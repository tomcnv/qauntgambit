"""
Property-based tests for Value Boundary Profile Selection.

Feature: value-boundary-profile-selection, Property 1: Boundary Profile Detection
Validates: Requirements 1.1, 1.2, 1.3, 1.4

Tests for:
- Property 1: Boundary Profile Detection

This test validates that the ComponentScorer correctly identifies profiles
designed for value boundary trading based on their min_distance_from_vah
and min_distance_from_val conditions.
"""

import pytest
from hypothesis import given, strategies as st, settings, assume
from typing import Optional

from quantgambit.deeptrader_core.profiles.component_scorer import ComponentScorer
from quantgambit.deeptrader_core.profiles.router_config import RouterConfig
from quantgambit.deeptrader_core.profiles.context_vector import ContextVector
from quantgambit.deeptrader_core.strategies.chessboard.profile_spec import ProfileConditions


# ============================================================================
# Hypothesis Strategies
# ============================================================================

# Position in value area
position_in_value_values = st.sampled_from(["above", "below", "inside"])

# Distance values in basis points (positive floats)
distance_bps_values = st.floats(min_value=0.1, max_value=100.0, allow_nan=False, allow_infinity=False)

# Optional distance values (None or positive float)
optional_distance_bps = st.one_of(st.none(), distance_bps_values)

# Symbol names
symbols = st.sampled_from(["BTC-USDT", "ETH-USDT", "SOL-USDT", "DOGE-USDT"])


@st.composite
def context_vectors_with_position(draw, position: Optional[str] = None) -> ContextVector:
    """Generate valid ContextVector instances with optional fixed position_in_value."""
    pos = position if position is not None else draw(position_in_value_values)
    return ContextVector(
        symbol=draw(symbols),
        timestamp=draw(st.floats(min_value=1000000000.0, max_value=2000000000.0)),
        price=draw(st.floats(min_value=100.0, max_value=100000.0)),
        position_in_value=pos,
    )


@st.composite
def profile_conditions_with_boundary(
    draw,
    has_vah: Optional[bool] = None,
    has_val: Optional[bool] = None,
    has_required_location: Optional[bool] = None,
) -> ProfileConditions:
    """
    Generate ProfileConditions with configurable boundary conditions.
    
    Args:
        has_vah: If True, always set min_distance_from_vah; if False, never set it; if None, random
        has_val: If True, always set min_distance_from_val; if False, never set it; if None, random
        has_required_location: If True, always set required_value_location; if False, never set it; if None, random
    """
    # Determine whether to set each field
    set_vah = draw(st.booleans()) if has_vah is None else has_vah
    set_val = draw(st.booleans()) if has_val is None else has_val
    set_required = draw(st.booleans()) if has_required_location is None else has_required_location
    
    min_distance_from_vah = draw(distance_bps_values) if set_vah else None
    min_distance_from_val = draw(distance_bps_values) if set_val else None
    required_value_location = draw(position_in_value_values) if set_required else None
    
    return ProfileConditions(
        min_distance_from_vah=min_distance_from_vah,
        min_distance_from_val=min_distance_from_val,
        required_value_location=required_value_location,
    )


# ============================================================================
# Property 1: Boundary Profile Detection Tests
# ============================================================================

