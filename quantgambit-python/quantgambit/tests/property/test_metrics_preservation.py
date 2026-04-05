"""Property tests for metrics preservation in backtest executor.

Property 6: Metrics Preservation
- Test that all existing metrics are present in results
- Test that execute() method signature is unchanged

Requirements: 5.1, 5.3
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone, timedelta
from typing import Dict, Any

from quantgambit.backtesting.strategy_executor import (
    StrategyBacktestExecutor,
    StrategyExecutorConfig,
)


class TestMetricsPresence:
    """Test that all required metrics are present in results."""
    
    def test_calculate_metrics_returns_all_required_fields(self):
        """Test that _calculate_metrics returns all required metric fields."""
        # Create executor with mock pool
        mock_pool = MagicMock()
        executor = StrategyBacktestExecutor(
            platform_pool=mock_pool,
            config=StrategyExecutorConfig(),
        )
        
        # Sample trades
        trades = [
            {
                "ts": "2024-01-01T00:00:00",
                "symbol": "BTCUSDT",
                "side": "long",
                "size": 0.01,
                "entry_price": 50000.0,
                "exit_price": 50100.0,
                "pnl": 10.0,
                "entry_fee": 0.5,
                "exit_fee": 0.5,
                "total_fees": 1.0,
                "entry_slippage_bps": 5.0,
                "exit_slippage_bps": 5.0,
                "strategy_id": "mean_reversion",
                "profile_id": "test_profile",
                "exit_reason": "take_profit",
            },
            {
                "ts": "2024-01-01T01:00:00",
                "symbol": "BTCUSDT",
                "side": "short",
                "size": 0.01,
                "entry_price": 50200.0,
                "exit_price": 50100.0,
                "pnl": 10.0,
                "entry_fee": 0.5,
                "exit_fee": 0.5,
                "total_fees": 1.0,
                "entry_slippage_bps": 5.0,
                "exit_slippage_bps": 5.0,
                "strategy_id": "mean_reversion",
                "profile_id": "test_profile",
                "exit_reason": "take_profit",
            },
        ]
        
        equity_curve = [
            {"ts": "2024-01-01T00:00:00", "equity": 10000.0, "realized_pnl": 0.0, "open_positions": 0},
            {"ts": "2024-01-01T01:00:00", "equity": 10020.0, "realized_pnl": 20.0, "open_positions": 0},
        ]
        
        events = [
            {"ts": datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)},
            {"ts": datetime(2024, 1, 1, 1, 0, 0, tzinfo=timezone.utc)},
        ]
        
        results = executor._calculate_metrics(
            trades=trades,
            equity_curve=equity_curve,
            initial_capital=10000.0,
            final_equity=10020.0,
            max_drawdown=0.0,
            events=events,
        )
        
        # Check all required metrics are present
        metrics = results["metrics"]
        
        required_metrics = [
            "realized_pnl",
            "total_fees",
            "total_trades",
            "win_rate",
            "max_drawdown_pct",
            "avg_slippage_bps",
            "total_return_pct",
            "profit_factor",
            "avg_trade_pnl",
            "sharpe_ratio",
            "sortino_ratio",
            "trades_per_day",
            "fee_drag_pct",
            "slippage_drag_pct",
            "gross_profit",
            "gross_loss",
            "avg_win",
            "avg_loss",
            "largest_win",
            "largest_loss",
            "winning_trades",
            "losing_trades",
        ]
        
        for metric in required_metrics:
            assert metric in metrics, f"Missing required metric: {metric}"
    
    def test_calculate_metrics_handles_empty_trades(self):
        """Test that _calculate_metrics handles empty trade list."""
        mock_pool = MagicMock()
        executor = StrategyBacktestExecutor(
            platform_pool=mock_pool,
            config=StrategyExecutorConfig(),
        )
        
        results = executor._calculate_metrics(
            trades=[],
            equity_curve=[],
            initial_capital=10000.0,
            final_equity=10000.0,
            max_drawdown=0.0,
            events=[],
        )
        
        metrics = results["metrics"]
        
        # Should have all metrics even with no trades
        assert metrics["total_trades"] == 0
        assert metrics["win_rate"] == 0
        assert metrics["realized_pnl"] == 0
        assert metrics["total_return_pct"] == 0
    
    def test_calculate_metrics_handles_all_losing_trades(self):
        """Test that _calculate_metrics handles all losing trades."""
        mock_pool = MagicMock()
        executor = StrategyBacktestExecutor(
            platform_pool=mock_pool,
            config=StrategyExecutorConfig(),
        )
        
        trades = [
            {
                "ts": "2024-01-01T00:00:00",
                "symbol": "BTCUSDT",
                "side": "long",
                "size": 0.01,
                "entry_price": 50000.0,
                "exit_price": 49900.0,
                "pnl": -10.0,
                "entry_fee": 0.5,
                "exit_fee": 0.5,
                "total_fees": 1.0,
                "entry_slippage_bps": 5.0,
                "exit_slippage_bps": 5.0,
                "strategy_id": "mean_reversion",
                "profile_id": "test_profile",
                "exit_reason": "stop_loss",
            },
        ]
        
        events = [{"ts": datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)}]
        
        results = executor._calculate_metrics(
            trades=trades,
            equity_curve=[],
            initial_capital=10000.0,
            final_equity=9990.0,
            max_drawdown=0.001,
            events=events,
        )
        
        metrics = results["metrics"]
        
        assert metrics["win_rate"] == 0
        assert metrics["winning_trades"] == 0
        assert metrics["losing_trades"] == 1
        assert metrics["profit_factor"] == 0  # No profit, so factor is 0


class TestExecuteMethodSignature:
    """Test that execute() method signature is unchanged."""
    
    @pytest.mark.asyncio
    async def test_execute_accepts_required_parameters(self):
        """Test that execute() accepts the required parameters."""
        mock_pool = MagicMock()
        executor = StrategyBacktestExecutor(
            platform_pool=mock_pool,
            config=StrategyExecutorConfig(),
        )
        
        # Mock internal methods to avoid actual execution
        executor._update_status = AsyncMock()
        executor._get_timescale_pool = AsyncMock()
        executor._fetch_decision_events = AsyncMock(return_value=[])
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
        
        # Should accept these parameters without error
        try:
            result = await executor.execute(
                run_id="test-run-123",
                tenant_id="tenant-1",
                bot_id="bot-1",
                config={
                    "symbol": "BTCUSDT",
                    "start_date": "2024-01-01",
                    "end_date": "2024-01-02",
                    "initial_capital": 10000.0,
                },
            )
            # Should return a dict with status
            assert isinstance(result, dict)
            assert "status" in result
        except TypeError as e:
            pytest.fail(f"execute() signature changed: {e}")
    
    def test_execute_method_exists(self):
        """Test that execute() method exists on StrategyBacktestExecutor."""
        mock_pool = MagicMock()
        executor = StrategyBacktestExecutor(
            platform_pool=mock_pool,
            config=StrategyExecutorConfig(),
        )
        
        assert hasattr(executor, "execute")
        assert callable(executor.execute)


class TestResultsStructure:
    """Test that results structure is preserved."""
    
    def test_results_contain_trades_list(self):
        """Test that results contain trades list."""
        mock_pool = MagicMock()
        executor = StrategyBacktestExecutor(
            platform_pool=mock_pool,
            config=StrategyExecutorConfig(),
        )
        
        results = executor._calculate_metrics(
            trades=[],
            equity_curve=[],
            initial_capital=10000.0,
            final_equity=10000.0,
            max_drawdown=0.0,
            events=[],
        )
        
        assert "trades" in results
        assert isinstance(results["trades"], list)
    
    def test_results_contain_equity_curve(self):
        """Test that results contain equity curve."""
        mock_pool = MagicMock()
        executor = StrategyBacktestExecutor(
            platform_pool=mock_pool,
            config=StrategyExecutorConfig(),
        )
        
        results = executor._calculate_metrics(
            trades=[],
            equity_curve=[{"ts": "2024-01-01", "equity": 10000.0}],
            initial_capital=10000.0,
            final_equity=10000.0,
            max_drawdown=0.0,
            events=[],
        )
        
        assert "equity_curve" in results
        assert isinstance(results["equity_curve"], list)


class TestBackwardsCompatibility:
    """Test backwards compatibility of the refactored executor."""
    
    def test_config_from_env_still_works(self):
        """Test that StrategyExecutorConfig.from_env() still works."""
        config = StrategyExecutorConfig.from_env()
        
        # Should have all expected attributes
        assert hasattr(config, "timescale_host")
        assert hasattr(config, "timescale_port")
        assert hasattr(config, "sample_every")
        assert hasattr(config, "max_spread_bps")
        assert hasattr(config, "min_depth_usd")
        assert hasattr(config, "cooldown_seconds")
    
    def test_executor_initialization(self):
        """Test that executor can be initialized with just platform_pool."""
        mock_pool = MagicMock()
        
        # Should work with just platform_pool
        executor = StrategyBacktestExecutor(platform_pool=mock_pool)
        assert executor is not None
        assert executor.config is not None
        
        # Should work with explicit config
        config = StrategyExecutorConfig(sample_every=5)
        executor = StrategyBacktestExecutor(platform_pool=mock_pool, config=config)
        assert executor.config.sample_every == 5
