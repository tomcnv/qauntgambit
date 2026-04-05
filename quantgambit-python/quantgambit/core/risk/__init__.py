"""
Risk management for QuantGambit.

This package provides:
- KillSwitch: Emergency trading halt with latch behavior
- Risk controls and guards
"""

from quantgambit.core.risk.kill_switch import (
    KillSwitch,
    KillSwitchConfig,
    KillSwitchTrigger,
    KillSwitchState,
)

__all__ = [
    "KillSwitch",
    "KillSwitchConfig",
    "KillSwitchTrigger",
    "KillSwitchState",
]
