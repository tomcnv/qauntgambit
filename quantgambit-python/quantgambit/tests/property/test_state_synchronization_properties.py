"""
Property-based tests for State Synchronization.

Feature: trading-pipeline-integration

These tests verify the correctness properties of state synchronization,
ensuring proper round-trip export/import and validation of invalid states.

Uses hypothesis library with minimum 100 iterations per property test.

**Validates: Requirements 8.1, 8.2, 8.3, 8.4, 8.6**
"""

from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

from quantgambit.integration.warm_start import (
    WarmStartState,
    WarmStartLoader,
    StateImportResult,
    ImportValidationStatus,
)


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


# Valid WarmStartState strategy
@st.composite
def valid_warm_start_state_strategy(draw):
    """Generate a valid WarmStartState that passes validation.
    
    This strategy ensures:
    - Equity is positive
    - Position value does not exceed 10x equity
    - All required fields are present
    """
    equity = draw(equity_strategy)
    
    # Generate positions with total value <= 5x equity (well within 10x limit)
    max_position_value = equity * 5
    positions = []
    remaining_value = max_position_value
    
    num_positions = draw(st.integers(min_value=0, max_value=5))
    for _ in range(num_positions):
        if remaining_value <= 0:
            break
        
        symbol = draw(symbol_strategy)
        entry_price = draw(entry_price_strategy)
        
        # Calculate max size to stay within remaining value
        max_size = remaining_value / entry_price if entry_price > 0 else 0
        
        # Only add position if max_size is large enough for a valid float range
        min_size = 0.001
        if max_size >= min_size:
            size = draw(st.floats(
                min_value=min_size,
                max_value=max(max_size, min_size + 0.001),  # Ensure valid range
                allow_nan=False,
                allow_infinity=False,
            ))
            position_value = abs(size * entry_price)
            remaining_value -= position_value
            
            positions.append({
                "symbol": symbol,
                "size": size,
                "entry_price": entry_price,
                "opened_at": draw(recent_timestamp_strategy).isoformat(),
            })
    
    # Generate candle history for position symbols
    position_symbols = list(set(p.get("symbol") for p in positions if p.get("symbol")))
    candle_history = {}
    for symbol in position_symbols:
        candle_history[symbol] = draw(st.lists(candle_strategy(), min_size=1, max_size=10))
    
    return WarmStartState(
        snapshot_time=datetime.now(timezone.utc),
        positions=positions,
        account_state={
            "equity": equity,
            "margin": draw(st.floats(min_value=0, max_value=equity * 0.5, allow_nan=False, allow_infinity=False)),
            "balance": draw(st.floats(min_value=equity * 0.5, max_value=equity * 1.5, allow_nan=False, allow_infinity=False)),
        },
        candle_history=candle_history,
        pipeline_state=draw(pipeline_state_strategy),
    )


# Invalid WarmStartState strategy (for validation testing)
@st.composite
def invalid_warm_start_state_strategy(draw):
    """Generate a WarmStartState with validation errors.
    
    This strategy creates states that should fail validation due to:
    - Missing equity
    - Zero/negative equity
    - Position value exceeding 10x equity
    """
    error_type = draw(st.sampled_from([
        "missing_equity",
        "zero_equity",
        "excessive_position_value",
        "empty_account_state",
    ]))
    
    if error_type == "missing_equity":
        return WarmStartState(
            snapshot_time=datetime.now(timezone.utc),
            positions=[{
                "symbol": "BTCUSDT",
                "size": 0.1,
                "entry_price": 50000,
            }],
            account_state={"margin": 1000},  # Missing equity
            candle_history={},
            pipeline_state={},
        )
    
    elif error_type == "zero_equity":
        return WarmStartState(
            snapshot_time=datetime.now(timezone.utc),
            positions=[{
                "symbol": "BTCUSDT",
                "size": 0.1,
                "entry_price": 50000,
            }],
            account_state={"equity": 0},  # Zero equity
            candle_history={},
            pipeline_state={},
        )
    
    elif error_type == "excessive_position_value":
        # Create position value > 10x equity
        equity = draw(st.floats(min_value=100, max_value=10000, allow_nan=False, allow_infinity=False))
        position_value = equity * 15  # 15x equity (exceeds 10x limit)
        entry_price = 50000.0
        size = position_value / entry_price
        
        return WarmStartState(
            snapshot_time=datetime.now(timezone.utc),
            positions=[{
                "symbol": "BTCUSDT",
                "size": size,
                "entry_price": entry_price,
            }],
            account_state={"equity": equity},
            candle_history={},
            pipeline_state={},
        )
    
    else:  # empty_account_state
        return WarmStartState(
            snapshot_time=datetime.now(timezone.utc),
            positions=[{
                "symbol": "BTCUSDT",
                "size": 0.1,
                "entry_price": 50000,
            }],
            account_state={},  # Empty account state
            candle_history={},
            pipeline_state={},
        )


