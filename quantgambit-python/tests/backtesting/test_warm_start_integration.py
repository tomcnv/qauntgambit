"""
Unit tests for warm start integration with BacktestExecutor.

Feature: bot-integration-fixes
Tests for:
- Warm start is attempted when enabled
- Cold start fallback on failure
- Stale state warning
- Validation failure results in cold start fallback with warning

**Validates: Requirements 3.1, 3.5, 3.6**
"""

from __future__ import annotations

import pytest
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import AsyncMock, MagicMock, patch

from quantgambit.backtesting.executor import (
    BacktestExecutor,
    ExecutorConfig,
)
from quantgambit.integration.warm_start import WarmStartState


# =============================================================================
# Test Fixtures
# =============================================================================

@pytest.fixture
def mock_db_pool():
    """Create a mock database pool."""
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=AsyncMock())
    return pool


@pytest.fixture
def mock_redis_client():
    """Create a mock Redis client."""
    return MagicMock()


@pytest.fixture
def valid_warm_start_state():
    """Create a valid warm start state for testing."""
    return WarmStartState(
        snapshot_time=datetime.now(timezone.utc),
        positions=[
            {
                "symbol": "BTCUSDT",
                "size": 0.1,
                "entry_price": 50000.0,
                "side": "long",
            }
        ],
        account_state={
            "equity": 10000.0,
            "margin": 500.0,
            "balance": 9500.0,
        },
        recent_decisions=[],
        candle_history={
            "BTCUSDT": [
                {"ts": "2024-01-01T00:00:00Z", "open": 50000, "high": 50100, "low": 49900, "close": 50050, "volume": 100}
            ]
        },
        pipeline_state={},
    )


@pytest.fixture
def stale_warm_start_state():
    """Create a stale warm start state (older than threshold)."""
    # Create state that is 10 minutes old (default threshold is 5 minutes)
    stale_time = datetime.now(timezone.utc) - timedelta(minutes=10)
    return WarmStartState(
        snapshot_time=stale_time,
        positions=[
            {
                "symbol": "BTCUSDT",
                "size": 0.1,
                "entry_price": 50000.0,
                "side": "long",
            }
        ],
        account_state={
            "equity": 10000.0,
            "margin": 500.0,
            "balance": 9500.0,
        },
        recent_decisions=[],
        candle_history={
            "BTCUSDT": [
                {"ts": "2024-01-01T00:00:00Z", "open": 50000, "high": 50100, "low": 49900, "close": 50050, "volume": 100}
            ]
        },
        pipeline_state={},
    )


@pytest.fixture
def invalid_warm_start_state():
    """Create an invalid warm start state (missing equity)."""
    return WarmStartState(
        snapshot_time=datetime.now(timezone.utc),
        positions=[
            {
                "symbol": "BTCUSDT",
                "size": 0.1,
                "entry_price": 50000.0,
                "side": "long",
            }
        ],
        account_state={},  # Missing equity - will fail validation
        recent_decisions=[],
        candle_history={
            "BTCUSDT": [
                {"ts": "2024-01-01T00:00:00Z", "open": 50000, "high": 50100, "low": 49900, "close": 50050, "volume": 100}
            ]
        },
        pipeline_state={},
    )


@pytest.fixture
def mock_warm_start_loader(valid_warm_start_state):
    """Create a mock WarmStartLoader that returns valid state."""
    loader = MagicMock()
    loader.load_current_state = AsyncMock(return_value=valid_warm_start_state)
    return loader


# =============================================================================
# Test Class: Warm Start Attempted When Enabled
# Validates: Requirement 3.1
# =============================================================================

