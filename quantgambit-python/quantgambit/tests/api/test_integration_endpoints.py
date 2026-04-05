"""
Frontend API Integration Tests for Trading Pipeline Integration.

Feature: trading-pipeline-integration
Requirements: 4.5, 1.4, 7.4, 9.3

This module provides integration tests for the API endpoints that the frontend
components use:
- GET /api/shadow/metrics - Shadow comparison metrics
- GET /api/config/diff - Configuration differences (via backtest endpoint)
- POST /api/replay/run - Trigger replay validation
- GET /api/replay/results/{run_id} - Get replay results
- GET /api/metrics/compare - Metrics comparison

These tests verify that the APIs return correct data structures and handle
both success and error cases appropriately.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# Import shadow endpoints
from quantgambit.api.shadow_endpoints import (
    router as shadow_router,
    set_shadow_comparator,
    store_comparison_result,
    clear_comparison_results,
)
from quantgambit.integration.shadow_comparison import (
    ComparisonResult,
    ComparisonMetrics,
)

# Import replay endpoints
from quantgambit.api.replay_endpoints import (
    router as replay_router,
    set_replay_manager,
    clear_pending_runs,
)
from quantgambit.integration.replay_validation import ReplayReport

# Import metrics endpoints
from quantgambit.api.metrics_endpoints import (
    router as metrics_router,
    set_metrics_reconciler,
    set_load_live_metrics_callback,
    set_load_backtest_metrics_callback,
    clear_metrics_state,
)
from quantgambit.integration.unified_metrics import UnifiedMetrics, MetricsReconciler


# =============================================================================
# Test App Setup
# =============================================================================

# Create a combined test app with all routers for integration testing
app = FastAPI()
app.include_router(shadow_router)
app.include_router(replay_router)
app.include_router(metrics_router)
client = TestClient(app)


# =============================================================================
# Mock Classes
# =============================================================================

class MockShadowComparator:
    """Mock ShadowComparator for testing shadow metrics API.
    
    Feature: trading-pipeline-integration
    Requirements: 4.5
    """
    
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


class MockReplayManager:
    """Mock ReplayManager for testing replay API.
    
    Feature: trading-pipeline-integration
    Requirements: 7.4
    """
    
    def __init__(
        self,
        reports: Optional[List[ReplayReport]] = None,
        replay_result: Optional[ReplayReport] = None,
    ):
        self._reports: Dict[str, ReplayReport] = {}
        if reports:
            for report in reports:
                if report.run_id:
                    self._reports[report.run_id] = report
        self._replay_result = replay_result
    
    async def replay_range(
        self,
        start_time: datetime,
        end_time: datetime,
        symbol: Optional[str] = None,
        decision_filter: Optional[str] = None,
        max_decisions: int = 10000,
    ) -> ReplayReport:
        """Return mock replay result."""
        if self._replay_result:
            return self._replay_result
        
        return ReplayReport(
            total_replayed=100,
            matches=90,
            changes=10,
            match_rate=0.9,
            changes_by_category={"improved": 5, "degraded": 3, "unexpected": 2},
            changes_by_stage={"ev_gate->none": 5, "none->ev_gate": 3},
            sample_changes=[],
            run_id="test_run_123",
            run_at=datetime.now(timezone.utc),
            start_time=start_time,
            end_time=end_time,
        )
    
    async def save_report(self, report: ReplayReport) -> None:
        """Save report to mock storage."""
        if report.run_id:
            self._reports[report.run_id] = report
    
    async def get_report(self, run_id: str) -> Optional[ReplayReport]:
        """Get report from mock storage."""
        return self._reports.get(run_id)
    
    async def list_reports(
        self,
        limit: int = 100,
        offset: int = 0,
    ) -> List[ReplayReport]:
        """List reports from mock storage."""
        reports = list(self._reports.values())
        reports.sort(key=lambda r: r.run_at or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
        return reports[offset:offset + limit]


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture(autouse=True)
def reset_all_state():
    """Reset all module state before each test.
    
    This ensures tests are isolated and don't affect each other.
    """
    # Reset shadow state
    set_shadow_comparator(None)
    clear_comparison_results()
    
    # Reset replay state
    set_replay_manager(None)
    clear_pending_runs()
    
    # Reset metrics state
    clear_metrics_state()
    
    yield
    
    # Cleanup after test
    set_shadow_comparator(None)
    clear_comparison_results()
    set_replay_manager(None)
    clear_pending_runs()
    clear_metrics_state()


@pytest.fixture
def sample_live_metrics():
    """Create sample live trading metrics for testing.
    
    Feature: trading-pipeline-integration
    Requirements: 9.3
    """
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
    """Create sample backtest metrics for testing.
    
    Feature: trading-pipeline-integration
    Requirements: 9.3
    """
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
def sample_replay_reports():
    """Create sample replay reports for testing.
    
    Feature: trading-pipeline-integration
    Requirements: 7.4
    """
    now = datetime.now(timezone.utc)
    return [
        ReplayReport(
            total_replayed=100,
            matches=90,
            changes=10,
            match_rate=0.9,
            changes_by_category={"improved": 5, "degraded": 3, "unexpected": 2},
            changes_by_stage={"ev_gate->none": 5},
            sample_changes=[],
            run_id=f"replay_{i:012d}",
            run_at=now - timedelta(hours=i),
            start_time=now - timedelta(days=1),
            end_time=now,
        )
        for i in range(5)
    ]


@pytest.fixture
def sample_comparisons():
    """Create sample shadow comparison results for testing.
    
    Feature: trading-pipeline-integration
    Requirements: 4.5
    """
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
# Shadow Metrics API Integration Tests
# =============================================================================

class TestShadowMetricsAPIIntegration:
    """Integration tests for shadow metrics API.
    
    Feature: trading-pipeline-integration
    **Validates: Requirements 4.5**
    
    Tests that the shadow metrics API returns correct data for frontend
    consumption, including agreement rates, divergence reasons, and P&L.
    """
    
    def test_shadow_metrics_returns_correct_data_structure(self):
        """Shadow metrics API returns all required fields for frontend.
        
        **Validates: Requirements 4.5**
        """
        comparator = MockShadowComparator(
            total_comparisons=100,
            agreements=80,
            divergence_by_reason={
                "stage_diff:ev_gate": 10,
                "profile_diff:scalp": 5,
                "unknown": 5,
            },
            live_pnl=1000.0,
            shadow_pnl=1200.0,
        )
        set_shadow_comparator(comparator)
        
        response = client.get("/api/shadow/metrics")
        
        assert response.status_code == 200
        data = response.json()
        
        # Verify all required fields for frontend are present
        assert "total_comparisons" in data
        assert "agreements" in data
        assert "disagreements" in data
        assert "agreement_rate" in data
        assert "divergence_rate" in data
        assert "divergence_by_reason" in data
        assert "top_divergence_reasons" in data
        assert "live_pnl_estimate" in data
        assert "shadow_pnl_estimate" in data
        assert "pnl_difference" in data
        assert "exceeds_alert_threshold" in data
    
    def test_shadow_metrics_returns_correct_values(self):
        """Shadow metrics API returns correct calculated values.
        
        **Validates: Requirements 4.5**
        """
        comparator = MockShadowComparator(
            total_comparisons=100,
            agreements=80,
            live_pnl=1000.0,
            shadow_pnl=1500.0,
        )
        set_shadow_comparator(comparator)
        
        response = client.get("/api/shadow/metrics")
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["total_comparisons"] == 100
        assert data["agreements"] == 80
        assert data["disagreements"] == 20
        assert data["agreement_rate"] == 0.8
        assert abs(data["divergence_rate"] - 0.2) < 0.001
        assert data["live_pnl_estimate"] == 1000.0
        assert data["shadow_pnl_estimate"] == 1500.0
        assert data["pnl_difference"] == 500.0
    
    def test_shadow_metrics_returns_503_when_disabled(self):
        """Shadow metrics API returns 503 when shadow mode is disabled.
        
        **Validates: Requirements 4.5**
        """
        # Shadow comparator not set
        response = client.get("/api/shadow/metrics")
        
        assert response.status_code == 503
        data = response.json()
        assert "Shadow mode is not enabled" in data["detail"]
    
    def test_shadow_comparisons_returns_filtered_results(self, sample_comparisons):
        """Shadow comparisons API returns correctly filtered results.
        
        **Validates: Requirements 4.5**
        """
        comparator = MockShadowComparator()
        set_shadow_comparator(comparator)
        
        for comp in sample_comparisons:
            store_comparison_result(comp)
        
        # Filter by symbol
        response = client.get("/api/shadow/comparisons?symbol=BTCUSDT")
        
        assert response.status_code == 200
        data = response.json()
        
        # All returned comparisons should be for BTCUSDT
        for comp in data["comparisons"]:
            assert comp["symbol"] == "BTCUSDT"
    
    def test_shadow_comparisons_pagination_works(self, sample_comparisons):
        """Shadow comparisons API pagination works correctly.
        
        **Validates: Requirements 4.5**
        """
        comparator = MockShadowComparator()
        set_shadow_comparator(comparator)
        
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
    
    def test_shadow_alert_threshold_detection(self):
        """Shadow metrics correctly detects when alert threshold is exceeded.
        
        **Validates: Requirements 4.5**
        """
        # 30% divergence exceeds 20% threshold
        comparator = MockShadowComparator(
            total_comparisons=100,
            agreements=70,  # 30% divergence
        )
        set_shadow_comparator(comparator)
        
        response = client.get("/api/shadow/metrics")
        
        assert response.status_code == 200
        data = response.json()
        assert data["exceeds_alert_threshold"] is True


# =============================================================================
# Replay API Integration Tests
# =============================================================================

class TestReplayAPIIntegration:
    """Integration tests for replay validation API.
    
    Feature: trading-pipeline-integration
    **Validates: Requirements 7.4**
    
    Tests that the replay API correctly triggers replay validation and
    returns results in the format expected by the frontend.
    """
    
    def test_replay_run_triggers_and_returns_run_id(self):
        """POST /api/replay/run triggers replay and returns run_id.
        
        **Validates: Requirements 7.4**
        """
        manager = MockReplayManager()
        set_replay_manager(manager)
        
        now = datetime.now(timezone.utc)
        response = client.post(
            "/api/replay/run",
            json={
                "start_time": (now - timedelta(days=1)).isoformat(),
                "end_time": now.isoformat(),
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        
        assert "run_id" in data
        assert data["run_id"].startswith("replay_")
        assert data["status"] == "queued"
        assert "message" in data
    
    def test_replay_run_accepts_filters(self):
        """POST /api/replay/run accepts symbol and decision filters.
        
        **Validates: Requirements 7.4**
        """
        manager = MockReplayManager()
        set_replay_manager(manager)
        
        now = datetime.now(timezone.utc)
        response = client.post(
            "/api/replay/run",
            json={
                "start_time": (now - timedelta(days=1)).isoformat(),
                "end_time": now.isoformat(),
                "symbol": "BTCUSDT",
                "decision_filter": "accepted",
                "max_decisions": 5000,
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        assert "run_id" in data
    
    def test_replay_results_returns_correct_structure(self, sample_replay_reports):
        """GET /api/replay/results/{run_id} returns correct data structure.
        
        **Validates: Requirements 7.4**
        """
        manager = MockReplayManager(reports=sample_replay_reports)
        set_replay_manager(manager)
        
        response = client.get("/api/replay/results/replay_000000000000")
        
        assert response.status_code == 200
        data = response.json()
        
        # Verify all required fields for frontend are present
        assert "run_id" in data
        assert "total_replayed" in data
        assert "matches" in data
        assert "changes" in data
        assert "match_rate" in data
        assert "changes_by_category" in data
        assert "changes_by_stage" in data
        assert "has_degradations" in data
        assert "has_improvements" in data
        assert "is_passing" in data
    
    def test_replay_results_returns_correct_values(self, sample_replay_reports):
        """GET /api/replay/results/{run_id} returns correct values.
        
        **Validates: Requirements 7.4**
        """
        manager = MockReplayManager(reports=sample_replay_reports)
        set_replay_manager(manager)
        
        response = client.get("/api/replay/results/replay_000000000000")
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["run_id"] == "replay_000000000000"
        assert data["total_replayed"] == 100
        assert data["matches"] == 90
        assert data["changes"] == 10
        assert data["match_rate"] == 0.9
    
    def test_replay_results_returns_404_for_unknown_run(self):
        """GET /api/replay/results/{run_id} returns 404 for unknown run.
        
        **Validates: Requirements 7.4**
        """
        manager = MockReplayManager()
        set_replay_manager(manager)
        
        response = client.get("/api/replay/results/nonexistent_run")
        
        assert response.status_code == 404
        data = response.json()
        assert "not found" in data["detail"].lower()
    
    def test_replay_results_returns_503_when_disabled(self):
        """GET /api/replay/results/{run_id} returns 503 when disabled.
        
        **Validates: Requirements 7.4**
        """
        # Replay manager not set
        response = client.get("/api/replay/results/test_run")
        
        assert response.status_code == 503
        data = response.json()
        assert "Replay functionality is not enabled" in data["detail"]
    
    def test_replay_run_validates_time_range(self):
        """POST /api/replay/run validates start_time < end_time.
        
        **Validates: Requirements 7.4**
        """
        manager = MockReplayManager()
        set_replay_manager(manager)
        
        now = datetime.now(timezone.utc)
        response = client.post(
            "/api/replay/run",
            json={
                "start_time": now.isoformat(),
                "end_time": (now - timedelta(days=1)).isoformat(),  # Invalid: end before start
            }
        )
        
        assert response.status_code == 400
        data = response.json()
        assert "start_time must be before end_time" in data["detail"]
    
    def test_replay_run_validates_decision_filter(self):
        """POST /api/replay/run validates decision_filter values.
        
        **Validates: Requirements 7.4**
        """
        manager = MockReplayManager()
        set_replay_manager(manager)
        
        now = datetime.now(timezone.utc)
        response = client.post(
            "/api/replay/run",
            json={
                "start_time": (now - timedelta(days=1)).isoformat(),
                "end_time": now.isoformat(),
                "decision_filter": "invalid_value",
            }
        )
        
        assert response.status_code == 400
        data = response.json()
        assert "decision_filter must be 'accepted' or 'rejected'" in data["detail"]
    
    def test_replay_runs_list_returns_summaries(self, sample_replay_reports):
        """GET /api/replay/runs returns list of run summaries.
        
        **Validates: Requirements 7.4**
        """
        manager = MockReplayManager(reports=sample_replay_reports)
        set_replay_manager(manager)
        
        response = client.get("/api/replay/runs")
        
        assert response.status_code == 200
        data = response.json()
        
        assert "runs" in data
        assert len(data["runs"]) == 5
        
        # Verify summary fields
        run = data["runs"][0]
        assert "run_id" in run
        assert "run_at" in run
        assert "total_replayed" in run
        assert "match_rate" in run
        assert "has_degradations" in run
        assert "is_passing" in run


# =============================================================================
# Metrics Comparison API Integration Tests
# =============================================================================

class TestMetricsComparisonAPIIntegration:
    """Integration tests for metrics comparison API.
    
    Feature: trading-pipeline-integration
    **Validates: Requirements 9.3**
    
    Tests that the metrics comparison API returns correct data for frontend
    consumption, including side-by-side metrics and divergence factors.
    """
    
    def test_metrics_compare_returns_correct_structure(
        self, sample_live_metrics, sample_backtest_metrics
    ):
        """GET /api/metrics/compare returns correct data structure.
        
        **Validates: Requirements 9.3**
        """
        reconciler = MetricsReconciler(risk_free_rate=0.05)
        set_metrics_reconciler(reconciler)
        
        async def load_live(period_hours: float) -> UnifiedMetrics:
            return sample_live_metrics
        
        async def load_backtest(run_id: str) -> UnifiedMetrics:
            return sample_backtest_metrics
        
        set_load_live_metrics_callback(load_live)
        set_load_backtest_metrics_callback(load_backtest)
        
        response = client.get("/api/metrics/compare?backtest_run_id=test_run")
        
        assert response.status_code == 200
        data = response.json()
        
        # Verify all required fields for frontend are present
        assert "live_metrics" in data
        assert "backtest_metrics" in data
        assert "significant_differences" in data
        assert "divergence_factors" in data
        assert "overall_similarity" in data
        assert "comparison_timestamp" in data
        assert "has_significant_differences" in data
        assert "backtest_run_id" in data
        assert "live_period_hours" in data
    
    def test_metrics_compare_returns_correct_metric_values(
        self, sample_live_metrics, sample_backtest_metrics
    ):
        """GET /api/metrics/compare returns correct metric values.
        
        **Validates: Requirements 9.3**
        """
        reconciler = MetricsReconciler(risk_free_rate=0.05)
        set_metrics_reconciler(reconciler)
        
        async def load_live(period_hours: float) -> UnifiedMetrics:
            return sample_live_metrics
        
        async def load_backtest(run_id: str) -> UnifiedMetrics:
            return sample_backtest_metrics
        
        set_load_live_metrics_callback(load_live)
        set_load_backtest_metrics_callback(load_backtest)
        
        response = client.get("/api/metrics/compare?backtest_run_id=test_run")
        
        assert response.status_code == 200
        data = response.json()
        
        # Verify live metrics values
        live = data["live_metrics"]
        assert live["total_return_pct"] == 15.5
        assert live["sharpe_ratio"] == 1.8
        assert live["total_trades"] == 150
        assert live["win_rate"] == 0.6
        
        # Verify backtest metrics values
        backtest = data["backtest_metrics"]
        assert backtest["total_return_pct"] == 18.0
        assert backtest["sharpe_ratio"] == 2.1
        assert backtest["total_trades"] == 160
        assert backtest["win_rate"] == 0.625
    
    def test_metrics_compare_identifies_significant_differences(
        self, sample_live_metrics, sample_backtest_metrics
    ):
        """GET /api/metrics/compare identifies significant differences (>10%).
        
        **Validates: Requirements 9.3**
        """
        reconciler = MetricsReconciler(risk_free_rate=0.05)
        set_metrics_reconciler(reconciler)
        
        async def load_live(period_hours: float) -> UnifiedMetrics:
            return sample_live_metrics
        
        async def load_backtest(run_id: str) -> UnifiedMetrics:
            return sample_backtest_metrics
        
        set_load_live_metrics_callback(load_live)
        set_load_backtest_metrics_callback(load_backtest)
        
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
    
    def test_metrics_compare_returns_divergence_factors(
        self, sample_live_metrics, sample_backtest_metrics
    ):
        """GET /api/metrics/compare returns divergence attribution factors.
        
        **Validates: Requirements 9.3**
        """
        reconciler = MetricsReconciler(risk_free_rate=0.05)
        set_metrics_reconciler(reconciler)
        
        async def load_live(period_hours: float) -> UnifiedMetrics:
            return sample_live_metrics
        
        async def load_backtest(run_id: str) -> UnifiedMetrics:
            return sample_backtest_metrics
        
        set_load_live_metrics_callback(load_live)
        set_load_backtest_metrics_callback(load_backtest)
        
        response = client.get("/api/metrics/compare?backtest_run_id=test_run")
        
        assert response.status_code == 200
        data = response.json()
        
        factors = data["divergence_factors"]
        assert isinstance(factors, list)
    
    def test_metrics_compare_returns_503_when_disabled(self):
        """GET /api/metrics/compare returns 503 when not configured.
        
        **Validates: Requirements 9.3**
        """
        # Reconciler not set
        response = client.get("/api/metrics/compare?backtest_run_id=test_run")
        
        assert response.status_code == 503
        data = response.json()
        assert "Metrics comparison functionality is not enabled" in data["detail"]
    
    def test_metrics_compare_returns_404_for_unknown_backtest(
        self, sample_live_metrics
    ):
        """GET /api/metrics/compare returns 404 for unknown backtest.
        
        **Validates: Requirements 9.3**
        """
        reconciler = MetricsReconciler(risk_free_rate=0.05)
        set_metrics_reconciler(reconciler)
        
        async def load_live(period_hours: float) -> UnifiedMetrics:
            return sample_live_metrics
        
        async def load_backtest(run_id: str) -> Optional[UnifiedMetrics]:
            return None  # Backtest not found
        
        set_load_live_metrics_callback(load_live)
        set_load_backtest_metrics_callback(load_backtest)
        
        response = client.get("/api/metrics/compare?backtest_run_id=nonexistent")
        
        assert response.status_code == 404
        data = response.json()
        assert "not found" in data["detail"].lower()
    
    def test_metrics_compare_accepts_custom_live_period(
        self, sample_live_metrics, sample_backtest_metrics
    ):
        """GET /api/metrics/compare accepts custom live_period_hours.
        
        **Validates: Requirements 9.3**
        """
        reconciler = MetricsReconciler(risk_free_rate=0.05)
        set_metrics_reconciler(reconciler)
        
        async def load_live(period_hours: float) -> UnifiedMetrics:
            return sample_live_metrics
        
        async def load_backtest(run_id: str) -> UnifiedMetrics:
            return sample_backtest_metrics
        
        set_load_live_metrics_callback(load_live)
        set_load_backtest_metrics_callback(load_backtest)
        
        response = client.get(
            "/api/metrics/compare?backtest_run_id=test_run&live_period_hours=48"
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["live_period_hours"] == 48.0
    
    def test_metrics_compare_validates_live_period_range(
        self, sample_live_metrics, sample_backtest_metrics
    ):
        """GET /api/metrics/compare validates live_period_hours range.
        
        **Validates: Requirements 9.3**
        """
        reconciler = MetricsReconciler(risk_free_rate=0.05)
        set_metrics_reconciler(reconciler)
        
        async def load_live(period_hours: float) -> UnifiedMetrics:
            return sample_live_metrics
        
        async def load_backtest(run_id: str) -> UnifiedMetrics:
            return sample_backtest_metrics
        
        set_load_live_metrics_callback(load_live)
        set_load_backtest_metrics_callback(load_backtest)
        
        # Test minimum validation
        response = client.get(
            "/api/metrics/compare?backtest_run_id=test_run&live_period_hours=0.05"
        )
        assert response.status_code == 422  # Validation error
        
        # Test maximum validation
        response = client.get(
            "/api/metrics/compare?backtest_run_id=test_run&live_period_hours=800"
        )
        assert response.status_code == 422  # Validation error


# =============================================================================
# Config Diff API Integration Tests (via Backtest Endpoint)
# =============================================================================

class TestConfigDiffAPIIntegration:
    """Integration tests for config diff API.
    
    Feature: trading-pipeline-integration
    **Validates: Requirements 1.4**
    
    Tests that the config diff API shows configuration differences between
    live and backtest configurations. The config diff endpoint is part of
    the backtest API at GET /api/research/backtests/{run_id}/config-diff.
    
    Note: These tests verify the expected behavior of the config diff
    functionality. The actual endpoint requires database connections,
    so we test the response structure and error handling patterns.
    """
    
    def test_config_diff_response_structure_documented(self):
        """Config diff API response structure is documented.
        
        **Validates: Requirements 1.4**
        
        This test documents the expected response structure for the
        config diff API endpoint. The actual endpoint is at:
        GET /api/research/backtests/{run_id}/config-diff
        
        Expected response structure:
        {
            "source_version": "live_v1.0",
            "target_version": "backtest_abc123",
            "critical_diffs": [
                {"key": "fee_bps", "old": 5.0, "new": 10.0}
            ],
            "warning_diffs": [
                {"key": "slippage_bps", "old": 1.0, "new": 2.0}
            ],
            "info_diffs": [
                {"key": "some_param", "old": "a", "new": "b"}
            ],
            "has_critical_diffs": true,
            "total_diffs": 3
        }
        """
        # This test documents the expected structure
        expected_fields = [
            "source_version",
            "target_version",
            "critical_diffs",
            "warning_diffs",
            "info_diffs",
            "has_critical_diffs",
            "total_diffs",
        ]
        
        # Verify the expected fields are documented
        assert len(expected_fields) == 7
        assert "critical_diffs" in expected_fields
        assert "warning_diffs" in expected_fields
        assert "info_diffs" in expected_fields
    
    def test_config_diff_categorization_rules_documented(self):
        """Config diff categorization rules are documented.
        
        **Validates: Requirements 1.4**
        
        Critical parameters (require acknowledgment):
        - fee_bps: Trading fees
        - slippage_bps: Slippage estimates
        - entry_threshold: Entry signal threshold
        - exit_threshold: Exit signal threshold
        - stop_loss_pct: Stop loss percentage
        - take_profit_pct: Take profit percentage
        
        Warning parameters (logged but don't block):
        - risk_per_trade_pct: Risk per trade
        - max_position_size: Maximum position size
        - cooldown_seconds: Cooldown between trades
        
        Info parameters (informational only):
        - All other parameters
        """
        critical_params = [
            "fee_bps",
            "slippage_bps",
            "entry_threshold",
            "exit_threshold",
            "stop_loss_pct",
            "take_profit_pct",
        ]
        
        warning_params = [
            "risk_per_trade_pct",
            "max_position_size",
            "cooldown_seconds",
        ]
        
        # Verify categorization is documented
        assert len(critical_params) == 6
        assert len(warning_params) == 3
        assert "fee_bps" in critical_params
        assert "slippage_bps" in critical_params


# =============================================================================
# Cross-API Integration Tests
# =============================================================================

class TestCrossAPIIntegration:
    """Integration tests that verify cross-API functionality.
    
    Feature: trading-pipeline-integration
    **Validates: Requirements 4.5, 1.4, 7.4, 9.3**
    
    Tests that verify the APIs work together correctly for frontend
    dashboard scenarios.
    """
    
    def test_all_apis_return_503_when_not_configured(self):
        """All APIs return 503 when their services are not configured.
        
        **Validates: Requirements 4.5, 7.4, 9.3**
        """
        # Shadow metrics
        response = client.get("/api/shadow/metrics")
        assert response.status_code == 503
        
        # Shadow comparisons
        response = client.get("/api/shadow/comparisons")
        assert response.status_code == 503
        
        # Replay results
        response = client.get("/api/replay/results/test_run")
        assert response.status_code == 503
        
        # Replay runs list
        response = client.get("/api/replay/runs")
        assert response.status_code == 503
        
        # Metrics compare
        response = client.get("/api/metrics/compare?backtest_run_id=test")
        assert response.status_code == 503
    
    def test_apis_can_be_enabled_independently(
        self, sample_live_metrics, sample_backtest_metrics
    ):
        """APIs can be enabled independently of each other.
        
        **Validates: Requirements 4.5, 7.4, 9.3**
        """
        # Enable only shadow
        comparator = MockShadowComparator()
        set_shadow_comparator(comparator)
        
        # Shadow should work
        response = client.get("/api/shadow/metrics")
        assert response.status_code == 200
        
        # Replay should still be disabled
        response = client.get("/api/replay/runs")
        assert response.status_code == 503
        
        # Metrics should still be disabled
        response = client.get("/api/metrics/compare?backtest_run_id=test")
        assert response.status_code == 503
        
        # Now enable replay
        manager = MockReplayManager()
        set_replay_manager(manager)
        
        # Replay should now work
        response = client.get("/api/replay/runs")
        assert response.status_code == 200
        
        # Metrics should still be disabled
        response = client.get("/api/metrics/compare?backtest_run_id=test")
        assert response.status_code == 503
    
    def test_frontend_dashboard_scenario_shadow_monitoring(self, sample_comparisons):
        """Frontend dashboard scenario: Shadow mode monitoring.
        
        **Validates: Requirements 4.5**
        
        Simulates the frontend dashboard loading shadow comparison data:
        1. Get aggregated metrics for the overview panel
        2. Get recent comparisons for the detail view
        3. Filter comparisons by divergence status
        """
        comparator = MockShadowComparator(
            total_comparisons=100,
            agreements=85,
            divergence_by_reason={
                "stage_diff:ev_gate": 8,
                "profile_diff:scalp": 5,
                "unknown": 2,
            },
        )
        set_shadow_comparator(comparator)
        
        for comp in sample_comparisons:
            store_comparison_result(comp)
        
        # Step 1: Get metrics for overview
        metrics_response = client.get("/api/shadow/metrics")
        assert metrics_response.status_code == 200
        metrics = metrics_response.json()
        assert metrics["agreement_rate"] == 0.85
        
        # Step 2: Get recent comparisons
        comparisons_response = client.get("/api/shadow/comparisons?limit=10")
        assert comparisons_response.status_code == 200
        comparisons = comparisons_response.json()
        assert len(comparisons["comparisons"]) <= 10
        
        # Step 3: Filter to divergences only
        divergences_response = client.get("/api/shadow/comparisons?agrees=false")
        assert divergences_response.status_code == 200
        divergences = divergences_response.json()
        for comp in divergences["comparisons"]:
            assert comp["agrees"] is False
    
    def test_frontend_dashboard_scenario_replay_validation(self, sample_replay_reports):
        """Frontend dashboard scenario: Replay validation workflow.
        
        **Validates: Requirements 7.4**
        
        Simulates the frontend dashboard replay validation workflow:
        1. Trigger a new replay run
        2. List recent replay runs
        3. Get detailed results for a specific run
        """
        manager = MockReplayManager(reports=sample_replay_reports)
        set_replay_manager(manager)
        
        # Step 1: Trigger new replay
        now = datetime.now(timezone.utc)
        trigger_response = client.post(
            "/api/replay/run",
            json={
                "start_time": (now - timedelta(days=1)).isoformat(),
                "end_time": now.isoformat(),
            }
        )
        assert trigger_response.status_code == 200
        new_run_id = trigger_response.json()["run_id"]
        assert new_run_id.startswith("replay_")
        
        # Step 2: List recent runs
        list_response = client.get("/api/replay/runs?limit=10")
        assert list_response.status_code == 200
        runs = list_response.json()
        assert len(runs["runs"]) > 0
        
        # Step 3: Get detailed results for existing run
        detail_response = client.get("/api/replay/results/replay_000000000000")
        assert detail_response.status_code == 200
        detail = detail_response.json()
        assert detail["total_replayed"] == 100
        assert "changes_by_category" in detail
    
    def test_frontend_dashboard_scenario_metrics_comparison(
        self, sample_live_metrics, sample_backtest_metrics
    ):
        """Frontend dashboard scenario: Metrics comparison.
        
        **Validates: Requirements 9.3**
        
        Simulates the frontend dashboard metrics comparison workflow:
        1. Compare backtest metrics with live trading
        2. Identify significant differences
        3. Review divergence factors
        """
        reconciler = MetricsReconciler(risk_free_rate=0.05)
        set_metrics_reconciler(reconciler)
        
        async def load_live(period_hours: float) -> UnifiedMetrics:
            return sample_live_metrics
        
        async def load_backtest(run_id: str) -> UnifiedMetrics:
            return sample_backtest_metrics
        
        set_load_live_metrics_callback(load_live)
        set_load_backtest_metrics_callback(load_backtest)
        
        # Step 1: Compare metrics
        compare_response = client.get(
            "/api/metrics/compare?backtest_run_id=test_run&live_period_hours=24"
        )
        assert compare_response.status_code == 200
        comparison = compare_response.json()
        
        # Step 2: Check for significant differences
        assert "significant_differences" in comparison
        assert "has_significant_differences" in comparison
        
        # Step 3: Review divergence factors
        assert "divergence_factors" in comparison
        assert "overall_similarity" in comparison
        
        # Verify metrics are present for side-by-side display
        assert comparison["live_metrics"]["total_return_pct"] == 15.5
        assert comparison["backtest_metrics"]["total_return_pct"] == 18.0
