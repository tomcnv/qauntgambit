"""Copilot tool: query_market_price.

Queries the Redis orderbook feed stream for the latest bid/ask data and
computes mid price and spread in basis points.  Supports querying a single
symbol or all symbols present in the stream.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from quantgambit.copilot.models import ToolDefinition

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# JSON Schema exposed to the LLM
# ---------------------------------------------------------------------------

QUERY_MARKET_PRICE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "symbol": {
            "type": "string",
            "description": "Trading pair symbol (e.g. BTCUSDT). Omit for all symbols.",
        },
    },
    "additionalProperties": False,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _resolve_exchange(
    redis_client: Any,
    tenant_id: str,
    bot_id: str,
) -> str | None:
    """Resolve the exchange name.

    Checks the ``EXCHANGE`` environment variable first.  If unset, falls back
    to the Redis key ``quantgambit:{tenant_id}:{bot_id}:market_data:provider``.
    """
    exchange = os.environ.get("EXCHANGE")
    if exchange:
        return exchange

    try:
        raw = await redis_client.get(
            f"quantgambit:{tenant_id}:{bot_id}:market_data:provider"
        )
        if raw is not None:
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            return raw
    except Exception:
        logger.warning("_resolve_exchange: Redis fallback read failed", exc_info=True)

    return None


def _parse_orderbook_entry(
    entry_fields: dict[str, Any],
    exchange: str,
) -> dict[str, Any] | None:
    """Parse a single orderbook stream entry into a price record.

    Returns ``None`` when the entry cannot be parsed (malformed JSON, empty
    bids/asks, etc.).
    """
    try:
        symbol = entry_fields.get("symbol") or entry_fields.get(b"symbol")
        if isinstance(symbol, bytes):
            symbol = symbol.decode("utf-8")
        if not symbol:
            return None

        raw_bids = entry_fields.get("bids") or entry_fields.get(b"bids")
        raw_asks = entry_fields.get("asks") or entry_fields.get(b"asks")
        if isinstance(raw_bids, bytes):
            raw_bids = raw_bids.decode("utf-8")
        if isinstance(raw_asks, bytes):
            raw_asks = raw_asks.decode("utf-8")

        bids = json.loads(raw_bids) if isinstance(raw_bids, str) else raw_bids
        asks = json.loads(raw_asks) if isinstance(raw_asks, str) else raw_asks

        if not bids or not asks:
            return None

        best_bid = float(bids[0][0])
        best_ask = float(asks[0][0])

        if best_bid <= 0 or best_ask <= 0:
            return None

        mid_price = (best_bid + best_ask) / 2
        spread_bps = (best_ask - best_bid) / mid_price * 10000

        return {
            "symbol": symbol,
            "best_bid": best_bid,
            "best_ask": best_ask,
            "mid_price": mid_price,
            "spread_bps": round(spread_bps, 4),
            "exchange": exchange,
        }
    except (json.JSONDecodeError, TypeError, ValueError, IndexError, KeyError):
        logger.warning(
            "_parse_orderbook_entry: failed to parse entry", exc_info=True
        )
        return None


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------

async def _query_market_price_handler(
    *,
    redis_client: Any,
    tenant_id: str,
    bot_id: str,
    symbol: str | None = None,
) -> list[dict[str, Any]] | dict[str, Any]:
    """Return latest price data from the orderbook feed stream.

    When *symbol* is provided, returns a single-element list with price data
    for that symbol.  When omitted, returns price data for all symbols found
    in recent stream entries.
    """
    try:
        exchange = await _resolve_exchange(redis_client, tenant_id, bot_id)
        if not exchange:
            return {"error": "Could not resolve exchange name"}

        stream_key = f"events:orderbook_feed:{exchange}"

        if symbol is not None:
            # Single-symbol mode: read latest entry, scan for matching symbol
            entries = await redis_client.xrevrange(stream_key, count=100)
            if not entries:
                return {"error": f"No price data available for {symbol}"}

            for _entry_id, entry_fields in entries:
                record = _parse_orderbook_entry(entry_fields, exchange)
                if record and record["symbol"].upper() == symbol.upper():
                    return [record]

            return {"error": f"No price data available for {symbol}"}

        else:
            # All-symbols mode: read recent entries, deduplicate by symbol
            entries = await redis_client.xrevrange(stream_key, count=100)
            if not entries:
                return {"error": "No price data available"}

            seen: dict[str, dict[str, Any]] = {}
            for _entry_id, entry_fields in entries:
                record = _parse_orderbook_entry(entry_fields, exchange)
                if record and record["symbol"] not in seen:
                    seen[record["symbol"]] = record

            if not seen:
                return {"error": "No price data available"}

            return list(seen.values())

    except Exception:
        logger.warning("query_market_price: Redis read failed", exc_info=True)
        return {"error": "Failed to retrieve market price data from Redis"}


# ---------------------------------------------------------------------------
# Registration helper
# ---------------------------------------------------------------------------

def create_query_market_price_tool(
    redis_client: Any,
    tenant_id: str,
    bot_id: str,
) -> ToolDefinition:
    """Return a ``ToolDefinition`` for ``query_market_price``."""

    async def handler(**kwargs: Any) -> list[dict[str, Any]] | dict[str, Any]:
        return await _query_market_price_handler(
            redis_client=redis_client,
            tenant_id=tenant_id,
            bot_id=bot_id,
            **kwargs,
        )

    return ToolDefinition(
        name="query_market_price",
        description=(
            "Query current market prices from the orderbook feed. "
            "Returns best bid, best ask, mid price, and spread in basis points. "
            "Optionally filter by symbol; omit for all symbols."
        ),
        parameters_schema=QUERY_MARKET_PRICE_SCHEMA,
        handler=handler,
    )
