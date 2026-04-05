"""Failover state machine with guarded transitions."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class FailoverState(str, Enum):
    PRIMARY_ACTIVE = "PRIMARY_ACTIVE"
    PRIMARY_DEGRADED = "PRIMARY_DEGRADED"
    FAILOVER_ARMED = "FAILOVER_ARMED"
    SECONDARY_ACTIVE = "SECONDARY_ACTIVE"
    RECOVERY_PENDING = "RECOVERY_PENDING"
    HALTED = "HALTED"


@dataclass
class FailoverContext:
    state: FailoverState = FailoverState.PRIMARY_ACTIVE
    primary_exchange: Optional[str] = None
    secondary_exchange: Optional[str] = None


class FailoverStateMachine:
    """Simple state machine for manual failover control."""

    def __init__(self, context: Optional[FailoverContext] = None):
        self.context = context or FailoverContext()

    def apply(self, command_type: str) -> FailoverState:
        state = self.context.state

        if command_type == "HALT":
            self.context.state = FailoverState.HALTED
            return self.context.state

        if state == FailoverState.HALTED:
            return state

        if command_type == "FAILOVER_ARM" and state == FailoverState.PRIMARY_ACTIVE:
            self.context.state = FailoverState.FAILOVER_ARMED
        elif command_type == "FAILOVER_EXEC" and state == FailoverState.FAILOVER_ARMED:
            self.context.state = FailoverState.SECONDARY_ACTIVE
        elif command_type == "RECOVER_ARM" and state == FailoverState.SECONDARY_ACTIVE:
            self.context.state = FailoverState.RECOVERY_PENDING
        elif command_type == "RECOVER_EXEC" and state == FailoverState.RECOVERY_PENDING:
            self.context.state = FailoverState.PRIMARY_ACTIVE

        return self.context.state

