"""
Integration tests for MDS resilience under various scenarios.

Tests cover:
1. Load spikes - sudden increase in message volume
2. Asymmetric feeds - trades healthy but orderbook stalled (and vice versa)
3. Backlog tier transitions - soft to hard and recovery
4. Post-trim resync validation
5. Soak test for drift detection
"""

import asyncio
import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from quantgambit.io.backlog_policy import (
    BacklogPolicy,
    BacklogPolicyConfig,
    BacklogTier,
    StreamBacklogConfig,
    StreamType,
)
from quantgambit.diagnostics.health_worker import HealthWorker, HealthWorkerConfig


class FakeRedisForResilience:
    """Fake Redis client for resilience testing."""
    
    def __init__(self):
        self.depths = {}
        self.consumer_lags = {}
        self.redis = self
        self._keys = []
    
    async def stream_length(self, stream):
        return self.depths.get(stream, 0)
    
    async def xinfo_groups(self, stream):
        lag = self.consumer_lags.get(stream, 0)
        # Match HealthWorker lookup: it filters groups by "{tenant}:{bot}" substring.
        return [{"name": "quantgambit:test_group:t1:b1", "lag": lag}]
    
    async def keys(self, pattern):
        return self._keys
    
    async def get(self, key):
        return None
    
    def set_depth(self, stream, depth):
        self.depths[stream] = depth
    
    def set_lag(self, stream, lag):
        self.consumer_lags[stream] = lag


class FakeTelemetry:
    """Fake telemetry for testing."""
    
    def __init__(self):
        self.payloads = []
    
    async def publish_latency(self, ctx, payload):
        self.payloads.append(("latency", payload))
    
    async def publish_health_snapshot(self, ctx, payload):
        self.payloads.append(("health", payload))


class TestLoadSpikes:
    """Test behavior under sudden load spikes."""
    
    def test_graceful_degradation_on_spike(self):
        """System degrades gracefully when load spikes."""
        redis = FakeRedisForResilience()
        telemetry = FakeTelemetry()
        
        config = HealthWorkerConfig(
            streams=["events:market_data"],
            track_consumer_lag=True,
            backlog_config=BacklogPolicyConfig(
                streams={
                    "events:market_data": StreamBacklogConfig(
                        soft_threshold=1000,
                        hard_threshold=5000,
                    ),
                },
                lag_soft_threshold=100,
                lag_hard_threshold=500,
            ),
        )
        
        worker = HealthWorker(
            redis_client=redis,
            telemetry=telemetry,
            telemetry_context=MagicMock(tenant_id="t1", bot_id="b1"),
            config=config,
        )
        
        async def simulate_spike():
            # Start normal
            redis.set_depth("events:market_data", 500)
            redis.set_lag("events:market_data", 0)
            await worker._emit_once()
            
            # Spike occurs
            redis.set_depth("events:market_data", 10000)
            redis.set_lag("events:market_data", 2000)
            await worker._emit_once()
            
            # Check degradation
            health_payloads = [p for n, p in telemetry.payloads if n == "health"]
            assert health_payloads[-1]["status"] == "degraded"
            assert health_payloads[-1]["backlog_tier"] == "hard"
            assert worker.should_block_entries() == True
        
        asyncio.run(simulate_spike())
    
    def test_recovery_after_spike(self):
        """System recovers when load returns to normal."""
        redis = FakeRedisForResilience()
        telemetry = FakeTelemetry()
        
        config = HealthWorkerConfig(
            streams=["events:market_data"],
            track_consumer_lag=True,
            backlog_config=BacklogPolicyConfig(
                streams={
                    "events:market_data": StreamBacklogConfig(
                        soft_threshold=1000,
                        hard_threshold=5000,
                    ),
                },
                lag_soft_threshold=100,
                lag_hard_threshold=500,
            ),
        )
        
        worker = HealthWorker(
            redis_client=redis,
            telemetry=telemetry,
            telemetry_context=MagicMock(tenant_id="t1", bot_id="b1"),
            config=config,
        )
        
        async def simulate_recovery():
            # Start degraded (above hard threshold)
            redis.set_depth("events:market_data", 10000)
            redis.set_lag("events:market_data", 2000)
            await worker._emit_once()
            assert worker.should_block_entries() == True
            
            # Load returns to normal
            redis.set_depth("events:market_data", 500)
            redis.set_lag("events:market_data", 0)
            await worker._emit_once()
            
            # Check recovery
            health_payloads = [p for n, p in telemetry.payloads if n == "health"]
            assert health_payloads[-1]["status"] == "ok"
            assert health_payloads[-1]["backlog_tier"] == "normal"
            assert worker.should_block_entries() == False
        
        asyncio.run(simulate_recovery())


