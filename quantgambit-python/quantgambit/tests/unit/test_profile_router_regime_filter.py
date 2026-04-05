from quantgambit.deeptrader_core.profiles.context_vector import ContextVector
from quantgambit.deeptrader_core.profiles.profile_router import ProfileRouter
from quantgambit.deeptrader_core.strategies.chessboard.profile_spec import (
    ProfileSpec,
    ProfileConditions,
)


def _make_context(regime_family: str, market_regime: str) -> ContextVector:
    """Create a context with specified regime and valid safety values for v2 hard filters."""
    return ContextVector(
        symbol="BTC",
        timestamp=1.0,
        price=100.0,
        regime_family=regime_family,
        market_regime=market_regime,
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


def test_profile_router_tag_inferred_regime_is_soft_preference():
    """
    Test that tag-inferred regime allowlists are soft preferences, not hard constraints.
    
    Profile Router v2 Requirement 1.3: Tag-inferred regime allowlists are soft scoring
    factors, not hard constraints. Only explicit allowed_regimes causes hard rejection.
    """
    router = ProfileRouter()
    context = _make_context("trend", "breakout")
    
    # Profile with tags but no explicit allowed_regimes
    spec = ProfileSpec(
        id="test_profile",
        name="Test Profile",
        description="test",
        conditions=ProfileConditions(),  # No explicit allowed_regimes
        tags=["mean_reversion"],  # Tag-inferred regime
    )
    
    passed, reasons = router._check_rule_filters(spec, context)
    
    # In v2, tag-inferred regime is soft preference - profile passes hard filters
    assert passed is True, (
        f"Profile Router v2: tag-inferred regime is soft preference, not hard constraint. "
        f"Got reasons: {reasons}"
    )


def test_profile_router_explicit_regime_is_hard_constraint():
    """
    Test that explicit allowed_regimes causes hard rejection on mismatch.
    
    Profile Router v2 Requirement 1.4: Only profiles with explicitly specified
    ProfileConditions.allowed_regimes use hard filtering for regime.
    """
    router = ProfileRouter()
    context = _make_context("trend", "breakout")
    
    # Profile with explicit allowed_regimes
    spec = ProfileSpec(
        id="test_profile",
        name="Test Profile",
        description="test",
        conditions=ProfileConditions(
            allowed_regimes=["mean_revert", "range"],  # Explicit constraint
        ),
        tags=["mean_reversion"],
    )
    
    passed, reasons = router._check_rule_filters(spec, context)
    
    # Explicit allowed_regimes is hard constraint - should reject
    assert passed is False, (
        f"Profile with explicit allowed_regimes should be rejected on mismatch. "
        f"Got reasons: {reasons}"
    )
    assert any("regime_mismatch" in r for r in reasons), (
        f"Rejection reason should include regime_mismatch, got: {reasons}"
    )


def test_profile_router_allows_regime_match():
    """Test that profiles pass when regime matches."""
    router = ProfileRouter()
    context = _make_context("mean_revert", "range")
    spec = ProfileSpec(
        id="test_profile",
        name="Test Profile",
        description="test",
        conditions=ProfileConditions(),
        tags=["mean_reversion"],
    )
    passed, reasons = router._check_rule_filters(spec, context)
    assert passed is True
    assert not any("regime_mismatch" in r for r in reasons)
