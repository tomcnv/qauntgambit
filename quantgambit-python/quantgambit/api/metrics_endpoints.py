"""Metrics comparison API endpoints for trading pipeline integration.

Feature: trading-pipeline-integration
Requirements: 9.3 - THE System SHALL support side-by-side comparison reports
              showing live vs backtest metrics

This module provides REST API endpoints for:
- GET /api/metrics/compare - Compare live vs backtest metrics by run_id
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Query, HTTPException
from pydantic import BaseModel, Field

from quantgambit.integration.unified_metrics import (
    UnifiedMetrics,
    MetricsComparison,
    MetricsReconciler,
)


# ============================================================================
# Response Models
# ============================================================================

class UnifiedMetricsResponse(BaseModel):
    """Response model for unified metrics.
    
    Feature: trading-pipeline-integration
    Requirements: 9.1
    """
    # Return metrics
    total_return_pct: float = Field(..., description="Total return as percentage")
    annualized_return_pct: float = Field(..., description="Annualized return as percentage")
    
    # Risk metrics
    sharpe_ratio: float = Field(..., description="Risk-adjusted return (Sharpe ratio)")
    sortino_ratio: float = Field(..., description="Downside risk-adjusted return (Sortino ratio)")
    max_drawdown_pct: float = Field(..., description="Maximum peak-to-trough decline as percentage")
    max_drawdown_duration_sec: float = Field(..., description="Duration of max drawdown in seconds")
    
    # Trade metrics
    total_trades: int = Field(..., description="Total number of completed trades")
    winning_trades: int = Field(..., description="Number of profitable trades")
    losing_trades: int = Field(..., description="Number of unprofitable trades")
    win_rate: float = Field(..., description="Ratio of winning trades to total (0.0 to 1.0)")
    profit_factor: float = Field(..., description="Gross profit / gross loss ratio")
    avg_trade_pnl: float = Field(0.0, description="Average profit/loss per trade")
    avg_win_pct: float = Field(..., description="Average percentage gain on winning trades")
    avg_loss_pct: float = Field(..., description="Average percentage loss on losing trades")
    
    # Execution metrics
    avg_slippage_bps: float = Field(..., description="Average slippage in basis points")
    avg_latency_ms: float = Field(..., description="Average execution latency in milliseconds")
    partial_fill_rate: float = Field(..., description="Rate of partial fills (0.0 to 1.0)")


class MetricDifferenceResponse(BaseModel):
    """Response model for a single metric difference."""
    live: float = Field(..., description="Value from live trading")
    backtest: float = Field(..., description="Value from backtesting")
    diff_pct: float = Field(..., description="Percentage difference ((backtest - live) / live * 100)")
    significant: bool = Field(..., description="Whether difference exceeds 10% threshold")


class MetricsComparisonResponse(BaseModel):
    """Response model for metrics comparison.
    
    Feature: trading-pipeline-integration
    Requirements: 9.3, 9.4, 9.6
    """
    live_metrics: UnifiedMetricsResponse = Field(
        ...,
        description="Metrics from live trading"
    )
    backtest_metrics: UnifiedMetricsResponse = Field(
        ...,
        description="Metrics from backtesting"
    )
    significant_differences: Dict[str, MetricDifferenceResponse] = Field(
        default_factory=dict,
        description="Metrics with >10% difference"
    )
    divergence_factors: List[str] = Field(
        default_factory=list,
        description="Identified factors contributing to divergence"
    )
    overall_similarity: float = Field(
        ...,
        description="Overall similarity score (0.0 to 1.0, where 1.0 is identical)"
    )
    comparison_timestamp: str = Field(
        ...,
        description="When the comparison was performed (ISO format)"
    )
    has_significant_differences: bool = Field(
        ...,
        description="Whether any metrics differ by more than 10%"
    )
    backtest_run_id: Optional[str] = Field(
        None,
        description="The backtest run ID used for comparison"
    )
    live_period_hours: Optional[float] = Field(
        None,
        description="The live data period in hours used for comparison"
    )


# ============================================================================
# Module-level state for metrics reconciler and data loaders
# ============================================================================

# Global metrics reconciler instance
_metrics_reconciler: Optional[MetricsReconciler] = None

# Callback functions for loading metrics data
# These will be set by the runtime to provide actual data loading
_load_live_metrics_callback: Optional[callable] = None
_load_backtest_metrics_callback: Optional[callable] = None


def set_metrics_reconciler(reconciler: Optional[MetricsReconciler]) -> None:
    """Set the global metrics reconciler instance.
    
    Called by the runtime when metrics functionality is enabled.
    
    Args:
        reconciler: The MetricsReconciler instance or None to disable
    """
    global _metrics_reconciler
    _metrics_reconciler = reconciler


def get_metrics_reconciler() -> Optional[MetricsReconciler]:
    """Get the global metrics reconciler instance.
    
    Returns:
        The MetricsReconciler instance or None if not enabled
    """
    return _metrics_reconciler


def set_load_live_metrics_callback(callback: Optional[callable]) -> None:
    """Set the callback for loading live metrics.
    
    Args:
        callback: Async function that takes (period_hours: float) and returns UnifiedMetrics
    """
    global _load_live_metrics_callback
    _load_live_metrics_callback = callback


def get_load_live_metrics_callback() -> Optional[callable]:
    """Get the callback for loading live metrics."""
    return _load_live_metrics_callback


def set_load_backtest_metrics_callback(callback: Optional[callable]) -> None:
    """Set the callback for loading backtest metrics.
    
    Args:
        callback: Async function that takes (run_id: str) and returns UnifiedMetrics
    """
    global _load_backtest_metrics_callback
    _load_backtest_metrics_callback = callback


def get_load_backtest_metrics_callback() -> Optional[callable]:
    """Get the callback for loading backtest metrics."""
    return _load_backtest_metrics_callback


def clear_metrics_state() -> None:
    """Clear all metrics state. Used for testing."""
    global _metrics_reconciler, _load_live_metrics_callback, _load_backtest_metrics_callback
    _metrics_reconciler = None
    _load_live_metrics_callback = None
    _load_backtest_metrics_callback = None


# ============================================================================
# Helper Functions
# ============================================================================

def _unified_metrics_to_response(metrics: UnifiedMetrics) -> UnifiedMetricsResponse:
    """Convert UnifiedMetrics to response model.
    
    Args:
        metrics: The UnifiedMetrics instance to convert
        
    Returns:
        UnifiedMetricsResponse instance
    """
    return UnifiedMetricsResponse(
        total_return_pct=metrics.total_return_pct,
        annualized_return_pct=metrics.annualized_return_pct,
        sharpe_ratio=metrics.sharpe_ratio,
        sortino_ratio=metrics.sortino_ratio if metrics.sortino_ratio != float('inf') else 999.99,
        max_drawdown_pct=metrics.max_drawdown_pct,
        max_drawdown_duration_sec=metrics.max_drawdown_duration_sec,
        total_trades=metrics.total_trades,
        winning_trades=metrics.winning_trades,
        losing_trades=metrics.losing_trades,
        win_rate=metrics.win_rate,
        profit_factor=metrics.profit_factor if metrics.profit_factor != float('inf') else 999.99,
        avg_trade_pnl=metrics.avg_trade_pnl,
        avg_win_pct=metrics.avg_win_pct,
        avg_loss_pct=metrics.avg_loss_pct,
        avg_slippage_bps=metrics.avg_slippage_bps,
        avg_latency_ms=metrics.avg_latency_ms,
        partial_fill_rate=metrics.partial_fill_rate,
    )


def _comparison_to_response(
    comparison: MetricsComparison,
    backtest_run_id: Optional[str] = None,
    live_period_hours: Optional[float] = None,
) -> MetricsComparisonResponse:
    """Convert MetricsComparison to response model.
    
    Args:
        comparison: The MetricsComparison instance to convert
        backtest_run_id: The backtest run ID used for comparison
        live_period_hours: The live data period in hours
        
    Returns:
        MetricsComparisonResponse instance
    """
    # Convert significant differences to response format
    sig_diffs = {}
    for metric_name, diff_info in comparison.significant_differences.items():
        sig_diffs[metric_name] = MetricDifferenceResponse(
            live=diff_info["live"],
            backtest=diff_info["backtest"],
            diff_pct=diff_info["diff_pct"],
            significant=diff_info.get("significant", True),
        )
    
    return MetricsComparisonResponse(
        live_metrics=_unified_metrics_to_response(comparison.live_metrics),
        backtest_metrics=_unified_metrics_to_response(comparison.backtest_metrics),
        significant_differences=sig_diffs,
        divergence_factors=comparison.divergence_factors,
        overall_similarity=comparison.overall_similarity,
        comparison_timestamp=comparison.comparison_timestamp.isoformat(),
        has_significant_differences=comparison.has_significant_differences(),
        backtest_run_id=backtest_run_id,
        live_period_hours=live_period_hours,
    )


# ============================================================================
# Router
# ============================================================================

router = APIRouter(prefix="/api/metrics", tags=["metrics"])


@router.get("/compare", response_model=MetricsComparisonResponse)
async def compare_metrics(
    backtest_run_id: str = Query(
        ...,
        description="The backtest run ID to compare against live metrics"
    ),
    live_period_hours: float = Query(
        24.0,
        ge=0.1,
        le=720.0,  # Max 30 days
        description="Hours of live data to use for comparison (default: 24 hours)"
    ),
) -> MetricsComparisonResponse:
    """Compare live trading metrics against backtest metrics.
    
    Retrieves metrics from both live trading (for the specified period) and
    a backtest run, then computes a detailed comparison including:
    - Side-by-side metrics values
    - Significant differences (>10%)
    - Divergence attribution factors
    - Overall similarity score
    
    Feature: trading-pipeline-integration
    Requirements: 9.3 - THE System SHALL support side-by-side comparison reports
                  showing live vs backtest metrics
    
    Args:
        backtest_run_id: The unique identifier of the backtest run to compare
        live_period_hours: Hours of live trading data to include (0.1 to 720)
        
    Returns:
        MetricsComparisonResponse with full comparison results
        
    Raises:
        HTTPException: 503 if metrics functionality is not enabled
        HTTPException: 404 if backtest run is not found
        HTTPException: 400 if no live data available for the specified period
    """
    reconciler = get_metrics_reconciler()
    
    if reconciler is None:
        raise HTTPException(
            status_code=503,
            detail="Metrics comparison functionality is not enabled. Configure MetricsReconciler to access this endpoint."
        )
    
    load_live = get_load_live_metrics_callback()
    load_backtest = get_load_backtest_metrics_callback()
    
    if load_live is None or load_backtest is None:
        raise HTTPException(
            status_code=503,
            detail="Metrics data loaders are not configured. Configure data loading callbacks to access this endpoint."
        )
    
    # Load backtest metrics
    try:
        backtest_metrics = await load_backtest(backtest_run_id)
    except Exception as e:
        if "not found" in str(e).lower():
            raise HTTPException(
                status_code=404,
                detail=f"Backtest run with id '{backtest_run_id}' not found"
            )
        raise HTTPException(
            status_code=500,
            detail=f"Failed to load backtest metrics: {str(e)}"
        )
    
    if backtest_metrics is None:
        raise HTTPException(
            status_code=404,
            detail=f"Backtest run with id '{backtest_run_id}' not found"
        )
    
    # Load live metrics
    try:
        live_metrics = await load_live(live_period_hours)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to load live metrics: {str(e)}"
        )
    
    if live_metrics is None:
        raise HTTPException(
            status_code=400,
            detail=f"No live trading data available for the last {live_period_hours} hours"
        )
    
    # Perform comparison
    comparison = reconciler.compare_metrics(live_metrics, backtest_metrics)
    
    return _comparison_to_response(
        comparison,
        backtest_run_id=backtest_run_id,
        live_period_hours=live_period_hours,
    )
