"""Redis snapshot writer for UI panels."""

from __future__ import annotations

import json
from typing import Any, Dict, Optional


class RedisSnapshotWriter:
    """Write snapshot keys with TTL for UI consumption."""

    def __init__(self, redis, ttl_seconds: int = 120):
        self.redis = redis
        self.ttl_seconds = ttl_seconds

    async def write(self, key: str, payload: Dict[str, Any]) -> None:
        await self.redis.set(key, json.dumps(payload))
        await self.redis.expire(key, self.ttl_seconds)

    async def append_history(self, key: str, payload: Dict[str, Any], max_items: int = 100) -> None:
        serialized = json.dumps(payload)
        await self.redis.lpush(key, serialized)
        await self.redis.ltrim(key, 0, max_items - 1)
        await self.redis.expire(key, self.ttl_seconds)


class RedisSnapshotReader:
    """Read snapshot keys and history lists for UI consumption."""

    def __init__(self, redis):
        self.redis = redis

    async def read(self, key: str) -> Optional[Dict[str, Any]]:
        raw = await self.redis.get(key)
        if not raw:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        return json.loads(raw)

    async def read_history(self, key: str, limit: int = 100) -> list[Dict[str, Any]]:
        raw_items = await self.redis.lrange(key, 0, max(limit - 1, 0))
        items: list[Dict[str, Any]] = []
        for raw in raw_items or []:
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            try:
                items.append(json.loads(raw))
            except json.JSONDecodeError:
                continue
        return items
