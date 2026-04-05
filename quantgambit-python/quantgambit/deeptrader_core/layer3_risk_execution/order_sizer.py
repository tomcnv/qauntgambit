"""
Order Sizer - Calculate position sizes

Uses multiple methods:
1. Kelly Criterion - Optimal position sizing based on edge
2. Portfolio Heat - Limit total exposure
3. Volatility Adjustment - Scale size based on volatility
4. Liquidity Adjustment - Scale size based on orderbook depth

Returns position size in units and USD.
"""

from typing import Dict, Optional
from quantgambit.deeptrader_core.layer2_signals import TradingSignal
from quantgambit.deeptrader_core.layer1_predictions import MarketContext


class OrderSizer:
    """Calculate position sizes with multiple methods"""
    
    def __init__(
        self,
        account_balance: float = 10000.0,
        max_position_pct: float = 0.10,  # Max 10% of account per position
        max_portfolio_heat: float = 40.0,  # Max 40% total exposure (increased from 30%)
        kelly_fraction: float = 0.25,  # Use 25% of Kelly (conservative)
        min_position_usd: float = 500.0,  # Minimum position size (increased to meet exchange minimums)
        max_position_usd: float = 5000.0,  # Maximum position size
    ):
        self.account_balance = account_balance
        self.max_position_pct = max_position_pct
        self.max_portfolio_heat = max_portfolio_heat
        self.kelly_fraction = kelly_fraction
        self.min_position_usd = min_position_usd
        self.max_position_usd = max_position_usd
        
        # Stats
        self.positions_sized = 0
        self.total_size_usd = 0.0
        self.sizing_methods_used = {}
    
    def calculate_position_size(
        self,
        signal: TradingSignal,
        context: MarketContext,
        current_exposure_usd: float = 0.0,
        win_rate: Optional[float] = None,
        avg_win_loss_ratio: Optional[float] = None
    ) -> Dict:
        """
        Calculate position size for a signal
        
        Args:
            signal: TradingSignal from Layer 2
            context: MarketContext from Layer 1
            current_exposure_usd: Current total exposure in USD
            win_rate: Historical win rate (0.0-1.0)
            avg_win_loss_ratio: Average win/loss ratio
            
        Returns:
            Dict with position_size_units, position_size_usd, method, adjustments
        """
        # 1. Base size from Kelly Criterion (if we have historical data)
        if win_rate is not None and avg_win_loss_ratio is not None:
            kelly_size_usd = self._kelly_criterion(
                signal, win_rate, avg_win_loss_ratio
            )
            method = "kelly"
        else:
            # Fallback to fixed percentage
            kelly_size_usd = self.account_balance * self.max_position_pct
            method = "fixed_pct"
        
        # 2. Adjust for signal strength
        strength_multiplier = self._get_strength_multiplier(signal)
        adjusted_size_usd = kelly_size_usd * strength_multiplier
        
        # 3. Adjust for volatility
        volatility_multiplier = self._get_volatility_multiplier(context)
        adjusted_size_usd *= volatility_multiplier
        
        # 4. Adjust for liquidity
        liquidity_multiplier = self._get_liquidity_multiplier(context)
        adjusted_size_usd *= liquidity_multiplier
        
        # 5. Check portfolio heat
        portfolio_heat_pct = (current_exposure_usd / self.account_balance) * 100
        remaining_heat = self.max_portfolio_heat - portfolio_heat_pct
        
        if remaining_heat <= 0:
            # Portfolio is too hot, reject
            return {
                'position_size_units': 0.0,
                'position_size_usd': 0.0,
                'method': method,
                'rejected': True,
                'rejection_reason': f'portfolio_heat_exceeded ({portfolio_heat_pct:.1f}% / {self.max_portfolio_heat}%)',
                'adjustments': {}
            }
        
        # Limit to remaining heat
        max_size_from_heat = (remaining_heat / 100.0) * self.account_balance
        adjusted_size_usd = min(adjusted_size_usd, max_size_from_heat)
        
        # 6. Apply min/max limits
        adjusted_size_usd = max(self.min_position_usd, min(self.max_position_usd, adjusted_size_usd))
        
        # 7. Convert to units
        position_size_units = adjusted_size_usd / signal.entry_price
        
        # Update stats
        self.positions_sized += 1
        self.total_size_usd += adjusted_size_usd
        self.sizing_methods_used[method] = self.sizing_methods_used.get(method, 0) + 1
        
        return {
            'position_size_units': position_size_units,
            'position_size_usd': adjusted_size_usd,
            'method': method,
            'rejected': False,
            'adjustments': {
                'kelly_size_usd': kelly_size_usd,
                'strength_multiplier': strength_multiplier,
                'volatility_multiplier': volatility_multiplier,
                'liquidity_multiplier': liquidity_multiplier,
                'portfolio_heat_pct': portfolio_heat_pct,
                'remaining_heat_pct': remaining_heat,
            }
        }
    
    def _kelly_criterion(
        self,
        signal: TradingSignal,
        win_rate: float,
        avg_win_loss_ratio: float
    ) -> float:
        """
        Calculate Kelly Criterion position size
        
        Kelly % = W - (1 - W) / R
        Where:
        - W = win rate (probability of winning)
        - R = average win/loss ratio
        
        Args:
            signal: TradingSignal
            win_rate: Historical win rate (0.0-1.0)
            avg_win_loss_ratio: Average win/loss ratio
            
        Returns:
            Position size in USD
        """
        # Kelly formula
        kelly_pct = win_rate - ((1 - win_rate) / avg_win_loss_ratio)
        
        # Clamp to reasonable range (0-50%)
        kelly_pct = max(0.0, min(0.5, kelly_pct))
        
        # Apply Kelly fraction (conservative)
        fractional_kelly_pct = kelly_pct * self.kelly_fraction
        
        # Convert to USD
        kelly_size_usd = self.account_balance * fractional_kelly_pct
        
        return kelly_size_usd
    
    def _get_strength_multiplier(self, signal: TradingSignal) -> float:
        """Get position size multiplier based on signal strength"""
        from quantgambit.deeptrader_core.layer2_signals import SignalStrength
        
        if signal.signal_strength == SignalStrength.STRONG:
            return 1.3  # Increase size by 30%
        elif signal.signal_strength == SignalStrength.MODERATE:
            return 1.0  # Normal size
        else:  # WEAK
            return 0.7  # Reduce size by 30%
    
    def _get_volatility_multiplier(self, context: MarketContext) -> float:
        """Get position size multiplier based on volatility"""
        if context.volatility_regime == "high":
            return 0.7  # Reduce size by 30% in high volatility
        elif context.volatility_regime == "low":
            return 1.2  # Increase size by 20% in low volatility
        else:
            return 1.0  # Normal size
    
    def _get_liquidity_multiplier(self, context: MarketContext) -> float:
        """Get position size multiplier based on liquidity"""
        if context.liquidity_regime == "thin":
            return 0.5  # Reduce size by 50% in thin liquidity
        elif context.liquidity_regime == "deep":
            return 1.1  # Increase size by 10% in deep liquidity
        else:
            return 1.0  # Normal size
    
    def update_account_balance(self, new_balance: float):
        """Update account balance"""
        self.account_balance = new_balance
    
    def get_stats(self) -> Dict:
        """Get order sizer statistics"""
        avg_size_usd = self.total_size_usd / self.positions_sized if self.positions_sized > 0 else 0.0
        
        return {
            'positions_sized': self.positions_sized,
            'total_size_usd': self.total_size_usd,
            'avg_size_usd': avg_size_usd,
            'sizing_methods_used': dict(self.sizing_methods_used),
            'account_balance': self.account_balance,
            'max_position_pct': self.max_position_pct,
            'max_portfolio_heat': self.max_portfolio_heat,
        }


def calculate_position_size(
    signal: TradingSignal,
    context: MarketContext,
    account_balance: float,
    current_exposure_usd: float = 0.0,
    win_rate: Optional[float] = None,
    avg_win_loss_ratio: Optional[float] = None
) -> Dict:
    """
    Calculate position size for a signal
    
    Args:
        signal: TradingSignal from Layer 2
        context: MarketContext from Layer 1
        account_balance: Current account balance
        current_exposure_usd: Current total exposure in USD
        win_rate: Historical win rate (0.0-1.0)
        avg_win_loss_ratio: Average win/loss ratio
        
    Returns:
        Dict with position_size_units, position_size_usd, method, adjustments
    """
    sizer = OrderSizer(account_balance=account_balance)
    return sizer.calculate_position_size(
        signal, context, current_exposure_usd, win_rate, avg_win_loss_ratio
    )

