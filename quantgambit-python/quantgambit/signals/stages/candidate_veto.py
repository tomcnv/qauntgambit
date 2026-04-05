"""
CandidateVetoStage - Side-aware post-candidate vetoes.

This stage runs AFTER CandidateGenerationStage (when we know the side).
It applies the key pre-trade vetoes that require knowledge of trade direction.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional, Dict, Set

from quantgambit.signals.pipeline import Stage, StageContext, StageResult
from quantgambit.deeptrader_core.types import MarketSnapshot, TradeCandidate, GateDecision
from quantgambit.observability.logger import log_info, log_warning
from quantgambit.signals.confirmation.evidence import evaluate_exit_orderflow, evaluate_exit_price_level
from quantgambit.strategies.disable_rules import (
    enabled_strategies_by_symbol_from_env,
    is_strategy_disabled_for_symbol,
)


def _parse_key_float_map(raw: str) -> Dict[str, float]:
    result: Dict[str, float] = {}
    if not raw:
        return result
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
            result[key] = float(value_raw.strip())
        except (TypeError, ValueError):
            continue
    return result


@dataclass
class CandidateVetoConfig:
    """Configuration for CandidateVetoStage."""
    # Orderflow veto thresholds (regime-scaled)
    orderflow_veto_base: float = 0.5  # Base threshold for orderflow veto
    orderflow_veto_trend_boost: float = 0.2  # Additional strictness in trending regime
    
    # Tradeability: edge must exceed costs
    min_net_edge_bps: float = 5.0  # Minimum edge after costs
    fee_bps: float = 2.0  # Estimated fee per side
    slippage_bps_multiplier: float = 1.0  # Multiplier for expected slippage
    net_edge_buffer_bps: float = 0.0  # Extra buffer added to costs
    
    # Regime compatibility
    # Strategies in these sets are blocked in incompatible regimes
    mean_reversion_strategies: Set[str] = None
    trend_following_strategies: Set[str] = None
    breakout_strategies: Set[str] = None
    breakout_allowed_vol_regimes: Set[str] = None
    
    # Trend strength threshold for regime blocking
    trend_strength_block_mean_reversion: float = 0.7
    trend_strength_block_trend_following: float = 0.3

    # Execution quality veto thresholds
    max_spread_bps: float = 15.0
    min_depth_usd: float = 500.0
    max_slippage_bps: float = 30.0
    max_slippage_bps_by_symbol: Dict[str, float] = None
    max_slippage_bps_by_symbol_session: Dict[str, float] = None
    slippage_tolerance_bps: float = 0.25
    min_net_edge_bps_by_symbol: Dict[str, float] = None
    min_net_edge_bps_by_symbol_session: Dict[str, float] = None
    min_data_quality_score: float = 0.1
    max_snapshot_age_ms: float = 8000.0
    prevent_immediate_invalidation_entry: bool = True
    require_green_readiness: bool = False
    enforce_side_quality_gate: bool = True
    side_quality_fail_closed: bool = False
    side_quality_min_samples: int = 100
    min_directional_accuracy_long: float = 0.50
    min_directional_accuracy_short: float = 0.50
    orderflow_veto_base_by_symbol: Dict[str, float] = None
    orderflow_veto_base_by_symbol_session: Dict[str, float] = None
    mean_reversion_max_adverse_orderflow_by_symbol: Dict[str, float] = None
    pre_entry_invalidation_flow_threshold_by_symbol: Dict[str, float] = None
    disable_short_entries: bool = False
    min_gross_edge_to_cost_ratio: float = 1.0
    allow_env_overrides: bool = False

    def __post_init__(self):
        if self.mean_reversion_strategies is None:
            self.mean_reversion_strategies = {
                "mean_reversion_fade",
                "poc_magnet_scalp",
                "amt_value_area_rejection_scalp",
                "spread_compression",
                "vwap_reversion",
                "low_vol_grind",
                "liquidity_hunt",
            }
        if self.trend_following_strategies is None:
            self.trend_following_strategies = {
                "trend_pullback",
                "us_open_momentum",
                "opening_range_breakout",
                "high_vol_breakout",
            }
        if self.breakout_strategies is None:
            self.breakout_strategies = {
                "opening_range_breakout",
                "breakout_scalp",
                "high_vol_breakout",
                "vol_expansion",
            }
        if self.breakout_allowed_vol_regimes is None:
            # Default: only allow breakouts in higher-vol regimes
            self.breakout_allowed_vol_regimes = {"high", "expansion"}
        # Optional env overrides for trend strength thresholds
        by_symbol = os.getenv("CANDIDATE_VETO_ORDERFLOW_BASE_BY_SYMBOL", "")
        if by_symbol:
            self.orderflow_veto_base_by_symbol = _parse_key_float_map(by_symbol)
        by_symbol_session = os.getenv("CANDIDATE_VETO_ORDERFLOW_BASE_BY_SYMBOL_SESSION", "")
        if by_symbol_session:
            self.orderflow_veto_base_by_symbol_session = _parse_key_float_map(by_symbol_session)
        mean_rev_adverse = os.getenv("MEAN_REVERSION_MAX_ADVERSE_ORDERFLOW_BY_SYMBOL", "")
        if mean_rev_adverse:
            self.mean_reversion_max_adverse_orderflow_by_symbol = _parse_key_float_map(mean_rev_adverse)
        pre_entry_flow_thresholds = os.getenv("PRE_ENTRY_INVALIDATION_FLOW_THRESHOLD_BY_SYMBOL", "")
        if pre_entry_flow_thresholds:
            self.pre_entry_invalidation_flow_threshold_by_symbol = _parse_key_float_map(pre_entry_flow_thresholds)

        if self.allow_env_overrides:
            try:
                mean_rev_override = os.getenv("CANDIDATE_VETO_TREND_BLOCK_MEAN_REVERSION")
                if mean_rev_override is not None and mean_rev_override != "":
                    self.trend_strength_block_mean_reversion = float(mean_rev_override)
                trend_follow_override = os.getenv("CANDIDATE_VETO_TREND_BLOCK_TREND_FOLLOWING")
                if trend_follow_override is not None and trend_follow_override != "":
                    self.trend_strength_block_trend_following = float(trend_follow_override)
            except ValueError:
                log_warning(
                    "candidate_veto_env_override_invalid",
                    orderflow_base_by_symbol=os.getenv("CANDIDATE_VETO_ORDERFLOW_BASE_BY_SYMBOL"),
                    orderflow_base_by_symbol_session=os.getenv("CANDIDATE_VETO_ORDERFLOW_BASE_BY_SYMBOL_SESSION"),
                    mean_reversion=os.getenv("CANDIDATE_VETO_TREND_BLOCK_MEAN_REVERSION"),
                    trend_following=os.getenv("CANDIDATE_VETO_TREND_BLOCK_TREND_FOLLOWING"),
                )
            # Tradeability env overrides
            try:
                min_net_edge = os.getenv("MIN_NET_EDGE_BPS")
                if min_net_edge is not None and min_net_edge != "":
                    self.min_net_edge_bps = float(min_net_edge)
                fee_bps = os.getenv("FEE_BPS")
                if fee_bps is not None and fee_bps != "":
                    self.fee_bps = float(fee_bps)
                slippage_mult = os.getenv("SLIPPAGE_BPS_MULTIPLIER")
                if slippage_mult is not None and slippage_mult != "":
                    self.slippage_bps_multiplier = float(slippage_mult)
                edge_buffer = os.getenv("NET_EDGE_BUFFER_BPS")
                if edge_buffer is not None and edge_buffer != "":
                    self.net_edge_buffer_bps = float(edge_buffer)
            except ValueError:
                log_warning(
                    "candidate_veto_tradeability_env_invalid",
                    min_net_edge=os.getenv("MIN_NET_EDGE_BPS"),
                    fee_bps=os.getenv("FEE_BPS"),
                    slippage_mult=os.getenv("SLIPPAGE_BPS_MULTIPLIER"),
                    edge_buffer=os.getenv("NET_EDGE_BUFFER_BPS"),
                )
            # Breakout regime env override
            breakout_env = os.getenv("BREAKOUT_ALLOWED_VOL_REGIMES")
            if breakout_env:
                self.breakout_allowed_vol_regimes = {
                    s.strip().lower()
                    for s in breakout_env.split(",")
                    if s.strip()
                }
            # Execution-quality env overrides
            try:
                max_spread = os.getenv("EXECUTION_MAX_SPREAD_BPS")
                if max_spread is not None and max_spread != "":
                    self.max_spread_bps = float(max_spread)
                min_depth = os.getenv("EXECUTION_MIN_DEPTH_USD")
                if min_depth is not None and min_depth != "":
                    self.min_depth_usd = float(min_depth)
                max_slip = os.getenv("EXECUTION_MAX_SLIPPAGE_BPS")
                if max_slip is not None and max_slip != "":
                    self.max_slippage_bps = float(max_slip)
                self.max_slippage_bps_by_symbol = _parse_key_float_map(
                    os.getenv("EXECUTION_MAX_SLIPPAGE_BPS_BY_SYMBOL", "")
                )
                self.max_slippage_bps_by_symbol_session = _parse_key_float_map(
                    os.getenv("EXECUTION_MAX_SLIPPAGE_BPS_BY_SYMBOL_SESSION", "")
                )
                self.min_net_edge_bps_by_symbol = _parse_key_float_map(
                    os.getenv("MIN_NET_EDGE_BPS_BY_SYMBOL", "")
                )
                self.min_net_edge_bps_by_symbol_session = _parse_key_float_map(
                    os.getenv("MIN_NET_EDGE_BPS_BY_SYMBOL_SESSION", "")
                )
                min_dq = os.getenv("EXECUTION_MIN_DATA_QUALITY_SCORE")
                if min_dq is not None and min_dq != "":
                    self.min_data_quality_score = float(min_dq)
                max_age = os.getenv("EXECUTION_MAX_SNAPSHOT_AGE_MS")
                if max_age is not None and max_age != "":
                    self.max_snapshot_age_ms = float(max_age)
                pre_inv = os.getenv("CANDIDATE_VETO_PREVENT_IMMEDIATE_INVALIDATION_ENTRY")
                if pre_inv is not None and pre_inv != "":
                    self.prevent_immediate_invalidation_entry = pre_inv.strip().lower() in {
                        "1",
                        "true",
                        "yes",
                        "on",
                    }
                require_green = os.getenv("CANDIDATE_VETO_REQUIRE_GREEN_READINESS")
                if require_green is not None and require_green != "":
                    self.require_green_readiness = require_green.strip().lower() in {
                        "1",
                        "true",
                        "yes",
                        "on",
                    }
                enforce_side_quality = os.getenv("CANDIDATE_VETO_ENFORCE_SIDE_QUALITY_GATE")
                if enforce_side_quality is not None and enforce_side_quality != "":
                    self.enforce_side_quality_gate = enforce_side_quality.strip().lower() in {
                        "1",
                        "true",
                        "yes",
                        "on",
                    }
                side_quality_fail_closed = os.getenv("CANDIDATE_VETO_SIDE_QUALITY_FAIL_CLOSED")
                if side_quality_fail_closed is not None and side_quality_fail_closed != "":
                    self.side_quality_fail_closed = side_quality_fail_closed.strip().lower() in {
                        "1",
                        "true",
                        "yes",
                        "on",
                    }
                side_quality_min_samples = os.getenv("CANDIDATE_VETO_SIDE_QUALITY_MIN_SAMPLES")
                if side_quality_min_samples is not None and side_quality_min_samples != "":
                    self.side_quality_min_samples = max(0, int(float(side_quality_min_samples)))
                min_da_long = os.getenv("CANDIDATE_VETO_MIN_DIRECTIONAL_ACCURACY_LONG")
                if min_da_long is not None and min_da_long != "":
                    self.min_directional_accuracy_long = max(0.0, min(1.0, float(min_da_long)))
                min_da_short = os.getenv("CANDIDATE_VETO_MIN_DIRECTIONAL_ACCURACY_SHORT")
                if min_da_short is not None and min_da_short != "":
                    self.min_directional_accuracy_short = max(0.0, min(1.0, float(min_da_short)))
                disable_shorts = os.getenv("CANDIDATE_VETO_DISABLE_SHORT_ENTRIES")
                if disable_shorts is not None and disable_shorts != "":
                    self.disable_short_entries = disable_shorts.strip().lower() in {
                        "1",
                        "true",
                        "yes",
                        "on",
                    }
                min_edge_to_cost_ratio = os.getenv("CANDIDATE_VETO_MIN_GROSS_EDGE_TO_COST_RATIO")
                if min_edge_to_cost_ratio is not None and min_edge_to_cost_ratio != "":
                    self.min_gross_edge_to_cost_ratio = max(0.0, float(min_edge_to_cost_ratio))
            except ValueError:
                log_warning(
                    "candidate_veto_execution_env_invalid",
                    max_spread=os.getenv("EXECUTION_MAX_SPREAD_BPS"),
                    min_depth=os.getenv("EXECUTION_MIN_DEPTH_USD"),
                    max_slippage=os.getenv("EXECUTION_MAX_SLIPPAGE_BPS"),
                    min_data_quality=os.getenv("EXECUTION_MIN_DATA_QUALITY_SCORE"),
                    max_snapshot_age=os.getenv("EXECUTION_MAX_SNAPSHOT_AGE_MS"),
                )


class CandidateVetoStage(Stage):
    """
    Side-aware veto stage that runs after candidate generation.
    
    Now that we know the trade direction, we can apply:
    1. Orderflow veto (direction-specific)
    2. Regime gate (strategy/regime compatibility)
    3. Tradeability check (edge vs costs)
    4. Per-strategy custom constraints
    
    This is the "real" PreTradeVeto - it just runs after we have a candidate.
    """
    name = "candidate_veto"
    
    def __init__(self, config: Optional[CandidateVetoConfig] = None):
        self.config = config or CandidateVetoConfig(allow_env_overrides=True)
        self._trace_enabled = os.getenv("CANDIDATE_VETO_TRACE", "").lower() in {"1", "true"}
        allowed_raw = os.getenv("PREDICTION_ALLOWED_DIRECTIONS", "")
        self._allowed_directions = {
            token.strip().lower()
            for token in allowed_raw.split(",")
            if token.strip()
        }
        disabled_mean_rev = os.getenv("DISABLE_MEAN_REVERSION_SYMBOLS", "")
        self._disabled_mean_rev_symbols = {
            s.strip().upper()
            for s in disabled_mean_rev.split(",")
            if s.strip()
        }
        disabled_strategies = os.getenv("DISABLE_STRATEGIES", "")
        self._disabled_strategies = {
            s.strip()
            for s in disabled_strategies.split(",")
            if s.strip()
        }
        self._enabled_strategies_by_symbol = enabled_strategies_by_symbol_from_env()

    def _resolve_orderflow_base_threshold(self, symbol: str, session: Optional[str]) -> float:
        base = float(self.config.orderflow_veto_base)
        symbol_key = (symbol or "").strip().upper()
        session_key = (session or "").strip().upper()
        by_symbol = self.config.orderflow_veto_base_by_symbol or {}
        by_symbol_session = self.config.orderflow_veto_base_by_symbol_session or {}
        if symbol_key in by_symbol:
            base = float(by_symbol[symbol_key])
        composite_key = f"{symbol_key}@{session_key}" if symbol_key and session_key else ""
        if composite_key and composite_key in by_symbol_session:
            base = float(by_symbol_session[composite_key])
        return max(0.0, base)

    def _resolve_mean_reversion_orderflow_cap(self, symbol: str) -> Optional[float]:
        symbol_key = (symbol or "").strip().upper()
        if not symbol_key:
            return None
        overrides = self.config.mean_reversion_max_adverse_orderflow_by_symbol or {}
        if symbol_key not in overrides:
            return None
        return max(0.0, float(overrides[symbol_key]))

    def _resolve_max_slippage_threshold(self, symbol: str, session: Optional[str]) -> float:
        threshold = float(self.config.max_slippage_bps)
        symbol_key = (symbol or "").strip().upper()
        session_key = (session or "").strip().upper()
        by_symbol = self.config.max_slippage_bps_by_symbol or {}
        by_symbol_session = self.config.max_slippage_bps_by_symbol_session or {}
        if symbol_key in by_symbol:
            threshold = float(by_symbol[symbol_key])
        composite_key = f"{symbol_key}@{session_key}" if symbol_key and session_key else ""
        if composite_key and composite_key in by_symbol_session:
            threshold = float(by_symbol_session[composite_key])
        return max(0.0, threshold)

    def _resolve_min_net_edge_threshold(self, symbol: str, session: Optional[str]) -> float:
        threshold = float(self.config.min_net_edge_bps)
        symbol_key = (symbol or "").strip().upper()
        session_key = (session or "").strip().upper()
        by_symbol = self.config.min_net_edge_bps_by_symbol or {}
        by_symbol_session = self.config.min_net_edge_bps_by_symbol_session or {}
        if symbol_key in by_symbol:
            threshold = float(by_symbol[symbol_key])
        composite_key = f"{symbol_key}@{session_key}" if symbol_key and session_key else ""
        if composite_key and composite_key in by_symbol_session:
            threshold = float(by_symbol_session[composite_key])
        return max(0.0, threshold)
    
    async def run(self, ctx: StageContext) -> StageResult:
        reasons = []
        metrics = {}
        
        # Get candidate (may not exist for exit signals)
        candidate: Optional[TradeCandidate] = ctx.data.get("candidate")
        snapshot: Optional[MarketSnapshot] = ctx.data.get("snapshot")
        
        # Exit signals bypass candidate veto
        signal = ctx.signal
        if signal:
            if isinstance(signal, dict):
                is_exit = signal.get("is_exit_signal", False) or signal.get("reduce_only", False)
            else:
                is_exit = getattr(signal, "is_exit_signal", False) or getattr(signal, "reduce_only", False)
            
            if is_exit:
                if self._trace_enabled:
                    log_info(
                        "candidate_veto_exit_bypass",
                        symbol=ctx.symbol,
                    )
                return StageResult.CONTINUE
        
        if not candidate:
            # No candidate - nothing to veto, this is expected for exit signals
            return StageResult.CONTINUE
        
        if not snapshot:
            reasons.append("no_snapshot")
            return self._reject(ctx, candidate, reasons, metrics)
        
        side = candidate.side
        market_context = ctx.data.get("market_context") or {}
        session = market_context.get("session")
        metrics["side"] = side
        metrics["strategy_id"] = candidate.strategy_id

        if self.config.disable_short_entries and side == "short":
            reasons.append("direction_policy_blocked:short_disabled")
            return self._reject(ctx, candidate, reasons, metrics)

        # Hard direction guard: do not allow candidate-side entries that conflict
        # with runtime direction policy (e.g. short disabled via up,flat).
        if self._allowed_directions:
            side_direction = "down" if side == "short" else "up" if side == "long" else None
            if side_direction and side_direction not in self._allowed_directions:
                reasons.append(f"direction_policy_blocked:{side_direction}")
                metrics["allowed_directions"] = sorted(self._allowed_directions)
                return self._reject(ctx, candidate, reasons, metrics)

        # =================================================================
        # Check 0: Hard disable specific strategies via env
        # =================================================================
        if is_strategy_disabled_for_symbol(
            candidate.strategy_id,
            ctx.symbol,
            disabled_strategies=self._disabled_strategies,
            disabled_mean_rev_symbols=self._disabled_mean_rev_symbols,
            enabled_strategies_by_symbol=self._enabled_strategies_by_symbol,
        ):
            if candidate.strategy_id in self._disabled_strategies:
                reasons.append("strategy_disabled")
                metrics["disabled_strategy"] = candidate.strategy_id
                return self._reject(ctx, candidate, reasons, metrics)
            if (
                candidate.strategy_id in self.config.mean_reversion_strategies
                and ctx.symbol
                and ctx.symbol.upper() in self._disabled_mean_rev_symbols
            ):
                reasons.append("mean_reversion_disabled_for_symbol")
                metrics["symbol"] = ctx.symbol
                metrics["disabled_mean_reversion"] = True
                return self._reject(ctx, candidate, reasons, metrics)
            reasons.append("strategy_disabled_for_symbol")
            metrics["disabled_strategy"] = candidate.strategy_id
            return self._reject(ctx, candidate, reasons, metrics)

        # =================================================================
        # Check 0.5: Execution Quality Veto
        # =================================================================
        exec_veto = self._check_execution_quality(snapshot, symbol=ctx.symbol, session=session)
        if exec_veto:
            reasons.append(exec_veto)
            metrics["execution_vetoed"] = True
            return self._reject(ctx, candidate, reasons, metrics)

        # =================================================================
        # Check 0.6: Readiness and Side-Quality Veto
        # =================================================================
        readiness_veto = self._check_readiness_quality(ctx)
        if readiness_veto:
            reasons.append(readiness_veto)
            metrics["readiness_vetoed"] = True
            return self._reject(ctx, candidate, reasons, metrics)
        side_quality_veto = self._check_side_quality_gate(
            side=side,
            market_context=market_context,
        )
        if side_quality_veto:
            reasons.append(side_quality_veto)
            metrics["side_quality_vetoed"] = True
            return self._reject(ctx, candidate, reasons, metrics)

        # =================================================================
        # Check 0.75: Mirror invalidation exits pre-entry
        # =================================================================
        immediate_invalidation = self._check_immediate_invalidation_risk(candidate, snapshot, market_context)
        if immediate_invalidation:
            reasons.append(immediate_invalidation)
            metrics["immediate_invalidation_vetoed"] = True
            return self._reject(ctx, candidate, reasons, metrics)
        
        # =================================================================
        # Check 1: Orderflow Veto (side-aware)
        # =================================================================
        orderflow_base_threshold = self._resolve_orderflow_base_threshold(ctx.symbol, session)
        metrics["orderflow_veto_base"] = orderflow_base_threshold
        orderflow_result = self._check_orderflow_veto(candidate, snapshot, orderflow_base_threshold)
        if orderflow_result:
            reasons.append(orderflow_result)
            metrics["orderflow_vetoed"] = True
        
        # =================================================================
        # Check 2: Regime Gate (strategy/regime compatibility)
        # =================================================================
        regime_result = self._check_regime_compatibility(candidate, snapshot)
        if regime_result:
            reasons.append(regime_result)
            metrics["regime_vetoed"] = True
        
        # =================================================================
        # Check 3: Tradeability (edge vs costs)
        # =================================================================
        ev_gate_result = ctx.data.get("ev_gate_result")
        tradeability_result = self._check_tradeability(
            candidate,
            snapshot,
            ev_gate_result=ev_gate_result,
            symbol=ctx.symbol,
            session=session,
        )
        if tradeability_result:
            reasons.append(tradeability_result)
            metrics["tradeability_vetoed"] = True
        
        # Store metrics for telemetry
        metrics["expected_edge_bps"] = candidate.expected_edge_bps
        metrics["imb_5s"] = snapshot.imb_5s
        metrics["trend_strength"] = snapshot.trend_strength
        metrics["trend_direction"] = snapshot.trend_direction
        
        if reasons:
            return self._reject(ctx, candidate, reasons, metrics)
        
        # Store gate decision for telemetry
        ctx.data["gate_decisions"] = ctx.data.get("gate_decisions") or []
        ctx.data["gate_decisions"].append(GateDecision(
            allowed=True,
            gate_name=self.name,
            reasons=[],
            metrics=metrics,
        ))
        
        if self._trace_enabled:
            log_info(
                "candidate_veto_pass",
                symbol=ctx.symbol,
                side=side,
                strategy_id=candidate.strategy_id,
                expected_edge_bps=round(candidate.expected_edge_bps, 2),
            )
        
        return StageResult.CONTINUE
    
    def _check_orderflow_veto(
        self,
        candidate: TradeCandidate,
        snapshot: MarketSnapshot,
        orderflow_veto_base: Optional[float] = None,
    ) -> Optional[str]:
        """
        Check orderflow veto with regime-scaled thresholds.
        
        In trending regimes, we're stricter about entering against the flow:
        - In uptrend: shorts require stricter allowance (lower threshold)
        - In downtrend: longs require stricter allowance (higher threshold)
        """
        side = candidate.side
        imb = snapshot.imb_5s  # Use 5-second smoothed imbalance
        trend = snapshot.trend_direction
        trend_strength = snapshot.trend_strength
        
        # Calculate regime-adjusted threshold
        base_threshold = (
            float(orderflow_veto_base)
            if orderflow_veto_base is not None
            else float(self.config.orderflow_veto_base)
        )
        symbol = (candidate.symbol or "").strip().upper()
        strategy_id = str(candidate.strategy_id or "").strip().lower()
        mean_reversion_cap = None
        if strategy_id == "mean_reversion_fade":
            mean_reversion_cap = self._resolve_mean_reversion_orderflow_cap(symbol)
        
        # Regime scaling: stricter when trading against trend
        if side == "long" and trend == "down" and trend_strength > 0.3:
            # Trying to long in downtrend - need stronger positive flow
            threshold = -(base_threshold - self.config.orderflow_veto_trend_boost)
        elif side == "short" and trend == "up" and trend_strength > 0.3:
            # Trying to short in uptrend - need stronger negative flow
            threshold = base_threshold + self.config.orderflow_veto_trend_boost
        elif side == "long":
            threshold = -base_threshold
        else:  # short
            threshold = base_threshold

        if mean_reversion_cap is not None:
            if side == "short":
                threshold = max(threshold, mean_reversion_cap)
            else:
                threshold = min(threshold, -mean_reversion_cap)
        
        # Apply veto
        if side == "long" and imb < threshold:
            return f"orderflow_veto_long:imb_5s={imb:.2f}<{threshold:.2f}"
        elif side == "short" and imb > threshold:
            return f"orderflow_veto_short:imb_5s={imb:.2f}>{threshold:.2f}"
        
        return None
    
    def _check_regime_compatibility(
        self, candidate: TradeCandidate, snapshot: MarketSnapshot
    ) -> Optional[str]:
        """
        Check strategy/regime compatibility.
        
        - Mean reversion blocked when trend_strength > threshold
        - Trend following blocked when trend_strength < threshold in low vol
        """
        strategy_id = candidate.strategy_id.lower()
        trend_strength = snapshot.trend_strength
        vol_regime = snapshot.vol_regime
        
        # Mean reversion in strong trend = bad
        if strategy_id in self.config.mean_reversion_strategies:
            if trend_strength > self.config.trend_strength_block_mean_reversion:
                return f"regime_veto:mean_reversion_in_trend:strength={trend_strength:.2f}"
        
        # Trend following in low vol + weak trend = bad
        if strategy_id in self.config.trend_following_strategies:
            if vol_regime == "low" and trend_strength < self.config.trend_strength_block_trend_following:
                return f"regime_veto:trend_following_no_trend:strength={trend_strength:.2f},vol={vol_regime}"
        
        # Breakout strategies only in specified volatility regimes
        if strategy_id in self.config.breakout_strategies:
            if vol_regime not in self.config.breakout_allowed_vol_regimes:
                return f"regime_veto:breakout_wrong_vol:vol={vol_regime}"
        
        return None

    def _check_tradeability(
        self,
        candidate: TradeCandidate,
        snapshot: MarketSnapshot,
        ev_gate_result: Optional[object] = None,
        symbol: Optional[str] = None,
        session: Optional[str] = None,
    ) -> Optional[str]:
        """
        Check that expected edge exceeds costs.
        
        expected_edge_bps is treated as net edge. When EVGate is available,
        prefer G_bps - total_cost_bps for a consistent cost model.
        """
        expected_edge = candidate.expected_edge_bps
        edge_source = "candidate"
        total_cost_bps = None
        gross_edge_bps = None
        if ev_gate_result is not None:
            try:
                g_bps = float(getattr(ev_gate_result, "G_bps", 0.0))
                gross_edge_bps = g_bps
                total_cost_bps = getattr(ev_gate_result, "total_cost_bps", None)
                if total_cost_bps is not None:
                    expected_edge = g_bps - float(total_cost_bps)
                    edge_source = "ev_gate"
            except (TypeError, ValueError):
                pass

        # Apply buffer (extra margin) after net edge.
        net_edge = expected_edge - self.config.net_edge_buffer_bps
        min_net_edge_threshold = self._resolve_min_net_edge_threshold(symbol or candidate.symbol, session)
        if self._trace_enabled:
            log_info(
                "candidate_veto_edge_components",
                symbol=candidate.symbol,
                side=candidate.side,
                strategy_id=candidate.strategy_id,
                expected_edge_bps=round(expected_edge, 2),
                edge_source=edge_source,
                total_cost_bps=round(float(total_cost_bps), 2) if total_cost_bps is not None else None,
                edge_buffer_bps=round(self.config.net_edge_buffer_bps, 2),
                net_edge_bps=round(net_edge, 2),
                min_net_edge_bps=round(min_net_edge_threshold, 2),
            )

        if (
            gross_edge_bps is not None
            and total_cost_bps is not None
            and float(total_cost_bps) > 0.0
            and self.config.min_gross_edge_to_cost_ratio > 0.0
        ):
            gross_to_cost_ratio = gross_edge_bps / float(total_cost_bps)
            if gross_to_cost_ratio + 1e-9 < self.config.min_gross_edge_to_cost_ratio:
                return (
                    "tradeability_veto:gross_cost_ratio="
                    f"{gross_to_cost_ratio:.2f}<{self.config.min_gross_edge_to_cost_ratio:.2f}"
                )
        
        if net_edge < min_net_edge_threshold:
            return f"tradeability_veto:net_edge={net_edge:.1f}bps<{min_net_edge_threshold:.1f}bps"
        
        return None

    def _check_execution_quality(
        self,
        snapshot: MarketSnapshot,
        *,
        symbol: Optional[str] = None,
        session: Optional[str] = None,
    ) -> Optional[str]:
        """Veto trades when execution quality is poor."""
        max_slippage_threshold = self._resolve_max_slippage_threshold(symbol or snapshot.symbol, session)
        if snapshot.snapshot_age_ms > self.config.max_snapshot_age_ms:
            return f"execution_veto:stale_snapshot:{snapshot.snapshot_age_ms:.0f}ms"
        if snapshot.data_quality_score < self.config.min_data_quality_score:
            return f"execution_veto:low_data_quality:{snapshot.data_quality_score:.2f}"
        if snapshot.spread_bps > self.config.max_spread_bps:
            return f"execution_veto:wide_spread:{snapshot.spread_bps:.2f}bps"
        if snapshot.ask_depth_usd < self.config.min_depth_usd or snapshot.bid_depth_usd < self.config.min_depth_usd:
            return "execution_veto:thin_depth"
        if snapshot.expected_fill_slippage_bps > (max_slippage_threshold + float(self.config.slippage_tolerance_bps or 0.0)):
            return (
                f"execution_veto:high_slippage:{snapshot.expected_fill_slippage_bps:.2f}bps>"
                f"{max_slippage_threshold:.2f}"
            )
        return None

    def _check_readiness_quality(self, ctx: StageContext) -> Optional[str]:
        if not self.config.require_green_readiness:
            return None
        readiness_raw = ctx.data.get("readiness_level")
        # `readiness_level` can be an enum (ReadinessLevel.GREEN) or plain string.
        # Use enum `.value` when available; stringifying enum names causes false vetoes
        # like `execution_veto:readiness_readinesslevel.green`.
        readiness_val = getattr(readiness_raw, "value", readiness_raw)
        readiness = str(readiness_val or "").strip().lower()
        if not readiness:
            return "execution_veto:missing_readiness_level"
        if readiness != "green":
            return f"execution_veto:readiness_{readiness}"
        return None

    def _check_side_quality_gate(
        self,
        *,
        side: str,
        market_context: Dict[str, object],
    ) -> Optional[str]:
        if not self.config.enforce_side_quality_gate:
            return None
        metrics = market_context.get("prediction_score_gate_metrics")
        if not isinstance(metrics, dict):
            if self.config.side_quality_fail_closed:
                return "side_quality_veto:metrics_missing"
            return None

        samples_raw = metrics.get("samples")
        try:
            samples = int(samples_raw) if samples_raw is not None else 0
        except (TypeError, ValueError):
            samples = 0
        if samples < self.config.side_quality_min_samples:
            return f"side_quality_veto:low_samples:{samples}<{self.config.side_quality_min_samples}"

        key = "directional_accuracy_long" if side == "long" else "directional_accuracy_short"
        threshold = (
            self.config.min_directional_accuracy_long
            if side == "long"
            else self.config.min_directional_accuracy_short
        )
        raw_val = metrics.get(key)
        if raw_val is None:
            if self.config.side_quality_fail_closed:
                return f"side_quality_veto:{key}_missing"
            return None
        try:
            value = float(raw_val)
        except (TypeError, ValueError):
            if self.config.side_quality_fail_closed:
                return f"side_quality_veto:{key}_invalid"
            return None
        if value > 1.0:
            value = value / 100.0
        value = max(0.0, min(1.0, value))
        if value < threshold:
            return f"side_quality_veto:{side}_directional_accuracy:{value:.3f}<{threshold:.3f}"
        return None

    def _check_immediate_invalidation_risk(
        self,
        candidate: TradeCandidate,
        snapshot: MarketSnapshot,
        market_context: Dict[str, object],
    ) -> Optional[str]:
        """
        Block entries that already satisfy invalidation-exit conditions.

        This keeps entry/exit semantics aligned and prevents immediate churn:
        enter -> invalidation exit within seconds.
        """
        if not self.config.prevent_immediate_invalidation_entry:
            return None

        side = candidate.side
        strategy_id = str(candidate.strategy_id or "").strip().lower()
        profile_id = str(getattr(candidate, "profile_id", "") or "").strip().lower()

        # Scalper profile entries are intentionally managed by a tighter,
        # profile-specific execution loop. Do not mirror invalidation exits
        # pre-entry for that path, or we end up blocking otherwise valid
        # fast-turnover SOL scalps on transient flow/support noise.
        if profile_id == "scalper" or strategy_id == "scalper":
            return None

        # Use the most adverse orderflow reading available.
        flow_candidates = []
        mc_flow = market_context.get("orderflow_imbalance")
        try:
            if mc_flow is not None:
                flow_candidates.append(float(mc_flow))
        except (TypeError, ValueError):
            pass
        flow_candidates.append(float(snapshot.imb_5s))
        if side == "long":
            adverse_flow = min(flow_candidates)
        else:
            adverse_flow = max(flow_candidates)

        flow_bad, flow_reason = evaluate_exit_orderflow(side, adverse_flow)

        # Build level context using most precise distances available.
        level_ctx: Dict[str, object] = dict(market_context or {})
        if side == "long":
            if (
                level_ctx.get("distance_to_vah_pct") is None
                and snapshot.distance_to_vah_bps is not None
                and float(snapshot.distance_to_vah_bps) > 0.0
            ):
                level_ctx["distance_to_vah_pct"] = float(snapshot.distance_to_vah_bps) / 10000.0
            if level_ctx.get("distance_to_vah") is None and snapshot.vah_price is not None:
                level_ctx["distance_to_vah"] = abs(float(snapshot.mid_price) - float(snapshot.vah_price))
        else:
            if (
                level_ctx.get("distance_to_val_pct") is None
                and snapshot.distance_to_val_bps is not None
                and float(snapshot.distance_to_val_bps) > 0.0
            ):
                level_ctx["distance_to_val_pct"] = float(snapshot.distance_to_val_bps) / 10000.0
            if level_ctx.get("distance_to_val") is None and snapshot.val_price is not None:
                level_ctx["distance_to_val"] = abs(float(snapshot.mid_price) - float(snapshot.val_price))

        level_bad, level_reason = evaluate_exit_price_level(side, level_ctx, float(snapshot.mid_price))

        reasons = []
        require_level_confirmation = strategy_id in {
            "mean_reversion_fade",
            "vwap_reversion",
            "spot_mean_reversion",
            "spot_dip_accumulator",
        }
        stronger_flow_required = strategy_id in {
            "mean_reversion_fade",
            "vwap_reversion",
        }
        stronger_flow_threshold = 0.90
        symbol_thresholds = self.config.pre_entry_invalidation_flow_threshold_by_symbol or {}
        symbol_key = str(
            getattr(snapshot, "symbol", "") or market_context.get("symbol") or ""
        ).strip().upper()
        if symbol_key and symbol_key in symbol_thresholds:
            stronger_flow_threshold = float(symbol_thresholds[symbol_key])
        if stronger_flow_required and abs(adverse_flow) < stronger_flow_threshold:
            flow_bad = False
            flow_reason = None
        if flow_bad and not require_level_confirmation:
            reasons.append(flow_reason)
        elif flow_bad and level_bad and require_level_confirmation:
            reasons.append(flow_reason)
        if level_bad and not require_level_confirmation:
            reasons.append(level_reason)
        elif level_bad and flow_bad and require_level_confirmation:
            reasons.append(level_reason)
        if reasons:
            return "pre_entry_invalidation_risk:" + "+".join(reasons)
        return None
    
    def _reject(
        self,
        ctx: StageContext,
        candidate: Optional[TradeCandidate],
        reasons: list,
        metrics: dict,
    ) -> StageResult:
        """Record rejection and return REJECT result."""
        ctx.rejection_reason = reasons[0] if reasons else "candidate_vetoed"
        ctx.rejection_stage = self.name
        ctx.rejection_detail = {
            "reasons": reasons,
            "metrics": metrics,
            "candidate": candidate.to_dict() if candidate else None,
        }
        
        # Store gate decision for telemetry
        ctx.data["gate_decisions"] = ctx.data.get("gate_decisions") or []
        ctx.data["gate_decisions"].append(GateDecision(
            allowed=False,
            gate_name=self.name,
            reasons=reasons,
            metrics=metrics,
        ))
        
        if self._trace_enabled:
            log_warning(
                "candidate_veto_reject",
                symbol=ctx.symbol,
                reasons=reasons,
                side=candidate.side if candidate else None,
                strategy_id=candidate.strategy_id if candidate else None,
            )
        
        return StageResult.REJECT
