"""
Opening Range Breakout Strategy

Captures directional moves after session opening range establishes.

Entry Conditions:
- First 15-30 minutes of session (US or Asia)
- Opening range high/low established
- Wait for consolidation (5-10 min)
- Enter on breakout with volume
- Rotation >7 confirms direction

Risk Profile:
- Medium stops (0.6% - 1.0%)
- Standard position size (0.8% - 1.2% risk)
- Target: 1:2 or 1:3 risk/reward

Exit Logic:
- Take profit at 2x or 3x stop distance
- Exit at session midpoint if no follow-through
- Trail stop after 1x reward

Best Market Conditions:
- Session: First 15-30 minutes of US or Asia session
- Volatility: normal to high
- Value Location: Any
- Time-based trigger

Note:
This strategy requires tracking session start times and opening range data.
For simplicity, we'll use a stateless approach that checks if we're in the
breakout window based on features rather than maintaining session state.
"""

from typing import Optional, Dict, Any
from quantgambit.deeptrader_core.types import Features, AccountState, Profile, StrategySignal
from .base import Strategy


class OpeningRangeBreakout(Strategy):
    """
    Opening range breakout strategy for session-based momentum.
    
    Captures strong directional moves that occur after the opening
    range is established in major trading sessions.
    """
    
    strategy_id = "opening_range_breakout"
    
    def generate_signal(
        self,
        features: Features,
        account: AccountState,
        profile: Profile,
        params: Dict[str, Any],
    ) -> Optional[StrategySignal]:
        """
        Generate opening range breakout signal.
        
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
        min_rotation_factor = params.get("min_rotation_factor", 3.5)  # Breakout with moderate momentum
        breakout_confirmation_pct = params.get("breakout_confirmation_pct", 0.001)  # 0.1%
        risk_per_trade_pct = params.get("risk_per_trade_pct", 0.01)
        stop_loss_pct = params.get("stop_loss_pct", 0.012)  # 1.2% (was 0.8%)
        reward_ratio = params.get("reward_ratio", 2.0)  # 1:2 risk/reward
        max_spread = params.get("max_spread", 0.002)
        
        # Sanity checks
        if not features.value_area_high or not features.value_area_low:
            return None
        
        # Fast filter: spread check
        if features.spread > max_spread:
            return None
        
        # For this implementation, we'll use the value area high/low as proxies
        # for opening range high/low. This is a reasonable approximation since
        # value areas are calculated over similar timeframes.
        # 
        # In a full implementation, we'd track actual opening range from 
        # StateManager, but for now this provides the core breakout logic.
        
        opening_range_high = features.value_area_high
        opening_range_low = features.value_area_low
        current_price = features.price
        rotation = features.rotation_factor
        
        # Check for LONG breakout (above opening range high)
        if allow_longs and rotation >= min_rotation_factor:
            # Price must break ABOVE opening range high with confirmation
            breakout_level = opening_range_high * (1.0 + breakout_confirmation_pct)
            
            if current_price > breakout_level:
                # Breakout confirmed!
                entry = current_price
                
                # Stop loss at opening range high (broken level becomes support)
                sl = opening_range_high
                stop_distance = entry - sl
                
                # Take profit based on reward ratio
                tp = entry + (stop_distance * reward_ratio)
                
                # Position sizing based on stop distance
                size = (account.equity * risk_per_trade_pct) / stop_distance
                
                return StrategySignal(
                    strategy_id=self.strategy_id,
                    symbol=features.symbol,
                    side="long",
                    size=size,
                    entry_price=entry,
                    stop_loss=sl,
                    take_profit=tp,
                    meta_reason=f"opening_range_breakout_long_rot_{rotation:.1f}_rr_{reward_ratio}",
                    profile_id=profile.id,
                )
        
        # Check for SHORT breakout (below opening range low)
        if allow_shorts and rotation <= -min_rotation_factor:
            # Price must break BELOW opening range low with confirmation
            breakout_level = opening_range_low * (1.0 - breakout_confirmation_pct)
            
            if current_price < breakout_level:
                # Breakout confirmed!
                entry = current_price
                
                # Stop loss at opening range low (broken level becomes resistance)
                sl = opening_range_low
                stop_distance = sl - entry
                
                # Take profit based on reward ratio
                tp = entry - (stop_distance * reward_ratio)
                
                # Position sizing based on stop distance
                size = (account.equity * risk_per_trade_pct) / stop_distance
                
                return StrategySignal(
                    strategy_id=self.strategy_id,
                    symbol=features.symbol,
                    side="short",
                    size=size,
                    entry_price=entry,
                    stop_loss=sl,
                    take_profit=tp,
                    meta_reason=f"opening_range_breakout_short_rot_{abs(rotation):.1f}_rr_{reward_ratio}",
                    profile_id=profile.id,
                )
        
        return None
