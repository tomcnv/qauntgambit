"""Anthropic Claude LLM provider using httpx async streaming."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator

import httpx

from quantgambit.copilot.models import LLMChunk
from quantgambit.copilot.providers.base import ModelProvider

logger = logging.getLogger(__name__)

_API_URL = "https://api.anthropic.com/v1/messages"
_ANTHROPIC_VERSION = "2023-06-01"
_MAX_RETRIES = 3
_INITIAL_BACKOFF_S = 1.0


class AnthropicProvider(ModelProvider):
    """Anthropic Claude API provider."""

    def __init__(self, api_key: str, model: str) -> None:
        self._api_key = api_key
        self._model = model

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def chat_completion_stream(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        temperature: float = 0.1,
    ) -> AsyncIterator[LLMChunk]:
        """Stream chat completion, yielding normalised LLMChunk objects.

        Retries up to 3 times on connection errors with exponential backoff.
        """
        system_prompt, api_messages = self._convert_messages(messages)
        payload = self._build_payload(api_messages, system_prompt, tools, temperature)
        headers = self._build_headers()

        last_exc: Exception | None = None
        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                async for chunk in self._stream_request(_API_URL, headers, payload):
                    yield chunk
                return
            except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
                last_exc = exc
                if attempt < _MAX_RETRIES:
                    wait = _INITIAL_BACKOFF_S * (2 ** (attempt - 1))
                    logger.warning(
                        "Anthropic connection error (attempt %d/%d), retrying in %.1fs: %s",
                        attempt,
                        _MAX_RETRIES,
                        wait,
                        exc,
                    )
                    await asyncio.sleep(wait)

        logger.error("Anthropic connection failed after %d attempts: %s", _MAX_RETRIES, last_exc)
        yield LLMChunk(type="done")

    # ------------------------------------------------------------------
    # Message conversion
    # ------------------------------------------------------------------

    @staticmethod
    def _convert_messages(
        messages: list[dict],
    ) -> tuple[str | None, list[dict]]:
        """Convert OpenAI-style messages to Anthropic format.

        Extracts the system message (if any) and returns it separately,
        since Anthropic uses a top-level ``system`` field rather than a
        system role in the messages array.

        Tool result messages (role="tool") are converted to Anthropic's
        ``tool_result`` content blocks within a ``user`` role message.
        """
        system_prompt: str | None = None
        api_messages: list[dict] = []

        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "")

            if role == "system":
                system_prompt = content
            elif role == "assistant":
                # Check if the assistant message contains tool_calls
                tool_calls = msg.get("tool_calls")
                if tool_calls:
                    blocks: list[dict] = []
                    if content:
                        blocks.append({"type": "text", "text": content})
                    for tc in tool_calls:
                        fn = tc.get("function", {})
                        try:
                            input_data = json.loads(fn.get("arguments", "{}"))
                        except (json.JSONDecodeError, TypeError):
                            input_data = {}
                        blocks.append({
                            "type": "tool_use",
                            "id": tc.get("id", ""),
                            "name": fn.get("name", ""),
                            "input": input_data,
                        })
                    api_messages.append({"role": "assistant", "content": blocks})
                else:
                    api_messages.append({"role": "assistant", "content": content})
            elif role == "tool":
                # Anthropic expects tool results as user messages with
                # tool_result content blocks.
                tool_call_id = msg.get("tool_call_id", "")
                api_messages.append({
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": tool_call_id,
                            "content": content,
                        }
                    ],
                })
            else:
                # user messages
                api_messages.append({"role": "user", "content": content})

        return system_prompt, api_messages

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_headers(self) -> dict[str, str]:
        return {
            "x-api-key": self._api_key,
            "anthropic-version": _ANTHROPIC_VERSION,
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }

    def _build_payload(
        self,
        messages: list[dict],
        system_prompt: str | None,
        tools: list[dict] | None,
        temperature: float,
    ) -> dict:
        payload: dict = {
            "model": self._model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": 4096,
            "stream": True,
        }
        if system_prompt:
            payload["system"] = system_prompt
        if tools:
            payload["tools"] = [
                {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "input_schema": t.get("parameters", {}),
                }
                for t in tools
            ]
        return payload

    async def _stream_request(
        self,
        url: str,
        headers: dict[str, str],
        payload: dict,
    ) -> AsyncIterator[LLMChunk]:
        """Open an SSE stream and yield normalised LLMChunk objects."""
        active_blocks: dict[int, dict] = {}

        async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0)) as client:
            async with client.stream("POST", url, headers=headers, json=payload) as response:
                response.raise_for_status()
                event_type: str | None = None
                async for line in response.aiter_lines():
                    line = line.strip()
                    if not line:
                        event_type = None
                        continue
                    if line.startswith("event:"):
                        event_type = line[len("event:"):].strip()
                        continue
                    if not line.startswith("data:"):
                        continue

                    data_str = line[len("data:"):].strip()
                    try:
                        data = json.loads(data_str)
                    except json.JSONDecodeError:
                        logger.warning("Skipping malformed SSE data: %s", data_str[:200])
                        continue

                    for chunk in self._parse_event(event_type, data, active_blocks):
                        yield chunk

        yield LLMChunk(type="done")

    # ------------------------------------------------------------------
    # SSE event parsing
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_event(
        event_type: str | None,
        data: dict,
        active_blocks: dict[int, dict],
    ) -> list[LLMChunk]:
        """Parse a single Anthropic SSE event into zero or more LLMChunk objects.

        Anthropic SSE event types:
        - message_start: contains message metadata
        - content_block_start: new content block (text or tool_use)
        - content_block_delta: incremental content update
        - content_block_stop: content block finished
        - message_delta: message-level updates (stop_reason)
        - message_stop: stream complete
        """
        chunks: list[LLMChunk] = []

        if event_type == "content_block_start":
            index = data.get("index", 0)
            block = data.get("content_block", {})
            block_type = block.get("type", "")

            if block_type == "tool_use":
                tool_id = block.get("id", "")
                tool_name = block.get("name", "")
                active_blocks[index] = {
                    "type": "tool_use",
                    "id": tool_id,
                    "name": tool_name,
                    "arguments": "",
                }
                chunks.append(
                    LLMChunk(
                        type="tool_call_start",
                        tool_call_id=tool_id,
                        tool_name=tool_name,
                        tool_arguments="",
                    )
                )
            elif block_type == "text":
                active_blocks[index] = {"type": "text"}

        elif event_type == "content_block_delta":
            index = data.get("index", 0)
            delta = data.get("delta", {})
            delta_type = delta.get("type", "")

            if delta_type == "text_delta":
                text = delta.get("text", "")
                if text:
                    chunks.append(LLMChunk(type="text_delta", content=text))

            elif delta_type == "input_json_delta":
                partial_json = delta.get("partial_json", "")
                block_info = active_blocks.get(index)
                if block_info and block_info["type"] == "tool_use":
                    block_info["arguments"] += partial_json
                    chunks.append(
                        LLMChunk(
                            type="tool_call_delta",
                            tool_call_id=block_info["id"],
                            tool_name=block_info["name"],
                            tool_arguments=partial_json,
                        )
                    )

        elif event_type == "content_block_stop":
            index = data.get("index", 0)
            block_info = active_blocks.pop(index, None)
            if block_info and block_info["type"] == "tool_use":
                chunks.append(
                    LLMChunk(
                        type="tool_call_end",
                        tool_call_id=block_info["id"],
                        tool_name=block_info["name"],
                        tool_arguments=block_info["arguments"],
                    )
                )

        # message_start, message_delta, message_stop are ignored for
        # LLMChunk purposes (no content to emit).

        return chunks
