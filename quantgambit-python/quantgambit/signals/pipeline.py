"""Stage-based decision pipeline with telemetry hooks."""

from __future__ import annotations

import time
import os
from dataclasses import dataclass, asdict
from enum import Enum
from typing import List, Optional, Dict, Any, TYPE_CHECKING, Union, Tuple

from quantgambit.observability.telemetry import TelemetryContext, TelemetryPipeline
from quantgambit.observability.logger import log_info, log_warning, log_error
from quantgambit.observability.schemas import decision_payload
from quantgambit.deeptrader_core.types import ExitType, ExitDecision
from quantgambit.deeptrader_core.strategies.chessboard import get_profile_registry
from quantgambit.risk.fee_model import FeeModel, FeeAwareExitCheck
from quantgambit.ingest.schemas import coerce_float
from quantgambit.signals.confirmation import ConfirmationPolicyEngine
from quantgambit.signals.prediction_audit import build_directional_fields, normalize_side

if TYPE_CHECKING:
    from quantgambit.config.trading_mode import TradingModeManager
    from quantgambit.observability.blocked_signal_telemetry import BlockedSignalTelemetry
    from quantgambit.signals.stages.minimum_hold_time import MinimumHoldTimeEnforcer
    from quantgambit.signals.services.strategy_diagnostics import StrategyDiagnostics


# =============================================================================
# Stage Ordering Constants (Requirement 8)
# =============================================================================
# Canonical stage order for the signal pipeline.
# Pipeline SHALL execute stages in this order:
# DataReadiness → AMTCalculator → GlobalGate → ProfileRouter → Strategy →
# Arbitration → Confirmation → EVGate → ExecutionFeasibility → Execution
#
# Note: PositionEvaluation and RiskCheck are special stages that can appear
# at different positions based on the pipeline configuration.

CANONICAL_STAGE_ORDER: Tuple[str, ...] = (
    "data_readiness",
    "amt_calculator",
    "global_gate",
    "profile_routing",  # ProfileRouter stage name
    "signal_check",     # Strategy/Signal stage name
    "arbitration",
    "confirmation",
    "ev_gate",
    "execution_feasibility",
    "execution",
)

# Stages that must appear before EVGate (Requirement 8.8)
# EVGate SHALL NOT run before Strategy has produced a signal
STAGES_REQUIRED_BEFORE_EV_GATE: Tuple[str, ...] = (
    "signal_check",  # Strategy must produce signal before EVGate
)

# Optional stages that can be omitted but should maintain relative order
OPTIONAL_STAGES: Tuple[str, ...] = (
    "arbitration",
    "confirmation",
    "execution_feasibility",
)

# Special stages that have flexible positioning
FLEXIBLE_STAGES: Tuple[str, ...] = (
    "position_evaluation",
    "risk_check",
    "prediction_gate",
)

# Default profile ID when ProfileRouter is missing (Requirement 8.12)
DEFAULT_PROFILE_ID: str = "default"

# Stage data contract checks (runtime validation)
STAGE_REQUIRED_DATA_KEYS: Dict[str, Tuple[str, ...]] = {
    "data_readiness": ("features", "market_context"),
    "amt_calculator": ("features", "market_context"),
    "symbol_characteristics": ("features", "market_context"),
    "snapshot_builder": ("features", "market_context"),
    "global_gate": ("market_context",),
    "profile_routing": ("market_context",),
    "position_evaluation": ("market_context",),
    "cooldown": ("market_context",),
    "prediction_gate": ("market_context",),
    "signal_check": ("features", "market_context"),
    "confirmation": ("market_context",),
    "strategy_trend_alignment": ("market_context",),
    "model_direction_alignment": ("prediction",),
    "cost_data_quality": ("features", "market_context"),
    "ev_gate": ("features", "market_context", "prediction"),
    "fee_aware_entry": ("features", "market_context"),
    "session_filter": ("market_context",),
    "confidence_position_sizer": ("prediction",),
    "ev_position_sizer": ("ev_gate_result",),
    "candidate_generation": ("snapshot",),
    "candidate_veto": ("candidate", "snapshot"),
    "risk_check": ("signal",),
    "execution": ("signal",),
}

STAGE_POST_REQUIRED_KEYS: Dict[str, Tuple[str, ...]] = {
    "profile_routing": ("profile_id",),
    "signal_check": ("signal",),
    "candidate_generation": ("candidate",),
}


class ConfigurationError(Exception):
    """Raised when pipeline configuration is invalid."""
    pass


def signal_to_dict(signal: Any) -> Dict[str, Any]:
    """
    Convert a signal to a dictionary.
    
    Handles StrategySignal dataclass, dict, or any object with __dict__.
    Returns empty dict if signal is None or cannot be converted.
    
    Args:
        signal: The signal to convert (StrategySignal, dict, or other object)
        
    Returns:
        Dictionary representation of the signal
    """
    if signal is None:
        return {}
    if isinstance(signal, dict):
        return signal
    if hasattr(signal, '__dataclass_fields__'):
        return asdict(signal)
    if hasattr(signal, '__dict__'):
        return signal.__dict__
    return {}


def _parse_symbol_float_map(raw: Optional[str]) -> Dict[str, float]:
    """
    Parse `SYMBOL:value` pairs from env/config strings.

    Supported separators between pairs: comma/semicolon.
    Example: "SOLUSDT:0.16,ETHUSDT:0.18"
    """
    if not raw:
        return {}
    result: Dict[str, float] = {}
    normalized = raw.replace(";", ",")
    for part in normalized.split(","):
        token = part.strip()
        if not token or ":" not in token:
            continue
        symbol_raw, value_raw = token.split(":", 1)
        symbol = symbol_raw.strip().upper()
        if not symbol:
            continue
        try:
            value = float(value_raw.strip())
        except (TypeError, ValueError):
            continue
        if value < 0.0:
            value = 0.0
        if value > 1.0:
            value = 1.0
        result[symbol] = value
    return result


def _parse_key_float_map(raw: Optional[str]) -> Dict[str, float]:
    """
    Parse `KEY:value` pairs from env/config strings.

    Supported separators between pairs: comma/semicolon.
    Unlike `_parse_symbol_float_map`, values are not clamped to [0, 1].
    """
    if not raw:
        return {}
    result: Dict[str, float] = {}
    normalized = raw.replace(";", ",")
    for part in normalized.split(","):
        token = part.strip()
        if not token or ":" not in token:
            continue
        key_raw, value_raw = token.split(":", 1)
        key = key_raw.strip().upper()
        if not key:
            continue
        try:
            value = float(value_raw.strip())
        except (TypeError, ValueError):
            continue
        result[key] = value
    return result


def _resolve_action_policy_probabilities(
    prediction: Dict[str, Any],
) -> Optional[Dict[str, float]]:
    """
    Resolve action-policy probabilities from prediction payloads.

    For action-conditional contracts (`p_long_win`, `p_short_win`), use values directly.
    For multiclass directional contracts (`up/down/flat`), compute conditional side win
    probabilities over directional mass so high `p_flat` does not suppress side conviction.
    """
    p_long = coerce_float(prediction.get("p_long_win"))
    p_short = coerce_float(prediction.get("p_short_win"))
    if p_long is None or p_short is None:
        probs = prediction.get("probs") if isinstance(prediction.get("probs"), dict) else {}
        p_long = coerce_float(p_long if p_long is not None else probs.get("p_long_win"))
        p_short = coerce_float(p_short if p_short is not None else probs.get("p_short_win"))
    if p_long is None or p_short is None:
        return None

    prediction_contract = str(prediction.get("prediction_contract") or "").strip().lower()
    if prediction_contract == "action_conditional_pnl_winprob":
        p_star = max(p_long, p_short)
        margin = abs(p_long - p_short)
        return {
            "p_long_raw": p_long,
            "p_short_raw": p_short,
            "p_long_eval": p_long,
            "p_short_eval": p_short,
            "p_star": p_star,
            "margin": margin,
            "directional_mass": 1.0,
            "normalized": 0.0,
        }

    directional_mass = max(0.0, p_long + p_short)
    if directional_mass <= 1e-9:
        return {
            "p_long_raw": p_long,
            "p_short_raw": p_short,
            "p_long_eval": 0.5,
            "p_short_eval": 0.5,
            "p_star": 0.5,
            "margin": 0.0,
            "directional_mass": directional_mass,
            "normalized": 1.0,
        }

    p_long_eval = p_long / directional_mass
    p_short_eval = p_short / directional_mass
    p_star = max(p_long_eval, p_short_eval)
    margin = abs(p_long_eval - p_short_eval)
    return {
        "p_long_raw": p_long,
        "p_short_raw": p_short,
        "p_long_eval": p_long_eval,
        "p_short_eval": p_short_eval,
        "p_star": p_star,
        "margin": margin,
        "directional_mass": directional_mass,
        "normalized": 1.0,
    }


def _resolve_symbol_session_float_override(
    symbol: str,
    session: Optional[str],
    base_value: float,
    by_symbol_env: str,
    by_symbol_session_env: str,
) -> float:
    symbol_key = (symbol or "").strip().upper()
    session_key = (session or "").strip().upper()
    resolved = float(base_value)

    by_symbol = _parse_key_float_map(os.getenv(by_symbol_env, ""))
    if symbol_key in by_symbol:
        resolved = float(by_symbol[symbol_key])

    by_symbol_session = _parse_key_float_map(os.getenv(by_symbol_session_env, ""))
    composite_key = f"{symbol_key}@{session_key}" if symbol_key and session_key else ""
    if composite_key and composite_key in by_symbol_session:
        resolved = float(by_symbol_session[composite_key])

    return resolved


class StageResult(str, Enum):
    CONTINUE = "CONTINUE"
    REJECT = "REJECT"
    COMPLETE = "COMPLETE"
    SKIP_TO_EXECUTION = "SKIP_TO_EXECUTION"  # Used when exit signal generated


@dataclass
class StageContext:
    symbol: str
    data: dict
    rejection_reason: Optional[str] = None
    rejection_stage: Optional[str] = None
    rejection_detail: Optional[dict] = None
    profile_id: Optional[str] = None
    signal: Optional[dict] = None
    stage_trace: Optional[list[dict]] = None


class Stage:
    name = "base"

    async def run(self, ctx: StageContext) -> StageResult:
        return StageResult.CONTINUE


# =============================================================================
# Stage Ordering Validation Functions (Requirement 8.9, 8.10, 8.11)
# =============================================================================

def validate_stage_ordering(stages: List[Stage]) -> Tuple[bool, List[str]]:
    """
    Validate that stages are in the correct order.
    
    Implements Requirement 8.9: Pipeline config SHALL validate stage ordering at initialization.
    
    Args:
        stages: List of Stage objects to validate
        
    Returns:
        Tuple of (is_valid, list_of_errors)
    """
    errors = []
    stage_names = [s.name for s in stages]
    
    # Build position map for canonical stages
    canonical_positions = {name: i for i, name in enumerate(CANONICAL_STAGE_ORDER)}
    
    # Check relative ordering of canonical stages
    last_canonical_pos = -1
    last_canonical_name = None
    
    for stage_name in stage_names:
        if stage_name in FLEXIBLE_STAGES:
            # Flexible stages can appear anywhere
            continue
            
        if stage_name in canonical_positions:
            pos = canonical_positions[stage_name]
            if pos < last_canonical_pos:
                errors.append(
                    f"Stage '{stage_name}' (position {pos}) appears after "
                    f"'{last_canonical_name}' (position {last_canonical_pos}) - "
                    f"violates canonical order"
                )
            else:
                last_canonical_pos = pos
                last_canonical_name = stage_name
    
    # Check that EVGate doesn't run before Strategy (Requirement 8.8)
    ev_gate_idx = None
    signal_check_idx = None
    
    for i, name in enumerate(stage_names):
        if name == "ev_gate":
            ev_gate_idx = i
        if name == "signal_check":
            signal_check_idx = i
    
    if ev_gate_idx is not None and signal_check_idx is not None:
        if ev_gate_idx < signal_check_idx:
            errors.append(
                f"EVGate (index {ev_gate_idx}) runs before Strategy/SignalCheck "
                f"(index {signal_check_idx}) - EVGate requires signal from Strategy"
            )
    
    return len(errors) == 0, errors


def check_profile_router_present(stages: List[Stage]) -> Tuple[bool, Optional[str]]:
    """
    Check if ProfileRouter is present in the pipeline.
    
    Implements Requirement 8.12: IF ProfileRouter is missing from stage list
    THEN Pipeline SHALL log a warning (not error) and use default profile.
    
    Args:
        stages: List of Stage objects
        
    Returns:
        Tuple of (is_present, warning_message_if_missing)
    """
    stage_names = [s.name for s in stages]
    
    if "profile_routing" not in stage_names:
        return False, (
            "ProfileRouter stage is missing from pipeline. "
            f"Using default profile '{DEFAULT_PROFILE_ID}'. "
            "Add ProfileRoutingStage for dynamic profile selection."
        )
    
    return True, None


def log_stage_execution_order(stages: List[Stage]) -> None:
    """
    Log the stage execution order at startup.
    
    Implements Requirement 8.11: Pipeline SHALL log stage execution order
    at startup for verification.
    
    Args:
        stages: List of Stage objects
    """
    stage_names = [s.name for s in stages]
    stage_order_str = " → ".join(stage_names)
    
    log_info(
        "pipeline_stage_order",
        stage_count=len(stages),
        stage_order=stage_order_str,
        stages=stage_names,
    )


def get_canonical_stage_order() -> Tuple[str, ...]:
    """
    Get the canonical stage order for reference.
    
    Returns:
        Tuple of stage names in canonical order
    """
    return CANONICAL_STAGE_ORDER


class DataReadinessStage(Stage):
    name = "data_readiness"

    async def run(self, ctx: StageContext) -> StageResult:
        features = ctx.data.get("features") or {}
        if not features:
            ctx.rejection_reason = "no_features"
            ctx.rejection_stage = self.name
            ctx.rejection_detail = {"features_present": False}
            return StageResult.REJECT
        return StageResult.CONTINUE


