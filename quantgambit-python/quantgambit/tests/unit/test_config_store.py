import asyncio
from types import SimpleNamespace

from quantgambit.config.models import BotConfig
from quantgambit.config.store import ConfigStore


class FakeConn:
    def __init__(self):
        self.rows = []

    async def fetchrow(self, query, *args):
        tenant_id = args[0] if len(args) > 0 else None
        bot_id = args[1] if len(args) > 1 else None
        version = args[2] if len(args) > 2 else None
        for row in sorted(self.rows, key=lambda r: r["version"], reverse=True):
            if row["tenant_id"] != tenant_id or row["bot_id"] != bot_id:
                continue
            if version is not None and row["version"] != version:
                continue
            return row
        return None

    async def fetch(self, query, tenant_id, bot_id, limit):
        rows = [
            row
            for row in sorted(self.rows, key=lambda r: r["version"], reverse=True)
            if row["tenant_id"] == tenant_id and row["bot_id"] == bot_id
        ]
        return rows[:limit]

    async def execute(self, query, tenant_id, bot_id, version, config):
        self.rows.append({
            "tenant_id": tenant_id,
            "bot_id": bot_id,
            "version": version,
            "config": config,
            "created_at": "2024-01-01T00:00:00Z",
        })


class AcquireContext:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, exc_type, exc, tb):
        return False


class FakePool:
    def __init__(self):
        self.conn = FakeConn()

    def acquire(self):
        return AcquireContext(self.conn)


async def _write_and_read(store):
    config = BotConfig(
        tenant_id="tenant1",
        bot_id="bot1",
        version=1,
        active_exchange="okx",
        symbols=["BTC"],
    )
    await store.upsert(config)
    record = await store.get_latest("tenant1", "bot1")
    return record


def test_config_store_round_trip():
    pool = FakePool()
    store = ConfigStore(pool)
    record = asyncio.run(_write_and_read(store))
    assert record is not None
    assert record.config.bot_id == "bot1"


def test_config_store_version_lookup_and_history():
    pool = FakePool()
    store = ConfigStore(pool)
    config_v1 = BotConfig(
        tenant_id="tenant1",
        bot_id="bot1",
        version=1,
        active_exchange="okx",
        symbols=["BTC"],
    )
    config_v2 = BotConfig(
        tenant_id="tenant1",
        bot_id="bot1",
        version=2,
        active_exchange="okx",
        symbols=["BTC", "ETH"],
    )
    asyncio.run(store.upsert(config_v1))
    asyncio.run(store.upsert(config_v2))
    record = asyncio.run(store.get_version("tenant1", "bot1", 1))
    assert record is not None
    assert record.version == 1
    history = asyncio.run(store.list_versions("tenant1", "bot1", limit=10))
    assert [item.version for item in history] == [2, 1]