class TestBoundaryProfileDetection:
    """
    Property 1: Boundary Profile Detection
    
    For any ProfileConditions object:
    - If min_distance_from_vah is not None, the profile should be identified as a VAH boundary profile
    - If min_distance_from_val is not None, the profile should be identified as a VAL boundary profile
    - If neither is set, the profile should not be identified as a boundary profile
    
    **Feature: value-boundary-profile-selection, Property 1: Boundary Profile Detection**
    **Validates: Requirements 1.1, 1.2, 1.3, 1.4**
    """
    
    @given(
        min_distance_from_vah=distance_bps_values,
        position_in_value=position_in_value_values,
    )
    @settings(max_examples=100)
    def test_vah_boundary_profile_detection(
        self,
        min_distance_from_vah: float,
        position_in_value: str,
    ):
        """
        Property 1: Boundary Profile Detection
        
        WHEN a profile has min_distance_from_vah condition set,
        THE ComponentScorer SHALL identify it as a boundary profile for VAH trading.
        
        When position_in_value="above" and profile has min_distance_from_vah,
        the value_fit score should be >= 0.8 (boundary bonus).
        
        **Validates: Requirements 1.1**
        """
        config = RouterConfig()
        scorer = ComponentScorer(config)
        
        # Profile with min_distance_from_vah set (VAH boundary profile)
        conditions = ProfileConditions(
            min_distance_from_vah=min_distance_from_vah,
            min_distance_from_val=None,
            required_value_location=None,
        )
        
        context = ContextVector(
            symbol="BTC-USDT",
            timestamp=1700000000.0,
            price=50000.0,
            position_in_value=position_in_value,
        )
        
        score = scorer.score_value_fit(conditions, context)
        
        # Verify boundary profile detection behavior
        if position_in_value == "above":
            # VAH boundary profile should get bonus when price is above value area
            assert score >= 0.8, \
                f"VAH boundary profile with position_in_value='above' should get score >= 0.8, got {score}"
        else:
            # When not at the matching boundary, should return neutral
            assert score == 0.5, \
                f"VAH boundary profile with position_in_value='{position_in_value}' should get neutral score 0.5, got {score}"
    
    @given(
        min_distance_from_val=distance_bps_values,
        position_in_value=position_in_value_values,
    )
    @settings(max_examples=100)
    def test_val_boundary_profile_detection(
        self,
        min_distance_from_val: float,
        position_in_value: str,
    ):
        """
        Property 1: Boundary Profile Detection
        
        WHEN a profile has min_distance_from_val condition set,
        THE ComponentScorer SHALL identify it as a boundary profile for VAL trading.
        
        When position_in_value="below" and profile has min_distance_from_val,
        the value_fit score should be >= 0.8 (boundary bonus).
        
        **Validates: Requirements 1.2**
        """
        config = RouterConfig()
        scorer = ComponentScorer(config)
        
        # Profile with min_distance_from_val set (VAL boundary profile)
        conditions = ProfileConditions(
            min_distance_from_vah=None,
            min_distance_from_val=min_distance_from_val,
            required_value_location=None,
        )
        
        context = ContextVector(
            symbol="BTC-USDT",
            timestamp=1700000000.0,
            price=50000.0,
            position_in_value=position_in_value,
        )
        
        score = scorer.score_value_fit(conditions, context)
        
        # Verify boundary profile detection behavior
        if position_in_value == "below":
            # VAL boundary profile should get bonus when price is below value area
            assert score >= 0.8, \
                f"VAL boundary profile with position_in_value='below' should get score >= 0.8, got {score}"
        else:
            # When not at the matching boundary, should return neutral
            assert score == 0.5, \
                f"VAL boundary profile with position_in_value='{position_in_value}' should get neutral score 0.5, got {score}"
    
    @given(
        min_distance_from_vah=distance_bps_values,
        min_distance_from_val=distance_bps_values,
        position_in_value=position_in_value_values,
    )
    @settings(max_examples=100)
    def test_both_boundary_conditions_detection(
        self,
        min_distance_from_vah: float,
        min_distance_from_val: float,
        position_in_value: str,
    ):
        """
        Property 1: Boundary Profile Detection
        
        WHEN a profile has both min_distance_from_vah and min_distance_from_val conditions set,
        THE ComponentScorer SHALL identify it as a boundary profile for both VAH and VAL trading.
        
        The profile should get boundary bonus when price is at either boundary.
        
        **Validates: Requirements 1.3**
        """
        config = RouterConfig()
        scorer = ComponentScorer(config)
        
        # Profile with both boundary conditions set
        conditions = ProfileConditions(
            min_distance_from_vah=min_distance_from_vah,
            min_distance_from_val=min_distance_from_val,
            required_value_location=None,
        )
        
        context = ContextVector(
            symbol="BTC-USDT",
            timestamp=1700000000.0,
            price=50000.0,
            position_in_value=position_in_value,
        )
        
        score = scorer.score_value_fit(conditions, context)
        
        # Verify boundary profile detection behavior
        if position_in_value == "above":
            # Should get VAH boundary bonus
            assert score >= 0.8, \
                f"Dual boundary profile with position_in_value='above' should get score >= 0.8, got {score}"
        elif position_in_value == "below":
            # Should get VAL boundary bonus
            assert score >= 0.8, \
                f"Dual boundary profile with position_in_value='below' should get score >= 0.8, got {score}"
        else:
            # Inside position should return neutral
            assert score == 0.5, \
                f"Dual boundary profile with position_in_value='inside' should get neutral score 0.5, got {score}"
    
    @given(position_in_value=position_in_value_values)
    @settings(max_examples=100)
    def test_non_boundary_profile_detection(self, position_in_value: str):
        """
        Property 1: Boundary Profile Detection
        
        WHEN a profile has neither min_distance_from_vah nor min_distance_from_val conditions set,
        THE ComponentScorer SHALL NOT identify it as a boundary profile.
        
        The profile should always return neutral score (0.5) regardless of position.
        
        **Validates: Requirements 1.4**
        """
        config = RouterConfig()
        scorer = ComponentScorer(config)
        
        # Profile with no boundary conditions
        conditions = ProfileConditions(
            min_distance_from_vah=None,
            min_distance_from_val=None,
            required_value_location=None,
        )
        
        context = ContextVector(
            symbol="BTC-USDT",
            timestamp=1700000000.0,
            price=50000.0,
            position_in_value=position_in_value,
        )
        
        score = scorer.score_value_fit(conditions, context)
        
        # Non-boundary profile should always return neutral
        assert score == 0.5, \
            f"Non-boundary profile should always return neutral score 0.5, got {score} " \
            f"(position_in_value='{position_in_value}')"
    
    @given(
        min_distance_from_vah=optional_distance_bps,
        min_distance_from_val=optional_distance_bps,
        position_in_value=position_in_value_values,
    )
    @settings(max_examples=100)
    def test_boundary_detection_consistency(
        self,
        min_distance_from_vah: Optional[float],
        min_distance_from_val: Optional[float],
        position_in_value: str,
    ):
        """
        Property 1: Boundary Profile Detection
        
        For any ProfileConditions object, the boundary detection logic should be consistent:
        - VAH boundary profile (min_distance_from_vah set) + position="above" → score >= 0.8
        - VAL boundary profile (min_distance_from_val set) + position="below" → score >= 0.8
        - Non-matching boundary or no boundary conditions → score == 0.5
        
        **Validates: Requirements 1.1, 1.2, 1.3, 1.4**
        """
        config = RouterConfig()
        scorer = ComponentScorer(config)
        
        conditions = ProfileConditions(
            min_distance_from_vah=min_distance_from_vah,
            min_distance_from_val=min_distance_from_val,
            required_value_location=None,
        )
        
        context = ContextVector(
            symbol="BTC-USDT",
            timestamp=1700000000.0,
            price=50000.0,
            position_in_value=position_in_value,
        )
        
        score = scorer.score_value_fit(conditions, context)
        
        # Determine expected behavior
        is_vah_boundary = min_distance_from_vah is not None
        is_val_boundary = min_distance_from_val is not None
        
        # Check boundary bonus conditions
        should_get_vah_bonus = is_vah_boundary and position_in_value == "above"
        should_get_val_bonus = is_val_boundary and position_in_value == "below"
        
        if should_get_vah_bonus or should_get_val_bonus:
            assert score >= 0.8, \
                f"Boundary profile at matching boundary should get score >= 0.8, got {score} " \
                f"(vah={min_distance_from_vah}, val={min_distance_from_val}, pos={position_in_value})"
        else:
            assert score == 0.5, \
                f"Non-matching boundary should return neutral 0.5, got {score} " \
                f"(vah={min_distance_from_vah}, val={min_distance_from_val}, pos={position_in_value})"
    
    @given(
        min_distance_from_vah=optional_distance_bps,
        min_distance_from_val=optional_distance_bps,
        position_in_value=position_in_value_values,
    )
    @settings(max_examples=100)
    def test_score_always_in_valid_range(
        self,
        min_distance_from_vah: Optional[float],
        min_distance_from_val: Optional[float],
        position_in_value: str,
    ):
        """
        Property 1: Boundary Profile Detection
        
        For any inputs (without required_value_location), the value_fit score
        SHALL always be in [0.5, 1.0] range.
        
        **Validates: Requirements 1.1, 1.2, 1.3, 1.4**
        """
        config = RouterConfig()
        scorer = ComponentScorer(config)
        
        conditions = ProfileConditions(
            min_distance_from_vah=min_distance_from_vah,
            min_distance_from_val=min_distance_from_val,
            required_value_location=None,
        )
        
        context = ContextVector(
            symbol="BTC-USDT",
            timestamp=1700000000.0,
            price=50000.0,
            position_in_value=position_in_value,
        )
        
        score = scorer.score_value_fit(conditions, context)
        
        # Without required_value_location, score should be in [0.5, 1.0]
        # (0.5 for neutral, 0.85 for boundary bonus)
        assert 0.5 <= score <= 1.0, \
            f"Score should be in [0.5, 1.0] without required_value_location, got {score}"


# ============================================================================
# Property 2: Boundary Bonus Scoring Tests
# ============================================================================

