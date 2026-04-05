import json
import time
from fnmatch import fnmatch
from fastapi.testclient import TestClient

from quantgambit.api.app import app, _redis_client, _timescale_reader


class FakeRedis:
    def __init__(self, data=None, lists=None):
        self.data = data or {}
        self.lists = lists or {}

    async def get(self, key):
        return self.data.get(key)

    async def set(self, key, value):
        self.data[key] = value
        return True

    async def expire(self, key, ttl):
        return True

    async def lrange(self, key, start, stop):
        lst = self.lists.get(key, [])
        return lst[start : stop + 1 if stop >= 0 else None]

    async def keys(self, pattern):
        all_keys = list(self.data.keys()) + list(self.lists.keys())
        return [key for key in all_keys if fnmatch(key, pattern)]

    async def hgetall(self, key):
        value = self.data.get(key, {})
        return value if isinstance(value, dict) else {}

    async def xadd(self, stream, data):
        return "1-0"

    async def close(self):
        return True


def get_client(fake_redis):
    async def _fake_redis_dep():
        try:
            yield fake_redis
        finally:
            pass
    async def _fake_ts_dep():
        try:
            yield FakeTimescale([])
        finally:
            pass

    app.dependency_overrides[_redis_client] = _fake_redis_dep
    app.dependency_overrides[_timescale_reader] = _fake_ts_dep
    return TestClient(app)


class FakePool:
    def __init__(self, rows):
        self._rows = rows

    async def fetch(self, query, *args):
        return self._rows


class FakeTimescale:
    def __init__(self, rows):
        self.pool = FakePool(rows)

    async def load_latest_positions(self, tenant_id: str, bot_id: str):
        return {"positions": []}


def get_client_with_timescale(fake_redis, timescale_rows):
    async def _fake_redis_dep():
        try:
            yield fake_redis
        finally:
            pass

    async def _fake_ts_dep():
        try:
            yield FakeTimescale(timescale_rows)
        finally:
            pass

    app.dependency_overrides[_redis_client] = _fake_redis_dep
    app.dependency_overrides[_timescale_reader] = _fake_ts_dep
    return TestClient(app)


def test_runtime_quality_endpoint():
    tenant = "t1"
    bot = "b1"
    fake = FakeRedis(
        data={
            f"quantgambit:{tenant}:{bot}:quality:latest": json.dumps(
                {"orderbook_sync_state": "synced", "trade_sync_state": "synced", "quality_score": 0.95}
            ),
            f"quantgambit:{tenant}:{bot}:market_data:provider": json.dumps(
                {"active_provider": "ws", "switch_count": 1}
            ),
        }
    )
    client = get_client(fake)
    res = client.get("/api/runtime/quality", params={"tenant_id": tenant, "bot_id": bot})
    assert res.status_code == 200
    body = res.json()
    assert body["orderbook_sync_state"] == "synced"
    assert body["active_provider"] == "ws"


def test_runtime_config_endpoint():
    tenant = "t1"
    bot = "b1"
    fake = FakeRedis(
        data={
            f"quantgambit:{tenant}:{bot}:config:drift": json.dumps(
                {"stored_version": 1, "runtime_version": 2, "timestamp": 1.0}
            )
        }
    )
    client = get_client(fake)
    res = client.get("/api/runtime/config", params={"tenant_id": tenant, "bot_id": bot})
    assert res.status_code == 200
    body = res.json()
    assert body["drift"] is True
    assert body["stored_version"] == 1


def test_runtime_risk_endpoint():
    tenant = "t1"
    bot = "b1"
    fake = FakeRedis(
        data={
            f"quantgambit:{tenant}:{bot}:risk:sizing": json.dumps(
                {
                    "status": "accepted",
                    "size_usd": 1000.0,
                    "risk_budget_usd": 500.0,
                    "limits": {"max_total_exposure_pct": 0.10},
                    "remaining": {"total_usd": 2500.0},
                    "exposure": {"total_usd": 1500.0},
                    "overrides": {"max_positions": 2},
                    "account_equity": 10000.0,
                    "net_exposure_usd": 1500.0,
                    "net_exposure_pct": 0.15,
                }
            )
        }
    )
    client = get_client(fake)
    res = client.get("/api/runtime/risk", params={"tenant_id": tenant, "bot_id": bot})
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "accepted"
    assert body["size_usd"] == 1000.0
    assert body["limits"]["max_total_exposure_pct"] == 0.10
    assert body["remaining"]["total_usd"] == 2500.0
    assert body["exposure"]["total_usd"] == 1500.0
    assert body["overrides"]["max_positions"] == 2
    assert body["account_equity"] == 10000.0
    assert body["net_exposure_usd"] == 1500.0
    assert body["net_exposure_pct"] == 0.15


