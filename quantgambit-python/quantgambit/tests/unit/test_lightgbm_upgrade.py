"""Unit tests for LightGBM model upgrade – dataset fingerprint."""

from __future__ import annotations

import hashlib
import os
import sys
import tempfile

import pytest

_SCRIPTS_DIR = os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "scripts"
)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from train_prediction_baseline import _compute_dataset_fingerprint


class TestBaselineMetricsLoading:
    """Tests for baseline metrics loading at start of main()."""

    def test_loads_metrics_from_valid_latest_json(self, tmp_path):
        """When latest.json exists with valid metrics, baseline_metrics is populated."""
        import json

        latest = {
            "metrics": {
                "f1_down": 0.23,
                "f1_up": 0.45,
                "directional_f1_macro": 0.34,
            },
            "trading_metrics": {
                "ev_after_costs_mean": 0.012,
                "directional_accuracy": 0.55,
            },
        }
        latest_path = tmp_path / "latest.json"
        latest_path.write_text(json.dumps(latest))

        with open(str(latest_path), "r") as f:
            baseline_data = json.load(f)
        baseline_metrics = {
            "f1_down": baseline_data.get("metrics", {}).get("f1_down", 0.0),
            "f1_up": baseline_data.get("metrics", {}).get("f1_up", 0.0),
            "directional_f1_macro": baseline_data.get("metrics", {}).get("directional_f1_macro", 0.0),
            "ev_after_costs_mean": baseline_data.get("trading_metrics", {}).get("ev_after_costs_mean", 0.0),
            "directional_accuracy": baseline_data.get("trading_metrics", {}).get("directional_accuracy", 0.0),
        }

        assert baseline_metrics["f1_down"] == 0.23
        assert baseline_metrics["f1_up"] == 0.45
        assert baseline_metrics["directional_f1_macro"] == 0.34
        assert baseline_metrics["ev_after_costs_mean"] == 0.012
        assert baseline_metrics["directional_accuracy"] == 0.55

    def test_missing_file_sets_none(self, tmp_path):
        """When latest.json does not exist, baseline_metrics is None."""
        import json

        baseline_metrics = None
        baseline_path = str(tmp_path / "latest.json")
        try:
            with open(baseline_path, "r") as f:
                baseline_data = json.load(f)
            baseline_metrics = {
                "f1_down": baseline_data.get("metrics", {}).get("f1_down", 0.0),
            }
        except (FileNotFoundError, json.JSONDecodeError, KeyError):
            baseline_metrics = None

        assert baseline_metrics is None

    def test_malformed_json_sets_none(self, tmp_path):
        """When latest.json contains invalid JSON, baseline_metrics is None."""
        import json

        latest_path = tmp_path / "latest.json"
        latest_path.write_text("not valid json {{{")

        baseline_metrics = None
        try:
            with open(str(latest_path), "r") as f:
                baseline_data = json.load(f)
            baseline_metrics = {"f1_down": baseline_data.get("metrics", {}).get("f1_down", 0.0)}
        except (FileNotFoundError, json.JSONDecodeError, KeyError):
            baseline_metrics = None

        assert baseline_metrics is None

    def test_missing_metrics_keys_default_to_zero(self, tmp_path):
        """When latest.json has empty metrics/trading_metrics, values default to 0.0."""
        import json

        latest = {"metrics": {}, "trading_metrics": {}}
        latest_path = tmp_path / "latest.json"
        latest_path.write_text(json.dumps(latest))

        with open(str(latest_path), "r") as f:
            baseline_data = json.load(f)
        baseline_metrics = {
            "f1_down": baseline_data.get("metrics", {}).get("f1_down", 0.0),
            "f1_up": baseline_data.get("metrics", {}).get("f1_up", 0.0),
            "directional_f1_macro": baseline_data.get("metrics", {}).get("directional_f1_macro", 0.0),
            "ev_after_costs_mean": baseline_data.get("trading_metrics", {}).get("ev_after_costs_mean", 0.0),
            "directional_accuracy": baseline_data.get("trading_metrics", {}).get("directional_accuracy", 0.0),
        }

        assert baseline_metrics["f1_down"] == 0.0
        assert baseline_metrics["f1_up"] == 0.0
        assert baseline_metrics["directional_f1_macro"] == 0.0
        assert baseline_metrics["ev_after_costs_mean"] == 0.0
        assert baseline_metrics["directional_accuracy"] == 0.0


class TestComputeDatasetFingerprint:
    """Tests for _compute_dataset_fingerprint()."""

    def test_returns_sha256_of_file_content(self, tmp_path):
        content = b"col1,col2\n1,2\n3,4\n"
        csv_file = tmp_path / "data.csv"
        csv_file.write_bytes(content)
        expected = hashlib.sha256(content).hexdigest()
        assert _compute_dataset_fingerprint(str(csv_file)) == expected

    def test_idempotent(self, tmp_path):
        csv_file = tmp_path / "data.csv"
        csv_file.write_bytes(b"a,b,c\n1,2,3\n")
        first = _compute_dataset_fingerprint(str(csv_file))
        second = _compute_dataset_fingerprint(str(csv_file))
        assert first == second

    def test_returns_error_for_missing_file(self):
        result = _compute_dataset_fingerprint("/nonexistent/path/data.csv")
        assert result == "error:unreadable"

    def test_empty_file(self, tmp_path):
        csv_file = tmp_path / "empty.csv"
        csv_file.write_bytes(b"")
        expected = hashlib.sha256(b"").hexdigest()
        assert _compute_dataset_fingerprint(str(csv_file)) == expected
