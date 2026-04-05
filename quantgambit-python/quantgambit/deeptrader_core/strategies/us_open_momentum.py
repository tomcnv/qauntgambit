"""
US Open Momentum Strategy

Trades high-liquidity momentum moves at US market open.
Session: 12:00-14:00 UTC (first 2 hours for extended window)
"""

from typing import Optional, Dict, Any
from datetime import datetime, UTC

from quantgambit.deeptrader_core.types import Features, AccountState, Profile, StrategySignal
from .base import Strategy


class USOpenMomentum(Strategy):
    """
    Trade US session open momentum with high liquidity.
    
    Market Conditions:
    - Session: us (13:00-14:00 UTC first hour, or 12:00-14:00 extended)
    - Volatility: normal to high
    - Trend: up or down (strong directional)
    - Highest liquidity period
    
    Entry Logic:
    - Strong directional move at US open
    - Aligned with EMA trend
    - High volume confirmation
    - Enter pullbacks or breakouts
    
    Risk Profile:
    - Medium to wide stops (0.7-1.2%)
    - Larger position size (1.0-2.0% risk)
    - Swing targets (1.5-3.0%)
    """
    
    strategy_id = "us_open_momentum"
    
    def generate_signal(
        self,
        features: Features,
        account: AccountState,
        profile: Profile,
        params: Dict[str, Any],
    ) -> Optional[StrategySignal]:
        """Generate signal for US open momentum"""
        
        # Extract parameters with defaults
        allow_longs = params.get('allow_longs', True)
        allow_shorts = params.get('allow_shorts', True)
        extended_window = params.get('extended_window', True)  # 12:00-14:00 vs 13:00-14:00
        min_ema_spread_pct = params.get('min_ema_spread_pct', 0.0015)  # 0.15% EMA separation
        min_rotation_factor = params.get('min_rotation_factor', 3.0)  # Momentum, but not ultra-strict
        min_trades_per_sec = params.get('min_trades_per_sec', 1.0)  # Crypto baseline liquidity
        risk_per_trade_pct = params.get('risk_per_trade_pct', 0.015)
        stop_loss_pct = params.get('stop_loss_pct', 0.010)  # 1.0%
        take_profit_pct = params.get('take_profit_pct', 0.025)  # 2.5%
        max_spread = params.get('max_spread', 0.0015)
        
        # Session filter - must be US
        if profile.session != 'us':
            return None

        # Time window filter
        if features.timestamp is None:
            return None
        dt = datetime.fromtimestamp(features.timestamp, UTC)
        if extended_window:
            if dt.hour not in [12, 13]:  # 12:00-14:00 UTC
                return None
        else:
            if dt.hour != 13:  # 13:00-14:00 UTC only
                return None
        
        # Volume check - highest liquidity period
        if features.trades_per_second is None:
            return None
        if features.trades_per_second < min_trades_per_sec:
            return None

        # Spread check
        if features.spread > max_spread:
            return None

        # EMA alignment check - trend confirmation.
        # Keep fail-closed behavior when EMA context is missing.
        ema_fast = features.ema_fast_15m
        ema_slow = features.ema_slow_15m
        if ema_fast is None or ema_slow is None:
            return None
        ema_spread = abs(ema_fast - ema_slow) / features.price
        if ema_spread < min_ema_spread_pct:
            return None  # EMAs too close, no clear trend
        is_uptrend = ema_fast > ema_slow
        is_downtrend = ema_fast < ema_slow
        
        # Long: Uptrend + positive rotation
        if is_uptrend and allow_longs:
            # Need strong momentum but can enter on brief pullbacks
            if features.rotation_factor > min_rotation_factor:
                # Calculate position size (larger for high liquidity)
                stop_distance = features.price * stop_loss_pct
                position_value = account.equity * risk_per_trade_pct
                size = position_value / stop_distance
                
                # Calculate levels
                # Stop below recent support (fast EMA)
                stop_loss = max(
                    features.ema_fast_15m * 0.995,  # 0.5% below fast EMA
                    features.price * (1 - stop_loss_pct)
                )
                take_profit = features.price * (1 + take_profit_pct)
                
                return StrategySignal(
                    strategy_id=self.strategy_id,
                    symbol=features.symbol,
                    side='long',
                    size=size,
                    entry_price=features.price,
                    stop_loss=stop_loss,
                    take_profit=take_profit,
                    meta_reason=f"us_open_momentum_long_rot_{features.rotation_factor:.1f}",
                    profile_id=profile.id
                )
        
        # Short: Downtrend + negative rotation
        if is_downtrend and allow_shorts:
            if features.rotation_factor < -min_rotation_factor:
                # Calculate position size (larger for high liquidity)
                stop_distance = features.price * stop_loss_pct
                position_value = account.equity * risk_per_trade_pct
                size = position_value / stop_distance
                
                # Calculate levels
                # Stop above recent resistance (fast EMA)
                stop_loss = min(
                    features.ema_fast_15m * 1.005,  # 0.5% above fast EMA
                    features.price * (1 + stop_loss_pct)
                )
                take_profit = features.price * (1 - take_profit_pct)
                
                return StrategySignal(
                    strategy_id=self.strategy_id,
                    symbol=features.symbol,
                    side='short',
                    size=size,
                    entry_price=features.price,
                    stop_loss=stop_loss,
                    take_profit=take_profit,
                    meta_reason=f"us_open_momentum_short_rot_{features.rotation_factor:.1f}",
                    profile_id=profile.id
                )
        
        return None
