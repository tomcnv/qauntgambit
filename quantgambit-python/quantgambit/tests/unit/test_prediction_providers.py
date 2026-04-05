from quantgambit.signals.prediction_providers import (
    DeepSeekContextPredictionProvider,
    HeuristicPredictionProvider,
    LegacyPredictionProvider,
    OnnxPredictionProvider,
    OnnxExpertRoute,
    RoutedOnnxPredictionProvider,
    build_prediction_provider,
)
import quantgambit.signals.prediction_providers as prediction_providers_module


def test_legacy_prediction_provider_builds_payload():
    provider = LegacyPredictionProvider()
    features = {
        "ema_fast_15m": 101.0,
        "ema_slow_15m": 100.0,
        "rotation_factor": 2.0,
        "atr_5m": 1.2,
        "atr_5m_baseline": 1.0,
    }
    market_context = {
        "price": 100.5,
        "spread_bps": 2.0,
        "bid_depth_usd": 60000.0,
        "ask_depth_usd": 62000.0,
        "orderbook_imbalance": 0.05,
        "trend_strength": 0.002,
        "data_completeness": 0.9,
    }
    payload = provider.build_prediction(features, market_context, timestamp=123.0)
    assert payload is not None
    assert payload["direction"] in {"up", "down", "flat"}
    assert payload["confidence"] >= 0.0
    assert payload["source"] == "legacy_layer1"


def test_heuristic_prediction_provider_v1_default_source():
    provider = HeuristicPredictionProvider()
    payload = provider.build_prediction(
        features={"symbol": "BTCUSDT"},
        market_context={
            "price": 100.0,
            "orderbook_imbalance": 0.2,
            "trend_strength": 0.0002,
            "volatility_regime": "normal",
            "data_completeness": 0.95,
        },
        timestamp=1.0,
    )
    assert payload is not None
    assert payload["source"] == "heuristic_v1"


def test_heuristic_prediction_provider_v1_sets_reject_reason():
    provider = HeuristicPredictionProvider()
    payload = provider.build_prediction(
        features={"symbol": "BTCUSDT"},
        market_context={
            "price": 100.0,
            "orderbook_imbalance": 0.2,
            "trend_strength": 0.0002,
            "volatility_regime": "normal",
            "data_completeness": 0.2,
        },
        timestamp=1.0,
    )
    assert payload is not None
    assert payload["reject"] is True
    assert payload["reason"] == "heuristic_low_data_completeness"


def test_heuristic_prediction_provider_v2_uses_scored_direction(monkeypatch):
    monkeypatch.setenv("PREDICTION_HEURISTIC_VERSION", "v2")
    monkeypatch.setenv("PREDICTION_HEURISTIC_V2_ENTRY_SCORE", "0.15")
    provider = HeuristicPredictionProvider()
    payload = provider.build_prediction(
        features={"symbol": "ETHUSDT", "rotation_factor": 4.0},
        market_context={
            "price": 100.0,
            "orderbook_imbalance": 0.55,
            "trend_direction": "up",
            "trend_strength": 0.0002,
            "volatility_regime": "normal",
            "data_completeness": 0.95,
            "spread_bps": 0.5,
            "session": "europe",
        },
        timestamp=1.0,
    )
    assert payload is not None
    assert payload["source"] == "heuristic_v2"
    assert payload["direction"] == "up"
    assert payload["reject"] is False
    assert payload["confidence"] >= 0.12
    assert payload.get("heuristic_score", 0.0) > 0.15


def test_heuristic_prediction_provider_v2_rejects_low_quality(monkeypatch):
    monkeypatch.setenv("PREDICTION_HEURISTIC_VERSION", "v2")
    monkeypatch.setenv("PREDICTION_HEURISTIC_V2_MIN_DATA_COMPLETENESS", "0.5")
    provider = HeuristicPredictionProvider()
    payload = provider.build_prediction(
        features={"symbol": "SOLUSDT"},
        market_context={
            "price": 100.0,
            "orderbook_imbalance": -0.35,
            "trend_direction": "down",
            "trend_strength": 0.00015,
            "volatility_regime": "high",
            "data_completeness": 0.3,
            "spread_bps": 4.9,
            "session": "europe",
        },
        timestamp=1.0,
    )
    assert payload is not None
    assert payload["source"] == "heuristic_v2"
    assert payload["reject"] is True
    assert payload["reason"] == "heuristic_low_data_completeness"


