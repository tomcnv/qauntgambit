"""
Property-based tests for EV Gate EV formula calculation.

Feature: ev-based-entry-gate
Tests correctness properties for:
- Property 1: EV Formula Correctness

**Validates: Requirements 1.4**
"""

import pytest
import math
from hypothesis import given, strategies as st, settings, assume

from quantgambit.signals.stages.ev_gate import calculate_ev


# =============================================================================
# Test Strategies (Generators)
# =============================================================================

# Win probability p ∈ [0, 1]
probability = st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False)

# Reward-to-risk ratio R > 0 (positive, reasonable range)
reward_risk_ratio = st.floats(min_value=0.01, max_value=10.0, allow_nan=False, allow_infinity=False)

# Cost ratio C ≥ 0 (non-negative, reasonable range)
cost_ratio = st.floats(min_value=0.0, max_value=0.99, allow_nan=False, allow_infinity=False)


# =============================================================================
# Property 1: EV Formula Correctness
# Feature: ev-based-entry-gate, Property 1: EV Formula Correctness
# Validates: Requirements 1.4
# =============================================================================

@settings(max_examples=100)
@given(
    p=probability,
    R=reward_risk_ratio,
    C=cost_ratio,
)
def test_property_1_ev_formula_correctness(
    p: float,
    R: float,
    C: float,
):
    """
    Property 1: EV Formula Correctness
    
    *For any* valid inputs (p ∈ [0,1], R > 0, C ≥ 0), the computed EV SHALL equal
    `p × R - (1 - p) × 1 - C` within floating-point tolerance.
    
    **Validates: Requirements 1.4**
    """
    # Calculate EV using the function under test
    ev = calculate_ev(p, R, C)
    
    # Expected value using the formula: EV = p × R - (1 - p) × 1 - C
    expected = p * R - (1 - p) * 1 - C
    
    # Property: EV equals expected formula within floating-point tolerance
    assert abs(ev - expected) < 1e-9, \
        f"EV={ev} should equal expected={expected} for p={p}, R={R}, C={C}"


@settings(max_examples=100)
@given(
    R=reward_risk_ratio,
    C=cost_ratio,
)
def test_property_1_ev_at_p_zero(
    R: float,
    C: float,
):
    """
    Property 1 (p=0): When p=0, EV = -1 - C (always lose)
    
    *For any* R > 0 and C ≥ 0, when p=0, EV SHALL equal -1 - C.
    
    **Validates: Requirements 1.4**
    """
    p = 0.0
    
    # Calculate EV
    ev = calculate_ev(p, R, C)
    
    # Expected: EV = 0 × R - (1 - 0) × 1 - C = -1 - C
    expected = -1 - C
    
    # Property: EV equals -1 - C when p=0
    assert abs(ev - expected) < 1e-9, \
        f"EV={ev} should equal -1-C={expected} when p=0"


@settings(max_examples=100)
@given(
    R=reward_risk_ratio,
    C=cost_ratio,
)
def test_property_1_ev_at_p_one(
    R: float,
    C: float,
):
    """
    Property 1 (p=1): When p=1, EV = R - C (always win)
    
    *For any* R > 0 and C ≥ 0, when p=1, EV SHALL equal R - C.
    
    **Validates: Requirements 1.4**
    """
    p = 1.0
    
    # Calculate EV
    ev = calculate_ev(p, R, C)
    
    # Expected: EV = 1 × R - (1 - 1) × 1 - C = R - C
    expected = R - C
    
    # Property: EV equals R - C when p=1
    assert abs(ev - expected) < 1e-9, \
        f"EV={ev} should equal R-C={expected} when p=1"


@settings(max_examples=100)
@given(
    p=probability,
    R=reward_risk_ratio,
)
def test_property_1_ev_at_c_zero(
    p: float,
    R: float,
):
    """
    Property 1 (C=0): When C=0, EV = p × R - (1 - p) (no costs)
    
    *For any* p ∈ [0,1] and R > 0, when C=0, EV SHALL equal p × R - (1 - p).
    
    **Validates: Requirements 1.4**
    """
    C = 0.0
    
    # Calculate EV
    ev = calculate_ev(p, R, C)
    
    # Expected: EV = p × R - (1 - p) × 1 - 0 = p × R - (1 - p)
    expected = p * R - (1 - p)
    
    # Property: EV equals p × R - (1 - p) when C=0
    assert abs(ev - expected) < 1e-9, \
        f"EV={ev} should equal p*R-(1-p)={expected} when C=0"


