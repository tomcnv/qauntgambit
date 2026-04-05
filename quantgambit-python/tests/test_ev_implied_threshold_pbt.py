"""
Property-based tests for EV Gate implied threshold calculation.

Feature: ev-based-entry-gate
Tests correctness properties for:
- Property 2: Implied Threshold Correctness

**Validates: Requirements 1.6, 2.1, 2.2, 2.3**
"""

import pytest
import math
from hypothesis import given, strategies as st, settings, assume

from quantgambit.signals.stages.ev_gate import calculate_p_min, calculate_ev


# =============================================================================
# Test Strategies (Generators)
# =============================================================================

# Reward-to-risk ratio R > 0 (positive, reasonable range)
reward_risk_ratio = st.floats(min_value=0.01, max_value=10.0, allow_nan=False, allow_infinity=False)

# Cost ratio C ≥ 0 (non-negative, reasonable range)
cost_ratio = st.floats(min_value=0.0, max_value=0.99, allow_nan=False, allow_infinity=False)


# =============================================================================
# Property 2: Implied Threshold Correctness
# Feature: ev-based-entry-gate, Property 2: Implied Threshold Correctness
# Validates: Requirements 1.6, 2.1, 2.2, 2.3
# =============================================================================

@settings(max_examples=100)
@given(
    R=reward_risk_ratio,
    C=cost_ratio,
)
def test_property_2_implied_threshold_formula(
    R: float,
    C: float,
):
    """
    Property 2: Implied Threshold Correctness
    
    *For any* valid R > 0 and C ≥ 0, the computed p_min SHALL equal
    `(1 + C) / (R + 1)` within floating-point tolerance.
    
    **Validates: Requirements 1.6**
    """
    # Calculate p_min using the function under test
    p_min = calculate_p_min(R, C)
    
    # Expected value using the formula: p_min = (1 + C) / (R + 1)
    expected = (1 + C) / (R + 1)
    
    # Property: p_min equals expected formula within floating-point tolerance
    assert abs(p_min - expected) < 1e-9, \
        f"p_min={p_min} should equal expected={(1+C)/(R+1)}={expected} for R={R}, C={C}"


@settings(max_examples=100)
@given(
    R=reward_risk_ratio,
    C=cost_ratio,
)
def test_property_2_p_min_is_breakeven(
    R: float,
    C: float,
):
    """
    Property 2: p_min is the breakeven probability (EV = 0 at p_min)
    
    *For any* R > 0 and C ≥ 0, when p = p_min, EV SHALL equal 0.
    
    **Validates: Requirements 1.6**
    """
    # Calculate p_min
    p_min = calculate_p_min(R, C)
    
    # Skip if p_min is outside valid probability range
    assume(0 <= p_min <= 1)
    
    # Calculate EV at p_min
    ev = calculate_ev(p_min, R, C)
    
    # Property: EV equals 0 at p_min (breakeven)
    assert abs(ev) < 1e-9, \
        f"EV={ev} should equal 0 at p_min={p_min} for R={R}, C={C}"


@settings(max_examples=100)
@given(
    R=reward_risk_ratio,
    C=cost_ratio,
)
def test_property_2_ev_positive_above_p_min(
    R: float,
    C: float,
):
    """
    Property 2: EV is positive when p > p_min
    
    *For any* R > 0 and C ≥ 0, when p > p_min, EV SHALL be positive.
    
    **Validates: Requirements 1.6**
    """
    # Calculate p_min
    p_min = calculate_p_min(R, C)
    
    # Skip if p_min is outside valid range or too close to 1
    assume(0 <= p_min < 0.99)
    
    # Test with p slightly above p_min
    delta = 0.01
    p = min(p_min + delta, 1.0)
    
    # Calculate EV
    ev = calculate_ev(p, R, C)
    
    # Property: EV is positive when p > p_min
    assert ev > 0, \
        f"EV={ev} should be positive when p={p} > p_min={p_min} for R={R}, C={C}"


