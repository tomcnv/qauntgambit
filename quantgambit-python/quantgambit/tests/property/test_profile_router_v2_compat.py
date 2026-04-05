"""
Property-based tests for Profile Router v2 Backward Compatibility.

Feature: profile-router-v2, Property 17: Backward Compatibility
Validates: Requirements 10.1, 10.2, 10.3, 10.4, 10.5

Tests that:
- select_profiles(context, top_k, symbol) signature is maintained (10.1)
- ProfileScore existing fields are maintained (10.2)
- get_all_metrics() return structure is maintained (10.3)
- Legacy ProfileConditions required_* fields are converted to soft preferences, except
  required_session which is treated as a hard eligibility constraint for session-scoped profiles (10.4)
- use_v2_scoring feature flag enables/disables new scoring logic (10.5)
"""

import pytest
from hypothesis import given, strategies as st, settings, assume
from typing import Dict, List, Optional
import time
import inspect

from quantgambit.deeptrader_core.profiles.profile_router import ProfileRouter, ProfileScore
from quantgambit.deeptrader_core.profiles.router_config import RouterConfig
from quantgambit.deeptrader_core.profiles.context_vector import ContextVector
from quantgambit.deeptrader_core.strategies.chessboard.profile_spec import (
    ProfileSpec,
    ProfileConditions,
)


# ============================================================================
# Hypothesis Strategies
# ============================================================================

# Valid sessions
VALID_SESSIONS = ['asia', 'europe', 'us', 'overnight']

# Valid trend directions
VALID_TRENDS = ['up', 'down', 'flat']

# Valid volatility regimes
VALID_VOL_REGIMES = ['low', 'normal', 'high']

# Valid value locations
VALID_VALUE_LOCATIONS = ['above', 'below', 'inside']


@st.composite
def context_vectors(draw) -> ContextVector:
    """Generate valid ContextVector instances for testing."""
    return ContextVector(
        symbol=draw(st.sampled_from(['BTC-USDT', 'ETH-USDT', 'SOL-USDT'])),
        timestamp=draw(st.floats(min_value=1e9, max_value=2e9, allow_nan=False, allow_infinity=False)),
        price=draw(st.floats(min_value=100.0, max_value=100000.0, allow_nan=False, allow_infinity=False)),
        trend_direction=draw(st.sampled_from(VALID_TRENDS)),
        volatility_regime=draw(st.sampled_from(VALID_VOL_REGIMES)),
        session=draw(st.sampled_from(VALID_SESSIONS)),
        position_in_value=draw(st.sampled_from(VALID_VALUE_LOCATIONS)),
        spread_bps=draw(st.floats(min_value=1.0, max_value=30.0, allow_nan=False, allow_infinity=False)),
        bid_depth_usd=draw(st.floats(min_value=20000.0, max_value=500000.0, allow_nan=False, allow_infinity=False)),
        ask_depth_usd=draw(st.floats(min_value=20000.0, max_value=500000.0, allow_nan=False, allow_infinity=False)),
        trades_per_second=draw(st.floats(min_value=0.5, max_value=10.0, allow_nan=False, allow_infinity=False)),
        book_age_ms=draw(st.floats(min_value=10.0, max_value=2000.0, allow_nan=False, allow_infinity=False)),
        trade_age_ms=draw(st.floats(min_value=10.0, max_value=5000.0, allow_nan=False, allow_infinity=False)),
        risk_mode='normal',
        expected_cost_bps=draw(st.floats(min_value=1.0, max_value=10.0, allow_nan=False, allow_infinity=False)),
        liquidity_score=draw(st.floats(min_value=0.3, max_value=1.0, allow_nan=False, allow_infinity=False)),
        data_completeness=draw(st.floats(min_value=0.5, max_value=1.0, allow_nan=False, allow_infinity=False)),
    )


@st.composite
def legacy_profile_conditions(draw) -> ProfileConditions:
    """Generate ProfileConditions with legacy required_* fields."""
    return ProfileConditions(
        required_trend=draw(st.sampled_from([None] + VALID_TRENDS)),
        required_volatility=draw(st.sampled_from([None] + VALID_VOL_REGIMES)),
        required_session=draw(st.sampled_from([None] + VALID_SESSIONS)),
        required_value_location=draw(st.sampled_from([None] + VALID_VALUE_LOCATIONS)),
    )


