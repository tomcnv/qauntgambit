"""
Property-based tests for Profile Router v2 Regime Mapping.

Feature: profile-router-v2, Property 1: Regime Mapping Determinism
Validates: Requirements 1.1

Tests that for any ContextVector with a valid market_regime, the RegimeMapper
SHALL produce a regime_family that matches the specified mapping rules.
"""

import pytest
from hypothesis import given, strategies as st, settings, assume
from typing import Tuple

from quantgambit.deeptrader_core.profiles.regime_mapper import (
    RegimeMapper,
    RegimeMappingResult,
    REGIME_FAMILIES,
    MARKET_REGIMES,
)
from quantgambit.deeptrader_core.profiles.router_config import RouterConfig
from quantgambit.deeptrader_core.profiles.context_vector import ContextVector


# ============================================================================
# Hypothesis Strategies
# ============================================================================

# Valid market regimes
valid_market_regimes = st.sampled_from(["range", "breakout", "squeeze", "chop"])

# Trend strength values
trend_strength_values = st.floats(min_value=0.0, max_value=0.02, allow_nan=False, allow_infinity=False)

# Liquidity score values (0-1)
liquidity_score_values = st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False)

# Expected cost in basis points
expected_cost_bps_values = st.floats(min_value=0.0, max_value=50.0, allow_nan=False, allow_infinity=False)


@st.composite
def context_vectors_for_regime_mapping(draw) -> ContextVector:
    """Generate ContextVector instances for regime mapping tests."""
    return ContextVector(
        symbol=draw(st.sampled_from(["BTC-USDT", "ETH-USDT", "SOL-USDT"])),
        timestamp=draw(st.floats(min_value=0, max_value=2e9, allow_nan=False, allow_infinity=False)),
        price=draw(st.floats(min_value=100, max_value=100000, allow_nan=False, allow_infinity=False)),
        market_regime=draw(valid_market_regimes),
        trend_strength=draw(trend_strength_values),
        liquidity_score=draw(liquidity_score_values),
        expected_cost_bps=draw(expected_cost_bps_values),
    )


@st.composite
def context_vectors_with_unknown_regime(draw) -> ContextVector:
    """Generate ContextVector instances with unknown market regimes."""
    unknown_regime = draw(st.text(min_size=1, max_size=20, alphabet="abcdefghijklmnopqrstuvwxyz"))
    assume(unknown_regime.lower() not in MARKET_REGIMES)
    
    return ContextVector(
        symbol=draw(st.sampled_from(["BTC-USDT", "ETH-USDT", "SOL-USDT"])),
        timestamp=draw(st.floats(min_value=0, max_value=2e9, allow_nan=False, allow_infinity=False)),
        price=draw(st.floats(min_value=100, max_value=100000, allow_nan=False, allow_infinity=False)),
        market_regime=unknown_regime,
        trend_strength=draw(trend_strength_values),
        liquidity_score=draw(liquidity_score_values),
        expected_cost_bps=draw(expected_cost_bps_values),
    )


# ============================================================================
# Property Tests
# ============================================================================

