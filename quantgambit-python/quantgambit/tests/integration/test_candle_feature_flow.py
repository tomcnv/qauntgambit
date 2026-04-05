import asyncio

from quantgambit.ingest.candle_worker import CandleWorker, CandleWorkerConfig
from quantgambit.signals.feature_worker import FeaturePredictionWorker, FeatureWorkerConfig
from quantgambit.storage.redis_streams import RedisStreamsClient, Event


class FakeRedis:
    def __init__(self):
        self.streams = {}
        self.kv = {}

    async def get(self, key):
        return self.kv.get(key)

    async def set(self, key, value):
        self.kv[key] = value
        return True

    async def xadd(self, stream, data):
        self.streams.setdefault(stream, []).append(data)
        return "1-0"

    async def xgroup_create(self, stream, group, id="0", mkstream=True):
        self.streams.setdefault(stream, [])

    async def xreadgroup(self, group, consumer, streams, count=10, block=1000):
        results = []
        for stream, last_id in streams.items():
            entries = []
            if self.streams.get(stream):
                data = self.streams[stream].pop(0)
                entries.append(("1-0", data))
            if entries:
                results.append((stream, entries))
        return results

    async def xack(self, stream, group, message_id):
        return 1


class FakeTimescale:
    def __init__(self):
        self.written = []

    async def write_candle(self, row):
        self.written.append(row)


def test_candle_feature_flow_emits_snapshot():
    redis = FakeRedis()
    client = RedisStreamsClient(redis)
    timescale = FakeTimescale()
    candle_worker = CandleWorker(
        redis_client=client,
        timescale=timescale,
        tenant_id="t1",
        bot_id="b1",
        exchange="okx",
        config=CandleWorkerConfig(timeframes_sec=(60,)),
    )
    feature_worker = FeaturePredictionWorker(
        redis_client=client,
        bot_id="b1",
        exchange="okx",
        config=FeatureWorkerConfig(candle_stream="events:candles"),
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
            "last": 100.0,
            "volume": 1.0,
        },
    )
    tick_event_next = Event(
        event_id="2",
        event_type="market_tick",
        schema_version="v1",
        timestamp="170",
        ts_recv_us=170000000,
        ts_canon_us=170000000,
        ts_exchange_s=None,
        bot_id="b1",
        payload={
            "symbol": "BTC",
            "timestamp": 170,
            "bid": 99.0,
            "ask": 101.0,
            "last": 100.0,
            "volume": 1.0,
        },
    )

    async def run_once():
        await client.publish_event("events:market_data", tick_event)
        tick_payload = {"data": client.redis.streams["events:market_data"].pop(0)["data"]}
        await candle_worker._handle_message(tick_payload)
        await client.publish_event("events:market_data", tick_event_next)
        tick_payload = {"data": client.redis.streams["events:market_data"].pop(0)["data"]}
        await candle_worker._handle_message(tick_payload)
        candle_payload = {"data": client.redis.streams["events:candles"].pop(0)["data"]}
        await feature_worker._handle_candle(candle_payload)
        await client.publish_event("events:market_data", tick_event)
        tick_payload = {"data": client.redis.streams["events:market_data"].pop(0)["data"]}
        await feature_worker._handle_message(tick_payload)

    asyncio.run(run_once())
    assert client.redis.streams.get("events:features")
