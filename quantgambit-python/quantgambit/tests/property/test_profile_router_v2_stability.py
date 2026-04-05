"""
Property-based tests for Profile Router v2 Stability (Hysteresis).

Feature: profile-router-v2, Property 5: Hysteresis State Transitions
Validates: Requirements 2.3

Tests that for any HysteresisTracker and for any sequence of values, state
transitions SHALL only occur when:
- Transitioning from low_state to high_state: value exceeds entry_threshold
- Transitioning from high_state to low_state: value falls below exit_threshold

The tracker SHALL NOT flip-flop when values oscillate between entry and exit thresholds.
"""

import pytest
from hypothesis import given, strategies as st, settings, assume
from typing import List, Tuple

from quantgambit.deeptrader_core.profiles.hysteresis_tracker import (
    HysteresisTracker,
    HysteresisState,
    VOLATILITY_REGIMES,
    TREND_DIRECTIONS,
)
from quantgambit.deeptrader_core.profiles.router_config import RouterConfig


# ============================================================================
# Hypothesis Strategies
# ============================================================================

# Symbol names
symbols = st.sampled_from(["BTC-USDT", "ETH-USDT", "SOL-USDT", "DOGE-USDT"])

# Category names
categories = st.sampled_from(["vol_regime_high", "vol_regime_low", "trend_up", "trend_down"])

# Threshold values (entry > exit for high bands)
entry_thresholds = st.floats(min_value=0.5, max_value=2.0, allow_nan=False, allow_infinity=False)
exit_thresholds = st.floats(min_value=0.1, max_value=1.5, allow_nan=False, allow_infinity=False)

# Value sequences
value_sequences = st.lists(
    st.floats(min_value=0.0, max_value=3.0, allow_nan=False, allow_infinity=False),
    min_size=1,
    max_size=50
)

# ATR ratio values for volatility regime
atr_ratio_values = st.floats(min_value=0.3, max_value=2.0, allow_nan=False, allow_infinity=False)

# EMA spread values for trend direction
ema_spread_values = st.floats(min_value=-0.005, max_value=0.005, allow_nan=False, allow_infinity=False)


@st.composite
def valid_threshold_pairs(draw) -> Tuple[float, float]:
    """Generate valid (entry, exit) threshold pairs where entry > exit."""
    entry = draw(st.floats(min_value=0.5, max_value=2.0, allow_nan=False, allow_infinity=False))
    exit_val = draw(st.floats(min_value=0.1, max_value=entry - 0.01, allow_nan=False, allow_infinity=False))
    assume(entry > exit_val)
    return (entry, exit_val)


@st.composite
def oscillating_value_sequences(draw, entry: float, exit_val: float) -> List[float]:
    """
    Generate value sequences that oscillate between entry and exit thresholds.
    These should NOT cause state transitions due to hysteresis.
    """
    # Generate values strictly between exit and entry thresholds
    mid = (entry + exit_val) / 2
    half_range = (entry - exit_val) / 2 * 0.9  # Stay within 90% of the range
    
    values = []
    for _ in range(draw(st.integers(min_value=5, max_value=20))):
        offset = draw(st.floats(min_value=-half_range, max_value=half_range, allow_nan=False, allow_infinity=False))
        values.append(mid + offset)
    
    return values


# ============================================================================
# Property Tests
# ============================================================================

