"""
Property-based tests for RelaxationEngine safety guards.

Feature: ev-based-entry-gate
Tests correctness properties for:
- Property 8: Relaxation Safety Guards

**Validates: Requirements 6.6, 6.7**
"""

import pytest
from hypothesis import given, strategies as st, settings, assume, HealthCheck

from quantgambit.signals.stages.ev_gate import (
    RelaxationEngine,
    EVGateConfig,
)


# =============================================================================
# Test Strategies (Generators)
# =============================================================================

# Spread percentile ∈ [0, 1]
spread_percentile = st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False)

# Book imbalance ∈ [-1, 1] (positive = more bids, negative = more asks)
book_imbalance = st.floats(min_value=-1.0, max_value=1.0, allow_nan=False, allow_infinity=False)

# Signal side
signal_side = st.sampled_from(["long", "short"])

# Volatility regime
volatility_regime = st.sampled_from(["low", "medium", "high"])

# Trading session
session = st.sampled_from(["us", "europe", "asia", "unknown"])

# Calibration reliability - low (below threshold)
low_reliability = st.floats(min_value=0.0, max_value=0.79, allow_nan=False, allow_infinity=False)

# Calibration reliability - high (at or above threshold)
high_reliability = st.floats(min_value=0.8, max_value=1.0, allow_nan=False, allow_infinity=False)

# Calibration reliability - any
any_reliability = st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False)

# Book age - fresh (below threshold)
fresh_book_age = st.floats(min_value=0.0, max_value=250.0, allow_nan=False, allow_infinity=False)

# Book age - stale (above threshold)
stale_book_age = st.floats(min_value=251.0, max_value=1000.0, allow_nan=False, allow_infinity=False)

# Book age - any
any_book_age = st.floats(min_value=0.0, max_value=1000.0, allow_nan=False, allow_infinity=False)

# Low spread percentile (triggers relaxation)
low_spread = st.floats(min_value=0.0, max_value=0.29, allow_nan=False, allow_infinity=False)

# High spread percentile (triggers tightening)
high_spread = st.floats(min_value=0.71, max_value=1.0, allow_nan=False, allow_infinity=False)

# Favorable imbalance for long (positive)
favorable_long_imbalance = st.floats(min_value=0.01, max_value=1.0, allow_nan=False, allow_infinity=False)

# Favorable imbalance for short (negative)
favorable_short_imbalance = st.floats(min_value=-1.0, max_value=-0.01, allow_nan=False, allow_infinity=False)


# =============================================================================
# Property 8: Relaxation Safety Guards
# Feature: ev-based-entry-gate, Property 8: Relaxation Safety Guards
# Validates: Requirements 6.6, 6.7
# =============================================================================

@settings(max_examples=100)
@given(
    spread_pct=spread_percentile,
    imbalance=book_imbalance,
    side=signal_side,
    vol_regime=volatility_regime,
    sess=session,
    reliability=low_reliability,  # Use generator that produces low values
    book_age=fresh_book_age,  # Use fresh book to isolate reliability check
)
def test_property_8_low_reliability_disables_relaxation(
    spread_pct: float,
    imbalance: float,
    side: str,
    vol_regime: str,
    sess: str,
    reliability: float,
    book_age: float,
):
    """
    Property 8: Relaxation Safety Guards (Low Reliability)
    
    *For any* scenario where calibration_reliability < 0.8, all relaxation
    SHALL be disabled (no relaxation factors < 1.0 in candidates).
    
    **Validates: Requirements 6.6**
    """
    # Create config with relaxation enabled
    config = EVGateConfig(
        max_book_age_ms=250,
        relaxation_spread_percentile=0.30,
        relaxation_multiplier=0.8,
        tightening_spread_percentile=0.70,
        tightening_multiplier=1.25,
    )
    engine = RelaxationEngine(config)
    
    # Compute adjustment
    result = engine.compute_adjustment(
        spread_percentile=spread_pct,
        book_imbalance=imbalance,
        signal_side=side,
        volatility_regime=vol_regime,
        session=sess,
        calibration_reliability=reliability,
        book_age_ms=book_age,
    )
    
    # Property: No relaxation factors (< 1.0) should be present when reliability is low
    # Only base (1.0) and tightening (> 1.0) factors are allowed
    relaxation_factors = [f for f, _ in result.candidate_factors if f < 1.0]
    
    assert len(relaxation_factors) == 0, \
        f"Relaxation factors {relaxation_factors} should not be present when reliability={reliability} < 0.8"


