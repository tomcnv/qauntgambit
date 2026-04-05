from quantgambit.api.app import _extract_signal


def test_extract_signal_uses_prediction_confidence_over_candidate_confidence():
    payload = {
        "result": "COMPLETE",
        "signal_side": "long",
        "prediction_confidence": 0.74,
        "candidate": {"confidence": 0.55},
    }

    signal = _extract_signal(payload)

    assert signal["side"] == "long"
    assert signal["confidence"] == 0.74


def test_extract_signal_falls_back_to_candidate_confidence():
    payload = {
        "result": "COMPLETE",
        "signal_side": "short",
        "candidate": {"confidence": 0.61},
    }

    signal = _extract_signal(payload)

    assert signal["side"] == "short"
    assert signal["confidence"] == 0.61

