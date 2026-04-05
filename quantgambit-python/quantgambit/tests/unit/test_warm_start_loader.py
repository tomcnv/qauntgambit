"""Unit tests for WarmStartLoader class.

Feature: trading-pipeline-integration
Requirements: 3.1 - THE System SHALL support initializing a backtest with current
              live positions, account state, and recent decision history
Requirements: 3.2 - WHEN warm starting a backtest THEN the System SHALL load the
              most recent state snapshot from Redis
Requirements: 3.3 - THE System SHALL include open positions with entry prices,
              sizes, and timestamps in the warm start state
Requirements: 3.4 - WHEN warm starting THEN the System SHALL include recent candle
              history for AMT calculations
"""

import json
from datetime import datetime, timezone
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from quantgambit.integration.warm_start import (
    WarmStartLoader,
    WarmStartState,
    StateImportResult,
    ImportValidationStatus,
)


class MockRedisClient:
    """Mock Redis client for testing."""
    
    def __init__(self, data: Dict[str, str] = None):
        self._data = data or {}
    
    async def get(self, key: str) -> str | None:
        return self._data.get(key)
    
    async def set(self, key: str, value: str) -> None:
        """Set data for a key (async version for import_state)."""
        self._data[key] = value
    
    def set_data(self, key: str, value: Any) -> None:
        """Set data for a key (JSON serialized) - sync version for test setup."""
        self._data[key] = json.dumps(value)


class MockConnection:
    """Mock database connection for testing."""
    
    def __init__(
        self,
        fetch_results: List[Dict[str, Any]] = None,
        decision_results: List[Dict[str, Any]] = None,
        candle_results: List[Dict[str, Any]] = None,
    ):
        self._fetch_results = fetch_results or []
        self._decision_results = decision_results
        self._candle_results = candle_results
    
    async def fetch(self, query: str, *args) -> List[Dict[str, Any]]:
        # Return different results based on query type
        if self._decision_results is not None and "recorded_decisions" in query:
            return self._decision_results
        if self._candle_results is not None and "market_candles" in query:
            return self._candle_results
        return self._fetch_results
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass


class MockPool:
    """Mock connection pool for testing."""
    
    def __init__(self, connection: MockConnection = None):
        self._connection = connection or MockConnection()
    
    def acquire(self):
        return self._connection


class TestWarmStartLoaderInitialization:
    """Tests for WarmStartLoader initialization."""
    
    def test_can_be_initialized_with_required_parameters(self) -> None:
        """WarmStartLoader can be initialized with redis_client, timescale_pool, tenant_id, bot_id."""
        redis = MockRedisClient()
        pool = MockPool()
        
        loader = WarmStartLoader(
            redis_client=redis,
            timescale_pool=pool,
            tenant_id="tenant1",
            bot_id="bot1",
        )
        
        assert loader.tenant_id == "tenant1"
        assert loader.bot_id == "bot1"
    
    def test_tenant_id_property(self) -> None:
        """tenant_id property returns the correct value."""
        loader = WarmStartLoader(
            redis_client=MockRedisClient(),
            timescale_pool=MockPool(),
            tenant_id="my_tenant",
            bot_id="my_bot",
        )
        
        assert loader.tenant_id == "my_tenant"
    
    def test_bot_id_property(self) -> None:
        """bot_id property returns the correct value."""
        loader = WarmStartLoader(
            redis_client=MockRedisClient(),
            timescale_pool=MockPool(),
            tenant_id="my_tenant",
            bot_id="my_bot",
        )
        
        assert loader.bot_id == "my_bot"


class TestWarmStartLoaderRedisKeyFormat:
    """Tests for Redis key format generation."""
    
    def test_get_redis_key_positions(self) -> None:
        """_get_redis_key generates correct key for positions."""
        loader = WarmStartLoader(
            redis_client=MockRedisClient(),
            timescale_pool=MockPool(),
            tenant_id="tenant1",
            bot_id="bot1",
        )
        
        key = loader._get_redis_key("positions")
        
        assert key == "quantgambit:tenant1:bot1:positions:latest"
    
    def test_get_redis_key_account(self) -> None:
        """_get_redis_key generates correct key for account."""
        loader = WarmStartLoader(
            redis_client=MockRedisClient(),
            timescale_pool=MockPool(),
            tenant_id="tenant1",
            bot_id="bot1",
        )
        
        key = loader._get_redis_key("account")
        
        assert key == "quantgambit:tenant1:bot1:account:latest"
    
    def test_get_redis_key_pipeline_state(self) -> None:
        """_get_redis_key generates correct key for pipeline_state."""
        loader = WarmStartLoader(
            redis_client=MockRedisClient(),
            timescale_pool=MockPool(),
            tenant_id="tenant1",
            bot_id="bot1",
        )
        
        key = loader._get_redis_key("pipeline_state")
        
        assert key == "quantgambit:tenant1:bot1:pipeline_state"


