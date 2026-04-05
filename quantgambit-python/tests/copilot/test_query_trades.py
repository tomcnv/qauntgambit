"""Unit tests for the query_trades copilot tool."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from quantgambit.copilot.models import ToolDefinition
from quantgambit.copilot.tools.trades import (
    QUERY_TRADES_SCHEMA,
    _extract_trade,
    _parse_payload,
    _query_trades_handler,
    _safe_float,
    create_query_trades_tool,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_row(
    symbol: str = "BTCUSDT",
    side: str = "buy",
    entry_price: float = 50000.0,
    exit_price: float = 51000.0,
    size: float = 0.1,
    pnl: float = 100.0,
    ts: datetime | None = None,
    position_effect: str = "close",
    reason: str = "position_close",
) -> dict[str, Any]:
    """Build a fake ``order_events`` row dict."""
    if ts is None:
        ts = datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
    payload = {
        "side": side,
        "entry_price": entry_price,
        "exit_price": exit_price,
        "size": size,
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
        d = {"a": 1}
        assert _parse_payload(d) is d

    def test_json_string(self):
        assert _parse_payload('{"x": 2}') == {"x": 2}

    def test_invalid_json(self):
        assert _parse_payload("not json") == {}

    def test_none(self):
        assert _parse_payload(None) == {}


# ---------------------------------------------------------------------------
# _extract_trade
# ---------------------------------------------------------------------------

class TestExtractTrade:
    def test_basic_extraction(self):
        row = _make_row()
        trade = _extract_trade(row)
        assert trade["symbol"] == "BTCUSDT"
        assert trade["side"] == "buy"
        assert trade["entry_price"] == 50000.0
        assert trade["exit_price"] == 51000.0
        assert trade["size"] == 0.1
        assert trade["pnl"] == 100.0
        assert trade["timestamp"] is not None

    def test_side_normalization_long(self):
        row = _make_row(side="long")
        trade = _extract_trade(row)
        assert trade["side"] == "buy"

    def test_side_normalization_short(self):
        row = _make_row(side="short")
        trade = _extract_trade(row)
        assert trade["side"] == "sell"

    def test_missing_symbol_falls_back(self):
        row = _make_row()
        row["symbol"] = None
        # Symbol should come from payload
        payload = json.loads(row["payload"])
        payload["symbol"] = "ETHUSDT"
        row["payload"] = json.dumps(payload)
        trade = _extract_trade(row)
        assert trade["symbol"] == "ETHUSDT"

    def test_payload_as_dict(self):
        row = _make_row()
        row["payload"] = json.loads(row["payload"])
        trade = _extract_trade(row)
        assert trade["entry_price"] == 50000.0

    def test_timestamp_iso_format(self):
        ts = datetime(2024, 6, 1, 10, 30, 0, tzinfo=timezone.utc)
        row = _make_row(ts=ts)
        trade = _extract_trade(row)
        assert "2024-06-01" in trade["timestamp"]

    def test_all_fields_present(self):
        row = _make_row()
        trade = _extract_trade(row)
        expected_keys = {"symbol", "side", "entry_price", "exit_price", "size", "pnl", "timestamp"}
        assert set(trade.keys()) == expected_keys


# ---------------------------------------------------------------------------
# _query_trades_handler
# ---------------------------------------------------------------------------

class TestQueryTradesHandler:
    @pytest.mark.asyncio
    async def test_basic_query(self):
        rows = [_make_row(), _make_row(symbol="ETHUSDT")]
        pool = _make_pool(rows)
        result = await _query_trades_handler(
            pool=pool, tenant_id="t1", bot_id="b1",
        )
        assert len(result) == 2
        assert result[0]["symbol"] == "BTCUSDT"
        assert result[1]["symbol"] == "ETHUSDT"

    @pytest.mark.asyncio
    async def test_symbol_filter_passed_to_query(self):
        pool = _make_pool([_make_row(symbol="BTCUSDT")])
        await _query_trades_handler(
            pool=pool, tenant_id="t1", bot_id="b1", symbol="BTCUSDT",
        )
        conn = pool.acquire.return_value.__aenter__.return_value
        query_arg = conn.fetch.call_args[0][0]
        # Symbol should be a parameterised placeholder, not interpolated
        assert "symbol=$" in query_arg

    @pytest.mark.asyncio
    async def test_time_range_filter(self):
        pool = _make_pool([])
        await _query_trades_handler(
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
    async def test_side_filter(self):
        rows = [
            _make_row(side="buy"),
            _make_row(side="sell"),
        ]
        pool = _make_pool(rows)
        result = await _query_trades_handler(
            pool=pool, tenant_id="t1", bot_id="b1", side="buy",
        )
        assert all(t["side"] == "buy" for t in result)

    @pytest.mark.asyncio
    async def test_limit_clamped(self):
        pool = _make_pool([])
        await _query_trades_handler(
            pool=pool, tenant_id="t1", bot_id="b1", limit=9999,
        )
        conn = pool.acquire.return_value.__aenter__.return_value
        # The last positional arg to fetch is the limit value
        args = conn.fetch.call_args[0]
        # limit should be clamped to 500
        assert args[-1] == 500

    @pytest.mark.asyncio
    async def test_limit_minimum(self):
        pool = _make_pool([])
        await _query_trades_handler(
            pool=pool, tenant_id="t1", bot_id="b1", limit=-5,
        )
        conn = pool.acquire.return_value.__aenter__.return_value
        args = conn.fetch.call_args[0]
        assert args[-1] == 1

    @pytest.mark.asyncio
    async def test_empty_result(self):
        pool = _make_pool([])
        result = await _query_trades_handler(
            pool=pool, tenant_id="t1", bot_id="b1",
        )
        assert result == []

    @pytest.mark.asyncio
    async def test_invalid_start_time_ignored(self):
        pool = _make_pool([])
        # Should not raise — invalid date is silently skipped
        result = await _query_trades_handler(
            pool=pool, tenant_id="t1", bot_id="b1", start_time="not-a-date",
        )
        assert result == []

    @pytest.mark.asyncio
    async def test_parameterised_query_no_string_interpolation(self):
        """Ensure SQL uses $N placeholders, not f-string interpolation of values."""
        pool = _make_pool([])
        await _query_trades_handler(
            pool=pool,
            tenant_id="t1",
            bot_id="b1",
            symbol="BTCUSDT",
            start_time="2024-01-01T00:00:00Z",
            end_time="2024-12-31T23:59:59Z",
        )
        conn = pool.acquire.return_value.__aenter__.return_value
        query_arg = conn.fetch.call_args[0][0]
        # No literal values should appear in the query
        assert "BTCUSDT" not in query_arg
        assert "2024-01-01" not in query_arg

    @pytest.mark.asyncio
    async def test_close_events_filter_in_query(self):
        """The query should only return close events (trades with PnL)."""
        pool = _make_pool([])
        await _query_trades_handler(
            pool=pool, tenant_id="t1", bot_id="b1",
        )
        conn = pool.acquire.return_value.__aenter__.return_value
        query_arg = conn.fetch.call_args[0][0]
        assert "position_effect" in query_arg
        assert "close" in query_arg


# ---------------------------------------------------------------------------
# create_query_trades_tool
# ---------------------------------------------------------------------------

class TestCreateQueryTradesTool:
    def test_returns_tool_definition(self):
        pool = _make_pool([])
        tool = create_query_trades_tool(pool, "t1", "b1")
        assert isinstance(tool, ToolDefinition)
        assert tool.name == "query_trades"
        assert tool.parameters_schema == QUERY_TRADES_SCHEMA

    def test_description_non_empty(self):
        pool = _make_pool([])
        tool = create_query_trades_tool(pool, "t1", "b1")
        assert len(tool.description) > 0

    @pytest.mark.asyncio
    async def test_handler_delegates_to_query(self):
        rows = [_make_row()]
        pool = _make_pool(rows)
        tool = create_query_trades_tool(pool, "t1", "b1")
        result = await tool.handler(symbol="BTCUSDT")
        assert len(result) == 1
        assert result[0]["symbol"] == "BTCUSDT"

    @pytest.mark.asyncio
    async def test_handler_with_no_args(self):
        pool = _make_pool([_make_row()])
        tool = create_query_trades_tool(pool, "t1", "b1")
        result = await tool.handler()
        assert len(result) == 1
