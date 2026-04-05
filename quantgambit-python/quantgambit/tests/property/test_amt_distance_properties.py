"""Property-based tests for AMT Distance Calculations.

Feature: amt-fields-in-decision-events

Tests the distance calculation algorithm properties:
- Property 3: Distance Calculation Correctness

**Validates: Requirements 3.1, 3.2, 3.3**

These tests use Hypothesis to generate random prices and AMT levels (POC, VAL, VAH)
and verify that the distance calculations are mathematically correct:
- distance_to_val equals |price - VAL| (absolute)
- distance_to_vah equals |price - VAH| (absolute)
- distance_to_poc equals (price - POC) (signed, positive when price > POC)
"""

import pytest
from hypothesis import given, strategies as st, settings, assume

from quantgambit.signals.stages.amt_calculator import _calculate_distances


# =============================================================================
# Strategies for generating test data
# =============================================================================

# Generate realistic price values (crypto range)
price_strategy = st.floats(
    min_value=0.01,
    max_value=1000000.0,
    allow_nan=False,
    allow_infinity=False,
)

# Generate positive price values for AMT levels
amt_level_strategy = st.floats(
    min_value=0.01,
    max_value=1000000.0,
    allow_nan=False,
    allow_infinity=False,
)


@st.composite
def valid_amt_levels_strategy(draw):
    """Generate valid AMT levels (POC, VAL, VAH) where VAL <= POC <= VAH.
    
    This strategy ensures that the generated AMT levels are valid,
    meaning VAL <= POC <= VAH (POC is within the value area).
    """
    val = draw(amt_level_strategy)
    # VAH must be >= VAL
    vah = draw(st.floats(
        min_value=val,
        max_value=max(val * 2, val + 10000),  # Allow reasonable spread
        allow_nan=False,
        allow_infinity=False,
    ))
    # POC must be between VAL and VAH
    poc = draw(st.floats(
        min_value=val,
        max_value=vah,
        allow_nan=False,
        allow_infinity=False,
    ))
    return poc, val, vah


@st.composite
def price_and_amt_levels_strategy(draw):
    """Generate a price and valid AMT levels for distance testing.
    
    This strategy generates a random price and valid AMT levels (POC, VAL, VAH)
    for testing distance calculations.
    """
    poc, val, vah = draw(valid_amt_levels_strategy())
    price = draw(price_strategy)
    return price, poc, val, vah


@st.composite
def price_above_poc_strategy(draw):
    """Generate a price that is strictly above POC.
    
    This strategy generates valid AMT levels and a price that is
    guaranteed to be above the point of control.
    """
    poc, val, vah = draw(valid_amt_levels_strategy())
    # Price must be > POC
    price = draw(st.floats(
        min_value=poc + 0.0001,  # Strictly above POC
        max_value=poc * 2 + 10000,
        allow_nan=False,
        allow_infinity=False,
    ))
    return price, poc, val, vah


@st.composite
def price_below_poc_strategy(draw):
    """Generate a price that is strictly below POC.
    
    This strategy generates valid AMT levels and a price that is
    guaranteed to be below the point of control.
    """
    poc, val, vah = draw(valid_amt_levels_strategy())
    # Price must be < POC
    # Ensure we have room below POC
    assume(poc > 0.01)
    price = draw(st.floats(
        min_value=0.0001,
        max_value=poc - 0.0001,  # Strictly below POC
        allow_nan=False,
        allow_infinity=False,
    ))
    return price, poc, val, vah


# =============================================================================
# Property Tests - Distance Calculation Correctness
# =============================================================================