def test_heuristic_prediction_provider_v2_can_be_forced_by_provider_config(monkeypatch):
    monkeypatch.delenv("PREDICTION_HEURISTIC_VERSION", raising=False)
    provider = HeuristicPredictionProvider(provider_config={"heuristic_version": "v2"})
    payload = provider.build_prediction(
        features={"symbol": "BTCUSDT", "rotation_factor": 2.5},
        market_context={
            "price": 100.0,
            "orderbook_imbalance": 0.45,
            "trend_direction": "up",
            "trend_strength": 0.00015,
            "volatility_regime": "normal",
            "data_completeness": 0.9,
            "spread_bps": 0.6,
            "session": "europe",
        },
        timestamp=1.0,
    )
    assert payload is not None
    assert payload["source"] == "heuristic_v2"


def test_heuristic_prediction_provider_v2_rejects_low_net_edge(monkeypatch):
    monkeypatch.setenv("PREDICTION_HEURISTIC_VERSION", "v2")
    monkeypatch.setenv("PREDICTION_HEURISTIC_V2_ENTRY_SCORE", "0.15")
    monkeypatch.setenv("PREDICTION_HEURISTIC_V2_EXPECTED_MOVE_PER_SCORE_BPS", "10")
    monkeypatch.setenv("PREDICTION_HEURISTIC_V2_MIN_NET_EDGE_BPS", "8")
    monkeypatch.setenv("PREDICTION_HEURISTIC_V2_FEE_BPS", "5.5")
    monkeypatch.setenv("PREDICTION_HEURISTIC_V2_SLIPPAGE_BPS", "2.0")
    monkeypatch.setenv("PREDICTION_HEURISTIC_V2_ADVERSE_SELECTION_BPS", "1.0")
    provider = HeuristicPredictionProvider()
    payload = provider.build_prediction(
        features={"symbol": "ETHUSDT", "rotation_factor": 2.0},
        market_context={
            "price": 100.0,
            "orderbook_imbalance": 0.30,
            "trend_direction": "up",
            "trend_strength": 0.0001,
            "volatility_regime": "normal",
            "data_completeness": 0.95,
            "spread_bps": 0.6,
            "session": "us",
        },
        timestamp=1.0,
    )
    assert payload is not None
    assert payload["source"] == "heuristic_v2"
    assert payload["reason"] == "heuristic_low_net_edge"
    assert payload["reject"] is True
    assert payload["expected_net_edge_bps"] < 8.0


def test_heuristic_prediction_provider_v2_uses_stricter_short_entry_threshold(monkeypatch):
    monkeypatch.setenv("PREDICTION_HEURISTIC_VERSION", "v2")
    monkeypatch.setenv("PREDICTION_HEURISTIC_V2_ENTRY_SCORE_LONG", "0.15")
    monkeypatch.setenv("PREDICTION_HEURISTIC_V2_ENTRY_SCORE_SHORT", "0.45")
    provider = HeuristicPredictionProvider()
    payload = provider.build_prediction(
        features={"symbol": "SOLUSDT", "rotation_factor": 1.5},
        market_context={
            "price": 100.0,
            "orderbook_imbalance": -0.25,
            "trend_direction": "down",
            "trend_strength": 0.00008,
            "volatility_regime": "normal",
            "data_completeness": 0.95,
            "spread_bps": 0.3,
            "session": "us",
        },
        timestamp=1.0,
    )
    assert payload is not None
    assert payload["source"] == "heuristic_v2"
    assert payload["direction"] == "flat"


def test_build_prediction_provider_supports_deepseek_context():
    provider = build_prediction_provider("deepseek_context")
    assert isinstance(provider, DeepSeekContextPredictionProvider)


def test_deepseek_context_provider_abstains_when_context_missing(monkeypatch):
    monkeypatch.delenv("AI_ENABLED_SYMBOLS", raising=False)
    monkeypatch.setenv("AI_MIN_FEATURE_COMPLETENESS", "0.9")
    provider = DeepSeekContextPredictionProvider()
    monkeypatch.setattr(prediction_providers_module, "get_symbol_context", lambda symbol: {})
    payload = provider.build_prediction(
        {"symbol": "BTCUSDT"},
        {
            "symbol": "BTCUSDT",
            "price": 100.0,
            "spread_bps": 2.0,
            "data_completeness": 0.95,
            "data_quality_status": "ok",
            "session": "ny",
        },
        timestamp=1.0,
    )
    assert payload is not None
    assert payload["reject"] is True
    assert "sentiment_missing" in payload["reason_codes"]


