"""
Property-based tests for EV Gate L, G, R calculation.

Feature: ev-based-entry-gate
Tests correctness properties for:
- Property 1: EV Formula Correctness (partial - L, G, R calculation)

**Validates: Requirements 1.1, 1.2**
"""

import pytest
import math
from hypothesis import given, strategies as st, settings, assume

from quantgambit.signals.stages.ev_gate import calculate_L_G_R


# =============================================================================
# Test Strategies (Generators)
# =============================================================================

# Positive prices (must be > 0 for valid calculations)
positive_price = st.floats(min_value=0.01, max_value=1_000_000.0, allow_nan=False, allow_infinity=False)

# Side values
side_value = st.sampled_from(["long", "short", "LONG", "SHORT", "Long", "Short"])


# =============================================================================
# Property 1: L, G, R Calculation Correctness
# Feature: ev-based-entry-gate, Property 1: EV Formula Correctness (partial)
# Validates: Requirements 1.1, 1.2
# =============================================================================

@settings(max_examples=100)
@given(
    entry_price=positive_price,
    stop_distance_pct=st.floats(min_value=0.001, max_value=0.5, allow_nan=False, allow_infinity=False),
    tp_distance_pct=st.floats(min_value=0.001, max_value=0.5, allow_nan=False, allow_infinity=False),
)
def test_property_1_lgr_calculation_long(
    entry_price: float,
    stop_distance_pct: float,
    tp_distance_pct: float,
):
    """
    Property 1 (Long): L, G, R calculation for long positions
    
    *For any* valid long position with entry_price, stop_loss below entry,
    and take_profit above entry:
    - L SHALL equal abs(entry_price - stop_loss) / entry_price * 10000 (in bps)
    - G SHALL equal abs(take_profit - entry_price) / entry_price * 10000 (in bps)
    - R SHALL equal G / L
    
    **Validates: Requirements 1.1, 1.2**
    """
    # Calculate stop_loss and take_profit for long position
    stop_loss = entry_price * (1 - stop_distance_pct)
    take_profit = entry_price * (1 + tp_distance_pct)
    
    # Ensure valid prices
    assume(stop_loss > 0)
    assume(take_profit > entry_price)
    assume(stop_loss < entry_price)
    
    # Calculate L, G, R
    L_bps, G_bps, R = calculate_L_G_R(entry_price, stop_loss, take_profit, "long")
    
    # Expected values
    expected_L = abs(entry_price - stop_loss) / entry_price * 10000
    expected_G = abs(take_profit - entry_price) / entry_price * 10000
    expected_R = expected_G / expected_L if expected_L > 0 else float('nan')
    
    # Property: L calculation is correct
    assert abs(L_bps - expected_L) < 1e-6, \
        f"L_bps={L_bps} should equal expected={expected_L}"
    
    # Property: G calculation is correct
    assert abs(G_bps - expected_G) < 1e-6, \
        f"G_bps={G_bps} should equal expected={expected_G}"
    
    # Property: R calculation is correct
    assert abs(R - expected_R) < 1e-6, \
        f"R={R} should equal expected={expected_R}"
    
    # Property: L and G are positive
    assert L_bps > 0, f"L_bps={L_bps} should be positive"
    assert G_bps > 0, f"G_bps={G_bps} should be positive"
    
    # Property: R is positive
    assert R > 0, f"R={R} should be positive"


