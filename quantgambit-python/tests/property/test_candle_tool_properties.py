"""
Property-based tests for the candle copilot tool.

Feature: copilot-deep-knowledge
Tests correctness properties for:
- Property 3: Candle tool returns well-formed OHLCV records
- Property 4: Candle tool schema validates valid and rejects invalid parameters
- Property 5: Candle tool scopes queries to tenant and bot

**Validates: Requirements 4.2, 4.5, 4.6, 8.3**
"""

from __future__ import annotations

import math
from datetime import datetime, timezone, timedelta
from typing import Any
from unittest.mock import AsyncMock

import jsonschema
import pytest
from hypothesis import given, settings, assume, strategies as st

from quantgambit.copilot.tools.candles import (
    QUERY_CANDLES_SCHEMA,
    _query_candles_handler,
)

# =============================================================================
# Hypothesis Strategies
# =============================================================================

# Finite floats for OHLCV numeric fields
ohlcv_floats = st.floats(
    min_value=0.001, max_value=1_000_000.0, allow_nan=False, allow_infinity=False
)

volume_floats = st.floats(
    min_value=0.0, max_value=10_000_000.0, allow_nan=False, allow_infinity=False
)

symbols = st.sampled_from(["BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "XRPUSDT"])

tenant_ids = st.text(
    alphabet=st.sampled_from("abcdefghijklmnopqrstuvwxyz0123456789-_"),
    min_size=1,
    max_size=30,
)

bot_ids = st.text(
    alphabet=st.sampled_from("abcdefghijklmnopqrstuvwxyz0123456789-_"),
    min_size=1,
    max_size=30,
)

_BASE_TS = datetime(2025, 1, 15, 12, 0, 0, tzinfo=timezone.utc)


@st.composite
def ohlcv_rows_strategy(draw):
    """Generate a list of mock asyncpg OHLCV rows.

    Returns (rows, symbol) where rows simulate asyncpg Record dicts.
    """
    symbol = draw(symbols)
    count = draw(st.integers(min_value=1, max_value=20))
    rows = []
    for i in range(count):
        ts = _BASE_TS - timedelta(minutes=i)
        rows.append({
            "ts": ts,
            "open": draw(ohlcv_floats),
            "high": draw(ohlcv_floats),
            "low": draw(ohlcv_floats),
            "close": draw(ohlcv_floats),
            "volume": draw(volume_floats),
        })
    return rows, symbol


def _make_candle_pool(rows: list[dict[str, Any]]) -> AsyncMock:
    """Build a mock asyncpg pool that returns the given rows from fetch()."""
    pool = AsyncMock()
    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=rows)

    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__ = AsyncMock(return_value=False)
    pool.acquire = lambda: ctx
    return pool


# =============================================================================
# Property 3: Candle tool returns well-formed OHLCV records
# Feature: copilot-deep-knowledge, Property 3: Candle tool returns well-formed OHLCV records
# =============================================================================

_REQUIRED_CANDLE_FIELDS = {"ts", "open", "high", "low", "close", "volume"}
_NUMERIC_CANDLE_FIELDS = {"open", "high", "low", "close", "volume"}


@pytest.mark.asyncio
@given(data=ohlcv_rows_strategy())
@settings(max_examples=100)
async def test_property_3_every_record_has_all_ohlcv_fields(
    data: tuple[list[dict[str, Any]], str],
):
    """Every record returned by _query_candles_handler contains ts, open, high, low, close, volume.

    **Validates: Requirements 4.5**
    """
    rows, symbol = data
    pool = _make_candle_pool(rows)

    result = await _query_candles_handler(
        pool=pool, tenant_id="t1", bot_id="b1", symbol=symbol,
    )

    assert isinstance(result, list), f"Expected list, got {type(result)}: {result}"
    assert len(result) == len(rows)

    for i, record in enumerate(result):
        assert _REQUIRED_CANDLE_FIELDS.issubset(record.keys()), (
            f"Record {i} missing fields: {_REQUIRED_CANDLE_FIELDS - record.keys()}"
        )


@pytest.mark.asyncio
@given(data=ohlcv_rows_strategy())
@settings(max_examples=100)
async def test_property_3_all_numeric_fields_are_finite_floats(
    data: tuple[list[dict[str, Any]], str],
):
    """All numeric fields (open, high, low, close, volume) are finite floats.

    **Validates: Requirements 4.5**
    """
    rows, symbol = data
    pool = _make_candle_pool(rows)

    result = await _query_candles_handler(
        pool=pool, tenant_id="t1", bot_id="b1", symbol=symbol,
    )

    assert isinstance(result, list)

    for i, record in enumerate(result):
        for field in _NUMERIC_CANDLE_FIELDS:
            val = record[field]
            assert isinstance(val, float), (
                f"Record {i} field '{field}' is {type(val).__name__}, expected float"
            )
            assert math.isfinite(val), (
                f"Record {i} field '{field}' is not finite: {val}"
            )


# =============================================================================
# Property 4: Candle tool schema validates valid and rejects invalid parameters
# Feature: copilot-deep-knowledge, Property 4: Candle tool schema validates valid and rejects invalid parameters
# =============================================================================


@st.composite
def valid_candle_params(draw):
    """Generate valid parameter dicts for the candle tool schema."""
    params: dict[str, Any] = {"symbol": draw(st.text(min_size=1, max_size=20))}
    if draw(st.booleans()):
        params["timeframe_sec"] = draw(st.integers(min_value=1, max_value=10_000))
    if draw(st.booleans()):
        params["limit"] = draw(st.integers(min_value=1, max_value=500))
    return params


@given(params=valid_candle_params())
@settings(max_examples=100)
def test_property_4_schema_accepts_valid_params(params: dict[str, Any]):
    """Schema accepts dicts with string symbol and optional int timeframe_sec/limit.

    **Validates: Requirements 4.2, 8.3**
    """
    # Should not raise
    jsonschema.validate(instance=params, schema=QUERY_CANDLES_SCHEMA)


# Wrong types for symbol
_wrong_type_for_symbol = st.one_of(
    st.integers(),
    st.booleans(),
    st.lists(st.text(min_size=0, max_size=5), min_size=0, max_size=3),
    st.floats(allow_nan=False, allow_infinity=False),
)

# Extra key names that aren't valid schema properties
_extra_key_names = st.text(
    alphabet=st.sampled_from("abcdefghijklmnopqrstuvwxyz_"),
    min_size=1,
    max_size=15,
).filter(lambda k: k not in ("symbol", "timeframe_sec", "limit"))


@st.composite
def invalid_candle_params(draw):
    """Generate parameter dicts that should be rejected by the candle schema."""
    method = draw(st.sampled_from([
        "missing_symbol",
        "wrong_type_symbol",
        "wrong_type_timeframe",
        "wrong_type_limit",
        "timeframe_below_min",
        "limit_below_min",
        "limit_above_max",
        "extra_key",
    ]))

    if method == "missing_symbol":
        # symbol is required
        params: dict[str, Any] = {}
        if draw(st.booleans()):
            params["timeframe_sec"] = draw(st.integers(min_value=1, max_value=100))
        return params

    elif method == "wrong_type_symbol":
        return {"symbol": draw(_wrong_type_for_symbol)}

    elif method == "wrong_type_timeframe":
        return {
            "symbol": draw(st.text(min_size=1, max_size=10)),
            "timeframe_sec": draw(st.one_of(
                st.text(min_size=1, max_size=10),
                st.booleans(),
                st.floats(allow_nan=False, allow_infinity=False).filter(
                    lambda x: x != int(x) if x == x else True
                ),
            )),
        }

    elif method == "wrong_type_limit":
        return {
            "symbol": draw(st.text(min_size=1, max_size=10)),
            "limit": draw(st.one_of(
                st.text(min_size=1, max_size=10),
                st.booleans(),
                st.floats(allow_nan=False, allow_infinity=False).filter(
                    lambda x: x != int(x) if x == x else True
                ),
            )),
        }

    elif method == "timeframe_below_min":
        return {
            "symbol": draw(st.text(min_size=1, max_size=10)),
            "timeframe_sec": draw(st.integers(max_value=0)),
        }

    elif method == "limit_below_min":
        return {
            "symbol": draw(st.text(min_size=1, max_size=10)),
            "limit": draw(st.integers(max_value=0)),
        }

    elif method == "limit_above_max":
        return {
            "symbol": draw(st.text(min_size=1, max_size=10)),
            "limit": draw(st.integers(min_value=501)),
        }

    else:  # extra_key
        params = {"symbol": draw(st.text(min_size=1, max_size=10))}
        extra_key = draw(_extra_key_names)
        params[extra_key] = draw(st.one_of(st.text(min_size=0, max_size=10), st.integers()))
        return params


@given(params=invalid_candle_params())
@settings(max_examples=100)
def test_property_4_schema_rejects_invalid_params(params: dict[str, Any]):
    """Schema rejects dicts missing symbol, with wrong types, out-of-range values, or extra keys.

    **Validates: Requirements 4.2, 8.3**
    """
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=params, schema=QUERY_CANDLES_SCHEMA)


