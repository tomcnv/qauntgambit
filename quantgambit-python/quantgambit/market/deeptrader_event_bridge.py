"""Bridge deeptrader EventBus events into a tick queue."""

from __future__ import annotations

import asyncio
from typing import Any


class DeepTraderEventBridge:
    """Subscribes to deeptrader EventBus and forwards ticks to a queue."""

    def __init__(self, event_bus: Any, queue: asyncio.Queue):
        self.event_bus = event_bus
        self.queue = queue

    def attach(self) -> None:
        from fast_scalper.event_bus import EventType  # type: ignore

        self.event_bus.subscribe(EventType.ORDERBOOK_UPDATE, self._on_orderbook)
        self.event_bus.subscribe(EventType.TRADE, self._on_trade)

    async def _on_orderbook(self, event) -> None:
        data = getattr(event, "data", None)
        if not data:
            return
        bids = getattr(data, "bids", []) or []
        asks = getattr(data, "asks", []) or []
        bid = bids[0][0] if bids else None
        ask = asks[0][0] if asks else None
        await self.queue.put({
            "symbol": getattr(data, "symbol", None) or getattr(event, "symbol", None),
            "bid": bid,
            "ask": ask,
            "timestamp": getattr(data, "timestamp", None) or getattr(event, "timestamp", None),
        })

    async def _on_trade(self, event) -> None:
        data = getattr(event, "data", None)
        if not data:
            return
        await self.queue.put({
            "symbol": getattr(data, "symbol", None) or getattr(event, "symbol", None),
            "last": getattr(data, "price", None),
            "timestamp": getattr(data, "timestamp", None) or getattr(event, "timestamp", None),
        })

