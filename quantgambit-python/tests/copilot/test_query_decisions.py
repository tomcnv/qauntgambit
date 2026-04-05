"""Unit tests for the query_decision_traces copilot tool."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from quantgambit.copilot.models import ToolDefinition
from quantgambit.copilot.tools.decisions import (
    QUERY_DECISION_TRACES_SCHEMA,
    _extract_decision,
    _parse_payload,
    _query_decision_traces_handler,
    _safe_float,
    create_query_decision_traces_tool,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_row(
    symbol: str = "BTCUSDT",
    result: str = "REJECT",
    rejection_reason: str | None = "risk_blocked",
    gates_passed: list[str] | None = None,
    signal_confidence: float | None = 0.85,
    ts: datetime | None = None,
) -> dict[str, Any]:
    """Build a fake ``decision_events`` row dict."""
    if ts is None:
        ts = datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
    if gates_passed is None:
        gates_passed = ["DataReadiness", "PositionEvaluation", "Risk"]
    payload = {
        "result": result,
        "rejection_reason": rejection_reason,
        "gates_passed": gates_passed,
        "signal_confidence": signal_confidence,
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
# _safe_float
# ---------------------------------------------------------------------------

class TestSafeFloat:
    def test_none(self):
        assert _safe_float(None) is None

    def test_int(self):
        assert _safe_float(42) == 42.0

    def test_string_number(self):
        assert _safe_float("0.95") == 0.95

    def test_invalid_string(self):
        assert _safe_float("abc") is None


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
# _extract_decision
# ---------------------------------------------------------------------------

class TestExtractDecision:
    def test_basic_extraction(self):
        row = _make_row()
        decision = _extract_decision(row)
        assert decision["symbol"] == "BTCUSDT"
        assert decision["stages_executed"] == ["DataReadiness", "PositionEvaluation", "Risk"]
        assert decision["rejection_reason"] == "risk_blocked"
        assert decision["signal_confidence"] == 0.85
        assert decision["result"] == "REJECT"
        assert decision["timestamp"] is not None

    def test_complete_decision(self):
        row = _make_row(
            result="COMPLETE",
            rejection_reason=None,
            gates_passed=[
                "DataReadiness", "PositionEvaluation", "Risk",
                "Signal", "Prediction", "Execution", "ProfileRouting",
            ],
        )
        decision = _extract_decision(row)
        assert decision["result"] == "COMPLETE"
        assert decision["rejection_reason"] is None
        assert len(decision["stages_executed"]) == 7

    def test_missing_symbol_falls_back(self):
        row = _make_row()
        row["symbol"] = None
        payload = json.loads(row["payload"])
        payload["symbol"] = "ETHUSDT"
        row["payload"] = json.dumps(payload)
        decision = _extract_decision(row)
        assert decision["symbol"] == "ETHUSDT"

    def test_missing_symbol_unknown(self):
        row = _make_row()
        row["symbol"] = None
        decision = _extract_decision(row)
        assert decision["symbol"] == "UNKNOWN"

    def test_payload_as_dict(self):
        row = _make_row()
        row["payload"] = json.loads(row["payload"])
        decision = _extract_decision(row)
        assert decision["rejection_reason"] == "risk_blocked"

    def test_missing_gates_passed(self):
        row = _make_row(gates_passed=None)
        payload = json.loads(row["payload"])
        del payload["gates_passed"]
        row["payload"] = json.dumps(payload)
        decision = _extract_decision(row)
        assert decision["stages_executed"] == []

    def test_timestamp_iso_format(self):
        ts = datetime(2024, 6, 1, 10, 30, 0, tzinfo=timezone.utc)
        row = _make_row(ts=ts)
        decision = _extract_decision(row)
        assert "2024-06-01" in decision["timestamp"]

    def test_all_fields_present(self):
        row = _make_row()
        decision = _extract_decision(row)
        expected_keys = {
            "symbol", "stages_executed", "rejection_reason",
            "signal_confidence", "result", "timestamp",
        }
        assert set(decision.keys()) == expected_keys

    def test_signal_confidence_from_snapshot(self):
        """signal_confidence can live inside the snapshot sub-dict."""
        row = _make_row(signal_confidence=None)
        payload = json.loads(row["payload"])
        payload["signal_confidence"] = None
        payload["snapshot"] = {"signal_confidence": 0.72}
        row["payload"] = json.dumps(payload)
        decision = _extract_decision(row)
        assert decision["signal_confidence"] == 0.72


# ---------------------------------------------------------------------------
# _query_decision_traces_handler
# ---------------------------------------------------------------------------

class TestQueryDecisionTracesHandler:
    @pytest.mark.asyncio
    async def test_basic_query(self):
        rows = [_make_row(), _make_row(symbol="ETHUSDT")]
        pool = _make_pool(rows)
        result = await _query_decision_traces_handler(
            pool=pool, tenant_id="t1", bot_id="b1",
        )
        assert len(result) == 2
        assert result[0]["symbol"] == "BTCUSDT"
        assert result[1]["symbol"] == "ETHUSDT"

    @pytest.mark.asyncio
    async def test_symbol_filter_passed_to_query(self):
        pool = _make_pool([_make_row(symbol="BTCUSDT")])
        await _query_decision_traces_handler(
            pool=pool, tenant_id="t1", bot_id="b1", symbol="BTCUSDT",
        )
        conn = pool.acquire.return_value.__aenter__.return_value
        query_arg = conn.fetch.call_args[0][0]
        assert "symbol=$" in query_arg

    @pytest.mark.asyncio
    async def test_time_range_filter(self):
        pool = _make_pool([])
        await _query_decision_traces_handler(
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
    async def test_limit_clamped_to_500(self):
        pool = _make_pool([])
        await _query_decision_traces_handler(
            pool=pool, tenant_id="t1", bot_id="b1", limit=9999,
        )
        conn = pool.acquire.return_value.__aenter__.return_value
        args = conn.fetch.call_args[0]
        assert args[-1] == 500

    @pytest.mark.asyncio
    async def test_limit_minimum(self):
        pool = _make_pool([])
        await _query_decision_traces_handler(
            pool=pool, tenant_id="t1", bot_id="b1", limit=-5,
        )
        conn = pool.acquire.return_value.__aenter__.return_value
        args = conn.fetch.call_args[0]
        assert args[-1] == 1

    @pytest.mark.asyncio
    async def test_empty_result(self):
        pool = _make_pool([])
        result = await _query_decision_traces_handler(
            pool=pool, tenant_id="t1", bot_id="b1",
        )
        assert result == []

    @pytest.mark.asyncio
    async def test_invalid_start_time_ignored(self):
        pool = _make_pool([])
        result = await _query_decision_traces_handler(
            pool=pool, tenant_id="t1", bot_id="b1", start_time="not-a-date",
        )
        assert result == []

    @pytest.mark.asyncio
    async def test_parameterised_query_no_string_interpolation(self):
        """Ensure SQL uses $N placeholders, not f-string interpolation of values."""
        pool = _make_pool([])
        await _query_decision_traces_handler(
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
        """The query should target the decision_events table."""
        pool = _make_pool([])
        await _query_decision_traces_handler(
            pool=pool, tenant_id="t1", bot_id="b1",
        )
        conn = pool.acquire.return_value.__aenter__.return_value
        query_arg = conn.fetch.call_args[0][0]
        assert "decision_events" in query_arg

    @pytest.mark.asyncio
    async def test_orders_by_ts_desc(self):
        """Results should be ordered by timestamp descending."""
        pool = _make_pool([])
        await _query_decision_traces_handler(
            pool=pool, tenant_id="t1", bot_id="b1",
        )
        conn = pool.acquire.return_value.__aenter__.return_value
        query_arg = conn.fetch.call_args[0][0]
        assert "ORDER BY ts DESC" in query_arg


# ---------------------------------------------------------------------------
# create_query_decision_traces_tool
# ---------------------------------------------------------------------------

class TestCreateQueryDecisionTracesTool:
    def test_returns_tool_definition(self):
        pool = _make_pool([])
        tool = create_query_decision_traces_tool(pool, "t1", "b1")
        assert isinstance(tool, ToolDefinition)
        assert tool.name == "query_decision_traces"
        assert tool.parameters_schema == QUERY_DECISION_TRACES_SCHEMA

    def test_description_non_empty(self):
        pool = _make_pool([])
        tool = create_query_decision_traces_tool(pool, "t1", "b1")
        assert len(tool.description) > 0

    @pytest.mark.asyncio
    async def test_handler_delegates_to_query(self):
        rows = [_make_row()]
        pool = _make_pool(rows)
        tool = create_query_decision_traces_tool(pool, "t1", "b1")
        result = await tool.handler(symbol="BTCUSDT")
        assert len(result) == 1
        assert result[0]["symbol"] == "BTCUSDT"

    @pytest.mark.asyncio
    async def test_handler_with_no_args(self):
        pool = _make_pool([_make_row()])
        tool = create_query_decision_traces_tool(pool, "t1", "b1")
        result = await tool.handler()
        assert len(result) == 1
