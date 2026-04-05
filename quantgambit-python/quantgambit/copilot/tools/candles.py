"""Copilot tool: query_candles.

Queries the TimescaleDB ``market_candles`` table and returns OHLCV
candlestick records for a given symbol and timeframe.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from quantgambit.copilot.models import ToolDefinition

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# JSON Schema exposed to the LLM
# ---------------------------------------------------------------------------

QUERY_CANDLES_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "symbol": {
            "type": "string",
            "description": "Trading pair symbol (e.g. BTCUSDT).",
        },
        "timeframe_sec": {
            "type": "integer",
            "description": "Candle timeframe in seconds (default 60).",
            "minimum": 1,
        },
        "limit": {
            "type": "integer",
            "description": "Maximum number of candles to return (default 100, max 500).",
            "minimum": 1,
            "maximum": 500,
        },
    },
    "required": ["symbol"],
    "additionalProperties": False,
}


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------


async def _query_candles_handler(
    *,
    pool: Any,
    tenant_id: str,
    bot_id: str,
    symbol: str,
    timeframe_sec: int = 60,
    limit: int = 100,
) -> list[dict[str, Any]] | dict[str, str]:
    """Query ``market_candles`` and return OHLCV records ordered by ts DESC."""
    limit = max(1, min(limit, 500))

    query = (
        "SELECT ts, open, high, low, close, volume "
        "FROM market_candles "
        "WHERE tenant_id=$1 AND bot_id=$2 AND symbol=$3 AND timeframe_sec=$4 "
        "ORDER BY ts DESC "
        "LIMIT $5"
    )

    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(query, tenant_id, bot_id, symbol, timeframe_sec, limit)
    except Exception:
        logger.warning("Failed to query candle data from TimescaleDB", exc_info=True)
        return {"error": "Failed to query candle data from TimescaleDB"}

    if not rows:
        return {
            "error": f"No candle data available for {symbol} at {timeframe_sec}s timeframe"
        }

    candles: list[dict[str, Any]] = []
    for row in rows:
        ts = row["ts"]
        if isinstance(ts, datetime):
            ts_str = ts.isoformat()
        else:
            ts_str = str(ts) if ts is not None else None

        candles.append({
            "ts": ts_str,
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
            "volume": float(row["volume"]),
        })

    return candles


# ---------------------------------------------------------------------------
# Registration helper
# ---------------------------------------------------------------------------


def create_query_candles_tool(
    pool: Any,
    tenant_id: str,
    bot_id: str,
) -> ToolDefinition:
    """Return a ``ToolDefinition`` for ``query_candles`` bound to *pool*."""

    async def handler(**kwargs: Any) -> list[dict[str, Any]] | dict[str, str]:
        return await _query_candles_handler(
            pool=pool,
            tenant_id=tenant_id,
            bot_id=bot_id,
            **kwargs,
        )

    return ToolDefinition(
        name="query_candles",
        description=(
            "Query OHLCV candlestick data for a trading pair. "
            "Returns candles with timestamp, open, high, low, close, "
            "and volume. Defaults to the most recent 100 candles at "
            "60-second timeframe."
        ),
        parameters_schema=QUERY_CANDLES_SCHEMA,
        handler=handler,
    )
