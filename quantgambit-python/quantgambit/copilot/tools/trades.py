"""Copilot tool: query_trades.

Queries the TimescaleDB ``order_events`` table and returns trade records
matching the caller's filters.
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

QUERY_TRADES_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "symbol": {
            "type": "string",
            "description": "Filter trades by trading pair symbol (e.g. BTCUSDT).",
        },
        "start_time": {
            "type": "string",
            "description": "ISO-8601 start of the time range (inclusive).",
        },
        "end_time": {
            "type": "string",
            "description": "ISO-8601 end of the time range (inclusive).",
        },
        "side": {
            "type": "string",
            "enum": ["buy", "sell"],
            "description": "Filter by trade side.",
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

def _safe_float(value: Any) -> float | None:
    """Convert *value* to float, returning ``None`` on failure."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


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


def _extract_trade(row: dict[str, Any]) -> dict[str, Any]:
    """Normalise a single ``order_events`` row into the copilot trade schema."""
    payload = _parse_payload(row.get("payload"))
    symbol = row.get("symbol") or payload.get("symbol") or "UNKNOWN"

    raw_side = str(payload.get("side") or "unknown").lower()
    side_map = {"long": "buy", "short": "sell", "buy": "buy", "sell": "sell"}
    side = side_map.get(raw_side, raw_side)

    entry_price = _safe_float(
        payload.get("entry_price")
        or payload.get("entryPrice")
        or payload.get("fill_price")
        or payload.get("fillPrice")
        or payload.get("price")
    )
    exit_price = _safe_float(
        payload.get("exit_price")
        or payload.get("exitPrice")
        or payload.get("fill_price")
        or payload.get("fillPrice")
        or payload.get("price")
    )
    size = _safe_float(
        payload.get("size")
        or payload.get("filled_size")
        or payload.get("quantity")
    )
    pnl = _safe_float(
        payload.get("net_pnl")
        or payload.get("realized_pnl")
        or payload.get("closed_pnl")
        or payload.get("pnl")
    )

    ts = row.get("ts")
    if isinstance(ts, datetime):
        timestamp = ts.isoformat()
    else:
        timestamp = str(ts) if ts is not None else None

    return {
        "symbol": symbol,
        "side": side,
        "entry_price": entry_price,
        "exit_price": exit_price,
        "size": size,
        "pnl": pnl,
        "timestamp": timestamp,
    }


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------

async def _query_trades_handler(
    *,
    pool: Any,
    tenant_id: str,
    bot_id: str,
    symbol: str | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
    side: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Query ``order_events`` and return normalised trade records."""
    where = "WHERE tenant_id=$1 AND bot_id=$2"
    params: list[Any] = [tenant_id, bot_id]

    # Only return close events (trades with PnL)
    where += (
        " AND ("
        "(payload->>'position_effect' = 'close') "
        "OR (payload->>'reason' IN "
        "('position_close', 'strategic_exit', 'stop_loss', 'take_profit'))"
        ")"
    )

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
        f"SELECT ts, payload, symbol, exchange FROM order_events {where} "
        f"ORDER BY ts DESC LIMIT ${len(params)}"
    )

    async with pool.acquire() as conn:
        rows = await conn.fetch(query, *params)

    trades = [_extract_trade(dict(r)) for r in rows]

    # Apply side filter in Python (side lives inside the JSONB payload)
    if side is not None:
        side_lower = side.lower()
        trades = [t for t in trades if t.get("side") == side_lower]

    return trades


# ---------------------------------------------------------------------------
# Registration helper
# ---------------------------------------------------------------------------

def create_query_trades_tool(
    pool: Any,
    tenant_id: str,
    bot_id: str,
) -> ToolDefinition:
    """Return a ``ToolDefinition`` for ``query_trades`` bound to *pool*."""

    async def handler(**kwargs: Any) -> list[dict[str, Any]]:
        return await _query_trades_handler(
            pool=pool,
            tenant_id=tenant_id,
            bot_id=bot_id,
            **kwargs,
        )

    return ToolDefinition(
        name="query_trades",
        description=(
            "Query recent trades from the order history. "
            "Returns trade records with symbol, side, entry/exit prices, "
            "size, PnL, and timestamp. Filters by symbol, time range, "
            "and side are optional."
        ),
        parameters_schema=QUERY_TRADES_SCHEMA,
        handler=handler,
    )
