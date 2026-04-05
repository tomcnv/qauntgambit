"""
Property-based tests for ConfidenceGateStage.

Feature: trading-loss-fixes
Tests correctness properties for:
- Property 1: Confidence Gate Rejection

**Validates: Requirements 1.1, 1.4**

NOTE: ConfidenceGateStage is deprecated in favor of EVGateStage.
These tests suppress deprecation warnings to validate legacy behavior.
"""

import pytest
import asyncio
import warnings
from hypothesis import given, strategies as st, settings, assume

from quantgambit.signals.stages.confidence_gate import ConfidenceGateStage, ConfidenceGateConfig
from quantgambit.signals.pipeline import StageContext, StageResult
from quantgambit.observability.blocked_signal_telemetry import BlockedSignalTelemetry


# =============================================================================
# Helper to create ConfidenceGateStage without deprecation warnings
# =============================================================================

def create_confidence_gate_stage(config=None, telemetry=None):
    """Create ConfidenceGateStage with deprecation warnings suppressed."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        return ConfidenceGateStage(config=config, telemetry=telemetry)


# =============================================================================
# Test Strategies (Generators)
# =============================================================================

# Confidence values in 0-1 range
confidence_value = st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False)

# Threshold values in valid range (0-1)
threshold_value = st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False)

# Symbols
symbol = st.sampled_from(["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT"])


# =============================================================================
# Property 1: Confidence Gate Rejection
# Feature: trading-loss-fixes, Property 1: Confidence Gate Rejection
# Validates: Requirements 1.1, 1.4
# =============================================================================

@settings(max_examples=100)
@given(
    confidence=confidence_value,
    threshold=threshold_value,
    sym=symbol,
)
def test_property_1_confidence_gate_rejection(
    confidence: float,
    threshold: float,
    sym: str,
):
    """
    Property 1: Confidence Gate Rejection
    
    *For any* signal with confidence below the configured threshold (default 50%), 
    the ConfidenceGateStage SHALL reject the signal and the signal SHALL NOT 
    reach position sizing or execution stages.
    
    Conversely, signals with confidence >= threshold SHALL pass through.
    
    **Validates: Requirements 1.1, 1.4**
    """
    # Create stage with the given threshold (suppress deprecation warning)
    config = ConfidenceGateConfig(min_confidence=threshold)
    stage = create_confidence_gate_stage(config=config)
    
    # Create context with the given confidence
    ctx = StageContext(
        symbol=sym,
        data={
            "prediction": {"confidence": confidence}
        }
    )
    
    # Run the stage
    result = asyncio.run(stage.run(ctx))
    
    # Property: signals below threshold are rejected, signals >= threshold pass
    if confidence < threshold:
        assert result == StageResult.REJECT, \
            f"Signal with confidence {confidence} should be REJECTED when threshold is {threshold}"
        assert ctx.rejection_reason == "low_confidence", \
            f"Rejection reason should be 'low_confidence', got {ctx.rejection_reason}"
        assert ctx.rejection_stage == "confidence_gate", \
            f"Rejection stage should be 'confidence_gate', got {ctx.rejection_stage}"
        assert ctx.rejection_detail is not None, \
            "Rejection detail should be set"
        assert ctx.rejection_detail["confidence"] == confidence, \
            f"Rejection detail confidence should be {confidence}"
        assert ctx.rejection_detail["threshold"] == threshold, \
            f"Rejection detail threshold should be {threshold}"
    else:
        assert result == StageResult.CONTINUE, \
            f"Signal with confidence {confidence} should CONTINUE when threshold is {threshold}"
        assert ctx.rejection_reason is None, \
            f"Rejection reason should be None for passing signals, got {ctx.rejection_reason}"


@settings(max_examples=100)
@given(
    confidence=confidence_value,
    sym=symbol,
)
def test_property_1_default_threshold_rejection(
    confidence: float,
    sym: str,
):
    """
    Property 1 (Default Threshold): Confidence Gate with Default 50% Threshold
    
    *For any* signal with confidence below 50% (the default threshold), 
    the ConfidenceGateStage SHALL reject the signal.
    
    **Validates: Requirements 1.1**
    """
    # Create stage with default config (50% threshold, suppress deprecation warning)
    stage = create_confidence_gate_stage()
    default_threshold = 0.50
    
    # Create context with the given confidence
    ctx = StageContext(
        symbol=sym,
        data={
            "prediction": {"confidence": confidence}
        }
    )
    
    # Run the stage
    result = asyncio.run(stage.run(ctx))
    
    # Property: signals below 50% are rejected
    if confidence < default_threshold:
        assert result == StageResult.REJECT, \
            f"Signal with confidence {confidence} should be REJECTED (default threshold 50%)"
    else:
        assert result == StageResult.CONTINUE, \
            f"Signal with confidence {confidence} should CONTINUE (default threshold 50%)"


@settings(max_examples=100)
@given(
    confidence=confidence_value,
    threshold=threshold_value,
    sym=symbol,
)
def test_property_1_telemetry_emission(
    confidence: float,
    threshold: float,
    sym: str,
):
    """
    Property 1 (Telemetry): Blocked signals emit telemetry
    
    *For any* signal rejected by the confidence gate, telemetry SHALL be emitted
    with the confidence value and threshold.
    
    **Validates: Requirements 1.2**
    """
    # Create telemetry instance
    telemetry = BlockedSignalTelemetry()
    
    # Create stage with telemetry (suppress deprecation warning)
    config = ConfidenceGateConfig(min_confidence=threshold)
    stage = create_confidence_gate_stage(config=config, telemetry=telemetry)
    
    # Get initial count
    initial_count = telemetry.get_count_for_gate("confidence_gate")
    
    # Create context with the given confidence
    ctx = StageContext(
        symbol=sym,
        data={
            "prediction": {"confidence": confidence}
        }
    )
    
    # Run the stage
    result = asyncio.run(stage.run(ctx))
    
    # Get final count
    final_count = telemetry.get_count_for_gate("confidence_gate")
    
    # Property: rejected signals increment telemetry count
    if confidence < threshold:
        assert final_count == initial_count + 1, \
            f"Telemetry count should increment by 1 for rejected signal"
    else:
        assert final_count == initial_count, \
            f"Telemetry count should not change for passing signal"


@settings(max_examples=100)
@given(
    confidence_pct=st.floats(min_value=0.0, max_value=100.0, allow_nan=False, allow_infinity=False),
    sym=symbol,
)
def test_property_1_percentage_normalization(
    confidence_pct: float,
    sym: str,
):
    """
    Property 1 (Normalization): Confidence values > 1 are normalized
    
    *For any* confidence value provided as a percentage (0-100), the stage
    SHALL normalize it to the 0-1 range before comparison.
    
    **Validates: Requirements 1.1**
    """
    # Skip values that are ambiguous (could be 0-1 or 0-100)
    assume(confidence_pct > 1.0)
    
    # Create stage with default config (suppress deprecation warning)
    stage = create_confidence_gate_stage()
    default_threshold = 0.50
    
    # Create context with percentage confidence
    ctx = StageContext(
        symbol=sym,
        data={
            "prediction": {"confidence": confidence_pct}
        }
    )
    
    # Run the stage
    result = asyncio.run(stage.run(ctx))
    
    # Normalized confidence
    normalized = confidence_pct / 100.0
    
    # Property: normalized confidence is used for comparison
    if normalized < default_threshold:
        assert result == StageResult.REJECT, \
            f"Signal with {confidence_pct}% (normalized to {normalized}) should be REJECTED"
    else:
        assert result == StageResult.CONTINUE, \
            f"Signal with {confidence_pct}% (normalized to {normalized}) should CONTINUE"


@settings(max_examples=100)
@given(sym=symbol)
def test_property_1_missing_prediction_rejected(sym: str):
    """
    Property 1 (Edge Case): Missing prediction data is rejected
    
    *For any* signal with missing prediction data, the stage SHALL treat
    confidence as 0 and reject the signal.
    
    **Validates: Requirements 1.1**
    """
    # Create stage with default config (suppress deprecation warning)
    stage = create_confidence_gate_stage()
    
    # Create context with no prediction data
    ctx = StageContext(
        symbol=sym,
        data={}
    )
    
    # Run the stage
    result = asyncio.run(stage.run(ctx))
    
    # Property: missing prediction is treated as 0 confidence and rejected
    assert result == StageResult.REJECT, \
        "Signal with missing prediction should be REJECTED"
    assert ctx.rejection_reason == "low_confidence", \
        "Rejection reason should be 'low_confidence'"
    assert ctx.rejection_detail["confidence"] == 0.0, \
        "Missing confidence should be treated as 0.0"
