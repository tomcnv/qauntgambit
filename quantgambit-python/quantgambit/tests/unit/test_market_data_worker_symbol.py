import asyncio
import json
import time

from quantgambit.ingest.market_data_worker import MarketDataWorker, MarketDataWorkerConfig
from quantgambit.market.reference_prices import ReferencePriceCache
from quantgambit.storage.redis_streams import RedisStreamsClient


class FakeProvider:
    def __init__(self):
        self.called = False

    async def next_tick(self):
        if self.called:
            raise StopAsyncIteration()
        self.called = True
        return {"symbol": "BTC/USDT:USDT", "bid": 100.0, "ask": 101.0, "timestamp": __import__("time").time()}


class FakeRedis:
    def __init__(self):
        self.events = []

    async def xadd(self, stream, data):
        self.events.append((stream, data))
        return "1-0"


class FakeTelemetry:
    def __init__(self):
        self.latency_payloads = []

    async def publish_latency(self, ctx, payload):
        self.latency_payloads.append(payload)


def test_market_data_worker_normalizes_symbol():
    redis = FakeRedis()
    worker = MarketDataWorker(
        provider=FakeProvider(),
        cache=ReferencePriceCache(),
        redis_client=RedisStreamsClient(redis),
        bot_id="b1",
        exchange="okx",
        config=MarketDataWorkerConfig(idle_backoff_sec=0.0, stale_threshold_sec=999.0),
    )

    async def run_once():
        try:
            await worker.run()
        except StopAsyncIteration:
            return

    asyncio.run(run_once())
    assert redis.events
    payload = json.loads(redis.events[0][1]["data"])
    assert payload["payload"]["symbol"] == "BTC-USDT-SWAP"


def test_market_data_worker_uses_local_timestamp():
    class LocalTimestampProvider:
        def __init__(self):
            self.called = False

        async def next_tick(self):
            if self.called:
                raise StopAsyncIteration()
            self.called = True
            return {"symbol": "BTC/USDT:USDT", "bid": 100.0, "ask": 101.0, "timestamp": 1.0}

    redis = FakeRedis()
    cache = ReferencePriceCache()
    worker = MarketDataWorker(
        provider=LocalTimestampProvider(),
        cache=cache,
        redis_client=RedisStreamsClient(redis),
        bot_id="b1",
        exchange="okx",
        config=MarketDataWorkerConfig(
            idle_backoff_sec=0.0,
            stale_threshold_sec=0.0001,
            timestamp_source="local",
        ),
    )

    async def run_once():
        try:
            await worker.run()
        except StopAsyncIteration:
            return

    asyncio.run(run_once())
    assert redis.events
    price, ts = cache.get_reference_price_with_ts("BTC-USDT-SWAP")
    assert price == 100.5
    assert ts >= time.time() - 1.0


def test_market_data_worker_emits_clock_skew():
    class SkewedProvider:
        def __init__(self):
            self.called = False

        async def next_tick(self):
            if self.called:
                raise StopAsyncIteration()
            self.called = True
            return {"symbol": "BTC/USDT:USDT", "bid": 100.0, "ask": 101.0, "timestamp": 1.0}

    redis = FakeRedis()
    telemetry = FakeTelemetry()
    worker = MarketDataWorker(
        provider=SkewedProvider(),
        cache=ReferencePriceCache(),
        redis_client=RedisStreamsClient(redis),
        bot_id="b1",
        exchange="okx",
        telemetry=telemetry,
        telemetry_context=object(),
        config=MarketDataWorkerConfig(
            idle_backoff_sec=0.0,
            stale_threshold_sec=0.0001,
            max_clock_skew_sec=0.1,
        ),
    )

    async def run_once():
        try:
            await worker.run()
        except StopAsyncIteration:
            return

    asyncio.run(run_once())
    assert any(payload.get("market_data_clock_skew") for payload in telemetry.latency_payloads)


def test_market_data_worker_tracks_gap_and_out_of_order():
    class SequenceProvider:
        def __init__(self):
            self.calls = 0

        async def next_tick(self):
            self.calls += 1
            if self.calls == 1:
                return {"symbol": "BTC/USDT:USDT", "bid": 100.0, "ask": 101.0, "timestamp": 10.0}
            if self.calls == 2:
                return {"symbol": "BTC/USDT:USDT", "bid": 100.0, "ask": 101.0, "timestamp": 20.0}
            if self.calls == 3:
                return {"symbol": "BTC/USDT:USDT", "bid": 100.0, "ask": 101.0, "timestamp": 5.0}
            raise StopAsyncIteration()

    class FakeHealth:
        def __init__(self):
            self.calls = []

        def record_market_tick(self, age_sec, is_stale, is_skew, is_gap, is_out_of_order):
            self.calls.append((is_gap, is_out_of_order))

    redis = FakeRedis()
    worker = MarketDataWorker(
        provider=SequenceProvider(),
        cache=ReferencePriceCache(),
        redis_client=RedisStreamsClient(redis),
        bot_id="b1",
        exchange="okx",
        config=MarketDataWorkerConfig(
            idle_backoff_sec=0.0,
            stale_threshold_sec=1.0,
            max_clock_skew_sec=0.0,
        ),
    )
    worker.health_worker = FakeHealth()

    async def run_once():
        try:
            await worker.run()
        except StopAsyncIteration:
            return

    asyncio.run(run_once())
    assert worker.health_worker.calls[0] == (False, False)
    assert worker.health_worker.calls[1] == (True, False)
    assert worker.health_worker.calls[2] == (False, True)


def test_market_data_worker_allows_orderbook_update_after_trade_without_price():
    class SequenceProvider:
        def __init__(self):
            self.calls = 0

        async def next_tick(self):
            self.calls += 1
            if self.calls == 1:
                return {"symbol": "BTC/USDT:USDT", "last": 100.0, "timestamp": 1.0, "source": "trade_feed"}
            if self.calls == 2:
                return {
                    "symbol": "BTC/USDT:USDT",
                    "bid": 100.0,
                    "ask": 101.0,
                    "timestamp": 2.0,
                    "source": "orderbook_feed",
                }
            raise StopAsyncIteration()

    redis = FakeRedis()
    cache = ReferencePriceCache()
    worker = MarketDataWorker(
        provider=SequenceProvider(),
        cache=cache,
        redis_client=RedisStreamsClient(redis),
        bot_id="b1",
        exchange="okx",
        config=MarketDataWorkerConfig(
            idle_backoff_sec=0.0,
            stale_threshold_sec=999.0,
            max_clock_skew_sec=0.0,
        ),
    )

    async def run_once():
        try:
            await worker.run()
        except StopAsyncIteration:
            return

    asyncio.run(run_once())
    price, _ = cache.get_reference_price_with_ts("BTC-USDT-SWAP")
    assert price == 100.5
