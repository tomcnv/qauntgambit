from quantgambit.deeptrader_core.strategies.spot_mean_reversion import SpotMeanReversion
from quantgambit.deeptrader_core.types import AccountState, Features, Profile


def _account() -> AccountState:
    return AccountState(
        equity=25_000.0,
        daily_pnl=0.0,
        max_daily_loss=-1_000.0,
        open_positions=0,
        symbol_open_positions=0,
        symbol_daily_pnl=0.0,
    )


def _profile() -> Profile:
    return Profile(
        id="spot_mean_revert",
        trend="flat",
        volatility="normal",
        value_location="inside",
        session="europe",
        risk_mode="normal",
    )


def test_spot_mean_reversion_allows_live_like_europe_session_entry(monkeypatch):
    monkeypatch.setattr(
        "quantgambit.deeptrader_core.strategies.spot_mean_reversion.get_sentiment",
        lambda symbol: 0.0,
    )
    monkeypatch.setattr(
        "quantgambit.deeptrader_core.strategies.spot_mean_reversion.get_prediction",
        lambda symbol: {"direction": "up", "reject": False, "confidence": 0.62},
    )

    signal = SpotMeanReversion().generate_signal(
        Features(
            symbol="BTCUSDT",
            price=100.0,
            spread=0.0002,
            position_in_value="inside",
            distance_to_poc=-0.03,
            rotation_factor=0.0,
            trend_strength=0.22,
            bid_depth_usd=1_200_000.0,
            ask_depth_usd=950_000.0,
        ),
        _account(),
        _profile(),
        {
            "stop_loss_pct": 0.005,
            "take_profit_pct": 0.004,
            "risk_per_trade_pct": 0.03,
            "max_spread": 0.003,
            "min_poc_distance_bps": 0.5,
            "max_poc_distance_bps": 150.0,
            "max_trend_strength": 0.35,
            "sentiment_floor": -0.5,
        },
    )

    assert signal is not None
    assert signal.side == "long"


def test_spot_mean_reversion_allows_moderately_lighter_bid_depth(monkeypatch):
    monkeypatch.setattr(
        "quantgambit.deeptrader_core.strategies.spot_mean_reversion.get_sentiment",
        lambda symbol: 0.0,
    )
    monkeypatch.setattr(
        "quantgambit.deeptrader_core.strategies.spot_mean_reversion.get_prediction",
        lambda symbol: {"direction": "up", "reject": False, "confidence": 0.6},
    )

    signal = SpotMeanReversion().generate_signal(
        Features(
            symbol="ETHUSDT",
            price=100.0,
            spread=0.0003,
            position_in_value="inside",
            distance_to_poc=-0.02,
            rotation_factor=0.0,
            trend_strength=0.3,
            bid_depth_usd=750_000.0,
            ask_depth_usd=1_000_000.0,
        ),
        _account(),
        _profile(),
        {
            "max_spread": 0.004,
            "max_trend_strength": 0.45,
        },
    )

    assert signal is not None
    assert signal.side == "long"