class TestHysteresisStateTransitions:
    """
    Property 5: Hysteresis State Transitions
    
    For any HysteresisTracker and for any sequence of values, state transitions
    SHALL only occur when:
    - Transitioning from low_state to high_state: value exceeds entry_threshold
    - Transitioning from high_state to low_state: value falls below exit_threshold
    
    The tracker SHALL NOT flip-flop when values oscillate between entry and exit thresholds.
    
    **Feature: profile-router-v2, Property 5: Hysteresis State Transitions**
    **Validates: Requirements 2.3**
    """
    
    @given(
        symbol=symbols,
        category=categories,
        thresholds=valid_threshold_pairs(),
        values=value_sequences
    )
    @settings(max_examples=100)
    def test_upward_transition_requires_entry_threshold(
        self,
        symbol: str,
        category: str,
        thresholds: Tuple[float, float],
        values: List[float]
    ):
        """
        Property 5: Hysteresis State Transitions
        
        For any sequence of values starting in low_state, transition to high_state
        SHALL only occur when value exceeds entry_threshold.
        
        **Validates: Requirements 2.3**
        """
        entry_threshold, exit_threshold = thresholds
        tracker = HysteresisTracker()
        
        # Start in low state
        current_state = "low"
        
        for value in values:
            state = tracker.get_state(
                symbol=symbol,
                category=category,
                value=value,
                entry_threshold=entry_threshold,
                exit_threshold=exit_threshold,
                high_state="high",
                low_state="low",
                default_state="low"
            )
            
            # If we transitioned to high, value must have exceeded entry threshold
            if current_state == "low" and state == "high":
                assert value > entry_threshold, \
                    f"Transition to high occurred with value={value} <= entry_threshold={entry_threshold}"
            
            current_state = state
    
    @given(
        symbol=symbols,
        category=categories,
        thresholds=valid_threshold_pairs(),
        values=value_sequences
    )
    @settings(max_examples=100)
    def test_downward_transition_requires_exit_threshold(
        self,
        symbol: str,
        category: str,
        thresholds: Tuple[float, float],
        values: List[float]
    ):
        """
        Property 5: Hysteresis State Transitions
        
        For any sequence of values starting in high_state, transition to low_state
        SHALL only occur when value falls below exit_threshold.
        
        **Validates: Requirements 2.3**
        """
        entry_threshold, exit_threshold = thresholds
        tracker = HysteresisTracker()
        
        # Initialize in high state by first exceeding entry threshold
        tracker.get_state(
            symbol=symbol,
            category=category,
            value=entry_threshold + 0.5,  # Ensure we start in high state
            entry_threshold=entry_threshold,
            exit_threshold=exit_threshold,
            high_state="high",
            low_state="low",
            default_state="low"
        )
        
        current_state = "high"
        
        for value in values:
            state = tracker.get_state(
                symbol=symbol,
                category=category,
                value=value,
                entry_threshold=entry_threshold,
                exit_threshold=exit_threshold,
                high_state="high",
                low_state="low",
                default_state="low"
            )
            
            # If we transitioned to low, value must have fallen below exit threshold
            if current_state == "high" and state == "low":
                assert value < exit_threshold, \
                    f"Transition to low occurred with value={value} >= exit_threshold={exit_threshold}"
            
            current_state = state
    
    @given(
        symbol=symbols,
        category=categories,
        entry=st.floats(min_value=1.0, max_value=1.5, allow_nan=False, allow_infinity=False),
        exit_val=st.floats(min_value=0.5, max_value=0.9, allow_nan=False, allow_infinity=False),
        num_oscillations=st.integers(min_value=5, max_value=20)
    )
    @settings(max_examples=100)
    def test_no_flip_flop_in_dead_zone(
        self,
        symbol: str,
        category: str,
        entry: float,
        exit_val: float,
        num_oscillations: int
    ):
        """
        Property 5: Hysteresis State Transitions
        
        For any sequence of values oscillating between entry and exit thresholds
        (the "dead zone"), the tracker SHALL NOT flip-flop between states.
        
        **Validates: Requirements 2.3**
        """
        assume(entry > exit_val + 0.1)  # Ensure meaningful dead zone
        
        tracker = HysteresisTracker()
        
        # Start in low state
        initial_state = tracker.get_state(
            symbol=symbol,
            category=category,
            value=exit_val - 0.1,  # Start below exit threshold
            entry_threshold=entry,
            exit_threshold=exit_val,
            high_state="high",
            low_state="low",
            default_state="low"
        )
        assert initial_state == "low"
        
        # Generate values in the dead zone (between exit and entry)
        mid = (entry + exit_val) / 2
        dead_zone_values = [mid + (0.1 if i % 2 == 0 else -0.1) for i in range(num_oscillations)]
        
        # Ensure all values are in dead zone
        for v in dead_zone_values:
            assume(exit_val < v < entry)
        
        # Apply all values - state should remain "low"
        for value in dead_zone_values:
            state = tracker.get_state(
                symbol=symbol,
                category=category,
                value=value,
                entry_threshold=entry,
                exit_threshold=exit_val,
                high_state="high",
                low_state="low",
                default_state="low"
            )
            assert state == "low", \
                f"State changed to {state} with value={value} in dead zone [{exit_val}, {entry}]"
    
    @given(
        symbol=symbols,
        category=categories,
        thresholds=valid_threshold_pairs()
    )
    @settings(max_examples=100)
    def test_state_is_deterministic(
        self,
        symbol: str,
        category: str,
        thresholds: Tuple[float, float]
    ):
        """
        Property 5: Hysteresis State Transitions
        
        For any given state history, calling get_state with the same value
        SHALL produce the same result.
        
        **Validates: Requirements 2.3**
        """
        entry_threshold, exit_threshold = thresholds
        
        # Create two trackers with identical history
        tracker1 = HysteresisTracker()
        tracker2 = HysteresisTracker()
        
        # Apply same sequence to both
        test_values = [0.3, 0.8, 1.5, 1.2, 0.4, 0.9]
        
        for value in test_values:
            state1 = tracker1.get_state(
                symbol=symbol,
                category=category,
                value=value,
                entry_threshold=entry_threshold,
                exit_threshold=exit_threshold,
                high_state="high",
                low_state="low",
                default_state="low"
            )
            state2 = tracker2.get_state(
                symbol=symbol,
                category=category,
                value=value,
                entry_threshold=entry_threshold,
                exit_threshold=exit_threshold,
                high_state="high",
                low_state="low",
                default_state="low"
            )
            assert state1 == state2, \
                f"Non-deterministic state: {state1} != {state2} for value={value}"


