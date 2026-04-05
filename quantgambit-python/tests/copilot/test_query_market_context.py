"""Unit tests for the query_market_context copilot tool."""

from __future__ import annotations

import inspect
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock

import pytest

from quantgambit.copilot.models import ToolDefinition
from quantgambit.copilot.tools.market_context import (
    QUERY_MARKET_CONTEXT_SCHEMA,
    _query_market_context_handler,
    create_query_market_context_tool,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TENANT = "t1"
_BOT = "b1"

_TS_1 = datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
_TS_2 = datetime(2024, 1, 15, 10, 29, 0, tzinfo=timezone.utc)
_TS_3 = datetime(2024, 1, 15, 10, 28, 0, tzinfo=timezone.utc)


def _make_row(
    symbol: str = "BTCUSDT",
    ts: datetime = _TS_1,
    spread_bps: float = 1.5,
    depth_usd: float = 250000.0,
    funding_rate: float = 0.0001,
    iv: float = 0.45,
    vol: float = 0.02,
) -> dict[str, Any]:
    """Build a fake asyncpg Record-like dict."""
    return {
        "symbol": symbol,
        "ts": ts,
        "spread_bps": spread_bps,
        "depth_usd": depth_usd,
        "funding_rate": funding_rate,
        "iv": iv,
        "vol": vol,
    }


def _make_pool(
    rows: list[dict[str, Any]] | None = None,
    fail: bool = False,
) -> AsyncMock:
    """Return a mock asyncpg pool.

    The pool's ``acquire()`` context manager yields a mock connection whose
    ``fetch()`` returns *rows* (or raises on *fail*).
    """
    pool = AsyncMock()
    conn = AsyncMock()

    if fail:
        conn.fetch = AsyncMock(side_effect=Exception("DB connection failed"))
    else:
        conn.fetch = AsyncMock(return_value=rows or [])

    # pool.acquire() is used as `async with pool.acquire() as conn:`
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__ = AsyncMock(return_value=False)
    pool.acquire = lambda: ctx

    # Stash conn for assertion access in tests
    pool._mock_conn = conn
    return pool


# ---------------------------------------------------------------------------
# Handler — rows returned
# ---------------------------------------------------------------------------


class TestQueryMarketContextHandlerRows:
    @pytest.mark.asyncio
    async def test_returns_rows_for_symbol(self):
        rows = [_make_row(symbol="BTCUSDT", ts=_TS_1)]
        pool = _make_pool(rows=rows)
        result = await _query_market_context_handler(
            pool=pool, tenant_id=_TENANT, bot_id=_BOT, symbol="BTCUSDT",
        )
        assert isinstance(result, list)
        assert len(result) == 1
        entry = result[0]
        assert entry["symbol"] == "BTCUSDT"
        assert entry["ts"] == _TS_1.isoformat()
        assert entry["spread_bps"] == 1.5
        assert entry["depth_usd"] == 250000.0
        assert entry["funding_rate"] == 0.0001
        assert entry["iv"] == 0.45
        assert entry["vol"] == 0.02

    @pytest.mark.asyncio
    async def test_returns_multiple_rows(self):
        rows = [
            _make_row(symbol="BTCUSDT", ts=_TS_1),
            _make_row(symbol="BTCUSDT", ts=_TS_2),
            _make_row(symbol="ETHUSDT", ts=_TS_3),
        ]
        pool = _make_pool(rows=rows)
        result = await _query_market_context_handler(
            pool=pool, tenant_id=_TENANT, bot_id=_BOT,
        )
        assert isinstance(result, list)
        assert len(result) == 3

    @pytest.mark.asyncio
    async def test_ts_converted_to_iso_string(self):
        rows = [_make_row(ts=_TS_1)]
        pool = _make_pool(rows=rows)
        result = await _query_market_context_handler(
            pool=pool, tenant_id=_TENANT, bot_id=_BOT,
        )
        assert result[0]["ts"] == "2024-01-15T10:30:00+00:00"

    @pytest.mark.asyncio
    async def test_numeric_fields_are_floats(self):
        rows = [_make_row(spread_bps=2, depth_usd=100000, funding_rate=0, iv=1, vol=0)]
        pool = _make_pool(rows=rows)
        result = await _query_market_context_handler(
            pool=pool, tenant_id=_TENANT, bot_id=_BOT,
        )
        entry = result[0]
        for field in ("spread_bps", "depth_usd", "funding_rate", "iv", "vol"):
            assert isinstance(entry[field], float), f"{field} should be float"


# ---------------------------------------------------------------------------
# Symbol filtering
# ---------------------------------------------------------------------------


class TestQueryMarketContextSymbolFiltering:
    @pytest.mark.asyncio
    async def test_symbol_passed_to_query(self):
        pool = _make_pool(rows=[])
        await _query_market_context_handler(
            pool=pool, tenant_id=_TENANT, bot_id=_BOT, symbol="ETHUSDT",
        )
        conn = pool._mock_conn
        conn.fetch.assert_called_once()
        args = conn.fetch.call_args
        # Second positional arg (after query string) is the symbol parameter
        assert args[0][1] == "ETHUSDT"

    @pytest.mark.asyncio
    async def test_no_symbol_passes_none(self):
        pool = _make_pool(rows=[])
        await _query_market_context_handler(
            pool=pool, tenant_id=_TENANT, bot_id=_BOT,
        )
        conn = pool._mock_conn
        args = conn.fetch.call_args
        assert args[0][1] is None


# ---------------------------------------------------------------------------
# Limit parameter
# ---------------------------------------------------------------------------


class TestQueryMarketContextLimit:
    @pytest.mark.asyncio
    async def test_default_limit_is_10(self):
        pool = _make_pool(rows=[])
        await _query_market_context_handler(
            pool=pool, tenant_id=_TENANT, bot_id=_BOT,
        )
        conn = pool._mock_conn
        args = conn.fetch.call_args
        # Third positional arg is the limit parameter
        assert args[0][2] == 10

    @pytest.mark.asyncio
    async def test_custom_limit_passed(self):
        pool = _make_pool(rows=[])
        await _query_market_context_handler(
            pool=pool, tenant_id=_TENANT, bot_id=_BOT, limit=25,
        )
        conn = pool._mock_conn
        args = conn.fetch.call_args
        assert args[0][2] == 25

    @pytest.mark.asyncio
    async def test_limit_1(self):
        pool = _make_pool(rows=[])
        await _query_market_context_handler(
            pool=pool, tenant_id=_TENANT, bot_id=_BOT, limit=1,
        )
        conn = pool._mock_conn
        args = conn.fetch.call_args
        assert args[0][2] == 1

    @pytest.mark.asyncio
    async def test_limit_100(self):
        pool = _make_pool(rows=[])
        await _query_market_context_handler(
            pool=pool, tenant_id=_TENANT, bot_id=_BOT, limit=100,
        )
        conn = pool._mock_conn
        args = conn.fetch.call_args
        assert args[0][2] == 100


# ---------------------------------------------------------------------------
# Empty result
# ---------------------------------------------------------------------------


class TestQueryMarketContextEmpty:
    @pytest.mark.asyncio
    async def test_empty_rows_returns_empty_list(self):
        pool = _make_pool(rows=[])
        result = await _query_market_context_handler(
            pool=pool, tenant_id=_TENANT, bot_id=_BOT, symbol="BTCUSDT",
        )
        assert result == []

    @pytest.mark.asyncio
    async def test_empty_rows_all_symbols_returns_empty_list(self):
        pool = _make_pool(rows=[])
        result = await _query_market_context_handler(
            pool=pool, tenant_id=_TENANT, bot_id=_BOT,
        )
        assert result == []


# ---------------------------------------------------------------------------
# DB connection failure
# ---------------------------------------------------------------------------


class TestQueryMarketContextErrors:
    @pytest.mark.asyncio
    async def test_db_failure_returns_error(self):
        pool = _make_pool(fail=True)
        result = await _query_market_context_handler(
            pool=pool, tenant_id=_TENANT, bot_id=_BOT,
        )
        assert isinstance(result, dict)
        assert "error" in result

    @pytest.mark.asyncio
    async def test_db_failure_with_symbol_returns_error(self):
        pool = _make_pool(fail=True)
        result = await _query_market_context_handler(
            pool=pool, tenant_id=_TENANT, bot_id=_BOT, symbol="BTCUSDT",
        )
        assert isinstance(result, dict)
        assert "error" in result
        assert "TimescaleDB" in result["error"] or "market context" in result["error"].lower()


# ---------------------------------------------------------------------------
# SQL uses parameterised queries
# ---------------------------------------------------------------------------


class TestQueryMarketContextSQL:
    def test_handler_source_has_no_string_interpolation(self):
        """Verify the handler SQL uses $1/$2 placeholders, not f-strings or %."""
        source = inspect.getsource(_query_market_context_handler)
        # Should contain parameterised placeholders
        assert "$1" in source
        assert "$2" in source
        # Should NOT contain f-string interpolation or %-formatting in the query
        # (we check that the SELECT statement doesn't use f-string or .format)
        assert "f\"SELECT" not in source
        assert "f'SELECT" not in source
        assert '".format(' not in source
        assert "% " not in source.split("SELECT")[0] if "SELECT" in source else True


# ---------------------------------------------------------------------------
# create_query_market_context_tool
# ---------------------------------------------------------------------------


class TestCreateQueryMarketContextTool:
    def test_returns_tool_definition(self):
        pool = _make_pool()
        tool = create_query_market_context_tool(pool, _TENANT, _BOT)
        assert isinstance(tool, ToolDefinition)
        assert tool.name == "query_market_context"
        assert tool.parameters_schema == QUERY_MARKET_CONTEXT_SCHEMA

    def test_description_non_empty(self):
        pool = _make_pool()
        tool = create_query_market_context_tool(pool, _TENANT, _BOT)
        assert len(tool.description) > 0

    @pytest.mark.asyncio
    async def test_handler_delegates_with_symbol(self):
        rows = [_make_row(symbol="BTCUSDT")]
        pool = _make_pool(rows=rows)
        tool = create_query_market_context_tool(pool, _TENANT, _BOT)
        result = await tool.handler(symbol="BTCUSDT")
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["symbol"] == "BTCUSDT"

    @pytest.mark.asyncio
    async def test_handler_delegates_with_no_args(self):
        rows = [_make_row(symbol="BTCUSDT")]
        pool = _make_pool(rows=rows)
        tool = create_query_market_context_tool(pool, _TENANT, _BOT)
        result = await tool.handler()
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_handler_delegates_with_limit(self):
        rows = [_make_row()]
        pool = _make_pool(rows=rows)
        tool = create_query_market_context_tool(pool, _TENANT, _BOT)
        result = await tool.handler(limit=5)
        assert isinstance(result, list)
        conn = pool._mock_conn
        args = conn.fetch.call_args
        assert args[0][2] == 5
