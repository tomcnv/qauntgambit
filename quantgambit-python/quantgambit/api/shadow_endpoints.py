"""Shadow comparison API endpoints for trading pipeline integration.

Feature: trading-pipeline-integration
Requirements: 4.5 - THE System SHALL expose shadow comparison metrics via API
              (agreement rate, divergence reasons, P&L difference)

This module provides REST API endpoints for:
- Getting aggregated shadow comparison metrics (GET /api/shadow/metrics)
- Querying shadow comparison results with filters (GET /api/shadow/comparisons)
"""

from __future__ import annotations

import bisect
import json
import math
import os
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Query, HTTPException
from pydantic import BaseModel, Field
import redis.asyncio as redis

from quantgambit.integration.shadow_comparison import (
    ComparisonResult,
    ComparisonMetrics,
    ShadowComparator,
)


# ============================================================================
# Response Models
# ============================================================================

class DivergenceReasonCount(BaseModel):
    """Count of divergences by reason."""
    reason: str = Field(..., description="Divergence reason category")
    count: int = Field(..., description="Number of occurrences")


class ComparisonMetricsResponse(BaseModel):
    """Response model for shadow comparison metrics.
    
    Feature: trading-pipeline-integration
    Requirements: 4.5
    """
    total_comparisons: int = Field(..., description="Total number of comparisons in the window")
    agreements: int = Field(..., description="Number of comparisons where decisions agreed")
    disagreements: int = Field(..., description="Number of comparisons where decisions diverged")
    agreement_rate: float = Field(..., description="Ratio of agreements to total (0.0 to 1.0)")
    divergence_rate: float = Field(..., description="Ratio of divergences to total (0.0 to 1.0)")
    divergence_by_reason: Dict[str, int] = Field(
        default_factory=dict,
        description="Count of divergences by reason category"
    )
    top_divergence_reasons: List[DivergenceReasonCount] = Field(
        default_factory=list,
        description="Top divergence reasons sorted by count"
    )
    live_pnl_estimate: float = Field(0.0, description="Estimated P&L from live decisions")
    shadow_pnl_estimate: float = Field(0.0, description="Estimated P&L from shadow decisions")
    pnl_difference: float = Field(0.0, description="P&L difference (shadow - live)")
    exceeds_alert_threshold: bool = Field(
        False,
        description="Whether divergence rate exceeds alert threshold (20%)"
    )


class ComparisonResultResponse(BaseModel):
    """Response model for a single comparison result.
    
    Feature: trading-pipeline-integration
    Requirements: 4.5
    """
    timestamp: str = Field(..., description="When the comparison was made (ISO format)")
    symbol: str = Field(..., description="Trading symbol")
    live_decision: str = Field(..., description="Decision from live pipeline")
    shadow_decision: str = Field(..., description="Decision from shadow pipeline")
    agrees: bool = Field(..., description="Whether decisions agree")
    divergence_reason: Optional[str] = Field(None, description="Reason for divergence if any")
    live_rejection_stage: Optional[str] = Field(None, description="Stage that rejected in live pipeline")
    shadow_rejection_stage: Optional[str] = Field(None, description="Stage that rejected in shadow pipeline")
    live_config_version: Optional[str] = Field(None, description="Config version used by live pipeline")
    shadow_config_version: Optional[str] = Field(None, description="Config version used by shadow pipeline")


class ComparisonListResponse(BaseModel):
    """Response model for comparison list.
    
    Feature: trading-pipeline-integration
    Requirements: 4.5
    """
    comparisons: List[ComparisonResultResponse] = Field(
        default_factory=list,
        description="List of comparison results"
    )
    total: int = Field(..., description="Total number of comparisons matching filters")
    filtered: int = Field(..., description="Number of comparisons returned after limit")


