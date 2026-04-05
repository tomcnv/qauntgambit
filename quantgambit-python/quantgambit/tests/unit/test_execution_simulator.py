from quantgambit.backtesting.simulator import (
    ExecutionSimulator,
    FeeModel,
    SlippageModel,
    TieredFeeModel,
    VolatilitySlippageModel,
)


def test_simulator_marks_to_market():
    sim = ExecutionSimulator(starting_equity=1000.0, fee_model=FeeModel(taker_bps=0.0))
    sim.apply_signal("BTC", "buy", 1.0, 100.0)
    result = sim.mark_to_market({"BTC": 110.0})
    assert result.equity == 1010.0


def test_simulator_realized_pnl_on_flip():
    sim = ExecutionSimulator(starting_equity=1000.0, fee_model=FeeModel(taker_bps=0.0))
    sim.apply_signal("BTC", "buy", 1.0, 100.0)
    sim.apply_signal("BTC", "sell", 1.0, 90.0)
    result = sim.mark_to_market({"BTC": 90.0})
    assert result.realized_pnl == -10.0


def test_simulator_report_tracks_win_rate_and_drawdown():
    sim = ExecutionSimulator(
        starting_equity=1000.0,
        fee_model=FeeModel(taker_bps=0.0),
        slippage_model=SlippageModel(slippage_bps=0.0),
    )
    sim.apply_signal("BTC", "buy", 1.0, 100.0)
    sim.apply_signal("BTC", "sell", 1.0, 110.0)
    sim.mark_to_market({"BTC": 110.0})
    report = sim.report()
    assert report.total_trades == 1
    assert sim.trades[0].total_fees >= 0.0
    assert report.win_rate == 1.0
    assert report.max_drawdown_pct >= 0.0
    assert report.total_return_pct >= 0.0
    assert report.avg_trade_pnl == report.realized_pnl


def test_simulator_accounts_for_fees_and_slippage():
    sim = ExecutionSimulator(
        starting_equity=1000.0,
        fee_model=FeeModel(taker_bps=10.0),
        slippage_model=SlippageModel(slippage_bps=10.0),
    )
    sim.apply_signal("BTC", "buy", 1.0, 100.0)
    sim.apply_signal("BTC", "sell", 1.0, 100.0)
    sim.mark_to_market({"BTC": 100.0})
    report = sim.report()
    assert report.total_trades == 1
    assert report.total_fees > 0.0
    assert report.avg_slippage_bps > 0.0
    assert report.total_return_pct != 0.0


def test_simulator_applies_depth_based_slippage():
    sim = ExecutionSimulator(
        starting_equity=1000.0,
        fee_model=FeeModel(taker_bps=0.0),
        slippage_model=SlippageModel(slippage_bps=0.0, impact_bps=50.0, max_slippage_bps=100.0),
    )
    sim.apply_signal("BTC", "buy", 1.0, 100.0, bid_depth_usd=100.0, ask_depth_usd=100.0)
    sim.apply_signal("BTC", "sell", 1.0, 100.0, bid_depth_usd=100.0, ask_depth_usd=100.0)
    sim.mark_to_market({"BTC": 100.0})
    trade = sim.trades[0]
    assert trade.entry_slippage_bps > 0.0
    assert trade.exit_slippage_bps > 0.0


def test_simulator_close_all_realizes_pnl():
    sim = ExecutionSimulator(starting_equity=1000.0, fee_model=FeeModel(taker_bps=0.0))
    sim.apply_signal("BTC", "buy", 1.0, 100.0)
    sim.close_all({"BTC": 110.0})
    report = sim.report()
    assert report.total_trades == 1


def test_tiered_fee_model_uses_notional_thresholds():
    model = TieredFeeModel(tiers=[(0.0, 5.0), (200.0, 2.0)], default_bps=10.0)
    small_fee = model.estimate_fee(100.0, 1.0)
    large_fee = model.estimate_fee(100.0, 3.0)
    assert round(small_fee, 6) == round(100.0 * 1.0 * 0.0005, 6)
    assert round(large_fee, 6) == round(100.0 * 3.0 * 0.0002, 6)


def test_simulator_applies_volatility_slippage():
    sim = ExecutionSimulator(
        starting_equity=1000.0,
        fee_model=FeeModel(taker_bps=0.0),
        slippage_model=VolatilitySlippageModel(
            slippage_bps=0.0,
            impact_bps=0.0,
            max_slippage_bps=100.0,
            volatility_bps=20.0,
            volatility_ratio_cap=2.0,
        ),
    )
    sim.apply_signal("BTC", "buy", 1.0, 100.0, volatility_ratio=2.0)
    sim.apply_signal("BTC", "sell", 1.0, 100.0, volatility_ratio=2.0)
    sim.mark_to_market({"BTC": 100.0})
    trade = sim.trades[0]
    assert trade.entry_slippage_bps > 0.0
    assert trade.exit_slippage_bps > 0.0


def test_simulator_uses_bid_ask_as_base_price():
    sim = ExecutionSimulator(
        starting_equity=1000.0,
        fee_model=FeeModel(taker_bps=0.0),
        slippage_model=SlippageModel(slippage_bps=0.0),
    )
    sim.apply_signal("BTC", "buy", 1.0, 100.0, bid=99.0, ask=101.0)
    sim.apply_signal("BTC", "sell", 1.0, 100.0, bid=99.0, ask=101.0)
    sim.mark_to_market({"BTC": 100.0})
    trade = sim.trades[0]
    assert trade.entry_price == 101.0
    assert trade.exit_price == 99.0
