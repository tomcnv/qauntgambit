"""
Tests for EV Gate API endpoints.

Requirements: 7.2, 7.3, 7.4, Non-functional observability
"""

import pytest
import time
from unittest.mock import AsyncMock, MagicMock, patch

from quantgambit.api.ev_gate_endpoints import (
    EVGateMetricsCollector,
    EVGateDecisionLog,
    EVGateDecisionResponse,
    EVGateAggregateMetrics,
    EVGateRejectCounters,
    EVGateAcceptanceByDimension,
    get_metrics_collector,
)


class TestEVGateMetricsCollector:
    """Tests for EVGateMetricsCollector."""
    
    def test_record_decision_accept(self):
        """Test recording an accepted decision."""
        collector = EVGateMetricsCollector()
        
        log = EVGateDecisionLog(
            timestamp=time.time(),
            symbol="BTCUSDT",
            signal_id="test-1",
            decision="ACCEPT",
            p_calibrated=0.65,
            p_min=0.55,
            R=1.5,
            C=0.1,
            EV=0.05,
        )
        
        collector.record_decision(log)
        
        assert collector._accepts_total == 1
        assert collector._rejects_total == 0
        assert len(collector._decisions) == 1
    
    def test_record_decision_reject(self):
        """Test recording a rejected decision."""
        collector = EVGateMetricsCollector()
        
        log = EVGateDecisionLog(
            timestamp=time.time(),
            symbol="BTCUSDT",
            signal_id="test-1",
            decision="REJECT",
            reject_code="EV_BELOW_MIN",
            reject_reason="EV below threshold",
            p_calibrated=0.45,
            p_min=0.55,
            R=1.5,
            C=0.1,
            EV=-0.02,
        )
        
        collector.record_decision(log)
        
        assert collector._accepts_total == 0
        assert collector._rejects_total == 1
        assert collector._rejects_by_code["EV_BELOW_MIN"] == 1
    
    def test_get_decisions_with_filters(self):
        """Test getting decisions with filters."""
        collector = EVGateMetricsCollector()
        
        # Add some decisions
        for i in range(5):
            log = EVGateDecisionLog(
                timestamp=time.time(),
                symbol="BTCUSDT" if i % 2 == 0 else "ETHUSDT",
                signal_id=f"test-{i}",
                decision="ACCEPT" if i % 2 == 0 else "REJECT",
                regime_label="trending" if i < 3 else "ranging",
            )
            collector.record_decision(log)
        
        # Filter by symbol
        btc_decisions, total = collector.get_decisions(symbol="BTCUSDT")
        assert len(btc_decisions) == 3
        
        # Filter by decision
        accepts, total = collector.get_decisions(decision="ACCEPT")
        assert len(accepts) == 3
        
        # Filter by regime
        trending, total = collector.get_decisions(regime="trending")
        assert len(trending) == 3
    
    def test_get_aggregate_metrics(self):
        """Test computing aggregate metrics."""
        collector = EVGateMetricsCollector()
        
        # Add some decisions
        for i in range(10):
            log = EVGateDecisionLog(
                timestamp=time.time(),
                symbol="BTCUSDT",
                signal_id=f"test-{i}",
                decision="ACCEPT" if i < 7 else "REJECT",
                R=1.5,
                C=0.1,
                EV=0.05 if i < 7 else -0.02,
            )
            collector.record_decision(log)
        
        metrics = collector.get_aggregate_metrics(period_hours=24.0)
        
        assert metrics.total_decisions == 10
        assert metrics.total_accepts == 7
        assert metrics.total_rejects == 3
        assert metrics.acceptance_rate == 0.7
        assert metrics.gross_EV == pytest.approx(0.35, rel=0.01)
    
    def test_get_reject_counters(self):
        """Test getting reject counters."""
        collector = EVGateMetricsCollector()
        
        # Add some rejections
        codes = ["EV_BELOW_MIN", "EV_BELOW_MIN", "INVALID_R", "STALE_BOOK"]
        for i, code in enumerate(codes):
            log = EVGateDecisionLog(
                timestamp=time.time(),
                symbol="BTCUSDT" if i < 2 else "ETHUSDT",
                signal_id=f"test-{i}",
                decision="REJECT",
                reject_code=code,
                regime_label="trending",
                session="us",
            )
            collector.record_decision(log)
        
        counters = collector.get_reject_counters(period_hours=24.0)
        
        assert counters.total_rejects == 4
        assert counters.by_code["EV_BELOW_MIN"] == 2
        assert counters.by_code["INVALID_R"] == 1
        assert counters.by_code["STALE_BOOK"] == 1
        assert counters.by_symbol["BTCUSDT"] == 2
        assert counters.by_symbol["ETHUSDT"] == 2
    
    def test_get_acceptance_by_dimension(self):
        """Test getting acceptance rate by dimension."""
        collector = EVGateMetricsCollector()
        
        # Add decisions for different dimensions
        for i in range(10):
            log = EVGateDecisionLog(
                timestamp=time.time(),
                symbol="BTCUSDT" if i < 6 else "ETHUSDT",
                signal_id=f"test-{i}",
                decision="ACCEPT" if i % 2 == 0 else "REJECT",
                strategy_id="scalper" if i < 5 else "swing",
                regime_label="trending",
                session="us",
            )
            collector.record_decision(log)
        
        acceptance = collector.get_acceptance_by_dimension(period_hours=24.0)
        
        assert "BTCUSDT" in acceptance.by_symbol
        assert "ETHUSDT" in acceptance.by_symbol
        assert "scalper" in acceptance.by_strategy
        assert "swing" in acceptance.by_strategy
    
    def test_get_prometheus_metrics(self):
        """Test generating Prometheus metrics."""
        collector = EVGateMetricsCollector()
        
        # Add some decisions
        for i in range(5):
            log = EVGateDecisionLog(
                timestamp=time.time(),
                symbol="BTCUSDT",
                signal_id=f"test-{i}",
                decision="ACCEPT" if i < 3 else "REJECT",
                reject_code="EV_BELOW_MIN" if i >= 3 else None,
            )
            collector.record_decision(log)
        
        metrics = collector.get_prometheus_metrics()
        
        assert "ev_gate_accepts_total 3" in metrics
        assert "ev_gate_rejects_total 2" in metrics
        assert 'ev_gate_rejects_by_code{code="EV_BELOW_MIN"} 2' in metrics
        assert "ev_gate_decisions_total 5" in metrics
        assert "ev_gate_acceptance_rate" in metrics
    
    def test_cleanup_old_decisions(self):
        """Test that old decisions are cleaned up."""
        collector = EVGateMetricsCollector()
        collector.RETENTION_SECONDS = 1  # 1 second for testing
        
        # Add an old decision
        old_log = EVGateDecisionLog(
            timestamp=time.time() - 2,  # 2 seconds ago
            symbol="BTCUSDT",
            signal_id="old",
            decision="ACCEPT",
        )
        collector._decisions.append(old_log)
        
        # Add a new decision
        new_log = EVGateDecisionLog(
            timestamp=time.time(),
            symbol="BTCUSDT",
            signal_id="new",
            decision="ACCEPT",
        )
        collector.record_decision(new_log)
        
        # Force cleanup
        collector._cleanup_old_decisions()
        
        # Only new decision should remain
        assert len(collector._decisions) == 1
        assert collector._decisions[0].signal_id == "new"


