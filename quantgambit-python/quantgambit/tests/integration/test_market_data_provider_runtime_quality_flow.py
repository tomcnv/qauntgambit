import asyncio
import time

from fastapi.testclient import TestClient

from quantgambit.api.app import app, _redis_client
from quantgambit.market.quality import MarketDataQualityTracker
from quantgambit.observability.telemetry import TelemetryContext
from quantgambit.runtime.entrypoint import ResilientMarketDataProvider
from quantgambit.storage.redis_snapshots import RedisSnapshotWriter


class FakeRedis:
    def __init__(self):
        self.data = {}
        self.lists = {}

    async def get(self, key):
        return self.data.get(key)

    async def set(self, key, value):
        self.data[key] = value
        return True

    async def expire(self, key, ttl):
        return True

    async def lpush(self, key, value):
        self.lists.setdefault(key, []).insert(0, value)
        return len(self.lists[key])

    async def ltrim(self, key, start, stop):
        lst = self.lists.get(key, [])
        self.lists[key] = lst[start : stop + 1 if stop >= 0 else None]
        return True


class DummyProvider:
    def __init__(self, *, fail=True, tick=None):
        self.fail = fail
        self.tick = tick

    async def next_tick(self):
        if self.fail:
            raise RuntimeError("no data")
        return self.tick


def test_provider_switch_updates_runtime_quality():
    redis = FakeRedis()
    snapshots = RedisSnapshotWriter(redis)
    ctx = TelemetryContext(tenant_id="t1", bot_id="b1", exchange="okx")
    quality = MarketDataQualityTracker(snapshot_writer=snapshots, telemetry_context=ctx)
    provider = ResilientMarketDataProvider(
        providers=[DummyProvider(fail=True), DummyProvider(fail=False, tick={"symbol": "BTC"})],
        provider_names=["ws", "ccxt"],
        switch_threshold=1,
        idle_backoff_sec=0.0,
        guardrail_cooldown_sec=0.0,
    )
    provider.set_snapshot_writer(snapshots, "quantgambit:t1:b1:market_data:provider")

    async def run_once():
        await provider.next_tick()
        now = time.time()
        quality.update_orderbook(symbol="BTC", timestamp=now, now_ts=now, gap=False)
        await quality.snapshot("BTC", now_ts=now)

    asyncio.run(run_once())

    async def _fake_redis_dep():
        try:
            yield redis
        finally:
            pass

    app.dependency_overrides[_redis_client] = _fake_redis_dep
    client = TestClient(app)
    res = client.get("/api/runtime/quality", params={"tenant_id": "t1", "bot_id": "b1"})
    assert res.status_code == 200
    body = res.json()
    assert body["active_provider"] == "ccxt"
    assert body["orderbook_sync_state"] == "synced"
    assert body["trade_sync_state"] in {"unknown", "synced", "stale"}