class TestWarmStartLoaderLoadCurrentState:
    """Tests for load_current_state() method."""
    
    @pytest.mark.asyncio
    async def test_load_current_state_returns_warm_start_state(self) -> None:
        """load_current_state() returns a WarmStartState.
        
        Requirements: 3.1, 3.2
        """
        redis = MockRedisClient()
        redis.set_data("quantgambit:tenant1:bot1:positions:latest", [])
        redis.set_data("quantgambit:tenant1:bot1:account:latest", {"equity": 10000.0})
        redis.set_data("quantgambit:tenant1:bot1:pipeline_state", {})
        
        pool = MockPool(MockConnection([]))
        
        loader = WarmStartLoader(
            redis_client=redis,
            timescale_pool=pool,
            tenant_id="tenant1",
            bot_id="bot1",
        )
        
        state = await loader.load_current_state()
        
        assert isinstance(state, WarmStartState)
        assert state.snapshot_time is not None
        assert state.snapshot_time.tzinfo == timezone.utc
    
    @pytest.mark.asyncio
    async def test_load_current_state_loads_positions_from_redis(self) -> None:
        """load_current_state() loads positions from Redis with correct key format.
        
        Requirements: 3.2, 3.3
        """
        positions = [
            {"symbol": "BTCUSDT", "size": 0.1, "entry_price": 50000.0},
            {"symbol": "ETHUSDT", "size": 1.0, "entry_price": 3000.0},
        ]
        
        redis = MockRedisClient()
        redis.set_data("quantgambit:tenant1:bot1:positions:latest", positions)
        redis.set_data("quantgambit:tenant1:bot1:account:latest", {"equity": 10000.0})
        redis.set_data("quantgambit:tenant1:bot1:pipeline_state", {})
        
        pool = MockPool(MockConnection([]))
        
        loader = WarmStartLoader(
            redis_client=redis,
            timescale_pool=pool,
            tenant_id="tenant1",
            bot_id="bot1",
        )
        
        state = await loader.load_current_state()
        
        assert state.positions == positions
        assert len(state.positions) == 2
        assert state.positions[0]["symbol"] == "BTCUSDT"
        assert state.positions[0]["size"] == 0.1
        assert state.positions[0]["entry_price"] == 50000.0
    
    @pytest.mark.asyncio
    async def test_load_current_state_loads_account_state_from_redis(self) -> None:
        """load_current_state() loads account state from Redis with correct key format.
        
        Requirements: 3.2
        """
        account_state = {"equity": 10000.0, "margin": 500.0, "balance": 9500.0}
        
        redis = MockRedisClient()
        redis.set_data("quantgambit:tenant1:bot1:positions:latest", [])
        redis.set_data("quantgambit:tenant1:bot1:account:latest", account_state)
        redis.set_data("quantgambit:tenant1:bot1:pipeline_state", {})
        
        pool = MockPool(MockConnection([]))
        
        loader = WarmStartLoader(
            redis_client=redis,
            timescale_pool=pool,
            tenant_id="tenant1",
            bot_id="bot1",
        )
        
        state = await loader.load_current_state()
        
        assert state.account_state == account_state
        assert state.account_state["equity"] == 10000.0
        assert state.account_state["margin"] == 500.0
    
    @pytest.mark.asyncio
    async def test_load_current_state_loads_pipeline_state_from_redis(self) -> None:
        """load_current_state() loads pipeline state from Redis with correct key format.
        
        Requirements: 3.2
        """
        pipeline_state = {"cooldown_until": None, "hysteresis": 0.5}
        
        redis = MockRedisClient()
        redis.set_data("quantgambit:tenant1:bot1:positions:latest", [])
        redis.set_data("quantgambit:tenant1:bot1:account:latest", {"equity": 10000.0})
        redis.set_data("quantgambit:tenant1:bot1:pipeline_state", pipeline_state)
        
        pool = MockPool(MockConnection([]))
        
        loader = WarmStartLoader(
            redis_client=redis,
            timescale_pool=pool,
            tenant_id="tenant1",
            bot_id="bot1",
        )
        
        state = await loader.load_current_state()
        
        assert state.pipeline_state == pipeline_state
        assert state.pipeline_state["cooldown_until"] is None
        assert state.pipeline_state["hysteresis"] == 0.5
    
    @pytest.mark.asyncio
    async def test_load_current_state_handles_missing_redis_data(self) -> None:
        """load_current_state() handles missing Redis data gracefully."""
        # Empty Redis - no data set
        redis = MockRedisClient()
        pool = MockPool(MockConnection([]))
        
        loader = WarmStartLoader(
            redis_client=redis,
            timescale_pool=pool,
            tenant_id="tenant1",
            bot_id="bot1",
        )
        
        state = await loader.load_current_state()
        
        assert state.positions == []
        assert state.account_state == {}
        assert state.pipeline_state == {}
    
    @pytest.mark.asyncio
    async def test_load_current_state_loads_candle_history_for_position_symbols(self) -> None:
        """load_current_state() loads candle history for symbols with positions.
        
        Requirements: 3.4
        """
        positions = [
            {"symbol": "BTCUSDT", "size": 0.1, "entry_price": 50000.0},
        ]
        
        candles = [
            {"ts": datetime.now(timezone.utc), "open": 50000, "high": 50100, "low": 49900, "close": 50050, "volume": 100},
            {"ts": datetime.now(timezone.utc), "open": 50050, "high": 50200, "low": 50000, "close": 50150, "volume": 150},
        ]
        
        redis = MockRedisClient()
        redis.set_data("quantgambit:tenant1:bot1:positions:latest", positions)
        redis.set_data("quantgambit:tenant1:bot1:account:latest", {"equity": 10000.0})
        redis.set_data("quantgambit:tenant1:bot1:pipeline_state", {})
        
        # Mock connection that returns empty decisions and candles for candle queries
        connection = MockConnection(decision_results=[], candle_results=candles)
        pool = MockPool(connection)
        
        loader = WarmStartLoader(
            redis_client=redis,
            timescale_pool=pool,
            tenant_id="tenant1",
            bot_id="bot1",
        )
        
        state = await loader.load_current_state()
        
        assert "BTCUSDT" in state.candle_history
        assert len(state.candle_history["BTCUSDT"]) == 2


class TestWarmStartLoaderLoadRecentDecisions:
    """Tests for _load_recent_decisions() method."""
    
    @pytest.mark.asyncio
    async def test_load_recent_decisions_queries_timescaledb(self) -> None:
        """_load_recent_decisions() queries TimescaleDB correctly.
        
        Requirements: 3.1
        """
        # Create mock decision rows
        decision_rows = [
            {
                "decision_id": "dec_123",
                "timestamp": datetime.now(timezone.utc),
                "symbol": "BTCUSDT",
                "config_version": "v1",
                "market_snapshot": "{}",
                "features": "{}",
                "positions": "[]",
                "account_state": "{}",
                "stage_results": "[]",
                "rejection_stage": None,
                "rejection_reason": None,
                "decision": "accepted",
                "signal": None,
                "profile_id": "profile1",
            }
        ]
        
        connection = MockConnection(decision_rows)
        pool = MockPool(connection)
        redis = MockRedisClient()
        
        loader = WarmStartLoader(
            redis_client=redis,
            timescale_pool=pool,
            tenant_id="tenant1",
            bot_id="bot1",
        )
        
        decisions = await loader._load_recent_decisions(hours=1)
        
        assert len(decisions) == 1
        assert decisions[0].decision_id == "dec_123"
        assert decisions[0].symbol == "BTCUSDT"
    
    @pytest.mark.asyncio
    async def test_load_recent_decisions_returns_empty_list_when_no_data(self) -> None:
        """_load_recent_decisions() returns empty list when no decisions found."""
        connection = MockConnection([])
        pool = MockPool(connection)
        redis = MockRedisClient()
        
        loader = WarmStartLoader(
            redis_client=redis,
            timescale_pool=pool,
            tenant_id="tenant1",
            bot_id="bot1",
        )
        
        decisions = await loader._load_recent_decisions(hours=1)
        
        assert decisions == []


