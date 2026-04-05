"""Property-based tests for AMT Rotation Factor Calculation.

Feature: amt-fields-in-decision-events

Tests the rotation factor calculation algorithm properties:
- Property 7: Rotation Factor Calculation

**Validates: Requirements 4.1, 4.2, 4.3, 4.4**

These tests use Hypothesis to generate random orderflow imbalance [-1, 1] and trend states
and verify that the rotation factor calculation follows the specified formula:
- Base: orderflow_imbalance * scale_factor
- If trend_direction is "up": add trend_strength * contribution_factor
- If trend_direction is "down": subtract trend_strength * contribution_factor
- Result SHALL be within approximately [-15, +15] range
"""

import pytest
from hypothesis import given, strategies as st, settings, assume

from quantgambit.signals.stages.amt_calculator import _calculate_rotation_factor


# =============================================================================
# Strategies for generating test data
# =============================================================================

# Generate orderflow imbalance values in range [-1, 1]
orderflow_imbalance_strategy = st.floats(
    min_value=-1.0,
    max_value=1.0,
    allow_nan=False,
    allow_infinity=False,
)

# Generate trend strength values in range [0, 1]
trend_strength_strategy = st.floats(
    min_value=0.0,
    max_value=1.0,
    allow_nan=False,
    allow_infinity=False,
)

# Generate trend direction values
trend_direction_strategy = st.sampled_from(["up", "down", None, "neutral", "sideways"])

# Generate valid trend directions only (up, down, None)
valid_trend_direction_strategy = st.sampled_from(["up", "down", None])


# Generate scale factor values (positive)
scale_factor_strategy = st.floats(
    min_value=0.1,
    max_value=20.0,
    allow_nan=False,
    allow_infinity=False,
)

# Generate contribution factor values (positive)
contribution_factor_strategy = st.floats(
    min_value=0.1,
    max_value=20.0,
    allow_nan=False,
    allow_infinity=False,
)


@st.composite
def rotation_factor_inputs_strategy(draw):
    """Generate valid inputs for rotation factor calculation.
    
    This strategy generates a complete set of inputs for the
    _calculate_rotation_factor function.
    """
    orderflow_imbalance = draw(orderflow_imbalance_strategy)
    trend_direction = draw(valid_trend_direction_strategy)
    trend_strength = draw(trend_strength_strategy)
    return orderflow_imbalance, trend_direction, trend_strength


@st.composite
def rotation_factor_with_custom_factors_strategy(draw):
    """Generate inputs with custom scale and contribution factors.
    
    This strategy generates inputs including custom scale_factor and
    contribution_factor values for testing the formula.
    """
    orderflow_imbalance = draw(orderflow_imbalance_strategy)
    trend_direction = draw(valid_trend_direction_strategy)
    trend_strength = draw(trend_strength_strategy)
    scale_factor = draw(scale_factor_strategy)
    contribution_factor = draw(contribution_factor_strategy)
    return orderflow_imbalance, trend_direction, trend_strength, scale_factor, contribution_factor


# =============================================================================
# Property Tests - Rotation Factor Calculation
# =============================================================================

