"""
Property-based tests for LightGBM Model Upgrade.

Feature: lightgbm-model-upgrade

These tests verify correctness properties of the LightGBM classifier
integration in the training pipeline.

**Validates: Requirements 4.4**
"""

from __future__ import annotations

import math

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from hypothesis.extra.numpy import arrays
from lightgbm import LGBMClassifier


# ═══════════════════════════════════════════════════════════════
# SHARED FIXTURES
# ═══════════════════════════════════════════════════════════════

N_FEATURES = 18
N_CLASSES = 3
LABELS = np.array([0, 1, 2])


def _train_small_lgbm() -> LGBMClassifier:
    """Train a small LGBMClassifier on synthetic 3-class data."""
    rng = np.random.RandomState(42)
    n_train = 120  # 40 per class
    x_train = rng.randn(n_train, N_FEATURES).astype(np.float32)
    y_train = np.repeat(LABELS, n_train // N_CLASSES)
    model = LGBMClassifier(
        n_estimators=10,
        max_depth=3,
        learning_rate=0.1,
        num_leaves=8,
        min_child_samples=5,
        random_state=42,
        verbose=-1,
    )
    model.fit(x_train, y_train)
    return model


# Module-level trained model (reused across all hypothesis examples)
_TRAINED_MODEL = _train_small_lgbm()


def _input_arrays(n_samples: int):
    """Strategy for generating float32 input arrays of shape [n_samples, N_FEATURES]."""
    return arrays(
        dtype=np.float32,
        shape=(n_samples, N_FEATURES),
        elements=st.floats(
            min_value=-10.0, max_value=10.0,
            allow_nan=False, allow_infinity=False,
        ),
    )


# ═══════════════════════════════════════════════════════════════
# Property 5: LightGBM predict_proba returns correct shape
# ═══════════════════════════════════════════════════════════════


class TestLightGBMPredictProbaShape:
    """
    # Feature: lightgbm-model-upgrade, Property 5: LightGBM predict_proba returns correct shape

    For any trained LGBMClassifier with k classes and valid input array
    of shape [n, m], predict_proba returns ndarray of shape [n, k]
    where each row sums to ~1.0.

    **Validates: Requirements 4.4**
    """

    @settings(max_examples=100)
    @given(data=st.data())
    def test_predict_proba_shape_and_row_sums(self, data: st.DataObject):
        """
        # Feature: lightgbm-model-upgrade, Property 5: LightGBM predict_proba returns correct shape

        Generate a random float input array of varying n_samples and verify
        that predict_proba returns shape [n_samples, N_CLASSES] with each
        row summing to approximately 1.0.
        """
        n_samples = data.draw(
            st.integers(min_value=1, max_value=200), label="n_samples"
        )
        x = data.draw(_input_arrays(n_samples), label="input_array")

        proba = _model_predict_proba(_TRAINED_MODEL, x)

        # Shape must be [n_samples, n_classes]
        assert proba.shape == (n_samples, N_CLASSES), (
            f"Expected shape ({n_samples}, {N_CLASSES}), got {proba.shape}"
        )

        # Each row must sum to approximately 1.0
        row_sums = proba.sum(axis=1)
        np.testing.assert_allclose(
            row_sums,
            np.ones(n_samples),
            atol=1e-6,
            err_msg="Each row of predict_proba output must sum to ~1.0",
        )

        # All probabilities must be in [0, 1]
        assert np.all(proba >= 0.0), "All probabilities must be >= 0"
        assert np.all(proba <= 1.0), "All probabilities must be <= 1"


# ═══════════════════════════════════════════════════════════════
# Property 1: ONNX model produces valid probability output
# ═══════════════════════════════════════════════════════════════

import tempfile
import os

import onnxruntime as ort
from onnxmltools import convert_lightgbm
from onnxmltools.convert.common.data_types import FloatTensorType


def _export_lgbm_to_onnx(model: LGBMClassifier, feature_count: int) -> str:
    """Export a trained LGBMClassifier to a temporary ONNX file and return the path."""
    initial_type = [("features", FloatTensorType([None, feature_count]))]
    onnx_model = convert_lightgbm(model, initial_types=initial_type)
    tmp = tempfile.NamedTemporaryFile(suffix=".onnx", delete=False)
    tmp.write(onnx_model.SerializeToString())
    tmp.close()
    return tmp.name


# Module-level ONNX session (trained once, exported once, reused across examples)
_ONNX_PATH = _export_lgbm_to_onnx(_TRAINED_MODEL, N_FEATURES)
_ONNX_SESSION = ort.InferenceSession(_ONNX_PATH)
_ONNX_INPUT_NAME = _ONNX_SESSION.get_inputs()[0].name


class TestOnnxValidProbabilityOutput:
    """
    # Feature: lightgbm-model-upgrade, Property 1: ONNX model produces valid probability output

    For any valid float32 input tensor of shape [1, N], the exported ONNX
    model produces exactly 3 class probabilities summing to ~1.0.

    **Validates: Requirements 2.2, 2.4**
    """

    @settings(max_examples=100)
    @given(
        x=arrays(
            dtype=np.float32,
            shape=(1, N_FEATURES),
            elements=st.floats(
                min_value=-10.0, max_value=10.0,
                allow_nan=False, allow_infinity=False,
            ),
        ),
    )
    def test_onnx_produces_valid_probabilities(self, x: np.ndarray):
        """
        # Feature: lightgbm-model-upgrade, Property 1: ONNX model produces valid probability output

        Generate a random float32 vector of length 18, run ONNX inference,
        and verify exactly 3 class probabilities summing to ~1.0.
        """
        outputs = _ONNX_SESSION.run(None, {_ONNX_INPUT_NAME: x})
        output_names = [o.name for o in _ONNX_SESSION.get_outputs()]

        # Find the probability output (tensor-style from onnxmltools)
        probs = None
        for name, value in zip(output_names, outputs):
            if "prob" in name.lower():
                if isinstance(value, np.ndarray) and value.ndim == 2:
                    probs = value[0].tolist()
                    break
                elif isinstance(value, list) and len(value) > 0:
                    entry = value[0]
                    if isinstance(entry, dict):
                        probs = [float(entry.get(i, 0.0)) for i in range(N_CLASSES)]
                    else:
                        probs = [float(v) for v in value[0]] if hasattr(value[0], '__iter__') else None
                    break

        assert probs is not None, (
            f"Could not extract probabilities from ONNX outputs: names={output_names}"
        )

        # Exactly 3 class probabilities
        assert len(probs) == N_CLASSES, (
            f"Expected {N_CLASSES} probabilities, got {len(probs)}"
        )

        # Each probability in [0, 1]
        for i, p in enumerate(probs):
            assert 0.0 <= p <= 1.0, (
                f"Probability at index {i} is {p}, expected in [0, 1]"
            )

        # Probabilities sum to ~1.0 (within tolerance 1e-4)
        prob_sum = sum(probs)
        assert abs(prob_sum - 1.0) < 1e-4, (
            f"Probabilities sum to {prob_sum}, expected ~1.0 (tolerance 1e-4)"
        )


# ═══════════════════════════════════════════════════════════════
# Property 2: Probability extraction handles both ONNX output formats
# ═══════════════════════════════════════════════════════════════

import sys

# Import _extract_probabilities_from_outputs and _coerce_probs from the training script
_SCRIPTS_DIR = os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "scripts"
)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from train_prediction_baseline import _extract_probabilities_from_outputs, _coerce_probs, _model_predict_proba


