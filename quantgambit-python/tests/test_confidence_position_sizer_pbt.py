"""
Property-based tests for ConfidencePositionSizer.

Feature: trading-loss-fixes
Tests correctness properties for:
- Property 5: Confidence-Based Position Sizing

**Validates: Requirements 7.1, 7.2, 7.3, 7.4, 7.5**

NOTE: ConfidencePositionSizer is deprecated in favor of EVPositionSizerStage.
These tests suppress deprecation warnings to validate legacy behavior.
"""

import pytest
import asyncio
import warnings
from hypothesis import given, strategies as st, settings, assume

from quantgambit.signals.stages.confidence_position_sizer import (
    ConfidencePositionSizer,
    ConfidencePositionSizerConfig,
    ConfidencePositionSizerStage,
    CONFIDENCE_MULTIPLIERS,
)
from quantgambit.signals.pipeline import StageContext, StageResult


# =============================================================================
# Helpers to create deprecated classes without warnings
# =============================================================================

def create_confidence_position_sizer(config=None):
    """Create ConfidencePositionSizer with deprecation warnings suppressed."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        return ConfidencePositionSizer(config=config)


def create_confidence_position_sizer_stage(config=None, telemetry=None):
    """Create ConfidencePositionSizerStage with deprecation warnings suppressed."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        return ConfidencePositionSizerStage(config=config, telemetry=telemetry)


# =============================================================================
# Test Strategies (Generators)
# =============================================================================

# Confidence values in 0-1 range
confidence_value = st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False)

# Position sizes (positive values)
position_size = st.floats(min_value=0.01, max_value=1000000.0, allow_nan=False, allow_infinity=False)

# Position sizes in USD
position_size_usd = st.floats(min_value=1.0, max_value=10000000.0, allow_nan=False, allow_infinity=False)

# Symbols
symbol = st.sampled_from(["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT"])


# =============================================================================
# Property 5: Confidence-Based Position Sizing
# Feature: trading-loss-fixes, Property 5: Confidence-Based Position Sizing
# Validates: Requirements 7.1, 7.2, 7.3, 7.4, 7.5
# =============================================================================

@settings(max_examples=100)
@given(
    confidence=confidence_value,
)
def test_property_5_confidence_multiplier_bands(confidence: float):
    """
    Property 5: Confidence-Based Position Sizing - Multiplier Bands
    
    *For any* signal that passes the confidence gate, the position size SHALL be 
    multiplied by the confidence multiplier corresponding to the signal's confidence band:
    - 50-60% → 0.5x
    - 60-75% → 0.75x
    - 75-90% → 1.0x
    - 90%+ → 1.25x
    
    **Validates: Requirements 7.1, 7.2, 7.3, 7.4, 7.5**
    """
    sizer = create_confidence_position_sizer()
    multiplier = sizer.get_multiplier(confidence)
    
    # Property: multiplier matches the correct band
    if 0.50 <= confidence < 0.60:
        assert multiplier == 0.50, \
            f"Confidence {confidence} (50-60%) should get 0.5x multiplier, got {multiplier}"
    elif 0.60 <= confidence < 0.75:
        assert multiplier == 0.75, \
            f"Confidence {confidence} (60-75%) should get 0.75x multiplier, got {multiplier}"
    elif 0.75 <= confidence < 0.90:
        assert multiplier == 1.00, \
            f"Confidence {confidence} (75-90%) should get 1.0x multiplier, got {multiplier}"
    elif 0.90 <= confidence <= 1.0:
        assert multiplier == 1.25, \
            f"Confidence {confidence} (90%+) should get 1.25x multiplier, got {multiplier}"
    else:
        # Below 50% - should get default multiplier (1.0)
        assert multiplier == 1.0, \
            f"Confidence {confidence} (below 50%) should get default 1.0x multiplier, got {multiplier}"


