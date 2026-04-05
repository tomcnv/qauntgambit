"""
Property-based tests for chart event emission and serialization.

Feature: copilot-deep-knowledge
Tests correctness properties for:
- Property 9: Engine emits chart event for non-empty candle results
- Property 10: ChartDataEvent serializes with required fields

**Validates: Requirements 6.1, 6.2**
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from hypothesis import given, settings, strategies as st

from quantgambit.copilot.conversation import ConversationManager
from quantgambit.copilot.engine import AgentEngine
from quantgambit.copilot.models import (
    ChartDataEvent,
    DoneEvent,
    LLMChunk,
    TextDelta,
    ToolCallResult,
    ToolCallStart,
    ToolDefinition,
)
from quantgambit.copilot.prompt import SystemPromptBuilder
from quantgambit.copilot.providers.base import ModelProvider
from quantgambit.copilot.tools.registry import ToolRegistry

# =============================================================================
# Hypothesis Strategies
# =============================================================================

symbols = st.text(
    alphabet=st.sampled_from("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"),
    min_size=1,
    max_size=20,
)

timeframe_secs = st.integers(min_value=1, max_value=86400)

ohlcv_floats = st.floats(
    min_value=0.001, max_value=1_000_000.0, allow_nan=False, allow_infinity=False
)

volume_floats = st.floats(
    min_value=0.0, max_value=10_000_000.0, allow_nan=False, allow_infinity=False
)


@st.composite
def candle_dict(draw):
    """Generate a single OHLCV candle dict."""
    return {
        "ts": draw(st.text(min_size=10, max_size=30)),
        "open": draw(ohlcv_floats),
        "high": draw(ohlcv_floats),
        "low": draw(ohlcv_floats),
        "close": draw(ohlcv_floats),
        "volume": draw(volume_floats),
    }


non_empty_candle_lists = st.lists(candle_dict(), min_size=1, max_size=20)


@st.composite
def chart_data_event_strategy(draw):
    """Generate a random ChartDataEvent instance."""
    return ChartDataEvent(
        symbol=draw(symbols),
        timeframe_sec=draw(timeframe_secs),
        candles=draw(st.lists(candle_dict(), min_size=0, max_size=10)),
    )


# =============================================================================
# Engine test helpers
# =============================================================================


async def _aiter(items):
    """Turn a list into an async iterator."""
    for item in items:
        yield item


def _make_text_chunks(text: str) -> list[LLMChunk]:
    """Create LLMChunks that stream a text response."""
    chunks = [LLMChunk(type="text_delta", content=word + " ") for word in text.split()]
    chunks.append(LLMChunk(type="done"))
    return chunks


def _make_tool_call_chunks(
    tool_name: str, arguments: dict, tool_call_id: str = "tc_1"
) -> list[LLMChunk]:
    """Create LLMChunks that represent a single tool call."""
    args_str = json.dumps(arguments)
    return [
        LLMChunk(
            type="tool_call_start",
            tool_call_id=tool_call_id,
            tool_name=tool_name,
        ),
        LLMChunk(
            type="tool_call_delta",
            tool_call_id=tool_call_id,
            tool_arguments=args_str,
        ),
        LLMChunk(type="tool_call_end", tool_call_id=tool_call_id),
        LLMChunk(type="done"),
    ]


class _MockModelProvider(ModelProvider):
    """Model provider that returns pre-configured chunk sequences."""

    def __init__(self, responses: list[list[LLMChunk]]) -> None:
        self._responses = list(responses)
        self._call_count = 0

    async def chat_completion_stream(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        temperature: float = 0.1,
    ) -> AsyncIterator[LLMChunk]:
        idx = min(self._call_count, len(self._responses) - 1)
        self._call_count += 1
        async for chunk in _aiter(self._responses[idx]):
            yield chunk


def _build_engine(
    model_provider: ModelProvider,
    tool_registry: ToolRegistry,
) -> AgentEngine:
    """Build an AgentEngine with mock conversation manager and prompt builder."""
    conversation_manager = MagicMock(spec=ConversationManager)
    conversation_manager.append_message = AsyncMock()
    conversation_manager.truncate_to_fit = AsyncMock(return_value=[])

    prompt_builder = SystemPromptBuilder(tool_registry)

    return AgentEngine(
        model_provider=model_provider,
        tool_registry=tool_registry,
        conversation_manager=conversation_manager,
        system_prompt_builder=prompt_builder,
    )


async def _collect_events(engine: AgentEngine, **kwargs) -> list:
    """Run the engine and collect all yielded events."""
    events = []
    async for event in engine.run(**kwargs):
        events.append(event)
    return events


# =============================================================================
# Property 9: Engine emits chart event for non-empty candle results
# Feature: copilot-deep-knowledge, Property 9: Engine emits chart event for non-empty candle results
# =============================================================================


@pytest.mark.asyncio
@given(symbol=symbols, timeframe_sec=timeframe_secs, candles=non_empty_candle_lists)
@settings(max_examples=100)
async def test_property_9_engine_emits_chart_event_for_non_empty_candles(
    symbol: str,
    timeframe_sec: int,
    candles: list[dict],
):
    """When query_candles returns a non-empty list, the engine yields a ChartDataEvent
    with the same symbol and candle data.

    **Validates: Requirements 6.1**
    """
    registry = ToolRegistry()

    # Create a query_candles handler that returns the generated candles
    async def candles_handler(**kwargs):
        return candles

    registry.register(
        ToolDefinition(
            name="query_candles",
            description="Query OHLCV candle data",
            parameters_schema={
                "type": "object",
                "properties": {
                    "symbol": {"type": "string"},
                    "timeframe_sec": {"type": "integer"},
                },
                "required": ["symbol"],
            },
            handler=candles_handler,
        )
    )

    tool_args = {"symbol": symbol, "timeframe_sec": timeframe_sec}

    # First LLM call: tool call. Second: text response.
    provider = _MockModelProvider([
        _make_tool_call_chunks("query_candles", tool_args),
        _make_text_chunks("Here is the chart"),
    ])
    engine = _build_engine(provider, registry)

    events = await _collect_events(
        engine,
        user_message="Show me candles",
        conversation_id="conv-prop9",
    )

    chart_events = [e for e in events if isinstance(e, ChartDataEvent)]
    assert len(chart_events) == 1, (
        f"Expected exactly 1 ChartDataEvent, got {len(chart_events)}"
    )

    ce = chart_events[0]
    assert ce.type == "chart_data"
    assert ce.symbol == symbol
    assert ce.timeframe_sec == timeframe_sec
    assert ce.candles == candles


# =============================================================================
# Property 10: ChartDataEvent serializes with required fields
# Feature: copilot-deep-knowledge, Property 10: ChartDataEvent serializes with required fields
# =============================================================================


@given(event=chart_data_event_strategy())
@settings(max_examples=100)
def test_property_10_chart_data_event_serializes_with_required_fields(
    event: ChartDataEvent,
):
    """Serializing a ChartDataEvent via dataclasses.asdict produces a dict with
    type="chart_data", string symbol, int timeframe_sec, and list candles.

    **Validates: Requirements 6.2**
    """
    d = dataclasses.asdict(event)

    assert d["type"] == "chart_data", f"Expected type='chart_data', got {d['type']!r}"
    assert isinstance(d["symbol"], str), f"symbol should be str, got {type(d['symbol'])}"
    assert isinstance(d["timeframe_sec"], int), (
        f"timeframe_sec should be int, got {type(d['timeframe_sec'])}"
    )
    assert isinstance(d["candles"], list), (
        f"candles should be list, got {type(d['candles'])}"
    )

    # Verify the dict is JSON-serializable (required for SSE protocol)
    json_str = json.dumps(d)
    assert isinstance(json_str, str)

    # Round-trip: parse back and verify fields preserved
    parsed = json.loads(json_str)
    assert parsed["type"] == "chart_data"
    assert parsed["symbol"] == event.symbol
    assert parsed["timeframe_sec"] == event.timeframe_sec
    assert len(parsed["candles"]) == len(event.candles)
