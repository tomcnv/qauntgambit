"""
API tests for Replay Validation endpoints.

Feature: trading-pipeline-integration
Requirements: 7.4 - WHEN pipeline code changes THEN the System SHALL support
              running replay validation as part of CI/CD

Tests for:
- POST /api/replay/run endpoint to trigger replay
- GET /api/replay/results/{run_id} endpoint
- GET /api/replay/runs endpoint for listing
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from quantgambit.api.replay_endpoints import (
    router,
    set_replay_manager,
    get_replay_manager,
    get_pending_run,
    set_pending_run,
    remove_pending_run,
    clear_pending_runs,
    _report_to_response,
    _report_to_summary,
)
from quantgambit.integration.replay_validation import (
    ReplayReport,
    ReplayResult,
    ReplayManager,
)


# Create a test app with just the replay router
app = FastAPI()
app.include_router(router)
client = TestClient(app)


# =============================================================================
# Mock ReplayManager for testing
# =============================================================================

class MockReplayManager:
    """Mock ReplayManager for testing API endpoints."""
    
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
        # Sort by run_at descending
        reports.sort(key=lambda r: r.run_at or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
        return reports[offset:offset + limit]


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture(autouse=True)
def reset_replay_state():
    """Reset replay manager and pending runs before each test."""
    set_replay_manager(None)
    clear_pending_runs()
    yield
    set_replay_manager(None)
    clear_pending_runs()


@pytest.fixture
def mock_manager():
    """Create a mock replay manager."""
    return MockReplayManager()


@pytest.fixture
def mock_manager_with_reports():
    """Create a mock replay manager with pre-existing reports."""
    now = datetime.now(timezone.utc)
    reports = [
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
    return MockReplayManager(reports=reports)


@pytest.fixture
def sample_report():
    """Create a sample replay report."""
    now = datetime.now(timezone.utc)
    return ReplayReport(
        total_replayed=100,
        matches=90,
        changes=10,
        match_rate=0.9,
        changes_by_category={"improved": 5, "degraded": 3, "unexpected": 2},
        changes_by_stage={"ev_gate->none": 5, "none->ev_gate": 3, "data_readiness->ev_gate": 2},
        sample_changes=[],
        run_id="test_run_abc123",
        run_at=now,
        start_time=now - timedelta(days=1),
        end_time=now,
    )


# =============================================================================
# POST /api/replay/run Tests
# =============================================================================

class TestTriggerReplayRun:
    """Tests for POST /api/replay/run endpoint."""
    
    def test_returns_503_when_replay_disabled(self):
        """Returns 503 when replay functionality is not enabled."""
        now = datetime.now(timezone.utc)
        response = client.post(
            "/api/replay/run",
            json={
                "start_time": (now - timedelta(days=1)).isoformat(),
                "end_time": now.isoformat(),
            }
        )
        
        assert response.status_code == 503
        data = response.json()
        assert "Replay functionality is not enabled" in data["detail"]
    
    def test_returns_run_id_when_triggered(self, mock_manager):
        """Returns run_id when replay is triggered successfully."""
        set_replay_manager(mock_manager)
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
    
    def test_validates_decision_filter(self, mock_manager):
        """Validates decision_filter parameter."""
        set_replay_manager(mock_manager)
        now = datetime.now(timezone.utc)
        
        response = client.post(
            "/api/replay/run",
            json={
                "start_time": (now - timedelta(days=1)).isoformat(),
                "end_time": now.isoformat(),
                "decision_filter": "invalid",
            }
        )
        
        assert response.status_code == 400
        data = response.json()
        assert "decision_filter must be 'accepted' or 'rejected'" in data["detail"]
    
    def test_accepts_valid_decision_filter_accepted(self, mock_manager):
        """Accepts 'accepted' as decision_filter."""
        set_replay_manager(mock_manager)
        now = datetime.now(timezone.utc)
        
        response = client.post(
            "/api/replay/run",
            json={
                "start_time": (now - timedelta(days=1)).isoformat(),
                "end_time": now.isoformat(),
                "decision_filter": "accepted",
            }
        )
        
        assert response.status_code == 200
    
    def test_accepts_valid_decision_filter_rejected(self, mock_manager):
        """Accepts 'rejected' as decision_filter."""
        set_replay_manager(mock_manager)
        now = datetime.now(timezone.utc)
        
        response = client.post(
            "/api/replay/run",
            json={
                "start_time": (now - timedelta(days=1)).isoformat(),
                "end_time": now.isoformat(),
                "decision_filter": "rejected",
            }
        )
        
        assert response.status_code == 200
    
    def test_validates_time_range(self, mock_manager):
        """Validates that start_time is before end_time."""
        set_replay_manager(mock_manager)
        now = datetime.now(timezone.utc)
        
        response = client.post(
            "/api/replay/run",
            json={
                "start_time": now.isoformat(),
                "end_time": (now - timedelta(days=1)).isoformat(),
            }
        )
        
        assert response.status_code == 400
        data = response.json()
        assert "start_time must be before end_time" in data["detail"]
    
    def test_accepts_symbol_filter(self, mock_manager):
        """Accepts symbol filter parameter."""
        set_replay_manager(mock_manager)
        now = datetime.now(timezone.utc)
        
        response = client.post(
            "/api/replay/run",
            json={
                "start_time": (now - timedelta(days=1)).isoformat(),
                "end_time": now.isoformat(),
                "symbol": "BTCUSDT",
            }
        )
        
        assert response.status_code == 200
    
    def test_accepts_max_decisions_parameter(self, mock_manager):
        """Accepts max_decisions parameter."""
        set_replay_manager(mock_manager)
        now = datetime.now(timezone.utc)
        
        response = client.post(
            "/api/replay/run",
            json={
                "start_time": (now - timedelta(days=1)).isoformat(),
                "end_time": now.isoformat(),
                "max_decisions": 5000,
            }
        )
        
        assert response.status_code == 200
    
    def test_validates_max_decisions_min(self, mock_manager):
        """Validates minimum max_decisions value."""
        set_replay_manager(mock_manager)
        now = datetime.now(timezone.utc)
        
        response = client.post(
            "/api/replay/run",
            json={
                "start_time": (now - timedelta(days=1)).isoformat(),
                "end_time": now.isoformat(),
                "max_decisions": 0,
            }
        )
        
        assert response.status_code == 422  # Validation error
    
    def test_validates_max_decisions_max(self, mock_manager):
        """Validates maximum max_decisions value."""
        set_replay_manager(mock_manager)
        now = datetime.now(timezone.utc)
        
        response = client.post(
            "/api/replay/run",
            json={
                "start_time": (now - timedelta(days=1)).isoformat(),
                "end_time": now.isoformat(),
                "max_decisions": 100001,
            }
        )
        
        assert response.status_code == 422  # Validation error
    
    def test_stores_pending_run(self, mock_manager):
        """Stores pending run info after triggering."""
        set_replay_manager(mock_manager)
        now = datetime.now(timezone.utc)
        
        response = client.post(
            "/api/replay/run",
            json={
                "start_time": (now - timedelta(days=1)).isoformat(),
                "end_time": now.isoformat(),
            }
        )
        
        assert response.status_code == 200
        run_id = response.json()["run_id"]
        
        # Note: In TestClient, background tasks run synchronously,
        # so the status may already be "completed" by the time we check.
        # We just verify that the pending run info exists.
        pending = get_pending_run(run_id)
        assert pending is not None
        # Status could be "queued", "running", or "completed" depending on timing
        assert pending["status"] in ("queued", "running", "completed")


# =============================================================================
# GET /api/replay/results/{run_id} Tests
# =============================================================================

class TestGetReplayResults:
    """Tests for GET /api/replay/results/{run_id} endpoint."""
    
    def test_returns_503_when_replay_disabled(self):
        """Returns 503 when replay functionality is not enabled."""
        response = client.get("/api/replay/results/test_run_123")
        
        assert response.status_code == 503
        data = response.json()
        assert "Replay functionality is not enabled" in data["detail"]
    
    def test_returns_404_when_run_not_found(self, mock_manager):
        """Returns 404 when run_id is not found."""
        set_replay_manager(mock_manager)
        
        response = client.get("/api/replay/results/nonexistent_run")
        
        assert response.status_code == 404
        data = response.json()
        assert "not found" in data["detail"]
    
    def test_returns_202_when_run_queued(self, mock_manager):
        """Returns 202 when run is still queued."""
        set_replay_manager(mock_manager)
        set_pending_run("test_run_123", {"status": "queued"})
        
        response = client.get("/api/replay/results/test_run_123")
        
        assert response.status_code == 202
        data = response.json()
        assert "queued" in data["detail"]
    
    def test_returns_202_when_run_running(self, mock_manager):
        """Returns 202 when run is still running."""
        set_replay_manager(mock_manager)
        set_pending_run("test_run_123", {"status": "running"})
        
        response = client.get("/api/replay/results/test_run_123")
        
        assert response.status_code == 202
        data = response.json()
        assert "running" in data["detail"]
    
    def test_returns_500_when_run_failed(self, mock_manager):
        """Returns 500 when run failed."""
        set_replay_manager(mock_manager)
        set_pending_run("test_run_123", {
            "status": "failed",
            "error": "Database connection error",
        })
        
        response = client.get("/api/replay/results/test_run_123")
        
        assert response.status_code == 500
        data = response.json()
        assert "failed" in data["detail"]
        assert "Database connection error" in data["detail"]
    
    def test_returns_report_when_completed(self, mock_manager_with_reports):
        """Returns report when run is completed."""
        set_replay_manager(mock_manager_with_reports)
        
        response = client.get("/api/replay/results/replay_000000000000")
        
        assert response.status_code == 200
        data = response.json()
        assert data["run_id"] == "replay_000000000000"
        assert data["total_replayed"] == 100
        assert data["matches"] == 90
        assert data["changes"] == 10
        assert data["match_rate"] == 0.9
    
    def test_returns_changes_by_category(self, mock_manager_with_reports):
        """Returns changes breakdown by category."""
        set_replay_manager(mock_manager_with_reports)
        
        response = client.get("/api/replay/results/replay_000000000000")
        
        assert response.status_code == 200
        data = response.json()
        assert "changes_by_category" in data
        categories = {c["category"]: c["count"] for c in data["changes_by_category"]}
        assert "improved" in categories
        assert "degraded" in categories
    
    def test_returns_changes_by_stage(self, mock_manager_with_reports):
        """Returns changes breakdown by stage."""
        set_replay_manager(mock_manager_with_reports)
        
        response = client.get("/api/replay/results/replay_000000000000")
        
        assert response.status_code == 200
        data = response.json()
        assert "changes_by_stage" in data
    
    def test_returns_has_degradations_flag(self, mock_manager_with_reports):
        """Returns has_degradations flag."""
        set_replay_manager(mock_manager_with_reports)
        
        response = client.get("/api/replay/results/replay_000000000000")
        
        assert response.status_code == 200
        data = response.json()
        assert "has_degradations" in data
        assert data["has_degradations"] is True  # Report has degraded changes
    
    def test_returns_is_passing_flag(self, mock_manager_with_reports):
        """Returns is_passing flag."""
        set_replay_manager(mock_manager_with_reports)
        
        response = client.get("/api/replay/results/replay_000000000000")
        
        assert response.status_code == 200
        data = response.json()
        assert "is_passing" in data


# =============================================================================
# GET /api/replay/runs Tests
# =============================================================================

class TestListReplayRuns:
    """Tests for GET /api/replay/runs endpoint."""
    
    def test_returns_503_when_replay_disabled(self):
        """Returns 503 when replay functionality is not enabled."""
        response = client.get("/api/replay/runs")
        
        assert response.status_code == 503
        data = response.json()
        assert "Replay functionality is not enabled" in data["detail"]
    
    def test_returns_empty_list_when_no_runs(self, mock_manager):
        """Returns empty list when no runs exist."""
        set_replay_manager(mock_manager)
        
        response = client.get("/api/replay/runs")
        
        assert response.status_code == 200
        data = response.json()
        assert data["runs"] == []
        assert data["total"] == 0
    
    def test_returns_list_of_runs(self, mock_manager_with_reports):
        """Returns list of replay runs."""
        set_replay_manager(mock_manager_with_reports)
        
        response = client.get("/api/replay/runs")
        
        assert response.status_code == 200
        data = response.json()
        assert len(data["runs"]) == 5
        assert data["total"] == 5
    
    def test_runs_sorted_by_run_at_descending(self, mock_manager_with_reports):
        """Runs are sorted by run_at descending (most recent first)."""
        set_replay_manager(mock_manager_with_reports)
        
        response = client.get("/api/replay/runs")
        
        assert response.status_code == 200
        data = response.json()
        runs = data["runs"]
        
        # Verify descending order
        for i in range(len(runs) - 1):
            ts1 = datetime.fromisoformat(runs[i]["run_at"].replace('Z', '+00:00'))
            ts2 = datetime.fromisoformat(runs[i + 1]["run_at"].replace('Z', '+00:00'))
            assert ts1 >= ts2
    
    def test_respects_limit_parameter(self, mock_manager_with_reports):
        """Respects limit parameter."""
        set_replay_manager(mock_manager_with_reports)
        
        response = client.get("/api/replay/runs?limit=2")
        
        assert response.status_code == 200
        data = response.json()
        assert len(data["runs"]) == 2
        assert data["limit"] == 2
    
    def test_respects_offset_parameter(self, mock_manager_with_reports):
        """Respects offset parameter for pagination."""
        set_replay_manager(mock_manager_with_reports)
        
        # Get first page
        response1 = client.get("/api/replay/runs?limit=2&offset=0")
        data1 = response1.json()
        
        # Get second page
        response2 = client.get("/api/replay/runs?limit=2&offset=2")
        data2 = response2.json()
        
        assert response1.status_code == 200
        assert response2.status_code == 200
        
        # Pages should have different runs
        run_ids1 = {r["run_id"] for r in data1["runs"]}
        run_ids2 = {r["run_id"] for r in data2["runs"]}
        assert run_ids1.isdisjoint(run_ids2)
    
    def test_validates_limit_min(self, mock_manager):
        """Validates minimum limit value."""
        set_replay_manager(mock_manager)
        
        response = client.get("/api/replay/runs?limit=0")
        
        assert response.status_code == 422  # Validation error
    
    def test_validates_limit_max(self, mock_manager):
        """Validates maximum limit value."""
        set_replay_manager(mock_manager)
        
        response = client.get("/api/replay/runs?limit=1001")
        
        assert response.status_code == 422  # Validation error
    
    def test_run_summary_fields(self, mock_manager_with_reports):
        """Verifies all expected fields in run summary."""
        set_replay_manager(mock_manager_with_reports)
        
        response = client.get("/api/replay/runs")
        
        assert response.status_code == 200
        data = response.json()
        run = data["runs"][0]
        
        assert "run_id" in run
        assert "run_at" in run
        assert "start_time" in run
        assert "end_time" in run
        assert "total_replayed" in run
        assert "match_rate" in run
        assert "has_degradations" in run
        assert "is_passing" in run


# =============================================================================
# Module State Management Tests
# =============================================================================

class TestModuleState:
    """Tests for module-level state management functions."""
    
    def test_set_and_get_replay_manager(self, mock_manager):
        """Can set and get replay manager."""
        assert get_replay_manager() is None
        
        set_replay_manager(mock_manager)
        
        assert get_replay_manager() is mock_manager
    
    def test_set_and_get_pending_run(self):
        """Can set and get pending run."""
        assert get_pending_run("test_run") is None
        
        set_pending_run("test_run", {"status": "queued"})
        
        pending = get_pending_run("test_run")
        assert pending is not None
        assert pending["status"] == "queued"
    
    def test_remove_pending_run(self):
        """Can remove pending run."""
        set_pending_run("test_run", {"status": "queued"})
        
        remove_pending_run("test_run")
        
        assert get_pending_run("test_run") is None
    
    def test_clear_pending_runs(self):
        """Can clear all pending runs."""
        set_pending_run("run1", {"status": "queued"})
        set_pending_run("run2", {"status": "running"})
        
        clear_pending_runs()
        
        assert get_pending_run("run1") is None
        assert get_pending_run("run2") is None


# =============================================================================
# Helper Function Tests
# =============================================================================

class TestHelperFunctions:
    """Tests for helper functions."""
    
    def test_report_to_response(self, sample_report):
        """Converts ReplayReport to ReplayReportResponse correctly."""
        response = _report_to_response(sample_report)
        
        assert response.run_id == sample_report.run_id
        assert response.total_replayed == sample_report.total_replayed
        assert response.matches == sample_report.matches
        assert response.changes == sample_report.changes
        assert response.match_rate == sample_report.match_rate
        
        # Check changes_by_category conversion
        categories = {c.category: c.count for c in response.changes_by_category}
        assert categories == sample_report.changes_by_category
        
        # Check changes_by_stage conversion
        stages = {s.stage_diff: s.count for s in response.changes_by_stage}
        assert stages == sample_report.changes_by_stage
    
    def test_report_to_summary(self, sample_report):
        """Converts ReplayReport to ReplayRunSummary correctly."""
        summary = _report_to_summary(sample_report)
        
        assert summary.run_id == sample_report.run_id
        assert summary.total_replayed == sample_report.total_replayed
        assert summary.match_rate == sample_report.match_rate
        assert summary.has_degradations == sample_report.has_degradations()
        assert summary.is_passing == sample_report.is_passing()