class TestRegimeMappingDeterminism:
    """
    Property 1: Regime Mapping Determinism
    
    For any ContextVector with a valid market_regime, the RegimeMapper SHALL
    produce a regime_family that matches the specified mapping rules:
    - "range" with trend_strength <= 0.003 → "mean_revert"
    - "range" with trend_strength > 0.003 → "trend"
    - "breakout" → "trend"
    - "squeeze" with liquidity_score >= 0.3 → "trend"
    - "squeeze" with liquidity_score < 0.3 → "avoid"
    - "chop" with expected_cost_bps < 5 → "mean_revert"
    - "chop" with expected_cost_bps >= 5 → "avoid"
    
    **Feature: profile-router-v2, Property 1: Regime Mapping Determinism**
    **Validates: Requirements 1.1**
    """
    
    @given(context=context_vectors_for_regime_mapping())
    @settings(max_examples=100)
    def test_regime_mapping_produces_valid_family(self, context: ContextVector):
        """
        Property 1: Regime Mapping Determinism
        
        For any valid ContextVector, the mapped regime_family SHALL be one of
        the valid regime families: "trend", "mean_revert", "avoid", "unknown".
        
        **Validates: Requirements 1.1**
        """
        config = RouterConfig()
        mapper = RegimeMapper(config)
        
        regime_family, confidence = mapper.map_regime(context)
        
        assert regime_family in REGIME_FAMILIES, \
            f"Invalid regime_family '{regime_family}', expected one of {REGIME_FAMILIES}"
        assert 0.0 <= confidence <= 1.0, \
            f"Confidence {confidence} out of range [0, 1]"
    
    @given(context=context_vectors_for_regime_mapping())
    @settings(max_examples=100)
    def test_regime_mapping_is_deterministic(self, context: ContextVector):
        """
        Property 1: Regime Mapping Determinism
        
        For any ContextVector, calling map_regime multiple times with the same
        input SHALL produce the same output.
        
        **Validates: Requirements 1.1**
        """
        config = RouterConfig()
        mapper = RegimeMapper(config)
        
        result1 = mapper.map_regime(context)
        result2 = mapper.map_regime(context)
        result3 = mapper.map_regime(context)
        
        assert result1 == result2 == result3, \
            f"Non-deterministic mapping: {result1} != {result2} != {result3}"
    
    @given(
        trend_strength=st.floats(min_value=0.0, max_value=0.003, allow_nan=False, allow_infinity=False)
    )
    @settings(max_examples=100)
    def test_range_low_trend_maps_to_mean_revert(self, trend_strength: float):
        """
        Property 1: Regime Mapping Determinism
        
        For "range" regime with trend_strength <= 0.003, SHALL map to "mean_revert".
        
        **Validates: Requirements 1.1**
        """
        config = RouterConfig()
        mapper = RegimeMapper(config)
        
        context = ContextVector(
            symbol="BTC-USDT",
            timestamp=0.0,
            price=50000.0,
            market_regime="range",
            trend_strength=trend_strength,
        )
        
        regime_family, confidence = mapper.map_regime(context)
        
        assert regime_family == "mean_revert", \
            f"range with trend_strength={trend_strength} should map to mean_revert, got {regime_family}"
        assert confidence == 0.8, \
            f"Expected confidence 0.8, got {confidence}"
    
    @given(
        trend_strength=st.floats(min_value=0.0031, max_value=0.02, allow_nan=False, allow_infinity=False)
    )
    @settings(max_examples=100)
    def test_range_high_trend_maps_to_trend(self, trend_strength: float):
        """
        Property 1: Regime Mapping Determinism
        
        For "range" regime with trend_strength > 0.003, SHALL map to "trend".
        
        **Validates: Requirements 1.1**
        """
        config = RouterConfig()
        mapper = RegimeMapper(config)
        
        context = ContextVector(
            symbol="BTC-USDT",
            timestamp=0.0,
            price=50000.0,
            market_regime="range",
            trend_strength=trend_strength,
        )
        
        regime_family, confidence = mapper.map_regime(context)
        
        assert regime_family == "trend", \
            f"range with trend_strength={trend_strength} should map to trend, got {regime_family}"
        assert confidence == 0.6, \
            f"Expected confidence 0.6, got {confidence}"
    
    @given(
        liquidity_score=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
        expected_cost_bps=st.floats(min_value=0.0, max_value=50.0, allow_nan=False, allow_infinity=False)
    )
    @settings(max_examples=100)
    def test_breakout_always_maps_to_trend(self, liquidity_score: float, expected_cost_bps: float):
        """
        Property 1: Regime Mapping Determinism
        
        For "breakout" regime, SHALL always map to "trend" regardless of other factors.
        
        **Validates: Requirements 1.1**
        """
        config = RouterConfig()
        mapper = RegimeMapper(config)
        
        context = ContextVector(
            symbol="BTC-USDT",
            timestamp=0.0,
            price=50000.0,
            market_regime="breakout",
            liquidity_score=liquidity_score,
            expected_cost_bps=expected_cost_bps,
        )
        
        regime_family, confidence = mapper.map_regime(context)
        
        assert regime_family == "trend", \
            f"breakout should always map to trend, got {regime_family}"
        assert confidence == 0.9, \
            f"Expected confidence 0.9, got {confidence}"
    
    @given(
        liquidity_score=st.floats(min_value=0.3, max_value=1.0, allow_nan=False, allow_infinity=False)
    )
    @settings(max_examples=100)
    def test_squeeze_high_liquidity_maps_to_trend(self, liquidity_score: float):
        """
        Property 1: Regime Mapping Determinism
        
        For "squeeze" regime with liquidity_score >= 0.3, SHALL map to "trend".
        
        **Validates: Requirements 1.1**
        """
        config = RouterConfig()
        mapper = RegimeMapper(config)
        
        context = ContextVector(
            symbol="BTC-USDT",
            timestamp=0.0,
            price=50000.0,
            market_regime="squeeze",
            liquidity_score=liquidity_score,
        )
        
        regime_family, confidence = mapper.map_regime(context)
        
        assert regime_family == "trend", \
            f"squeeze with liquidity_score={liquidity_score} should map to trend, got {regime_family}"
        assert confidence == 0.7, \
            f"Expected confidence 0.7, got {confidence}"
    
    @given(
        liquidity_score=st.floats(min_value=0.0, max_value=0.299, allow_nan=False, allow_infinity=False)
    )
    @settings(max_examples=100)
    def test_squeeze_low_liquidity_maps_to_avoid(self, liquidity_score: float):
        """
        Property 1: Regime Mapping Determinism
        
        For "squeeze" regime with liquidity_score < 0.3, SHALL map to "avoid".
        
        **Validates: Requirements 1.1**
        """
        config = RouterConfig()
        mapper = RegimeMapper(config)
        
        context = ContextVector(
            symbol="BTC-USDT",
            timestamp=0.0,
            price=50000.0,
            market_regime="squeeze",
            liquidity_score=liquidity_score,
        )
        
        regime_family, confidence = mapper.map_regime(context)
        
        assert regime_family == "avoid", \
            f"squeeze with liquidity_score={liquidity_score} should map to avoid, got {regime_family}"
        assert confidence == 0.7, \
            f"Expected confidence 0.7, got {confidence}"
    
    @given(
        expected_cost_bps=st.floats(min_value=0.0, max_value=4.99, allow_nan=False, allow_infinity=False)
    )
    @settings(max_examples=100)
    def test_chop_low_cost_maps_to_mean_revert(self, expected_cost_bps: float):
        """
        Property 1: Regime Mapping Determinism
        
        For "chop" regime with expected_cost_bps < 5, SHALL map to "mean_revert".
        
        **Validates: Requirements 1.1**
        """
        config = RouterConfig()
        mapper = RegimeMapper(config)
        
        context = ContextVector(
            symbol="BTC-USDT",
            timestamp=0.0,
            price=50000.0,
            market_regime="chop",
            expected_cost_bps=expected_cost_bps,
        )
        
        regime_family, confidence = mapper.map_regime(context)
        
        assert regime_family == "mean_revert", \
            f"chop with expected_cost_bps={expected_cost_bps} should map to mean_revert, got {regime_family}"
        assert confidence == 0.5, \
            f"Expected confidence 0.5, got {confidence}"
    
    @given(
        expected_cost_bps=st.floats(min_value=5.0, max_value=50.0, allow_nan=False, allow_infinity=False)
    )
    @settings(max_examples=100)
    def test_chop_high_cost_maps_to_avoid(self, expected_cost_bps: float):
        """
        Property 1: Regime Mapping Determinism
        
        For "chop" regime with expected_cost_bps >= 5, SHALL map to "avoid".
        
        **Validates: Requirements 1.1**
        """
        config = RouterConfig()
        mapper = RegimeMapper(config)
        
        context = ContextVector(
            symbol="BTC-USDT",
            timestamp=0.0,
            price=50000.0,
            market_regime="chop",
            expected_cost_bps=expected_cost_bps,
        )
        
        regime_family, confidence = mapper.map_regime(context)
        
        assert regime_family == "avoid", \
            f"chop with expected_cost_bps={expected_cost_bps} should map to avoid, got {regime_family}"
        assert confidence == 0.8, \
            f"Expected confidence 0.8, got {confidence}"
    
    @given(context=context_vectors_with_unknown_regime())
    @settings(max_examples=100)
    def test_unknown_regime_maps_to_unknown(self, context: ContextVector):
        """
        Property 1: Regime Mapping Determinism
        
        For unknown market_regime values, SHALL map to "unknown" with low confidence.
        
        **Validates: Requirements 1.1**
        """
        config = RouterConfig()
        mapper = RegimeMapper(config)
        
        regime_family, confidence = mapper.map_regime(context)
        
        assert regime_family == "unknown", \
            f"Unknown regime '{context.market_regime}' should map to unknown, got {regime_family}"
        assert confidence == 0.3, \
            f"Expected confidence 0.3 for unknown regime, got {confidence}"


