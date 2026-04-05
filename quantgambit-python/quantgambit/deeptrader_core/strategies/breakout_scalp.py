"""
Breakout Scalp Strategy

Captures momentum when price breaks value area boundaries with strong confirmation.

Entry Conditions:
- Price breaks above VAH (for long) or below VAL (for short)
- Rotation factor confirms direction (>3.5 for breakout)
- High volatility (ATR expanding)
- Strong directional momentum
- Sufficient edge after fees (expected profit > min_edge_bps)

BPS Standardization (Strategy Signal Architecture Fixes Requirement 1.4.4):
- All distance thresholds expressed in basis points (bps)
- Uses canonical formula: (price - reference) / mid_price * 10000
- All threshold logging includes "bps" suffix for clarity

Risk Profile:
- Wider stops (0.8% - 1.2%) to allow for volatility
- Larger position size (0.8% - 1.5% risk)
- Faster take-profit (0.5% - 0.8%)

Best Market Conditions:
- Trend: up or down (strong directional)
- Volatility: high
- Value Location: Transitioning from inside → above/below
- Session: US or Europe (high liquidity)

Fee-Aware Entry Filtering (US-4):
- min_edge_bps: Minimum edge after fees/slippage (default 3 bps, configurable via STRATEGY_MIN_EDGE_BPS)
- fee_bps: Estimated round-trip fees in basis points (default 6 bps, configurable via STRATEGY_FEE_BPS)
- slippage_bps: Estimated slippage in basis points (default 2 bps, configurable via STRATEGY_SLIPPAGE_BPS)
"""

from typing import Optional, Dict, Any
import logging
import os
from quantgambit.deeptrader_core.types import Features, AccountState, Profile, StrategySignal
from quantgambit.core.unit_converter import pct_to_bps, bps_to_pct
from .base import Strategy

logger = logging.getLogger(__name__)

# Fee-aware entry filtering defaults (US-4)
# RELAXED: Reduced from 8.0 to 3.0 bps for scalping (was blocking most trades)
# Can be overridden via STRATEGY_MIN_EDGE_BPS environment variable
DEFAULT_MIN_EDGE_BPS = float(os.getenv("STRATEGY_MIN_EDGE_BPS", "3.0"))
DEFAULT_FEE_BPS = float(os.getenv("STRATEGY_FEE_BPS", "6.0"))  # Round-trip fees (~0.06% taker)
DEFAULT_SLIPPAGE_BPS = float(os.getenv("STRATEGY_SLIPPAGE_BPS", "2.0"))  # Expected slippage