@settings(max_examples=100)
@given(
    R=reward_risk_ratio,
    C=cost_ratio,
)
def test_property_2_ev_negative_below_p_min(
    R: float,
    C: float,
):
    """
    Property 2: EV is negative when p < p_min
    
    *For any* R > 0 and C ≥ 0, when p < p_min, EV SHALL be negative.
    
    **Validates: Requirements 1.6**
    """
    # Calculate p_min
    p_min = calculate_p_min(R, C)
    
    # Skip if p_min is outside valid range or too close to 0
    assume(0.01 < p_min <= 1)
    
    # Test with p slightly below p_min
    delta = 0.01
    p = max(p_min - delta, 0.0)
    
    # Calculate EV
    ev = calculate_ev(p, R, C)
    
    # Property: EV is negative when p < p_min
    assert ev < 0, \
        f"EV={ev} should be negative when p={p} < p_min={p_min} for R={R}, C={C}"


@settings(max_examples=100)
@given(
    R=reward_risk_ratio,
    C=cost_ratio,
)
def test_property_2_p_min_decreases_with_r(
    R: float,
    C: float,
):
    """
    Property 2: p_min decreases as R increases (better risk/reward = lower threshold)
    
    *For any* fixed C ≥ 0, p_min SHALL decrease as R increases.
    
    **Validates: Requirements 1.6, 2.1, 2.2, 2.3**
    """
    # Skip edge case where R is already at max
    assume(R < 9.9)
    
    # Calculate p_min at R and R + delta
    delta = 0.1
    p_min_low_r = calculate_p_min(R, C)
    p_min_high_r = calculate_p_min(R + delta, C)
    
    # Property: p_min decreases with R
    assert p_min_high_r < p_min_low_r, \
        f"p_min should decrease with R: p_min(R={R})={p_min_low_r}, p_min(R={R+delta})={p_min_high_r}"


@settings(max_examples=100)
@given(
    R=reward_risk_ratio,
    C=cost_ratio,
)
def test_property_2_p_min_increases_with_c(
    R: float,
    C: float,
):
    """
    Property 2: p_min increases as C increases (higher costs = higher threshold)
    
    *For any* fixed R > 0, p_min SHALL increase as C increases.
    
    **Validates: Requirements 1.6**
    """
    # Skip edge case where C is already at max
    assume(C < 0.98)
    
    # Calculate p_min at C and C + delta
    delta = 0.01
    p_min_low_c = calculate_p_min(R, C)
    p_min_high_c = calculate_p_min(R, C + delta)
    
    # Property: p_min increases with C
    assert p_min_high_c > p_min_low_c, \
        f"p_min should increase with C: p_min(C={C})={p_min_low_c}, p_min(C={C+delta})={p_min_high_c}"


# =============================================================================
# Specific Example Tests (Requirements 2.1, 2.2, 2.3)
# =============================================================================

def test_requirement_2_1_r_1_c_0_10():
    """
    Requirement 2.1: WHEN R = 1.0 and C = 0.10, THEN p_min > 55%
    
    **Validates: Requirements 2.1**
    """
    R = 1.0
    C = 0.10
    
    # Calculate p_min
    p_min = calculate_p_min(R, C)
    
    # Expected: p_min = (1 + 0.10) / (1.0 + 1) = 1.10 / 2 = 0.55
    expected = 0.55
    
    # Property: p_min equals 55%
    assert abs(p_min - expected) < 1e-9, \
        f"p_min={p_min} should equal {expected} for R={R}, C={C}"


def test_requirement_2_2_r_0_7_c_0_10():
    """
    Requirement 2.2: WHEN R = 0.7 and C = 0.10, THEN p_min > 64.7%
    
    **Validates: Requirements 2.2**
    """
    R = 0.7
    C = 0.10
    
    # Calculate p_min
    p_min = calculate_p_min(R, C)
    
    # Expected: p_min = (1 + 0.10) / (0.7 + 1) = 1.10 / 1.7 ≈ 0.647
    expected = 1.10 / 1.7
    
    # Property: p_min equals approximately 64.7%
    assert abs(p_min - expected) < 1e-9, \
        f"p_min={p_min} should equal {expected:.4f} for R={R}, C={C}"
    
    # Also verify it's approximately 64.7%
    assert abs(p_min - 0.647) < 0.001, \
        f"p_min={p_min:.3f} should be approximately 64.7%"


