"""
EV Gate API Endpoints

Provides API endpoints for EV gate decision logs, aggregate metrics,
reject counters, and Prometheus metrics.

Requirements: 7.2, 7.3, 7.4, Non-functional observability
"""

import json
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

import redis.asyncio as redis

from quantgambit.signals.stages.ev_gate import EVGateRejectCode

logger = logging.getLogger(__name__)


# =============================================================================
# Pydantic Models
# =============================================================================

class EVGateDecisionResponse(BaseModel):
    """Single EV gate decision log entry."""
    timestamp: float
    symbol: str
    signal_id: Optional[str] = None
    decision: str  # "ACCEPT" or "REJECT"
    reject_code: Optional[str] = None
    reject_reason: Optional[str] = None
    
    # Calculated values
    p_hat: float = 0.0
    p_calibrated: float = 0.0
    p_min: float = 0.0
    R: float = 0.0
    C: float = 0.0
    EV: float = 0.0
    L_bps: float = 0.0
    G_bps: float = 0.0
    
    # Cost breakdown
    spread_bps: float = 0.0
    fee_bps: float = 0.0
    slippage_bps: float = 0.0
    adverse_selection_bps: float = 0.0
    total_cost_bps: float = 0.0
    
    # Thresholds
    ev_min_base: float = 0.0
    ev_min_adjusted: float = 0.0
    adjustment_factor: float = 1.0
    adjustment_reason: Optional[str] = None
    
    # Context
    regime_label: Optional[str] = None
    session: Optional[str] = None
    volatility_regime: Optional[str] = None
    
    # Calibration
    calibration_method: str = "uncalibrated"
    calibration_reliability: float = 0.0
    
    # Data quality
    book_age_ms: float = 0.0
    spread_age_ms: float = 0.0
    
    # Shadow mode comparison
    ev_gate_would_reject: Optional[bool] = None
    confidence_gate_rejected: Optional[bool] = None


class EVGateDecisionsListResponse(BaseModel):
    """Response for listing EV gate decisions."""
    decisions: List[EVGateDecisionResponse]
    total: int
    limit: int
    offset: int


class EVGateAggregateMetrics(BaseModel):
    """Aggregate metrics for EV gate decisions."""
    trades_per_day: float = 0.0
    gross_EV: float = 0.0
    net_EV: float = 0.0
    acceptance_rate: float = 0.0
    total_decisions: int = 0
    total_accepts: int = 0
    total_rejects: int = 0
    avg_EV_accepted: float = 0.0
    avg_R_accepted: float = 0.0
    avg_C_accepted: float = 0.0
    period_hours: float = 24.0
    timestamp: float = 0.0


class EVGateRejectCounters(BaseModel):
    """Reject counters by code, symbol, regime, and session."""
    by_code: Dict[str, int] = {}
    by_symbol: Dict[str, int] = {}
    by_regime: Dict[str, int] = {}
    by_session: Dict[str, int] = {}
    total_rejects: int = 0
    period_hours: float = 24.0
    timestamp: float = 0.0


class EVGateAcceptanceByDimension(BaseModel):
    """Acceptance rate breakdown by dimension."""
    by_symbol: Dict[str, Dict[str, float]] = {}  # symbol -> {accepts, rejects, rate}
    by_strategy: Dict[str, Dict[str, float]] = {}
    by_regime: Dict[str, Dict[str, float]] = {}
    by_session: Dict[str, Dict[str, float]] = {}
    timestamp: float = 0.0


# =============================================================================
# In-Memory Storage for Decision Logs
# =============================================================================

