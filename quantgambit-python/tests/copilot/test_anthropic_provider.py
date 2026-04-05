"""Unit tests for AnthropicProvider."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from quantgambit.copilot.models import LLMChunk
from quantgambit.copilot.providers.anthropic import AnthropicProvider


# ---------------------------------------------------------------------------
# Helpers – SSE line builders
# ---------------------------------------------------------------------------


def _sse_event(event_type: str, data: dict) -> list[str]:
    """Build SSE lines for an Anthropic event (event + data lines)."""
    return [f"event: {event_type}", f"data: {json.dumps(data)}"]


def _message_start() -> list[str]:
    return _sse_event("message_start", {
        "type": "message_start",
        "message": {"id": "msg_1", "type": "message", "role": "assistant", "content": []},
    })


def _text_block_start(index: int = 0) -> list[str]:
    return _sse_event("content_block_start", {
        "type": "content_block_start",
        "index": index,
        "content_block": {"type": "text", "text": ""},
    })


def _text_delta(index: int, text: str) -> list[str]:
    return _sse_event("content_block_delta", {
        "type": "content_block_delta",
        "index": index,
        "delta": {"type": "text_delta", "text": text},
    })


def _block_stop(index: int) -> list[str]:
    return _sse_event("content_block_stop", {
        "type": "content_block_stop",
        "index": index,
    })


def _tool_use_start(index: int, tool_id: str, name: str) -> list[str]:
    return _sse_event("content_block_start", {
        "type": "content_block_start",
        "index": index,
        "content_block": {"type": "tool_use", "id": tool_id, "name": name},
    })


def _tool_input_delta(index: int, partial_json: str) -> list[str]:
    return _sse_event("content_block_delta", {
        "type": "content_block_delta",
        "index": index,
        "delta": {"type": "input_json_delta", "partial_json": partial_json},
    })


def _message_delta(stop_reason: str = "end_turn") -> list[str]:
    return _sse_event("message_delta", {
        "type": "message_delta",
        "delta": {"stop_reason": stop_reason},
    })


def _message_stop() -> list[str]:
    return _sse_event("message_stop", {"type": "message_stop"})


# ---------------------------------------------------------------------------
# Fake httpx helpers (same pattern as OpenAI tests)
# ---------------------------------------------------------------------------


class _FakeAsyncLineIterator:
    def __init__(self, lines: list[str]) -> None:
        self._lines = lines
        self._idx = 0

    def __aiter__(self):
        return self

    async def __anext__(self) -> str:
        if self._idx >= len(self._lines):
            raise StopAsyncIteration
        line = self._lines[self._idx]
        self._idx += 1
        return line


class _FakeStreamResponse:
    def __init__(self, lines: list[str], status_code: int = 200) -> None:
        self._lines = lines
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                "error", request=MagicMock(), response=MagicMock(status_code=self.status_code)
            )

    def aiter_lines(self):
        return _FakeAsyncLineIterator(self._lines)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


class _FakeAsyncClient:
    def __init__(self, stream_response: _FakeStreamResponse) -> None:
        self._stream_response = stream_response

    def stream(self, method, url, **kwargs):
        return self._stream_response

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


def _build_lines(*event_groups: list[str]) -> list[str]:
    """Flatten event groups into a single line list with blank separators."""
    lines: list[str] = []
    for group in event_groups:
        lines.extend(group)
        lines.append("")  # blank line between events
    return lines


# ---------------------------------------------------------------------------
# _parse_event – text deltas
# ---------------------------------------------------------------------------


class TestParseEventText:
    def test_text_block_start_no_chunks(self):
        chunks = AnthropicProvider._parse_event(
            "content_block_start",
            {"index": 0, "content_block": {"type": "text", "text": ""}},
            {},
        )
        assert chunks == []

    def test_text_delta(self):
        active: dict[int, dict] = {0: {"type": "text"}}
        chunks = AnthropicProvider._parse_event(
            "content_block_delta",
            {"index": 0, "delta": {"type": "text_delta", "text": "Hello"}},
            active,
        )
        assert len(chunks) == 1
        assert chunks[0].type == "text_delta"
        assert chunks[0].content == "Hello"

    def test_empty_text_delta_ignored(self):
        active: dict[int, dict] = {0: {"type": "text"}}
        chunks = AnthropicProvider._parse_event(
            "content_block_delta",
            {"index": 0, "delta": {"type": "text_delta", "text": ""}},
            active,
        )
        assert chunks == []

    def test_text_block_stop_no_chunks(self):
        active: dict[int, dict] = {0: {"type": "text"}}
        chunks = AnthropicProvider._parse_event(
            "content_block_stop",
            {"index": 0},
            active,
        )
        assert chunks == []
        assert 0 not in active


# ---------------------------------------------------------------------------
# _parse_event – tool calls
# ---------------------------------------------------------------------------


class TestParseEventToolCalls:
    def test_tool_use_start(self):
        active: dict[int, dict] = {}
        chunks = AnthropicProvider._parse_event(
            "content_block_start",
            {"index": 0, "content_block": {"type": "tool_use", "id": "toolu_1", "name": "query_trades"}},
            active,
        )
        assert len(chunks) == 1
        assert chunks[0].type == "tool_call_start"
        assert chunks[0].tool_call_id == "toolu_1"
        assert chunks[0].tool_name == "query_trades"
        assert chunks[0].tool_arguments == ""
        assert 0 in active

    def test_tool_input_delta(self):
        active: dict[int, dict] = {
            0: {"type": "tool_use", "id": "toolu_1", "name": "query_trades", "arguments": '{"sym'}
        }
        chunks = AnthropicProvider._parse_event(
            "content_block_delta",
            {"index": 0, "delta": {"type": "input_json_delta", "partial_json": 'bol": "BTC"}'}},
            active,
        )
        assert len(chunks) == 1
        assert chunks[0].type == "tool_call_delta"
        assert chunks[0].tool_call_id == "toolu_1"
        assert chunks[0].tool_name == "query_trades"
        assert chunks[0].tool_arguments == 'bol": "BTC"}'
        assert active[0]["arguments"] == '{"symbol": "BTC"}'

    def test_tool_block_stop(self):
        active: dict[int, dict] = {
            0: {"type": "tool_use", "id": "toolu_1", "name": "query_trades", "arguments": '{"symbol": "BTC"}'}
        }
        chunks = AnthropicProvider._parse_event(
            "content_block_stop",
            {"index": 0},
            active,
        )
        assert len(chunks) == 1
        assert chunks[0].type == "tool_call_end"
        assert chunks[0].tool_call_id == "toolu_1"
        assert chunks[0].tool_name == "query_trades"
        assert chunks[0].tool_arguments == '{"symbol": "BTC"}'
        assert 0 not in active

    def test_multiple_parallel_tool_calls(self):
        active: dict[int, dict] = {}
        # Start two tool calls
        c1 = AnthropicProvider._parse_event(
            "content_block_start",
            {"index": 0, "content_block": {"type": "tool_use", "id": "toolu_a", "name": "tool_a"}},
            active,
        )
        c2 = AnthropicProvider._parse_event(
            "content_block_start",
            {"index": 1, "content_block": {"type": "tool_use", "id": "toolu_b", "name": "tool_b"}},
            active,
        )
        assert c1[0].type == "tool_call_start"
        assert c2[0].type == "tool_call_start"
        assert len(active) == 2

        # Stop both
        e1 = AnthropicProvider._parse_event("content_block_stop", {"index": 0}, active)
        e2 = AnthropicProvider._parse_event("content_block_stop", {"index": 1}, active)
        assert e1[0].type == "tool_call_end"
        assert e1[0].tool_name == "tool_a"
        assert e2[0].type == "tool_call_end"
        assert e2[0].tool_name == "tool_b"
        assert len(active) == 0


# ---------------------------------------------------------------------------
# _parse_event – ignored events
# ---------------------------------------------------------------------------


class TestParseEventIgnored:
    def test_message_start_ignored(self):
        chunks = AnthropicProvider._parse_event(
            "message_start",
            {"type": "message_start", "message": {"id": "msg_1"}},
            {},
        )
        assert chunks == []

    def test_message_delta_ignored(self):
        chunks = AnthropicProvider._parse_event(
            "message_delta",
            {"type": "message_delta", "delta": {"stop_reason": "end_turn"}},
            {},
        )
        assert chunks == []

    def test_message_stop_ignored(self):
        chunks = AnthropicProvider._parse_event(
            "message_stop",
            {"type": "message_stop"},
            {},
        )
        assert chunks == []

    def test_unknown_event_type(self):
        chunks = AnthropicProvider._parse_event("ping", {}, {})
        assert chunks == []


# ---------------------------------------------------------------------------
# _convert_messages
# ---------------------------------------------------------------------------


class TestConvertMessages:
    def test_system_message_extracted(self):
        messages = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Hi"},
        ]
        system, api_msgs = AnthropicProvider._convert_messages(messages)
        assert system == "You are helpful."
        assert len(api_msgs) == 1
        assert api_msgs[0]["role"] == "user"

    def test_no_system_message(self):
        messages = [{"role": "user", "content": "Hi"}]
        system, api_msgs = AnthropicProvider._convert_messages(messages)
        assert system is None
        assert len(api_msgs) == 1

    def test_assistant_message_plain(self):
        messages = [{"role": "assistant", "content": "Hello!"}]
        _, api_msgs = AnthropicProvider._convert_messages(messages)
        assert api_msgs[0]["role"] == "assistant"
        assert api_msgs[0]["content"] == "Hello!"

    def test_assistant_message_with_tool_calls(self):
        messages = [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "function": {"name": "query_trades", "arguments": '{"symbol": "BTC"}'},
                    }
                ],
            }
        ]
        _, api_msgs = AnthropicProvider._convert_messages(messages)
        assert api_msgs[0]["role"] == "assistant"
        blocks = api_msgs[0]["content"]
        assert isinstance(blocks, list)
        assert len(blocks) == 1
        assert blocks[0]["type"] == "tool_use"
        assert blocks[0]["id"] == "call_1"
        assert blocks[0]["name"] == "query_trades"
        assert blocks[0]["input"] == {"symbol": "BTC"}

    def test_assistant_with_text_and_tool_calls(self):
        messages = [
            {
                "role": "assistant",
                "content": "Let me check.",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "function": {"name": "query_trades", "arguments": "{}"},
                    }
                ],
            }
        ]
        _, api_msgs = AnthropicProvider._convert_messages(messages)
        blocks = api_msgs[0]["content"]
        assert len(blocks) == 2
        assert blocks[0]["type"] == "text"
        assert blocks[0]["text"] == "Let me check."
        assert blocks[1]["type"] == "tool_use"

    def test_tool_result_message(self):
        messages = [
            {"role": "tool", "content": '{"trades": []}', "tool_call_id": "call_1"},
        ]
        _, api_msgs = AnthropicProvider._convert_messages(messages)
        assert api_msgs[0]["role"] == "user"
        blocks = api_msgs[0]["content"]
        assert len(blocks) == 1
        assert blocks[0]["type"] == "tool_result"
        assert blocks[0]["tool_use_id"] == "call_1"
        assert blocks[0]["content"] == '{"trades": []}'

    def test_malformed_tool_call_arguments(self):
        messages = [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"id": "call_1", "function": {"name": "t", "arguments": "not json"}},
                ],
            }
        ]
        _, api_msgs = AnthropicProvider._convert_messages(messages)
        blocks = api_msgs[0]["content"]
        assert blocks[0]["input"] == {}


# ---------------------------------------------------------------------------
# _build_payload
# ---------------------------------------------------------------------------


class TestBuildPayload:
    def test_basic_payload(self):
        provider = AnthropicProvider(api_key="sk-ant-test", model="claude-3-5-sonnet-20241022")
        payload = provider._build_payload(
            messages=[{"role": "user", "content": "hi"}],
            system_prompt=None,
            tools=None,
            temperature=0.5,
        )
        assert payload["model"] == "claude-3-5-sonnet-20241022"
        assert payload["stream"] is True
        assert payload["temperature"] == 0.5
        assert payload["max_tokens"] == 4096
        assert "system" not in payload
        assert "tools" not in payload

    def test_payload_with_system(self):
        provider = AnthropicProvider(api_key="k", model="m")
        payload = provider._build_payload(
            messages=[{"role": "user", "content": "hi"}],
            system_prompt="Be helpful.",
            tools=None,
            temperature=0.1,
        )
        assert payload["system"] == "Be helpful."

    def test_payload_with_tools(self):
        provider = AnthropicProvider(api_key="k", model="m")
        tools = [{"name": "my_tool", "description": "desc", "parameters": {"type": "object"}}]
        payload = provider._build_payload(
            messages=[{"role": "user", "content": "hi"}],
            system_prompt=None,
            tools=tools,
            temperature=0.1,
        )
        assert len(payload["tools"]) == 1
        assert payload["tools"][0]["name"] == "my_tool"
        assert payload["tools"][0]["description"] == "desc"
        assert payload["tools"][0]["input_schema"] == {"type": "object"}


# ---------------------------------------------------------------------------
# _build_headers
# ---------------------------------------------------------------------------


class TestBuildHeaders:
    def test_headers(self):
        provider = AnthropicProvider(api_key="sk-ant-secret", model="m")
        headers = provider._build_headers()
        assert headers["x-api-key"] == "sk-ant-secret"
        assert headers["anthropic-version"] == "2023-06-01"
        assert headers["Content-Type"] == "application/json"


# ---------------------------------------------------------------------------
# Constructor
# ---------------------------------------------------------------------------


class TestConstructor:
    def test_stores_api_key_and_model(self):
        provider = AnthropicProvider(api_key="key", model="claude-3-5-sonnet-20241022")
        assert provider._api_key == "key"
        assert provider._model == "claude-3-5-sonnet-20241022"


# ---------------------------------------------------------------------------
# Full streaming flow (mocked httpx)
# ---------------------------------------------------------------------------


class TestStreamingFlow:
    @pytest.mark.asyncio
    async def test_text_stream(self):
        lines = _build_lines(
            _message_start(),
            _text_block_start(0),
            _text_delta(0, "Hello "),
            _text_delta(0, "world"),
            _block_stop(0),
            _message_delta(),
            _message_stop(),
        )
        fake_resp = _FakeStreamResponse(lines)
        fake_client = _FakeAsyncClient(fake_resp)

        provider = AnthropicProvider(api_key="k", model="m")
        with patch("quantgambit.copilot.providers.anthropic.httpx.AsyncClient", return_value=fake_client):
            chunks = [c async for c in provider.chat_completion_stream([{"role": "user", "content": "hi"}])]

        text_chunks = [c for c in chunks if c.type == "text_delta"]
        assert len(text_chunks) == 2
        assert text_chunks[0].content == "Hello "
        assert text_chunks[1].content == "world"
        assert chunks[-1].type == "done"

    @pytest.mark.asyncio
    async def test_tool_call_stream(self):
        lines = _build_lines(
            _message_start(),
            _tool_use_start(0, "toolu_1", "query_trades"),
            _tool_input_delta(0, '{"sym'),
            _tool_input_delta(0, 'bol": "BTC"}'),
            _block_stop(0),
            _message_delta("tool_use"),
            _message_stop(),
        )
        fake_resp = _FakeStreamResponse(lines)
        fake_client = _FakeAsyncClient(fake_resp)

        provider = AnthropicProvider(api_key="k", model="m")
        with patch("quantgambit.copilot.providers.anthropic.httpx.AsyncClient", return_value=fake_client):
            chunks = [c async for c in provider.chat_completion_stream([{"role": "user", "content": "hi"}])]

        types = [c.type for c in chunks]
        assert "tool_call_start" in types
        assert "tool_call_delta" in types
        assert "tool_call_end" in types
        assert types[-1] == "done"

        end_chunk = [c for c in chunks if c.type == "tool_call_end"][0]
        assert end_chunk.tool_name == "query_trades"
        assert json.loads(end_chunk.tool_arguments) == {"symbol": "BTC"}

    @pytest.mark.asyncio
    async def test_text_and_tool_call_mixed(self):
        """Anthropic can return text followed by a tool call in the same message."""
        lines = _build_lines(
            _message_start(),
            _text_block_start(0),
            _text_delta(0, "Let me check."),
            _block_stop(0),
            _tool_use_start(1, "toolu_2", "query_positions"),
            _tool_input_delta(1, "{}"),
            _block_stop(1),
            _message_delta("tool_use"),
            _message_stop(),
        )
        fake_resp = _FakeStreamResponse(lines)
        fake_client = _FakeAsyncClient(fake_resp)

        provider = AnthropicProvider(api_key="k", model="m")
        with patch("quantgambit.copilot.providers.anthropic.httpx.AsyncClient", return_value=fake_client):
            chunks = [c async for c in provider.chat_completion_stream([{"role": "user", "content": "hi"}])]

        text_chunks = [c for c in chunks if c.type == "text_delta"]
        assert len(text_chunks) == 1
        assert text_chunks[0].content == "Let me check."

        end_chunks = [c for c in chunks if c.type == "tool_call_end"]
        assert len(end_chunks) == 1
        assert end_chunks[0].tool_name == "query_positions"

    @pytest.mark.asyncio
    async def test_malformed_sse_data_skipped(self):
        lines = _build_lines(
            _message_start(),
            _text_block_start(0),
            _text_delta(0, "ok"),
        )
        # Inject a malformed data line
        lines.append("data: {invalid json")
        lines.append("")
        lines.extend(_build_lines(
            _text_delta(0, " still ok"),
            _block_stop(0),
            _message_stop(),
        ))
        fake_resp = _FakeStreamResponse(lines)
        fake_client = _FakeAsyncClient(fake_resp)

        provider = AnthropicProvider(api_key="k", model="m")
        with patch("quantgambit.copilot.providers.anthropic.httpx.AsyncClient", return_value=fake_client):
            chunks = [c async for c in provider.chat_completion_stream([{"role": "user", "content": "hi"}])]

        text_chunks = [c for c in chunks if c.type == "text_delta"]
        assert len(text_chunks) == 2

    @pytest.mark.asyncio
    async def test_non_data_lines_ignored(self):
        lines = [
            ": comment line",
            "retry: 5000",
        ]
        lines.extend(_build_lines(
            _message_start(),
            _text_block_start(0),
            _text_delta(0, "hi"),
            _block_stop(0),
            _message_stop(),
        ))
        fake_resp = _FakeStreamResponse(lines)
        fake_client = _FakeAsyncClient(fake_resp)

        provider = AnthropicProvider(api_key="k", model="m")
        with patch("quantgambit.copilot.providers.anthropic.httpx.AsyncClient", return_value=fake_client):
            chunks = [c async for c in provider.chat_completion_stream([{"role": "user", "content": "hi"}])]

        text_chunks = [c for c in chunks if c.type == "text_delta"]
        assert len(text_chunks) == 1

    @pytest.mark.asyncio
    async def test_system_message_passed_in_payload(self):
        """Verify system message is extracted and passed as top-level field."""
        captured_payload = {}

        class _CapturingClient:
            def stream(self, method, url, **kwargs):
                captured_payload.update(kwargs.get("json", {}))
                return _FakeStreamResponse(_build_lines(_message_start(), _message_stop()))

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

        provider = AnthropicProvider(api_key="k", model="m")
        messages = [
            {"role": "system", "content": "You are a trading assistant."},
            {"role": "user", "content": "Show trades"},
        ]
        with patch("quantgambit.copilot.providers.anthropic.httpx.AsyncClient", return_value=_CapturingClient()):
            _ = [c async for c in provider.chat_completion_stream(messages)]

        assert captured_payload.get("system") == "You are a trading assistant."
        # System message should NOT appear in the messages array
        for msg in captured_payload.get("messages", []):
            assert msg["role"] != "system"


# ---------------------------------------------------------------------------
# Retry logic
# ---------------------------------------------------------------------------


class TestRetryLogic:
    @pytest.mark.asyncio
    async def test_retries_on_connect_error(self):
        call_count = 0

        class _FailingClient:
            def stream(self, *a, **kw):
                return self

            async def __aenter__(self):
                nonlocal call_count
                call_count += 1
                raise httpx.ConnectError("refused")

            async def __aexit__(self, *args):
                pass

        class _FailingOuter:
            async def __aenter__(self):
                return _FailingClient()

            async def __aexit__(self, *args):
                pass

        provider = AnthropicProvider(api_key="k", model="m")
        with patch("quantgambit.copilot.providers.anthropic.httpx.AsyncClient", return_value=_FailingOuter()):
            with patch("quantgambit.copilot.providers.anthropic.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
                chunks = [c async for c in provider.chat_completion_stream([{"role": "user", "content": "hi"}])]

        assert chunks[-1].type == "done"
        assert mock_sleep.call_count == 2  # retries after attempt 1 and 2

    @pytest.mark.asyncio
    async def test_succeeds_on_second_attempt(self):
        attempt = 0
        lines = _build_lines(
            _message_start(),
            _text_block_start(0),
            _text_delta(0, "recovered"),
            _block_stop(0),
            _message_stop(),
        )

        class _RetryClient:
            def stream(self, *a, **kw):
                return self

            async def __aenter__(self):
                nonlocal attempt
                attempt += 1
                if attempt == 1:
                    raise httpx.ConnectError("first fail")
                return _FakeStreamResponse(lines)

            async def __aexit__(self, *args):
                pass

        class _RetryOuter:
            async def __aenter__(self):
                return _RetryClient()

            async def __aexit__(self, *args):
                pass

        provider = AnthropicProvider(api_key="k", model="m")
        with patch("quantgambit.copilot.providers.anthropic.httpx.AsyncClient", return_value=_RetryOuter()):
            with patch("quantgambit.copilot.providers.anthropic.asyncio.sleep", new_callable=AsyncMock):
                chunks = [c async for c in provider.chat_completion_stream([{"role": "user", "content": "hi"}])]

        text_chunks = [c for c in chunks if c.type == "text_delta"]
        assert len(text_chunks) == 1
        assert text_chunks[0].content == "recovered"

    @pytest.mark.asyncio
    async def test_retries_on_connect_timeout(self):
        call_count = 0

        class _TimeoutClient:
            def stream(self, *a, **kw):
                return self

            async def __aenter__(self):
                nonlocal call_count
                call_count += 1
                raise httpx.ConnectTimeout("timeout")

            async def __aexit__(self, *args):
                pass

        class _TimeoutOuter:
            async def __aenter__(self):
                return _TimeoutClient()

            async def __aexit__(self, *args):
                pass

        provider = AnthropicProvider(api_key="k", model="m")
        with patch("quantgambit.copilot.providers.anthropic.httpx.AsyncClient", return_value=_TimeoutOuter()):
            with patch("quantgambit.copilot.providers.anthropic.asyncio.sleep", new_callable=AsyncMock):
                chunks = [c async for c in provider.chat_completion_stream([{"role": "user", "content": "hi"}])]

        assert chunks[-1].type == "done"