class PredictionScoreMetrics(BaseModel):
    provider: str = Field(..., description="Prediction provider being scored (shadow/live)")
    lookback_hours: float = Field(..., description="Lookback window in hours")
    horizon_sec: float = Field(..., description="Outcome horizon in seconds")
    flat_threshold_bps: float = Field(..., description="Absolute return threshold treated as flat")
    samples: int = Field(..., description="Number of scored predictions (non-abstain)")
    predictions_total: int = Field(..., description="Total predictions observed (including abstains)")
    abstain_count: int = Field(..., description="Number of abstained predictions")
    abstain_rate_pct: float = Field(..., description="Abstain rate percentage (0-100)")
    abstain_by_reason: Dict[str, int] = Field(
        default_factory=dict,
        description="Abstain counts by reason (e.g., onnx_low_confidence)",
    )
    exact_accuracy_pct: float = Field(..., description="Exact class accuracy percentage")
    directional_accuracy_pct: float = Field(..., description="Directional accuracy for non-flat predictions only (up/down subset)")
    directional_accuracy_nonflat_pct: float = Field(..., description="Alias of directional_accuracy_pct for clarity")
    directional_accuracy_all_pct: float = Field(..., description="Directional accuracy over all scored predictions (equivalent to exact class accuracy)")
    directional_coverage_pct: float = Field(..., description="Percentage of scored predictions that are directional (up/down)")
    avg_confidence_pct: float = Field(..., description="Average model confidence percentage")
    avg_realized_bps: float = Field(..., description="Average realized return in basis points")
    ece_top1_pct: Optional[float] = Field(None, description="Expected calibration error percentage")
    multiclass_brier: Optional[float] = Field(None, description="Multiclass Brier score")
    ml_score: float = Field(..., description="Composite ML score (0-100)")
    promotion_score_v2: float = Field(..., description="Promotion score v2 (tradability+calibration composite, 0-100)")


class PredictionScoreResponse(BaseModel):
    enabled: bool = Field(..., description="Whether prediction scoring data is available")
    metrics: Optional[PredictionScoreMetrics] = Field(
        None, description="Prediction scoring metrics when enabled"
    )
    reason: Optional[str] = Field(None, description="Reason when scoring data is unavailable")


# ============================================================================
# Module-level state for shadow comparator
# ============================================================================

# Global shadow comparator instance - will be set by the runtime
_shadow_comparator: Optional[ShadowComparator] = None

# In-memory storage for comparison results (for querying)
_comparison_results: List[ComparisonResult] = []
_max_stored_comparisons: int = 10000


def set_shadow_comparator(comparator: Optional[ShadowComparator]) -> None:
    """Set the global shadow comparator instance.
    
    Called by the runtime when shadow mode is enabled.
    
    Args:
        comparator: The ShadowComparator instance or None to disable
    """
    global _shadow_comparator
    _shadow_comparator = comparator


def get_shadow_comparator() -> Optional[ShadowComparator]:
    """Get the global shadow comparator instance.
    
    Returns:
        The ShadowComparator instance or None if not enabled
    """
    return _shadow_comparator


def store_comparison_result(result: ComparisonResult) -> None:
    """Store a comparison result for later querying.
    
    Args:
        result: The ComparisonResult to store
    """
    global _comparison_results
    _comparison_results.append(result)
    
    # Trim to max size
    if len(_comparison_results) > _max_stored_comparisons:
        _comparison_results = _comparison_results[-_max_stored_comparisons:]


def clear_comparison_results() -> None:
    """Clear all stored comparison results."""
    global _comparison_results
    _comparison_results = []


def get_stored_comparisons() -> List[ComparisonResult]:
    """Get all stored comparison results.
    
    Returns:
        List of stored ComparisonResult objects
    """
    return _comparison_results.copy()


# ============================================================================
# Router
# ============================================================================

router = APIRouter(prefix="/api/shadow", tags=["shadow"])

def _redis_fallback_enabled() -> bool:
    """
    Whether /api/shadow/* endpoints may fall back to Redis-backed history.

    Default is disabled so that "shadow mode disabled" is an explicit 503 unless
    the runtime has enabled comparator mode (or operators explicitly opt into
    Redis fallback for post-restart debugging).
    """
    return os.getenv("SHADOW_API_REDIS_FALLBACK_ENABLED", "false").strip().lower() in (
        "1",
        "true",
        "yes",
        "y",
        "on",
    )


