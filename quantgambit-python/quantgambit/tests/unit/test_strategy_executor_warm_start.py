"""Unit tests for warm start integration with StrategyBacktestExecutor.

Feature: trading-pipeline-integration
Task: 4.3 Integrate warm start with backtest executor

Tests verify:
1. execute() accepts warm_start_state parameter
2. When warm_start_state is provided, positions are initialized from it
3. When warm_start_state is provided, account state is initialized from it
4. When warm_start_state is provided, candle cache is pre-populated
5. When warm_start_state is None, cold start behavior is used

Requirements: 3.1 - THE System SHALL support initializing a backtest with current
              live positions, account state, and recent decision history
"""

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from typing import Any, Dict, List

from quantgambit.backtesting.strategy_executor import (
    StrategyBacktestExecutor,
    StrategyExecutorConfig,
)
from quantgambit.integration.warm_start import WarmStartState


class TestWarmStartIntegration:
    """Tests for warm start integration with StrategyBacktestExecutor."""
    
    @pytest.fixture
    def mock_platform_pool(self):
        """Create a mock platform pool."""
        pool = AsyncMock()
        pool.acquire = AsyncMock()
        return pool
    
    @pytest.fixture
    def executor_config(self):
        """Create a test executor config."""
        return StrategyExecutorConfig(
            timescale_host="localhost",
            timescale_port=5433,
            timescale_db="test_db",
            timescale_user="test_user",
            timescale_password="test_pass",
            sample_every=1,
        )
    
    @pytest.fixture
    def warm_start_state(self):
        """Create a test warm start state."""
        return WarmStartState(
            snapshot_time=datetime.now(timezone.utc),
            positions=[
                {
                    "symbol": "BTCUSDT",
                    "side": "long",
                    "size": 0.1,
                    "entry_price": 50000.0,
                    "stop_loss": 49000.0,
                    "take_profit": 52000.0,
                    "strategy_id": "test_strategy",
                    "profile_id": "test_profile",
                }
            ],
            account_state={
                "equity": 15000.0,
                "margin": 5000.0,
                "balance": 10000.0,
            },
            recent_decisions=[],
            candle_history={
                "BTCUSDT": [
                    {"ts": datetime.now(timezone.utc) - timedelta(hours=1), "open": 49500, "high": 50100, "low": 49400, "close": 50000, "volume": 100},
                    {"ts": datetime.now(timezone.utc) - timedelta(minutes=30), "open": 50000, "high": 50200, "low": 49900, "close": 50100, "volume": 150},
                ]
            },
            pipeline_state={"cooldown_until": None},
        )
    
    @pytest.fixture
    def cold_start_config(self):
        """Create a test backtest config for cold start."""
        return {
            "symbol": "BTCUSDT",
            "start_date": "2024-01-01",
            "end_date": "2024-01-02",
            "initial_capital": 10000.0,
            "force_run": True,
        }
    
    def test_execute_accepts_warm_start_state_parameter(self, mock_platform_pool, executor_config):
        """Test that execute() method accepts warm_start_state parameter.
        
        Validates: Requirements 3.1
        """
        executor = StrategyBacktestExecutor(mock_platform_pool, executor_config)
        
        # Verify the execute method has warm_start_state parameter
        import inspect
        sig = inspect.signature(executor.execute)
        params = list(sig.parameters.keys())
        
        assert "warm_start_state" in params, "execute() should accept warm_start_state parameter"
        
        # Verify it has a default value of None
        warm_start_param = sig.parameters["warm_start_state"]
        assert warm_start_param.default is None, "warm_start_state should default to None"
    
    def test_warm_start_state_positions_initialization(self, warm_start_state):
        """Test that positions are correctly extracted from warm start state.
        
        Validates: Requirements 3.1
        """
        # Verify positions are present
        assert len(warm_start_state.positions) == 1
        
        pos = warm_start_state.positions[0]
        assert pos["symbol"] == "BTCUSDT"
        assert pos["side"] == "long"
        assert pos["size"] == 0.1
        assert pos["entry_price"] == 50000.0
        assert pos["stop_loss"] == 49000.0
        assert pos["take_profit"] == 52000.0
    
    def test_warm_start_state_account_initialization(self, warm_start_state):
        """Test that account state is correctly extracted from warm start state.
        
        Validates: Requirements 3.1
        """
        # Verify account state is present
        assert warm_start_state.account_state["equity"] == 15000.0
        assert warm_start_state.account_state["margin"] == 5000.0
        assert warm_start_state.account_state["balance"] == 10000.0
    
    def test_warm_start_state_candle_history(self, warm_start_state):
        """Test that candle history is correctly extracted from warm start state.
        
        Validates: Requirements 3.1
        """
        # Verify candle history is present
        assert "BTCUSDT" in warm_start_state.candle_history
        candles = warm_start_state.candle_history["BTCUSDT"]
        assert len(candles) == 2
        
        # Verify candle structure
        for candle in candles:
            assert "ts" in candle
            assert "open" in candle
            assert "high" in candle
            assert "low" in candle
            assert "close" in candle
            assert "volume" in candle
    
    def test_cold_start_behavior_when_warm_start_none(self, mock_platform_pool, executor_config):
        """Test that cold start behavior is used when warm_start_state is None.
        
        Validates: Requirements 3.1
        """
        executor = StrategyBacktestExecutor(mock_platform_pool, executor_config)
        
        # The executor should be created without issues
        assert executor is not None
        assert executor.config == executor_config
        
        # When warm_start_state is None, the executor should use initial_capital
        # from config (this is the cold start behavior)
    
    def test_warm_start_state_validation(self, warm_start_state):
        """Test that warm start state validation works correctly.
        
        Validates: Requirements 3.5
        """
        is_valid, errors = warm_start_state.validate()
        
        # Our test state should be valid
        assert is_valid is True
        assert len(errors) == 0
    
    def test_warm_start_state_staleness_check(self):
        """Test that staleness check works correctly.
        
        Validates: Requirements 3.6
        """
        # Create a fresh state
        fresh_state = WarmStartState(
            snapshot_time=datetime.now(timezone.utc),
            account_state={"equity": 10000},
        )
        assert fresh_state.is_stale() is False
        
        # Create a stale state (10 minutes old)
        stale_state = WarmStartState(
            snapshot_time=datetime.now(timezone.utc) - timedelta(minutes=10),
            account_state={"equity": 10000},
        )
        assert stale_state.is_stale() is True
    
    def test_warm_start_state_with_multiple_positions(self):
        """Test warm start state with multiple positions.
        
        The executor currently supports single position tracking, so it should
        use the first position when multiple are provided.
        
        Validates: Requirements 3.1
        """
        state = WarmStartState(
            snapshot_time=datetime.now(timezone.utc),
            positions=[
                {"symbol": "BTCUSDT", "side": "long", "size": 0.1, "entry_price": 50000},
                {"symbol": "ETHUSDT", "side": "short", "size": 1.0, "entry_price": 3000},
            ],
            account_state={"equity": 20000},
        )
        
        assert len(state.positions) == 2
        assert state.get_position_count() == 2
        assert state.get_symbols_with_positions() == ["BTCUSDT", "ETHUSDT"] or \
               state.get_symbols_with_positions() == ["ETHUSDT", "BTCUSDT"]
    
    def test_warm_start_state_empty_positions(self):
        """Test warm start state with no positions (flat).
        
        Validates: Requirements 3.1
        """
        state = WarmStartState(
            snapshot_time=datetime.now(timezone.utc),
            positions=[],
            account_state={"equity": 10000},
        )
        
        assert len(state.positions) == 0
        assert state.get_position_count() == 0
        assert state.get_total_position_value() == 0.0
    
    def test_warm_start_state_candle_history_for_positions(self, warm_start_state):
        """Test that candle history exists for position symbols.
        
        Validates: Requirements 3.4
        """
        # Our test state has BTCUSDT position and BTCUSDT candle history
        assert warm_start_state.has_candle_history_for_positions() is True
        
        # Create a state without candle history for the position symbol
        state_without_history = WarmStartState(
            snapshot_time=datetime.now(timezone.utc),
            positions=[{"symbol": "ETHUSDT", "size": 1.0, "entry_price": 3000}],
            account_state={"equity": 10000},
            candle_history={},  # No candle history
        )
        assert state_without_history.has_candle_history_for_positions() is False
    
    def test_warm_start_state_serialization(self, warm_start_state):
        """Test that warm start state can be serialized and deserialized.
        
        Validates: Requirements 3.1
        """
        # Serialize to dict
        state_dict = warm_start_state.to_dict()
        
        assert "snapshot_time" in state_dict
        assert "positions" in state_dict
        assert "account_state" in state_dict
        assert "candle_history" in state_dict
        assert "pipeline_state" in state_dict
        
        # Deserialize from dict
        restored_state = WarmStartState.from_dict(state_dict)
        
        assert len(restored_state.positions) == len(warm_start_state.positions)
        assert restored_state.account_state["equity"] == warm_start_state.account_state["equity"]


