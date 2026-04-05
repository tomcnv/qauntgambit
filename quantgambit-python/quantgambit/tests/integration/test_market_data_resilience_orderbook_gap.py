import asyncio
import json
import time

import pytest

from quantgambit.ingest.orderbook_worker import OrderbookWorker, OrderbookWorkerConfig
from quantgambit.market.reference_prices import ReferencePriceCache
from quantgambit.market.quality import MarketDataQualityTracker
from quantgambit.observability.telemetry import TelemetryContext, TelemetryPipeline
from quantgambit.signals.feature_worker import FeaturePredictionWorker, FeatureWorkerConfig
from quantgambit.storage.redis_snapshots import RedisSnapshotWriter
from quantgambit.storage.redis_streams import Event, RedisStreamsClient, decode_message


class FakeRedis:
    def __init__(self):
        self.events = []
        self.data = {}
        self.lists = {}

    async def get(self, key):
        return self.data.get(key)

    async def xadd(self, stream, data):
        self.events.append((stream, data))
        return "1-0"

    async def xgroup_create(self, stream, group, id="0", mkstream=True):
        return None

    async def xreadgroup(self, group, consumer, streams, count=10, block=1000):
        return []

    async def xack(self, stream, group, message_id):
        return 1

    async def set(self, key, value):
        self.data[key] = value
        return True

    async def lpush(self, key, value):
        self.lists.setdefault(key, []).insert(0, value)
        return len(self.lists[key])

    async def ltrim(self, key, start, stop):
        items = self.lists.get(key, [])
        self.lists[key] = items[start : stop + 1 if stop >= 0 else None]
        return True

    async def expire(self, key, ttl):
        return True


@pytest.mark.asyncio
async def test_orderbook_gap_emits_resync_and_blocks_prediction():
    redis = FakeRedis()
    client = RedisStreamsClient(redis)
    cache = ReferencePriceCache()
    snapshots = RedisSnapshotWriter(redis)
    ctx = TelemetryContext(tenant_id="t1", bot_id="b1", exchange="okx")
    telemetry = TelemetryPipeline(redis_client=client, timescale_writer=None, snapshot_writer=snapshots)
    quality = MarketDataQualityTracker(
        snapshot_writer=snapshots,
        telemetry=telemetry,
        telemetry_context=ctx,
        gap_window_sec=60.0,
    )
    orderbook_worker = OrderbookWorker(
        redis_client=client,
        cache=cache,
        quality_tracker=quality,
        config=OrderbookWorkerConfig(
            resync_min_interval_sec=0.0,
            allow_delta_bootstrap=False,  # Disable bootstrap so gaps trigger resync
        ),
        telemetry=telemetry,
        telemetry_context=ctx,
    )

    now_us = int(time.time() * 1_000_000)
    snapshot_event = Event(
        event_id="1",
        event_type="orderbook_snapshot",
        schema_version="v1",
        timestamp=str(time.time()),
        ts_recv_us=now_us,
        ts_canon_us=now_us,
        ts_exchange_s=None,
        bot_id="b1",
        symbol="BTCUSDT",
        exchange="okx",
        payload={
            "symbol": "BTCUSDT",
            "seq": 10,
            "timestamp": time.time(),
            "bids": [[100.0, 1.0]],
            "asks": [[101.0, 1.0]],
        },
    )
    await orderbook_worker._handle_message({"data": json.dumps(snapshot_event.__dict__)})

    gap_us = now_us + 10
    gap_event = Event(
        event_id="2",
        event_type="orderbook_delta",
        schema_version="v1",
        timestamp=str(time.time()),
        ts_recv_us=gap_us,
        ts_canon_us=gap_us,
        ts_exchange_s=None,
        bot_id="b1",
        symbol="BTCUSDT",
        exchange="okx",
        payload={
            "symbol": "BTCUSDT",
            "seq": 12,
            "timestamp": time.time(),
            "bids": [[100.5, 1.0]],
            "asks": [[101.5, 1.0]],
        },
    )
    await orderbook_worker._handle_message({"data": json.dumps(gap_event.__dict__)})

    resync_events = [
        decode_message(data)
        for stream, data in redis.events
        if stream == "events:orderbook_resync"
    ]
    assert resync_events, "expected orderbook_resync event after gap"

    feature_worker = FeaturePredictionWorker(
        redis_client=client,
        bot_id="b1",
        exchange="okx",
        config=FeatureWorkerConfig(gate_on_orderbook_gap=True),
        telemetry=telemetry,
        telemetry_context=ctx,
        orderbook_cache=cache,
        quality_tracker=quality,
    )
    tick = {
        "symbol": "BTCUSDT",
        "timestamp": time.time(),
        "bid": 100.0,
        "ask": 101.0,
        "last": 100.5,
        "source": "orderbook_feed",
    }
    snapshot = await feature_worker._build_snapshot("BTCUSDT", tick)
    assert snapshot is not None
    status = snapshot.get("prediction_status") or {}
    assert status.get("reason") == "orderbook_gap"
    assert snapshot["market_context"]["orderbook_sync_state"] == "resyncing"