def test_runtime_orders_positions_guardrails_overrides_health():
    tenant = "t1"
    bot = "b1"
    base = f"quantgambit:{tenant}:{bot}"
    fake = FakeRedis(
        data={
            f"{base}:orders:latest": json.dumps({"orders": []}),
            f"{base}:positions:latest": json.dumps({"positions": []}),
        },
        lists={
            f"{base}:guardrails:history": [json.dumps({"type": "guardrail", "detail": "x"})],
            f"{base}:risk:overrides": [json.dumps({"overrides": {"max_positions": 1}})],
            f"{base}:health:history": [json.dumps({"status": "ok"})],
        },
    )
    client = get_client(fake)

    res = client.get("/api/runtime/orders", params={"tenant_id": tenant, "bot_id": bot})
    assert res.status_code == 200
    assert res.json()["payload"] == {"orders": []}

    res = client.get("/api/runtime/positions", params={"tenant_id": tenant, "bot_id": bot})
    assert res.status_code == 200
    assert res.json()["payload"] == {"positions": []}

    res = client.get("/api/runtime/guardrails", params={"tenant_id": tenant, "bot_id": bot})
    assert res.status_code == 200
    assert res.json()["total"] == 1


def test_runtime_prediction_snapshot():
    tenant = "t1"
    bot = "b1"
    fake = FakeRedis(
        data={
            f"quantgambit:{tenant}:{bot}:prediction:latest": json.dumps(
                {"status": "suppressed", "reason": "orderbook_gap"}
            )
        }
    )
    client = get_client(fake)
    res = client.get("/api/runtime/prediction", params={"tenant_id": tenant, "bot_id": bot})
    assert res.status_code == 200
    assert res.json()["payload"]["reason"] == "orderbook_gap"


def test_history_endpoints_timescale():
    tenant = "t1"
    bot = "b1"
    ts_rows = [{"ts": 1, "payload": {"foo": "bar"}}]
    fake_redis = FakeRedis(
        lists={
            f"quantgambit:{tenant}:{bot}:risk:overrides": [json.dumps({"overrides": {"max_positions": 1}})],
            f"quantgambit:{tenant}:{bot}:health:history": [json.dumps({"status": "ok"})],
        }
    )
    client = get_client_with_timescale(fake_redis, ts_rows)

    res = client.get("/api/history/decisions", params={"tenant_id": tenant, "bot_id": bot})
    assert res.status_code == 200
    assert res.json()["items"][0]["foo"] == "bar"

    res = client.get("/api/history/orders", params={"tenant_id": tenant, "bot_id": bot})
    assert res.status_code == 200
    assert res.json()["items"][0]["foo"] == "bar"

    res = client.get("/api/history/predictions", params={"tenant_id": tenant, "bot_id": bot})
    assert res.status_code == 200
    assert res.json()["items"][0]["foo"] == "bar"

    res = client.get("/api/history/guardrails", params={"tenant_id": tenant, "bot_id": bot})
    assert res.status_code == 200
    assert res.json()["items"][0]["foo"] == "bar"

    res = client.get("/api/runtime/overrides", params={"tenant_id": tenant, "bot_id": bot})
    assert res.status_code == 200
    assert res.json()["total"] == 1

    res = client.get("/api/runtime/health", params={"tenant_id": tenant, "bot_id": bot})
    assert res.status_code == 200
    assert res.json()["total"] == 1


def test_replay_runs_route_is_mounted():
    client = get_client(FakeRedis())
    res = client.get("/api/replay/runs")
    # Route should exist in app; without configured manager it returns 503.
    assert res.status_code == 503


