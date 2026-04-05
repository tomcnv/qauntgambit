"""
Property-based tests for SessionAwareRiskMode.

Feature: trading-loss-fixes
Tests correctness properties for:
- Property 6: Session Risk Mode

**Validates: Requirements 5.1**
"""

import pytest
from hypothesis import given, strategies as st, settings, assume
from datetime import datetime, timezone

from quantgambit.signals.stages.session_risk import (
    classify_session_risk,
    SessionRiskResult,
    is_strategy_allowed_in_session,
    is_strategy_preferred_for_session_risk,
    STRATEGY_SESSION_PREFERENCES,
    get_utc_hour_from_timestamp,
)
from quantgambit.deeptrader_core.types import Features, AccountState, Profile
from quantgambit.deeptrader_core.profiles.profile_classifier import (
    classify_profile,
    classify_session,
)


# =============================================================================
# Test Strategies (Generators)
# =============================================================================

# Sessions
session_strategy = st.sampled_from(["asia", "europe", "us", "overnight"])

# Volatility regimes
volatility_strategy = st.sampled_from(["low", "normal", "high"])

# UTC hours (0-23)
utc_hour_strategy = st.integers(min_value=0, max_value=23)

# Strategy IDs from the registry
strategy_id_strategy = st.sampled_from([
    "mean_reversion_fade",
    "trend_following",
    "trend_pullback",
    "asia_range_scalp",
    "europe_open_vol",
    "us_open_momentum",
    "overnight_thin",
    "breakout_scalp",
    "poc_magnet_scalp",
    "high_vol_breakout",
])

# Symbols
symbol_strategy = st.sampled_from(["BTCUSDT", "ETHUSDT", "SOLUSDT"])

# Prices
price_strategy = st.floats(min_value=100.0, max_value=100000.0, allow_nan=False, allow_infinity=False)

# EMA values (relative to price)
ema_multiplier_strategy = st.floats(min_value=0.95, max_value=1.05, allow_nan=False, allow_infinity=False)

# ATR values
atr_strategy = st.floats(min_value=10.0, max_value=1000.0, allow_nan=False, allow_infinity=False)

# Daily PnL
daily_pnl_strategy = st.floats(min_value=-1000.0, max_value=1000.0, allow_nan=False, allow_infinity=False)


# =============================================================================
# Property 6: Session Risk Mode
# Feature: trading-loss-fixes, Property 6: Session Risk Mode
# Validates: Requirements 5.1
# =============================================================================

@settings(max_examples=100)
@given(
    volatility=volatility_strategy,
    utc_hour=utc_hour_strategy,
)
def test_property_6_overnight_session_risk_off(
    volatility: str,
    utc_hour: int,
):
    """
    Property 6: Session Risk Mode - Overnight
    
    *For any* profile classified with session "overnight", the risk_mode 
    SHALL be set to "off" and no signals SHALL be generated.
    
    **Validates: Requirements 5.1**
    """
    # Call classify_session_risk with overnight session
    result = classify_session_risk("overnight", volatility, utc_hour)
    
    # Property: overnight session always sets risk_mode to "off"
    assert result.risk_mode == "off", \
        f"Overnight session should have risk_mode='off', got '{result.risk_mode}'"
    
    # Property: overnight session has position_size_multiplier = 0
    assert result.position_size_multiplier == 0.0, \
        f"Overnight session should have position_size_multiplier=0.0, got {result.position_size_multiplier}"
    
    # Property: overnight session has empty preferred_strategies (no trading)
    assert result.preferred_strategies == [], \
        f"Overnight session should have empty preferred_strategies, got {result.preferred_strategies}"
    
    # Property: reason indicates overnight
    assert "overnight" in result.reason.lower(), \
        f"Reason should mention overnight, got '{result.reason}'"


