"""Unit tests for the query_candles copilot tool."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from quantgambit.copilot.models import ToolDefinition
from quantgambit.copilot.tools.candles import (
    QUERY_CANDLES_SCHEMA,
    _query_candles_handler,
    create_query_candles_tool,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_candle_row(
    ts: datetime | None = None,
    open_: float = 42000.0,
    high: float = 42100.0,
    low: float = 41900.0,
    close: float = 42050.0,
    volume: float = 12.5,
) -> dict[str, Any]:
    """Build a fake ``market_candles`` row dict."""
    if ts is None:
        ts = datetime(2024, 6, 15, 10, 0, 0, tzinfo=timezone.utc)
    return {
        "ts": ts,
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    }


def _make_pool(rows: list[dict[str, Any]], *, raise_exc: Exception | None = None) -> MagicMock:
    """Return a mock asyncpg pool.

    If *raise_exc* is provided, ``conn.fetch`` will raise that exception
    instead of returning rows.
    """
    conn = AsyncMock()
    if raise_exc is not None:
        conn.fetch = AsyncMock(side_effect=raise_exc)
    else:
        conn.fetch = AsyncMock(return_value=rows)

    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__ = AsyncMock(return_value=False)

    pool = MagicMock()
    pool.acquire.return_value = ctx
    return pool


# ---------------------------------------------------------------------------
# _query_candles_handler
# ---------------------------------------------------------------------------


class TestQueryCandlesHandler:
    """Tests for _query_candles_handler — Requirements 4.1, 4.3, 4.4."""

    @pytest.mark.asyncio
    async def test_known_rows_returned(self):
        """Handler returns well-formed OHLCV dicts for known rows."""
        rows = [
            _make_candle_row(open_=100.0, high=110.0, low=90.0, close=105.0, volume=5.0),
            _make_candle_row(
                ts=datetime(2024, 6, 15, 10, 1, 0, tzinfo=timezone.utc),
                open_=105.0, high=115.0, low=95.0, close=110.0, volume=8.0,
            ),
        ]
        pool = _make_pool(rows)
        result = await _query_candles_handler(
            pool=pool, tenant_id="t1", bot_id="b1", symbol="BTCUSDT",
        )
        assert isinstance(result, list)
        assert len(result) == 2
        first = result[0]
        assert first["open"] == 100.0
        assert first["high"] == 110.0
        assert first["low"] == 90.0
        assert first["close"] == 105.0
        assert first["volume"] == 5.0
        assert first["ts"] is not None

    @pytest.mark.asyncio
    async def test_output_fields(self):
        """Each returned candle contains exactly the expected keys."""
        pool = _make_pool([_make_candle_row()])
        result = await _query_candles_handler(
            pool=pool, tenant_id="t1", bot_id="b1", symbol="BTCUSDT",
        )
        expected_keys = {"ts", "open", "high", "low", "close", "volume"}
        assert set(result[0].keys()) == expected_keys

    @pytest.mark.asyncio
    async def test_timestamp_iso_format(self):
        """Datetime timestamps are serialised to ISO-8601 strings."""
        ts = datetime(2024, 6, 15, 10, 30, 0, tzinfo=timezone.utc)
        pool = _make_pool([_make_candle_row(ts=ts)])
        result = await _query_candles_handler(
            pool=pool, tenant_id="t1", bot_id="b1", symbol="BTCUSDT",
        )
        assert "2024-06-15" in result[0]["ts"]

    @pytest.mark.asyncio
    async def test_empty_result_returns_error(self):
        """Empty result set returns an error dict (Requirement 4.4)."""
        pool = _make_pool([])
        result = await _query_candles_handler(
            pool=pool, tenant_id="t1", bot_id="b1", symbol="BTCUSDT",
        )
        assert isinstance(result, dict)
        assert "error" in result
        assert "BTCUSDT" in result["error"]

    @pytest.mark.asyncio
    async def test_default_timeframe_and_limit(self):
        """Defaults timeframe_sec=60 and limit=100 when omitted (Requirement 4.3)."""
        pool = _make_pool([])
        await _query_candles_handler(
            pool=pool, tenant_id="t1", bot_id="b1", symbol="BTCUSDT",
        )
        conn = pool.acquire.return_value.__aenter__.return_value
        args = conn.fetch.call_args[0]
        # positional args: query, tenant_id, bot_id, symbol, timeframe_sec, limit
        assert args[4] == 60   # timeframe_sec default
        assert args[5] == 100  # limit default

    @pytest.mark.asyncio
    async def test_limit_clamped_to_500(self):
        """Limit values above 500 are clamped down."""
        pool = _make_pool([])
        await _query_candles_handler(
            pool=pool, tenant_id="t1", bot_id="b1", symbol="BTCUSDT", limit=9999,
        )
        conn = pool.acquire.return_value.__aenter__.return_value
        args = conn.fetch.call_args[0]
        assert args[5] == 500

    @pytest.mark.asyncio
    async def test_limit_minimum_is_one(self):
        """Limit values below 1 are clamped up to 1."""
        pool = _make_pool([])
        await _query_candles_handler(
            pool=pool, tenant_id="t1", bot_id="b1", symbol="BTCUSDT", limit=-10,
        )
        conn = pool.acquire.return_value.__aenter__.return_value
        args = conn.fetch.call_args[0]
        assert args[5] == 1

    @pytest.mark.asyncio
    async def test_database_exception_returns_error(self):
        """Database errors are caught and returned as an error dict."""
        pool = _make_pool([], raise_exc=RuntimeError("connection lost"))
        result = await _query_candles_handler(
            pool=pool, tenant_id="t1", bot_id="b1", symbol="BTCUSDT",
        )
        assert isinstance(result, dict)
        assert "error" in result
        assert "Failed" in result["error"]

    @pytest.mark.asyncio
    async def test_query_scoped_to_tenant_and_bot(self):
        """SQL query includes tenant_id and bot_id as parameters (Requirement 4.6)."""
        pool = _make_pool([])
        await _query_candles_handler(
            pool=pool, tenant_id="tenant-abc", bot_id="bot-xyz", symbol="ETHUSDT",
        )
        conn = pool.acquire.return_value.__aenter__.return_value
        args = conn.fetch.call_args[0]
        assert args[1] == "tenant-abc"
        assert args[2] == "bot-xyz"

    @pytest.mark.asyncio
    async def test_numeric_fields_are_floats(self):
        """OHLCV numeric fields are returned as Python floats."""
        pool = _make_pool([_make_candle_row(open_=100, high=110, low=90, close=105, volume=5)])
        result = await _query_candles_handler(
            pool=pool, tenant_id="t1", bot_id="b1", symbol="BTCUSDT",
        )
        candle = result[0]
        for key in ("open", "high", "low", "close", "volume"):
            assert isinstance(candle[key], float), f"{key} should be float"


# ---------------------------------------------------------------------------
# create_query_candles_tool
# ---------------------------------------------------------------------------


class TestCreateQueryCandlesTool:
    """Tests for the factory function — Requirement 8.1."""

    def test_returns_tool_definition(self):
        pool = _make_pool([])
        tool = create_query_candles_tool(pool, "t1", "b1")
        assert isinstance(tool, ToolDefinition)
        assert tool.name == "query_candles"
        assert tool.parameters_schema == QUERY_CANDLES_SCHEMA

    def test_description_non_empty(self):
        pool = _make_pool([])
        tool = create_query_candles_tool(pool, "t1", "b1")
        assert len(tool.description) > 0

    @pytest.mark.asyncio
    async def test_handler_delegates_to_query(self):
        rows = [_make_candle_row()]
        pool = _make_pool(rows)
        tool = create_query_candles_tool(pool, "t1", "b1")
        result = await tool.handler(symbol="BTCUSDT")
        assert isinstance(result, list)
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_handler_passes_optional_params(self):
        pool = _make_pool([])
        tool = create_query_candles_tool(pool, "t1", "b1")
        await tool.handler(symbol="ETHUSDT", timeframe_sec=300, limit=50)
        conn = pool.acquire.return_value.__aenter__.return_value
        args = conn.fetch.call_args[0]
        assert args[4] == 300  # timeframe_sec
        assert args[5] == 50   # limit