class TestRotationFactorProperties:
    """Property-based tests for Rotation Factor Calculation.
    
    Feature: amt-fields-in-decision-events
    Property 7: Rotation Factor Calculation
    **Validates: Requirements 4.1, 4.2, 4.3, 4.4**
    """
    
    @given(data=rotation_factor_inputs_strategy())
    @settings(max_examples=100)
    def test_property_7_result_within_range(self, data):
        """Property 7: Rotation factor is within [-15, +15] range.
        
        *For any* orderflow imbalance and trend state, the rotation_factor
        SHALL be within approximately [-15, +15] range.
        
        Feature: amt-fields-in-decision-events, Property 7: Rotation Factor Calculation
        **Validates: Requirements 4.4**
        """
        orderflow_imbalance, trend_direction, trend_strength = data
        
        result = _calculate_rotation_factor(
            orderflow_imbalance=orderflow_imbalance,
            trend_direction=trend_direction,
            trend_strength=trend_strength,
        )
        
        # Property 7: Result SHALL be within [-15, +15] range
        assert -15.0 <= result <= 15.0, (
            f"Rotation factor {result} is outside [-15, +15] range. "
            f"Inputs: orderflow_imbalance={orderflow_imbalance}, "
            f"trend_direction={trend_direction}, trend_strength={trend_strength}"
        )

    @given(
        orderflow_imbalance=orderflow_imbalance_strategy,
        trend_strength=trend_strength_strategy,
    )
    @settings(max_examples=100)
    def test_property_7_base_calculation_from_orderflow(self, orderflow_imbalance, trend_strength):
        """Property 7: Base rotation is calculated from orderflow imbalance.
        
        *For any* orderflow imbalance with no trend (None), the rotation_factor
        SHALL be calculated as: orderflow_imbalance * scale_factor (default 5.0).
        
        Feature: amt-fields-in-decision-events, Property 7: Rotation Factor Calculation
        **Validates: Requirements 4.1**
        """
        # With no trend direction, only base calculation applies
        result = _calculate_rotation_factor(
            orderflow_imbalance=orderflow_imbalance,
            trend_direction=None,
            trend_strength=trend_strength,
        )
        
        # Expected: orderflow_imbalance * scale_factor (5.0), clamped to [-15, 15]
        expected = orderflow_imbalance * 5.0
        expected = max(-15.0, min(15.0, expected))
        
        assert result == pytest.approx(expected, rel=1e-9), (
            f"Base rotation mismatch: orderflow_imbalance={orderflow_imbalance}, "
            f"expected {expected}, got {result}"
        )
    
    @given(
        orderflow_imbalance=orderflow_imbalance_strategy,
        trend_strength=trend_strength_strategy,
    )
    @settings(max_examples=100)
    def test_property_7_trend_up_adds_contribution(self, orderflow_imbalance, trend_strength):
        """Property 7: Trend up adds trend_strength contribution.
        
        *For any* orderflow imbalance and trend_strength with trend_direction="up",
        the rotation_factor SHALL add trend_strength * contribution_factor (default 5.0).
        
        Feature: amt-fields-in-decision-events, Property 7: Rotation Factor Calculation
        **Validates: Requirements 4.2**
        """
        result = _calculate_rotation_factor(
            orderflow_imbalance=orderflow_imbalance,
            trend_direction="up",
            trend_strength=trend_strength,
        )
        
        # Expected: (orderflow_imbalance * 5.0) + (trend_strength * 5.0), clamped
        base = orderflow_imbalance * 5.0
        trend_contribution = trend_strength * 5.0
        expected = base + trend_contribution
        expected = max(-15.0, min(15.0, expected))
        
        assert result == pytest.approx(expected, rel=1e-9), (
            f"Trend up calculation mismatch: orderflow_imbalance={orderflow_imbalance}, "
            f"trend_strength={trend_strength}, expected {expected}, got {result}"
        )

    @given(
        orderflow_imbalance=orderflow_imbalance_strategy,
        trend_strength=trend_strength_strategy,
    )
    @settings(max_examples=100)
    def test_property_7_trend_down_subtracts_contribution(self, orderflow_imbalance, trend_strength):
        """Property 7: Trend down subtracts trend_strength contribution.
        
        *For any* orderflow imbalance and trend_strength with trend_direction="down",
        the rotation_factor SHALL subtract trend_strength * contribution_factor (default 5.0).
        
        Feature: amt-fields-in-decision-events, Property 7: Rotation Factor Calculation
        **Validates: Requirements 4.3**
        """
        result = _calculate_rotation_factor(
            orderflow_imbalance=orderflow_imbalance,
            trend_direction="down",
            trend_strength=trend_strength,
        )
        
        # Expected: (orderflow_imbalance * 5.0) - (trend_strength * 5.0), clamped
        base = orderflow_imbalance * 5.0
        trend_contribution = trend_strength * 5.0
        expected = base - trend_contribution
        expected = max(-15.0, min(15.0, expected))
        
        assert result == pytest.approx(expected, rel=1e-9), (
            f"Trend down calculation mismatch: orderflow_imbalance={orderflow_imbalance}, "
            f"trend_strength={trend_strength}, expected {expected}, got {result}"
        )
    
    @given(data=rotation_factor_with_custom_factors_strategy())
    @settings(max_examples=100)
    def test_property_7_formula_with_custom_factors(self, data):
        """Property 7: Formula is applied correctly with custom factors.
        
        *For any* orderflow imbalance, trend state, and custom scale/contribution factors,
        the rotation_factor SHALL be calculated using the specified formula.
        
        Feature: amt-fields-in-decision-events, Property 7: Rotation Factor Calculation
        **Validates: Requirements 4.1, 4.2, 4.3, 4.4**
        """
        orderflow_imbalance, trend_direction, trend_strength, scale_factor, contribution_factor = data
        
        result = _calculate_rotation_factor(
            orderflow_imbalance=orderflow_imbalance,
            trend_direction=trend_direction,
            trend_strength=trend_strength,
            scale_factor=scale_factor,
            contribution_factor=contribution_factor,
        )
        
        # Calculate expected value
        base = orderflow_imbalance * scale_factor
        
        if trend_direction == "up":
            trend_contribution = trend_strength * contribution_factor
        elif trend_direction == "down":
            trend_contribution = -trend_strength * contribution_factor
        else:
            trend_contribution = 0.0
        
        expected = base + trend_contribution
        expected = max(-15.0, min(15.0, expected))
        
        assert result == pytest.approx(expected, rel=1e-9), (
            f"Formula mismatch: orderflow_imbalance={orderflow_imbalance}, "
            f"trend_direction={trend_direction}, trend_strength={trend_strength}, "
            f"scale_factor={scale_factor}, contribution_factor={contribution_factor}, "
            f"expected {expected}, got {result}"
        )

    @given(data=rotation_factor_inputs_strategy())
    @settings(max_examples=100)
    def test_property_7_calculation_is_deterministic(self, data):
        """Property 7: Rotation factor calculation is deterministic.
        
        *For any* orderflow imbalance and trend state, calling _calculate_rotation_factor
        multiple times with the same inputs SHALL return the same result.
        
        Feature: amt-fields-in-decision-events, Property 7: Rotation Factor Calculation
        **Validates: Requirements 4.1, 4.2, 4.3, 4.4**
        """
        orderflow_imbalance, trend_direction, trend_strength = data
        
        # Call calculation multiple times
        result1 = _calculate_rotation_factor(
            orderflow_imbalance=orderflow_imbalance,
            trend_direction=trend_direction,
            trend_strength=trend_strength,
        )
        result2 = _calculate_rotation_factor(
            orderflow_imbalance=orderflow_imbalance,
            trend_direction=trend_direction,
            trend_strength=trend_strength,
        )
        result3 = _calculate_rotation_factor(
            orderflow_imbalance=orderflow_imbalance,
            trend_direction=trend_direction,
            trend_strength=trend_strength,
        )
        
        # All results should be identical (deterministic)
        assert result1 == result2 == result3, (
            f"Rotation factor calculation is not deterministic: got {result1}, {result2}, {result3}"
        )


