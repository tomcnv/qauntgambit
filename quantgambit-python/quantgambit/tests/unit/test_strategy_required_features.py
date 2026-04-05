from quantgambit.deeptrader_core.types import Features, AccountState, Profile
from quantgambit.deeptrader_core.strategies.vwap_reversion import VWAPReversion
from quantgambit.deeptrader_core.strategies.order_flow_imbalance import OrderFlowImbalance
from quantgambit.deeptrader_core.strategies.volume_profile_cluster import VolumeProfileCluster
from quantgambit.deeptrader_core.strategies.low_vol_grind import LowVolGrind
from quantgambit.deeptrader_core.strategies.spread_compression import SpreadCompression
from quantgambit.deeptrader_core.strategies.breakout_scalp import BreakoutScalp
from quantgambit.deeptrader_core.strategies.liquidity_hunt import LiquidityHunt
from quantgambit.deeptrader_core.strategies.mean_reversion_fade import MeanReversionFade
from quantgambit.deeptrader_core.strategies.trend_pullback import TrendPullback
from quantgambit.deeptrader_core.strategies.high_vol_breakout import HighVolBreakout
from quantgambit.deeptrader_core.strategies.vol_expansion import VolExpansion
from quantgambit.deeptrader_core.strategies.opening_range_breakout import OpeningRangeBreakout
from quantgambit.deeptrader_core.strategies.overnight_thin import OvernightThin
from quantgambit.deeptrader_core.strategies.europe_open_vol import EuropeOpenVol
from quantgambit.deeptrader_core.strategies.asia_range_scalp import AsiaRangeScalp
from quantgambit.deeptrader_core.strategies.drawdown_recovery import DrawdownRecovery
from quantgambit.deeptrader_core.strategies.max_profit_protection import MaxProfitProtection
from quantgambit.deeptrader_core.strategies.amt_value_area_rejection_scalp import AmtValueAreaRejectionScalp
from quantgambit.deeptrader_core.strategies.poc_magnet_scalp import POCMagnetScalp
from quantgambit.deeptrader_core.strategies.chop_zone_avoid import ChopZoneAvoid
from quantgambit.deeptrader_core.strategies.us_open_momentum import USOpenMomentum
from quantgambit.deeptrader_core.strategies.registry import STRATEGIES


def _account():
    return AccountState(
        equity=1000.0,
        daily_pnl=0.0,
        max_daily_loss=100.0,
        open_positions=0,
        symbol_open_positions=0,
        symbol_daily_pnl=0.0,
    )


def _profile(**overrides):
    base = dict(
        id="p1",
        trend="flat",
        volatility="normal",
        value_location="inside",
        session="us",
        risk_mode="normal",
    )
    base.update(overrides)
    return Profile(**base)


def _features(**overrides):
    base = dict(
        symbol="BTC",
        price=100.0,
        spread=0.0001,
        rotation_factor=5.0,
        position_in_value="inside",
        atr_5m=1.0,
        atr_5m_baseline=1.0,
        ema_fast_15m=101.0,
        ema_slow_15m=100.0,
        trades_per_second=5.0,
        orderbook_imbalance=0.8,
    )
    base.update(overrides)
    return Features(**base)


VALIDATED_STRATEGY_IDS = {
    "amt_value_area_rejection_scalp",
    "poc_magnet_scalp",
    "vwap_reversion",
    "order_flow_imbalance",
    "volume_profile_cluster",
    "low_vol_grind",
    "spread_compression",
    "breakout_scalp",
    "liquidity_hunt",
    "mean_reversion_fade",
    "trend_pullback",
    "high_vol_breakout",
    "vol_expansion",
    "opening_range_breakout",
    "overnight_thin",
    "europe_open_vol",
    "asia_range_scalp",
    "drawdown_recovery",
    "max_profit_protection",
    "chop_zone_avoid",
    "us_open_momentum",
}

EXPECTED_MISSING_STRATEGY_IDS: set[str] = {
    "liquidity_fade_scalp",
    "spread_capture_scalp",
    "test_signal_generator",  # Test strategy, no required features
    "spot_dip_accumulator",
    "spot_momentum_breakout",
    "spot_mean_reversion",
}


def test_strategy_gating_coverage_summary():
    registry_ids = set(STRATEGIES.keys())
    assert VALIDATED_STRATEGY_IDS.issubset(registry_ids)
    missing = registry_ids - VALIDATED_STRATEGY_IDS
    assert missing == EXPECTED_MISSING_STRATEGY_IDS