def _safe_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _to_datetime_utc(value: Any) -> Optional[datetime]:
    """Parse mixed timestamp formats into UTC datetime."""
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    if isinstance(value, (int, float)):
        numeric = float(value)
        if numeric > 1_000_000_000_000:  # microseconds epoch
            numeric = numeric / 1_000_000.0
        elif numeric > 1_000_000_000:  # milliseconds epoch
            numeric = numeric / 1000.0
        try:
            return datetime.fromtimestamp(numeric, tz=timezone.utc)
        except (OSError, OverflowError, ValueError):
            return None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return _to_datetime_utc(float(text))
        except ValueError:
            pass
        try:
            if text.endswith("Z"):
                text = text[:-1] + "+00:00"
            parsed = datetime.fromisoformat(text)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except ValueError:
            return None
    return None


def _prediction_decision(prediction: Any) -> Optional[str]:
    """Extract comparable decision string from a prediction payload."""
    if not isinstance(prediction, dict):
        return None
    direction = prediction.get("direction")
    if direction is not None:
        text = str(direction).strip().lower()
        if text:
            return text
    if prediction.get("reject") is True:
        return "rejected"
    return None


def _comparison_from_feature_event(event: dict[str, Any]) -> Optional[dict[str, Any]]:
    payload = event.get("payload")
    if not isinstance(payload, dict):
        return None
    live_pred = payload.get("prediction")
    shadow_pred = payload.get("prediction_shadow")
    live_decision = _prediction_decision(live_pred)
    shadow_decision = _prediction_decision(shadow_pred)
    if not live_decision or not shadow_decision:
        return None

    ts = (
        _to_datetime_utc(event.get("ts_canon_us"))
        or _to_datetime_utc(event.get("ts_recv_us"))
        or _to_datetime_utc(event.get("timestamp"))
        or _to_datetime_utc(payload.get("timestamp"))
        or _to_datetime_utc(shadow_pred.get("timestamp") if isinstance(shadow_pred, dict) else None)
        or _to_datetime_utc(live_pred.get("timestamp") if isinstance(live_pred, dict) else None)
    )
    if ts is None:
        ts = datetime.now(timezone.utc)

    symbol = str(event.get("symbol") or payload.get("symbol") or "UNKNOWN")
    agrees = live_decision == shadow_decision
    return {
        "timestamp_dt": ts,
        "symbol": symbol,
        "live_decision": live_decision,
        "shadow_decision": shadow_decision,
        "agrees": agrees,
        "divergence_reason": None if agrees else "direction_diff",
        "live_rejection_stage": "prediction_reject" if live_decision == "rejected" else None,
        "shadow_rejection_stage": "prediction_reject" if shadow_decision == "rejected" else None,
        "live_config_version": live_pred.get("source") if isinstance(live_pred, dict) else None,
        "shadow_config_version": shadow_pred.get("source") if isinstance(shadow_pred, dict) else None,
    }


def _extract_ts_seconds(event: dict[str, Any], payload: dict[str, Any]) -> Optional[float]:
    for key in ("ts_canon_us", "ts_recv_us"):
        raw = event.get(key)
        ts = _safe_float(raw)
        if ts is None:
            continue
        if ts > 1_000_000_000_000:
            return ts / 1_000_000.0
        if ts > 1_000_000_000:
            return ts / 1000.0
        return ts
    for raw in (payload.get("timestamp"), event.get("timestamp")):
        ts = _safe_float(raw)
        if ts is not None:
            return ts
    return None


def _extract_price(payload: dict[str, Any]) -> Optional[float]:
    features = payload.get("features") or {}
    market_context = payload.get("market_context") or {}
    for raw in (
        market_context.get("price"),
        features.get("price"),
        market_context.get("last"),
        features.get("last"),
    ):
        price = _safe_float(raw)
        if price is not None and price > 0:
            return price
    return None


def _normalize_probs(prediction: dict[str, Any]) -> Optional[dict[str, float]]:
    class_order = ("down", "flat", "up")
    probs_raw = prediction.get("probs")
    probs: dict[str, float] = {}
    if isinstance(probs_raw, dict):
        for cls in class_order:
            value = _safe_float(probs_raw.get(cls))
            if value is None:
                return None
            probs[cls] = max(0.0, min(1.0, value))
    else:
        p_up = _safe_float(prediction.get("p_up"))
        p_down = _safe_float(prediction.get("p_down"))
        p_flat = _safe_float(prediction.get("p_flat"))
        if p_up is None or p_down is None:
            return None
        if p_flat is None:
            p_flat = max(0.0, 1.0 - p_up - p_down)
        probs = {
            "up": max(0.0, min(1.0, p_up)),
            "down": max(0.0, min(1.0, p_down)),
            "flat": max(0.0, min(1.0, p_flat)),
        }
    total = sum(probs.values())
    if total <= 0:
        return None
    if abs(total - 1.0) > 0.005:
        for cls in probs:
            probs[cls] = probs[cls] / total
    return probs


