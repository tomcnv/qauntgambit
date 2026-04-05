"""
API endpoints for quant-grade infrastructure.

Exposes:
- Kill switch status and control
- Config bundle management
- Reconciliation status
- Latency metrics
"""

import json
import logging
import os
import pathlib
import asyncio
import math
import statistics
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

import redis.asyncio as redis
import asyncpg

from quantgambit.storage.redis_snapshots import RedisSnapshotReader

logger = logging.getLogger(__name__)


_NORMAL_DECISION_REJECTIONS = {
    "no_signal",
    "low_confidence",
    "prediction_low_confidence",
}

_NON_DEGRADED_DECISION_PREFIXES = (
    "warmup",
    "insufficient_",
    "low_data_",
    "profile_warmup",
    "symbol_warmup",
)


def _is_non_problem_decision_rejection(reason: Optional[str]) -> bool:
    reason_norm = (reason or "").strip().lower()
    if not reason_norm:
        return True
    if reason_norm in _NORMAL_DECISION_REJECTIONS:
        return True
    if reason_norm.startswith(_NON_DEGRADED_DECISION_PREFIXES):
        return True
    return False


# =============================================================================
# Pydantic Models
# =============================================================================

class KillSwitchStatus(BaseModel):
    """Kill switch status response."""
    is_active: bool
    triggered_by: Dict[str, float] = {}  # trigger -> timestamp
    message: str = ""
    last_reset_ts: float = 0.0
    last_reset_by: str = ""


class KillSwitchTriggerRequest(BaseModel):
    """Request to trigger kill switch."""
    trigger: str  # e.g., "OPERATOR_TRIGGER", "STALE_BOOK"
    message: str = "Manual trigger"


class KillSwitchResetRequest(BaseModel):
    """Request to reset kill switch."""
    operator_id: str


class ConfigBundleResponse(BaseModel):
    """Config bundle response."""
    bundle_id: str
    version: str
    name: str
    description: str = ""
    status: str
    created_at: str
    created_by: str
    approved_at: Optional[str] = None
    approved_by: Optional[str] = None
    activated_at: Optional[str] = None
    feature_set_version_id: str = ""
    model_version_id: str = ""
    calibrator_version_id: str = ""
    risk_profile_version_id: str = ""
    execution_policy_version_id: str = ""
    content_hash: str = ""


class ConfigBundleCreateRequest(BaseModel):
    """Request to create a config bundle."""
    name: str
    description: str = ""
    feature_set_version_id: str = ""
    model_version_id: str = ""
    calibrator_version_id: str = ""
    risk_profile_version_id: str = ""
    execution_policy_version_id: str = ""
    config: Dict[str, Any] = {}


class AuditEntryResponse(BaseModel):
    """Audit log entry."""
    timestamp: str
    action: str
    actor: str
    bundle_id: str
    previous_status: Optional[str]
    new_status: str
    notes: str = ""


class ReconciliationStatus(BaseModel):
    """Reconciliation worker status."""
    running: bool
    total_runs: int
    total_discrepancies: int
    total_healed: int
    interval_sec: float
    last_result: Optional[Dict[str, Any]] = None


class DiscrepancyResponse(BaseModel):
    """Single discrepancy."""
    type: str
    symbol: str
    description: str
    local_state: Dict[str, Any]
    exchange_state: Dict[str, Any]
    detected_at: str
    resolved: bool
    resolution_action: str = ""


class LatencyMetrics(BaseModel):
    """Latency metrics response."""
    metrics: Dict[str, Dict[str, float]]  # metric_name -> {p50, p95, p99, count}


class HotPathStats(BaseModel):
    """Hot path statistics."""
    ticks_processed: int
    decisions_made: int
    intents_emitted: int
    blocked_count: int
    pending_intents: int
    positions: int
    latencies: Dict[str, Dict[str, float]]


# =============================================================================
# Pipeline Health Models
# =============================================================================

class WorkerHealth(BaseModel):
    """Health status for an individual worker."""
    name: str
    status: str  # "healthy", "degraded", "down", "idle"
    latency_p99_ms: float = 0.0
    throughput_per_sec: float = 0.0
    last_event_ts: Optional[float] = None
    error_message: Optional[str] = None
    mds_quality_score: Optional[float] = None
    orderbook_event_rate_l1_eps: Optional[float] = None
    orderbook_event_rate_l2_eps: Optional[float] = None


class SymbolStatus(BaseModel):
    """Per-symbol status for decision layer."""
    symbol: str
    status: str  # "healthy", "degraded", "down", "idle"
    last_decision_ts: Optional[float] = None
    age_sec: Optional[float] = None
    rejection_reason: Optional[str] = None
    profile_id: Optional[str] = None
    strategy_id: Optional[str] = None
    session: Optional[str] = None
    decisions_count: int = 0


class LayerHealth(BaseModel):
    """Health status for a pipeline layer."""
    name: str  # "ingest", "feature", "decision", "risk", "execution", "reconciliation"
    display_name: str
    status: str  # "healthy", "degraded", "down", "idle"
    latency_p50_ms: float = 0.0
    latency_p95_ms: float = 0.0
    latency_p99_ms: float = 0.0
    throughput_per_sec: float = 0.0
    last_event_ts: Optional[float] = None
    age_sec: Optional[float] = None
    blockers: List[str] = []  # e.g., ["kill_switch_active", "no_profile_match"]
    workers: List[WorkerHealth] = []
    events_processed: int = 0
    events_rejected: int = 0
    symbol_status: Optional[List[SymbolStatus]] = None  # Per-symbol status for decision layer


class PipelineHealthResponse(BaseModel):
    """Complete pipeline health response."""
    layers: List[LayerHealth]
    overall_status: str  # "healthy", "degraded", "down"
    tick_to_execution_p99_ms: float = 0.0
    decisions_per_minute: float = 0.0
    fills_per_hour: float = 0.0
    kill_switch_active: bool = False
    prediction: Optional[Dict[str, Any]] = None
    timestamp: float


def _percentile(values: List[float], q: float) -> Optional[float]:
    if not values:
        return None
    if q <= 0:
        return min(values)
    if q >= 100:
        return max(values)
    ordered = sorted(values)
    rank = (q / 100.0) * (len(ordered) - 1)
    lo = int(math.floor(rank))
    hi = int(math.ceil(rank))
    if lo == hi:
        return float(ordered[lo])
    w = rank - lo
    return float((ordered[lo] * (1.0 - w)) + (ordered[hi] * w))


def _summarize_prediction_input_health(
    feature_samples_with_payload: List[Dict[str, Any]],
    feature_keys: List[str],
) -> Dict[str, Any]:
    """
    Summarize live ONNX input feature quality from sampled feature snapshots.

    Produces per-feature missingness/variance diagnostics so operators can detect
    low-information inputs (constant, near-constant, or mostly missing).
    """
    if not feature_keys:
        return {
            "status": "unknown",
            "sample_count": int(len(feature_samples_with_payload)),
            "feature_count": 0,
            "message": "model_feature_keys_missing",
            "features": [],
            "critical_features": [],
            "warning_features": [],
        }

    per_feature_values: Dict[str, List[float]] = {key: [] for key in feature_keys}
    per_feature_fallback_hits: Dict[str, int] = {key: 0 for key in feature_keys}
    sample_count = 0
    source_counts: Dict[str, int] = {"onnx": 0, "heuristic": 0, "other": 0}

    for sample in feature_samples_with_payload:
        payload = sample.get("payload")
        if not isinstance(payload, dict):
            continue
        sample_count += 1
        features = payload.get("features") if isinstance(payload.get("features"), dict) else {}
        market_context = payload.get("market_context") if isinstance(payload.get("market_context"), dict) else {}
        prediction = payload.get("prediction") if isinstance(payload.get("prediction"), dict) else {}
        source = str(prediction.get("source") or "").lower()
        if "onnx" in source:
            source_counts["onnx"] += 1
        elif "heuristic" in source:
            source_counts["heuristic"] += 1
        else:
            source_counts["other"] += 1

        for key in feature_keys:
            raw = features.get(key)
            used_market_context = False
            if raw is None:
                raw = market_context.get(key)
                used_market_context = raw is not None
            try:
                value = float(raw)
            except (TypeError, ValueError):
                continue
            if not math.isfinite(value):
                continue
            per_feature_values[key].append(value)
            if used_market_context:
                per_feature_fallback_hits[key] += 1

    critical_features: List[str] = []
    warning_features: List[str] = []
    feature_summaries: List[Dict[str, Any]] = []
    denominator = max(sample_count, 1)

    structural_constant_features = {
        # Often saturated at 1.0 in healthy flow; only problematic when missing/low.
        "data_completeness",
        # Can be near-constant on tight markets; avoid escalating to critical by itself.
        "spread_bps",
    }
    slow_moving_timeframe_features = {
        # These are derived from slower candle windows and may legitimately stay
        # constant over short sample windows (especially in range sessions).
        "ema_fast_15m",
        "ema_slow_15m",
        "atr_5m",
        "atr_5m_baseline",
    }

    for key in feature_keys:
        values = per_feature_values.get(key, [])
        n = len(values)
        missing_pct = max(0.0, 100.0 * (1.0 - (n / float(denominator))))
        fallback_pct = (100.0 * (per_feature_fallback_hits.get(key, 0) / float(max(n, 1)))) if n else 0.0
        zero_pct = (100.0 * sum(1 for v in values if abs(v) < 1e-12) / float(max(n, 1))) if n else 0.0
        unique_values = len({round(v, 10) for v in values}) if values else 0
        p01 = _percentile(values, 1.0)
        p99 = _percentile(values, 99.0)
        stddev = statistics.pstdev(values) if n > 1 else 0.0
        dynamic_range = (p99 - p01) if (p01 is not None and p99 is not None) else None

        status = "ok"
        if n == 0 or missing_pct >= 25.0:
            status = "critical"
            critical_features.append(key)
        elif unique_values <= 1 or stddev <= 1e-12:
            if key in structural_constant_features or key in slow_moving_timeframe_features:
                status = "warning"
                warning_features.append(key)
            else:
                status = "critical"
                critical_features.append(key)
        elif unique_values <= 3 or zero_pct >= 90.0:
            status = "warning"
            warning_features.append(key)

        feature_summaries.append(
            {
                "name": key,
                "status": status,
                "samples": int(n),
                "missing_pct": round(missing_pct, 2),
                "fallback_from_market_context_pct": round(fallback_pct, 2),
                "zero_pct": round(zero_pct, 2),
                "unique_values": int(unique_values),
                "p01": round(float(p01), 10) if p01 is not None else None,
                "p99": round(float(p99), 10) if p99 is not None else None,
                "range_p01_p99": round(float(dynamic_range), 10) if dynamic_range is not None else None,
                "stddev": round(float(stddev), 10),
            }
        )

    overall_status = "ok"
    if critical_features:
        overall_status = "critical"
    elif warning_features:
        overall_status = "warning"

    return {
        "status": overall_status,
        "sample_count": int(sample_count),
        "feature_count": int(len(feature_keys)),
        "source_counts": source_counts,
        "critical_features": critical_features,
        "warning_features": warning_features,
        "features": feature_summaries,
    }


def _infer_score_gate_mode(
    gate_status_counts: Dict[str, int],
    env_default: Optional[str] = None,
) -> str:
    """Infer score gate mode from runtime-emitted status counts."""
    fallback_count = int((gate_status_counts or {}).get("fallback", 0) or 0)
    blocked_count = int((gate_status_counts or {}).get("blocked", 0) or 0)
    if fallback_count > 0 and blocked_count == 0:
        return "fallback_heuristic"
    if blocked_count > 0 and fallback_count == 0:
        return "block"
    if fallback_count > 0 and blocked_count > 0:
        return "mixed"
    default_mode = (env_default or os.getenv("PREDICTION_SCORE_GATE_MODE", "block")).strip().lower()
    if default_mode not in {"block", "fallback_heuristic"}:
        default_mode = "block"
    return default_mode or "block"


def _normalize_position_side_from_close_payload(payload: Dict[str, Any]) -> Optional[str]:
    """Infer held position side for close-side events.

    For close rows, order side is opposite of held position side:
    `sell` closes `long`, `buy` closes `short`.
    """
    raw_position_side = str(
        payload.get("position_side")
        or payload.get("closed_position_side")
        or payload.get("positionSide")
        or payload.get("closedPositionSide")
        or ""
    ).strip().lower()
    if raw_position_side in {"long", "buy"}:
        return "long"
    if raw_position_side in {"short", "sell"}:
        return "short"

    close_side = str(payload.get("side") or "").strip().lower()
    if close_side == "sell":
        return "long"
    if close_side == "buy":
        return "short"
    return None