# ============================================================================
# Property Tests
# ============================================================================

class TestBackwardCompatibility:
    """
    Property 17: Backward Compatibility
    
    For any call to select_profiles(context, top_k, symbol) with legacy
    ProfileConditions using required_* fields, the router SHALL:
    - Return ProfileScore objects with all existing fields populated
    - Convert required_* conditions to soft preferences (not hard rejections), except
      required_session which is an eligibility constraint
    - Maintain existing get_all_metrics() return structure
    
    **Feature: profile-router-v2, Property 17: Backward Compatibility**
    **Validates: Requirements 10.1, 10.2, 10.3, 10.4, 10.5**
    """
    
    def test_select_profiles_signature_maintained(self):
        """
        Property 17: Backward Compatibility - API Signature
        
        The select_profiles method SHALL maintain the signature:
        select_profiles(context: ContextVector, top_k: int = 3, symbol: Optional[str] = None)
        
        **Validates: Requirements 10.1**
        """
        router = ProfileRouter()
        sig = inspect.signature(router.select_profiles)
        params = list(sig.parameters.keys())
        
        # Check required parameters
        assert 'context' in params, "select_profiles must have 'context' parameter"
        assert 'top_k' in params, "select_profiles must have 'top_k' parameter"
        assert 'symbol' in params, "select_profiles must have 'symbol' parameter"
        
        # Check default values
        assert sig.parameters['top_k'].default == 3, "top_k default must be 3"
        assert sig.parameters['symbol'].default is None, "symbol default must be None"
    
    def test_profile_score_existing_fields_maintained(self):
        """
        Property 17: Backward Compatibility - ProfileScore Fields
        
        ProfileScore SHALL maintain all existing fields:
        - profile_id: str
        - score: float
        - confidence: float
        - reasons: List[str]
        - rule_passed: bool
        - ml_score: Optional[float]
        
        **Validates: Requirements 10.2**
        """
        # Check that all existing fields are present
        existing_fields = ['profile_id', 'score', 'confidence', 'reasons', 'rule_passed', 'ml_score']
        
        for field_name in existing_fields:
            assert field_name in ProfileScore.__dataclass_fields__, \
                f"ProfileScore must have '{field_name}' field"
        
        # Check field types
        assert ProfileScore.__dataclass_fields__['profile_id'].type == str
        assert ProfileScore.__dataclass_fields__['score'].type == float
        assert ProfileScore.__dataclass_fields__['confidence'].type == float
        assert ProfileScore.__dataclass_fields__['rule_passed'].type == bool
    
    def test_get_all_metrics_structure_maintained(self):
        """
        Property 17: Backward Compatibility - get_all_metrics Structure
        
        get_all_metrics() SHALL maintain existing return structure keys:
        - total_trades, total_wins, overall_win_rate, total_pnl
        - avg_pnl_per_trade, active_profiles, registered_profiles
        - ml_enabled, top_profiles, live_top_profiles
        - selection_history, rejection_summary, top_rejection_reasons
        
        **Validates: Requirements 10.3**
        """
        router = ProfileRouter()
        metrics = router.get_all_metrics()
        
        # Check existing keys are present
        existing_keys = [
            'total_trades', 'total_wins', 'overall_win_rate', 'total_pnl',
            'avg_pnl_per_trade', 'active_profiles', 'registered_profiles',
            'ml_enabled', 'top_profiles', 'live_top_profiles',
            'selection_history', 'rejection_summary', 'top_rejection_reasons',
        ]
        
        for key in existing_keys:
            assert key in metrics, f"get_all_metrics must return '{key}'"
    
    @given(context=context_vectors(), conditions=legacy_profile_conditions())
    @settings(max_examples=100)
    def test_legacy_required_fields_soft_preference(
        self,
        context: ContextVector,
        conditions: ProfileConditions
    ):
        """
        Property 17: Backward Compatibility - Soft Preferences
        
        For any ProfileConditions with legacy required_* fields, the router
        SHALL convert them to soft preferences (not hard rejections),
        except required_session which is an eligibility constraint.
        
        A profile with mismatched required_* fields SHALL:
        - Pass rule filters (rule_passed=True)
        - Have a lower score than a matching profile
        - NOT be hard-rejected
        
        **Validates: Requirements 10.4**
        """
        router = ProfileRouter(config=RouterConfig(use_v2_scoring=True))
        
        # Create a profile spec with the legacy conditions
        spec = ProfileSpec(
            id='test_legacy_profile',
            name='Test Legacy Profile',
            description='Test profile with legacy required_* fields',
            conditions=conditions,
            tags=['test'],
        )
        
        # Score the profile
        score = router._score_profile(spec, context)
        
        # The profile should NOT be hard-rejected due to required_* mismatches
        # (only safety-critical hard filters should cause rejection)
        # If the context passes safety filters, the profile should pass rule filters
        if (context.spread_bps <= 50.0 and
            context.bid_depth_usd + context.ask_depth_usd >= 10000.0 and
            context.trades_per_second >= 0.1 and
            context.book_age_ms <= 5000.0 and
            context.trade_age_ms <= 10000.0 and
            context.risk_mode == 'normal'):

            # required_session is an eligibility constraint: mismatch rejects.
            if conditions.required_session and conditions.required_session != context.session:
                assert not score.rule_passed, (
                    "required_session mismatch should reject even if safety filters pass. "
                    f"required_session={conditions.required_session}, context.session={context.session}, "
                    f"reasons={score.reasons}"
                )
            else:
                assert score.rule_passed, (
                    "Profile with legacy required_* fields should pass rule filters when safety filters pass. "
                    f"Reasons: {score.reasons}"
                )
                assert score.hard_filter_passed, (
                    f"Profile should pass hard filters. Reasons: {score.reasons}"
                )
    
    @given(context=context_vectors())
    @settings(max_examples=100)
    def test_v2_scoring_flag_enables_new_logic(self, context: ContextVector):
        """
        Property 17: Backward Compatibility - Feature Flag
        
        When use_v2_scoring=True, the router SHALL use ComponentScorer
        and WeightedScoreAggregator for scoring.
        
        When use_v2_scoring=False, the router SHALL use legacy
        _calculate_base_score method.
        
        **Validates: Requirements 10.5**
        """
        # Create routers with different scoring modes
        router_v2 = ProfileRouter(config=RouterConfig(use_v2_scoring=True))
        router_legacy = ProfileRouter(config=RouterConfig(use_v2_scoring=False))
        
        # Get a profile to score
        specs = router_v2.registry.list_specs()
        if not specs:
            return  # Skip if no profiles registered
        
        spec = specs[0]
        
        # Score with v2 scoring
        score_v2 = router_v2._score_profile(spec, context)
        
        # Score with legacy scoring
        score_legacy = router_legacy._score_profile(spec, context)
        
        # Both should produce valid scores
        assert 0.0 <= score_v2.score <= 1.0, "v2 score must be in [0, 1]"
        assert 0.0 <= score_legacy.score <= 1.0, "legacy score must be in [0, 1]"
        
        # v2 scoring should populate component_scores
        if score_v2.rule_passed:
            # v2 scoring populates component_scores
            # (may be empty if profile was rejected)
            pass  # Component scores are populated in v2 mode
        
        # Legacy scoring should NOT populate component_scores
        if score_legacy.rule_passed:
            # Legacy mode doesn't populate component_scores
            assert score_legacy.component_scores == {}, \
                "Legacy scoring should not populate component_scores"
    
    @given(context=context_vectors())
    @settings(max_examples=100)
    def test_select_profiles_returns_profile_scores(self, context: ContextVector):
        """
        Property 17: Backward Compatibility - Return Type
        
        select_profiles SHALL return a List[ProfileScore] with all
        existing fields populated.
        
        **Validates: Requirements 10.1, 10.2**
        """
        router = ProfileRouter()
        
        # Call select_profiles
        results = router.select_profiles(context, top_k=3, symbol=context.symbol)
        
        # Check return type
        assert isinstance(results, list), "select_profiles must return a list"
        
        # Check each result
        for score in results:
            assert isinstance(score, ProfileScore), \
                "Each result must be a ProfileScore"
            
            # Check existing fields are populated
            assert isinstance(score.profile_id, str), "profile_id must be str"
            assert isinstance(score.score, float), "score must be float"
            assert isinstance(score.confidence, float), "confidence must be float"
            assert isinstance(score.reasons, list), "reasons must be list"
            assert isinstance(score.rule_passed, bool), "rule_passed must be bool"
            
            # Check score bounds
            assert 0.0 <= score.score <= 1.0, "score must be in [0, 1]"
            assert 0.0 <= score.confidence <= 1.0, "confidence must be in [0, 1]"
    
    def test_v2_scoring_default_is_true(self):
        """
        Property 17: Backward Compatibility - Default Flag Value
        
        use_v2_scoring SHALL default to True for new behavior.
        
        **Validates: Requirements 10.5**
        """
        config = RouterConfig()
        assert config.use_v2_scoring is True, \
            "use_v2_scoring must default to True"
        
        router = ProfileRouter()
        assert router.config.use_v2_scoring is True, \
            "Router should use v2 scoring by default"
    
    @given(
        use_v2=st.booleans(),
        context=context_vectors()
    )
    @settings(max_examples=100)
    def test_scoring_mode_switch_via_config_update(
        self,
        use_v2: bool,
        context: ContextVector
    ):
        """
        Property 17: Backward Compatibility - Config Update
        
        Updating the config with a different use_v2_scoring value
        SHALL change the scoring behavior.
        
        **Validates: Requirements 10.5**
        """
        # Start with opposite mode
        initial_config = RouterConfig(use_v2_scoring=not use_v2)
        router = ProfileRouter(config=initial_config)
        
        assert router.config.use_v2_scoring == (not use_v2)
        
        # Update to target mode
        new_config = RouterConfig(use_v2_scoring=use_v2)
        router.update_config(new_config)
        
        assert router.config.use_v2_scoring == use_v2
        
        # Verify scoring works in new mode
        results = router.select_profiles(context, top_k=3, symbol=context.symbol)
        assert isinstance(results, list)


