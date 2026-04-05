"""
API tests for Strategy Diagnostics endpoints.

Tests for /api/v1/diagnostics/strategies endpoint as specified in Requirement 7.11.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from quantgambit.api.diagnostics_endpoints import router
from quantgambit.signals.services.strategy_diagnostics import (
    get_strategy_diagnostics,
    reset_strategy_diagnostics,
)


# Create a test app with just the diagnostics router
from fastapi import FastAPI

app = FastAPI()
app.include_router(router)
client = TestClient(app)


@pytest.fixture(autouse=True)
def reset_diagnostics():
    """Reset diagnostics before each test."""
    reset_strategy_diagnostics()
    yield
    reset_strategy_diagnostics()


# =============================================================================
# GET /api/v1/diagnostics/strategies Tests
# =============================================================================

class TestGetStrategiesEndpoint:
    """Tests for GET /api/v1/diagnostics/strategies endpoint."""
    
    def test_returns_empty_when_no_strategies(self):
        """Returns empty list when no strategies have been recorded."""
        response = client.get("/api/v1/diagnostics/strategies")
        
        assert response.status_code == 200
        data = response.json()
        assert data["strategies"] == []
        assert data["aggregate"]["total_ticks"] == 0
    
    def test_returns_strategy_metrics(self):
        """Returns metrics for recorded strategies."""
        diagnostics = get_strategy_diagnostics()
        diagnostics.record_tick("test_strategy")
        diagnostics.record_setup("test_strategy")
        
        response = client.get("/api/v1/diagnostics/strategies")
        
        assert response.status_code == 200
        data = response.json()
        assert len(data["strategies"]) == 1
        assert data["strategies"][0]["strategy_id"] == "test_strategy"
        assert data["strategies"][0]["tick_count"] == 1
        assert data["strategies"][0]["setup_count"] == 1
    
    def test_returns_multiple_strategies(self):
        """Returns metrics for multiple strategies."""
        diagnostics = get_strategy_diagnostics()
        diagnostics.record_tick("strategy_a")
        diagnostics.record_tick("strategy_b")
        diagnostics.record_tick("strategy_c")
        
        response = client.get("/api/v1/diagnostics/strategies")
        
        assert response.status_code == 200
        data = response.json()
        assert len(data["strategies"]) == 3
    
    def test_filter_by_strategy_id(self):
        """Filters by strategy_id when provided."""
        diagnostics = get_strategy_diagnostics()
        diagnostics.record_tick("strategy_a")
        diagnostics.record_tick("strategy_b")
        
        response = client.get("/api/v1/diagnostics/strategies?strategy_id=strategy_a")
        
        assert response.status_code == 200
        data = response.json()
        assert len(data["strategies"]) == 1
        assert data["strategies"][0]["strategy_id"] == "strategy_a"
    
    def test_filter_by_unknown_strategy_returns_404(self):
        """Returns 404 when filtering by unknown strategy."""
        response = client.get("/api/v1/diagnostics/strategies?strategy_id=unknown")
        
        assert response.status_code == 404
    
    def test_includes_rates(self):
        """Response includes rate calculations."""
        diagnostics = get_strategy_diagnostics()
        for _ in range(100):
            diagnostics.record_tick("test_strategy")
        for _ in range(10):
            diagnostics.record_setup("test_strategy")
        
        response = client.get("/api/v1/diagnostics/strategies")
        
        assert response.status_code == 200
        data = response.json()
        assert data["strategies"][0]["setup_rate"] == 0.1
    
    def test_includes_failure_breakdown(self):
        """Response includes failure breakdown (Requirement 7.12)."""
        diagnostics = get_strategy_diagnostics()
        diagnostics.record_tick("test_strategy")
        diagnostics.record_predicate_failure("test_strategy", "fail_flow")
        diagnostics.record_predicate_failure("test_strategy", "fail_flow")
        diagnostics.record_predicate_failure("test_strategy", "fail_trend")
        
        response = client.get("/api/v1/diagnostics/strategies")
        
        assert response.status_code == 200
        data = response.json()
        breakdown = data["strategies"][0]["failure_breakdown"]
        assert breakdown["fail_flow"] == 2
        assert breakdown["fail_trend"] == 1
    
    def test_includes_top_failures(self):
        """Response includes top failures."""
        diagnostics = get_strategy_diagnostics()
        diagnostics.record_tick("test_strategy")
        diagnostics.record_predicate_failure("test_strategy", "fail_flow")
        diagnostics.record_predicate_failure("test_strategy", "fail_flow")
        diagnostics.record_predicate_failure("test_strategy", "fail_trend")
        
        response = client.get("/api/v1/diagnostics/strategies")
        
        assert response.status_code == 200
        data = response.json()
        top_failures = data["strategies"][0]["top_failures"]
        assert len(top_failures) > 0
        assert top_failures[0]["type"] == "fail_flow"
        assert top_failures[0]["count"] == 2
    
    def test_includes_bottleneck(self):
        """Response includes bottleneck identification (Requirement 7.8)."""
        diagnostics = get_strategy_diagnostics()
        diagnostics.record_tick("test_strategy")
        # No setups, so bottleneck should be "setup"
        
        response = client.get("/api/v1/diagnostics/strategies")
        
        assert response.status_code == 200
        data = response.json()
        assert data["strategies"][0]["bottleneck"] == "setup"
    
    def test_includes_aggregate_metrics(self):
        """Response includes aggregate metrics (Requirement 7.12)."""
        diagnostics = get_strategy_diagnostics()
        diagnostics.record_tick("strategy_a")
        diagnostics.record_tick("strategy_a")
        diagnostics.record_tick("strategy_b")
        diagnostics.record_setup("strategy_a")
        
        response = client.get("/api/v1/diagnostics/strategies")
        
        assert response.status_code == 200
        data = response.json()
        assert data["aggregate"]["total_ticks"] == 3
        assert data["aggregate"]["total_setups"] == 1


# =============================================================================
# GET /api/v1/diagnostics/strategies/{strategy_id}/bottleneck Tests
# =============================================================================

class TestGetBottleneckEndpoint:
    """Tests for GET /api/v1/diagnostics/strategies/{strategy_id}/bottleneck endpoint."""
    
    def test_returns_bottleneck_for_strategy(self):
        """Returns bottleneck stage for a strategy."""
        diagnostics = get_strategy_diagnostics()
        diagnostics.record_tick("test_strategy")
        
        response = client.get("/api/v1/diagnostics/strategies/test_strategy/bottleneck")
        
        assert response.status_code == 200
        data = response.json()
        assert data["strategy_id"] == "test_strategy"
        assert data["bottleneck"] == "setup"
    
    def test_returns_404_for_unknown_strategy(self):
        """Returns 404 for unknown strategy."""
        response = client.get("/api/v1/diagnostics/strategies/unknown/bottleneck")
        
        assert response.status_code == 404


# =============================================================================
# GET /api/v1/diagnostics/strategies/{strategy_id}/failures Tests
# =============================================================================

class TestGetFailuresEndpoint:
    """Tests for GET /api/v1/diagnostics/strategies/{strategy_id}/failures endpoint."""
    
    def test_returns_failure_breakdown(self):
        """Returns failure breakdown for a strategy."""
        diagnostics = get_strategy_diagnostics()
        diagnostics.record_tick("test_strategy")
        diagnostics.record_predicate_failure("test_strategy", "fail_flow")
        diagnostics.record_predicate_failure("test_strategy", "fail_trend")
        
        response = client.get("/api/v1/diagnostics/strategies/test_strategy/failures")
        
        assert response.status_code == 200
        data = response.json()
        assert data["strategy_id"] == "test_strategy"
        assert data["breakdown"]["fail_flow"] == 1
        assert data["breakdown"]["fail_trend"] == 1
    
    def test_returns_top_failures(self):
        """Returns top failures sorted by count."""
        diagnostics = get_strategy_diagnostics()
        diagnostics.record_tick("test_strategy")
        diagnostics.record_predicate_failure("test_strategy", "fail_flow")
        diagnostics.record_predicate_failure("test_strategy", "fail_flow")
        diagnostics.record_predicate_failure("test_strategy", "fail_trend")
        
        response = client.get("/api/v1/diagnostics/strategies/test_strategy/failures")
        
        assert response.status_code == 200
        data = response.json()
        assert len(data["top_failures"]) > 0
        assert data["top_failures"][0]["type"] == "fail_flow"
        assert data["top_failures"][0]["count"] == 2
    
    def test_top_n_parameter(self):
        """Respects top_n parameter."""
        diagnostics = get_strategy_diagnostics()
        diagnostics.record_tick("test_strategy")
        diagnostics.record_predicate_failure("test_strategy", "fail_flow")
        diagnostics.record_predicate_failure("test_strategy", "fail_trend")
        diagnostics.record_predicate_failure("test_strategy", "fail_ev")
        diagnostics.record_predicate_failure("test_strategy", "fail_cost")
        diagnostics.record_predicate_failure("test_strategy", "fail_data")
        
        response = client.get("/api/v1/diagnostics/strategies/test_strategy/failures?top_n=2")
        
        assert response.status_code == 200
        data = response.json()
        # All have count 1, so we just check we get at most 2
        assert len(data["top_failures"]) <= 2
    
    def test_returns_404_for_unknown_strategy(self):
        """Returns 404 for unknown strategy."""
        response = client.get("/api/v1/diagnostics/strategies/unknown/failures")
        
        assert response.status_code == 404