def test_deepseek_context_provider_parses_structured_json(monkeypatch):
    monkeypatch.setenv("AI_ENABLED_SYMBOLS", "BTCUSDT")
    monkeypatch.setenv("AI_ENABLED_SESSIONS", "ny")
    monkeypatch.setenv("AI_PROVIDER_MIN_CONFIDENCE", "0.60")
    provider = DeepSeekContextPredictionProvider()
    monkeypatch.setattr(
        prediction_providers_module,
        "get_symbol_context",
        lambda symbol: {
            "sentiment": {
                "combined_sentiment": 0.62,
                "news_count_1h": 5,
                "source_quality": 0.9,
                "age_ms": 1000,
                "is_stale": False,
            },
            "events": {"age_ms": 1000, "exchange_risk_flag": False},
        },
    )
    monkeypatch.setattr(prediction_providers_module, "get_global_context", lambda: {})
    monkeypatch.setattr(
        prediction_providers_module,
        "llm_complete_sync",
        lambda *args, **kwargs: """{"direction":"long","confidence":0.81,"expected_move_bps":42,"horizon_sec":7200,"reason_codes":["sentiment_aligned"],"risk_flags":[],"valid_for_ms":180000,"raw_score":0.44}""",
    )
    payload = provider.build_prediction(
        {"symbol": "BTCUSDT"},
        {
            "symbol": "BTCUSDT",
            "price": 100.0,
            "spread_bps": 2.0,
            "data_completeness": 0.95,
            "data_quality_status": "ok",
            "session": "ny",
            "trend_direction": "up",
            "trend_strength": 0.001,
            "volatility_regime": "normal",
            "market_regime": "trending",
        },
        timestamp=1.0,
    )
    assert payload is not None
    assert payload["direction"] == "up"
    assert payload["source"] == "deepseek_context"
    assert payload["provider_latency_ms"] >= 1
    assert payload["reason_codes"] == ["sentiment_aligned"]


def test_deepseek_context_provider_reuses_cached_prediction(monkeypatch):
    monkeypatch.setenv("AI_ENABLED_SYMBOLS", "BTCUSDT")
    monkeypatch.setenv("AI_ENABLED_SESSIONS", "ny")
    monkeypatch.setenv("AI_PROVIDER_MIN_CONFIDENCE", "0.60")
    provider = DeepSeekContextPredictionProvider({"valid_for_ms": 180000})
    monkeypatch.setattr(
        prediction_providers_module,
        "get_symbol_context",
        lambda symbol: {
            "sentiment": {
                "combined_sentiment": 0.62,
                "news_count_1h": 5,
                "source_quality": 0.9,
                "age_ms": 1000,
                "is_stale": False,
            },
            "events": {"age_ms": 1000, "exchange_risk_flag": False},
        },
    )
    monkeypatch.setattr(prediction_providers_module, "get_global_context", lambda: {})
    calls = {"count": 0}

    def _fake_llm(*args, **kwargs):
        calls["count"] += 1
        return """{"direction":"long","confidence":0.81,"expected_move_bps":42,"horizon_sec":7200,"reason_codes":["sentiment_aligned"],"risk_flags":[],"valid_for_ms":180000,"raw_score":0.44}"""

    monkeypatch.setattr(prediction_providers_module, "llm_complete_sync", _fake_llm)
    market_context = {
        "symbol": "BTCUSDT",
        "price": 100.0,
        "spread_bps": 2.0,
        "data_completeness": 0.95,
        "data_quality_status": "ok",
        "session": "ny",
        "trend_direction": "up",
        "trend_strength": 0.001,
        "volatility_regime": "normal",
        "market_regime": "trending",
    }

    first = provider.build_prediction({"symbol": "BTCUSDT"}, market_context, timestamp=1.0)
    second = provider.build_prediction({"symbol": "BTCUSDT"}, market_context, timestamp=2.0)

    assert first is not None
    assert second is not None
    assert calls["count"] == 1
    assert second["cached_prediction"] is True
    assert second["provider_latency_ms"] == 0
    assert second["reason_codes"][0] == "cached_prediction"
    assert second["direction"] == "up"