@settings(max_examples=100)
@given(
    spread_pct=spread_percentile,
    imbalance=book_imbalance,
    side=signal_side,
    vol_regime=volatility_regime,
    sess=session,
    reliability=high_reliability,  # Use high reliability to isolate book age check
    book_age=stale_book_age,  # Use generator that produces stale values
)
def test_property_8_stale_book_disables_relaxation(
    spread_pct: float,
    imbalance: float,
    side: str,
    vol_regime: str,
    sess: str,
    reliability: float,
    book_age: float,
):
    """
    Property 8: Relaxation Safety Guards (Stale Book)
    
    *For any* scenario where book_age_ms > MAX_BOOK_AGE_MS, all relaxation
    SHALL be disabled (no relaxation factors < 1.0 in candidates).
    
    **Validates: Requirements 6.7**
    """
    # Create config with max_book_age_ms=250
    config = EVGateConfig(
        max_book_age_ms=250,
        relaxation_spread_percentile=0.30,
        relaxation_multiplier=0.8,
        tightening_spread_percentile=0.70,
        tightening_multiplier=1.25,
    )
    engine = RelaxationEngine(config)
    
    # Compute adjustment
    result = engine.compute_adjustment(
        spread_percentile=spread_pct,
        book_imbalance=imbalance,
        signal_side=side,
        volatility_regime=vol_regime,
        session=sess,
        calibration_reliability=reliability,
        book_age_ms=book_age,
    )
    
    # Property: No relaxation factors (< 1.0) should be present when book is stale
    # Only base (1.0) and tightening (> 1.0) factors are allowed
    relaxation_factors = [f for f, _ in result.candidate_factors if f < 1.0]
    
    assert len(relaxation_factors) == 0, \
        f"Relaxation factors {relaxation_factors} should not be present when book_age={book_age}ms > max=250ms"


@settings(max_examples=100)
@given(
    spread_pct=high_spread,  # Use high spread to trigger tightening
    imbalance=book_imbalance,
    side=signal_side,
    vol_regime=volatility_regime,
    sess=session,
    reliability=low_reliability,  # Low reliability triggers safety guard
    book_age=fresh_book_age,
)
def test_property_8_tightening_still_applies_with_low_reliability(
    spread_pct: float,
    imbalance: float,
    side: str,
    vol_regime: str,
    sess: str,
    reliability: float,
    book_age: float,
):
    """
    Property 8: Relaxation Safety Guards (Tightening Still Applies with Low Reliability)
    
    *For any* scenario where reliability < 0.8 (safety guard triggered),
    tightening SHALL still apply when spread_percentile > 70%.
    
    **Validates: Requirements 6.6**
    """
    # Create config
    config = EVGateConfig(
        max_book_age_ms=250,
        relaxation_spread_percentile=0.30,
        relaxation_multiplier=0.8,
        tightening_spread_percentile=0.70,
        tightening_multiplier=1.25,
    )
    engine = RelaxationEngine(config)
    
    # Compute adjustment
    result = engine.compute_adjustment(
        spread_percentile=spread_pct,
        book_imbalance=imbalance,
        signal_side=side,
        volatility_regime=vol_regime,
        session=sess,
        calibration_reliability=reliability,
        book_age_ms=book_age,
    )
    
    # Property: Tightening factor (1.25) should still be present
    tightening_factors = [f for f, _ in result.candidate_factors if f > 1.0]
    
    assert 1.25 in tightening_factors, \
        f"Tightening factor 1.25 should be present when spread_pct={spread_pct} > 0.70, " \
        f"even with low reliability={reliability}"