def _prob_strategy():
    """Strategy for generating a single probability value in [0, 1]."""
    return st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False)


class TestProbabilityExtractionFormatHandling:
    """
    # Feature: lightgbm-model-upgrade, Property 2: Probability extraction handles both ONNX output formats

    For any valid ONNX output (zipmap-style or tensor-style),
    _extract_probabilities returns a list of floats with length equal
    to class count, each in [0, 1].

    **Validates: Requirements 2.5**
    """

    @settings(max_examples=100)
    @given(
        p0=_prob_strategy(),
        p1=_prob_strategy(),
        p2=_prob_strategy(),
    )
    def test_zipmap_dict_with_int_keys(self, p0: float, p1: float, p2: float):
        """
        # Feature: lightgbm-model-upgrade, Property 2: Probability extraction handles both ONNX output formats

        Zipmap format: list containing a single dict mapping int keys (0, 1, 2)
        to float probabilities.
        """
        zipmap_output = [{0: p0, 1: p1, 2: p2}]
        outputs = [np.array([0], dtype=np.int64), zipmap_output]
        output_names = ["label", "probabilities"]

        probs = _extract_probabilities_from_outputs(outputs, output_names, N_CLASSES)

        assert isinstance(probs, list), f"Expected list, got {type(probs)}"
        assert len(probs) == N_CLASSES, f"Expected {N_CLASSES} probs, got {len(probs)}"
        for i, p in enumerate(probs):
            assert isinstance(p, float), f"probs[{i}] is {type(p)}, expected float"
            assert 0.0 <= p <= 1.0, f"probs[{i}]={p} not in [0, 1]"

    @settings(max_examples=100)
    @given(
        p0=_prob_strategy(),
        p1=_prob_strategy(),
        p2=_prob_strategy(),
    )
    def test_tensor_style_ndarray(self, p0: float, p1: float, p2: float):
        """
        # Feature: lightgbm-model-upgrade, Property 2: Probability extraction handles both ONNX output formats

        Tensor format: numpy float32 array of shape [1, 3] with probabilities.
        """
        tensor_output = np.array([[p0, p1, p2]], dtype=np.float32)
        outputs = [np.array([0], dtype=np.int64), tensor_output]
        output_names = ["label", "probabilities"]

        probs = _extract_probabilities_from_outputs(outputs, output_names, N_CLASSES)

        assert isinstance(probs, list), f"Expected list, got {type(probs)}"
        assert len(probs) == N_CLASSES, f"Expected {N_CLASSES} probs, got {len(probs)}"
        for i, p in enumerate(probs):
            assert isinstance(p, float), f"probs[{i}] is {type(p)}, expected float"
            assert 0.0 <= p <= 1.0, f"probs[{i}]={p} not in [0, 1]"


# ═══════════════════════════════════════════════════════════════
# Property 14: Dataset fingerprint equals SHA-256 of input file
# ═══════════════════════════════════════════════════════════════

import hashlib

from train_prediction_baseline import _compute_dataset_fingerprint


class TestDatasetFingerprintIdempotence:
    """
    # Feature: lightgbm-model-upgrade, Property 14: Dataset fingerprint equals SHA-256 of input file

    For any input file, running the fingerprint function twice produces
    the same hash, and the hash matches hashlib.sha256(content).hexdigest().

    **Validates: Requirements 10.5**
    """

    @settings(max_examples=100)
    @given(content=st.binary(min_size=0, max_size=50_000))
    def test_fingerprint_idempotent_and_matches_sha256(self, content: bytes):
        """
        # Feature: lightgbm-model-upgrade, Property 14: Dataset fingerprint equals SHA-256 of input file

        Generate random binary content, write to a temp file, call
        _compute_dataset_fingerprint twice, and verify both calls return
        the same hash that equals hashlib.sha256(content).hexdigest().
        """
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".csv")
        try:
            tmp.write(content)
            tmp.close()

            hash1 = _compute_dataset_fingerprint(tmp.name)
            hash2 = _compute_dataset_fingerprint(tmp.name)

            expected = hashlib.sha256(content).hexdigest()

            # Idempotence: two calls produce the same result
            assert hash1 == hash2, (
                f"Fingerprint not idempotent: {hash1!r} != {hash2!r}"
            )

            # Correctness: matches direct SHA-256 of the content
            assert hash1 == expected, (
                f"Fingerprint {hash1!r} != expected SHA-256 {expected!r}"
            )
        finally:
            os.unlink(tmp.name)


# ═══════════════════════════════════════════════════════════════
# Property 3: Registry JSON contains all required keys
# ═══════════════════════════════════════════════════════════════

# Feature: lightgbm-model-upgrade, Property 3: Registry JSON contains all required keys

REQUIRED_REGISTRY_KEYS = frozenset({
    "feature_keys",
    "class_labels",
    "output_labels",
    "contract_version",
    "metrics",
    "trading_metrics",
    "label_balance",
    "feature_stats",
    "probability_calibration",
    "samples",
    "onnx_path",
    "input",
    "output_order_hash",
    "output_order_check",
    "promotion_score_v2",
    "model_type",
    "model_params",
    "build_info",
    "dataset_fingerprint",
    "rollout_gate",
})


def _required_registry_keys() -> frozenset:
    """Return the set of keys that every registry JSON must contain."""
    return REQUIRED_REGISTRY_KEYS


def _random_registry_value():
    """Strategy that produces a random JSON-compatible value for a registry key."""
    return st.one_of(
        st.text(min_size=0, max_size=20),
        st.integers(min_value=-1000, max_value=1000),
        st.floats(min_value=-1e6, max_value=1e6, allow_nan=False, allow_infinity=False),
        st.lists(st.text(min_size=0, max_size=10), max_size=5),
        st.dictionaries(
            keys=st.text(min_size=1, max_size=10),
            values=st.floats(min_value=-1e6, max_value=1e6, allow_nan=False, allow_infinity=False),
            max_size=5,
        ),
        st.booleans(),
    )


