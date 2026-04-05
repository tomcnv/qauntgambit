import pytest

from quantgambit.deeptrader_core.strategies.poc_magnet_scalp import POCMagnetScalp
from quantgambit.deeptrader_core.types import AccountState, Features, Profile


def _make_account() -> AccountState:
    return AccountState(
        equity=10000.0,
        daily_pnl=0.0,
        max_daily_loss=-500.0,
        open_positions=0,
        symbol_open_positions=0,
        symbol_daily_pnl=0.0,
    )


def _make_profile(session: str = "europe") -> Profile:
    return Profile(
        id="near_poc_micro_scalp",
        trend="flat",
        volatility="normal",
        value_location="inside",
        session=session,
        risk_mode="normal",
    )


def _make_features(rotation_factor: float) -> Features:
    return Features(
        symbol="ETHUSDT",
        price=2082.25,
        spread=0.00001,
        rotation_factor=rotation_factor,
        position_in_value="inside",
        distance_to_poc=11.2,
        distance_to_poc_bps=54.1,
        orderflow_imbalance=0.57,
        bid_depth_usd=400000.0,
        ask_depth_usd=190000.0,
    )


def test_poc_magnet_default_rejects_short_when_rotation_positive():
    strategy = POCMagnetScalp()
    signal = strategy.generate_signal(
        features=_make_features(rotation_factor=2.8),
        account=_make_account(),
        profile=_make_profile("europe"),
        params={
            "rotation_threshold": 0.4,
            "max_adverse_orderflow": 0.6,
            "min_edge_bps": 3.0,
        },
    )
    assert signal is None


def test_poc_magnet_symbol_session_short_rotation_override_allows_signal(monkeypatch):
    monkeypatch.setenv(
        "POC_MAGNET_SHORT_ROTATION_MAX_BY_SYMBOL_SESSION",
        "ETHUSDT@EUROPE:3.0",
    )
    strategy = POCMagnetScalp()
    signal = strategy.generate_signal(
        features=_make_features(rotation_factor=2.8),
        account=_make_account(),
        profile=_make_profile("europe"),
        params={
            "rotation_threshold": 0.4,
            "max_adverse_orderflow": 0.6,
            "min_edge_bps": 3.0,
        },
    )
    assert signal is not None
    assert signal.side == "short"
    assert signal.strategy_id == "poc_magnet_scalp"