# ═══════════════════════════════════════════════════════════════
# HELPER FUNCTIONS
# ═══════════════════════════════════════════════════════════════

def create_mock_redis():
    """Create a mock Redis client for testing."""
    redis = MagicMock()
    redis.get = AsyncMock(return_value=None)
    redis.set = AsyncMock(return_value=True)
    return redis


def create_mock_pool():
    """Create a mock database pool for testing."""
    pool = MagicMock()
    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=[])
    pool.acquire = MagicMock(return_value=AsyncMock(
        __aenter__=AsyncMock(return_value=conn),
        __aexit__=AsyncMock()
    ))
    return pool


def setup_mock_redis_with_state(redis_mock, state: WarmStartState):
    """Configure mock Redis to return the given state data."""
    async def mock_get(key):
        if "positions" in key:
            return json.dumps(state.positions)
        elif "account" in key:
            return json.dumps(state.account_state)
        elif "pipeline_state" in key:
            return json.dumps(state.pipeline_state)
        return None
    
    redis_mock.get = AsyncMock(side_effect=mock_get)


# ═══════════════════════════════════════════════════════════════
# PROPERTY 20: STATE SYNCHRONIZATION ROUND-TRIP
# Feature: trading-pipeline-integration, Property 20
# Validates: Requirements 8.1, 8.2, 8.3
# ═══════════════════════════════════════════════════════════════

