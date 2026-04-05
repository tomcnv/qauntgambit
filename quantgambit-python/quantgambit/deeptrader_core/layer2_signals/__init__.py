"""
Layer 2: Signals (Trade Opportunities)

Generates trading signals from MarketContext with confirmations, cooldowns, and invalidations.

Components:
- TradingSignal: Unified signal dataclass
- SignalEngine: Main signal generation engine
- SignalConfirmation: Multi-factor confirmation logic
- SignalCooldown: Prevents over-trading
- SignalInvalidation: Detects when signals become invalid
"""

from .trading_signal import TradingSignal, SignalType, SignalStrength
from .signal_engine import SignalEngine, generate_signals
from .signal_confirmation import SignalConfirmation, confirm_signal
from .signal_cooldown import SignalCooldown
from .signal_invalidation import SignalInvalidation, check_invalidation

__all__ = [
    'TradingSignal',
    'SignalType',
    'SignalStrength',
    'SignalEngine',
    'generate_signals',
    'SignalConfirmation',
    'confirm_signal',
    'SignalCooldown',
    'SignalInvalidation',
    'check_invalidation',
]























