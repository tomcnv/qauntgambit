"""
API tests for Shadow Comparison endpoints.

Feature: trading-pipeline-integration
Requirements: 4.5 - THE System SHALL expose shadow comparison metrics via API
              (agreement rate, divergence reasons, P&L difference)

Tests for:
- GET /api/shadow/metrics endpoint
- GET /api/shadow/comparisons endpoint with filters
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from quantgambit.api.shadow_endpoints import (
    router,
    set_shadow_comparator,
    get_shadow_comparator,
    store_comparison_result,
    clear_comparison_results,
    get_stored_comparisons,
)
from quantgambit.integration.shadow_comparison import (
    ComparisonResult,
    ComparisonMetrics,
    ShadowComparator,
)


# Create a test app with just the shadow router
app = FastAPI()
app.include_router(router)
client = TestClient(app)


# =============================================================================
# Mock ShadowComparator for testing
# =============================================================================

class MockShadowComparator:
    """Mock ShadowComparator for testing API endpoints."""
    
    def __init__(
        self,
        total_comparisons: int = 100,
        agreements: int = 80,
        divergence_by_reason: Optional[Dict[str, int]] = None,
        live_pnl: float = 1000.0,
        shadow_pnl: float = 1200.0,
    ):
        self._total = total_comparisons
        self._agreements = agreements
        self._divergence_by_reason = divergence_by_reason or {}
        self._live_pnl = live_pnl
        self._shadow_pnl = shadow_pnl
    
    def get_metrics(self) -> ComparisonMetrics:
        """Return mock metrics."""
        disagreements = self._total - self._agreements
        agreement_rate = self._agreements / self._total if self._total > 0 else 1.0
        
        return ComparisonMetrics(
            total_comparisons=self._total,
            agreements=self._agreements,
            disagreements=disagreements,
            agreement_rate=agreement_rate,
            divergence_by_reason=self._divergence_by_reason,
            live_pnl_estimate=self._live_pnl,
            shadow_pnl_estimate=self._shadow_pnl,
        )


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture(autouse=True)
def reset_shadow_state():
    """Reset shadow comparator and stored comparisons before each test."""
    set_shadow_comparator(None)
    clear_comparison_results()
    yield
    set_shadow_comparator(None)
    clear_comparison_results()


@pytest.fixture
def mock_comparator():
    """Create a mock shadow comparator."""
    return MockShadowComparator()


@pytest.fixture
def mock_comparator_with_divergences():
    """Create a mock shadow comparator with divergence data."""
    return MockShadowComparator(
        total_comparisons=100,
        agreements=75,
        divergence_by_reason={
            "stage_diff:ev_gatevsdata_readiness": 10,
            "profile_diff:scalp_longvstrend_follow": 8,
            "unknown": 7,
        },
        live_pnl=1000.0,
        shadow_pnl=1500.0,
    )


@pytest.fixture
def sample_comparisons():
    """Create sample comparison results for testing."""
    base_time = datetime.now(timezone.utc)
    
    return [
        ComparisonResult.create(
            timestamp=base_time - timedelta(minutes=i),
            symbol="BTCUSDT" if i % 2 == 0 else "ETHUSDT",
            live_decision="accepted" if i % 3 == 0 else "rejected",
            shadow_decision="accepted" if i % 3 == 0 else "rejected",
            divergence_reason=None if i % 3 == 0 else f"stage_diff:stage_{i}",
            live_rejection_stage=None if i % 3 == 0 else f"stage_{i}",
            shadow_rejection_stage=None if i % 3 == 0 else f"stage_{i}",
        )
        for i in range(20)
    ]


# =============================================================================
# GET /api/shadow/metrics Tests
# =============================================================================

class TestGetShadowMetrics:
    """Tests for GET /api/shadow/metrics endpoint."""
    
    def test_returns_503_when_shadow_mode_disabled(self):
        """Returns 503 when shadow mode is not enabled."""
        response = client.get("/api/shadow/metrics")
        
        assert response.status_code == 503
        data = response.json()
        assert "Shadow mode is not enabled" in data["detail"]
    
    def test_returns_metrics_when_enabled(self, mock_comparator):
        """Returns metrics when shadow mode is enabled."""
        set_shadow_comparator(mock_comparator)
        
        response = client.get("/api/shadow/metrics")
        
        assert response.status_code == 200
        data = response.json()
        assert data["total_comparisons"] == 100
        assert data["agreements"] == 80
        assert data["disagreements"] == 20
        assert data["agreement_rate"] == 0.8
        assert abs(data["divergence_rate"] - 0.2) < 0.001  # Float comparison
    
    def test_returns_pnl_estimates(self, mock_comparator):
        """Returns P&L estimates in metrics."""
        set_shadow_comparator(mock_comparator)
        
        response = client.get("/api/shadow/metrics")
        
        assert response.status_code == 200
        data = response.json()
        assert data["live_pnl_estimate"] == 1000.0
        assert data["shadow_pnl_estimate"] == 1200.0
        assert data["pnl_difference"] == 200.0
    
    def test_returns_divergence_breakdown(self, mock_comparator_with_divergences):
        """Returns divergence breakdown by reason."""
        set_shadow_comparator(mock_comparator_with_divergences)
        
        response = client.get("/api/shadow/metrics")
        
        assert response.status_code == 200
        data = response.json()
        assert "divergence_by_reason" in data
        assert data["divergence_by_reason"]["stage_diff:ev_gatevsdata_readiness"] == 10
        assert data["divergence_by_reason"]["profile_diff:scalp_longvstrend_follow"] == 8
    
    def test_returns_top_divergence_reasons(self, mock_comparator_with_divergences):
        """Returns top divergence reasons sorted by count."""
        set_shadow_comparator(mock_comparator_with_divergences)
        
        response = client.get("/api/shadow/metrics")
        
        assert response.status_code == 200
        data = response.json()
        assert "top_divergence_reasons" in data
        top_reasons = data["top_divergence_reasons"]
        assert len(top_reasons) > 0
        # Should be sorted by count descending
        assert top_reasons[0]["reason"] == "stage_diff:ev_gatevsdata_readiness"
        assert top_reasons[0]["count"] == 10
    
    def test_returns_alert_threshold_status(self, mock_comparator_with_divergences):
        """Returns whether divergence exceeds alert threshold."""
        set_shadow_comparator(mock_comparator_with_divergences)
        
        response = client.get("/api/shadow/metrics")
        
        assert response.status_code == 200
        data = response.json()
        # 25% divergence exceeds 20% threshold
        assert data["exceeds_alert_threshold"] is True
    
    def test_alert_threshold_false_when_below(self, mock_comparator):
        """Alert threshold is false when divergence is below threshold."""
        set_shadow_comparator(mock_comparator)
        
        response = client.get("/api/shadow/metrics")
        
        assert response.status_code == 200
        data = response.json()
        # 20% divergence does not exceed 20% threshold (must be >)
        assert data["exceeds_alert_threshold"] is False


# =============================================================================
# GET /api/shadow/comparisons Tests
# =============================================================================

class TestGetShadowComparisons:
    """Tests for GET /api/shadow/comparisons endpoint."""
    
    def test_returns_503_when_shadow_mode_disabled(self):
        """Returns 503 when shadow mode is not enabled."""
        response = client.get("/api/shadow/comparisons")
        
        assert response.status_code == 503
        data = response.json()
        assert "Shadow mode is not enabled" in data["detail"]
    
    def test_returns_empty_list_when_no_comparisons(self, mock_comparator):
        """Returns empty list when no comparisons stored."""
        set_shadow_comparator(mock_comparator)
        
        response = client.get("/api/shadow/comparisons")
        
        assert response.status_code == 200
        data = response.json()
        assert data["comparisons"] == []
        assert data["total"] == 0
        assert data["filtered"] == 0
    
    def test_returns_stored_comparisons(self, mock_comparator, sample_comparisons):
        """Returns stored comparison results."""
        set_shadow_comparator(mock_comparator)
        for comp in sample_comparisons:
            store_comparison_result(comp)
        
        response = client.get("/api/shadow/comparisons")
        
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 20
        assert len(data["comparisons"]) == 20
    
    def test_comparisons_sorted_by_timestamp_descending(self, mock_comparator, sample_comparisons):
        """Comparisons are sorted by timestamp descending (most recent first)."""
        set_shadow_comparator(mock_comparator)
        for comp in sample_comparisons:
            store_comparison_result(comp)
        
        response = client.get("/api/shadow/comparisons")
        
        assert response.status_code == 200
        data = response.json()
        comparisons = data["comparisons"]
        
        # Verify descending order
        for i in range(len(comparisons) - 1):
            ts1 = datetime.fromisoformat(comparisons[i]["timestamp"])
            ts2 = datetime.fromisoformat(comparisons[i + 1]["timestamp"])
            assert ts1 >= ts2
    
    def test_filter_by_symbol(self, mock_comparator, sample_comparisons):
        """Filters comparisons by symbol."""
        set_shadow_comparator(mock_comparator)
        for comp in sample_comparisons:
            store_comparison_result(comp)
        
        response = client.get("/api/shadow/comparisons?symbol=BTCUSDT")
        
        assert response.status_code == 200
        data = response.json()
        # Every even index has BTCUSDT
        assert data["total"] == 10
        for comp in data["comparisons"]:
            assert comp["symbol"] == "BTCUSDT"
    
    def test_filter_by_agrees_true(self, mock_comparator, sample_comparisons):
        """Filters comparisons by agrees=true."""
        set_shadow_comparator(mock_comparator)
        for comp in sample_comparisons:
            store_comparison_result(comp)
        
        response = client.get("/api/shadow/comparisons?agrees=true")
        
        assert response.status_code == 200
        data = response.json()
        for comp in data["comparisons"]:
            assert comp["agrees"] is True
    
    def test_filter_by_agrees_false(self, mock_comparator, sample_comparisons):
        """Filters comparisons by agrees=false (divergences only)."""
        set_shadow_comparator(mock_comparator)
        for comp in sample_comparisons:
            store_comparison_result(comp)
        
        response = client.get("/api/shadow/comparisons?agrees=false")
        
        assert response.status_code == 200
        data = response.json()
        for comp in data["comparisons"]:
            assert comp["agrees"] is False
    
    def test_filter_by_time_range(self, mock_comparator, sample_comparisons):
        """Filters comparisons by time range."""
        set_shadow_comparator(mock_comparator)
        for comp in sample_comparisons:
            store_comparison_result(comp)
        
        # Get comparisons from last 10 minutes
        # Use URL-safe format without timezone suffix for query params
        now = datetime.now(timezone.utc)
        start_time = (now - timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%S")
        end_time = now.strftime("%Y-%m-%dT%H:%M:%S")
        
        response = client.get(
            f"/api/shadow/comparisons?start_time={start_time}&end_time={end_time}"
        )
        
        assert response.status_code == 200
        data = response.json()
        # Should have comparisons from indices 0-9 (within 10 minutes)
        assert data["total"] <= 11  # At most 11 comparisons in 10 minute window
    
    def test_limit_parameter(self, mock_comparator, sample_comparisons):
        """Respects limit parameter."""
        set_shadow_comparator(mock_comparator)
        for comp in sample_comparisons:
            store_comparison_result(comp)
        
        response = client.get("/api/shadow/comparisons?limit=5")
        
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 20  # Total before limit
        assert data["filtered"] == 5  # After limit
        assert len(data["comparisons"]) == 5
    
    def test_offset_parameter(self, mock_comparator, sample_comparisons):
        """Respects offset parameter for pagination."""
        set_shadow_comparator(mock_comparator)
        for comp in sample_comparisons:
            store_comparison_result(comp)
        
        # Get first page
        response1 = client.get("/api/shadow/comparisons?limit=5&offset=0")
        data1 = response1.json()
        
        # Get second page
        response2 = client.get("/api/shadow/comparisons?limit=5&offset=5")
        data2 = response2.json()
        
        assert response1.status_code == 200
        assert response2.status_code == 200
        
        # Pages should have different comparisons
        timestamps1 = {c["timestamp"] for c in data1["comparisons"]}
        timestamps2 = {c["timestamp"] for c in data2["comparisons"]}
        assert timestamps1.isdisjoint(timestamps2)
    
    def test_limit_validation_min(self, mock_comparator):
        """Validates minimum limit value."""
        set_shadow_comparator(mock_comparator)
        
        response = client.get("/api/shadow/comparisons?limit=0")
        
        assert response.status_code == 422  # Validation error
    
    def test_limit_validation_max(self, mock_comparator):
        """Validates maximum limit value."""
        set_shadow_comparator(mock_comparator)
        
        response = client.get("/api/shadow/comparisons?limit=1001")
        
        assert response.status_code == 422  # Validation error
    
    def test_comparison_response_fields(self, mock_comparator):
        """Verifies all expected fields in comparison response."""
        set_shadow_comparator(mock_comparator)
        
        comparison = ComparisonResult.create(
            timestamp=datetime.now(timezone.utc),
            symbol="BTCUSDT",
            live_decision="accepted",
            shadow_decision="rejected",
            divergence_reason="stage_diff:ev_gatevsdata_readiness",
            live_rejection_stage=None,
            shadow_rejection_stage="data_readiness",
            live_config_version="v1.0.0",
            shadow_config_version="v1.1.0",
        )
        store_comparison_result(comparison)
        
        response = client.get("/api/shadow/comparisons")
        
        assert response.status_code == 200
        data = response.json()
        comp = data["comparisons"][0]
        
        assert "timestamp" in comp
        assert comp["symbol"] == "BTCUSDT"
        assert comp["live_decision"] == "accepted"
        assert comp["shadow_decision"] == "rejected"
        assert comp["agrees"] is False
        assert comp["divergence_reason"] == "stage_diff:ev_gatevsdata_readiness"
        assert comp["live_rejection_stage"] is None
        assert comp["shadow_rejection_stage"] == "data_readiness"
        assert comp["live_config_version"] == "v1.0.0"
        assert comp["shadow_config_version"] == "v1.1.0"
    
    def test_filter_by_divergence_reason(self, mock_comparator):
        """Filters comparisons by divergence reason."""
        set_shadow_comparator(mock_comparator)
        
        # Create comparisons with different divergence reasons
        for i in range(5):
            store_comparison_result(ComparisonResult.create(
                timestamp=datetime.now(timezone.utc) - timedelta(minutes=i),
                symbol="BTCUSDT",
                live_decision="accepted",
                shadow_decision="rejected",
                divergence_reason="stage_diff:ev_gate",
            ))
        
        for i in range(3):
            store_comparison_result(ComparisonResult.create(
                timestamp=datetime.now(timezone.utc) - timedelta(minutes=i + 10),
                symbol="BTCUSDT",
                live_decision="rejected",
                shadow_decision="accepted",
                divergence_reason="profile_diff:scalp",
            ))
        
        response = client.get("/api/shadow/comparisons?divergence_reason=stage_diff:ev_gate")
        
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 5
        for comp in data["comparisons"]:
            assert comp["divergence_reason"] == "stage_diff:ev_gate"


# =============================================================================
# Module State Management Tests
# =============================================================================

class TestModuleState:
    """Tests for module-level state management functions."""
    
    def test_set_and_get_shadow_comparator(self, mock_comparator):
        """Can set and get shadow comparator."""
        assert get_shadow_comparator() is None
        
        set_shadow_comparator(mock_comparator)
        
        assert get_shadow_comparator() is mock_comparator
    
    def test_store_and_get_comparisons(self):
        """Can store and retrieve comparison results."""
        comparison = ComparisonResult.create(
            timestamp=datetime.now(timezone.utc),
            symbol="BTCUSDT",
            live_decision="accepted",
            shadow_decision="accepted",
        )
        
        store_comparison_result(comparison)
        
        stored = get_stored_comparisons()
        assert len(stored) == 1
        assert stored[0].symbol == "BTCUSDT"
    
    def test_clear_comparisons(self):
        """Can clear stored comparisons."""
        comparison = ComparisonResult.create(
            timestamp=datetime.now(timezone.utc),
            symbol="BTCUSDT",
            live_decision="accepted",
            shadow_decision="accepted",
        )
        store_comparison_result(comparison)
        
        clear_comparison_results()
        
        assert len(get_stored_comparisons()) == 0
    
    def test_get_stored_comparisons_returns_copy(self):
        """get_stored_comparisons returns a copy, not the original list."""
        comparison = ComparisonResult.create(
            timestamp=datetime.now(timezone.utc),
            symbol="BTCUSDT",
            live_decision="accepted",
            shadow_decision="accepted",
        )
        store_comparison_result(comparison)
        
        stored1 = get_stored_comparisons()
        stored2 = get_stored_comparisons()
        
        assert stored1 is not stored2
        assert stored1 == stored2