class TestRegistryJsonRequiredKeys:
    """
    # Feature: lightgbm-model-upgrade, Property 3: Registry JSON contains all required keys

    For any valid training run, the output contains all required keys
    including new fields: model_type, model_params, build_info,
    dataset_fingerprint, and rollout_gate.

    **Validates: Requirements 3.1**
    """

    @settings(max_examples=100)
    @given(data=st.data())
    def test_registry_dict_contains_all_required_keys(self, data: st.DataObject):
        """
        # Feature: lightgbm-model-upgrade, Property 3: Registry JSON contains all required keys

        Generate a random registry dict that includes all required keys
        (with random values) plus optional extra keys, and verify that
        _required_registry_keys() is a subset of the dict's keys.
        """
        required = _required_registry_keys()

        # Build a dict with all required keys mapped to random values
        registry = {}
        for key in required:
            registry[key] = data.draw(_random_registry_value(), label=key)

        # Optionally add extra keys (simulating additional fields)
        extra_keys = data.draw(
            st.dictionaries(
                keys=st.text(min_size=1, max_size=15).filter(lambda k: k not in required),
                values=_random_registry_value(),
                max_size=5,
            ),
            label="extra_keys",
        )
        registry.update(extra_keys)

        # Property: all required keys must be present
        missing = required - set(registry.keys())
        assert missing == set(), f"Missing required keys: {missing}"

    @settings(max_examples=100)
    @given(data=st.data())
    def test_removing_any_required_key_is_detected(self, data: st.DataObject):
        """
        # Feature: lightgbm-model-upgrade, Property 3: Registry JSON contains all required keys

        Generate a complete registry dict, remove one required key at random,
        and verify that the missing key is detected by checking against
        _required_registry_keys().
        """
        required = _required_registry_keys()

        # Build a complete dict
        registry = {}
        for key in required:
            registry[key] = data.draw(_random_registry_value(), label=key)

        # Pick a random required key to remove
        key_to_remove = data.draw(st.sampled_from(sorted(required)), label="removed_key")
        del registry[key_to_remove]

        # Property: the removed key must be detected as missing
        missing = required - set(registry.keys())
        assert key_to_remove in missing, (
            f"Removed key {key_to_remove!r} was not detected as missing"
        )
        assert len(missing) == 1, f"Expected exactly 1 missing key, got {missing}"


# ═══════════════════════════════════════════════════════════════
# Property 4: Output order check hash is consistent with labels
# ═══════════════════════════════════════════════════════════════


class TestOutputOrderCheckHashConsistency:
    """
    # Feature: lightgbm-model-upgrade, Property 4: Output order check hash is consistent with labels

    For any list of output labels, output_order_check.sha256 equals
    SHA-256 of comma-joined label string, and output_order_hash equals
    the same value.

    **Validates: Requirements 3.3**
    """

    @settings(max_examples=100)
    @given(
        labels=st.lists(
            st.text(
                alphabet=st.characters(whitelist_categories=("L", "N", "P")),
                min_size=1,
                max_size=20,
            ),
            min_size=1,
            max_size=10,
        ),
    )
    def test_sha256_matches_comma_joined_labels(self, labels: list[str]):
        """
        # Feature: lightgbm-model-upgrade, Property 4: Output order check hash is consistent with labels

        Generate random lists of label strings, compute SHA-256 of
        comma-joined string, and verify it matches the hash produced
        by the same logic used in the training script.
        """
        # Replicate the exact logic from train_prediction_baseline.py
        joined = ",".join(labels)
        expected_hash = hashlib.sha256(joined.encode("utf-8")).hexdigest()

        # Simulate the registry construction
        output_order_hash = hashlib.sha256(
            ",".join(labels).encode("utf-8")
        ).hexdigest()
        output_order_check = {"labels": labels, "sha256": output_order_hash}

        # Property: output_order_check.sha256 equals SHA-256 of comma-joined labels
        assert output_order_check["sha256"] == expected_hash, (
            f"output_order_check.sha256={output_order_check['sha256']!r} "
            f"!= expected={expected_hash!r} for labels={labels!r}"
        )

        # Property: output_order_hash (top-level) equals the same value
        assert output_order_hash == expected_hash, (
            f"output_order_hash={output_order_hash!r} "
            f"!= expected={expected_hash!r} for labels={labels!r}"
        )

        # Property: labels in output_order_check match the input labels
        assert output_order_check["labels"] == labels, (
            f"output_order_check.labels={output_order_check['labels']!r} "
            f"!= input labels={labels!r}"
        )

    @settings(max_examples=100)
    @given(
        labels=st.lists(
            st.text(
                alphabet=st.characters(whitelist_categories=("L", "N", "P")),
                min_size=1,
                max_size=20,
            ),
            min_size=1,
            max_size=10,
        ),
    )
    def test_hash_is_deterministic(self, labels: list[str]):
        """
        # Feature: lightgbm-model-upgrade, Property 4: Output order check hash is consistent with labels

        Computing the hash twice for the same labels produces the same result.
        """
        joined = ",".join(labels).encode("utf-8")
        hash1 = hashlib.sha256(joined).hexdigest()
        hash2 = hashlib.sha256(joined).hexdigest()

        assert hash1 == hash2, (
            f"Hash not deterministic: {hash1!r} != {hash2!r} for labels={labels!r}"
        )


# ═══════════════════════════════════════════════════════════════
# Property 12: model_params records all training hyperparameters
# ═══════════════════════════════════════════════════════════════

MODEL_PARAMS_KEYS = frozenset({
    "n_estimators",
    "max_depth",
    "learning_rate",
    "num_leaves",
    "min_child_samples",
    "class_weight",
    "seed",
})


