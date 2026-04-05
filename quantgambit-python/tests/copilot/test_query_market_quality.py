"""Unit tests for the query_market_quality copilot tool."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock

import pytest

from quantgambit.copilot.models import ToolDefinition
from quantgambit.copilot.tools.market_quality import (
    QUERY_MARKET_QUALITY_SCHEMA,
    _query_market_quality_handler,
    create_query_market_quality_tool,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DEFAULT_QUALITY: dict[str, Any] = {
    "quality_score": 0.95,
    "tick_age": 1.2,
    "orderbook_age": 0.8,
    "trade_age": 3.5,
    "tick_synced": True,
    "orderbook_synced": True,
    "trade_synced": True,
}

_TENANT = "t1"
_BOT = "b1"


def _quality_key(symbol: str) -> str:
    return f"quantgambit:{_TENANT}:{_BOT}:quality:{symbol}:latest"


def _make_redis(
    *,
    keys_data: dict[str, dict[str, Any]] | None = None,
    fail: bool = False,
) -> AsyncMock:
    """Return a mock Redis client for quality snapshot reads.

    *keys_data* maps full Redis keys to their JSON-decoded values.
    """
    redis = AsyncMock()

    if fail:
        redis.get = AsyncMock(side_effect=ConnectionError("Redis down"))
        redis.scan = AsyncMock(side_effect=ConnectionError("Redis down"))
        return redis

    keys_data = keys_data or {}

    async def _get(key: str) -> bytes | None:
        if key in keys_data:
            return json.dumps(keys_data[key]).encode("utf-8")
        return None

    redis.get = AsyncMock(side_effect=_get)

    # SCAN mock: yields all keys in one pass then returns cursor 0
    async def _scan(cursor: int, *, match: str = "", count: int = 100):
        if cursor == 0:
            return (0, list(keys_data.keys()))
        return (0, [])

    redis.scan = AsyncMock(side_effect=_scan)
    return redis


# ---------------------------------------------------------------------------
# Single-symbol mode
# ---------------------------------------------------------------------------


class TestQueryMarketQualityHandlerSingleSymbol:
    @pytest.mark.asyncio
    async def test_returns_quality_for_symbol(self):
        key = _quality_key("BTCUSDT")
        redis = _make_redis(keys_data={key: _DEFAULT_QUALITY})
        result = await _query_market_quality_handler(
            redis_client=redis, tenant_id=_TENANT, bot_id=_BOT,
            symbol="BTCUSDT",
        )
        assert isinstance(result, list)
        assert len(result) == 1
        entry = result[0]
        assert entry["symbol"] == "BTCUSDT"
        assert entry["quality_score"] == 0.95
        assert entry["tick_age"] == 1.2
        assert entry["orderbook_age"] == 0.8
        assert entry["trade_age"] == 3.5
        assert entry["tick_synced"] is True

    @pytest.mark.asyncio
    async def test_missing_key_returns_error(self):
        redis = _make_redis(keys_data={})
        result = await _query_market_quality_handler(
            redis_client=redis, tenant_id=_TENANT, bot_id=_BOT,
            symbol="BTCUSDT",
        )
        assert isinstance(result, dict)
        assert "error" in result
        assert "BTCUSDT" in result["error"]

    @pytest.mark.asyncio
    async def test_malformed_json_returns_error(self):
        redis = AsyncMock()
        redis.get = AsyncMock(return_value=b"not-valid-json{")
        result = await _query_market_quality_handler(
            redis_client=redis, tenant_id=_TENANT, bot_id=_BOT,
            symbol="BTCUSDT",
        )
        assert isinstance(result, dict)
        assert "error" in result

    @pytest.mark.asyncio
    async def test_bytes_value_decoded(self):
        """Handler decodes bytes from Redis correctly."""
        key = _quality_key("ETHUSDT")
        redis = _make_redis(keys_data={key: {"quality_score": 0.8, "tick_age": 2.0,
                                              "orderbook_age": 1.0, "trade_age": 4.0,
                                              "tick_synced": False}})
        result = await _query_market_quality_handler(
            redis_client=redis, tenant_id=_TENANT, bot_id=_BOT,
            symbol="ETHUSDT",
        )
        assert isinstance(result, list)
        assert result[0]["quality_score"] == 0.8
        assert result[0]["tick_synced"] is False


# ---------------------------------------------------------------------------
# All-symbols mode (SCAN)
# ---------------------------------------------------------------------------


class TestQueryMarketQualityHandlerAllSymbols:
    @pytest.mark.asyncio
    async def test_returns_all_symbols(self):
        keys_data = {
            _quality_key("BTCUSDT"): _DEFAULT_QUALITY,
            _quality_key("ETHUSDT"): {**_DEFAULT_QUALITY, "quality_score": 0.80},
        }
        redis = _make_redis(keys_data=keys_data)
        result = await _query_market_quality_handler(
            redis_client=redis, tenant_id=_TENANT, bot_id=_BOT,
        )
        assert isinstance(result, list)
        assert len(result) == 2
        symbols = {r["symbol"] for r in result}
        assert symbols == {"BTCUSDT", "ETHUSDT"}

    @pytest.mark.asyncio
    async def test_no_keys_returns_error(self):
        redis = _make_redis(keys_data={})
        result = await _query_market_quality_handler(
            redis_client=redis, tenant_id=_TENANT, bot_id=_BOT,
        )
        assert isinstance(result, dict)
        assert "error" in result

    @pytest.mark.asyncio
    async def test_skips_malformed_entries(self):
        """Malformed JSON entries are skipped; valid ones are returned."""
        key_good = _quality_key("BTCUSDT")
        key_bad = _quality_key("BADUSDT")

        redis = AsyncMock()

        async def _get(key: str) -> bytes | None:
            if key == key_good:
                return json.dumps(_DEFAULT_QUALITY).encode("utf-8")
            if key == key_bad:
                return b"not-json{"
            return None

        redis.get = AsyncMock(side_effect=_get)

        async def _scan(cursor: int, *, match: str = "", count: int = 100):
            if cursor == 0:
                return (0, [key_good, key_bad])
            return (0, [])

        redis.scan = AsyncMock(side_effect=_scan)

        result = await _query_market_quality_handler(
            redis_client=redis, tenant_id=_TENANT, bot_id=_BOT,
        )
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["symbol"] == "BTCUSDT"

    @pytest.mark.asyncio
    async def test_extracts_symbol_from_key(self):
        """Symbol is extracted from the Redis key pattern, not from the JSON value."""
        key = _quality_key("SOLUSDT")
        data = {**_DEFAULT_QUALITY}  # no "symbol" field in stored data
        redis = _make_redis(keys_data={key: data})
        result = await _query_market_quality_handler(
            redis_client=redis, tenant_id=_TENANT, bot_id=_BOT,
        )
        assert isinstance(result, list)
        assert result[0]["symbol"] == "SOLUSDT"


# ---------------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------------


class TestQueryMarketQualityHandlerErrors:
    @pytest.mark.asyncio
    async def test_redis_failure_single_symbol(self):
        redis = _make_redis(fail=True)
        result = await _query_market_quality_handler(
            redis_client=redis, tenant_id=_TENANT, bot_id=_BOT,
            symbol="BTCUSDT",
        )
        assert isinstance(result, dict)
        assert "error" in result
        assert "failed" in result["error"].lower() or "Failed" in result["error"]

    @pytest.mark.asyncio
    async def test_redis_failure_all_symbols(self):
        redis = _make_redis(fail=True)
        result = await _query_market_quality_handler(
            redis_client=redis, tenant_id=_TENANT, bot_id=_BOT,
        )
        assert isinstance(result, dict)
        assert "error" in result


# ---------------------------------------------------------------------------
# create_query_market_quality_tool
# ---------------------------------------------------------------------------


class TestCreateQueryMarketQualityTool:
    def test_returns_tool_definition(self):
        redis = _make_redis()
        tool = create_query_market_quality_tool(redis, _TENANT, _BOT)
        assert isinstance(tool, ToolDefinition)
        assert tool.name == "query_market_quality"
        assert tool.parameters_schema == QUERY_MARKET_QUALITY_SCHEMA

    def test_description_non_empty(self):
        redis = _make_redis()
        tool = create_query_market_quality_tool(redis, _TENANT, _BOT)
        assert len(tool.description) > 0

    @pytest.mark.asyncio
    async def test_handler_delegates_single_symbol(self):
        key = _quality_key("BTCUSDT")
        redis = _make_redis(keys_data={key: _DEFAULT_QUALITY})
        tool = create_query_market_quality_tool(redis, _TENANT, _BOT)
        result = await tool.handler(symbol="BTCUSDT")
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["symbol"] == "BTCUSDT"

    @pytest.mark.asyncio
    async def test_handler_delegates_all_symbols(self):
        keys_data = {
            _quality_key("BTCUSDT"): _DEFAULT_QUALITY,
            _quality_key("ETHUSDT"): _DEFAULT_QUALITY,
        }
        redis = _make_redis(keys_data=keys_data)
        tool = create_query_market_quality_tool(redis, _TENANT, _BOT)
        result = await tool.handler()
        assert isinstance(result, list)
        assert len(result) == 2
