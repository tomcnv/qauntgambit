"""Unit tests for the query_market_price copilot tool."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from quantgambit.copilot.models import ToolDefinition
from quantgambit.copilot.tools.market_price import (
    QUERY_MARKET_PRICE_SCHEMA,
    _parse_orderbook_entry,
    _query_market_price_handler,
    _resolve_exchange,
    create_query_market_price_tool,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DEFAULT_BIDS = [[67000.5, 1.0], [66999.0, 2.0]]
_DEFAULT_ASKS = [[67001.0, 0.5], [67002.0, 1.5]]


def _make_orderbook_entry(
    symbol: str = "BTCUSDT",
    bids: list[list[float]] | None = None,
    asks: list[list[float]] | None = None,
) -> dict[str, Any]:
    """Build a fake orderbook stream entry."""
    return {
        "symbol": symbol,
        "bids": json.dumps(bids if bids is not None else _DEFAULT_BIDS),
        "asks": json.dumps(asks if asks is not None else _DEFAULT_ASKS),
    }


def _make_redis(
    entries: list[tuple[str, dict[str, Any]]] | None = None,
    provider: str | None = None,
    fail: bool = False,
) -> AsyncMock:
    """Return a mock Redis client for orderbook stream reads."""
    redis = AsyncMock()

    if fail:
        redis.xrevrange = AsyncMock(side_effect=ConnectionError("Redis down"))
        redis.get = AsyncMock(side_effect=ConnectionError("Redis down"))
        return redis

    redis.xrevrange = AsyncMock(return_value=entries or [])

    async def _get(key: str) -> bytes | None:
        if provider and "market_data:provider" in key:
            return provider.encode("utf-8")
        return None

    redis.get = AsyncMock(side_effect=_get)
    return redis


# ---------------------------------------------------------------------------
# _parse_orderbook_entry
# ---------------------------------------------------------------------------


class TestParseOrderbookEntry:
    def test_valid_entry(self):
        entry = _make_orderbook_entry()
        result = _parse_orderbook_entry(entry, "binance")
        assert result is not None
        assert result["symbol"] == "BTCUSDT"
        assert result["best_bid"] == 67000.5
        assert result["best_ask"] == 67001.0
        assert result["exchange"] == "binance"

    def test_returns_none_for_empty_bids(self):
        entry = _make_orderbook_entry(bids=[])
        result = _parse_orderbook_entry(entry, "binance")
        assert result is None

    def test_returns_none_for_empty_asks(self):
        entry = _make_orderbook_entry(asks=[])
        result = _parse_orderbook_entry(entry, "binance")
        assert result is None

    def test_returns_none_for_missing_symbol(self):
        entry = {"bids": "[[1,1]]", "asks": "[[2,1]]"}
        result = _parse_orderbook_entry(entry, "binance")
        assert result is None

    def test_returns_none_for_zero_bid(self):
        entry = _make_orderbook_entry(bids=[[0, 1.0]], asks=[[67001.0, 0.5]])
        result = _parse_orderbook_entry(entry, "binance")
        assert result is None

    def test_handles_bytes_fields(self):
        entry = {
            b"symbol": b"ETHUSDT",
            b"bids": b'[[3000.0, 1.0]]',
            b"asks": b'[[3001.0, 1.0]]',
        }
        result = _parse_orderbook_entry(entry, "binance")
        assert result is not None
        assert result["symbol"] == "ETHUSDT"

    def test_returns_none_for_malformed_json(self):
        entry = {"symbol": "BTCUSDT", "bids": "not-json{", "asks": "[[1,1]]"}
        result = _parse_orderbook_entry(entry, "binance")
        assert result is None


# ---------------------------------------------------------------------------
# _resolve_exchange
# ---------------------------------------------------------------------------


class TestResolveExchange:
    @pytest.mark.asyncio
    async def test_uses_env_var_when_set(self):
        redis = _make_redis(provider="bybit")
        with patch.dict("os.environ", {"EXCHANGE": "binance"}):
            result = await _resolve_exchange(redis, "t1", "b1")
        assert result == "binance"
        # Should NOT have called Redis
        redis.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_falls_back_to_redis_when_env_unset(self):
        redis = _make_redis(provider="bybit")
        with patch.dict("os.environ", {}, clear=True):
            # Ensure EXCHANGE is not set
            import os
            os.environ.pop("EXCHANGE", None)
            result = await _resolve_exchange(redis, "t1", "b1")
        assert result == "bybit"
        redis.get.assert_called_once_with(
            "quantgambit:t1:b1:market_data:provider"
        )

    @pytest.mark.asyncio
    async def test_returns_none_when_both_unavailable(self):
        redis = _make_redis(provider=None)
        with patch.dict("os.environ", {}, clear=True):
            import os
            os.environ.pop("EXCHANGE", None)
            result = await _resolve_exchange(redis, "t1", "b1")
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_redis_failure(self):
        redis = _make_redis(fail=True)
        with patch.dict("os.environ", {}, clear=True):
            import os
            os.environ.pop("EXCHANGE", None)
            result = await _resolve_exchange(redis, "t1", "b1")
        assert result is None


# ---------------------------------------------------------------------------
# _query_market_price_handler — single-symbol mode
# ---------------------------------------------------------------------------


class TestQueryMarketPriceHandlerSingleSymbol:
    @pytest.mark.asyncio
    async def test_returns_price_for_symbol(self):
        entry = _make_orderbook_entry(symbol="BTCUSDT")
        redis = _make_redis(entries=[("1-0", entry)], provider="binance")
        with patch.dict("os.environ", {"EXCHANGE": "binance"}):
            result = await _query_market_price_handler(
                redis_client=redis, tenant_id="t1", bot_id="b1",
                symbol="BTCUSDT",
            )
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["symbol"] == "BTCUSDT"
        assert result[0]["exchange"] == "binance"

    @pytest.mark.asyncio
    async def test_case_insensitive_symbol_match(self):
        entry = _make_orderbook_entry(symbol="BTCUSDT")
        redis = _make_redis(entries=[("1-0", entry)], provider="binance")
        with patch.dict("os.environ", {"EXCHANGE": "binance"}):
            result = await _query_market_price_handler(
                redis_client=redis, tenant_id="t1", bot_id="b1",
                symbol="btcusdt",
            )
        assert isinstance(result, list)
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_empty_stream_returns_error(self):
        redis = _make_redis(entries=[], provider="binance")
        with patch.dict("os.environ", {"EXCHANGE": "binance"}):
            result = await _query_market_price_handler(
                redis_client=redis, tenant_id="t1", bot_id="b1",
                symbol="BTCUSDT",
            )
        assert "error" in result
        assert "BTCUSDT" in result["error"]

    @pytest.mark.asyncio
    async def test_symbol_not_found_returns_error(self):
        entry = _make_orderbook_entry(symbol="ETHUSDT")
        redis = _make_redis(entries=[("1-0", entry)], provider="binance")
        with patch.dict("os.environ", {"EXCHANGE": "binance"}):
            result = await _query_market_price_handler(
                redis_client=redis, tenant_id="t1", bot_id="b1",
                symbol="BTCUSDT",
            )
        assert "error" in result
        assert "BTCUSDT" in result["error"]


# ---------------------------------------------------------------------------
# _query_market_price_handler — all-symbols mode
# ---------------------------------------------------------------------------


class TestQueryMarketPriceHandlerAllSymbols:
    @pytest.mark.asyncio
    async def test_returns_all_symbols(self):
        entries = [
            ("2-0", _make_orderbook_entry(symbol="ETHUSDT", bids=[[3000.0, 1.0]], asks=[[3001.0, 1.0]])),
            ("1-0", _make_orderbook_entry(symbol="BTCUSDT")),
        ]
        redis = _make_redis(entries=entries, provider="binance")
        with patch.dict("os.environ", {"EXCHANGE": "binance"}):
            result = await _query_market_price_handler(
                redis_client=redis, tenant_id="t1", bot_id="b1",
            )
        assert isinstance(result, list)
        assert len(result) == 2
        symbols = {r["symbol"] for r in result}
        assert symbols == {"BTCUSDT", "ETHUSDT"}

    @pytest.mark.asyncio
    async def test_deduplicates_by_symbol(self):
        """When multiple entries exist for the same symbol, only the first (latest) is kept."""
        entries = [
            ("2-0", _make_orderbook_entry(symbol="BTCUSDT", bids=[[68000.0, 1.0]], asks=[[68001.0, 1.0]])),
            ("1-0", _make_orderbook_entry(symbol="BTCUSDT", bids=[[67000.0, 1.0]], asks=[[67001.0, 1.0]])),
        ]
        redis = _make_redis(entries=entries, provider="binance")
        with patch.dict("os.environ", {"EXCHANGE": "binance"}):
            result = await _query_market_price_handler(
                redis_client=redis, tenant_id="t1", bot_id="b1",
            )
        assert len(result) == 1
        assert result[0]["best_bid"] == 68000.0  # latest entry

    @pytest.mark.asyncio
    async def test_empty_stream_returns_error(self):
        redis = _make_redis(entries=[], provider="binance")
        with patch.dict("os.environ", {"EXCHANGE": "binance"}):
            result = await _query_market_price_handler(
                redis_client=redis, tenant_id="t1", bot_id="b1",
            )
        assert "error" in result


# ---------------------------------------------------------------------------
# _query_market_price_handler — error paths
# ---------------------------------------------------------------------------


class TestQueryMarketPriceHandlerErrors:
    @pytest.mark.asyncio
    async def test_redis_failure_returns_error(self):
        redis = _make_redis(fail=True)
        with patch.dict("os.environ", {"EXCHANGE": "binance"}):
            result = await _query_market_price_handler(
                redis_client=redis, tenant_id="t1", bot_id="b1",
            )
        assert "error" in result

    @pytest.mark.asyncio
    async def test_no_exchange_returns_error(self):
        redis = _make_redis(provider=None)
        with patch.dict("os.environ", {}, clear=True):
            import os
            os.environ.pop("EXCHANGE", None)
            result = await _query_market_price_handler(
                redis_client=redis, tenant_id="t1", bot_id="b1",
            )
        assert "error" in result
        assert "exchange" in result["error"].lower()


# ---------------------------------------------------------------------------
# Mid price and spread BPS computation
# ---------------------------------------------------------------------------


class TestMidPriceAndSpreadComputation:
    def test_known_values(self):
        """Verify mid_price and spread_bps with the design doc example."""
        entry = _make_orderbook_entry(
            bids=[[67000.5, 1.0], [66999.0, 2.0]],
            asks=[[67001.0, 0.5], [67002.0, 1.5]],
        )
        result = _parse_orderbook_entry(entry, "binance")
        assert result is not None
        assert result["best_bid"] == 67000.5
        assert result["best_ask"] == 67001.0
        expected_mid = (67000.5 + 67001.0) / 2
        assert result["mid_price"] == expected_mid
        expected_spread = (67001.0 - 67000.5) / expected_mid * 10000
        assert result["spread_bps"] == round(expected_spread, 4)

    def test_tight_spread(self):
        """Spread of zero when bid == ask."""
        entry = _make_orderbook_entry(
            bids=[[100.0, 1.0]],
            asks=[[100.0, 1.0]],
        )
        result = _parse_orderbook_entry(entry, "binance")
        assert result is not None
        assert result["mid_price"] == 100.0
        assert result["spread_bps"] == 0.0

    def test_wide_spread(self):
        entry = _make_orderbook_entry(
            bids=[[90.0, 1.0]],
            asks=[[110.0, 1.0]],
        )
        result = _parse_orderbook_entry(entry, "binance")
        assert result is not None
        mid = (90.0 + 110.0) / 2  # 100.0
        spread = (110.0 - 90.0) / mid * 10000  # 2000.0
        assert result["mid_price"] == mid
        assert result["spread_bps"] == round(spread, 4)


# ---------------------------------------------------------------------------
# create_query_market_price_tool
# ---------------------------------------------------------------------------


class TestCreateQueryMarketPriceTool:
    def test_returns_tool_definition(self):
        redis = _make_redis()
        tool = create_query_market_price_tool(redis, "t1", "b1")
        assert isinstance(tool, ToolDefinition)
        assert tool.name == "query_market_price"
        assert tool.parameters_schema == QUERY_MARKET_PRICE_SCHEMA

    def test_description_non_empty(self):
        redis = _make_redis()
        tool = create_query_market_price_tool(redis, "t1", "b1")
        assert len(tool.description) > 0

    @pytest.mark.asyncio
    async def test_handler_delegates(self):
        entry = _make_orderbook_entry(symbol="BTCUSDT")
        redis = _make_redis(entries=[("1-0", entry)], provider="binance")
        with patch.dict("os.environ", {"EXCHANGE": "binance"}):
            tool = create_query_market_price_tool(redis, "t1", "b1")
            result = await tool.handler(symbol="BTCUSDT")
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["symbol"] == "BTCUSDT"

    @pytest.mark.asyncio
    async def test_handler_with_no_args(self):
        entry = _make_orderbook_entry(symbol="BTCUSDT")
        redis = _make_redis(entries=[("1-0", entry)], provider="binance")
        with patch.dict("os.environ", {"EXCHANGE": "binance"}):
            tool = create_query_market_price_tool(redis, "t1", "b1")
            result = await tool.handler()
        assert isinstance(result, list)
