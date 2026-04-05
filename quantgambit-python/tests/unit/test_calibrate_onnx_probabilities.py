import sys
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


def _load_module():
    script_path = Path(__file__).resolve().parents[2] / "scripts" / "calibrate_onnx_probabilities.py"
    spec = spec_from_file_location("calibrate_onnx_probabilities", script_path)
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_classify_skipped_classes_unstable_params():
    module = _load_module()
    kind = module._classify_skipped_classes(
        {
            "down": "unstable_params:a=0.01,b=-2.0",
            "up": "no_improvement:ece_before=0.1,ece_after=0.2",
        }
    )
    assert kind == "unstable_params"


def test_classify_skipped_classes_insufficient_samples():
    module = _load_module()
    kind = module._classify_skipped_classes(
        {
            "_global": "insufficient_samples",
        }
    )
    assert kind == "insufficient_samples"
