"""Config watcher consuming Redis config update events."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from quantgambit.config.models import BotConfig
from quantgambit.storage.redis_streams import RedisStreamsClient, decode_and_validate_event


@dataclass
class ConfigApplier:
    """Apply config updates safely in the runtime."""

    async def apply(self, config: BotConfig) -> bool:  # pragma: no cover - interface
        raise NotImplementedError


class ConfigWatcher:
    """Watches config updates and applies them to the running bot."""

    def __init__(
        self,
        redis_client: RedisStreamsClient,
        applier: ConfigApplier,
        stream: str = "events:config",
        consumer_group: str = "quantgambit_config",
        consumer_name: str = "config_watcher",
    ):
        self.redis = redis_client
        self.applier = applier
        self.stream = stream
        self.consumer_group = consumer_group
        self.consumer_name = consumer_name
        self._last_version: dict[tuple[str, str], int] = {}

    async def start(self) -> None:
        await self.redis.create_group(self.stream, self.consumer_group)
        while True:
            messages = await self.redis.read_group(
                self.consumer_group,
                self.consumer_name,
                {self.stream: ">"},
            )
            for stream_name, entries in messages:
                for message_id, payload in entries:
                    await self._handle_message(payload)
                    await self.redis.ack(stream_name, self.consumer_group, message_id)

    async def _handle_message(self, payload: dict) -> None:
        event = decode_and_validate_event(payload)
        raw_config = (event.get("payload") or {}).get("config")
        if not raw_config:
            return
        config = BotConfig.model_validate(raw_config)
        key = (config.tenant_id, config.bot_id)
        last_version = self._last_version.get(key, 0)
        if config.version <= last_version:
            return
        applied = await self.applier.apply(config)
        if applied:
            self._last_version[key] = config.version
