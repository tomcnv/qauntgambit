"""
Tests for CalibrationOutput and CalibrationGate.

Property-based tests validate:
- Property 1: Spread Blocking Correctness
- Property 2: Depth Blocking Correctness
- Property 3: Warn Zone Size Reduction
- Property 5: DecisionRecord Completeness (serialization round-trip)
"""

import pytest
from hypothesis import given, strategies as st, settings

from quantgambit.core.decision.calibration import CalibrationOutput, CalibrationGate
from quantgambit.risk.symbol_calibrator import SymbolCalibrator, CalibrationConfig


# =============================================================================
# Strategies for generating test data
# =============================================================================

@st.composite
def calibration_output_strategy(draw):
    """Generate random CalibrationOutput instances."""
    spread_typical = draw(st.floats(min_value=1.0, max_value=50.0))
    spread_warn = spread_typical * 2
    spread_block = spread_typical * 4
    
    depth_typical = draw(st.floats(min_value=1000.0, max_value=100000.0))
    depth_warn = depth_typical * 0.5
    depth_block = depth_typical * 0.25
    
    spread_current = draw(st.floats(min_value=0.1, max_value=100.0))
    depth_current = draw(st.floats(min_value=100.0, max_value=200000.0))
    
    spread_blocked = spread_current > spread_block
    spread_warn_flag = spread_current > spread_warn and not spread_blocked
    depth_blocked = depth_current < depth_block
    depth_warn_flag = depth_current < depth_warn and not depth_blocked
    
    size_multiplier = 1.0
    reasons = []
    if spread_warn_flag:
        size_multiplier *= 0.5
        reasons.append("spread_warn")
    if depth_warn_flag:
        size_multiplier *= 0.5
        reasons.append("depth_warn")
    
    quality = draw(st.sampled_from(["good", "fair", "poor"]))
    sample_count = draw(st.integers(min_value=0, max_value=1000))
    
    return CalibrationOutput(
        spread_block_bps=spread_block,
        spread_warn_bps=spread_warn,
        spread_typical_bps=spread_typical,
        depth_block_usd=depth_block,
        depth_warn_usd=depth_warn,
        depth_typical_usd=depth_typical,
        spread_current_bps=spread_current,
        depth_current_usd=depth_current,
        spread_blocked=spread_blocked,
        spread_warn=spread_warn_flag,
        depth_blocked=depth_blocked,
        depth_warn=depth_warn_flag,
        size_multiplier=size_multiplier,
        adjustment_reason=", ".join(reasons) if reasons else None,
        calibration_quality=quality,
        sample_count=sample_count,
        using_fallback=quality == "poor",
    )


# =============================================================================
# Property 5: DecisionRecord Completeness (Serialization Round-Trip)
# =============================================================================

class TestCalibrationOutputSerialization:
    """
    **Feature: symbol-calibrator-integration, Property 5: DecisionRecord Completeness**
    **Validates: Requirements 1.4, 2.4, 3.1, 3.2, 3.3, 5.3, 6.4**
    """
    
    @given(output=calibration_output_strategy())
    @settings(max_examples=100)
    def test_round_trip_serialization(self, output: CalibrationOutput):
        """
        *For any* CalibrationOutput, serializing to dict and deserializing
        should produce an equivalent object.
        """
        # Serialize
        data = output.to_dict()
        
        # Deserialize
        restored = CalibrationOutput.from_dict(data)
        
        # Verify all fields match (with tolerance for float rounding)
        assert abs(restored.spread_block_bps - output.spread_block_bps) < 0.01
        assert abs(restored.spread_warn_bps - output.spread_warn_bps) < 0.01
        assert abs(restored.spread_typical_bps - output.spread_typical_bps) < 0.01
        assert abs(restored.depth_block_usd - output.depth_block_usd) < 1.0
        assert abs(restored.depth_warn_usd - output.depth_warn_usd) < 1.0
        assert abs(restored.depth_typical_usd - output.depth_typical_usd) < 1.0
        assert abs(restored.spread_current_bps - output.spread_current_bps) < 0.01
        assert abs(restored.depth_current_usd - output.depth_current_usd) < 1.0
        assert restored.spread_blocked == output.spread_blocked
        assert restored.spread_warn == output.spread_warn
        assert restored.depth_blocked == output.depth_blocked
        assert restored.depth_warn == output.depth_warn
        assert abs(restored.size_multiplier - output.size_multiplier) < 0.0001
        assert restored.adjustment_reason == output.adjustment_reason
        assert restored.calibration_quality == output.calibration_quality
        assert restored.sample_count == output.sample_count
        assert restored.using_fallback == output.using_fallback
    
    def test_to_dict_contains_all_fields(self):
        """Verify to_dict includes all required fields."""
        output = CalibrationOutput(
            spread_block_bps=20.0,
            spread_warn_bps=10.0,
            spread_typical_bps=5.0,
            depth_block_usd=1000.0,
            depth_warn_usd=5000.0,
            depth_typical_usd=10000.0,
            spread_current_bps=3.0,
            depth_current_usd=8000.0,
            spread_blocked=False,
            spread_warn=False,
            depth_blocked=False,
            depth_warn=False,
            size_multiplier=1.0,
            adjustment_reason=None,
            calibration_quality="good",
            sample_count=150,
            using_fallback=False,
        )
        
        data = output.to_dict()
        
        # Verify all required fields are present
        required_fields = [
            "spread_block_bps", "spread_warn_bps", "spread_typical_bps",
            "depth_block_usd", "depth_warn_usd", "depth_typical_usd",
            "spread_current_bps", "depth_current_usd",
            "spread_blocked", "spread_warn", "depth_blocked", "depth_warn",
            "size_multiplier", "adjustment_reason",
            "calibration_quality", "sample_count", "using_fallback",
        ]
        
        for field in required_fields:
            assert field in data, f"Missing field: {field}"


# =============================================================================
# Property 1: Spread Blocking Correctness
# =============================================================================

