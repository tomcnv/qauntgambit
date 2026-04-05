import asyncio

from quantgambit.config.loss_prevention import load_loss_prevention_config
from quantgambit.signals.decision_engine import DecisionEngine, DecisionInput


def test_decision_engine_rejects_without_features():
    loss_prevention_config = load_loss_prevention_config()
    engine = DecisionEngine(
        ev_gate_config=loss_prevention_config.ev_gate,
        ev_position_sizer_config=loss_prevention_config.ev_position_sizer,
        cost_data_quality_config=loss_prevention_config.cost_data_quality,
    )
    decision_input = DecisionInput(symbol="BTC", market_context={}, features={})
    result = asyncio.run(engine.decide(decision_input))
    assert result is False


def test_decision_engine_rejects_risk_block():
    loss_prevention_config = load_loss_prevention_config()
    engine = DecisionEngine(
        ev_gate_config=loss_prevention_config.ev_gate,
        ev_position_sizer_config=loss_prevention_config.ev_position_sizer,
        cost_data_quality_config=loss_prevention_config.cost_data_quality,
    )
    decision_input = DecisionInput(symbol="BTC", market_context={}, features={"signal": True}, risk_ok=False)
    result = asyncio.run(engine.decide(decision_input))
    assert result is False