@settings(max_examples=100)
@given(
    entry_price=positive_price,
    stop_distance_pct=st.floats(min_value=0.001, max_value=0.5, allow_nan=False, allow_infinity=False),
    tp_distance_pct=st.floats(min_value=0.001, max_value=0.5, allow_nan=False, allow_infinity=False),
)
def test_property_1_lgr_calculation_short(
    entry_price: float,
    stop_distance_pct: float,
    tp_distance_pct: float,
):
    """
    Property 1 (Short): L, G, R calculation for short positions
    
    *For any* valid short position with entry_price, stop_loss above entry,
    and take_profit below entry:
    - L SHALL equal abs(stop_loss - entry_price) / entry_price * 10000 (in bps)
    - G SHALL equal abs(entry_price - take_profit) / entry_price * 10000 (in bps)
    - R SHALL equal G / L
    
    **Validates: Requirements 1.1, 1.2**
    """
    # Calculate stop_loss and take_profit for short position
    stop_loss = entry_price * (1 + stop_distance_pct)
    take_profit = entry_price * (1 - tp_distance_pct)
    
    # Ensure valid prices
    assume(take_profit > 0)
    assume(stop_loss > entry_price)
    assume(take_profit < entry_price)
    
    # Calculate L, G, R
    L_bps, G_bps, R = calculate_L_G_R(entry_price, stop_loss, take_profit, "short")
    
    # Expected values
    expected_L = abs(stop_loss - entry_price) / entry_price * 10000
    expected_G = abs(entry_price - take_profit) / entry_price * 10000
    expected_R = expected_G / expected_L if expected_L > 0 else float('nan')
    
    # Property: L calculation is correct
    assert abs(L_bps - expected_L) < 1e-6, \
        f"L_bps={L_bps} should equal expected={expected_L}"
    
    # Property: G calculation is correct
    assert abs(G_bps - expected_G) < 1e-6, \
        f"G_bps={G_bps} should equal expected={expected_G}"
    
    # Property: R calculation is correct
    assert abs(R - expected_R) < 1e-6, \
        f"R={R} should equal expected={expected_R}"
    
    # Property: L and G are positive
    assert L_bps > 0, f"L_bps={L_bps} should be positive"
    assert G_bps > 0, f"G_bps={G_bps} should be positive"
    
    # Property: R is positive
    assert R > 0, f"R={R} should be positive"


@settings(max_examples=100)
@given(
    entry_price=positive_price,
    stop_distance_pct=st.floats(min_value=0.001, max_value=0.5, allow_nan=False, allow_infinity=False),
    tp_distance_pct=st.floats(min_value=0.001, max_value=0.5, allow_nan=False, allow_infinity=False),
)
def test_property_1_r_equals_g_over_l(
    entry_price: float,
    stop_distance_pct: float,
    tp_distance_pct: float,
):
    """
    Property 1 (R = G/L): R is always equal to G divided by L
    
    *For any* valid position, R SHALL equal G / L within floating-point tolerance.
    
    **Validates: Requirements 1.2**
    """
    # Calculate stop_loss and take_profit for long position
    stop_loss = entry_price * (1 - stop_distance_pct)
    take_profit = entry_price * (1 + tp_distance_pct)
    
    # Ensure valid prices
    assume(stop_loss > 0)
    assume(take_profit > entry_price)
    assume(stop_loss < entry_price)
    
    # Calculate L, G, R
    L_bps, G_bps, R = calculate_L_G_R(entry_price, stop_loss, take_profit, "long")
    
    # Property: R = G / L
    expected_R = G_bps / L_bps
    assert abs(R - expected_R) < 1e-9, \
        f"R={R} should equal G/L={expected_R}"


@settings(max_examples=100)
@given(
    entry_price=positive_price,
    distance_pct=st.floats(min_value=0.001, max_value=0.5, allow_nan=False, allow_infinity=False),
)
def test_property_1_symmetric_rr_gives_r_equals_1(
    entry_price: float,
    distance_pct: float,
):
    """
    Property 1 (Symmetric R=1): When stop and target are equidistant, R = 1
    
    *For any* position where stop_loss and take_profit are equidistant from entry,
    R SHALL equal 1.0.
    
    **Validates: Requirements 1.2**
    """
    # Calculate symmetric stop_loss and take_profit
    stop_loss = entry_price * (1 - distance_pct)
    take_profit = entry_price * (1 + distance_pct)
    
    # Ensure valid prices
    assume(stop_loss > 0)
    
    # Calculate L, G, R
    L_bps, G_bps, R = calculate_L_G_R(entry_price, stop_loss, take_profit, "long")
    
    # Property: R = 1 when distances are equal
    assert abs(R - 1.0) < 1e-9, \
        f"R={R} should equal 1.0 when stop and target are equidistant"
    
    # Property: L = G when distances are equal
    assert abs(L_bps - G_bps) < 1e-6, \
        f"L_bps={L_bps} should equal G_bps={G_bps} when distances are equal"


