"""
Trend Continuation Pullback Strategy

Enters trending markets on pullbacks to the value area (POC support/resistance).

Entry Conditions:
- Strong trend (EMA fast > slow by >0.5% for uptrend, or vice versa)
- Price pulls back inside value area from above/below
- Rotation factor still aligned with trend (>5 for uptrend, <-5 for downtrend)
- Entry at POC support/resistance
- Sufficient edge after fees (expected profit > min_edge_bps)

Risk Profile:
- Medium stops (0.5% - 0.8%)
- Larger position size (1.0% - 2.0% risk)
- Swing target (1.0% - 2.0%)

Exit Logic:
- Trail stop at POC
- Exit if trend breaks (EMA crossover)
- Take partial profits at 0.5%, let rest run

Best Market Conditions:
- Trend: up or down (strong)
- Volatility: normal to high
- Value Location: Price pulls back inside from above/below
- EMA alignment confirms trend

Fee-Aware Entry Filtering (US-4):
- min_edge_bps: Minimum edge after fees/slippage (default 3 bps, configurable via STRATEGY_MIN_EDGE_BPS)
- fee_bps: Estimated round-trip fees in basis points (default 6 bps, configurable via STRATEGY_FEE_BPS)
- slippage_bps: Estimated slippage in basis points (default 2 bps, configurable via STRATEGY_SLIPPAGE_BPS)
"""

from typing import Optional, Dict, Any
import logging
import os
from quantgambit.deeptrader_core.types import Features, AccountState, Profile, StrategySignal
from .base import Strategy

logger = logging.getLogger(__name__)

# Fee-aware entry filtering defaults (US-4)
# RELAXED: Reduced from 8.0 to 3.0 bps for scalping (was blocking most trades)
# Can be overridden via STRATEGY_MIN_EDGE_BPS environment variable
DEFAULT_MIN_EDGE_BPS = float(os.getenv("STRATEGY_MIN_EDGE_BPS", "3.0"))
DEFAULT_FEE_BPS = float(os.getenv("STRATEGY_FEE_BPS", "6.0"))  # Round-trip fees (~0.06% taker)
DEFAULT_SLIPPAGE_BPS = float(os.getenv("STRATEGY_SLIPPAGE_BPS", "2.0"))  # Expected slippage


