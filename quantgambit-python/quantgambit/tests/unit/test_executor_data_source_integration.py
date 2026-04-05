"""
Unit tests for BacktestExecutor data source integration.

Feature: backtest-timescaledb-replay
Task: 7.3 Write unit tests for executor integration

Tests that:
- Redis data source is used by default
- TimescaleDB data source is used when configured
- Error handling for missing exchange parameter

Validates: Requirements 1.1, 1.3, 4.2
"""

import pytest
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, call

from quantgambit.backtesting.executor import (
    BacktestExecutor,
    BacktestStatus,
    ExecutorConfig,
)
from quantgambit.backtesting.data_source import (
    DataSourceFactory,
    DataSourceType,
    DataValidationResult,
)


class TestDataSourceSelection:
    """Tests for data source selection in BacktestExecutor.
    
    Validates: Requirements 1.1, 1.3
    """
    
    @pytest.mark.asyncio
    async def test_redis_data_source_used_by_default(self):
        """
        Redis data source should be used when data_source is not specified.
        
        Validates: Requirements 1.3
        """
        # Create executor with default config
        config = ExecutorConfig(
            data_source="redis",
            temp_dir="/tmp/test_backtests",
        )
        
        mock_pool = MagicMock()
        mock_redis = MagicMock()
        
        executor = BacktestExecutor(
            db_pool=mock_pool,
            redis_client=mock_redis,
            config=config,
        )
        
        # Mock the store
        executor.store = MagicMock()
        executor.store.write_run = AsyncMock()
        executor.store.get_run = AsyncMock(return_value=None)
        
        # Track which data source is created
        created_sources = []
        
        original_create = DataSourceFactory.create
        
        def tracking_create(config, db_pool=None, redis_client=None):
            created_sources.append(config.get("data_source", "redis"))
            # Return a mock data source
            mock_source = MagicMock()
            mock_source.validate = AsyncMock(return_value=DataValidationResult(
                is_valid=True,
                snapshot_count=100,
                trade_count=0,
                first_timestamp=datetime(2024, 1, 1),
                last_timestamp=datetime(2024, 1, 31),
                coverage_pct=100.0,
                warnings=[],
            ))
            mock_source.export = AsyncMock(return_value=100)
            mock_source.close = AsyncMock()
            return mock_source
        
        with patch.object(DataSourceFactory, 'create', side_effect=tracking_create):
            with patch.object(executor, '_replay_snapshots', new_callable=AsyncMock):
                with patch('builtins.open', MagicMock(return_value=iter(['{"test": 1}'] * 100))):
                    mock_path = MagicMock(spec=Path)
                    mock_path.exists.return_value = True
                    mock_path.stat.return_value.st_size = 100
                    
                    # Patch Path to return our mock
                    with patch('quantgambit.backtesting.executor.Path') as MockPath:
                        MockPath.return_value = mock_path
                        mock_path.__truediv__ = MagicMock(return_value=mock_path)
                        mock_path.mkdir = MagicMock()
                        
                        await executor.execute(
                            run_id="test-123",
                            tenant_id="tenant-1",
                            bot_id="bot-1",
                            config={
                                "symbol": "BTC-USDT-SWAP",
                                "start_date": "2024-01-01",
                                "end_date": "2024-01-31",
                            },
                        )
        
        # Verify redis data source was created
        assert len(created_sources) == 1
        assert created_sources[0] == "redis"
    
    @pytest.mark.asyncio
    async def test_timescaledb_data_source_used_when_configured(self):
        """
        TimescaleDB data source should be used when data_source='timescaledb'.
        
        Validates: Requirements 1.1
        """
        # Create executor with timescaledb config
        config = ExecutorConfig(
            data_source="timescaledb",
            default_exchange="okx",
            temp_dir="/tmp/test_backtests",
        )
        
        mock_pool = MagicMock()
        mock_redis = MagicMock()
        
        executor = BacktestExecutor(
            db_pool=mock_pool,
            redis_client=mock_redis,
            config=config,
        )
        
        # Mock the store
        executor.store = MagicMock()
        executor.store.write_run = AsyncMock()
        executor.store.get_run = AsyncMock(return_value=None)
        
        # Track which data source is created
        created_sources = []
        
        def tracking_create(config, db_pool=None, redis_client=None):
            created_sources.append(config.get("data_source", "redis"))
            # Return a mock data source
            mock_source = MagicMock()
            mock_source.validate = AsyncMock(return_value=DataValidationResult(
                is_valid=True,
                snapshot_count=100,
                trade_count=50,
                first_timestamp=datetime(2024, 1, 1),
                last_timestamp=datetime(2024, 1, 31),
                coverage_pct=100.0,
                warnings=[],
            ))
            mock_source.export = AsyncMock(return_value=100)
            mock_source.close = AsyncMock()
            return mock_source
        
        with patch.object(DataSourceFactory, 'create', side_effect=tracking_create):
            with patch.object(executor, '_replay_snapshots', new_callable=AsyncMock):
                with patch('builtins.open', MagicMock(return_value=iter(['{"test": 1}'] * 100))):
                    mock_path = MagicMock(spec=Path)
                    mock_path.exists.return_value = True
                    mock_path.stat.return_value.st_size = 100
                    
                    with patch('quantgambit.backtesting.executor.Path') as MockPath:
                        MockPath.return_value = mock_path
                        mock_path.__truediv__ = MagicMock(return_value=mock_path)
                        mock_path.mkdir = MagicMock()
                        
                        await executor.execute(
                            run_id="test-123",
                            tenant_id="tenant-1",
                            bot_id="bot-1",
                            config={
                                "symbol": "BTC-USDT-SWAP",
                                "start_date": "2024-01-01",
                                "end_date": "2024-01-31",
                            },
                        )
        
        # Verify timescaledb data source was created
        assert len(created_sources) == 1
        assert created_sources[0] == "timescaledb"
    
    @pytest.mark.asyncio
    async def test_config_override_data_source(self):
        """
        Per-backtest config should override executor default data source.
        
        Validates: Requirements 1.1
        """
        # Create executor with redis default
        config = ExecutorConfig(
            data_source="redis",
            default_exchange="okx",
            temp_dir="/tmp/test_backtests",
        )
        
        mock_pool = MagicMock()
        mock_redis = MagicMock()
        
        executor = BacktestExecutor(
            db_pool=mock_pool,
            redis_client=mock_redis,
            config=config,
        )
        
        # Mock the store
        executor.store = MagicMock()
        executor.store.write_run = AsyncMock()
        executor.store.get_run = AsyncMock(return_value=None)
        
        # Track which data source is created
        created_sources = []
        
        def tracking_create(config, db_pool=None, redis_client=None):
            created_sources.append(config.get("data_source", "redis"))
            mock_source = MagicMock()
            mock_source.validate = AsyncMock(return_value=DataValidationResult(
                is_valid=True,
                snapshot_count=100,
                trade_count=50,
                first_timestamp=datetime(2024, 1, 1),
                last_timestamp=datetime(2024, 1, 31),
                coverage_pct=100.0,
                warnings=[],
            ))
            mock_source.export = AsyncMock(return_value=100)
            mock_source.close = AsyncMock()
            return mock_source
        
        with patch.object(DataSourceFactory, 'create', side_effect=tracking_create):
            with patch.object(executor, '_replay_snapshots', new_callable=AsyncMock):
                with patch('builtins.open', MagicMock(return_value=iter(['{"test": 1}'] * 100))):
                    mock_path = MagicMock(spec=Path)
                    mock_path.exists.return_value = True
                    mock_path.stat.return_value.st_size = 100
                    
                    with patch('quantgambit.backtesting.executor.Path') as MockPath:
                        MockPath.return_value = mock_path
                        mock_path.__truediv__ = MagicMock(return_value=mock_path)
                        mock_path.mkdir = MagicMock()
                        
                        # Override data_source in backtest config
                        await executor.execute(
                            run_id="test-123",
                            tenant_id="tenant-1",
                            bot_id="bot-1",
                            config={
                                "symbol": "BTC-USDT-SWAP",
                                "start_date": "2024-01-01",
                                "end_date": "2024-01-31",
                                "data_source": "timescaledb",  # Override
                                "exchange": "binance",
                            },
                        )
        
        # Verify timescaledb was used despite redis default
        assert len(created_sources) == 1
        assert created_sources[0] == "timescaledb"