@settings(max_examples=100)
@given(
    entry_price=positive_price,
    stop_distance_pct=st.floats(min_value=0.001, max_value=0.5, allow_nan=False, allow_infinity=False),
    tp_multiplier=st.floats(min_value=0.1, max_value=10.0, allow_nan=False, allow_infinity=False),
)
def test_property_1_r_proportional_to_tp_sl_ratio(
    entry_price: float,
    stop_distance_pct: float,
    tp_multiplier: float,
):
    """
    Property 1 (R Proportionality): R is proportional to TP/SL distance ratio
    
    *For any* position, R SHALL be proportional to the ratio of take_profit
    distance to stop_loss distance.
    
    **Validates: Requirements 1.2**
    """
    # Calculate stop_loss and take_profit
    stop_loss = entry_price * (1 - stop_distance_pct)
    tp_distance_pct = stop_distance_pct * tp_multiplier
    take_profit = entry_price * (1 + tp_distance_pct)
    
    # Ensure valid prices
    assume(stop_loss > 0)
    assume(take_profit > entry_price)
    
    # Calculate L, G, R
    L_bps, G_bps, R = calculate_L_G_R(entry_price, stop_loss, take_profit, "long")
    
    # Property: R is approximately equal to tp_multiplier
    # (since tp_distance = stop_distance * tp_multiplier)
    assert abs(R - tp_multiplier) < 1e-6, \
        f"R={R} should equal tp_multiplier={tp_multiplier}"


@settings(max_examples=100)
@given(
    entry_price=positive_price,
    stop_distance_pct=st.floats(min_value=0.001, max_value=0.5, allow_nan=False, allow_infinity=False),
    tp_distance_pct=st.floats(min_value=0.001, max_value=0.5, allow_nan=False, allow_infinity=False),
    side=side_value,
)
def test_property_1_l_g_always_positive(
    entry_price: float,
    stop_distance_pct: float,
    tp_distance_pct: float,
    side: str,
):
    """
    Property 1 (Positive L, G): L and G are always positive for valid inputs
    
    *For any* valid position, L and G SHALL be positive (absolute distances).
    
    **Validates: Requirements 1.1**
    """
    # Calculate stop_loss and take_profit based on side
    if side.lower() == "long":
        stop_loss = entry_price * (1 - stop_distance_pct)
        take_profit = entry_price * (1 + tp_distance_pct)
    else:
        stop_loss = entry_price * (1 + stop_distance_pct)
        take_profit = entry_price * (1 - tp_distance_pct)
    
    # Ensure valid prices
    assume(stop_loss > 0)
    assume(take_profit > 0)
    
    # Calculate L, G, R
    L_bps, G_bps, R = calculate_L_G_R(entry_price, stop_loss, take_profit, side)
    
    # Property: L and G are positive
    assert L_bps > 0, f"L_bps={L_bps} should be positive"
    assert G_bps > 0, f"G_bps={G_bps} should be positive"


@settings(max_examples=100)
@given(
    entry_price=positive_price,
)
def test_property_1_zero_entry_price_returns_nan_r(
    entry_price: float,
):
    """
    Property 1 (Edge Case): Zero or negative entry price returns NaN for R
    
    *For any* entry_price <= 0, R SHALL be NaN.
    
    **Validates: Requirements 1.1**
    """
    # Test with zero entry price
    L_bps, G_bps, R = calculate_L_G_R(0.0, 100.0, 200.0, "long")
    
    # Property: R is NaN when entry_price is 0
    assert math.isnan(R), f"R should be NaN when entry_price is 0, got {R}"
    
    # Test with negative entry price
    L_bps, G_bps, R = calculate_L_G_R(-100.0, 100.0, 200.0, "long")
    
    # Property: R is NaN when entry_price is negative
    assert math.isnan(R), f"R should be NaN when entry_price is negative, got {R}"


@settings(max_examples=100)
@given(
    entry_price=positive_price,
    take_profit=positive_price,
)
def test_property_1_zero_l_returns_nan_r(
    entry_price: float,
    take_profit: float,
):
    """
    Property 1 (Edge Case): When L = 0 (stop_loss = entry_price), R is NaN
    
    *For any* position where stop_loss equals entry_price, R SHALL be NaN.
    
    **Validates: Requirements 1.1**
    """
    # Set stop_loss = entry_price (L = 0)
    stop_loss = entry_price
    
    # Calculate L, G, R
    L_bps, G_bps, R = calculate_L_G_R(entry_price, stop_loss, take_profit, "long")
    
    # Property: R is NaN when L = 0
    assert math.isnan(R), f"R should be NaN when L=0 (stop_loss=entry_price), got {R}"
    
    # Property: L should be 0
    assert L_bps == 0.0, f"L_bps should be 0 when stop_loss=entry_price, got {L_bps}"
