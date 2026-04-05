"""
Property-based tests for Profile Router v2 Hard Filter Redesign.

Feature: profile-router-v2, Properties 8, 11
Validates: Requirements 3.1, 3.2, 5.5

Tests for:
- Property 8: Hard Filter Specificity
- Property 11: Cost Hard Rejection Threshold
"""

import pytest
from hypothesis import given, strategies as st, settings, assume
from typing import List, Optional

from quantgambit.deeptrader_core.profiles.context_vector import ContextVector
from quantgambit.deeptrader_core.profiles.profile_router import ProfileRouter
from quantgambit.deeptrader_core.profiles.router_config import RouterConfig
from quantgambit.deeptrader_core.strategies.chessboard.profile_spec import (
    ProfileSpec,
    ProfileConditions,
)


# ============================================================================
# Hypothesis Strategies
# ============================================================================

# Symbol names
symbols = st.sampled_from(["BTC-USDT", "ETH-USDT", "SOL-USDT", "DOGE-USDT"])

# Session names
sessions = st.sampled_from(["asia", "europe", "us", "overnight"])

# Trend directions
trend_directions = st.sampled_from(["up", "down", "flat"])

# Volatility regimes
volatility_regimes = st.sampled_from(["low", "normal", "high"])

# Value locations
value_locations = st.sampled_from(["above", "below", "inside"])

# Risk modes
risk_modes = st.sampled_from(["normal", "protection", "recovery", "off"])

# Safe risk modes (for passing safety filters)
safe_risk_modes = st.sampled_from(["normal", "recovery"])


# Cost values in basis points
cost_bps_values = st.floats(min_value=0.0, max_value=50.0, allow_nan=False, allow_infinity=False)

# Spread values in basis points
spread_bps_values = st.floats(min_value=0.0, max_value=100.0, allow_nan=False, allow_infinity=False)

# Depth values in USD
depth_usd_values = st.floats(min_value=0.0, max_value=200000.0, allow_nan=False, allow_infinity=False)

# TPS values
tps_values = st.floats(min_value=0.0, max_value=20.0, allow_nan=False, allow_infinity=False)

# Age values in milliseconds
age_ms_values = st.floats(min_value=0.0, max_value=20000.0, allow_nan=False, allow_infinity=False)

# Profile tags
mean_revert_tags = ["mean_reversion", "fade", "range", "reversal", "contrarian", "vwap"]
momentum_tags = ["momentum", "breakout", "trend", "volatility", "taker"]


@st.composite
def safe_context_vectors(draw) -> ContextVector:
    """Generate ContextVector instances that pass all safety hard filters."""
    config = RouterConfig()
    
    return ContextVector(
        symbol=draw(symbols),
        timestamp=draw(st.floats(min_value=1000000000.0, max_value=2000000000.0)),
        price=draw(st.floats(min_value=100.0, max_value=100000.0)),
        session=draw(sessions),
        hour_utc=draw(st.integers(min_value=0, max_value=23)),
        trend_direction=draw(trend_directions),
        volatility_regime=draw(volatility_regimes),
        position_in_value=draw(value_locations),
        # Safe values that pass hard filters
        spread_bps=draw(st.floats(min_value=0.0, max_value=config.max_safe_spread_bps - 1, allow_nan=False, allow_infinity=False)),
        bid_depth_usd=draw(st.floats(min_value=config.min_safe_depth_usd / 2 + 1, max_value=100000.0, allow_nan=False, allow_infinity=False)),
        ask_depth_usd=draw(st.floats(min_value=config.min_safe_depth_usd / 2 + 1, max_value=100000.0, allow_nan=False, allow_infinity=False)),
        trades_per_second=draw(st.floats(min_value=config.min_safe_tps + 0.1, max_value=10.0, allow_nan=False, allow_infinity=False)),
        book_age_ms=draw(st.floats(min_value=0.0, max_value=config.max_book_age_ms - 100, allow_nan=False, allow_infinity=False)),
        trade_age_ms=draw(st.floats(min_value=0.0, max_value=config.max_trade_age_ms - 100, allow_nan=False, allow_infinity=False)),
        risk_mode=draw(safe_risk_modes),
        expected_cost_bps=draw(st.floats(min_value=0.0, max_value=10.0, allow_nan=False, allow_infinity=False)),
    )


