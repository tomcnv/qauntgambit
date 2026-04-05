"""Config safety guards."""

from __future__ import annotations

from typing import Optional

from quantgambit.config.watcher import ConfigApplier
from quantgambit.observability.logger import log_warning


class SafeConfigApplier(ConfigApplier):
    """Apply config only when runtime is safe."""

    def __init__(self, runtime_state, position_manager, repository, delegate):
        self.runtime_state = runtime_state
        self.position_manager = position_manager
        self.repository = repository
        self.delegate = delegate
        self._pending: list = []

    async def apply(self, config):
        if not getattr(self.runtime_state, "trading_paused", False):
            log_warning("config_apply_blocked", reason="trading_active")
            self._pending.append(config)
            return False
        positions = await self.position_manager.list_open_positions()
        if positions:
            log_warning("config_apply_blocked", reason="open_positions")
            self._pending.append(config)
            return False
        await self.delegate.apply(config)
        self.repository.apply(config)
        log_warning("config_apply_allowed", version=config.version)
        return True

    async def flush_if_safe(self) -> None:
        if not self._pending:
            return
        if not getattr(self.runtime_state, "trading_paused", False):
            return
        positions = await self.position_manager.list_open_positions()
        if positions:
            return
        pending = list(self._pending)
        self._pending.clear()
        for config in pending:
            await self.delegate.apply(config)
            self.repository.apply(config)
            log_warning("config_apply_pending", version=config.version)