class TestAsymmetricFeeds:
    """Test behavior when feeds have different health states."""
    
    def test_trades_healthy_orderbook_stalled(self):
        """Trades healthy but orderbook stalled should still allow exits."""
        redis = FakeRedisForResilience()
        telemetry = FakeTelemetry()
        
        config = HealthWorkerConfig(
            streams=["events:trades", "events:orderbook"],
            track_consumer_lag=True,
            backlog_config=BacklogPolicyConfig(
                streams={
                    "events:trades": StreamBacklogConfig(
                        stream_type=StreamType.TRADES,
                        soft_threshold=1000,
                        hard_threshold=5000,
                    ),
                    "events:orderbook": StreamBacklogConfig(
                        stream_type=StreamType.ORDERBOOK,
                        soft_threshold=1000,
                        hard_threshold=5000,
                    ),
                },
            ),
        )
        
        worker = HealthWorker(
            redis_client=redis,
            telemetry=telemetry,
            telemetry_context=MagicMock(tenant_id="t1", bot_id="b1"),
            config=config,
        )
        
        async def check():
            # Trades healthy, orderbook stalled
            redis.set_depth("events:trades", 500)
            redis.set_lag("events:trades", 0)
            redis.set_depth("events:orderbook", 10000)  # Stalled
            redis.set_lag("events:orderbook", 5000)
            
            await worker._emit_once()
            
            health_payloads = [p for n, p in telemetry.payloads if n == "health"]
            payload = health_payloads[-1]
            
            # Overall should be degraded due to orderbook
            assert payload["status"] == "degraded"
            
            # But stream tiers should be different
            assert payload["stream_tiers"]["events:trades"] == "normal"
            assert payload["stream_tiers"]["events:orderbook"] == "hard"
        
        asyncio.run(check())
    
    def test_orderbook_healthy_trades_stalled(self):
        """Orderbook healthy but trades stalled is more critical."""
        redis = FakeRedisForResilience()
        telemetry = FakeTelemetry()
        
        config = HealthWorkerConfig(
            streams=["events:trades", "events:orderbook"],
            track_consumer_lag=True,
            backlog_config=BacklogPolicyConfig(
                streams={
                    "events:trades": StreamBacklogConfig(
                        stream_type=StreamType.TRADES,
                        soft_threshold=1000,
                        hard_threshold=5000,
                        protect_exit_signals=True,
                    ),
                    "events:orderbook": StreamBacklogConfig(
                        stream_type=StreamType.ORDERBOOK,
                        soft_threshold=1000,
                        hard_threshold=5000,
                    ),
                },
            ),
        )
        
        worker = HealthWorker(
            redis_client=redis,
            telemetry=telemetry,
            telemetry_context=MagicMock(tenant_id="t1", bot_id="b1"),
            config=config,
        )
        
        async def check():
            # Orderbook healthy, trades stalled
            redis.set_depth("events:orderbook", 500)
            redis.set_lag("events:orderbook", 0)
            redis.set_depth("events:trades", 10000)  # Stalled
            redis.set_lag("events:trades", 5000)
            
            await worker._emit_once()
            
            health_payloads = [p for n, p in telemetry.payloads if n == "health"]
            payload = health_payloads[-1]
            
            # Overall should be degraded
            assert payload["status"] == "degraded"
            
            # Trades should be hard tier
            assert payload["stream_tiers"]["events:trades"] == "hard"
            assert payload["stream_tiers"]["events:orderbook"] == "normal"
        
        asyncio.run(check())


class TestBacklogTierTransitions:
    """Test transitions between backlog tiers."""
    
    def test_normal_to_soft_to_hard_to_normal(self):
        """Test full tier transition cycle."""
        redis = FakeRedisForResilience()
        telemetry = FakeTelemetry()
        
        config = HealthWorkerConfig(
            streams=["events:market_data"],
            track_consumer_lag=True,
            backlog_config=BacklogPolicyConfig(
                streams={
                    "events:market_data": StreamBacklogConfig(
                        soft_threshold=1000,
                        hard_threshold=5000,
                    ),
                },
            ),
        )
        
        worker = HealthWorker(
            redis_client=redis,
            telemetry=telemetry,
            telemetry_context=MagicMock(tenant_id="t1", bot_id="b1"),
            config=config,
        )
        
        async def check():
            tiers = []
            
            # Normal
            redis.set_depth("events:market_data", 500)
            redis.set_lag("events:market_data", 0)
            await worker._emit_once()
            tiers.append(worker.get_backlog_policy().get_overall_tier())
            
            # Soft
            redis.set_depth("events:market_data", 2000)
            redis.set_lag("events:market_data", 0)
            await worker._emit_once()
            tiers.append(worker.get_backlog_policy().get_overall_tier())
            
            # Hard
            redis.set_depth("events:market_data", 10000)
            redis.set_lag("events:market_data", 0)
            await worker._emit_once()
            tiers.append(worker.get_backlog_policy().get_overall_tier())
            
            # Back to normal
            redis.set_depth("events:market_data", 500)
            redis.set_lag("events:market_data", 0)
            await worker._emit_once()
            tiers.append(worker.get_backlog_policy().get_overall_tier())
            
            assert tiers == [
                BacklogTier.NORMAL,
                BacklogTier.SOFT,
                BacklogTier.HARD,
                BacklogTier.NORMAL,
            ]
        
        asyncio.run(check())


