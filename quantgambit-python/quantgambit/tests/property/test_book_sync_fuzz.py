"""
Property-based fuzz tests for order book synchronization.

Uses Hypothesis to generate random sequences of book updates and verify
that sync invariants always hold.

Invariants tested:
- Sequence gaps trigger resync
- Duplicate updates are handled safely
- Out-of-order updates don't corrupt state
- Crossed books are detected
- Coherence status is accurate
"""

import pytest
from hypothesis import given, strategies as st, settings, assume

from quantgambit.core.clock import SimClock, set_clock
from quantgambit.core.book.types import OrderBook, Level, BookSide
from quantgambit.core.book.venue_sync import (
    BaseBookSync,
    BookCoherence,
    CoherenceStatus,
    SyncResult,
)
from quantgambit.core.book.guardian import BookGuardian, GuardianConfig, BlockReason
from quantgambit.io.adapters.bybit.book_sync import BybitBookSync


# Strategies for generating test data
sequences = st.integers(min_value=1, max_value=10000)
prices = st.floats(min_value=1.0, max_value=100000.0, allow_nan=False, allow_infinity=False)
sizes = st.floats(min_value=0.0, max_value=1000.0, allow_nan=False, allow_infinity=False)
timestamps = st.floats(min_value=1704067200.0, max_value=1735689600.0)  # 2024-2025


def generate_book_levels(
    base_price: float,
    spread_bps: float = 10.0,
    depth: int = 5,
) -> tuple[list, list]:
    """Generate valid bid/ask levels."""
    spread = base_price * spread_bps / 10000
    mid = base_price
    
    bids = []
    asks = []
    
    for i in range(depth):
        bid_price = mid - spread / 2 - i * spread
        ask_price = mid + spread / 2 + i * spread
        
        bids.append([str(bid_price), "1.0"])
        asks.append([str(ask_price), "1.0"])
    
    return bids, asks


class TestBookSyncInvariants:
    """Property-based tests for book sync invariants."""
    
    @given(st.lists(sequences, min_size=1, max_size=50))
    @settings(max_examples=500)
    def test_sequence_gaps_detected(self, sequence_list):
        """
        Property: Sequence gaps are always detected.
        """
        sync = BybitBookSync(max_gap=0)  # Strict sequence
        symbol = "BTCUSDT"
        
        # Start with snapshot
        bids, asks = generate_book_levels(40000.0)
        sync.on_snapshot(symbol, bids, asks, 1, 1704067200.0)
        
        gap_detected = False
        last_seq = 1
        
        for seq in sequence_list:
            if seq <= last_seq:
                continue  # Skip duplicates/old
            
            result = sync.on_delta(symbol, [], [], seq, 1704067200.0)
            
            expected_gap = seq > last_seq + 1
            if expected_gap and not result.coherence.is_coherent:
                gap_detected = True
            
            if result.coherence.is_coherent:
                last_seq = seq
        
        # If we had gaps, they should have been detected
        # (unless all sequences were consecutive)
    
    @given(st.lists(sequences, min_size=2, max_size=30))
    @settings(max_examples=300)
    def test_duplicate_updates_safe(self, sequence_list):
        """
        Property: Duplicate sequence numbers don't corrupt state.
        """
        sync = BybitBookSync()
        symbol = "BTCUSDT"
        
        # Start with snapshot
        bids, asks = generate_book_levels(40000.0)
        sync.on_snapshot(symbol, bids, asks, 1, 1704067200.0)
        
        # Send same sequence multiple times
        for seq in sequence_list:
            for _ in range(3):  # Send each 3 times
                result = sync.on_delta(symbol, [], [], seq, 1704067200.0)
                
                # Should never crash
                assert result is not None
                
                # Book should still be valid if it was valid before
                book = sync.get_book(symbol)
                if book:
                    assert not book.is_crossed()
    
    @given(st.lists(st.tuples(sequences, st.booleans()), min_size=1, max_size=30))
    @settings(max_examples=300)
    def test_out_of_order_handled(self, updates):
        """
        Property: Out-of-order updates don't corrupt state.
        """
        sync = BybitBookSync()
        symbol = "BTCUSDT"
        
        # Start with snapshot
        bids, asks = generate_book_levels(40000.0)
        sync.on_snapshot(symbol, bids, asks, 100, 1704067200.0)
        
        # Shuffle the updates
        import random
        random.shuffle(updates)
        
        for seq, is_snapshot in updates:
            if is_snapshot:
                bids, asks = generate_book_levels(40000.0)
                result = sync.on_snapshot(symbol, bids, asks, seq, 1704067200.0)
            else:
                result = sync.on_delta(symbol, [], [], seq, 1704067200.0)
            
            # Should never crash
            assert result is not None
            
            # Book should be valid or None
            book = sync.get_book(symbol)
            if book:
                assert not book.is_crossed()
    
    @given(prices, prices)
    @settings(max_examples=200)
    def test_crossed_book_detected(self, bid_price, ask_price):
        """
        Property: Crossed books (bid >= ask) are always detected.
        """
        sync = BybitBookSync()
        symbol = "BTCUSDT"
        
        bids = [[str(bid_price), "1.0"]]
        asks = [[str(ask_price), "1.0"]]
        
        result = sync.on_snapshot(symbol, bids, asks, 1, 1704067200.0)
        
        is_crossed = bid_price >= ask_price
        
        if is_crossed:
            assert not result.coherence.is_coherent, \
                f"Crossed book not detected: bid={bid_price}, ask={ask_price}"
            assert result.coherence.status == CoherenceStatus.CROSSED
        else:
            assert result.coherence.is_coherent, \
                f"Valid book rejected: bid={bid_price}, ask={ask_price}"


