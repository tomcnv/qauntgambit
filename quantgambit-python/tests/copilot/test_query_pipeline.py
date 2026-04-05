"""Unit tests for the query_pipeline_throughput copilot tool."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from quantgambit.copilot.models import ToolDefinition
from quantgambit.copilot.tools.pipeline import (
    PIPELINE_STAGES,
    QUERY_PIPELINE_THROUGHPUT_SCHEMA,
    _aggregate_throughput,
    _parse_payload,
    _query_pipeline_throughput_handler,
    create_query_pipeline_throughput_tool,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_row(
    symbol: str = "BTCUSDT",
    gates_passed: list[str] | None = None,
    ts: datetime | None = None,
) -> dict[str, Any]:
    """Build a fake ``decision_events`` row dict."""
    if ts is None:
        ts = datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
    if gates_passed is None:
        gates_passed = ["DataReadiness", "PositionEvaluation", "Risk"]
    payload = {
        "gates_passed": gates_passed,
        "result": "COMPLETE" if len(gates_passed) == 7 else "REJECT",
    }
    return {
        "ts": ts,
        "symbol": symbol,
        "payload": json.dumps(payload),
    }


def _make_pool(rows: list[dict[str, Any]]) -> MagicMock:
    """Return a mock asyncpg pool that yields *rows* from ``conn.fetch``."""
    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=rows)

    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__ = AsyncMock(return_value=False)

    pool = MagicMock()
    pool.acquire.return_value = ctx
    return pool


# ---------------------------------------------------------------------------
# _parse_payload
# ---------------------------------------------------------------------------

class TestParsePayload:
    def test_dict_passthrough(self):
        d = {"a": 1}
        assert _parse_payload(d) is d

    def test_json_string(self):
        assert _parse_payload('{"x": 2}') == {"x": 2}

    def test_invalid_json(self):
        assert _parse_payload("not json") == {}

    def test_none(self):
        assert _parse_payload(None) == {}


# ---------------------------------------------------------------------------
# _aggregate_throughput
# ---------------------------------------------------------------------------

class TestAggregateThroughput:
    def test_empty_rows(self):
        result = _aggregate_throughput([])
        assert result["total_decisions"] == 0
        assert result["bottleneck"] is None
        for stage in PIPELINE_STAGES:
            assert result["per_stage"][stage]["count"] == 0
            assert result["per_stage"][stage]["pass_rate"] == 0.0

    def test_single_event_all_stages(self):
        row = _make_row(gates_passed=PIPELINE_STAGES[:])
        result = _aggregate_throughput([row])
        assert result["total_decisions"] == 1
        for stage in PIPELINE_STAGES:
            assert result["per_stage"][stage]["count"] == 1
            assert result["per_stage"][stage]["pass_rate"] == 1.0
        # All stages have rate 1.0 — bottleneck is the first one (min picks first)
        assert result["bottleneck"]["pass_rate"] == 1.0

    def test_single_event_partial_stages(self):
        row = _make_row(gates_passed=["DataReadiness", "PositionEvaluation"])
        result = _aggregate_throughput([row])
        assert result["total_decisions"] == 1
        assert result["per_stage"]["DataReadiness"]["count"] == 1
        assert result["per_stage"]["PositionEvaluation"]["count"] == 1
        assert result["per_stage"]["Risk"]["count"] == 0
        # Bottleneck among stages with count > 0
        assert result["bottleneck"]["pass_rate"] == 1.0

    def test_multiple_events_bottleneck(self):
        """Two events: one passes 3 stages, one passes all 7.
        Stages 4-7 have count=1 (pass_rate=0.5), stages 1-3 have count=2 (pass_rate=1.0).
        Bottleneck should be the first stage with 0.5 rate.
        """
        rows = [
            _make_row(gates_passed=["DataReadiness", "PositionEvaluation", "Risk"]),
            _make_row(gates_passed=PIPELINE_STAGES[:]),
        ]
        result = _aggregate_throughput(rows)
        assert result["total_decisions"] == 2
        assert result["per_stage"]["DataReadiness"]["count"] == 2
        assert result["per_stage"]["Signal"]["count"] == 1
        assert result["bottleneck"]["stage"] == "Signal"
        assert result["bottleneck"]["pass_rate"] == 0.5

    def test_unknown_stages_ignored(self):
        """Stages not in PIPELINE_STAGES should not appear in output."""
        row = _make_row(gates_passed=["DataReadiness", "UnknownStage"])
        result = _aggregate_throughput([row])
        assert "UnknownStage" not in result["per_stage"]
        assert result["per_stage"]["DataReadiness"]["count"] == 1

    def test_event_counted_in_exactly_its_stages(self):
        """Each event is counted only in the stages it passed through."""
        rows = [
            _make_row(gates_passed=["DataReadiness"]),
            _make_row(gates_passed=["DataReadiness", "PositionEvaluation", "Risk"]),
        ]
        result = _aggregate_throughput(rows)
        assert result["per_stage"]["DataReadiness"]["count"] == 2
        assert result["per_stage"]["PositionEvaluation"]["count"] == 1
        assert result["per_stage"]["Risk"]["count"] == 1
        assert result["per_stage"]["Signal"]["count"] == 0

    def test_pass_rate_computation(self):
        """pass_rate = count / total_decisions."""
        rows = [
            _make_row(gates_passed=["DataReadiness", "PositionEvaluation"]),
            _make_row(gates_passed=["DataReadiness", "PositionEvaluation"]),
            _make_row(gates_passed=["DataReadiness"]),
        ]
        result = _aggregate_throughput(rows)
        assert result["total_decisions"] == 3
        assert result["per_stage"]["DataReadiness"]["pass_rate"] == 1.0
        assert result["per_stage"]["PositionEvaluation"]["pass_rate"] == round(2 / 3, 4)

    def test_bottleneck_is_minimum_pass_rate(self):
        """Bottleneck is the stage with the lowest pass_rate among stages with count > 0."""
        rows = [
            _make_row(gates_passed=PIPELINE_STAGES[:]),
            _make_row(gates_passed=PIPELINE_STAGES[:]),
            _make_row(gates_passed=PIPELINE_STAGES[:]),
            _make_row(gates_passed=["DataReadiness"]),
        ]
        result = _aggregate_throughput(rows)
        # DataReadiness: 4/4=1.0, others: 3/4=0.75 except stages not in last event
        assert result["bottleneck"]["pass_rate"] == 0.75

    def test_payload_as_json_string(self):
        """Payload stored as JSON string should be parsed correctly."""
        row = {
            "ts": datetime(2024, 1, 1, tzinfo=timezone.utc),
            "symbol": "BTCUSDT",
            "payload": json.dumps({"gates_passed": ["DataReadiness", "Risk"]}),
        }
        result = _aggregate_throughput([row])
        assert result["per_stage"]["DataReadiness"]["count"] == 1
        assert result["per_stage"]["Risk"]["count"] == 1

    def test_missing_gates_passed(self):
        """Event with no gates_passed should still count toward total."""
        row = {
            "ts": datetime(2024, 1, 1, tzinfo=timezone.utc),
            "symbol": "BTCUSDT",
            "payload": json.dumps({}),
        }
        result = _aggregate_throughput([row])
        assert result["total_decisions"] == 1
        for stage in PIPELINE_STAGES:
            assert result["per_stage"][stage]["count"] == 0
        # No stages with count > 0, so no bottleneck
        assert result["bottleneck"] is None


# ---------------------------------------------------------------------------
# _query_pipeline_throughput_handler
# ---------------------------------------------------------------------------

class TestQueryPipelineThroughputHandler:
    @pytest.mark.asyncio
    async def test_basic_query(self):
        rows = [_make_row(), _make_row(symbol="ETHUSDT")]
        pool = _make_pool(rows)
        result = await _query_pipeline_throughput_handler(
            pool=pool, tenant_id="t1", bot_id="b1",
        )
        assert result["total_decisions"] == 2

    @pytest.mark.asyncio
    async def test_symbol_filter_passed_to_query(self):
        pool = _make_pool([])
        await _query_pipeline_throughput_handler(
            pool=pool, tenant_id="t1", bot_id="b1", symbol="BTCUSDT",
        )
        conn = pool.acquire.return_value.__aenter__.return_value
        query_arg = conn.fetch.call_args[0][0]
        assert "symbol=$" in query_arg

    @pytest.mark.asyncio
    async def test_time_range_filter(self):
        pool = _make_pool([])
        await _query_pipeline_throughput_handler(
            pool=pool,
            tenant_id="t1",
            bot_id="b1",
            start_time="2024-01-01T00:00:00Z",
            end_time="2024-12-31T23:59:59Z",
        )
        conn = pool.acquire.return_value.__aenter__.return_value
        query_arg = conn.fetch.call_args[0][0]
        assert "ts >=" in query_arg
        assert "ts <=" in query_arg

    @pytest.mark.asyncio
    async def test_empty_result(self):
        pool = _make_pool([])
        result = await _query_pipeline_throughput_handler(
            pool=pool, tenant_id="t1", bot_id="b1",
        )
        assert result["total_decisions"] == 0
        assert result["bottleneck"] is None

    @pytest.mark.asyncio
    async def test_invalid_start_time_ignored(self):
        pool = _make_pool([])
        result = await _query_pipeline_throughput_handler(
            pool=pool, tenant_id="t1", bot_id="b1", start_time="not-a-date",
        )
        assert result["total_decisions"] == 0

    @pytest.mark.asyncio
    async def test_parameterised_query_no_string_interpolation(self):
        pool = _make_pool([])
        await _query_pipeline_throughput_handler(
            pool=pool,
            tenant_id="t1",
            bot_id="b1",
            symbol="BTCUSDT",
            start_time="2024-01-01T00:00:00Z",
            end_time="2024-12-31T23:59:59Z",
        )
        conn = pool.acquire.return_value.__aenter__.return_value
        query_arg = conn.fetch.call_args[0][0]
        assert "BTCUSDT" not in query_arg
        assert "2024-01-01" not in query_arg

    @pytest.mark.asyncio
    async def test_queries_decision_events_table(self):
        pool = _make_pool([])
        await _query_pipeline_throughput_handler(
            pool=pool, tenant_id="t1", bot_id="b1",
        )
        conn = pool.acquire.return_value.__aenter__.return_value
        query_arg = conn.fetch.call_args[0][0]
        assert "decision_events" in query_arg

    @pytest.mark.asyncio
    async def test_returns_all_pipeline_stages(self):
        pool = _make_pool([_make_row()])
        result = await _query_pipeline_throughput_handler(
            pool=pool, tenant_id="t1", bot_id="b1",
        )
        for stage in PIPELINE_STAGES:
            assert stage in result["per_stage"]


# ---------------------------------------------------------------------------
# create_query_pipeline_throughput_tool
# ---------------------------------------------------------------------------

class TestCreateQueryPipelineThroughputTool:
    def test_returns_tool_definition(self):
        pool = _make_pool([])
        tool = create_query_pipeline_throughput_tool(pool, "t1", "b1")
        assert isinstance(tool, ToolDefinition)
        assert tool.name == "query_pipeline_throughput"
        assert tool.parameters_schema == QUERY_PIPELINE_THROUGHPUT_SCHEMA

    def test_description_non_empty(self):
        pool = _make_pool([])
        tool = create_query_pipeline_throughput_tool(pool, "t1", "b1")
        assert len(tool.description) > 0

    @pytest.mark.asyncio
    async def test_handler_delegates_to_query(self):
        rows = [_make_row()]
        pool = _make_pool(rows)
        tool = create_query_pipeline_throughput_tool(pool, "t1", "b1")
        result = await tool.handler(symbol="BTCUSDT")
        assert result["total_decisions"] == 1

    @pytest.mark.asyncio
    async def test_handler_with_no_args(self):
        pool = _make_pool([_make_row()])
        tool = create_query_pipeline_throughput_tool(pool, "t1", "b1")
        result = await tool.handler()
        assert result["total_decisions"] == 1
