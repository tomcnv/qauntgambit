"""Copilot tool: query_backtests.

Queries the PostgreSQL ``backtest_runs`` table (joined with
``backtest_metrics``) via the dashboard pool and returns backtest records
matching the caller's filters.
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

QUERY_BACKTESTS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "strategy_id": {
            "type": "string",
            "description": "Filter backtests by strategy / run ID.",
        },
        "status": {
            "type": "string",
            "description": "Filter by backtest status (e.g. pending, running, finished, failed, cancelled, degraded).",
        },
        "limit": {
            "type": "integer",
            "description": "Maximum number of records to return (default 20, max 100).",
            "default": 20,
        },
    },
    "additionalProperties": False,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_float(value: Any) -> float | None:
    """Convert *value* to float, returning ``None`` on failure."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_metrics(raw: Any) -> dict[str, Any]:
    """Normalise metrics from a ``backtest_metrics`` row into a summary dict."""
    if raw is None:
        return {}
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return {}
    if not isinstance(raw, dict):
        return {}
    return {
        "sharpe_ratio": _safe_float(raw.get("sharpe_ratio")),
        "max_drawdown_pct": _safe_float(raw.get("max_drawdown_pct")),
        "win_rate": _safe_float(raw.get("win_rate")),
        "total_pnl": _safe_float(raw.get("realized_pnl")),
        "total_trades": raw.get("total_trades"),
        "profit_factor": _safe_float(raw.get("profit_factor")),
    }


def _format_datetime(value: Any) -> str | None:
    """Return an ISO-8601 string for a datetime, or ``None``."""
    if isinstance(value, datetime):
        return value.isoformat()
    if value is not None:
        return str(value)
    return None


def _extract_backtest(row: dict[str, Any]) -> dict[str, Any]:
    """Normalise a joined backtest_runs + backtest_metrics row."""
    start_date = _format_datetime(row.get("start_date"))
    end_date = _format_datetime(row.get("end_date"))
    date_range = f"{start_date or '?'} - {end_date or '?'}"

    # Metrics come from the joined backtest_metrics columns
    metrics = {
        "sharpe_ratio": _safe_float(row.get("sharpe_ratio")),
        "max_drawdown_pct": _safe_float(row.get("max_drawdown_pct")),
        "win_rate": _safe_float(row.get("win_rate")),
        "total_pnl": _safe_float(row.get("realized_pnl")),
        "total_trades": row.get("total_trades"),
        "profit_factor": _safe_float(row.get("profit_factor")),
    }

    return {
        "id": str(row.get("run_id", "")),
        "strategy_id": row.get("name") or str(row.get("run_id", "")),
        "symbol": row.get("symbol") or "ALL",
        "date_range": date_range,
        "status": row.get("status") or "unknown",
        "metrics": metrics,
        "created_at": _format_datetime(row.get("created_at")),
    }


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------

async def _query_backtests_handler(
    *,
    dashboard_pool: Any,
    tenant_id: str,
    bot_id: str,
    strategy_id: str | None = None,
    status: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Query ``backtest_runs`` (LEFT JOIN ``backtest_metrics``) and return
    normalised backtest records."""
    where = "WHERE r.tenant_id=$1 AND r.bot_id=$2"
    params: list[Any] = [tenant_id, bot_id]

    if strategy_id is not None:
        params.append(strategy_id)
        where += f" AND (r.run_id=${len(params)} OR r.name=${len(params)})"

    if status is not None:
        params.append(status)
        where += f" AND r.status=${len(params)}"

    # Clamp limit
    limit = max(1, min(limit, 100))
    params.append(limit)

    query = (
        "SELECT r.run_id, r.tenant_id, r.bot_id, r.status, r.started_at, "
        "r.finished_at, r.name, r.symbol, r.start_date, r.end_date, "
        "r.created_at, "
        "m.sharpe_ratio, m.max_drawdown_pct, m.win_rate, m.realized_pnl, "
        "m.total_trades, m.profit_factor "
        "FROM backtest_runs r "
        "LEFT JOIN backtest_metrics m ON r.run_id = m.run_id "
        f"{where} "
        f"ORDER BY r.started_at DESC LIMIT ${len(params)}"
    )

    async with dashboard_pool.acquire() as conn:
        rows = await conn.fetch(query, *params)

    return [_extract_backtest(dict(r)) for r in rows]


# ---------------------------------------------------------------------------
# Registration helper
# ---------------------------------------------------------------------------

def create_query_backtests_tool(
    dashboard_pool: Any,
    tenant_id: str,
    bot_id: str,
) -> ToolDefinition:
    """Return a ``ToolDefinition`` for ``query_backtests`` bound to *dashboard_pool*."""

    async def handler(**kwargs: Any) -> list[dict[str, Any]]:
        return await _query_backtests_handler(
            dashboard_pool=dashboard_pool,
            tenant_id=tenant_id,
            bot_id=bot_id,
            **kwargs,
        )

    return ToolDefinition(
        name="query_backtests",
        description=(
            "Query backtest runs and their results. "
            "Returns backtest records with strategy ID, symbol, date range, "
            "status, and key metrics (Sharpe ratio, max drawdown, win rate, "
            "total PnL, trade count, profit factor). "
            "Filters by strategy_id and status are optional."
        ),
        parameters_schema=QUERY_BACKTESTS_SCHEMA,
        handler=handler,
    )
