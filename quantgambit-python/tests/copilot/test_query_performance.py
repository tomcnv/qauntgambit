"""Unit tests for the query_performance copilot tool."""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from quantgambit.copilot.models import ToolDefinition
from quantgambit.copilot.tools.performance import (
    QUERY_PERFORMANCE_SCHEMA,
    _extract_pnl_and_symbol,
    _parse_payload,
    _query_performance_handler,
    _safe_float,
    compute_max_drawdown,
    compute_metrics,
    create_query_performance_tool,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_row(
    symbol: str = "BTCUSDT",
    pnl: float = 100.0,
    ts: datetime | None = None,
    position_effect: str = "close",
    reason: str = "position_close",
) -> dict[str, Any]:
    """Build a fake ``order_events`` row dict."""
    if ts is None:
        ts = datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
    payload = {
        "side": "buy",
        "entry_price": 50000.0,
        "exit_price": 51000.0,
        "size": 0.1,
        "net_pnl": pnl,
        "position_effect": position_effect,
        "reason": reason,
    }
    return {
        "ts": ts,
        "symbol": symbol,
        "exchange": "binance",
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
        assert _safe_float("3.14") == 3.14

    def test_invalid_string(self):
        assert _safe_float("abc") is None


# ---------------------------------------------------------------------------
# _parse_payload
# ---------------------------------------------------------------------------


class TestParsePayload:
    def test_dict_passthrough(self):
        d = {"key": "value"}
        assert _parse_payload(d) is d

    def test_json_string(self):
        assert _parse_payload('{"a": 1}') == {"a": 1}

    def test_invalid_json(self):
        assert _parse_payload("not json") == {}

    def test_none(self):
        assert _parse_payload(None) == {}


# ---------------------------------------------------------------------------
# _extract_pnl_and_symbol
# ---------------------------------------------------------------------------


class TestExtractPnlAndSymbol:
    def test_basic_extraction(self):
        row = _make_row(symbol="ETHUSDT", pnl=50.0)
        sym, pnl, ts = _extract_pnl_and_symbol(row)
        assert sym == "ETHUSDT"
        assert pnl == 50.0
        assert ts is not None

    def test_missing_symbol_falls_back(self):
        row = _make_row()
        row["symbol"] = None
        # payload doesn't have symbol either
        sym, pnl, _ = _extract_pnl_and_symbol(row)
        assert sym == "UNKNOWN"

    def test_none_pnl(self):
        row = _make_row()
        payload = json.loads(row["payload"])
        del payload["net_pnl"]
        row["payload"] = json.dumps(payload)
        _, pnl, _ = _extract_pnl_and_symbol(row)
        assert pnl is None

    def test_timestamp_iso_format(self):
        ts = datetime(2024, 6, 1, 10, 30, 0, tzinfo=timezone.utc)
        row = _make_row(ts=ts)
        _, _, timestamp = _extract_pnl_and_symbol(row)
        assert "2024-06-01" in timestamp


# ---------------------------------------------------------------------------
# compute_metrics
# ---------------------------------------------------------------------------


class TestComputeMetrics:
    def test_empty_list(self):
        m = compute_metrics([])
        assert m["total_pnl"] == 0.0
        assert m["win_rate"] == 0.0
        assert m["trade_count"] == 0

    def test_all_wins(self):
        m = compute_metrics([100.0, 200.0, 50.0])
        assert m["total_pnl"] == 350.0
        assert m["win_rate"] == 1.0
        assert m["avg_win"] == pytest.approx(350.0 / 3)
        assert m["avg_loss"] == 0.0
        assert m["profit_factor"] == 9999.99
        assert m["trade_count"] == 3

    def test_all_losses(self):
        m = compute_metrics([-100.0, -50.0])
        assert m["total_pnl"] == -150.0
        assert m["win_rate"] == 0.0
        assert m["avg_win"] == 0.0
        assert m["avg_loss"] == pytest.approx(-75.0)
        assert m["profit_factor"] == 0.0

    def test_mixed(self):
        m = compute_metrics([100.0, -50.0, 200.0, -30.0])
        assert m["total_pnl"] == pytest.approx(220.0)
        assert m["win_rate"] == pytest.approx(0.5)
        assert m["avg_win"] == pytest.approx(150.0)
        assert m["avg_loss"] == pytest.approx(-40.0)
        assert m["profit_factor"] == pytest.approx(300.0 / 80.0)
        assert m["trade_count"] == 4

    def test_zero_pnl_not_counted_as_win(self):
        m = compute_metrics([0.0, 100.0, -50.0])
        # zero is neither win nor loss
        assert m["win_rate"] == pytest.approx(1 / 3)

    def test_single_win(self):
        m = compute_metrics([42.0])
        assert m["total_pnl"] == 42.0
        assert m["win_rate"] == 1.0
        assert m["max_drawdown"] == 0.0

    def test_single_loss(self):
        m = compute_metrics([-10.0])
        assert m["total_pnl"] == -10.0
        assert m["win_rate"] == 0.0
        assert m["max_drawdown"] == 10.0


# ---------------------------------------------------------------------------
# compute_max_drawdown
# ---------------------------------------------------------------------------


class TestComputeMaxDrawdown:
    def test_empty(self):
        assert compute_max_drawdown([]) == 0.0

    def test_monotonically_increasing(self):
        assert compute_max_drawdown([10.0, 20.0, 30.0]) == 0.0

    def test_monotonically_decreasing(self):
        # cumulative: -10, -30, -60 → peak stays at 0, max dd = 60
        assert compute_max_drawdown([-10.0, -20.0, -30.0]) == 60.0

    def test_peak_then_trough(self):
        # cumulative: 100, 150, 50, 80
        # peak=150, trough=50, dd=100
        assert compute_max_drawdown([100.0, 50.0, -100.0, 30.0]) == 100.0

    def test_multiple_drawdowns_returns_max(self):
        # cumulative: 10, 5, 15, 5
        # dd1: 10-5=5, dd2: 15-5=10
        assert compute_max_drawdown([10.0, -5.0, 10.0, -10.0]) == 10.0

    def test_all_zeros(self):
        assert compute_max_drawdown([0.0, 0.0, 0.0]) == 0.0

    def test_recovery_after_drawdown(self):
        # cumulative: 100, 50, 150 → dd=50, then recovers
        assert compute_max_drawdown([100.0, -50.0, 100.0]) == 50.0


# ---------------------------------------------------------------------------
# _query_performance_handler
# ---------------------------------------------------------------------------


class TestQueryPerformanceHandler:
    @pytest.mark.asyncio
    async def test_basic_query(self):
        rows = [_make_row(pnl=100.0), _make_row(pnl=-50.0)]
        pool = _make_pool(rows)
        result = await _query_performance_handler(
            pool=pool, tenant_id="t1", bot_id="b1"
        )
        assert "overall" in result
        assert result["overall"]["total_pnl"] == pytest.approx(50.0)
        assert result["overall"]["trade_count"] == 2

    @pytest.mark.asyncio
    async def test_symbol_filter_passed_to_query(self):
        pool = _make_pool([_make_row(symbol="ETHUSDT", pnl=200.0)])
        result = await _query_performance_handler(
            pool=pool, tenant_id="t1", bot_id="b1", symbol="ETHUSDT"
        )
        conn = pool.acquire.return_value.__aenter__.return_value
        query = conn.fetch.call_args[0][0]
        assert "symbol=$3" in query

    @pytest.mark.asyncio
    async def test_time_range_filter(self):
        pool = _make_pool([_make_row(pnl=100.0)])
        await _query_performance_handler(
            pool=pool,
            tenant_id="t1",
            bot_id="b1",
            start_time="2024-01-01T00:00:00Z",
            end_time="2024-12-31T23:59:59Z",
        )
        conn = pool.acquire.return_value.__aenter__.return_value
        query = conn.fetch.call_args[0][0]
        assert "ts >=" in query
        assert "ts <=" in query

    @pytest.mark.asyncio
    async def test_empty_result(self):
        pool = _make_pool([])
        result = await _query_performance_handler(
            pool=pool, tenant_id="t1", bot_id="b1"
        )
        assert result["overall"]["total_pnl"] == 0.0
        assert result["overall"]["trade_count"] == 0

    @pytest.mark.asyncio
    async def test_group_by_symbol(self):
        rows = [
            _make_row(symbol="BTCUSDT", pnl=100.0),
            _make_row(symbol="BTCUSDT", pnl=-30.0),
            _make_row(symbol="ETHUSDT", pnl=50.0),
        ]
        pool = _make_pool(rows)
        result = await _query_performance_handler(
            pool=pool, tenant_id="t1", bot_id="b1", group_by_symbol=True
        )
        assert "per_symbol" in result
        assert "BTCUSDT" in result["per_symbol"]
        assert "ETHUSDT" in result["per_symbol"]
        assert result["per_symbol"]["BTCUSDT"]["total_pnl"] == pytest.approx(70.0)
        assert result["per_symbol"]["ETHUSDT"]["total_pnl"] == pytest.approx(50.0)
        # Sum of per-symbol totals equals overall
        per_sym_total = sum(
            v["total_pnl"] for v in result["per_symbol"].values()
        )
        assert per_sym_total == pytest.approx(result["overall"]["total_pnl"])

    @pytest.mark.asyncio
    async def test_group_by_symbol_not_included_by_default(self):
        rows = [_make_row(pnl=100.0)]
        pool = _make_pool(rows)
        result = await _query_performance_handler(
            pool=pool, tenant_id="t1", bot_id="b1"
        )
        assert "per_symbol" not in result

    @pytest.mark.asyncio
    async def test_none_pnl_rows_skipped(self):
        row_no_pnl = _make_row()
        payload = json.loads(row_no_pnl["payload"])
        del payload["net_pnl"]
        row_no_pnl["payload"] = json.dumps(payload)

        rows = [_make_row(pnl=100.0), row_no_pnl]
        pool = _make_pool(rows)
        result = await _query_performance_handler(
            pool=pool, tenant_id="t1", bot_id="b1"
        )
        assert result["overall"]["trade_count"] == 1
        assert result["overall"]["total_pnl"] == pytest.approx(100.0)

    @pytest.mark.asyncio
    async def test_invalid_start_time_ignored(self):
        pool = _make_pool([_make_row(pnl=50.0)])
        result = await _query_performance_handler(
            pool=pool, tenant_id="t1", bot_id="b1", start_time="not-a-date"
        )
        # Should still work, just no time filter applied
        assert result["overall"]["trade_count"] == 1

    @pytest.mark.asyncio
    async def test_parameterised_query_no_string_interpolation(self):
        pool = _make_pool([])
        await _query_performance_handler(
            pool=pool,
            tenant_id="t1",
            bot_id="b1",
            symbol="BTCUSDT",
            start_time="2024-01-01T00:00:00Z",
        )
        conn = pool.acquire.return_value.__aenter__.return_value
        query = conn.fetch.call_args[0][0]
        # No raw values should appear in the query string
        assert "BTCUSDT" not in query
        assert "t1" not in query

    @pytest.mark.asyncio
    async def test_close_events_filter_in_query(self):
        pool = _make_pool([])
        await _query_performance_handler(
            pool=pool, tenant_id="t1", bot_id="b1"
        )
        conn = pool.acquire.return_value.__aenter__.return_value
        query = conn.fetch.call_args[0][0]
        assert "position_effect" in query
        assert "close" in query

    @pytest.mark.asyncio
    async def test_order_by_ts_asc(self):
        """Trades must be ordered ASC for correct drawdown computation."""
        pool = _make_pool([])
        await _query_performance_handler(
            pool=pool, tenant_id="t1", bot_id="b1"
        )
        conn = pool.acquire.return_value.__aenter__.return_value
        query = conn.fetch.call_args[0][0]
        assert "ORDER BY ts ASC" in query


# ---------------------------------------------------------------------------
# create_query_performance_tool
# ---------------------------------------------------------------------------


class TestCreateQueryPerformanceTool:
    def test_returns_tool_definition(self):
        pool = MagicMock()
        tool = create_query_performance_tool(pool, "t1", "b1")
        assert isinstance(tool, ToolDefinition)
        assert tool.name == "query_performance"

    def test_description_non_empty(self):
        pool = MagicMock()
        tool = create_query_performance_tool(pool, "t1", "b1")
        assert len(tool.description) > 0

    def test_schema_matches(self):
        pool = MagicMock()
        tool = create_query_performance_tool(pool, "t1", "b1")
        assert tool.parameters_schema is QUERY_PERFORMANCE_SCHEMA

    @pytest.mark.asyncio
    async def test_handler_delegates_to_query(self):
        rows = [_make_row(pnl=75.0)]
        pool = _make_pool(rows)
        tool = create_query_performance_tool(pool, "t1", "b1")
        result = await tool.handler(symbol="BTCUSDT")
        assert result["overall"]["total_pnl"] == pytest.approx(75.0)

    @pytest.mark.asyncio
    async def test_handler_with_no_args(self):
        pool = _make_pool([_make_row(pnl=10.0)])
        tool = create_query_performance_tool(pool, "t1", "b1")
        result = await tool.handler()
        assert result["overall"]["trade_count"] == 1