@settings(max_examples=100)
@given(
    spread_pct=high_spread,  # Use high spread to trigger tightening
    imbalance=book_imbalance,
    side=signal_side,
    vol_regime=volatility_regime,
    sess=session,
    reliability=high_reliability,
    book_age=stale_book_age,  # Stale book triggers safety guard
)
def test_property_8_tightening_still_applies_with_stale_book(
    spread_pct: float,
    imbalance: float,
    side: str,
    vol_regime: str,
    sess: str,
    reliability: float,
    book_age: float,
):
    """
    Property 8: Relaxation Safety Guards (Tightening Still Applies with Stale Book)
    
    *For any* scenario where book_age > MAX_BOOK_AGE_MS (safety guard triggered),
    tightening SHALL still apply when spread_percentile > 70%.
    
    **Validates: Requirements 6.7**
    """
    # Create config
    config = EVGateConfig(
        max_book_age_ms=250,
        relaxation_spread_percentile=0.30,
        relaxation_multiplier=0.8,
        tightening_spread_percentile=0.70,
        tightening_multiplier=1.25,
    )
    engine = RelaxationEngine(config)
    
    # Compute adjustment
    result = engine.compute_adjustment(
        spread_percentile=spread_pct,
        book_imbalance=imbalance,
        signal_side=side,
        volatility_regime=vol_regime,
        session=sess,
        calibration_reliability=reliability,
        book_age_ms=book_age,
    )
    
    # Property: Tightening factor (1.25) should still be present
    tightening_factors = [f for f, _ in result.candidate_factors if f > 1.0]
    
    assert 1.25 in tightening_factors, \
        f"Tightening factor 1.25 should be present when spread_pct={spread_pct} > 0.70, " \
        f"even with stale book_age={book_age}ms"


@settings(max_examples=100)
@given(
    spread_pct=low_spread,  # Low spread for relaxation
    imbalance=favorable_long_imbalance,  # Favorable for long
    vol_regime=volatility_regime,
    sess=session,
    reliability=high_reliability,  # Good reliability
    book_age=fresh_book_age,  # Fresh book
)
def test_property_8_good_conditions_allow_relaxation_long(
    spread_pct: float,
    imbalance: float,
    vol_regime: str,
    sess: str,
    reliability: float,
    book_age: float,
):
    """
    Property 8: Relaxation Safety Guards (Good Conditions Allow Relaxation - Long)
    
    *For any* scenario where calibration_reliability >= 0.8 AND book_age_ms <= MAX_BOOK_AGE_MS,
    relaxation SHALL be allowed for long signals with favorable imbalance.
    
    **Validates: Requirements 6.6, 6.7**
    """
    # Create config
    config = EVGateConfig(
        max_book_age_ms=250,
        relaxation_spread_percentile=0.30,
        relaxation_multiplier=0.8,
        tightening_spread_percentile=0.70,
        tightening_multiplier=1.25,
    )
    engine = RelaxationEngine(config)
    
    # Compute adjustment for long signal
    result = engine.compute_adjustment(
        spread_percentile=spread_pct,
        book_imbalance=imbalance,
        signal_side="long",
        volatility_regime=vol_regime,
        session=sess,
        calibration_reliability=reliability,
        book_age_ms=book_age,
    )
    
    # Property: Relaxation factor (0.8) should be present when conditions are favorable
    relaxation_factors = [f for f, _ in result.candidate_factors if f < 1.0]
    
    assert 0.8 in relaxation_factors, \
        f"Relaxation factor 0.8 should be present when safety guards pass " \
        f"(reliability={reliability} >= 0.8, book_age={book_age} <= 250) " \
        f"and conditions are favorable (spread_pct={spread_pct} < 0.30, imbalance={imbalance} > 0)"


@settings(max_examples=100)
@given(
    spread_pct=low_spread,  # Low spread for relaxation
    imbalance=favorable_short_imbalance,  # Favorable for short
    vol_regime=volatility_regime,
    sess=session,
    reliability=high_reliability,  # Good reliability
    book_age=fresh_book_age,  # Fresh book
)
def test_property_8_good_conditions_allow_relaxation_short(
    spread_pct: float,
    imbalance: float,
    vol_regime: str,
    sess: str,
    reliability: float,
    book_age: float,
):
    """
    Property 8: Relaxation Safety Guards (Good Conditions Allow Relaxation - Short)
    
    *For any* scenario where calibration_reliability >= 0.8 AND book_age_ms <= MAX_BOOK_AGE_MS,
    relaxation SHALL be allowed for short signals with favorable imbalance.
    
    **Validates: Requirements 6.6, 6.7**
    """
    # Create config
    config = EVGateConfig(
        max_book_age_ms=250,
        relaxation_spread_percentile=0.30,
        relaxation_multiplier=0.8,
        tightening_spread_percentile=0.70,
        tightening_multiplier=1.25,
    )
    engine = RelaxationEngine(config)
    
    # Compute adjustment for short signal
    result = engine.compute_adjustment(
        spread_percentile=spread_pct,
        book_imbalance=imbalance,
        signal_side="short",
        volatility_regime=vol_regime,
        session=sess,
        calibration_reliability=reliability,
        book_age_ms=book_age,
    )
    
    # Property: Relaxation factor (0.8) should be present when conditions are favorable
    relaxation_factors = [f for f, _ in result.candidate_factors if f < 1.0]
    
    assert 0.8 in relaxation_factors, \
        f"Relaxation factor 0.8 should be present when safety guards pass " \
        f"(reliability={reliability} >= 0.8, book_age={book_age} <= 250) " \
        f"and conditions are favorable (spread_pct={spread_pct} < 0.30, imbalance={imbalance} < 0)"