@settings(max_examples=100)
@given(
    p=probability,
    C=cost_ratio,
)
def test_property_1_ev_at_r_one(
    p: float,
    C: float,
):
    """
    Property 1 (R=1): When R=1, EV = p - (1 - p) - C = 2p - 1 - C
    
    *For any* p ∈ [0,1] and C ≥ 0, when R=1, EV SHALL equal 2p - 1 - C.
    
    **Validates: Requirements 1.4**
    """
    R = 1.0
    
    # Calculate EV
    ev = calculate_ev(p, R, C)
    
    # Expected: EV = p × 1 - (1 - p) × 1 - C = p - 1 + p - C = 2p - 1 - C
    expected = 2 * p - 1 - C
    
    # Property: EV equals 2p - 1 - C when R=1
    assert abs(ev - expected) < 1e-9, \
        f"EV={ev} should equal 2p-1-C={expected} when R=1"


@settings(max_examples=100)
@given(
    p=probability,
    R=reward_risk_ratio,
    C=cost_ratio,
)
def test_property_1_ev_increases_with_p(
    p: float,
    R: float,
    C: float,
):
    """
    Property 1 (Monotonicity in p): EV increases as p increases
    
    *For any* fixed R > 0 and C ≥ 0, EV SHALL increase as p increases.
    
    **Validates: Requirements 1.4**
    """
    # Skip edge case where p is already at max
    assume(p < 0.99)
    
    # Calculate EV at p and p + delta
    delta = 0.01
    ev_low = calculate_ev(p, R, C)
    ev_high = calculate_ev(p + delta, R, C)
    
    # Property: EV increases with p
    assert ev_high > ev_low, \
        f"EV should increase with p: EV({p})={ev_low}, EV({p+delta})={ev_high}"


@settings(max_examples=100)
@given(
    p=probability,
    R=reward_risk_ratio,
    C=cost_ratio,
)
def test_property_1_ev_increases_with_r(
    p: float,
    R: float,
    C: float,
):
    """
    Property 1 (Monotonicity in R): EV increases as R increases (when p > 0)
    
    *For any* p > 0 and fixed C ≥ 0, EV SHALL increase as R increases.
    
    **Validates: Requirements 1.4**
    """
    # Skip edge case where p is 0 (R doesn't affect EV when p=0)
    assume(p > 0.01)
    # Skip edge case where R is already at max
    assume(R < 9.9)
    
    # Calculate EV at R and R + delta
    delta = 0.1
    ev_low = calculate_ev(p, R, C)
    ev_high = calculate_ev(p, R + delta, C)
    
    # Property: EV increases with R (when p > 0)
    assert ev_high > ev_low, \
        f"EV should increase with R: EV(R={R})={ev_low}, EV(R={R+delta})={ev_high}"


@settings(max_examples=100)
@given(
    p=probability,
    R=reward_risk_ratio,
    C=cost_ratio,
)
def test_property_1_ev_decreases_with_c(
    p: float,
    R: float,
    C: float,
):
    """
    Property 1 (Monotonicity in C): EV decreases as C increases
    
    *For any* fixed p ∈ [0,1] and R > 0, EV SHALL decrease as C increases.
    
    **Validates: Requirements 1.4**
    """
    # Skip edge case where C is already at max
    assume(C < 0.98)
    
    # Calculate EV at C and C + delta
    delta = 0.01
    ev_high = calculate_ev(p, R, C)
    ev_low = calculate_ev(p, R, C + delta)
    
    # Property: EV decreases with C
    assert ev_low < ev_high, \
        f"EV should decrease with C: EV(C={C})={ev_high}, EV(C={C+delta})={ev_low}"


@settings(max_examples=100)
@given(
    R=reward_risk_ratio,
    C=cost_ratio,
)
def test_property_1_breakeven_probability(
    R: float,
    C: float,
):
    """
    Property 1 (Breakeven): At p = (1 + C) / (R + 1), EV = 0
    
    *For any* R > 0 and C ≥ 0, when p = (1 + C) / (R + 1), EV SHALL equal 0.
    
    **Validates: Requirements 1.4**
    """
    # Calculate breakeven probability
    p_breakeven = (1 + C) / (R + 1)
    
    # Skip if breakeven probability is outside [0, 1]
    assume(0 <= p_breakeven <= 1)
    
    # Calculate EV at breakeven
    ev = calculate_ev(p_breakeven, R, C)
    
    # Property: EV equals 0 at breakeven probability
    assert abs(ev) < 1e-9, \
        f"EV={ev} should equal 0 at breakeven p={(1+C)/(R+1)}={p_breakeven}"
