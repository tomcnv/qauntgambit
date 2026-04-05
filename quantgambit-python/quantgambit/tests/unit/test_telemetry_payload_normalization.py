from quantgambit.observability.telemetry import (
    _normalize_decision_payload,
    _normalize_order_payload,
    _normalize_prediction_payload,
)


def test_normalize_prediction_payload_sets_provider_and_block_reason():
    payload = {
        "source": "onnx_v1",
        "reject": True,
        "reason": "score_high_ece",
        "direction": "up",
        "confidence": "0.73",
    }
    normalized = _normalize_prediction_payload(payload)
    assert normalized["provider"] == "onnx_v1"
    assert normalized["prediction_blocked_reason"] == "score_high_ece"
    assert normalized["abstain_reason"] == "score_high_ece"
    assert normalized["directional_label"] == "long"
    assert normalized["confidence"] == 0.73


def test_normalize_prediction_payload_does_not_block_when_abstain_is_threshold_dict():
    payload = {
        "provider": "onnx_v1",
        "reject": False,
        "direction": "up",
        "confidence": 0.82,
        "abstain": {"min_confidence": 0.33, "min_margin": 0.01, "max_entropy": 0.99},
    }
    normalized = _normalize_prediction_payload(payload)
    assert normalized["provider"] == "onnx_v1"
    assert "prediction_blocked_reason" not in normalized
    assert "abstain_reason" not in normalized


def test_normalize_prediction_payload_sets_block_reason_when_explicit_abstain_bool():
    payload = {
        "provider": "suppressed",
        "abstain": True,
        "reason": "score_snapshot_stale",
    }
    normalized = _normalize_prediction_payload(payload)
    assert normalized["prediction_blocked_reason"] == "score_snapshot_stale"
    assert normalized["abstain_reason"] == "score_snapshot_stale"


def test_normalize_order_payload_sets_close_category_and_latency():
    payload = {
        "position_effect": "close",
        "reason": "guardian_max_age_reached",
        "entry_timestamp": 1700000000,
        "exit_timestamp": 1700000030,
    }
    normalized = _normalize_order_payload(payload)
    assert normalized["exit_reason"] == "guardian_max_age_reached"
    assert normalized["close_category"] == "guardian_age"
    assert normalized["entry_to_exit_latency_sec"] == 30.0


def test_normalize_decision_payload_derives_edge_fields_and_rejection_stage():
    payload = {
        "result": "REJECT",
        "rejected_by": "prediction_gate",
        "expected_bps": 8.0,
        "ev_gate": {"total_cost_bps": 3.0},
        "rejection_detail": {"prediction_blocked_reason": "score_low_accuracy"},
    }
    normalized = _normalize_decision_payload(payload)
    assert normalized["decision"] == "rejected"
    assert normalized["rejection_stage"] == "prediction_gate"
    assert normalized["expected_gross_edge_bps"] == 8.0
    assert normalized["estimated_total_cost_bps"] == 3.0
    assert normalized["expected_net_edge_bps"] == 5.0
    assert normalized["prediction_blocked_reason"] == "score_low_accuracy"


def test_normalize_order_payload_sets_liquidity_from_explicit_bool():
    payload = {"status": "filled", "is_maker": True}
    normalized = _normalize_order_payload(payload)
    assert normalized["liquidity"] == "maker"
    assert normalized["maker_taker"] == "maker"
    assert normalized["liquidity_type"] == "maker"
    assert normalized["is_maker"] is True
    assert normalized["liquidity_source"] == "explicit_bool"


def test_normalize_order_payload_infers_taker_from_market_order():
    payload = {"status": "filled", "order_type": "market", "post_only": False}
    normalized = _normalize_order_payload(payload)
    assert normalized["liquidity"] == "taker"
    assert normalized["is_maker"] is False
    assert normalized["liquidity_source"] in {"heuristic_post_only", "heuristic_order_type_market"}
