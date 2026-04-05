import asyncio

from quantgambit.ingest.orderbook_worker import OrderbookWorker, OrderbookWorkerConfig
from quantgambit.market.reference_prices import ReferencePriceCache
from quantgambit.observability.telemetry import TelemetryContext, TelemetryPipeline
from quantgambit.storage.redis_streams import RedisStreamsClient


class FakeTelemetry:
    def __init__(self):
        self.guardrails = []

    async def publish_guardrail(self, ctx, payload):
        self.guardrails.append(payload)


class FakeRedis:
    async def xgroup_create(self, stream, group, id="0", mkstream=True):
        return None

    async def xreadgroup(self, group, consumer, streams, count=10, block=1000):
        return []

    async def xack(self, stream, group, message_id):
        return 1

    async def xadd(self, stream, data):
        return "1-0"


def test_orderbook_worker_guardrail_on_gap():
    redis = RedisStreamsClient(FakeRedis())
    cache = ReferencePriceCache()
    telemetry = FakeTelemetry()
    ctx = TelemetryContext(tenant_id="t1", bot_id="b1", exchange="okx")
    worker = OrderbookWorker(
        redis_client=redis,
        cache=cache,
        telemetry=telemetry,
        telemetry_context=ctx,
        config=OrderbookWorkerConfig(
            resync_min_interval_sec=0.0,
            allow_delta_bootstrap=False,  # Disable bootstrap so gaps trigger guardrails
        ),
    )
    snapshot = {"symbol": "BTC", "seq": 1, "bids": [[1, 1]], "asks": [[2, 1]], "timestamp": 1}
    delta_gap = {"symbol": "BTC", "seq": 3, "bids": [[1, 0]], "asks": [[2, 1]], "timestamp": 2}
    asyncio.run(worker._apply_snapshot(snapshot))
    asyncio.run(worker._apply_delta(delta_gap))
    assert telemetry.guardrails
    guard = telemetry.guardrails[0]
    assert guard["type"] == "order_resync"
    assert guard["reason"] == "gap_detected"
