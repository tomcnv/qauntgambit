from quantgambit.api.app import _evaluate_confirmation_readiness


def test_confirmation_readiness_ready_when_all_checks_pass():
    result = _evaluate_confirmation_readiness(
        comparison_count=1200,
        mismatch_count=12,
        contract_violations=0,
        min_comparisons=500,
        max_disagreement_pct=2.0,
        max_contract_violations=0,
    )
    assert result["ready_for_enforce"] is True
    assert result["checks"]["min_comparisons_met"] is True
    assert result["checks"]["disagreement_within_limit"] is True
    assert result["checks"]["contract_violations_within_limit"] is True


def test_confirmation_readiness_not_ready_when_disagreement_high():
    result = _evaluate_confirmation_readiness(
        comparison_count=600,
        mismatch_count=30,  # 5.0%
        contract_violations=0,
        min_comparisons=500,
        max_disagreement_pct=2.0,
        max_contract_violations=0,
    )
    assert result["ready_for_enforce"] is False
    assert result["checks"]["disagreement_within_limit"] is False