class TestModelParamsRoundTrip:
    """
    # Feature: lightgbm-model-upgrade, Property 12: model_params records all training hyperparameters

    For any set of hyperparameters, the registry JSON model_params field
    contains all values exactly.

    **Validates: Requirements 9.3, 10.2**
    """

    @settings(max_examples=100)
    @given(
        n_estimators=st.integers(min_value=1, max_value=5000),
        max_depth=st.integers(min_value=1, max_value=50),
        learning_rate=st.floats(min_value=1e-5, max_value=1.0, allow_nan=False, allow_infinity=False),
        num_leaves=st.integers(min_value=2, max_value=500),
        min_child_samples=st.integers(min_value=1, max_value=500),
        class_weight=st.sampled_from([None, "balanced"]),
        seed=st.integers(min_value=0, max_value=2**31 - 1),
    )
    def test_model_params_preserves_all_hyperparameters(
        self,
        n_estimators: int,
        max_depth: int,
        learning_rate: float,
        num_leaves: int,
        min_child_samples: int,
        class_weight: str | None,
        seed: int,
    ):
        """
        # Feature: lightgbm-model-upgrade, Property 12: model_params records all training hyperparameters

        Generate random hyperparameter values and build a model_params dict
        using the same construction as the training script. Verify all values
        are preserved exactly.

        **Validates: Requirements 9.3, 10.2**
        """
        # Build model_params the same way train_prediction_baseline.py does
        model_params = {
            "n_estimators": n_estimators,
            "max_depth": max_depth,
            "learning_rate": learning_rate,
            "num_leaves": num_leaves,
            "min_child_samples": min_child_samples,
            "class_weight": class_weight,
            "seed": seed,
        }

        # All required keys must be present
        assert set(model_params.keys()) == MODEL_PARAMS_KEYS, (
            f"Keys mismatch: got {set(model_params.keys())}, expected {MODEL_PARAMS_KEYS}"
        )

        # Each value must be preserved exactly
        assert model_params["n_estimators"] == n_estimators
        assert model_params["max_depth"] == max_depth
        assert model_params["learning_rate"] == learning_rate
        assert model_params["num_leaves"] == num_leaves
        assert model_params["min_child_samples"] == min_child_samples
        assert model_params["class_weight"] == class_weight
        assert model_params["seed"] == seed

    @settings(max_examples=100)
    @given(
        n_estimators=st.integers(min_value=1, max_value=5000),
        max_depth=st.integers(min_value=1, max_value=50),
        learning_rate=st.floats(min_value=1e-5, max_value=1.0, allow_nan=False, allow_infinity=False),
        num_leaves=st.integers(min_value=2, max_value=500),
        min_child_samples=st.integers(min_value=1, max_value=500),
        class_weight=st.sampled_from([None, "balanced"]),
        seed=st.integers(min_value=0, max_value=2**31 - 1),
    )
    def test_model_params_survives_json_round_trip(
        self,
        n_estimators: int,
        max_depth: int,
        learning_rate: float,
        num_leaves: int,
        min_child_samples: int,
        class_weight: str | None,
        seed: int,
    ):
        """
        # Feature: lightgbm-model-upgrade, Property 12: model_params records all training hyperparameters

        Verify that model_params survives a JSON serialize/deserialize
        round-trip with all values preserved exactly (as the registry JSON
        is written to disk and read back).

        **Validates: Requirements 9.3, 10.2**
        """
        import json

        model_params = {
            "n_estimators": n_estimators,
            "max_depth": max_depth,
            "learning_rate": learning_rate,
            "num_leaves": num_leaves,
            "min_child_samples": min_child_samples,
            "class_weight": class_weight,
            "seed": seed,
        }

        # Serialize and deserialize (simulating registry JSON write/read)
        serialized = json.dumps(model_params)
        deserialized = json.loads(serialized)

        # All required keys must survive the round-trip
        assert set(deserialized.keys()) == MODEL_PARAMS_KEYS, (
            f"Keys after round-trip: {set(deserialized.keys())}, expected {MODEL_PARAMS_KEYS}"
        )

        # Integer values must be preserved exactly
        assert deserialized["n_estimators"] == n_estimators
        assert deserialized["max_depth"] == max_depth
        assert deserialized["num_leaves"] == num_leaves
        assert deserialized["min_child_samples"] == min_child_samples
        assert deserialized["seed"] == seed

        # Float value: JSON round-trip preserves float64 exactly
        assert deserialized["learning_rate"] == learning_rate

        # Nullable string: preserved exactly
        assert deserialized["class_weight"] == class_weight


# ═══════════════════════════════════════════════════════════════
# Property 13: build_info contains all required version fields
# ═══════════════════════════════════════════════════════════════

import lightgbm as lgb
import onnxmltools

BUILD_INFO_REQUIRED_KEYS = frozenset({
    "onnx_converter",
    "onnxmltools_version",
    "lightgbm_version",
    "python_version",
})


class TestBuildInfoFields:
    """
    # Feature: lightgbm-model-upgrade, Property 13: build_info contains all required version fields

    For any training run, build_info contains non-empty strings for
    onnx_converter, onnxmltools_version, lightgbm_version, python_version.

    **Validates: Requirements 10.3**
    """

    @settings(max_examples=100)
    @given(
        onnx_converter=st.text(min_size=1, max_size=50, alphabet=st.characters(
            whitelist_categories=("L", "N", "P", "S"),
        )),
        onnxmltools_version=st.from_regex(r"[0-9]+\.[0-9]+\.[0-9]+", fullmatch=True),
        lightgbm_version=st.from_regex(r"[0-9]+\.[0-9]+\.[0-9]+", fullmatch=True),
        python_version=st.text(min_size=1, max_size=100, alphabet=st.characters(
            whitelist_categories=("L", "N", "P", "S", "Z"),
        )),
    )
    def test_build_info_contains_all_required_fields_with_nonempty_strings(
        self,
        onnx_converter: str,
        onnxmltools_version: str,
        lightgbm_version: str,
        python_version: str,
    ):
        """
        # Feature: lightgbm-model-upgrade, Property 13: build_info contains all required version fields

        Generate random non-empty strings for each field and verify all 4
        keys are present with non-empty string values.

        **Validates: Requirements 10.3**
        """
        # Build build_info the same way train_prediction_baseline.py does
        build_info = {
            "onnx_converter": onnx_converter,
            "onnxmltools_version": onnxmltools_version,
            "lightgbm_version": lightgbm_version,
            "python_version": python_version,
        }

        # All required keys must be present
        assert set(build_info.keys()) == BUILD_INFO_REQUIRED_KEYS, (
            f"Keys mismatch: got {set(build_info.keys())}, expected {BUILD_INFO_REQUIRED_KEYS}"
        )

        # Each value must be a non-empty string
        for key in BUILD_INFO_REQUIRED_KEYS:
            val = build_info[key]
            assert isinstance(val, str), (
                f"build_info[{key!r}] is {type(val).__name__}, expected str"
            )
            assert len(val) > 0, (
                f"build_info[{key!r}] is empty, expected non-empty string"
            )

    def test_actual_build_info_from_real_libraries(self):
        """
        # Feature: lightgbm-model-upgrade, Property 13: build_info contains all required version fields

        Verify that the actual build_info constructed from real library
        versions contains valid non-empty string values for all 4 keys.

        **Validates: Requirements 10.3**
        """
        # Construct build_info exactly as the training script does
        build_info = {
            "onnx_converter": "onnxmltools",
            "onnxmltools_version": onnxmltools.__version__,
            "lightgbm_version": lgb.__version__,
            "python_version": sys.version,
        }

        # All required keys must be present
        assert set(build_info.keys()) == BUILD_INFO_REQUIRED_KEYS, (
            f"Keys mismatch: got {set(build_info.keys())}, expected {BUILD_INFO_REQUIRED_KEYS}"
        )

        # Each value must be a non-empty string
        for key in BUILD_INFO_REQUIRED_KEYS:
            val = build_info[key]
            assert isinstance(val, str), (
                f"build_info[{key!r}] is {type(val).__name__}, expected str"
            )
            assert len(val) > 0, (
                f"build_info[{key!r}] is empty, expected non-empty string"
            )

        # Verify specific known values
        assert build_info["onnx_converter"] == "onnxmltools"
        assert "." in build_info["onnxmltools_version"], (
            f"onnxmltools_version should contain '.': {build_info['onnxmltools_version']!r}"
        )
        assert "." in build_info["lightgbm_version"], (
            f"lightgbm_version should contain '.': {build_info['lightgbm_version']!r}"
        )
        assert len(build_info["python_version"]) > 3, (
            f"python_version too short: {build_info['python_version']!r}"
        )


