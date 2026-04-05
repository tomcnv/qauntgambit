"""Runtime state for control-plane actions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Awaitable, Callable, Optional

from quantgambit.control.failover import FailoverStateMachine


@dataclass
class ControlRuntimeState:
    trading_paused: bool = False
    pause_reason: Optional[str] = None
    execution_ready: bool = False
    execution_block_reason: Optional[str] = None
    execution_last_checked_at: Optional[float] = None
    trading_disabled: bool = False
    kill_switch_active: bool = False
    config_drift_active: bool = False
    exchange_credentials_configured: bool = False
    execution_readiness_probe: Optional[Callable[[], Awaitable[None]]] = None
    failover_state: FailoverStateMachine = FailoverStateMachine()