def test_vwap_reversion_requires_vwap():
    strategy = VWAPReversion()
    features = _features(vwap=None, point_of_control=100.0)
    signal = strategy.generate_signal(
        features=features,
        account=_account(),
        profile=_profile(volatility="normal", value_location="inside"),
        params={"allow_longs": True, "allow_shorts": True},
    )
    assert signal is None


def test_order_flow_imbalance_requires_orderflow_imbalance():
    strategy = OrderFlowImbalance()
    features = _features(orderflow_imbalance=None, orderbook_imbalance=0.9, trades_per_second=10.0)
    signal = strategy.generate_signal(
        features=features,
        account=_account(),
        profile=_profile(session="us"),
        params={"allow_longs": True, "allow_shorts": True, "min_volume_threshold": 1.0},
    )
    assert signal is None


def test_volume_profile_cluster_requires_poc():
    strategy = VolumeProfileCluster()
    features = _features(point_of_control=None)
    signal = strategy.generate_signal(
        features=features,
        account=_account(),
        profile=_profile(volatility="normal"),
        params={"allow_longs": True, "allow_shorts": True},
    )
    assert signal is None


def test_low_vol_grind_requires_poc():
    strategy = LowVolGrind()
    features = _features(point_of_control=None, atr_5m=0.4, atr_5m_baseline=1.0)
    signal = strategy.generate_signal(
        features=features,
        account=_account(),
        profile=_profile(volatility="low", value_location="inside"),
        params={"allow_longs": True, "allow_shorts": True},
    )
    assert signal is None


def test_spread_compression_requires_value_area():
    strategy = SpreadCompression()
    features = _features(value_area_low=None, value_area_high=None)
    signal = strategy.generate_signal(
        features=features,
        account=_account(),
        profile=_profile(volatility="low"),
        params={"allow_longs": True, "allow_shorts": True},
    )
    assert signal is None


def test_breakout_scalp_requires_value_area():
    strategy = BreakoutScalp()
    features = _features(value_area_high=None, value_area_low=None, point_of_control=100.0)
    signal = strategy.generate_signal(
        features=features,
        account=_account(),
        profile=_profile(volatility="high", value_location="inside"),
        params={"allow_longs": True, "allow_shorts": True},
    )
    assert signal is None


def test_liquidity_hunt_requires_value_area():
    strategy = LiquidityHunt()
    features = _features(value_area_high=None, value_area_low=None)
    signal = strategy.generate_signal(
        features=features,
        account=_account(),
        profile=_profile(volatility="normal"),
        params={"allow_longs": True, "allow_shorts": True},
    )
    assert signal is None


def test_mean_reversion_fade_requires_poc():
    strategy = MeanReversionFade()
    features = _features(point_of_control=None, distance_to_poc=2.0)
    signal = strategy.generate_signal(
        features=features,
        account=_account(),
        profile=_profile(trend="flat", volatility="normal", value_location="inside"),
        params={"allow_longs": True, "allow_shorts": True},
    )
    assert signal is None


def test_trend_pullback_requires_value_area():
    strategy = TrendPullback()
    features = _features(point_of_control=100.0, value_area_high=None, value_area_low=None)
    signal = strategy.generate_signal(
        features=features,
        account=_account(),
        profile=_profile(trend="up", volatility="normal", value_location="inside"),
        params={"allow_longs": True, "allow_shorts": True},
    )
    assert signal is None


def test_high_vol_breakout_requires_value_area():
    strategy = HighVolBreakout()
    features = _features(value_area_high=None, value_area_low=None)
    signal = strategy.generate_signal(
        features=features,
        account=_account(),
        profile=_profile(trend="up", volatility="high"),
        params={"allow_longs": True, "allow_shorts": True},
    )
    assert signal is None


def test_vol_expansion_requires_value_area():
    strategy = VolExpansion()
    features = _features(value_area_high=None, value_area_low=None)
    signal = strategy.generate_signal(
        features=features,
        account=_account(),
        profile=_profile(volatility="normal", value_location="inside"),
        params={"allow_longs": True, "allow_shorts": True},
    )
    assert signal is None


def test_vol_expansion_requires_poc_when_inside():
    strategy = VolExpansion()
    features = _features(point_of_control=None, value_area_high=101.0, value_area_low=99.0)
    signal = strategy.generate_signal(
        features=features,
        account=_account(),
        profile=_profile(volatility="normal", value_location="inside"),
        params={"allow_longs": True, "allow_shorts": True},
    )
    assert signal is None


