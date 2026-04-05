"""
BookGuardian - Quoteability gate for trading decisions.

The BookGuardian is a hard execution gate that determines whether
a symbol is safe to trade based on book integrity and quality.

Checks performed:
1. Book exists (snapshot received)
2. Book is coherent (no sequence gaps, valid state)
3. Book is fresh (not stale)
4. Book is not crossed
5. Spread is acceptable
6. Depth is sufficient
7. Top-of-book sizes meet minimums

If any check fails, the symbol is marked as NOT tradeable and
the decision pipeline should skip it.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Dict, Any, Callable

from quantgambit.core.clock import Clock, get_clock
from quantgambit.core.book.types import OrderBook, BookUpdate, Level
from quantgambit.core.book.venue_sync import VenueBookSync, BookCoherence, CoherenceStatus


class BlockReason(str, Enum):
    """Reasons why trading is blocked."""
    
    NO_BOOK = "no_book"                   # No book data
    INCOHERENT = "incoherent"             # Book sync failed
    STALE = "stale"                       # Book too old
    CROSSED = "crossed"                   # Bid >= ask
    SPREAD_TOO_WIDE = "spread_too_wide"   # Spread exceeds limit
    INSUFFICIENT_DEPTH = "insufficient_depth"  # Not enough levels
    INSUFFICIENT_SIZE = "insufficient_size"    # Top-of-book too thin
    RESYNC_PENDING = "resync_pending"     # Waiting for resync


@dataclass
class GuardianConfig:
    """
    Configuration for BookGuardian checks.
    
    Attributes:
        max_book_age_sec: Maximum book age before stale
        max_spread_bps: Maximum spread in basis points
        min_depth_levels: Minimum required depth levels per side
        min_top_size: Minimum size at best bid/ask
        min_total_size: Minimum cumulative size across top N levels
        size_check_levels: Number of levels to check for min_total_size
    """
    
    max_book_age_sec: float = 5.0
    max_spread_bps: float = 50.0  # 0.5%
    min_depth_levels: int = 3
    min_top_size: float = 0.0  # No minimum by default
    min_total_size: float = 0.0  # No minimum by default
    size_check_levels: int = 5


@dataclass
class BookHealth:
    """
    Health status for a symbol's book.
    
    Attributes:
        symbol: Trading symbol
        is_tradeable: Whether trading is allowed
        block_reason: Why trading is blocked (if applicable)
        coherence: Book sync coherence status
        book_age_sec: Age of book in seconds
        spread_bps: Current spread in basis points
        bid_depth: Number of bid levels
        ask_depth: Number of ask levels
        best_bid: Best bid price
        best_ask: Best ask price
        mid_price: Mid price
        last_check_mono: Monotonic time of last check
        unsafe_since_mono: When symbol became unsafe (if applicable)
        resync_count: Number of resyncs triggered
    """
    
    symbol: str
    is_tradeable: bool = False
    block_reason: Optional[BlockReason] = None
    coherence: Optional[BookCoherence] = None
    book_age_sec: float = 0.0
    spread_bps: Optional[float] = None
    bid_depth: int = 0
    ask_depth: int = 0
    best_bid: Optional[float] = None
    best_ask: Optional[float] = None
    mid_price: Optional[float] = None
    last_check_mono: float = 0.0
    unsafe_since_mono: Optional[float] = None
    resync_count: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "symbol": self.symbol,
            "is_tradeable": self.is_tradeable,
            "block_reason": self.block_reason.value if self.block_reason else None,
            "book_age_sec": self.book_age_sec,
            "spread_bps": self.spread_bps,
            "bid_depth": self.bid_depth,
            "ask_depth": self.ask_depth,
            "best_bid": self.best_bid,
            "best_ask": self.best_ask,
            "mid_price": self.mid_price,
            "resync_count": self.resync_count,
        }


# Callback type for state change notifications
StateChangeCallback = Callable[[str, bool, Optional[BlockReason]], None]


class BookGuardian:
    """
    Hard execution gate based on book integrity and quality.
    
    The BookGuardian consumes book updates from VenueBookSync and
    determines whether each symbol is safe to trade.
    
    Usage:
        sync = BybitBookSync()
        guardian = BookGuardian(sync, clock, config)
        
        # On book update
        result = sync.on_delta(symbol, bids, asks, seq, ts)
        health = guardian.check(symbol)
        
        if health.is_tradeable:
            # Safe to trade
            pass
        else:
            # Skip this symbol
            logger.info(f"Skipping {symbol}: {health.block_reason}")
    """
    
    def __init__(
        self,
        book_sync: VenueBookSync,
        clock: Optional[Clock] = None,
        config: Optional[GuardianConfig] = None,
        on_state_change: Optional[StateChangeCallback] = None,
    ):
        """
        Initialize the guardian.
        
        Args:
            book_sync: VenueBookSync instance for book data
            clock: Clock for timestamps (uses global if not provided)
            config: Guardian configuration
            on_state_change: Callback when tradeable state changes
        """
        self._sync = book_sync
        self._clock = clock or get_clock()
        self._config = config or GuardianConfig()
        self._on_state_change = on_state_change
        
        # Per-symbol health tracking
        self._health: Dict[str, BookHealth] = {}
    
    def check(self, symbol: str) -> BookHealth:
        """
        Check if a symbol is tradeable.
        
        This is the main entry point. Call after each book update
        or periodically to get current tradeable status.
        
        Args:
            symbol: Symbol to check
            
        Returns:
            BookHealth with current status
        """
        now_mono = self._clock.now_mono()
        now_wall = self._clock.now_wall()
        
        # Get or create health record
        health = self._health.get(symbol)
        if health is None:
            health = BookHealth(symbol=symbol)
            self._health[symbol] = health
        
        was_tradeable = health.is_tradeable
        
        # Get book and coherence from sync
        book = self._sync.get_book(symbol)
        coherence = self._sync.get_coherence(symbol)
        health.coherence = coherence
        health.last_check_mono = now_mono
        
        # Check 1: Book exists
        if book is None:
            self._mark_unsafe(health, BlockReason.NO_BOOK, now_mono)
            self._notify_if_changed(symbol, was_tradeable, health)
            return health
        
        # Check 2: Book is coherent
        if not coherence.is_coherent:
            reason = BlockReason.INCOHERENT
            if coherence.status == CoherenceStatus.RESYNC_NEEDED:
                reason = BlockReason.RESYNC_PENDING
            self._mark_unsafe(health, reason, now_mono)
            self._notify_if_changed(symbol, was_tradeable, health)
            return health
        
        # Check 3: Book is fresh
        if book.timestamp:
            age = now_wall - book.timestamp
            health.book_age_sec = age
            if age > self._config.max_book_age_sec:
                self._mark_unsafe(health, BlockReason.STALE, now_mono)
                self._sync.request_resync(symbol)
                health.resync_count += 1
                self._notify_if_changed(symbol, was_tradeable, health)
                return health
        
        # Check 4: Book is not crossed
        if book.is_crossed():
            self._mark_unsafe(health, BlockReason.CROSSED, now_mono)
            self._sync.request_resync(symbol)
            health.resync_count += 1
            self._notify_if_changed(symbol, was_tradeable, health)
            return health
        
        # Update health metrics
        health.best_bid = book.best_bid_price
        health.best_ask = book.best_ask_price
        health.mid_price = book.mid_price
        health.spread_bps = book.spread_bps
        health.bid_depth = len(book.bids)
        health.ask_depth = len(book.asks)
        
        # Check 5: Spread is acceptable
        if (
            health.spread_bps is not None
            and health.spread_bps > self._config.max_spread_bps + 1e-6
        ):
            self._mark_unsafe(health, BlockReason.SPREAD_TOO_WIDE, now_mono)
            self._notify_if_changed(symbol, was_tradeable, health)
            return health
        
        # Check 6: Sufficient depth
        if (
            health.bid_depth < self._config.min_depth_levels
            or health.ask_depth < self._config.min_depth_levels
        ):
            self._mark_unsafe(health, BlockReason.INSUFFICIENT_DEPTH, now_mono)
            self._notify_if_changed(symbol, was_tradeable, health)
            return health
        
        # Check 7: Sufficient size at top of book
        if self._config.min_top_size > 0:
            bid_size = book.bids[0].size if book.bids else 0
            ask_size = book.asks[0].size if book.asks else 0
            if bid_size < self._config.min_top_size or ask_size < self._config.min_top_size:
                self._mark_unsafe(health, BlockReason.INSUFFICIENT_SIZE, now_mono)
                self._notify_if_changed(symbol, was_tradeable, health)
                return health
        
        # Check 8: Sufficient total size across levels
        if self._config.min_total_size > 0:
            from quantgambit.core.book.types import BookSide
            bid_total = book.cumulative_size(BookSide.BID, self._config.size_check_levels)
            ask_total = book.cumulative_size(BookSide.ASK, self._config.size_check_levels)
            if bid_total < self._config.min_total_size or ask_total < self._config.min_total_size:
                self._mark_unsafe(health, BlockReason.INSUFFICIENT_SIZE, now_mono)
                self._notify_if_changed(symbol, was_tradeable, health)
                return health
        
        # All checks passed - mark as tradeable
        self._mark_safe(health)
        self._notify_if_changed(symbol, was_tradeable, health)
        return health
    
    def _mark_unsafe(
        self,
        health: BookHealth,
        reason: BlockReason,
        now_mono: float,
    ) -> None:
        """Mark symbol as unsafe for trading."""
        if health.is_tradeable:
            health.unsafe_since_mono = now_mono
        health.is_tradeable = False
        health.block_reason = reason
    
    def _mark_safe(self, health: BookHealth) -> None:
        """Mark symbol as safe for trading."""
        health.is_tradeable = True
        health.block_reason = None
        health.unsafe_since_mono = None
    
    def _notify_if_changed(
        self,
        symbol: str,
        was_tradeable: bool,
        health: BookHealth,
    ) -> None:
        """Notify callback if tradeable state changed."""
        if self._on_state_change and was_tradeable != health.is_tradeable:
            self._on_state_change(symbol, health.is_tradeable, health.block_reason)
    
    def is_tradeable(self, symbol: str) -> bool:
        """
        Quick check if symbol is tradeable.
        
        Uses cached health - call check() first to update.
        """
        health = self._health.get(symbol)
        return health is not None and health.is_tradeable
    
    def get_health(self, symbol: str) -> Optional[BookHealth]:
        """Get cached health for a symbol."""
        return self._health.get(symbol)
    
    def get_all_health(self) -> Dict[str, BookHealth]:
        """Get health for all tracked symbols."""
        return dict(self._health)
    
    def get_tradeable_symbols(self) -> list[str]:
        """Get list of currently tradeable symbols."""
        return [s for s, h in self._health.items() if h.is_tradeable]
    
    def get_blocked_symbols(self) -> Dict[str, BlockReason]:
        """Get blocked symbols with their reasons."""
        return {
            s: h.block_reason
            for s, h in self._health.items()
            if not h.is_tradeable and h.block_reason
        }
    
    def reset(self, symbol: str) -> None:
        """Reset health tracking for a symbol."""
        self._health.pop(symbol, None)
    
    def stats(self) -> Dict[str, Any]:
        """Get guardian statistics."""
        total = len(self._health)
        tradeable = sum(1 for h in self._health.values() if h.is_tradeable)
        
        by_reason: Dict[str, int] = {}
        for h in self._health.values():
            if not h.is_tradeable and h.block_reason:
                reason = h.block_reason.value
                by_reason[reason] = by_reason.get(reason, 0) + 1
        
        total_resyncs = sum(h.resync_count for h in self._health.values())
        
        return {
            "total_symbols": total,
            "tradeable": tradeable,
            "blocked": total - tradeable,
            "blocked_by_reason": by_reason,
            "total_resyncs": total_resyncs,
        }
    
    # ================================================================
    # HotPath compatibility methods
    # ================================================================
    
    def handle_update(self, symbol: str, update: BookUpdate) -> Optional[OrderBook]:
        """
        Process a book update and return the book if quoteable.
        
        This method provides HotPath compatibility by:
        1. Converting BookUpdate to sync format
        2. Processing through the underlying VenueBookSync
        3. Running quoteability checks
        4. Returning the book if safe to trade, None otherwise
        
        Args:
            symbol: Trading symbol
            update: Book update (snapshot or delta)
            
        Returns:
            OrderBook if quoteable, None if not safe to trade
        """
        # Convert Level objects to raw [price, size] lists
        bids_raw = [[level.price, level.size] for level in update.bids]
        asks_raw = [[level.price, level.size] for level in update.asks]
        
        # Get sequence and timestamp (default to 0 if None)
        sequence = update.sequence_id or 0
        timestamp = update.timestamp or self._clock.now_wall()
        
        # Route to appropriate sync method
        if update.is_snapshot:
            result = self._sync.on_snapshot(
                symbol=symbol,
                bids=bids_raw,
                asks=asks_raw,
                sequence=sequence,
                timestamp=timestamp,
            )
        else:
            result = self._sync.on_delta(
                symbol=symbol,
                bids=bids_raw,
                asks=asks_raw,
                sequence=sequence,
                timestamp=timestamp,
            )
        
        # Check if sync result indicates incoherence
        if result.book is None or result.resync_requested:
            # Force a health check to update status
            self.check(symbol)
            return None
        
        # Run full quoteability check
        health = self.check(symbol)
        
        # Return book only if quoteable
        if health.is_tradeable:
            return result.book
        
        return None
    
    def is_quoteable(self, symbol: str) -> bool:
        """
        Check if a symbol is quoteable (safe to trade).
        
        This is an alias for is_tradeable() to provide
        HotPath interface compatibility.
        
        Args:
            symbol: Trading symbol
            
        Returns:
            True if symbol is safe to trade
        """
        return self.is_tradeable(symbol)