class TestWarmStartLoaderLoadCandleHistory:
    """Tests for _load_candle_history() method."""
    
    @pytest.mark.asyncio
    async def test_load_candle_history_queries_timescaledb(self) -> None:
        """_load_candle_history() queries TimescaleDB correctly.
        
        Requirements: 3.4
        """
        candle_rows = [
            {"ts": datetime.now(timezone.utc), "open": 50000, "high": 50100, "low": 49900, "close": 50050, "volume": 100},
            {"ts": datetime.now(timezone.utc), "open": 50050, "high": 50200, "low": 50000, "close": 50150, "volume": 150},
        ]
        
        connection = MockConnection(candle_rows)
        pool = MockPool(connection)
        redis = MockRedisClient()
        
        loader = WarmStartLoader(
            redis_client=redis,
            timescale_pool=pool,
            tenant_id="tenant1",
            bot_id="bot1",
        )
        
        candles = await loader._load_candle_history("BTCUSDT", hours=12)
        
        assert len(candles) == 2
        assert candles[0]["open"] == 50000
        assert candles[1]["close"] == 50150
    
    @pytest.mark.asyncio
    async def test_load_candle_history_returns_empty_list_when_no_data(self) -> None:
        """_load_candle_history() returns empty list when no candles found."""
        connection = MockConnection([])
        pool = MockPool(connection)
        redis = MockRedisClient()
        
        loader = WarmStartLoader(
            redis_client=redis,
            timescale_pool=pool,
            tenant_id="tenant1",
            bot_id="bot1",
        )
        
        candles = await loader._load_candle_history("BTCUSDT", hours=12)
        
        assert candles == []
    
    @pytest.mark.asyncio
    async def test_load_candle_history_converts_rows_to_dicts(self) -> None:
        """_load_candle_history() converts database rows to dictionaries."""
        # Simulate asyncpg Record-like objects
        class MockRecord(dict):
            pass
        
        candle_rows = [
            MockRecord({"ts": datetime.now(timezone.utc), "open": 50000, "high": 50100, "low": 49900, "close": 50050, "volume": 100}),
        ]
        
        connection = MockConnection(candle_rows)
        pool = MockPool(connection)
        redis = MockRedisClient()
        
        loader = WarmStartLoader(
            redis_client=redis,
            timescale_pool=pool,
            tenant_id="tenant1",
            bot_id="bot1",
        )
        
        candles = await loader._load_candle_history("BTCUSDT", hours=12)
        
        assert isinstance(candles[0], dict)
        assert "open" in candles[0]
        assert "close" in candles[0]


class TestWarmStartLoaderRowToDecision:
    """Tests for _row_to_decision() helper method."""
    
    def test_row_to_decision_converts_row(self) -> None:
        """_row_to_decision() converts database row to RecordedDecision."""
        row = {
            "decision_id": "dec_456",
            "timestamp": datetime.now(timezone.utc),
            "symbol": "ETHUSDT",
            "config_version": "v2",
            "market_snapshot": "{}",
            "features": "{}",
            "positions": "[]",
            "account_state": "{}",
            "stage_results": "[]",
            "rejection_stage": "ev_gate",
            "rejection_reason": "EV too low",
            "decision": "rejected",
            "signal": None,
            "profile_id": "profile2",
        }
        
        loader = WarmStartLoader(
            redis_client=MockRedisClient(),
            timescale_pool=MockPool(),
            tenant_id="tenant1",
            bot_id="bot1",
        )
        
        decision = loader._row_to_decision(row)
        
        assert decision.decision_id == "dec_456"
        assert decision.symbol == "ETHUSDT"
        assert decision.rejection_stage == "ev_gate"
        assert decision.decision == "rejected"


class TestWarmStartLoaderIntegration:
    """Integration tests for WarmStartLoader."""
    
    @pytest.mark.asyncio
    async def test_full_load_with_multiple_positions(self) -> None:
        """Full load with multiple positions loads candle history for each symbol."""
        positions = [
            {"symbol": "BTCUSDT", "size": 0.1, "entry_price": 50000.0},
            {"symbol": "ETHUSDT", "size": 1.0, "entry_price": 3000.0},
            {"symbol": "BTCUSDT", "size": 0.2, "entry_price": 51000.0},  # Duplicate symbol
        ]
        
        redis = MockRedisClient()
        redis.set_data("quantgambit:tenant1:bot1:positions:latest", positions)
        redis.set_data("quantgambit:tenant1:bot1:account:latest", {"equity": 10000.0})
        redis.set_data("quantgambit:tenant1:bot1:pipeline_state", {})
        
        # Mock connection returns empty decisions and candles
        candles = [{"ts": datetime.now(timezone.utc), "open": 50000, "high": 50100, "low": 49900, "close": 50050, "volume": 100}]
        connection = MockConnection(decision_results=[], candle_results=candles)
        pool = MockPool(connection)
        
        loader = WarmStartLoader(
            redis_client=redis,
            timescale_pool=pool,
            tenant_id="tenant1",
            bot_id="bot1",
        )
        
        state = await loader.load_current_state()
        
        # Should have candle history for unique symbols only
        assert "BTCUSDT" in state.candle_history
        assert "ETHUSDT" in state.candle_history
        assert len(state.candle_history) == 2
    
    @pytest.mark.asyncio
    async def test_loaded_state_can_be_validated(self) -> None:
        """Loaded state can be validated using WarmStartState.validate()."""
        positions = [
            {"symbol": "BTCUSDT", "size": 0.1, "entry_price": 50000.0},
        ]
        
        redis = MockRedisClient()
        redis.set_data("quantgambit:tenant1:bot1:positions:latest", positions)
        redis.set_data("quantgambit:tenant1:bot1:account:latest", {"equity": 10000.0})
        redis.set_data("quantgambit:tenant1:bot1:pipeline_state", {})
        
        pool = MockPool(MockConnection([]))
        
        loader = WarmStartLoader(
            redis_client=redis,
            timescale_pool=pool,
            tenant_id="tenant1",
            bot_id="bot1",
        )
        
        state = await loader.load_current_state()
        valid, errors = state.validate()
        
        assert valid is True
        assert errors == []
    
    @pytest.mark.asyncio
    async def test_loaded_state_staleness_check(self) -> None:
        """Loaded state can be checked for staleness."""
        redis = MockRedisClient()
        redis.set_data("quantgambit:tenant1:bot1:positions:latest", [])
        redis.set_data("quantgambit:tenant1:bot1:account:latest", {"equity": 10000.0})
        redis.set_data("quantgambit:tenant1:bot1:pipeline_state", {})
        
        pool = MockPool(MockConnection([]))
        
        loader = WarmStartLoader(
            redis_client=redis,
            timescale_pool=pool,
            tenant_id="tenant1",
            bot_id="bot1",
        )
        
        state = await loader.load_current_state()
        
        # Freshly loaded state should not be stale
        assert state.is_stale() is False


