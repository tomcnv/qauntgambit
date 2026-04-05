import asyncio
import json
from datetime import datetime, timezone

import pytest

from scripts.export_prediction_dataset import (
    _load_feature_keys,
    _label_from_orders,
    _parse_iso_ts,
    _label_from_return,
    _iter_order_pnl_rows,
    _find_snapshot_before,
    _iter_order_exit_rows,
    _parse_timescale_order_row,
    _load_order_events_timescale,
)


def test_load_feature_keys_reads_config(tmp_path):
    config_path = tmp_path / "prediction.json"
    config_path.write_text(json.dumps({"feature_keys": ["price", "spread_bps"]}), encoding="utf-8")
    assert _load_feature_keys(str(config_path)) == ["price", "spread_bps"]


def test_load_feature_keys_missing_path():
    with pytest.raises(SystemExit):
        _load_feature_keys("missing.json")


def test_load_feature_keys_missing_keys(tmp_path):
    config_path = tmp_path / "prediction.json"
    config_path.write_text(json.dumps({"class_labels": ["up"]}), encoding="utf-8")
    with pytest.raises(SystemExit):
        _load_feature_keys(str(config_path))


def test_parse_iso_ts():
    ts = _parse_iso_ts("2024-01-01T00:00:00Z")
    assert ts == 1704067200.0


def test_label_from_orders_window():
    order_ts = [100.0, 120.0]
    orders = [{"timestamp": 100.0, "side": "buy"}, {"timestamp": 120.0, "side": "sell"}]
    assert _label_from_orders(order_ts, orders, 90.0, 15.0) == "up"
    assert _label_from_orders(order_ts, orders, 110.0, 5.0) is None


def test_label_from_return():
    assert _label_from_return(0.01, 0.001, -0.001) == "up"
    assert _label_from_return(-0.01, 0.001, -0.001) == "down"
    assert _label_from_return(0.0, 0.001, -0.001) == "flat"


def test_iter_order_pnl_rows():
    records = {
        "BTC": [
            {"timestamp": 100.0, "price": 100.0, "features": {"price": 100.0}, "market_context": {}},
            {"timestamp": 200.0, "price": 110.0, "features": {"price": 110.0}, "market_context": {}},
        ]
    }
    orders = {"BTC": [{"timestamp": 110.0, "side": "buy", "fill_price": 101.0}]}
    rows = list(
        _iter_order_pnl_rows(
            records,
            orders,
            window_sec=20.0,
            horizon_sec=80.0,
            up_threshold=0.001,
            down_threshold=-0.001,
            feature_keys=["price"],
        )
    )
    assert rows
    assert rows[0]["label"] == "up"


def test_find_snapshot_before():
    timestamps = [10.0, 20.0, 30.0]
    assert _find_snapshot_before(timestamps, 5.0) is None
    assert _find_snapshot_before(timestamps, 20.0) == 1
    assert _find_snapshot_before(timestamps, 25.0) == 1


def test_iter_order_exit_rows():
    records = {
        "BTC": [
            {"timestamp": 100.0, "price": 100.0, "features": {"price": 100.0}, "market_context": {}},
            {"timestamp": 150.0, "price": 110.0, "features": {"price": 110.0}, "market_context": {}},
        ]
    }
    orders = {
        "BTC": [
            {
                "timestamp": 140.0,
                "side": "sell",
                "fill_price": 106.0,
                "position_effect": "close",
                "entry_timestamp": 110.0,
                "realized_pnl_pct": 4.95,
                "entry_price": 101.0,
                "size": 1.0,
            },
        ]
    }
    rows = list(
        _iter_order_exit_rows(
            records,
            orders,
            up_threshold=0.001,
            down_threshold=-0.001,
            feature_keys=["price"],
        )
    )
    assert rows
    assert rows[0]["label"] == "up"


def test_parse_timescale_order_row():
    ts = datetime(2024, 1, 1, tzinfo=timezone.utc)
    row = {
        "symbol": "BTC",
        "ts": ts,
        "payload": {
            "side": "sell",
            "fill_price": 105.0,
            "position_effect": "close",
            "realized_pnl_pct": 2.0,
            "entry_timestamp": 1704067200.0,
            "entry_price": 100.0,
            "size": 1.0,
        },
    }
    parsed = _parse_timescale_order_row(row)
    assert parsed["symbol"] == "BTC"
    assert parsed["timestamp"] == ts.timestamp()
    assert parsed["position_effect"] == "close"
    assert parsed["realized_pnl_pct"] == 2.0


def test_timescale_order_events_drive_exit_labels(monkeypatch):
    class FakeConn:
        async def fetch(self, query, *params):
            return [
                {
                    "symbol": "BTC",
                    "ts": datetime(2024, 1, 1, tzinfo=timezone.utc),
                    "payload": {
                        "side": "sell",
                        "fill_price": 105.0,
                        "position_effect": "close",
                        "realized_pnl_pct": 2.0,
                        "entry_timestamp": 1704067200.0,
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

    async def fake_create_pool(_):
        return FakePool()

    monkeypatch.setattr("scripts.export_prediction_dataset.asyncpg.create_pool", fake_create_pool)
    order_events = asyncio.run(
        _load_order_events_timescale(
            "postgres://localhost:5432/bot",
            tenant_id="t1",
            bot_id="b1",
            limit=None,
            status="filled",
            exchange=None,
        )
    )
    records = {
        "BTC": [
            {"timestamp": 1704067190.0, "price": 100.0, "features": {"price": 100.0}, "market_context": {}},
            {"timestamp": 1704067210.0, "price": 110.0, "features": {"price": 110.0}, "market_context": {}},
        ]
    }
    rows = list(
        _iter_order_exit_rows(
            records,
            order_events,
            up_threshold=0.001,
            down_threshold=-0.001,
            feature_keys=["price"],
        )
    )
    assert rows
    assert rows[0]["label"] == "up"