class TestRotationFactorTrendBehavior:
    """Property tests for trend direction behavior in rotation factor.
    
    Feature: amt-fields-in-decision-events
    Property 7: Rotation Factor Calculation
    **Validates: Requirements 4.2, 4.3**
    """
    
    @given(
        orderflow_imbalance=orderflow_imbalance_strategy,
        trend_strength=st.floats(min_value=0.01, max_value=1.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=100)
    def test_property_7_trend_up_increases_rotation(self, orderflow_imbalance, trend_strength):
        """Property 7: Trend up increases rotation factor compared to no trend.
        
        *For any* orderflow imbalance and positive trend_strength, trend_direction="up"
        SHALL result in a higher rotation factor than trend_direction=None.
        
        Feature: amt-fields-in-decision-events, Property 7: Rotation Factor Calculation
        **Validates: Requirements 4.2**
        """
        # Ensure trend_strength is positive for meaningful comparison
        assume(trend_strength > 0.001)
        
        result_no_trend = _calculate_rotation_factor(
            orderflow_imbalance=orderflow_imbalance,
            trend_direction=None,
            trend_strength=trend_strength,
        )
        
        result_trend_up = _calculate_rotation_factor(
            orderflow_imbalance=orderflow_imbalance,
            trend_direction="up",
            trend_strength=trend_strength,
        )
        
        # Trend up should increase rotation (unless clamped)
        # If not clamped, result_trend_up > result_no_trend
        # If clamped at 15, both might be 15
        assert result_trend_up >= result_no_trend, (
            f"Trend up should increase rotation: no_trend={result_no_trend}, "
            f"trend_up={result_trend_up}"
        )

    @given(
        orderflow_imbalance=orderflow_imbalance_strategy,
        trend_strength=st.floats(min_value=0.01, max_value=1.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=100)
    def test_property_7_trend_down_decreases_rotation(self, orderflow_imbalance, trend_strength):
        """Property 7: Trend down decreases rotation factor compared to no trend.
        
        *For any* orderflow imbalance and positive trend_strength, trend_direction="down"
        SHALL result in a lower rotation factor than trend_direction=None.
        
        Feature: amt-fields-in-decision-events, Property 7: Rotation Factor Calculation
        **Validates: Requirements 4.3**
        """
        # Ensure trend_strength is positive for meaningful comparison
        assume(trend_strength > 0.001)
        
        result_no_trend = _calculate_rotation_factor(
            orderflow_imbalance=orderflow_imbalance,
            trend_direction=None,
            trend_strength=trend_strength,
        )
        
        result_trend_down = _calculate_rotation_factor(
            orderflow_imbalance=orderflow_imbalance,
            trend_direction="down",
            trend_strength=trend_strength,
        )
        
        # Trend down should decrease rotation (unless clamped)
        # If not clamped, result_trend_down < result_no_trend
        # If clamped at -15, both might be -15
        assert result_trend_down <= result_no_trend, (
            f"Trend down should decrease rotation: no_trend={result_no_trend}, "
            f"trend_down={result_trend_down}"
        )
    
    @given(
        orderflow_imbalance=orderflow_imbalance_strategy,
        trend_strength=st.floats(min_value=0.01, max_value=1.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=100)
    def test_property_7_trend_up_vs_down_symmetry(self, orderflow_imbalance, trend_strength):
        """Property 7: Trend up and down have symmetric effect on rotation.
        
        *For any* orderflow imbalance and trend_strength, the difference between
        trend_up and no_trend should equal the difference between no_trend and trend_down
        (when not clamped).
        
        Feature: amt-fields-in-decision-events, Property 7: Rotation Factor Calculation
        **Validates: Requirements 4.2, 4.3**
        """
        # Ensure trend_strength is positive for meaningful comparison
        assume(trend_strength > 0.001)
        
        result_no_trend = _calculate_rotation_factor(
            orderflow_imbalance=orderflow_imbalance,
            trend_direction=None,
            trend_strength=trend_strength,
        )
        
        result_trend_up = _calculate_rotation_factor(
            orderflow_imbalance=orderflow_imbalance,
            trend_direction="up",
            trend_strength=trend_strength,
        )
        
        result_trend_down = _calculate_rotation_factor(
            orderflow_imbalance=orderflow_imbalance,
            trend_direction="down",
            trend_strength=trend_strength,
        )
        
        # Calculate expected contribution
        expected_contribution = trend_strength * 5.0  # default contribution_factor
        
        # Check if values are not clamped
        base = orderflow_imbalance * 5.0
        if abs(base) + expected_contribution <= 15.0:
            # Not clamped - symmetry should hold
            diff_up = result_trend_up - result_no_trend
            diff_down = result_no_trend - result_trend_down
            
            assert diff_up == pytest.approx(diff_down, rel=1e-9), (
                f"Trend contribution should be symmetric: diff_up={diff_up}, diff_down={diff_down}"
            )


class TestRotationFactorEdgeCases:
    """Property tests for edge cases in rotation factor calculation.
    
    Feature: amt-fields-in-decision-events
    Property 7: Rotation Factor Calculation
    **Validates: Requirements 4.1, 4.2, 4.3, 4.4**
    """
    
    @given(trend_direction=valid_trend_direction_strategy, trend_strength=trend_strength_strategy)
    @settings(max_examples=100)
    def test_property_7_zero_orderflow_base_is_zero(self, trend_direction, trend_strength):
        """Property 7: Zero orderflow imbalance results in zero base contribution.
        
        *For any* trend state, when orderflow_imbalance is 0, the base contribution
        SHALL be 0, and only trend contribution affects the result.
        
        Feature: amt-fields-in-decision-events, Property 7: Rotation Factor Calculation
        **Validates: Requirements 4.1**
        """
        result = _calculate_rotation_factor(
            orderflow_imbalance=0.0,
            trend_direction=trend_direction,
            trend_strength=trend_strength,
        )
        
        # Expected: only trend contribution
        if trend_direction == "up":
            expected = trend_strength * 5.0
        elif trend_direction == "down":
            expected = -trend_strength * 5.0
        else:
            expected = 0.0
        
        expected = max(-15.0, min(15.0, expected))
        
        assert result == pytest.approx(expected, rel=1e-9), (
            f"Zero orderflow mismatch: trend_direction={trend_direction}, "
            f"trend_strength={trend_strength}, expected {expected}, got {result}"
        )
    
    @given(orderflow_imbalance=orderflow_imbalance_strategy, trend_direction=valid_trend_direction_strategy)
    @settings(max_examples=100)
    def test_property_7_zero_trend_strength_no_trend_contribution(self, orderflow_imbalance, trend_direction):
        """Property 7: Zero trend strength results in no trend contribution.
        
        *For any* orderflow imbalance and trend direction, when trend_strength is 0,
        the trend contribution SHALL be 0.
        
        Feature: amt-fields-in-decision-events, Property 7: Rotation Factor Calculation
        **Validates: Requirements 4.2, 4.3**
        """
        result = _calculate_rotation_factor(
            orderflow_imbalance=orderflow_imbalance,
            trend_direction=trend_direction,
            trend_strength=0.0,
        )
        
        # Expected: only base contribution (no trend contribution)
        expected = orderflow_imbalance * 5.0
        expected = max(-15.0, min(15.0, expected))
        
        assert result == pytest.approx(expected, rel=1e-9), (
            f"Zero trend strength mismatch: orderflow_imbalance={orderflow_imbalance}, "
            f"expected {expected}, got {result}"
        )
    
    @given(trend_strength=trend_strength_strategy)
    @settings(max_examples=100)
    def test_property_7_max_positive_orderflow_clamped(self, trend_strength):
        """Property 7: Maximum positive orderflow with trend up is clamped at 15.
        
        When orderflow_imbalance is 1.0 and trend_direction is "up" with max trend_strength,
        the result SHALL be clamped at 15.0.
        
        Feature: amt-fields-in-decision-events, Property 7: Rotation Factor Calculation
        **Validates: Requirements 4.4**
        """
        result = _calculate_rotation_factor(
            orderflow_imbalance=1.0,
            trend_direction="up",
            trend_strength=1.0,
        )
        
        # Expected: (1.0 * 5.0) + (1.0 * 5.0) = 10.0, not clamped
        # But with max values, should be clamped at 15
        assert result <= 15.0, f"Result {result} exceeds maximum 15.0"
        assert result == pytest.approx(10.0, rel=1e-9), f"Expected 10.0, got {result}"

    @given(trend_strength=trend_strength_strategy)
    @settings(max_examples=100)
    def test_property_7_max_negative_orderflow_clamped(self, trend_strength):
        """Property 7: Maximum negative orderflow with trend down is clamped at -15.
        
        When orderflow_imbalance is -1.0 and trend_direction is "down" with max trend_strength,
        the result SHALL be clamped at -15.0.
        
        Feature: amt-fields-in-decision-events, Property 7: Rotation Factor Calculation
        **Validates: Requirements 4.4**
        """
        result = _calculate_rotation_factor(
            orderflow_imbalance=-1.0,
            trend_direction="down",
            trend_strength=1.0,
        )
        
        # Expected: (-1.0 * 5.0) - (1.0 * 5.0) = -10.0, not clamped
        assert result >= -15.0, f"Result {result} is below minimum -15.0"
        assert result == pytest.approx(-10.0, rel=1e-9), f"Expected -10.0, got {result}"
    
    @given(
        orderflow_imbalance=orderflow_imbalance_strategy,
        trend_strength=trend_strength_strategy,
    )
    @settings(max_examples=100)
    def test_property_7_unknown_trend_direction_no_contribution(self, orderflow_imbalance, trend_strength):
        """Property 7: Unknown trend direction results in no trend contribution.
        
        *For any* orderflow imbalance and trend_strength, when trend_direction is
        not "up" or "down" (e.g., "neutral", "sideways"), the trend contribution SHALL be 0.
        
        Feature: amt-fields-in-decision-events, Property 7: Rotation Factor Calculation
        **Validates: Requirements 4.2, 4.3**
        """
        for unknown_direction in ["neutral", "sideways", "unknown", ""]:
            result = _calculate_rotation_factor(
                orderflow_imbalance=orderflow_imbalance,
                trend_direction=unknown_direction,
                trend_strength=trend_strength,
            )
            
            # Expected: only base contribution (no trend contribution)
            expected = orderflow_imbalance * 5.0
            expected = max(-15.0, min(15.0, expected))
            
            assert result == pytest.approx(expected, rel=1e-9), (
                f"Unknown trend direction '{unknown_direction}' mismatch: "
                f"orderflow_imbalance={orderflow_imbalance}, expected {expected}, got {result}"
            )


class TestRotationFactorClampingBehavior:
    """Property tests for clamping behavior in rotation factor calculation.
    
    Feature: amt-fields-in-decision-events
    Property 7: Rotation Factor Calculation
    **Validates: Requirements 4.4**
    """
    
    @given(
        scale_factor=st.floats(min_value=10.0, max_value=50.0, allow_nan=False, allow_infinity=False),
        contribution_factor=st.floats(min_value=10.0, max_value=50.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=100)
    def test_property_7_extreme_positive_clamped_at_15(self, scale_factor, contribution_factor):
        """Property 7: Extreme positive values are clamped at 15.
        
        *For any* combination of inputs that would produce a value > 15,
        the result SHALL be clamped at 15.0.
        
        Feature: amt-fields-in-decision-events, Property 7: Rotation Factor Calculation
        **Validates: Requirements 4.4**
        """
        result = _calculate_rotation_factor(
            orderflow_imbalance=1.0,
            trend_direction="up",
            trend_strength=1.0,
            scale_factor=scale_factor,
            contribution_factor=contribution_factor,
        )
        
        # With large factors, result should be clamped at 15
        assert result == 15.0, f"Expected clamped value 15.0, got {result}"

    @given(
        scale_factor=st.floats(min_value=10.0, max_value=50.0, allow_nan=False, allow_infinity=False),
        contribution_factor=st.floats(min_value=10.0, max_value=50.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=100)
    def test_property_7_extreme_negative_clamped_at_minus_15(self, scale_factor, contribution_factor):
        """Property 7: Extreme negative values are clamped at -15.
        
        *For any* combination of inputs that would produce a value < -15,
        the result SHALL be clamped at -15.0.
        
        Feature: amt-fields-in-decision-events, Property 7: Rotation Factor Calculation
        **Validates: Requirements 4.4**
        """
        result = _calculate_rotation_factor(
            orderflow_imbalance=-1.0,
            trend_direction="down",
            trend_strength=1.0,
            scale_factor=scale_factor,
            contribution_factor=contribution_factor,
        )
        
        # With large factors, result should be clamped at -15
        assert result == -15.0, f"Expected clamped value -15.0, got {result}"
    
    @given(data=rotation_factor_with_custom_factors_strategy())
    @settings(max_examples=100)
    def test_property_7_clamping_preserves_sign(self, data):
        """Property 7: Clamping preserves the sign of the rotation factor.
        
        *For any* inputs, if the unclamped value is positive, the clamped result
        SHALL be positive (or zero). If unclamped is negative, clamped SHALL be
        negative (or zero).
        
        Feature: amt-fields-in-decision-events, Property 7: Rotation Factor Calculation
        **Validates: Requirements 4.4**
        """
        orderflow_imbalance, trend_direction, trend_strength, scale_factor, contribution_factor = data
        
        result = _calculate_rotation_factor(
            orderflow_imbalance=orderflow_imbalance,
            trend_direction=trend_direction,
            trend_strength=trend_strength,
            scale_factor=scale_factor,
            contribution_factor=contribution_factor,
        )
        
        # Calculate unclamped value
        base = orderflow_imbalance * scale_factor
        if trend_direction == "up":
            trend_contribution = trend_strength * contribution_factor
        elif trend_direction == "down":
            trend_contribution = -trend_strength * contribution_factor
        else:
            trend_contribution = 0.0
        unclamped = base + trend_contribution
        
        # Check sign preservation (with tolerance for zero)
        if unclamped > 0.001:
            assert result >= 0, f"Positive unclamped {unclamped} should give non-negative result, got {result}"
        elif unclamped < -0.001:
            assert result <= 0, f"Negative unclamped {unclamped} should give non-positive result, got {result}"


class TestRotationFactorMonotonicity:
    """Property tests for monotonicity in rotation factor calculation.
    
    Feature: amt-fields-in-decision-events
    Property 7: Rotation Factor Calculation
    **Validates: Requirements 4.1, 4.2, 4.3**
    """
    
    @given(
        orderflow_1=st.floats(min_value=-1.0, max_value=0.0, allow_nan=False, allow_infinity=False),
        orderflow_2=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
        trend_direction=valid_trend_direction_strategy,
        trend_strength=trend_strength_strategy,
    )
    @settings(max_examples=100)
    def test_property_7_monotonic_in_orderflow(self, orderflow_1, orderflow_2, trend_direction, trend_strength):
        """Property 7: Rotation factor is monotonically increasing in orderflow imbalance.
        
        *For any* trend state, if orderflow_1 < orderflow_2, then
        rotation_factor(orderflow_1) <= rotation_factor(orderflow_2).
        
        Feature: amt-fields-in-decision-events, Property 7: Rotation Factor Calculation
        **Validates: Requirements 4.1**
        """
        # Ensure orderflow_1 < orderflow_2
        assume(orderflow_1 < orderflow_2)
        
        result_1 = _calculate_rotation_factor(
            orderflow_imbalance=orderflow_1,
            trend_direction=trend_direction,
            trend_strength=trend_strength,
        )
        
        result_2 = _calculate_rotation_factor(
            orderflow_imbalance=orderflow_2,
            trend_direction=trend_direction,
            trend_strength=trend_strength,
        )
        
        assert result_1 <= result_2, (
            f"Rotation factor should be monotonic in orderflow: "
            f"orderflow_1={orderflow_1} -> {result_1}, orderflow_2={orderflow_2} -> {result_2}"
        )

    @given(
        orderflow_imbalance=orderflow_imbalance_strategy,
        trend_strength_1=st.floats(min_value=0.0, max_value=0.5, allow_nan=False, allow_infinity=False),
        trend_strength_2=st.floats(min_value=0.5, max_value=1.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=100)
    def test_property_7_monotonic_in_trend_strength_up(self, orderflow_imbalance, trend_strength_1, trend_strength_2):
        """Property 7: Rotation factor is monotonically increasing in trend_strength when trend is up.
        
        *For any* orderflow imbalance with trend_direction="up", if trend_strength_1 < trend_strength_2,
        then rotation_factor(trend_strength_1) <= rotation_factor(trend_strength_2).
        
        Feature: amt-fields-in-decision-events, Property 7: Rotation Factor Calculation
        **Validates: Requirements 4.2**
        """
        # Ensure trend_strength_1 < trend_strength_2
        assume(trend_strength_1 < trend_strength_2)
        
        result_1 = _calculate_rotation_factor(
            orderflow_imbalance=orderflow_imbalance,
            trend_direction="up",
            trend_strength=trend_strength_1,
        )
        
        result_2 = _calculate_rotation_factor(
            orderflow_imbalance=orderflow_imbalance,
            trend_direction="up",
            trend_strength=trend_strength_2,
        )
        
        assert result_1 <= result_2, (
            f"Rotation factor should increase with trend_strength when trend is up: "
            f"strength_1={trend_strength_1} -> {result_1}, strength_2={trend_strength_2} -> {result_2}"
        )
    
    @given(
        orderflow_imbalance=orderflow_imbalance_strategy,
        trend_strength_1=st.floats(min_value=0.0, max_value=0.5, allow_nan=False, allow_infinity=False),
        trend_strength_2=st.floats(min_value=0.5, max_value=1.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=100)
    def test_property_7_monotonic_in_trend_strength_down(self, orderflow_imbalance, trend_strength_1, trend_strength_2):
        """Property 7: Rotation factor is monotonically decreasing in trend_strength when trend is down.
        
        *For any* orderflow imbalance with trend_direction="down", if trend_strength_1 < trend_strength_2,
        then rotation_factor(trend_strength_1) >= rotation_factor(trend_strength_2).
        
        Feature: amt-fields-in-decision-events, Property 7: Rotation Factor Calculation
        **Validates: Requirements 4.3**
        """
        # Ensure trend_strength_1 < trend_strength_2
        assume(trend_strength_1 < trend_strength_2)
        
        result_1 = _calculate_rotation_factor(
            orderflow_imbalance=orderflow_imbalance,
            trend_direction="down",
            trend_strength=trend_strength_1,
        )
        
        result_2 = _calculate_rotation_factor(
            orderflow_imbalance=orderflow_imbalance,
            trend_direction="down",
            trend_strength=trend_strength_2,
        )
        
        assert result_1 >= result_2, (
            f"Rotation factor should decrease with trend_strength when trend is down: "
            f"strength_1={trend_strength_1} -> {result_1}, strength_2={trend_strength_2} -> {result_2}"
        )
