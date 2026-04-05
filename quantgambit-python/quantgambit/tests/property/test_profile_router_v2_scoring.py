"""
Property-based tests for Profile Router v2 Component Scoring.

Feature: profile-router-v2, Properties 9-10
Validates: Requirements 4.1, 4.2, 4.3, 4.4, 5.4

Tests for:
- Property 9: Session Soft Scoring
- Property 10: Cost Viability Scoring
"""

import pytest
from hypothesis import given, strategies as st, settings, assume
from typing import List, Optional, Dict

from quantgambit.deeptrader_core.profiles.component_scorer import (
    ComponentScorer,
    SESSION_OVERLAPS,
    MEAN_REVERT_TAGS,
    MOMENTUM_TAGS,
)
from quantgambit.deeptrader_core.profiles.router_config import RouterConfig
from quantgambit.deeptrader_core.profiles.context_vector import ContextVector
from quantgambit.deeptrader_core.strategies.chessboard.profile_spec import ProfileConditions


# ============================================================================
# Hypothesis Strategies
# ============================================================================

# Session names
sessions = st.sampled_from(["asia", "europe", "us", "overnight"])

# Hour UTC values
hours_utc = st.integers(min_value=0, max_value=23)

# Symbol names
symbols = st.sampled_from(["BTC-USDT", "ETH-USDT", "SOL-USDT", "DOGE-USDT"])

# Cost values in basis points
cost_bps_values = st.floats(min_value=0.0, max_value=50.0, allow_nan=False, allow_infinity=False)

# Volatility regimes
volatility_regimes = st.sampled_from(["low", "normal", "high"])

# Profile tags
mean_revert_tags = st.sampled_from(list(MEAN_REVERT_TAGS))
momentum_tags = st.sampled_from(list(MOMENTUM_TAGS))


@st.composite
def context_vectors(draw) -> ContextVector:
    """Generate valid ContextVector instances."""
    return ContextVector(
        symbol=draw(symbols),
        timestamp=draw(st.floats(min_value=1000000000.0, max_value=2000000000.0)),
        price=draw(st.floats(min_value=100.0, max_value=100000.0)),
        session=draw(sessions),
        hour_utc=draw(hours_utc),
        expected_cost_bps=draw(cost_bps_values),
        volatility_regime=draw(volatility_regimes),
        spread_bps=draw(st.floats(min_value=0.0, max_value=30.0, allow_nan=False, allow_infinity=False)),
        bid_depth_usd=draw(st.floats(min_value=0.0, max_value=200000.0, allow_nan=False, allow_infinity=False)),
        ask_depth_usd=draw(st.floats(min_value=0.0, max_value=200000.0, allow_nan=False, allow_infinity=False)),
        trades_per_second=draw(st.floats(min_value=0.0, max_value=10.0, allow_nan=False, allow_infinity=False)),
    )


@st.composite
def profile_conditions_with_session(draw) -> ProfileConditions:
    """Generate ProfileConditions with session requirements."""
    has_required = draw(st.booleans())
    has_allowed = draw(st.booleans())
    
    required_session = draw(sessions) if has_required else None
    allowed_sessions = draw(st.lists(sessions, min_size=1, max_size=3, unique=True)) if has_allowed else None
    
    return ProfileConditions(
        required_session=required_session,
        allowed_sessions=allowed_sessions,
    )


# ============================================================================
# Property 9: Session Soft Scoring Tests
# ============================================================================

