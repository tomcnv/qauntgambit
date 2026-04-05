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


def _event(tick: dict):
    ts_us = int((tick.get("timestamp") or 0) * 1_000_000)
    tick = {**tick, "ts_recv_us": ts_us, "ts_canon_us": ts_us, "ts_exchange_s": None}
    payload = {
        "event_id": "1",
        "event_type": "market_tick",
        "schema_version": "v1",
        "timestamp": str(tick.get("timestamp")),
        "ts_recv_us": ts_us,
        "ts_canon_us": ts_us,
        "ts_exchange_s": None,
        "bot_id": "b1",
        "symbol": tick.get("symbol"),
        "exchange": "okx",
        "payload": tick,
    }
    return {"data": json.dumps(payload)}


def test_candle_worker_marks_last_price_source():
    redis = FakeRedis()
    worker = CandleWorker(
        redis_client=RedisStreamsClient(redis),
        timescale=FakeTimescale(),
        tenant_id="t1",
        bot_id="b1",
        exchange="okx",
        config=CandleWorkerConfig(timeframes_sec=(60,)),
    )

    async def run_once():
        await worker._handle_message(_event({"symbol": "BTC", "timestamp": 10, "last": 100.0, "volume": 1}))
        await worker._handle_message(_event({"symbol": "BTC", "timestamp": 20, "last": 101.0, "volume": 1}))
        await worker._handle_message(_event({"symbol": "BTC", "timestamp": 70, "last": 102.0, "volume": 1}))

    asyncio.run(run_once())
    assert redis.events
    payload = json.loads(redis.events[0][1]["data"])["payload"]
    assert payload["price_source"] == "last"
    assert payload["is_derived"] is False


def test_candle_worker_marks_mid_price_source():
    redis = FakeRedis()
    worker = CandleWorker(
        redis_client=RedisStreamsClient(redis),
        timescale=FakeTimescale(),
        tenant_id="t1",
        bot_id="b1",
        exchange="okx",
        config=CandleWorkerConfig(timeframes_sec=(60,)),
    )

    async def run_once():
        await worker._handle_message(_event({"symbol": "BTC", "timestamp": 10, "bid": 99.0, "ask": 101.0}))
        await worker._handle_message(_event({"symbol": "BTC", "timestamp": 20, "bid": 100.0, "ask": 102.0}))
        await worker._handle_message(_event({"symbol": "BTC", "timestamp": 70, "bid": 101.0, "ask": 103.0}))

    asyncio.run(run_once())
    payload = json.loads(redis.events[0][1]["data"])["payload"]
    assert payload["price_source"] == "mid"
    assert payload["is_derived"] is True
