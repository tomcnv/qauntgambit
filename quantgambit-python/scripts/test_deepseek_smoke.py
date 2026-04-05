#!/usr/bin/env python3
"""Smoke test: verify DeepSeek R1 streams correctly through OpenAIProvider.

Usage:
    python scripts/test_deepseek_smoke.py

Reads COPILOT_LLM_* env vars from .env (via dotenv) and sends a simple
message to DeepSeek, printing each streamed chunk type + content.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

# Ensure the project root is on sys.path
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from quantgambit.config.env_loading import apply_layered_env_defaults

loaded_paths = apply_layered_env_defaults(project_root, os.environ.get("ENV_FILE"), os.environ)
if loaded_paths:
    print("✅ Loaded environment defaults from " + ", ".join(str(path) for path in loaded_paths))
else:
    print("⚠️  No env file found, using existing env vars")

from quantgambit.copilot.providers.openai import OpenAIProvider


async def main() -> int:
    api_key = os.environ.get("COPILOT_LLM_API_KEY", "")
    model = os.environ.get("COPILOT_LLM_MODEL", "")
    base_url = os.environ.get("COPILOT_LLM_BASE_URL", "")
    provider_name = os.environ.get("COPILOT_LLM_PROVIDER", "")

    print(f"\nProvider:  {provider_name}")
    print(f"Model:     {model}")
    print(f"Base URL:  {base_url}")
    print(f"API Key:   {'***' + api_key[-4:] if len(api_key) > 4 else '(not set)'}")
    print()

    if not api_key or not model or not base_url:
        print("❌ Missing COPILOT_LLM_API_KEY, COPILOT_LLM_MODEL, or COPILOT_LLM_BASE_URL")
        return 1

    provider = OpenAIProvider(api_key=api_key, model=model, base_url=base_url)

    messages = [
        {"role": "system", "content": "You are a helpful trading assistant. Be concise."},
        {"role": "user", "content": "What is a stop-loss order? Answer in one sentence."},
    ]

    print("=" * 60)
    print("Sending test message to DeepSeek R1...")
    print("=" * 60)

    chunk_count = 0
    text_chunks = []
    chunk_types: dict[str, int] = {}

    try:
        async for chunk in provider.chat_completion_stream(messages=messages, tools=None):
            chunk_types[chunk.type] = chunk_types.get(chunk.type, 0) + 1
            chunk_count += 1

            if chunk.type == "text_delta" and chunk.content:
                text_chunks.append(chunk.content)
                print(chunk.content, end="", flush=True)
            elif chunk.type == "done":
                break
    except Exception as exc:
        print(f"\n\n❌ Error during streaming: {exc}")
        return 1

    full_response = "".join(text_chunks)
    print("\n")
    print("=" * 60)
    print(f"Total chunks received: {chunk_count}")
    print(f"Chunk types: {chunk_types}")
    print(f"Response length: {len(full_response)} chars")
    print("=" * 60)

    if full_response.strip():
        print("\n✅ DeepSeek R1 is working! Streaming parsed correctly.")
        return 0
    else:
        print("\n❌ No text content received. Check API key and model name.")
        return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
