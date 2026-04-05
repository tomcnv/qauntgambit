"""Replay validation API endpoints for trading pipeline integration.

Feature: trading-pipeline-integration
Requirements: 7.4 - WHEN pipeline code changes THEN the System SHALL support
              running replay validation as part of CI/CD

This module provides REST API endpoints for:
- POST /api/replay/run - Trigger a replay validation run
- GET /api/replay/results/{run_id} - Get results of a replay run
- GET /api/replay/runs - List recent replay runs with pagination
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

from fastapi import APIRouter, Query, HTTPException, BackgroundTasks
from pydantic import BaseModel, Field

from quantgambit.integration.replay_validation import (
    ReplayReport,
    ReplayResult,
    ReplayManager,
)


# ============================================================================
# Request/Response Models
# ============================================================================

class ReplayRunRequest(BaseModel):
    """Request model for triggering a replay run.
    
    Feature: trading-pipeline-integration
    Requirements: 7.4
    """
    start_time: datetime = Field(
        ...,
        description="Start of time range to replay (ISO format)"
    )
    end_time: datetime = Field(
        ...,
        description="End of time range to replay (ISO format)"
    )
    symbol: Optional[str] = Field(
        None,
        description="Optional filter by trading symbol"
    )
    decision_filter: Optional[str] = Field(
        None,
        description="Optional filter by decision outcome ('accepted' or 'rejected')"
    )
    max_decisions: int = Field(
        10000,
        ge=1,
        le=100000,
        description="Maximum number of decisions to replay"
    )


class ReplayRunResponse(BaseModel):
    """Response model for replay run initiation.
    
    Feature: trading-pipeline-integration
    Requirements: 7.4
    """
    run_id: str = Field(..., description="Unique identifier for this replay run")
    status: str = Field(..., description="Status of the replay run ('queued', 'running', 'completed', 'failed')")
    message: str = Field(..., description="Human-readable status message")


class ChangeCategoryCount(BaseModel):
    """Count of changes by category."""
    category: str = Field(..., description="Change category (expected, unexpected, improved, degraded)")
    count: int = Field(..., description="Number of changes in this category")


class StageDiffCount(BaseModel):
    """Count of changes by stage difference."""
    stage_diff: str = Field(..., description="Stage difference (e.g., 'ev_gate->data_readiness')")
    count: int = Field(..., description="Number of changes with this stage difference")


class SampleChangeResponse(BaseModel):
    """Response model for a sample changed decision."""
    original_decision_id: str = Field(..., description="ID of the original decision")
    original_symbol: str = Field(..., description="Symbol of the original decision")
    original_timestamp: str = Field(..., description="Timestamp of the original decision (ISO format)")
    original_decision: str = Field(..., description="Original decision outcome")
    replayed_decision: str = Field(..., description="Replayed decision outcome")
    change_category: str = Field(..., description="Category of change")
    stage_diff: Optional[str] = Field(None, description="Stage difference if any")


class ReplayReportResponse(BaseModel):
    """Response model for replay report.
    
    Feature: trading-pipeline-integration
    Requirements: 7.4
    """
    run_id: Optional[str] = Field(None, description="Unique identifier for this replay run")
    run_at: Optional[str] = Field(None, description="When the replay was executed (ISO format)")
    start_time: Optional[str] = Field(None, description="Start of replayed time range (ISO format)")
    end_time: Optional[str] = Field(None, description="End of replayed time range (ISO format)")
    total_replayed: int = Field(..., description="Total number of decisions replayed")
    matches: int = Field(..., description="Number of decisions that matched original outcome")
    changes: int = Field(..., description="Number of decisions that changed from original outcome")
    match_rate: float = Field(..., description="Ratio of matches to total (0.0 to 1.0)")
    changes_by_category: List[ChangeCategoryCount] = Field(
        default_factory=list,
        description="Count of changes by category"
    )
    changes_by_stage: List[StageDiffCount] = Field(
        default_factory=list,
        description="Count of changes by stage difference"
    )
    sample_changes: List[SampleChangeResponse] = Field(
        default_factory=list,
        description="Sample of changed decisions for review"
    )
    has_degradations: bool = Field(False, description="Whether any changes are degradations")
    has_improvements: bool = Field(False, description="Whether any changes are improvements")
    is_passing: bool = Field(True, description="Whether the replay validation passes (degradation rate < 5%)")


class ReplayRunSummary(BaseModel):
    """Summary of a replay run for listing."""
    run_id: str = Field(..., description="Unique identifier for this replay run")
    run_at: str = Field(..., description="When the replay was executed (ISO format)")
    start_time: Optional[str] = Field(None, description="Start of replayed time range (ISO format)")
    end_time: Optional[str] = Field(None, description="End of replayed time range (ISO format)")
    total_replayed: int = Field(..., description="Total number of decisions replayed")
    match_rate: float = Field(..., description="Ratio of matches to total (0.0 to 1.0)")
    has_degradations: bool = Field(False, description="Whether any changes are degradations")
    is_passing: bool = Field(True, description="Whether the replay validation passes")


class ReplayRunListResponse(BaseModel):
    """Response model for listing replay runs."""
    runs: List[ReplayRunSummary] = Field(
        default_factory=list,
        description="List of replay run summaries"
    )
    total: int = Field(..., description="Total number of runs")
    limit: int = Field(..., description="Limit used for pagination")
    offset: int = Field(..., description="Offset used for pagination")


# ============================================================================
# Module-level state for replay manager
# ============================================================================

# Global replay manager instance - will be set by the runtime
_replay_manager: Optional[ReplayManager] = None

# In-memory storage for pending/running replay runs
_pending_runs: Dict[str, Dict[str, Any]] = {}


def set_replay_manager(manager: Optional[ReplayManager]) -> None:
    """Set the global replay manager instance.
    
    Called by the runtime when replay functionality is enabled.
    
    Args:
        manager: The ReplayManager instance or None to disable
    """
    global _replay_manager
    _replay_manager = manager


def get_replay_manager() -> Optional[ReplayManager]:
    """Get the global replay manager instance.
    
    Returns:
        The ReplayManager instance or None if not enabled
    """
    return _replay_manager


def get_pending_run(run_id: str) -> Optional[Dict[str, Any]]:
    """Get a pending run by ID.
    
    Args:
        run_id: The run ID to look up
        
    Returns:
        The pending run info or None if not found
    """
    return _pending_runs.get(run_id)


def set_pending_run(run_id: str, info: Dict[str, Any]) -> None:
    """Set a pending run.
    
    Args:
        run_id: The run ID
        info: The run info dictionary
    """
    _pending_runs[run_id] = info


def remove_pending_run(run_id: str) -> None:
    """Remove a pending run.
    
    Args:
        run_id: The run ID to remove
    """
    _pending_runs.pop(run_id, None)


def clear_pending_runs() -> None:
    """Clear all pending runs."""
    _pending_runs.clear()


# ============================================================================
# Helper Functions
# ============================================================================

def _report_to_response(report: ReplayReport) -> ReplayReportResponse:
    """Convert a ReplayReport to a ReplayReportResponse.
    
    Args:
        report: The ReplayReport to convert
        
    Returns:
        ReplayReportResponse instance
    """
    # Convert changes_by_category dict to list of ChangeCategoryCount
    changes_by_category = [
        ChangeCategoryCount(category=cat, count=count)
        for cat, count in sorted(report.changes_by_category.items())
    ]
    
    # Convert changes_by_stage dict to list of StageDiffCount
    changes_by_stage = [
        StageDiffCount(stage_diff=diff, count=count)
        for diff, count in sorted(report.changes_by_stage.items())
    ]
    
    # Convert sample_changes to response format
    sample_changes = []
    for result in report.sample_changes:
        sample_changes.append(SampleChangeResponse(
            original_decision_id=result.get_original_decision_id(),
            original_symbol=result.get_original_symbol(),
            original_timestamp=result.get_original_timestamp().isoformat(),
            original_decision=result.original_decision.decision,
            replayed_decision=result.replayed_decision,
            change_category=result.change_category,
            stage_diff=result.stage_diff,
        ))
    
    return ReplayReportResponse(
        run_id=report.run_id,
        run_at=report.run_at.isoformat() if report.run_at else None,
        start_time=report.start_time.isoformat() if report.start_time else None,
        end_time=report.end_time.isoformat() if report.end_time else None,
        total_replayed=report.total_replayed,
        matches=report.matches,
        changes=report.changes,
        match_rate=report.match_rate,
        changes_by_category=changes_by_category,
        changes_by_stage=changes_by_stage,
        sample_changes=sample_changes,
        has_degradations=report.has_degradations(),
        has_improvements=report.has_improvements(),
        is_passing=report.is_passing(),
    )


def _report_to_summary(report: ReplayReport) -> ReplayRunSummary:
    """Convert a ReplayReport to a ReplayRunSummary.
    
    Args:
        report: The ReplayReport to convert
        
    Returns:
        ReplayRunSummary instance
    """
    return ReplayRunSummary(
        run_id=report.run_id or "unknown",
        run_at=report.run_at.isoformat() if report.run_at else datetime.now(timezone.utc).isoformat(),
        start_time=report.start_time.isoformat() if report.start_time else None,
        end_time=report.end_time.isoformat() if report.end_time else None,
        total_replayed=report.total_replayed,
        match_rate=report.match_rate,
        has_degradations=report.has_degradations(),
        is_passing=report.is_passing(),
    )


async def _run_replay_async(
    run_id: str,
    manager: ReplayManager,
    start_time: datetime,
    end_time: datetime,
    symbol: Optional[str],
    decision_filter: Optional[str],
    max_decisions: int,
) -> None:
    """Run replay validation asynchronously.
    
    This function is executed as a background task.
    
    Args:
        run_id: The run ID for this replay
        manager: The ReplayManager instance
        start_time: Start of time range
        end_time: End of time range
        symbol: Optional symbol filter
        decision_filter: Optional decision filter
        max_decisions: Maximum decisions to replay
    """
    try:
        # Update status to running
        set_pending_run(run_id, {
            "status": "running",
            "started_at": datetime.now(timezone.utc).isoformat(),
        })
        
        # Run the replay
        report = await manager.replay_range(
            start_time=start_time,
            end_time=end_time,
            symbol=symbol,
            decision_filter=decision_filter,
            max_decisions=max_decisions,
        )
        
        # Override the run_id to match our generated one
        # (ReplayManager generates its own, but we want to use ours for tracking)
        object.__setattr__(report, 'run_id', run_id)
        
        # Save the report to the database
        await manager.save_report(report)
        
        # Update status to completed
        set_pending_run(run_id, {
            "status": "completed",
            "completed_at": datetime.now(timezone.utc).isoformat(),
        })
        
    except Exception as e:
        # Update status to failed
        set_pending_run(run_id, {
            "status": "failed",
            "error": str(e),
            "failed_at": datetime.now(timezone.utc).isoformat(),
        })


# ============================================================================
# Router
# ============================================================================

router = APIRouter(prefix="/api/replay", tags=["replay"])


@router.post("/run", response_model=ReplayRunResponse)
async def trigger_replay_run(
    request: ReplayRunRequest,
    background_tasks: BackgroundTasks,
) -> ReplayRunResponse:
    """Trigger a replay validation run.
    
    Initiates an asynchronous replay of recorded decisions through the current
    pipeline. The replay runs in the background and results can be retrieved
    using the GET /api/replay/results/{run_id} endpoint.
    
    Feature: trading-pipeline-integration
    Requirements: 7.4 - WHEN pipeline code changes THEN the System SHALL support
                  running replay validation as part of CI/CD
    
    Args:
        request: ReplayRunRequest with time range and filters
        background_tasks: FastAPI background tasks for async execution
        
    Returns:
        ReplayRunResponse with run_id and status
        
    Raises:
        HTTPException: 503 if replay functionality is not enabled
        HTTPException: 400 if decision_filter is invalid
    """
    manager = get_replay_manager()
    
    if manager is None:
        raise HTTPException(
            status_code=503,
            detail="Replay functionality is not enabled. Configure ReplayManager to access this endpoint."
        )
    
    # Validate decision_filter if provided
    if request.decision_filter is not None:
        if request.decision_filter not in ("accepted", "rejected"):
            raise HTTPException(
                status_code=400,
                detail=f"decision_filter must be 'accepted' or 'rejected', got '{request.decision_filter}'"
            )
    
    # Ensure timestamps have timezone info
    start_time = request.start_time
    end_time = request.end_time
    
    if start_time.tzinfo is None:
        start_time = start_time.replace(tzinfo=timezone.utc)
    if end_time.tzinfo is None:
        end_time = end_time.replace(tzinfo=timezone.utc)
    
    # Validate time range
    if start_time >= end_time:
        raise HTTPException(
            status_code=400,
            detail="start_time must be before end_time"
        )
    
    # Generate run_id
    run_id = f"replay_{uuid4().hex[:12]}"
    
    # Store pending run info
    set_pending_run(run_id, {
        "status": "queued",
        "queued_at": datetime.now(timezone.utc).isoformat(),
        "start_time": start_time.isoformat(),
        "end_time": end_time.isoformat(),
        "symbol": request.symbol,
        "decision_filter": request.decision_filter,
        "max_decisions": request.max_decisions,
    })
    
    # Schedule background task
    background_tasks.add_task(
        _run_replay_async,
        run_id=run_id,
        manager=manager,
        start_time=start_time,
        end_time=end_time,
        symbol=request.symbol,
        decision_filter=request.decision_filter,
        max_decisions=request.max_decisions,
    )
    
    return ReplayRunResponse(
        run_id=run_id,
        status="queued",
        message="Replay validation run has been queued for execution",
    )


@router.get("/results/{run_id}", response_model=ReplayReportResponse)
async def get_replay_results(run_id: str) -> ReplayReportResponse:
    """Get results of a replay run.
    
    Retrieves the results of a previously triggered replay validation run.
    If the run is still in progress, returns the current status.
    
    Feature: trading-pipeline-integration
    Requirements: 7.4
    
    Args:
        run_id: The unique identifier of the replay run
        
    Returns:
        ReplayReportResponse with the replay results
        
    Raises:
        HTTPException: 503 if replay functionality is not enabled
        HTTPException: 404 if run_id is not found
        HTTPException: 202 if run is still in progress
    """
    manager = get_replay_manager()
    
    if manager is None:
        raise HTTPException(
            status_code=503,
            detail="Replay functionality is not enabled. Configure ReplayManager to access this endpoint."
        )
    
    # Check if run is pending/running
    pending = get_pending_run(run_id)
    if pending is not None:
        status = pending.get("status", "unknown")
        if status in ("queued", "running"):
            raise HTTPException(
                status_code=202,
                detail=f"Replay run is still {status}. Please try again later.",
                headers={"Retry-After": "5"},
            )
        elif status == "failed":
            raise HTTPException(
                status_code=500,
                detail=f"Replay run failed: {pending.get('error', 'Unknown error')}",
            )
    
    # Try to get from database
    report = await manager.get_report(run_id)
    
    if report is None:
        raise HTTPException(
            status_code=404,
            detail=f"Replay run with id '{run_id}' not found",
        )
    
    return _report_to_response(report)


@router.get("/runs", response_model=ReplayRunListResponse)
async def list_replay_runs(
    limit: int = Query(
        100,
        ge=1,
        le=1000,
        description="Maximum number of runs to return"
    ),
    offset: int = Query(
        0,
        ge=0,
        description="Number of runs to skip for pagination"
    ),
) -> ReplayRunListResponse:
    """List recent replay runs with pagination.
    
    Returns a paginated list of replay validation runs, ordered by run_at
    descending (most recent first).
    
    Feature: trading-pipeline-integration
    Requirements: 7.4
    
    Args:
        limit: Maximum number of runs to return (1-1000)
        offset: Number of runs to skip for pagination
        
    Returns:
        ReplayRunListResponse with list of run summaries
        
    Raises:
        HTTPException: 503 if replay functionality is not enabled
    """
    manager = get_replay_manager()
    
    if manager is None:
        raise HTTPException(
            status_code=503,
            detail="Replay functionality is not enabled. Configure ReplayManager to access this endpoint."
        )
    
    # Get reports from database
    reports = await manager.list_reports(limit=limit, offset=offset)
    
    # Convert to summaries
    summaries = [_report_to_summary(report) for report in reports]
    
    return ReplayRunListResponse(
        runs=summaries,
        total=len(summaries),  # Note: This is the count returned, not total in DB
        limit=limit,
        offset=offset,
    )