class TestWarmStartLoaderExportState:
    """Tests for export_state() method.
    
    Feature: trading-pipeline-integration
    Requirements: 8.1 - THE System SHALL support exporting live state to a format
                  consumable by backtest
    Requirements: 8.2 - WHEN exporting state THEN the System SHALL include positions,
                  account state, recent decisions, and pipeline state
    Requirements: 8.5 - THE System SHALL support point-in-time state snapshots for
                  reproducible testing
    """
    
    @pytest.mark.asyncio
    async def test_export_state_returns_warm_start_state(self) -> None:
        """export_state() returns a WarmStartState.
        
        Requirements: 8.1
        """
        redis = MockRedisClient()
        redis.set_data("quantgambit:tenant1:bot1:positions:latest", [])
        redis.set_data("quantgambit:tenant1:bot1:account:latest", {"equity": 10000.0})
        redis.set_data("quantgambit:tenant1:bot1:pipeline_state", {})
        
        pool = MockPool(MockConnection([]))
        
        loader = WarmStartLoader(
            redis_client=redis,
            timescale_pool=pool,
            tenant_id="tenant1",
            bot_id="bot1",
        )
        
        state = await loader.export_state()
        
        assert isinstance(state, WarmStartState)
        assert state.snapshot_time is not None
        assert state.snapshot_time.tzinfo == timezone.utc
    
    @pytest.mark.asyncio
    async def test_export_state_includes_positions(self) -> None:
        """export_state() includes positions from Redis.
        
        Requirements: 8.2
        """
        positions = [
            {"symbol": "BTCUSDT", "size": 0.1, "entry_price": 50000.0},
            {"symbol": "ETHUSDT", "size": 1.0, "entry_price": 3000.0},
        ]
        
        redis = MockRedisClient()
        redis.set_data("quantgambit:tenant1:bot1:positions:latest", positions)
        redis.set_data("quantgambit:tenant1:bot1:account:latest", {"equity": 10000.0})
        redis.set_data("quantgambit:tenant1:bot1:pipeline_state", {})
        
        pool = MockPool(MockConnection([]))
        
        loader = WarmStartLoader(
            redis_client=redis,
            timescale_pool=pool,
            tenant_id="tenant1",
            bot_id="bot1",
        )
        
        state = await loader.export_state()
        
        assert state.positions == positions
        assert len(state.positions) == 2
    
    @pytest.mark.asyncio
    async def test_export_state_includes_account_state(self) -> None:
        """export_state() includes account state from Redis.
        
        Requirements: 8.2
        """
        account_state = {"equity": 10000.0, "margin": 500.0, "balance": 9500.0}
        
        redis = MockRedisClient()
        redis.set_data("quantgambit:tenant1:bot1:positions:latest", [])
        redis.set_data("quantgambit:tenant1:bot1:account:latest", account_state)
        redis.set_data("quantgambit:tenant1:bot1:pipeline_state", {})
        
        pool = MockPool(MockConnection([]))
        
        loader = WarmStartLoader(
            redis_client=redis,
            timescale_pool=pool,
            tenant_id="tenant1",
            bot_id="bot1",
        )
        
        state = await loader.export_state()
        
        assert state.account_state == account_state
    
    @pytest.mark.asyncio
    async def test_export_state_includes_pipeline_state(self) -> None:
        """export_state() includes pipeline state from Redis.
        
        Requirements: 8.2
        """
        pipeline_state = {"cooldown_until": None, "hysteresis": 0.5}
        
        redis = MockRedisClient()
        redis.set_data("quantgambit:tenant1:bot1:positions:latest", [])
        redis.set_data("quantgambit:tenant1:bot1:account:latest", {"equity": 10000.0})
        redis.set_data("quantgambit:tenant1:bot1:pipeline_state", pipeline_state)
        
        pool = MockPool(MockConnection([]))
        
        loader = WarmStartLoader(
            redis_client=redis,
            timescale_pool=pool,
            tenant_id="tenant1",
            bot_id="bot1",
        )
        
        state = await loader.export_state()
        
        assert state.pipeline_state == pipeline_state
    
    @pytest.mark.asyncio
    async def test_export_state_with_custom_snapshot_time(self) -> None:
        """export_state() supports custom snapshot_time for point-in-time snapshots.
        
        Requirements: 8.5
        """
        custom_time = datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
        
        redis = MockRedisClient()
        redis.set_data("quantgambit:tenant1:bot1:positions:latest", [])
        redis.set_data("quantgambit:tenant1:bot1:account:latest", {"equity": 10000.0})
        redis.set_data("quantgambit:tenant1:bot1:pipeline_state", {})
        
        pool = MockPool(MockConnection([]))
        
        loader = WarmStartLoader(
            redis_client=redis,
            timescale_pool=pool,
            tenant_id="tenant1",
            bot_id="bot1",
        )
        
        state = await loader.export_state(snapshot_time=custom_time)
        
        assert state.snapshot_time == custom_time
    
    @pytest.mark.asyncio
    async def test_export_state_with_naive_snapshot_time_adds_utc(self) -> None:
        """export_state() adds UTC timezone to naive snapshot_time.
        
        Requirements: 8.5
        """
        naive_time = datetime(2024, 1, 15, 12, 0, 0)  # No timezone
        
        redis = MockRedisClient()
        redis.set_data("quantgambit:tenant1:bot1:positions:latest", [])
        redis.set_data("quantgambit:tenant1:bot1:account:latest", {"equity": 10000.0})
        redis.set_data("quantgambit:tenant1:bot1:pipeline_state", {})
        
        pool = MockPool(MockConnection([]))
        
        loader = WarmStartLoader(
            redis_client=redis,
            timescale_pool=pool,
            tenant_id="tenant1",
            bot_id="bot1",
        )
        
        state = await loader.export_state(snapshot_time=naive_time)
        
        assert state.snapshot_time.tzinfo == timezone.utc
        assert state.snapshot_time.year == 2024
        assert state.snapshot_time.month == 1
        assert state.snapshot_time.day == 15
    
    @pytest.mark.asyncio
    async def test_export_state_without_decisions(self) -> None:
        """export_state() can exclude decisions when include_decisions=False."""
        redis = MockRedisClient()
        redis.set_data("quantgambit:tenant1:bot1:positions:latest", [])
        redis.set_data("quantgambit:tenant1:bot1:account:latest", {"equity": 10000.0})
        redis.set_data("quantgambit:tenant1:bot1:pipeline_state", {})
        
        # Even if there are decisions in the DB, they should not be loaded
        decision_rows = [
            {
                "decision_id": "dec_123",
                "timestamp": datetime.now(timezone.utc),
                "symbol": "BTCUSDT",
                "config_version": "v1",
                "market_snapshot": "{}",
                "features": "{}",
                "positions": "[]",
                "account_state": "{}",
                "stage_results": "[]",
                "rejection_stage": None,
                "rejection_reason": None,
                "decision": "accepted",
                "signal": None,
                "profile_id": "profile1",
            }
        ]
        pool = MockPool(MockConnection(decision_rows))
        
        loader = WarmStartLoader(
            redis_client=redis,
            timescale_pool=pool,
            tenant_id="tenant1",
            bot_id="bot1",
        )
        
        state = await loader.export_state(include_decisions=False)
        
        assert state.recent_decisions == []
    
    @pytest.mark.asyncio
    async def test_export_state_without_candles(self) -> None:
        """export_state() can exclude candles when include_candles=False."""
        positions = [{"symbol": "BTCUSDT", "size": 0.1, "entry_price": 50000.0}]
        
        redis = MockRedisClient()
        redis.set_data("quantgambit:tenant1:bot1:positions:latest", positions)
        redis.set_data("quantgambit:tenant1:bot1:account:latest", {"equity": 10000.0})
        redis.set_data("quantgambit:tenant1:bot1:pipeline_state", {})
        
        pool = MockPool(MockConnection([]))
        
        loader = WarmStartLoader(
            redis_client=redis,
            timescale_pool=pool,
            tenant_id="tenant1",
            bot_id="bot1",
        )
        
        state = await loader.export_state(include_candles=False)
        
        assert state.candle_history == {}
    
    @pytest.mark.asyncio
    async def test_export_state_is_json_serializable(self) -> None:
        """export_state() result can be serialized to JSON.
        
        Requirements: 8.5
        """
        positions = [{"symbol": "BTCUSDT", "size": 0.1, "entry_price": 50000.0}]
        account_state = {"equity": 10000.0, "margin": 500.0}
        pipeline_state = {"cooldown": False}
        
        redis = MockRedisClient()
        redis.set_data("quantgambit:tenant1:bot1:positions:latest", positions)
        redis.set_data("quantgambit:tenant1:bot1:account:latest", account_state)
        redis.set_data("quantgambit:tenant1:bot1:pipeline_state", pipeline_state)
        
        pool = MockPool(MockConnection([]))
        
        loader = WarmStartLoader(
            redis_client=redis,
            timescale_pool=pool,
            tenant_id="tenant1",
            bot_id="bot1",
        )
        
        state = await loader.export_state(include_decisions=False)
        
        # Should not raise
        json_str = state.to_json()
        assert isinstance(json_str, str)
        
        # Should be valid JSON
        parsed = json.loads(json_str)
        assert "snapshot_time" in parsed
        assert "positions" in parsed
        assert "account_state" in parsed
        assert "pipeline_state" in parsed


