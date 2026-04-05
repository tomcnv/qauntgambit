import asyncio
import time

from quantgambit.ingest.orderbook_worker import OrderbookWorker, OrderbookWorkerConfig
from quantgambit.market.reference_prices import ReferencePriceCache
from quantgambit.storage.redis_streams import RedisStreamsClient


class FakeRedis:
    def __init__(self):
        self.events = []

    async def xgroup_create(self, stream, group, id="0", mkstream=True):
        return None

    async def xreadgroup(self, group, consumer, streams, count=10, block=1000):
        return []

    async def xack(self, stream, group, message_id):
        return 1

    async def xadd(self, stream, data):
        self.events.append((stream, data))
        return "1-0"


def test_orderbook_worker_updates_timestamp():
    cache = ReferencePriceCache()
    worker = OrderbookWorker(redis_client=RedisStreamsClient(FakeRedis()), cache=cache)
    snapshot = {
        "symbol": "BTC",
        "seq": 1,
        "bids": [[100, 1]],
        "asks": [[101, 1]],
        "timestamp": 10.0,
    }
    delta = {
        "symbol": "BTC",
        "seq": 2,
        "bids": [[100, 0]],
        "asks": [[101, 2]],
        "timestamp": 12.0,
    }
    asyncio.run(worker._apply_snapshot(snapshot))
    _, ts = cache.get_orderbook_with_ts("BTC")
    assert ts == 10.0
    price = cache.get_reference_price("BTC")
    assert price == 100.5
    asyncio.run(worker._apply_delta(delta))
    _, ts = cache.get_orderbook_with_ts("BTC")
    assert ts == 12.0
    price = cache.get_reference_price("BTC")
    assert price == 100.5


def test_orderbook_worker_clears_cache_on_gap():
    cache = ReferencePriceCache()
    # Disable delta bootstrap so gaps actually clear the cache
    config = OrderbookWorkerConfig(allow_delta_bootstrap=False)
    worker = OrderbookWorker(
        redis_client=RedisStreamsClient(FakeRedis()),
        cache=cache,
        config=config,
    )
    snapshot = {
        "symbol": "BTC",
        "seq": 1,
        "bids": [[100, 1]],
        "asks": [[101, 1]],
        "timestamp": 10.0,
    }
    delta_gap = {
        "symbol": "BTC",
        "seq": 3,  # Gap: expected seq=2, got seq=3
        "bids": [[100, 0]],
        "asks": [[101, 2]],
        "timestamp": 12.0,
    }
    asyncio.run(worker._apply_snapshot(snapshot))
    assert cache.get_orderbook("BTC") is not None
    asyncio.run(worker._apply_delta(delta_gap))
    assert cache.get_orderbook("BTC") is None


def test_orderbook_worker_emits_resync_on_gap():
    redis = FakeRedis()
    cache = ReferencePriceCache()
    # Disable delta bootstrap so gaps actually trigger resync events
    config = OrderbookWorkerConfig(allow_delta_bootstrap=False)
    worker = OrderbookWorker(
        redis_client=RedisStreamsClient(redis),
        cache=cache,
        config=config,
    )
    snapshot = {
        "symbol": "BTC",
        "seq": 1,
        "bids": [[100, 1]],
        "asks": [[101, 1]],
        "timestamp": 10.0,
    }
    delta_gap = {
        "symbol": "BTC",
        "seq": 3,  # Gap: expected seq=2, got seq=3
        "bids": [[100, 0]],
        "asks": [[101, 2]],
        "timestamp": 12.0,
    }
    asyncio.run(worker._apply_snapshot(snapshot))
    asyncio.run(worker._apply_delta(delta_gap))
    assert any(stream == "events:orderbook_resync" for stream, _ in redis.events)


def test_orderbook_worker_live_gap_does_not_delta_bootstrap():
    redis = FakeRedis()
    cache = ReferencePriceCache()
    worker = OrderbookWorker(
        redis_client=RedisStreamsClient(redis),
        cache=cache,
        config=OrderbookWorkerConfig(allow_delta_bootstrap=True),
    )
    snapshot = {
        "symbol": "BTC",
        "seq": 1,
        "bids": [[100, 1]],
        "asks": [[101, 1]],
        "timestamp": 10.0,
    }
    delta_gap = {
        "symbol": "BTC",
        "seq": 3,
        "prev_seq": 2,
        "bids": [[100, 0]],
        "asks": [[101, 2]],
        "timestamp": 12.0,
    }
    asyncio.run(worker._apply_snapshot(snapshot))
    assert cache.get_orderbook("BTC") is not None
    asyncio.run(worker._apply_delta(delta_gap))
    assert cache.get_orderbook("BTC") is None
    assert any(stream == "events:orderbook_resync" for stream, _ in redis.events)
