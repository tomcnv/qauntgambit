from quantgambit.signals.pipeline import StageContext
from quantgambit.signals.pipeline import _inject_signal_identity
from quantgambit.deeptrader_core.types import StrategySignal


def test_inject_signal_identity_sets_p_hat_from_prediction_probs_long():
    signal = {"side": "long", "strategy_id": "range_market_scalp", "profile_id": "p1"}
    ctx = StageContext(
        symbol="ETHUSDT",
        data={"prediction": {"probs": {"up": 0.77, "down": 0.10, "flat": 0.13}}},
        profile_id="p1",
        signal=signal,
    )
    _inject_signal_identity(signal, ctx)
    assert signal.get("p_hat_source") == "prediction_p_hat"
    assert signal.get("p_hat") == 0.77


def test_inject_signal_identity_sets_p_hat_from_prediction_probs_short():
    signal = {"side": "short", "strategy_id": "range_market_scalp", "profile_id": "p1"}
    ctx = StageContext(
        symbol="ETHUSDT",
        data={"prediction": {"probs": {"up": 0.20, "down": 0.63, "flat": 0.17}}},
        profile_id="p1",
        signal=signal,
    )
    _inject_signal_identity(signal, ctx)
    assert signal.get("p_hat_source") == "prediction_p_hat"
    assert signal.get("p_hat") == 0.63


def test_inject_signal_identity_sets_p_hat_on_strategy_signal_object():
    signal = StrategySignal(
        strategy_id="range_market_scalp",
        symbol="ETHUSDT",
        side="long",
        size=1.0,
        entry_price=100.0,
        stop_loss=99.0,
        take_profit=101.0,
        meta_reason="test",
        profile_id="p1",
    )
    ctx = StageContext(
        symbol="ETHUSDT",
        data={"prediction": {"probs": {"up": 0.66, "down": 0.20, "flat": 0.14}}},
        profile_id="p1",
        signal=None,
    )
    _inject_signal_identity(signal, ctx)
    assert signal.p_hat_source == "prediction_p_hat"
    assert signal.p_hat == 0.66


def test_inject_signal_identity_prefers_explicit_prediction_p_hat():
    signal = {"side": "short", "strategy_id": "range_market_scalp", "profile_id": "p1"}
    ctx = StageContext(
        symbol="ETHUSDT",
        data={
            "prediction": {
                "p_hat": 0.58,
                "p_hat_source": "fallback_heuristic",
                "probs": {"up": 0.22, "down": 0.71, "flat": 0.07},
            }
        },
        profile_id="p1",
        signal=signal,
    )
    _inject_signal_identity(signal, ctx)
    assert signal.get("p_hat") == 0.58
    assert signal.get("p_hat_source") == "fallback_heuristic"


def test_inject_signal_identity_defaults_prediction_p_hat_source_when_missing():
    signal = {"side": "long", "strategy_id": "range_market_scalp", "profile_id": "p1"}
    ctx = StageContext(
        symbol="ETHUSDT",
        data={"prediction": {"p_hat": 0.61}},
        profile_id="p1",
        signal=signal,
    )
    _inject_signal_identity(signal, ctx)
    assert signal.get("p_hat") == 0.61
    assert signal.get("p_hat_source") == "prediction_p_hat"
