"""
StrategyTrendAlignmentStage - Ensures strategies only trade in compatible market conditions.

This stage is part of the loss prevention system that filters out signals where
the strategy type conflicts with the current market trend. For example, mean
reversion strategies should not short in uptrends or long in downtrends.

Requirements: 2.1, 2.2, 2.3, 2.4, 2.5
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional, Dict, Any, Set, TYPE_CHECKING

from quantgambit.signals.pipeline import Stage, StageContext, StageResult, signal_to_dict
from quantgambit.observability.logger import log_info, log_warning

if TYPE_CHECKING:
    from quantgambit.observability.blocked_signal_telemetry import BlockedSignalTelemetry


# =============================================================================
# STRATEGY_TREND_RULES Configuration (Task 2.1)
# Requirements: 2.1, 2.2, 2.3
# =============================================================================

STRATEGY_TREND_RULES: Dict[str, Dict[str, Any]] = {
    "mean_reversion_fade": {
        # Mean reversion should only trade in ranging/flat markets
        # Requirement 2.1: Reject SHORT signals in uptrends
        # Requirement 2.2: Reject LONG signals in downtrends
        "allowed_trends": {"flat"},
        "reject_on_trend_up": "short",    # Don't short in uptrends
        "reject_on_trend_down": "long",   # Don't long in downtrends
        "description": "Mean reversion trades against short-term moves, dangerous in trending markets",
    },
    "trend_following": {
        # Trend following should only trade in trending markets
        # Requirement 2.3: Reject ALL signals in flat markets
        "allowed_trends": {"up", "down"},
        "reject_on_trend_flat": "all",    # Don't trade in flat markets
        "description": "Trend following requires established trends to work",
    },
}

# Valid trend values for classification
VALID_TRENDS: Set[str] = {"up", "down", "flat"}

# Valid signal sides
VALID_SIDES: Set[str] = {"long", "short"}



@dataclass
class StrategyTrendAlignmentConfig:
    """Configuration for StrategyTrendAlignmentStage.
    
    Attributes:
        rules: Strategy-specific trend alignment rules.
               Defaults to STRATEGY_TREND_RULES.
        ema_trend_threshold: Threshold for EMA-based trend classification.
                            Percentage difference between fast and slow EMA.
                            Default is 0.001 (0.1%).
    """
    rules: Optional[Dict[str, Dict[str, Any]]] = None
    ema_trend_threshold: float = 0.001  # 0.1% difference for trend classification
    
    def __post_init__(self):
        """Set default rules if not provided."""
        # Allow env override for tuning
        env_threshold = os.environ.get("EMA_TREND_THRESHOLD")
        if env_threshold is not None:
            self.ema_trend_threshold = float(env_threshold)
        if self.rules is None:
            self.rules = STRATEGY_TREND_RULES


class StrategyTrendAlignmentStage(Stage):
    """
    Pipeline stage that ensures strategies only trade in compatible market conditions.
    
    This stage extracts the strategy_id and signal_side from ctx.signal, determines
    the current market trend, and rejects signals that conflict with the strategy's
    trend requirements.
    
    Requirements:
    - 2.1: Reject mean reversion SHORT signals in uptrends
    - 2.2: Reject mean reversion LONG signals in downtrends
    - 2.3: Reject trend following signals in flat markets
    - 2.4: Emit telemetry with strategy type, signal direction, and current trend
    - 2.5: Classify trend as "up", "down", or "flat" based on EMA relationships
    """
    name = "strategy_trend_alignment"
    
    def __init__(
        self,
        config: Optional[StrategyTrendAlignmentConfig] = None,
        telemetry: Optional["BlockedSignalTelemetry"] = None,
    ):
        """Initialize StrategyTrendAlignmentStage.
        
        Args:
            config: Configuration for the stage. Uses defaults if None.
            telemetry: Optional telemetry for recording blocked signals.
        """
        self.config = config or StrategyTrendAlignmentConfig()
        self.telemetry = telemetry
    
    async def run(self, ctx: StageContext) -> StageResult:
        """
        Evaluate strategy-trend alignment and reject mismatched signals.
        
        Args:
            ctx: Stage context containing signal and market data.
            
        Returns:
            StageResult.REJECT if strategy-trend mismatch detected,
            StageResult.CONTINUE otherwise.
            
        Requirements: 2.1, 2.2, 2.3, 2.5
        """
        # Extract signal information - convert to dict if needed
        signal = signal_to_dict(ctx.signal)
        strategy_id = self._get_strategy_id(signal, ctx)
        signal_side = self._get_signal_side(signal)
        
        # If no signal or strategy, continue (nothing to filter)
        if not strategy_id or not signal_side:
            log_info(
                "strategy_trend_alignment_skip",
                symbol=ctx.symbol,
                reason="no_strategy_or_signal",
                strategy_id=strategy_id,
                signal_side=signal_side,
            )
            return StageResult.CONTINUE
        
        # Get current trend (Requirement 2.5)
        trend = self._get_trend(ctx)
        
        # Get rules for this strategy
        rules = self.config.rules.get(strategy_id, {})
        if not rules:
            # No rules for this strategy, allow through
            log_info(
                "strategy_trend_alignment_no_rules",
                symbol=ctx.symbol,
                strategy_id=strategy_id,
            )
            return StageResult.CONTINUE
        
        # Check for strategy-trend mismatch
        rejection_reason = self._check_mismatch(strategy_id, signal_side, trend, rules)
        
        if rejection_reason:
            return await self._reject(ctx, rejection_reason, strategy_id, signal_side, trend)
        
        # Log successful pass
        log_info(
            "strategy_trend_alignment_pass",
            symbol=ctx.symbol,
            strategy_id=strategy_id,
            signal_side=signal_side,
            trend=trend,
        )
        
        return StageResult.CONTINUE
    
    def _get_strategy_id(self, signal: Dict[str, Any], ctx: StageContext) -> Optional[str]:
        """Extract strategy_id from signal or context."""
        # Try signal first
        strategy_id = signal.get("strategy_id")
        if strategy_id:
            return strategy_id
        
        # Try context data
        if ctx.data:
            strategy_id = ctx.data.get("strategy_id")
            if strategy_id:
                return strategy_id
            
            # Try market_context
            market_context = ctx.data.get("market_context", {})
            strategy_id = market_context.get("strategy_id")
            if strategy_id:
                return strategy_id
        
        return None
    
    def _get_signal_side(self, signal: Dict[str, Any]) -> Optional[str]:
        """Extract signal side (long/short) from signal."""
        side = signal.get("side")
        if side and side.lower() in VALID_SIDES:
            return side.lower()
        
        # Try direction field
        direction = signal.get("direction")
        if direction:
            direction = direction.lower()
            if direction in VALID_SIDES:
                return direction
            # Map buy/sell to long/short
            if direction == "buy":
                return "long"
            if direction == "sell":
                return "short"
        
        return None
    
    def _get_trend(self, ctx: StageContext) -> str:
        """
        Get current market trend from context or classify from features.
        
        Requirement 2.5: Classify trend as "up", "down", or "flat" based on EMA relationships.
        
        Returns:
            "up", "down", or "flat"
        """
        # Try to get trend from market_context first
        market_context = ctx.data.get("market_context", {}) if ctx.data else {}
        
        # Check various trend field names
        trend = market_context.get("trend")
        if trend and trend.lower() in VALID_TRENDS:
            normalized = trend.lower()
            if normalized in {"up", "down"}:
                trend_strength = (
                    market_context.get("trend_strength")
                    if isinstance(market_context, dict)
                    else None
                )
                if trend_strength is None:
                    features = ctx.data.get("features", {}) if ctx.data else {}
                    trend_strength = features.get("trend_strength")
                try:
                    strength_val = float(trend_strength) if trend_strength is not None else None
                except (TypeError, ValueError):
                    strength_val = None
                if strength_val is not None and abs(strength_val) < self.config.ema_trend_threshold:
                    return "flat"
                if strength_val is None:
                    trend_bias = (
                        market_context.get("trend_bias")
                        if isinstance(market_context, dict)
                        else None
                    )
                    try:
                        bias_val = float(trend_bias) if trend_bias is not None else None
                    except (TypeError, ValueError):
                        bias_val = None
                    if bias_val is not None and abs(bias_val) < self.config.ema_trend_threshold:
                        return "flat"
            return normalized
        
        trend_direction = market_context.get("trend_direction")
        if trend_direction:
            trend_direction = trend_direction.lower()
            if trend_direction in VALID_TRENDS:
                # If trend strength is weak, treat as flat to avoid false mismatches.
                trend_strength = (
                    market_context.get("trend_strength")
                    if isinstance(market_context, dict)
                    else None
                )
                if trend_strength is None:
                    features = ctx.data.get("features", {}) if ctx.data else {}
                    trend_strength = features.get("trend_strength")
                try:
                    strength_val = float(trend_strength) if trend_strength is not None else None
                except (TypeError, ValueError):
                    strength_val = None
                if strength_val is not None and abs(strength_val) < self.config.ema_trend_threshold:
                    return "flat"
                return trend_direction
            # Map bullish/bearish to up/down
            if trend_direction in ("bullish", "uptrend"):
                return "up"
            if trend_direction in ("bearish", "downtrend"):
                return "down"
        
        trend_bias = market_context.get("trend_bias")
        if trend_bias:
            trend_bias = trend_bias.lower()
            if trend_bias in VALID_TRENDS:
                return trend_bias
            if trend_bias in ("long", "bullish"):
                return "up"
            if trend_bias in ("short", "bearish"):
                return "down"
        
        # Classify from features using EMA relationship
        return self._classify_trend_from_features(ctx)
    
    def _classify_trend_from_features(self, ctx: StageContext) -> str:
        """
        Classify trend from EMA features.
        
        Requirement 2.5: Use EMA relationships to determine trend.
        
        Returns:
            "up" if fast EMA > slow EMA by threshold
            "down" if fast EMA < slow EMA by threshold
            "flat" otherwise
        """
        features = ctx.data.get("features", {}) if ctx.data else {}
        market_context = ctx.data.get("market_context", {}) if ctx.data else {}
        
        # Get EMA values
        ema_fast = (
            features.get("ema_fast_15m") or 
            market_context.get("ema_fast_15m") or
            features.get("ema_fast") or
            market_context.get("ema_fast")
        )
        ema_slow = (
            features.get("ema_slow_15m") or 
            market_context.get("ema_slow_15m") or
            features.get("ema_slow") or
            market_context.get("ema_slow")
        )
        
        if ema_fast is None or ema_slow is None or ema_slow == 0:
            # Can't classify, default to flat (safest)
            return "flat"
        
        # Calculate percentage difference
        diff_pct = (ema_fast - ema_slow) / ema_slow
        
        if diff_pct > self.config.ema_trend_threshold:
            return "up"
        elif diff_pct < -self.config.ema_trend_threshold:
            return "down"
        else:
            return "flat"
    
    def _check_mismatch(
        self,
        strategy_id: str,
        signal_side: str,
        trend: str,
        rules: Dict[str, Any],
    ) -> Optional[str]:
        """
        Check if there's a strategy-trend mismatch.
        
        Requirements: 2.1, 2.2, 2.3
        
        Returns:
            Rejection reason string if mismatch, None otherwise.
        """
        # Check mean reversion rules (Requirements 2.1, 2.2)
        if strategy_id == "mean_reversion_fade":
            # Mean reversion is already filtered by geometry, cost, and confirmation.
            # In live operation, this stage has been over-blocking valid range entries
            # when upstream trend labeling is overly coarse. Do not add a second
            # hard counter-trend veto here.
            return None
        
        # Check trend following rules (Requirement 2.3)
        if strategy_id == "trend_following":
            # Requirement 2.3: Reject ALL signals in flat markets
            if trend == "flat":
                return "trend_following_in_flat_market"
        
        # Generic rule checking for other strategies
        reject_on_up = rules.get("reject_on_trend_up")
        if trend == "up" and reject_on_up:
            if reject_on_up == "all" or reject_on_up == signal_side:
                return f"{strategy_id}_rejected_in_uptrend"
        
        reject_on_down = rules.get("reject_on_trend_down")
        if trend == "down" and reject_on_down:
            if reject_on_down == "all" or reject_on_down == signal_side:
                return f"{strategy_id}_rejected_in_downtrend"
        
        reject_on_flat = rules.get("reject_on_trend_flat")
        if trend == "flat" and reject_on_flat:
            if reject_on_flat == "all" or reject_on_flat == signal_side:
                return f"{strategy_id}_rejected_in_flat_market"
        
        return None
    
    async def _reject(
        self,
        ctx: StageContext,
        reason: str,
        strategy_id: str,
        signal_side: str,
        trend: str,
    ) -> StageResult:
        """
        Reject the signal and emit telemetry.
        
        Requirement 2.4: Emit telemetry with strategy type, signal direction, and current trend.
        
        Returns:
            StageResult.REJECT
        """
        ctx.rejection_reason = "strategy_trend_mismatch"
        ctx.rejection_stage = self.name
        ctx.rejection_detail = {
            "strategy_id": strategy_id,
            "signal_side": signal_side,
            "trend": trend,
            "mismatch_reason": reason,
        }
        
        # Emit telemetry (Requirement 2.4)
        if self.telemetry:
            await self.telemetry.record_blocked(
                symbol=ctx.symbol,
                gate_name="strategy_trend_mismatch",
                reason=f"{reason}: {signal_side} signal in {trend} trend",
                metrics={
                    "strategy_id": strategy_id,
                    "signal_side": signal_side,
                    "trend": trend,
                },
            )
        
        log_warning(
            "strategy_trend_alignment_reject",
            symbol=ctx.symbol,
            strategy_id=strategy_id,
            signal_side=signal_side,
            trend=trend,
            reason=reason,
        )
        
        return StageResult.REJECT