def test_opening_range_breakout_requires_value_area():
    strategy = OpeningRangeBreakout()
    features = _features(value_area_high=None, value_area_low=None)
    signal = strategy.generate_signal(
        features=features,
        account=_account(),
        profile=_profile(session="us"),
        params={"allow_longs": True, "allow_shorts": True},
    )
    assert signal is None


def test_overnight_thin_requires_value_area():
    strategy = OvernightThin()
    features = _features(value_area_high=None, value_area_low=None)
    signal = strategy.generate_signal(
        features=features,
        account=_account(),
        profile=_profile(session="overnight"),
        params={"allow_longs": True, "allow_shorts": True},
    )
    assert signal is None


def test_europe_open_vol_requires_value_area():
    strategy = EuropeOpenVol()
    features = _features(
        value_area_high=None,
        value_area_low=None,
        timestamp=7 * 3600,
        atr_5m=1.2,
        atr_5m_baseline=1.0,
    )
    signal = strategy.generate_signal(
        features=features,
        account=_account(),
        profile=_profile(session="europe", volatility="high"),
        params={"allow_longs": True, "allow_shorts": True},
    )
    assert signal is None


def test_asia_range_scalp_requires_poc():
    strategy = AsiaRangeScalp()
    features = _features(point_of_control=None)
    signal = strategy.generate_signal(
        features=features,
        account=_account(),
        profile=_profile(session="asia", volatility="low"),
        params={"allow_longs": True, "allow_shorts": True},
    )
    assert signal is None


def test_drawdown_recovery_requires_value_area():
    strategy = DrawdownRecovery()
    features = _features(value_area_high=None, value_area_low=None)
    account = AccountState(
        equity=1000.0,
        daily_pnl=-200.0,
        max_daily_loss=-100.0,
        open_positions=0,
        symbol_open_positions=0,
        symbol_daily_pnl=0.0,
    )
    signal = strategy.generate_signal(
        features=features,
        account=account,
        profile=_profile(volatility="normal", value_location="above"),
        params={"allow_longs": True, "allow_shorts": True},
    )
    assert signal is None


def test_max_profit_protection_requires_poc():
    strategy = MaxProfitProtection()
    features = _features(point_of_control=None)
    account = AccountState(
        equity=1000.0,
        daily_pnl=50.0,
        max_daily_loss=100.0,
        open_positions=0,
        symbol_open_positions=0,
        symbol_daily_pnl=0.0,
    )
    signal = strategy.generate_signal(
        features=features,
        account=account,
        profile=_profile(trend="up", volatility="normal", value_location="inside"),
        params={"allow_longs": True, "allow_shorts": True},
    )
    assert signal is None


def test_amt_value_area_rejection_requires_distances():
    strategy = AmtValueAreaRejectionScalp()
    features = _features(
        position_in_value="below",
        rotation_factor=10.0,
        distance_to_val=None,
        distance_to_vah=1.0,
        distance_to_poc=1.0,
    )
    signal = strategy.generate_signal(
        features=features,
        account=_account(),
        profile=_profile(volatility="normal", value_location="below"),
        params={"allow_longs": True, "allow_shorts": True},
    )
    assert signal is None


def test_poc_magnet_scalp_requires_distance_to_poc():
    strategy = POCMagnetScalp()
    features = _features(
        position_in_value="inside",
        distance_to_poc=None,
        rotation_factor=2.0,
    )
    signal = strategy.generate_signal(
        features=features,
        account=_account(),
        profile=_profile(volatility="normal", value_location="inside"),
        params={"allow_longs": True, "allow_shorts": True},
    )
    assert signal is None


def test_chop_zone_avoid_requires_rotation():
    strategy = ChopZoneAvoid()
    features = _features(rotation_factor=None)
    signal = strategy.generate_signal(
        features=features,
        account=_account(),
        profile=_profile(volatility="low", value_location="inside"),
        params={},
    )
    assert signal is None


def test_us_open_momentum_requires_ema():
    strategy = USOpenMomentum()
    features = _features(
        timestamp=12 * 3600,
        ema_fast_15m=None,
        ema_slow_15m=100.0,
        trades_per_second=10.0,
        rotation_factor=10.0,
    )
    signal = strategy.generate_signal(
        features=features,
        account=_account(),
        profile=_profile(trend="up", volatility="normal", session="us"),
        params={"allow_longs": True, "allow_shorts": True, "extended_window": True},
    )
    assert signal is None
