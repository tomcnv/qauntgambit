"""Unit tests for ExecutionSimulator.calibrate_from_live() method.

Tests the calibration functionality that updates simulator parameters
based on live execution data.

**Validates: Requirements 5.4**
"""

import pytest
import math
from quantgambit.integration.execution_simulator import (
    ExecutionSimulator,
    ExecutionSimulatorConfig,
    CalibrationResult,
)


class TestCalibrateFromLiveEmptyInput:
    """Tests for calibrate_from_live with empty input."""

    def test_empty_list_returns_current_config_values(self):
        """Empty list should return current config values without changes."""
        config = ExecutionSimulatorConfig(
            base_latency_ms=50.0,
            latency_std_ms=20.0,
            base_slippage_bps=1.0,
            partial_fill_prob_small=0.02,
            partial_fill_prob_medium=0.10,
            partial_fill_prob_large=0.30,
        )
        simulator = ExecutionSimulator(config)
        
        result = simulator.calibrate_from_live([])
        
        assert result.num_fills == 0
        assert result.latency_mean_ms == 50.0
        assert result.latency_std_ms == 20.0
        assert result.slippage_mean_bps == 1.0
        assert result.partial_fill_rate_small == 0.02
        assert result.partial_fill_rate_medium == 0.10
        assert result.partial_fill_rate_large == 0.30
        assert result.parameters_updated == []
        assert result.fills_by_size_bucket == {"small": 0, "medium": 0, "large": 0}

    def test_empty_list_does_not_modify_config(self):
        """Empty list should not modify the config."""
        config = ExecutionSimulatorConfig(
            base_latency_ms=50.0,
            latency_std_ms=20.0,
            base_slippage_bps=1.0,
        )
        simulator = ExecutionSimulator(config)
        
        simulator.calibrate_from_live([])
        
        assert simulator.config.base_latency_ms == 50.0
        assert simulator.config.latency_std_ms == 20.0
        assert simulator.config.base_slippage_bps == 1.0


class TestCalibrateFromLiveLatency:
    """Tests for latency calibration."""

    def test_single_fill_updates_latency_mean(self):
        """Single fill should update latency mean."""
        simulator = ExecutionSimulator()
        live_fills = [{"latency_ms": 75.0, "slippage_bps": 1.0}]
        
        result = simulator.calibrate_from_live(live_fills)
        
        assert result.latency_mean_ms == 75.0
        assert simulator.config.base_latency_ms == 75.0
        assert "base_latency_ms" in result.parameters_updated

    def test_multiple_fills_calculates_correct_mean(self):
        """Multiple fills should calculate correct mean latency."""
        simulator = ExecutionSimulator()
        live_fills = [
            {"latency_ms": 40.0, "slippage_bps": 1.0},
            {"latency_ms": 50.0, "slippage_bps": 1.0},
            {"latency_ms": 60.0, "slippage_bps": 1.0},
        ]
        
        result = simulator.calibrate_from_live(live_fills)
        
        assert result.latency_mean_ms == 50.0
        assert simulator.config.base_latency_ms == 50.0

    def test_multiple_fills_calculates_correct_std(self):
        """Multiple fills should calculate correct standard deviation."""
        simulator = ExecutionSimulator()
        # Values: 40, 50, 60 -> mean=50, variance=((10^2 + 0 + 10^2)/3) = 200/3
        # std = sqrt(200/3) ≈ 8.165
        live_fills = [
            {"latency_ms": 40.0, "slippage_bps": 1.0},
            {"latency_ms": 50.0, "slippage_bps": 1.0},
            {"latency_ms": 60.0, "slippage_bps": 1.0},
        ]
        
        result = simulator.calibrate_from_live(live_fills)
        
        expected_std = math.sqrt(200 / 3)
        assert abs(result.latency_std_ms - expected_std) < 0.001
        assert abs(simulator.config.latency_std_ms - expected_std) < 0.001
        assert "latency_std_ms" in result.parameters_updated

    def test_single_fill_preserves_existing_std(self):
        """Single fill should preserve existing std (can't calculate from 1 sample)."""
        config = ExecutionSimulatorConfig(latency_std_ms=25.0)
        simulator = ExecutionSimulator(config)
        live_fills = [{"latency_ms": 75.0, "slippage_bps": 1.0}]
        
        result = simulator.calibrate_from_live(live_fills)
        
        # With single fill, std should be preserved from config
        assert result.latency_std_ms == 25.0
        assert simulator.config.latency_std_ms == 25.0

    def test_missing_latency_uses_default(self):
        """Missing latency_ms should use config default."""
        config = ExecutionSimulatorConfig(base_latency_ms=50.0)
        simulator = ExecutionSimulator(config)
        live_fills = [
            {"slippage_bps": 1.0},  # Missing latency_ms
            {"latency_ms": 100.0, "slippage_bps": 1.0},
        ]
        
        result = simulator.calibrate_from_live(live_fills)
        
        # Mean of 50 (default) and 100 = 75
        assert result.latency_mean_ms == 75.0