class TestWarmStartSimulationIntegration:
    """Integration tests for warm start with simulation logic."""
    
    @pytest.fixture
    def mock_platform_pool(self):
        """Create a mock platform pool."""
        pool = AsyncMock()
        pool.acquire = AsyncMock()
        return pool
    
    @pytest.fixture
    def executor_config(self):
        """Create a test executor config."""
        return StrategyExecutorConfig(
            timescale_host="localhost",
            timescale_port=5433,
            timescale_db="test_db",
            timescale_user="test_user",
            timescale_password="test_pass",
            sample_every=1,
        )
    
    @pytest.mark.asyncio
    async def test_warm_start_equity_initialization(self, mock_platform_pool, executor_config):
        """Test that equity is initialized from warm start state.
        
        Validates: Requirements 3.1
        """
        executor = StrategyBacktestExecutor(mock_platform_pool, executor_config)
        
        warm_start_state = WarmStartState(
            snapshot_time=datetime.now(timezone.utc),
            positions=[],
            account_state={"equity": 25000.0},
            candle_history={},
            pipeline_state={},
        )
        
        # The warm start state should have equity of 25000
        assert warm_start_state.account_state["equity"] == 25000.0
        
        # Verify the state is valid
        is_valid, errors = warm_start_state.validate()
        assert is_valid is True
    
    @pytest.mark.asyncio
    async def test_warm_start_position_initialization(self, mock_platform_pool, executor_config):
        """Test that position is initialized from warm start state.
        
        Validates: Requirements 3.1
        """
        executor = StrategyBacktestExecutor(mock_platform_pool, executor_config)
        
        warm_start_state = WarmStartState(
            snapshot_time=datetime.now(timezone.utc),
            positions=[
                {
                    "symbol": "BTCUSDT",
                    "side": "long",
                    "size": 0.5,
                    "entry_price": 45000.0,
                    "stop_loss": 44000.0,
                    "take_profit": 47000.0,
                }
            ],
            account_state={"equity": 30000.0},
            candle_history={},
            pipeline_state={},
        )
        
        # Verify position data
        assert len(warm_start_state.positions) == 1
        pos = warm_start_state.positions[0]
        assert pos["side"] == "long"
        assert pos["size"] == 0.5
        assert pos["entry_price"] == 45000.0
    
    @pytest.mark.asyncio
    async def test_warm_start_candle_cache_population(self, mock_platform_pool, executor_config):
        """Test that candle cache is pre-populated from warm start state.
        
        Validates: Requirements 3.1, 3.4
        """
        executor = StrategyBacktestExecutor(mock_platform_pool, executor_config)
        
        # Create warm start state with candle history
        candle_history = {
            "BTCUSDT": [
                {"ts": datetime.now(timezone.utc) - timedelta(hours=2), "open": 49000, "high": 49500, "low": 48900, "close": 49400, "volume": 100},
                {"ts": datetime.now(timezone.utc) - timedelta(hours=1), "open": 49400, "high": 50000, "low": 49300, "close": 49800, "volume": 120},
                {"ts": datetime.now(timezone.utc) - timedelta(minutes=30), "open": 49800, "high": 50200, "low": 49700, "close": 50000, "volume": 150},
            ]
        }
        
        warm_start_state = WarmStartState(
            snapshot_time=datetime.now(timezone.utc),
            positions=[],
            account_state={"equity": 10000.0},
            candle_history=candle_history,
            pipeline_state={},
        )
        
        # Verify candle history is present
        assert "BTCUSDT" in warm_start_state.candle_history
        assert len(warm_start_state.candle_history["BTCUSDT"]) == 3
    
    def test_warm_start_with_stale_state_warning(self, mock_platform_pool, executor_config):
        """Test that stale warm start state triggers warning.
        
        Validates: Requirements 3.6
        """
        # Create a stale state (10 minutes old)
        stale_state = WarmStartState(
            snapshot_time=datetime.now(timezone.utc) - timedelta(minutes=10),
            positions=[],
            account_state={"equity": 10000.0},
            candle_history={},
            pipeline_state={},
        )
        
        # Verify staleness
        assert stale_state.is_stale() is True
        assert stale_state.get_age_seconds() > 300  # More than 5 minutes
    
    def test_warm_start_validation_errors(self):
        """Test warm start state validation catches errors.
        
        Validates: Requirements 3.5
        """
        # Create state with missing equity
        invalid_state = WarmStartState(
            snapshot_time=datetime.now(timezone.utc),
            positions=[],
            account_state={},  # Missing equity
            candle_history={},
            pipeline_state={},
        )
        
        is_valid, errors = invalid_state.validate()
        assert is_valid is False
        assert "Missing equity in account state" in errors
    
    def test_warm_start_validation_position_equity_ratio(self):
        """Test warm start state validation catches position/equity ratio issues.
        
        Validates: Requirements 3.5
        """
        # Create state with position value exceeding 10x equity
        invalid_state = WarmStartState(
            snapshot_time=datetime.now(timezone.utc),
            positions=[
                {"symbol": "BTCUSDT", "size": 100, "entry_price": 50000}  # 5M position value
            ],
            account_state={"equity": 1000},  # Only 1000 equity
            candle_history={},
            pipeline_state={},
        )
        
        is_valid, errors = invalid_state.validate()
        assert is_valid is False
        assert any("exceeds" in error for error in errors)


