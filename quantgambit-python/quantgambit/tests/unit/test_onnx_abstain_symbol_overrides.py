def test_onnx_abstain_min_confidence_symbol_override(monkeypatch):
    monkeypatch.setenv("PREDICTION_ONNX_MIN_CONFIDENCE_BY_SYMBOL", "BTCUSDT:0.35")

    from quantgambit.signals.prediction_providers import OnnxPredictionProvider

    provider = OnnxPredictionProvider(
        model_path=None,
        feature_keys=["x"],
        class_labels=["down", "flat", "up"],
        provider_config={},
        min_confidence=0.52,  # global strict
        min_margin=0.10,
        max_entropy=0.93,
    )

    min_conf, min_margin, max_entropy = provider._effective_abstain_thresholds("BTCUSDT", None)
    assert min_conf == 0.35
    assert min_margin == 0.10
    assert max_entropy == 0.93


def test_onnx_abstain_session_and_symbol_session_override(monkeypatch):
    monkeypatch.setenv("PREDICTION_ONNX_MIN_CONFIDENCE_BY_SESSION", "ASIA:0.44")
    monkeypatch.setenv("PREDICTION_ONNX_MIN_CONFIDENCE_BY_SYMBOL", "BTCUSDT:0.40")
    monkeypatch.setenv("PREDICTION_ONNX_MIN_CONFIDENCE_BY_SYMBOL_SESSION", "BTCUSDT@ASIA:0.36")

    from quantgambit.signals.prediction_providers import OnnxPredictionProvider

    provider = OnnxPredictionProvider(
        model_path=None,
        feature_keys=["x"],
        class_labels=["down", "flat", "up"],
        provider_config={},
        min_confidence=0.52,
        min_margin=0.10,
        max_entropy=0.93,
    )

    # Session override should apply when no symbol-specific override exists.
    min_conf, _, _ = provider._effective_abstain_thresholds("ETHUSDT", "asia")
    assert min_conf == 0.44

    # Symbol+session should win over session and symbol overrides.
    min_conf, _, _ = provider._effective_abstain_thresholds("BTCUSDT", "asia")
    assert min_conf == 0.36