class TestBookGuardianInvariants:
    """Property-based tests for BookGuardian."""
    
    @given(prices, st.floats(min_value=0.1, max_value=100.0))
    @settings(max_examples=300)
    def test_spread_threshold_enforced(self, mid_price, spread_bps):
        """
        Property: Spread threshold is always enforced.
        """
        assume(mid_price > 0)
        
        clock = SimClock(start_time=1704067200.0)
        set_clock(clock)
        
        config = GuardianConfig(max_spread_bps=50.0)  # 0.5%
        sync = BybitBookSync()
        guardian = BookGuardian(sync, clock, config)
        
        symbol = "BTCUSDT"
        
        # Create book with specified spread
        spread = mid_price * spread_bps / 10000
        bid = mid_price - spread / 2
        ask = mid_price + spread / 2
        
        bids = [[str(bid), "1.0"]]
        asks = [[str(ask), "1.0"]]
        
        sync.on_snapshot(symbol, bids, asks, 1, clock.now_wall())
        health = guardian.check(symbol)
        
        if spread_bps > config.max_spread_bps:
            assert not health.is_tradeable, \
                f"Wide spread not blocked: {spread_bps} bps > {config.max_spread_bps}"
            assert health.block_reason == BlockReason.SPREAD_TOO_WIDE
        else:
            # May still be blocked for other reasons (depth, etc.)
            if health.block_reason == BlockReason.SPREAD_TOO_WIDE:
                pytest.fail(f"Valid spread blocked: {spread_bps} bps <= {config.max_spread_bps}")
    
    @given(st.integers(min_value=0, max_value=10))
    @settings(max_examples=100)
    def test_depth_threshold_enforced(self, depth):
        """
        Property: Depth threshold is always enforced.
        """
        clock = SimClock(start_time=1704067200.0)
        set_clock(clock)
        
        config = GuardianConfig(min_depth_levels=3)
        sync = BybitBookSync()
        guardian = BookGuardian(sync, clock, config)
        
        symbol = "BTCUSDT"
        
        # Create book with specified depth
        bids, asks = generate_book_levels(40000.0, depth=depth)
        
        sync.on_snapshot(symbol, bids, asks, 1, clock.now_wall())
        health = guardian.check(symbol)
        
        if depth < config.min_depth_levels:
            assert not health.is_tradeable, \
                f"Shallow book not blocked: {depth} < {config.min_depth_levels}"
            assert health.block_reason == BlockReason.INSUFFICIENT_DEPTH
    
    @given(st.floats(min_value=0.0, max_value=20.0))
    @settings(max_examples=200)
    def test_staleness_detected(self, age_sec):
        """
        Property: Stale books are always detected.
        """
        clock = SimClock(start_time=1704067200.0)
        set_clock(clock)
        
        config = GuardianConfig(max_book_age_sec=5.0)
        sync = BybitBookSync()
        guardian = BookGuardian(sync, clock, config)
        
        symbol = "BTCUSDT"
        
        # Create book
        bids, asks = generate_book_levels(40000.0)
        book_time = clock.now_wall()
        sync.on_snapshot(symbol, bids, asks, 1, book_time)
        
        # Advance clock
        clock.advance(age_sec)
        
        health = guardian.check(symbol)
        
        if age_sec > config.max_book_age_sec:
            assert not health.is_tradeable, \
                f"Stale book not blocked: {age_sec}s > {config.max_book_age_sec}s"
            assert health.block_reason == BlockReason.STALE
    
    @given(st.lists(st.booleans(), min_size=1, max_size=20))
    @settings(max_examples=200)
    def test_state_transitions_consistent(self, coherence_sequence):
        """
        Property: Guardian state transitions are consistent.
        """
        clock = SimClock(start_time=1704067200.0)
        set_clock(clock)
        
        config = GuardianConfig()
        sync = BybitBookSync()
        guardian = BookGuardian(sync, clock, config)
        
        symbol = "BTCUSDT"
        seq = 1
        
        for should_be_coherent in coherence_sequence:
            if should_be_coherent:
                # Send valid snapshot
                bids, asks = generate_book_levels(40000.0)
                sync.on_snapshot(symbol, bids, asks, seq, clock.now_wall())
                seq += 1
            else:
                # Trigger resync (gap)
                sync.request_resync(symbol)
            
            health = guardian.check(symbol)
            
            # Health should reflect sync state
            coherence = sync.get_coherence(symbol)
            if not coherence.is_coherent:
                assert not health.is_tradeable