def test_deepseek_context_provider_refreshes_after_cache_expiry(monkeypatch):
    monkeypatch.setenv("AI_ENABLED_SYMBOLS", "BTCUSDT")
    monkeypatch.setenv("AI_ENABLED_SESSIONS", "ny")
    monkeypatch.setenv("AI_PROVIDER_MIN_CONFIDENCE", "0.60")
    provider = DeepSeekContextPredictionProvider({"valid_for_ms": 1000, "cache_min_valid_for_ms": 1000})
    monkeypatch.setattr(
        prediction_providers_module,
        "get_symbol_context",
        lambda symbol: {
            "sentiment": {
                "combined_sentiment": 0.62,
                "news_count_1h": 5,
                "source_quality": 0.9,
                "age_ms": 1000,
                "is_stale": False,
            },
            "events": {"age_ms": 1000, "exchange_risk_flag": False},
        },
    )
    monkeypatch.setattr(prediction_providers_module, "get_global_context", lambda: {})
    calls = {"count": 0}

    def _fake_llm(*args, **kwargs):
        calls["count"] += 1
        return """{"direction":"long","confidence":0.81,"expected_move_bps":42,"horizon_sec":7200,"reason_codes":["sentiment_aligned"],"risk_flags":[],"valid_for_ms":1000,"raw_score":0.44}"""

    fake_time = {"now": 1000.0}

    def _fake_time():
        return fake_time["now"]

    monkeypatch.setattr(prediction_providers_module, "llm_complete_sync", _fake_llm)
    monkeypatch.setattr(prediction_providers_module.time, "time", _fake_time)
    market_context = {
        "symbol": "BTCUSDT",
        "price": 100.0,
        "spread_bps": 2.0,
        "data_completeness": 0.95,
        "data_quality_status": "ok",
        "session": "ny",
        "trend_direction": "up",
        "trend_strength": 0.001,
        "volatility_regime": "normal",
        "market_regime": "trending",
    }

    first = provider.build_prediction({"symbol": "BTCUSDT"}, market_context, timestamp=1.0)
    fake_time["now"] = 1000.5
    second = provider.build_prediction({"symbol": "BTCUSDT"}, market_context, timestamp=2.0)
    fake_time["now"] = 1001.2
    third = provider.build_prediction({"symbol": "BTCUSDT"}, market_context, timestamp=3.0)

    assert first is not None
    assert second is not None
    assert third is not None
    assert calls["count"] == 2
    assert second["cached_prediction"] is True
    assert third.get("cached_prediction") is not True


def test_ai_session_aliases_match_runtime_labels(monkeypatch):
    monkeypatch.setenv("AI_ENABLED_SESSIONS", "london,ny")

    admissible, reasons = prediction_providers_module.is_ai_admissible(
        {"symbol": "BTCUSDT"},
        {
            "symbol": "BTCUSDT",
            "spread_bps": 2.0,
            "data_completeness": 0.95,
            "data_quality_status": "ok",
            "session": "us",
        },
        {
            "sentiment": {
                "news_count_1h": 5,
                "source_quality": 0.9,
                "age_ms": 1000,
                "is_stale": False,
            },
            "events": {"age_ms": 1000, "exchange_risk_flag": False},
        },
    )
    assert admissible is True
    assert "session_not_enabled" not in reasons

    admissible, reasons = prediction_providers_module.is_ai_admissible(
        {"symbol": "BTCUSDT"},
        {
            "symbol": "BTCUSDT",
            "spread_bps": 2.0,
            "data_completeness": 0.95,
            "data_quality_status": "ok",
            "session": "europe",
        },
        {
            "sentiment": {
                "news_count_1h": 5,
                "source_quality": 0.9,
                "age_ms": 1000,
                "is_stale": False,
            },
            "events": {"age_ms": 1000, "exchange_risk_flag": False},
        },
    )
    assert admissible is True
    assert "session_not_enabled" not in reasons


def test_onnx_prediction_provider_missing_model_returns_none():
    provider = OnnxPredictionProvider(model_path=None, feature_keys=["price"])
    payload = provider.build_prediction({"price": 1.0}, {"price": 1.0}, timestamp=1.0)
    assert payload is None


def test_onnx_prediction_provider_uses_probability_output():
    class FakeSession:
        def run(self, _unused, _inputs):
            return [
                {"down": 0.1, "flat": 0.2, "up": 0.7},
            ]

    provider = OnnxPredictionProvider(
        model_path="model.onnx",
        feature_keys=["price"],
        class_labels=["down", "flat", "up"],
    )
    provider._session = FakeSession()
    provider._input_name = "input"
    provider._output_names = ["output"]
    payload = provider.build_prediction({"price": 100.0}, {"price": 100.0}, timestamp=1.0)
    assert payload is not None
    assert payload["direction"] == "up"
    assert payload["confidence"] == 0.7
    assert payload["p_long_win"] == 0.7
    assert payload["p_short_win"] == 0.1


def test_onnx_prediction_provider_maps_int_key_probabilities():
    class FakeSession:
        def run(self, _unused, _inputs):
            # Mimic sklearn-onnx: seq(map(int64 -> float)) style.
            return [
                [{0: 0.05, 1: 0.15, 2: 0.80}],
            ]

    provider = OnnxPredictionProvider(
        model_path="model.onnx",
        feature_keys=["price"],
        class_labels=["down", "flat", "up"],
    )
    provider._session = FakeSession()
    provider._input_name = "input"
    provider._output_names = ["output_probability"]
    payload = provider.build_prediction({"price": 100.0}, {"price": 100.0}, timestamp=1.0)
    assert payload is not None
    assert payload["direction"] == "up"
    assert payload["confidence"] == 0.80
    assert payload["p_long_win"] == 0.80
    assert payload["p_short_win"] == 0.05