class TestSessionSoftScoring:
    """
    Property 9: Session Soft Scoring
    
    For any profile with required_session or allowed_sessions, and for any
    ContextVector with a different session, the profile SHALL NOT be rejected.
    The session_fit component SHALL be:
    - 1.0 for exact match
    - 0.7 for overlap period
    - 0.3 for non-matching session
    
    **Feature: profile-router-v2, Property 9: Session Soft Scoring**
    **Validates: Requirements 4.1, 4.2, 4.3, 4.4**
    """
    
    @given(
        session=sessions,
        hour_utc=hours_utc,
    )
    @settings(max_examples=100)
    def test_exact_session_match_returns_1_0(
        self,
        session: str,
        hour_utc: int,
    ):
        """
        Property 9: Session Soft Scoring
        
        For any exact session match, session_fit SHALL return 1.0.
        
        **Validates: Requirements 4.1**
        """
        # Use the same session for both required and context
        config = RouterConfig()
        scorer = ComponentScorer(config)
        
        conditions = ProfileConditions(required_session=session)
        context = ContextVector(
            symbol="BTC-USDT",
            timestamp=1700000000.0,
            price=50000.0,
            session=session,
            hour_utc=hour_utc,
        )
        
        score = scorer.score_session_fit(conditions, context)
        
        assert score == 1.0, \
            f"Exact session match should return 1.0, got {score}"
    
    @given(
        required_session=sessions,
        context_session=sessions,
        hour_utc=hours_utc,
    )
    @settings(max_examples=100)
    def test_non_matching_session_returns_positive_score(
        self,
        required_session: str,
        context_session: str,
        hour_utc: int,
    ):
        """
        Property 9: Session Soft Scoring
        
        For any non-matching session (without overlap), session_fit SHALL return
        a positive score (soft preference, not rejection).
        
        **Validates: Requirements 4.1**
        """
        assume(required_session != context_session)
        
        # Ensure we're not in an overlap period
        overlap_hours = SESSION_OVERLAPS.get((required_session, context_session), [])
        assume(hour_utc not in overlap_hours)
        
        config = RouterConfig()
        scorer = ComponentScorer(config)
        
        conditions = ProfileConditions(required_session=required_session)
        context = ContextVector(
            symbol="BTC-USDT",
            timestamp=1700000000.0,
            price=50000.0,
            session=context_session,
            hour_utc=hour_utc,
        )
        
        score = scorer.score_session_fit(conditions, context)
        
        # Score should be positive (not rejected) but less than 1.0
        assert score > 0.0, \
            f"Non-matching session should return positive score (soft preference), got {score}"
        assert score < 1.0, \
            f"Non-matching session should return less than 1.0, got {score}"
        assert score == 0.3, \
            f"Non-matching session should return 0.3, got {score}"
    
    @given(hour_utc=hours_utc)
    @settings(max_examples=100)
    def test_overlap_period_returns_0_7(self, hour_utc: int):
        """
        Property 9: Session Soft Scoring
        
        For any session overlap period, session_fit SHALL return 0.7.
        
        **Validates: Requirements 4.3**
        """
        # Find an overlap pair for this hour
        overlap_found = False
        for (req, curr), hours in SESSION_OVERLAPS.items():
            if hour_utc in hours:
                overlap_found = True
                required_session = req
                context_session = curr
                break
        
        assume(overlap_found)
        
        config = RouterConfig()
        scorer = ComponentScorer(config)
        
        conditions = ProfileConditions(required_session=required_session)
        context = ContextVector(
            symbol="BTC-USDT",
            timestamp=1700000000.0,
            price=50000.0,
            session=context_session,
            hour_utc=hour_utc,
        )
        
        score = scorer.score_session_fit(conditions, context)
        
        assert score == 0.7, \
            f"Overlap period should return 0.7, got {score} " \
            f"(required={required_session}, current={context_session}, hour={hour_utc})"
    
    @given(
        allowed_sessions=st.lists(sessions, min_size=1, max_size=3, unique=True),
        context_session=sessions,
        hour_utc=hours_utc,
    )
    @settings(max_examples=100)
    def test_allowed_sessions_match_returns_0_8(
        self,
        allowed_sessions: List[str],
        context_session: str,
        hour_utc: int,
    ):
        """
        Property 9: Session Soft Scoring
        
        For any match with allowed_sessions, session_fit SHALL return at least 0.8.
        
        **Validates: Requirements 4.2**
        """
        assume(context_session in allowed_sessions)
        
        config = RouterConfig()
        scorer = ComponentScorer(config)
        
        conditions = ProfileConditions(allowed_sessions=allowed_sessions)
        context = ContextVector(
            symbol="BTC-USDT",
            timestamp=1700000000.0,
            price=50000.0,
            session=context_session,
            hour_utc=hour_utc,
        )
        
        score = scorer.score_session_fit(conditions, context)
        
        assert score >= 0.8, \
            f"Allowed sessions match should return at least 0.8, got {score}"
    
    @given(hour_utc=hours_utc)
    @settings(max_examples=100)
    def test_no_session_requirements_returns_neutral(self, hour_utc: int):
        """
        Property 9: Session Soft Scoring
        
        For any profile with no session requirements, session_fit SHALL return 0.5 (neutral).
        
        **Validates: Requirements 4.1**
        """
        config = RouterConfig()
        scorer = ComponentScorer(config)
        
        conditions = ProfileConditions()  # No session requirements
        context = ContextVector(
            symbol="BTC-USDT",
            timestamp=1700000000.0,
            price=50000.0,
            session="us",
            hour_utc=hour_utc,
        )
        
        score = scorer.score_session_fit(conditions, context)
        
        assert score == 0.5, \
            f"No session requirements should return 0.5 (neutral), got {score}"
    
    @given(
        required_session=sessions,
        context_session=sessions,
        hour_utc=hours_utc,
    )
    @settings(max_examples=100)
    def test_session_score_always_in_valid_range(
        self,
        required_session: str,
        context_session: str,
        hour_utc: int,
    ):
        """
        Property 9: Session Soft Scoring
        
        For any inputs, session_fit SHALL return a value in [0, 1].
        
        **Validates: Requirements 4.1, 4.2, 4.3, 4.4**
        """
        config = RouterConfig()
        scorer = ComponentScorer(config)
        
        conditions = ProfileConditions(required_session=required_session)
        context = ContextVector(
            symbol="BTC-USDT",
            timestamp=1700000000.0,
            price=50000.0,
            session=context_session,
            hour_utc=hour_utc,
        )
        
        score = scorer.score_session_fit(conditions, context)
        
        assert 0.0 <= score <= 1.0, \
            f"Session score should be in [0, 1], got {score}"