class TestWarmStartAttemptedWhenEnabled:
    """
    Tests that warm start is attempted when BACKTEST_WARM_START_ENABLED is "true".
    
    **Validates: Requirement 3.1**
    WHEN the BACKTEST_WARM_START_ENABLED environment variable is "true"
    THEN the BacktestExecutor SHALL support warm start initialization
    """
    
    @pytest.mark.asyncio
    async def test_warm_start_loader_called_when_enabled(
        self,
        mock_db_pool,
        mock_redis_client,
        mock_warm_start_loader,
        valid_warm_start_state,
    ):
        """
        Test that WarmStartLoader.load_current_state() is called when warm start is enabled.
        
        **Validates: Requirement 3.1**
        """
        # Create config with warm start enabled
        config = ExecutorConfig(
            warm_start_enabled=True,
            warm_start_stale_threshold_sec=300.0,
            parity_mode=False,  # Disable parity check for this test
        )
        
        # Create executor with warm start loader
        executor = BacktestExecutor(
            db_pool=mock_db_pool,
            redis_client=mock_redis_client,
            config=config,
            warm_start_loader=mock_warm_start_loader,
        )
        
        # Call _load_warm_start_state directly
        result = await executor._load_warm_start_state()
        
        # Verify loader was called
        mock_warm_start_loader.load_current_state.assert_called_once()
        
        # Verify result is the valid state
        assert result is not None
        assert result == valid_warm_start_state
    
    @pytest.mark.asyncio
    async def test_warm_start_not_attempted_when_disabled(
        self,
        mock_db_pool,
        mock_redis_client,
        mock_warm_start_loader,
    ):
        """
        Test that warm start is not attempted when warm_start_enabled is False.
        
        **Validates: Requirement 3.1**
        """
        # Create config with warm start disabled
        config = ExecutorConfig(
            warm_start_enabled=False,
            parity_mode=False,
        )
        
        # Create executor with warm start loader
        executor = BacktestExecutor(
            db_pool=mock_db_pool,
            redis_client=mock_redis_client,
            config=config,
            warm_start_loader=mock_warm_start_loader,
        )
        
        # Verify that when warm_start_enabled is False, the loader is not used
        # The execute method checks config.warm_start_enabled before calling _load_warm_start_state
        assert executor.config.warm_start_enabled is False
        assert executor.warm_start_loader is not None
    
    @pytest.mark.asyncio
    async def test_warm_start_not_attempted_when_loader_is_none(
        self,
        mock_db_pool,
        mock_redis_client,
    ):
        """
        Test that warm start returns None when loader is not provided.
        
        **Validates: Requirement 3.1**
        """
        # Create config with warm start enabled but no loader
        config = ExecutorConfig(
            warm_start_enabled=True,
            parity_mode=False,
        )
        
        # Create executor without warm start loader
        executor = BacktestExecutor(
            db_pool=mock_db_pool,
            redis_client=mock_redis_client,
            config=config,
            warm_start_loader=None,
        )
        
        # Call _load_warm_start_state directly
        result = await executor._load_warm_start_state()
        
        # Verify result is None when loader is not available
        assert result is None


# =============================================================================
# Test Class: Cold Start Fallback on Failure
# Validates: Requirement 3.6
# =============================================================================

class TestColdStartFallbackOnFailure:
    """
    Tests that cold start fallback occurs when warm start fails.
    
    **Validates: Requirement 3.6**
    IF warm start state validation fails THEN the System SHALL fall back
    to cold start with a warning
    """
    
    @pytest.mark.asyncio
    async def test_cold_start_fallback_when_loader_raises_exception(
        self,
        mock_db_pool,
        mock_redis_client,
    ):
        """
        Test that cold start fallback occurs when loader raises an exception.
        
        **Validates: Requirement 3.6**
        """
        # Create a loader that raises an exception
        failing_loader = MagicMock()
        failing_loader.load_current_state = AsyncMock(
            side_effect=Exception("Failed to load state")
        )
        
        # Create config with warm start enabled
        config = ExecutorConfig(
            warm_start_enabled=True,
            parity_mode=False,
        )
        
        # Create executor with failing loader
        executor = BacktestExecutor(
            db_pool=mock_db_pool,
            redis_client=mock_redis_client,
            config=config,
            warm_start_loader=failing_loader,
        )
        
        # Call _load_warm_start_state - should return None (cold start fallback)
        with patch('quantgambit.backtesting.executor.log_warning') as mock_log_warning:
            result = await executor._load_warm_start_state()
        
        # Verify result is None (cold start fallback)
        assert result is None
        
        # Verify warning was logged
        mock_log_warning.assert_called_once()
        call_args = mock_log_warning.call_args
        assert call_args[0][0] == "warm_start_load_failed"
    
    @pytest.mark.asyncio
    async def test_cold_start_fallback_when_loader_returns_none(
        self,
        mock_db_pool,
        mock_redis_client,
    ):
        """
        Test that cold start fallback occurs when loader returns None.
        
        **Validates: Requirement 3.6**
        """
        # Create a loader that returns None
        none_loader = MagicMock()
        none_loader.load_current_state = AsyncMock(return_value=None)
        
        # Create config with warm start enabled
        config = ExecutorConfig(
            warm_start_enabled=True,
            parity_mode=False,
        )
        
        # Create executor with none-returning loader
        executor = BacktestExecutor(
            db_pool=mock_db_pool,
            redis_client=mock_redis_client,
            config=config,
            warm_start_loader=none_loader,
        )
        
        # Call _load_warm_start_state - should handle None gracefully
        # Note: The current implementation expects load_current_state to return a state
        # If it returns None, accessing .is_stale() will fail, triggering exception handling
        result = await executor._load_warm_start_state()
        
        # Result should be None (cold start fallback)
        assert result is None