def test_onnx_prediction_provider_clamps_nan_inf_probabilities_to_safe_range(monkeypatch):
    import time
    import math

    class FakeSession:
        def run(self, _unused, _inputs):
            return [
                {"down": float("nan"), "flat": float("inf"), "up": -1.0},
            ]

    # Ensure the ONNX provider path does not read wall-clock time (determinism contract).
    monkeypatch.setattr(time, "time", lambda: (_ for _ in ()).throw(AssertionError("time.time called")))

    provider = OnnxPredictionProvider(
        model_path="model.onnx",
        feature_keys=["price"],
        class_labels=["down", "flat", "up"],
        refresh_interval_sec=300.0,
    )
    provider._session = FakeSession()
    provider._input_name = "input"
    provider._output_names = ["probabilities"]
    payload = provider.build_prediction({"price": 100.0}, {"price": 100.0}, timestamp=123.0)
    assert payload is not None
    assert payload["direction"] in {"down", "flat", "up"}
    assert 0.0 <= payload["confidence"] <= 1.0
    probs = payload.get("probs") or {}
    for value in probs.values():
        assert value is not None
        assert isinstance(value, float)
        assert math.isfinite(value)
        assert 0.0 <= value <= 1.0


def test_onnx_prediction_provider_handles_non_numeric_outputs_gracefully():
    class FakeSession:
        def run(self, _unused, _inputs):
            return [
                [None, "bad", 0.9],
            ]

    provider = OnnxPredictionProvider(
        model_path="model.onnx",
        feature_keys=["price"],
        class_labels=["down", "flat", "up"],
    )
    provider._session = FakeSession()
    provider._input_name = "input"
    provider._output_names = ["output_probability"]
    payload = provider.build_prediction({"price": 100.0}, {"price": 100.0}, timestamp=1.0)
    assert payload is not None
    assert payload["direction"] in {"down", "flat", "up"}
    assert 0.0 <= payload["confidence"] <= 1.0


def test_onnx_prediction_provider_rejects_when_critical_features_missing(monkeypatch):
    class FakeSession:
        def run(self, _unused, _inputs):
            raise AssertionError("inference should not run when critical features are missing")

    monkeypatch.setenv("PREDICTION_ONNX_CRITICAL_FEATURE_GATE_ENABLED", "true")
    monkeypatch.setenv("PREDICTION_ONNX_CRITICAL_FEATURES", "price,spread_bps")
    monkeypatch.setenv("PREDICTION_ONNX_CRITICAL_FEATURE_MIN_PRESENCE", "1.0")

    provider = OnnxPredictionProvider(
        model_path="model.onnx",
        feature_keys=["price", "spread_bps"],
        class_labels=["down", "flat", "up"],
    )
    provider._session = FakeSession()
    provider._input_name = "input"
    provider._output_names = ["output_probability"]

    payload = provider.build_prediction({"price": 100.0}, {"price": 100.0}, timestamp=1.0)
    assert payload is not None
    assert payload["reject"] is True
    assert payload["reason"] == "onnx_missing_critical_feature"
    gate = payload.get("critical_feature_gate") or {}
    assert gate.get("present_ratio") == 0.5
    assert "spread_bps" in (gate.get("missing_critical_features") or [])


def test_onnx_prediction_provider_allows_partial_critical_presence_when_threshold_met(monkeypatch):
    class FakeSession:
        def run(self, _unused, _inputs):
            return [{"down": 0.1, "flat": 0.2, "up": 0.7}]

    monkeypatch.setenv("PREDICTION_ONNX_CRITICAL_FEATURE_GATE_ENABLED", "true")
    monkeypatch.setenv("PREDICTION_ONNX_CRITICAL_FEATURES", "price,spread_bps")
    monkeypatch.setenv("PREDICTION_ONNX_CRITICAL_FEATURE_MIN_PRESENCE", "0.5")

    provider = OnnxPredictionProvider(
        model_path="model.onnx",
        feature_keys=["price", "spread_bps"],
        class_labels=["down", "flat", "up"],
    )
    provider._session = FakeSession()
    provider._input_name = "input"
    provider._output_names = ["output_probability"]

    payload = provider.build_prediction({"price": 100.0}, {"price": 100.0}, timestamp=1.0)
    assert payload is not None
    assert payload["reject"] is False
    assert payload["direction"] == "up"


