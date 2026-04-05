from quantgambit.signals.pipeline import _resolve_action_policy_probabilities


def test_action_policy_probabilities_preserve_action_contract():
    payload = {
        "prediction_contract": "action_conditional_pnl_winprob",
        "p_long_win": 0.72,
        "p_short_win": 0.41,
    }
    resolved = _resolve_action_policy_probabilities(payload)
    assert resolved is not None
    assert resolved["normalized"] == 0.0
    assert resolved["directional_mass"] == 1.0
    assert resolved["p_long_eval"] == 0.72
    assert resolved["p_short_eval"] == 0.41
    assert resolved["p_star"] == 0.72


def test_action_policy_probabilities_normalize_multiclass_directional_mass():
    payload = {
        "prediction_contract": "tp_before_sl_within_horizon",
        "p_long_win": 0.08,
        "p_short_win": 0.32,
    }
    resolved = _resolve_action_policy_probabilities(payload)
    assert resolved is not None
    assert resolved["normalized"] == 1.0
    assert resolved["directional_mass"] == 0.40
    assert round(resolved["p_long_eval"], 4) == 0.2
    assert round(resolved["p_short_eval"], 4) == 0.8
    assert round(resolved["p_star"], 4) == 0.8
    assert round(resolved["margin"], 4) == 0.6


def test_action_policy_probabilities_handles_zero_directional_mass():
    payload = {
        "prediction_contract": "tp_before_sl_within_horizon",
        "p_long_win": 0.0,
        "p_short_win": 0.0,
    }
    resolved = _resolve_action_policy_probabilities(payload)
    assert resolved is not None
    assert resolved["normalized"] == 1.0
    assert resolved["directional_mass"] == 0.0
    assert resolved["p_star"] == 0.5
    assert resolved["margin"] == 0.0
