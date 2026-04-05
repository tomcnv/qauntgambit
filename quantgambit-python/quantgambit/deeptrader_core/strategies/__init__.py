"""Strategy System - Pluggable trading strategies

Provides:
- Base Strategy ABC
- Strategy implementations
- Strategy registry
"""

from .base import Strategy
from .amt_value_area_rejection_scalp import AmtValueAreaRejectionScalp

__all__ = ['Strategy', 'AmtValueAreaRejectionScalp']

