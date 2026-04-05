"""
Bybit order book synchronization.

Bybit WebSocket book semantics:
- Snapshot: Full book with `u` (updateId)
- Delta: Incremental updates with `u` (updateId)
- updateId must increase monotonically
- Gap detection: if new_u > last_u + 1, resync needed
- Snapshot resets the sequence

References:
- https://bybit-exchange.github.io/docs/v5/websocket/public/orderbook
"""

from typing import Optional, Dict, Any, List

from quantgambit.core.book.types import OrderBook, Level, BookSide
from quantgambit.core.book.venue_sync import (
    VenueBookSync,
    BaseBookSync,
    BookCoherence,
    CoherenceStatus,
    SyncResult,
)


class BybitBookSync(BaseBookSync):
    """
    Bybit-specific order book synchronization.
    
    Bybit uses:
    - `u` field for updateId (sequence number)
    - `seq` field for cross-symbol sequence (optional)
    - Snapshot type: "snapshot"
    - Delta type: "delta"
    
    Sequence rules:
    - First message must be snapshot
    - Delta updateId must be exactly last_u + 1
    - Any gap triggers resync
    """
    
    def __init__(
        self,
        max_gap: int = 0,  # Bybit requires strict sequence (no gaps)
        max_stale_sec: float = 5.0,
    ):
        """
        Initialize Bybit book sync.
        
        Args:
            max_gap: Maximum allowed sequence gap (0 = strict)
            max_stale_sec: Maximum book age before stale
        """
        super().__init__(max_gap=max_gap, max_stale_sec=max_stale_sec)
        
        # Track if we've received initial snapshot
        self._has_snapshot: Dict[str, bool] = {}
    
    def on_snapshot(
        self,
        symbol: str,
        bids: List[List],
        asks: List[List],
        sequence: int,
        timestamp: float,
        raw_data: Optional[Dict[str, Any]] = None,
    ) -> SyncResult:
        """
        Process Bybit snapshot.
        
        Bybit snapshot format:
        {
            "topic": "orderbook.50.BTCUSDT",
            "type": "snapshot",
            "ts": 1672304484978,
            "data": {
                "s": "BTCUSDT",
                "b": [["16879.50", "0.006"], ...],  # bids
                "a": [["16879.00", "0.060"], ...],  # asks
                "u": 18521288,
                "seq": 7961638724
            }
        }
        """
        # Mark that we have a snapshot
        self._has_snapshot[symbol] = True
        
        # Use base implementation
        result = super().on_snapshot(symbol, bids, asks, sequence, timestamp, raw_data)
        
        return result
    
    def on_delta(
        self,
        symbol: str,
        bids: List[List],
        asks: List[List],
        sequence: int,
        timestamp: float,
        raw_data: Optional[Dict[str, Any]] = None,
    ) -> SyncResult:
        """
        Process Bybit delta.
        
        Bybit delta format:
        {
            "topic": "orderbook.50.BTCUSDT",
            "type": "delta",
            "ts": 1672304484978,
            "data": {
                "s": "BTCUSDT",
                "b": [["16879.50", "0.006"], ...],  # bid changes
                "a": [["16879.00", "0.060"], ...],  # ask changes
                "u": 18521289,
                "seq": 7961638725
            }
        }
        """
        # Check if we have a snapshot first
        if not self._has_snapshot.get(symbol, False):
            return SyncResult(
                book=None,
                coherence=BookCoherence.incoherent(
                    CoherenceStatus.NO_SNAPSHOT,
                    "No snapshot received yet for Bybit",
                    sequence=sequence,
                ),
                resync_requested=True,
            )
        
        # Use base implementation with strict sequence checking
        return super().on_delta(symbol, bids, asks, sequence, timestamp, raw_data)
    
    def _check_sequence(
        self,
        symbol: str,
        last_seq: int,
        new_seq: int,
    ) -> BookCoherence:
        """
        Bybit-specific sequence validation.
        
        Bybit requires strict sequence: new_u == last_u + 1
        """
        # First delta after snapshot
        if last_seq == 0:
            return BookCoherence.coherent(new_seq, 0)
        
        # Check for exact sequence
        expected = last_seq + 1
        
        if new_seq < expected:
            # Duplicate or old message - safe to ignore
            return BookCoherence.coherent(last_seq, 0)
        
        if new_seq > expected:
            # Gap detected - need resync
            gap = new_seq - last_seq
            self._gap_counts[symbol] = self._gap_counts.get(symbol, 0) + 1
            return BookCoherence.incoherent(
                CoherenceStatus.SEQUENCE_GAP,
                f"Bybit sequence gap: expected {expected}, got {new_seq} (gap={gap})",
                sequence=new_seq,
                gap_count=self._gap_counts[symbol],
            )
        
        # Exact match - all good
        return BookCoherence.coherent(new_seq, 0)
    
    def reset(self, symbol: str) -> None:
        """Reset state for symbol."""
        super().reset(symbol)
        self._has_snapshot.pop(symbol, None)
    
    def needs_resync(self, symbol: str) -> bool:
        """Check if resync needed."""
        # Need resync if no snapshot or explicitly requested
        if not self._has_snapshot.get(symbol, False):
            return True
        return super().needs_resync(symbol)
    
    @staticmethod
    def parse_message(raw: Dict[str, Any]) -> tuple[str, str, List, List, int, float]:
        """
        Parse raw Bybit WebSocket message.
        
        Args:
            raw: Raw WebSocket message
            
        Returns:
            Tuple of (symbol, msg_type, bids, asks, sequence, timestamp)
        """
        data = raw.get("data", {})
        
        symbol = data.get("s", "")
        msg_type = raw.get("type", "")  # "snapshot" or "delta"
        bids = data.get("b", [])
        asks = data.get("a", [])
        sequence = data.get("u", 0)
        timestamp = raw.get("ts", 0) / 1000  # Convert ms to seconds
        
        return (symbol, msg_type, bids, asks, sequence, timestamp)
    
    def process_message(self, raw: Dict[str, Any]) -> Optional[SyncResult]:
        """
        Process a raw Bybit WebSocket message.
        
        Convenience method that parses and routes to appropriate handler.
        
        Args:
            raw: Raw WebSocket message
            
        Returns:
            SyncResult, or None if message type not recognized
        """
        symbol, msg_type, bids, asks, sequence, timestamp = self.parse_message(raw)
        
        if not symbol:
            return None
        
        if msg_type == "snapshot":
            return self.on_snapshot(symbol, bids, asks, sequence, timestamp, raw)
        elif msg_type == "delta":
            return self.on_delta(symbol, bids, asks, sequence, timestamp, raw)
        
        return None
