"""Reference price cache for slippage calculations."""

from __future__ import annotations

import time
from typing import Dict, Optional, Tuple

from quantgambit.execution.adapters import ReferencePriceProvider


class ReferencePriceCache(ReferencePriceProvider):
    """In-memory reference price provider with exchange timestamp tracking."""

    def __init__(self):
        self._prices: Dict[str, float] = {}
        self._price_ts: Dict[str, float] = {}
        self._orderbooks: Dict[str, dict] = {}
        self._orderbook_ts: Dict[str, float] = {}
        # Exchange matching engine timestamps (cts) for latency measurement
        self._orderbook_cts_ms: Dict[str, int] = {}  # Orderbook cts from exchange
        self._orderbook_recv_ms: Dict[str, float] = {}  # When we received the update
        self._trade_ts_ms: Dict[str, int] = {}  # Trade T from exchange
        self._trade_recv_ms: Dict[str, float] = {}  # When we received the trade

    def update(self, symbol: str, price: float, timestamp: Optional[float] = None) -> None:
        self._prices[symbol] = price
        if timestamp is not None:
            self._price_ts[symbol] = float(timestamp)

    def update_orderbook(
        self, 
        symbol: str, 
        bids: list, 
        asks: list, 
        timestamp: Optional[float] = None,
        cts_ms: Optional[int] = None,
    ) -> None:
        self._orderbooks[symbol] = {"bids": bids, "asks": asks}
        now_ms = time.time() * 1000
        self._orderbook_recv_ms[symbol] = now_ms
        if timestamp is not None:
            self._orderbook_ts[symbol] = float(timestamp)
        if cts_ms is not None:
            self._orderbook_cts_ms[symbol] = cts_ms
    
    def update_trade_timestamp(self, symbol: str, trade_ts_ms: int) -> None:
        """Update the latest trade timestamp from exchange."""
        now_ms = time.time() * 1000
        self._trade_recv_ms[symbol] = now_ms
        # Keep max trade timestamp (trades can batch)
        existing = self._trade_ts_ms.get(symbol)
        if existing is None or trade_ts_ms > existing:
            self._trade_ts_ms[symbol] = trade_ts_ms
    
    def get_latency_data(self, symbol: str) -> dict:
        """Get latency data for DataReadinessGate."""
        return {
            "book_cts_ms": self._orderbook_cts_ms.get(symbol),
            "book_recv_ms": self._orderbook_recv_ms.get(symbol),
            "trade_ts_ms": self._trade_ts_ms.get(symbol),
            "trade_recv_ms": self._trade_recv_ms.get(symbol),
        }

    def clear_orderbook(self, symbol: str) -> None:
        self._orderbooks.pop(symbol, None)
        self._orderbook_ts.pop(symbol, None)

    def get_reference_price(self, symbol: str) -> Optional[float]:
        return self._prices.get(symbol)

    def get_reference_price_with_ts(self, symbol: str) -> Optional[Tuple[float, float]]:
        price = self._prices.get(symbol)
        ts = self._price_ts.get(symbol)
        if price is None or ts is None:
            return None
        return price, ts

    def get_orderbook_with_ts(self, symbol: str) -> Optional[Tuple[dict, float]]:
        book = self._orderbooks.get(symbol)
        ts = self._orderbook_ts.get(symbol)
        if book is None or ts is None:
            return None
        return book, ts

    def get_orderbook(self, symbol: str) -> Optional[dict]:
        return self._orderbooks.get(symbol)
