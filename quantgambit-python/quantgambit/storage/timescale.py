"""TimescaleDB writer for telemetry events."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import math
from typing import Any, Dict, Optional, Union
import asyncpg


@dataclass(frozen=True)
class TelemetryRow:
    tenant_id: str
    bot_id: str
    symbol: Optional[str]
    exchange: Optional[str]
    timestamp: Union[str, datetime]
    payload: Dict[str, Any]


@dataclass(frozen=True)
class CandleRow:
    tenant_id: str
    bot_id: str
    symbol: str
    exchange: str
    timeframe_sec: int
    timestamp: Union[str, datetime]
    open: float
    high: float
    low: float
    close: float
    volume: float


class TimescaleWriter:
    """Write telemetry events into TimescaleDB tables."""

    def __init__(self, pool):
        self.pool = pool

    async def write(self, table: str, row: TelemetryRow) -> None:
        async with self.pool.acquire() as conn:
            if table == "order_events":
                await self._write_order_event(conn, row)
                return
            query = (
                f"INSERT INTO {table} (tenant_id, bot_id, symbol, exchange, ts, payload) "
                "VALUES ($1, $2, $3, $4, $5, $6)"
            )
            await conn.execute(
                query,
                row.tenant_id,
                row.bot_id,
                row.symbol,
                row.exchange,
                _coerce_timestamp(row.timestamp),
                _coerce_payload(row.payload),
            )

    async def _write_order_event(self, conn, row: TelemetryRow) -> None:
        payload = _extract_order_event_payload_fields(row.payload)
        event_ts = _coerce_timestamp(row.timestamp)
        query = (
            "INSERT INTO order_events "
            "(tenant_id, bot_id, symbol, exchange, ts, order_id, client_order_id, event_type, status, reason, "
            "fill_price, filled_size, fee_usd, payload) "
            "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14)"
        )
        legacy_query = (
            "INSERT INTO order_events (tenant_id, bot_id, symbol, exchange, ts, payload) "
            "VALUES ($1, $2, $3, $4, $5, $6)"
        )
        try:
            await conn.execute(
                query,
                row.tenant_id,
                row.bot_id,
                row.symbol,
                row.exchange,
                event_ts,
                payload.get("order_id"),
                payload.get("client_order_id"),
                payload.get("event_type"),
                payload.get("status"),
                payload.get("reason"),
                payload.get("fill_price"),
                payload.get("filled_size"),
                payload.get("fee_usd"),
                _coerce_payload(row.payload),
            )
        except asyncpg.UndefinedColumnError:
            await conn.execute(
                legacy_query,
                row.tenant_id,
                row.bot_id,
                row.symbol,
                row.exchange,
                event_ts,
                _coerce_payload(row.payload),
            )

    async def write_decision(self, row: TelemetryRow) -> None:
        await self.write("decision_events", row)

    async def write_order(self, row: TelemetryRow) -> None:
        await self.write("order_events", row)

    async def write_prediction(self, row: TelemetryRow) -> None:
        await self.write("prediction_events", row)

    async def write_latency(self, row: TelemetryRow) -> None:
        await self.write("latency_events", row)

    async def write_fee(self, row: TelemetryRow) -> None:
        await self.write("fee_events", row)

    async def write_candle(self, row: CandleRow) -> None:
        query = (
            "INSERT INTO market_candles (tenant_id, bot_id, symbol, exchange, timeframe_sec, ts, open, high, low, close, volume) "
            "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)"
        )
        async with self.pool.acquire() as conn:
            await conn.execute(
                query,
                row.tenant_id,
                row.bot_id,
                row.symbol,
                row.exchange,
                row.timeframe_sec,
                _coerce_timestamp(row.timestamp),
                row.open,
                row.high,
                row.low,
                row.close,
                row.volume,
            )


class NullTimescaleWriter:
    """No-op Timescale writer for environments without a DB."""

    async def write(self, table: str, row: TelemetryRow) -> None:  # pragma: no cover - trivial
        return None

    async def write_decision(self, row: TelemetryRow) -> None:  # pragma: no cover - trivial
        return None

    async def write_order(self, row: TelemetryRow) -> None:  # pragma: no cover - trivial
        return None

    async def write_prediction(self, row: TelemetryRow) -> None:  # pragma: no cover - trivial
        return None

    async def write_latency(self, row: TelemetryRow) -> None:  # pragma: no cover - trivial
        return None

    async def write_fee(self, row: TelemetryRow) -> None:  # pragma: no cover - trivial
        return None

    async def write_candle(self, row: CandleRow) -> None:  # pragma: no cover - trivial
        return None


class TimescaleReader:
    """Read telemetry snapshots from TimescaleDB tables."""

    def __init__(self, pool):
        self.pool = pool

    async def load_latest_positions(self, tenant_id: str, bot_id: str) -> Optional[Dict[str, Any]]:
        query = (
            "SELECT payload FROM position_events "
            "WHERE tenant_id=$1 AND bot_id=$2 "
            "ORDER BY ts DESC, (payload::jsonb->>'count')::int DESC LIMIT 1"
        )
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(query, tenant_id, bot_id)
        if not row:
            return None
        payload = row.get("payload") if isinstance(row, dict) else row["payload"]
        if isinstance(payload, str):
            try:
                return json.loads(payload)
            except json.JSONDecodeError:
                return None
        return payload

    async def load_latest_order_event(self, tenant_id: str, bot_id: str) -> Optional[Dict[str, Any]]:
        query = (
            "SELECT payload FROM order_events "
            "WHERE tenant_id=$1 AND bot_id=$2 "
            "ORDER BY ts DESC LIMIT 1"
        )
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(query, tenant_id, bot_id)
        if not row:
            return None
        payload = row.get("payload") if isinstance(row, dict) else row["payload"]
        if isinstance(payload, str):
            try:
                return json.loads(payload)
            except json.JSONDecodeError:
                return None
        return payload

    async def load_latest_order_intent_for_symbol(
        self,
        tenant_id: str,
        bot_id: str,
        symbol: str,
    ) -> Optional[Dict[str, Any]]:
        query = (
            "SELECT stop_loss, take_profit, entry_price, side, size, "
            "client_order_id, decision_id, strategy_id, profile_id, snapshot_metrics "
            "FROM order_intents "
            "WHERE tenant_id=$1 AND bot_id=$2 AND symbol=$3 "
            "AND (client_order_id IS NULL OR client_order_id NOT LIKE 'qg-guard-%') "
            "AND (COALESCE(snapshot_metrics->>'post_only', 'false') = 'true' OR client_order_id LIKE '%:m%') "
            "ORDER BY created_at DESC LIMIT 1"
        )
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(query, tenant_id, bot_id, symbol)
        if not row:
            return None
        return dict(row)


def _coerce_timestamp(value: Union[str, datetime]) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        cleaned = value.replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(cleaned)
        except ValueError:
            pass
    return datetime.now(timezone.utc)


def _coerce_payload(value: Dict[str, Any] | str) -> str:
    if isinstance(value, str):
        return value
    sanitized = _sanitize_nans(value)
    return json.dumps(sanitized, separators=(",", ":"), sort_keys=True, allow_nan=False)


def _sanitize_nans(value: Any) -> Any:
    """Recursively replace NaN/Infinity with None for JSON compatibility."""
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    if isinstance(value, dict):
        return {k: _sanitize_nans(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_sanitize_nans(v) for v in value]
    return value


def _extract_order_event_payload_fields(payload: Dict[str, Any]) -> Dict[str, Any]:
    normalized = dict(payload or {})
    return {
        "order_id": _clean_text(normalized.get("order_id") or normalized.get("id")),
        "client_order_id": _clean_text(
            normalized.get("client_order_id")
            or normalized.get("clientOrderId")
            or normalized.get("orderLinkId")
            or normalized.get("newClientOrderId")
        ),
        "event_type": _clean_text(normalized.get("event_type") or normalized.get("source")),
        "status": _clean_text(normalized.get("status") or normalized.get("order_status")),
        "reason": _clean_text(
            normalized.get("reason")
            or normalized.get("rejection_reason")
            or normalized.get("error_message")
            or normalized.get("last_error")
        ),
        "fill_price": _coerce_optional_float(normalized.get("fill_price") or normalized.get("price") or normalized.get("average")),
        "filled_size": _coerce_optional_float(
            normalized.get("filled_size")
            or normalized.get("fill_qty")
            or normalized.get("filled")
            or normalized.get("amount")
        ),
        "fee_usd": _coerce_optional_float(
            normalized.get("fee_usd")
            or normalized.get("fee")
            or normalized.get("total_fees_usd")
        ),
    }


def _clean_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _coerce_optional_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