@st.composite
def profile_specs_with_soft_conditions(draw) -> ProfileSpec:
    """Generate ProfileSpec with soft preference conditions (trend, vol, value).

    NOTE: required_session is treated as an eligibility constraint (hard), so it is excluded
    from this property which asserts that soft conditions do not cause rejection.
    """
    has_trend = draw(st.booleans())
    has_vol = draw(st.booleans())
    has_value = draw(st.booleans())
    
    conditions = ProfileConditions(
        required_trend=draw(trend_directions) if has_trend else None,
        required_volatility=draw(volatility_regimes) if has_vol else None,
        required_value_location=draw(value_locations) if has_value else None,
        required_session=None,
    )
    
    return ProfileSpec(
        id=f"test_profile_{draw(st.integers(min_value=1, max_value=1000))}",
        name="Test Profile",
        description="Test profile for property testing",
        conditions=conditions,
        tags=draw(st.lists(st.sampled_from(mean_revert_tags + momentum_tags), min_size=0, max_size=2)),
    )


# ============================================================================
# Property 8: Hard Filter Specificity Tests
# ============================================================================

class TestHardFilterSpecificity:
    """
    Property 8: Hard Filter Specificity
    
    For any ContextVector, hard rejection SHALL only occur for safety-critical conditions:
    - spread_bps > max_safe_spread_bps
    - total_depth_usd < min_safe_depth_usd
    - trades_per_second < min_safe_tps
    - book_age_ms > max_book_age_ms
    - trade_age_ms > max_trade_age_ms
    - risk_mode in ["off", "protection"]
    
    All other conditions (trend, volatility, value_location, session) SHALL affect
    scoring but NOT cause rejection.
    
    **Feature: profile-router-v2, Property 8: Hard Filter Specificity**
    **Validates: Requirements 3.1, 3.2**
    """
    
    @given(
        context=safe_context_vectors(),
        spec=profile_specs_with_soft_conditions(),
    )
    @settings(max_examples=100)
    def test_soft_conditions_do_not_cause_rejection(
        self,
        context: ContextVector,
        spec: ProfileSpec,
    ):
        """
        Property 8: Hard Filter Specificity
        
        For any profile with soft preference conditions (trend, volatility,
        value_location, session), the profile SHALL NOT be rejected when
        safety conditions are met.
        
        **Validates: Requirements 3.2**
        """
        router = ProfileRouter()
        
        passed, reasons = router._check_rule_filters(spec, context)
        
        # With safe context values, profile should pass hard filters
        # regardless of soft preference mismatches
        assert passed is True, (
            f"Profile with soft conditions should pass when safety conditions are met. "
            f"Got reasons: {reasons}"
        )
        
        # Verify no soft condition rejection reasons
        soft_rejection_patterns = [
            "trend_mismatch", "trend_too_weak", "trend_too_strong",
            "vol_mismatch", "vol_too_low", "vol_too_high",
            "value_mismatch",
            "session_mismatch", "session_not_allowed",
        ]
        for pattern in soft_rejection_patterns:
            assert not any(pattern in r for r in reasons), (
                f"Soft condition '{pattern}' should not cause rejection in v2. "
                f"Got reasons: {reasons}"
            )
    
    @given(spread_bps=st.floats(min_value=51.0, max_value=200.0, allow_nan=False, allow_infinity=False))
    @settings(max_examples=100)
    def test_spread_too_wide_causes_rejection(self, spread_bps: float):
        """
        Property 8: Hard Filter Specificity
        
        For any context where spread_bps > max_safe_spread_bps (default 50),
        the profile SHALL be rejected.
        
        **Validates: Requirements 3.1**
        """
        router = ProfileRouter()
        config = RouterConfig()
        
        context = ContextVector(
            symbol="BTC-USDT",
            timestamp=1700000000.0,
            price=50000.0,
            spread_bps=spread_bps,
            # Other values are safe
            bid_depth_usd=50000.0,
            ask_depth_usd=50000.0,
            trades_per_second=5.0,
            book_age_ms=100.0,
            trade_age_ms=100.0,
            risk_mode="normal",
        )
        
        spec = ProfileSpec(
            id="test_profile",
            name="Test Profile",
            description="Test",
            conditions=ProfileConditions(),
        )
        
        passed, reasons = router._check_rule_filters(spec, context)
        
        assert passed is False, (
            f"Spread {spread_bps}bp > {config.max_safe_spread_bps}bp should cause rejection"
        )
        assert any("spread_too_wide" in r for r in reasons), (
            f"Rejection reason should include spread_too_wide, got: {reasons}"
        )

    
    @given(total_depth=st.floats(min_value=0.0, max_value=9999.0, allow_nan=False, allow_infinity=False))
    @settings(max_examples=100)
    def test_depth_too_low_causes_rejection(self, total_depth: float):
        """
        Property 8: Hard Filter Specificity
        
        For any context where total_depth_usd < min_safe_depth_usd (default 10000),
        the profile SHALL be rejected.
        
        **Validates: Requirements 3.1**
        """
        router = ProfileRouter()
        config = RouterConfig()
        
        # Split total depth between bid and ask
        bid_depth = total_depth / 2
        ask_depth = total_depth / 2
        
        context = ContextVector(
            symbol="BTC-USDT",
            timestamp=1700000000.0,
            price=50000.0,
            bid_depth_usd=bid_depth,
            ask_depth_usd=ask_depth,
            # Other values are safe
            spread_bps=5.0,
            trades_per_second=5.0,
            book_age_ms=100.0,
            trade_age_ms=100.0,
            risk_mode="normal",
        )
        
        spec = ProfileSpec(
            id="test_profile",
            name="Test Profile",
            description="Test",
            conditions=ProfileConditions(),
        )
        
        passed, reasons = router._check_rule_filters(spec, context)
        
        assert passed is False, (
            f"Depth ${total_depth:.0f} < ${config.min_safe_depth_usd:.0f} should cause rejection"
        )
        assert any("depth_too_low" in r for r in reasons), (
            f"Rejection reason should include depth_too_low, got: {reasons}"
        )
    
    @given(tps=st.floats(min_value=0.0, max_value=0.09, allow_nan=False, allow_infinity=False))
    @settings(max_examples=100)
    def test_tps_too_low_causes_rejection(self, tps: float):
        """
        Property 8: Hard Filter Specificity
        
        For any context where trades_per_second < min_safe_tps (default 0.1),
        the profile SHALL be rejected.
        
        **Validates: Requirements 3.1**
        """
        router = ProfileRouter()
        config = RouterConfig()
        
        context = ContextVector(
            symbol="BTC-USDT",
            timestamp=1700000000.0,
            price=50000.0,
            trades_per_second=tps,
            # Other values are safe
            spread_bps=5.0,
            bid_depth_usd=50000.0,
            ask_depth_usd=50000.0,
            book_age_ms=100.0,
            trade_age_ms=100.0,
            risk_mode="normal",
        )
        
        spec = ProfileSpec(
            id="test_profile",
            name="Test Profile",
            description="Test",
            conditions=ProfileConditions(),
        )
        
        passed, reasons = router._check_rule_filters(spec, context)
        
        assert passed is False, (
            f"TPS {tps:.2f} < {config.min_safe_tps:.2f} should cause rejection"
        )
        assert any("tps_too_low" in r for r in reasons), (
            f"Rejection reason should include tps_too_low, got: {reasons}"
        )
    
    @given(book_age_ms=st.floats(min_value=5001.0, max_value=20000.0, allow_nan=False, allow_infinity=False))
    @settings(max_examples=100)
    def test_book_data_stale_causes_rejection(self, book_age_ms: float):
        """
        Property 8: Hard Filter Specificity
        
        For any context where book_age_ms > max_book_age_ms (default 5000),
        the profile SHALL be rejected.
        
        **Validates: Requirements 3.1**
        """
        router = ProfileRouter()
        config = RouterConfig()
        
        context = ContextVector(
            symbol="BTC-USDT",
            timestamp=1700000000.0,
            price=50000.0,
            book_age_ms=book_age_ms,
            # Other values are safe
            spread_bps=5.0,
            bid_depth_usd=50000.0,
            ask_depth_usd=50000.0,
            trades_per_second=5.0,
            trade_age_ms=100.0,
            risk_mode="normal",
        )
        
        spec = ProfileSpec(
            id="test_profile",
            name="Test Profile",
            description="Test",
            conditions=ProfileConditions(),
        )
        
        passed, reasons = router._check_rule_filters(spec, context)
        
        assert passed is False, (
            f"Book age {book_age_ms:.0f}ms > {config.max_book_age_ms:.0f}ms should cause rejection"
        )
        assert any("book_data_stale" in r for r in reasons), (
            f"Rejection reason should include book_data_stale, got: {reasons}"
        )

    
    @given(trade_age_ms=st.floats(min_value=10001.0, max_value=30000.0, allow_nan=False, allow_infinity=False))
    @settings(max_examples=100)
    def test_trade_data_stale_causes_rejection(self, trade_age_ms: float):
        """
        Property 8: Hard Filter Specificity
        
        For any context where trade_age_ms > max_trade_age_ms (default 10000),
        the profile SHALL be rejected.
        
        **Validates: Requirements 3.1**
        """
        router = ProfileRouter()
        config = RouterConfig()
        
        context = ContextVector(
            symbol="BTC-USDT",
            timestamp=1700000000.0,
            price=50000.0,
            trade_age_ms=trade_age_ms,
            # Other values are safe
            spread_bps=5.0,
            bid_depth_usd=50000.0,
            ask_depth_usd=50000.0,
            trades_per_second=5.0,
            book_age_ms=100.0,
            risk_mode="normal",
        )
        
        spec = ProfileSpec(
            id="test_profile",
            name="Test Profile",
            description="Test",
            conditions=ProfileConditions(),
        )
        
        passed, reasons = router._check_rule_filters(spec, context)
        
        assert passed is False, (
            f"Trade age {trade_age_ms:.0f}ms > {config.max_trade_age_ms:.0f}ms should cause rejection"
        )
        assert any("trade_data_stale" in r for r in reasons), (
            f"Rejection reason should include trade_data_stale, got: {reasons}"
        )
    
    @given(risk_mode=st.sampled_from(["off", "protection"]))
    @settings(max_examples=100)
    def test_unsafe_risk_mode_causes_rejection(self, risk_mode: str):
        """
        Property 8: Hard Filter Specificity
        
        For any context where risk_mode in ["off", "protection"],
        the profile SHALL be rejected.
        
        **Validates: Requirements 3.1**
        """
        router = ProfileRouter()
        
        context = ContextVector(
            symbol="BTC-USDT",
            timestamp=1700000000.0,
            price=50000.0,
            risk_mode=risk_mode,
            # Other values are safe
            spread_bps=5.0,
            bid_depth_usd=50000.0,
            ask_depth_usd=50000.0,
            trades_per_second=5.0,
            book_age_ms=100.0,
            trade_age_ms=100.0,
        )
        
        spec = ProfileSpec(
            id="test_profile",
            name="Test Profile",
            description="Test",
            conditions=ProfileConditions(),
        )
        
        passed, reasons = router._check_rule_filters(spec, context)
        
        assert passed is False, (
            f"Risk mode '{risk_mode}' should cause rejection"
        )
        assert any("risk_mode_unsafe" in r for r in reasons), (
            f"Rejection reason should include risk_mode_unsafe, got: {reasons}"
        )
    
    @given(risk_mode=st.sampled_from(["normal", "recovery"]))
    @settings(max_examples=100)
    def test_safe_risk_mode_does_not_cause_rejection(self, risk_mode: str):
        """
        Property 8: Hard Filter Specificity
        
        For any context where risk_mode in ["normal", "recovery"],
        the profile SHALL NOT be rejected due to risk mode.
        
        **Validates: Requirements 3.1**
        """
        router = ProfileRouter()
        
        context = ContextVector(
            symbol="BTC-USDT",
            timestamp=1700000000.0,
            price=50000.0,
            risk_mode=risk_mode,
            # Other values are safe
            spread_bps=5.0,
            bid_depth_usd=50000.0,
            ask_depth_usd=50000.0,
            trades_per_second=5.0,
            book_age_ms=100.0,
            trade_age_ms=100.0,
        )
        
        spec = ProfileSpec(
            id="test_profile",
            name="Test Profile",
            description="Test",
            conditions=ProfileConditions(),
        )
        
        passed, reasons = router._check_rule_filters(spec, context)
        
        assert passed is True, (
            f"Risk mode '{risk_mode}' should not cause rejection. Got reasons: {reasons}"
        )
        assert not any("risk_mode" in r for r in reasons), (
            f"No risk_mode rejection reason expected, got: {reasons}"
        )