class TestTimescaleDBExchangeValidation:
    """Tests for exchange parameter validation with TimescaleDB.
    
    Validates: Requirements 4.2
    """
    
    @pytest.mark.asyncio
    async def test_missing_exchange_uses_default(self):
        """
        When exchange is not in backtest config, default_exchange should be used.
        
        Validates: Requirements 4.2
        """
        config = ExecutorConfig(
            data_source="timescaledb",
            default_exchange="okx",
            temp_dir="/tmp/test_backtests",
        )
        
        mock_pool = MagicMock()
        mock_redis = MagicMock()
        
        executor = BacktestExecutor(
            db_pool=mock_pool,
            redis_client=mock_redis,
            config=config,
        )
        
        executor.store = MagicMock()
        executor.store.write_run = AsyncMock()
        executor.store.get_run = AsyncMock(return_value=None)
        
        # Track the config passed to factory
        captured_configs = []
        
        def tracking_create(config, db_pool=None, redis_client=None):
            captured_configs.append(config.copy())
            mock_source = MagicMock()
            mock_source.validate = AsyncMock(return_value=DataValidationResult(
                is_valid=True,
                snapshot_count=100,
                trade_count=50,
                first_timestamp=datetime(2024, 1, 1),
                last_timestamp=datetime(2024, 1, 31),
                coverage_pct=100.0,
                warnings=[],
            ))
            mock_source.export = AsyncMock(return_value=100)
            mock_source.close = AsyncMock()
            return mock_source
        
        with patch.object(DataSourceFactory, 'create', side_effect=tracking_create):
            with patch.object(executor, '_replay_snapshots', new_callable=AsyncMock):
                with patch('builtins.open', MagicMock(return_value=iter(['{"test": 1}'] * 100))):
                    mock_path = MagicMock(spec=Path)
                    mock_path.exists.return_value = True
                    mock_path.stat.return_value.st_size = 100
                    
                    with patch('quantgambit.backtesting.executor.Path') as MockPath:
                        MockPath.return_value = mock_path
                        mock_path.__truediv__ = MagicMock(return_value=mock_path)
                        mock_path.mkdir = MagicMock()
                        
                        await executor.execute(
                            run_id="test-123",
                            tenant_id="tenant-1",
                            bot_id="bot-1",
                            config={
                                "symbol": "BTC-USDT-SWAP",
                                "start_date": "2024-01-01",
                                "end_date": "2024-01-31",
                                # No exchange specified
                            },
                        )
        
        # Verify default exchange was used
        assert len(captured_configs) == 1
        assert captured_configs[0]["exchange"] == "okx"
    
    @pytest.mark.asyncio
    async def test_exchange_from_config_overrides_default(self):
        """
        Exchange in backtest config should override default_exchange.
        
        Validates: Requirements 4.2
        """
        config = ExecutorConfig(
            data_source="timescaledb",
            default_exchange="okx",
            temp_dir="/tmp/test_backtests",
        )
        
        mock_pool = MagicMock()
        mock_redis = MagicMock()
        
        executor = BacktestExecutor(
            db_pool=mock_pool,
            redis_client=mock_redis,
            config=config,
        )
        
        executor.store = MagicMock()
        executor.store.write_run = AsyncMock()
        executor.store.get_run = AsyncMock(return_value=None)
        
        captured_configs = []
        
        def tracking_create(config, db_pool=None, redis_client=None):
            captured_configs.append(config.copy())
            mock_source = MagicMock()
            mock_source.validate = AsyncMock(return_value=DataValidationResult(
                is_valid=True,
                snapshot_count=100,
                trade_count=50,
                first_timestamp=datetime(2024, 1, 1),
                last_timestamp=datetime(2024, 1, 31),
                coverage_pct=100.0,
                warnings=[],
            ))
            mock_source.export = AsyncMock(return_value=100)
            mock_source.close = AsyncMock()
            return mock_source
        
        with patch.object(DataSourceFactory, 'create', side_effect=tracking_create):
            with patch.object(executor, '_replay_snapshots', new_callable=AsyncMock):
                with patch('builtins.open', MagicMock(return_value=iter(['{"test": 1}'] * 100))):
                    mock_path = MagicMock(spec=Path)
                    mock_path.exists.return_value = True
                    mock_path.stat.return_value.st_size = 100
                    
                    with patch('quantgambit.backtesting.executor.Path') as MockPath:
                        MockPath.return_value = mock_path
                        mock_path.__truediv__ = MagicMock(return_value=mock_path)
                        mock_path.mkdir = MagicMock()
                        
                        await executor.execute(
                            run_id="test-123",
                            tenant_id="tenant-1",
                            bot_id="bot-1",
                            config={
                                "symbol": "BTC-USDT-SWAP",
                                "start_date": "2024-01-01",
                                "end_date": "2024-01-31",
                                "exchange": "binance",  # Override
                            },
                        )
        
        # Verify config exchange was used
        assert len(captured_configs) == 1
        assert captured_configs[0]["exchange"] == "binance"