class TestRegimeMappingWithCustomConfig:
    """Tests for regime mapping with custom configuration thresholds."""
    
    @given(
        threshold=st.floats(min_value=0.001, max_value=0.01, allow_nan=False, allow_infinity=False),
        trend_strength=st.floats(min_value=0.0, max_value=0.02, allow_nan=False, allow_infinity=False)
    )
    @settings(max_examples=100)
    def test_range_mapping_respects_custom_threshold(self, threshold: float, trend_strength: float):
        """
        Property 1: Regime Mapping Determinism
        
        Range regime mapping SHALL respect custom trend_strength_for_range_to_trend threshold.
        
        **Validates: Requirements 1.1**
        """
        config = RouterConfig(trend_strength_for_range_to_trend=threshold)
        mapper = RegimeMapper(config)
        
        context = ContextVector(
            symbol="BTC-USDT",
            timestamp=0.0,
            price=50000.0,
            market_regime="range",
            trend_strength=trend_strength,
        )
        
        regime_family, _ = mapper.map_regime(context)
        
        if trend_strength > threshold:
            assert regime_family == "trend", \
                f"With threshold={threshold}, trend_strength={trend_strength} should map to trend"
        else:
            assert regime_family == "mean_revert", \
                f"With threshold={threshold}, trend_strength={trend_strength} should map to mean_revert"
    
    @given(
        threshold=st.floats(min_value=0.1, max_value=0.9, allow_nan=False, allow_infinity=False),
        liquidity_score=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False)
    )
    @settings(max_examples=100)
    def test_squeeze_mapping_respects_custom_threshold(self, threshold: float, liquidity_score: float):
        """
        Property 1: Regime Mapping Determinism
        
        Squeeze regime mapping SHALL respect custom squeeze_liquidity_threshold.
        
        **Validates: Requirements 1.1**
        """
        config = RouterConfig(squeeze_liquidity_threshold=threshold)
        mapper = RegimeMapper(config)
        
        context = ContextVector(
            symbol="BTC-USDT",
            timestamp=0.0,
            price=50000.0,
            market_regime="squeeze",
            liquidity_score=liquidity_score,
        )
        
        regime_family, _ = mapper.map_regime(context)
        
        if liquidity_score < threshold:
            assert regime_family == "avoid", \
                f"With threshold={threshold}, liquidity_score={liquidity_score} should map to avoid"
        else:
            assert regime_family == "trend", \
                f"With threshold={threshold}, liquidity_score={liquidity_score} should map to trend"
    
    @given(
        threshold=st.floats(min_value=1.0, max_value=20.0, allow_nan=False, allow_infinity=False),
        expected_cost_bps=st.floats(min_value=0.0, max_value=50.0, allow_nan=False, allow_infinity=False)
    )
    @settings(max_examples=100)
    def test_chop_mapping_respects_custom_threshold(self, threshold: float, expected_cost_bps: float):
        """
        Property 1: Regime Mapping Determinism
        
        Chop regime mapping SHALL respect custom chop_cost_threshold_bps.
        
        **Validates: Requirements 1.1**
        """
        config = RouterConfig(chop_cost_threshold_bps=threshold)
        mapper = RegimeMapper(config)
        
        context = ContextVector(
            symbol="BTC-USDT",
            timestamp=0.0,
            price=50000.0,
            market_regime="chop",
            expected_cost_bps=expected_cost_bps,
        )
        
        regime_family, _ = mapper.map_regime(context)
        
        if expected_cost_bps < threshold:
            assert regime_family == "mean_revert", \
                f"With threshold={threshold}, expected_cost_bps={expected_cost_bps} should map to mean_revert"
        else:
            assert regime_family == "avoid", \
                f"With threshold={threshold}, expected_cost_bps={expected_cost_bps} should map to avoid"