class TestVolatilityRegimeHysteresis:
    """Tests for volatility regime hysteresis using RouterConfig bands."""
    
    @given(atr_ratio=atr_ratio_values)
    @settings(max_examples=100)
    def test_volatility_regime_returns_valid_state(self, atr_ratio: float):
        """
        Property 5: Hysteresis State Transitions
        
        For any ATR ratio, get_volatility_regime SHALL return a valid volatility regime.
        
        **Validates: Requirements 2.3**
        """
        tracker = HysteresisTracker()
        config = RouterConfig()
        
        regime = tracker.get_volatility_regime("BTC-USDT", atr_ratio, config)
        
        assert regime in VOLATILITY_REGIMES, \
            f"Invalid volatility regime '{regime}', expected one of {VOLATILITY_REGIMES}"
    
    @given(
        symbol=symbols,
        num_values=st.integers(min_value=10, max_value=30)
    )
    @settings(max_examples=100)
    def test_volatility_regime_hysteresis_prevents_flip_flop(
        self,
        symbol: str,
        num_values: int
    ):
        """
        Property 5: Hysteresis State Transitions
        
        For values oscillating near volatility thresholds, the regime SHALL NOT
        flip-flop rapidly.
        
        **Validates: Requirements 2.3**
        """
        tracker = HysteresisTracker()
        config = RouterConfig()
        
        # Default bands: high entry=1.35, high exit=1.25
        # Generate values oscillating around 1.30 (in the dead zone)
        values = [1.30 + (0.02 if i % 2 == 0 else -0.02) for i in range(num_values)]
        
        # Start in normal state
        tracker.get_volatility_regime(symbol, 1.0, config)
        
        regimes = []
        for atr_ratio in values:
            regime = tracker.get_volatility_regime(symbol, atr_ratio, config)
            regimes.append(regime)
        
        # Count transitions
        transitions = sum(1 for i in range(1, len(regimes)) if regimes[i] != regimes[i-1])
        
        # Should have very few transitions (ideally 0) when oscillating in dead zone
        assert transitions <= 2, \
            f"Too many transitions ({transitions}) when oscillating in dead zone: {regimes}"


class TestTrendDirectionHysteresis:
    """Tests for trend direction hysteresis using RouterConfig bands."""
    
    @given(ema_spread=ema_spread_values)
    @settings(max_examples=100)
    def test_trend_direction_returns_valid_state(self, ema_spread: float):
        """
        Property 5: Hysteresis State Transitions
        
        For any EMA spread, get_trend_direction SHALL return a valid trend direction.
        
        **Validates: Requirements 2.3**
        """
        tracker = HysteresisTracker()
        config = RouterConfig()
        
        direction = tracker.get_trend_direction("BTC-USDT", ema_spread, config)
        
        assert direction in TREND_DIRECTIONS, \
            f"Invalid trend direction '{direction}', expected one of {TREND_DIRECTIONS}"
    
    @given(
        symbol=symbols,
        num_values=st.integers(min_value=10, max_value=30)
    )
    @settings(max_examples=100)
    def test_trend_direction_hysteresis_prevents_flip_flop(
        self,
        symbol: str,
        num_values: int
    ):
        """
        Property 5: Hysteresis State Transitions
        
        For values oscillating near trend thresholds, the direction SHALL NOT
        flip-flop rapidly.
        
        **Validates: Requirements 2.3**
        """
        tracker = HysteresisTracker()
        config = RouterConfig()
        
        # Default bands: entry=0.0012, exit=0.0008
        # Generate values oscillating around 0.001 (in the dead zone)
        values = [0.001 + (0.0001 if i % 2 == 0 else -0.0001) for i in range(num_values)]
        
        # Start in flat state
        tracker.get_trend_direction(symbol, 0.0, config)
        
        directions = []
        for ema_spread in values:
            direction = tracker.get_trend_direction(symbol, ema_spread, config)
            directions.append(direction)
        
        # Count transitions
        transitions = sum(1 for i in range(1, len(directions)) if directions[i] != directions[i-1])
        
        # Should have very few transitions when oscillating in dead zone
        assert transitions <= 2, \
            f"Too many transitions ({transitions}) when oscillating in dead zone: {directions}"


