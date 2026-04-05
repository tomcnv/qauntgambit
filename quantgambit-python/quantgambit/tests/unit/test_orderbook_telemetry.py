import asyncio
import json

from quantgambit.signals.feature_worker import FeaturePredictionWorker, FeatureWorkerConfig
from quantgambit.storage.redis_streams import RedisStreamsClient, Event


class FakeRedis:
    async def get(self, key):
        return None

    async def xadd(self, stream, data):
        return "1-0"

    async def xgroup_create(self, stream, group, id="0", mkstream=True):
        return None

    async def xreadgroup(self, group, consumer, streams, count=10, block=1000):
        return []

    async def xack(self, stream, group, message_id):
        return 1


class FakeTelemetry:
    def __init__(self):
        self.orderbook_payloads = []

    async def publish_orderbook(self, ctx, payload):
        self.orderbook_payloads.append(payload)


def test_feature_worker_emits_orderbook_telemetry():
    redis_client = RedisStreamsClient(FakeRedis())
    telemetry = FakeTelemetry()
    worker = FeaturePredictionWorker(
        redis_client=redis_client,
        bot_id="b1",
        exchange="okx",
        config=FeatureWorkerConfig(orderbook_emit_min_ticks=1, orderbook_emit_interval_ms=0),
        telemetry=telemetry,
        telemetry_context=object(),
    )
    tick_event = Event(
        event_id="1",
        event_type="market_tick",
        schema_version="v1",
        timestamp="100",
        ts_recv_us=100000000,
        ts_canon_us=100000000,
        ts_exchange_s=None,
        bot_id="b1",
        payload={
            "symbol": "BTC",
            "timestamp": 100,
            "bid": 99.0,
            "ask": 101.0,
            "bids": [[99, 1]],
            "asks": [[101, 1]],
        },
    )
    payload = {"data": json.dumps(tick_event.__dict__)}

    async def run_once():
        await worker._handle_message(payload)
        await worker._flush_orderbook_tasks()

    asyncio.run(run_once())
    assert telemetry.orderbook_payloads