@settings(max_examples=100)
@given(
    confidence=confidence_value,
    size=position_size,
    size_usd=position_size_usd,
    sym=symbol,
)
def test_property_5_position_size_scaling(
    confidence: float,
    size: float,
    size_usd: float,
    sym: str,
):
    """
    Property 5: Confidence-Based Position Sizing - Size Scaling
    
    *For any* signal with size fields, applying the confidence sizer SHALL
    scale both 'size' and 'size_usd' by the correct multiplier.
    
    **Validates: Requirements 7.1, 7.6**
    """
    # Only test signals that would pass confidence gate (>= 50%)
    assume(confidence >= 0.50)
    
    sizer = create_confidence_position_sizer()
    expected_multiplier = sizer.get_multiplier(confidence)
    
    # Create signal with size fields
    signal = {
        "symbol": sym,
        "side": "long",
        "size": size,
        "size_usd": size_usd,
    }
    
    # Apply sizing
    result = sizer.apply(signal.copy(), confidence)
    
    # Property: sizes are scaled by the correct multiplier
    expected_size = size * expected_multiplier
    expected_size_usd = size_usd * expected_multiplier
    
    assert abs(result["size"] - expected_size) < 1e-9, \
        f"Size should be {expected_size}, got {result['size']}"
    assert abs(result["size_usd"] - expected_size_usd) < 1e-9, \
        f"Size USD should be {expected_size_usd}, got {result['size_usd']}"


@settings(max_examples=100)
@given(
    confidence=confidence_value,
    size=position_size,
    sym=symbol,
)
def test_property_5_metadata_added(
    confidence: float,
    size: float,
    sym: str,
):
    """
    Property 5: Confidence-Based Position Sizing - Metadata
    
    *For any* signal processed by the sizer, the signal SHALL contain
    'confidence_multiplier' and 'confidence' metadata fields.
    
    **Validates: Requirements 7.7**
    """
    sizer = create_confidence_position_sizer()
    
    # Create signal
    signal = {
        "symbol": sym,
        "side": "long",
        "size": size,
    }
    
    # Apply sizing
    result = sizer.apply(signal.copy(), confidence)
    
    # Property: metadata is added
    assert "confidence_multiplier" in result, \
        "Signal should have 'confidence_multiplier' field"
    assert "confidence" in result, \
        "Signal should have 'confidence' field"
    
    # Verify values
    expected_multiplier = sizer.get_multiplier(confidence)
    assert result["confidence_multiplier"] == expected_multiplier, \
        f"confidence_multiplier should be {expected_multiplier}, got {result['confidence_multiplier']}"
    
    # Confidence should be normalized to 0-1 range
    expected_confidence = confidence / 100.0 if confidence > 1.0 else confidence
    assert result["confidence"] == expected_confidence, \
        f"confidence should be {expected_confidence}, got {result['confidence']}"


@settings(max_examples=100)
@given(
    confidence_pct=st.floats(min_value=50.0, max_value=100.0, allow_nan=False, allow_infinity=False),
    size=position_size,
    sym=symbol,
)
def test_property_5_percentage_normalization(
    confidence_pct: float,
    size: float,
    sym: str,
):
    """
    Property 5: Confidence-Based Position Sizing - Percentage Normalization
    
    *For any* confidence value provided as a percentage (0-100), the sizer
    SHALL normalize it to the 0-1 range before applying the multiplier.
    
    **Validates: Requirements 7.1**
    """
    sizer = create_confidence_position_sizer()
    
    # Get multiplier for percentage value
    multiplier_from_pct = sizer.get_multiplier(confidence_pct)
    
    # Get multiplier for normalized value
    normalized = confidence_pct / 100.0
    multiplier_from_normalized = sizer.get_multiplier(normalized)
    
    # Property: both should give the same multiplier
    assert multiplier_from_pct == multiplier_from_normalized, \
        f"Percentage {confidence_pct}% and normalized {normalized} should give same multiplier"


