"""Postgres-backed config store with versioning."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from quantgambit.config.models import BotConfig


@dataclass(frozen=True)
class ConfigRecord:
    tenant_id: str
    bot_id: str
    version: int
    config: BotConfig
    created_at: Optional[str] = None


class ConfigStore:
    """Persist and fetch bot configurations."""

    def __init__(self, pool):
        self.pool = pool

    async def get_latest(self, tenant_id: str, bot_id: str) -> Optional[ConfigRecord]:
        query = (
            "SELECT tenant_id, bot_id, version, config, created_at "
            "FROM bot_configs "
            "WHERE tenant_id=$1 AND bot_id=$2 "
            "ORDER BY version DESC LIMIT 1"
        )
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(query, tenant_id, bot_id)
        if not row:
            return None
        config = BotConfig.model_validate(row["config"])
        return ConfigRecord(
            tenant_id=row["tenant_id"],
            bot_id=row["bot_id"],
            version=row["version"],
            config=config,
            created_at=_coerce_ts(row.get("created_at")),
        )

    async def get_version(self, tenant_id: str, bot_id: str, version: int) -> Optional[ConfigRecord]:
        query = (
            "SELECT tenant_id, bot_id, version, config, created_at "
            "FROM bot_configs "
            "WHERE tenant_id=$1 AND bot_id=$2 AND version=$3"
        )
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(query, tenant_id, bot_id, version)
        if not row:
            return None
        config = BotConfig.model_validate(row["config"])
        return ConfigRecord(
            tenant_id=row["tenant_id"],
            bot_id=row["bot_id"],
            version=row["version"],
            config=config,
            created_at=_coerce_ts(row.get("created_at")),
        )

    async def list_versions(
        self,
        tenant_id: str,
        bot_id: str,
        limit: int = 50,
    ) -> list[ConfigRecord]:
        query = (
            "SELECT tenant_id, bot_id, version, config, created_at "
            "FROM bot_configs "
            "WHERE tenant_id=$1 AND bot_id=$2 "
            "ORDER BY version DESC LIMIT $3"
        )
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(query, tenant_id, bot_id, limit)
        records: list[ConfigRecord] = []
        for row in rows:
            config = BotConfig.model_validate(row["config"])
            records.append(
                ConfigRecord(
                    tenant_id=row["tenant_id"],
                    bot_id=row["bot_id"],
                    version=row["version"],
                    config=config,
                    created_at=_coerce_ts(row.get("created_at")),
                )
            )
        return records

    async def upsert(self, config: BotConfig) -> ConfigRecord:
        query = (
            "INSERT INTO bot_configs (tenant_id, bot_id, version, config) "
            "VALUES ($1, $2, $3, $4)"
        )
        async with self.pool.acquire() as conn:
            await conn.execute(
                query,
                config.tenant_id,
                config.bot_id,
                config.version,
                config.model_dump(mode="json"),
            )
        return ConfigRecord(
            tenant_id=config.tenant_id,
            bot_id=config.bot_id,
            version=config.version,
            config=config,
            created_at=None,
        )


def _coerce_ts(value) -> Optional[str]:
    if value is None:
        return None
    return str(value)
