"""
Property-based tests for Warm Start System.

Feature: trading-pipeline-integration

These tests verify the correctness properties of the warm start system,
ensuring proper state loading, validation, and staleness detection.

Uses hypothesis library with minimum 100 iterations per property test.

**Validates: Requirements 3.1, 3.3, 3.4, 3.5, 3.6**
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

from quantgambit.integration.warm_start import WarmStartState, WarmStartLoader


# ═══════════════════════════════════════════════════════════════
# STRATEGIES FOR PROPERTY-BASED TESTING
# ═══════════════════════════════════════════════════════════════

# Symbol strategy
symbol_strategy = st.sampled_from([
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT",
    "ADAUSDT", "DOGEUSDT", "AVAXUSDT", "DOTUSDT", "MATICUSDT",
])

# Positive float strategy for prices and sizes
positive_float_strategy = st.floats(
    min_value=0.001,
    max_value=100000.0,
    allow_nan=False,
    allow_infinity=False,
)


# Equity strategy (positive values)
equity_strategy = st.floats(
    min_value=100.0,
    max_value=10000000.0,
    allow_nan=False,
    allow_infinity=False,
)

# Position size strategy (can be positive or negative for long/short)
position_size_strategy = st.floats(
    min_value=-1000.0,
    max_value=1000.0,
    allow_nan=False,
    allow_infinity=False,
).filter(lambda x: abs(x) >= 0.001)

# Entry price strategy
entry_price_strategy = st.floats(
    min_value=0.01,
    max_value=100000.0,
    allow_nan=False,
    allow_infinity=False,
)

# Timestamp strategy for recent times
recent_timestamp_strategy = st.datetimes(
    min_value=datetime(2020, 1, 1),
    max_value=datetime(2030, 12, 31),
    timezones=st.just(timezone.utc),
)

# Age in seconds strategy
age_seconds_strategy = st.floats(
    min_value=0.0,
    max_value=3600.0,  # Up to 1 hour
    allow_nan=False,
    allow_infinity=False,
)

# Max age threshold strategy
max_age_strategy = st.floats(
    min_value=1.0,
    max_value=1800.0,  # Up to 30 minutes
    allow_nan=False,
    allow_infinity=False,
)


# Position strategy
@st.composite
def position_strategy(draw):
    """Generate a valid position dictionary."""
    return {
        "symbol": draw(symbol_strategy),
        "size": draw(position_size_strategy),
        "entry_price": draw(entry_price_strategy),
        "opened_at": draw(recent_timestamp_strategy).isoformat(),
    }


# Positions list strategy
positions_list_strategy = st.lists(
    position_strategy(),
    min_size=0,
    max_size=10,
)


# Account state strategy
@st.composite
def account_state_strategy(draw):
    """Generate a valid account state dictionary."""
    equity = draw(equity_strategy)
    return {
        "equity": equity,
        "margin": draw(st.floats(min_value=0, max_value=equity, allow_nan=False, allow_infinity=False)),
        "balance": draw(st.floats(min_value=0, max_value=equity * 2, allow_nan=False, allow_infinity=False)),
    }


# Candle strategy
@st.composite
def candle_strategy(draw):
    """Generate a valid candle dictionary."""
    open_price = draw(positive_float_strategy)
    close_price = draw(positive_float_strategy)
    high_price = max(open_price, close_price) * draw(st.floats(min_value=1.0, max_value=1.1, allow_nan=False, allow_infinity=False))
    low_price = min(open_price, close_price) * draw(st.floats(min_value=0.9, max_value=1.0, allow_nan=False, allow_infinity=False))
    return {
        "ts": draw(recent_timestamp_strategy).isoformat(),
        "open": open_price,
        "high": high_price,
        "low": low_price,
        "close": close_price,
        "volume": draw(st.floats(min_value=0, max_value=1000000, allow_nan=False, allow_infinity=False)),
    }


# Candle history strategy (dict of symbol -> list of candles)
@st.composite
def candle_history_strategy(draw, symbols: List[str] = None):
    """Generate candle history for given symbols."""
    if symbols is None:
        symbols = draw(st.lists(symbol_strategy, min_size=0, max_size=5, unique=True))
    
    history = {}
    for symbol in symbols:
        history[symbol] = draw(st.lists(candle_strategy(), min_size=1, max_size=20))
    return history


# Pipeline state strategy
pipeline_state_strategy = st.fixed_dictionaries({
    "cooldown_until": st.one_of(st.none(), st.text(min_size=0, max_size=30)),
    "hysteresis_state": st.dictionaries(
        keys=symbol_strategy,
        values=st.floats(min_value=0, max_value=1, allow_nan=False, allow_infinity=False),
        min_size=0,
        max_size=5,
    ),
})


# ═══════════════════════════════════════════════════════════════
# HELPER FUNCTIONS
# ═══════════════════════════════════════════════════════════════

def create_mock_redis():
    """Create a mock Redis client for testing."""
    redis = MagicMock()
    redis.get = AsyncMock(return_value=None)
    return redis


def create_mock_pool():
    """Create a mock database pool for testing."""
    pool = MagicMock()
    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=[])
    pool.acquire = MagicMock(return_value=AsyncMock(__aenter__=AsyncMock(return_value=conn), __aexit__=AsyncMock()))
    return pool



# ═══════════════════════════════════════════════════════════════
# PROPERTY 7: WARM START DATA COMPLETENESS
# Feature: trading-pipeline-integration, Property 7
# Validates: Requirements 3.1, 3.3, 3.4
# ═══════════════════════════════════════════════════════════════

class TestWarmStartDataCompleteness:
    """
    Feature: trading-pipeline-integration, Property 7: Warm Start Data Completeness
    
    For any WarmStartState loaded from live system, the state SHALL include:
    all open positions with entry_price, size, and opened_at; account_state
    with equity; and candle_history for all symbols with open positions.
    
    **Validates: Requirements 3.1, 3.3, 3.4**
    """
    
    @settings(max_examples=100)
    @given(
        positions=positions_list_strategy,
        account_state=account_state_strategy(),
        pipeline_state=pipeline_state_strategy,
    )
    def test_warm_start_state_preserves_positions(
        self,
        positions: List[Dict[str, Any]],
        account_state: Dict[str, Any],
        pipeline_state: Dict[str, Any],
    ):
        """
        **Validates: Requirements 3.1, 3.3**
        
        Property: For any WarmStartState, all positions are preserved with
        their entry_price, size, and symbol fields intact.
        """
        # Get unique symbols from positions
        symbols = list(set(p.get("symbol") for p in positions if p.get("symbol")))
        
        # Create candle history for position symbols
        candle_history = {symbol: [{"open": 100, "close": 101}] for symbol in symbols}
        
        state = WarmStartState(
            snapshot_time=datetime.now(timezone.utc),
            positions=positions,
            account_state=account_state,
            candle_history=candle_history,
            pipeline_state=pipeline_state,
        )
        
        # Verify all positions are preserved
        assert len(state.positions) == len(positions)
        
        # Verify each position has required fields
        for i, pos in enumerate(state.positions):
            original = positions[i]
            assert pos.get("symbol") == original.get("symbol"), "Symbol should be preserved"
            assert pos.get("size") == original.get("size"), "Size should be preserved"
            assert pos.get("entry_price") == original.get("entry_price"), "Entry price should be preserved"
    
    @settings(max_examples=100)
    @given(
        positions=positions_list_strategy,
        account_state=account_state_strategy(),
    )
    def test_warm_start_state_preserves_account_state(
        self,
        positions: List[Dict[str, Any]],
        account_state: Dict[str, Any],
    ):
        """
        **Validates: Requirements 3.1**
        
        Property: For any WarmStartState, account_state with equity is preserved.
        """
        state = WarmStartState(
            snapshot_time=datetime.now(timezone.utc),
            positions=positions,
            account_state=account_state,
        )
        
        # Verify account state is preserved
        assert state.account_state == account_state
        assert "equity" in state.account_state, "Account state should include equity"
        assert state.account_state["equity"] == account_state["equity"]
    
    @settings(max_examples=100)
    @given(positions=positions_list_strategy)
    def test_warm_start_state_tracks_position_symbols(
        self,
        positions: List[Dict[str, Any]],
    ):
        """
        **Validates: Requirements 3.3, 3.4**
        
        Property: For any WarmStartState with positions, get_symbols_with_positions()
        returns all unique symbols that have open positions.
        """
        state = WarmStartState(
            snapshot_time=datetime.now(timezone.utc),
            positions=positions,
            account_state={"equity": 10000},
        )
        
        # Get expected symbols
        expected_symbols = set(p.get("symbol") for p in positions if p.get("symbol"))
        
        # Verify symbols match
        actual_symbols = set(state.get_symbols_with_positions())
        assert actual_symbols == expected_symbols
    
    @settings(max_examples=100)
    @given(positions=positions_list_strategy)
    def test_warm_start_candle_history_completeness_check(
        self,
        positions: List[Dict[str, Any]],
    ):
        """
        **Validates: Requirements 3.4**
        
        Property: For any WarmStartState, has_candle_history_for_positions()
        returns True only when candle_history contains data for all position symbols.
        """
        # Get unique symbols from positions
        symbols = list(set(p.get("symbol") for p in positions if p.get("symbol")))
        
        # Case 1: Complete candle history
        complete_history = {symbol: [{"open": 100, "close": 101}] for symbol in symbols}
        state_complete = WarmStartState(
            snapshot_time=datetime.now(timezone.utc),
            positions=positions,
            account_state={"equity": 10000},
            candle_history=complete_history,
        )
        
        if symbols:
            assert state_complete.has_candle_history_for_positions(), \
                "Should return True when all position symbols have candle history"
        else:
            # No positions means no symbols to check
            assert state_complete.has_candle_history_for_positions()
        
        # Case 2: Incomplete candle history (if we have symbols)
        if len(symbols) > 0:
            # Remove one symbol from history
            incomplete_history = {s: [{"open": 100, "close": 101}] for s in symbols[:-1]}
            state_incomplete = WarmStartState(
                snapshot_time=datetime.now(timezone.utc),
                positions=positions,
                account_state={"equity": 10000},
                candle_history=incomplete_history,
            )
            
            assert not state_incomplete.has_candle_history_for_positions(), \
                "Should return False when some position symbols lack candle history"
    
    @settings(max_examples=100)
    @given(
        positions=positions_list_strategy,
        account_state=account_state_strategy(),
    )
    def test_warm_start_state_calculates_total_position_value(
        self,
        positions: List[Dict[str, Any]],
        account_state: Dict[str, Any],
    ):
        """
        **Validates: Requirements 3.3**
        
        Property: For any WarmStartState, get_total_position_value() returns
        the sum of abs(size * entry_price) for all positions.
        """
        state = WarmStartState(
            snapshot_time=datetime.now(timezone.utc),
            positions=positions,
            account_state=account_state,
        )
        
        # Calculate expected total
        expected_total = sum(
            abs(p.get("size", 0) * p.get("entry_price", 0))
            for p in positions
        )
        
        # Verify calculation
        actual_total = state.get_total_position_value()
        assert abs(actual_total - expected_total) < 0.0001, \
            f"Expected {expected_total}, got {actual_total}"
    
    @settings(max_examples=100)
    @given(positions=positions_list_strategy)
    def test_warm_start_state_counts_positions(
        self,
        positions: List[Dict[str, Any]],
    ):
        """
        **Validates: Requirements 3.3**
        
        Property: For any WarmStartState, get_position_count() returns
        the exact number of positions.
        """
        state = WarmStartState(
            snapshot_time=datetime.now(timezone.utc),
            positions=positions,
            account_state={"equity": 10000},
        )
        
        assert state.get_position_count() == len(positions)



# ═══════════════════════════════════════════════════════════════
# PROPERTY 8: WARM START VALIDATION
# Feature: trading-pipeline-integration, Property 8
# Validates: Requirements 3.5
# ═══════════════════════════════════════════════════════════════

class TestWarmStartValidation:
    """
    Feature: trading-pipeline-integration, Property 8: Warm Start Validation
    
    For any WarmStartState where total position value exceeds 10x account equity,
    the validate() method SHALL return (False, [error_message]) indicating
    the inconsistency.
    
    **Validates: Requirements 3.5**
    """
    
    @settings(max_examples=100)
    @given(
        equity=st.floats(min_value=100, max_value=1000000, allow_nan=False, allow_infinity=False),
        position_size=st.floats(min_value=0.001, max_value=100, allow_nan=False, allow_infinity=False),
        entry_price=st.floats(min_value=1, max_value=100000, allow_nan=False, allow_infinity=False),
    )
    def test_validation_detects_excessive_position_value(
        self,
        equity: float,
        position_size: float,
        entry_price: float,
    ):
        """
        **Validates: Requirements 3.5**
        
        Property: For any WarmStartState where total position value exceeds
        10x account equity, validate() returns (False, [error_message]).
        """
        position_value = abs(position_size * entry_price)
        
        state = WarmStartState(
            snapshot_time=datetime.now(timezone.utc),
            positions=[{
                "symbol": "BTCUSDT",
                "size": position_size,
                "entry_price": entry_price,
            }],
            account_state={"equity": equity},
        )
        
        is_valid, errors = state.validate()
        
        # Check if position value exceeds 10x equity
        if position_value > equity * 10:
            assert is_valid is False, \
                f"Should be invalid when position value {position_value} > 10x equity {equity}"
            assert len(errors) > 0, "Should have error messages"
            # Verify error message mentions the issue
            assert any("exceeds" in error.lower() or "10" in error for error in errors), \
                "Error should mention the position/equity ratio issue"
        else:
            # Position value within limits - should pass this specific check
            # (may still fail for other reasons like missing equity)
            pass
    
    @settings(max_examples=100)
    @given(
        equity=st.floats(min_value=1000, max_value=1000000, allow_nan=False, allow_infinity=False),
        num_positions=st.integers(min_value=1, max_value=10),
    )
    def test_validation_checks_aggregate_position_value(
        self,
        equity: float,
        num_positions: int,
    ):
        """
        **Validates: Requirements 3.5**
        
        Property: For any WarmStartState with multiple positions, validate()
        checks the aggregate position value against equity.
        """
        # Create positions that together exceed 10x equity
        per_position_value = (equity * 11) / num_positions  # Total = 11x equity
        entry_price = 50000.0
        size = per_position_value / entry_price
        
        positions = [
            {
                "symbol": f"SYM{i}USDT",
                "size": size,
                "entry_price": entry_price,
            }
            for i in range(num_positions)
        ]
        
        state = WarmStartState(
            snapshot_time=datetime.now(timezone.utc),
            positions=positions,
            account_state={"equity": equity},
        )
        
        is_valid, errors = state.validate()
        
        # Total position value is 11x equity, should fail
        assert is_valid is False, "Should be invalid when aggregate position value exceeds 10x equity"
        assert len(errors) > 0, "Should have error messages"
    
    @settings(max_examples=100)
    @given(
        equity=st.floats(min_value=10000, max_value=1000000, allow_nan=False, allow_infinity=False),
    )
    def test_validation_passes_for_reasonable_positions(
        self,
        equity: float,
    ):
        """
        **Validates: Requirements 3.5**
        
        Property: For any WarmStartState where position value is within 10x equity,
        validate() passes the position/equity check.
        """
        # Create a position worth 5x equity (within limit)
        position_value = equity * 5
        entry_price = 50000.0
        size = position_value / entry_price
        
        state = WarmStartState(
            snapshot_time=datetime.now(timezone.utc),
            positions=[{
                "symbol": "BTCUSDT",
                "size": size,
                "entry_price": entry_price,
            }],
            account_state={"equity": equity},
        )
        
        is_valid, errors = state.validate()
        
        # Should pass - position value is within 10x equity
        assert is_valid is True, f"Should be valid when position value {position_value} <= 10x equity {equity}"
        assert len(errors) == 0, "Should have no error messages"
    
    @settings(max_examples=100)
    @given(
        positions=positions_list_strategy,
    )
    def test_validation_requires_equity_in_account_state(
        self,
        positions: List[Dict[str, Any]],
    ):
        """
        **Validates: Requirements 3.5**
        
        Property: For any WarmStartState without equity in account_state,
        validate() returns (False, [error_message]).
        """
        # Create state without equity
        state = WarmStartState(
            snapshot_time=datetime.now(timezone.utc),
            positions=positions,
            account_state={},  # No equity
        )
        
        is_valid, errors = state.validate()
        
        assert is_valid is False, "Should be invalid when equity is missing"
        assert len(errors) > 0, "Should have error messages"
        assert any("equity" in error.lower() for error in errors), \
            "Error should mention missing equity"
    
    @settings(max_examples=100)
    @given(
        positions=positions_list_strategy,
    )
    def test_validation_requires_positive_equity(
        self,
        positions: List[Dict[str, Any]],
    ):
        """
        **Validates: Requirements 3.5**
        
        Property: For any WarmStartState with zero or negative equity,
        validate() returns (False, [error_message]).
        """
        # Create state with zero equity
        state = WarmStartState(
            snapshot_time=datetime.now(timezone.utc),
            positions=positions,
            account_state={"equity": 0},
        )
        
        is_valid, errors = state.validate()
        
        assert is_valid is False, "Should be invalid when equity is zero"
        assert len(errors) > 0, "Should have error messages"
    
    @settings(max_examples=100)
    @given(
        equity=st.floats(min_value=10000, max_value=1000000, allow_nan=False, allow_infinity=False),
    )
    def test_validation_passes_with_no_positions(
        self,
        equity: float,
    ):
        """
        **Validates: Requirements 3.5**
        
        Property: For any WarmStartState with valid equity and no positions,
        validate() returns (True, []).
        """
        state = WarmStartState(
            snapshot_time=datetime.now(timezone.utc),
            positions=[],
            account_state={"equity": equity},
        )
        
        is_valid, errors = state.validate()
        
        assert is_valid is True, "Should be valid with no positions and valid equity"
        assert len(errors) == 0, "Should have no error messages"



# ═══════════════════════════════════════════════════════════════
# PROPERTY 9: WARM START STALENESS DETECTION
# Feature: trading-pipeline-integration, Property 9
# Validates: Requirements 3.6
# ═══════════════════════════════════════════════════════════════

class TestWarmStartStalenessDetection:
    """
    Feature: trading-pipeline-integration, Property 9: Warm Start Staleness Detection
    
    For any WarmStartState with snapshot_time older than max_age_sec (default 300),
    the is_stale() method SHALL return True.
    
    **Validates: Requirements 3.6**
    """
    
    @settings(max_examples=100)
    @given(
        age_seconds=st.floats(min_value=301, max_value=3600, allow_nan=False, allow_infinity=False),
    )
    def test_staleness_detected_for_old_snapshots_default_threshold(
        self,
        age_seconds: float,
    ):
        """
        **Validates: Requirements 3.6**
        
        Property: For any WarmStartState with snapshot_time older than 300 seconds
        (default threshold), is_stale() returns True.
        """
        # Create a snapshot that is age_seconds old
        old_time = datetime.now(timezone.utc) - timedelta(seconds=age_seconds)
        
        state = WarmStartState(
            snapshot_time=old_time,
            account_state={"equity": 10000},
        )
        
        # Should be stale with default threshold (300 seconds)
        assert state.is_stale() is True, \
            f"Snapshot {age_seconds}s old should be stale (default threshold 300s)"
    
    @settings(max_examples=100)
    @given(
        age_seconds=st.floats(min_value=0, max_value=299, allow_nan=False, allow_infinity=False),
    )
    def test_not_stale_for_recent_snapshots_default_threshold(
        self,
        age_seconds: float,
    ):
        """
        **Validates: Requirements 3.6**
        
        Property: For any WarmStartState with snapshot_time within 300 seconds
        (default threshold), is_stale() returns False.
        """
        # Create a snapshot that is age_seconds old
        recent_time = datetime.now(timezone.utc) - timedelta(seconds=age_seconds)
        
        state = WarmStartState(
            snapshot_time=recent_time,
            account_state={"equity": 10000},
        )
        
        # Should not be stale with default threshold (300 seconds)
        assert state.is_stale() is False, \
            f"Snapshot {age_seconds}s old should not be stale (default threshold 300s)"
    
    @settings(max_examples=100)
    @given(
        age_seconds=st.floats(min_value=0, max_value=3600, allow_nan=False, allow_infinity=False),
        max_age_sec=st.floats(min_value=1, max_value=1800, allow_nan=False, allow_infinity=False),
    )
    def test_staleness_respects_custom_threshold(
        self,
        age_seconds: float,
        max_age_sec: float,
    ):
        """
        **Validates: Requirements 3.6**
        
        Property: For any WarmStartState and custom max_age_sec threshold,
        is_stale(max_age_sec) returns True iff age > max_age_sec.
        """
        # Skip boundary cases where timing could cause flakiness
        # (within 1 second of threshold)
        assume(abs(age_seconds - max_age_sec) > 1.0)
        
        # Create a snapshot that is age_seconds old
        snapshot_time = datetime.now(timezone.utc) - timedelta(seconds=age_seconds)
        
        state = WarmStartState(
            snapshot_time=snapshot_time,
            account_state={"equity": 10000},
        )
        
        is_stale = state.is_stale(max_age_sec=max_age_sec)
        
        if age_seconds > max_age_sec:
            assert is_stale is True, \
                f"Snapshot {age_seconds}s old should be stale (threshold {max_age_sec}s)"
        else:
            assert is_stale is False, \
                f"Snapshot {age_seconds}s old should not be stale (threshold {max_age_sec}s)"
    
    @settings(max_examples=100)
    @given(
        age_seconds=st.floats(min_value=0, max_value=3600, allow_nan=False, allow_infinity=False),
    )
    def test_get_age_seconds_returns_correct_age(
        self,
        age_seconds: float,
    ):
        """
        **Validates: Requirements 3.6**
        
        Property: For any WarmStartState, get_age_seconds() returns the
        approximate age of the snapshot in seconds.
        """
        # Create a snapshot that is age_seconds old
        snapshot_time = datetime.now(timezone.utc) - timedelta(seconds=age_seconds)
        
        state = WarmStartState(
            snapshot_time=snapshot_time,
            account_state={"equity": 10000},
        )
        
        actual_age = state.get_age_seconds()
        
        # Allow for small timing differences (up to 1 second)
        assert abs(actual_age - age_seconds) < 1.0, \
            f"Expected age ~{age_seconds}s, got {actual_age}s"
    
    @settings(max_examples=100)
    @given(
        age_seconds=st.floats(min_value=0, max_value=3600, allow_nan=False, allow_infinity=False),
    )
    def test_staleness_handles_timezone_naive_timestamps(
        self,
        age_seconds: float,
    ):
        """
        **Validates: Requirements 3.6**
        
        Property: For any WarmStartState with timezone-naive snapshot_time,
        is_stale() still works correctly by assuming UTC.
        """
        # Skip boundary cases where timing could cause flakiness
        # (within 2 seconds of threshold)
        assume(abs(age_seconds - 300) > 2.0)
        
        # Create a timezone-naive timestamp
        naive_time = datetime.utcnow() - timedelta(seconds=age_seconds)
        
        state = WarmStartState(
            snapshot_time=naive_time,
            account_state={"equity": 10000},
        )
        
        # Should handle timezone-naive timestamps gracefully
        # The __post_init__ should add UTC timezone
        is_stale = state.is_stale(max_age_sec=300)
        
        if age_seconds > 300:
            assert is_stale is True
        else:
            assert is_stale is False
    
    @settings(max_examples=100)
    @given(
        positions=positions_list_strategy,
        account_state=account_state_strategy(),
    )
    def test_staleness_independent_of_state_content(
        self,
        positions: List[Dict[str, Any]],
        account_state: Dict[str, Any],
    ):
        """
        **Validates: Requirements 3.6**
        
        Property: For any WarmStartState, staleness is determined solely by
        snapshot_time, not by the content of positions or account_state.
        """
        # Create two states with same timestamp but different content
        snapshot_time = datetime.now(timezone.utc) - timedelta(seconds=100)
        
        state1 = WarmStartState(
            snapshot_time=snapshot_time,
            positions=positions,
            account_state=account_state,
        )
        
        state2 = WarmStartState(
            snapshot_time=snapshot_time,
            positions=[],  # Different content
            account_state={"equity": 1},  # Different content
        )
        
        # Both should have same staleness result
        assert state1.is_stale() == state2.is_stale(), \
            "Staleness should be independent of state content"
    
    @settings(max_examples=100)
    @given(
        max_age_sec=st.floats(min_value=1, max_value=1800, allow_nan=False, allow_infinity=False),
    )
    def test_boundary_staleness_at_exact_threshold(
        self,
        max_age_sec: float,
    ):
        """
        **Validates: Requirements 3.6**
        
        Property: For any WarmStartState with age exactly at the threshold,
        is_stale() returns False (not stale at boundary).
        """
        # Create a snapshot exactly at the threshold
        # Note: Due to timing, we test just under the threshold
        snapshot_time = datetime.now(timezone.utc) - timedelta(seconds=max_age_sec - 0.1)
        
        state = WarmStartState(
            snapshot_time=snapshot_time,
            account_state={"equity": 10000},
        )
        
        # Should not be stale at the boundary
        assert state.is_stale(max_age_sec=max_age_sec) is False, \
            f"Snapshot at threshold should not be stale"



# ═══════════════════════════════════════════════════════════════
# ADDITIONAL PROPERTY TESTS FOR SERIALIZATION
# Feature: trading-pipeline-integration
# Validates: Requirements 3.1, 3.3, 3.4
# ═══════════════════════════════════════════════════════════════

class TestWarmStartStateSerialization:
    """
    Additional property tests for WarmStartState serialization.
    
    These tests ensure that WarmStartState can be serialized and deserialized
    correctly, which is essential for state transfer between systems.
    
    **Validates: Requirements 3.1, 3.3, 3.4**
    """
    
    @settings(max_examples=100)
    @given(
        positions=positions_list_strategy,
        account_state=account_state_strategy(),
        pipeline_state=pipeline_state_strategy,
    )
    def test_warm_start_state_round_trip_serialization(
        self,
        positions: List[Dict[str, Any]],
        account_state: Dict[str, Any],
        pipeline_state: Dict[str, Any],
    ):
        """
        **Validates: Requirements 3.1, 3.3**
        
        Property: For any WarmStartState, serialization to dict and back
        preserves all values.
        """
        # Get unique symbols from positions
        symbols = list(set(p.get("symbol") for p in positions if p.get("symbol")))
        candle_history = {symbol: [{"open": 100, "close": 101}] for symbol in symbols}
        
        original = WarmStartState(
            snapshot_time=datetime.now(timezone.utc),
            positions=positions,
            account_state=account_state,
            candle_history=candle_history,
            pipeline_state=pipeline_state,
        )
        
        # Serialize to dict
        state_dict = original.to_dict()
        
        # Deserialize back
        restored = WarmStartState.from_dict(state_dict)
        
        # Verify all fields match
        assert len(restored.positions) == len(original.positions)
        assert restored.account_state == original.account_state
        assert restored.candle_history == original.candle_history
        assert restored.pipeline_state == original.pipeline_state
        
        # Verify snapshot_time is close (may have microsecond differences due to ISO format)
        time_diff = abs((restored.snapshot_time - original.snapshot_time).total_seconds())
        assert time_diff < 1.0, "Snapshot time should be preserved within 1 second"
    
    @settings(max_examples=100)
    @given(
        equity=equity_strategy,
    )
    def test_warm_start_state_to_dict_format(
        self,
        equity: float,
    ):
        """
        **Validates: Requirements 3.1**
        
        Property: For any WarmStartState, to_dict() produces a dictionary
        with all required keys.
        """
        state = WarmStartState(
            snapshot_time=datetime.now(timezone.utc),
            positions=[{"symbol": "BTCUSDT", "size": 0.1, "entry_price": 50000}],
            account_state={"equity": equity},
            candle_history={"BTCUSDT": [{"open": 50000, "close": 50100}]},
            pipeline_state={"cooldown_until": None},
        )
        
        state_dict = state.to_dict()
        
        # Verify all required keys are present
        required_keys = [
            "snapshot_time",
            "positions",
            "account_state",
            "recent_decisions",
            "candle_history",
            "pipeline_state",
        ]
        
        for key in required_keys:
            assert key in state_dict, f"Missing required key: {key}"
        
        # Verify snapshot_time is ISO format string
        assert isinstance(state_dict["snapshot_time"], str)
        
        # Verify positions is a list
        assert isinstance(state_dict["positions"], list)
        
        # Verify account_state is a dict
        assert isinstance(state_dict["account_state"], dict)
