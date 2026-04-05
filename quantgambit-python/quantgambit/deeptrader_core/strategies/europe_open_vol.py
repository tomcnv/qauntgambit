"""
Europe Open Volatility Strategy

Captures volatility spike at European market open.
Session: 07:00-08:00 UTC (first hour)
"""

from typing import Optional, Dict, Any
from datetime import datetime, UTC

from quantgambit.deeptrader_core.types import Features, AccountState, Profile, StrategySignal
from .base import Strategy


class EuropeOpenVol(Strategy):
    """
    Trade volatility spike at European open.
    
    Market Conditions:
    - Session: europe (07:00-08:00 UTC first hour)
    - Volatility: normal to high
    - Any trend direction
    - Volume increasing
    
    Entry Logic:
    - First breakout after 07:00 UTC
    - Confirmed by volume (high trades/sec)
    - Wait for initial spike to settle
    - Enter on retest with rotation confirmation
    
    Risk Profile:
    - Medium stops (0.5-0.8%)
    - Standard position size (0.8-1.2% risk)
    - Target: Ride volatility (1.0-2.0%)
    """
    
    strategy_id = "europe_open_vol"
    
    def generate_signal(
        self,
        features: Features,
        account: AccountState,
        profile: Profile,
        params: Dict[str, Any],
    ) -> Optional[StrategySignal]:
        """Generate signal for Europe open volatility"""
        
        # Extract parameters with defaults
        allow_longs = params.get('allow_longs', True)
        allow_shorts = params.get('allow_shorts', True)
        open_window_minutes = params.get('open_window_minutes', 60)  # First 60 min
        min_atr_ratio = params.get('min_atr_ratio', 1.0)  # ATR expanding, but not extreme
        min_trades_per_sec = params.get('min_trades_per_sec', 1.5)  # Europe open can be active without being fully spiky
        rotation_threshold = params.get('rotation_threshold', 3.0)
        risk_per_trade_pct = params.get('risk_per_trade_pct', 0.01)
        stop_loss_pct = params.get('stop_loss_pct', 0.012)  # 1.2% (was 0.6%)
        take_profit_pct = params.get('take_profit_pct', 0.024)  # 2.4% (was 1.5%)
        max_spread = params.get('max_spread', 0.0015)
        
        # Session filter - must be Europe
        if profile.session != 'europe':
            return None
        
        # Time window filter - first hour only
        dt = datetime.fromtimestamp(features.timestamp, UTC)
        if dt.hour != 7:  # 07:00-08:00 UTC
            return None
        
        # Volatility filter - must have expanding volatility
        if profile.volatility not in ['normal', 'high']:
            return None
        
        # ATR ratio check - volatility must be expanding
        if features.atr_5m_baseline > 0:
            atr_ratio = features.atr_5m / features.atr_5m_baseline
            if atr_ratio < min_atr_ratio:
                return None
        
        # Volume check - need increased activity
        if features.trades_per_second < min_trades_per_sec:
            return None
        
        # Spread check
        if features.spread > max_spread:
            return None
        
        # Need value area for breakout detection
        if features.value_area_high is None or features.value_area_low is None:
            return None
        
        # Determine breakout direction
        breakout_confirmation_pct = params.get("breakout_confirmation_pct", 0.0015)
        is_above_vah = features.price >= features.value_area_high * (1 - breakout_confirmation_pct)
        is_below_val = features.price <= features.value_area_low * (1 + breakout_confirmation_pct)
        
        # Long: Breakout above VAH with strong rotation
        if is_above_vah and allow_longs:
            if features.rotation_factor > rotation_threshold:
                # Calculate position size
                stop_distance = features.price * stop_loss_pct
                position_value = account.equity * risk_per_trade_pct
                size = position_value / stop_distance
                
                # Calculate levels
                stop_loss = features.value_area_high * (1 - (stop_loss_pct * 0.8))  # Just below VAH
                take_profit = features.price * (1 + take_profit_pct)
                
                return StrategySignal(
                    strategy_id=self.strategy_id,
                    symbol=features.symbol,
                    side='long',
                    size=size,
                    entry_price=features.price,
                    stop_loss=stop_loss,
                    take_profit=take_profit,
                    meta_reason=f"europe_open_breakout_long_rot_{features.rotation_factor:.1f}",
                    profile_id=profile.id
                )
        
        # Short: Breakout below VAL with strong rotation
        if is_below_val and allow_shorts:
            if features.rotation_factor < -rotation_threshold:
                # Calculate position size
                stop_distance = features.price * stop_loss_pct
                position_value = account.equity * risk_per_trade_pct
                size = position_value / stop_distance
                
                # Calculate levels
                stop_loss = features.value_area_low * (1 + (stop_loss_pct * 0.8))  # Just above VAL
                take_profit = features.price * (1 - take_profit_pct)
                
                return StrategySignal(
                    strategy_id=self.strategy_id,
                    symbol=features.symbol,
                    side='short',
                    size=size,
                    entry_price=features.price,
                    stop_loss=stop_loss,
                    take_profit=take_profit,
                    meta_reason=f"europe_open_breakout_short_rot_{features.rotation_factor:.1f}",
                    profile_id=profile.id
                )
        
        return None
