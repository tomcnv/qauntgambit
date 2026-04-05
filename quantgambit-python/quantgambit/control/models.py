"""Control plane request/response models."""

from __future__ import annotations

from pydantic import BaseModel, Field
from typing import Dict, Optional


class ControlScope(BaseModel):
    symbol: Optional[str] = None
    exchange: Optional[str] = None
    bot_id: Optional[str] = None


class ControlRequest(BaseModel):
    bot_id: str
    scope: Optional[ControlScope] = None
    reason: Optional[str] = None
    requested_by: str
    confirm_token: Optional[str] = None


class FailoverArmRequest(BaseModel):
    bot_id: str
    symbol: str
    primary_exchange: str
    secondary_exchange: str
    requested_by: str


class FailoverExecRequest(BaseModel):
    bot_id: str
    symbol: str
    requested_by: str
    confirm_token: str


class RiskOverrideRequest(BaseModel):
    bot_id: str
    scope: Optional[ControlScope] = None
    overrides: Dict[str, float]
    ttl_seconds: int = Field(gt=0)
    requested_by: str
    confirm_token: str


class ControlResponse(BaseModel):
    command_id: str
    status: str
    message: str


class ControlStateResponse(BaseModel):
    trading_paused: bool
    pause_reason: Optional[str] = None
    failover_state: Optional[str] = None
    primary_exchange: Optional[str] = None
    secondary_exchange: Optional[str] = None
    timestamp: Optional[str] = None


class CommandHistoryEntry(BaseModel):
    command_id: Optional[str] = None
    status: Optional[str] = None
    message: Optional[str] = None
    executed_at: Optional[str] = None


class CommandHistoryResponse(BaseModel):
    items: list[CommandHistoryEntry]
