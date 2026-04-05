"""Property-based tests for AMT Position Classification.

Feature: amt-fields-in-decision-events

Tests the position classification algorithm properties:
- Property 2: Position Classification Consistency

**Validates: Requirements 2.1, 2.2, 2.3**

These tests use Hypothesis to generate random prices and AMT levels (VAL, VAH)
and verify that the position classification is deterministic and consistent
with the price relationship to bounds.
"""

import pytest
from hypothesis import given, strategies as st, settings, assume

from quantgambit.signals.stages.amt_calculator import _classify_position


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
    """Generate valid AMT levels where VAL <= VAH.
    
    This strategy ensures that the generated value area bounds are valid,
    meaning VAL is always less than or equal to VAH.
    """
    val = draw(amt_level_strategy)
    # VAH must be >= VAL
    vah = draw(st.floats(
        min_value=val,
        max_value=max(val * 2, val + 10000),  # Allow reasonable spread
        allow_nan=False,
        allow_infinity=False,
    ))
    return val, vah


@st.composite
def price_above_vah_strategy(draw):
    """Generate a price that is strictly above VAH.
    
    This strategy generates valid AMT levels and a price that is
    guaranteed to be above the value area high.
    """
    val, vah = draw(valid_amt_levels_strategy())
    # Price must be > VAH
    price = draw(st.floats(
        min_value=vah + 0.0001,  # Strictly above VAH
        max_value=vah * 2 + 10000,
        allow_nan=False,
        allow_infinity=False,
    ))
    return price, val, vah


@st.composite
def price_below_val_strategy(draw):
    """Generate a price that is strictly below VAL.
    
    This strategy generates valid AMT levels and a price that is
    guaranteed to be below the value area low.
    """
    val, vah = draw(valid_amt_levels_strategy())
    # Price must be < VAL
    # Ensure we have room below VAL
    assume(val > 0.01)
    price = draw(st.floats(
        min_value=0.0001,
        max_value=val - 0.0001,  # Strictly below VAL
        allow_nan=False,
        allow_infinity=False,
    ))
    return price, val, vah


@st.composite
def price_inside_value_area_strategy(draw):
    """Generate a price that is inside the value area (VAL <= price <= VAH).
    
    This strategy generates valid AMT levels and a price that is
    guaranteed to be within the value area bounds (inclusive).
    """
    val, vah = draw(valid_amt_levels_strategy())
    # Price must be VAL <= price <= VAH
    price = draw(st.floats(
        min_value=val,
        max_value=vah,
        allow_nan=False,
        allow_infinity=False,
    ))
    return price, val, vah


# =============================================================================
# Property Tests
# =============================================================================