class TestCalibrateFromLiveSlippage:
    """Tests for slippage calibration."""

    def test_single_fill_updates_slippage(self):
        """Single fill should update slippage."""
        simulator = ExecutionSimulator()
        live_fills = [{"latency_ms": 50.0, "slippage_bps": 2.5}]
        
        result = simulator.calibrate_from_live(live_fills)
        
        assert result.slippage_mean_bps == 2.5
        assert simulator.config.base_slippage_bps == 2.5
        assert "base_slippage_bps" in result.parameters_updated

    def test_multiple_fills_calculates_correct_mean_slippage(self):
        """Multiple fills should calculate correct mean slippage."""
        simulator = ExecutionSimulator()
        live_fills = [
            {"latency_ms": 50.0, "slippage_bps": 0.5},
            {"latency_ms": 50.0, "slippage_bps": 1.0},
            {"latency_ms": 50.0, "slippage_bps": 1.5},
        ]
        
        result = simulator.calibrate_from_live(live_fills)
        
        assert result.slippage_mean_bps == 1.0
        assert simulator.config.base_slippage_bps == 1.0

    def test_missing_slippage_uses_default(self):
        """Missing slippage_bps should use config default."""
        config = ExecutionSimulatorConfig(base_slippage_bps=1.0)
        simulator = ExecutionSimulator(config)
        live_fills = [
            {"latency_ms": 50.0},  # Missing slippage_bps
            {"latency_ms": 50.0, "slippage_bps": 3.0},
        ]
        
        result = simulator.calibrate_from_live(live_fills)
        
        # Mean of 1.0 (default) and 3.0 = 2.0
        assert result.slippage_mean_bps == 2.0