class PositionEvaluationStage(Stage):
    """
    Evaluate existing open positions for potential exit signals.
    
    This stage runs BEFORE entry signal generation to prioritize exits.
    If a position exists for the current symbol and market conditions
    warrant an exit, it generates a CLOSE_LONG/CLOSE_SHORT signal.
    
    Exit Classification:
    - SAFETY exits: Hard stop, liquidation proximity, data failure. Ignore min_hold.
    - INVALIDATION exits: Orderflow flip, regime change, trend reversal. Respect min_hold.
    
    Exit conditions evaluated:
    1. [SAFETY] Hard stop hit
    2. [SAFETY] Price near liquidation
    3. [SAFETY] Data staleness while in position
    4. [INVALIDATION] Trend reversal against position
    5. [INVALIDATION] Orderflow reversal
    6. [INVALIDATION] Price at key levels
    7. [INVALIDATION] Volatility spike (risk-off)
    8. [INVALIDATION] Underwater position with adverse conditions
    9. [INVALIDATION] Time-based degradation
    """
    name = "position_evaluation"

    def __init__(
        self,
        min_confirmations_for_exit: int = 2,  # Require 2 confirmations to exit (was 1 - too trigger happy)
        exit_underwater_threshold_pct: float = -0.3,  # -0.3% underwater triggers stricter evaluation (was -1%)
        max_underwater_hold_sec: float = 600.0,  # 10 minutes max for underwater positions (was 1 hour!)
        min_hold_time_sec: float = 30.0,  # Minimum hold time before INVALIDATION exits (fallback)
        # Safety exit thresholds
        liquidation_proximity_pct: float = 0.5,  # Exit if within 0.5% of liquidation
        hard_stop_pct: float = 2.0,  # Emergency exit at 2% loss
        max_data_stale_sec: float = 5.0,  # Max data staleness while in position
        # Fee-aware exit parameters
        fee_model: Optional[FeeModel] = None,  # Fee model for breakeven calculations
        min_profit_buffer_bps: float = 5.0,  # Minimum profit above breakeven (5 bps default)
        fee_check_grace_period_sec: float = 30.0,  # Grace period for time budget exits
        # Trading mode manager for mode-aware parameters
        trading_mode_manager: Optional["TradingModeManager"] = None,
        # Blocked signal telemetry for fee check blocking
        blocked_signal_telemetry: Optional["BlockedSignalTelemetry"] = None,
        # Minimum hold time enforcer for strategy-specific hold times (Requirement 3)
        min_hold_enforcer: Optional["MinimumHoldTimeEnforcer"] = None,
        confirmation_policy_engine: Optional[ConfirmationPolicyEngine] = None,
    ):
        self.min_confirmations_for_exit = min_confirmations_for_exit
        self.exit_underwater_threshold_pct = exit_underwater_threshold_pct
        self.max_underwater_hold_sec = max_underwater_hold_sec
        self.min_hold_time_sec = min_hold_time_sec
        self.liquidation_proximity_pct = liquidation_proximity_pct
        self.hard_stop_pct = hard_stop_pct
        self.max_data_stale_sec = max_data_stale_sec
        # Fee-aware exit configuration
        self.fee_model = fee_model
        self.min_profit_buffer_bps = min_profit_buffer_bps
        self.fee_check_grace_period_sec = fee_check_grace_period_sec
        # Trading mode manager
        self._trading_mode_manager = trading_mode_manager
        # Blocked signal telemetry
        self._blocked_signal_telemetry = blocked_signal_telemetry
        # Minimum hold time enforcer (Requirement 3) - lazy import to avoid circular dependency
        if min_hold_enforcer is not None:
            self._min_hold_enforcer = min_hold_enforcer
        else:
            from quantgambit.signals.stages.minimum_hold_time import MinimumHoldTimeEnforcer
            self._min_hold_enforcer = MinimumHoldTimeEnforcer()
        # Deterioration tracking per position (Requirement 7)
        self._deterioration_counters: Dict[str, int] = {}
        self._last_pnl: Dict[str, float] = {}
        self._confirmation_policy_engine = confirmation_policy_engine or ConfirmationPolicyEngine()
    
    def _get_mode_config(self, symbol: str):
        """Get mode-specific config for symbol."""
        if self._trading_mode_manager:
            return self._trading_mode_manager.get_config(symbol)
        return None
    
    def _has_deteriorated(self, position_key: str, current_pnl: float) -> bool:
        """Check if position P&L has worsened since last tick (Requirement 7.1)."""
        last_pnl = self._last_pnl.get(position_key)
        if last_pnl is None:
            return False
        return current_pnl < last_pnl
    
    def _update_deterioration(self, position_key: str, current_pnl: float) -> int:
        """Update deterioration counter and return current count (Requirement 7.2)."""
        if self._has_deteriorated(position_key, current_pnl):
            self._deterioration_counters[position_key] = self._deterioration_counters.get(position_key, 0) + 1
        else:
            # Reset on improvement
            self._deterioration_counters[position_key] = 0
        
        self._last_pnl[position_key] = current_pnl
        return self._deterioration_counters.get(position_key, 0)
    
    def get_hold_time_info(self, position: dict) -> dict:
        """
        Get comprehensive hold time information for display.
        
        Args:
            position: Position dict with 'strategy_id', 'opened_at' fields
            
        Returns:
            Dict with hold time details for dashboard display
            
        Requirement 3.6: Display time remaining until minimum hold time is satisfied
        """
        return self._min_hold_enforcer.get_hold_time_info(position)

    async def run(self, ctx: StageContext) -> StageResult:
        positions = ctx.data.get("positions") or []
        if not positions:
            if _exit_trace_enabled():
                log_info("position_eval_no_positions", symbol=ctx.symbol)
            return StageResult.CONTINUE
        
        symbol = ctx.symbol
        market_context = ctx.data.get("market_context") or {}
        
        # Find position for this symbol
        position = self._find_position_for_symbol(positions, symbol)
        if not position:
            if _exit_trace_enabled():
                # Log available positions for debugging symbol matching
                pos_symbols = [_get_attr(p, "symbol") for p in positions]
                log_info(
                    "position_eval_no_match",
                    symbol=symbol,
                    normalized=_normalize_symbol(symbol),
                    available_positions=pos_symbols,
                )
            return StageResult.CONTINUE
        
        # Log that we found a position to evaluate
        if _exit_trace_enabled():
            log_info(
                "position_eval_found",
                symbol=symbol,
                position_side=_get_attr(position, "side"),
                position_size=_get_attr(position, "size"),
                entry_price=_get_attr(position, "entry_price"),
            )
        
        # Evaluate exit conditions
        exit_signal = self._evaluate_exit(position, market_context, ctx)
        
        if exit_signal:
            ctx.signal = exit_signal
            _inject_signal_identity(ctx.signal, ctx)
            log_info(
                "position_exit_signal_generated",
                symbol=symbol,
                side=exit_signal.get("side"),
                reason=exit_signal.get("meta_reason"),
                confirmations=exit_signal.get("confirmations"),
            )
            # Skip directly to risk check and execution
            return StageResult.SKIP_TO_EXECUTION
        
        return StageResult.CONTINUE

    def _find_position_for_symbol(self, positions: list, symbol: str) -> Optional[Dict[str, Any]]:
        """Find an open position for the given symbol.
        
        Uses normalized symbol comparison to handle different exchange formats:
        - BTCUSDT, BTC/USDT:USDT, BTC-USDT-SWAP should all match
        """
        normalized_target = _normalize_symbol(symbol)
        for pos in positions:
            pos_symbol = _get_attr(pos, "symbol")
            if pos_symbol and _normalize_symbol(pos_symbol) == normalized_target:
                return pos
        return None

    def _evaluate_exit(
        self,
        position: Dict[str, Any],
        market_context: dict,
        ctx: StageContext,
    ) -> Optional[dict]:
        """
        Evaluate whether the position should be closed based on market conditions.
        Returns an exit signal dict if exit is warranted, None otherwise.
        
        Exit Classification:
        - SAFETY exits bypass min_hold: hard stop, liquidation, data failure
        - TIME BUDGET exits: time-to-work fail, max-hold exceeded (MFT scalping)
        - INVALIDATION exits respect min_hold: orderflow flip, regime change, etc.
        """
        side = _get_attr(position, "side")
        entry_price = _get_attr(position, "entry_price")
        current_price = market_context.get("price")
        opened_at = _get_attr(position, "opened_at")
        size = _get_attr(position, "size")
        stop_loss = _get_attr(position, "stop_loss")
        
        # Time budget parameters from position
        time_to_work_sec = _get_attr(position, "time_to_work_sec")
        max_hold_sec = _get_attr(position, "max_hold_sec")
        mfe_min_bps = _get_attr(position, "mfe_min_bps")
        mfe_pct = _get_attr(position, "mfe_pct")  # Current MFE achieved
        
        if not side or not entry_price or not current_price:
            return None
        
        # Calculate current P&L
        if side == "long":
            pnl_pct = (current_price - entry_price) / entry_price * 100
        elif side == "short":
            pnl_pct = (entry_price - current_price) / entry_price * 100
        else:
            return None
        
        hold_time_sec = time.time() - opened_at if opened_at else 0.0
        
        # =================================================================
        # SAFETY EXITS - Always allowed, bypass min_hold
        # =================================================================
        safety_decision = self._check_safety_exits(
            side, pnl_pct, current_price, entry_price, stop_loss, market_context, ctx
        )
        if safety_decision and safety_decision.should_exit:
            return self._build_exit_signal(
                ctx, side, size, current_price, entry_price, pnl_pct,
                safety_decision, hold_time_sec,
                strategy_id=_get_attr(position, "strategy_id"),
                profile_id=_get_attr(position, "profile_id"),
            )
        
        # =================================================================
        # TIME BUDGET EXITS - MFT scalping time management
        # =================================================================
        time_budget_decision = self._check_time_budget_exits(
            side, pnl_pct, hold_time_sec, time_to_work_sec, max_hold_sec,
            mfe_min_bps, mfe_pct, market_context, ctx,
            size=size, entry_price=entry_price, current_price=current_price
        )
        if time_budget_decision and time_budget_decision.should_exit:
            return self._build_exit_signal(
                ctx, side, size, current_price, entry_price, pnl_pct,
                time_budget_decision, hold_time_sec,
                strategy_id=_get_attr(position, "strategy_id"),
                profile_id=_get_attr(position, "profile_id"),
            )
        
        # =================================================================
        # INVALIDATION EXITS - Respect min_hold time (with urgency reduction)
        # =================================================================
        # Use strategy-specific min_hold from enforcer (Requirement 3.4)
        strategy_id = _get_attr(position, "strategy_id") or "default"
        base_min_hold = self._min_hold_enforcer.config.get_min_hold_time(strategy_id)
        
        # Override with position's min_hold if explicitly set
        position_min_hold = _get_attr(position, "min_hold_time_seconds")
        if position_min_hold is not None:
            base_min_hold = position_min_hold
        
        # Get mode config for urgency threshold (Requirement 6)
        mode_config = self._get_mode_config(ctx.symbol)
        urgency_bypass_threshold = 0.8  # Default
        if mode_config:
            urgency_bypass_threshold = mode_config.urgency_bypass_threshold
        
        # Calculate preliminary urgency to check for min_hold reduction
        # This is a simplified calculation - full urgency is calculated in _check_invalidation_exits
        is_underwater = pnl_pct < self.exit_underwater_threshold_pct
        preliminary_urgency = 0.3 if is_underwater else 0.0
        
        # Reduce min_hold for high urgency situations (Requirement 6.1, 6.2)
        effective_min_hold = base_min_hold
        if preliminary_urgency >= urgency_bypass_threshold or is_underwater:
            # Cap at 5 seconds for high urgency (Requirement 6.3)
            effective_min_hold = min(5.0, base_min_hold)
            if _exit_trace_enabled() and effective_min_hold < base_min_hold:
                log_info(
                    "min_hold_reduced_high_urgency",
                    symbol=ctx.symbol,
                    strategy_id=strategy_id,
                    base_min_hold=base_min_hold,
                    effective_min_hold=effective_min_hold,
                    preliminary_urgency=round(preliminary_urgency, 2),
                    is_underwater=is_underwater,
                )
        
        if opened_at and effective_min_hold > 0:
            if hold_time_sec < effective_min_hold:
                # Calculate time remaining for display (Requirement 3.6)
                time_remaining = effective_min_hold - hold_time_sec
                if _exit_trace_enabled():
                    log_info(
                        "position_exit_min_hold_not_met",
                        symbol=ctx.symbol,
                        strategy_id=strategy_id,
                        hold_time_sec=round(hold_time_sec, 1),
                        min_hold_time_sec=effective_min_hold,
                        base_min_hold=base_min_hold,
                        time_remaining_sec=round(time_remaining, 1),
                    )
                return None
        
        invalidation_decision = self._check_invalidation_exits(
            side,
            pnl_pct,
            current_price,
            entry_price,
            market_context,
            ctx,
            size,
            strategy_id=_get_attr(position, "strategy_id"),
        )
        if invalidation_decision and invalidation_decision.should_exit:
            return self._build_exit_signal(
                ctx, side, size, current_price, entry_price, pnl_pct,
                invalidation_decision, hold_time_sec,
                strategy_id=_get_attr(position, "strategy_id"),
                profile_id=_get_attr(position, "profile_id"),
            )
        
        # Log why we didn't exit (for debugging)
        if _exit_trace_enabled() or _trace_detail_enabled():
            self._log_no_exit(ctx, side, pnl_pct, invalidation_decision, market_context, opened_at)
        
        return None
    
    def _check_safety_exits(
        self,
        side: str,
        pnl_pct: float,
        current_price: float,
        entry_price: float,
        stop_loss: Optional[float],
        market_context: dict,
        ctx: StageContext,
    ) -> Optional[ExitDecision]:
        """
        Check for SAFETY exits that bypass min_hold.
        
        These protect from catastrophic losses and must execute immediately.
        CRITICAL: Safety exits NEVER check fees - they must always execute.
        """
        confirmations = []
        urgency = 0.0
        bypass_reason = None
        
        # --- Safety 1: Hard Stop Hit ---
        if pnl_pct < -self.hard_stop_pct:
            confirmations.append(f"hard_stop_hit (pnl={pnl_pct:.2f}%)")
            urgency = 1.0
            bypass_reason = "hard_stop_hit"
        
        # --- Safety 2: Position Stop Loss Hit ---
        if stop_loss:
            if side == "long" and current_price <= stop_loss:
                confirmations.append(f"stop_loss_hit (price={current_price:.2f}<=SL={stop_loss:.2f})")
                urgency = max(urgency, 0.9)
                bypass_reason = bypass_reason or "stop_loss_hit"
            elif side == "short" and current_price >= stop_loss:
                confirmations.append(f"stop_loss_hit (price={current_price:.2f}>=SL={stop_loss:.2f})")
                urgency = max(urgency, 0.9)
                bypass_reason = bypass_reason or "stop_loss_hit"
        
        # --- Safety 3: Data Staleness While in Position ---
        data_quality_status = market_context.get("data_quality_status")
        trade_sync_state = market_context.get("trade_sync_state")
        
        if data_quality_status == "stale" or trade_sync_state == "stale":
            confirmations.append("data_stale_while_in_position")
            urgency = max(urgency, 0.8)
            bypass_reason = bypass_reason or "data_stale"
        
        # --- Safety 4: Deeply Underwater (Emergency) ---
        deep_underwater_threshold = min(-1.0, self.exit_underwater_threshold_pct * 3)
        if pnl_pct < deep_underwater_threshold:
            confirmations.append(f"deeply_underwater_emergency (pnl={pnl_pct:.2f}%)")
            urgency = max(urgency, 0.95)
            bypass_reason = bypass_reason or "deeply_underwater"
        
        if not confirmations:
            return None
        
        # Log that fee check is being bypassed for safety exit
        if _exit_trace_enabled() and self.fee_model is not None:
            log_info(
                "fee_check_bypassed_safety_exit",
                symbol=ctx.symbol,
                side=side,
                bypass_reason=bypass_reason,
                confirmations=confirmations,
                pnl_pct=round(pnl_pct, 2),
            )
        
        return ExitDecision(
            should_exit=True,
            exit_type=ExitType.SAFETY,
            reason=confirmations[0],
            urgency=urgency,
            confirmations=confirmations,
            # fee_check_result is None - safety exits bypass fee checks
        )
    
    def _check_time_budget_exits(
        self,
        side: str,
        pnl_pct: float,
        hold_time_sec: float,
        time_to_work_sec: Optional[float],
        max_hold_sec: Optional[float],
        mfe_min_bps: Optional[float],
        mfe_pct: Optional[float],
        market_context: dict,
        ctx: StageContext,
        size: Optional[float] = None,
        entry_price: Optional[float] = None,
        current_price: Optional[float] = None,
    ) -> Optional[ExitDecision]:
        """
        Check for TIME BUDGET exits (MFT scalping).
        
        Time budget rules:
        1. Time-to-work: If no MFE_min by T_work, scratch/de-risk
        2. Max-hold: Stale trade exit at max_hold
        
        Fee-aware behavior:
        - If below fee threshold and within grace period: extend hold
        - If below fee threshold and past grace period: exit anyway (stale trade)
        - If above fee threshold: exit immediately
        """
        confirmations = []
        urgency = 0.0
        
        # Get regime multiplier for time budgets
        volatility_regime = market_context.get("volatility_regime", "normal")
        regime_multiplier = 1.0
        if volatility_regime == "high" or volatility_regime == "shock":
            regime_multiplier = 0.5  # Shrink holds in chaos
        elif volatility_regime == "low":
            # Only extend for trend strategies (check if position has trend tag)
            # For now, use a slight extension
            regime_multiplier = 1.1
        
        # --- Time Budget 1: Time-to-Work Check ---
        # If we haven't made minimum progress by T_work, scratch the trade
        if time_to_work_sec is not None and mfe_min_bps is not None:
            effective_t_work = time_to_work_sec * regime_multiplier
            if hold_time_sec >= effective_t_work:
                # Check if we've achieved minimum favorable excursion
                # mfe_pct is in percentage, mfe_min_bps is in basis points
                mfe_achieved_bps = (mfe_pct or 0.0) * 100.0  # Convert % to bps
                if mfe_achieved_bps < mfe_min_bps:
                    confirmations.append(
                        f"time_to_work_fail (hold={hold_time_sec:.1f}s>T_work={effective_t_work:.1f}s, "
                        f"MFE={mfe_achieved_bps:.1f}bps<min={mfe_min_bps:.1f}bps)"
                    )
                    urgency = 0.6  # Medium urgency - scratch trade
                    if _exit_trace_enabled():
                        log_info(
                            "time_budget_t_work_fail",
                            symbol=ctx.symbol,
                            hold_time_sec=round(hold_time_sec, 1),
                            t_work_sec=round(effective_t_work, 1),
                            mfe_achieved_bps=round(mfe_achieved_bps, 1),
                            mfe_min_bps=mfe_min_bps,
                            regime_multiplier=regime_multiplier,
                        )
        
        # --- Time Budget 2: Max-Hold Check ---
        # Stale trade exit - signal has decayed
        if max_hold_sec is not None:
            effective_max_hold = max_hold_sec * regime_multiplier
            if hold_time_sec >= effective_max_hold:
                confirmations.append(
                    f"max_hold_exceeded (hold={hold_time_sec:.1f}s>=max={effective_max_hold:.1f}s)"
                )
                urgency = max(urgency, 0.7)  # Higher urgency than T_work fail
                if _exit_trace_enabled():
                    log_info(
                        "time_budget_max_hold_exceeded",
                        symbol=ctx.symbol,
                        hold_time_sec=round(hold_time_sec, 1),
                        max_hold_sec=round(effective_max_hold, 1),
                        pnl_pct=round(pnl_pct, 2),
                        regime_multiplier=regime_multiplier,
                    )
        
        if not confirmations:
            return None
        
        # =================================================================
        # FEE-AWARE TIME BUDGET EXIT LOGIC
        # Apply grace period if below fee threshold
        # =================================================================
        fee_check_result: Optional[FeeAwareExitCheck] = None
        if (self.fee_model is not None and size is not None and size > 0 
            and entry_price is not None and current_price is not None):
            
            fee_check_result = self.fee_model.check_exit_profitability(
                size=size,
                entry_price=entry_price,
                current_price=current_price,
                side=side,
                min_profit_buffer_bps=self.min_profit_buffer_bps,
            )
            
            if not fee_check_result.should_allow_exit:
                # Below fee threshold - check grace period
                # Grace period extends from max_hold (or t_work) by fee_check_grace_period_sec
                effective_deadline = (max_hold_sec or time_to_work_sec or 0) * regime_multiplier
                grace_deadline = effective_deadline + self.fee_check_grace_period_sec
                
                if hold_time_sec < grace_deadline:
                    # Within grace period - extend hold, don't exit yet
                    if _exit_trace_enabled():
                        log_info(
                            "fee_aware_time_budget_grace_period",
                            symbol=ctx.symbol,
                            side=side,
                            hold_time_sec=round(hold_time_sec, 1),
                            grace_deadline=round(grace_deadline, 1),
                            gross_pnl_bps=fee_check_result.gross_pnl_bps,
                            min_required_bps=fee_check_result.min_required_bps,
                            shortfall_bps=fee_check_result.shortfall_bps,
                        )
                    return None  # Extend hold - don't exit yet
                else:
                    # Past grace period - exit anyway (stale trade)
                    if _exit_trace_enabled():
                        log_info(
                            "fee_aware_time_budget_grace_expired",
                            symbol=ctx.symbol,
                            side=side,
                            hold_time_sec=round(hold_time_sec, 1),
                            grace_deadline=round(grace_deadline, 1),
                            gross_pnl_bps=fee_check_result.gross_pnl_bps,
                            net_pnl_bps=fee_check_result.net_pnl_bps,
                            reason="grace_period_expired_exit_anyway",
                        )
                    confirmations.append(f"grace_period_expired (shortfall={fee_check_result.shortfall_bps:.1f}bps)")
        
        decision = ExitDecision(
            should_exit=True,
            exit_type=ExitType.INVALIDATION,  # Time budget exits are invalidation-class
            reason=confirmations[0],
            urgency=urgency,
            confirmations=confirmations,
        )
        if fee_check_result is not None:
            decision.fee_check_result = fee_check_result
            if not fee_check_result.should_allow_exit:
                decision.fee_check_bypassed = True
                decision.fee_bypass_reason = "grace_period_expired_exit_anyway"
        
        return decision
    
    def _check_invalidation_exits(
        self,
        side: str,
        pnl_pct: float,
        current_price: float,
        entry_price: float,
        market_context: dict,
        ctx: StageContext,
        size: Optional[float] = None,
        strategy_id: Optional[str] = None,
    ) -> Optional[ExitDecision]:
        """
        Check for INVALIDATION exits that respect min_hold.
        
        These indicate the trading premise has changed.
        Fee-aware: Exits are blocked if profit doesn't cover fees + buffer.
        """
        confirmations = []
        legacy_reject_reason = "insufficient_confirmations"
        
        # --- Invalidation 1: Trend Reversal ---
        trend_bias = market_context.get("trend_bias") or market_context.get("trend_direction")
        trend_confidence = market_context.get("trend_confidence")
        if trend_confidence is None:
            trend_strength = market_context.get("trend_strength")
            if trend_strength is not None:
                trend_confidence = min(1.0, abs(trend_strength) * 100.0)
            else:
                trend_confidence = 0.0
        
        if trend_bias == "down":
            trend_bias = "short"
        elif trend_bias == "up":
            trend_bias = "long"
        
        if side == "long" and trend_bias == "short" and trend_confidence >= 0.3:
            confirmations.append(f"trend_reversal_short (conf={trend_confidence:.2f})")
        elif side == "short" and trend_bias == "long" and trend_confidence >= 0.3:
            confirmations.append(f"trend_reversal_long (conf={trend_confidence:.2f})")
        
        # --- Invalidation 2: Orderflow Reversal ---
        orderflow_imbalance = market_context.get("orderflow_imbalance") or 0.0
        
        if side == "long" and orderflow_imbalance < -0.75:
            confirmations.append(f"orderflow_sell_pressure (imb={orderflow_imbalance:+.2f})")
        elif side == "short" and orderflow_imbalance > 0.75:
            confirmations.append(f"orderflow_buy_pressure (imb={orderflow_imbalance:+.2f})")
        
        # --- Invalidation 3: Price at Key Levels ---
        price = current_price or entry_price
        if side == "long":
            distance_to_vah = market_context.get("distance_to_vah_pct")
            if distance_to_vah is None:
                raw_dist = market_context.get("distance_to_vah")
                if raw_dist is not None and price and price > 0:
                    distance_to_vah = raw_dist / price
                else:
                    distance_to_vah = 1.0
            if distance_to_vah is not None and abs(distance_to_vah) < 0.001:
                confirmations.append("price_at_resistance_vah")
        elif side == "short":
            distance_to_val = market_context.get("distance_to_val_pct")
            if distance_to_val is None:
                raw_dist = market_context.get("distance_to_val")
                if raw_dist is not None and price and price > 0:
                    distance_to_val = raw_dist / price
                else:
                    distance_to_val = 1.0
            if distance_to_val is not None and abs(distance_to_val) < 0.001:
                confirmations.append("price_at_support_val")
        
        # --- Invalidation 4: Volatility Spike ---
        volatility_regime = market_context.get("volatility_regime")
        volatility_percentile = market_context.get("volatility_percentile")
        if volatility_percentile is None:
            atr_ratio = market_context.get("atr_ratio")
            if atr_ratio is not None:
                volatility_percentile = min(1.0, 0.5 + (atr_ratio - 1.0) * 0.67)
            else:
                volatility_percentile = 0.5
        
        if volatility_regime == "high" and volatility_percentile > 0.8:
            confirmations.append(f"volatility_spike (pct={volatility_percentile:.2f})")
        
        # --- Invalidation 5: Underwater with Adverse Market ---
        is_underwater = pnl_pct < self.exit_underwater_threshold_pct
        
        if is_underwater:
            if side == "long" and (trend_bias == "short" or orderflow_imbalance < -0.15):
                confirmations.append(f"underwater_adverse_conditions (pnl={pnl_pct:.2f}%)")
            elif side == "short" and (trend_bias == "long" or orderflow_imbalance > 0.15):
                confirmations.append(f"underwater_adverse_conditions (pnl={pnl_pct:.2f}%)")
        
        # --- Invalidation 6: Max Underwater Hold Time ---
        # This is handled in the main _evaluate_exit method
        
        # --- Invalidation 7: Conservative Mode Underwater ---
        risk_mode = market_context.get("risk_mode")
        if risk_mode == "conservative" and is_underwater:
            confirmations.append("conservative_mode_underwater")
        
        legacy_confirm = len(confirmations) >= self.min_confirmations_for_exit
        if not legacy_confirm:
            legacy_reject_reason = "insufficient_confirmations"

        unified_result = self._confirmation_policy_engine.evaluate_exit_non_emergency(
            side=side,
            pnl_pct=pnl_pct,
            current_price=current_price,
            entry_price=entry_price,
            market_context=market_context,
            strategy_id=strategy_id,
        )
        unified_confirm = unified_result.confirm
        unified_confirmations = list(unified_result.passed_evidence)
        unified_reject_reason = (
            unified_result.failed_hard_guards[0]
            if unified_result.failed_hard_guards
            else (unified_result.decision_reason_codes[0] if unified_result.decision_reason_codes else "unified_reject")
        )

        mode = self._confirmation_policy_engine.config.mode if self._confirmation_policy_engine.config.enabled else "legacy"
        final_confirm = unified_confirm if mode == "enforce" else legacy_confirm
        if mode == "enforce":
            confirmations = unified_confirmations
            reject_reason = unified_reject_reason
        else:
            reject_reason = legacy_reject_reason

        diff = legacy_confirm != unified_confirm
        if diff or _exit_trace_enabled():
            log_info(
                "exit_confirmation_policy_compare",
                symbol=ctx.symbol,
                side=side,
                strategy_id=strategy_id,
                mode=mode,
                legacy_decision=legacy_confirm,
                unified_decision=unified_confirm,
                unified_confidence=round(unified_result.confidence, 3),
                diff_reason="decision_mismatch" if diff else "none",
            )
        if isinstance(ctx.data, dict):
            comparisons = ctx.data.get("confirmation_shadow_comparisons")
            if not isinstance(comparisons, list):
                comparisons = []
                ctx.data["confirmation_shadow_comparisons"] = comparisons
            comparisons.append(
                {
                    "source_stage": self.name,
                    "decision_context": "exit_non_emergency",
                    "mode": mode,
                    "legacy_decision": bool(legacy_confirm),
                    "unified_decision": bool(unified_confirm),
                    "final_decision": bool(final_confirm),
                    "diff": bool(diff),
                    "diff_reason": "decision_mismatch" if diff else "none",
                    "unified_confidence": float(unified_result.confidence),
                    "strategy_id": strategy_id,
                    "side": side,
                }
            )

        if not final_confirm:
            return ExitDecision(
                should_exit=False,
                exit_type=ExitType.INVALIDATION,
                reason=reject_reason,
                urgency=0.0,
                confirmations=confirmations if mode != "enforce" else unified_confirmations,
            )
        
        # Calculate urgency for bypass decisions (Requirement 3.1)
        urgency = min(1.0, len(confirmations) * 0.3 + (0.3 if is_underwater else 0.0))
        
        # Get mode-specific config for bypass thresholds
        mode_config = self._get_mode_config(ctx.symbol)
        urgency_bypass_threshold = 0.8  # Default
        confirmation_bypass_count = 3   # Default
        deterioration_force_exit_count = 3  # Default
        
        if mode_config:
            urgency_bypass_threshold = mode_config.urgency_bypass_threshold
            confirmation_bypass_count = mode_config.confirmation_bypass_count
            deterioration_force_exit_count = mode_config.deterioration_force_exit_count
        
        # =================================================================
        # URGENCY-BASED FEE CHECK BYPASS (Requirement 3)
        # =================================================================
        bypass_fee_check = False
        bypass_reason = None
        
        # Bypass 1: High urgency (Requirement 3.1)
        if urgency >= urgency_bypass_threshold:
            bypass_fee_check = True
            bypass_reason = f"urgency_bypass (urgency={urgency:.2f}>={urgency_bypass_threshold})"
        
        # Bypass 2: Multiple confirmations (Requirement 3.2)
        if len(confirmations) >= confirmation_bypass_count:
            bypass_fee_check = True
            bypass_reason = bypass_reason or f"confirmation_bypass (count={len(confirmations)}>={confirmation_bypass_count})"
        
        # Bypass 3: Deterioration counter (Requirement 7)
        position_key = f"{ctx.symbol}:{side}"
        deterioration_count = self._update_deterioration(position_key, pnl_pct)
        if deterioration_count >= deterioration_force_exit_count:
            bypass_fee_check = True
            bypass_reason = bypass_reason or f"deterioration_force_exit (count={deterioration_count}>={deterioration_force_exit_count})"
            if _exit_trace_enabled():
                log_info(
                    "deterioration_force_exit",
                    symbol=ctx.symbol,
                    side=side,
                    deterioration_count=deterioration_count,
                    threshold=deterioration_force_exit_count,
                    pnl_pct=round(pnl_pct, 2),
                )
        
        # =================================================================
        # FEE-AWARE EXIT GATING (with bypass support)
        # Block exit if profit doesn't cover fees + buffer (unless bypassed)
        # =================================================================
        fee_check_result: Optional[FeeAwareExitCheck] = None
        if self.fee_model is not None and size is not None and size > 0:
            fee_check_result = self.fee_model.check_exit_profitability(
                size=size,
                entry_price=entry_price,
                current_price=current_price,
                side=side,
                min_profit_buffer_bps=self.min_profit_buffer_bps,
            )
            
            if not fee_check_result.should_allow_exit:
                # Check if we should bypass the fee check
                if bypass_fee_check:
                    # Log bypass (Requirement 3.4, 3.5)
                    if _exit_trace_enabled():
                        log_info(
                            "fee_check_bypassed",
                            symbol=ctx.symbol,
                            side=side,
                            bypass_reason=bypass_reason,
                            urgency=round(urgency, 2),
                            confirmations=len(confirmations),
                            deterioration_count=deterioration_count,
                            gross_pnl_bps=fee_check_result.gross_pnl_bps,
                            net_pnl_bps=fee_check_result.net_pnl_bps,
                            shortfall_bps=fee_check_result.shortfall_bps,
                        )
                    # Continue to exit despite fee check failure
                else:
                    # Block exit - profit doesn't cover fees and no bypass
                    if _exit_trace_enabled():
                        log_info(
                            "fee_aware_exit_blocked",
                            symbol=ctx.symbol,
                            side=side,
                            gross_pnl_bps=fee_check_result.gross_pnl_bps,
                            net_pnl_bps=fee_check_result.net_pnl_bps,
                            breakeven_bps=fee_check_result.breakeven_bps,
                            min_required_bps=fee_check_result.min_required_bps,
                            shortfall_bps=fee_check_result.shortfall_bps,
                            reason=fee_check_result.reason,
                            confirmations=confirmations,
                            urgency=round(urgency, 2),
                            bypass_threshold=urgency_bypass_threshold,
                        )
                    # Emit blocked signal telemetry (Requirement 9.3)
                    if self._blocked_signal_telemetry:
                        import asyncio
                        try:
                            loop = asyncio.get_event_loop()
                            if loop.is_running():
                                asyncio.create_task(
                                    self._blocked_signal_telemetry.record_blocked(
                                        symbol=ctx.symbol,
                                        gate_name="fee_check",
                                        reason=f"fee_check_blocked: {fee_check_result.reason}",
                                        metrics={
                                            "side": side,
                                            "gross_pnl_bps": fee_check_result.gross_pnl_bps,
                                            "net_pnl_bps": fee_check_result.net_pnl_bps,
                                            "breakeven_bps": fee_check_result.breakeven_bps,
                                            "min_required_bps": fee_check_result.min_required_bps,
                                            "shortfall_bps": fee_check_result.shortfall_bps,
                                            "urgency": round(urgency, 2),
                                            "confirmations": len(confirmations),
                                        },
                                    )
                                )
                        except RuntimeError:
                            pass  # No event loop, skip telemetry
                    return ExitDecision(
                        should_exit=False,
                        exit_type=ExitType.INVALIDATION,
                        reason=f"fee_check_blocked: {fee_check_result.reason}",
                        urgency=0.0,
                        confirmations=confirmations,
                        fee_check_result=fee_check_result,
                    )
            else:
                if _exit_trace_enabled():
                    log_info(
                        "fee_aware_exit_allowed",
                        symbol=ctx.symbol,
                        side=side,
                        gross_pnl_bps=fee_check_result.gross_pnl_bps,
                        net_pnl_bps=fee_check_result.net_pnl_bps,
                        min_required_bps=fee_check_result.min_required_bps,
                    )
        
        # Urgency was already calculated above
        decision = ExitDecision(
            should_exit=True,
            exit_type=ExitType.INVALIDATION,
            reason=confirmations[0],
            urgency=urgency,
            confirmations=confirmations,
        )
        setattr(decision, "confirmation_confidence", unified_result.confidence)
        setattr(decision, "confirmation_votes", unified_result.evidence_votes)
        setattr(decision, "confirmation_failed_guards", unified_result.failed_hard_guards)
        setattr(decision, "confirmation_reason_codes", unified_result.decision_reason_codes)
        # Attach fee check result if available
        if fee_check_result is not None:
            decision.fee_check_result = fee_check_result
            if bypass_fee_check and not fee_check_result.should_allow_exit:
                decision.fee_check_bypassed = True
                decision.fee_bypass_reason = bypass_reason
        
        return decision
    
    def _build_exit_signal(
        self,
        ctx: StageContext,
        side: str,
        size: float,
        current_price: float,
        entry_price: float,
        pnl_pct: float,
        decision: ExitDecision,
        hold_time_sec: float,
        strategy_id: Optional[str] = None,
        profile_id: Optional[str] = None,
    ) -> dict:
        """Build the exit signal dict from an ExitDecision."""
        exit_side = "sell" if side == "long" else "buy"
        signal_type = "CLOSE_LONG" if side == "long" else "CLOSE_SHORT"
        
        # Build fee_aware metadata
        fee_aware_meta = {
            "fee_check_passed": decision.exit_type == ExitType.SAFETY,
            "fee_check_bypassed": decision.exit_type == ExitType.SAFETY,
            "bypass_reason": decision.reason if decision.exit_type == ExitType.SAFETY else None,
        }
        
        # Add detailed fee info if available
        fee_check = getattr(decision, "fee_check_result", None)
        if fee_check is not None:
            fee_aware_meta.update({
                "fee_check_passed": bool(fee_check.should_allow_exit),
                "fee_check_bypassed": bool(getattr(decision, "fee_check_bypassed", False)),
                "bypass_reason": getattr(decision, "fee_bypass_reason", None),
                "gross_pnl_bps": fee_check.gross_pnl_bps,
                "net_pnl_bps": fee_check.net_pnl_bps,
                "breakeven_bps": fee_check.breakeven_bps,
                "min_required_bps": fee_check.min_required_bps,
                "shortfall_bps": fee_check.shortfall_bps,
                "gross_pnl_usd": fee_check.gross_pnl_usd,
                "net_pnl_usd": fee_check.net_pnl_usd,
                "estimated_exit_fee_usd": fee_check.estimated_exit_fee_usd,
            })
        
        payload = {
            "signal": True,
            "side": exit_side,
            "signal_type": signal_type,
            "symbol": ctx.symbol,
            "size": size,
            "entry_price": current_price,
            "stop_loss": None,
            "take_profit": None,
            "meta_reason": f"{decision.exit_type.value}_exit: {', '.join(decision.confirmations[:3])}",
            "confirmations": decision.confirmations,
            "current_pnl_pct": round(pnl_pct, 2),
            "position_entry_price": entry_price,
            "is_exit_signal": True,
            "reduce_only": True,
            "exit_type": decision.exit_type.value,
            "urgency": decision.urgency,
            "hold_time_sec": round(hold_time_sec, 1),
            "fee_aware": fee_aware_meta,
            "confirmation_version": self._confirmation_policy_engine.config.version,
            "confirmation_mode": self._confirmation_policy_engine.config.mode,
            "confirmation_confidence": getattr(decision, "confirmation_confidence", None),
            "confirmation_votes": getattr(decision, "confirmation_votes", {}),
            "confirmation_failed_guards": getattr(decision, "confirmation_failed_guards", []),
            "confirmation_reason_codes": getattr(decision, "confirmation_reason_codes", list(decision.confirmations)),
        }
        if strategy_id:
            payload["strategy_id"] = strategy_id
        if profile_id:
            payload["profile_id"] = profile_id
        return payload
    
    def _log_no_exit(
        self,
        ctx: StageContext,
        side: str,
        pnl_pct: float,
        decision: Optional[ExitDecision],
        market_context: dict,
        opened_at: Optional[float],
    ) -> None:
        """Log why exit was not triggered."""
        confirmations = decision.confirmations if decision else []
        
        log_info(
            "position_exit_not_triggered",
            symbol=ctx.symbol,
            side=side,
            pnl_pct=round(pnl_pct, 2),
            is_underwater=pnl_pct < self.exit_underwater_threshold_pct,
            confirmations=confirmations,
            min_required=self.min_confirmations_for_exit,
            eval_context={
                "trend_bias": market_context.get("trend_direction"),
                "orderflow_imbalance": round(market_context.get("orderflow_imbalance") or 0, 2),
                "volatility_regime": market_context.get("volatility_regime"),
                "risk_mode": market_context.get("risk_mode"),
                "entry_price": market_context.get("price"),
                "hold_time_sec": round(time.time() - opened_at) if opened_at else None,
                "underwater_threshold_pct": self.exit_underwater_threshold_pct,
            },
        )