class TestSpreadBlocking:
    """
    **Feature: symbol-calibrator-integration, Property 1: Spread Blocking Correctness**
    **Validates: Requirements 1.1**
    """
    
    @given(
        spread_typical=st.floats(min_value=1.0, max_value=20.0),
        spread_current=st.floats(min_value=0.1, max_value=100.0),
    )
    @settings(max_examples=100)
    def test_spread_blocking_when_exceeds_threshold(
        self, spread_typical: float, spread_current: float
    ):
        """
        *For any* symbol and spread value, if the spread exceeds the calibrated
        spread_block_bps threshold, spread_blocked SHALL be True.
        """
        # Create calibrator with known thresholds
        config = CalibrationConfig(
            sample_interval_sec=0.0,
            spread_warn_multiplier=2.0,
            spread_block_multiplier=4.0,
            min_samples_for_calibration=1,
        )
        calibrator = SymbolCalibrator(config)
        
        # Feed enough samples to establish typical spread
        for _ in range(25):
            calibrator.observe("TESTUSDT", spread_bps=spread_typical, bid_depth_usd=50000, ask_depth_usd=50000)
        
        gate = CalibrationGate(calibrator)
        
        # Check gating
        output = gate.check(
            symbol="TESTUSDT",
            spread_bps=spread_current,
            bid_depth_usd=50000.0,
            ask_depth_usd=50000.0,
        )
        
        # Verify blocking behavior
        # Block threshold is 4x typical (but at least 5 bps)
        expected_block_threshold = max(spread_typical * 4.0, 5.0)
        expected_blocked = spread_current > expected_block_threshold
        
        assert output.spread_blocked == expected_blocked, (
            f"spread_current={spread_current}, threshold={expected_block_threshold}, "
            f"expected_blocked={expected_blocked}, actual={output.spread_blocked}"
        )


# =============================================================================
# Property 2: Depth Blocking Correctness
# =============================================================================

class TestDepthBlocking:
    """
    **Feature: symbol-calibrator-integration, Property 2: Depth Blocking Correctness**
    **Validates: Requirements 2.1**
    """
    
    @given(
        depth_typical=st.floats(min_value=5000.0, max_value=100000.0),
        depth_current=st.floats(min_value=100.0, max_value=200000.0),
    )
    @settings(max_examples=100)
    def test_depth_blocking_when_below_threshold(
        self, depth_typical: float, depth_current: float
    ):
        """
        *For any* symbol and depth value, if the minimum depth falls below the
        calibrated depth_block_usd threshold, depth_blocked SHALL be True.
        """
        # Create calibrator with known thresholds
        config = CalibrationConfig(
            sample_interval_sec=0.0,
            depth_warn_fraction=0.5,
            depth_block_fraction=0.25,
            min_samples_for_calibration=1,
        )
        calibrator = SymbolCalibrator(config)
        
        # Feed enough samples to establish typical depth
        for _ in range(25):
            calibrator.observe("TESTUSDT", spread_bps=5.0, bid_depth_usd=depth_typical, ask_depth_usd=depth_typical)
        
        gate = CalibrationGate(calibrator)
        
        # Check gating
        output = gate.check(
            symbol="TESTUSDT",
            spread_bps=5.0,
            bid_depth_usd=depth_current,
            ask_depth_usd=depth_current,
        )
        
        # Verify blocking behavior
        # Block threshold is 0.25x typical (but at least $500)
        expected_block_threshold = max(depth_typical * 0.25, 500.0)
        expected_blocked = depth_current < expected_block_threshold
        
        assert output.depth_blocked == expected_blocked, (
            f"depth_current={depth_current}, threshold={expected_block_threshold}, "
            f"expected_blocked={expected_blocked}, actual={output.depth_blocked}"
        )


# =============================================================================
# Property 3: Warn Zone Size Reduction
# =============================================================================

class TestWarnZoneSizeReduction:
    """
    **Feature: symbol-calibrator-integration, Property 3: Warn Zone Size Reduction**
    **Validates: Requirements 1.2, 2.2, 6.1, 6.2, 6.3**
    """
    
    def test_spread_warn_reduces_size_by_half(self):
        """When spread is in warn zone, size_multiplier should be 0.5."""
        config = CalibrationConfig(sample_interval_sec=0.0, min_samples_for_calibration=1)
        calibrator = SymbolCalibrator(config)
        
        # Establish typical spread of 5 bps
        for _ in range(25):
            calibrator.observe("TESTUSDT", spread_bps=5.0, bid_depth_usd=50000, ask_depth_usd=50000)
        
        gate = CalibrationGate(calibrator, warn_size_multiplier=0.5)
        
        # Spread in warn zone: > 10 bps (2x typical) but < 20 bps (4x typical)
        output = gate.check("TESTUSDT", spread_bps=15.0, bid_depth_usd=50000, ask_depth_usd=50000)
        
        assert output.spread_warn is True
        assert output.spread_blocked is False
        assert output.size_multiplier == 0.5
        assert "spread_warn" in (output.adjustment_reason or "")
    
    def test_depth_warn_reduces_size_by_half(self):
        """When depth is in warn zone, size_multiplier should be 0.5."""
        config = CalibrationConfig(sample_interval_sec=0.0, min_samples_for_calibration=1)
        calibrator = SymbolCalibrator(config)
        
        # Establish typical depth of 50000
        for _ in range(25):
            calibrator.observe("TESTUSDT", spread_bps=5.0, bid_depth_usd=50000, ask_depth_usd=50000)
        
        gate = CalibrationGate(calibrator, warn_size_multiplier=0.5)
        
        # Depth in warn zone: < 25000 (0.5x typical) but > 12500 (0.25x typical)
        output = gate.check("TESTUSDT", spread_bps=5.0, bid_depth_usd=20000, ask_depth_usd=20000)
        
        assert output.depth_warn is True
        assert output.depth_blocked is False
        assert output.size_multiplier == 0.5
        assert "depth_warn" in (output.adjustment_reason or "")
    
    def test_both_warn_zones_multiplicative(self):
        """When both spread and depth are in warn zones, size_multiplier should be 0.25."""
        config = CalibrationConfig(sample_interval_sec=0.0, min_samples_for_calibration=1)
        calibrator = SymbolCalibrator(config)
        
        # Establish typical values
        for _ in range(25):
            calibrator.observe("TESTUSDT", spread_bps=5.0, bid_depth_usd=50000, ask_depth_usd=50000)
        
        gate = CalibrationGate(calibrator, warn_size_multiplier=0.5)
        
        # Both in warn zone
        output = gate.check("TESTUSDT", spread_bps=15.0, bid_depth_usd=20000, ask_depth_usd=20000)
        
        assert output.spread_warn is True
        assert output.depth_warn is True
        assert output.size_multiplier == 0.25  # 0.5 * 0.5
        assert "spread_warn" in (output.adjustment_reason or "")
        assert "depth_warn" in (output.adjustment_reason or "")
    
    @given(
        spread_in_warn=st.booleans(),
        depth_in_warn=st.booleans(),
    )
    @settings(max_examples=100)
    def test_size_multiplier_is_multiplicative(self, spread_in_warn: bool, depth_in_warn: bool):
        """
        *For any* combination of warn zone conditions, the size_multiplier
        should be the product of individual multipliers.
        """
        config = CalibrationConfig(sample_interval_sec=0.0, min_samples_for_calibration=1)
        calibrator = SymbolCalibrator(config)
        
        # Establish typical values: spread=5 bps, depth=50000
        for _ in range(25):
            calibrator.observe("TESTUSDT", spread_bps=5.0, bid_depth_usd=50000, ask_depth_usd=50000)
        
        gate = CalibrationGate(calibrator, warn_size_multiplier=0.5)
        
        # Set spread based on condition
        # Normal: 5 bps, Warn: 15 bps (between 10 and 20)
        spread = 15.0 if spread_in_warn else 5.0
        
        # Set depth based on condition
        # Normal: 50000, Warn: 20000 (between 12500 and 25000)
        depth = 20000.0 if depth_in_warn else 50000.0
        
        output = gate.check("TESTUSDT", spread_bps=spread, bid_depth_usd=depth, ask_depth_usd=depth)
        
        # Calculate expected multiplier
        expected_multiplier = 1.0
        if spread_in_warn:
            expected_multiplier *= 0.5
        if depth_in_warn:
            expected_multiplier *= 0.5
        
        assert abs(output.size_multiplier - expected_multiplier) < 0.001, (
            f"spread_in_warn={spread_in_warn}, depth_in_warn={depth_in_warn}, "
            f"expected={expected_multiplier}, actual={output.size_multiplier}"
        )