# =============================================================================
# Property 5: Candle tool scopes queries to tenant and bot
# Feature: copilot-deep-knowledge, Property 5: Candle tool scopes queries to tenant and bot
# =============================================================================


def _make_recording_pool() -> tuple[AsyncMock, list]:
    """Build a mock pool that records the SQL query and parameters passed to fetch()."""
    pool = AsyncMock()
    conn = AsyncMock()
    call_log: list[tuple[str, tuple]] = []

    async def _recording_fetch(query: str, *args):
        call_log.append((query, args))
        return []  # Return empty to trigger the "no data" path

    conn.fetch = AsyncMock(side_effect=_recording_fetch)

    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__ = AsyncMock(return_value=False)
    pool.acquire = lambda: ctx
    return pool, call_log


@pytest.mark.asyncio
@given(tid=tenant_ids, bid=bot_ids, symbol=symbols)
@settings(max_examples=100)
async def test_property_5_query_includes_tenant_and_bot(
    tid: str, bid: str, symbol: str,
):
    """The SQL query executed by the handler includes both tenant_id and bot_id as parameters.

    **Validates: Requirements 4.6**
    """
    pool, call_log = _make_recording_pool()

    await _query_candles_handler(
        pool=pool, tenant_id=tid, bot_id=bid, symbol=symbol,
    )

    assert len(call_log) == 1, f"Expected 1 query, got {len(call_log)}"
    query, params = call_log[0]

    # tenant_id and bot_id must appear in the query parameters
    assert tid in params, (
        f"tenant_id '{tid}' not found in query params: {params}"
    )
    assert bid in params, (
        f"bot_id '{bid}' not found in query params: {params}"
    )

    # The SQL text should reference tenant_id and bot_id placeholders
    assert "tenant_id" in query, "SQL query does not reference tenant_id"
    assert "bot_id" in query, "SQL query does not reference bot_id"
