from quantgambit.deeptrader_core.strategies.high_vol_breakout import HighVolBreakout
from quantgambit.deeptrader_core.strategies.liquidity_fade_scalp import LiquidityFadeScalp
from quantgambit.deeptrader_core.strategies.liquidity_hunt import LiquidityHunt
from quantgambit.deeptrader_core.strategies.spread_capture_scalp import SpreadCaptureScalp
from quantgambit.deeptrader_core.strategies.vol_expansion import VolExpansion
from quantgambit.deeptrader_core.strategies.vwap_reversion import VWAPReversion
from quantgambit.deeptrader_core.types import AccountState, Features, Profile


def _account() -> AccountState:
    return AccountState(
        equity=10_000.0,
        daily_pnl=0.0,
        max_daily_loss=500.0,
        open_positions=0,
        symbol_open_positions=0,
        symbol_daily_pnl=0.0,
    )


def test_liquidity_hunt_accepts_lower_rotation_with_wider_wick_window() -> None:
    strategy = LiquidityHunt()
    profile = Profile(
        id="liquidity_hunt_profile",
        trend="flat",
        volatility="high",
        value_location="inside",
        session="us",
        risk_mode="normal",
    )
    features = Features(
        symbol="BTCUSDT",
        price=98_180.0,
        spread=0.001,
        rotation_factor=4.2,
        position_in_value="inside",
        value_area_low=98_000.0,
        value_area_high=102_000.0,
        point_of_control=100_000.0,
    )

    signal = strategy.generate_signal(
        features,
        _account(),
        profile,
        {"min_rotation_factor": 4.0, "min_wick_size_pct": 0.0035},
    )

    assert signal is not None
    assert signal.side == "long"


def test_vol_expansion_accepts_earlier_inside_value_expansion() -> None:
    strategy = VolExpansion()
    profile = Profile(
        id="vol_expansion_profile",
        trend="flat",
        volatility="high",
        value_location="inside",
        session="us",
        risk_mode="normal",
    )
    features = Features(
        symbol="ETHUSDT",
        price=3_050.0,
        spread=0.0015,
        rotation_factor=4.1,
        position_in_value="inside",
        value_area_low=2_980.0,
        value_area_high=3_100.0,
        point_of_control=3_000.0,
        atr_5m=111.0,
        atr_5m_baseline=100.0,
        ema_fast_15m=3_025.0,
        ema_slow_15m=3_000.0,
    )

    signal = strategy.generate_signal(
        features,
        _account(),
        profile,
        {"min_vwap_anchor_rr_ratio": 0.0},
    )

    assert signal is not None
    assert signal.side == "long"


def test_high_vol_breakout_accepts_moderate_breakout_conditions() -> None:
    strategy = HighVolBreakout()
    profile = Profile(
        id="high_vol_breakout_profile",
        trend="up",
        volatility="high",
        value_location="above",
        session="us",
        risk_mode="normal",
    )
    features = Features(
        symbol="SOLUSDT",
        price=181.0,
        spread=0.002,
        rotation_factor=3.2,
        position_in_value="above",
        value_area_low=176.0,
        value_area_high=180.7,
        atr_5m=151.0,
        atr_5m_baseline=100.0,
        trades_per_second=1.6,
        ema_fast_15m=180.9,
        ema_slow_15m=180.1,
    )

    signal = strategy.generate_signal(
        features,
        _account(),
        profile,
        {"min_vwap_anchor_rr_ratio": 0.0},
    )

    assert signal is not None
    assert signal.side == "long"


