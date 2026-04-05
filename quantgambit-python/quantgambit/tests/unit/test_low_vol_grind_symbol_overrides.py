import os


def test_low_vol_grind_symbol_overrides_allow_btc_signal(monkeypatch):
    """
    BTC previously got no entries because range_market_scalp disables mean reversion for BTC
    and low_vol_grind was both (a) too strict and (b) could be disabled by missing allow flags.

    This test asserts env overrides can loosen low_vol_grind for BTC without touching other symbols.
    """
    monkeypatch.setenv("LOW_VOL_GRIND_MAX_ATR_RATIO_BY_SYMBOL", "BTCUSDT:1.0")
    monkeypatch.setenv("LOW_VOL_GRIND_POC_PROXIMITY_PCT_BY_SYMBOL", "BTCUSDT:0.0020")

    from quantgambit.deeptrader_core.strategies.low_vol_grind import LowVolGrind
    from quantgambit.deeptrader_core.types import Features, AccountState, Profile

    # 25 bps away from POC gives enough edge after costs (~8 bps) + min_edge (5 bps)
    price = 66800.0
    poc = price * (1.0 + 0.0025)  # +25 bps

    features = Features(
        symbol="BTCUSDT",
        price=price,
        spread=price * 0.000001,  # ~0.01 bps
        rotation_factor=0.0,
        position_in_value="inside",
        timestamp=0.0,
        distance_to_val=None,
        distance_to_vah=None,
        distance_to_poc=(price - poc),
        value_area_low=None,
        value_area_high=None,
        point_of_control=poc,
        ema_fast_15m=0.0,
        ema_slow_15m=0.0,
        atr_5m=110.0,
        atr_5m_baseline=114.0,  # atr_ratio ~0.965 <= 1.0 override
        vwap=0.0,
        trades_per_second=5.0,
        orderbook_imbalance=0.0,
        orderflow_imbalance=0.0,
        bid_depth_usd=1_000_000.0,
        ask_depth_usd=1_000_000.0,
    )
    profile = Profile(
        id="range_market_scalp",
        trend="flat",
        volatility="normal",  # strategy should not depend on this string
        value_location="inside",
        session="us",
        risk_mode="normal",
    )
    account = AccountState(
        equity=100_000.0,
        daily_pnl=0.0,
        max_daily_loss=0.0,
        open_positions=0,
        symbol_open_positions=0,
        symbol_daily_pnl=0.0,
    )
    params = {
        "max_atr_ratio": 0.8,  # would reject without BTC override
        "min_edge_bps": 5.0,
        "fee_bps": 6.0,
        "slippage_bps": 2.0,
        # NOTE: no allow_longs/allow_shorts keys here on purpose (should default to True)
    }

    sig = LowVolGrind().generate_signal(features, account, profile, params)
    assert sig is not None
    assert sig.symbol == "BTCUSDT"