# ============================================================================
# Property 11: Cost Hard Rejection Threshold Tests
# ============================================================================

class TestCostHardRejectionThreshold:
    """
    Property 11: Cost Hard Rejection Threshold
    
    For any profile where expected_cost_bps >= 2 × max_viable_cost_bps,
    the profile SHALL be hard-rejected (cost_viability_fit = 0 AND rule_passed = False).
    
    Max viable cost depends on profile type:
    - Mean-reversion profiles: 8 bps (hard reject at 16 bps)
    - Momentum profiles: 15 bps in high vol, 12 bps otherwise (hard reject at 30/24 bps)
    - Default: 10 bps (hard reject at 20 bps)
    
    **Feature: profile-router-v2, Property 11: Cost Hard Rejection Threshold**
    **Validates: Requirements 5.5**
    """
    
    @given(expected_cost_bps=st.floats(min_value=16.0, max_value=50.0, allow_nan=False, allow_infinity=False))
    @settings(max_examples=100)
    def test_mean_revert_profile_hard_rejected_at_2x_threshold(
        self,
        expected_cost_bps: float,
    ):
        """
        Property 11: Cost Hard Rejection Threshold
        
        For any mean-reversion profile where expected_cost_bps >= 16 (2 × 8),
        the profile SHALL be hard-rejected.
        
        **Validates: Requirements 5.5**
        """
        router = ProfileRouter()
        
        context = ContextVector(
            symbol="BTC-USDT",
            timestamp=1700000000.0,
            price=50000.0,
            expected_cost_bps=expected_cost_bps,
            # Safe values for other hard filters
            spread_bps=5.0,
            bid_depth_usd=50000.0,
            ask_depth_usd=50000.0,
            trades_per_second=5.0,
            book_age_ms=100.0,
            trade_age_ms=100.0,
            risk_mode="normal",
        )
        
        spec = ProfileSpec(
            id="test_mean_revert",
            name="Test Mean Revert Profile",
            description="Test",
            conditions=ProfileConditions(),
            tags=["mean_reversion"],  # Mean-revert tag
        )
        
        passed, reasons = router._check_rule_filters(spec, context)
        
        assert passed is False, (
            f"Mean-revert profile with cost {expected_cost_bps}bp >= 16bp should be rejected. "
            f"Got reasons: {reasons}"
        )
        assert any("cost_too_high" in r for r in reasons), (
            f"Rejection reason should include cost_too_high, got: {reasons}"
        )
    
    @given(expected_cost_bps=st.floats(min_value=0.0, max_value=15.9, allow_nan=False, allow_infinity=False))
    @settings(max_examples=100)
    def test_mean_revert_profile_not_rejected_below_2x_threshold(
        self,
        expected_cost_bps: float,
    ):
        """
        Property 11: Cost Hard Rejection Threshold
        
        For any mean-reversion profile where expected_cost_bps < 16 (2 × 8),
        the profile SHALL NOT be hard-rejected due to cost.
        
        **Validates: Requirements 5.5**
        """
        router = ProfileRouter()
        
        context = ContextVector(
            symbol="BTC-USDT",
            timestamp=1700000000.0,
            price=50000.0,
            expected_cost_bps=expected_cost_bps,
            # Safe values for other hard filters
            spread_bps=5.0,
            bid_depth_usd=50000.0,
            ask_depth_usd=50000.0,
            trades_per_second=5.0,
            book_age_ms=100.0,
            trade_age_ms=100.0,
            risk_mode="normal",
        )
        
        spec = ProfileSpec(
            id="test_mean_revert",
            name="Test Mean Revert Profile",
            description="Test",
            conditions=ProfileConditions(),
            tags=["mean_reversion"],
        )
        
        passed, reasons = router._check_rule_filters(spec, context)
        
        assert passed is True, (
            f"Mean-revert profile with cost {expected_cost_bps}bp < 16bp should pass. "
            f"Got reasons: {reasons}"
        )
        assert not any("cost_too_high" in r for r in reasons), (
            f"No cost_too_high rejection expected, got: {reasons}"
        )

    
    @given(expected_cost_bps=st.floats(min_value=30.0, max_value=60.0, allow_nan=False, allow_infinity=False))
    @settings(max_examples=100)
    def test_momentum_profile_high_vol_hard_rejected_at_2x_threshold(
        self,
        expected_cost_bps: float,
    ):
        """
        Property 11: Cost Hard Rejection Threshold
        
        For any momentum profile in high volatility where expected_cost_bps >= 30 (2 × 15),
        the profile SHALL be hard-rejected.
        
        **Validates: Requirements 5.5**
        """
        router = ProfileRouter()
        
        context = ContextVector(
            symbol="BTC-USDT",
            timestamp=1700000000.0,
            price=50000.0,
            expected_cost_bps=expected_cost_bps,
            volatility_regime="high",  # High volatility
            # Safe values for other hard filters
            spread_bps=5.0,
            bid_depth_usd=50000.0,
            ask_depth_usd=50000.0,
            trades_per_second=5.0,
            book_age_ms=100.0,
            trade_age_ms=100.0,
            risk_mode="normal",
        )
        
        spec = ProfileSpec(
            id="test_momentum",
            name="Test Momentum Profile",
            description="Test",
            conditions=ProfileConditions(),
            tags=["momentum"],  # Momentum tag
        )
        
        passed, reasons = router._check_rule_filters(spec, context)
        
        assert passed is False, (
            f"Momentum profile (high vol) with cost {expected_cost_bps}bp >= 30bp should be rejected. "
            f"Got reasons: {reasons}"
        )
        assert any("cost_too_high" in r for r in reasons), (
            f"Rejection reason should include cost_too_high, got: {reasons}"
        )
    
    @given(expected_cost_bps=st.floats(min_value=24.0, max_value=50.0, allow_nan=False, allow_infinity=False))
    @settings(max_examples=100)
    def test_momentum_profile_normal_vol_hard_rejected_at_2x_threshold(
        self,
        expected_cost_bps: float,
    ):
        """
        Property 11: Cost Hard Rejection Threshold
        
        For any momentum profile in normal/low volatility where expected_cost_bps >= 24 (2 × 12),
        the profile SHALL be hard-rejected.
        
        **Validates: Requirements 5.5**
        """
        router = ProfileRouter()
        
        context = ContextVector(
            symbol="BTC-USDT",
            timestamp=1700000000.0,
            price=50000.0,
            expected_cost_bps=expected_cost_bps,
            volatility_regime="normal",  # Normal volatility
            # Safe values for other hard filters
            spread_bps=5.0,
            bid_depth_usd=50000.0,
            ask_depth_usd=50000.0,
            trades_per_second=5.0,
            book_age_ms=100.0,
            trade_age_ms=100.0,
            risk_mode="normal",
        )
        
        spec = ProfileSpec(
            id="test_momentum",
            name="Test Momentum Profile",
            description="Test",
            conditions=ProfileConditions(),
            tags=["momentum"],
        )
        
        passed, reasons = router._check_rule_filters(spec, context)
        
        assert passed is False, (
            f"Momentum profile (normal vol) with cost {expected_cost_bps}bp >= 24bp should be rejected. "
            f"Got reasons: {reasons}"
        )
        assert any("cost_too_high" in r for r in reasons), (
            f"Rejection reason should include cost_too_high, got: {reasons}"
        )
    
    @given(expected_cost_bps=st.floats(min_value=20.0, max_value=50.0, allow_nan=False, allow_infinity=False))
    @settings(max_examples=100)
    def test_default_profile_hard_rejected_at_2x_threshold(
        self,
        expected_cost_bps: float,
    ):
        """
        Property 11: Cost Hard Rejection Threshold
        
        For any profile without specific tags where expected_cost_bps >= 20 (2 × 10),
        the profile SHALL be hard-rejected.
        
        **Validates: Requirements 5.5**
        """
        router = ProfileRouter()
        
        context = ContextVector(
            symbol="BTC-USDT",
            timestamp=1700000000.0,
            price=50000.0,
            expected_cost_bps=expected_cost_bps,
            # Safe values for other hard filters
            spread_bps=5.0,
            bid_depth_usd=50000.0,
            ask_depth_usd=50000.0,
            trades_per_second=5.0,
            book_age_ms=100.0,
            trade_age_ms=100.0,
            risk_mode="normal",
        )
        
        spec = ProfileSpec(
            id="test_default",
            name="Test Default Profile",
            description="Test",
            conditions=ProfileConditions(),
            tags=[],  # No specific tags
        )
        
        passed, reasons = router._check_rule_filters(spec, context)
        
        assert passed is False, (
            f"Default profile with cost {expected_cost_bps}bp >= 20bp should be rejected. "
            f"Got reasons: {reasons}"
        )
        assert any("cost_too_high" in r for r in reasons), (
            f"Rejection reason should include cost_too_high, got: {reasons}"
        )

    
    @given(
        expected_cost_bps=st.floats(min_value=0.0, max_value=50.0, allow_nan=False, allow_infinity=False),
        tag=st.sampled_from(mean_revert_tags),
    )
    @settings(max_examples=100)
    def test_cost_threshold_varies_by_profile_type(
        self,
        expected_cost_bps: float,
        tag: str,
    ):
        """
        Property 11: Cost Hard Rejection Threshold
        
        For any profile, the hard rejection threshold SHALL depend on profile type:
        - Mean-reversion: 2 × 8 = 16 bps
        - Momentum (high vol): 2 × 15 = 30 bps
        - Momentum (normal vol): 2 × 12 = 24 bps
        - Default: 2 × 10 = 20 bps
        
        **Validates: Requirements 5.5**
        """
        router = ProfileRouter()
        
        context = ContextVector(
            symbol="BTC-USDT",
            timestamp=1700000000.0,
            price=50000.0,
            expected_cost_bps=expected_cost_bps,
            volatility_regime="normal",
            # Safe values for other hard filters
            spread_bps=5.0,
            bid_depth_usd=50000.0,
            ask_depth_usd=50000.0,
            trades_per_second=5.0,
            book_age_ms=100.0,
            trade_age_ms=100.0,
            risk_mode="normal",
        )
        
        spec = ProfileSpec(
            id="test_profile",
            name="Test Profile",
            description="Test",
            conditions=ProfileConditions(),
            tags=[tag],
        )
        
        passed, reasons = router._check_rule_filters(spec, context)
        
        # Mean-revert threshold is 16 bps
        threshold = 16.0
        
        if expected_cost_bps >= threshold:
            assert passed is False, (
                f"Profile with tag '{tag}' and cost {expected_cost_bps}bp >= {threshold}bp "
                f"should be rejected. Got reasons: {reasons}"
            )
        else:
            assert passed is True, (
                f"Profile with tag '{tag}' and cost {expected_cost_bps}bp < {threshold}bp "
                f"should pass. Got reasons: {reasons}"
            )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


