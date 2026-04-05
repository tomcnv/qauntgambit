from quantgambit.api.quant_endpoints import _infer_score_gate_mode, _is_non_problem_decision_rejection


def test_infer_score_gate_mode_blocked_only():
    assert _infer_score_gate_mode({"blocked": 25}) == "block"


def test_infer_score_gate_mode_fallback_only():
    assert _infer_score_gate_mode({"fallback": 12}) == "fallback_heuristic"


def test_infer_score_gate_mode_mixed():
    assert _infer_score_gate_mode({"fallback": 5, "blocked": 3}) == "mixed"


def test_infer_score_gate_mode_default_when_no_counts():
    assert _infer_score_gate_mode({}, env_default="fallback_heuristic") == "fallback_heuristic"


def test_non_problem_decision_rejection_allows_warmup_and_insufficient_data_states():
    assert _is_non_problem_decision_rejection("warmup")
    assert _is_non_problem_decision_rejection("insufficient_depth")
    assert _is_non_problem_decision_rejection("low_data_quality")
    assert _is_non_problem_decision_rejection("profile_warmup_pending")


def test_non_problem_decision_rejection_keeps_real_blockers_degraded():
    assert not _is_non_problem_decision_rejection("kill_switch_active")
    assert not _is_non_problem_decision_rejection("orderbook_stale:BTCUSDT")
