"""Orderbook state and delta application."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List


@dataclass
class OrderbookState:
    symbol: str
    bids: Dict[float, float] = field(default_factory=dict)
    asks: Dict[float, float] = field(default_factory=dict)
    seq: int = 0
    valid: bool = False

    def apply_snapshot(self, bids: List[list], asks: List[list], seq: int) -> None:
        self.bids = {float(p): float(s) for p, s in bids if s > 0}
        self.asks = {float(p): float(s) for p, s in asks if s > 0}
        self.seq = seq
        self.valid = True

    def apply_delta(self, bids: List[list], asks: List[list], seq: int) -> None:
        for price, size in bids:
            price = float(price)
            size = float(size)
            if size <= 0:
                self.bids.pop(price, None)
            else:
                self.bids[price] = size
        for price, size in asks:
            price = float(price)
            size = float(size)
            if size <= 0:
                self.asks.pop(price, None)
            else:
                self.asks[price] = size
        self.seq = seq

    def as_levels(self, depth: int = 20) -> tuple[List[list], List[list]]:
        bids = sorted(self.bids.items(), key=lambda x: x[0], reverse=True)[:depth]
        asks = sorted(self.asks.items(), key=lambda x: x[0])[:depth]
        return [[p, s] for p, s in bids], [[p, s] for p, s in asks]
