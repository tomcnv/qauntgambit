from quantgambit.api.runtime_knobs import knob_catalog, merge_runtime_config, validate_section_patch


def test_knob_catalog_contains_core_sections():
    catalog = knob_catalog()
    assert isinstance(catalog, list)
    keys = {item["key"] for item in catalog}
    assert "risk_per_trade_pct" in keys
    assert "max_slippage_bps" in keys
    assert "position_continuation_gate_enabled" in keys


def test_validate_section_patch_rejects_unknown_and_wrong_section():
    cleaned, errors = validate_section_patch(
        "risk_config",
        {
            "risk_per_trade_pct": 1.2,
            "max_slippage_bps": 3.0,  # belongs to execution_config
            "does_not_exist": 1,
        },
    )
    assert cleaned == {"risk_per_trade_pct": 1.2}
    assert any("wrong_section:risk_config.max_slippage_bps" in err for err in errors)
    assert any("unknown_key:risk_config.does_not_exist" in err for err in errors)


def test_merge_runtime_config_applies_patches_and_symbol_normalization():
    current = {
        "risk_config": {"risk_per_trade_pct": 0.5},
        "execution_config": {"max_slippage_bps": 5.0},
        "profile_overrides": {"position_continuation_gate_enabled": False},
        "enabled_symbols": ["ETHUSDT"],
    }
    merged, errors = merge_runtime_config(
        current,
        risk_patch={"risk_per_trade_pct": 1.0},
        execution_patch={"max_slippage_bps": 2.5},
        profile_patch={"position_continuation_gate_enabled": "true"},
        enabled_symbols=["ethusdt", "btcusdt", "ETHUSDT"],
    )
    assert errors == []
    assert merged["risk_config"]["risk_per_trade_pct"] == 1.0
    assert merged["execution_config"]["max_slippage_bps"] == 2.5
    assert merged["profile_overrides"]["position_continuation_gate_enabled"] is True
    assert merged["enabled_symbols"] == ["ETHUSDT", "BTCUSDT"]


def test_merge_runtime_config_handles_json_string_sections():
    current = {
        "risk_config": '{"max_positions": 2}',
        "execution_config": '{"max_retries": 1}',
        "profile_overrides": '{"position_continuation_gate_enabled": false}',
        "enabled_symbols": '["ethusdt","btcusdt"]',
    }
    merged, errors = merge_runtime_config(
        current,
        risk_patch={"max_positions": 3},
        profile_patch={"position_continuation_gate_enabled": True},
    )
    assert errors == []
    assert merged["risk_config"]["max_positions"] == 3
    assert merged["execution_config"]["max_retries"] == 1
    assert merged["profile_overrides"]["position_continuation_gate_enabled"] is True
    assert merged["enabled_symbols"] == ["ethusdt", "btcusdt"]
