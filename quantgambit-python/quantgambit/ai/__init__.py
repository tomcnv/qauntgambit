"""Lightweight LLM client for AI features. Uses DeepSeek via OpenAI-compatible API."""

from __future__ import annotations

import asyncio
import os
import httpx
import logging

logger = logging.getLogger(__name__)

_BASE_URL = os.getenv("COPILOT_LLM_BASE_URL", "https://api.deepseek.com/v1").rstrip("/")
_API_KEY = os.getenv("COPILOT_LLM_API_KEY", "")
_MODEL = os.getenv("COPILOT_LLM_MODEL", "deepseek-chat")
_TIMEOUT_SEC = float(os.getenv("COPILOT_LLM_TIMEOUT_SEC", "30"))


def _resolve_model(model: str | None = None) -> str:
    chosen = (model or _MODEL or "deepseek-chat").strip()
    return chosen or "deepseek-chat"


async def llm_complete(
    prompt: str,
    system: str = "",
    temperature: float = 0.3,
    max_tokens: int = 1024,
    *,
    model: str | None = None,
    timeout_sec: float | None = None,
) -> str:
    """Single-shot LLM completion. Returns text response."""
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    resolved_timeout = float(timeout_sec if timeout_sec is not None else _TIMEOUT_SEC)
    async with httpx.AsyncClient(timeout=resolved_timeout) as client:
        resp = await client.post(
            f"{_BASE_URL}/chat/completions",
            headers={"Authorization": f"Bearer {_API_KEY}", "Content-Type": "application/json"},
            json={
                "model": _resolve_model(model),
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            },
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]


def llm_complete_sync(
    prompt: str,
    system: str = "",
    temperature: float = 0.3,
    max_tokens: int = 1024,
    *,
    model: str | None = None,
    timeout_sec: float | None = None,
) -> str:
    """Sync wrapper for code paths that cannot await directly."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(
            llm_complete(
                prompt,
                system=system,
                temperature=temperature,
                max_tokens=max_tokens,
                model=model,
                timeout_sec=timeout_sec,
            )
        )

    resolved_timeout = float(timeout_sec if timeout_sec is not None else _TIMEOUT_SEC)
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    with httpx.Client(timeout=resolved_timeout) as client:
        resp = client.post(
            f"{_BASE_URL}/chat/completions",
            headers={"Authorization": f"Bearer {_API_KEY}", "Content-Type": "application/json"},
            json={
                "model": _resolve_model(model),
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            },
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]