class TestCalibrateFromLivePartialFills:
    """Tests for partial fill rate calibration."""

    def test_fills_bucketed_by_size_ratio(self):
        """Fills should be bucketed by size_ratio."""
        simulator = ExecutionSimulator()
        live_fills = [
            {"latency_ms": 50.0, "slippage_bps": 1.0, "size_ratio": 0.005, "is_partial": False},  # small
            {"latency_ms": 50.0, "slippage_bps": 1.0, "size_ratio": 0.008, "is_partial": False},  # small
            {"latency_ms": 50.0, "slippage_bps": 1.0, "size_ratio": 0.02, "is_partial": False},   # medium
            {"latency_ms": 50.0, "slippage_bps": 1.0, "size_ratio": 0.03, "is_partial": False},   # medium
            {"latency_ms": 50.0, "slippage_bps": 1.0, "size_ratio": 0.04, "is_partial": False},   # medium
            {"latency_ms": 50.0, "slippage_bps": 1.0, "size_ratio": 0.10, "is_partial": False},   # large
        ]
        
        result = simulator.calibrate_from_live(live_fills)
        
        assert result.fills_by_size_bucket["small"] == 2
        assert result.fills_by_size_bucket["medium"] == 3
        assert result.fills_by_size_bucket["large"] == 1

    def test_partial_fill_rate_calculated_correctly(self):
        """Partial fill rate should be calculated correctly for each bucket."""
        simulator = ExecutionSimulator()
        # Create enough fills to trigger updates (MIN_FILLS_FOR_UPDATE = 5)
        live_fills = [
            # Small bucket: 2/6 partial = 0.333
            {"latency_ms": 50.0, "slippage_bps": 1.0, "size_ratio": 0.005, "is_partial": True},
            {"latency_ms": 50.0, "slippage_bps": 1.0, "size_ratio": 0.006, "is_partial": True},
            {"latency_ms": 50.0, "slippage_bps": 1.0, "size_ratio": 0.007, "is_partial": False},
            {"latency_ms": 50.0, "slippage_bps": 1.0, "size_ratio": 0.008, "is_partial": False},
            {"latency_ms": 50.0, "slippage_bps": 1.0, "size_ratio": 0.009, "is_partial": False},
            {"latency_ms": 50.0, "slippage_bps": 1.0, "size_ratio": 0.0095, "is_partial": False},
            # Medium bucket: 3/5 partial = 0.6
            {"latency_ms": 50.0, "slippage_bps": 1.0, "size_ratio": 0.02, "is_partial": True},
            {"latency_ms": 50.0, "slippage_bps": 1.0, "size_ratio": 0.025, "is_partial": True},
            {"latency_ms": 50.0, "slippage_bps": 1.0, "size_ratio": 0.03, "is_partial": True},
            {"latency_ms": 50.0, "slippage_bps": 1.0, "size_ratio": 0.035, "is_partial": False},
            {"latency_ms": 50.0, "slippage_bps": 1.0, "size_ratio": 0.04, "is_partial": False},
            # Large bucket: 4/5 partial = 0.8
            {"latency_ms": 50.0, "slippage_bps": 1.0, "size_ratio": 0.10, "is_partial": True},
            {"latency_ms": 50.0, "slippage_bps": 1.0, "size_ratio": 0.15, "is_partial": True},
            {"latency_ms": 50.0, "slippage_bps": 1.0, "size_ratio": 0.20, "is_partial": True},
            {"latency_ms": 50.0, "slippage_bps": 1.0, "size_ratio": 0.25, "is_partial": True},
            {"latency_ms": 50.0, "slippage_bps": 1.0, "size_ratio": 0.30, "is_partial": False},
        ]
        
        result = simulator.calibrate_from_live(live_fills)
        
        assert abs(result.partial_fill_rate_small - 2/6) < 0.001
        assert abs(result.partial_fill_rate_medium - 3/5) < 0.001
        assert abs(result.partial_fill_rate_large - 4/5) < 0.001

    def test_partial_fill_prob_updated_with_enough_data(self):
        """Partial fill probabilities should be updated when enough data exists."""
        simulator = ExecutionSimulator()
        # Create 5 fills in small bucket (minimum required)
        live_fills = [
            {"latency_ms": 50.0, "slippage_bps": 1.0, "size_ratio": 0.005, "is_partial": True},
            {"latency_ms": 50.0, "slippage_bps": 1.0, "size_ratio": 0.006, "is_partial": False},
            {"latency_ms": 50.0, "slippage_bps": 1.0, "size_ratio": 0.007, "is_partial": False},
            {"latency_ms": 50.0, "slippage_bps": 1.0, "size_ratio": 0.008, "is_partial": False},
            {"latency_ms": 50.0, "slippage_bps": 1.0, "size_ratio": 0.009, "is_partial": False},
        ]
        
        result = simulator.calibrate_from_live(live_fills)
        
        # 1/5 = 0.2 partial fill rate
        assert simulator.config.partial_fill_prob_small == 0.2
        assert "partial_fill_prob_small" in result.parameters_updated

    def test_partial_fill_prob_not_updated_with_insufficient_data(self):
        """Partial fill probabilities should not be updated with insufficient data."""
        config = ExecutionSimulatorConfig(
            partial_fill_prob_small=0.02,
            partial_fill_prob_medium=0.10,
            partial_fill_prob_large=0.30,
        )
        simulator = ExecutionSimulator(config)
        # Only 3 fills in small bucket (less than MIN_FILLS_FOR_UPDATE=5)
        live_fills = [
            {"latency_ms": 50.0, "slippage_bps": 1.0, "size_ratio": 0.005, "is_partial": True},
            {"latency_ms": 50.0, "slippage_bps": 1.0, "size_ratio": 0.006, "is_partial": True},
            {"latency_ms": 50.0, "slippage_bps": 1.0, "size_ratio": 0.007, "is_partial": False},
        ]
        
        result = simulator.calibrate_from_live(live_fills)
        
        # Config should not be updated
        assert simulator.config.partial_fill_prob_small == 0.02
        assert "partial_fill_prob_small" not in result.parameters_updated
        # But result should still show calculated rate
        assert abs(result.partial_fill_rate_small - 2/3) < 0.001

    def test_fills_without_size_ratio_not_bucketed(self):
        """Fills without size_ratio should not be counted in buckets."""
        simulator = ExecutionSimulator()
        live_fills = [
            {"latency_ms": 50.0, "slippage_bps": 1.0},  # No size_ratio
            {"latency_ms": 50.0, "slippage_bps": 1.0, "size_ratio": 0.005, "is_partial": False},
        ]
        
        result = simulator.calibrate_from_live(live_fills)
        
        assert result.fills_by_size_bucket["small"] == 1
        assert result.fills_by_size_bucket["medium"] == 0
        assert result.fills_by_size_bucket["large"] == 0