@settings(max_examples=100)
@given(
    symbol=symbol_strategy,
    price=price_strategy,
    ema_mult=ema_multiplier_strategy,
    atr=atr_strategy,
    daily_pnl=daily_pnl_strategy,
)
def test_property_6_overnight_profile_classification(
    symbol: str,
    price: float,
    ema_mult: float,
    atr: float,
    daily_pnl: float,
):
    """
    Property 6: Session Risk Mode - Profile Classification
    
    *For any* features with timestamp in overnight hours (22-24 UTC),
    the classified profile SHALL have risk_mode="off".
    
    **Validates: Requirements 5.1**
    """
    # Create timestamp in overnight hours (22-24 UTC)
    overnight_hour = 23  # Fixed to overnight
    overnight_ts = datetime(2024, 1, 10, overnight_hour, 30, 0, tzinfo=timezone.utc).timestamp()
    
    # Create features
    features = Features(
        symbol=symbol,
        price=price,
        spread=price * 0.0001,  # 1 bps spread
        rotation_factor=0.0,
        position_in_value="inside",
        timestamp=overnight_ts,
        ema_fast_15m=price * ema_mult,
        ema_slow_15m=price,
        atr_5m=atr,
        atr_5m_baseline=atr,
    )
    
    # Create account state (ensure not in loss-based off mode)
    account = AccountState(
        equity=10000.0,
        daily_pnl=daily_pnl,
        max_daily_loss=-500.0,
        open_positions=0,
        symbol_open_positions=0,
        symbol_daily_pnl=0.0,
    )
    
    # Skip if daily_pnl would trigger loss-based off mode
    # (we want to test session-based off mode specifically)
    assume(daily_pnl >= 0.7 * account.max_daily_loss)
    
    # Classify profile
    profile = classify_profile(features, account)
    
    # Property: overnight session sets risk_mode to "off"
    assert profile.session == "overnight", \
        f"Session should be 'overnight' for hour {overnight_hour}, got '{profile.session}'"
    assert profile.risk_mode == "off", \
        f"Overnight profile should have risk_mode='off', got '{profile.risk_mode}'"


@settings(max_examples=100)
@given(
    volatility=volatility_strategy,
    utc_hour=st.integers(min_value=0, max_value=5),  # Low liquidity hours
)
def test_property_6_low_liquidity_hours_reduced_size(
    volatility: str,
    utc_hour: int,
):
    """
    Property 6 (Extended): Low Liquidity Hours
    
    *For any* session during low liquidity hours (0-6 UTC),
    the position_size_multiplier SHALL be 0.5.
    
    **Validates: Requirements 5.3**
    """
    # Get session for this hour (will be "asia" for 0-6 UTC)
    session = "asia"  # 0-6 UTC is classified as asia
    
    result = classify_session_risk(session, volatility, utc_hour)
    
    # Property: low liquidity hours have reduced position size
    assert result.position_size_multiplier == 0.5, \
        f"Low liquidity hours should have position_size_multiplier=0.5, got {result.position_size_multiplier}"
    
    # Property: risk_mode is "reduced"
    assert result.risk_mode == "reduced", \
        f"Low liquidity hours should have risk_mode='reduced', got '{result.risk_mode}'"


@settings(max_examples=100)
@given(
    utc_hour=st.integers(min_value=6, max_value=6),  # Asia session, not low liquidity
)
def test_property_6_asia_low_vol_prefers_trend(
    utc_hour: int,
):
    """
    Property 6 (Extended): Asia Low Volatility
    
    *For any* Asia session with low volatility,
    the preferred_strategies SHALL include trend following strategies.
    
    **Validates: Requirements 5.2**
    """
    result = classify_session_risk("asia", "low", utc_hour)
    
    # Property: Asia low vol prefers trend following
    assert result.preferred_strategies is not None, \
        "Asia low vol should have preferred_strategies set"
    assert "trend_following" in result.preferred_strategies or "trend_pullback" in result.preferred_strategies, \
        f"Asia low vol should prefer trend strategies, got {result.preferred_strategies}"
    
    # Property: risk_mode is normal (not reduced)
    assert result.risk_mode == "normal", \
        f"Asia low vol should have risk_mode='normal', got '{result.risk_mode}'"


