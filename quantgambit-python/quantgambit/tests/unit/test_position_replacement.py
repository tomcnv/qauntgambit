import time

import pytest

from quantgambit.signals.pipeline import StageContext, _maybe_allow_replacement


def _ctx(symbol: str, positions: list, risk_limits: dict | None = None) -> StageContext:
    return StageContext(symbol=symbol, data={"positions": positions, "risk_limits": risk_limits or {}})


def test_replacement_allowed_with_strict_thresholds(monkeypatch):
    monkeypatch.setenv("ALLOW_POSITION_REPLACEMENT", "true")
    monkeypatch.setenv("REPLACE_OPPOSITE_ONLY", "true")
    monkeypatch.setenv("REPLACE_MIN_EDGE_BPS", "5.0")
    monkeypatch.setenv("REPLACE_MIN_CONFIDENCE", "0.6")
    monkeypatch.setenv("REPLACE_MIN_HOLD_SEC", "0.0")

    positions = [
        {"symbol": "BTCUSDT", "side": "short", "size": 1.0, "opened_at": time.time() - 120},
    ]
    signal = {
        "side": "long",
        "expected_edge_bps": 12.0,
        "prediction_confidence": 0.75,
    }

    ctx = _ctx("BTCUSDT", positions, {"max_positions_per_symbol": 1})
    assert _maybe_allow_replacement(signal, ctx) is True
    assert signal.get("replace_position") is True
    assert signal.get("replace_reason") == "replace_opposite_side"


def test_replacement_blocked_by_edge_threshold(monkeypatch):
    monkeypatch.setenv("ALLOW_POSITION_REPLACEMENT", "true")
    monkeypatch.setenv("REPLACE_OPPOSITE_ONLY", "true")
    monkeypatch.setenv("REPLACE_MIN_EDGE_BPS", "15.0")
    monkeypatch.setenv("REPLACE_MIN_CONFIDENCE", "0.0")
    monkeypatch.setenv("REPLACE_MIN_HOLD_SEC", "0.0")

    positions = [
        {"symbol": "ETHUSDT", "side": "short", "size": 1.0, "opened_at": time.time() - 120},
    ]
    signal = {
        "side": "long",
        "expected_edge_bps": 10.0,
        "prediction_confidence": 0.9,
    }

    ctx = _ctx("ETHUSDT", positions, {"max_positions_per_symbol": 1})
    assert _maybe_allow_replacement(signal, ctx) is False
    assert signal.get("replace_position") is None


def test_replacement_blocked_by_same_side(monkeypatch):
    monkeypatch.setenv("ALLOW_POSITION_REPLACEMENT", "true")
    monkeypatch.setenv("REPLACE_OPPOSITE_ONLY", "true")
    monkeypatch.setenv("REPLACE_MIN_EDGE_BPS", "0.0")
    monkeypatch.setenv("REPLACE_MIN_CONFIDENCE", "0.0")
    monkeypatch.setenv("REPLACE_MIN_HOLD_SEC", "0.0")

    positions = [
        {"symbol": "SOLUSDT", "side": "long", "size": 1.0, "opened_at": time.time() - 120},
    ]
    signal = {
        "side": "long",
        "expected_edge_bps": 20.0,
        "prediction_confidence": 0.9,
    }

    ctx = _ctx("SOLUSDT", positions, {"max_positions_per_symbol": 1})
    assert _maybe_allow_replacement(signal, ctx) is False


def test_replacement_blocked_by_min_hold(monkeypatch):
    monkeypatch.setenv("ALLOW_POSITION_REPLACEMENT", "true")
    monkeypatch.setenv("REPLACE_OPPOSITE_ONLY", "true")
    monkeypatch.setenv("REPLACE_MIN_EDGE_BPS", "0.0")
    monkeypatch.setenv("REPLACE_MIN_CONFIDENCE", "0.0")
    monkeypatch.setenv("REPLACE_MIN_HOLD_SEC", "60.0")

    now = time.time()
    monkeypatch.setattr(time, "time", lambda: now)

    positions = [
        {"symbol": "BTCUSDT", "side": "short", "size": 1.0, "opened_at": now - 10},
    ]
    signal = {
        "side": "long",
        "expected_edge_bps": 20.0,
        "prediction_confidence": 0.9,
    }

    ctx = _ctx("BTCUSDT", positions, {"max_positions_per_symbol": 1})
    assert _maybe_allow_replacement(signal, ctx) is False
