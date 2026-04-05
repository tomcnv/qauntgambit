from quantgambit.deeptrader_core.profiles.context_vector import ContextVector
from quantgambit.deeptrader_core.profiles.profile_router import ProfileRouter
from quantgambit.deeptrader_core.strategies.chessboard.profile_spec import (
    ProfileConditions,
    ProfileSpec,
)


class _DummyRegistry:
    def __init__(self, specs):
        self._specs = list(specs)
        self._by_id = {s.id: s for s in self._specs}

    def list_specs(self):
        return list(self._specs)

    def get_spec(self, profile_id: str):
        return self._by_id.get(profile_id)


def _ctx(hour_utc: int) -> ContextVector:
    return ContextVector(
        symbol="BTCUSDT",
        timestamp=1.0,
        price=100.0,
        bid_depth_usd=50000.0,
        ask_depth_usd=50000.0,
        spread_bps=5.0,
        trades_per_second=10.0,
        book_age_ms=100.0,
        trade_age_ms=100.0,
        risk_mode="normal",
        session="us",
        hour_utc=hour_utc,
    )


def _router_with_profiles() -> ProfileRouter:
    us_open = ProfileSpec(
        id="us_open_momentum",
        name="US Open Momentum",
        description="test",
        conditions=ProfileConditions(required_session="us"),
        strategy_ids=["us_open_momentum"],
    )
    baseline = ProfileSpec(
        id="trend_continuation_pullback",
        name="Trend Continuation Pullback",
        description="test",
        conditions=ProfileConditions(required_session="us"),
        strategy_ids=["trend_pullback"],
    )
    router = ProfileRouter()
    router.registry = _DummyRegistry([us_open, baseline])
    return router


def test_us_open_profile_boosted_inside_window(monkeypatch):
    monkeypatch.setenv("PROFILE_US_OPEN_WINDOW_ENABLED", "true")
    monkeypatch.setenv("PROFILE_US_OPEN_WINDOW_START_UTC", "13")
    monkeypatch.setenv("PROFILE_US_OPEN_WINDOW_END_UTC", "16")
    monkeypatch.setenv("PROFILE_US_OPEN_WINDOW_SCORE_BOOST", "0.2")
    monkeypatch.setenv("PROFILE_US_OPEN_WINDOW_OUTSIDE_PENALTY", "0.2")

    router = _router_with_profiles()
    selected = router.select_profiles(_ctx(14), top_k=1, symbol="BTCUSDT")
    assert selected
    assert selected[0].profile_id == "us_open_momentum"
    assert "us_open_window_boost" in selected[0].reasons


def test_us_open_profile_penalized_outside_window(monkeypatch):
    monkeypatch.setenv("PROFILE_US_OPEN_WINDOW_ENABLED", "true")
    monkeypatch.setenv("PROFILE_US_OPEN_WINDOW_START_UTC", "13")
    monkeypatch.setenv("PROFILE_US_OPEN_WINDOW_END_UTC", "16")
    monkeypatch.setenv("PROFILE_US_OPEN_WINDOW_SCORE_BOOST", "0.2")
    monkeypatch.setenv("PROFILE_US_OPEN_WINDOW_OUTSIDE_PENALTY", "0.2")

    router = _router_with_profiles()
    selected = router.select_profiles(_ctx(19), top_k=1, symbol="BTCUSDT")
    assert selected
    assert selected[0].profile_id == "trend_continuation_pullback"