class TestRegimeMappingDetailed:
    """Tests for detailed regime mapping results."""
    
    @given(context=context_vectors_for_regime_mapping())
    @settings(max_examples=100)
    def test_detailed_mapping_includes_source_regime(self, context: ContextVector):
        """
        Property 1: Regime Mapping Determinism
        
        Detailed mapping result SHALL include the source market_regime.
        
        **Validates: Requirements 1.1**
        """
        config = RouterConfig()
        mapper = RegimeMapper(config)
        
        result = mapper.map_regime_detailed(context)
        
        assert result.source_regime == context.market_regime.lower(), \
            f"Source regime mismatch: {result.source_regime} != {context.market_regime.lower()}"
    
    @given(context=context_vectors_for_regime_mapping())
    @settings(max_examples=100)
    def test_detailed_mapping_includes_reason(self, context: ContextVector):
        """
        Property 1: Regime Mapping Determinism
        
        Detailed mapping result SHALL include a non-empty mapping reason.
        
        **Validates: Requirements 1.1**
        """
        config = RouterConfig()
        mapper = RegimeMapper(config)
        
        result = mapper.map_regime_detailed(context)
        
        assert result.mapping_reason, \
            "Mapping reason should not be empty"
        assert len(result.mapping_reason) > 0, \
            "Mapping reason should have content"