def _extract_prediction_for_score(payload: dict[str, Any], provider: str) -> Optional[dict[str, Any]]:
    key = "prediction_shadow" if provider == "shadow" else "prediction"
    prediction = payload.get(key)
    if not isinstance(prediction, dict):
        return None
    direction = str(prediction.get("direction") or "").lower().strip()
    if direction not in {"up", "down", "flat"}:
        return None
    probs = _normalize_probs(prediction)
    confidence = _safe_float(prediction.get("confidence"))
    if confidence is None and probs is not None:
        confidence = _safe_float(probs.get(direction), 0.0)
    reject = bool(prediction.get("reject")) if "reject" in prediction else False
    reason = prediction.get("reason") if isinstance(prediction.get("reason"), str) else None
    return {
        "direction": direction,
        "confidence": float(confidence or 0.0),
        "probs": probs,
        "reject": reject,
        "reason": reason,
    }


def _classify_outcome(ret_bps: float, flat_threshold_bps: float) -> str:
    if ret_bps >= flat_threshold_bps:
        return "up"
    if ret_bps <= -flat_threshold_bps:
        return "down"
    return "flat"


def _brier_term(probs: dict[str, float], outcome: str) -> float:
    total = 0.0
    for cls in ("down", "flat", "up"):
        target = 1.0 if cls == outcome else 0.0
        p = float(probs.get(cls, 0.0))
        total += (p - target) ** 2
    return total / 3.0


def _conf_bin_label(value: float) -> str:
    idx = max(0, min(9, int(value * 10.0)))
    lo = idx * 0.1
    hi = lo + 0.1
    return f"{lo:.1f}-{hi:.1f}"


def _ece_from_bins(conf_bins: dict[str, dict[str, float]]) -> Optional[float]:
    total_n = 0
    weighted_error = 0.0
    for label, bin_data in conf_bins.items():
        n = int(bin_data.get("n") or 0)
        correct = int(bin_data.get("correct") or 0)
        conf_sum = float(bin_data.get("conf_sum") or 0.0)
        if n <= 0:
            continue
        avg_conf = conf_sum / float(n)
        acc = correct / float(n)
        weighted_error += abs(acc - avg_conf) * float(n)
        total_n += n
    if total_n <= 0:
        return None
    return weighted_error / float(total_n)


async def _load_feature_events_for_scoring(max_rows: int) -> list[dict[str, Any]]:
    redis_url = os.getenv("BOT_REDIS_URL") or os.getenv("REDIS_URL", "redis://localhost:6379")
    tenant_id = (os.getenv("DEFAULT_TENANT_ID") or os.getenv("TENANT_ID") or "").strip()
    bot_id = (os.getenv("DEFAULT_BOT_ID") or os.getenv("BOT_ID") or "").strip()

    stream_candidates: list[str] = []
    if tenant_id and bot_id:
        stream_candidates.append(f"events:features:{tenant_id}:{bot_id}")
    stream_candidates.append("events:features")

    client = redis.from_url(redis_url, decode_responses=True)
    try:
        parsed_events: list[dict[str, Any]] = []
        for stream in stream_candidates:
            rows = await client.xrevrange(stream, count=max_rows)
            if not rows:
                continue
            for _, fields in rows:
                raw = fields.get("data")
                if not raw:
                    continue
                try:
                    event = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if isinstance(event, dict):
                    parsed_events.append(event)
            if parsed_events:
                break
        parsed_events.reverse()
        return parsed_events
    finally:
        await client.aclose()


