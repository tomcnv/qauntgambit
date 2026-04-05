"""
Property-based tests for MinimumHoldTimeEnforcer.

Feature: trading-loss-fixes
Tests correctness properties for:
- Property 4: Minimum Hold Time Enforcement

**Validates: Requirements 3.2, 3.3, 3.5**
"""

import pytest
import time
from hypothesis import given, strategies as st, settings, assume

from quantgambit.signals.stages.minimum_hold_time import (
    MinimumHoldTimeEnforcer,
    MinimumHoldTimeConfig,
    STRATEGY_MIN_HOLD_TIMES,
)
from quantgambit.deeptrader_core.types import ExitType, ExitDecision


# =============================================================================
# Test Strategies (Generators)
# =============================================================================

# Strategy IDs
strategy_id = st.sampled_from([
    "mean_reversion_fade",
    "trend_following",
    "default",
    "unknown_strategy",
])

# Hold times in seconds (0 to 600 seconds = 10 minutes)
hold_time_sec = st.floats(min_value=0.0, max_value=600.0, allow_nan=False, allow_infinity=False)

# Exit types
exit_type = st.sampled_from([ExitType.SAFETY, ExitType.INVALIDATION])

# Urgency values
urgency = st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False)


def make_exit_decision(exit_type: ExitType, urgency: float = 0.5) -> ExitDecision:
    """Create an ExitDecision for testing."""
    return ExitDecision(
        should_exit=True,
        exit_type=exit_type,
        reason="test_reason",
        urgency=urgency,
        confirmations=["test_confirmation"],
    )


def make_position(strategy_id: str, hold_time_sec: float) -> dict:
    """Create a position dict for testing."""
    return {
        "symbol": "BTCUSDT",
        "side": "long",
        "strategy_id": strategy_id,
        "opened_at": time.time() - hold_time_sec,  # Position opened hold_time_sec ago
        "entry_price": 50000.0,
        "size": 0.1,
    }


# =============================================================================
# Property 4: Minimum Hold Time Enforcement
# Feature: trading-loss-fixes, Property 4: Minimum Hold Time Enforcement
# Validates: Requirements 3.2, 3.3, 3.5
# =============================================================================

@settings(max_examples=100)
@given(
    strat_id=strategy_id,
    hold_time=hold_time_sec,
)
def test_property_4_safety_exits_always_allowed(
    strat_id: str,
    hold_time: float,
):
    """
    Property 4 (Safety Bypass): Safety exits always bypass minimum hold time
    
    *For any* position with a SAFETY exit signal, the exit SHALL proceed 
    immediately regardless of hold time.
    
    **Validates: Requirements 3.5**
    """
    enforcer = MinimumHoldTimeEnforcer()
    position = make_position(strat_id, hold_time)
    exit_decision = make_exit_decision(ExitType.SAFETY)
    
    allowed, reason = enforcer.should_allow_exit(position, exit_decision)
    
    # Property: Safety exits are ALWAYS allowed
    assert allowed is True, \
        f"Safety exit should ALWAYS be allowed, got allowed={allowed}"
    assert reason == "safety_exit_bypass", \
        f"Reason should be 'safety_exit_bypass', got {reason}"


@settings(max_examples=100)
@given(
    strat_id=strategy_id,
    hold_time=hold_time_sec,
)
def test_property_4_invalidation_respects_min_hold(
    strat_id: str,
    hold_time: float,
):
    """
    Property 4 (Invalidation Hold): Invalidation exits respect minimum hold time
    
    *For any* position with an INVALIDATION exit signal:
    - IF hold_time < min_hold_time, THEN exit SHALL be deferred
    - IF hold_time >= min_hold_time, THEN exit SHALL be allowed
    
    **Validates: Requirements 3.2, 3.3**
    """
    enforcer = MinimumHoldTimeEnforcer()
    position = make_position(strat_id, hold_time)
    exit_decision = make_exit_decision(ExitType.INVALIDATION)
    
    # Get expected min hold time for this strategy
    expected_min_hold = STRATEGY_MIN_HOLD_TIMES.get(
        strat_id, 
        STRATEGY_MIN_HOLD_TIMES["default"]
    )
    
    allowed, reason = enforcer.should_allow_exit(position, exit_decision)
    
    # Property: Invalidation exits respect min_hold
    if hold_time < expected_min_hold:
        assert allowed is False, \
            f"Invalidation exit should be DEFERRED when hold_time ({hold_time:.1f}s) < min_hold ({expected_min_hold:.1f}s)"
        assert "min_hold_not_met" in reason, \
            f"Reason should contain 'min_hold_not_met', got {reason}"
    else:
        assert allowed is True, \
            f"Invalidation exit should be ALLOWED when hold_time ({hold_time:.1f}s) >= min_hold ({expected_min_hold:.1f}s)"


