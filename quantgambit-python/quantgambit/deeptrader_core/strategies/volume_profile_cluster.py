"""
Volume Profile Cluster Strategy

Trades price action near high-volume nodes (HVNs) which act as support/resistance.
Volume clusters represent areas of significant buyer/seller activity.

Entry Conditions:
- Price approaching HVN (high-volume node)
- Bounce from HVN support (long) or resistance (short)
- Strong rotation confirming bounce
- Volume-weighted S/R levels

Risk Management:
- Moderate stops (0.6%) placed beyond HVN
- Moderate targets (1.2%) to next HVN or VA boundary
- Moderate position sizing (1.2% risk)

Ideal Market Conditions:
- Normal to high volatility
- Clear HVN identification from volume profile
- Price action respecting volume levels
- Good liquidity

NOTE: Requires volume profile calculation in StateManager.
"""

from typing import Optional, Dict, Any
from quantgambit.deeptrader_core.types import Features, AccountState, Profile, StrategySignal
from .base import Strategy
from quantgambit.observability.logger import log_info


class VolumeProfileCluster(Strategy):
    strategy_id = "volume_profile_cluster"

    def generate_signal(
        self,
        features: Features,
        account: AccountState,
        profile: Profile,
        params: Dict[str, Any],
    ) -> Optional[StrategySignal]:
        """Generate signal for volume profile cluster bounce/break strategy"""
        
        # Check if longs/shorts are allowed
        if not params.get("allow_longs") and not params.get("allow_shorts"):
            return None

        # Market conditions: Normal to high volatility
        if profile.volatility not in ["normal", "high"]:
            return None
        
        # Validate required features
        hvn = features.point_of_control
        if not hvn:
            log_info(f"VolumeProfileCluster: Missing HVN data for {features.symbol}")
            return None
        
        # Check spread
        if features.spread > params.get("max_spread", 0.002):
            log_info(f"VolumeProfileCluster: Spread too wide ({features.spread:.4f}) for {features.symbol}")
            return None
        
        # Check proximity to HVN
        distance_to_hvn = abs(features.price - hvn) / features.price
        proximity_threshold = params.get("proximity_to_hvn_pct", 0.005)
        
        if distance_to_hvn > proximity_threshold:
            # Not close enough to HVN
            return None
        
        signal_side = None
        entry_price = features.price
        stop_loss = 0.0
        take_profit = 0.0
        meta_reason = ""

        rotation_threshold = params.get("rotation_threshold", 5.0)

        # Long signal: Price near HVN from below, bouncing up (HVN as support)
        if params.get("allow_longs") and features.price <= hvn:
            # Confirm strong upward rotation (bounce from support)
            if features.rotation_factor > rotation_threshold:
                signal_side = "long"
                # Stop below HVN
                stop_loss = hvn * (1 - params.get("stop_loss_pct", 0.012))  # 1.2% (was 0.6%)
                # Target VAH or next resistance
                if features.value_area_high:
                    take_profit = min(
                        features.price * (1 + params.get("take_profit_pct", 0.012)),
                        features.value_area_high
                    )
                else:
                    take_profit = features.price * (1 + params.get("take_profit_pct", 0.024))  # 2.4% (was 1.2%)
                
                meta_reason = f"volume_cluster_long_hvn_bounce_{distance_to_hvn:.4f}"

        # Short signal: Price near HVN from above, rejecting down (HVN as resistance)
        elif params.get("allow_shorts") and features.price >= hvn:
            # Confirm strong downward rotation (rejection from resistance)
            if features.rotation_factor < -rotation_threshold:
                signal_side = "short"
                # Stop above HVN
                stop_loss = hvn * (1 + params.get("stop_loss_pct", 0.012))  # 1.2% (was 0.6%)
                # Target VAL or next support
                if features.value_area_low:
                    take_profit = max(
                        features.price * (1 - params.get("take_profit_pct", 0.012)),
                        features.value_area_low
                    )
                else:
                    take_profit = features.price * (1 - params.get("take_profit_pct", 0.024))  # 2.4% (was 1.2%)
                
                meta_reason = f"volume_cluster_short_hvn_reject_{distance_to_hvn:.4f}"

        if signal_side:
            # Calculate position size
            risk_per_trade_pct = params.get("risk_per_trade_pct", 0.012)
            price_diff = abs(entry_price - stop_loss)
            
            if price_diff == 0:
                log_info(f"VolumeProfileCluster: Stop loss price is same as entry price for {features.symbol}, cannot calculate size.")
                return None
            
            # Position size based on risk percentage and stop distance
            position_value = account.equity * (risk_per_trade_pct / params.get("stop_loss_pct", 0.012))
            size = position_value / entry_price
            
            if size <= 0:
                log_info(f"VolumeProfileCluster: Calculated size is zero or negative for {features.symbol}")
                return None

            log_info(f"VolumeProfileCluster: Generated {signal_side} signal for {features.symbol} @ {entry_price:.2f} "
                    f"with size {size:.4f}. HVN: {hvn:.2f}, Distance: {distance_to_hvn:.4f}. "
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
