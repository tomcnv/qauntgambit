"""Unit tests for the query_trade_flow copilot tool."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from quantgambit.copilot.models import ToolDefinition
from quantgambit.copilot.tools.trade_flow import (
    QUERY_TRADE_FLOW_SCHEMA,
    _query_trade_flow_handler,
    create_query_trade_flow_tool,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_trade_flow_row(
    trade_count: int = 150,
    buy_volume: float = 25.5,
    sell_volume: float = 18.3,
    vwap: float | None = 42050.0,
) -> dict[str, Any]:
    """Build a fake aggregated trade flow row dict."""
    return {
        "trade_count": trade_count,
        "buy_volume": buy_volume,
        "sell_volume": sell_volume,
        "vwap": vwap,
    }


def _make_pool(
    row: dict[str, Any] | None,
    *,
    raise_exc: Exception | None = None,
) -> MagicMock:
    """Return a mock asyncpg pool.

    *row* is the single aggregated row returned by ``conn.fetchrow``.
    If *raise_exc* is provided, ``conn.fetchrow`` raises that exception.
    """
    conn = AsyncMock()
    if raise_exc is not None:
        conn.fetchrow = AsyncMock(side_effect=raise_exc)
    else:
        conn.fetchrow = AsyncMock(return_value=row)

    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__ = AsyncMock(return_value=False)

    pool = MagicMock()
    pool.acquire.return_value = ctx
    return pool


# ---------------------------------------------------------------------------
# _query_trade_flow_handler
# ---------------------------------------------------------------------------


class TestQueryTradeFlowHandler:
    """Tests for _query_trade_flow_handler — Requirements 5.1, 5.4, 5.5."""

    @pytest.mark.asyncio
    async def test_aggregated_data_returned(self):
        """Handler returns all required fields for valid aggregated data."""
        pool = _make_pool(_make_trade_flow_row(
            trade_count=150, buy_volume=25.5, sell_volume=18.3, vwap=42050.0,
        ))
        result = await _query_trade_flow_handler(
            pool=pool, tenant_id="t1", bot_id="b1", symbol="BTCUSDT",
        )
        assert isinstance(result, dict)
        assert "error" not in result
        assert result["trade_count"] == 150
        assert result["buy_volume"] == 25.5
        assert result["sell_volume"] == 18.3
        assert result["vwap"] == 42050.0
        # imbalance = (25.5 - 18.3) / (25.5 + 18.3) ≈ 0.1643...
        expected_imbalance = (25.5 - 18.3) / (25.5 + 18.3)
        assert result["orderflow_imbalance"] == pytest.approx(expected_imbalance)
        # trades_per_second = 150 / 60 = 2.5
        assert result["trades_per_second"] == pytest.approx(2.5)

    @pytest.mark.asyncio
    async def test_output_fields(self):
        """Returned dict contains exactly the expected keys (Requirement 5.2)."""
        pool = _make_pool(_make_trade_flow_row())
        result = await _query_trade_flow_handler(
            pool=pool, tenant_id="t1", bot_id="b1", symbol="BTCUSDT",
        )
        expected_keys = {
            "trade_count", "buy_volume", "sell_volume",
            "orderflow_imbalance", "vwap", "trades_per_second",
        }
        assert set(result.keys()) == expected_keys

    @pytest.mark.asyncio
    async def test_none_row_returns_error(self):
        """None row from DB returns an error dict (Requirement 5.5)."""
        pool = _make_pool(None)
        result = await _query_trade_flow_handler(
            pool=pool, tenant_id="t1", bot_id="b1", symbol="BTCUSDT",
        )
        assert isinstance(result, dict)
        assert "error" in result
        assert "BTCUSDT" in result["error"]

    @pytest.mark.asyncio
    async def test_zero_trade_count_returns_error(self):
        """trade_count=0 returns an error dict (Requirement 5.5)."""
        pool = _make_pool(_make_trade_flow_row(trade_count=0))
        result = await _query_trade_flow_handler(
            pool=pool, tenant_id="t1", bot_id="b1", symbol="ETHUSDT",
        )
        assert isinstance(result, dict)
        assert "error" in result
        assert "ETHUSDT" in result["error"]

    @pytest.mark.asyncio
    async def test_default_window_sec(self):
        """Defaults window_sec=60 when omitted (Requirement 5.4)."""
        pool = _make_pool(None)
        await _query_trade_flow_handler(
            pool=pool, tenant_id="t1", bot_id="b1", symbol="BTCUSDT",
        )
        conn = pool.acquire.return_value.__aenter__.return_value
        args = conn.fetchrow.call_args[0]
        # The 4th positional arg ($4) is the window_sec as string
        assert args[4] == "60"

    @pytest.mark.asyncio
    async def test_division_by_zero_handling(self):
        """VWAP=None and imbalance=0.0 when total volume is 0."""
        pool = _make_pool(_make_trade_flow_row(
            trade_count=5, buy_volume=0.0, sell_volume=0.0, vwap=None,
        ))
        result = await _query_trade_flow_handler(
            pool=pool, tenant_id="t1", bot_id="b1", symbol="BTCUSDT",
        )
        assert result["vwap"] is None
        assert result["orderflow_imbalance"] == 0.0

    @pytest.mark.asyncio
    async def test_database_exception_returns_error(self):
        """Database errors are caught and returned as an error dict."""
        pool = _make_pool(None, raise_exc=RuntimeError("connection lost"))
        result = await _query_trade_flow_handler(
            pool=pool, tenant_id="t1", bot_id="b1", symbol="BTCUSDT",
        )
        assert isinstance(result, dict)
        assert "error" in result
        assert "Failed" in result["error"]

    @pytest.mark.asyncio
    async def test_query_scoped_to_tenant_and_bot(self):
        """SQL query includes tenant_id and bot_id as parameters (Requirement 5.6)."""
        pool = _make_pool(None)
        await _query_trade_flow_handler(
            pool=pool, tenant_id="tenant-abc", bot_id="bot-xyz", symbol="ETHUSDT",
        )
        conn = pool.acquire.return_value.__aenter__.return_value
        args = conn.fetchrow.call_args[0]
        assert args[1] == "tenant-abc"
        assert args[2] == "bot-xyz"


# ---------------------------------------------------------------------------
# create_query_trade_flow_tool
# ---------------------------------------------------------------------------


class TestCreateQueryTradeFlowTool:
    """Tests for the factory function — Requirement 8.2."""

    def test_returns_tool_definition(self):
        pool = _make_pool(None)
        tool = create_query_trade_flow_tool(pool, "t1", "b1")
        assert isinstance(tool, ToolDefinition)
        assert tool.name == "query_trade_flow"
        assert tool.parameters_schema == QUERY_TRADE_FLOW_SCHEMA

    def test_description_non_empty(self):
        pool = _make_pool(None)
        tool = create_query_trade_flow_tool(pool, "t1", "b1")
        assert len(tool.description) > 0

    @pytest.mark.asyncio
    async def test_handler_delegates_to_query(self):
        pool = _make_pool(_make_trade_flow_row())
        tool = create_query_trade_flow_tool(pool, "t1", "b1")
        result = await tool.handler(symbol="BTCUSDT")
        assert isinstance(result, dict)
        assert "trade_count" in result

    @pytest.mark.asyncio
    async def test_handler_passes_optional_params(self):
        pool = _make_pool(None)
        tool = create_query_trade_flow_tool(pool, "t1", "b1")
        await tool.handler(symbol="ETHUSDT", window_sec=300)
        conn = pool.acquire.return_value.__aenter__.return_value
        args = conn.fetchrow.call_args[0]
        assert args[4] == "300"