class TestBoundaryBonusScoring:
    """
    Property 2: Boundary Bonus Scoring
    
    For any ProfileConditions with `min_distance_from_vah` set and no `required_value_location`,
    when `position_in_value="above"`, the `value_fit` score should be >= 0.8.
    
    Similarly, for any ProfileConditions with `min_distance_from_val` set and no `required_value_location`,
    when `position_in_value="below"`, the `value_fit` score should be >= 0.8.
    
    **Feature: value-boundary-profile-selection, Property 2: Boundary Bonus Scoring**
    **Validates: Requirements 2.1, 2.2**
    """
    
    @given(
        min_distance_from_vah=distance_bps_values,
        symbol=symbols,
        timestamp=st.floats(min_value=1000000000.0, max_value=2000000000.0),
        price=st.floats(min_value=100.0, max_value=100000.0),
    )
    @settings(max_examples=100)
    def test_vah_boundary_profile_bonus_when_above(
        self,
        min_distance_from_vah: float,
        symbol: str,
        timestamp: float,
        price: float,
    ):
        """
        Property 2: Boundary Bonus Scoring
        
        WHEN a profile has min_distance_from_vah condition set AND no required_value_location,
        AND position_in_value="above",
        THE ComponentScorer SHALL return a value_fit score >= 0.8.
        
        **Validates: Requirements 2.1**
        """
        config = RouterConfig()
        scorer = ComponentScorer(config)
        
        # Profile with min_distance_from_vah set (VAH boundary profile)
        # and NO required_value_location
        conditions = ProfileConditions(
            min_distance_from_vah=min_distance_from_vah,
            min_distance_from_val=None,
            required_value_location=None,  # Explicitly no required_value_location
        )
        
        context = ContextVector(
            symbol=symbol,
            timestamp=timestamp,
            price=price,
            position_in_value="above",  # Price is above value area
        )
        
        score = scorer.score_value_fit(conditions, context)
        
        # VAH boundary profile should get bonus when price is above value area
        assert score >= 0.8, \
            f"VAH boundary profile (min_distance_from_vah={min_distance_from_vah}) " \
            f"with position_in_value='above' should get score >= 0.8, got {score}"
    
    @given(
        min_distance_from_val=distance_bps_values,
        symbol=symbols,
        timestamp=st.floats(min_value=1000000000.0, max_value=2000000000.0),
        price=st.floats(min_value=100.0, max_value=100000.0),
    )
    @settings(max_examples=100)
    def test_val_boundary_profile_bonus_when_below(
        self,
        min_distance_from_val: float,
        symbol: str,
        timestamp: float,
        price: float,
    ):
        """
        Property 2: Boundary Bonus Scoring
        
        WHEN a profile has min_distance_from_val condition set AND no required_value_location,
        AND position_in_value="below",
        THE ComponentScorer SHALL return a value_fit score >= 0.8.
        
        **Validates: Requirements 2.2**
        """
        config = RouterConfig()
        scorer = ComponentScorer(config)
        
        # Profile with min_distance_from_val set (VAL boundary profile)
        # and NO required_value_location
        conditions = ProfileConditions(
            min_distance_from_vah=None,
            min_distance_from_val=min_distance_from_val,
            required_value_location=None,  # Explicitly no required_value_location
        )
        
        context = ContextVector(
            symbol=symbol,
            timestamp=timestamp,
            price=price,
            position_in_value="below",  # Price is below value area
        )
        
        score = scorer.score_value_fit(conditions, context)
        
        # VAL boundary profile should get bonus when price is below value area
        assert score >= 0.8, \
            f"VAL boundary profile (min_distance_from_val={min_distance_from_val}) " \
            f"with position_in_value='below' should get score >= 0.8, got {score}"
    
    @given(
        min_distance_from_vah=distance_bps_values,
        min_distance_from_val=distance_bps_values,
        symbol=symbols,
        timestamp=st.floats(min_value=1000000000.0, max_value=2000000000.0),
        price=st.floats(min_value=100.0, max_value=100000.0),
    )
    @settings(max_examples=100)
    def test_dual_boundary_profile_bonus_when_above(
        self,
        min_distance_from_vah: float,
        min_distance_from_val: float,
        symbol: str,
        timestamp: float,
        price: float,
    ):
        """
        Property 2: Boundary Bonus Scoring
        
        WHEN a profile has both min_distance_from_vah AND min_distance_from_val conditions set,
        AND no required_value_location, AND position_in_value="above",
        THE ComponentScorer SHALL return a value_fit score >= 0.8.
        
        **Validates: Requirements 2.1**
        """
        config = RouterConfig()
        scorer = ComponentScorer(config)
        
        # Profile with both boundary conditions set
        # and NO required_value_location
        conditions = ProfileConditions(
            min_distance_from_vah=min_distance_from_vah,
            min_distance_from_val=min_distance_from_val,
            required_value_location=None,  # Explicitly no required_value_location
        )
        
        context = ContextVector(
            symbol=symbol,
            timestamp=timestamp,
            price=price,
            position_in_value="above",  # Price is above value area
        )
        
        score = scorer.score_value_fit(conditions, context)
        
        # Dual boundary profile should get VAH bonus when price is above
        assert score >= 0.8, \
            f"Dual boundary profile (vah={min_distance_from_vah}, val={min_distance_from_val}) " \
            f"with position_in_value='above' should get score >= 0.8, got {score}"
    
    @given(
        min_distance_from_vah=distance_bps_values,
        min_distance_from_val=distance_bps_values,
        symbol=symbols,
        timestamp=st.floats(min_value=1000000000.0, max_value=2000000000.0),
        price=st.floats(min_value=100.0, max_value=100000.0),
    )
    @settings(max_examples=100)
    def test_dual_boundary_profile_bonus_when_below(
        self,
        min_distance_from_vah: float,
        min_distance_from_val: float,
        symbol: str,
        timestamp: float,
        price: float,
    ):
        """
        Property 2: Boundary Bonus Scoring
        
        WHEN a profile has both min_distance_from_vah AND min_distance_from_val conditions set,
        AND no required_value_location, AND position_in_value="below",
        THE ComponentScorer SHALL return a value_fit score >= 0.8.
        
        **Validates: Requirements 2.2**
        """
        config = RouterConfig()
        scorer = ComponentScorer(config)
        
        # Profile with both boundary conditions set
        # and NO required_value_location
        conditions = ProfileConditions(
            min_distance_from_vah=min_distance_from_vah,
            min_distance_from_val=min_distance_from_val,
            required_value_location=None,  # Explicitly no required_value_location
        )
        
        context = ContextVector(
            symbol=symbol,
            timestamp=timestamp,
            price=price,
            position_in_value="below",  # Price is below value area
        )
        
        score = scorer.score_value_fit(conditions, context)
        
        # Dual boundary profile should get VAL bonus when price is below
        assert score >= 0.8, \
            f"Dual boundary profile (vah={min_distance_from_vah}, val={min_distance_from_val}) " \
            f"with position_in_value='below' should get score >= 0.8, got {score}"
    
    @given(
        min_distance_from_vah=optional_distance_bps,
        min_distance_from_val=optional_distance_bps,
        symbol=symbols,
        timestamp=st.floats(min_value=1000000000.0, max_value=2000000000.0),
        price=st.floats(min_value=100.0, max_value=100000.0),
    )
    @settings(max_examples=100)
    def test_boundary_bonus_scoring_comprehensive(
        self,
        min_distance_from_vah: Optional[float],
        min_distance_from_val: Optional[float],
        symbol: str,
        timestamp: float,
        price: float,
    ):
        """
        Property 2: Boundary Bonus Scoring
        
        Comprehensive test for boundary bonus scoring:
        - VAH boundary profile (min_distance_from_vah set) + position="above" → score >= 0.8
        - VAL boundary profile (min_distance_from_val set) + position="below" → score >= 0.8
        
        This test verifies the property holds across all combinations of boundary conditions.
        
        **Validates: Requirements 2.1, 2.2**
        """
        # Skip if neither boundary condition is set (not a boundary profile)
        assume(min_distance_from_vah is not None or min_distance_from_val is not None)
        
        config = RouterConfig()
        scorer = ComponentScorer(config)
        
        conditions = ProfileConditions(
            min_distance_from_vah=min_distance_from_vah,
            min_distance_from_val=min_distance_from_val,
            required_value_location=None,  # Explicitly no required_value_location
        )
        
        is_vah_boundary = min_distance_from_vah is not None
        is_val_boundary = min_distance_from_val is not None
        
        # Test VAH boundary bonus (Requirement 2.1)
        if is_vah_boundary:
            context_above = ContextVector(
                symbol=symbol,
                timestamp=timestamp,
                price=price,
                position_in_value="above",
            )
            score_above = scorer.score_value_fit(conditions, context_above)
            assert score_above >= 0.8, \
                f"VAH boundary profile with position_in_value='above' should get score >= 0.8, " \
                f"got {score_above} (vah={min_distance_from_vah}, val={min_distance_from_val})"
        
        # Test VAL boundary bonus (Requirement 2.2)
        if is_val_boundary:
            context_below = ContextVector(
                symbol=symbol,
                timestamp=timestamp,
                price=price,
                position_in_value="below",
            )
            score_below = scorer.score_value_fit(conditions, context_below)
            assert score_below >= 0.8, \
                f"VAL boundary profile with position_in_value='below' should get score >= 0.8, " \
                f"got {score_below} (vah={min_distance_from_vah}, val={min_distance_from_val})"


