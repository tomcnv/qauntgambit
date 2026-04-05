import sys
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


def _load_module():
    script_path = (
        Path(__file__).resolve().parents[3] / "scripts" / "calibrate_onnx_probabilities.py"
    )
    spec = spec_from_file_location("calibrate_onnx_probabilities", script_path)
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_select_calibration_source_prefers_live_when_guardrails_pass():
    module = _load_module()
    class_labels = ["down", "flat", "up"]
    live_rows = [
        {"label": "down"},
        {"label": "flat"},
        {"label": "up"},
        {"label": "flat"},
    ]
    source, rows, reason = module.select_calibration_source(
        class_labels=class_labels,
        live_rows=live_rows,
        fallback_rows=[{"label": "down"}],
        min_live_samples=4,
        min_class_ratio=0.20,
    )
    assert source == "live"
    assert rows == live_rows
    assert reason is None


def test_select_calibration_source_falls_back_with_reason():
    module = _load_module()
    class_labels = ["down", "flat", "up"]
    live_rows = [{"label": "flat"} for _ in range(10)]
    fallback_rows = [{"label": "down"}, {"label": "up"}, {"label": "flat"}]
    source, rows, reason = module.select_calibration_source(
        class_labels=class_labels,
        live_rows=live_rows,
        fallback_rows=fallback_rows,
        min_live_samples=8,
        min_class_ratio=0.10,
    )
    assert source == "fallback"
    assert rows == fallback_rows
    assert reason is not None
    assert "live_guardrail_failed" in reason
