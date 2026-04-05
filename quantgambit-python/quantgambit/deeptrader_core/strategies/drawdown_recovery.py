"""
Drawdown Recovery Strategy

Conservative trading mode that activates after losses to rebuild capital safely.

Key Features:
- Activates when daily_pnl indicates moderate drawdown
- Reduces position sizes by 50%
- Only trades highest-probability setups (strong rotation + value rejection)
- Tighter stops, wider profit targets (2:1 minimum reward:risk)
- Avoids aggressive/risky setups
- Focus on mean reversion and value area rejection trades

Philosophy:
"After a loss, focus on small wins and capital preservation, not revenge trading"
"""

from typing import Optional
from quantgambit.deeptrader_core.types import Features, AccountState, Profile, StrategySignal
from quantgambit.deeptrader_core.strategies.base import Strategy


class DrawdownRecovery(Strategy):
    """
    Conservative recovery strategy for drawdown periods.
    
    Trades only when:
    - Account is in drawdown mode (daily_pnl < -30% of max_daily_loss)
    - Strong value area rejection (above VAH or below VAL)
    - Strong rotation confirming direction
    - Reduces risk per trade by 50%
    - Uses 2:1 reward:risk minimum
    """
    
    def generate_signal(
        self, 
        features: Features, 
        account: AccountState, 
        profile: Profile, 
        params: dict
    ) -> Optional[StrategySignal]:
        """
        Generate conservative recovery signals during drawdown.
        
        Args:
            features: Current market features
            account: Account state (must be in drawdown)
            profile: Market profile
            params: Strategy parameters
                - allow_longs (bool): Allow long positions
                - allow_shorts (bool): Allow short positions
                - drawdown_threshold_pct (float): % of max_daily_loss to activate (default 0.3)
                - min_distance_from_val_vah_pct (float): Min % away from VAL/VAH
                - rotation_threshold (float): Min rotation factor
                - stop_loss_pct (float): Stop loss %
                - take_profit_pct (float): Take profit % (should be >= 2x stop_loss_pct)
                - risk_per_trade_pct (float): Risk per trade % (will be halved)
                - max_spread (float): Max allowed spread
        
        Returns:
            StrategySignal if conditions met, None otherwise
        """
        # Extract parameters with defaults
        allow_longs = params.get("allow_longs", True)
        allow_shorts = params.get("allow_shorts", True)
        drawdown_threshold_pct = params.get("drawdown_threshold_pct", 0.3)
        min_distance_from_val_vah = params.get("min_distance_from_val_vah_pct", 0.01)
        rotation_threshold = params.get("rotation_threshold", 8.0)
        stop_loss_pct = params.get("stop_loss_pct", 0.012)  # 1.2% (was 0.5%)
        take_profit_pct = params.get("take_profit_pct", 0.024)  # 2.4% - maintaining 2:1 R:R
        risk_per_trade_pct = params.get("risk_per_trade_pct", 0.01)
        max_spread = params.get("max_spread", 0.002)
        
        # 1. Check if we're in drawdown mode
        if account.max_daily_loss >= 0:
            # No loss limit set, can't determine drawdown
            return None
        
        drawdown_threshold = account.max_daily_loss * drawdown_threshold_pct
        if account.daily_pnl >= drawdown_threshold:
            # Not in significant drawdown
            return None
        
        # 2. Spread check
        if features.spread > max_spread:
            return None
        
        # 3. Check for missing data
        if features.value_area_high is None or features.value_area_low is None:
            return None
        
        # 4. Only trade strong rejections from value area boundaries
        # Price must be outside value area (above VAH or below VAL)
        if profile.value_location != "above" and profile.value_location != "below":
            return None
        
        # Calculate distance from value boundaries
        if profile.value_location == "above":
            # Price above VAH - look for short (rejection down)
            distance_from_boundary = (features.price - features.value_area_high) / features.price
        else:  # below
            # Price below VAL - look for long (rejection up)
            distance_from_boundary = (features.value_area_low - features.price) / features.price
        
        if distance_from_boundary < min_distance_from_val_vah:
            return None
        
        # 5. Check rotation - must be STRONG in direction of mean reversion
        if abs(features.rotation_factor) < rotation_threshold:
            return None
        
        # 6. Determine trade direction based on value location and rotation
        if profile.value_location == "above":
            # Above VAH - short if rotation is negative (selling pressure)
            if features.rotation_factor >= 0:
                return None
            if not allow_shorts:
                return None
            side = "short"
            entry_price = features.price
            stop_loss_price = entry_price * (1 + stop_loss_pct)
            take_profit_price = entry_price * (1 - take_profit_pct)
        
        else:  # below
            # Below VAL - long if rotation is positive (buying pressure)
            if features.rotation_factor <= 0:
                return None
            if not allow_longs:
                return None
            side = "long"
            entry_price = features.price
            stop_loss_price = entry_price * (1 - stop_loss_pct)
            take_profit_price = entry_price * (1 + take_profit_pct)
        
        # 7. Position sizing - HALVED for recovery mode
        recovery_risk_pct = risk_per_trade_pct * 0.5  # 50% of normal risk
        position_size = (account.equity * recovery_risk_pct) / entry_price
        
        return StrategySignal(
            strategy_id="drawdown_recovery",
            profile_id=profile.id,
            symbol=features.symbol,
            side=side,
            size=position_size,
            entry_price=entry_price,
            stop_loss=stop_loss_price,
            take_profit=take_profit_price,
            meta_reason=(
                f"RECOVERY MODE: Daily PnL ${account.daily_pnl:.2f} "
                f"(threshold ${drawdown_threshold:.2f}). "
                f"Conservative {side} from {profile.value_location} value area "
                f"with strong rotation {features.rotation_factor:.1f}. "
                f"Risk reduced 50% to {recovery_risk_pct:.1f}%"
            )
        )