class TestWarmStartLoaderExportStateJson:
    """Tests for export_state_json() method."""
    
    @pytest.mark.asyncio
    async def test_export_state_json_returns_string(self) -> None:
        """export_state_json() returns a JSON string."""
        redis = MockRedisClient()
        redis.set_data("quantgambit:tenant1:bot1:positions:latest", [])
        redis.set_data("quantgambit:tenant1:bot1:account:latest", {"equity": 10000.0})
        redis.set_data("quantgambit:tenant1:bot1:pipeline_state", {})
        
        pool = MockPool(MockConnection([]))
        
        loader = WarmStartLoader(
            redis_client=redis,
            timescale_pool=pool,
            tenant_id="tenant1",
            bot_id="bot1",
        )
        
        json_str = await loader.export_state_json()
        
        assert isinstance(json_str, str)
        # Should be valid JSON
        parsed = json.loads(json_str)
        assert isinstance(parsed, dict)
    
    @pytest.mark.asyncio
    async def test_export_state_json_with_custom_snapshot_time(self) -> None:
        """export_state_json() supports custom snapshot_time."""
        custom_time = datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
        
        redis = MockRedisClient()
        redis.set_data("quantgambit:tenant1:bot1:positions:latest", [])
        redis.set_data("quantgambit:tenant1:bot1:account:latest", {"equity": 10000.0})
        redis.set_data("quantgambit:tenant1:bot1:pipeline_state", {})
        
        pool = MockPool(MockConnection([]))
        
        loader = WarmStartLoader(
            redis_client=redis,
            timescale_pool=pool,
            tenant_id="tenant1",
            bot_id="bot1",
        )
        
        json_str = await loader.export_state_json(snapshot_time=custom_time)
        
        parsed = json.loads(json_str)
        assert "2024-01-15" in parsed["snapshot_time"]
    
    @pytest.mark.asyncio
    async def test_export_state_json_round_trip(self) -> None:
        """export_state_json() result can be parsed back to WarmStartState."""
        positions = [{"symbol": "BTCUSDT", "size": 0.1, "entry_price": 50000.0}]
        account_state = {"equity": 10000.0, "margin": 500.0}
        pipeline_state = {"cooldown": False}
        
        redis = MockRedisClient()
        redis.set_data("quantgambit:tenant1:bot1:positions:latest", positions)
        redis.set_data("quantgambit:tenant1:bot1:account:latest", account_state)
        redis.set_data("quantgambit:tenant1:bot1:pipeline_state", pipeline_state)
        
        pool = MockPool(MockConnection([]))
        
        loader = WarmStartLoader(
            redis_client=redis,
            timescale_pool=pool,
            tenant_id="tenant1",
            bot_id="bot1",
        )
        
        json_str = await loader.export_state_json(include_decisions=False)
        
        # Parse back to WarmStartState
        restored = WarmStartState.from_json(json_str)
        
        assert restored.positions == positions
        assert restored.account_state == account_state
        assert restored.pipeline_state == pipeline_state