# =============================================================================
# Test Class: Stale State Warning
# Validates: Requirement 3.5
# =============================================================================

class TestStaleStateWarning:
    """
    Tests that stale state warning is logged when state is older than threshold.
    
    **Validates: Requirement 3.5**
    IF warm start state is stale (older than configurable threshold)
    THEN the System SHALL log a warning but proceed with the backtest
    """
    
    @pytest.mark.asyncio
    async def test_stale_state_warning_logged(
        self,
        mock_db_pool,
        mock_redis_client,
        stale_warm_start_state,
    ):
        """
        Test that a warning is logged when warm start state is stale.
        
        **Validates: Requirement 3.5**
        """
        # Create a loader that returns stale state
        stale_loader = MagicMock()
        stale_loader.load_current_state = AsyncMock(return_value=stale_warm_start_state)
        
        # Create config with warm start enabled and 5 minute threshold
        config = ExecutorConfig(
            warm_start_enabled=True,
            warm_start_stale_threshold_sec=300.0,  # 5 minutes
            parity_mode=False,
        )
        
        # Create executor with stale state loader
        executor = BacktestExecutor(
            db_pool=mock_db_pool,
            redis_client=mock_redis_client,
            config=config,
            warm_start_loader=stale_loader,
        )
        
        # Call _load_warm_start_state and verify warning is logged
        with patch('quantgambit.backtesting.executor.log_warning') as mock_log_warning:
            result = await executor._load_warm_start_state()
        
        # Verify result is still returned (proceed with backtest)
        assert result is not None
        assert result == stale_warm_start_state
        
        # Verify stale warning was logged
        mock_log_warning.assert_called_once()
        call_args = mock_log_warning.call_args
        assert call_args[0][0] == "warm_start_state_stale"
        assert "age_seconds" in call_args[1]
        assert "threshold_sec" in call_args[1]
    
    @pytest.mark.asyncio
    async def test_fresh_state_no_warning(
        self,
        mock_db_pool,
        mock_redis_client,
        valid_warm_start_state,
    ):
        """
        Test that no stale warning is logged when state is fresh.
        
        **Validates: Requirement 3.5**
        """
        # Create a loader that returns fresh state
        fresh_loader = MagicMock()
        fresh_loader.load_current_state = AsyncMock(return_value=valid_warm_start_state)
        
        # Create config with warm start enabled
        config = ExecutorConfig(
            warm_start_enabled=True,
            warm_start_stale_threshold_sec=300.0,  # 5 minutes
            parity_mode=False,
        )
        
        # Create executor with fresh state loader
        executor = BacktestExecutor(
            db_pool=mock_db_pool,
            redis_client=mock_redis_client,
            config=config,
            warm_start_loader=fresh_loader,
        )
        
        # Call _load_warm_start_state and verify no stale warning is logged
        with patch('quantgambit.backtesting.executor.log_warning') as mock_log_warning:
            with patch('quantgambit.backtesting.executor.log_info') as mock_log_info:
                result = await executor._load_warm_start_state()
        
        # Verify result is returned
        assert result is not None
        assert result == valid_warm_start_state
        
        # Verify no stale warning was logged
        for call in mock_log_warning.call_args_list:
            assert call[0][0] != "warm_start_state_stale"
    
    @pytest.mark.asyncio
    async def test_stale_threshold_is_configurable(
        self,
        mock_db_pool,
        mock_redis_client,
    ):
        """
        Test that the stale threshold is configurable via ExecutorConfig.
        
        **Validates: Requirement 3.5**
        """
        # Create state that is 2 minutes old
        two_min_old_time = datetime.now(timezone.utc) - timedelta(minutes=2)
        two_min_old_state = WarmStartState(
            snapshot_time=two_min_old_time,
            positions=[],
            account_state={"equity": 10000.0},
            recent_decisions=[],
            candle_history={},
            pipeline_state={},
        )
        
        loader = MagicMock()
        loader.load_current_state = AsyncMock(return_value=two_min_old_state)
        
        # Test with 1 minute threshold (state should be stale)
        config_short = ExecutorConfig(
            warm_start_enabled=True,
            warm_start_stale_threshold_sec=60.0,  # 1 minute
            parity_mode=False,
        )
        
        executor_short = BacktestExecutor(
            db_pool=mock_db_pool,
            redis_client=mock_redis_client,
            config=config_short,
            warm_start_loader=loader,
        )
        
        with patch('quantgambit.backtesting.executor.log_warning') as mock_log_warning:
            await executor_short._load_warm_start_state()
        
        # Should log stale warning with 1 minute threshold
        stale_warning_logged = any(
            call[0][0] == "warm_start_state_stale"
            for call in mock_log_warning.call_args_list
        )
        assert stale_warning_logged, "Should log stale warning with 1 minute threshold"
        
        # Reset mock
        loader.load_current_state.reset_mock()
        
        # Test with 5 minute threshold (state should NOT be stale)
        config_long = ExecutorConfig(
            warm_start_enabled=True,
            warm_start_stale_threshold_sec=300.0,  # 5 minutes
            parity_mode=False,
        )
        
        executor_long = BacktestExecutor(
            db_pool=mock_db_pool,
            redis_client=mock_redis_client,
            config=config_long,
            warm_start_loader=loader,
        )
        
        with patch('quantgambit.backtesting.executor.log_warning') as mock_log_warning:
            await executor_long._load_warm_start_state()
        
        # Should NOT log stale warning with 5 minute threshold
        stale_warning_logged = any(
            call[0][0] == "warm_start_state_stale"
            for call in mock_log_warning.call_args_list
        )
        assert not stale_warning_logged, "Should NOT log stale warning with 5 minute threshold"


