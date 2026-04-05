"""
High Volatility Breakout Strategy

Captures explosive breakouts during volatility spikes (ATR > 2x baseline).
Uses wide stops and aggressive targets during high-momentum conditions.

Entry Conditions:
- ATR must be > 2x baseline (high volatility spike)
- Price breaks above VAH (long) or below VAL (short) with confirmation
- Strong rotation in breakout direction
- Volume surge confirmation (optional but preferred)
- Clear EMA alignment for directional bias

Risk Management:
- Wider stops (1.5%) to avoid volatility whipsaws
- Aggressive targets (2%) to capture momentum
- Larger position sizing (0.8% risk) when conditions are ideal

Ideal Market Conditions:
- High volatility (ATR > 2x baseline)
- Strong directional momentum
- Clear breakout from value area
- High volume/liquidity
"""

from typing import Optional, Dict, Any
from quantgambit.deeptrader_core.types import Features, AccountState, Profile, StrategySignal
from .base import Strategy
from quantgambit.observability.logger import log_info


class HighVolBreakout(Strategy):
    strategy_id = "high_vol_breakout"

    def generate_signal(
        self,
        features: Features,
        account: AccountState,
        profile: Profile,
        params: Dict[str, Any],
    ) -> Optional[StrategySignal]:
        """Generate signal for high volatility breakout strategy"""
        
        allow_longs = params.get("allow_longs", True)
        allow_shorts = params.get("allow_shorts", True)

        # Check if longs/shorts are allowed
        if not allow_longs and not allow_shorts:
            return None

        # Market conditions: High volatility required
        if profile.volatility != "high":
            return None
        
        # Check spread - can tolerate wider spreads in high vol
        if features.spread > params.get("max_spread", 0.005):
            log_info(f"HighVolBreakout: Spread too wide ({features.spread:.4f}) for {features.symbol}")
            return None
        
        # Validate required features
        if not features.value_area_high or not features.value_area_low:
            log_info(f"HighVolBreakout: Missing value area data for {features.symbol}")
            return None
        
        # Check for ATR spike (core requirement)
        atr_ratio = features.atr_5m / features.atr_5m_baseline if features.atr_5m_baseline > 0 else 0
        min_atr_ratio = params.get("min_atr_ratio", 1.5)
        
        if atr_ratio < min_atr_ratio:
            # Not a volatility spike - don't trade
            return None
        
        # Optional: Check for volume surge (if trades_per_second is high)
        min_trades_per_sec = params.get("min_trades_per_sec", 1.5)
        if features.trades_per_second < min_trades_per_sec:
            log_info(f"HighVolBreakout: Insufficient liquidity ({features.trades_per_second:.1f} tps) for {features.symbol}")
            return None

        signal_side = None
        entry_price = features.price
        stop_loss = 0.0
        take_profit = 0.0
        meta_reason = ""

        breakout_confirmation_pct = params.get("breakout_confirmation_pct", 0.0010)
        min_rotation_factor = params.get("min_rotation_factor", 3.0)

        # Long signal: Price breaks above VAH with strong upward rotation
        if allow_longs and \
           features.price > features.value_area_high * (1 + breakout_confirmation_pct) and \
           features.rotation_factor > min_rotation_factor:
            
            # Additional confirmation: EMA alignment for uptrend (optional but strong signal)
            if features.ema_fast_15m > features.ema_slow_15m:
                signal_side = "long"
                stop_loss = features.price * (1 - params.get("stop_loss_pct", 0.015))
                take_profit = features.price * (1 + params.get("take_profit_pct", 0.02))
                meta_reason = f"high_vol_breakout_long_vah_break_atr_{atr_ratio:.2f}x"
            else:
                log_info(f"HighVolBreakout: Long breakout but EMAs not aligned for {features.symbol}")

        # Short signal: Price breaks below VAL with strong downward rotation
        elif allow_shorts and \
             features.price < features.value_area_low * (1 - breakout_confirmation_pct) and \
             features.rotation_factor < -min_rotation_factor:
            
            # Additional confirmation: EMA alignment for downtrend
            if features.ema_fast_15m < features.ema_slow_15m:
                signal_side = "short"
                stop_loss = features.price * (1 + params.get("stop_loss_pct", 0.015))
                take_profit = features.price * (1 - params.get("take_profit_pct", 0.02))
                meta_reason = f"high_vol_breakout_short_val_break_atr_{atr_ratio:.2f}x"
            else:
                log_info(f"HighVolBreakout: Short breakout but EMAs not aligned for {features.symbol}")

        if signal_side:
            # Calculate position size
            risk_per_trade_pct = params.get("risk_per_trade_pct", 0.008)
            price_diff = abs(entry_price - stop_loss)
            
            if price_diff == 0:
                log_info(f"HighVolBreakout: Stop loss price is same as entry price for {features.symbol}, cannot calculate size.")
                return None
            
            # Position size based on risk percentage and stop distance
            # Aggressive sizing due to strong conditions
            position_value = account.equity * (risk_per_trade_pct / params.get("stop_loss_pct", 0.015))
            size = position_value / entry_price
            
            if size <= 0:
                log_info(f"HighVolBreakout: Calculated size is zero or negative for {features.symbol}")
                return None

            log_info(f"HighVolBreakout: Generated {signal_side} signal for {features.symbol} @ {entry_price:.2f} "
                    f"with size {size:.4f}. ATR: {atr_ratio:.2f}x baseline. "
                    f"SL: {stop_loss:.2f}, TP: {take_profit:.2f}. Reason: {meta_reason}")
            
            return StrategySignal(
                strategy_id=self.strategy_id,
                symbol=features.symbol,
                side=signal_side,
                size=size,
                entry_price=entry_price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                meta_reason=meta_reason,
                profile_id=profile.id
            )
        
        return None
