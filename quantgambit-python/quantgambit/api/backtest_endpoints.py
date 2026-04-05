"""Backtest API endpoints for research and backtesting functionality.

Feature: backtesting-api-integration
Requirements: R1.1, R1.2, R1.3, R2.1, R2.2, R5.5, R6.1

This module provides REST API endpoints for:
- Creating backtests (POST /api/research/backtests)
- Listing backtests (GET /api/research/backtests)
- Getting backtest details (GET /api/research/backtests/{run_id})
- Cancelling backtests (DELETE /api/research/backtests/{run_id})
- Exporting backtest results (GET /api/research/backtests/{run_id}/export)
- Listing available datasets (GET /api/research/datasets)
"""

from __future__ import annotations

import asyncio
import csv
import io
import json
import logging
import os
import shutil
import ssl
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, Body, Depends, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field

from quantgambit.api.errors import (
    APIError,
    ValidationError,
    InvalidDateFormatError,
    InvalidDateRangeError,
    MissingFieldError,
    InvalidFieldValueError,
    InvalidFormatError,
    NotFoundError,
    BacktestNotFoundError,
    WFORunNotFoundError,
    InvalidStatusTransitionError,
    DatabaseError,
    RedisError,
    ServerError,
    validate_required_field,
    validate_positive_number,
    validate_enum_value,
)

logger = logging.getLogger(__name__)

from quantgambit.backtesting.store import (
    BacktestStore,
    BacktestRunRecord,
    WFORunRecord,
)
from quantgambit.backtesting.job_queue import BacktestJobQueue, JobStatus
from quantgambit.backtesting.dataset_scanner import DatasetScanner, ScanConfig


_MODEL_TRAINING_JOBS: dict[str, dict[str, Any]] = {}
_MODEL_TRAINING_JOBS_LOADED = False


def _host_looks_remote_managed(host: Any) -> bool:
    host_str = str(host or "localhost").strip().lower()
    return (
        host_str.endswith(".rds.amazonaws.com")
        or host_str.endswith(".amazonaws.com")
        or "neon.tech" in host_str
        or "supabase.co" in host_str
        or "render.com" in host_str
    )


def _should_enable_pg_ssl(host: Any, explicit_value: Any = None) -> bool:
    explicit = str(explicit_value or "").strip().lower()
    if explicit in {"false", "0", "no", "disable", "off"}:
        return False
    if explicit in {"true", "1", "yes", "require", "on"}:
        return True
    return _host_looks_remote_managed(host)


def _timescale_connect_kwargs() -> dict[str, Any]:
    host = os.getenv("TIMESCALE_HOST", os.getenv("BOT_DB_HOST", "localhost"))
    port = int(str(os.getenv("TIMESCALE_PORT", os.getenv("BOT_DB_PORT", "5433"))))
    database = os.getenv("TIMESCALE_DB", os.getenv("BOT_DB_NAME", "quantgambit_bot"))
    user = os.getenv("TIMESCALE_USER", os.getenv("BOT_DB_USER", "quantgambit"))
    password = os.getenv("TIMESCALE_PASSWORD", os.getenv("BOT_DB_PASSWORD", ""))
    ssl_env = (
        os.getenv("TIMESCALE_SSL")
        or os.getenv("BOT_DB_SSL")
        or os.getenv("DB_SSL")
        or ""
    )
    ssl_ctx = None
    if _should_enable_pg_ssl(host, ssl_env):
        ssl_ctx = ssl.create_default_context()
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_NONE
    return {
        "host": str(host or "localhost"),
        "port": port,
        "database": database,
        "user": user,
        "password": password,
        "ssl": ssl_ctx,
    }


def _iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _model_training_jobs_path() -> Path:
    return _project_root() / "models" / "registry" / "model_training_jobs.json"


def _load_model_training_jobs_from_disk() -> None:
    global _MODEL_TRAINING_JOBS_LOADED
    if _MODEL_TRAINING_JOBS_LOADED:
        return
    path = _model_training_jobs_path()
    _MODEL_TRAINING_JOBS_LOADED = True
    if not path.exists():
        return
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            for key, value in payload.items():
                if isinstance(key, str) and isinstance(value, dict):
                    _MODEL_TRAINING_JOBS[key] = value
    except Exception:
        logger.warning("model_training_jobs_load_failed", exc_info=True)


def _persist_model_training_jobs_to_disk(max_jobs: int = 200) -> None:
    path = _model_training_jobs_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    jobs = sorted(
        _MODEL_TRAINING_JOBS.values(),
        key=lambda item: item.get("started_at") or "",
        reverse=True,
    )[:max_jobs]
    payload = {str(item.get("id")): item for item in jobs if isinstance(item, dict) and item.get("id")}
    try:
        path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    except Exception:
        logger.warning("model_training_jobs_persist_failed", exc_info=True)