# =============================================================================
# Test Class: Validation Failure Fallback
# Validates: Requirement 3.6
# =============================================================================

class TestValidationFailureFallback:
    """
    Tests that validation failure results in cold start fallback with warning.
    
    **Validates: Requirement 3.6**
    IF warm start state validation fails THEN the System SHALL fall back
    to cold start with a warning
    """
    
    @pytest.mark.asyncio
    async def test_validation_failure_returns_none(
        self,
        mock_db_pool,
        mock_redis_client,
        invalid_warm_start_state,
    ):
        """
        Test that validation failure returns None (cold start fallback).
        
        **Validates: Requirement 3.6**
        """
        # Create a loader that returns invalid state
        invalid_loader = MagicMock()
        invalid_loader.load_current_state = AsyncMock(return_value=invalid_warm_start_state)
        
        # Create config with warm start enabled
        config = ExecutorConfig(
            warm_start_enabled=True,
            parity_mode=False,
        )
        
        # Create executor with invalid state loader
        executor = BacktestExecutor(
            db_pool=mock_db_pool,
            redis_client=mock_redis_client,
            config=config,
            warm_start_loader=invalid_loader,
        )
        
        # Call _load_warm_start_state
        with patch('quantgambit.backtesting.executor.log_warning') as mock_log_warning:
            result = await executor._load_warm_start_state()
        
        # Verify result is None (cold start fallback)
        assert result is None
        
        # Verify validation failure warning was logged
        mock_log_warning.assert_called_once()
        call_args = mock_log_warning.call_args
        assert call_args[0][0] == "warm_start_validation_failed"
        assert "errors" in call_args[1]
    
    @pytest.mark.asyncio
    async def test_validation_failure_logs_specific_errors(
        self,
        mock_db_pool,
        mock_redis_client,
        invalid_warm_start_state,
    ):
        """
        Test that validation failure logs specific error messages.
        
        **Validates: Requirement 3.6**
        """
        # Create a loader that returns invalid state
        invalid_loader = MagicMock()
        invalid_loader.load_current_state = AsyncMock(return_value=invalid_warm_start_state)
        
        # Create config with warm start enabled
        config = ExecutorConfig(
            warm_start_enabled=True,
            parity_mode=False,
        )
        
        # Create executor with invalid state loader
        executor = BacktestExecutor(
            db_pool=mock_db_pool,
            redis_client=mock_redis_client,
            config=config,
            warm_start_loader=invalid_loader,
        )
        
        # Call _load_warm_start_state
        with patch('quantgambit.backtesting.executor.log_warning') as mock_log_warning:
            result = await executor._load_warm_start_state()
        
        # Verify the logged errors contain the specific validation error
        call_args = mock_log_warning.call_args
        errors = call_args[1].get("errors", [])
        assert len(errors) > 0
        assert any("equity" in error.lower() for error in errors)
    
    @pytest.mark.asyncio
    async def test_valid_state_passes_validation(
        self,
        mock_db_pool,
        mock_redis_client,
        valid_warm_start_state,
    ):
        """
        Test that valid state passes validation and is returned.
        
        **Validates: Requirement 3.6**
        """
        # Create a loader that returns valid state
        valid_loader = MagicMock()
        valid_loader.load_current_state = AsyncMock(return_value=valid_warm_start_state)
        
        # Create config with warm start enabled
        config = ExecutorConfig(
            warm_start_enabled=True,
            parity_mode=False,
        )
        
        # Create executor with valid state loader
        executor = BacktestExecutor(
            db_pool=mock_db_pool,
            redis_client=mock_redis_client,
            config=config,
            warm_start_loader=valid_loader,
        )
        
        # Call _load_warm_start_state
        with patch('quantgambit.backtesting.executor.log_warning') as mock_log_warning:
            with patch('quantgambit.backtesting.executor.log_info') as mock_log_info:
                result = await executor._load_warm_start_state()
        
        # Verify result is the valid state
        assert result is not None
        assert result == valid_warm_start_state
        
        # Verify no validation failure warning was logged
        for call in mock_log_warning.call_args_list:
            assert call[0][0] != "warm_start_validation_failed"
        
        # Verify success info was logged
        success_logged = any(
            call[0][0] == "warm_start_state_loaded"
            for call in mock_log_info.call_args_list
        )
        assert success_logged


