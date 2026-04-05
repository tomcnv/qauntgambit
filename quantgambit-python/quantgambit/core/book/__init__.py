"""
Order book management - types, sync, and guardian.

This package contains:
- types: OrderBook, Level, and related data structures
- venue_sync: Per-venue book synchronization logic
- guardian: BookGuardian quoteability gate
"""

from quantgambit.core.book.types import OrderBook, Level, BookSide
from quantgambit.core.book.venue_sync import (
    VenueBookSync,
    BookCoherence,
    SyncResult,
)
from quantgambit.core.book.guardian import BookGuardian, BookHealth, GuardianConfig

__all__ = [
    "OrderBook",
    "Level",
    "BookSide",
    "VenueBookSync",
    "BookCoherence",
    "SyncResult",
    "BookGuardian",
    "BookHealth",
    "GuardianConfig",
]
