"""
VWAP Reversion Strategy

Mean reversion to session VWAP (Volume-Weighted Average Price).
VWAP is a key institutional reference level that price tends to gravitate toward.

Entry Conditions:
- Price deviates roughly 0.2-1.5% from session VWAP
- Rotation confirms reversal toward VWAP
- Not at extreme deviations (avoid catching falling knives)
- Target VWAP or slightly beyond

Risk Management:
- Moderate stops (0.8%) to handle noise
- Target VWAP with small buffer (0.2%)
- Moderate-high position sizing (1.5% risk)

Ideal Market Conditions:
- Normal volatility (not trending strongly)
- Inside value area (mean-reverting regime)
- Any session (VWAP is universal)
- Good volume for VWAP relevance

NOTE: Requires VWAP calculation from candle/trade data.
"""

from typing import Optional, Dict, Any
from quantgambit.deeptrader_core.types import Features, AccountState, Profile, StrategySignal
from .base import Strategy
from quantgambit.observability.logger import log_info


class VWAPReversion(Strategy):
    strategy_id = "vwap_reversion"

    def generate_signal(
        self,
        features: Features,
        account: AccountState,
        profile: Profile,
        params: Dict[str, Any],
    ) -> Optional[StrategySignal]:
        """Generate signal for VWAP mean reversion strategy"""
        
        allow_longs = params.get("allow_longs", True)
        allow_shorts = params.get("allow_shorts", True)

        # Check if longs/shorts are allowed
        if not allow_longs and not allow_shorts:
            return None

        # Market conditions: Normal volatility preferred (not strongly trending)
        if profile.volatility not in ["low", "normal"]:
            return None
        
        # Prefer inside value area (mean-reverting regime)
        if profile.value_location not in ["inside", "flat"]:
            return None
        
        # Validate required features
        vwap = features.vwap
        if not vwap:
            log_info(f"VWAPReversion: Missing VWAP data for {features.symbol}")
            return None
        
        # Calculate deviation from VWAP
        deviation = (features.price - vwap) / vwap
        deviation_pct = abs(deviation)
        
        min_deviation_pct = params.get("min_deviation_pct", 0.0008)
        max_deviation_pct = params.get("max_deviation_pct", 0.015)
        
        # Check if deviation is in acceptable range
        if deviation_pct < min_deviation_pct or deviation_pct > max_deviation_pct:
            return None
        
        # Check spread
        if features.spread > params.get("max_spread", 0.004):
            log_info(f"VWAPReversion: Spread too wide ({features.spread:.4f}) for {features.symbol}")
            return None
        
        signal_side = None
        entry_price = features.price
        stop_loss = 0.0
        take_profit = 0.0
        meta_reason = ""

        rotation_threshold = params.get("rotation_threshold", 1.0)
        stop_loss_pct = params.get("stop_loss_pct", 0.006)
        min_reward_risk_ratio = params.get("min_reward_risk_ratio", 1.25)
        min_vwap_anchor_rr_ratio = params.get("min_vwap_anchor_rr_ratio", 0.85)

        # Long signal: Price below VWAP, rotating up toward VWAP
        if allow_longs and deviation < 0:  # Below VWAP
            # Confirm rotation toward VWAP (upward)
            if features.rotation_factor > rotation_threshold:
                signal_side = "long"
                stop_loss = features.price * (1 - stop_loss_pct)
                
                # Target VWAP with buffer
                if params.get("take_profit_at_vwap", True):
                    vwap_offset = vwap * params.get("vwap_offset_pct", 0.002)
                    take_profit = vwap + vwap_offset
                else:
                    take_profit = features.price * (1 + abs(deviation))
                
                meta_reason = f"vwap_reversion_long_dev_{deviation:.3f}"

        # Short signal: Price above VWAP, rotating down toward VWAP
        elif allow_shorts and deviation > 0:  # Above VWAP
            # Confirm rotation toward VWAP (downward)
            if features.rotation_factor < -rotation_threshold:
                signal_side = "short"
                stop_loss = features.price * (1 + stop_loss_pct)
                
                # Target VWAP with buffer
                if params.get("take_profit_at_vwap", True):
                    vwap_offset = vwap * params.get("vwap_offset_pct", 0.002)
                    take_profit = vwap - vwap_offset
                else:
                    take_profit = features.price * (1 - abs(deviation))
                
                meta_reason = f"vwap_reversion_short_dev_{deviation:.3f}"

        if signal_side:
            stop_distance = abs(entry_price - stop_loss)
            anchored_take_profit = take_profit
            anchored_take_profit_distance = abs(entry_price - anchored_take_profit)
            if (
                params.get("take_profit_at_vwap", True)
                and stop_distance > 0.0
                and anchored_take_profit_distance < (stop_distance * max(min_vwap_anchor_rr_ratio, 0.0))
            ):
                log_info(
                    f"VWAPReversion: Anchored VWAP target too close for {features.symbol}. "
                    f"TP distance {anchored_take_profit_distance:.4f} < "
                    f"{stop_distance * max(min_vwap_anchor_rr_ratio, 0.0):.4f}"
                )
                return None
            min_take_profit_distance = stop_distance * max(min_reward_risk_ratio, 0.0)
            if signal_side == "long":
                take_profit = max(take_profit, entry_price + min_take_profit_distance)
            else:
                take_profit = min(take_profit, entry_price - min_take_profit_distance)

            # Calculate position size
            risk_per_trade_pct = params.get("risk_per_trade_pct", 0.015)
            price_diff = stop_distance
            
            if price_diff == 0:
                log_info(f"VWAPReversion: Stop loss price is same as entry price for {features.symbol}, cannot calculate size.")
                return None
            
            # Position size based on risk percentage and stop distance
            position_value = account.equity * (risk_per_trade_pct / stop_loss_pct)
            size = position_value / entry_price
            
            if size <= 0:
                log_info(f"VWAPReversion: Calculated size is zero or negative for {features.symbol}")
                return None

            log_info(f"VWAPReversion: Generated {signal_side} signal for {features.symbol} @ {entry_price:.2f} "
                    f"with size {size:.4f}. VWAP: {vwap:.2f}, Deviation: {deviation:.3f}. "
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