class TrendPullback(Strategy):
    """
    Trend continuation strategy for pullback entries.
    
    Enters strong trending markets when price pulls back to value area,
    providing better entry points in the direction of the trend.
    """
    
    strategy_id = "trend_pullback"
    
    def generate_signal(
        self,
        features: Features,
        account: AccountState,
        profile: Profile,
        params: Dict[str, Any],
    ) -> Optional[StrategySignal]:
        """
        Generate trend pullback signal when price retraces to value area in strong trend.
        
        Args:
            features: Market features including price, AMT metrics, indicators
            account: Account state for position sizing
            profile: Current market profile
            params: Strategy parameters from profile config
            
        Returns:
            StrategySignal if conditions met, None otherwise
        """
        # Extract parameters with defaults
        allow_longs = params.get("allow_longs", True)
        allow_shorts = params.get("allow_shorts", True)
        min_ema_spread_pct = params.get("min_ema_spread_pct", 0.0007)  # 0.07% EMA separation
        min_rotation_factor = params.get("min_rotation_factor", 1.0)  # Directional bias
        poc_entry_threshold = params.get("poc_entry_threshold", 0.008)  # Within 0.8% of POC
        risk_per_trade_pct = params.get("risk_per_trade_pct", 0.015)
        stop_loss_pct = params.get("stop_loss_pct", 0.012)  # 1.2% (was 0.6%)
        take_profit_target_pct = params.get("take_profit_target_pct", 0.015)  # 1.5% target
        max_spread = params.get("max_spread", 0.003)
        
        # Fee-aware entry filtering parameters (US-4)
        min_edge_bps = params.get("min_edge_bps", DEFAULT_MIN_EDGE_BPS)
        fee_bps = params.get("fee_bps", DEFAULT_FEE_BPS)
        slippage_bps = params.get("slippage_bps", DEFAULT_SLIPPAGE_BPS)
        total_cost_bps = fee_bps + slippage_bps
        
        # Sanity checks
        if not features.point_of_control:
            return None
        
        if not features.value_area_high or not features.value_area_low:
            return None
        
        # Fast filter: spread check
        if features.spread > max_spread:
            return None
        
        # Must be INSIDE value area (pullback condition)
        if features.position_in_value != "inside":
            return None
        
        # Calculate EMA spread to confirm trend strength
        ema_fast = features.ema_fast_15m
        ema_slow = features.ema_slow_15m
        
        if not ema_fast or not ema_slow:
            return None
        
        ema_spread_pct = abs(ema_fast - ema_slow) / ema_slow
        
        # Check for strong trend
        if ema_spread_pct < min_ema_spread_pct:
            return None  # Trend not strong enough
        
        # Fee-aware edge check (US-4): expected profit must exceed costs + minimum edge
        # Expected profit = take_profit_target_pct (our target)
        expected_profit_bps = take_profit_target_pct * 10000 - total_cost_bps
        
        if expected_profit_bps < min_edge_bps:
            logger.info(
                f"[{features.symbol}] trend_pullback: Rejecting entry - insufficient edge. "
                f"expected_profit={expected_profit_bps:.1f}bps, min_edge={min_edge_bps:.1f}bps, "
                f"target={take_profit_target_pct * 10000:.1f}bps, costs={total_cost_bps:.1f}bps"
            )
            return None  # No edge after costs!
        
        # Determine trend direction
        uptrend = ema_fast > ema_slow
        downtrend = ema_fast < ema_slow
        
        # Check if price is near POC (entry zone)
        poc = features.point_of_control
        current_price = features.price
        distance_from_poc_pct = abs(current_price - poc) / current_price
        
        if distance_from_poc_pct > poc_entry_threshold:
            return None  # Not at POC entry zone yet
        
        rotation = features.rotation_factor
        
        if uptrend:
            # UPTREND: Look for LONG entry on pullback
            if not allow_longs:
                return None
            
            # Rotation should still be positive (aligned with uptrend)
            if rotation < min_rotation_factor:
                return None
            
            # Calculate trade parameters
            entry = current_price
            
            # Stop loss below POC (if pullback continues, we're wrong)
            sl = poc * (1.0 - stop_loss_pct)
            
            # Take profit above entry (trend continuation target)
            tp = entry * (1.0 + take_profit_target_pct)
            
            # Position sizing based on stop distance
            stop_distance = entry - sl
            size = (account.equity * risk_per_trade_pct) / stop_distance
            
            return StrategySignal(
                strategy_id=self.strategy_id,
                symbol=features.symbol,
                side="long",
                size=size,
                entry_price=entry,
                stop_loss=sl,
                take_profit=tp,
                meta_reason=f"trend_pullback_long_ema_spread_{ema_spread_pct:.4f}_rot_{rotation:.1f}",
                profile_id=profile.id,
            )
        
        elif downtrend:
            # DOWNTREND: Look for SHORT entry on pullback
            if not allow_shorts:
                return None
            
            # Rotation should still be negative (aligned with downtrend)
            if rotation > -min_rotation_factor:
                return None
            
            # Calculate trade parameters
            entry = current_price
            
            # Stop loss above POC (if pullback continues, we're wrong)
            sl = poc * (1.0 + stop_loss_pct)
            
            # Take profit below entry (trend continuation target)
            tp = entry * (1.0 - take_profit_target_pct)
            
            # Position sizing based on stop distance
            stop_distance = sl - entry
            size = (account.equity * risk_per_trade_pct) / stop_distance
            
            return StrategySignal(
                strategy_id=self.strategy_id,
                symbol=features.symbol,
                side="short",
                size=size,
                entry_price=entry,
                stop_loss=sl,
                take_profit=tp,
                meta_reason=f"trend_pullback_short_ema_spread_{ema_spread_pct:.4f}_rot_{abs(rotation):.1f}",
                profile_id=profile.id,
            )
        
        return None
