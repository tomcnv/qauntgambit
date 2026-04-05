"""Azure OpenAI Service LLM provider.

Reuses OpenAI streaming normalisation since Azure uses the same SSE format.
The key differences are:
- URL: ``{endpoint}/openai/deployments/{model}/chat/completions?api-version={api_version}``
- Auth header: ``api-key`` instead of ``Authorization: Bearer``
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator

import httpx

from quantgambit.copilot.models import LLMChunk
from quantgambit.copilot.providers.openai import OpenAIProvider

logger = logging.getLogger(__name__)

_MAX_RETRIES = 3
_INITIAL_BACKOFF_S = 1.0


class AzureOpenAIProvider(OpenAIProvider):
    """Azure OpenAI Service provider.

    Inherits streaming and chunk-parsing logic from :class:`OpenAIProvider`.
    Overrides URL construction and authentication headers for the Azure API.
    """

    def __init__(
        self,
        api_key: str,
        model: str,
        endpoint: str,
        api_version: str,
    ) -> None:
        # Initialise the parent *without* setting base_url – we build our own URL.
        super().__init__(api_key=api_key, model=model)
        self._endpoint = endpoint.rstrip("/")
        self._api_version = api_version

    # ------------------------------------------------------------------
    # Overrides
    # ------------------------------------------------------------------

    def _build_headers(self) -> dict[str, str]:
        """Azure uses ``api-key`` header instead of Bearer token."""
        return {
            "api-key": self._api_key,
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }

    async def chat_completion_stream(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        temperature: float = 0.1,
    ) -> AsyncIterator[LLMChunk]:
        """Stream chat completion via Azure OpenAI.

        Uses the Azure deployment URL and ``api-key`` auth header.
        Retries up to 3 times on connection errors with exponential backoff.
        """
        payload = self._build_payload(messages, tools, temperature)
        headers = self._build_headers()
        url = self._build_url()

        last_exc: Exception | None = None
        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                async for chunk in self._stream_request(url, headers, payload):
                    yield chunk
                return
            except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
                last_exc = exc
                if attempt < _MAX_RETRIES:
                    wait = _INITIAL_BACKOFF_S * (2 ** (attempt - 1))
                    logger.warning(
                        "Azure OpenAI connection error (attempt %d/%d), retrying in %.1fs: %s",
                        attempt,
                        _MAX_RETRIES,
                        wait,
                        exc,
                    )
                    await asyncio.sleep(wait)

        logger.error("Azure OpenAI connection failed after %d attempts: %s", _MAX_RETRIES, last_exc)
        yield LLMChunk(type="done")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_url(self) -> str:
        """Build the Azure OpenAI deployment URL."""
        return (
            f"{self._endpoint}/openai/deployments/{self._model}"
            f"/chat/completions?api-version={self._api_version}"
        )
