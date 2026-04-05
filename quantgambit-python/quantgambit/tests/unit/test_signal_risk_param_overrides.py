import pytest

from quantgambit.signals.pipeline import StageContext
from quantgambit.signals.pipeline import _enforce_min_risk_params


def test_symbol_session_overrides_take_precedence(monkeypatch):
    monkeypatch.setenv("MIN_SIGNAL_STOP_DISTANCE_BPS", "5")
    monkeypatch.setenv("MIN_SIGNAL_RR", "1.0")
    monkeypatch.setenv("MIN_SIGNAL_STOP_DISTANCE_BPS_BY_SYMBOL", "ETHUSDT:40")
    monkeypatch.setenv("MIN_SIGNAL_RR_BY_SYMBOL", "ETHUSDT:1.5")
    monkeypatch.setenv(
        "MIN_SIGNAL_STOP_DISTANCE_BPS_BY_SYMBOL_SESSION",
        "ETHUSDT@EUROPE:60",
    )
    monkeypatch.setenv(
        "MIN_SIGNAL_RR_BY_SYMBOL_SESSION",
        "ETHUSDT@EUROPE:2.0",
    )

    signal = {
        "symbol": "ETHUSDT",
        "side": "long",
        "entry_price": 100.0,
        "stop_loss": 99.7,    # 30 bps (will be widened to 60 bps)
        "take_profit": 100.3,  # 30 bps (will be widened to RR=2.0 => 120 bps)
    }
    ctx = StageContext(
        symbol="ETHUSDT",
        data={"market_context": {"session": "europe"}},
    )

    _enforce_min_risk_params(signal, ctx)

    assert signal["sl_distance_bps"] == 60.0
    assert signal["tp_distance_bps"] == 120.0
    assert signal["stop_loss"] == pytest.approx(99.4)
    assert signal["take_profit"] == pytest.approx(101.2)


def test_enforce_max_distances_from_resolved_params_long():
    signal = {
        "symbol": "ETHUSDT",
        "side": "long",
        "entry_price": 100.0,
        "stop_loss": 98.8,    # 120 bps (should cap to 80 bps)
        "take_profit": 103.0,  # 300 bps (should cap to 140 bps)
    }
    ctx = StageContext(
        symbol="ETHUSDT",
        data={"resolved_params": {"stop_loss_bps": 80.0, "take_profit_bps": 140.0}},
    )

    _enforce_min_risk_params(signal, ctx)

    assert signal["sl_distance_bps"] == 80.0
    assert signal["tp_distance_bps"] == 140.0
    assert signal["stop_loss"] == pytest.approx(99.2)
    assert signal["take_profit"] == pytest.approx(101.4)


def test_enforce_max_distances_from_resolved_params_short():
    signal = {
        "symbol": "SOLUSDT",
        "side": "short",
        "entry_price": 100.0,
        "stop_loss": 101.5,  # 150 bps (should cap to 80 bps)
        "take_profit": 96.0,  # 400 bps (should cap to 140 bps)
    }
    ctx = StageContext(
        symbol="SOLUSDT",
        data={"resolved_params": {"stop_loss_bps": 80.0, "take_profit_bps": 140.0}},
    )

    _enforce_min_risk_params(signal, ctx)

    assert signal["sl_distance_bps"] == 80.0
    assert signal["tp_distance_bps"] == 140.0
    assert signal["stop_loss"] == pytest.approx(100.8)
    assert signal["take_profit"] == pytest.approx(98.6)
