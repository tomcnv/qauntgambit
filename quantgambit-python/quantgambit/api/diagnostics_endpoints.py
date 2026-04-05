"""
Strategy Diagnostics API Endpoints

Provides API endpoints for strategy diagnostics including:
- Per-strategy metrics with rates
- Predicate-level failure breakdown
- Bottleneck identification

Requirement 7.11: StrategyDiagnostics SHALL be accessible via API endpoint /api/v1/diagnostics/strategies
Requirement 7.12: API response SHALL include both aggregate rates AND predicate-level failure breakdown
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from quantgambit.signals.services.strategy_diagnostics import (
    StrategyDiagnostics,
    StrategyMetrics,
    get_strategy_diagnostics,
)

logger = logging.getLogger(__name__)


# =============================================================================
# Pydantic Models
# =============================================================================

class FailureBreakdownResponse(BaseModel):
    """Predicate-level failure breakdown."""
    fail_distance: int = Field(0, description="Failed due to distance threshold")
    fail_spread: int = Field(0, description="Failed due to spread too wide")
    fail_flow: int = Field(0, description="Failed due to flow_rotation not confirming")
    fail_trend: int = Field(0, description="Failed due to adverse trend_bias")
    fail_ev: int = Field(0, description="Failed due to EV below threshold")
    fail_cost: int = Field(0, description="Failed due to costs exceeding potential profit")
    fail_data: int = Field(0, description="Failed due to missing or invalid data")


class TopFailureResponse(BaseModel):
    """Top failure predicate."""
    type: str = Field(..., description="Failure type (e.g., 'fail_flow')")
    count: int = Field(..., description="Number of failures")


class StrategyMetricsResponse(BaseModel):
    """Metrics for a single strategy.
    
    Requirement 7.1: Track per-strategy counters
    Requirement 7.2: Track predicate-level failure counters
    Requirement 7.3: Compute rates
    """
    strategy_id: str = Field(..., description="Strategy identifier")
    
    # Pipeline stage counters (Requirement 7.1)
    tick_count: int = Field(0, description="Number of ticks processed")
    setup_count: int = Field(0, description="Number of setups detected (CandidateSignal emitted)")
    confirm_count: int = Field(0, description="Number of confirmations passed")
    ev_pass_count: int = Field(0, description="Number of signals that passed EVGate")
    signal_count: int = Field(0, description="Number of signals sent for execution")
    
    # Rates (Requirement 7.3)
    setup_rate: float = Field(0.0, description="setup_count / tick_count")
    confirm_rate: float = Field(0.0, description="confirm_count / setup_count")
    ev_rate: float = Field(0.0, description="ev_pass_count / confirm_count")
    execution_rate: float = Field(0.0, description="signal_count / ev_pass_count")
    
    # Bottleneck (Requirement 7.8)
    bottleneck: str = Field("unknown", description="Pipeline stage with lowest pass rate")
    
    # Failure breakdown (Requirement 7.9)
    failure_breakdown: FailureBreakdownResponse = Field(
        default_factory=FailureBreakdownResponse,
        description="Predicate-level failure counts"
    )
    
    # Top failures
    top_failures: List[TopFailureResponse] = Field(
        default_factory=list,
        description="Top 3 failure predicates by count"
    )


class AggregateMetricsResponse(BaseModel):
    """Aggregate metrics across all strategies."""
    total_ticks: int = Field(0, description="Total ticks across all strategies")
    total_setups: int = Field(0, description="Total setups across all strategies")
    total_confirms: int = Field(0, description="Total confirmations across all strategies")
    total_ev_passes: int = Field(0, description="Total EV passes across all strategies")
    total_signals: int = Field(0, description="Total signals across all strategies")
    
    overall_setup_rate: float = Field(0.0, description="Overall setup rate")
    overall_confirm_rate: float = Field(0.0, description="Overall confirmation rate")
    overall_ev_rate: float = Field(0.0, description="Overall EV pass rate")
    overall_execution_rate: float = Field(0.0, description="Overall execution rate")


class StrategyDiagnosticsResponse(BaseModel):
    """
    Response for strategy diagnostics endpoint.
    
    Requirement 7.11: Accessible via API endpoint /api/v1/diagnostics/strategies
    Requirement 7.12: Include both aggregate rates AND predicate-level failure breakdown
    """
    strategies: List[StrategyMetricsResponse] = Field(
        default_factory=list,
        description="Per-strategy metrics"
    )
    aggregate: AggregateMetricsResponse = Field(
        default_factory=AggregateMetricsResponse,
        description="Aggregate metrics across all strategies"
    )
    tick_counter: int = Field(0, description="Global tick counter")
    log_interval: int = Field(1000, description="Ticks between diagnostic log summaries")


class BottleneckResponse(BaseModel):
    """Response for bottleneck endpoint."""
    strategy_id: str = Field(..., description="Strategy identifier")
    bottleneck: str = Field(..., description="Bottleneck stage: 'setup', 'confirm', 'ev', 'execution', or 'none'")


class FailureBreakdownDetailResponse(BaseModel):
    """Detailed failure breakdown response."""
    strategy_id: str = Field(..., description="Strategy identifier")
    breakdown: FailureBreakdownResponse = Field(..., description="Failure counts by predicate")
    top_failures: List[TopFailureResponse] = Field(
        default_factory=list,
        description="Top failure predicates by count"
    )


# =============================================================================
# Helper Functions
# =============================================================================

def _metrics_to_response(metrics: StrategyMetrics) -> StrategyMetricsResponse:
    """Convert StrategyMetrics to API response model."""
    breakdown = metrics.get_failure_breakdown()
    top_failures = metrics.get_top_failures(3)
    
    return StrategyMetricsResponse(
        strategy_id=metrics.strategy_id,
        tick_count=metrics.tick_count,
        setup_count=metrics.setup_count,
        confirm_count=metrics.confirm_count,
        ev_pass_count=metrics.ev_pass_count,
        signal_count=metrics.signal_count,
        setup_rate=round(metrics.setup_rate, 6),
        confirm_rate=round(metrics.confirm_rate, 6),
        ev_rate=round(metrics.ev_rate, 6),
        execution_rate=round(metrics.execution_rate, 6),
        bottleneck=metrics.get_bottleneck(),
        failure_breakdown=FailureBreakdownResponse(
            fail_distance=breakdown.get("fail_distance", 0),
            fail_spread=breakdown.get("fail_spread", 0),
            fail_flow=breakdown.get("fail_flow", 0),
            fail_trend=breakdown.get("fail_trend", 0),
            fail_ev=breakdown.get("fail_ev", 0),
            fail_cost=breakdown.get("fail_cost", 0),
            fail_data=breakdown.get("fail_data", 0),
        ),
        top_failures=[
            TopFailureResponse(type=f[0], count=f[1])
            for f in top_failures if f[1] > 0
        ],
    )


# =============================================================================
# Router
# =============================================================================

router = APIRouter(prefix="/api/v1/diagnostics", tags=["diagnostics"])


# =============================================================================
# Strategy Diagnostics Endpoint
# Requirement 7.11: Accessible via API endpoint /api/v1/diagnostics/strategies
# =============================================================================

@router.get("/strategies", response_model=StrategyDiagnosticsResponse)
async def get_strategy_diagnostics_endpoint(
    strategy_id: Optional[str] = Query(
        None,
        description="Filter by strategy ID. If not provided, returns all strategies."
    ),
) -> StrategyDiagnosticsResponse:
    """
    Get strategy diagnostics with per-strategy metrics and failure breakdown.
    
    Requirement 7.11: StrategyDiagnostics SHALL be accessible via API endpoint
    /api/v1/diagnostics/strategies
    
    Requirement 7.12: API response SHALL include both aggregate rates AND
    predicate-level failure breakdown
    
    Returns:
        StrategyDiagnosticsResponse with:
        - strategies: List of per-strategy metrics
        - aggregate: Aggregate metrics across all strategies
        - tick_counter: Global tick counter
        - log_interval: Ticks between diagnostic log summaries
    """
    diagnostics = get_strategy_diagnostics()
    
    if strategy_id:
        # Return single strategy
        metrics = diagnostics.get_metrics(strategy_id)
        if metrics is None:
            raise HTTPException(
                status_code=404,
                detail=f"Strategy '{strategy_id}' not found"
            )
        
        strategies = [_metrics_to_response(metrics)]
        aggregate = AggregateMetricsResponse(
            total_ticks=metrics.tick_count,
            total_setups=metrics.setup_count,
            total_confirms=metrics.confirm_count,
            total_ev_passes=metrics.ev_pass_count,
            total_signals=metrics.signal_count,
            overall_setup_rate=round(metrics.setup_rate, 6),
            overall_confirm_rate=round(metrics.confirm_rate, 6),
            overall_ev_rate=round(metrics.ev_rate, 6),
            overall_execution_rate=round(metrics.execution_rate, 6),
        )
    else:
        # Return all strategies
        all_metrics = diagnostics.get_all_metrics()
        strategies = [
            _metrics_to_response(m)
            for m in all_metrics.values()
        ]
        
        # Calculate aggregates
        total_ticks = sum(m.tick_count for m in all_metrics.values())
        total_setups = sum(m.setup_count for m in all_metrics.values())
        total_confirms = sum(m.confirm_count for m in all_metrics.values())
        total_ev_passes = sum(m.ev_pass_count for m in all_metrics.values())
        total_signals = sum(m.signal_count for m in all_metrics.values())
        
        aggregate = AggregateMetricsResponse(
            total_ticks=total_ticks,
            total_setups=total_setups,
            total_confirms=total_confirms,
            total_ev_passes=total_ev_passes,
            total_signals=total_signals,
            overall_setup_rate=round(total_setups / total_ticks, 6) if total_ticks > 0 else 0.0,
            overall_confirm_rate=round(total_confirms / total_setups, 6) if total_setups > 0 else 0.0,
            overall_ev_rate=round(total_ev_passes / total_confirms, 6) if total_confirms > 0 else 0.0,
            overall_execution_rate=round(total_signals / total_ev_passes, 6) if total_ev_passes > 0 else 0.0,
        )
    
    api_response = diagnostics.get_api_response()
    
    return StrategyDiagnosticsResponse(
        strategies=strategies,
        aggregate=aggregate,
        tick_counter=api_response.get("tick_counter", 0),
        log_interval=api_response.get("log_interval", 1000),
    )


@router.get("/strategies/{strategy_id}/bottleneck", response_model=BottleneckResponse)
async def get_strategy_bottleneck(
    strategy_id: str,
) -> BottleneckResponse:
    """
    Get the bottleneck stage for a specific strategy.
    
    Requirement 7.8: Expose get_bottleneck(strategy_id) returning
    "setup", "confirm", "ev", or "execution"
    
    Args:
        strategy_id: Strategy identifier
        
    Returns:
        BottleneckResponse with strategy_id and bottleneck stage
    """
    diagnostics = get_strategy_diagnostics()
    bottleneck = diagnostics.get_bottleneck(strategy_id)
    
    if bottleneck == "unknown":
        raise HTTPException(
            status_code=404,
            detail=f"Strategy '{strategy_id}' not found"
        )
    
    return BottleneckResponse(
        strategy_id=strategy_id,
        bottleneck=bottleneck,
    )


@router.get("/strategies/{strategy_id}/failures", response_model=FailureBreakdownDetailResponse)
async def get_strategy_failure_breakdown(
    strategy_id: str,
    top_n: int = Query(3, ge=1, le=10, description="Number of top failures to return"),
) -> FailureBreakdownDetailResponse:
    """
    Get predicate-level failure breakdown for a specific strategy.
    
    Requirement 7.9: Expose get_failure_breakdown(strategy_id) returning
    counts for each fail_* predicate
    
    Args:
        strategy_id: Strategy identifier
        top_n: Number of top failures to return (default 3)
        
    Returns:
        FailureBreakdownDetailResponse with breakdown and top failures
    """
    diagnostics = get_strategy_diagnostics()
    metrics = diagnostics.get_metrics(strategy_id)
    
    if metrics is None:
        raise HTTPException(
            status_code=404,
            detail=f"Strategy '{strategy_id}' not found"
        )
    
    breakdown = metrics.get_failure_breakdown()
    top_failures = metrics.get_top_failures(top_n)
    
    return FailureBreakdownDetailResponse(
        strategy_id=strategy_id,
        breakdown=FailureBreakdownResponse(
            fail_distance=breakdown.get("fail_distance", 0),
            fail_spread=breakdown.get("fail_spread", 0),
            fail_flow=breakdown.get("fail_flow", 0),
            fail_trend=breakdown.get("fail_trend", 0),
            fail_ev=breakdown.get("fail_ev", 0),
            fail_cost=breakdown.get("fail_cost", 0),
            fail_data=breakdown.get("fail_data", 0),
        ),
        top_failures=[
            TopFailureResponse(type=f[0], count=f[1])
            for f in top_failures if f[1] > 0
        ],
    )