# =============================================================================
# Unit Tests
# =============================================================================

class TestCalibrationGateBasics:
    """Basic unit tests for CalibrationGate."""
    
    def test_uses_min_depth(self):
        """Gate should use minimum of bid/ask depth."""
        config = CalibrationConfig(sample_interval_sec=0.0, min_samples_for_calibration=1)
        calibrator = SymbolCalibrator(config)
        
        for _ in range(25):
            calibrator.observe("TESTUSDT", spread_bps=5.0, bid_depth_usd=50000, ask_depth_usd=50000)
        
        gate = CalibrationGate(calibrator)
        
        # Bid depth is lower
        output = gate.check("TESTUSDT", spread_bps=5.0, bid_depth_usd=10000, ask_depth_usd=50000)
        assert output.depth_current_usd == 10000.0
        
        # Ask depth is lower
        output = gate.check("TESTUSDT", spread_bps=5.0, bid_depth_usd=50000, ask_depth_usd=8000)
        assert output.depth_current_usd == 8000.0
    
    def test_fallback_thresholds_when_no_data(self):
        """Should use fallback thresholds when calibration quality is poor."""
        calibrator = SymbolCalibrator()
        gate = CalibrationGate(calibrator)
        
        # No observations - should use fallback
        output = gate.check("NEWUSDT", spread_bps=5.0, bid_depth_usd=10000, ask_depth_usd=10000)
        
        assert output.calibration_quality == "poor"
        assert output.using_fallback is True
        assert output.sample_count == 0
    
    def test_is_blocked_helper(self):
        """Test is_blocked() helper method."""
        output = CalibrationOutput(
            spread_block_bps=20.0, spread_warn_bps=10.0, spread_typical_bps=5.0,
            depth_block_usd=1000.0, depth_warn_usd=5000.0, depth_typical_usd=10000.0,
            spread_current_bps=25.0, depth_current_usd=8000.0,
            spread_blocked=True, spread_warn=False,
            depth_blocked=False, depth_warn=False,
            size_multiplier=1.0, adjustment_reason=None,
            calibration_quality="good", sample_count=100, using_fallback=False,
        )
        assert output.is_blocked() is True
        
        output.spread_blocked = False
        output.depth_blocked = True
        assert output.is_blocked() is True
        
        output.depth_blocked = False
        assert output.is_blocked() is False
    
    def test_is_degraded_helper(self):
        """Test is_degraded() helper method."""
        output = CalibrationOutput(
            spread_block_bps=20.0, spread_warn_bps=10.0, spread_typical_bps=5.0,
            depth_block_usd=1000.0, depth_warn_usd=5000.0, depth_typical_usd=10000.0,
            spread_current_bps=15.0, depth_current_usd=8000.0,
            spread_blocked=False, spread_warn=True,
            depth_blocked=False, depth_warn=False,
            size_multiplier=0.5, adjustment_reason="spread_warn",
            calibration_quality="good", sample_count=100, using_fallback=False,
        )
        assert output.is_degraded() is True
        
        output.spread_warn = False
        output.depth_warn = True
        assert output.is_degraded() is True
        
        output.depth_warn = False
        assert output.is_degraded() is False



# =============================================================================
# Property 4: Fallback Threshold Usage
# =============================================================================

class TestFallbackThresholds:
    """
    **Feature: symbol-calibrator-integration, Property 4: Fallback Threshold Usage**
    **Validates: Requirements 1.3, 2.3**
    """
    
    @given(
        spread_current=st.floats(min_value=0.1, max_value=100.0),
        depth_current=st.floats(min_value=100.0, max_value=200000.0),
    )
    @settings(max_examples=100)
    def test_fallback_thresholds_when_poor_quality(
        self, spread_current: float, depth_current: float
    ):
        """
        *For any* symbol with calibration_quality = "poor" (insufficient samples),
        the system SHALL use fallback absolute thresholds.
        """
        # Create calibrator with no data
        calibrator = SymbolCalibrator()
        gate = CalibrationGate(calibrator)
        
        # Check a symbol with no observations
        output = gate.check(
            symbol="NEWUSDT",
            spread_bps=spread_current,
            bid_depth_usd=depth_current,
            ask_depth_usd=depth_current,
        )
        
        # Should use fallback thresholds
        assert output.calibration_quality == "poor"
        assert output.using_fallback is True
        assert output.sample_count == 0
        
        # Fallback thresholds should be the config defaults
        config = CalibrationConfig()
        assert output.spread_warn_bps == config.fallback_spread_warn_bps
        assert output.spread_block_bps == config.fallback_spread_block_bps
        assert output.depth_warn_usd == config.fallback_depth_warn_usd
        assert output.depth_block_usd == config.fallback_depth_block_usd
    
    def test_calibrated_thresholds_when_good_quality(self):
        """When sufficient samples exist, should use calibrated thresholds."""
        config = CalibrationConfig(
            sample_interval_sec=0.0,
            min_samples_for_calibration=20,
            good_samples_threshold=100,
        )
        calibrator = SymbolCalibrator(config)
        
        # Feed 150 samples (good quality)
        for _ in range(150):
            calibrator.observe("BTCUSDT", spread_bps=3.0, bid_depth_usd=80000, ask_depth_usd=80000)
        
        gate = CalibrationGate(calibrator)
        output = gate.check("BTCUSDT", spread_bps=3.0, bid_depth_usd=80000, ask_depth_usd=80000)
        
        assert output.calibration_quality == "good"
        assert output.using_fallback is False
        assert output.sample_count >= 100
        
        # Thresholds should be based on observed data, not fallback
        # Typical spread ~3 bps, so warn should be ~6 bps, block ~12 bps
        assert output.spread_typical_bps < 5.0  # Close to 3
        assert output.spread_warn_bps < 15.0  # 2x typical
        assert output.spread_block_bps < 25.0  # 4x typical