def test_dashboard_live_status_uses_runtime_position_guardian_fallback():
    tenant = "t1"
    bot = "b1"
    base = f"quantgambit:{tenant}:{bot}"
    now = time.time()
    fake = FakeRedis(
        data={
            f"{base}:health:latest": json.dumps(
                {
                    "timestamp": now,
                    "position_guardian": {"status": "running", "timestamp": now},
                }
            ),
            f"{base}:control:state": json.dumps({"trading_paused": False}),
            f"{base}:guardrail:latest": json.dumps({}),
            f"{base}:quality:latest": json.dumps({"quality_score": 0.98}),
            f"{base}:risk:sizing": json.dumps({"status": "ok"}),
            f"{base}:prediction:latest": json.dumps({"provider": "onnx"}),
        },
        lists={
            f"{base}:decisions:history": [],
            f"{base}:orders:history": [],
        },
    )
    client = get_client(fake)
    res = client.get("/api/dashboard/live-status", params={"tenant_id": tenant, "botId": bot})
    assert res.status_code == 200
    body = res.json()
    assert body["position_guardian"]["status"] == "running"
    guard_cfg = body["position_guardian"]["config"]
    assert "maxAgeSec" in guard_cfg
    assert "hardMaxAgeSec" in guard_cfg
    assert "continuationEnabled" in guard_cfg


def test_dashboard_live_status_surfaces_misconfigured_runtime_position_guardian():
    tenant = "t1"
    bot = "b1"
    base = f"quantgambit:{tenant}:{bot}"
    now = time.time()
    fake = FakeRedis(
        data={
            f"{base}:health:latest": json.dumps(
                {
                    "timestamp": now,
                    "position_guardian": {
                        "status": "misconfigured",
                        "reason": "live_perp_guard_disabled",
                        "timestamp": now,
                        "config": {"maxAgeSec": 0.0, "hardMaxAgeSec": 0.0, "continuationEnabled": True},
                    },
                }
            ),
            f"{base}:control:state": json.dumps({"trading_paused": False}),
            f"{base}:guardrail:latest": json.dumps({}),
            f"{base}:quality:latest": json.dumps({"quality_score": 0.98}),
            f"{base}:risk:sizing": json.dumps({"status": "ok"}),
            f"{base}:prediction:latest": json.dumps({"provider": "onnx"}),
        },
        lists={
            f"{base}:decisions:history": [],
            f"{base}:orders:history": [],
        },
    )
    client = get_client(fake)
    res = client.get("/api/dashboard/live-status", params={"tenant_id": tenant, "botId": bot})
    assert res.status_code == 200
    body = res.json()
    assert body["position_guardian"]["status"] == "misconfigured"
    assert body["position_guardian"]["config"]["maxAgeSec"] == 0.0


def test_dashboard_live_status_does_not_mark_bot_running_from_stale_activity_only():
    tenant = "t1"
    bot = "b1"
    base = f"quantgambit:{tenant}:{bot}"
    stale_ts = time.time() - 300
    recent_ts = time.time() - 5
    fake = FakeRedis(
        data={
            f"{base}:health:latest": json.dumps(
                {
                    "timestamp": stale_ts,
                    "timestamp_epoch": stale_ts,
                    "services": {"python_engine": {"status": "stopped"}},
                }
            ),
            f"{base}:control:state": json.dumps({"trading_active": True, "trading_paused": False}),
            f"{base}:guardrail:latest": json.dumps({}),
            f"{base}:quality:latest": json.dumps({"quality_score": 0.98}),
            f"{base}:risk:sizing": json.dumps({"status": "ok"}),
            f"{base}:prediction:latest": json.dumps({"provider": "deepseek_context"}),
        },
        lists={
            f"{base}:decision:history": [json.dumps({"timestamp": recent_ts, "result": "APPROVE"})],
            f"{base}:orders:history": [json.dumps({"timestamp": recent_ts, "status": "filled"})],
        },
    )
    client = get_client(fake)
    res = client.get("/api/dashboard/live-status", params={"tenant_id": tenant, "botId": bot})
    assert res.status_code == 200
    body = res.json()
    assert body["heartbeat"]["status"] == "dead"
    assert body["botStatus"] == "stopped"
    assert body["funnel"]["isLive"] is False