def _compute_prediction_score(
    events: list[dict[str, Any]],
    provider: str,
    lookback_hours: float,
    horizon_sec: float,
    flat_threshold_bps: float,
) -> Optional[PredictionScoreMetrics]:
    now = datetime.now(timezone.utc).timestamp()
    min_ts = now - (lookback_hours * 3600.0)

    events_by_symbol: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        payload = event.get("payload")
        if not isinstance(payload, dict):
            continue
        ts = _extract_ts_seconds(event, payload)
        symbol = str(event.get("symbol") or payload.get("symbol") or "").strip()
        price = _extract_price(payload)
        if ts is None or not symbol or price is None:
            continue
        if ts < min_ts:
            continue
        prediction = _extract_prediction_for_score(payload, provider=provider)
        events_by_symbol.setdefault(symbol, []).append(
            {"ts": ts, "price": price, "prediction": prediction}
        )

    predictions_total = 0
    abstain_count = 0
    abstain_by_reason: dict[str, int] = {}
    samples = 0  # non-abstain only
    exact_correct = 0
    directional_samples = 0
    directional_correct = 0
    conf_sum = 0.0
    realized_sum = 0.0
    brier_sum = 0.0
    brier_count = 0
    conf_bins = {f"{i*0.1:.1f}-{(i+1)*0.1:.1f}": {"n": 0, "correct": 0, "conf_sum": 0.0} for i in range(10)}

    for _, symbol_events in events_by_symbol.items():
        if len(symbol_events) < 2:
            continue
        ts_list = [float(item["ts"]) for item in symbol_events]
        price_list = [float(item["price"]) for item in symbol_events]
        for idx, item in enumerate(symbol_events):
            prediction = item.get("prediction")
            if prediction is None:
                continue
            predictions_total += 1
            if prediction.get("reject"):
                abstain_count += 1
                reason = str(prediction.get("reason") or "abstain").strip() or "abstain"
                abstain_by_reason[reason] = abstain_by_reason.get(reason, 0) + 1
                continue
            target_ts = float(item["ts"]) + horizon_sec
            fidx = bisect.bisect_left(ts_list, target_ts)
            if fidx >= len(ts_list):
                continue
            entry_price = price_list[idx]
            exit_price = price_list[fidx]
            if entry_price <= 0:
                continue
            ret_bps = ((exit_price - entry_price) / entry_price) * 10000.0
            outcome = _classify_outcome(ret_bps, flat_threshold_bps)
            pred_dir = str(prediction["direction"])
            conf = max(0.0, min(1.0, float(prediction["confidence"])))

            samples += 1
            conf_sum += conf
            realized_sum += ret_bps
            if pred_dir == outcome:
                exact_correct += 1
            if pred_dir in {"up", "down"}:
                directional_samples += 1
                if pred_dir == outcome:
                    directional_correct += 1

            label = _conf_bin_label(conf)
            conf_bins[label]["n"] += 1
            conf_bins[label]["conf_sum"] += conf
            if pred_dir == outcome:
                conf_bins[label]["correct"] += 1

            probs = prediction.get("probs")
            if isinstance(probs, dict):
                brier_sum += _brier_term(probs, outcome)
                brier_count += 1

    if samples == 0:
        return None

    exact_acc = exact_correct / float(samples)
    directional_acc = (
        directional_correct / float(directional_samples) if directional_samples > 0 else exact_acc
    )
    directional_coverage = (
        directional_samples / float(samples) if samples > 0 else 0.0
    )
    avg_conf = conf_sum / float(samples)
    avg_realized_bps = realized_sum / float(samples)
    ece = _ece_from_bins(conf_bins)
    brier = (brier_sum / float(brier_count)) if brier_count > 0 else None

    # Composite score favors realized directional correctness, then calibration.
    calibration_component = 1.0 - min(1.0, ece or 1.0)
    ml_score = (
        (exact_acc * 0.55) +
        (directional_acc * 0.30) +
        (calibration_component * 0.15)
    ) * 100.0
    realized_component = 0.5 + (0.5 * math.tanh(avg_realized_bps / 2.0))
    ece_component = 1.0 - min(1.0, (ece if ece is not None else 1.0) / 0.25)
    brier_component = 1.0 - min(1.0, (brier if brier is not None else 1.0) / 0.25)
    promotion_score_v2 = (
        (exact_acc * 0.30)
        + (directional_acc * 0.25)
        + (realized_component * 0.25)
        + (ece_component * 0.10)
        + (brier_component * 0.10)
    ) * 100.0
    abstain_rate = (abstain_count / float(predictions_total)) if predictions_total > 0 else 0.0

    return PredictionScoreMetrics(
        provider=provider,
        lookback_hours=lookback_hours,
        horizon_sec=horizon_sec,
        flat_threshold_bps=flat_threshold_bps,
        samples=samples,
        predictions_total=predictions_total,
        abstain_count=abstain_count,
        abstain_rate_pct=round(abstain_rate * 100.0, 2),
        abstain_by_reason=abstain_by_reason,
        exact_accuracy_pct=round(exact_acc * 100.0, 2),
        directional_accuracy_pct=round(directional_acc * 100.0, 2),
        directional_accuracy_nonflat_pct=round(directional_acc * 100.0, 2),
        directional_accuracy_all_pct=round(exact_acc * 100.0, 2),
        directional_coverage_pct=round(directional_coverage * 100.0, 2),
        avg_confidence_pct=round(avg_conf * 100.0, 2),
        avg_realized_bps=round(avg_realized_bps, 3),
        ece_top1_pct=round((ece or 0.0) * 100.0, 2) if ece is not None else None,
        multiclass_brier=round(brier, 6) if brier is not None else None,
        ml_score=round(ml_score, 2),
        promotion_score_v2=round(promotion_score_v2, 2),
    )


