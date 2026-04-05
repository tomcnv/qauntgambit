import asyncio

from quantgambit.observability.telemetry import TelemetryContext, TelemetryPipeline
from quantgambit.storage.redis_streams import RedisStreamsClient
from quantgambit.storage.redis_snapshots import RedisSnapshotWriter


class FakeRedis:
    def __init__(self):
        self.events = []
        self.kv = {}

    async def xadd(self, stream, data):
        self.events.append((stream, data))
        return "1-0"

    async def set(self, key, value):
        self.kv[key] = value
        return True

    async def expire(self, key, ttl):
        return True


def test_publish_decision_to_redis():
    redis = FakeRedis()
    pipeline = TelemetryPipeline(redis_client=RedisStreamsClient(redis))
    ctx = TelemetryContext(tenant_id="t1", bot_id="b1", exchange="okx")

    asyncio.run(pipeline.publish_decision(ctx, "BTC", {"result": "CONTINUE"}))

    assert len(redis.events) == 1
    assert redis.events[0][0] == "events:decision"


def test_publish_health_snapshot():
    redis = FakeRedis()
    pipeline = TelemetryPipeline(snapshot_writer=RedisSnapshotWriter(redis))
    ctx = TelemetryContext(tenant_id="t1", bot_id="b1", exchange="okx")

    async def run_once():
        await pipeline.publish_health_snapshot(ctx, {"status": "auth_failed"})

    asyncio.run(run_once())
    key = "quantgambit:t1:b1:health:latest"
    assert key in redis.kv
