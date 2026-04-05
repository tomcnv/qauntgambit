"""
Liquidity Hunt Strategy

Detects institutional stop hunts (rapid wicks beyond value area) and fades the reversal.
Exploits the classic pattern: spike to trigger stops → immediate reversal.

Entry Conditions:
- Recent wick beyond VAH/VAL (within last 60 seconds)
- Quick reversal back into value area
- Strong rotation in reversal direction
- Volume spike confirmation
- Tight spread for execution

Risk Management:
- Very tight stops (0.4%) - hunt failed = exit immediately
- Quick targets (0.8%) - capture the bounce/fade
- Moderate position sizing (1.5% risk)
- Fast execution required

Ideal Market Conditions:
- High volatility periods (stop hunts are more common)
- Near value area boundaries
- High liquidity (US/Europe sessions)
- Clear direction after hunt
"""

from typing import Optional, Dict, Any
import time
from quantgambit.deeptrader_core.types import Features, AccountState, Profile, StrategySignal
from .base import Strategy
from quantgambit.observability.logger import log_info


class LiquidityHunt(Strategy):
    strategy_id = "liquidity_hunt"

    def generate_signal(
        self,
        features: Features,
        account: AccountState,
        profile: Profile,
        params: Dict[str, Any],
    ) -> Optional[StrategySignal]:
        """Generate signal for liquidity hunt fade strategy"""
        
        allow_longs = params.get("allow_longs", True)
        allow_shorts = params.get("allow_shorts", True)

        # Check if longs/shorts are allowed
        if not allow_longs and not allow_shorts:
            return None

        # Market conditions: High volatility preferred for stop hunts
        if profile.volatility not in ["normal", "high"]:
            return None
        
        # Check spread - must be tight for fast execution
        if features.spread > params.get("max_spread", 0.002):
            log_info(f"LiquidityHunt: Spread too wide ({features.spread:.4f}) for {features.symbol}")
            return None
        
        # Validate required features
        if not features.value_area_high or not features.value_area_low:
            log_info(f"LiquidityHunt: Missing value area data for {features.symbol}")
            return None
        
        # NOTE: In production, we'd track recent highs/lows and detect wicks
        # For now, we'll use a simplified approach:
        # If price was recently outside VA but is now back inside with strong rotation,
        # we assume a hunt occurred
        
        signal_side = None
        entry_price = features.price
        stop_loss = 0.0
        take_profit = 0.0
        meta_reason = ""

        min_wick_size_pct = params.get("min_wick_size_pct", 0.003)
        min_rotation_factor = params.get("min_rotation_factor", 8.0)

        # Long signal: Price above VAH but rotating down (hunt up, fade down)
        # Or price recently below VAL, now back inside rotating up (hunt down, fade up)
        if allow_longs:
            # Detect downward hunt that bounced (price near VAL, strong rotation up)
            if features.position_in_value in ["inside", "below"]:
                distance_to_val = abs(features.price - features.value_area_low) / features.price
                
                # If very close to VAL and strong upward rotation, likely bounced from hunt
                if distance_to_val < min_wick_size_pct * 2 and \
                   features.rotation_factor > min_rotation_factor:
                    signal_side = "long"
                    stop_loss = features.value_area_low * (1 - params.get("stop_loss_pct", 0.012))  # 1.2% (was 0.4%)
                    take_profit = features.price * (1 + params.get("take_profit_pct", 0.02))  # 2.0% (was 0.8%)
                    meta_reason = "liquidity_hunt_long_val_bounce"

        # Short signal: Price below VAL but rotating up (hunt down, fade up)
        # Or price recently above VAH, now back inside rotating down (hunt up, fade down)
        if allow_shorts:
            # Detect upward hunt that bounced (price near VAH, strong rotation down)
            if features.position_in_value in ["inside", "above"]:
                distance_to_vah = abs(features.price - features.value_area_high) / features.price
                
                # If very close to VAH and strong downward rotation, likely bounced from hunt
                if distance_to_vah < min_wick_size_pct * 2 and \
                   features.rotation_factor < -min_rotation_factor:
                    signal_side = "short"
                    stop_loss = features.value_area_high * (1 + params.get("stop_loss_pct", 0.012))  # 1.2% (was 0.4%)
                    take_profit = features.price * (1 - params.get("take_profit_pct", 0.02))  # 2.0% (was 0.8%)
                    meta_reason = "liquidity_hunt_short_vah_bounce"

        if signal_side:
            # Calculate position size
            risk_per_trade_pct = params.get("risk_per_trade_pct", 0.015)
            price_diff = abs(entry_price - stop_loss)
            
            if price_diff == 0:
                log_info(f"LiquidityHunt: Stop loss price is same as entry price for {features.symbol}, cannot calculate size.")
                return None
            
            # Position size based on risk percentage and stop distance
            position_value = account.equity * (risk_per_trade_pct / params.get("stop_loss_pct", 0.012))
            size = position_value / entry_price
            
            if size <= 0:
                log_info(f"LiquidityHunt: Calculated size is zero or negative for {features.symbol}")
                return None

            log_info(f"LiquidityHunt: Generated {signal_side} signal for {features.symbol} @ {entry_price:.2f} "
                    f"with size {size:.4f}. Rotation: {features.rotation_factor:.1f}. "
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
