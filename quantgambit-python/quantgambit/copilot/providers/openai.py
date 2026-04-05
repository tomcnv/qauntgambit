"""OpenAI and OpenAI-compatible LLM provider using httpx async streaming."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator

import httpx

from quantgambit.copilot.models import LLMChunk
from quantgambit.copilot.providers.base import ModelProvider

logger = logging.getLogger(__name__)

_DEFAULT_BASE_URL = "https://api.openai.com/v1"
_MAX_RETRIES = 3
_INITIAL_BACKOFF_S = 1.0


class OpenAIProvider(ModelProvider):
    """OpenAI and OpenAI-compatible endpoints (including local models)."""

    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str | None = None,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._base_url = (base_url or _DEFAULT_BASE_URL).rstrip("/")

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
        payload = self._build_payload(messages, tools, temperature)
        headers = self._build_headers()
        url = f"{self._base_url}/chat/completions"

        last_exc: Exception | None = None
        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                async for chunk in self._stream_request(url, headers, payload):
                    yield chunk
                return  # success – exit retry loop
            except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
                last_exc = exc
                if attempt < _MAX_RETRIES:
                    wait = _INITIAL_BACKOFF_S * (2 ** (attempt - 1))
                    logger.warning(
                        "OpenAI connection error (attempt %d/%d), retrying in %.1fs: %s",
                        attempt,
                        _MAX_RETRIES,
                        wait,
                        exc,
                    )
                    await asyncio.sleep(wait)

        # All retries exhausted
        logger.error("OpenAI connection failed after %d attempts: %s", _MAX_RETRIES, last_exc)
        yield LLMChunk(type="done")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }

    def _build_payload(
        self,
        messages: list[dict],
        tools: list[dict] | None,
        temperature: float,
    ) -> dict:
        payload: dict = {
            "model": self._model,
            "messages": messages,
            "temperature": temperature,
            "stream": True,
        }
        if tools:
            payload["tools"] = [
                t if "type" in t else {"type": "function", "function": t}
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
        # Track in-progress tool calls keyed by index
        active_tool_calls: dict[int, dict] = {}
        chunk_count = 0
        finish_reason_seen = None

        # Log the request details for debugging
        msg_count = len(payload.get("messages", []))
        has_tools = bool(payload.get("tools"))
        last_role = payload["messages"][-1]["role"] if payload.get("messages") else "none"
        logger.info(
            "LLM request: model=%s msg_count=%d has_tools=%s last_msg_role=%s",
            payload.get("model"), msg_count, has_tools, last_role,
        )

        async with httpx.AsyncClient(timeout=httpx.Timeout(180.0, connect=10.0)) as client:
            async with client.stream("POST", url, headers=headers, json=payload) as response:
                if response.status_code >= 400:
                    body = await response.aread()
                    body_text = body.decode(errors="replace")[:500]
                    logger.error(
                        "LLM API error %d for %s: %s",
                        response.status_code,
                        url,
                        body_text,
                    )
                    # Yield an error text chunk so the user sees something
                    # instead of a silent failure, then yield done.
                    yield LLMChunk(
                        type="text_delta",
                        content=(
                            "\n\nI encountered an issue communicating with the AI service "
                            f"(HTTP {response.status_code}). Let me try a different approach — "
                            "could you rephrase your question?"
                        ),
                    )
                    yield LLMChunk(type="done")
                    return
                async for line in response.aiter_lines():
                    line = line.strip()
                    if not line or not line.startswith("data:"):
                        continue
                    data_str = line[len("data:"):].strip()
                    if data_str == "[DONE]":
                        break

                    try:
                        data = json.loads(data_str)
                    except json.JSONDecodeError:
                        logger.warning("Skipping malformed SSE data: %s", data_str[:200])
                        continue

                    # Track finish_reason for logging
                    choices = data.get("choices", [])
                    if choices:
                        fr = choices[0].get("finish_reason")
                        if fr:
                            finish_reason_seen = fr

                    for chunk in self._parse_chunk(data, active_tool_calls):
                        chunk_count += 1
                        yield chunk

        logger.info(
            "LLM stream completed: chunks=%d finish_reason=%s model=%s",
            chunk_count, finish_reason_seen, self._model,
        )

        # Safety: if tool calls were started but never ended (e.g. stream
        # closed without a finish_reason), emit end events now.
        if active_tool_calls:
            logger.warning(
                "Stream ended with %d unclosed tool calls — emitting end events",
                len(active_tool_calls),
            )
            for idx, tc_info in active_tool_calls.items():
                yield LLMChunk(
                    type="tool_call_end",
                    tool_call_id=tc_info["id"],
                    tool_name=tc_info["name"],
                    tool_arguments=tc_info["arguments"],
                )
            active_tool_calls.clear()

        # Emit done sentinel
        yield LLMChunk(type="done")

    # ------------------------------------------------------------------
    # SSE chunk parsing
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_chunk(
        data: dict,
        active_tool_calls: dict[int, dict],
    ) -> list[LLMChunk]:
        """Parse a single SSE JSON object into zero or more LLMChunk objects."""
        chunks: list[LLMChunk] = []
        choices = data.get("choices", [])
        if not choices:
            return chunks

        delta = choices[0].get("delta", {})

        # --- Text content ---
        content = delta.get("content")
        if content:
            chunks.append(LLMChunk(type="text_delta", content=content))

        # --- Tool calls (streamed incrementally) ---
        tool_calls = delta.get("tool_calls")
        if tool_calls:
            for tc in tool_calls:
                idx = tc.get("index", 0)
                tc_id = tc.get("id")
                fn = tc.get("function", {})
                fn_name = fn.get("name")
                fn_args = fn.get("arguments", "")

                if idx not in active_tool_calls:
                    # First chunk for this tool call
                    active_tool_calls[idx] = {
                        "id": tc_id or "",
                        "name": fn_name or "",
                        "arguments": fn_args,
                    }
                    chunks.append(
                        LLMChunk(
                            type="tool_call_start",
                            tool_call_id=tc_id or "",
                            tool_name=fn_name or "",
                            tool_arguments=fn_args,
                        )
                    )
                else:
                    # Subsequent argument fragment
                    active_tool_calls[idx]["arguments"] += fn_args
                    chunks.append(
                        LLMChunk(
                            type="tool_call_delta",
                            tool_call_id=active_tool_calls[idx]["id"],
                            tool_name=active_tool_calls[idx]["name"],
                            tool_arguments=fn_args,
                        )
                    )

        # --- Finish reason signals tool call end ---
        finish_reason = choices[0].get("finish_reason")
        if finish_reason and active_tool_calls:
            # Emit tool_call_end for all active tool calls.
            # DeepSeek may use "stop" instead of "tool_calls" as finish_reason,
            # so we emit end events for ANY finish_reason when tool calls exist.
            for idx, tc_info in active_tool_calls.items():
                chunks.append(
                    LLMChunk(
                        type="tool_call_end",
                        tool_call_id=tc_info["id"],
                        tool_name=tc_info["name"],
                        tool_arguments=tc_info["arguments"],
                    )
                )
            active_tool_calls.clear()

        return chunks