def test_requirement_2_3_r_2_c_0_10():
    """
    Requirement 2.3: WHEN R = 2.0 and C = 0.10, THEN p_min > 36.7%
    
    **Validates: Requirements 2.3**
    """
    R = 2.0
    C = 0.10
    
    # Calculate p_min
    p_min = calculate_p_min(R, C)
    
    # Expected: p_min = (1 + 0.10) / (2.0 + 1) = 1.10 / 3 ≈ 0.367
    expected = 1.10 / 3.0
    
    # Property: p_min equals approximately 36.7%
    assert abs(p_min - expected) < 1e-9, \
        f"p_min={p_min} should equal {expected:.4f} for R={R}, C={C}"
    
    # Also verify it's approximately 36.7%
    assert abs(p_min - 0.367) < 0.001, \
        f"p_min={p_min:.3f} should be approximately 36.7%"


# =============================================================================
# Edge Case Tests
# =============================================================================

@settings(max_examples=100)
@given(
    R=reward_risk_ratio,
)
def test_property_2_p_min_at_c_zero(
    R: float,
):
    """
    Property 2 (C=0): When C=0, p_min = 1 / (R + 1)
    
    *For any* R > 0, when C=0, p_min SHALL equal 1 / (R + 1).
    
    **Validates: Requirements 1.6**
    """
    C = 0.0
    
    # Calculate p_min
    p_min = calculate_p_min(R, C)
    
    # Expected: p_min = (1 + 0) / (R + 1) = 1 / (R + 1)
    expected = 1 / (R + 1)
    
    # Property: p_min equals 1 / (R + 1) when C=0
    assert abs(p_min - expected) < 1e-9, \
        f"p_min={p_min} should equal 1/(R+1)={expected} when C=0"


@settings(max_examples=100)
@given(
    C=cost_ratio,
)
def test_property_2_p_min_at_r_one(
    C: float,
):
    """
    Property 2 (R=1): When R=1, p_min = (1 + C) / 2
    
    *For any* C ≥ 0, when R=1, p_min SHALL equal (1 + C) / 2.
    
    **Validates: Requirements 1.6**
    """
    R = 1.0
    
    # Calculate p_min
    p_min = calculate_p_min(R, C)
    
    # Expected: p_min = (1 + C) / (1 + 1) = (1 + C) / 2
    expected = (1 + C) / 2
    
    # Property: p_min equals (1 + C) / 2 when R=1
    assert abs(p_min - expected) < 1e-9, \
        f"p_min={p_min} should equal (1+C)/2={expected} when R=1"


def test_property_2_p_min_bounds():
    """
    Property 2 (Bounds): p_min is bounded by reasonable values
    
    For typical trading scenarios:
    - When R is high (good risk/reward), p_min should be low
    - When R is low (poor risk/reward), p_min should be high
    
    **Validates: Requirements 1.6**
    """
    # High R, low C: p_min should be low
    p_min_favorable = calculate_p_min(R=3.0, C=0.05)
    assert p_min_favorable < 0.30, \
        f"p_min={p_min_favorable} should be < 30% for favorable R=3, C=0.05"
    
    # Low R, high C: p_min should be high
    p_min_unfavorable = calculate_p_min(R=0.5, C=0.20)
    assert p_min_unfavorable > 0.70, \
        f"p_min={p_min_unfavorable} should be > 70% for unfavorable R=0.5, C=0.20"
    
    # R=1, C=0: p_min should be exactly 50%
    p_min_neutral = calculate_p_min(R=1.0, C=0.0)
    assert abs(p_min_neutral - 0.5) < 1e-9, \
        f"p_min={p_min_neutral} should be exactly 50% for R=1, C=0"