class TestEVGateDecisionLog:
    """Tests for EVGateDecisionLog dataclass."""
    
    def test_to_dict(self):
        """Test converting decision log to dictionary."""
        log = EVGateDecisionLog(
            timestamp=1234567890.0,
            symbol="BTCUSDT",
            signal_id="test-1",
            decision="ACCEPT",
            p_calibrated=0.65,
            R=1.5,
            C=0.1,
            EV=0.05,
        )
        
        d = log.to_dict()
        
        assert d["timestamp"] == 1234567890.0
        assert d["symbol"] == "BTCUSDT"
        assert d["decision"] == "ACCEPT"
        assert d["p_calibrated"] == 0.65
        assert d["R"] == 1.5


class TestGlobalMetricsCollector:
    """Tests for global metrics collector singleton."""
    
    def test_get_metrics_collector_singleton(self):
        """Test that get_metrics_collector returns the same instance."""
        collector1 = get_metrics_collector()
        collector2 = get_metrics_collector()
        
        assert collector1 is collector2


@pytest.mark.asyncio
class TestEVGateAPIEndpoints:
    """Integration tests for EV gate API endpoints."""
    
    async def test_decisions_endpoint(self):
        """Test the decisions endpoint returns correct format."""
        from fastapi.testclient import TestClient
        from quantgambit.api.ev_gate_endpoints import router
        from fastapi import FastAPI
        
        app = FastAPI()
        app.include_router(router)
        
        # Add some test data
        collector = get_metrics_collector()
        log = EVGateDecisionLog(
            timestamp=time.time(),
            symbol="BTCUSDT",
            signal_id="test-api",
            decision="ACCEPT",
            p_calibrated=0.65,
            R=1.5,
            C=0.1,
            EV=0.05,
        )
        collector.record_decision(log)
        
        client = TestClient(app)
        
        # Mock Redis to return empty (fall back to in-memory)
        with patch('quantgambit.api.ev_gate_endpoints.get_redis_client') as mock_redis:
            mock_client = AsyncMock()
            mock_client.xrevrange = AsyncMock(return_value=[])
            mock_redis.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_redis.return_value.__aexit__ = AsyncMock(return_value=None)
            
            response = client.get(
                "/api/v1/ev-gate/decisions",
                params={"tenant_id": "test", "bot_id": "test"}
            )
        
        assert response.status_code == 200
        data = response.json()
        assert "decisions" in data
        assert "total" in data
    
    async def test_metrics_endpoint(self):
        """Test the metrics endpoint returns correct format."""
        from fastapi.testclient import TestClient
        from quantgambit.api.ev_gate_endpoints import router
        from fastapi import FastAPI
        
        app = FastAPI()
        app.include_router(router)
        
        client = TestClient(app)
        
        with patch('quantgambit.api.ev_gate_endpoints.get_redis_client') as mock_redis:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=None)
            mock_redis.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_redis.return_value.__aexit__ = AsyncMock(return_value=None)
            
            response = client.get(
                "/api/v1/ev-gate/metrics",
                params={"tenant_id": "test", "bot_id": "test"}
            )
        
        assert response.status_code == 200
        data = response.json()
        assert "trades_per_day" in data
        assert "acceptance_rate" in data
    
    async def test_prometheus_endpoint(self):
        """Test the Prometheus metrics endpoint."""
        from fastapi.testclient import TestClient
        from quantgambit.api.ev_gate_endpoints import router
        from fastapi import FastAPI
        
        app = FastAPI()
        app.include_router(router)
        
        client = TestClient(app)
        
        response = client.get(
            "/api/v1/ev-gate/prometheus",
            params={"tenant_id": "test", "bot_id": "test"}
        )
        
        assert response.status_code == 200
        assert "ev_gate_accepts_total" in response.text
        assert "ev_gate_rejects_total" in response.text
    
    async def test_health_endpoint(self):
        """Test the health check endpoint."""
        from fastapi.testclient import TestClient
        from quantgambit.api.ev_gate_endpoints import router
        from fastapi import FastAPI
        
        app = FastAPI()
        app.include_router(router)
        
        client = TestClient(app)
        
        response = client.get("/api/v1/ev-gate/health")
        
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "accepts_total" in data
        assert "rejects_total" in data
