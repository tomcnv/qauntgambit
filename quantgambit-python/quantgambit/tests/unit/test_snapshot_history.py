import asyncio

from quantgambit.storage.redis_snapshots import RedisSnapshotWriter


class FakeRedis:
    def __init__(self):
        self.list = []
        self.expiry = None

    async def set(self, key, value):
        return True

    async def expire(self, key, ttl):
        self.expiry = ttl
        return True

    async def lpush(self, key, value):
        self.list.insert(0, value)
        return len(self.list)

    async def ltrim(self, key, start, end):
        self.list = self.list[start : end + 1]
        return True


def test_append_history():
    redis = FakeRedis()
    writer = RedisSnapshotWriter(redis, ttl_seconds=10)

    asyncio.run(writer.append_history("history:key", {"a": 1}, max_items=2))
    asyncio.run(writer.append_history("history:key", {"b": 2}, max_items=2))
    asyncio.run(writer.append_history("history:key", {"c": 3}, max_items=2))

    assert len(redis.list) == 2
    assert redis.expiry == 10