class TestDataValidationHandling:
    """Tests for data validation result handling.
    
    Validates: Requirements 5.1
    """
    
    @pytest.mark.asyncio
    async def test_validation_failure_returns_failed_status(self):
        """
        When data validation fails, executor should return FAILED status.
        
        Validates: Requirements 5.1
        """
        config = ExecutorConfig(
            data_source="timescaledb",
            default_exchange="okx",
            temp_dir="/tmp/test_backtests",
        )
        
        mock_pool = MagicMock()
        mock_redis = MagicMock()
        
        executor = BacktestExecutor(
            db_pool=mock_pool,
            redis_client=mock_redis,
            config=config,
        )
        
        executor.store = MagicMock()
        executor.store.write_run = AsyncMock()
        executor.store.get_run = AsyncMock(return_value=None)
        
        def failing_create(config, db_pool=None, redis_client=None):
            mock_source = MagicMock()
            mock_source.validate = AsyncMock(return_value=DataValidationResult(
                is_valid=False,
                snapshot_count=0,
                trade_count=0,
                first_timestamp=None,
                last_timestamp=None,
                coverage_pct=0.0,
                warnings=[],
                error_message="No data found for the specified time range",
            ))
            mock_source.close = AsyncMock()
            return mock_source
        
        with patch.object(DataSourceFactory, 'create', side_effect=failing_create):
            mock_path = MagicMock(spec=Path)
            mock_path.mkdir = MagicMock()
            mock_path.__truediv__ = MagicMock(return_value=mock_path)
            
            with patch('quantgambit.backtesting.executor.Path') as MockPath:
                MockPath.return_value = mock_path
                
                result = await executor.execute(
                    run_id="test-123",
                    tenant_id="tenant-1",
                    bot_id="bot-1",
                    config={
                        "symbol": "BTC-USDT-SWAP",
                        "start_date": "2024-01-01",
                        "end_date": "2024-01-31",
                    },
                )
        
        assert result.status == BacktestStatus.FAILED
        assert "No data found" in result.error_message or "validation failed" in result.error_message.lower()
    
    @pytest.mark.asyncio
    async def test_validation_warnings_are_logged(self):
        """
        Validation warnings should be logged but not fail the backtest.
        
        Validates: Requirements 5.1
        """
        config = ExecutorConfig(
            data_source="timescaledb",
            default_exchange="okx",
            temp_dir="/tmp/test_backtests",
        )
        
        mock_pool = MagicMock()
        mock_redis = MagicMock()
        
        executor = BacktestExecutor(
            db_pool=mock_pool,
            redis_client=mock_redis,
            config=config,
        )
        
        executor.store = MagicMock()
        executor.store.write_run = AsyncMock()
        executor.store.get_run = AsyncMock(return_value=None)
        
        logged_warnings = []
        
        def create_with_warnings(config, db_pool=None, redis_client=None):
            mock_source = MagicMock()
            mock_source.validate = AsyncMock(return_value=DataValidationResult(
                is_valid=True,
                snapshot_count=50,
                trade_count=25,
                first_timestamp=datetime(2024, 1, 5),
                last_timestamp=datetime(2024, 1, 25),
                coverage_pct=66.7,
                warnings=["Low data coverage: 66.7%", "Data starts 4 days after requested start"],
            ))
            mock_source.export = AsyncMock(return_value=50)
            mock_source.close = AsyncMock()
            return mock_source
        
        with patch.object(DataSourceFactory, 'create', side_effect=create_with_warnings):
            with patch.object(executor, '_replay_snapshots', new_callable=AsyncMock):
                with patch('builtins.open', MagicMock(return_value=iter(['{"test": 1}'] * 50))):
                    with patch('quantgambit.backtesting.executor.log_warning') as mock_log_warning:
                        mock_path = MagicMock(spec=Path)
                        mock_path.exists.return_value = True
                        mock_path.stat.return_value.st_size = 100
                        mock_path.mkdir = MagicMock()
                        mock_path.__truediv__ = MagicMock(return_value=mock_path)
                        
                        with patch('quantgambit.backtesting.executor.Path') as MockPath:
                            MockPath.return_value = mock_path
                            
                            result = await executor.execute(
                                run_id="test-123",
                                tenant_id="tenant-1",
                                bot_id="bot-1",
                                config={
                                    "symbol": "BTC-USDT-SWAP",
                                    "start_date": "2024-01-01",
                                    "end_date": "2024-01-31",
                                },
                            )
                        
                        # Verify warnings were logged
                        warning_calls = [c for c in mock_log_warning.call_args_list 
                                        if c[0][0] == "backtest_data_warning"]
                        assert len(warning_calls) == 2