# ============================================================================
# Property 10: Cost Viability Scoring Tests
# ============================================================================

class TestCostViabilityScoring:
    """
    Property 10: Cost Viability Scoring
    
    For any profile and ContextVector, the cost_viability_fit component SHALL equal
    max(0, 1 - (expected_cost_bps / max_viable_cost_bps)), where max_viable_cost_bps
    is 8 for mean-reversion profiles and 15 for momentum profiles.
    
    **Feature: profile-router-v2, Property 10: Cost Viability Scoring**
    **Validates: Requirements 5.4**
    """
    
    @given(expected_cost_bps=cost_bps_values)
    @settings(max_examples=100)
    def test_mean_revert_profile_cost_formula(self, expected_cost_bps: float):
        """
        Property 10: Cost Viability Scoring
        
        For any mean-reversion profile, cost_viability_fit SHALL equal
        max(0, 1 - (expected_cost_bps / 8)).
        
        **Validates: Requirements 5.4**
        """
        config = RouterConfig()
        scorer = ComponentScorer(config)
        
        conditions = ProfileConditions()
        context = ContextVector(
            symbol="BTC-USDT",
            timestamp=1700000000.0,
            price=50000.0,
            expected_cost_bps=expected_cost_bps,
        )
        
        # Use mean-reversion tag
        tags = ["mean_reversion"]
        
        score = scorer.score_cost_viability_fit(conditions, context, tags)
        
        # Expected formula: max(0, 1 - (cost / 8))
        max_viable_cost = 8.0
        
        # Hard rejection at 2x threshold
        if expected_cost_bps >= 2 * max_viable_cost:
            expected_score = 0.0
        else:
            expected_score = max(0.0, 1.0 - (expected_cost_bps / max_viable_cost))
        
        assert abs(score - expected_score) < 0.001, \
            f"Mean-revert cost score mismatch: got {score}, expected {expected_score} " \
            f"(cost={expected_cost_bps})"
    
    @given(
        expected_cost_bps=cost_bps_values,
        volatility_regime=volatility_regimes,
    )
    @settings(max_examples=100)
    def test_momentum_profile_cost_formula(
        self,
        expected_cost_bps: float,
        volatility_regime: str,
    ):
        """
        Property 10: Cost Viability Scoring
        
        For any momentum profile, cost_viability_fit SHALL equal
        max(0, 1 - (expected_cost_bps / max_viable_cost)), where max_viable_cost
        is 15 in high volatility and 12 otherwise.
        
        **Validates: Requirements 5.4**
        """
        config = RouterConfig()
        scorer = ComponentScorer(config)
        
        conditions = ProfileConditions()
        context = ContextVector(
            symbol="BTC-USDT",
            timestamp=1700000000.0,
            price=50000.0,
            expected_cost_bps=expected_cost_bps,
            volatility_regime=volatility_regime,
        )
        
        # Use momentum tag
        tags = ["momentum"]
        
        score = scorer.score_cost_viability_fit(conditions, context, tags)
        
        # Expected formula depends on volatility
        if volatility_regime == "high":
            max_viable_cost = 15.0
        else:
            max_viable_cost = 12.0
        
        # Hard rejection at 2x threshold
        if expected_cost_bps >= 2 * max_viable_cost:
            expected_score = 0.0
        else:
            expected_score = max(0.0, 1.0 - (expected_cost_bps / max_viable_cost))
        
        assert abs(score - expected_score) < 0.001, \
            f"Momentum cost score mismatch: got {score}, expected {expected_score} " \
            f"(cost={expected_cost_bps}, vol={volatility_regime})"
    
    @given(expected_cost_bps=st.floats(min_value=16.0, max_value=50.0, allow_nan=False, allow_infinity=False))
    @settings(max_examples=100)
    def test_hard_rejection_at_2x_threshold_mean_revert(self, expected_cost_bps: float):
        """
        Property 10: Cost Viability Scoring
        
        For any mean-reversion profile where expected_cost_bps >= 2 * 8 = 16,
        cost_viability_fit SHALL return 0.0 (hard rejection).
        
        **Validates: Requirements 5.5**
        """
        config = RouterConfig()
        scorer = ComponentScorer(config)
        
        conditions = ProfileConditions()
        context = ContextVector(
            symbol="BTC-USDT",
            timestamp=1700000000.0,
            price=50000.0,
            expected_cost_bps=expected_cost_bps,
        )
        
        tags = ["mean_reversion"]
        
        score = scorer.score_cost_viability_fit(conditions, context, tags)
        
        assert score == 0.0, \
            f"Cost >= 2x threshold should return 0.0, got {score} (cost={expected_cost_bps})"
    
    @given(expected_cost_bps=st.floats(min_value=0.0, max_value=8.0, allow_nan=False, allow_infinity=False))
    @settings(max_examples=100)
    def test_cost_score_decreases_with_cost(self, expected_cost_bps: float):
        """
        Property 10: Cost Viability Scoring
        
        For any profile, cost_viability_fit SHALL decrease as expected_cost_bps increases.
        
        **Validates: Requirements 5.4**
        """
        config = RouterConfig()
        scorer = ComponentScorer(config)
        
        conditions = ProfileConditions()
        tags = ["mean_reversion"]
        
        # Test with two different costs
        context_low = ContextVector(
            symbol="BTC-USDT",
            timestamp=1700000000.0,
            price=50000.0,
            expected_cost_bps=expected_cost_bps,
        )
        
        context_high = ContextVector(
            symbol="BTC-USDT",
            timestamp=1700000000.0,
            price=50000.0,
            expected_cost_bps=expected_cost_bps + 2.0,  # Higher cost
        )
        
        score_low = scorer.score_cost_viability_fit(conditions, context_low, tags)
        score_high = scorer.score_cost_viability_fit(conditions, context_high, tags)
        
        assert score_low >= score_high, \
            f"Higher cost should result in lower or equal score: " \
            f"score_low={score_low}, score_high={score_high}"
    
    @given(expected_cost_bps=cost_bps_values)
    @settings(max_examples=100)
    def test_cost_score_always_in_valid_range(self, expected_cost_bps: float):
        """
        Property 10: Cost Viability Scoring
        
        For any inputs, cost_viability_fit SHALL return a value in [0, 1].
        
        **Validates: Requirements 5.4**
        """
        config = RouterConfig()
        scorer = ComponentScorer(config)
        
        conditions = ProfileConditions()
        context = ContextVector(
            symbol="BTC-USDT",
            timestamp=1700000000.0,
            price=50000.0,
            expected_cost_bps=expected_cost_bps,
        )
        
        # Test with various tag combinations
        for tags in [[], ["mean_reversion"], ["momentum"], ["trend"]]:
            score = scorer.score_cost_viability_fit(conditions, context, tags)
            
            assert 0.0 <= score <= 1.0, \
                f"Cost score should be in [0, 1], got {score} (tags={tags})"
    
    @given(expected_cost_bps=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False))
    @settings(max_examples=100)
    def test_zero_cost_returns_near_1_0(self, expected_cost_bps: float):
        """
        Property 10: Cost Viability Scoring
        
        For any profile with very low expected_cost_bps, cost_viability_fit
        SHALL return a value close to 1.0.
        
        **Validates: Requirements 5.4**
        """
        config = RouterConfig()
        scorer = ComponentScorer(config)
        
        conditions = ProfileConditions()
        context = ContextVector(
            symbol="BTC-USDT",
            timestamp=1700000000.0,
            price=50000.0,
            expected_cost_bps=expected_cost_bps,
        )
        
        tags = ["mean_reversion"]
        
        score = scorer.score_cost_viability_fit(conditions, context, tags)
        
        # With cost <= 1 bps and max_viable = 8, score should be >= 0.875
        assert score >= 0.875, \
            f"Very low cost should return high score, got {score} (cost={expected_cost_bps})"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


