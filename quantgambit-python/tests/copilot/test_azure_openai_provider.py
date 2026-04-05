"""Unit tests for AzureOpenAIProvider."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from quantgambit.copilot.models import LLMChunk
from quantgambit.copilot.providers.azure_openai import AzureOpenAIProvider
from quantgambit.copilot.providers.openai import OpenAIProvider


# ---------------------------------------------------------------------------
# Helpers (reuse the same SSE helpers as the OpenAI tests)
# ---------------------------------------------------------------------------


def _sse_line(data: dict | str) -> str:
    if isinstance(data, str):
        return f"data: {data}"
    return f"data: {json.dumps(data)}"


def _text_chunk(content: str, finish_reason: str | None = None) -> dict:
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
# Fake httpx helpers
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
        self.last_url: str | None = None
        self.last_headers: dict | None = None

    def stream(self, method, url, **kwargs):
        self.last_url = url
        self.last_headers = kwargs.get("headers")
        return self._stream_response

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


# ---------------------------------------------------------------------------
# Constructor
# ---------------------------------------------------------------------------


class TestConstructor:
    def test_stores_endpoint_and_api_version(self):
        provider = AzureOpenAIProvider(
            api_key="az-key",
            model="gpt-4o",
            endpoint="https://myresource.openai.azure.com",
            api_version="2024-02-01",
        )
        assert provider._endpoint == "https://myresource.openai.azure.com"
        assert provider._api_version == "2024-02-01"
        assert provider._api_key == "az-key"
        assert provider._model == "gpt-4o"

    def test_endpoint_trailing_slash_stripped(self):
        provider = AzureOpenAIProvider(
            api_key="k",
            model="m",
            endpoint="https://myresource.openai.azure.com/",
            api_version="2024-02-01",
        )
        assert provider._endpoint == "https://myresource.openai.azure.com"

    def test_is_subclass_of_openai_provider(self):
        provider = AzureOpenAIProvider(
            api_key="k", model="m",
            endpoint="https://x.openai.azure.com",
            api_version="2024-02-01",
        )
        assert isinstance(provider, OpenAIProvider)


# ---------------------------------------------------------------------------
# _build_url
# ---------------------------------------------------------------------------


class TestBuildUrl:
    def test_url_format(self):
        provider = AzureOpenAIProvider(
            api_key="k",
            model="gpt-4o",
            endpoint="https://myresource.openai.azure.com",
            api_version="2024-02-01",
        )
        url = provider._build_url()
        assert url == (
            "https://myresource.openai.azure.com/openai/deployments/gpt-4o"
            "/chat/completions?api-version=2024-02-01"
        )

    def test_url_with_different_model(self):
        provider = AzureOpenAIProvider(
            api_key="k",
            model="gpt-35-turbo",
            endpoint="https://east.openai.azure.com",
            api_version="2023-12-01",
        )
        url = provider._build_url()
        assert "deployments/gpt-35-turbo" in url
        assert "api-version=2023-12-01" in url


# ---------------------------------------------------------------------------
# _build_headers
# ---------------------------------------------------------------------------


class TestBuildHeaders:
    def test_uses_api_key_header(self):
        provider = AzureOpenAIProvider(
            api_key="az-secret",
            model="m",
            endpoint="https://x.openai.azure.com",
            api_version="2024-02-01",
        )
        headers = provider._build_headers()
        assert headers["api-key"] == "az-secret"
        assert headers["Content-Type"] == "application/json"
        assert headers["Accept"] == "text/event-stream"

    def test_no_bearer_authorization(self):
        provider = AzureOpenAIProvider(
            api_key="az-secret",
            model="m",
            endpoint="https://x.openai.azure.com",
            api_version="2024-02-01",
        )
        headers = provider._build_headers()
        assert "Authorization" not in headers


# ---------------------------------------------------------------------------
# _build_payload (inherited from OpenAIProvider)
# ---------------------------------------------------------------------------


class TestBuildPayload:
    def test_payload_uses_model(self):
        provider = AzureOpenAIProvider(
            api_key="k", model="gpt-4o",
            endpoint="https://x.openai.azure.com",
            api_version="2024-02-01",
        )
        payload = provider._build_payload(
            messages=[{"role": "user", "content": "hi"}],
            tools=None,
            temperature=0.5,
        )
        assert payload["model"] == "gpt-4o"
        assert payload["stream"] is True
        assert payload["temperature"] == 0.5

    def test_payload_with_tools(self):
        provider = AzureOpenAIProvider(
            api_key="k", model="gpt-4o",
            endpoint="https://x.openai.azure.com",
            api_version="2024-02-01",
        )
        tools = [{"name": "my_tool", "description": "desc", "parameters": {}}]
        payload = provider._build_payload(
            messages=[{"role": "user", "content": "hi"}],
            tools=tools,
            temperature=0.1,
        )
        assert len(payload["tools"]) == 1
        assert payload["tools"][0]["type"] == "function"


# ---------------------------------------------------------------------------
# Streaming flow (reuses OpenAI SSE format)
# ---------------------------------------------------------------------------


class TestStreamingFlow:
    @pytest.mark.asyncio
    async def test_text_stream(self):
        lines = [
            _sse_line(_text_chunk("Hello ")),
            _sse_line(_text_chunk("Azure")),
            "data: [DONE]",
        ]
        fake_resp = _FakeStreamResponse(lines)
        fake_client = _FakeAsyncClient(fake_resp)

        provider = AzureOpenAIProvider(
            api_key="k", model="gpt-4o",
            endpoint="https://myresource.openai.azure.com",
            api_version="2024-02-01",
        )
        with patch("quantgambit.copilot.providers.openai.httpx.AsyncClient", return_value=fake_client):
            chunks = [c async for c in provider.chat_completion_stream(
                [{"role": "user", "content": "hi"}]
            )]

        text_chunks = [c for c in chunks if c.type == "text_delta"]
        assert len(text_chunks) == 2
        assert text_chunks[0].content == "Hello "
        assert text_chunks[1].content == "Azure"
        assert chunks[-1].type == "done"

    @pytest.mark.asyncio
    async def test_tool_call_stream(self):
        lines = [
            _sse_line(_tool_call_chunk(index=0, tc_id="call_1", name="query_trades", arguments='{"sym')),
            _sse_line(_tool_call_chunk(index=0, arguments='bol": "ETH"}')),
            _sse_line(_finish_chunk("tool_calls")),
            "data: [DONE]",
        ]
        fake_resp = _FakeStreamResponse(lines)
        fake_client = _FakeAsyncClient(fake_resp)

        provider = AzureOpenAIProvider(
            api_key="k", model="gpt-4o",
            endpoint="https://myresource.openai.azure.com",
            api_version="2024-02-01",
        )
        with patch("quantgambit.copilot.providers.openai.httpx.AsyncClient", return_value=fake_client):
            chunks = [c async for c in provider.chat_completion_stream(
                [{"role": "user", "content": "hi"}]
            )]

        types = [c.type for c in chunks]
        assert "tool_call_start" in types
        assert "tool_call_delta" in types
        assert "tool_call_end" in types
        assert types[-1] == "done"

        end_chunk = [c for c in chunks if c.type == "tool_call_end"][0]
        assert end_chunk.tool_name == "query_trades"
        assert json.loads(end_chunk.tool_arguments) == {"symbol": "ETH"}

    @pytest.mark.asyncio
    async def test_uses_azure_url(self):
        """Verify the provider hits the Azure deployment URL, not the OpenAI URL."""
        lines = [
            _sse_line(_text_chunk("ok")),
            "data: [DONE]",
        ]
        fake_resp = _FakeStreamResponse(lines)
        fake_client = _FakeAsyncClient(fake_resp)

        provider = AzureOpenAIProvider(
            api_key="k", model="gpt-4o",
            endpoint="https://myresource.openai.azure.com",
            api_version="2024-02-01",
        )
        with patch("quantgambit.copilot.providers.openai.httpx.AsyncClient", return_value=fake_client):
            _ = [c async for c in provider.chat_completion_stream(
                [{"role": "user", "content": "hi"}]
            )]

        assert fake_client.last_url == (
            "https://myresource.openai.azure.com/openai/deployments/gpt-4o"
            "/chat/completions?api-version=2024-02-01"
        )

    @pytest.mark.asyncio
    async def test_uses_api_key_header_in_request(self):
        """Verify the provider sends api-key header, not Bearer token."""
        lines = [
            _sse_line(_text_chunk("ok")),
            "data: [DONE]",
        ]
        fake_resp = _FakeStreamResponse(lines)
        fake_client = _FakeAsyncClient(fake_resp)

        provider = AzureOpenAIProvider(
            api_key="az-secret-key", model="gpt-4o",
            endpoint="https://myresource.openai.azure.com",
            api_version="2024-02-01",
        )
        with patch("quantgambit.copilot.providers.openai.httpx.AsyncClient", return_value=fake_client):
            _ = [c async for c in provider.chat_completion_stream(
                [{"role": "user", "content": "hi"}]
            )]

        assert fake_client.last_headers["api-key"] == "az-secret-key"
        assert "Authorization" not in fake_client.last_headers


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

        provider = AzureOpenAIProvider(
            api_key="k", model="m",
            endpoint="https://x.openai.azure.com",
            api_version="2024-02-01",
        )
        with patch("quantgambit.copilot.providers.azure_openai.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            with patch("quantgambit.copilot.providers.openai.httpx.AsyncClient", return_value=_FailingOuter()):
                chunks = [c async for c in provider.chat_completion_stream(
                    [{"role": "user", "content": "hi"}]
                )]

        assert chunks[-1].type == "done"
        assert mock_sleep.call_count == 2

    @pytest.mark.asyncio
    async def test_succeeds_on_second_attempt(self):
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

        provider = AzureOpenAIProvider(
            api_key="k", model="m",
            endpoint="https://x.openai.azure.com",
            api_version="2024-02-01",
        )
        with patch("quantgambit.copilot.providers.azure_openai.asyncio.sleep", new_callable=AsyncMock):
            with patch("quantgambit.copilot.providers.openai.httpx.AsyncClient", return_value=_RetryOuter()):
                chunks = [c async for c in provider.chat_completion_stream(
                    [{"role": "user", "content": "hi"}]
                )]

        text_chunks = [c for c in chunks if c.type == "text_delta"]
        assert len(text_chunks) == 1
        assert text_chunks[0].content == "recovered"
