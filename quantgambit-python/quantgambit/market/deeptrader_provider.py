"""Market data provider adapter for deeptrader websocket sources."""

from __future__ import annotations

import asyncio
from typing import Optional

from quantgambit.market.updater import MarketDataProvider
from quantgambit.market.ticks import normalize_tick


class DeepTraderMarketDataProvider(MarketDataProvider):
    """Consumes ticks from a deeptrader event queue."""

    def __init__(self, queue: asyncio.Queue):
        self.queue = queue

    async def next_tick(self) -> Optional[dict]:
        try:
            raw = await self.queue.get()
            return normalize_tick(raw)
        except asyncio.CancelledError:
            return None
