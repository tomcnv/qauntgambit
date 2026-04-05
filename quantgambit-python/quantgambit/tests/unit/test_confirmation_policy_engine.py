import pytest

from quantgambit.signals.confirmation import (
    ConfirmationPolicyConfig,
    ConfirmationPolicyEngine,
    ConfirmationWeights,
    StrategyPolicyOverride,
)


def test_entry_hard_guard_blocks_risk_mode_off() -> None:
    engine = ConfirmationPolicyEngine(
        ConfirmationPolicyConfig(mode="enforce", enabled=True)
    )
    result = engine.evaluate_entry(
        side="long",
        flow=1.0,
        trend=0.2,
        market_context={"risk_mode": "off"},
        strategy_id="s1",
        requires_flow_reversal=True,
        required_flow_direction=None,
        max_adverse_trend=0.7,
    )
    assert result.confirm is False
    assert "guard_risk_mode_off" in result.failed_hard_guards


def test_weighted_confidence_entry_threshold() -> None:
    engine = ConfirmationPolicyEngine(
        ConfirmationPolicyConfig(
            mode="enforce",
            enabled=True,
            weights=ConfirmationWeights(trend=2.0, flow=1.0, risk_stability=1.0),
        )
    )
    result = engine.evaluate_entry(
        side="long",
        flow=1.0,
        trend=0.2,
        market_context={"volatility_regime": "normal", "volatility_percentile": 0.4},
        strategy_id="s1",
        requires_flow_reversal=True,
        required_flow_direction=None,
        max_adverse_trend=0.7,
    )
    assert result.confirm is True
    assert result.confidence == pytest.approx(1.0, rel=1e-6)


def test_exit_requires_two_of_three_by_default() -> None:
    engine = ConfirmationPolicyEngine(
        ConfirmationPolicyConfig(mode="enforce", enabled=True)
    )
    result = engine.evaluate_exit_non_emergency(
        side="long",
        pnl_pct=-0.5,
        current_price=99.5,
        entry_price=100.0,
        market_context={
            "trend_bias": "short",
            "trend_confidence": 0.4,
            "orderflow_imbalance": -0.8,
            "volatility_regime": "normal",
            "volatility_percentile": 0.4,
        },
        strategy_id="s1",
    )
    assert result.confirm is True
    assert sum(1 for v in result.evidence_votes.values() if v) >= 2


def test_strategy_override_bounds_rejected() -> None:
    config = ConfirmationPolicyConfig(
        mode="enforce",
        enabled=True,
        strategy_overrides={
            "s1": StrategyPolicyOverride(
                weights=ConfirmationWeights(trend=9.0, flow=1.0, risk_stability=1.0)
            )
        },
    )
    engine = ConfirmationPolicyEngine(config)
    with pytest.raises(ValueError, match="out of bounds"):
        engine.evaluate_entry(
            side="long",
            flow=1.0,
            trend=0.1,
            market_context={"volatility_regime": "normal", "volatility_percentile": 0.3},
            strategy_id="s1",
            requires_flow_reversal=True,
            required_flow_direction=None,
            max_adverse_trend=0.7,
        )
