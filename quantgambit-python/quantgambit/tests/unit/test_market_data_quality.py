import asyncio
import time

from quantgambit.market.quality import MarketDataQualityTracker
from quantgambit.observability.telemetry import TelemetryContext


class FakeTelemetry:
    def __init__(self):
        self.guardrails = []

    async def publish_guardrail(self, ctx, payload):
        self.guardrails.append(payload)


class FakeSnapshotWriter:
    def __init__(self):
        self.writes = {}
        self.history = {}

    async def write(self, key, payload):
        self.writes[key] = payload

    async def append_history(self, key, payload, max_items=100):
        self.history.setdefault(key, []).append(payload)


def test_quality_tracker_flags_stale_tick():
    tracker = MarketDataQualityTracker(
        tick_stale_sec=1.0,
        trade_stale_sec=1.0,
        orderbook_stale_sec=1.0,
        gap_window_sec=10.0,
    )
    old_ts = time.time() - 5
    tracker.update_tick(
        symbol="BTC",
        timestamp=old_ts,
        now_ts=old_ts,
        is_stale=True,
        is_gap=False,
        is_skew=False,
        is_out_of_order=False,
    )

    async def run_once():
        return await tracker.snapshot("BTC", now_ts=old_ts + 5)

    snapshot = asyncio.run(run_once())
    assert snapshot["status"] in {"degraded", "stale"}
    assert "tick_stale" in snapshot["flags"]
    assert snapshot["orderbook_sync_state"] in {"stale", "resyncing"}
    assert snapshot["trade_sync_state"] == "unknown"


def test_quality_tracker_tracks_preferred_source():
    tracker = MarketDataQualityTracker()
    now = time.time()
    tracker.update_tick(
        symbol="BTC",
        timestamp=now - 1,
        now_ts=now - 1,
        is_stale=False,
        is_gap=False,
        is_skew=False,
        is_out_of_order=False,
        source="okx_ws",
    )
    tracker.update_tick(
        symbol="BTC",
        timestamp=now,
        now_ts=now,
        is_stale=False,
        is_gap=False,
        is_skew=False,
        is_out_of_order=False,
        source="bybit_ws",
    )

    async def run_once():
        return await tracker.snapshot("BTC", now_ts=now)

    snapshot = asyncio.run(run_once())
    assert snapshot["preferred_source"] == "bybit_ws"


def test_quality_tracker_sets_resync_state_on_gap():
    tracker = MarketDataQualityTracker(orderbook_stale_sec=1.0, gap_window_sec=10.0)
    now = time.time()
    tracker.update_orderbook(symbol="BTC", timestamp=now, now_ts=now, gap=True)

    async def run_once():
        return await tracker.snapshot("BTC", now_ts=now)

    snapshot = asyncio.run(run_once())
    assert snapshot["orderbook_sync_state"] == "resyncing"
    assert snapshot["trade_sync_state"] == "unknown"


def test_quality_tracker_emits_guardrail_on_gap():
    telemetry = FakeTelemetry()
    ctx = TelemetryContext(tenant_id="t1", bot_id="b1", exchange="okx")
    tracker = MarketDataQualityTracker(
        telemetry=telemetry,
        telemetry_context=ctx,
        gap_window_sec=10.0,
    )
    now = time.time()
    tracker.update_orderbook(symbol="ETH", timestamp=now, now_ts=now, gap=True)

    async def run_once():
        return await tracker.snapshot("ETH", now_ts=now)

    snapshot = asyncio.run(run_once())
    assert snapshot["orderbook_sync_state"] == "resyncing"
    assert snapshot["trade_sync_state"] == "unknown"
    guardrail = next(item for item in telemetry.guardrails if item.get("type") == "market_data_quality")
    assert guardrail["flags"] is not None
    assert "orderbook_gap" in guardrail["flags"]


def test_quality_tracker_writes_latest_snapshot_key():
    writer = FakeSnapshotWriter()
    ctx = TelemetryContext(tenant_id="t1", bot_id="b1", exchange="okx")
    tracker = MarketDataQualityTracker(
        snapshot_writer=writer,
        telemetry_context=ctx,
    )
    now = time.time()
    tracker.update_orderbook(symbol="BTC", timestamp=now, now_ts=now, gap=False)

    async def run_once():
        return await tracker.snapshot("BTC", now_ts=now)

    asyncio.run(run_once())
    assert "quantgambit:t1:b1:quality:latest" in writer.writes