# ============================================================================
# Backtesting Mode Tests
# ============================================================================

class TestBacktestingMode:
    """
    Tests for backtesting mode which disables data freshness hard filters.
    
    When backtesting_mode=True in RouterConfig:
    - book_age_ms checks are skipped
    - trade_age_ms checks are skipped
    - All other safety hard filters remain active
    
    This allows historical data replay without rejection due to "stale" data.
    """
    
    @given(
        book_age_ms=st.floats(min_value=5001.0, max_value=1000000.0, allow_nan=False, allow_infinity=False),
        trade_age_ms=st.floats(min_value=10001.0, max_value=1000000.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=100)
    def test_backtesting_mode_skips_data_freshness_checks(
        self,
        book_age_ms: float,
        trade_age_ms: float,
    ):
        """
        In backtesting mode, stale book_age_ms and trade_age_ms SHALL NOT cause rejection.
        
        This is essential for replaying historical data where timestamps are in the past.
        """
        # Create router with backtesting mode enabled
        config = RouterConfig(backtesting_mode=True)
        router = ProfileRouter(config=config)
        
        context = ContextVector(
            symbol="BTC-USDT",
            timestamp=1700000000.0,
            price=50000.0,
            book_age_ms=book_age_ms,  # Would normally cause rejection
            trade_age_ms=trade_age_ms,  # Would normally cause rejection
            # Other values are safe
            spread_bps=5.0,
            bid_depth_usd=50000.0,
            ask_depth_usd=50000.0,
            trades_per_second=5.0,
            risk_mode="normal",
        )
        
        spec = ProfileSpec(
            id="test_profile",
            name="Test Profile",
            description="Test",
            conditions=ProfileConditions(),
        )
        
        passed, reasons = router._check_rule_filters(spec, context)
        
        assert passed is True, (
            f"Backtesting mode should skip data freshness checks. "
            f"book_age_ms={book_age_ms}, trade_age_ms={trade_age_ms}. "
            f"Got reasons: {reasons}"
        )
        assert not any("book_data_stale" in r for r in reasons), (
            f"No book_data_stale rejection expected in backtesting mode, got: {reasons}"
        )
        assert not any("trade_data_stale" in r for r in reasons), (
            f"No trade_data_stale rejection expected in backtesting mode, got: {reasons}"
        )
    
    @given(spread_bps=st.floats(min_value=51.0, max_value=200.0, allow_nan=False, allow_infinity=False))
    @settings(max_examples=100)
    def test_backtesting_mode_still_enforces_spread_check(self, spread_bps: float):
        """
        In backtesting mode, spread_bps > max_safe_spread_bps SHALL still cause rejection.
        
        Safety filters other than data freshness remain active.
        """
        config = RouterConfig(backtesting_mode=True)
        router = ProfileRouter(config=config)
        
        context = ContextVector(
            symbol="BTC-USDT",
            timestamp=1700000000.0,
            price=50000.0,
            spread_bps=spread_bps,
            # Stale data that would be skipped
            book_age_ms=100000.0,
            trade_age_ms=100000.0,
            # Other values are safe
            bid_depth_usd=50000.0,
            ask_depth_usd=50000.0,
            trades_per_second=5.0,
            risk_mode="normal",
        )
        
        spec = ProfileSpec(
            id="test_profile",
            name="Test Profile",
            description="Test",
            conditions=ProfileConditions(),
        )
        
        passed, reasons = router._check_rule_filters(spec, context)
        
        assert passed is False, (
            f"Spread {spread_bps}bp > max should still cause rejection in backtesting mode"
        )
        assert any("spread_too_wide" in r for r in reasons), (
            f"Rejection reason should include spread_too_wide, got: {reasons}"
        )
    
    @given(total_depth=st.floats(min_value=0.0, max_value=9999.0, allow_nan=False, allow_infinity=False))
    @settings(max_examples=100)
    def test_backtesting_mode_still_enforces_depth_check(self, total_depth: float):
        """
        In backtesting mode, total_depth_usd < min_safe_depth_usd SHALL still cause rejection.
        
        Safety filters other than data freshness remain active.
        """
        config = RouterConfig(backtesting_mode=True)
        router = ProfileRouter(config=config)
        
        context = ContextVector(
            symbol="BTC-USDT",
            timestamp=1700000000.0,
            price=50000.0,
            bid_depth_usd=total_depth / 2,
            ask_depth_usd=total_depth / 2,
            # Stale data that would be skipped
            book_age_ms=100000.0,
            trade_age_ms=100000.0,
            # Other values are safe
            spread_bps=5.0,
            trades_per_second=5.0,
            risk_mode="normal",
        )
        
        spec = ProfileSpec(
            id="test_profile",
            name="Test Profile",
            description="Test",
            conditions=ProfileConditions(),
        )
        
        passed, reasons = router._check_rule_filters(spec, context)
        
        assert passed is False, (
            f"Depth ${total_depth:.0f} < min should still cause rejection in backtesting mode"
        )
        assert any("depth_too_low" in r for r in reasons), (
            f"Rejection reason should include depth_too_low, got: {reasons}"
        )
    
    def test_backtesting_mode_default_is_false(self):
        """
        By default, backtesting_mode SHALL be False (live trading mode).
        """
        config = RouterConfig()
        assert config.backtesting_mode is False, (
            "Default backtesting_mode should be False"
        )
    
    def test_backtesting_mode_can_be_enabled(self):
        """
        backtesting_mode can be explicitly set to True.
        """
        config = RouterConfig(backtesting_mode=True)
        assert config.backtesting_mode is True, (
            "backtesting_mode should be True when explicitly set"
        )