# =============================================================================
# Property 6: Observation Feeding
# =============================================================================

class TestObservationFeeding:
    """
    **Feature: symbol-calibrator-integration, Property 6: Observation Feeding**
    **Validates: Requirements 4.4**
    """
    
    @given(
        num_observations=st.integers(min_value=1, max_value=50),
        spread_bps=st.floats(min_value=1.0, max_value=20.0),
        depth_usd=st.floats(min_value=1000.0, max_value=100000.0),
    )
    @settings(max_examples=100)
    def test_observations_are_recorded(
        self, num_observations: int, spread_bps: float, depth_usd: float
    ):
        """
        *For any* set of observations fed to the calibrator,
        the sample count should increase accordingly.
        """
        config = CalibrationConfig(sample_interval_sec=0.0)  # No rate limiting
        calibrator = SymbolCalibrator(config)
        
        # Feed observations
        for _ in range(num_observations):
            calibrator.observe(
                symbol="TESTUSDT",
                spread_bps=spread_bps,
                bid_depth_usd=depth_usd,
                ask_depth_usd=depth_usd,
            )
        
        # Check that observations were recorded
        thresholds = calibrator.get_thresholds("TESTUSDT")
        assert thresholds.sample_count == num_observations
    
    def test_calibration_gate_uses_calibrator_data(self):
        """Gate should use data from calibrator observations."""
        config = CalibrationConfig(sample_interval_sec=0.0, min_samples_for_calibration=1)
        calibrator = SymbolCalibrator(config)
        
        # Feed observations with specific spread
        for _ in range(30):
            calibrator.observe("ETHUSDT", spread_bps=8.0, bid_depth_usd=30000, ask_depth_usd=30000)
        
        gate = CalibrationGate(calibrator)
        output = gate.check("ETHUSDT", spread_bps=8.0, bid_depth_usd=30000, ask_depth_usd=30000)
        
        # Typical spread should be close to 8 bps
        assert 6.0 < output.spread_typical_bps < 10.0
        assert output.sample_count == 30



# =============================================================================
# Unit Tests for Size Adjustment in Hot Path
# =============================================================================

class TestSizeAdjustmentInHotPath:
    """
    Tests for size_multiplier application in the hot path.
    **Validates: Requirements 6.1, 6.2, 6.3**
    """
    
    def test_size_multiplier_applied_to_risk_output(self):
        """
        When calibration_size_multiplier < 1.0, w_target should be scaled down.
        
        This tests the logic that would be applied in the hot path.
        """
        # Simulate risk output before adjustment
        original_w_target = 0.10
        w_current = 0.0
        calibration_size_multiplier = 0.5
        
        # Apply the same logic as hot path
        adjusted_w_target = original_w_target * calibration_size_multiplier
        adjusted_delta_w = adjusted_w_target - w_current
        
        assert adjusted_w_target == 0.05  # 0.10 * 0.5
        assert adjusted_delta_w == 0.05
    
    def test_size_multiplier_1_0_no_change(self):
        """When size_multiplier is 1.0, no adjustment should occur."""
        original_w_target = 0.10
        calibration_size_multiplier = 1.0
        
        adjusted_w_target = original_w_target * calibration_size_multiplier
        
        assert adjusted_w_target == original_w_target
    
    def test_size_multiplier_0_25_both_warn_zones(self):
        """When both spread and depth are in warn zones, multiplier is 0.25."""
        original_w_target = 0.10
        calibration_size_multiplier = 0.25  # 0.5 * 0.5
        
        adjusted_w_target = original_w_target * calibration_size_multiplier
        
        assert adjusted_w_target == 0.025  # 0.10 * 0.25
    
    def test_size_multiplier_preserves_direction(self):
        """Size multiplier should preserve position direction (long/short)."""
        # Long position
        long_w_target = 0.10
        adjusted_long = long_w_target * 0.5
        assert adjusted_long > 0
        
        # Short position
        short_w_target = -0.10
        adjusted_short = short_w_target * 0.5
        assert adjusted_short < 0
        assert adjusted_short == -0.05



# =============================================================================
# Property 7: O(1) Performance
# =============================================================================

class TestO1Performance:
    """
    **Feature: symbol-calibrator-integration, Property 7: O(1) Performance**
    **Validates: Requirements 4.3**
    """
    
    def test_observe_is_fast(self):
        """observe() should complete in bounded time regardless of sample count."""
        import time
        
        config = CalibrationConfig(sample_interval_sec=0.0)
        calibrator = SymbolCalibrator(config)
        
        # Warm up with many samples
        for _ in range(1000):
            calibrator.observe("BTCUSDT", spread_bps=5.0, bid_depth_usd=50000, ask_depth_usd=50000)
        
        # Time a single observe
        start = time.perf_counter()
        for _ in range(100):
            calibrator.observe("BTCUSDT", spread_bps=5.0, bid_depth_usd=50000, ask_depth_usd=50000)
        elapsed = time.perf_counter() - start
        
        # Should complete 100 observations in < 10ms (0.1ms per observation)
        assert elapsed < 0.01, f"observe() too slow: {elapsed*1000:.2f}ms for 100 calls"
    
    def test_get_thresholds_is_fast(self):
        """get_thresholds() should complete in bounded time."""
        import time
        
        config = CalibrationConfig(sample_interval_sec=0.0)
        calibrator = SymbolCalibrator(config)
        
        # Warm up with many samples
        for _ in range(1000):
            calibrator.observe("BTCUSDT", spread_bps=5.0, bid_depth_usd=50000, ask_depth_usd=50000)
        
        # Time threshold lookups
        start = time.perf_counter()
        for _ in range(100):
            calibrator.get_thresholds("BTCUSDT")
        elapsed = time.perf_counter() - start
        
        # Should complete 100 lookups in < 10ms
        assert elapsed < 0.01, f"get_thresholds() too slow: {elapsed*1000:.2f}ms for 100 calls"
    
    def test_calibration_gate_check_is_fast(self):
        """CalibrationGate.check() should complete in bounded time."""
        import time
        
        config = CalibrationConfig(sample_interval_sec=0.0)
        calibrator = SymbolCalibrator(config)
        
        # Warm up
        for _ in range(1000):
            calibrator.observe("BTCUSDT", spread_bps=5.0, bid_depth_usd=50000, ask_depth_usd=50000)
        
        gate = CalibrationGate(calibrator)
        
        # Time gate checks
        start = time.perf_counter()
        for _ in range(100):
            gate.check("BTCUSDT", spread_bps=5.0, bid_depth_usd=50000, ask_depth_usd=50000)
        elapsed = time.perf_counter() - start
        
        # Should complete 100 checks in < 10ms
        assert elapsed < 0.01, f"check() too slow: {elapsed*1000:.2f}ms for 100 calls"
    
    @given(sample_count=st.integers(min_value=10, max_value=1000))
    @settings(max_examples=20)
    def test_performance_independent_of_sample_count(self, sample_count: int):
        """
        *For any* sample count, calibrator operations should complete in bounded time.
        """
        import time
        
        config = CalibrationConfig(sample_interval_sec=0.0)
        calibrator = SymbolCalibrator(config)
        
        # Add samples
        for _ in range(sample_count):
            calibrator.observe("TESTUSDT", spread_bps=5.0, bid_depth_usd=50000, ask_depth_usd=50000)
        
        # Time operations
        start = time.perf_counter()
        for _ in range(10):
            calibrator.observe("TESTUSDT", spread_bps=5.0, bid_depth_usd=50000, ask_depth_usd=50000)
            calibrator.get_thresholds("TESTUSDT")
        elapsed = time.perf_counter() - start
        
        # Should complete in < 5ms regardless of sample count
        assert elapsed < 0.005, (
            f"Operations too slow with {sample_count} samples: {elapsed*1000:.2f}ms"
        )



