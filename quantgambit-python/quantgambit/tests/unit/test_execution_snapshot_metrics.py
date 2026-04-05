from quantgambit.execution.execution_worker import _extract_snapshot_metrics


def test_extract_snapshot_metrics_includes_nested_prediction_fields():
    decision = {
        "timestamp": 1771149000.0,
        "risk_context": {"spread_bps": 2.1},
        "signal": {"p_hat": 0.62, "p_hat_source": "prediction_p_hat"},
        "prediction": {
            "direction": "up",
            "confidence": 0.64,
            "source": "onnx_v1",
            "provider": "onnx",
            "reject": False,
            "expert_id": "trend",
            "expert_routed": True,
            "calibration_applied": True,
            "p_up": 0.64,
            "p_down": 0.21,
            "p_flat": 0.15,
            "margin": 0.43,
            "entropy": 0.78,
        },
    }

    metrics = _extract_snapshot_metrics(decision)
    assert metrics is not None
    assert metrics["prediction_source"] == "onnx_v1"
    assert metrics["prediction_direction"] == "up"
    assert metrics["prediction_expert_id"] == "trend"
    assert metrics["prediction_expert_routed"] is True
    assert metrics["prediction_calibration_applied"] is True
    assert metrics["prediction"]["provider"] == "onnx"
    assert metrics["prediction"]["p_up"] == 0.64


def test_extract_snapshot_metrics_falls_back_to_flat_prediction_fields():
    decision = {
        "signal": {
            "prediction_confidence": 0.58,
            "prediction_direction": "down",
            "prediction_source": "onnx_v1",
        },
        "prediction_source": "onnx_v1",
        "prediction_direction": "down",
    }

    metrics = _extract_snapshot_metrics(decision)
    assert metrics is not None
    assert metrics["prediction_source"] == "onnx_v1"
    assert metrics["prediction_direction"] == "down"
    assert metrics["prediction_confidence"] == 0.58