@settings(max_examples=100)
@given(
    hold_time=hold_time_sec,
)
def test_property_4_mean_reversion_120_seconds(
    hold_time: float,
):
    """
    Property 4 (Mean Reversion): Mean reversion strategy has 120 second min hold
    
    *For any* mean_reversion_fade position with an INVALIDATION exit:
    - IF hold_time < 120s, THEN exit SHALL be deferred
    - IF hold_time >= 120s, THEN exit SHALL be allowed
    
    **Validates: Requirements 3.4**
    """
    enforcer = MinimumHoldTimeEnforcer()
    position = make_position("mean_reversion_fade", hold_time)
    exit_decision = make_exit_decision(ExitType.INVALIDATION)
    
    allowed, reason = enforcer.should_allow_exit(position, exit_decision)
    
    # Property: mean_reversion_fade has 120 second min hold
    if hold_time < 120.0:
        assert allowed is False, \
            f"Mean reversion exit should be DEFERRED when hold_time ({hold_time:.1f}s) < 120s"
    else:
        assert allowed is True, \
            f"Mean reversion exit should be ALLOWED when hold_time ({hold_time:.1f}s) >= 120s"


@settings(max_examples=100)
@given(
    hold_time=hold_time_sec,
)
def test_property_4_trend_following_300_seconds(
    hold_time: float,
):
    """
    Property 4 (Trend Following): Trend following strategy has 300 second min hold
    
    *For any* trend_following position with an INVALIDATION exit:
    - IF hold_time < 300s, THEN exit SHALL be deferred
    - IF hold_time >= 300s, THEN exit SHALL be allowed
    
    **Validates: Requirements 3.4**
    """
    enforcer = MinimumHoldTimeEnforcer()
    position = make_position("trend_following", hold_time)
    exit_decision = make_exit_decision(ExitType.INVALIDATION)
    
    allowed, reason = enforcer.should_allow_exit(position, exit_decision)
    
    # Property: trend_following has 300 second min hold
    if hold_time < 300.0:
        assert allowed is False, \
            f"Trend following exit should be DEFERRED when hold_time ({hold_time:.1f}s) < 300s"
    else:
        assert allowed is True, \
            f"Trend following exit should be ALLOWED when hold_time ({hold_time:.1f}s) >= 300s"


@settings(max_examples=100)
@given(
    hold_time=hold_time_sec,
)
def test_property_4_default_60_seconds(
    hold_time: float,
):
    """
    Property 4 (Default): Unknown strategies have 60 second min hold
    
    *For any* unknown strategy position with an INVALIDATION exit:
    - IF hold_time < 60s, THEN exit SHALL be deferred
    - IF hold_time >= 60s, THEN exit SHALL be allowed
    
    **Validates: Requirements 3.4**
    """
    enforcer = MinimumHoldTimeEnforcer()
    position = make_position("unknown_strategy", hold_time)
    exit_decision = make_exit_decision(ExitType.INVALIDATION)
    
    allowed, reason = enforcer.should_allow_exit(position, exit_decision)
    
    # Property: unknown strategies use default 60 second min hold
    if hold_time < 60.0:
        assert allowed is False, \
            f"Unknown strategy exit should be DEFERRED when hold_time ({hold_time:.1f}s) < 60s"
    else:
        assert allowed is True, \
            f"Unknown strategy exit should be ALLOWED when hold_time ({hold_time:.1f}s) >= 60s"


