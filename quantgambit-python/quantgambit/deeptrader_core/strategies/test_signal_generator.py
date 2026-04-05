"""
Test Signal Generator Strategy

A minimal strategy that ALWAYS generates a signal when enabled.
Used exclusively for end-to-end testing of the trading pipeline.

WARNING: This strategy will generate trades regardless of market conditions.
Only use in test/paper trading environments.
"""

from typing import Optional, Dict, Any
from quantgambit.deeptrader_core.types import Features, AccountState, Profile, StrategySignal
from .base import Strategy


class TestSignalGenerator(Strategy):
    """
    Always generates a signal for testing purposes.
    
    This strategy bypasses all market condition checks and generates
    a small test signal to validate the full trading pipeline.
    
    Safety features:
    - Very small position sizes (0.05% risk)
    - Wide stops (2%) and targets (3%) for 1.5:1 R:R
    - Only works when explicitly enabled via test_mode param
    """
    
    strategy_id = "test_signal_generator"
    
    def generate_signal(
        self,
        features: Features,
        account: AccountState,
        profile: Profile,
        params: Dict[str, Any],
    ) -> Optional[StrategySignal]:
        """Generate a test signal regardless of market conditions."""
        
        # Safety check: must explicitly enable test mode
        if not params.get("test_mode_enabled", False):
            return None
        
        # Get basic parameters
        allow_longs = params.get("allow_longs", True)
        allow_shorts = params.get("allow_shorts", True)
        risk_per_trade_pct = params.get("risk_per_trade_pct", 0.05)  # 5% to meet OKX minimums
        stop_loss_pct = params.get("stop_loss_pct", 0.02)  # 2%
        take_profit_pct = params.get("take_profit_pct", 0.03)  # 3%
        
        # Must have valid price
        if not features.price or features.price <= 0:
            return None
        
        # Must have valid account equity
        if not account.equity or account.equity <= 0:
            return None
        
        # Determine direction based on orderflow imbalance (or default to long)
        if features.orderflow_imbalance is not None:
            side = "short" if features.orderflow_imbalance < -0.1 else "long"
        elif features.rotation_factor is not None:
            side = "short" if features.rotation_factor < 0 else "long"
        else:
            side = "long"
        
        # Check if side is allowed
        if side == "long" and not allow_longs:
            if allow_shorts:
                side = "short"
            else:
                return None
        elif side == "short" and not allow_shorts:
            if allow_longs:
                side = "long"
            else:
                return None
        
        # Calculate entry, stop, and target
        entry = features.price
        
        if side == "long":
            stop_loss = entry * (1 - stop_loss_pct)
            take_profit = entry * (1 + take_profit_pct)
        else:
            stop_loss = entry * (1 + stop_loss_pct)
            take_profit = entry * (1 - take_profit_pct)
        
        # Calculate position size
        stop_distance = abs(entry - stop_loss)
        if stop_distance <= 0:
            return None
        
        position_value = account.equity * risk_per_trade_pct
        size = position_value / stop_distance
        
        # Ensure minimum viable size
        if size <= 0:
            return None
        
        return StrategySignal(
            strategy_id=self.strategy_id,
            symbol=features.symbol,
            side=side,
            size=size,
            entry_price=entry,
            stop_loss=stop_loss,
            take_profit=take_profit,
            meta_reason=f"test_signal_{side}_orderflow_{features.orderflow_imbalance:.2f}" if features.orderflow_imbalance else f"test_signal_{side}",
            profile_id=profile.id,
        )