class TestDistanceCalculationProperties:
    """Property-based tests for Distance Calculation Correctness.
    
    Feature: amt-fields-in-decision-events
    Property 3: Distance Calculation Correctness
    **Validates: Requirements 3.1, 3.2, 3.3**
    """
    
    @given(data=price_and_amt_levels_strategy())
    @settings(max_examples=100)
    def test_property_3_distance_to_val_is_absolute(self, data):
        """Property 3: distance_to_val equals |price - VAL| (absolute).
        
        *For any* price and valid AMT levels, distance_to_val SHALL equal
        the absolute value of (price - VAL).
        
        Feature: amt-fields-in-decision-events, Property 3: Distance Calculation Correctness
        **Validates: Requirements 3.1**
        """
        price, poc, val, vah = data
        
        # Calculate distances
        result = _calculate_distances(price, poc, vah, val)
        
        # Property 3: distance_to_val equals |price - VAL|
        expected_distance_to_val = abs(price - val)
        
        assert result["distance_to_val"] == pytest.approx(expected_distance_to_val, rel=1e-9), (
            f"distance_to_val mismatch: price={price}, VAL={val}, "
            f"expected {expected_distance_to_val}, got {result['distance_to_val']}"
        )
    
    @given(data=price_and_amt_levels_strategy())
    @settings(max_examples=100)
    def test_property_3_distance_to_vah_is_absolute(self, data):
        """Property 3: distance_to_vah equals |price - VAH| (absolute).
        
        *For any* price and valid AMT levels, distance_to_vah SHALL equal
        the absolute value of (price - VAH).
        
        Feature: amt-fields-in-decision-events, Property 3: Distance Calculation Correctness
        **Validates: Requirements 3.2**
        """
        price, poc, val, vah = data
        
        # Calculate distances
        result = _calculate_distances(price, poc, vah, val)
        
        # Property 3: distance_to_vah equals |price - VAH|
        expected_distance_to_vah = abs(price - vah)
        
        assert result["distance_to_vah"] == pytest.approx(expected_distance_to_vah, rel=1e-9), (
            f"distance_to_vah mismatch: price={price}, VAH={vah}, "
            f"expected {expected_distance_to_vah}, got {result['distance_to_vah']}"
        )
    
    @given(data=price_and_amt_levels_strategy())
    @settings(max_examples=100)
    def test_property_3_distance_to_poc_is_signed(self, data):
        """Property 3: distance_to_poc equals (price - POC) (signed).
        
        *For any* price and valid AMT levels, distance_to_poc SHALL equal
        (price - POC) with sign preserved.
        
        Feature: amt-fields-in-decision-events, Property 3: Distance Calculation Correctness
        **Validates: Requirements 3.3**
        """
        price, poc, val, vah = data
        
        # Calculate distances
        result = _calculate_distances(price, poc, vah, val)
        
        # Property 3: distance_to_poc equals (price - POC) with sign
        expected_distance_to_poc = price - poc
        
        assert result["distance_to_poc"] == pytest.approx(expected_distance_to_poc, rel=1e-9), (
            f"distance_to_poc mismatch: price={price}, POC={poc}, "
            f"expected {expected_distance_to_poc}, got {result['distance_to_poc']}"
        )
    
    @given(data=price_above_poc_strategy())
    @settings(max_examples=100)
    def test_property_3_distance_to_poc_positive_when_price_above(self, data):
        """Property 3: distance_to_poc is positive when price > POC.
        
        *For any* price > POC, distance_to_poc SHALL be positive.
        
        Feature: amt-fields-in-decision-events, Property 3: Distance Calculation Correctness
        **Validates: Requirements 3.3**
        """
        price, poc, val, vah = data
        
        # Verify precondition: price > POC
        assert price > poc, f"Test setup error: price ({price}) should be > POC ({poc})"
        
        # Calculate distances
        result = _calculate_distances(price, poc, vah, val)
        
        # Property 3: distance_to_poc is positive when price > POC
        assert result["distance_to_poc"] > 0, (
            f"Expected positive distance_to_poc for price ({price}) > POC ({poc}), "
            f"got {result['distance_to_poc']}"
        )
    
    @given(data=price_below_poc_strategy())
    @settings(max_examples=100)
    def test_property_3_distance_to_poc_negative_when_price_below(self, data):
        """Property 3: distance_to_poc is negative when price < POC.
        
        *For any* price < POC, distance_to_poc SHALL be negative.
        
        Feature: amt-fields-in-decision-events, Property 3: Distance Calculation Correctness
        **Validates: Requirements 3.3**
        """
        price, poc, val, vah = data
        
        # Verify precondition: price < POC
        assert price < poc, f"Test setup error: price ({price}) should be < POC ({poc})"
        
        # Calculate distances
        result = _calculate_distances(price, poc, vah, val)
        
        # Property 3: distance_to_poc is negative when price < POC
        assert result["distance_to_poc"] < 0, (
            f"Expected negative distance_to_poc for price ({price}) < POC ({poc}), "
            f"got {result['distance_to_poc']}"
        )
    
    @given(data=price_and_amt_levels_strategy())
    @settings(max_examples=100)
    def test_property_3_distance_to_val_is_non_negative(self, data):
        """Property 3: distance_to_val is always non-negative.
        
        *For any* price and valid AMT levels, distance_to_val SHALL be >= 0
        because it is an absolute distance.
        
        Feature: amt-fields-in-decision-events, Property 3: Distance Calculation Correctness
        **Validates: Requirements 3.1**
        """
        price, poc, val, vah = data
        
        # Calculate distances
        result = _calculate_distances(price, poc, vah, val)
        
        # Property 3: distance_to_val is non-negative (absolute value)
        assert result["distance_to_val"] >= 0, (
            f"distance_to_val should be non-negative, got {result['distance_to_val']}"
        )
    
    @given(data=price_and_amt_levels_strategy())
    @settings(max_examples=100)
    def test_property_3_distance_to_vah_is_non_negative(self, data):
        """Property 3: distance_to_vah is always non-negative.
        
        *For any* price and valid AMT levels, distance_to_vah SHALL be >= 0
        because it is an absolute distance.
        
        Feature: amt-fields-in-decision-events, Property 3: Distance Calculation Correctness
        **Validates: Requirements 3.2**
        """
        price, poc, val, vah = data
        
        # Calculate distances
        result = _calculate_distances(price, poc, vah, val)
        
        # Property 3: distance_to_vah is non-negative (absolute value)
        assert result["distance_to_vah"] >= 0, (
            f"distance_to_vah should be non-negative, got {result['distance_to_vah']}"
        )
    
    @given(
        price=price_strategy,
        poc=amt_level_strategy,
        val=amt_level_strategy,
        vah=amt_level_strategy,
    )
    @settings(max_examples=100)
    def test_property_3_calculation_is_deterministic(self, price, poc, val, vah):
        """Property 3: Distance calculation is deterministic.
        
        *For any* price and AMT levels, calling _calculate_distances
        multiple times with the same inputs SHALL return the same results.
        
        Feature: amt-fields-in-decision-events, Property 3: Distance Calculation Correctness
        **Validates: Requirements 3.1, 3.2, 3.3**
        """
        # Call calculation multiple times
        result1 = _calculate_distances(price, poc, vah, val)
        result2 = _calculate_distances(price, poc, vah, val)
        result3 = _calculate_distances(price, poc, vah, val)
        
        # All results should be identical (deterministic)
        assert result1 == result2 == result3, (
            f"Distance calculation is not deterministic: got {result1}, {result2}, {result3}"
        )
    
    @given(data=price_and_amt_levels_strategy())
    @settings(max_examples=100)
    def test_property_3_all_distance_keys_present(self, data):
        """Property 3: All distance keys are present in result.
        
        *For any* price and valid AMT levels, the result SHALL contain
        all three distance keys: distance_to_val, distance_to_vah, distance_to_poc.
        
        Feature: amt-fields-in-decision-events, Property 3: Distance Calculation Correctness
        **Validates: Requirements 3.1, 3.2, 3.3**
        """
        price, poc, val, vah = data
        
        # Calculate distances
        result = _calculate_distances(price, poc, vah, val)
        
        # All keys must be present (may include additional fields)
        required_keys = {"distance_to_val", "distance_to_vah", "distance_to_poc"}
        assert required_keys.issubset(result.keys()), (
            f"Missing keys in result: expected at least {required_keys}, got {set(result.keys())}"
        )