class TestPositionClassificationProperties:
    """Property-based tests for Position Classification.
    
    Feature: amt-fields-in-decision-events
    Property 2: Position Classification Consistency
    **Validates: Requirements 2.1, 2.2, 2.3**
    """
    
    @given(data=price_above_vah_strategy())
    @settings(max_examples=100)
    def test_property_2_price_above_vah_classified_as_above(self, data):
        """Property 2: Price above VAH is classified as "above".
        
        *For any* price > VAH, the position_in_value classification SHALL be "above".
        
        Feature: amt-fields-in-decision-events, Property 2: Position Classification Consistency
        **Validates: Requirements 2.1**
        """
        price, val, vah = data
        
        # Verify precondition: price > VAH
        assert price > vah, f"Test setup error: price ({price}) should be > VAH ({vah})"
        
        # Classify position
        result = _classify_position(price, vah, val)
        
        # Property 2: If price > VAH, classification is "above"
        assert result == "above", (
            f"Expected 'above' for price ({price}) > VAH ({vah}), got '{result}'"
        )
    
    @given(data=price_below_val_strategy())
    @settings(max_examples=100)
    def test_property_2_price_below_val_classified_as_below(self, data):
        """Property 2: Price below VAL is classified as "below".
        
        *For any* price < VAL, the position_in_value classification SHALL be "below".
        
        Feature: amt-fields-in-decision-events, Property 2: Position Classification Consistency
        **Validates: Requirements 2.2**
        """
        price, val, vah = data
        
        # Verify precondition: price < VAL
        assert price < val, f"Test setup error: price ({price}) should be < VAL ({val})"
        
        # Classify position
        result = _classify_position(price, vah, val)
        
        # Property 2: If price < VAL, classification is "below"
        assert result == "below", (
            f"Expected 'below' for price ({price}) < VAL ({val}), got '{result}'"
        )
    
    @given(data=price_inside_value_area_strategy())
    @settings(max_examples=100)
    def test_property_2_price_inside_value_area_classified_as_inside(self, data):
        """Property 2: Price inside value area is classified as "inside".
        
        *For any* VAL <= price <= VAH, the position_in_value classification SHALL be "inside".
        
        Feature: amt-fields-in-decision-events, Property 2: Position Classification Consistency
        **Validates: Requirements 2.3**
        """
        price, val, vah = data
        
        # Verify precondition: VAL <= price <= VAH
        assert val <= price <= vah, (
            f"Test setup error: price ({price}) should be in [{val}, {vah}]"
        )
        
        # Classify position
        result = _classify_position(price, vah, val)
        
        # Property 2: If VAL <= price <= VAH, classification is "inside"
        assert result == "inside", (
            f"Expected 'inside' for price ({price}) in [{val}, {vah}], got '{result}'"
        )
    
    @given(
        price=price_strategy,
        val=amt_level_strategy,
        vah=amt_level_strategy,
    )
    @settings(max_examples=100)
    def test_property_2_classification_is_deterministic(self, price, val, vah):
        """Property 2: Classification is deterministic.
        
        *For any* price and valid AMT levels, calling _classify_position
        multiple times with the same inputs SHALL return the same result.
        
        Feature: amt-fields-in-decision-events, Property 2: Position Classification Consistency
        **Validates: Requirements 2.1, 2.2, 2.3**
        """
        # Ensure VAL <= VAH for valid AMT levels
        if val > vah:
            val, vah = vah, val
        
        # Call classification multiple times
        result1 = _classify_position(price, vah, val)
        result2 = _classify_position(price, vah, val)
        result3 = _classify_position(price, vah, val)
        
        # All results should be identical (deterministic)
        assert result1 == result2 == result3, (
            f"Classification is not deterministic: got {result1}, {result2}, {result3}"
        )
    
    @given(
        price=price_strategy,
        val=amt_level_strategy,
        vah=amt_level_strategy,
    )
    @settings(max_examples=100)
    def test_property_2_classification_is_exhaustive(self, price, val, vah):
        """Property 2: Classification covers all cases.
        
        *For any* price and valid AMT levels, the classification SHALL be
        one of "above", "below", or "inside" - no other values are possible.
        
        Feature: amt-fields-in-decision-events, Property 2: Position Classification Consistency
        **Validates: Requirements 2.1, 2.2, 2.3**
        """
        # Ensure VAL <= VAH for valid AMT levels
        if val > vah:
            val, vah = vah, val
        
        result = _classify_position(price, vah, val)
        
        # Result must be one of the three valid classifications
        valid_classifications = {"above", "below", "inside"}
        assert result in valid_classifications, (
            f"Invalid classification '{result}', expected one of {valid_classifications}"
        )
    
    @given(
        price=price_strategy,
        val=amt_level_strategy,
        vah=amt_level_strategy,
    )
    @settings(max_examples=100)
    def test_property_2_classification_matches_price_relationship(self, price, val, vah):
        """Property 2: Classification matches price relationship to bounds.
        
        *For any* price and valid AMT levels (VAL, VAH), the position_in_value
        classification SHALL be deterministic and consistent:
        - If price > VAH, classification is "above"
        - If price < VAL, classification is "below"
        - If VAL <= price <= VAH, classification is "inside"
        
        Feature: amt-fields-in-decision-events, Property 2: Position Classification Consistency
        **Validates: Requirements 2.1, 2.2, 2.3**
        """
        # Ensure VAL <= VAH for valid AMT levels
        if val > vah:
            val, vah = vah, val
        
        result = _classify_position(price, vah, val)
        
        # Verify classification matches price relationship
        if price > vah:
            expected = "above"
        elif price < val:
            expected = "below"
        else:
            expected = "inside"
        
        assert result == expected, (
            f"Classification mismatch: price={price}, VAL={val}, VAH={vah}, "
            f"expected '{expected}', got '{result}'"
        )