async def _load_redis_shadow_comparisons(max_rows: int) -> List[dict[str, Any]]:
    """Build comparison rows from shared feature snapshot streams."""
    redis_url = os.getenv("BOT_REDIS_URL") or os.getenv("REDIS_URL", "redis://localhost:6379")
    tenant_id = (os.getenv("DEFAULT_TENANT_ID") or os.getenv("TENANT_ID") or "").strip()
    bot_id = (os.getenv("DEFAULT_BOT_ID") or os.getenv("BOT_ID") or "").strip()

    stream_candidates: list[str] = []
    if tenant_id and bot_id:
        stream_candidates.append(f"events:features:{tenant_id}:{bot_id}")
    stream_candidates.append("events:features")

    client = redis.from_url(redis_url, decode_responses=True)
    try:
        comparisons: List[dict[str, Any]] = []
        for stream in stream_candidates:
            rows = await client.xrevrange(stream, count=max_rows)
            if not rows:
                continue
            for _, fields in rows:
                raw = fields.get("data")
                if not raw:
                    continue
                try:
                    event = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if not isinstance(event, dict):
                    continue
                comparison = _comparison_from_feature_event(event)
                if comparison is not None:
                    comparisons.append(comparison)
            if comparisons:
                break
        comparisons.sort(key=lambda item: item["timestamp_dt"], reverse=True)
        return comparisons
    finally:
        await client.aclose()


def _metrics_from_comparison_rows(rows: List[dict[str, Any]]) -> ComparisonMetricsResponse:
    total = len(rows)
    agreements = sum(1 for row in rows if bool(row.get("agrees")))
    disagreements = total - agreements
    agreement_rate = (agreements / total) if total > 0 else 1.0
    divergence_by_reason = dict(
        Counter(
            str(row["divergence_reason"])
            for row in rows
            if row.get("divergence_reason")
        )
    )
    top_reasons = [
        DivergenceReasonCount(reason=reason, count=count)
        for reason, count in Counter(divergence_by_reason).most_common(10)
    ]
    return ComparisonMetricsResponse(
        total_comparisons=total,
        agreements=agreements,
        disagreements=disagreements,
        agreement_rate=agreement_rate,
        divergence_rate=(disagreements / total) if total > 0 else 0.0,
        divergence_by_reason=divergence_by_reason,
        top_divergence_reasons=top_reasons,
        live_pnl_estimate=0.0,
        shadow_pnl_estimate=0.0,
        pnl_difference=0.0,
        exceeds_alert_threshold=((disagreements / total) > 0.20) if total > 0 else False,
    )


