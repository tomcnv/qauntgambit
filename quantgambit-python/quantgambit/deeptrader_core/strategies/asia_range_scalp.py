"""
Asia Range Scalp Strategy

Exploits Asia session's typically range-bound behavior with tight scalps.
Session: 00:00-07:00 UTC
"""

from typing import Optional, Dict, Any
from datetime import datetime, UTC

from quantgambit.deeptrader_core.types import Features, AccountState, Profile, StrategySignal
from .base import Strategy


class AsiaRangeScalp(Strategy):
    """
    Trade range-bound behavior during Asia session.
    
    Market Conditions:
    - Session: asia (00:00-07:00 UTC)
    - Trend: flat
    - Volatility: low to normal
    - Value Location: inside
    
    Entry Logic:
    - Identify session high/low
    - Trade bounces within range
    - Tight profit targets (0.2-0.4%)
    - Small position sizes
    
    Risk Profile:
    - Very tight stops (0.2-0.3%)
    - Small position size (0.3-0.5% risk)
    - Quick scalp targets
    """
    
    strategy_id = "asia_range_scalp"
    
    def generate_signal(
        self,
        features: Features,
        account: AccountState,
        profile: Profile,
        params: Dict[str, Any],
    ) -> Optional[StrategySignal]:
        """Generate signal for Asia range scalp"""
        
        # Extract parameters with defaults
        allow_longs = params.get('allow_longs', True)
        allow_shorts = params.get('allow_shorts', True)
        min_distance_from_val = params.get('min_distance_from_val', 0.002)  # 0.2%
        max_distance_from_val = params.get('max_distance_from_val', 0.008)  # 0.8%
        rotation_threshold = params.get('rotation_threshold', 3.0)
        risk_per_trade_pct = params.get('risk_per_trade_pct', 0.004)
        stop_loss_pct = params.get('stop_loss_pct', 0.01)  # 1.0% (was 0.25% - too tight for crypto)
        take_profit_pct = params.get('take_profit_pct', 0.015)  # 1.5% (was 0.3%)
        max_spread = params.get('max_spread', 0.0005)
        
        # Session filter - must be Asia session
        if profile.session != 'asia':
            return None
        
        # Trend filter - prefer flat markets
        if profile.trend not in ['flat']:
            return None
        
        # Volatility filter - low to normal only
        if profile.volatility not in ['low', 'normal']:
            return None
        
        # Value location filter - must be inside
        if profile.value_location != 'inside':
            return None
        
        # Spread check
        if features.spread > max_spread:
            return None
        
        # Need POC for range trading
        if features.point_of_control is None:
            return None
        
        # Calculate distance from POC
        distance_from_poc = abs(features.price - features.point_of_control) / features.price
        
        # Must be within range boundaries
        if distance_from_poc < min_distance_from_val:
            return None  # Too close to POC
        
        if distance_from_poc > max_distance_from_val:
            return None  # Too far from range
        
        # Determine side based on position relative to POC
        is_above_poc = features.price > features.point_of_control
        is_below_poc = features.price < features.point_of_control
        
        # Look for mean reversion opportunities
        # Long: Price below POC, rotation turning up
        if is_below_poc and allow_longs:
            # Need rotation turning positive (mean reversion)
            if features.rotation_factor > rotation_threshold:
                # Calculate position size
                stop_distance = features.price * stop_loss_pct
                position_value = account.equity * risk_per_trade_pct
                size = position_value / stop_distance
                
                # Calculate levels
                stop_loss = features.price * (1 - stop_loss_pct)
                take_profit = features.price * (1 + take_profit_pct)
                
                return StrategySignal(
                    strategy_id=self.strategy_id,
                    symbol=features.symbol,
                    side='long',
                    size=size,
                    entry_price=features.price,
                    stop_loss=stop_loss,
                    take_profit=take_profit,
                    meta_reason=f"asia_range_long_dist_{distance_from_poc:.4f}",
                    profile_id=profile.id
                )
        
        # Short: Price above POC, rotation turning down
        if is_above_poc and allow_shorts:
            # Need rotation turning negative (mean reversion)
            if features.rotation_factor < -rotation_threshold:
                # Calculate position size
                stop_distance = features.price * stop_loss_pct
                position_value = account.equity * risk_per_trade_pct
                size = position_value / stop_distance
                
                # Calculate levels
                stop_loss = features.price * (1 + stop_loss_pct)
                take_profit = features.price * (1 - take_profit_pct)
                
                return StrategySignal(
                    strategy_id=self.strategy_id,
                    symbol=features.symbol,
                    side='short',
                    size=size,
                    entry_price=features.price,
                    stop_loss=stop_loss,
                    take_profit=take_profit,
                    meta_reason=f"asia_range_short_dist_{distance_from_poc:.4f}",
                    profile_id=profile.id
                )
        
        return None
