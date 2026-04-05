"""
Tests for BookGuardian HotPath compatibility methods.

Tests the interface alignment between BookGuardian and HotPath:
- handle_update(symbol, BookUpdate) -> Optional[OrderBook]
- is_quoteable(symbol) -> bool
"""

import pytest
from quantgambit.core.clock import SimClock
from quantgambit.core.book.types import OrderBook, BookUpdate, Level
from quantgambit.core.book.guardian import BookGuardian, GuardianConfig, BlockReason
from quantgambit.io.adapters.bybit.book_sync import BybitBookSync


@pytest.fixture
def clock():
    """Create a SimClock."""
    return SimClock()


@pytest.fixture
def book_sync():
    """Create a BybitBookSync."""
    return BybitBookSync(max_stale_sec=5.0)


@pytest.fixture
def guardian(book_sync, clock):
    """Create a BookGuardian with relaxed config for testing."""
    config = GuardianConfig(
        max_book_age_sec=5.0,
        max_spread_bps=100.0,  # 1%
        min_depth_levels=1,
        min_top_size=0.0,
    )
    return BookGuardian(
        book_sync=book_sync,
        clock=clock,
        config=config,
    )


def create_book_update(
    symbol: str,
    bid: float,
    ask: float,
    seq: int = 1,
    is_snapshot: bool = True,
) -> BookUpdate:
    """Create a BookUpdate for testing."""
    return BookUpdate(
        symbol=symbol,
        bids=[Level(price=bid, size=10.0)],
        asks=[Level(price=ask, size=10.0)],
        sequence_id=seq,
        timestamp=0.0,
        is_snapshot=is_snapshot,
    )


class TestHandleUpdate:
    """Test handle_update method."""
    
    def test_snapshot_returns_book(self, guardian, clock):
        """Snapshot update should return valid book."""
        update = create_book_update("BTCUSDT", 50000.0, 50001.0, seq=1, is_snapshot=True)
        
        book = guardian.handle_update("BTCUSDT", update)
        
        assert book is not None
        assert book.symbol == "BTCUSDT"
        assert book.best_bid_price == 50000.0
        assert book.best_ask_price == 50001.0
    
    def test_delta_without_snapshot_returns_none(self, guardian, clock):
        """Delta without prior snapshot should return None."""
        update = create_book_update("BTCUSDT", 50000.0, 50001.0, seq=1, is_snapshot=False)
        
        book = guardian.handle_update("BTCUSDT", update)
        
        # Delta without snapshot fails - book sync requires snapshot first
        assert book is None
    
    def test_delta_after_snapshot_returns_book(self, guardian, clock):
        """Delta after snapshot should return updated book."""
        # First send snapshot
        snapshot = create_book_update("BTCUSDT", 50000.0, 50010.0, seq=1, is_snapshot=True)
        guardian.handle_update("BTCUSDT", snapshot)
        
        # Then send delta - update the SAME price level with new size
        # Note: delta ADDS/UPDATES levels, doesn't replace the entire book
        delta = BookUpdate(
            symbol="BTCUSDT",
            bids=[Level(price=50000.0, size=20.0)],  # Update existing bid size
            asks=[Level(price=50010.0, size=20.0)],  # Update existing ask size
            sequence_id=2,
            timestamp=0.0,
            is_snapshot=False,
        )
        book = guardian.handle_update("BTCUSDT", delta)
        
        assert book is not None
        # Best prices stay the same, sizes updated
        assert book.best_bid_price == 50000.0
        assert book.best_ask_price == 50010.0
        assert book.bids[0].size == 20.0
        assert book.asks[0].size == 20.0
    
    def test_crossed_book_returns_none(self, guardian, clock):
        """Crossed book (bid >= ask) should return None."""
        # Crossed book: bid > ask
        update = create_book_update("BTCUSDT", 50010.0, 50000.0, seq=1, is_snapshot=True)
        
        book = guardian.handle_update("BTCUSDT", update)
        
        assert book is None
        
        # Symbol should not be quoteable
        assert guardian.is_quoteable("BTCUSDT") is False
        
        # Verify it was blocked (could be CROSSED or NO_BOOK depending on sync behavior)
        health = guardian.get_health("BTCUSDT")
        assert health is not None
        assert health.is_tradeable is False
        assert health.block_reason is not None  # Either CROSSED or NO_BOOK