@settings(max_examples=100)
@given(
    strategy_id=strategy_id_strategy,
)
def test_property_6_strategy_session_preferences(
    strategy_id: str,
):
    """
    Property 6 (Extended): Strategy Session Preferences
    
    *For any* strategy with defined session preferences,
    the strategy SHALL only be allowed in those sessions.
    
    **Validates: Requirements 5.4, 5.5**
    """
    # Get the strategy's preferred sessions (if any)
    preferred_sessions = STRATEGY_SESSION_PREFERENCES.get(strategy_id)
    
    if preferred_sessions is None:
        # Strategy has no preferences, should be allowed everywhere
        for session in ["asia", "europe", "us", "overnight"]:
            assert is_strategy_allowed_in_session(strategy_id, session), \
                f"Strategy {strategy_id} with no preferences should be allowed in {session}"
    else:
        # Strategy has preferences, check each session
        for session in ["asia", "europe", "us", "overnight"]:
            expected = session in preferred_sessions
            actual = is_strategy_allowed_in_session(strategy_id, session)
            assert actual == expected, \
                f"Strategy {strategy_id} in {session}: expected {expected}, got {actual}"


@settings(max_examples=100)
@given(
    session=session_strategy,
    volatility=volatility_strategy,
    utc_hour=utc_hour_strategy,
)
def test_property_6_session_risk_result_consistency(
    session: str,
    volatility: str,
    utc_hour: int,
):
    """
    Property 6 (Consistency): Session Risk Result Invariants
    
    *For any* session risk classification:
    - If risk_mode is "off", position_size_multiplier must be 0
    - If risk_mode is "reduced", position_size_multiplier must be < 1
    - If risk_mode is "normal", position_size_multiplier must be >= 1
    
    **Validates: Requirements 5.1, 5.3**
    """
    result = classify_session_risk(session, volatility, utc_hour)
    
    # Invariant: risk_mode "off" implies position_size_multiplier = 0
    if result.risk_mode == "off":
        assert result.position_size_multiplier == 0.0, \
            f"risk_mode='off' should have position_size_multiplier=0, got {result.position_size_multiplier}"
        assert result.preferred_strategies == [], \
            f"risk_mode='off' should have empty preferred_strategies"
    
    # Invariant: risk_mode "reduced" implies position_size_multiplier < 1
    elif result.risk_mode == "reduced":
        assert 0 < result.position_size_multiplier < 1.0, \
            f"risk_mode='reduced' should have 0 < position_size_multiplier < 1, got {result.position_size_multiplier}"
    
    # Invariant: risk_mode "normal" implies position_size_multiplier >= 1
    elif result.risk_mode == "normal":
        assert result.position_size_multiplier >= 1.0, \
            f"risk_mode='normal' should have position_size_multiplier >= 1, got {result.position_size_multiplier}"
    
    # Invariant: session in result matches input
    assert result.session == session, \
        f"Result session should match input, expected {session}, got {result.session}"
    
    # Invariant: reason is always set
    assert result.reason, \
        "Result reason should always be set"


@settings(max_examples=100)
@given(
    utc_hour=utc_hour_strategy,
)
def test_property_6_utc_hour_extraction(
    utc_hour: int,
):
    """
    Property 6 (Helper): UTC Hour Extraction
    
    *For any* timestamp, get_utc_hour_from_timestamp SHALL return
    the correct UTC hour.
    
    **Validates: Helper function correctness**
    """
    # Create timestamp for the given hour
    ts = datetime(2024, 1, 10, utc_hour, 30, 0, tzinfo=timezone.utc).timestamp()
    
    # Extract hour
    extracted_hour = get_utc_hour_from_timestamp(ts)
    
    # Property: extracted hour matches input
    assert extracted_hour == utc_hour, \
        f"Extracted hour should be {utc_hour}, got {extracted_hour}"
