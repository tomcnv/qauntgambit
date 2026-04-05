"""Configuration models and versioning."""

from __future__ import annotations

from pydantic import BaseModel, Field
from typing import Dict, Optional, Any


class BotConfig(BaseModel):
    tenant_id: str
    bot_id: str
    version: int = Field(ge=1)
    trading_mode: str = "paper"  # paper | live
    market_type: str = "perp"  # perp | spot
    margin_mode: str = "isolated"  # isolated | cross
    active_exchange: str
    symbols: list[str]
    risk: Dict[str, float] = {}
    execution: Dict[str, float] = {}
    strategy: Dict[str, float] = {}
    profile_settings: Dict[str, Any] = Field(default_factory=dict)
    trading_hours: Dict[str, int] = Field(
        default_factory=lambda: {"start_hour_utc": 0, "end_hour_utc": 24}
    )
    order_intent_max_age_sec: Optional[float] = None


class ConfigUpdateRequest(BaseModel):
    tenant_id: str
    bot_id: str
    requested_by: str
    config: BotConfig
    reason: Optional[str] = None


class ConfigResponse(BaseModel):
    tenant_id: str
    bot_id: str
    version: int
    status: str
    message: str


class ConfigVersionDetail(BaseModel):
    tenant_id: str
    bot_id: str
    version: int
    created_at: Optional[str] = None
    config: BotConfig


class ConfigHistoryResponse(BaseModel):
    tenant_id: str
    bot_id: str
    versions: list[ConfigVersionDetail]


class ConfigRollbackRequest(BaseModel):
    tenant_id: str
    bot_id: str
    target_version: int
    requested_by: str
    reason: Optional[str] = None
