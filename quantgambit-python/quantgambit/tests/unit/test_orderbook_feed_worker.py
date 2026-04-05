import time

from quantgambit.ingest.orderbook_feed import OrderbookFeedWorker, OrderbookFeedConfig, _resolve_orderbook_timestamp
from quantgambit.storage.redis_streams import RedisStreamsClient


class FakeProvider:
    def __init__(self):
        self._updates = [
            {
                "type": "snapshot",
                "payload": {"symbol": "BTC", "seq": 1, "bids": [[100, 1]], "asks": [[101, 1]], "timestamp": 1},
            },
            {
                "type": "delta",
                "payload": {"symbol": "BTC", "seq": 2, "bids": [[100, 0]], "asks": [[101, 2]], "timestamp": 2},
            },
        ]
        self.requested = 0

    async def next_update(self):
        if self._updates:
            return self._updates.pop(0)
        return None

    async def request_snapshot(self):
        self.requested += 1


class FakeRedis:
    def __init__(self):
        self.events = []
        self.resync = []

    async def xadd(self, stream, data):
        self.events.append((stream, data))
        return "1-0"

    async def xreadgroup(self, group, consumer, streams, count=10, block=1000):
        if not self.resync:
            return []
        stream_name, payload = self.resync.pop(0)
        return [(stream_name, [("1-0", payload)])]

    async def xack(self, stream, group, message_id):
        return 1


def test_orderbook_feed_publishes_snapshot_and_delta():
    redis = FakeRedis()
    worker = OrderbookFeedWorker(
        provider=FakeProvider(),
        redis_client=RedisStreamsClient(redis),
        bot_id="b1",
        exchange="okx",
        config=OrderbookFeedConfig(stream="events:orderbook_feed", idle_backoff_sec=0.0),
    )
    snapshot_ts = 1
    delta_ts = 2
    snapshot = {
        "symbol": "BTC",
        "seq": 1,
        "bids": [[100, 1]],
        "asks": [[101, 1]],
        "timestamp": snapshot_ts,
        "ts_recv_us": snapshot_ts * 1_000_000,
        "ts_canon_us": snapshot_ts * 1_000_000,
        "ts_exchange_s": None,
    }
    delta = {
        "symbol": "BTC",
        "seq": 2,
        "bids": [[100, 0]],
        "asks": [[101, 2]],
        "timestamp": delta_ts,
        "ts_recv_us": delta_ts * 1_000_000,
        "ts_canon_us": delta_ts * 1_000_000,
        "ts_exchange_s": None,
    }
    import asyncio

    async def run_once():
        await worker._publish_snapshot(snapshot)
        await worker._publish_delta(delta)

    asyncio.run(run_once())
    assert len(redis.events) == 2


def test_orderbook_feed_normalizes_symbol():
    redis = FakeRedis()
    worker = OrderbookFeedWorker(
        provider=FakeProvider(),
        redis_client=RedisStreamsClient(redis),
        bot_id="b1",
        exchange="okx",
        config=OrderbookFeedConfig(stream="events:orderbook_feed", idle_backoff_sec=0.0),
    )
    snapshot = {
        "symbol": "BTC/USDT:USDT",
        "seq": 1,
        "bids": [[100, 1]],
        "asks": [[101, 1]],
        "timestamp": 1,
        "ts_recv_us": 1_000_000,
        "ts_canon_us": 1_000_000,
        "ts_exchange_s": None,
    }
    import asyncio

    async def run_once():
        await worker._publish_snapshot(snapshot)

    asyncio.run(run_once())
    assert redis.events
    payload = __import__("json").loads(redis.events[0][1]["data"])
    assert payload["payload"]["symbol"] == "BTC-USDT-SWAP"


def test_orderbook_timestamp_skew_falls_back_to_local():
    ts, skewed, _ = _resolve_orderbook_timestamp(1.0, "exchange", max_skew_sec=0.001)
    assert skewed is True
    assert ts != 1.0
    assert abs(ts - time.time()) < 1.0


def test_orderbook_feed_resync_requests_snapshot():
    redis = FakeRedis()
    provider = FakeProvider()
    worker = OrderbookFeedWorker(
        provider=provider,
        redis_client=RedisStreamsClient(redis),
        bot_id="b1",
        exchange="okx",
        config=OrderbookFeedConfig(stream="events:orderbook_feed", idle_backoff_sec=0.0),
    )
    import json
    resync_event = {
        "event_id": "1",
        "event_type": "orderbook_resync",
        "schema_version": "v1",
        "timestamp": "1",
        "ts_recv_us": 1_000_000,
        "ts_canon_us": 1_000_000,
        "ts_exchange_s": None,
        "bot_id": "system",
        "symbol": "BTC",
        "exchange": "okx",
        "payload": {"symbol": "BTC"},
    }
    redis.resync.append(("events:orderbook_resync", {"data": json.dumps(resync_event)}))

    import asyncio

    async def run_once():
        await worker._handle_resync()

    asyncio.run(run_once())
    assert provider.requested == 1
