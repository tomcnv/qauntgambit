"""Tests for backlog policy with tiered management."""

import asyncio
import pytest

from quantgambit.io.backlog_policy import (
    BacklogPolicy,
    BacklogPolicyConfig,
    BacklogTier,
    StreamBacklogConfig,
    StreamType,
)


class TestBacklogTierComputation:
    """Test tier computation based on depth and lag."""
    
    def test_normal_tier_when_below_thresholds(self):
        """Normal tier when depth and lag are low."""
        config = BacklogPolicyConfig(
            streams={
                "test_stream": StreamBacklogConfig(
                    soft_threshold=1000,
                    hard_threshold=5000,
                ),
            },
            lag_soft_threshold=100,
            lag_hard_threshold=500,
        )
        policy = BacklogPolicy(config=config)
        
        async def check():
            metrics = await policy.check_and_enforce(
                stream_depths={"test_stream": 500},
                consumer_lags={"test_stream": 50},
            )
            assert metrics.overall_tier == BacklogTier.NORMAL
            assert metrics.streams["test_stream"].tier == BacklogTier.NORMAL
        
        asyncio.run(check())
    
    def test_soft_tier_on_high_depth(self):
        """Soft tier when depth exceeds soft threshold."""
        config = BacklogPolicyConfig(
            streams={
                "test_stream": StreamBacklogConfig(
                    soft_threshold=1000,
                    hard_threshold=5000,
                ),
            },
        )
        policy = BacklogPolicy(config=config)
        
        async def check():
            metrics = await policy.check_and_enforce(
                stream_depths={"test_stream": 2000},  # Above soft, below hard
                consumer_lags={"test_stream": 0},
            )
            assert metrics.overall_tier == BacklogTier.SOFT
            assert metrics.streams["test_stream"].tier == BacklogTier.SOFT
        
        asyncio.run(check())
    
    def test_soft_tier_on_high_lag(self):
        """Soft tier when lag exceeds soft threshold."""
        config = BacklogPolicyConfig(
            lag_soft_threshold=100,
            lag_hard_threshold=500,
        )
        policy = BacklogPolicy(config=config)
        
        async def check():
            metrics = await policy.check_and_enforce(
                stream_depths={"test_stream": 500},  # Low depth
                consumer_lags={"test_stream": 200},  # Above soft lag
            )
            assert metrics.overall_tier == BacklogTier.SOFT
        
        asyncio.run(check())
    
    def test_hard_tier_on_high_depth(self):
        """Hard tier when depth exceeds hard threshold."""
        config = BacklogPolicyConfig(
            streams={
                "test_stream": StreamBacklogConfig(
                    soft_threshold=1000,
                    hard_threshold=5000,
                ),
            },
        )
        policy = BacklogPolicy(config=config)
        
        async def check():
            metrics = await policy.check_and_enforce(
                stream_depths={"test_stream": 10000},  # Above hard
                consumer_lags={"test_stream": 0},
            )
            assert metrics.overall_tier == BacklogTier.HARD
            assert metrics.streams["test_stream"].tier == BacklogTier.HARD
        
        asyncio.run(check())
    
    def test_hard_tier_on_high_lag(self):
        """Hard tier when lag exceeds hard threshold."""
        config = BacklogPolicyConfig(
            lag_soft_threshold=100,
            lag_hard_threshold=500,
        )
        policy = BacklogPolicy(config=config)
        
        async def check():
            metrics = await policy.check_and_enforce(
                stream_depths={"test_stream": 100},  # Low depth
                consumer_lags={"test_stream": 1000},  # Above hard lag
            )
            assert metrics.overall_tier == BacklogTier.HARD
        
        asyncio.run(check())
    
    def test_worst_tier_wins(self):
        """Overall tier is the worst across all streams."""
        config = BacklogPolicyConfig(
            streams={
                "stream_a": StreamBacklogConfig(soft_threshold=1000, hard_threshold=5000),
                "stream_b": StreamBacklogConfig(soft_threshold=1000, hard_threshold=5000),
            },
        )
        policy = BacklogPolicy(config=config)
        
        async def check():
            metrics = await policy.check_and_enforce(
                stream_depths={
                    "stream_a": 500,   # Normal
                    "stream_b": 10000,  # Hard
                },
                consumer_lags={},
            )
            assert metrics.overall_tier == BacklogTier.HARD
            assert metrics.streams["stream_a"].tier == BacklogTier.NORMAL
            assert metrics.streams["stream_b"].tier == BacklogTier.HARD
        
        asyncio.run(check())


