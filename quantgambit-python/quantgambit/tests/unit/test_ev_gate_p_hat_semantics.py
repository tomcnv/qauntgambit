from quantgambit.signals.pipeline import StageContext
from quantgambit.signals.stages.ev_gate import EVGateStage


def test_ev_gate_does_not_treat_prediction_confidence_as_p_hat():
    """
    EVGate must not silently treat prediction confidence as calibrated P(win).
    If p_hat is missing from the signal, EVGate must use conservative defaults
    rather than mapping from prediction["confidence"].
    """
    stage = EVGateStage()

    signal = {
        "strategy_id": "range_market_scalp",
        "meta_reason": "test",
        "side": "long",
        "entry_price": 100.0,
        "sl_distance_bps": 25.0,
        "tp_distance_bps": 50.0,
    }
    ctx = StageContext(
        symbol="ETHUSDT",
        data={
            "prediction": {"confidence": 0.9, "source": "heuristic_v1"},
            "market_context": {"mid_price": 100.0},
            "features": {},
        },
    )

    stage._compute_defaults(ctx, signal)

    assert signal.get("p_hat_source") == "uncalibrated_conservative"
    assert 0.0 <= float(signal.get("p_hat")) <= 1.0
    assert float(signal.get("p_hat")) != 0.9


def test_ev_gate_handles_non_dict_strategy_calibration(monkeypatch):
    stage = EVGateStage()

    class _Cost:
        spread_bps = 0.1
        fee_bps = 6.0
        slippage_bps = 1.0
        adverse_selection_bps = 0.5
        total_bps = 7.6

    monkeypatch.setattr(stage, "_get_book_age_ms", lambda _ctx: 0.0)
    monkeypatch.setattr(stage, "_get_spread_age_ms", lambda _ctx: 0.0)
    monkeypatch.setattr(stage.cost_estimator, "estimate", lambda **kwargs: _Cost())

    signal = {
        "strategy_id": "mean_reversion_fade",
        "meta_reason": "test",
        "side": "long",
        "entry_price": 100.0,
        "sl_distance_bps": 30.0,
        "tp_distance_bps": 60.0,
        "p_hat": 0.55,
    }
    ctx = StageContext(
        symbol="ETHUSDT",
        data={
            "prediction": {"confidence": 0.6},
            "market_context": {"mid_price": 100.0, "n_trades": 0, "calibration_reliability": 0.0},
            "features": {},
            # Regression: this used to crash with `'int' object has no attribute 'get'`.
            "calibration": {"ETHUSDT:mean_reversion_fade": 1},
        },
    )

    captured = {}

    class _FakeCalStatus:
        def __init__(self):
            from quantgambit.signals.services.calibration_state import CalibrationState
            self.state = CalibrationState.COLD
            self.p_effective = 0.52
            self.reliability = 0.5
            self.size_multiplier = 0.7
            self.min_edge_bps_adjustment = 0.0

    def _fake_eval(strategy_id, n_trades, p_observed, reliability):
        captured["strategy_id"] = strategy_id
        captured["n_trades"] = n_trades
        captured["p_observed"] = p_observed
        captured["reliability"] = reliability
        return _FakeCalStatus()

    monkeypatch.setattr("quantgambit.signals.stages.ev_gate.evaluate_calibration", _fake_eval)

    result = stage._evaluate(ctx, signal)

    assert result is not None
    assert result.decision in {"ACCEPT", "REJECT"}
    assert captured["n_trades"] == 1


def test_ev_gate_applies_config_cost_floors(monkeypatch):
    stage = EVGateStage()

    class _Cost:
        spread_bps = 0.1
        fee_bps = 11.0
        slippage_bps = 0.2
        adverse_selection_bps = 0.3
        total_bps = 11.6

    stage.config.min_slippage_bps = 2.0
    stage.config.adverse_selection_bps = 1.5

    monkeypatch.setattr(stage, "_get_book_age_ms", lambda _ctx: 0.0)
    monkeypatch.setattr(stage, "_get_spread_age_ms", lambda _ctx: 0.0)
    monkeypatch.setattr(stage.cost_estimator, "estimate", lambda **kwargs: _Cost())

    signal = {
        "strategy_id": "mean_reversion_fade",
        "meta_reason": "test",
        "side": "long",
        "entry_price": 100.0,
        "sl_distance_bps": 30.0,
        "tp_distance_bps": 60.0,
        "p_hat": 0.55,
    }
    ctx = StageContext(
        symbol="ETHUSDT",
        data={
            "prediction": {"confidence": 0.6},
            "market_context": {"mid_price": 100.0, "n_trades": 0, "calibration_reliability": 0.0},
            "features": {},
        },
    )

    result = stage._evaluate(ctx, signal)

    assert result.slippage_bps == 2.0
    assert result.adverse_selection_bps == 1.5
    assert result.total_cost_bps == 0.1 + 11.0 + 2.0 + 1.5