class TestPostTrimResync:
    """Test that resync is properly triggered after trim operations."""
    
    def test_resync_after_orderbook_compact(self):
        """Resync is triggered after orderbook compaction."""
        resync_called = []
        compact_called = []
        
        async def mock_resync(stream: str) -> None:
            resync_called.append(stream)
        
        async def mock_compact(stream: str, top_n: int) -> int:
            compact_called.append((stream, top_n))
            return 100
        
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
            # Trigger hard tier
            await policy.check_and_enforce(
                stream_depths={"events:orderbook": 10000},
                consumer_lags={},
            )
            
            # Verify compact was called
            assert len(compact_called) == 1
            assert compact_called[0] == ("events:orderbook", 20)
            
            # Verify resync was called after compact
            assert len(resync_called) == 1
            assert resync_called[0] == "events:orderbook"
        
        asyncio.run(check())
    
    def test_no_resync_when_disabled(self):
        """No resync when resync_after_trim is False."""
        resync_called = []
        compact_called = []
        
        async def mock_resync(stream: str) -> None:
            resync_called.append(stream)
        
        async def mock_compact(stream: str, top_n: int) -> int:
            compact_called.append((stream, top_n))
            return 100
        
        config = BacklogPolicyConfig(
            streams={
                "events:orderbook": StreamBacklogConfig(
                    stream_type=StreamType.ORDERBOOK,
                    soft_threshold=1000,
                    hard_threshold=5000,
                    resync_after_trim=False,  # Disabled
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
                stream_depths={"events:orderbook": 10000},
                consumer_lags={},
            )
            
            # Compact was called
            assert len(compact_called) == 1
            
            # But resync was NOT called
            assert len(resync_called) == 0
        
        asyncio.run(check())


class TestSoakDrift:
    """Test for drift detection over sustained load."""
    
    def test_metrics_accumulate_correctly(self):
        """Metrics accumulate correctly over multiple checks."""
        config = BacklogPolicyConfig()
        policy = BacklogPolicy(config=config)
        
        async def check():
            # Simulate multiple checks
            for i in range(10):
                await policy.check_and_enforce(
                    stream_depths={"test_stream": 1000 + i * 100},
                    consumer_lags={"test_stream": 50 + i * 10},
                )
            
            metrics = policy.get_metrics()
            
            # Last check should have the final values
            assert metrics.total_depth == 1900  # 1000 + 9*100
            assert metrics.total_lag == 140  # 50 + 9*10
            assert metrics.last_check_ts > 0
        
        asyncio.run(check())
    
    def test_trim_counts_accumulate(self):
        """Trim counts accumulate over multiple operations."""
        trim_count = [0]
        
        async def mock_trim(stream: str, count: int) -> int:
            trim_count[0] += 1
            return count
        
        config = BacklogPolicyConfig(
            streams={
                "test_stream": StreamBacklogConfig(
                    stream_type=StreamType.MARKET_DATA,
                    soft_threshold=1000,
                    hard_threshold=5000,
                    protect_exit_signals=False,
                ),
            },
            enable_trimming=True,
        )
        
        policy = BacklogPolicy(
            config=config,
            trim_callback=mock_trim,
        )
        
        async def check():
            # Multiple hard tier checks should trigger multiple trims
            for _ in range(5):
                await policy.check_and_enforce(
                    stream_depths={"test_stream": 10000},
                    consumer_lags={},
                )
            
            metrics = policy.get_metrics()
            assert metrics.total_trimmed > 0
            assert trim_count[0] == 5
        
        asyncio.run(check())


class TestHighDepthZeroLag:
    """Test that high depth with zero lag is NOT overflow (when in soft tier)."""
    
    def test_high_depth_zero_lag_is_ok(self):
        """High depth (soft tier) with lag=0 should not trigger overflow."""
        redis = FakeRedisForResilience()
        telemetry = FakeTelemetry()
        
        config = HealthWorkerConfig(
            streams=["events:market_data"],
            track_consumer_lag=True,
            max_stream_depth=1000,  # Legacy threshold
            backlog_config=BacklogPolicyConfig(
                streams={
                    "events:market_data": StreamBacklogConfig(
                        soft_threshold=10000,  # 15000 is above soft
                        hard_threshold=30000,  # 15000 is below hard
                    ),
                },
                lag_soft_threshold=100,
                lag_hard_threshold=500,
            ),
        )
        
        worker = HealthWorker(
            redis_client=redis,
            telemetry=telemetry,
            telemetry_context=MagicMock(tenant_id="t1", bot_id="b1"),
            config=config,
        )
        
        async def check():
            # High depth (soft tier) but lag=0 (consumer is caught up)
            redis.set_depth("events:market_data", 15000)  # Above soft, below hard
            redis.set_lag("events:market_data", 0)
            
            await worker._emit_once()
            
            health_payloads = [p for n, p in telemetry.payloads if n == "health"]
            payload = health_payloads[-1]
            
            # Should NOT be overflow because lag=0 (soft tier with lag=0 is OK)
            assert payload["queue_overflow"] == False
            assert payload["status"] == "ok"
            assert payload.get("backlog_note") == "high_depth_but_caught_up"
        
        asyncio.run(check())