def test_liquidity_fade_scalp_accepts_smaller_cascade_reversal() -> None:
    strategy = LiquidityFadeScalp()
    profile = Profile(
        id="liquidity_fade_profile",
        trend="flat",
        volatility="high",
        value_location="inside",
        session="us",
        risk_mode="normal",
    )
    features = Features(
        symbol="BTCUSDT",
        price=100_000.0,
        spread=10.0,
        rotation_factor=0.0,
        position_in_value="inside",
        trades_per_second=3.2,
    )
    features.price_change_30s = -0.0013
    features.imb_1s = 0.1
    features.imb_30s = -0.2

    signal = strategy.generate_signal(
        features,
        _account(),
        profile,
        {"min_vwap_anchor_rr_ratio": 0.0},
    )

    assert signal is not None
    assert signal.side == "long"


def test_spread_capture_accepts_moderate_imbalance_on_tight_books() -> None:
    strategy = SpreadCaptureScalp()
    profile = Profile(
        id="spread_capture_profile",
        trend="flat",
        volatility="normal",
        value_location="inside",
        session="europe",
        risk_mode="normal",
    )
    features = Features(
        symbol="ETHUSDT",
        price=2_088.5,
        spread=0.020885,
        rotation_factor=0.0,
        position_in_value="inside",
        orderflow_imbalance=0.40,
        bid_depth_usd=500_000.0,
        ask_depth_usd=450_000.0,
    )

    signal = strategy.generate_signal(
        features,
        _account(),
        profile,
        {"min_imbalance": 0.35, "tp_spread_fraction": 4.0, "min_edge_bps": 0.2, "fee_bps": 0.0},
    )

    assert signal is not None
    assert signal.side == "short"


def test_vwap_reversion_accepts_ten_bps_deviation_in_range_regime() -> None:
    strategy = VWAPReversion()
    profile = Profile(
        id="vwap_reversion_profile",
        trend="flat",
        volatility="normal",
        value_location="inside",
        session="europe",
        risk_mode="normal",
    )
    features = Features(
        symbol="SOLUSDT",
        price=99.89,
        spread=0.0008,
        rotation_factor=1.8,
        position_in_value="inside",
        vwap=100.00,
    )

    signal = strategy.generate_signal(
        features,
        _account(),
        profile,
        {"min_vwap_anchor_rr_ratio": 0.0},
    )

    assert signal is not None
    assert signal.side == "long"


def test_vwap_reversion_enforces_min_reward_risk_ratio() -> None:
    strategy = VWAPReversion()
    profile = Profile(
        id="vwap_reversion_profile",
        trend="flat",
        volatility="normal",
        value_location="inside",
        session="europe",
        risk_mode="normal",
    )
    features = Features(
        symbol="BTCUSDT",
        price=100.20,
        spread=0.0004,
        rotation_factor=-1.6,
        position_in_value="inside",
        vwap=100.00,
    )

    signal = strategy.generate_signal(
        features,
        _account(),
        profile,
        {
            "stop_loss_pct": 0.006,
            "vwap_offset_pct": 0.002,
            "min_reward_risk_ratio": 1.25,
            "min_vwap_anchor_rr_ratio": 0.0,
        },
    )

    assert signal is not None
    assert signal.side == "short"
    stop_distance = abs(signal.entry_price - signal.stop_loss)
    take_profit_distance = abs(signal.entry_price - signal.take_profit)
    assert take_profit_distance >= stop_distance * 1.25


def test_vwap_reversion_skips_when_vwap_anchor_is_too_close() -> None:
    strategy = VWAPReversion()
    profile = Profile(
        id="vwap_reversion_profile",
        trend="flat",
        volatility="normal",
        value_location="inside",
        session="europe",
        risk_mode="normal",
    )
    features = Features(
        symbol="BTCUSDT",
        price=100.20,
        spread=0.0004,
        rotation_factor=-1.6,
        position_in_value="inside",
        vwap=100.00,
    )

    signal = strategy.generate_signal(
        features,
        _account(),
        profile,
        {
            "stop_loss_pct": 0.006,
            "vwap_offset_pct": 0.002,
            "min_reward_risk_ratio": 1.25,
            "min_vwap_anchor_rr_ratio": 0.85,
        },
    )

    assert signal is None