class RiskStage(Stage):
    name = "risk_check"

    def __init__(self, validator, correlation_guard=None):
        self.validator = validator
        self.correlation_guard = correlation_guard

    async def run(self, ctx: StageContext) -> StageResult:
        signal = ctx.signal or {}
        
        # Exit signals (reduce_only, is_exit_signal) bypass normal risk checks
        # They're designed to REDUCE exposure, not increase it
        # Handle both dict and StrategySignal objects
        if isinstance(signal, dict):
            is_exit_signal = signal.get("is_exit_signal", False) or signal.get("reduce_only", False)
        else:
            is_exit_signal = getattr(signal, "is_exit_signal", False) or getattr(signal, "reduce_only", False)
        
        if is_exit_signal:
            side = signal.get("side") if isinstance(signal, dict) else getattr(signal, "side", None)
            log_info(
                "risk_stage_exit_bypass",
                symbol=ctx.symbol,
                reason="exit_signal_allowed",
                side=side,
            )
            return StageResult.CONTINUE

        if _maybe_allow_replacement(signal, ctx):
            return StageResult.CONTINUE

        if _should_block_existing_position(signal, ctx):
            ctx.rejection_reason = "position_exists"
            ctx.rejection_stage = self.name
            if _trace_detail_enabled():
                ctx.rejection_detail = {
                    "symbol": ctx.symbol,
                    "reason": "same_symbol_position_open",
                }
            log_info(
                "risk_stage_position_exists_reject",
                symbol=ctx.symbol,
                reason="same_symbol_position_open",
            )
            return StageResult.REJECT
        
        # Check correlation guard BEFORE entry (only for new positions)
        if self.correlation_guard is not None:
            # Get signal direction
            if isinstance(signal, dict):
                signal_side = signal.get("side") or signal.get("direction")
            else:
                signal_side = getattr(signal, "side", None) or getattr(signal, "direction", None)
            
            # Normalize to "long"/"short"
            if signal_side:
                signal_side_normalized = signal_side.lower()
                if signal_side_normalized in {"buy", "long"}:
                    signal_side_normalized = "long"
                elif signal_side_normalized in {"sell", "short"}:
                    signal_side_normalized = "short"
                else:
                    signal_side_normalized = None
                
                if signal_side_normalized:
                    # Get existing positions as list of dicts
                    positions = ctx.data.get("positions") or []
                    existing_positions = self._positions_to_dicts(positions)
                    
                    corr_result = await self.correlation_guard.check(
                        new_symbol=ctx.symbol,
                        new_side=signal_side_normalized,
                        existing_positions=existing_positions,
                    )
                    
                    if not corr_result.allowed:
                        ctx.rejection_reason = "correlation_blocked"
                        ctx.rejection_stage = "correlation_guard"
                        if _trace_detail_enabled():
                            ctx.rejection_detail = {
                                "correlation_reason": corr_result.reason,
                                "blocking_symbol": corr_result.blocking_symbol,
                                "correlation": corr_result.correlation,
                                # Debug aid: show what the guard thought was already open.
                                # Keep it small to avoid log spam.
                                "existing_positions": existing_positions[:10],
                                "new_side": signal_side_normalized,
                            }
                        log_info(
                            "correlation_guard_reject",
                            symbol=ctx.symbol,
                            blocking_symbol=corr_result.blocking_symbol,
                            correlation=corr_result.correlation,
                            reason=corr_result.reason,
                        )
                        return StageResult.REJECT

        context = {
            "symbol": ctx.symbol,
            "market_context": ctx.data.get("market_context"),
            "features": ctx.data.get("features"),
            "account": ctx.data.get("account"),
            "positions": ctx.data.get("positions"),
            "risk_limits": ctx.data.get("risk_limits"),
        }
        if not self.validator.allow(signal, context=context):
            ctx.rejection_reason = getattr(self.validator, "last_rejection_reason", None) or "risk_blocked"
            ctx.rejection_stage = self.name
            if _trace_detail_enabled():
                ctx.rejection_detail = {"risk_reason": ctx.rejection_reason}
            log_info(
                "risk_stage_reject",
                symbol=ctx.symbol,
                reason=ctx.rejection_reason,
                account=context.get("account"),
                positions=_serialize_positions(context.get("positions")),
            )
            return StageResult.REJECT
        return StageResult.CONTINUE
    
    def _positions_to_dicts(self, positions) -> list:
        """Convert position objects to list of dicts for correlation guard."""
        result = []
        for pos in positions:
            if isinstance(pos, dict):
                result.append(pos)
            else:
                # PositionSnapshot or similar object
                symbol = getattr(pos, "symbol", None)
                size = getattr(pos, "size", 0)
                side = getattr(pos, "side", None)
                
                # Normalize size based on side
                if side:
                    side_lower = side.lower()
                    if side_lower in {"short", "sell"} and size > 0:
                        size = -size
                
                result.append({"symbol": symbol, "size": size})
        return result


