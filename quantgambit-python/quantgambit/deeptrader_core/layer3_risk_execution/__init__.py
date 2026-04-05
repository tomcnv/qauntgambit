"""
Layer 3: Risk/Execution

Handles order sizing, risk validation, order execution, and position management.

Components:
- OrderSizer: Calculate position sizes (Kelly Criterion, portfolio heat)
- RiskValidator: Validate signals against risk limits
- OrderExecutor: Execute orders (market/limit)
- PositionManager: Manage positions (stop loss, take profit, trailing stops)
- ExecutionMonitor: Monitor execution quality (slippage, fill rate)
"""

from .order_sizer import OrderSizer, calculate_position_size
from .risk_validator import RiskValidator, validate_signal
from .order_executor import OrderExecutor, ExecutionResult
from .position_manager import PositionManager, Position
from .execution_monitor import ExecutionMonitor

__all__ = [
    'OrderSizer',
    'calculate_position_size',
    'RiskValidator',
    'validate_signal',
    'OrderExecutor',
    'ExecutionResult',
    'PositionManager',
    'Position',
    'ExecutionMonitor',
]