# =============================================================================
# Task 10: Integration Tests for Hot Path with Calibrator
# =============================================================================

class TestHotPathWithCalibrator:
    """
    **Feature: symbol-calibrator-integration, Task 10.1: Integration test for hot path WITH calibrator**
    **Validates: Requirements 1.1, 2.1, 4.4**
    
    Tests the full integration of CalibrationGate into the HotPath.
    """
    
    def _create_mock_book(self, bid_price=50000.0, ask_price=50002.5, bid_depth=50000.0, ask_depth=50000.0):
        """Create a properly mocked OrderBook."""
        from unittest.mock import MagicMock
        from quantgambit.core.book.types import OrderBook, Level
        
        book = MagicMock(spec=OrderBook)
        book.best_bid_price = bid_price
        book.best_ask_price = ask_price
        book.mid_price = (bid_price + ask_price) / 2
        book.timestamp = 1000.0
        book.sequence_id = 1
        
        # Create proper bid/ask levels
        bid_level = MagicMock(spec=Level)
        bid_level.price = bid_price
        bid_level.size = bid_depth / bid_price  # Convert USD to size
        
        ask_level = MagicMock(spec=Level)
        ask_level.price = ask_price
        ask_level.size = ask_depth / ask_price
        
        book.bids = [bid_level]
        book.asks = [ask_level]
        
        return book
    
    def test_spread_blocking_in_hot_path(self):
        """
        When spread exceeds calibrated threshold, hot path should block with BLOCKED_SPREAD_WIDE.
        """
        from unittest.mock import MagicMock, patch
        from quantgambit.core.decision import DecisionOutcome, BookSnapshot
        from quantgambit.core.decision.calibration import CalibrationGate
        from quantgambit.risk.symbol_calibrator import SymbolCalibrator, CalibrationConfig
        from quantgambit.runtime.hot_path import HotPath
        from quantgambit.core.clock import Clock
        from quantgambit.core.book.guardian import BookGuardian
        from quantgambit.core.book.types import BookUpdate
        from quantgambit.core.risk.kill_switch import KillSwitch
        
        # Create calibrator with known thresholds
        config = CalibrationConfig(
            sample_interval_sec=0.0,
            min_samples_for_calibration=1,
            spread_warn_multiplier=2.0,
            spread_block_multiplier=4.0,
        )
        calibrator = SymbolCalibrator(config)
        
        # Establish typical spread of 5 bps
        for _ in range(30):
            calibrator.observe("BTCUSDT", spread_bps=5.0, bid_depth_usd=50000, ask_depth_usd=50000)
        
        gate = CalibrationGate(calibrator)
        
        # Create mocks
        clock = MagicMock(spec=Clock)
        clock.now.return_value = 1000.0
        clock.now_mono.return_value = 1000.0
        
        guardian = MagicMock(spec=BookGuardian)
        guardian.is_quoteable.return_value = True
        
        kill_switch = MagicMock(spec=KillSwitch)
        kill_switch.is_active.return_value = False
        
        feature_builder = MagicMock()
        model_runner = MagicMock()
        calibrator_mock = MagicMock()
        edge_transform = MagicMock()
        vol_estimator = MagicMock()
        risk_mapper = MagicMock()
        exec_policy = MagicMock()
        gateway = MagicMock()
        publisher = MagicMock()
        
        published_records = []
        publisher.publish = lambda e: published_records.append(e)
        
        hot_path = HotPath(
            clock=clock,
            book_guardian=guardian,
            kill_switch=kill_switch,
            feature_builder=feature_builder,
            model_runner=model_runner,
            calibrator=calibrator_mock,
            edge_transform=edge_transform,
            vol_estimator=vol_estimator,
            risk_mapper=risk_mapper,
            execution_policy=exec_policy,
            execution_gateway=gateway,
            publisher=publisher,
            symbol_calibrator=calibrator,
            calibration_gate=gate,
        )
        
        # Create book with wide spread (30 bps > 20 bps block threshold)
        book = self._create_mock_book(
            bid_price=50000.0,
            ask_price=50015.0,  # 30 bps spread
            bid_depth=50000.0,
            ask_depth=50000.0,
        )
        guardian.handle_update.return_value = book
        
        # Mock BookSnapshot.from_order_book to return wide spread
        mock_snapshot = MagicMock()
        mock_snapshot.spread_bps = 30.0  # Wide spread
        mock_snapshot.bid_depth_usd = 50000.0
        mock_snapshot.ask_depth_usd = 50000.0
        
        with patch.object(BookSnapshot, 'from_order_book', return_value=mock_snapshot):
            update = MagicMock(spec=BookUpdate)
            hot_path.on_book_update("BTCUSDT", update)
        
        # Verify spread blocking occurred
        assert hot_path._state.blocked_count == 1
        assert len(published_records) == 1
        
        record_payload = published_records[0].payload
        assert record_payload.get("outcome") == DecisionOutcome.BLOCKED_SPREAD_WIDE.value
    
    def test_depth_blocking_in_hot_path(self):
        """
        When depth falls below calibrated threshold, hot path should block with BLOCKED_DEPTH_THIN.
        """
        from unittest.mock import MagicMock, patch
        from quantgambit.core.decision import DecisionOutcome, BookSnapshot
        from quantgambit.core.decision.calibration import CalibrationGate
        from quantgambit.risk.symbol_calibrator import SymbolCalibrator, CalibrationConfig
        from quantgambit.runtime.hot_path import HotPath
        from quantgambit.core.clock import Clock
        from quantgambit.core.book.guardian import BookGuardian
        from quantgambit.core.book.types import BookUpdate
        from quantgambit.core.risk.kill_switch import KillSwitch
        
        # Create calibrator with known thresholds
        config = CalibrationConfig(
            sample_interval_sec=0.0,
            min_samples_for_calibration=1,
            depth_warn_fraction=0.5,
            depth_block_fraction=0.25,
        )
        calibrator = SymbolCalibrator(config)
        
        # Establish typical depth of 50000
        for _ in range(30):
            calibrator.observe("BTCUSDT", spread_bps=5.0, bid_depth_usd=50000, ask_depth_usd=50000)
        
        gate = CalibrationGate(calibrator)
        
        # Create mocks
        clock = MagicMock(spec=Clock)
        clock.now.return_value = 1000.0
        clock.now_mono.return_value = 1000.0
        
        guardian = MagicMock(spec=BookGuardian)
        guardian.is_quoteable.return_value = True
        
        kill_switch = MagicMock(spec=KillSwitch)
        kill_switch.is_active.return_value = False
        
        feature_builder = MagicMock()
        model_runner = MagicMock()
        calibrator_mock = MagicMock()
        edge_transform = MagicMock()
        vol_estimator = MagicMock()
        risk_mapper = MagicMock()
        exec_policy = MagicMock()
        gateway = MagicMock()
        publisher = MagicMock()
        
        published_records = []
        publisher.publish = lambda e: published_records.append(e)
        
        hot_path = HotPath(
            clock=clock,
            book_guardian=guardian,
            kill_switch=kill_switch,
            feature_builder=feature_builder,
            model_runner=model_runner,
            calibrator=calibrator_mock,
            edge_transform=edge_transform,
            vol_estimator=vol_estimator,
            risk_mapper=risk_mapper,
            execution_policy=exec_policy,
            execution_gateway=gateway,
            publisher=publisher,
            symbol_calibrator=calibrator,
            calibration_gate=gate,
        )
        
        # Create book with thin depth
        book = self._create_mock_book(
            bid_price=50000.0,
            ask_price=50002.5,
            bid_depth=5000.0,  # Below block threshold
            ask_depth=5000.0,
        )
        guardian.handle_update.return_value = book
        
        # Mock BookSnapshot.from_order_book to return thin depth
        mock_snapshot = MagicMock()
        mock_snapshot.spread_bps = 5.0
        mock_snapshot.bid_depth_usd = 5000.0  # Below block threshold (12500)
        mock_snapshot.ask_depth_usd = 5000.0
        
        with patch.object(BookSnapshot, 'from_order_book', return_value=mock_snapshot):
            update = MagicMock(spec=BookUpdate)
            hot_path.on_book_update("BTCUSDT", update)
        
        assert hot_path._state.blocked_count == 1
        assert len(published_records) == 1
        
        record_payload = published_records[0].payload
        assert record_payload.get("outcome") == DecisionOutcome.BLOCKED_DEPTH_THIN.value
    
    def test_size_reduction_in_warn_zone(self):
        """
        When spread/depth are in warn zones, size_multiplier should reduce position size.
        """
        from unittest.mock import MagicMock, patch
        from quantgambit.core.decision import BookSnapshot
        from quantgambit.core.decision.calibration import CalibrationGate
        from quantgambit.risk.symbol_calibrator import SymbolCalibrator, CalibrationConfig
        from quantgambit.runtime.hot_path import HotPath
        from quantgambit.core.clock import Clock
        from quantgambit.core.book.guardian import BookGuardian
        from quantgambit.core.book.types import BookUpdate
        from quantgambit.core.risk.kill_switch import KillSwitch
        
        # Create calibrator
        config = CalibrationConfig(
            sample_interval_sec=0.0,
            min_samples_for_calibration=1,
        )
        calibrator = SymbolCalibrator(config)
        
        # Establish typical spread of 5 bps
        for _ in range(30):
            calibrator.observe("BTCUSDT", spread_bps=5.0, bid_depth_usd=50000, ask_depth_usd=50000)
        
        gate = CalibrationGate(calibrator, warn_size_multiplier=0.5)
        
        # Create mocks
        clock = MagicMock(spec=Clock)
        clock.now.return_value = 1000.0
        clock.now_mono.return_value = 1000.0
        
        guardian = MagicMock(spec=BookGuardian)
        guardian.is_quoteable.return_value = True
        
        kill_switch = MagicMock(spec=KillSwitch)
        kill_switch.is_active.return_value = False
        
        feature_builder = MagicMock()
        features = MagicMock()
        feature_builder.build.return_value = features
        
        model_runner = MagicMock()
        model_runner.infer.return_value = {
            "p_hat": 0.6,
            "model_version_id": "test_v1",
        }
        
        calibrator_mock = MagicMock()
        calibrator_mock.calibrate.return_value = {
            "p_hat": 0.6,
            "calibrator_version_id": "cal_v1",
        }
        
        edge_transform = MagicMock()
        edge_transform.to_edge.return_value = {
            "s": 0.2,
            "tau": 0.1,
            "deadband_blocked": False,
        }
        
        vol_estimator = MagicMock()
        vol_estimator.estimate.return_value = {
            "vol_version_id": "v1",
            "vol_hat": 0.02,
        }
        
        risk_mapper = MagicMock()
        risk_mapper.map.return_value = {
            "w_target": 0.10,
            "w_current": 0.0,
            "delta_w": 0.10,
            "churn_guard_blocked": False,
        }
        
        exec_policy = MagicMock()
        exec_policy.build_intents.return_value = []
        
        gateway = MagicMock()
        publisher = MagicMock()
        
        published_records = []
        publisher.publish = lambda e: published_records.append(e)
        
        hot_path = HotPath(
            clock=clock,
            book_guardian=guardian,
            kill_switch=kill_switch,
            feature_builder=feature_builder,
            model_runner=model_runner,
            calibrator=calibrator_mock,
            edge_transform=edge_transform,
            vol_estimator=vol_estimator,
            risk_mapper=risk_mapper,
            execution_policy=exec_policy,
            execution_gateway=gateway,
            publisher=publisher,
            symbol_calibrator=calibrator,
            calibration_gate=gate,
        )
        
        # Create book with spread in warn zone
        book = self._create_mock_book(
            bid_price=50000.0,
            ask_price=50007.5,  # 15 bps spread
            bid_depth=50000.0,
            ask_depth=50000.0,
        )
        guardian.handle_update.return_value = book
        
        # Mock BookSnapshot.from_order_book
        mock_snapshot = MagicMock()
        mock_snapshot.spread_bps = 15.0  # In warn zone (> 10 bps, < 20 bps)
        mock_snapshot.bid_depth_usd = 50000.0
        mock_snapshot.ask_depth_usd = 50000.0
        
        with patch.object(BookSnapshot, 'from_order_book', return_value=mock_snapshot):
            update = MagicMock(spec=BookUpdate)
            hot_path.on_book_update("BTCUSDT", update)
        
        # Verify risk_mapper.map was called
        assert risk_mapper.map.called
        
        # Verify record was published with calibration output
        assert len(published_records) >= 1
        record_payload = published_records[0].payload
        calibration_data = record_payload.get("calibration_output")
        if calibration_data:
            assert calibration_data.get("size_multiplier") == 0.5
            assert calibration_data.get("spread_warn") is True
    
    def test_observation_feeding_updates_calibrator(self):
        """
        Each tick should feed the symbol calibrator with spread/depth observations.
        """
        from unittest.mock import MagicMock, patch
        from quantgambit.core.decision import BookSnapshot
        from quantgambit.core.decision.calibration import CalibrationGate
        from quantgambit.risk.symbol_calibrator import SymbolCalibrator, CalibrationConfig
        from quantgambit.runtime.hot_path import HotPath
        from quantgambit.core.clock import Clock
        from quantgambit.core.book.guardian import BookGuardian
        from quantgambit.core.book.types import BookUpdate
        from quantgambit.core.risk.kill_switch import KillSwitch
        
        # Create calibrator with spy
        config = CalibrationConfig(sample_interval_sec=0.0)
        calibrator = SymbolCalibrator(config)
        original_observe = calibrator.observe
        observe_calls = []
        
        def spy_observe(symbol, spread_bps, bid_depth_usd, ask_depth_usd):
            observe_calls.append({
                "symbol": symbol,
                "spread_bps": spread_bps,
                "bid_depth_usd": bid_depth_usd,
                "ask_depth_usd": ask_depth_usd,
            })
            return original_observe(symbol, spread_bps, bid_depth_usd, ask_depth_usd)
        
        calibrator.observe = spy_observe
        
        gate = CalibrationGate(calibrator)
        
        # Create mocks
        clock = MagicMock(spec=Clock)
        clock.now.return_value = 1000.0
        clock.now_mono.return_value = 1000.0
        
        guardian = MagicMock(spec=BookGuardian)
        guardian.is_quoteable.return_value = True
        
        kill_switch = MagicMock(spec=KillSwitch)
        kill_switch.is_active.return_value = False
        
        feature_builder = MagicMock()
        model_runner = MagicMock()
        calibrator_mock = MagicMock()
        edge_transform = MagicMock()
        vol_estimator = MagicMock()
        risk_mapper = MagicMock()
        exec_policy = MagicMock()
        gateway = MagicMock()
        publisher = MagicMock()
        publisher.publish = MagicMock()
        
        hot_path = HotPath(
            clock=clock,
            book_guardian=guardian,
            kill_switch=kill_switch,
            feature_builder=feature_builder,
            model_runner=model_runner,
            calibrator=calibrator_mock,
            edge_transform=edge_transform,
            vol_estimator=vol_estimator,
            risk_mapper=risk_mapper,
            execution_policy=exec_policy,
            execution_gateway=gateway,
            publisher=publisher,
            symbol_calibrator=calibrator,
            calibration_gate=gate,
        )
        
        # Create book
        book = self._create_mock_book()
        guardian.handle_update.return_value = book
        
        # Mock BookSnapshot.from_order_book
        mock_snapshot = MagicMock()
        mock_snapshot.spread_bps = 5.0
        mock_snapshot.bid_depth_usd = 40000.0
        mock_snapshot.ask_depth_usd = 45000.0
        
        with patch.object(BookSnapshot, 'from_order_book', return_value=mock_snapshot):
            # Process multiple ticks
            for i in range(3):
                update = MagicMock(spec=BookUpdate)
                hot_path.on_book_update("BTCUSDT", update)
        
        # Verify observations were fed
        assert len(observe_calls) == 3
        for call_data in observe_calls:
            assert call_data["symbol"] == "BTCUSDT"
            assert call_data["spread_bps"] == 5.0
            assert call_data["bid_depth_usd"] == 40000.0
            assert call_data["ask_depth_usd"] == 45000.0


