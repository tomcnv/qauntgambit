"""
Overnight Thin Market Strategy

Ultra-conservative strategy for low liquidity overnight periods.
Session: 22:00-00:00 UTC
"""

from typing import Optional, Dict, Any
from datetime import datetime, UTC

from quantgambit.deeptrader_core.types import Features, AccountState, Profile, StrategySignal
from .base import Strategy


class OvernightThin(Strategy):
    """
    Conservative trading during overnight thin markets.
    
    Market Conditions:
    - Session: overnight (22:00-00:00 UTC)
    - Volatility: low to normal
    - Any trend (but requires strong confirmation)
    - Low liquidity
    
    Entry Logic:
    - Only trade obvious setups
    - Require 2x normal confirmation
    - Wider spreads tolerated (thin market)
    - Very selective
    
    Risk Profile:
    - Tight stops (0.3-0.5%)
    - Small position size (0.3-0.5% risk)
    - Conservative targets (0.4-0.8%)
    """
    
    strategy_id = "overnight_thin"
    
    def generate_signal(
        self,
        features: Features,
        account: AccountState,
        profile: Profile,
        params: Dict[str, Any],
    ) -> Optional[StrategySignal]:
        """Generate signal for overnight thin market"""
        
        # Extract parameters with defaults
        allow_longs = params.get('allow_longs', True)
        allow_shorts = params.get('allow_shorts', True)
        rotation_threshold = params.get('rotation_threshold', 8.0)  # High confirmation
        min_distance_from_vah = params.get('min_distance_from_vah', 0.003)  # 0.3%
        min_distance_from_val = params.get('min_distance_from_val', 0.003)  # 0.3%
        risk_per_trade_pct = params.get('risk_per_trade_pct', 0.004)  # Small size
        stop_loss_pct = params.get('stop_loss_pct', 0.012)  # 1.2% (was 0.4%)
        take_profit_pct = params.get('take_profit_pct', 0.018)  # 1.8% (was 0.6%)
        max_spread = params.get('max_spread', 0.002)  # Wider tolerance for thin markets
        require_trend_alignment = params.get('require_trend_alignment', True)
        
        # Session filter - must be overnight
        if profile.session != 'overnight':
            return None
        
        # Volatility filter - avoid high volatility in thin markets
        if profile.volatility == 'high':
            return None
        
        # Spread check (more lenient for overnight)
        if features.spread > max_spread:
            return None
        
        # Need value area for safe trading
        if features.value_area_high is None or features.value_area_low is None:
            return None
        
        # Very selective - only trade clear rejections at value area extremes
        is_near_vah = features.value_area_high and abs(features.price - features.value_area_high) / features.price < min_distance_from_vah
        is_near_val = features.value_area_low and abs(features.price - features.value_area_low) / features.price < min_distance_from_val
        
        # Additional confirmation: check if trend aligns with direction
        if require_trend_alignment:
            # For long, prefer uptrend or flat
            # For short, prefer downtrend or flat
            pass  # We'll check this per signal
        
        # Long: Price near VAL, strong rejection upward
        if is_near_val and allow_longs:
            # Need very strong rotation confirmation (2x normal)
            if features.rotation_factor > rotation_threshold:
                # Additional trend check
                if require_trend_alignment and profile.trend == 'down':
                    return None  # Don't fight downtrend in thin market
                
                # Calculate position size (small for thin market)
                stop_distance = features.price * stop_loss_pct
                position_value = account.equity * risk_per_trade_pct
                size = position_value / stop_distance
                
                # Calculate levels
                stop_loss = features.value_area_low * (1 - (stop_loss_pct * 0.8))  # Just below VAL
                take_profit = features.price * (1 + take_profit_pct)
                
                return StrategySignal(
                    strategy_id=self.strategy_id,
                    symbol=features.symbol,
                    side='long',
                    size=size,
                    entry_price=features.price,
                    stop_loss=stop_loss,
                    take_profit=take_profit,
                    meta_reason=f"overnight_rejection_long_rot_{features.rotation_factor:.1f}",
                    profile_id=profile.id
                )
        
        # Short: Price near VAH, strong rejection downward
        if is_near_vah and allow_shorts:
            # Need very strong rotation confirmation (2x normal)
            if features.rotation_factor < -rotation_threshold:
                # Additional trend check
                if require_trend_alignment and profile.trend == 'up':
                    return None  # Don't fight uptrend in thin market
                
                # Calculate position size (small for thin market)
                stop_distance = features.price * stop_loss_pct
                position_value = account.equity * risk_per_trade_pct
                size = position_value / stop_distance
                
                # Calculate levels
                stop_loss = features.value_area_high * (1 + (stop_loss_pct * 0.8))  # Just above VAH
                take_profit = features.price * (1 - take_profit_pct)
                
                return StrategySignal(
                    strategy_id=self.strategy_id,
                    symbol=features.symbol,
                    side='short',
                    size=size,
                    entry_price=features.price,
                    stop_loss=stop_loss,
                    take_profit=take_profit,
                    meta_reason=f"overnight_rejection_short_rot_{features.rotation_factor:.1f}",
                    profile_id=profile.id
                )
        
        return None