@router.get("/metrics", response_model=ComparisonMetricsResponse)
async def get_shadow_metrics() -> ComparisonMetricsResponse:
    """Get aggregated shadow comparison metrics.
    
    Returns metrics from the shadow comparator's rolling window including:
    - Agreement rate between live and shadow pipelines
    - Divergence breakdown by reason
    - P&L estimates for both pipelines
    
    Feature: trading-pipeline-integration
    Requirements: 4.5 - THE System SHALL expose shadow comparison metrics via API
    
    Returns:
        ComparisonMetricsResponse with aggregated statistics
        
    Raises:
        HTTPException: 503 if shadow mode is not enabled
    """
    comparator = get_shadow_comparator()
    
    if comparator is not None:
        metrics = comparator.get_metrics()

        # Build top divergence reasons list
        top_reasons = [
            DivergenceReasonCount(reason=reason, count=count)
            for reason, count in metrics.top_divergence_reasons(n=10)
        ]

        return ComparisonMetricsResponse(
            total_comparisons=metrics.total_comparisons,
            agreements=metrics.agreements,
            disagreements=metrics.disagreements,
            agreement_rate=metrics.agreement_rate,
            divergence_rate=metrics.divergence_rate(),
            divergence_by_reason=metrics.divergence_by_reason,
            top_divergence_reasons=top_reasons,
            live_pnl_estimate=metrics.live_pnl_estimate,
            shadow_pnl_estimate=metrics.shadow_pnl_estimate,
            pnl_difference=metrics.pnl_difference(),
            exceeds_alert_threshold=metrics.exceeds_threshold(),
        )

    if not _redis_fallback_enabled():
        raise HTTPException(
            status_code=503,
            detail="Shadow mode is not enabled. Enable shadow mode to access metrics.",
        )

    lookback = int(os.getenv("SHADOW_API_REDIS_LOOKBACK", "2000"))
    fallback_rows = await _load_redis_shadow_comparisons(max_rows=max(lookback, 100))
    if not fallback_rows:
        raise HTTPException(
            status_code=503,
            detail="Shadow mode is not enabled. Enable shadow mode to access metrics."
        )
    return _metrics_from_comparison_rows(fallback_rows)