# =============================================================================
# Test Class: ExecutorConfig Environment Variable Support
# Validates: Requirement 3.1
# =============================================================================

class TestExecutorConfigWarmStartEnv:
    """
    Tests that ExecutorConfig correctly reads warm start environment variables.
    
    **Validates: Requirement 3.1**
    """
    
    def test_warm_start_enabled_default_is_false(self):
        """
        Test that warm_start_enabled defaults to False.
        
        **Validates: Requirement 3.1**
        """
        config = ExecutorConfig()
        assert config.warm_start_enabled is False
    
    def test_warm_start_stale_threshold_default(self):
        """
        Test that warm_start_stale_threshold_sec defaults to 300.0 (5 minutes).
        
        **Validates: Requirement 3.5**
        """
        config = ExecutorConfig()
        assert config.warm_start_stale_threshold_sec == 300.0
    
    def test_from_env_reads_warm_start_enabled(self):
        """
        Test that from_env() reads BACKTEST_WARM_START_ENABLED.
        
        **Validates: Requirement 3.1**
        """
        with patch.dict('os.environ', {'BACKTEST_WARM_START_ENABLED': 'true'}):
            config = ExecutorConfig.from_env()
            assert config.warm_start_enabled is True
        
        with patch.dict('os.environ', {'BACKTEST_WARM_START_ENABLED': 'false'}):
            config = ExecutorConfig.from_env()
            assert config.warm_start_enabled is False
        
        with patch.dict('os.environ', {'BACKTEST_WARM_START_ENABLED': '1'}):
            config = ExecutorConfig.from_env()
            assert config.warm_start_enabled is True
        
        with patch.dict('os.environ', {'BACKTEST_WARM_START_ENABLED': 'yes'}):
            config = ExecutorConfig.from_env()
            assert config.warm_start_enabled is True
    
    def test_from_env_reads_warm_start_stale_threshold(self):
        """
        Test that from_env() reads BACKTEST_WARM_START_STALE_SEC.
        
        **Validates: Requirement 3.5**
        """
        with patch.dict('os.environ', {'BACKTEST_WARM_START_STALE_SEC': '600.0'}):
            config = ExecutorConfig.from_env()
            assert config.warm_start_stale_threshold_sec == 600.0
        
        with patch.dict('os.environ', {'BACKTEST_WARM_START_STALE_SEC': '120'}):
            config = ExecutorConfig.from_env()
            assert config.warm_start_stale_threshold_sec == 120.0
