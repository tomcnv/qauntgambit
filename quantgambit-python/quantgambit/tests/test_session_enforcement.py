"""
Session Enforcement Unit Tests

Tests that the profile router correctly enforces session constraints:
- overnight_thin profile rejected when context.session="us"
- overnight_thin profile accepted when context.session="overnight"
- Profiles with allowed_sessions constraint
- Profiles with no session constraint (should always pass)

Requirements: US-1 (AC1.4)
"""

import pytest
from quantgambit.deeptrader_core.profiles.context_vector import ContextVector
from quantgambit.deeptrader_core.profiles.profile_router import ProfileRouter
from quantgambit.deeptrader_core.strategies.chessboard.profile_spec import (
    ProfileSpec,
    ProfileConditions,
)


def _make_context(session: str, symbol: str = "BTCUSDT") -> ContextVector:
    """Create a minimal context vector with specified session.
    
    Note: Provides valid safety values (depth, spread, tps) to pass
    Profile Router v2 safety hard filters, allowing session behavior
    to be tested in isolation.
    """
    return ContextVector(
        symbol=symbol,
        timestamp=1.0,
        price=50000.0,
        session=session,
        hour_utc=20 if session == "us" else 23,  # 20:00 UTC for US, 23:00 for overnight
        data_completeness=1.0,
        spread_bps=5.0,
        trades_per_second=10.0,
        rotation_factor=1.0,
        # Safety values for v2 hard filters
        bid_depth_usd=50000.0,  # Sufficient depth
        ask_depth_usd=50000.0,  # Sufficient depth
        book_age_ms=100.0,  # Fresh data
        trade_age_ms=100.0,  # Fresh data
        risk_mode="normal",  # Safe risk mode
    )