# ============================================================================
# Property 2: Soft Regime Penalty Application Tests
# ============================================================================

class TestSoftRegimePenaltyApplication:
    """
    Property 2: Soft Regime Penalty Application
    
    For any ContextVector with unknown or low-confidence regime_family, and for any
    profile that demands a specific regime family via tags (not explicit allowed_regimes),
    the profile SHALL NOT be rejected (score > 0) and SHALL have a score penalty of
    approximately 0.15 compared to a profile with no regime preference.
    
    **Feature: profile-router-v2, Property 2: Soft Regime Penalty Application**
    **Validates: Requirements 1.2, 1.3**
    """
    
    @given(context=context_vectors_with_unknown_regime())
    @settings(max_examples=100)
    def test_unknown_regime_applies_soft_penalty(self, context: ContextVector):
        """
        Property 2: Soft Regime Penalty Application
        
        For any unknown regime, profiles with tag-inferred regime preference SHALL
        receive a soft penalty (approximately 0.15) but NOT be rejected.
        
        **Validates: Requirements 1.2**
        """
        from quantgambit.deeptrader_core.profiles.component_scorer import ComponentScorer
        from quantgambit.deeptrader_core.strategies.chessboard.profile_spec import ProfileConditions
        
        config = RouterConfig()
        scorer = ComponentScorer(config)
        
        conditions = ProfileConditions()
        
        # Profile with trend tags (demands trend regime)
        trend_tags = ["trend", "momentum"]
        score_with_preference = scorer.score_regime_fit(conditions, context, trend_tags)
        
        # Profile with no regime preference
        no_preference_tags = []
        score_without_preference = scorer.score_regime_fit(conditions, context, no_preference_tags)
        
        # Score with preference should be positive (not rejected)
        assert score_with_preference > 0, \
            f"Profile with regime preference should not be rejected, got score {score_with_preference}"
        
        # Score with preference should be approximately 1.0 - 0.15 = 0.85 for unknown regime
        expected_penalty_score = 1.0 - config.regime_soft_penalty
        assert abs(score_with_preference - expected_penalty_score) < 0.01, \
            f"Expected score ~{expected_penalty_score} for unknown regime, got {score_with_preference}"
        
        # Score without preference should be neutral (0.5)
        assert score_without_preference == 0.5, \
            f"Profile without regime preference should have neutral score 0.5, got {score_without_preference}"
    
    @given(
        market_regime=valid_market_regimes,
        trend_strength=trend_strength_values,
        liquidity_score=liquidity_score_values,
        expected_cost_bps=expected_cost_bps_values,
    )
    @settings(max_examples=100)
    def test_tag_inferred_regime_is_soft_preference(
        self,
        market_regime: str,
        trend_strength: float,
        liquidity_score: float,
        expected_cost_bps: float,
    ):
        """
        Property 2: Soft Regime Penalty Application
        
        For any profile with tag-inferred regime preference (not explicit allowed_regimes),
        the profile SHALL NOT be rejected regardless of regime mismatch.
        
        **Validates: Requirements 1.3**
        """
        from quantgambit.deeptrader_core.profiles.component_scorer import ComponentScorer
        from quantgambit.deeptrader_core.strategies.chessboard.profile_spec import ProfileConditions
        
        config = RouterConfig()
        scorer = ComponentScorer(config)
        
        context = ContextVector(
            symbol="BTC-USDT",
            timestamp=0.0,
            price=50000.0,
            market_regime=market_regime,
            trend_strength=trend_strength,
            liquidity_score=liquidity_score,
            expected_cost_bps=expected_cost_bps,
        )
        
        conditions = ProfileConditions()  # No explicit allowed_regimes
        
        # Test with various tag-inferred regime preferences
        for tags in [["trend"], ["mean_reversion"], ["momentum"], ["fade"]]:
            score = scorer.score_regime_fit(conditions, context, tags)
            
            # Score should always be positive (soft preference, not rejection)
            assert score > 0, \
                f"Tag-inferred regime should not reject profile. " \
                f"Tags={tags}, regime={market_regime}, score={score}"
            
            # Score should be in valid range
            assert 0.0 <= score <= 1.0, \
                f"Score should be in [0, 1], got {score}"
    
    @given(context=context_vectors_for_regime_mapping())
    @settings(max_examples=100)
    def test_matching_regime_gets_full_score(self, context: ContextVector):
        """
        Property 2: Soft Regime Penalty Application
        
        For any profile with tag-inferred regime preference that matches the
        mapped regime_family, the profile SHALL receive full score (1.0).
        
        **Validates: Requirements 1.2, 1.3**
        """
        from quantgambit.deeptrader_core.profiles.component_scorer import ComponentScorer
        from quantgambit.deeptrader_core.strategies.chessboard.profile_spec import ProfileConditions
        
        config = RouterConfig()
        scorer = ComponentScorer(config)
        mapper = RegimeMapper(config)
        
        # Get the mapped regime family
        mapped_family, _ = mapper.map_regime(context)
        
        # Skip if unknown regime
        assume(mapped_family != "unknown")
        
        conditions = ProfileConditions()
        
        # Choose tags that match the mapped regime
        if mapped_family == "trend":
            tags = ["trend", "momentum"]
        elif mapped_family == "mean_revert":
            tags = ["mean_reversion", "fade"]
        else:  # avoid
            tags = ["avoid"]
        
        score = scorer.score_regime_fit(conditions, context, tags)
        
        assert score == 1.0, \
            f"Matching regime should get full score 1.0, got {score}. " \
            f"Mapped family={mapped_family}, tags={tags}"
    
    @given(context=context_vectors_for_regime_mapping())
    @settings(max_examples=100)
    def test_mismatched_regime_gets_penalty(self, context: ContextVector):
        """
        Property 2: Soft Regime Penalty Application
        
        For any profile with tag-inferred regime preference that does NOT match
        the mapped regime_family, the profile SHALL receive a penalty but NOT
        be rejected (score > 0).
        
        **Validates: Requirements 1.2, 1.3**
        """
        from quantgambit.deeptrader_core.profiles.component_scorer import ComponentScorer
        from quantgambit.deeptrader_core.strategies.chessboard.profile_spec import ProfileConditions
        
        config = RouterConfig()
        scorer = ComponentScorer(config)
        mapper = RegimeMapper(config)
        
        # Get the mapped regime family
        mapped_family, _ = mapper.map_regime(context)
        
        # Skip if unknown regime
        assume(mapped_family != "unknown")
        
        conditions = ProfileConditions()
        
        # Choose tags that DON'T match the mapped regime
        if mapped_family == "trend":
            tags = ["mean_reversion", "fade"]  # Opposite of trend
        elif mapped_family == "mean_revert":
            tags = ["trend", "momentum"]  # Opposite of mean_revert
        else:  # avoid
            tags = ["trend", "momentum"]  # Want to trade when should avoid
        
        score = scorer.score_regime_fit(conditions, context, tags)
        
        # Score should be positive (not rejected)
        assert score > 0, \
            f"Mismatched regime should not reject profile, got score {score}"
        
        # Score should be less than 1.0 (penalty applied)
        assert score < 1.0, \
            f"Mismatched regime should have penalty, got score {score}"


