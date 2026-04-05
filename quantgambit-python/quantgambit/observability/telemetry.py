"""Telemetry pipeline to Redis Streams + TimescaleDB."""

from __future__ import annotations

import time
import os
import json
from datetime import datetime, timezone
import uuid
from dataclasses import dataclass
from typing import Any, Dict, Optional
import json

from quantgambit.storage.redis_streams import Event, RedisStreamsClient, validate_event_payload
from quantgambit.ingest.time_utils import now_recv_us
from quantgambit.observability.logger import log_warning
from quantgambit.storage.redis_snapshots import RedisSnapshotWriter
from quantgambit.execution.order_statuses import normalize_order_status
from quantgambit.storage.timescale import TimescaleWriter, TelemetryRow


@dataclass(frozen=True)
class TelemetryContext:
    tenant_id: str
    bot_id: str
    exchange: Optional[str] = None


class TelemetryPipeline:
    """Publish telemetry to Redis Streams and TimescaleDB."""

    def __init__(
        self,
        redis_client: Optional[RedisStreamsClient] = None,
        timescale_writer: Optional[TimescaleWriter] = None,
        snapshot_writer: Optional[RedisSnapshotWriter] = None,
    ):
        self.redis = redis_client
        self.timescale = timescale_writer
        self.snapshots = snapshot_writer
        # DB write throttling for high-rate streams (not applied to Redis streams).
        self._last_timescale_write: Dict[tuple[str, str, str, str], float] = {}
        self._decision_db_interval_sec = _safe_float_env("TELEMETRY_DECISION_DB_INTERVAL_SEC", 0.25)
        self._prediction_db_interval_sec = _safe_float_env("TELEMETRY_PREDICTION_DB_INTERVAL_SEC", 0.50)

    async def publish_decision(self, ctx: TelemetryContext, symbol: str, payload: Dict[str, Any]) -> None:
        await self._publish("decision", "events:decision", "decision_events", ctx, symbol, payload)
        await self._snapshot_decision_history(ctx, symbol, payload)
        await self._snapshot_rejections(ctx, symbol, payload)

    async def publish_order(self, ctx: TelemetryContext, symbol: str, payload: Dict[str, Any]) -> None:
        await self._publish("order", "events:order", "order_events", ctx, symbol, payload)
        await self._snapshot_order_history(ctx, symbol, payload)
        await self._snapshot_slippage(ctx, symbol, payload)

    async def publish_prediction(self, ctx: TelemetryContext, symbol: str, payload: Dict[str, Any]) -> None:
        await self._publish("prediction", "events:prediction", "prediction_events", ctx, symbol, payload)
        await self._snapshot_prediction(ctx, symbol, payload)
        await self._snapshot_prediction_history(ctx, symbol, payload)

    async def publish_prediction_shadow(self, ctx: TelemetryContext, symbol: str, payload: Dict[str, Any]) -> None:
        """Publish shadow predictions for offline evaluation.

        This intentionally does NOT snapshot to Redis keys (avoid overwriting "latest prediction"
        views that the UI may treat as authoritative).
        """
        await self._publish("prediction_shadow", "events:prediction_shadow", "prediction_events", ctx, symbol, payload)

    async def publish_latency(self, ctx: TelemetryContext, payload: Dict[str, Any]) -> None:
        await self._publish("latency", "events:latency", "latency_events", ctx, None, payload)
        await self._snapshot_latency(ctx, payload)

    async def publish_fee(self, ctx: TelemetryContext, symbol: str, payload: Dict[str, Any]) -> None:
        await self._publish("fee", "events:fee", "fee_events", ctx, symbol, payload)

    async def publish_risk(self, ctx: TelemetryContext, payload: Dict[str, Any]) -> None:
        await self._publish("risk", "events:risk", "risk_events", ctx, None, payload)
        await self._snapshot_risk(ctx, payload)

    async def publish_positions(self, ctx: TelemetryContext, payload: Dict[str, Any]) -> None:
        await self._publish("positions", "events:positions", "position_events", ctx, None, payload)
        await self._snapshot_positions(ctx, payload)

    async def publish_position_lifecycle(
        self,
        ctx: TelemetryContext,
        symbol: str,
        event_type: str,  # "opened" or "closed"
        payload: Dict[str, Any],
    ) -> None:
        """Publish position lifecycle event (opened/closed) with full PnL data.
        
        This is the single source of truth for position PnL.
        - event_type "opened": records entry_price, size, side
        - event_type "closed": records exit_price, realized_pnl, fees, hold_time
        """
        payload["event_type"] = event_type
        payload["symbol"] = symbol
        await self._publish(
            "position_lifecycle",
            "events:position_lifecycle",
            "position_events",  # Same table, different event_type
            ctx,
            symbol,
            payload,
        )
        if event_type == "closed":
            await self._increment_trade_counts(ctx, payload)

    async def publish_orderbook(self, ctx: TelemetryContext, payload: Dict[str, Any]) -> None:
        _validate_orderbook_payload(payload)
        await self._publish("orderbook", "events:orderbook", "orderbook_events", ctx, payload.get("symbol"), payload)

    async def publish_guardrail(self, ctx: TelemetryContext, payload: Dict[str, Any]) -> None:
        try:
            _validate_guardrail_payload(payload)
        except ValueError as exc:
            log_warning("guardrail_payload_invalid", error=str(exc), payload=payload)
            return
        await self._publish("guardrail", "events:guardrail", "guardrail_events", ctx, payload.get("symbol"), payload)
        await self._snapshot_guardrail(ctx, payload)

    async def publish_health_snapshot(self, ctx: TelemetryContext, payload: Dict[str, Any]) -> None:
        await self._snapshot_health(ctx, payload)

    async def publish_order_update(self, ctx: TelemetryContext, payload: Dict[str, Any]) -> None:
        await self._publish(
            "order_update",
            "events:order_update",
            "order_update_events",
            ctx,
            payload.get("symbol"),
            payload,
        )

    async def publish_signal(self, ctx: TelemetryContext, payload: Dict[str, Any]) -> None:
        """Publish trading signal snapshot to Redis stream and signals table."""
        stream = f"quantgambit:{ctx.tenant_id}:{ctx.bot_id}:signals"
        await self._publish("signal", stream, None, ctx, payload.get("symbol"), payload)

    async def _snapshot_slippage(self, ctx: TelemetryContext, symbol: Optional[str], payload: Dict[str, Any]) -> None:
        if not self.snapshots or not symbol:
            return
        slippage = payload.get("slippage_bps")
        if slippage is None:
            return
        status = normalize_order_status(payload.get("status"))
        if status != "filled":
            return
        try:
            slippage_val = float(slippage)
        except (TypeError, ValueError):
            return
        alpha = float(os.getenv("SLIPPAGE_EMA_ALPHA", "0.2"))
        if alpha <= 0 or alpha > 1:
            alpha = 0.2
        key = f"quantgambit:{ctx.tenant_id}:{ctx.bot_id}:slippage:{symbol}"
        raw = await self.snapshots.redis.get(key)
        stats = {}
        if raw:
            try:
                if isinstance(raw, bytes):
                    raw = raw.decode("utf-8")
                stats = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                stats = {}
        prev_ema = stats.get("ema_bps")
        if prev_ema is None:
            ema = slippage_val
        else:
            try:
                prev_ema = float(prev_ema)
            except (TypeError, ValueError):
                prev_ema = slippage_val
            ema = (alpha * slippage_val) + ((1 - alpha) * prev_ema)
        count = int(stats.get("count") or 0) + 1
        snapshot = {
            "symbol": symbol,
            "ema_bps": round(ema, 4),
            "last_bps": round(slippage_val, 4),
            "count": count,
            "updated_at": time.time(),
        }
        await self.snapshots.write(key, snapshot)
        await self._write_signal(ctx, payload)

    async def _increment_trade_counts(self, ctx: TelemetryContext, payload: Dict[str, Any]) -> None:
        if not self.redis:
            return
        symbol = payload.get("symbol")
        if not symbol:
            return
        strategy_id = payload.get("strategy_id")
        key = f"quantgambit:{ctx.tenant_id}:{ctx.bot_id}:calibration:trade_counts"
        try:
            if strategy_id:
                await self.redis.redis.hincrby(key, f"{symbol}:{strategy_id}", 1)
                await self.redis.redis.hincrby(key, str(strategy_id), 1)
            await self.redis.redis.hincrby(key, str(symbol), 1)
            await self.redis.redis.hincrby(key, "total", 1)
            await self.redis.redis.hset(key, "last_updated_ts", str(time.time()))
        except Exception as exc:
            log_warning("calibration_trade_count_update_failed", error=str(exc))

    async def publish_log(self, ctx: TelemetryContext, payload: Dict[str, Any]) -> None:
        """Publish a runtime log line to Redis and timeline_events."""
        stream = f"quantgambit:{ctx.tenant_id}:{ctx.bot_id}:logs"
        await self._publish("log", stream, None, ctx, payload.get("symbol"), payload)
        await self._write_timeline(ctx, "log", payload)

    async def publish_risk_incident(self, ctx: TelemetryContext, payload: Dict[str, Any]) -> None:
        """Publish a risk incident to Redis and risk_incidents."""
        stream = f"quantgambit:{ctx.tenant_id}:{ctx.bot_id}:risk:incidents"
        await self._publish("risk_incident", stream, None, ctx, payload.get("symbol"), payload)
        await self._write_risk_incident(ctx, payload)

    async def publish_sltp_event(self, ctx: TelemetryContext, payload: Dict[str, Any]) -> None:
        """Publish stop-loss / take-profit events to Redis and sltp_events."""
        stream = f"quantgambit:{ctx.tenant_id}:{ctx.bot_id}:sltp_events"
        await self._publish("sltp_event", stream, None, ctx, payload.get("symbol"), payload)
        await self._write_sltp_event(ctx, payload)

    async def publish_market_context(self, ctx: TelemetryContext, payload: Dict[str, Any]) -> None:
        """Publish market context snapshot (spread, depth, funding, etc.)."""
        stream = f"quantgambit:{ctx.tenant_id}:{ctx.bot_id}:market_context"
        await self._publish("market_context", stream, None, ctx, payload.get("symbol"), payload)
        await self._write_market_context(ctx, payload)

    async def _publish(
        self,
        event_type: str,
        redis_stream: str,
        timescale_table: str,
        ctx: TelemetryContext,
        symbol: Optional[str],
        payload: Dict[str, Any],
    ) -> None:
        timestamp = _now_iso()
        ts_recv_us = now_recv_us()
        event_id = str(uuid.uuid4())
        payload_with_tenant = {"tenant_id": ctx.tenant_id, **payload}
        payload_normalized = _normalize_event_payload(event_type, payload_with_tenant)

        if self.redis:
            event = Event(
                event_id=event_id,
                event_type=event_type,
                schema_version="v1",
                timestamp=timestamp,
                ts_recv_us=ts_recv_us,
                ts_canon_us=ts_recv_us,
                ts_exchange_s=None,
                bot_id=ctx.bot_id,
                symbol=symbol,
                exchange=ctx.exchange,
                payload=payload_normalized,
            )
            validate_event_payload(event.__dict__)
            await self.redis.publish_event(redis_stream, event)

        if self.timescale and timescale_table:
            payload_for_db = payload_normalized

            # Orderbook payloads can be huge if they include bids/asks; strip before persisting.
            if timescale_table == "orderbook_events" and os.getenv("TELEMETRY_ORDERBOOK_DB_STRIP_LEVELS", "true").lower() in {"1", "true", "yes"}:
                payload_for_db = dict(payload_with_tenant)
                for k in ("bids", "asks", "levels", "orderbook", "raw_orderbook"):
                    payload_for_db.pop(k, None)

            # Throttle DB writes for high-rate streams (keep Redis stream unthrottled).
            interval_sec = self._timescale_interval_for_table(timescale_table, payload_for_db)
            if interval_sec > 0:
                key_suffix = self._timescale_throttle_key_suffix(timescale_table, symbol, payload_for_db)
                key = (ctx.tenant_id, ctx.bot_id, timescale_table, key_suffix)
                last = self._last_timescale_write.get(key, 0.0)
                now_s = time.time()
                if now_s - last < interval_sec:
                    return
                self._last_timescale_write[key] = now_s

            row = TelemetryRow(
                tenant_id=ctx.tenant_id,
                bot_id=ctx.bot_id,
                symbol=symbol,
                exchange=ctx.exchange,
                timestamp=timestamp,
                payload=payload_for_db,
            )
            await self.timescale.write(timescale_table, row)

        if event_type == "decision":
            await self._snapshot_decision(ctx, symbol, payload)

    def _timescale_interval_for_table(self, timescale_table: str, payload: Dict[str, Any]) -> float:
        if timescale_table == "orderbook_events":
            return _safe_float_env("TELEMETRY_ORDERBOOK_DB_INTERVAL_SEC", 1.0)
        if timescale_table == "decision_events":
            decision = str(payload.get("decision") or payload.get("result") or "").strip().lower()
            # Keep actionable trade transitions fully persisted; throttle everything else.
            if decision in {"enter", "buy", "sell", "exit", "close"}:
                return 0.0
            return self._decision_db_interval_sec
        if timescale_table == "prediction_events":
            return self._prediction_db_interval_sec
        return 0.0

    def _timescale_throttle_key_suffix(self, timescale_table: str, symbol: Optional[str], payload: Dict[str, Any]) -> str:
        if timescale_table == "prediction_events":
            source = str(payload.get("source") or payload.get("provider") or "unknown")
            direction = str(payload.get("direction") or "unknown")
            blocked_reason = str(
                payload.get("prediction_blocked_reason")
                or payload.get("abstain_reason")
                or payload.get("reason")
                or ""
            )
            return f"{symbol or ''}:{source}:{direction}:{blocked_reason}"
        return str(symbol or "")

    async def _snapshot_decision(self, ctx: TelemetryContext, symbol: Optional[str], payload: Dict[str, Any]) -> None:
        if not self.snapshots:
            return
        key = f"quantgambit:{ctx.tenant_id}:{ctx.bot_id}:decision:latest"
        normalized = _normalize_decision_payload(payload)
        snapshot = {
            "symbol": symbol,
            "exchange": ctx.exchange,
            "timestamp": _now_iso(),
            **normalized,
        }
        await self.snapshots.write(key, snapshot)

    async def _snapshot_decision_history(
        self,
        ctx: TelemetryContext,
        symbol: Optional[str],
        payload: Dict[str, Any],
    ) -> None:
        if not self.snapshots:
            return
        key = f"quantgambit:{ctx.tenant_id}:{ctx.bot_id}:decision:history"
        normalized = _normalize_decision_payload(payload)
        snapshot = {
            "symbol": symbol,
            "exchange": ctx.exchange,
            "timestamp": _now_iso(),
            **normalized,
        }
        await self.snapshots.append_history(key, snapshot, max_items=200)

    async def _write_timeline(self, ctx: TelemetryContext, event_type: str, detail: Dict[str, Any]) -> None:
        pool = getattr(self.timescale, "pool", None)
        if not pool:
            return
        try:
            # Serialize dict to JSON string for PostgreSQL
            detail_json = json.dumps(detail, separators=(",", ":"), default=str)
            async with pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO timeline_events (tenant_id, bot_id, event_type, detail, created_at) "
                    "VALUES ($1, $2, $3, $4, now())",
                    ctx.tenant_id,
                    ctx.bot_id,
                    event_type,
                    detail_json,
                )
        except Exception as exc:
            log_warning("timeline_write_failed", error=str(exc))

    async def _write_risk_incident(self, ctx: TelemetryContext, payload: Dict[str, Any]) -> None:
        pool = getattr(self.timescale, "pool", None)
        if not pool:
            return
        try:
            # Serialize dict to JSON string for PostgreSQL
            detail_json = json.dumps(payload, separators=(",", ":"), default=str)
            async with pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO risk_incidents (tenant_id, bot_id, type, symbol, limit_hit, detail, pnl, created_at) "
                    "VALUES ($1, $2, $3, $4, $5, $6, $7, now())",
                    ctx.tenant_id,
                    ctx.bot_id,
                    payload.get("type") or payload.get("reason"),
                    payload.get("symbol"),
                    payload.get("limit_hit"),
                    detail_json,
                    payload.get("pnl"),
                )
        except Exception as exc:
            log_warning("risk_incident_write_failed", error=str(exc))

    async def _write_sltp_event(self, ctx: TelemetryContext, payload: Dict[str, Any]) -> None:
        pool = getattr(self.timescale, "pool", None)
        if not pool:
            return
        try:
            # Serialize dict to JSON string for PostgreSQL
            detail_json = json.dumps(payload, separators=(",", ":"), default=str)
            async with pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO sltp_events (tenant_id, bot_id, symbol, side, event_type, pnl, detail, created_at) "
                    "VALUES ($1, $2, $3, $4, $5, $6, $7, now())",
                    ctx.tenant_id,
                    ctx.bot_id,
                    payload.get("symbol"),
                    payload.get("side"),
                    payload.get("event_type") or payload.get("eventType"),
                    payload.get("pnl"),
                    detail_json,
                )
        except Exception as exc:
            log_warning("sltp_write_failed", error=str(exc))

    async def _write_signal(self, ctx: TelemetryContext, payload: Dict[str, Any]) -> None:
        pool = getattr(self.timescale, "pool", None)
        if not pool:
            return
        try:
            decision = str(payload.get("decision") or "")
            reason = payload.get("reason")
            if isinstance(reason, (dict, list)):
                reason = str(reason)
            timeframe = payload.get("timeframe")
            if timeframe is not None and not isinstance(timeframe, str):
                timeframe = str(timeframe)
            score = payload.get("score")
            pnl = payload.get("pnl")
            # ensure payload is JSON-serializable text for asyncpg
            payload_json = json.dumps(payload, separators=(",", ":"), default=str)
            async with pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO signals (tenant_id, bot_id, symbol, decision, reason, score, timeframe, pnl, payload, created_at) "
                    "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, now())",
                    ctx.tenant_id,
                    ctx.bot_id,
                    payload.get("symbol"),
                    decision,
                    reason,
                    score,
                    timeframe,
                    pnl,
                    payload_json,
                )
        except Exception as exc:
            log_warning("signal_write_failed", error=str(exc))

    async def _write_market_context(self, ctx: TelemetryContext, payload: Dict[str, Any]) -> None:
        pool = getattr(self.timescale, "pool", None)
        if not pool:
            return
        try:
            async with pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO market_context (tenant_id, bot_id, symbol, spread_bps, depth_usd, funding_rate, iv, vol, created_at) "
                    "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, now())",
                    ctx.tenant_id,
                    ctx.bot_id,
                    payload.get("symbol"),
                    payload.get("spread_bps"),
                    payload.get("depth_usd"),
                    payload.get("funding_rate"),
                    payload.get("iv"),
                    payload.get("vol"),
                )
        except Exception as exc:
            log_warning("market_context_write_failed", error=str(exc))

    async def _snapshot_latency(self, ctx: TelemetryContext, payload: Dict[str, Any]) -> None:
        if not self.snapshots:
            return
        key = f"quantgambit:{ctx.tenant_id}:{ctx.bot_id}:latency:latest"
        snapshot = {
            "exchange": ctx.exchange,
            "timestamp": _now_iso(),
            **payload,
        }
        await self.snapshots.write(key, snapshot)

    async def _snapshot_risk(self, ctx: TelemetryContext, payload: Dict[str, Any]) -> None:
        if not self.snapshots:
            return
        key = f"quantgambit:{ctx.tenant_id}:{ctx.bot_id}:risk:latest"
        snapshot = {
            "exchange": ctx.exchange,
            "timestamp": _now_iso(),
            **payload,
        }
        await self.snapshots.write(key, snapshot)

    async def _snapshot_prediction(self, ctx: TelemetryContext, symbol: Optional[str], payload: Dict[str, Any]) -> None:
        if not self.snapshots:
            return
        key = f"quantgambit:{ctx.tenant_id}:{ctx.bot_id}:prediction:latest"
        normalized = _normalize_prediction_payload(payload)
        snapshot = {
            "symbol": symbol,
            "exchange": ctx.exchange,
            "timestamp": _now_iso(),
            **normalized,
        }
        await self.snapshots.write(key, snapshot)
        if symbol:
            per_symbol_key = f"quantgambit:{ctx.tenant_id}:{ctx.bot_id}:prediction:{symbol}:latest"
            await self.snapshots.write(per_symbol_key, snapshot)

    async def _snapshot_prediction_history(
        self,
        ctx: TelemetryContext,
        symbol: Optional[str],
        payload: Dict[str, Any],
    ) -> None:
        if not self.snapshots:
            return
        key = f"quantgambit:{ctx.tenant_id}:{ctx.bot_id}:prediction:history"
        normalized = _normalize_prediction_payload(payload)
        snapshot = {
            "symbol": symbol,
            "exchange": ctx.exchange,
            "timestamp": _now_iso(),
            **normalized,
        }
        await self.snapshots.append_history(key, snapshot, max_items=200)

    async def _snapshot_order_history(
        self,
        ctx: TelemetryContext,
        symbol: Optional[str],
        payload: Dict[str, Any],
    ) -> None:
        if not self.snapshots:
            return
        key = f"quantgambit:{ctx.tenant_id}:{ctx.bot_id}:order:history"
        normalized = _normalize_order_payload(payload)
        snapshot = {
            "symbol": symbol,
            "exchange": ctx.exchange,
            "timestamp": _now_iso(),
            **normalized,
        }
        await self.snapshots.append_history(key, snapshot, max_items=200)

    async def _snapshot_rejections(self, ctx: TelemetryContext, symbol: Optional[str], payload: Dict[str, Any]) -> None:
        if not self.snapshots:
            return
        normalized = _normalize_decision_payload(payload)
        if str(normalized.get("result") or "").upper() not in {"REJECT", "REJECTED"}:
            return
        key = f"quantgambit:{ctx.tenant_id}:{ctx.bot_id}:decision:rejections"
        snapshot = {
            "symbol": symbol,
            "exchange": ctx.exchange,
            "timestamp": _now_iso(),
            **normalized,
        }
        await self.snapshots.append_history(key, snapshot, max_items=200)

    async def _snapshot_positions(self, ctx: TelemetryContext, payload: Dict[str, Any]) -> None:
        if not self.snapshots:
            return
        key = f"quantgambit:{ctx.tenant_id}:{ctx.bot_id}:positions:latest"
        snapshot = {
            "exchange": ctx.exchange,
            "timestamp": _now_iso(),
            **payload,
        }
        await self.snapshots.write(key, snapshot)

    async def _snapshot_guardrail(self, ctx: TelemetryContext, payload: Dict[str, Any]) -> None:
        if not self.snapshots:
            return
        key = f"quantgambit:{ctx.tenant_id}:{ctx.bot_id}:guardrail:latest"
        snapshot = {
            "exchange": ctx.exchange,
            "timestamp": _now_iso(),
            **payload,
        }
        await self.snapshots.write(key, snapshot)

    async def _snapshot_health(self, ctx: TelemetryContext, payload: Dict[str, Any]) -> None:
        if not self.snapshots:
            return
        key = f"quantgambit:{ctx.tenant_id}:{ctx.bot_id}:health:latest"
        payload_copy = dict(payload or {})
        payload_ts = payload_copy.pop("timestamp", None)
        epoch_ts = _coerce_epoch(payload_ts) or time.time()

        # Read existing snapshot to preserve a small set of keys that may be
        # produced by other workers.
        existing: Dict[str, Any] = {}
        try:
            raw = await self.snapshots.redis.get(key)
            if raw:
                if isinstance(raw, bytes):
                    raw = raw.decode("utf-8")
                existing = json.loads(raw)
        except Exception:
            pass

        # Preserve position_guardian only when it indicates "running".
        # We intentionally do NOT preserve `services`, because start/stop flows
        # can leave stale "stopped" service flags that would incorrectly mark a
        # healthy runtime as degraded.
        if "position_guardian" not in payload_copy and "position_guardian" in existing:
            pg = existing.get("position_guardian")
            if isinstance(pg, dict) and str(pg.get("status") or "").strip().lower() in {"running", "ok", "healthy"}:
                payload_copy["position_guardian"] = pg

        snapshot = {
            "exchange": ctx.exchange,
            "timestamp": _now_iso(),
            "timestamp_epoch": epoch_ts,
            **payload_copy,
        }
        await self.snapshots.write(key, snapshot)