class TestStateSynchronizationRoundTrip:
    """
    Feature: trading-pipeline-integration, Property 20: State Synchronization Round-Trip
    
    For any valid WarmStartState s, WHEN export_state() is called THEN
    import_state(export_state(s)) produces equivalent state.
    
    This tests that export/import is lossless for valid states.
    
    **Validates: Requirements 8.1, 8.2, 8.3**
    """
    
    @settings(max_examples=100)
    @given(state=valid_warm_start_state_strategy())
    def test_round_trip_via_json_preserves_positions(self, state: WarmStartState):
        """
        **Validates: Requirements 8.1, 8.2**
        
        Property: For any valid WarmStartState, export to JSON and import back
        preserves all position data (symbol, size, entry_price).
        """
        # Export to JSON
        json_str = state.to_json()
        
        # Import back
        restored = WarmStartState.from_json(json_str)
        
        # Verify positions are preserved
        assert len(restored.positions) == len(state.positions), \
            "Position count should be preserved"
        
        for i, (original, restored_pos) in enumerate(zip(state.positions, restored.positions)):
            assert restored_pos.get("symbol") == original.get("symbol"), \
                f"Position {i} symbol should be preserved"
            assert restored_pos.get("size") == original.get("size"), \
                f"Position {i} size should be preserved"
            assert restored_pos.get("entry_price") == original.get("entry_price"), \
                f"Position {i} entry_price should be preserved"
    
    @settings(max_examples=100)
    @given(state=valid_warm_start_state_strategy())
    def test_round_trip_via_json_preserves_account_state(self, state: WarmStartState):
        """
        **Validates: Requirements 8.1, 8.2**
        
        Property: For any valid WarmStartState, export to JSON and import back
        preserves account state (equity, margin, balance).
        """
        # Export to JSON
        json_str = state.to_json()
        
        # Import back
        restored = WarmStartState.from_json(json_str)
        
        # Verify account state is preserved
        assert restored.account_state.get("equity") == state.account_state.get("equity"), \
            "Equity should be preserved"
        assert restored.account_state.get("margin") == state.account_state.get("margin"), \
            "Margin should be preserved"
        assert restored.account_state.get("balance") == state.account_state.get("balance"), \
            "Balance should be preserved"
    
    @settings(max_examples=100)
    @given(state=valid_warm_start_state_strategy())
    def test_round_trip_via_json_preserves_candle_history(self, state: WarmStartState):
        """
        **Validates: Requirements 8.1, 8.2**
        
        Property: For any valid WarmStartState, export to JSON and import back
        preserves candle history for all symbols.
        """
        # Export to JSON
        json_str = state.to_json()
        
        # Import back
        restored = WarmStartState.from_json(json_str)
        
        # Verify candle history symbols are preserved
        assert set(restored.candle_history.keys()) == set(state.candle_history.keys()), \
            "Candle history symbols should be preserved"
        
        # Verify candle counts are preserved
        for symbol in state.candle_history:
            assert len(restored.candle_history[symbol]) == len(state.candle_history[symbol]), \
                f"Candle count for {symbol} should be preserved"
    
    @settings(max_examples=100)
    @given(state=valid_warm_start_state_strategy())
    def test_round_trip_via_json_preserves_pipeline_state(self, state: WarmStartState):
        """
        **Validates: Requirements 8.1, 8.2**
        
        Property: For any valid WarmStartState, export to JSON and import back
        preserves pipeline state (cooldowns, hysteresis).
        """
        # Export to JSON
        json_str = state.to_json()
        
        # Import back
        restored = WarmStartState.from_json(json_str)
        
        # Verify pipeline state is preserved
        assert restored.pipeline_state == state.pipeline_state, \
            "Pipeline state should be preserved"


    @settings(max_examples=100)
    @given(state=valid_warm_start_state_strategy())
    def test_round_trip_via_dict_preserves_all_fields(self, state: WarmStartState):
        """
        **Validates: Requirements 8.1, 8.2**
        
        Property: For any valid WarmStartState, export to dict and import back
        preserves all fields.
        """
        # Export to dict
        state_dict = state.to_dict()
        
        # Import back
        restored = WarmStartState.from_dict(state_dict)
        
        # Verify all fields are preserved
        assert len(restored.positions) == len(state.positions)
        assert restored.account_state == state.account_state
        assert restored.pipeline_state == state.pipeline_state
        
        # Verify snapshot_time is close (may have microsecond differences)
        time_diff = abs((restored.snapshot_time - state.snapshot_time).total_seconds())
        assert time_diff < 1.0, "Snapshot time should be preserved within 1 second"
    
    @settings(max_examples=100)
    @given(state=valid_warm_start_state_strategy())
    @pytest.mark.asyncio
    async def test_round_trip_via_import_state_method(self, state: WarmStartState):
        """
        **Validates: Requirements 8.1, 8.2, 8.3**
        
        Property: For any valid WarmStartState, export to JSON and import via
        WarmStartLoader.import_state() produces equivalent state with SUCCESS status.
        """
        # Create mock dependencies
        redis = create_mock_redis()
        pool = create_mock_pool()
        
        # Setup mock Redis to return the state data for comparison
        setup_mock_redis_with_state(redis, state)
        
        loader = WarmStartLoader(redis, pool, "tenant1", "bot1")
        
        # Export to JSON
        json_str = state.to_json()
        
        # Import via loader
        result = await loader.import_state(json_str, validate_against_live=False)
        
        # Verify import succeeded
        assert result.is_valid, f"Import should succeed for valid state, errors: {result.errors}"
        assert result.state is not None, "Imported state should not be None"
        
        # Verify positions are preserved
        assert len(result.state.positions) == len(state.positions)
        
        # Verify account state is preserved
        assert result.state.account_state.get("equity") == state.account_state.get("equity")
    
    @settings(max_examples=100)
    @given(state=valid_warm_start_state_strategy())
    @pytest.mark.asyncio
    async def test_round_trip_preserves_validation_status(self, state: WarmStartState):
        """
        **Validates: Requirements 8.3**
        
        Property: For any valid WarmStartState, after round-trip export/import,
        the restored state should also pass validation.
        """
        # Export to JSON
        json_str = state.to_json()
        
        # Import back
        restored = WarmStartState.from_json(json_str)
        
        # Verify original passes validation
        original_valid, original_errors = state.validate()
        assert original_valid, f"Original state should be valid: {original_errors}"
        
        # Verify restored passes validation
        restored_valid, restored_errors = restored.validate()
        assert restored_valid, f"Restored state should be valid: {restored_errors}"
    
    @settings(max_examples=100)
    @given(
        positions=positions_list_strategy,
        account_state=account_state_strategy(),
        pipeline_state=pipeline_state_strategy,
    )
    def test_round_trip_with_empty_candle_history(
        self,
        positions: List[Dict[str, Any]],
        account_state: Dict[str, Any],
        pipeline_state: Dict[str, Any],
    ):
        """
        **Validates: Requirements 8.1, 8.2**
        
        Property: For any WarmStartState with empty candle history,
        round-trip export/import preserves the empty state.
        """
        state = WarmStartState(
            snapshot_time=datetime.now(timezone.utc),
            positions=positions,
            account_state=account_state,
            candle_history={},  # Empty candle history
            pipeline_state=pipeline_state,
        )
        
        # Export to JSON
        json_str = state.to_json()
        
        # Import back
        restored = WarmStartState.from_json(json_str)
        
        # Verify empty candle history is preserved
        assert restored.candle_history == {}, "Empty candle history should be preserved"
    
    @settings(max_examples=100)
    @given(state=valid_warm_start_state_strategy())
    def test_round_trip_json_is_valid_json(self, state: WarmStartState):
        """
        **Validates: Requirements 8.1**
        
        Property: For any valid WarmStartState, to_json() produces valid JSON
        that can be parsed by json.loads().
        """
        # Export to JSON
        json_str = state.to_json()
        
        # Verify it's valid JSON
        try:
            parsed = json.loads(json_str)
            assert isinstance(parsed, dict), "Parsed JSON should be a dictionary"
        except json.JSONDecodeError as e:
            pytest.fail(f"to_json() should produce valid JSON: {e}")
    
    @settings(max_examples=100)
    @given(state=valid_warm_start_state_strategy())
    def test_round_trip_preserves_snapshot_time_timezone(self, state: WarmStartState):
        """
        **Validates: Requirements 8.1, 8.2**
        
        Property: For any valid WarmStartState, round-trip export/import
        preserves the snapshot_time with timezone information.
        """
        # Export to JSON
        json_str = state.to_json()
        
        # Import back
        restored = WarmStartState.from_json(json_str)
        
        # Verify timezone is preserved
        assert restored.snapshot_time.tzinfo is not None, \
            "Restored snapshot_time should have timezone info"


