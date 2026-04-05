"""Unit tests for the query_backtests copilot tool."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from quantgambit.copilot.models import ToolDefinition
from quantgambit.copilot.tools.backtests import (
    QUERY_BACKTESTS_SCHEMA,
    _extract_backtest,
    _format_datetime,
    _parse_metrics,
    _query_backtests_handler,
    _safe_float,
    create_query_backtests_tool,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SENTINEL = object()


def _make_row(
    run_id: str = "run-001",
    tenant_id: str = "t1",
    bot_id: str = "b1",
    status: str = "finished",
    name: str | None = "momentum_v2",
    symbol: str | None = "BTCUSDT",
    start_date: Any = _SENTINEL,
    end_date: Any = _SENTINEL,
    created_at: Any = _SENTINEL,
    started_at: Any = _SENTINEL,
    finished_at: datetime | None = None,
    # Metrics columns (from LEFT JOIN)
    sharpe_ratio: float | None = 1.5,
    max_drawdown_pct: float | None = 8.2,
    win_rate: float | None = 0.62,
    realized_pnl: float | None = 4500.0,
    total_trades: int | None = 120,
    profit_factor: float | None = 1.8,
) -> dict[str, Any]:
    """Build a fake joined backtest_runs + backtest_metrics row."""
    if start_date is _SENTINEL:
        start_date = datetime(2024, 1, 1, tzinfo=timezone.utc)
    if end_date is _SENTINEL:
        end_date = datetime(2024, 6, 30, tzinfo=timezone.utc)
    if created_at is _SENTINEL:
        created_at = datetime(2024, 7, 1, 12, 0, 0, tzinfo=timezone.utc)
    if started_at is _SENTINEL:
        started_at = datetime(2024, 7, 1, 12, 0, 0, tzinfo=timezone.utc)
    return {
        "run_id": run_id,
        "tenant_id": tenant_id,
        "bot_id": bot_id,
        "status": status,
        "name": name,
        "symbol": symbol,
        "start_date": start_date,
        "end_date": end_date,
        "created_at": created_at,
        "started_at": started_at,
        "finished_at": finished_at,
        "sharpe_ratio": sharpe_ratio,
        "max_drawdown_pct": max_drawdown_pct,
        "win_rate": win_rate,
        "realized_pnl": realized_pnl,
        "total_trades": total_trades,
        "profit_factor": profit_factor,
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
# _format_datetime
# ---------------------------------------------------------------------------

class TestFormatDatetime:
    def test_datetime_object(self):
        dt = datetime(2024, 6, 1, 10, 30, 0, tzinfo=timezone.utc)
        result = _format_datetime(dt)
        assert "2024-06-01" in result

    def test_none(self):
        assert _format_datetime(None) is None

    def test_string_passthrough(self):
        assert _format_datetime("2024-01-01") == "2024-01-01"


# ---------------------------------------------------------------------------
# _parse_metrics
# ---------------------------------------------------------------------------

class TestParseMetrics:
    def test_dict_input(self):
        raw = {
            "sharpe_ratio": 1.5,
            "max_drawdown_pct": 8.0,
            "win_rate": 0.6,
            "realized_pnl": 1000.0,
            "total_trades": 50,
            "profit_factor": 1.8,
        }
        result = _parse_metrics(raw)
        assert result["sharpe_ratio"] == 1.5
        assert result["total_pnl"] == 1000.0
        assert result["total_trades"] == 50

    def test_none_input(self):
        assert _parse_metrics(None) == {}

    def test_invalid_json_string(self):
        assert _parse_metrics("not json") == {}

    def test_non_dict(self):
        assert _parse_metrics(42) == {}


# ---------------------------------------------------------------------------
# _extract_backtest
# ---------------------------------------------------------------------------

class TestExtractBacktest:
    def test_basic_extraction(self):
        row = _make_row()
        bt = _extract_backtest(row)
        assert bt["id"] == "run-001"
        assert bt["strategy_id"] == "momentum_v2"
        assert bt["symbol"] == "BTCUSDT"
        assert bt["status"] == "finished"
        assert "2024-01-01" in bt["date_range"]
        assert "2024-06-30" in bt["date_range"]
        assert bt["metrics"]["sharpe_ratio"] == 1.5
        assert bt["metrics"]["win_rate"] == 0.62
        assert bt["metrics"]["total_pnl"] == 4500.0
        assert bt["metrics"]["total_trades"] == 120
        assert bt["created_at"] is not None

    def test_missing_name_uses_run_id(self):
        row = _make_row(name=None)
        bt = _extract_backtest(row)
        assert bt["strategy_id"] == "run-001"

    def test_missing_symbol_defaults_to_all(self):
        row = _make_row(symbol=None)
        bt = _extract_backtest(row)
        assert bt["symbol"] == "ALL"

    def test_missing_dates(self):
        row = _make_row(start_date=None, end_date=None)
        bt = _extract_backtest(row)
        assert bt["date_range"] == "? - ?"

    def test_null_metrics(self):
        row = _make_row(
            sharpe_ratio=None,
            max_drawdown_pct=None,
            win_rate=None,
            realized_pnl=None,
            total_trades=None,
            profit_factor=None,
        )
        bt = _extract_backtest(row)
        assert bt["metrics"]["sharpe_ratio"] is None
        assert bt["metrics"]["total_pnl"] is None

    def test_all_fields_present(self):
        row = _make_row()
        bt = _extract_backtest(row)
        expected_keys = {"id", "strategy_id", "symbol", "date_range", "status", "metrics", "created_at"}
        assert set(bt.keys()) == expected_keys


# ---------------------------------------------------------------------------
# _query_backtests_handler
# ---------------------------------------------------------------------------

class TestQueryBacktestsHandler:
    @pytest.mark.asyncio
    async def test_basic_query(self):
        rows = [_make_row(), _make_row(run_id="run-002", symbol="ETHUSDT")]
        pool = _make_pool(rows)
        result = await _query_backtests_handler(
            dashboard_pool=pool, tenant_id="t1", bot_id="b1",
        )
        assert len(result) == 2
        assert result[0]["id"] == "run-001"
        assert result[1]["symbol"] == "ETHUSDT"

    @pytest.mark.asyncio
    async def test_strategy_id_filter(self):
        pool = _make_pool([_make_row()])
        await _query_backtests_handler(
            dashboard_pool=pool, tenant_id="t1", bot_id="b1",
            strategy_id="run-001",
        )
        conn = pool.acquire.return_value.__aenter__.return_value
        query_arg = conn.fetch.call_args[0][0]
        # strategy_id should match run_id OR name via parameterised placeholder
        assert "run_id=$" in query_arg or "r.run_id=$" in query_arg
        assert "name=$" in query_arg or "r.name=$" in query_arg

    @pytest.mark.asyncio
    async def test_status_filter(self):
        pool = _make_pool([])
        await _query_backtests_handler(
            dashboard_pool=pool, tenant_id="t1", bot_id="b1",
            status="finished",
        )
        conn = pool.acquire.return_value.__aenter__.return_value
        query_arg = conn.fetch.call_args[0][0]
        assert "status=$" in query_arg or "r.status=$" in query_arg

    @pytest.mark.asyncio
    async def test_limit_clamped_to_100(self):
        pool = _make_pool([])
        await _query_backtests_handler(
            dashboard_pool=pool, tenant_id="t1", bot_id="b1",
            limit=999,
        )
        conn = pool.acquire.return_value.__aenter__.return_value
        args = conn.fetch.call_args[0]
        # The last positional arg is the limit value, clamped to 100
        assert args[-1] == 100

    @pytest.mark.asyncio
    async def test_limit_minimum(self):
        pool = _make_pool([])
        await _query_backtests_handler(
            dashboard_pool=pool, tenant_id="t1", bot_id="b1",
            limit=-5,
        )
        conn = pool.acquire.return_value.__aenter__.return_value
        args = conn.fetch.call_args[0]
        assert args[-1] == 1

    @pytest.mark.asyncio
    async def test_default_limit(self):
        pool = _make_pool([])
        await _query_backtests_handler(
            dashboard_pool=pool, tenant_id="t1", bot_id="b1",
        )
        conn = pool.acquire.return_value.__aenter__.return_value
        args = conn.fetch.call_args[0]
        assert args[-1] == 20

    @pytest.mark.asyncio
    async def test_empty_result(self):
        pool = _make_pool([])
        result = await _query_backtests_handler(
            dashboard_pool=pool, tenant_id="t1", bot_id="b1",
        )
        assert result == []

    @pytest.mark.asyncio
    async def test_parameterised_query_no_string_interpolation(self):
        """Ensure SQL uses $N placeholders, not f-string interpolation of values."""
        pool = _make_pool([])
        await _query_backtests_handler(
            dashboard_pool=pool, tenant_id="t1", bot_id="b1",
            strategy_id="my-strat", status="degraded",
        )
        conn = pool.acquire.return_value.__aenter__.return_value
        query_arg = conn.fetch.call_args[0][0]
        assert "my-strat" not in query_arg
        assert "degraded" not in query_arg

    @pytest.mark.asyncio
    async def test_left_join_metrics(self):
        """The query should LEFT JOIN backtest_metrics."""
        pool = _make_pool([])
        await _query_backtests_handler(
            dashboard_pool=pool, tenant_id="t1", bot_id="b1",
        )
        conn = pool.acquire.return_value.__aenter__.return_value
        query_arg = conn.fetch.call_args[0][0]
        assert "LEFT JOIN" in query_arg
        assert "backtest_metrics" in query_arg

    @pytest.mark.asyncio
    async def test_ordered_by_started_at_desc(self):
        pool = _make_pool([])
        await _query_backtests_handler(
            dashboard_pool=pool, tenant_id="t1", bot_id="b1",
        )
        conn = pool.acquire.return_value.__aenter__.return_value
        query_arg = conn.fetch.call_args[0][0]
        assert "ORDER BY" in query_arg
        assert "DESC" in query_arg


# ---------------------------------------------------------------------------
# create_query_backtests_tool
# ---------------------------------------------------------------------------

class TestCreateQueryBacktestsTool:
    def test_returns_tool_definition(self):
        pool = _make_pool([])
        tool = create_query_backtests_tool(pool, "t1", "b1")
        assert isinstance(tool, ToolDefinition)
        assert tool.name == "query_backtests"
        assert tool.parameters_schema == QUERY_BACKTESTS_SCHEMA

    def test_description_non_empty(self):
        pool = _make_pool([])
        tool = create_query_backtests_tool(pool, "t1", "b1")
        assert len(tool.description) > 0

    @pytest.mark.asyncio
    async def test_handler_delegates_to_query(self):
        rows = [_make_row()]
        pool = _make_pool(rows)
        tool = create_query_backtests_tool(pool, "t1", "b1")
        result = await tool.handler(strategy_id="run-001")
        assert len(result) == 1
        assert result[0]["id"] == "run-001"

    @pytest.mark.asyncio
    async def test_handler_with_no_args(self):
        pool = _make_pool([_make_row()])
        tool = create_query_backtests_tool(pool, "t1", "b1")
        result = await tool.handler()
        assert len(result) == 1
