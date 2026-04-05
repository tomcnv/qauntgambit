"""Unit tests for ConfigurationRegistry integration with StrategyBacktestExecutor.

Feature: trading-pipeline-integration
Task: 15.3 Wire ConfigurationRegistry into backtest executor

Tests verify:
1. StrategyBacktestExecutor accepts config_registry parameter
2. When config_registry is provided, config is loaded from registry
3. Config version is stored with backtest results
4. Parity checking is enforced when require_parity=True
5. ConfigurationError is raised when critical parameters differ

Requirements: 1.1 - THE System SHALL maintain a single source of truth for all trading
              configuration parameters
              1.2 - WHEN a backtest is initiated THEN the System SHALL automatically load
              the current live configuration unless explicitly overridden
              1.5 - WHEN critical configuration parameters differ THEN the System SHALL
              require explicit acknowledgment before proceeding
"""

import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from typing import Any, Dict, Optional

from quantgambit.backtesting.strategy_executor import (
    StrategyBacktestExecutor,
    StrategyExecutorConfig,
)
from quantgambit.integration.config_registry import (
    ConfigurationRegistry,
    ConfigurationError,
)
from quantgambit.integration.config_version import ConfigVersion
from quantgambit.integration.config_diff import ConfigDiff


class TestConfigRegistryIntegration:
    """Tests for ConfigurationRegistry integration with StrategyBacktestExecutor."""
    
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
    def mock_config_registry(self):
        """Create a mock ConfigurationRegistry."""
        registry = AsyncMock(spec=ConfigurationRegistry)
        
        # Create a default live config
        live_config = ConfigVersion(
            version_id="live_abc12345",
            created_at=datetime.now(timezone.utc),
            created_by="live",
            config_hash="hash123",
            parameters={
                "slippage_bps": 5.0,
                "maker_fee_bps": 2.0,
                "taker_fee_bps": 5.5,
                "max_spread_bps": 15.0,
            },
        )
        
        # Default behavior: return live config with no diff
        registry.get_config_for_backtest = AsyncMock(return_value=(live_config, None))
        
        return registry
    
    def test_executor_accepts_config_registry_parameter(self, mock_platform_pool, executor_config):
        """Test that StrategyBacktestExecutor accepts config_registry parameter.
        
        Validates: Requirements 1.1
        """
        # Create executor without config_registry
        executor_no_registry = StrategyBacktestExecutor(mock_platform_pool, executor_config)
        assert executor_no_registry._config_registry is None
        
        # Create executor with config_registry
        mock_registry = MagicMock(spec=ConfigurationRegistry)
        executor_with_registry = StrategyBacktestExecutor(
            mock_platform_pool, executor_config, config_registry=mock_registry
        )
        assert executor_with_registry._config_registry is mock_registry
    
    def test_executor_init_signature_includes_config_registry(self, mock_platform_pool, executor_config):
        """Test that __init__ method has config_registry parameter.
        
        Validates: Requirements 1.1
        """
        import inspect
        sig = inspect.signature(StrategyBacktestExecutor.__init__)
        params = list(sig.parameters.keys())
        
        assert "config_registry" in params, "__init__() should accept config_registry parameter"
        
        # Verify it has a default value of None
        config_registry_param = sig.parameters["config_registry"]
        assert config_registry_param.default is None, "config_registry should default to None"
    
    @pytest.mark.asyncio
    async def test_config_loaded_from_registry_when_provided(
        self, mock_platform_pool, executor_config, mock_config_registry
    ):
        """Test that config is loaded from registry when provided.
        
        Validates: Requirements 1.2
        """
        executor = StrategyBacktestExecutor(
            mock_platform_pool, executor_config, config_registry=mock_config_registry
        )
        
        # Mock the internal methods to avoid actual database calls
        executor._update_status = AsyncMock()
        executor._get_timescale_pool = AsyncMock()
        # Provide at least one event so we get past the "no events" check
        executor._fetch_decision_events = AsyncMock(return_value=[
            {"ts": datetime.now(timezone.utc), "payload": {"snapshot": {"mid_price": 50000}}}
        ])
        executor._fetch_orderbook_events = AsyncMock(return_value={})
        executor._fetch_candle_data = AsyncMock(return_value=[])
        executor.validate_data = AsyncMock(return_value=MagicMock(
            passes_threshold=True,
            threshold_overridden=False,
            errors=[],
            data_quality_grade="A",
            overall_completeness_pct=100.0,
            recommendation="Good",
            total_gaps=0,
            critical_gaps=0,
            warnings=[],
        ))
        executor._run_strategy_simulation = AsyncMock(return_value={
            "metrics": {
                "realized_pnl": 0,
                "total_fees": 0,
                "total_trades": 0,
                "win_rate": 0,
                "max_drawdown_pct": 0,
                "avg_slippage_bps": 0,
                "total_return_pct": 0,
                "profit_factor": 0,
                "avg_trade_pnl": 0,
            },
            "trades": [],
            "equity_curve": [],
            "runtime_quality": {},
        })
        executor._store_results = AsyncMock()
        
        # Execute backtest
        config = {
            "symbol": "BTCUSDT",
            "start_date": "2024-01-01",
            "end_date": "2024-01-02",
            "initial_capital": 10000.0,
            "force_run": True,
        }
        
        result = await executor.execute("test_run", "tenant1", "bot1", config)
        
        # Verify registry was called
        mock_config_registry.get_config_for_backtest.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_config_version_stored_in_results(
        self, mock_platform_pool, executor_config, mock_config_registry
    ):
        """Test that config_version is stored in backtest results.
        
        Validates: Requirements 1.2
        """
        executor = StrategyBacktestExecutor(
            mock_platform_pool, executor_config, config_registry=mock_config_registry
        )
        
        # Mock internal methods
        executor._update_status = AsyncMock()
        executor._get_timescale_pool = AsyncMock()
        executor._fetch_decision_events = AsyncMock(return_value=[
            {"ts": datetime.now(timezone.utc), "payload": {"snapshot": {"mid_price": 50000}}}
        ])
        executor._fetch_orderbook_events = AsyncMock(return_value={})
        executor._fetch_candle_data = AsyncMock(return_value=[])
        executor.validate_data = AsyncMock(return_value=MagicMock(
            passes_threshold=True,
            threshold_overridden=False,
            errors=[],
            data_quality_grade="A",
            overall_completeness_pct=100.0,
            recommendation="Good",
            total_gaps=0,
            critical_gaps=0,
            warnings=[],
        ))
        executor._run_strategy_simulation = AsyncMock(return_value={
            "metrics": {
                "realized_pnl": 0,
                "total_fees": 0,
                "total_trades": 0,
                "win_rate": 0,
                "max_drawdown_pct": 0,
                "avg_slippage_bps": 0,
                "total_return_pct": 0,
                "profit_factor": 0,
                "avg_trade_pnl": 0,
            },
            "trades": [],
            "equity_curve": [],
            "runtime_quality": {},
        })
        executor._store_results = AsyncMock()
        
        # Execute backtest
        config = {
            "symbol": "BTCUSDT",
            "start_date": "2024-01-01",
            "end_date": "2024-01-02",
            "initial_capital": 10000.0,
            "force_run": True,
        }
        
        result = await executor.execute("test_run", "tenant1", "bot1", config)
        
        # Verify config_version is in results
        assert "config_version" in result
        assert result["config_version"] == "live_abc12345"
    
    @pytest.mark.asyncio
    async def test_parity_check_raises_error_on_critical_diff(
        self, mock_platform_pool, executor_config
    ):
        """Test that ConfigurationError is raised when critical parameters differ.
        
        Validates: Requirements 1.5
        """
        # Create a mock registry that raises ConfigurationError
        mock_registry = AsyncMock(spec=ConfigurationRegistry)
        mock_registry.get_config_for_backtest = AsyncMock(
            side_effect=ConfigurationError(
                "Critical configuration differences detected",
                critical_diffs=[("slippage_bps", 5.0, 10.0)],
            )
        )
        
        executor = StrategyBacktestExecutor(
            mock_platform_pool, executor_config, config_registry=mock_registry
        )
        
        # Mock internal methods
        executor._update_status = AsyncMock()
        executor._get_timescale_pool = AsyncMock()
        executor._fetch_decision_events = AsyncMock(return_value=[
            {"ts": datetime.now(timezone.utc), "payload": {"snapshot": {"mid_price": 50000}}}
        ])
        executor._fetch_orderbook_events = AsyncMock(return_value={})
        executor._fetch_candle_data = AsyncMock(return_value=[])
        executor.validate_data = AsyncMock(return_value=MagicMock(
            passes_threshold=True,
            threshold_overridden=False,
            errors=[],
            data_quality_grade="A",
            overall_completeness_pct=100.0,
            recommendation="Good",
        ))
        
        # Execute backtest with require_parity=True (default)
        config = {
            "symbol": "BTCUSDT",
            "start_date": "2024-01-01",
            "end_date": "2024-01-02",
            "initial_capital": 10000.0,
            "force_run": True,
            "require_parity": True,
        }
        
        # Should fail with error about parity check
        result = await executor.execute("test_run", "tenant1", "bot1", config)
        
        assert result["status"] == "failed"
        assert "parity" in result["error"].lower() or "configuration" in result["error"].lower()
    
    @pytest.mark.asyncio
    async def test_parity_check_bypassed_when_require_parity_false(
        self, mock_platform_pool, executor_config
    ):
        """Test that parity check is bypassed when require_parity=False.
        
        Validates: Requirements 1.5
        """
        # Create a mock registry that returns config with diff
        mock_registry = AsyncMock(spec=ConfigurationRegistry)
        
        live_config = ConfigVersion(
            version_id="live_abc12345",
            created_at=datetime.now(timezone.utc),
            created_by="live",
            config_hash="hash123",
            parameters={"slippage_bps": 5.0},
        )
        
        config_diff = MagicMock(spec=ConfigDiff)
        config_diff.has_critical_diffs = False
        config_diff.has_warning_diffs = True
        config_diff.has_diffs = True
        config_diff.critical_diffs = []
        config_diff.warning_diffs = [("slippage_bps", 5.0, 10.0)]
        config_diff.info_diffs = []
        
        mock_registry.get_config_for_backtest = AsyncMock(return_value=(live_config, config_diff))
        
        executor = StrategyBacktestExecutor(
            mock_platform_pool, executor_config, config_registry=mock_registry
        )
        
        # Mock internal methods
        executor._update_status = AsyncMock()
        executor._get_timescale_pool = AsyncMock()
        executor._fetch_decision_events = AsyncMock(return_value=[
            {"ts": datetime.now(timezone.utc), "payload": {"snapshot": {"mid_price": 50000}}}
        ])
        executor._fetch_orderbook_events = AsyncMock(return_value={})
        executor._fetch_candle_data = AsyncMock(return_value=[])
        executor.validate_data = AsyncMock(return_value=MagicMock(
            passes_threshold=True,
            threshold_overridden=False,
            errors=[],
            data_quality_grade="A",
            overall_completeness_pct=100.0,
            recommendation="Good",
            total_gaps=0,
            critical_gaps=0,
            warnings=[],
        ))
        executor._run_strategy_simulation = AsyncMock(return_value={
            "metrics": {
                "realized_pnl": 0,
                "total_fees": 0,
                "total_trades": 0,
                "win_rate": 0,
                "max_drawdown_pct": 0,
                "avg_slippage_bps": 0,
                "total_return_pct": 0,
                "profit_factor": 0,
                "avg_trade_pnl": 0,
            },
            "trades": [],
            "equity_curve": [],
            "runtime_quality": {},
        })
        executor._store_results = AsyncMock()
        
        # Execute backtest with require_parity=False
        config = {
            "symbol": "BTCUSDT",
            "start_date": "2024-01-01",
            "end_date": "2024-01-02",
            "initial_capital": 10000.0,
            "force_run": True,
            "require_parity": False,
        }
        
        result = await executor.execute("test_run", "tenant1", "bot1", config)
        
        # Should succeed despite warning diffs
        assert result["status"] in ["completed", "degraded"]
        assert "config_version" in result
    
    @pytest.mark.asyncio
    async def test_config_diff_stored_in_results(
        self, mock_platform_pool, executor_config
    ):
        """Test that config_diff is stored in backtest results when present.
        
        Validates: Requirements 1.2
        """
        # Create a mock registry that returns config with diff
        mock_registry = AsyncMock(spec=ConfigurationRegistry)
        
        live_config = ConfigVersion(
            version_id="live_abc12345",
            created_at=datetime.now(timezone.utc),
            created_by="live",
            config_hash="hash123",
            parameters={"slippage_bps": 5.0},
        )
        
        config_diff = MagicMock(spec=ConfigDiff)
        config_diff.has_critical_diffs = False
        config_diff.has_warning_diffs = True
        config_diff.has_diffs = True
        config_diff.critical_diffs = []
        config_diff.warning_diffs = [("slippage_bps", 5.0, 10.0)]
        config_diff.info_diffs = [("some_param", "a", "b")]
        
        mock_registry.get_config_for_backtest = AsyncMock(return_value=(live_config, config_diff))
        
        executor = StrategyBacktestExecutor(
            mock_platform_pool, executor_config, config_registry=mock_registry
        )
        
        # Mock internal methods
        executor._update_status = AsyncMock()
        executor._get_timescale_pool = AsyncMock()
        executor._fetch_decision_events = AsyncMock(return_value=[
            {"ts": datetime.now(timezone.utc), "payload": {"snapshot": {"mid_price": 50000}}}
        ])
        executor._fetch_orderbook_events = AsyncMock(return_value={})
        executor._fetch_candle_data = AsyncMock(return_value=[])
        executor.validate_data = AsyncMock(return_value=MagicMock(
            passes_threshold=True,
            threshold_overridden=False,
            errors=[],
            data_quality_grade="A",
            overall_completeness_pct=100.0,
            recommendation="Good",
            total_gaps=0,
            critical_gaps=0,
            warnings=[],
        ))
        executor._run_strategy_simulation = AsyncMock(return_value={
            "metrics": {
                "realized_pnl": 0,
                "total_fees": 0,
                "total_trades": 0,
                "win_rate": 0,
                "max_drawdown_pct": 0,
                "avg_slippage_bps": 0,
                "total_return_pct": 0,
                "profit_factor": 0,
                "avg_trade_pnl": 0,
            },
            "trades": [],
            "equity_curve": [],
            "runtime_quality": {},
        })
        executor._store_results = AsyncMock()
        
        # Execute backtest
        config = {
            "symbol": "BTCUSDT",
            "start_date": "2024-01-01",
            "end_date": "2024-01-02",
            "initial_capital": 10000.0,
            "force_run": True,
            "require_parity": False,
        }
        
        result = await executor.execute("test_run", "tenant1", "bot1", config)
        
        # Verify config_diff is in results
        assert "config_diff" in result
        assert result["config_diff"]["has_critical_diffs"] is False
        assert result["config_diff"]["has_warning_diffs"] is True
        assert result["config_diff"]["warning_count"] == 1
        assert result["config_diff"]["info_count"] == 1
    
    @pytest.mark.asyncio
    async def test_no_registry_uses_config_directly(
        self, mock_platform_pool, executor_config
    ):
        """Test that when no registry is provided, config is used directly.
        
        Validates: Requirements 1.1
        """
        # Create executor without config_registry
        executor = StrategyBacktestExecutor(mock_platform_pool, executor_config)
        
        # Mock internal methods
        executor._update_status = AsyncMock()
        executor._get_timescale_pool = AsyncMock()
        executor._fetch_decision_events = AsyncMock(return_value=[
            {"ts": datetime.now(timezone.utc), "payload": {"snapshot": {"mid_price": 50000}}}
        ])
        executor._fetch_orderbook_events = AsyncMock(return_value={})
        executor._fetch_candle_data = AsyncMock(return_value=[])
        executor.validate_data = AsyncMock(return_value=MagicMock(
            passes_threshold=True,
            threshold_overridden=False,
            errors=[],
            data_quality_grade="A",
            overall_completeness_pct=100.0,
            recommendation="Good",
            total_gaps=0,
            critical_gaps=0,
            warnings=[],
        ))
        executor._run_strategy_simulation = AsyncMock(return_value={
            "metrics": {
                "realized_pnl": 0,
                "total_fees": 0,
                "total_trades": 0,
                "win_rate": 0,
                "max_drawdown_pct": 0,
                "avg_slippage_bps": 0,
                "total_return_pct": 0,
                "profit_factor": 0,
                "avg_trade_pnl": 0,
            },
            "trades": [],
            "equity_curve": [],
            "runtime_quality": {},
        })
        executor._store_results = AsyncMock()
        
        # Execute backtest
        config = {
            "symbol": "BTCUSDT",
            "start_date": "2024-01-01",
            "end_date": "2024-01-02",
            "initial_capital": 10000.0,
            "force_run": True,
        }
        
        result = await executor.execute("test_run", "tenant1", "bot1", config)
        
        # Should succeed without config_version
        assert result["status"] in ["completed", "degraded"]
        assert "config_version" not in result