@router.get("/comparisons", response_model=ComparisonListResponse)
async def get_shadow_comparisons(
    start_time: Optional[datetime] = Query(
        None,
        description="Start of time range (ISO format)"
    ),
    end_time: Optional[datetime] = Query(
        None,
        description="End of time range (ISO format)"
    ),
    symbol: Optional[str] = Query(
        None,
        description="Filter by trading symbol"
    ),
    agrees: Optional[bool] = Query(
        None,
        description="Filter by agreement status (true=agreements, false=divergences)"
    ),
    divergence_reason: Optional[str] = Query(
        None,
        description="Filter by divergence reason"
    ),
    limit: int = Query(
        100,
        ge=1,
        le=1000,
        description="Maximum number of results to return"
    ),
    offset: int = Query(
        0,
        ge=0,
        description="Number of results to skip"
    ),
) -> ComparisonListResponse:
    """Get shadow comparison results with optional filters.
    
    Returns a list of comparison results from the stored history,
    filtered by the provided parameters.
    
    Feature: trading-pipeline-integration
    Requirements: 4.5 - THE System SHALL expose shadow comparison metrics via API
    
    Args:
        start_time: Start of time range filter (inclusive)
        end_time: End of time range filter (inclusive)
        symbol: Filter by trading symbol
        agrees: Filter by agreement status
        divergence_reason: Filter by divergence reason
        limit: Maximum results to return (1-1000)
        offset: Number of results to skip for pagination
        
    Returns:
        ComparisonListResponse with filtered comparison results
        
    Raises:
        HTTPException: 503 if shadow mode is not enabled
    """
    comparator = get_shadow_comparator()
    
    if comparator is None:
        if not _redis_fallback_enabled():
            raise HTTPException(
                status_code=503,
                detail="Shadow mode is not enabled. Enable shadow mode to access comparisons.",
            )
        lookback = int(os.getenv("SHADOW_API_REDIS_LOOKBACK", "2000"))
        fetch_rows = max(lookback, (offset + limit) * 2, 100)
        rows = await _load_redis_shadow_comparisons(max_rows=fetch_rows)
        if not rows:
            raise HTTPException(
                status_code=503,
                detail="Shadow mode is not enabled. Enable shadow mode to access comparisons."
            )

        filtered_rows = rows
        if start_time is not None:
            if start_time.tzinfo is None:
                start_time = start_time.replace(tzinfo=timezone.utc)
            filtered_rows = [row for row in filtered_rows if row["timestamp_dt"] >= start_time]
        if end_time is not None:
            if end_time.tzinfo is None:
                end_time = end_time.replace(tzinfo=timezone.utc)
            filtered_rows = [row for row in filtered_rows if row["timestamp_dt"] <= end_time]
        if symbol is not None:
            filtered_rows = [row for row in filtered_rows if row["symbol"] == symbol]
        if agrees is not None:
            filtered_rows = [row for row in filtered_rows if row["agrees"] == agrees]
        if divergence_reason is not None:
            filtered_rows = [
                row for row in filtered_rows
                if row.get("divergence_reason") == divergence_reason
            ]

        total = len(filtered_rows)
        paginated = filtered_rows[offset:offset + limit]
        return ComparisonListResponse(
            comparisons=[
                ComparisonResultResponse(
                    timestamp=row["timestamp_dt"].isoformat(),
                    symbol=row["symbol"],
                    live_decision=row["live_decision"],
                    shadow_decision=row["shadow_decision"],
                    agrees=row["agrees"],
                    divergence_reason=row.get("divergence_reason"),
                    live_rejection_stage=row.get("live_rejection_stage"),
                    shadow_rejection_stage=row.get("shadow_rejection_stage"),
                    live_config_version=row.get("live_config_version"),
                    shadow_config_version=row.get("shadow_config_version"),
                )
                for row in paginated
            ],
            total=total,
            filtered=len(paginated),
        )

    # Get stored comparisons (in-process comparator mode)
    comparisons = get_stored_comparisons()

    # Apply filters
    filtered = comparisons
    if start_time is not None:
        if start_time.tzinfo is None:
            start_time = start_time.replace(tzinfo=timezone.utc)
        filtered = [c for c in filtered if c.timestamp >= start_time]
    if end_time is not None:
        if end_time.tzinfo is None:
            end_time = end_time.replace(tzinfo=timezone.utc)
        filtered = [c for c in filtered if c.timestamp <= end_time]
    if symbol is not None:
        filtered = [c for c in filtered if c.symbol == symbol]
    if agrees is not None:
        filtered = [c for c in filtered if c.agrees == agrees]
    if divergence_reason is not None:
        filtered = [c for c in filtered if c.divergence_reason == divergence_reason]

    # Sort by timestamp descending (most recent first)
    filtered.sort(key=lambda c: c.timestamp, reverse=True)

    # Get total before pagination
    total = len(filtered)

    # Apply pagination
    paginated = filtered[offset:offset + limit]

    # Convert to response models
    response_comparisons = [
        ComparisonResultResponse(
            timestamp=c.timestamp.isoformat(),
            symbol=c.symbol,
            live_decision=c.live_decision,
            shadow_decision=c.shadow_decision,
            agrees=c.agrees,
            divergence_reason=c.divergence_reason,
            live_rejection_stage=c.live_rejection_stage,
            shadow_rejection_stage=c.shadow_rejection_stage,
            live_config_version=c.live_config_version,
            shadow_config_version=c.shadow_config_version,
        )
        for c in paginated
    ]

    return ComparisonListResponse(
        comparisons=response_comparisons,
        total=total,
        filtered=len(paginated),
    )


@router.get("/prediction-score", response_model=PredictionScoreResponse)
async def get_prediction_score(
    provider: str = Query("shadow", pattern="^(shadow|live)$"),
    lookback_hours: float = Query(6.0, ge=0.1, le=72.0),
    horizon_sec: float = Query(60.0, ge=5.0, le=900.0),
    flat_threshold_bps: float = Query(3.0, ge=0.1, le=50.0),
    max_rows: int = Query(12000, ge=500, le=50000),
) -> PredictionScoreResponse:
    """Outcome-based prediction quality score for ML/live prediction providers."""
    events = await _load_feature_events_for_scoring(max_rows=max_rows)
    if not events:
        return PredictionScoreResponse(enabled=False, reason="no_feature_events")

    metrics = _compute_prediction_score(
        events=events,
        provider=provider,
        lookback_hours=lookback_hours,
        horizon_sec=horizon_sec,
        flat_threshold_bps=flat_threshold_bps,
    )
    if metrics is None:
        return PredictionScoreResponse(enabled=False, reason="insufficient_labeled_samples")
    return PredictionScoreResponse(enabled=True, metrics=metrics)