def test_ev_gate_rejects_when_expected_net_edge_below_min(monkeypatch):
    stage = EVGateStage()

    class _Cost:
        spread_bps = 0.1
        fee_bps = 11.0
        slippage_bps = 1.0
        adverse_selection_bps = 0.5
        total_bps = 12.6

    stage.config.min_expected_edge_bps = 8.5
    monkeypatch.setenv("EV_GATE_COST_MULTIPLE", "0")

    monkeypatch.setattr(stage, "_get_book_age_ms", lambda _ctx: 0.0)
    monkeypatch.setattr(stage, "_get_spread_age_ms", lambda _ctx: 0.0)
    monkeypatch.setattr(stage.cost_estimator, "estimate", lambda **kwargs: _Cost())
    monkeypatch.setattr(
        "quantgambit.signals.stages.ev_gate.evaluate_calibration",
        lambda **kwargs: type(
            "_CalStatus",
            (),
            {
                "state": type("_S", (), {"value": "ok"})(),
                "p_effective": 0.55,
                "reliability": 1.0,
                "size_multiplier": 1.0,
                "min_edge_bps_adjustment": 0.0,
            },
        )(),
    )

    signal = {
        "strategy_id": "mean_reversion_fade",
        "meta_reason": "test",
        "side": "long",
        "entry_price": 100.0,
        "sl_distance_bps": 30.0,
        "tp_distance_bps": 60.0,
        "p_hat": 0.55,
    }
    ctx = StageContext(
        symbol="ETHUSDT",
        data={
            "prediction": {"confidence": 0.6},
            "market_context": {"mid_price": 100.0, "n_trades": 500, "calibration_reliability": 1.0},
            "features": {},
        },
    )

    result = stage._evaluate(ctx, signal)

    assert result.decision == "REJECT"
    assert result.reject_code is not None
    assert result.reject_code.value == "EXPECTED_EDGE_BELOW_MIN"
    assert result.expected_net_edge_bps < stage.config.min_expected_edge_bps


def test_ev_gate_symbol_specific_min_expected_edge_override(monkeypatch):
    stage = EVGateStage()

    class _Cost:
        spread_bps = 0.1
        fee_bps = 2.0
        slippage_bps = 0.5
        adverse_selection_bps = 0.5
        total_bps = 3.1

    stage.config.min_expected_edge_bps = 0.2
    stage.config.min_expected_edge_bps_by_symbol = {"ETHUSDT": 20.0}
    monkeypatch.setenv("EV_GATE_COST_MULTIPLE", "0")

    monkeypatch.setattr(stage, "_get_book_age_ms", lambda _ctx: 0.0)
    monkeypatch.setattr(stage, "_get_spread_age_ms", lambda _ctx: 0.0)
    monkeypatch.setattr(stage.cost_estimator, "estimate", lambda **kwargs: _Cost())
    monkeypatch.setattr(
        "quantgambit.signals.stages.ev_gate.evaluate_calibration",
        lambda **kwargs: type(
            "_CalStatus",
            (),
            {
                "state": type("_S", (), {"value": "ok"})(),
                "p_effective": 0.55,
                "reliability": 1.0,
                "size_multiplier": 1.0,
                "min_edge_bps_adjustment": 0.0,
            },
        )(),
    )

    signal = {
        "strategy_id": "mean_reversion_fade",
        "meta_reason": "test",
        "side": "long",
        "entry_price": 100.0,
        "sl_distance_bps": 30.0,
        "tp_distance_bps": 60.0,
        "p_hat": 0.55,
    }
    ctx = StageContext(
        symbol="ETHUSDT",
        data={
            "prediction": {"confidence": 0.6},
            "market_context": {"mid_price": 100.0, "n_trades": 500, "calibration_reliability": 1.0},
            "features": {},
        },
    )

    result = stage._evaluate(ctx, signal)

    assert result.decision == "REJECT"
    assert result.reject_code is not None
    assert result.reject_code.value == "EXPECTED_EDGE_BELOW_MIN"
    assert result.min_expected_edge_bps == 20.0


def test_ev_gate_spread_age_prefers_orderbook_freshness_over_trade_timestamp():
    stage = EVGateStage()
    ctx = StageContext(
        symbol="BTCUSDT",
        data={
            "market_context": {
                "book_timestamp_ms": 100_000.0,
                "timestamp_ms": 100_000.0,
                "feed_staleness": {"orderbook": 0.0},
            },
            "features": {},
        },
    )

    spread_age_ms = stage._get_spread_age_ms(ctx)

    assert spread_age_ms is not None
    assert spread_age_ms == 0.0


def test_ev_gate_spread_age_prefers_feed_staleness_over_book_recv_timestamp():
    stage = EVGateStage()
    ctx = StageContext(
        symbol="BTCUSDT",
        data={
            "market_context": {
                "book_recv_ms": 1.0,
                "feed_staleness": {"orderbook": 0.0},
            },
            "features": {},
        },
    )

    spread_age_ms = stage._get_spread_age_ms(ctx)

    assert spread_age_ms is not None
    assert spread_age_ms == 0.0