class TestBacklogHelpers:
    """Test helper methods for backlog policy."""
    
    def test_should_reduce_size_on_soft_tier(self):
        """should_reduce_size returns True on soft tier."""
        config = BacklogPolicyConfig(
            streams={
                "test_stream": StreamBacklogConfig(soft_threshold=1000, hard_threshold=5000),
            },
        )
        policy = BacklogPolicy(config=config)
        
        async def check():
            await policy.check_and_enforce(
                stream_depths={"test_stream": 2000},
                consumer_lags={},
            )
            assert policy.should_reduce_size() == True
            assert policy.should_block_entries() == False
        
        asyncio.run(check())
    
    def test_should_block_entries_on_hard_tier(self):
        """should_block_entries returns True on hard tier."""
        config = BacklogPolicyConfig(
            streams={
                "test_stream": StreamBacklogConfig(soft_threshold=1000, hard_threshold=5000),
            },
        )
        policy = BacklogPolicy(config=config)
        
        async def check():
            await policy.check_and_enforce(
                stream_depths={"test_stream": 10000},
                consumer_lags={},
            )
            assert policy.should_reduce_size() == True
            assert policy.should_block_entries() == True
        
        asyncio.run(check())
    
    def test_no_action_on_normal_tier(self):
        """No action needed on normal tier."""
        config = BacklogPolicyConfig()
        policy = BacklogPolicy(config=config)
        
        async def check():
            await policy.check_and_enforce(
                stream_depths={"test_stream": 100},
                consumer_lags={"test_stream": 0},
            )
            assert policy.should_reduce_size() == False
            assert policy.should_block_entries() == False
        
        asyncio.run(check())


class TestBacklogMetrics:
    """Test metrics tracking."""
    
    def test_metrics_aggregation(self):
        """Metrics are properly aggregated."""
        config = BacklogPolicyConfig()
        policy = BacklogPolicy(config=config)
        
        async def check():
            metrics = await policy.check_and_enforce(
                stream_depths={
                    "stream_a": 1000,
                    "stream_b": 2000,
                },
                consumer_lags={
                    "stream_a": 100,
                    "stream_b": 200,
                },
            )
            assert metrics.total_depth == 3000
            assert metrics.total_lag == 300
            assert len(metrics.streams) == 2
        
        asyncio.run(check())
    
    def test_metrics_to_dict(self):
        """Metrics can be serialized to dict."""
        config = BacklogPolicyConfig()
        policy = BacklogPolicy(config=config)
        
        async def check():
            metrics = await policy.check_and_enforce(
                stream_depths={"test_stream": 1000},
                consumer_lags={"test_stream": 100},
            )
            d = metrics.to_dict()
            assert "overall_tier" in d
            assert "total_depth" in d
            assert "total_lag" in d
            assert "streams" in d
        
        asyncio.run(check())


class TestTradeStreamProtection:
    """Test that trade streams are never trimmed."""
    
    def test_trades_never_trimmed(self):
        """Trade streams are protected from trimming."""
        trim_called = []
        
        async def mock_trim(stream: str, count: int) -> int:
            trim_called.append((stream, count))
            return count
        
        config = BacklogPolicyConfig(
            streams={
                "events:trades": StreamBacklogConfig(
                    stream_type=StreamType.TRADES,
                    soft_threshold=1000,
                    hard_threshold=5000,
                    protect_exit_signals=True,  # This should prevent trimming
                ),
            },
            enable_trimming=True,
        )
        policy = BacklogPolicy(
            config=config,
            trim_callback=mock_trim,
        )
        
        async def check():
            # Even at hard tier, trades should not be trimmed
            await policy.check_and_enforce(
                stream_depths={"events:trades": 10000},  # Above hard
                consumer_lags={},
            )
            # Trim should NOT have been called for trades
            assert len(trim_called) == 0
        
        asyncio.run(check())


class TestResyncAfterTrim:
    """Test that resync is triggered after trim operations."""
    
    def test_resync_triggered_after_compact(self):
        """Resync is triggered after orderbook compaction."""
        resync_called = []
        compact_called = []
        
        async def mock_resync(stream: str) -> None:
            resync_called.append(stream)
        
        async def mock_compact(stream: str, top_n: int) -> int:
            compact_called.append((stream, top_n))
            return 100  # Compacted 100 entries
        
        config = BacklogPolicyConfig(
            streams={
                "events:orderbook": StreamBacklogConfig(
                    stream_type=StreamType.ORDERBOOK,
                    soft_threshold=1000,
                    hard_threshold=5000,
                    top_n_levels=20,
                    resync_after_trim=True,
                ),
            },
            enable_compaction=True,
        )
        policy = BacklogPolicy(
            config=config,
            resync_callback=mock_resync,
            compact_callback=mock_compact,
        )
        
        async def check():
            await policy.check_and_enforce(
                stream_depths={"events:orderbook": 10000},  # Above hard
                consumer_lags={},
            )
            # Compact should have been called
            assert len(compact_called) == 1
            assert compact_called[0][1] == 20  # top_n_levels
            # Resync should have been called after compact
            assert len(resync_called) == 1
        
        asyncio.run(check())
