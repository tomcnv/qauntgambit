from quantgambit.runtime.entrypoint import (
    RuntimeConfig,
    _apply_ai_profile_prediction_overrides,
    _resolve_market_data_symbols,
    _load_prediction_config,
    _validate_onnx_provider,
)


def test_runtime_config_defaults():
    cfg = RuntimeConfig(tenant_id="t", bot_id="b", exchange="okx")
    assert cfg.trading_mode == "live"
    assert cfg.market_type == "perp"
    assert cfg.margin_mode == "isolated"


def test_resolve_market_data_symbols_prefers_env():
    raw = _resolve_market_data_symbols("ETH/USDT:USDT", "BTCUSDT", "", "okx")
    assert raw == "ETH/USDT:USDT"


def test_resolve_market_data_symbols_falls_back_to_orderbook():
    raw = _resolve_market_data_symbols("", "BTCUSDT", "", "bybit")
    assert raw == "BTCUSDT"


def test_resolve_market_data_symbols_uses_default():
    raw = _resolve_market_data_symbols("", "", "", "binance")
    assert raw == "BTCUSDT"


def test_load_prediction_config_reads_json(tmp_path):
    config_path = tmp_path / "prediction.json"
    config_path.write_text('{"feature_keys": ["price"], "class_labels": ["down", "up"]}', encoding="utf-8")
    payload = _load_prediction_config(str(config_path))
    assert payload["feature_keys"] == ["price"]
    assert payload["class_labels"] == ["down", "up"]


def test_validate_onnx_provider_strict_uses_resolved_model_path():
    class Provider:
        default_provider = type("DefaultProvider", (), {"model_path": "models/registry/latest.onnx"})()

        @staticmethod
        def validate(_now_ts=None):
            return False

    try:
        _validate_onnx_provider(
            label="primary",
            provider=Provider(),
            provider_name="onnx",
            strict=True,
        )
        assert False, "Expected strict ONNX validation failure"
    except RuntimeError as exc:
        assert "models/registry/latest.onnx" in str(exc)


def test_validate_onnx_provider_non_strict_no_raise():
    class Provider:
        model_path = "models/registry/latest.onnx"

        @staticmethod
        def validate(_now_ts=None):
            return False

    _validate_onnx_provider(
        label="primary",
        provider=Provider(),
        provider_name="onnx",
        strict=False,
    )


def test_apply_ai_profile_prediction_overrides_forces_deepseek():
    provider, shadow_provider, model_path, model_config, model_features, model_classes, min_conf = _apply_ai_profile_prediction_overrides(
        '{"bot_type":"ai_spot_swing","ai_provider":"deepseek_context","ai_confidence_floor":0.81}',
        "onnx",
        "",
        "models/registry/latest.onnx",
        "models/registry/latest.json",
        "price,spread",
        "down,flat,up",
        0.55,
    )
    assert provider == "deepseek_context"
    assert shadow_provider == ""
    assert model_path is None
    assert model_config == ""
    assert model_features == ""
    assert model_classes == "down,flat,up"
    assert min_conf == 0.81


def test_apply_ai_profile_prediction_overrides_keeps_live_provider_in_shadow_mode(monkeypatch):
    monkeypatch.setenv("AI_SHADOW_ONLY", "true")
    (
        provider,
        shadow_provider,
        model_path,
        model_config,
        model_features,
        model_classes,
        min_conf,
    ) = _apply_ai_profile_prediction_overrides(
        '{"bot_type":"ai_spot_swing","ai_provider":"deepseek_context","ai_shadow_mode":true,"ai_confidence_floor":0.81}',
        "heuristic",
        "",
        "models/registry/latest.onnx",
        "models/registry/latest.json",
        "price,spread",
        "down,flat,up",
        0.55,
    )
    assert provider == "heuristic"
    assert shadow_provider == "deepseek_context"
    assert model_path == "models/registry/latest.onnx"
    assert model_config == "models/registry/latest.json"
    assert model_features == "price,spread"
    assert model_classes == "down,flat,up"
    assert min_conf == 0.81
