from quantgambit.signals.stages.ev_gate import CostEstimator


def test_cost_estimator_uses_env_fee_config(monkeypatch):
    estimator = CostEstimator()

    monkeypatch.setenv("EV_GATE_FEE_CONFIG", "bybit_regular")
    estimator._ensure_env_fee_model()

    # Bybit regular taker fee rate should be wired (0.055% = 0.00055).
    # This test covers late dotenv/env application after CostEstimator construction.
    assert estimator.fee_model.config.taker_fee_rate == 0.00055