@settings(max_examples=100)
@given(
    reliability=any_reliability,
    book_age=fresh_book_age,  # Fresh book to isolate reliability check
)
def test_property_8_safety_guard_boundary_reliability(
    reliability: float,
    book_age: float,
):
    """
    Property 8: Relaxation Safety Guards (Reliability Boundary)
    
    *For any* reliability value, the safety guard SHALL be triggered if and only if
    reliability < 0.8 (the RELAXATION_RELIABILITY_THRESHOLD).
    
    **Validates: Requirements 6.6**
    """
    config = EVGateConfig(
        max_book_age_ms=250,
        relaxation_spread_percentile=0.30,
        relaxation_multiplier=0.8,
    )
    engine = RelaxationEngine(config)
    
    # Check the internal safety guard method
    relaxation_disabled = engine._check_relaxation_safety_guards(
        calibration_reliability=reliability,
        book_age_ms=book_age,
    )
    
    # Property: Safety guard triggered iff reliability < 0.8
    expected_disabled = reliability < 0.8
    
    assert relaxation_disabled == expected_disabled, \
        f"Safety guard should be {'triggered' if expected_disabled else 'not triggered'} " \
        f"when reliability={reliability} {'<' if expected_disabled else '>='} 0.8"


@settings(max_examples=100)
@given(
    reliability=high_reliability,  # High reliability to isolate book age check
    book_age=any_book_age,
)
def test_property_8_safety_guard_boundary_book_age(
    reliability: float,
    book_age: float,
):
    """
    Property 8: Relaxation Safety Guards (Book Age Boundary)
    
    *For any* book_age value, the safety guard SHALL be triggered if and only if
    book_age > MAX_BOOK_AGE_MS (250ms).
    
    **Validates: Requirements 6.7**
    """
    config = EVGateConfig(
        max_book_age_ms=250,
        relaxation_spread_percentile=0.30,
        relaxation_multiplier=0.8,
    )
    engine = RelaxationEngine(config)
    
    # Check the internal safety guard method
    relaxation_disabled = engine._check_relaxation_safety_guards(
        calibration_reliability=reliability,
        book_age_ms=book_age,
    )
    
    # Property: Safety guard triggered iff book_age > 250
    expected_disabled = book_age > 250
    
    assert relaxation_disabled == expected_disabled, \
        f"Safety guard should be {'triggered' if expected_disabled else 'not triggered'} " \
        f"when book_age={book_age}ms {'>' if expected_disabled else '<='} 250ms"


@settings(max_examples=100)
@given(
    reliability=any_reliability,
    book_age=any_book_age,
)
def test_property_8_either_guard_disables_relaxation(
    reliability: float,
    book_age: float,
):
    """
    Property 8: Relaxation Safety Guards (Either Guard Disables)
    
    *For any* scenario, relaxation SHALL be disabled if EITHER reliability < 0.8
    OR book_age > MAX_BOOK_AGE_MS (logical OR).
    
    **Validates: Requirements 6.6, 6.7**
    """
    config = EVGateConfig(
        max_book_age_ms=250,
        relaxation_spread_percentile=0.30,
        relaxation_multiplier=0.8,
    )
    engine = RelaxationEngine(config)
    
    # Check the internal safety guard method
    relaxation_disabled = engine._check_relaxation_safety_guards(
        calibration_reliability=reliability,
        book_age_ms=book_age,
    )
    
    # Property: Relaxation disabled iff (reliability < 0.8 OR book_age > 250)
    expected_disabled = (reliability < 0.8) or (book_age > 250)
    
    assert relaxation_disabled == expected_disabled, \
        f"Safety guard should be {'triggered' if expected_disabled else 'not triggered'} " \
        f"when reliability={reliability} and book_age={book_age}ms"