class TestIsQuoteable:
    """Test is_quoteable method."""
    
    def test_quoteable_after_valid_update(self, guardian, clock):
        """Symbol should be quoteable after valid update."""
        update = create_book_update("BTCUSDT", 50000.0, 50001.0, seq=1, is_snapshot=True)
        guardian.handle_update("BTCUSDT", update)
        
        assert guardian.is_quoteable("BTCUSDT") is True
    
    def test_not_quoteable_before_update(self, guardian):
        """Symbol should not be quoteable before any update."""
        assert guardian.is_quoteable("BTCUSDT") is False
    
    def test_not_quoteable_after_crossed_book(self, guardian, clock):
        """Symbol should not be quoteable with crossed book."""
        update = create_book_update("BTCUSDT", 50010.0, 50000.0, seq=1, is_snapshot=True)
        guardian.handle_update("BTCUSDT", update)
        
        assert guardian.is_quoteable("BTCUSDT") is False
    
    def test_quoteable_alias_for_is_tradeable(self, guardian, clock):
        """is_quoteable should be alias for is_tradeable."""
        update = create_book_update("BTCUSDT", 50000.0, 50001.0, seq=1, is_snapshot=True)
        guardian.handle_update("BTCUSDT", update)
        
        assert guardian.is_quoteable("BTCUSDT") == guardian.is_tradeable("BTCUSDT")


class TestSequenceHandling:
    """Test sequence number handling."""
    
    def test_sequential_updates(self, guardian, clock):
        """Sequential updates should be processed correctly."""
        # Snapshot with wide spread to allow delta updates
        update1 = create_book_update("BTCUSDT", 50000.0, 50100.0, seq=1, is_snapshot=True)
        book1 = guardian.handle_update("BTCUSDT", update1)
        assert book1 is not None
        assert book1.best_bid_price == 50000.0
        
        # Delta seq=2 - update existing levels (same prices, new sizes)
        update2 = BookUpdate(
            symbol="BTCUSDT",
            bids=[Level(price=50000.0, size=15.0)],
            asks=[Level(price=50100.0, size=15.0)],
            sequence_id=2,
            timestamp=0.0,
            is_snapshot=False,
        )
        book2 = guardian.handle_update("BTCUSDT", update2)
        assert book2 is not None
        assert book2.bids[0].size == 15.0
        
        # Delta seq=3 - add a new level
        update3 = BookUpdate(
            symbol="BTCUSDT",
            bids=[Level(price=50010.0, size=5.0)],  # New bid level
            asks=[Level(price=50090.0, size=5.0)],  # New ask level
            sequence_id=3,
            timestamp=0.0,
            is_snapshot=False,
        )
        book3 = guardian.handle_update("BTCUSDT", update3)
        assert book3 is not None
        # Best bid is now 50010 (higher than 50000)
        assert book3.best_bid_price == 50010.0
        # Best ask is now 50090 (lower than 50100)
        assert book3.best_ask_price == 50090.0
    
    def test_gap_triggers_resync(self, guardian, clock):
        """Sequence gap should trigger resync need."""
        # Snapshot seq=1
        update1 = create_book_update("BTCUSDT", 50000.0, 50001.0, seq=1, is_snapshot=True)
        guardian.handle_update("BTCUSDT", update1)
        
        # Skip to seq=10 (gap of 8)
        update2 = create_book_update("BTCUSDT", 50010.0, 50011.0, seq=10, is_snapshot=False)
        book = guardian.handle_update("BTCUSDT", update2)
        
        # Should return None due to gap detection
        # (Bybit requires strict sequence: new_u == last_u + 1)
        assert book is None


class TestMultipleSymbols:
    """Test handling multiple symbols."""
    
    def test_independent_symbol_tracking(self, guardian, clock):
        """Each symbol should be tracked independently."""
        # Update BTCUSDT
        btc_update = create_book_update("BTCUSDT", 50000.0, 50001.0, seq=1, is_snapshot=True)
        guardian.handle_update("BTCUSDT", btc_update)
        
        # Update ETHUSDT
        eth_update = create_book_update("ETHUSDT", 3000.0, 3001.0, seq=1, is_snapshot=True)
        guardian.handle_update("ETHUSDT", eth_update)
        
        assert guardian.is_quoteable("BTCUSDT") is True
        assert guardian.is_quoteable("ETHUSDT") is True
        
        # Cross ETHUSDT book
        eth_crossed = create_book_update("ETHUSDT", 3010.0, 3000.0, seq=2, is_snapshot=False)
        guardian.handle_update("ETHUSDT", eth_crossed)
        
        # BTCUSDT should still be quoteable
        assert guardian.is_quoteable("BTCUSDT") is True
        # ETHUSDT should not be quoteable
        assert guardian.is_quoteable("ETHUSDT") is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
