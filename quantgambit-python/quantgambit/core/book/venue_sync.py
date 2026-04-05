"""
Order book synchronization interface and base implementation.

Each exchange has different WebSocket book semantics:
- Sequence IDs and gap detection rules
- Snapshot vs delta handling
- Checksum verification
- Resync requirements

This module defines the VenueBookSync interface that abstracts these
differences, allowing the rest of the system to be exchange-agnostic.

Implementations go in io/adapters/{venue}/book_sync.py
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Optional, Dict, Any, List

from quantgambit.core.book.types import OrderBook, Level, BookSide


class CoherenceStatus(str, Enum):
    """Book coherence status."""
    
    COHERENT = "coherent"           # Book is valid and up-to-date
    STALE = "stale"                 # Book is too old
    SEQUENCE_GAP = "sequence_gap"   # Missing updates detected
    CHECKSUM_FAIL = "checksum_fail" # Checksum verification failed
    CROSSED = "crossed"             # Book is crossed (invalid)
    NO_SNAPSHOT = "no_snapshot"     # No snapshot received yet
    RESYNC_NEEDED = "resync_needed" # Explicit resync required


@dataclass
class BookCoherence:
    """
    Result of coherence check from VenueBookSync.
    
    Attributes:
        is_coherent: Whether the book is valid for trading
        status: Detailed status
        sequence: Current sequence/update ID
        timestamp: Exchange timestamp
        reason: Human-readable reason if not coherent
        gap_count: Number of sequence gaps detected (for metrics)
    """
    
    is_coherent: bool
    status: CoherenceStatus
    sequence: Optional[int] = None
    timestamp: Optional[float] = None
    reason: Optional[str] = None
    gap_count: int = 0
    
    @classmethod
    def coherent(cls, sequence: int, timestamp: float) -> "BookCoherence":
        """Create a coherent result."""
        return cls(
            is_coherent=True,
            status=CoherenceStatus.COHERENT,
            sequence=sequence,
            timestamp=timestamp,
        )
    
    @classmethod
    def incoherent(
        cls,
        status: CoherenceStatus,
        reason: str,
        sequence: Optional[int] = None,
        gap_count: int = 0,
    ) -> "BookCoherence":
        """Create an incoherent result."""
        return cls(
            is_coherent=False,
            status=status,
            sequence=sequence,
            reason=reason,
            gap_count=gap_count,
        )


@dataclass
class SyncResult:
    """
    Result of processing a book update.
    
    Attributes:
        book: Updated order book (or None if update failed)
        coherence: Coherence status after update
        resync_requested: Whether a resync should be triggered
    """
    
    book: Optional[OrderBook]
    coherence: BookCoherence
    resync_requested: bool = False


class VenueBookSync(ABC):
    """
    Abstract interface for venue-specific book synchronization.
    
    Each venue implementation handles:
    - Snapshot processing
    - Delta application with sequence validation
    - Coherence checking
    - Resync triggering
    
    The interface is pure - no I/O, just state management.
    """
    
    @abstractmethod
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
        Process a book snapshot.
        
        Args:
            symbol: Trading symbol
            bids: List of [price, size] or [price, size, count]
            asks: List of [price, size] or [price, size, count]
            sequence: Venue sequence/update ID
            timestamp: Exchange timestamp (epoch seconds)
            raw_data: Raw venue data for debugging
            
        Returns:
            SyncResult with updated book and coherence status
        """
        pass
    
    @abstractmethod
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
        Process a book delta update.
        
        Args:
            symbol: Trading symbol
            bids: List of [price, size] changes (size=0 means remove)
            asks: List of [price, size] changes
            sequence: Venue sequence/update ID
            timestamp: Exchange timestamp (epoch seconds)
            raw_data: Raw venue data for debugging
            
        Returns:
            SyncResult with updated book and coherence status
        """
        pass
    
    @abstractmethod
    def get_book(self, symbol: str) -> Optional[OrderBook]:
        """
        Get current book for a symbol.
        
        Returns None if no snapshot has been received.
        """
        pass
    
    @abstractmethod
    def get_coherence(self, symbol: str) -> BookCoherence:
        """
        Get current coherence status for a symbol.
        """
        pass
    
    @abstractmethod
    def needs_resync(self, symbol: str) -> bool:
        """
        Check if a symbol needs resync.
        """
        pass
    
    @abstractmethod
    def request_resync(self, symbol: str) -> None:
        """
        Mark a symbol as needing resync.
        
        This should be called when external factors indicate
        the book may be stale (e.g., WS reconnect).
        """
        pass
    
    @abstractmethod
    def clear_resync(self, symbol: str) -> None:
        """
        Clear resync flag after successful snapshot.
        """
        pass
    
    @abstractmethod
    def reset(self, symbol: str) -> None:
        """
        Reset all state for a symbol.
        
        Called on reconnect or when starting fresh.
        """
        pass
    
    @abstractmethod
    def stats(self) -> Dict[str, Any]:
        """
        Get sync statistics for monitoring.
        """
        pass


class BaseBookSync(VenueBookSync):
    """
    Base implementation with common functionality.
    
    Subclasses implement venue-specific sequence validation.
    """
    
    def __init__(self, max_gap: int = 1, max_stale_sec: float = 5.0):
        """
        Initialize base sync.
        
        Args:
            max_gap: Maximum allowed sequence gap before resync
            max_stale_sec: Maximum book age before considered stale
        """
        self._max_gap = max_gap
        self._max_stale_sec = max_stale_sec
        
        # Per-symbol state
        self._books: Dict[str, OrderBook] = {}
        self._last_sequence: Dict[str, int] = {}
        self._needs_resync: Dict[str, bool] = {}
        self._gap_counts: Dict[str, int] = {}
        self._snapshot_counts: Dict[str, int] = {}
        self._delta_counts: Dict[str, int] = {}
    
    def on_snapshot(
        self,
        symbol: str,
        bids: List[List],
        asks: List[List],
        sequence: int,
        timestamp: float,
        raw_data: Optional[Dict[str, Any]] = None,
    ) -> SyncResult:
        """Process snapshot - creates fresh book."""
        # Create new book
        book = OrderBook(
            symbol=symbol,
            bids=[Level.from_list(b) for b in bids],
            asks=[Level.from_list(a) for a in asks],
            update_id=sequence,
            timestamp=timestamp,
        )
        
        # Check for crossed book
        if book.is_crossed():
            return SyncResult(
                book=None,
                coherence=BookCoherence.incoherent(
                    CoherenceStatus.CROSSED,
                    f"Crossed book: bid={book.best_bid_price} >= ask={book.best_ask_price}",
                    sequence=sequence,
                ),
                resync_requested=True,
            )
        
        # Store book and sequence
        self._books[symbol] = book
        self._last_sequence[symbol] = sequence
        self._needs_resync[symbol] = False
        self._snapshot_counts[symbol] = self._snapshot_counts.get(symbol, 0) + 1
        
        return SyncResult(
            book=book,
            coherence=BookCoherence.coherent(sequence, timestamp),
        )
    
    def on_delta(
        self,
        symbol: str,
        bids: List[List],
        asks: List[List],
        sequence: int,
        timestamp: float,
        raw_data: Optional[Dict[str, Any]] = None,
    ) -> SyncResult:
        """Process delta - applies to existing book."""
        # Check if we have a snapshot
        book = self._books.get(symbol)
        if book is None:
            return SyncResult(
                book=None,
                coherence=BookCoherence.incoherent(
                    CoherenceStatus.NO_SNAPSHOT,
                    "No snapshot received yet",
                    sequence=sequence,
                ),
                resync_requested=True,
            )
        
        # Check sequence
        last_seq = self._last_sequence.get(symbol, 0)
        coherence = self._check_sequence(symbol, last_seq, sequence)
        
        if not coherence.is_coherent:
            return SyncResult(
                book=book,
                coherence=coherence,
                resync_requested=True,
            )
        
        # Apply deltas
        for bid in bids:
            price, size = float(bid[0]), float(bid[1])
            book.apply_delta(BookSide.BID, price, size)
        
        for ask in asks:
            price, size = float(ask[0]), float(ask[1])
            book.apply_delta(BookSide.ASK, price, size)
        
        # Update book metadata
        book.update_id = sequence
        book.timestamp = timestamp
        self._last_sequence[symbol] = sequence
        self._delta_counts[symbol] = self._delta_counts.get(symbol, 0) + 1
        
        # Check for crossed book after update
        if book.is_crossed():
            self._needs_resync[symbol] = True
            return SyncResult(
                book=book,
                coherence=BookCoherence.incoherent(
                    CoherenceStatus.CROSSED,
                    f"Crossed book after delta: bid={book.best_bid_price} >= ask={book.best_ask_price}",
                    sequence=sequence,
                ),
                resync_requested=True,
            )
        
        return SyncResult(
            book=book,
            coherence=BookCoherence.coherent(sequence, timestamp),
        )
    
    def _check_sequence(
        self,
        symbol: str,
        last_seq: int,
        new_seq: int,
    ) -> BookCoherence:
        """
        Check sequence validity.
        
        Override in subclass for venue-specific rules.
        """
        # Basic gap detection
        gap = new_seq - last_seq
        
        if gap <= 0:
            # Duplicate or old message - ignore but don't fail
            return BookCoherence.coherent(new_seq, 0)
        
        if gap > self._max_gap + 1:
            # Sequence gap detected
            self._gap_counts[symbol] = self._gap_counts.get(symbol, 0) + 1
            return BookCoherence.incoherent(
                CoherenceStatus.SEQUENCE_GAP,
                f"Sequence gap: {last_seq} -> {new_seq} (gap={gap})",
                sequence=new_seq,
                gap_count=self._gap_counts[symbol],
            )
        
        return BookCoherence.coherent(new_seq, 0)
    
    def get_book(self, symbol: str) -> Optional[OrderBook]:
        """Get current book."""
        return self._books.get(symbol)
    
    def get_coherence(self, symbol: str) -> BookCoherence:
        """Get current coherence status."""
        if symbol not in self._books:
            return BookCoherence.incoherent(
                CoherenceStatus.NO_SNAPSHOT,
                "No snapshot received",
            )
        
        if self._needs_resync.get(symbol, False):
            return BookCoherence.incoherent(
                CoherenceStatus.RESYNC_NEEDED,
                "Resync requested",
                sequence=self._last_sequence.get(symbol),
            )
        
        return BookCoherence.coherent(
            sequence=self._last_sequence.get(symbol, 0),
            timestamp=self._books[symbol].timestamp or 0,
        )
    
    def needs_resync(self, symbol: str) -> bool:
        """Check if resync needed."""
        return self._needs_resync.get(symbol, True)  # Default to needing resync
    
    def request_resync(self, symbol: str) -> None:
        """Request resync."""
        self._needs_resync[symbol] = True
    
    def clear_resync(self, symbol: str) -> None:
        """Clear resync flag."""
        self._needs_resync[symbol] = False
    
    def reset(self, symbol: str) -> None:
        """Reset all state for symbol."""
        self._books.pop(symbol, None)
        self._last_sequence.pop(symbol, None)
        self._needs_resync.pop(symbol, None)
        self._gap_counts.pop(symbol, None)
    
    def stats(self) -> Dict[str, Any]:
        """Get statistics."""
        return {
            "symbols_tracked": len(self._books),
            "total_snapshots": sum(self._snapshot_counts.values()),
            "total_deltas": sum(self._delta_counts.values()),
            "total_gaps": sum(self._gap_counts.values()),
            "symbols_needing_resync": sum(1 for v in self._needs_resync.values() if v),
        }