def test_onnx_prediction_provider_applies_probability_calibration():
    class FakeSession:
        def run(self, _unused, _inputs):
            return [
                {"down": 0.45, "flat": 0.10, "up": 0.45},
            ]

    provider = OnnxPredictionProvider(
        model_path="model.onnx",
        feature_keys=["price"],
        class_labels=["down", "flat", "up"],
        provider_config={
            "probability_calibration": {
                "per_class": {
                    "up": {"a": 1.8, "b": 0.7},
                    "down": {"a": 1.0, "b": -0.4},
                    "flat": {"a": 1.0, "b": -0.2},
                }
            }
        },
    )
    provider._session = FakeSession()
    provider._input_name = "input"
    provider._output_names = ["output_probability"]

    payload = provider.build_prediction({"price": 100.0}, {"price": 100.0}, timestamp=1.0)
    assert payload is not None
    assert payload["calibration_applied"] is True
    assert payload["probs_raw"]["up"] == 0.45
    assert payload["direction"] == "up"
    assert payload["confidence"] > payload["confidence_raw"]


def test_onnx_prediction_provider_abstains_on_low_margin():
    class FakeSession:
        def run(self, _unused, _inputs):
            return [
                {"down": 0.49, "flat": 0.02, "up": 0.49},
            ]

    provider = OnnxPredictionProvider(
        model_path="model.onnx",
        feature_keys=["price"],
        class_labels=["down", "flat", "up"],
        provider_config={"abstain": {"min_margin": 0.05}},
    )
    provider._session = FakeSession()
    provider._input_name = "input"
    provider._output_names = ["output_probability"]

    payload = provider.build_prediction({"price": 100.0}, {"price": 100.0}, timestamp=1.0)
    assert payload is not None
    assert payload["reject"] is True
    assert payload["reason"] == "onnx_low_margin"


def test_onnx_prediction_provider_honors_reject_flat_override(monkeypatch):
    class FakeSession:
        def run(self, _unused, _inputs):
            return [
                {"down": 0.10, "flat": 0.80, "up": 0.10},
            ]

    monkeypatch.setenv("PREDICTION_ONNX_REJECT_FLAT", "false")

    provider = OnnxPredictionProvider(
        model_path="model.onnx",
        feature_keys=["price"],
        class_labels=["down", "flat", "up"],
    )
    provider._session = FakeSession()
    provider._input_name = "input"
    provider._output_names = ["output_probability"]

    payload = provider.build_prediction({"price": 100.0}, {"price": 100.0}, timestamp=1.0)
    assert payload is not None
    assert payload["direction"] == "flat"
    assert payload["reject"] is False
    assert payload["reason"] is None
    assert payload["abstain"]["reject_flat_class"] is False


def test_onnx_prediction_provider_exposes_f1_gate_diagnostics():
    class FakeSession:
        def run(self, _unused, _inputs):
            return [
                {"down": 0.90, "flat": 0.05, "up": 0.05},
            ]

    provider = OnnxPredictionProvider(
        model_path="model.onnx",
        feature_keys=["price"],
        class_labels=["down", "flat", "up"],
        provider_config={"metrics": {"f1_down": 0.25}},
    )
    provider._session = FakeSession()
    provider._input_name = "input"
    provider._output_names = ["output_probability"]
    provider._min_f1_down = 0.40

    payload = provider.build_prediction({"price": 100.0}, {"price": 100.0}, timestamp=1.0)
    assert payload is not None
    assert payload["reject"] is True
    assert payload["reason"] == "onnx_unreliable_down_class"
    assert payload["abstain"]["f1_down"] == 0.25
    assert payload["abstain"]["min_f1_down_for_short"] == 0.40


def test_onnx_prediction_provider_handles_inference_exception():
    class FakeSession:
        def run(self, _unused, _inputs):
            raise RuntimeError("boom")

    provider = OnnxPredictionProvider(
        model_path="model.onnx",
        feature_keys=["price"],
        class_labels=["down", "flat", "up"],
    )
    provider._session = FakeSession()
    provider._input_name = "input"
    provider._output_names = ["output_probability"]

    payload = provider.build_prediction({"price": 100.0}, {"price": 100.0}, timestamp=1.0)
    assert payload is None
    assert provider._session is None
    assert provider._input_name is None
    assert provider._output_names == []


def test_onnx_prediction_provider_validate_fails_when_model_missing():
    provider = OnnxPredictionProvider(
        model_path="definitely_missing_model.onnx",
        feature_keys=["price"],
        class_labels=["down", "flat", "up"],
    )
    assert provider.validate(0.0) is False


