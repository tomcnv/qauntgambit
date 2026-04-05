"""Copilot tool: query_market_context.

Queries TimescaleDB ``market_context`` table for recent market
microstructure data (spread, depth, funding rate, IV, vol) per symbol.
"""

from __future__ import annotations

import logging
from typing import Any

from quantgambit.copilot.models import ToolDefinition

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# JSON Schema exposed to the LLM
# ---------------------------------------------------------------------------

QUERY_MARKET_CONTEXT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "symbol": {
            "type": "string",
            "description": "Trading pair symbol (e.g. BTCUSDT). Omit for all symbols.",
        },
        "limit": {
            "type": "integer",
            "description": "Max rows to return (default 10).",
            "minimum": 1,
            "maximum": 100,
        },
    },
    "additionalProperties": False,
}


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------

async def _query_market_context_handler(
    *,
    pool: Any,
    tenant_id: str,
    bot_id: str,
    symbol: str | None = None,
    limit: int = 10,
) -> list[dict[str, Any]] | dict[str, Any]:
    """Return recent market context rows from TimescaleDB."""

    query = (
        "SELECT symbol, ts, spread_bps, depth_usd, funding_rate, iv, vol "
        "FROM market_context "
        "WHERE ($1::text IS NULL OR symbol = $1) "
        "ORDER BY ts DESC "
        "LIMIT $2"
    )

    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(query, symbol, limit)
    except Exception:
        logger.warning("query_market_context: DB query failed", exc_info=True)
        return {"error": "Failed to query market context from TimescaleDB"}

    if not rows:
        return []

    return [
        {
            "symbol": row["symbol"],
            "ts": row["ts"].isoformat(),
            "spread_bps": float(row["spread_bps"]),
            "depth_usd": float(row["depth_usd"]),
            "funding_rate": float(row["funding_rate"]),
            "iv": float(row["iv"]),
            "vol": float(row["vol"]),
        }
        for row in rows
    ]


# ---------------------------------------------------------------------------
# Registration helper
# ---------------------------------------------------------------------------

def create_query_market_context_tool(
    pool: Any,
    tenant_id: str,
    bot_id: str,
) -> ToolDefinition:
    """Return a ``ToolDefinition`` for ``query_market_context`` bound to *pool*."""

    async def handler(**kwargs: Any) -> list[dict[str, Any]] | dict[str, Any]:
        return await _query_market_context_handler(
            pool=pool,
            tenant_id=tenant_id,
            bot_id=bot_id,
            **kwargs,
        )

    return ToolDefinition(
        name="query_market_context",
        description=(
            "Query recent market microstructure data. "
            "Returns rows with spread (bps), depth (USD), funding rate, "
            "implied volatility, and realized volatility. "
            "Optionally filter by symbol and limit the number of rows."
        ),
        parameters_schema=QUERY_MARKET_CONTEXT_SCHEMA,
        handler=handler,
    )
