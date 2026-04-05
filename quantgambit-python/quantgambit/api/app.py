"""FastAPI application exposing runtime/status endpoints for quantgambit."""

from __future__ import annotations

import asyncio
from bisect import bisect_left
import hashlib
import json
import logging
import math
import os
import re
import ssl
import time
import uuid
from datetime import datetime, timezone, timedelta

# Configure logging so copilot engine (and other modules) emit to stdout/stderr.
# PM2 captures stdout/stderr, so this makes ReAct loop logs visible in PM2 logs.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import FastAPI, Depends, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

import asyncpg
import redis.asyncio as redis

from quantgambit.auth.jwt_auth import build_auth_dependency, build_auth_dependency_with_claims, UserClaims, _verify_jwt
from quantgambit.observability.logger import log_warning, log_info
from quantgambit.storage.redis_snapshots import RedisSnapshotReader
from quantgambit.storage.redis_streams import RedisStreamsClient, Command, command_stream_name, control_command_stream_name
from quantgambit.storage.timescale import TimescaleReader
from quantgambit.runtime.entrypoint import _build_timescale_url
from quantgambit.execution.symbols import normalize_exchange_symbol, to_ccxt_market_symbol, to_storage_symbol
from quantgambit.control.command_manager import preview_runtime_env_parity, export_runtime_env
from quantgambit.api.quant_endpoints import router as quant_router
from quantgambit.api.ev_gate_endpoints import router as ev_gate_router
from quantgambit.api.backtest_endpoints import create_backtest_router
from quantgambit.api.replay_endpoints import router as replay_router, set_replay_manager
from quantgambit.api.copilot_endpoints import create_copilot_router
from quantgambit.api.diagnostics_endpoints import router as diagnostics_router
from quantgambit.api.shadow_endpoints import router as shadow_router
from quantgambit.api.docs_endpoints import create_docs_router
from quantgambit.api.runtime_knobs import knob_catalog, merge_runtime_config
from quantgambit.docs.loader import DocLoader
from quantgambit.docs.search import DocSearchIndex
from quantgambit.config.loss_prevention import load_loss_prevention_config
from quantgambit.integration.replay_validation import ReplayManager
from quantgambit.signals.decision_engine import DecisionEngine

DASHBOARD_POOL = None
_EXCHANGE_BALANCE_CACHE: dict[str, tuple[float, float]] = {}
_EXCHANGE_BALANCE_LAST_ATTEMPT: dict[str, float] = {}
_EXCHANGE_BALANCE_FETCH_LOCKS: dict[str, asyncio.Lock] = {}
_DASHBOARD_METRICS_CACHE: dict[str, tuple[dict[str, Any], float]] = {}
_REPLAY_SESSIONS: dict[str, dict[str, Any]] = {}
_REPLAY_ANNOTATIONS: dict[str, list[dict[str, Any]]] = {}
_VIEWER_ALLOWED_READ_PATHS = (
    "/api/monitoring/fast-scalper",
    "/api/python/bot/status",
    "/api/dashboard/state",
    "/api/dashboard/live-status",
    "/api/dashboard/trading",
    "/api/dashboard/metrics",
    "/api/dashboard/positions",
    "/api/dashboard/trade-history",
    "/api/dashboard/drawdown",
    "/api/bot-instances/",
    "/api/bot-config/bots/",
    "/api/quant/pipeline/health",
)
_VIEWER_PATH_BOT_PATTERNS = (
    re.compile(r"^/api/bot-instances/([0-9a-fA-F-]{36})$"),
    re.compile(r"^/api/bot-config/bots/([0-9a-fA-F-]{36})$"),
)


class _ReplayConfigRegistryStub:
    async def get_live_config(self) -> dict[str, Any]:
        return {}


async def _ensure_replay_tables(pool: asyncpg.Pool) -> None:
    """Ensure replay report storage exists before enabling replay endpoints."""
    async with pool.acquire() as conn:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS replay_validations (
                run_id TEXT PRIMARY KEY,
                run_at TIMESTAMPTZ NOT NULL,
                start_time TIMESTAMPTZ,
                end_time TIMESTAMPTZ,
                total_replayed INTEGER NOT NULL DEFAULT 0,
                matches INTEGER NOT NULL DEFAULT 0,
                changes INTEGER NOT NULL DEFAULT 0,
                match_rate DOUBLE PRECISION NOT NULL DEFAULT 1.0,
                changes_by_category JSONB NOT NULL DEFAULT '{}'::jsonb,
                changes_by_stage JSONB NOT NULL DEFAULT '{}'::jsonb
            )
            """
        )


async def _maybe_initialize_replay_manager() -> None:
    enabled = os.getenv("ENABLE_REPLAY_VALIDATION_API", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    if not enabled:
        set_replay_manager(None)
        return

    try:
        pool = await _get_timescale_pool()
        await _ensure_replay_tables(pool)
        async with pool.acquire() as conn:
            has_recorded_decisions = await conn.fetchval(
                "SELECT to_regclass('public.recorded_decisions') IS NOT NULL"
            )
        if not has_recorded_decisions:
            set_replay_manager(None)
            log_warning(
                "replay_manager_disabled_missing_table",
                table="recorded_decisions",
            )
            return

        loss_prevention_config = load_loss_prevention_config()
        engine = DecisionEngine(
            backtesting_mode=True,
            ev_gate_config=loss_prevention_config.ev_gate,
            ev_position_sizer_config=loss_prevention_config.ev_position_sizer,
            cost_data_quality_config=loss_prevention_config.cost_data_quality,
        )
        manager = ReplayManager(pool, engine, _ReplayConfigRegistryStub())
        set_replay_manager(manager)
        log_info("replay_manager_enabled")
    except Exception as exc:
        set_replay_manager(None)
        log_warning("replay_manager_init_failed", error=str(exc))


class RuntimeQualityResponse(BaseModel):
    orderbook_sync_state: str
    trade_sync_state: str
    quality_score: float | None = None
    quality_flags: list[str] | None = None
    active_provider: str | None = None
    switch_count: int | None = None
    last_switch_at: float | None = None
    control_state: dict[str, Any] | None = None
    risk_snapshot: dict[str, Any] | None = None


class RiskSizingResponse(BaseModel):
    status: str | None = None
    rejection_reason: str | None = None
    symbol: str | None = None
    size_usd: float | None = None
    risk_budget_usd: float | None = None
    risk_multiplier: float | None = None
    total_exposure_usd: float | None = None
    total_exposure_pct: float | None = None
    long_exposure_usd: float | None = None
    short_exposure_usd: float | None = None
    net_exposure_usd: float | None = None
    net_exposure_pct: float | None = None
    symbol_exposure_usd: float | None = None
    strategy_exposure_usd: float | None = None
    account_equity: float | None = None
    overrides: dict[str, Any] | None = None
    limits: dict[str, Any] | None = None
    remaining: dict[str, Any] | None = None
    exposure: dict[str, Any] | None = None
    config: dict[str, Any] | None = None


class SnapshotResponse(BaseModel):
    payload: dict[str, Any] | None = None


class EventsResponse(BaseModel):
    items: list[dict[str, Any]]
    total: int


class ConfigDriftResponse(BaseModel):
    stored_version: int | None = None
    runtime_version: int | None = None
    drift: bool = False
    timestamp: float | None = None


class BacktestSummary(BaseModel):
    id: str
    name: str | None = None
    status: str | None = None
    started_at: float | None = None
    completed_at: float | None = None


class BacktestDetail(BaseModel):
    id: str
    name: str | None = None
    status: str | None = None
    started_at: float | None = None
    completed_at: float | None = None
    equity_curve: list[dict[str, Any]] | None = None
    decisions: list[dict[str, Any]] | None = None
    fills: list[dict[str, Any]] | None = None
    # Optional: include metrics if needed
    metrics: dict[str, Any] | None = None


class MonitoringAlertsResponse(BaseModel):
    timestamp: str
    alerts: list[dict[str, Any]]
    warnings: list[dict[str, Any]]
    total: int


class MonitoringDashboardResponse(BaseModel):
    timestamp: str
    uptime: int
    nodejs: dict[str, Any]
    python: dict[str, Any]
    redis: dict[str, Any]
    health: str


class FastScalperRejectionsResponse(BaseModel):
    recent: list[dict[str, Any]]
    counts: dict[str, int]
    timestamp: str


class FastScalperLogsResponse(BaseModel):
    logs: list[str]
    timestamp: str


class BotStatusResponse(BaseModel):
    platform: dict[str, Any]
    trading: dict[str, Any]
    stats: dict[str, Any]
    workers: dict[str, Any]
    dbBotStatus: dict[str, Any] | None = None


class TradingSnapshotResponse(BaseModel):
    positions: list[dict[str, Any]]
    pendingOrders: list[dict[str, Any]]
    metrics: dict[str, Any]
    execution: dict[str, Any]
    risk: dict[str, Any]
    exchangeStatus: dict[str, Any]
    performance: dict[str, Any]
    recentTrades: list[dict[str, Any]]
    updatedAt: int
    strategies: list[dict[str, Any]] | None = None


class SignalLabSnapshotResponse(BaseModel):
    stageRejections: dict[str, Any]
    featureHealth: dict[str, Any]
    componentDiagnostics: dict[str, Any]
    allocator: dict[str, Any]
    bladeStatus: dict[str, Any]
    bladeSignals: dict[str, Any]
    bladeMetrics: dict[str, Any]
    eventBus: dict[str, Any]
    recentDecisions: list[dict[str, Any]]
    updatedAt: int


def _window_to_minutes(window: str | None, fallback_minutes: int = 60) -> tuple[str, int]:
    if not window:
        return f"{fallback_minutes}m", fallback_minutes
    raw = str(window).strip().lower()
    presets = {
        "15m": 15,
        "1h": 60,
        "6h": 360,
        "24h": 1440,
    }
    if raw in presets:
        return raw, presets[raw]
    try:
        if raw.endswith("m"):
            mins = max(1, int(raw[:-1]))
            return f"{mins}m", mins
        if raw.endswith("h"):
            mins = max(1, int(raw[:-1])) * 60
            return raw, mins
        mins = max(1, int(raw))
        return f"{mins}m", mins
    except (TypeError, ValueError):
        return f"{fallback_minutes}m", fallback_minutes


def _to_iso8601(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        dt = value
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat()
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value), tz=timezone.utc).isoformat()
        except Exception:
            return None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            if text.endswith("Z"):
                text = text[:-1] + "+00:00"
            dt = datetime.fromisoformat(text)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc).isoformat()
        except Exception:
            return value
    return None


def _coerce_json_dict(value: Any) -> dict[str, Any]:
    current = value
    for _ in range(3):
        if isinstance(current, dict):
            return current
        if isinstance(current, (bytes, bytearray, memoryview)):
            try:
                current = bytes(current).decode("utf-8", errors="ignore")
                continue
            except Exception:
                return {}
        if isinstance(current, str):
            text = current.strip()
            if not text:
                return {}
            try:
                current = json.loads(text)
                continue
            except Exception:
                return {}
        if hasattr(current, "items"):
            try:
                return dict(current)
            except Exception:
                return {}
        return {}
    return {}


def _coerce_json_list(value: Any) -> list[Any]:
    current = value
    for _ in range(3):
        if isinstance(current, list):
            return list(current)
        if isinstance(current, tuple):
            return list(current)
        if isinstance(current, (bytes, bytearray, memoryview)):
            try:
                current = bytes(current).decode("utf-8", errors="ignore")
                continue
            except Exception:
                return []
        if isinstance(current, str):
            text = current.strip()
            if not text:
                return []
            try:
                current = json.loads(text)
                continue
            except Exception:
                return []
        return []
    return []


def _parse_env_text(value: str) -> dict[str, str]:
    env: dict[str, str] = {}
    for line in str(value or "").splitlines():
        text = line.strip()
        if not text or text.startswith("#"):
            continue
        if text.startswith("export "):
            text = text[len("export ") :].strip()
        if "=" not in text:
            continue
        key, raw = text.split("=", 1)
        key = key.strip()
        raw = raw.strip().strip('"').strip("'")
        if key:
            env[key] = raw
    return env


def _coerce_env_value(raw: str) -> Any:
    value = str(raw).strip()
    low = value.lower()
    if low in {"true", "false"}:
        return low == "true"
    try:
        if "." in value:
            return float(value)
        return int(value)
    except Exception:
        return value


def _env_overrides_to_db_patches(env_overrides: dict[str, str]) -> dict[str, Any]:
    risk_patch: dict[str, Any] = {}
    execution_patch: dict[str, Any] = {}
    profile_patch: dict[str, Any] = {}
    enabled_symbols: list[str] | None = None
    trading_capital_usd: float | None = None
    unmapped: list[str] = []
    env_to_target: dict[str, tuple[str, str]] = {
        "RISK_PER_TRADE_PCT": ("risk_config", "risk_per_trade_pct"),
        "MAX_TOTAL_EXPOSURE_PCT": ("risk_config", "max_total_exposure_pct"),
        "MAX_EXPOSURE_PER_SYMBOL_PCT": ("risk_config", "max_exposure_per_symbol_pct"),
        "MAX_POSITIONS": ("risk_config", "max_positions"),
        "MAX_POSITIONS_PER_SYMBOL": ("risk_config", "max_positions_per_symbol"),
        "MAX_DAILY_DRAWDOWN_PCT": ("risk_config", "max_daily_drawdown_pct"),
        "MAX_DRAWDOWN_PCT": ("risk_config", "max_drawdown_pct"),
        "MAX_LEVERAGE": ("risk_config", "max_leverage"),
        "MIN_ORDER_INTERVAL_SEC": ("execution_config", "min_order_interval_sec"),
        "MAX_ORDER_RETRIES": ("execution_config", "max_retries"),
        "ORDER_RETRY_DELAY_SEC": ("execution_config", "retry_delay_sec"),
        "EXECUTION_TIMEOUT_SEC": ("execution_config", "execution_timeout_sec"),
        "MAX_SLIPPAGE_BPS": ("execution_config", "max_slippage_bps"),
        "THROTTLE_MODE": ("execution_config", "throttle_mode"),
        "DEFAULT_STOP_LOSS_PCT": ("execution_config", "default_stop_loss_pct"),
        "DEFAULT_TAKE_PROFIT_PCT": ("execution_config", "default_take_profit_pct"),
        "ORDER_INTENT_MAX_AGE_SEC": ("execution_config", "order_intent_max_age_sec"),
        "POSITION_CONTINUATION_GATE_ENABLED": ("profile_overrides", "position_continuation_gate_enabled"),
        "ENABLE_UNIFIED_CONFIRMATION_POLICY": ("profile_overrides", "enable_unified_confirmation_policy"),
        "PREDICTION_SCORE_GATE_ENABLED": ("profile_overrides", "prediction_score_gate_enabled"),
    }
    ignored_runtime_only = {
        "ACTIVE_EXCHANGE",
        "ORDERBOOK_EXCHANGE",
        "ORDER_UPDATES_EXCHANGE",
        "TRADING_MODE",
        "BOT_CONFIG_VERSION",
        "TRADE_SYMBOLS",
        "MARKET_DATA_SYMBOLS",
        "EXCHANGE_ACCOUNT_ID",
        "LIVE_EQUITY",
        "PAPER_EQUITY",
        "EXECUTION_PROVIDER",
        "DEFAULT_ORDER_TYPE",
        "MAX_HOLD_TIME_HOURS",
        "TRAILING_STOP_PCT",
        "TRAILING_STOP_ENABLED",
        "ENABLE_VOLATILITY_FILTER",
        "LEVERAGE_MODE",
        "MIN_POSITION_SIZE_USD",
        "MAX_DAILY_LOSS_PER_SYMBOL_PCT",
    }
    for raw_key, raw_val in (env_overrides or {}).items():
        key = str(raw_key).strip().upper()
        if not key:
            continue
        if key in ignored_runtime_only:
            continue
        if key == "ORDERBOOK_SYMBOLS":
            enabled_symbols = [s.strip().upper() for s in str(raw_val).split(",") if s.strip()]
            continue
        if key == "TRADING_CAPITAL_USD":
            try:
                trading_capital_usd = float(raw_val)
            except Exception:
                unmapped.append(key)
            continue
        if key == "PROFILE_OVERRIDES":
            parsed = _coerce_json_dict(raw_val)
            for p_key, p_val in parsed.items():
                profile_patch[str(p_key)] = p_val
            continue
        target = env_to_target.get(key)
        if not target:
            unmapped.append(key)
            continue
        section, field_key = target
        value = _coerce_env_value(str(raw_val))
        # DB/runtime env often stores exposure ratios as fractions (0.4 = 40%),
        # while knob validation expects percent-style values (40.0).
        if key in {"MAX_TOTAL_EXPOSURE_PCT", "MAX_EXPOSURE_PER_SYMBOL_PCT"}:
            try:
                num = float(value)
                if 0 < num <= 1:
                    value = num * 100.0
            except Exception:
                pass
        if section == "risk_config":
            risk_patch[field_key] = value
        elif section == "execution_config":
            execution_patch[field_key] = value
        else:
            profile_patch[field_key] = value
    return {
        "risk_patch": risk_patch,
        "execution_patch": execution_patch,
        "profile_patch": profile_patch,
        "enabled_symbols": enabled_symbols,
        "trading_capital_usd": trading_capital_usd,
        "unmapped_env_keys": sorted(set(unmapped)),
    }


def _extract_rejection_stage(payload: dict[str, Any]) -> str | None:
    rejection_detail = payload.get("rejection_detail") if isinstance(payload.get("rejection_detail"), dict) else {}
    stage = payload.get("rejection_stage") or rejection_detail.get("stage") or payload.get("stage")
    stage_text = str(stage).strip().lower() if stage is not None else ""
    if stage_text:
        return stage_text

    # Runtime payloads can omit explicit stage and only provide reason text.
    reason = (_extract_rejection_reason(payload) or "").strip().lower()
    if not reason:
        return None
    if "flow_" in reason or reason.startswith("flow"):
        return "flow_filter"
    if "spread" in reason:
        return "spread_filter"
    if "confirm" in reason:
        return "confirmation"
    if "prediction" in reason or "onnx" in reason or "entropy" in reason:
        return "prediction"
    if "session" in reason:
        return "session_filter"
    if "quality" in reason or "orderbook_gap" in reason or "book_gap" in reason:
        return "quality_filter"
    if (
        "risk" in reason
        or "position_limit" in reason
        or "exposure" in reason
        or "sizing" in reason
        or "kill_switch" in reason
    ):
        return "risk"
    return "unknown"


def _extract_rejection_reason(payload: dict[str, Any]) -> str | None:
    rejection_detail = payload.get("rejection_detail") if isinstance(payload.get("rejection_detail"), dict) else {}
    prediction = payload.get("prediction") if isinstance(payload.get("prediction"), dict) else {}
    reason = (
        payload.get("rejection_reason")
        or rejection_detail.get("reason")
        or prediction.get("reason")
        or payload.get("reason")
    )
    if reason is None:
        return None
    text = str(reason).strip()
    if not text:
        return None
    canonical = text.lower()
    # Backward-compatible typo normalization for historical payloads.
    if canonical == "prediction_missiong":
        return "prediction_missing"
    return text


def _extract_signal(payload: dict[str, Any]) -> dict[str, Any]:
    decision = str(payload.get("decision") or payload.get("result") or "").strip().lower()
    prediction = payload.get("prediction") if isinstance(payload.get("prediction"), dict) else {}
    candidate = payload.get("candidate") if isinstance(payload.get("candidate"), dict) else {}
    side = prediction.get("side") or payload.get("signal_side")
    if not side:
        if "long" in decision or decision in {"buy"}:
            side = "long"
        elif "short" in decision or decision in {"sell"}:
            side = "short"
    if side is not None:
        side = str(side).strip().lower()
    strength = _safe_float(
        prediction.get("strength"),
        _safe_float(prediction.get("score"), _safe_float(payload.get("score"), 0.0)),
    )
    confidence = _safe_float(
        prediction.get("confidence"),
        _safe_float(
            payload.get("prediction_confidence"),
            _safe_float(
                payload.get("confirmation_confidence"),
                _safe_float(payload.get("confidence"), _safe_float(candidate.get("confidence"), 0.0)),
            ),
        ),
    )
    return {
        "side": side if side in {"long", "short"} else None,
        "strength": strength,
        "confidence": max(0.0, min(confidence, 1.0)),
    }


def _extract_profile_strategy(payload: dict[str, Any]) -> tuple[str | None, str | None]:
    signal = payload.get("signal") if isinstance(payload.get("signal"), dict) else {}
    candidate = payload.get("candidate") if isinstance(payload.get("candidate"), dict) else {}
    rejection_detail = payload.get("rejection_detail") if isinstance(payload.get("rejection_detail"), dict) else {}
    strategy_attempts = rejection_detail.get("strategy_attempts") if isinstance(rejection_detail.get("strategy_attempts"), list) else []
    profile_id = (
        payload.get("profile_id")
        or payload.get("profile")
        or signal.get("profile_id")
        or candidate.get("profile_id")
    )
    strategy_id = (
        payload.get("strategy_id")
        or payload.get("strategy")
        or signal.get("strategy_id")
        or candidate.get("strategy_id")
    )
    if strategy_id is None:
        for attempt in strategy_attempts:
            if not isinstance(attempt, dict):
                continue
            value = attempt.get("strategy_id")
            if value:
                strategy_id = value
                break
    profile_text = str(profile_id).strip() if profile_id is not None else ""
    strategy_text = str(strategy_id).strip() if strategy_id is not None else ""
    return (profile_text or None, strategy_text or None)


def _extract_strategy_attempts(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rejection_detail = payload.get("rejection_detail") if isinstance(payload.get("rejection_detail"), dict) else {}
    attempts = rejection_detail.get("strategy_attempts") if isinstance(rejection_detail.get("strategy_attempts"), list) else []
    normalized: list[dict[str, Any]] = []
    for attempt in attempts:
        if not isinstance(attempt, dict):
            continue
        normalized.append(
            {
                "profile_id": attempt.get("profile_id"),
                "strategy_id": attempt.get("strategy_id"),
                "status": attempt.get("status"),
            }
        )
    return normalized


def _extract_session_regime(payload: dict[str, Any]) -> tuple[str | None, str | None]:
    market_context = payload.get("market_context") if isinstance(payload.get("market_context"), dict) else {}
    snapshot = payload.get("snapshot") if isinstance(payload.get("snapshot"), dict) else {}

    def _session_from_hour_utc(hour: int) -> str:
        if 0 <= hour < 8:
            return "asia"
        if 8 <= hour < 13:
            return "europe"
        return "us"

    fallback_session = None
    ts_epoch = _as_epoch_seconds(payload.get("timestamp"))
    if ts_epoch is None:
        ns_val = snapshot.get("timestamp_ns")
        if isinstance(ns_val, (int, float)) and ns_val > 0:
            ts_epoch = float(ns_val) / 1_000_000_000.0
    if ts_epoch is not None:
        try:
            fallback_session = _session_from_hour_utc(datetime.fromtimestamp(ts_epoch, tz=timezone.utc).hour)
        except Exception:
            fallback_session = None

    session = (
        payload.get("session")
        or market_context.get("session")
        or fallback_session
    )
    regime = (
        payload.get("market_regime")
        or market_context.get("market_regime")
        or market_context.get("volatility_regime")
        or snapshot.get("vol_regime")
    )
    session_text = str(session).strip().lower() if session is not None else ""
    regime_text = str(regime).strip().lower() if regime is not None else ""
    return (session_text or None, regime_text or None)


def _evaluate_confirmation_readiness(
    *,
    comparison_count: int,
    mismatch_count: int,
    contract_violations: int,
    min_comparisons: int,
    max_disagreement_pct: float,
    max_contract_violations: int,
) -> dict[str, Any]:
    disagreement_pct = (mismatch_count / comparison_count * 100.0) if comparison_count > 0 else 0.0
    checks = {
        "min_comparisons_met": comparison_count >= min_comparisons,
        "disagreement_within_limit": disagreement_pct <= max_disagreement_pct,
        "contract_violations_within_limit": contract_violations <= max_contract_violations,
    }
    ready = all(checks.values())
    return {
        "ready_for_enforce": ready,
        "disagreement_pct": round(disagreement_pct, 3),
        "checks": checks,
    }


def _as_epoch_seconds(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if hasattr(value, "timestamp"):
        try:
            return float(value.timestamp())
        except Exception:
            return None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            if text.endswith("Z"):
                text = text[:-1] + "+00:00"
            dt = datetime.fromisoformat(text)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return float(dt.timestamp())
        except Exception:
            return None
    return None


def _confirmation_cohort(legacy_decision: bool, unified_decision: bool) -> str:
    if legacy_decision and unified_decision:
        return "both_pass"
    if legacy_decision and not unified_decision:
        return "legacy_only"
    if not legacy_decision and unified_decision:
        return "unified_only"
    return "both_reject"


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2 == 1:
        return float(ordered[mid])
    return float((ordered[mid - 1] + ordered[mid]) / 2.0)


def _parse_symbol_float_overrides(raw: str) -> dict[str, float]:
    mapping: dict[str, float] = {}
    for part in (raw or "").split(","):
        token = part.strip()
        if not token or ":" not in token:
            continue
        symbol, value = token.split(":", 1)
        symbol_key = symbol.strip().upper()
        if not symbol_key:
            continue
        parsed = _safe_float(value.strip(), None)
        if parsed is None:
            continue
        mapping[symbol_key] = float(parsed)
    return mapping


def _compute_confirmation_markout_stats(
    *,
    samples: list[dict[str, Any]],
    candle_rows: list[dict[str, Any]],
    horizon_sec: int,
    max_entry_lag_sec: int = 120,
) -> dict[str, Any]:
    candles_by_symbol: dict[str, dict[str, list[float]]] = {}
    for row in candle_rows:
        symbol = str(row.get("symbol") or "").strip().upper()
        ts = _safe_float(row.get("ts_epoch"), None)
        close = _safe_float(row.get("close"), None)
        if not symbol or ts is None or close is None or close <= 0:
            continue
        bucket = candles_by_symbol.setdefault(symbol, {"ts": [], "close": []})
        bucket["ts"].append(float(ts))
        bucket["close"].append(float(close))

    for symbol, bucket in candles_by_symbol.items():
        pairs = sorted(zip(bucket["ts"], bucket["close"]), key=lambda item: item[0])
        bucket["ts"] = [float(item[0]) for item in pairs]
        bucket["close"] = [float(item[1]) for item in pairs]

    cohort_markouts: dict[str, list[float]] = {
        "both_pass": [],
        "legacy_only": [],
        "unified_only": [],
        "both_reject": [],
    }
    cohort_net_markouts: dict[str, list[float]] = {
        "both_pass": [],
        "legacy_only": [],
        "unified_only": [],
        "both_reject": [],
    }
    cohort_total_samples: dict[str, int] = {
        "both_pass": 0,
        "legacy_only": 0,
        "unified_only": 0,
        "both_reject": 0,
    }

    evaluable_total = 0
    for sample in samples:
        cohort = str(sample.get("cohort") or "both_reject")
        if cohort not in cohort_markouts:
            cohort = "both_reject"
        cohort_total_samples[cohort] = int(cohort_total_samples.get(cohort, 0)) + 1

        symbol = str(sample.get("symbol") or "").strip().upper()
        side = str(sample.get("side") or "").strip().lower()
        ts = _safe_float(sample.get("ts_epoch"), None)
        if not symbol or side not in {"long", "short"} or ts is None:
            continue

        series = candles_by_symbol.get(symbol)
        if not series:
            continue
        ts_list = series["ts"]
        close_list = series["close"]
        if not ts_list:
            continue

        entry_idx = bisect_left(ts_list, float(ts))
        if entry_idx >= len(ts_list):
            continue
        entry_ts = ts_list[entry_idx]
        if entry_ts - float(ts) > float(max_entry_lag_sec):
            continue

        target_ts = float(ts) + float(horizon_sec)
        exit_idx = bisect_left(ts_list, target_ts)
        if exit_idx >= len(ts_list):
            continue

        entry_px = close_list[entry_idx]
        exit_px = close_list[exit_idx]
        if entry_px <= 0:
            continue

        raw_bps = ((exit_px - entry_px) / entry_px) * 10000.0
        markout_bps = -raw_bps if side == "short" else raw_bps
        estimated_cost_bps = _safe_float(sample.get("estimated_cost_bps"), 0.0)
        net_markout_bps = float(markout_bps) - float(estimated_cost_bps or 0.0)
        cohort_markouts[cohort].append(float(markout_bps))
        cohort_net_markouts[cohort].append(float(net_markout_bps))
        evaluable_total += 1

    cohorts: dict[str, Any] = {}
    for cohort, values in cohort_markouts.items():
        net_values = cohort_net_markouts.get(cohort, [])
        mean_bps = (sum(values) / len(values)) if values else None
        mean_net_bps = (sum(net_values) / len(net_values)) if net_values else None
        med_bps = _median(values)
        med_net_bps = _median(net_values)
        wins = len([val for val in values if val > 0.0])
        net_wins = len([val for val in net_values if val > 0.0])
        cohorts[cohort] = {
            "samples": int(cohort_total_samples.get(cohort, 0)),
            "evaluated": len(values),
            "positiveRate": round((wins / len(values)), 4) if values else None,
            "meanMarkoutBps": round(mean_bps, 3) if mean_bps is not None else None,
            "medianMarkoutBps": round(med_bps, 3) if med_bps is not None else None,
            "netPositiveRate": round((net_wins / len(net_values)), 4) if net_values else None,
            "meanNetMarkoutBps": round(mean_net_bps, 3) if mean_net_bps is not None else None,
            "medianNetMarkoutBps": round(med_net_bps, 3) if med_net_bps is not None else None,
        }

    return {
        "totalSamples": int(len(samples)),
        "evaluatedSamples": int(evaluable_total),
        "cohorts": cohorts,
    }


def _decision_outcome(payload: dict[str, Any]) -> str:
    decision = str(payload.get("decision") or payload.get("result") or "").strip().lower()
    rejection_stage = _extract_rejection_stage(payload)
    rejection_reason = _extract_rejection_reason(payload)
    if rejection_stage or rejection_reason or decision in {"reject", "rejected", "blocked", "deny"}:
        return "rejected"
    if decision in {
        "approved",
        "accept",
        "accepted",
        "long",
        "short",
        "buy",
        "sell",
        "enter_long",
        "enter_short",
        "exit_long",
        "exit_short",
    }:
        return "approved"
    return "hold"


def _is_signal_triggered(payload: dict[str, Any]) -> bool:
    signal = _extract_signal(payload)
    if signal.get("side") in {"long", "short"}:
        return True
    decision = str(payload.get("decision") or payload.get("result") or "").strip().lower()
    return decision in {"long", "short", "buy", "sell", "enter_long", "enter_short"}


def _p95(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = int(round((len(ordered) - 1) * 0.95))
    return float(ordered[index])


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _coerce_epoch_timestamp(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        ts = float(value)
        # UI commonly sends epoch milliseconds.
        if ts > 1e12:
            ts /= 1000.0
        return ts
    if isinstance(value, str):
        try:
            ts = float(value)
            if ts > 1e12:
                ts /= 1000.0
            return ts
        except (TypeError, ValueError):
            pass
        try:
            text = value.strip()
            if text.endswith("Z"):
                text = text[:-1] + "+00:00"
            parsed = datetime.fromisoformat(text)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.timestamp()
        except (TypeError, ValueError):
            return None
    return None


def _status_to_bool(value: Any) -> Optional[bool]:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"running", "ok", "healthy", "ready", "alive", "up"}
    if isinstance(value, dict):
        status = value.get("status")
        if isinstance(status, bool):
            return status
        if isinstance(status, str):
            return status.strip().lower() in {"running", "ok", "healthy", "ready", "alive", "up"}
    return None


def _normalize_service_health(health: dict) -> dict:
    if not isinstance(health, dict) or not health:
        return {}
    services_raw = health.get("services") or {}
    services: dict[str, bool] = {}

    if isinstance(services_raw, dict):
        for name, value in services_raw.items():
            status = _status_to_bool(value)
            if status is not None:
                services[name] = status
            if isinstance(value, dict):
                workers = value.get("workers")
                if isinstance(workers, dict):
                    for worker_name, worker_value in workers.items():
                        worker_status = _status_to_bool(worker_value)
                        if worker_status is not None:
                            services[worker_name] = worker_status

    for key in ("position_guardian", "position_guard", "position_guardian_worker"):
        status = _status_to_bool(health.get(key))
        if status is not None and key not in services:
            services[key] = status

    missing = [name for name, ok in services.items() if ok is False]
    timestamp = _coerce_epoch_timestamp(health.get("timestamp_epoch") or health.get("timestamp")) or time.time()
    normalized = {
        "services": services,
        "missing": missing,
        "all_ready": len(missing) == 0 if services else False,
        "timestamp": timestamp,
    }

    # Preserve details used by the UI
    if "python_engine" in health:
        normalized["python_engine"] = health["python_engine"]
    elif isinstance(services_raw, dict) and "python_engine" in services_raw:
        normalized["python_engine"] = services_raw["python_engine"]
    if "position_guardian" in health:
        normalized["position_guardian"] = health["position_guardian"]
    elif isinstance(services_raw, dict) and "position_guardian" in services_raw:
        normalized["position_guardian"] = services_raw["position_guardian"]

    return normalized


def _to_epoch_ms(value: Any) -> Optional[int]:
    if value is None:
        return None
    # Handle datetime objects from asyncpg
    if hasattr(value, 'timestamp'):
        return int(value.timestamp() * 1000)
    if isinstance(value, (int, float)):
        ts = float(value)
        if ts > 1_000_000_000_000:
            return int(ts)
        if ts > 1_000_000_000:
            return int(ts * 1000)
        return int(ts * 1000)
    if isinstance(value, str):
        try:
            return _to_epoch_ms(float(value))
        except (TypeError, ValueError):
            pass
        try:
            text = value.strip()
            if text.endswith("Z"):
                text = text[:-1] + "+00:00"
            parsed = datetime.fromisoformat(text)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return int(parsed.timestamp() * 1000)
        except (TypeError, ValueError):
            return None
    return None


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


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


def _sanitize_for_json(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _sanitize_for_json(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_sanitize_for_json(v) for v in value]
    if isinstance(value, tuple):
        return [_sanitize_for_json(v) for v in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _storage_symbol_key(symbol: Any) -> str:
    return str(to_storage_symbol(symbol) or "").upper()


def _symbol_aliases(symbol: str) -> list[str]:
    base = (symbol or "").strip().upper()
    if not base:
        return []
    canonical = _storage_symbol_key(base)
    aliases = {
        base,
        canonical,
    }
    return [item for item in aliases if item]


class BotControlRequest(BaseModel):
    tenant_id: str | None = None
    bot_id: str | None = None
    action: str
    requested_by: str | None = None
    reason: str | None = None
    cancel_orders: bool | None = None
    close_positions: bool | None = None
    order_id: str | None = Field(default=None, alias="orderId")
    client_order_id: str | None = Field(default=None, alias="clientOrderId")
    symbol: str | None = None
    exchange: str | None = None
    price: float | None = Field(default=None, alias="newPrice")
    size: float | None = Field(default=None, alias="newSize")
    bot_exchange_config_id: str | None = Field(default=None, alias="botExchangeConfigId")
    config_version: int | None = Field(default=None, alias="configVersion")
    enabled_symbols: list[str] | None = Field(default=None, alias="enabledSymbols")
    risk_config: dict[str, Any] | None = Field(default=None, alias="riskConfig")
    execution_config: dict[str, Any] | None = Field(default=None, alias="executionConfig")
    profile_overrides: dict[str, Any] | None = Field(default=None, alias="profileOverrides")

    model_config = ConfigDict(populate_by_name=True)


class BotControlResponse(BaseModel):
    status: str
    command_id: str | None = None
    message: str | None = None
    success: bool = True


async def _redis_client():
    url = os.getenv("BOT_REDIS_URL") or os.getenv("REDIS_URL", "redis://localhost:6379")
    client = redis.from_url(url)
    try:
        yield client
    finally:  # pragma: no cover - close on app shutdown
        await client.close()

_TIMESCALE_POOL: asyncpg.Pool | None = None
_TIMESCALE_LOCK = asyncio.Lock()


async def _get_timescale_pool():
    global _TIMESCALE_POOL
    async with _TIMESCALE_LOCK:
        if _TIMESCALE_POOL is None:
            host = os.getenv("TIMESCALE_HOST", os.getenv("BOT_DB_HOST", "localhost"))
            port = int(str(os.getenv("TIMESCALE_PORT", os.getenv("BOT_DB_PORT", "5433"))))
            name = os.getenv("TIMESCALE_DB", os.getenv("BOT_DB_NAME", "quantgambit_bot"))
            user = os.getenv("TIMESCALE_USER", os.getenv("BOT_DB_USER", "quantgambit"))
            password = os.getenv("TIMESCALE_PASSWORD", os.getenv("BOT_DB_PASSWORD", ""))
            ssl_ctx = None
            ssl_env = (
                os.getenv("TIMESCALE_SSL")
                or os.getenv("BOT_DB_SSL")
                or os.getenv("DB_SSL")
                or ""
            )
            if _should_enable_pg_ssl(host, ssl_env):
                ssl_ctx = ssl.create_default_context()
                ssl_ctx.check_hostname = False
                ssl_ctx.verify_mode = ssl.CERT_NONE
            pool_max = int(os.getenv("TIMESCALE_POOL_MAX", "20"))
            _TIMESCALE_POOL = await asyncpg.create_pool(
                host=str(host or "localhost"),
                port=port,
                user=user,
                password=password,
                database=name,
                ssl=ssl_ctx,
                min_size=1,
                max_size=max(3, pool_max),
                timeout=10.0,
            )
    return _TIMESCALE_POOL


async def _timescale_reader():
    pool = await _get_timescale_pool()
    yield TimescaleReader(pool)


async def _timescale_reader_optional():
    timeout_sec = max(0.2, float(_safe_float(os.getenv("TIMESCALE_OPTIONAL_CONNECT_TIMEOUT_SEC"), 0.8)))
    try:
        pool = await asyncio.wait_for(_get_timescale_pool(), timeout=timeout_sec)
        yield TimescaleReader(pool)
    except Exception:
        yield None


async def _dashboard_pool():
    global DASHBOARD_POOL
    if DASHBOARD_POOL is None:
        host = os.getenv("DASHBOARD_DB_HOST", os.getenv("BOT_DB_HOST", os.getenv("DB_HOST", os.getenv("PLATFORM_DB_HOST", "localhost"))))
        port = os.getenv("DASHBOARD_DB_PORT", os.getenv("BOT_DB_PORT", "5432"))
        name = os.getenv("DASHBOARD_DB_NAME", os.getenv("BOT_DB_NAME", "platform_db"))
        user = os.getenv("DASHBOARD_DB_USER", os.getenv("BOT_DB_USER", "platform"))
        password = os.getenv("DASHBOARD_DB_PASSWORD", os.getenv("BOT_DB_PASSWORD", "platform_pw"))
        # NOTE: Avoid building a DSN with raw password. Special characters like
        # ":" "@" "&" etc must be URL-encoded or asyncpg will mis-parse the DSN.
        # Passing explicit connection args is safer.
        host_str = str(host or "localhost")
        port_str = str(port or "5432")
        try:
            port_int = int(port_str)
        except ValueError as exc:
            raise ValueError(f"Invalid DASHBOARD_DB_PORT={port_str!r}") from exc

        ssl_ctx = None
        ssl_env = (
            os.getenv("DASHBOARD_DB_SSL")
            or os.getenv("BOT_DB_SSL")
            or os.getenv("DB_SSL")
            or ""
        ).strip().lower()
        if _should_enable_pg_ssl(host_str, ssl_env):
            ssl_ctx = ssl.create_default_context()
            ssl_ctx.check_hostname = False
            ssl_ctx.verify_mode = ssl.CERT_NONE

        DASHBOARD_POOL = await asyncpg.create_pool(
            host=host_str,
            port=port_int,
            user=user,
            password=password,
            database=name,
            ssl=ssl_ctx,
            min_size=1,
            max_size=int(os.getenv("DASHBOARD_POOL_MAX", "3")),
            timeout=10.0,
        )
    return DASHBOARD_POOL


def create_app() -> FastAPI:
    @asynccontextmanager
    async def _lifespan(_app: FastAPI):
        await _maybe_initialize_replay_manager()
        yield
        set_replay_manager(None)
        global DASHBOARD_POOL
        if DASHBOARD_POOL is not None:
            await DASHBOARD_POOL.close()
            DASHBOARD_POOL = None
        global _TIMESCALE_POOL
        if _TIMESCALE_POOL is not None:
            await _TIMESCALE_POOL.close()
            _TIMESCALE_POOL = None

    app = FastAPI(title="quantgambit-api", version="1.0.0", lifespan=_lifespan)
    cors_env = os.getenv("CORS_ALLOW_ORIGINS", "")
    if cors_env.strip():
        allow_origins = [origin.strip() for origin in cors_env.split(",") if origin.strip()]
    else:
        allow_origins = [
            "http://dashboard.quantgambit.local",
            "http://bot.quantgambit.local",
            "http://quantgambit.local",
            "https://dashboard.quantgambit.local",
            "https://bot.quantgambit.local",
            "https://quantgambit.local",
            "http://localhost:5173",
            "http://localhost:3000",
            "http://localhost:3001",
            # Production domains
            "https://quantgambit.com",
            "https://dashboard.quantgambit.com",
            "https://api.quantgambit.com",
            "https://bot.quantgambit.com",
        ]
    # Allow any subdomain on our local/prod domains (covers future hosts)
    # while still keeping a sane default for dev.
    allow_origin_regex = r"https?://([a-z0-9-]+\.)*quantgambit\.(local|com)(:\d+)?$"
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allow_origins,
        allow_origin_regex=allow_origin_regex,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def enforce_viewer_read_only_scope(request: Request, call_next):
        if request.method == "OPTIONS":
            return await call_next(request)

        auth_header = request.headers.get("authorization", "")
        if not auth_header.lower().startswith("bearer "):
            return await call_next(request)

        try:
            claims = _verify_jwt(auth_header.split(" ", 1)[1].strip())
        except HTTPException:
            return await call_next(request)

        if str(claims.get("role", "")).lower() != "viewer":
            return await call_next(request)

        path = request.url.path
        if request.method != "GET":
            return JSONResponse(status_code=403, content={"detail": "viewer_accounts_are_read_only"})

        if not any(path == allowed or path.startswith(allowed) for allowed in _VIEWER_ALLOWED_READ_PATHS):
            return JSONResponse(status_code=403, content={"detail": "viewer_endpoint_not_allowed"})

        viewer_scope = claims.get("viewer_scope") or {}
        allowed_bot_ids = set()
        if isinstance(viewer_scope, dict):
            bot_id = viewer_scope.get("botId")
            if bot_id:
                allowed_bot_ids.add(str(bot_id))
            for item in viewer_scope.get("allowedBotIds") or []:
                if item:
                    allowed_bot_ids.add(str(item))

        if not allowed_bot_ids:
            return JSONResponse(status_code=403, content={"detail": "viewer_scope_missing_bot"})

        requested_tenant = request.query_params.get("tenant_id") or request.query_params.get("tenantId")
        if requested_tenant and requested_tenant != str(claims.get("tenant_id") or claims.get("userId") or ""):
            return JSONResponse(status_code=403, content={"detail": "viewer_scope_tenant_mismatch"})

        requested_bot_ids = set()
        query_bot_id = request.query_params.get("bot_id") or request.query_params.get("botId")
        if query_bot_id:
            requested_bot_ids.add(query_bot_id)
        for pattern in _VIEWER_PATH_BOT_PATTERNS:
            match = pattern.match(path)
            if match:
                requested_bot_ids.add(match.group(1))

        if not requested_bot_ids:
            return JSONResponse(status_code=403, content={"detail": "viewer_scope_requires_bot"})

        if not requested_bot_ids.issubset(allowed_bot_ids):
            return JSONResponse(status_code=403, content={"detail": "viewer_scope_bot_mismatch"})

        return await call_next(request)

    # Health check endpoint (no auth required)
    @app.get("/health")
    async def health_check():
        """Health check endpoint for monitoring and load balancers."""
        return {
            "status": "healthy",
            "service": "quantgambit-api",
            "version": "1.0.0",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    @app.get("/")
    async def root():
        """Root endpoint with API info."""
        return {
            "service": "quantgambit-api",
            "version": "1.0.0",
            "docs": "/docs",
            "health": "/health",
        }
    
    # Include quant-grade infrastructure endpoints
    app.include_router(quant_router)
    
    # Include EV gate endpoints
    app.include_router(ev_gate_router)
    
    # Include strategy diagnostics endpoints
    app.include_router(diagnostics_router)

    # Include shadow comparison endpoints
    app.include_router(shadow_router)
    
    auth_dep = build_auth_dependency()
    auth_claims_dep = build_auth_dependency_with_claims()
    
    # Include backtest research endpoints
    backtest_router = create_backtest_router(
        dashboard_pool_dep=_dashboard_pool,
        redis_client_dep=_redis_client,
        auth_dep=auth_dep,
        timescale_pool_dep=_get_timescale_pool,
    )
    app.include_router(backtest_router)
    # Include replay validation endpoints used by /analysis/replay.
    app.include_router(replay_router)
    
    # Load platform documentation (used by both copilot and docs endpoints)
    _docs_dir = Path(os.getenv(
        "DOCS_DIR",
        str(Path(__file__).resolve().parent.parent.parent.parent / "deeptrader-dashhboard" / "public" / "docs" / "pages"),
    ))
    _doc_loader = DocLoader(_docs_dir)
    _doc_loader.load_all()
    _search_index = DocSearchIndex()
    _search_index.build(_doc_loader._pages)

    # Include copilot chat endpoints (with doc_loader for page context)
    copilot_router = create_copilot_router(
        dashboard_pool_dep=_dashboard_pool,
        redis_client_dep=_redis_client,
        timescale_pool_dep=_get_timescale_pool,
        auth_dep=auth_dep,
        doc_loader=_doc_loader,
    )
    app.include_router(copilot_router)

    # Include platform documentation endpoints
    docs_router = create_docs_router(doc_loader=_doc_loader, search_index=_search_index)
    app.include_router(docs_router, prefix="/api")
    
    # Default scope values are allowed only for non-critical read paths.
    default_tenant = os.getenv("DEFAULT_TENANT_ID", "")
    default_bot = os.getenv("DEFAULT_BOT_ID", "")

    def _resolve_scope(
        tenant_id: Optional[str],
        bot_id: Optional[str],
        *,
        require_explicit: bool = False,
        allow_default: bool = True,
    ) -> tuple[str, str]:
        use_default = allow_default and not require_explicit
        resolved_tenant = tenant_id or (default_tenant if use_default else "")
        resolved_bot = bot_id or (default_bot if use_default else "")
        if require_explicit and (not resolved_tenant or not resolved_bot):
            raise HTTPException(
                status_code=400,
                detail="tenant_id and bot_id are required for this endpoint",
            )
        return resolved_tenant, resolved_bot

    async def _resolve_bot_from_exchange_account(pool, exchange_account_id: str | None) -> str | None:
        if not pool or not exchange_account_id:
            return None
        try:
            account_row = await pool.fetchrow(
                """
                SELECT active_bot_id
                FROM exchange_accounts
                WHERE id=$1
                """,
                exchange_account_id,
            )
            if account_row and account_row.get("active_bot_id"):
                return str(account_row["active_bot_id"])
            row = await pool.fetchrow(
                """
                SELECT bot_instance_id
                FROM bot_exchange_configs
                WHERE exchange_account_id=$1
                  AND is_active=true
                  AND deleted_at IS NULL
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                exchange_account_id,
            )
            if row and row.get("bot_instance_id"):
                return str(row["bot_instance_id"])
        except Exception:
            return None
        return None

    def _default_bot_profile(bot_id: str, name: str | None = None) -> dict[str, Any]:
        timestamp = _now_iso()
        return {
            "id": bot_id,
            "name": name or f"Bot {bot_id}",
            "environment": "paper",
            "engine_type": "quantgambit",
            "engineType": "quantgambit",
            "description": None,
            "status": "inactive",
            "active_version_id": None,
            "activeVersionId": None,
            "activeVersion": None,
            "metadata": {},
            "created_at": timestamp,
            "updated_at": timestamp,
            "createdAt": timestamp,
            "updatedAt": timestamp,
        }

    def _default_bot_version(bot_id: str, version_number: int = 1) -> dict[str, Any]:
        timestamp = _now_iso()
        return {
            "id": str(uuid.uuid4()),
            "bot_profile_id": bot_id,
            "version_number": version_number,
            "status": "draft",
            "config_blob": {},
            "config": {},
            "notes": None,
            "created_at": timestamp,
            "activated_at": None,
            "botProfileId": bot_id,
            "versionNumber": version_number,
            "createdAt": timestamp,
            "activatedAt": None,
        }

    def _default_bot_instance(bot_id: str) -> dict[str, Any]:
        timestamp = _now_iso()
        return {
            "id": bot_id,
            "user_id": "unknown",
            "name": f"Bot {bot_id}",
            "description": None,
            "strategy_template_id": None,
            "allocator_role": "core",
            "bot_type": "standard",
            "default_risk_config": {},
            "default_execution_config": {},
            "profile_overrides": {},
            "tags": [],
            "is_active": False,
            "created_at": timestamp,
            "updated_at": timestamp,
        }

    def _default_exchange_config(bot_id: str, config_id: str) -> dict[str, Any]:
        timestamp = _now_iso()
        return {
            "id": config_id,
            "bot_instance_id": bot_id,
            "credential_id": "unknown",
            "exchange_account_id": None,
            "environment": "paper",
            "trading_capital_usd": None,
            "enabled_symbols": [],
            "risk_config": {},
            "execution_config": {},
            "profile_overrides": {},
            "state": "created",
            "last_state_change": None,
            "last_error": None,
            "is_active": False,
            "activated_at": None,
            "last_heartbeat_at": None,
            "decisions_count": 0,
            "trades_count": 0,
            "config_version": 1,
            "notes": None,
            "created_at": timestamp,
            "updated_at": timestamp,
            "createdAt": timestamp,
            "updatedAt": timestamp,
            "exchange": "unknown",
            "credential_label": None,
            "is_testnet": True,
            "credential_status": None,
            "exchange_balance": None,
            "bot_name": f"Bot {bot_id}",
        }

    async def _ensure_single_live_per_account(pool, exchange_account_id: str, exclude_config_id: str | None = None):
        if not exchange_account_id:
            return
        # block multiple live, non-testnet active configs on same exchange account
        params: list[Any] = [exchange_account_id]
        query = """
        SELECT bec.id, bec.bot_instance_id
        FROM bot_exchange_configs bec
        JOIN exchange_accounts ea ON ea.id = bec.exchange_account_id
        WHERE bec.exchange_account_id=$1
          AND bec.environment='live'
          AND bec.is_active=true
          AND COALESCE(ea.is_demo,false)=false
        """
        if exclude_config_id:
            query += " AND bec.id <> $2"
            params.append(exclude_config_id)
        rows = await _fetch_rows(pool, query, *params)
        if rows:
            raise HTTPException(
                status_code=400,
                detail="Another live bot is already active on this exchange account",
            )

    def _default_policy() -> dict[str, Any]:
        timestamp = _now_iso()
        return {
            "id": "policy-default",
            "user_id": "unknown",
            "max_daily_loss_pct": 0.0,
            "max_daily_loss_usd": None,
            "max_total_exposure_pct": 0.0,
            "max_single_position_pct": 0.0,
            "max_per_symbol_exposure_pct": 0.0,
            "max_leverage": 1.0,
            "allowed_leverage_levels": [],
            "max_concurrent_positions": 0,
            "max_concurrent_bots": 0,
            "max_symbols": 0,
            "total_capital_limit_usd": None,
            "min_reserve_pct": 0.0,
            "live_trading_enabled": False,
            "allowed_environments": ["paper"],
            "allowed_exchanges": [],
            "trading_hours_enabled": False,
            "circuit_breaker_enabled": False,
            "circuit_breaker_loss_pct": 0.0,
            "circuit_breaker_cooldown_minutes": 0,
            "policy_version": 1,
            "created_at": timestamp,
            "updated_at": timestamp,
            "createdAt": timestamp,
            "updatedAt": timestamp,
        }

    async def _resolve_runtime_tenant_scope(
        redis_client: Any,
        tenant_id: str,
        bot_id: str,
        *,
        suffixes: list[str],
    ) -> str:
        if not bot_id:
            return tenant_id
        for suffix in suffixes:
            key = f"quantgambit:{tenant_id}:{bot_id}:{suffix}"
            try:
                key_type = await redis_client.type(key)
                if isinstance(key_type, bytes):
                    key_type = key_type.decode("utf-8", errors="ignore")
                key_type = str(key_type or "").strip().lower()
                if key_type and key_type != "none":
                    return tenant_id
            except Exception:
                continue
        for suffix in suffixes:
            try:
                wildcard = await redis_client.keys(f"quantgambit:*:{bot_id}:{suffix}")
            except Exception:
                wildcard = []
            if wildcard:
                sample_key = str(wildcard[0])
                parts = sample_key.split(":")
                if len(parts) >= 4:
                    return parts[1]
        return tenant_id

    def _default_strategy_template(template_id: str) -> dict[str, Any]:
        return {
            "id": template_id,
            "name": "Default",
            "slug": "default",
            "description": None,
            "strategy_family": "unknown",
            "timeframe": "1m",
            "default_profile_bundle": {},
            "default_risk_config": {},
            "default_execution_config": {},
            "supported_exchanges": [],
            "recommended_symbols": [],
            "version": 1,
            "is_system": True,
            "is_active": True,
            "created_at": _now_iso(),
        }

    async def _publish_control_command(
        redis_client,
        command_type: str,
        request: BotControlRequest,
        confirm_required: bool = False,
    ) -> BotControlResponse:
        trading_mode = os.getenv("TRADING_MODE", "live").lower()
        if confirm_required and trading_mode in {"paper", "testnet"}:
            confirm_required = False
        tenant_id = str(request.tenant_id or "").strip()
        bot_id = str(request.bot_id or "").strip()
        if not tenant_id or not bot_id:
            raise HTTPException(status_code=400, detail="tenant_id and bot_id are required")
        command_id = str(uuid.uuid4())
        scope = {
            "tenant_id": tenant_id,
            "bot_id": bot_id,
        }
        payload = {
            "cancel_orders": request.cancel_orders,
            "close_positions": request.close_positions,
            "order_id": request.order_id,
            "client_order_id": request.client_order_id,
            "symbol": request.symbol,
            "exchange": request.exchange,
            "price": request.price,
            "size": request.size,
        }
        command = Command(
            command_id=command_id,
            type=command_type,
            scope=scope,
            requested_by=request.requested_by or "dashboard",
            requested_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            schema_version="v1",
            reason=request.reason,
            confirm_required=confirm_required,
            payload={k: v for k, v in payload.items() if v is not None},
        )
        stream_client = RedisStreamsClient(redis_client)
        stream_name = control_command_stream_name(tenant_id, bot_id)
        await stream_client.publish_command(stream_name, command)
        return BotControlResponse(status="accepted", command_id=command_id, message="queued", success=True)

    async def _fetch_rows(pool, query: str, *params):
        try:
            async with pool.acquire() as conn:
                rows = await conn.fetch(query, *params)
            return [dict(row) for row in rows]
        except Exception:
            return []

    async def _fetch_row(pool, query: str, *params):
        try:
            async with pool.acquire() as conn:
                row = await conn.fetchrow(query, *params)
            return dict(row) if row else None
        except Exception:
            return None

    def _decode_bytes(val: Any) -> Any:
        if isinstance(val, bytes):
            return val.decode()
        return val

    async def _read_stream(redis_client, key: str, limit: int = 200) -> list[dict[str, Any]]:
        try:
            entries = await redis_client.xrevrange(key, count=limit)
        except Exception:
            return []
        records: list[dict[str, Any]] = []
        for entry_id, payload in entries:
            record: dict[str, Any] = {"id": _decode_bytes(entry_id)}
            if isinstance(payload, dict):
                for k, v in payload.items():
                    record[_decode_bytes(k)] = _decode_bytes(v)
            records.append(record)
        return records

    async def _fetch_timescale_rows(query: str, *params) -> list[dict[str, Any]]:
        try:
            pool = await _get_timescale_pool()
        except Exception:
            return []
        try:
            async with pool.acquire() as conn:
                rows = await conn.fetch(query, *params)
            return [dict(row) for row in rows]
        except Exception:
            return []

    async def _fetch_timescale_rows_timeboxed(
        query: str,
        *params: Any,
        timeout_sec: float,
    ) -> tuple[list[dict[str, Any]], bool]:
        try:
            rows = await asyncio.wait_for(_fetch_timescale_rows(query, *params), timeout=max(0.2, timeout_sec))
            return rows, False
        except asyncio.TimeoutError:
            return [], True
        except Exception:
            return [], False

    async def _fetch_timescale_rows_direct_timeboxed(
        query: str,
        *params: Any,
        timeout_sec: float,
    ) -> tuple[list[dict[str, Any]], bool]:
        async def _run_direct() -> list[dict[str, Any]]:
            conn = await asyncpg.connect(_build_timescale_url(), timeout=max(0.2, timeout_sec))
            try:
                rows = await conn.fetch(query, *params, timeout=max(0.2, timeout_sec))
                return [dict(row) for row in rows]
            finally:
                await conn.close()

        try:
            rows = await asyncio.wait_for(_run_direct(), timeout=max(0.3, timeout_sec + 0.2))
            return rows, False
        except asyncio.TimeoutError:
            return [], True
        except Exception:
            return [], False

    async def _scan_redis_keys(
        redis_client: redis.Redis,
        pattern: str,
        *,
        limit: int = 200,
        timeout_sec: float = 1.0,
    ) -> list[str]:
        if limit <= 0:
            return []

        async def _scan() -> list[str]:
            cursor = 0
            out: list[str] = []
            while True:
                cursor, batch = await redis_client.scan(cursor=cursor, match=pattern, count=min(200, limit))
                for item in batch:
                    key = item.decode("utf-8") if isinstance(item, bytes) else str(item)
                    out.append(key)
                    if len(out) >= limit:
                        return out
                if cursor == 0:
                    break
            return out

        try:
            return await asyncio.wait_for(_scan(), timeout=max(0.2, timeout_sec))
        except Exception:
            return []

    def _format_bot_profile(row: dict[str, Any]) -> dict[str, Any]:
        if not row:
            return {}
        return {
            "id": str(row.get("id")),
            "name": row.get("name"),
            "environment": row.get("environment"),
            "engine_type": row.get("engine_type"),
            "engineType": row.get("engine_type"),
            "description": row.get("description"),
            "status": row.get("status"),
            "owner_id": str(row.get("owner_id")) if row.get("owner_id") else None,
            "ownerId": str(row.get("owner_id")) if row.get("owner_id") else None,
            "active_version_id": str(row.get("active_version_id")) if row.get("active_version_id") else None,
            "activeVersionId": str(row.get("active_version_id")) if row.get("active_version_id") else None,
            "metadata": row.get("metadata") or {},
            "created_at": row.get("created_at"),
            "updated_at": row.get("updated_at"),
            "createdAt": row.get("created_at"),
            "updatedAt": row.get("updated_at"),
        }

    def _format_bot_version(row: dict[str, Any]) -> dict[str, Any]:
        if not row:
            return {}
        return {
            "id": str(row.get("id")),
            "bot_profile_id": str(row.get("bot_profile_id")),
            "botProfileId": str(row.get("bot_profile_id")),
            "version_number": row.get("version_number"),
            "versionNumber": row.get("version_number"),
            "status": row.get("status"),
            "config_blob": row.get("config_blob") or {},
            "config": row.get("config_blob") or {},
            "checksum": row.get("checksum"),
            "notes": row.get("notes"),
            "created_by": str(row.get("created_by")) if row.get("created_by") else None,
            "promoted_by": str(row.get("promoted_by")) if row.get("promoted_by") else None,
            "created_at": row.get("created_at"),
            "activated_at": row.get("activated_at"),
            "createdAt": row.get("created_at"),
            "activatedAt": row.get("activated_at"),
        }

    def _format_bot_instance(row: dict[str, Any]) -> dict[str, Any]:
        if not row:
            return {}
        def _ensure_json(val: Any) -> Any:
            if isinstance(val, str):
                try:
                    import json
                    return json.loads(val)
                except Exception:
                    return val
            return val
        return {
            "id": str(row.get("id")),
            "user_id": str(row.get("user_id")) if row.get("user_id") else "unknown",
            "name": row.get("name"),
            "description": row.get("description"),
            "strategy_template_id": str(row.get("strategy_template_id")) if row.get("strategy_template_id") else None,
            "allocator_role": row.get("allocator_role") or "core",
            "market_type": row.get("market_type") or "perp",
            "bot_type": _derive_bot_type(row.get("profile_overrides")),
            "default_risk_config": _ensure_json(row.get("default_risk_config")) or {},
            "default_execution_config": _ensure_json(row.get("default_execution_config")) or {},
            "profile_overrides": _ensure_json(row.get("profile_overrides")) or {},
            "tags": row.get("tags") or [],
            "is_active": bool(row.get("is_active", False)),
            "created_at": row.get("created_at"),
            "updated_at": row.get("updated_at"),
            "template_name": row.get("template_name"),
            "template_slug": row.get("template_slug"),
            "strategy_family": row.get("strategy_family"),
            "trading_mode": row.get("trading_mode") or "paper",
        }

    def _ensure_json(val: Any) -> Any:
        if isinstance(val, str):
            try:
                import json
                return json.loads(val)
            except Exception:
                return val
        return val

    def _normalize_bot_type(value: Any) -> str:
        normalized = str(value or "").strip().lower()
        if normalized in {"ai_spot_swing", "ai-spot-swing", "spot_swing_ai"}:
            return "ai_spot_swing"
        return "standard"

    def _derive_bot_type(profile_overrides: Any) -> str:
        profile = _ensure_json(profile_overrides) or {}
        if not isinstance(profile, dict):
            return "standard"
        return _normalize_bot_type(profile.get("bot_type"))

    def _normalize_bot_profile_overrides(data: dict[str, Any], existing: dict[str, Any] | None = None) -> dict[str, Any]:
        merged = dict(existing or {})
        provided = data.get("profileOverrides") or data.get("profile_overrides") or {}
        if isinstance(provided, str):
            try:
                provided = json.loads(provided)
            except Exception:
                provided = {}
        if isinstance(provided, dict):
            merged.update(provided)

        bot_type = _normalize_bot_type(data.get("botType") or data.get("bot_type") or merged.get("bot_type"))
        merged["bot_type"] = bot_type
        if bot_type == "ai_spot_swing":
            merged["ai_provider"] = str(
                data.get("aiProvider")
                or data.get("ai_provider")
                or merged.get("ai_provider")
                or "deepseek_context"
            ).strip() or "deepseek_context"
            merged["ai_profile"] = str(
                data.get("aiProfile")
                or data.get("ai_profile")
                or merged.get("ai_profile")
                or "spot_ai_assist"
            ).strip() or "spot_ai_assist"
            merged["ai_shadow_mode"] = bool(
                data.get("aiShadowMode")
                if data.get("aiShadowMode") is not None
                else data.get("ai_shadow_mode")
                if data.get("ai_shadow_mode") is not None
                else merged.get("ai_shadow_mode", True)
            )
            merged["ai_confidence_floor"] = float(
                _safe_float(
                    data.get("aiConfidenceFloor")
                    or data.get("ai_confidence_floor")
                    or merged.get("ai_confidence_floor"),
                    0.74,
                )
            )
            merged["ai_sentiment_required"] = bool(
                data.get("aiSentimentRequired")
                if data.get("aiSentimentRequired") is not None
                else data.get("ai_sentiment_required")
                if data.get("ai_sentiment_required") is not None
                else merged.get("ai_sentiment_required", True)
            )
            merged["ai_require_baseline_alignment"] = bool(
                data.get("aiRequireBaselineAlignment")
                if data.get("aiRequireBaselineAlignment") is not None
                else data.get("ai_require_baseline_alignment")
                if data.get("ai_require_baseline_alignment") is not None
                else merged.get("ai_require_baseline_alignment", True)
            )
            sessions = (
                data.get("aiSessions")
                or data.get("ai_sessions")
                or merged.get("ai_sessions")
                or ["london", "ny"]
            )
            if isinstance(sessions, str):
                sessions = [item.strip() for item in sessions.split(",") if item.strip()]
            merged["ai_sessions"] = sessions if isinstance(sessions, list) else ["london", "ny"]
        return merged

    def _format_exchange_config(row: dict[str, Any]) -> dict[str, Any]:
        if not row:
            return {}
        return {
            "id": str(row.get("id")),
            "bot_instance_id": str(row.get("bot_instance_id")) if row.get("bot_instance_id") else None,
            "credential_id": str(row.get("credential_id")) if row.get("credential_id") else "unknown",
            "exchange_account_id": str(row.get("exchange_account_id")) if row.get("exchange_account_id") else None,
            "environment": row.get("environment") or "paper",
            "trading_capital_usd": row.get("trading_capital_usd"),
            "enabled_symbols": _ensure_json(row.get("enabled_symbols")) or [],
            "risk_config": _ensure_json(row.get("risk_config")) or {},
            "execution_config": _ensure_json(row.get("execution_config")) or {},
            "profile_overrides": _ensure_json(row.get("profile_overrides")) or {},
            "state": row.get("state") or "created",
            "last_state_change": row.get("last_state_change"),
            "last_error": row.get("last_error"),
            "is_active": bool(row.get("is_active", False)),
            "activated_at": row.get("activated_at"),
            "last_heartbeat_at": row.get("last_heartbeat_at"),
            "decisions_count": row.get("decisions_count") or 0,
            "trades_count": row.get("trades_count") or 0,
            "config_version": row.get("config_version") or 1,
            "notes": row.get("notes"),
            "created_at": row.get("created_at"),
            "updated_at": row.get("updated_at"),
            "exchange": row.get("exchange"),
            "exchange_account_label": row.get("exchange_account_label"),
            "exchange_account_venue": row.get("exchange_account_venue"),
            "credential_label": row.get("credential_label"),
            "is_testnet": row.get("is_testnet"),
            "credential_status": row.get("credential_status"),
            "exchange_balance": row.get("exchange_balance"),
            "bot_name": row.get("bot_name"),
        }

    def _format_config_version(row: dict[str, Any]) -> dict[str, Any]:
        if not row:
            return {}
        return {
            "id": str(row.get("id")),
            "bot_exchange_config_id": str(row.get("bot_exchange_config_id")),
            "version_number": row.get("version_number"),
            "trading_capital_usd": row.get("trading_capital_usd"),
            "enabled_symbols": row.get("enabled_symbols") or [],
            "risk_config": row.get("risk_config") or {},
            "execution_config": row.get("execution_config") or {},
            "change_summary": row.get("change_summary"),
            "change_type": row.get("change_type"),
            "was_activated": bool(row.get("was_activated", False)),
            "activated_at": row.get("activated_at"),
            "created_at": row.get("created_at"),
        }

    def _status_to_health(status: str | None) -> str:
        if status in {"ok", "healthy"}:
            return "healthy"
        if status in {"degraded", "warning"}:
            return "degraded"
        if status in {"stale", "critical", "error"}:
            return "critical"
        return "unknown"

    def _quality_to_metric(payload: dict[str, Any], symbol: str | None = None) -> dict[str, Any]:
        import uuid
        timestamp = payload.get("timestamp") or time.time()
        iso_ts = _now_iso()
        try:
            iso_ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(float(timestamp)))
        except (TypeError, ValueError):
            pass
        gap_count = int(payload.get("gap_count") or 0)
        out_of_order = int(payload.get("out_of_order_count") or 0)
        # Add unique suffix to prevent duplicate React keys when multiple events have same timestamp
        unique_suffix = uuid.uuid4().hex[:8]
        return {
            "id": f"{symbol or payload.get('symbol') or 'unknown'}:{int(float(timestamp))}:{unique_suffix}",
            "symbol": symbol or payload.get("symbol") or "UNKNOWN",
            "timeframe": payload.get("timeframe") or "1m",
            "metric_date": iso_ts,
            "total_candles_expected": 0,
            "total_candles_received": 0,
            "missing_candles_count": gap_count,
            "duplicate_candles_count": 0,
            "avg_ingest_latency_ms": None,
            "max_ingest_latency_ms": None,
            "min_ingest_latency_ms": None,
            "outlier_count": 0,
            "gap_count": gap_count,
            "invalid_price_count": 0,
            "timestamp_drift_seconds": payload.get("tick_age_sec"),
            "quality_score": float(payload.get("quality_score") or 0),
            "status": _status_to_health(payload.get("status")),
            "created_at": iso_ts,
            "updated_at": iso_ts,
        }

    def _compute_exposure_snapshot(positions: list[dict[str, Any]]) -> dict[str, Any]:
        exposures: dict[str, dict[str, Any]] = {}
        total_exposure = 0.0
        for pos in positions:
            symbol = pos.get("symbol") or "UNKNOWN"
            size = float(pos.get("size") or 0)
            price = (
                pos.get("current_price")
                or pos.get("reference_price")
                or pos.get("entry_price")
                or 0
            )
            try:
                price = float(price)
            except (TypeError, ValueError):
                price = 0.0
            exposure_usd = abs(size * price)
            total_exposure += exposure_usd
            bucket = exposures.setdefault(
                symbol,
                {
                    "symbol": symbol,
                    "exposureUsd": 0.0,
                    "exposurePct": 0.0,
                    "positions": 0,
                    "pnl": 0.0,
                },
            )
            bucket["exposureUsd"] += exposure_usd
            bucket["positions"] += 1
            bucket["pnl"] += float(pos.get("pnl") or 0)
        for bucket in exposures.values():
            bucket["exposurePct"] = (bucket["exposureUsd"] / total_exposure * 100.0) if total_exposure else 0.0
        return {"exposureBySymbol": list(exposures.values()), "totalExposureUsd": total_exposure}

    def _normalize_trade_event(event: dict[str, Any]) -> dict[str, Any]:
        symbol = event.get("symbol") or "UNKNOWN"
        raw_side = str(event.get("side") or "unknown").lower()
        # Normalize order-side and keep direction-side explicit for UI diagnostics.
        side_map = {"long": "buy", "short": "sell", "buy": "buy", "sell": "sell"}
        order_side = side_map.get(raw_side, raw_side)
        position_effect = str(event.get("position_effect") or "").strip().lower()
        raw_position_side = str(
            event.get("position_side")
            or event.get("closed_position_side")
            or event.get("positionSide")
            or ""
        ).strip().lower()
        position_side = raw_position_side if raw_position_side in {"long", "short"} else None
        # For close rows, order side is opposite of the held position side.
        # Detect closes by position_effect OR by close-like reason (many events
        # have position_effect='' or 'open' despite being actual closes).
        close_reasons = {
            "position_close", "strategic_exit", "stop_loss", "take_profit",
            "stop_loss_hit", "take_profit_hit", "max_age_exceeded",
            "breakeven_stop_hit", "profit_lock_retrace", "exchange_reconcile",
            "exchange_backfill",
        }
        raw_reason = str(event.get("reason") or "").strip().lower()
        is_close_event = (
            position_effect == "close"
            or raw_reason in close_reasons
            or raw_reason.startswith("safety_exit")
        )
        if position_side is None and is_close_event:
            if order_side == "buy":
                position_side = "short"
            elif order_side == "sell":
                position_side = "long"
        size = _safe_float(event.get("size") or event.get("filled_size") or event.get("quantity"))

        # Important: order_events are often "order-level" (single fill price) not "trade-level"
        # (position entry/exit). We should *not* synthesize PnL from a single fill price, since
        # that fabricates $0.00 PnL and hides missing exchange-reconciled PnL.
        explicit_entry = event.get("entry_price") or event.get("entryPrice")
        explicit_exit = event.get("exit_price") or event.get("exitPrice")
        fill_price = event.get("fill_price") or event.get("fillPrice") or event.get("price")

        entry_price = _safe_float(explicit_entry or fill_price)
        exit_price = _safe_float(explicit_exit or fill_price)
        entry_fee = _safe_float(event.get("entry_fee_usd") or event.get("entry_fee") or event.get("entryFee"))
        exit_fee = _safe_float(event.get("fee_usd") or event.get("fees") or event.get("fee"))
        total_fees = _safe_float(event.get("total_fees_usd") or event.get("total_fees") or event.get("totalFees"))
        if total_fees is None and (entry_fee is not None or exit_fee is not None):
            total_fees = (entry_fee or 0.0) + (exit_fee or 0.0)
        liquidity_raw = str(
            event.get("liquidity")
            or event.get("liquidity_type")
            or event.get("maker_taker")
            or ""
        ).strip().lower()
        is_maker = event.get("is_maker")
        if isinstance(is_maker, bool):
            liquidity_raw = "maker" if is_maker else "taker"
        liquidity = "maker" if "maker" in liquidity_raw else ("taker" if "taker" in liquidity_raw else None)
        if liquidity is None:
            post_only = event.get("post_only")
            entry_post_only = event.get("entry_post_only")
            if isinstance(post_only, bool):
                liquidity = "maker" if post_only else "taker"
            elif isinstance(entry_post_only, bool):
                liquidity = "maker" if entry_post_only else "taker"
            else:
                order_type = str(event.get("order_type") or "").strip().lower()
                if order_type == "market":
                    liquidity = "taker"
        maker_percent = 1.0 if liquidity == "maker" else 0.0 if liquidity == "taker" else None
        realized_pnl = _safe_float(
            event.get("net_pnl")
            or event.get("realized_pnl")
            or event.get("closed_pnl")
            or event.get("exec_pnl")
            or event.get("pnl")
        )
        gross_pnl = _safe_float(event.get("gross_pnl"))

        # Only infer gross PnL when we truly have a trade entry/exit price pair.
        # For order-level rows (single fill price), gross_pnl must come from exchange reconciliation.
        has_trade_entry_exit = explicit_entry is not None and explicit_exit is not None
        computed_gross: Optional[float] = None
        if has_trade_entry_exit and size is not None and entry_price is not None and exit_price is not None:
            gross_basis_side = position_side or ("short" if order_side in {"sell", "short"} else "long")
            if gross_basis_side == "short":
                computed_gross = (entry_price - exit_price) * size
            else:
                computed_gross = (exit_price - entry_price) * size
            # Only synthesize gross PnL when payload doesn't provide one.
            # Exchange-reconciled rows should remain authoritative.
            if computed_gross is not None and gross_pnl is None:
                gross_pnl = computed_gross
        # If gross_pnl couldn't be computed but we have realized+fees, infer gross
        if gross_pnl is None and realized_pnl is not None and total_fees is not None:
            gross_pnl = realized_pnl + total_fees
        net_pnl = realized_pnl
        # If payload fee is partial/one-sided but we have reliable net and gross, derive
        # the effective round-trip fees from the net-vs-gross delta.
        if net_pnl is not None and gross_pnl is not None:
            inferred_total_fees = abs(gross_pnl - net_pnl)
            if inferred_total_fees > 1e-9:
                if total_fees is None or inferred_total_fees > (total_fees + 1e-9):
                    total_fees = inferred_total_fees
        if net_pnl is None and gross_pnl is not None and total_fees is not None:
            net_pnl = gross_pnl - total_fees
        pnl = net_pnl if net_pnl is not None else (gross_pnl if gross_pnl is not None else realized_pnl)
        pnl_pct = event.get("realized_pnl_pct") or event.get("pnlPercent")
        raw_ts = (
            # Prefer exchange execution times when present (backfill/reconcile payloads).
            event.get("last_exec_time_ms")
            or event.get("exec_time_ms")
            or event.get("execTime")
            or event.get("exit_timestamp")
            or event.get("timestamp")
            or event.get("ts")
            or event.get("created_at")
        )
        timestamp_ms = _to_epoch_ms(raw_ts)
        hold_time_sec = _safe_float(event.get("hold_time_sec"))
        entry_ts = event.get("entry_timestamp") or event.get("opened_at") or event.get("entry_time")
        exit_ts = event.get("exit_timestamp") or event.get("exit_time") or event.get("timestamp") or event.get("ts")
        # Normalize epoch timestamps if present
        def _to_epoch_sec(value: Any) -> Optional[float]:
            if value is None:
                return None
            try:
                value = float(value)
            except (TypeError, ValueError):
                return None
            # If it's in ms, convert to seconds
            if value > 1e12:
                return value / 1000.0
            return value
        if hold_time_sec is None:
            entry_sec = _to_epoch_sec(entry_ts)
            exit_sec = _to_epoch_sec(exit_ts)
            if entry_sec is not None and exit_sec is not None:
                hold_time_sec = max(0.0, exit_sec - entry_sec)
        holding_duration = None
        if hold_time_sec is not None:
            holding_duration = int(_safe_float(hold_time_sec) * 1000)
        notional = None
        if size is not None and entry_price is not None:
            notional = size * entry_price
        trade_id = (
            event.get("order_id")
            or event.get("client_order_id")
            or event.get("trade_id")
            or event.get("id")
        )
        # Add unique suffix to prevent duplicate React keys when multiple events have same timestamp
        import uuid
        unique_suffix = uuid.uuid4().hex[:8]
        if not trade_id and timestamp_ms is not None:
            trade_id = f"{symbol}:{timestamp_ms}:{unique_suffix}"
        generic_close_reasons = {"position_close", "exchange_reconcile", "exchange_backfill"}
        reason_candidates = [
            event.get("exit_reason"),
            event.get("close_reason"),
            event.get("closed_by"),
            event.get("reason"),
        ]
        normalized_reason_candidates = [
            str(candidate).strip()
            for candidate in reason_candidates
            if candidate is not None and str(candidate).strip()
        ]
        exit_reason = None
        for candidate in normalized_reason_candidates:
            if candidate.lower() not in generic_close_reasons:
                exit_reason = candidate
                break
        if exit_reason is None and normalized_reason_candidates:
            exit_reason = normalized_reason_candidates[0]
        display_side = position_side
        if display_side is None:
            # Only expose LONG/SHORT when we have a true position direction.
            # For spot and order-only rows, BUY/SELL is the correct UI semantic.
            if order_side in {"buy", "sell"}:
                display_side = order_side
            elif order_side in {"long", "short"}:
                display_side = order_side
        return {
            "id": str(trade_id) if trade_id else f"{symbol}:{timestamp_ms or int(time.time() * 1000)}:{unique_suffix}",
            "bot_id": event.get("bot_id"),
            "symbol": symbol,
            "side": display_side or "unknown",
            "order_side": order_side,
            # Expose normalized position direction so UI can render LONG/SHORT
            # instead of raw close-order side (BUY/SELL).
            "position_side": position_side,
            "original_side": position_side,
            "entry_price": entry_price,
            "exit_price": exit_price,
            "entry_time": event.get("entry_timestamp") or event.get("entry_time"),
            "exit_time": event.get("exit_timestamp") or event.get("exit_time"),
            "size": size,
            "pnl": pnl,
            "gross_pnl": gross_pnl,
            "net_pnl": net_pnl,
            "fees": total_fees if total_fees is not None else exit_fee,
            "entry_fee_usd": entry_fee,
            "total_fees_usd": total_fees,
            "notional": notional,
            "pnlPercent": _safe_float(pnl_pct, default=None) if pnl_pct is not None else None,
            "timestamp": timestamp_ms or int(time.time() * 1000),
            "formattedTimestamp": None,
            "holdingDuration": holding_duration,
            "exitReason": exit_reason,
            "exit_reason": exit_reason,
            "close_reason": event.get("close_reason"),
            "closed_by": event.get("closed_by"),
            "decisionTrace": None,
            "slippage_bps": event.get("slippage_bps"),
            "latency_ms": event.get("latency_ms") or event.get("fill_time_ms"),
            "mid_at_send": _safe_float(event.get("mid_at_send")),
            "expected_price_at_send": _safe_float(event.get("expected_price_at_send")),
            "send_ts": _safe_float(event.get("send_ts")),
            "ack_ts": _safe_float(event.get("ack_ts")),
            "first_fill_ts": _safe_float(event.get("first_fill_ts")),
            "final_fill_ts": _safe_float(event.get("final_fill_ts")),
            "post_only_reject_count": int(_safe_float(event.get("post_only_reject_count"), 0.0) or 0),
            "cancel_after_timeout_count": int(_safe_float(event.get("cancel_after_timeout_count"), 0.0) or 0),
            "order_type": event.get("order_type"),
            "post_only": event.get("post_only"),
            # Include status and position effect for filtering
            "status": event.get("status"),
            "position_effect": event.get("position_effect"),
            "liquidity": liquidity,
            "liquidity_role": liquidity,
            "makerPercent": maker_percent,
        }

    _CLOSE_REASON_RANK: dict[str, int] = {
        "exchange_reconcile": 7,
        "exchange_backfill": 6,
        "position_close": 5,
        "strategic_exit": 4,
        "breakeven_stop_hit": 4,
        "trailing_stop_hit": 4,
        "stop_loss": 3,
        "take_profit": 3,
        "stop_loss_hit": 2,
        "take_profit_hit": 2,
        "execution_update": 1,
    }

    _CLOSE_REASONS: set[str] = {
        "position_close",
        "strategic_exit",
        "stop_loss",
        "take_profit",
        "exchange_reconcile",
        "exchange_backfill",
    }
    _NON_ATTEMPT_ORDER_STATUSES: set[str] = {"retrying", "submitted", "open", "new"}
    _NON_ATTEMPT_ORDER_REASONS: set[str] = {"execution_retry", "execution_status", "execution_update"}

    def _event_reason(event: dict[str, Any]) -> str:
        return str(event.get("reason") or "").strip().lower()

    def _event_reason_rank(event: dict[str, Any]) -> int:
        return _CLOSE_REASON_RANK.get(_event_reason(event), 0)

    def _event_has_entry_exit(event: dict[str, Any]) -> bool:
        return bool(
            (event.get("entry_price") is not None and event.get("exit_price") is not None)
            or (event.get("entryPrice") is not None and event.get("exitPrice") is not None)
        )

    def _event_raw_pnl(event: dict[str, Any]) -> float | None:
        for key in ("net_pnl", "realized_pnl", "gross_pnl", "pnl"):
            value = _safe_float(event.get(key), None)
            if value is not None:
                return value
        return None

    def _event_has_pnl(event: dict[str, Any]) -> bool:
        return _event_raw_pnl(event) is not None

    def _event_has_nonzero_pnl(event: dict[str, Any]) -> bool:
        pnl = _event_raw_pnl(event)
        return pnl is not None and abs(pnl) > 1e-9

    def _event_ts_ms(event: dict[str, Any]) -> int:
        return _to_epoch_ms(
            event.get("last_exec_time_ms")
            or event.get("exec_time_ms")
            or event.get("execTime")
            or event.get("exit_timestamp")
            or event.get("timestamp")
            or event.get("ts")
            or event.get("created_at")
        )

    def _is_close_order_event(event: dict[str, Any]) -> bool:
        position_effect = str(event.get("position_effect") or "").strip().lower()
        reason = _event_reason(event)
        status = str(event.get("status") or "").strip().lower()
        event_type = str(event.get("event_type") or "").strip().lower()
        return (
            position_effect == "close"
            or reason in _CLOSE_REASONS
            or event_type == "closed"
            or status == "closed"
        )

    def _is_meaningful_order_attempt(event: dict[str, Any]) -> bool:
        status = str(event.get("status") or "").strip().lower()
        reason = _event_reason(event)
        order_id = str(event.get("order_id") or "").strip()
        client_order_id = str(event.get("client_order_id") or "").strip()
        if not order_id and not client_order_id:
            return False
        if status in _NON_ATTEMPT_ORDER_STATUSES:
            return False
        if reason in _NON_ATTEMPT_ORDER_REASONS and status not in {"filled", "closed", "failed", "rejected", "canceled"}:
            return False
        return True

    def _is_meaningful_trade_history_event(event: dict[str, Any]) -> bool:
        if not _is_close_order_event(event):
            return False
        if not _is_meaningful_order_attempt(event):
            return False
        if _event_has_entry_exit(event):
            return True
        pnl_val = _event_raw_pnl(event)
        reason = _event_reason(event)
        if pnl_val is not None:
            return True
        return reason in {
            "strategic_exit",
            "stop_loss",
            "take_profit",
            "stop_loss_hit",
            "take_profit_hit",
            "exchange_reconcile",
            "exchange_backfill",
            "position_close",
        }

    def _should_replace_order_event(existing: dict[str, Any], candidate: dict[str, Any]) -> bool:
        existing_reason = _event_reason(existing)
        candidate_reason = _event_reason(candidate)
        generic_close_reasons = {"position_close", "exchange_reconcile", "exchange_backfill"}
        existing_is_generic_reason = existing_reason in generic_close_reasons
        candidate_is_generic_reason = candidate_reason in generic_close_reasons
        # Keep specific semantic close reasons over generic lifecycle/reconcile labels.
        if existing_reason and candidate_reason:
            if existing_is_generic_reason and not candidate_is_generic_reason:
                return True
            if candidate_is_generic_reason and not existing_is_generic_reason:
                return False

        existing_nonzero = _event_has_nonzero_pnl(existing)
        candidate_nonzero = _event_has_nonzero_pnl(candidate)
        if candidate_nonzero and not existing_nonzero:
            return True
        if existing_nonzero and not candidate_nonzero:
            return False

        existing_has_entry_exit = _event_has_entry_exit(existing)
        candidate_has_entry_exit = _event_has_entry_exit(candidate)
        if candidate_has_entry_exit and not existing_has_entry_exit:
            return True
        if existing_has_entry_exit and not candidate_has_entry_exit:
            return False

        existing_rank = _event_reason_rank(existing)
        candidate_rank = _event_reason_rank(candidate)
        if candidate_rank > existing_rank:
            return True
        if existing_rank > candidate_rank:
            return False

        existing_pnl = _event_raw_pnl(existing)
        candidate_pnl = _event_raw_pnl(candidate)
        if (
            existing_pnl is not None
            and candidate_pnl is not None
            and abs(existing_pnl - candidate_pnl) > 1e-6
            and candidate_rank >= existing_rank
        ):
            return True

        return _event_ts_ms(candidate) > _event_ts_ms(existing)

    def _dedupe_order_events(
        events: list[dict[str, Any]],
        *,
        close_only: bool = False,
    ) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
        deduped_by_order: dict[str, dict[str, Any]] = {}
        deduped_without_id: list[dict[str, Any]] = []
        best_pnl_by_order_id: dict[str, dict[str, Any]] = {}

        for event in events:
            if close_only and not _is_close_order_event(event):
                continue

            order_id = str(event.get("order_id") or event.get("client_order_id") or "").strip()
            if not order_id:
                deduped_without_id.append(event)
                continue

            pnl_existing = best_pnl_by_order_id.get(order_id)
            if pnl_existing is None:
                best_pnl_by_order_id[order_id] = event
            else:
                def _pnl_source_rank(evt: dict[str, Any]) -> tuple[int, int, int]:
                    reason = _event_reason(evt)
                    source_rank = 0
                    if reason in {"exchange_reconcile", "exchange_backfill"}:
                        source_rank = 3
                    elif reason == "position_close":
                        source_rank = 2
                    elif _is_close_order_event(evt):
                        source_rank = 1
                    nonzero_rank = 1 if _event_has_nonzero_pnl(evt) else 0
                    return (source_rank, nonzero_rank, _event_ts_ms(evt))

                if _pnl_source_rank(event) > _pnl_source_rank(pnl_existing):
                    best_pnl_by_order_id[order_id] = event

            existing = deduped_by_order.get(order_id)
            if existing is None or _should_replace_order_event(existing, event):
                deduped_by_order[order_id] = event

        return list(deduped_by_order.values()) + deduped_without_id, best_pnl_by_order_id

    def _canonical_close_trades(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        deduped_events, _ = _dedupe_order_events(events, close_only=True)
        trades = [
            _normalize_trade_event(evt)
            for evt in deduped_events
            if _is_meaningful_trade_history_event(evt)
        ]
        return sorted(
            trades,
            key=lambda t: t.get("timestamp") or t.get("ts") or 0,
            reverse=True,
        )

    def _compute_trade_history_stats(trades: list[dict[str, Any]]) -> dict[str, Any]:
        total_trades = len(trades)
        total_pnl = sum(_safe_float(t.get("net_pnl") if t.get("net_pnl") is not None else t.get("pnl")) for t in trades)
        total_gross_pnl = sum(_safe_float(t.get("gross_pnl") if t.get("gross_pnl") is not None else t.get("pnl")) for t in trades)
        total_fees = sum(_safe_float(t.get("fees")) for t in trades)
        winning = [t for t in trades if _safe_float(t.get("net_pnl") if t.get("net_pnl") is not None else t.get("pnl")) > 0]
        losing = [t for t in trades if _safe_float(t.get("net_pnl") if t.get("net_pnl") is not None else t.get("pnl")) < 0]
        breakeven = [t for t in trades if _safe_float(t.get("net_pnl") if t.get("net_pnl") is not None else t.get("pnl")) == 0]
        avg_pnl = (total_pnl / total_trades) if total_trades else 0.0
        largest_win = max([_safe_float(t.get("net_pnl") if t.get("net_pnl") is not None else t.get("pnl")) for t in winning], default=0.0)
        largest_loss = min([_safe_float(t.get("net_pnl") if t.get("net_pnl") is not None else t.get("pnl")) for t in losing], default=0.0)
        win_rate = (len(winning) / total_trades * 100.0) if total_trades else 0.0
        avg_win = (sum(_safe_float(t.get("net_pnl") if t.get("net_pnl") is not None else t.get("pnl")) for t in winning) / len(winning)) if winning else 0.0
        avg_loss = (sum(_safe_float(t.get("net_pnl") if t.get("net_pnl") is not None else t.get("pnl")) for t in losing) / len(losing)) if losing else 0.0
        return {
            "totalTrades": total_trades,
            "totalPnl": total_pnl,
            "totalPnL": total_pnl,
            "totalGrossPnl": total_gross_pnl,
            "winningTrades": len(winning),
            "losingTrades": len(losing),
            "breakEvenTrades": len(breakeven),
            "avgPnl": avg_pnl,
            "avgWin": avg_win,
            "avgLoss": avg_loss,
            "largestWin": largest_win,
            "largestLoss": largest_loss,
            "maxWin": largest_win,
            "maxLoss": largest_loss,
            "winRate": win_rate,
            "totalFees": total_fees,
            "netPnl": total_pnl,
            "avgFeesPerTrade": (total_fees / total_trades) if total_trades else 0.0,
        }

    def _aggregate_execution_quality(events: list[dict[str, Any]]) -> dict[str, Any]:
        fills = [e for e in events if str(e.get("status", "")).lower() in {"filled", "closed"}]
        slippages = [e.get("slippage_bps") for e in fills if e.get("slippage_bps") is not None]
        latencies = [e.get("latency_ms") for e in fills if e.get("latency_ms") is not None]
        total_orders = len(events)
        total_fills = len(fills)
        total_rejects = len([e for e in events if str(e.get("status", "")).lower() in {"rejected", "error"}])
        avg_slippage = sum(slippages) / len(slippages) if slippages else 0.0
        avg_latency = sum(latencies) / len(latencies) if latencies else 0.0
        fill_rate = (total_fills / total_orders * 100.0) if total_orders else 0.0
        return {
            "total_orders": total_orders,
            "total_fills": total_fills,
            "total_rejects": total_rejects,
            "avg_slippage_bps": avg_slippage,
            "avg_execution_time_ms": avg_latency,
            "fill_rate_pct": fill_rate,
        }

    @app.get("/api/runtime/quality", response_model=RuntimeQualityResponse)
    async def get_runtime_quality(
        tenant_id: str,
        bot_id: str,
        redis_client=Depends(_redis_client),
    ):
        reader = RedisSnapshotReader(redis_client)
        key = f"quantgambit:{tenant_id}:{bot_id}:quality:latest"
        payload = await reader.read(key) or {}
        provider_key = f"quantgambit:{tenant_id}:{bot_id}:market_data:provider"
        provider = await reader.read(provider_key) or {}
        control_key = f"quantgambit:{tenant_id}:{bot_id}:control:state"
        control_state = await reader.read(control_key) or {}
        risk_key = f"quantgambit:{tenant_id}:{bot_id}:risk:sizing"
        risk_snapshot = await reader.read(risk_key) or {}
        return RuntimeQualityResponse(
            orderbook_sync_state=payload.get("orderbook_sync_state", "unknown"),
            trade_sync_state=payload.get("trade_sync_state", "unknown"),
            quality_score=payload.get("quality_score"),
            quality_flags=payload.get("flags") or payload.get("quality_flags"),
            active_provider=provider.get("active_provider"),
            switch_count=provider.get("switch_count"),
            last_switch_at=provider.get("last_switch_at"),
            control_state=control_state or None,
            risk_snapshot=risk_snapshot or None,
        )

    @app.post("/api/bot/control", response_model=BotControlResponse, dependencies=[Depends(auth_dep)])
    async def control_bot(
        request: BotControlRequest,
        redis_client=Depends(_redis_client),
    ):
        tenant_id, bot_id = _resolve_scope(request.tenant_id, request.bot_id, require_explicit=True)
        request.tenant_id = tenant_id
        request.bot_id = bot_id
        action = request.action.lower()
        if action == "start":
            return await _publish_control_command(redis_client, "RESUME", request)
        if action == "pause":
            return await _publish_control_command(redis_client, "PAUSE", request)
        if action == "halt":
            return await _publish_control_command(redis_client, "HALT", request, confirm_required=True)
        if action == "flatten":
            return await _publish_control_command(redis_client, "FLATTEN", request, confirm_required=True)
        raise HTTPException(status_code=400, detail="unsupported_action")

    @app.post("/api/bot/start", response_model=BotControlResponse, dependencies=[Depends(auth_dep)])
    async def start_bot(request: BotControlRequest, redis_client=Depends(_redis_client)):
        tenant_id, bot_id = _resolve_scope(request.tenant_id, request.bot_id, require_explicit=True)
        request.tenant_id = tenant_id
        request.bot_id = bot_id
        return await _publish_control_command(redis_client, "RESUME", request)

    @app.post("/api/bot/stop", response_model=BotControlResponse, dependencies=[Depends(auth_dep)])
    async def stop_bot(request: BotControlRequest, redis_client=Depends(_redis_client)):
        tenant_id, bot_id = _resolve_scope(request.tenant_id, request.bot_id, require_explicit=True)
        request.tenant_id = tenant_id
        request.bot_id = bot_id
        return await _publish_control_command(redis_client, "HALT", request, confirm_required=True)

    @app.post("/api/bot/emergency-stop", response_model=BotControlResponse, dependencies=[Depends(auth_dep)])
    async def emergency_stop_bot(request: BotControlRequest, redis_client=Depends(_redis_client)):
        tenant_id, bot_id = _resolve_scope(request.tenant_id, request.bot_id, require_explicit=True)
        request.tenant_id = tenant_id
        request.bot_id = bot_id
        return await _publish_control_command(redis_client, "FLATTEN", request, confirm_required=True)

    @app.get("/api/monitoring/runtime-config", dependencies=[Depends(auth_dep)])
    async def monitoring_runtime_config(
        tenant_id: str | None = None,
        bot_id: str | None = None,
        redis_client=Depends(_redis_client),
    ):
        """Return the active runtime config from the last start command."""
        tenant_id, bot_id = _resolve_scope(tenant_id, bot_id, require_explicit=True)
        # Read the last start command to get the config that was used to launch the bot
        stream_key = f"commands:control:{tenant_id}:{bot_id}"
        try:
            entries = await redis_client.xrevrange(stream_key, count=10)
            for entry_id, entry_data in entries:
                raw = entry_data.get(b"data") or entry_data.get("data")
                if not raw:
                    continue
                if isinstance(raw, bytes):
                    raw = raw.decode("utf-8")
                data = json.loads(raw)
                if data.get("type") == "start_bot":
                    payload = data.get("payload", {})
                    exchange_account = payload.get("exchange_account", {})
                    bot_info = payload.get("bot", {})
                    return {
                        "success": True,
                        "config": {
                            "command_id": data.get("command_id"),
                            "timestamp": data.get("timestamp"),
                            # Basic config
                            "exchange": payload.get("exchange"),
                            "trading_mode": payload.get("trading_mode"),
                            "environment": payload.get("environment"),
                            "market_type": payload.get("market_type"),
                            "margin_mode": payload.get("margin_mode"),
                            "enabled_symbols": payload.get("enabled_symbols", []),
                            "is_testnet": payload.get("is_testnet"),
                            # Risk configuration
                            "risk_config": payload.get("risk_config", {}),
                            # Execution configuration
                            "execution_config": payload.get("execution_config", {}),
                            # Profile overrides (strategy-specific settings)
                            "profile_overrides": payload.get("profile_overrides", {}),
                            # Exchange account info
                            "exchange_account": {
                                "id": exchange_account.get("id"),
                                "label": exchange_account.get("label"),
                                "venue": exchange_account.get("venue"),
                                "environment": exchange_account.get("environment"),
                                "is_testnet": exchange_account.get("is_testnet"),
                                "exchange_balance": exchange_account.get("exchange_balance"),
                                "available_balance": exchange_account.get("available_balance"),
                                "balance_currency": exchange_account.get("balance_currency"),
                            },
                            # Bot info
                            "bot": {
                                "id": bot_info.get("id"),
                                "name": bot_info.get("name"),
                                "allocator_role": bot_info.get("allocator_role"),
                                "trading_mode": bot_info.get("trading_mode"),
                                "default_risk_config": bot_info.get("default_risk_config", {}),
                                "default_execution_config": bot_info.get("default_execution_config", {}),
                            },
                            # Streams
                            "streams": payload.get("streams", {}),
                            # Config version
                            "config_version": payload.get("config_version"),
                            # Metadata
                            "scope": data.get("scope", {}),
                            "requested_by": data.get("requested_by"),
                        },
                    }
        except Exception as e:
            return {"success": False, "config": None, "error": str(e)}
        return {"success": False, "config": None, "error": "No start command found"}

    async def _read_last_start_command(
        redis_client,
        tenant_id: str,
        bot_id: str,
    ) -> dict[str, Any] | None:
        stream_key = f"commands:control:{tenant_id}:{bot_id}"
        entries = await redis_client.xrevrange(stream_key, count=10)
        for _entry_id, entry_data in entries:
            raw = entry_data.get(b"data") or entry_data.get("data")
            if not raw:
                continue
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            data = json.loads(raw)
            if data.get("type") == "start_bot":
                return data
        return None

    async def _fetch_runtime_mapping_payload(pool: asyncpg.Pool, bot_exchange_config_id: str) -> dict[str, Any]:
        row = await _fetch_row(
            pool,
            """
            SELECT id, bot_instance_id, exchange, environment, config_version, trading_capital_usd, enabled_symbols,
                   risk_config, execution_config, profile_overrides, exchange_account_id
            FROM bot_exchange_configs
            WHERE id=$1
            """,
            bot_exchange_config_id,
        )
        if not row:
            raise HTTPException(status_code=404, detail="bot_exchange_config_not_found")
        bot_row = await _fetch_row(
            pool,
            """
            SELECT id, default_risk_config, default_execution_config
            FROM bot_instances
            WHERE id=$1
            """,
            row.get("bot_instance_id"),
        )
        return {
            "exchange": row.get("exchange"),
            "trading_mode": row.get("environment"),
            "config_version": row.get("config_version"),
            "trading_capital_usd": row.get("trading_capital_usd"),
            "exchange_account_id": str(row.get("exchange_account_id")) if row.get("exchange_account_id") else None,
            "enabled_symbols": _coerce_json_list(row.get("enabled_symbols")),
            "risk_config": _coerce_json_dict(row.get("risk_config")),
            "execution_config": _coerce_json_dict(row.get("execution_config")),
            "profile_overrides": _coerce_json_dict(row.get("profile_overrides")),
            "bot": {
                "id": bot_row.get("id") if bot_row else None,
                "default_risk_config": _coerce_json_dict(bot_row.get("default_risk_config")) if bot_row else {},
                "default_execution_config": _coerce_json_dict(bot_row.get("default_execution_config")) if bot_row else {},
            },
        }

    @app.get("/api/dashboard/runtime-config/knobs", dependencies=[Depends(auth_dep)])
    async def dashboard_runtime_knobs():
        return {"success": True, "knobs": knob_catalog()}

    @app.get("/api/dashboard/runtime-config/effective", dependencies=[Depends(auth_dep)])
    async def dashboard_runtime_config_effective(
        bot_exchange_config_id: str = Query(..., alias="botExchangeConfigId"),
        pool=Depends(_dashboard_pool),
    ):
        row = await _fetch_row(
            pool,
            """
            SELECT *
            FROM bot_exchange_configs
            WHERE id=$1
            """,
            bot_exchange_config_id,
        )
        if not row:
            raise HTTPException(status_code=404, detail="bot_exchange_config_not_found")
        return {"success": True, "config": _format_exchange_config(row), "knobs": knob_catalog()}

    @app.get("/api/dashboard/runtime-config/parity", dependencies=[Depends(auth_dep)])
    async def dashboard_runtime_config_parity(
        bot_exchange_config_id: str = Query(..., alias="botExchangeConfigId"),
        pool=Depends(_dashboard_pool),
    ):
        row = await _fetch_row(
            pool,
            "SELECT id, config_version FROM bot_exchange_configs WHERE id=$1",
            bot_exchange_config_id,
        )
        if not row:
            raise HTTPException(status_code=404, detail="bot_exchange_config_not_found")
        payload = await _fetch_runtime_mapping_payload(pool, bot_exchange_config_id)
        parity = preview_runtime_env_parity({}, payload)
        return {
            "success": True,
            "botExchangeConfigId": bot_exchange_config_id,
            "configVersion": row.get("config_version"),
            "parity": parity,
        }

    @app.get("/api/dashboard/runtime-config/export", dependencies=[Depends(auth_dep)])
    async def dashboard_runtime_config_export(
        bot_exchange_config_id: str = Query(..., alias="botExchangeConfigId"),
        pool=Depends(_dashboard_pool),
    ):
        row = await _fetch_row(
            pool,
            "SELECT id, config_version FROM bot_exchange_configs WHERE id=$1",
            bot_exchange_config_id,
        )
        if not row:
            raise HTTPException(status_code=404, detail="bot_exchange_config_not_found")
        payload = await _fetch_runtime_mapping_payload(pool, bot_exchange_config_id)
        exported = export_runtime_env({}, payload)
        return {
            "success": True,
            "botExchangeConfigId": bot_exchange_config_id,
            "configVersion": row.get("config_version"),
            **exported,
        }

    @app.get("/api/dashboard/runtime-config/preflight", dependencies=[Depends(auth_dep)])
    async def dashboard_runtime_config_preflight(
        bot_exchange_config_id: str = Query(..., alias="botExchangeConfigId"),
        pool=Depends(_dashboard_pool),
    ):
        row = await _fetch_row(
            pool,
            """
            SELECT
                bec.id,
                bec.config_version,
                bec.exchange_account_id,
                bi.id AS bot_id,
                bi.user_id AS tenant_id
            FROM bot_exchange_configs bec
            JOIN bot_instances bi ON bi.id = bec.bot_instance_id
            WHERE bec.id=$1
            """,
            bot_exchange_config_id,
        )
        if not row:
            raise HTTPException(status_code=404, detail="bot_exchange_config_not_found")
        payload = await _fetch_runtime_mapping_payload(pool, bot_exchange_config_id)
        exported = export_runtime_env({}, payload)
        runtime_env = exported.get("runtime_env") or {}
        diagnostics = exported.get("diagnostics") or {}
        blockers: list[str] = []
        warnings: list[str] = []

        for key in ("TENANT_ID", "BOT_ID", "ACTIVE_EXCHANGE", "EXCHANGE_ACCOUNT_ID"):
            if not str(runtime_env.get(key) or "").strip():
                blockers.append(f"missing_runtime_env:{key}")

        if not row.get("tenant_id"):
            blockers.append("missing_bot_owner_user_id")
        if not row.get("exchange_account_id"):
            blockers.append("missing_exchange_account_id")

        if diagnostics.get("unmapped_keys"):
            warnings.append("runtime_env_has_unmapped_dashboard_keys")
        if diagnostics.get("missing_payload_keys"):
            warnings.append("runtime_env_missing_payload_keys")

        return {
            "success": len(blockers) == 0,
            "botExchangeConfigId": bot_exchange_config_id,
            "configVersion": row.get("config_version"),
            "scope": {
                "tenant_id": row.get("tenant_id"),
                "bot_id": row.get("bot_id"),
                "exchange_account_id": row.get("exchange_account_id"),
            },
            "blockers": blockers,
            "warnings": warnings,
            "diagnostics": diagnostics,
            "runtimeEnvKeys": sorted(runtime_env.keys()),
        }

    @app.get("/api/dashboard/runtime-config/drift", dependencies=[Depends(auth_dep)])
    async def dashboard_runtime_config_drift(
        bot_exchange_config_id: str = Query(..., alias="botExchangeConfigId"),
        pool=Depends(_dashboard_pool),
        redis_client=Depends(_redis_client),
    ):
        row = await _fetch_row(
            pool,
            """
            SELECT
                bec.id,
                bec.config_version,
                bec.exchange_account_id,
                bi.id AS bot_id,
                bi.user_id AS tenant_id
            FROM bot_exchange_configs bec
            JOIN bot_instances bi ON bi.id = bec.bot_instance_id
            WHERE bec.id=$1
            """,
            bot_exchange_config_id,
        )
        if not row:
            raise HTTPException(status_code=404, detail="bot_exchange_config_not_found")

        tenant_id = str(row.get("tenant_id") or "").strip()
        bot_id = str(row.get("bot_id") or "").strip()
        if not tenant_id or not bot_id:
            raise HTTPException(status_code=400, detail="bot_instance_missing_scope")

        payload = await _fetch_runtime_mapping_payload(pool, bot_exchange_config_id)
        exported = export_runtime_env({}, payload)
        expected_env = exported.get("runtime_env") or {}
        start_command = await _read_last_start_command(redis_client, tenant_id, bot_id)
        if not start_command:
            return {
                "success": False,
                "botExchangeConfigId": bot_exchange_config_id,
                "scope": {"tenant_id": tenant_id, "bot_id": bot_id},
                "error": "no_start_command_found",
            }

        start_payload = start_command.get("payload") or {}
        launched = export_runtime_env({}, start_payload)
        launched_env = launched.get("runtime_env") or {}

        keys_of_interest = sorted(set(expected_env.keys()) | set(launched_env.keys()))
        mismatches: list[dict[str, Any]] = []
        for key in keys_of_interest:
            expected_value = expected_env.get(key)
            launched_value = launched_env.get(key)
            if str(expected_value or "") != str(launched_value or ""):
                mismatches.append(
                    {
                        "key": key,
                        "expected": expected_value,
                        "launched": launched_value,
                    }
                )

        return {
            "success": True,
            "botExchangeConfigId": bot_exchange_config_id,
            "configVersion": row.get("config_version"),
            "scope": {"tenant_id": tenant_id, "bot_id": bot_id},
            "expectedDiagnostics": exported.get("diagnostics") or {},
            "launchedDiagnostics": launched.get("diagnostics") or {},
            "mismatchCount": len(mismatches),
            "mismatches": mismatches,
        }

    @app.get("/api/monitoring/model-contract", dependencies=[Depends(auth_dep)])
    async def monitoring_model_contract():
        config_path_raw = os.getenv("PREDICTION_MODEL_CONFIG", "")
        model_path_raw = os.getenv("PREDICTION_MODEL_PATH", "")
        env_feature_keys = [item.strip() for item in os.getenv("PREDICTION_MODEL_FEATURES", "").split(",") if item.strip()]
        env_class_labels = [item.strip() for item in os.getenv("PREDICTION_MODEL_CLASSES", "").split(",") if item.strip()]

        config_payload: dict[str, Any] = {}
        config_path_resolved = None
        if config_path_raw:
            config_path = Path(config_path_raw)
            if not config_path.is_absolute():
                config_path = (Path(__file__).resolve().parents[3] / config_path).resolve()
            config_path_resolved = str(config_path)
            if config_path.exists():
                try:
                    config_payload = json.loads(config_path.read_text(encoding="utf-8"))
                except Exception as exc:
                    raise HTTPException(status_code=500, detail=f"invalid_model_config:{exc}")

        config_feature_keys = config_payload.get("feature_keys") if isinstance(config_payload.get("feature_keys"), list) else []
        config_class_labels = config_payload.get("class_labels") if isinstance(config_payload.get("class_labels"), list) else []
        feature_drift = env_feature_keys != config_feature_keys if config_feature_keys else False
        class_drift = env_class_labels != config_class_labels if config_class_labels else False

        return {
            "success": True,
            "modelPath": model_path_raw or None,
            "configPath": config_path_resolved,
            "envFeatureKeys": env_feature_keys,
            "configFeatureKeys": config_feature_keys,
            "envClassLabels": env_class_labels,
            "configClassLabels": config_class_labels,
            "featureDrift": feature_drift,
            "classDrift": class_drift,
        }

    @app.post("/api/dashboard/runtime-config/import", dependencies=[Depends(auth_dep)])
    async def dashboard_runtime_config_import(
        payload: dict[str, Any],
        pool=Depends(_dashboard_pool),
    ):
        config_id = str(payload.get("botExchangeConfigId") or payload.get("bot_exchange_config_id") or "").strip()
        if not config_id:
            raise HTTPException(status_code=400, detail="bot_exchange_config_id_required")
        env_overrides = _coerce_json_dict(payload.get("runtimeEnv") or payload.get("runtime_env"))
        if not env_overrides:
            env_overrides = _parse_env_text(str(payload.get("envText") or payload.get("env_text") or ""))
        if not env_overrides:
            raise HTTPException(status_code=400, detail="runtime_env_or_env_text_required")
        dry_run = bool(payload.get("dryRun") if "dryRun" in payload else payload.get("dry_run", True))

        existing = await _fetch_row(pool, "SELECT * FROM bot_exchange_configs WHERE id=$1", config_id)
        if not existing:
            raise HTTPException(status_code=404, detail="bot_exchange_config_not_found")

        patches = _env_overrides_to_db_patches({str(k): str(v) for k, v in env_overrides.items() if v is not None})
        next_config, errors = merge_runtime_config(
            existing,
            risk_patch=patches["risk_patch"],
            execution_patch=patches["execution_patch"],
            profile_patch=patches["profile_patch"],
            enabled_symbols=patches["enabled_symbols"],
        )
        if errors:
            raise HTTPException(status_code=400, detail={"validation_errors": errors})

        proposal = {
            "enabled_symbols": next_config["enabled_symbols"],
            "risk_config": next_config["risk_config"],
            "execution_config": next_config["execution_config"],
            "profile_overrides": next_config["profile_overrides"],
            "trading_capital_usd": patches["trading_capital_usd"] if patches["trading_capital_usd"] is not None else existing.get("trading_capital_usd"),
        }
        if dry_run:
            return {
                "success": True,
                "dryRun": True,
                "botExchangeConfigId": config_id,
                "proposal": proposal,
                "unmapped_env_keys": patches["unmapped_env_keys"],
            }

        change_summary = str(payload.get("changeSummary") or payload.get("change_summary") or "runtime_env_import")
        requested_by_raw = payload.get("requestedBy") or payload.get("requested_by")
        requested_by_uuid: str | None = None
        if requested_by_raw:
            try:
                requested_by_uuid = str(uuid.UUID(str(requested_by_raw)))
            except Exception:
                requested_by_uuid = None
        next_version = int(existing.get("config_version") or 0) + 1
        async with pool.acquire() as conn:
            async with conn.transaction():
                locked = await conn.fetchrow(
                    """
                    SELECT id, config_version
                    FROM bot_exchange_configs
                    WHERE id=$1
                    FOR UPDATE
                    """,
                    config_id,
                )
                if not locked:
                    raise HTTPException(status_code=404, detail="bot_exchange_config_not_found")
                latest_version_row = await conn.fetchrow(
                    "SELECT COALESCE(MAX(version_number), 0) AS max_version FROM bot_exchange_config_versions WHERE bot_exchange_config_id=$1",
                    config_id,
                )
                max_version = int((latest_version_row or {}).get("max_version") or 0)
                next_version = max(int(locked.get("config_version") or 0), max_version) + 1

                version_row = await conn.fetchrow(
                    """
                    INSERT INTO bot_exchange_config_versions
                    (id, bot_exchange_config_id, version_number, trading_capital_usd, enabled_symbols, risk_config, execution_config,
                     profile_overrides, change_summary, change_type, was_activated, activated_at, created_at, created_by)
                    VALUES ($1, $2, $3, $4, $5::jsonb, $6::jsonb, $7::jsonb, $8::jsonb, $9, $10, FALSE, NULL, NOW(), $11)
                    ON CONFLICT (bot_exchange_config_id, version_number) DO UPDATE
                    SET trading_capital_usd=EXCLUDED.trading_capital_usd,
                        enabled_symbols=EXCLUDED.enabled_symbols,
                        risk_config=EXCLUDED.risk_config,
                        execution_config=EXCLUDED.execution_config,
                        profile_overrides=EXCLUDED.profile_overrides,
                        change_summary=EXCLUDED.change_summary,
                        change_type=EXCLUDED.change_type,
                        created_at=NOW(),
                        created_by=EXCLUDED.created_by
                    RETURNING version_number
                    """,
                    str(uuid.uuid4()),
                    config_id,
                    next_version,
                    proposal["trading_capital_usd"],
                    json.dumps(proposal["enabled_symbols"]),
                    json.dumps(proposal["risk_config"]),
                    json.dumps(proposal["execution_config"]),
                    json.dumps(proposal["profile_overrides"]),
                    change_summary,
                    "runtime_env_import",
                    requested_by_uuid,
                )
                persisted_version = int((version_row or {}).get("version_number") or next_version)
                await conn.execute(
                    """
                    UPDATE bot_exchange_configs
                    SET trading_capital_usd=$2,
                        enabled_symbols=$3::jsonb,
                        risk_config=$4::jsonb,
                        execution_config=$5::jsonb,
                        profile_overrides=$6::jsonb,
                        config_version=$7,
                        updated_at=NOW()
                    WHERE id=$1
                    """,
                    config_id,
                    proposal["trading_capital_usd"],
                    json.dumps(proposal["enabled_symbols"]),
                    json.dumps(proposal["risk_config"]),
                    json.dumps(proposal["execution_config"]),
                    json.dumps(proposal["profile_overrides"]),
                    persisted_version,
                )
                next_version = persisted_version

        updated = await _fetch_row(pool, "SELECT * FROM bot_exchange_configs WHERE id=$1", config_id)
        return {
            "success": True,
            "dryRun": False,
            "version": int((updated or {}).get("config_version") or next_version),
            "config": _format_exchange_config(updated),
            "unmapped_env_keys": patches["unmapped_env_keys"],
        }

    @app.post("/api/dashboard/runtime-config/apply", dependencies=[Depends(auth_dep)])
    async def dashboard_runtime_config_apply(
        payload: dict[str, Any],
        pool=Depends(_dashboard_pool),
    ):
        config_id = str(payload.get("botExchangeConfigId") or payload.get("bot_exchange_config_id") or "").strip()
        if not config_id:
            raise HTTPException(status_code=400, detail="bot_exchange_config_id_required")
        existing = await _fetch_row(
            pool,
            """
            SELECT *
            FROM bot_exchange_configs
            WHERE id=$1
            """,
            config_id,
        )
        if not existing:
            raise HTTPException(status_code=404, detail="bot_exchange_config_not_found")

        next_config, errors = merge_runtime_config(
            existing,
            risk_patch=payload.get("riskConfig") or payload.get("risk_config"),
            execution_patch=payload.get("executionConfig") or payload.get("execution_config"),
            profile_patch=payload.get("profileOverrides") or payload.get("profile_overrides"),
            enabled_symbols=payload.get("enabledSymbols") or payload.get("enabled_symbols"),
        )
        if errors:
            raise HTTPException(status_code=400, detail={"validation_errors": errors})

        change_summary = str(payload.get("changeSummary") or payload.get("change_summary") or "dashboard_knob_update")
        requested_by_raw = payload.get("requestedBy") or payload.get("requested_by")
        requested_by_uuid: str | None = None
        if requested_by_raw:
            try:
                requested_by_uuid = str(uuid.UUID(str(requested_by_raw)))
            except Exception:
                requested_by_uuid = None
        next_version = int(existing.get("config_version") or 0) + 1
        async with pool.acquire() as conn:
            async with conn.transaction():
                locked = await conn.fetchrow(
                    """
                    SELECT id, config_version, trading_capital_usd
                    FROM bot_exchange_configs
                    WHERE id=$1
                    FOR UPDATE
                    """,
                    config_id,
                )
                if not locked:
                    raise HTTPException(status_code=404, detail="bot_exchange_config_not_found")
                latest_version_row = await conn.fetchrow(
                    "SELECT COALESCE(MAX(version_number), 0) AS max_version FROM bot_exchange_config_versions WHERE bot_exchange_config_id=$1",
                    config_id,
                )
                max_version = int((latest_version_row or {}).get("max_version") or 0)
                next_version = max(int(locked.get("config_version") or 0), max_version) + 1

                version_row = await conn.fetchrow(
                    """
                    INSERT INTO bot_exchange_config_versions
                    (id, bot_exchange_config_id, version_number, trading_capital_usd, enabled_symbols, risk_config, execution_config,
                     profile_overrides, change_summary, change_type, was_activated, activated_at, created_at, created_by)
                    VALUES ($1, $2, $3, $4, $5::jsonb, $6::jsonb, $7::jsonb, $8::jsonb, $9, $10, FALSE, NULL, NOW(), $11)
                    ON CONFLICT (bot_exchange_config_id, version_number) DO UPDATE
                    SET enabled_symbols=EXCLUDED.enabled_symbols,
                        risk_config=EXCLUDED.risk_config,
                        execution_config=EXCLUDED.execution_config,
                        profile_overrides=EXCLUDED.profile_overrides,
                        change_summary=EXCLUDED.change_summary,
                        change_type=EXCLUDED.change_type,
                        created_at=NOW(),
                        created_by=EXCLUDED.created_by
                    RETURNING version_number
                    """,
                    str(uuid.uuid4()),
                    config_id,
                    next_version,
                    locked.get("trading_capital_usd"),
                    json.dumps(next_config["enabled_symbols"]),
                    json.dumps(next_config["risk_config"]),
                    json.dumps(next_config["execution_config"]),
                    json.dumps(next_config["profile_overrides"]),
                    change_summary,
                    "manual_dashboard",
                    requested_by_uuid,
                )
                persisted_version = int((version_row or {}).get("version_number") or next_version)
                await conn.execute(
                    """
                    UPDATE bot_exchange_configs
                    SET enabled_symbols=$2::jsonb,
                        risk_config=$3::jsonb,
                        execution_config=$4::jsonb,
                        profile_overrides=$5::jsonb,
                        config_version=$6,
                        updated_at=NOW()
                    WHERE id=$1
                    """,
                    config_id,
                    json.dumps(next_config["enabled_symbols"]),
                    json.dumps(next_config["risk_config"]),
                    json.dumps(next_config["execution_config"]),
                    json.dumps(next_config["profile_overrides"]),
                    persisted_version,
                )
                next_version = persisted_version
        updated = await _fetch_row(
            pool,
            """
            SELECT *
            FROM bot_exchange_configs
            WHERE id=$1
            """,
            config_id,
        )
        updated_version = int((updated or {}).get("config_version") or next_version)
        return {"success": True, "config": _format_exchange_config(updated), "version": updated_version}

    @app.get("/api/monitoring/fast-scalper/rejections", response_model=FastScalperRejectionsResponse, dependencies=[Depends(auth_dep)])
    async def monitoring_rejections(
        tenant_id: str | None = None,
        bot_id: str | None = None,
        limit: int = 200,
        redis_client=Depends(_redis_client),
    ):
        tenant_id, bot_id = _resolve_scope(tenant_id, bot_id)
        reader = RedisSnapshotReader(redis_client)
        key = f"quantgambit:{tenant_id}:{bot_id}:decision:rejections"
        history = await reader.read_history(key, limit=limit)
        counts: dict[str, int] = {}
        for item in history:
            reason = str(item.get("rejection_reason") or item.get("reason") or "unknown")
            counts[reason] = counts.get(reason, 0) + 1
        return FastScalperRejectionsResponse(
            recent=history,
            counts=counts,
            timestamp=_now_iso(),
        )

    @app.get("/api/monitoring/fast-scalper/logs", response_model=FastScalperLogsResponse, dependencies=[Depends(auth_dep)])
    async def monitoring_logs(
        limit: int = 200,
        tenant_id: str | None = None,
        bot_id: str | None = Query(default=None, alias="botId"),
        redis_client=Depends(_redis_client),
    ):
        tenant_id, bot_id = _resolve_scope(tenant_id, bot_id)
        stream_key = f"quantgambit:{tenant_id}:{bot_id}:logs"
        records = await _read_stream(redis_client, stream_key, limit=limit)
        logs: list[str] = []
        for rec in records:
            ts = rec.get("ts") or rec.get("timestamp") or rec.get("time")
            level = (rec.get("level") or "info").upper()
            msg = rec.get("msg") or rec.get("message") or ""
            context = rec.get("context")
            parts = [f"[{ts}]" if ts else None, level, str(msg) if msg is not None else ""]
            if context:
                parts.append(str(context))
            logs.append(" ".join(p for p in parts if p))
        return FastScalperLogsResponse(logs=logs, timestamp=_now_iso())

    @app.get("/api/monitoring/fast-scalper", response_model=dict, dependencies=[Depends(auth_dep)])
    async def monitoring_fast_scalper(
        tenant_id: str | None = None,
        bot_id: str | None = Query(default=None, alias="botId"),
        redis_client=Depends(_redis_client),
    ):
        tenant_id, bot_id = _resolve_scope(tenant_id, bot_id)
        reader = RedisSnapshotReader(redis_client)
        positions_payload = await reader.read(f"quantgambit:{tenant_id}:{bot_id}:positions:latest") or {}
        if isinstance(positions_payload, dict):
            positions = positions_payload.get("positions") or []
        else:
            positions = []
        decision_history = await reader.read_history(
            f"quantgambit:{tenant_id}:{bot_id}:decision:history",
            limit=200,
        )
        now = time.time()
        recent_decisions = [
            d
            for d in decision_history
            if _coerce_epoch_timestamp(d.get("timestamp")) and now - _coerce_epoch_timestamp(d.get("timestamp")) <= 60
        ]
        control_state = await reader.read(f"quantgambit:{tenant_id}:{bot_id}:control:state") or {}
        health_state = await reader.read(f"quantgambit:{tenant_id}:{bot_id}:health:latest") or {}
        control_status = str(control_state.get("status") or "").strip().lower()
        python_engine_status = str(
            (health_state.get("services") or {}).get("python_engine", {}).get("status") or ""
        ).strip().lower()
        explicit_stopped = control_status in {"paused", "stopped", "stopping"}
        heartbeat_epoch = _coerce_epoch_timestamp(
            health_state.get("timestamp_epoch") or health_state.get("timestamp")
        )
        heartbeat_age = (time.time() - heartbeat_epoch) if heartbeat_epoch else None
        heartbeat_fresh = heartbeat_age is not None and heartbeat_age <= 30.0
        inferred_running = heartbeat_fresh and (
            control_status in {"running", "starting", "resuming"}
            or python_engine_status in {"running", "online", "ok"}
        )
        decisions_per_sec = (len(recent_decisions) / 60.0) if recent_decisions else 0.0
        order_history = await reader.read_history(
            f"quantgambit:{tenant_id}:{bot_id}:orders:history",
            limit=200,
        )
        if not order_history:
            order_history = await reader.read_history(
                f"quantgambit:{tenant_id}:{bot_id}:order:history",
                limit=200,
            )
        canonical_order_history, _ = _dedupe_order_events(
            [
                item
                for item in order_history
                if isinstance(item, dict) and _is_meaningful_trade_history_event(item)
            ],
            close_only=True,
        )
        canonical_fills = [
            o for o in canonical_order_history if str(o.get("status", "")).lower() in {"filled", "closed"}
        ]
        completed_trades = len(canonical_fills)
        daily_pnl = sum(
            _safe_float(
                o.get("net_pnl")
                if o.get("net_pnl") is not None
                else o.get("realized_pnl")
                if o.get("realized_pnl") is not None
                else o.get("pnl")
            )
            for o in canonical_fills
        )
        warmup_symbols: dict[str, Any] = {}
        warmup_keys = await redis_client.keys(f"quantgambit:{tenant_id}:{bot_id}:warmup:*")
        for key in warmup_keys:
            payload = await redis_client.get(key)
            if not payload:
                continue
            try:
                item = json.loads(payload)
            except Exception:
                continue
            symbol = item.get("symbol")
            if not symbol:
                continue
            warmup_symbols[symbol] = {
                "amt": {"status": "ready" if item.get("ready") else "warming", "progress": item.get("sample_count", 0)},
                "htf": {"status": "unknown", "progress": 0},
                "ready": bool(item.get("ready")),
                "reasons": item.get("reasons") or [],
            }
        if explicit_stopped:
            status = "stopped"
        elif inferred_running:
            status = "running"
        else:
            status = "unknown"
        return {
            "status": status,
            "timestamp": _now_iso(),
            "metrics": {
                "decisionsPerSec": decisions_per_sec,
                "positions": len(positions),
                "maxPositions": len(positions),
                "dailyPnl": daily_pnl,
                "completedTrades": completed_trades,
                "webSocketStatus": "unknown",
            },
            "warmup": {"allWarmedUp": bool(warmup_symbols) and all(v.get("ready") for v in warmup_symbols.values()), "symbols": warmup_symbols},
        }

    @app.get("/api/monitoring/dashboard", response_model=MonitoringDashboardResponse, dependencies=[Depends(auth_dep)])
    async def monitoring_dashboard(redis_client=Depends(_redis_client)):
        redis_connected = False
        try:
            redis_connected = bool(await redis_client.ping())
        except Exception:
            redis_connected = False
        return MonitoringDashboardResponse(
            timestamp=_now_iso(),
            uptime=0,
            nodejs={
                "server": {"running": False, "status": "not_available"},
                "dataCollectors": {"total": 0, "running": 0, "healthy": False, "details": []},
            },
            python={
                "workers": {"total": 1 if redis_connected else 0, "running": 1 if redis_connected else 0, "healthy": redis_connected, "details": []},
                "controlManager": {"running": False},
            },
            redis={
                "connected": redis_connected,
                "pubsub": {"channels": [], "active": False},
                "streams": {"channels": [], "active": False},
            },
            health="healthy" if redis_connected else "unknown",
        )

    @app.get("/api/monitoring/alerts", response_model=MonitoringAlertsResponse, dependencies=[Depends(auth_dep)])
    async def monitoring_alerts(
        tenant_id: str | None = None,
        bot_id: str | None = Query(default=None, alias="botId"),
        redis_client=Depends(_redis_client),
    ):
        tenant_id, bot_id = _resolve_scope(tenant_id, bot_id)
        reader = RedisSnapshotReader(redis_client)
        guardrail = await reader.read(f"quantgambit:{tenant_id}:{bot_id}:guardrail:latest") or {}
        alerts: list[dict[str, Any]] = []
        warnings: list[dict[str, Any]] = []
        if guardrail:
            record = {
                "severity": "warning",
                "component": guardrail.get("type") or "guardrail",
                "name": guardrail.get("symbol") or "global",
                "message": guardrail.get("reason") or guardrail.get("detail") or "guardrail_event",
                "timestamp": _now_iso(),
            }
            warnings.append(record)
        return MonitoringAlertsResponse(
            timestamp=_now_iso(),
            alerts=alerts,
            warnings=warnings,
            total=len(alerts) + len(warnings),
        )

    @app.get("/api/python/bot/status", response_model=BotStatusResponse, dependencies=[Depends(auth_dep)])
    async def python_bot_status(
        tenant_id: str | None = None,
        bot_id: str | None = Query(default=None, alias="botId"),
        redis_client=Depends(_redis_client),
    ):
        tenant_id, bot_id = _resolve_scope(tenant_id, bot_id)
        tenant_id = await _resolve_runtime_tenant_scope(
            redis_client,
            tenant_id,
            bot_id,
            suffixes=["control:state", "health:latest", "warmup:BTCUSDT"],
        )
        reader = RedisSnapshotReader(redis_client)
        control_key = f"quantgambit:{tenant_id}:{bot_id}:control:state"
        control = await reader.read(control_key) or {}
        health = await reader.read(f"quantgambit:{tenant_id}:{bot_id}:health:latest") or {}
        # Read last decision from stream (not history key which may not exist)
        last_decision = {}
        decision_stream = f"events:decisions:{tenant_id}:{bot_id}"
        try:
            entries = await redis_client.xrevrange(decision_stream, count=1)
            if entries:
                entry_id, entry_data = entries[0]
                raw = entry_data.get(b"data") or entry_data.get("data")
                if raw:
                    if isinstance(raw, bytes):
                        raw = raw.decode("utf-8")
                    last_decision = json.loads(raw)
        except Exception:
            pass  # Fall back to empty
        metrics = health.get("metrics") if isinstance(health, dict) else {}
        heartbeat_epoch = _coerce_epoch_timestamp(health.get("timestamp_epoch") or health.get("timestamp"))
        heartbeat_age = (time.time() - heartbeat_epoch) if heartbeat_epoch else None
        # Derive active state: prefer explicit control flags, but infer from fresh
        # runtime heartbeat/service status when control state is temporarily absent.
        if "trading_active" in control:
            is_active = bool(control.get("trading_active"))
            is_paused = not is_active
        elif "trading_paused" in control:
            is_paused = bool(control.get("trading_paused"))
            is_active = not is_paused
        else:
            health_status = str(health.get("status") or "").strip().lower()
            services = health.get("services") if isinstance(health, dict) else {}
            python_engine = services.get("python_engine") if isinstance(services, dict) else {}
            engine_status = str((python_engine or {}).get("status") or "").strip().lower()
            heartbeat_fresh = heartbeat_age is not None and heartbeat_age <= 30.0
            inferred_active = heartbeat_fresh and (
                health_status in {"ok", "running", "healthy"}
                or engine_status in {"running", "online", "ok", "healthy"}
            )
            is_active = bool(inferred_active)
            is_paused = not is_active
        mode = control.get("trading_mode") or health.get("mode") or os.getenv("PREDICTION_MODE") or "unknown"
        # enrich stats with heartbeat/decision even when idle
        stats_payload = {
            "decisions": metrics.get("decisions") if isinstance(metrics, dict) else 0,
            "trades": metrics.get("trades") if isinstance(metrics, dict) else 0,
            "wins": metrics.get("wins") if isinstance(metrics, dict) else 0,
            "losses": metrics.get("losses") if isinstance(metrics, dict) else 0,
            "lastDecision": last_decision,
            "lastHeartbeatAge": heartbeat_age,
        }
        return BotStatusResponse(
            platform={
                "status": health.get("status") or "unknown",
                "uptime": health.get("uptime") or 0,
            },
            trading={
                "isActive": is_active,
                "mode": mode,
                "startTime": control.get("start_time"),
                "stopTime": control.get("stop_time"),
            },
            stats=stats_payload,
            workers={
                "alwaysOn": {},
                "trading": {"health": health},
            },
            dbBotStatus=None,
        )

    @app.get("/api/dashboard/live-status", response_model=dict, dependencies=[Depends(auth_dep)])
    async def dashboard_live_status(
        tenant_id: str | None = None,
        bot_id: str | None = Query(default=None, alias="botId"),
        exchangeAccountId: str | None = None,
        redis_client=Depends(_redis_client),
        timescale=Depends(_timescale_reader_optional),
    ):
        tenant_id, bot_id = _resolve_scope(tenant_id, bot_id)
        tenant_id = await _resolve_runtime_tenant_scope(
            redis_client,
            tenant_id,
            bot_id,
            suffixes=["control:state", "health:latest", "quality:latest", "warmup:BTCUSDT"],
        )
        reader = RedisSnapshotReader(redis_client)
        quality_key = f"quantgambit:{tenant_id}:{bot_id}:quality:latest"
        risk_key = f"quantgambit:{tenant_id}:{bot_id}:risk:sizing"
        health_key = f"quantgambit:{tenant_id}:{bot_id}:health:latest"
        prediction_key = f"quantgambit:{tenant_id}:{bot_id}:prediction:latest"
        decision_key = f"quantgambit:{tenant_id}:{bot_id}:decision:history"
        orders_key = f"quantgambit:{tenant_id}:{bot_id}:orders:history"
        guardrail_key = f"quantgambit:{tenant_id}:{bot_id}:guardrail:latest"
        control_key = f"quantgambit:{tenant_id}:{bot_id}:control:state"
        positions_key = f"quantgambit:{tenant_id}:{bot_id}:positions:latest"
        quality = await reader.read(quality_key) or {}
        risk = await reader.read(risk_key) or {}
        health = await reader.read(health_key) or {}
        prediction = await reader.read(prediction_key) or {}
        guardrail = await reader.read(guardrail_key) or {}
        control = await reader.read(control_key) or {}
        positions_snapshot = await reader.read(positions_key) or {}
        decision_history = await reader.read_history(decision_key, limit=1)
        order_history = await reader.read_history(orders_key, limit=1)
        if not order_history:
            order_history = await reader.read_history(f"quantgambit:{tenant_id}:{bot_id}:order:history", limit=1)
        live_status_query_timeout_sec = max(0.2, float(_safe_float(os.getenv("LIVE_STATUS_QUERY_TIMEOUT_SEC"), 1.2)))

        async def _safe_timescale_fetch(query: str, *params: Any) -> list[Any]:
            if not timescale or not getattr(timescale, "pool", None):
                return []
            try:
                return await asyncio.wait_for(
                    timescale.pool.fetch(query, *params),
                    timeout=live_status_query_timeout_sec,
                )
            except Exception:
                return []
        heartbeat_epoch = _coerce_epoch_timestamp(health.get("timestamp_epoch") or health.get("timestamp"))
        age_seconds = None
        if heartbeat_epoch:
            age_seconds = max(0.0, time.time() - heartbeat_epoch)
        heartbeat_status = "stale"
        if age_seconds is None:
            heartbeat_status = "unknown"
        elif age_seconds <= 15:
            heartbeat_status = "ok"
        elif age_seconds > 60:
            heartbeat_status = "dead"
        decision = decision_history[0] if decision_history else {}
        order = order_history[0] if order_history else {}
        # Compute quality score - prefer quality:latest, fallback to health data
        quality_score = _safe_float(quality.get("quality_score")) * 100.0 if quality.get("quality_score") else 0.0
        if quality_score == 0.0 and health:
            # Compute from health metrics: 100% minus penalties for stale/gap/skew/out_of_order
            stale_pct = _safe_float(health.get("market_data_stale_pct"))
            gap_pct = _safe_float(health.get("market_data_gap_pct"))
            skew_pct = _safe_float(health.get("market_data_skew_pct"))
            out_of_order_pct = _safe_float(health.get("market_data_out_of_order_pct"))
            tick_age = _safe_float(health.get("last_tick_age_sec"))
            # Start at 100%, penalize for issues
            score = 100.0
            score -= stale_pct * 0.4  # Stale data is bad
            score -= gap_pct * 0.3    # Gaps are concerning
            score -= skew_pct * 0.1   # Skew is minor
            score -= out_of_order_pct * 0.1  # Out of order is minor
            if tick_age and tick_age > 5:
                score -= min(30, tick_age * 3)  # Penalize old ticks
            quality_score = max(0.0, min(100.0, score))
        # Check guardian status.
        #
        # Prefer tenant guardian heartbeat when present, but fall back to the runtime
        # health snapshot's position_guardian status for deployments that use only the
        # in-runtime position guard worker.
        guardian_key = f"guardian:tenant:{tenant_id}:health"
        guardian_health = await reader.read(guardian_key) or {}
        runtime_guardian = None
        if isinstance(health, dict):
            runtime_guardian = (
                health.get("position_guardian")
                or health.get("position_guard")
                or ((health.get("services") or {}).get("position_guardian") if isinstance(health.get("services"), dict) else None)
            )
        runtime_guardian_config = runtime_guardian.get("config") if isinstance(runtime_guardian, dict) else {}
        if not isinstance(runtime_guardian_config, dict):
            runtime_guardian_config = {}
        runtime_guardian_reason = runtime_guardian.get("reason") if isinstance(runtime_guardian, dict) else None

        guardian_running = False
        guardian_status = "stopped"
        guardian_age = None
        guardian_timestamp = None
        accounts_monitored = 0

        # Source 1: dedicated tenant guardian heartbeat.
        if guardian_health:
            guardian_timestamp = guardian_health.get("timestamp")
            accounts_monitored = int(guardian_health.get("accounts_monitored", 0) or 0)
            if guardian_timestamp:
                guardian_age = max(0.0, time.time() - float(guardian_timestamp))
                guardian_running = guardian_age <= 60 and guardian_health.get("status") == "running"
                guardian_status = "running" if guardian_running else "stopped"

        # Source 2 fallback: runtime position guard heartbeat.
        if (not guardian_running) and isinstance(runtime_guardian, dict):
            runtime_ts = runtime_guardian.get("timestamp")
            runtime_status = str(runtime_guardian.get("status") or "").strip().lower()
            if runtime_status == "misconfigured":
                guardian_status = "misconfigured"
            if runtime_ts:
                try:
                    runtime_age = max(0.0, time.time() - float(runtime_ts))
                except (TypeError, ValueError):
                    runtime_age = None
                if runtime_age is not None:
                    guardian_age = runtime_age
                    guardian_timestamp = runtime_ts
                    # Runtime guard ticks every second; 60s keeps parity with tenant guardian logic.
                    guardian_running = runtime_age <= 60 and runtime_status in {"running", "ok"}
                    if guardian_running:
                        guardian_status = "running"
            elif runtime_status in {"running", "ok"}:
                guardian_running = True
                guardian_status = "running"
        
        payload = {
            "heartbeat": {
                "status": heartbeat_status,
                "lastTickTime": health.get("timestamp") or health.get("timestamp_epoch"),
                "ageSeconds": age_seconds,
            },
            "lastDecision": {
                "approved": None if not decision else decision.get("result") != "REJECT",
                "reason": decision.get("rejection_reason"),
                "time": decision.get("timestamp"),
                "symbol": decision.get("symbol"),
            },
            "lastOrder": {
                "status": order.get("status") or "none",
                "latency": order.get("latency_ms"),
                "time": order.get("timestamp"),
                "symbol": order.get("symbol"),
            },
            "riskState": {
                "status": "paused" if control.get("trading_paused") else "ok",
                "guardrail": guardrail.get("type"),
                "pausedBy": guardrail.get("reason"),
            },
            "dataQuality": {
                "score": quality_score,
                "gapCount": int(quality.get("gap_count") or 0) if quality else 0,
                "staleSymbols": [],
            },
            "quality": quality,
            "risk": risk,
            "health": health,
            "prediction": prediction,
            "position_guardian": {
                "status": guardian_status,
                "reason": runtime_guardian_reason,
                "timestamp": guardian_timestamp,
                "ageSeconds": guardian_age,
                "accountsMonitored": accounts_monitored,
                "config": {
                    "maxAgeSec": _safe_float(runtime_guardian_config.get("maxAgeSec"), _safe_float(os.getenv("POSITION_GUARD_MAX_AGE_SEC"), 0.0)),
                    "hardMaxAgeSec": _safe_float(runtime_guardian_config.get("hardMaxAgeSec"), _safe_float(os.getenv("POSITION_GUARD_MAX_AGE_HARD_SEC"), 0.0)),
                    "maxAgeConfirmations": int(_safe_float(runtime_guardian_config.get("maxAgeConfirmations"), _safe_float(os.getenv("POSITION_GUARD_MAX_AGE_CONFIRMATIONS"), 1))),
                    "maxAgeExtensionSec": _safe_float(runtime_guardian_config.get("maxAgeExtensionSec"), _safe_float(os.getenv("POSITION_GUARD_MAX_AGE_EXTENSION_SEC"), 0.0)),
                    "maxAgeMaxExtensions": int(_safe_float(runtime_guardian_config.get("maxAgeMaxExtensions"), _safe_float(os.getenv("POSITION_GUARD_MAX_AGE_MAX_EXTENSIONS"), 0))),
                    "continuationEnabled": bool(
                        runtime_guardian_config.get("continuationEnabled")
                        if runtime_guardian_config.get("continuationEnabled") is not None
                        else str(os.getenv("POSITION_CONTINUATION_GATE_ENABLED", "true")).lower() in {"1", "true", "yes"}
                    ),
                },
            },
        }
        
        # Add orchestrator stats for decision funnel - query from TimescaleDB
        orchestrator_key = f"quantgambit:{tenant_id}:{bot_id}:orchestrator:stats"
        orchestrator_stats = await reader.read(orchestrator_key) or {}
        
        # Get stats from TimescaleDB for accurate counts
        db_stats = {}
        try:
            # Get decision counts from last hour - handle multiple result field values
            decision_rows = await _safe_timescale_fetch(
                """SELECT 
                    COUNT(*) as total_decisions,
                    COUNT(*) FILTER (WHERE payload->>'result' IN ('COMPLETE', 'ACCEPTED', 'APPROVE', 'approved')) as approved,
                    COUNT(*) FILTER (WHERE payload->>'result' IN ('REJECT', 'REJECTED', 'rejected')) as rejected
                FROM decision_events 
                WHERE tenant_id=$1 AND bot_id=$2 AND ts > NOW() - INTERVAL '1 hour'""",
                tenant_id, bot_id
            )
            if decision_rows:
                db_stats["total_decisions"] = decision_rows[0].get("total_decisions", 0)
                db_stats["approved"] = decision_rows[0].get("approved", 0)
                db_stats["rejected"] = decision_rows[0].get("rejected", 0)
            
            # Get order counts from order_events with same time window as decisions
            order_rows = await _safe_timescale_fetch(
                """SELECT 
                    COUNT(DISTINCT COALESCE(NULLIF(payload->>'order_id', ''), NULLIF(payload->>'client_order_id', '')))
                        FILTER (
                            WHERE COALESCE(NULLIF(payload->>'order_id', ''), NULLIF(payload->>'client_order_id', '')) IS NOT NULL
                              AND lower(coalesce(payload->>'status', '')) NOT IN ('retrying', 'submitted', 'open', 'new')
                        ) as total_orders,
                    COUNT(DISTINCT COALESCE(NULLIF(payload->>'order_id', ''), NULLIF(payload->>'client_order_id', '')))
                        FILTER (
                            WHERE COALESCE(NULLIF(payload->>'order_id', ''), NULLIF(payload->>'client_order_id', '')) IS NOT NULL
                              AND lower(coalesce(payload->>'status', '')) IN ('filled', 'closed')
                        ) as fills,
                    COUNT(DISTINCT COALESCE(NULLIF(payload->>'order_id', ''), NULLIF(payload->>'client_order_id', '')))
                        FILTER (
                            WHERE COALESCE(NULLIF(payload->>'order_id', ''), NULLIF(payload->>'client_order_id', '')) IS NOT NULL
                              AND lower(coalesce(payload->>'status', '')) IN ('rejected', 'failed')
                              AND lower(coalesce(payload->>'reason', '')) <> 'execution_retry'
                        ) as rejects
                FROM order_events 
                WHERE tenant_id=$1 AND bot_id=$2 AND ts > NOW() - INTERVAL '1 hour'""",
                tenant_id, bot_id
            )
            if order_rows:
                db_stats["total_orders"] = order_rows[0].get("total_orders", 0)
                db_stats["fills"] = order_rows[0].get("fills", 0)
                db_stats["rejects"] = order_rows[0].get("rejects", 0)
            
            # Get top rejection reasons from decision_events
            reject_rows = await _safe_timescale_fetch(
                """SELECT payload->>'rejection_reason' as reason, COUNT(*) as cnt
                FROM decision_events 
                WHERE tenant_id=$1 AND bot_id=$2 
                  AND ts > NOW() - INTERVAL '1 hour'
                  AND payload->>'result' IN ('REJECT', 'REJECTED', 'rejected')
                  AND payload->>'rejection_reason' IS NOT NULL
                GROUP BY payload->>'rejection_reason'
                ORDER BY cnt DESC
                LIMIT 5""",
                tenant_id, bot_id
            )
            db_stats["top_rejects"] = [{"reason": r["reason"], "count": r["cnt"]} for r in reject_rows if r.get("reason")]
        except Exception as e:
            pass  # Fall back to Redis-only stats
        
        # Get decision history for rejection reasons (Redis fallback)
        full_decision_history = await reader.read_history(decision_key, limit=100)
        rejection_reasons: dict[str, int] = {}
        signals_generated = 0
        signals_rejected = 0
        for dec in full_decision_history:
            result = dec.get("result") or dec.get("decision")
            if result == "REJECT" or result == "rejected":
                signals_rejected += 1
                reason = dec.get("rejection_reason") or dec.get("reason") or "unknown"
                rejection_reasons[reason] = rejection_reasons.get(reason, 0) + 1
            elif result in ("APPROVE", "approved"):
                signals_generated += 1
        
        # Use DB stats if available, otherwise use Redis stats
        events_ingested = (
            db_stats.get("total_decisions", 0)
            or orchestrator_stats.get("events_ingested")
            or len(full_decision_history)
        )
        signals_gen_final = db_stats.get("approved", 0) or signals_generated
        signals_rej_final = db_stats.get("rejected", 0) or signals_rejected
        orders_placed = db_stats.get("total_orders", 0) or orchestrator_stats.get("orders_placed", 0)
        fills_count = db_stats.get("fills", 0) or orchestrator_stats.get("fills", 0)
        
        # Build top rejection reasons - prefer DB stats
        if db_stats.get("top_rejects"):
            top_reject_reasons = db_stats["top_rejects"]
        else:
            top_reject_reasons = sorted(
                [{"reason": r, "count": c} for r, c in rejection_reasons.items()],
                key=lambda x: x["count"],
                reverse=True
            )[:5]
        
        # Get blade signals / guardrails
        blade_signals: dict[str, str] = {}
        if guardrail:
            blade_signals["risk"] = "block" if guardrail.get("type") else "allow"
        if control.get("trading_paused"):
            blade_signals["trading"] = "block"
        else:
            blade_signals["trading"] = "allow"
        
        payload["orchestratorStats"] = {
            "eventsIngested": events_ingested,
            "signalsGenerated": signals_gen_final,
            "signalsRejected": signals_rej_final,
            "ordersPlaced": orders_placed,
            "fills": fills_count,
            "decisionsPerSec": orchestrator_stats.get("decisions_per_sec") or (events_ingested / 3600 if events_ingested else 0),
        }
        payload["topRejectReasons"] = top_reject_reasons
        payload["bladeSignals"] = blade_signals
        
        # Calculate top symbols exposure from positions with signals, pnl, slippage
        positions = positions_snapshot.get("positions") or []
        symbol_stats: dict[str, dict[str, Any]] = {}
        # Use a rolling 24h window (not UTC day-boundary) so dashboard PnL block
        # reflects recent trading activity consistently.
        metrics_window_hours = 24
        window_start = datetime.now(timezone.utc) - timedelta(hours=metrics_window_hours)
        
        # Initialize from positions with exposure and unrealized PnL
        for pos in positions:
            symbol = pos.get("symbol", "UNKNOWN")
            qty = _safe_float(pos.get("size") or pos.get("quantity") or 0)
            entry_price = _safe_float(pos.get("entry_price") or pos.get("price") or 0)
            mark_price = _safe_float(pos.get("reference_price") or pos.get("current_price") or pos.get("mark_price") or entry_price)
            notional = abs(qty * entry_price)
            side = str(pos.get("side") or "").upper()
            
            # Calculate unrealized PnL for this position
            unrealized = 0.0
            if entry_price and mark_price and qty:
                if side in {"LONG", "BUY"}:
                    unrealized = (mark_price - entry_price) * qty
                else:
                    unrealized = (entry_price - mark_price) * qty
            
            if symbol not in symbol_stats:
                symbol_stats[symbol] = {
                    "symbol": symbol, 
                    "longExposure": 0.0, 
                    "shortExposure": 0.0, 
                    "netExposure": 0.0,
                    "signals": 0,
                    "pnl": 0.0,
                    "slippage": 0.0,
                }
            if side in {"LONG", "BUY"}:
                symbol_stats[symbol]["longExposure"] += notional
                symbol_stats[symbol]["netExposure"] += notional
            else:
                symbol_stats[symbol]["shortExposure"] += notional
                symbol_stats[symbol]["netExposure"] -= notional
            symbol_stats[symbol]["pnl"] += unrealized
        
        # Get per-symbol stats from order_events (signals, slippage)
        try:
            # Use order_events which has the symbol column populated
            symbol_order_stats = await _safe_timescale_fetch(
                """SELECT 
                    symbol,
                    COUNT(*) as order_count,
                    AVG((payload->>'slippage_bps')::numeric) FILTER (WHERE payload->>'slippage_bps' IS NOT NULL) as avg_slippage
                FROM order_events 
                WHERE tenant_id=$1 AND bot_id=$2 AND symbol IS NOT NULL AND ts >= $3
                GROUP BY symbol""",
                tenant_id, bot_id, window_start
            )
            
            for row in symbol_order_stats:
                sym = row.get("symbol")
                if not sym:
                    continue
                if sym not in symbol_stats:
                    symbol_stats[sym] = {
                        "symbol": sym, 
                        "longExposure": 0.0, 
                        "shortExposure": 0.0, 
                        "netExposure": 0.0,
                        "signals": 0,
                        "pnl": 0.0,
                        "slippage": 0.0,
                    }
                symbol_stats[sym]["signals"] = row.get("order_count", 0) or 0
                symbol_stats[sym]["slippage"] = round(_safe_float(row.get("avg_slippage")), 2)

            # Prefer realized PnL from position_events (single source of truth)
            symbol_realized_stats = await _safe_timescale_fetch(
                """SELECT 
                    symbol,
                    SUM(COALESCE((payload->>'net_pnl')::numeric, (payload->>'realized_pnl')::numeric))
                        FILTER (WHERE (payload->>'net_pnl') IS NOT NULL OR (payload->>'realized_pnl') IS NOT NULL) as realized_pnl
                FROM position_events
                WHERE tenant_id=$1 AND bot_id=$2 AND symbol IS NOT NULL AND ts >= $3
                AND (payload->>'event_type' = 'closed' OR payload::text LIKE '%\"status\": \"closed\"%')
                GROUP BY symbol""",
                tenant_id, bot_id, window_start
            )
            for row in symbol_realized_stats:
                sym = row.get("symbol")
                if not sym:
                    continue
                if sym not in symbol_stats:
                    symbol_stats[sym] = {
                        "symbol": sym, 
                        "longExposure": 0.0, 
                        "shortExposure": 0.0, 
                        "netExposure": 0.0,
                        "signals": 0,
                        "pnl": 0.0,
                        "slippage": 0.0,
                    }
                realized = _safe_float(row.get("realized_pnl"))
                symbol_stats[sym]["pnl"] += realized
        except Exception as e:
            pass  # Fall back to position-only data
        
        top_symbols = sorted(
            list(symbol_stats.values()),
            key=lambda x: abs(x.get("netExposure", 0)),
            reverse=True
        )[:5]
        payload["topSymbols"] = top_symbols
        
        # Calculate unrealized PnL from positions
        unrealized_pnl = 0.0
        gross_exposure = 0.0
        net_exposure = 0.0
        for pos in positions:
            qty = _safe_float(pos.get("size") or pos.get("quantity") or 0)
            entry_price = _safe_float(pos.get("entry_price") or pos.get("price") or 0)
            mark_price = _safe_float(
                pos.get("reference_price")
                or pos.get("current_price")
                or pos.get("mark_price")
                or entry_price
            )
            side = str(pos.get("side") or "").lower()
            # Calculate PnL
            if entry_price and mark_price and qty:
                if side in {"long", "buy"}:
                    unrealized_pnl += (mark_price - entry_price) * qty
                elif side in {"short", "sell"}:
                    unrealized_pnl += (entry_price - mark_price) * qty
            # Calculate exposure
            notional = abs(qty * mark_price) if mark_price else 0.0
            gross_exposure += notional
            if side in {"long", "buy"}:
                net_exposure += notional
            else:
                net_exposure -= notional
        
        payload["unrealizedPnl"] = unrealized_pnl
        payload["grossExposure"] = gross_exposure
        payload["netExposure"] = net_exposure
        
        # Add rejectRate and pendingOrders in the format frontend expects
        # Get pending orders
        all_orders = await reader.read_history(orders_key, limit=100) or []
        pending_statuses = {"new", "open", "pending", "partially_filled", "submitted"}
        pending_orders = [o for o in all_orders if str(o.get("status", "")).lower() in pending_statuses]
        oldest_pending_age = 0.0
        now_ts = time.time()
        for o in pending_orders:
            order_ts = _coerce_epoch_timestamp(o.get("timestamp") or o.get("created_at") or o.get("ts"))
            if order_ts:
                age = now_ts - order_ts
                if age > oldest_pending_age:
                    oldest_pending_age = age
        
        # Calculate reject rates (5m and 1h)
        try:
            reject_5m_rows = await asyncio.wait_for(timescale.pool.fetch(
                """SELECT COUNT(*) as total,
                    COUNT(*) FILTER (WHERE payload->>'result' IN ('REJECT', 'REJECTED', 'rejected')) as rejected
                FROM decision_events 
                WHERE tenant_id=$1 AND bot_id=$2 AND ts > NOW() - INTERVAL '5 minutes'""",
                tenant_id, bot_id
            ), timeout=live_status_query_timeout_sec)
            total_5m = reject_5m_rows[0].get("total", 0) if reject_5m_rows else 0
            rejected_5m = reject_5m_rows[0].get("rejected", 0) if reject_5m_rows else 0
            reject_rate_5m = (rejected_5m / total_5m * 100.0) if total_5m > 0 else 0.0
            
            reject_1h_rows = await asyncio.wait_for(timescale.pool.fetch(
                """SELECT COUNT(*) as total,
                    COUNT(*) FILTER (WHERE payload->>'result' IN ('REJECT', 'REJECTED', 'rejected')) as rejected
                FROM decision_events 
                WHERE tenant_id=$1 AND bot_id=$2 AND ts > NOW() - INTERVAL '1 hour'""",
                tenant_id, bot_id
            ), timeout=live_status_query_timeout_sec)
            total_1h = reject_1h_rows[0].get("total", 0) if reject_1h_rows else 0
            rejected_1h = reject_1h_rows[0].get("rejected", 0) if reject_1h_rows else 0
            reject_rate_1h = (rejected_1h / total_1h * 100.0) if total_1h > 0 else 0.0
        except Exception:
            reject_rate_5m = 0.0
            reject_rate_1h = 0.0
        
        # Get top rejection reason
        top_reason = ""
        top_reason_count = 0
        if top_reject_reasons:
            top_reason = top_reject_reasons[0].get("reason", "")
            top_reason_count = top_reject_reasons[0].get("count", 0)
        
        payload["rejectRate"] = {
            "last5m": round(reject_rate_5m, 1),
            "last1h": round(reject_rate_1h, 1),
            "topReason": top_reason,
            "topReasonCount": top_reason_count,
        }
        payload["pendingOrders"] = {
            "count": len(pending_orders),
            "oldestAgeSeconds": round(oldest_pending_age, 1),
        }
        
        # Calculate drawdown from authoritative risk/account state only.
        # Never synthesize equity from PAPER_EQUITY for dashboard consumers.
        starting_equity = _safe_float(
            risk.get("equity")
            or risk.get("current_equity")
            or risk.get("account_equity")
            or risk.get("initial_equity")
        )
        peak_equity = _safe_float(risk.get("peak_equity") or risk.get("peak_balance") or risk.get("initial_equity"))
        current_equity = None
        drawdown_pct = 0.0
        if starting_equity is not None and starting_equity > 0:
            current_equity = starting_equity + unrealized_pnl
            if peak_equity is None or peak_equity <= 0:
                peak_equity = starting_equity
            drawdown_pct = max(0.0, (peak_equity - current_equity) / peak_equity * 100) if peak_equity > 0 else 0.0
        
        # Update risk object with calculated drawdown
        payload["risk"] = {
            **risk,
            "drawdown": round(drawdown_pct, 2),
            "rolling_drawdown": round(drawdown_pct, 2),
            "unrealized_pnl": round(unrealized_pnl, 2),
            "current_equity": round(current_equity, 2) if current_equity is not None else None,
            "peak_equity": round(peak_equity, 2) if peak_equity is not None else None,
        }
        
        # Add botStatus field for frontend compatibility.
        # A bot is "running" only when a fresh runtime heartbeat exists.
        # Historical decisions/orders may continue to exist after shutdown and
        # must not keep the bot in a false live state.
        control_active = bool(control.get("trading_active")) and not bool(control.get("trading_paused"))
        if heartbeat_status == "ok":
            bot_status = "running"
        elif heartbeat_status == "stale":
            bot_status = "slow" if control_active else "stopped"
        else:
            bot_status = "stopped"
        payload["botStatus"] = bot_status
        
        # Also add funnel data for WhyNoTrades component
        # The funnel shows: evaluated -> gated -> approved -> ordered -> filled
        payload["funnel"] = {
            "evaluated": events_ingested,
            "gated": signals_gen_final + signals_rej_final,  # All signals that passed initial evaluation
            "approved": signals_gen_final,
            "ordered": orders_placed,
            "filled": fills_count,
            "isLive": heartbeat_status == "ok",
        }

        # AI Sentiment data from Redis
        sentiment_symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
        sentiment_data = {}
        for sym in sentiment_symbols:
            raw = await redis_client.get(f"ai:sentiment:{sym}")
            if raw:
                try:
                    import json as _json
                    sentiment_data[sym] = _json.loads(raw)
                except Exception:
                    pass
        global_raw = await redis_client.get("ai:sentiment:global")
        if global_raw:
            try:
                import json as _json
                sentiment_data["global"] = _json.loads(global_raw)
            except Exception:
                pass
        payload["sentiment"] = sentiment_data

        # AI Param Tuner suggestions from Redis
        tuner_raw = await redis_client.get(f"ai:param_suggestions:{bot_id}")
        if tuner_raw:
            try:
                import json as _json
                payload["paramSuggestions"] = _json.loads(tuner_raw)
            except Exception:
                pass
        
        return payload

    @app.get("/api/dashboard/state", response_model=dict, dependencies=[Depends(auth_dep)])
    async def dashboard_state(
        tenant_id: str | None = None,
        bot_id: str | None = None,
        redis_client=Depends(_redis_client),
    ):
        tenant_id, bot_id = _resolve_scope(tenant_id, bot_id)
        reader = RedisSnapshotReader(redis_client)
        key = f"quantgambit:{tenant_id}:{bot_id}:control:state"
        control_state = await reader.read(key) or {}
        raw_health = await reader.read(f"quantgambit:{tenant_id}:{bot_id}:health:latest") or {}
        health = _normalize_service_health(raw_health) if raw_health else {}
        warmup = await reader.read(f"quantgambit:{tenant_id}:{bot_id}:warmup:overall") or {}
        risk = await reader.read(f"quantgambit:{tenant_id}:{bot_id}:risk:sizing") or {}
        market_data = await reader.read(f"quantgambit:{tenant_id}:{bot_id}:market_data:latest") or {}
        trading_mode = str(control_state.get("trading_mode") or os.getenv("TRADING_MODE", "unknown")).lower()
        control_active = bool(control_state.get("trading_active"))
        inferred_active = bool((health or {}).get("all_ready")) and not bool(control_state.get("trading_paused", False))
        risk_status = str((risk or {}).get("status") or (risk or {}).get("gate_status") or "").strip().lower()
        risk_blocked = bool((risk or {}).get("blocked")) or bool((risk or {}).get("rejected"))
        if risk_status in {"blocked", "rejected", "deny", "halted", "paused", "disabled"}:
            risk_blocked = True
        risk_ok = (not risk_blocked) and (
            risk_status in {"", "ok", "accepted", "allow", "ready", "pass", "passing"}
            or bool((risk or {}).get("can_trade", True))
        )
        payload = {
            "serviceHealth": health,
            "resourceUsage": None,
            "componentDiagnostics": None,
            "control": control_state,
            "apiContractVersion": "2026-02-24",
            # Canonical dashboard contract fields (never omitted).
            "marketData": market_data if isinstance(market_data, dict) else {},
            "trading": {
                "mode": trading_mode,
                "active": bool(control_active or inferred_active),
                "paused": bool(control_state.get("trading_paused", False)),
                "disabled": bool(str(os.getenv("TRADING_DISABLED", "false")).lower() in {"1", "true", "yes"}),
            },
            "dataReadiness": {
                "ready": bool(warmup.get("ready", False)) if isinstance(warmup, dict) else False,
                "progress": _safe_float(warmup.get("progress"), 0.0) if isinstance(warmup, dict) else 0.0,
            },
            "gates": {
                "risk_ok": bool(risk_ok),
                "service_health_ok": bool((health or {}).get("all_ready", False)),
            },
            "mode": trading_mode,
            "updatedAt": int(time.time() * 1000),
        }
        return payload

    @app.get("/api/dashboard/warmup", response_model=dict, dependencies=[Depends(auth_dep)])
    async def dashboard_warmup(
        tenant_id: str | None = None,
        bot_id: str | None = Query(default=None, alias="botId"),
        bot_id_snake: str | None = Query(default=None, alias="bot_id"),
        redis_client=Depends(_redis_client),
    ):
        if not bot_id and bot_id_snake:
            bot_id = bot_id_snake
        tenant_id, bot_id = _resolve_scope(tenant_id, bot_id)
        reader = RedisSnapshotReader(redis_client)
        resolved_tenant_id = tenant_id
        keys = await redis_client.keys(f"quantgambit:{tenant_id}:{bot_id}:warmup:*")
        if not keys and bot_id:
            wildcard_keys = await redis_client.keys(f"quantgambit:*:{bot_id}:warmup:*")
            if wildcard_keys:
                keys = wildcard_keys
                try:
                    sample_key = str(wildcard_keys[0])
                    parts = sample_key.split(":")
                    if len(parts) >= 5:
                        resolved_tenant_id = parts[1]
                except Exception:
                    resolved_tenant_id = tenant_id
        if bot_id:
            try:
                candle_count_key = f"quantgambit:{resolved_tenant_id}:{bot_id}:candle_counts"
                candle_count_exists = await redis_client.exists(candle_count_key)
            except Exception:
                candle_count_exists = 0
            if not candle_count_exists:
                wildcard_candle_keys = await redis_client.keys(f"quantgambit:*:{bot_id}:candle_counts")
                if wildcard_candle_keys:
                    try:
                        sample_key = str(wildcard_candle_keys[0])
                        parts = sample_key.split(":")
                        if len(parts) >= 4:
                            resolved_tenant_id = parts[1]
                    except Exception:
                        resolved_tenant_id = tenant_id
        symbols: dict[str, Any] = {}
        progress_values: list[float] = []

        def _ingest_warmup_item(item: dict) -> tuple[str | None, dict]:
            symbol = item.get("symbol")
            if not symbol:
                return None, {}
            sample_count = float(item.get("sample_count") or 0)
            min_samples = float(item.get("min_samples") or 0) or 1.0
            candle_count = item.get("candle_count") or 0
            min_candles = item.get("min_candles") or 0
            ready = bool(item.get("ready"))
            quality_score = item.get("quality_score")
            flags = item.get("quality_flags") or []
            reasons = item.get("reasons") or []
            sample_pct = min(100.0, (sample_count / max(min_samples, 1.0)) * 100.0)
            candle_pct = (
                min(100.0, (float(candle_count) / max(float(min_candles or 1), 1.0)) * 100.0)
                if min_candles
                else 100.0
            )
            progress_pct = min(100.0, (sample_pct + candle_pct) / 2.0)
            progress_values.append(progress_pct)
            return symbol, {
                "amt": {
                    "status": "ready" if ready else "warming",
                    "progress": progress_pct,
                    "sampleCount": sample_count,
                    "minSamples": min_samples,
                    "candleCount": candle_count,
                    "minCandles": min_candles,
                    "qualityScore": quality_score,
                    "flags": flags,
                },
                "htf": {
                    "status": "unknown",
                    "progress": 0,
                    "candles": None,
                },
                "overallReady": ready,
                "overallProgress": progress_pct,
                "reasons": reasons,
            }

        for key in keys:
            payload = await redis_client.get(key)
            if not payload:
                continue
            try:
                item = json.loads(payload)
            except Exception:
                continue
            symbol, entry = _ingest_warmup_item(item)
            if symbol:
                symbols[symbol] = entry

        if not symbols:
            legacy_keys = await redis_client.keys(f"quantgambit:{bot_id}:warmup:*")
            for key in legacy_keys:
                payload = await redis_client.get(key)
                if not payload:
                    continue
                try:
                    item = json.loads(payload)
                except Exception:
                    continue
                symbol, entry = _ingest_warmup_item(item)
                if symbol:
                    symbols[symbol] = entry

        amt_timeframe_sec = int(os.getenv("AMT_CANDLE_TIMEFRAME_SEC", "300"))
        amt_min_candles = int(os.getenv("AMT_MIN_CANDLES", "10"))
        decision_warmup_min_samples = int(os.getenv("DECISION_WARMUP_MIN_SAMPLES", "5"))
        candle_counts_key = f"quantgambit:{resolved_tenant_id}:{bot_id}:candle_counts"
        candle_counts_by_symbol: dict[str, int] = {}
        try:
            raw_candle_counts = await redis_client.hgetall(candle_counts_key)
        except Exception:
            raw_candle_counts = {}
        for raw_key, raw_value in (raw_candle_counts or {}).items():
            try:
                key_str = raw_key.decode("utf-8") if isinstance(raw_key, bytes) else str(raw_key)
                value_str = raw_value.decode("utf-8") if isinstance(raw_value, bytes) else str(raw_value)
                symbol, timeframe = key_str.rsplit(":", 1)
                if int(timeframe) != amt_timeframe_sec:
                    continue
                candle_counts_by_symbol[symbol] = int(value_str)
            except Exception:
                continue

        merged_symbol_names = set(symbols.keys()) | set(candle_counts_by_symbol.keys())
        merged_symbols: dict[str, Any] = {}
        progress_values = []
        for key in merged_symbol_names:
            value = symbols.get(key) or {
                "amt": {
                    "status": "warming",
                    "progress": 0.0,
                    "sampleCount": 0.0,
                    "minSamples": float(decision_warmup_min_samples),
                    "candleCount": 0,
                    "minCandles": amt_min_candles,
                    "qualityScore": None,
                    "flags": [],
                },
                "reasons": ["warmup"],
            }
            sample_count = value["amt"].get("sampleCount") or 0
            min_samples = value["amt"].get("minSamples") or float(decision_warmup_min_samples)
            candle_count = candle_counts_by_symbol.get(key, value["amt"].get("candleCount") or 0)
            min_candles = value["amt"].get("minCandles") or amt_min_candles
            sample_pct = min(100.0, (float(sample_count) / max(float(min_samples), 1.0)) * 100.0)
            candle_pct = (
                min(100.0, (float(candle_count) / max(float(min_candles), 1.0)) * 100.0)
                if min_candles
                else 100.0
            )
            progress_pct = min(100.0, (sample_pct + candle_pct) / 2.0)
            progress_values.append(progress_pct)
            merged_symbols[key] = {
                **value,
                "amt": {
                    **(value.get("amt") or {}),
                    "progress": progress_pct,
                    "sampleCount": sample_count,
                    "minSamples": min_samples,
                    "candleCount": candle_count,
                    "minCandles": min_candles,
                },
            }

        symbols = merged_symbols
        symbol_count = len(symbols)
        overall_progress = float(sum(progress_values) / max(len(progress_values), 1)) if progress_values else 0.0
        # Some runtimes, including the AI spot/swing path, may not emit explicit
        # warmup snapshots. In that case a healthy heartbeat is the only reliable
        # readiness signal and the UI should not wait forever on symbol warmup keys
        # that will never exist.
        inferred_ready_without_keys = False
        health_key = f"quantgambit:{resolved_tenant_id}:{bot_id}:health:latest"
        health_payload = await reader.read(health_key) or {}
        heartbeat_ts = health_payload.get("timestamp_epoch") or health_payload.get("timestamp")
        metrics_age_sec = None
        heartbeat_alive = False
        heartbeat_epoch = _coerce_epoch_timestamp(heartbeat_ts)
        if heartbeat_epoch:
            metrics_age_sec = max(0.0, time.time() - heartbeat_epoch)
            heartbeat_alive = metrics_age_sec <= 15.0
        if symbol_count == 0 and heartbeat_alive:
            inferred_ready_without_keys = True
            overall_progress = 100.0
        # Consider warmup "ready" when we have enough candles/samples (progress >= 100%).
        # If there are no warmup keys but the runtime heartbeat is alive, treat warmup as
        # complete so the UI can advance for provider paths that do not use AMT warmup.
        overall_ready = (symbol_count > 0 and overall_progress >= 100.0) or inferred_ready_without_keys

        warmup_symbols: dict[str, Any] = {}
        for key, value in symbols.items():
            sample_count = value["amt"]["sampleCount"] or 0
            min_samples = value["amt"]["minSamples"] or 1
            candle_count = value["amt"]["candleCount"] or 0
            min_candles = value["amt"]["minCandles"] or 1
            # Cap at minimum for display (don't show 500/20, show 20/20)
            capped_samples = min(sample_count, min_samples)
            capped_candles = min(candle_count, min_candles)
            samples_ready = sample_count >= min_samples
            candles_ready = candle_count >= min_candles
            warmup_symbols[key] = {
                "status": "ready" if (samples_ready and candles_ready) else "warming",
                "progress": value["amt"]["progress"],
                "sampleCount": capped_samples,
                "minSamples": min_samples,
                "candleCount": capped_candles,
                "minCandles": min_candles,
                "samplesReady": samples_ready,
                "candlesReady": candles_ready,
                "reasons": value.get("reasons") or [],
            }

        total_samples = sum(entry["sampleCount"] or 0 for entry in warmup_symbols.values())
        total_min_samples = sum(entry["minSamples"] or 0 for entry in warmup_symbols.values())
        total_candles = sum(entry["candleCount"] or 0 for entry in warmup_symbols.values())
        total_min_candles = sum(entry["minCandles"] or 0 for entry in warmup_symbols.values())

        response_payload = {
            "symbols": warmup_symbols,
            "overall": {
                "progress": overall_progress,
                "ready": overall_ready,
                "symbolCount": symbol_count,
                "sampleCount": total_samples,
                "minSamples": total_min_samples,
                "candleCount": total_candles,
                "minCandles": total_min_candles,
                "inferredReadyWithoutKeys": inferred_ready_without_keys,
            },
            "botStatus": {
                "heartbeatAlive": heartbeat_alive,
                "metricsAgeSeconds": metrics_age_sec,
                "servicesHealthy": heartbeat_alive,
            },
            "updatedAt": int(time.time() * 1000),
        }
        log_info(
            "dashboard_warmup_response",
            tenant_id=resolved_tenant_id,
            bot_id=bot_id,
            symbol_count=symbol_count,
            overall_progress=overall_progress,
            overall_ready=overall_ready,
            total_samples=total_samples,
            total_min_samples=total_min_samples,
            total_candles=total_candles,
            total_min_candles=total_min_candles,
            inferred_ready_without_keys=inferred_ready_without_keys,
        )
        return response_payload
        
        # Add symbol_characteristics to warmup response (Requirement 6.3)
        # Fetch from Redis hash keys: quantgambit:symbol_chars:{symbol}
        symbol_characteristics: dict[str, Any] = {}
        try:
            char_keys = await redis_client.keys("quantgambit:symbol_chars:*")
            for key in char_keys:
                try:
                    # Extract symbol from key
                    key_str = key.decode("utf-8") if isinstance(key, bytes) else key
                    symbol = key_str.split(":")[-1]
                    
                    # Get hash data
                    char_data = await redis_client.hgetall(key)
                    if char_data:
                        # Convert bytes to strings
                        parsed = {}
                        for k, v in char_data.items():
                            k_str = k.decode("utf-8") if isinstance(k, bytes) else k
                            v_str = v.decode("utf-8") if isinstance(v, bytes) else v
                            # Try to convert numeric values
                            try:
                                if "." in v_str:
                                    parsed[k_str] = float(v_str)
                                elif v_str.isdigit() or (v_str.startswith("-") and v_str[1:].isdigit()):
                                    parsed[k_str] = int(v_str)
                                else:
                                    parsed[k_str] = v_str
                            except (ValueError, AttributeError):
                                parsed[k_str] = v_str
                        
                        # Include key fields for dashboard display
                        symbol_characteristics[symbol] = {
                            "typical_spread_bps": parsed.get("typical_spread_bps"),
                            "typical_depth_usd": parsed.get("typical_depth_usd"),
                            "typical_daily_range_pct": parsed.get("typical_daily_range_pct"),
                            "typical_atr": parsed.get("typical_atr"),
                            "typical_volatility_regime": parsed.get("typical_volatility_regime"),
                            "sample_count": parsed.get("sample_count"),
                            "last_updated_ns": parsed.get("last_updated_ns"),
                            "is_warmed_up": (parsed.get("sample_count") or 0) >= 100,
                        }
                except Exception:
                    continue
        except Exception:
            pass  # Symbol characteristics are optional
        
        # Return the full response with symbol_characteristics
        return {
            "symbols": warmup_symbols,
            "overall": {
                "progress": overall_progress,
                "ready": overall_ready,
                "symbolCount": symbol_count,
                "sampleCount": total_samples,
                "minSamples": total_min_samples,
                "candleCount": total_candles,
                "minCandles": total_min_candles,
            },
            "botStatus": {
                "heartbeatAlive": heartbeat_alive,
                "metricsAgeSeconds": metrics_age_sec,
                "servicesHealthy": heartbeat_alive,
            },
            "symbolCharacteristics": symbol_characteristics,
            "updatedAt": int(time.time() * 1000),
        }

    def _enrich_position(pos: dict[str, Any]) -> dict[str, Any]:
        """Compute derived fields for a position: mark_price, unrealized_pnl, market_value."""
        entry_price = _safe_float(pos.get("entry_price"))
        reference_price = _safe_float(
            pos.get("reference_price")
            or pos.get("current_price")
            or pos.get("mark_price")
            or pos.get("markPrice")
        )
        raw_size = _safe_float(pos.get("size"))
        size = abs(raw_size)
        raw_side = str(pos.get("side", "")).strip().lower()
        if raw_side in {"long", "buy"}:
            side = "long"
        elif raw_side in {"short", "sell"}:
            side = "short"
        elif raw_size < 0:
            side = "short"
        else:
            side = "long"
        
        # Mark price is the current market price (reference_price)
        mark_price = reference_price
        
        # Compute unrealized PnL
        unrealized_pnl = None
        unrealized_pnl_pct = None
        if entry_price and mark_price and size:
            if side in ("long", "buy"):
                unrealized_pnl = (mark_price - entry_price) * size
            elif side in ("short", "sell"):
                unrealized_pnl = (entry_price - mark_price) * size
            # Compute percentage
            if unrealized_pnl is not None and entry_price > 0:
                cost_basis = entry_price * size
                if cost_basis > 0:
                    unrealized_pnl_pct = (unrealized_pnl / cost_basis) * 100
        
        # Market value is current value of position
        market_value = None
        if mark_price and size:
            market_value = mark_price * size

        # Estimate net PnL after round-trip fees (entry+exit taker by default).
        # This helps operators compare optimistic mark-to-market vs likely realized.
        estimated_round_trip_fee_usd = None
        estimated_net_unrealized_after_fees = None
        round_trip_fee_bps = _safe_float(os.getenv("POSITIONS_ESTIMATED_ROUND_TRIP_FEE_BPS")) or 12.0
        if mark_price and size:
            notional = abs(mark_price * size)
            estimated_round_trip_fee_usd = notional * (round_trip_fee_bps / 10000.0)
            if unrealized_pnl is not None:
                estimated_net_unrealized_after_fees = unrealized_pnl - estimated_round_trip_fee_usd
        
        # Return enriched position with both snake_case and camelCase for frontend compatibility
        return {
            **pos,
            "mark_price": mark_price,
            "markPrice": mark_price,
            "unrealized_pnl": unrealized_pnl,
            "unrealizedPnl": unrealized_pnl,
            "pnl": unrealized_pnl,  # Common shorthand
            "unrealized_pnl_pct": unrealized_pnl_pct,
            "unrealizedPnlPct": unrealized_pnl_pct,
            "market_value": market_value,
            "marketValue": market_value,
            "estimated_round_trip_fee_usd": estimated_round_trip_fee_usd,
            "estimatedRoundTripFeeUsd": estimated_round_trip_fee_usd,
            "estimated_net_unrealized_after_fees": estimated_net_unrealized_after_fees,
            "estimatedNetUnrealizedAfterFees": estimated_net_unrealized_after_fees,
            "entry_price": entry_price,
            "entryPrice": entry_price,
        }

    @app.get("/api/dashboard/positions", response_model=dict, dependencies=[Depends(auth_dep)])
    async def dashboard_positions(
        tenant_id: str | None = None,
        bot_id: str | None = Query(default=None, alias="botId"),
        exchange_account_id: str | None = Query(default=None, alias="exchangeAccountId"),
        redis_client=Depends(_redis_client),
        timescale=Depends(_timescale_reader),
    ):
        """Get current open positions.
        
        Position State Hierarchy (source of truth):
        1. Exchange (authoritative) - runtime syncs from here on startup
        2. Redis cache (fast) - updated by runtime on each position change
        3. TimescaleDB (history) - NOT used for current positions
        
        We only read from Redis here. If Redis is empty, there are no positions.
        We do NOT fall back to TimescaleDB as that may contain stale/closed positions.
        """
        # Resolve scope; tolerate missing bot_id by returning empty positions instead of 500
        try:
            tenant_id, bot_id = _resolve_scope(tenant_id, bot_id)
        except Exception:
            return {"positions": [], "_warning": "missing_scope"}
        tenant_id = await _resolve_runtime_tenant_scope(
            redis_client,
            tenant_id,
            bot_id,
            suffixes=["positions:latest", "control:state", "health:latest"],
        )
        reader = RedisSnapshotReader(redis_client)
        positions: list[dict[str, Any]] = []
        try:
            key = f"quantgambit:{tenant_id}:{bot_id}:positions:latest"
            payload = await reader.read(key) or {}
            positions = payload.get("positions") if isinstance(payload, dict) else []
            # NOTE: No TimescaleDB fallback - Redis is the cache, not DB
            # If positions is empty, that means there are no open positions
        except Exception:
            return {"positions": [], "_warning": "positions_unavailable"}
        # Enrich positions with computed fields
        enriched = [_enrich_position(p) for p in (positions or [])]
        return {"positions": enriched}

    @app.get("/api/dashboard/pending-orders", response_model=dict, dependencies=[Depends(auth_dep)])
    async def dashboard_pending_orders(
        tenant_id: str | None = None,
        bot_id: str | None = None,
        limit: int = 200,
        redis_client=Depends(_redis_client),
    ):
        try:
            tenant_id, bot_id = _resolve_scope(tenant_id, bot_id)
        except Exception:
            return {"orders": []}
        tenant_id = await _resolve_runtime_tenant_scope(
            redis_client,
            tenant_id,
            bot_id,
            suffixes=["orders:history", "control:state", "health:latest"],
        )
        reader = RedisSnapshotReader(redis_client)
        key = f"quantgambit:{tenant_id}:{bot_id}:orders:history"
        try:
            history = await reader.read_history(key, limit=limit)
        except Exception:
            history = []
        pending_statuses = {"new", "open", "pending", "partially_filled"}
        pending = [item for item in history if str(item.get("status", "")).lower() in pending_statuses]
        return {"orders": pending}

    @app.get("/api/dashboard/trading", response_model=TradingSnapshotResponse, dependencies=[Depends(auth_dep)])
    async def dashboard_trading_snapshot(
        tenant_id: str | None = None,
        bot_id: str | None = Query(default=None, alias="botId"),
        exchangeAccountId: str | None = None,
        exchange_account_id: str | None = None,
        redis_client=Depends(_redis_client),
        timescale=Depends(_timescale_reader),
    ):
        try:
            account_id = exchangeAccountId or exchange_account_id
            if not bot_id and account_id:
                resolved_bot = await _resolve_bot_from_exchange_account(timescale.pool, account_id)
                if resolved_bot:
                    bot_id = resolved_bot
            tenant_id, bot_id = _resolve_scope(tenant_id, bot_id)
        except Exception:
            return TradingSnapshotResponse(
                positions=[],
                pendingOrders=[],
                metrics={},
                execution={},
                risk={},
                exchangeStatus={},
                performance={},
                recentTrades=[],
                updatedAt=int(time.time() * 1000),
            )
        tenant_id = await _resolve_runtime_tenant_scope(
            redis_client,
            tenant_id,
            bot_id,
            suffixes=["positions:latest", "orders:history", "control:state", "health:latest"],
        )
        reader = RedisSnapshotReader(redis_client)
        positions = await reader.read(f"quantgambit:{tenant_id}:{bot_id}:positions:latest") or {}
        if not (isinstance(positions, dict) and positions.get("positions")):
            fallback = await timescale.load_latest_positions(tenant_id, bot_id)
            if isinstance(fallback, dict):
                positions = fallback
        orders = await reader.read_history(f"quantgambit:{tenant_id}:{bot_id}:orders:history", limit=200)
        pending_statuses = {"new", "open", "pending", "partially_filled"}
        pending = [item for item in orders if str(item.get("status", "")).lower() in pending_statuses]
        risk = await reader.read(f"quantgambit:{tenant_id}:{bot_id}:risk:sizing") or {}
        account_id = exchangeAccountId or exchange_account_id
        unrealized_pnl = 0.0
        positions_list = positions.get("positions") if isinstance(positions, dict) else []
        for pos in positions_list or []:
            qty = _safe_float(pos.get("size") or pos.get("quantity"))
            entry_price = _safe_float(pos.get("entry_price"))
            mark_price = _safe_float(
                pos.get("reference_price")
                or pos.get("current_price")
                or pos.get("mark_price")
                or pos.get("entry_price")
            )
            side = str(pos.get("side") or "").lower()
            pos_pnl = _safe_float(pos.get("unrealized_pnl") or pos.get("pnl"))
            if pos_pnl == 0.0 and entry_price and mark_price and qty:
                if side in {"long", "buy"}:
                    pos_pnl = (mark_price - entry_price) * qty
                elif side in {"short", "sell"}:
                    pos_pnl = (entry_price - mark_price) * qty
            unrealized_pnl += pos_pnl

        recent_trade_events: list[dict[str, Any]] = []
        execution_summary: dict[str, Any] = {}
        daily_pnl = 0.0
        daily_fees = 0.0
        trade_count = 0
        try:
            rows = await timescale.pool.fetch(
                "SELECT ts, payload, symbol, exchange, bot_id FROM order_events "
                "WHERE tenant_id=$1 AND bot_id=$2 ORDER BY ts DESC LIMIT 500",
                tenant_id,
                bot_id,
            )
            events = [_merge_ts_payload(row) for row in rows]
            if not events:
                lifecycle_rows = await timescale.pool.fetch(
                    "SELECT created_at, exchange, symbol, side, size, status, event_type, order_id, "
                    "client_order_id, reason, fill_price, fee_usd, filled_size, remaining_size "
                    "FROM order_lifecycle_events "
                    "WHERE tenant_id=$1 AND bot_id=$2 ORDER BY created_at DESC LIMIT 500",
                    tenant_id,
                    bot_id,
                )
                fallback_events: list[dict[str, Any]] = []
                for row in lifecycle_rows:
                    created_at = row.get("created_at")
                    ts_epoch = created_at.timestamp() if hasattr(created_at, "timestamp") else None
                    fallback_events.append(
                        {
                            "timestamp": ts_epoch,
                            "ts": ts_epoch,
                            "exchange": row.get("exchange"),
                            "symbol": row.get("symbol"),
                            "side": row.get("side"),
                            "size": row.get("size"),
                            "status": row.get("status"),
                            "event_type": row.get("event_type"),
                            "order_id": row.get("order_id"),
                            "client_order_id": row.get("client_order_id"),
                            "reason": row.get("reason"),
                            "fill_price": row.get("fill_price"),
                            "fee_usd": row.get("fee_usd"),
                            "filled_size": row.get("filled_size"),
                            "remaining_size": row.get("remaining_size"),
                        }
                    )
                events = fallback_events
            execution_summary = _aggregate_execution_quality(events)
            aggregated_closes, _ = _dedupe_order_events(events, close_only=True)
            for item in aggregated_closes[:20]:
                trade = _normalize_trade_event(item)
                daily_pnl += _safe_float(trade.get("pnl"))
                daily_fees += _safe_float(trade.get("fees"))
                trade_count += 1
                recent_trade_events.append(trade)
        except Exception:
            recent_trade_events = []
            execution_summary = {}

        metrics = {
            "positionsCount": len(positions_list if isinstance(positions_list, list) else []),
            "pendingOrdersCount": len(pending),
            "account_balance": _safe_float(risk.get("equity") or risk.get("account_balance")) or None,
            "daily_pnl": daily_pnl,
            "unrealized_pnl": unrealized_pnl,
            "total_pnl": daily_pnl + unrealized_pnl,
            "daily_fees": daily_fees,
            "completedTrades": trade_count,
            "exchangeAccountId": account_id,
        }
        execution = {
            "provider": os.getenv("EXECUTION_PROVIDER", "unknown"),
            "policy": os.getenv("EXECUTION_POLICY", "unknown"),
            "fill": {
                "total_orders": execution_summary.get("total_orders", 0),
                "total_fills": execution_summary.get("total_fills", 0),
                "total_rejects": execution_summary.get("total_rejects", 0),
                "fill_rate_pct": execution_summary.get("fill_rate_pct", 0.0),
                "avg_slippage_bps": execution_summary.get("avg_slippage_bps", 0.0),
            },
            "quality": {
                "overall": {
                    "avg_execution_time_ms": execution_summary.get("avg_execution_time_ms", 0.0),
                    "avg_slippage_bps": execution_summary.get("avg_slippage_bps", 0.0),
                    "fill_rate_pct": execution_summary.get("fill_rate_pct", 0.0),
                    "rejection_rate": execution_summary.get("rejection_rate", 0.0),
                },
            },
        }
        exchange_status = {
            "exchange": os.getenv("ACTIVE_EXCHANGE", "unknown"),
            "mode": str(os.getenv("TRADING_MODE", "unknown")).lower(),
            "demo": str(os.getenv("BYBIT_DEMO", "false")).strip().lower() in {"1", "true", "yes"},
        }
        return TradingSnapshotResponse(
            positions=positions_list if isinstance(positions_list, list) else [],
            pendingOrders=pending,
            metrics=metrics,
            execution=execution,
            risk=risk,
        exchangeStatus=exchange_status,
        performance={},
        recentTrades=recent_trade_events,
        updatedAt=int(time.time() * 1000),
    )

    @app.get("/api/dashboard/metrics", response_model=dict, dependencies=[Depends(auth_dep)])
    async def dashboard_metrics(
        tenant_id: str | None = None,
        bot_id: str | None = Query(default=None, alias="botId"),
        exchangeAccountId: str | None = None,
        exchange_account_id: str | None = None,
        redis_client=Depends(_redis_client),
        timescale=Depends(_timescale_reader),
        pool=Depends(_dashboard_pool),
    ):
        account_id = exchangeAccountId or exchange_account_id
        if not bot_id and account_id:
            resolved_bot = await _resolve_bot_from_exchange_account(pool or timescale.pool, account_id)
            if resolved_bot:
                bot_id = resolved_bot
        tenant_id, bot_id = _resolve_scope(tenant_id, bot_id)
        tenant_id = await _resolve_runtime_tenant_scope(
            redis_client,
            tenant_id,
            bot_id,
            suffixes=["positions:latest", "orders:history", "control:state", "health:latest"],
        )
        account_id = exchangeAccountId or exchange_account_id
        metrics_cache_ttl_sec = max(1.0, float(_safe_float(os.getenv("DASHBOARD_METRICS_CACHE_SEC"), 10.0)))
        metrics_cache_key = f"{tenant_id}:{bot_id}:{account_id or ''}"
        cached_metrics = _DASHBOARD_METRICS_CACHE.get(metrics_cache_key)
        if cached_metrics:
            cached_payload, cached_ts = cached_metrics
            if (time.time() - cached_ts) <= metrics_cache_ttl_sec:
                return cached_payload
        
        # Check if this is paper trading by looking at the exchange account environment
        is_paper = False
        available_balance = None
        balance_currency = None
        if account_id and pool:
            try:
                row = await pool.fetchrow(
                    "SELECT environment, available_balance, balance_currency FROM exchange_accounts WHERE id = $1",
                    account_id
                )
                if row:
                    is_paper = row.get("environment") == "paper"
                    available_balance = _safe_float(row.get("available_balance"))
                    balance_currency = row.get("balance_currency") or "USDT"
            except Exception as exc:
                log_warning("dashboard_metrics_account_lookup_failed", error=str(exc), account_id=account_id)
        
        reader = RedisSnapshotReader(redis_client)
        positions_payload = await reader.read(f"quantgambit:{tenant_id}:{bot_id}:positions:latest") or {}
        if isinstance(positions_payload, dict):
            positions = positions_payload.get("positions") or []
        else:
            positions = []
        risk_snapshot = await reader.read(f"quantgambit:{tenant_id}:{bot_id}:risk:sizing") or {}
        risk_equity = _safe_float(
            risk_snapshot.get("equity")
            or risk_snapshot.get("account_balance")
            or risk_snapshot.get("current_equity")
        )
        risk_peak = _safe_float(
            risk_snapshot.get("peak_balance")
            or risk_snapshot.get("initial_equity")
            or risk_snapshot.get("peak_equity")
        )
        net_exposure = 0.0
        gross_exposure = 0.0
        unrealized_pnl = 0.0
        for pos in positions:
            qty = _safe_float(pos.get("size") or pos.get("quantity"))
            entry_price = _safe_float(pos.get("entry_price"))
            mark_price = _safe_float(
                pos.get("reference_price")
                or pos.get("current_price")
                or pos.get("mark_price")
                or pos.get("entry_price")
            )
            notional = abs(qty * mark_price) if mark_price else 0.0
            gross_exposure += notional
            side = str(pos.get("side") or "").lower()
            signed = notional if side in {"long", "buy"} else -notional
            net_exposure += signed
            # Calculate unrealized PnL if not provided
            pos_pnl = _safe_float(pos.get("unrealized_pnl") or pos.get("pnl"))
            if pos_pnl == 0.0 and entry_price and mark_price and qty:
                if side in {"long", "buy"}:
                    pos_pnl = (mark_price - entry_price) * qty
                elif side in {"short", "sell"}:
                    pos_pnl = (entry_price - mark_price) * qty
            unrealized_pnl += pos_pnl
        metrics_window_hours = 24
        window_start = datetime.now(timezone.utc) - timedelta(hours=metrics_window_hours)
        
        # Get PnL from order_events (normal trading flow)
        rows = await timescale.pool.fetch(
            "SELECT ts, payload, symbol, exchange, bot_id FROM order_events "
            "WHERE tenant_id=$1 AND bot_id=$2 AND ts >= $3 ORDER BY ts DESC LIMIT 500",
            tenant_id,
            bot_id,
            window_start,
        )
        events = [_merge_ts_payload(row) for row in rows]
        
        # Realized PnL source: deduped close rows from order_events.
        # This keeps overview aligned with Orders & Fills / trade history.
        daily_pnl = 0.0
        daily_fees = 0.0
        trade_count = 0

        aggregated_closes, _ = _dedupe_order_events(events, close_only=True)
        for e in aggregated_closes:
            trade = _normalize_trade_event(e)
            daily_pnl += _safe_float(trade.get("pnl"))
            daily_fees += _safe_float(trade.get("fees"))
            trade_count += 1
        execution_summary = _aggregate_execution_quality(events)
        total_orders = execution_summary.get("total_orders") or 0
        rejection_rate = execution_summary.get("total_rejects", 0) / (total_orders or 1)
        reject_rate = 0.0
        if execution_summary.get("total_orders"):
            reject_rate = execution_summary.get("total_rejects", 0) / execution_summary.get("total_orders", 1)
        # Get exchange balance from risk snapshot (refreshed periodically from exchange)
        # Note: Exchange equity already includes unrealized PnL
        exchange_balance = _safe_float(risk_snapshot.get("equity") or risk_snapshot.get("account_balance"))
        peak_equity = _safe_float(risk_snapshot.get("peak_balance") or risk_snapshot.get("initial_equity"))
        
        balance_cache_ttl_sec = max(1.0, float(_safe_float(os.getenv("METRICS_EXCHANGE_BALANCE_CACHE_SEC"), 15.0)))
        stale_cache_ttl_sec = max(
            balance_cache_ttl_sec,
            float(_safe_float(os.getenv("METRICS_EXCHANGE_BALANCE_STALE_CACHE_SEC"), 300.0)),
        )
        balance_refresh_cooldown_sec = max(
            1.0,
            float(_safe_float(os.getenv("METRICS_EXCHANGE_BALANCE_MIN_REFRESH_SEC"), 30.0)),
        )
        has_cached_exchange_balance = False
        if account_id:
            cached = _EXCHANGE_BALANCE_CACHE.get(str(account_id))
            if cached:
                cached_balance, cached_ts = cached
                if (time.time() - cached_ts) <= balance_cache_ttl_sec and cached_balance > 0:
                    exchange_balance = cached_balance
                    has_cached_exchange_balance = True
                elif (time.time() - cached_ts) <= stale_cache_ttl_sec and cached_balance > 0:
                    exchange_balance = cached_balance
                    has_cached_exchange_balance = True

        # If no balance from runtime/cache, fetch live from exchange (not database - it may be stale).
        # Never let exchange I/O stall this endpoint.
        if (not exchange_balance or exchange_balance <= 0) and not has_cached_exchange_balance:
            if account_id and pool:
                async def _refresh_exchange_balance() -> float | None:
                    nonlocal exchange_balance
                    account_key = str(account_id)
                    lock = _EXCHANGE_BALANCE_FETCH_LOCKS.setdefault(account_key, asyncio.Lock())
                    async with lock:
                        now = time.time()
                        cached = _EXCHANGE_BALANCE_CACHE.get(account_key)
                        if cached:
                            cached_balance, cached_ts = cached
                            if (now - cached_ts) <= balance_cache_ttl_sec and cached_balance > 0:
                                return cached_balance

                        should_fetch = not exchange_balance or exchange_balance <= 0
                        last_attempt = _EXCHANGE_BALANCE_LAST_ATTEMPT.get(account_key, 0.0)
                        if should_fetch and (now - last_attempt) < balance_refresh_cooldown_sec:
                            should_fetch = False
                        if not should_fetch:
                            return exchange_balance if exchange_balance > 0 else None

                        _EXCHANGE_BALANCE_LAST_ATTEMPT[account_key] = now
                        acct_row = await pool.fetchrow(
                            "SELECT venue, is_demo, secret_id FROM exchange_accounts WHERE id = $1",
                            account_id,
                        )
                        if not (acct_row and acct_row.get("secret_id")):
                            return None

                        from quantgambit.storage.secrets import SecretsProvider
                        secrets = SecretsProvider()
                        creds = secrets.get_credentials(acct_row["secret_id"])
                        if not creds:
                            return None

                        exchange_id = (acct_row.get("venue") or "bybit").lower()
                        is_demo = acct_row.get("is_demo", False)
                        if not (creds.api_key and creds.secret_key):
                            return None
                        from quantgambit.execution.ccxt_clients import CcxtCredentials, build_ccxt_client

                        market_type = "spot" if exchange_id == "bybit" else "perp"
                        client = build_ccxt_client(
                            exchange_id,
                            CcxtCredentials(
                                api_key=creds.api_key,
                                secret_key=creds.secret_key,
                                passphrase=creds.passphrase,
                                testnet=bool(is_demo),
                                demo=bool(is_demo),
                            ),
                            market_type=market_type,
                        )

                        try:
                            balance_value = await client.fetch_balance("USDT")
                            if balance_value and balance_value > 0:
                                _EXCHANGE_BALANCE_CACHE[account_key] = (float(balance_value), time.time())
                                return float(balance_value)
                        finally:
                            try:
                                await client.client.close()
                            except Exception:
                                pass
                    return None

                try:
                    asyncio.create_task(_refresh_exchange_balance())
                except Exception as e:
                    import traceback
                    log_warning("metrics_fetch_balance_schedule_failed", error=str(e), traceback=traceback.format_exc())
        
        # Calculate current equity - prefer live exchange balance, then risk snapshot fallback
        if exchange_balance and exchange_balance > 0:
            current_equity = exchange_balance
        elif risk_equity and risk_equity > 0:
            current_equity = risk_equity
            exchange_balance = risk_equity
        else:
            current_equity = None
            exchange_balance = None
        if (not peak_equity or peak_equity <= 0) and risk_peak and risk_peak > 0:
            peak_equity = risk_peak
        if current_equity and (not peak_equity or peak_equity <= 0):
            peak_equity = current_equity
        
        # Calculate drawdown
        drawdown_pct = 0.0
        if current_equity and peak_equity and peak_equity > 0:
            drawdown_pct = max(0.0, (peak_equity - current_equity) / peak_equity * 100)
        
        # Total P&L = realized (from closed trades) + unrealized (from open positions)
        total_pnl = daily_pnl + unrealized_pnl
        
        metrics = {
            "daily_pnl": daily_pnl,
            "dailyPnl": daily_pnl,
            "daily_fees": daily_fees,
            "unrealized_pnl": unrealized_pnl,
            "total_pnl": total_pnl,  # Realized + Unrealized for 24h display
            "totalPnl": total_pnl,
            "net_exposure": net_exposure,
            "gross_exposure": gross_exposure,
            "leverage": risk_snapshot.get("leverage") or 1,
            "drawdown": round(drawdown_pct, 2),
            "max_drawdown": round(drawdown_pct, 2),
            "maxDrawdown": round(drawdown_pct, 2),
            "rolling_drawdown": round(drawdown_pct, 2),
            "current_equity": round(current_equity, 2) if current_equity else None,
            "peak_equity": round(peak_equity, 2) if peak_equity else None,
            "exchange_balance": round(exchange_balance, 2) if exchange_balance else None,
            "account_balance": round(exchange_balance, 2) if exchange_balance else None,
            "available_balance": round(available_balance, 2) if available_balance else None,
            "balance_currency": balance_currency,
            "avg_slippage": execution_summary.get("avg_slippage_bps", 0),
            "avg_latency": execution_summary.get("avg_execution_time_ms", 0),
            "reject_rate": reject_rate,
            "trades_count": trade_count,
            "fillRate": execution_summary.get("fill_rate_pct", 0),
            "makerRatio": None,  # Not available from exchange - show N/A in UI
            "_isPaper": is_paper,  # True only if exchange account environment is 'paper'
            "_source": "telemetry",
            "window_hours": metrics_window_hours,
            "window_start_utc": window_start.isoformat(),
        }
        payload = {"data": metrics}
        _DASHBOARD_METRICS_CACHE[metrics_cache_key] = (payload, time.time())
        return payload

    @app.get("/api/dashboard/execution", response_model=dict, dependencies=[Depends(auth_dep)])
    async def dashboard_execution_stats(
        tenant_id: str | None = None,
        bot_id: str | None = Query(default=None, alias="botId"),
        exchange_account_id: str | None = Query(default=None, alias="exchangeAccountId"),
        exchangeAccountId: str | None = None,
        redis_client=Depends(_redis_client),
        timescale=Depends(_timescale_reader),
    ):
        try:
            account_id = exchangeAccountId or exchange_account_id
            if not bot_id and account_id:
                resolved_bot = await _resolve_bot_from_exchange_account(timescale.pool, account_id)
                if resolved_bot:
                    bot_id = resolved_bot
            tenant_id, bot_id = _resolve_scope(tenant_id, bot_id)
        except Exception:
            return {"data": {}}
        tenant_id = await _resolve_runtime_tenant_scope(
            redis_client,
            tenant_id,
            bot_id,
            suffixes=["orders:history", "control:state", "health:latest"],
        )
        reader = RedisSnapshotReader(redis_client)
        
        # Get accurate stats from order_states table
        order_stats = {"total_orders": 0, "total_fills": 0, "total_rejects": 0}
        latency_percentiles = {
            "signal_to_order_p50": None, "signal_to_order_p95": None, "signal_to_order_p99": None,
            "order_to_ack_p50": None, "order_to_ack_p95": None, "order_to_ack_p99": None,
            "ack_to_fill_p50": None, "ack_to_fill_p95": None, "ack_to_fill_p99": None,
        }
        avg_slippage_db = 0.0
        avg_roundtrip_ms = 0.0
        try:
            stats_rows = await timescale.pool.fetch(
                """SELECT 
                    COUNT(*) as total_orders,
                    COUNT(*) FILTER (WHERE status = 'filled') as fills,
                    COUNT(*) FILTER (WHERE status IN ('rejected', 'failed')) as rejects,
                    AVG(slippage_bps) FILTER (WHERE slippage_bps IS NOT NULL) as avg_slippage,
                    AVG(EXTRACT(EPOCH FROM (filled_at - submitted_at))*1000) 
                        FILTER (WHERE filled_at IS NOT NULL AND submitted_at IS NOT NULL) as avg_roundtrip_ms,
                    PERCENTILE_CONT(0.5) WITHIN GROUP (
                        ORDER BY GREATEST(0, EXTRACT(EPOCH FROM ((COALESCE(os.submitted_at, os.open_at, os.accepted_at, os.filled_at) - oi.created_at)) * 1000))
                    )
                        FILTER (WHERE oi.created_at IS NOT NULL AND COALESCE(os.submitted_at, os.open_at, os.accepted_at, os.filled_at) IS NOT NULL) as signal_to_order_p50,
                    PERCENTILE_CONT(0.95) WITHIN GROUP (
                        ORDER BY GREATEST(0, EXTRACT(EPOCH FROM ((COALESCE(os.submitted_at, os.open_at, os.accepted_at, os.filled_at) - oi.created_at)) * 1000))
                    )
                        FILTER (WHERE oi.created_at IS NOT NULL AND COALESCE(os.submitted_at, os.open_at, os.accepted_at, os.filled_at) IS NOT NULL) as signal_to_order_p95,
                    PERCENTILE_CONT(0.99) WITHIN GROUP (
                        ORDER BY GREATEST(0, EXTRACT(EPOCH FROM ((COALESCE(os.submitted_at, os.open_at, os.accepted_at, os.filled_at) - oi.created_at)) * 1000))
                    )
                        FILTER (WHERE oi.created_at IS NOT NULL AND COALESCE(os.submitted_at, os.open_at, os.accepted_at, os.filled_at) IS NOT NULL) as signal_to_order_p99,
                    PERCENTILE_CONT(0.5) WITHIN GROUP (
                        ORDER BY GREATEST(0, EXTRACT(EPOCH FROM ((COALESCE(os.accepted_at, os.open_at, os.filled_at, os.submitted_at) - os.submitted_at)) * 1000))
                    )
                        FILTER (WHERE os.submitted_at IS NOT NULL AND COALESCE(os.accepted_at, os.open_at, os.filled_at) IS NOT NULL) as order_to_ack_p50,
                    PERCENTILE_CONT(0.95) WITHIN GROUP (
                        ORDER BY GREATEST(0, EXTRACT(EPOCH FROM ((COALESCE(os.accepted_at, os.open_at, os.filled_at, os.submitted_at) - os.submitted_at)) * 1000))
                    )
                        FILTER (WHERE os.submitted_at IS NOT NULL AND COALESCE(os.accepted_at, os.open_at, os.filled_at) IS NOT NULL) as order_to_ack_p95,
                    PERCENTILE_CONT(0.99) WITHIN GROUP (
                        ORDER BY GREATEST(0, EXTRACT(EPOCH FROM ((COALESCE(os.accepted_at, os.open_at, os.filled_at, os.submitted_at) - os.submitted_at)) * 1000))
                    )
                        FILTER (WHERE os.submitted_at IS NOT NULL AND COALESCE(os.accepted_at, os.open_at, os.filled_at) IS NOT NULL) as order_to_ack_p99,
                    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY EXTRACT(EPOCH FROM (os.filled_at - COALESCE(os.accepted_at, os.open_at, os.submitted_at)))*1000)
                        FILTER (WHERE os.filled_at IS NOT NULL AND COALESCE(os.accepted_at, os.open_at, os.submitted_at) IS NOT NULL) as ack_to_fill_p50,
                    PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY EXTRACT(EPOCH FROM (os.filled_at - COALESCE(os.accepted_at, os.open_at, os.submitted_at)))*1000)
                        FILTER (WHERE os.filled_at IS NOT NULL AND COALESCE(os.accepted_at, os.open_at, os.submitted_at) IS NOT NULL) as ack_to_fill_p95,
                    PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY EXTRACT(EPOCH FROM (os.filled_at - COALESCE(os.accepted_at, os.open_at, os.submitted_at)))*1000)
                        FILTER (WHERE os.filled_at IS NOT NULL AND COALESCE(os.accepted_at, os.open_at, os.submitted_at) IS NOT NULL) as ack_to_fill_p99
                FROM order_states os
                LEFT JOIN order_intents oi
                  ON oi.tenant_id = os.tenant_id
                 AND oi.bot_id = os.bot_id
                 AND oi.client_order_id = os.client_order_id
                WHERE os.tenant_id=$1 AND os.bot_id=$2""",
                tenant_id, bot_id
            )
            if stats_rows:
                order_stats["total_orders"] = stats_rows[0].get("total_orders", 0)
                order_stats["total_fills"] = stats_rows[0].get("fills", 0)
                order_stats["total_rejects"] = stats_rows[0].get("rejects", 0)
                if stats_rows[0].get("avg_slippage") is not None:
                    avg_slippage_db = round(float(stats_rows[0]["avg_slippage"]), 2)
                if stats_rows[0].get("avg_roundtrip_ms") is not None:
                    avg_roundtrip_ms = round(float(stats_rows[0]["avg_roundtrip_ms"]), 2)
                # Extract latency percentiles (may be None if no data)
                for key in latency_percentiles:
                    val = stats_rows[0].get(key)
                    if val is not None:
                        latency_percentiles[key] = round(float(val), 2)
        except Exception:
            pass
        
        try:
            rows = await timescale.pool.fetch(
                "SELECT ts, payload, symbol, exchange, bot_id FROM order_events "
                "WHERE tenant_id=$1 AND bot_id=$2 ORDER BY ts DESC LIMIT 500",
                tenant_id,
                bot_id,
            )
            events = [_merge_ts_payload(row) for row in rows]
            if not events:
                lifecycle_rows = await timescale.pool.fetch(
                    "SELECT created_at, exchange, symbol, side, size, status, event_type, order_id, "
                    "client_order_id, reason, fill_price, fee_usd, filled_size, remaining_size "
                    "FROM order_lifecycle_events "
                    "WHERE tenant_id=$1 AND bot_id=$2 ORDER BY created_at DESC LIMIT 500",
                    tenant_id,
                    bot_id,
                )
                fallback_events: list[dict[str, Any]] = []
                for row in lifecycle_rows:
                    created_at = row.get("created_at")
                    ts_epoch = created_at.timestamp() if hasattr(created_at, "timestamp") else None
                    fallback_events.append(
                        {
                            "timestamp": ts_epoch,
                            "ts": ts_epoch,
                            "exchange": row.get("exchange"),
                            "symbol": row.get("symbol"),
                            "side": row.get("side"),
                            "size": row.get("size"),
                            "status": row.get("status"),
                            "event_type": row.get("event_type"),
                            "order_id": row.get("order_id"),
                            "client_order_id": row.get("client_order_id"),
                            "reason": row.get("reason"),
                            "fill_price": row.get("fill_price"),
                            "fee_usd": row.get("fee_usd"),
                            "filled_size": row.get("filled_size"),
                            "remaining_size": row.get("remaining_size"),
                        }
                    )
                events = fallback_events
        except Exception:
            events = []
        execution_summary = _aggregate_execution_quality(events)
        
        # Override with accurate stats from order_states
        if order_stats["total_orders"] > 0:
            execution_summary["total_orders"] = order_stats["total_orders"]
            execution_summary["total_fills"] = order_stats["total_fills"]
            execution_summary["total_rejects"] = order_stats["total_rejects"]
            if execution_summary["total_orders"] > 0:
                execution_summary["fill_rate_pct"] = (execution_summary["total_fills"] / execution_summary["total_orders"]) * 100
        now = time.time()
        recent_5m = [
            e for e in events if _coerce_epoch_timestamp(e.get("timestamp") or e.get("ts")) and
            now - _coerce_epoch_timestamp(e.get("timestamp") or e.get("ts")) <= 300
        ]
        recent_1h = [
            e for e in events if _coerce_epoch_timestamp(e.get("timestamp") or e.get("ts")) and
            now - _coerce_epoch_timestamp(e.get("timestamp") or e.get("ts")) <= 3600
        ]
        reject_5m = len([e for e in recent_5m if str(e.get("status", "")).lower() in {"rejected", "error"}])
        reject_1h = len([e for e in recent_1h if str(e.get("status", "")).lower() in {"rejected", "error"}])
        total_5m = len(recent_5m) or 1
        total_1h = len(recent_1h) or 1
        reject_rate = execution_summary.get("total_rejects", 0) / (execution_summary.get("total_orders", 1) or 1)
        rejection_rate = execution_summary.get("rejection_rate", reject_rate)
        reason_counts: dict[str, int] = {}
        for item in events:
            if str(item.get("status", "")).lower() not in {"rejected", "error"}:
                continue
            reason = str(item.get("reason") or item.get("rejection_reason") or "unknown")
            reason_counts[reason] = reason_counts.get(reason, 0) + 1
        top_reason = max(reason_counts.items(), key=lambda kv: kv[1])[0] if reason_counts else ""
        top_reason_count = reason_counts.get(top_reason, 0) if top_reason else 0
        
        # Fetch hourly latency distribution for charts
        latency_history: list[dict] = []
        fill_rate_history: list[dict] = []
        try:
            # Latency percentiles by hour (last 24 hours)
            latency_rows = await timescale.pool.fetch(
                """SELECT 
                    date_trunc('hour', submitted_at) as bucket,
                    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY EXTRACT(EPOCH FROM (filled_at - submitted_at))*1000)
                        FILTER (WHERE filled_at IS NOT NULL AND submitted_at IS NOT NULL) as p50,
                    PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY EXTRACT(EPOCH FROM (filled_at - submitted_at))*1000)
                        FILTER (WHERE filled_at IS NOT NULL AND submitted_at IS NOT NULL) as p95,
                    PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY EXTRACT(EPOCH FROM (filled_at - submitted_at))*1000)
                        FILTER (WHERE filled_at IS NOT NULL AND submitted_at IS NOT NULL) as p99
                FROM order_states 
                WHERE tenant_id=$1 AND bot_id=$2 
                    AND submitted_at >= NOW() - INTERVAL '24 hours'
                GROUP BY bucket
                ORDER BY bucket""",
                tenant_id, bot_id
            )
            for row in latency_rows:
                bucket = row.get("bucket")
                if bucket:
                    latency_history.append({
                        "hour": bucket.strftime("%H:%M") if hasattr(bucket, "strftime") else str(bucket),
                        "p50": round(float(row.get("p50") or 0), 1),
                        "p95": round(float(row.get("p95") or 0), 1),
                        "p99": round(float(row.get("p99") or 0), 1),
                    })
            
            # Fill rate breakdown by hour (last 24 hours)
            fill_rows = await timescale.pool.fetch(
                """SELECT 
                    date_trunc('hour', updated_at) as bucket,
                    COUNT(*) FILTER (WHERE status = 'filled') as filled,
                    COUNT(*) FILTER (WHERE status = 'partially_filled') as partial,
                    COUNT(*) FILTER (WHERE status IN ('canceled', 'cancelled')) as cancelled,
                    COUNT(*) FILTER (WHERE status IN ('rejected', 'failed')) as rejected
                FROM order_states 
                WHERE tenant_id=$1 AND bot_id=$2 
                    AND updated_at >= NOW() - INTERVAL '24 hours'
                GROUP BY bucket
                ORDER BY bucket""",
                tenant_id, bot_id
            )
            for row in fill_rows:
                bucket = row.get("bucket")
                if bucket:
                    fill_rate_history.append({
                        "hour": bucket.strftime("%H:%M") if hasattr(bucket, "strftime") else str(bucket),
                        "filled": int(row.get("filled") or 0),
                        "partial": int(row.get("partial") or 0),
                        "cancelled": int(row.get("cancelled") or 0),
                        "rejected": int(row.get("rejected") or 0),
                    })
        except Exception:
            pass
        # Fallback: derive hourly charts from order_events when order_states has no rows yet.
        if not latency_history or not fill_rate_history:
            cutoff_ts = time.time() - 24 * 3600
            hourly: dict[str, dict] = {}
            for e in events:
                event_ts = _coerce_epoch_timestamp(e.get("timestamp") or e.get("ts"))
                if not event_ts or event_ts < cutoff_ts:
                    continue
                bucket = datetime.fromtimestamp(event_ts, timezone.utc).strftime("%H:00")
                slot = hourly.setdefault(
                    bucket,
                    {"latencies": [], "filled": 0, "partial": 0, "cancelled": 0, "rejected": 0},
                )
                status = str(e.get("status") or "").lower()
                if status == "filled":
                    slot["filled"] += 1
                elif status in {"partial", "partially_filled"}:
                    slot["partial"] += 1
                elif status in {"canceled", "cancelled"}:
                    slot["cancelled"] += 1
                elif status in {"rejected", "failed", "error"}:
                    slot["rejected"] += 1
                latency = _safe_float(e.get("latency_ms") or e.get("fill_time_ms"))
                if latency is not None and latency >= 0:
                    slot["latencies"].append(latency)

            def _percentile(values: list[float], q: float) -> float:
                if not values:
                    return 0.0
                ordered = sorted(values)
                idx = max(0, min(len(ordered) - 1, int(round((len(ordered) - 1) * q))))
                return float(ordered[idx])

            if not latency_history:
                for hour in sorted(hourly.keys()):
                    vals = hourly[hour]["latencies"]
                    latency_history.append(
                        {
                            "hour": hour,
                            "p50": round(_percentile(vals, 0.50), 1),
                            "p95": round(_percentile(vals, 0.95), 1),
                            "p99": round(_percentile(vals, 0.99), 1),
                        }
                    )
            if not fill_rate_history:
                for hour in sorted(hourly.keys()):
                    fill_rate_history.append(
                        {
                            "hour": hour,
                            "filled": int(hourly[hour]["filled"]),
                            "partial": int(hourly[hour]["partial"]),
                            "cancelled": int(hourly[hour]["cancelled"]),
                            "rejected": int(hourly[hour]["rejected"]),
                        }
                    )
        pending_history = await reader.read_history(
            f"quantgambit:{tenant_id}:{bot_id}:orders:history", limit=200
        )
        pending_statuses = {"new", "open", "pending", "partially_filled"}
        open_orders = len([o for o in pending_history if str(o.get("status", "")).lower() in pending_statuses])
        recent_orders = sorted(events, key=lambda e: _coerce_epoch_timestamp(e.get("timestamp") or e.get("ts")) or 0, reverse=True)[:10]
        # Filter ALL events for filled/closed first, then take top 10 (not just from recent_orders)
        all_trades = [e for e in events if str(e.get("status", "")).lower() in {"filled", "closed"}]
        recent_trades = sorted(all_trades, key=lambda e: _coerce_epoch_timestamp(e.get("timestamp") or e.get("ts")) or 0, reverse=True)[:10]
        recent_orders_payload = [
            {
                "id": str(item.get("order_id") or item.get("client_order_id") or ""),
                "symbol": item.get("symbol"),
                "side": item.get("side"),
                "status": item.get("status"),
                "type": item.get("order_type"),
                "size": _safe_float(item.get("size") or item.get("filled_size") or item.get("quantity")),
                "price": _safe_float(item.get("fill_price") or item.get("price") or item.get("entry_price")),
                "timestamp": _to_epoch_ms(item.get("timestamp") or item.get("ts")),
                "reason": item.get("reason") or item.get("rejection_reason"),
                "slippage_bps": _safe_float(item.get("slippage_bps")),
                "latency_ms": _safe_float(item.get("latency_ms") or item.get("fill_time_ms")),
            }
            for item in recent_orders
        ]
        recent_trades_payload = [_normalize_trade_event(item) for item in recent_trades]
        # Use DB stats for slippage/latency if available, otherwise fall back to event-based
        final_slippage = avg_slippage_db or execution_summary.get("avg_slippage_bps", 0)
        final_latency = avg_roundtrip_ms or execution_summary.get("avg_execution_time_ms", 0)
        
        return {
            "data": {
                "quality": {
                    "overall": {
                        "avg_slippage_bps": final_slippage,
                        "avg_execution_time_ms": final_latency,
                        "rejection_rate": rejection_rate,
                        "fill_rate": execution_summary.get("fill_rate_pct", 0),
                        # Latency percentiles from actual timestamp data
                        "order_to_ack_p50": latency_percentiles["order_to_ack_p50"],
                        "order_to_ack_p95": latency_percentiles["order_to_ack_p95"],
                        "order_to_ack_p99": latency_percentiles["order_to_ack_p99"],
                        "ack_to_fill_p50": latency_percentiles["ack_to_fill_p50"],
                        "ack_to_fill_p95": latency_percentiles["ack_to_fill_p95"],
                        "ack_to_fill_p99": latency_percentiles["ack_to_fill_p99"],
                    },
                    "recent": {
                        "avg_slippage_bps": final_slippage,
                        "avg_execution_time_ms": final_latency,
                        "fill_rate": execution_summary.get("fill_rate_pct", 0),
                    },
                },
                "fill": execution_summary,
                "maker_ratio": None,  # Not available from exchange
                "open_orders": open_orders,
                "cancel_rate": 0,
                "replace_rate": 0,
                "reject_codes": list(reason_counts.keys()),
                # Hourly time-series data for charts
                "latency_history": latency_history,
                "fill_rate_history": fill_rate_history,
            },
            "rejectRate5m": (reject_5m / total_5m * 100.0),
            "rejectRate1h": (reject_1h / total_1h * 100.0),
            "topRejectReason": top_reason,
            "topRejectCount": top_reason_count,
            "recentOrders": recent_orders_payload,
            "recentTrades": recent_trades_payload,
        }

    @app.get("/api/dashboard/execution-slippage-rollup", response_model=dict, dependencies=[Depends(auth_dep)])
    async def dashboard_execution_slippage_rollup(
        tenant_id: str | None = None,
        bot_id: str | None = Query(default=None, alias="botId"),
        limit: int = Query(default=8, ge=1, le=50),
        redis_client=Depends(_redis_client),
    ):
        try:
            tenant_id, bot_id = _resolve_scope(tenant_id, bot_id)
        except Exception:
            return {"data": {"overall": None, "latest_symbol_side": None, "symbol_sides": []}}

        prefix = f"deeptrader:rollup:slippage:{tenant_id}:{bot_id}:"
        overall_key = f"{prefix}__overall__"

        def _decode_snapshot(raw: Any) -> Optional[dict[str, Any]]:
            if raw is None:
                return None
            try:
                if isinstance(raw, (bytes, bytearray)):
                    raw = raw.decode("utf-8")
                parsed = json.loads(raw) if isinstance(raw, str) else raw
                return parsed if isinstance(parsed, dict) else None
            except Exception:
                return None

        overall_raw = await redis_client.get(overall_key)
        overall = _decode_snapshot(overall_raw)

        symbol_side_rows: list[dict[str, Any]] = []
        pattern = f"{prefix}*:*"
        cursor = 0
        seen = 0
        # SCAN keeps this safe for production Redis.
        while True:
            cursor, keys = await redis_client.scan(cursor=cursor, match=pattern, count=100)
            if keys:
                for key in keys:
                    key_text = key.decode("utf-8") if isinstance(key, (bytes, bytearray)) else str(key)
                    if key_text.endswith("__overall__"):
                        continue
                    raw = await redis_client.get(key)
                    decoded = _decode_snapshot(raw)
                    if decoded is None:
                        continue
                    symbol_side_rows.append(decoded)
                    seen += 1
                    if seen >= 200:
                        break
            if cursor == 0 or seen >= 200:
                break

        symbol_side_rows.sort(
            key=lambda item: float(item.get("updated_at") or item.get("as_of_ts") or 0.0),
            reverse=True,
        )
        top = symbol_side_rows[:limit]
        latest_symbol_side = top[0] if top else None
        return {
            "data": {
                "overall": overall,
                "latest_symbol_side": latest_symbol_side,
                "symbol_sides": top,
                "updatedAt": int(time.time() * 1000),
            }
        }

    @app.post("/api/dashboard/execution-slippage-autotune", response_model=dict, dependencies=[Depends(auth_dep)])
    async def dashboard_execution_slippage_autotune(
        tenant_id: str | None = None,
        bot_id: str | None = Query(default=None, alias="botId"),
        apply: bool = Query(default=False),
        min_samples: int | None = Query(default=None, ge=1, le=10000),
        redis_client=Depends(_redis_client),
        pool=Depends(_dashboard_pool),
    ):
        tenant_id, bot_id = _resolve_scope(tenant_id, bot_id, require_explicit=True, allow_default=False)

        key = f"deeptrader:rollup:slippage:{tenant_id}:{bot_id}:__overall__"
        raw = await redis_client.get(key)
        if not raw:
            return {
                "data": {
                    "applied": False,
                    "reason": "rollup_unavailable",
                    "target_key": key,
                }
            }

        try:
            if isinstance(raw, (bytes, bytearray)):
                raw = raw.decode("utf-8")
            overall = json.loads(raw) if isinstance(raw, str) else raw
        except Exception:
            overall = None
        if not isinstance(overall, dict):
            return {"data": {"applied": False, "reason": "rollup_unparseable"}}

        observed = _safe_float(overall.get("avg_realized_slippage_bps_overall"))
        sample_count = int(_safe_float(overall.get("sample_count_overall")) or 0)
        required_samples = int(min_samples or int(os.getenv("SLIPPAGE_AUTOTUNE_MIN_SAMPLES", "20")))
        if observed <= 0 or sample_count < required_samples:
            return {
                "data": {
                    "applied": False,
                    "reason": "insufficient_samples",
                    "observed_bps": observed,
                    "sample_count": sample_count,
                    "min_samples": required_samples,
                }
            }

        cfg = await _fetch_row(
            pool,
            """
            SELECT id, profile_overrides
            FROM bot_exchange_configs
            WHERE bot_instance_id=$1 AND is_active=true AND deleted_at IS NULL
            ORDER BY updated_at DESC
            LIMIT 1
            """,
            bot_id,
        )
        if not cfg:
            raise HTTPException(status_code=404, detail="active_exchange_config_not_found")

        profile_overrides = cfg.get("profile_overrides") if isinstance(cfg, dict) else cfg["profile_overrides"]
        if isinstance(profile_overrides, str):
            try:
                profile_overrides = json.loads(profile_overrides)
            except json.JSONDecodeError:
                profile_overrides = {}
        if not isinstance(profile_overrides, dict):
            profile_overrides = {}

        current = (
            _safe_float((profile_overrides.get("cost_model") or {}).get("slippage_bps"))
            or _safe_float(profile_overrides.get("slippage_bps"))
            or observed
        )
        buffer_bps = _safe_float(os.getenv("SLIPPAGE_AUTOTUNE_BUFFER_BPS")) or 0.25
        min_bps = _safe_float(os.getenv("SLIPPAGE_AUTOTUNE_MIN_BPS")) or 0.5
        max_bps = _safe_float(os.getenv("SLIPPAGE_AUTOTUNE_MAX_BPS")) or 25.0
        max_step_bps = _safe_float(os.getenv("SLIPPAGE_AUTOTUNE_MAX_STEP_BPS")) or 1.0

        target = max(min_bps, min(max_bps, observed + buffer_bps))
        delta = target - current
        bounded_delta = max(-max_step_bps, min(max_step_bps, delta))
        recommended = round(current + bounded_delta, 4)

        result = {
            "applied": False,
            "config_id": str(cfg.get("id") if isinstance(cfg, dict) else cfg["id"]),
            "observed_bps": observed,
            "sample_count": sample_count,
            "current_bps": current,
            "recommended_bps": recommended,
            "target_bps": target,
            "bounded_delta_bps": bounded_delta,
            "buffer_bps": buffer_bps,
            "max_step_bps": max_step_bps,
        }
        if not apply:
            return {"data": result}

        if abs(bounded_delta) < 1e-9:
            result["applied"] = False
            result["reason"] = "already_aligned"
            return {"data": result}

        next_overrides = dict(profile_overrides)
        next_cost_model = dict(next_overrides.get("cost_model") or {})
        next_cost_model["slippage_bps"] = recommended
        next_overrides["cost_model"] = next_cost_model
        next_overrides["slippage_bps"] = recommended
        next_overrides["slippage_autotune"] = {
            "updated_at": time.time(),
            "observed_bps": observed,
            "sample_count": sample_count,
            "previous_bps": current,
            "recommended_bps": recommended,
            "buffer_bps": buffer_bps,
            "max_step_bps": max_step_bps,
        }

        await pool.execute(
            """
            UPDATE bot_exchange_configs
            SET profile_overrides=$3::jsonb, updated_at=NOW()
            WHERE id=$1 AND bot_instance_id=$2
            """,
            result["config_id"],
            bot_id,
            json.dumps(next_overrides),
        )
        result["applied"] = True
        return {"data": result}

    @app.get("/api/dashboard/order-attempts", response_model=dict, dependencies=[Depends(auth_dep)])
    async def dashboard_order_attempts(
        tenant_id: str | None = None,
        bot_id: str | None = Query(default=None, alias="botId"),
        limit: int = 100,
        redis_client=Depends(_redis_client),
        timescale=Depends(_timescale_reader),
    ):
        tenant_id, bot_id = _resolve_scope(tenant_id, bot_id)
        tenant_id = await _resolve_runtime_tenant_scope(
            redis_client,
            tenant_id,
            bot_id,
            suffixes=["orders:history", "control:state", "health:latest"],
        )
        rows = await timescale.pool.fetch(
            "SELECT ts, payload, symbol, exchange, bot_id FROM order_events "
            "WHERE tenant_id=$1 AND bot_id=$2 ORDER BY ts DESC LIMIT $3",
            tenant_id,
            bot_id,
            limit,
        )
        attempts: list[dict[str, Any]] = []
        status_counts = {
            "filled": 0,
            "rejected": 0,
            "failed": 0,
            "timeout": 0,
            "pending": 0,
        }
        rejection_reasons: dict[str, int] = {}
        by_symbol: dict[str, dict[str, int]] = {}
        by_profile: dict[str, dict[str, int]] = {}
        for row in rows:
            event = _merge_ts_payload(row)
            status = str(event.get("status") or "pending").lower()
            reason_raw = event.get("reason") or event.get("rejection_reason")
            reason_norm = str(reason_raw or "").lower()
            # Drop synthetic execution status rows that are not actual order attempts.
            # Older runtime versions emitted "failed/execution_retry" heartbeat-like rows
            # with no order_id/error context, which inflated failure stats.
            if (
                status == "failed"
                and reason_norm == "execution_retry"
                and not event.get("order_id")
                and not event.get("error_code")
                and not event.get("error_message")
            ):
                continue
            # Retry/in-flight updates are not failures; map them to pending bucket.
            if status in {"retrying", "submitted", "open", "new"}:
                status = "pending"
            if status not in status_counts:
                status = "failed"
            status_counts[status] += 1
            reason = reason_raw
            if reason and status in {"rejected", "failed", "timeout"}:
                reason_str = str(reason)
                rejection_reasons[reason_str] = rejection_reasons.get(reason_str, 0) + 1
            symbol = event.get("symbol") or "UNKNOWN"
            symbol_bucket = by_symbol.setdefault(symbol, {"attempts": 0, "filled": 0, "rejected": 0})
            symbol_bucket["attempts"] += 1
            if status == "filled":
                symbol_bucket["filled"] += 1
            if status in {"rejected", "failed", "timeout"}:
                symbol_bucket["rejected"] += 1
            profile_id = event.get("profile_id")
            if profile_id:
                profile_bucket = by_profile.setdefault(str(profile_id), {"attempts": 0, "filled": 0, "rejected": 0})
                profile_bucket["attempts"] += 1
                if status == "filled":
                    profile_bucket["filled"] += 1
                if status in {"rejected", "failed", "timeout"}:
                    profile_bucket["rejected"] += 1
            attempt = {
                "timestamp": _coerce_epoch_timestamp(event.get("timestamp") or event.get("ts")) or time.time(),
                "symbol": symbol,
                "side": event.get("side") or "unknown",
                "size_usd": _safe_float(event.get("size") or event.get("size_usd")),
                "quantity": _safe_float(event.get("size")),
                "price": _safe_float(event.get("entry_price") or event.get("fill_price") or event.get("price")),
                "status": status,
                "profile_id": event.get("profile_id"),
                "strategy_id": event.get("strategy_id"),
                "signal_strength": event.get("signal_strength"),
                "confidence": event.get("confidence"),
                "order_id": event.get("order_id"),
                "fill_price": event.get("fill_price"),
                "slippage_bps": event.get("slippage_bps"),
                "execution_time_ms": event.get("latency_ms"),
                "error_code": event.get("error_code"),
                "error_message": event.get("reason") or event.get("error_message"),
                "rejection_stage": event.get("rejection_stage"),
            }
            attempts.append(attempt)
        total_attempts = len(attempts)
        total_filled = status_counts.get("filled", 0)
        success_rate = (total_filled / total_attempts * 100.0) if total_attempts else 0.0
        stats = {
            "total_attempts": total_attempts,
            "total_filled": total_filled,
            "total_rejected": status_counts.get("rejected", 0),
            "total_failed": status_counts.get("failed", 0),
            "total_timeout": status_counts.get("timeout", 0),
            "rejection_reasons": rejection_reasons,
            "by_symbol": by_symbol,
            "by_profile": by_profile,
            "success_rate": success_rate,
        }
        return {"data": {"attempts": attempts, "stats": stats}}

    @app.get("/api/dashboard/rejected-signals", response_model=dict, dependencies=[Depends(auth_dep)])
    async def dashboard_rejected_signals(
        tenant_id: str | None = None,
        bot_id: str | None = Query(default=None, alias="botId"),
        limit: int = 50,
        redis_client=Depends(_redis_client),
    ):
        """Get recent rejected signals with detailed rejection reasons for dashboard display."""
        tenant_id, bot_id = _resolve_scope(tenant_id, bot_id)
        reader = RedisSnapshotReader(redis_client)
        key = f"quantgambit:{tenant_id}:{bot_id}:decision:rejections"
        history = await reader.read_history(key, limit=limit)
        
        rejections: list[dict[str, Any]] = []
        reason_counts: dict[str, int] = {}
        stage_counts: dict[str, int] = {}
        by_symbol: dict[str, dict[str, int]] = {}
        
        for item in history:
            reason = str(item.get("rejection_reason") or item.get("reason") or "unknown")
            stage = str(item.get("rejected_by") or item.get("rejection_stage") or "unknown")
            symbol = str(item.get("symbol") or "UNKNOWN")
            
            reason_counts[reason] = reason_counts.get(reason, 0) + 1
            stage_counts[stage] = stage_counts.get(stage, 0) + 1
            
            symbol_bucket = by_symbol.setdefault(symbol, {"total": 0, "reasons": {}})
            symbol_bucket["total"] += 1
            symbol_bucket["reasons"][reason] = symbol_bucket["reasons"].get(reason, 0) + 1
            
            # Extract key metrics for display
            snapshot = item.get("snapshot") or {}
            metrics = item.get("metrics") or {}
            resolved_params = item.get("resolved_params") or {}
            rejection_detail = item.get("rejection_detail") or {}
            
            rejection = {
                "timestamp": item.get("timestamp"),
                "symbol": symbol,
                "rejection_reason": reason,
                "rejection_stage": stage,
                "gates_passed": item.get("gates_passed") or [],
                "latency_ms": item.get("latency_ms"),
                # Market snapshot at rejection time
                "mid_price": snapshot.get("mid_price"),
                "spread_bps": snapshot.get("spread_bps"),
                "vol_regime": snapshot.get("vol_regime"),
                "trend_direction": snapshot.get("trend_direction"),
                "data_quality_score": snapshot.get("data_quality_score"),
                # Key metrics
                "trading_mode": metrics.get("trading_mode"),
                "min_depth_usd": metrics.get("min_depth_usd"),
                # Resolved parameters that may explain rejection
                "min_distance_from_poc_pct": resolved_params.get("min_distance_from_poc_pct"),
                "max_spread_bps": resolved_params.get("max_spread_bps"),
                "min_depth_per_side_usd": resolved_params.get("min_depth_per_side_usd"),
                # Rejection detail (strategy-specific)
                "rejection_detail": rejection_detail,
            }
            rejections.append(rejection)
        
        # Find top rejection reason
        top_reason = max(reason_counts.items(), key=lambda x: x[1])[0] if reason_counts else None
        top_reason_count = reason_counts.get(top_reason, 0) if top_reason else 0
        
        stats = {
            "total_rejections": len(rejections),
            "reason_counts": reason_counts,
            "stage_counts": stage_counts,
            "by_symbol": by_symbol,
            "top_reason": top_reason,
            "top_reason_count": top_reason_count,
        }
        
        return {"data": {"rejections": rejections, "stats": stats}}

    @app.get("/api/dashboard/blocking-intents", response_model=dict, dependencies=[Depends(auth_dep)])
    async def dashboard_blocking_intents(
        tenant_id: str | None = None,
        bot_id: str | None = Query(default=None, alias="botId"),
        limit: int = 50,
        timescale=Depends(_timescale_reader),
    ):
        """Get blocking/pending/submitted order intents that may prevent new trades."""
        tenant_id, bot_id = _resolve_scope(tenant_id, bot_id)
        
        # Query order_intents table for pending/submitted intents
        blocking_rows = await timescale.pool.fetch(
            """
            SELECT symbol, side, size, status, last_error, created_at, submitted_at,
                   stop_loss, take_profit, client_order_id
            FROM order_intents 
            WHERE tenant_id=$1 AND bot_id=$2 
              AND status IN ('pending', 'submitted')
            ORDER BY created_at DESC 
            LIMIT $3
            """,
            tenant_id,
            bot_id,
            limit,
        )
        
        # Also get recent failures to help diagnose issues
        failed_rows = await timescale.pool.fetch(
            """
            SELECT symbol, side, size, status, last_error, created_at, submitted_at
            FROM order_intents 
            WHERE tenant_id=$1 AND bot_id=$2 
              AND status = 'failed'
              AND created_at > NOW() - INTERVAL '1 hour'
            ORDER BY created_at DESC 
            LIMIT $3
            """,
            tenant_id,
            bot_id,
            limit,
        )
        
        # Get intent stats
        stats_rows = await timescale.pool.fetch(
            """
            SELECT status, COUNT(*) as count
            FROM order_intents 
            WHERE tenant_id=$1 AND bot_id=$2
            GROUP BY status
            """,
            tenant_id,
            bot_id,
        )
        
        # Get failure reasons
        reason_rows = await timescale.pool.fetch(
            """
            SELECT last_error, COUNT(*) as count
            FROM order_intents 
            WHERE tenant_id=$1 AND bot_id=$2 
              AND status = 'failed'
              AND last_error IS NOT NULL
            GROUP BY last_error
            ORDER BY count DESC
            LIMIT 10
            """,
            tenant_id,
            bot_id,
        )
        
        def _row_to_dict(r: Any) -> dict[str, Any]:
            created = r.get("created_at")
            return {
                "symbol": r.get("symbol"),
                "side": r.get("side"),
                "size": float(r.get("size") or 0),
                "status": r.get("status"),
                "lastError": r.get("last_error"),
                "stopLoss": float(r.get("stop_loss") or 0) if r.get("stop_loss") else None,
                "takeProfit": float(r.get("take_profit") or 0) if r.get("take_profit") else None,
                "clientOrderId": r.get("client_order_id"),
                "createdAt": created.isoformat() if created else None,
                "submittedAt": r.get("submitted_at").isoformat() if r.get("submitted_at") else None,
                "ageSeconds": (datetime.now(timezone.utc) - created).total_seconds() if created else None,
            }
        
        blocking = [_row_to_dict(r) for r in blocking_rows]
        failed = [_row_to_dict(r) for r in failed_rows]
        
        stats = {s.get("status"): s.get("count") for s in stats_rows}
        failure_reasons = {r.get("last_error"): r.get("count") for r in reason_rows}
        
        return {
            "blocking": blocking,
            "blockingCount": len(blocking),
            "recentFailures": failed,
            "recentFailureCount": len(failed),
            "stats": stats,
            "failureReasons": failure_reasons,
            "hasBlockingIntents": len(blocking) > 0,
        }

    @app.get("/api/dashboard/market-context", response_model=dict, dependencies=[Depends(auth_dep)])
    async def dashboard_market_context(
        tenant_id: str | None = None,
        bot_id: str | None = Query(default=None, alias="botId"),
        symbol: str | None = None,
        redis_client=Depends(_redis_client),
    ):
        tenant_id, bot_id = _resolve_scope(tenant_id, bot_id)
        max_rows = max(20, int(_safe_float(os.getenv("MARKET_CONTEXT_MAX_ROWS"), 200)))
        query_timeout_sec = max(0.2, float(_safe_float(os.getenv("MARKET_CONTEXT_QUERY_TIMEOUT_SEC"), 1.5)))
        query = (
            "SELECT DISTINCT ON (symbol) symbol, spread_bps, depth_usd, funding_rate, iv, vol, created_at "
            "FROM market_context WHERE tenant_id=$1 AND bot_id=$2 "
        )
        params: list[Any] = [tenant_id, bot_id]
        if symbol:
            query += "AND UPPER(symbol)=UPPER($3) "
            params.append(symbol)
        query += f"ORDER BY symbol, created_at DESC LIMIT ${len(params)+1}"
        params.append(max_rows)
        rows, timed_out = await _fetch_timescale_rows_timeboxed(query, *params, timeout_sec=query_timeout_sec)
        contexts: dict[str, dict[str, Any]] = {}
        for row in rows:
            sym = str(row.get("symbol") or "UNKNOWN").upper()
            spread_missing = row.get("spread_bps") is None
            depth_missing = row.get("depth_usd") is None
            funding_missing = row.get("funding_rate") is None
            iv_missing = row.get("iv") is None
            vol_missing = row.get("vol") is None
            spread_bps = _safe_float(row.get("spread_bps"), 0.0) or 0.0
            depth_usd = _safe_float(row.get("depth_usd"), 0.0) or 0.0
            funding_rate = _safe_float(row.get("funding_rate"), 0.0) or 0.0
            iv = _safe_float(row.get("iv"), 0.0) or 0.0
            vol = _safe_float(row.get("vol"), 0.0) or 0.0
            ts_iso = _to_iso8601(row.get("created_at"))
            # For perp-first bots, plain *USDT symbols are treated as perp unless explicit
            # instrument metadata is available elsewhere.
            instrument_type = "perp"
            if "-" in sym:
                if "SWAP" in sym or "PERP" in sym:
                    instrument_type = "perp"
                elif any(ch.isdigit() for ch in sym):
                    instrument_type = "futures"
                else:
                    instrument_type = "spot"

            contexts[sym] = {
                # Canonical + backward-compatible keys.
                "symbol": sym,
                "timestamp": ts_iso,
                "instrument_type": instrument_type,
                "spread_bps": spread_bps,
                "spreadBps": spread_bps,
                "spread_missing": spread_missing,
                "bid_depth_usd": depth_usd / 2.0 if depth_usd > 0 else 0.0,
                "ask_depth_usd": depth_usd / 2.0 if depth_usd > 0 else 0.0,
                "depth_usd": depth_usd,
                "depthUsd": depth_usd,
                "depth_missing": depth_missing,
                "funding_rate": funding_rate,
                "fundingRate": funding_rate,
                "funding_missing": funding_missing,
                "iv": iv,
                "iv_missing": iv_missing,
                "vol": vol,
                "volatility_percentile": vol,
                "vol_missing": vol_missing,
                "volatility_regime": ("high" if vol >= 80 else "low" if vol <= 20 else "normal"),
                "liquidity_regime": ("thin" if depth_usd < 50000 else "normal"),
                "context_source": "market_context",
            }

        fallback_query = (
            "SELECT DISTINCT ON (symbol) symbol, ts, close "
            "FROM market_candles "
            "WHERE tenant_id=$1 AND bot_id=$2 "
        )
        fallback_params: list[Any] = [tenant_id, bot_id]
        if symbol:
            fallback_query += "AND UPPER(symbol)=UPPER($3) "
            fallback_params.append(symbol)
        fallback_query += f"ORDER BY symbol, ts DESC LIMIT ${len(fallback_params)+1}"
        fallback_params.append(max_rows)
        fallback_rows, candle_timeout = await _fetch_timescale_rows_timeboxed(
            fallback_query,
            *fallback_params,
            timeout_sec=query_timeout_sec,
        )
        for row in fallback_rows:
            sym = str(row.get("symbol") or "").strip().upper()
            if not sym or sym in contexts:
                continue
            ts_iso = _to_iso8601(row.get("ts"))
            contexts[sym] = {
                "symbol": sym,
                "timestamp": ts_iso,
                "instrument_type": "perp",
                "spread_bps": 0.0,
                "spreadBps": 0.0,
                "spread_missing": True,
                "bid_depth_usd": 0.0,
                "ask_depth_usd": 0.0,
                "depth_usd": 0.0,
                "depthUsd": 0.0,
                "depth_missing": True,
                "funding_rate": 0.0,
                "fundingRate": 0.0,
                "funding_missing": True,
                "iv": 0.0,
                "iv_missing": True,
                "vol": 50.0,
                "volatility_percentile": 50.0,
                "vol_missing": True,
                "volatility_regime": "normal",
                "liquidity_regime": "thin",
                "last_price": _safe_float(row.get("close"), 0.0),
                "context_source": "candle_fallback",
            }

        # Depth/spread fallback from orderbook_events when market_context rows are sparse.
        ob_query = (
            "SELECT DISTINCT ON (symbol) symbol, ts, "
            "NULLIF(payload->>'bid_depth_usd','')::double precision AS bid_depth_usd, "
            "NULLIF(payload->>'ask_depth_usd','')::double precision AS ask_depth_usd "
            "FROM orderbook_events "
            "WHERE tenant_id=$1 AND bot_id=$2 "
        )
        ob_params: list[Any] = [tenant_id, bot_id]
        if symbol:
            ob_query += "AND UPPER(symbol)=UPPER($3) "
            ob_params.append(symbol)
        ob_query += f"ORDER BY symbol, ts DESC LIMIT ${len(ob_params)+1}"
        ob_params.append(max_rows)
        ob_rows, orderbook_timeout = await _fetch_timescale_rows_timeboxed(
            ob_query,
            *ob_params,
            timeout_sec=query_timeout_sec,
        )
        for row in ob_rows:
            sym = str(row.get("symbol") or "").strip().upper()
            if not sym:
                continue
            bid_depth = _safe_float(row.get("bid_depth_usd"), 0.0) or 0.0
            ask_depth = _safe_float(row.get("ask_depth_usd"), 0.0) or 0.0
            depth_usd = bid_depth + ask_depth
            spread_bps = None
            ts_iso = _to_iso8601(row.get("ts"))
            existing = contexts.get(sym)
            if existing is None:
                contexts[sym] = {
                    "symbol": sym,
                    "timestamp": ts_iso,
                    "instrument_type": "perp",
                    "spread_bps": float(spread_bps or 0.0),
                    "spreadBps": float(spread_bps or 0.0),
                    "spread_missing": spread_bps is None,
                    "bid_depth_usd": bid_depth,
                    "ask_depth_usd": ask_depth,
                    "depth_usd": depth_usd,
                    "depthUsd": depth_usd,
                    "depth_missing": depth_usd <= 0.0,
                    "funding_rate": 0.0,
                    "fundingRate": 0.0,
                    "funding_missing": True,
                    "iv": 0.0,
                    "iv_missing": True,
                    "vol": 50.0,
                    "volatility_percentile": 50.0,
                    "vol_missing": True,
                    "volatility_regime": "normal",
                    "liquidity_regime": ("thin" if depth_usd < 50000 else "normal"),
                    "context_source": "orderbook_fallback",
                }
                continue
            if float(existing.get("depth_usd") or 0.0) <= 0.0 and depth_usd > 0.0:
                existing["bid_depth_usd"] = bid_depth
                existing["ask_depth_usd"] = ask_depth
                existing["depth_usd"] = depth_usd
                existing["depthUsd"] = depth_usd
                existing["depth_missing"] = False
                existing["liquidity_regime"] = "thin" if depth_usd < 50000 else "normal"
                existing["context_source"] = "orderbook_fallback"
            if bool(existing.get("spread_missing")) and spread_bps is not None:
                existing["spread_bps"] = float(spread_bps)
                existing["spreadBps"] = float(spread_bps)
                existing["spread_missing"] = False
            if not existing.get("timestamp") and ts_iso:
                existing["timestamp"] = ts_iso

        cache_health: dict[str, dict[str, Any]] = {}
        now_epoch = time.time()
        for sym, ctx in contexts.items():
            age_ms: int | None = None
            ts_epoch = _as_epoch_seconds(ctx.get("timestamp"))
            if ts_epoch is not None:
                age_ms = max(0, int((now_epoch - ts_epoch) * 1000.0))
            cache_health[sym] = {
                "age_ms": age_ms,
                "stale": bool(age_ms is not None and age_ms > 120_000),
                "timestamp": int(ts_epoch * 1000) if ts_epoch is not None else None,
            }

        feature_health = {
            "summary": {
                "symbols": len(contexts),
                "timedOut": bool(timed_out),
                "fallbackFromCandles": int(sum(1 for c in contexts.values() if str(c.get("context_source") or "") == "candle_fallback")),
            }
        }
        diagnostics = {
            "contextQueryTimedOut": bool(timed_out),
            "candleQueryTimedOut": bool(candle_timeout),
            "orderbookQueryTimedOut": bool(orderbook_timeout),
        }
        context_list = list(contexts.values())
        spreads = [float(c.get("spread_bps") or 0.0) for c in context_list if not c.get("spread_missing")]
        vols = [float(c.get("volatility_percentile") or 0.0) for c in context_list if not c.get("vol_missing")]
        depths = [float(c.get("depth_usd") or 0.0) for c in context_list if not c.get("depth_missing")]

        avg_spread = (sum(spreads) / len(spreads)) if spreads else 0.0
        avg_vol = (sum(vols) / len(vols)) if vols else 50.0
        avg_depth = (sum(depths) / len(depths)) if depths else 0.0
        spread_regime = "extreme" if avg_spread >= 3.0 else "widened" if avg_spread >= 1.5 else "normal"
        vol_regime = "spike" if avg_vol >= 80.0 else "elevated" if avg_vol >= 65.0 else "normal"
        liq_regime = "cliffy" if avg_depth < 25_000 else "thin" if avg_depth < 100_000 else "normal"

        symbol_opportunities = []
        for sym, ctx in contexts.items():
            spread = float(ctx.get("spread_bps") or 0.0)
            vol_pct = float(ctx.get("volatility_percentile") or 0.0)
            vol_pct_effective = vol_pct if not bool(ctx.get("vol_missing")) else 50.0
            depth = float(ctx.get("depth_usd") or 0.0)
            tradable = (
                not bool(ctx.get("spread_missing"))
                and not bool(ctx.get("depth_missing"))
                and spread <= 3.0
                and depth >= 50_000
                and 20.0 <= vol_pct_effective <= 80.0
            )
            blocked_reason = None
            if not tradable:
                if bool(ctx.get("spread_missing")) or bool(ctx.get("depth_missing")):
                    blocked_reason = "missing_market_context"
                elif spread > 3.0:
                    blocked_reason = "spread_too_wide"
                elif depth < 50_000:
                    blocked_reason = "insufficient_depth"
                else:
                    blocked_reason = "volatility_out_of_band"
            symbol_opportunities.append(
                {
                    "symbol": sym,
                    "spreadBps": spread,
                    "volatilityPercentile": vol_pct_effective,
                    "volatilityFallbackUsed": bool(ctx.get("vol_missing")),
                    "depthUsd": depth,
                    "tradable": tradable,
                    "blockedReason": blocked_reason,
                }
            )

        trading_gates = [
            {"key": "data_ready", "name": "Data Ready", "threshold": "Connected", "actual": "Connected" if context_list else "Disconnected", "unit": "", "passed": bool(context_list), "severity": "critical", "blocking": True},
            {"key": "spread_cap", "name": "Avg Spread", "threshold": 3.0, "actual": round(avg_spread, 3), "unit": "bp", "passed": avg_spread <= 3.0, "severity": "warning", "blocking": False},
            {"key": "vol_band", "name": "Vol Band", "threshold": "20-80", "actual": round(avg_vol, 1), "unit": "pct", "passed": 20.0 <= avg_vol <= 80.0, "severity": "warning", "blocking": False},
            {"key": "liquidity_min", "name": "Avg Depth", "threshold": 50_000, "actual": round(avg_depth, 2), "unit": "usd", "passed": avg_depth >= 50_000, "severity": "critical", "blocking": True},
        ]

        recommendations: list[str] = []
        if spread_regime != "normal":
            recommendations.append(f"Spread regime is {spread_regime}; reduce size or wait")
        if vol_regime != "normal":
            recommendations.append(f"Volatility regime is {vol_regime}; avoid forcing entries")
        if liq_regime != "normal":
            recommendations.append(f"Liquidity regime is {liq_regime}; prioritize liquid symbols")
        if not recommendations:
            recommendations.append("Conditions are broadly normal; follow standard profile routing")

        selected_profile_id: str | None = None
        try:
            reader = RedisSnapshotReader(redis_client)
            key_latest = f"quantgambit:{tenant_id}:{bot_id}:profile_router:latest"
            snap = await reader.read(key_latest) or {}
            if not snap:
                symbol_keys = await _scan_redis_keys(
                    redis_client,
                    f"quantgambit:{tenant_id}:{bot_id}:profile_router:*:latest",
                    limit=20,
                    timeout_sec=0.5,
                )
                symbol_keys = [k for k in symbol_keys if not k.endswith(":profile_router:latest")]
                best_ts = 0.0
                for key in symbol_keys[:20]:
                    try:
                        item = await asyncio.wait_for(reader.read(key), timeout=0.08) or {}
                    except Exception:
                        item = {}
                    if not item:
                        continue
                    ts = _as_epoch_seconds(item.get("timestamp")) or 0.0
                    if ts >= best_ts:
                        best_ts = ts
                        snap = item
            if isinstance(snap, dict):
                value = str(snap.get("selected_profile_id") or "").strip()
                if value:
                    selected_profile_id = value
        except Exception:
            selected_profile_id = None

        now_ms = int(time.time() * 1000)
        return {
            "contexts": contexts,
            "featureHealth": feature_health,
            "cacheHealth": cache_health,
            "diagnostics": diagnostics,
            "updatedAt": now_ms,
            # Legacy/summary payload expected by Market Context UI panels.
            "timestamp": now_ms,
            "marketRegime": {
                "spreadRegime": spread_regime,
                "volRegime": vol_regime,
                "liqRegime": liq_regime,
                "avgSpreadBps": round(avg_spread, 4),
                "avgVolPercentile": round(avg_vol, 2),
                "avgDepthUsd": round(avg_depth, 2),
            },
            "profileRouting": {
                "enabled": True,
                "selectedProfile": selected_profile_id,
            },
            "symbolOpportunities": sorted(symbol_opportunities, key=lambda row: (not bool(row["tradable"]), row["symbol"])),
            "tradingGates": trading_gates,
            "recommendations": recommendations,
        }

    @app.get("/api/dashboard/signals", response_model=SignalLabSnapshotResponse, dependencies=[Depends(auth_dep)])
    async def dashboard_signals_snapshot(
        tenant_id: str | None = None,
        bot_id: str | None = Query(default=None, alias="botId"),
        limit: int = 50,
    ):
        tenant_id, bot_id = _resolve_scope(tenant_id, bot_id)
        rows = await _fetch_timescale_rows(
            "SELECT ts, symbol, payload FROM decision_events "
            "WHERE tenant_id=$1 AND bot_id=$2 ORDER BY ts DESC LIMIT $3",
            tenant_id,
            bot_id,
            limit,
        )
        recent = [
            {
                "symbol": row.get("symbol"),
                "decision": payload.get("decision"),
                "reason": _extract_rejection_reason(payload),
                "score": _safe_float(payload.get("score")),
                "timeframe": payload.get("timeframe"),
                "pnl": _safe_float(payload.get("pnl")),
                "timestamp": _to_iso8601(row.get("ts")),
            }
            for row in rows
            for payload in [_coerce_json_dict(row.get("payload"))]
        ]
        return SignalLabSnapshotResponse(
            stageRejections={},
            featureHealth={},
            componentDiagnostics={},
            allocator={},
            bladeStatus={},
            bladeSignals={"recent": recent},
            bladeMetrics={},
            eventBus={},
            recentDecisions=recent,
            updatedAt=int(time.time() * 1000),
        )

    @app.get("/api/dashboard/signals/funnel", response_model=dict, dependencies=[Depends(auth_dep)])
    async def dashboard_signal_funnel(
        tenant_id: str | None = None,
        bot_id: str | None = Query(default=None, alias="botId"),
        window_minutes: int = 60,
        timeWindow: str | None = None,
        exchangeAccountId: str | None = None,
    ):
        _ = exchangeAccountId
        tenant_id, bot_id = _resolve_scope(tenant_id, bot_id)
        window_label, window_mins = _window_to_minutes(timeWindow, window_minutes)
        max_rows = max(200, int(_safe_float(os.getenv("SIGNAL_FUNNEL_MAX_ROWS"), 12000)))
        query_timeout_sec = max(0.2, float(_safe_float(os.getenv("SIGNAL_FUNNEL_QUERY_TIMEOUT_SEC"), 1.5)))
        decision_rows, decision_timeout = await _fetch_timescale_rows_timeboxed(
            "SELECT ts, payload FROM decision_events "
            "WHERE tenant_id=$1 AND bot_id=$2 "
            "AND ts >= NOW() - make_interval(mins => $3) "
            "ORDER BY ts DESC "
            "LIMIT $4",
            tenant_id,
            bot_id,
            window_mins,
            max_rows,
            timeout_sec=query_timeout_sec,
        )
        order_rows, order_timeout = await _fetch_timescale_rows_timeboxed(
            "SELECT payload FROM order_events "
            "WHERE tenant_id=$1 AND bot_id=$2 "
            "AND ts >= NOW() - make_interval(mins => $3) "
            "ORDER BY ts DESC "
            "LIMIT $4",
            tenant_id,
            bot_id,
            window_mins,
            max_rows,
            timeout_sec=query_timeout_sec,
        )

        filter_rejection_stages = {
            "prediction",
            "model",
            "signal",
            "confirmation",
            "spread_filter",
            "flow_filter",
            "quality_filter",
            "session_filter",
        }
        risk_rejection_stages = {
            "risk",
            "risk_limits",
            "risk_limit",
            "risk_guardrails",
            "risk_guardrail",
            "sizing",
            "position_limit",
            "emergency",
        }

        market_ticks = len(decision_rows)
        predictions_produced = 0
        signals_triggered = 0
        passed_filters = 0
        passed_risk = 0
        for row in decision_rows:
            payload = _coerce_json_dict(row.get("payload"))
            if isinstance(payload.get("prediction"), dict):
                predictions_produced += 1
            triggered = _is_signal_triggered(payload)
            if not triggered:
                continue
            signals_triggered += 1
            rejection_stage = _extract_rejection_stage(payload) or ""
            rejected = _decision_outcome(payload) == "rejected"
            if rejected and rejection_stage in filter_rejection_stages:
                continue
            passed_filters += 1
            if rejected and rejection_stage in risk_rejection_stages:
                continue
            passed_risk += 1

        orders_sent_statuses = {"submitted", "accepted", "open", "placed", "new", "filled", "partially_filled"}
        fill_statuses = {"filled", "partially_filled"}
        orders_sent = 0
        fills = 0
        for row in order_rows:
            payload = _coerce_json_dict(row.get("payload"))
            status = str(payload.get("status") or payload.get("order_status") or "").strip().lower()
            if status in orders_sent_statuses:
                orders_sent += 1
            if status in fill_statuses:
                fills += 1

        def _rate(numerator: int, denominator: int) -> float:
            if denominator <= 0:
                return 0.0
            return round((numerator / denominator) * 100.0, 2)

        return {
            "timeWindow": window_label,
            "stages": {
                "marketTicks": market_ticks,
                "predictionsProduced": predictions_produced,
                "signalsTriggered": signals_triggered,
                "passedFilters": passed_filters,
                "passedRiskGates": passed_risk,
                "ordersSent": orders_sent,
                "fills": fills,
            },
            "conversionRates": {
                "predictions": _rate(predictions_produced, market_ticks),
                "signals": _rate(signals_triggered, predictions_produced),
                "filters": _rate(passed_filters, signals_triggered),
                "risk": _rate(passed_risk, passed_filters),
                "orders": _rate(orders_sent, passed_risk),
                "fills": _rate(fills, orders_sent),
            },
            "diagnostics": {
                "queryTimeoutSec": query_timeout_sec,
                "maxRows": max_rows,
                "decisionQueryTimedOut": bool(decision_timeout),
                "orderQueryTimedOut": bool(order_timeout),
                "decisionRows": len(decision_rows),
                "orderRows": len(order_rows),
                "decisionRowsTruncated": len(decision_rows) >= max_rows,
                "orderRowsTruncated": len(order_rows) >= max_rows,
            },
            "updatedAt": int(time.time() * 1000),
        }

    @app.get("/api/dashboard/signals/symbols", response_model=dict, dependencies=[Depends(auth_dep)])
    async def dashboard_signal_symbols(
        tenant_id: str | None = None,
        bot_id: str | None = Query(default=None, alias="botId"),
        limit: int = 50,
        timeWindow: str | None = None,
        exchangeAccountId: str | None = None,
        redis_client=Depends(_redis_client),
    ):
        _ = exchangeAccountId
        tenant_id, bot_id = _resolve_scope(tenant_id, bot_id)
        _, window_mins = _window_to_minutes(timeWindow, 1440)
        query_timeout_sec = max(0.2, float(_safe_float(os.getenv("SIGNAL_SYMBOLS_QUERY_TIMEOUT_SEC"), 1.5)))
        rows, query_timed_out = await _fetch_timescale_rows_timeboxed(
            "SELECT ts, symbol, payload FROM decision_events "
            "WHERE tenant_id=$1 AND bot_id=$2 "
            "AND ts >= NOW() - make_interval(mins => $3) "
            "ORDER BY ts DESC "
            "LIMIT $4",
            tenant_id,
            bot_id,
            window_mins,
            limit,
            timeout_sec=query_timeout_sec,
        )

        latest_by_symbol: dict[str, dict[str, Any]] = {}
        latencies_by_symbol: dict[str, list[float]] = {}
        for row in rows:
            symbol = row.get("symbol")
            if not symbol:
                continue
            payload = _coerce_json_dict(row.get("payload"))
            latency = _safe_float(payload.get("latency_ms"), 0.0)
            if latency > 0:
                latencies_by_symbol.setdefault(symbol, []).append(latency)
            if symbol not in latest_by_symbol:
                latest_by_symbol[symbol] = {"ts": row.get("ts"), "payload": payload}

        # Fallback profile attribution map from live profile-router snapshots.
        routing_by_symbol: dict[str, dict[str, Any]] = {}
        try:
            reader = RedisSnapshotReader(redis_client)
            symbol_keys = await _scan_redis_keys(
                redis_client,
                f"quantgambit:{tenant_id}:{bot_id}:profile_router:*:latest",
                limit=20,
                timeout_sec=0.5,
            )
            symbol_keys = [k for k in symbol_keys if not k.endswith(":profile_router:latest")]
            for key in symbol_keys:
                try:
                    snap = await asyncio.wait_for(reader.read(key), timeout=0.08) or {}
                except Exception:
                    snap = {}
                sym = str((snap or {}).get("symbol") or "").upper()
                sel = str((snap or {}).get("selected_profile_id") or "").strip()
                if sym:
                    routing_by_symbol[sym] = {
                        "profile": sel or None,
                        "strategy": str((snap or {}).get("selected_strategy_id") or "").strip() or None,
                        "session": str((snap or {}).get("session") or "").strip().lower() or None,
                        "regime": str((snap or {}).get("regime") or "").strip().lower() or None,
                    }
        except Exception:
            routing_by_symbol = {}

        symbols: list[dict[str, Any]] = []
        for symbol, latest in latest_by_symbol.items():
            payload = latest.get("payload") or {}
            outcome = _decision_outcome(payload)
            signal = _extract_signal(payload)
            status = "no_signal"
            if outcome == "rejected":
                status = "blocked"
            elif signal.get("side") in {"long", "short"}:
                status = "tradable"
            profile_id, strategy_id = _extract_profile_strategy(payload)
            session, regime = _extract_session_regime(payload)
            routing = routing_by_symbol.get(symbol) or {}
            resolved_profile = profile_id or routing.get("profile") or "unknown"
            resolved_strategy = strategy_id or routing.get("strategy")
            resolved_session = session or routing.get("session")
            resolved_regime = regime or routing.get("regime")
            symbols.append(
                {
                    "symbol": symbol,
                    "status": status,
                    "profile": resolved_profile,
                    "strategy": resolved_strategy,
                    "session": resolved_session,
                    "regime": resolved_regime,
                    "signal": signal,
                    "blockingStage": _extract_rejection_stage(payload) if outcome == "rejected" else None,
                    "blockingReason": _extract_rejection_reason(payload) if outcome == "rejected" else None,
                    "lastDecision": _to_iso8601(latest.get("ts")),
                    "lastDecisionOutcome": outcome,
                    "latencyP95": round(_p95(latencies_by_symbol.get(symbol, [])), 2),
                }
            )

        symbols = sorted(symbols, key=lambda item: (item.get("status") != "blocked", item.get("symbol") or ""))
        return {
            "symbols": symbols,
            "configuredCount": len(symbols),
            "diagnostics": {
                "queryTimeoutSec": query_timeout_sec,
                "queryTimedOut": bool(query_timed_out),
                "rows": len(rows),
                "limit": limit,
            },
            "updatedAt": int(time.time() * 1000),
        }

    @app.get("/api/dashboard/signals/decisions/{symbol}", response_model=dict, dependencies=[Depends(auth_dep)])
    async def dashboard_signal_decisions(
        symbol: str,
        tenant_id: str | None = None,
        bot_id: str | None = Query(default=None, alias="botId"),
        limit: int = 50,
        exchangeAccountId: str | None = None,
        redis_client=Depends(_redis_client),
    ):
        _ = exchangeAccountId
        tenant_id, bot_id = _resolve_scope(tenant_id, bot_id)
        routing_fallback: dict[str, Any] = {}
        try:
            reader = RedisSnapshotReader(redis_client)
            key_symbol = f"quantgambit:{tenant_id}:{bot_id}:profile_router:{symbol.upper()}:latest"
            snap = await reader.read(key_symbol) or {}
            if isinstance(snap, dict):
                routing_fallback = {
                    "profile": str(snap.get("selected_profile_id") or "").strip() or None,
                    "strategy": str(snap.get("selected_strategy_id") or "").strip() or None,
                    "session": str(snap.get("session") or "").strip().lower() or None,
                    "regime": str(snap.get("regime") or "").strip().lower() or None,
                }
        except Exception:
            routing_fallback = {}
        rows = await _fetch_timescale_rows(
            "SELECT ts, symbol, payload FROM decision_events "
            "WHERE tenant_id=$1 AND bot_id=$2 AND symbol=$3 "
            "ORDER BY ts DESC LIMIT $4",
            tenant_id,
            bot_id,
            symbol,
            limit,
        )
        decisions: list[dict[str, Any]] = []
        for idx, row in enumerate(rows):
            payload = _coerce_json_dict(row.get("payload"))
            ts_iso = _to_iso8601(row.get("ts"))
            profile_id, strategy_id = _extract_profile_strategy(payload)
            session, regime = _extract_session_regime(payload)
            attempts = _extract_strategy_attempts(payload)
            decisions.append(
                {
                    "id": str(payload.get("event_id") or payload.get("decision_id") or f"{symbol}-{idx}-{ts_iso or 'na'}"),
                    "timestamp": ts_iso,
                    "outcome": _decision_outcome(payload),
                    "decisionType": payload.get("decision"),
                    "rejectionStage": _extract_rejection_stage(payload),
                    "rejectionReason": _extract_rejection_reason(payload),
                    "thresholds": payload.get("thresholds") if isinstance(payload.get("thresholds"), dict) else {},
                    "actuals": payload.get("actuals") if isinstance(payload.get("actuals"), dict) else {},
                    "stageTimings": payload.get("stage_timings") if isinstance(payload.get("stage_timings"), dict) else {},
                    "profile": profile_id or routing_fallback.get("profile"),
                    "strategy": strategy_id or routing_fallback.get("strategy"),
                    "session": session or routing_fallback.get("session"),
                    "regime": regime or routing_fallback.get("regime"),
                    "strategyAttempts": attempts,
                    "signal": _extract_signal(payload),
                    "latency": round(_safe_float(payload.get("latency_ms"), 0.0), 2),
                }
            )
        return {"symbol": symbol, "decisions": decisions, "count": len(decisions), "updatedAt": int(time.time() * 1000)}

    @app.get("/api/dashboard/signals/narrative", response_model=dict, dependencies=[Depends(auth_dep)])
    async def dashboard_signal_narrative(
        tenant_id: str | None = None,
        bot_id: str | None = Query(default=None, alias="botId"),
        timeWindow: str | None = None,
        exchangeAccountId: str | None = None,
    ):
        _ = exchangeAccountId
        tenant_id, bot_id = _resolve_scope(tenant_id, bot_id)
        window_label, window_mins = _window_to_minutes(timeWindow, 60)
        max_rows = max(200, int(_safe_float(os.getenv("SIGNAL_NARRATIVE_MAX_ROWS"), 10000)))
        query_timeout_sec = max(0.2, float(_safe_float(os.getenv("SIGNAL_NARRATIVE_QUERY_TIMEOUT_SEC"), 1.5)))
        decision_rows, decision_timeout = await _fetch_timescale_rows_timeboxed(
            "SELECT ts, payload FROM decision_events "
            "WHERE tenant_id=$1 AND bot_id=$2 "
            "AND ts >= NOW() - make_interval(mins => $3) "
            "ORDER BY ts DESC "
            "LIMIT $4",
            tenant_id,
            bot_id,
            window_mins,
            max_rows,
            timeout_sec=query_timeout_sec,
        )
        order_rows, order_timeout = await _fetch_timescale_rows_timeboxed(
            "SELECT payload FROM order_events "
            "WHERE tenant_id=$1 AND bot_id=$2 "
            "AND ts >= NOW() - make_interval(mins => $3) "
            "ORDER BY ts DESC "
            "LIMIT $4",
            tenant_id,
            bot_id,
            window_mins,
            max_rows,
            timeout_sec=query_timeout_sec,
        )
        diagnostics: dict[str, Any] = {
            "queryTimeoutSec": query_timeout_sec,
            "maxRows": max_rows,
            "decisionQueryTimedOut": bool(decision_timeout),
            "orderQueryTimedOut": bool(order_timeout),
            "decisionRows": len(decision_rows),
            "orderRows": len(order_rows),
            "decisionRowsTruncated": len(decision_rows) >= max_rows,
            "orderRowsTruncated": len(order_rows) >= max_rows,
        }

        signals_count = 0
        rejects_count = 0
        stage_counts: dict[str, int] = {}
        reason_counts: dict[str, int] = {}
        prediction_blocked = 0
        confirmation_blocked = 0
        flow_blocked = 0
        spread_blocked = 0
        risk_blocked = 0
        for row in decision_rows:
            payload = _coerce_json_dict(row.get("payload"))
            if _is_signal_triggered(payload):
                signals_count += 1
            if _decision_outcome(payload) == "rejected":
                rejects_count += 1
                stage = _extract_rejection_stage(payload) or "unknown"
                stage_counts[stage] = stage_counts.get(stage, 0) + 1
                reason = (_extract_rejection_reason(payload) or "").lower()
                if reason:
                    reason_counts[reason] = reason_counts.get(reason, 0) + 1
                if "prediction" in stage or "onnx" in reason or "entropy" in reason:
                    prediction_blocked += 1
                blocked_reason = str(
                    payload.get("prediction_blocked_reason")
                    or payload.get("prediction", {}).get("blocked_reason")
                    or ""
                ).strip().lower()
                if blocked_reason:
                    reason_counts[f"prediction_blocked:{blocked_reason}"] = (
                        reason_counts.get(f"prediction_blocked:{blocked_reason}", 0) + 1
                    )
                if "confirm" in stage or "confirmation" in reason:
                    confirmation_blocked += 1
                if "flow" in stage or "flow_" in reason or reason.startswith("flow"):
                    flow_blocked += 1
                if "spread" in stage or "spread" in reason:
                    spread_blocked += 1
                if "risk" in stage or "risk" in reason or "position_limit" in reason:
                    risk_blocked += 1

        fills = 0
        for row in order_rows:
            payload = _coerce_json_dict(row.get("payload"))
            status = str(payload.get("status") or payload.get("order_status") or "").strip().lower()
            if status in {"filled", "partially_filled"}:
                fills += 1

        top_stage = "none"
        top_count = 0
        if stage_counts:
            top_stage, top_count = max(stage_counts.items(), key=lambda item: item[1])
        top_pct = round((top_count / rejects_count) * 100.0, 2) if rejects_count > 0 else 0.0
        top_rejection_reasons = sorted(
            (
                {
                    "reason": reason,
                    "count": count,
                    "pct": round((count / rejects_count) * 100.0, 2) if rejects_count > 0 else 0.0,
                }
                for reason, count in reason_counts.items()
            ),
            key=lambda item: item["count"],
            reverse=True,
        )[:8]

        if signals_count <= 0 and rejects_count <= 0:
            narrative = f"No signal decisions observed in the last {window_label}. Runtime may still be warming up."
        elif rejects_count > 0:
            narrative = (
                f"Observed {signals_count} signal candidates and {rejects_count} rejections in the last {window_label}. "
                f"Top blocker is {top_stage} ({top_pct:.1f}% of rejects). "
                f"Prediction-gated={prediction_blocked}, confirmation-gated={confirmation_blocked}, "
                f"flow-gated={flow_blocked}, spread-gated={spread_blocked}, risk-gated={risk_blocked}."
            )
        else:
            narrative = f"Signal flow is healthy in the last {window_label}: {signals_count} candidates and {fills} fills."

        return {
            "narrative": narrative,
            "metrics": {
                "tradesCount": fills,
                "signalsCount": signals_count,
                "rejectsCount": rejects_count,
                "topRejectionStage": top_stage,
                "topRejectionPct": top_pct,
                "topRejectionReasons": top_rejection_reasons,
                "wsStatus": "connected" if decision_rows else "idle",
                "orderbookAge": 0,
                "modelWarmup": 100 if decision_rows else 0,
                "signalGenerationIssue": signals_count == 0 and rejects_count > 0,
            },
            "diagnostics": diagnostics,
            "timeWindow": window_label,
            "updatedAt": int(time.time() * 1000),
        }

    @app.get("/api/dashboard/strategy-status", response_model=dict, dependencies=[Depends(auth_dep)])
    async def dashboard_strategy_status(
        tenant_id: str | None = None,
        bot_id: str | None = Query(default=None, alias="botId"),
    ):
        tenant_id, bot_id = _resolve_scope(tenant_id, bot_id)
        rows = await _fetch_timescale_rows(
            "SELECT ts, symbol, payload FROM decision_events "
            "WHERE tenant_id=$1 AND bot_id=$2 ORDER BY ts DESC LIMIT 5",
            tenant_id,
            bot_id,
        )
        last = rows[0] if rows else None
        return {
            "strategy": {"id": bot_id, "name": "runtime", "description": "QuantGambit runtime strategy"},
            "conditions": {"required": [], "weights": {}},
            "featureStatus": {},
            "recentEvaluations": rows or [],
            "signalsGenerated": len(rows),
            "lastSignal": last,
            "updatedAt": int(time.time() * 1000),
        }

    @app.get("/api/dashboard/signals/confirmation-readiness", response_model=dict, dependencies=[Depends(auth_dep)])
    async def dashboard_confirmation_readiness(
        tenant_id: str | None = None,
        bot_id: str | None = Query(default=None, alias="botId"),
        timeWindow: str | None = None,
        exchangeAccountId: str | None = None,
        redis_client=Depends(_redis_client),
    ):
        _ = exchangeAccountId
        tenant_id, bot_id = _resolve_scope(tenant_id, bot_id)
        window_label, window_mins = _window_to_minutes(timeWindow, 60)
        cache_ttl_sec = max(0, int(_safe_float(os.getenv("CONFIRMATION_READY_CACHE_TTL_SEC"), 10)))
        cache_key = (
            f"quantgambit:{tenant_id}:{bot_id}:api:confirmation_readiness:{window_label}"
        )
        if cache_ttl_sec > 0:
            try:
                cached_raw = await redis_client.get(cache_key)
                if cached_raw:
                    cached_payload = _coerce_json_dict(cached_raw)
                    if cached_payload:
                        diagnostics = cached_payload.get("diagnostics")
                        if not isinstance(diagnostics, dict):
                            diagnostics = {}
                        diagnostics["cacheHit"] = True
                        cached_payload["diagnostics"] = diagnostics
                        return cached_payload
            except Exception:
                pass

        max_rows = max(1000, int(_safe_float(os.getenv("CONFIRMATION_READY_MAX_ROWS"), 20000)))
        query_timeout_sec = max(0.2, float(_safe_float(os.getenv("CONFIRMATION_READY_QUERY_TIMEOUT_SEC"), 2.0)))
        rows: list[dict[str, Any]] = []
        partial_diagnostics: dict[str, Any] = {"truncated": False, "queryTimeoutSec": query_timeout_sec}
        try:
            rows = await asyncio.wait_for(
                _fetch_timescale_rows(
                    "SELECT ts, symbol, payload FROM decision_events "
                    "WHERE tenant_id=$1 AND bot_id=$2 "
                    "AND ts >= NOW() - make_interval(mins => $3) "
                    "ORDER BY ts DESC "
                    "LIMIT $4",
                    tenant_id,
                    bot_id,
                    window_mins,
                    max_rows,
                ),
                timeout=query_timeout_sec,
            )
            partial_diagnostics["truncated"] = len(rows) >= max_rows
        except asyncio.TimeoutError:
            rows = []
            partial_diagnostics["decisionQueryTimedOut"] = True

        decision_count = 0
        decisions_with_shadow = 0
        comparison_count = 0
        mismatch_count = 0
        contract_violations = 0
        mode_counts: dict[str, int] = {}
        diff_reason_counts: dict[str, int] = {}
        pre_confirmation_blocked = 0
        pre_confirmation_stage_counts: dict[str, int] = {}
        pre_confirmation_reason_counts: dict[str, int] = {}
        outcome_samples: list[dict[str, Any]] = []
        per_symbol_costs = _parse_symbol_float_overrides(
            os.getenv("CONFIRMATION_READY_ESTIMATED_COST_BPS_BY_SYMBOL", "")
        )
        fallback_cost_bps = _safe_float(
            os.getenv("CONFIRMATION_READY_ESTIMATED_COST_BPS"),
            (
                _safe_float(os.getenv("FEE_BPS"), 5.5)
                + _safe_float(os.getenv("STRATEGY_SLIPPAGE_BPS"), 2.0)
                + _safe_float(os.getenv("EV_GATE_ADVERSE_SELECTION_BPS"), 2.0)
            ),
        )

        for row in rows:
            payload = _coerce_json_dict(row.get("payload"))
            decision_count += 1
            if payload.get("rejection_reason") == "stage_data_contract_violation":
                contract_violations += 1
            row_ts_epoch = _as_epoch_seconds(row.get("ts"))
            signal = _extract_signal(payload)
            signal_side = signal.get("side")
            symbol = str(payload.get("symbol") or row.get("symbol") or "").strip().upper()

            comparisons = payload.get("confirmation_shadow_comparisons")
            if not isinstance(comparisons, list) or not comparisons:
                outcome = _decision_outcome(payload)
                if outcome == "rejected":
                    stage = _extract_rejection_stage(payload) or "unknown"
                    reason = (_extract_rejection_reason(payload) or "unknown").strip().lower()
                    # Shadow comparisons are expected at/after confirmation stage.
                    # Rejections before that should be surfaced explicitly in readiness diagnostics.
                    if "confirm" not in stage:
                        pre_confirmation_blocked += 1
                        pre_confirmation_stage_counts[stage] = pre_confirmation_stage_counts.get(stage, 0) + 1
                        pre_confirmation_reason_counts[reason] = pre_confirmation_reason_counts.get(reason, 0) + 1
                continue
            decisions_with_shadow += 1
            comparison_count += len(comparisons)
            for item in comparisons:
                if not isinstance(item, dict):
                    continue
                mode = str(item.get("mode") or "unknown")
                mode_counts[mode] = mode_counts.get(mode, 0) + 1
                diff = bool(item.get("diff"))
                if diff:
                    mismatch_count += 1
                    reason = str(item.get("diff_reason") or "unknown")
                    diff_reason_counts[reason] = diff_reason_counts.get(reason, 0) + 1
                decision_context = str(item.get("decision_context") or "")
                if decision_context != "entry_live_signal":
                    continue
                comparison_side = str(item.get("side") or "").strip().lower()
                effective_side = signal_side if signal_side in {"long", "short"} else comparison_side
                if row_ts_epoch is None or not symbol or effective_side not in {"long", "short"}:
                    continue
                legacy_decision = bool(item.get("legacy_decision"))
                unified_decision = bool(item.get("unified_decision"))
                outcome_samples.append(
                    {
                        "ts_epoch": float(row_ts_epoch),
                        "symbol": symbol,
                        "side": effective_side,
                        "cohort": _confirmation_cohort(legacy_decision, unified_decision),
                        "estimated_cost_bps": float(per_symbol_costs.get(symbol, fallback_cost_bps)),
                    }
                )

        max_disagreement_pct = _safe_float(os.getenv("CONFIRMATION_READY_MAX_DISAGREEMENT_PCT"), 2.0)
        min_comparisons = int(_safe_float(os.getenv("CONFIRMATION_READY_MIN_COMPARISONS"), 500))
        max_contract_violations = int(_safe_float(os.getenv("CONFIRMATION_READY_MAX_CONTRACT_VIOLATIONS"), 0))
        readiness = _evaluate_confirmation_readiness(
            comparison_count=comparison_count,
            mismatch_count=mismatch_count,
            contract_violations=contract_violations,
            min_comparisons=min_comparisons,
            max_disagreement_pct=max_disagreement_pct,
            max_contract_violations=max_contract_violations,
        )

        outcome_horizon_minutes = max(1, int(_safe_float(os.getenv("CONFIRMATION_READY_MARKOUT_MINUTES"), 5)))
        outcome_min_samples = max(1, int(_safe_float(os.getenv("CONFIRMATION_READY_MIN_OUTCOME_SAMPLES"), 100)))
        outcome_min_unified_only_mean_bps = _safe_float(
            os.getenv("CONFIRMATION_READY_MIN_UNIFIED_ONLY_MEAN_BPS"),
            0.0,
        )
        outcome_min_unified_vs_legacy_delta_bps = _safe_float(
            os.getenv("CONFIRMATION_READY_MIN_UNIFIED_VS_LEGACY_DELTA_BPS"),
            0.0,
        )
        use_net_markout = os.getenv("CONFIRMATION_READY_USE_NET_MARKOUT", "true").strip().lower() in {
            "1",
            "true",
            "yes",
        }

        markout_summary = {"totalSamples": 0, "evaluatedSamples": 0, "cohorts": {}}
        if outcome_samples:
            symbols = sorted(
                {
                    str(item.get("symbol") or "").strip().upper()
                    for item in outcome_samples
                    if str(item.get("symbol") or "").strip()
                }
            )
            ts_values = [float(item["ts_epoch"]) for item in outcome_samples if item.get("ts_epoch") is not None]
            if symbols and ts_values:
                range_start = min(ts_values) - 120.0
                range_end = max(ts_values) + (outcome_horizon_minutes * 60.0) + 180.0
                try:
                    candle_rows = await asyncio.wait_for(
                        _fetch_timescale_rows(
                            """
                            SELECT EXTRACT(EPOCH FROM ts) AS ts_epoch, UPPER(symbol) AS symbol, close
                            FROM market_candles
                            WHERE tenant_id=$1
                              AND bot_id=$2
                              AND timeframe_sec=60
                              AND UPPER(symbol) = ANY($3::text[])
                              AND ts >= to_timestamp($4)
                              AND ts <= to_timestamp($5)
                            ORDER BY symbol ASC, ts ASC
                            """,
                            tenant_id,
                            bot_id,
                            symbols,
                            float(range_start),
                            float(range_end),
                        ),
                        timeout=query_timeout_sec,
                    )
                except asyncio.TimeoutError:
                    candle_rows = []
                    partial_diagnostics["candleQueryTimedOut"] = True
                markout_summary = _compute_confirmation_markout_stats(
                    samples=outcome_samples,
                    candle_rows=candle_rows,
                    horizon_sec=outcome_horizon_minutes * 60,
                )

        cohorts = markout_summary.get("cohorts") if isinstance(markout_summary.get("cohorts"), dict) else {}
        unified_only = cohorts.get("unified_only") if isinstance(cohorts.get("unified_only"), dict) else {}
        legacy_only = cohorts.get("legacy_only") if isinstance(cohorts.get("legacy_only"), dict) else {}
        unified_only_eval = int(unified_only.get("evaluated") or 0)
        legacy_only_eval = int(legacy_only.get("evaluated") or 0)
        unified_only_mean_gross = _safe_float(unified_only.get("meanMarkoutBps"), None)
        legacy_only_mean_gross = _safe_float(legacy_only.get("meanMarkoutBps"), None)
        unified_only_mean_net = _safe_float(unified_only.get("meanNetMarkoutBps"), None)
        legacy_only_mean_net = _safe_float(legacy_only.get("meanNetMarkoutBps"), None)
        unified_only_mean = unified_only_mean_net if use_net_markout else unified_only_mean_gross
        legacy_only_mean = legacy_only_mean_net if use_net_markout else legacy_only_mean_gross
        unified_minus_legacy = (
            (unified_only_mean - legacy_only_mean)
            if (unified_only_mean is not None and legacy_only_mean is not None)
            else None
        )
        unified_minus_legacy_gross = (
            (unified_only_mean_gross - legacy_only_mean_gross)
            if (unified_only_mean_gross is not None and legacy_only_mean_gross is not None)
            else None
        )
        unified_minus_legacy_net = (
            (unified_only_mean_net - legacy_only_mean_net)
            if (unified_only_mean_net is not None and legacy_only_mean_net is not None)
            else None
        )
        enough_unified_only = unified_only_eval >= outcome_min_samples
        enough_legacy_only = legacy_only_eval >= outcome_min_samples
        unified_only_edge_ok = bool(
            enough_unified_only
            and unified_only_mean is not None
            and unified_only_mean >= outcome_min_unified_only_mean_bps
        )
        unified_vs_legacy_ok = bool(
            (not enough_legacy_only)
            or (
                unified_minus_legacy is not None
                and unified_minus_legacy >= outcome_min_unified_vs_legacy_delta_bps
            )
        )
        outcome_ready = bool(enough_unified_only and unified_only_edge_ok and unified_vs_legacy_ok)
        recommended_ready_for_enforce = bool(readiness["ready_for_enforce"] and outcome_ready)

        top_diff_reasons = sorted(
            (
                {"reason": reason, "count": count}
                for reason, count in diff_reason_counts.items()
            ),
            key=lambda item: item["count"],
            reverse=True,
        )[:10]
        top_pre_confirmation_stages = sorted(
            (
                {"stage": stage, "count": count}
                for stage, count in pre_confirmation_stage_counts.items()
            ),
            key=lambda item: item["count"],
            reverse=True,
        )[:5]
        top_pre_confirmation_reasons = sorted(
            (
                {"reason": reason, "count": count}
                for reason, count in pre_confirmation_reason_counts.items()
            ),
            key=lambda item: item["count"],
            reverse=True,
        )[:8]
        top_pre_stage = top_pre_confirmation_stages[0]["stage"] if top_pre_confirmation_stages else None
        top_pre_count = int(top_pre_confirmation_stages[0]["count"]) if top_pre_confirmation_stages else 0
        pre_confirmation_blocked_pct = (
            round((pre_confirmation_blocked / decision_count) * 100.0, 2) if decision_count > 0 else 0.0
        )
        shadow_data_hint = None
        if comparison_count == 0 and pre_confirmation_blocked > 0:
            shadow_data_hint = (
                f"No shadow comparisons yet: {pre_confirmation_blocked} decisions "
                f"({pre_confirmation_blocked_pct:.2f}%) were rejected before confirmation "
                f"(top stage={top_pre_stage or 'unknown'}, n={top_pre_count})."
            )

        response_payload = {
            "timeWindow": window_label,
            "decisionCount": decision_count,
            "decisionsWithShadow": decisions_with_shadow,
            "comparisonCount": comparison_count,
            "mismatchCount": mismatch_count,
            "disagreementPct": readiness["disagreement_pct"],
            "contractViolations": contract_violations,
            "modeCounts": mode_counts,
            "topDiffReasons": top_diff_reasons,
            "thresholds": {
                "maxDisagreementPct": max_disagreement_pct,
                "minComparisons": min_comparisons,
                "maxContractViolations": max_contract_violations,
            },
            "checks": readiness["checks"],
            "readyForEnforce": readiness["ready_for_enforce"],
            "marketOutcome": {
                "horizonMinutes": outcome_horizon_minutes,
                "metric": "netMarkoutBps" if use_net_markout else "markoutBps",
                "estimatedCostBpsFallback": round(float(fallback_cost_bps), 3),
                "totalSamples": int(markout_summary.get("totalSamples") or 0),
                "evaluatedSamples": int(markout_summary.get("evaluatedSamples") or 0),
                "cohorts": cohorts,
                "deltaUnifiedMinusLegacyBps": (
                    round(unified_minus_legacy, 3) if unified_minus_legacy is not None else None
                ),
                "deltaUnifiedMinusLegacyGrossBps": (
                    round(unified_minus_legacy_gross, 3) if unified_minus_legacy_gross is not None else None
                ),
                "deltaUnifiedMinusLegacyNetBps": (
                    round(unified_minus_legacy_net, 3) if unified_minus_legacy_net is not None else None
                ),
            },
            "outcomeThresholds": {
                "minOutcomeSamples": outcome_min_samples,
                "minUnifiedOnlyMeanBps": outcome_min_unified_only_mean_bps,
                "minUnifiedVsLegacyDeltaBps": outcome_min_unified_vs_legacy_delta_bps,
            },
            "outcomeChecks": {
                "unified_only_samples_met": enough_unified_only,
                "unified_only_mean_markout_ok": unified_only_edge_ok,
                "unified_vs_legacy_delta_ok": unified_vs_legacy_ok,
            },
            "shadowData": {
                "decisionsWithoutShadow": int(max(0, decision_count - decisions_with_shadow)),
                "preConfirmationBlocked": int(pre_confirmation_blocked),
                "preConfirmationBlockedPct": pre_confirmation_blocked_pct,
                "topPreConfirmationStages": top_pre_confirmation_stages,
                "topPreConfirmationReasons": top_pre_confirmation_reasons,
                "hint": shadow_data_hint,
            },
            "outcomeReadyForEnforce": outcome_ready,
            "recommendedReadyForEnforce": recommended_ready_for_enforce,
            "diagnostics": partial_diagnostics,
            "updatedAt": int(time.time() * 1000),
        }
        if cache_ttl_sec > 0:
            try:
                await redis_client.setex(
                    cache_key,
                    cache_ttl_sec,
                    json.dumps(_sanitize_for_json(response_payload), allow_nan=False),
                )
            except Exception:
                pass
        return response_payload

    @app.get("/api/dashboard/trade-history", response_model=dict, dependencies=[Depends(auth_dep)])
    async def dashboard_trade_history(
        tenant_id: str | None = None,
        bot_id: str | None = Query(default=None, alias="botId"),
        limit: int = 200,
        offset: int = 0,
        window: str | None = None,
        symbol: str | None = None,
        side: str | None = None,
        status: str | None = Query(default="filled,closed", description="Comma-separated status filter. Default: filled,closed"),
        includeAll: bool = Query(default=False, description="Include all order events regardless of status"),
        showEntries: bool = Query(default=False, description="Include position entry events (open). Default: only show closes with PnL"),
        startDate: str | None = None,
        endDate: str | None = None,
        minPnl: float | None = None,
        maxPnl: float | None = None,
        exchangeAccountId: str | None = None,
        exchange_account_id: str | None = None,
        timescale=Depends(_timescale_reader),
        pool=Depends(_dashboard_pool),
    ):
        async def _discover_runtime_tenant(target_bot_id: str) -> str | None:
            bot_id_text = str(target_bot_id or "").strip()
            if not bot_id_text:
                return None
            try:
                row = await timescale.pool.fetchrow(
                    """
                    SELECT tenant_id, max(event_ts) AS last_seen
                    FROM (
                        SELECT tenant_id, ts AS event_ts
                        FROM order_events
                        WHERE bot_id = $1
                        UNION ALL
                        SELECT tenant_id, created_at AS event_ts
                        FROM order_lifecycle_events
                        WHERE bot_id = $1
                    ) t
                    GROUP BY tenant_id
                    ORDER BY last_seen DESC NULLS LAST
                    LIMIT 1
                    """,
                    bot_id_text,
                )
                if row:
                    tenant_val = row["tenant_id"]
                    return str(tenant_val).strip() if tenant_val is not None else None
            except Exception:
                return None
            return None

        # Resolve account_id from either parameter
        account_id = exchangeAccountId or exchange_account_id
        
        # If we have an exchange account but no bot, try to find the bot for this account
        if account_id and not bot_id and pool:
            try:
                resolved_bot = await _resolve_bot_from_exchange_account(pool, account_id)
                if resolved_bot:
                    bot_id = resolved_bot
            except Exception as exc:
                log_warning("replay_feature_dictionary_failed", error=str(exc), symbol=symbol)
        
        try:
            if bot_id and not tenant_id:
                discovered_tenant = await _discover_runtime_tenant(bot_id)
                if discovered_tenant:
                    tenant_id = discovered_tenant
            tenant_id, bot_id = _resolve_scope(tenant_id, bot_id)
        except Exception:
            return {"trades": [], "totalCount": 0, "stats": {}, "pagination": {"total": 0, "limit": limit, "offset": offset, "hasMore": False}}
        start_ts = _coerce_epoch_timestamp(startDate)
        end_ts = _coerce_epoch_timestamp(endDate)
        start_dt = datetime.fromtimestamp(start_ts, timezone.utc) if start_ts else None
        # If endDate is provided as a date string (not a full timestamp), interpret it as end of day
        end_dt = None
        if end_ts:
            end_dt = datetime.fromtimestamp(end_ts, timezone.utc)
            # If the time is exactly midnight, assume user meant "end of day" and add 23:59:59
            if end_dt.hour == 0 and end_dt.minute == 0 and end_dt.second == 0:
                end_dt = end_dt.replace(hour=23, minute=59, second=59, microsecond=999999)
        # Respect explicit `window` when dates are omitted; default to 72h so
        # exchange backfills are visible without requiring manual date filters.
        if start_dt is None and end_dt is None and not includeAll:
            _, window_minutes = _window_to_minutes(window, fallback_minutes=72 * 60)
            start_dt = datetime.now(timezone.utc) - timedelta(minutes=window_minutes)
        
        # Build status filter - by default only show completed trades
        status_filter = None
        if not includeAll and status:
            status_filter = [s.strip().lower() for s in status.split(",")]

        # Use order_events as the single source of truth for closes.
        # position_events can contain duplicate/derived lifecycle rows that diverge from
        # exchange-reconciled close events and cause PnL mismatches vs Orders & Fills.
        use_position_events = False
        if use_position_events:
            # Merge close events from both position_events and order_events.
            # position_events is preferred for cleaner realized PnL, but it can miss
            # exchange-close rows when local close synthesis fails.
            base_params: list[Any] = [tenant_id, bot_id]
            pos_where = (
                "WHERE tenant_id=$1 AND bot_id=$2 "
                "AND ("
                "(payload->>'event_type' = 'closed') "
                "OR (payload->>'position_effect' = 'close') "
                "OR (payload->>'reason' IN ('position_close', 'strategic_exit', 'stop_loss', 'take_profit')) "
                "OR payload::text LIKE '%\"status\": \"closed\"%'"
                ") "
            )
            ord_where = (
                "WHERE tenant_id=$1 AND bot_id=$2 "
                "AND ("
                "(payload->>'position_effect' = 'close') "
                "OR (payload->>'reason' IN ('position_close', 'strategic_exit', 'stop_loss', 'take_profit'))"
                ") "
            )
            if symbol:
                pos_where += f"AND symbol=${len(base_params)+1} "
                ord_where += f"AND symbol=${len(base_params)+1} "
                base_params.append(symbol)
            if start_dt:
                pos_where += f"AND ts >= ${len(base_params)+1} "
                ord_where += f"AND ts >= ${len(base_params)+1} "
                base_params.append(start_dt)
            if end_dt:
                pos_where += f"AND ts <= ${len(base_params)+1} "
                ord_where += f"AND ts <= ${len(base_params)+1} "
                base_params.append(end_dt)

            # Pull a bounded working set for accurate merge/dedupe.
            window_limit = min(max((offset + limit) * 5, 500), 5000)
            query_params = list(base_params)
            query_params.append(window_limit)
            pos_query = (
                f"SELECT ts, payload, symbol, exchange, bot_id FROM position_events {pos_where} "
                f"ORDER BY ts DESC LIMIT ${len(query_params)}"
            )
            ord_query = (
                f"SELECT ts, payload, symbol, exchange, bot_id FROM order_events {ord_where} "
                f"ORDER BY ts DESC LIMIT ${len(query_params)}"
            )
            try:
                pos_rows = await timescale.pool.fetch(pos_query, *query_params)
                ord_rows = await timescale.pool.fetch(ord_query, *query_params)
            except Exception:
                return {"trades": [], "totalCount": 0, "_warning": "timescale_unavailable"}

            def _row_to_event(row: Any, source: str) -> dict:
                payload = row.get("payload") if isinstance(row, dict) else row["payload"]
                if isinstance(payload, str):
                    try:
                        payload = json.loads(payload)
                    except Exception:
                        payload = {}
                event = dict(payload or {})
                event["ts"] = row.get("ts") if isinstance(row, dict) else row["ts"]
                event["symbol"] = row.get("symbol") or event.get("symbol")
                event["exchange"] = row.get("exchange") or event.get("exchange")
                event["_source_table"] = source
                # Normalize close_order_id for downstream dedupe/detail lookup.
                if event.get("close_order_id") and not event.get("order_id"):
                    event["order_id"] = event.get("close_order_id")
                return event

            merged_events = (
                [_row_to_event(r, "position_events") for r in pos_rows]
                + [_row_to_event(r, "order_events") for r in ord_rows]
            )

            # Deduplicate by order_id, preferring position_events rows with richer close data.
            seen_order_ids: dict[str, dict] = {}
            for event in merged_events:
                order_id = event.get("order_id") or event.get("client_order_id")
                if order_id:
                    existing = seen_order_ids.get(order_id)
                    if existing is None:
                        seen_order_ids[order_id] = event
                        continue
                    existing_is_pos = existing.get("_source_table") == "position_events"
                    new_is_pos = event.get("_source_table") == "position_events"
                    existing_pnl = existing.get("net_pnl") if existing.get("net_pnl") is not None else existing.get("realized_pnl")
                    new_pnl = event.get("net_pnl") if event.get("net_pnl") is not None else event.get("realized_pnl")
                    existing_has_filled_size = existing.get("filled_size") is not None
                    new_has_filled_size = event.get("filled_size") is not None
                    # Prefer the row with better close fidelity, not blindly by table.
                    # position_events can lag exchange-reconciled order_events.
                    existing_has_pnl = existing_pnl is not None and existing_pnl != 0
                    new_has_pnl = new_pnl is not None and new_pnl != 0
                    existing_reason = str(existing.get("reason") or "").lower()
                    new_reason = str(event.get("reason") or "").lower()
                    existing_is_exchange_reconciled = existing_reason in {"exchange_reconcile", "exchange_backfill"}
                    new_is_exchange_reconciled = new_reason in {"exchange_reconcile", "exchange_backfill"}
                    reason_rank = {
                        "exchange_reconcile": 6,
                        "exchange_backfill": 5,
                        "position_close": 4,
                        "strategic_exit": 3,
                        "stop_loss": 2,
                        "take_profit": 2,
                        "stop_loss_hit": 1,
                        "take_profit_hit": 1,
                        "execution_update": 0,
                    }
                    existing_reason_rank = reason_rank.get(existing_reason, 0)
                    new_reason_rank = reason_rank.get(new_reason, 0)
                    pnl_conflict = (
                        existing_has_pnl
                        and new_has_pnl
                        and abs(_safe_float(existing_pnl) - _safe_float(new_pnl)) > 1e-6
                    )
                    if pnl_conflict and existing_is_pos and not new_is_pos:
                        # Prefer order_events when PnL conflicts: this is where
                        # exchange-reconciled PnL is corrected.
                        seen_order_ids[order_id] = event
                    elif new_has_pnl and not existing_has_pnl:
                        seen_order_ids[order_id] = event
                    elif new_is_exchange_reconciled and not existing_is_exchange_reconciled:
                        seen_order_ids[order_id] = event
                    elif pnl_conflict and new_reason_rank > existing_reason_rank:
                        seen_order_ids[order_id] = event
                    elif new_is_pos and not existing_is_pos and not existing_has_pnl:
                        seen_order_ids[order_id] = event
                    elif new_has_filled_size and not existing_has_filled_size:
                        seen_order_ids[order_id] = event
                else:
                    seen_order_ids[f"no_order_id_{len(seen_order_ids)}"] = event

            deduped_events = list(seen_order_ids.values())
            trades = [_normalize_trade_event(e) for e in deduped_events]
            trades.sort(key=lambda t: t.get("timestamp") or t.get("ts") or 0, reverse=True)
            total_count = len(trades)
            trades = trades[offset : offset + limit]

            # Apply client-side filters
            if side:
                side_lower = side.lower()
                trades = [t for t in trades if str(t.get("side", "")).lower() == side_lower]
            if minPnl is not None:
                trades = [t for t in trades if _safe_float(t.get("pnl")) >= minPnl]
            if maxPnl is not None:
                trades = [t for t in trades if _safe_float(t.get("pnl")) <= maxPnl]

            stats = _compute_trade_history_stats(trades)
            stats["totalDbCount"] = total_count
            return {
                "trades": trades,
                "pagination": {
                    "total": total_count,
                    "limit": limit,
                    "offset": offset,
                    "hasMore": offset + limit < total_count,
                },
                "totalCount": total_count,
                "stats": stats,
                "filters": {
                    "symbol": symbol,
                    "side": side,
                    "startDate": startDate,
                    "endDate": endDate,
                },
                "updatedAt": int(time.time() * 1000),
            }
        
        # Build base WHERE clause for both count and data queries
        base_where = "WHERE tenant_id=$1 AND bot_id=$2 "
        params: list[Any] = [tenant_id, bot_id]
        
        # Add status filter to SQL query for efficiency
        if status_filter:
            base_where += f"AND LOWER(payload->>'status') = ANY(${len(params)+1}::text[]) "
            params.append(status_filter)
        
        # By default, only show position close events (which have PnL)
        # This filters out entry events that would appear as "duplicates"
        if not showEntries and not includeAll:
            base_where += (
                "AND (payload->>'position_effect' = 'close' "
                "OR payload->>'reason' IN ('position_close', 'strategic_exit', 'stop_loss', 'take_profit', 'exchange_reconcile', 'exchange_backfill')) "
            )
        
        if symbol:
            base_where += f"AND symbol=${len(params)+1} "
            params.append(symbol)
        if start_dt:
            base_where += f"AND ts >= ${len(params)+1} "
            params.append(start_dt)
        if end_dt:
            base_where += f"AND ts <= ${len(params)+1} "
            params.append(end_dt)
        
        # Pull a bounded working set and paginate after dedupe/normalization.
        # This prevents leg-level duplication from leaking into the visible page.
        total_count = 0
        # Keep working set bounded so trade-history remains responsive on large event tables.
        window_limit = min(max((offset + limit) * 6, 600), 4000)
        query = f"SELECT ts, payload, symbol, exchange, bot_id FROM order_events {base_where}"
        query += f"ORDER BY ts DESC LIMIT ${len(params)+1}"
        query_params = list(params)
        query_params.append(window_limit)
        
        used_position_fallback = False
        upstream_event_count = 0
        trade_history_timeout_sec = max(
            1.0,
            float(_safe_float(os.getenv("TRADE_HISTORY_QUERY_TIMEOUT_SEC"), 6.0)),
        )
        try:
            rows, query_timed_out = await _fetch_timescale_rows_timeboxed(
                query,
                *query_params,
                timeout_sec=trade_history_timeout_sec,
            )
            if query_timed_out:
                # Shared pool can saturate under heavy dashboard polling. Retry once
                # with a one-off direct connection to avoid user-visible empty history.
                direct_rows, direct_timed_out = await _fetch_timescale_rows_direct_timeboxed(
                    query,
                    *query_params,
                    timeout_sec=min(2.5, trade_history_timeout_sec),
                )
                if direct_rows:
                    rows = direct_rows
                    query_timed_out = False
                elif direct_timed_out:
                    query_timed_out = True
            events = [_merge_ts_payload(row) for row in rows]
            if query_timed_out and not events:
                # Fallback: use an index-friendly ts scan first, then filter close-like rows
                # in memory. This avoids JSON predicate scans under heavy load.
                pos_where = "WHERE tenant_id=$1 AND bot_id=$2 "
                pos_params: list[Any] = [tenant_id, bot_id]
                if symbol:
                    pos_where += f"AND symbol=${len(pos_params)+1} "
                    pos_params.append(symbol)
                if start_dt:
                    pos_where += f"AND ts >= ${len(pos_params)+1} "
                    pos_params.append(start_dt)
                if end_dt:
                    pos_where += f"AND ts <= ${len(pos_params)+1} "
                    pos_params.append(end_dt)
                pos_query = (
                    f"SELECT ts, payload, symbol, exchange, bot_id FROM position_events {pos_where}"
                    f"ORDER BY ts DESC LIMIT ${len(pos_params)+1}"
                )
                pos_params.append(min(window_limit, 1500))
                pos_rows, _ = await _fetch_timescale_rows_timeboxed(
                    pos_query,
                    *pos_params,
                    timeout_sec=trade_history_timeout_sec,
                )
                if not pos_rows:
                    pos_rows, _ = await _fetch_timescale_rows_direct_timeboxed(
                        pos_query,
                        *pos_params,
                        timeout_sec=min(2.5, trade_history_timeout_sec),
                    )
                pos_events = [_merge_ts_payload(row) for row in pos_rows]
                close_reason_allow = {
                    "position_close",
                    "strategic_exit",
                    "stop_loss",
                    "take_profit",
                    "exchange_reconcile",
                    "exchange_backfill",
                }
                filtered_events: list[dict[str, Any]] = []
                for evt in pos_events:
                    event_type = str(evt.get("event_type") or "").strip().lower()
                    position_effect = str(evt.get("position_effect") or "").strip().lower()
                    reason = str(evt.get("reason") or "").strip().lower()
                    status_val = str(evt.get("status") or "").strip().lower()
                    if (
                        event_type == "closed"
                        or position_effect == "close"
                        or status_val == "closed"
                        or reason in close_reason_allow
                    ):
                        filtered_events.append(evt)
                events = filtered_events
                used_position_fallback = bool(events)
            if query_timed_out and not events:
                lifecycle_where = "WHERE tenant_id=$1 AND bot_id=$2 "
                lifecycle_params: list[Any] = [tenant_id, bot_id]
                if status_filter:
                    lifecycle_where += f"AND LOWER(status) = ANY(${len(lifecycle_params)+1}::text[]) "
                    lifecycle_params.append(status_filter)
                if symbol:
                    lifecycle_where += f"AND symbol=${len(lifecycle_params)+1} "
                    lifecycle_params.append(symbol)
                if start_dt:
                    lifecycle_where += f"AND created_at >= ${len(lifecycle_params)+1} "
                    lifecycle_params.append(start_dt)
                if end_dt:
                    lifecycle_where += f"AND created_at <= ${len(lifecycle_params)+1} "
                    lifecycle_params.append(end_dt)
                lifecycle_query = (
                    "SELECT created_at AS ts, "
                    "jsonb_strip_nulls(jsonb_build_object("
                    "'tenant_id', tenant_id, "
                    "'bot_id', bot_id, "
                    "'exchange', exchange, "
                    "'symbol', symbol, "
                    "'side', side, "
                    "'size', size, "
                    "'status', status, "
                    "'event_type', event_type, "
                    "'order_id', order_id, "
                    "'client_order_id', client_order_id, "
                    "'reason', reason, "
                    "'fill_price', fill_price, "
                    "'fee_usd', fee_usd, "
                    "'filled_size', filled_size, "
                    "'remaining_size', remaining_size, "
                    "'state_source', state_source, "
                    "'raw_exchange_status', raw_exchange_status, "
                    "'position_effect', CASE "
                    "  WHEN lower(coalesce(event_type, '')) IN ('closed', 'close') THEN 'close' "
                    "  WHEN lower(coalesce(status, '')) IN ('closed', 'filled') "
                    "   AND lower(coalesce(event_type, '')) IN ('close', 'take_profit_hit', 'stop_loss_hit') THEN 'close' "
                    "  ELSE NULL END, "
                    "'ts', created_at"
                    ")) AS payload, "
                    "symbol, exchange, bot_id "
                    f"FROM order_lifecycle_events {lifecycle_where}"
                    f"ORDER BY created_at DESC LIMIT ${len(lifecycle_params)+1}"
                )
                lifecycle_params.append(min(window_limit, 1500))
                lifecycle_rows, lifecycle_timed_out = await _fetch_timescale_rows_direct_timeboxed(
                    lifecycle_query,
                    *lifecycle_params,
                    timeout_sec=min(4.0, trade_history_timeout_sec + 1.0),
                )
                if lifecycle_rows:
                    events = [_merge_ts_payload(row) for row in lifecycle_rows]
                    query_timed_out = query_timed_out and lifecycle_timed_out
        except Exception:
            return {"trades": [], "totalCount": 0, "_warning": "timescale_unavailable"}
        upstream_event_count = len(events)

        if used_position_fallback:
            normalized_fallback_events: list[dict[str, Any]] = []
            for evt in events:
                normalized = dict(evt)
                event_type = str(normalized.get("event_type") or "").strip().lower()
                if event_type == "closed":
                    normalized.setdefault("position_effect", "close")
                    normalized.setdefault("status", "closed")
                    if not normalized.get("reason"):
                        normalized["reason"] = (
                            normalized.get("close_reason")
                            or normalized.get("exit_reason")
                            or "position_close"
                        )
                if not normalized.get("order_id") and normalized.get("close_order_id"):
                    normalized["order_id"] = normalized.get("close_order_id")
                normalized_fallback_events.append(normalized)
            events = normalized_fallback_events
        
        # Deduplicate by order_id with one canonical event per order.
        # close_only keeps history focused on close outcomes by default.
        deduped_events, best_pnl_by_order_id = _dedupe_order_events(
            events,
            close_only=(not showEntries and not includeAll),
        )
        if not showEntries and not includeAll:
            def _has_explicit_entry_exit(evt: dict[str, Any]) -> bool:
                return (
                    (evt.get("entry_price") is not None and evt.get("exit_price") is not None)
                    or (evt.get("entryPrice") is not None and evt.get("exitPrice") is not None)
                )

            def _has_realized_close_pnl(evt: dict[str, Any]) -> bool:
                pnl_val = (
                    evt.get("net_pnl")
                    if evt.get("net_pnl") is not None
                    else evt.get("realized_pnl")
                    if evt.get("realized_pnl") is not None
                    else evt.get("gross_pnl")
                )
                if pnl_val is None:
                    return False
                # Keep exchange-reconciled close rows even when entry/exit prices are absent.
                # This prevents an empty trade-history after reconnect/reconcile flows.
                is_close_effect = str(evt.get("position_effect") or "").lower() == "close"
                reason = str(evt.get("reason") or "").lower()
                return is_close_effect or reason in {
                    "exchange_reconcile",
                    "exchange_backfill",
                    "position_close",
                    "strategic_exit",
                    "stop_loss",
                    "take_profit",
                }

            deduped_events = [
                evt
                for evt in deduped_events
                if _is_meaningful_trade_history_event(evt)
                and (
                    _has_explicit_entry_exit(evt)
                    or _has_realized_close_pnl(evt)
                    or str(evt.get("reason") or "").lower() not in {"exchange_reconcile", "exchange_backfill"}
                )
            ]

        # Keep entry/exit-rich rows, but borrow PnL/fees from best reconcile row for the same order.
        merged_events: list[dict[str, Any]] = []
        for evt in deduped_events:
            order_id = evt.get("order_id") or evt.get("client_order_id")
            pnl_evt = best_pnl_by_order_id.get(order_id) if order_id else None
            if pnl_evt and pnl_evt is not evt:
                merged = dict(evt)
                for key in (
                    "net_pnl",
                    "realized_pnl",
                    "gross_pnl",
                    "fee_usd",
                    "entry_fee_usd",
                    "total_fees_usd",
                    "fees",
                    # Preserve maker/taker metadata when the canonical row is selected
                    # for entry/exit completeness but liquidity lives on reconcile rows.
                    "liquidity",
                    "liquidity_type",
                    "maker_taker",
                    "is_maker",
                ):
                    if pnl_evt.get(key) is not None:
                        merged[key] = pnl_evt.get(key)
                merged_events.append(merged)
            else:
                merged_events.append(evt)

        # Enrich with position lifecycle close metadata (true position side + entry/exit timestamps).
        order_ids: list[str] = []
        seen_ids: set[str] = set()
        for evt in merged_events:
            oid = str(evt.get("order_id") or evt.get("client_order_id") or "").strip()
            if oid and oid not in seen_ids:
                seen_ids.add(oid)
                order_ids.append(oid)
        pos_query_timed_out = False
        if order_ids:
            try:
                # Cap enrichment joins to keep page latency bounded.
                join_order_ids = order_ids[:2000]
                pos_query = (
                    "SELECT ts, payload FROM position_events "
                    "WHERE tenant_id=$1 AND bot_id=$2 "
                    "AND payload->>'event_type'='closed' "
                    "AND payload->>'close_order_id' = ANY($3::text[]) "
                    "ORDER BY ts DESC",
                )
                pos_rows, pos_query_timed_out = await _fetch_timescale_rows_timeboxed(
                    pos_query,
                    tenant_id,
                    bot_id,
                    join_order_ids,
                    timeout_sec=1.5,
                )
                close_meta_by_order: dict[str, dict[str, Any]] = {}
                for row in pos_rows:
                    payload = row.get("payload") if isinstance(row, dict) else row["payload"]
                    if isinstance(payload, str):
                        try:
                            payload = json.loads(payload)
                        except Exception:
                            payload = {}
                    meta = dict(payload or {})
                    close_oid = str(meta.get("close_order_id") or "").strip()
                    if close_oid and close_oid not in close_meta_by_order:
                        close_meta_by_order[close_oid] = meta
                if close_meta_by_order:
                    enriched_events: list[dict[str, Any]] = []
                    for evt in merged_events:
                        oid = str(evt.get("order_id") or evt.get("client_order_id") or "").strip()
                        meta = close_meta_by_order.get(oid)
                        if not meta:
                            enriched_events.append(evt)
                            continue
                        merged = dict(evt)
                        # Prefer lifecycle-close semantics for trade-history rows.
                        for key in (
                            "side",
                            "entry_price",
                            "exit_price",
                            "entry_timestamp",
                            "exit_timestamp",
                            "hold_time_sec",
                            "realized_pnl_pct",
                            "closed_by",
                            "close_reason",
                            "exit_reason",
                        ):
                            if meta.get(key) is not None:
                                merged[key] = meta.get(key)
                        meta_close_reason = str(meta.get("close_reason") or meta.get("exit_reason") or "").strip()
                        merged_reason = str(merged.get("reason") or "").strip().lower()
                        if meta_close_reason and merged_reason in {"position_close", "exchange_reconcile", "exchange_backfill"}:
                            merged["reason"] = meta_close_reason
                        enriched_events.append(merged)
                    merged_events = enriched_events
            except Exception:
                pass
        trades = [_normalize_trade_event(e) for e in merged_events]

        # Liquidity backfill: canonical close rows can miss maker/taker even when
        # sibling order events for the same order_id contain it.
        liquidity_hints: dict[str, tuple[int, int, Optional[str], Optional[float]]] = {}
        for evt in events:
            hint_order_id = str(evt.get("order_id") or evt.get("client_order_id") or "").strip()
            if not hint_order_id:
                continue
            normalized_hint = _normalize_trade_event(evt)
            hint_liquidity = normalized_hint.get("liquidity")
            hint_maker_percent = normalized_hint.get("makerPercent")
            if hint_liquidity is None and hint_maker_percent is None:
                continue
            has_explicit_liquidity = any(
                evt.get(k) is not None for k in ("liquidity", "liquidity_type", "maker_taker", "is_maker")
            )
            inferred_by_order_type = str(evt.get("order_type") or "").strip().lower() == "market"
            inferred_by_post_only = isinstance(evt.get("post_only"), bool) or isinstance(evt.get("entry_post_only"), bool)
            hint_rank = 2 if has_explicit_liquidity else 1 if (inferred_by_order_type or inferred_by_post_only) else 0
            hint_ts = int(_to_epoch_ms(evt.get("ts")) or 0)
            prev = liquidity_hints.get(hint_order_id)
            if prev is None or (hint_rank, hint_ts) > (prev[0], prev[1]):
                liquidity_hints[hint_order_id] = (hint_rank, hint_ts, hint_liquidity, hint_maker_percent)

        for trade_row in trades:
            if trade_row.get("liquidity") is not None and trade_row.get("makerPercent") is not None:
                continue
            trade_order_id = str(trade_row.get("id") or "").strip()
            if not trade_order_id:
                continue
            hint = liquidity_hints.get(trade_order_id)
            if not hint:
                continue
            if trade_row.get("liquidity") is None and hint[2] is not None:
                trade_row["liquidity"] = hint[2]
            if trade_row.get("makerPercent") is None and hint[3] is not None:
                trade_row["makerPercent"] = hint[3]

        # Trade history should show completed trade rows (entry/exit/PnL), not raw buy/sell legs.
        if not showEntries and not includeAll:
            def _is_realized_close_trade(row: dict[str, Any]) -> bool:
                has_prices = row.get("entry_price") is not None and row.get("exit_price") is not None
                if has_prices:
                    return True
                pnl_val = (
                    row.get("net_pnl")
                    if row.get("net_pnl") is not None
                    else row.get("pnl")
                    if row.get("pnl") is not None
                    else row.get("gross_pnl")
                )
                reason = str(row.get("reason") or "").lower()
                position_effect = str(row.get("position_effect") or "").lower()
                status = str(row.get("status") or "").lower()
                is_close_semantic = (
                    position_effect == "close"
                    or status == "closed"
                    or reason in {
                    "exchange_reconcile",
                    "exchange_backfill",
                    "position_close",
                    "strategic_exit",
                    "stop_loss",
                    "take_profit",
                    }
                )
                if pnl_val is not None:
                    return is_close_semantic
                # Degraded-mode fallback (position_events closes) can omit PnL briefly; still render.
                return is_close_semantic

            trades = [
                t
                for t in trades
                if _is_realized_close_trade(t)
            ]
        # Re-sort by timestamp descending after deduplication
        trades.sort(key=lambda t: t.get("timestamp") or t.get("ts") or 0, reverse=True)
        
        # Apply additional filters that can't be done in SQL efficiently
        if side:
            side_lower = side.lower()
            side_aliases = {side_lower}
            if side_lower in {"buy", "long"}:
                side_aliases.update({"buy", "long"})
            if side_lower in {"sell", "short"}:
                side_aliases.update({"sell", "short"})
            trades = [t for t in trades if str(t.get("side", "")).lower() in side_aliases]
        if minPnl is not None:
            trades = [t for t in trades if _safe_float(t.get("pnl")) >= minPnl]
        if maxPnl is not None:
            trades = [t for t in trades if _safe_float(t.get("pnl")) <= maxPnl]
        
        total_count = len(trades)
        total = total_count
        paged = trades[offset : offset + limit]
        
        # Stats are computed from the current page - for full stats, client should fetch all
        # or use a dedicated /api/dashboard/trade-stats endpoint
        stats = _compute_trade_history_stats(trades)
        stats["totalDbCount"] = total_count  # Add total count from DB for display
        return {
            "trades": paged,
            "pagination": {
                "total": total,
                "limit": limit,
                "offset": offset,
                "hasMore": offset + limit < total,
            },
            "totalCount": total,
            "stats": stats,
            "filters": {
                "symbol": symbol,
                "side": side,
                "startDate": startDate,
                "endDate": endDate,
            },
            "updatedAt": int(time.time() * 1000),
            "_warning": (
                "trade_history_query_timed_out"
                if (query_timed_out or pos_query_timed_out) and total == 0 and upstream_event_count == 0
                else None
            ),
        }

    @app.get("/api/dashboard/trade-history/{trade_id}", response_model=dict, dependencies=[Depends(auth_dep)])
    async def dashboard_trade_history_detail(
        trade_id: str,
        tenant_id: str | None = None,
        bot_id: str | None = Query(default=None, alias="botId"),
        timescale=Depends(_timescale_reader),
    ):
        def _session_from_ts_ms(ts_ms: Optional[float]) -> Optional[str]:
            if not ts_ms:
                return None
            dt = datetime.fromtimestamp(float(ts_ms) / 1000.0, tz=timezone.utc)
            hour = dt.hour
            if 0 <= hour < 8:
                return "asia"
            if 8 <= hour < 16:
                return "europe"
            return "us"

        def _trace_outcome(result: Any) -> str:
            value = str(result or "").strip().upper()
            return "approved" if value in {"ACCEPTED", "COMPLETE", "ALLOW", "APPROVE"} else "rejected"

        def _stage_from_gate(gate: dict[str, Any]) -> dict[str, Any]:
            reasons = gate.get("reasons")
            reason_text = ", ".join(str(r) for r in reasons if r) if isinstance(reasons, list) else None
            return {
                "name": str(gate.get("gate_name") or "unknown"),
                "inputs": {},
                "output": {
                    "score": None,
                    "pass": bool(gate.get("allowed")),
                    "reason": reason_text,
                },
                "latencyMs": 0.0,
                "features": gate.get("metrics") if isinstance(gate.get("metrics"), dict) else {},
            }

        tenant_id, bot_id = _resolve_scope(tenant_id, bot_id)
        rows = await timescale.pool.fetch(
            "SELECT ts, payload, symbol, exchange, bot_id FROM order_events "
            "WHERE tenant_id=$1 AND bot_id=$2 "
            "AND ((payload::jsonb->>'order_id')=$3 OR (payload::jsonb->>'client_order_id')=$3) "
            "ORDER BY ts DESC LIMIT 50",
            tenant_id,
            bot_id,
            trade_id,
        )
        event = {}
        if rows:
            candidates = [_merge_ts_payload(r) for r in rows]
            deduped_candidates, _ = _dedupe_order_events(candidates, close_only=False)
            event = deduped_candidates[0] if deduped_candidates else {}
        position_event: dict[str, Any] | None = None
        if event:
            try:
                pos_rows = await timescale.pool.fetch(
                    "SELECT ts, payload, symbol, exchange, bot_id FROM position_events "
                    "WHERE tenant_id=$1 AND bot_id=$2 "
                    "AND payload->>'event_type'='closed' "
                    "AND payload->>'close_order_id'=$3 "
                    "ORDER BY ts DESC LIMIT 1",
                    tenant_id,
                    bot_id,
                    trade_id,
                )
                if pos_rows:
                    pos_event = _merge_ts_payload(pos_rows[0])
                    position_event = dict(pos_event)
                    merged = dict(event)
                    for key in (
                        "side",
                        "entry_price",
                        "exit_price",
                        "entry_timestamp",
                        "exit_timestamp",
                        "hold_time_sec",
                        "closed_by",
                        "close_reason",
                    ):
                        if pos_event.get(key) is not None:
                            merged[key] = pos_event.get(key)
                    event = merged
            except Exception:
                pass
        if not event:
            # Fallback to position_events (closed positions)
            pos_rows = await timescale.pool.fetch(
                "SELECT ts, payload, symbol, exchange, bot_id FROM position_events "
                "WHERE tenant_id=$1 AND bot_id=$2 "
                "AND ((payload::jsonb->>'close_order_id')=$3 OR (payload::jsonb->>'order_id')=$3) "
                "ORDER BY ts DESC LIMIT 1",
                tenant_id,
                bot_id,
                trade_id,
            )
            if pos_rows:
                payload = pos_rows[0].get("payload") if isinstance(pos_rows[0], dict) else pos_rows[0]["payload"]
                if isinstance(payload, str):
                    try:
                        payload = json.loads(payload)
                    except Exception:
                        payload = {}
                event = dict(payload or {})
                position_event = dict(event)
                event["ts"] = pos_rows[0].get("ts") if isinstance(pos_rows[0], dict) else pos_rows[0]["ts"]
                event["symbol"] = pos_rows[0].get("symbol") if isinstance(pos_rows[0], dict) else pos_rows[0]["symbol"]
                if event.get("close_order_id") and not event.get("order_id"):
                    event["order_id"] = event.get("close_order_id")
        trade = _normalize_trade_event(event) if event else {
            "id": trade_id,
            "symbol": "UNKNOWN",
            "side": "unknown",
            "entry_price": 0,
            "exit_price": 0,
            "size": 0,
            "pnl": 0,
            "fees": 0,
            "pnlPercent": None,
            "timestamp": int(time.time() * 1000),
            "formattedTimestamp": None,
            "holdingDuration": None,
            "exitReason": None,
            "decisionTrace": None,
        }
        symbol = str(event.get("symbol") or trade.get("symbol") or "")
        entry_ts_ms = _to_epoch_ms(event.get("entry_timestamp")) if event else None
        exit_ts_ms = _to_epoch_ms(event.get("exit_timestamp")) if event else None
        event_ts_ms = _to_epoch_ms(event.get("ts")) if event else None
        if entry_ts_ms is None:
            entry_ts_ms = trade.get("entryTime")
        if exit_ts_ms is None:
            exit_ts_ms = trade.get("exitTime")
        if event_ts_ms is None:
            event_ts_ms = trade.get("timestamp")

        # Enrich fills for both entry and exit legs.
        fills: list[dict[str, Any]] = []
        try:
            window_start_ms = int((entry_ts_ms or event_ts_ms or int(time.time() * 1000)) - 30_000)
            window_end_ms = int((exit_ts_ms or event_ts_ms or int(time.time() * 1000)) + 30_000)
            if window_end_ms < window_start_ms:
                window_end_ms = window_start_ms + 60_000
            fill_rows = await timescale.pool.fetch(
                "SELECT ts, payload, symbol, exchange, bot_id FROM order_events "
                "WHERE tenant_id=$1 AND bot_id=$2 AND symbol=$3 "
                "AND ts >= to_timestamp($4::double precision / 1000.0) "
                "AND ts <= to_timestamp($5::double precision / 1000.0) "
                "AND lower(coalesce(payload->>'status','')) IN ('filled','closed') "
                "ORDER BY ts ASC LIMIT 300",
                tenant_id,
                bot_id,
                symbol,
                float(window_start_ms),
                float(window_end_ms),
            )
            fills_seen: set[tuple[str, float, float]] = set()
            for r in fill_rows:
                merged = _merge_ts_payload(r)
                fill_ts_ms = _to_epoch_ms(merged.get("ts"))
                if fill_ts_ms is None:
                    continue
                order_id = str(merged.get("order_id") or "")
                client_order_id = str(merged.get("client_order_id") or "")
                include = (order_id == trade_id) or (client_order_id == trade_id)
                if not include and entry_ts_ms and exit_ts_ms:
                    include = (entry_ts_ms - 10_000) <= fill_ts_ms <= (exit_ts_ms + 10_000)
                if not include:
                    continue
                qty = _safe_float(merged.get("filled_size"), _safe_float(merged.get("size"), 0.0))
                price = _safe_float(
                    merged.get("fill_price"),
                    _safe_float(merged.get("entry_price"), _safe_float(merged.get("exit_price"), 0.0)),
                )
                key = (order_id or client_order_id or "na", round(qty, 8), round(price, 8))
                if key in fills_seen:
                    continue
                fills_seen.add(key)
                liquidity_raw = str(
                    merged.get("liquidity")
                    or merged.get("liquidity_type")
                    or merged.get("maker_taker")
                    or "taker"
                ).lower()
                liquidity_known = any(
                    merged.get(k) is not None for k in ("liquidity", "liquidity_type", "maker_taker", "is_maker")
                )
                if merged.get("is_maker") is True:
                    liquidity_raw = "maker"
                    liquidity_known = True
                elif merged.get("is_maker") is False:
                    liquidity_raw = "taker"
                    liquidity_known = True
                liquidity = "maker" if "maker" in liquidity_raw else "taker"
                fills.append(
                    {
                        "id": f"{order_id or client_order_id or trade_id}:{int(fill_ts_ms)}:{len(fills)}",
                        "timestamp": int(fill_ts_ms),
                        "venueOrderId": order_id or None,
                        "quantity": qty,
                        "price": price,
                        "fee": _safe_float(merged.get("fee_usd"), _safe_float(merged.get("total_fees_usd"), 0.0)),
                        "liquidity": liquidity,
                        "liquidityRole": liquidity,
                        "_liquidityKnown": bool(liquidity_known),
                        "slippageBps": _safe_float(merged.get("slippage_bps"), None),
                        "positionEffect": str(merged.get("position_effect") or "").lower() or None,
                    }
                )
        except Exception:
            fills = []

        # If we only captured close-leg fills, try to pull the most recent open-leg fill
        # for the same symbol near the trade window so round-trip fees are represented.
        try:
            has_open_leg = any(str(f.get("positionEffect", "")).lower() == "open" for f in fills)
            if (not has_open_leg) and entry_ts_ms is not None:
                entry_row = await timescale.pool.fetchrow(
                    "SELECT ts, payload, symbol, exchange, bot_id FROM order_events "
                    "WHERE tenant_id=$1 AND bot_id=$2 "
                    "AND lower(coalesce(payload->>'status','')) IN ('filled','closed') "
                    "AND lower(coalesce(payload->>'position_effect',''))='open' "
                    "AND coalesce(payload->>'order_id','') <> $3 "
                    "AND ts >= to_timestamp($4::double precision / 1000.0) "
                    "AND ts <= to_timestamp($5::double precision / 1000.0) "
                    "ORDER BY abs((extract(epoch FROM ts) * 1000.0) - $6::double precision) ASC "
                    "LIMIT 1",
                    tenant_id,
                    bot_id,
                    trade_id,
                    float(entry_ts_ms - 300_000),
                    float(entry_ts_ms + 300_000),
                    float(entry_ts_ms),
                )
                if entry_row:
                    merged = _merge_ts_payload(entry_row)
                    entry_fill_ts_ms = _to_epoch_ms(merged.get("ts"))
                    if entry_fill_ts_ms is not None:
                        entry_qty = _safe_float(merged.get("filled_size"), _safe_float(merged.get("size"), 0.0))
                        entry_price = _safe_float(
                            merged.get("fill_price"),
                            _safe_float(merged.get("entry_price"), _safe_float(merged.get("exit_price"), 0.0)),
                        )
                        entry_order_id = str(merged.get("order_id") or merged.get("client_order_id") or "")
                        entry_key = (entry_order_id or "na", round(entry_qty, 8), round(entry_price, 8))
                        if entry_key not in fills_seen:
                            fills_seen.add(entry_key)
                            fills.append(
                                {
                                    "id": f"{entry_order_id or trade_id}:{int(entry_fill_ts_ms)}:entry",
                                    "timestamp": int(entry_fill_ts_ms),
                                    "venueOrderId": entry_order_id or None,
                                    "quantity": entry_qty,
                                    "price": entry_price,
                                    "fee": _safe_float(merged.get("fee_usd"), _safe_float(merged.get("total_fees_usd"), 0.0)),
                                    "liquidity": "maker"
                                    if str(merged.get("liquidity") or merged.get("maker_taker") or "").lower().find("maker") >= 0
                                    else "taker",
                                    "liquidityRole": "maker"
                                    if str(merged.get("liquidity") or merged.get("maker_taker") or "").lower().find("maker") >= 0
                                    else "taker",
                                    "_liquidityKnown": any(
                                        merged.get(k) is not None
                                        for k in ("liquidity", "liquidity_type", "maker_taker", "is_maker")
                                    ),
                                    "slippageBps": _safe_float(merged.get("slippage_bps"), None),
                                    "positionEffect": "open",
                                }
                            )
        except Exception:
            pass
        fills.sort(key=lambda f: f.get("timestamp") or 0)
        if not fills:
            # Keep a minimal fill row so Fills tab has concrete data for closed trades.
            fallback_ts = int(exit_ts_ms or entry_ts_ms or event_ts_ms or int(time.time() * 1000))
            fills = [{
                "id": f"{trade_id}:{fallback_ts}:fallback",
                "timestamp": fallback_ts,
                "venueOrderId": trade_id,
                "quantity": _safe_float(trade.get("size"), 0.0),
                "price": _safe_float(trade.get("exit_price"), _safe_float(trade.get("entry_price"), 0.0)),
                "fee": _safe_float(trade.get("fees"), 0.0),
                "liquidity": "taker",
                "liquidityRole": "taker",
                "_liquidityKnown": False,
                "slippageBps": _safe_float(trade.get("slippageBps"), None),
            }]

        # Backfill entry/exit timestamps from observed fills when lifecycle timestamps are missing.
        fill_ts_values = [int(f.get("timestamp")) for f in fills if isinstance(f.get("timestamp"), (int, float))]
        if fill_ts_values:
            if entry_ts_ms is None:
                entry_ts_ms = float(min(fill_ts_values))
            if exit_ts_ms is None:
                exit_ts_ms = float(max(fill_ts_values))

        # Pick the nearest decision event around entry to populate trace + market context.
        decision_trace: dict[str, Any] | None = None
        market_context: dict[str, Any] | None = None
        try:
            decision_center_ms = int(entry_ts_ms or event_ts_ms or int(time.time() * 1000))
            decision_rows = await timescale.pool.fetch(
                "SELECT ts, payload, symbol FROM decision_events "
                "WHERE tenant_id=$1 AND bot_id=$2 "
                "AND ts >= to_timestamp($3::double precision / 1000.0) "
                "AND ts <= to_timestamp($4::double precision / 1000.0) "
                "ORDER BY ts DESC LIMIT 350",
                tenant_id,
                bot_id,
                float(decision_center_ms - 180_000),
                float(decision_center_ms + 180_000),
            )
            best_decision: dict[str, Any] | None = None
            best_score: tuple[int, int, float] | None = None
            for row in decision_rows:
                payload = row["payload"]
                if isinstance(payload, str):
                    try:
                        payload = json.loads(payload)
                    except Exception:
                        payload = {}
                if not isinstance(payload, dict):
                    continue
                row_symbol = str(row.get("symbol") or "").upper()
                payload_symbol = str(
                    payload.get("symbol")
                    or (payload.get("snapshot") or {}).get("symbol")
                    or ""
                ).upper()
                has_symbol_hint = bool(row_symbol or payload_symbol)
                symbol_match = int((not symbol) or (row_symbol == symbol.upper()) or (payload_symbol == symbol.upper()))
                # Only reject when symbol hint exists and mismatches target symbol.
                if symbol and has_symbol_hint and symbol_match == 0:
                    continue
                ts_ms = _to_epoch_ms(row["ts"]) or 0.0
                result = str(payload.get("result") or "").upper()
                approved = int(result in {"ACCEPTED", "COMPLETE", "ALLOW", "APPROVE"})
                gate_count = len(payload.get("gate_decisions") or []) if isinstance(payload.get("gate_decisions"), list) else 0
                has_snapshot = int(isinstance(payload.get("snapshot"), dict))
                richness = int(gate_count > 0) + has_snapshot
                # For executed trades, strongly prefer approved/completed and richer traces near entry.
                score = (approved, richness, symbol_match, -abs(ts_ms - decision_center_ms))
                if best_score is None or score > best_score:
                    best_score = score
                    best_decision = {"payload": payload, "ts_ms": ts_ms}
            if best_decision:
                payload = best_decision["payload"]
                # For executed trades, avoid attaching a nearby rejected/no-signal decision
                # as if it caused the trade. If we cannot confidently find an approved
                # decision trace, return no decisionTrace rather than a misleading one.
                trade_status = str(trade.get("status") or "").strip().lower()
                trade_effect = str(trade.get("position_effect") or "").strip().lower()
                is_executed_trade = trade_status in {"filled", "closed"} or trade_effect == "close"
                result_text = str(payload.get("result") or "").strip().upper()
                if is_executed_trade and result_text not in {"ACCEPTED", "COMPLETE", "ALLOW", "APPROVE"}:
                    best_decision = None
                    payload = {}
            if best_decision:
                payload = best_decision["payload"]
                gate_decisions = payload.get("gate_decisions") if isinstance(payload.get("gate_decisions"), list) else []
                stages = [_stage_from_gate(g) for g in gate_decisions if isinstance(g, dict)]
                # Include strategy attempts as a compact stage when gate_decisions are sparse.
                rejection_detail = payload.get("rejection_detail") if isinstance(payload.get("rejection_detail"), dict) else {}
                attempts = rejection_detail.get("strategy_attempts") if isinstance(rejection_detail.get("strategy_attempts"), list) else []
                if attempts:
                    stages.append({
                        "name": "strategy_selection",
                        "inputs": {},
                        "output": {
                            "score": None,
                            "pass": _trace_outcome(payload.get("result")) == "approved",
                            "reason": str(payload.get("rejection_reason") or "") or None,
                        },
                        "latencyMs": 0.0,
                        "features": {"attempts": attempts},
                    })
                trace_ts = int(best_decision["ts_ms"] or decision_center_ms)
                result = payload.get("result")
                decision_trace = {
                    "id": str(payload.get("decision_id") or f"{trade_id}:{trace_ts}"),
                    "tradeId": trade_id,
                    "timestamp": trace_ts,
                    "symbol": symbol,
                    "stages": stages,
                    "totalLatencyMs": _safe_float(payload.get("latency_ms"), 0.0),
                    "outcome": _trace_outcome(result),
                    "finalScore": _safe_float(payload.get("expected_bps"), None),
                    "primaryReason": str(payload.get("rejection_reason") or payload.get("rejected_by") or "") or None,
                }
                snapshot = payload.get("snapshot") if isinstance(payload.get("snapshot"), dict) else {}
                metrics = payload.get("metrics") if isinstance(payload.get("metrics"), dict) else {}
                vol_regime = str(snapshot.get("vol_regime") or "").lower()
                trend_direction = str(snapshot.get("trend_direction") or "").lower()
                regime = None
                volatility = None
                if vol_regime in {"high", "extreme"}:
                    regime = "volatile"
                    volatility = "high"
                elif vol_regime in {"low", "quiet"}:
                    regime = "quiet"
                    volatility = "low"
                elif vol_regime:
                    regime = "ranging"
                    volatility = "medium"
                trend = "neutral"
                if trend_direction in {"up", "bull", "bullish"}:
                    trend = "bullish"
                elif trend_direction in {"down", "bear", "bearish"}:
                    trend = "bearish"
                market_context = {
                    "regime": regime,
                    "trend": trend,
                    "volatility": volatility,
                    "session": _session_from_ts_ms(entry_ts_ms or event_ts_ms),
                    "spread": _safe_float(snapshot.get("spread_bps"), _safe_float(metrics.get("spread_bps"), None)),
                    "volume24h": _safe_float(snapshot.get("volume_24h"), _safe_float(metrics.get("volume_24h"), None)),
                }
        except Exception:
            decision_trace = None
            market_context = None

        if market_context is None:
            market_context = {"session": _session_from_ts_ms(entry_ts_ms or event_ts_ms)}

        fills_count = len(fills)
        known_liquidity_fills = [f for f in fills if bool(f.get("_liquidityKnown"))]
        maker_count = sum(1 for f in known_liquidity_fills if str(f.get("liquidity", "")).lower() == "maker")
        maker_percent = (maker_count / len(known_liquidity_fills)) if known_liquidity_fills else None
        fill_latencies = [f.get("latency_ms") for f in fills if isinstance(f.get("latency_ms"), (int, float))]
        avg_latency_ms = (sum(float(v) for v in fill_latencies) / len(fill_latencies)) if fill_latencies else None
        fill_slippages = [float(f.get("slippageBps")) for f in fills if isinstance(f.get("slippageBps"), (int, float))]
        avg_slippage_bps = (sum(fill_slippages) / len(fill_slippages)) if fill_slippages else None
        hold_time_seconds = _safe_float(trade.get("hold_time_seconds"), None)
        if hold_time_seconds is None and entry_ts_ms is not None and exit_ts_ms is not None:
            hold_time_seconds = max(0.0, (float(exit_ts_ms) - float(entry_ts_ms)) / 1000.0)
        if avg_latency_ms is None and isinstance(decision_trace, dict):
            avg_latency_ms = _safe_float(decision_trace.get("totalLatencyMs"), None)
        gross_pnl_value = _safe_float(trade.get("gross_pnl"), None)
        effective_fees = _safe_float(trade.get("fees"), 0.0) or 0.0
        has_reported_fees = trade.get("fees") is not None
        observed_fill_fees = sum(
            _safe_float(f.get("fee"), 0.0) or 0.0
            for f in fills
        )
        if (not has_reported_fees) and observed_fill_fees > effective_fees + 1e-9:
            effective_fees = observed_fill_fees
        net_pnl_value = _safe_float(trade.get("net_pnl"), None)
        preserve_reported_net = net_pnl_value is not None
        if gross_pnl_value is not None and effective_fees is not None and not preserve_reported_net:
            recomputed_net = gross_pnl_value - effective_fees
            if net_pnl_value is None or abs(recomputed_net - net_pnl_value) > 1e-6:
                net_pnl_value = recomputed_net

        detail = {
            "id": trade.get("id"),
            "symbol": trade.get("symbol"),
            "side": trade.get("side"),
            "entryPrice": trade.get("entry_price"),
            "exitPrice": trade.get("exit_price"),
            "size": trade.get("size"),
            "quantity": trade.get("size"),
            "notional": (
                _safe_float(trade.get("size"), 0.0) * _safe_float(trade.get("entry_price"), 0.0)
                if trade.get("size") is not None and trade.get("entry_price") is not None
                else None
            ),
            "realizedPnl": gross_pnl_value,
            "netPnl": net_pnl_value,
            "fees": effective_fees,
            "pnl": gross_pnl_value,
            "pnlPercent": trade.get("pnlPercent"),
            "pnlBps": trade.get("realized_pnl_pct"),
            "timestamp": trade.get("timestamp"),
            "formattedTimestamp": trade.get("formattedTimestamp"),
            "entryTime": int(entry_ts_ms) if entry_ts_ms is not None else trade.get("entryTime"),
            "exitTime": int(exit_ts_ms) if exit_ts_ms is not None else trade.get("exitTime"),
            "holdTimeSeconds": hold_time_seconds,
            "slippageBps": (
                _safe_float(trade.get("slippageBps"), None)
                if _safe_float(trade.get("slippageBps"), None) is not None
                else avg_slippage_bps
            ),
            "latencyMs": avg_latency_ms,
            "makerPercent": maker_percent,
            "liquidity": trade.get("liquidity"),
            "liquidityRole": trade.get("liquidity_role") or trade.get("liquidity"),
            "fillsCount": fills_count,
            "decisionTraceId": decision_trace.get("id") if isinstance(decision_trace, dict) else None,
            "hasDecisionTrace": decision_trace is not None,
            "decisionOutcome": decision_trace.get("outcome") if isinstance(decision_trace, dict) else None,
            "decision": decision_trace,
            "exit": {"reason": trade.get("exitReason"), "details": None},
            "marketContext": market_context,
            "relatedTraces": [],
        }
        return {
            "trade": detail,
            "decisionTrace": decision_trace,
            "fills": fills,
            "marketContext": market_context,
            "updatedAt": int(time.time() * 1000),
        }

    @app.delete("/api/dashboard/clear-history", dependencies=[Depends(auth_dep)])
    async def dashboard_clear_history(
        tenant_id: str | None = None,
        bot_id: str | None = Query(default=None, alias="botId"),
        timescale=Depends(_timescale_reader),
        redis_client=Depends(_redis_client),
    ):
        """Clear order history for a bot (used to reset demo/test state)."""
        try:
            tenant_id, bot_id = _resolve_scope(tenant_id, bot_id, require_explicit=True)
        except Exception:
            return {"success": False, "error": "Invalid bot scope"}
        
        deleted_events = 0
        deleted_positions = 0
        cleared_redis = 0
        
        try:
            # Delete order events from TimescaleDB
            result = await timescale.pool.execute(
                "DELETE FROM order_events WHERE tenant_id=$1 AND bot_id=$2",
                tenant_id,
                bot_id,
            )
            deleted_events = int(result.split()[-1]) if result else 0
        except Exception as e:
            log_warning("clear_history_order_events_failed", error=str(e))
        
        try:
            # Delete position events from TimescaleDB
            result = await timescale.pool.execute(
                "DELETE FROM position_events WHERE tenant_id=$1 AND bot_id=$2",
                tenant_id,
                bot_id,
            )
            deleted_positions = int(result.split()[-1]) if result else 0
        except Exception as e:
            log_warning("clear_history_position_events_failed", error=str(e))
        
        try:
            # Clear Redis snapshots
            patterns = [
                f"quantgambit:{tenant_id}:{bot_id}:positions:*",
                f"quantgambit:{tenant_id}:{bot_id}:orders:*",
                f"quantgambit:{tenant_id}:{bot_id}:execution:*",
            ]
            for pattern in patterns:
                keys = await redis_client.keys(pattern)
                if keys:
                    await redis_client.delete(*keys)
                    cleared_redis += len(keys)
        except Exception as e:
            log_warning("clear_history_redis_failed", error=str(e))
        
        return {
            "success": True,
            "deleted_order_events": deleted_events,
            "deleted_position_events": deleted_positions,
            "cleared_redis_keys": cleared_redis,
            "message": f"Cleared {deleted_events} order events, {deleted_positions} position events, {cleared_redis} Redis keys",
        }

    @app.post("/api/dashboard/cancel-all-orders", response_model=BotControlResponse, dependencies=[Depends(auth_dep)])
    async def dashboard_cancel_all(
        request: BotControlRequest,
        redis_client=Depends(_redis_client),
    ):
        tenant_id, bot_id = _resolve_scope(request.tenant_id, request.bot_id, require_explicit=True)
        request.tenant_id = tenant_id
        request.bot_id = bot_id
        request.action = "halt"
        request.cancel_orders = True
        return await _publish_control_command(redis_client, "halt_bot", request, confirm_required=False)

    @app.post("/api/dashboard/close-all-positions", dependencies=[Depends(auth_dep)])
    async def dashboard_close_all(
        request: BotControlRequest,
        redis_client=Depends(_redis_client),
    ):
        """Close all positions directly via exchange API."""
        tenant_id, bot_id = _resolve_scope(request.tenant_id, request.bot_id, require_explicit=True)
        
        # Get positions from Redis snapshot
        reader = RedisSnapshotReader(redis_client)
        positions_key = f"quantgambit:{tenant_id}:{bot_id}:positions:latest"
        positions_snapshot = await reader.read(positions_key) or {}
        positions = positions_snapshot.get("positions") or []
        
        if not positions:
            return {"success": True, "closed": [], "count": 0, "message": "No positions to close"}

        def _position_scope_owned(position: dict[str, Any]) -> bool:
            """Require bot-local attribution before flattening account-level inventory."""
            ownership_fields = (
                "entry_client_order_id",
                "entry_decision_id",
                "prediction_source",
                "strategy_id",
                "profile_id",
            )
            for field in ownership_fields:
                value = position.get(field)
                if value is None:
                    continue
                if isinstance(value, str) and not value.strip():
                    continue
                return True
            return False
        
        # Get database pool
        platform = await _dashboard_pool()
        
        # Get bot config to find exchange account
        bot_row = await _fetch_row(
            platform,
            """
            SELECT
                exchange_account_id,
                environment,
                metadata
            FROM bot_exchange_configs
            WHERE bot_instance_id=$1
              AND is_active=true
            """,
            bot_id
        )
        if not bot_row or not bot_row.get("exchange_account_id"):
            return {"success": False, "error": "Bot config or exchange account not found"}
        
        exchange_account_id = bot_row["exchange_account_id"]
        cfg_metadata = _ensure_json(bot_row.get("metadata")) or {}
        market_type = str(
            cfg_metadata.get("market_type")
            or cfg_metadata.get("marketType")
            or "perp"
        ).strip().lower() or "perp"
        
        # Get exchange account details
        account_row = await _fetch_row(
            platform,
            "SELECT venue, is_demo, secret_id FROM exchange_accounts WHERE id=$1",
            exchange_account_id
        )
        if not account_row:
            return {"success": False, "error": "Exchange account not found"}
        
        exchange = (account_row.get("venue") or "").lower()
        is_demo = bool(account_row.get("is_demo", False))
        secret_id = account_row.get("secret_id")
        
        if not secret_id:
            return {"success": False, "error": "No credentials configured for exchange account"}
        
        # Load credentials
        try:
            from quantgambit.storage.secrets import SecretsProvider
            secrets = SecretsProvider()
            creds = secrets.get_credentials(secret_id)
            if not creds:
                return {"success": False, "error": "Could not load exchange credentials"}
        except Exception as e:
            return {"success": False, "error": f"Credential error: {str(e)}"}
        
        # Build exchange client
        try:
            import ccxt.async_support as ccxt
            
            exchange_class = getattr(ccxt, exchange, None)
            if not exchange_class:
                return {"success": False, "error": f"Unknown exchange: {exchange}"}
            
            config = {
                "apiKey": creds.api_key,
                "secret": creds.secret_key,
                "enableRateLimit": True,
                "options": {"defaultType": "spot" if market_type == "spot" else "swap"},
            }
            if creds.passphrase:
                config["password"] = creds.passphrase
            
            client = exchange_class(config)
            
            # Handle demo/testnet URLs
            # For Bybit: is_testnet=true with environment=live means "Demo Trading" (api-demo.bybit.com)
            # Real Bybit testnet would be api-testnet.bybit.com but we use demo for simulated live trading
            if exchange == "bybit":
                if is_demo:
                    # Bybit Demo Trading (not testnet)
                    # Demo doesn't support load_markets - preload from mainnet
                    prod_client = ccxt.bybit({"enableRateLimit": True, "options": {"defaultType": "spot" if market_type == "spot" else "swap"}})
                    await prod_client.load_markets()
                    
                    # Now set up demo client with preloaded markets
                    demo_url = "https://api-demo.bybit.com"
                    client.urls["api"] = {"public": demo_url, "private": demo_url}
                    client.hostname = "api-demo.bybit.com"
                    client.options["fetchCurrencies"] = False
                    client.markets = prod_client.markets
                    client.markets_by_id = prod_client.markets_by_id
                    client.currencies = prod_client.currencies
                    client.currencies_by_id = prod_client.currencies_by_id
                    await prod_client.close()
                else:
                    await client.load_markets()
            elif exchange == "okx" and is_demo:
                client.headers = {"x-simulated-trading": "1"}
                await client.load_markets()
            else:
                if is_demo:
                    client.set_sandbox_mode(True)
                await client.load_markets()
            
            async def _reconcile_ccxt_close(
                *,
                symbol: str,
                order_result: dict,
                fallback_fill_price: float,
                fallback_fee_usd: float,
            ) -> dict:
                order_id = str(order_result.get("id") or "")
                client_order_id = str(
                    order_result.get("clientOrderId")
                    or order_result.get("client_order_id")
                    or order_result.get("clientOrderID")
                    or ""
                )
                ts_ms_raw = order_result.get("timestamp")
                try:
                    ts_ms = int(float(ts_ms_raw)) if ts_ms_raw is not None else None
                except (TypeError, ValueError):
                    ts_ms = None
                since_ms = max((ts_ms or int(time.time() * 1000)) - 120_000, 0)

                try:
                    trades = await client.fetch_my_trades(symbol, since=since_ms, limit=200)
                except Exception as exc:
                    log_warning("dashboard_manual_close_fetch_trades_failed", symbol=symbol, order_id=order_id, error=str(exc))
                    trades = []

                matched = []
                for tr in trades or []:
                    tr_oid = str(tr.get("order") or tr.get("orderId") or "")
                    tr_coid = str(
                        tr.get("clientOrderId")
                        or (tr.get("info") or {}).get("clientOrderId")
                        or (tr.get("info") or {}).get("orderLinkId")
                        or ""
                    )
                    if order_id and tr_oid and tr_oid == order_id:
                        matched.append(tr)
                        continue
                    if client_order_id and tr_coid and tr_coid == client_order_id:
                        matched.append(tr)

                total_qty = 0.0
                total_price_qty = 0.0
                total_fees = 0.0
                latest_ts = None
                for tr in matched:
                    try:
                        qty = abs(float(tr.get("amount") or tr.get("qty") or 0.0))
                    except (TypeError, ValueError):
                        qty = 0.0
                    try:
                        px = float(tr.get("price") or 0.0)
                    except (TypeError, ValueError):
                        px = 0.0
                    fee_obj = tr.get("fee") or {}
                    try:
                        fee_cost = abs(float((fee_obj or {}).get("cost") or 0.0))
                    except (TypeError, ValueError):
                        fee_cost = 0.0
                    tr_ts = tr.get("timestamp")
                    if tr_ts is not None:
                        try:
                            tr_ts = float(tr_ts) / 1000.0 if float(tr_ts) > 1e12 else float(tr_ts)
                            if latest_ts is None or tr_ts > latest_ts:
                                latest_ts = tr_ts
                        except (TypeError, ValueError):
                            pass
                    total_qty += qty
                    if qty > 0 and px > 0:
                        total_price_qty += qty * px
                    total_fees += fee_cost

                if total_qty > 0 and total_price_qty > 0:
                    return {
                        "avg_price": total_price_qty / total_qty,
                        "total_qty": total_qty,
                        "total_fees_usd": total_fees,
                        "exit_timestamp": latest_ts or time.time(),
                        "trade_count": len(matched),
                        "reconciled": True,
                    }

                return {
                    "avg_price": fallback_fill_price,
                    "total_qty": 0.0,
                    "total_fees_usd": fallback_fee_usd,
                    "exit_timestamp": (ts_ms / 1000.0) if ts_ms else time.time(),
                    "trade_count": 0,
                    "reconciled": False,
                }

            closed = []
            for pos in positions:
                symbol = pos.get("symbol", "")
                side = pos.get("side", "").lower()
                size = abs(float(pos.get("size", 0)))
                opened_at = _safe_float(pos.get("opened_at"))
                scope_owned = _position_scope_owned(pos)
                
                if size <= 0:
                    continue

                if not scope_owned:
                    closed.append({
                        "symbol": symbol,
                        "side": side,
                        "size": size,
                        "success": False,
                        "error": "position_scope_ambiguous",
                        "scope_owned": False,
                    })
                    continue
                
                # Spot positions are flattened by selling the held asset.
                # Derivatives positions need the opposite side with reduce-only semantics.
                is_spot = market_type == "spot"
                if is_spot and side not in {"", "long"}:
                    closed.append({
                        "symbol": symbol,
                        "side": "sell",
                        "size": size,
                        "success": False,
                        "error": f"unsupported_spot_position_side:{side}",
                    })
                    continue

                close_side = "sell" if is_spot or side == "long" else "buy"

                # Normalize symbol for exchange using the canonical adapter helper.
                ccxt_symbol = to_ccxt_market_symbol(exchange, symbol, market_type="spot" if is_spot else "perp") or symbol
                
                try:
                    order_params = {} if is_spot else {"reduceOnly": True}
                    result = await client.create_order(
                        symbol=ccxt_symbol,
                        type="market",
                        side=close_side,
                        amount=size,
                        params=order_params,
                    )
                    
                    # Reconcile with exchange executions to get authoritative avg fill + fees.
                    entry_price = float(pos.get("entry_price", 0))
                    fallback_fill_price = float(result.get("average") or result.get("price") or 0)
                    fee = result.get("fee", {})
                    fallback_fee_usd = float(fee.get("cost", 0)) if isinstance(fee, dict) else 0.0
                    reconciled = await _reconcile_ccxt_close(
                        symbol=ccxt_symbol,
                        order_result=result or {},
                        fallback_fill_price=fallback_fill_price,
                        fallback_fee_usd=fallback_fee_usd,
                    )

                    fill_price = float(reconciled.get("avg_price") or fallback_fill_price or 0.0)
                    filled_size = float(reconciled.get("total_qty") or size)
                    fee_usd = float(reconciled.get("total_fees_usd") or fallback_fee_usd or 0.0)
                    exit_ts = float(reconciled.get("exit_timestamp") or time.time())

                    gross_pnl = 0.0
                    if entry_price and fill_price:
                        if side == "long":
                            gross_pnl = (fill_price - entry_price) * filled_size
                        else:  # short
                            gross_pnl = (entry_price - fill_price) * filled_size

                    net_pnl = gross_pnl - fee_usd
                    
                    closed.append({
                        "symbol": symbol,
                        "side": close_side,
                        "original_side": side,  # The position side (long/short)
                        "size": filled_size,
                        "success": True,
                        "scope_owned": True,
                        "order_id": result.get("id"),
                        "client_order_id": result.get("clientOrderId") or result.get("client_order_id"),
                        "entry_price": entry_price,
                        "fill_price": fill_price,
                        "entry_timestamp": opened_at,
                        "exit_timestamp": exit_ts,
                        "hold_time_sec": (exit_ts - opened_at) if opened_at else None,
                        "realized_pnl": net_pnl,
                        "gross_pnl": gross_pnl,
                        "net_pnl": net_pnl,
                        "fee_usd": fee_usd,
                        "total_fees_usd": fee_usd,
                        "filled_size": filled_size,
                        "trade_count": int(reconciled.get("trade_count") or 0),
                        "reconciled": bool(reconciled.get("reconciled")),
                    })
                except Exception as e:
                    closed.append({
                        "symbol": symbol,
                        "side": close_side,
                        "size": size,
                        "success": False,
                        "scope_owned": True,
                        "error": str(e),
                    })
            
            await client.close()
            
            success_count = sum(1 for c in closed if c.get("success"))
            total_pnl = sum(c.get("net_pnl", c.get("realized_pnl", 0)) for c in closed if c.get("success"))
            total_fees = sum(c.get("total_fees_usd", c.get("fee_usd", 0)) for c in closed if c.get("success"))
            ambiguous_count = sum(1 for c in closed if c.get("error") == "position_scope_ambiguous")
            
            # Update local state after closing on exchange
            if success_count > 0:
                try:
                    # Clear Redis positions snapshot (show 0 open positions)
                    await redis_client.set(positions_key, '{"positions":[],"count":0}')
                except Exception:
                    pass
                
                # Record position closes in TimescaleDB (preserve history, don't delete)
                # Use the new position lifecycle event format (event_type: "closed")
                try:
                    timescale_url = os.getenv("BOT_TIMESCALE_URL") or _build_timescale_url()
                    import asyncpg
                    ts_conn = await asyncpg.connect(timescale_url)
                    
                    # Record each close with exchange-authoritative fields.
                    for c in closed:
                        if c.get("success"):
                            close_ts = _safe_float(c.get("exit_timestamp")) or time.time()
                            # position_events lifecycle row
                            payload = {
                                "event_type": "closed",  # Consistent with Guardian and normal trading flow
                                "symbol": c.get("symbol"),
                                "side": c.get("original_side"),  # Original position side
                                "size": c.get("size"),
                                "status": "closed",
                                "entry_price": c.get("entry_price"),
                                "exit_price": c.get("fill_price"),
                                "exit_timestamp": close_ts,
                                "realized_pnl": c.get("net_pnl", c.get("realized_pnl", 0)),
                                "realized_pnl_pct": None,  # Not calculated here
                                "fee_usd": c.get("fee_usd", 0),
                                "total_fees_usd": c.get("total_fees_usd", c.get("fee_usd", 0)),
                                "gross_pnl": c.get("gross_pnl"),
                                "net_pnl": c.get("net_pnl"),
                                "hold_time_sec": c.get("hold_time_sec"),
                                "closed_by": "dashboard_flatten_all",
                                "close_order_id": c.get("order_id"),
                                "close_client_order_id": c.get("client_order_id"),
                                "exchange_reconciled": c.get("reconciled", False),
                                "exchange_trade_count": c.get("trade_count", 0),
                            }
                            await ts_conn.execute(
                                "INSERT INTO position_events (tenant_id, bot_id, symbol, exchange, ts, payload) VALUES ($1, $2, $3, $4, NOW(), $5)",
                                tenant_id, bot_id, c.get("symbol"), exchange, json.dumps(payload)
                            )

                            # order_events row for trade history/pnl aggregation parity
                            order_payload = {
                                "tenant_id": tenant_id,
                                "bot_id": bot_id,
                                "symbol": c.get("symbol"),
                                "side": c.get("side"),
                                "size": c.get("size"),
                                "filled_size": c.get("filled_size", c.get("size")),
                                "status": "filled",
                                "reason": "position_close",
                                "position_effect": "close",
                                "entry_price": c.get("entry_price"),
                                "exit_price": c.get("fill_price"),
                                "fill_price": c.get("fill_price"),
                                "realized_pnl": c.get("net_pnl", c.get("realized_pnl", 0)),
                                "realized_pnl_pct": None,
                                "gross_pnl": c.get("gross_pnl"),
                                "net_pnl": c.get("net_pnl"),
                                "fee_usd": c.get("fee_usd", 0),
                                "total_fees_usd": c.get("total_fees_usd", c.get("fee_usd", 0)),
                                "order_id": c.get("order_id"),
                                "client_order_id": c.get("client_order_id"),
                                "entry_timestamp": c.get("entry_timestamp"),
                                "exit_timestamp": close_ts,
                                "hold_time_sec": c.get("hold_time_sec"),
                                "source": "dashboard_manual_close",
                                "exchange_reconciled": c.get("reconciled", False),
                                "exchange_trade_count": c.get("trade_count", 0),
                            }
                            semantic_key = (
                                "ord|"
                                + "|".join(
                                    [
                                        str(order_payload.get("order_id") or ""),
                                        str(order_payload.get("client_order_id") or ""),
                                        str(order_payload.get("status") or ""),
                                        str(order_payload.get("event_type") or ""),
                                        str(order_payload.get("reason") or ""),
                                        str(order_payload.get("filled_size") or ""),
                                        str(order_payload.get("remaining_size") or ""),
                                        str(order_payload.get("fill_price") or ""),
                                        str(order_payload.get("fee_usd") or ""),
                                    ]
                                )
                            )
                            if semantic_key == "ord|||||||||":
                                raw_key = json.dumps(order_payload, separators=(",", ":"), sort_keys=True, default=str)
                                semantic_key = "raw:" + hashlib.sha256(
                                    f"{raw_key}|{close_ts}".encode("utf-8")
                                ).hexdigest()[:24]
                            await ts_conn.execute(
                                """
                                WITH incoming AS (
                                    SELECT $6::jsonb AS payload
                                )
                                INSERT INTO order_events (
                                    tenant_id, bot_id, symbol, exchange, ts,
                                    order_id, client_order_id, event_type, status, reason,
                                    fill_price, filled_size, fee_usd,
                                    payload, semantic_key
                                )
                                SELECT
                                    $1, $2, $3, $4, TO_TIMESTAMP($5),
                                    nullif(trim(coalesce(incoming.payload->>'order_id', '')), ''),
                                    nullif(trim(coalesce(incoming.payload->>'client_order_id', '')), ''),
                                    nullif(trim(coalesce(incoming.payload->>'event_type', '')), ''),
                                    nullif(trim(coalesce(incoming.payload->>'status', '')), ''),
                                    nullif(trim(coalesce(incoming.payload->>'reason', '')), ''),
                                    NULLIF(incoming.payload->>'fill_price', '')::double precision,
                                    NULLIF(incoming.payload->>'filled_size', '')::double precision,
                                    NULLIF(incoming.payload->>'fee_usd', '')::double precision,
                                    incoming.payload, $7
                                FROM incoming
                                WHERE NOT EXISTS (
                                    SELECT 1
                                    FROM order_events oe
                                    WHERE oe.tenant_id = $1
                                      AND oe.bot_id = $2
                                      AND (
                                          oe.semantic_key = $7
                                          OR (
                                              oe.symbol IS NOT DISTINCT FROM $3
                                              AND oe.exchange = $4
                                              AND oe.ts = TO_TIMESTAMP($5)
                                              AND oe.payload = incoming.payload
                                          )
                                      )
                                )
                                """,
                                tenant_id,
                                bot_id,
                                c.get("symbol"),
                                exchange,
                                close_ts,
                                json.dumps(order_payload),
                                semantic_key,
                            )
                            # trade_costs row for TCA and EV/cost calibration parity
                            try:
                                entry_px = _safe_float(c.get("entry_price")) or 0.0
                                exit_px = _safe_float(c.get("fill_price")) or 0.0
                                filled_sz = _safe_float(c.get("filled_size")) or _safe_float(c.get("size")) or 0.0
                                fees_total = _safe_float(c.get("total_fees_usd")) or _safe_float(c.get("fee_usd")) or 0.0
                                ref_px = exit_px or entry_px or 0.0
                                notional = abs(filled_sz * (entry_px or exit_px or 0.0))
                                total_cost_bps = (fees_total / notional * 10000.0) if notional > 0 else 0.0
                                trade_id = str(c.get("order_id") or f"{c.get('symbol')}:{int(close_ts*1000)}")
                                await ts_conn.execute(
                                    "INSERT INTO trade_costs "
                                    "(trade_id, symbol, profile_id, execution_price, decision_mid_price, slippage_bps, "
                                    "fees, funding_cost, total_cost, order_size, side, timestamp, "
                                    "entry_fee_usd, exit_fee_usd, total_cost_bps) "
                                    "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,TO_TIMESTAMP($12),$13,$14,$15)",
                                    trade_id,
                                    c.get("symbol"),
                                    None,
                                    exit_px,
                                    ref_px,
                                    0.0,
                                    fees_total,
                                    0.0,
                                    fees_total,
                                    filled_sz if filled_sz > 0 else None,
                                    (c.get("original_side") or c.get("side") or "").lower() or None,
                                    close_ts,
                                    None,
                                    _safe_float(c.get("fee_usd")),
                                    total_cost_bps,
                                )
                            except Exception:
                                # Do not fail flatten if TCA write is unavailable.
                                pass
                    
                    await ts_conn.close()
                except Exception:
                    # Log but don't fail - positions are closed on exchange
                    pass
            
            return {
                "success": success_count > 0,
                "closed": closed,
                "count": success_count,
                "total": len(closed),
                "ambiguous": ambiguous_count,
                "realizedPnl": round(total_pnl, 2),
                "totalFees": round(total_fees, 2),
                "message": (
                    f"Closed {success_count}/{len(closed)} positions, "
                    f"skipped {ambiguous_count} ambiguous positions, PnL: ${total_pnl:.2f}"
                ),
            }
            
        except Exception as e:
            return {"success": False, "error": f"Exchange error: {str(e)}"}

    @app.post("/api/dashboard/orders/cancel", response_model=BotControlResponse, dependencies=[Depends(auth_dep)])
    async def dashboard_cancel_order(
        request: BotControlRequest,
        redis_client=Depends(_redis_client),
    ):
        tenant_id, bot_id = _resolve_scope(request.tenant_id, request.bot_id, require_explicit=True)
        request.tenant_id = tenant_id
        request.bot_id = bot_id
        request.action = "cancel"
        return await _publish_control_command(redis_client, "CANCEL_ORDER", request)

    @app.post("/api/dashboard/orders/replace", response_model=BotControlResponse, dependencies=[Depends(auth_dep)])
    async def dashboard_replace_order(
        request: BotControlRequest,
        redis_client=Depends(_redis_client),
    ):
        tenant_id, bot_id = _resolve_scope(request.tenant_id, request.bot_id, require_explicit=True)
        request.tenant_id = tenant_id
        request.bot_id = bot_id
        request.action = "replace"
        return await _publish_control_command(redis_client, "REPLACE_ORDER", request)

    @app.post("/api/dashboard/close-position", response_model=BotControlResponse, dependencies=[Depends(auth_dep)])
    async def dashboard_close_position(
        request: BotControlRequest,
        redis_client=Depends(_redis_client),
    ):
        tenant_id, bot_id = _resolve_scope(request.tenant_id, request.bot_id, require_explicit=True)
        request.tenant_id = tenant_id
        request.bot_id = bot_id
        request.action = "flatten"
        request.close_positions = True
        return await _publish_control_command(redis_client, "FLATTEN", request, confirm_required=True)

    @app.get("/api/dashboard/bots", dependencies=[Depends(auth_dep)])
    async def dashboard_bots():
        return {"bots": []}

    @app.get("/api/dashboard/profiles", dependencies=[Depends(auth_dep)])
    async def dashboard_profiles():
        return {"profiles": []}

    @app.get("/api/dashboard/strategies", dependencies=[Depends(auth_dep)])
    async def dashboard_strategies():
        return {"strategies": []}

    @app.get("/api/dashboard/profile-editor", dependencies=[Depends(auth_dep)])
    async def dashboard_profile_editor():
        return {"profile": None, "strategies": []}

    @app.get("/api/dashboard/history", dependencies=[Depends(auth_dep)])
    async def dashboard_history(
        tenant_id: str | None = None,
        bot_id: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ):
        tenant_id, bot_id = _resolve_scope(tenant_id, bot_id)
        events = await _fetch_timescale_rows(
            "SELECT event_type, detail, created_at FROM timeline_events "
            "WHERE tenant_id=$1 AND bot_id=$2 ORDER BY created_at DESC LIMIT $3 OFFSET $4",
            tenant_id,
            bot_id,
            limit,
            offset,
        )
        return {"events": events, "count": len(events)}

    @app.get("/api/dashboard/sl-tp-events", dependencies=[Depends(auth_dep)])
    async def dashboard_sl_tp_events(
        limit: int = 200,
        offset: int = 0,
        tenant_id: str | None = None,
        bot_id: str | None = None,
        redis_client=Depends(_redis_client),
    ):
        tenant_id, bot_id = _resolve_scope(tenant_id, bot_id)
        stream_key = f"quantgambit:{tenant_id}:{bot_id}:sltp_events"
        records = await _read_stream(redis_client, stream_key, limit=limit)
        # If no live events, fall back to Timescale history
        if not records:
            records = await _fetch_timescale_rows(
                "SELECT id, symbol, side, event_type, pnl, detail, created_at "
                "FROM sltp_events WHERE tenant_id=$1 AND bot_id=$2 "
                "ORDER BY created_at DESC LIMIT $3 OFFSET $4",
                tenant_id,
                bot_id,
                limit,
                offset,
            )
        events = [
            {
                "id": r.get("id"),
                "symbol": r.get("symbol"),
                "side": r.get("side"),
                "eventType": r.get("event_type") or r.get("eventType"),
                "pnl": _safe_float(r.get("pnl")),
                "detail": r.get("detail"),
                "created_at": r.get("created_at"),
            }
            for r in records
        ]
        return {"events": events, "count": len(events)}

    @app.get("/api/dashboard/exchange-positions", dependencies=[Depends(auth_dep)])
    async def dashboard_exchange_positions(
        tenant_id: str | None = None,
        bot_id: str | None = Query(default=None, alias="botId"),
        redis_client=Depends(_redis_client),
    ):
        """
        Best-effort "exchange truth" positions.

        The dashboard uses this to detect orphaned positions / drift.
        Previously this endpoint was a stub and always returned empty.
        """

        def _env_bool(name: str, default: bool = False) -> bool:
            raw = os.getenv(name)
            if raw is None:
                return default
            return str(raw).strip().lower() in {"1", "true", "yes", "y", "on"}

        tenant_id, bot_id = _resolve_scope(tenant_id, bot_id)

        exchange = (os.getenv("ACTIVE_EXCHANGE") or os.getenv("EXCHANGE") or "").strip().lower() or "unknown"
        secret_id = str(os.getenv("EXCHANGE_SECRET_ID") or "").strip()
        symbols = [s.strip() for s in str(os.getenv("ORDERBOOK_SYMBOLS") or "").split(",") if s.strip()]

        # Bybit has demo + testnet; demo is NOT the same as testnet.
        is_demo = _env_bool("BYBIT_DEMO", _env_bool("ORDER_UPDATES_DEMO", False))
        is_testnet = _env_bool("BYBIT_TESTNET", _env_bool("ORDERBOOK_TESTNET", False))

        # Fall back to engine positions snapshot if exchange fetch is unavailable.
        async def _fallback_engine_positions() -> list[dict[str, Any]]:
            try:
                reader = RedisSnapshotReader(redis_client)
                positions_key = f"quantgambit:{tenant_id}:{bot_id}:positions:latest"
                snap = await reader.read(positions_key) or {}
                engine_positions = snap.get("positions") or []
            except Exception:
                engine_positions = []
            out: list[dict[str, Any]] = []
            for p in engine_positions:
                sym = str(p.get("symbol") or "").strip().upper()
                side = str(p.get("side") or "").strip().upper()
                qty = _safe_float(p.get("size")) or 0.0
                if not sym or qty == 0:
                    continue
                out.append(
                    {
                        "symbol": sym,
                        "side": "LONG" if side == "LONG" or side == "long" else "SHORT",
                        "quantity": float(qty),
                        "entryPrice": _safe_float(p.get("entry_price")) or 0.0,
                        "markPrice": _safe_float(p.get("mark_price") or p.get("markPrice")) or 0.0,
                        "unrealizedPnl": _safe_float(p.get("unrealized_pnl") or p.get("unrealizedPnl") or p.get("pnl")) or 0.0,
                        "leverage": int(_safe_float(p.get("leverage")) or 1),
                        "marginType": str(p.get("marginType") or p.get("margin_type") or "unknown"),
                        "liquidationPrice": _safe_float(p.get("liqPrice") or p.get("liquidation_price")) or 0.0,
                        "breakEvenPrice": _safe_float(p.get("breakEvenPrice") or p.get("breakeven_price")) or 0.0,
                        "stopLoss": _safe_float(p.get("stop_loss") or p.get("stopLoss")),
                        "takeProfit": _safe_float(p.get("take_profit") or p.get("takeProfit")),
                    }
                )
            return out

        if exchange == "unknown" or not secret_id:
            return {
                "positions": await _fallback_engine_positions(),
                "exchange": exchange,
                "isDemo": bool(is_demo),
                "isTestnet": bool(is_testnet),
                "source": "engine_fallback_missing_exchange_config",
            }

        # Prefer an actual exchange fetch (ccxt), fall back to engine snapshot.
        try:
            from quantgambit.storage.secrets import SecretsProvider
            from quantgambit.execution.ccxt_clients import CcxtCredentials, build_ccxt_client

            provider = SecretsProvider()
            creds = provider.get_credentials(secret_id)
            if creds is None:
                raise RuntimeError("missing_exchange_creds")

            # Bybit Demo has partial API support in CCXT (notably positions),
            # so prefer the native V5 REST client for exchange-truth positions.
            if exchange == "bybit":
                from quantgambit.core.clock import WallClock
                from quantgambit.io.adapters.bybit.rest_client import BybitRESTClient, BybitRESTConfig

                base_url = "https://api.bybit.com"
                if is_demo:
                    base_url = "https://api-demo.bybit.com"
                elif is_testnet:
                    base_url = "https://api-testnet.bybit.com"

                bybit_cfg = BybitRESTConfig(
                    base_url=base_url,
                    api_key=creds.api_key,
                    api_secret=creds.secret_key,
                    category=str(os.getenv("BYBIT_V5_CATEGORY") or "linear").strip() or "linear",
                )
                bybit = BybitRESTClient(WallClock(), bybit_cfg)
                try:
                    # Bybit V5 may require `symbol` or `settleCoin` for position/list.
                    # We avoid settleCoin ambiguity by querying per configured symbol.
                    target_symbols = symbols or []
                    raw_positions: list[dict[str, Any]] = []
                    if target_symbols:
                        for sym in target_symbols:
                            try:
                                raw_positions.extend(await bybit.get_positions(sym))
                            except Exception:
                                continue
                    else:
                        raw_positions = await bybit.get_positions()
                finally:
                    await bybit.stop()

                positions: list[dict[str, Any]] = []
                for pos in raw_positions or []:
                    if not isinstance(pos, dict):
                        continue
                    sym = str(pos.get("symbol") or "").strip().upper()
                    size = _safe_float(pos.get("size")) or 0.0
                    if not sym or abs(float(size)) <= 0:
                        continue
                    side = "LONG" if float(size) > 0 else "SHORT"
                    raw = pos.get("raw") if isinstance(pos.get("raw"), dict) else {}
                    positions.append(
                        {
                            "symbol": sym,
                            "side": side,
                            "quantity": abs(float(size)),
                            "entryPrice": _safe_float(pos.get("entry_price")) or 0.0,
                            "markPrice": _safe_float(raw.get("markPrice") or raw.get("mark_price")) or 0.0,
                            "unrealizedPnl": _safe_float(pos.get("unrealized_pnl")) or 0.0,
                            "leverage": int(_safe_float(pos.get("leverage")) or 1),
                            "marginType": str(raw.get("tradeMode") or raw.get("marginMode") or "unknown"),
                            "liquidationPrice": _safe_float(pos.get("liq_price") or raw.get("liqPrice")) or 0.0,
                            "breakEvenPrice": _safe_float(raw.get("bustPrice") or raw.get("breakEvenPrice")) or 0.0,
                            "stopLoss": _safe_float(raw.get("stopLoss") or raw.get("stopLossPrice")),
                            "takeProfit": _safe_float(raw.get("takeProfit") or raw.get("takeProfitPrice")),
                        }
                    )

                return {
                    "positions": positions,
                    "exchange": exchange,
                    "isDemo": bool(is_demo),
                    "isTestnet": bool(is_testnet),
                    "source": "exchange_bybit_rest_v5",
                }

            ccxt_creds = CcxtCredentials(
                api_key=creds.api_key,
                secret_key=creds.secret_key,
                passphrase=getattr(creds, "passphrase", None),
                testnet=bool(is_testnet),
                demo=bool(is_demo),
            )
            client = build_ccxt_client(exchange, ccxt_creds, market_type="perp", margin_mode="isolated")
            try:
                rows = await client.fetch_positions(symbols or None)
            finally:
                await client.close()

            if rows is None:
                raise RuntimeError("exchange_positions_unavailable")

            positions: list[dict[str, Any]] = []
            for row in rows or []:
                if not isinstance(row, dict):
                    continue
                contracts = _safe_float(row.get("contracts") or row.get("size") or row.get("positionAmt"))
                if not contracts or abs(float(contracts)) <= 0:
                    continue
                side_raw = str(row.get("side") or "").strip().lower()
                side = "LONG" if side_raw == "long" else "SHORT" if side_raw == "short" else None
                if side is None:
                    # Sometimes Bybit returns size sign instead of explicit side.
                    side = "SHORT" if float(contracts) < 0 else "LONG"
                info = row.get("info") if isinstance(row.get("info"), dict) else {}
                # CCXT symbol might be "SOL/USDT:USDT"; normalize for UI.
                sym = (row.get("symbol") or info.get("symbol") or "").strip()
                sym = str(normalize_exchange_symbol(exchange, sym, "perp") or "").upper()
                if not sym:
                    continue
                positions.append(
                    {
                        "symbol": sym.upper(),
                        "side": side,
                        "quantity": abs(float(contracts)),
                        "entryPrice": _safe_float(row.get("entryPrice") or row.get("entry_price") or info.get("avgPrice")) or 0.0,
                        "markPrice": _safe_float(row.get("markPrice") or row.get("mark_price") or info.get("markPrice")) or 0.0,
                        "unrealizedPnl": _safe_float(row.get("unrealizedPnl") or row.get("unrealized_pnl") or info.get("unrealisedPnl")) or 0.0,
                        "leverage": int(_safe_float(row.get("leverage") or info.get("leverage")) or 1),
                        "marginType": str(row.get("marginMode") or info.get("tradeMode") or "unknown"),
                        "liquidationPrice": _safe_float(row.get("liquidationPrice") or info.get("liqPrice")) or 0.0,
                        "breakEvenPrice": _safe_float(row.get("breakEvenPrice") or info.get("bustPrice")) or 0.0,
                        "stopLoss": _safe_float(info.get("stopLoss") or info.get("stopLossPrice") or row.get("stopLoss")),
                        "takeProfit": _safe_float(info.get("takeProfit") or info.get("takeProfitPrice") or row.get("takeProfit")),
                    }
                )

            return {
                "positions": positions,
                "exchange": exchange,
                "isDemo": bool(is_demo),
                "isTestnet": bool(is_testnet),
                "source": "exchange_ccxt",
            }
        except Exception as exc:
            return {
                "positions": await _fallback_engine_positions(),
                "exchange": exchange,
                "isDemo": bool(is_demo),
                "isTestnet": bool(is_testnet),
                "source": "engine_fallback",
                "error": str(exc),
            }

    @app.get("/api/dashboard/orphaned-positions", dependencies=[Depends(auth_dep)])
    async def dashboard_orphaned_positions():
        return {"positions": [], "count": 0}

    @app.post("/api/dashboard/close-all-orphaned", dependencies=[Depends(auth_dep)])
    async def dashboard_close_all_orphaned():
        return {"closed": [], "count": 0}

    @app.post("/api/dashboard/clear-order-history", dependencies=[Depends(auth_dep)])
    async def dashboard_clear_order_history(
        tenant_id: str | None = None,
        bot_id: str | None = Query(default=None, alias="botId"),
        timescale=Depends(_timescale_reader),
    ):
        """Clear order history for a bot (for testing/debugging purposes)."""
        try:
            tenant_id, bot_id = _resolve_scope(tenant_id, bot_id, require_explicit=True)
        except Exception:
            return {"success": False, "error": "Could not resolve tenant/bot scope"}
        
        try:
            # Delete order_events for this bot
            result = await timescale.pool.execute(
                "DELETE FROM order_events WHERE tenant_id=$1 AND bot_id=$2",
                tenant_id, bot_id
            )
            deleted_orders = int(result.split()[-1]) if "DELETE" in result else 0
            
            # Also clear position_events
            result2 = await timescale.pool.execute(
                "DELETE FROM position_events WHERE tenant_id=$1 AND bot_id=$2",
                tenant_id, bot_id
            )
            deleted_positions = int(result2.split()[-1]) if "DELETE" in result2 else 0
            
            log_info(
                "dashboard_clear_order_history",
                tenant_id=tenant_id,
                bot_id=bot_id,
                deleted_orders=deleted_orders,
                deleted_positions=deleted_positions,
            )
            
            return {
                "success": True,
                "deleted_orders": deleted_orders,
                "deleted_positions": deleted_positions,
                "message": f"Cleared {deleted_orders} order events and {deleted_positions} position events",
            }
        except Exception as e:
            log_warning("dashboard_clear_order_history_error", error=str(e))
            return {"success": False, "error": str(e)}

    @app.post("/api/dashboard/clear-trade-history", dependencies=[Depends(auth_dep)])
    async def dashboard_clear_trade_history(
        tenant_id: str | None = None,
        bot_id: str | None = Query(default=None, alias="botId"),
        timescale=Depends(_timescale_reader),
        redis_client=Depends(_redis_client),
    ):
        """
        Clear trade/PnL history while keeping order history + market data (candles/orderbook/trades).

        This is intended for "start fresh" analysis runs without losing the raw market data
        needed for calibration/backtesting.
        """
        try:
            tenant_id, bot_id = _resolve_scope(tenant_id, bot_id, require_explicit=True)
        except Exception:
            return {"success": False, "error": "Could not resolve tenant/bot scope"}

        deleted = {}
        # Keep: order_events, order_intents, execution_ledger, order_execution_summary, market_candles, orderbook_snapshots, trade_records, market_trades, etc.
        tables_to_clear = [
            "position_events",
            "fee_events",
            "signals",
            "timeline_events",
            "risk_incidents",
            "sltp_events",
        ]
        for table in tables_to_clear:
            try:
                result = await timescale.pool.execute(
                    f"DELETE FROM {table} WHERE tenant_id=$1 AND bot_id=$2",
                    tenant_id,
                    bot_id,
                )
                deleted[table] = int(result.split()[-1]) if result else 0
            except Exception as e:
                deleted[table] = f"error:{e}"
                log_warning("dashboard_clear_trade_history_failed", table=table, error=str(e))

        # Clear Redis snapshots related to positions and derived PnL, but keep orders/execution snapshots.
        cleared_redis = 0
        try:
            patterns = [
                f"quantgambit:{tenant_id}:{bot_id}:positions:*",
                f"quantgambit:{tenant_id}:{bot_id}:pnl:*",
                f"quantgambit:{tenant_id}:{bot_id}:metrics:*",
                f"quantgambit:{tenant_id}:{bot_id}:risk:*",
            ]
            for pattern in patterns:
                keys = await redis_client.keys(pattern)
                if keys:
                    await redis_client.delete(*keys)
                    cleared_redis += len(keys)
        except Exception as e:
            log_warning("dashboard_clear_trade_history_redis_failed", error=str(e))

        log_info(
            "dashboard_clear_trade_history",
            tenant_id=tenant_id,
            bot_id=bot_id,
            deleted=deleted,
            cleared_redis_keys=cleared_redis,
        )
        return {"success": True, "deleted": deleted, "cleared_redis_keys": cleared_redis}

    @app.post("/api/dashboard/clear-execution-history", dependencies=[Depends(auth_dep)])
    async def dashboard_clear_execution_history(
        tenant_id: str | None = None,
        bot_id: str | None = Query(default=None, alias="botId"),
        timescale=Depends(_timescale_reader),
        redis_client=Depends(_redis_client),
    ):
        """
        Clear ALL bot orders/fills/trades + PnL history in our system.

        Intended for clean-slate debugging runs. This keeps market data tables
        (e.g. `market_candles`, orderbook snapshots, trade_records) intact.

        Deletes Timescale rows for:
        - order_events, order_intents, execution_ledger, order_execution_summary
        - position_events, fee_events
        - signals/timeline/risk/sltp derived tables
        Clears Redis snapshots for positions/orders/execution/metrics/pnl/risk + kill switch state.
        """
        try:
            tenant_id, bot_id = _resolve_scope(tenant_id, bot_id, require_explicit=True)
        except Exception:
            return {"success": False, "error": "Could not resolve tenant/bot scope"}

        deleted: dict[str, int | str] = {}
        # NOTE: order matters for FK constraints if any exist (typically there aren't in Timescale telemetry tables).
        tables_to_clear = [
            "order_events",
            "order_intents",
            "order_execution_summary",
            "execution_ledger",
            "position_events",
            "fee_events",
            "signals",
            "timeline_events",
            "risk_incidents",
            "sltp_events",
        ]
        for table in tables_to_clear:
            try:
                result = await timescale.pool.execute(
                    f"DELETE FROM {table} WHERE tenant_id=$1 AND bot_id=$2",
                    tenant_id,
                    bot_id,
                )
                deleted[table] = int(result.split()[-1]) if result else 0
            except Exception as e:
                deleted[table] = f"error:{e}"
                log_warning("dashboard_clear_execution_history_failed", table=table, error=str(e))

        cleared_redis = 0
        baseline_ms = int(time.time() * 1000)
        try:
            patterns = [
                f"quantgambit:{tenant_id}:{bot_id}:positions:*",
                f"quantgambit:{tenant_id}:{bot_id}:orders:*",
                f"quantgambit:{tenant_id}:{bot_id}:execution:*",
                f"quantgambit:{tenant_id}:{bot_id}:pnl:*",
                f"quantgambit:{tenant_id}:{bot_id}:metrics:*",
                f"quantgambit:{tenant_id}:{bot_id}:risk:*",
                f"quantgambit:{tenant_id}:{bot_id}:kill_switch:*",
                f"quantgambit:{tenant_id}:{bot_id}:reconciliation:*",
            ]
            for pattern in patterns:
                keys = await redis_client.keys(pattern)
                if keys:
                    await redis_client.delete(*keys)
                    cleared_redis += len(keys)
        except Exception as e:
            log_warning("dashboard_clear_execution_history_redis_failed", error=str(e))

        # Set a reconciliation baseline so we only reconcile executions after this reset.
        try:
            await redis_client.set(
                f"quantgambit:{tenant_id}:{bot_id}:execution_reconcile:baseline_ms",
                str(baseline_ms),
            )
            # Also pin last_ms to the baseline to avoid backfill from old windows.
            await redis_client.set(
                f"quantgambit:{tenant_id}:{bot_id}:execution_reconcile:last_ms",
                str(baseline_ms),
            )
        except Exception as e:
            log_warning("dashboard_clear_execution_history_baseline_failed", error=str(e))

        log_info(
            "dashboard_clear_execution_history",
            tenant_id=tenant_id,
            bot_id=bot_id,
            deleted=deleted,
            cleared_redis_keys=cleared_redis,
        )
        return {
            "success": True,
            "deleted": deleted,
            "cleared_redis_keys": cleared_redis,
            "reconcile_baseline_ms": baseline_ms,
        }

    @app.get("/api/dashboard/risk/limits", dependencies=[Depends(auth_dep)])
    async def dashboard_risk_limits():
        return {"success": True, "limits": [], "policy": _default_policy()}

    @app.get("/api/dashboard/risk/incidents", dependencies=[Depends(auth_dep)])
    async def dashboard_risk_incidents(
        limit: int = 200,
        offset: int = 0,
        tenant_id: str | None = None,
        bot_id: str | None = None,
        redis_client=Depends(_redis_client),
    ):
        tenant_id, bot_id = _resolve_scope(tenant_id, bot_id)
        stream_key = f"quantgambit:{tenant_id}:{bot_id}:risk:incidents"
        records = await _read_stream(redis_client, stream_key, limit=limit)
        if not records:
            records = await _fetch_timescale_rows(
                "SELECT id, type, symbol, limit_hit, detail, pnl, created_at "
                "FROM risk_incidents WHERE tenant_id=$1 AND bot_id=$2 "
                "ORDER BY created_at DESC LIMIT $3 OFFSET $4",
                tenant_id,
                bot_id,
                limit,
                offset,
            )
        incidents = [
            {
                "id": r.get("id"),
                "type": r.get("type"),
                "symbol": r.get("symbol"),
                "limit_hit": r.get("limit_hit"),
                "detail": r.get("detail"),
                "pnl": _safe_float(r.get("pnl")),
                "created_at": r.get("created_at"),
            }
            for r in records
        ]
        return {"success": True, "incidents": incidents, "total": len(incidents), "limit": limit, "offset": offset}

    @app.get("/api/dashboard/risk", dependencies=[Depends(auth_dep)])
    async def dashboard_risk(
        tenant_id: str | None = None,
        bot_id: str | None = None,
        redis_client=Depends(_redis_client),
    ):
        tenant_id, bot_id = _resolve_scope(tenant_id, bot_id)
        reader = RedisSnapshotReader(redis_client)
        positions = await reader.read(f"quantgambit:{tenant_id}:{bot_id}:positions:latest") or {}
        risk_snapshot = await reader.read(f"quantgambit:{tenant_id}:{bot_id}:risk:sizing") or {}
        exposure_payload = _compute_exposure_snapshot(positions.get("positions") or [])
        engine_exposure = risk_snapshot.get("exposure") or {}
        return {
            "data": {
                "exposureBySymbol": exposure_payload.get("exposureBySymbol", []),
                "blocklist": [],
                "totals": {
                    "totalExposureUsd": exposure_payload.get("totalExposureUsd", 0.0),
                    "engineTotalExposureUsd": engine_exposure.get("total_usd"),
                    "engineNetExposureUsd": engine_exposure.get("net_usd"),
                },
                "limits": risk_snapshot.get("limits"),
                "remaining": risk_snapshot.get("remaining"),
                "exposure": risk_snapshot.get("exposure"),
                "account_equity": risk_snapshot.get("account_equity"),
            }
        }

    @app.get("/api/loss-prevention/metrics", dependencies=[Depends(auth_dep)])
    async def loss_prevention_metrics(
        tenant_id: str | None = None,
        bot_id: str | None = None,
        window_hours: float = 24.0,
        redis_client=Depends(_redis_client),
    ):
        """Get loss prevention metrics including rejected signals and estimated losses avoided.
        
        Returns aggregated metrics for the Loss Prevention dashboard panel.
        
        Requirements: 8.2
        """
        from quantgambit.observability.loss_prevention_metrics import (
            LossPreventionMetrics,
            LossPreventionMetricsAggregator,
            DEFAULT_AVG_LOSS_PER_TRADE_USD,
        )
        from quantgambit.observability.blocked_signal_telemetry import BlockedSignalRepository
        
        tenant_id, bot_id = _resolve_scope(tenant_id, bot_id)
        tenant_id = await _resolve_runtime_tenant_scope(
            redis_client,
            tenant_id,
            bot_id,
            suffixes=["blocked_signals", "control:state", "health:latest"],
        )
        
        try:
            # Create repository (in-memory for now, can be extended to use database)
            repository = BlockedSignalRepository(connection_string=None)
            
            # Try to get counts from Redis stream
            stream_key = f"quantgambit:{tenant_id}:{bot_id}:blocked_signals"
            records = await _read_stream(redis_client, stream_key, limit=1000)
            
            # Aggregate counts by rejection reason
            counts_by_reason: Dict[str, int] = {}
            for record in records:
                reason = record.get("rejection_reason") or record.get("gate_name")
                if reason:
                    counts_by_reason[reason] = counts_by_reason.get(reason, 0) + 1
            
            # Create aggregator and get metrics
            aggregator = LossPreventionMetricsAggregator(
                repository=repository,
                avg_loss_per_trade_usd=DEFAULT_AVG_LOSS_PER_TRADE_USD,
            )
            
            metrics = aggregator.get_metrics_sync(
                counts_by_reason=counts_by_reason,
                window_hours=window_hours,
            )
            
            return {
                "success": True,
                "data": metrics.to_dict(),
                "updatedAt": int(time.time() * 1000),
            }
            
        except Exception as e:
            log_warning("loss_prevention_metrics_error", error=str(e))
            # Return empty metrics on error
            empty_metrics = LossPreventionMetrics.empty(window_hours=window_hours)
            return {
                "success": False,
                "error": str(e),
                "data": empty_metrics.to_dict(),
                "updatedAt": int(time.time() * 1000),
            }

    @app.get("/api/dashboard/candles/{symbol}", dependencies=[Depends(auth_dep)])
    async def dashboard_candles(
        symbol: str,
        timeframe: str = "1m",
        limit: int = 288,
        startTime: float | None = None,
        endTime: float | None = None,
        tenant_id: str | None = None,
        bot_id: str | None = Query(default=None, alias="botId"),
        redis_client=Depends(_redis_client),
        timescale=Depends(_timescale_reader),
    ):
        try:
            tenant_id, bot_id = _resolve_scope(tenant_id, bot_id)
        except Exception:
            return {
                "symbol": symbol,
                "timeframe": timeframe,
                "candles": [],
                "count": 0,
                "updatedAt": int(time.time() * 1000),
                "_warning": "missing_scope",
            }

        def _symbol_candidates(value: Any) -> list[str]:
            raw = str(value or "").strip().upper()
            canonical = _storage_symbol_key(raw)
            compact = "".join(ch for ch in raw if ch.isalnum())
            candidates = [raw, compact, canonical]
            seen: set[str] = set()
            unique: list[str] = []
            for item in candidates:
                key = str(item or "").strip().upper()
                if not key or key in seen:
                    continue
                seen.add(key)
                unique.append(key)
            return unique

        def _symbols_match(left: Any, right: Any) -> bool:
            left_set = set(_symbol_candidates(left))
            right_set = set(_symbol_candidates(right))
            return bool(left_set.intersection(right_set))

        def _timeframe_seconds(raw: Any) -> int | None:
            txt = str(raw or "").strip().lower()
            if not txt:
                return None
            if txt.endswith("m"):
                try:
                    return int(txt[:-1]) * 60
                except ValueError:
                    return None
            if txt.endswith("h"):
                try:
                    return int(txt[:-1]) * 3600
                except ValueError:
                    return None
            if txt.endswith("d"):
                try:
                    return int(txt[:-1]) * 86400
                except ValueError:
                    return None
            try:
                return int(float(txt))
            except (TypeError, ValueError):
                return None

        def _to_seconds(raw: Any) -> float | None:
            try:
                ts = float(raw)
            except (TypeError, ValueError):
                return None
            if ts > 1e15:  # microseconds
                return ts / 1_000_000.0
            if ts > 1e12:  # milliseconds
                return ts / 1000.0
            return ts

        def _bucketize_and_merge(
            rows: list[dict[str, Any]],
            tf_sec: int,
        ) -> list[dict[str, Any]]:
            if tf_sec <= 0:
                return sorted(rows, key=lambda item: int(item["time"]))
            sorted_rows = sorted(rows, key=lambda item: float(item.get("_raw_time", item["time"])))
            merged: dict[int, dict[str, Any]] = {}
            for item in sorted_rows:
                try:
                    raw_ts = float(item.get("_raw_time", item["time"]))
                    bucket_ts = int(raw_ts // tf_sec) * tf_sec
                    o = float(item["open"])
                    h = float(item["high"])
                    l = float(item["low"])
                    c = float(item["close"])
                    v = float(item.get("volume") or 0.0)
                except (TypeError, ValueError, KeyError):
                    continue
                if h < l:
                    continue
                existing = merged.get(bucket_ts)
                if existing is None:
                    merged[bucket_ts] = {
                        "time": int(bucket_ts),
                        "open": o,
                        "high": h,
                        "low": l,
                        "close": c,
                        "volume": v,
                    }
                    continue
                existing["high"] = max(float(existing["high"]), h)
                existing["low"] = min(float(existing["low"]), l)
                existing["close"] = c
                existing["volume"] = float(existing.get("volume") or 0.0) + v
            return sorted(merged.values(), key=lambda item: int(item["time"]))

        query_tf_sec = _timeframe_seconds(timeframe)
        start_sec = _to_seconds(startTime)
        end_sec = _to_seconds(endTime)
        symbol_variants = _symbol_candidates(symbol)
        limit = max(1, min(int(limit or 288), 5000))

        candles: list[dict[str, Any]] = []

        # For bounded historical windows (trade inspector), prefer finalized DB candles.
        prefer_timescale = True  # Always prefer DB — Redis stream only has a few recent events

        if timescale and getattr(timescale, "pool", None) and prefer_timescale:
            tf_sec = query_tf_sec or 60
            try:
                rows = await timescale.pool.fetch(
                    """
                    SELECT
                        EXTRACT(EPOCH FROM ts) AS ts_epoch,
                        open,
                        high,
                        low,
                        close,
                        volume
                    FROM market_candles
                    WHERE tenant_id = $1
                      AND bot_id = $2
                      AND timeframe_sec = $3
                      AND UPPER(symbol) = ANY($4::text[])
                      AND ($5::double precision IS NULL OR ts >= to_timestamp($5))
                      AND ($6::double precision IS NULL OR ts <= to_timestamp($6))
                    ORDER BY ts DESC
                    LIMIT $7
                    """,
                    tenant_id,
                    bot_id,
                    int(tf_sec),
                    symbol_variants,
                    start_sec,
                    end_sec,
                    limit,
                )
                for row in rows:
                    ts_epoch = row.get("ts_epoch") if isinstance(row, dict) else row["ts_epoch"]
                    ts_val = _to_seconds(ts_epoch)
                    if ts_val is None:
                        continue
                    candles.append(
                        {
                            "time": int(ts_val),
                            "open": float(row.get("open") if isinstance(row, dict) else row["open"]),
                            "high": float(row.get("high") if isinstance(row, dict) else row["high"]),
                            "low": float(row.get("low") if isinstance(row, dict) else row["low"]),
                            "close": float(row.get("close") if isinstance(row, dict) else row["close"]),
                            "volume": float((row.get("volume") if isinstance(row, dict) else row["volume"]) or 0.0),
                            "_raw_time": float(ts_val),
                        }
                    )
            except Exception:
                pass

        # For live/unbounded requests, or if DB had no rows, use stream fallback.
        if not candles:
            stream_candidates = [f"events:candles:{tenant_id}:{bot_id}", "events:candles"]
            raw_rows: list[Any] = []
            for stream in stream_candidates:
                try:
                    rows = await redis_client.xrevrange(stream, count=max(limit * 6, 500))
                except Exception:
                    continue
                if rows:
                    raw_rows = rows
                    break

            candles_by_time: dict[int, dict[str, Any]] = {}
            for row in raw_rows:
                fields = row[1] if isinstance(row, (list, tuple)) and len(row) > 1 else {}
                if isinstance(fields, list):
                    fields = {fields[i]: fields[i + 1] for i in range(0, len(fields), 2)}
                if not isinstance(fields, dict):
                    continue
                raw = fields.get("data")
                if not raw:
                    continue
                if isinstance(raw, bytes):
                    raw = raw.decode("utf-8")
                try:
                    event = json.loads(raw)
                except Exception:
                    continue
                if not isinstance(event, dict):
                    continue
                if event.get("event_type") and event.get("event_type") != "candle":
                    continue
                payload = event.get("payload") if isinstance(event.get("payload"), dict) else event
                if not isinstance(payload, dict):
                    continue
                if not _symbols_match(payload.get("symbol"), symbol):
                    continue
                payload_tf = payload.get("timeframe") or payload.get("timeframe_sec")
                payload_tf_sec = _timeframe_seconds(payload_tf)
                if query_tf_sec and payload_tf_sec != query_tf_sec:
                    continue
                ts_sec = _to_seconds(payload.get("timestamp") or event.get("timestamp"))
                if ts_sec is None:
                    continue
                if start_sec is not None and ts_sec < start_sec:
                    continue
                if end_sec is not None and ts_sec > end_sec:
                    continue
                try:
                    o = float(payload.get("open"))
                    h = float(payload.get("high"))
                    l = float(payload.get("low"))
                    c = float(payload.get("close"))
                except (TypeError, ValueError):
                    continue
                if h < l:
                    continue
                candle = {
                    "time": int(ts_sec),
                    "open": o,
                    "high": h,
                    "low": l,
                    "close": c,
                    "volume": float(payload.get("volume") or 0.0),
                    "_raw_time": float(ts_sec),
                }
                candles_by_time[int(ts_sec)] = candle
            candles = sorted(candles_by_time.values(), key=lambda item: int(item["time"]))

        if not candles and timescale and getattr(timescale, "pool", None) and not prefer_timescale:
            tf_sec = query_tf_sec or 60
            try:
                rows = await timescale.pool.fetch(
                    """
                    SELECT
                        EXTRACT(EPOCH FROM ts) AS ts_epoch,
                        open,
                        high,
                        low,
                        close,
                        volume
                    FROM market_candles
                    WHERE tenant_id = $1
                      AND bot_id = $2
                      AND timeframe_sec = $3
                      AND UPPER(symbol) = ANY($4::text[])
                      AND ($5::double precision IS NULL OR ts >= to_timestamp($5))
                      AND ($6::double precision IS NULL OR ts <= to_timestamp($6))
                    ORDER BY ts ASC
                    LIMIT $7
                    """,
                    tenant_id,
                    bot_id,
                    int(tf_sec),
                    symbol_variants,
                    start_sec,
                    end_sec,
                    limit,
                )
                for row in rows:
                    ts_epoch = row.get("ts_epoch") if isinstance(row, dict) else row["ts_epoch"]
                    ts_val = _to_seconds(ts_epoch)
                    if ts_val is None:
                        continue
                    candles.append(
                        {
                            "time": int(ts_val),
                            "open": float(row.get("open") if isinstance(row, dict) else row["open"]),
                            "high": float(row.get("high") if isinstance(row, dict) else row["high"]),
                            "low": float(row.get("low") if isinstance(row, dict) else row["low"]),
                            "close": float(row.get("close") if isinstance(row, dict) else row["close"]),
                            "volume": float((row.get("volume") if isinstance(row, dict) else row["volume"]) or 0.0),
                            "_raw_time": float(ts_val),
                        }
                    )
            except Exception:
                pass

        candles = _bucketize_and_merge(candles, int(query_tf_sec or 60))

        if len(candles) > limit:
            candles = candles[-limit:]

        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "candles": candles,
            "count": len(candles),
            "updatedAt": int(time.time() * 1000),
        }

    @app.get("/api/dashboard/drawdown", dependencies=[Depends(auth_dep)])
    async def dashboard_drawdown(
        hours: int = 24,
        tenant_id: str | None = None,
        bot_id: str | None = Query(default=None, alias="botId"),
        exchangeAccountId: str | None = None,
        exchange_account_id: str | None = None,
        redis_client=Depends(_redis_client),
        timescale=Depends(_timescale_reader),
        pool=Depends(_dashboard_pool),
    ):
        """Calculate equity curve and drawdown from order events."""
        account_id = exchangeAccountId or exchange_account_id
        if account_id and not bot_id and pool:
            try:
                resolved_bot = await _resolve_bot_from_exchange_account(pool, account_id)
                if resolved_bot:
                    bot_id = resolved_bot
            except Exception:
                pass
        try:
            if bot_id and not tenant_id:
                tenant_id = await _resolve_runtime_tenant_scope(
                    redis_client,
                    tenant_id,
                    bot_id,
                    suffixes=["positions:latest", "orders:history", "control:state", "health:latest"],
                )
            tenant_id, bot_id = _resolve_scope(tenant_id, bot_id)
        except Exception:
            return {
                "drawdown": [],
                "currentDrawdown": 0,
                "maxDrawdown": 0,
                "accountBalance": 0,
                "count": 0,
                "updatedAt": int(time.time() * 1000),
            }
        
        # Initialize Redis reader for later use
        reader = RedisSnapshotReader(redis_client)
        
        # Resolve exchange account ID - try explicit param first
        # If no explicit account_id, try to get it from bot's exchange config
        if not account_id and pool and bot_id:
            try:
                config_row = await pool.fetchrow(
                    """SELECT exchange_account_id FROM bot_exchange_configs 
                    WHERE bot_id = $1 AND is_active = true 
                    ORDER BY updated_at DESC LIMIT 1""",
                    bot_id
                )
                if config_row:
                    account_id = config_row.get("exchange_account_id")
            except Exception:
                pass
        
        # Get starting equity - priority: exchange_accounts table > Redis.
        # Do not invent PAPER_EQUITY here; viewer/admin dashboards must not show
        # fabricated account values when authoritative balance data is missing.
        starting_equity = None
        
        # 1. Try to get real balance from exchange_accounts table (platform DB)
        if account_id and pool:
            try:
                row = await pool.fetchrow(
                    "SELECT exchange_balance, available_balance, balance_currency "
                    "FROM exchange_accounts WHERE id = $1",
                    account_id
                )
                if row and row.get("exchange_balance"):
                    starting_equity = float(row["exchange_balance"])
            except Exception:
                pass
        
        # 2. If still no account, try to get any exchange account for this tenant with a balance
        if starting_equity is None and pool and tenant_id:
            try:
                row = await pool.fetchrow(
                    """SELECT exchange_balance FROM exchange_accounts 
                    WHERE tenant_id = $1 AND exchange_balance > 0 
                    ORDER BY updated_at DESC LIMIT 1""",
                    tenant_id
                )
                if row and row.get("exchange_balance"):
                    starting_equity = float(row["exchange_balance"])
            except Exception:
                pass
        
        # 3. Fall back to Redis account state
        if starting_equity is None:
            reader = RedisSnapshotReader(redis_client)
            account_state = await reader.read(f"quantgambit:{tenant_id}:{bot_id}:account:state") or {}
            risk_sizing = await reader.read(f"quantgambit:{tenant_id}:{bot_id}:risk:sizing") or {}
            starting_equity = float(account_state.get("equity") or risk_sizing.get("equity") or 0)
        
        if starting_equity is not None and starting_equity <= 0:
            starting_equity = None
        
        # Fetch order events with PnL data
        cutoff = datetime.now(timezone.utc) - __import__('datetime').timedelta(hours=hours)
        try:
            rows = await timescale.pool.fetch(
                "SELECT ts, payload, symbol FROM order_events "
                "WHERE tenant_id=$1 AND bot_id=$2 AND ts >= $3 "
                "ORDER BY ts ASC",
                tenant_id,
                bot_id,
                cutoff,
            )
        except Exception:
            rows = []
        
        # Build equity curve from filled orders
        equity_points = []
        current_equity = starting_equity or 0.0
        peak_equity = starting_equity or 0.0
        max_drawdown = 0.0
        
        for row in rows:
            payload = row.get("payload") or {}
            if isinstance(payload, str):
                try:
                    payload = json.loads(payload)
                except:
                    continue
            
            status = str(payload.get("status", "")).lower()
            if status not in {"filled", "closed"}:
                continue
            
            net_pnl = _safe_float(payload.get("net_pnl"))
            pnl = _safe_float(payload.get("pnl") or payload.get("realized_pnl") or 0)
            fees = _safe_float(payload.get("total_fees_usd") if payload.get("total_fees_usd") is not None else payload.get("fees") or payload.get("fee_usd") or 0)
            
            # Update equity (avoid double-subtracting fees if net_pnl provided)
            if net_pnl is not None:
                current_equity += net_pnl
                pnl = net_pnl
            else:
                current_equity += pnl - fees
            peak_equity = max(peak_equity, current_equity)
            
            # Calculate drawdown
            drawdown_pct = ((peak_equity - current_equity) / peak_equity * 100) if peak_equity > 0 else 0
            max_drawdown = max(max_drawdown, drawdown_pct)
            
            ts = row.get("ts")
            if ts:
                equity_points.append({
                    "time": ts.isoformat() if hasattr(ts, 'isoformat') else str(ts),
                    "equity": round(current_equity, 2),
                    "drawdown": round(drawdown_pct, 2),
                    "pnl": round(pnl, 2),
                })
        
        # Get unrealized PnL from current positions
        positions_snapshot = await reader.read(f"quantgambit:{tenant_id}:{bot_id}:positions:latest") or {}
        positions = positions_snapshot.get("positions") or []
        unrealized_pnl = sum(_safe_float(p.get("unrealized_pnl") or 0) for p in positions)
        
        # Never synthesize fake history. If authoritative equity history is not
        # available, return an empty curve and let the client render "Unavailable".
        if not equity_points:
            current_equity = (starting_equity or 0.0) + unrealized_pnl
        else:
            # Add current unrealized PnL to the most recent equity point
            current_equity = (starting_equity or 0.0) + unrealized_pnl
            if equity_points and unrealized_pnl != 0:
                # Update the last point with unrealized PnL
                now = datetime.now(timezone.utc)
                equity_points.append({
                    "time": now.isoformat(),
                    "equity": round(current_equity, 2),
                    "drawdown": round(max(0, (peak_equity - current_equity) / peak_equity * 100), 2) if peak_equity > 0 else 0,
                    "pnl": round(unrealized_pnl, 2),
                })
        
        # Update peak and calculate current drawdown
        peak_equity = max(peak_equity, current_equity)
        current_drawdown = ((peak_equity - current_equity) / peak_equity * 100) if peak_equity > 0 else 0
        max_drawdown = max(max_drawdown, current_drawdown)
        
        return {
            "drawdown": equity_points,
            "currentDrawdown": round(current_drawdown, 2),
            "maxDrawdown": round(max_drawdown, 2),
            "accountBalance": round(current_equity, 2) if starting_equity is not None else None,
            "peakEquity": round(peak_equity, 2) if starting_equity is not None else None,
            "startingEquity": round(starting_equity, 2) if starting_equity is not None else None,
            "count": len(equity_points),
            "updatedAt": int(time.time() * 1000),
        }

    @app.get("/api/bot-config/bots", dependencies=[Depends(auth_dep)])
    async def bot_config_bots(pool=Depends(_dashboard_pool)):
        rows = await _fetch_rows(
            pool,
            "SELECT id, name, environment, engine_type, description, status, owner_id, "
            "active_version_id, metadata, created_at, updated_at FROM bot_profiles ORDER BY updated_at DESC",
        )
        bots = [_format_bot_profile(row) for row in rows]
        return {"bots": bots}

    @app.get("/api/bot-config/bots/{bot_id}", dependencies=[Depends(auth_dep)])
    async def bot_config_bot_detail(bot_id: str, pool=Depends(_dashboard_pool)):
        bot_row = await _fetch_row(
            pool,
            "SELECT id, name, environment, engine_type, description, status, owner_id, "
            "active_version_id, metadata, created_at, updated_at FROM bot_profiles WHERE id=$1",
            bot_id,
        )
        version_rows = await _fetch_rows(
            pool,
            "SELECT id, bot_profile_id, version_number, status, config_blob, checksum, notes, "
            "created_by, promoted_by, created_at, activated_at "
            "FROM bot_profile_versions WHERE bot_profile_id=$1 ORDER BY version_number DESC",
            bot_id,
        )
        bot = _format_bot_profile(bot_row) if bot_row else _default_bot_profile(bot_id)
        versions = [_format_bot_version(row) for row in version_rows]
        return {"bot": bot, "versions": versions}

    @app.post("/api/bot-config/bots", dependencies=[Depends(auth_dep)])
    async def bot_config_create_bot(
        data: dict[str, Any],
        pool=Depends(_dashboard_pool),
        claims: UserClaims = Depends(auth_claims_dep),
    ):
        user_id = _scoped_user_id(claims)
        bot_id = str(uuid.uuid4())
        name = data.get("name") or f"Bot {bot_id}"
        environment = data.get("environment") or "paper"
        engine_type = data.get("engineType") or data.get("engine_type") or "quantgambit"
        description = data.get("description")
        metadata = data.get("metadata") or {}
        row = await _fetch_row(
            pool,
            "INSERT INTO bot_profiles (id, name, environment, engine_type, description, status, owner_id, metadata) "
            "VALUES ($1, $2, $3, $4, $5, $6, $7, $8) "
            "RETURNING id, name, environment, engine_type, description, status, owner_id, active_version_id, metadata, created_at, updated_at",
            bot_id,
            name,
            environment,
            engine_type,
            description,
            "inactive",
            user_id,
            json.dumps(metadata),
        )
        bot = _format_bot_profile(row) if row else _default_bot_profile(bot_id, name=name)
        version = _default_bot_version(bot_id)
        return {"message": "created", "bot": bot, "version": version}

    @app.post("/api/bot-config/bots/{bot_id}/versions", dependencies=[Depends(auth_dep)])
    async def bot_config_create_version(
        bot_id: str,
        data: dict[str, Any],
        pool=Depends(_dashboard_pool),
        claims: UserClaims = Depends(auth_claims_dep),
    ):
        user_id = _scoped_user_id(claims)
        bot_row = await _fetch_row(pool, "SELECT id FROM bot_profiles WHERE id=$1 AND owner_id=$2", bot_id, user_id)
        if not bot_row:
            raise HTTPException(status_code=404, detail="bot_profile_not_found")
        config_blob = data.get("config") or data.get("config_blob") or {}
        latest = await _fetch_row(
            pool,
            "SELECT COALESCE(MAX(version_number), 0) AS max_version FROM bot_profile_versions WHERE bot_profile_id=$1",
            bot_id,
        )
        next_version = int(data.get("versionNumber") or data.get("version_number") or 0)
        if not next_version:
            next_version = int((latest or {}).get("max_version", 0)) + 1
        row = await _fetch_row(
            pool,
            "INSERT INTO bot_profile_versions (bot_profile_id, version_number, status, config_blob, notes) "
            "VALUES ($1, $2, $3, $4, $5) "
            "RETURNING id, bot_profile_id, version_number, status, config_blob, checksum, notes, created_by, "
            "promoted_by, created_at, activated_at",
            bot_id,
            next_version,
            data.get("status") or "draft",
            json.dumps(config_blob),
            data.get("notes"),
        )
        version = _format_bot_version(row) if row else _default_bot_version(bot_id, version_number=next_version)
        return {"message": "created", "version": version, "activated": False}

    @app.post("/api/bot-config/bots/{bot_id}/activate", dependencies=[Depends(auth_dep)])
    async def bot_config_activate_version(
        bot_id: str,
        data: dict[str, Any],
        pool=Depends(_dashboard_pool),
        claims: UserClaims = Depends(auth_claims_dep),
    ):
        user_id = _scoped_user_id(claims)
        bot_row = await _fetch_row(pool, "SELECT id FROM bot_profiles WHERE id=$1 AND owner_id=$2", bot_id, user_id)
        if not bot_row:
            raise HTTPException(status_code=404, detail="bot_profile_not_found")
        version_id = data.get("versionId") or data.get("version_id")
        if not version_id:
            latest = await _fetch_row(
                pool,
                "SELECT id FROM bot_profile_versions WHERE bot_profile_id=$1 ORDER BY version_number DESC LIMIT 1",
                bot_id,
            )
            version_id = latest.get("id") if latest else None
        if version_id:
            await _fetch_row(
                pool,
                "UPDATE bot_profiles SET active_version_id=$1, updated_at=NOW() WHERE id=$2 AND owner_id=$3 RETURNING id",
                version_id,
                bot_id,
                user_id,
            )
        bot_row = await _fetch_row(
            pool,
            "SELECT id, name, environment, engine_type, description, status, owner_id, active_version_id, metadata, created_at, updated_at "
            "FROM bot_profiles WHERE id=$1 AND owner_id=$2",
            bot_id,
            user_id,
        )
        version_row = await _fetch_row(
            pool,
            "SELECT id, bot_profile_id, version_number, status, config_blob, checksum, notes, created_by, promoted_by, created_at, activated_at "
            "FROM bot_profile_versions WHERE id=$1",
            version_id,
        )
        bot = _format_bot_profile(bot_row) if bot_row else _default_bot_profile(bot_id)
        version = _format_bot_version(version_row) if version_row else _default_bot_version(bot_id, version_number=1)
        return {"message": "activated", "bot": bot, "version": version}

    @app.get("/api/bot-config/active-bot", dependencies=[Depends(auth_dep)])
    async def bot_config_active_bot(pool=Depends(_dashboard_pool)):
        row = await _fetch_row(
            pool,
            "SELECT id, name, environment, engine_type, description, status, owner_id, active_version_id, metadata, created_at, updated_at "
            "FROM bot_profiles WHERE active_version_id IS NOT NULL ORDER BY updated_at DESC LIMIT 1",
        )
        return {"bot": _format_bot_profile(row) if row else None}

    @app.post("/api/bot-config/active-bot", dependencies=[Depends(auth_dep)])
    async def bot_config_set_active_bot(
        data: dict[str, Any],
        pool=Depends(_dashboard_pool),
        claims: UserClaims = Depends(auth_claims_dep),
    ):
        user_id = _scoped_user_id(claims)
        bot_id = data.get("botId") or data.get("bot_id")
        if bot_id:
            owned_bot = await _fetch_row(pool, "SELECT id FROM bot_profiles WHERE id=$1 AND owner_id=$2", bot_id, user_id)
            if not owned_bot:
                raise HTTPException(status_code=404, detail="bot_profile_not_found")
            latest = await _fetch_row(
                pool,
                "SELECT id FROM bot_profile_versions WHERE bot_profile_id=$1 ORDER BY version_number DESC LIMIT 1",
                bot_id,
            )
            if latest:
                await _fetch_row(
                    pool,
                    "UPDATE bot_profiles SET active_version_id=$1, updated_at=NOW() WHERE id=$2 AND owner_id=$3 RETURNING id",
                    latest.get("id"),
                    bot_id,
                    user_id,
                )
            bot_row = await _fetch_row(
                pool,
                "SELECT id, name, environment, engine_type, description, status, owner_id, active_version_id, metadata, created_at, updated_at "
                "FROM bot_profiles WHERE id=$1 AND owner_id=$2",
                bot_id,
                user_id,
            )
            bot = _format_bot_profile(bot_row) if bot_row else _default_bot_profile(bot_id)
        else:
            bot = None
        return {"message": "active", "bot": bot}

    @app.get("/api/bot-config/strategies", dependencies=[Depends(auth_dep)])
    async def bot_config_strategies():
        return {"strategies": []}

    @app.get("/api/bot-config/strategies/{strategy_id}", dependencies=[Depends(auth_dep)])
    async def bot_config_strategy_detail(strategy_id: str):
        return {
            "strategy": {
                "id": strategy_id,
                "name": "Unknown",
                "description": "",
                "category": "unknown",
                "defaultParams": {},
                "paramDescriptions": {},
                "inUse": [],
                "inUseCount": 0,
            }
        }

    @app.get("/api/bot-config/profile-specs", dependencies=[Depends(auth_dep)])
    async def bot_config_profile_specs():
        return {"timestamp": int(time.time()), "specs": []}

    @app.get("/api/bot-config/profile-metrics", dependencies=[Depends(auth_dep)])
    async def bot_config_profile_metrics(
        tenant_id: str | None = None,
        bot_id: str | None = Query(default=None, alias="botId"),
        redis_client=Depends(_redis_client),
    ):
        tenant_id, bot_id = _resolve_scope(tenant_id, bot_id)
        reader = RedisSnapshotReader(redis_client)
        key_latest = f"quantgambit:{tenant_id}:{bot_id}:profile_router:latest"
        latest = await reader.read(key_latest) or {}
        redis_scan_timeout = max(0.2, float(_safe_float(os.getenv("PROFILE_ROUTER_REDIS_SCAN_TIMEOUT_SEC"), 1.0)))
        snapshot_read_timeout = max(0.05, float(_safe_float(os.getenv("PROFILE_ROUTER_SNAPSHOT_READ_TIMEOUT_SEC"), 0.15)))
        snapshot_key_limit = min(100, max(5, int(_safe_float(os.getenv("PROFILE_ROUTER_MAX_SYMBOL_KEYS"), 40))))
        symbol_keys = await _scan_redis_keys(
            redis_client,
            f"quantgambit:{tenant_id}:{bot_id}:profile_router:*:latest",
            limit=snapshot_key_limit,
            timeout_sec=redis_scan_timeout,
        )
        # Exclude the global latest key.
        symbol_keys = [k for k in symbol_keys if not k.endswith(":profile_router:latest")]

        snapshots: list[dict[str, Any]] = []
        if latest:
            snapshots.append(latest)
        for key in symbol_keys[:snapshot_key_limit]:
            try:
                snap = await asyncio.wait_for(reader.read(key), timeout=snapshot_read_timeout) or {}
            except Exception:
                snap = {}
            if snap:
                snapshots.append(snap)

        # Deduplicate snapshots by symbol, preferring latest-like payloads.
        by_symbol: dict[str, dict[str, Any]] = {}
        for snap in snapshots:
            sym = str(snap.get("symbol") or "").upper()
            if not sym:
                continue
            by_symbol[sym] = snap

        selected_counts: dict[tuple[str, str], int] = {}
        try:
            metrics_query_timeout = max(
                0.2,
                float(_safe_float(os.getenv("PROFILE_METRICS_QUERY_TIMEOUT_SEC"), 1.5)),
            )
            rows, metrics_timed_out = await _fetch_timescale_rows_timeboxed(
                """
                SELECT COALESCE(symbol, payload->>'symbol') AS symbol,
                       payload->>'profile_id' AS profile_id,
                       COUNT(*)::int AS picks
                FROM decision_events
                WHERE tenant_id=$1
                  AND bot_id=$2
                  AND ts >= NOW() - interval '24 hours'
                  AND payload->>'profile_id' IS NOT NULL
                GROUP BY COALESCE(symbol, payload->>'symbol'), payload->>'profile_id'
                """,
                tenant_id,
                bot_id,
                timeout_sec=metrics_query_timeout,
            )
            if not metrics_timed_out:
                for row in rows:
                    sym = str(row.get("symbol") or "").upper()
                    pid = str(row.get("profile_id") or "")
                    if not sym or not pid:
                        continue
                    selected_counts[(sym, pid)] = int(row.get("picks") or 0)
        except Exception:
            selected_counts = {}

        instances: list[dict[str, Any]] = []
        for sym, snap in by_symbol.items():
            selected = str(snap.get("selected_profile_id") or "")
            scores = snap.get("last_scores") or snap.get("scores") or []
            if not isinstance(scores, list):
                continue
            for entry in scores:
                if not isinstance(entry, dict):
                    continue
                pid = str(entry.get("profile_id") or "").strip()
                if not pid:
                    continue
                eligible = bool(entry.get("eligible", True))
                state = "disabled"
                if pid == selected and eligible:
                    state = "active"
                elif eligible:
                    state = "warming"
                instance = {
                    "profile_id": pid,
                    "symbol": sym,
                    "state": state,
                    "trades_count": int(selected_counts.get((sym, pid), 0)),
                    "wins": 0,
                    "losses": 0,
                    "win_rate": 0.0,
                    "total_pnl": 0.0,
                    "consecutive_losses": 0,
                    "max_drawdown": 0.0,
                    "error_count": 0,
                    "updated_at": _to_iso8601(snap.get("timestamp")) or _now_iso(),
                }
                instances.append(instance)

        total_instances = len(instances)
        total_profiles = len({i["profile_id"] for i in instances})
        active_instances = len([i for i in instances if i["state"] == "active"])
        warming_instances = len([i for i in instances if i["state"] == "warming"])
        cooling_instances = len([i for i in instances if i["state"] == "cooling"])
        disabled_instances = len([i for i in instances if i["state"] == "disabled"])
        error_instances = len([i for i in instances if i["state"] == "error"])
        return {
            "timestamp": int(time.time()),
            "total_profiles": total_profiles,
            "total_instances": total_instances,
            "active_instances": active_instances,
            "warming_instances": warming_instances,
            "cooling_instances": cooling_instances,
            "disabled_instances": disabled_instances,
            "error_instances": error_instances,
            "instances": instances,
            "diagnostics": {
                "symbolSnapshotKeys": len(symbol_keys),
                "redisScanTimeoutSec": redis_scan_timeout,
                "snapshotReadTimeoutSec": snapshot_read_timeout,
            },
        }

    @app.get("/api/bot-config/profile-router", dependencies=[Depends(auth_dep)])
    async def bot_config_profile_router(
        tenant_id: str | None = None,
        bot_id: str | None = Query(default=None, alias="botId"),
        symbol: str | None = None,
        redis_client=Depends(_redis_client),
    ):
        tenant_id, bot_id = _resolve_scope(tenant_id, bot_id)
        reader = RedisSnapshotReader(redis_client)
        key_latest = f"quantgambit:{tenant_id}:{bot_id}:profile_router:latest"
        redis_scan_timeout = max(0.2, float(_safe_float(os.getenv("PROFILE_ROUTER_REDIS_SCAN_TIMEOUT_SEC"), 1.0)))
        snapshot_read_timeout = max(0.05, float(_safe_float(os.getenv("PROFILE_ROUTER_SNAPSHOT_READ_TIMEOUT_SEC"), 0.15)))
        snapshot_key_limit = min(100, max(5, int(_safe_float(os.getenv("PROFILE_ROUTER_MAX_SYMBOL_KEYS"), 40))))
        symbol_snapshots: list[dict[str, Any]] = []
        symbol_keys: list[str] = []
        snapshot_key = f"quantgambit:{tenant_id}:{bot_id}:profile_router:{symbol}:latest" if symbol else key_latest
        snapshot = await reader.read(snapshot_key) or {}
        if not snapshot:
            snapshot = await reader.read(key_latest) or {}

        if symbol:
            if snapshot:
                symbol_snapshots.append(snapshot)
        else:
            symbol_keys = await _scan_redis_keys(
                redis_client,
                f"quantgambit:{tenant_id}:{bot_id}:profile_router:*:latest",
                limit=snapshot_key_limit,
                timeout_sec=redis_scan_timeout,
            )
            symbol_keys = [k for k in symbol_keys if not k.endswith(":profile_router:latest")]
            if snapshot:
                symbol_snapshots.append(snapshot)
            for key in symbol_keys[:snapshot_key_limit]:
                try:
                    snap = await asyncio.wait_for(reader.read(key), timeout=snapshot_read_timeout) or {}
                except Exception:
                    snap = {}
                if snap:
                    symbol_snapshots.append(snap)

        if not symbol_snapshots and snapshot:
            symbol_snapshots = [snapshot]

        def _snapshot_ts(item: dict[str, Any]) -> float:
            return _as_epoch_seconds(item.get("timestamp")) or 0.0

        primary = max(symbol_snapshots, key=_snapshot_ts) if symbol_snapshots else {}
        scores = primary.get("scores") or primary.get("last_scores") or []
        if not isinstance(scores, list):
            scores = []
        selected_profile_id = primary.get("selected_profile_id")
        live_symbol = str(primary.get("symbol") or symbol or "").upper() or None
        rejection_counts: dict[str, int] = {}
        rejection_summary: dict[str, list[dict[str, Any]]] = {}
        eligible_profiles = 0
        live_top_profiles: list[dict[str, Any]] = []
        now_ts = int(time.time())
        for snap in symbol_snapshots or [primary]:
            snap_symbol = str(snap.get("symbol") or live_symbol or "unknown").upper()
            snap_scores = snap.get("scores") or snap.get("last_scores") or []
            if not isinstance(snap_scores, list):
                continue
            valid_scores = [
                entry
                for entry in snap_scores
                if isinstance(entry, dict) and str(entry.get("profile_id") or "").strip()
            ]
            valid_scores.sort(
                key=lambda entry: _safe_float(entry.get("adjusted_score"), _safe_float(entry.get("score"), 0.0)),
                reverse=True,
            )
            if valid_scores:
                top = valid_scores[0]
                live_top_profiles.append(
                    {
                        "profile_id": str(top.get("profile_id") or ""),
                        "symbol": snap_symbol,
                        "score": _safe_float(top.get("adjusted_score"), _safe_float(top.get("score"), 0.0)),
                        "confidence": _safe_float(top.get("confidence"), 0.0),
                        "timestamp": now_ts,
                    }
                )
            for entry in valid_scores:
                profile_id = str(entry.get("profile_id") or "").strip()
                eligible = bool(entry.get("eligible", True))
                if eligible:
                    eligible_profiles += 1
                    continue
                reasons = entry.get("eligibility_reasons")
                if not isinstance(reasons, list):
                    reasons = []
                reason_texts = [str(r).strip() for r in reasons if str(r).strip()]
                if not reason_texts:
                    reason_texts = ["ineligible"]
                bucket = rejection_summary.setdefault(snap_symbol or "unknown", [])
                bucket.append({"profile_id": profile_id, "reasons": reason_texts})
                for reason in reason_texts:
                    rejection_counts[reason] = rejection_counts.get(reason, 0) + 1

        top_rejection_reasons = sorted(
            rejection_counts.items(),
            key=lambda item: item[1],
            reverse=True,
        )[:12]
        sorted_scores = [
            entry for entry in scores if isinstance(entry, dict) and str(entry.get("profile_id") or "").strip()
        ]
        sorted_scores.sort(
            key=lambda entry: _safe_float(entry.get("adjusted_score"), _safe_float(entry.get("score"), 0.0)),
            reverse=True,
        )
        live_top_profiles.sort(key=lambda item: _safe_float(item.get("score"), 0.0), reverse=True)
        live_top_profiles = live_top_profiles[:12]
        return {
            "timestamp": int(time.time()),
            "total_trades": 0,
            "total_wins": 0,
            "overall_win_rate": 0,
            "total_pnl": 0,
            "avg_pnl_per_trade": 0,
            "active_profiles": int(eligible_profiles),
            "registered_profiles": int(len(sorted_scores)),
            "ml_enabled": False,
            "top_profiles": [],
            "live_top_profiles": live_top_profiles,
            "selection_history": {},
            "rejection_summary": rejection_summary,
            "top_rejection_reasons": top_rejection_reasons,
            "symbol": live_symbol,
            "risk_mode": primary.get("risk_mode"),
            "selected_profile_id": selected_profile_id,
            "last_scores": scores,
            "diagnostics": {
                "symbolSnapshots": len(symbol_snapshots),
                "redisScanTimeoutSec": redis_scan_timeout,
                "symbolKeyCount": len(symbol_keys),
                "snapshotReadTimeoutSec": snapshot_read_timeout,
            },
        }

    @app.get("/api/bot-instances/templates", dependencies=[Depends(auth_dep)])
    async def bot_instances_templates():
        return {"templates": []}

    @app.get("/api/bot-instances/templates/{template_id}", dependencies=[Depends(auth_dep)])
    async def bot_instances_template_detail(template_id: str):
        return {"template": _default_strategy_template(template_id)}

    def _scoped_user_id(claims: UserClaims) -> str:
        # In this app, the "tenant" concept maps to the platform user id.
        # Keep a fallback for local/dev where AUTH_MODE may be disabled.
        user_id = str(claims.user_id or "").strip()
        if user_id.lower() in {"", "anonymous", "unknown", "none", "null"}:
            user_id = ""
        if not user_id:
            user_id = str(claims.tenant_id or "").strip()
        if user_id.lower() in {"", "anonymous", "unknown", "none", "null"}:
            user_id = ""
        if not user_id and os.getenv("AUTH_ALLOW_DEFAULT_USER_ID", "false").lower() in {"1", "true", "yes", "on"}:
            user_id = str(os.getenv("DEFAULT_USER_ID", "") or "").strip()
        if user_id.lower() in {"", "anonymous", "unknown", "none", "null"}:
            raise HTTPException(status_code=401, detail="user_id_missing")
        return user_id

    def _requested_user_id(claims: UserClaims, tenant_id: str | None = None) -> str:
        scoped_user_id = _scoped_user_id(claims)
        candidate = str(tenant_id or "").strip()
        if candidate.lower() not in {"", "anonymous", "unknown", "none", "null"}:
            if candidate != scoped_user_id:
                raise HTTPException(status_code=403, detail="tenant_scope_mismatch")
            return candidate
        return scoped_user_id

    async def _require_owned_bot_instance(pool, bot_id: str, user_id: str) -> dict[str, Any]:
        row = await _fetch_row(
            pool,
            "SELECT * FROM bot_instances WHERE id=$1 AND user_id=$2 AND deleted_at IS NULL",
            bot_id,
            user_id,
        )
        if not row:
            raise HTTPException(status_code=404, detail="bot_instance_not_found")
        return row

    @app.get("/api/bot-instances", dependencies=[Depends(auth_dep)])
    async def bot_instances_list(
        includeInactive: bool | None = None,
        tenant_id: str | None = None,
        pool=Depends(_dashboard_pool),
        claims: UserClaims = Depends(auth_claims_dep),
    ):
        user_id = _requested_user_id(claims, tenant_id)
        query = (
            "SELECT id, user_id, name, description, strategy_template_id, allocator_role, market_type, "
            "default_risk_config, default_execution_config, profile_overrides, tags, is_active, trading_mode, "
            "created_at, updated_at FROM bot_instances WHERE user_id=$1 "
            + ("" if includeInactive else "AND deleted_at IS NULL")
            + " ORDER BY updated_at DESC"
        )
        rows = await _fetch_rows(pool, query, user_id)
        bots = [_format_bot_instance(row) for row in rows]

        # Attach exchange configs for each bot
        if bots:
            bot_ids = [b["id"] for b in bots]
            placeholders = ",".join(f"${i+1}" for i in range(len(bot_ids)))
            cfg_rows = await _fetch_rows(
                pool,
                f"""
                SELECT bec.*, ea.label AS exchange_account_label, ea.venue AS exchange_account_venue
                FROM bot_exchange_configs bec
                LEFT JOIN exchange_accounts ea ON ea.id = bec.exchange_account_id
                WHERE bec.bot_instance_id IN ({placeholders}) AND bec.deleted_at IS NULL
                """,
                *bot_ids,
            )
            configs_by_bot: dict[str, list[dict[str, Any]]] = {}
            for cfg in cfg_rows:
                formatted = _format_exchange_config(cfg)
                configs_by_bot.setdefault(formatted["bot_instance_id"], []).append(formatted)
            for bot in bots:
                bot["exchangeConfigs"] = configs_by_bot.get(bot["id"], [])

        return {"bots": bots}

    @app.get("/api/bot-instances/{bot_id}", dependencies=[Depends(auth_dep)])
    async def bot_instances_detail(
        bot_id: str,
        tenant_id: str | None = None,
        botId: str | None = None,
        pool=Depends(_dashboard_pool),
        redis_client=Depends(_redis_client),
        claims: UserClaims = Depends(auth_claims_dep),
    ):
        if str(bot_id).strip().lower() == "active":
            tenant_id, resolved_bot_id = _resolve_scope(tenant_id, botId)
            target_bot_id = resolved_bot_id
            if target_bot_id:
                bot_row = await _fetch_row(
                    pool,
                    "SELECT * FROM bot_instances WHERE id=$1 AND deleted_at IS NULL",
                    target_bot_id,
                )
            else:
                bot_row = await _fetch_row(
                    pool,
                    "SELECT * FROM bot_instances WHERE is_active=true AND deleted_at IS NULL "
                    "ORDER BY updated_at DESC LIMIT 1",
                )
            if not bot_row:
                return {"active": None, "symbols": [], "policy": _default_policy()}
            exchange_row = await _fetch_row(
                pool,
                "SELECT bec.*, ea.venue AS exchange, ea.label AS exchange_account_label "
                "FROM bot_exchange_configs bec "
                "LEFT JOIN exchange_accounts ea ON bec.exchange_account_id = ea.id "
                "WHERE bec.bot_instance_id=$1 AND bec.is_active=true AND bec.deleted_at IS NULL "
                "ORDER BY bec.updated_at DESC LIMIT 1",
                bot_row.get("id"),
            )
            runtime_active = False
            try:
                reader = RedisSnapshotReader(redis_client)
                health = await reader.read(f"quantgambit:{tenant_id}:{bot_row.get('id')}:health:latest") or {}
                heartbeat_epoch = _coerce_epoch_timestamp(
                    health.get("timestamp_epoch") or health.get("timestamp")
                )
                heartbeat_age = (time.time() - heartbeat_epoch) if heartbeat_epoch else None
                health_status = str(health.get("status") or "").strip().lower()
                services = health.get("services") if isinstance(health, dict) else {}
                python_engine = services.get("python_engine") if isinstance(services, dict) else {}
                engine_status = str((python_engine or {}).get("status") or "").strip().lower()
                runtime_active = bool(
                    heartbeat_age is not None
                    and heartbeat_age <= 30.0
                    and (
                        health_status in {"ok", "running", "healthy"}
                        or engine_status in {"running", "online", "ok", "healthy"}
                    )
                )
            except Exception:
                runtime_active = False
            if not exchange_row and runtime_active:
                exchange_row = await _fetch_row(
                    pool,
                    "SELECT bec.*, ea.venue AS exchange, ea.label AS exchange_account_label "
                    "FROM bot_exchange_configs bec "
                    "LEFT JOIN exchange_accounts ea ON bec.exchange_account_id = ea.id "
                    "WHERE bec.bot_instance_id=$1 AND bec.deleted_at IS NULL "
                    "ORDER BY bec.updated_at DESC LIMIT 1",
                    bot_row.get("id"),
                )
            active_config = _format_exchange_config(exchange_row) if exchange_row else None
            if active_config and runtime_active:
                active_config["is_active"] = True
                active_config["state"] = "running"
                active_config["runtime_inferred_active"] = True
            return {"active": active_config, "symbols": [], "policy": _default_policy()}

        user_id = _scoped_user_id(claims)
        row = await _fetch_row(
            pool,
            "SELECT id, user_id, name, description, strategy_template_id, allocator_role, market_type, "
            "default_risk_config, default_execution_config, profile_overrides, tags, is_active, trading_mode, "
            "created_at, updated_at FROM bot_instances WHERE id=$1 AND user_id=$2",
            bot_id,
            user_id,
        )
        return {"bot": _format_bot_instance(row) if row else _default_bot_instance(bot_id)}

    @app.post("/api/bot-instances", dependencies=[Depends(auth_dep)])
    async def bot_instances_create(
        data: dict[str, Any],
        tenant_id: str | None = None,
        pool=Depends(_dashboard_pool),
        claims: UserClaims = Depends(auth_claims_dep),
    ):
        user_id = _requested_user_id(claims, tenant_id)
        existing_user = await _fetch_row(pool, "SELECT id FROM users WHERE id=$1", user_id)
        if not existing_user:
            raise HTTPException(
                status_code=401,
                detail={
                    "error": "user_not_found",
                    "message": "No user row found for bot create request",
                    "user_id": user_id,
                },
            )
        bot_id = str(uuid.uuid4())
        name = data.get("name") or f"Bot {bot_id[:6]}"
        description = data.get("description")
        strategy_template_id = data.get("strategyTemplateId") or data.get("strategy_template_id")
        allocator_role = data.get("allocatorRole") or data.get("allocator_role") or "core"
        requested_bot_type = _normalize_bot_type(data.get("botType") or data.get("bot_type"))
        market_type = (data.get("marketType") or data.get("market_type") or ("spot" if requested_bot_type == "ai_spot_swing" else "perp")).lower()
        default_risk_config = data.get("defaultRiskConfig") or data.get("default_risk_config") or {}
        default_execution_config = data.get("defaultExecutionConfig") or data.get("default_execution_config") or {}
        profile_overrides = _normalize_bot_profile_overrides(data)
        tags = data.get("tags") or []
        is_active = bool(data.get("isActive", True))
        trading_mode = (data.get("tradingMode") or data.get("trading_mode") or "paper").lower()
        await pool.execute(
            """
            INSERT INTO bot_instances
              (id, user_id, name, description, strategy_template_id, allocator_role, market_type,
               default_risk_config, default_execution_config, profile_overrides, tags, is_active, trading_mode, created_at, updated_at)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,NOW(),NOW())
            """,
            bot_id,
            user_id,
            name,
            description,
            strategy_template_id,
            allocator_role,
            market_type,
            json.dumps(default_risk_config),
            json.dumps(default_execution_config),
            json.dumps(profile_overrides),
            tags,
            is_active,
            trading_mode,
        )
        row = await _fetch_row(
            pool,
            "SELECT id, user_id, name, description, strategy_template_id, allocator_role, market_type, "
            "default_risk_config, default_execution_config, profile_overrides, tags, is_active, trading_mode, "
            "created_at, updated_at FROM bot_instances WHERE id=$1",
            bot_id,
        )
        return {"message": "created", "bot": _format_bot_instance(row)}

    @app.put("/api/bot-instances/{bot_id}", dependencies=[Depends(auth_dep)])
    async def bot_instances_update(
        bot_id: str,
        data: dict[str, Any],
        pool=Depends(_dashboard_pool),
        claims: UserClaims = Depends(auth_claims_dep),
    ):
        user_id = _scoped_user_id(claims)
        existing = await _fetch_row(
            pool,
            "SELECT profile_overrides FROM bot_instances WHERE id=$1 AND user_id=$2",
            bot_id,
            user_id,
        )
        profile_overrides = None
        if (
            data.get("profileOverrides") is not None
            or data.get("profile_overrides") is not None
            or data.get("botType") is not None
            or data.get("bot_type") is not None
            or data.get("aiProvider") is not None
            or data.get("ai_provider") is not None
            or data.get("aiProfile") is not None
            or data.get("ai_profile") is not None
            or data.get("aiShadowMode") is not None
            or data.get("ai_shadow_mode") is not None
            or data.get("aiConfidenceFloor") is not None
            or data.get("ai_confidence_floor") is not None
            or data.get("aiSentimentRequired") is not None
            or data.get("ai_sentiment_required") is not None
            or data.get("aiRequireBaselineAlignment") is not None
            or data.get("ai_require_baseline_alignment") is not None
            or data.get("aiSessions") is not None
            or data.get("ai_sessions") is not None
        ):
            profile_overrides = _normalize_bot_profile_overrides(
                data,
                _ensure_json(existing.get("profile_overrides")) if existing else None,
            )
        await pool.execute(
            """
            UPDATE bot_instances SET
              name=COALESCE($3,name),
              description=COALESCE($4,description),
              allocator_role=COALESCE($5,allocator_role),
              market_type=COALESCE($6,market_type),
              default_risk_config=COALESCE($7,default_risk_config),
              default_execution_config=COALESCE($8,default_execution_config),
              profile_overrides=COALESCE($9,profile_overrides),
              tags=COALESCE($10,tags),
              is_active=COALESCE($11,is_active),
              trading_mode=COALESCE($12,trading_mode),
              updated_at=NOW()
            WHERE id=$1 AND user_id=$2
            """,
            bot_id,
            user_id,
            data.get("name"),
            data.get("description"),
            data.get("allocatorRole") or data.get("allocator_role"),
            (data.get("marketType") or data.get("market_type")) if data.get("marketType") or data.get("market_type") else None,
            json.dumps(data.get("defaultRiskConfig") or data.get("default_risk_config")) if data.get("defaultRiskConfig") or data.get("default_risk_config") else None,
            json.dumps(data.get("defaultExecutionConfig") or data.get("default_execution_config")) if data.get("defaultExecutionConfig") or data.get("default_execution_config") else None,
            json.dumps(profile_overrides) if profile_overrides is not None else None,
            data.get("tags"),
            data.get("isActive"),
            (data.get("tradingMode") or data.get("trading_mode")) if data.get("tradingMode") or data.get("trading_mode") else None,
        )
        row = await _fetch_row(
            pool,
            "SELECT id, user_id, name, description, strategy_template_id, allocator_role, market_type, "
            "default_risk_config, default_execution_config, profile_overrides, tags, is_active, trading_mode, "
            "created_at, updated_at FROM bot_instances WHERE id=$1 AND user_id=$2",
            bot_id,
            user_id,
        )
        return {"message": "updated", "bot": _format_bot_instance(row)}

    @app.delete("/api/bot-instances/{bot_id}", dependencies=[Depends(auth_dep)])
    async def bot_instances_delete(
        bot_id: str,
        pool=Depends(_dashboard_pool),
        claims: UserClaims = Depends(auth_claims_dep),
    ):
        user_id = _scoped_user_id(claims)
        await pool.execute(
            "UPDATE bot_instances SET deleted_at=NOW(), is_active=false WHERE id=$1 AND user_id=$2",
            bot_id,
            user_id,
        )
        return {"message": "deleted"}

    @app.get("/api/bot-instances/{bot_id}/logs", dependencies=[Depends(auth_dep)])
    async def bot_instances_logs(bot_id: str, limit: int = 200):
        return {"logs": [], "count": 0}

    @app.post("/api/bot-instances/{bot_id}/configs/{config_id}/clear-errors", dependencies=[Depends(auth_dep)])
    async def bot_instances_clear_errors(
        bot_id: str,
        config_id: str,
        pool=Depends(_dashboard_pool),
        claims: UserClaims = Depends(auth_claims_dep),
    ):
        user_id = _scoped_user_id(claims)
        await _require_owned_bot_instance(pool, bot_id, user_id)
        return {"message": "cleared"}

    @app.post("/api/bot-instances/{bot_id}/start", dependencies=[Depends(auth_dep)])
    async def bot_instances_start(
        bot_id: str,
        pool=Depends(_dashboard_pool),
        claims: UserClaims = Depends(auth_claims_dep),
    ):
        user_id = _scoped_user_id(claims)
        await _require_owned_bot_instance(pool, bot_id, user_id)
        return {"message": "started"}

    @app.post("/api/bot-instances/{bot_id}/stop", dependencies=[Depends(auth_dep)])
    async def bot_instances_stop(
        bot_id: str,
        pool=Depends(_dashboard_pool),
        claims: UserClaims = Depends(auth_claims_dep),
    ):
        user_id = _scoped_user_id(claims)
        await _require_owned_bot_instance(pool, bot_id, user_id)
        return {"message": "stopped"}

    @app.post("/api/bot-instances/{bot_id}/pause", dependencies=[Depends(auth_dep)])
    async def bot_instances_pause(
        bot_id: str,
        pool=Depends(_dashboard_pool),
        claims: UserClaims = Depends(auth_claims_dep),
    ):
        user_id = _scoped_user_id(claims)
        await _require_owned_bot_instance(pool, bot_id, user_id)
        return {"message": "paused"}

    @app.post("/api/bot-instances/{bot_id}/resume", dependencies=[Depends(auth_dep)])
    async def bot_instances_resume(
        bot_id: str,
        pool=Depends(_dashboard_pool),
        claims: UserClaims = Depends(auth_claims_dep),
    ):
        user_id = _scoped_user_id(claims)
        await _require_owned_bot_instance(pool, bot_id, user_id)
        return {"message": "resumed"}

    @app.get("/api/bot-instances/{bot_id}/budget", dependencies=[Depends(auth_dep)])
    async def bot_instances_budget(bot_id: str):
        return {"budget": None}

    @app.put("/api/bot-instances/{bot_id}/budget", dependencies=[Depends(auth_dep)])
    async def bot_instances_budget_update(
        bot_id: str,
        data: dict[str, Any],
        pool=Depends(_dashboard_pool),
        claims: UserClaims = Depends(auth_claims_dep),
    ):
        user_id = _scoped_user_id(claims)
        await _require_owned_bot_instance(pool, bot_id, user_id)
        return {"budget": data}

    @app.delete("/api/bot-instances/{bot_id}/budget", dependencies=[Depends(auth_dep)])
    async def bot_instances_budget_delete(
        bot_id: str,
        pool=Depends(_dashboard_pool),
        claims: UserClaims = Depends(auth_claims_dep),
    ):
        user_id = _scoped_user_id(claims)
        await _require_owned_bot_instance(pool, bot_id, user_id)
        return {"message": "deleted"}

    @app.get("/api/bot-instances/{bot_id}/exchanges", dependencies=[Depends(auth_dep)])
    async def bot_instances_exchanges(bot_id: str, pool=Depends(_dashboard_pool)):
        rows = await _fetch_rows(
            pool,
            "SELECT * FROM bot_exchange_configs WHERE bot_instance_id=$1 AND deleted_at IS NULL ORDER BY updated_at DESC",
            bot_id,
        )
        return {"configs": [_format_exchange_config(row) for row in rows]}

    @app.get("/api/bot-instances/{bot_id}/exchanges/{config_id}", dependencies=[Depends(auth_dep)])
    async def bot_instances_exchange_detail(bot_id: str, config_id: str, pool=Depends(_dashboard_pool)):
        row = await _fetch_row(
            pool,
            """
            SELECT bec.*, ea.label AS exchange_account_label, ea.venue AS exchange_account_venue
            FROM bot_exchange_configs bec
            LEFT JOIN exchange_accounts ea ON ea.id = bec.exchange_account_id
            WHERE bec.id=$1
            """,
            config_id,
        )
        versions = await _fetch_rows(
            pool,
            "SELECT * FROM bot_exchange_config_versions WHERE bot_exchange_config_id=$1 ORDER BY version_number DESC",
            config_id,
        )
        return {
            "config": _format_exchange_config(row) if row else _default_exchange_config(bot_id, config_id),
            "symbolConfigs": [],
            "versions": [_format_config_version(v) for v in versions],
        }

    @app.post("/api/bot-instances/{bot_id}/exchanges", dependencies=[Depends(auth_dep)])
    async def bot_instances_exchange_create(
        bot_id: str,
        data: dict[str, Any],
        pool=Depends(_dashboard_pool),
        claims: UserClaims = Depends(auth_claims_dep),
    ):
        user_id = _scoped_user_id(claims)
        await _require_owned_bot_instance(pool, bot_id, user_id)
        config_id = str(uuid.uuid4())
        exchange_account_id = data.get("exchangeAccountId") or data.get("exchange_account_id")
        credential_id = data.get("credentialId") or data.get("credential_id")
        exchange = data.get("exchange")
        environment = data.get("environment") or "paper"
        trading_capital = data.get("tradingCapitalUsd") or data.get("trading_capital_usd")
        enabled_symbols = data.get("enabledSymbols") or data.get("enabled_symbols") or []
        risk_config = data.get("riskConfig") or data.get("risk_config") or {}
        execution_config = data.get("executionConfig") or data.get("execution_config") or {}
        notes = data.get("notes")
        if not exchange_account_id:
            raise HTTPException(status_code=400, detail="exchange_account_id is required")
        if not exchange:
            raise HTTPException(status_code=400, detail="exchange is required")
        # Guard live activation on same exchange account
        if bool(data.get("isActive", True)) and environment.lower() == "live" and exchange_account_id:
            await _ensure_single_live_per_account(pool, exchange_account_id)

        await pool.execute(
            """
            INSERT INTO bot_exchange_configs
              (id, bot_instance_id, credential_id, exchange_account_id, exchange, environment,
               trading_capital_usd, enabled_symbols, risk_config, execution_config, profile_overrides,
               state, is_active, created_at, updated_at, notes)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,NOW(),NOW(),$14)
            """,
            config_id,
            bot_id,
            credential_id,
            exchange_account_id,
            exchange,
            environment,
            trading_capital,
            json.dumps(enabled_symbols),
            json.dumps(risk_config),
            json.dumps(execution_config),
            json.dumps(data.get("profileOverrides") or data.get("profile_overrides") or {}),
            data.get("state") or "created",
            bool(data.get("isActive", True)),
            notes,
        )
        row = await _fetch_row(
            pool,
            """
            SELECT bec.*, ea.label AS exchange_account_label, ea.venue AS exchange_account_venue
            FROM bot_exchange_configs bec
            LEFT JOIN exchange_accounts ea ON ea.id = bec.exchange_account_id
            WHERE bec.id=$1
            """,
            config_id,
        )
        return {"message": "created", "config": _format_exchange_config(row)}

    @app.put("/api/bot-instances/{bot_id}/exchanges/{config_id}", dependencies=[Depends(auth_dep)])
    async def bot_instances_exchange_update(
        bot_id: str,
        config_id: str,
        data: dict[str, Any],
        pool=Depends(_dashboard_pool),
        claims: UserClaims = Depends(auth_claims_dep),
    ):
        user_id = _scoped_user_id(claims)
        await _require_owned_bot_instance(pool, bot_id, user_id)
        await pool.execute(
            """
            UPDATE bot_exchange_configs SET
              exchange_account_id=COALESCE($3,exchange_account_id),
              credential_id=COALESCE($4,credential_id),
              exchange=COALESCE($5,exchange),
              environment=COALESCE($6,environment),
              trading_capital_usd=COALESCE($7,trading_capital_usd),
              enabled_symbols=COALESCE($8,enabled_symbols),
              risk_config=COALESCE($9,risk_config),
              execution_config=COALESCE($10,execution_config),
              profile_overrides=COALESCE($11,profile_overrides),
              notes=COALESCE($12,notes),
              updated_at=NOW()
            WHERE id=$1 AND bot_instance_id=$2
            """,
            config_id,
            bot_id,
            data.get("exchangeAccountId") or data.get("exchange_account_id"),
            data.get("credentialId") or data.get("credential_id"),
            data.get("exchange"),
            data.get("environment"),
            data.get("tradingCapitalUsd") or data.get("trading_capital_usd"),
            json.dumps(data.get("enabledSymbols")) if data.get("enabledSymbols") is not None else json.dumps(data.get("enabled_symbols")) if data.get("enabled_symbols") is not None else None,
            json.dumps(data.get("riskConfig") or data.get("risk_config")) if data.get("riskConfig") or data.get("risk_config") else None,
            json.dumps(data.get("executionConfig") or data.get("execution_config")) if data.get("executionConfig") or data.get("execution_config") else None,
            json.dumps(data.get("profileOverrides") or data.get("profile_overrides")) if data.get("profileOverrides") or data.get("profile_overrides") else None,
            data.get("notes"),
        )
        row = await _fetch_row(
            pool,
            "SELECT * FROM bot_exchange_configs WHERE id=$1 AND bot_instance_id=$2",
            config_id,
            bot_id,
        )
        return {"message": "updated", "config": _format_exchange_config(row)}

    @app.delete("/api/bot-instances/{bot_id}/exchanges/{config_id}", dependencies=[Depends(auth_dep)])
    async def bot_instances_exchange_delete(
        bot_id: str,
        config_id: str,
        pool=Depends(_dashboard_pool),
        claims: UserClaims = Depends(auth_claims_dep),
    ):
        user_id = _scoped_user_id(claims)
        await _require_owned_bot_instance(pool, bot_id, user_id)
        return {"message": "deleted"}

    @app.post("/api/bot-instances/{bot_id}/exchanges/{config_id}/activate", dependencies=[Depends(auth_dep)])
    async def bot_instances_exchange_activate(
        bot_id: str,
        config_id: str,
        pool=Depends(_dashboard_pool),
        claims: UserClaims = Depends(auth_claims_dep),
    ):
        user_id = _scoped_user_id(claims)
        await _require_owned_bot_instance(pool, bot_id, user_id)
        # Guard live activation on same exchange account
        cfg = await _fetch_row(
            pool,
            "SELECT exchange_account_id, environment FROM bot_exchange_configs WHERE id=$1 AND bot_instance_id=$2",
            config_id,
            bot_id,
        )
        if cfg and cfg.get("environment") == "live" and cfg.get("exchange_account_id"):
            await _ensure_single_live_per_account(pool, cfg["exchange_account_id"], exclude_config_id=config_id)
        # Deactivate other configs for this bot, activate the requested one
        await pool.execute("UPDATE bot_exchange_configs SET is_active=false WHERE bot_instance_id=$1", bot_id)
        await pool.execute(
            "UPDATE bot_exchange_configs SET is_active=true, state=COALESCE(state,'ready'), updated_at=NOW() WHERE id=$1 AND bot_instance_id=$2",
            config_id,
            bot_id,
        )
        if cfg and cfg.get("exchange_account_id"):
            await pool.execute(
                "UPDATE exchange_accounts SET active_bot_id=$1 WHERE id=$2",
                bot_id,
                cfg["exchange_account_id"],
            )
        row = await _fetch_row(
            pool,
            """
            SELECT bec.*, ea.label AS exchange_account_label, ea.venue AS exchange_account_venue
            FROM bot_exchange_configs bec
            LEFT JOIN exchange_accounts ea ON ea.id = bec.exchange_account_id
            WHERE bec.id=$1
            """,
            config_id,
        )
        return {"message": "activated", "config": _format_exchange_config(row)}

    @app.post("/api/bot-instances/{bot_id}/exchanges/{config_id}/deactivate", dependencies=[Depends(auth_dep)])
    async def bot_instances_exchange_deactivate(
        bot_id: str,
        config_id: str,
        pool=Depends(_dashboard_pool),
        claims: UserClaims = Depends(auth_claims_dep),
    ):
        user_id = _scoped_user_id(claims)
        await _require_owned_bot_instance(pool, bot_id, user_id)
        cfg = await _fetch_row(
            pool,
            "SELECT exchange_account_id FROM bot_exchange_configs WHERE id=$1 AND bot_instance_id=$2",
            config_id,
            bot_id,
        )
        await pool.execute(
            "UPDATE bot_exchange_configs SET is_active=false, updated_at=NOW() WHERE id=$1 AND bot_instance_id=$2",
            config_id,
            bot_id,
        )
        if cfg and cfg.get("exchange_account_id"):
            await pool.execute(
                "UPDATE exchange_accounts SET active_bot_id=NULL WHERE id=$1 AND active_bot_id=$2",
                cfg["exchange_account_id"],
                bot_id,
            )
        row = await _fetch_row(
            pool,
            """
            SELECT bec.*, ea.label AS exchange_account_label, ea.venue AS exchange_account_venue
            FROM bot_exchange_configs bec
            LEFT JOIN exchange_accounts ea ON ea.id = bec.exchange_account_id
            WHERE bec.id=$1
            """,
            config_id,
        )
        return {"message": "deactivated", "config": _format_exchange_config(row)}

    @app.post("/api/bot-instances/{bot_id}/exchanges/{config_id}/state", dependencies=[Depends(auth_dep)])
    async def bot_instances_exchange_state(
        bot_id: str,
        config_id: str,
        data: dict[str, Any],
        pool=Depends(_dashboard_pool),
        claims: UserClaims = Depends(auth_claims_dep),
    ):
        user_id = _scoped_user_id(claims)
        await _require_owned_bot_instance(pool, bot_id, user_id)
        return {"message": "state_updated", "config": _default_exchange_config(bot_id, config_id)}

    @app.get("/api/bot-instances/{bot_id}/exchanges/{config_id}/versions", dependencies=[Depends(auth_dep)])
    async def bot_instances_exchange_versions(bot_id: str, config_id: str, limit: int = 50, pool=Depends(_dashboard_pool)):
        rows = await _fetch_rows(
            pool,
            "SELECT * FROM bot_exchange_config_versions WHERE bot_exchange_config_id=$1 ORDER BY version_number DESC LIMIT $2",
            config_id,
            limit,
        )
        return {"versions": [_format_config_version(row) for row in rows]}

    @app.get("/api/bot-instances/{bot_id}/exchanges/{config_id}/versions/{version_number}", dependencies=[Depends(auth_dep)])
    async def bot_instances_exchange_version_detail(
        bot_id: str,
        config_id: str,
        version_number: int,
        pool=Depends(_dashboard_pool),
    ):
        row = await _fetch_row(
            pool,
            "SELECT * FROM bot_exchange_config_versions WHERE bot_exchange_config_id=$1 AND version_number=$2",
            config_id,
            version_number,
        )
        return {"version": _format_config_version(row) if row else _format_config_version({})}

    @app.post(
        "/api/bot-instances/{bot_id}/exchanges/{config_id}/versions/{target_version}/rollback",
        dependencies=[Depends(auth_dep)],
    )
    async def bot_instances_exchange_rollback(
        bot_id: str,
        config_id: str,
        target_version: int,
        pool=Depends(_dashboard_pool),
        claims: UserClaims = Depends(auth_claims_dep),
    ):
        user_id = _scoped_user_id(claims)
        await _require_owned_bot_instance(pool, bot_id, user_id)
        return {"message": "rollback_queued"}

    @app.get("/api/bot-instances/{bot_id}/exchanges/{config_id}/versions/compare", dependencies=[Depends(auth_dep)])
    async def bot_instances_exchange_versions_compare(bot_id: str, config_id: str, versionA: int, versionB: int):
        return {"diff": {}}

    @app.get("/api/bot-instances/{bot_id}/exchanges/{config_id}/versions/performance", dependencies=[Depends(auth_dep)])
    async def bot_instances_exchange_versions_performance(bot_id: str, config_id: str, limit: int = 50):
        return {"versions": []}

    @app.get("/api/bot-instances/{bot_id}/exchanges/{config_id}/symbols", dependencies=[Depends(auth_dep)])
    async def bot_instances_exchange_symbols(bot_id: str, config_id: str):
        return {"symbols": []}

    @app.put("/api/bot-instances/{bot_id}/exchanges/{config_id}/symbols/{symbol}", dependencies=[Depends(auth_dep)])
    async def bot_instances_exchange_symbol_update(
        bot_id: str,
        config_id: str,
        symbol: str,
        data: dict[str, Any],
        pool=Depends(_dashboard_pool),
        claims: UserClaims = Depends(auth_claims_dep),
    ):
        user_id = _scoped_user_id(claims)
        await _require_owned_bot_instance(pool, bot_id, user_id)
        return {"message": "updated", "symbol": {"symbol": symbol}}

    @app.put("/api/bot-instances/{bot_id}/exchanges/{config_id}/symbols", dependencies=[Depends(auth_dep)])
    async def bot_instances_exchange_symbols_update(
        bot_id: str,
        config_id: str,
        data: dict[str, Any],
        pool=Depends(_dashboard_pool),
        claims: UserClaims = Depends(auth_claims_dep),
    ):
        user_id = _scoped_user_id(claims)
        await _require_owned_bot_instance(pool, bot_id, user_id)
        return {"message": "updated", "symbols": data.get("symbols", [])}

    @app.delete("/api/bot-instances/{bot_id}/exchanges/{config_id}/symbols/{symbol}", dependencies=[Depends(auth_dep)])
    async def bot_instances_exchange_symbol_delete(
        bot_id: str,
        config_id: str,
        symbol: str,
        pool=Depends(_dashboard_pool),
        claims: UserClaims = Depends(auth_claims_dep),
    ):
        user_id = _scoped_user_id(claims)
        await _require_owned_bot_instance(pool, bot_id, user_id)
        return {"message": "deleted"}

    @app.get("/api/bot-instances/policy", dependencies=[Depends(auth_dep)])
    async def bot_instances_policy(pool=Depends(_dashboard_pool)):
        row = await _fetch_row(
            pool,
            "SELECT * FROM tenant_risk_policies ORDER BY updated_at DESC LIMIT 1",
        )
        policy = _default_policy() if not row else {**_default_policy(), **row}
        return {"policy": policy}

    @app.put("/api/bot-instances/policy", dependencies=[Depends(auth_dep)])
    async def bot_instances_policy_update(data: dict[str, Any]):
        return {"message": "updated", "policy": _default_policy()}

    @app.post("/api/bot-instances/policy/enable-live", dependencies=[Depends(auth_dep)])
    async def bot_instances_policy_enable_live(pool=Depends(_dashboard_pool)):
        row = await _fetch_row(
            pool,
            "SELECT * FROM tenant_risk_policies ORDER BY updated_at DESC LIMIT 1",
        )
        policy = _default_policy() if not row else {**_default_policy(), **row}
        policy["live_trading_enabled"] = True
        return {"message": "enabled", "policy": policy}

    @app.get("/api/bot-instances/active", dependencies=[Depends(auth_dep)])
    async def bot_instances_active(
        tenant_id: str | None = None,
        bot_id: str | None = None,
        botId: str | None = None,
        pool=Depends(_dashboard_pool),
        redis_client=Depends(_redis_client),
    ):
        tenant_id, resolved_bot_id = _resolve_scope(tenant_id, bot_id or botId)
        if resolved_bot_id:
            bot_id = resolved_bot_id
        # Prefer explicitly requested bot_id; otherwise pick the most recently updated active bot
        if bot_id:
            bot_row = await _fetch_row(
                pool,
                "SELECT * FROM bot_instances WHERE id=$1 AND deleted_at IS NULL",
                bot_id,
            )
        else:
            bot_row = await _fetch_row(
                pool,
                "SELECT * FROM bot_instances WHERE is_active=true AND deleted_at IS NULL "
                "ORDER BY updated_at DESC LIMIT 1",
            )
        if not bot_row:
            return {"active": None, "symbols": [], "policy": _default_policy()}
        bot = _format_bot_instance(bot_row)
        exchange_row = await _fetch_row(
            pool,
            "SELECT bec.*, ea.venue AS exchange, ea.label AS exchange_account_label "
            "FROM bot_exchange_configs bec "
            "LEFT JOIN exchange_accounts ea ON bec.exchange_account_id = ea.id "
            "WHERE bec.bot_instance_id=$1 AND bec.is_active=true AND bec.deleted_at IS NULL "
            "ORDER BY bec.updated_at DESC LIMIT 1",
            bot_row.get("id"),
        )
        runtime_active = False
        try:
            reader = RedisSnapshotReader(redis_client)
            health = await reader.read(f"quantgambit:{tenant_id}:{bot_row.get('id')}:health:latest") or {}
            heartbeat_epoch = _coerce_epoch_timestamp(
                health.get("timestamp_epoch") or health.get("timestamp")
            )
            heartbeat_age = (time.time() - heartbeat_epoch) if heartbeat_epoch else None
            health_status = str(health.get("status") or "").strip().lower()
            services = health.get("services") if isinstance(health, dict) else {}
            python_engine = services.get("python_engine") if isinstance(services, dict) else {}
            engine_status = str((python_engine or {}).get("status") or "").strip().lower()
            runtime_active = bool(
                heartbeat_age is not None
                and heartbeat_age <= 30.0
                and (
                    health_status in {"ok", "running", "healthy"}
                    or engine_status in {"running", "online", "ok", "healthy"}
                )
            )
        except Exception:
            runtime_active = False

        if not exchange_row and runtime_active:
            # DB is stale/inactive but runtime is healthy; surface the latest config
            # so the dashboard does not show a false "stopped" state.
            exchange_row = await _fetch_row(
                pool,
                "SELECT bec.*, ea.venue AS exchange, ea.label AS exchange_account_label "
                "FROM bot_exchange_configs bec "
                "LEFT JOIN exchange_accounts ea ON bec.exchange_account_id = ea.id "
                "WHERE bec.bot_instance_id=$1 AND bec.deleted_at IS NULL "
                "ORDER BY bec.updated_at DESC LIMIT 1",
                bot_row.get("id"),
            )
        active_config = _format_exchange_config(exchange_row) if exchange_row else None
        if active_config and runtime_active:
            active_config["is_active"] = True
            active_config["state"] = "running"
            active_config["runtime_inferred_active"] = True
        symbols: list[dict[str, Any]] = []
        return {"active": active_config, "symbols": symbols, "policy": _default_policy()}

    @app.get("/api/bot-management", dependencies=[Depends(auth_dep)])
    async def bot_management():
        return {"status": "ok"}

    @app.get("/api/bots", dependencies=[Depends(auth_dep)])
    async def bots_list():
        return {"bots": []}

    @app.get("/api/data-quality/metrics", dependencies=[Depends(auth_dep)])
    async def data_quality_metrics(
        tenant_id: str | None = None,
        bot_id: str | None = None,
        symbol: str | None = None,
        timeframe: str | None = None,
        limit: int = 200,
        redis_client=Depends(_redis_client),
    ):
        tenant_id, bot_id = _resolve_scope(tenant_id, bot_id)
        reader = RedisSnapshotReader(redis_client)
        pattern = f"quantgambit:{tenant_id}:{bot_id}:quality:*:latest"
        if symbol:
            pattern = f"quantgambit:{tenant_id}:{bot_id}:quality:{symbol}:latest"
        keys = await redis_client.keys(pattern)
        metrics: list[dict[str, Any]] = []
        for key in keys[:limit]:
            payload = await reader.read(key)
            if not payload:
                continue
            payload_symbol = payload.get("symbol")
            payload_timeframe = payload.get("timeframe")
            if symbol and payload_symbol and payload_symbol != symbol:
                continue
            if timeframe and payload_timeframe and payload_timeframe != timeframe:
                continue
            metrics.append(_quality_to_metric(payload, symbol=payload_symbol))
        return {"success": True, "data": metrics, "count": len(metrics)}

    @app.get("/api/data-quality/metrics/timeseries", dependencies=[Depends(auth_dep)])
    async def data_quality_metrics_timeseries(
        tenant_id: str | None = None,
        bot_id: str | None = None,
        symbol: str | None = None,
        timeframe: str | None = None,
        limit: int = 200,
        redis_client=Depends(_redis_client),
    ):
        tenant_id, bot_id = _resolve_scope(tenant_id, bot_id)
        reader = RedisSnapshotReader(redis_client)
        metrics: list[dict[str, Any]] = []
        if symbol:
            key = f"quantgambit:{tenant_id}:{bot_id}:quality:{symbol}:history"
            history = await reader.read_history(key, limit=limit)
            for payload in history:
                payload_timeframe = payload.get("timeframe")
                if timeframe and payload_timeframe and payload_timeframe != timeframe:
                    continue
                metrics.append(_quality_to_metric(payload, symbol=symbol))
        return {"success": True, "data": metrics, "count": len(metrics)}

    @app.post("/api/data-quality/metrics", dependencies=[Depends(auth_dep)])
    async def data_quality_metrics_create(data: dict[str, Any]):
        return {"success": True, "data": data}

    @app.get("/api/data-quality/gaps", dependencies=[Depends(auth_dep)])
    async def data_quality_gaps(
        tenant_id: str | None = None,
        bot_id: str | None = None,
        symbol: str | None = None,
        timeframe: str | None = None,
        limit: int = 200,
        timescale=Depends(_timescale_reader),
    ):
        tenant_id, bot_id = _resolve_scope(tenant_id, bot_id)
        rows = await timescale.pool.fetch(
            "SELECT ts, payload FROM guardrail_events WHERE tenant_id=$1 AND bot_id=$2 ORDER BY ts DESC LIMIT $3",
            tenant_id,
            bot_id,
            limit,
        )
        gaps: list[dict[str, Any]] = []
        for row in rows:
            payload = row.get("payload") if isinstance(row, dict) else row["payload"]
            if isinstance(payload, str):
                try:
                    payload = json.loads(payload)
                except json.JSONDecodeError:
                    continue
            guard_type = payload.get("type")
            flags = payload.get("flags") or []
            if guard_type != "market_data_quality" and "orderbook_gap" not in flags:
                continue
            payload_symbol = payload.get("symbol") or "UNKNOWN"
            payload_timeframe = payload.get("timeframe")
            if symbol and payload_symbol != symbol:
                continue
            if timeframe and payload_timeframe and payload_timeframe != timeframe:
                continue
            ts = row.get("ts") if isinstance(row, dict) else row["ts"]
            gaps.append(
                {
                    "id": f"{payload_symbol}:{ts}",
                    "symbol": payload_symbol,
                    "timeframe": payload_timeframe or "1m",
                    "gap_start_time": str(ts),
                    "gap_end_time": str(ts),
                    "gap_duration_seconds": 0,
                    "expected_candles_count": None,
                    "missing_candles_count": payload.get("gap_count"),
                    "detected_at": str(ts),
                    "severity": "high" if "orderbook_gap" in flags else "medium",
                    "notes": payload.get("reason") or payload.get("detail"),
                    "created_at": str(ts),
                }
            )
        return {"success": True, "data": gaps, "count": len(gaps)}

    @app.post("/api/data-quality/gaps", dependencies=[Depends(auth_dep)])
    async def data_quality_gaps_create(data: dict[str, Any]):
        return {"success": True, "data": data}

    @app.put("/api/data-quality/gaps/{gap_id}/resolve", dependencies=[Depends(auth_dep)])
    async def data_quality_gaps_resolve(gap_id: str, data: dict[str, Any]):
        return {"success": True, "data": {"id": gap_id, **data}}

    @app.get("/api/data-quality/alerts", dependencies=[Depends(auth_dep)])
    async def data_quality_alerts(
        tenant_id: str | None = None,
        bot_id: str | None = None,
        symbol: str | None = None,
        timeframe: str | None = None,
        limit: int = 200,
        timescale=Depends(_timescale_reader),
    ):
        tenant_id, bot_id = _resolve_scope(tenant_id, bot_id)
        rows = await timescale.pool.fetch(
            "SELECT ts, payload FROM guardrail_events WHERE tenant_id=$1 AND bot_id=$2 ORDER BY ts DESC LIMIT $3",
            tenant_id,
            bot_id,
            limit,
        )
        alerts: list[dict[str, Any]] = []
        for row in rows:
            payload = row.get("payload") if isinstance(row, dict) else row["payload"]
            if isinstance(payload, str):
                try:
                    payload = json.loads(payload)
                except json.JSONDecodeError:
                    continue
            guard_type = payload.get("type")
            if guard_type not in {"market_data_quality", "trade_feed_stale", "auth_failed", "ws_error"}:
                continue
            payload_symbol = payload.get("symbol") or "UNKNOWN"
            payload_timeframe = payload.get("timeframe")
            if symbol and payload_symbol != symbol:
                continue
            if timeframe and payload_timeframe and payload_timeframe != timeframe:
                continue
            ts = row.get("ts") if isinstance(row, dict) else row["ts"]
            severity = "critical" if guard_type == "auth_failed" else "high"
            alerts.append(
                {
                    "id": f"{payload_symbol}:{ts}",
                    "symbol": payload_symbol,
                    "alert_type": "gap" if guard_type == "market_data_quality" else "high_latency",
                    "severity": severity,
                    "threshold_value": None,
                    "actual_value": payload.get("quality_score"),
                    "threshold_type": None,
                    "detected_at": str(ts),
                    "status": "open",
                    "description": payload.get("reason") or guard_type,
                    "created_at": str(ts),
                    "updated_at": str(ts),
                }
            )
        return {"success": True, "data": alerts, "count": len(alerts)}

    @app.post("/api/data-quality/alerts", dependencies=[Depends(auth_dep)])
    async def data_quality_alerts_create(data: dict[str, Any]):
        return {"success": True, "data": data}

    @app.put("/api/data-quality/alerts/{alert_id}/status", dependencies=[Depends(auth_dep)])
    async def data_quality_alerts_update(alert_id: str, data: dict[str, Any]):
        return {"success": True, "data": {"id": alert_id, **data}}

    @app.get("/api/data-quality/health", dependencies=[Depends(auth_dep)])
    async def data_quality_health(
        tenant_id: str | None = None,
        bot_id: str | None = None,
        symbol: str | None = None,
        timeframe: str | None = None,
        redis_client=Depends(_redis_client),
    ):
        tenant_id, bot_id = _resolve_scope(tenant_id, bot_id)
        reader = RedisSnapshotReader(redis_client)
        pattern = f"quantgambit:{tenant_id}:{bot_id}:quality:*:latest"
        if symbol:
            pattern = f"quantgambit:{tenant_id}:{bot_id}:quality:{symbol}:latest"
        keys = await redis_client.keys(pattern)
        items: list[dict[str, Any]] = []
        for key in keys:
            payload = await reader.read(key)
            if not payload:
                continue
            payload_symbol = payload.get("symbol") or "UNKNOWN"
            payload_timeframe = payload.get("timeframe") or "1m"
            if timeframe and payload_timeframe and payload_timeframe != timeframe:
                continue
            items.append(
                {
                    "symbol": payload_symbol,
                    "timeframe": payload_timeframe,
                    "health_status": _status_to_health(payload.get("status")),
                    "quality_score": float(payload.get("quality_score") or 0),
                    "last_metric_time": payload.get("timestamp"),
                    "last_candle_time": None,
                    "last_update_time": payload.get("timestamp"),
                    "active_gaps_count": int(payload.get("gap_count") or 0),
                    "active_alerts_count": 0,
                    "avg_latency_ms": None,
                    "updated_at": _now_iso(),
                }
            )
        return {"success": True, "data": items}

    @app.get("/api/data-quality/health/{symbol}", dependencies=[Depends(auth_dep)])
    async def data_quality_health_symbol(
        symbol: str,
        tenant_id: str | None = None,
        bot_id: str | None = None,
        redis_client=Depends(_redis_client),
    ):
        tenant_id, bot_id = _resolve_scope(tenant_id, bot_id)
        reader = RedisSnapshotReader(redis_client)
        payload = await reader.read(f"quantgambit:{tenant_id}:{bot_id}:quality:{symbol}:latest") or {}
        return {
            "success": True,
            "data": {
                "symbol": symbol,
                "timeframe": payload.get("timeframe") or "1m",
                "health_status": _status_to_health(payload.get("status")),
                "quality_score": float(payload.get("quality_score") or 0),
                "last_metric_time": payload.get("timestamp"),
                "last_candle_time": None,
                "last_update_time": payload.get("timestamp"),
                "active_gaps_count": int(payload.get("gap_count") or 0),
                "active_alerts_count": 0,
                "avg_latency_ms": None,
                "updated_at": _now_iso(),
            },
        }

    @app.get("/api/replay/sessions", dependencies=[Depends(auth_dep)])
    async def replay_sessions(
        symbol: str | None = None,
        limit: int = 50,
        tenant_id: str | None = None,
        bot_id: str | None = Query(default=None, alias="botId"),
    ):
        tenant_id, bot_id = _resolve_scope(tenant_id, bot_id)
        scoped = [
            session
            for session in _REPLAY_SESSIONS.values()
            if session.get("tenant_id") == tenant_id and session.get("bot_id") == bot_id
        ]
        if symbol:
            scoped = [session for session in scoped if session.get("symbol") == symbol]
        scoped.sort(key=lambda item: item.get("created_at") or "", reverse=True)
        return {"success": True, "data": scoped[: max(1, min(limit, 200))]}

    @app.post("/api/replay/sessions", dependencies=[Depends(auth_dep)])
    async def replay_sessions_create(
        data: dict[str, Any],
        tenant_id: str | None = None,
        bot_id: str | None = Query(default=None, alias="botId"),
    ):
        tenant_id, bot_id = _resolve_scope(tenant_id, bot_id, require_explicit=True, allow_default=False)
        now_iso = _now_iso()
        session_id = str(uuid.uuid4())
        session = {
            "id": session_id,
            "tenant_id": tenant_id,
            "bot_id": bot_id,
            "incident_id": data.get("incidentId") or data.get("incident_id"),
            "symbol": data.get("symbol"),
            "start_time": data.get("startTime") or data.get("start_time"),
            "end_time": data.get("endTime") or data.get("end_time"),
            "created_by": data.get("createdBy") or data.get("created_by"),
            "session_name": data.get("sessionName") or data.get("session_name"),
            "notes": data.get("notes"),
            "created_at": now_iso,
            "last_accessed_at": now_iso,
        }
        _REPLAY_SESSIONS[session_id] = session
        return {"success": True, "data": session}

    @app.get("/api/replay/summary", dependencies=[Depends(auth_dep)])
    async def replay_summary(
        symbol: str,
        start: str,
        end: str,
        tenant_id: str | None = None,
        bot_id: str | None = Query(default=None, alias="botId"),
        timescale=Depends(_timescale_reader),
    ):
        tenant_id, bot_id = _resolve_scope(tenant_id, bot_id)
        start_ts = _coerce_epoch_timestamp(start)
        end_ts = _coerce_epoch_timestamp(end)
        if start_ts is None or end_ts is None:
            return {
                "success": True,
                "data": {
                    "trades": {"count": 0, "totalPnl": 0.0, "avgSlippageBps": "0", "maxPnl": 0.0, "minPnl": 0.0},
                    "decisions": {"approved": 0, "rejected": 0, "avgLatencyMs": "0"},
                    "maxDrawdown": 0.0,
                },
            }
        start_dt = datetime.fromtimestamp(start_ts, timezone.utc)
        end_dt = datetime.fromtimestamp(end_ts, timezone.utc)
        symbol_aliases = _symbol_aliases(symbol)
        max_rows = max(1000, int(_safe_float(os.getenv("REPLAY_SUMMARY_MAX_ROWS"), 20000)))
        query_timeout_sec = max(0.5, float(_safe_float(os.getenv("REPLAY_SUMMARY_QUERY_TIMEOUT_SEC"), 4.0)))

        order_events: list[dict[str, Any]] = []
        decision_events: list[dict[str, Any]] = []
        if timescale and getattr(timescale, "pool", None):
            try:
                order_rows = await asyncio.wait_for(
                    timescale.pool.fetch(
                        """
                        SELECT ts, payload, symbol
                        FROM order_events
                        WHERE tenant_id=$1
                          AND bot_id=$2
                          AND symbol = ANY($3::text[])
                          AND ts >= $4
                          AND ts <= $5
                          AND lower(coalesce(payload->>'status','')) IN ('filled','closed')
                          AND (
                            lower(coalesce(payload->>'position_effect',''))='close'
                            OR lower(coalesce(payload->>'reason','')) IN (
                                'position_close','strategic_exit','stop_loss','take_profit','exchange_reconcile','exchange_backfill'
                            )
                          )
                        ORDER BY ts DESC
                        LIMIT $6
                        """,
                        tenant_id,
                        bot_id,
                        symbol_aliases,
                        start_dt,
                        end_dt,
                        max_rows,
                    ),
                    timeout=query_timeout_sec,
                )
                decision_rows = await asyncio.wait_for(
                    timescale.pool.fetch(
                        """
                        SELECT ts, payload, symbol
                        FROM decision_events
                        WHERE tenant_id=$1
                          AND bot_id=$2
                          AND symbol = ANY($3::text[])
                          AND ts >= $4
                          AND ts <= $5
                        ORDER BY ts DESC
                        LIMIT $6
                        """,
                        tenant_id,
                        bot_id,
                        symbol_aliases,
                        start_dt,
                        end_dt,
                        max_rows,
                    ),
                    timeout=query_timeout_sec,
                )
                order_events = [_merge_ts_payload(row) for row in order_rows]
                decision_events = [_merge_ts_payload(row) for row in decision_rows]
            except Exception as exc:
                log_warning("replay_summary_query_failed", error=str(exc), symbol=symbol)
                pass

        canonical_trades = _canonical_close_trades(order_events)
        trades = [
            {
                "pnl": _safe_float(
                    trade.get("net_pnl")
                    if trade.get("net_pnl") is not None
                    else trade.get("pnl"),
                    0.0,
                ),
                "slippage": _safe_float(
                    trade.get("slippage_bps"),
                    _safe_float(trade.get("slippage"), 0.0),
                ),
            }
            for trade in canonical_trades
        ]

        approved = 0
        rejected = 0
        latencies: list[float] = []
        for event in decision_events:
            outcome = _decision_outcome(event)
            if outcome == "approved":
                approved += 1
            elif outcome == "rejected":
                rejected += 1
            latency = event.get("total_latency_ms") or event.get("latency_ms")
            if latency is not None:
                latencies.append(_safe_float(latency, 0.0))

        total_pnl = float(sum(item["pnl"] for item in trades))
        avg_slippage = float(sum(item["slippage"] for item in trades) / len(trades)) if trades else 0.0
        max_pnl = max((item["pnl"] for item in trades), default=0.0)
        min_pnl = min((item["pnl"] for item in trades), default=0.0)

        running = 0.0
        peak = 0.0
        max_drawdown = 0.0
        for item in trades:
            running += item["pnl"]
            peak = max(peak, running)
            max_drawdown = min(max_drawdown, running - peak)

        return {
            "success": True,
            "data": {
                "trades": {
                    "count": len(trades),
                    "totalPnl": total_pnl,
                    "avgSlippageBps": f"{avg_slippage:.2f}",
                    "maxPnl": max_pnl,
                    "minPnl": min_pnl,
                },
                "decisions": {
                    "approved": approved,
                    "rejected": rejected,
                    "avgLatencyMs": f"{(sum(latencies) / len(latencies)):.2f}" if latencies else "0",
                },
                "maxDrawdown": abs(float(max_drawdown)),
            },
        }

    @app.get("/api/replay/features/dictionary", dependencies=[Depends(auth_dep)])
    async def replay_features_dictionary(
        symbol: str | None = None,
        tenant_id: str | None = None,
        bot_id: str | None = Query(default=None, alias="botId"),
        timescale=Depends(_timescale_reader),
    ):
        tenant_id, bot_id = _resolve_scope(tenant_id, bot_id)
        features: dict[str, dict[str, Any]] = {}
        if timescale and getattr(timescale, "pool", None):
            try:
                params: list[Any] = [tenant_id, bot_id]
                where = "WHERE tenant_id=$1 AND bot_id=$2 "
                if symbol:
                    where += "AND symbol = ANY($3::text[]) "
                    params.append(_symbol_aliases(symbol))
                rows = await timescale.pool.fetch(
                    f"""
                    SELECT payload
                    FROM decision_events
                    {where}
                    ORDER BY ts DESC
                    LIMIT 500
                    """,
                    *params,
                )
                for row in rows:
                    payload = row.get("payload") if isinstance(row, dict) else row["payload"]
                    if isinstance(payload, str):
                        try:
                            payload = json.loads(payload)
                        except Exception:
                            payload = {}
                    feature_map = payload.get("features") if isinstance(payload, dict) else {}
                    if not isinstance(feature_map, dict):
                        continue
                    for name, value in feature_map.items():
                        if name not in features:
                            features[name] = {
                                "name": name,
                                "displayName": str(name).replace("_", " ").title(),
                                "description": f"Runtime feature: {name}",
                                "unit": "",
                            }
                        if isinstance(value, (int, float)):
                            existing = features[name].get("typicalRange")
                            if existing is None:
                                features[name]["typicalRange"] = {"min": float(value), "max": float(value)}
                            else:
                                existing["min"] = min(float(existing["min"]), float(value))
                                existing["max"] = max(float(existing["max"]), float(value))
            except Exception:
                pass

        grouped = {"runtime": list(features.values())}
        return {"success": True, "data": grouped}

    @app.post("/api/replay/compare", dependencies=[Depends(auth_dep)])
    async def replay_compare(data: dict[str, Any]):
        return {
            "success": True,
            "data": {
                "baselineSessionId": data.get("baselineSessionId"),
                "compareSessionId": data.get("compareSessionId"),
                "symbol": data.get("symbol"),
                "timeRange": data.get("timeRange") or {},
                "summary": {
                    "baseline": {"tradeCount": 0, "rejectCount": 0, "decisionCount": 0, "totalPnl": 0, "avgSlippage": 0},
                    "compare": {"tradeCount": 0, "rejectCount": 0, "decisionCount": 0, "totalPnl": 0, "avgSlippage": 0},
                    "diff": {"tradeCountDelta": 0, "rejectCountDelta": 0, "pnlDelta": 0, "avgSlippageDelta": 0},
                },
                "addedEvents": [],
                "removedEvents": [],
                "changedDecisions": [],
            },
        }

    @app.post("/api/replay/annotations", dependencies=[Depends(auth_dep)])
    async def replay_annotations_create(data: dict[str, Any]):
        session_id = str(data.get("sessionId") or data.get("session_id") or "").strip()
        if not session_id:
            raise HTTPException(status_code=400, detail="sessionId is required")
        annotation = {
            "id": str(uuid.uuid4()),
            "session_id": session_id,
            "timestamp": data.get("timestamp") or _now_iso(),
            "annotation_type": data.get("annotationType") or data.get("annotation_type") or "note",
            "title": data.get("title") or "Untitled",
            "content": data.get("content") or "",
            "tags": data.get("tags") or [],
            "created_by": data.get("createdBy") or "system",
            "created_at": _now_iso(),
        }
        _REPLAY_ANNOTATIONS.setdefault(session_id, []).append(annotation)
        return {"success": True, "data": annotation}

    @app.get("/api/replay/annotations/{session_id}", dependencies=[Depends(auth_dep)])
    async def replay_annotations_list(session_id: str):
        return {"success": True, "data": _REPLAY_ANNOTATIONS.get(session_id, [])}

    @app.delete("/api/replay/annotations/{annotation_id}", dependencies=[Depends(auth_dep)])
    async def replay_annotations_delete(annotation_id: str):
        for session_id, annotations in list(_REPLAY_ANNOTATIONS.items()):
            filtered = [item for item in annotations if item.get("id") != annotation_id]
            if len(filtered) != len(annotations):
                _REPLAY_ANNOTATIONS[session_id] = filtered
                return {"success": True}
        return {"success": True}

    @app.get("/api/replay/data/{symbol}", dependencies=[Depends(auth_dep)])
    async def replay_symbol(
        symbol: str,
        start: str | None = None,
        end: str | None = None,
        tenant_id: str | None = None,
        bot_id: str | None = Query(default=None, alias="botId"),
        timescale=Depends(_timescale_reader),
    ):
        if not start or not end:
            end_ts = time.time()
            start_ts = end_ts - 4 * 3600
            start = datetime.fromtimestamp(start_ts, timezone.utc).isoformat()
            end = datetime.fromtimestamp(end_ts, timezone.utc).isoformat()
        events_response = await replay_symbol_events(
            symbol=symbol,
            start=start,
            end=end,
            limit=1000,
            offset=0,
            includeDetails=True,
            tenant_id=tenant_id,
            bot_id=bot_id,
            timescale=timescale,
        )
        events = events_response.get("events", [])
        trades = [event for event in events if event.get("type") == "trade"]
        traces = [event for event in events if event.get("type") in {"decision", "rejection"}]
        return {
            "success": True,
            "data": {
                "snapshots": [],
                "traces": traces,
                "trades": trades,
                "positions": [],
            },
        }

    @app.get("/api/replay/{symbol}/events", dependencies=[Depends(auth_dep)])
    async def replay_symbol_events(
        symbol: str,
        start: str,
        end: str,
        types: str | None = None,
        limit: int = 1000,
        offset: int = 0,
        includeDetails: bool = True,  # noqa: N803
        tenant_id: str | None = None,
        bot_id: str | None = Query(default=None, alias="botId"),
        timescale=Depends(_timescale_reader),
    ):
        del includeDetails
        tenant_id, bot_id = _resolve_scope(tenant_id, bot_id)
        start_ts = _coerce_epoch_timestamp(start)
        end_ts = _coerce_epoch_timestamp(end)
        if start_ts is None or end_ts is None:
            raise HTTPException(status_code=400, detail="start and end are required")
        start_dt = datetime.fromtimestamp(start_ts, timezone.utc)
        end_dt = datetime.fromtimestamp(end_ts, timezone.utc)
        symbol_aliases = _symbol_aliases(symbol)

        selected_types = {item.strip().lower() for item in (types or "").split(",") if item.strip()}
        events: list[dict[str, Any]] = []
        if timescale and getattr(timescale, "pool", None):
            try:
                decision_rows = await timescale.pool.fetch(
                    """
                    SELECT ts, payload, symbol, exchange
                    FROM decision_events
                    WHERE tenant_id=$1 AND bot_id=$2 AND symbol = ANY($3::text[]) AND ts >= $4 AND ts <= $5
                    ORDER BY ts ASC
                    LIMIT 5000
                    """,
                    tenant_id,
                    bot_id,
                    symbol_aliases,
                    start_dt,
                    end_dt,
                )
                for row in decision_rows:
                    payload = _merge_ts_payload(row)
                    ts_ms = _to_epoch_ms(payload.get("ts") or row.get("ts") if isinstance(row, dict) else row["ts"])
                    outcome = _decision_outcome(payload)
                    event_type = "rejection" if outcome == "rejected" else "decision"
                    event = {
                        "id": str(payload.get("decision_id") or payload.get("id") or f"decision-{ts_ms}-{uuid.uuid4().hex[:6]}"),
                        "timestamp": int(ts_ms or int(time.time() * 1000)),
                        "type": event_type,
                        "symbol": payload.get("symbol") or symbol,
                        "severity": "warning" if event_type == "rejection" else "info",
                        "data": {
                            "decision": payload.get("decision"),
                            "outcome": "rejected" if event_type == "rejection" else "approved",
                            "side": payload.get("side") or (payload.get("signal") or {}).get("side"),
                            "confidence": payload.get("confidence"),
                            "gateResults": payload.get("gateResults") or payload.get("gate_results") or payload.get("gates"),
                            "stageResults": payload.get("stageResults") or payload.get("stage_results"),
                            "featureContributions": payload.get("featureContributions") or payload.get("feature_contributions"),
                            "executionMetrics": payload.get("executionMetrics") or payload.get("execution_metrics"),
                            "rejectionReason": _extract_rejection_reason(payload),
                            "predictionBlockedReason": payload.get("prediction_blocked_reason"),
                        },
                    }
                    if not selected_types or event_type in selected_types:
                        events.append(event)

                order_rows = await timescale.pool.fetch(
                    """
                    SELECT ts, payload, symbol, exchange
                    FROM order_events
                    WHERE tenant_id=$1 AND bot_id=$2 AND symbol = ANY($3::text[]) AND ts >= $4 AND ts <= $5
                    ORDER BY ts ASC
                    LIMIT 5000
                    """,
                    tenant_id,
                    bot_id,
                    symbol_aliases,
                    start_dt,
                    end_dt,
                )
                order_events = [_merge_ts_payload(row) for row in order_rows]
                canonical_trades = _canonical_close_trades(order_events)
                for trade in canonical_trades:
                    ts_ms = _to_epoch_ms(trade.get("timestamp"))
                    status = str(trade.get("status") or "closed").lower()
                    event_type = "trade"
                    event = {
                        "id": str(trade.get("id") or f"trade-{ts_ms}-{uuid.uuid4().hex[:6]}"),
                        "timestamp": int(ts_ms or int(time.time() * 1000)),
                        "type": event_type,
                        "symbol": trade.get("symbol") or symbol,
                        "severity": "info",
                        "data": {
                            "status": status,
                            "side": trade.get("side"),
                            "size": trade.get("size"),
                            "price": trade.get("exit_price") or trade.get("entry_price"),
                            "pnl": trade.get("net_pnl") if trade.get("net_pnl") is not None else trade.get("pnl"),
                            "slippage": trade.get("slippage_bps") or trade.get("slippage"),
                            "reason": trade.get("exitReason") or trade.get("close_reason"),
                        },
                    }
                    if not selected_types or event_type in selected_types:
                        events.append(event)
            except Exception as exc:
                log_warning("replay_events_query_failed", error=str(exc), symbol=symbol)
                events = []

        events.sort(key=lambda item: int(item.get("timestamp") or 0))
        total = len(events)
        bounded_limit = max(1, min(limit, 5000))
        bounded_offset = max(0, offset)
        paged = events[bounded_offset : bounded_offset + bounded_limit]
        return {
            "success": True,
            "events": paged,
            "total": total,
            "hasMore": bounded_offset + bounded_limit < total,
        }

    @app.get("/api/replay/{symbol}/snapshot/{timestamp}", dependencies=[Depends(auth_dep)])
    async def replay_symbol_snapshot(
        symbol: str,
        timestamp: str,
        tenant_id: str | None = None,
        bot_id: str | None = Query(default=None, alias="botId"),
        timescale=Depends(_timescale_reader),
    ):
        tenant_id, bot_id = _resolve_scope(tenant_id, bot_id)
        target_ts = _coerce_epoch_timestamp(timestamp)
        if target_ts is None:
            raise HTTPException(status_code=400, detail="invalid timestamp")
        target_dt = datetime.fromtimestamp(target_ts, timezone.utc)
        symbol_aliases = _symbol_aliases(symbol)

        market_snapshot: dict[str, Any] | None = None
        nearest_decision: dict[str, Any] | None = None
        current_position: dict[str, Any] | None = None
        recent_trades: list[dict[str, Any]] = []
        if timescale and getattr(timescale, "pool", None):
            try:
                candle_row = await timescale.pool.fetchrow(
                    """
                    SELECT ts, open, high, low, close, volume
                    FROM market_candles
                    WHERE tenant_id=$1 AND bot_id=$2 AND symbol = ANY($3::text[]) AND ts <= $4
                    ORDER BY ts DESC
                    LIMIT 1
                    """,
                    tenant_id,
                    bot_id,
                    symbol_aliases,
                    target_dt,
                )
                if candle_row:
                    market_snapshot = {
                        "price": _safe_float(candle_row.get("close") if isinstance(candle_row, dict) else candle_row["close"], 0.0),
                        "volume": _safe_float(candle_row.get("volume") if isinstance(candle_row, dict) else candle_row["volume"], 0.0),
                        "spread": 0.0,
                        "depth": {},
                        "gateStates": {},
                        "regimeLabel": None,
                        "dataQualityScore": None,
                    }

                decision_row = await timescale.pool.fetchrow(
                    """
                    SELECT ts, payload
                    FROM decision_events
                    WHERE tenant_id=$1 AND bot_id=$2 AND symbol = ANY($3::text[])
                    ORDER BY ABS(EXTRACT(EPOCH FROM (ts - $4::timestamptz))) ASC
                    LIMIT 1
                    """,
                    tenant_id,
                    bot_id,
                    symbol_aliases,
                    target_dt,
                )
                if decision_row:
                    payload = decision_row.get("payload") if isinstance(decision_row, dict) else decision_row["payload"]
                    if isinstance(payload, str):
                        try:
                            payload = json.loads(payload)
                        except Exception:
                            payload = {}
                    nearest_decision = {
                        "timestamp": (decision_row.get("ts") if isinstance(decision_row, dict) else decision_row["ts"]).isoformat(),
                        "outcome": _decision_outcome(payload or {}),
                        "stageResults": (payload or {}).get("stageResults") or (payload or {}).get("stage_results"),
                        "gateResults": (payload or {}).get("gateResults") or (payload or {}).get("gate_results"),
                        "featureContributions": (payload or {}).get("featureContributions") or (payload or {}).get("feature_contributions"),
                    }

                position_row = await timescale.pool.fetchrow(
                    """
                    SELECT ts, payload
                    FROM position_events
                    WHERE tenant_id=$1 AND bot_id=$2
                    ORDER BY ts DESC
                    LIMIT 1
                    """,
                    tenant_id,
                    bot_id,
                )
                if position_row:
                    payload = position_row.get("payload") if isinstance(position_row, dict) else position_row["payload"]
                    if isinstance(payload, str):
                        try:
                            payload = json.loads(payload)
                        except Exception:
                            payload = {}
                    positions = payload.get("positions") if isinstance(payload, dict) else []
                    if isinstance(positions, list):
                        for item in positions:
                            if not isinstance(item, dict):
                                continue
                            if item.get("symbol") != symbol:
                                continue
                            current_position = {
                                "side": item.get("side"),
                                "size": _safe_float(item.get("size"), 0.0),
                                "entryPrice": _safe_float(item.get("entry_price"), 0.0),
                                "unrealizedPnl": _safe_float(item.get("unrealized_pnl"), 0.0),
                            }
                            break

                trade_rows = await timescale.pool.fetch(
                    """
                    SELECT ts, payload
                    FROM order_events
                    WHERE tenant_id=$1 AND bot_id=$2 AND symbol = ANY($3::text[]) AND ts <= $4
                    ORDER BY ts DESC
                    LIMIT 10
                    """,
                    tenant_id,
                    bot_id,
                    symbol_aliases,
                    target_dt,
                )
                trade_events = [_merge_ts_payload(row) for row in trade_rows]
                canonical_recent = _canonical_close_trades(trade_events)[:10]
                for trade in canonical_recent:
                    recent_trades.append(
                        {
                            "id": str(trade.get("id") or uuid.uuid4()),
                            "timestamp": datetime.fromtimestamp(
                                (_to_epoch_ms(trade.get("timestamp")) or int(time.time() * 1000)) / 1000.0,
                                timezone.utc,
                            ).isoformat(),
                            "side": trade.get("side") or "unknown",
                            "size": _safe_float(trade.get("size"), 0.0),
                            "price": _safe_float(trade.get("exit_price") or trade.get("entry_price"), 0.0),
                            "pnl": trade.get("net_pnl") if trade.get("net_pnl") is not None else trade.get("pnl"),
                        }
                    )
            except Exception as exc:
                log_warning("replay_snapshot_query_failed", error=str(exc), symbol=symbol)

        return {
            "success": True,
            "data": {
                "timestamp": datetime.fromtimestamp(target_ts, timezone.utc).isoformat(),
                "symbol": symbol,
                "marketSnapshot": market_snapshot,
                "nearestDecision": nearest_decision,
                "currentPosition": current_position,
                "recentTrades": recent_trades,
            },
        }

    @app.get("/api/replay/integrity", dependencies=[Depends(auth_dep)])
    async def replay_integrity(
        symbol: str,
        start: str,
        end: str,
        tenant_id: str | None = None,
        bot_id: str | None = Query(default=None, alias="botId"),
        timescale=Depends(_timescale_reader),
    ):
        tenant_id, bot_id = _resolve_scope(tenant_id, bot_id)
        start_ts = _coerce_epoch_timestamp(start)
        end_ts = _coerce_epoch_timestamp(end)
        if start_ts is None or end_ts is None:
            raise HTTPException(status_code=400, detail="start and end are required")
        start_dt = datetime.fromtimestamp(start_ts, timezone.utc)
        end_dt = datetime.fromtimestamp(end_ts, timezone.utc)
        symbol_aliases = _symbol_aliases(symbol)
        expected = max(1, int((end_ts - start_ts) / 60.0))
        actual_snapshots = 0
        data_gaps = 0
        if timescale and getattr(timescale, "pool", None):
            try:
                actual_snapshots = int(
                    await timescale.pool.fetchval(
                        """
                        SELECT COUNT(*)
                        FROM market_candles
                        WHERE tenant_id=$1 AND bot_id=$2 AND symbol = ANY($3::text[]) AND ts >= $4 AND ts <= $5
                        """,
                        tenant_id,
                        bot_id,
                        symbol_aliases,
                        start_dt,
                        end_dt,
                    )
                    or 0
                )
            except Exception as exc:
                log_warning("replay_integrity_query_failed", error=str(exc), symbol=symbol)
                actual_snapshots = 0
        data_gaps = max(0, expected - actual_snapshots)
        coverage = 100.0 * float(actual_snapshots) / float(max(1, expected))
        score = "A" if coverage >= 95 else "B" if coverage >= 80 else "C" if coverage >= 60 else "D"
        dataset_hash = hashlib.sha256(
            f"{tenant_id}:{bot_id}:{symbol}:{int(start_ts)}:{int(end_ts)}:{actual_snapshots}".encode("utf-8")
        ).hexdigest()[:16]
        return {
            "success": True,
            "data": {
                "sessionId": f"{symbol}:{int(start_ts)}:{int(end_ts)}",
                "symbol": symbol,
                "timeRange": {
                    "start": datetime.fromtimestamp(start_ts, timezone.utc).isoformat(),
                    "end": datetime.fromtimestamp(end_ts, timezone.utc).isoformat(),
                },
                "integrity": {
                    "score": score,
                    "snapshotCoverage": f"{coverage:.1f}%",
                    "dataGaps": data_gaps,
                    "expectedSnapshots": expected,
                    "actualSnapshots": actual_snapshots,
                },
                "reproducibility": {
                    "datasetHash": dataset_hash,
                    "configVersion": None,
                    "botId": bot_id,
                    "exchangeAccountId": None,
                },
            },
        }

    @app.get("/api/replay/integrity/{session_id}", dependencies=[Depends(auth_dep)])
    async def replay_integrity_session(
        session_id: str,
        tenant_id: str | None = None,
        bot_id: str | None = Query(default=None, alias="botId"),
        timescale=Depends(_timescale_reader),
    ):
        session = _REPLAY_SESSIONS.get(session_id)
        if not session:
            return {
                "success": True,
                "data": {
                    "sessionId": session_id,
                    "symbol": "",
                    "timeRange": {"start": "", "end": ""},
                    "integrity": {"score": "D", "snapshotCoverage": "0.0%", "dataGaps": 0, "expectedSnapshots": 0, "actualSnapshots": 0},
                    "reproducibility": {"datasetHash": "", "configVersion": None, "botId": bot_id or "", "exchangeAccountId": None},
                },
            }
        return await replay_integrity(
            symbol=session.get("symbol") or "",
            start=session.get("start_time") or "",
            end=session.get("end_time") or "",
            tenant_id=tenant_id,
            bot_id=bot_id,
            timescale=timescale,
        )

    @app.get("/api/reporting/templates", dependencies=[Depends(auth_dep)])
    async def reporting_templates():
        return {"templates": [], "total": 0}

    @app.post("/api/reporting/templates", dependencies=[Depends(auth_dep)])
    async def reporting_templates_create(data: dict[str, Any]):
        return {"success": True, "data": data}

    @app.get("/api/reporting/reports", dependencies=[Depends(auth_dep)])
    async def reporting_reports():
        return {"reports": [], "total": 0}

    @app.post("/api/reporting/reports", dependencies=[Depends(auth_dep)])
    async def reporting_reports_create(data: dict[str, Any]):
        return {"success": True, "data": data}

    @app.get("/api/reporting/portfolio/strategies", dependencies=[Depends(auth_dep)])
    async def reporting_portfolio_strategies():
        return {"strategies": [], "total": 0}

    @app.post("/api/reporting/portfolio/strategies", dependencies=[Depends(auth_dep)])
    async def reporting_portfolio_strategies_create(data: dict[str, Any]):
        return {"success": True, "data": data}

    @app.get("/api/reporting/portfolio/correlations", dependencies=[Depends(auth_dep)])
    async def reporting_portfolio_correlations():
        return {"correlations": [], "total": 0}

    @app.post("/api/reporting/portfolio/correlations", dependencies=[Depends(auth_dep)])
    async def reporting_portfolio_correlations_create(data: dict[str, Any]):
        return {"success": True, "data": data}

    @app.get("/api/reporting/portfolio/summary", dependencies=[Depends(auth_dep)])
    async def reporting_portfolio_summary():
        return {"summary": {}, "total": 0}

    @app.post("/api/reporting/portfolio/summary", dependencies=[Depends(auth_dep)])
    async def reporting_portfolio_summary_create(data: dict[str, Any]):
        return {"success": True, "data": data}

    # Note: /api/research/backtests endpoints are now in backtest_endpoints.py router

    @app.get("/api/research/walk-forward", dependencies=[Depends(auth_dep)])
    async def research_walk_forward():
        return {"runs": []}

    @app.get("/api/research/walk-forward/{run_id}", dependencies=[Depends(auth_dep)])
    async def research_walk_forward_detail(run_id: str):
        return {"run": {"id": run_id}}

    @app.post("/api/research/walk-forward", dependencies=[Depends(auth_dep)])
    async def research_walk_forward_create(data: dict[str, Any]):
        return {"run": data}

    # NOTE: GET /api/research/datasets is now provided by backtest_endpoints.py router

    @app.get("/api/risk/limits", dependencies=[Depends(auth_dep)])
    async def risk_limits(pool=Depends(_dashboard_pool)):
        row = await _fetch_row(
            pool,
            "SELECT * FROM tenant_risk_policies ORDER BY updated_at DESC LIMIT 1",
        )
        policy = _default_policy() if not row else {**_default_policy(), **row}
        return {
            "success": True,
            "policy": policy,
            "limits": {
                "maxPositionSize": policy.get("max_single_position_pct", 0),
                "maxDailyLoss": policy.get("max_daily_loss_pct", 0),
                "maxDrawdown": policy.get("circuit_breaker_loss_pct", 0),
                "maxExposure": policy.get("max_total_exposure_pct", 0),
                "maxConcentration": policy.get("max_per_symbol_exposure_pct", 0),
                "varLimit": 0,
            },
            "current": {
                "positionSize": 0,
                "dailyLoss": 0,
                "drawdown": 0,
                "exposure": 0,
                "concentration": 0,
                "var": 0,
            },
            "utilization": {},
        }

    @app.put("/api/risk/limits", dependencies=[Depends(auth_dep)])
    async def risk_limits_update(data: dict[str, Any]):
        return {"success": True, "policy": _default_policy(), "message": "updated"}

    @app.get("/api/risk/exposure", dependencies=[Depends(auth_dep)])
    async def risk_exposure(
        tenant_id: str | None = None,
        bot_id: str | None = None,
        redis_client=Depends(_redis_client),
    ):
        tenant_id, bot_id = _resolve_scope(tenant_id, bot_id)
        reader = RedisSnapshotReader(redis_client)
        positions = await reader.read(f"quantgambit:{tenant_id}:{bot_id}:positions:latest") or {}
        exposure_payload = _compute_exposure_snapshot(positions.get("positions") or [])
        return {"success": True, "data": exposure_payload.get("exposureBySymbol", []), "count": len(exposure_payload.get("exposureBySymbol", []))}

    @app.get("/api/risk/metrics", dependencies=[Depends(auth_dep)])
    async def risk_metrics(
        tenant_id: str | None = None,
        bot_id: str | None = None,
        limit: int = 200,
        timescale=Depends(_timescale_reader),
    ):
        tenant_id, bot_id = _resolve_scope(tenant_id, bot_id)
        rows = await timescale.pool.fetch(
            "SELECT ts, payload FROM risk_events WHERE tenant_id=$1 AND bot_id=$2 ORDER BY ts DESC LIMIT $3",
            tenant_id,
            bot_id,
            limit,
        )
        items = [_merge_ts_payload(row) for row in rows]
        return {"success": True, "data": items, "count": len(items)}

    @app.get("/api/risk/component-var", dependencies=[Depends(auth_dep)])
    async def risk_component_var():
        return {
            "success": True,
            "data": [],
            "totalVar": 0,
            "components": [],
            "total": 0,
            "timestamp": _now_iso(),
        }

    @app.get("/api/risk/correlations", dependencies=[Depends(auth_dep)])
    async def risk_correlations():
        return {"success": True, "data": []}

    @app.get("/api/risk/var", dependencies=[Depends(auth_dep)])
    async def risk_var():
        return {"success": True, "data": []}

    @app.post("/api/risk/var/historical", dependencies=[Depends(auth_dep)])
    async def risk_var_historical(data: dict[str, Any]):
        return {
            "success": True,
            "var": 0.0,
            "expectedShortfall": 0.0,
            "method": "historical",
            "confidenceLevel": data.get("confidenceLevel", 0.95),
            "timeHorizonDays": data.get("timeHorizonDays", 1),
        }

    @app.post("/api/risk/var/monte-carlo", dependencies=[Depends(auth_dep)])
    async def risk_var_monte_carlo(data: dict[str, Any]):
        return {
            "success": True,
            "var": 0.0,
            "expectedShortfall": 0.0,
            "method": "monte_carlo",
            "confidenceLevel": data.get("confidenceLevel", 0.95),
            "timeHorizonDays": data.get("timeHorizonDays", 1),
        }

    @app.get("/api/risk/var/snapshot", dependencies=[Depends(auth_dep)])
    async def risk_var_snapshot():
        return {"success": True, "snapshot": None}

    @app.get("/api/risk/var/data-status", dependencies=[Depends(auth_dep)])
    async def risk_var_data_status():
        return {"success": True, "status": "unknown"}

    @app.post("/api/risk/var/force-snapshot", dependencies=[Depends(auth_dep)])
    async def risk_var_force_snapshot(data: dict[str, Any]):
        return {"success": True, "message": "queued", "results": [], "snapshotMeta": {}}

    @app.post("/api/risk/var/trigger-refresh", dependencies=[Depends(auth_dep)])
    async def risk_var_trigger_refresh(data: dict[str, Any]):
        return {"success": True, "message": "queued", "supportedEvents": []}

    @app.get("/api/risk/scenarios/factors", dependencies=[Depends(auth_dep)])
    async def risk_scenario_factors():
        return {"success": True, "scenario": None, "factors": []}

    @app.get("/api/risk/scenarios", dependencies=[Depends(auth_dep)])
    async def risk_scenarios():
        return {"success": True, "data": []}

    @app.post("/api/risk/scenarios", dependencies=[Depends(auth_dep)])
    async def risk_scenarios_create(data: dict[str, Any]):
        return {"success": True, "data": data}

    @app.get("/api/risk/scenarios/{scenario_id}", dependencies=[Depends(auth_dep)])
    async def risk_scenarios_detail(scenario_id: str):
        return {"success": True, "scenario": {"id": scenario_id}, "factors": []}

    @app.get("/api/risk/scenarios/{scenario_id}/factors", dependencies=[Depends(auth_dep)])
    async def risk_scenarios_factors_detail(scenario_id: str):
        return {"success": True, "scenario": {"id": scenario_id}, "factors": []}

    @app.get("/api/risk/incidents", dependencies=[Depends(auth_dep)])
    async def risk_incidents(limit: int = 200, offset: int = 0):
        return {"success": True, "incidents": [], "total": 0, "limit": limit, "offset": offset}

    @app.get("/api/risk/incidents/snapshot", dependencies=[Depends(auth_dep)])
    async def risk_incidents_snapshot():
        return {"success": True, "snapshot": {}}

    @app.get("/api/risk/incidents/{incident_id}", dependencies=[Depends(auth_dep)])
    async def risk_incidents_detail(incident_id: str):
        return {"success": True, "incident": {"id": incident_id}}

    @app.post("/api/risk/incidents", dependencies=[Depends(auth_dep)])
    async def risk_incidents_create(data: dict[str, Any]):
        return {"success": True, "incident": data}

    @app.post("/api/risk/incidents/{incident_id}/acknowledge", dependencies=[Depends(auth_dep)])
    async def risk_incidents_acknowledge(incident_id: str):
        return {"success": True, "incident": {"id": incident_id}}

    @app.put("/api/risk/incidents/{incident_id}/assign", dependencies=[Depends(auth_dep)])
    async def risk_incidents_assign(incident_id: str, data: dict[str, Any]):
        return {"success": True, "incident": {"id": incident_id, **data}}

    @app.put("/api/risk/incidents/{incident_id}/resolve", dependencies=[Depends(auth_dep)])
    async def risk_incidents_resolve(incident_id: str, data: dict[str, Any]):
        return {"success": True, "incident": {"id": incident_id, **data}}

    @app.put("/api/risk/incidents/{incident_id}/status", dependencies=[Depends(auth_dep)])
    async def risk_incidents_status(incident_id: str, data: dict[str, Any]):
        return {"success": True, "incident": {"id": incident_id, **data}}

    @app.get("/api/risk/incidents/{incident_id}/timeline", dependencies=[Depends(auth_dep)])
    async def risk_incidents_timeline(incident_id: str):
        return {"success": True, "timeline": []}

    @app.post("/api/risk/incidents/{incident_id}/timeline", dependencies=[Depends(auth_dep)])
    async def risk_incidents_timeline_add(incident_id: str, data: dict[str, Any]):
        return {"success": True}

    @app.get("/api/risk/incidents/{incident_id}/evidence", dependencies=[Depends(auth_dep)])
    async def risk_incidents_evidence(incident_id: str):
        return {"success": True, "evidence": {}}

    @app.get("/api/risk/incidents/{incident_id}/export", dependencies=[Depends(auth_dep)])
    async def risk_incidents_export(incident_id: str):
        return {"success": True}

    @app.get("/api/tca/analysis", dependencies=[Depends(auth_dep)])
    async def tca_analysis():
        return {"analysis": [], "total": 0}

    @app.get("/api/tca/capacity/{profile_id}", dependencies=[Depends(auth_dep)])
    async def tca_capacity(profile_id: str):
        return {"profileId": profile_id, "curve": []}

    @app.get("/api/tca/costs/{trade_id}", dependencies=[Depends(auth_dep)])
    async def tca_costs(trade_id: str):
        return {"tradeId": trade_id, "costs": []}

    @app.get("/api/runtime/config", response_model=ConfigDriftResponse)
    async def get_runtime_config(
        tenant_id: str,
        bot_id: str,
        redis_client=Depends(_redis_client),
    ):
        reader = RedisSnapshotReader(redis_client)
        key = f"quantgambit:{tenant_id}:{bot_id}:config:drift"
        payload = await reader.read(key) or {}
        return ConfigDriftResponse(
            stored_version=payload.get("stored_version"),
            runtime_version=payload.get("runtime_version"),
            drift=bool(payload),
            timestamp=payload.get("timestamp"),
        )

    @app.get("/api/runtime/risk", response_model=RiskSizingResponse)
    async def get_runtime_risk(
        tenant_id: str,
        bot_id: str,
        redis_client=Depends(_redis_client),
    ):
        reader = RedisSnapshotReader(redis_client)
        decision_key = f"quantgambit:{tenant_id}:{bot_id}:risk:latest_decision"
        legacy_key = f"quantgambit:{tenant_id}:{bot_id}:risk:sizing"
        payload = await reader.read(decision_key) or await reader.read(legacy_key) or {}
        return RiskSizingResponse(
            status=payload.get("status"),
            rejection_reason=payload.get("rejection_reason"),
            symbol=payload.get("symbol"),
            size_usd=payload.get("size_usd"),
            risk_budget_usd=payload.get("risk_budget_usd"),
            risk_multiplier=payload.get("risk_multiplier"),
            total_exposure_usd=payload.get("total_exposure_usd"),
            total_exposure_pct=payload.get("total_exposure_pct"),
            long_exposure_usd=payload.get("long_exposure_usd"),
            short_exposure_usd=payload.get("short_exposure_usd"),
            net_exposure_usd=payload.get("net_exposure_usd"),
            net_exposure_pct=payload.get("net_exposure_pct"),
            symbol_exposure_usd=payload.get("symbol_exposure_usd"),
            strategy_exposure_usd=payload.get("strategy_exposure_usd"),
            account_equity=payload.get("account_equity"),
            overrides=payload.get("overrides"),
            limits=payload.get("limits"),
            remaining=payload.get("remaining"),
            exposure=payload.get("exposure"),
            config=payload.get("config"),
        )

    @app.get("/api/runtime/orders", response_model=SnapshotResponse)
    async def get_runtime_orders_snapshot(
        tenant_id: str,
        bot_id: str,
        redis_client=Depends(_redis_client),
    ):
        reader = RedisSnapshotReader(redis_client)
        key = f"quantgambit:{tenant_id}:{bot_id}:orders:latest"
        payload = await reader.read(key) or {}
        return SnapshotResponse(payload=payload)

    @app.get("/api/runtime/positions", response_model=SnapshotResponse)
    async def get_runtime_positions_snapshot(
        tenant_id: str,
        bot_id: str,
        redis_client=Depends(_redis_client),
        timescale=Depends(_timescale_reader),
    ):
        reader = RedisSnapshotReader(redis_client)
        key = f"quantgambit:{tenant_id}:{bot_id}:positions:latest"
        payload = await reader.read(key) or {}
        if not (isinstance(payload, dict) and payload.get("positions")):
            fallback = await timescale.load_latest_positions(tenant_id, bot_id)
            if isinstance(fallback, dict):
                payload = fallback
        return SnapshotResponse(payload=payload)

    @app.get("/api/runtime/prediction", response_model=SnapshotResponse)
    async def get_runtime_prediction_snapshot(
        tenant_id: str,
        bot_id: str,
        redis_client=Depends(_redis_client),
    ):
        reader = RedisSnapshotReader(redis_client)
        key = f"quantgambit:{tenant_id}:{bot_id}:prediction:latest"
        payload = await reader.read(key) or {}
        return SnapshotResponse(payload=payload)

    @app.get("/api/runtime/guardrails", response_model=EventsResponse)
    async def get_runtime_guardrails(
        tenant_id: str,
        bot_id: str,
        limit: int = 100,
        redis_client=Depends(_redis_client),
    ):
        reader = RedisSnapshotReader(redis_client)
        key = f"quantgambit:{tenant_id}:{bot_id}:guardrails:history"
        history = await reader.read_history(key, limit=limit)
        return EventsResponse(items=history, total=len(history))

    @app.get("/api/runtime/overrides", response_model=EventsResponse)
    async def get_runtime_overrides(
        tenant_id: str,
        bot_id: str,
        limit: int = 100,
        redis_client=Depends(_redis_client),
    ):
        reader = RedisSnapshotReader(redis_client)
        key = f"quantgambit:{tenant_id}:{bot_id}:risk:overrides"
        history = await reader.read_history(key, limit=limit)
        return EventsResponse(items=history, total=len(history))

    @app.get("/api/runtime/health", response_model=EventsResponse)
    async def get_runtime_health(
        tenant_id: str,
        bot_id: str,
        limit: int = 100,
        redis_client=Depends(_redis_client),
    ):
        reader = RedisSnapshotReader(redis_client)
        key = f"quantgambit:{tenant_id}:{bot_id}:health:history"
        history = await reader.read_history(key, limit=limit)
        return EventsResponse(items=history, total=len(history))

    @app.get("/api/history/decisions", response_model=EventsResponse, dependencies=[Depends(auth_dep)])
    async def list_decision_events(
        tenant_id: str,
        bot_id: str,
        limit: int = 200,
        symbol: str | None = None,
        timescale=Depends(_timescale_reader),
    ):
        query = (
            "SELECT ts, payload FROM decision_events WHERE tenant_id=$1 AND bot_id=$2 "
            + ("AND symbol=$3 " if symbol else "")
            + "ORDER BY ts DESC LIMIT $"
        )
        query += "4" if symbol else "3"
        params = [tenant_id, bot_id]
        if symbol:
            params.append(symbol)
        params.append(limit)
        rows = await timescale.pool.fetch(query, *params)
        items = [_merge_ts_payload(row) for row in rows]
        return EventsResponse(items=items, total=len(items))

    @app.get("/api/history/orders", response_model=EventsResponse, dependencies=[Depends(auth_dep)])
    async def list_order_events(
        tenant_id: str,
        bot_id: str,
        limit: int = 200,
        symbol: str | None = None,
        timescale=Depends(_timescale_reader),
    ):
        query = (
            "SELECT ts, payload FROM order_events WHERE tenant_id=$1 AND bot_id=$2 "
            + ("AND symbol=$3 " if symbol else "")
            + "ORDER BY ts DESC LIMIT $"
        )
        query += "4" if symbol else "3"
        params = [tenant_id, bot_id]
        if symbol:
            params.append(symbol)
        params.append(limit)
        rows = await timescale.pool.fetch(query, *params)
        items = [_merge_ts_payload(row) for row in rows]
        return EventsResponse(items=items, total=len(items))

    @app.get("/api/history/predictions", response_model=EventsResponse, dependencies=[Depends(auth_dep)])
    async def list_prediction_events(
        tenant_id: str,
        bot_id: str,
        limit: int = 200,
        symbol: str | None = None,
        timescale=Depends(_timescale_reader),
        redis_client=Depends(_redis_client),
    ):
        query = (
            "SELECT ts, payload FROM prediction_events WHERE tenant_id=$1 AND bot_id=$2 "
            + ("AND symbol=$3 " if symbol else "")
            + "ORDER BY ts DESC LIMIT $"
        )
        query += "4" if symbol else "3"
        params = [tenant_id, bot_id]
        if symbol:
            params.append(symbol)
        params.append(limit)
        rows = await timescale.pool.fetch(query, *params)
        items = [_merge_ts_payload(row) for row in rows]
        if not items:
            reader = RedisSnapshotReader(redis_client)
            history = await reader.read_history(
                f"quantgambit:{tenant_id}:{bot_id}:prediction:history",
                limit=limit,
            )
            if symbol:
                symbol_upper = symbol.upper()
                history = [
                    item for item in history
                    if str((item or {}).get("symbol") or "").upper() == symbol_upper
                ]
            items = history
        return EventsResponse(items=items, total=len(items))

    @app.get("/api/history/guardrails", response_model=EventsResponse, dependencies=[Depends(auth_dep)])
    async def list_guardrail_events(
        tenant_id: str,
        bot_id: str,
        limit: int = 200,
        timescale=Depends(_timescale_reader),
    ):
        query = (
            "SELECT ts, payload FROM guardrail_events WHERE tenant_id=$1 AND bot_id=$2 "
            "ORDER BY ts DESC LIMIT $3"
        )
        rows = await timescale.pool.fetch(query, tenant_id, bot_id, limit)
        items = [_merge_ts_payload(row) for row in rows]
        return EventsResponse(items=items, total=len(items))

    @app.get("/api/backtests", response_model=list[BacktestSummary], dependencies=[Depends(auth_dep)])
    async def list_backtests(
        tenant_id: str,
        bot_id: str,
        limit: int = 50,
        pool=Depends(_dashboard_pool),
    ):
        query = (
            "SELECT run_id, status, started_at, finished_at, config "
            "FROM backtest_runs WHERE tenant_id=$1 AND bot_id=$2 "
            "ORDER BY started_at DESC LIMIT $3"
        )
        async with pool.acquire() as conn:
            rows = await conn.fetch(query, tenant_id, bot_id, limit)
        results: list[BacktestSummary] = []
        for row in rows:
            data = dict(row)
            results.append(
                BacktestSummary(
                    id=str(data.get("run_id")),
                    name=(data.get("config") or {}).get("name") if isinstance(data.get("config"), dict) else None,
                    status=data.get("status"),
                    started_at=_to_ts(data.get("started_at")),
                    completed_at=_to_ts(data.get("finished_at")),
                )
            )
        return results

    @app.get("/api/backtests/{backtest_id}", response_model=BacktestDetail, dependencies=[Depends(auth_dep)])
    async def get_backtest(backtest_id: str, pool=Depends(_dashboard_pool)):
        async with pool.acquire() as conn:
            run = await conn.fetchrow(
                "SELECT run_id, status, started_at, finished_at, config FROM backtest_runs WHERE run_id=$1",
                backtest_id,
            )
            if not run:
                raise HTTPException(status_code=404, detail="backtest_not_found")
            metrics = await conn.fetchrow(
                "SELECT realized_pnl, total_fees, total_trades, win_rate, max_drawdown_pct, avg_slippage_bps, "
                "total_return_pct, profit_factor, avg_trade_pnl FROM backtest_metrics WHERE run_id=$1",
                backtest_id,
            )
            equity = await conn.fetch(
                "SELECT ts, equity, realized_pnl, open_positions FROM backtest_equity_curve "
                "WHERE run_id=$1 ORDER BY ts ASC",
                backtest_id,
            )
            decisions = await conn.fetch(
                "SELECT ts, symbol, decision, rejection_reason, profile_id, payload "
                "FROM backtest_decision_snapshots WHERE run_id=$1 ORDER BY ts ASC LIMIT 5000",
                backtest_id,
            )
            fills = await conn.fetch(
                "SELECT ts, symbol, side, size, entry_price, exit_price, pnl, entry_fee, exit_fee, total_fees, "
                "entry_slippage_bps, exit_slippage_bps, strategy_id, profile_id, reason "
                "FROM backtest_trades WHERE run_id=$1 ORDER BY ts ASC LIMIT 5000",
                backtest_id,
            )
            metrics_dict = dict(metrics) if metrics else {}
        equity_curve = [
            {
                "ts": _to_ts(row.get("ts")),
                "equity": float(row.get("equity")),
                "realized_pnl": float(row.get("realized_pnl")),
                "open_positions": row.get("open_positions"),
            }
            for row in equity
        ]
        return BacktestDetail(
            id=run.get("run_id"),
            name=(run.get("config") or {}).get("name") if isinstance(run.get("config"), dict) else None,
            status=run.get("status"),
            started_at=_to_ts(run.get("started_at")),
            completed_at=_to_ts(run.get("finished_at")),
            equity_curve=equity_curve,
            decisions=[dict(row) for row in decisions],
            fills=[dict(row) for row in fills],
            metrics=metrics_dict if metrics else None,
        )

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    reload_enabled = os.getenv("API_RELOAD", "").strip().lower() in {"1", "true", "yes", "on"}
    uvicorn.run(
        "quantgambit.api.app:app",
        host="0.0.0.0",
        port=int(os.getenv("API_PORT", "8080")),
        reload=reload_enabled,
    )


def _to_ts(value) -> float | None:
    if value is None:
        return None
    # Handle datetime objects from asyncpg
    if hasattr(value, 'timestamp'):
        return value.timestamp()
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _merge_ts_payload(row) -> dict:
    data = dict(row)
    payload = data.get("payload")
    # Handle string payload first (JSONB can come as string from asyncpg)
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except Exception:
            payload = {}
    elif not isinstance(payload, dict):
        payload = {}
    if "ts" not in payload and data.get("ts") is not None:
        payload["ts"] = _to_ts(data.get("ts"))
    if "symbol" not in payload and data.get("symbol") is not None:
        payload["symbol"] = data.get("symbol")
    if "exchange" not in payload and data.get("exchange") is not None:
        payload["exchange"] = data.get("exchange")
    if "bot_id" not in payload and data.get("bot_id") is not None:
        payload["bot_id"] = str(data.get("bot_id"))
    return payload
