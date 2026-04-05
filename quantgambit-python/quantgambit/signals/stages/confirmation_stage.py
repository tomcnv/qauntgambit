"""
ConfirmationStage - Validate CandidateSignals using flow and trend signals.

This stage validates CandidateSignal objects using flow_rotation and trend_bias
from AMT levels. It converts confirmed candidates to StrategySignal objects
and records predicate-level failures for diagnostics.

Requirement 4.6: Confirmation_Stage SHALL validate candidates using flow_rotation,
orderflow alignment, and trend bounds.

Requirement 4.7: When a candidate passes confirmation, the Confirmation_Stage
SHALL convert it to a StrategySignal with SL/TP prices.

Requirement 4.10: When a candidate fails confirmation, the System SHALL increment
confirm_reject_count for that strategy AND log the specific failure reason.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional, TYPE_CHECKING

from quantgambit.signals.pipeline import Stage, StageContext, StageResult
from quantgambit.deeptrader_core.types import CandidateSignal, StrategySignal
from quantgambit.observability.logger import log_info
from quantgambit.signals.confirmation import ConfirmationPolicyEngine
from quantgambit.signals.confirmation.evidence import (
    evaluate_flow,
    evaluate_trend,
    get_field,
    normalize_side,
)

if TYPE_CHECKING:
    from quantgambit.signals.stages.amt_calculator import AMTLevels


@dataclass
class ConfirmationConfig:
    """
    Configuration for signal confirmation.
    
    Attributes:
        min_flow_magnitude: Minimum |flow_rotation| for reversal confirmation
        max_adverse_trend: Maximum trend bias against trade direction
        require_flow_sign_match: Whether flow direction must match trade side
        default_size: Default position size when account state unavailable
        risk_per_trade_pct: Risk percentage per trade for sizing
    """
    min_flow_magnitude: float = 0.5  # Minimum |flow_rotation| for reversal
    max_adverse_trend: float = 0.7   # Max trend bias against trade
    require_flow_sign_match: bool = True
    default_size: float = 0.01  # Default position size
    risk_per_trade_pct: float = 0.6  # Risk percentage per trade


class ConfirmationStage(Stage):
    """
    Validate CandidateSignals using flow and trend signals.
    
    This stage:
    1. Gets candidate from ctx.data["candidate_signal"]
    2. Validates using flow_rotation and trend_bias from AMT levels
    3. Converts confirmed candidates to StrategySignal
    4. Records predicate-level failures for diagnostics
    
    Requirement 4.6: Validate candidates using flow_rotation and trend bounds
    Requirement 4.7: Convert confirmed candidates to StrategySignal
    Requirement 4.10: Record predicate-level failures
    
    Attributes:
        name: Stage name for identification ("confirmation")
        config: ConfirmationConfig with validation parameters
        _diagnostics: Optional StrategyDiagnostics for recording failures
    """
    name = "confirmation"
    
    def __init__(
        self,
        config: Optional[ConfirmationConfig] = None,
        diagnostics: Optional["StrategyDiagnostics"] = None,
        policy_engine: Optional[ConfirmationPolicyEngine] = None,
    ):
        """
        Initialize the confirmation stage.
        
        Args:
            config: Configuration for validation. If None, uses defaults.
            diagnostics: Optional StrategyDiagnostics for recording failures.
        """
        self.config = config or ConfirmationConfig()
        self.diagnostics = diagnostics
        self.policy_engine = policy_engine or ConfirmationPolicyEngine()
        self._trace_enabled = os.getenv("CONFIRMATION_TRACE", "").lower() in {"1", "true"}
        self._min_flow_magnitude_by_symbol = self._parse_symbol_float_map(
            os.getenv("CONFIRMATION_POLICY_MIN_FLOW_MAGNITUDE_BY_SYMBOL", "")
        )
    
    async def run(self, ctx: StageContext) -> StageResult:
        """
        Validate candidate and convert to StrategySignal if confirmed.
        
        This method:
        1. Gets candidate from ctx.data["candidate_signal"]
        2. Validates using flow_rotation and trend_bias
        3. Converts to StrategySignal if confirmed
        4. Records failures for diagnostics
        
        Args:
            ctx: Stage context containing symbol, data dict, and other state
        
        Returns:
            StageResult.CONTINUE if confirmed or no candidate
            StageResult.REJECT if candidate fails confirmation
        """
        symbol = ctx.symbol
        
        # Get candidate from context. In the live pipeline this is typically absent,
        # so we also support validating the existing ctx.signal directly.
        candidate: Optional[CandidateSignal] = ctx.data.get("candidate_signal")
        
        # Get AMT levels for flow_rotation and trend_bias
        amt_levels = self._resolve_amt_levels(ctx)
        
        if amt_levels is None:
            # No AMT levels - cannot confirm
            if candidate is None and ctx.signal is None:
                return StageResult.CONTINUE
            if candidate is not None:
                self._record_failure(ctx, candidate, "fail_data", "no_amt_levels")
            ctx.rejection_reason = "no_amt_levels_for_confirmation"
            ctx.rejection_stage = self.name
            return StageResult.REJECT
        
        # Extract flow and trend signals
        # Try to get flow_rotation and trend_bias from AMT levels
        flow = getattr(amt_levels, "flow_rotation", None)
        trend = getattr(amt_levels, "trend_bias", None)
        
        # Fallback to rotation_factor if flow_rotation not available
        if flow is None:
            flow = getattr(amt_levels, "rotation_factor", 0.0)
        if trend is None:
            trend = 0.0

        # Signal-first path: validate existing signal and continue.
        if candidate is None:
            return self._validate_existing_signal(ctx, flow=float(flow), trend=float(trend))
        
        legacy_valid, legacy_reason = self._legacy_validate_candidate(
            candidate,
            flow=float(flow),
            trend=float(trend),
            symbol=ctx.symbol,
        )
        unified_result = self.policy_engine.evaluate_entry(
            side=candidate.side,
            flow=float(flow),
            trend=float(trend),
            market_context=ctx.data.get("market_context") or {},
            strategy_id=candidate.strategy_id,
            requires_flow_reversal=bool(candidate.requires_flow_reversal),
            required_flow_direction=candidate.flow_direction_required,
            max_adverse_trend=float(candidate.max_adverse_trend_bias),
        )
        confirmed, reject_reason = self._resolve_decision(
            ctx=ctx,
            symbol=symbol,
            strategy_id=candidate.strategy_id,
            side=candidate.side,
            legacy_confirm=legacy_valid,
            legacy_reason=legacy_reason,
            unified_confirm=unified_result.confirm,
            unified_reasons=unified_result.decision_reason_codes,
            unified_confidence=unified_result.confidence,
            decision_context="entry",
        )
        if not confirmed:
            failure_type = "fail_guard"
            if "flow_" in reject_reason:
                failure_type = "fail_flow"
            elif "trend_" in reject_reason:
                failure_type = "fail_trend"
            self._record_failure(ctx, candidate, failure_type, reject_reason)
            ctx.rejection_reason = reject_reason
            ctx.rejection_stage = self.name
            return StageResult.REJECT
        
        # Confirmation passed - convert to StrategySignal
        mid_price = ctx.data.get("mid_price")
        if mid_price is None:
            # Try to get from market_context or features
            market_context = ctx.data.get("market_context") or {}
            features = ctx.data.get("features") or {}
            mid_price = market_context.get("mid_price") or features.get("price") or candidate.entry_price
        
        # Normalize candidate to have both distance and price
        normalized = candidate.normalize(mid_price)
        
        # Calculate position size
        size = self._calculate_size(normalized, ctx)
        
        # Build confirmation reason
        confirmation_reason = (
            f"flow={flow:.2f},trend={trend:.2f},"
            f"policy_conf={unified_result.confidence:.2f}"
        )
        
        # Convert to StrategySignal
        try:
            signal = normalized.to_strategy_signal(
                size=size,
                confirmation_reason=confirmation_reason,
            )
        except ValueError as e:
            # SL/TP prices not set - this shouldn't happen after normalize()
            self._record_failure(ctx, candidate, "fail_data", str(e))
            ctx.rejection_reason = f"conversion_error: {e}"
            ctx.rejection_stage = self.name
            return StageResult.REJECT
        
        # Set signal in context
        ctx.signal = signal
        ctx.data["confirmed_signal"] = signal
        setattr(signal, "confirmation_version", unified_result.version)
        setattr(signal, "confirmation_mode", unified_result.mode)
        setattr(signal, "confirmation_confidence", unified_result.confidence)
        setattr(signal, "confirmation_votes", unified_result.evidence_votes)
        setattr(signal, "confirmation_failed_guards", unified_result.failed_hard_guards)
        setattr(signal, "confirmation_reason_codes", unified_result.decision_reason_codes)
        
        # Record confirmation success
        if self.diagnostics:
            self.diagnostics.record_confirm(candidate.strategy_id)
        
        log_info(
            "confirmation_passed",
            symbol=symbol,
            strategy_id=candidate.strategy_id,
            side=candidate.side,
            setup_score=round(candidate.setup_score, 3),
            flow=round(flow, 2),
            trend=round(trend, 2),
            entry_price=round(signal.entry_price, 2),
            stop_loss=round(signal.stop_loss, 2),
            take_profit=round(signal.take_profit, 2),
            size=round(size, 6),
        )
        
        return StageResult.CONTINUE

    def _resolve_amt_levels(self, ctx: StageContext):
        amt_levels = ctx.data.get("amt_levels")
        if amt_levels is not None:
            return amt_levels

        features = ctx.data.get("features") or {}
        market_context = ctx.data.get("market_context") or {}

        poc = features.get("point_of_control")
        if poc is None:
            poc = market_context.get("point_of_control")
        vah = features.get("value_area_high")
        if vah is None:
            vah = market_context.get("value_area_high")
        val = features.get("value_area_low")
        if val is None:
            val = market_context.get("value_area_low")
        position_in_value = features.get("position_in_value") or market_context.get("position_in_value")

        flow_rotation = features.get("flow_rotation")
        if flow_rotation is None:
            flow_rotation = market_context.get("flow_rotation")
        if flow_rotation is None:
            flow_rotation = features.get("rotation_factor")
        if flow_rotation is None:
            flow_rotation = market_context.get("rotation_factor")

        trend_bias = features.get("trend_bias")
        if trend_bias is None:
            trend_bias = market_context.get("trend_bias")

        rotation_factor = features.get("rotation_factor")
        if rotation_factor is None:
            rotation_factor = market_context.get("rotation_factor")

        if (
            poc is None
            or vah is None
            or val is None
            or position_in_value is None
            or flow_rotation is None
        ):
            return None

        from quantgambit.signals.stages.amt_calculator import AMTLevels

        fallback_levels = AMTLevels(
            point_of_control=float(poc),
            value_area_high=float(vah),
            value_area_low=float(val),
            position_in_value=str(position_in_value),
            distance_to_poc=float(
                features.get("distance_to_poc")
                if features.get("distance_to_poc") is not None
                else market_context.get("distance_to_poc", 0.0)
            ),
            distance_to_vah=float(
                features.get("distance_to_vah")
                if features.get("distance_to_vah") is not None
                else market_context.get("distance_to_vah", 0.0)
            ),
            distance_to_val=float(
                features.get("distance_to_val")
                if features.get("distance_to_val") is not None
                else market_context.get("distance_to_val", 0.0)
            ),
            distance_to_poc_bps=float(
                features.get("distance_to_poc_bps")
                if features.get("distance_to_poc_bps") is not None
                else market_context.get("distance_to_poc_bps", 0.0)
            ),
            distance_to_vah_bps=float(
                features.get("distance_to_vah_bps")
                if features.get("distance_to_vah_bps") is not None
                else market_context.get("distance_to_vah_bps", 0.0)
            ),
            distance_to_val_bps=float(
                features.get("distance_to_val_bps")
                if features.get("distance_to_val_bps") is not None
                else market_context.get("distance_to_val_bps", 0.0)
            ),
            flow_rotation=float(flow_rotation),
            flow_rotation_raw=float(flow_rotation),
            trend_bias=float(trend_bias or 0.0),
            rotation_factor=float(rotation_factor if rotation_factor is not None else flow_rotation),
            candle_count=int(market_context.get("candle_count") or features.get("candle_count") or 0),
            calculation_ts=float(market_context.get("timestamp") or features.get("timestamp") or 0.0),
        )
        ctx.data["amt_levels"] = fallback_levels
        return fallback_levels

    def _validate_existing_signal(self, ctx: StageContext, flow: float, trend: float) -> StageResult:
        signal = ctx.signal
        if signal is None:
            if self._trace_enabled:
                log_info("confirmation_no_candidate_or_signal", symbol=ctx.symbol)
            return StageResult.CONTINUE

        side = normalize_side(get_field(signal, "side"))
        strategy_id = get_field(signal, "strategy_id") or "unknown"

        is_exit = bool(
            get_field(signal, "is_exit_signal")
            or get_field(signal, "reduce_only")
        )
        if is_exit:
            return StageResult.CONTINUE

        if side not in {"long", "short"}:
            return StageResult.CONTINUE

        min_flow_magnitude = self._min_flow_magnitude_for_symbol(ctx.symbol)
        requires_flow_reversal = self._strategy_requires_flow_reversal(strategy_id)
        if requires_flow_reversal:
            flow_valid, flow_reason, _ = evaluate_flow(
                side=side,
                flow=flow,
                min_magnitude=min_flow_magnitude,
            )
        else:
            flow_valid, flow_reason = True, "flow_optional"
        trend_valid, trend_reason, _ = evaluate_trend(
            side=side,
            trend=trend,
            max_adverse=self.config.max_adverse_trend,
        )
        legacy_valid = flow_valid and trend_valid
        legacy_reason = flow_reason if not flow_valid else trend_reason

        unified_result = self.policy_engine.evaluate_entry(
            side=side,
            flow=flow,
            trend=trend,
            market_context=ctx.data.get("market_context") or {},
            strategy_id=strategy_id,
            requires_flow_reversal=requires_flow_reversal,
            required_flow_direction=None,
            max_adverse_trend=self.config.max_adverse_trend,
        )
        confirmed, reject_reason = self._resolve_decision(
            ctx=ctx,
            symbol=ctx.symbol,
            strategy_id=strategy_id,
            side=side,
            legacy_confirm=legacy_valid,
            legacy_reason=legacy_reason,
            unified_confirm=unified_result.confirm,
            unified_reasons=unified_result.decision_reason_codes,
            unified_confidence=unified_result.confidence,
            decision_context="entry_live_signal",
        )
        if not confirmed:
            failure_type = "fail_flow" if "flow_" in reject_reason else "fail_trend"
            if "guard_" in reject_reason:
                failure_type = "fail_guard"
            ctx.rejection_reason = reject_reason
            ctx.rejection_stage = self.name
            self._record_live_signal_failure(ctx, strategy_id, side, failure_type, reject_reason)
            return StageResult.REJECT

        if isinstance(signal, dict):
            signal["confirmation_version"] = unified_result.version
            signal["confirmation_mode"] = unified_result.mode
            signal["confirmation_confidence"] = unified_result.confidence
            signal["confirmation_votes"] = unified_result.evidence_votes
            signal["confirmation_failed_guards"] = unified_result.failed_hard_guards
            signal["confirmation_reason_codes"] = unified_result.decision_reason_codes
        else:
            setattr(signal, "confirmation_version", unified_result.version)
            setattr(signal, "confirmation_mode", unified_result.mode)
            setattr(signal, "confirmation_confidence", unified_result.confidence)
            setattr(signal, "confirmation_votes", unified_result.evidence_votes)
            setattr(signal, "confirmation_failed_guards", unified_result.failed_hard_guards)
            setattr(signal, "confirmation_reason_codes", unified_result.decision_reason_codes)

        log_info(
            "confirmation_passed_signal",
            symbol=ctx.symbol,
            strategy_id=strategy_id,
            side=side,
            flow=round(flow, 2),
            trend=round(trend, 2),
        )
        return StageResult.CONTINUE

    @staticmethod
    def _strategy_requires_flow_reversal(strategy_id: Optional[str]) -> bool:
        strategy = str(strategy_id or "").strip().lower()
        if strategy in {"spot_dip_accumulator", "spot_mean_reversion", "mean_reversion_fade"}:
            return False
        return True

    def _legacy_validate_candidate(
        self,
        candidate: CandidateSignal,
        flow: float,
        trend: float,
        symbol: Optional[str] = None,
    ) -> tuple[bool, str]:
        min_flow_magnitude = self._min_flow_magnitude_for_symbol(symbol)
        if candidate.requires_flow_reversal:
            flow_ok, flow_reason, _ = evaluate_flow(
                side=candidate.side,
                flow=flow,
                min_magnitude=min_flow_magnitude,
                required_direction=candidate.flow_direction_required,
            )
            if not flow_ok:
                return False, flow_reason
        trend_ok, trend_reason, _ = evaluate_trend(
            side=candidate.side,
            trend=trend,
            max_adverse=float(candidate.max_adverse_trend_bias),
        )
        if not trend_ok:
            return False, trend_reason
        return True, ""

    def _min_flow_magnitude_for_symbol(self, symbol: Optional[str]) -> float:
        if symbol:
            override = self._min_flow_magnitude_by_symbol.get(str(symbol).upper())
            if override is not None:
                return override
        return float(self.config.min_flow_magnitude)

    @staticmethod
    def _parse_symbol_float_map(raw: str) -> dict[str, float]:
        out: dict[str, float] = {}
        if not raw:
            return out
        for item in raw.split(","):
            token = item.strip()
            if not token or ":" not in token:
                continue
            symbol, value_text = token.split(":", 1)
            symbol = symbol.strip().upper()
            if not symbol:
                continue
            try:
                value = float(value_text.strip())
            except (TypeError, ValueError):
                continue
            out[symbol] = max(0.0, min(1.0, value))
        return out

    def _resolve_decision(
        self,
        *,
        ctx: Optional[StageContext],
        symbol: str,
        strategy_id: str,
        side: str,
        legacy_confirm: bool,
        legacy_reason: str,
        unified_confirm: bool,
        unified_reasons: list[str],
        unified_confidence: float,
        decision_context: str,
    ) -> tuple[bool, str]:
        mode = self.policy_engine.config.mode if self.policy_engine.config.enabled else "legacy"
        if not self.policy_engine.config.enabled:
            final_confirm = legacy_confirm
            final_reason = "" if legacy_confirm else legacy_reason
        elif mode == "shadow":
            final_confirm = legacy_confirm
            final_reason = "" if legacy_confirm else legacy_reason
        else:
            final_confirm = bool(legacy_confirm and unified_confirm)
            if not unified_confirm:
                final_reason = unified_reasons[0] if unified_reasons else "confirmation_rejected"
            elif not legacy_confirm:
                final_reason = legacy_reason or "confirmation_rejected"
            else:
                final_reason = ""

        diff = legacy_confirm != unified_confirm
        if diff or self._trace_enabled:
            log_info(
                "confirmation_policy_compare",
                symbol=symbol,
                strategy_id=strategy_id,
                side=side,
                decision_context=decision_context,
                mode=mode,
                legacy_decision=legacy_confirm,
                unified_decision=unified_confirm,
                unified_confidence=round(unified_confidence, 3),
                diff_reason="decision_mismatch" if diff else "none",
            )
        if ctx is not None and isinstance(ctx.data, dict):
            comparisons = ctx.data.get("confirmation_shadow_comparisons")
            if not isinstance(comparisons, list):
                comparisons = []
                ctx.data["confirmation_shadow_comparisons"] = comparisons
            comparisons.append(
                {
                    "source_stage": self.name,
                    "decision_context": decision_context,
                    "mode": mode,
                    "legacy_decision": bool(legacy_confirm),
                    "unified_decision": bool(unified_confirm),
                    "final_decision": bool(final_confirm),
                    "diff": bool(diff),
                    "diff_reason": "decision_mismatch" if diff else "none",
                    "unified_confidence": float(unified_confidence),
                    "strategy_id": strategy_id,
                    "side": side,
                }
            )
        return final_confirm, final_reason
    
    def _calculate_size(
        self,
        candidate: CandidateSignal,
        ctx: StageContext,
    ) -> float:
        """
        Calculate position size for the trade.
        
        Uses account state if available, otherwise uses default size.
        
        Args:
            candidate: Normalized CandidateSignal with SL/TP prices
            ctx: Stage context with account state
            
        Returns:
            Position size
        """
        # Try to get account state
        account = ctx.data.get("account_state")
        
        if account is None:
            return self.config.default_size
        
        # Get equity from account
        equity = getattr(account, "equity", None)
        if equity is None or equity <= 0:
            return self.config.default_size
        
        # Calculate size based on stop loss distance
        if candidate.sl_price is None:
            return self.config.default_size
        
        stop_distance = abs(candidate.entry_price - candidate.sl_price)
        if stop_distance <= 0:
            return self.config.default_size
        
        # Size = (equity * risk_pct) / stop_distance
        risk_amount = equity * (self.config.risk_per_trade_pct / 100)
        size = risk_amount / stop_distance
        
        return size
    
    def _record_failure(
        self,
        ctx: StageContext,
        candidate: CandidateSignal,
        failure_type: str,
        detail: str,
    ) -> None:
        """
        Record a predicate-level failure for diagnostics.
        
        Requirement 4.10: When a candidate fails confirmation, the System SHALL
        increment confirm_reject_count for that strategy AND log the specific
        failure reason.
        
        Args:
            ctx: Stage context
            candidate: CandidateSignal that failed
            failure_type: Type of failure (e.g., "fail_flow", "fail_trend")
            detail: Detailed failure reason
        """
        if self.diagnostics:
            self.diagnostics.record_predicate_failure(candidate.strategy_id, failure_type)
        
        log_info(
            "confirmation_failed",
            symbol=ctx.symbol,
            strategy_id=candidate.strategy_id,
            side=candidate.side,
            failure_type=failure_type,
            detail=detail,
            setup_score=round(candidate.setup_score, 3),
        )

    def _record_live_signal_failure(
        self,
        ctx: StageContext,
        strategy_id: str,
        side: str,
        failure_type: str,
        detail: str,
    ) -> None:
        if self.diagnostics:
            self.diagnostics.record_predicate_failure(strategy_id, failure_type)

        log_info(
            "confirmation_failed_signal",
            symbol=ctx.symbol,
            strategy_id=strategy_id,
            side=side,
            failure_type=failure_type,
            detail=detail,
        )
