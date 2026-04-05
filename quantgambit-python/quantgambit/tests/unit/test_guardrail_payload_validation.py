import asyncio

from quantgambit.observability.telemetry import TelemetryPipeline, TelemetryContext


class FakeRedis:
    def __init__(self):
        self.events = []

    async def xadd(self, stream, data):
        self.events.append((stream, data))
        return "1-0"


class FakeRedisClient:
    def __init__(self, redis):
        self.redis = redis

    async def publish_event(self, stream, event):
        await self.redis.xadd(stream, {"data": "payload"})


def test_guardrail_payload_validation_drops_invalid():
    telemetry = TelemetryPipeline(redis_client=FakeRedisClient(FakeRedis()))
    ctx = TelemetryContext(tenant_id="t1", bot_id="b1", exchange="okx")

    async def run_once():
        await telemetry.publish_guardrail(ctx, {"symbol": "BTC"})

    asyncio.run(run_once())
    assert telemetry.redis.redis.events == []


def test_guardrail_payload_validation_accepts_minimal():
    telemetry = TelemetryPipeline(redis_client=FakeRedisClient(FakeRedis()))
    ctx = TelemetryContext(tenant_id="t1", bot_id="b1", exchange="okx")

    async def run_once():
        await telemetry.publish_guardrail(ctx, {"type": "ws_stale", "symbol": "BTC"})

    asyncio.run(run_once())
    assert len(telemetry.redis.redis.events) == 1
