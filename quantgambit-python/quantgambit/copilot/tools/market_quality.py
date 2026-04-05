"""Copilot tool: query_market_quality.

Queries Redis for market data quality snapshots.  Each symbol has a quality
snapshot stored at ``quantgambit:{tenant_id}:{bot_id}:quality:{symbol}:latest``
containing quality scores, data ages, and sync states.  Supports querying a
single symbol or all symbols via ``SCAN``.
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

QUERY_MARKET_QUALITY_SCHEMA: dict[str, Any] = {
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
# Handler
# ---------------------------------------------------------------------------

async def _query_market_quality_handler(
    *,
    redis_client: Any,
    tenant_id: str,
    bot_id: str,
    symbol: str | None = None,
) -> list[dict[str, Any]] | dict[str, Any]:
    """Return market data quality snapshots from Redis.

    When *symbol* is provided, reads the specific quality key for that symbol.
    When omitted, uses ``SCAN`` to discover all quality keys and returns data
    for every symbol found.
    """
    try:
        if symbol is not None:
            # Single-symbol mode
            key = f"quantgambit:{tenant_id}:{bot_id}:quality:{symbol}:latest"
            raw = await redis_client.get(key)
            if raw is None:
                return {"error": f"No quality data available for {symbol}"}
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            try:
                data = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                logger.warning("query_market_quality: malformed JSON for key=%s", key)
                return {"error": f"No quality data available for {symbol}"}
            data["symbol"] = symbol
            return [data]

        else:
            # All-symbols mode: SCAN for quality keys
            pattern = f"quantgambit:{tenant_id}:{bot_id}:quality:*:latest"
            prefix = f"quantgambit:{tenant_id}:{bot_id}:quality:"
            suffix = ":latest"

            results: list[dict[str, Any]] = []
            cursor = 0
            while True:
                cursor, keys = await redis_client.scan(
                    cursor, match=pattern, count=100,
                )
                for key in keys:
                    if isinstance(key, bytes):
                        key = key.decode("utf-8")
                    # Extract symbol from key pattern
                    if key.startswith(prefix) and key.endswith(suffix):
                        sym = key[len(prefix):-len(suffix)]
                    else:
                        continue

                    raw = await redis_client.get(key)
                    if raw is None:
                        continue
                    if isinstance(raw, bytes):
                        raw = raw.decode("utf-8")
                    try:
                        data = json.loads(raw)
                    except (json.JSONDecodeError, TypeError):
                        logger.warning(
                            "query_market_quality: malformed JSON for key=%s", key,
                        )
                        continue
                    data["symbol"] = sym
                    results.append(data)

                if cursor == 0:
                    break

            if not results:
                return {"error": "No quality data available"}

            return results

    except Exception:
        logger.warning("query_market_quality: Redis read failed", exc_info=True)
        return {"error": "Failed to retrieve market quality data from Redis"}


# ---------------------------------------------------------------------------
# Registration helper
# ---------------------------------------------------------------------------

def create_query_market_quality_tool(
    redis_client: Any,
    tenant_id: str,
    bot_id: str,
) -> ToolDefinition:
    """Return a ``ToolDefinition`` for ``query_market_quality``."""

    async def handler(**kwargs: Any) -> list[dict[str, Any]] | dict[str, Any]:
        return await _query_market_quality_handler(
            redis_client=redis_client,
            tenant_id=tenant_id,
            bot_id=bot_id,
            **kwargs,
        )

    return ToolDefinition(
        name="query_market_quality",
        description=(
            "Query market data quality for a trading symbol. "
            "Returns quality score, tick age, orderbook age, trade age, "
            "and sync states indicating data freshness and reliability. "
            "Optionally filter by symbol; omit for all symbols."
        ),
        parameters_schema=QUERY_MARKET_QUALITY_SCHEMA,
        handler=handler,
    )
