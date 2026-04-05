"""In-memory config repository to track applied versions."""

from __future__ import annotations

from typing import Dict, Optional

from quantgambit.config.models import BotConfig


class ConfigRepository:
    """Tracks the current applied config version in memory."""

    def __init__(self):
        self._configs: Dict[str, BotConfig] = {}

    def apply(self, config: BotConfig) -> None:
        key = f"{config.tenant_id}:{config.bot_id}"
        self._configs[key] = config

    def current_version(self, tenant_id: str, bot_id: str) -> Optional[int]:
        key = f"{tenant_id}:{bot_id}"
        cfg = self._configs.get(key)
        return cfg.version if cfg else None

    def current_config(self, tenant_id: str, bot_id: str) -> Optional[BotConfig]:
        key = f"{tenant_id}:{bot_id}"
        return self._configs.get(key)
