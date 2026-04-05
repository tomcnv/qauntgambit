"""
GlobalGateStage - Side-agnostic pre-signal gating.

Runs early (before signal generation) to reject obviously bad conditions.
All checks here are side-agnostic - they don't depend on trade direction.

Implements graceful degradation:
    NORMAL -> REDUCE_SIZE -> NO_ENTRIES -> FLATTEN

Implements conditional vol shock handling (Requirement 6):
    - Never hard rejects on vol_shock
    - Applies strategy-specific size and EV multipliers
    - Forces taker-only when spread is wide during vol shock
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple

from quantgambit.signals.pipeline import Stage, StageContext, StageResult
from quantgambit.deeptrader_core.types import MarketSnapshot, GateDecision
from quantgambit.observability.logger import log_info, log_warning
from quantgambit.risk.degradation import (
    DegradationManager,
    DegradationConfig,
    TradingMode,
    get_degradation_manager,
)


@dataclass
class VolShockConfig:
    """
    Configuration for conditional vol shock handling (Requirement 6).
    
    Instead of hard rejecting on vol_shock, applies conditional adjustments
    based on strategy type and market conditions.
    """
    # Size multipliers by strategy type (Requirement 6.2)
    # Lower multiplier = more size reduction during vol shock
    size_multiplier_by_strategy: Dict[str, float] = field(default_factory=lambda: {
        "mean_reversion": 0.50,   # 50% size reduction - most conservative
        "breakout": 0.75,         # 25% size reduction - vol can help breakouts
        "trend_pullback": 0.70,   # 30% size reduction
        "default": 0.50,          # Default: 50% size reduction
    })
    
    # EV multipliers by strategy type (Requirement 6.2)
    # Higher multiplier = higher EV_Min required during vol shock
    ev_multiplier_by_strategy: Dict[str, float] = field(default_factory=lambda: {
        "mean_reversion": 1.50,   # 50% higher EV_Min required
        "breakout": 1.25,         # 25% higher EV_Min - less penalty for breakouts
        "trend_pullback": 1.30,   # 30% higher EV_Min
        "default": 1.50,          # Default: 50% higher EV_Min
    })
    
    # Spread threshold for forcing taker-only execution (Requirement 6.3)
    # When spread_percentile > this threshold during vol shock, force taker
    spread_threshold_for_taker: float = 0.80
    
    # Reduced TTL for maker orders during vol shock (Requirement 6.4)
    # When spread is acceptable, allow maker-first but with reduced TTL
    reduced_maker_ttl_ms: int = 2000


@dataclass
class GlobalGateConfig:
    """Configuration for GlobalGateStage."""
    # Snapshot age thresholds (tiered)
    # Adjusted for realistic Redis pipeline latency
    snapshot_age_ok_ms: float = 2000.0      # <2s: full trading
    snapshot_age_reduce_ms: float = 5000.0  # 2-5s: reduce size
    snapshot_age_block_ms: float = 10000.0  # >10s: block entries
    
    # Spread limits
    max_spread_bps: float = 10.0            # Absolute max spread
    max_spread_vs_typical_ratio: float = 3.0  # Spread vs typical threshold
    
    # Depth limits
    min_depth_per_side_usd: float = 10000.0  # Minimum $10k depth per side (fallback)
    
    # Multiplier-based depth threshold (Requirement 7.6)
    # When set, this multiplier is used with typical_depth_usd from symbol characteristics
    # to calculate min_depth_per_side_usd dynamically. Falls back to min_depth_per_side_usd
    # if symbol characteristics are unavailable.
    depth_typical_multiplier: Optional[float] = 0.5  # Default: require 50% of typical depth
    
    # Vol shock - NEVER hard reject (Requirement 6.1)
    # Set to False by default to enable conditional handling
    block_on_vol_shock: bool = False
    
    # Vol shock conditional handling configuration (Requirement 6)
    vol_shock_config: VolShockConfig = field(default_factory=VolShockConfig)
    
    # Size reduction factors
    stale_data_size_factor: float = 0.5     # Reduce size 50% when data is stale
    wide_spread_size_factor: float = 0.5    # Reduce size 50% when spread is wide


class GlobalGateStage(Stage):
    """
    Side-agnostic global gate that runs before signal generation.
    
    Blocks or reduces trading when:
    1. Snapshot is too old (tiered response)
    2. Spread is too wide (absolute or relative to typical)
    3. Depth is too thin
    4. Vol shock detected
    5. Market hours check (for symbols with sessions)
    
    Implements graceful degradation:
    - NORMAL: Full trading
    - REDUCE_SIZE: Trade with reduced position sizes
    - NO_ENTRIES: No new entries, exits allowed
    - FLATTEN: Actively close positions
    
    This stage sets ctx.data["size_factor"] and ctx.data["trading_mode"]
    to communicate sizing adjustments and mode to downstream stages.
    """
    name = "global_gate"
    
    def __init__(
        self, 
        config: Optional[GlobalGateConfig] = None,
        degradation_manager: Optional[DegradationManager] = None,
    ):
        self.config = config or GlobalGateConfig()
        self._degradation_manager = degradation_manager or get_degradation_manager()
        self._trace_enabled = os.getenv("GLOBAL_GATE_TRACE", "").lower() in {"1", "true"}
    
    async def run(self, ctx: StageContext) -> StageResult:
        reasons = []
        metrics = {}
        size_factor = 1.0
        
        snapshot: Optional[MarketSnapshot] = ctx.data.get("snapshot")
        market_context = ctx.data.get("market_context") or {}
        
        if snapshot is None:
            reasons.append("no_snapshot")
            return self._reject(ctx, reasons, metrics)
        
        # ===== GRACEFUL DEGRADATION EVALUATION =====
        # Evaluate trading mode based on data quality and market conditions
        feed_staleness = market_context.get("feed_staleness") or {}
        data_quality = market_context.get("data_quality_score")
        ws_connected = getattr(snapshot, "ws_connected", True)
        
        degradation = self._degradation_manager.evaluate(
            symbol=ctx.symbol,
            feed_staleness=feed_staleness,
            data_quality=data_quality,
            spread_bps=snapshot.spread_bps,
            bid_depth_usd=snapshot.bid_depth_usd,
            ask_depth_usd=snapshot.ask_depth_usd,
            ws_connected=ws_connected,
        )
        
        # Store trading mode for downstream stages
        ctx.data["trading_mode"] = degradation.mode
        ctx.data["degradation_decision"] = degradation
        metrics["trading_mode"] = degradation.mode.name
        metrics["trading_mode_reasons"] = degradation.reasons
        
        # Apply degradation mode
        if degradation.mode == TradingMode.FLATTEN:
            # Flatten mode - reject entries, signal flatten needed
            ctx.data["should_flatten"] = True
            reasons.append(f"flatten_mode:{','.join(degradation.reasons[:3])}")
            return self._reject(ctx, reasons, metrics)
        
        if degradation.mode == TradingMode.NO_ENTRIES:
            # No entries mode - only allow exits
            is_exit = ctx.data.get("is_exit_signal", False)
            if not is_exit:
                reasons.append(f"no_entries_mode:{','.join(degradation.reasons[:3])}")
                return self._reject(ctx, reasons, metrics)
        
        if degradation.mode == TradingMode.REDUCE_SIZE:
            # Reduce size mode - apply multiplier
            size_factor *= degradation.size_multiplier
            if self._trace_enabled:
                log_info(
                    "global_gate_degradation_reduce",
                    symbol=ctx.symbol,
                    mode=degradation.mode.name,
                    size_factor=size_factor,
                )
        
        # ===== TRADITIONAL CHECKS (may further reduce size) =====
        
        # Check 1: Snapshot age (tiered response)
        age_ms = snapshot.snapshot_age_ms
        metrics["snapshot_age_ms"] = age_ms
        
        if age_ms > self.config.snapshot_age_block_ms:
            reasons.append(f"snapshot_too_old:{age_ms:.0f}ms>{self.config.snapshot_age_block_ms:.0f}ms")
        elif age_ms > self.config.snapshot_age_reduce_ms:
            # Don't reject, but reduce size
            size_factor *= self.config.stale_data_size_factor
            if self._trace_enabled:
                log_info(
                    "global_gate_stale_reduce",
                    symbol=ctx.symbol,
                    age_ms=age_ms,
                    size_factor=size_factor,
                )
        
        # Check 2: Spread limits
        spread_bps = snapshot.spread_bps
        typical_spread = snapshot.typical_spread_bps
        metrics["spread_bps"] = spread_bps
        metrics["typical_spread_bps"] = typical_spread
        
        # Absolute spread check
        if spread_bps > self.config.max_spread_bps:
            reasons.append(f"spread_too_wide:{spread_bps:.1f}bps>{self.config.max_spread_bps:.1f}bps")
        
        # Relative spread check (vs typical)
        if typical_spread > 0 and spread_bps > typical_spread * self.config.max_spread_vs_typical_ratio:
            # Don't hard reject, but reduce size
            size_factor *= self.config.wide_spread_size_factor
            if self._trace_enabled:
                log_info(
                    "global_gate_wide_spread_reduce",
                    symbol=ctx.symbol,
                    spread_bps=spread_bps,
                    typical_spread_bps=typical_spread,
                    size_factor=size_factor,
                )
        
        # Check 3: Depth limits (skip in backtest mode — historical depth data is incomplete)
        is_backtest = (ctx.data.get("mode") == "backtest"
                       or (isinstance(ctx.data.get("market_context"), dict)
                           and ctx.data["market_context"].get("mode") == "backtest"))
        min_depth = min(snapshot.bid_depth_usd, snapshot.ask_depth_usd)
        metrics["min_depth_usd"] = min_depth
        
        if not is_backtest:
            # Get min_depth_per_side_usd from resolved_params if available
            # Fall back to multiplier calculation if symbol_characteristics available
            # Finally fall back to config value
            resolved_params = ctx.data.get("resolved_params")
            symbol_characteristics = ctx.data.get("symbol_characteristics")
            
            if resolved_params is not None:
                min_depth_threshold = resolved_params.min_depth_per_side_usd
                metrics["min_depth_threshold_source"] = "resolved_params"
            elif (
                symbol_characteristics is not None
                and self.config.depth_typical_multiplier is not None
                and symbol_characteristics.typical_depth_usd > 0
            ):
                min_depth_threshold = (
                    self.config.depth_typical_multiplier * symbol_characteristics.typical_depth_usd
                )
                metrics["min_depth_threshold_source"] = "multiplier"
                metrics["depth_typical_multiplier"] = self.config.depth_typical_multiplier
                metrics["typical_depth_usd"] = symbol_characteristics.typical_depth_usd
            else:
                min_depth_threshold = self.config.min_depth_per_side_usd
                metrics["min_depth_threshold_source"] = "config"
            
            metrics["min_depth_threshold_usd"] = min_depth_threshold
            
            if min_depth < min_depth_threshold:
                reasons.append(f"depth_too_thin:{min_depth:.0f}USD<{min_depth_threshold:.0f}USD")
        
        # Check 4: Vol shock - Conditional handling (Requirement 6)
        metrics["vol_shock"] = snapshot.vol_shock
        
        if snapshot.vol_shock:
            # NEVER hard reject on vol_shock (Requirement 6.1)
            # Instead, apply conditional adjustments based on strategy type
            if self.config.block_on_vol_shock:
                # Legacy behavior - only if explicitly enabled
                reasons.append("vol_shock_detected")
            else:
                # Conditional vol shock handling (Requirement 6.2-6.4)
                # Get strategy type from context (may be set by ProfileRouter or strategy)
                strategy_type = self._get_strategy_type(ctx)
                spread_percentile = market_context.get("spread_percentile", 0.5)
                
                vol_shock_size_mult, vol_shock_ev_mult, execution_mode = self._apply_vol_shock_adjustments(
                    ctx=ctx,
                    strategy_type=strategy_type,
                    spread_percentile=spread_percentile,
                )
                
                # Apply vol shock size multiplier
                size_factor *= vol_shock_size_mult
                
                metrics["vol_shock_strategy_type"] = strategy_type
                metrics["vol_shock_size_multiplier"] = vol_shock_size_mult
                metrics["vol_shock_ev_multiplier"] = vol_shock_ev_mult
                metrics["vol_shock_execution_mode"] = execution_mode
        
        # Check 5: Data quality (only if not already handled by degradation)
        if not ws_connected:
            # Already handled by degradation manager, just note it
            metrics["ws_connected"] = False
        
        # Check 6: Data quality score (only if not already handled)
        if data_quality is not None and data_quality < 0.5 and degradation.mode == TradingMode.NORMAL:
            reasons.append(f"low_data_quality:{data_quality:.2f}")
        
        # If we have hard rejection reasons, reject
        if reasons:
            return self._reject(ctx, reasons, metrics)
        
        # Store size factor for downstream stages
        ctx.data["size_factor"] = size_factor
        
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
                "global_gate_pass",
                symbol=ctx.symbol,
                trading_mode=degradation.mode.name,
                size_factor=size_factor,
                metrics=metrics,
            )
        
        return StageResult.CONTINUE
    
    def _get_strategy_type(self, ctx: StageContext) -> str:
        """
        Extract strategy type from context for vol shock adjustments.
        
        Looks for strategy type in:
        1. ctx.data["strategy_type"] - explicitly set
        2. ctx.data["profile_params"]["strategy_type"] - from ProfileRouter
        3. ctx.data["candidate_signal"].strategy_id - extract from strategy ID
        4. Falls back to "default"
        """
        # Check explicit strategy_type
        if "strategy_type" in ctx.data:
            return ctx.data["strategy_type"]
        
        # Check profile params
        profile_params = ctx.data.get("profile_params") or {}
        if "strategy_type" in profile_params:
            return profile_params["strategy_type"]
        
        # Try to extract from candidate signal strategy_id
        candidate = ctx.data.get("candidate_signal")
        if candidate is not None:
            strategy_id = getattr(candidate, "strategy_id", "")
            # Extract strategy type from ID (e.g., "mean_reversion_fade" -> "mean_reversion")
            for known_type in ["mean_reversion", "breakout", "trend_pullback"]:
                if known_type in strategy_id.lower():
                    return known_type
        
        return "default"
    
    def _apply_vol_shock_adjustments(
        self,
        ctx: StageContext,
        strategy_type: str,
        spread_percentile: float,
    ) -> Tuple[float, float, str]:
        """
        Apply conditional vol shock adjustments based on strategy type (Requirement 6).
        
        Instead of hard rejecting on vol_shock, applies:
        - Strategy-specific size multiplier (Requirement 6.2)
        - Strategy-specific EV multiplier (Requirement 6.2)
        - Execution mode based on spread (Requirement 6.3, 6.4)
        
        Args:
            ctx: Stage context to update with vol shock data
            strategy_type: Type of strategy (mean_reversion, breakout, trend_pullback, default)
            spread_percentile: Current spread percentile (0-1)
            
        Returns:
            Tuple of (size_multiplier, ev_multiplier, execution_mode)
        """
        config = self.config.vol_shock_config
        
        # Get strategy-specific multipliers (Requirement 6.2)
        size_mult = config.size_multiplier_by_strategy.get(
            strategy_type,
            config.size_multiplier_by_strategy.get("default", 0.50)
        )
        ev_mult = config.ev_multiplier_by_strategy.get(
            strategy_type,
            config.ev_multiplier_by_strategy.get("default", 1.50)
        )
        
        # Determine execution mode based on spread (Requirement 6.3, 6.4)
        if spread_percentile > config.spread_threshold_for_taker:
            # Wide spread during vol shock - force taker only (Requirement 6.3)
            execution_mode = "taker_only"
        else:
            # Acceptable spread - allow maker-first with reduced TTL (Requirement 6.4)
            execution_mode = "maker_first_reduced_ttl"
        
        # Set context data for downstream stages (Requirement 6.5)
        ctx.data["vol_shock_active"] = True
        ctx.data["vol_shock_size_multiplier"] = size_mult
        ctx.data["vol_shock_ev_multiplier"] = ev_mult
        ctx.data["vol_shock_execution_mode"] = execution_mode
        
        if execution_mode == "taker_only":
            ctx.data["force_taker"] = True
        else:
            ctx.data["maker_ttl_ms"] = config.reduced_maker_ttl_ms
        
        # Log adjustments (Requirement 6.8)
        log_info(
            "vol_shock_conditional_adjustment",
            symbol=ctx.symbol,
            strategy_type=strategy_type,
            spread_percentile=round(spread_percentile, 2),
            size_multiplier=size_mult,
            ev_multiplier=ev_mult,
            execution_mode=execution_mode,
        )
        
        return size_mult, ev_mult, execution_mode
    
    def _reject(self, ctx: StageContext, reasons: list, metrics: dict) -> StageResult:
        """Record rejection and return REJECT result."""
        ctx.rejection_reason = reasons[0] if reasons else "global_gate_blocked"
        ctx.rejection_stage = self.name
        ctx.rejection_detail = {
            "reasons": reasons,
            "metrics": metrics,
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
                "global_gate_reject",
                symbol=ctx.symbol,
                reasons=reasons,
                metrics=metrics,
            )
        
        return StageResult.REJECT