# ============================================================================
# Property 3: Neutral Score for Inside Position Tests
# ============================================================================

class TestNeutralScoreForInsidePosition:
    """
    Property 3: Neutral Score for Inside Position
    
    For any ProfileConditions with boundary conditions (`min_distance_from_vah` or
    `min_distance_from_val`) but no `required_value_location`, when `position_in_value="inside"`,
    the `value_fit` score should be exactly 0.5.
    
    **Feature: value-boundary-profile-selection, Property 3: Neutral Score for Inside Position**
    **Validates: Requirements 2.3**
    """
    
    @given(
        min_distance_from_vah=distance_bps_values,
        symbol=symbols,
        timestamp=st.floats(min_value=1000000000.0, max_value=2000000000.0),
        price=st.floats(min_value=100.0, max_value=100000.0),
    )
    @settings(max_examples=100)
    def test_vah_boundary_profile_neutral_when_inside(
        self,
        min_distance_from_vah: float,
        symbol: str,
        timestamp: float,
        price: float,
    ):
        """
        Property 3: Neutral Score for Inside Position
        
        WHEN a profile has min_distance_from_vah condition set AND no required_value_location,
        AND position_in_value="inside",
        THE ComponentScorer SHALL return a value_fit score of exactly 0.5 (neutral).
        
        **Validates: Requirements 2.3**
        """
        config = RouterConfig()
        scorer = ComponentScorer(config)
        
        # Profile with min_distance_from_vah set (VAH boundary profile)
        # and NO required_value_location
        conditions = ProfileConditions(
            min_distance_from_vah=min_distance_from_vah,
            min_distance_from_val=None,
            required_value_location=None,  # Explicitly no required_value_location
        )
        
        context = ContextVector(
            symbol=symbol,
            timestamp=timestamp,
            price=price,
            position_in_value="inside",  # Price is inside value area
        )
        
        score = scorer.score_value_fit(conditions, context)
        
        # VAH boundary profile should return neutral when price is inside value area
        assert score == 0.5, \
            f"VAH boundary profile (min_distance_from_vah={min_distance_from_vah}) " \
            f"with position_in_value='inside' should get neutral score 0.5, got {score}"
    
    @given(
        min_distance_from_val=distance_bps_values,
        symbol=symbols,
        timestamp=st.floats(min_value=1000000000.0, max_value=2000000000.0),
        price=st.floats(min_value=100.0, max_value=100000.0),
    )
    @settings(max_examples=100)
    def test_val_boundary_profile_neutral_when_inside(
        self,
        min_distance_from_val: float,
        symbol: str,
        timestamp: float,
        price: float,
    ):
        """
        Property 3: Neutral Score for Inside Position
        
        WHEN a profile has min_distance_from_val condition set AND no required_value_location,
        AND position_in_value="inside",
        THE ComponentScorer SHALL return a value_fit score of exactly 0.5 (neutral).
        
        **Validates: Requirements 2.3**
        """
        config = RouterConfig()
        scorer = ComponentScorer(config)
        
        # Profile with min_distance_from_val set (VAL boundary profile)
        # and NO required_value_location
        conditions = ProfileConditions(
            min_distance_from_vah=None,
            min_distance_from_val=min_distance_from_val,
            required_value_location=None,  # Explicitly no required_value_location
        )
        
        context = ContextVector(
            symbol=symbol,
            timestamp=timestamp,
            price=price,
            position_in_value="inside",  # Price is inside value area
        )
        
        score = scorer.score_value_fit(conditions, context)
        
        # VAL boundary profile should return neutral when price is inside value area
        assert score == 0.5, \
            f"VAL boundary profile (min_distance_from_val={min_distance_from_val}) " \
            f"with position_in_value='inside' should get neutral score 0.5, got {score}"
    
    @given(
        min_distance_from_vah=distance_bps_values,
        min_distance_from_val=distance_bps_values,
        symbol=symbols,
        timestamp=st.floats(min_value=1000000000.0, max_value=2000000000.0),
        price=st.floats(min_value=100.0, max_value=100000.0),
    )
    @settings(max_examples=100)
    def test_dual_boundary_profile_neutral_when_inside(
        self,
        min_distance_from_vah: float,
        min_distance_from_val: float,
        symbol: str,
        timestamp: float,
        price: float,
    ):
        """
        Property 3: Neutral Score for Inside Position
        
        WHEN a profile has both min_distance_from_vah AND min_distance_from_val conditions set,
        AND no required_value_location, AND position_in_value="inside",
        THE ComponentScorer SHALL return a value_fit score of exactly 0.5 (neutral).
        
        **Validates: Requirements 2.3**
        """
        config = RouterConfig()
        scorer = ComponentScorer(config)
        
        # Profile with both boundary conditions set
        # and NO required_value_location
        conditions = ProfileConditions(
            min_distance_from_vah=min_distance_from_vah,
            min_distance_from_val=min_distance_from_val,
            required_value_location=None,  # Explicitly no required_value_location
        )
        
        context = ContextVector(
            symbol=symbol,
            timestamp=timestamp,
            price=price,
            position_in_value="inside",  # Price is inside value area
        )
        
        score = scorer.score_value_fit(conditions, context)
        
        # Dual boundary profile should return neutral when price is inside value area
        assert score == 0.5, \
            f"Dual boundary profile (vah={min_distance_from_vah}, val={min_distance_from_val}) " \
            f"with position_in_value='inside' should get neutral score 0.5, got {score}"
    
    @given(
        min_distance_from_vah=optional_distance_bps,
        min_distance_from_val=optional_distance_bps,
        symbol=symbols,
        timestamp=st.floats(min_value=1000000000.0, max_value=2000000000.0),
        price=st.floats(min_value=100.0, max_value=100000.0),
    )
    @settings(max_examples=100)
    def test_neutral_score_inside_position_comprehensive(
        self,
        min_distance_from_vah: Optional[float],
        min_distance_from_val: Optional[float],
        symbol: str,
        timestamp: float,
        price: float,
    ):
        """
        Property 3: Neutral Score for Inside Position
        
        Comprehensive test: For any ProfileConditions with boundary conditions
        (min_distance_from_vah or min_distance_from_val) but no required_value_location,
        when position_in_value="inside", the value_fit score should be exactly 0.5.
        
        This test verifies the property holds across all combinations of boundary conditions.
        
        **Validates: Requirements 2.3**
        """
        # Skip if neither boundary condition is set (not a boundary profile)
        assume(min_distance_from_vah is not None or min_distance_from_val is not None)
        
        config = RouterConfig()
        scorer = ComponentScorer(config)
        
        conditions = ProfileConditions(
            min_distance_from_vah=min_distance_from_vah,
            min_distance_from_val=min_distance_from_val,
            required_value_location=None,  # Explicitly no required_value_location
        )
        
        context = ContextVector(
            symbol=symbol,
            timestamp=timestamp,
            price=price,
            position_in_value="inside",  # Price is inside value area
        )
        
        score = scorer.score_value_fit(conditions, context)
        
        # Any boundary profile should return neutral when price is inside value area
        assert score == 0.5, \
            f"Boundary profile (vah={min_distance_from_vah}, val={min_distance_from_val}) " \
            f"with position_in_value='inside' should get neutral score 0.5, got {score}"


