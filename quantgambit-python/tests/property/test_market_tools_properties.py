"""
Property-based tests for market price copilot tool.

Feature: copilot-tools-and-compact-ui
Tests correctness properties for:
- Property 1: Mid price and spread BPS computation correctness

**Validates: Requirements 1.1, 1.6**
"""

from __future__ import annotations

import json
import os
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from hypothesis import given, settings, assume, strategies as st

from quantgambit.copilot.tools.market_price import (
    _parse_orderbook_entry,
    _query_market_price_handler,
)

# =============================================================================
# Hypothesis Strategies (Generators)
# =============================================================================

# Positive prices for bids and asks — avoid extremely small values that cause
# floating-point issues and extremely large values that overflow.
positive_prices = st.floats(
    min_value=0.01, max_value=1_000_000.0, allow_nan=False, allow_infinity=False
)

# Positive sizes for orderbook entries
positive_sizes = st.floats(
    min_value=0.001, max_value=100_000.0, allow_nan=False, allow_infinity=False
)

symbols = st.sampled_from(["BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "XRPUSDT"])

exchanges = st.sampled_from(["binance", "bybit", "okx", "deribit"])


@st.composite
def orderbook_strategy(draw):
    """Generate a valid orderbook with positive bid/ask prices.

    Returns (symbol, best_bid, best_ask, bids_array, asks_array, exchange).
    """
    symbol = draw(symbols)
    exchange = draw(exchanges)

    best_bid = draw(positive_prices)
    best_ask = draw(positive_prices)

    # Ensure both are strictly positive (already guaranteed by min_value=0.01)
    assume(best_bid > 0)
    assume(best_ask > 0)

    # Build bids array (best bid first, then lower prices)
    extra_bid_count = draw(st.integers(min_value=0, max_value=3))
    bids = [[best_bid, draw(positive_sizes)]]
    for _ in range(extra_bid_count):
        lower_price = draw(st.floats(min_value=0.01, max_value=best_bid, allow_nan=False, allow_infinity=False))
        bids.append([lower_price, draw(positive_sizes)])

    # Build asks array (best ask first, then higher prices)
    extra_ask_count = draw(st.integers(min_value=0, max_value=3))
    asks = [[best_ask, draw(positive_sizes)]]
    for _ in range(extra_ask_count):
        higher_price = draw(st.floats(min_value=best_ask, max_value=1_000_000.0, allow_nan=False, allow_infinity=False))
        asks.append([higher_price, draw(positive_sizes)])

    return symbol, best_bid, best_ask, bids, asks, exchange


# =============================================================================
# Property 1: Mid price and spread BPS computation correctness
# Feature: copilot-tools-and-compact-ui, Property 1: Mid price and spread BPS computation correctness
# =============================================================================


@given(data=orderbook_strategy())
@settings(max_examples=100)
def test_property_1_mid_price_computation_via_parse(
    data: tuple[str, float, float, list, list, str],
):
    """_parse_orderbook_entry computes mid_price == (best_bid + best_ask) / 2.

    **Validates: Requirements 1.1, 1.6**
    """
    symbol, best_bid, best_ask, bids, asks, exchange = data

    entry_fields = {
        "symbol": symbol,
        "bids": json.dumps(bids),
        "asks": json.dumps(asks),
    }

    result = _parse_orderbook_entry(entry_fields, exchange)
    assert result is not None, "Expected a valid parse result"

    expected_mid = (best_bid + best_ask) / 2
    assert result["mid_price"] == pytest.approx(expected_mid), (
        f"mid_price mismatch: got {result['mid_price']}, expected {expected_mid}"
    )


@given(data=orderbook_strategy())
@settings(max_examples=100)
def test_property_1_spread_bps_computation_via_parse(
    data: tuple[str, float, float, list, list, str],
):
    """_parse_orderbook_entry computes spread_bps == (best_ask - best_bid) / mid_price * 10000.

    **Validates: Requirements 1.1, 1.6**
    """
    symbol, best_bid, best_ask, bids, asks, exchange = data

    entry_fields = {
        "symbol": symbol,
        "bids": json.dumps(bids),
        "asks": json.dumps(asks),
    }

    result = _parse_orderbook_entry(entry_fields, exchange)
    assert result is not None, "Expected a valid parse result"

    mid_price = (best_bid + best_ask) / 2
    expected_spread_bps = round((best_ask - best_bid) / mid_price * 10000, 4)
    assert result["spread_bps"] == pytest.approx(expected_spread_bps), (
        f"spread_bps mismatch: got {result['spread_bps']}, expected {expected_spread_bps}"
    )


@given(data=orderbook_strategy())
@settings(max_examples=100)
def test_property_1_result_contains_all_required_fields(
    data: tuple[str, float, float, list, list, str],
):
    """_parse_orderbook_entry result includes all required fields.

    **Validates: Requirements 1.1, 1.6**
    """
    symbol, best_bid, best_ask, bids, asks, exchange = data

    entry_fields = {
        "symbol": symbol,
        "bids": json.dumps(bids),
        "asks": json.dumps(asks),
    }

    result = _parse_orderbook_entry(entry_fields, exchange)
    assert result is not None, "Expected a valid parse result"

    required_fields = {"symbol", "best_bid", "best_ask", "mid_price", "spread_bps", "exchange"}
    assert required_fields.issubset(result.keys()), (
        f"Missing fields: {required_fields - result.keys()}"
    )
    assert result["symbol"] == symbol
    assert result["exchange"] == exchange
    assert result["best_bid"] == pytest.approx(best_bid)
    assert result["best_ask"] == pytest.approx(best_ask)


@pytest.mark.asyncio
@given(data=orderbook_strategy())
@settings(max_examples=100)
async def test_property_1_handler_mid_price_and_spread_bps(
    data: tuple[str, float, float, list, list, str],
):
    """Full handler returns correct mid_price and spread_bps via mocked Redis.

    **Validates: Requirements 1.1, 1.6**
    """
    symbol, best_bid, best_ask, bids, asks, exchange = data

    entry_fields = {
        "symbol": symbol,
        "bids": json.dumps(bids),
        "asks": json.dumps(asks),
    }

    redis = AsyncMock()
    redis.xrevrange = AsyncMock(return_value=[("entry-id", entry_fields)])
    redis.get = AsyncMock(return_value=None)

    with patch.dict("os.environ", {"EXCHANGE": exchange}):
        result = await _query_market_price_handler(
            redis_client=redis,
            tenant_id="t1",
            bot_id="b1",
            symbol=symbol,
        )

    assert isinstance(result, list), f"Expected list, got {type(result)}: {result}"
    assert len(result) == 1

    record = result[0]
    expected_mid = (best_bid + best_ask) / 2
    expected_spread_bps = round((best_ask - best_bid) / expected_mid * 10000, 4)

    assert record["mid_price"] == pytest.approx(expected_mid)
    assert record["spread_bps"] == pytest.approx(expected_spread_bps)
    assert record["best_bid"] == pytest.approx(best_bid)
    assert record["best_ask"] == pytest.approx(best_ask)
    assert record["exchange"] == exchange
    assert record["symbol"] == symbol


# =============================================================================
# Property 3: Exchange resolution precedence
# Feature: copilot-tools-and-compact-ui, Property 3: Exchange resolution precedence
# =============================================================================

# Strategy: non-empty alphanumeric exchange names (realistic exchange identifiers)
exchange_names = st.text(
    alphabet=st.sampled_from("abcdefghijklmnopqrstuvwxyz0123456789_-"),
    min_size=1,
    max_size=30,
)

from quantgambit.copilot.tools.market_price import _resolve_exchange


@pytest.mark.asyncio
@given(env_exchange=exchange_names, redis_exchange=exchange_names)
@settings(max_examples=100)
async def test_property_3_env_var_takes_precedence_over_redis(
    env_exchange: str,
    redis_exchange: str,
):
    """When EXCHANGE env var is set, _resolve_exchange returns it regardless of Redis value.

    **Validates: Requirements 1.5**
    """
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=redis_exchange)

    with patch.dict("os.environ", {"EXCHANGE": env_exchange}, clear=False):
        result = await _resolve_exchange(redis, tenant_id="t1", bot_id="b1")

    assert result == env_exchange, (
        f"Expected env var '{env_exchange}' to take precedence, got '{result}'"
    )


@pytest.mark.asyncio
@given(redis_exchange=exchange_names)
@settings(max_examples=100)
async def test_property_3_falls_back_to_redis_when_env_unset(
    redis_exchange: str,
):
    """When EXCHANGE env var is unset, _resolve_exchange returns the Redis value.

    **Validates: Requirements 1.5**
    """
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=redis_exchange)

    env = os.environ.copy()
    env.pop("EXCHANGE", None)

    with patch.dict("os.environ", env, clear=True):
        result = await _resolve_exchange(redis, tenant_id="t1", bot_id="b1")

    assert result == redis_exchange, (
        f"Expected Redis fallback '{redis_exchange}', got '{result}'"
    )
    redis.get.assert_called_once_with("quantgambit:t1:b1:market_data:provider")