class TestWarmStartLoaderImportState:
    """Tests for import_state() method.
    
    Feature: trading-pipeline-integration
    Requirements: 8.3 - State import validates consistency before applying
    Requirements: 8.4 - State import reports specific inconsistencies on validation failure
    Requirements: 8.6 - State import supports importing backtest final state
    """
    
    @pytest.mark.asyncio
    async def test_import_state_from_json_string(self) -> None:
        """import_state() can import from JSON string.
        
        Requirements: 8.6
        """
        json_str = json.dumps({
            "snapshot_time": datetime.now(timezone.utc).isoformat(),
            "positions": [{"symbol": "BTCUSDT", "size": 0.1, "entry_price": 50000.0}],
            "account_state": {"equity": 10000.0},
            "recent_decisions": [],
            "candle_history": {},
            "pipeline_state": {},
        })
        
        redis = MockRedisClient()
        pool = MockPool(MockConnection([]))
        
        loader = WarmStartLoader(
            redis_client=redis,
            timescale_pool=pool,
            tenant_id="tenant1",
            bot_id="bot1",
        )
        
        result = await loader.import_state(json_str, validate_against_live=False)
        
        assert result.is_valid
        assert result.state is not None
        assert len(result.state.positions) == 1
        assert result.state.positions[0]["symbol"] == "BTCUSDT"
    
    @pytest.mark.asyncio
    async def test_import_state_from_dict(self) -> None:
        """import_state() can import from dictionary.
        
        Requirements: 8.6
        """
        state_dict = {
            "snapshot_time": datetime.now(timezone.utc).isoformat(),
            "positions": [{"symbol": "ETHUSDT", "size": 1.0, "entry_price": 3000.0}],
            "account_state": {"equity": 5000.0},
            "recent_decisions": [],
            "candle_history": {},
            "pipeline_state": {},
        }
        
        redis = MockRedisClient()
        pool = MockPool(MockConnection([]))
        
        loader = WarmStartLoader(
            redis_client=redis,
            timescale_pool=pool,
            tenant_id="tenant1",
            bot_id="bot1",
        )
        
        result = await loader.import_state(state_dict, validate_against_live=False)
        
        assert result.is_valid
        assert result.state is not None
        assert result.state.positions[0]["symbol"] == "ETHUSDT"
    
    @pytest.mark.asyncio
    async def test_import_state_from_warm_start_state(self) -> None:
        """import_state() can import from WarmStartState object directly.
        
        Requirements: 8.6
        """
        state = WarmStartState(
            snapshot_time=datetime.now(timezone.utc),
            positions=[{"symbol": "BTCUSDT", "size": 0.5, "entry_price": 45000.0}],
            account_state={"equity": 20000.0},
            recent_decisions=[],
            candle_history={},
            pipeline_state={},
        )
        
        redis = MockRedisClient()
        pool = MockPool(MockConnection([]))
        
        loader = WarmStartLoader(
            redis_client=redis,
            timescale_pool=pool,
            tenant_id="tenant1",
            bot_id="bot1",
        )
        
        result = await loader.import_state(state, validate_against_live=False)
        
        assert result.is_valid
        assert result.state is state  # Same object
    
    @pytest.mark.asyncio
    async def test_import_state_validates_consistency(self) -> None:
        """import_state() validates state consistency.
        
        Requirements: 8.3
        """
        # State with position value exceeding 10x equity
        state_dict = {
            "snapshot_time": datetime.now(timezone.utc).isoformat(),
            "positions": [{"symbol": "BTCUSDT", "size": 100, "entry_price": 50000.0}],  # 5M value
            "account_state": {"equity": 1000.0},  # Only 1K equity
            "recent_decisions": [],
            "candle_history": {},
            "pipeline_state": {},
        }
        
        redis = MockRedisClient()
        pool = MockPool(MockConnection([]))
        
        loader = WarmStartLoader(
            redis_client=redis,
            timescale_pool=pool,
            tenant_id="tenant1",
            bot_id="bot1",
        )
        
        result = await loader.import_state(state_dict, validate_against_live=False)
        
        assert result.status == ImportValidationStatus.FAILED
        assert not result.is_valid
        assert any("exceeds" in error.lower() for error in result.errors)
    
    @pytest.mark.asyncio
    async def test_import_state_reports_missing_equity(self) -> None:
        """import_state() reports missing equity as error.
        
        Requirements: 8.4
        """
        state_dict = {
            "snapshot_time": datetime.now(timezone.utc).isoformat(),
            "positions": [],
            "account_state": {},  # Missing equity
            "recent_decisions": [],
            "candle_history": {},
            "pipeline_state": {},
        }
        
        redis = MockRedisClient()
        pool = MockPool(MockConnection([]))
        
        loader = WarmStartLoader(
            redis_client=redis,
            timescale_pool=pool,
            tenant_id="tenant1",
            bot_id="bot1",
        )
        
        result = await loader.import_state(state_dict, validate_against_live=False)
        
        assert result.status == ImportValidationStatus.FAILED
        assert any("equity" in error.lower() for error in result.errors)
    
    @pytest.mark.asyncio
    async def test_import_state_reports_invalid_json(self) -> None:
        """import_state() reports invalid JSON format.
        
        Requirements: 8.4
        """
        invalid_json = "{ invalid json }"
        
        redis = MockRedisClient()
        pool = MockPool(MockConnection([]))
        
        loader = WarmStartLoader(
            redis_client=redis,
            timescale_pool=pool,
            tenant_id="tenant1",
            bot_id="bot1",
        )
        
        result = await loader.import_state(invalid_json, validate_against_live=False)
        
        assert result.status == ImportValidationStatus.FAILED
        assert any("json" in error.lower() for error in result.errors)
    
    @pytest.mark.asyncio
    async def test_import_state_reports_missing_position_symbol(self) -> None:
        """import_state() reports missing position symbol.
        
        Requirements: 8.4
        """
        state_dict = {
            "snapshot_time": datetime.now(timezone.utc).isoformat(),
            "positions": [{"size": 0.1, "entry_price": 50000.0}],  # Missing symbol
            "account_state": {"equity": 10000.0},
            "recent_decisions": [],
            "candle_history": {},
            "pipeline_state": {},
        }
        
        redis = MockRedisClient()
        pool = MockPool(MockConnection([]))
        
        loader = WarmStartLoader(
            redis_client=redis,
            timescale_pool=pool,
            tenant_id="tenant1",
            bot_id="bot1",
        )
        
        result = await loader.import_state(state_dict, validate_against_live=False)
        
        assert result.status == ImportValidationStatus.FAILED
        assert any("symbol" in error.lower() for error in result.errors)
    
    @pytest.mark.asyncio
    async def test_import_state_reports_missing_position_size(self) -> None:
        """import_state() reports missing position size.
        
        Requirements: 8.4
        """
        state_dict = {
            "snapshot_time": datetime.now(timezone.utc).isoformat(),
            "positions": [{"symbol": "BTCUSDT", "entry_price": 50000.0}],  # Missing size
            "account_state": {"equity": 10000.0},
            "recent_decisions": [],
            "candle_history": {},
            "pipeline_state": {},
        }
        
        redis = MockRedisClient()
        pool = MockPool(MockConnection([]))
        
        loader = WarmStartLoader(
            redis_client=redis,
            timescale_pool=pool,
            tenant_id="tenant1",
            bot_id="bot1",
        )
        
        result = await loader.import_state(state_dict, validate_against_live=False)
        
        assert result.status == ImportValidationStatus.FAILED
        assert any("size" in error.lower() for error in result.errors)
    
    @pytest.mark.asyncio
    async def test_import_state_warns_on_zero_position_size(self) -> None:
        """import_state() warns on zero position size.
        
        Requirements: 8.4
        """
        state_dict = {
            "snapshot_time": datetime.now(timezone.utc).isoformat(),
            "positions": [{"symbol": "BTCUSDT", "size": 0, "entry_price": 50000.0}],
            "account_state": {"equity": 10000.0},
            "recent_decisions": [],
            "candle_history": {},
            "pipeline_state": {},
        }
        
        redis = MockRedisClient()
        pool = MockPool(MockConnection([]))
        
        loader = WarmStartLoader(
            redis_client=redis,
            timescale_pool=pool,
            tenant_id="tenant1",
            bot_id="bot1",
        )
        
        result = await loader.import_state(state_dict, validate_against_live=False)
        
        assert result.status == ImportValidationStatus.WARNING
        assert result.is_valid  # Still valid, just has warnings
        assert any("zero" in warning.lower() for warning in result.warnings)
    
    @pytest.mark.asyncio
    async def test_import_state_warns_on_stale_state(self) -> None:
        """import_state() warns when state is stale.
        
        Requirements: 8.4
        """
        from datetime import timedelta
        
        old_time = datetime.now(timezone.utc) - timedelta(minutes=10)
        state_dict = {
            "snapshot_time": old_time.isoformat(),
            "positions": [],
            "account_state": {"equity": 10000.0},
            "recent_decisions": [],
            "candle_history": {},
            "pipeline_state": {},
        }
        
        redis = MockRedisClient()
        pool = MockPool(MockConnection([]))
        
        loader = WarmStartLoader(
            redis_client=redis,
            timescale_pool=pool,
            tenant_id="tenant1",
            bot_id="bot1",
        )
        
        result = await loader.import_state(state_dict, validate_against_live=False)
        
        assert result.status == ImportValidationStatus.WARNING
        assert any("stale" in warning.lower() for warning in result.warnings)
    
    @pytest.mark.asyncio
    async def test_import_state_validates_against_live_state(self) -> None:
        """import_state() compares against live state when validate_against_live=True.
        
        Requirements: 8.3
        """
        # Set up live state with different positions
        redis = MockRedisClient()
        redis.set_data("quantgambit:tenant1:bot1:positions:latest", [
            {"symbol": "ETHUSDT", "size": 2.0, "entry_price": 3000.0}
        ])
        redis.set_data("quantgambit:tenant1:bot1:account:latest", {"equity": 15000.0})
        redis.set_data("quantgambit:tenant1:bot1:pipeline_state", {})
        
        pool = MockPool(MockConnection([]))
        
        loader = WarmStartLoader(
            redis_client=redis,
            timescale_pool=pool,
            tenant_id="tenant1",
            bot_id="bot1",
        )
        
        # Import state with different positions
        state_dict = {
            "snapshot_time": datetime.now(timezone.utc).isoformat(),
            "positions": [{"symbol": "BTCUSDT", "size": 0.1, "entry_price": 50000.0}],
            "account_state": {"equity": 10000.0},
            "recent_decisions": [],
            "candle_history": {},
            "pipeline_state": {},
        }
        
        result = await loader.import_state(state_dict, validate_against_live=True)
        
        # Should have warnings about differences
        assert result.has_warnings
        assert any("symbol" in warning.lower() or "position" in warning.lower() 
                   for warning in result.warnings)
    
    @pytest.mark.asyncio
    async def test_import_state_applies_to_redis(self) -> None:
        """import_state() applies state to Redis when apply_to_redis=True.
        
        Requirements: 8.6
        """
        redis = MockRedisClient()
        pool = MockPool(MockConnection([]))
        
        loader = WarmStartLoader(
            redis_client=redis,
            timescale_pool=pool,
            tenant_id="tenant1",
            bot_id="bot1",
        )
        
        state_dict = {
            "snapshot_time": datetime.now(timezone.utc).isoformat(),
            "positions": [{"symbol": "BTCUSDT", "size": 0.1, "entry_price": 50000.0}],
            "account_state": {"equity": 10000.0},
            "recent_decisions": [],
            "candle_history": {},
            "pipeline_state": {"cooldown": False},
        }
        
        result = await loader.import_state(
            state_dict, 
            apply_to_redis=True, 
            validate_against_live=False
        )
        
        assert result.is_valid
        assert result.applied
        
        # Verify Redis was updated
        positions_json = await redis.get("quantgambit:tenant1:bot1:positions:latest")
        assert positions_json is not None
        positions = json.loads(positions_json)
        assert len(positions) == 1
        assert positions[0]["symbol"] == "BTCUSDT"
        
        account_json = await redis.get("quantgambit:tenant1:bot1:account:latest")
        assert account_json is not None
        account = json.loads(account_json)
        assert account["equity"] == 10000.0
    
    @pytest.mark.asyncio
    async def test_import_state_does_not_apply_on_validation_failure(self) -> None:
        """import_state() does not apply to Redis when validation fails.
        
        Requirements: 8.3
        """
        redis = MockRedisClient()
        pool = MockPool(MockConnection([]))
        
        loader = WarmStartLoader(
            redis_client=redis,
            timescale_pool=pool,
            tenant_id="tenant1",
            bot_id="bot1",
        )
        
        # Invalid state - missing equity
        state_dict = {
            "snapshot_time": datetime.now(timezone.utc).isoformat(),
            "positions": [],
            "account_state": {},  # Missing equity
            "recent_decisions": [],
            "candle_history": {},
            "pipeline_state": {},
        }
        
        result = await loader.import_state(
            state_dict, 
            apply_to_redis=True, 
            validate_against_live=False
        )
        
        assert not result.is_valid
        assert not result.applied
        
        # Verify Redis was NOT updated
        positions_json = await redis.get("quantgambit:tenant1:bot1:positions:latest")
        assert positions_json is None
    
    @pytest.mark.asyncio
    async def test_import_state_result_to_dict(self) -> None:
        """StateImportResult.to_dict() returns serializable dictionary."""
        state_dict = {
            "snapshot_time": datetime.now(timezone.utc).isoformat(),
            "positions": [{"symbol": "BTCUSDT", "size": 0.1, "entry_price": 50000.0}],
            "account_state": {"equity": 10000.0},
            "recent_decisions": [],
            "candle_history": {},
            "pipeline_state": {},
        }
        
        redis = MockRedisClient()
        pool = MockPool(MockConnection([]))
        
        loader = WarmStartLoader(
            redis_client=redis,
            timescale_pool=pool,
            tenant_id="tenant1",
            bot_id="bot1",
        )
        
        result = await loader.import_state(state_dict, validate_against_live=False)
        result_dict = result.to_dict()
        
        assert isinstance(result_dict, dict)
        assert "status" in result_dict
        assert "is_valid" in result_dict
        assert "errors" in result_dict
        assert "warnings" in result_dict
        assert "applied" in result_dict
        assert "state_summary" in result_dict
        
        # Should be JSON serializable
        json_str = json.dumps(result_dict)
        assert isinstance(json_str, str)
    
    @pytest.mark.asyncio
    async def test_import_state_warns_on_missing_candle_history(self) -> None:
        """import_state() warns when candle history is missing for position symbols.
        
        Requirements: 8.4
        """
        state_dict = {
            "snapshot_time": datetime.now(timezone.utc).isoformat(),
            "positions": [{"symbol": "BTCUSDT", "size": 0.1, "entry_price": 50000.0}],
            "account_state": {"equity": 10000.0},
            "recent_decisions": [],
            "candle_history": {},  # No candle history for BTCUSDT
            "pipeline_state": {},
        }
        
        redis = MockRedisClient()
        pool = MockPool(MockConnection([]))
        
        loader = WarmStartLoader(
            redis_client=redis,
            timescale_pool=pool,
            tenant_id="tenant1",
            bot_id="bot1",
        )
        
        result = await loader.import_state(state_dict, validate_against_live=False)
        
        assert result.has_warnings
        assert any("candle" in warning.lower() for warning in result.warnings)
    
    @pytest.mark.asyncio
    async def test_import_state_warns_on_negative_balance(self) -> None:
        """import_state() warns on negative account balance.
        
        Requirements: 8.4
        """
        state_dict = {
            "snapshot_time": datetime.now(timezone.utc).isoformat(),
            "positions": [],
            "account_state": {"equity": 10000.0, "balance": -500.0},
            "recent_decisions": [],
            "candle_history": {},
            "pipeline_state": {},
        }
        
        redis = MockRedisClient()
        pool = MockPool(MockConnection([]))
        
        loader = WarmStartLoader(
            redis_client=redis,
            timescale_pool=pool,
            tenant_id="tenant1",
            bot_id="bot1",
        )
        
        result = await loader.import_state(state_dict, validate_against_live=False)
        
        assert result.has_warnings
        assert any("negative" in warning.lower() for warning in result.warnings)
    
    @pytest.mark.asyncio
    async def test_import_state_warns_on_high_margin_ratio(self) -> None:
        """import_state() warns when margin exceeds equity.
        
        Requirements: 8.4
        """
        state_dict = {
            "snapshot_time": datetime.now(timezone.utc).isoformat(),
            "positions": [],
            "account_state": {"equity": 10000.0, "margin": 15000.0},  # Margin > equity
            "recent_decisions": [],
            "candle_history": {},
            "pipeline_state": {},
        }
        
        redis = MockRedisClient()
        pool = MockPool(MockConnection([]))
        
        loader = WarmStartLoader(
            redis_client=redis,
            timescale_pool=pool,
            tenant_id="tenant1",
            bot_id="bot1",
        )
        
        result = await loader.import_state(state_dict, validate_against_live=False)
        
        assert result.has_warnings
        assert any("margin" in warning.lower() for warning in result.warnings)
    
    @pytest.mark.asyncio
    async def test_import_state_round_trip_with_export(self) -> None:
        """import_state() can import state exported by export_state().
        
        Requirements: 8.6
        """
        positions = [{"symbol": "BTCUSDT", "size": 0.1, "entry_price": 50000.0}]
        account_state = {"equity": 10000.0, "margin": 500.0}
        pipeline_state = {"cooldown": False}
        
        redis = MockRedisClient()
        redis.set_data("quantgambit:tenant1:bot1:positions:latest", positions)
        redis.set_data("quantgambit:tenant1:bot1:account:latest", account_state)
        redis.set_data("quantgambit:tenant1:bot1:pipeline_state", pipeline_state)
        
        pool = MockPool(MockConnection([]))
        
        loader = WarmStartLoader(
            redis_client=redis,
            timescale_pool=pool,
            tenant_id="tenant1",
            bot_id="bot1",
        )
        
        # Export state
        exported_json = await loader.export_state_json(include_decisions=False)
        
        # Import the exported state
        result = await loader.import_state(exported_json, validate_against_live=False)
        
        assert result.is_valid
        assert result.state is not None
        assert result.state.positions == positions
        assert result.state.account_state == account_state
        assert result.state.pipeline_state == pipeline_state


