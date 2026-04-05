"""Copilot tool: query_pipeline_throughput.

Queries the TimescaleDB ``decision_events`` table, aggregates per-stage
counts, computes pass-through rates, and identifies the bottleneck stage.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from quantgambit.copilot.models import ToolDefinition

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PIPELINE_STAGES: list[str] = [
    "DataReadiness",
    "PositionEvaluation",
    "Risk",
    "Signal",
    "Prediction",
    "Execution",
    "ProfileRouting",
]

# ---------------------------------------------------------------------------
# JSON Schema exposed to the LLM
# ---------------------------------------------------------------------------

QUERY_PIPELINE_THROUGHPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "start_time": {
            "type": "string",
            "description": "ISO-8601 start of the time range (inclusive).",
        },
        "end_time": {
            "type": "string",
            "description": "ISO-8601 end of the time range (inclusive).",
        },
        "symbol": {
            "type": "string",
            "description": "Filter by trading pair symbol (e.g. BTCUSDT).",
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


# ---------------------------------------------------------------------------
# Aggregation logic
# ---------------------------------------------------------------------------

def _aggregate_throughput(
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """Aggregate decision event rows into per-stage throughput stats.

    Each row is expected to have a ``payload`` field containing a
    ``gates_passed`` list of stage names the decision passed through.

    Returns a dict with ``total_decisions``, ``per_stage``, and ``bottleneck``.
    """
    total = len(rows)

    # Count how many decisions reached each stage
    stage_counts: dict[str, int] = {stage: 0 for stage in PIPELINE_STAGES}
    for row in rows:
        payload = _parse_payload(row.get("payload"))
        gates_passed: list[str] = payload.get("gates_passed") or []
        for stage in gates_passed:
            if stage in stage_counts:
                stage_counts[stage] += 1

    # Compute pass-through rates
    per_stage: dict[str, dict[str, Any]] = {}
    for stage in PIPELINE_STAGES:
        count = stage_counts[stage]
        pass_rate = count / total if total > 0 else 0.0
        per_stage[stage] = {"count": count, "pass_rate": round(pass_rate, 4)}

    # Identify bottleneck: stage with lowest pass_rate among stages with count > 0
    bottleneck: dict[str, Any] | None = None
    if total > 0:
        candidates = [
            (stage, per_stage[stage]["pass_rate"])
            for stage in PIPELINE_STAGES
            if per_stage[stage]["count"] > 0
        ]
        if candidates:
            min_stage, min_rate = min(candidates, key=lambda x: x[1])
            bottleneck = {"stage": min_stage, "pass_rate": min_rate}

    return {
        "total_decisions": total,
        "per_stage": per_stage,
        "bottleneck": bottleneck,
    }


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------

async def _query_pipeline_throughput_handler(
    *,
    pool: Any,
    tenant_id: str,
    bot_id: str,
    start_time: str | None = None,
    end_time: str | None = None,
    symbol: str | None = None,
) -> dict[str, Any]:
    """Query ``decision_events`` and return pipeline throughput stats."""
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

    query = f"SELECT ts, payload, symbol FROM decision_events {where} ORDER BY ts DESC"

    async with pool.acquire() as conn:
        rows = await conn.fetch(query, *params)

    return _aggregate_throughput([dict(r) for r in rows])


# ---------------------------------------------------------------------------
# Registration helper
# ---------------------------------------------------------------------------

def create_query_pipeline_throughput_tool(
    pool: Any,
    tenant_id: str,
    bot_id: str,
) -> ToolDefinition:
    """Return a ``ToolDefinition`` for ``query_pipeline_throughput`` bound to *pool*."""

    async def handler(**kwargs: Any) -> dict[str, Any]:
        return await _query_pipeline_throughput_handler(
            pool=pool,
            tenant_id=tenant_id,
            bot_id=bot_id,
            **kwargs,
        )

    return ToolDefinition(
        name="query_pipeline_throughput",
        description=(
            "Query decision pipeline throughput statistics. "
            "Returns per-stage decision counts, pass-through rates, "
            "and identifies the bottleneck stage (lowest pass-through rate). "
            "Filters by symbol and time range are optional."
        ),
        parameters_schema=QUERY_PIPELINE_THROUGHPUT_SCHEMA,
        handler=handler,
    )
