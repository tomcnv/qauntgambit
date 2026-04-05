"""Idempotency store for execution intents."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Callable, Awaitable, Dict, Any
import time
from datetime import datetime, timezone, timedelta

from quantgambit.storage.postgres import PostgresIdempotencyStore, IdempotencyAuditRecord


@dataclass(frozen=True)
class IdempotencyConfig:
    ttl_sec: int = 300
    namespace: str = "quantgambit"


class RedisIdempotencyStore:
    """Redis-backed idempotency store with TTL."""

    def __init__(
        self,
        redis,
        bot_id: str,
        tenant_id: Optional[str] = None,
        config: Optional[IdempotencyConfig] = None,
        audit_store: Optional[PostgresIdempotencyStore] = None,
        alert_hook: Optional[Callable[[str, str, Optional[Dict[str, Any]]], Awaitable[None]]] = None,
    ):
        self.redis = redis
        self.bot_id = bot_id
        self.tenant_id = tenant_id
        self.config = config or IdempotencyConfig()
        self.audit_store = audit_store
        self.alert_hook = alert_hook

    async def claim(self, client_order_id: Optional[str]) -> bool:
        if not client_order_id:
            return True
        if self.config.ttl_sec <= 0:
            return True
        if self.audit_store and self.tenant_id:
            try:
                if await self.audit_store.is_claimed(self.tenant_id, self.bot_id, client_order_id):
                    await self._audit(client_order_id, False)
                    return False
            except Exception:
                pass
        key = self._dedupe_key(client_order_id)
        try:
            result = await self.redis.set(key, "1", nx=True, ex=self.config.ttl_sec)
        except Exception as exc:
            await self._audit(client_order_id, False, reason=f"redis_unavailable:{exc}")
            if self.alert_hook:
                await self.alert_hook(
                    "idempotency_store_unavailable",
                    "Redis idempotency store unavailable; failing closed.",
                    {
                        "tenant_id": self.tenant_id,
                        "bot_id": self.bot_id,
                        "client_order_id": client_order_id,
                        "error": str(exc),
                    },
                )
            return False
        claimed = bool(result)
        await self._audit(client_order_id, claimed)
        return claimed

    async def _audit(self, client_order_id: str, claimed: bool, reason: Optional[str] = None) -> None:
        if not (self.audit_store and self.tenant_id):
            return
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        expires = time.strftime(
            "%Y-%m-%dT%H:%M:%SZ",
            time.gmtime(time.time() + self.config.ttl_sec),
        )
        status = "claimed" if claimed else "duplicate"
        await self.audit_store.write_audit(
            IdempotencyAuditRecord(
                tenant_id=self.tenant_id,
                bot_id=self.bot_id,
                client_order_id=client_order_id,
                status=status,
                created_at=now,
                expires_at=expires,
                reason=reason,
            )
        )

    def _dedupe_key(self, client_order_id: str) -> str:
        if self.tenant_id:
            return f"{self.config.namespace}:{self.tenant_id}:{self.bot_id}:execution:dedupe:{client_order_id}"
        return f"{self.config.namespace}:{self.bot_id}:execution:dedupe:{client_order_id}"

    async def replay_recent_claims(self, hours: float, limit: int = 500) -> int:
        if not (self.audit_store and self.tenant_id):
            return 0
        since = None
        if hours and hours > 0:
            since = datetime.now(timezone.utc) - timedelta(hours=hours)
        rows = await self.audit_store.load_recent_claims(self.tenant_id, self.bot_id, since, limit)
        replayed = 0
        now = datetime.now(timezone.utc)
        for row in rows:
            if (row.get("status") or "") != "claimed":
                continue
            client_order_id = row.get("client_order_id")
            if not client_order_id:
                continue
            expires_at = _parse_datetime(row.get("expires_at"))
            if not expires_at or expires_at <= now:
                continue
            ttl = max(1, int((expires_at - now).total_seconds()))
            key = self._dedupe_key(client_order_id)
            await self.redis.set(key, "1", ex=ttl)
            replayed += 1
        return replayed


def _parse_datetime(value: Optional[object]) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