def _artifact_ts_to_iso(ts: str) -> str:
    try:
        parsed = datetime.strptime(ts, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
        return parsed.strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        return _iso_now()


def _hydrate_model_training_jobs_from_artifacts(max_jobs: int = 50) -> None:
    registry_dir = _project_root() / "models" / "registry"
    if not registry_dir.exists():
        return

    artifact_index: dict[str, dict[str, Any]] = {}
    for path in registry_dir.glob("prediction_baseline_*.*"):
        if path.suffix not in {".json", ".onnx"}:
            continue
        stem = path.stem
        if not stem.startswith("prediction_baseline_"):
            continue
        ts = stem.removeprefix("prediction_baseline_")
        if not ts:
            continue
        item = artifact_index.setdefault(
            ts,
            {
                "id": f"artifact-{ts}",
                "status": "completed",
                "started_at": _artifact_ts_to_iso(ts),
                "finished_at": _artifact_ts_to_iso(ts),
                "label_source": "unknown",
                "stream": "features_stream",
                "tenant_id": None,
                "bot_id": None,
                "exit_code": 0,
                "promotion_status": None,
                "summary": {},
                "stdout_tail": [],
                "stderr_tail": [],
                "artifacts": [],
            },
        )
        item["artifacts"].append(
            {
                "name": path.name,
                "path": str(path.relative_to(_project_root())),
                "size": path.stat().st_size,
            }
        )

    if not artifact_index:
        return

    for _, entry in sorted(artifact_index.items(), key=lambda kv: kv[0], reverse=True)[:max_jobs]:
        _MODEL_TRAINING_JOBS.setdefault(entry["id"], entry)


def _pick_python_bin(project_root: Path) -> str:
    candidates = [
        project_root / ".venv" / "bin" / "python",
        project_root / "venv" / "bin" / "python",
        project_root / "venv311" / "bin" / "python",
        Path(sys.executable),
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return sys.executable


def _parse_training_summary(output_text: str) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for raw_line in (output_text or "").splitlines():
        line = raw_line.strip()
        if line.startswith("promotion_blocked:"):
            summary["promotion_status"] = "blocked"
            summary["promotion_reason"] = line.split(":", 1)[1].strip()
        elif line.startswith("promotion_check:"):
            summary["promotion_status"] = "passed"
            summary["promotion_reason"] = line.split(":", 1)[1].strip()
        elif line.startswith("metrics:"):
            # metrics:accuracy=0.123
            _, payload = line.split(":", 1)
            if "=" in payload:
                key, value = payload.split("=", 1)
                try:
                    summary[key.strip()] = float(value.strip())
                except ValueError:
                    summary[key.strip()] = value.strip()
        elif line.startswith("paired_check:"):
            # paired_check:candidate_f1=...,latest_f1=...,candidate_ev=...,latest_ev=...
            _, payload = line.split(":", 1)
            for item in payload.split(","):
                part = item.strip()
                if "=" not in part:
                    continue
                key, value = part.split("=", 1)
                key = key.strip()
                try:
                    summary[key] = float(value.strip())
                except ValueError:
                    summary[key] = value.strip()
        elif line.startswith("baseline_comparison:"):
            # baseline_comparison:f1_down=0.9(baseline=0.8)
            _, payload = line.split(":", 1)
            if "=" in payload:
                metric, rhs = payload.split("=", 1)
                metric = metric.strip()
                candidate_value_raw = rhs.split("(", 1)[0].strip()
                try:
                    summary[f"candidate_{metric}"] = float(candidate_value_raw)
                except ValueError:
                    summary[f"candidate_{metric}"] = candidate_value_raw
                if "(baseline=" in rhs:
                    baseline_raw = rhs.split("(baseline=", 1)[1].rstrip(")").strip()
                    try:
                        summary[f"baseline_{metric}"] = float(baseline_raw)
                    except ValueError:
                        summary[f"baseline_{metric}"] = baseline_raw
        elif line.startswith("warn:"):
            warnings = summary.setdefault("warnings", [])
            if isinstance(warnings, list):
                warnings.append(line.removeprefix("warn:").strip())
    return summary


def _run_training_subprocess(cmd: list[str], cwd: str) -> tuple[int, str, str]:
    proc = subprocess.Popen(
        cmd,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    stdout, stderr = proc.communicate()
    return int(proc.returncode or 0), stdout or "", stderr or ""


def _latest_pointer(registry_dir: Path) -> dict[str, Any]:
    pointer_path = registry_dir / "latest_pointer.json"
    if pointer_path.exists():
        try:
            return json.loads(pointer_path.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _select_promotable_artifacts(job: dict[str, Any]) -> tuple[Path, Path]:
    artifacts = job.get("artifacts") or []
    rows = []
    for item in artifacts:
        path = item.get("path")
        name = item.get("name")
        if not path or not name:
            continue
        if not name.startswith("prediction_baseline_"):
            continue
        if not (name.endswith(".json") or name.endswith(".onnx")):
            continue
        try:
            rows.append((Path(path), name, item.get("updated_at") or ""))
        except Exception:
            continue
    json_candidates = sorted(
        [row for row in rows if row[1].endswith(".json")],
        key=lambda r: r[2],
        reverse=True,
    )
    for config_path, config_name, _updated_at in json_candidates:
        stem = config_name.rsplit(".", 1)[0]
        onnx_name = f"{stem}.onnx"
        onnx_match = next((row for row in rows if row[1] == onnx_name), None)
        if onnx_match and config_path.exists() and onnx_match[0].exists():
            return onnx_match[0], config_path
    raise ValueError("No promotable prediction_baseline artifacts found for this job.")


# ============================================================================
# Error Handling Utilities
# ============================================================================

def _validate_date(date_str: str, field_name: str) -> datetime:
    """Validate and parse a date string.
    
    Args:
        date_str: Date string to parse
        field_name: Name of the field for error messages
        
    Returns:
        Parsed datetime object
        
    Raises:
        InvalidDateFormatError: If the date format is invalid
    """
    formats = [
        "%Y-%m-%d",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M",  # datetime-local input format (no seconds)
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",  # datetime without seconds
    ]
    for fmt in formats:
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue
    raise InvalidDateFormatError(field_name, date_str)


def _validate_date_range(start_date: datetime, end_date: datetime, start_str: str, end_str: str) -> None:
    """Validate that start_date is before end_date.
    
    Args:
        start_date: Start datetime
        end_date: End datetime
        start_str: Original start date string for error message
        end_str: Original end date string for error message
        
    Raises:
        InvalidDateRangeError: If start_date >= end_date
    """
    if start_date >= end_date:
        raise InvalidDateRangeError(start_str, end_str)


def _normalize_symbol_candidates(symbol: str) -> list[str]:
    raw = (symbol or "").strip().upper()
    if not raw:
        return []
    compact = "".join(ch for ch in raw if ch.isalnum())
    canonical = str(to_storage_symbol(raw) or "").upper()
    candidates: list[str] = []
    for value in (raw, compact, canonical):
        if value and value not in candidates:
            candidates.append(value)
    return candidates


async def _preflight_validate_backtest_data(
    *,
    timescale_pool: Any,
    symbol: str,
    start_dt: datetime,
    end_dt: datetime,
    require_decision_events: bool = True,
) -> None:
    """
    Fail-fast preflight check for backtest jobs to avoid hours-long "running" states
    when requested data range has no source data.
    """
    if timescale_pool is None:
        return

    symbol_candidates = _normalize_symbol_candidates(symbol)
    if not symbol_candidates:
        raise ValidationError(
            message="symbol is required",
            details={"field": "symbol"},
        )

    # Align to UTC for consistent DB comparisons.
    start_utc = start_dt if start_dt.tzinfo else start_dt.replace(tzinfo=timezone.utc)
    end_utc = end_dt if end_dt.tzinfo else end_dt.replace(tzinfo=timezone.utc)

    async with timescale_pool.acquire() as conn:
        decision_count = int(
            await conn.fetchval(
                """
                SELECT COUNT(*)::bigint
                FROM decision_events
                WHERE symbol = ANY($1::text[])
                  AND ts >= $2::timestamptz
                  AND ts < $3::timestamptz
                """,
                symbol_candidates,
                start_utc,
                end_utc,
            )
            or 0
        )
        candle_count = int(
            await conn.fetchval(
                """
                SELECT COUNT(*)::bigint
                FROM market_candles
                WHERE symbol = ANY($1::text[])
                  AND ts >= $2::timestamptz
                  AND ts < $3::timestamptz
                """,
                symbol_candidates,
                start_utc,
                end_utc,
            )
            or 0
        )
        availability = await conn.fetchrow(
            """
            SELECT
              (SELECT MIN(ts) FROM decision_events WHERE symbol = ANY($1::text[])) AS decision_min_ts,
              (SELECT MAX(ts) FROM decision_events WHERE symbol = ANY($1::text[])) AS decision_max_ts,
              (SELECT MIN(ts) FROM market_candles WHERE symbol = ANY($1::text[])) AS candle_min_ts,
              (SELECT MAX(ts) FROM market_candles WHERE symbol = ANY($1::text[])) AS candle_max_ts
            """,
            symbol_candidates,
        )

    needs_decisions = bool(require_decision_events)
    missing_decisions = needs_decisions and decision_count <= 0
    missing_candles = candle_count <= 0
    if missing_decisions or missing_candles:
        details = {
            "symbol_requested": symbol,
            "symbol_candidates": symbol_candidates,
            "requested_start": start_utc.isoformat(),
            "requested_end": end_utc.isoformat(),
            "decision_events_count": decision_count,
            "market_candles_count": candle_count,
            "decision_events_range": {
                "start": availability["decision_min_ts"].isoformat() if availability and availability["decision_min_ts"] else None,
                "end": availability["decision_max_ts"].isoformat() if availability and availability["decision_max_ts"] else None,
            },
            "market_candles_range": {
                "start": availability["candle_min_ts"].isoformat() if availability and availability["candle_min_ts"] else None,
                "end": availability["candle_max_ts"].isoformat() if availability and availability["candle_max_ts"] else None,
            },
            "require_decision_events": needs_decisions,
        }
        raise ValidationError(
            message=(
                "No backtest source data found in requested time range. "
                "Choose a range with decision events and market candles or run backfill first."
            ),
            details=details,
        )


async def _backtest_preflight_report(
    *,
    timescale_pool: Any,
    symbol: str,
    start_dt: datetime,
    end_dt: datetime,
    require_decision_events: bool = True,
) -> dict[str, Any]:
    symbol_candidates = _normalize_symbol_candidates(symbol)
    start_utc = start_dt if start_dt.tzinfo else start_dt.replace(tzinfo=timezone.utc)
    end_utc = end_dt if end_dt.tzinfo else end_dt.replace(tzinfo=timezone.utc)

    if timescale_pool is None:
        return {
            "ok": False,
            "symbol_requested": symbol,
            "symbol_candidates": symbol_candidates,
            "requested_start": start_utc.isoformat(),
            "requested_end": end_utc.isoformat(),
            "decision_events_count": 0,
            "market_candles_count": 0,
            "decision_events_range": {"start": None, "end": None},
            "market_candles_range": {"start": None, "end": None},
            "require_decision_events": bool(require_decision_events),
            "message": "timescale_not_configured",
        }

    async with timescale_pool.acquire() as conn:
        decision_count = int(
            await conn.fetchval(
                """
                SELECT COUNT(*)::bigint
                FROM decision_events
                WHERE symbol = ANY($1::text[])
                  AND ts >= $2::timestamptz
                  AND ts < $3::timestamptz
                """,
                symbol_candidates,
                start_utc,
                end_utc,
            )
            or 0
        )
        candle_count = int(
            await conn.fetchval(
                """
                SELECT COUNT(*)::bigint
                FROM market_candles
                WHERE symbol = ANY($1::text[])
                  AND ts >= $2::timestamptz
                  AND ts < $3::timestamptz
                """,
                symbol_candidates,
                start_utc,
                end_utc,
            )
            or 0
        )
        availability = await conn.fetchrow(
            """
            SELECT
              (SELECT MIN(ts) FROM decision_events WHERE symbol = ANY($1::text[])) AS decision_min_ts,
              (SELECT MAX(ts) FROM decision_events WHERE symbol = ANY($1::text[])) AS decision_max_ts,
              (SELECT MIN(ts) FROM market_candles WHERE symbol = ANY($1::text[])) AS candle_min_ts,
              (SELECT MAX(ts) FROM market_candles WHERE symbol = ANY($1::text[])) AS candle_max_ts
            """,
            symbol_candidates,
        )

    needs_decisions = bool(require_decision_events)
    missing_decisions = needs_decisions and decision_count <= 0
    missing_candles = candle_count <= 0
    ok = not (missing_decisions or missing_candles)
    return {
        "ok": ok,
        "symbol_requested": symbol,
        "symbol_candidates": symbol_candidates,
        "requested_start": start_utc.isoformat(),
        "requested_end": end_utc.isoformat(),
        "decision_events_count": decision_count,
        "market_candles_count": candle_count,
        "decision_events_range": {
            "start": availability["decision_min_ts"].isoformat() if availability and availability["decision_min_ts"] else None,
            "end": availability["decision_max_ts"].isoformat() if availability and availability["decision_max_ts"] else None,
        },
        "market_candles_range": {
            "start": availability["candle_min_ts"].isoformat() if availability and availability["candle_min_ts"] else None,
            "end": availability["candle_max_ts"].isoformat() if availability and availability["candle_max_ts"] else None,
        },
        "require_decision_events": needs_decisions,
        "message": "ok" if ok else "no_source_data_in_requested_range",
    }


# ============================================================================
# Request/Response Models
# ============================================================================

class CreateBacktestRequest(BaseModel):
    """Request model for creating a new backtest."""
    name: Optional[str] = Field(None, description="Optional name for the backtest")
    strategy_id: Optional[str] = Field(None, description="Strategy identifier (legacy)")
    profile_id: Optional[str] = Field(None, description="Profile identifier (recommended)")
    symbol: str = Field(..., description="Trading symbol (e.g., BTC-USDT-SWAP)")
    start_date: str = Field(..., description="Start date in ISO format (YYYY-MM-DD)")
    end_date: str = Field(..., description="End date in ISO format (YYYY-MM-DD)")
    initial_capital: float = Field(10000.0, description="Initial capital for the backtest")
    force_run: bool = Field(False, description="If True, bypass data validation thresholds")
    config: Dict[str, Any] = Field(default_factory=dict, description="Additional configuration")
    
    def get_strategy_or_profile(self) -> tuple[Optional[str], Optional[str]]:
        """Return (strategy_id, profile_id). At least one must be set."""
        return (self.strategy_id, self.profile_id)


class RerunBacktestRequest(BaseModel):
    """Request model for rerunning a backtest."""

    force_run: bool = Field(False, description="If True, bypass data validation thresholds")


class PromoteBacktestRequest(BaseModel):
    """Request model for promoting a backtest config to bot config versions."""

    bot_id: Optional[str] = Field(None, description="Target bot profile ID")
    notes: Optional[str] = Field(None, description="Optional note on promoted config version")
    activate: bool = Field(False, description="Whether to activate promoted version immediately")
    status: str = Field("draft", description="Version status")


class PromoteBacktestResponse(BaseModel):
    """Response model for promoted backtest config."""

    success: bool
    run_id: str
    bot_id: str
    version_id: str
    version_number: int
    activated: bool


class StartModelTrainingRequest(BaseModel):
    """Request for starting an ONNX retraining job."""

    redis_url: Optional[str] = Field(None, description="Redis URL override")
    tenant_id: Optional[str] = Field(None, description="Tenant ID for namespaced stream")
    bot_id: Optional[str] = Field(None, description="Bot ID for namespaced stream")
    stream: str = Field("events:features", description="Base feature stream name")
    label_source: str = Field(
        "future_return",
        description="Label source (future_return|tp_sl|policy_replay)",
    )
    limit: int = Field(100000, ge=1000, le=1000000, description="Max snapshots to read")
    hours: Optional[float] = Field(24.0, ge=0.25, le=240.0, description="Training window in hours")
    walk_forward_folds: int = Field(3, ge=1, le=10, description="Walk-forward folds")
    drift_check: bool = Field(False, description="Enable feature drift check")
    allow_regression: bool = Field(False, description="Allow regression promotion")
    min_directional_f1: float = Field(0.25, ge=0.0, le=1.0)
    min_ev_after_costs: float = Field(0.0, ge=-10.0, le=10.0)
    min_directional_f1_delta: float = Field(0.0, ge=-1.0, le=1.0)
    min_ev_delta: float = Field(0.0, ge=-10.0, le=10.0)
    keep_dataset: bool = Field(True, description="Keep timestamped dataset artifact")
    # v4 training pipeline params
    horizon_sec: float = Field(120.0, ge=10.0, le=600.0, description="Label horizon in seconds")
    tp_bps: float = Field(8.0, ge=1.0, le=50.0, description="Take-profit barrier in bps")
    sl_bps: float = Field(8.0, ge=1.0, le=50.0, description="Stop-loss barrier in bps")
    use_v4_pipeline: bool = Field(True, description="Use v4 trade-record labeling pipeline")


class ModelTrainingJobSummary(BaseModel):
    id: str
    status: str
    started_at: str
    finished_at: Optional[str] = None
    label_source: str
    stream: str
    tenant_id: Optional[str] = None
    bot_id: Optional[str] = None
    exit_code: Optional[int] = None
    promotion_status: Optional[str] = None


class StartModelTrainingResponse(BaseModel):
    success: bool
    job: ModelTrainingJobSummary


class PromoteModelTrainingJobRequest(BaseModel):
    notes: Optional[str] = Field(None, description="Optional promotion notes.")


class PromoteModelTrainingJobResponse(BaseModel):
    success: bool
    job_id: str
    source_model_file: str
    source_config_file: str
    latest_model_path: str
    latest_config_path: str


class ActiveModelInfoResponse(BaseModel):
    model_file: Optional[str] = None
    config_file: Optional[str] = None
    promoted_at: Optional[str] = None
    promoted_from_job_id: Optional[str] = None
    source_model_file: Optional[str] = None
    source_config_file: Optional[str] = None
    pointer_updated_at: Optional[str] = None

class CompareLiveRequest(BaseModel):
    """Request model for comparing backtest with live metrics.

    Feature: trading-pipeline-integration
    **Validates: Requirements 9.3**
    """

    live_start_date: Optional[str] = Field(
        None, description="Start date for live metrics (defaults to backtest start)"
    )
    live_end_date: Optional[str] = Field(
        None, description="End date for live metrics (defaults to backtest end)"
    )


class BackfillRequest(BaseModel):
    """Request model for data backfill."""

    symbol: str = Field(..., description="Trading symbol (e.g., BTCUSDT)")
    exchange: str = Field("bybit", description="Exchange name (bybit, binance, okx)")
    start_date: str = Field(..., description="Start date in ISO format (YYYY-MM-DD)")
    end_date: str = Field(..., description="End date in ISO format (YYYY-MM-DD)")
    timeframe: str = Field("5m", description="Candle timeframe (1m, 5m, 15m, 1h, etc.)")


class GapBackfillRequest(BaseModel):
    """Request model for backfilling a specific gap."""

    gap_id: str = Field(..., description="Gap ID from data quality")
    symbol: str = Field(..., description="Trading symbol")
    exchange: str = Field("bybit", description="Exchange name")
    start_time: str = Field(..., description="Gap start time")
    end_time: str = Field(..., description="Gap end time")
    timeframe: str = Field("5m", description="Candle timeframe")


class CreateBacktestResponse(BaseModel):
    """Response model for backtest creation."""
    run_id: str
    status: str
    message: str


class BacktestPreflightResponse(BaseModel):
    ok: bool
    symbol_requested: str
    symbol_candidates: list[str]
    requested_start: str
    requested_end: str
    decision_events_count: int
    market_candles_count: int
    decision_events_range: dict[str, Optional[str]]
    market_candles_range: dict[str, Optional[str]]
    require_decision_events: bool
    message: str


class BacktestResults(BaseModel):
    """Results/metrics for a backtest run - used in list view."""
    return_pct: Optional[float] = Field(None, alias="total_return_pct")
    total_return_pct: Optional[float] = None
    max_drawdown_pct: Optional[float] = None
    sharpe_ratio: Optional[float] = None
    sortino_ratio: Optional[float] = None
    profit_factor: Optional[float] = None
    win_rate: Optional[float] = None
    total_trades: Optional[int] = None
    trades_per_day: Optional[float] = None
    expectancy: Optional[float] = None  # avg_trade_pnl
    fee_drag_pct: Optional[float] = None
    slippage_drag_pct: Optional[float] = None
    realized_pnl: Optional[float] = None
    total_fees: Optional[float] = None
    gross_profit: Optional[float] = None
    gross_loss: Optional[float] = None
    avg_win: Optional[float] = None
    avg_loss: Optional[float] = None
    largest_win: Optional[float] = None
    largest_loss: Optional[float] = None
    winning_trades: Optional[int] = None
    losing_trades: Optional[int] = None
    
    model_config = ConfigDict(populate_by_name=True)


class BacktestSummary(BaseModel):
    """Summary model for backtest list."""
    id: str
    name: Optional[str] = None
    strategy_id: Optional[str] = None  # For frontend compatibility
    profile_id: Optional[str] = None   # Alias for strategy_id
    strategy: Optional[str] = None     # Legacy field
    symbol: Optional[str] = None
    exchange: Optional[str] = None
    timeframe: Optional[str] = None
    status: str
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    initial_capital: Optional[float] = None
    slippage_bps: Optional[float] = None
    created_at: Optional[str] = None
    completed_at: Optional[str] = None
    results: Optional[BacktestResults] = None  # Nested results object for frontend
    # Legacy flat fields for backward compatibility
    realized_pnl: Optional[float] = None
    total_return_pct: Optional[float] = None


class BacktestListResponse(BaseModel):
    """Response model for backtest list."""
    backtests: List[BacktestSummary]
    total: int


class BacktestMetrics(BaseModel):
    """Metrics for a backtest run."""
    realized_pnl: Optional[float] = None
    total_fees: Optional[float] = None
    total_trades: Optional[int] = None
    win_rate: Optional[float] = None
    max_drawdown_pct: Optional[float] = None
    avg_slippage_bps: Optional[float] = None
    total_return_pct: Optional[float] = None
    profit_factor: Optional[float] = None
    avg_trade_pnl: Optional[float] = None
    sharpe_ratio: Optional[float] = None
    sortino_ratio: Optional[float] = None
    trades_per_day: Optional[float] = None
    fee_drag_pct: Optional[float] = None
    slippage_drag_pct: Optional[float] = None
    gross_profit: Optional[float] = None
    gross_loss: Optional[float] = None
    avg_win: Optional[float] = None
    avg_loss: Optional[float] = None
    largest_win: Optional[float] = None
    largest_loss: Optional[float] = None
    winning_trades: Optional[int] = None
    losing_trades: Optional[int] = None


class EquityPoint(BaseModel):
    """Single point on the equity curve."""
    ts: str
    equity: float
    realized_pnl: float
    open_positions: int


class Trade(BaseModel):
    """Trade record."""
    ts: str
    symbol: str
    side: str
    size: float
    entry_price: float
    exit_price: float
    pnl: float
    total_fees: float


class DecisionSnapshot(BaseModel):
    """Decision snapshot record."""
    ts: str
    symbol: str
    decision: str
    rejection_reason: Optional[str] = None
    profile_id: Optional[str] = None


class BacktestRunDetail(BaseModel):
    """Detailed run metadata."""
    id: str
    name: Optional[str] = None
    strategy_id: Optional[str] = None
    profile_id: Optional[str] = None  # Alias for strategy_id
    symbol: Optional[str] = None
    exchange: Optional[str] = None
    timeframe: Optional[str] = None
    status: str
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    initial_capital: Optional[float] = None
    slippage_bps: Optional[float] = None
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    completed_at: Optional[str] = None  # Alias for finished_at
    error_message: Optional[str] = None
    config: Dict[str, Any] = Field(default_factory=dict)
    # Metrics fields for frontend compatibility
    total_return_percent: Optional[float] = None
    sharpe_ratio: Optional[float] = None
    max_drawdown_percent: Optional[float] = None
    win_rate: Optional[float] = None
    total_trades: Optional[int] = None
    profit_factor: Optional[float] = None


class EquityCurvePointResponse(BaseModel):
    """Equity curve point for frontend compatibility."""
    time: str
    value: float
    timestamp: Optional[str] = None  # Alias for time
    equity: Optional[float] = None   # Alias for value
    drawdown: Optional[float] = None


class TradeResponse(BaseModel):
    """Trade record for frontend compatibility."""
    id: Optional[str] = None
    ts: Optional[str] = None
    entry_time: Optional[str] = None
    exit_time: Optional[str] = None
    symbol: str
    side: str
    direction: Optional[str] = None  # Alias for side
    size: float
    quantity: Optional[float] = None  # Alias for size
    entry_price: float
    exit_price: float
    entry: Optional[float] = None    # Alias for entry_price
    exit: Optional[float] = None     # Alias for exit_price
    pnl: float
    pnl_pct: Optional[float] = None
    realized_pnl: Optional[float] = None  # Alias for pnl
    total_fees: float
    exit_reason: Optional[str] = None


class RejectionBreakdownResponse(BaseModel):
    """Breakdown of rejection reasons by category.
    
    Feature: backtest-diagnostics
    **Validates: Requirements 1.2, 2.1**
    """
    spread_too_wide: int = Field(0, description="Rejections due to spread being too wide")
    depth_too_thin: int = Field(0, description="Rejections due to orderbook depth being too thin")
    snapshot_stale: int = Field(0, description="Rejections due to stale snapshot data")
    vol_shock: int = Field(0, description="Rejections due to volatility shock")


class ExecutionDiagnosticsResponse(BaseModel):
    """Execution diagnostics for API response.
    
    Feature: backtest-diagnostics
    **Validates: Requirements 2.1, 2.2**
    
    Contains detailed diagnostics about backtest execution including:
    - Snapshot processing statistics
    - Global gate rejection breakdown
    - Signal pipeline statistics
    - Human-readable summary and suggestions
    """
    # Snapshot processing
    total_snapshots: int = Field(..., description="Total number of snapshots in the date range")
    snapshots_processed: int = Field(..., description="Number of snapshots successfully processed")
    snapshots_skipped: int = Field(..., description="Number of snapshots skipped (missing data)")
    
    # Global gate rejections (safety filters)
    global_gate_rejections: int = Field(..., description="Total number of global gate rejections")
    rejection_breakdown: RejectionBreakdownResponse = Field(
        default_factory=RejectionBreakdownResponse,
        description="Breakdown of rejections by reason"
    )
    
    # Profile and signal stats
    profiles_selected: int = Field(..., description="Number of times a profile was selected")
    signals_generated: int = Field(..., description="Number of entry signals generated")
    cooldown_rejections: int = Field(..., description="Number of signals blocked by cooldown")
    
    # Derived summary
    summary: str = Field(..., description="Human-readable explanation of the backtest outcome")
    primary_issue: Optional[str] = Field(None, description="Main reason for no trades (if applicable)")
    suggestions: List[str] = Field(default_factory=list, description="Actionable recommendations")


class BacktestDetailResponse(BaseModel):
    """Response model for backtest detail.
    
    Feature: backtest-diagnostics
    **Validates: Requirements 2.1, 2.4**
    """
    # Frontend expects 'backtest' not 'run'
    backtest: BacktestRunDetail
    run: Optional[BacktestRunDetail] = None  # Legacy field
    metrics: Optional[BacktestMetrics] = None
    # Frontend expects 'equityCurve' not 'equity_curve'
    equityCurve: List[EquityCurvePointResponse] = Field(default_factory=list)
    equity_curve: Optional[List[EquityPoint]] = None  # Legacy field
    trades: List[TradeResponse] = Field(default_factory=list)
    decisions: List[DecisionSnapshot] = Field(default_factory=list)
    # Execution diagnostics for understanding backtest behavior
    execution_diagnostics: Optional[ExecutionDiagnosticsResponse] = Field(
        None, 
        description="Detailed diagnostics about backtest execution (available for backtests run after this feature)"
    )


class CancelBacktestResponse(BaseModel):
    """Response model for backtest cancellation."""
    success: bool
    message: str
    run_id: str
    status: str


class DatasetInfo(BaseModel):
    """Information about an available dataset.
    
    **Validates: Requirements R2.1, R2.2**
    """
    symbol: str = Field(..., description="Trading symbol (e.g., BTC-USDT-SWAP)")
    exchange: str = Field(..., description="Exchange name (e.g., OKX)")
    earliest_date: str = Field(..., description="Earliest available date in ISO format")
    latest_date: str = Field(..., description="Latest available date in ISO format")
    candle_count: int = Field(..., description="Number of data points available")
    gaps: int = Field(..., description="Number of detected data gaps")
    gap_dates: List[str] = Field(default_factory=list, description="Dates where gaps were detected")
    completeness_pct: float = Field(..., description="Data completeness percentage (0-100)")
    last_updated: str = Field(..., description="Last update timestamp in ISO format")


class DatasetListResponse(BaseModel):
    """Response model for dataset list.
    
    **Validates: Requirements R2.1, R2.2**
    """
    datasets: List[DatasetInfo] = Field(default_factory=list, description="List of available datasets")
    total: int = Field(..., description="Total number of datasets")


# ============================================================================
# Data Validation Request/Response Models
# ============================================================================

class ValidateDataRequest(BaseModel):
    """Request model for data validation.
    
    Feature: backtest-data-validation
    **Validates: Requirements 6.1, 6.2**
    """
    symbol: str = Field(..., description="Trading symbol (e.g., BTC-USDT-SWAP)")
    start_date: str = Field(..., description="Start date in ISO format (YYYY-MM-DD)")
    end_date: str = Field(..., description="End date in ISO format (YYYY-MM-DD)")
    minimum_completeness_pct: float = Field(80.0, ge=0, le=100, description="Minimum completeness threshold")
    max_critical_gaps: int = Field(5, ge=0, description="Maximum critical gaps allowed")
    max_gap_duration_pct: float = Field(10.0, ge=0, le=100, description="Maximum gap duration as percentage")


class GapDetail(BaseModel):
    """Details about a detected data gap."""
    start_time: str = Field(..., description="Gap start time in ISO format")
    end_time: str = Field(..., description="Gap end time in ISO format")
    duration_minutes: float = Field(..., description="Gap duration in minutes")
    is_critical: bool = Field(..., description="Whether the gap is critical")
    session: str = Field(..., description="Trading session (asia, europe, us, overnight)")


class ValidateDataResponse(BaseModel):
    """Response model for data validation.
    
    Feature: backtest-data-validation
    **Validates: Requirements 6.1, 6.2, 6.5**
    """
    symbol: str = Field(..., description="Trading symbol")
    start_date: str = Field(..., description="Start date")
    end_date: str = Field(..., description="End date")
    
    # Overall metrics
    overall_completeness_pct: float = Field(..., description="Overall data completeness percentage")
    data_quality_grade: str = Field(..., description="Quality grade (A, B, C, D, F)")
    recommendation: str = Field(..., description="Recommendation: proceed, proceed_with_caution, insufficient_data")
    
    # Gap analysis
    total_gaps: int = Field(..., description="Total number of gaps detected")
    critical_gaps: int = Field(..., description="Number of critical gaps")
    gap_duration_pct: float = Field(..., description="Total gap duration as percentage of range")
    gap_details: List[GapDetail] = Field(default_factory=list, description="Details of detected gaps")
    
    # Per-source completeness
    decision_events_completeness: float = Field(..., description="Decision events completeness percentage")
    orderbook_events_completeness: float = Field(..., description="Orderbook events completeness percentage")
    candle_data_completeness: float = Field(..., description="Candle data completeness percentage")
    
    # Validation result
    passes_threshold: bool = Field(..., description="Whether validation passed thresholds")
    threshold_overridden: bool = Field(False, description="Whether threshold was overridden by force_run")
    warnings: List[str] = Field(default_factory=list, description="Warning messages")
    errors: List[str] = Field(default_factory=list, description="Error messages")


# ============================================================================
# WFO (Walk-Forward Optimization) Request/Response Models
# ============================================================================

class WFOConfig(BaseModel):
    """Configuration for walk-forward optimization.
    
    **Validates: Requirements R3.1**
    """
    in_sample_days: int = Field(..., ge=1, description="Number of days for in-sample period")
    out_sample_days: int = Field(..., ge=1, description="Number of days for out-of-sample period")
    periods: int = Field(..., ge=1, description="Number of WFO periods to run")
    objective: str = Field("sharpe", description="Optimization objective: sharpe, sortino, profit_factor")


class CreateWFORequest(BaseModel):
    """Request model for creating a new WFO run.
    
    **Validates: Requirements R3.1**
    """
    profile_id: str = Field(..., description="Profile identifier for the strategy")
    symbol: str = Field(..., description="Trading symbol (e.g., BTC-USDT-SWAP)")
    config: WFOConfig = Field(..., description="WFO configuration")


class CreateWFOResponse(BaseModel):
    """Response model for WFO creation.
    
    **Validates: Requirements R3.1**
    """
    run_id: str
    status: str
    message: str


class WFOPeriodResult(BaseModel):
    """Results for a single WFO period."""
    period: int = Field(..., description="Period number (1-indexed)")
    in_sample_start: str = Field(..., description="In-sample start date")
    in_sample_end: str = Field(..., description="In-sample end date")
    out_sample_start: str = Field(..., description="Out-of-sample start date")
    out_sample_end: str = Field(..., description="Out-of-sample end date")
    in_sample_sharpe: Optional[float] = Field(None, description="In-sample Sharpe ratio")
    out_sample_sharpe: Optional[float] = Field(None, description="Out-of-sample Sharpe ratio")
    in_sample_return_pct: Optional[float] = Field(None, description="In-sample return percentage")
    out_sample_return_pct: Optional[float] = Field(None, description="Out-of-sample return percentage")
    in_sample_max_dd_pct: Optional[float] = Field(None, description="In-sample max drawdown percentage")
    out_sample_max_dd_pct: Optional[float] = Field(None, description="Out-of-sample max drawdown percentage")
    optimized_params: Dict[str, Any] = Field(default_factory=dict, description="Optimized parameters for this period")


class WFOSummary(BaseModel):
    """Summary model for WFO run list.
    
    **Validates: Requirements R3.2**
    """
    id: str
    profile_id: Optional[str] = None
    symbol: Optional[str] = None
    status: str
    config: Optional[Dict[str, Any]] = None
    created_at: Optional[str] = None
    avg_is_sharpe: Optional[float] = Field(None, description="Average in-sample Sharpe ratio")
    avg_oos_sharpe: Optional[float] = Field(None, description="Average out-of-sample Sharpe ratio")
    degradation_pct: Optional[float] = Field(None, description="Performance degradation percentage")


class WFOListResponse(BaseModel):
    """Response model for WFO run list.
    
    **Validates: Requirements R3.2**
    """
    runs: List[WFOSummary] = Field(default_factory=list, description="List of WFO runs")
    total: int = Field(..., description="Total number of WFO runs")


class WFODetailResponse(BaseModel):
    """Response model for WFO run detail.
    
    **Validates: Requirements R3.3**
    """
    id: str
    profile_id: Optional[str] = None
    symbol: Optional[str] = None
    status: str
    config: Dict[str, Any] = Field(default_factory=dict)
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    created_at: Optional[str] = None
    periods: List[WFOPeriodResult] = Field(default_factory=list, description="Period-by-period results")
    summary: Dict[str, Any] = Field(default_factory=dict, description="Summary statistics")
    recommended_params: Dict[str, Any] = Field(default_factory=dict, description="Recommended parameters")
    error_message: Optional[str] = None


# ============================================================================
# Strategy Registry Request/Response Models
# ============================================================================

class StrategyParameter(BaseModel):
    """Parameter definition for a strategy.
    
    **Validates: Requirements R4.1**
    """
    name: str = Field(..., description="Parameter name")
    type: str = Field(..., description="Parameter type (float, int, bool, str)")
    description: str = Field(..., description="Parameter description")
    default: Optional[Any] = Field(None, description="Default value")
    min_value: Optional[float] = Field(None, description="Minimum value (for numeric types)")
    max_value: Optional[float] = Field(None, description="Maximum value (for numeric types)")


class StrategyInfo(BaseModel):
    """Information about an available strategy.
    
    **Validates: Requirements R4.1**
    """
    id: str = Field(..., description="Strategy identifier")
    name: str = Field(..., description="Human-readable strategy name")
    description: str = Field(..., description="Strategy description")
    parameters: List[StrategyParameter] = Field(default_factory=list, description="Strategy parameters")
    default_values: Dict[str, Any] = Field(default_factory=dict, description="Default parameter values")


class StrategyListResponse(BaseModel):
    """Response model for strategy list.
    
    **Validates: Requirements R4.1**
    """
    strategies: List[StrategyInfo] = Field(default_factory=list, description="List of available strategies")
    total: int = Field(..., description="Total number of strategies")


# ============================================================================
# Strategy Registry Data
# ============================================================================

# Hardcoded strategy registry with metadata for backtesting
# This provides strategy information without requiring the full deeptrader_core module
STRATEGY_REGISTRY: List[StrategyInfo] = [
    StrategyInfo(
        id="amt_value_area_rejection_scalp",
        name="AMT Value Area Rejection Scalp",
        description="Scalps rejections at value area boundaries using AMT (Auction Market Theory) principles. Enters when price tests VAH/VAL and shows rejection.",
        parameters=[
            StrategyParameter(name="risk_per_trade_pct", type="float", description="Risk per trade as percentage (decimal) of equity", default=0.005, min_value=0.001, max_value=0.02),
            StrategyParameter(name="stop_loss_pct", type="float", description="Stop loss percentage (decimal)", default=0.005, min_value=0.001, max_value=0.02),
            StrategyParameter(name="take_profit_pct", type="float", description="Take profit percentage (decimal)", default=0.008, min_value=0.001, max_value=0.03),
            StrategyParameter(name="min_rejection_strength", type="float", description="Minimum rejection strength to trigger entry", default=0.6, min_value=0.1, max_value=1.0),
        ],
        default_values={"risk_per_trade_pct": 0.005, "stop_loss_pct": 0.005, "take_profit_pct": 0.008, "min_rejection_strength": 0.6},
    ),
    StrategyInfo(
        id="poc_magnet_scalp",
        name="POC Magnet Scalp",
        description="Trades price attraction to Point of Control (POC). Enters when price is extended from POC and shows signs of reverting.",
        parameters=[
            StrategyParameter(name="risk_per_trade_pct", type="float", description="Risk per trade as percentage (decimal) of equity", default=0.005, min_value=0.001, max_value=0.02),
            StrategyParameter(name="min_distance_from_poc_pct", type="float", description="Minimum distance from POC to trigger entry (decimal)", default=0.003, min_value=0.001, max_value=0.02),
            StrategyParameter(name="stop_loss_pct", type="float", description="Stop loss percentage (decimal)", default=0.005, min_value=0.001, max_value=0.02),
        ],
        default_values={"risk_per_trade_pct": 0.005, "min_distance_from_poc_pct": 0.003, "stop_loss_pct": 0.005},
    ),
    StrategyInfo(
        id="breakout_scalp",
        name="Breakout Scalp",
        description="Trades breakouts from consolidation ranges. Enters on confirmed breakout with volume confirmation.",
        parameters=[
            StrategyParameter(name="risk_per_trade_pct", type="float", description="Risk per trade as percentage (decimal) of equity", default=0.006, min_value=0.001, max_value=0.02),
            StrategyParameter(name="breakout_threshold_pct", type="float", description="Minimum breakout percentage (decimal)", default=0.002, min_value=0.0005, max_value=0.01),
            StrategyParameter(name="volume_multiplier", type="float", description="Required volume multiplier for confirmation", default=1.5, min_value=1.0, max_value=5.0),
        ],
        default_values={"risk_per_trade_pct": 0.006, "breakout_threshold_pct": 0.002, "volume_multiplier": 1.5},
    ),
    StrategyInfo(
        id="mean_reversion_fade",
        name="Mean Reversion Fade",
        description="Fades overextensions in ranging markets by trading back towards the Point of Control. Best in flat, low volatility conditions.",
        parameters=[
            StrategyParameter(name="risk_per_trade_pct", type="float", description="Risk per trade as percentage (decimal) of equity", default=0.006, min_value=0.001, max_value=0.02),
            StrategyParameter(name="min_distance_from_poc_pct", type="float", description="Minimum distance from POC to trigger entry (decimal)", default=0.003, min_value=0.001, max_value=0.02),
            StrategyParameter(name="stop_loss_pct", type="float", description="Stop loss percentage (decimal)", default=0.012, min_value=0.001, max_value=0.03),
            StrategyParameter(name="max_atr_ratio", type="float", description="Maximum ATR ratio (volatility filter)", default=1.0, min_value=0.5, max_value=2.0),
        ],
        default_values={"risk_per_trade_pct": 0.006, "min_distance_from_poc_pct": 0.003, "stop_loss_pct": 0.012, "max_atr_ratio": 1.0},
    ),
    StrategyInfo(
        id="trend_pullback",
        name="Trend Pullback",
        description="Enters on pullbacks within established trends. Waits for retracement to support/resistance before entering in trend direction.",
        parameters=[
            StrategyParameter(name="risk_per_trade_pct", type="float", description="Risk per trade as percentage (decimal) of equity", default=0.007, min_value=0.001, max_value=0.02),
            StrategyParameter(name="pullback_depth_pct", type="float", description="Required pullback depth percentage (decimal)", default=0.003, min_value=0.001, max_value=0.01),
            StrategyParameter(name="trend_strength_min", type="float", description="Minimum trend strength to qualify", default=0.5, min_value=0.1, max_value=1.0),
        ],
        default_values={"risk_per_trade_pct": 0.007, "pullback_depth_pct": 0.003, "trend_strength_min": 0.5},
    ),
    StrategyInfo(
        id="opening_range_breakout",
        name="Opening Range Breakout",
        description="Trades breakouts from the opening range. Defines range in first N minutes and trades breakout with momentum.",
        parameters=[
            StrategyParameter(name="risk_per_trade_pct", type="float", description="Risk per trade as percentage (decimal) of equity", default=0.008, min_value=0.001, max_value=0.02),
            StrategyParameter(name="range_minutes", type="int", description="Minutes to define opening range", default=15, min_value=5, max_value=60),
            StrategyParameter(name="breakout_buffer_pct", type="float", description="Buffer above/below range for entry (decimal)", default=0.001, min_value=0, max_value=0.005),
        ],
        default_values={"risk_per_trade_pct": 0.008, "range_minutes": 15, "breakout_buffer_pct": 0.001},
    ),
    StrategyInfo(
        id="asia_range_scalp",
        name="Asia Range Scalp",
        description="Scalps within the Asian session range. Trades mean reversion within the typically quieter Asian hours.",
        parameters=[
            StrategyParameter(name="risk_per_trade_pct", type="float", description="Risk per trade as percentage (decimal) of equity", default=0.004, min_value=0.001, max_value=0.02),
            StrategyParameter(name="range_buffer_pct", type="float", description="Buffer from range boundaries (decimal)", default=0.001, min_value=0, max_value=0.005),
        ],
        default_values={"risk_per_trade_pct": 0.004, "range_buffer_pct": 0.001},
    ),
    StrategyInfo(
        id="europe_open_vol",
        name="Europe Open Volatility",
        description="Trades the volatility expansion at European market open. Captures directional moves as liquidity increases.",
        parameters=[
            StrategyParameter(name="risk_per_trade_pct", type="float", description="Risk per trade as percentage (decimal) of equity", default=0.006, min_value=0.001, max_value=0.02),
            StrategyParameter(name="vol_expansion_threshold", type="float", description="Volatility expansion threshold", default=1.5, min_value=1.0, max_value=3.0),
        ],
        default_values={"risk_per_trade_pct": 0.006, "vol_expansion_threshold": 1.5},
    ),
    StrategyInfo(
        id="us_open_momentum",
        name="US Open Momentum",
        description="Trades momentum at US market open. Captures strong directional moves during high-volume US session start.",
        parameters=[
            StrategyParameter(name="risk_per_trade_pct", type="float", description="Risk per trade as percentage (decimal) of equity", default=0.007, min_value=0.001, max_value=0.02),
            StrategyParameter(name="momentum_threshold", type="float", description="Minimum momentum for entry", default=0.5, min_value=0.1, max_value=1.0),
        ],
        default_values={"risk_per_trade_pct": 0.007, "momentum_threshold": 0.5},
    ),
    StrategyInfo(
        id="overnight_thin",
        name="Overnight Thin",
        description="Trades during thin overnight liquidity. Uses wider stops and smaller size due to potential gaps.",
        parameters=[
            StrategyParameter(name="risk_per_trade_pct", type="float", description="Risk per trade as percentage (decimal) of equity", default=0.003, min_value=0.001, max_value=0.01),
            StrategyParameter(name="stop_loss_pct", type="float", description="Stop loss percentage (decimal) (wider for overnight)", default=0.015, min_value=0.005, max_value=0.03),
        ],
        default_values={"risk_per_trade_pct": 0.003, "stop_loss_pct": 0.015},
    ),
    StrategyInfo(
        id="high_vol_breakout",
        name="High Volatility Breakout",
        description="Trades breakouts during high volatility regimes. Uses momentum confirmation and wider stops.",
        parameters=[
            StrategyParameter(name="risk_per_trade_pct", type="float", description="Risk per trade as percentage (decimal) of equity", default=0.005, min_value=0.001, max_value=0.02),
            StrategyParameter(name="vol_threshold", type="float", description="Volatility threshold to activate", default=1.5, min_value=1.0, max_value=3.0),
            StrategyParameter(name="breakout_confirmation_bars", type="int", description="Bars to confirm breakout", default=2, min_value=1, max_value=5),
        ],
        default_values={"risk_per_trade_pct": 0.005, "vol_threshold": 1.5, "breakout_confirmation_bars": 2},
    ),
    StrategyInfo(
        id="low_vol_grind",
        name="Low Volatility Grind",
        description="Trades small moves during low volatility. Uses tight stops and targets small, consistent gains.",
        parameters=[
            StrategyParameter(name="risk_per_trade_pct", type="float", description="Risk per trade as percentage (decimal) of equity", default=0.003, min_value=0.001, max_value=0.01),
            StrategyParameter(name="target_pct", type="float", description="Target profit percentage (decimal)", default=0.002, min_value=0.0005, max_value=0.005),
            StrategyParameter(name="max_vol_ratio", type="float", description="Maximum volatility ratio to trade", default=0.8, min_value=0.3, max_value=1.0),
        ],
        default_values={"risk_per_trade_pct": 0.003, "target_pct": 0.002, "max_vol_ratio": 0.8},
    ),
    StrategyInfo(
        id="vol_expansion",
        name="Volatility Expansion",
        description="Trades volatility expansion from compression. Enters when volatility breaks out of low range.",
        parameters=[
            StrategyParameter(name="risk_per_trade_pct", type="float", description="Risk per trade as percentage (decimal) of equity", default=0.006, min_value=0.001, max_value=0.02),
            StrategyParameter(name="compression_threshold", type="float", description="Volatility compression threshold", default=0.5, min_value=0.2, max_value=0.8),
            StrategyParameter(name="expansion_multiplier", type="float", description="Required expansion multiplier", default=2.0, min_value=1.5, max_value=4.0),
        ],
        default_values={"risk_per_trade_pct": 0.006, "compression_threshold": 0.5, "expansion_multiplier": 2.0},
    ),
    StrategyInfo(
        id="liquidity_hunt",
        name="Liquidity Hunt",
        description="Identifies and trades liquidity sweeps. Enters after stop hunts at key levels reverse.",
        parameters=[
            StrategyParameter(name="risk_per_trade_pct", type="float", description="Risk per trade as percentage (decimal) of equity", default=0.005, min_value=0.001, max_value=0.02),
            StrategyParameter(name="sweep_threshold_pct", type="float", description="Minimum sweep percentage (decimal)", default=0.003, min_value=0.001, max_value=0.01),
            StrategyParameter(name="reversal_confirmation_bars", type="int", description="Bars to confirm reversal", default=2, min_value=1, max_value=5),
        ],
        default_values={"risk_per_trade_pct": 0.005, "sweep_threshold_pct": 0.003, "reversal_confirmation_bars": 2},
    ),
    StrategyInfo(
        id="spread_compression",
        name="Spread Compression",
        description="Trades when spread compresses indicating potential move. Enters on spread expansion with direction.",
        parameters=[
            StrategyParameter(name="risk_per_trade_pct", type="float", description="Risk per trade as percentage (decimal) of equity", default=0.004, min_value=0.001, max_value=0.02),
            StrategyParameter(name="compression_ratio", type="float", description="Spread compression ratio threshold", default=0.5, min_value=0.2, max_value=0.8),
        ],
        default_values={"risk_per_trade_pct": 0.004, "compression_ratio": 0.5},
    ),
    StrategyInfo(
        id="vwap_reversion",
        name="VWAP Reversion",
        description="Trades reversion to VWAP. Enters when price extends from VWAP and shows reversal signs.",
        parameters=[
            StrategyParameter(name="risk_per_trade_pct", type="float", description="Risk per trade as percentage (decimal) of equity", default=0.005, min_value=0.001, max_value=0.02),
            StrategyParameter(name="min_distance_from_vwap_pct", type="float", description="Minimum distance from VWAP (decimal)", default=0.003, min_value=0.001, max_value=0.01),
            StrategyParameter(name="stop_loss_pct", type="float", description="Stop loss percentage (decimal)", default=0.008, min_value=0.002, max_value=0.02),
        ],
        default_values={"risk_per_trade_pct": 0.005, "min_distance_from_vwap_pct": 0.003, "stop_loss_pct": 0.008},
    ),
]


def get_strategy_registry() -> List[StrategyInfo]:
    """Get the strategy registry.
    
    Returns the hardcoded strategy list. In the future, this could be
    extended to dynamically load strategies from the deeptrader_core module.
    
    **Validates: Requirements R4.1**
    """
    return STRATEGY_REGISTRY


# ============================================================================
# Global Job Queue (singleton)
# ============================================================================

_JOB_QUEUE: Optional[BacktestJobQueue] = None


def get_job_queue() -> BacktestJobQueue:
    """Get or create the global job queue."""
    global _JOB_QUEUE
    if _JOB_QUEUE is None:
        max_concurrent = int(os.getenv("BACKTEST_MAX_CONCURRENT", "2"))
        timeout_hours = float(os.getenv("BACKTEST_TIMEOUT_HOURS", "4.0"))
        _JOB_QUEUE = BacktestJobQueue(
            max_concurrent=max_concurrent,
            timeout_hours=timeout_hours,
        )
    return _JOB_QUEUE


def set_job_queue(queue: BacktestJobQueue) -> None:
    """Set the global job queue (for testing)."""
    global _JOB_QUEUE
    _JOB_QUEUE = queue


# ============================================================================
# Router Creation
# ============================================================================

def create_backtest_router(
    dashboard_pool_dep,
    redis_client_dep,
    auth_dep,
    use_tenant_isolation: bool = False,
    timescale_pool_dep=None,
) -> APIRouter:
    """Create the backtest API router.
    
    Args:
        dashboard_pool_dep: Dependency for database pool (platform DB)
        redis_client_dep: Dependency for Redis client
        auth_dep: Authentication dependency
        use_tenant_isolation: If True, use claims-based tenant isolation.
            If False, use DEFAULT_TENANT_ID from environment.
        timescale_pool_dep: Optional dependency for timescale database pool (for market_candles)
        
    Returns:
        FastAPI router with backtest endpoints
    """
    from quantgambit.auth.jwt_auth import build_auth_dependency_with_claims, UserClaims, verify_tenant_access
    
    router = APIRouter(prefix="/api/research", tags=["research"])
    _load_model_training_jobs_from_disk()
    _hydrate_model_training_jobs_from_artifacts()
    
    # Default tenant/bot from environment (used when tenant isolation is disabled)
    default_tenant = os.getenv("DEFAULT_TENANT_ID", "default")
    default_bot = os.getenv("DEFAULT_BOT_ID", "default")
    
    # Build claims-based auth dependency if tenant isolation is enabled
    if use_tenant_isolation:
        claims_auth_dep = build_auth_dependency_with_claims()
    else:
        claims_auth_dep = None
    
    def get_tenant_id(claims: Optional[Any] = None) -> str:
        """Get tenant ID from claims or default."""
        if use_tenant_isolation and claims:
            return claims.tenant_id
        return default_tenant
    
    @router.post("/backtests", response_model=CreateBacktestResponse, dependencies=[Depends(auth_dep)])
    async def create_backtest(
        request: CreateBacktestRequest,
        pool=Depends(dashboard_pool_dep),
        redis_client=Depends(redis_client_dep),
        timescale_pool=Depends(timescale_pool_dep) if timescale_pool_dep else None,
        # Keep un-annotated: `UserClaims` is imported inside the router factory,
        # and OpenAPI generation will fail under `from __future__ import annotations`
        # if this is annotated as `Optional[UserClaims]`.
        claims=Depends(claims_auth_dep) if use_tenant_isolation else None,
    ) -> CreateBacktestResponse:
        """Create a new backtest run.
        
        Validates the request, creates a run record with status="pending",
        submits the job to the BacktestJobQueue, and returns the run_id immediately.
        
        **Validates: Requirements R1.1**
        
        Raises:
            ValidationError: If request validation fails
            DatabaseError: If database operation fails
        """
        try:
            # Get tenant ID from claims or default
            tenant_id = get_tenant_id(claims)
            
            # Validate dates using module-level function
            start_dt = _validate_date(request.start_date, "start_date")
            end_dt = _validate_date(request.end_date, "end_date")
            _validate_date_range(start_dt, end_dt, request.start_date, request.end_date)

            # Fail fast when requested window has no source data.
            data_source = (os.getenv("BACKTEST_DATA_SOURCE", "timescaledb") or "timescaledb").strip().lower()
            if data_source == "timescaledb":
                await _preflight_validate_backtest_data(
                    timescale_pool=timescale_pool,
                    symbol=request.symbol,
                    start_dt=start_dt,
                    end_dt=end_dt,
                    require_decision_events=True,
                )
            
            # Validate required fields using error module utilities
            strategy_id, profile_id = request.get_strategy_or_profile()
            if not strategy_id and not profile_id:
                raise ValidationError("Either strategy_id or profile_id must be provided")
            validate_required_field(request.symbol, "symbol")
            validate_positive_number(request.initial_capital, "initial_capital")
            
            # Generate run_id
            run_id = str(uuid.uuid4())
            
            # Build config
            config = {
                "name": request.name,
                "strategy_id": strategy_id,
                "profile_id": profile_id,
                "symbol": request.symbol,
                "start_date": request.start_date,
                "end_date": request.end_date,
                "initial_capital": request.initial_capital,
                "force_run": request.force_run,
                **request.config,
            }
            
            # Create run record with status="pending"
            store = BacktestStore(pool)
            now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            
            run_record = BacktestRunRecord(
                run_id=run_id,
                tenant_id=tenant_id,
                bot_id=default_bot,
                status="pending",
                started_at=now_iso,
                config=config,
                name=request.name,
                symbol=request.symbol,
                start_date=request.start_date,
                end_date=request.end_date,
            )
            
            await store.write_run(run_record)
            
            # Note: The backtest-worker process will pick up pending jobs
            # and execute them asynchronously. We don't execute inline here.
            
            return CreateBacktestResponse(
                run_id=run_id,
                status="pending",
                message="Backtest job submitted successfully",
            )
        except APIError:
            # Re-raise our custom errors
            raise
        except Exception as e:
            logger.exception(f"Error creating backtest: {e}")
            raise DatabaseError("backtest creation")

    @router.get("/backtests/preflight", response_model=BacktestPreflightResponse, dependencies=[Depends(auth_dep)])
    async def backtest_preflight(
        symbol: str = Query(..., description="Trading symbol (e.g., BTCUSDT or BTC-USDT-SWAP)"),
        start_date: str = Query(..., description="Start date in ISO format"),
        end_date: str = Query(..., description="End date in ISO format"),
        require_decision_events: bool = Query(True, description="Require decision events in range"),
        timescale_pool=Depends(timescale_pool_dep) if timescale_pool_dep else None,
    ) -> BacktestPreflightResponse:
        try:
            start_dt = _validate_date(start_date, "start_date")
            end_dt = _validate_date(end_date, "end_date")
            _validate_date_range(start_dt, end_dt, start_date, end_date)
            report = await _backtest_preflight_report(
                timescale_pool=timescale_pool,
                symbol=symbol,
                start_dt=start_dt,
                end_dt=end_dt,
                require_decision_events=require_decision_events,
            )
            return BacktestPreflightResponse(**report)
        except APIError:
            raise
        except Exception as e:
            logger.exception(f"Error in backtest preflight: {e}")
            raise DatabaseError("backtest preflight")
    
    @router.get("/backtests", response_model=BacktestListResponse, dependencies=[Depends(auth_dep)])
    async def list_backtests(
        status: Optional[str] = Query(None, description="Filter by status"),
        strategy_id: Optional[str] = Query(None, description="Filter by strategy_id"),
        symbol: Optional[str] = Query(None, description="Filter by symbol"),
        limit: int = Query(50, ge=1, le=500, description="Maximum results to return"),
        offset: int = Query(0, ge=0, description="Offset for pagination"),
        pool=Depends(dashboard_pool_dep),
    ) -> BacktestListResponse:
        """List backtest runs with optional filtering.
        
        Supports filtering by status, strategy_id, and symbol.
        Returns paginated results.
        
        **Validates: Requirements R1.2**
        
        Raises:
            DatabaseError: If database operation fails
        """
        try:
            store = BacktestStore(pool)
            
            # Get runs with filtering
            runs = await store.list_runs(
                tenant_id=default_tenant,
                status=status,
                symbol=symbol,
                limit=limit,
                offset=offset,
            )
            
            # Get total count
            total = await store.count_runs(
                tenant_id=default_tenant,
                status=status,
                symbol=symbol,
            )
            
            # Build response
            backtests = []
            for run in runs:
                # Get metrics for results object
                metrics = await store.get_metrics(run.run_id)
                
                # Extract strategy_id and other config from config
                config = run.config or {}
                run_strategy_id = config.get("strategy_id")
                
                # Filter by strategy_id if specified (since store doesn't support it)
                if strategy_id and run_strategy_id != strategy_id:
                    continue
                
                # Build results object if metrics exist
                results = None
                if metrics:
                    results = BacktestResults(
                        total_return_pct=metrics.total_return_pct,
                        max_drawdown_pct=metrics.max_drawdown_pct,
                        sharpe_ratio=metrics.sharpe_ratio,
                        sortino_ratio=metrics.sortino_ratio,
                        profit_factor=metrics.profit_factor,
                        win_rate=metrics.win_rate,
                        total_trades=metrics.total_trades,
                        trades_per_day=metrics.trades_per_day,
                        expectancy=metrics.avg_trade_pnl,
                        fee_drag_pct=metrics.fee_drag_pct,
                        slippage_drag_pct=metrics.slippage_drag_pct,
                        realized_pnl=metrics.realized_pnl,
                        total_fees=metrics.total_fees,
                        gross_profit=metrics.gross_profit,
                        gross_loss=metrics.gross_loss,
                        avg_win=metrics.avg_win,
                        avg_loss=metrics.avg_loss,
                        largest_win=metrics.largest_win,
                        largest_loss=metrics.largest_loss,
                        winning_trades=metrics.winning_trades,
                        losing_trades=metrics.losing_trades,
                    )
                
                backtests.append(BacktestSummary(
                    id=run.run_id,
                    name=run.name,
                    strategy_id=run_strategy_id,
                    profile_id=run_strategy_id,
                    strategy=run_strategy_id,
                    symbol=run.symbol,
                    exchange=config.get("exchange", "okx"),
                    timeframe=config.get("timeframe", "5m"),
                    status=run.status,
                    start_date=run.start_date,
                    end_date=run.end_date,
                    initial_capital=config.get("initial_capital", 10000),
                    slippage_bps=config.get("slippage_bps"),
                    created_at=run.created_at,
                    completed_at=run.finished_at,
                    results=results,
                    # Legacy flat fields
                    realized_pnl=metrics.realized_pnl if metrics else None,
                    total_return_pct=metrics.total_return_pct if metrics else None,
                ))
            
            return BacktestListResponse(
                backtests=backtests,
                total=total,
            )
        except APIError:
            raise
        except Exception as e:
            logger.exception(f"Error listing backtests: {e}")
            raise DatabaseError("listing backtests")
    
    @router.get("/backtests/{run_id}", response_model=BacktestDetailResponse, dependencies=[Depends(auth_dep)])
    async def get_backtest_detail(
        run_id: str,
        pool=Depends(dashboard_pool_dep),
    ) -> BacktestDetailResponse:
        """Get detailed results for a specific backtest run.
        
        Returns run metadata, equity curve, trades, decisions, and metrics.
        
        **Validates: Requirements R1.3**
        
        Raises:
            BacktestNotFoundError: If backtest run not found
            DatabaseError: If database operation fails
        """
        try:
            store = BacktestStore(pool)
            
            # Get run record
            run = await store.get_run(run_id)
            if not run:
                raise BacktestNotFoundError(run_id)
            
            # Get metrics
            metrics_record = await store.get_metrics(run_id)
            metrics = None
            if metrics_record:
                metrics = BacktestMetrics(
                    realized_pnl=metrics_record.realized_pnl,
                    total_fees=metrics_record.total_fees,
                    total_trades=metrics_record.total_trades,
                    win_rate=metrics_record.win_rate,
                    max_drawdown_pct=metrics_record.max_drawdown_pct,
                    avg_slippage_bps=metrics_record.avg_slippage_bps,
                    total_return_pct=metrics_record.total_return_pct,
                    profit_factor=metrics_record.profit_factor,
                    avg_trade_pnl=metrics_record.avg_trade_pnl,
                    sharpe_ratio=metrics_record.sharpe_ratio,
                    sortino_ratio=metrics_record.sortino_ratio,
                    trades_per_day=metrics_record.trades_per_day,
                    fee_drag_pct=metrics_record.fee_drag_pct,
                    slippage_drag_pct=metrics_record.slippage_drag_pct,
                    gross_profit=metrics_record.gross_profit,
                    gross_loss=metrics_record.gross_loss,
                    avg_win=metrics_record.avg_win,
                    avg_loss=metrics_record.avg_loss,
                    largest_win=metrics_record.largest_win,
                    largest_loss=metrics_record.largest_loss,
                    winning_trades=metrics_record.winning_trades,
                    losing_trades=metrics_record.losing_trades,
                )
            
            # Get equity curve - format for frontend compatibility
            equity_records = await store.get_equity_curve(run_id)
            equity_curve = [
                EquityCurvePointResponse(
                    time=record.ts,
                    value=record.equity,
                    timestamp=record.ts,
                    equity=record.equity,
                    drawdown=0,  # TODO: calculate drawdown
                )
                for record in equity_records
            ]
            
            # Get trades - format for frontend compatibility
            trade_records = await store.get_trades(run_id)
            trades = [
                TradeResponse(
                    id=f"{record.run_id}_{idx}",
                    ts=record.ts,
                    entry_time=record.ts,
                    exit_time=record.ts,  # TODO: store actual exit time
                    symbol=record.symbol,
                    side=record.side,
                    direction=record.side,
                    size=record.size,
                    quantity=record.size,
                    entry_price=record.entry_price,
                    exit_price=record.exit_price,
                    entry=record.entry_price,
                    exit=record.exit_price,
                    pnl=record.pnl,
                    pnl_pct=(record.exit_price - record.entry_price) / record.entry_price * 100
                        if record.side == "long" and record.entry_price
                        else (record.entry_price - record.exit_price) / record.entry_price * 100
                        if record.entry_price else 0.0,
                    realized_pnl=record.pnl,
                    total_fees=record.total_fees,
                    exit_reason=record.reason,
                )
                for idx, record in enumerate(trade_records)
            ]
            
            # Get decisions
            decision_records = await store.get_decision_snapshots(run_id)
            decisions = [
                DecisionSnapshot(
                    ts=record.ts,
                    symbol=record.symbol,
                    decision=record.decision,
                    rejection_reason=record.rejection_reason,
                    profile_id=record.profile_id,
                )
                for record in decision_records
            ]
            
            # Build run detail with all fields for frontend compatibility
            config = run.config or {}
            run_detail = BacktestRunDetail(
                id=run.run_id,
                name=run.name,
                strategy_id=config.get("strategy_id"),
                profile_id=config.get("strategy_id"),
                symbol=run.symbol,
                exchange=config.get("exchange", "okx"),
                timeframe=config.get("timeframe", "5m"),
                status=run.status,
                start_date=run.start_date,
                end_date=run.end_date,
                initial_capital=config.get("initial_capital", 10000),
                slippage_bps=config.get("slippage_bps"),
                started_at=run.started_at,
                finished_at=run.finished_at,
                completed_at=run.finished_at,
                error_message=run.error_message,
                config=config,
                # Metrics fields for frontend
                total_return_percent=metrics_record.total_return_pct if metrics_record else None,
                sharpe_ratio=None,  # Not stored yet
                max_drawdown_percent=metrics_record.max_drawdown_pct if metrics_record else None,
                win_rate=metrics_record.win_rate if metrics_record else None,
                total_trades=metrics_record.total_trades if metrics_record else None,
                profit_factor=metrics_record.profit_factor if metrics_record else None,
            )
            
            # Build execution diagnostics response if available
            # Feature: backtest-diagnostics
            # **Validates: Requirements 2.1**
            execution_diagnostics = None
            if run.execution_diagnostics:
                diag = run.execution_diagnostics
                # Build rejection breakdown from stored data
                breakdown_data = diag.get("rejection_breakdown", {})
                rejection_breakdown = RejectionBreakdownResponse(
                    spread_too_wide=breakdown_data.get("spread_too_wide", 0),
                    depth_too_thin=breakdown_data.get("depth_too_thin", 0),
                    snapshot_stale=breakdown_data.get("snapshot_stale", 0),
                    vol_shock=breakdown_data.get("vol_shock", 0),
                )
                
                execution_diagnostics = ExecutionDiagnosticsResponse(
                    total_snapshots=diag.get("total_snapshots", 0),
                    snapshots_processed=diag.get("snapshots_processed", 0),
                    snapshots_skipped=diag.get("snapshots_skipped", 0),
                    global_gate_rejections=diag.get("global_gate_rejections", 0),
                    rejection_breakdown=rejection_breakdown,
                    profiles_selected=diag.get("profiles_selected", 0),
                    signals_generated=diag.get("signals_generated", 0),
                    cooldown_rejections=diag.get("cooldown_rejections", 0),
                    summary=diag.get("summary", ""),
                    primary_issue=diag.get("primary_issue"),
                    suggestions=diag.get("suggestions", []),
                )
            
            return BacktestDetailResponse(
                backtest=run_detail,
                run=run_detail,  # Legacy field
                metrics=metrics,
                equityCurve=equity_curve,
                equity_curve=None,  # Legacy field
                trades=trades,
                decisions=decisions,
                execution_diagnostics=execution_diagnostics,
            )
        except APIError:
            raise
        except Exception as e:
            logger.exception(f"Error getting backtest detail: {e}")
            raise DatabaseError("getting backtest detail")
    
    @router.delete("/backtests/{run_id}", response_model=CancelBacktestResponse, dependencies=[Depends(auth_dep)])
    async def cancel_backtest(
        run_id: str,
        pool=Depends(dashboard_pool_dep),
    ) -> CancelBacktestResponse:
        """Cancel a running backtest job.
        
        Cancels the job via BacktestJobQueue and updates status to "cancelled".
        
        **Validates: Requirements R5.5**
        
        Raises:
            BacktestNotFoundError: If backtest run not found
            InvalidStatusTransitionError: If backtest cannot be cancelled
            DatabaseError: If database operation fails
        """
        try:
            store = BacktestStore(pool)
            
            # Check if run exists
            run = await store.get_run(run_id)
            if not run:
                raise BacktestNotFoundError(run_id)
            
            # Check if run can be cancelled
            if run.status not in ("pending", "running"):
                raise InvalidStatusTransitionError(run.status, "cancel")
            
            # Try to cancel via job queue
            job_queue = get_job_queue()
            cancelled = await job_queue.cancel(run_id)
            
            # Update status in database
            await store.update_run_status(
                run_id=run_id,
                status="cancelled",
                finished_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            )
            
            return CancelBacktestResponse(
                success=True,
                message="Backtest cancelled successfully" if cancelled else "Backtest marked as cancelled",
                run_id=run_id,
                status="cancelled",
            )
        except APIError:
            raise
        except Exception as e:
            logger.exception(f"Error cancelling backtest: {e}")
            raise DatabaseError("cancelling backtest")
    
    @router.post("/backtests/{run_id}/rerun", response_model=CreateBacktestResponse, dependencies=[Depends(auth_dep)])
    async def rerun_backtest(
        run_id: str,
        request: RerunBacktestRequest = Body(default_factory=RerunBacktestRequest),
        pool=Depends(dashboard_pool_dep),
        # Keep un-annotated: `UserClaims` is imported inside the router factory,
        # and OpenAPI generation will fail under `from __future__ import annotations`
        # if this is annotated as `Optional[UserClaims]`.
        claims=Depends(claims_auth_dep) if use_tenant_isolation else None,
    ) -> CreateBacktestResponse:
        """Clone and rerun a backtest with the same configuration.
        
        Creates a new backtest run with the same configuration as the original.
        The new run gets a fresh run_id and starts with status="pending".
        
        Args:
            run_id: Original backtest run ID to clone
            request: Optional request body with force_run flag
        
        Raises:
            BacktestNotFoundError: If original backtest run not found
            DatabaseError: If database operation fails
        """
        try:
            store = BacktestStore(pool)
            
            # Get original run
            original_run = await store.get_run(run_id)
            if not original_run:
                raise BacktestNotFoundError(run_id)
            
            # Generate new run_id
            new_run_id = str(uuid.uuid4())
            
            # Get tenant ID from claims or default
            tenant_id = get_tenant_id(claims)
            
            # Create new run record with same config
            now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            config = original_run.config or {}
            
            # Apply force_run if requested
            force_run = request.force_run
            logger.info(f"Rerun backtest {run_id}: force_run={force_run}, request={request}")
            if force_run:
                config["force_run"] = True
            
            # Update name to indicate it's a rerun
            original_name = original_run.name or f"Run {run_id[:8]}"
            new_name = f"{original_name} (rerun)"
            if force_run:
                new_name = f"{original_name} (force rerun)"
            
            new_run_record = BacktestRunRecord(
                run_id=new_run_id,
                tenant_id=tenant_id,
                bot_id=original_run.bot_id,
                status="pending",
                started_at=now_iso,
                config=config,
                name=new_name,
                symbol=original_run.symbol,
                start_date=original_run.start_date,
                end_date=original_run.end_date,
            )
            
            await store.write_run(new_run_record)
            
            message = f"Backtest rerun submitted (cloned from {run_id})"
            if force_run:
                message = f"Backtest force rerun submitted (cloned from {run_id}, bypassing data validation)"
            
            return CreateBacktestResponse(
                run_id=new_run_id,
                status="pending",
                message=message,
            )
        except APIError:
            raise
        except Exception as e:
            logger.exception(f"Error rerunning backtest: {e}")
            raise DatabaseError("rerunning backtest")

    @router.post(
        "/backtests/{run_id}/promote",
        response_model=PromoteBacktestResponse,
        dependencies=[Depends(auth_dep)],
    )
    async def promote_backtest(
        run_id: str,
        request: PromoteBacktestRequest = Body(default_factory=PromoteBacktestRequest),
        pool=Depends(dashboard_pool_dep),
    ) -> PromoteBacktestResponse:
        """Promote completed/degraded backtest config into bot profile versions."""
        try:
            store = BacktestStore(pool)
            run = await store.get_run(run_id)
            if not run:
                raise BacktestNotFoundError(run_id)
            if run.status not in {"completed", "degraded"}:
                raise InvalidStatusTransitionError(run.status, "promote")

            target_bot_id = request.bot_id or default_bot
            if not target_bot_id:
                raise ValidationError("bot_id is required")

            config_blob = dict(run.config or {})
            config_blob["promoted_from_backtest_run_id"] = run_id
            config_blob["promoted_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

            async with pool.acquire() as conn:
                async with conn.transaction():
                    bot_row = await conn.fetchrow(
                        "SELECT id FROM bot_profiles WHERE id=$1",
                        target_bot_id,
                    )
                    if not bot_row:
                        await conn.execute(
                            "INSERT INTO bot_profiles (id, name, environment, engine_type, description, status, metadata) "
                            "VALUES ($1, $2, $3, $4, $5, $6, $7)",
                            target_bot_id,
                            f"Bot {target_bot_id}",
                            "paper",
                            "quantgambit",
                            "Auto-created during backtest promotion",
                            "inactive",
                            json.dumps({}),
                        )

                    max_version_row = await conn.fetchrow(
                        "SELECT COALESCE(MAX(version_number), 0) AS max_version "
                        "FROM bot_profile_versions WHERE bot_profile_id=$1",
                        target_bot_id,
                    )
                    next_version = int((max_version_row or {}).get("max_version", 0)) + 1

                    version_row = await conn.fetchrow(
                        "INSERT INTO bot_profile_versions (bot_profile_id, version_number, status, config_blob, notes, promoted_by) "
                        "VALUES ($1, $2, $3, $4, $5, $6) "
                        "RETURNING id, version_number",
                        target_bot_id,
                        next_version,
                        request.status or "draft",
                        json.dumps(config_blob),
                        request.notes or f"Promoted from backtest {run_id}",
                        "backtest_promoter",
                    )
                    if not version_row:
                        raise DatabaseError("creating bot profile version")

                    if request.activate:
                        await conn.execute(
                            "UPDATE bot_profiles SET active_version_id=$1, updated_at=NOW() WHERE id=$2",
                            version_row["id"],
                            target_bot_id,
                        )

            return PromoteBacktestResponse(
                success=True,
                run_id=run_id,
                bot_id=target_bot_id,
                version_id=str(version_row["id"]),
                version_number=int(version_row["version_number"]),
                activated=bool(request.activate),
            )
        except APIError:
            raise
        except Exception as e:
            logger.exception(f"Error promoting backtest {run_id}: {e}")
            raise DatabaseError("promoting backtest config")

    @router.delete("/backtests/{run_id}/delete", dependencies=[Depends(auth_dep)])
    async def delete_backtest(
        run_id: str,
        pool=Depends(dashboard_pool_dep),
    ) -> Dict[str, Any]:
        """Permanently delete a backtest run and all associated data.
        
        Deletes the run record, metrics, trades, equity curve, and decision snapshots.
        This action cannot be undone.
        
        Raises:
            BacktestNotFoundError: If backtest run not found
            InvalidStatusTransitionError: If backtest is currently running
            DatabaseError: If database operation fails
        """
        try:
            store = BacktestStore(pool)
            
            # Check if run exists
            run = await store.get_run(run_id)
            if not run:
                raise BacktestNotFoundError(run_id)
            
            # Don't allow deleting running backtests
            if run.status == "running":
                raise InvalidStatusTransitionError(run.status, "delete")
            
            # Delete the run (cascades to related tables via FK constraints)
            deleted = await store.delete_run(run_id)
            
            return {
                "success": deleted,
                "message": "Backtest deleted successfully" if deleted else "Backtest not found",
                "run_id": run_id,
            }
        except APIError:
            raise
        except Exception as e:
            logger.exception(f"Error deleting backtest: {e}")
            raise DatabaseError("deleting backtest")
    
    @router.get("/backtests/{run_id}/export", dependencies=[Depends(auth_dep)])
    async def export_backtest(
        run_id: str,
        format: str = Query("json", description="Export format: json or csv"),
        pool=Depends(dashboard_pool_dep),
    ) -> Response:
        """Export backtest results in specified format.
        
        Supports JSON and CSV formats. Returns a downloadable file.
        
        **Validates: Requirements R6.1**
        
        Raises:
            InvalidFormatError: If format is not json or csv
            BacktestNotFoundError: If backtest run not found
            DatabaseError: If database operation fails
        """
        try:
            store = BacktestStore(pool)
            
            # Validate format
            if format not in ("json", "csv"):
                raise InvalidFormatError(format, ["json", "csv"])
            
            # Get run record
            run = await store.get_run(run_id)
            if not run:
                raise BacktestNotFoundError(run_id)
            
            # Get all data
            metrics = await store.get_metrics(run_id)
            equity_curve = await store.get_equity_curve(run_id)
            trades = await store.get_trades(run_id)
            
            if format == "json":
                # Build JSON export
                export_data = {
                    "run": {
                        "id": run.run_id,
                        "name": run.name,
                        "symbol": run.symbol,
                        "status": run.status,
                        "start_date": run.start_date,
                        "end_date": run.end_date,
                        "started_at": run.started_at,
                        "finished_at": run.finished_at,
                        "config": run.config,
                    },
                    "metrics": {
                        "realized_pnl": metrics.realized_pnl if metrics else None,
                        "total_fees": metrics.total_fees if metrics else None,
                        "total_trades": metrics.total_trades if metrics else None,
                        "win_rate": metrics.win_rate if metrics else None,
                        "max_drawdown_pct": metrics.max_drawdown_pct if metrics else None,
                        "avg_slippage_bps": metrics.avg_slippage_bps if metrics else None,
                        "total_return_pct": metrics.total_return_pct if metrics else None,
                        "profit_factor": metrics.profit_factor if metrics else None,
                        "avg_trade_pnl": metrics.avg_trade_pnl if metrics else None,
                    } if metrics else None,
                    "equity_curve": [
                        {
                            "ts": point.ts,
                            "equity": point.equity,
                            "realized_pnl": point.realized_pnl,
                            "open_positions": point.open_positions,
                        }
                        for point in equity_curve
                    ],
                    "trades": [
                        {
                            "ts": trade.ts,
                            "symbol": trade.symbol,
                            "side": trade.side,
                            "size": trade.size,
                            "entry_price": trade.entry_price,
                            "exit_price": trade.exit_price,
                            "pnl": trade.pnl,
                            "total_fees": trade.total_fees,
                            "entry_slippage_bps": trade.entry_slippage_bps,
                            "exit_slippage_bps": trade.exit_slippage_bps,
                        }
                        for trade in trades
                    ],
                }
                
                content = json.dumps(export_data, indent=2)
                return Response(
                    content=content,
                    media_type="application/json",
                    headers={
                        "Content-Disposition": f"attachment; filename=backtest_{run_id}.json"
                    },
                )
            
            else:  # CSV format
                # Create CSV with trades
                output = io.StringIO()
                writer = csv.writer(output)
                
                # Write header
                writer.writerow([
                    "ts", "symbol", "side", "size", "entry_price", "exit_price",
                    "pnl", "total_fees", "entry_slippage_bps", "exit_slippage_bps"
                ])
                
                # Write trades
                for trade in trades:
                    writer.writerow([
                        trade.ts,
                        trade.symbol,
                        trade.side,
                        trade.size,
                        trade.entry_price,
                        trade.exit_price,
                        trade.pnl,
                        trade.total_fees,
                        trade.entry_slippage_bps,
                        trade.exit_slippage_bps,
                    ])
                
                content = output.getvalue()
                return Response(
                    content=content,
                    media_type="text/csv",
                    headers={
                        "Content-Disposition": f"attachment; filename=backtest_{run_id}.csv"
                    },
                )
        except APIError:
            raise
        except Exception as e:
            logger.exception(f"Error exporting backtest: {e}")
            raise DatabaseError("exporting backtest")
    
    @router.get("/datasets", response_model=DatasetListResponse, dependencies=[Depends(auth_dep)])
    async def list_datasets(
        symbol: Optional[str] = Query(None, description="Filter by symbol (e.g., BTC-USDT-SWAP)"),
        redis_client=Depends(redis_client_dep),
    ) -> DatasetListResponse:
        """List available datasets for backtesting.
        
        Returns the configured trading symbols with their data availability.
        Uses fast indexed queries per-symbol instead of expensive GROUP BY scans.
        
        **Validates: Requirements R2.1, R2.2**
        
        Raises:
            RedisError: If Redis operation fails
            DatabaseError: If database operation fails
        """
        import asyncpg
        
        dataset_infos: List[DatasetInfo] = []
        data_source = os.getenv("BACKTEST_DATA_SOURCE", "redis")
        default_exchange = os.getenv("BACKTEST_DEFAULT_EXCHANGE", "bybit")
        
        # Get configured symbols from environment (these are the symbols we collect data for)
        configured_symbols_str = os.getenv("ORDERBOOK_SYMBOLS", "") or os.getenv("TRADE_SYMBOLS", "")
        configured_symbols = [s.strip() for s in configured_symbols_str.split(",") if s.strip()]
        
        # Fallback to common symbols if not configured
        if not configured_symbols:
            configured_symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
        
        # Filter by requested symbol if provided
        if symbol:
            configured_symbols = [s for s in configured_symbols if s == symbol]
        
        # When using timescaledb data source, query decision_events per symbol
        # This is much faster than GROUP BY on millions of rows
        if data_source == "timescaledb":
            try:
                conn = await asyncpg.connect(**_timescale_connect_kwargs())
                try:
                    # Query each symbol individually - uses index efficiently
                    for sym in configured_symbols:
                        # Get min/max timestamps for this symbol
                        row = await conn.fetchrow("""
                            SELECT 
                                MIN(ts) as earliest_date,
                                MAX(ts) as latest_date
                            FROM decision_events
                            WHERE symbol = $1
                        """, sym)
                        
                        if row and row["earliest_date"]:
                            # Estimate count based on time range (assuming ~1 event per second)
                            # This is much faster than COUNT(*) on millions of rows
                            earliest = row["earliest_date"]
                            latest = row["latest_date"]
                            if earliest and latest:
                                time_diff = (latest - earliest).total_seconds()
                                # Rough estimate: ~1 decision event per second per symbol
                                approx_count = int(time_diff)
                            else:
                                approx_count = 0
                            
                            dataset_infos.append(DatasetInfo(
                                symbol=sym,
                                exchange=default_exchange,
                                earliest_date=row["earliest_date"].isoformat() if row["earliest_date"] else "",
                                latest_date=row["latest_date"].isoformat() if row["latest_date"] else "",
                                candle_count=approx_count,
                                gaps=0,
                                gap_dates=[],
                                completeness_pct=100.0,
                                last_updated=row["latest_date"].isoformat() if row["latest_date"] else "",
                            ))
                finally:
                    await conn.close()
            except Exception as e:
                logger.warning(f"Could not query decision_events table: {e}")
        
        # Fallback: try market_candles table with per-symbol queries
        if not dataset_infos:
            try:
                conn = await asyncpg.connect(dsn)
                try:
                    for sym in configured_symbols:
                        row = await conn.fetchrow("""
                            SELECT 
                                MIN(ts) as earliest_date,
                                MAX(ts) as latest_date
                            FROM market_candles
                            WHERE symbol = $1
                        """, sym)
                        
                        if row and row["earliest_date"]:
                            # Get exchange from first row
                            exchange_row = await conn.fetchrow("""
                                SELECT exchange FROM market_candles WHERE symbol = $1 LIMIT 1
                            """, sym)
                            exchange = exchange_row["exchange"] if exchange_row else "OKX"
                            
                            # Estimate count based on time range
                            earliest = row["earliest_date"]
                            latest = row["latest_date"]
                            if earliest and latest:
                                time_diff = (latest - earliest).total_seconds()
                                # Rough estimate: ~1 candle per second
                                approx_count = int(time_diff)
                            else:
                                approx_count = 0
                            
                            dataset_infos.append(DatasetInfo(
                                symbol=sym,
                                exchange=exchange,
                                earliest_date=row["earliest_date"].isoformat() if row["earliest_date"] else "",
                                latest_date=row["latest_date"].isoformat() if row["latest_date"] else "",
                                candle_count=approx_count,
                                gaps=0,
                                gap_dates=[],
                                completeness_pct=100.0,
                                last_updated=row["latest_date"].isoformat() if row["latest_date"] else "",
                            ))
                finally:
                    await conn.close()
            except Exception as e:
                logger.warning(f"Could not query market_candles table: {e}")
        
        # If no database results, try Redis streams
        if not dataset_infos:
            try:
                # Get stream key and exchange from environment
                stream_key = os.getenv("BACKTEST_STREAM_KEY", "events:feature_snapshots")
                exchange = os.getenv("BACKTEST_EXCHANGE", "OKX")
                
                # Create scanner config
                config = ScanConfig(
                    stream_key=stream_key,
                    exchange=exchange,
                )
                
                # Scan datasets
                scanner = DatasetScanner(redis_client, config)
                datasets = await scanner.scan_datasets(symbol_filter=symbol)
                
                # Convert to response model
                dataset_infos = [
                    DatasetInfo(
                        symbol=ds.symbol,
                        exchange=ds.exchange,
                        earliest_date=ds.earliest_date,
                        latest_date=ds.latest_date,
                        candle_count=ds.candle_count,
                        gaps=ds.gaps,
                        gap_dates=ds.gap_dates,
                        completeness_pct=ds.completeness_pct,
                        last_updated=ds.last_updated,
                    )
                    for ds in datasets
                ]
            except Exception as e:
                logger.warning(f"Could not scan Redis streams: {e}")
        
        return DatasetListResponse(
            datasets=dataset_infos,
            total=len(dataset_infos),
        )
    
    # ========================================================================
    # Data Validation Endpoint
    # ========================================================================
    
    @router.get("/validate-data", response_model=ValidateDataResponse, dependencies=[Depends(auth_dep)])
    async def validate_data(
        symbol: str = Query(..., description="Trading symbol (e.g., BTC-USDT-SWAP)"),
        start_date: str = Query(..., description="Start date in ISO format (YYYY-MM-DD)"),
        end_date: str = Query(..., description="End date in ISO format (YYYY-MM-DD)"),
        minimum_completeness_pct: float = Query(80.0, ge=0, le=100, description="Minimum completeness threshold"),
        max_critical_gaps: int = Query(5, ge=0, description="Maximum critical gaps allowed"),
        max_gap_duration_pct: float = Query(10.0, ge=0, le=100, description="Maximum gap duration percentage"),
    ) -> ValidateDataResponse:
        """Validate data quality before running a backtest.
        
        Performs pre-flight validation to check data availability and quality
        for the specified symbol and date range. Returns quality metrics,
        gap analysis, and a recommendation.
        
        Feature: backtest-data-validation
        **Validates: Requirements 6.1, 6.2, 6.5**
        
        Note: This endpoint always returns HTTP 200. Validation failures are
        indicated in the response body (passes_threshold=False), not via HTTP status.
        
        Raises:
            ValidationError: If request parameters are invalid
            DatabaseError: If database operation fails
        """
        import asyncpg
        from quantgambit.backtesting.data_validator import DataValidator, ValidationConfig
        
        try:
            # Validate dates
            start_dt = _validate_date(start_date, "start_date")
            end_dt = _validate_date(end_date, "end_date")
            _validate_date_range(start_dt, end_dt, start_date, end_date)
            
            pool = await asyncpg.create_pool(**_timescale_connect_kwargs(), min_size=1, max_size=3)
            
            try:
                # Create validation config
                config = ValidationConfig(
                    minimum_completeness_pct=minimum_completeness_pct,
                    max_critical_gaps=max_critical_gaps,
                    max_gap_duration_pct=max_gap_duration_pct,
                )
                
                # Run validation
                validator = DataValidator(pool, config)
                report = await validator.validate(
                    symbol=symbol,
                    start_date=start_date,
                    end_date=end_date,
                    config=config,
                    force_run=False,
                )
                
                # Convert gap details to response model
                gap_details = [
                    GapDetail(
                        start_time=g.start_time,
                        end_time=g.end_time,
                        duration_minutes=g.duration_minutes,
                        is_critical=g.is_critical,
                        session=g.session,
                    )
                    for g in report.gap_details[:10]  # Limit to first 10
                ]
                
                return ValidateDataResponse(
                    symbol=report.symbol,
                    start_date=report.start_date,
                    end_date=report.end_date,
                    overall_completeness_pct=report.overall_completeness_pct,
                    data_quality_grade=report.data_quality_grade,
                    recommendation=report.recommendation,
                    total_gaps=report.total_gaps,
                    critical_gaps=report.critical_gaps,
                    gap_duration_pct=report.gap_duration_pct,
                    gap_details=gap_details,
                    decision_events_completeness=report.decision_events_completeness,
                    orderbook_events_completeness=report.orderbook_events_completeness,
                    candle_data_completeness=report.candle_data_completeness,
                    passes_threshold=report.passes_threshold,
                    threshold_overridden=report.threshold_overridden,
                    warnings=report.warnings,
                    errors=report.errors,
                )
            finally:
                await pool.close()
                
        except APIError:
            raise
        except Exception as e:
            logger.exception(f"Error validating data: {e}")
            raise DatabaseError("data validation")
    
    # ========================================================================
    # Walk-Forward Optimization Endpoints
    # ========================================================================
    
    @router.post("/walk-forward", response_model=CreateWFOResponse, dependencies=[Depends(auth_dep)])
    async def create_wfo_run(
        request: CreateWFORequest,
        pool=Depends(dashboard_pool_dep),
        redis_client=Depends(redis_client_dep),
    ) -> CreateWFOResponse:
        """Create a new walk-forward optimization run.
        
        Validates the WFO configuration, creates a wfo_runs record with status="pending",
        submits the WFO job to the queue, and returns the run_id immediately.
        
        **Validates: Requirements R3.1**
        
        Raises:
            ValidationError: If request validation fails
            DatabaseError: If database operation fails
        """
        try:
            # Validate required fields using error module utilities
            validate_required_field(request.profile_id, "profile_id")
            validate_required_field(request.symbol, "symbol")
            
            # Validate WFO config
            if request.config.in_sample_days < 1:
                raise InvalidFieldValueError("in_sample_days", "in_sample_days must be at least 1", request.config.in_sample_days)
            if request.config.out_sample_days < 1:
                raise InvalidFieldValueError("out_sample_days", "out_sample_days must be at least 1", request.config.out_sample_days)
            if request.config.periods < 1:
                raise InvalidFieldValueError("periods", "periods must be at least 1", request.config.periods)
            
            valid_objectives = ["sharpe", "sortino", "profit_factor"]
            validate_enum_value(request.config.objective, "objective", valid_objectives)
            
            # Generate run_id
            run_id = str(uuid.uuid4())
            
            # Build config dict
            config_dict = {
                "profile_id": request.profile_id,
                "symbol": request.symbol,
                "in_sample_days": request.config.in_sample_days,
                "out_sample_days": request.config.out_sample_days,
                "periods": request.config.periods,
                "objective": request.config.objective,
            }
            
            # Create WFO run record with status="pending"
            store = BacktestStore(pool)
            now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            
            wfo_record = WFORunRecord(
                run_id=run_id,
                tenant_id=default_tenant,
                bot_id=default_bot,
                profile_id=request.profile_id,
                symbol=request.symbol,
                status="pending",
                config=config_dict,
                results={},
                started_at=now_iso,
            )
            
            await store.write_wfo_run(wfo_record)
            
            # Submit WFO job to queue
            job_queue = get_job_queue()
            
            async def execute_wfo_job(job_run_id: str, job_config: Dict[str, Any]) -> None:
                """Execute the WFO job (placeholder - actual WFO logic would go here)."""
                # TODO: Implement actual WFO execution logic
                # For now, just update status to completed
                await store.update_wfo_run_status(
                    run_id=job_run_id,
                    status="finished",
                    results={"message": "WFO execution placeholder"},
                    finished_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                )
            
            await job_queue.submit(
                config=config_dict,
                executor=execute_wfo_job,
                run_id=run_id,
            )
            
            return CreateWFOResponse(
                run_id=run_id,
                status="pending",
                message="WFO job submitted successfully",
            )
        except APIError:
            raise
        except Exception as e:
            logger.exception(f"Error creating WFO run: {e}")
            raise DatabaseError("creating WFO run")
    
    @router.get("/walk-forward", response_model=WFOListResponse, dependencies=[Depends(auth_dep)])
    async def list_wfo_runs(
        profile_id: Optional[str] = Query(None, description="Filter by profile_id"),
        symbol: Optional[str] = Query(None, description="Filter by symbol"),
        status: Optional[str] = Query(None, description="Filter by status"),
        limit: int = Query(50, ge=1, le=500, description="Maximum results to return"),
        offset: int = Query(0, ge=0, description="Offset for pagination"),
        pool=Depends(dashboard_pool_dep),
    ) -> WFOListResponse:
        """List walk-forward optimization runs with optional filtering.
        
        Supports filtering by profile_id, symbol, and status.
        Returns paginated results.
        
        **Validates: Requirements R3.2**
        
        Raises:
            DatabaseError: If database operation fails
        """
        try:
            store = BacktestStore(pool)
            
            # Get WFO runs with filtering
            runs = await store.list_wfo_runs(
                tenant_id=default_tenant,
                profile_id=profile_id,
                symbol=symbol,
                status=status,
                limit=limit,
                offset=offset,
            )
            
            # Get total count
            total = await store.count_wfo_runs(
                tenant_id=default_tenant,
                profile_id=profile_id,
                symbol=symbol,
                status=status,
            )
            
            # Build response
            wfo_summaries = []
            for run in runs:
                # Extract summary metrics from results
                results = run.results or {}
                summary = results.get("summary", {})
                
                wfo_summaries.append(WFOSummary(
                    id=run.run_id,
                    profile_id=run.profile_id,
                    symbol=run.symbol,
                    status=run.status,
                    config=run.config,
                    created_at=run.created_at,
                    avg_is_sharpe=summary.get("avg_is_sharpe"),
                    avg_oos_sharpe=summary.get("avg_oos_sharpe"),
                    degradation_pct=summary.get("degradation_pct"),
                ))
            
            return WFOListResponse(
                runs=wfo_summaries,
                total=total,
            )
        except APIError:
            raise
        except Exception as e:
            logger.exception(f"Error listing WFO runs: {e}")
            raise DatabaseError("listing WFO runs")
    
    @router.get("/walk-forward/{run_id}", response_model=WFODetailResponse, dependencies=[Depends(auth_dep)])
    async def get_wfo_detail(
        run_id: str,
        pool=Depends(dashboard_pool_dep),
    ) -> WFODetailResponse:
        """Get detailed results for a specific WFO run.
        
        Returns run metadata, period-by-period results, summary statistics,
        and recommended parameters.
        
        **Validates: Requirements R3.3**
        
        Raises:
            WFORunNotFoundError: If WFO run not found
            DatabaseError: If database operation fails
        """
        try:
            store = BacktestStore(pool)
            
            # Get WFO run record
            run = await store.get_wfo_run(run_id)
            if not run:
                raise WFORunNotFoundError(run_id)
            
            # Parse results for period-by-period metrics
            results = run.results or {}
            periods_data = results.get("periods", [])
            
            periods = []
            for period_data in periods_data:
                periods.append(WFOPeriodResult(
                    period=period_data.get("period", 0),
                    in_sample_start=period_data.get("in_sample_start", ""),
                    in_sample_end=period_data.get("in_sample_end", ""),
                    out_sample_start=period_data.get("out_sample_start", ""),
                    out_sample_end=period_data.get("out_sample_end", ""),
                    in_sample_sharpe=period_data.get("in_sample_sharpe"),
                    out_sample_sharpe=period_data.get("out_sample_sharpe"),
                    in_sample_return_pct=period_data.get("in_sample_return_pct"),
                    out_sample_return_pct=period_data.get("out_sample_return_pct"),
                    in_sample_max_dd_pct=period_data.get("in_sample_max_dd_pct"),
                    out_sample_max_dd_pct=period_data.get("out_sample_max_dd_pct"),
                    optimized_params=period_data.get("optimized_params", {}),
                ))
            
            return WFODetailResponse(
                id=run.run_id,
                profile_id=run.profile_id,
                symbol=run.symbol,
                status=run.status,
                config=run.config or {},
                started_at=run.started_at,
                finished_at=run.finished_at,
                created_at=run.created_at,
                periods=periods,
                summary=results.get("summary", {}),
                recommended_params=results.get("recommended_params", {}),
                error_message=run.error_message,
            )
        except APIError:
            raise
        except Exception as e:
            logger.exception(f"Error getting WFO detail: {e}")
            raise DatabaseError("getting WFO detail")
    
    # ========================================================================
    # Strategy Registry Endpoint
    # ========================================================================
    
    @router.get("/strategies", response_model=StrategyListResponse, dependencies=[Depends(auth_dep)])
    async def list_strategies() -> StrategyListResponse:
        """List available strategies for backtesting.
        
        Returns all registered strategies with their metadata, parameters,
        and default values. This endpoint provides the strategy information
        needed to configure backtests.
        
        **Validates: Requirements R4.1**
        """
        strategies = get_strategy_registry()
        
        return StrategyListResponse(
            strategies=strategies,
            total=len(strategies),
        )
    
    # ========================================================================
    # Data Backfill Endpoints
    # ========================================================================
    
    # Store active backfill jobs for progress tracking
    _backfill_jobs: Dict[str, Any] = {}
    
    class BackfillResponse(BaseModel):
        """Response model for backfill operation."""
        job_id: str
        status: str
        message: str
        symbol: str
        exchange: str
        start_date: str
        end_date: str
        timeframe: str
    
    class BackfillProgressResponse(BaseModel):
        """Response model for backfill progress."""
        job_id: str
        status: str
        total_candles: int = 0
        inserted_candles: int = 0
        skipped_candles: int = 0
        failed_batches: int = 0
        current_date: Optional[str] = None
        started_at: Optional[str] = None
        finished_at: Optional[str] = None
        error: Optional[str] = None
    
    class BackfillResultResponse(BaseModel):
        """Response model for completed backfill."""
        job_id: str
        symbol: str
        exchange: str
        start_date: str
        end_date: str
        timeframe: str
        total_candles: int
        inserted_candles: int
        skipped_candles: int
        failed_batches: int
        duration_sec: float
        status: str
        error: Optional[str] = None
    
    @router.post("/backfill", response_model=BackfillResponse, dependencies=[Depends(auth_dep)])
    async def start_backfill(
        request: BackfillRequest,
        background_tasks: BackgroundTasks,
        pool=Depends(dashboard_pool_dep),
    ) -> BackfillResponse:
        """Start a data backfill operation.
        
        Fetches historical candle data from the specified exchange and inserts
        it into the market_candles table. Existing candles are skipped.
        
        The operation runs in the background. Use GET /backfill/{job_id}/progress
        to track progress.
        """
        from quantgambit.backtesting.data_backfill import DataBackfillService
        
        # Generate job ID
        job_id = f"backfill:{request.exchange}:{request.symbol}:{uuid.uuid4().hex[:8]}"
        
        # Validate dates
        start_dt = _validate_date(request.start_date, "start_date")
        end_dt = _validate_date(request.end_date, "end_date")
        _validate_date_range(start_dt, end_dt, request.start_date, request.end_date)
        
        # Create service and store reference
        service = DataBackfillService(pool)
        _backfill_jobs[job_id] = {
            "service": service,
            "status": "pending",
            "request": request.model_dump(),
        }
        
        async def run_backfill():
            try:
                _backfill_jobs[job_id]["status"] = "running"
                result = await service.backfill(
                    symbol=request.symbol,
                    exchange=request.exchange,
                    start_date=request.start_date,
                    end_date=request.end_date,
                    timeframe=request.timeframe,
                    job_id=job_id,
                )
                _backfill_jobs[job_id]["result"] = result.to_dict()
                _backfill_jobs[job_id]["status"] = result.status
            except Exception as e:
                logger.exception(f"Backfill job {job_id} failed: {e}")
                _backfill_jobs[job_id]["status"] = "failed"
                _backfill_jobs[job_id]["error"] = str(e)
        
        # Run in background
        background_tasks.add_task(run_backfill)
        
        return BackfillResponse(
            job_id=job_id,
            status="pending",
            message="Backfill job started",
            symbol=request.symbol,
            exchange=request.exchange,
            start_date=request.start_date,
            end_date=request.end_date,
            timeframe=request.timeframe,
        )
    
    @router.get("/backfill/{job_id}/progress", response_model=BackfillProgressResponse, dependencies=[Depends(auth_dep)])
    async def get_backfill_progress(job_id: str) -> BackfillProgressResponse:
        """Get progress of a backfill operation.
        
        Returns current progress including candles inserted, skipped, and any errors.
        """
        if job_id not in _backfill_jobs:
            raise HTTPException(status_code=404, detail=f"Backfill job not found: {job_id}")
        
        job = _backfill_jobs[job_id]
        service = job.get("service")
        
        # Get progress from service
        progress = service.get_progress(job_id) if service else None
        
        if progress:
            return BackfillProgressResponse(
                job_id=job_id,
                status=progress.status,
                total_candles=progress.total_candles,
                inserted_candles=progress.inserted_candles,
                skipped_candles=progress.skipped_candles,
                failed_batches=progress.failed_batches,
                current_date=progress.current_date,
                started_at=progress.started_at,
                finished_at=progress.finished_at,
                error=progress.error,
            )
        
        # Fallback to job status
        return BackfillProgressResponse(
            job_id=job_id,
            status=job.get("status", "unknown"),
            error=job.get("error"),
        )
    
    @router.get("/backfill/{job_id}/result", response_model=BackfillResultResponse, dependencies=[Depends(auth_dep)])
    async def get_backfill_result(job_id: str) -> BackfillResultResponse:
        """Get result of a completed backfill operation.
        
        Returns final statistics including total candles processed, inserted, and duration.
        """
        if job_id not in _backfill_jobs:
            raise HTTPException(status_code=404, detail=f"Backfill job not found: {job_id}")
        
        job = _backfill_jobs[job_id]
        result = job.get("result")
        
        if not result:
            raise HTTPException(status_code=400, detail=f"Backfill job not completed: {job_id}")
        
        return BackfillResultResponse(
            job_id=job_id,
            **result,
        )
    
    @router.post("/backfill/gap", response_model=BackfillResponse, dependencies=[Depends(auth_dep)])
    async def backfill_gap(
        request: GapBackfillRequest,
        background_tasks: BackgroundTasks,
        pool=Depends(dashboard_pool_dep),
    ) -> BackfillResponse:
        """Backfill a specific data gap.
        
        Convenience endpoint for backfilling gaps detected by the data quality system.
        """
        from quantgambit.backtesting.data_backfill import DataBackfillService
        
        # Generate job ID using gap_id
        job_id = f"backfill:gap:{request.gap_id}:{uuid.uuid4().hex[:8]}"
        
        # Create service and store reference
        service = DataBackfillService(pool)
        _backfill_jobs[job_id] = {
            "service": service,
            "status": "pending",
            "gap_id": request.gap_id,
            "request": request.model_dump(),
        }
        
        async def run_backfill():
            try:
                _backfill_jobs[job_id]["status"] = "running"
                result = await service.backfill(
                    symbol=request.symbol,
                    exchange=request.exchange,
                    start_date=request.start_time,
                    end_date=request.end_time,
                    timeframe=request.timeframe,
                    job_id=job_id,
                )
                _backfill_jobs[job_id]["result"] = result.to_dict()
                _backfill_jobs[job_id]["status"] = result.status
            except Exception as e:
                logger.exception(f"Gap backfill job {job_id} failed: {e}")
                _backfill_jobs[job_id]["status"] = "failed"
                _backfill_jobs[job_id]["error"] = str(e)
        
        # Run in background
        background_tasks.add_task(run_backfill)
        
        return BackfillResponse(
            job_id=job_id,
            status="pending",
            message=f"Gap backfill started for gap {request.gap_id}",
            symbol=request.symbol,
            exchange=request.exchange,
            start_date=request.start_time,
            end_date=request.end_time,
            timeframe=request.timeframe,
        )
    
    @router.get("/backfill/jobs", dependencies=[Depends(auth_dep)])
    async def list_backfill_jobs() -> Dict[str, Any]:
        """List all backfill jobs and their status."""
        jobs = []
        for job_id, job in _backfill_jobs.items():
            jobs.append({
                "job_id": job_id,
                "status": job.get("status", "unknown"),
                "request": job.get("request"),
                "gap_id": job.get("gap_id"),
                "error": job.get("error"),
            })
        return {"jobs": jobs, "total": len(jobs)}
    
    # ========================================================================
    # Trading Pipeline Integration Endpoints
    # Feature: trading-pipeline-integration
    # ========================================================================
    
    class WarmStartResponse(BaseModel):
        """Response model for warm start state.
        
        Feature: trading-pipeline-integration
        **Validates: Requirements 3.1**
        """
        snapshot_time: str = Field(..., description="When the snapshot was taken")
        positions: List[Dict[str, Any]] = Field(default_factory=list, description="Open positions")
        account_state: Dict[str, Any] = Field(default_factory=dict, description="Account state")
        candle_history: Dict[str, List[Dict[str, Any]]] = Field(default_factory=dict, description="Candle history by symbol")
        pipeline_state: Dict[str, Any] = Field(default_factory=dict, description="Pipeline state")
        is_stale: bool = Field(..., description="Whether the snapshot is stale (>5 minutes old)")
        age_seconds: float = Field(..., description="Age of the snapshot in seconds")
        is_valid: bool = Field(..., description="Whether the state passed validation")
        validation_errors: List[str] = Field(default_factory=list, description="Validation error messages")
    
    class ConfigDiffResponse(BaseModel):
        """Response model for configuration diff.
        
        Feature: trading-pipeline-integration
        **Validates: Requirements 1.4**
        """
        source_version: str = Field(..., description="Source configuration version ID")
        target_version: str = Field(..., description="Target configuration version ID (backtest)")
        critical_diffs: List[Dict[str, Any]] = Field(default_factory=list, description="Critical parameter differences")
        warning_diffs: List[Dict[str, Any]] = Field(default_factory=list, description="Warning parameter differences")
        info_diffs: List[Dict[str, Any]] = Field(default_factory=list, description="Info parameter differences")
        has_critical_diffs: bool = Field(..., description="Whether there are critical differences")
        total_diffs: int = Field(..., description="Total number of differences")
    
    class MetricComparisonItem(BaseModel):
        """Single metric comparison item."""
        live: float = Field(..., description="Live metric value")
        backtest: float = Field(..., description="Backtest metric value")
        diff_pct: float = Field(..., description="Percentage difference")
        significant: bool = Field(..., description="Whether difference is significant (>10%)")
    
    class CompareLiveResponse(BaseModel):
        """Response model for live vs backtest comparison.
        
        Feature: trading-pipeline-integration
        **Validates: Requirements 9.3**
        """
        backtest_run_id: str = Field(..., description="Backtest run ID")
        comparison_timestamp: str = Field(..., description="When the comparison was performed")
        overall_similarity: float = Field(..., description="Overall similarity score (0-1)")
        significant_differences: Dict[str, MetricComparisonItem] = Field(
            default_factory=dict, 
            description="Metrics with significant differences (>10%)"
        )
        divergence_factors: List[str] = Field(
            default_factory=list, 
            description="Identified factors contributing to divergence"
        )
        live_metrics: Dict[str, Any] = Field(default_factory=dict, description="Live trading metrics")
        backtest_metrics: Dict[str, Any] = Field(default_factory=dict, description="Backtest metrics")
    
    @router.post("/backtest/warm-start", response_model=WarmStartResponse, dependencies=[Depends(auth_dep)])
    async def get_warm_start_state(
        redis_client=Depends(redis_client_dep),
        timescale_pool=Depends(timescale_pool_dep) if timescale_pool_dep else None,
    ) -> WarmStartResponse:
        """Load current live state for warm starting a backtest.
        
        Retrieves the current live trading state from Redis and TimescaleDB,
        including positions, account state, and candle history. This state
        can be used to initialize a backtest from the current market position.
        
        Feature: trading-pipeline-integration
        **Validates: Requirements 3.1**
        
        Returns:
            WarmStartResponse containing the live state snapshot with validation status.
            
        Raises:
            DatabaseError: If database operation fails
        """
        from quantgambit.integration.warm_start import WarmStartLoader
        import asyncpg
        
        try:
            # Build timescale connection if not provided via dependency
            pool = timescale_pool
            pool_created = False
            
            if pool is None:
                pool = await asyncpg.create_pool(**_timescale_connect_kwargs(), min_size=1, max_size=3)
                pool_created = True
            
            try:
                # Create warm start loader
                loader = WarmStartLoader(
                    redis_client=redis_client,
                    timescale_pool=pool,
                    tenant_id=default_tenant,
                    bot_id=default_bot,
                )
                
                # Load current state
                state = await loader.load_current_state()
                
                # Validate state
                is_valid, validation_errors = state.validate()
                
                # Serialize candle history (handle datetime objects)
                serialized_candle_history = {}
                for symbol, candles in state.candle_history.items():
                    serialized_candles = []
                    for candle in candles:
                        serialized_candle = {}
                        for key, value in candle.items():
                            if hasattr(value, 'isoformat'):
                                serialized_candle[key] = value.isoformat()
                            else:
                                serialized_candle[key] = value
                        serialized_candles.append(serialized_candle)
                    serialized_candle_history[symbol] = serialized_candles
                
                return WarmStartResponse(
                    snapshot_time=state.snapshot_time.isoformat(),
                    positions=state.positions,
                    account_state=state.account_state,
                    candle_history=serialized_candle_history,
                    pipeline_state=state.pipeline_state,
                    is_stale=state.is_stale(),
                    age_seconds=state.get_age_seconds(),
                    is_valid=is_valid,
                    validation_errors=validation_errors,
                )
            finally:
                if pool_created and pool:
                    await pool.close()
                    
        except Exception as e:
            logger.exception(f"Error loading warm start state: {e}")
            raise DatabaseError("loading warm start state")
    
    @router.get("/backtests/{run_id}/config-diff", response_model=ConfigDiffResponse, dependencies=[Depends(auth_dep)])
    async def get_config_diff(
        run_id: str,
        pool=Depends(dashboard_pool_dep),
        redis_client=Depends(redis_client_dep),
        timescale_pool=Depends(timescale_pool_dep) if timescale_pool_dep else None,
    ) -> ConfigDiffResponse:
        """Get configuration diff between live and backtest config.
        
        Returns the configuration differences between the current live
        configuration and the configuration used for the specified backtest.
        Differences are categorized as critical, warning, or info.
        
        Feature: trading-pipeline-integration
        **Validates: Requirements 1.4**
        
        Args:
            run_id: Backtest run ID to compare against live config
            
        Returns:
            ConfigDiffResponse with categorized configuration differences.
            
        Raises:
            BacktestNotFoundError: If backtest run not found
            DatabaseError: If database operation fails
        """
        from quantgambit.integration.config_registry import ConfigurationRegistry
        from quantgambit.integration.config_diff import ConfigDiffEngine
        from quantgambit.integration.config_version import ConfigVersion
        import asyncpg
        
        try:
            store = BacktestStore(pool)
            
            # Get backtest run
            run = await store.get_run(run_id)
            if not run:
                raise BacktestNotFoundError(run_id)
            
            # Get backtest config from run
            backtest_config_params = run.config or {}
            
            # Build timescale connection if not provided via dependency
            ts_pool = timescale_pool
            pool_created = False
            
            if ts_pool is None:
                ts_pool = await asyncpg.create_pool(**_timescale_connect_kwargs(), min_size=1, max_size=3)
                pool_created = True
            
            try:
                # Create configuration registry
                registry = ConfigurationRegistry(ts_pool, redis_client)
                
                # Get live config
                live_config = await registry.get_live_config()
                
                # Create backtest config version for comparison
                backtest_config = ConfigVersion(
                    version_id=f"backtest_{run_id[:8]}",
                    created_at=datetime.now(timezone.utc),
                    created_by="backtest",
                    config_hash="",
                    parameters=backtest_config_params,
                )
                
                # Compare configs
                diff_engine = ConfigDiffEngine()
                diff = diff_engine.compare(live_config, backtest_config)
                
                return ConfigDiffResponse(
                    source_version=diff.source_version,
                    target_version=diff.target_version,
                    critical_diffs=[
                        {"key": k, "old": o, "new": n}
                        for k, o, n in diff.critical_diffs
                    ],
                    warning_diffs=[
                        {"key": k, "old": o, "new": n}
                        for k, o, n in diff.warning_diffs
                    ],
                    info_diffs=[
                        {"key": k, "old": o, "new": n}
                        for k, o, n in diff.info_diffs
                    ],
                    has_critical_diffs=diff.has_critical_diffs,
                    total_diffs=diff.total_diffs,
                )
            finally:
                if pool_created and ts_pool:
                    await ts_pool.close()
                    
        except APIError:
            raise
        except Exception as e:
            logger.exception(f"Error getting config diff: {e}")
            raise DatabaseError("getting config diff")
    
    @router.post("/backtests/{run_id}/compare-live", response_model=CompareLiveResponse, dependencies=[Depends(auth_dep)])
    async def compare_backtest_with_live(
        run_id: str,
        request: CompareLiveRequest = Body(default_factory=CompareLiveRequest),
        pool=Depends(dashboard_pool_dep),
    ) -> CompareLiveResponse:
        """Compare backtest metrics with live trading metrics.
        
        Uses MetricsReconciler to compute a comparison between the backtest
        results and live trading performance over the same period. Returns
        divergence factors and significant differences.
        
        Feature: trading-pipeline-integration
        **Validates: Requirements 9.3**
        
        Args:
            run_id: Backtest run ID to compare
            request: Optional date range for live metrics
            
        Returns:
            CompareLiveResponse with metrics comparison and divergence analysis.
            
        Raises:
            BacktestNotFoundError: If backtest run not found
            DatabaseError: If database operation fails
        """
        from quantgambit.integration.unified_metrics import MetricsReconciler, UnifiedMetrics
        
        try:
            store = BacktestStore(pool)
            
            # Get backtest run
            run = await store.get_run(run_id)
            if not run:
                raise BacktestNotFoundError(run_id)
            
            # Get backtest metrics
            metrics_record = await store.get_metrics(run_id)
            
            # Build backtest UnifiedMetrics from stored metrics
            backtest_metrics = UnifiedMetrics(
                total_return_pct=metrics_record.total_return_pct if metrics_record else 0.0,
                annualized_return_pct=0.0,  # Not stored in current schema
                sharpe_ratio=metrics_record.sharpe_ratio if metrics_record else 0.0,
                sortino_ratio=metrics_record.sortino_ratio if metrics_record else 0.0,
                max_drawdown_pct=metrics_record.max_drawdown_pct if metrics_record else 0.0,
                max_drawdown_duration_sec=0.0,  # Not stored in current schema
                total_trades=metrics_record.total_trades if metrics_record else 0,
                winning_trades=metrics_record.winning_trades if metrics_record else 0,
                losing_trades=metrics_record.losing_trades if metrics_record else 0,
                win_rate=metrics_record.win_rate if metrics_record else 0.0,
                profit_factor=metrics_record.profit_factor if metrics_record else 0.0,
                avg_trade_pnl=metrics_record.avg_trade_pnl if metrics_record else 0.0,
                avg_win_pct=0.0,  # Not stored in current schema
                avg_loss_pct=0.0,  # Not stored in current schema
                avg_slippage_bps=metrics_record.avg_slippage_bps if metrics_record else 0.0,
                avg_latency_ms=0.0,  # Not stored in current schema
                partial_fill_rate=0.0,  # Not stored in current schema
            )
            
            # For live metrics, we would query from live trading data
            # For now, create placeholder live metrics (in production, this would
            # query from recorded_decisions and live trade history)
            # TODO: Implement actual live metrics retrieval from TimescaleDB
            live_metrics = UnifiedMetrics(
                total_return_pct=0.0,
                annualized_return_pct=0.0,
                sharpe_ratio=0.0,
                sortino_ratio=0.0,
                max_drawdown_pct=0.0,
                max_drawdown_duration_sec=0.0,
                total_trades=0,
                winning_trades=0,
                losing_trades=0,
                win_rate=0.0,
                profit_factor=0.0,
                avg_trade_pnl=0.0,
                avg_win_pct=0.0,
                avg_loss_pct=0.0,
                avg_slippage_bps=0.0,
                avg_latency_ms=0.0,
                partial_fill_rate=0.0,
            )
            
            # Compare metrics using MetricsReconciler
            reconciler = MetricsReconciler()
            comparison = reconciler.compare_metrics(live_metrics, backtest_metrics)
            
            # Convert significant differences to response format
            significant_diffs = {}
            for metric_name, diff_info in comparison.significant_differences.items():
                significant_diffs[metric_name] = MetricComparisonItem(
                    live=diff_info.get("live", 0.0),
                    backtest=diff_info.get("backtest", 0.0),
                    diff_pct=diff_info.get("diff_pct", 0.0),
                    significant=diff_info.get("significant", False),
                )
            
            return CompareLiveResponse(
                backtest_run_id=run_id,
                comparison_timestamp=comparison.comparison_timestamp.isoformat(),
                overall_similarity=comparison.overall_similarity,
                significant_differences=significant_diffs,
                divergence_factors=comparison.divergence_factors,
                live_metrics=live_metrics.to_dict(),
                backtest_metrics=backtest_metrics.to_dict(),
            )
            
        except APIError:
            raise
        except Exception as e:
            logger.exception(f"Error comparing backtest with live: {e}")
            raise DatabaseError("comparing backtest with live")

    @router.post(
        "/model-training/jobs",
        response_model=StartModelTrainingResponse,
        dependencies=[Depends(auth_dep)],
    )
    async def start_model_training_job(
        request: StartModelTrainingRequest,
        background_tasks: BackgroundTasks,
    ) -> StartModelTrainingResponse:
        """Start ONNX model retraining job and capture artifacts/metrics."""
        job_id = str(uuid.uuid4())
        tenant_id = request.tenant_id or default_tenant or None
        bot_id = request.bot_id or default_bot or None
        started_at = _iso_now()
        job = {
            "id": job_id,
            "status": "queued",
            "started_at": started_at,
            "finished_at": None,
            "label_source": request.label_source,
            "stream": request.stream,
            "tenant_id": tenant_id,
            "bot_id": bot_id,
            "request": request.model_dump(),
            "command": [],
            "stdout_tail": [],
            "stderr_tail": [],
            "exit_code": None,
            "artifacts": [],
            "summary": {},
        }
        _MODEL_TRAINING_JOBS[job_id] = job
        _persist_model_training_jobs_to_disk()

        async def _run_job() -> None:
            project_root = _project_root()
            registry_dir = project_root / "models" / "registry"
            registry_dir.mkdir(parents=True, exist_ok=True)
            python_bin = _pick_python_bin(project_root)

            if request.use_v4_pipeline:
                # v4 pipeline: train_from_collected.py with trade-record labeling
                ts_tag = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
                model_out = str(registry_dir / f"prediction_baseline_{ts_tag}.onnx")
                config_out = str(registry_dir / f"prediction_baseline_{ts_tag}.json")
                cmd = [
                    python_bin,
                    "scripts/train_from_collected.py",
                    "--input", "features_collected.csv",
                    "--model-output", model_out,
                    "--config-output", config_out,
                    "--horizon-sec", str(request.horizon_sec),
                    "--tp-bps", str(request.tp_bps),
                    "--sl-bps", str(request.sl_bps),
                ]
            else:
                # Legacy pipeline
                cmd = [
                    python_bin,
                    "scripts/retrain_prediction_baseline.py",
                    "--stream",
                    request.stream,
                    "--label-source",
                    request.label_source,
                    "--limit",
                    str(request.limit),
                    "--walk-forward-folds",
                    str(request.walk_forward_folds),
                    "--min-directional-f1",
                    str(request.min_directional_f1),
                    "--min-ev-after-costs",
                    str(request.min_ev_after_costs),
                    "--min-directional-f1-delta",
                    str(request.min_directional_f1_delta),
                    "--min-ev-delta",
                    str(request.min_ev_delta),
                ]
                if request.keep_dataset:
                    cmd.append("--keep-dataset")
                if request.drift_check:
                    cmd.append("--drift-check")
                if request.allow_regression:
                    cmd.append("--allow-regression")
                if request.hours is not None:
                    cmd.extend(["--hours", str(request.hours)])
                if request.redis_url:
                    cmd.extend(["--redis-url", request.redis_url])
                if tenant_id and bot_id:
                    cmd.extend(["--tenant-id", str(tenant_id), "--bot-id", str(bot_id)])

            before_stats = {}
            if registry_dir.exists():
                for p in registry_dir.glob("*"):
                    try:
                        before_stats[p.name] = p.stat().st_mtime
                    except Exception:
                        continue

            job["status"] = "running"
            job["command"] = cmd
            _persist_model_training_jobs_to_disk()
            try:
                exit_code, stdout, stderr = await asyncio.to_thread(
                    _run_training_subprocess,
                    cmd,
                    str(project_root),
                )
                job["exit_code"] = exit_code
                job["stdout_tail"] = stdout.splitlines()[-300:]
                job["stderr_tail"] = stderr.splitlines()[-300:]
                job["summary"] = _parse_training_summary(f"{stdout}\n{stderr}")
                job["promotion_status"] = job["summary"].get("promotion_status")

                artifact_lines = []
                for line in stdout.splitlines():
                    text = line.strip()
                    if text.startswith(("written:", "registered:", "latest:", "config:")):
                        artifact_lines.append(text)
                artifacts = [{"line": line} for line in artifact_lines]

                after_artifacts = []
                if registry_dir.exists():
                    for p in registry_dir.glob("*"):
                        try:
                            after_mtime = p.stat().st_mtime
                        except Exception:
                            continue
                        before_mtime = before_stats.get(p.name, 0.0)
                        if p.name not in before_stats or after_mtime > before_mtime:
                            after_artifacts.append(
                                {
                                    "name": p.name,
                                    "path": str(p),
                                    "updated_at": datetime.fromtimestamp(after_mtime, timezone.utc).isoformat(),
                                    "size_bytes": p.stat().st_size,
                                }
                            )
                job["artifacts"] = after_artifacts + artifacts
                if exit_code == 0:
                    job["status"] = "completed"
                elif str(job.get("promotion_status") or "") == "blocked":
                    job["status"] = "blocked"
                else:
                    job["status"] = "failed"
            except Exception as exc:
                job["status"] = "failed"
                job["stderr_tail"] = (job.get("stderr_tail") or []) + [str(exc)]
            finally:
                job["finished_at"] = _iso_now()
                _persist_model_training_jobs_to_disk()

        background_tasks.add_task(_run_job)
        return StartModelTrainingResponse(
            success=True,
            job=ModelTrainingJobSummary(
                id=job_id,
                status=job["status"],
                started_at=started_at,
                finished_at=None,
                label_source=request.label_source,
                stream=request.stream,
                tenant_id=tenant_id,
                bot_id=bot_id,
                exit_code=None,
                promotion_status=None,
            ),
        )

    @router.get(
        "/model-training/active",
        response_model=ActiveModelInfoResponse,
        dependencies=[Depends(auth_dep)],
    )
    async def get_active_model_info() -> ActiveModelInfoResponse:
        project_root = _project_root()
        registry_dir = project_root / "models" / "registry"
        latest_json = registry_dir / "latest.json"
        pointer = _latest_pointer(registry_dir)
        current = pointer.get("current") or {}
        pointer_updated_at = pointer.get("updated_at")

        payload: dict[str, Any] = {}
        if latest_json.exists():
            try:
                payload = json.loads(latest_json.read_text(encoding="utf-8"))
            except Exception:
                payload = {}

        promotion = payload.get("promotion") if isinstance(payload, dict) else {}
        if not isinstance(promotion, dict):
            promotion = {}

        promoted_at = promotion.get("manual_promoted_at") or promotion.get("promoted_at")
        promoted_from_job_id = promotion.get("manual_promoted_from_job_id")
        source_model_file = promotion.get("source_model_file")
        source_config_file = promotion.get("source_config_file")

        return ActiveModelInfoResponse(
            model_file=current.get("model"),
            config_file=current.get("config"),
            promoted_at=promoted_at,
            promoted_from_job_id=promoted_from_job_id,
            source_model_file=source_model_file,
            source_config_file=source_config_file,
            pointer_updated_at=pointer_updated_at,
        )

    @router.get(
        "/model-training/jobs",
        response_model=list[ModelTrainingJobSummary],
        dependencies=[Depends(auth_dep)],
    )
    async def list_model_training_jobs(
        limit: int = Query(20, ge=1, le=200),
    ) -> list[ModelTrainingJobSummary]:
        jobs = sorted(
            _MODEL_TRAINING_JOBS.values(),
            key=lambda item: item.get("started_at") or "",
            reverse=True,
        )[:limit]
        return [
            ModelTrainingJobSummary(
                id=j["id"],
                status=j["status"],
                started_at=j["started_at"],
                finished_at=j.get("finished_at"),
                label_source=j["label_source"],
                stream=j["stream"],
                tenant_id=j.get("tenant_id"),
                bot_id=j.get("bot_id"),
                exit_code=j.get("exit_code"),
                promotion_status=j.get("promotion_status"),
            )
            for j in jobs
        ]

    @router.get(
        "/model-training/jobs/{job_id}",
        dependencies=[Depends(auth_dep)],
    )
    async def get_model_training_job(job_id: str) -> dict[str, Any]:
        job = _MODEL_TRAINING_JOBS.get(job_id)
        if not job:
            raise NotFoundError("Model training job", job_id)
        return {"job": job}

    @router.post(
        "/model-training/jobs/{job_id}/promote",
        response_model=PromoteModelTrainingJobResponse,
        dependencies=[Depends(auth_dep)],
    )
    async def promote_model_training_job(
        job_id: str,
        request: PromoteModelTrainingJobRequest = Body(default_factory=PromoteModelTrainingJobRequest),
    ) -> PromoteModelTrainingJobResponse:
        """Manually promote produced training artifacts to latest.{onnx,json}."""
        job = _MODEL_TRAINING_JOBS.get(job_id)
        if not job:
            raise NotFoundError("Model training job", job_id)
        if str(job.get("status")) in {"queued", "running"}:
            raise ValidationError("Training job is still running and cannot be promoted yet.")
        if str(job.get("status")) == "failed":
            raise ValidationError("Failed job cannot be promoted.")

        project_root = _project_root()
        registry_dir = project_root / "models" / "registry"
        registry_dir.mkdir(parents=True, exist_ok=True)
        latest_onnx = registry_dir / "latest.onnx"
        latest_json = registry_dir / "latest.json"

        try:
            source_onnx, source_config = _select_promotable_artifacts(job)
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc

        if not source_onnx.exists() or not source_config.exists():
            raise ValidationError("Selected source artifacts are missing on disk.")

        payload: dict[str, Any]
        try:
            payload = json.loads(source_config.read_text(encoding="utf-8"))
        except Exception as exc:
            raise ValidationError("Could not parse source config JSON for promotion.") from exc

        pointer = _latest_pointer(registry_dir)
        previous_current = pointer.get("current") or {}
        ts = _iso_now()
        payload["onnx_path"] = "models/registry/latest.onnx"
        payload["promotion"] = {
            **(payload.get("promotion") or {}),
            "manual_promoted_at": ts,
            "manual_promoted_from_job_id": job_id,
            "source_model_file": source_onnx.name,
            "source_config_file": source_config.name,
            "previous_model_file": previous_current.get("model"),
            "previous_config_file": previous_current.get("config"),
            "notes": request.notes,
        }

        shutil.copy2(source_onnx, latest_onnx)
        latest_json.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

        pointer_payload = {
            "updated_at": ts,
            "current": {"model": source_onnx.name, "config": source_config.name},
            "previous": {
                "model": previous_current.get("model"),
                "config": previous_current.get("config"),
            },
        }
        (registry_dir / "latest_pointer.json").write_text(
            json.dumps(pointer_payload, indent=2, sort_keys=True),
            encoding="utf-8",
        )

        job["manual_promotion"] = {
            "promoted_at": ts,
            "source_model_file": source_onnx.name,
            "source_config_file": source_config.name,
            "notes": request.notes,
        }
        _persist_model_training_jobs_to_disk()

        return PromoteModelTrainingJobResponse(
            success=True,
            job_id=job_id,
            source_model_file=source_onnx.name,
            source_config_file=source_config.name,
            latest_model_path=str(latest_onnx),
            latest_config_path=str(latest_json),
        )

    return router
from quantgambit.execution.symbols import to_storage_symbol