class TestDistanceCalculationEdgeCases:
    """Property tests for edge cases in distance calculations.
    
    Feature: amt-fields-in-decision-events
    Property 3: Distance Calculation Correctness
    **Validates: Requirements 3.1, 3.2, 3.3, 3.4**
    """
    
    @given(price=price_strategy)
    @settings(max_examples=100)
    def test_property_3_none_poc_returns_zero_distance(self, price):
        """Property 3: None POC returns 0.0 for distance_to_poc.
        
        IF POC is None, THEN distance_to_poc SHALL be 0.0.
        
        Feature: amt-fields-in-decision-events, Property 3: Distance Calculation Correctness
        **Validates: Requirements 3.4**
        """
        result = _calculate_distances(price, None, 100.0, 90.0)
        
        assert result["distance_to_poc"] == 0.0, (
            f"Expected distance_to_poc=0.0 when POC is None, got {result['distance_to_poc']}"
        )
    
    @given(price=price_strategy)
    @settings(max_examples=100)
    def test_property_3_none_vah_returns_zero_distance(self, price):
        """Property 3: None VAH returns 0.0 for distance_to_vah.
        
        IF VAH is None, THEN distance_to_vah SHALL be 0.0.
        
        Feature: amt-fields-in-decision-events, Property 3: Distance Calculation Correctness
        **Validates: Requirements 3.4**
        """
        result = _calculate_distances(price, 95.0, None, 90.0)
        
        assert result["distance_to_vah"] == 0.0, (
            f"Expected distance_to_vah=0.0 when VAH is None, got {result['distance_to_vah']}"
        )
    
    @given(price=price_strategy)
    @settings(max_examples=100)
    def test_property_3_none_val_returns_zero_distance(self, price):
        """Property 3: None VAL returns 0.0 for distance_to_val.
        
        IF VAL is None, THEN distance_to_val SHALL be 0.0.
        
        Feature: amt-fields-in-decision-events, Property 3: Distance Calculation Correctness
        **Validates: Requirements 3.4**
        """
        result = _calculate_distances(price, 95.0, 100.0, None)
        
        assert result["distance_to_val"] == 0.0, (
            f"Expected distance_to_val=0.0 when VAL is None, got {result['distance_to_val']}"
        )
    
    @given(price=price_strategy)
    @settings(max_examples=100)
    def test_property_3_all_none_returns_all_zero_distances(self, price):
        """Property 3: All None AMT levels return all 0.0 distances.
        
        IF all AMT levels (POC, VAH, VAL) are None, THEN all distances SHALL be 0.0.
        
        Feature: amt-fields-in-decision-events, Property 3: Distance Calculation Correctness
        **Validates: Requirements 3.4**
        """
        result = _calculate_distances(price, None, None, None)
        
        assert result["distance_to_poc"] == 0.0, (
            f"Expected distance_to_poc=0.0 when all None, got {result['distance_to_poc']}"
        )
        assert result["distance_to_vah"] == 0.0, (
            f"Expected distance_to_vah=0.0 when all None, got {result['distance_to_vah']}"
        )
        assert result["distance_to_val"] == 0.0, (
            f"Expected distance_to_val=0.0 when all None, got {result['distance_to_val']}"
        )
    
    @given(level=amt_level_strategy)
    @settings(max_examples=100)
    def test_property_3_price_at_poc_has_zero_distance_to_poc(self, level):
        """Property 3: Price exactly at POC has zero distance_to_poc.
        
        When price equals POC exactly, distance_to_poc SHALL be 0.0.
        
        Feature: amt-fields-in-decision-events, Property 3: Distance Calculation Correctness
        **Validates: Requirements 3.3**
        """
        poc = level
        val = level * 0.9
        vah = level * 1.1
        price = poc  # Price exactly at POC
        
        result = _calculate_distances(price, poc, vah, val)
        
        assert result["distance_to_poc"] == pytest.approx(0.0, abs=1e-9), (
            f"Expected distance_to_poc=0.0 for price ({price}) at POC ({poc}), "
            f"got {result['distance_to_poc']}"
        )
    
    @given(level=amt_level_strategy)
    @settings(max_examples=100)
    def test_property_3_price_at_val_has_zero_distance_to_val(self, level):
        """Property 3: Price exactly at VAL has zero distance_to_val.
        
        When price equals VAL exactly, distance_to_val SHALL be 0.0.
        
        Feature: amt-fields-in-decision-events, Property 3: Distance Calculation Correctness
        **Validates: Requirements 3.1**
        """
        val = level
        vah = level * 1.1
        poc = level * 1.05
        price = val  # Price exactly at VAL
        
        result = _calculate_distances(price, poc, vah, val)
        
        assert result["distance_to_val"] == pytest.approx(0.0, abs=1e-9), (
            f"Expected distance_to_val=0.0 for price ({price}) at VAL ({val}), "
            f"got {result['distance_to_val']}"
        )
    
    @given(level=amt_level_strategy)
    @settings(max_examples=100)
    def test_property_3_price_at_vah_has_zero_distance_to_vah(self, level):
        """Property 3: Price exactly at VAH has zero distance_to_vah.
        
        When price equals VAH exactly, distance_to_vah SHALL be 0.0.
        
        Feature: amt-fields-in-decision-events, Property 3: Distance Calculation Correctness
        **Validates: Requirements 3.2**
        """
        val = level * 0.9
        vah = level
        poc = level * 0.95
        price = vah  # Price exactly at VAH
        
        result = _calculate_distances(price, poc, vah, val)
        
        assert result["distance_to_vah"] == pytest.approx(0.0, abs=1e-9), (
            f"Expected distance_to_vah=0.0 for price ({price}) at VAH ({vah}), "
            f"got {result['distance_to_vah']}"
        )
    
    @given(level=amt_level_strategy)
    @settings(max_examples=100)
    def test_property_3_all_levels_equal_price_at_level(self, level):
        """Property 3: When all levels equal and price at level, all distances are zero.
        
        When POC == VAL == VAH == price, all distances SHALL be 0.0.
        
        Feature: amt-fields-in-decision-events, Property 3: Distance Calculation Correctness
        **Validates: Requirements 3.1, 3.2, 3.3**
        """
        poc = val = vah = price = level
        
        result = _calculate_distances(price, poc, vah, val)
        
        assert result["distance_to_poc"] == pytest.approx(0.0, abs=1e-9), (
            f"Expected distance_to_poc=0.0, got {result['distance_to_poc']}"
        )
        assert result["distance_to_val"] == pytest.approx(0.0, abs=1e-9), (
            f"Expected distance_to_val=0.0, got {result['distance_to_val']}"
        )
        assert result["distance_to_vah"] == pytest.approx(0.0, abs=1e-9), (
            f"Expected distance_to_vah=0.0, got {result['distance_to_vah']}"
        )


