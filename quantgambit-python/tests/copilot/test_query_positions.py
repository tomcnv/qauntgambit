"""Unit tests for the query_positions copilot tool."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from quantgambit.copilot.models import ToolDefinition
from quantgambit.copilot.tools.positions import (
    QUERY_POSITIONS_SCHEMA,
    _compute_unrealized_pnl,
    _extract_position,
    _query_positions_handler,
    _safe_float,
    create_query_positions_tool,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_position(
    symbol: str = "BTCUSDT",
    side: str = "long",
    size: float = 0.5,
    entry_price: float = 50000.0,
    reference_price: float = 51000.0,
    stop_loss: float = 49000.0,
    take_profit: float = 53000.0,
    unrealized_pnl: float | None = None,
) -> dict[str, Any]:
    """Build a fake Redis position record."""
    pos: dict[str, Any] = {
        "symbol": symbol,
        "side": side,
        "size": size,
        "entry_price": entry_price,
        "reference_price": reference_price,
        "stop_loss": stop_loss,
        "take_profit": take_profit,
    }
    if unrealized_pnl is not None:
        pos["unrealized_pnl"] = unrealized_pnl
    return pos


def _make_redis_snapshot(positions: list[dict[str, Any]]) -> str:
    """Serialise positions into the Redis snapshot JSON format."""
    return json.dumps({"positions": positions, "count": len(positions)})


def _make_redis_client(snapshot_json: str | None = None) -> AsyncMock:
    """Return a mock Redis client that returns *snapshot_json* on ``get``."""
    client = AsyncMock()
    client.get = AsyncMock(return_value=snapshot_json)
    return client


def _make_pool(rows: list[dict[str, Any]] | None = None) -> MagicMock:
    """Return a mock asyncpg pool.  *rows* are returned by ``conn.fetchrow``."""
    conn = AsyncMock()
    if rows:
        conn.fetchrow = AsyncMock(return_value=rows[0])
    else:
        conn.fetchrow = AsyncMock(return_value=None)
    conn.fetch = AsyncMock(return_value=rows or [])

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
# _compute_unrealized_pnl
# ---------------------------------------------------------------------------

class TestComputeUnrealizedPnl:
    def test_long_profit(self):
        pnl = _compute_unrealized_pnl("long", 50000.0, 51000.0, 1.0)
        assert pnl == 1000.0

    def test_long_loss(self):
        pnl = _compute_unrealized_pnl("long", 50000.0, 49000.0, 1.0)
        assert pnl == -1000.0

    def test_short_profit(self):
        pnl = _compute_unrealized_pnl("short", 50000.0, 49000.0, 1.0)
        assert pnl == 1000.0

    def test_short_loss(self):
        pnl = _compute_unrealized_pnl("short", 50000.0, 51000.0, 1.0)
        assert pnl == -1000.0

    def test_buy_alias(self):
        pnl = _compute_unrealized_pnl("buy", 100.0, 110.0, 2.0)
        assert pnl == 20.0

    def test_sell_alias(self):
        pnl = _compute_unrealized_pnl("sell", 100.0, 90.0, 2.0)
        assert pnl == 20.0

    def test_none_entry_price(self):
        assert _compute_unrealized_pnl("long", None, 51000.0, 1.0) is None

    def test_none_current_price(self):
        assert _compute_unrealized_pnl("long", 50000.0, None, 1.0) is None

    def test_none_size(self):
        assert _compute_unrealized_pnl("long", 50000.0, 51000.0, None) is None

    def test_zero_entry_price(self):
        assert _compute_unrealized_pnl("long", 0.0, 51000.0, 1.0) is None

    def test_zero_size(self):
        assert _compute_unrealized_pnl("long", 50000.0, 51000.0, 0.0) is None

    def test_unknown_side(self):
        assert _compute_unrealized_pnl("unknown", 50000.0, 51000.0, 1.0) is None


# ---------------------------------------------------------------------------
# _extract_position
# ---------------------------------------------------------------------------

class TestExtractPosition:
    def test_basic_extraction(self):
        pos = _make_position()
        result = _extract_position(pos)
        assert result["symbol"] == "BTCUSDT"
        assert result["side"] == "long"
        assert result["size"] == 0.5
        assert result["entry_price"] == 50000.0
        assert result["current_price"] == 51000.0
        assert result["stop_loss"] == 49000.0
        assert result["take_profit"] == 53000.0

    def test_side_normalization_buy(self):
        pos = _make_position(side="buy")
        result = _extract_position(pos)
        assert result["side"] == "long"

    def test_side_normalization_sell(self):
        pos = _make_position(side="sell")
        result = _extract_position(pos)
        assert result["side"] == "short"

    def test_uses_reference_price_as_current(self):
        pos = _make_position(reference_price=52000.0)
        result = _extract_position(pos)
        assert result["current_price"] == 52000.0

    def test_falls_back_to_current_price_field(self):
        pos = _make_position()
        del pos["reference_price"]
        pos["current_price"] = 48000.0
        result = _extract_position(pos)
        assert result["current_price"] == 48000.0

    def test_precomputed_unrealized_pnl(self):
        pos = _make_position(unrealized_pnl=500.0)
        result = _extract_position(pos)
        assert result["unrealized_pnl"] == 500.0

    def test_computed_unrealized_pnl_when_missing(self):
        pos = _make_position()  # long, entry=50000, ref=51000, size=0.5
        result = _extract_position(pos)
        # (51000 - 50000) * 0.5 = 500.0
        assert result["unrealized_pnl"] == 500.0

    def test_missing_symbol_defaults(self):
        pos = _make_position()
        pos["symbol"] = None
        result = _extract_position(pos)
        assert result["symbol"] == "UNKNOWN"

    def test_all_fields_present(self):
        pos = _make_position()
        result = _extract_position(pos)
        expected_keys = {
            "symbol", "side", "size", "entry_price", "current_price",
            "unrealized_pnl", "stop_loss", "take_profit",
        }
        assert set(result.keys()) == expected_keys

    def test_camel_case_field_fallbacks(self):
        pos = {
            "symbol": "ETHUSDT",
            "side": "long",
            "size": 1.0,
            "entryPrice": 3000.0,
            "currentPrice": 3100.0,
            "stopLoss": 2900.0,
            "takeProfit": 3300.0,
        }
        result = _extract_position(pos)
        assert result["entry_price"] == 3000.0
        assert result["current_price"] == 3100.0
        assert result["stop_loss"] == 2900.0
        assert result["take_profit"] == 3300.0


# ---------------------------------------------------------------------------
# _query_positions_handler
# ---------------------------------------------------------------------------

class TestQueryPositionsHandler:
    @pytest.mark.asyncio
    async def test_reads_from_redis(self):
        positions = [_make_position(), _make_position(symbol="ETHUSDT")]
        redis = _make_redis_client(_make_redis_snapshot(positions))
        pool = _make_pool()
        result = await _query_positions_handler(
            pool=pool, redis_client=redis, tenant_id="t1", bot_id="b1",
        )
        assert len(result) == 2
        assert result[0]["symbol"] == "BTCUSDT"
        assert result[1]["symbol"] == "ETHUSDT"

    @pytest.mark.asyncio
    async def test_redis_key_format(self):
        redis = _make_redis_client(None)
        pool = _make_pool()
        await _query_positions_handler(
            pool=pool, redis_client=redis, tenant_id="t1", bot_id="b1",
        )
        redis.get.assert_called_once_with("quantgambit:t1:b1:positions:latest")

    @pytest.mark.asyncio
    async def test_symbol_filter(self):
        positions = [
            _make_position(symbol="BTCUSDT"),
            _make_position(symbol="ETHUSDT"),
        ]
        redis = _make_redis_client(_make_redis_snapshot(positions))
        pool = _make_pool()
        result = await _query_positions_handler(
            pool=pool, redis_client=redis, tenant_id="t1", bot_id="b1",
            symbol="ETHUSDT",
        )
        assert len(result) == 1
        assert result[0]["symbol"] == "ETHUSDT"

    @pytest.mark.asyncio
    async def test_symbol_filter_case_insensitive(self):
        positions = [_make_position(symbol="BTCUSDT")]
        redis = _make_redis_client(_make_redis_snapshot(positions))
        pool = _make_pool()
        result = await _query_positions_handler(
            pool=pool, redis_client=redis, tenant_id="t1", bot_id="b1",
            symbol="btcusdt",
        )
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_filters_zero_size_positions(self):
        positions = [
            _make_position(size=0.5),
            _make_position(symbol="ETHUSDT", size=0.0),
        ]
        redis = _make_redis_client(_make_redis_snapshot(positions))
        pool = _make_pool()
        result = await _query_positions_handler(
            pool=pool, redis_client=redis, tenant_id="t1", bot_id="b1",
        )
        assert len(result) == 1
        assert result[0]["symbol"] == "BTCUSDT"

    @pytest.mark.asyncio
    async def test_falls_back_to_timescale_when_redis_empty(self):
        redis = _make_redis_client(None)
        ts_payload = json.dumps({"positions": [_make_position()]})
        pool = _make_pool([{"payload": ts_payload}])
        result = await _query_positions_handler(
            pool=pool, redis_client=redis, tenant_id="t1", bot_id="b1",
        )
        assert len(result) == 1
        assert result[0]["symbol"] == "BTCUSDT"

    @pytest.mark.asyncio
    async def test_timescale_fallback_single_event(self):
        """TimescaleDB row with a single position event (no 'positions' key)."""
        redis = _make_redis_client(None)
        single_pos = _make_position()
        single_pos["event_type"] = "open"
        ts_payload = json.dumps(single_pos)
        pool = _make_pool([{"payload": ts_payload}])
        result = await _query_positions_handler(
            pool=pool, redis_client=redis, tenant_id="t1", bot_id="b1",
        )
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_empty_redis_and_timescale(self):
        redis = _make_redis_client(None)
        pool = _make_pool()
        result = await _query_positions_handler(
            pool=pool, redis_client=redis, tenant_id="t1", bot_id="b1",
        )
        assert result == []

    @pytest.mark.asyncio
    async def test_redis_failure_falls_back(self):
        redis = AsyncMock()
        redis.get = AsyncMock(side_effect=Exception("connection refused"))
        pool = _make_pool()
        result = await _query_positions_handler(
            pool=pool, redis_client=redis, tenant_id="t1", bot_id="b1",
        )
        assert result == []

    @pytest.mark.asyncio
    async def test_redis_bytes_response(self):
        positions = [_make_position()]
        snapshot = _make_redis_snapshot(positions).encode("utf-8")
        redis = _make_redis_client(snapshot)
        pool = _make_pool()
        result = await _query_positions_handler(
            pool=pool, redis_client=redis, tenant_id="t1", bot_id="b1",
        )
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_timescale_uses_parameterised_query(self):
        redis = _make_redis_client(None)
        pool = _make_pool()
        await _query_positions_handler(
            pool=pool, redis_client=redis, tenant_id="t1", bot_id="b1",
        )
        conn = pool.acquire.return_value.__aenter__.return_value
        query_arg = conn.fetchrow.call_args[0][0]
        assert "$1" in query_arg
        assert "$2" in query_arg
        # No literal values interpolated
        assert "t1" not in query_arg
        assert "b1" not in query_arg


# ---------------------------------------------------------------------------
# create_query_positions_tool
# ---------------------------------------------------------------------------

class TestCreateQueryPositionsTool:
    def test_returns_tool_definition(self):
        pool = _make_pool()
        redis = _make_redis_client(None)
        tool = create_query_positions_tool(pool, redis, "t1", "b1")
        assert isinstance(tool, ToolDefinition)
        assert tool.name == "query_positions"
        assert tool.parameters_schema == QUERY_POSITIONS_SCHEMA

    def test_description_non_empty(self):
        pool = _make_pool()
        redis = _make_redis_client(None)
        tool = create_query_positions_tool(pool, redis, "t1", "b1")
        assert len(tool.description) > 0

    @pytest.mark.asyncio
    async def test_handler_delegates_to_query(self):
        positions = [_make_position()]
        redis = _make_redis_client(_make_redis_snapshot(positions))
        pool = _make_pool()
        tool = create_query_positions_tool(pool, redis, "t1", "b1")
        result = await tool.handler(symbol="BTCUSDT")
        assert len(result) == 1
        assert result[0]["symbol"] == "BTCUSDT"

    @pytest.mark.asyncio
    async def test_handler_with_no_args(self):
        positions = [_make_position()]
        redis = _make_redis_client(_make_redis_snapshot(positions))
        pool = _make_pool()
        tool = create_query_positions_tool(pool, redis, "t1", "b1")
        result = await tool.handler()
        assert len(result) == 1