def test_routed_onnx_prediction_provider_routes_to_matching_expert():
    class DefaultSession:
        def run(self, _unused, _inputs):
            return [{"down": 0.1, "flat": 0.2, "up": 0.7}]

    class ExpertSession:
        def run(self, _unused, _inputs):
            return [{"down": 0.8, "flat": 0.1, "up": 0.1}]

    provider = build_prediction_provider(
        "onnx",
        model_path="default.onnx",
        feature_keys=["price"],
        class_labels=["down", "flat", "up"],
        provider_config={
            "experts": [
                {
                    "id": "btc_us",
                    "model_path": "expert.onnx",
                    "feature_keys": ["price"],
                    "class_labels": ["down", "flat", "up"],
                    "match": {"symbols": ["BTCUSDT"], "sessions": ["US"]},
                    "priority": 10,
                }
            ]
        },
    )
    assert hasattr(provider, "default_provider")
    assert hasattr(provider, "experts")
    provider.default_provider._session = DefaultSession()
    provider.default_provider._input_name = "input"
    provider.default_provider._output_names = ["prob"]
    provider.experts[0].provider._session = ExpertSession()
    provider.experts[0].provider._input_name = "input"
    provider.experts[0].provider._output_names = ["prob"]

    payload_match = provider.build_prediction(
        {"symbol": "BTCUSDT", "price": 100.0},
        {"symbol": "BTCUSDT", "session": "us", "price": 100.0},
        timestamp=1.0,
    )
    assert payload_match is not None
    assert payload_match["direction"] == "down"
    assert payload_match["expert_id"] == "btc_us"
    assert payload_match["expert_routed"] is True

    payload_default = provider.build_prediction(
        {"symbol": "ETHUSDT", "price": 100.0},
        {"symbol": "ETHUSDT", "session": "us", "price": 100.0},
        timestamp=1.0,
    )
    assert payload_default is not None
    assert payload_default["direction"] == "up"
    assert payload_default["expert_id"] == "default"
    assert payload_default["expert_routed"] is False


def test_routed_onnx_prediction_provider_disables_invalid_expert_on_validate():
    class DefaultSession:
        def run(self, _unused, _inputs):
            return [{"down": 0.1, "flat": 0.2, "up": 0.7}]

    class ExpertSession:
        def run(self, _unused, _inputs):
            return [{"down": 0.9, "flat": 0.05, "up": 0.05}]

    provider = build_prediction_provider(
        "onnx",
        model_path="default.onnx",
        feature_keys=["price"],
        class_labels=["down", "flat", "up"],
        provider_config={
            "experts": [
                {
                    "id": "btc_only",
                    "model_path": "expert.onnx",
                    "feature_keys": ["price"],
                    "class_labels": ["down", "flat", "up"],
                    "match": {"symbols": ["BTCUSDT"]},
                    "priority": 10,
                }
            ]
        },
    )
    provider.default_provider._session = DefaultSession()
    provider.default_provider._input_name = "input"
    provider.default_provider._output_names = ["prob"]
    provider.experts[0].provider._session = ExpertSession()
    provider.experts[0].provider._input_name = "input"
    provider.experts[0].provider._output_names = ["prob"]
    provider.experts[0].provider.validate = lambda _now_ts=None: False

    assert provider.validate(1.0) is False
    assert provider.experts[0].disabled is True

    payload = provider.build_prediction(
        {"symbol": "BTCUSDT", "price": 100.0},
        {"symbol": "BTCUSDT", "price": 100.0},
        timestamp=1.0,
    )
    assert payload is not None
    assert payload["expert_id"] == "default"


def test_routed_onnx_prediction_provider_validate_passes_with_one_healthy_expert():
    class DefaultSession:
        def run(self, _unused, _inputs):
            return [{"down": 0.1, "flat": 0.2, "up": 0.7}]

    class ExpertSession:
        def run(self, _unused, _inputs):
            return [{"down": 0.6, "flat": 0.2, "up": 0.2}]

    provider = build_prediction_provider(
        "onnx",
        model_path="default.onnx",
        feature_keys=["price"],
        class_labels=["down", "flat", "up"],
        provider_config={
            "experts": [
                {
                    "id": "bad_expert",
                    "model_path": "bad.onnx",
                    "feature_keys": ["price"],
                    "class_labels": ["down", "flat", "up"],
                    "match": {"symbols": ["BTCUSDT"]},
                    "priority": 10,
                },
                {
                    "id": "good_expert",
                    "model_path": "good.onnx",
                    "feature_keys": ["price"],
                    "class_labels": ["down", "flat", "up"],
                    "match": {"symbols": ["ETHUSDT"]},
                    "priority": 5,
                },
            ]
        },
    )
    provider.default_provider._session = DefaultSession()
    provider.default_provider._input_name = "input"
    provider.default_provider._output_names = ["prob"]
    provider.experts[0].provider._session = ExpertSession()
    provider.experts[0].provider._input_name = "input"
    provider.experts[0].provider._output_names = ["prob"]
    provider.experts[1].provider._session = ExpertSession()
    provider.experts[1].provider._input_name = "input"
    provider.experts[1].provider._output_names = ["prob"]
    provider.experts[0].provider.validate = lambda _now_ts=None: False
    provider.experts[1].provider.validate = lambda _now_ts=None: True

    assert provider.validate(1.0) is True
    assert provider.experts[0].disabled is True
    assert provider.experts[1].disabled is False