class TestPositionClassificationEdgeCases:
    """Property tests for edge cases in position classification.
    
    Feature: amt-fields-in-decision-events
    Property 2: Position Classification Consistency
    **Validates: Requirements 2.1, 2.2, 2.3, 2.4**
    """
    
    @given(price=price_strategy)
    @settings(max_examples=100)
    def test_property_2_none_vah_defaults_to_inside(self, price):
        """Property 2: None VAH defaults to "inside".
        
        IF VAH is None, THEN the classification SHALL default to "inside".
        
        Feature: amt-fields-in-decision-events, Property 2: Position Classification Consistency
        **Validates: Requirements 2.4**
        """
        result = _classify_position(price, None, 100.0)
        
        assert result == "inside", (
            f"Expected 'inside' when VAH is None, got '{result}'"
        )
    
    @given(price=price_strategy)
    @settings(max_examples=100)
    def test_property_2_none_val_defaults_to_inside(self, price):
        """Property 2: None VAL defaults to "inside".
        
        IF VAL is None, THEN the classification SHALL default to "inside".
        
        Feature: amt-fields-in-decision-events, Property 2: Position Classification Consistency
        **Validates: Requirements 2.4**
        """
        result = _classify_position(price, 100.0, None)
        
        assert result == "inside", (
            f"Expected 'inside' when VAL is None, got '{result}'"
        )
    
    @given(price=price_strategy)
    @settings(max_examples=100)
    def test_property_2_both_none_defaults_to_inside(self, price):
        """Property 2: Both VAH and VAL None defaults to "inside".
        
        IF both VAH and VAL are None, THEN the classification SHALL default to "inside".
        
        Feature: amt-fields-in-decision-events, Property 2: Position Classification Consistency
        **Validates: Requirements 2.4**
        """
        result = _classify_position(price, None, None)
        
        assert result == "inside", (
            f"Expected 'inside' when both VAH and VAL are None, got '{result}'"
        )
    
    @given(level=amt_level_strategy)
    @settings(max_examples=100)
    def test_property_2_price_exactly_at_vah_is_inside(self, level):
        """Property 2: Price exactly at VAH is classified as "inside".
        
        When price equals VAH exactly, it is within the value area (inclusive).
        
        Feature: amt-fields-in-decision-events, Property 2: Position Classification Consistency
        **Validates: Requirements 2.3**
        """
        val = level * 0.9  # VAL is 10% below
        vah = level
        price = vah  # Price exactly at VAH
        
        result = _classify_position(price, vah, val)
        
        assert result == "inside", (
            f"Expected 'inside' for price ({price}) exactly at VAH ({vah}), got '{result}'"
        )
    
    @given(level=amt_level_strategy)
    @settings(max_examples=100)
    def test_property_2_price_exactly_at_val_is_inside(self, level):
        """Property 2: Price exactly at VAL is classified as "inside".
        
        When price equals VAL exactly, it is within the value area (inclusive).
        
        Feature: amt-fields-in-decision-events, Property 2: Position Classification Consistency
        **Validates: Requirements 2.3**
        """
        val = level
        vah = level * 1.1  # VAH is 10% above
        price = val  # Price exactly at VAL
        
        result = _classify_position(price, vah, val)
        
        assert result == "inside", (
            f"Expected 'inside' for price ({price}) exactly at VAL ({val}), got '{result}'"
        )
    
    @given(level=amt_level_strategy)
    @settings(max_examples=100)
    def test_property_2_val_equals_vah_price_at_level_is_inside(self, level):
        """Property 2: When VAL equals VAH, price at that level is "inside".
        
        When VAL == VAH (degenerate value area), a price at that level
        is classified as "inside".
        
        Feature: amt-fields-in-decision-events, Property 2: Position Classification Consistency
        **Validates: Requirements 2.3**
        """
        val = level
        vah = level  # VAL == VAH
        price = level  # Price at the same level
        
        result = _classify_position(price, vah, val)
        
        assert result == "inside", (
            f"Expected 'inside' for price ({price}) at VAL=VAH ({level}), got '{result}'"
        )
    
    @given(level=amt_level_strategy)
    @settings(max_examples=100)
    def test_property_2_val_equals_vah_price_above_is_above(self, level):
        """Property 2: When VAL equals VAH, price above is "above".
        
        When VAL == VAH (degenerate value area), a price above that level
        is classified as "above".
        
        Feature: amt-fields-in-decision-events, Property 2: Position Classification Consistency
        **Validates: Requirements 2.1**
        """
        val = level
        vah = level  # VAL == VAH
        price = level * 1.1  # Price above
        
        result = _classify_position(price, vah, val)
        
        assert result == "above", (
            f"Expected 'above' for price ({price}) above VAL=VAH ({level}), got '{result}'"
        )
    
    @given(level=amt_level_strategy)
    @settings(max_examples=100)
    def test_property_2_val_equals_vah_price_below_is_below(self, level):
        """Property 2: When VAL equals VAH, price below is "below".
        
        When VAL == VAH (degenerate value area), a price below that level
        is classified as "below".
        
        Feature: amt-fields-in-decision-events, Property 2: Position Classification Consistency
        **Validates: Requirements 2.2**
        """
        val = level
        vah = level  # VAL == VAH
        price = level * 0.9  # Price below
        
        result = _classify_position(price, vah, val)
        
        assert result == "below", (
            f"Expected 'below' for price ({price}) below VAL=VAH ({level}), got '{result}'"
        )