# ============================================================================
# Property 4: Required Value Location Precedence Tests
# ============================================================================

class TestRequiredValueLocationPrecedence:
    """
    Property 4: Required Value Location Precedence
    
    For any ProfileConditions with `required_value_location` set, the `value_fit` score
    should be 1.0 when `position_in_value` matches `required_value_location`, and 0.0
    otherwise, regardless of any boundary conditions that may also be set.
    
    **Feature: value-boundary-profile-selection, Property 4: Required Value Location Precedence**
    **Validates: Requirements 2.4, 3.1**
    """
    
    @given(
        required_value_location=position_in_value_values,
        position_in_value=position_in_value_values,
        symbol=symbols,
        timestamp=st.floats(min_value=1000000000.0, max_value=2000000000.0),
        price=st.floats(min_value=100.0, max_value=100000.0),
    )
    @settings(max_examples=100)
    def test_required_value_location_match_returns_1(
        self,
        required_value_location: str,
        position_in_value: str,
        symbol: str,
        timestamp: float,
        price: float,
    ):
        """
        Property 4: Required Value Location Precedence
        
        WHEN a profile has required_value_location set AND position_in_value matches,
        THE ComponentScorer SHALL return a value_fit score of exactly 1.0.
        
        **Validates: Requirements 2.4, 3.1**
        """
        # Only test matching cases
        assume(required_value_location == position_in_value)
        
        config = RouterConfig()
        scorer = ComponentScorer(config)
        
        # Profile with required_value_location set (no boundary conditions)
        conditions = ProfileConditions(
            min_distance_from_vah=None,
            min_distance_from_val=None,
            required_value_location=required_value_location,
        )
        
        context = ContextVector(
            symbol=symbol,
            timestamp=timestamp,
            price=price,
            position_in_value=position_in_value,
        )
        
        score = scorer.score_value_fit(conditions, context)
        
        # When required_value_location matches position_in_value, score should be 1.0
        assert score == 1.0, \
            f"Profile with required_value_location='{required_value_location}' " \
            f"and position_in_value='{position_in_value}' should get score 1.0, got {score}"
    
    @given(
        required_value_location=position_in_value_values,
        position_in_value=position_in_value_values,
        symbol=symbols,
        timestamp=st.floats(min_value=1000000000.0, max_value=2000000000.0),
        price=st.floats(min_value=100.0, max_value=100000.0),
    )
    @settings(max_examples=100)
    def test_required_value_location_mismatch_returns_0(
        self,
        required_value_location: str,
        position_in_value: str,
        symbol: str,
        timestamp: float,
        price: float,
    ):
        """
        Property 4: Required Value Location Precedence
        
        WHEN a profile has required_value_location set AND position_in_value does NOT match,
        THE ComponentScorer SHALL return a value_fit score of exactly 0.0.
        
        **Validates: Requirements 2.4, 3.1**
        """
        # Only test non-matching cases
        assume(required_value_location != position_in_value)
        
        config = RouterConfig()
        scorer = ComponentScorer(config)
        
        # Profile with required_value_location set (no boundary conditions)
        conditions = ProfileConditions(
            min_distance_from_vah=None,
            min_distance_from_val=None,
            required_value_location=required_value_location,
        )
        
        context = ContextVector(
            symbol=symbol,
            timestamp=timestamp,
            price=price,
            position_in_value=position_in_value,
        )
        
        score = scorer.score_value_fit(conditions, context)
        
        # When required_value_location doesn't match position_in_value, score should be 0.0
        assert score == 0.0, \
            f"Profile with required_value_location='{required_value_location}' " \
            f"and position_in_value='{position_in_value}' should get score 0.0, got {score}"
    
    @given(
        required_value_location=position_in_value_values,
        position_in_value=position_in_value_values,
        min_distance_from_vah=distance_bps_values,
        symbol=symbols,
        timestamp=st.floats(min_value=1000000000.0, max_value=2000000000.0),
        price=st.floats(min_value=100.0, max_value=100000.0),
    )
    @settings(max_examples=100)
    def test_required_value_location_precedence_over_vah_boundary(
        self,
        required_value_location: str,
        position_in_value: str,
        min_distance_from_vah: float,
        symbol: str,
        timestamp: float,
        price: float,
    ):
        """
        Property 4: Required Value Location Precedence
        
        WHEN a profile has BOTH required_value_location AND min_distance_from_vah set,
        THE required_value_location SHALL take precedence over boundary conditions.
        
        Score should be 1.0 when position matches, 0.0 otherwise,
        regardless of the VAH boundary condition.
        
        **Validates: Requirements 2.4, 3.1**
        """
        config = RouterConfig()
        scorer = ComponentScorer(config)
        
        # Profile with BOTH required_value_location AND min_distance_from_vah set
        conditions = ProfileConditions(
            min_distance_from_vah=min_distance_from_vah,
            min_distance_from_val=None,
            required_value_location=required_value_location,
        )
        
        context = ContextVector(
            symbol=symbol,
            timestamp=timestamp,
            price=price,
            position_in_value=position_in_value,
        )
        
        score = scorer.score_value_fit(conditions, context)
        
        # required_value_location takes precedence over boundary conditions
        if required_value_location == position_in_value:
            assert score == 1.0, \
                f"Profile with required_value_location='{required_value_location}' " \
                f"and min_distance_from_vah={min_distance_from_vah} " \
                f"should get score 1.0 when position matches, got {score}"
        else:
            assert score == 0.0, \
                f"Profile with required_value_location='{required_value_location}' " \
                f"and min_distance_from_vah={min_distance_from_vah} " \
                f"should get score 0.0 when position doesn't match, got {score}"
    
    @given(
        required_value_location=position_in_value_values,
        position_in_value=position_in_value_values,
        min_distance_from_val=distance_bps_values,
        symbol=symbols,
        timestamp=st.floats(min_value=1000000000.0, max_value=2000000000.0),
        price=st.floats(min_value=100.0, max_value=100000.0),
    )
    @settings(max_examples=100)
    def test_required_value_location_precedence_over_val_boundary(
        self,
        required_value_location: str,
        position_in_value: str,
        min_distance_from_val: float,
        symbol: str,
        timestamp: float,
        price: float,
    ):
        """
        Property 4: Required Value Location Precedence
        
        WHEN a profile has BOTH required_value_location AND min_distance_from_val set,
        THE required_value_location SHALL take precedence over boundary conditions.
        
        Score should be 1.0 when position matches, 0.0 otherwise,
        regardless of the VAL boundary condition.
        
        **Validates: Requirements 2.4, 3.1**
        """
        config = RouterConfig()
        scorer = ComponentScorer(config)
        
        # Profile with BOTH required_value_location AND min_distance_from_val set
        conditions = ProfileConditions(
            min_distance_from_vah=None,
            min_distance_from_val=min_distance_from_val,
            required_value_location=required_value_location,
        )
        
        context = ContextVector(
            symbol=symbol,
            timestamp=timestamp,
            price=price,
            position_in_value=position_in_value,
        )
        
        score = scorer.score_value_fit(conditions, context)
        
        # required_value_location takes precedence over boundary conditions
        if required_value_location == position_in_value:
            assert score == 1.0, \
                f"Profile with required_value_location='{required_value_location}' " \
                f"and min_distance_from_val={min_distance_from_val} " \
                f"should get score 1.0 when position matches, got {score}"
        else:
            assert score == 0.0, \
                f"Profile with required_value_location='{required_value_location}' " \
                f"and min_distance_from_val={min_distance_from_val} " \
                f"should get score 0.0 when position doesn't match, got {score}"
    
    @given(
        required_value_location=position_in_value_values,
        position_in_value=position_in_value_values,
        min_distance_from_vah=distance_bps_values,
        min_distance_from_val=distance_bps_values,
        symbol=symbols,
        timestamp=st.floats(min_value=1000000000.0, max_value=2000000000.0),
        price=st.floats(min_value=100.0, max_value=100000.0),
    )
    @settings(max_examples=100)
    def test_required_value_location_precedence_over_both_boundaries(
        self,
        required_value_location: str,
        position_in_value: str,
        min_distance_from_vah: float,
        min_distance_from_val: float,
        symbol: str,
        timestamp: float,
        price: float,
    ):
        """
        Property 4: Required Value Location Precedence
        
        WHEN a profile has required_value_location AND BOTH min_distance_from_vah
        AND min_distance_from_val set, THE required_value_location SHALL take
        precedence over all boundary conditions.
        
        Score should be 1.0 when position matches, 0.0 otherwise,
        regardless of any boundary conditions.
        
        **Validates: Requirements 2.4, 3.1**
        """
        config = RouterConfig()
        scorer = ComponentScorer(config)
        
        # Profile with required_value_location AND both boundary conditions set
        conditions = ProfileConditions(
            min_distance_from_vah=min_distance_from_vah,
            min_distance_from_val=min_distance_from_val,
            required_value_location=required_value_location,
        )
        
        context = ContextVector(
            symbol=symbol,
            timestamp=timestamp,
            price=price,
            position_in_value=position_in_value,
        )
        
        score = scorer.score_value_fit(conditions, context)
        
        # required_value_location takes precedence over all boundary conditions
        if required_value_location == position_in_value:
            assert score == 1.0, \
                f"Profile with required_value_location='{required_value_location}' " \
                f"and both boundary conditions (vah={min_distance_from_vah}, val={min_distance_from_val}) " \
                f"should get score 1.0 when position matches, got {score}"
        else:
            assert score == 0.0, \
                f"Profile with required_value_location='{required_value_location}' " \
                f"and both boundary conditions (vah={min_distance_from_vah}, val={min_distance_from_val}) " \
                f"should get score 0.0 when position doesn't match, got {score}"
    
    @given(
        required_value_location=position_in_value_values,
        position_in_value=position_in_value_values,
        min_distance_from_vah=optional_distance_bps,
        min_distance_from_val=optional_distance_bps,
        symbol=symbols,
        timestamp=st.floats(min_value=1000000000.0, max_value=2000000000.0),
        price=st.floats(min_value=100.0, max_value=100000.0),
    )
    @settings(max_examples=100)
    def test_required_value_location_precedence_comprehensive(
        self,
        required_value_location: str,
        position_in_value: str,
        min_distance_from_vah: Optional[float],
        min_distance_from_val: Optional[float],
        symbol: str,
        timestamp: float,
        price: float,
    ):
        """
        Property 4: Required Value Location Precedence
        
        Comprehensive test: For any ProfileConditions with required_value_location set,
        the value_fit score should be 1.0 when position_in_value matches
        required_value_location, and 0.0 otherwise, regardless of any boundary
        conditions that may also be set.
        
        This test verifies the property holds across all combinations of boundary conditions.
        
        **Validates: Requirements 2.4, 3.1**
        """
        config = RouterConfig()
        scorer = ComponentScorer(config)
        
        # Profile with required_value_location set (with any combination of boundary conditions)
        conditions = ProfileConditions(
            min_distance_from_vah=min_distance_from_vah,
            min_distance_from_val=min_distance_from_val,
            required_value_location=required_value_location,
        )
        
        context = ContextVector(
            symbol=symbol,
            timestamp=timestamp,
            price=price,
            position_in_value=position_in_value,
        )
        
        score = scorer.score_value_fit(conditions, context)
        
        # required_value_location always takes precedence
        if required_value_location == position_in_value:
            assert score == 1.0, \
                f"Profile with required_value_location='{required_value_location}' " \
                f"(vah={min_distance_from_vah}, val={min_distance_from_val}) " \
                f"should get score 1.0 when position='{position_in_value}' matches, got {score}"
        else:
            assert score == 0.0, \
                f"Profile with required_value_location='{required_value_location}' " \
                f"(vah={min_distance_from_vah}, val={min_distance_from_val}) " \
                f"should get score 0.0 when position='{position_in_value}' doesn't match, got {score}"
    
    @given(
        required_value_location=position_in_value_values,
        min_distance_from_vah=optional_distance_bps,
        min_distance_from_val=optional_distance_bps,
        symbol=symbols,
        timestamp=st.floats(min_value=1000000000.0, max_value=2000000000.0),
        price=st.floats(min_value=100.0, max_value=100000.0),
    )
    @settings(max_examples=100)
    def test_required_value_location_score_always_binary(
        self,
        required_value_location: str,
        min_distance_from_vah: Optional[float],
        min_distance_from_val: Optional[float],
        symbol: str,
        timestamp: float,
        price: float,
    ):
        """
        Property 4: Required Value Location Precedence
        
        For any ProfileConditions with required_value_location set,
        the value_fit score SHALL always be either 1.0 or 0.0 (binary),
        never any intermediate value like 0.5 or 0.85.
        
        This ensures required_value_location always takes precedence and
        boundary bonus scoring is never applied when required_value_location is set.
        
        **Validates: Requirements 2.4, 3.1**
        """
        config = RouterConfig()
        scorer = ComponentScorer(config)
        
        conditions = ProfileConditions(
            min_distance_from_vah=min_distance_from_vah,
            min_distance_from_val=min_distance_from_val,
            required_value_location=required_value_location,
        )
        
        # Test all three position values
        for position in ["above", "below", "inside"]:
            context = ContextVector(
                symbol=symbol,
                timestamp=timestamp,
                price=price,
                position_in_value=position,
            )
            
            score = scorer.score_value_fit(conditions, context)
            
            # Score must be binary (1.0 or 0.0) when required_value_location is set
            assert score in (0.0, 1.0), \
                f"Profile with required_value_location='{required_value_location}' " \
                f"(vah={min_distance_from_vah}, val={min_distance_from_val}) " \
                f"should get binary score (0.0 or 1.0), got {score} for position='{position}'"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