# ============================================================================
# Property 12: Weighted Score Computation Tests
# ============================================================================

from quantgambit.deeptrader_core.profiles.weighted_score_aggregator import (
    WeightedScoreAggregator,
    clamp_score,
)


class TestWeightedScoreComputation:
    """
    Property 12: Weighted Score Computation
    
    For any profile that passes hard filters, the final score SHALL equal the
    weighted sum of component scores:
    score = Σ(weight_i × component_score_i) for all components
    
    Where weights sum to 1.0 and each component_score is in [0, 1].
    
    **Feature: profile-router-v2, Property 12: Weighted Score Computation**
    **Validates: Requirements 6.1, 6.2**
    """
    
    @given(
        trend_fit=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
        vol_fit=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
        value_fit=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
        microstructure_fit=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
        rotation_fit=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
        session_fit=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
        cost_viability_fit=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=100)
    def test_weighted_sum_equals_manual_calculation(
        self,
        trend_fit: float,
        vol_fit: float,
        value_fit: float,
        microstructure_fit: float,
        rotation_fit: float,
        session_fit: float,
        cost_viability_fit: float,
    ):
        """
        Property 12: Weighted Score Computation
        
        For any set of component scores, the final score SHALL equal the
        weighted sum using default weights.
        
        **Validates: Requirements 6.1, 6.2**
        """
        config = RouterConfig()
        aggregator = WeightedScoreAggregator(config)
        
        component_scores = {
            'trend_fit': trend_fit,
            'vol_fit': vol_fit,
            'value_fit': value_fit,
            'microstructure_fit': microstructure_fit,
            'rotation_fit': rotation_fit,
            'session_fit': session_fit,
            'cost_viability_fit': cost_viability_fit,
        }
        
        # Compute using aggregator
        final_score = aggregator.aggregate_scores(component_scores)
        
        # Compute manually
        weights = config.component_weights
        expected_score = sum(
            weights[comp] * score
            for comp, score in component_scores.items()
        )
        expected_score = max(0.0, min(1.0, expected_score))
        
        assert abs(final_score - expected_score) < 0.0001, \
            f"Weighted score mismatch: got {final_score}, expected {expected_score}"
    
    @given(context_vectors())
    @settings(max_examples=100)
    def test_full_pipeline_produces_valid_breakdown(self, context: ContextVector):
        """
        Property 12: Weighted Score Computation
        
        For any context, the full scoring pipeline SHALL produce a valid
        breakdown with all components and weighted contributions.
        
        **Validates: Requirements 6.1, 6.2**
        """
        config = RouterConfig()
        aggregator = WeightedScoreAggregator(config)
        
        conditions = ProfileConditions()
        
        result = aggregator.compute_weighted_score(
            conditions=conditions,
            context=context,
            profile_tags=["trend"],
        )
        
        # Verify all expected keys are present
        assert 'final_score' in result
        assert 'component_scores' in result
        assert 'weighted_contributions' in result
        assert 'weights_used' in result
        
        # Verify all components are scored
        expected_components = {
            'trend_fit', 'vol_fit', 'value_fit', 'microstructure_fit',
            'rotation_fit', 'session_fit', 'cost_viability_fit', 'regime_fit'
        }
        assert set(result['component_scores'].keys()) == expected_components
        
        # Verify final score matches sum of contributions
        total_contribution = sum(result['weighted_contributions'].values())
        assert abs(result['final_score'] - max(0.0, min(1.0, total_contribution))) < 0.0001
    
    @given(
        weights=st.fixed_dictionaries({
            'trend_fit': st.floats(min_value=0.05, max_value=0.5, allow_nan=False, allow_infinity=False),
            'vol_fit': st.floats(min_value=0.05, max_value=0.5, allow_nan=False, allow_infinity=False),
            'value_fit': st.floats(min_value=0.05, max_value=0.5, allow_nan=False, allow_infinity=False),
            'microstructure_fit': st.floats(min_value=0.05, max_value=0.5, allow_nan=False, allow_infinity=False),
            'rotation_fit': st.floats(min_value=0.05, max_value=0.5, allow_nan=False, allow_infinity=False),
            'session_fit': st.floats(min_value=0.05, max_value=0.5, allow_nan=False, allow_infinity=False),
            'cost_viability_fit': st.floats(min_value=0.05, max_value=0.5, allow_nan=False, allow_infinity=False),
            'regime_fit': st.floats(min_value=0.05, max_value=0.5, allow_nan=False, allow_infinity=False),
        }),
    )
    @settings(max_examples=100)
    def test_custom_weights_are_applied(self, weights: Dict[str, float]):
        """
        Property 12: Weighted Score Computation
        
        For any custom weights, the aggregator SHALL use those weights
        instead of default config weights.
        
        **Validates: Requirements 6.2**
        """
        # Normalize weights to sum to 1.0
        total = sum(weights.values())
        normalized_weights = {k: v / total for k, v in weights.items()}
        
        config = RouterConfig()
        aggregator = WeightedScoreAggregator(config)
        
        # All scores at 1.0 - final should equal sum of weights (1.0)
        component_scores = {comp: 1.0 for comp in normalized_weights.keys()}
        
        final_score = aggregator.aggregate_scores(component_scores, normalized_weights)
        
        # With all scores at 1.0 and weights summing to 1.0, result should be 1.0
        assert abs(final_score - 1.0) < 0.001, \
            f"With all scores=1.0 and normalized weights, final should be 1.0, got {final_score}"
    
    @given(context_vectors())
    @settings(max_examples=100)
    def test_weights_sum_to_one_in_default_config(self, context: ContextVector):
        """
        Property 12: Weighted Score Computation
        
        The default config weights SHALL sum to 1.0.
        
        **Validates: Requirements 6.2**
        """
        config = RouterConfig()
        
        total_weight = sum(config.component_weights.values())
        
        assert abs(total_weight - 1.0) < 0.001, \
            f"Default weights should sum to 1.0, got {total_weight}"


