"""
Unit tests for multi-timeframe orderflow persistence tracking.

Tests the new orderflow buffer system in FeaturePredictionWorker:
- Rolling imbalance buffers (1s, 5s, 30s)
- Persistence tracking (how long imbalance has been same sign)
"""

import pytest
from collections import deque

from quantgambit.signals.feature_worker import FeaturePredictionWorker, FeatureWorkerConfig


class MockRedisClient:
    """Mock Redis client for testing."""
    
    def __init__(self):
        self.redis = None
    
    async def create_group(self, stream, group):
        pass
    
    async def read_group(self, group, consumer, streams, block_ms=0):
        return []
    
    async def ack(self, stream, group, message_id):
        pass
    
    async def publish_event(self, stream, event):
        pass


class TestOrderflowPersistence:
    """Tests for orderflow persistence tracking."""
    
    @pytest.fixture
    def worker(self):
        """Create FeaturePredictionWorker for testing."""
        redis = MockRedisClient()
        worker = FeaturePredictionWorker(
            redis_client=redis,
            bot_id="test_bot",
            exchange="bybit",
            config=FeatureWorkerConfig(),
        )
        return worker
    
    def test_update_orderflow_buffers(self, worker):
        """Should update all orderflow buffers."""
        symbol = "BTCUSDT"
        ts = 1_000_000
        imb = 0.3
        
        worker._update_orderflow_buffers(symbol, ts, imb)
        
        assert symbol in worker._imb_buffer_1s
        assert symbol in worker._imb_buffer_5s
        assert symbol in worker._imb_buffer_30s
        assert len(worker._imb_buffer_1s[symbol]) == 1
        assert worker._imb_buffer_1s[symbol][0] == (ts, imb)
    
    def test_compute_rolling_imbalance_1s(self, worker):
        """Should compute 1-second rolling average."""
        symbol = "BTCUSDT"
        now = 2_000_000
        
        # Add samples: 0.3, 0.4, 0.5 over 0.5 seconds
        worker._update_orderflow_buffers(symbol, now - 400_000, 0.3)
        worker._update_orderflow_buffers(symbol, now - 200_000, 0.4)
        worker._update_orderflow_buffers(symbol, now, 0.5)
        
        avg = worker._compute_rolling_imbalance(symbol, now, 1.0)
        
        assert abs(avg - 0.4) < 0.01  # Average of 0.3, 0.4, 0.5
    
    def test_compute_rolling_imbalance_5s(self, worker):
        """Should compute 5-second rolling average."""
        symbol = "BTCUSDT"
        now = 3_000_000
        
        # Add samples over 4 seconds
        worker._update_orderflow_buffers(symbol, now - 3_000_000, 0.2)
        worker._update_orderflow_buffers(symbol, now - 2_000_000, 0.3)
        worker._update_orderflow_buffers(symbol, now - 1_000_000, 0.4)
        worker._update_orderflow_buffers(symbol, now, 0.5)
        
        avg = worker._compute_rolling_imbalance(symbol, now, 5.0)
        
        assert abs(avg - 0.35) < 0.01  # Average of 0.2, 0.3, 0.4, 0.5
    
    def test_compute_rolling_imbalance_excludes_old(self, worker):
        """Should exclude samples older than horizon."""
        symbol = "BTCUSDT"
        now = 4_000_000
        
        # Add old sample (6 seconds ago) and recent samples
        worker._update_orderflow_buffers(symbol, now - 6_000_000, -0.5)  # Should be excluded
        worker._update_orderflow_buffers(symbol, now - 2_000_000, 0.3)
        worker._update_orderflow_buffers(symbol, now, 0.5)
        
        avg = worker._compute_rolling_imbalance(symbol, now, 5.0)
        
        assert abs(avg - 0.4) < 0.01  # Average of 0.3, 0.5 only
    
    def test_compute_persistence_positive(self, worker):
        """Should track persistence of positive imbalance."""
        symbol = "BTCUSDT"
        now = 5_000_000
        
        # Add positive imbalances over 3 seconds
        worker._update_orderflow_buffers(symbol, now - 3_000_000, 0.2)
        worker._update_orderflow_buffers(symbol, now - 2_000_000, 0.3)
        worker._update_orderflow_buffers(symbol, now - 1_000_000, 0.4)
        worker._update_orderflow_buffers(symbol, now, 0.5)
        
        persistence = worker._compute_orderflow_persistence(symbol, now)
        
        assert persistence >= 3.0  # At least 3 seconds of same sign
    
    def test_compute_persistence_sign_change(self, worker):
        """Persistence should reset on sign change."""
        symbol = "BTCUSDT"
        now = 6_000_000
        
        # Positive, then negative
        worker._update_orderflow_buffers(symbol, now - 3_000_000, 0.3)
        worker._update_orderflow_buffers(symbol, now - 2_000_000, -0.2)  # Sign change
        worker._update_orderflow_buffers(symbol, now - 1_000_000, -0.3)
        worker._update_orderflow_buffers(symbol, now, -0.4)
        
        persistence = worker._compute_orderflow_persistence(symbol, now)
        
        # Should only count since sign change
        assert persistence < 2.5
        assert persistence >= 2.0
    
    def test_get_multi_timeframe_orderflow(self, worker):
        """Should return all orderflow metrics."""
        symbol = "BTCUSDT"
        now = 7_000_000
        
        # Add samples
        worker._update_orderflow_buffers(symbol, now - 2_000_000, 0.2)
        worker._update_orderflow_buffers(symbol, now - 1_000_000, 0.3)
        
        imb_1s, imb_5s, imb_30s, persistence = worker._get_multi_timeframe_orderflow(
            symbol, now, 0.4
        )
        
        # All values should be computed
        assert imb_1s != 0.0  # Most recent value
        assert imb_5s != 0.0  # Average over 5s
        assert imb_30s != 0.0  # Average over 30s
        assert persistence >= 0.0
    
    def test_buffers_have_max_length(self, worker):
        """Buffers should not grow unbounded."""
        symbol = "BTCUSDT"
        now = 8_000_000
        
        # Add many samples
        for i in range(200):
            worker._update_orderflow_buffers(symbol, now + i * 10_000, 0.1)
        
        # Buffers should be bounded
        assert len(worker._imb_buffer_1s[symbol]) <= 100
        assert len(worker._imb_buffer_5s[symbol]) <= 500
        assert len(worker._imb_buffer_30s[symbol]) <= 3000
    
    def test_empty_buffer_returns_zero(self, worker):
        """Should return 0 for empty buffers."""
        symbol = "NONEXISTENT"
        now = 9_000_000
        
        avg = worker._compute_rolling_imbalance(symbol, now, 5.0)
        persistence = worker._compute_orderflow_persistence(symbol, now)
        
        assert avg == 0.0
        assert persistence == 0.0
    
    def test_zero_imbalance_persistence(self, worker):
        """Zero imbalance should return 0 persistence."""
        symbol = "BTCUSDT"
        now = 10_000_000
        
        # Add zero imbalances
        worker._update_orderflow_buffers(symbol, now - 1_000_000, 0.0)
        worker._update_orderflow_buffers(symbol, now, 0.0)
        
        persistence = worker._compute_orderflow_persistence(symbol, now)
        
        assert persistence == 0.0


