"""Unit tests for AgentEngine."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, MagicMock

import pytest

from quantgambit.copilot.conversation import ConversationManager
from quantgambit.copilot.engine import AgentEngine, MAX_TOOL_CALLS_PER_TURN
from quantgambit.copilot.models import (
    DoneEvent,
    ErrorEvent,
    LLMChunk,
    Message,
    SettingsMutationProposal,
    TextDelta,
    ToolCallResult,
    ToolCallStart,
    ToolDefinition,
    ToolResult,
    TradeContext,
)
from quantgambit.copilot.prompt import SystemPromptBuilder
from quantgambit.copilot.providers.base import ModelProvider
from quantgambit.copilot.tools.registry import ToolRegistry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _aiter(items):
    """Turn a list into an async iterator."""
    for item in items:
        yield item


def _make_text_chunks(text: str) -> list[LLMChunk]:
    """Create LLMChunks that stream a text response word by word."""
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
    """Model provider that returns pre-configured chunk sequences.

    Each call to chat_completion_stream pops the next sequence from the list.
    """

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


class _ErrorModelProvider(ModelProvider):
    """Model provider that always raises during streaming."""

    async def chat_completion_stream(self, messages, tools=None, temperature=0.1):
        raise ConnectionError("LLM unreachable")
        # Make it an async generator
        yield  # pragma: no cover


def _build_engine(
    model_provider: ModelProvider,
    tool_registry: ToolRegistry | None = None,
) -> AgentEngine:
    """Build an AgentEngine with mock conversation manager and prompt builder."""
    if tool_registry is None:
        tool_registry = ToolRegistry()

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


# ---------------------------------------------------------------------------
# Tests: basic text response
# ---------------------------------------------------------------------------


class TestTextResponse:
    @pytest.mark.asyncio
    async def test_yields_text_deltas_and_done(self):
        provider = _MockModelProvider([_make_text_chunks("Hello world")])
        engine = _build_engine(provider)

        events = await _collect_events(
            engine,
            user_message="Hi",
            conversation_id="conv-1",
        )

        text_events = [e for e in events if isinstance(e, TextDelta)]
        assert len(text_events) >= 1
        full_text = "".join(e.content for e in text_events)
        assert "Hello" in full_text
        assert "world" in full_text

        # Last event should be DoneEvent
        assert isinstance(events[-1], DoneEvent)

    @pytest.mark.asyncio
    async def test_persists_user_and_assistant_messages(self):
        provider = _MockModelProvider([_make_text_chunks("Response")])
        engine = _build_engine(provider)

        await _collect_events(
            engine,
            user_message="Question",
            conversation_id="conv-1",
        )

        cm = engine._conversation
        # User message appended first, then assistant message
        assert cm.append_message.call_count == 2
        user_call = cm.append_message.call_args_list[0]
        assert user_call[0][1].role == "user"
        assert user_call[0][1].content == "Question"

        assistant_call = cm.append_message.call_args_list[1]
        assert assistant_call[0][1].role == "assistant"


# ---------------------------------------------------------------------------
# Tests: tool call loop
# ---------------------------------------------------------------------------


class TestToolCallLoop:
    @pytest.mark.asyncio
    async def test_executes_tool_and_yields_events(self):
        registry = ToolRegistry()

        async def echo_handler(**kwargs):
            return {"echo": kwargs}

        registry.register(
            ToolDefinition(
                name="test_tool",
                description="A test tool",
                parameters_schema={
                    "type": "object",
                    "properties": {"q": {"type": "string"}},
                },
                handler=echo_handler,
            )
        )

        # First call: tool call. Second call: text response.
        provider = _MockModelProvider(
            [
                _make_tool_call_chunks("test_tool", {"q": "hello"}),
                _make_text_chunks("Done with tool"),
            ]
        )
        engine = _build_engine(provider, registry)

        events = await _collect_events(
            engine,
            user_message="Use the tool",
            conversation_id="conv-1",
        )

        tool_starts = [e for e in events if isinstance(e, ToolCallStart)]
        tool_results = [e for e in events if isinstance(e, ToolCallResult)]
        assert len(tool_starts) == 1
        assert tool_starts[0].tool_name == "test_tool"
        assert len(tool_results) == 1
        assert tool_results[0].success is True

    @pytest.mark.asyncio
    async def test_tool_failure_yields_result_with_success_false(self):
        registry = ToolRegistry()

        async def failing_handler(**kwargs):
            raise RuntimeError("tool broke")

        registry.register(
            ToolDefinition(
                name="bad_tool",
                description="Fails",
                parameters_schema={"type": "object", "properties": {}},
                handler=failing_handler,
            )
        )

        provider = _MockModelProvider(
            [
                _make_tool_call_chunks("bad_tool", {}),
                _make_text_chunks("Tool failed, sorry"),
            ]
        )
        engine = _build_engine(provider, registry)

        events = await _collect_events(
            engine,
            user_message="Try the bad tool",
            conversation_id="conv-1",
        )

        tool_results = [e for e in events if isinstance(e, ToolCallResult)]
        assert len(tool_results) == 1
        assert tool_results[0].success is False


# ---------------------------------------------------------------------------
# Tests: max tool call limit
# ---------------------------------------------------------------------------


class TestMaxToolCallLimit:
    @pytest.mark.asyncio
    async def test_enforces_max_tool_calls(self):
        registry = ToolRegistry()

        async def counter_handler(**kwargs):
            return {"count": 1}

        registry.register(
            ToolDefinition(
                name="counter",
                description="Counts",
                parameters_schema={"type": "object", "properties": {}},
                handler=counter_handler,
            )
        )

        # Create MAX_TOOL_CALLS_PER_TURN + 1 tool call responses, then a text response
        responses = []
        for i in range(MAX_TOOL_CALLS_PER_TURN + 1):
            responses.append(
                _make_tool_call_chunks("counter", {}, tool_call_id=f"tc_{i}")
            )
        responses.append(_make_text_chunks("Forced text after limit"))

        provider = _MockModelProvider(responses)
        engine = _build_engine(provider, registry)

        events = await _collect_events(
            engine,
            user_message="Call tools many times",
            conversation_id="conv-1",
        )

        tool_results = [e for e in events if isinstance(e, ToolCallResult)]
        # Should not exceed MAX_TOOL_CALLS_PER_TURN
        assert len(tool_results) <= MAX_TOOL_CALLS_PER_TURN


# ---------------------------------------------------------------------------
# Tests: error handling
# ---------------------------------------------------------------------------


class TestErrorHandling:
    @pytest.mark.asyncio
    async def test_llm_unreachable_yields_error_event(self):
        provider = _ErrorModelProvider()
        engine = _build_engine(provider)

        events = await _collect_events(
            engine,
            user_message="Hello",
            conversation_id="conv-1",
        )

        error_events = [e for e in events if isinstance(e, ErrorEvent)]
        assert len(error_events) >= 1
        assert "unavailable" in error_events[0].message.lower()

        # Should still end with DoneEvent
        assert isinstance(events[-1], DoneEvent)


# ---------------------------------------------------------------------------
# Tests: trade context
# ---------------------------------------------------------------------------


class TestTradeContext:
    @pytest.mark.asyncio
    async def test_trade_context_without_trace_id(self):
        """Trade context without decision_trace_id should not pre-fetch."""
        provider = _MockModelProvider([_make_text_chunks("Trade info")])
        engine = _build_engine(provider)

        ctx = TradeContext(
            trade_id="t-1",
            symbol="BTCUSDT",
            side="buy",
            entry_price=50000.0,
            exit_price=51000.0,
            pnl=100.0,
            hold_time_seconds=3600.0,
        )

        events = await _collect_events(
            engine,
            user_message="Tell me about this trade",
            conversation_id="conv-1",
            trade_context=ctx,
        )

        # No tool call events for pre-fetch
        tool_starts = [e for e in events if isinstance(e, ToolCallStart)]
        assert len(tool_starts) == 0

    @pytest.mark.asyncio
    async def test_trade_context_with_trace_id_prefetches(self):
        """Trade context with decision_trace_id should pre-fetch the trace."""
        registry = ToolRegistry()

        async def trace_handler(**kwargs):
            return {"trace_id": kwargs.get("trace_id"), "stages": ["Risk", "Signal"]}

        registry.register(
            ToolDefinition(
                name="query_decision_traces",
                description="Query decision traces",
                parameters_schema={
                    "type": "object",
                    "properties": {"trace_id": {"type": "string"}},
                },
                handler=trace_handler,
            )
        )

        provider = _MockModelProvider([_make_text_chunks("Here is the trace")])
        engine = _build_engine(provider, registry)

        ctx = TradeContext(
            trade_id="t-1",
            symbol="BTCUSDT",
            side="buy",
            entry_price=50000.0,
            exit_price=51000.0,
            pnl=100.0,
            hold_time_seconds=3600.0,
            decision_trace_id="dt-123",
        )

        events = await _collect_events(
            engine,
            user_message="Why was this trade taken?",
            conversation_id="conv-1",
            trade_context=ctx,
        )

        # Should have pre-fetch tool call events
        tool_starts = [e for e in events if isinstance(e, ToolCallStart)]
        assert len(tool_starts) == 1
        assert tool_starts[0].tool_name == "query_decision_traces"

        tool_results = [e for e in events if isinstance(e, ToolCallResult)]
        assert len(tool_results) == 1
        assert tool_results[0].success is True


# ---------------------------------------------------------------------------
# Tests: empty response after tool calls (bot-stopping bug)
# ---------------------------------------------------------------------------


class TestEmptyResponseAfterToolCalls:
    """Verify the engine recovers when the LLM returns empty after tool calls.

    This reproduces the scenario where DeepSeek executes tools, then returns
    an empty response instead of synthesising a text reply.
    """

    @pytest.mark.asyncio
    async def test_empty_response_triggers_nudge_and_retry(self):
        """After tool calls, an empty LLM response should retry with a nudge."""
        registry = ToolRegistry()

        async def echo_handler(**kwargs):
            return {"echo": kwargs}

        registry.register(
            ToolDefinition(
                name="test_tool",
                description="A test tool",
                parameters_schema={
                    "type": "object",
                    "properties": {"q": {"type": "string"}},
                },
                handler=echo_handler,
            )
        )

        # Iteration 1: tool call
        # Iteration 2: empty response (no text, no tools) — triggers nudge
        # Iteration 3: text response after nudge
        provider = _MockModelProvider(
            [
                _make_tool_call_chunks("test_tool", {"q": "hello"}),
                [LLMChunk(type="done")],  # empty response
                _make_text_chunks("Here is my analysis"),
            ]
        )
        engine = _build_engine(provider, registry)

        events = await _collect_events(
            engine,
            user_message="Analyze this",
            conversation_id="conv-1",
        )

        text_events = [e for e in events if isinstance(e, TextDelta)]
        full_text = "".join(e.content for e in text_events)
        assert "analysis" in full_text.lower()
        assert isinstance(events[-1], DoneEvent)

    @pytest.mark.asyncio
    async def test_double_empty_response_yields_fallback(self):
        """If even the nudge retry returns empty, yield a user-visible fallback."""
        registry = ToolRegistry()

        async def echo_handler(**kwargs):
            return {"data": "result"}

        registry.register(
            ToolDefinition(
                name="test_tool",
                description="A test tool",
                parameters_schema={"type": "object", "properties": {}},
                handler=echo_handler,
            )
        )

        # Iteration 1: tool call
        # Iteration 2: empty (triggers nudge + force_no_tools)
        # Iteration 3: empty again (forced text mode) — should yield fallback
        provider = _MockModelProvider(
            [
                _make_tool_call_chunks("test_tool", {}),
                [LLMChunk(type="done")],  # empty
                [LLMChunk(type="done")],  # empty again
            ]
        )
        engine = _build_engine(provider, registry)

        events = await _collect_events(
            engine,
            user_message="Do something",
            conversation_id="conv-1",
        )

        text_events = [e for e in events if isinstance(e, TextDelta)]
        full_text = "".join(e.content for e in text_events)
        # Should contain the fallback message with tool results
        assert "ran into trouble" in full_text.lower() or "here's what i found" in full_text.lower()
        # Should include the tool result data
        assert "test_tool" in full_text
        assert isinstance(events[-1], DoneEvent)

    @pytest.mark.asyncio
    async def test_multiple_tool_calls_then_empty_recovers(self):
        """Multiple rounds of tool calls followed by empty should still recover."""
        registry = ToolRegistry()

        async def handler(**kwargs):
            return {"ok": True}

        registry.register(
            ToolDefinition(
                name="tool_a",
                description="Tool A",
                parameters_schema={"type": "object", "properties": {}},
                handler=handler,
            )
        )
        registry.register(
            ToolDefinition(
                name="tool_b",
                description="Tool B",
                parameters_schema={"type": "object", "properties": {}},
                handler=handler,
            )
        )

        # Iteration 1: tool_a call
        # Iteration 2: tool_b call
        # Iteration 3: empty (triggers nudge)
        # Iteration 4: text response
        provider = _MockModelProvider(
            [
                _make_tool_call_chunks("tool_a", {}, tool_call_id="tc_a"),
                _make_tool_call_chunks("tool_b", {}, tool_call_id="tc_b"),
                [LLMChunk(type="done")],  # empty
                _make_text_chunks("Based on the data I gathered"),
            ]
        )
        engine = _build_engine(provider, registry)

        events = await _collect_events(
            engine,
            user_message="Check both tools",
            conversation_id="conv-1",
        )

        tool_starts = [e for e in events if isinstance(e, ToolCallStart)]
        assert len(tool_starts) == 2

        text_events = [e for e in events if isinstance(e, TextDelta)]
        full_text = "".join(e.content for e in text_events)
        assert "data" in full_text.lower()
        assert isinstance(events[-1], DoneEvent)


# ---------------------------------------------------------------------------
# Tests: hallucinated tool calls (DeepSeek XML markup bug)
# ---------------------------------------------------------------------------


class TestHallucinatedToolCalls:
    """Verify the engine detects and recovers from hallucinated tool calls.

    DeepSeek sometimes outputs XML-like markup (e.g. <｜DSML｜function_calls>)
    as text instead of using the tool_calls API.  The engine should detect
    this, strip the markup, and retry.
    """

    @pytest.mark.asyncio
    async def test_detects_hallucinated_tool_call_and_retries(self):
        """When LLM outputs XML tool markup as text, engine should retry."""
        registry = ToolRegistry()

        async def handler(**kwargs):
            return {"data": "real result"}

        registry.register(
            ToolDefinition(
                name="query_pipeline_throughput",
                description="Query pipeline throughput",
                parameters_schema={"type": "object", "properties": {}},
                handler=handler,
            )
        )

        hallucinated_text = (
            "Let me check the pipeline throughput:\n"
            '<｜DSML｜function_calls>\n'
            '<｜DSML｜invoke name="query_pipeline_throughput">\n'
            '</｜DSML｜invoke>\n'
            '</｜DSML｜function_calls>'
        )

        # Iteration 1: LLM hallucinates tool call as text
        # Iteration 2: LLM properly calls the tool via API
        # Iteration 3: LLM returns text response
        provider = _MockModelProvider(
            [
                _make_text_chunks(hallucinated_text),
                _make_tool_call_chunks("query_pipeline_throughput", {}),
                _make_text_chunks("The pipeline throughput is healthy"),
            ]
        )
        engine = _build_engine(provider, registry)

        events = await _collect_events(
            engine,
            user_message="Check pipeline throughput",
            conversation_id="conv-1",
        )

        # Should have tool call events from the proper API call
        tool_starts = [e for e in events if isinstance(e, ToolCallStart)]
        assert len(tool_starts) == 1
        assert tool_starts[0].tool_name == "query_pipeline_throughput"

        # Should end with text and DoneEvent
        text_events = [e for e in events if isinstance(e, TextDelta)]
        full_text = "".join(e.content for e in text_events)
        assert "pipeline throughput" in full_text.lower()
        assert isinstance(events[-1], DoneEvent)

    @pytest.mark.asyncio
    async def test_hallucinated_then_text_only_response(self):
        """After hallucination retry, LLM may respond with text only (no tools)."""
        hallucinated_text = (
            "I'll look that up:\n"
            '<function_calls><invoke name="query_trades"></invoke></function_calls>'
        )

        # Iteration 1: hallucinated markup
        # Iteration 2: proper text response (LLM decides it has enough info)
        provider = _MockModelProvider(
            [
                _make_text_chunks(hallucinated_text),
                _make_text_chunks("Based on available data the trades look good"),
            ]
        )
        engine = _build_engine(provider)

        events = await _collect_events(
            engine,
            user_message="How are my trades?",
            conversation_id="conv-1",
        )

        text_events = [e for e in events if isinstance(e, TextDelta)]
        full_text = "".join(e.content for e in text_events)
        assert "trades look good" in full_text.lower()
        assert isinstance(events[-1], DoneEvent)


# ---------------------------------------------------------------------------
# Tests: hallucinated tool call detection helpers
# ---------------------------------------------------------------------------

from quantgambit.copilot.engine import (
    _contains_hallucinated_tool_calls,
    _strip_hallucinated_tool_calls,
)


class TestHallucinatedToolCallHelpers:
    def test_detects_dsml_function_calls(self):
        text = '<｜DSML｜function_calls><｜DSML｜invoke name="foo"></｜DSML｜invoke></｜DSML｜function_calls>'
        assert _contains_hallucinated_tool_calls(text) is True

    def test_detects_plain_function_calls(self):
        text = '<function_calls><invoke name="bar"></invoke></function_calls>'
        assert _contains_hallucinated_tool_calls(text) is True

    def test_detects_invoke_tag(self):
        text = 'Let me check: <invoke name="query_trades">'
        assert _contains_hallucinated_tool_calls(text) is True

    def test_no_false_positive_on_normal_text(self):
        text = "The function calls were successful and returned 42 results."
        assert _contains_hallucinated_tool_calls(text) is False

    def test_no_false_positive_on_code_discussion(self):
        text = "You can use `tool_call_id` to track the response."
        assert _contains_hallucinated_tool_calls(text) is False

    def test_strips_dsml_markup(self):
        text = (
            "Let me check:\n"
            '<｜DSML｜function_calls>\n'
            '<｜DSML｜invoke name="query_pipeline_throughput">\n'
            '</｜DSML｜invoke>\n'
            '</｜DSML｜function_calls>'
        )
        cleaned = _strip_hallucinated_tool_calls(text)
        assert "Let me check:" in cleaned
        assert "function_calls" not in cleaned
        assert "invoke" not in cleaned

    def test_strips_plain_markup(self):
        text = 'Hello <function_calls><invoke name="foo"></invoke></function_calls> world'
        cleaned = _strip_hallucinated_tool_calls(text)
        assert "Hello" in cleaned
        assert "function_calls" not in cleaned

    def test_preserves_text_before_markup(self):
        text = "Here is my analysis of the data.\n<function_calls><invoke name=\"x\"></invoke></function_calls>"
        cleaned = _strip_hallucinated_tool_calls(text)
        assert "Here is my analysis" in cleaned