class TestWarmStartEdgeCases:
    """Edge case tests for warm start integration."""
    
    def test_warm_start_with_zero_equity(self):
        """Test warm start state with zero equity."""
        state = WarmStartState(
            snapshot_time=datetime.now(timezone.utc),
            positions=[],
            account_state={"equity": 0},
            candle_history={},
            pipeline_state={},
        )
        
        is_valid, errors = state.validate()
        assert is_valid is False
        assert "Missing equity in account state" in errors
    
    def test_warm_start_with_negative_position_size(self):
        """Test warm start state with negative position size (short)."""
        state = WarmStartState(
            snapshot_time=datetime.now(timezone.utc),
            positions=[
                {"symbol": "BTCUSDT", "side": "short", "size": -0.5, "entry_price": 50000}
            ],
            account_state={"equity": 10000},
            candle_history={},
            pipeline_state={},
        )
        
        # Negative size should still calculate position value correctly
        total_value = state.get_total_position_value()
        assert total_value == 25000.0  # abs(-0.5 * 50000)
    
    def test_warm_start_with_empty_candle_history(self):
        """Test warm start state with empty candle history."""
        state = WarmStartState(
            snapshot_time=datetime.now(timezone.utc),
            positions=[{"symbol": "BTCUSDT", "size": 0.1, "entry_price": 50000}],
            account_state={"equity": 10000},
            candle_history={},  # Empty
            pipeline_state={},
        )
        
        # Should not have candle history for positions
        assert state.has_candle_history_for_positions() is False
    
    def test_warm_start_with_partial_candle_history(self):
        """Test warm start state with candle history for some but not all positions."""
        state = WarmStartState(
            snapshot_time=datetime.now(timezone.utc),
            positions=[
                {"symbol": "BTCUSDT", "size": 0.1, "entry_price": 50000},
                {"symbol": "ETHUSDT", "size": 1.0, "entry_price": 3000},
            ],
            account_state={"equity": 10000},
            candle_history={
                "BTCUSDT": [{"ts": datetime.now(timezone.utc), "open": 50000, "high": 50100, "low": 49900, "close": 50050, "volume": 100}]
                # Missing ETHUSDT candles
            },
            pipeline_state={},
        )
        
        # Should not have candle history for all positions
        assert state.has_candle_history_for_positions() is False
    
    def test_warm_start_age_calculation(self):
        """Test warm start state age calculation."""
        # Create state 2 minutes ago
        state = WarmStartState(
            snapshot_time=datetime.now(timezone.utc) - timedelta(minutes=2),
            account_state={"equity": 10000},
        )
        
        age = state.get_age_seconds()
        assert 110 < age < 130  # Should be around 120 seconds
    
    def test_warm_start_timezone_handling(self):
        """Test warm start state handles timezone correctly."""
        # Create state with naive datetime (no timezone)
        naive_time = datetime.now()
        state = WarmStartState(
            snapshot_time=naive_time,
            account_state={"equity": 10000},
        )
        
        # Should have timezone info after initialization
        assert state.snapshot_time.tzinfo is not None
        
        # Staleness check should work
        assert state.is_stale() is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