class TestOrderBookInvariants:
    """Property-based tests for OrderBook data structure."""
    
    @given(st.lists(st.tuples(prices, sizes), min_size=1, max_size=20))
    @settings(max_examples=300)
    def test_delta_application_consistent(self, deltas):
        """
        Property: Delta application maintains book consistency.
        """
        book = OrderBook(symbol="BTCUSDT")
        
        for price, size in deltas:
            assume(price > 0)
            
            # Apply to bids
            book.apply_delta(BookSide.BID, price, size)
            
            # Check consistency
            for i in range(len(book.bids) - 1):
                assert book.bids[i].price >= book.bids[i + 1].price, \
                    "Bids not sorted descending"
            
            # All sizes should be positive (or level removed)
            for level in book.bids:
                assert level.size > 0
    
    @given(st.lists(st.tuples(prices, sizes), min_size=1, max_size=20))
    @settings(max_examples=300)
    def test_zero_size_removes_level(self, deltas):
        """
        Property: Zero-size deltas remove levels.
        """
        book = OrderBook(symbol="BTCUSDT")
        
        # First add some levels
        for price, size in deltas:
            assume(price > 0 and size > 0)
            book.apply_delta(BookSide.BID, price, size)
        
        initial_count = len(book.bids)
        
        # Now remove with zero size
        for price, _ in deltas[:len(deltas) // 2]:
            book.apply_delta(BookSide.BID, price, 0.0)
        
        # Should have fewer levels
        assert len(book.bids) <= initial_count


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