# ============================================================================
# Property 3: Explicit Regime Hard Constraint Tests
# ============================================================================

class TestExplicitRegimeHardConstraint:
    """
    Property 3: Explicit Regime Hard Constraint
    
    For any profile with explicitly specified ProfileConditions.allowed_regimes,
    and for any ContextVector where the mapped regime_family is not in allowed_regimes,
    the profile SHALL be rejected (rule_passed = False).
    
    **Feature: profile-router-v2, Property 3: Explicit Regime Hard Constraint**
    **Validates: Requirements 1.4**
    """
    
    @given(context=context_vectors_for_regime_mapping())
    @settings(max_examples=100)
    def test_explicit_allowed_regimes_is_hard_constraint(self, context: ContextVector):
        """
        Property 3: Explicit Regime Hard Constraint
        
        For any profile with explicit allowed_regimes that doesn't include the
        current regime, the profile SHALL be rejected.
        
        **Validates: Requirements 1.4**
        """
        from quantgambit.deeptrader_core.profiles.profile_router import ProfileRouter
        from quantgambit.deeptrader_core.strategies.chessboard.profile_spec import (
            ProfileSpec, ProfileConditions
        )
        
        config = RouterConfig()
        mapper = RegimeMapper(config)
        router = ProfileRouter()
        
        # Get the mapped regime family
        mapped_family, _ = mapper.map_regime(context)
        
        # Skip if unknown regime (can't test hard constraint with unknown)
        assume(mapped_family != "unknown")
        
        # Create allowed_regimes that EXCLUDES the current regime
        all_regimes = {"trend", "mean_revert", "avoid"}
        excluded_regimes = list(all_regimes - {mapped_family})
        
        # Skip if no regimes to exclude (shouldn't happen)
        assume(len(excluded_regimes) > 0)
        
        # Create profile with explicit allowed_regimes
        spec = ProfileSpec(
            id="test_explicit_regime",
            name="Test Explicit Regime",
            description="Test profile with explicit allowed_regimes",
            conditions=ProfileConditions(
                allowed_regimes=excluded_regimes,  # Explicitly excludes current regime
            ),
            tags=["test"],
        )
        
        # Update context with regime_family for the check
        context.regime_family = mapped_family
        
        passed, reasons = router._check_explicit_regime_constraint(spec, context)
        
        assert passed is False, \
            f"Profile with explicit allowed_regimes={excluded_regimes} should be rejected " \
            f"when current regime is {mapped_family}. Reasons: {reasons}"
        
        # Verify rejection reason mentions regime mismatch
        assert any("regime_mismatch" in r for r in reasons), \
            f"Rejection reasons should mention regime_mismatch: {reasons}"
    
    @given(context=context_vectors_for_regime_mapping())
    @settings(max_examples=100)
    def test_explicit_allowed_regimes_allows_matching(self, context: ContextVector):
        """
        Property 3: Explicit Regime Hard Constraint
        
        For any profile with explicit allowed_regimes that INCLUDES the current
        regime, the profile SHALL NOT be rejected.
        
        **Validates: Requirements 1.4**
        """
        from quantgambit.deeptrader_core.profiles.profile_router import ProfileRouter
        from quantgambit.deeptrader_core.strategies.chessboard.profile_spec import (
            ProfileSpec, ProfileConditions
        )
        
        config = RouterConfig()
        mapper = RegimeMapper(config)
        router = ProfileRouter()
        
        # Get the mapped regime family
        mapped_family, _ = mapper.map_regime(context)
        
        # Skip if unknown regime
        assume(mapped_family != "unknown")
        
        # Create allowed_regimes that INCLUDES the current regime
        spec = ProfileSpec(
            id="test_explicit_regime_match",
            name="Test Explicit Regime Match",
            description="Test profile with matching allowed_regimes",
            conditions=ProfileConditions(
                allowed_regimes=[mapped_family],  # Explicitly includes current regime
            ),
            tags=["test"],
        )
        
        # Update context with regime_family for the check
        context.regime_family = mapped_family
        
        passed, reasons = router._check_explicit_regime_constraint(spec, context)
        
        assert passed is True, \
            f"Profile with explicit allowed_regimes=[{mapped_family}] should pass " \
            f"when current regime is {mapped_family}. Reasons: {reasons}"
    
    @given(context=context_vectors_for_regime_mapping())
    @settings(max_examples=100)
    def test_no_explicit_allowed_regimes_always_passes(self, context: ContextVector):
        """
        Property 3: Explicit Regime Hard Constraint
        
        For any profile WITHOUT explicit allowed_regimes, the regime constraint
        check SHALL always pass (tag-inferred regimes are soft preferences).
        
        **Validates: Requirements 1.4**
        """
        from quantgambit.deeptrader_core.profiles.profile_router import ProfileRouter
        from quantgambit.deeptrader_core.strategies.chessboard.profile_spec import (
            ProfileSpec, ProfileConditions
        )
        
        router = ProfileRouter()
        
        # Create profile WITHOUT explicit allowed_regimes
        spec = ProfileSpec(
            id="test_no_explicit_regime",
            name="Test No Explicit Regime",
            description="Test profile without allowed_regimes",
            conditions=ProfileConditions(),  # No allowed_regimes
            tags=["mean_reversion"],  # Tag-inferred regime (soft preference)
        )
        
        passed, reasons = router._check_explicit_regime_constraint(spec, context)
        
        assert passed is True, \
            f"Profile without explicit allowed_regimes should always pass regime check. " \
            f"Reasons: {reasons}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
