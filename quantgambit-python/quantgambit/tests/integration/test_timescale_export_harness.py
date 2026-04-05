import asyncio
import json
from types import SimpleNamespace

from scripts.export_prediction_dataset import _run


class FakeRedis:
    def __init__(self, events):
        self._events = events
        self._served = set()

    async def xrange(self, stream, min="-", max="+", count=1000):
        if min != "-" and stream in self._served:
            return []
        self._served.add(stream)
        return self._events.get(stream, [])

    async def aclose(self):
        return None


class FakeConn:
    async def fetch(self, query, *params):
        return [
            {
                "symbol": "BTC",
                "ts": 1704067200.0,
                "payload": {
                    "side": "sell",
                    "fill_price": 105.0,
                    "position_effect": "close",
                    "realized_pnl_pct": 2.0,
                    "entry_timestamp": 1704067190.0,
                    "entry_price": 100.0,
                    "size": 1.0,
                    "status": "filled",
                },
            }
        ]


class FakeAcquire:
    async def __aenter__(self):
        return FakeConn()

    async def __aexit__(self, exc_type, exc, tb):
        return False


class FakePool:
    def acquire(self):
        return FakeAcquire()

    async def close(self):
        return None


def test_timescale_export_harness(monkeypatch, tmp_path):
    async def fake_create_pool(_):
        return FakePool()

    def fake_from_url(_):
        feature_event = {
            "event_id": "1",
            "event_type": "feature_snapshot",
            "schema_version": "v1",
            "timestamp": "2024-01-01T00:00:00Z",
            "bot_id": "b1",
            "symbol": "BTC",
            "exchange": "binance",
            "payload": {
                "symbol": "BTC",
                "timestamp": 1704067190.0,
                "features": {"price": 100.0},
                "market_context": {"price": 100.0, "timestamp": 1704067190.0},
            },
        }
        payload = {"data": json.dumps(feature_event)}
        events = {"events:features": [("1-0", payload)]}
        return FakeRedis(events)

    monkeypatch.setattr("scripts.export_prediction_dataset.asyncpg.create_pool", fake_create_pool)
    monkeypatch.setattr("scripts.export_prediction_dataset.redis.from_url", fake_from_url)
    output = tmp_path / "export.csv"
    args = SimpleNamespace(
        redis_url="redis://local",
        stream="events:features",
        limit=None,
        label_source="order_exit_pnl",
        order_source="timescale",
        timescale_url="postgres://local",
        tenant_id="t1",
        bot_id="b1",
        exchange="binance",
        order_stream="events:order",
        order_limit=None,
        order_status="filled",
        horizon_sec=300.0,
        up_threshold=0.001,
        down_threshold=-0.001,
        order_window_sec=30.0,
        features=["price"],
        output=str(output),
    )
    asyncio.run(_run(args))
    contents = output.read_text(encoding="utf-8").strip().splitlines()
    assert len(contents) == 2
