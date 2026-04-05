"""Copilot tool: query_trade_flow.

Queries the TimescaleDB ``market_trades`` table and returns aggregated
trade flow statistics (buy/sell volume, order-flow imbalance, VWAP,
trades-per-second) for a given symbol and lookback window.
"""

from __future__ import annotations

import logging
from typing import Any

from quantgambit.copilot.models import ToolDefinition

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# JSON Schema exposed to the LLM
# ---------------------------------------------------------------------------

QUERY_TRADE_FLOW_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "symbol": {
            "type": "string",
            "description": "Trading pair symbol (e.g. BTCUSDT).",
        },
        "window_sec": {
            "type": "integer",
            "description": "Lookback window in seconds (default 60).",
            "minimum": 1,
            "maximum": 3600,
        },
    },
    "required": ["symbol"],
    "additionalProperties": False,
}


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------


async def _query_trade_flow_handler(
    *,
    pool: Any,
    tenant_id: str,
    bot_id: str,
    symbol: str,
    window_sec: int = 60,
) -> dict[str, Any]:
    """Query ``market_trades`` and return aggregated trade flow statistics."""
    window_sec = max(1, min(window_sec, 3600))

    query = (
        "SELECT "
        "COUNT(*) as trade_count, "
        "SUM(CASE WHEN payload->>'side' = 'buy' "
        "THEN (payload->>'size')::float ELSE 0 END) as buy_volume, "
        "SUM(CASE WHEN payload->>'side' = 'sell' "
        "THEN (payload->>'size')::float ELSE 0 END) as sell_volume, "
        "SUM((payload->>'price')::float * (payload->>'size')::float) "
        "/ NULLIF(SUM((payload->>'size')::float), 0) as vwap "
        "FROM market_trades "
        "WHERE tenant_id=$1 AND bot_id=$2 AND symbol=$3 "
        "AND ts >= NOW() - ($4 || ' seconds')::interval"
    )

    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                query, tenant_id, bot_id, symbol, str(window_sec),
            )
    except Exception:
        logger.warning(
            "Failed to query trade flow data from TimescaleDB", exc_info=True,
        )
        return {"error": "Failed to query trade flow data from TimescaleDB"}

    if row is None or row["trade_count"] == 0:
        return {"error": f"No recent trade data available for {symbol}"}

    trade_count: int = row["trade_count"]
    buy_volume: float = float(row["buy_volume"] or 0.0)
    sell_volume: float = float(row["sell_volume"] or 0.0)
    vwap = float(row["vwap"]) if row["vwap"] is not None else None

    total_volume = buy_volume + sell_volume
    if total_volume > 0:
        orderflow_imbalance = (buy_volume - sell_volume) / total_volume
    else:
        orderflow_imbalance = 0.0

    trades_per_second = trade_count / window_sec

    return {
        "trade_count": trade_count,
        "buy_volume": buy_volume,
        "sell_volume": sell_volume,
        "orderflow_imbalance": orderflow_imbalance,
        "vwap": vwap,
        "trades_per_second": trades_per_second,
    }


# ---------------------------------------------------------------------------
# Registration helper
# ---------------------------------------------------------------------------


def create_query_trade_flow_tool(
    pool: Any,
    tenant_id: str,
    bot_id: str,
) -> ToolDefinition:
    """Return a ``ToolDefinition`` for ``query_trade_flow`` bound to *pool*."""

    async def handler(**kwargs: Any) -> dict[str, Any]:
        return await _query_trade_flow_handler(
            pool=pool,
            tenant_id=tenant_id,
            bot_id=bot_id,
            **kwargs,
        )

    return ToolDefinition(
        name="query_trade_flow",
        description=(
            "Query recent trade flow statistics for a trading pair. "
            "Returns trade count, buy/sell volume, order-flow imbalance, "
            "VWAP, and trades-per-second for the specified lookback window. "
            "Defaults to a 60-second window."
        ),
        parameters_schema=QUERY_TRADE_FLOW_SCHEMA,
        handler=handler,
    )