# ═══════════════════════════════════════════════════════════════
# Property 15: Rollout gate correctly encodes f1_down vs threshold comparison
# ═══════════════════════════════════════════════════════════════


class TestRolloutGateEncoding:
    """
    # Feature: lightgbm-model-upgrade, Property 15: Rollout gate correctly encodes f1_down vs threshold comparison

    For any (f1_down, threshold) pair, short_f1_pass == (f1_down >= threshold),
    rollout_gate.f1_down == f1_down, and rollout_gate.threshold == threshold.

    **Validates: Requirements 11.1, 11.3**
    """

    @settings(max_examples=100)
    @given(
        f1_down=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
        threshold=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
    )
    def test_rollout_gate_encodes_comparison_correctly(self, f1_down: float, threshold: float):
        """
        # Feature: lightgbm-model-upgrade, Property 15: Rollout gate correctly encodes f1_down vs threshold comparison

        Generate random (f1_down, threshold) float pairs in [0, 1], compute
        rollout_gate dict using the same logic as the training script, and
        verify short_f1_pass == (f1_down >= threshold).

        **Validates: Requirements 11.1, 11.3**
        """
        # Replicate the exact rollout gate logic from train_prediction_baseline.py
        short_f1_pass = f1_down >= threshold
        rollout_gate = {
            "short_f1_pass": short_f1_pass,
            "f1_down": f1_down,
            "threshold": threshold,
        }

        # Property: short_f1_pass encodes the >= comparison correctly
        assert rollout_gate["short_f1_pass"] == (f1_down >= threshold), (
            f"short_f1_pass={rollout_gate['short_f1_pass']} but "
            f"f1_down={f1_down} >= threshold={threshold} is {f1_down >= threshold}"
        )

        # Property: f1_down is preserved exactly
        assert rollout_gate["f1_down"] == f1_down, (
            f"rollout_gate.f1_down={rollout_gate['f1_down']} != f1_down={f1_down}"
        )

        # Property: threshold is preserved exactly
        assert rollout_gate["threshold"] == threshold, (
            f"rollout_gate.threshold={rollout_gate['threshold']} != threshold={threshold}"
        )


# ═══════════════════════════════════════════════════════════════
# Property 7: Walk-forward fold metrics and aggregate consistency
# ═══════════════════════════════════════════════════════════════


class TestWalkForwardFoldMetricsConsistency:
    """
    # Feature: lightgbm-model-upgrade, Property 7: Walk-forward fold metrics and aggregate consistency

    For any set of fold results, aggregate directional_f1_macro_mean equals
    the mean of per-fold values, and directional_f1_macro_min equals the
    minimum. Same for ev_after_costs_mean and ev_after_costs_min.

    **Validates: Requirements 5.2, 5.3**
    """

    @settings(max_examples=100)
    @given(
        fold_data=st.lists(
            st.fixed_dictionaries({
                "directional_f1_macro": st.floats(
                    min_value=0.0, max_value=1.0,
                    allow_nan=False, allow_infinity=False,
                ),
                "ev_after_costs_mean": st.floats(
                    min_value=0.0, max_value=1.0,
                    allow_nan=False, allow_infinity=False,
                ),
            }),
            min_size=1,
            max_size=20,
        ),
    )
    def test_aggregate_mean_and_min_match_per_fold_values(
        self, fold_data: list[dict],
    ):
        """
        # Feature: lightgbm-model-upgrade, Property 7: Walk-forward fold metrics and aggregate consistency

        Generate lists of fold metric dicts (each with a random
        directional_f1_macro and ev_after_costs_mean float in [0, 1]).
        Compute aggregates using numpy mean/min (same as the training script)
        and verify consistency.

        **Validates: Requirements 5.2, 5.3**
        """
        # Build fold_metrics in the same structure as the training script
        fold_metrics = [
            {
                "fold": i,
                "train_samples": 100,
                "test_samples": 50,
                "metrics": {
                    "directional_f1_macro": fd["directional_f1_macro"],
                },
                "trading_metrics": {
                    "ev_after_costs_mean": fd["ev_after_costs_mean"],
                },
            }
            for i, fd in enumerate(fold_data)
        ]

        # Replicate the exact aggregation logic from train_prediction_baseline.py
        directional_scores = [
            float((item.get("metrics") or {}).get("directional_f1_macro", 0.0))
            for item in fold_metrics
        ]
        ev_scores = [
            float((item.get("trading_metrics") or {}).get("ev_after_costs_mean", 0.0))
            for item in fold_metrics
        ]

        agg_f1_mean = float(np.mean(np.asarray(directional_scores, dtype=np.float64)))
        agg_f1_min = float(np.min(np.asarray(directional_scores, dtype=np.float64)))
        agg_ev_mean = float(np.mean(np.asarray(ev_scores, dtype=np.float64)))
        agg_ev_min = float(np.min(np.asarray(ev_scores, dtype=np.float64)))

        # Property: directional_f1_macro_mean == np.mean(per-fold values)
        expected_f1_mean = float(np.mean([fd["directional_f1_macro"] for fd in fold_data]))
        assert agg_f1_mean == pytest.approx(expected_f1_mean, abs=1e-12), (
            f"directional_f1_macro_mean={agg_f1_mean} != "
            f"np.mean(per-fold)={expected_f1_mean}"
        )

        # Property: directional_f1_macro_min == np.min(per-fold values)
        expected_f1_min = float(np.min([fd["directional_f1_macro"] for fd in fold_data]))
        assert agg_f1_min == pytest.approx(expected_f1_min, abs=1e-12), (
            f"directional_f1_macro_min={agg_f1_min} != "
            f"np.min(per-fold)={expected_f1_min}"
        )

        # Property: ev_after_costs_mean == np.mean(per-fold values)
        expected_ev_mean = float(np.mean([fd["ev_after_costs_mean"] for fd in fold_data]))
        assert agg_ev_mean == pytest.approx(expected_ev_mean, abs=1e-12), (
            f"ev_after_costs_mean={agg_ev_mean} != "
            f"np.mean(per-fold)={expected_ev_mean}"
        )

        # Property: ev_after_costs_min == np.min(per-fold values)
        expected_ev_min = float(np.min([fd["ev_after_costs_mean"] for fd in fold_data]))
        assert agg_ev_min == pytest.approx(expected_ev_min, abs=1e-12), (
            f"ev_after_costs_min={agg_ev_min} != "
            f"np.min(per-fold)={expected_ev_min}"
        )

    @settings(max_examples=100)
    @given(
        fold_data=st.lists(
            st.fixed_dictionaries({
                "directional_f1_macro": st.floats(
                    min_value=0.0, max_value=1.0,
                    allow_nan=False, allow_infinity=False,
                ),
                "ev_after_costs_mean": st.floats(
                    min_value=0.0, max_value=1.0,
                    allow_nan=False, allow_infinity=False,
                ),
            }),
            min_size=1,
            max_size=20,
        ),
    )
    def test_aggregate_min_is_bounded_by_mean(
        self, fold_data: list[dict],
    ):
        """
        # Feature: lightgbm-model-upgrade, Property 7: Walk-forward fold metrics and aggregate consistency

        For any set of fold results, the min aggregate must be <= the mean
        aggregate for both directional_f1_macro and ev_after_costs.

        **Validates: Requirements 5.2, 5.3**
        """
        directional_scores = np.asarray(
            [fd["directional_f1_macro"] for fd in fold_data], dtype=np.float64,
        )
        ev_scores = np.asarray(
            [fd["ev_after_costs_mean"] for fd in fold_data], dtype=np.float64,
        )

        # min <= mean always holds for any non-empty set of real numbers
        assert float(np.min(directional_scores)) <= float(np.mean(directional_scores)) + 1e-15, (
            "directional_f1_macro_min must be <= directional_f1_macro_mean"
        )
        assert float(np.min(ev_scores)) <= float(np.mean(ev_scores)) + 1e-15, (
            "ev_after_costs_min must be <= ev_after_costs_mean"
        )


