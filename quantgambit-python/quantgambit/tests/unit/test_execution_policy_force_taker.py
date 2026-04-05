import os

from quantgambit.execution.execution_policy import ExecutionPolicy


def test_execution_policy_force_taker_overrides_maker_probs(monkeypatch):
    monkeypatch.setenv("EXECUTION_POLICY_FORCE_TAKER", "true")
    policy = ExecutionPolicy()

    plan = policy.plan_execution(strategy_id="low_vol_grind")

    assert plan.p_entry_maker == 0.0
    assert plan.p_exit_maker == 0.0
    assert plan.entry_urgency == "immediate"
    assert plan.exit_urgency == "immediate"