# ═══════════════════════════════════════════════════════════════
# PROPERTY 21: STATE SYNCHRONIZATION VALIDATION
# Feature: trading-pipeline-integration, Property 21
# Validates: Requirements 8.3, 8.4, 8.6
# ═══════════════════════════════════════════════════════════════

class TestStateSynchronizationValidation:
    """
    Feature: trading-pipeline-integration, Property 21: State Synchronization Validation
    
    For any WarmStartState s with validation errors, WHEN import_state(s) is called
    THEN result.is_valid == False AND result.errors is non-empty.
    
    This tests that invalid states are properly rejected with specific error messages.
    
    **Validates: Requirements 8.3, 8.4, 8.6**
    """
    
    @settings(max_examples=100)
    @given(state=invalid_warm_start_state_strategy())
    @pytest.mark.asyncio
    async def test_import_rejects_invalid_states(self, state: WarmStartState):
        """
        **Validates: Requirements 8.3, 8.4**
        
        Property: For any WarmStartState with validation errors,
        import_state() returns result.is_valid == False.
        """
        # Create mock dependencies
        redis = create_mock_redis()
        pool = create_mock_pool()
        
        loader = WarmStartLoader(redis, pool, "tenant1", "bot1")
        
        # Export to JSON
        json_str = state.to_json()
        
        # Import via loader
        result = await loader.import_state(json_str, validate_against_live=False)
        
        # Verify import failed validation
        assert result.is_valid is False, \
            f"Import should fail for invalid state, got status: {result.status}"
        assert result.status == ImportValidationStatus.FAILED, \
            f"Status should be FAILED, got: {result.status}"
    
    @settings(max_examples=100)
    @given(state=invalid_warm_start_state_strategy())
    @pytest.mark.asyncio
    async def test_import_provides_error_messages_for_invalid_states(self, state: WarmStartState):
        """
        **Validates: Requirements 8.4, 8.6**
        
        Property: For any WarmStartState with validation errors,
        import_state() returns non-empty result.errors with specific messages.
        """
        # Create mock dependencies
        redis = create_mock_redis()
        pool = create_mock_pool()
        
        loader = WarmStartLoader(redis, pool, "tenant1", "bot1")
        
        # Export to JSON
        json_str = state.to_json()
        
        # Import via loader
        result = await loader.import_state(json_str, validate_against_live=False)
        
        # Verify errors are provided
        assert len(result.errors) > 0, \
            "Import should provide error messages for invalid state"
        
        # Verify errors are strings
        for error in result.errors:
            assert isinstance(error, str), "Each error should be a string"
            assert len(error) > 0, "Error messages should not be empty"
    
    @settings(max_examples=100)
    @given(
        equity=st.floats(min_value=100, max_value=10000, allow_nan=False, allow_infinity=False),
    )
    @pytest.mark.asyncio
    async def test_import_rejects_excessive_position_value(self, equity: float):
        """
        **Validates: Requirements 8.3, 8.4**
        
        Property: For any WarmStartState where position value exceeds 10x equity,
        import_state() returns FAILED status with error mentioning the issue.
        """
        # Create state with position value > 10x equity
        position_value = equity * 15  # 15x equity
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
        
        # Create mock dependencies
        redis = create_mock_redis()
        pool = create_mock_pool()
        
        loader = WarmStartLoader(redis, pool, "tenant1", "bot1")
        
        # Import via loader
        result = await loader.import_state(state, validate_against_live=False)
        
        # Verify import failed
        assert result.is_valid is False, "Should reject excessive position value"
        assert result.status == ImportValidationStatus.FAILED
        
        # Verify error message mentions the issue
        error_text = " ".join(result.errors).lower()
        assert "exceeds" in error_text or "10" in error_text or "equity" in error_text, \
            f"Error should mention position/equity issue: {result.errors}"
    
    @settings(max_examples=100)
    @given(positions=positions_list_strategy)
    @pytest.mark.asyncio
    async def test_import_rejects_missing_equity(self, positions: List[Dict[str, Any]]):
        """
        **Validates: Requirements 8.3, 8.4**
        
        Property: For any WarmStartState without equity in account_state,
        import_state() returns FAILED status with error mentioning equity.
        """
        state = WarmStartState(
            snapshot_time=datetime.now(timezone.utc),
            positions=positions,
            account_state={"margin": 1000},  # Missing equity
        )
        
        # Create mock dependencies
        redis = create_mock_redis()
        pool = create_mock_pool()
        
        loader = WarmStartLoader(redis, pool, "tenant1", "bot1")
        
        # Import via loader
        result = await loader.import_state(state, validate_against_live=False)
        
        # Verify import failed
        assert result.is_valid is False, "Should reject missing equity"
        assert result.status == ImportValidationStatus.FAILED
        
        # Verify error message mentions equity
        error_text = " ".join(result.errors).lower()
        assert "equity" in error_text, \
            f"Error should mention missing equity: {result.errors}"


    @settings(max_examples=100)
    @given(positions=positions_list_strategy)
    @pytest.mark.asyncio
    async def test_import_rejects_empty_account_state(self, positions: List[Dict[str, Any]]):
        """
        **Validates: Requirements 8.3, 8.4**
        
        Property: For any WarmStartState with empty account_state,
        import_state() returns FAILED status.
        """
        state = WarmStartState(
            snapshot_time=datetime.now(timezone.utc),
            positions=positions,
            account_state={},  # Empty account state
        )
        
        # Create mock dependencies
        redis = create_mock_redis()
        pool = create_mock_pool()
        
        loader = WarmStartLoader(redis, pool, "tenant1", "bot1")
        
        # Import via loader
        result = await loader.import_state(state, validate_against_live=False)
        
        # Verify import failed
        assert result.is_valid is False, "Should reject empty account state"
        assert result.status == ImportValidationStatus.FAILED
        assert len(result.errors) > 0, "Should provide error messages"
    
    @settings(max_examples=100)
    @given(positions=positions_list_strategy)
    @pytest.mark.asyncio
    async def test_import_rejects_zero_equity(self, positions: List[Dict[str, Any]]):
        """
        **Validates: Requirements 8.3, 8.4**
        
        Property: For any WarmStartState with zero equity,
        import_state() returns FAILED status.
        """
        state = WarmStartState(
            snapshot_time=datetime.now(timezone.utc),
            positions=positions,
            account_state={"equity": 0},  # Zero equity
        )
        
        # Create mock dependencies
        redis = create_mock_redis()
        pool = create_mock_pool()
        
        loader = WarmStartLoader(redis, pool, "tenant1", "bot1")
        
        # Import via loader
        result = await loader.import_state(state, validate_against_live=False)
        
        # Verify import failed
        assert result.is_valid is False, "Should reject zero equity"
        assert result.status == ImportValidationStatus.FAILED
    
    @pytest.mark.asyncio
    async def test_import_rejects_invalid_json(self):
        """
        **Validates: Requirements 8.3, 8.4**
        
        Property: For invalid JSON input, import_state() returns FAILED status
        with error mentioning JSON parsing issue.
        """
        # Create mock dependencies
        redis = create_mock_redis()
        pool = create_mock_pool()
        
        loader = WarmStartLoader(redis, pool, "tenant1", "bot1")
        
        # Try to import invalid JSON
        result = await loader.import_state("not valid json {{{", validate_against_live=False)
        
        # Verify import failed
        assert result.is_valid is False, "Should reject invalid JSON"
        assert result.status == ImportValidationStatus.FAILED
        assert len(result.errors) > 0, "Should provide error messages"
        
        # Verify error mentions JSON
        error_text = " ".join(result.errors).lower()
        assert "json" in error_text, f"Error should mention JSON: {result.errors}"
    
    @pytest.mark.asyncio
    async def test_import_rejects_missing_required_fields(self):
        """
        **Validates: Requirements 8.3, 8.4**
        
        Property: For JSON missing required fields (snapshot_time),
        import_state() returns FAILED status.
        """
        # Create mock dependencies
        redis = create_mock_redis()
        pool = create_mock_pool()
        
        loader = WarmStartLoader(redis, pool, "tenant1", "bot1")
        
        # Try to import JSON missing snapshot_time
        invalid_json = json.dumps({
            "positions": [],
            "account_state": {"equity": 10000},
            # Missing snapshot_time
        })
        
        result = await loader.import_state(invalid_json, validate_against_live=False)
        
        # Verify import failed
        assert result.is_valid is False, "Should reject missing required fields"
        assert result.status == ImportValidationStatus.FAILED
        assert len(result.errors) > 0, "Should provide error messages"
    
    @settings(max_examples=100)
    @given(state=valid_warm_start_state_strategy())
    @pytest.mark.asyncio
    async def test_import_accepts_valid_states(self, state: WarmStartState):
        """
        **Validates: Requirements 8.3, 8.6**
        
        Property: For any valid WarmStartState, import_state() returns
        SUCCESS or WARNING status (is_valid == True).
        """
        # Create mock dependencies
        redis = create_mock_redis()
        pool = create_mock_pool()
        
        # Setup mock Redis to return the state data
        setup_mock_redis_with_state(redis, state)
        
        loader = WarmStartLoader(redis, pool, "tenant1", "bot1")
        
        # Import via loader
        result = await loader.import_state(state, validate_against_live=False)
        
        # Verify import succeeded
        assert result.is_valid is True, \
            f"Should accept valid state, errors: {result.errors}"
        assert result.status in (ImportValidationStatus.SUCCESS, ImportValidationStatus.WARNING)
        assert result.state is not None, "Imported state should not be None"


    @settings(max_examples=100)
    @given(
        equity=st.floats(min_value=10000, max_value=1000000, allow_nan=False, allow_infinity=False),
    )
    @pytest.mark.asyncio
    async def test_import_validates_position_completeness(self, equity: float):
        """
        **Validates: Requirements 8.4**
        
        Property: For any WarmStartState with positions missing required fields,
        import_state() reports specific warnings or errors.
        """
        # Create state with incomplete position data
        state = WarmStartState(
            snapshot_time=datetime.now(timezone.utc),
            positions=[
                {"symbol": "BTCUSDT"},  # Missing size and entry_price
            ],
            account_state={"equity": equity},
        )
        
        # Create mock dependencies
        redis = create_mock_redis()
        pool = create_mock_pool()
        
        loader = WarmStartLoader(redis, pool, "tenant1", "bot1")
        
        # Import via loader
        result = await loader.import_state(state, validate_against_live=False)
        
        # Should have warnings about missing fields
        # Note: This may be a warning rather than error depending on implementation
        all_messages = result.errors + result.warnings
        assert len(all_messages) > 0, \
            "Should report issues with incomplete position data"
    
    @settings(max_examples=100)
    @given(state=valid_warm_start_state_strategy())
    @pytest.mark.asyncio
    async def test_import_result_contains_state_summary(self, state: WarmStartState):
        """
        **Validates: Requirements 8.4**
        
        Property: For any import result, to_dict() provides a state summary
        with position count and account state info.
        """
        # Create mock dependencies
        redis = create_mock_redis()
        pool = create_mock_pool()
        
        loader = WarmStartLoader(redis, pool, "tenant1", "bot1")
        
        # Import via loader
        result = await loader.import_state(state, validate_against_live=False)
        
        # Convert to dict
        result_dict = result.to_dict()
        
        # Verify structure
        assert "status" in result_dict
        assert "is_valid" in result_dict
        assert "errors" in result_dict
        assert "warnings" in result_dict
        
        # If state was parsed, verify summary
        if result.state is not None:
            assert "state_summary" in result_dict
            summary = result_dict["state_summary"]
            assert "position_count" in summary
            assert "has_account_state" in summary
    
    @settings(max_examples=100)
    @given(
        equity=st.floats(min_value=10000, max_value=1000000, allow_nan=False, allow_infinity=False),
        age_seconds=st.floats(min_value=400, max_value=3600, allow_nan=False, allow_infinity=False),
    )
    @pytest.mark.asyncio
    async def test_import_warns_about_stale_state(self, equity: float, age_seconds: float):
        """
        **Validates: Requirements 8.4**
        
        Property: For any WarmStartState that is stale (>300 seconds old),
        import_state() includes a warning about staleness.
        """
        # Create a stale state
        old_time = datetime.now(timezone.utc) - timedelta(seconds=age_seconds)
        state = WarmStartState(
            snapshot_time=old_time,
            positions=[],
            account_state={"equity": equity},
        )
        
        # Create mock dependencies
        redis = create_mock_redis()
        pool = create_mock_pool()
        
        loader = WarmStartLoader(redis, pool, "tenant1", "bot1")
        
        # Import via loader
        result = await loader.import_state(state, validate_against_live=False)
        
        # Should have warning about staleness
        assert result.has_warnings, "Should warn about stale state"
        warning_text = " ".join(result.warnings).lower()
        assert "stale" in warning_text, \
            f"Warning should mention staleness: {result.warnings}"