@dataclass
class EVGateDecisionLog:
    """In-memory decision log entry."""
    timestamp: float
    symbol: str
    signal_id: str
    decision: str
    reject_code: Optional[str] = None
    reject_reason: Optional[str] = None
    p_hat: float = 0.0
    p_calibrated: float = 0.0
    p_min: float = 0.0
    R: float = 0.0
    C: float = 0.0
    EV: float = 0.0
    L_bps: float = 0.0
    G_bps: float = 0.0
    spread_bps: float = 0.0
    fee_bps: float = 0.0
    slippage_bps: float = 0.0
    adverse_selection_bps: float = 0.0
    total_cost_bps: float = 0.0
    ev_min_base: float = 0.0
    ev_min_adjusted: float = 0.0
    adjustment_factor: float = 1.0
    adjustment_reason: Optional[str] = None
    regime_label: Optional[str] = None
    session: Optional[str] = None
    volatility_regime: Optional[str] = None
    strategy_id: Optional[str] = None
    calibration_method: str = "uncalibrated"
    calibration_reliability: float = 0.0
    book_age_ms: float = 0.0
    spread_age_ms: float = 0.0
    ev_gate_would_reject: Optional[bool] = None
    confidence_gate_rejected: Optional[bool] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class EVGateMetricsCollector:
    """
    Collects and aggregates EV gate metrics.
    
    This class provides:
    1. In-memory storage for recent decision logs
    2. Aggregate metrics computation
    3. Reject counters by various dimensions
    4. Prometheus metrics export
    
    Requirements: 7.2, 7.3, 7.4
    """
    
    # Maximum number of decisions to keep in memory
    MAX_DECISIONS = 10000
    
    # Retention period for decisions (24 hours)
    RETENTION_SECONDS = 24 * 60 * 60
    
    def __init__(self):
        """Initialize the metrics collector."""
        self._decisions: List[EVGateDecisionLog] = []
        self._accepts_total: int = 0
        self._rejects_total: int = 0
        self._rejects_by_code: Dict[str, int] = defaultdict(int)
        self._last_cleanup: float = time.time()
    
    def record_decision(self, log: EVGateDecisionLog) -> None:
        """Record a decision log entry.
        
        Args:
            log: The decision log to record.
        """
        self._decisions.append(log)
        
        # Update counters
        if log.decision == "ACCEPT":
            self._accepts_total += 1
        else:
            self._rejects_total += 1
            if log.reject_code:
                self._rejects_by_code[log.reject_code] += 1
        
        # Periodic cleanup
        if time.time() - self._last_cleanup > 300:  # Every 5 minutes
            self._cleanup_old_decisions()
    
    def _cleanup_old_decisions(self) -> None:
        """Remove decisions older than retention period."""
        cutoff = time.time() - self.RETENTION_SECONDS
        self._decisions = [d for d in self._decisions if d.timestamp > cutoff]
        
        # Trim to max size
        if len(self._decisions) > self.MAX_DECISIONS:
            self._decisions = self._decisions[-self.MAX_DECISIONS:]
        
        self._last_cleanup = time.time()
    
    def get_decisions(
        self,
        symbol: Optional[str] = None,
        regime: Optional[str] = None,
        session: Optional[str] = None,
        decision: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[List[EVGateDecisionLog], int]:
        """Get filtered decision logs.
        
        Args:
            symbol: Filter by symbol
            regime: Filter by regime
            session: Filter by session
            decision: Filter by decision (ACCEPT/REJECT)
            limit: Maximum number of results
            offset: Offset for pagination
            
        Returns:
            Tuple of (filtered decisions, total count)
        """
        self._cleanup_old_decisions()
        
        # Filter decisions
        filtered = self._decisions
        
        if symbol:
            filtered = [d for d in filtered if d.symbol == symbol]
        if regime:
            filtered = [d for d in filtered if d.regime_label == regime]
        if session:
            filtered = [d for d in filtered if d.session == session]
        if decision:
            filtered = [d for d in filtered if d.decision == decision]
        
        # Sort by timestamp descending
        filtered = sorted(filtered, key=lambda d: d.timestamp, reverse=True)
        
        total = len(filtered)
        
        # Apply pagination
        filtered = filtered[offset:offset + limit]
        
        return filtered, total
    
    def get_aggregate_metrics(self, period_hours: float = 24.0) -> EVGateAggregateMetrics:
        """Compute aggregate metrics for the specified period.
        
        Args:
            period_hours: Period in hours to compute metrics for.
            
        Returns:
            EVGateAggregateMetrics with computed values.
            
        Requirements: 7.3
        """
        self._cleanup_old_decisions()
        
        cutoff = time.time() - (period_hours * 3600)
        recent = [d for d in self._decisions if d.timestamp > cutoff]
        
        total = len(recent)
        accepts = [d for d in recent if d.decision == "ACCEPT"]
        rejects = [d for d in recent if d.decision == "REJECT"]
        
        # Compute metrics
        acceptance_rate = len(accepts) / total if total > 0 else 0.0
        trades_per_day = len(accepts) * (24.0 / period_hours) if period_hours > 0 else 0.0
        
        # Compute EV metrics
        gross_EV = sum(d.EV for d in accepts) if accepts else 0.0
        avg_EV = gross_EV / len(accepts) if accepts else 0.0
        avg_R = sum(d.R for d in accepts) / len(accepts) if accepts else 0.0
        avg_C = sum(d.C for d in accepts) / len(accepts) if accepts else 0.0
        
        # Net EV accounts for costs
        net_EV = sum(d.EV - d.C for d in accepts) if accepts else 0.0
        
        return EVGateAggregateMetrics(
            trades_per_day=trades_per_day,
            gross_EV=gross_EV,
            net_EV=net_EV,
            acceptance_rate=acceptance_rate,
            total_decisions=total,
            total_accepts=len(accepts),
            total_rejects=len(rejects),
            avg_EV_accepted=avg_EV,
            avg_R_accepted=avg_R,
            avg_C_accepted=avg_C,
            period_hours=period_hours,
            timestamp=time.time(),
        )
    
    def get_reject_counters(self, period_hours: float = 24.0) -> EVGateRejectCounters:
        """Get reject counters by various dimensions.
        
        Args:
            period_hours: Period in hours to compute counters for.
            
        Returns:
            EVGateRejectCounters with counts by code, symbol, regime, session.
            
        Requirements: 7.4
        """
        self._cleanup_old_decisions()
        
        cutoff = time.time() - (period_hours * 3600)
        rejects = [d for d in self._decisions if d.timestamp > cutoff and d.decision == "REJECT"]
        
        by_code: Dict[str, int] = defaultdict(int)
        by_symbol: Dict[str, int] = defaultdict(int)
        by_regime: Dict[str, int] = defaultdict(int)
        by_session: Dict[str, int] = defaultdict(int)
        
        for d in rejects:
            if d.reject_code:
                by_code[d.reject_code] += 1
            by_symbol[d.symbol] += 1
            if d.regime_label:
                by_regime[d.regime_label] += 1
            if d.session:
                by_session[d.session] += 1
        
        return EVGateRejectCounters(
            by_code=dict(by_code),
            by_symbol=dict(by_symbol),
            by_regime=dict(by_regime),
            by_session=dict(by_session),
            total_rejects=len(rejects),
            period_hours=period_hours,
            timestamp=time.time(),
        )
    
    def get_acceptance_by_dimension(self, period_hours: float = 24.0) -> EVGateAcceptanceByDimension:
        """Get acceptance rate breakdown by dimension.
        
        Args:
            period_hours: Period in hours to compute rates for.
            
        Returns:
            EVGateAcceptanceByDimension with rates by symbol, strategy, regime, session.
            
        Requirements: 7.5
        """
        self._cleanup_old_decisions()
        
        cutoff = time.time() - (period_hours * 3600)
        recent = [d for d in self._decisions if d.timestamp > cutoff]
        
        def compute_rates(decisions: List[EVGateDecisionLog], key_fn) -> Dict[str, Dict[str, float]]:
            groups: Dict[str, Dict[str, int]] = defaultdict(lambda: {"accepts": 0, "rejects": 0})
            for d in decisions:
                key = key_fn(d)
                if key:
                    if d.decision == "ACCEPT":
                        groups[key]["accepts"] += 1
                    else:
                        groups[key]["rejects"] += 1
            
            result = {}
            for key, counts in groups.items():
                total = counts["accepts"] + counts["rejects"]
                result[key] = {
                    "accepts": float(counts["accepts"]),
                    "rejects": float(counts["rejects"]),
                    "rate": counts["accepts"] / total if total > 0 else 0.0,
                }
            return result
        
        return EVGateAcceptanceByDimension(
            by_symbol=compute_rates(recent, lambda d: d.symbol),
            by_strategy=compute_rates(recent, lambda d: d.strategy_id),
            by_regime=compute_rates(recent, lambda d: d.regime_label),
            by_session=compute_rates(recent, lambda d: d.session),
            timestamp=time.time(),
        )
    
    def get_prometheus_metrics(self) -> str:
        """Generate Prometheus metrics in text format.
        
        Returns:
            Prometheus metrics as text.
            
        Requirements: Non-functional observability
        """
        lines = []
        
        # ev_gate_accepts_total
        lines.append("# HELP ev_gate_accepts_total Total number of signals accepted by EV gate")
        lines.append("# TYPE ev_gate_accepts_total counter")
        lines.append(f"ev_gate_accepts_total {self._accepts_total}")
        lines.append("")
        
        # ev_gate_rejects_total
        lines.append("# HELP ev_gate_rejects_total Total number of signals rejected by EV gate")
        lines.append("# TYPE ev_gate_rejects_total counter")
        lines.append(f"ev_gate_rejects_total {self._rejects_total}")
        lines.append("")
        
        # ev_gate_rejects_by_code
        lines.append("# HELP ev_gate_rejects_by_code Number of rejections by reject code")
        lines.append("# TYPE ev_gate_rejects_by_code counter")
        for code, count in self._rejects_by_code.items():
            lines.append(f'ev_gate_rejects_by_code{{code="{code}"}} {count}')
        lines.append("")
        
        # ev_gate_decisions_total (gauge for recent period)
        self._cleanup_old_decisions()
        lines.append("# HELP ev_gate_decisions_total Total decisions in last 24h")
        lines.append("# TYPE ev_gate_decisions_total gauge")
        lines.append(f"ev_gate_decisions_total {len(self._decisions)}")
        lines.append("")
        
        # ev_gate_acceptance_rate (gauge)
        total = len(self._decisions)
        accepts = len([d for d in self._decisions if d.decision == "ACCEPT"])
        rate = accepts / total if total > 0 else 0.0
        lines.append("# HELP ev_gate_acceptance_rate Acceptance rate in last 24h")
        lines.append("# TYPE ev_gate_acceptance_rate gauge")
        lines.append(f"ev_gate_acceptance_rate {rate:.4f}")
        
        return "\n".join(lines)


# Global metrics collector instance
_metrics_collector: Optional[EVGateMetricsCollector] = None


def get_metrics_collector() -> EVGateMetricsCollector:
    """Get the global EV gate metrics collector."""
    global _metrics_collector
    if _metrics_collector is None:
        _metrics_collector = EVGateMetricsCollector()
    return _metrics_collector


# =============================================================================
# Redis Connection
# =============================================================================

async def get_redis_client():
    """Get Redis client."""
    import os
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    client = redis.from_url(redis_url, decode_responses=False)
    try:
        yield client
    finally:
        await client.aclose()


# =============================================================================
# Router Definition
# =============================================================================

router = APIRouter(prefix="/api/v1/ev-gate", tags=["ev-gate"])


# =============================================================================
# Decision Logs Endpoint
# Requirements: 7.2
# =============================================================================

@router.get("/decisions", response_model=EVGateDecisionsListResponse)
async def get_ev_gate_decisions(
    tenant_id: str = Query(...),
    bot_id: str = Query(...),
    symbol: Optional[str] = Query(None, description="Filter by symbol"),
    regime: Optional[str] = Query(None, description="Filter by regime"),
    session: Optional[str] = Query(None, description="Filter by session"),
    decision: Optional[str] = Query(None, description="Filter by decision (ACCEPT/REJECT)"),
    limit: int = Query(100, le=1000, description="Maximum results"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    redis_client=Depends(get_redis_client),
):
    """
    Get EV gate decision logs with filtering support.
    
    Supports filtering by:
    - symbol: Trading symbol (e.g., BTCUSDT)
    - regime: Market regime label
    - session: Trading session (us, europe, asia)
    - decision: ACCEPT or REJECT
    
    Requirements: 7.2
    """
    # Try to get from Redis first
    key = f"quantgambit:{tenant_id}:{bot_id}:ev_gate:decisions"
    
    try:
        # Get recent decisions from Redis stream
        entries = await redis_client.xrevrange(key, count=limit + offset)
        
        decisions = []
        for entry_id, payload in entries:
            try:
                if isinstance(payload, dict):
                    data = {}
                    for k, v in payload.items():
                        key_str = k.decode() if isinstance(k, bytes) else k
                        val_str = v.decode() if isinstance(v, bytes) else v
                        if key_str == "data":
                            data = json.loads(val_str)
                        else:
                            data[key_str] = val_str
                    
                    # Apply filters
                    if symbol and data.get("symbol") != symbol:
                        continue
                    if regime and data.get("regime_label") != regime:
                        continue
                    if session and data.get("session") != session:
                        continue
                    if decision and data.get("decision") != decision:
                        continue
                    
                    decisions.append(EVGateDecisionResponse(**data))
            except (json.JSONDecodeError, KeyError, TypeError):
                continue
        
        # Apply pagination
        total = len(decisions)
        decisions = decisions[offset:offset + limit]
        
        return EVGateDecisionsListResponse(
            decisions=decisions,
            total=total,
            limit=limit,
            offset=offset,
        )
        
    except Exception as e:
        logger.warning(f"Failed to get decisions from Redis: {e}")
        
        # Fall back to in-memory collector
        collector = get_metrics_collector()
        logs, total = collector.get_decisions(
            symbol=symbol,
            regime=regime,
            session=session,
            decision=decision,
            limit=limit,
            offset=offset,
        )
        
        decisions = [
            EVGateDecisionResponse(**log.to_dict())
            for log in logs
        ]
        
        return EVGateDecisionsListResponse(
            decisions=decisions,
            total=total,
            limit=limit,
            offset=offset,
        )


# =============================================================================
# Aggregate Metrics Endpoint
# Requirements: 7.3
# =============================================================================

@router.get("/metrics", response_model=EVGateAggregateMetrics)
async def get_ev_gate_metrics(
    tenant_id: str = Query(...),
    bot_id: str = Query(...),
    period_hours: float = Query(24.0, ge=1.0, le=168.0, description="Period in hours"),
    redis_client=Depends(get_redis_client),
):
    """
    Get aggregate EV gate metrics.
    
    Computes:
    - trades_per_day: Accepted signals extrapolated to daily rate
    - gross_EV: Sum of EV for accepted signals
    - net_EV: Sum of EV minus costs for accepted signals
    - acceptance_rate: Ratio of accepts to total decisions
    
    Requirements: 7.3
    """
    # Try to get from Redis first
    key = f"quantgambit:{tenant_id}:{bot_id}:ev_gate:metrics"
    
    try:
        data = await redis_client.get(key)
        if data:
            if isinstance(data, bytes):
                data = data.decode('utf-8')
            metrics = json.loads(data)
            return EVGateAggregateMetrics(**metrics)
    except Exception as e:
        logger.warning(f"Failed to get metrics from Redis: {e}")
    
    # Fall back to in-memory collector
    collector = get_metrics_collector()
    return collector.get_aggregate_metrics(period_hours)


# =============================================================================
# Reject Counters Endpoint
# Requirements: 7.4
# =============================================================================

@router.get("/rejects", response_model=EVGateRejectCounters)
async def get_ev_gate_rejects(
    tenant_id: str = Query(...),
    bot_id: str = Query(...),
    period_hours: float = Query(24.0, ge=1.0, le=168.0, description="Period in hours"),
    redis_client=Depends(get_redis_client),
):
    """
    Get EV gate reject counters by code, symbol, regime, and session.
    
    Returns counts of rejections grouped by:
    - by_code: Reject code (EV_BELOW_MIN, INVALID_R, etc.)
    - by_symbol: Trading symbol
    - by_regime: Market regime
    - by_session: Trading session
    
    Requirements: 7.4
    """
    # Try to get from Redis first
    key = f"quantgambit:{tenant_id}:{bot_id}:ev_gate:rejects"
    
    try:
        data = await redis_client.get(key)
        if data:
            if isinstance(data, bytes):
                data = data.decode('utf-8')
            counters = json.loads(data)
            return EVGateRejectCounters(**counters)
    except Exception as e:
        logger.warning(f"Failed to get reject counters from Redis: {e}")
    
    # Fall back to in-memory collector
    collector = get_metrics_collector()
    return collector.get_reject_counters(period_hours)


# =============================================================================
# Acceptance Rate by Dimension Endpoint
# Requirements: 7.5
# =============================================================================

@router.get("/acceptance", response_model=EVGateAcceptanceByDimension)
async def get_ev_gate_acceptance(
    tenant_id: str = Query(...),
    bot_id: str = Query(...),
    period_hours: float = Query(24.0, ge=1.0, le=168.0, description="Period in hours"),
    redis_client=Depends(get_redis_client),
):
    """
    Get acceptance rate breakdown by dimension.
    
    Returns acceptance rates grouped by:
    - by_symbol: Per-symbol acceptance rate
    - by_strategy: Per-strategy acceptance rate
    - by_regime: Per-regime acceptance rate
    - by_session: Per-session acceptance rate
    
    Requirements: 7.5
    """
    collector = get_metrics_collector()
    return collector.get_acceptance_by_dimension(period_hours)


# =============================================================================
# Prometheus Metrics Endpoint
# Requirements: Non-functional observability
# =============================================================================

@router.get("/prometheus", response_class=PlainTextResponse)
async def get_ev_gate_prometheus_metrics(
    tenant_id: str = Query(...),
    bot_id: str = Query(...),
):
    """
    Get EV gate metrics in Prometheus format.
    
    Exposes:
    - ev_gate_accepts_total: Total accepted signals
    - ev_gate_rejects_total: Total rejected signals
    - ev_gate_rejects_by_code: Rejections by code
    - ev_gate_decisions_total: Total decisions in last 24h
    - ev_gate_acceptance_rate: Acceptance rate in last 24h
    
    Requirements: Non-functional observability
    """
    collector = get_metrics_collector()
    return collector.get_prometheus_metrics()


# =============================================================================
# Health Check Endpoint
# =============================================================================

@router.get("/health")
async def ev_gate_health():
    """Health check for EV gate API."""
    collector = get_metrics_collector()
    return {
        "status": "healthy",
        "decisions_in_memory": len(collector._decisions),
        "accepts_total": collector._accepts_total,
        "rejects_total": collector._rejects_total,
        "timestamp": time.time(),
    }
