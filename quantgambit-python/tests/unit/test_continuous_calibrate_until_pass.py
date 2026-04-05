import sys
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


def _load_module():
    script_path = (
        Path(__file__).resolve().parents[2] / "scripts" / "continuous_calibrate_until_pass.py"
    )
    spec = spec_from_file_location("continuous_calibrate_until_pass", script_path)
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_extract_json_objects_parses_multiple_payloads():
    module = _load_module()
    text = (
        'noise {"status":"ok","x":1}\n'
        "more-noise\n"
        '{"score_snapshot":{"status":"blocked","symbols":{"BTCUSDT":{"status":"blocked"}}}}'
    )
    items = module._extract_json_objects(text)
    assert len(items) >= 2
    assert items[0]["status"] == "ok"
    assert items[-1]["score_snapshot"]["status"] == "blocked"


def test_resolve_targets_prefers_explicit_ids(tmp_path):
    module = _load_module()
    model_meta = tmp_path / "latest.json"
    model_meta.write_text(
        '{"experts":[{"id":"btc_us"},{"id":"eth_us"}]}',
        encoding="utf-8",
    )
    targets = module._resolve_targets(model_meta, "btc_us,eth_us,btc_us", all_experts=True)
    assert targets == ["btc_us", "eth_us"]


def test_resolve_targets_uses_all_experts_when_requested(tmp_path):
    module = _load_module()
    model_meta = tmp_path / "latest.json"
    model_meta.write_text(
        '{"experts":[{"id":"btc_us"},{},{"id":"eth_us"}]}',
        encoding="utf-8",
    )
    targets = module._resolve_targets(model_meta, "", all_experts=True)
    assert targets == ["btc_us", "eth_us"]


def test_resolve_targets_defaults_to_single_primary(tmp_path):
    module = _load_module()
    model_meta = tmp_path / "latest.json"
    model_meta.write_text("{}", encoding="utf-8")
    targets = module._resolve_targets(model_meta, "", all_experts=False)
    assert targets == [None]


def test_validate_targets_fails_when_experts_requested_but_missing():
    module = _load_module()
    ok, err = module._validate_targets_against_meta(
        {},
        ["btc_us", "eth_us"],
        expert_ids_csv="btc_us,eth_us",
        all_experts=False,
    )
    assert ok is False
    assert err == "expert_targets_requested_but_no_experts_in_meta"


def test_validate_targets_fails_when_requested_expert_not_found():
    module = _load_module()
    ok, err = module._validate_targets_against_meta(
        {"experts": [{"id": "btc_us"}]},
        ["btc_us", "sol_us"],
        expert_ids_csv="btc_us,sol_us",
        all_experts=False,
    )
    assert ok is False
    assert err == "expert_targets_not_found_in_meta:sol_us"


def test_validate_targets_accepts_present_experts():
    module = _load_module()
    ok, err = module._validate_targets_against_meta(
        {"experts": [{"id": "btc_us"}, {"id": "eth_us"}]},
        ["btc_us", "eth_us"],
        expert_ids_csv="btc_us,eth_us",
        all_experts=False,
    )
    assert ok is True
    assert err is None


def test_select_expert_meta_fallback_picks_latest_with_experts(tmp_path):
    module = _load_module()
    latest = tmp_path / "latest.json"
    latest.write_text("{}", encoding="utf-8")

    older = tmp_path / "latest.json.bak.1"
    older.write_text('{"experts":[{"id":"btc_us"}]}', encoding="utf-8")

    newer_no_experts = tmp_path / "latest.json.bak.2"
    newer_no_experts.write_text('{"foo":"bar"}', encoding="utf-8")

    newest = tmp_path / "latest.json.rollback_backup.3"
    newest.write_text('{"experts":[{"id":"eth_us"}]}', encoding="utf-8")

    picked = module._select_expert_meta_fallback(latest)
    assert picked is not None
    assert picked.name == "latest.json.rollback_backup.3"


def test_select_expert_meta_fallback_returns_none_when_missing(tmp_path):
    module = _load_module()
    latest = tmp_path / "latest.json"
    latest.write_text("{}", encoding="utf-8")
    (tmp_path / "latest.json.bak.1").write_text('{"foo":"bar"}', encoding="utf-8")
    picked = module._select_expert_meta_fallback(latest)
    assert picked is None


def test_classify_calibration_failure_prefers_structured_payload():
    module = _load_module()
    out = module._classify_calibration_failure(
        {
            "status": "failed",
            "reason": "no_calibration_fitted",
            "failure_kind": "unstable_params",
            "retryable": True,
        },
        stdout="",
        stderr="",
    )
    assert out["status"] == "failed"
    assert out["reason"] == "no_calibration_fitted"
    assert out["failure_kind"] == "unstable_params"
    assert out["retryable"] is True


def test_classify_calibration_failure_detects_non_retryable_marker():
    module = _load_module()
    out = module._classify_calibration_failure({}, stdout="", stderr="expert_not_found:btc_us")
    assert out["retryable"] is False
    assert out["reason"] == "expert_not_found"


def test_resolve_expert_fallback_dataset_uses_trained_dataset(tmp_path):
    module = _load_module()
    dataset = tmp_path / "expert.csv"
    dataset.write_text("a,b\n1,2\n", encoding="utf-8")
    payload = {
        "experts": [
            {
                "id": "btc_us",
                "meta": {"trained_from_dataset": str(dataset)},
            }
        ]
    }
    resolved = module._resolve_expert_fallback_dataset(payload, "btc_us")
    assert resolved == str(dataset)