@pytest.mark.asyncio
@given(env_exchange=exchange_names)
@settings(max_examples=100)
async def test_property_3_env_var_prevents_redis_call(
    env_exchange: str,
):
    """When EXCHANGE env var is set, Redis is never queried for the exchange.

    **Validates: Requirements 1.5**
    """
    redis = AsyncMock()
    redis.get = AsyncMock(return_value="should_not_matter")

    with patch.dict("os.environ", {"EXCHANGE": env_exchange}, clear=False):
        result = await _resolve_exchange(redis, tenant_id="t1", bot_id="b1")

    assert result == env_exchange
    redis.get.assert_not_called()


# =============================================================================
# Property 4: Quality snapshot field completeness
# Feature: copilot-tools-and-compact-ui, Property 4: Quality snapshot field completeness
# =============================================================================

from quantgambit.copilot.tools.market_quality import _query_market_quality_handler

# Strategy: generate quality snapshot dicts with all required fields plus
# at least one sync state boolean.

_SYNC_STATE_FIELDS = ["tick_synced", "orderbook_synced", "trade_synced"]

quality_scores = st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False)
age_values = st.floats(min_value=0.0, max_value=10_000.0, allow_nan=False, allow_infinity=False)
quality_symbols = st.sampled_from(["BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "XRPUSDT"])


@st.composite
def quality_snapshot_strategy(draw):
    """Generate a valid quality snapshot dict with required fields.

    Always includes quality_score, tick_age, orderbook_age, trade_age,
    and at least one sync state boolean field.
    Returns (symbol, snapshot_dict).
    """
    symbol = draw(quality_symbols)
    snapshot: dict[str, Any] = {
        "quality_score": draw(quality_scores),
        "tick_age": draw(age_values),
        "orderbook_age": draw(age_values),
        "trade_age": draw(age_values),
    }

    # Include a random subset of sync state fields, but always at least one
    included_sync = draw(
        st.lists(
            st.sampled_from(_SYNC_STATE_FIELDS),
            min_size=1,
            max_size=len(_SYNC_STATE_FIELDS),
            unique=True,
        )
    )
    for field in included_sync:
        snapshot[field] = draw(st.booleans())

    return symbol, snapshot


@st.composite
def multi_quality_snapshot_strategy(draw):
    """Generate multiple quality snapshots for distinct symbols (all-symbols mode).

    Returns a list of (symbol, snapshot_dict) tuples with unique symbols.
    """
    available = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "XRPUSDT"]
    count = draw(st.integers(min_value=1, max_value=len(available)))
    chosen = draw(
        st.lists(
            st.sampled_from(available),
            min_size=count,
            max_size=count,
            unique=True,
        )
    )
    pairs = []
    for sym in chosen:
        snapshot: dict[str, Any] = {
            "quality_score": draw(quality_scores),
            "tick_age": draw(age_values),
            "orderbook_age": draw(age_values),
            "trade_age": draw(age_values),
        }
        included_sync = draw(
            st.lists(
                st.sampled_from(_SYNC_STATE_FIELDS),
                min_size=1,
                max_size=len(_SYNC_STATE_FIELDS),
                unique=True,
            )
        )
        for field in included_sync:
            snapshot[field] = draw(st.booleans())
        pairs.append((sym, snapshot))
    return pairs


def _make_quality_redis(
    keys_data: dict[str, dict[str, Any]],
) -> AsyncMock:
    """Build a mock Redis client for quality snapshot reads."""
    redis = AsyncMock()

    async def _get(key: str) -> bytes | None:
        if key in keys_data:
            return json.dumps(keys_data[key]).encode("utf-8")
        return None

    redis.get = AsyncMock(side_effect=_get)

    async def _scan(cursor: int, *, match: str = "", count: int = 100):
        if cursor == 0:
            return (0, list(keys_data.keys()))
        return (0, [])

    redis.scan = AsyncMock(side_effect=_scan)
    return redis


_REQUIRED_QUALITY_FIELDS = {"quality_score", "tick_age", "orderbook_age", "trade_age", "symbol"}


@pytest.mark.asyncio
@given(data=quality_snapshot_strategy())
@settings(max_examples=100)
async def test_property_4_single_symbol_field_completeness(
    data: tuple[str, dict[str, Any]],
):
    """Single-symbol quality query returns all required fields and at least one sync state.

    **Validates: Requirements 2.1, 2.2**
    """
    symbol, snapshot = data

    key = f"quantgambit:t1:b1:quality:{symbol}:latest"
    redis = _make_quality_redis({key: snapshot})

    result = await _query_market_quality_handler(
        redis_client=redis, tenant_id="t1", bot_id="b1", symbol=symbol,
    )

    assert isinstance(result, list), f"Expected list, got {type(result)}: {result}"
    assert len(result) == 1

    entry = result[0]

    # All required fields must be present
    assert _REQUIRED_QUALITY_FIELDS.issubset(entry.keys()), (
        f"Missing required fields: {_REQUIRED_QUALITY_FIELDS - entry.keys()}"
    )

    # Symbol must match the requested symbol
    assert entry["symbol"] == symbol

    # At least one sync state field must be present
    sync_fields_present = [f for f in _SYNC_STATE_FIELDS if f in entry]
    assert len(sync_fields_present) >= 1, (
        f"Expected at least one sync state field, found none in {entry.keys()}"
    )


@pytest.mark.asyncio
@given(data=quality_snapshot_strategy())
@settings(max_examples=100)
async def test_property_4_single_symbol_values_preserved(
    data: tuple[str, dict[str, Any]],
):
    """Single-symbol quality query preserves the original snapshot values.

    **Validates: Requirements 2.1, 2.2**
    """
    symbol, snapshot = data

    key = f"quantgambit:t1:b1:quality:{symbol}:latest"
    redis = _make_quality_redis({key: snapshot})

    result = await _query_market_quality_handler(
        redis_client=redis, tenant_id="t1", bot_id="b1", symbol=symbol,
    )

    entry = result[0]

    assert entry["quality_score"] == pytest.approx(snapshot["quality_score"])
    assert entry["tick_age"] == pytest.approx(snapshot["tick_age"])
    assert entry["orderbook_age"] == pytest.approx(snapshot["orderbook_age"])
    assert entry["trade_age"] == pytest.approx(snapshot["trade_age"])

    for field in _SYNC_STATE_FIELDS:
        if field in snapshot:
            assert entry[field] == snapshot[field]


@pytest.mark.asyncio
@given(data=multi_quality_snapshot_strategy())
@settings(max_examples=100)
async def test_property_4_all_symbols_field_completeness(
    data: list[tuple[str, dict[str, Any]]],
):
    """All-symbols quality query returns complete fields for every symbol.

    **Validates: Requirements 2.1, 2.2**
    """
    keys_data = {}
    for symbol, snapshot in data:
        key = f"quantgambit:t1:b1:quality:{symbol}:latest"
        keys_data[key] = snapshot

    redis = _make_quality_redis(keys_data)

    result = await _query_market_quality_handler(
        redis_client=redis, tenant_id="t1", bot_id="b1",
    )

    assert isinstance(result, list), f"Expected list, got {type(result)}: {result}"
    assert len(result) == len(data)

    result_symbols = {entry["symbol"] for entry in result}
    expected_symbols = {sym for sym, _ in data}
    assert result_symbols == expected_symbols, (
        f"Symbol mismatch: got {result_symbols}, expected {expected_symbols}"
    )

    for entry in result:
        # All required fields present
        assert _REQUIRED_QUALITY_FIELDS.issubset(entry.keys()), (
            f"Missing required fields in {entry['symbol']}: "
            f"{_REQUIRED_QUALITY_FIELDS - entry.keys()}"
        )

        # At least one sync state field present
        sync_fields_present = [f for f in _SYNC_STATE_FIELDS if f in entry]
        assert len(sync_fields_present) >= 1, (
            f"No sync state field in {entry['symbol']}: {entry.keys()}"
        )

        # Symbol matches one of the input symbols
        assert entry["symbol"] in expected_symbols


# =============================================================================
# Property 5: Market context limit and ordering
# Feature: copilot-tools-and-compact-ui, Property 5: Market context limit and ordering
# =============================================================================

from datetime import datetime, timezone, timedelta

from quantgambit.copilot.tools.market_context import _query_market_context_handler

# Strategies for market context rows
context_symbols = st.sampled_from(["BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "XRPUSDT"])
context_limits = st.integers(min_value=1, max_value=100)
context_floats = st.floats(min_value=0.0, max_value=1_000_000.0, allow_nan=False, allow_infinity=False)

# Base timestamp for generating rows
_BASE_TS = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)


@st.composite
def market_context_rows_strategy(draw):
    """Generate a random set of market context rows with distinct timestamps.

    Returns (rows, symbol_filter, limit) where:
    - rows: list of dicts simulating asyncpg Record objects (with datetime ts)
    - symbol_filter: str | None — the symbol to filter by (or None for all)
    - limit: int — the requested limit (1–100)
    """
    limit = draw(context_limits)

    # Decide whether to filter by symbol
    use_symbol_filter = draw(st.booleans())
    filter_symbol = draw(context_symbols) if use_symbol_filter else None

    # Generate between 0 and 150 raw rows (can exceed limit to test capping)
    row_count = draw(st.integers(min_value=0, max_value=150))
    rows = []
    for i in range(row_count):
        sym = draw(context_symbols)
        ts = _BASE_TS - timedelta(seconds=i * 60 + draw(st.integers(min_value=0, max_value=59)))
        rows.append({
            "symbol": sym,
            "ts": ts,
            "spread_bps": draw(context_floats),
            "depth_usd": draw(context_floats),
            "funding_rate": draw(st.floats(min_value=-0.01, max_value=0.01, allow_nan=False, allow_infinity=False)),
            "iv": draw(context_floats),
            "vol": draw(context_floats),
        })

    return rows, filter_symbol, limit


def _simulate_db_query(
    rows: list[dict[str, Any]],
    symbol: str | None,
    limit: int,
) -> list[dict[str, Any]]:
    """Simulate the SQL query: filter by symbol, order by ts DESC, limit."""
    filtered = rows if symbol is None else [r for r in rows if r["symbol"] == symbol]
    sorted_rows = sorted(filtered, key=lambda r: r["ts"], reverse=True)
    return sorted_rows[:limit]


def _make_context_pool(rows: list[dict[str, Any]]) -> AsyncMock:
    """Build a mock asyncpg pool that simulates the market_context SQL query.

    The mock connection's ``fetch(query, symbol, limit)`` applies the same
    filtering, ordering, and limiting that the real DB would.
    """
    pool = AsyncMock()
    conn = AsyncMock()

    async def _fetch(query: str, symbol: str | None, limit: int):
        return _simulate_db_query(rows, symbol, limit)

    conn.fetch = AsyncMock(side_effect=_fetch)

    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__ = AsyncMock(return_value=False)
    pool.acquire = lambda: ctx
    return pool


@pytest.mark.asyncio
@given(data=market_context_rows_strategy())
@settings(max_examples=100)
async def test_property_5_result_length_within_limit(
    data: tuple[list[dict[str, Any]], str | None, int],
):
    """Handler returns at most ``limit`` rows.

    **Validates: Requirements 3.1, 3.2, 3.3**
    """
    rows, symbol_filter, limit = data
    pool = _make_context_pool(rows)

    kwargs: dict[str, Any] = {"pool": pool, "tenant_id": "t1", "bot_id": "b1", "limit": limit}
    if symbol_filter is not None:
        kwargs["symbol"] = symbol_filter

    result = await _query_market_context_handler(**kwargs)

    # Must be a list (not an error dict) when pool doesn't fail
    assert isinstance(result, list), f"Expected list, got {type(result)}: {result}"
    assert len(result) <= limit, (
        f"Result length {len(result)} exceeds limit {limit}"
    )


@pytest.mark.asyncio
@given(data=market_context_rows_strategy())
@settings(max_examples=100)
async def test_property_5_rows_ordered_by_ts_desc(
    data: tuple[list[dict[str, Any]], str | None, int],
):
    """Handler returns rows ordered by timestamp descending.

    **Validates: Requirements 3.1, 3.2, 3.3**
    """
    rows, symbol_filter, limit = data
    pool = _make_context_pool(rows)

    kwargs: dict[str, Any] = {"pool": pool, "tenant_id": "t1", "bot_id": "b1", "limit": limit}
    if symbol_filter is not None:
        kwargs["symbol"] = symbol_filter

    result = await _query_market_context_handler(**kwargs)
    assert isinstance(result, list)

    if len(result) >= 2:
        timestamps = [r["ts"] for r in result]
        for i in range(len(timestamps) - 1):
            assert timestamps[i] >= timestamps[i + 1], (
                f"Rows not in ts DESC order: {timestamps[i]} < {timestamps[i + 1]}"
            )


@pytest.mark.asyncio
@given(data=market_context_rows_strategy())
@settings(max_examples=100)
async def test_property_5_symbol_filter_respected(
    data: tuple[list[dict[str, Any]], str | None, int],
):
    """When a symbol filter is provided, all returned rows have matching symbol.

    **Validates: Requirements 3.1, 3.2, 3.3**
    """
    rows, symbol_filter, limit = data
    assume(symbol_filter is not None)

    pool = _make_context_pool(rows)

    result = await _query_market_context_handler(
        pool=pool, tenant_id="t1", bot_id="b1", symbol=symbol_filter, limit=limit,
    )
    assert isinstance(result, list)

    for entry in result:
        assert entry["symbol"] == symbol_filter, (
            f"Expected symbol '{symbol_filter}', got '{entry['symbol']}'"
        )


@pytest.mark.asyncio
@given(data=market_context_rows_strategy())
@settings(max_examples=100)
async def test_property_5_default_limit_caps_at_10(
    data: tuple[list[dict[str, Any]], str | None, int],
):
    """When no limit is provided, handler defaults to 10 rows.

    **Validates: Requirements 3.1, 3.2, 3.3**
    """
    rows, symbol_filter, _limit = data

    # Use default limit (don't pass limit kwarg)
    pool = _make_context_pool(rows)

    kwargs: dict[str, Any] = {"pool": pool, "tenant_id": "t1", "bot_id": "b1"}
    if symbol_filter is not None:
        kwargs["symbol"] = symbol_filter

    result = await _query_market_context_handler(**kwargs)
    assert isinstance(result, list)
    assert len(result) <= 10, (
        f"Default limit should cap at 10, got {len(result)} rows"
    )


# =============================================================================
# Property 6: Schema validation rejects invalid parameters
# Feature: copilot-tools-and-compact-ui, Property 6: Schema validation rejects invalid parameters
#
# For any parameter dict that violates a tool's JSON Schema (wrong type, extra
# keys), ToolRegistry.execute() SHALL return ToolResult(success=False) with a
# validation error message, without invoking the handler.
#
# **Validates: Requirements 4.3**
# =============================================================================

from unittest.mock import MagicMock

from quantgambit.copilot.models import ToolResult
from quantgambit.copilot.tools.registry import ToolRegistry
from quantgambit.copilot.tools.market_price import create_query_market_price_tool
from quantgambit.copilot.tools.market_quality import create_query_market_quality_tool
from quantgambit.copilot.tools.market_context import create_query_market_context_tool

# The three market tool names and their schemas for reference:
# - query_market_price:   { symbol?: string }, additionalProperties: false
# - query_market_quality: { symbol?: string }, additionalProperties: false
# - query_market_context: { symbol?: string, limit?: integer(1-100) }, additionalProperties: false

_MARKET_TOOL_NAMES = [
    "query_market_price",
    "query_market_quality",
    "query_market_context",
]


def _make_market_registry() -> tuple[ToolRegistry, AsyncMock]:
    """Build a ToolRegistry with all three market tools using mock deps.

    Returns (registry, handler_spy) where handler_spy can be used to verify
    that no handler was actually invoked.
    """
    redis = AsyncMock()
    pool = AsyncMock()

    registry = ToolRegistry()
    registry.register(
        create_query_market_price_tool(redis_client=redis, tenant_id="t1", bot_id="b1")
    )
    registry.register(
        create_query_market_quality_tool(redis_client=redis, tenant_id="t1", bot_id="b1")
    )
    registry.register(
        create_query_market_context_tool(pool=pool, tenant_id="t1", bot_id="b1")
    )
    return registry


# ---------------------------------------------------------------------------
# Hypothesis strategies for generating invalid parameters
# ---------------------------------------------------------------------------

# Wrong types for the "symbol" field (should be string)
_wrong_type_for_symbol = st.one_of(
    st.integers(),
    st.booleans(),
    st.lists(st.text(min_size=0, max_size=5), min_size=0, max_size=3),
    st.floats(allow_nan=False, allow_infinity=False),
)

# Wrong types for the "limit" field (should be integer 1-100)
_wrong_type_for_limit = st.one_of(
    st.text(min_size=1, max_size=10),
    st.booleans(),
    st.lists(st.integers(), min_size=0, max_size=3),
    st.floats(allow_nan=False, allow_infinity=False).filter(lambda x: x != int(x) if x == x else True),
)

# Out-of-range integers for "limit" (below 1 or above 100)
_out_of_range_limit = st.one_of(
    st.integers(max_value=0),
    st.integers(min_value=101),
)

# Extra keys that should be rejected by additionalProperties: false
_extra_key_names = st.text(
    alphabet=st.sampled_from("abcdefghijklmnopqrstuvwxyz_"),
    min_size=1,
    max_size=15,
).filter(lambda k: k not in ("symbol", "limit"))

_extra_key_values = st.one_of(
    st.text(min_size=0, max_size=10),
    st.integers(),
    st.booleans(),
)


@st.composite
def invalid_params_for_price_or_quality(draw):
    """Generate invalid params for query_market_price or query_market_quality.

    These tools accept only an optional `symbol` (string) with no additional
    properties. Invalid params include: wrong type for symbol, extra keys.
    """
    method = draw(st.sampled_from(["wrong_type_symbol", "extra_key"]))

    if method == "wrong_type_symbol":
        return {"symbol": draw(_wrong_type_for_symbol)}
    else:  # extra_key
        params: dict[str, Any] = {}
        # Optionally include a valid symbol
        if draw(st.booleans()):
            params["symbol"] = draw(st.text(min_size=1, max_size=10))
        # Add an extra key
        extra_key = draw(_extra_key_names)
        params[extra_key] = draw(_extra_key_values)
        return params


@st.composite
def invalid_params_for_context(draw):
    """Generate invalid params for query_market_context.

    This tool accepts optional `symbol` (string) and optional `limit`
    (integer 1-100) with no additional properties. Invalid params include:
    wrong type for symbol, wrong type for limit, out-of-range limit, extra keys.
    """
    method = draw(st.sampled_from([
        "wrong_type_symbol",
        "wrong_type_limit",
        "out_of_range_limit",
        "extra_key",
    ]))

    if method == "wrong_type_symbol":
        params: dict[str, Any] = {"symbol": draw(_wrong_type_for_symbol)}
        if draw(st.booleans()):
            params["limit"] = draw(st.integers(min_value=1, max_value=100))
        return params

    elif method == "wrong_type_limit":
        params = {"limit": draw(_wrong_type_for_limit)}
        if draw(st.booleans()):
            params["symbol"] = draw(st.text(min_size=1, max_size=10))
        return params

    elif method == "out_of_range_limit":
        params = {"limit": draw(_out_of_range_limit)}
        if draw(st.booleans()):
            params["symbol"] = draw(st.text(min_size=1, max_size=10))
        return params

    else:  # extra_key
        params = {}
        if draw(st.booleans()):
            params["symbol"] = draw(st.text(min_size=1, max_size=10))
        if draw(st.booleans()):
            params["limit"] = draw(st.integers(min_value=1, max_value=100))
        extra_key = draw(_extra_key_names)
        params[extra_key] = draw(_extra_key_values)
        return params


# ---------------------------------------------------------------------------
# Property 6 tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@given(bad_params=invalid_params_for_price_or_quality())
@settings(max_examples=100)
async def test_property_6_market_price_rejects_invalid_params(
    bad_params: dict[str, Any],
):
    """query_market_price rejects invalid params with success=False, handler not invoked.

    **Validates: Requirements 4.3**
    """
    registry = _make_market_registry()
    tool = registry.get("query_market_price")
    original_handler = tool.handler

    # Wrap handler to detect invocation
    call_count = 0

    async def spy_handler(**kwargs):
        nonlocal call_count
        call_count += 1
        return await original_handler(**kwargs)

    tool.handler = spy_handler

    result = await registry.execute("query_market_price", bad_params)

    assert isinstance(result, ToolResult)
    assert result.success is False, (
        f"Expected success=False for invalid params {bad_params}, got success=True"
    )
    assert result.error is not None
    assert "validation failed" in result.error.lower() or "validat" in result.error.lower()
    assert call_count == 0, (
        f"Handler was invoked {call_count} time(s) for invalid params {bad_params}"
    )


@pytest.mark.asyncio
@given(bad_params=invalid_params_for_price_or_quality())
@settings(max_examples=100)
async def test_property_6_market_quality_rejects_invalid_params(
    bad_params: dict[str, Any],
):
    """query_market_quality rejects invalid params with success=False, handler not invoked.

    **Validates: Requirements 4.3**
    """
    registry = _make_market_registry()
    tool = registry.get("query_market_quality")
    original_handler = tool.handler

    call_count = 0

    async def spy_handler(**kwargs):
        nonlocal call_count
        call_count += 1
        return await original_handler(**kwargs)

    tool.handler = spy_handler

    result = await registry.execute("query_market_quality", bad_params)

    assert isinstance(result, ToolResult)
    assert result.success is False, (
        f"Expected success=False for invalid params {bad_params}, got success=True"
    )
    assert result.error is not None
    assert "validation failed" in result.error.lower() or "validat" in result.error.lower()
    assert call_count == 0, (
        f"Handler was invoked {call_count} time(s) for invalid params {bad_params}"
    )


@pytest.mark.asyncio
@given(bad_params=invalid_params_for_context())
@settings(max_examples=100)
async def test_property_6_market_context_rejects_invalid_params(
    bad_params: dict[str, Any],
):
    """query_market_context rejects invalid params with success=False, handler not invoked.

    **Validates: Requirements 4.3**
    """
    registry = _make_market_registry()
    tool = registry.get("query_market_context")
    original_handler = tool.handler

    call_count = 0

    async def spy_handler(**kwargs):
        nonlocal call_count
        call_count += 1
        return await original_handler(**kwargs)

    tool.handler = spy_handler

    result = await registry.execute("query_market_context", bad_params)

    assert isinstance(result, ToolResult)
    assert result.success is False, (
        f"Expected success=False for invalid params {bad_params}, got success=True"
    )
    assert result.error is not None
    assert "validation failed" in result.error.lower() or "validat" in result.error.lower()
    assert call_count == 0, (
        f"Handler was invoked {call_count} time(s) for invalid params {bad_params}"
    )
