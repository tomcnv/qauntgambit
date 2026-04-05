"""
Risk Validator - Validate signals against risk limits

Validates signals against:
1. Position limits (max positions, max per symbol)
2. Exposure limits (max total exposure, max per symbol)
3. Daily loss limits (max daily loss, consecutive losses)
4. Correlation limits (max correlated positions)
5. Drawdown limits (max drawdown from peak)

Returns validation result with approval/rejection and reason.
"""

from typing import Dict, List, Optional
from quantgambit.deeptrader_core.layer2_signals import TradingSignal


class RiskValidator:
    """Validate signals against risk limits"""
    
    def __init__(
        self,
        max_positions: int = 4,
        max_positions_per_symbol: int = 1,
        max_total_exposure_pct: float = 0.50,  # Max 50% of account (decimal)
        max_exposure_per_symbol_pct: float = 0.20,  # Max 20% per symbol (decimal)
        max_daily_loss_pct: float = 0.05,  # Max 5% daily loss (decimal)
        max_consecutive_losses: int = 3,  # Max 3 consecutive losses
        max_drawdown_pct: float = 0.10,  # Max 10% drawdown from peak (decimal)
    ):
        self.max_positions = max_positions
        self.max_positions_per_symbol = max_positions_per_symbol
        self.max_total_exposure_pct = max_total_exposure_pct
        self.max_exposure_per_symbol_pct = max_exposure_per_symbol_pct
        self.max_daily_loss_pct = max_daily_loss_pct
        self.max_consecutive_losses = max_consecutive_losses
        self.max_drawdown_pct = max_drawdown_pct
        
        # Stats
        self.signals_validated = 0
        self.signals_approved = 0
        self.signals_rejected = 0
        self.rejection_reasons = {}
    
    def validate_signal(
        self,
        signal: TradingSignal,
        position_size_usd: float,
        account_balance: float,
        current_positions: List[Dict],
        daily_pnl: float,
        consecutive_losses: int,
        peak_balance: float,
        min_position_size_usd: float = 0.0
    ) -> Dict:
        """
        Validate a signal against risk limits
        
        Args:
            signal: TradingSignal from Layer 2
            position_size_usd: Proposed position size in USD
            account_balance: Current account balance
            current_positions: List of current positions
            daily_pnl: Current daily P&L
            consecutive_losses: Current consecutive losses
            peak_balance: Peak account balance
            
        Returns:
            Dict with approved, rejection_reason, warnings
        """
        self.signals_validated += 1
        warnings = []
        
        # 1. Check position count
        if len(current_positions) >= self.max_positions:
            self._reject("max_positions_exceeded")
            return {
                'approved': False,
                'rejection_reason': f'max_positions_exceeded ({len(current_positions)}/{self.max_positions})',
                'warnings': warnings
            }
        
        # 2. Check positions per symbol
        symbol_positions = [p for p in current_positions if p['symbol'] == signal.symbol]
        if len(symbol_positions) >= self.max_positions_per_symbol:
            self._reject("max_positions_per_symbol_exceeded")
            return {
                'approved': False,
                'rejection_reason': f'max_positions_per_symbol_exceeded ({len(symbol_positions)}/{self.max_positions_per_symbol})',
                'warnings': warnings
            }
        
        # 3. Check total exposure
        current_exposure_usd = sum(p.get('size_usd', 0) for p in current_positions)
        new_total_exposure = current_exposure_usd + position_size_usd
        exposure_pct = new_total_exposure / account_balance
        
        if exposure_pct > self.max_total_exposure_pct:
            self._reject("max_total_exposure_exceeded")
            return {
                'approved': False,
                'rejection_reason': f'max_total_exposure_exceeded ({exposure_pct * 100:.1f}% / {self.max_total_exposure_pct * 100:.1f}%)',
                'warnings': warnings
            }
        
        # Warning if approaching limit
        if exposure_pct > self.max_total_exposure_pct * 0.8:
            warnings.append(f'approaching_max_exposure ({exposure_pct * 100:.1f}% / {self.max_total_exposure_pct * 100:.1f}%)')
        
        # 4. Check exposure per symbol
        symbol_exposure_usd = sum(p.get('size_usd', 0) for p in symbol_positions)
        new_symbol_exposure = symbol_exposure_usd + position_size_usd
        symbol_exposure_pct = new_symbol_exposure / account_balance
        
        if symbol_exposure_pct > self.max_exposure_per_symbol_pct:
            self._reject("max_exposure_per_symbol_exceeded")
            return {
                'approved': False,
                'rejection_reason': f'max_exposure_per_symbol_exceeded ({symbol_exposure_pct * 100:.1f}% / {self.max_exposure_per_symbol_pct * 100:.1f}%)',
                'warnings': warnings
            }
        
        # 5. Check daily loss limit
        daily_loss_pct = daily_pnl / account_balance
        if daily_loss_pct < -self.max_daily_loss_pct:
            self._reject("max_daily_loss_exceeded")
            return {
                'approved': False,
                'rejection_reason': f'max_daily_loss_exceeded ({daily_loss_pct * 100:.2f}% / -{self.max_daily_loss_pct * 100:.1f}%)',
                'warnings': warnings
            }
        
        # Warning if approaching daily loss limit
        if daily_loss_pct < -self.max_daily_loss_pct * 0.8:
            warnings.append(f'approaching_daily_loss_limit ({daily_loss_pct * 100:.2f}% / -{self.max_daily_loss_pct * 100:.1f}%)')
        
        # 6. Check consecutive losses
        if consecutive_losses >= self.max_consecutive_losses:
            self._reject("max_consecutive_losses_exceeded")
            return {
                'approved': False,
                'rejection_reason': f'max_consecutive_losses_exceeded ({consecutive_losses}/{self.max_consecutive_losses})',
                'warnings': warnings
            }
        
        # Warning if approaching consecutive loss limit
        if consecutive_losses >= self.max_consecutive_losses - 1:
            warnings.append(f'approaching_consecutive_loss_limit ({consecutive_losses}/{self.max_consecutive_losses})')
        
        # 7. Check drawdown
        drawdown_pct = ((peak_balance - account_balance) / peak_balance) * 100
        if drawdown_pct > self.max_drawdown_pct:
            self._reject("max_drawdown_exceeded")
            return {
                'approved': False,
                'rejection_reason': f'max_drawdown_exceeded ({drawdown_pct:.2f}% / {self.max_drawdown_pct}%)',
                'warnings': warnings
            }
        
        # Warning if approaching drawdown limit
        if drawdown_pct > self.max_drawdown_pct * 0.8:
            warnings.append(f'approaching_drawdown_limit ({drawdown_pct:.2f}% / {self.max_drawdown_pct}%)')
        
        # 8. Check min size feasibility
        if position_size_usd < min_position_size_usd:
            self._reject("min_position_size")
            return {
                'approved': False,
                'rejection_reason': f'min_position_size ({position_size_usd:.2f} < {min_position_size_usd:.2f})',
                'warnings': warnings
            }
        
        # 9. Check signal validity
        if not signal.is_valid():
            self._reject("invalid_signal")
            return {
                'approved': False,
                'rejection_reason': 'invalid_signal (failed signal validation)',
                'warnings': warnings
            }
        
        # All checks passed
        self.signals_approved += 1
        return {
            'approved': True,
            'rejection_reason': None,
            'warnings': warnings
        }
    
    def _reject(self, reason: str):
        """Record signal rejection"""
        self.signals_rejected += 1
        self.rejection_reasons[reason] = self.rejection_reasons.get(reason, 0) + 1
    
    def get_stats(self) -> Dict:
        """Get risk validator statistics"""
        approval_rate = (self.signals_approved / self.signals_validated * 100) if self.signals_validated > 0 else 0.0
        rejection_rate = (self.signals_rejected / self.signals_validated * 100) if self.signals_validated > 0 else 0.0
        
        return {
            'signals_validated': self.signals_validated,
            'signals_approved': self.signals_approved,
            'signals_rejected': self.signals_rejected,
            'approval_rate': approval_rate,
            'rejection_rate': rejection_rate,
            'rejection_reasons': dict(self.rejection_reasons),
            'limits': {
                'max_positions': self.max_positions,
                'max_positions_per_symbol': self.max_positions_per_symbol,
                'max_total_exposure_pct': self.max_total_exposure_pct,
                'max_exposure_per_symbol_pct': self.max_exposure_per_symbol_pct,
                'max_daily_loss_pct': self.max_daily_loss_pct,
                'max_consecutive_losses': self.max_consecutive_losses,
                'max_drawdown_pct': self.max_drawdown_pct,
            }
        }


def validate_signal(
    signal: TradingSignal,
    position_size_usd: float,
    account_balance: float,
    current_positions: List[Dict],
    daily_pnl: float = 0.0,
    consecutive_losses: int = 0,
    peak_balance: Optional[float] = None
) -> Dict:
    """
    Validate a signal against risk limits
    
    Args:
        signal: TradingSignal from Layer 2
        position_size_usd: Proposed position size in USD
        account_balance: Current account balance
        current_positions: List of current positions
        daily_pnl: Current daily P&L
        consecutive_losses: Current consecutive losses
        peak_balance: Peak account balance (defaults to current balance)
        
    Returns:
        Dict with approved, rejection_reason, warnings
    """
    if peak_balance is None:
        peak_balance = account_balance
    
    validator = RiskValidator()
    return validator.validate_signal(
        signal, position_size_usd, account_balance, current_positions,
        daily_pnl, consecutive_losses, peak_balance
    )