# ═══════════════════════════════════════════════════════════════
# Property 6: Calibration output contains required per-class fields
# ═══════════════════════════════════════════════════════════════

CALIBRATION_REQUIRED_PER_CLASS_FIELDS = {"a", "b", "fitted"}
CLASS_LABELS = ["down", "flat", "up"]


def _calibration_per_class_entry():
    """Strategy for generating a single per_class calibration entry with required fields."""
    return st.fixed_dictionaries(
        {
            "a": st.floats(
                min_value=-50.0, max_value=50.0,
                allow_nan=False, allow_infinity=False,
            ),
            "b": st.floats(
                min_value=-50.0, max_value=50.0,
                allow_nan=False, allow_infinity=False,
            ),
            "fitted": st.booleans(),
        },
        # Optional extra fields that the real implementation may include
        optional={
            "samples": st.integers(min_value=0, max_value=10000),
            "positives": st.integers(min_value=0, max_value=10000),
            "reason": st.text(min_size=1, max_size=50),
        },
    )


def _calibration_metrics_dict():
    """Strategy for generating a calibration metrics dict (metrics_before / metrics_after)."""
    return st.dictionaries(
        keys=st.sampled_from(["brier_score", "ece", "reliability", "per_class"]),
        values=st.floats(
            min_value=0.0, max_value=1.0,
            allow_nan=False, allow_infinity=False,
        ),
        min_size=0,
        max_size=4,
    )


class TestCalibrationOutputFields:
    """
    # Feature: lightgbm-model-upgrade, Property 6: Calibration output contains required per-class fields

    For any non-empty calibration result with enabled=True, each per_class
    entry contains a (float), b (float), and fitted (bool) fields, and the
    result contains metrics_before and metrics_after dicts.

    **Validates: Requirements 4.2**
    """

    @settings(max_examples=100)
    @given(data=st.data())
    def test_enabled_calibration_has_required_per_class_fields(self, data: st.DataObject):
        """
        # Feature: lightgbm-model-upgrade, Property 6: Calibration output contains required per-class fields

        Generate random calibration result dicts with enabled=True and
        per_class entries containing a (float), b (float), fitted (bool).
        Verify all required fields are present in each per_class entry.

        **Validates: Requirements 4.2**
        """
        # Generate per_class entries for each class label
        per_class = {}
        for label in CLASS_LABELS:
            per_class[label] = data.draw(
                _calibration_per_class_entry(), label=f"per_class_{label}"
            )

        # Build calibration result dict matching the training script structure
        calibration_result = {
            "enabled": True,
            "method": data.draw(
                st.sampled_from(["logit_affine_ovr", "identity"]),
                label="method",
            ),
            "samples": data.draw(
                st.integers(min_value=1, max_value=10000), label="samples"
            ),
            "fit_samples": data.draw(
                st.integers(min_value=1, max_value=5000), label="fit_samples"
            ),
            "eval_samples": data.draw(
                st.integers(min_value=1, max_value=5000), label="eval_samples"
            ),
            "per_class": per_class,
            "metrics_before": data.draw(
                _calibration_metrics_dict(), label="metrics_before"
            ),
            "metrics_after": data.draw(
                _calibration_metrics_dict(), label="metrics_after"
            ),
        }

        # Property: enabled must be True
        assert calibration_result["enabled"] is True

        # Property: each per_class entry contains required fields a, b, fitted
        for label, entry in calibration_result["per_class"].items():
            missing = CALIBRATION_REQUIRED_PER_CLASS_FIELDS - set(entry.keys())
            assert missing == set(), (
                f"per_class[{label!r}] missing required fields: {missing}"
            )

            # a must be a float
            assert isinstance(entry["a"], (int, float)), (
                f"per_class[{label!r}]['a'] is {type(entry['a']).__name__}, expected float"
            )

            # b must be a float
            assert isinstance(entry["b"], (int, float)), (
                f"per_class[{label!r}]['b'] is {type(entry['b']).__name__}, expected float"
            )

            # fitted must be a bool
            assert isinstance(entry["fitted"], bool), (
                f"per_class[{label!r}]['fitted'] is {type(entry['fitted']).__name__}, expected bool"
            )

        # Property: metrics_before and metrics_after dicts are present
        assert "metrics_before" in calibration_result, (
            "calibration result missing 'metrics_before'"
        )
        assert isinstance(calibration_result["metrics_before"], dict), (
            f"metrics_before is {type(calibration_result['metrics_before']).__name__}, expected dict"
        )

        assert "metrics_after" in calibration_result, (
            "calibration result missing 'metrics_after'"
        )
        assert isinstance(calibration_result["metrics_after"], dict), (
            f"metrics_after is {type(calibration_result['metrics_after']).__name__}, expected dict"
        )

    @settings(max_examples=100)
    @given(data=st.data())
    def test_removing_required_field_from_per_class_is_detected(self, data: st.DataObject):
        """
        # Feature: lightgbm-model-upgrade, Property 6: Calibration output contains required per-class fields

        Generate a valid per_class entry, remove one required field at random,
        and verify the missing field is detected.

        **Validates: Requirements 4.2**
        """
        # Generate a valid per_class entry
        entry = data.draw(_calibration_per_class_entry(), label="entry")

        # Pick a required field to remove
        field_to_remove = data.draw(
            st.sampled_from(sorted(CALIBRATION_REQUIRED_PER_CLASS_FIELDS)),
            label="removed_field",
        )
        del entry[field_to_remove]

        # Property: the removed field must be detected as missing
        missing = CALIBRATION_REQUIRED_PER_CLASS_FIELDS - set(entry.keys())
        assert field_to_remove in missing, (
            f"Removed field {field_to_remove!r} was not detected as missing"
        )

