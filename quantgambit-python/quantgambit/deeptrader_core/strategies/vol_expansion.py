"""
Volatility Expansion Strategy

Catches regime transitions from compression to expansion (Bollinger Band squeeze breakouts).
Trades the initial thrust when volatility expands after a period of compression.

Entry Conditions:
- ATR has been declining for 3+ periods (compression phase)
- ATR starts expanding (increases by 20%+)
- Price breaks out of compression range
- Strong rotation in breakout direction
- Direction confirmed by EMAs or price action

Risk Management:
- Medium stops (0.8%) to allow expansion room
- Medium-large targets (1.5%) to capture momentum
- Moderate position sizing (0.6% risk)

Ideal Market Conditions:
- Flat/inside value area → breakout
- Low → Normal volatility transition
- Clear directional catalyst
- Good liquidity

Note: This strategy requires tracking ATR history, which we'll approximate
using the relationship between current ATR and baseline ATR.
"""

from typing import Optional, Dict, Any
from quantgambit.deeptrader_core.types import Features, AccountState, Profile, StrategySignal
from .base import Strategy
from quantgambit.observability.logger import log_info


class VolExpansion(Strategy):
    strategy_id = "vol_expansion"

    def generate_signal(
        self,
        features: Features,
        account: AccountState,
        profile: Profile,
        params: Dict[str, Any],
    ) -> Optional[StrategySignal]:
        """Generate signal for volatility expansion strategy"""
        
        # Extract profile_id for logging attribution (Requirement 7.1, 7.3)
        profile_id = profile.id if profile else "unknown"
        
        allow_longs = params.get("allow_longs", True)
        allow_shorts = params.get("allow_shorts", True)

        # Check if longs/shorts are allowed
        if not allow_longs and not allow_shorts:
            return None

        # Market conditions: Transitioning from low to normal/high volatility
        # We detect this by checking if we're currently in "normal" vol and ATR is expanding
        if profile.volatility not in ["normal", "high"]:
            log_info(f"VolExpansion: Rejecting - volatility not normal/high ({profile.volatility}) for {features.symbol}, profile_id={profile_id}")
            return None
        
        # Must be breaking out from inside or flat
        if profile.value_location not in ["inside", "above", "below"]:
            log_info(f"VolExpansion: Rejecting - value_location not inside/above/below ({profile.value_location}) for {features.symbol}, profile_id={profile_id}")
            return None
        
        # Check spread
        max_spread = params.get("max_spread", 0.003)
        if features.spread > max_spread:
            log_info(
                f"VolExpansion: Rejecting - spread too wide. "
                f"spread={features.spread:.6f}, max_spread={max_spread:.6f}, "
                f"symbol={features.symbol}, profile_id={profile_id}"
            )
            return None
        
        # Validate required features
        if not features.value_area_high or not features.value_area_low:
            log_info(f"VolExpansion: Rejecting - missing value area data for {features.symbol}, profile_id={profile_id}")
            return None
        if profile.value_location == "inside" and features.point_of_control is None:
            log_info(f"VolExpansion: Rejecting - missing POC for inside-value expansion on {features.symbol}, profile_id={profile_id}")
            return None
        
        # Check for volatility expansion
        # If ATR > baseline, we're in expansion
        # The key is to catch the BEGINNING of expansion, not late entry
        atr_ratio = features.atr_5m / features.atr_5m_baseline if features.atr_5m_baseline > 0 else 1.0
        expansion_threshold = params.get("expansion_threshold", 1.1)
        max_atr_ratio = params.get("max_atr_ratio", 2.0)
        
        # We want ATR to be expanding (above baseline) but not too far into the move
        if atr_ratio < expansion_threshold:
            rotation_str = f"{features.rotation_factor:.3f}" if features.rotation_factor else "N/A"
            log_info(
                f"VolExpansion: Rejecting - ATR ratio below expansion threshold. "
                f"atr_ratio={atr_ratio:.3f}, expansion_threshold={expansion_threshold:.3f}, "
                f"rotation={rotation_str}, "
                f"spread={features.spread:.6f}, symbol={features.symbol}, profile_id={profile_id}"
            )
            return None
        
        if atr_ratio > max_atr_ratio:
            rotation_str = f"{features.rotation_factor:.3f}" if features.rotation_factor else "N/A"
            log_info(
                f"VolExpansion: Rejecting - ATR ratio too high (expansion matured). "
                f"atr_ratio={atr_ratio:.3f}, max_atr_ratio={max_atr_ratio:.3f}, "
                f"rotation={rotation_str}, "
                f"spread={features.spread:.6f}, symbol={features.symbol}, profile_id={profile_id}"
            )
            return None
        
        # Check for breakout confirmation
        breakout_confirmation_pct = params.get("breakout_confirmation_pct", 0.0008)
        min_rotation_factor = params.get("min_rotation_factor", 4.0)

        signal_side = None
        entry_price = features.price
        stop_loss = 0.0
        take_profit = 0.0
        meta_reason = ""

        # Long signal: Expanding above VAH with strong rotation
        if allow_longs and \
           features.price > features.value_area_high * (1 + breakout_confirmation_pct) and \
           features.rotation_factor > min_rotation_factor:
            
            # Confirm with EMA alignment
            if features.ema_fast_15m > features.ema_slow_15m:
                signal_side = "long"
                stop_loss = features.price * (1 - params.get("stop_loss_pct", 0.012))  # 1.2% (was 0.8%)
                take_profit = features.price * (1 + params.get("take_profit_pct", 0.015))
                meta_reason = f"vol_expansion_long_vah_break_atr_{atr_ratio:.2f}x"
            else:
                log_info(
                    f"VolExpansion: Rejecting long - EMAs not aligned. "
                    f"ema_fast={features.ema_fast_15m:.2f}, ema_slow={features.ema_slow_15m:.2f}, "
                    f"atr_ratio={atr_ratio:.3f}, rotation={features.rotation_factor:.3f}, "
                    f"spread={features.spread:.6f}, symbol={features.symbol}, profile_id={profile_id}"
                )

        # Short signal: Expanding below VAL with strong rotation
        elif allow_shorts and \
             features.price < features.value_area_low * (1 - breakout_confirmation_pct) and \
             features.rotation_factor < -min_rotation_factor:
            
            # Confirm with EMA alignment
            if features.ema_fast_15m < features.ema_slow_15m:
                signal_side = "short"
                stop_loss = features.price * (1 + params.get("stop_loss_pct", 0.012))  # 1.2% (was 0.8%)
                take_profit = features.price * (1 - params.get("take_profit_pct", 0.015))
                meta_reason = f"vol_expansion_short_val_break_atr_{atr_ratio:.2f}x"
            else:
                log_info(
                    f"VolExpansion: Rejecting short - EMAs not aligned. "
                    f"ema_fast={features.ema_fast_15m:.2f}, ema_slow={features.ema_slow_15m:.2f}, "
                    f"atr_ratio={atr_ratio:.3f}, rotation={features.rotation_factor:.3f}, "
                    f"spread={features.spread:.6f}, symbol={features.symbol}, profile_id={profile_id}"
                )

        # Special case: Inside value area but showing signs of expansion
        # This catches early expansion before full breakout
        elif not signal_side and profile.value_location == "inside":
            
            # Long setup: Price near VAH, expanding with upward rotation
            if allow_longs and \
               features.price > features.point_of_control and \
               features.rotation_factor > min_rotation_factor and \
               features.ema_fast_15m > features.ema_slow_15m:
                
                signal_side = "long"
                stop_loss = features.value_area_low * (1 - params.get("stop_loss_pct", 0.012))  # 1.2%
                take_profit = features.price * (1 + params.get("take_profit_pct", 0.015))
                meta_reason = f"vol_expansion_long_early_atr_{atr_ratio:.2f}x"
            
            # Short setup: Price near VAL, expanding with downward rotation
            elif allow_shorts and \
                 features.price < features.point_of_control and \
                 features.rotation_factor < -min_rotation_factor and \
                 features.ema_fast_15m < features.ema_slow_15m:
                
                signal_side = "short"
                stop_loss = features.value_area_high * (1 + params.get("stop_loss_pct", 0.012))  # 1.2%
                take_profit = features.price * (1 - params.get("take_profit_pct", 0.015))
                meta_reason = f"vol_expansion_short_early_atr_{atr_ratio:.2f}x"
            
            else:
                # Log rejection for inside value area case
                rotation = features.rotation_factor if features.rotation_factor else 0.0
                log_info(
                    f"VolExpansion: Rejecting inside-value expansion - conditions not met. "
                    f"rotation={rotation:.3f}, min_rotation={min_rotation_factor:.3f}, "
                    f"atr_ratio={atr_ratio:.3f}, spread={features.spread:.6f}, "
                    f"symbol={features.symbol}, profile_id={profile_id}"
                )
        
        else:
            # Log rejection when no signal conditions matched
            rotation = features.rotation_factor if features.rotation_factor else 0.0
            price_vs_vah = features.price / features.value_area_high if features.value_area_high else 0
            price_vs_val = features.price / features.value_area_low if features.value_area_low else 0
            log_info(
                f"VolExpansion: Rejecting - no breakout conditions met. "
                f"rotation={rotation:.3f}, min_rotation={min_rotation_factor:.3f}, "
                f"price_vs_vah={price_vs_vah:.4f}, price_vs_val={price_vs_val:.4f}, "
                f"atr_ratio={atr_ratio:.3f}, spread={features.spread:.6f}, "
                f"symbol={features.symbol}, profile_id={profile_id}"
            )

        if signal_side:
            # Calculate position size
            risk_per_trade_pct = params.get("risk_per_trade_pct", 0.006)
            price_diff = abs(entry_price - stop_loss)
            
            if price_diff == 0:
                log_info(f"VolExpansion: Stop loss price is same as entry price for {features.symbol}, cannot calculate size.")
                return None
            
            # Position size based on risk percentage and stop distance
            position_value = account.equity * (risk_per_trade_pct / params.get("stop_loss_pct", 0.012))  # 1.2%
            size = position_value / entry_price
            
            if size <= 0:
                log_info(f"VolExpansion: Calculated size is zero or negative for {features.symbol}")
                return None

            log_info(f"VolExpansion: Generated {signal_side} signal for {features.symbol} @ {entry_price:.2f} "
                    f"with size {size:.4f}. ATR expansion: {atr_ratio:.2f}x baseline. "
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
