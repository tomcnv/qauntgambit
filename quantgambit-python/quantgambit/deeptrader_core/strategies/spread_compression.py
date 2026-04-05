"""
Spread Compression Strategy

Detects spread compression (coiling/tightening) as a precursor to volatility expansion.
Narrow spreads indicate market consolidation before a breakout move.

Entry Conditions:
- Spread significantly below baseline (< 70%)
- Sustained compression (not a momentary spike)
- Price near value area boundary (breakout setup)
- Direction bias from rotation/EMAs
- Enter before expansion for edge

Risk Management:
- Moderate stops (0.6%) to allow breakout room
- Wide targets (1.5%) to capture expansion
- Moderate position sizing (1.0% risk)

Ideal Market Conditions:
- Low → Normal volatility transition
- Inside or at value area boundaries
- Clear directional bias forming
- Good liquidity for breakout
"""

from typing import Optional, Dict, Any
from quantgambit.deeptrader_core.types import Features, AccountState, Profile, StrategySignal
from .base import Strategy
from quantgambit.observability.logger import log_info


class SpreadCompression(Strategy):
    strategy_id = "spread_compression"

    def generate_signal(
        self,
        features: Features,
        account: AccountState,
        profile: Profile,
        params: Dict[str, Any],
    ) -> Optional[StrategySignal]:
        """Generate signal for spread compression breakout strategy"""
        
        # Check if longs/shorts are allowed
        if not params.get("allow_longs") and not params.get("allow_shorts"):
            return None

        # Market conditions: Low to normal volatility (compression phase)
        if profile.volatility not in ["low", "normal"]:
            return None
        
        # Validate required features
        if not features.value_area_high or not features.value_area_low:
            log_info(f"SpreadCompression: Missing value area data for {features.symbol}")
            return None
        
        # NOTE: In production, we'd track spread history over time
        # For now, we use current spread vs a baseline concept
        # If spread is very tight, we assume compression
        
        compression_threshold = params.get("compression_threshold", 0.7)
        # Assume baseline spread is 0.001 (0.1%) for crypto
        baseline_spread = 0.001
        
        # Check if spread is compressed
        if features.spread > baseline_spread * compression_threshold:
            # Spread not compressed enough
            return None
        
        # Spread is tight - look for directional bias
        signal_side = None
        entry_price = features.price
        stop_loss = 0.0
        take_profit = 0.0
        meta_reason = ""

        min_rotation_factor = params.get("min_rotation_factor", 2.5)
        breakout_confirmation_pct = params.get("breakout_confirmation_pct", 0.001)

        # Long signal: Compressed spread + upward bias + near VAH
        if params.get("allow_longs"):
            # Price near VAH or above, with upward rotation and EMA alignment
            if features.price >= features.value_area_high * (1 - breakout_confirmation_pct) and \
               features.rotation_factor > min_rotation_factor and \
               features.ema_fast_15m > features.ema_slow_15m:
                
                signal_side = "long"
                stop_loss = features.price * (1 - params.get("stop_loss_pct", 0.012))  # 1.2% (was 0.6%)
                take_profit = features.price * (1 + params.get("take_profit_pct", 0.024))  # 2.4% (was 1.5%)
                meta_reason = f"spread_compression_long_breakout_spread_{features.spread:.4f}"

        # Short signal: Compressed spread + downward bias + near VAL
        if params.get("allow_shorts"):
            # Price near VAL or below, with downward rotation and EMA alignment
            if features.price <= features.value_area_low * (1 + breakout_confirmation_pct) and \
               features.rotation_factor < -min_rotation_factor and \
               features.ema_fast_15m < features.ema_slow_15m:
                
                signal_side = "short"
                stop_loss = features.price * (1 + params.get("stop_loss_pct", 0.012))  # 1.2% (was 0.6%)
                take_profit = features.price * (1 - params.get("take_profit_pct", 0.024))  # 2.4% (was 1.5%)
                meta_reason = f"spread_compression_short_breakout_spread_{features.spread:.4f}"

        if signal_side:
            # Calculate position size
            risk_per_trade_pct = params.get("risk_per_trade_pct", 0.01)
            price_diff = abs(entry_price - stop_loss)
            
            if price_diff == 0:
                log_info(f"SpreadCompression: Stop loss price is same as entry price for {features.symbol}, cannot calculate size.")
                return None
            
            # Position size based on risk percentage and stop distance
            position_value = account.equity * (risk_per_trade_pct / params.get("stop_loss_pct", 0.012))
            size = position_value / entry_price
            
            if size <= 0:
                log_info(f"SpreadCompression: Calculated size is zero or negative for {features.symbol}")
                return None

            log_info(f"SpreadCompression: Generated {signal_side} signal for {features.symbol} @ {entry_price:.2f} "
                    f"with size {size:.4f}. Spread: {features.spread:.4f} (compressed). "
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
