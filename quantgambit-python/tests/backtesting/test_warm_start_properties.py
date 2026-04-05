"""
Property-based tests for Warm Start State Completeness.

Feature: bot-integration-fixes
Tests correctness properties for:
- Property 2: Warm Start State Completeness

**Validates: Requirements 3.3, 3.4**

For any warm start initialization, the loaded state SHALL include positions,
account state, recent decision history, and candle history for AMT calculations.
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional
from dataclasses import dataclass

import pytest
from hypothesis import given, strategies as st, settings, assume

from quantgambit.integration.warm_start import WarmStartState


# =============================================================================
# Test Strategies (Generators)
# =============================================================================

# Symbols - common trading pairs
symbol_strategy = st.sampled_from([
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT",
    "BNBUSDT", "ADAUSDT", "AVAXUSDT", "DOTUSDT", "MATICUSDT"
])

# Price values - realistic price ranges
price_strategy = st.floats(
    min_value=0.01,
    max_value=100000.0,
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

# Equity strategy (positive values)
equity_strategy = st.floats(
    min_value=100.0,
    max_value=10000000.0,
    allow_nan=False,
    allow_infinity=False,
)

# Volume strategy
volume_strategy = st.floats(
    min_value=0.0,
    max_value=1000000.0,
    allow_nan=False,
    allow_infinity=False,
)

# Timestamp strategy for recent times
recent_timestamp_strategy = st.datetimes(
    min_value=datetime(2020, 1, 1),
    max_value=datetime(2030, 12, 31),
    timezones=st.just(timezone.utc),
)


@st.composite
def position_strategy(draw):
    """Generate a valid position dictionary."""
    return {
        "symbol": draw(symbol_strategy),
        "size": draw(position_size_strategy),
        "entry_price": draw(price_strategy),
        "opened_at": draw(recent_timestamp_strategy).isoformat(),
    }


# Positions list strategy
positions_list_strategy = st.lists(
    position_strategy(),
    min_size=0,
    max_size=10,
)


@st.composite
def account_state_strategy(draw):
    """Generate a valid account state dictionary."""
    equity = draw(equity_strategy)
    return {
        "equity": equity,
        "margin": draw(st.floats(min_value=0, max_value=equity, allow_nan=False, allow_infinity=False)),
        "balance": draw(st.floats(min_value=0, max_value=equity * 2, allow_nan=False, allow_infinity=False)),
    }


@st.composite
def candle_strategy(draw):
    """Generate a valid candle dictionary."""
    open_price = draw(price_strategy)
    close_price = draw(price_strategy)
    high_price = max(open_price, close_price) * draw(st.floats(min_value=1.0, max_value=1.1, allow_nan=False, allow_infinity=False))
    low_price = min(open_price, close_price) * draw(st.floats(min_value=0.9, max_value=1.0, allow_nan=False, allow_infinity=False))
    return {
        "ts": draw(recent_timestamp_strategy).isoformat(),
        "open": open_price,
        "high": high_price,
        "low": low_price,
        "close": close_price,
        "volume": draw(volume_strategy),
    }


@st.composite
def candle_history_strategy(draw, symbols: Optional[List[str]] = None):
    """Generate candle history for given symbols."""
    if symbols is None:
        symbols = draw(st.lists(symbol_strategy, min_size=0, max_size=5, unique=True))
    
    history = {}
    for symbol in symbols:
        history[symbol] = draw(st.lists(candle_strategy(), min_size=1, max_size=20))
    return history


@st.composite
def recent_decision_strategy(draw):
    """Generate a mock recent decision dictionary."""
    return {
        "decision_id": f"dec_{draw(st.integers(min_value=1, max_value=999999))}",
        "symbol": draw(symbol_strategy),
        "timestamp": draw(recent_timestamp_strategy).isoformat(),
        "decision": draw(st.sampled_from(["accepted", "rejected"])),
        "confidence": draw(st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False)),
    }


# Recent decisions list strategy
recent_decisions_list_strategy = st.lists(
    recent_decision_strategy(),
    min_size=0,
    max_size=20,
)


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


@st.composite
def warm_start_state_strategy(draw):
    """Generate a complete WarmStartState object."""
    positions = draw(positions_list_strategy)
    account_state = draw(account_state_strategy())
    recent_decisions = draw(recent_decisions_list_strategy)
    
    # Get unique symbols from positions for candle history
    position_symbols = list(set(p.get("symbol") for p in positions if p.get("symbol")))
    
    # Generate candle history for position symbols
    candle_history = {}
    for symbol in position_symbols:
        candle_history[symbol] = draw(st.lists(candle_strategy(), min_size=1, max_size=20))
    
    # Optionally add candle history for additional symbols
    additional_symbols = draw(st.lists(symbol_strategy, min_size=0, max_size=3, unique=True))
    for symbol in additional_symbols:
        if symbol not in candle_history:
            candle_history[symbol] = draw(st.lists(candle_strategy(), min_size=1, max_size=20))
    
    pipeline_state = draw(pipeline_state_strategy)
    
    return WarmStartState(
        snapshot_time=draw(recent_timestamp_strategy),
        positions=positions,
        account_state=account_state,
        recent_decisions=recent_decisions,
        candle_history=candle_history,
        pipeline_state=pipeline_state,
    )


# =============================================================================
# Property 2: Warm Start State Completeness
# Feature: bot-integration-fixes, Property 2: Warm Start State Completeness
# Validates: Requirements 3.3, 3.4
# =============================================================================

class TestWarmStartStateCompleteness:
    """
    Feature: bot-integration-fixes, Property 2: Warm Start State Completeness
    
    For any warm start initialization, the loaded state SHALL include positions,
    account state, recent decision history, and candle history for AMT calculations.
    
    **Validates: Requirements 3.3, 3.4**
    """
    
    @settings(max_examples=100)
    @given(state=warm_start_state_strategy())
    def test_positions_field_is_present_and_is_list(
        self,
        state: WarmStartState,
    ):
        """
        Property 2: Positions field is present and is a list
        
        *For any* WarmStartState, the positions field SHALL be present and be a list.
        
        **Validates: Requirements 3.3**
        """
        # Property: positions field is present
        assert hasattr(state, 'positions'), "WarmStartState should have positions attribute"
        
        # Property: positions is not None
        assert state.positions is not None, "positions should not be None"
        
        # Property: positions is a list
        assert isinstance(state.positions, list), \
            f"positions should be a list, got {type(state.positions)}"
    
    @settings(max_examples=100)
    @given(state=warm_start_state_strategy())
    def test_account_state_field_is_present_and_is_dict(
        self,
        state: WarmStartState,
    ):
        """
        Property 2: Account state field is present and is a dict
        
        *For any* WarmStartState, the account_state field SHALL be present and be a dict.
        
        **Validates: Requirements 3.3**
        """
        # Property: account_state field is present
        assert hasattr(state, 'account_state'), "WarmStartState should have account_state attribute"
        
        # Property: account_state is not None
        assert state.account_state is not None, "account_state should not be None"
        
        # Property: account_state is a dict
        assert isinstance(state.account_state, dict), \
            f"account_state should be a dict, got {type(state.account_state)}"
    
    @settings(max_examples=100)
    @given(state=warm_start_state_strategy())
    def test_recent_decisions_field_is_present_and_is_list(
        self,
        state: WarmStartState,
    ):
        """
        Property 2: Recent decisions field is present and is a list
        
        *For any* WarmStartState, the recent_decisions field SHALL be present and be a list.
        
        **Validates: Requirements 3.3**
        """
        # Property: recent_decisions field is present
        assert hasattr(state, 'recent_decisions'), "WarmStartState should have recent_decisions attribute"
        
        # Property: recent_decisions is not None
        assert state.recent_decisions is not None, "recent_decisions should not be None"
        
        # Property: recent_decisions is a list
        assert isinstance(state.recent_decisions, list), \
            f"recent_decisions should be a list, got {type(state.recent_decisions)}"
    
    @settings(max_examples=100)
    @given(state=warm_start_state_strategy())
    def test_candle_history_field_is_present_and_is_dict(
        self,
        state: WarmStartState,
    ):
        """
        Property 2: Candle history field is present and is a dict
        
        *For any* WarmStartState, the candle_history field SHALL be present and be a dict
        for AMT calculations.
        
        **Validates: Requirements 3.4**
        """
        # Property: candle_history field is present
        assert hasattr(state, 'candle_history'), "WarmStartState should have candle_history attribute"
        
        # Property: candle_history is not None
        assert state.candle_history is not None, "candle_history should not be None"
        
        # Property: candle_history is a dict
        assert isinstance(state.candle_history, dict), \
            f"candle_history should be a dict, got {type(state.candle_history)}"
    
    @settings(max_examples=100)
    @given(state=warm_start_state_strategy())
    def test_all_required_fields_are_non_none(
        self,
        state: WarmStartState,
    ):
        """
        Property 2: All required fields are non-None
        
        *For any* WarmStartState, all required fields (positions, account_state,
        recent_decisions, candle_history) SHALL be non-None.
        
        **Validates: Requirements 3.3, 3.4**
        """
        # Property: All required fields are non-None
        assert state.positions is not None, "positions should not be None"
        assert state.account_state is not None, "account_state should not be None"
        assert state.recent_decisions is not None, "recent_decisions should not be None"
        assert state.candle_history is not None, "candle_history should not be None"
        
        # Also verify snapshot_time is present
        assert state.snapshot_time is not None, "snapshot_time should not be None"
    
    @settings(max_examples=100)
    @given(state=warm_start_state_strategy())
    def test_positions_contain_required_fields(
        self,
        state: WarmStartState,
    ):
        """
        Property 2: Positions contain required fields
        
        *For any* WarmStartState with positions, each position SHALL include
        entry_price, size, and symbol fields.
        
        **Validates: Requirements 3.3**
        """
        for i, position in enumerate(state.positions):
            # Property: Each position has symbol
            assert "symbol" in position, f"Position {i} should have 'symbol' field"
            assert position["symbol"] is not None, f"Position {i} symbol should not be None"
            
            # Property: Each position has size
            assert "size" in position, f"Position {i} should have 'size' field"
            assert position["size"] is not None, f"Position {i} size should not be None"
            
            # Property: Each position has entry_price
            assert "entry_price" in position, f"Position {i} should have 'entry_price' field"
            assert position["entry_price"] is not None, f"Position {i} entry_price should not be None"
    
    @settings(max_examples=100)
    @given(state=warm_start_state_strategy())
    def test_candle_history_for_position_symbols(
        self,
        state: WarmStartState,
    ):
        """
        Property 2: Candle history exists for position symbols
        
        *For any* WarmStartState with positions, candle_history SHALL include
        data for all symbols with open positions (for AMT calculations).
        
        **Validates: Requirements 3.4**
        """
        # Get unique symbols from positions
        position_symbols = set(p.get("symbol") for p in state.positions if p.get("symbol"))
        
        # Property: candle_history contains data for all position symbols
        for symbol in position_symbols:
            assert symbol in state.candle_history, \
                f"candle_history should contain data for position symbol '{symbol}'"
            assert len(state.candle_history[symbol]) > 0, \
                f"candle_history for '{symbol}' should not be empty"
    
    @settings(max_examples=100)
    @given(state=warm_start_state_strategy())
    def test_candle_history_entries_have_required_fields(
        self,
        state: WarmStartState,
    ):
        """
        Property 2: Candle history entries have required fields
        
        *For any* WarmStartState with candle_history, each candle SHALL include
        open, high, low, close fields for AMT calculations.
        
        **Validates: Requirements 3.4**
        """
        for symbol, candles in state.candle_history.items():
            for i, candle in enumerate(candles):
                # Property: Each candle has OHLC fields
                assert "open" in candle, f"Candle {i} for {symbol} should have 'open' field"
                assert "high" in candle, f"Candle {i} for {symbol} should have 'high' field"
                assert "low" in candle, f"Candle {i} for {symbol} should have 'low' field"
                assert "close" in candle, f"Candle {i} for {symbol} should have 'close' field"
    
    @settings(max_examples=100)
    @given(
        positions=positions_list_strategy,
        account_state=account_state_strategy(),
        recent_decisions=recent_decisions_list_strategy,
    )
    def test_warm_start_state_preserves_all_data(
        self,
        positions: List[Dict[str, Any]],
        account_state: Dict[str, Any],
        recent_decisions: List[Dict[str, Any]],
    ):
        """
        Property 2: WarmStartState preserves all input data
        
        *For any* input data used to create a WarmStartState, the state SHALL
        preserve all positions, account_state, and recent_decisions exactly.
        
        **Validates: Requirements 3.3, 3.4**
        """
        # Get unique symbols from positions for candle history
        position_symbols = list(set(p.get("symbol") for p in positions if p.get("symbol")))
        candle_history = {symbol: [{"open": 100, "close": 101, "high": 102, "low": 99}] for symbol in position_symbols}
        
        state = WarmStartState(
            snapshot_time=datetime.now(timezone.utc),
            positions=positions,
            account_state=account_state,
            recent_decisions=recent_decisions,
            candle_history=candle_history,
        )
        
        # Property: positions are preserved
        assert len(state.positions) == len(positions), "All positions should be preserved"
        for i, pos in enumerate(state.positions):
            assert pos == positions[i], f"Position {i} should be preserved exactly"
        
        # Property: account_state is preserved
        assert state.account_state == account_state, "account_state should be preserved exactly"
        
        # Property: recent_decisions are preserved
        assert len(state.recent_decisions) == len(recent_decisions), "All recent_decisions should be preserved"
    
    @settings(max_examples=100)
    @given(state=warm_start_state_strategy())
    def test_snapshot_time_has_timezone_info(
        self,
        state: WarmStartState,
    ):
        """
        Property 2: Snapshot time has timezone info
        
        *For any* WarmStartState, the snapshot_time SHALL have timezone info
        for proper staleness calculations.
        
        **Validates: Requirements 3.3**
        """
        # Property: snapshot_time has timezone info
        assert state.snapshot_time.tzinfo is not None, \
            "snapshot_time should have timezone info"
    
    @settings(max_examples=100)
    @given(state=warm_start_state_strategy())
    def test_state_completeness_via_helper_methods(
        self,
        state: WarmStartState,
    ):
        """
        Property 2: State completeness verified via helper methods
        
        *For any* WarmStartState, the helper methods (get_position_count,
        get_symbols_with_positions, has_candle_history_for_positions) SHALL
        work correctly with the state data.
        
        **Validates: Requirements 3.3, 3.4**
        """
        # Property: get_position_count returns correct count
        assert state.get_position_count() == len(state.positions), \
            "get_position_count should return the number of positions"
        
        # Property: get_symbols_with_positions returns correct symbols
        expected_symbols = set(p.get("symbol") for p in state.positions if p.get("symbol"))
        actual_symbols = set(state.get_symbols_with_positions())
        assert actual_symbols == expected_symbols, \
            "get_symbols_with_positions should return all position symbols"
        
        # Property: has_candle_history_for_positions returns True when complete
        # (Our strategy ensures candle history is complete for position symbols)
        if state.positions:
            assert state.has_candle_history_for_positions(), \
                "has_candle_history_for_positions should return True when candle history is complete"