class TestStateImportResult:
    """Tests for StateImportResult dataclass."""
    
    def test_is_valid_true_for_success(self) -> None:
        """is_valid returns True for SUCCESS status."""
        result = StateImportResult(
            status=ImportValidationStatus.SUCCESS,
            state=None,
            errors=[],
            warnings=[],
            applied=False,
        )
        
        assert result.is_valid is True
    
    def test_is_valid_true_for_warning(self) -> None:
        """is_valid returns True for WARNING status."""
        result = StateImportResult(
            status=ImportValidationStatus.WARNING,
            state=None,
            errors=[],
            warnings=["Some warning"],
            applied=False,
        )
        
        assert result.is_valid is True
    
    def test_is_valid_false_for_failed(self) -> None:
        """is_valid returns False for FAILED status."""
        result = StateImportResult(
            status=ImportValidationStatus.FAILED,
            state=None,
            errors=["Some error"],
            warnings=[],
            applied=False,
        )
        
        assert result.is_valid is False
    
    def test_has_warnings_true_when_warnings_exist(self) -> None:
        """has_warnings returns True when warnings list is not empty."""
        result = StateImportResult(
            status=ImportValidationStatus.WARNING,
            state=None,
            errors=[],
            warnings=["Warning 1", "Warning 2"],
            applied=False,
        )
        
        assert result.has_warnings is True
    
    def test_has_warnings_false_when_no_warnings(self) -> None:
        """has_warnings returns False when warnings list is empty."""
        result = StateImportResult(
            status=ImportValidationStatus.SUCCESS,
            state=None,
            errors=[],
            warnings=[],
            applied=False,
        )
        
        assert result.has_warnings is False
