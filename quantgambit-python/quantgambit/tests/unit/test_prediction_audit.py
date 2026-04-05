from quantgambit.signals.prediction_audit import build_directional_fields


def test_build_directional_fields_with_winprob_and_side_alignment():
    fields = build_directional_fields(
        {
            "direction": "up",
            "source": "onnx_action_v1",
            "p_long_win": 0.73,
            "p_short_win": 0.27,
        },
        "buy",
    )
    assert fields["prediction_present"] is True
    assert fields["prediction_direction"] == "up"
    assert fields["prediction_source"] == "onnx_action_v1"
    assert fields["model_side"] == "long"
    assert fields["signal_side"] == "long"
    assert fields["direction_alignment_match"] is True
    assert abs(fields["p_margin"] - 0.46) < 1e-9


def test_build_directional_fields_without_prediction():
    fields = build_directional_fields(None, "sell")
    assert fields["prediction_present"] is False
    assert fields["signal_side"] == "short"
    assert fields["direction_alignment_match"] is None