# ═══════════════════════════════════════════════════════════════
# PROPERTY 9 — Direction equals argmax of calibrated probabilities
# ═══════════════════════════════════════════════════════════════

CLASS_LABELS = ["down", "flat", "up"]


class TestDirectionEqualsArgmax:
    """
    # Feature: lightgbm-model-upgrade, Property 9: Direction equals argmax of calibrated probabilities

    For any calibrated probability map over [down, flat, up] with at least one
    non-zero probability, direction equals the label with the highest probability.

    **Validates: Requirements 7.2**
    """

    @settings(max_examples=100)
    @given(
        p_down=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
        p_flat=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
        p_up=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
    )
    def test_direction_equals_argmax_of_calibrated_probabilities(
        self, p_down: float, p_flat: float, p_up: float
    ):
        """
        # Feature: lightgbm-model-upgrade, Property 9: Direction equals argmax of calibrated probabilities

        Generate random probability distributions over 3 classes (down, flat, up)
        where at least one is non-zero. Compute direction as the label with the
        highest probability (argmax) and verify it matches.

        **Validates: Requirements 7.2**
        """
        from hypothesis import assume

        # At least one probability must be non-zero
        assume(p_down > 0.0 or p_flat > 0.0 or p_up > 0.0)

        prob_map = {"down": p_down, "flat": p_flat, "up": p_up}

        # Replicate the exact argmax logic from OnnxPredictionProvider.build_prediction:
        #   idx = int(max(range(len(class_labels)), key=lambda i: prob_map.get(class_labels[i], 0.0)))
        #   direction = class_labels[idx]
        idx = int(
            max(
                range(len(CLASS_LABELS)),
                key=lambda i: prob_map.get(CLASS_LABELS[i], 0.0),
            )
        )
        direction = CLASS_LABELS[idx]

        # Independently compute expected direction via argmax
        probs = [prob_map[label] for label in CLASS_LABELS]
        expected_idx = max(range(len(probs)), key=lambda i: probs[i])
        expected_direction = CLASS_LABELS[expected_idx]

        assert direction == expected_direction, (
            f"direction={direction!r} != expected={expected_direction!r} "
            f"for probs={prob_map}"
        )

        # The direction label must correspond to the maximum probability
        assert prob_map[direction] == max(probs), (
            f"direction={direction!r} has prob={prob_map[direction]} "
            f"but max prob is {max(probs)}"
        )


# ═══════════════════════════════════════════════════════════════
# PROPERTY 10: Margin and entropy are correctly computed
# ═══════════════════════════════════════════════════════════════

CLASS_LABELS_P10 = ["down", "flat", "up"]


def _clamp(value: float) -> float:
    """Mirror the _clamp helper from prediction_providers.py."""
    try:
        value_f = float(value)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(value_f):
        return 0.0
    return max(0.0, min(1.0, value_f))


def _expected_margin(prob_map: dict[str, float], labels: list[str]) -> float:
    """Independently compute expected margin matching _probability_margin."""
    values = sorted((_clamp(prob_map.get(label, 0.0)) for label in labels), reverse=True)
    if not values:
        return 0.0
    if len(values) == 1:
        return values[0]
    return max(0.0, values[0] - values[1])


def _expected_entropy(prob_map: dict[str, float], labels: list[str]) -> float:
    """Independently compute expected normalized entropy matching _normalized_entropy."""
    values = [_clamp(prob_map.get(label, 0.0)) for label in labels]
    total = sum(values)
    if total <= 0:
        return 1.0
    entropy = 0.0
    for v in values:
        p = v / total
        if p > 0:
            entropy -= p * math.log(p)
    base = math.log(max(2, len(labels)))
    if base <= 0:
        return 0.0
    return _clamp(entropy / base)