class SignalStage(Stage):
    """
    Signal generation stage that calls strategy registry.
    
    Symbol-Adaptive Parameters (Requirements 4.1, 4.2, 4.3):
    This stage injects resolved_params and symbol_characteristics into
    the features dict so strategies can access symbol-adaptive parameters.
    
    Signal Telemetry (Requirement 6.2):
    Resolved parameters are included in the signal metadata for debugging.
    
    Strategy Diagnostics (Requirement 7.4):
    Records tick_count and setup_count for each strategy.
    """
    name = "signal_check"

    def __init__(self, registry, diagnostics: Optional["StrategyDiagnostics"] = None):
        self.registry = registry
        self._diagnostics = diagnostics

    async def run(self, ctx: StageContext) -> StageResult:
        features = ctx.data.get("features") or {}
        market_context = ctx.data.get("market_context") or {}
        account = ctx.data.get("account") or {}

        # Prefer AMT-derived rotation when available to avoid zero/unstable tick-based rotation.
        amt_levels = ctx.data.get("amt_levels")
        if amt_levels is not None:
            rotation_val = getattr(amt_levels, "rotation_factor", None)
            if rotation_val is not None:
                features["rotation_factor"] = rotation_val
                market_context["rotation_factor"] = rotation_val
            # Prefer AMT-derived value area + POC distances for strategy inputs.
            poc = getattr(amt_levels, "point_of_control", None)
            vah = getattr(amt_levels, "value_area_high", None)
            val = getattr(amt_levels, "value_area_low", None)
            position_in_value = getattr(amt_levels, "position_in_value", None)
            if poc is not None and poc > 0:
                features["point_of_control"] = poc
                market_context["point_of_control"] = poc
            if vah is not None and vah > 0:
                features["value_area_high"] = vah
                market_context["value_area_high"] = vah
            if val is not None and val > 0:
                features["value_area_low"] = val
                market_context["value_area_low"] = val
            if position_in_value:
                features["position_in_value"] = position_in_value
                market_context["position_in_value"] = position_in_value
            # Distances (legacy + bps) - prefer AMT when available.
            dist_poc = getattr(amt_levels, "distance_to_poc", None)
            dist_vah = getattr(amt_levels, "distance_to_vah", None)
            dist_val = getattr(amt_levels, "distance_to_val", None)
            if dist_poc is not None:
                features["distance_to_poc"] = dist_poc
                market_context["distance_to_poc"] = dist_poc
            if dist_vah is not None:
                features["distance_to_vah"] = dist_vah
                market_context["distance_to_vah"] = dist_vah
            if dist_val is not None:
                features["distance_to_val"] = dist_val
                market_context["distance_to_val"] = dist_val
            dist_poc_bps = getattr(amt_levels, "distance_to_poc_bps", None)
            dist_vah_bps = getattr(amt_levels, "distance_to_vah_bps", None)
            dist_val_bps = getattr(amt_levels, "distance_to_val_bps", None)
            if dist_poc_bps is not None:
                features["distance_to_poc_bps"] = dist_poc_bps
                market_context["distance_to_poc_bps"] = dist_poc_bps
            if dist_vah_bps is not None:
                features["distance_to_vah_bps"] = dist_vah_bps
                market_context["distance_to_vah_bps"] = dist_vah_bps
            if dist_val_bps is not None:
                features["distance_to_val_bps"] = dist_val_bps
                market_context["distance_to_val_bps"] = dist_val_bps
        
        # Inject resolved_params and symbol_characteristics into features
        # so strategies can access symbol-adaptive parameters (Requirements 4.1, 4.2, 4.3)
        resolved_params = ctx.data.get("resolved_params")
        symbol_characteristics = ctx.data.get("symbol_characteristics")
        profile_scores = ctx.data.get("profile_scores")
        
        if resolved_params is not None:
            features["resolved_params"] = resolved_params
        if symbol_characteristics is not None:
            features["symbol_characteristics"] = symbol_characteristics
        if profile_scores is not None:
            features["profile_scores"] = profile_scores
            market_context["profile_scores"] = profile_scores
        
        # Record tick for diagnostics (Requirement 7.4)
        # Use profile_id as strategy_id proxy since we don't know which strategy will be called
        if self._diagnostics and ctx.profile_id:
            self._diagnostics.record_tick(ctx.profile_id)
        
        signal = None
        if hasattr(self.registry, "generate_signal_with_context"):
            signal = self.registry.generate_signal_with_context(
                ctx.symbol,
                ctx.profile_id,
                features,
                market_context,
                account,
            )
        else:
            signal = self.registry.generate_signal(ctx.profile_id, features)
        if not signal:
            # Diagnostic mode: emit a minimal test signal to validate downstream pipeline
            if os.getenv("FORCE_TEST_SIGNAL", "false").lower() in {"1", "true", "yes"}:
                # Synthesize a minimal but valid signal for downstream stages
                price = market_context.get("price") or features.get("price") or features.get("last") or 0.0
                if not price or price <= 0:
                    price = 100.0  # fallback to avoid zero distance in EV gate
                # Provide basic SL/TP offsets to satisfy EV/risk stages
                # Use slightly wider test distances so EV gate can pass despite fees/slippage
                sl = price * 0.995 if price else None  # ~50 bps
                tp = price * 1.0075 if price else None  # ~75 bps
                ctx.signal = {
                    "strategy_id": "test_signal_generator",
                    "symbol": ctx.symbol,
                    "side": "long",
                    "size": 1.0,
                    "entry_price": price,
                    "stop_loss": sl,
                    "take_profit": tp,
                    "sl_distance_bps": 50.0,
                    "tp_distance_bps": 75.0,
                    "spread_bps": (features.get("spread_bps") or market_context.get("spread_bps") or 0.1),
                    "meta_reason": "forced_test_signal",
                    "profile_id": ctx.profile_id,
                    "p_hat": 0.6,
                    "p_hat_source": "forced_test_signal",
                }
                return StageResult.CONTINUE
            ctx.rejection_reason = "no_signal"
            ctx.rejection_stage = self.name
            detail = {
                "profile_id": ctx.profile_id,
                "feature_snapshot": _feature_snapshot(features, market_context),
                "strategy_attempts": (features or {}).get("_strategy_attempts") if isinstance(features, dict) else None,
                "profile_attempts": (features or {}).get("_profile_attempts") if isinstance(features, dict) else None,
            }
            ctx.rejection_detail = detail
            if _trace_detail_enabled():
                log_info("no_signal_detail", symbol=ctx.symbol, **detail)
            return StageResult.REJECT
        if isinstance(signal, bool):
            ctx.signal = {"signal": True, "risk_ok": ctx.data.get("risk_ok", True)}
        else:
            ctx.signal = signal

        # Normalize signals to dict form for downstream stages (EV gate, sizing, execution).
        # Many strategies emit `StrategySignal` (dataclass). Several downstream stages
        # expect a dict and will silently lose dynamically injected fields if we only
        # call `asdict()` later. Converting here ensures p_hat/identity/cost injection
        # is preserved end-to-end.
        if ctx.signal is not None and not isinstance(ctx.signal, dict):
            ctx.signal = signal_to_dict(ctx.signal)

        prediction = ctx.data.get("prediction") or {}
        if isinstance(ctx.signal, dict) and isinstance(prediction, dict):
            resolved_probs = _resolve_action_policy_probabilities(prediction)
            if resolved_probs is not None:
                enabled = os.getenv("ACTION_CONDITIONAL_POLICY_ENABLED", "true").strip().lower() in {
                    "1",
                    "true",
                    "yes",
                    "on",
                }
                if enabled:
                    p_thresh = float(os.getenv("ACTION_CONDITIONAL_P_THRESH", "0.65"))
                    margin_thresh = float(os.getenv("ACTION_CONDITIONAL_MARGIN_THRESH", "0.0"))
                    min_directional_mass = float(os.getenv("ACTION_CONDITIONAL_MIN_DIRECTIONAL_MASS", "0.25"))
                    p_long = float(resolved_probs["p_long_eval"])
                    p_short = float(resolved_probs["p_short_eval"])
                    p_long_raw = float(resolved_probs["p_long_raw"])
                    p_short_raw = float(resolved_probs["p_short_raw"])
                    p_star = float(resolved_probs["p_star"])
                    margin = float(resolved_probs["margin"])
                    directional_mass = float(resolved_probs["directional_mass"])
                    normalized = bool(resolved_probs["normalized"])
                    blocked = (
                        p_star < p_thresh
                        or margin < margin_thresh
                        or directional_mass < min_directional_mass
                    )
                    if blocked:
                        ctx.rejection_reason = "action_policy_blocked"
                        ctx.rejection_stage = self.name
                        ctx.rejection_detail = {
                            "p_long_win": p_long,
                            "p_short_win": p_short,
                            "p_long_raw": p_long_raw,
                            "p_short_raw": p_short_raw,
                            "p_star": p_star,
                            "margin": margin,
                            "directional_mass": directional_mass,
                            "min_directional_mass": min_directional_mass,
                            "normalized": normalized,
                            "p_thresh": p_thresh,
                            "margin_thresh": margin_thresh,
                        }
                        return StageResult.REJECT
                    side = "long" if p_long >= p_short else "short"
                    current_effect = str(ctx.signal.get("position_effect") or "").lower()
                    if current_effect != "close":
                        ctx.signal["side"] = side
                        ctx.signal["model_direction"] = side
                        ctx.signal["p_long_win"] = p_long
                        ctx.signal["p_short_win"] = p_short
                        ctx.signal["p_long_win_raw"] = p_long_raw
                        ctx.signal["p_short_win_raw"] = p_short_raw
                        ctx.signal["p_star"] = p_star
                        ctx.signal["p_margin"] = margin
                        ctx.signal["directional_mass"] = directional_mass
                        ctx.signal["action_probabilities_normalized"] = normalized
                        ctx.signal["prediction_contract"] = "action_conditional_pnl_winprob"

        _inject_signal_identity(ctx.signal, ctx)
        _enforce_min_risk_params(ctx.signal, ctx)
        _inject_signal_cost_estimate(ctx.signal, ctx)
        
        # Record setup for diagnostics (Requirement 7.4)
        # A signal being generated means a setup was detected
        if self._diagnostics:
            strategy_id = None
            if hasattr(signal, 'strategy_id'):
                strategy_id = signal.strategy_id
            elif isinstance(signal, dict):
                strategy_id = signal.get('strategy_id')
            if strategy_id:
                self._diagnostics.record_setup(strategy_id)
        
        # Add resolved_params to signal metadata for telemetry (Requirement 6.2)
        if ctx.signal and isinstance(ctx.signal, dict) and resolved_params is not None:
            resolved_dict = resolved_params.to_dict() if hasattr(resolved_params, "to_dict") else resolved_params
            ctx.signal["resolved_params"] = resolved_dict
        
        return StageResult.CONTINUE