def _validate_guardrail_payload(payload: Dict[str, Any]) -> None:
    if not isinstance(payload, dict):
        raise ValueError("guardrail_payload_not_dict")
    if "type" not in payload:
        raise ValueError("guardrail_payload_missing_type")
    if not isinstance(payload.get("type"), str) or not payload.get("type"):
        raise ValueError("guardrail_payload_invalid_type")
    _validate_optional_str(payload, "symbol")
    _validate_optional_str(payload, "source")
    _validate_optional_str(payload, "reason")
    _validate_optional_str(payload, "order_id")
    _validate_optional_str(payload, "client_order_id")
    _validate_optional_int(payload, "attempt")
    _validate_optional_int(payload, "poll_attempts")


def _validate_optional_str(payload: Dict[str, Any], key: str) -> None:
    value = payload.get(key)
    if value is None:
        return
    if not isinstance(value, str):
        raise ValueError(f"guardrail_payload_invalid_{key}")


def _validate_optional_int(payload: Dict[str, Any], key: str) -> None:
    value = payload.get(key)
    if value is None:
        return
    if not isinstance(value, int):
        raise ValueError(f"guardrail_payload_invalid_{key}")


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _normalize_decision_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Ensure both decision and result keys exist for compatibility."""
    normalized: Dict[str, Any] = dict(payload or {})
    decision = str(normalized.get("decision") or "").strip().lower()
    result = str(normalized.get("result") or "").strip().upper()

    if not decision and result:
        if result in {"COMPLETE", "ACCEPTED"}:
            decision = "accepted"
        elif result in {"REJECT", "REJECTED"}:
            decision = "rejected"
        elif result == "SHADOW":
            decision = "shadow"

    if not result and decision:
        if decision == "accepted":
            result = "ACCEPTED"
        elif decision == "rejected":
            result = "REJECTED"
        elif decision == "shadow":
            result = "SHADOW"

    if decision:
        normalized["decision"] = decision
    if result:
        normalized["result"] = result
    rejection_stage = (
        normalized.get("rejection_stage")
        or normalized.get("rejected_by")
    )
    if rejection_stage:
        normalized["rejection_stage"] = str(rejection_stage)
    if "decision_context" not in normalized:
        raw_position_effect = str(normalized.get("position_effect") or "").strip().lower()
        if raw_position_effect == "close":
            normalized["decision_context"] = "exit_non_emergency"
        else:
            normalized["decision_context"] = "entry_live_signal"
    if "prediction_blocked_reason" not in normalized:
        detail = normalized.get("rejection_detail")
        if isinstance(detail, dict):
            blocked_reason = detail.get("prediction_blocked_reason")
            if blocked_reason:
                normalized["prediction_blocked_reason"] = str(blocked_reason)
    ev_gate = normalized.get("ev_gate")
    if isinstance(ev_gate, dict):
        if normalized.get("estimated_total_cost_bps") is None and ev_gate.get("total_cost_bps") is not None:
            normalized["estimated_total_cost_bps"] = ev_gate.get("total_cost_bps")
    if normalized.get("expected_gross_edge_bps") is None and normalized.get("expected_bps") is not None:
        normalized["expected_gross_edge_bps"] = normalized.get("expected_bps")
    if normalized.get("expected_net_edge_bps") is None:
        gross = _coerce_float(normalized.get("expected_gross_edge_bps"))
        cost = _coerce_float(normalized.get("estimated_total_cost_bps"))
        if gross is not None and cost is not None:
            normalized["expected_net_edge_bps"] = gross - cost
    return normalized


def _normalize_prediction_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    normalized: Dict[str, Any] = dict(payload or {})
    provider = normalized.get("provider") or normalized.get("source")
    normalized["provider"] = str(provider or "unknown")
    confidence = _coerce_float(normalized.get("confidence"))
    if confidence is not None:
        normalized["confidence"] = confidence
    direction = str(normalized.get("direction") or normalized.get("label") or "").strip().lower()
    if direction in {"up", "long", "buy"}:
        normalized["directional_label"] = "long"
    elif direction in {"down", "short", "sell"}:
        normalized["directional_label"] = "short"
    elif direction:
        normalized["directional_label"] = direction
    blocked_reason = (
        normalized.get("prediction_blocked_reason")
        or normalized.get("abstain_reason")
    )
    abstain_flag = normalized.get("abstain")
    # "abstain" may carry threshold diagnostics (dict) from ONNX providers.
    # Only treat it as a reject signal when explicitly boolean true.
    explicit_abstain = abstain_flag if isinstance(abstain_flag, bool) else False
    reject_flag = bool(normalized.get("reject")) or explicit_abstain
    if blocked_reason is None and reject_flag:
        blocked_reason = normalized.get("reason") or "prediction_reject_unspecified"
    if blocked_reason is not None:
        normalized["prediction_blocked_reason"] = str(blocked_reason)
        normalized["abstain_reason"] = str(normalized.get("abstain_reason") or blocked_reason)
    return normalized


def _normalize_order_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    normalized: Dict[str, Any] = dict(payload or {})
    exit_reason = (
        normalized.get("exit_reason")
        or normalized.get("close_reason")
        or normalized.get("closed_by")
        or normalized.get("reason")
    )
    if exit_reason is not None:
        normalized["exit_reason"] = str(exit_reason)
    if normalized.get("close_category") is None:
        reason = str(exit_reason or "").strip().lower()
        if "breakeven" in reason:
            normalized["close_category"] = "breakeven"
        elif "guardian" in reason and ("max_age" in reason or "age" in reason):
            normalized["close_category"] = "guardian_age"
        elif "guardian" in reason and ("time" in reason or "hold" in reason):
            normalized["close_category"] = "guardian_time"
        elif any(token in reason for token in {"risk", "emergency", "critical", "liquidation", "stop_loss"}):
            normalized["close_category"] = "risk"
        elif str(normalized.get("position_effect") or "").strip().lower() == "close":
            normalized["close_category"] = "signal_exit"
    if normalized.get("entry_to_exit_latency_sec") is None:
        hold_time = _coerce_float(normalized.get("hold_time_sec"))
        if hold_time is None:
            entry_ts = _coerce_float(normalized.get("entry_timestamp"))
            exit_ts = _coerce_float(normalized.get("exit_timestamp"))
            if entry_ts is not None and exit_ts is not None:
                if entry_ts > 1e12:
                    entry_ts /= 1000.0
                if exit_ts > 1e12:
                    exit_ts /= 1000.0
                hold_time = max(0.0, exit_ts - entry_ts)
        if hold_time is not None:
            normalized["entry_to_exit_latency_sec"] = hold_time
    liquidity, source = _normalize_liquidity_metadata(normalized)
    if liquidity in {"maker", "taker"}:
        normalized["liquidity"] = liquidity
        normalized["liquidity_type"] = liquidity
        normalized["maker_taker"] = liquidity
        normalized["is_maker"] = liquidity == "maker"
        normalized["liquidity_source"] = source
    return normalized


def _normalize_event_payload(event_type: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    if event_type == "decision":
        return _normalize_decision_payload(payload)
    if event_type in {"prediction", "prediction_shadow"}:
        return _normalize_prediction_payload(payload)
    if event_type in {"order", "order_update"}:
        return _normalize_order_payload(payload)
    return payload


def _coerce_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_float_env(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return float(default)
    try:
        value = float(raw)
        return value if value >= 0 else float(default)
    except (TypeError, ValueError):
        return float(default)


def _normalize_liquidity_metadata(payload: Dict[str, Any]) -> tuple[Optional[str], Optional[str]]:
    is_maker = payload.get("is_maker")
    if isinstance(is_maker, bool):
        return ("maker" if is_maker else "taker"), "explicit_bool"

    explicit = payload.get("liquidity") or payload.get("liquidity_type") or payload.get("maker_taker")
    explicit_norm = _coerce_liquidity(explicit)
    if explicit_norm in {"maker", "taker"}:
        return explicit_norm, "explicit_text"

    post_only = payload.get("post_only")
    if isinstance(post_only, bool):
        return ("maker" if post_only else "taker"), "heuristic_post_only"
    entry_post_only = payload.get("entry_post_only")
    if isinstance(entry_post_only, bool):
        return ("maker" if entry_post_only else "taker"), "heuristic_entry_post_only"

    order_type = str(payload.get("order_type") or "").strip().lower()
    if order_type == "market":
        return "taker", "heuristic_order_type_market"
    if order_type == "limit" and bool(payload.get("post_only")):
        return "maker", "heuristic_order_type_limit_post_only"
    return None, None


def _coerce_liquidity(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip().lower()
    if not text:
        return None
    if "maker" in text:
        return "maker"
    if "taker" in text:
        return "taker"
    return None


def _coerce_epoch(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
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


def _validate_orderbook_payload(payload: Dict[str, Any]) -> None:
    required = {"symbol", "timestamp", "bid_depth_usd", "ask_depth_usd", "orderbook_imbalance"}
    missing = required - set(payload.keys())
    if missing:
        raise ValueError(f"missing_fields:{','.join(sorted(missing))}")
