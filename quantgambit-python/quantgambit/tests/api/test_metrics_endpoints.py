"""
API tests for Metrics Comparison endpoints.

Feature: trading-pipeline-integration
Requirements: 9.3 - THE System SHALL support side-by-side comparison reports
              showing live vs backtest metrics

Tests for:
- GET /api/metrics/compare endpoint
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from quantgambit.api.metrics_endpoints import (
    router,
    set_metrics_reconciler,
    get_metrics_reconciler,
    set_load_live_metrics_callback,
    set_load_backtest_metrics_callback,
    get_load_live_metrics_callback,
    get_load_backtest_metrics_callback,
    clear_metrics_state,
)
from quantgambit.integration.unified_metrics import (
    UnifiedMetrics,
    MetricsComparison,
    MetricsReconciler,
)


# Create a test app with just the metrics router
app = FastAPI()
app.include_router(router)
client = TestClient(app)


# =============================================================================
# Test Fixtures
# =============================================================================

@pytest.fixture(autouse=True)
def reset_metrics_state():
    """Reset metrics state before each test."""
    clear_metrics_state()
    yield
    clear_metrics_state()


@pytest.fixture
def sample_live_metrics():
    """Create sample live trading metrics."""
    return UnifiedMetrics(
        total_return_pct=15.5,
        annualized_return_pct=62.0,
        sharpe_ratio=1.8,
        sortino_ratio=2.5,
        max_drawdown_pct=8.2,
        max_drawdown_duration_sec=3600.0,
        total_trades=150,
        winning_trades=90,
        losing_trades=60,
        win_rate=0.6,
        profit_factor=1.8,
        avg_trade_pnl=25.0,
        avg_win_pct=2.5,
        avg_loss_pct=-1.5,
        avg_slippage_bps=1.2,
        avg_latency_ms=45.0,
        partial_fill_rate=0.05,
    )


@pytest.fixture
def sample_backtest_metrics():
    """Create sample backtest metrics."""
    return UnifiedMetrics(
        total_return_pct=18.0,
        annualized_return_pct=72.0,
        sharpe_ratio=2.1,
        sortino_ratio=3.0,
        max_drawdown_pct=6.5,
        max_drawdown_duration_sec=2400.0,
        total_trades=160,
        winning_trades=100,
        losing_trades=60,
        win_rate=0.625,
        profit_factor=2.0,
        avg_trade_pnl=30.0,
        avg_win_pct=2.8,
        avg_loss_pct=-1.4,
        avg_slippage_bps=0.8,
        avg_latency_ms=30.0,
        partial_fill_rate=0.02,
    )


@pytest.fixture
def metrics_reconciler():
    """Create a MetricsReconciler instance."""
    return MetricsReconciler(risk_free_rate=0.05)


@pytest.fixture
def configured_metrics_state(
    metrics_reconciler,
    sample_live_metrics,
    sample_backtest_metrics,
):
    """Configure metrics state with reconciler and data loaders."""
    set_metrics_reconciler(metrics_reconciler)
    
    async def load_live(period_hours: float) -> UnifiedMetrics:
        return sample_live_metrics
    
    async def load_backtest(run_id: str) -> UnifiedMetrics:
        if run_id == "not_found":
            return None
        return sample_backtest_metrics
    
    set_load_live_metrics_callback(load_live)
    set_load_backtest_metrics_callback(load_backtest)
    
    return {
        "reconciler": metrics_reconciler,
        "live_metrics": sample_live_metrics,
        "backtest_metrics": sample_backtest_metrics,
    }


# =============================================================================
# GET /api/metrics/compare Tests
# =============================================================================

class TestCompareMetrics:
    """Tests for GET /api/metrics/compare endpoint."""
    
    def test_returns_503_when_reconciler_not_configured(self):
        """Returns 503 when MetricsReconciler is not configured."""
        response = client.get("/api/metrics/compare?backtest_run_id=test_run")
        
        assert response.status_code == 503
        data = response.json()
        assert "Metrics comparison functionality is not enabled" in data["detail"]
    
    def test_returns_503_when_data_loaders_not_configured(self, metrics_reconciler):
        """Returns 503 when data loaders are not configured."""
        set_metrics_reconciler(metrics_reconciler)
        
        response = client.get("/api/metrics/compare?backtest_run_id=test_run")
        
        assert response.status_code == 503
        data = response.json()
        assert "Metrics data loaders are not configured" in data["detail"]
    
    def test_requires_backtest_run_id_parameter(self, configured_metrics_state):
        """Requires backtest_run_id query parameter."""
        response = client.get("/api/metrics/compare")
        
        assert response.status_code == 422  # Validation error
    
    def test_returns_comparison_with_valid_run_id(self, configured_metrics_state):
        """Returns comparison when valid backtest_run_id is provided."""
        response = client.get("/api/metrics/compare?backtest_run_id=test_run_123")
        
        assert response.status_code == 200
        data = response.json()
        
        # Verify response structure
        assert "live_metrics" in data
        assert "backtest_metrics" in data
        assert "significant_differences" in data
        assert "divergence_factors" in data
        assert "overall_similarity" in data
        assert "comparison_timestamp" in data
        assert "has_significant_differences" in data
        assert data["backtest_run_id"] == "test_run_123"
    
    def test_returns_404_when_backtest_not_found(self, configured_metrics_state):
        """Returns 404 when backtest run is not found."""
        response = client.get("/api/metrics/compare?backtest_run_id=not_found")
        
        assert response.status_code == 404
        data = response.json()
        assert "not found" in data["detail"].lower()
    
    def test_default_live_period_is_24_hours(self, configured_metrics_state):
        """Default live_period_hours is 24."""
        response = client.get("/api/metrics/compare?backtest_run_id=test_run")
        
        assert response.status_code == 200
        data = response.json()
        assert data["live_period_hours"] == 24.0
    
    def test_custom_live_period_hours(self, configured_metrics_state):
        """Accepts custom live_period_hours parameter."""
        response = client.get(
            "/api/metrics/compare?backtest_run_id=test_run&live_period_hours=48"
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["live_period_hours"] == 48.0
    
    def test_live_period_hours_min_validation(self, configured_metrics_state):
        """Validates minimum live_period_hours (0.1)."""
        response = client.get(
            "/api/metrics/compare?backtest_run_id=test_run&live_period_hours=0.05"
        )
        
        assert response.status_code == 422  # Validation error
    
    def test_live_period_hours_max_validation(self, configured_metrics_state):
        """Validates maximum live_period_hours (720 = 30 days)."""
        response = client.get(
            "/api/metrics/compare?backtest_run_id=test_run&live_period_hours=800"
        )
        
        assert response.status_code == 422  # Validation error
    
    def test_returns_live_metrics_fields(self, configured_metrics_state):
        """Returns all expected live metrics fields."""
        response = client.get("/api/metrics/compare?backtest_run_id=test_run")
        
        assert response.status_code == 200
        data = response.json()
        live = data["live_metrics"]
        
        # Return metrics
        assert "total_return_pct" in live
        assert "annualized_return_pct" in live
        
        # Risk metrics
        assert "sharpe_ratio" in live
        assert "sortino_ratio" in live
        assert "max_drawdown_pct" in live
        assert "max_drawdown_duration_sec" in live
        
        # Trade metrics
        assert "total_trades" in live
        assert "winning_trades" in live
        assert "losing_trades" in live
        assert "win_rate" in live
        assert "profit_factor" in live
        assert "avg_win_pct" in live
        assert "avg_loss_pct" in live
        
        # Execution metrics
        assert "avg_slippage_bps" in live
        assert "avg_latency_ms" in live
        assert "partial_fill_rate" in live
    
    def test_returns_backtest_metrics_fields(self, configured_metrics_state):
        """Returns all expected backtest metrics fields."""
        response = client.get("/api/metrics/compare?backtest_run_id=test_run")
        
        assert response.status_code == 200
        data = response.json()
        backtest = data["backtest_metrics"]
        
        # Verify same fields as live
        assert "total_return_pct" in backtest
        assert "sharpe_ratio" in backtest
        assert "total_trades" in backtest
        assert "win_rate" in backtest
        assert "avg_slippage_bps" in backtest
    
    def test_returns_significant_differences(self, configured_metrics_state):
        """Returns significant differences when metrics differ by >10%."""
        response = client.get("/api/metrics/compare?backtest_run_id=test_run")
        
        assert response.status_code == 200
        data = response.json()
        
        # Should have some significant differences based on fixture data
        sig_diffs = data["significant_differences"]
        assert isinstance(sig_diffs, dict)
        
        # Each difference should have expected fields
        for metric_name, diff_info in sig_diffs.items():
            assert "live" in diff_info
            assert "backtest" in diff_info
            assert "diff_pct" in diff_info
            assert "significant" in diff_info
            assert diff_info["significant"] is True
    
    def test_returns_divergence_factors(self, configured_metrics_state):
        """Returns divergence attribution factors."""
        response = client.get("/api/metrics/compare?backtest_run_id=test_run")
        
        assert response.status_code == 200
        data = response.json()
        
        factors = data["divergence_factors"]
        assert isinstance(factors, list)
        # Based on fixture data, should have some factors
        # (slippage diff, latency diff, etc.)
    
    def test_returns_overall_similarity(self, configured_metrics_state):
        """Returns overall similarity score between 0 and 1."""
        response = client.get("/api/metrics/compare?backtest_run_id=test_run")
        
        assert response.status_code == 200
        data = response.json()
        
        similarity = data["overall_similarity"]
        assert 0.0 <= similarity <= 1.0
    
    def test_returns_comparison_timestamp(self, configured_metrics_state):
        """Returns comparison timestamp in ISO format."""
        response = client.get("/api/metrics/compare?backtest_run_id=test_run")
        
        assert response.status_code == 200
        data = response.json()
        
        timestamp = data["comparison_timestamp"]
        # Should be parseable as ISO format
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        assert parsed is not None
    
    def test_returns_has_significant_differences_flag(self, configured_metrics_state):
        """Returns has_significant_differences boolean flag."""
        response = client.get("/api/metrics/compare?backtest_run_id=test_run")
        
        assert response.status_code == 200
        data = response.json()
        
        assert "has_significant_differences" in data
        assert isinstance(data["has_significant_differences"], bool)


class TestCompareMetricsWithIdenticalData:
    """Tests for comparison with identical metrics."""
    
    @pytest.fixture
    def identical_metrics_state(self, metrics_reconciler, sample_live_metrics):
        """Configure state where live and backtest metrics are identical."""
        set_metrics_reconciler(metrics_reconciler)
        
        async def load_live(period_hours: float) -> UnifiedMetrics:
            return sample_live_metrics
        
        async def load_backtest(run_id: str) -> UnifiedMetrics:
            # Return same metrics as live
            return sample_live_metrics
        
        set_load_live_metrics_callback(load_live)
        set_load_backtest_metrics_callback(load_backtest)
    
    def test_identical_metrics_have_no_significant_differences(
        self,
        identical_metrics_state,
    ):
        """Identical metrics should have no significant differences."""
        response = client.get("/api/metrics/compare?backtest_run_id=test_run")
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["significant_differences"] == {}
        assert data["has_significant_differences"] is False
    
    def test_identical_metrics_have_similarity_of_one(
        self,
        identical_metrics_state,
    ):
        """Identical metrics should have overall_similarity of 1.0."""
        response = client.get("/api/metrics/compare?backtest_run_id=test_run")
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["overall_similarity"] == 1.0


class TestCompareMetricsErrorHandling:
    """Tests for error handling in metrics comparison."""
    
    def test_handles_live_metrics_load_error(self, metrics_reconciler):
        """Handles errors when loading live metrics."""
        set_metrics_reconciler(metrics_reconciler)
        
        async def load_live_error(period_hours: float) -> UnifiedMetrics:
            raise RuntimeError("Database connection failed")
        
        async def load_backtest(run_id: str) -> UnifiedMetrics:
            return UnifiedMetrics()
        
        set_load_live_metrics_callback(load_live_error)
        set_load_backtest_metrics_callback(load_backtest)
        
        response = client.get("/api/metrics/compare?backtest_run_id=test_run")
        
        assert response.status_code == 500
        data = response.json()
        assert "Failed to load live metrics" in data["detail"]
    
    def test_handles_backtest_metrics_load_error(self, metrics_reconciler):
        """Handles errors when loading backtest metrics."""
        set_metrics_reconciler(metrics_reconciler)
        
        async def load_live(period_hours: float) -> UnifiedMetrics:
            return UnifiedMetrics()
        
        async def load_backtest_error(run_id: str) -> UnifiedMetrics:
            raise RuntimeError("Backtest data corrupted")
        
        set_load_live_metrics_callback(load_live)
        set_load_backtest_metrics_callback(load_backtest_error)
        
        response = client.get("/api/metrics/compare?backtest_run_id=test_run")
        
        assert response.status_code == 500
        data = response.json()
        assert "Failed to load backtest metrics" in data["detail"]
    
    def test_handles_no_live_data_available(self, metrics_reconciler):
        """Returns 400 when no live data is available."""
        set_metrics_reconciler(metrics_reconciler)
        
        async def load_live_none(period_hours: float) -> Optional[UnifiedMetrics]:
            return None
        
        async def load_backtest(run_id: str) -> UnifiedMetrics:
            return UnifiedMetrics()
        
        set_load_live_metrics_callback(load_live_none)
        set_load_backtest_metrics_callback(load_backtest)
        
        response = client.get("/api/metrics/compare?backtest_run_id=test_run")
        
        assert response.status_code == 400
        data = response.json()
        assert "No live trading data available" in data["detail"]


class TestCompareMetricsInfinityHandling:
    """Tests for handling infinity values in metrics."""
    
    @pytest.fixture
    def metrics_with_infinity(self, metrics_reconciler):
        """Configure state with metrics containing infinity values."""
        set_metrics_reconciler(metrics_reconciler)
        
        live = UnifiedMetrics(
            total_return_pct=10.0,
            sortino_ratio=float('inf'),  # No downside returns
            profit_factor=float('inf'),  # No losses
        )
        
        backtest = UnifiedMetrics(
            total_return_pct=12.0,
            sortino_ratio=float('inf'),
            profit_factor=float('inf'),
        )
        
        async def load_live(period_hours: float) -> UnifiedMetrics:
            return live
        
        async def load_backtest(run_id: str) -> UnifiedMetrics:
            return backtest
        
        set_load_live_metrics_callback(load_live)
        set_load_backtest_metrics_callback(load_backtest)
    
    def test_infinity_values_are_capped(self, metrics_with_infinity):
        """Infinity values are capped to 999.99 in response."""
        response = client.get("/api/metrics/compare?backtest_run_id=test_run")
        
        assert response.status_code == 200
        data = response.json()
        
        # Infinity should be converted to 999.99
        assert data["live_metrics"]["sortino_ratio"] == 999.99
        assert data["live_metrics"]["profit_factor"] == 999.99
        assert data["backtest_metrics"]["sortino_ratio"] == 999.99
        assert data["backtest_metrics"]["profit_factor"] == 999.99


# =============================================================================
# Module State Management Tests
# =============================================================================

class TestModuleState:
    """Tests for module-level state management functions."""
    
    def test_set_and_get_metrics_reconciler(self, metrics_reconciler):
        """Can set and get metrics reconciler."""
        assert get_metrics_reconciler() is None
        
        set_metrics_reconciler(metrics_reconciler)
        
        assert get_metrics_reconciler() is metrics_reconciler
    
    def test_set_and_get_live_metrics_callback(self):
        """Can set and get live metrics callback."""
        assert get_load_live_metrics_callback() is None
        
        async def callback(period_hours: float):
            return UnifiedMetrics()
        
        set_load_live_metrics_callback(callback)
        
        assert get_load_live_metrics_callback() is callback
    
    def test_set_and_get_backtest_metrics_callback(self):
        """Can set and get backtest metrics callback."""
        assert get_load_backtest_metrics_callback() is None
        
        async def callback(run_id: str):
            return UnifiedMetrics()
        
        set_load_backtest_metrics_callback(callback)
        
        assert get_load_backtest_metrics_callback() is callback
    
    def test_clear_metrics_state(self, metrics_reconciler):
        """clear_metrics_state clears all state."""
        set_metrics_reconciler(metrics_reconciler)
        set_load_live_metrics_callback(lambda x: None)
        set_load_backtest_metrics_callback(lambda x: None)
        
        clear_metrics_state()
        
        assert get_metrics_reconciler() is None
        assert get_load_live_metrics_callback() is None
        assert get_load_backtest_metrics_callback() is None