# ============================================================================
# Property 13: Score Clamping Tests
# ============================================================================

class TestScoreClamping:
    """
    Property 13: Score Clamping
    
    For any computed score (before or after performance adjustment), the final
    score SHALL be clamped to [0.0, 1.0].
    
    **Feature: profile-router-v2, Property 13: Score Clamping**
    **Validates: Requirements 6.5**
    """
    
    @given(score=st.floats(min_value=-100.0, max_value=100.0, allow_nan=False, allow_infinity=False))
    @settings(max_examples=100)
    def test_clamp_score_utility_function(self, score: float):
        """
        Property 13: Score Clamping
        
        The clamp_score utility function SHALL always return a value in [0.0, 1.0].
        
        **Validates: Requirements 6.5**
        """
        clamped = clamp_score(score)
        
        assert 0.0 <= clamped <= 1.0, \
            f"Clamped score should be in [0.0, 1.0], got {clamped} from input {score}"
        
        # Verify clamping behavior
        if score < 0.0:
            assert clamped == 0.0
        elif score > 1.0:
            assert clamped == 1.0
        else:
            assert clamped == score
    
    @given(
        scores=st.lists(
            st.floats(min_value=0.0, max_value=2.0, allow_nan=False, allow_infinity=False),
            min_size=7,
            max_size=7,
        ),
    )
    @settings(max_examples=100)
    def test_aggregate_scores_clamps_result(self, scores: List[float]):
        """
        Property 13: Score Clamping
        
        The aggregate_scores method SHALL clamp the final result to [0.0, 1.0]
        even when component scores exceed 1.0.
        
        **Validates: Requirements 6.5**
        """
        config = RouterConfig()
        aggregator = WeightedScoreAggregator(config)
        
        component_names = [
            'trend_fit', 'vol_fit', 'value_fit', 'microstructure_fit',
            'rotation_fit', 'session_fit', 'cost_viability_fit'
        ]
        component_scores = dict(zip(component_names, scores))
        
        final_score = aggregator.aggregate_scores(component_scores)
        
        assert 0.0 <= final_score <= 1.0, \
            f"Final score should be clamped to [0.0, 1.0], got {final_score}"
    
    @given(context_vectors())
    @settings(max_examples=100)
    def test_compute_weighted_score_clamps_result(self, context: ContextVector):
        """
        Property 13: Score Clamping
        
        The compute_weighted_score method SHALL always return a final_score
        in [0.0, 1.0].
        
        **Validates: Requirements 6.5**
        """
        config = RouterConfig()
        aggregator = WeightedScoreAggregator(config)
        
        conditions = ProfileConditions()
        
        result = aggregator.compute_weighted_score(
            conditions=conditions,
            context=context,
            profile_tags=["momentum"],
        )
        
        assert 0.0 <= result['final_score'] <= 1.0, \
            f"Final score should be in [0.0, 1.0], got {result['final_score']}"
    
    @given(
        trend_fit=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
        vol_fit=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
        value_fit=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
        microstructure_fit=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
        rotation_fit=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
        session_fit=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
        cost_viability_fit=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=100)
    def test_valid_component_scores_produce_valid_final_score(
        self,
        trend_fit: float,
        vol_fit: float,
        value_fit: float,
        microstructure_fit: float,
        rotation_fit: float,
        session_fit: float,
        cost_viability_fit: float,
    ):
        """
        Property 13: Score Clamping
        
        For any valid component scores (all in [0, 1]), the final score
        SHALL also be in [0.0, 1.0].
        
        **Validates: Requirements 6.5**
        """
        config = RouterConfig()
        aggregator = WeightedScoreAggregator(config)
        
        component_scores = {
            'trend_fit': trend_fit,
            'vol_fit': vol_fit,
            'value_fit': value_fit,
            'microstructure_fit': microstructure_fit,
            'rotation_fit': rotation_fit,
            'session_fit': session_fit,
            'cost_viability_fit': cost_viability_fit,
        }
        
        final_score = aggregator.aggregate_scores(component_scores)
        
        assert 0.0 <= final_score <= 1.0, \
            f"Final score should be in [0.0, 1.0], got {final_score}"
    
    @given(
        negative_score=st.floats(min_value=-100.0, max_value=-0.001, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=100)
    def test_negative_scores_clamped_to_zero(self, negative_score: float):
        """
        Property 13: Score Clamping
        
        Any negative score SHALL be clamped to 0.0.
        
        **Validates: Requirements 6.5**
        """
        clamped = clamp_score(negative_score)
        
        assert clamped == 0.0, \
            f"Negative score {negative_score} should be clamped to 0.0, got {clamped}"
    
    @given(
        high_score=st.floats(min_value=1.001, max_value=100.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=100)
    def test_scores_above_one_clamped_to_one(self, high_score: float):
        """
        Property 13: Score Clamping
        
        Any score above 1.0 SHALL be clamped to 1.0.
        
        **Validates: Requirements 6.5**
        """
        clamped = clamp_score(high_score)
        
        assert clamped == 1.0, \
            f"Score {high_score} above 1.0 should be clamped to 1.0, got {clamped}"
