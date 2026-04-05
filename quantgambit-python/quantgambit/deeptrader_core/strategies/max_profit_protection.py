"""
Max Profit Protection Strategy

Conservative trading mode that activates after profits to protect gains.

Key Features:
- Activates when daily_pnl is positive (above threshold)
- Reduces position sizes by 30%
- Takes profits faster (tighter TP levels)
- Only trades highest-quality setups
- Avoids risky late-session trades
- Focus on preserving accumulated gains

Philosophy:
"When you're winning, protect your gains. Don't give profits back to the market."
"""

from typing import Optional
from quantgambit.deeptrader_core.types import Features, AccountState, Profile, StrategySignal
from quantgambit.deeptrader_core.strategies.base import Strategy


class MaxProfitProtection(Strategy):
    """
    Conservative protection strategy for profit preservation.
    
    Trades only when:
    - Account is in profit (daily_pnl > profit_threshold)
    - High-quality setup (clear trend + rotation alignment)
    - Reduces risk per trade by 30%
    - Uses faster profit-taking (1.5:1 reward:risk)
    - Avoids risky setups
    """
    
    def generate_signal(
        self, 
        features: Features, 
        account: AccountState, 
        profile: Profile, 
        params: dict
    ) -> Optional[StrategySignal]:
        """
        Generate conservative protection signals when in profit.
        
        Args:
            features: Current market features
            account: Account state (must be in profit)
            profile: Market profile
            params: Strategy parameters
                - allow_longs (bool): Allow long positions
                - allow_shorts (bool): Allow short positions
                - profit_threshold_pct (float): % of max_daily_loss to activate (default 0.5)
                - min_poc_distance_pct (float): Min % away from POC for entry
                - rotation_threshold (float): Min rotation factor
                - min_trend_strength (float): Min EMA spread for trend confirmation
                - stop_loss_pct (float): Stop loss %
                - take_profit_pct (float): Take profit % (faster than normal)
                - risk_per_trade_pct (float): Risk per trade % (will be reduced 30%)
                - max_spread (float): Max allowed spread
        
        Returns:
            StrategySignal if conditions met, None otherwise
        """
        # Extract parameters with defaults
        allow_longs = params.get("allow_longs", True)
        allow_shorts = params.get("allow_shorts", True)
        profit_threshold_pct = params.get("profit_threshold_pct", 0.5)
        min_poc_distance = params.get("min_poc_distance_pct", 0.005)
        rotation_threshold = params.get("rotation_threshold", 7.0)
        min_trend_strength = params.get("min_trend_strength", 0.003)
        stop_loss_pct = params.get("stop_loss_pct", 0.012)  # 1.2% (was 0.6%)
        take_profit_pct = params.get("take_profit_pct", 0.018)  # 1.8% - 1.5:1 R:R
        risk_per_trade_pct = params.get("risk_per_trade_pct", 0.01)
        max_spread = params.get("max_spread", 0.002)
        
        # 1. Check if we're in profit protection mode
        if account.max_daily_loss >= 0:
            # No loss limit set, use absolute profit threshold
            if account.daily_pnl <= 0:
                return None
        else:
            # Use relative threshold (e.g., 50% of max_daily_loss)
            profit_threshold = abs(account.max_daily_loss) * profit_threshold_pct
            if account.daily_pnl < profit_threshold:
                # Not enough profit to protect
                return None
        
        # 2. Spread check
        if features.spread > max_spread:
            return None
        
        # 3. Check for missing data
        if features.ema_fast_15m is None or features.ema_slow_15m is None:
            return None
        if features.point_of_control is None:
            return None
        
        # 4. Only trade with clear trend (not flat)
        if profile.trend == "flat":
            return None
        
        # 5. Check trend strength via EMA spread
        ema_spread_pct = abs(features.ema_fast_15m - features.ema_slow_15m) / features.price
        if ema_spread_pct < min_trend_strength:
            return None
        
        # 6. Check rotation alignment with trend
        if abs(features.rotation_factor) < rotation_threshold:
            return None
        
        # 7. Only trade when inside or at value area (safer entries)
        # Avoid chasing breakouts when protecting profits
        if profile.value_location not in ["inside", "at_val", "at_vah"]:
            return None
        
        # 8. Check distance from POC (want some separation for profit potential)
        distance_from_poc = abs(features.price - features.point_of_control) / features.price
        if distance_from_poc < min_poc_distance:
            return None
        
        # 9. Determine trade direction based on trend and rotation
        if profile.trend == "up":
            # Uptrend - only long if rotation positive
            if features.rotation_factor <= 0:
                return None
            if not allow_longs:
                return None
            side = "long"
            entry_price = features.price
            stop_loss_price = entry_price * (1 - stop_loss_pct)
            take_profit_price = entry_price * (1 + take_profit_pct)
        
        else:  # down
            # Downtrend - only short if rotation negative
            if features.rotation_factor >= 0:
                return None
            if not allow_shorts:
                return None
            side = "short"
            entry_price = features.price
            stop_loss_price = entry_price * (1 + stop_loss_pct)
            take_profit_price = entry_price * (1 - take_profit_pct)
        
        # 10. Position sizing - REDUCED for protection mode (70% of normal)
        protection_risk_pct = risk_per_trade_pct * 0.7  # 30% reduction
        position_size = (account.equity * protection_risk_pct) / entry_price
        
        return StrategySignal(
            strategy_id="max_profit_protection",
            profile_id=profile.id,
            symbol=features.symbol,
            side=side,
            size=position_size,
            entry_price=entry_price,
            stop_loss=stop_loss_price,
            take_profit=take_profit_price,
            meta_reason=(
                f"PROFIT PROTECTION: Daily PnL ${account.daily_pnl:.2f} (positive). "
                f"Conservative {side} with {profile.trend} trend, "
                f"rotation {features.rotation_factor:.1f}. "
                f"Risk reduced 30% to {protection_risk_pct:.1f}%, "
                f"faster TP for profit preservation"
            )
        )