# ============================================================================
# Property 5: Neutral Score for Non-Boundary Profiles Tests
# ============================================================================

class TestNeutralScoreForNonBoundaryProfiles:
    """
    Property 5: Neutral Score for Non-Boundary Profiles
    
    For any ProfileConditions without `required_value_location`, `min_distance_from_vah`,
    or `min_distance_from_val` (or with only `min_distance_from_poc`), the `value_fit`
    score should be exactly 0.5 regardless of `position_in_value`.
    
    **Feature: value-boundary-profile-selection, Property 5: Neutral Score for Non-Boundary Profiles**
    **Validates: Requirements 3.2, 3.3**
    """
    
    @given(
        position_in_value=position_in_value_values,
        symbol=symbols,
        timestamp=st.floats(min_value=1000000000.0, max_value=2000000000.0),
        price=st.floats(min_value=100.0, max_value=100000.0),
    )
    @settings(max_examples=100)
    def test_no_value_conditions_returns_neutral(
        self,
        position_in_value: str,
        symbol: str,
        timestamp: float,
        price: float,
    ):
        """
        Property 5: Neutral Score for Non-Boundary Profiles
        
        WHEN a profile has no value-related conditions (no required_value_location,
        no min_distance_from_vah, no min_distance_from_val),
        THE ComponentScorer SHALL return a value_fit score of exactly 0.5 (neutral)
        regardless of position_in_value.
        
        **Validates: Requirements 3.2**
        """
        config = RouterConfig()
        scorer = ComponentScorer(config)
        
        # Profile with NO value-related conditions
        conditions = ProfileConditions(
            min_distance_from_vah=None,
            min_distance_from_val=None,
            required_value_location=None,
        )
        
        context = ContextVector(
            symbol=symbol,
            timestamp=timestamp,
            price=price,
            position_in_value=position_in_value,
        )
        
        score = scorer.score_value_fit(conditions, context)
        
        # Non-boundary profile should always return neutral score
        assert score == 0.5, \
            f"Profile with no value conditions should return neutral score 0.5, " \
            f"got {score} (position_in_value='{position_in_value}')"
    
    @given(
        min_distance_from_poc=distance_bps_values,
        position_in_value=position_in_value_values,
        symbol=symbols,
        timestamp=st.floats(min_value=1000000000.0, max_value=2000000000.0),
        price=st.floats(min_value=100.0, max_value=100000.0),
    )
    @settings(max_examples=100)
    def test_only_poc_distance_returns_neutral(
        self,
        min_distance_from_poc: float,
        position_in_value: str,
        symbol: str,
        timestamp: float,
        price: float,
    ):
        """
        Property 5: Neutral Score for Non-Boundary Profiles
        
        WHEN a profile has only min_distance_from_poc condition (not VAH/VAL),
        THE ComponentScorer SHALL return a value_fit score of exactly 0.5 (neutral)
        regardless of position_in_value.
        
        min_distance_from_poc is NOT a boundary condition (VAH/VAL), so profiles
        with only this condition should be treated as non-boundary profiles.
        
        **Validates: Requirements 3.3**
        """
        config = RouterConfig()
        scorer = ComponentScorer(config)
        
        # Profile with ONLY min_distance_from_poc (not a boundary condition)
        conditions = ProfileConditions(
            min_distance_from_vah=None,
            min_distance_from_val=None,
            min_distance_from_poc=min_distance_from_poc,  # Only POC distance, not VAH/VAL
            required_value_location=None,
        )
        
        context = ContextVector(
            symbol=symbol,
            timestamp=timestamp,
            price=price,
            position_in_value=position_in_value,
        )
        
        score = scorer.score_value_fit(conditions, context)
        
        # Profile with only POC distance should return neutral score
        assert score == 0.5, \
            f"Profile with only min_distance_from_poc={min_distance_from_poc} " \
            f"should return neutral score 0.5, got {score} " \
            f"(position_in_value='{position_in_value}')"
    
    @given(
        position_in_value=position_in_value_values,
        symbol=symbols,
        timestamp=st.floats(min_value=1000000000.0, max_value=2000000000.0),
        price=st.floats(min_value=100.0, max_value=100000.0),
    )
    @settings(max_examples=100)
    def test_neutral_score_for_above_position(
        self,
        position_in_value: str,
        symbol: str,
        timestamp: float,
        price: float,
    ):
        """
        Property 5: Neutral Score for Non-Boundary Profiles
        
        WHEN a profile has no value-related conditions AND position_in_value="above",
        THE ComponentScorer SHALL return a value_fit score of exactly 0.5 (neutral).
        
        This specifically tests that non-boundary profiles don't get any bonus
        when price is above the value area.
        
        **Validates: Requirements 3.2**
        """
        config = RouterConfig()
        scorer = ComponentScorer(config)
        
        # Profile with NO value-related conditions
        conditions = ProfileConditions(
            min_distance_from_vah=None,
            min_distance_from_val=None,
            required_value_location=None,
        )
        
        context = ContextVector(
            symbol=symbol,
            timestamp=timestamp,
            price=price,
            position_in_value="above",  # Explicitly test "above" position
        )
        
        score = scorer.score_value_fit(conditions, context)
        
        # Non-boundary profile should return neutral even when price is above
        assert score == 0.5, \
            f"Non-boundary profile with position_in_value='above' " \
            f"should return neutral score 0.5, got {score}"
    
    @given(
        position_in_value=position_in_value_values,
        symbol=symbols,
        timestamp=st.floats(min_value=1000000000.0, max_value=2000000000.0),
        price=st.floats(min_value=100.0, max_value=100000.0),
    )
    @settings(max_examples=100)
    def test_neutral_score_for_below_position(
        self,
        position_in_value: str,
        symbol: str,
        timestamp: float,
        price: float,
    ):
        """
        Property 5: Neutral Score for Non-Boundary Profiles
        
        WHEN a profile has no value-related conditions AND position_in_value="below",
        THE ComponentScorer SHALL return a value_fit score of exactly 0.5 (neutral).
        
        This specifically tests that non-boundary profiles don't get any bonus
        when price is below the value area.
        
        **Validates: Requirements 3.2**
        """
        config = RouterConfig()
        scorer = ComponentScorer(config)
        
        # Profile with NO value-related conditions
        conditions = ProfileConditions(
            min_distance_from_vah=None,
            min_distance_from_val=None,
            required_value_location=None,
        )
        
        context = ContextVector(
            symbol=symbol,
            timestamp=timestamp,
            price=price,
            position_in_value="below",  # Explicitly test "below" position
        )
        
        score = scorer.score_value_fit(conditions, context)
        
        # Non-boundary profile should return neutral even when price is below
        assert score == 0.5, \
            f"Non-boundary profile with position_in_value='below' " \
            f"should return neutral score 0.5, got {score}"
    
    @given(
        position_in_value=position_in_value_values,
        symbol=symbols,
        timestamp=st.floats(min_value=1000000000.0, max_value=2000000000.0),
        price=st.floats(min_value=100.0, max_value=100000.0),
    )
    @settings(max_examples=100)
    def test_neutral_score_for_inside_position(
        self,
        position_in_value: str,
        symbol: str,
        timestamp: float,
        price: float,
    ):
        """
        Property 5: Neutral Score for Non-Boundary Profiles
        
        WHEN a profile has no value-related conditions AND position_in_value="inside",
        THE ComponentScorer SHALL return a value_fit score of exactly 0.5 (neutral).
        
        This specifically tests that non-boundary profiles return neutral
        when price is inside the value area.
        
        **Validates: Requirements 3.2**
        """
        config = RouterConfig()
        scorer = ComponentScorer(config)
        
        # Profile with NO value-related conditions
        conditions = ProfileConditions(
            min_distance_from_vah=None,
            min_distance_from_val=None,
            required_value_location=None,
        )
        
        context = ContextVector(
            symbol=symbol,
            timestamp=timestamp,
            price=price,
            position_in_value="inside",  # Explicitly test "inside" position
        )
        
        score = scorer.score_value_fit(conditions, context)
        
        # Non-boundary profile should return neutral when price is inside
        assert score == 0.5, \
            f"Non-boundary profile with position_in_value='inside' " \
            f"should return neutral score 0.5, got {score}"
    
    @given(
        min_distance_from_poc=optional_distance_bps,
        position_in_value=position_in_value_values,
        symbol=symbols,
        timestamp=st.floats(min_value=1000000000.0, max_value=2000000000.0),
        price=st.floats(min_value=100.0, max_value=100000.0),
    )
    @settings(max_examples=100)
    def test_neutral_score_comprehensive(
        self,
        min_distance_from_poc: Optional[float],
        position_in_value: str,
        symbol: str,
        timestamp: float,
        price: float,
    ):
        """
        Property 5: Neutral Score for Non-Boundary Profiles
        
        Comprehensive test: For any ProfileConditions without required_value_location,
        min_distance_from_vah, or min_distance_from_val (regardless of min_distance_from_poc),
        the value_fit score should be exactly 0.5 regardless of position_in_value.
        
        This test verifies the property holds across all combinations of:
        - All position_in_value values ("above", "below", "inside")
        - With or without min_distance_from_poc
        
        **Validates: Requirements 3.2, 3.3**
        """
        config = RouterConfig()
        scorer = ComponentScorer(config)
        
        # Profile with NO boundary conditions (VAH/VAL), but may have POC distance
        conditions = ProfileConditions(
            min_distance_from_vah=None,  # No VAH boundary condition
            min_distance_from_val=None,  # No VAL boundary condition
            min_distance_from_poc=min_distance_from_poc,  # May or may not have POC distance
            required_value_location=None,  # No required value location
        )
        
        context = ContextVector(
            symbol=symbol,
            timestamp=timestamp,
            price=price,
            position_in_value=position_in_value,
        )
        
        score = scorer.score_value_fit(conditions, context)
        
        # Non-boundary profile should always return neutral score
        assert score == 0.5, \
            f"Non-boundary profile (poc={min_distance_from_poc}) " \
            f"should return neutral score 0.5, got {score} " \
            f"(position_in_value='{position_in_value}')"
    
    @given(
        position_in_value=position_in_value_values,
        symbol=symbols,
        timestamp=st.floats(min_value=1000000000.0, max_value=2000000000.0),
        price=st.floats(min_value=100.0, max_value=100000.0),
    )
    @settings(max_examples=100)
    def test_non_boundary_profile_score_is_exactly_half(
        self,
        position_in_value: str,
        symbol: str,
        timestamp: float,
        price: float,
    ):
        """
        Property 5: Neutral Score for Non-Boundary Profiles
        
        For any non-boundary profile, the value_fit score SHALL be exactly 0.5,
        not approximately 0.5 or close to 0.5, but precisely 0.5.
        
        This test ensures there's no floating point drift or rounding issues
        in the neutral score calculation.
        
        **Validates: Requirements 3.2, 3.3**
        """
        config = RouterConfig()
        scorer = ComponentScorer(config)
        
        # Profile with NO value-related conditions
        conditions = ProfileConditions(
            min_distance_from_vah=None,
            min_distance_from_val=None,
            required_value_location=None,
        )
        
        context = ContextVector(
            symbol=symbol,
            timestamp=timestamp,
            price=price,
            position_in_value=position_in_value,
        )
        
        score = scorer.score_value_fit(conditions, context)
        
        # Score must be EXACTLY 0.5 (not approximately)
        assert score == 0.5, \
            f"Non-boundary profile score must be exactly 0.5, got {score} " \
            f"(difference from 0.5: {abs(score - 0.5)})"
        
        # Additional check: ensure it's the exact float value
        assert score is not None and isinstance(score, float), \
            f"Score must be a float, got {type(score)}"
