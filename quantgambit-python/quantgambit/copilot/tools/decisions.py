"""Copilot tool: query_decision_traces.

Queries the TimescaleDB ``decision_events`` table and returns decision trace
records matching the caller's filters.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from quantgambit.copilot.models import ToolDefinition

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# JSON Schema exposed to the LLM
# ---------------------------------------------------------------------------

QUERY_DECISION_TRACES_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "symbol": {
            "type": "string",
            "description": "Filter decision traces by trading pair symbol (e.g. BTCUSDT).",
        },
        "start_time": {
            "type": "string",
            "description": "ISO-8601 start of the time range (inclusive).",
        },
        "end_time": {
            "type": "string",
            "description": "ISO-8601 end of the time range (inclusive).",
        },
        "limit": {
            "type": "integer",
            "description": "Maximum number of records to return (default 50).",
            "default": 50,
        },
    },
    "additionalProperties": False,
}


# ---------------------------------------------------------------------------
# Payload helpers
# ---------------------------------------------------------------------------

def _parse_payload(raw: Any) -> dict[str, Any]:
    """Ensure *raw* is a dict, parsing JSON strings if needed."""
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return {}
    return {}


def _safe_float(value: Any) -> float | None:
    """Convert *value* to float, returning ``None`` on failure."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _extract_decision(row: dict[str, Any]) -> dict[str, Any]:
    """Normalise a single ``decision_events`` row into the copilot decision schema."""
    payload = _parse_payload(row.get("payload"))
    symbol = row.get("symbol") or payload.get("symbol") or "UNKNOWN"

    # stages_executed is stored as gates_passed in the pipeline payload
    stages_executed: list[str] = payload.get("gates_passed") or []

    rejection_reason: str | None = payload.get("rejection_reason")

    # signal_confidence may live in the snapshot or prediction data
    signal_confidence = _safe_float(
        payload.get("signal_confidence")
        or (payload.get("snapshot") or {}).get("signal_confidence")
    )

    result = payload.get("result")  # "COMPLETE" or "REJECT"

    ts = row.get("ts")
    if isinstance(ts, datetime):
        timestamp = ts.isoformat()
    else:
        timestamp = str(ts) if ts is not None else None

    return {
        "symbol": symbol,
        "stages_executed": stages_executed,
        "rejection_reason": rejection_reason,
        "signal_confidence": signal_confidence,
        "result": result,
        "timestamp": timestamp,
    }


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------

async def _query_decision_traces_handler(
    *,
    pool: Any,
    tenant_id: str,
    bot_id: str,
    symbol: str | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Query ``decision_events`` and return normalised decision trace records."""
    where = "WHERE tenant_id=$1 AND bot_id=$2"
    params: list[Any] = [tenant_id, bot_id]

    if symbol is not None:
        params.append(symbol)
        where += f" AND symbol=${len(params)}"

    if start_time is not None:
        try:
            dt = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
        except ValueError:
            dt = None
        if dt is not None:
            params.append(dt)
            where += f" AND ts >= ${len(params)}"

    if end_time is not None:
        try:
            dt = datetime.fromisoformat(end_time.replace("Z", "+00:00"))
        except ValueError:
            dt = None
        if dt is not None:
            params.append(dt)
            where += f" AND ts <= ${len(params)}"

    # Clamp limit to a sane range
    limit = max(1, min(limit, 500))
    params.append(limit)

    query = (
        f"SELECT ts, payload, symbol FROM decision_events {where} "
        f"ORDER BY ts DESC LIMIT ${len(params)}"
    )

    async with pool.acquire() as conn:
        rows = await conn.fetch(query, *params)

    return [_extract_decision(dict(r)) for r in rows]


# ---------------------------------------------------------------------------
# Registration helper
# ---------------------------------------------------------------------------

def create_query_decision_traces_tool(
    pool: Any,
    tenant_id: str,
    bot_id: str,
) -> ToolDefinition:
    """Return a ``ToolDefinition`` for ``query_decision_traces`` bound to *pool*."""

    async def handler(**kwargs: Any) -> list[dict[str, Any]]:
        return await _query_decision_traces_handler(
            pool=pool,
            tenant_id=tenant_id,
            bot_id=bot_id,
            **kwargs,
        )

    return ToolDefinition(
        name="query_decision_traces",
        description=(
            "Query decision pipeline traces from the decision history. "
            "Returns decision records with stages executed, rejection reason, "
            "signal confidence, and result (COMPLETE or REJECT). "
            "Filters by symbol and time range are optional."
        ),
        parameters_schema=QUERY_DECISION_TRACES_SCHEMA,
        handler=handler,
    )
