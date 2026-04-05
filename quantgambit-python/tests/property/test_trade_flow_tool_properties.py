"""
Property-based tests for the trade flow copilot tool.

Feature: copilot-deep-knowledge
Tests correctness properties for:
- Property 6: Trade flow tool returns all required fields
- Property 7: Trade flow tool schema validates valid and rejects invalid parameters
- Property 8: Trade flow tool scopes queries to tenant and bot

**Validates: Requirements 5.2, 5.3, 5.6, 8.4**
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import jsonschema
import pytest
from hypothesis import given, settings, strategies as st

from quantgambit.copilot.tools.trade_flow import (
    QUERY_TRADE_FLOW_SCHEMA,
    _query_trade_flow_handler,
)

# =============================================================================
# Hypothesis Strategies
# =============================================================================

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

# Positive floats for volume fields
volume_floats = st.floats(
    min_value=0.0, max_value=10_000_000.0, allow_nan=False, allow_infinity=False,
)

# Positive floats for VWAP (price-like)
vwap_floats = st.one_of(
    st.just(None),
    st.floats(min_value=0.001, max_value=1_000_000.0, allow_nan=False, allow_infinity=False),
)

trade_counts = st.integers(min_value=1, max_value=100_000)

window_secs = st.integers(min_value=1, max_value=3600)


# =============================================================================
# Helpers
# =============================================================================


@st.composite
def trade_flow_row_strategy(draw):
    """Generate a mock asyncpg fetchrow result for trade flow aggregation.

    Returns (row_dict, window_sec) simulating a non-empty aggregation result.
    """
    trade_count = draw(trade_counts)
    buy_volume = draw(volume_floats)
    sell_volume = draw(volume_floats)
    vwap = draw(vwap_floats)
    window_sec = draw(window_secs)

    row = {
        "trade_count": trade_count,
        "buy_volume": buy_volume,
        "sell_volume": sell_volume,
        "vwap": vwap,
    }
    return row, window_sec


def _make_trade_flow_pool(row: dict[str, Any] | None) -> AsyncMock:
    """Build a mock asyncpg pool that returns the given row from fetchrow()."""
    pool = AsyncMock()
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=row)

    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__ = AsyncMock(return_value=False)
    pool.acquire = lambda: ctx
    return pool


# =============================================================================
# Property 6: Trade flow tool returns all required fields
# Feature: copilot-deep-knowledge, Property 6: Trade flow tool returns all required fields
# =============================================================================

_REQUIRED_TRADE_FLOW_FIELDS = {
    "buy_volume",
    "sell_volume",
    "orderflow_imbalance",
    "vwap",
    "trades_per_second",
}


@pytest.mark.asyncio
@given(data=trade_flow_row_strategy(), symbol=symbols)
@settings(max_examples=100)
async def test_property_6_result_contains_all_required_fields(
    data: tuple[dict[str, Any], int],
    symbol: str,
):
    """Non-empty trade flow result contains buy_volume, sell_volume, orderflow_imbalance, vwap, trades_per_second.

    **Validates: Requirements 5.2**
    """
    row, window_sec = data
    pool = _make_trade_flow_pool(row)

    result = await _query_trade_flow_handler(
        pool=pool, tenant_id="t1", bot_id="b1", symbol=symbol, window_sec=window_sec,
    )

    assert isinstance(result, dict), f"Expected dict, got {type(result)}"
    # Should not be an error result since trade_count > 0
    assert "error" not in result, f"Unexpected error: {result}"
    assert _REQUIRED_TRADE_FLOW_FIELDS.issubset(result.keys()), (
        f"Missing fields: {_REQUIRED_TRADE_FLOW_FIELDS - result.keys()}"
    )


# =============================================================================
# Property 7: Trade flow tool schema validates valid and rejects invalid parameters
# Feature: copilot-deep-knowledge, Property 7: Trade flow tool schema validates valid and rejects invalid parameters
# =============================================================================


@st.composite
def valid_trade_flow_params(draw):
    """Generate valid parameter dicts for the trade flow tool schema."""
    params: dict[str, Any] = {"symbol": draw(st.text(min_size=1, max_size=20))}
    if draw(st.booleans()):
        params["window_sec"] = draw(st.integers(min_value=1, max_value=3600))
    return params


@given(params=valid_trade_flow_params())
@settings(max_examples=100)
def test_property_7_schema_accepts_valid_params(params: dict[str, Any]):
    """Schema accepts dicts with string symbol and optional int window_sec (1-3600).

    **Validates: Requirements 5.3, 8.4**
    """
    jsonschema.validate(instance=params, schema=QUERY_TRADE_FLOW_SCHEMA)


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
).filter(lambda k: k not in ("symbol", "window_sec"))


@st.composite
def invalid_trade_flow_params(draw):
    """Generate parameter dicts that should be rejected by the trade flow schema."""
    method = draw(st.sampled_from([
        "missing_symbol",
        "wrong_type_symbol",
        "wrong_type_window_sec",
        "window_sec_below_min",
        "window_sec_above_max",
        "extra_key",
    ]))

    if method == "missing_symbol":
        params: dict[str, Any] = {}
        if draw(st.booleans()):
            params["window_sec"] = draw(st.integers(min_value=1, max_value=3600))
        return params

    elif method == "wrong_type_symbol":
        return {"symbol": draw(_wrong_type_for_symbol)}

    elif method == "wrong_type_window_sec":
        return {
            "symbol": draw(st.text(min_size=1, max_size=10)),
            "window_sec": draw(st.one_of(
                st.text(min_size=1, max_size=10),
                st.booleans(),
                st.floats(allow_nan=False, allow_infinity=False).filter(
                    lambda x: x != int(x) if x == x else True
                ),
            )),
        }

    elif method == "window_sec_below_min":
        return {
            "symbol": draw(st.text(min_size=1, max_size=10)),
            "window_sec": draw(st.integers(max_value=0)),
        }

    elif method == "window_sec_above_max":
        return {
            "symbol": draw(st.text(min_size=1, max_size=10)),
            "window_sec": draw(st.integers(min_value=3601)),
        }

    else:  # extra_key
        params = {"symbol": draw(st.text(min_size=1, max_size=10))}
        extra_key = draw(_extra_key_names)
        params[extra_key] = draw(st.one_of(st.text(min_size=0, max_size=10), st.integers()))
        return params


@given(params=invalid_trade_flow_params())
@settings(max_examples=100)
def test_property_7_schema_rejects_invalid_params(params: dict[str, Any]):
    """Schema rejects dicts missing symbol, with wrong types, out-of-range values, or extra keys.

    **Validates: Requirements 5.3, 8.4**
    """
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=params, schema=QUERY_TRADE_FLOW_SCHEMA)


# =============================================================================
# Property 8: Trade flow tool scopes queries to tenant and bot
# Feature: copilot-deep-knowledge, Property 8: Trade flow tool scopes queries to tenant and bot
# =============================================================================


def _make_recording_pool() -> tuple[AsyncMock, list]:
    """Build a mock pool that records the SQL query and parameters passed to fetchrow()."""
    pool = AsyncMock()
    conn = AsyncMock()
    call_log: list[tuple[str, tuple]] = []

    async def _recording_fetchrow(query: str, *args):
        call_log.append((query, args))
        return None  # Return None to trigger the "no data" path

    conn.fetchrow = AsyncMock(side_effect=_recording_fetchrow)

    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__ = AsyncMock(return_value=False)
    pool.acquire = lambda: ctx
    return pool, call_log


@pytest.mark.asyncio
@given(tid=tenant_ids, bid=bot_ids, symbol=symbols)
@settings(max_examples=100)
async def test_property_8_query_includes_tenant_and_bot(
    tid: str, bid: str, symbol: str,
):
    """The SQL query executed by the handler includes both tenant_id and bot_id as parameters.

    **Validates: Requirements 5.6**
    """
    pool, call_log = _make_recording_pool()

    await _query_trade_flow_handler(
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
