"""Copilot tool: query_performance.

Queries the TimescaleDB ``order_events`` table, computes performance metrics
(total PnL, win rate, average win/loss, profit factor, max drawdown), and
optionally breaks them down per symbol.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from quantgambit.copilot.models import ToolDefinition

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# JSON Schema exposed to the LLM
# ---------------------------------------------------------------------------

QUERY_PERFORMANCE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "symbol": {
            "type": "string",
            "description": "Filter performance metrics to a specific trading pair symbol (e.g. BTCUSDT).",
        },
        "start_time": {
            "type": "string",
            "description": "ISO-8601 start of the time range (inclusive).",
        },
        "end_time": {
            "type": "string",
            "description": "ISO-8601 end of the time range (inclusive).",
        },
        "group_by_symbol": {
            "type": "boolean",
            "description": "When true, return a per-symbol breakdown of metrics.",
            "default": False,
        },
    },
    "additionalProperties": False,
}


# ---------------------------------------------------------------------------
# Payload helpers (shared logic with trades.py)
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


def _extract_pnl_and_symbol(row: dict[str, Any]) -> tuple[str, float | None, str | None]:
    """Extract (symbol, pnl, timestamp_iso) from an ``order_events`` row."""
    payload = _parse_payload(row.get("payload"))
    symbol = row.get("symbol") or payload.get("symbol") or "UNKNOWN"

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

    return symbol, pnl, timestamp


# ---------------------------------------------------------------------------
# Metric computation (pure functions)
# ---------------------------------------------------------------------------


def compute_metrics(pnl_values: list[float]) -> dict[str, Any]:
    """Compute performance metrics from a list of PnL values.

    Returns a dict with: total_pnl, win_rate, avg_win, avg_loss,
    profit_factor, max_drawdown, trade_count.
    """
    if not pnl_values:
        return {
            "total_pnl": 0.0,
            "win_rate": 0.0,
            "avg_win": 0.0,
            "avg_loss": 0.0,
            "profit_factor": 0.0,
            "max_drawdown": 0.0,
            "trade_count": 0,
        }

    total_pnl = sum(pnl_values)
    trade_count = len(pnl_values)

    wins = [p for p in pnl_values if p > 0]
    losses = [p for p in pnl_values if p < 0]

    win_rate = len(wins) / trade_count if trade_count > 0 else 0.0
    avg_win = sum(wins) / len(wins) if wins else 0.0
    avg_loss = sum(losses) / len(losses) if losses else 0.0

    sum_wins = sum(wins)
    sum_losses_abs = abs(sum(losses))
    # Use a large finite number instead of float("inf") because JSON and
    # PostgreSQL JSONB cannot represent Infinity.
    profit_factor = (
        sum_wins / sum_losses_abs if sum_losses_abs > 0 else 9999.99 if sum_wins > 0 else 0.0
    )

    max_drawdown = compute_max_drawdown(pnl_values)

    return {
        "total_pnl": total_pnl,
        "win_rate": win_rate,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "profit_factor": profit_factor,
        "max_drawdown": max_drawdown,
        "trade_count": trade_count,
    }


def compute_max_drawdown(pnl_values: list[float]) -> float:
    """Compute maximum peak-to-trough decline in the cumulative PnL curve.

    Returns a non-negative value representing the largest drawdown.
    """
    if not pnl_values:
        return 0.0

    cumulative = 0.0
    peak = 0.0
    max_dd = 0.0

    for pnl in pnl_values:
        cumulative += pnl
        if cumulative > peak:
            peak = cumulative
        drawdown = peak - cumulative
        if drawdown > max_dd:
            max_dd = drawdown

    return max_dd


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------


async def _query_performance_handler(
    *,
    pool: Any,
    tenant_id: str,
    bot_id: str,
    symbol: str | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
    group_by_symbol: bool = False,
) -> dict[str, Any]:
    """Query ``order_events`` and compute performance metrics."""
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

    query = (
        f"SELECT ts, payload, symbol FROM order_events {where} "
        f"ORDER BY ts ASC"
    )

    async with pool.acquire() as conn:
        rows = await conn.fetch(query, *params)

    # Extract PnL values per symbol
    trades_by_symbol: dict[str, list[float]] = {}
    all_pnl: list[float] = []

    for row in rows:
        sym, pnl, _ = _extract_pnl_and_symbol(dict(row))
        if pnl is None:
            continue
        all_pnl.append(pnl)
        trades_by_symbol.setdefault(sym, []).append(pnl)

    result: dict[str, Any] = {"overall": compute_metrics(all_pnl)}

    if group_by_symbol:
        per_symbol: dict[str, Any] = {}
        for sym, pnl_list in sorted(trades_by_symbol.items()):
            per_symbol[sym] = compute_metrics(pnl_list)
        result["per_symbol"] = per_symbol

    return result


# ---------------------------------------------------------------------------
# Registration helper
# ---------------------------------------------------------------------------


def create_query_performance_tool(
    pool: Any,
    tenant_id: str,
    bot_id: str,
) -> ToolDefinition:
    """Return a ``ToolDefinition`` for ``query_performance`` bound to *pool*."""

    async def handler(**kwargs: Any) -> dict[str, Any]:
        return await _query_performance_handler(
            pool=pool,
            tenant_id=tenant_id,
            bot_id=bot_id,
            **kwargs,
        )

    return ToolDefinition(
        name="query_performance",
        description=(
            "Compute trading performance metrics including total PnL, "
            "win rate, average win, average loss, profit factor, and "
            "maximum drawdown. Optionally filter by symbol and time range, "
            "or group results by symbol for comparative analysis."
        ),
        parameters_schema=QUERY_PERFORMANCE_SCHEMA,
        handler=handler,
    )