class TestCalibrateFromLiveEdgeCases:
    """Tests for edge cases in calibration."""

    def test_all_fields_missing_uses_defaults(self):
        """Fills with all fields missing should use config defaults."""
        config = ExecutionSimulatorConfig(
            base_latency_ms=50.0,
            base_slippage_bps=1.0,
        )
        simulator = ExecutionSimulator(config)
        live_fills = [{}, {}, {}]  # All empty
        
        result = simulator.calibrate_from_live(live_fills)
        
        assert result.latency_mean_ms == 50.0
        assert result.slippage_mean_bps == 1.0
        assert result.num_fills == 3

    def test_zero_latency_values(self):
        """Zero latency values should be handled correctly."""
        simulator = ExecutionSimulator()
        live_fills = [
            {"latency_ms": 0.0, "slippage_bps": 1.0},
            {"latency_ms": 100.0, "slippage_bps": 1.0},
        ]
        
        result = simulator.calibrate_from_live(live_fills)
        
        assert result.latency_mean_ms == 50.0

    def test_negative_slippage_values(self):
        """Negative slippage values (price improvement) should be handled."""
        simulator = ExecutionSimulator()
        live_fills = [
            {"latency_ms": 50.0, "slippage_bps": -0.5},  # Price improvement
            {"latency_ms": 50.0, "slippage_bps": 1.5},
        ]
        
        result = simulator.calibrate_from_live(live_fills)
        
        assert result.slippage_mean_bps == 0.5

    def test_boundary_size_ratios(self):
        """Boundary size ratios should be bucketed correctly."""
        simulator = ExecutionSimulator()
        live_fills = [
            # Exactly at boundaries
            {"latency_ms": 50.0, "slippage_bps": 1.0, "size_ratio": 0.01, "is_partial": False},   # medium (>= 0.01)
            {"latency_ms": 50.0, "slippage_bps": 1.0, "size_ratio": 0.05, "is_partial": False},   # large (>= 0.05)
            {"latency_ms": 50.0, "slippage_bps": 1.0, "size_ratio": 0.0099, "is_partial": False}, # small (< 0.01)
            {"latency_ms": 50.0, "slippage_bps": 1.0, "size_ratio": 0.0499, "is_partial": False}, # medium (< 0.05)
        ]
        
        result = simulator.calibrate_from_live(live_fills)
        
        assert result.fills_by_size_bucket["small"] == 1
        assert result.fills_by_size_bucket["medium"] == 2
        assert result.fills_by_size_bucket["large"] == 1

    def test_large_number_of_fills(self):
        """Large number of fills should be handled efficiently."""
        simulator = ExecutionSimulator()
        live_fills = [
            {"latency_ms": 50.0 + i * 0.1, "slippage_bps": 1.0, "size_ratio": 0.005, "is_partial": i % 10 == 0}
            for i in range(1000)
        ]
        
        result = simulator.calibrate_from_live(live_fills)
        
        assert result.num_fills == 1000
        assert result.fills_by_size_bucket["small"] == 1000
        # 100 out of 1000 are partial (every 10th)
        assert abs(result.partial_fill_rate_small - 0.1) < 0.001


class TestCalibrationResult:
    """Tests for CalibrationResult dataclass."""

    def test_calibration_result_contains_all_fields(self):
        """CalibrationResult should contain all expected fields."""
        simulator = ExecutionSimulator()
        live_fills = [
            {"latency_ms": 50.0, "slippage_bps": 1.0, "size_ratio": 0.005, "is_partial": False},
        ]
        
        result = simulator.calibrate_from_live(live_fills)
        
        assert hasattr(result, "num_fills")
        assert hasattr(result, "latency_mean_ms")
        assert hasattr(result, "latency_std_ms")
        assert hasattr(result, "slippage_mean_bps")
        assert hasattr(result, "partial_fill_rate_small")
        assert hasattr(result, "partial_fill_rate_medium")
        assert hasattr(result, "partial_fill_rate_large")
        assert hasattr(result, "fills_by_size_bucket")
        assert hasattr(result, "parameters_updated")

    def test_parameters_updated_tracks_changes(self):
        """parameters_updated should track which parameters were changed."""
        simulator = ExecutionSimulator()
        live_fills = [
            {"latency_ms": 75.0, "slippage_bps": 2.0},
        ]
        
        result = simulator.calibrate_from_live(live_fills)
        
        assert "base_latency_ms" in result.parameters_updated
        assert "latency_std_ms" in result.parameters_updated
        assert "base_slippage_bps" in result.parameters_updated
        # Partial fill probs not updated (insufficient data)
        assert "partial_fill_prob_small" not in result.parameters_updated
        assert "partial_fill_prob_medium" not in result.parameters_updated
        assert "partial_fill_prob_large" not in result.parameters_updated