class BreakoutScalp(Strategy):
    """
    Momentum breakout strategy for high-volatility trending markets.
    
    Captures strong directional moves when price breaks value area boundaries
    with volume and rotation confirmation.
    """
    
    strategy_id = "breakout_scalp"
    
    def generate_signal(
        self,
        features: Features,
        account: AccountState,
        profile: Profile,
        params: Dict[str, Any],
    ) -> Optional[StrategySignal]:
        """
        Generate breakout signal when price breaks value area with confirmation.
        
        Args:
            features: Market features including price, AMT metrics, indicators
            account: Account state for position sizing
            profile: Current market profile
            params: Strategy parameters from profile config
            
        Returns:
            StrategySignal if conditions met, None otherwise
        """
        # Extract parameters
        allow_longs = params.get("allow_longs", True)
        allow_shorts = params.get("allow_shorts", True)
        rotation_threshold = params.get("rotation_threshold", 3.5)  # Still momentum-confirmed, less over-strict
        risk_per_trade_pct = params.get("risk_per_trade_pct", 0.01)
        breakout_confirmation_pct = params.get("breakout_confirmation_pct", 0.0015)  # 15 bps beyond VA
        stop_loss_pct = params.get("stop_loss_pct", 0.004)  # 40 bps
        take_profit_pct = params.get("take_profit_pct", 0.005)  # 50 bps
        max_spread = params.get("max_spread", 0.003)
        min_atr_ratio = params.get("min_atr_ratio", 0.9)  # Allow modest expansion, not just extreme bursts
        
        # Fee-aware entry filtering parameters (US-4)
        min_edge_bps = params.get("min_edge_bps", DEFAULT_MIN_EDGE_BPS)
        fee_bps = params.get("fee_bps", DEFAULT_FEE_BPS)
        slippage_bps = params.get("slippage_bps", DEFAULT_SLIPPAGE_BPS)
        total_cost_bps = fee_bps + slippage_bps
        
        # Sanity checks
        if not features.value_area_high or not features.value_area_low:
            return None
        
        if not features.point_of_control:
            return None
        
        if features.spread > max_spread:
            return None
        
        # Check ATR expansion (need high volatility for breakouts)
        if features.atr_5m and features.atr_5m_baseline:
            atr_ratio = features.atr_5m / features.atr_5m_baseline
            if atr_ratio < min_atr_ratio:
                return None  # Volatility not high enough
        
        # Fee-aware edge check (US-4): expected profit must exceed costs + minimum edge
        # Expected profit = take_profit_pct (our target)
        # BPS Standardization: Convert take_profit_pct to bps for comparison (Requirement 1.4.4)
        take_profit_bps = pct_to_bps(take_profit_pct)  # take_profit_pct is decimal (e.g., 0.007 = 0.7%)
        expected_profit_bps = take_profit_bps - total_cost_bps
        
        if expected_profit_bps < min_edge_bps:
            logger.info(
                f"[{features.symbol}] breakout_scalp: Rejecting entry - insufficient edge. "
                f"expected_profit_bps={expected_profit_bps:.1f}bps, min_edge_bps={min_edge_bps:.1f}bps, "
                f"target_bps={take_profit_bps:.1f}bps, costs_bps={total_cost_bps:.1f}bps"
            )
            return None  # No edge after costs!
        
        # Get key levels
        vah = features.value_area_high
        val = features.value_area_low
        poc = features.point_of_control
        current_price = features.price
        rotation = features.rotation_factor
        
        # Calculate breakout confirmation distances
        breakout_distance_above = vah * breakout_confirmation_pct
        breakout_distance_below = val * breakout_confirmation_pct
        
        # Check for LONG breakout (above VAH)
        if allow_longs and rotation >= rotation_threshold:
            # Price must be ABOVE VAH with confirmation
            if current_price > (vah + breakout_distance_above):
                # Breakout confirmed!
                entry = current_price
                stop = vah  # Stop at the broken boundary
                stop_distance = entry - stop
                
                # Take profit based on momentum
                take_profit = entry + (stop_distance * (take_profit_pct / stop_loss_pct))
                
                # Calculate position size
                size = (account.equity * risk_per_trade_pct) / stop_distance
                
                return StrategySignal(
                    strategy_id=self.strategy_id,
                    symbol=features.symbol,
                    side="long",
                    size=size,
                    entry_price=entry,
                    stop_loss=stop,
                    take_profit=take_profit,
                    meta_reason=f"breakout_long_above_vah_rot_{abs(rotation):.1f}",
                    profile_id=profile.id,
                )
        
        # Check for SHORT breakout (below VAL)
        if allow_shorts and rotation <= -rotation_threshold:
            # Price must be BELOW VAL with confirmation
            if current_price < (val - breakout_distance_below):
                # Breakout confirmed!
                entry = current_price
                stop = val  # Stop at the broken boundary
                stop_distance = stop - entry
                
                # Take profit based on momentum
                take_profit = entry - (stop_distance * (take_profit_pct / stop_loss_pct))
                
                # Calculate position size
                size = (account.equity * risk_per_trade_pct) / stop_distance
                
                return StrategySignal(
                    strategy_id=self.strategy_id,
                    symbol=features.symbol,
                    side="short",
                    size=size,
                    entry_price=entry,
                    stop_loss=stop,
                    take_profit=take_profit,
                    meta_reason=f"breakout_short_below_val_rot_{abs(rotation):.1f}",
                    profile_id=profile.id,
                )
        
        return None
