from quantgambit.api.quant_endpoints import (
    _build_entry_quality_readiness,
    _build_directional_readiness,
    _close_event_identity,
    _normalize_position_side_from_close_payload,
)


def test_close_side_infers_long_position_for_sell_close():
    payload = {"symbol": "BTCUSDT", "side": "sell", "position_effect": "close"}
    assert _normalize_position_side_from_close_payload(payload) == "long"


def test_explicit_position_side_overrides_close_side():
    payload = {
        "symbol": "ETHUSDT",
        "side": "sell",
        "position_effect": "close",
        "position_side": "short",
    }
    assert _normalize_position_side_from_close_payload(payload) == "short"


def test_close_event_identity_stable_by_order_id():
    payload = {
        "symbol": "SOLUSDT",
        "order_id": "abc123",
        "side": "buy",
        "position_effect": "close",
    }
    assert _close_event_identity(payload) == "SOLUSDT:order_id:abc123"


def test_directional_readiness_recommends_long_only_when_short_is_not_ready(monkeypatch):
    monkeypatch.setenv("DIRECTIONAL_CANARY_MIN_TOTAL_SAMPLES", "100")
    monkeypatch.setenv("DIRECTIONAL_CANARY_MIN_SAMPLES_PER_SIDE", "40")
    monkeypatch.setenv("DIRECTIONAL_CANARY_MIN_WIN_RATE_LONG", "0.52")
    monkeypatch.setenv("DIRECTIONAL_CANARY_MIN_WIN_RATE_SHORT", "0.52")
    monkeypatch.setenv("DIRECTIONAL_CANARY_MIN_EXPECTANCY_LONG", "0.0")
    monkeypatch.setenv("DIRECTIONAL_CANARY_MIN_EXPECTANCY_SHORT", "0.0")

    canary = {
        "samples_close_fills": 160,
        "long": {"pnl_samples": 80, "win_rate": 0.58, "expectancy_net_pnl": 0.12},
        "short": {"pnl_samples": 80, "win_rate": 0.44, "expectancy_net_pnl": -0.05},
    }
    report = _build_directional_readiness(canary)
    assert report["ready_long"] is True
    assert report["ready_short"] is False
    assert report["recommended_short_enabled"] is False
    assert report["recommendation"] == "long_only"


def test_directional_readiness_recommends_both_sides_when_checks_pass(monkeypatch):
    monkeypatch.setenv("DIRECTIONAL_CANARY_MIN_TOTAL_SAMPLES", "100")
    monkeypatch.setenv("DIRECTIONAL_CANARY_MIN_SAMPLES_PER_SIDE", "40")
    monkeypatch.setenv("DIRECTIONAL_CANARY_MIN_WIN_RATE_LONG", "0.52")
    monkeypatch.setenv("DIRECTIONAL_CANARY_MIN_WIN_RATE_SHORT", "0.52")
    monkeypatch.setenv("DIRECTIONAL_CANARY_MIN_EXPECTANCY_LONG", "0.0")
    monkeypatch.setenv("DIRECTIONAL_CANARY_MIN_EXPECTANCY_SHORT", "0.0")

    canary = {
        "samples_close_fills": 140,
        "long": {"pnl_samples": 70, "win_rate": 0.56, "expectancy_net_pnl": 0.08},
        "short": {"pnl_samples": 70, "win_rate": 0.54, "expectancy_net_pnl": 0.03},
    }
    report = _build_directional_readiness(canary)
    assert report["ready_overall"] is True
    assert report["recommended_short_enabled"] is True
    assert report["recommendation"] == "enable_both_sides"


def test_entry_quality_readiness_flags_degraded_window(monkeypatch):
    monkeypatch.setenv("ENTRY_QUALITY_MIN_GREEN_PCT", "80")
    monkeypatch.setenv("ENTRY_QUALITY_MAX_BLOCKED_PCT", "25")
    monkeypatch.setenv("ENTRY_QUALITY_MAX_FALLBACK_PCT", "40")

    feature_samples = [
        {"payload": {"market_context": {"readiness_level": "green", "prediction_score_gate_status": "none"}}},
        {"payload": {"market_context": {"readiness_level": "yellow", "prediction_score_gate_status": "blocked"}}},
        {"payload": {"market_context": {"readiness_level": "red", "prediction_score_gate_status": "fallback"}}},
        {"payload": {"market_context": {"readiness_level": "green", "prediction_score_gate_status": "none"}}},
    ]
    decision_samples = [
        {"payload": {"rejection_reason": "execution_veto:readiness_yellow"}},
        {"payload": {"rejection_reason": "side_quality_veto:low_samples:20<100"}},
        {"payload": {"rejection_reason": "no_signal"}},
    ]
    report = _build_entry_quality_readiness(feature_samples, decision_samples)
    assert report["ready"] is False
    assert "green_readiness_pct" in report["blockers"]
    assert report["top_blocking_reasons"][0]["reason"].startswith("execution_veto:")


def test_entry_quality_readiness_passes_when_green_and_unblocked(monkeypatch):
    monkeypatch.setenv("ENTRY_QUALITY_MIN_GREEN_PCT", "70")
    monkeypatch.setenv("ENTRY_QUALITY_MAX_BLOCKED_PCT", "20")
    monkeypatch.setenv("ENTRY_QUALITY_MAX_FALLBACK_PCT", "40")

    feature_samples = [
        {"payload": {"market_context": {"readiness_level": "green", "prediction_score_gate_status": "none"}}},
        {"payload": {"market_context": {"readiness_level": "green", "prediction_score_gate_status": "none"}}},
        {"payload": {"market_context": {"readiness_level": "green", "prediction_score_gate_status": "fallback"}}},
        {"payload": {"market_context": {"readiness_level": "green", "prediction_score_gate_status": "none"}}},
    ]
    decision_samples = [{"payload": {"decision": "accepted"}}]
    report = _build_entry_quality_readiness(feature_samples, decision_samples)
    assert report["ready"] is True
    assert report["recommendation"] == "enforce_entry_quality_gates"


def test_entry_quality_readiness_maps_data_quality_status_to_readiness(monkeypatch):
    monkeypatch.setenv("ENTRY_QUALITY_MIN_GREEN_PCT", "50")
    feature_samples = [
        {"payload": {"market_context": {"data_quality_status": "ok", "prediction_score_gate_status": "ok"}}},
        {"payload": {"market_context": {"data_quality_status": "warning", "prediction_score_gate_status": "ok"}}},
        {"payload": {"market_context": {"data_quality_status": "critical", "prediction_score_gate_status": "blocked"}}},
    ]
    report = _build_entry_quality_readiness(feature_samples, decision_samples=[])
    assert report["readiness_counts"].get("green") == 1
    assert report["readiness_counts"].get("yellow") == 1
    assert report["readiness_counts"].get("red") == 1
