import os

from quantgambit.deeptrader_core.profiles.context_vector import ContextVector
from quantgambit.deeptrader_core.profiles.profile_router import ProfileRouter
from quantgambit.deeptrader_core.strategies.chessboard.profile_spec import ProfileSpec, ProfileConditions


class _DummyRegistry:
    def __init__(self, specs):
        self._specs = list(specs)
        self._by_id = {s.id: s for s in self._specs}

    def list_specs(self):
        return list(self._specs)

    def get_spec(self, profile_id: str):
        return self._by_id.get(profile_id)


def _ctx(symbol: str) -> ContextVector:
    # Use "near-POC" defaults; router's preference code will run deterministically.
    return ContextVector(
        symbol=symbol,
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
        hour_utc=0,
    )


def test_profile_router_rejects_profile_with_no_enabled_strategies(monkeypatch):
    """
    If all strategies under a profile are disabled for a symbol (e.g. mean-reversion
    disabled per-symbol), router must not select that profile.
    """
    monkeypatch.setenv("DISABLE_STRATEGIES", "")
    monkeypatch.setenv("DISABLE_MEAN_REVERSION_SYMBOLS", "ETHUSDT")

    poc_magnet = ProfileSpec(
        id="poc_magnet",
        name="POC Magnet",
        description="test",
        conditions=ProfileConditions(),
        strategy_ids=["poc_magnet_scalp", "vwap_reversion"],  # both mean-reversion family
        tags=["poc", "mean_reversion"],
    )
    range_scalp = ProfileSpec(
        id="range_market_scalp",
        name="Range Scalp",
        description="test",
        conditions=ProfileConditions(),
        strategy_ids=["breakout_scalp"],  # not mean-reversion
        tags=["range"],
    )

    router = ProfileRouter()
    router.registry = _DummyRegistry([poc_magnet, range_scalp])

    selected = router.select_profiles(_ctx("ETHUSDT"), top_k=1, symbol="ETHUSDT")
    assert selected, "expected at least one profile to be selected"
    assert selected[0].profile_id == "range_market_scalp"


def test_profile_router_allows_symbol_specific_strategy_override(monkeypatch):
    monkeypatch.setenv("DISABLE_STRATEGIES", "")
    monkeypatch.setenv("DISABLE_MEAN_REVERSION_SYMBOLS", "ETHUSDT")
    monkeypatch.setenv("ENABLE_STRATEGIES_BY_SYMBOL", "ETHUSDT:poc_magnet_scalp")

    poc_magnet = ProfileSpec(
        id="poc_magnet",
        name="POC Magnet",
        description="test",
        conditions=ProfileConditions(),
        strategy_ids=["poc_magnet_scalp", "vwap_reversion"],
        tags=["poc", "mean_reversion"],
    )
    range_scalp = ProfileSpec(
        id="range_market_scalp",
        name="Range Scalp",
        description="test",
        conditions=ProfileConditions(),
        strategy_ids=["breakout_scalp"],  # not mean-reversion
        tags=["range"],
    )

    router = ProfileRouter()
    router.registry = _DummyRegistry([poc_magnet, range_scalp])

    selected = router.select_profiles(_ctx("ETHUSDT"), top_k=3, symbol="ETHUSDT")
    profile_ids = [item.profile_id for item in selected]
    assert "poc_magnet" in profile_ids


def test_profile_router_selects_spot_profile_in_europe_session(monkeypatch):
    monkeypatch.delenv("DISABLE_STRATEGIES", raising=False)
    monkeypatch.delenv("DISABLE_MEAN_REVERSION_SYMBOLS", raising=False)
    monkeypatch.delenv("ENABLE_STRATEGIES_BY_SYMBOL", raising=False)

    from quantgambit.deeptrader_core.strategies.chessboard.canonical_profiles import (
        SPOT_ACCUMULATION,
        SPOT_MEAN_REVERT,
        SPOT_TREND_FOLLOW,
        SPOT_VOL_BREAKOUT,
        SPOT_VALUE_DIP,
    )

    router = ProfileRouter()
    router.registry = _DummyRegistry(
        [
            SPOT_ACCUMULATION,
            SPOT_MEAN_REVERT,
            SPOT_TREND_FOLLOW,
            SPOT_VOL_BREAKOUT,
            SPOT_VALUE_DIP,
        ]
    )

    ctx = ContextVector(
        symbol="BTCUSDT",
        timestamp=1.0,
        price=69130.0,
        bid_depth_usd=1_200_000.0,
        ask_depth_usd=1_000_000.0,
        spread_bps=5.0,
        trades_per_second=4.0,
        book_age_ms=50.0,
        trade_age_ms=50.0,
        risk_mode="normal",
        session="europe",
        hour_utc=7,
        volatility_regime="normal",
        trend_direction="up",
        trend_strength=0.22,
        position_in_value="inside",
        rotation_factor=1.2,
        volume_imbalance=0.05,
        data_completeness=1.0,
    )

    selected = router.select_profiles(ctx, top_k=1, symbol="BTCUSDT")
    assert selected, "expected at least one spot profile to be selected in Europe session"
    assert selected[0].profile_id in {
        "spot_accumulation",
        "spot_trend_follow",
        "spot_mean_revert",
    }