@settings(max_examples=100)
@given(
    confidence=st.floats(min_value=0.50, max_value=1.0, allow_nan=False, allow_infinity=False),
    size=position_size,
    sym=symbol,
)
def test_property_5_stage_applies_sizing(
    confidence: float,
    size: float,
    sym: str,
):
    """
    Property 5: Confidence-Based Position Sizing - Stage Integration
    
    *For any* signal in the pipeline context, the ConfidencePositionSizerStage
    SHALL apply the correct multiplier to the signal's size fields.
    
    **Validates: Requirements 7.1, 7.6**
    """
    stage = create_confidence_position_sizer_stage()
    sizer = create_confidence_position_sizer()
    expected_multiplier = sizer.get_multiplier(confidence)
    
    # Create context with signal and prediction
    ctx = StageContext(
        symbol=sym,
        data={
            "prediction": {"confidence": confidence}
        },
        signal={
            "symbol": sym,
            "side": "long",
            "size": size,
        }
    )
    
    # Run the stage
    result = asyncio.run(stage.run(ctx))
    
    # Property: stage continues and applies sizing
    assert result == StageResult.CONTINUE, \
        f"Stage should CONTINUE, got {result}"
    
    # Verify sizing was applied
    expected_size = size * expected_multiplier
    assert abs(ctx.signal["size"] - expected_size) < 1e-9, \
        f"Signal size should be {expected_size}, got {ctx.signal['size']}"
    
    # Verify metadata was added
    assert ctx.signal.get("confidence_multiplier") == expected_multiplier, \
        f"Signal should have confidence_multiplier={expected_multiplier}"
    assert ctx.signal.get("confidence") == confidence, \
        f"Signal should have confidence={confidence}"


@settings(max_examples=100)
@given(sym=symbol)
def test_property_5_no_signal_continues(sym: str):
    """
    Property 5: Confidence-Based Position Sizing - No Signal
    
    *For any* context without a signal, the stage SHALL continue without error.
    
    **Validates: Requirements 7.6**
    """
    stage = create_confidence_position_sizer_stage()
    
    # Create context without signal
    ctx = StageContext(
        symbol=sym,
        data={
            "prediction": {"confidence": 0.75}
        },
        signal=None,
    )
    
    # Run the stage
    result = asyncio.run(stage.run(ctx))
    
    # Property: stage continues without error
    assert result == StageResult.CONTINUE, \
        f"Stage should CONTINUE when no signal, got {result}"


@settings(max_examples=100)
@given(
    confidence=st.floats(min_value=0.50, max_value=1.0, allow_nan=False, allow_infinity=False),
    sym=symbol,
)
def test_property_5_missing_size_fields(
    confidence: float,
    sym: str,
):
    """
    Property 5: Confidence-Based Position Sizing - Missing Size Fields
    
    *For any* signal without size fields, the sizer SHALL add metadata
    without raising errors.
    
    **Validates: Requirements 7.7**
    """
    sizer = create_confidence_position_sizer()
    
    # Create signal without size fields
    signal = {
        "symbol": sym,
        "side": "long",
    }
    
    # Apply sizing - should not raise
    result = sizer.apply(signal.copy(), confidence)
    
    # Property: metadata is still added
    assert "confidence_multiplier" in result, \
        "Signal should have 'confidence_multiplier' even without size fields"
    assert "confidence" in result, \
        "Signal should have 'confidence' even without size fields"


@settings(max_examples=100)
@given(
    confidence=st.floats(min_value=0.50, max_value=1.0, allow_nan=False, allow_infinity=False),
    size=position_size,
)
def test_property_5_multiplier_monotonicity(
    confidence: float,
    size: float,
):
    """
    Property 5: Confidence-Based Position Sizing - Monotonicity
    
    *For any* two confidence values where c1 < c2, the resulting position
    size for c2 SHALL be >= the position size for c1 (within the same band
    or across bands).
    
    This ensures higher confidence never results in smaller positions.
    
    **Validates: Requirements 7.2, 7.3, 7.4, 7.5**
    """
    sizer = create_confidence_position_sizer()
    
    # Get multipliers for confidence and confidence + small delta
    m1 = sizer.get_multiplier(confidence)
    
    # Test with a slightly higher confidence
    higher_confidence = min(1.0, confidence + 0.01)
    m2 = sizer.get_multiplier(higher_confidence)
    
    # Property: higher confidence should give >= multiplier
    assert m2 >= m1, \
        f"Higher confidence {higher_confidence} should give >= multiplier than {confidence}: {m2} vs {m1}"