def test_routed_onnx_provider_resolves_model_paths_relative_to_config(tmp_path):
    config_path = tmp_path / "registry" / "latest.json"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text("{}", encoding="utf-8")
    default_model = config_path.parent / "default.onnx"
    expert_model = config_path.parent / "expert.onnx"
    default_model.write_bytes(b"")
    expert_model.write_bytes(b"")

    provider = build_prediction_provider(
        "onnx",
        model_path="default.onnx",
        feature_keys=["price"],
        class_labels=["down", "flat", "up"],
        provider_config={
            "__config_path": str(config_path),
            "experts": [
                {
                    "id": "expert_a",
                    "model_path": "expert.onnx",
                    "feature_keys": ["price"],
                    "class_labels": ["down", "flat", "up"],
                    "match": {"symbols": ["BTCUSDT"]},
                }
            ],
        },
    )

    assert isinstance(provider, RoutedOnnxPredictionProvider)
    assert provider.default_provider.model_path == str(default_model.resolve())
    assert provider.experts[0].provider.model_path == str(expert_model.resolve())


def test_routed_onnx_provider_logs_when_expert_returns_no_payload(monkeypatch):
    events = []

    def _fake_log_warning(event, **kwargs):
        events.append((event, kwargs))

    monkeypatch.setattr(prediction_providers_module, "log_warning", _fake_log_warning)

    class NoneProvider:
        def build_prediction(self, *_args, **_kwargs):
            return None

    class DefaultProvider:
        def build_prediction(self, *_args, **_kwargs):
            return {
                "timestamp": 1.0,
                "direction": "up",
                "confidence": 0.6,
                "source": "test",
            }

    provider = RoutedOnnxPredictionProvider(
        default_provider=DefaultProvider(),
        experts=[OnnxExpertRoute(id="expert_none", provider=NoneProvider(), match={"symbols": {"BTCUSDT"}})],
    )

    payload = provider.build_prediction(
        {"symbol": "BTCUSDT", "price": 100.0},
        {"symbol": "BTCUSDT", "session": "us", "price": 100.0},
        timestamp=1.0,
    )
    assert payload is not None
    assert payload["expert_id"] == "default"
    assert any(event == "onnx_expert_no_payload_fallback_default" for event, _ in events)


def test_onnx_prediction_provider_action_contract_two_head_tensor():
    class FakeSession:
        def run(self, _unused, _inputs):
            return [[0.72, 0.41]]

    provider = OnnxPredictionProvider(
        model_path="model.onnx",
        feature_keys=["price"],
        class_labels=["p_long_win", "p_short_win"],
        provider_config={"prediction_contract": "action_conditional_pnl_winprob"},
    )
    provider._session = FakeSession()
    provider._input_name = "input"
    provider._output_names = ["winprob"]
    payload = provider.build_prediction({"price": 100.0}, {"price": 100.0}, timestamp=1.0)
    assert payload is not None
    assert payload["direction"] == "up"
    assert payload["p_long_win"] == 0.72
    assert payload["p_short_win"] == 0.41
    assert payload["confidence"] == 0.72


def test_onnx_prediction_provider_action_contract_named_outputs():
    class FakeSession:
        def run(self, _unused, _inputs):
            return [[0.35], [0.79]]

    provider = OnnxPredictionProvider(
        model_path="model.onnx",
        feature_keys=["price"],
        class_labels=["p_long_win", "p_short_win"],
        provider_config={"prediction_contract": "action_conditional_pnl_winprob"},
    )
    provider._session = FakeSession()
    provider._input_name = "input"
    provider._output_names = ["p_long_win", "p_short_win"]
    payload = provider.build_prediction({"price": 100.0}, {"price": 100.0}, timestamp=1.0)
    assert payload is not None
    assert payload["direction"] == "down"
    assert payload["p_long_win"] == 0.35
    assert payload["p_short_win"] == 0.79