class PredictionStage(Stage):
    name = "prediction_gate"

    def __init__(
        self,
        min_confidence: float = 0.0,
        allowed_directions: Optional[set[str]] = None,
        min_confidence_by_symbol: Optional[Dict[str, float]] = None,
    ):
        self.min_confidence = min_confidence
        self.allowed_directions = allowed_directions
        self.enforce_score_quality_gate = True
        self.passthrough_on_reject = False
        self.score_quality_fail_closed = os.getenv(
            "PREDICTION_GATE_SCORE_FAIL_CLOSED",
            "false",
        ).strip().lower() in {"1", "true", "yes", "on"}
        self.min_directional_accuracy = coerce_float(
            os.getenv("PREDICTION_SCORE_MIN_DIRECTIONAL_ACCURACY")
        )
        if self.min_directional_accuracy is None:
            self.min_directional_accuracy = 0.50
        self.min_directional_accuracy_long = coerce_float(
            os.getenv("PREDICTION_SCORE_MIN_DIRECTIONAL_ACCURACY_LONG")
        )
        if self.min_directional_accuracy_long is None:
            self.min_directional_accuracy_long = self.min_directional_accuracy
        self.min_directional_accuracy_short = coerce_float(
            os.getenv("PREDICTION_SCORE_MIN_DIRECTIONAL_ACCURACY_SHORT")
        )
        if self.min_directional_accuracy_short is None:
            self.min_directional_accuracy_short = self.min_directional_accuracy
        self.max_ece = coerce_float(os.getenv("PREDICTION_SCORE_MAX_ECE"))
        if self.max_ece is None:
            self.max_ece = 0.20
        self.max_ece_long = coerce_float(os.getenv("PREDICTION_SCORE_MAX_ECE_LONG"))
        if self.max_ece_long is None:
            self.max_ece_long = self.max_ece
        self.max_ece_short = coerce_float(os.getenv("PREDICTION_SCORE_MAX_ECE_SHORT"))
        if self.max_ece_short is None:
            self.max_ece_short = self.max_ece
        if min_confidence_by_symbol is None:
            min_confidence_by_symbol = _parse_symbol_float_map(
                os.getenv("PREDICTION_MIN_CONFIDENCE_BY_SYMBOL", "")
            )
        self.min_confidence_by_symbol = {
            symbol.upper(): max(0.0, min(1.0, float(value)))
            for symbol, value in (min_confidence_by_symbol or {}).items()
        }
        self.require_prediction_for_entry = os.getenv(
            "PREDICTION_REQUIRE_PRESENT",
            "false",
        ).strip().lower() in {"1", "true", "yes", "on"}

    async def run(self, ctx: StageContext) -> StageResult:
        prediction = ctx.data.get("prediction")
        if not prediction:
            signal = ctx.signal if isinstance(ctx.signal, dict) else {}
            position_effect = str(signal.get("position_effect") or "").strip().lower()
            is_entry = position_effect != "close"
            if self.require_prediction_for_entry and is_entry:
                market_context = ctx.data.get("market_context") if isinstance(ctx.data.get("market_context"), dict) else {}
                prediction_status = ctx.data.get("prediction_status") if isinstance(ctx.data.get("prediction_status"), dict) else {}
                blocked_reason = (
                    prediction_status.get("reason")
                    or market_context.get("prediction_blocked")
                    or market_context.get("prediction_score_gate_reason")
                    or "prediction_missing"
                )
                blocked_reason = str(blocked_reason).strip() or "prediction_missing"
                if blocked_reason != "prediction_missing":
                    ctx.rejection_reason = "prediction_blocked"
                else:
                    ctx.rejection_reason = "prediction_missing"
                ctx.rejection_stage = self.name
                ctx.rejection_detail = {
                    "prediction_blocked_reason": blocked_reason,
                    "prediction_present": False,
                    "require_prediction_for_entry": True,
                }
                return StageResult.REJECT
            return StageResult.CONTINUE
        if prediction.get("reject"):
            if self.passthrough_on_reject:
                return StageResult.CONTINUE
            ctx.rejection_reason = "prediction_blocked"
            ctx.rejection_stage = self.name
            prediction_reason = prediction.get("reason") or "prediction_reject_unspecified"
            ctx.rejection_detail = {
                "prediction_blocked_reason": prediction_reason,
                "prediction": {
                    "reason": prediction_reason,
                }
            }
            if _trace_detail_enabled():
                ctx.rejection_detail = {
                    "prediction_blocked_reason": prediction_reason,
                    "prediction": {
                        "confidence": prediction.get("confidence"),
                        "reason": prediction_reason,
                        "reject": prediction.get("reject"),
                        "abstain": prediction.get("abstain"),
                        "source": prediction.get("source"),
                    }
                }
            return StageResult.REJECT
        confidence = prediction.get("confidence")
        symbol = (ctx.symbol or "").upper()
        effective_min_confidence = self.min_confidence_by_symbol.get(symbol, self.min_confidence)
        if confidence is not None and confidence < effective_min_confidence:
            ctx.rejection_reason = "prediction_low_confidence"
            ctx.rejection_stage = self.name
            if _trace_detail_enabled():
                ctx.rejection_detail = {
                    "confidence": confidence,
                    "min_confidence": effective_min_confidence,
                    "global_min_confidence": self.min_confidence,
                    "symbol": symbol,
                }
            return StageResult.REJECT
        direction = prediction.get("direction")
        if self.allowed_directions and direction and direction not in self.allowed_directions:
            ctx.rejection_reason = "prediction_direction_blocked"
            ctx.rejection_stage = self.name
            if _trace_detail_enabled():
                ctx.rejection_detail = {
                    "direction": direction,
                    "allowed": sorted(self.allowed_directions),
                }
            return StageResult.REJECT
        if self.enforce_score_quality_gate:
            source = str(prediction.get("source") or "").strip().lower()
            if "onnx" in source:
                market_context = ctx.data.get("market_context") if isinstance(ctx.data, dict) else None
                market_context = market_context if isinstance(market_context, dict) else {}
                status = str(market_context.get("prediction_score_gate_status") or "").strip().lower()
                blocked_reason = (
                    market_context.get("prediction_score_gate_reason")
                    or market_context.get("prediction_blocked")
                )
                if status == "blocked" and blocked_reason:
                    ctx.rejection_reason = "prediction_score_blocked"
                    ctx.rejection_stage = self.name
                    ctx.rejection_detail = {
                        "prediction_blocked_reason": blocked_reason,
                        "score_gate_status": status,
                    }
                    return StageResult.REJECT
                metrics = market_context.get("prediction_score_gate_metrics")
                if not isinstance(metrics, dict):
                    if self.score_quality_fail_closed:
                        ctx.rejection_reason = "prediction_score_metrics_missing"
                        ctx.rejection_stage = self.name
                        return StageResult.REJECT
                else:
                    def _ratio(value: object) -> Optional[float]:
                        val = coerce_float(value)
                        if val is None:
                            return None
                        if val > 1.0:
                            val = val / 100.0
                        return max(0.0, min(1.0, float(val)))

                    direction_lower = str(direction or "").strip().lower()
                    side = (
                        "long" if direction_lower in {"up", "long", "buy"} else
                        "short" if direction_lower in {"down", "short", "sell"} else
                        None
                    )
                    directional_accuracy = _ratio(metrics.get("directional_accuracy"))
                    directional_accuracy_long = _ratio(metrics.get("directional_accuracy_long"))
                    directional_accuracy_short = _ratio(metrics.get("directional_accuracy_short"))
                    ece_top1 = _ratio(metrics.get("ece_top1"))
                    ece_top1_long = _ratio(metrics.get("ece_top1_long"))
                    ece_top1_short = _ratio(metrics.get("ece_top1_short"))

                    if (
                        directional_accuracy is not None
                        and directional_accuracy < self.min_directional_accuracy
                    ):
                        ctx.rejection_reason = "prediction_low_directional_accuracy"
                        ctx.rejection_stage = self.name
                        ctx.rejection_detail = {
                            "directional_accuracy": directional_accuracy,
                            "min_directional_accuracy": self.min_directional_accuracy,
                        }
                        return StageResult.REJECT
                    if (
                        side == "long"
                        and directional_accuracy_long is not None
                        and directional_accuracy_long < self.min_directional_accuracy_long
                    ):
                        ctx.rejection_reason = "prediction_low_directional_accuracy_long"
                        ctx.rejection_stage = self.name
                        ctx.rejection_detail = {
                            "directional_accuracy_long": directional_accuracy_long,
                            "min_directional_accuracy_long": self.min_directional_accuracy_long,
                        }
                        return StageResult.REJECT
                    if (
                        side == "short"
                        and directional_accuracy_short is not None
                        and directional_accuracy_short < self.min_directional_accuracy_short
                    ):
                        ctx.rejection_reason = "prediction_low_directional_accuracy_short"
                        ctx.rejection_stage = self.name
                        ctx.rejection_detail = {
                            "directional_accuracy_short": directional_accuracy_short,
                            "min_directional_accuracy_short": self.min_directional_accuracy_short,
                        }
                        return StageResult.REJECT
                    if ece_top1 is not None and ece_top1 > self.max_ece:
                        ctx.rejection_reason = "prediction_high_ece"
                        ctx.rejection_stage = self.name
                        ctx.rejection_detail = {
                            "ece_top1": ece_top1,
                            "max_ece": self.max_ece,
                        }
                        return StageResult.REJECT
                    if side == "long" and ece_top1_long is not None and ece_top1_long > self.max_ece_long:
                        ctx.rejection_reason = "prediction_high_ece_long"
                        ctx.rejection_stage = self.name
                        ctx.rejection_detail = {
                            "ece_top1_long": ece_top1_long,
                            "max_ece_long": self.max_ece_long,
                        }
                        return StageResult.REJECT
                    if side == "short" and ece_top1_short is not None and ece_top1_short > self.max_ece_short:
                        ctx.rejection_reason = "prediction_high_ece_short"
                        ctx.rejection_stage = self.name
                        ctx.rejection_detail = {
                            "ece_top1_short": ece_top1_short,
                            "max_ece_short": self.max_ece_short,
                        }
                        return StageResult.REJECT
        return StageResult.CONTINUE


