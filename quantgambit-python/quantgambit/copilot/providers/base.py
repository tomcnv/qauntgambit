"""Base class for LLM providers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from quantgambit.copilot.models import LLMChunk


class ModelProvider(ABC):
    """Common interface all LLM providers implement."""

    @abstractmethod
    async def chat_completion_stream(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        temperature: float = 0.1,
    ) -> AsyncIterator[LLMChunk]:
        """Stream chat completion with optional tool calling.

        Yields normalized LLMChunk objects regardless of provider.
        """
        ...