class TestHysteresisTrackerStateManagement:
    """Tests for HysteresisTracker state management methods."""
    
    @given(
        symbol=symbols,
        category=categories,
        value=st.floats(min_value=0.0, max_value=2.0, allow_nan=False, allow_infinity=False)
    )
    @settings(max_examples=100)
    def test_get_state_info_returns_correct_state(
        self,
        symbol: str,
        category: str,
        value: float
    ):
        """
        Property 5: Hysteresis State Transitions
        
        After calling get_state, get_state_info SHALL return the correct state.
        
        **Validates: Requirements 2.3**
        """
        tracker = HysteresisTracker()
        
        state = tracker.get_state(
            symbol=symbol,
            category=category,
            value=value,
            entry_threshold=1.0,
            exit_threshold=0.5,
            high_state="high",
            low_state="low",
            default_state="low"
        )
        
        state_info = tracker.get_state_info(symbol, category)
        
        assert state_info is not None, "State info should exist after get_state"
        assert state_info.current_state == state, \
            f"State info mismatch: {state_info.current_state} != {state}"
        assert state_info.last_value == value, \
            f"Last value mismatch: {state_info.last_value} != {value}"
    
    @given(symbol=symbols, category=categories)
    @settings(max_examples=100)
    def test_reset_state_clears_state(self, symbol: str, category: str):
        """
        Property 5: Hysteresis State Transitions
        
        After reset_state, get_state_info SHALL return None.
        
        **Validates: Requirements 2.3**
        """
        tracker = HysteresisTracker()
        
        # Create state
        tracker.get_state(
            symbol=symbol,
            category=category,
            value=1.5,
            entry_threshold=1.0,
            exit_threshold=0.5,
            high_state="high",
            low_state="low",
            default_state="low"
        )
        
        # Reset
        tracker.reset_state(symbol, category)
        
        # Verify cleared
        state_info = tracker.get_state_info(symbol, category)
        assert state_info is None, "State info should be None after reset"
    
    @given(symbol=symbols)
    @settings(max_examples=100)
    def test_reset_symbol_clears_all_categories(self, symbol: str):
        """
        Property 5: Hysteresis State Transitions
        
        After reset_symbol, all states for that symbol SHALL be cleared.
        
        **Validates: Requirements 2.3**
        """
        tracker = HysteresisTracker()
        
        # Create states for multiple categories
        for category in ["cat1", "cat2", "cat3"]:
            tracker.get_state(
                symbol=symbol,
                category=category,
                value=1.5,
                entry_threshold=1.0,
                exit_threshold=0.5,
                high_state="high",
                low_state="low",
                default_state="low"
            )
        
        # Reset symbol
        tracker.reset_symbol(symbol)
        
        # Verify all cleared
        for category in ["cat1", "cat2", "cat3"]:
            state_info = tracker.get_state_info(symbol, category)
            assert state_info is None, f"State info for {category} should be None after reset_symbol"
    
    @given(
        symbol=symbols,
        category=categories,
        values=st.lists(
            st.floats(min_value=0.0, max_value=2.0, allow_nan=False, allow_infinity=False),
            min_size=5,
            max_size=20
        )
    )
    @settings(max_examples=100)
    def test_transition_count_increments_correctly(
        self,
        symbol: str,
        category: str,
        values: List[float]
    ):
        """
        Property 5: Hysteresis State Transitions
        
        Transition count SHALL increment only when state actually changes.
        Note: The first call may cause a transition from default state if the
        value triggers a state change.
        
        **Validates: Requirements 2.3**
        """
        tracker = HysteresisTracker()
        
        # Track state changes including the initial transition from default
        prev_state = "low"  # This is the default_state we'll use
        expected_transitions = 0
        
        for value in values:
            state = tracker.get_state(
                symbol=symbol,
                category=category,
                value=value,
                entry_threshold=1.0,
                exit_threshold=0.5,
                high_state="high",
                low_state="low",
                default_state="low"
            )
            
            # Count transition if state changed from previous
            if state != prev_state:
                expected_transitions += 1
            
            prev_state = state
        
        actual_transitions = tracker.get_transition_count(symbol, category)
        assert actual_transitions == expected_transitions, \
            f"Transition count mismatch: {actual_transitions} != {expected_transitions}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


# ============================================================================
# ProfileStabilityManager Property Tests
# ============================================================================

from quantgambit.deeptrader_core.profiles.profile_stability_manager import (
    ProfileStabilityManager,
    ProfileSelection,
    StabilityMetrics,
    SAFETY_DISQUALIFIERS,
)


# Additional strategies for ProfileStabilityManager tests
profile_ids = st.sampled_from([
    "momentum_btc_high_vol",
    "mean_revert_eth_low_vol",
    "breakout_sol_normal",
    "fade_doge_asia",
    "trend_follow_btc_us",
])

scores = st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False)

timestamps = st.floats(min_value=1000000000.0, max_value=2000000000.0, allow_nan=False, allow_infinity=False)

ttl_values = st.floats(min_value=1.0, max_value=600.0, allow_nan=False, allow_infinity=False)

switch_margins = st.floats(min_value=0.0, max_value=0.5, allow_nan=False, allow_infinity=False)

safety_reasons = st.sampled_from([
    "spread_too_wide",
    "depth_too_low",
    "data_stale",
    "risk_mode_off",
    "book_age_exceeded",
    "trade_age_exceeded",
    "tps_too_low",
])


