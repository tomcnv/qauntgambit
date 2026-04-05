import asyncio
import json

from quantgambit.ingest.candle_worker import CandleWorker, CandleWorkerConfig
from quantgambit.storage.redis_streams import RedisStreamsClient


class FakeRedis:
    def __init__(self):
        self.events = []

    async def xadd(self, stream, data):
        self.events.append((stream, data))
        return "1-0"


class FakeTimescale:
    async def write_candle(self, row):
        return None


def _event(symbol: str, ts_sec: float, price: float):
    ts_us = int(ts_sec * 1_000_000)
    tick = {
        "symbol": symbol,
        "timestamp": ts_sec,
        "last": price,
        "volume": 1.0,
        "ts_recv_us": ts_us,
        "ts_canon_us": ts_us,
        "ts_exchange_s": None,
    }
    payload = {
        "event_id": "1",
        "event_type": "market_tick",
        "schema_version": "v1",
        "timestamp": str(ts_sec),
        "ts_recv_us": ts_us,
        "ts_canon_us": ts_us,
        "ts_exchange_s": None,
        "bot_id": "b1",
        "symbol": symbol,
        "exchange": "okx",
        "payload": tick,
    }
    return {"data": json.dumps(payload)}


def test_grace_allows_late_tick_before_publish():
    redis = FakeRedis()
    worker = CandleWorker(
        redis_client=RedisStreamsClient(redis),
        timescale=FakeTimescale(),
        tenant_id="t1",
        bot_id="b1",
        exchange="okx",
        config=CandleWorkerConfig(timeframes_sec=(60,)),
    )

    async def run():
        await worker._handle_message(_event("BTC", 10.0, 100.0))
        await worker._handle_message(_event("BTC", 20.0, 110.0))
        # New bucket starts, pending candle created but not published (grace=2s)
        await worker._handle_message(_event("BTC", 61.0, 120.0))
        # Late tick within grace for previous bucket
        await worker._handle_message(_event("BTC", 59.0, 90.0))
        # Move time forward past grace to publish
        await worker._handle_message(_event("BTC", 63.0, 130.0))

    asyncio.run(run())
    assert redis.events
    payload = json.loads(redis.events[0][1]["data"])["payload"]
    assert payload["low"] == 90.0
    assert payload["close"] == 90.0


def test_late_tick_after_publish_is_dropped():
    redis = FakeRedis()
    worker = CandleWorker(
        redis_client=RedisStreamsClient(redis),
        timescale=FakeTimescale(),
        tenant_id="t1",
        bot_id="b1",
        exchange="okx",
        config=CandleWorkerConfig(timeframes_sec=(60,)),
    )

    async def run():
        await worker._handle_message(_event("BTC", 10.0, 100.0))
        await worker._handle_message(_event("BTC", 20.0, 110.0))
        # Publish pending candle immediately (now >= end + grace)
        await worker._handle_message(_event("BTC", 63.0, 120.0))
        # Late tick for already-finalized bucket should be dropped
        await worker._handle_message(_event("BTC", 30.0, 80.0))

    asyncio.run(run())
    assert len(redis.events) == 1


def test_pending_candle_publishes_after_long_gap():
    redis = FakeRedis()
    worker = CandleWorker(
        redis_client=RedisStreamsClient(redis),
        timescale=FakeTimescale(),
        tenant_id="t1",
        bot_id="b1",
        exchange="okx",
        config=CandleWorkerConfig(timeframes_sec=(60,)),
    )

    async def run():
        await worker._handle_message(_event("BTC", 10.0, 100.0))
        # Long gap; next tick far ahead should publish pending candle
        await worker._handle_message(_event("BTC", 130.0, 120.0))

    asyncio.run(run())
    assert len(redis.events) == 1


def test_multi_timeframe_finalize_after_stall():
    redis = FakeRedis()
    worker = CandleWorker(
        redis_client=RedisStreamsClient(redis),
        timescale=FakeTimescale(),
        tenant_id="t1",
        bot_id="b1",
        exchange="okx",
        config=CandleWorkerConfig(timeframes_sec=(60, 300)),
    )

    async def run():
        await worker._handle_message(_event("BTC", 10.0, 100.0))
        # Jump far enough to finalize both 60s and 300s buckets past grace
        await worker._handle_message(_event("BTC", 700.0, 120.0))

    asyncio.run(run())
    timeframes = [
        json.loads(event[1]["data"])["payload"]["timeframe_sec"] for event in redis.events
    ]
    assert sorted(timeframes) == [60, 300]