def _close_event_identity(payload: Dict[str, Any]) -> Optional[str]:
    symbol = str(payload.get("symbol") or "").strip().upper()
    for key in (
        "order_id",
        "venue_order_id",
        "trade_id",
        "client_order_id",
        "root_client_order_id",
        "id",
    ):
        token = str(payload.get(key) or "").strip()
        if token:
            return f"{symbol}:{key}:{token}"

    # Fallback composite key when durable IDs are absent.
    side = _normalize_position_side_from_close_payload(payload) or "unknown"
    size = payload.get("size") or payload.get("filled_size") or payload.get("quantity") or payload.get("qty")
    price = payload.get("fill_price") or payload.get("exit_price") or payload.get("price")
    ts = (
        payload.get("exit_timestamp")
        or payload.get("timestamp")
        or payload.get("ts")
        or payload.get("exec_time_ms")
        or payload.get("last_exec_time_ms")
    )
    reason = str(payload.get("exit_reason") or payload.get("close_reason") or payload.get("reason") or "").strip().lower()
    if ts is None and size is None and price is None and not reason:
        return None
    return f"{symbol}:fallback:{side}:{size}:{price}:{ts}:{reason}"


def _build_directional_readiness(canary: Dict[str, Any]) -> Dict[str, Any]:
    """Build directional readiness report card from realized close-fill canary stats."""
    min_total_samples = int(os.getenv("DIRECTIONAL_CANARY_MIN_TOTAL_SAMPLES", "150"))
    min_side_samples = int(os.getenv("DIRECTIONAL_CANARY_MIN_SAMPLES_PER_SIDE", "60"))
    min_long_win_rate = float(os.getenv("DIRECTIONAL_CANARY_MIN_WIN_RATE_LONG", "0.52"))
    min_short_win_rate = float(os.getenv("DIRECTIONAL_CANARY_MIN_WIN_RATE_SHORT", "0.52"))
    min_long_expectancy = float(os.getenv("DIRECTIONAL_CANARY_MIN_EXPECTANCY_LONG", "0.0"))
    min_short_expectancy = float(os.getenv("DIRECTIONAL_CANARY_MIN_EXPECTANCY_SHORT", "0.0"))

    long_data = canary.get("long") if isinstance(canary.get("long"), dict) else {}
    short_data = canary.get("short") if isinstance(canary.get("short"), dict) else {}

    long_samples = int(long_data.get("pnl_samples") or 0)
    short_samples = int(short_data.get("pnl_samples") or 0)
    total_samples = int(canary.get("samples_close_fills") or (long_samples + short_samples))
    long_win_rate = long_data.get("win_rate")
    short_win_rate = short_data.get("win_rate")
    long_expectancy = long_data.get("expectancy_net_pnl")
    short_expectancy = short_data.get("expectancy_net_pnl")

    def _check(name: str, actual: Optional[float], target: float, *, op: str = "gte") -> Dict[str, Any]:
        if actual is None:
            passed = False
        elif op == "gte":
            passed = float(actual) >= float(target)
        else:
            passed = False
        return {
            "name": name,
            "passed": bool(passed),
            "actual": actual,
            "target": target,
            "op": op,
        }

    checks: List[Dict[str, Any]] = [
        _check("total_samples", float(total_samples), float(min_total_samples)),
        _check("long_samples", float(long_samples), float(min_side_samples)),
        _check("short_samples", float(short_samples), float(min_side_samples)),
        _check("long_win_rate", long_win_rate, min_long_win_rate),
        _check("short_win_rate", short_win_rate, min_short_win_rate),
        _check("long_expectancy_net_pnl", long_expectancy, min_long_expectancy),
        _check("short_expectancy_net_pnl", short_expectancy, min_short_expectancy),
    ]

    long_ready = bool(
        long_samples >= min_side_samples
        and long_win_rate is not None
        and float(long_win_rate) >= min_long_win_rate
        and long_expectancy is not None
        and float(long_expectancy) >= min_long_expectancy
    )
    short_ready = bool(
        short_samples >= min_side_samples
        and short_win_rate is not None
        and float(short_win_rate) >= min_short_win_rate
        and short_expectancy is not None
        and float(short_expectancy) >= min_short_expectancy
    )
    min_total_ready = bool(total_samples >= min_total_samples)

    blockers = [check["name"] for check in checks if not check["passed"]]
    if long_ready and short_ready and min_total_ready:
        recommendation = "enable_both_sides"
    elif long_ready and min_total_ready:
        recommendation = "long_only"
    else:
        recommendation = "hold_or_shadow"

    return {
        "ready_overall": bool(long_ready and short_ready and min_total_ready),
        "ready_long": long_ready,
        "ready_short": short_ready,
        "recommended_short_enabled": bool(short_ready and min_total_ready),
        "recommendation": recommendation,
        "checks": checks,
        "blockers": blockers,
        "thresholds": {
            "min_total_samples": min_total_samples,
            "min_side_samples": min_side_samples,
            "min_long_win_rate": min_long_win_rate,
            "min_short_win_rate": min_short_win_rate,
            "min_long_expectancy_net_pnl": min_long_expectancy,
            "min_short_expectancy_net_pnl": min_short_expectancy,
        },
    }