# ═══════════════════════════════════════════════════════════════
# ADDITIONAL TESTS FOR STATE SYNCHRONIZATION EDGE CASES
# Feature: trading-pipeline-integration
# Validates: Requirements 8.1, 8.2, 8.3, 8.4, 8.6
# ═══════════════════════════════════════════════════════════════

class TestStateSynchronizationEdgeCases:
    """
    Additional tests for state synchronization edge cases.
    
    **Validates: Requirements 8.1, 8.2, 8.3, 8.4, 8.6**
    """
    
    @settings(max_examples=100)
    @given(state=valid_warm_start_state_strategy())
    @pytest.mark.asyncio
    async def test_import_from_dict_equivalent_to_json(self, state: WarmStartState):
        """
        **Validates: Requirements 8.1, 8.3**
        
        Property: For any valid WarmStartState, importing from dict produces
        the same result as importing from JSON.
        """
        # Create mock dependencies
        redis = create_mock_redis()
        pool = create_mock_pool()
        
        loader = WarmStartLoader(redis, pool, "tenant1", "bot1")
        
        # Import from JSON
        json_str = state.to_json()
        result_json = await loader.import_state(json_str, validate_against_live=False)
        
        # Import from dict
        state_dict = state.to_dict()
        result_dict = await loader.import_state(state_dict, validate_against_live=False)
        
        # Both should have same validation status
        assert result_json.is_valid == result_dict.is_valid, \
            "JSON and dict import should have same validation status"
        assert result_json.status == result_dict.status, \
            "JSON and dict import should have same status"
    
    @settings(max_examples=100)
    @given(state=valid_warm_start_state_strategy())
    @pytest.mark.asyncio
    async def test_import_from_warm_start_state_directly(self, state: WarmStartState):
        """
        **Validates: Requirements 8.3, 8.6**
        
        Property: For any valid WarmStartState, importing the object directly
        produces the same result as importing from JSON.
        """
        # Create mock dependencies
        redis = create_mock_redis()
        pool = create_mock_pool()
        
        loader = WarmStartLoader(redis, pool, "tenant1", "bot1")
        
        # Import directly
        result_direct = await loader.import_state(state, validate_against_live=False)
        
        # Import from JSON
        json_str = state.to_json()
        result_json = await loader.import_state(json_str, validate_against_live=False)
        
        # Both should have same validation status
        assert result_direct.is_valid == result_json.is_valid, \
            "Direct and JSON import should have same validation status"
    
    @settings(max_examples=100)
    @given(
        equity=st.floats(min_value=10000, max_value=1000000, allow_nan=False, allow_infinity=False),
    )
    def test_state_validation_is_idempotent(self, equity: float):
        """
        **Validates: Requirements 8.3**
        
        Property: For any WarmStartState, calling validate() multiple times
        produces the same result.
        """
        state = WarmStartState(
            snapshot_time=datetime.now(timezone.utc),
            positions=[{
                "symbol": "BTCUSDT",
                "size": 0.1,
                "entry_price": 50000,
            }],
            account_state={"equity": equity},
        )
        
        # Call validate multiple times
        result1 = state.validate()
        result2 = state.validate()
        result3 = state.validate()
        
        # All results should be identical
        assert result1 == result2 == result3, \
            "validate() should be idempotent"
    
    @settings(max_examples=100)
    @given(state=valid_warm_start_state_strategy())
    def test_round_trip_preserves_position_order(self, state: WarmStartState):
        """
        **Validates: Requirements 8.1, 8.2**
        
        Property: For any valid WarmStartState, round-trip export/import
        preserves the order of positions.
        """
        # Export to JSON
        json_str = state.to_json()
        
        # Import back
        restored = WarmStartState.from_json(json_str)
        
        # Verify position order is preserved
        for i, (original, restored_pos) in enumerate(zip(state.positions, restored.positions)):
            assert restored_pos.get("symbol") == original.get("symbol"), \
                f"Position {i} order should be preserved"

