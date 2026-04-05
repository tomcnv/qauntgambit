"""Risk override store with TTL support."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Dict, Optional, Any, List

from quantgambit.storage.redis_snapshots import RedisSnapshotReader, RedisSnapshotWriter


@dataclass(frozen=True)
class RiskOverride:
    overrides: Dict[str, float]
    expires_at: float
    scope: Optional[Dict[str, str]] = None


class RiskOverrideStore:
    """In-memory risk override store with scope filtering."""

    def __init__(
        self,
        time_fn=time.time,
        snapshot_writer: Optional[RedisSnapshotWriter] = None,
        snapshot_reader: Optional[RedisSnapshotReader] = None,
        snapshot_key: Optional[str] = None,
    ):
        self._time_fn = time_fn
        self._overrides: list[RiskOverride] = []
        self._snapshot_writer = snapshot_writer
        self._snapshot_reader = snapshot_reader
        self._snapshot_key = snapshot_key

    async def apply_overrides(
        self,
        overrides: Dict[str, float],
        ttl_seconds: int,
        scope: Optional[Dict[str, str]] = None,
    ) -> bool:
        if ttl_seconds <= 0:
            return False
        expires_at = self._time_fn() + ttl_seconds
        self._overrides.append(RiskOverride(overrides=overrides, expires_at=expires_at, scope=scope))
        await self._persist()
        return True

    def get_overrides(
        self,
        bot_id: Optional[str] = None,
        symbol: Optional[str] = None,
        exchange: Optional[str] = None,
    ) -> Dict[str, float]:
        now = self._time_fn()
        active: list[RiskOverride] = []
        for entry in list(self._overrides):
            if entry.expires_at <= now:
                self._overrides.remove(entry)
                continue
            if not _scope_matches(entry.scope, bot_id, symbol, exchange):
                continue
            active.append(entry)
        merged: Dict[str, float] = {}
        for entry in active:
            merged.update(entry.overrides)
        return merged

    async def load(self) -> None:
        if not (self._snapshot_reader and self._snapshot_key):
            return
        data = await self._snapshot_reader.read(self._snapshot_key)
        if not data:
            return
        entries = data.get("entries") or []
        now = self._time_fn()
        for entry in entries:
            if entry.get("expires_at") and entry["expires_at"] <= now:
                continue
            self._overrides.append(
                RiskOverride(
                    overrides=entry.get("overrides") or {},
                    expires_at=entry.get("expires_at") or now,
                    scope=entry.get("scope"),
                )
            )

    async def _persist(self) -> None:
        if not (self._snapshot_writer and self._snapshot_key):
            return
        entries: List[Dict[str, Any]] = []
        now = self._time_fn()
        for entry in self._overrides:
            if entry.expires_at <= now:
                continue
            entries.append(
                {
                    "overrides": entry.overrides,
                    "expires_at": entry.expires_at,
                    "scope": entry.scope,
                }
            )
        await self._snapshot_writer.write(self._snapshot_key, {"entries": entries})

    async def prune_expired(self) -> Optional[dict]:
        now = self._time_fn()
        before = len(self._overrides)
        self._overrides = [entry for entry in self._overrides if entry.expires_at > now]
        dropped = before - len(self._overrides)
        await self._persist()
        if dropped:
            return {"dropped": dropped}
        return None


def _scope_matches(
    scope: Optional[Dict[str, str]],
    bot_id: Optional[str],
    symbol: Optional[str],
    exchange: Optional[str],
) -> bool:
    if not scope:
        return True
    scope_bot = scope.get("bot_id")
    scope_symbol = scope.get("symbol")
    scope_exchange = scope.get("exchange")
    if scope_bot and bot_id and scope_bot != bot_id:
        return False
    if scope_symbol and symbol and scope_symbol != symbol:
        return False
    if scope_exchange and exchange and scope_exchange != exchange:
        return False
    return True
