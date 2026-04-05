import asyncio

from quantgambit.risk.overrides import RiskOverrideStore
from quantgambit.storage.redis_snapshots import RedisSnapshotWriter, RedisSnapshotReader


class FakeRedis:
    def __init__(self):
        self.kv = {}
        self.expiry = {}

    async def set(self, key, value):
        self.kv[key] = value
        return True

    async def get(self, key):
        return self.kv.get(key)

    async def expire(self, key, ttl):
        self.expiry[key] = ttl
        return True

    async def lpush(self, key, value):
        return 1

    async def ltrim(self, key, start, end):
        return True


def test_risk_overrides_persist_and_load():
    redis = FakeRedis()
    writer = RedisSnapshotWriter(redis, ttl_seconds=60)
    reader = RedisSnapshotReader(redis)
    store = RiskOverrideStore(snapshot_writer=writer, snapshot_reader=reader, snapshot_key="risk:overrides")

    async def apply():
        await store.apply_overrides({"max_positions": 1}, ttl_seconds=60, scope={"bot_id": "b1"})

    asyncio.run(apply())

    store2 = RiskOverrideStore(snapshot_reader=reader, snapshot_key="risk:overrides")

    async def load():
        await store2.load()

    asyncio.run(load())
    overrides = store2.get_overrides(bot_id="b1")
    assert overrides["max_positions"] == 1
