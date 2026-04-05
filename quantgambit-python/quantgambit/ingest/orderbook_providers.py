"""Orderbook feed providers."""

from __future__ import annotations

import asyncio
from typing import Optional


class QueueOrderbookProvider:
    """Consume orderbook updates from an asyncio.Queue."""

    def __init__(self, queue: asyncio.Queue):
        self.queue = queue

    async def next_update(self) -> Optional[dict]:
        try:
            return await self.queue.get()
        except Exception:
            return None


class StubOrderbookProvider:
    """Placeholder provider for integration with exchange SDKs."""

    async def next_update(self) -> Optional[dict]:
        return None
