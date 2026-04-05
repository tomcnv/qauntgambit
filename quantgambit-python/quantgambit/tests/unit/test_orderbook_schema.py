import pytest

from quantgambit.observability.telemetry import _validate_orderbook_payload


def test_orderbook_payload_requires_fields():
    with pytest.raises(ValueError):
        _validate_orderbook_payload({"symbol": "BTC"})


def test_orderbook_payload_accepts_minimal():
    payload = {
        "symbol": "BTC",
        "timestamp": 123,
        "bid_depth_usd": 1.0,
        "ask_depth_usd": 2.0,
        "orderbook_imbalance": 0.1,
    }
    _validate_orderbook_payload(payload)