@settings(max_examples=100)
@given(
    strat_id=strategy_id,
    hold_time=hold_time_sec,
)
def test_property_4_time_remaining_calculation(
    strat_id: str,
    hold_time: float,
):
    """
    Property 4 (Time Remaining): Time remaining is correctly calculated
    
    *For any* position, the time_remaining SHALL equal max(0, min_hold - hold_time).
    
    **Validates: Requirements 3.6**
    """
    enforcer = MinimumHoldTimeEnforcer()
    position = make_position(strat_id, hold_time)
    
    time_remaining = enforcer.get_time_remaining(position)
    
    # Get expected min hold time for this strategy
    expected_min_hold = STRATEGY_MIN_HOLD_TIMES.get(
        strat_id, 
        STRATEGY_MIN_HOLD_TIMES["default"]
    )
    
    expected_remaining = expected_min_hold - hold_time
    
    # Property: time_remaining is correctly calculated
    if expected_remaining <= 0:
        assert time_remaining is None, \
            f"Time remaining should be None when min_hold is satisfied"
    else:
        # Allow small tolerance for timing differences
        assert time_remaining is not None, \
            f"Time remaining should not be None when min_hold not satisfied"
        assert abs(time_remaining - expected_remaining) < 1.0, \
            f"Time remaining ({time_remaining:.1f}s) should be close to expected ({expected_remaining:.1f}s)"


@settings(max_examples=100)
@given(
    strat_id=strategy_id,
)
def test_property_4_no_opened_at_allows_exit(
    strat_id: str,
):
    """
    Property 4 (Missing Data): Positions without opened_at allow exit
    
    *For any* position without an opened_at timestamp, the exit SHALL be allowed
    (cannot enforce min_hold without timing data).
    
    **Validates: Requirements 3.2**
    """
    enforcer = MinimumHoldTimeEnforcer()
    
    # Position without opened_at
    position = {
        "symbol": "BTCUSDT",
        "side": "long",
        "strategy_id": strat_id,
        # No opened_at field
        "entry_price": 50000.0,
        "size": 0.1,
    }
    
    exit_decision = make_exit_decision(ExitType.INVALIDATION)
    
    allowed, reason = enforcer.should_allow_exit(position, exit_decision)
    
    # Property: Missing opened_at allows exit
    assert allowed is True, \
        f"Exit should be allowed when opened_at is missing"
    assert reason == "no_opened_at", \
        f"Reason should be 'no_opened_at', got {reason}"


@settings(max_examples=100)
@given(
    strat_id=strategy_id,
    hold_time=hold_time_sec,
)
def test_property_4_hold_time_info_completeness(
    strat_id: str,
    hold_time: float,
):
    """
    Property 4 (Info Completeness): Hold time info contains all required fields
    
    *For any* position, get_hold_time_info SHALL return a dict with:
    - strategy_id
    - min_hold_time_sec
    - hold_time_sec
    - time_remaining_sec
    - min_hold_satisfied
    
    **Validates: Requirements 3.6**
    """
    enforcer = MinimumHoldTimeEnforcer()
    position = make_position(strat_id, hold_time)
    
    info = enforcer.get_hold_time_info(position)
    
    # Property: All required fields are present
    assert "strategy_id" in info, "Info should contain 'strategy_id'"
    assert "min_hold_time_sec" in info, "Info should contain 'min_hold_time_sec'"
    assert "hold_time_sec" in info, "Info should contain 'hold_time_sec'"
    assert "time_remaining_sec" in info, "Info should contain 'time_remaining_sec'"
    assert "min_hold_satisfied" in info, "Info should contain 'min_hold_satisfied'"
    
    # Property: Values are consistent
    expected_min_hold = STRATEGY_MIN_HOLD_TIMES.get(
        strat_id, 
        STRATEGY_MIN_HOLD_TIMES["default"]
    )
    
    assert info["min_hold_time_sec"] == expected_min_hold, \
        f"min_hold_time_sec should be {expected_min_hold}"
    
    # min_hold_satisfied should be consistent with hold_time vs min_hold
    if info["hold_time_sec"] is not None:
        expected_satisfied = info["hold_time_sec"] >= expected_min_hold
        assert info["min_hold_satisfied"] == expected_satisfied, \
            f"min_hold_satisfied should be {expected_satisfied}"
