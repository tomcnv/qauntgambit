"""Unit tests for OpenAIProvider."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from quantgambit.copilot.models import LLMChunk
from quantgambit.copilot.providers.openai import OpenAIProvider


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sse_line(data: dict | str) -> str:
    """Build a single SSE data line."""
    if isinstance(data, str):
        return f"data: {data}"
    return f"data: {json.dumps(data)}"


def _text_chunk(content: str, finish_reason: str | None = None) -> dict:
    """Build an OpenAI streaming chunk with text content."""
    return {
        "choices": [
            {
                "delta": {"content": content},
                "finish_reason": finish_reason,
            }
        ]
    }


def _tool_call_chunk(
    index: int = 0,
    tc_id: str | None = None,
    name: str | None = None,
    arguments: str = "",
    finish_reason: str | None = None,
) -> dict:
    """Build an OpenAI streaming chunk with a tool call delta."""
    fn: dict = {"arguments": arguments}
    if name is not None:
        fn["name"] = name
    tc: dict = {"index": index, "function": fn}
    if tc_id is not None:
        tc["id"] = tc_id
    return {
        "choices": [
            {
                "delta": {"tool_calls": [tc]},
                "finish_reason": finish_reason,
            }
        ]
    }


def _finish_chunk(reason: str = "stop") -> dict:
    return {"choices": [{"delta": {}, "finish_reason": reason}]}


# ---------------------------------------------------------------------------
# _parse_chunk – text deltas
# ---------------------------------------------------------------------------


class TestParseChunkText:
    def test_text_delta(self):
        chunks = OpenAIProvider._parse_chunk(_text_chunk("Hello"), {})
        assert len(chunks) == 1
        assert chunks[0].type == "text_delta"
        assert chunks[0].content == "Hello"

    def test_empty_choices(self):
        chunks = OpenAIProvider._parse_chunk({"choices": []}, {})
        assert chunks == []

    def test_empty_delta(self):
        chunks = OpenAIProvider._parse_chunk({"choices": [{"delta": {}}]}, {})
        assert chunks == []


# ---------------------------------------------------------------------------
# _parse_chunk – tool calls
# ---------------------------------------------------------------------------


class TestParseChunkToolCalls:
    def test_tool_call_start(self):
        active: dict[int, dict] = {}
        data = _tool_call_chunk(index=0, tc_id="call_1", name="query_trades", arguments='{"sym')
        chunks = OpenAIProvider._parse_chunk(data, active)
        assert len(chunks) == 1
        assert chunks[0].type == "tool_call_start"
        assert chunks[0].tool_call_id == "call_1"
        assert chunks[0].tool_name == "query_trades"
        assert chunks[0].tool_arguments == '{"sym'
        assert 0 in active

    def test_tool_call_delta(self):
        active: dict[int, dict] = {0: {"id": "call_1", "name": "query_trades", "arguments": '{"sym'}}
        data = _tool_call_chunk(index=0, arguments='bol": "BTC"}')
        chunks = OpenAIProvider._parse_chunk(data, active)
        assert len(chunks) == 1
        assert chunks[0].type == "tool_call_delta"
        assert chunks[0].tool_arguments == 'bol": "BTC"}'
        assert active[0]["arguments"] == '{"symbol": "BTC"}'

    def test_tool_call_end_on_finish_reason(self):
        active: dict[int, dict] = {0: {"id": "call_1", "name": "query_trades", "arguments": '{"symbol": "BTC"}'}}
        data = _finish_chunk("tool_calls")
        chunks = OpenAIProvider._parse_chunk(data, active)
        assert len(chunks) == 1
        assert chunks[0].type == "tool_call_end"
        assert chunks[0].tool_call_id == "call_1"
        assert chunks[0].tool_name == "query_trades"
        assert chunks[0].tool_arguments == '{"symbol": "BTC"}'
        assert len(active) == 0  # cleared

    def test_multiple_parallel_tool_calls(self):
        active: dict[int, dict] = {}
        # First tool call start
        c1 = OpenAIProvider._parse_chunk(
            _tool_call_chunk(index=0, tc_id="call_a", name="tool_a", arguments="{}"),
            active,
        )
        # Second tool call start
        c2 = OpenAIProvider._parse_chunk(
            _tool_call_chunk(index=1, tc_id="call_b", name="tool_b", arguments="{}"),
            active,
        )
        assert c1[0].type == "tool_call_start"
        assert c2[0].type == "tool_call_start"
        assert len(active) == 2

        # Finish both
        end_chunks = OpenAIProvider._parse_chunk(_finish_chunk("tool_calls"), active)
        assert len(end_chunks) == 2
        names = {c.tool_name for c in end_chunks}
        assert names == {"tool_a", "tool_b"}


# ---------------------------------------------------------------------------
# _build_payload
# ---------------------------------------------------------------------------


class TestBuildPayload:
    def test_basic_payload(self):
        provider = OpenAIProvider(api_key="sk-test", model="gpt-4o")
        payload = provider._build_payload(
            messages=[{"role": "user", "content": "hi"}],
            tools=None,
            temperature=0.5,
        )
        assert payload["model"] == "gpt-4o"
        assert payload["stream"] is True
        assert payload["temperature"] == 0.5
        assert "tools" not in payload

    def test_payload_with_tools(self):
        provider = OpenAIProvider(api_key="sk-test", model="gpt-4o")
        tools = [{"name": "my_tool", "description": "desc", "parameters": {}}]
        payload = provider._build_payload(
            messages=[{"role": "user", "content": "hi"}],
            tools=tools,
            temperature=0.1,
        )
        assert len(payload["tools"]) == 1
        assert payload["tools"][0]["type"] == "function"
        assert payload["tools"][0]["function"]["name"] == "my_tool"


# ---------------------------------------------------------------------------
# _build_headers
# ---------------------------------------------------------------------------


class TestBuildHeaders:
    def test_authorization_header(self):
        provider = OpenAIProvider(api_key="sk-secret", model="gpt-4o")
        headers = provider._build_headers()
        assert headers["Authorization"] == "Bearer sk-secret"
        assert headers["Content-Type"] == "application/json"


# ---------------------------------------------------------------------------
# Constructor
# ---------------------------------------------------------------------------


class TestConstructor:
    def test_default_base_url(self):
        provider = OpenAIProvider(api_key="k", model="m")
        assert provider._base_url == "https://api.openai.com/v1"

    def test_custom_base_url_trailing_slash(self):
        provider = OpenAIProvider(api_key="k", model="m", base_url="http://localhost:8080/v1/")
        assert provider._base_url == "http://localhost:8080/v1"

    def test_custom_base_url(self):
        provider = OpenAIProvider(api_key="k", model="m", base_url="http://local:1234/v1")
        assert provider._base_url == "http://local:1234/v1"


# ---------------------------------------------------------------------------
# Full streaming flow (mocked httpx)
# ---------------------------------------------------------------------------


class _FakeAsyncLineIterator:
    """Simulate ``response.aiter_lines()``."""

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
    """Minimal mock for ``httpx.Response`` used inside ``client.stream()``."""

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
    """Minimal mock for ``httpx.AsyncClient``."""

    def __init__(self, stream_response: _FakeStreamResponse) -> None:
        self._stream_response = stream_response

    def stream(self, method, url, **kwargs):
        return self._stream_response

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


class TestStreamingFlow:
    @pytest.mark.asyncio
    async def test_text_stream(self):
        lines = [
            _sse_line(_text_chunk("Hello ")),
            _sse_line(_text_chunk("world")),
            "data: [DONE]",
        ]
        fake_resp = _FakeStreamResponse(lines)
        fake_client = _FakeAsyncClient(fake_resp)

        provider = OpenAIProvider(api_key="k", model="m")
        with patch("quantgambit.copilot.providers.openai.httpx.AsyncClient", return_value=fake_client):
            chunks = [c async for c in provider.chat_completion_stream([{"role": "user", "content": "hi"}])]

        text_chunks = [c for c in chunks if c.type == "text_delta"]
        assert len(text_chunks) == 2
        assert text_chunks[0].content == "Hello "
        assert text_chunks[1].content == "world"
        assert chunks[-1].type == "done"

    @pytest.mark.asyncio
    async def test_tool_call_stream(self):
        lines = [
            _sse_line(_tool_call_chunk(index=0, tc_id="call_1", name="query_trades", arguments='{"sym')),
            _sse_line(_tool_call_chunk(index=0, arguments='bol": "BTC"}')),
            _sse_line(_finish_chunk("tool_calls")),
            "data: [DONE]",
        ]
        fake_resp = _FakeStreamResponse(lines)
        fake_client = _FakeAsyncClient(fake_resp)

        provider = OpenAIProvider(api_key="k", model="m")
        with patch("quantgambit.copilot.providers.openai.httpx.AsyncClient", return_value=fake_client):
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
    async def test_malformed_sse_line_skipped(self):
        lines = [
            _sse_line(_text_chunk("ok")),
            "data: {invalid json",
            _sse_line(_text_chunk("still ok")),
            "data: [DONE]",
        ]
        fake_resp = _FakeStreamResponse(lines)
        fake_client = _FakeAsyncClient(fake_resp)

        provider = OpenAIProvider(api_key="k", model="m")
        with patch("quantgambit.copilot.providers.openai.httpx.AsyncClient", return_value=fake_client):
            chunks = [c async for c in provider.chat_completion_stream([{"role": "user", "content": "hi"}])]

        text_chunks = [c for c in chunks if c.type == "text_delta"]
        assert len(text_chunks) == 2

    @pytest.mark.asyncio
    async def test_non_data_lines_ignored(self):
        lines = [
            "",
            ": comment",
            "event: ping",
            _sse_line(_text_chunk("hi")),
            "data: [DONE]",
        ]
        fake_resp = _FakeStreamResponse(lines)
        fake_client = _FakeAsyncClient(fake_resp)

        provider = OpenAIProvider(api_key="k", model="m")
        with patch("quantgambit.copilot.providers.openai.httpx.AsyncClient", return_value=fake_client):
            chunks = [c async for c in provider.chat_completion_stream([{"role": "user", "content": "hi"}])]

        text_chunks = [c for c in chunks if c.type == "text_delta"]
        assert len(text_chunks) == 1


# ---------------------------------------------------------------------------
# Retry logic
# ---------------------------------------------------------------------------


class TestRetryLogic:
    @pytest.mark.asyncio
    async def test_retries_on_connect_error(self):
        """Should retry up to 3 times and yield done on exhaustion."""
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

        provider = OpenAIProvider(api_key="k", model="m")
        with patch("quantgambit.copilot.providers.openai.httpx.AsyncClient", return_value=_FailingOuter()):
            with patch("quantgambit.copilot.providers.openai.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
                chunks = [c async for c in provider.chat_completion_stream([{"role": "user", "content": "hi"}])]

        # Should have yielded a done chunk after exhausting retries
        assert chunks[-1].type == "done"
        # sleep called for retries (attempt 1 and 2, not after attempt 3)
        assert mock_sleep.call_count == 2

    @pytest.mark.asyncio
    async def test_succeeds_on_second_attempt(self):
        """Should succeed if the second attempt works."""
        attempt = 0

        lines = [
            _sse_line(_text_chunk("recovered")),
            "data: [DONE]",
        ]

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

        provider = OpenAIProvider(api_key="k", model="m")
        with patch("quantgambit.copilot.providers.openai.httpx.AsyncClient", return_value=_RetryOuter()):
            with patch("quantgambit.copilot.providers.openai.asyncio.sleep", new_callable=AsyncMock):
                chunks = [c async for c in provider.chat_completion_stream([{"role": "user", "content": "hi"}])]

        text_chunks = [c for c in chunks if c.type == "text_delta"]
        assert len(text_chunks) == 1
        assert text_chunks[0].content == "recovered"
