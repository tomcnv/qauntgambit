import asyncio

from quantgambit.ingest.orderbook_worker import OrderbookWorker, OrderbookWorkerConfig
from quantgambit.market.quality import MarketDataQualityTracker
from quantgambit.market.reference_prices import ReferencePriceCache
from quantgambit.signals.feature_worker import FeaturePredictionWorker
from quantgambit.storage.redis_streams import RedisStreamsClient, Event, decode_and_validate_event


class FakeRedis:
    def __init__(self):
        self.streams = {}
        self.kv = {}

    async def xadd(self, stream, data):
        self.streams.setdefault(stream, []).append(data)
        return "1-0"

    async def xgroup_create(self, stream, group, id="0", mkstream=True):
        self.streams.setdefault(stream, [])

    async def xreadgroup(self, group, consumer, streams, count=10, block=1000):
        results = []
        for stream in streams:
            entries = []
            if self.streams.get(stream):
                data = self.streams[stream].pop(0)
                entries.append(("1-0", data))
            if entries:
                results.append((stream, entries))
        return results

    async def xack(self, stream, group, message_id):
        return 1

    async def get(self, key):
        return self.kv.get(key)

    async def set(self, key, value):
        self.kv[key] = value
        return True


def test_orderbook_gap_emits_resync_and_blocks_prediction():
    redis = FakeRedis()
    client = RedisStreamsClient(redis)
    quality = MarketDataQualityTracker()
    cache = ReferencePriceCache()
    orderbook_worker = OrderbookWorker(
        redis_client=client,
        cache=cache,
        quality_tracker=quality,
        config=OrderbookWorkerConfig(
            resync_min_interval_sec=0.0,
            allow_delta_bootstrap=False,  # Disable bootstrap so gaps trigger resync
        ),
    )
    feature_worker = FeaturePredictionWorker(
        redis_client=client,
        bot_id="b1",
        exchange="okx",
        quality_tracker=quality,
    )

    snapshot_event = Event(
        event_id="1",
        event_type="orderbook_snapshot",
        schema_version="v1",
        timestamp="100",
        ts_recv_us=100000000,
        ts_canon_us=100000000,
        ts_exchange_s=None,
        bot_id="b1",
        payload={
            "symbol": "BTC",
            "timestamp": 100,
            "seq": 1,
            "bids": [[100.0, 1.0]],
            "asks": [[101.0, 1.0]],
        },
    )
    gap_event = Event(
        event_id="2",
        event_type="orderbook_delta",
        schema_version="v1",
        timestamp="101",
        ts_recv_us=101000000,
        ts_canon_us=101000000,
        ts_exchange_s=None,
        bot_id="b1",
        payload={
            "symbol": "BTC",
            "timestamp": 101,
            "seq": 3,
            "bids": [[100.5, 1.2]],
            "asks": [[101.5, 1.1]],
        },
    )
    tick_event = Event(
        event_id="3",
        event_type="market_tick",
        schema_version="v1",
        timestamp="102",
        ts_recv_us=102000000,
        ts_canon_us=102000000,
        ts_exchange_s=None,
        bot_id="b1",
        payload={
            "symbol": "BTC",
            "timestamp": 102,
            "bid": 100.0,
            "ask": 101.0,
            "last": 100.5,
            "volume": 1.0,
        },
    )

    async def run_once():
        await client.publish_event("events:orderbook_feed", snapshot_event)
        payload = {"data": redis.streams["events:orderbook_feed"].pop(0)["data"]}
        await orderbook_worker._handle_message(payload)
        await client.publish_event("events:orderbook_feed", gap_event)
        payload = {"data": redis.streams["events:orderbook_feed"].pop(0)["data"]}
        await orderbook_worker._handle_message(payload)
        await client.publish_event("events:market_data", tick_event)
        payload = {"data": redis.streams["events:market_data"].pop(0)["data"]}
        await feature_worker._handle_message(payload)

    asyncio.run(run_once())
    resync_payload = {"data": redis.streams["events:orderbook_resync"].pop(0)["data"]}
    resync_event = decode_and_validate_event(resync_payload)
    assert resync_event["event_type"] == "orderbook_resync"
    assert resync_event["payload"]["symbol"] == "BTC"
    feature_payload = {"data": redis.streams["events:features"].pop(0)["data"]}
    feature_event = decode_and_validate_event(feature_payload)
    snapshot = feature_event["payload"]
    assert snapshot["prediction_status"]["reason"] == "orderbook_gap"