class ExecutionStage(Stage):
    """
    Execution stage that sends signals for execution.
    
    Strategy Diagnostics (Requirement 7.7):
    Records signal_count when a signal is sent for execution.
    """
    name = "execution"

    def __init__(self, diagnostics: Optional["StrategyDiagnostics"] = None):
        self._diagnostics = diagnostics

    async def run(self, ctx: StageContext) -> StageResult:
        # Record signal for diagnostics (Requirement 7.7)
        if self._diagnostics and ctx.signal:
            strategy_id = None
            if hasattr(ctx.signal, 'strategy_id'):
                strategy_id = ctx.signal.strategy_id
            elif isinstance(ctx.signal, dict):
                strategy_id = ctx.signal.get('strategy_id')
            if strategy_id:
                self._diagnostics.record_signal(strategy_id)
        
        # Placeholder execution hook.
        return StageResult.COMPLETE


class ProfileRoutingStage(Stage):
    name = "profile_routing"

    def __init__(self, router):
        self.router = router

    def _inject_risk_context(self, ctx: StageContext, market_context: dict) -> None:
        account = ctx.data.get("account") or {}
        positions = ctx.data.get("positions") or []
        risk_limits = ctx.data.get("risk_limits") or {}
        equity = account.get("equity") or 0.0
        total_usd = 0.0
        for position in positions:
            price = (
                getattr(position, "reference_price", None)
                or getattr(position, "entry_price", None)
                or market_context.get("price")
            )
            size = getattr(position, "size", None)
            if price is None or size is None:
                continue
            try:
                total_usd += abs(float(size) * float(price))
            except (TypeError, ValueError):
                continue
        total_pct = (total_usd / float(equity) * 100.0) if equity else 0.0
        market_context.setdefault("total_exposure_usd", total_usd)
        market_context.setdefault("total_exposure_pct", total_pct)
        if risk_limits.get("max_total_exposure_pct") is not None:
            market_context.setdefault("max_total_exposure_pct", risk_limits.get("max_total_exposure_pct"))

    async def run(self, ctx: StageContext) -> StageResult:
        market_context = ctx.data.get("market_context") or {}
        features = ctx.data.get("features") or {}
        policy = ctx.data.get("profile_settings") or {}
        self._inject_risk_context(ctx, market_context)
        if hasattr(self.router, "set_policy"):
            self.router.set_policy(policy)
        if hasattr(self.router, "route_with_context"):
            profile_id = self.router.route_with_context(ctx.symbol, market_context, features)
        else:
            profile_id = self.router.route(market_context)
        ctx.profile_id = profile_id
        if profile_id:
            spec = None
            registry = getattr(self.router, "registry", None)
            if registry and hasattr(registry, "get_spec"):
                spec = registry.get_spec(profile_id)
            if spec is None:
                spec = get_profile_registry().get_spec(profile_id)
            if spec is not None:
                ctx.data["matched_profile"] = {
                    "profile_id": spec.id,
                    "risk_parameters": asdict(spec.risk),
                    "strategy_params": spec.strategy_params,
                }
        if getattr(self.router, "last_scores", None) is not None:
            ctx.data["profile_scores"] = self.router.last_scores
        if profile_id is None and getattr(self.router, "require_profile", False):
            scores = ctx.data.get("profile_scores") or []
            ctx.profile_id = None
            ctx.rejection_reason = "no_profile_match"
            ctx.rejection_stage = self.name
            if _trace_detail_enabled():
                ctx.rejection_detail = {
                    "profile_scores": scores,
                    "market_context": _market_context_snapshot(market_context),
                }
            return StageResult.REJECT
        return StageResult.CONTINUE


class Orchestrator:
    """Run stages sequentially and emit telemetry.
    
    Collects structured gate decisions from each stage and emits them
    as part of the decision telemetry payload.
    
    Stage Ordering Validation (Requirement 8.9, 8.10, 8.11, 8.12):
    - Validates stage ordering at initialization
    - Raises ConfigurationError for invalid stage ordering
    - Logs stage execution order at startup
    - Warns (not errors) if ProfileRouter is missing
    """

    def __init__(
        self,
        stages: List[Stage],
        telemetry: Optional[TelemetryPipeline] = None,
        telemetry_context: Optional[TelemetryContext] = None,
        validate_ordering: bool = True,
        strict_ordering: bool = False,
    ):
        """
        Initialize the Orchestrator with stage ordering validation.
        
        Args:
            stages: List of Stage objects to execute
            telemetry: Optional telemetry pipeline for publishing decisions
            telemetry_context: Optional telemetry context
            validate_ordering: Whether to validate stage ordering (default: True)
            strict_ordering: If True, raise ConfigurationError on invalid ordering.
                           If False, log warning but continue (default: False)
        """
        self.stages = stages
        self.telemetry = telemetry
        self.telemetry_context = telemetry_context
        self._profile_router_present = True
        self._stage_data_validation_enabled = os.getenv(
            "PIPELINE_STAGE_DATA_VALIDATION", "true"
        ).strip().lower() in {"1", "true", "yes", "on"}
        self._stage_data_validation_strict = os.getenv(
            "PIPELINE_STAGE_DATA_VALIDATION_STRICT", "false"
        ).strip().lower() in {"1", "true", "yes", "on"}
        
        # Validate stage ordering at initialization (Requirement 8.9)
        if validate_ordering:
            self._validate_and_log_stages(strict_ordering)
    
    def _validate_and_log_stages(self, strict_ordering: bool) -> None:
        """
        Validate stage ordering and log execution order.
        
        Implements Requirements 8.9, 8.10, 8.11, 8.12.
        """
        # Log stage execution order at startup (Requirement 8.11)
        log_stage_execution_order(self.stages)
        
        # Validate stage ordering (Requirement 8.9)
        is_valid, errors = validate_stage_ordering(self.stages)
        
        if not is_valid:
            error_msg = (
                f"Invalid stage ordering detected. Errors:\n" +
                "\n".join(f"  - {e}" for e in errors)
            )
            
            if strict_ordering:
                # Raise ConfigurationError for invalid ordering (Requirement 8.10)
                raise ConfigurationError(error_msg)
            else:
                # Log warning but continue
                log_warning(
                    f"pipeline_stage_ordering_warning: {error_msg}",
                    errors=errors,
                )
        
        # Check if ProfileRouter is present (Requirement 8.12)
        self._profile_router_present, warning_msg = check_profile_router_present(self.stages)
        
        if not self._profile_router_present and warning_msg:
            # Log warning (not error) if ProfileRouter is missing
            log_warning(
                f"pipeline_profile_router_missing: {warning_msg}",
                default_profile=DEFAULT_PROFILE_ID,
            )

    def _validate_stage_data_contract(
        self,
        stage_name: str,
        ctx: StageContext,
        phase: str,
    ) -> tuple[bool, list[str]]:
        if not self._stage_data_validation_enabled:
            return True, []
        requirements = STAGE_REQUIRED_DATA_KEYS.get(stage_name)
        if phase == "post":
            post_requirements = STAGE_POST_REQUIRED_KEYS.get(stage_name) or ()
            if requirements:
                requirements = tuple(dict.fromkeys((*requirements, *post_requirements)))
            else:
                requirements = post_requirements
        if not requirements:
            return True, []
        data = ctx.data if isinstance(ctx.data, dict) else {}
        missing: list[str] = []
        for key in requirements:
            if key == "signal":
                if not ctx.signal:
                    missing.append("signal")
                continue
            if key == "profile_id":
                if not ctx.profile_id:
                    missing.append("profile_id")
                continue
            if key == "candidate":
                if data.get("candidate") is None:
                    missing.append("candidate")
                continue
            value = data.get(key)
            if value is None:
                missing.append(key)
                continue
            if key in {"features", "market_context"} and isinstance(value, dict) and len(value) == 0:
                missing.append(key)
        if not missing:
            return True, []
        detail = {
            "phase": phase,
            "stage": stage_name,
            "missing_keys": missing,
        }
        if self._stage_data_validation_strict:
            ctx.rejection_reason = "stage_data_contract_violation"
            ctx.rejection_stage = stage_name
            ctx.rejection_detail = detail
            return False, missing
        log_warning("stage_data_contract_warning", **detail)
        return True, missing

    async def execute(self, ctx: StageContext) -> StageResult:
        start = time.perf_counter()
        result = StageResult.REJECT
        trace: list[dict] = []
        skip_to_execution = False
        skip_entry_generation = False
        gates_passed: list[str] = []
        
        # Use default profile if ProfileRouter is missing (Requirement 8.12)
        if not self._profile_router_present and ctx.profile_id is None:
            ctx.profile_id = DEFAULT_PROFILE_ID
        
        for stage in self.stages:
            # If we got SKIP_TO_EXECUTION, jump to RiskStage and ExecutionStage
            if skip_to_execution:
                if stage.name not in ("risk_check", "execution"):
                    trace.append({"stage": stage.name, "result": "SKIPPED"})
                    continue
            elif skip_entry_generation:
                if stage.name not in ("risk_check", "execution"):
                    trace.append({"stage": stage.name, "result": "SKIPPED"})
                    continue
                if stage.name == "risk_check":
                    ctx.rejection_reason = "position_exists"
                    ctx.rejection_stage = stage.name
                    if _trace_detail_enabled():
                        ctx.rejection_detail = {
                            "symbol": ctx.symbol,
                            "reason": "same_symbol_position_open",
                            "source": "entry_generation_short_circuit",
                        }
                    trace.append(
                        {
                            "stage": stage.name,
                            "result": StageResult.REJECT.value,
                            "rejection_reason": ctx.rejection_reason,
                            "rejection_detail": ctx.rejection_detail,
                        }
                    )
                    result = StageResult.REJECT
                    break

            pre_ok, pre_missing = self._validate_stage_data_contract(stage.name, ctx, phase="pre")
            if not pre_ok:
                trace.append(
                    {
                        "stage": stage.name,
                        "result": StageResult.REJECT.value,
                        "rejection_reason": ctx.rejection_reason,
                        "rejection_detail": ctx.rejection_detail,
                    }
                )
                result = StageResult.REJECT
                break
            
            result = await stage.run(ctx)
            trace_entry = {"stage": stage.name, "result": result.value}
            if pre_missing:
                trace_entry["contract_warnings_pre"] = pre_missing

            post_missing: list[str] = []
            if result != StageResult.REJECT:
                post_ok, post_missing = self._validate_stage_data_contract(stage.name, ctx, phase="post")
                if post_missing:
                    trace_entry["contract_warnings_post"] = post_missing
                if not post_ok:
                    result = StageResult.REJECT
                    trace_entry["result"] = StageResult.REJECT.value
                    trace_entry["rejection_reason"] = ctx.rejection_reason
                    if ctx.rejection_detail:
                        trace_entry["rejection_detail"] = ctx.rejection_detail

            # Attach gate decision metadata when available for this stage
            gate_decisions = None
            if isinstance(ctx.data, dict):
                gate_decisions = ctx.data.get("gate_decisions") or []
            if gate_decisions:
                for gate in reversed(gate_decisions):
                    gate_name = (
                        gate.gate_name
                        if hasattr(gate, "gate_name")
                        else gate.get("gate_name") if isinstance(gate, dict) else None
                    )
                    if gate_name == stage.name:
                        trace_entry["gate_decision"] = (
                            gate.to_dict()
                            if hasattr(gate, "to_dict")
                            else gate
                        )
                        break

            # Attach rejection detail when this stage rejects
            if result == StageResult.REJECT:
                trace_entry["rejection_reason"] = ctx.rejection_reason
                if ctx.rejection_detail:
                    trace_entry["rejection_detail"] = ctx.rejection_detail

            trace.append(trace_entry)
            
            if result == StageResult.REJECT:
                if ctx.rejection_stage is None:
                    ctx.rejection_stage = stage.name
                break
            
            # Track gates that passed
            gates_passed.append(stage.name)
            
            if result == StageResult.COMPLETE:
                break
            if result == StageResult.SKIP_TO_EXECUTION:
                # Position exit signal generated - skip to risk/execution stages
                skip_to_execution = True
                result = StageResult.CONTINUE  # Continue to next stage
            elif (
                stage.name == "position_evaluation"
                and result == StageResult.CONTINUE
                and not ctx.signal
                and _should_skip_entry_generation(ctx)
            ):
                skip_entry_generation = True
                
        ctx.stage_trace = trace
        latency_ms = (time.perf_counter() - start) * 1000.0
        
        # Determine final result
        final_result = StageResult.COMPLETE if result in (StageResult.COMPLETE, StageResult.CONTINUE) and ctx.signal else StageResult.REJECT
        
        if self.telemetry and self.telemetry_context:
            # Build structured decision payload
            payload = self._build_decision_payload(
                ctx=ctx,
                final_result=final_result,
                latency_ms=latency_ms,
                gates_passed=gates_passed,
            )
            
            await self.telemetry.publish_decision(
                ctx=self.telemetry_context,
                symbol=ctx.symbol,
                payload=payload,
            )
            await self.telemetry.publish_latency(
                ctx=self.telemetry_context,
                payload={"decision_latency_ms": latency_ms},
            )
        return final_result
    
    def _build_decision_payload(
        self,
        ctx: StageContext,
        final_result: StageResult,
        latency_ms: float,
        gates_passed: list[str],
    ) -> dict:
        """Build structured decision payload with gate details.
        
        Includes resolved_params in rejection_detail for observability (Requirement 6.1).
        """
        def _get_field(source: object, key: str):
            if source is None:
                return None
            if isinstance(source, dict):
                return source.get(key)
            return getattr(source, key, None)

        def _normalize_side(value: object) -> Optional[str]:
            if value is None:
                return None
            side = str(value).strip().lower()
            if side in {"long", "buy"}:
                return "long"
            if side in {"short", "sell"}:
                return "short"
            return None

        # Start with base payload
        expected_bps = None
        candidate_for_edge = ctx.data.get("candidate")
        if candidate_for_edge is not None:
            expected_bps = _get_field(candidate_for_edge, "expected_edge_bps")
        payload = decision_payload(
            result="COMPLETE" if final_result == StageResult.COMPLETE else "REJECT",
            latency_ms=latency_ms,
            rejection_reason=ctx.rejection_reason,
            expected_bps=expected_bps,
        )

        # Attach profile/strategy identity for attribution
        signal_dict = signal_to_dict(ctx.signal) if ctx.signal else {}

        profile_id = ctx.profile_id or signal_dict.get("profile_id")
        strategy_id = signal_dict.get("strategy_id")
        candidate = ctx.data.get("candidate")
        candidate_signal = ctx.data.get("candidate_signal")
        confirmed_signal = ctx.data.get("confirmed_signal")
        if not profile_id:
            profile_id = (
                _get_field(candidate, "profile_id")
                or _get_field(candidate_signal, "profile_id")
                or _get_field(confirmed_signal, "profile_id")
            )
        if not strategy_id:
            strategy_id = (
                _get_field(candidate, "strategy_id")
                or _get_field(candidate_signal, "strategy_id")
                or _get_field(confirmed_signal, "strategy_id")
            )
        if profile_id:
            payload["profile_id"] = profile_id
        if strategy_id:
            payload["strategy_id"] = strategy_id
        signal_side = _normalize_side(
            _get_field(candidate, "side")
            or _get_field(candidate_signal, "side")
            or _get_field(confirmed_signal, "side")
            or signal_dict.get("side")
        )
        if signal_side:
            payload["signal_side"] = signal_side
        
        # Add structured gate information
        payload["gates_passed"] = gates_passed
        payload["rejected_by"] = ctx.rejection_stage
        payload["rejection_stage"] = ctx.rejection_stage
        payload["rejection_reasons"] = [ctx.rejection_reason] if ctx.rejection_reason else []
        
        # Add rejection detail if available
        if ctx.rejection_detail:
            if isinstance(ctx.rejection_detail, dict):
                payload["rejection_detail"] = ctx.rejection_detail
                # Extract individual reasons if present
                if "reasons" in ctx.rejection_detail:
                    payload["rejection_reasons"] = ctx.rejection_detail["reasons"]
        
        # Add resolved_params to rejection telemetry (Requirement 6.1)
        # Include both multiplier and absolute values for debugging
        resolved_params = ctx.data.get("resolved_params")
        if resolved_params is not None:
            resolved_dict = resolved_params.to_dict() if hasattr(resolved_params, "to_dict") else resolved_params
            # Add to rejection_detail for rejected decisions
            if final_result == StageResult.REJECT:
                if payload.get("rejection_detail") is None:
                    payload["rejection_detail"] = {}
                payload["rejection_detail"]["resolved_params"] = resolved_dict
            # Always add to top-level for transparency
            payload["resolved_params"] = resolved_dict
        
        # Add gate decisions from context
        gate_decisions = ctx.data.get("gate_decisions") or []
        if gate_decisions:
            payload["gate_decisions"] = [
                gd.to_dict() if hasattr(gd, "to_dict") else gd
                for gd in gate_decisions
            ]
        execution_policy = ctx.data.get("execution_policy")
        if execution_policy is not None:
            if hasattr(execution_policy, "__dict__"):
                payload["execution_policy"] = {
                    "mode": getattr(execution_policy, "mode", None),
                    "ttl_ms": getattr(execution_policy, "ttl_ms", None),
                    "fallback_to_taker": getattr(execution_policy, "fallback_to_taker", None),
                    "reason": getattr(execution_policy, "reason", None),
                }
            elif isinstance(execution_policy, dict):
                payload["execution_policy"] = execution_policy

        comparisons = ctx.data.get("confirmation_shadow_comparisons")
        if isinstance(comparisons, list) and comparisons:
            payload["confirmation_shadow_comparisons"] = comparisons
            mismatch_count = 0
            mode_counts: Dict[str, int] = {}
            diff_reason_counts: Dict[str, int] = {}
            for item in comparisons:
                if not isinstance(item, dict):
                    continue
                if bool(item.get("diff")):
                    mismatch_count += 1
                    reason = str(item.get("diff_reason") or "unknown")
                    diff_reason_counts[reason] = diff_reason_counts.get(reason, 0) + 1
                mode_key = str(item.get("mode") or "unknown")
                mode_counts[mode_key] = mode_counts.get(mode_key, 0) + 1
            total_comparisons = len(comparisons)
            payload["confirmation_shadow_total"] = total_comparisons
            payload["confirmation_shadow_mismatches"] = mismatch_count
            payload["confirmation_shadow_disagreement_rate"] = (
                (mismatch_count / total_comparisons) if total_comparisons > 0 else 0.0
            )
            payload["confirmation_shadow_mode_counts"] = mode_counts
            payload["confirmation_shadow_diff_reason_counts"] = diff_reason_counts
        
        # Add snapshot summary if available
        snapshot = ctx.data.get("snapshot")
        if snapshot and hasattr(snapshot, "to_dict"):
            payload["snapshot"] = snapshot.to_dict()
        
        # Add candidate summary if available
        candidate = ctx.data.get("candidate")
        if candidate and hasattr(candidate, "to_dict"):
            payload["candidate"] = candidate.to_dict()
            candidate_confidence = _get_field(candidate, "confidence")
            try:
                if candidate_confidence is not None and payload.get("confidence") is None:
                    payload["confidence"] = float(candidate_confidence)
            except (TypeError, ValueError):
                pass

        prediction_ctx = ctx.data.get("prediction")
        if isinstance(prediction_ctx, dict):
            payload["prediction"] = prediction_ctx
            prediction_confidence = prediction_ctx.get("confidence")
            try:
                if prediction_confidence is not None:
                    payload["prediction_confidence"] = float(prediction_confidence)
                    # Prefer explicit prediction confidence for top-level confidence
                    # so dashboards/reporting show model confidence consistently.
                    payload["confidence"] = float(prediction_confidence)
            except (TypeError, ValueError):
                pass
        model_alignment = ctx.data.get("model_direction_alignment")
        if isinstance(model_alignment, dict):
            payload["model_direction_alignment"] = model_alignment

        # Canonical decision context for audit/reporting.
        raw_position_effect = str(signal_dict.get("position_effect") or "").strip().lower()
        is_exit_signal = bool(signal_dict.get("is_exit_signal")) or raw_position_effect == "close"
        if is_exit_signal:
            exit_reason = str(
                signal_dict.get("reason")
                or signal_dict.get("exit_reason")
                or ctx.rejection_reason
                or ""
            ).strip().lower()
            if any(token in exit_reason for token in {"emergency", "critical", "liquidation", "risk"}):
                payload["decision_context"] = "exit_emergency"
            else:
                payload["decision_context"] = "exit_non_emergency"
        else:
            payload["decision_context"] = "entry_live_signal"

        # Canonical prediction block reason.
        prediction_blocked_reason = None
        if isinstance(ctx.rejection_detail, dict):
            prediction_blocked_reason = ctx.rejection_detail.get("prediction_blocked_reason")
        if prediction_blocked_reason is None and isinstance(prediction_ctx, dict):
            if bool(prediction_ctx.get("reject")):
                prediction_blocked_reason = prediction_ctx.get("reason") or "prediction_reject_unspecified"
            elif prediction_ctx.get("abstain_reason"):
                prediction_blocked_reason = prediction_ctx.get("abstain_reason")
        if prediction_blocked_reason is not None:
            payload["prediction_blocked_reason"] = str(prediction_blocked_reason)
            if str(payload.get("rejection_reason") or "").strip().lower() == "prediction_blocked":
                # Surface the specific block cause in top-level rejection reason for UI readability.
                payload["rejection_reason_base"] = "prediction_blocked"
                payload["rejection_reason"] = str(prediction_blocked_reason)
                existing_reasons = payload.get("rejection_reasons")
                if isinstance(existing_reasons, list) and existing_reasons:
                    payload["rejection_reasons"] = [str(prediction_blocked_reason)] + [
                        str(reason) for reason in existing_reasons if str(reason) != str(prediction_blocked_reason)
                    ]
                else:
                    payload["rejection_reasons"] = [str(prediction_blocked_reason)]
        
        # Add metrics from gate decisions
        metrics = {}
        for gd in gate_decisions:
            gd_metrics = gd.metrics if hasattr(gd, "metrics") else (gd.get("metrics") if isinstance(gd, dict) else {})
            if gd_metrics:
                metrics.update(gd_metrics)
        if metrics:
            payload["metrics"] = metrics

        # Add EV gate details for accepted decisions (for post-trade analysis)
        ev_gate = ctx.data.get("ev_gate_result")
        expected_gross_edge_bps = None
        expected_net_edge_bps = None
        estimated_total_cost_bps = None
        if ev_gate is not None:
            expected_gross_edge_bps = coerce_float(getattr(ev_gate, "expected_gross_edge_bps", None))
            expected_net_edge_bps = coerce_float(getattr(ev_gate, "expected_net_edge_bps", None))
            estimated_total_cost_bps = coerce_float(getattr(ev_gate, "total_cost_bps", None))
            payload["ev_gate"] = {
                "ev": getattr(ev_gate, "EV", None),
                "ev_min": getattr(ev_gate, "ev_min_adjusted", None),
                "total_cost_bps": estimated_total_cost_bps,
                "p_calibrated": getattr(ev_gate, "p_calibrated", None),
                "p_min": getattr(ev_gate, "p_min", None),
                "R": getattr(ev_gate, "R", None),
                "C": getattr(ev_gate, "C", None),
            }
            if signal_side:
                payload["ev_gate"]["side"] = signal_side
        if expected_gross_edge_bps is None:
            expected_gross_edge_bps = coerce_float(expected_bps)
        if expected_net_edge_bps is None and expected_gross_edge_bps is not None and estimated_total_cost_bps is not None:
            expected_net_edge_bps = expected_gross_edge_bps - estimated_total_cost_bps
        if estimated_total_cost_bps is None:
            estimated_total_cost_bps = coerce_float(signal_dict.get("estimated_total_cost_bps"))
        payload["expected_gross_edge_bps"] = expected_gross_edge_bps
        payload["expected_net_edge_bps"] = expected_net_edge_bps
        payload["estimated_total_cost_bps"] = estimated_total_cost_bps

        directional_fields = build_directional_fields(prediction_ctx if isinstance(prediction_ctx, dict) else None, signal_side)
        if signal_side:
            payload["directional"] = {
                "side": signal_side,
                "rejected": final_result == StageResult.REJECT,
                "rejection_stage": ctx.rejection_stage,
                "ev": getattr(ev_gate, "EV", None) if ev_gate is not None else None,
                "p_calibrated": getattr(ev_gate, "p_calibrated", None) if ev_gate is not None else None,
                "p_min": getattr(ev_gate, "p_min", None) if ev_gate is not None else None,
            }
            payload["directional"].update(directional_fields)
        elif directional_fields:
            payload["directional"] = directional_fields

        for key in (
            "prediction_present",
            "prediction_direction",
            "prediction_source",
            "p_long_win",
            "p_short_win",
            "p_margin",
            "model_side",
            "signal_side",
            "direction_alignment_match",
        ):
            if key in directional_fields and key not in payload:
                payload[key] = directional_fields[key]
        
        return payload