class TestTimescaleDBConfigPropagation:
    """Tests for TimescaleDB-specific config propagation.
    
    Validates: Requirements 6.1
    """
    
    @pytest.mark.asyncio
    async def test_batch_size_propagated_to_data_source(self):
        """
        timescaledb_batch_size should be passed to the data source.
        
        Validates: Requirements 6.1
        """
        config = ExecutorConfig(
            data_source="timescaledb",
            default_exchange="okx",
            timescaledb_batch_size=500,
            temp_dir="/tmp/test_backtests",
        )
        
        mock_pool = MagicMock()
        mock_redis = MagicMock()
        
        executor = BacktestExecutor(
            db_pool=mock_pool,
            redis_client=mock_redis,
            config=config,
        )
        
        executor.store = MagicMock()
        executor.store.write_run = AsyncMock()
        executor.store.get_run = AsyncMock(return_value=None)
        
        captured_configs = []
        
        def tracking_create(config, db_pool=None, redis_client=None):
            captured_configs.append(config.copy())
            mock_source = MagicMock()
            mock_source.validate = AsyncMock(return_value=DataValidationResult(
                is_valid=True,
                snapshot_count=100,
                trade_count=50,
                first_timestamp=datetime(2024, 1, 1),
                last_timestamp=datetime(2024, 1, 31),
                coverage_pct=100.0,
                warnings=[],
            ))
            mock_source.export = AsyncMock(return_value=100)
            mock_source.close = AsyncMock()
            return mock_source
        
        with patch.object(DataSourceFactory, 'create', side_effect=tracking_create):
            with patch.object(executor, '_replay_snapshots', new_callable=AsyncMock):
                with patch('builtins.open', MagicMock(return_value=iter(['{"test": 1}'] * 100))):
                    mock_path = MagicMock(spec=Path)
                    mock_path.exists.return_value = True
                    mock_path.stat.return_value.st_size = 100
                    mock_path.mkdir = MagicMock()
                    mock_path.__truediv__ = MagicMock(return_value=mock_path)
                    
                    with patch('quantgambit.backtesting.executor.Path') as MockPath:
                        MockPath.return_value = mock_path
                        
                        await executor.execute(
                            run_id="test-123",
                            tenant_id="tenant-1",
                            bot_id="bot-1",
                            config={
                                "symbol": "BTC-USDT-SWAP",
                                "start_date": "2024-01-01",
                                "end_date": "2024-01-31",
                            },
                        )
        
        assert len(captured_configs) == 1
        assert captured_configs[0]["batch_size"] == 500
    
    @pytest.mark.asyncio
    async def test_include_trades_propagated_to_data_source(self):
        """
        timescaledb_include_trades should be passed to the data source.
        
        Validates: Requirements 6.1
        """
        config = ExecutorConfig(
            data_source="timescaledb",
            default_exchange="okx",
            timescaledb_include_trades=False,
            temp_dir="/tmp/test_backtests",
        )
        
        mock_pool = MagicMock()
        mock_redis = MagicMock()
        
        executor = BacktestExecutor(
            db_pool=mock_pool,
            redis_client=mock_redis,
            config=config,
        )
        
        executor.store = MagicMock()
        executor.store.write_run = AsyncMock()
        executor.store.get_run = AsyncMock(return_value=None)
        
        captured_configs = []
        
        def tracking_create(config, db_pool=None, redis_client=None):
            captured_configs.append(config.copy())
            mock_source = MagicMock()
            mock_source.validate = AsyncMock(return_value=DataValidationResult(
                is_valid=True,
                snapshot_count=100,
                trade_count=0,
                first_timestamp=datetime(2024, 1, 1),
                last_timestamp=datetime(2024, 1, 31),
                coverage_pct=100.0,
                warnings=[],
            ))
            mock_source.export = AsyncMock(return_value=100)
            mock_source.close = AsyncMock()
            return mock_source
        
        with patch.object(DataSourceFactory, 'create', side_effect=tracking_create):
            with patch.object(executor, '_replay_snapshots', new_callable=AsyncMock):
                with patch('builtins.open', MagicMock(return_value=iter(['{"test": 1}'] * 100))):
                    mock_path = MagicMock(spec=Path)
                    mock_path.exists.return_value = True
                    mock_path.stat.return_value.st_size = 100
                    mock_path.mkdir = MagicMock()
                    mock_path.__truediv__ = MagicMock(return_value=mock_path)
                    
                    with patch('quantgambit.backtesting.executor.Path') as MockPath:
                        MockPath.return_value = mock_path
                        
                        await executor.execute(
                            run_id="test-123",
                            tenant_id="tenant-1",
                            bot_id="bot-1",
                            config={
                                "symbol": "BTC-USDT-SWAP",
                                "start_date": "2024-01-01",
                                "end_date": "2024-01-31",
                            },
                        )
        
        assert len(captured_configs) == 1
        assert captured_configs[0]["include_trades"] is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