def _build_entry_quality_readiness(
    feature_samples_with_payload: List[Dict[str, Any]],
    decision_samples: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Summarize feed/feature gate health and entry blocking reasons."""
    min_green_pct = float(os.getenv("ENTRY_QUALITY_MIN_GREEN_PCT", "80"))
    max_blocked_pct = float(os.getenv("ENTRY_QUALITY_MAX_BLOCKED_PCT", "25"))
    max_fallback_pct = float(os.getenv("ENTRY_QUALITY_MAX_FALLBACK_PCT", "40"))

    readiness_counts: Dict[str, int] = {}
    gate_status_counts: Dict[str, int] = {}
    sample_count = 0

    for sample in feature_samples_with_payload:
        payload = sample.get("payload")
        if not isinstance(payload, dict):
            continue
        sample_count += 1
        market_context = payload.get("market_context") if isinstance(payload.get("market_context"), dict) else {}
        raw_readiness = market_context.get("readiness_level")
        readiness = str(raw_readiness or "unknown").strip().lower() or "unknown"
        if readiness == "unknown":
            # Feature snapshots currently emit data_quality_status consistently,
            # while readiness_level may be absent depending on producer version.
            dqs = str(market_context.get("data_quality_status") or "").strip().lower()
            if dqs == "ok":
                readiness = "green"
            elif dqs in {"warn", "warning", "degraded"}:
                readiness = "yellow"
            elif dqs in {"bad", "critical", "error"}:
                readiness = "red"
        readiness_counts[readiness] = int(readiness_counts.get(readiness, 0)) + 1

        raw_gate_status = market_context.get("prediction_score_gate_status")
        gate_status = str(raw_gate_status or "none").strip().lower() or "none"
        gate_status_counts[gate_status] = int(gate_status_counts.get(gate_status, 0)) + 1

    decision_count = 0
    blocking_reason_counts: Dict[str, int] = {}
    for sample in decision_samples:
        payload = sample.get("payload")
        if not isinstance(payload, dict):
            continue
        decision_count += 1
        reason = str(payload.get("rejection_reason") or "").strip()
        if not reason:
            continue
        reason_norm = reason.lower()
        if (
            reason_norm.startswith("execution_veto:")
            or reason_norm.startswith("side_quality_veto:")
            or reason_norm.startswith("prediction_low_")
            or reason_norm.startswith("data_readiness")
        ):
            blocking_reason_counts[reason_norm] = int(blocking_reason_counts.get(reason_norm, 0)) + 1

    green = int(readiness_counts.get("green", 0))
    blocked = int(gate_status_counts.get("blocked", 0))
    fallback = int(gate_status_counts.get("fallback", 0))

    green_pct = round((green / float(sample_count)) * 100.0, 2) if sample_count > 0 else 0.0
    blocked_pct = round((blocked / float(sample_count)) * 100.0, 2) if sample_count > 0 else 0.0
    fallback_pct = round((fallback / float(sample_count)) * 100.0, 2) if sample_count > 0 else 0.0

    checks = [
        {"name": "green_readiness_pct", "actual": green_pct, "target": min_green_pct, "passed": green_pct >= min_green_pct},
        {"name": "blocked_gate_pct", "actual": blocked_pct, "target_max": max_blocked_pct, "passed": blocked_pct <= max_blocked_pct},
        {"name": "fallback_gate_pct", "actual": fallback_pct, "target_max": max_fallback_pct, "passed": fallback_pct <= max_fallback_pct},
    ]
    blockers = [c["name"] for c in checks if not c["passed"]]
    ready = len(blockers) == 0
    recommendation = "enforce_entry_quality_gates" if ready else "hold_shadow_and_tune"

    top_blocking_reasons = sorted(
        [{"reason": reason, "count": int(count)} for reason, count in blocking_reason_counts.items()],
        key=lambda item: item["count"],
        reverse=True,
    )[:8]

    return {
        "sample_count": int(sample_count),
        "decision_sample_count": int(decision_count),
        "readiness_counts": readiness_counts,
        "gate_status_counts": gate_status_counts,
        "green_pct": green_pct,
        "blocked_pct": blocked_pct,
        "fallback_pct": fallback_pct,
        "checks": checks,
        "blockers": blockers,
        "ready": ready,
        "recommendation": recommendation,
        "top_blocking_reasons": top_blocking_reasons,
        "thresholds": {
            "min_green_pct": min_green_pct,
            "max_blocked_pct": max_blocked_pct,
            "max_fallback_pct": max_fallback_pct,
        },
    }


# =============================================================================
# Redis Connection (reuse from main app)
# =============================================================================

async def get_redis_client():
    """Get Redis client - should be injected from main app."""
    import os
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    client = redis.from_url(redis_url, decode_responses=False)
    try:
        yield client
    finally:
        await client.close()


_TIMESCALE_POOL: Optional[asyncpg.Pool] = None
_TIMESCALE_LOCK = asyncio.Lock()
_PLATFORM_POOL: Optional[asyncpg.Pool] = None
_PLATFORM_LOCK = asyncio.Lock()


def _build_timescale_url() -> str:
    explicit = os.getenv("BOT_TIMESCALE_URL", "").strip()
    if explicit:
        return explicit
    host = os.getenv("BOT_DB_HOST", "localhost")
    port = os.getenv("BOT_DB_PORT", "5433")
    name = os.getenv("BOT_DB_NAME", "quantgambit_bot")
    user = os.getenv("BOT_DB_USER", "quantgambit")
    password = os.getenv("BOT_DB_PASSWORD", "quantgambit_pw")
    auth = f"{user}:{password}@" if password else f"{user}@"
    return f"postgresql://{auth}{host}:{port}/{name}"


async def _get_timescale_pool() -> asyncpg.Pool:
    global _TIMESCALE_POOL
    async with _TIMESCALE_LOCK:
        if _TIMESCALE_POOL is None:
            _TIMESCALE_POOL = await asyncpg.create_pool(
                _build_timescale_url(),
                min_size=1,
                max_size=int(os.getenv("TIMESCALE_POOL_MAX", "4")),
                timeout=8.0,
            )
    return _TIMESCALE_POOL


def _db_ssl_enabled() -> bool:
    return str(os.getenv("DB_SSL", "false")).strip().lower() in {"1", "true", "yes", "on"}


async def _get_platform_pool() -> asyncpg.Pool:
    global _PLATFORM_POOL
    async with _PLATFORM_LOCK:
        if _PLATFORM_POOL is None:
            _PLATFORM_POOL = await asyncpg.create_pool(
                host=os.getenv("DASHBOARD_DB_HOST") or os.getenv("DB_HOST") or "localhost",
                port=int(os.getenv("DASHBOARD_DB_PORT") or os.getenv("DB_PORT") or "5432"),
                database=os.getenv("DASHBOARD_DB_NAME") or os.getenv("DB_NAME") or "platform_db",
                user=os.getenv("DASHBOARD_DB_USER") or os.getenv("DB_USER") or "platform",
                password=os.getenv("DASHBOARD_DB_PASSWORD") or os.getenv("DB_PASSWORD") or "",
                ssl="require" if _db_ssl_enabled() else None,
                min_size=1,
                max_size=int(os.getenv("PLATFORM_POOL_MAX", "4")),
                timeout=8.0,
            )
    return _PLATFORM_POOL


# =============================================================================
# Router Definition
# =============================================================================

router = APIRouter(prefix="/api/quant", tags=["quant-grade"])


# =============================================================================
# Kill Switch Endpoints
# =============================================================================

@router.get("/kill-switch/status", response_model=KillSwitchStatus)
async def get_kill_switch_status(
    tenant_id: str = Query(...),
    bot_id: str = Query(...),
    redis_client=Depends(get_redis_client),
):
    """Get kill switch status from Redis."""
    key = f"quantgambit:{tenant_id}:{bot_id}:kill_switch:state"
    
    try:
        data = await redis_client.get(key)
        if not data:
            return KillSwitchStatus(is_active=False)
        
        if isinstance(data, bytes):
            data = data.decode('utf-8')
        state = json.loads(data)
        
        return KillSwitchStatus(
            is_active=state.get("is_active", False),
            triggered_by=state.get("triggered_by", {}),
            message=state.get("message", ""),
            last_reset_ts=state.get("last_reset_ts", 0.0),
            last_reset_by=state.get("last_reset_by", ""),
        )
    except Exception as e:
        logger.error(f"Failed to get kill switch status: {e}")
        return KillSwitchStatus(is_active=False)


@router.post("/kill-switch/trigger", response_model=KillSwitchStatus)
async def trigger_kill_switch(
    request: KillSwitchTriggerRequest,
    tenant_id: str = Query(...),
    bot_id: str = Query(...),
    redis_client=Depends(get_redis_client),
):
    """Manually trigger kill switch."""
    import time
    
    key = f"quantgambit:{tenant_id}:{bot_id}:kill_switch:state"
    history_key = f"quantgambit:{tenant_id}:{bot_id}:kill_switch:history"
    timestamp = time.time()
    
    # Load existing state
    existing = await redis_client.get(key)
    if existing:
        if isinstance(existing, bytes):
            existing = existing.decode('utf-8')
        state = json.loads(existing)
    else:
        state = {"is_active": False, "triggered_by": {}, "message": ""}
    
    # Update state
    state["is_active"] = True
    state["message"] = request.message
    state["triggered_by"][request.trigger] = timestamp
    
    # Save state
    await redis_client.set(key, json.dumps(state))
    
    # Record history
    event = {
        "type": "trigger",
        "trigger": request.trigger,
        "message": request.message,
        "timestamp": timestamp,
    }
    await redis_client.rpush(history_key, json.dumps(event))
    await redis_client.ltrim(history_key, -500, -1)
    
    logger.warning(f"Kill switch triggered: {request.trigger} - {request.message}")
    
    return KillSwitchStatus(
        is_active=True,
        triggered_by=state["triggered_by"],
        message=request.message,
        last_reset_ts=state.get("last_reset_ts", 0.0),
    )


@router.post("/kill-switch/reset", response_model=KillSwitchStatus)
async def reset_kill_switch(
    request: KillSwitchResetRequest,
    tenant_id: str = Query(...),
    bot_id: str = Query(...),
    redis_client=Depends(get_redis_client),
):
    """Reset kill switch."""
    import time
    
    key = f"quantgambit:{tenant_id}:{bot_id}:kill_switch:state"
    history_key = f"quantgambit:{tenant_id}:{bot_id}:kill_switch:history"
    timestamp = time.time()
    
    # Reset state
    state = {
        "is_active": False,
        "triggered_by": {},
        "message": "",
        "last_reset_ts": timestamp,
        "last_reset_by": request.operator_id,
    }
    
    await redis_client.set(key, json.dumps(state))
    
    # Record history
    event = {
        "type": "reset",
        "operator_id": request.operator_id,
        "timestamp": timestamp,
    }
    await redis_client.rpush(history_key, json.dumps(event))
    await redis_client.ltrim(history_key, -500, -1)
    
    logger.warning(f"Kill switch reset by {request.operator_id}")
    
    return KillSwitchStatus(
        is_active=False,
        triggered_by={},
        message="",
        last_reset_ts=timestamp,
        last_reset_by=request.operator_id,
    )


@router.get("/kill-switch/history")
async def get_kill_switch_history(
    tenant_id: str = Query(...),
    bot_id: str = Query(...),
    limit: int = Query(100, le=500),
    redis_client=Depends(get_redis_client),
):
    """Get kill switch event history."""
    history_key = f"quantgambit:{tenant_id}:{bot_id}:kill_switch:history"
    
    events_raw = await redis_client.lrange(history_key, -limit, -1)
    
    events = []
    for event_data in events_raw:
        try:
            if isinstance(event_data, bytes):
                event_data = event_data.decode('utf-8')
            events.append(json.loads(event_data))
        except json.JSONDecodeError:
            continue
    
    return {"history": events}


# =============================================================================
# Config Bundle Endpoints
# =============================================================================

@router.get("/config-bundles", response_model=List[ConfigBundleResponse])
async def list_config_bundles(
    tenant_id: str = Query(...),
    status: Optional[str] = Query(None, description="Filter by status"),
    redis_client=Depends(get_redis_client),
):
    """List all config bundles."""
    from quantgambit.core.config.redis_store import RedisBundleStore
    from quantgambit.core.config.audit import BundleStatus
    
    store = RedisBundleStore(redis_client, tenant_id)
    
    status_filter = None
    if status:
        try:
            status_filter = BundleStatus(status)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid status: {status}")
    
    bundles = await store.list_bundles(status_filter)
    
    return [
        ConfigBundleResponse(
            bundle_id=b.bundle_id,
            version=b.version,
            name=b.name,
            description=b.description,
            status=b.status.value,
            created_at=b.created_at,
            created_by=b.created_by,
            approved_at=b.approved_at,
            approved_by=b.approved_by,
            activated_at=b.activated_at,
            feature_set_version_id=b.feature_set_version_id,
            model_version_id=b.model_version_id,
            calibrator_version_id=b.calibrator_version_id,
            risk_profile_version_id=b.risk_profile_version_id,
            execution_policy_version_id=b.execution_policy_version_id,
            content_hash=b.content_hash,
        )
        for b in bundles
    ]


@router.get("/config-bundles/active", response_model=Optional[ConfigBundleResponse])
async def get_active_bundle(
    tenant_id: str = Query(...),
    redis_client=Depends(get_redis_client),
):
    """Get currently active config bundle."""
    from quantgambit.core.config.redis_store import RedisBundleStore
    
    store = RedisBundleStore(redis_client, tenant_id)
    bundle = await store.get_active()
    
    if not bundle:
        return None
    
    return ConfigBundleResponse(
        bundle_id=bundle.bundle_id,
        version=bundle.version,
        name=bundle.name,
        description=bundle.description,
        status=bundle.status.value,
        created_at=bundle.created_at,
        created_by=bundle.created_by,
        approved_at=bundle.approved_at,
        approved_by=bundle.approved_by,
        activated_at=bundle.activated_at,
        feature_set_version_id=bundle.feature_set_version_id,
        model_version_id=bundle.model_version_id,
        calibrator_version_id=bundle.calibrator_version_id,
        risk_profile_version_id=bundle.risk_profile_version_id,
        execution_policy_version_id=bundle.execution_policy_version_id,
        content_hash=bundle.content_hash,
    )


@router.post("/config-bundles", response_model=ConfigBundleResponse)
async def create_config_bundle(
    request: ConfigBundleCreateRequest,
    tenant_id: str = Query(...),
    created_by: str = Query(...),
    redis_client=Depends(get_redis_client),
):
    """Create a new config bundle (in DRAFT status)."""
    from quantgambit.core.config.redis_store import RedisBundleStore
    from quantgambit.core.config.audit import ConfigBundleManager
    
    store = RedisBundleStore(redis_client, tenant_id)
    manager = ConfigBundleManager(store)
    
    bundle = await manager.create_bundle(
        name=request.name,
        created_by=created_by,
        feature_set_version_id=request.feature_set_version_id,
        model_version_id=request.model_version_id,
        calibrator_version_id=request.calibrator_version_id,
        risk_profile_version_id=request.risk_profile_version_id,
        execution_policy_version_id=request.execution_policy_version_id,
        description=request.description,
        config=request.config,
    )
    
    return ConfigBundleResponse(
        bundle_id=bundle.bundle_id,
        version=bundle.version,
        name=bundle.name,
        description=bundle.description,
        status=bundle.status.value,
        created_at=bundle.created_at,
        created_by=bundle.created_by,
        feature_set_version_id=bundle.feature_set_version_id,
        model_version_id=bundle.model_version_id,
        calibrator_version_id=bundle.calibrator_version_id,
        risk_profile_version_id=bundle.risk_profile_version_id,
        execution_policy_version_id=bundle.execution_policy_version_id,
        content_hash=bundle.content_hash,
    )


@router.post("/config-bundles/{bundle_id}/submit", response_model=ConfigBundleResponse)
async def submit_bundle_for_approval(
    bundle_id: str,
    tenant_id: str = Query(...),
    submitted_by: str = Query(...),
    notes: str = Query(""),
    redis_client=Depends(get_redis_client),
):
    """Submit bundle for approval."""
    from quantgambit.core.config.redis_store import RedisBundleStore
    from quantgambit.core.config.audit import ConfigBundleManager
    
    store = RedisBundleStore(redis_client, tenant_id)
    manager = ConfigBundleManager(store)
    
    try:
        bundle = await manager.submit_for_approval(bundle_id, submitted_by, notes)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    return ConfigBundleResponse(
        bundle_id=bundle.bundle_id,
        version=bundle.version,
        name=bundle.name,
        description=bundle.description,
        status=bundle.status.value,
        created_at=bundle.created_at,
        created_by=bundle.created_by,
        feature_set_version_id=bundle.feature_set_version_id,
        model_version_id=bundle.model_version_id,
        calibrator_version_id=bundle.calibrator_version_id,
        risk_profile_version_id=bundle.risk_profile_version_id,
        execution_policy_version_id=bundle.execution_policy_version_id,
        content_hash=bundle.content_hash,
    )


@router.post("/config-bundles/{bundle_id}/approve", response_model=ConfigBundleResponse)
async def approve_bundle(
    bundle_id: str,
    tenant_id: str = Query(...),
    approved_by: str = Query(...),
    notes: str = Query(""),
    redis_client=Depends(get_redis_client),
):
    """Approve a pending bundle."""
    from quantgambit.core.config.redis_store import RedisBundleStore
    from quantgambit.core.config.audit import ConfigBundleManager
    
    store = RedisBundleStore(redis_client, tenant_id)
    manager = ConfigBundleManager(store)
    
    try:
        bundle = await manager.approve(bundle_id, approved_by, notes)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    return ConfigBundleResponse(
        bundle_id=bundle.bundle_id,
        version=bundle.version,
        name=bundle.name,
        description=bundle.description,
        status=bundle.status.value,
        created_at=bundle.created_at,
        created_by=bundle.created_by,
        approved_at=bundle.approved_at,
        approved_by=bundle.approved_by,
        feature_set_version_id=bundle.feature_set_version_id,
        model_version_id=bundle.model_version_id,
        calibrator_version_id=bundle.calibrator_version_id,
        risk_profile_version_id=bundle.risk_profile_version_id,
        execution_policy_version_id=bundle.execution_policy_version_id,
        content_hash=bundle.content_hash,
    )


@router.post("/config-bundles/{bundle_id}/reject")
async def reject_bundle(
    bundle_id: str,
    tenant_id: str = Query(...),
    rejected_by: str = Query(...),
    reason: str = Query(...),
    redis_client=Depends(get_redis_client),
):
    """Reject a pending bundle."""
    from quantgambit.core.config.redis_store import RedisBundleStore
    from quantgambit.core.config.audit import ConfigBundleManager
    
    store = RedisBundleStore(redis_client, tenant_id)
    manager = ConfigBundleManager(store)
    
    try:
        bundle = await manager.reject(bundle_id, rejected_by, reason)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    return {"status": "rejected", "bundle_id": bundle_id}


@router.post("/config-bundles/{bundle_id}/activate", response_model=ConfigBundleResponse)
async def activate_bundle(
    bundle_id: str,
    tenant_id: str = Query(...),
    activated_by: str = Query(...),
    notes: str = Query(""),
    redis_client=Depends(get_redis_client),
):
    """Activate an approved bundle."""
    from quantgambit.core.config.redis_store import RedisBundleStore
    from quantgambit.core.config.audit import ConfigBundleManager
    
    store = RedisBundleStore(redis_client, tenant_id)
    manager = ConfigBundleManager(store)
    
    try:
        bundle = await manager.activate(bundle_id, activated_by, notes)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    return ConfigBundleResponse(
        bundle_id=bundle.bundle_id,
        version=bundle.version,
        name=bundle.name,
        description=bundle.description,
        status=bundle.status.value,
        created_at=bundle.created_at,
        created_by=bundle.created_by,
        approved_at=bundle.approved_at,
        approved_by=bundle.approved_by,
        activated_at=bundle.activated_at,
        feature_set_version_id=bundle.feature_set_version_id,
        model_version_id=bundle.model_version_id,
        calibrator_version_id=bundle.calibrator_version_id,
        risk_profile_version_id=bundle.risk_profile_version_id,
        execution_policy_version_id=bundle.execution_policy_version_id,
        content_hash=bundle.content_hash,
    )


@router.post("/config-bundles/rollback", response_model=ConfigBundleResponse)
async def rollback_to_bundle(
    to_bundle_id: str = Query(...),
    tenant_id: str = Query(...),
    rolled_back_by: str = Query(...),
    reason: str = Query(...),
    redis_client=Depends(get_redis_client),
):
    """Rollback to a previous bundle."""
    from quantgambit.core.config.redis_store import RedisBundleStore
    from quantgambit.core.config.audit import ConfigBundleManager
    
    store = RedisBundleStore(redis_client, tenant_id)
    manager = ConfigBundleManager(store)
    
    try:
        bundle = await manager.rollback(to_bundle_id, rolled_back_by, reason)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    return ConfigBundleResponse(
        bundle_id=bundle.bundle_id,
        version=bundle.version,
        name=bundle.name,
        description=bundle.description,
        status=bundle.status.value,
        created_at=bundle.created_at,
        created_by=bundle.created_by,
        approved_at=bundle.approved_at,
        approved_by=bundle.approved_by,
        activated_at=bundle.activated_at,
        feature_set_version_id=bundle.feature_set_version_id,
        model_version_id=bundle.model_version_id,
        calibrator_version_id=bundle.calibrator_version_id,
        risk_profile_version_id=bundle.risk_profile_version_id,
        execution_policy_version_id=bundle.execution_policy_version_id,
        content_hash=bundle.content_hash,
    )


@router.get("/config-bundles/{bundle_id}/audit", response_model=List[AuditEntryResponse])
async def get_bundle_audit_log(
    bundle_id: str,
    tenant_id: str = Query(...),
    redis_client=Depends(get_redis_client),
):
    """Get audit log for a bundle."""
    from quantgambit.core.config.redis_store import RedisBundleStore
    from quantgambit.core.config.audit import ConfigBundleManager
    
    store = RedisBundleStore(redis_client, tenant_id)
    manager = ConfigBundleManager(store)
    
    entries = await manager.get_audit_log(bundle_id)
    
    return [
        AuditEntryResponse(
            timestamp=e.timestamp,
            action=e.action,
            actor=e.actor,
            bundle_id=e.bundle_id,
            previous_status=e.previous_status,
            new_status=e.new_status,
            notes=e.notes,
        )
        for e in entries
    ]


# =============================================================================
# Reconciliation Endpoints
# =============================================================================

@router.get("/reconciliation/status", response_model=ReconciliationStatus)
async def get_reconciliation_status(
    tenant_id: str = Query(...),
    bot_id: str = Query(...),
    redis_client=Depends(get_redis_client),
):
    """Get reconciliation worker status from Redis snapshot."""
    key = f"quantgambit:{tenant_id}:{bot_id}:reconciliation:status"
    
    data = await redis_client.get(key)
    if not data:
        return ReconciliationStatus(
            running=False,
            total_runs=0,
            total_discrepancies=0,
            total_healed=0,
            interval_sec=30.0,
        )
    
    if isinstance(data, bytes):
        data = data.decode('utf-8')
    stats = json.loads(data)
    
    return ReconciliationStatus(
        running=stats.get("running", False),
        total_runs=stats.get("total_runs", 0),
        total_discrepancies=stats.get("total_discrepancies", 0),
        total_healed=stats.get("total_healed", 0),
        interval_sec=stats.get("interval_sec", 30.0),
        last_result=stats.get("last_result"),
    )


@router.get("/reconciliation/discrepancies", response_model=List[DiscrepancyResponse])
async def get_recent_discrepancies(
    tenant_id: str = Query(...),
    bot_id: str = Query(...),
    limit: int = Query(50),
    redis_client=Depends(get_redis_client),
):
    """Get recent discrepancies."""
    key = f"quantgambit:{tenant_id}:{bot_id}:reconciliation:discrepancies"
    
    items_raw = await redis_client.lrange(key, -limit, -1)
    
    discrepancies = []
    for item in items_raw:
        try:
            if isinstance(item, bytes):
                item = item.decode('utf-8')
            d = json.loads(item)
            discrepancies.append(DiscrepancyResponse(**d))
        except (json.JSONDecodeError, KeyError):
            continue
    
    return discrepancies


# =============================================================================
# Latency & Performance Endpoints
# =============================================================================

class LatencyHistoryPoint(BaseModel):
    """Single point in latency history."""
    timestamp: float
    p50_ms: float
    p95_ms: float
    p99_ms: float
    count: int


class LatencyHistoryResponse(BaseModel):
    """Latency history response."""
    operation: str
    history: List[LatencyHistoryPoint]


@router.get("/latency/metrics", response_model=LatencyMetrics)
async def get_latency_metrics(
    tenant_id: str = Query(...),
    bot_id: str = Query(...),
    redis_client=Depends(get_redis_client),
):
    """Get latency percentiles for all tracked metrics."""
    key = f"quantgambit:{tenant_id}:{bot_id}:latency:metrics"
    
    data = await redis_client.get(key)
    if not data:
        return LatencyMetrics(metrics={})
    
    if isinstance(data, bytes):
        data = data.decode('utf-8')
    
    return LatencyMetrics(metrics=json.loads(data))


@router.get("/latency/history")
async def get_latency_history(
    tenant_id: str = Query(...),
    bot_id: str = Query(...),
    operation: Optional[str] = Query(None, description="Filter by operation"),
    hours: float = Query(1.0, description="Hours of history to return"),
    redis_client=Depends(get_redis_client),
):
    """
    Get latency history for time-series graphs.
    
    Returns latency metrics over time for charting.
    """
    import time as time_module
    
    key = f"quantgambit:{tenant_id}:{bot_id}:latency:history"
    since_ts = time_module.time() - (hours * 3600)
    
    # Get all history from Redis list
    items_raw = await redis_client.lrange(key, 0, -1)
    
    history = []
    for item in items_raw:
        try:
            if isinstance(item, bytes):
                item = item.decode('utf-8')
            snapshot = json.loads(item)
            
            # Skip if before requested time
            if snapshot.get("timestamp", 0) < since_ts:
                continue
            
            if operation:
                # Filter to specific operation
                op_metrics = snapshot.get("metrics", {}).get(operation)
                if op_metrics:
                    history.append({
                        "timestamp": snapshot["timestamp"],
                        "p50_ms": op_metrics.get("p50_ms", 0),
                        "p95_ms": op_metrics.get("p95_ms", 0),
                        "p99_ms": op_metrics.get("p99_ms", 0),
                        "count": op_metrics.get("count", 0),
                    })
            else:
                history.append(snapshot)
        except (json.JSONDecodeError, KeyError):
            continue
    
    # Get list of available operations
    operations = set()
    for item in items_raw[-10:]:  # Check last 10 for available ops
        try:
            if isinstance(item, bytes):
                item = item.decode('utf-8')
            snapshot = json.loads(item)
            operations.update(snapshot.get("metrics", {}).keys())
        except (json.JSONDecodeError, KeyError):
            continue
    
    return {
        "operation": operation,
        "history": history,
        "operations": list(operations),
        "hours": hours,
    }


@router.get("/latency/operations")
async def get_latency_operations(
    tenant_id: str = Query(...),
    bot_id: str = Query(...),
    redis_client=Depends(get_redis_client),
):
    """Get list of tracked operations with current stats."""
    key = f"quantgambit:{tenant_id}:{bot_id}:latency:metrics"
    
    data = await redis_client.get(key)
    if not data:
        return {"operations": []}
    
    if isinstance(data, bytes):
        data = data.decode('utf-8')
    
    metrics = json.loads(data)
    
    operations = []
    for op, stats in metrics.items():
        operations.append({
            "name": op,
            "p50_ms": stats.get("p50_ms", 0),
            "p95_ms": stats.get("p95_ms", 0),
            "p99_ms": stats.get("p99_ms", 0),
            "count": stats.get("count", 0),
        })
    
    return {"operations": operations}


@router.get("/hot-path/stats", response_model=HotPathStats)
async def get_hot_path_stats(
    tenant_id: str = Query(...),
    bot_id: str = Query(...),
    redis_client=Depends(get_redis_client),
):
    """Get hot path statistics."""
    key = f"quantgambit:{tenant_id}:{bot_id}:hot_path:stats"
    
    data = await redis_client.get(key)
    if not data:
        return HotPathStats(
            ticks_processed=0,
            decisions_made=0,
            intents_emitted=0,
            blocked_count=0,
            pending_intents=0,
            positions=0,
            latencies={},
        )
    
    if isinstance(data, bytes):
        data = data.decode('utf-8')
    stats = json.loads(data)
    
    return HotPathStats(**stats)


# =============================================================================
# Book Guardian Endpoints
# =============================================================================

@router.get("/book-guardian/status")
async def get_book_guardian_status(
    tenant_id: str = Query(...),
    bot_id: str = Query(...),
    redis_client=Depends(get_redis_client),
):
    """Get book guardian status for all symbols."""
    key = f"quantgambit:{tenant_id}:{bot_id}:book_guardian:status"
    
    data = await redis_client.get(key)
    if not data:
        return {"symbols": {}}
    
    if isinstance(data, bytes):
        data = data.decode('utf-8')
    
    return json.loads(data)


# =============================================================================
# Guard Events Endpoints
# =============================================================================

@router.get("/guard-events")
async def get_guard_events(
    tenant_id: str = Query(...),
    bot_id: str = Query(...),
    limit: int = Query(50, le=200),
    redis_client=Depends(get_redis_client),
):
    """
    Get recent position guard events (trailing stop, SL/TP, max age).
    
    These events are published by PositionGuardWorker to telemetry.
    """
    key = f"quantgambit:{tenant_id}:{bot_id}:guard:events"
    
    items_raw = await redis_client.lrange(key, -limit, -1)
    
    events = []
    for item in items_raw:
        try:
            if isinstance(item, bytes):
                item = item.decode('utf-8')
            event = json.loads(item)
            events.append(event)
        except (json.JSONDecodeError, KeyError):
            continue
    
    # Sort by timestamp descending (most recent first)
    events.sort(key=lambda x: x.get("timestamp", 0), reverse=True)
    
    return {"events": events}


@router.get("/safety-events")
async def get_safety_events(
    tenant_id: str = Query(...),
    bot_id: str = Query(...),
    limit: int = Query(50, le=200),
    redis_client=Depends(get_redis_client),
):
    """
    Get combined safety events: kill switch + guard triggers.
    
    Aggregates events from both sources for the safety dashboard.
    """
    # Get kill switch history
    ks_key = f"quantgambit:{tenant_id}:{bot_id}:kill_switch:history"
    ks_items = await redis_client.lrange(ks_key, -limit, -1)
    
    # Get guard events
    guard_key = f"quantgambit:{tenant_id}:{bot_id}:guard:events"
    guard_items = await redis_client.lrange(guard_key, -limit, -1)
    
    events = []
    
    # Process kill switch events
    for item in ks_items:
        try:
            if isinstance(item, bytes):
                item = item.decode('utf-8')
            event = json.loads(item)
            events.append({
                "type": "kill_switch",
                "subtype": event.get("type", "unknown"),
                "timestamp": event.get("timestamp", 0),
                "message": event.get("message") or f"Kill switch {event.get('type', 'event')}",
                "trigger": event.get("trigger"),
                "operator_id": event.get("operator_id"),
            })
        except (json.JSONDecodeError, KeyError):
            continue
    
    # Process guard events
    for item in guard_items:
        try:
            if isinstance(item, bytes):
                item = item.decode('utf-8')
            event = json.loads(item)
            events.append({
                "type": "guard",
                "subtype": event.get("reason", "unknown"),
                "timestamp": event.get("timestamp", 0),
                "symbol": event.get("symbol"),
                "side": event.get("side"),
                "realized_pnl": event.get("realized_pnl"),
                "message": f"{event.get('symbol', '')} {event.get('reason', '').replace('_', ' ')}",
            })
        except (json.JSONDecodeError, KeyError):
            continue
    
    # Sort by timestamp descending
    events.sort(key=lambda x: x.get("timestamp", 0), reverse=True)
    
    return {"events": events[:limit]}


@router.get("/correlation-guard/stats")
async def get_correlation_guard_stats(
    tenant_id: str = Query(...),
    bot_id: str = Query(...),
    redis_client=Depends(get_redis_client),
):
    """Get correlation guard statistics."""
    key = f"quantgambit:{tenant_id}:{bot_id}:correlation_guard:stats"
    
    data = await redis_client.get(key)
    if not data:
        return {
            "checks_total": 0,
            "blocks_total": 0,
            "block_rate": 0.0,
        }
    
    if isinstance(data, bytes):
        data = data.decode('utf-8')
    
    return json.loads(data)


@router.get("/correlation-guard/matrix")
async def get_correlation_matrix(
    redis_client=Depends(get_redis_client),
):
    """Get the correlation matrix used by the guard."""
    from quantgambit.core.risk.correlation_guard import CORRELATION_MATRIX
    
    # Convert tuple keys to strings for JSON
    matrix = {}
    for (sym1, sym2), corr in CORRELATION_MATRIX.items():
        matrix[f"{sym1}_{sym2}"] = corr
    
    return {"correlations": matrix}


# =============================================================================
# Pipeline Health
# =============================================================================

@router.get("/pipeline/health", response_model=PipelineHealthResponse)
async def get_pipeline_health(
    tenant_id: Optional[str] = Query(None),
    bot_id: Optional[str] = Query(None),
    exchange_account_id: Optional[str] = Query(None),
    exchangeAccountId: Optional[str] = Query(None),
    redis_client=Depends(get_redis_client),
):
    """
    Get unified pipeline health showing all layers with status, latency, and throughput.
    
    Reads from actual Redis streams and keys to provide accurate pipeline status.
    """
    import time

    tenant_id = tenant_id or str(os.getenv("DEFAULT_TENANT_ID") or "").strip()
    bot_id = bot_id or str(os.getenv("DEFAULT_BOT_ID") or "").strip()

    async def discover_tenant_for_bot(current_bot: str) -> str:
        wildcard_patterns = [
            f"quantgambit:*:{current_bot}:health:latest",
            f"quantgambit:*:{current_bot}:quality:latest",
            f"quantgambit:*:{current_bot}:warmup:*",
            f"events:features:*:{current_bot}",
            f"events:decisions:*:{current_bot}",
        ]
        for pattern in wildcard_patterns:
            try:
                matches = await redis_client.keys(pattern)
            except Exception:
                continue
            for raw in matches or []:
                key = raw.decode("utf-8", errors="ignore") if isinstance(raw, bytes) else str(raw)
                if key.startswith("quantgambit:"):
                    parts = key.split(":")
                    if len(parts) >= 4 and parts[1]:
                        return parts[1]
                if key.startswith("events:"):
                    parts = key.split(":")
                    if len(parts) >= 4 and parts[2]:
                        return parts[2]
        return ""

    async def discover_tenant_from_platform(current_bot: str, current_account: str) -> str:
        if not current_bot and not current_account:
            return ""
        try:
            pool = await _get_platform_pool()
        except Exception:
            return ""
        async with pool.acquire() as conn:
            if current_bot:
                row = await conn.fetchrow(
                    """
                    SELECT user_id AS tenant_id
                    FROM bot_instances
                    WHERE id = $1
                    """,
                    current_bot,
                )
                if row and row.get("tenant_id"):
                    return str(row["tenant_id"])
            if current_account:
                row = await conn.fetchrow(
                    """
                    SELECT tenant_id
                    FROM exchange_accounts
                    WHERE id = $1
                    """,
                    current_account,
                )
                if row and row.get("tenant_id"):
                    return str(row["tenant_id"])
        return ""

    if bot_id and not tenant_id:
        tenant_id = await discover_tenant_for_bot(bot_id)
    if not tenant_id:
        account_id = (exchangeAccountId or exchange_account_id or "").strip()
        tenant_id = await discover_tenant_from_platform(bot_id, account_id)

    if not tenant_id or not bot_id:
        raise HTTPException(
            status_code=400,
            detail=(
                "tenant_id and bot_id are required, or provide a bot_id that can be resolved "
                "from live runtime state."
            ),
        )

    async def resolve_runtime_tenant(current_tenant: str, current_bot: str) -> str:
        candidate_keys = [
            f"quantgambit:{current_tenant}:{current_bot}:health:latest",
            f"quantgambit:{current_tenant}:{current_bot}:quality:latest",
            f"quantgambit:{current_tenant}:{current_bot}:warmup:BTCUSDT",
            f"events:features:{current_tenant}:{current_bot}",
            f"events:decisions:{current_tenant}:{current_bot}",
        ]
        for key in candidate_keys:
            try:
                key_type = await redis_client.type(key)
                if isinstance(key_type, bytes):
                    key_type = key_type.decode("utf-8", errors="ignore")
                key_type = str(key_type or "").strip().lower()
                if key_type and key_type != "none":
                    return current_tenant
            except Exception:
                continue

        wildcard_patterns = [
            f"quantgambit:*:{current_bot}:health:latest",
            f"quantgambit:*:{current_bot}:quality:latest",
            f"quantgambit:*:{current_bot}:warmup:*",
            f"events:features:*:{current_bot}",
            f"events:decisions:*:{current_bot}",
        ]
        for pattern in wildcard_patterns:
            try:
                matches = await redis_client.keys(pattern)
            except Exception:
                matches = []
            if not matches:
                continue
            sample = matches[0]
            if isinstance(sample, bytes):
                sample = sample.decode("utf-8", errors="ignore")
            parts = str(sample).split(":")
            if str(sample).startswith("quantgambit:") and len(parts) >= 4:
                return parts[1]
            if str(sample).startswith("events:") and len(parts) >= 4:
                return parts[2]
        return current_tenant

    tenant_id = await resolve_runtime_tenant(tenant_id, bot_id)
    
    now = time.time()
    
    # --- Helper Functions ---
    def parse_ts(ts) -> Optional[float]:
        if ts is None or ts == 0:
            return None
        if isinstance(ts, str):
            try:
                return float(ts)
            except ValueError:
                try:
                    from datetime import datetime as dt_mod
                    dt = dt_mod.fromisoformat(ts.replace('Z', '+00:00'))
                    return dt.timestamp()
                except (ValueError, AttributeError):
                    return None
        return float(ts) if ts else None
    
    def calc_age(ts) -> Optional[float]:
        parsed = parse_ts(ts)
        if parsed is None:
            return None
        return max(0, now - parsed)

    def load_prediction_model_meta() -> tuple[dict[str, Any], Optional[str]]:
        raw_path = str(os.getenv("PREDICTION_MODEL_CONFIG") or "").strip()
        if not raw_path:
            return {}, None
        path = pathlib.Path(raw_path)
        candidates: List[pathlib.Path] = []
        if path.is_absolute():
            candidates.append(path)
        else:
            candidates.append((pathlib.Path.cwd() / path).resolve())
            candidates.append((pathlib.Path(__file__).resolve().parents[2] / path).resolve())
        for candidate in candidates:
            try:
                if not candidate.exists():
                    continue
                payload = json.loads(candidate.read_text(encoding="utf-8"))
                if isinstance(payload, dict):
                    return payload, str(candidate)
            except Exception:
                continue
        return {}, None
    
    def determine_status(age_sec: Optional[float], has_data: bool, stale_threshold: float = 10.0) -> str:
        if not has_data:
            return "down"
        if age_sec is None:
            return "idle"
        if age_sec > stale_threshold * 3:
            return "down"
        if age_sec > stale_threshold:
            return "degraded"
        return "healthy"
    
    async def get_stream_info(stream_key: str) -> tuple[Optional[float], int]:
        """Get latest timestamp and approximate count from a stream."""
        try:
            # Get latest entry
            result = await redis_client.xrevrange(stream_key, '+', '-', count=1)
            if result:
                entry_id, data = result[0]
                # Use entry_id for timestamp (milliseconds-seq format)
                # This is the Redis publish time, not the payload data time
                if isinstance(entry_id, bytes):
                    entry_id = entry_id.decode('utf-8')
                ms = int(entry_id.split('-')[0])
                stream_ts = ms / 1000.0
                stream_count = await redis_client.xlen(stream_key)
                return stream_ts, stream_count
            return None, 0
        except Exception:
            return None, 0
    
    async def get_key_json(key: str) -> dict:
        """Get JSON data from a Redis key."""
        try:
            raw = await redis_client.get(key)
            if raw:
                if isinstance(raw, bytes):
                    raw = raw.decode('utf-8')
                return json.loads(raw)
        except Exception:
            pass
        return {}
    
    # --- Read Data from Redis ---
    
    # Decision data (from key, not stream for latest)
    decision_key = f"quantgambit:{tenant_id}:{bot_id}:decision:latest"
    decision_data = await get_key_json(decision_key)
    
    # Kill switch status
    kill_switch_key = f"quantgambit:{tenant_id}:{bot_id}:kill_switch:state"
    ks_data = await get_key_json(kill_switch_key)
    kill_switch_active = ks_data.get("is_active", False)
    
    # Reconciliation status
    recon_key = f"quantgambit:{tenant_id}:{bot_id}:reconciliation:status"
    recon_data = await get_key_json(recon_key)
    
    # MDS service health (includes freshness/integrity/throughput diagnostics)
    mds_health_key = os.getenv("MDS_HEALTH_KEY", "mds:health:bybit")
    mds_health = await get_key_json(mds_health_key)
    
    # Read from streams for real-time throughput
    market_data_stream = "events:market_data:bybit"
    feature_stream = f"events:features:{tenant_id}:{bot_id}"
    decision_stream = f"events:decisions:{tenant_id}:{bot_id}"
    trade_feed_stream = "events:trades:bybit"
    orderbook_feed_stream = "events:orderbook_feed:bybit"
    
    mds_ts, mds_count = await get_stream_info(market_data_stream)
    feature_ts, feature_count = await get_stream_info(feature_stream)
    decision_ts_stream, decision_count = await get_stream_info(decision_stream)
    trade_feed_ts, trade_feed_count = await get_stream_info(trade_feed_stream)
    orderbook_feed_ts, orderbook_feed_count = await get_stream_info(orderbook_feed_stream)
    
    # Get prediction status for quality info (check one symbol)
    prediction_key = f"quantgambit:{tenant_id}:{bot_id}:prediction:BTCUSDT:latest"
    prediction_data = await get_key_json(prediction_key)
    
    # Get profile router info
    profile_router_key = f"quantgambit:{tenant_id}:{bot_id}:profile_router:latest"
    profile_router_data = await get_key_json(profile_router_key)
    
    # Get latest feature snapshot for data quality flags
    feature_snapshot = {}
    try:
        result = await redis_client.xrevrange(feature_stream, '+', '-', count=1)
        if result:
            _, data = result[0]
            payload = data.get(b'data') or data.get('data')
            if payload:
                if isinstance(payload, bytes):
                    payload = payload.decode('utf-8')
                parsed = json.loads(payload)
                feature_snapshot = parsed.get('payload', {}).get('market_context', {})
    except Exception:
        pass
    
    # Helper for stream-rate estimation using recent event windows.
    async def sample_stream_events(
        stream_key: str,
        *,
        sample_count: int = 300,
        parse_payload: bool = False,
    ) -> List[Dict[str, Any]]:
        """
        Read a recent stream window and return normalized entries.

        We intentionally compute throughput from sampled event timestamps instead of
        XLEN/retention-size to avoid inflated rates when streams are aggressively trimmed.
        """
        try:
            result = await redis_client.xrevrange(stream_key, "+", "-", count=sample_count)
        except Exception:
            return []

        samples: List[Dict[str, Any]] = []
        for entry_id, data in result:
            try:
                entry_id_str = entry_id.decode("utf-8") if isinstance(entry_id, bytes) else str(entry_id)
                ts = int(entry_id_str.split("-")[0]) / 1000.0
            except Exception:
                continue

            entry: Dict[str, Any] = {"ts": ts}
            if parse_payload:
                payload_raw = data.get(b"data") if isinstance(data, dict) else None
                if payload_raw is None and isinstance(data, dict):
                    payload_raw = data.get("data")
                parsed_payload: Dict[str, Any] = {}
                if payload_raw:
                    try:
                        if isinstance(payload_raw, bytes):
                            payload_raw = payload_raw.decode("utf-8")
                        parsed = json.loads(payload_raw)
                        if isinstance(parsed, dict):
                            parsed_payload = parsed.get("payload", parsed)
                    except Exception:
                        parsed_payload = {}
                entry["payload"] = parsed_payload
            samples.append(entry)

        return samples

    def rate_per_sec(samples: List[Dict[str, Any]]) -> float:
        """Compute events/sec from a sampled stream window."""
        if len(samples) < 2:
            return 0.0
        newest_ts = samples[0]["ts"]
        oldest_ts = samples[-1]["ts"]
        span_sec = max(0.0, newest_ts - oldest_ts)
        if span_sec <= 0.0:
            return 0.0
        return float(len(samples) - 1) / span_sec

    def is_normal_rejection(reason: Optional[str]) -> bool:
        return _is_non_problem_decision_rejection(reason)

    def is_accepted_decision(payload: Dict[str, Any]) -> bool:
        decision = str(payload.get("decision") or "").strip().lower()
        rejection_reason = payload.get("rejection_reason")
        signal = payload.get("signal")
        if decision == "rejected" or rejection_reason:
            return False
        if signal is None:
            return decision in {"accepted", "complete", "completed"}
        return True

    def is_fill_event(payload: Dict[str, Any]) -> bool:
        status = str(payload.get("status") or "").strip().lower()
        event = str(payload.get("event") or "").strip().lower()
        return status in {"filled", "partially_filled"} or event in {"fill", "filled"}

    def avg_symbol_metric(data: Dict[str, Any], key: str) -> Optional[float]:
        values = data.get(key)
        if not isinstance(values, dict):
            return None
        nums: List[float] = []
        for raw in values.values():
            if raw is None:
                continue
            try:
                nums.append(float(raw))
            except (TypeError, ValueError):
                continue
        if not nums:
            return None
        return round(sum(nums) / len(nums), 3)

    def is_close_fill(payload: Dict[str, Any]) -> bool:
        position_effect = str(payload.get("position_effect") or "").strip().lower()
        if position_effect == "close":
            return True
        reason = str(payload.get("reason") or "").strip().lower()
        return "close" in reason or "exit" in reason

    def normalize_position_side_from_close_fill(payload: Dict[str, Any]) -> Optional[str]:
        return _normalize_position_side_from_close_payload(payload)

    def close_event_identity(payload: Dict[str, Any]) -> Optional[str]:
        return _close_event_identity(payload)

    def extract_order_payload(sample: Dict[str, Any]) -> Dict[str, Any]:
        raw = sample.get("payload")
        if not isinstance(raw, dict):
            return {}
        nested = raw.get("payload")
        if isinstance(nested, dict):
            return nested
        return raw

    async def sample_close_order_events_with_pnl(limit: int = 600) -> List[Dict[str, Any]]:
        """
        Read recent close-side order_events from Timescale/Postgres where realized PnL exists.
        This is the canonical source for realized PnL (streams often omit net_pnl fields).
        """
        try:
            pool = await _get_timescale_pool()
            async with pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT ts, payload
                    FROM order_events
                    WHERE tenant_id=$1
                      AND bot_id=$2
                      AND (
                        lower(coalesce(payload->>'position_effect',''))='close'
                        OR lower(coalesce(payload->>'reason','')) LIKE '%close%'
                        OR lower(coalesce(payload->>'reason','')) LIKE '%exit%'
                        OR lower(coalesce(payload->>'close_reason','')) LIKE '%close%'
                        OR lower(coalesce(payload->>'close_reason','')) LIKE '%exit%'
                      )
                      AND (
                        payload ? 'net_pnl'
                        OR payload ? 'realized_pnl'
                      )
                    ORDER BY ts DESC
                    LIMIT $3
                    """,
                    tenant_id,
                    bot_id,
                    int(limit),
                )
            parsed: List[Dict[str, Any]] = []
            for row in rows:
                payload = row.get("payload")
                if isinstance(payload, str):
                    try:
                        payload = json.loads(payload)
                    except Exception:
                        payload = {}
                if isinstance(payload, dict):
                    # Preserve DB event timestamp for accurate rolling-window stats.
                    payload["__event_ts"] = row.get("ts")
                    parsed.append(payload)
            return parsed
        except Exception:
            return []

    # Pre-sample stream windows for realistic rates/summary metrics.
    mds_samples = await sample_stream_events(market_data_stream, sample_count=300)
    trade_samples = await sample_stream_events(trade_feed_stream, sample_count=300)
    orderbook_samples = await sample_stream_events(orderbook_feed_stream, sample_count=300)
    feature_samples = await sample_stream_events(feature_stream, sample_count=300)
    feature_samples_with_payload = await sample_stream_events(feature_stream, sample_count=400, parse_payload=True)
    decision_samples = await sample_stream_events(decision_stream, sample_count=600, parse_payload=True)
    order_update_samples = await sample_stream_events("events:order_updates", sample_count=600, parse_payload=True)
    if not order_update_samples:
        # Backward compatibility for legacy singular stream key.
        order_update_samples = await sample_stream_events("events:order_update", sample_count=600, parse_payload=True)
    
    # Build layers
    layers: List[LayerHealth] = []
    
    # --- INGEST LAYER ---
    # For ingest, use feature stream timestamp since it's bot-specific
    ingest_age = calc_age(feature_ts) if feature_ts else calc_age(mds_ts)
    
    # Check individual feed health by timestamp age
    trade_feed_age = calc_age(trade_feed_ts)
    orderbook_feed_age = calc_age(orderbook_feed_ts)
    
    # Trade feed is stale if >30 seconds old
    trade_feed_stale = trade_feed_age is None or trade_feed_age > 30
    # Orderbook feed is stale if >10 seconds old  
    orderbook_feed_stale = orderbook_feed_age is None or orderbook_feed_age > 10
    
    # Use sampled windows for throughput (events per second).
    mds_throughput = rate_per_sec(mds_samples)
    trade_throughput = rate_per_sec(trade_samples)
    orderbook_throughput = rate_per_sec(orderbook_samples)
    
    # Get quality status from feature snapshot (more accurate than prediction)
    orderbook_sync = feature_snapshot.get("orderbook_sync_state") or prediction_data.get("orderbook_sync_state", "unknown")
    trade_sync = feature_snapshot.get("trade_sync_state") or prediction_data.get("trade_sync_state", "unknown")
    quality_flags = feature_snapshot.get("data_quality_flags") or prediction_data.get("flags", []) or []
    candle_sync = feature_snapshot.get("candle_sync_state", "unknown")
    
    # Determine trade worker status from actual stream health
    trade_status = "down" if trade_feed_stale else "healthy"
    if trade_sync == "stale" or "trade_stale" in quality_flags:
        trade_status = "degraded"
    
    # Determine orderbook worker status
    orderbook_status = "down" if orderbook_feed_stale else "healthy"
    if orderbook_sync != "synced" and orderbook_sync != "unknown":
        orderbook_status = "degraded"
    
    # Ingest status: use feature stream for bot-specific health
    ingest_status = determine_status(ingest_age, bool(feature_ts or mds_ts))
    # Downgrade to degraded/down if feeds are unhealthy
    if trade_feed_stale or orderbook_feed_stale:
        ingest_status = "down" if (trade_feed_stale and orderbook_feed_stale) else "degraded"
    
    ingest_workers = [
        WorkerHealth(
            name="Market Data Service",
            status=ingest_status,
            throughput_per_sec=round(mds_throughput, 2),
            mds_quality_score=(
                float(mds_health.get("mds_quality_score"))
                if mds_health.get("mds_quality_score") is not None
                else None
            ),
            orderbook_event_rate_l1_eps=avg_symbol_metric(mds_health, "orderbook_event_rate_l1_eps"),
            orderbook_event_rate_l2_eps=avg_symbol_metric(mds_health, "orderbook_event_rate_l2_eps"),
        ),
        WorkerHealth(
            name="Orderbook WebSocket",
            status=orderbook_status,
            throughput_per_sec=round(orderbook_throughput, 2),
            last_event_ts=orderbook_feed_ts,
            error_message=f"No data for {orderbook_feed_age:.0f}s" if orderbook_feed_stale and orderbook_feed_age else None,
        ),
        WorkerHealth(
            name="Trade WebSocket",
            status=trade_status,
            throughput_per_sec=round(trade_throughput, 2),
            last_event_ts=trade_feed_ts,
            error_message=f"No data for {trade_feed_age:.0f}s - RESTART MDS!" if trade_feed_stale and trade_feed_age else None,
        ),
        WorkerHealth(
            name="Candles",
            status="degraded" if candle_sync == "stale" or "candle_stale" in quality_flags else "healthy",
        ),
    ]
    
    ingest_blockers = []
    if trade_feed_stale:
        ingest_blockers.append(f"trade_websocket_disconnected ({trade_feed_age:.0f}s stale)" if trade_feed_age else "trade_websocket_down")
    elif trade_sync == "stale" or "trade_stale" in quality_flags:
        ingest_blockers.append("trade_feed_stale")
    if orderbook_feed_stale:
        ingest_blockers.append(f"orderbook_websocket_disconnected ({orderbook_feed_age:.0f}s stale)" if orderbook_feed_age else "orderbook_websocket_down")
    elif orderbook_sync != "synced" and orderbook_sync != "unknown":
        ingest_blockers.append("orderbook_not_synced")
    
    layers.append(LayerHealth(
        name="ingest",
        display_name="Ingest",
        status=ingest_status,
        throughput_per_sec=round(mds_throughput, 2),
        last_event_ts=feature_ts or mds_ts,  # Use bot-specific timestamp
        age_sec=ingest_age,
        blockers=ingest_blockers,
        workers=ingest_workers,
        events_processed=mds_count,
    ))
    
    # --- FEATURE LAYER ---
    feature_age = calc_age(feature_ts)
    feature_throughput = rate_per_sec(feature_samples)
    
    feature_blockers = []
    quality_score = feature_snapshot.get("data_quality_score") or prediction_data.get("quality_score", 1.0)
    quality_status = feature_snapshot.get("data_quality_status", "ok")
    
    if quality_score and quality_score < 0.6:
        feature_blockers.append(f"low_data_quality ({quality_score:.2f})")
    if quality_status != "ok":
        feature_blockers.append(f"quality_status: {quality_status}")
    if quality_flags:
        for flag in quality_flags[:3]:  # Show up to 3 flags
            feature_blockers.append(flag)
    
    feature_status = determine_status(feature_age, bool(feature_ts))
    # Downgrade if data quality is poor
    if quality_score and quality_score < 0.8 and feature_status == "healthy":
        feature_status = "degraded"
    
    layers.append(LayerHealth(
        name="feature",
        display_name="Features",
        status=feature_status,
        throughput_per_sec=round(feature_throughput, 2),
        last_event_ts=feature_ts,
        age_sec=feature_age,
        blockers=feature_blockers,
        workers=[
            WorkerHealth(
                name="Feature Worker",
                status=feature_status,
            ),
        ],
        events_processed=feature_count,
    ))
    
    # --- DECISION LAYER ---
    decision_ts_key = decision_data.get("timestamp")
    decision_ts_final = decision_ts_stream or parse_ts(decision_ts_key)
    decision_age = calc_age(decision_ts_final)
    decision_throughput = rate_per_sec(decision_samples)
    
    decision_blockers = []
    rejection_reason = decision_data.get("rejection_reason")
    if rejection_reason:
        decision_blockers.append(rejection_reason)
    
    # Get profile info
    profile_id = decision_data.get("profile_id") or profile_router_data.get("matched_profile_id")
    
    # Estimate accepted vs rejected from decision result
    decisions_accepted = 0
    decisions_rejected = decision_count  # Most are rejections when no_signal
    
    # Decision layer status - treat stale/no-signal periods as idle, not down.
    decision_status = determine_status(decision_age, bool(decision_ts_final))
    if decision_status == "down" and (not rejection_reason or is_normal_rejection(rejection_reason)):
        decision_status = "idle"
    if decision_status == "healthy" and rejection_reason and not is_normal_rejection(rejection_reason):
        decision_status = "degraded"  # Healthy but blocked by a non-routine rejection
    
    # --- PER-SYMBOL DECISION STATUS ---
    # Get active symbols from warmup or configured symbol lists.
    active_symbols: List[str] = []
    
    # Try to get symbols from warmup state
    warmup_key = f"quantgambit:{tenant_id}:{bot_id}:warmup:*"
    try:
        warmup_keys = await redis_client.keys(warmup_key)
        if warmup_keys:
            active_symbols = []
            for key in warmup_keys:
                if isinstance(key, bytes):
                    key = key.decode('utf-8')
                # Extract symbol from key like "quantgambit:tenant:bot:warmup:BTCUSDT"
                parts = key.split(':')
                if len(parts) >= 5:
                    active_symbols.append(parts[-1])
    except Exception:
        pass

    if not active_symbols:
        configured_symbols: List[str] = []
        for env_key in ("SYMBOLS", "ORDERBOOK_SYMBOLS", "MARKET_DATA_SYMBOLS"):
            raw = os.getenv(env_key, "")
            if not raw:
                continue
            configured_symbols.extend([s.strip() for s in raw.split(",") if s.strip()])
        # Keep insertion order while deduping.
        active_symbols = list(dict.fromkeys(configured_symbols))
    
    def _session_from_ts(ts: Optional[float]) -> str:
        """Derive canonical trading session from UTC timestamp."""
        try:
            ts_f = float(ts) if ts is not None else time.time()
        except Exception:
            ts_f = time.time()
        hour_utc = datetime.fromtimestamp(ts_f, tz=timezone.utc).hour
        if 0 <= hour_utc < 7:
            return "asia"
        if 7 <= hour_utc < 12:
            return "europe"
        if 12 <= hour_utc < 22:
            return "us"
        return "overnight"

    # Get per-symbol decision status
    symbol_statuses = []
    for symbol in active_symbols:
        # Get latest decision for this symbol
        symbol_decision_key = f"quantgambit:{tenant_id}:{bot_id}:decision:{symbol}:latest"
        symbol_decision = await get_key_json(symbol_decision_key)
        
        # If no per-symbol key, try to get from recent stream entries
        if not symbol_decision:
            try:
                # Read recent decisions from stream and filter by symbol
                result = await redis_client.xrevrange(decision_stream, '+', '-', count=50)
                for entry_id, data in result:
                    payload = data.get(b'data') or data.get('data')
                    if payload:
                        if isinstance(payload, bytes):
                            payload = payload.decode('utf-8')
                        parsed = json.loads(payload)
                        entry_symbol = parsed.get('symbol') or parsed.get('payload', {}).get('symbol')
                        if entry_symbol == symbol:
                            symbol_decision = parsed.get('payload', parsed)
                            # Use entry_id for timestamp
                            if isinstance(entry_id, bytes):
                                entry_id = entry_id.decode('utf-8')
                            ms = int(entry_id.split('-')[0])
                            symbol_decision['_stream_ts'] = ms / 1000.0
                            break
            except Exception:
                pass
        
        # Determine symbol status
        symbol_ts = symbol_decision.get('_stream_ts') or parse_ts(symbol_decision.get('timestamp'))
        symbol_age = calc_age(symbol_ts)
        symbol_rejection = symbol_decision.get('rejection_reason')
        symbol_profile = symbol_decision.get('profile_id')
        symbol_strategy = (
            symbol_decision.get("strategy_id")
            or (symbol_decision.get("signal") or {}).get("strategy_id")
            or (symbol_decision.get("candidate") or {}).get("strategy_id")
        )
        symbol_session = (
            symbol_decision.get("session")
            or symbol_decision.get("session_name")
            or (symbol_decision.get("market_context") or {}).get("session")
            or (symbol_decision.get("profile_router") or {}).get("session")
        )
        if symbol_session is None or str(symbol_session).strip() == "":
            symbol_session = _session_from_ts(symbol_ts)
        
        # Status logic: healthy if recent and not rejecting, degraded if rejecting, down if stale
        if symbol_age is None or symbol_age > 30:
            sym_status = "idle"
        elif symbol_rejection and not _is_non_problem_decision_rejection(symbol_rejection):
            sym_status = "degraded"  # Blocking rejection
        elif symbol_rejection:
            sym_status = "healthy"  # Normal rejection (no_signal, low_confidence)
        else:
            sym_status = "healthy"
        
        symbol_statuses.append(SymbolStatus(
            symbol=symbol,
            status=sym_status,
            last_decision_ts=symbol_ts,
            age_sec=symbol_age,
            rejection_reason=symbol_rejection,
            profile_id=symbol_profile,
            strategy_id=(str(symbol_strategy) if symbol_strategy is not None else None),
            session=(str(symbol_session) if symbol_session is not None else _session_from_ts(symbol_ts)),
        ))
    
    layers.append(LayerHealth(
        name="decision",
        display_name="Decision",
        status=decision_status,
        throughput_per_sec=round(decision_throughput, 2),
        last_event_ts=decision_ts_final,
        age_sec=decision_age,
        blockers=decision_blockers,
        workers=[
            WorkerHealth(
                name="Profile Router",
                status="healthy" if profile_id else "degraded",
            ),
            WorkerHealth(
                name="Decision Worker",
                status=decision_status,
            ),
        ],
        events_processed=decision_count,
        events_rejected=decision_count if rejection_reason else 0,
        symbol_status=symbol_statuses if symbol_statuses else None,
    ))
    
    # --- RISK LAYER ---
    risk_blockers = []
    if kill_switch_active:
        risk_blockers.append("kill_switch_active")
    
    layers.append(LayerHealth(
        name="risk",
        display_name="Risk",
        status="down" if kill_switch_active else "healthy",
        blockers=risk_blockers,
        workers=[
            WorkerHealth(
                name="Risk Worker",
                status="down" if kill_switch_active else "healthy",
            ),
            WorkerHealth(
                name="Kill Switch",
                status="down" if kill_switch_active else "healthy",
            ),
            WorkerHealth(
                name="Position Guard",
                status="healthy",
            ),
        ],
    ))
    
    # --- EXECUTION LAYER ---
    # Check for recent orders in order stream
    order_stream = "events:order_updates"
    order_ts, order_count = await get_stream_info(order_stream)
    if not order_ts and order_count == 0:
        # Backward compatibility for legacy singular stream key.
        order_stream = "events:order_update"
        order_ts, order_count = await get_stream_info(order_stream)
    exec_age = calc_age(order_ts)
    
    # Execution status: idle if no orders and system is rejecting with no_signal
    # This isn't a problem - the bot is working, just waiting for edge
    exec_status = "idle"
    if order_ts and exec_age is not None:
        if exec_age < 60:
            exec_status = "healthy"
        elif exec_age < 3600:  # Less than 1 hour
            exec_status = "idle"  # Not down, just waiting for signals
        else:
            exec_status = "idle"  # Still just waiting - not "down"
    
    layers.append(LayerHealth(
        name="execution",
        display_name="Execution",
        status=exec_status,
        last_event_ts=order_ts,
        age_sec=exec_age,
        workers=[
            WorkerHealth(
                name="Execution Worker",
                status=exec_status,
            ),
        ],
        events_processed=order_count,
    ))
    
    # --- RECONCILIATION LAYER ---
    recon_total_runs = recon_data.get("total_runs", 0)
    recon_discrepancies = recon_data.get("total_discrepancies", 0)
    
    layers.append(LayerHealth(
        name="reconciliation",
        display_name="Reconciliation",
        status="healthy" if recon_total_runs > 0 else "idle",
        workers=[
            WorkerHealth(
                name="Reconciler Worker",
                status="healthy" if recon_total_runs > 0 else "idle",
            ),
            WorkerHealth(
                name="Order Store",
                status="healthy",
            ),
        ],
        events_processed=recon_total_runs,
        blockers=[f"discrepancies: {recon_discrepancies}"] if recon_discrepancies > 0 else [],
    ))
    
    # Calculate overall status
    layer_statuses = [layer.status for layer in layers]
    if "down" in layer_statuses:
        overall_status = "down"
    elif "degraded" in layer_statuses:
        overall_status = "degraded"
    else:
        overall_status = "healthy"
    
    # Prediction mode/status summary for dashboard diagnostics.
    live_source_counts: Dict[str, int] = {}
    gate_status_counts: Dict[str, int] = {}
    shadow_source_counts: Dict[str, int] = {}
    # Per-symbol breakdown so we can show "onnx by symbol" even when the
    # prediction score snapshot job isn't running yet.
    per_symbol_live_source_counts: Dict[str, Dict[str, int]] = {}
    per_symbol_gate_status_counts: Dict[str, Dict[str, int]] = {}
    per_symbol_calibration_applied: Dict[str, Dict[str, int]] = {}
    onnx_live_count = 0
    fallback_count = 0
    suppressed_live_count = 0
    parsed_feature_predictions = 0
    for sample in feature_samples_with_payload:
        payload = sample.get("payload") or {}
        if not isinstance(payload, dict):
            continue
        parsed_feature_predictions += 1
        live_pred = payload.get("prediction") if isinstance(payload.get("prediction"), dict) else {}
        shadow_pred = payload.get("prediction_shadow") if isinstance(payload.get("prediction_shadow"), dict) else {}
        prediction_status = payload.get("prediction_status") if isinstance(payload.get("prediction_status"), dict) else {}
        market_context = payload.get("market_context") if isinstance(payload.get("market_context"), dict) else {}
        symbol = str(payload.get("symbol") or "").strip() or "unknown"

        live_source = str(live_pred.get("source") or "").strip()
        if not live_source:
            pred_state = str(prediction_status.get("status") or "").strip().lower()
            pred_reason = str(
                prediction_status.get("reason")
                or market_context.get("prediction_blocked")
                or ""
            ).strip().lower()
            if pred_state in {"suppressed", "blocked", "abstain"} or pred_reason:
                if pred_reason.startswith("score_"):
                    live_source = "suppressed_score_gate"
                else:
                    live_source = "suppressed"
            else:
                live_source = "unknown"
        live_source_counts[live_source] = int(live_source_counts.get(live_source, 0)) + 1
        if "onnx" in live_source.lower():
            onnx_live_count += 1
        if live_source.startswith("suppressed"):
            suppressed_live_count += 1
        if symbol not in per_symbol_live_source_counts:
            per_symbol_live_source_counts[symbol] = {}
        per_symbol_live_source_counts[symbol][live_source] = int(
            per_symbol_live_source_counts[symbol].get(live_source, 0)
        ) + 1

        # Track whether calibration is being applied (should be true for ONNX predictions
        # when model meta has probability_calibration enabled).
        applied = bool(live_pred.get("calibration_applied"))
        if symbol not in per_symbol_calibration_applied:
            per_symbol_calibration_applied[symbol] = {"true": 0, "false": 0}
        per_symbol_calibration_applied[symbol]["true" if applied else "false"] = int(
            per_symbol_calibration_applied[symbol].get("true" if applied else "false", 0)
        ) + 1

        shadow_source = str(shadow_pred.get("source") or "unknown").strip() or "unknown"
        shadow_source_counts[shadow_source] = int(shadow_source_counts.get(shadow_source, 0)) + 1

        gate_status = str(market_context.get("prediction_score_gate_status") or "").strip().lower()
        if not gate_status:
            pred_reason = str(
                prediction_status.get("reason")
                or market_context.get("prediction_blocked")
                or ""
            ).strip().lower()
            if pred_reason.startswith("score_"):
                gate_status = "blocked"
            elif str(prediction_status.get("status") or "").strip().lower() in {"suppressed", "blocked"}:
                gate_status = "blocked"
            else:
                gate_status = "none"
        gate_status_counts[gate_status] = int(gate_status_counts.get(gate_status, 0)) + 1
        if gate_status == "fallback":
            fallback_count += 1
        if symbol not in per_symbol_gate_status_counts:
            per_symbol_gate_status_counts[symbol] = {}
        per_symbol_gate_status_counts[symbol][gate_status] = int(
            per_symbol_gate_status_counts[symbol].get(gate_status, 0)
        ) + 1

    total_live_predictions = sum(live_source_counts.values()) or 0
    heuristic_count = sum(
        count for source, count in live_source_counts.items() if "heuristic" in source.lower()
    )
    live_primary_source = max(live_source_counts.items(), key=lambda item: item[1])[0] if live_source_counts else "unknown"
    model_meta, model_meta_path = load_prediction_model_meta()
    expert_items = model_meta.get("experts")
    experts = expert_items if isinstance(expert_items, list) else []
    moe_enabled = len(experts) > 0
    expert_status: List[Dict[str, Any]] = []
    latest_calibration_ts: Optional[float] = None
    experts_with_calibration = 0
    for item in experts:
        if not isinstance(item, dict):
            continue
        expert_id = str(item.get("id") or "").strip() or "unknown"
        calibration = item.get("probability_calibration")
        if not isinstance(calibration, dict):
            provider_cfg = item.get("provider_config")
            if isinstance(provider_cfg, dict) and isinstance(provider_cfg.get("probability_calibration"), dict):
                calibration = provider_cfg.get("probability_calibration")
        if not isinstance(calibration, dict):
            calibration = {}
        fitted_at = parse_ts(calibration.get("fitted_at"))
        if fitted_at is not None:
            latest_calibration_ts = max(latest_calibration_ts or fitted_at, fitted_at)
        calibrated_classes = 0
        per_class = calibration.get("per_class")
        if isinstance(per_class, dict):
            calibrated_classes = len([k for k, v in per_class.items() if isinstance(v, dict)])
        if calibrated_classes > 0:
            experts_with_calibration += 1
        expert_status.append(
            {
                "id": expert_id,
                "calibration_source": str(calibration.get("source") or "unknown"),
                "calibrated_classes": calibrated_classes,
                "fitted_at": fitted_at,
                "age_sec": calc_age(fitted_at),
            }
        )
    moe_latest_calibration_age_sec = calc_age(latest_calibration_ts) if latest_calibration_ts else None

    if onnx_live_count > 0 and heuristic_count > 0:
        prediction_mode = "mixed"
    elif onnx_live_count > 0 and moe_enabled:
        prediction_mode = "onnx_moe"
    elif onnx_live_count > 0:
        prediction_mode = "onnx"
    elif heuristic_count > 0:
        prediction_mode = "fallback"
    elif suppressed_live_count > 0:
        prediction_mode = "suppressed"
    else:
        prediction_mode = "unknown"

    score_snapshot_key = f"quantgambit:{tenant_id}:{bot_id}:prediction:score:latest"
    score_snapshot = await get_key_json(score_snapshot_key)
    score_symbols: List[Dict[str, Any]] = []
    score_snapshot_missing = not bool(score_snapshot)
    score_status = "missing" if score_snapshot_missing else str(score_snapshot.get("status") or "unknown")
    score_provider = "none" if score_snapshot_missing else str(score_snapshot.get("provider") or "unknown")
    score_timestamp = parse_ts(score_snapshot.get("timestamp") or score_snapshot.get("updated_at"))
    score_age_sec = calc_age(score_timestamp) if score_timestamp else None
    if isinstance(score_snapshot.get("symbols"), dict):
        for symbol, entry in sorted(score_snapshot.get("symbols", {}).items()):
            entry_dict = entry if isinstance(entry, dict) else {}
            score_symbols.append(
                {
                    "symbol": str(symbol),
                    "status": str(entry_dict.get("status") or "unknown"),
                    "samples": int(entry_dict.get("samples") or 0),
                    "ml_score": float(entry_dict.get("ml_score")) if entry_dict.get("ml_score") is not None else None,
                    "exact_accuracy": float(entry_dict.get("exact_accuracy")) if entry_dict.get("exact_accuracy") is not None else None,
                    "ece_top1": float(entry_dict.get("ece_top1")) if entry_dict.get("ece_top1") is not None else None,
                }
            )
    else:
        # If we don't have a scorer job populating Redis yet, derive a minimal per-symbol
        # snapshot from recent feature snapshots so the UI doesn't show empty/unknown.
        derived_symbols = sorted(
            {s for s in (active_symbols or []) if s} | set(per_symbol_live_source_counts.keys())
        )
        for symbol in derived_symbols:
            source_counts = per_symbol_live_source_counts.get(symbol, {})
            gate_counts = per_symbol_gate_status_counts.get(symbol, {})
            cal_counts = per_symbol_calibration_applied.get(symbol, {"true": 0, "false": 0})
            samples = int(sum(source_counts.values()) or 0)
            score_symbols.append(
                {
                    "symbol": str(symbol),
                    # "unscored" means we are producing predictions, but no score snapshot process
                    # is publishing evaluation metrics yet.
                    "status": "unscored" if samples > 0 else "no_recent_predictions",
                    "samples": samples,
                    "ml_score": None,
                    "exact_accuracy": None,
                    "ece_top1": None,
                    # Extra diagnostics for the dashboard.
                    "live_source_counts": source_counts,
                    "score_gate_status_counts": gate_counts,
                    "calibration_applied_counts": cal_counts,
                }
            )

    symbol_states = [s.get("status") for s in score_symbols if s.get("status")]
    # "onnx_status" should reflect **current live usage**, not the evaluator snapshot.
    # The evaluator (score snapshot) is still useful to display, but it should not
    # override reality when we see onnx_v1 predictions flowing.
    if onnx_live_count > 0 and heuristic_count == 0:
        onnx_status = "active"
    elif onnx_live_count > 0 and heuristic_count > 0:
        onnx_status = "mixed"
    elif onnx_live_count == 0 and heuristic_count > 0:
        onnx_status = "fallback"
    elif onnx_live_count == 0 and heuristic_count == 0 and suppressed_live_count > 0:
        onnx_status = "blocked"
    else:
        onnx_status = "unknown"

    # Detect whether the score gate is actively influencing live predictions by looking
    # at recent feature snapshots (market_context.prediction_score_gate_status).
    score_gate_enabled = any(
        (status in {"fallback", "blocked"}) and int(count or 0) > 0
        for status, count in (gate_status_counts or {}).items()
    )
    # Infer gate mode from runtime-emitted statuses first (source of truth).
    # API-process env can differ from runtime env and produced misleading UI.
    score_gate_mode = _infer_score_gate_mode(gate_status_counts)

    # Surface top-level probability calibration metadata (non-MoE case).
    top_level_cal = model_meta.get("probability_calibration") if isinstance(model_meta, dict) else None
    top_level_cal = top_level_cal if isinstance(top_level_cal, dict) else {}
    top_level_cal_fitted_at = parse_ts(top_level_cal.get("fitted_at") or top_level_cal.get("timestamp"))
    top_level_cal_metrics_after = top_level_cal.get("metrics_after") if isinstance(top_level_cal.get("metrics_after"), dict) else {}
    top_level_cal_ece = top_level_cal_metrics_after.get("ece_top1")
    try:
        top_level_cal_ece = float(top_level_cal_ece) if top_level_cal_ece is not None else None
    except (TypeError, ValueError):
        top_level_cal_ece = None

    prediction_summary = {
        "mode": prediction_mode,
        "onnx_status": onnx_status,
        "live_primary_source": live_primary_source,
        "live_source_counts": live_source_counts,
        "shadow_source_counts": shadow_source_counts,
        "gate_status_counts": gate_status_counts,
        "onnx_live_share_pct": round((onnx_live_count / float(total_live_predictions)) * 100.0, 2)
        if total_live_predictions > 0
        else 0.0,
        "fallback_rate_pct": round((fallback_count / float(parsed_feature_predictions)) * 100.0, 2)
        if parsed_feature_predictions > 0
        else 0.0,
        "score_gate_enabled": score_gate_enabled,
        "score_gate_mode": score_gate_mode,
        "score_snapshot_provider": score_provider,
        "score_snapshot_status": score_status,
        "score_snapshot_age_sec": score_age_sec,
        "score_snapshot_missing": score_snapshot_missing,
        "moe_enabled": moe_enabled,
        "moe_experts_total": len(experts),
        "moe_experts_with_calibration": experts_with_calibration,
        "moe_latest_calibration_age_sec": moe_latest_calibration_age_sec,
        "moe_model_meta_path": model_meta_path,
        "moe_expert_status": expert_status,
        "probability_calibration": {
            "enabled": bool(top_level_cal.get("enabled")),
            "method": str(top_level_cal.get("method") or "unknown"),
            "fitted_at": top_level_cal_fitted_at,
            "age_sec": calc_age(top_level_cal_fitted_at),
            "ece_top1_after": top_level_cal_ece,
        }
        if top_level_cal
        else None,
        "symbols": score_symbols,
    }
    model_feature_keys_raw = model_meta.get("feature_keys") if isinstance(model_meta, dict) else None
    model_feature_keys = [str(item) for item in model_feature_keys_raw] if isinstance(model_feature_keys_raw, list) else []
    prediction_summary["input_feature_health"] = _summarize_prediction_input_health(
        feature_samples_with_payload,
        model_feature_keys,
    )

    # Calculate rates from sampled windows.
    accepted_decisions = [s for s in decision_samples if is_accepted_decision(s.get("payload", {}))]
    decisions_per_minute = rate_per_sec(accepted_decisions) * 60.0

    fill_events = [s for s in order_update_samples if is_fill_event(extract_order_payload(s))]
    fills_per_hour = rate_per_sec(fill_events) * 3600.0

    # Directional canary metrics from close-side order events with realized PnL.
    # We intentionally base both "trades" and "pnl_samples" on the same canonical
    # deduped source so the dashboard is internally consistent.
    directional_counts = {"long": 0, "short": 0}
    directional_wins = {"long": 0, "short": 0}
    directional_pnl = {"long": 0.0, "short": 0.0}
    directional_pnl_samples = {"long": 0, "short": 0}

    # Source counts and realized PnL from canonical order_events rows.
    close_order_events = await sample_close_order_events_with_pnl(limit=600)
    seen_pnl_ids: set[str] = set()
    for payload in close_order_events:
        identity = close_event_identity(payload)
        if not identity or identity in seen_pnl_ids:
            continue
        seen_pnl_ids.add(identity)
        side = normalize_position_side_from_close_fill(payload)
        if side is None:
            continue
        pnl = payload.get("net_pnl")
        if pnl is None:
            pnl = payload.get("realized_pnl")
        try:
            pnl_f = float(pnl)
        except (TypeError, ValueError):
            continue
        directional_counts[side] += 1
        directional_pnl_samples[side] += 1
        directional_pnl[side] += pnl_f
        if pnl_f > 0:
            directional_wins[side] += 1
    canary = {
        "samples_close_fills": int(sum(directional_counts.values())),
        "long": {
            "trades": int(directional_counts["long"]),
            "pnl_samples": int(directional_pnl_samples["long"]),
            "win_rate": round((directional_wins["long"] / directional_pnl_samples["long"]), 4) if directional_pnl_samples["long"] else None,
            "expectancy_net_pnl": round((directional_pnl["long"] / directional_pnl_samples["long"]), 6) if directional_pnl_samples["long"] else None,
        },
        "short": {
            "trades": int(directional_counts["short"]),
            "pnl_samples": int(directional_pnl_samples["short"]),
            "win_rate": round((directional_wins["short"] / directional_pnl_samples["short"]), 4) if directional_pnl_samples["short"] else None,
            "expectancy_net_pnl": round((directional_pnl["short"] / directional_pnl_samples["short"]), 6) if directional_pnl_samples["short"] else None,
        },
    }
    prediction_summary["directional_canary"] = canary
    prediction_summary["directional_readiness"] = _build_directional_readiness(canary)
    prediction_summary["entry_quality_readiness"] = _build_entry_quality_readiness(
        feature_samples_with_payload,
        decision_samples,
    )
    # Rolling performance by prediction source (realized close-fill PnL).
    # Helps compare heuristic live behavior while ONNX runs in shadow.
    def _to_epoch(raw_ts: Any) -> Optional[float]:
        if raw_ts is None:
            return None
        if isinstance(raw_ts, (int, float)):
            return float(raw_ts)
        if hasattr(raw_ts, "timestamp"):
            try:
                return float(raw_ts.timestamp())
            except Exception:
                return None
        if isinstance(raw_ts, str):
            text = raw_ts.strip()
            if not text:
                return None
            try:
                return float(text)
            except Exception:
                try:
                    return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
                except Exception:
                    return None
        return None

    def _source_bucket(raw_source: str) -> str:
        src = (raw_source or "").strip().lower()
        if "heuristic_v2" in src:
            return "heuristic_v2"
        if "heuristic" in src:
            return "heuristic"
        if "onnx" in src:
            return "onnx"
        if "reconcile" in src:
            return "exchange_reconcile"
        return "unknown"

    def _empty_perf() -> Dict[str, Any]:
        return {"n": 0, "wins": 0, "sum_net_pnl": 0.0, "avg_net_pnl": None, "win_rate": None}

    rolling_windows = [1, 6]
    rolling_perf: Dict[str, Any] = {}
    for hours in rolling_windows:
        cutoff = now - float(hours * 3600)
        by_source: Dict[str, Dict[str, Any]] = {}
        by_source_side: Dict[str, Dict[str, Dict[str, Any]]] = {}
        total = _empty_perf()

        for payload in close_order_events:
            event_ts = _to_epoch(payload.get("__event_ts")) or _to_epoch(payload.get("timestamp")) or _to_epoch(payload.get("ts"))
            if event_ts is None or event_ts < cutoff:
                continue
            identity = close_event_identity(payload)
            if not identity:
                continue
            side = normalize_position_side_from_close_fill(payload) or "unknown"
            raw_source = str(
                payload.get("prediction_source")
                or payload.get("source")
                or payload.get("p_hat_source")
                or payload.get("decision_source")
                or "unknown"
            )
            source = _source_bucket(raw_source)
            pnl = payload.get("net_pnl")
            if pnl is None:
                pnl = payload.get("realized_pnl")
            try:
                pnl_f = float(pnl)
            except (TypeError, ValueError):
                continue

            bucket = by_source.setdefault(source, _empty_perf())
            bucket["n"] += 1
            bucket["sum_net_pnl"] += pnl_f
            if pnl_f > 0:
                bucket["wins"] += 1

            side_bucket = by_source_side.setdefault(source, {}).setdefault(side, _empty_perf())
            side_bucket["n"] += 1
            side_bucket["sum_net_pnl"] += pnl_f
            if pnl_f > 0:
                side_bucket["wins"] += 1

            total["n"] += 1
            total["sum_net_pnl"] += pnl_f
            if pnl_f > 0:
                total["wins"] += 1

        for stats in list(by_source.values()) + [total]:
            n = int(stats.get("n") or 0)
            wins = int(stats.get("wins") or 0)
            sum_pnl = float(stats.get("sum_net_pnl") or 0.0)
            stats["sum_net_pnl"] = round(sum_pnl, 6)
            stats["avg_net_pnl"] = round(sum_pnl / n, 6) if n > 0 else None
            stats["win_rate"] = round(wins / n, 4) if n > 0 else None
        for source_stats in by_source_side.values():
            for stats in source_stats.values():
                n = int(stats.get("n") or 0)
                wins = int(stats.get("wins") or 0)
                sum_pnl = float(stats.get("sum_net_pnl") or 0.0)
                stats["sum_net_pnl"] = round(sum_pnl, 6)
                stats["avg_net_pnl"] = round(sum_pnl / n, 6) if n > 0 else None
                stats["win_rate"] = round(wins / n, 4) if n > 0 else None

        rolling_perf[f"{hours}h"] = {
            "window_hours": hours,
            "total": total,
            "by_source": by_source,
            "by_source_side": by_source_side,
        }
    prediction_summary["rolling_performance"] = rolling_perf

    # End-to-end p99 estimate: prefer latency snapshot; fallback to latest decision latency.
    latency_metrics = await get_key_json(f"quantgambit:{tenant_id}:{bot_id}:latency:metrics")
    latency_ops = (
        "tick_to_execution",
        "decision_worker",
        "feature_worker",
        "risk_worker",
        "execution_worker",
    )
    op_p99s: List[float] = []
    for op in latency_ops:
        op_stats = latency_metrics.get(op)
        if isinstance(op_stats, dict):
            try:
                p99 = float(op_stats.get("p99_ms", 0.0) or 0.0)
                if p99 > 0:
                    op_p99s.append(p99)
            except Exception:
                continue
    if latency_metrics.get("tick_to_execution") and isinstance(latency_metrics.get("tick_to_execution"), dict):
        e2e_latency = float(latency_metrics["tick_to_execution"].get("p99_ms", 0.0) or 0.0)
    elif op_p99s:
        # Approximate e2e by summing stage p99s when direct metric is unavailable.
        e2e_latency = float(sum(op_p99s))
    else:
        e2e_latency = float(decision_data.get("latency_ms", 0.0) or 0.0)
    
    return PipelineHealthResponse(
        layers=layers,
        overall_status=overall_status,
        tick_to_execution_p99_ms=e2e_latency,
        decisions_per_minute=round(decisions_per_minute, 1),
        fills_per_hour=round(fills_per_hour, 1),
        kill_switch_active=kill_switch_active,
        prediction=prediction_summary,
        timestamp=now,
    )


# =============================================================================
# Health Check
# =============================================================================

@router.get("/health")
async def quant_health():
    """Health check for quant API."""
    return {
        "status": "ok",
        "timestamp": datetime.utcnow().isoformat(),
        "components": {
            "kill_switch": "available",
            "config_bundles": "available",
            "reconciliation": "available",
            "latency_tracking": "available",
            "book_guardian": "available",
            "guard_events": "available",
            "correlation_guard": "available",
            "pipeline_health": "available",
        },
    }