class TestOrderflowIntegration:
    """Integration tests for orderflow in feature snapshots."""
    
    @pytest.fixture
    def worker(self):
        """Create FeaturePredictionWorker for testing."""
        redis = MockRedisClient()
        worker = FeaturePredictionWorker(
            redis_client=redis,
            bot_id="test_bot",
            exchange="bybit",
            config=FeatureWorkerConfig(),
        )
        return worker
    
    def test_multi_timeframe_different_horizons(self, worker):
        """Different horizons should give different averages."""
        symbol = "BTCUSDT"
        now = 20_000_000
        
        # Add varying imbalances over 35 seconds
        # Recent: positive, Old: negative
        worker._update_orderflow_buffers(symbol, now - 35_000_000, -0.5)
        worker._update_orderflow_buffers(symbol, now - 25_000_000, -0.4)
        worker._update_orderflow_buffers(symbol, now - 15_000_000, -0.2)
        worker._update_orderflow_buffers(symbol, now - 8_000_000, 0.1)
        worker._update_orderflow_buffers(symbol, now - 3_000_000, 0.3)
        worker._update_orderflow_buffers(symbol, now - 1_000_000, 0.5)
        worker._update_orderflow_buffers(symbol, now, 0.6)
        
        imb_1s = worker._compute_rolling_imbalance(symbol, now, 1.0)
        imb_5s = worker._compute_rolling_imbalance(symbol, now, 5.0)
        imb_30s = worker._compute_rolling_imbalance(symbol, now, 30.0)
        
        # 1s should be most positive (recent values)
        # 30s should include negative values from earlier
        assert imb_1s > imb_5s
        assert imb_5s > imb_30s
        assert imb_1s > 0  # Recent is positive