def _trace_detail_enabled() -> bool:
    return os.getenv("DECISION_GATE_TRACE_VERBOSE") == "1"


def _exit_trace_enabled() -> bool:
    """Enable position exit evaluation tracing for debugging exit logic."""
    return os.getenv("POSITION_EXIT_TRACE", "").lower() in {"1", "true", "yes"}


def _normalize_symbol(symbol: str) -> str:
    """Normalize symbol for comparison across different exchange formats.
    
    Handles formats like:
    - BTCUSDT (binance)
    - BTC/USDT:USDT (ccxt unified)
    - BTC-USDT-SWAP (okx)
    """
    if not symbol:
        return ""
    # Remove settle suffix if present (e.g., BTC/USDT:USDT -> BTC/USDT)
    normalized = symbol.upper()
    if ":" in normalized:
        normalized = normalized.split(":", 1)[0]
    # Remove common separators and suffixes
    normalized = normalized.replace("/", "").replace("-", "")
    # Remove common suffixes
    for suffix in ["SWAP", "PERP", "PERPETUAL"]:
        if normalized.endswith(suffix):
            normalized = normalized[:-len(suffix)]
    return normalized


def _get_attr(source, key, default=None):
    if source is None:
        return default
    if isinstance(source, dict):
        return source.get(key, default)
    return getattr(source, key, default)


def _feature_snapshot(features: dict, market_context: dict) -> dict:
    return {
        "price": _get_attr(features, "price"),
        "spread": _get_attr(features, "spread"),
        "spread_bps": _get_attr(features, "spread_bps"),
        "position_in_value": _get_attr(features, "position_in_value"),
        "value_location_ctx": _get_attr(market_context, "value_location"),
        "point_of_control": _get_attr(features, "point_of_control"),
        "distance_to_poc": _get_attr(features, "distance_to_poc"),
        "distance_to_poc_bps": _get_attr(features, "distance_to_poc_bps"),
        "atr_5m": _get_attr(features, "atr_5m"),
        "atr_5m_baseline": _get_attr(features, "atr_5m_baseline"),
        "rotation_factor": _get_attr(features, "rotation_factor"),
        "orderflow_imbalance": _get_attr(features, "orderflow_imbalance"),
        "bid_depth_usd": _get_attr(features, "bid_depth_usd"),
        "ask_depth_usd": _get_attr(features, "ask_depth_usd"),
        "candle_count": _get_attr(market_context, "candle_count"),
        "timestamp": _get_attr(market_context, "timestamp"),
    }


def _market_context_snapshot(market_context: dict) -> dict:
    return {
        "session": _get_attr(market_context, "session"),
        "trend": _get_attr(market_context, "trend"),
        "volatility": _get_attr(market_context, "volatility"),
        "value_location": _get_attr(market_context, "value_location"),
        "risk_mode": _get_attr(market_context, "risk_mode"),
    }


def _env_float(key: str, default: float) -> float:
    raw = os.getenv(key)
    if not raw or not raw.strip():
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


def _normalize_signal_side(value: Optional[str]) -> Optional[str]:
    return normalize_side(value)


def _normalize_position_side(position) -> Optional[str]:
    return _normalize_signal_side(_get_attr(position, "side"))


def _extract_expected_edge_bps(signal: dict, ctx: StageContext) -> Optional[float]:
    for key in ("expected_edge_bps", "edge_bps"):
        value = signal.get(key)
        if value is not None:
            try:
                return float(value)
            except (TypeError, ValueError):
                return None
    candidate = ctx.data.get("candidate")
    if candidate is not None:
        value = getattr(candidate, "expected_edge_bps", None)
        if value is None and isinstance(candidate, dict):
            value = candidate.get("expected_edge_bps")
        try:
            return float(value) if value is not None else None
        except (TypeError, ValueError):
            return None
    return None


def _extract_signal_confidence(signal: dict) -> Optional[float]:
    for key in ("prediction_confidence", "confidence", "signal_confidence"):
        value = signal.get(key)
        if value is not None:
            try:
                return float(value)
            except (TypeError, ValueError):
                return None
    return None


def _normalize_timestamp_seconds(value: Optional[float]) -> Optional[float]:
    if value is None:
        return None
    try:
        ts = float(value)
    except (TypeError, ValueError):
        return None
    return ts / 1000.0 if ts > 1e12 else ts