def test_monitoring_fast_scalper_does_not_mark_running_from_positions_only():
    tenant = "t1"
    bot = "b1"
    base = f"quantgambit:{tenant}:{bot}"
    fake = FakeRedis(
        data={
            f"{base}:positions:latest": json.dumps({"positions": [{"symbol": "BTCUSDT", "size": 1.0}]}),
            f"{base}:control:state": json.dumps({}),
            f"{base}:health:latest": json.dumps({"services": {"python_engine": {"status": "stopped"}}}),
        },
        lists={},
    )
    client = get_client(fake)
    res = client.get("/api/monitoring/fast-scalper", params={"tenant_id": tenant, "botId": bot})
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "unknown"


def test_monitoring_fast_scalper_ignores_retry_noise_in_completed_trades():
    tenant = "t1"
    bot = "b1"
    base = f"quantgambit:{tenant}:{bot}"
    fake = FakeRedis(
        data={
            f"{base}:control:state": json.dumps({"status": "running"}),
            f"{base}:health:latest": json.dumps(
                {
                    "timestamp_epoch": time.time(),
                    "services": {"python_engine": {"status": "running"}},
                }
            ),
        },
        lists={
            f"{base}:orders:history": [
                json.dumps(
                    {
                        "symbol": "BTCUSDT",
                        "status": "retrying",
                        "reason": "execution_retry",
                        "order_id": "ord-retry",
                        "client_order_id": "cid-retry",
                        "position_effect": "close",
                    }
                ),
                json.dumps(
                    {
                        "symbol": "BTCUSDT",
                        "status": "open",
                        "reason": "execution_update",
                        "order_id": "ord-open",
                        "client_order_id": "cid-open",
                        "position_effect": "close",
                    }
                ),
                json.dumps(
                    {
                        "symbol": "BTCUSDT",
                        "status": "filled",
                        "reason": "stop_loss_hit",
                        "order_id": "ord-filled",
                        "client_order_id": "cid-filled",
                        "position_effect": "close",
                        "entry_price": 71000.0,
                        "exit_price": 70800.0,
                        "filled_size": 0.01,
                        "net_pnl": -2.0,
                    }
                ),
            ]
        },
    )
    client = get_client(fake)
    res = client.get("/api/monitoring/fast-scalper", params={"tenant_id": tenant, "botId": bot})
    assert res.status_code == 200
    body = res.json()
    assert body["metrics"]["completedTrades"] == 1
    assert body["metrics"]["dailyPnl"] == -2.0


def test_dashboard_warmup_merges_candle_counts_into_symbol_progress():
    tenant = "t1"
    bot = "b1"
    base = f"quantgambit:{tenant}:{bot}"
    now = time.time()
    fake = FakeRedis(
        data={
            f"{base}:warmup:BTCUSDT": json.dumps(
                {
                    "symbol": "BTCUSDT",
                    "ready": False,
                    "sample_count": 2,
                    "min_samples": 2,
                    "candle_count": 0,
                    "min_candles": 0,
                    "reasons": ["warmup"],
                }
            ),
            f"{base}:health:latest": json.dumps(
                {
                    "status": "starting",
                    "timestamp_epoch": now,
                    "services": {"python_engine": {"status": "running"}},
                }
            ),
            f"{base}:candle_counts": {
                "BTCUSDT:60": "99",
                "BTCUSDT:300": "4",
                "ETHUSDT:300": "3",
            },
        }
    )
    client = get_client(fake)
    res = client.get("/api/dashboard/warmup", params={"tenant_id": tenant, "botId": bot})
    assert res.status_code == 200
    body = res.json()
    assert body["symbols"]["BTCUSDT"]["sampleCount"] == 2
    assert body["symbols"]["BTCUSDT"]["candleCount"] == 4
    assert body["symbols"]["BTCUSDT"]["minCandles"] == 10
    assert body["symbols"]["ETHUSDT"]["candleCount"] == 3
    assert body["overall"]["candleCount"] == 7
