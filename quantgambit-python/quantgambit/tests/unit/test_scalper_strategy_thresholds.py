from quantgambit.deeptrader_core.strategies.europe_open_vol import EuropeOpenVol
from quantgambit.deeptrader_core.strategies.high_vol_breakout import HighVolBreakout
from quantgambit.deeptrader_core.strategies.breakout_scalp import BreakoutScalp
from quantgambit.deeptrader_core.strategies.low_vol_grind import LowVolGrind
from quantgambit.deeptrader_core.strategies.poc_magnet_scalp import POCMagnetScalp
from quantgambit.deeptrader_core.strategies.trend_pullback import TrendPullback
from quantgambit.deeptrader_core.strategies.spread_compression import SpreadCompression
from quantgambit.deeptrader_core.strategies.vwap_reversion import VWAPReversion
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
        id="range_market_scalp",
        trend="flat",
        volatility="normal",
        value_location="inside",
        session="us",
        risk_mode="normal",
    )


def test_vwap_reversion_allows_scalp_sized_deviation():
    signal = VWAPReversion().generate_signal(
        Features(
            symbol="BTCUSDT",
            price=100.0,
            vwap=100.25,
            spread=0.0002,
            rotation_factor=1.6,
            position_in_value="inside",
        ),
        _account(),
        _profile(),
        {"allow_longs": True, "allow_shorts": True},
    )
    assert signal is not None
    assert signal.side == "long"


def test_trend_pullback_allows_soft_live_pullback():
    signal = TrendPullback().generate_signal(
        Features(
            symbol="ETHUSDT",
            price=100.04,
            point_of_control=100.0,
            value_area_high=100.3,
            value_area_low=99.7,
            position_in_value="inside",
            rotation_factor=1.1,
            ema_fast_15m=100.16,
            ema_slow_15m=100.0,
            spread=0.0002,
        ),
        _account(),
        _profile(),
        {"allow_longs": True, "allow_shorts": True},
    )
    assert signal is not None
    assert signal.side == "long"


def test_europe_open_vol_allows_soft_live_open_breakout():
    from datetime import UTC, datetime

    signal = EuropeOpenVol().generate_signal(
        Features(
            symbol="BTCUSDT",
            price=101.2,
            value_area_high=101.0,
            value_area_low=99.0,
            point_of_control=100.0,
            position_in_value="above",
            rotation_factor=3.2,
            atr_5m=102.0,
            atr_5m_baseline=100.0,
            spread=0.0008,
            trades_per_second=1.7,
            timestamp=datetime(2024, 1, 15, 7, 30, tzinfo=UTC).timestamp(),
        ),
        _account(),
        Profile(
            id="europe_open",
            trend="flat",
            volatility="high",
            value_location="above",
            session="europe",
            risk_mode="normal",
        ),
        {"allow_longs": True, "allow_shorts": True},
    )
    assert signal is not None
    assert signal.side == "long"


def test_breakout_scalp_allows_moderate_rotation_breakout():
    signal = BreakoutScalp().generate_signal(
        Features(
            symbol="BTCUSDT",
            price=100.2,
            value_area_high=100.0,
            value_area_low=99.0,
            point_of_control=99.5,
            spread=0.0002,
            rotation_factor=3.8,
            atr_5m=95.0,
            atr_5m_baseline=100.0,
            position_in_value="inside",
        ),
        _account(),
        _profile(),
        {"allow_longs": True, "allow_shorts": True},
    )
    assert signal is not None
    assert signal.side == "long"


def test_high_vol_breakout_allows_moderate_rotation_and_volume():
    profile = Profile(
        id="high_vol_breakout_profile",
        trend="up",
        volatility="high",
        value_location="above",
        session="europe",
        risk_mode="normal",
    )
    signal = HighVolBreakout().generate_signal(
        Features(
            symbol="BTCUSDT",
            price=102.2,
            value_area_high=101.0,
            value_area_low=99.0,
            point_of_control=100.0,
            position_in_value="above",
            spread=0.003,
            rotation_factor=4.2,
            atr_5m=145.0,
            atr_5m_baseline=100.0,
            trades_per_second=2.2,
            ema_fast_15m=101.4,
            ema_slow_15m=100.0,
        ),
        _account(),
        profile,
        {"allow_longs": True, "allow_shorts": True},
    )
    assert signal is not None
    assert signal.side == "long"


def test_low_vol_grind_allows_modest_liquidity_and_poc_proximity():
    signal = LowVolGrind().generate_signal(
        Features(
            symbol="BTCUSDT",
            price=100.0,
            point_of_control=100.08,
            position_in_value="inside",
            spread=0.02,
            rotation_factor=0.0,
            atr_5m=75.0,
            atr_5m_baseline=100.0,
            trades_per_second=1.3,
            value_area_high=100.1,
            value_area_low=99.9,
        ),
        _account(),
        _profile(),
        {
            "allow_longs": True,
            "allow_shorts": True,
            "fee_bps": 2.0,
            "slippage_bps": 1.0,
        },
    )
    assert signal is not None


def test_poc_magnet_allows_near_poc_scalp_setup():
    signal = POCMagnetScalp().generate_signal(
        Features(
            symbol="ETHUSDT",
            price=2000.0,
            point_of_control=2002.4,
            distance_to_poc=-2.4,
            distance_to_poc_bps=12.0,
            position_in_value="inside",
            spread=0.0001,
            rotation_factor=1.4,
            orderflow_imbalance=-0.1,
        ),
        _account(),
        _profile(),
        {
            "allow_longs": True,
            "allow_shorts": True,
            "fee_bps": 2.0,
            "slippage_bps": 1.0,
        },
    )
    assert signal is not None
    assert signal.side == "long"


def test_spread_compression_allows_moderate_rotation_when_compressed():
    signal = SpreadCompression().generate_signal(
        Features(
            symbol="BTCUSDT",
            price=100.2,
            value_area_high=100.0,
            value_area_low=99.0,
            spread=0.00065,
            rotation_factor=2.7,
            ema_fast_15m=100.4,
            ema_slow_15m=100.1,
            position_in_value="inside",
        ),
        _account(),
        _profile(),
        {"allow_longs": True, "allow_shorts": True},
    )
    assert signal is not None
    assert signal.side == "long"