def _maybe_allow_replacement(signal: object, ctx: StageContext) -> bool:
    if not isinstance(signal, dict):
        return False
    if signal.get("replace_position"):
        return True
    if os.getenv("ALLOW_POSITION_REPLACEMENT", "false").lower() not in {"1", "true", "yes"}:
        return False
    positions = ctx.data.get("positions") or []
    if not positions:
        return False
    risk_limits = ctx.data.get("risk_limits") or {}
    max_positions_per_symbol = risk_limits.get("max_positions_per_symbol")
    if max_positions_per_symbol is None:
        max_positions_per_symbol = int(_env_float("MAX_POSITIONS_PER_SYMBOL", 1))
    symbol_positions = [
        pos for pos in positions
        if _normalize_symbol(_get_attr(pos, "symbol")) == _normalize_symbol(ctx.symbol)
    ]
    if len(symbol_positions) < max_positions_per_symbol:
        return False
    existing = symbol_positions[0]
    new_side = _normalize_signal_side(signal.get("side"))
    existing_side = _normalize_position_side(existing)
    if not new_side or not existing_side:
        return False
    replace_opposite_only = os.getenv("REPLACE_OPPOSITE_ONLY", "true").lower() in {"1", "true", "yes"}
    if replace_opposite_only and new_side == existing_side:
        return False
    replace_min_hold_sec = _env_float("REPLACE_MIN_HOLD_SEC", 0.0)
    opened_at = _get_attr(existing, "opened_at")
    if replace_min_hold_sec > 0 and opened_at:
        try:
            opened_at_sec = _normalize_timestamp_seconds(opened_at)
            if opened_at_sec is not None and time.time() - opened_at_sec < replace_min_hold_sec:
                return False
        except (TypeError, ValueError):
            return False
    replace_min_edge_bps = _env_float("REPLACE_MIN_EDGE_BPS", 0.0)
    expected_edge_bps = _extract_expected_edge_bps(signal, ctx)
    if expected_edge_bps is not None and expected_edge_bps < replace_min_edge_bps:
        return False
    replace_min_confidence = _env_float("REPLACE_MIN_CONFIDENCE", 0.0)
    signal_confidence = _extract_signal_confidence(signal)
    if signal_confidence is not None and signal_confidence < replace_min_confidence:
        return False
    signal["replace_position"] = True
    signal["replace_reason"] = "replace_opposite_side" if new_side != existing_side else "replace_allowed"
    signal["replace_existing_side"] = existing_side
    signal["replace_existing_size"] = _get_attr(existing, "size")
    if expected_edge_bps is not None:
        signal["replace_expected_edge_bps"] = expected_edge_bps
    if signal_confidence is not None:
        signal["replace_signal_confidence"] = signal_confidence
    log_info(
        "risk_stage_replace_allowed",
        symbol=ctx.symbol,
        existing_side=existing_side,
        new_side=new_side,
        reason=signal["replace_reason"],
    )
    return True


def _should_block_existing_position(signal: object, ctx: StageContext) -> bool:
    if not isinstance(signal, dict):
        return False
    if signal.get("replace_position"):
        return False
    if os.getenv("BLOCK_IF_POSITION_EXISTS", "true").lower() not in {"1", "true", "yes"}:
        return False
    positions = ctx.data.get("positions") or []
    if not positions:
        return False
    risk_limits = ctx.data.get("risk_limits") or {}
    max_positions_per_symbol = risk_limits.get("max_positions_per_symbol")
    if max_positions_per_symbol is None:
        max_positions_per_symbol = int(_env_float("MAX_POSITIONS_PER_SYMBOL", 1))
    symbol_positions = [
        pos for pos in positions
        if _normalize_symbol(_get_attr(pos, "symbol")) == _normalize_symbol(ctx.symbol)
    ]
    return len(symbol_positions) >= max_positions_per_symbol


def _should_skip_entry_generation(ctx: StageContext) -> bool:
    if os.getenv("BLOCK_IF_POSITION_EXISTS", "true").lower() not in {"1", "true", "yes"}:
        return False
    if os.getenv("ALLOW_POSITION_REPLACEMENT", "false").lower() in {"1", "true", "yes"}:
        return False
    positions = ctx.data.get("positions") or []
    if not positions:
        return False
    risk_limits = ctx.data.get("risk_limits") or {}
    max_positions_per_symbol = risk_limits.get("max_positions_per_symbol")
    if max_positions_per_symbol is None:
        max_positions_per_symbol = int(_env_float("MAX_POSITIONS_PER_SYMBOL", 1))
    symbol_positions = [
        pos for pos in positions
        if _normalize_symbol(_get_attr(pos, "symbol")) == _normalize_symbol(ctx.symbol)
    ]
    return len(symbol_positions) >= max_positions_per_symbol


def _enforce_min_risk_params(signal: object, ctx: StageContext) -> None:
    if not isinstance(signal, dict):
        return
    entry_price = signal.get("entry_price") or _get_attr(ctx.data.get("market_context"), "price")
    stop_loss = signal.get("stop_loss")
    take_profit = signal.get("take_profit")
    side = _normalize_signal_side(signal.get("side"))
    if not entry_price or not stop_loss or not take_profit or not side:
        return
    try:
        entry_price = float(entry_price)
        stop_loss = float(stop_loss)
        take_profit = float(take_profit)
    except (TypeError, ValueError):
        return
    if entry_price <= 0:
        return
    raw_stop_loss = stop_loss
    repaired_geometry = False
    geometry_invalid = (
        (side == "long" and (stop_loss >= entry_price or take_profit <= entry_price))
        or (side == "short" and (stop_loss <= entry_price or take_profit >= entry_price))
    )
    market_context = ctx.data.get("market_context") or {}
    session = market_context.get("session")

    min_stop_bps = _env_float(
        "MIN_SIGNAL_STOP_DISTANCE_BPS",
        _env_float("EV_GATE_MIN_STOP_DISTANCE_BPS", 5.0),
    )
    min_rr = _env_float("MIN_SIGNAL_RR", 1.5)
    min_stop_bps = _resolve_symbol_session_float_override(
        symbol=ctx.symbol,
        session=session,
        base_value=min_stop_bps,
        by_symbol_env="MIN_SIGNAL_STOP_DISTANCE_BPS_BY_SYMBOL",
        by_symbol_session_env="MIN_SIGNAL_STOP_DISTANCE_BPS_BY_SYMBOL_SESSION",
    )
    min_rr = _resolve_symbol_session_float_override(
        symbol=ctx.symbol,
        session=session,
        base_value=min_rr,
        by_symbol_env="MIN_SIGNAL_RR_BY_SYMBOL",
        by_symbol_session_env="MIN_SIGNAL_RR_BY_SYMBOL_SESSION",
    )
    min_stop_bps = max(0.0, float(min_stop_bps))
    min_rr = max(0.0, float(min_rr))
    min_tp_bps = _env_float("MIN_SIGNAL_TP_DISTANCE_BPS", _env_float("PARAM_MIN_TAKE_PROFIT_BPS", 0.0))

    resolved_params = ctx.data.get("resolved_params")

    def _resolved_bps_value(field: str, fallback: float) -> float:
        raw_value = None
        if resolved_params is not None:
            if isinstance(resolved_params, dict):
                raw_value = resolved_params.get(field)
            else:
                raw_value = getattr(resolved_params, field, None)
        if raw_value is None:
            raw_value = fallback
        try:
            value = float(raw_value)
            return value if value > 0 else float(fallback)
        except (TypeError, ValueError):
            return float(fallback)

    max_stop_bps = _resolved_bps_value(
        "stop_loss_bps",
        _env_float("MAX_SIGNAL_STOP_DISTANCE_BPS", _env_float("PARAM_MAX_STOP_LOSS_BPS", 120.0)),
    )
    max_tp_bps = _resolved_bps_value(
        "take_profit_bps",
        _env_float("MAX_SIGNAL_TAKE_PROFIT_DISTANCE_BPS", _env_float("PARAM_MAX_TAKE_PROFIT_BPS", 180.0)),
    )

    adjusted = False
    if geometry_invalid:
        # Fix wrong-side SL/TP geometry before EV gate so invalid signals don't churn.
        if side == "long":
            stop_loss = entry_price * (1 - max(min_stop_bps, 1.0) / 10000)
            take_profit = max(take_profit, entry_price * (1 + (max(min_rr, 1.0) * max(min_stop_bps, 1.0) / 10000)))
        else:
            stop_loss = entry_price * (1 + max(min_stop_bps, 1.0) / 10000)
            take_profit = min(take_profit, entry_price * (1 - (max(min_rr, 1.0) * max(min_stop_bps, 1.0) / 10000)))
        adjusted = True
        repaired_geometry = True

    if side == "long":
        L_bps = (entry_price - stop_loss) / entry_price * 10000
        if L_bps < min_stop_bps:
            stop_loss = entry_price * (1 - min_stop_bps / 10000)
            adjusted = True
        L_bps = (entry_price - stop_loss) / entry_price * 10000
        G_bps = (take_profit - entry_price) / entry_price * 10000
        if L_bps > 0 and G_bps / L_bps < min_rr:
            take_profit = entry_price + (min_rr * (entry_price - stop_loss))
            adjusted = True
        G_bps = (take_profit - entry_price) / entry_price * 10000
        if min_tp_bps > 0 and G_bps < min_tp_bps:
            take_profit = entry_price * (1 + min_tp_bps / 10000)
            adjusted = True
    else:
        L_bps = (stop_loss - entry_price) / entry_price * 10000
        if L_bps < min_stop_bps:
            stop_loss = entry_price * (1 + min_stop_bps / 10000)
            adjusted = True
        L_bps = (stop_loss - entry_price) / entry_price * 10000
        G_bps = (entry_price - take_profit) / entry_price * 10000
        if L_bps > 0 and G_bps / L_bps < min_rr:
            take_profit = entry_price - (min_rr * (stop_loss - entry_price))
            adjusted = True
        G_bps = (entry_price - take_profit) / entry_price * 10000
        if min_tp_bps > 0 and G_bps < min_tp_bps:
            take_profit = entry_price * (1 - min_tp_bps / 10000)
            adjusted = True

    if side == "long":
        L_bps = (entry_price - stop_loss) / entry_price * 10000
        G_bps = (take_profit - entry_price) / entry_price * 10000
        if max_stop_bps > 0 and L_bps > max_stop_bps:
            stop_loss = entry_price * (1 - max_stop_bps / 10000)
            adjusted = True
        if max_tp_bps > 0 and G_bps > max_tp_bps:
            take_profit = entry_price * (1 + max_tp_bps / 10000)
            adjusted = True
    else:
        L_bps = (stop_loss - entry_price) / entry_price * 10000
        G_bps = (entry_price - take_profit) / entry_price * 10000
        if max_stop_bps > 0 and L_bps > max_stop_bps:
            stop_loss = entry_price * (1 + max_stop_bps / 10000)
            adjusted = True
        if max_tp_bps > 0 and G_bps > max_tp_bps:
            take_profit = entry_price * (1 - max_tp_bps / 10000)
            adjusted = True

    if side == "long":
        L_bps = (entry_price - stop_loss) / entry_price * 10000
        G_bps = (take_profit - entry_price) / entry_price * 10000
    else:
        L_bps = (stop_loss - entry_price) / entry_price * 10000
        G_bps = (entry_price - take_profit) / entry_price * 10000
    if adjusted:
        signal["stop_loss"] = stop_loss
        signal["take_profit"] = take_profit
    signal["sl_distance_bps"] = round(L_bps, 2)
    signal["tp_distance_bps"] = round(G_bps, 2)
    signal["sl_distance_bps_raw"] = round(abs((entry_price - raw_stop_loss) / entry_price * 10000), 2)
    signal["sl_fix_applied"] = bool(adjusted)
    signal["sl_geometry_repaired"] = bool(repaired_geometry)
    if adjusted:
        log_info(
            "signal_risk_params_adjusted",
            symbol=ctx.symbol,
            side=side,
            min_stop_bps=round(min_stop_bps, 2),
            min_rr=round(min_rr, 2),
            repaired_geometry=repaired_geometry,
        )


def _inject_signal_cost_estimate(signal: object, ctx: StageContext) -> None:
    if not isinstance(signal, dict):
        return
    if signal.get("cost_estimate_bps") is not None:
        return
    market_context = ctx.data.get("market_context") or {}
    features = ctx.data.get("features") or {}
    spread_bps = market_context.get("spread_bps") or features.get("spread_bps")
    try:
        spread_bps = float(spread_bps) if spread_bps is not None else 3.0
    except (TypeError, ValueError):
        spread_bps = 3.0
    fee_bps = _env_float("EV_GATE_FEE_BPS", _env_float("FEE_BPS", 7.0))
    slippage_bps = _env_float("EV_GATE_SLIPPAGE_BPS", _env_float("SLIPPAGE_BPS", 3.0))
    signal["cost_estimate_bps"] = float(spread_bps) + fee_bps + slippage_bps


def _inject_signal_identity(signal: object, ctx: StageContext) -> None:
    """Ensure strategy_id/profile_id are populated on signals for telemetry/execution."""
    if not signal:
        return

    def _get_field(source: object, key: str):
        if source is None:
            return None
        if isinstance(source, dict):
            return source.get(key)
        return getattr(source, key, None)

    def _set_field(target: object, key: str, value: Optional[str]) -> None:
        if not value:
            return
        if isinstance(target, dict):
            if not target.get(key):
                target[key] = value
            return
        try:
            if not getattr(target, key, None):
                setattr(target, key, value)
        except Exception:
            return

    # Profile id: signal -> ctx.profile_id -> matched_profile -> candidate -> confirmed
    profile_id = _get_field(signal, "profile_id")
    if not profile_id:
        profile_id = ctx.profile_id or _get_field(ctx.data.get("matched_profile"), "profile_id")
    if not profile_id:
        profile_id = (
            _get_field(ctx.data.get("candidate"), "profile_id")
            or _get_field(ctx.data.get("candidate_signal"), "profile_id")
            or _get_field(ctx.data.get("confirmed_signal"), "profile_id")
        )

    # Strategy id: signal -> candidate -> confirmed -> profile registry fallback
    strategy_id = _get_field(signal, "strategy_id")
    if not strategy_id:
        strategy_id = (
            _get_field(ctx.data.get("candidate"), "strategy_id")
            or _get_field(ctx.data.get("candidate_signal"), "strategy_id")
            or _get_field(ctx.data.get("confirmed_signal"), "strategy_id")
        )
    if not strategy_id and profile_id:
        try:
            spec = get_profile_registry().get_spec(profile_id)
            if spec and spec.strategy_ids:
                strategy_id = spec.strategy_ids[0]
        except Exception:
            strategy_id = None

    _set_field(signal, "profile_id", profile_id)
    _set_field(signal, "strategy_id", strategy_id)

    # If the strategy did not provide a calibrated p_hat, populate it from prediction.
    #
    # Priority:
    # 1) explicit prediction-level p_hat (e.g. fallback heuristics)
    # 2) side-aware extraction from per-class probabilities
    #
    # Contract:
    # - long -> p_hat = P(up)
    # - short -> p_hat = P(down)
    #
    # This only applies when probabilities are explicitly available. We do NOT
    # treat prediction["confidence"] as p_hat.
    if _get_field(signal, "p_hat") is None:
        pred = ctx.data.get("prediction") or {}
        pred_p_hat = pred.get("p_hat")
        pred_p_hat_source = pred.get("p_hat_source")
        if pred_p_hat is not None:
            try:
                p_val = float(pred_p_hat)
            except (TypeError, ValueError):
                p_val = None
            if p_val is not None:
                p_val = max(0.0, min(1.0, p_val))
                _set_field(signal, "p_hat", p_val)
                _set_field(signal, "p_hat_source", str(pred_p_hat_source or "prediction_p_hat"))
                return
        probs = pred.get("probs") or {}
        side = _normalize_signal_side(_get_field(signal, "side"))
        p_hat = None
        if side == "long":
            p_hat = pred.get("p_up") if pred.get("p_up") is not None else probs.get("up")
        elif side == "short":
            p_hat = pred.get("p_down") if pred.get("p_down") is not None else probs.get("down")
        if p_hat is not None:
            try:
                p_val = float(p_hat)
            except (TypeError, ValueError):
                p_val = None
            if p_val is not None:
                p_val = max(0.0, min(1.0, p_val))
                _set_field(signal, "p_hat", p_val)
                _set_field(signal, "p_hat_source", "prediction_p_hat")


def _serialize_positions(positions) -> list[dict]:
    serialized = []
    for position in positions or []:
        if isinstance(position, dict):
            serialized.append(position)
            continue
        payload = {}
        for key in (
            "symbol",
            "side",
            "size",
            "size_usd",
            "entry_price",
            "current_price",
            "unrealized_pnl",
            "realized_pnl",
        ):
            if hasattr(position, key):
                payload[key] = getattr(position, key)
        serialized.append(payload)
    return serialized