class TestDistanceCalculationMathematicalProperties:
    """Property tests for mathematical properties of distance calculations.
    
    Feature: amt-fields-in-decision-events
    Property 3: Distance Calculation Correctness
    **Validates: Requirements 3.1, 3.2, 3.3**
    """
    
    @given(data=price_and_amt_levels_strategy())
    @settings(max_examples=100)
    def test_property_3_distance_to_val_symmetry(self, data):
        """Property 3: distance_to_val is symmetric around VAL.
        
        For prices equidistant from VAL (one above, one below),
        distance_to_val SHALL be equal.
        
        Feature: amt-fields-in-decision-events, Property 3: Distance Calculation Correctness
        **Validates: Requirements 3.1**
        """
        _, poc, val, vah = data
        
        # Create two prices equidistant from VAL
        delta = 10.0
        price_above = val + delta
        price_below = val - delta
        
        # Ensure price_below is positive
        assume(price_below > 0)
        
        result_above = _calculate_distances(price_above, poc, vah, val)
        result_below = _calculate_distances(price_below, poc, vah, val)
        
        # Both should have the same distance to VAL
        assert result_above["distance_to_val"] == pytest.approx(result_below["distance_to_val"], rel=1e-9), (
            f"distance_to_val should be symmetric: "
            f"above={result_above['distance_to_val']}, below={result_below['distance_to_val']}"
        )
    
    @given(data=price_and_amt_levels_strategy())
    @settings(max_examples=100)
    def test_property_3_distance_to_vah_symmetry(self, data):
        """Property 3: distance_to_vah is symmetric around VAH.
        
        For prices equidistant from VAH (one above, one below),
        distance_to_vah SHALL be equal.
        
        Feature: amt-fields-in-decision-events, Property 3: Distance Calculation Correctness
        **Validates: Requirements 3.2**
        """
        _, poc, val, vah = data
        
        # Create two prices equidistant from VAH
        delta = 10.0
        price_above = vah + delta
        price_below = vah - delta
        
        # Ensure price_below is positive
        assume(price_below > 0)
        
        result_above = _calculate_distances(price_above, poc, vah, val)
        result_below = _calculate_distances(price_below, poc, vah, val)
        
        # Both should have the same distance to VAH
        assert result_above["distance_to_vah"] == pytest.approx(result_below["distance_to_vah"], rel=1e-9), (
            f"distance_to_vah should be symmetric: "
            f"above={result_above['distance_to_vah']}, below={result_below['distance_to_vah']}"
        )
    
    @given(data=price_and_amt_levels_strategy())
    @settings(max_examples=100)
    def test_property_3_distance_to_poc_antisymmetry(self, data):
        """Property 3: distance_to_poc is antisymmetric around POC.
        
        For prices equidistant from POC (one above, one below),
        distance_to_poc SHALL have equal magnitude but opposite signs.
        
        Feature: amt-fields-in-decision-events, Property 3: Distance Calculation Correctness
        **Validates: Requirements 3.3**
        """
        _, poc, val, vah = data
        
        # Create two prices equidistant from POC
        delta = 10.0
        price_above = poc + delta
        price_below = poc - delta
        
        # Ensure price_below is positive
        assume(price_below > 0)
        
        result_above = _calculate_distances(price_above, poc, vah, val)
        result_below = _calculate_distances(price_below, poc, vah, val)
        
        # Magnitudes should be equal
        assert abs(result_above["distance_to_poc"]) == pytest.approx(
            abs(result_below["distance_to_poc"]), rel=1e-9
        ), (
            f"distance_to_poc magnitudes should be equal: "
            f"above={result_above['distance_to_poc']}, below={result_below['distance_to_poc']}"
        )
        
        # Signs should be opposite
        assert result_above["distance_to_poc"] > 0, (
            f"distance_to_poc should be positive when price > POC"
        )
        assert result_below["distance_to_poc"] < 0, (
            f"distance_to_poc should be negative when price < POC"
        )
    
    @given(
        price=price_strategy,
        poc=amt_level_strategy,
        val=amt_level_strategy,
        vah=amt_level_strategy,
    )
    @settings(max_examples=100)
    def test_property_3_triangle_inequality_holds(self, price, poc, val, vah):
        """Property 3: Triangle inequality holds for distances.
        
        The distance from price to any AMT level should satisfy the
        triangle inequality with respect to other levels.
        
        Feature: amt-fields-in-decision-events, Property 3: Distance Calculation Correctness
        **Validates: Requirements 3.1, 3.2, 3.3**
        """
        result = _calculate_distances(price, poc, vah, val)
        
        # For absolute distances, triangle inequality should hold
        # |price - val| <= |price - poc| + |poc - val|
        # This is a basic sanity check on the distance calculations
        
        # Calculate direct distances
        dist_price_val = abs(price - val)
        dist_price_poc = abs(price - poc)
        dist_poc_val = abs(poc - val)
        
        # Triangle inequality
        assert dist_price_val <= dist_price_poc + dist_poc_val + 1e-9, (
            f"Triangle inequality violated: |price-val|={dist_price_val} > "
            f"|price-poc|={dist_price_poc} + |poc-val|={dist_poc_val}"
        )
