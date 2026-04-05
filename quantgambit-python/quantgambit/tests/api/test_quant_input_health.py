from quantgambit.api.quant_endpoints import _summarize_prediction_input_health


def _sample(feature_values: dict, market_context: dict | None = None, source: str = "onnx_v1") -> dict:
    return {
        "payload": {
            "features": feature_values,
            "market_context": market_context or {},
            "prediction": {"source": source},
        }
    }


def test_input_feature_health_flags_constant_and_missing_features():
    samples = [
        _sample({"spread_bps": 0.1, "price_change_1s": 0.0}),
        _sample({"spread_bps": 0.1, "price_change_1s": 0.0}),
        _sample({"spread_bps": 0.1, "price_change_1s": 0.0}),
    ]
    summary = _summarize_prediction_input_health(
        samples,
        ["spread_bps", "price_change_1s", "data_completeness"],
    )

    assert summary["status"] == "critical"
    assert summary["sample_count"] == 3
    assert "spread_bps" in summary["warning_features"]
    assert "data_completeness" in summary["critical_features"]


def test_input_feature_health_counts_market_context_fallback():
    samples = [
        _sample(
            {"price_change_1s": 0.01},
            market_context={"data_completeness": 1.0},
            source="heuristic_v1",
        ),
        _sample(
            {"price_change_1s": 0.02},
            market_context={"data_completeness": 1.0},
            source="onnx_v1",
        ),
    ]

    summary = _summarize_prediction_input_health(
        samples,
        ["price_change_1s", "data_completeness"],
    )
    by_name = {item["name"]: item for item in summary["features"]}

    assert summary["source_counts"]["onnx"] == 1
    assert summary["source_counts"]["heuristic"] == 1
    assert by_name["data_completeness"]["fallback_from_market_context_pct"] == 100.0
    assert by_name["price_change_1s"]["missing_pct"] == 0.0


def test_input_feature_health_structural_constants_are_warning_not_critical():
    samples = [
        _sample({"spread_bps": 0.1}, market_context={"data_completeness": 1.0}, source="onnx_v1"),
        _sample({"spread_bps": 0.1}, market_context={"data_completeness": 1.0}, source="onnx_v1"),
        _sample({"spread_bps": 0.1}, market_context={"data_completeness": 1.0}, source="onnx_v1"),
    ]
    summary = _summarize_prediction_input_health(samples, ["spread_bps", "data_completeness"])

    assert summary["status"] == "warning"
    assert summary["critical_features"] == []
    assert "spread_bps" in summary["warning_features"]
    assert "data_completeness" in summary["warning_features"]


def test_input_feature_health_slow_moving_features_are_warning_when_constant():
    samples = [
        _sample(
            {
                "ema_fast_15m": 1961.7,
                "ema_slow_15m": 1961.8,
                "atr_5m": 1.54,
                "atr_5m_baseline": 3.26,
            },
            source="onnx_v1",
        ),
        _sample(
            {
                "ema_fast_15m": 1961.7,
                "ema_slow_15m": 1961.8,
                "atr_5m": 1.54,
                "atr_5m_baseline": 3.26,
            },
            source="onnx_v1",
        ),
    ]
    summary = _summarize_prediction_input_health(
        samples,
        ["ema_fast_15m", "ema_slow_15m", "atr_5m", "atr_5m_baseline"],
    )

    assert summary["status"] == "warning"
    assert summary["critical_features"] == []
    assert set(summary["warning_features"]) == {
        "ema_fast_15m",
        "ema_slow_15m",
        "atr_5m",
        "atr_5m_baseline",
    }