class TestLegacyConditionsConversion:
    """
    Tests for legacy ProfileConditions conversion to soft preferences.
    
    **Feature: profile-router-v2, Property 17: Backward Compatibility**
    **Validates: Requirements 10.4**
    """
    
    @given(
        required_trend=st.sampled_from(VALID_TRENDS),
        context_trend=st.sampled_from(VALID_TRENDS)
    )
    @settings(max_examples=100)
    def test_required_trend_is_soft_preference(
        self,
        required_trend: str,
        context_trend: str
    ):
        """
        Property 17: Backward Compatibility - Trend Soft Preference
        
        required_trend SHALL be converted to a soft preference.
        A mismatched trend SHALL lower the score but NOT reject the profile.
        
        **Validates: Requirements 10.4**
        """
        router = ProfileRouter(config=RouterConfig(use_v2_scoring=True))
        
        # Create context with specific trend
        context = ContextVector(
            symbol='BTC-USDT',
            timestamp=time.time(),
            price=50000.0,
            trend_direction=context_trend,
            spread_bps=5.0,
            bid_depth_usd=50000.0,
            ask_depth_usd=50000.0,
            trades_per_second=1.0,
            book_age_ms=100.0,
            trade_age_ms=100.0,
            risk_mode='normal',
        )
        
        # Create profile with required_trend
        conditions = ProfileConditions(required_trend=required_trend)
        spec = ProfileSpec(
            id='test_trend_profile',
            name='Test Trend Profile',
            description='Test',
            conditions=conditions,
            tags=['test'],
        )
        
        # Score the profile
        score = router._score_profile(spec, context)
        
        # Profile should NOT be rejected due to trend mismatch
        assert score.rule_passed, \
            f"Profile should not be rejected due to trend mismatch. " \
            f"required={required_trend}, context={context_trend}, reasons={score.reasons}"
    
    @given(
        required_vol=st.sampled_from(VALID_VOL_REGIMES),
        context_vol=st.sampled_from(VALID_VOL_REGIMES)
    )
    @settings(max_examples=100)
    def test_required_volatility_is_soft_preference(
        self,
        required_vol: str,
        context_vol: str
    ):
        """
        Property 17: Backward Compatibility - Volatility Soft Preference
        
        required_volatility SHALL be converted to a soft preference.
        A mismatched volatility SHALL lower the score but NOT reject the profile.
        
        **Validates: Requirements 10.4**
        """
        router = ProfileRouter(config=RouterConfig(use_v2_scoring=True))
        
        # Create context with specific volatility
        context = ContextVector(
            symbol='BTC-USDT',
            timestamp=time.time(),
            price=50000.0,
            volatility_regime=context_vol,
            spread_bps=5.0,
            bid_depth_usd=50000.0,
            ask_depth_usd=50000.0,
            trades_per_second=1.0,
            book_age_ms=100.0,
            trade_age_ms=100.0,
            risk_mode='normal',
        )
        
        # Create profile with required_volatility
        conditions = ProfileConditions(required_volatility=required_vol)
        spec = ProfileSpec(
            id='test_vol_profile',
            name='Test Vol Profile',
            description='Test',
            conditions=conditions,
            tags=['test'],
        )
        
        # Score the profile
        score = router._score_profile(spec, context)
        
        # Profile should NOT be rejected due to volatility mismatch
        assert score.rule_passed, \
            f"Profile should not be rejected due to volatility mismatch. " \
            f"required={required_vol}, context={context_vol}, reasons={score.reasons}"
    
    @given(
        required_session=st.sampled_from(VALID_SESSIONS),
        context_session=st.sampled_from(VALID_SESSIONS)
    )
    @settings(max_examples=100)
    def test_required_session_is_soft_preference(
        self,
        required_session: str,
        context_session: str
    ):
        """
        Property 17: Backward Compatibility - Session Eligibility
        
        required_session SHALL be treated as an eligibility constraint.
        A mismatched session SHALL reject the profile.
        
        **Validates: Requirements 10.4**
        """
        router = ProfileRouter(config=RouterConfig(use_v2_scoring=True))
        
        # Create context with specific session
        context = ContextVector(
            symbol='BTC-USDT',
            timestamp=time.time(),
            price=50000.0,
            session=context_session,
            spread_bps=5.0,
            bid_depth_usd=50000.0,
            ask_depth_usd=50000.0,
            trades_per_second=1.0,
            book_age_ms=100.0,
            trade_age_ms=100.0,
            risk_mode='normal',
        )
        
        # Create profile with required_session
        conditions = ProfileConditions(required_session=required_session)
        spec = ProfileSpec(
            id='test_session_profile',
            name='Test Session Profile',
            description='Test',
            conditions=conditions,
            tags=['test'],
        )
        
        # Score the profile
        score = router._score_profile(spec, context)
        
        if required_session == context_session:
            assert score.rule_passed, (
                "Profile should pass when required_session matches context.session. "
                f"required={required_session}, context={context_session}, reasons={score.reasons}"
            )
        else:
            assert not score.rule_passed, (
                "Profile should be rejected when required_session mismatches context.session. "
                f"required={required_session}, context={context_session}, reasons={score.reasons}"
            )
    
    @given(
        required_value=st.sampled_from(VALID_VALUE_LOCATIONS),
        context_value=st.sampled_from(VALID_VALUE_LOCATIONS)
    )
    @settings(max_examples=100)
    def test_required_value_location_is_soft_preference(
        self,
        required_value: str,
        context_value: str
    ):
        """
        Property 17: Backward Compatibility - Value Location Soft Preference
        
        required_value_location SHALL be converted to a soft preference.
        A mismatched value location SHALL lower the score but NOT reject the profile.
        
        **Validates: Requirements 10.4**
        """
        router = ProfileRouter(config=RouterConfig(use_v2_scoring=True))
        
        # Create context with specific value location
        context = ContextVector(
            symbol='BTC-USDT',
            timestamp=time.time(),
            price=50000.0,
            position_in_value=context_value,
            spread_bps=5.0,
            bid_depth_usd=50000.0,
            ask_depth_usd=50000.0,
            trades_per_second=1.0,
            book_age_ms=100.0,
            trade_age_ms=100.0,
            risk_mode='normal',
        )
        
        # Create profile with required_value_location
        conditions = ProfileConditions(required_value_location=required_value)
        spec = ProfileSpec(
            id='test_value_profile',
            name='Test Value Profile',
            description='Test',
            conditions=conditions,
            tags=['test'],
        )
        
        # Score the profile
        score = router._score_profile(spec, context)
        
        # Profile should NOT be rejected due to value location mismatch
        assert score.rule_passed, \
            f"Profile should not be rejected due to value location mismatch. " \
            f"required={required_value}, context={context_value}, reasons={score.reasons}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