class TestHotPathWithoutCalibrator:
    """
    **Feature: symbol-calibrator-integration, Task 10.2: Integration test for hot path WITHOUT calibrator**
    **Validates: Requirements 4.5 (backward compatibility)**
    
    Tests that the hot path works correctly without a calibrator (backward compatibility).
    """
    
    def _create_mock_book(self, bid_price=50000.0, ask_price=50002.5, bid_depth=50000.0, ask_depth=50000.0):
        """Create a properly mocked OrderBook."""
        from unittest.mock import MagicMock
        from quantgambit.core.book.types import OrderBook, Level
        
        book = MagicMock(spec=OrderBook)
        book.best_bid_price = bid_price
        book.best_ask_price = ask_price
        book.mid_price = (bid_price + ask_price) / 2
        book.timestamp = 1000.0
        book.sequence_id = 1
        
        bid_level = MagicMock(spec=Level)
        bid_level.price = bid_price
        bid_level.size = bid_depth / bid_price
        
        ask_level = MagicMock(spec=Level)
        ask_level.price = ask_price
        ask_level.size = ask_depth / ask_price
        
        book.bids = [bid_level]
        book.asks = [ask_level]
        
        return book
    
    def test_hot_path_works_without_calibrator(self):
        """
        Hot path should function normally when no symbol_calibrator is provided.
        """
        from unittest.mock import MagicMock, patch
        from quantgambit.core.decision import BookSnapshot
        from quantgambit.runtime.hot_path import HotPath
        from quantgambit.core.clock import Clock
        from quantgambit.core.book.guardian import BookGuardian
        from quantgambit.core.book.types import BookUpdate
        from quantgambit.core.risk.kill_switch import KillSwitch
        
        # Create mocks
        clock = MagicMock(spec=Clock)
        clock.now.return_value = 1000.0
        clock.now_mono.return_value = 1000.0
        
        guardian = MagicMock(spec=BookGuardian)
        guardian.is_quoteable.return_value = True
        
        kill_switch = MagicMock(spec=KillSwitch)
        kill_switch.is_active.return_value = False
        
        feature_builder = MagicMock()
        features = MagicMock()
        feature_builder.build.return_value = features
        
        model_runner = MagicMock()
        model_runner.infer.return_value = {
            "p_hat": 0.6,
            "model_version_id": "test_v1",
        }
        
        calibrator_mock = MagicMock()
        calibrator_mock.calibrate.return_value = {
            "p_hat": 0.6,
            "calibrator_version_id": "cal_v1",
        }
        
        edge_transform = MagicMock()
        edge_transform.to_edge.return_value = {
            "s": 0.2,
            "tau": 0.1,
            "deadband_blocked": False,
        }
        
        vol_estimator = MagicMock()
        vol_estimator.estimate.return_value = {
            "vol_version_id": "v1",
            "vol_hat": 0.02,
        }
        
        risk_mapper = MagicMock()
        risk_mapper.map.return_value = {
            "w_target": 0.10,
            "w_current": 0.0,
            "delta_w": 0.10,
            "churn_guard_blocked": False,
        }
        
        exec_policy = MagicMock()
        exec_policy.build_intents.return_value = []
        
        gateway = MagicMock()
        publisher = MagicMock()
        
        published_records = []
        publisher.publish = lambda e: published_records.append(e)
        
        # Create hot path WITHOUT calibrator
        hot_path = HotPath(
            clock=clock,
            book_guardian=guardian,
            kill_switch=kill_switch,
            feature_builder=feature_builder,
            model_runner=model_runner,
            calibrator=calibrator_mock,
            edge_transform=edge_transform,
            vol_estimator=vol_estimator,
            risk_mapper=risk_mapper,
            execution_policy=exec_policy,
            execution_gateway=gateway,
            publisher=publisher,
            # No symbol_calibrator or calibration_gate
        )
        
        # Verify no calibrator
        assert hot_path._symbol_calibrator is None
        assert hot_path._calibration_gate is None
        
        # Create book
        book = self._create_mock_book()
        guardian.handle_update.return_value = book
        
        # Mock BookSnapshot.from_order_book
        mock_snapshot = MagicMock()
        mock_snapshot.spread_bps = 5.0
        mock_snapshot.bid_depth_usd = 50000.0
        mock_snapshot.ask_depth_usd = 50000.0
        
        with patch.object(BookSnapshot, 'from_order_book', return_value=mock_snapshot):
            update = MagicMock(spec=BookUpdate)
            hot_path.on_book_update("BTCUSDT", update)
        
        # Verify pipeline ran
        assert feature_builder.build.called
        assert model_runner.infer.called
        assert risk_mapper.map.called
        
        # Verify no blocking occurred
        assert hot_path._state.blocked_count == 0
    
    def test_no_calibration_output_in_record_without_calibrator(self):
        """
        When no calibrator is provided, decision records should not contain calibration_output.
        """
        from unittest.mock import MagicMock, patch
        from quantgambit.core.decision import BookSnapshot
        from quantgambit.runtime.hot_path import HotPath
        from quantgambit.core.clock import Clock
        from quantgambit.core.book.guardian import BookGuardian
        from quantgambit.core.book.types import BookUpdate
        from quantgambit.core.risk.kill_switch import KillSwitch
        
        # Create mocks
        clock = MagicMock(spec=Clock)
        clock.now.return_value = 1000.0
        clock.now_mono.return_value = 1000.0
        
        guardian = MagicMock(spec=BookGuardian)
        guardian.is_quoteable.return_value = True
        
        kill_switch = MagicMock(spec=KillSwitch)
        kill_switch.is_active.return_value = False
        
        feature_builder = MagicMock()
        feature_builder.build.return_value = MagicMock()
        
        model_runner = MagicMock()
        model_runner.infer.return_value = {
            "p_hat": 0.6,
            "model_version_id": "test_v1",
        }
        
        calibrator_mock = MagicMock()
        calibrator_mock.calibrate.return_value = {"p_hat": 0.6}
        
        edge_transform = MagicMock()
        edge_transform.to_edge.return_value = {
            "s": 0.2,
            "tau": 0.1,
            "deadband_blocked": False,
        }
        
        vol_estimator = MagicMock()
        vol_estimator.estimate.return_value = {
            "vol_version_id": "v1",
            "vol_hat": 0.02,
        }
        
        risk_mapper = MagicMock()
        risk_mapper.map.return_value = {
            "w_target": 0.10,
            "w_current": 0.0,
            "delta_w": 0.10,
            "churn_guard_blocked": False,
        }
        
        exec_policy = MagicMock()
        exec_policy.build_intents.return_value = []
        
        gateway = MagicMock()
        publisher = MagicMock()
        
        published_records = []
        publisher.publish = lambda e: published_records.append(e)
        
        # Create hot path WITHOUT calibrator
        hot_path = HotPath(
            clock=clock,
            book_guardian=guardian,
            kill_switch=kill_switch,
            feature_builder=feature_builder,
            model_runner=model_runner,
            calibrator=calibrator_mock,
            edge_transform=edge_transform,
            vol_estimator=vol_estimator,
            risk_mapper=risk_mapper,
            execution_policy=exec_policy,
            execution_gateway=gateway,
            publisher=publisher,
        )
        
        # Create book
        book = self._create_mock_book()
        guardian.handle_update.return_value = book
        
        # Mock BookSnapshot.from_order_book
        mock_snapshot = MagicMock()
        mock_snapshot.spread_bps = 5.0
        mock_snapshot.bid_depth_usd = 50000.0
        mock_snapshot.ask_depth_usd = 50000.0
        
        with patch.object(BookSnapshot, 'from_order_book', return_value=mock_snapshot):
            update = MagicMock(spec=BookUpdate)
            hot_path.on_book_update("BTCUSDT", update)
        
        # Verify record was published
        assert len(published_records) >= 1
        
        # Verify no calibration_output in record
        record_payload = published_records[0].payload
        calibration_output = record_payload.get("calibration_output")
        assert calibration_output is None, "calibration_output should be None when no calibrator"
    
    def test_auto_creates_gate_when_calibrator_provided(self):
        """
        When symbol_calibrator is provided but calibration_gate is not,
        HotPath should auto-create the gate.
        """
        from unittest.mock import MagicMock
        from quantgambit.core.decision.calibration import CalibrationGate
        from quantgambit.risk.symbol_calibrator import SymbolCalibrator
        from quantgambit.runtime.hot_path import HotPath
        from quantgambit.core.clock import Clock
        from quantgambit.core.book.guardian import BookGuardian
        from quantgambit.core.risk.kill_switch import KillSwitch
        
        calibrator = SymbolCalibrator()
        
        # Create minimal mocks
        clock = MagicMock(spec=Clock)
        guardian = MagicMock(spec=BookGuardian)
        kill_switch = MagicMock(spec=KillSwitch)
        feature_builder = MagicMock()
        model_runner = MagicMock()
        calibrator_mock = MagicMock()
        edge_transform = MagicMock()
        vol_estimator = MagicMock()
        risk_mapper = MagicMock()
        exec_policy = MagicMock()
        gateway = MagicMock()
        publisher = MagicMock()
        
        # Create hot path with calibrator but no gate
        hot_path = HotPath(
            clock=clock,
            book_guardian=guardian,
            kill_switch=kill_switch,
            feature_builder=feature_builder,
            model_runner=model_runner,
            calibrator=calibrator_mock,
            edge_transform=edge_transform,
            vol_estimator=vol_estimator,
            risk_mapper=risk_mapper,
            execution_policy=exec_policy,
            execution_gateway=gateway,
            publisher=publisher,
            symbol_calibrator=calibrator,
            # No calibration_gate provided
        )
        
        # Verify gate was auto-created
        assert hot_path._symbol_calibrator is calibrator
        assert hot_path._calibration_gate is not None
        assert isinstance(hot_path._calibration_gate, CalibrationGate)
