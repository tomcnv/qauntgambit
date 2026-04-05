"""Copilot tool: query_positions.

Queries Redis for current open positions and optionally falls back to
TimescaleDB ``position_events`` for recent position history.  The primary
source of truth for *current* positions is the Redis snapshot at
``quantgambit:{tenant_id}:{bot_id}:positions:latest``.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from quantgambit.copilot.models import ToolDefinition

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# JSON Schema exposed to the LLM
# ---------------------------------------------------------------------------

QUERY_POSITIONS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "symbol": {
            "type": "string",
            "description": "Filter positions by trading pair symbol (e.g. BTCUSDT).",
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


def _compute_unrealized_pnl(
    side: str,
    entry_price: float | None,
    current_price: float | None,
    size: float | None,
) -> float | None:
    """Compute unrealized PnL from position fields."""
    if entry_price is None or current_price is None or size is None:
        return None
    if entry_price <= 0 or size <= 0:
        return None
    if side in ("long", "buy"):
        return (current_price - entry_price) * size
    if side in ("short", "sell"):
        return (entry_price - current_price) * size
    return None


def _extract_position(pos: dict[str, Any]) -> dict[str, Any]:
    """Normalise a single Redis position record into the copilot position schema."""
    symbol = pos.get("symbol") or "UNKNOWN"

    raw_side = str(pos.get("side") or "unknown").lower()
    side_map = {"long": "long", "short": "short", "buy": "long", "sell": "short"}
    side = side_map.get(raw_side, raw_side)

    size = _safe_float(pos.get("size"))
    entry_price = _safe_float(pos.get("entry_price") or pos.get("entryPrice"))
    # Redis positions use reference_price as the current market price
    current_price = _safe_float(
        pos.get("reference_price")
        or pos.get("current_price")
        or pos.get("currentPrice")
        or pos.get("mark_price")
    )
    stop_loss = _safe_float(pos.get("stop_loss") or pos.get("stopLoss"))
    take_profit = _safe_float(pos.get("take_profit") or pos.get("takeProfit"))

    # Prefer pre-computed unrealized_pnl if available, otherwise compute
    unrealized_pnl = _safe_float(
        pos.get("unrealized_pnl") or pos.get("unrealizedPnl") or pos.get("pnl")
    )
    if unrealized_pnl is None:
        unrealized_pnl = _compute_unrealized_pnl(side, entry_price, current_price, size)

    return {
        "symbol": symbol,
        "side": side,
        "size": size,
        "entry_price": entry_price,
        "current_price": current_price,
        "unrealized_pnl": unrealized_pnl,
        "stop_loss": stop_loss,
        "take_profit": take_profit,
    }


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------

async def _query_positions_handler(
    *,
    pool: Any,
    redis_client: Any,
    tenant_id: str,
    bot_id: str,
    symbol: str | None = None,
) -> list[dict[str, Any]]:
    """Return current open positions from Redis, falling back to TimescaleDB."""
    positions: list[dict[str, Any]] = []

    # --- Primary source: Redis snapshot ---
    try:
        key = f"quantgambit:{tenant_id}:{bot_id}:positions:latest"
        raw = await redis_client.get(key)
        if raw is not None:
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            payload = json.loads(raw)
            if isinstance(payload, dict):
                positions = payload.get("positions") or []
            elif isinstance(payload, list):
                positions = payload
    except Exception:
        logger.warning("query_positions: Redis read failed, falling back to TimescaleDB")

    # --- Fallback: TimescaleDB position_events (latest snapshot) ---
    if not positions:
        try:
            query = (
                "SELECT payload FROM position_events "
                "WHERE tenant_id=$1 AND bot_id=$2 "
                "ORDER BY ts DESC LIMIT 1"
            )
            async with pool.acquire() as conn:
                row = await conn.fetchrow(query, tenant_id, bot_id)
            if row:
                raw_payload = row.get("payload") or row[0]
                if isinstance(raw_payload, str):
                    raw_payload = json.loads(raw_payload)
                if isinstance(raw_payload, dict):
                    positions = raw_payload.get("positions") or []
                    if not positions and raw_payload.get("symbol"):
                        # Single position event row
                        positions = [raw_payload]
        except Exception:
            logger.warning("query_positions: TimescaleDB fallback failed")

    # Normalise each position
    result = [_extract_position(p) for p in positions if isinstance(p, dict)]

    # Filter out zero-size positions (closed)
    result = [p for p in result if p.get("size") and p["size"] > 0]

    # Apply optional symbol filter
    if symbol is not None:
        symbol_upper = symbol.upper()
        result = [p for p in result if (p.get("symbol") or "").upper() == symbol_upper]

    return result


# ---------------------------------------------------------------------------
# Registration helper
# ---------------------------------------------------------------------------

def create_query_positions_tool(
    pool: Any,
    redis_client: Any,
    tenant_id: str,
    bot_id: str,
) -> ToolDefinition:
    """Return a ``ToolDefinition`` for ``query_positions`` bound to *pool* and *redis_client*."""

    async def handler(**kwargs: Any) -> list[dict[str, Any]]:
        return await _query_positions_handler(
            pool=pool,
            redis_client=redis_client,
            tenant_id=tenant_id,
            bot_id=bot_id,
            **kwargs,
        )

    return ToolDefinition(
        name="query_positions",
        description=(
            "Query current open positions. "
            "Returns position records with symbol, side, size, entry price, "
            "current price, unrealized PnL, stop loss, and take profit levels. "
            "Optionally filter by symbol."
        ),
        parameters_schema=QUERY_POSITIONS_SCHEMA,
        handler=handler,
    )