@st.composite
def ttl_switch_case(draw):
    """Generate (initial_profile, new_profile, initial_score, new_score) without heavy assume() filtering."""
    initial_profile = draw(profile_ids)
    # Pick a different profile deterministically (avoid assume-filtering).
    choices = [p for p in ["momentum_btc_high_vol", "mean_revert_eth_low_vol", "breakout_sol_normal", "fade_doge_asia", "trend_follow_btc_us"] if p != initial_profile]
    new_profile = draw(st.sampled_from(choices))

    switch_margin = 0.10
    initial_score = draw(st.floats(min_value=0.0, max_value=1.0 - (switch_margin + 0.01), allow_nan=False, allow_infinity=False))
    new_score = draw(st.floats(min_value=initial_score + switch_margin + 0.001, max_value=1.0, allow_nan=False, allow_infinity=False))
    return initial_profile, new_profile, initial_score, new_score


@st.composite
def router_configs_for_stability(draw) -> RouterConfig:
    """Generate RouterConfig with valid stability parameters."""
    return RouterConfig(
        min_profile_ttl_sec=draw(ttl_values),
        switch_margin=draw(switch_margins),
    )


class TestTTLPreventsPrematureSwitching:
    """
    Property 4: TTL Prevents Premature Switching
    
    For any symbol with an active profile selection, and for any sequence of
    select_profiles calls within MIN_PROFILE_TTL_SEC, the same profile SHALL
    be returned unless a safety disqualifier triggers, regardless of score changes.
    
    **Feature: profile-router-v2, Property 4: TTL Prevents Premature Switching**
    **Validates: Requirements 2.1, 2.2**
    """
    
    @given(
        symbol=symbols,
        initial_profile=profile_ids,
        new_profile=profile_ids,
        initial_score=scores,
        new_score=scores,
        initial_time=timestamps,
        time_delta=st.floats(min_value=0.1, max_value=119.9, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=100)
    def test_ttl_blocks_switch_within_period(
        self,
        symbol: str,
        initial_profile: str,
        new_profile: str,
        initial_score: float,
        new_score: float,
        initial_time: float,
        time_delta: float,
    ):
        """
        Property 4: TTL Prevents Premature Switching
        
        For any profile selection within TTL period, should_switch SHALL return False
        unless safety_disqualified is True.
        
        **Validates: Requirements 2.1, 2.2**
        """
        assume(initial_profile != new_profile)  # Different profiles
        
        config = RouterConfig(min_profile_ttl_sec=120.0, switch_margin=0.10)
        manager = ProfileStabilityManager(config)
        
        # Record initial selection
        manager.record_selection(symbol, initial_profile, initial_score, initial_time)
        
        # Try to switch within TTL (time_delta < 120)
        current_time = initial_time + time_delta
        
        should_switch = manager.should_switch(
            symbol=symbol,
            new_profile_id=new_profile,
            new_score=new_score,
            current_time=current_time,
            safety_disqualified=False,
        )
        
        # Should NOT switch within TTL
        assert should_switch is False, \
            f"Switch allowed within TTL: time_delta={time_delta}s < TTL=120s"
    
    @given(
        symbol=symbols,
        case=ttl_switch_case(),
        initial_time=timestamps,
        ttl=ttl_values,
    )
    @settings(max_examples=100)
    def test_ttl_allows_switch_after_expiry(
        self,
        symbol: str,
        case,
        initial_time: float,
        ttl: float,
    ):
        """
        Property 4: TTL Prevents Premature Switching
        
        For any profile selection after TTL expiry, should_switch SHALL return True
        if the new score exceeds current score by switch_margin.
        
        **Validates: Requirements 2.1, 2.2**
        """
        switch_margin = 0.10
        initial_profile, new_profile, initial_score, new_score = case
        
        config = RouterConfig(min_profile_ttl_sec=ttl, switch_margin=switch_margin)
        manager = ProfileStabilityManager(config)
        
        # Record initial selection
        manager.record_selection(symbol, initial_profile, initial_score, initial_time)
        
        # Try to switch after TTL expiry
        current_time = initial_time + ttl + 1.0  # 1 second after TTL
        
        should_switch = manager.should_switch(
            symbol=symbol,
            new_profile_id=new_profile,
            new_score=new_score,
            current_time=current_time,
            safety_disqualified=False,
        )
        
        # Should switch after TTL with sufficient score margin
        assert should_switch is True, \
            f"Switch blocked after TTL expiry: time_delta={ttl + 1.0}s > TTL={ttl}s, " \
            f"score_diff={new_score - initial_score:.3f} > margin={switch_margin}"
    
    @given(
        symbol=symbols,
        profile=profile_ids,
        score=scores,
        initial_time=timestamps,
        num_calls=st.integers(min_value=2, max_value=10),
    )
    @settings(max_examples=100)
    def test_same_profile_no_switch_needed(
        self,
        symbol: str,
        profile: str,
        score: float,
        initial_time: float,
        num_calls: int,
    ):
        """
        Property 4: TTL Prevents Premature Switching
        
        For any sequence of calls with the same profile_id, should_switch SHALL
        return False (no switch needed for same profile).
        
        **Validates: Requirements 2.1, 2.2**
        """
        config = RouterConfig(min_profile_ttl_sec=120.0, switch_margin=0.10)
        manager = ProfileStabilityManager(config)
        
        # Record initial selection
        manager.record_selection(symbol, profile, score, initial_time)
        
        # Multiple calls with same profile after TTL
        for i in range(num_calls):
            current_time = initial_time + 200.0 + i * 10.0  # After TTL
            
            should_switch = manager.should_switch(
                symbol=symbol,
                new_profile_id=profile,  # Same profile
                new_score=score + 0.2,  # Higher score
                current_time=current_time,
                safety_disqualified=False,
            )
            
            # Should NOT switch to same profile
            assert should_switch is False, \
                f"Switch suggested for same profile {profile}"


class TestSwitchMarginEnforcement:
    """
    Property 6: Switch Margin Enforcement
    
    For any profile switch attempt after TTL expiration, the switch SHALL only
    occur if the new profile's score exceeds the current profile's score by at
    least SWITCH_MARGIN (default 0.10).
    
    **Feature: profile-router-v2, Property 6: Switch Margin Enforcement**
    **Validates: Requirements 2.4**
    """
    
    @given(
        symbol=symbols,
        initial_profile=profile_ids,
        new_profile=profile_ids,
        initial_score=st.floats(min_value=0.2, max_value=0.8, allow_nan=False, allow_infinity=False),
        score_diff=st.floats(min_value=-0.3, max_value=0.3, allow_nan=False, allow_infinity=False),
        switch_margin=st.floats(min_value=0.05, max_value=0.3, allow_nan=False, allow_infinity=False),
        initial_time=timestamps,
    )
    @settings(max_examples=100)
    def test_switch_margin_enforced(
        self,
        symbol: str,
        initial_profile: str,
        new_profile: str,
        initial_score: float,
        score_diff: float,
        switch_margin: float,
        initial_time: float,
    ):
        """
        Property 6: Switch Margin Enforcement
        
        For any score difference, switch SHALL only occur if score_diff >= switch_margin.
        
        **Validates: Requirements 2.4**
        """
        assume(initial_profile != new_profile)  # Different profiles
        
        # Avoid edge cases where score_diff is very close to switch_margin
        # (floating point precision issues)
        assume(abs(score_diff - switch_margin) > 0.001)
        
        new_score = initial_score + score_diff
        assume(0.0 <= new_score <= 1.0)  # Valid score range
        
        config = RouterConfig(min_profile_ttl_sec=60.0, switch_margin=switch_margin)
        manager = ProfileStabilityManager(config)
        
        # Record initial selection
        manager.record_selection(symbol, initial_profile, initial_score, initial_time)
        
        # Try to switch after TTL
        current_time = initial_time + 100.0  # After TTL
        
        should_switch = manager.should_switch(
            symbol=symbol,
            new_profile_id=new_profile,
            new_score=new_score,
            current_time=current_time,
            safety_disqualified=False,
        )
        
        # Switch should only occur if score_diff >= switch_margin
        expected_switch = score_diff >= switch_margin
        assert should_switch == expected_switch, \
            f"Switch margin not enforced: score_diff={score_diff:.3f}, " \
            f"margin={switch_margin:.3f}, expected={expected_switch}, got={should_switch}"
    
    @given(
        symbol=symbols,
        initial_profile=profile_ids,
        new_profile=profile_ids,
        initial_score=st.floats(min_value=0.3, max_value=0.7, allow_nan=False, allow_infinity=False),
        initial_time=timestamps,
    )
    @settings(max_examples=100)
    def test_switch_blocked_when_score_lower(
        self,
        symbol: str,
        initial_profile: str,
        new_profile: str,
        initial_score: float,
        initial_time: float,
    ):
        """
        Property 6: Switch Margin Enforcement
        
        For any new profile with lower score, switch SHALL be blocked.
        
        **Validates: Requirements 2.4**
        """
        assume(initial_profile != new_profile)
        
        config = RouterConfig(min_profile_ttl_sec=60.0, switch_margin=0.10)
        manager = ProfileStabilityManager(config)
        
        # Record initial selection
        manager.record_selection(symbol, initial_profile, initial_score, initial_time)
        
        # Try to switch with lower score
        new_score = initial_score - 0.05  # Lower score
        current_time = initial_time + 100.0  # After TTL
        
        should_switch = manager.should_switch(
            symbol=symbol,
            new_profile_id=new_profile,
            new_score=new_score,
            current_time=current_time,
            safety_disqualified=False,
        )
        
        assert should_switch is False, \
            f"Switch allowed with lower score: new={new_score:.3f} < current={initial_score:.3f}"
    
    @given(
        symbol=symbols,
        initial_profile=profile_ids,
        new_profile=profile_ids,
        initial_score=st.floats(min_value=0.3, max_value=0.7, allow_nan=False, allow_infinity=False),
        initial_time=timestamps,
    )
    @settings(max_examples=100)
    def test_switch_blocked_when_margin_not_met(
        self,
        symbol: str,
        initial_profile: str,
        new_profile: str,
        initial_score: float,
        initial_time: float,
    ):
        """
        Property 6: Switch Margin Enforcement
        
        For any new profile with score slightly higher but below margin, switch SHALL be blocked.
        
        **Validates: Requirements 2.4**
        """
        assume(initial_profile != new_profile)
        
        switch_margin = 0.10
        config = RouterConfig(min_profile_ttl_sec=60.0, switch_margin=switch_margin)
        manager = ProfileStabilityManager(config)
        
        # Record initial selection
        manager.record_selection(symbol, initial_profile, initial_score, initial_time)
        
        # Try to switch with score just below margin
        new_score = initial_score + switch_margin - 0.01  # Just below margin
        current_time = initial_time + 100.0  # After TTL
        
        should_switch = manager.should_switch(
            symbol=symbol,
            new_profile_id=new_profile,
            new_score=new_score,
            current_time=current_time,
            safety_disqualified=False,
        )
        
        assert should_switch is False, \
            f"Switch allowed with score below margin: diff={new_score - initial_score:.3f} < margin={switch_margin}"


class TestSafetyDisqualifierBypass:
    """
    Property 7: Safety Disqualifier Bypass
    
    For any ContextVector with a safety disqualifier (spread_too_wide, depth_too_low,
    data_stale, risk_mode_off), profile switching SHALL be allowed immediately
    regardless of TTL or switch margin.
    
    **Feature: profile-router-v2, Property 7: Safety Disqualifier Bypass**
    **Validates: Requirements 2.5**
    """
    
    @given(
        symbol=symbols,
        initial_profile=profile_ids,
        new_profile=profile_ids,
        initial_score=scores,
        new_score=scores,
        initial_time=timestamps,
        time_delta=st.floats(min_value=0.1, max_value=60.0, allow_nan=False, allow_infinity=False),
        safety_reason=safety_reasons,
    )
    @settings(max_examples=100)
    def test_safety_disqualifier_bypasses_ttl(
        self,
        symbol: str,
        initial_profile: str,
        new_profile: str,
        initial_score: float,
        new_score: float,
        initial_time: float,
        time_delta: float,
        safety_reason: str,
    ):
        """
        Property 7: Safety Disqualifier Bypass
        
        For any safety disqualifier, switch SHALL be allowed regardless of TTL.
        
        **Validates: Requirements 2.5**
        """
        assume(initial_profile != new_profile)
        
        config = RouterConfig(min_profile_ttl_sec=120.0, switch_margin=0.10)
        manager = ProfileStabilityManager(config)
        
        # Record initial selection
        manager.record_selection(symbol, initial_profile, initial_score, initial_time)
        
        # Try to switch within TTL but with safety disqualifier
        current_time = initial_time + time_delta  # Within TTL
        
        should_switch = manager.should_switch(
            symbol=symbol,
            new_profile_id=new_profile,
            new_score=new_score,
            current_time=current_time,
            safety_disqualified=True,
            safety_reasons=[safety_reason],
        )
        
        # Should switch due to safety disqualifier
        assert should_switch is True, \
            f"Safety disqualifier {safety_reason} did not bypass TTL"
    
    @given(
        symbol=symbols,
        initial_profile=profile_ids,
        new_profile=profile_ids,
        initial_score=st.floats(min_value=0.5, max_value=0.9, allow_nan=False, allow_infinity=False),
        initial_time=timestamps,
        safety_reason=safety_reasons,
    )
    @settings(max_examples=100)
    def test_safety_disqualifier_bypasses_margin(
        self,
        symbol: str,
        initial_profile: str,
        new_profile: str,
        initial_score: float,
        initial_time: float,
        safety_reason: str,
    ):
        """
        Property 7: Safety Disqualifier Bypass
        
        For any safety disqualifier, switch SHALL be allowed regardless of switch margin.
        
        **Validates: Requirements 2.5**
        """
        assume(initial_profile != new_profile)
        
        config = RouterConfig(min_profile_ttl_sec=60.0, switch_margin=0.10)
        manager = ProfileStabilityManager(config)
        
        # Record initial selection
        manager.record_selection(symbol, initial_profile, initial_score, initial_time)
        
        # Try to switch with lower score but safety disqualifier
        new_score = initial_score - 0.2  # Much lower score
        current_time = initial_time + 100.0  # After TTL
        
        should_switch = manager.should_switch(
            symbol=symbol,
            new_profile_id=new_profile,
            new_score=new_score,
            current_time=current_time,
            safety_disqualified=True,
            safety_reasons=[safety_reason],
        )
        
        # Should switch due to safety disqualifier despite lower score
        assert should_switch is True, \
            f"Safety disqualifier {safety_reason} did not bypass switch margin"
    
    @given(reason=st.text(min_size=1, max_size=50))
    @settings(max_examples=100)
    def test_is_safety_disqualifier_recognizes_known_reasons(self, reason: str):
        """
        Property 7: Safety Disqualifier Bypass
        
        For any known safety disqualifier keyword, is_safety_disqualifier SHALL return True.
        
        **Validates: Requirements 2.5**
        """
        # Test each known safety disqualifier
        for disqualifier in SAFETY_DISQUALIFIERS:
            test_reason = f"some_prefix_{disqualifier}_some_suffix"
            assert ProfileStabilityManager.is_safety_disqualifier(test_reason) is True, \
                f"Failed to recognize safety disqualifier: {disqualifier}"
    
    @given(
        symbol=symbols,
        initial_profile=profile_ids,
        new_profile=profile_ids,
        initial_score=scores,
        new_score=scores,
        initial_time=timestamps,
    )
    @settings(max_examples=100)
    def test_no_safety_disqualifier_respects_ttl(
        self,
        symbol: str,
        initial_profile: str,
        new_profile: str,
        initial_score: float,
        new_score: float,
        initial_time: float,
    ):
        """
        Property 7: Safety Disqualifier Bypass
        
        Without safety disqualifier, TTL SHALL be respected.
        
        **Validates: Requirements 2.5**
        """
        assume(initial_profile != new_profile)
        
        config = RouterConfig(min_profile_ttl_sec=120.0, switch_margin=0.10)
        manager = ProfileStabilityManager(config)
        
        # Record initial selection
        manager.record_selection(symbol, initial_profile, initial_score, initial_time)
        
        # Try to switch within TTL without safety disqualifier
        current_time = initial_time + 60.0  # Within TTL
        
        should_switch = manager.should_switch(
            symbol=symbol,
            new_profile_id=new_profile,
            new_score=new_score,
            current_time=current_time,
            safety_disqualified=False,
        )
        
        # Should NOT switch without safety disqualifier
        assert should_switch is False, \
            f"Switch allowed within TTL without safety disqualifier"


class TestProfileStabilityManagerMetrics:
    """Tests for ProfileStabilityManager metrics tracking (Requirement 2.6)."""
    
    @given(
        symbol=symbols,
        profiles=st.lists(profile_ids, min_size=2, max_size=10),
        initial_time=timestamps,
    )
    @settings(max_examples=100)
    def test_switch_count_increments_correctly(
        self,
        symbol: str,
        profiles: List[str],
        initial_time: float,
    ):
        """
        Property 4: TTL Prevents Premature Switching
        
        Switch count SHALL increment only when profile actually changes.
        
        **Validates: Requirements 2.6**
        """
        config = RouterConfig(min_profile_ttl_sec=1.0, switch_margin=0.0)  # Minimal TTL and margin
        manager = ProfileStabilityManager(config)
        
        expected_switches = 0
        prev_profile = None
        
        for i, profile in enumerate(profiles):
            current_time = initial_time + (i + 1) * 10.0  # 10 seconds apart (after TTL)
            
            # Record selection
            manager.record_selection(symbol, profile, 0.5, current_time)
            
            # Count switch if profile changed
            if prev_profile is not None and profile != prev_profile:
                expected_switches += 1
            
            prev_profile = profile
        
        metrics = manager.get_metrics(symbol)
        assert metrics['switch_count'] == expected_switches, \
            f"Switch count mismatch: {metrics['switch_count']} != {expected_switches}"
    
    @given(
        symbol=symbols,
        profile=profile_ids,
        score=scores,
        initial_time=timestamps,
    )
    @settings(max_examples=100)
    def test_current_profile_tracked_correctly(
        self,
        symbol: str,
        profile: str,
        score: float,
        initial_time: float,
    ):
        """
        Property 4: TTL Prevents Premature Switching
        
        Current profile SHALL be tracked correctly after selection.
        
        **Validates: Requirements 2.6**
        """
        config = RouterConfig()
        manager = ProfileStabilityManager(config)
        
        # Record selection
        manager.record_selection(symbol, profile, score, initial_time)
        
        # Verify current profile
        assert manager.get_current_profile(symbol) == profile
        assert manager.get_current_score(symbol) == score
        
        metrics = manager.get_metrics(symbol)
        assert metrics['current_profile'] == profile
        assert metrics['current_profile_score'] == score
    
    @given(symbol=symbols)
    @settings(max_examples=100)
    def test_reset_clears_all_state(self, symbol: str):
        """
        Property 4: TTL Prevents Premature Switching
        
        Reset SHALL clear all state for a symbol.
        
        **Validates: Requirements 2.6**
        """
        config = RouterConfig()
        manager = ProfileStabilityManager(config)
        
        # Record some selections
        manager.record_selection(symbol, "profile1", 0.5, 1000000000.0)
        manager.record_selection(symbol, "profile2", 0.6, 1000000100.0)
        
        # Reset
        manager.reset_symbol(symbol)
        
        # Verify cleared
        assert manager.get_current_profile(symbol) is None
        assert manager.get_current_score(symbol) == 0.0
        
        metrics = manager.get_metrics(symbol)
        assert metrics['switch_count'] == 0
        assert metrics['current_profile'] is None