class TestSessionEnforcement:
    """Tests for session enforcement in profile router."""

    def test_overnight_thin_rejected_when_session_is_us(self):
        """
        Test that overnight_thin profile behavior during US session.
        
        required_session is an eligibility constraint. The overnight_thin profile
        has required_session="overnight", so during US session it must be rejected.
        
        Requirements: US-1 (AC1.1, AC1.2), Profile Router v2 Requirement 4.1
        """
        router = ProfileRouter()
        context = _make_context(session="us")
        
        # Create overnight_thin profile spec with required_session="overnight"
        overnight_thin_spec = ProfileSpec(
            id="overnight_thin",
            name="Overnight Thin Liquidity",
            description="Conservative trading during thin overnight hours",
            conditions=ProfileConditions(
                required_session="overnight",
            ),
        )
        
        passed, reasons = router._check_rule_filters(overnight_thin_spec, context)
        
        assert passed is False, (
            f"required_session mismatch should reject. Got reasons: {reasons}"
        )
        assert any("required_session_mismatch" in r for r in reasons), (
            f"Expected required_session_mismatch in reasons, got: {reasons}"
        )

    def test_overnight_thin_accepted_when_session_is_overnight(self):
        """
        Test that overnight_thin profile is accepted when context.session="overnight".
        
        The overnight_thin profile has required_session="overnight", so it should
        be accepted during overnight session hours (22:00-24:00 UTC).
        
        Requirements: US-1 (AC1.2)
        """
        router = ProfileRouter()
        context = _make_context(session="overnight")
        
        # Create overnight_thin profile spec with required_session="overnight"
        overnight_thin_spec = ProfileSpec(
            id="overnight_thin",
            name="Overnight Thin Liquidity",
            description="Conservative trading during thin overnight hours",
            conditions=ProfileConditions(
                required_session="overnight",
            ),
        )
        
        passed, reasons = router._check_rule_filters(overnight_thin_spec, context)
        
        assert passed is True, f"overnight_thin should be accepted during overnight session, got reasons: {reasons}"

    def test_profile_with_allowed_sessions_constraint(self):
        """
        Test that profiles with allowed_sessions constraint behavior.
        
        In Profile Router v2, session is a soft preference, not a hard filter.
        A profile with allowed_sessions=["us", "europe"] will:
        - Pass hard filters regardless of session
        - Get higher scores when context.session matches allowed_sessions
        - Get lower scores when context.session doesn't match
        
        Requirements: US-1 (AC1.2), Profile Router v2 Requirement 4.2
        """
        router = ProfileRouter()
        
        # Create profile with allowed_sessions constraint
        us_europe_profile = ProfileSpec(
            id="us_europe_only",
            name="US/Europe Only Profile",
            description="Profile that prefers US and Europe sessions",
            conditions=ProfileConditions(
                allowed_sessions=["us", "europe"],
            ),
        )
        
        # Test US session - should pass hard filters
        context_us = _make_context(session="us")
        passed, reasons = router._check_rule_filters(us_europe_profile, context_us)
        assert passed is True, f"Profile should pass hard filters during US session, got: {reasons}"
        
        # Test Europe session - should pass hard filters
        context_europe = _make_context(session="europe")
        passed, reasons = router._check_rule_filters(us_europe_profile, context_europe)
        assert passed is True, f"Profile should pass hard filters during Europe session, got: {reasons}"
        
        # Test Asia session - in v2, should pass hard filters (session is soft preference)
        context_asia = _make_context(session="asia")
        passed, reasons = router._check_rule_filters(us_europe_profile, context_asia)
        assert passed is True, (
            f"Profile Router v2: session is soft preference, profile should pass hard filters. "
            f"Got reasons: {reasons}"
        )
        
        # Test Overnight session - in v2, should pass hard filters (session is soft preference)
        context_overnight = _make_context(session="overnight")
        passed, reasons = router._check_rule_filters(us_europe_profile, context_overnight)
        assert passed is True, (
            f"Profile Router v2: session is soft preference, profile should pass hard filters. "
            f"Got reasons: {reasons}"
        )

    def test_profile_with_no_session_constraint_always_passes(self):
        """
        Test that profiles with no session constraint pass regardless of session.
        
        A profile with no required_session and no allowed_sessions should
        be accepted during any session.
        
        Requirements: US-1 (AC1.2)
        """
        router = ProfileRouter()
        
        # Create profile with no session constraints
        no_session_profile = ProfileSpec(
            id="no_session_constraint",
            name="No Session Constraint Profile",
            description="Profile that trades during any session",
            conditions=ProfileConditions(),  # No session constraints
        )
        
        # Test all sessions - all should pass
        for session in ["asia", "europe", "us", "overnight"]:
            context = _make_context(session=session)
            passed, reasons = router._check_rule_filters(no_session_profile, context)
            assert passed is True, (
                f"Profile with no session constraint should pass during {session} session, "
                f"got reasons: {reasons}"
            )

    def test_session_not_set_rejects_session_constrained_profiles(self):
        """
        Test that profiles with session constraints are rejected when session is None/empty.
        
        This is a defensive check to prevent session-constrained profiles from being
        selected when the session classification fails.
        
        Note: required_session is an eligibility constraint, so session-constrained profiles
        must be rejected when session classification is missing (None/empty).
        
        Requirements: US-1 (AC1.2, AC1.3)
        """
        router = ProfileRouter()
        
        # Create context with no session set but valid safety values
        context_no_session = ContextVector(
            symbol="BTCUSDT",
            timestamp=1.0,
            price=50000.0,
            session="",  # Empty session
            hour_utc=20,
            data_completeness=1.0,
            # Safety values for v2 hard filters
            bid_depth_usd=50000.0,
            ask_depth_usd=50000.0,
            spread_bps=5.0,
            trades_per_second=10.0,
            book_age_ms=100.0,
            trade_age_ms=100.0,
            risk_mode="normal",
        )
        
        # Profile with required_session - empty session should reject.
        required_session_profile = ProfileSpec(
            id="required_session_profile",
            name="Required Session Profile",
            description="Profile with required_session",
            conditions=ProfileConditions(
                required_session="overnight",
            ),
        )
        
        passed, reasons = router._check_rule_filters(required_session_profile, context_no_session)
        assert passed is False, (
            f"Empty session should reject required_session profile. Got reasons: {reasons}"
        )
        assert any("required_session_mismatch" in r for r in reasons), (
            f"Expected required_session_mismatch in reasons, got: {reasons}"
        )
        
        # Profile with allowed_sessions - same behavior in v2
        allowed_sessions_profile = ProfileSpec(
            id="allowed_sessions_profile",
            name="Allowed Sessions Profile",
            description="Profile with allowed_sessions",
            conditions=ProfileConditions(
                allowed_sessions=["us", "europe"],
            ),
        )
        
        passed, reasons = router._check_rule_filters(allowed_sessions_profile, context_no_session)
        assert passed is True, (
            f"allowed_sessions is soft; profile should pass hard filters. Got reasons: {reasons}"
        )

    def test_session_none_rejects_session_constrained_profiles(self):
        """
        Test that profiles with session constraints are handled when session is None.
        
        Note: In Profile Router v2, session is a soft preference, not a hard filter.
        Profiles with session constraints will pass hard filters but get lower
        scores in soft scoring when session doesn't match.
        
        Requirements: US-1 (AC1.2, AC1.3)
        """
        router = ProfileRouter()
        
        # Create context with None session but valid safety values
        context_none_session = ContextVector(
            symbol="BTCUSDT",
            timestamp=1.0,
            price=50000.0,
            session=None,  # None session
            hour_utc=20,
            data_completeness=1.0,
            # Safety values for v2 hard filters
            bid_depth_usd=50000.0,
            ask_depth_usd=50000.0,
            spread_bps=5.0,
            trades_per_second=10.0,
            book_age_ms=100.0,
            trade_age_ms=100.0,
            risk_mode="normal",
        )
        
        # Profile with required_session - None session should reject.
        required_session_profile = ProfileSpec(
            id="required_session_profile",
            name="Required Session Profile",
            description="Profile with required_session",
            conditions=ProfileConditions(
                required_session="overnight",
            ),
        )
        
        passed, reasons = router._check_rule_filters(required_session_profile, context_none_session)
        assert passed is False, (
            f"None session should reject required_session profile. Got reasons: {reasons}"
        )
        assert any("required_session_mismatch" in r for r in reasons), (
            f"Expected required_session_mismatch in reasons, got: {reasons}"
        )

    def test_no_session_constraint_passes_when_session_not_set(self):
        """
        Test that profiles without session constraints pass even when session is not set.
        
        Requirements: US-1 (AC1.2)
        """
        router = ProfileRouter()
        
        # Create context with empty session but valid safety values
        context_no_session = ContextVector(
            symbol="BTCUSDT",
            timestamp=1.0,
            price=50000.0,
            session="",  # Empty session
            hour_utc=20,
            data_completeness=1.0,
            # Safety values for v2 hard filters
            bid_depth_usd=50000.0,
            ask_depth_usd=50000.0,
            spread_bps=5.0,
            trades_per_second=10.0,
            book_age_ms=100.0,
            trade_age_ms=100.0,
            risk_mode="normal",
        )
        
        # Profile with no session constraints should still pass
        no_constraint_profile = ProfileSpec(
            id="no_constraint_profile",
            name="No Constraint Profile",
            description="Profile with no session constraints",
            conditions=ProfileConditions(),  # No session constraints
        )
        
        passed, reasons = router._check_rule_filters(no_constraint_profile, context_no_session)
        assert passed is True, (
            f"Profile with no session constraints should pass even when session is empty, "
            f"got reasons: {reasons}"
        )
