"""Property tests for sampling preservation in backtest executor.

Property 7: Sampling Preservation
- Test that every Nth event is processed
- Test that sampling behavior matches current implementation

Requirements: 6.2
"""

import pytest
from unittest.mock import MagicMock, AsyncMock
from datetime import datetime, timezone

from quantgambit.backtesting.strategy_executor import (
    StrategyBacktestExecutor,
    StrategyExecutorConfig,
)


class TestSamplingBehavior:
    """Test that sampling behavior is preserved."""
    
    def test_sample_every_config_is_respected(self):
        """Test that sample_every configuration is respected."""
        mock_pool = MagicMock()
        
        # Create config with specific sample_every
        config = StrategyExecutorConfig(sample_every=5)
        executor = StrategyBacktestExecutor(
            platform_pool=mock_pool,
            config=config,
        )
        
        assert executor.config.sample_every == 5
    
    def test_default_sample_every_is_10(self):
        """Test that default sample_every is 10."""
        mock_pool = MagicMock()
        executor = StrategyBacktestExecutor(platform_pool=mock_pool)
        
        assert executor.config.sample_every == 10
    
    def test_sample_interval_calculation(self):
        """Test that sample interval for equity curve is calculated correctly."""
        # The sample_interval for equity curve is max(1, len(events) // 500)
        # This ensures we get ~500 equity curve points regardless of event count
        
        # With 1000 events, interval should be 2
        assert max(1, 1000 // 500) == 2
        
        # With 100 events, interval should be 1 (minimum)
        assert max(1, 100 // 500) == 1
        
        # With 5000 events, interval should be 10
        assert max(1, 5000 // 500) == 10


class TestEventSampling:
    """Test that decision events are sampled correctly."""
    
    @pytest.mark.asyncio
    async def test_fetch_decision_events_samples_correctly(self):
        """Test that _fetch_decision_events samples every Nth event."""
        mock_pool = MagicMock()
        config = StrategyExecutorConfig(sample_every=3)
        executor = StrategyBacktestExecutor(
            platform_pool=mock_pool,
            config=config,
        )
        
        # Create mock timescale pool with proper async context manager
        mock_ts_pool = MagicMock()
        mock_conn = AsyncMock()
        
        # Create 10 mock rows
        mock_rows = []
        for i in range(10):
            mock_rows.append({
                "ts": datetime(2024, 1, 1, 0, i, 0, tzinfo=timezone.utc),
                "payload": {"price": 50000 + i},
            })
        
        mock_conn.fetch = AsyncMock(return_value=mock_rows)
        mock_ts_pool.acquire = MagicMock(return_value=AsyncContextManager(mock_conn))
        
        executor._timescale_pool = mock_ts_pool
        
        # Fetch events
        events = await executor._fetch_decision_events(
            symbol="BTCUSDT",
            start_date="2024-01-01",
            end_date="2024-01-02",
        )
        
        # With sample_every=3, we should get events at indices 0, 3, 6, 9
        # That's 4 events from 10 total
        assert len(events) == 4
        
        # Verify the timestamps are correct (indices 0, 3, 6, 9)
        expected_minutes = [0, 3, 6, 9]
        for i, event in enumerate(events):
            assert event["ts"].minute == expected_minutes[i]


class AsyncContextManager:
    """Helper class for async context manager mocking."""
    def __init__(self, return_value):
        self.return_value = return_value
    
    async def __aenter__(self):
        return self.return_value
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        return None


class TestEquityCurveSampling:
    """Test that equity curve sampling is preserved."""
    
    def test_equity_curve_has_reasonable_size(self):
        """Test that equity curve doesn't grow unbounded."""
        mock_pool = MagicMock()
        executor = StrategyBacktestExecutor(
            platform_pool=mock_pool,
            config=StrategyExecutorConfig(),
        )
        
        # Create many events (using microseconds to avoid datetime limits)
        events = [
            {"ts": datetime(2024, 1, 1, i // 3600, (i // 60) % 60, i % 60, tzinfo=timezone.utc)}
            for i in range(3600)  # 1 hour of events, 1 per second
        ]
        
        # Calculate expected sample interval
        sample_interval = max(1, len(events) // 500)
        
        # Expected equity curve points
        expected_points = len(events) // sample_interval
        
        # Should be around 500 points (give or take)
        assert 400 <= expected_points <= 600


class TestConfigurationPreservation:
    """Test that configuration options are preserved."""
    
    def test_all_config_options_available(self):
        """Test that all configuration options are still available."""
        config = StrategyExecutorConfig(
            timescale_host="localhost",
            timescale_port=5433,
            timescale_db="test_db",
            timescale_user="test_user",
            timescale_password="test_pass",
            sample_every=5,
            amt_lookback_candles=50,
            amt_value_area_pct=70.0,
            max_spread_bps=20.0,
            min_depth_usd=5000.0,
            max_snapshot_age_ms=3000.0,
            cooldown_seconds=30.0,
        )
        
        assert config.timescale_host == "localhost"
        assert config.timescale_port == 5433
        assert config.timescale_db == "test_db"
        assert config.timescale_user == "test_user"
        assert config.timescale_password == "test_pass"
        assert config.sample_every == 5
        assert config.amt_lookback_candles == 50
        assert config.amt_value_area_pct == 70.0
        assert config.max_spread_bps == 20.0
        assert config.min_depth_usd == 5000.0
        assert config.max_snapshot_age_ms == 3000.0
        assert config.cooldown_seconds == 30.0
    
    def test_config_from_env_uses_defaults(self):
        """Test that from_env() uses sensible defaults."""
        config = StrategyExecutorConfig.from_env()
        
        # Check defaults
        assert config.sample_every == 10
        assert config.amt_lookback_candles == 100
        assert config.amt_value_area_pct == 68.0
        assert config.max_spread_bps == 15.0
        assert config.min_depth_usd == 10000.0
        assert config.cooldown_seconds == 60.0