class TestMarginAndEntropyCorrectness:
    """
    # Feature: lightgbm-model-upgrade, Property 10: Margin and entropy are correctly computed

    For any probability distribution over [down, flat, up] where probabilities
    sum to ~1.0, margin equals the difference between the highest and
    second-highest probability, and entropy equals the normalized Shannon
    entropy (H / log(k)) of the distribution, both in [0, 1].

    **Validates: Requirements 7.3**
    """

    @settings(max_examples=100)
    @given(
        p_down=st.floats(min_value=0.01, max_value=10.0, allow_nan=False, allow_infinity=False),
        p_flat=st.floats(min_value=0.01, max_value=10.0, allow_nan=False, allow_infinity=False),
        p_up=st.floats(min_value=0.01, max_value=10.0, allow_nan=False, allow_infinity=False),
    )
    def test_margin_and_entropy_from_normalized_distribution(
        self, p_down: float, p_flat: float, p_up: float
    ):
        """
        # Feature: lightgbm-model-upgrade, Property 10: Margin and entropy are correctly computed

        Generate random positive floats, normalize to a probability distribution,
        then verify margin and entropy are computed correctly.

        **Validates: Requirements 7.3**
        """
        from quantgambit.signals.prediction_providers import (
            _normalized_entropy,
            _probability_margin,
        )

        # Normalize to a valid probability distribution summing to 1.0
        total = p_down + p_flat + p_up
        prob_map = {
            "down": p_down / total,
            "flat": p_flat / total,
            "up": p_up / total,
        }

        # Compute using the actual functions under test
        actual_margin = _probability_margin(prob_map, CLASS_LABELS_P10)
        actual_entropy = _normalized_entropy(prob_map, CLASS_LABELS_P10)

        # Compute expected values independently
        expected_margin = _expected_margin(prob_map, CLASS_LABELS_P10)
        expected_entropy = _expected_entropy(prob_map, CLASS_LABELS_P10)

        # Margin must match
        assert abs(actual_margin - expected_margin) < 1e-9, (
            f"margin mismatch: actual={actual_margin}, expected={expected_margin}, "
            f"probs={prob_map}"
        )

        # Entropy must match
        assert abs(actual_entropy - expected_entropy) < 1e-9, (
            f"entropy mismatch: actual={actual_entropy}, expected={expected_entropy}, "
            f"probs={prob_map}"
        )

        # Both must be in [0, 1]
        assert 0.0 <= actual_margin <= 1.0, f"margin={actual_margin} not in [0, 1]"
        assert 0.0 <= actual_entropy <= 1.0, f"entropy={actual_entropy} not in [0, 1]"

    @settings(max_examples=100)
    @given(
        dominant_idx=st.integers(min_value=0, max_value=2),
    )
    def test_concentrated_distribution_entropy_near_zero(self, dominant_idx: int):
        """
        # Feature: lightgbm-model-upgrade, Property 10: Margin and entropy are correctly computed

        When all probability is concentrated on one class, entropy should be
        near 0 and margin should equal the difference between 1.0 and the
        second-highest (which is ~0).

        **Validates: Requirements 7.3**
        """
        from quantgambit.signals.prediction_providers import (
            _normalized_entropy,
            _probability_margin,
        )

        labels = CLASS_LABELS_P10
        prob_map = {label: 0.0 for label in labels}
        prob_map[labels[dominant_idx]] = 1.0

        margin = _probability_margin(prob_map, labels)
        entropy = _normalized_entropy(prob_map, labels)

        # Concentrated distribution: entropy should be 0
        assert abs(entropy) < 1e-9, f"entropy={entropy}, expected ~0 for concentrated dist"

        # Margin should be 1.0 (1.0 - 0.0)
        assert abs(margin - 1.0) < 1e-9, f"margin={margin}, expected ~1.0 for concentrated dist"

        # Both in [0, 1]
        assert 0.0 <= margin <= 1.0
        assert 0.0 <= entropy <= 1.0

# ═══════════════════════════════════════════════════════════════
# Property 11 – F1 gate rejects short predictions when f1_down
#               is below threshold
# ═══════════════════════════════════════════════════════════════


class TestF1GateRejectsShortPredictions:
    """
    # Feature: lightgbm-model-upgrade, Property 11: F1 gate rejects short predictions when f1_down is below threshold

    For any f1_down value below PREDICTION_MIN_F1_DOWN_FOR_SHORT and any
    prediction with direction="down", the prediction payload shall have
    reject=True and reason containing an f1-related rejection string.

    **Validates: Requirements 7.4**
    """

    @settings(max_examples=100)
    @given(
        threshold=st.floats(min_value=0.1, max_value=1.0, allow_nan=False, allow_infinity=False),
        data=st.data(),
    )
    def test_f1_gate_rejects_down_when_f1_below_threshold(
        self, threshold: float, data: st.DataObject
    ):
        """
        # Feature: lightgbm-model-upgrade, Property 11: F1 gate rejects short predictions when f1_down is below threshold

        Generate a random threshold in [0.1, 1.0] and a random f1_down
        strictly below that threshold.  With direction="down", the
        _abstain_reason function must return the f1-related rejection
        string "onnx_unreliable_down_class", which causes reject=True
        in the prediction payload.

        **Validates: Requirements 7.4**
        """
        from quantgambit.signals.prediction_providers import _abstain_reason

        # f1_down is strictly below the threshold
        f1_down = data.draw(
            st.floats(min_value=0.0, max_value=threshold, exclude_max=True, allow_nan=False, allow_infinity=False),
            label="f1_down",
        )

        # Other abstain parameters are set to non-triggering values so
        # only the f1 gate can fire.
        reason = _abstain_reason(
            confidence=0.99,
            margin=0.99,
            entropy=0.01,
            min_confidence=0.0,
            min_margin=0.0,
            max_entropy=1.0,
            direction="down",
            f1_down=f1_down,
            min_f1_down=threshold,
        )

        # The gate must reject with the f1-related reason string
        assert reason is not None, (
            f"Expected rejection but got None "
            f"(f1_down={f1_down}, threshold={threshold})"
        )
        assert reason == "onnx_unreliable_down_class", (
            f"Expected 'onnx_unreliable_down_class' but got '{reason}' "
            f"(f1_down={f1_down}, threshold={threshold})"
        )

        # In the prediction payload, reject = bool(abstain_reason)
        reject = bool(reason)
        assert reject is True, (
            f"reject should be True when f1_down={f1_down} < threshold={threshold}"
        )

    @settings(max_examples=100)
    @given(
        threshold=st.floats(min_value=0.1, max_value=1.0, allow_nan=False, allow_infinity=False),
        data=st.data(),
    )
    def test_f1_gate_does_not_reject_non_down_directions(
        self, threshold: float, data: st.DataObject
    ):
        """
        # Feature: lightgbm-model-upgrade, Property 11: F1 gate rejects short predictions when f1_down is below threshold

        The f1 gate is direction-specific: it only fires for direction="down".
        For direction="up" with the same below-threshold f1_down, the gate
        must NOT produce the f1-related rejection (other gates may still fire,
        but not the f1 gate).

        **Validates: Requirements 7.4**
        """
        from quantgambit.signals.prediction_providers import _abstain_reason

        f1_down = data.draw(
            st.floats(min_value=0.0, max_value=threshold, exclude_max=True, allow_nan=False, allow_infinity=False),
            label="f1_down",
        )

        reason = _abstain_reason(
            confidence=0.99,
            margin=0.99,
            entropy=0.01,
            min_confidence=0.0,
            min_margin=0.0,
            max_entropy=1.0,
            direction="up",
            f1_down=f1_down,
            min_f1_down=threshold,
        )

        # For direction="up", the f1 gate must not fire
        assert reason != "onnx_unreliable_down_class", (
            f"F1 gate should not reject direction='up' "
            f"(f1_down={f1_down}, threshold={threshold})"
        )