class TestConfigRegistryOverrideParams:
    """Tests for override_params handling with ConfigurationRegistry."""
    
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
    async def test_override_params_passed_to_registry(
        self, mock_platform_pool, executor_config
    ):
        """Test that override_params from config are passed to registry.
        
        Validates: Requirements 1.2
        """
        mock_registry = AsyncMock(spec=ConfigurationRegistry)
        
        live_config = ConfigVersion(
            version_id="backtest_xyz789",
            created_at=datetime.now(timezone.utc),
            created_by="backtest",
            config_hash="hash456",
            parameters={"slippage_bps": 10.0},  # Overridden value
        )
        
        mock_registry.get_config_for_backtest = AsyncMock(return_value=(live_config, None))
        
        executor = StrategyBacktestExecutor(
            mock_platform_pool, executor_config, config_registry=mock_registry
        )
        
        # Mock internal methods
        executor._update_status = AsyncMock()
        executor._get_timescale_pool = AsyncMock()
        # Provide at least one event so we get past the "no events" check
        executor._fetch_decision_events = AsyncMock(return_value=[
            {"ts": datetime.now(timezone.utc), "payload": {"snapshot": {"mid_price": 50000}}}
        ])
        executor._fetch_orderbook_events = AsyncMock(return_value={})
        executor._fetch_candle_data = AsyncMock(return_value=[])
        executor.validate_data = AsyncMock(return_value=MagicMock(
            passes_threshold=True,
            threshold_overridden=False,
            errors=[],
            data_quality_grade="A",
            overall_completeness_pct=100.0,
            recommendation="Good",
            total_gaps=0,
            critical_gaps=0,
            warnings=[],
        ))
        executor._run_strategy_simulation = AsyncMock(return_value={
            "metrics": {
                "realized_pnl": 0,
                "total_fees": 0,
                "total_trades": 0,
                "win_rate": 0,
                "max_drawdown_pct": 0,
                "avg_slippage_bps": 0,
                "total_return_pct": 0,
                "profit_factor": 0,
                "avg_trade_pnl": 0,
            },
            "trades": [],
            "equity_curve": [],
            "runtime_quality": {},
        })
        executor._store_results = AsyncMock()
        
        # Execute backtest with override_params
        config = {
            "symbol": "BTCUSDT",
            "start_date": "2024-01-01",
            "end_date": "2024-01-02",
            "initial_capital": 10000.0,
            "force_run": True,
            "override_params": {"slippage_bps": 10.0},
            "require_parity": False,
        }
        
        result = await executor.execute("test_run", "tenant1", "bot1", config)
        
        # Verify registry was called with override_params
        mock_registry.get_config_for_backtest.assert_called_once_with(
            override_params={"slippage_bps": 10.0},
            require_parity=False,
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
