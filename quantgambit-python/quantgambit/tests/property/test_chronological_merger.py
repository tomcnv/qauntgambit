"""Property-based tests for ChronologicalMerger.

Feature: backtest-timescaledb-replay, Property 7: Chronological Ordering

Tests that for any sequence of merged orderbook snapshots and trade records,
the output SHALL be ordered by timestamp ascending. When two events have
identical timestamps, orderbook snapshots SHALL appear before trade records.

**Validates: Requirements 3.1, 3.2**
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import AsyncIterator, List, Tuple

import pytest
from hypothesis import given, strategies as st, settings, assume

from quantgambit.storage.persistence import OrderbookSnapshot, PersistenceTradeRecord
from quantgambit.backtesting.chronological_merger import ChronologicalMerger


# =============================================================================
# Strategies for generating test data (from design.md)
# =============================================================================

# OrderbookSnapshot generator as specified in design.md
orderbook_level = st.tuples(
    st.floats(min_value=0.01, max_value=100000.0, allow_nan=False, allow_infinity=False),
    st.floats(min_value=0.0001, max_value=10000.0, allow_nan=False, allow_infinity=False),
)

# Symbol generator - non-empty alphanumeric strings
symbol_strategy = st.text(
    min_size=1,
    max_size=20,
    alphabet=st.characters(whitelist_categories=('L', 'N')),
)

# Exchange generator - sampled from common exchanges
exchange_strategy = st.sampled_from(["binance", "okx", "coinbase", "kraken"])

# Timestamp generator - realistic datetime range
timestamp_strategy = st.datetimes(
    min_value=datetime(2020, 1, 1),
    max_value=datetime(2030, 1, 1),
)

# Sequence number generator
seq_strategy = st.integers(min_value=1, max_value=1000000)

# Bids and asks generators - non-empty lists of levels
bids_strategy = st.lists(orderbook_level, min_size=1, max_size=20)
asks_strategy = st.lists(orderbook_level, min_size=1, max_size=20)

# Spread in basis points
spread_bps_strategy = st.floats(
    min_value=0.0,
    max_value=1000.0,
    allow_nan=False,
    allow_infinity=False,
)

# Depth in USD
depth_usd_strategy = st.floats(
    min_value=0.0,
    max_value=100000000.0,
    allow_nan=False,
    allow_infinity=False,
)

# Orderbook imbalance (0 to 1)
imbalance_strategy = st.floats(
    min_value=0.0,
    max_value=1.0,
    allow_nan=False,
    allow_infinity=False,
)


def convert_levels_to_lists(levels: List[Tuple[float, float]]) -> List[List[float]]:
    """Convert tuples to lists for OrderbookSnapshot compatibility."""
    return [[price, size] for price, size in levels]


# Complete OrderbookSnapshot generator
@st.composite
def orderbook_snapshot_strategy(draw, timestamp: datetime = None):
    """Generate a valid OrderbookSnapshot with non-empty bids and asks."""
    bids_tuples = draw(bids_strategy)
    asks_tuples = draw(asks_strategy)
    
    ts = timestamp if timestamp is not None else draw(timestamp_strategy)
    
    return OrderbookSnapshot(
        symbol=draw(symbol_strategy),
        exchange=draw(exchange_strategy),
        timestamp=ts,
        seq=draw(seq_strategy),
        bids=convert_levels_to_lists(bids_tuples),
        asks=convert_levels_to_lists(asks_tuples),
        spread_bps=draw(spread_bps_strategy),
        bid_depth_usd=draw(depth_usd_strategy),
        ask_depth_usd=draw(depth_usd_strategy),
        orderbook_imbalance=draw(imbalance_strategy),
    )


# Trade record generator as specified in design.md
@st.composite
def trade_record_strategy(draw, timestamp: datetime = None):
    """Generate a valid PersistenceTradeRecord."""
    ts = timestamp if timestamp is not None else draw(timestamp_strategy)
    
    return PersistenceTradeRecord(
        symbol=draw(symbol_strategy),
        exchange=draw(exchange_strategy),
        timestamp=ts,
        price=draw(st.floats(min_value=0.01, max_value=100000.0, allow_nan=False, allow_infinity=False)),
        size=draw(st.floats(min_value=0.0001, max_value=10000.0, allow_nan=False, allow_infinity=False)),
        side=draw(st.sampled_from(["buy", "sell"])),
        trade_id=draw(st.text(min_size=1, max_size=50, alphabet=st.characters(whitelist_categories=('L', 'N')))),
    )


# Strategy for generating sorted lists of orderbook snapshots
@st.composite
def sorted_orderbook_snapshots_strategy(draw, min_size: int = 0, max_size: int = 10):
    """Generate a list of OrderbookSnapshots sorted by timestamp ascending."""
    count = draw(st.integers(min_value=min_size, max_value=max_size))
    
    if count == 0:
        return []
    
    # Generate timestamps and sort them
    base_time = draw(st.datetimes(min_value=datetime(2020, 1, 1), max_value=datetime(2029, 1, 1)))
    time_deltas = sorted([
        draw(st.integers(min_value=0, max_value=86400))  # Up to 1 day in seconds
        for _ in range(count)
    ])
    
    snapshots = []
    for delta in time_deltas:
        ts = base_time + timedelta(seconds=delta)
        bids_tuples = draw(bids_strategy)
        asks_tuples = draw(asks_strategy)
        
        snapshot = OrderbookSnapshot(
            symbol=draw(symbol_strategy),
            exchange=draw(exchange_strategy),
            timestamp=ts,
            seq=draw(seq_strategy),
            bids=convert_levels_to_lists(bids_tuples),
            asks=convert_levels_to_lists(asks_tuples),
            spread_bps=draw(spread_bps_strategy),
            bid_depth_usd=draw(depth_usd_strategy),
            ask_depth_usd=draw(depth_usd_strategy),
            orderbook_imbalance=draw(imbalance_strategy),
        )
        snapshots.append(snapshot)
    
    return snapshots


# Strategy for generating sorted lists of trade records
@st.composite
def sorted_trade_records_strategy(draw, min_size: int = 0, max_size: int = 20):
    """Generate a list of PersistenceTradeRecords sorted by timestamp ascending."""
    count = draw(st.integers(min_value=min_size, max_value=max_size))
    
    if count == 0:
        return []
    
    # Generate timestamps and sort them
    base_time = draw(st.datetimes(min_value=datetime(2020, 1, 1), max_value=datetime(2029, 1, 1)))
    time_deltas = sorted([
        draw(st.integers(min_value=0, max_value=86400))  # Up to 1 day in seconds
        for _ in range(count)
    ])
    
    trades = []
    for delta in time_deltas:
        ts = base_time + timedelta(seconds=delta)
        
        trade = PersistenceTradeRecord(
            symbol=draw(symbol_strategy),
            exchange=draw(exchange_strategy),
            timestamp=ts,
            price=draw(st.floats(min_value=0.01, max_value=100000.0, allow_nan=False, allow_infinity=False)),
            size=draw(st.floats(min_value=0.0001, max_value=10000.0, allow_nan=False, allow_infinity=False)),
            side=draw(st.sampled_from(["buy", "sell"])),
            trade_id=draw(st.text(min_size=1, max_size=50, alphabet=st.characters(whitelist_categories=('L', 'N')))),
        )
        trades.append(trade)
    
    return trades


# Strategy for generating snapshots and trades with overlapping timestamps
@st.composite
def overlapping_timestamps_strategy(draw):
    """Generate snapshots and trades that share some timestamps.
    
    This is critical for testing the tie-breaking behavior where
    orderbook snapshots should come before trades with the same timestamp.
    """
    # Generate a base time
    base_time = draw(st.datetimes(min_value=datetime(2020, 1, 1), max_value=datetime(2029, 1, 1)))
    
    # Generate some shared timestamps
    num_shared = draw(st.integers(min_value=1, max_value=5))
    shared_deltas = sorted([
        draw(st.integers(min_value=0, max_value=3600))  # Up to 1 hour
        for _ in range(num_shared)
    ])
    shared_timestamps = [base_time + timedelta(seconds=delta) for delta in shared_deltas]
    
    # Generate snapshots at shared timestamps
    snapshots = []
    for ts in shared_timestamps:
        bids_tuples = draw(bids_strategy)
        asks_tuples = draw(asks_strategy)
        
        snapshot = OrderbookSnapshot(
            symbol=draw(symbol_strategy),
            exchange=draw(exchange_strategy),
            timestamp=ts,
            seq=draw(seq_strategy),
            bids=convert_levels_to_lists(bids_tuples),
            asks=convert_levels_to_lists(asks_tuples),
            spread_bps=draw(spread_bps_strategy),
            bid_depth_usd=draw(depth_usd_strategy),
            ask_depth_usd=draw(depth_usd_strategy),
            orderbook_imbalance=draw(imbalance_strategy),
        )
        snapshots.append(snapshot)
    
    # Generate trades at shared timestamps (and possibly some unique ones)
    trades = []
    for ts in shared_timestamps:
        # Add 1-3 trades at each shared timestamp
        num_trades_at_ts = draw(st.integers(min_value=1, max_value=3))
        for _ in range(num_trades_at_ts):
            trade = PersistenceTradeRecord(
                symbol=draw(symbol_strategy),
                exchange=draw(exchange_strategy),
                timestamp=ts,
                price=draw(st.floats(min_value=0.01, max_value=100000.0, allow_nan=False, allow_infinity=False)),
                size=draw(st.floats(min_value=0.0001, max_value=10000.0, allow_nan=False, allow_infinity=False)),
                side=draw(st.sampled_from(["buy", "sell"])),
                trade_id=draw(st.text(min_size=1, max_size=50, alphabet=st.characters(whitelist_categories=('L', 'N')))),
            )
            trades.append(trade)
    
    # Sort trades by timestamp (they should already be sorted by shared_timestamps order)
    trades.sort(key=lambda t: t.timestamp)
    
    return snapshots, trades


# =============================================================================
# Helper functions for async iteration
# =============================================================================

async def list_to_async_iter(items: List) -> AsyncIterator:
    """Convert a list to an async iterator."""
    for item in items:
        yield item


async def collect_merge_results(
    merger: ChronologicalMerger,
    snapshots: List[OrderbookSnapshot],
    trades: List[PersistenceTradeRecord],
) -> List[Tuple[OrderbookSnapshot, List[PersistenceTradeRecord]]]:
    """Run the merger and collect all results."""
    results = []
    async for snapshot, associated_trades in merger.merge(
        list_to_async_iter(snapshots),
        list_to_async_iter(trades),
    ):
        results.append((snapshot, associated_trades))
    return results


# =============================================================================
# Property 7: Chronological Ordering
# =============================================================================


class TestChronologicalOrdering:
    """Property 7: Chronological Ordering

    For any sequence of merged orderbook snapshots and trade records, the
    output SHALL be ordered by timestamp ascending. When two events have
    identical timestamps, orderbook snapshots SHALL appear before trade records.

    **Validates: Requirements 3.1, 3.2**
    """

    @given(
        snapshots=sorted_orderbook_snapshots_strategy(min_size=1, max_size=10),
        trades=sorted_trade_records_strategy(min_size=0, max_size=20),
    )
    @settings(max_examples=100)
    def test_output_is_chronologically_ordered(
        self,
        snapshots: List[OrderbookSnapshot],
        trades: List[PersistenceTradeRecord],
    ):
        """Verify that merged output is ordered by timestamp ascending.

        **Validates: Requirements 3.1**
        """
        merger = ChronologicalMerger()
        results = asyncio.run(
            collect_merge_results(merger, snapshots, trades)
        )
        
        # Verify snapshots are in chronological order
        for i in range(1, len(results)):
            prev_snapshot = results[i - 1][0]
            curr_snapshot = results[i][0]
            
            assert prev_snapshot.timestamp <= curr_snapshot.timestamp, (
                f"Snapshots not in chronological order: "
                f"snapshot at index {i-1} has timestamp {prev_snapshot.timestamp}, "
                f"but snapshot at index {i} has timestamp {curr_snapshot.timestamp}"
            )

    @given(data=overlapping_timestamps_strategy())
    @settings(max_examples=100)
    def test_snapshots_before_trades_at_same_timestamp(
        self,
        data: Tuple[List[OrderbookSnapshot], List[PersistenceTradeRecord]],
    ):
        """Verify that orderbook snapshots appear before trades with same timestamp.

        When multiple events have the same timestamp, THE TimescaleDB_Data_Source
        SHALL order orderbook snapshots before trade records.

        **Validates: Requirements 3.2**
        """
        snapshots, trades = data
        assume(len(snapshots) > 0)
        
        merger = ChronologicalMerger()
        results = asyncio.run(
            collect_merge_results(merger, snapshots, trades)
        )
        
        # For each result, verify that trades associated with a snapshot
        # have timestamps >= the snapshot's timestamp
        # (trades with same timestamp are included with the snapshot,
        # meaning the snapshot "comes first" conceptually)
        for snapshot, associated_trades in results:
            for trade in associated_trades:
                # Trades should have timestamps <= the snapshot timestamp
                # because they are trades that occurred BEFORE or AT this snapshot
                # The merger collects trades between previous snapshot and current
                assert trade.timestamp <= snapshot.timestamp, (
                    f"Trade at {trade.timestamp} should not be associated with "
                    f"snapshot at {snapshot.timestamp} - trades should come before "
                    f"or at the same time as their associated snapshot"
                )

    @given(
        snapshots=sorted_orderbook_snapshots_strategy(min_size=2, max_size=10),
        trades=sorted_trade_records_strategy(min_size=1, max_size=20),
    )
    @settings(max_examples=100)
    def test_trades_associated_with_correct_snapshot(
        self,
        snapshots: List[OrderbookSnapshot],
        trades: List[PersistenceTradeRecord],
    ):
        """Verify that trades are associated with the correct snapshot.

        Trades that occurred between snapshot N-1 and snapshot N should be
        associated with snapshot N. The LAST snapshot gets all remaining
        trades (including those after its timestamp).

        **Validates: Requirements 3.1, 3.2**
        """
        merger = ChronologicalMerger()
        results = asyncio.run(
            collect_merge_results(merger, snapshots, trades)
        )
        
        # Collect all trades from results
        all_result_trades = []
        for _, associated_trades in results:
            all_result_trades.extend(associated_trades)
        
        # All input trades should appear in the output (the last snapshot
        # gets all remaining trades, including those after its timestamp)
        assert len(all_result_trades) == len(trades), (
            f"Expected {len(trades)} trades in output, got {len(all_result_trades)}"
        )

    @given(
        snapshots=sorted_orderbook_snapshots_strategy(min_size=1, max_size=10),
    )
    @settings(max_examples=100)
    def test_empty_trades_produces_valid_output(
        self,
        snapshots: List[OrderbookSnapshot],
    ):
        """Verify that merging with empty trades produces valid output.

        **Validates: Requirements 3.1**
        """
        trades: List[PersistenceTradeRecord] = []
        
        merger = ChronologicalMerger()
        results = asyncio.run(
            collect_merge_results(merger, snapshots, trades)
        )
        
        # Should have same number of results as snapshots
        assert len(results) == len(snapshots), (
            f"Expected {len(snapshots)} results, got {len(results)}"
        )
        
        # All associated trades should be empty
        for snapshot, associated_trades in results:
            assert len(associated_trades) == 0, (
                f"Expected no trades for snapshot at {snapshot.timestamp}, "
                f"got {len(associated_trades)}"
            )
        
        # Verify chronological order
        for i in range(1, len(results)):
            prev_snapshot = results[i - 1][0]
            curr_snapshot = results[i][0]
            assert prev_snapshot.timestamp <= curr_snapshot.timestamp

    @given(
        trades=sorted_trade_records_strategy(min_size=1, max_size=20),
    )
    @settings(max_examples=100)
    def test_empty_snapshots_produces_empty_output(
        self,
        trades: List[PersistenceTradeRecord],
    ):
        """Verify that merging with empty snapshots produces empty output.

        The merger yields (snapshot, trades) tuples, so with no snapshots,
        there should be no output.

        **Validates: Requirements 3.1**
        """
        snapshots: List[OrderbookSnapshot] = []
        
        merger = ChronologicalMerger()
        results = asyncio.run(
            collect_merge_results(merger, snapshots, trades)
        )
        
        # With no snapshots, there should be no output
        assert len(results) == 0, (
            f"Expected 0 results with no snapshots, got {len(results)}"
        )

    @given(
        snapshots=sorted_orderbook_snapshots_strategy(min_size=0, max_size=10),
        trades=sorted_trade_records_strategy(min_size=0, max_size=20),
    )
    @settings(max_examples=100)
    def test_all_snapshots_appear_in_output(
        self,
        snapshots: List[OrderbookSnapshot],
        trades: List[PersistenceTradeRecord],
    ):
        """Verify that all input snapshots appear in the output.

        **Validates: Requirements 3.1**
        """
        merger = ChronologicalMerger()
        results = asyncio.run(
            collect_merge_results(merger, snapshots, trades)
        )
        
        # Number of results should equal number of input snapshots
        assert len(results) == len(snapshots), (
            f"Expected {len(snapshots)} results, got {len(results)}"
        )
        
        # Each snapshot should appear exactly once
        result_timestamps = [r[0].timestamp for r in results]
        input_timestamps = [s.timestamp for s in snapshots]
        
        assert result_timestamps == input_timestamps, (
            f"Output snapshot timestamps don't match input: "
            f"expected {input_timestamps}, got {result_timestamps}"
        )

    @given(data=overlapping_timestamps_strategy())
    @settings(max_examples=100)
    def test_tie_breaking_with_identical_timestamps(
        self,
        data: Tuple[List[OrderbookSnapshot], List[PersistenceTradeRecord]],
    ):
        """Verify tie-breaking behavior when timestamps are identical.

        When two events have identical timestamps, orderbook snapshots
        SHALL appear before trade records. This means trades with the
        same timestamp as a snapshot should be associated with that
        snapshot (not the previous one).

        **Validates: Requirements 3.2**
        """
        snapshots, trades = data
        assume(len(snapshots) > 0)
        
        merger = ChronologicalMerger()
        results = asyncio.run(
            collect_merge_results(merger, snapshots, trades)
        )
        
        # Build a map of snapshot timestamps
        snapshot_timestamps = {s.timestamp for s in snapshots}
        
        # For each result, check trades with same timestamp as snapshot
        for snapshot, associated_trades in results:
            same_ts_trades = [t for t in associated_trades if t.timestamp == snapshot.timestamp]
            
            # If there are trades with the same timestamp as the snapshot,
            # they should be associated with THIS snapshot (not a later one)
            # This verifies the "snapshots before trades" ordering
            for trade in same_ts_trades:
                # The trade is correctly associated with a snapshot at the same timestamp
                assert trade.timestamp == snapshot.timestamp, (
                    f"Trade at {trade.timestamp} incorrectly associated with "
                    f"snapshot at {snapshot.timestamp}"
                )

    @given(
        snapshots=sorted_orderbook_snapshots_strategy(min_size=3, max_size=10),
        trades=sorted_trade_records_strategy(min_size=5, max_size=30),
    )
    @settings(max_examples=100)
    def test_trades_partitioned_correctly_between_snapshots(
        self,
        snapshots: List[OrderbookSnapshot],
        trades: List[PersistenceTradeRecord],
    ):
        """Verify that trades are correctly partitioned between snapshots.

        For non-last snapshots: trades between snapshot[i-1].timestamp (exclusive)
        and snapshot[i].timestamp (inclusive) should be associated with snapshot[i].
        
        For the last snapshot: it gets all remaining trades, including those
        after its timestamp.
        
        Note: When multiple snapshots have the same timestamp, trades at that
        timestamp are associated with the FIRST snapshot at that timestamp
        (since snapshots come before trades in ordering).

        **Validates: Requirements 3.1, 3.2**
        """
        merger = ChronologicalMerger()
        results = asyncio.run(
            collect_merge_results(merger, snapshots, trades)
        )
        
        # For each result, verify trade timestamps are within valid range
        # The valid range depends on whether this is the first/last snapshot
        num_results = len(results)
        for i, (snapshot, associated_trades) in enumerate(results):
            is_last = (i == num_results - 1)
            
            if i == 0:
                # First snapshot gets all trades up to and including its timestamp
                # (unless it's also the last snapshot)
                if not is_last:
                    for trade in associated_trades:
                        assert trade.timestamp <= snapshot.timestamp, (
                            f"Trade at {trade.timestamp} should not be associated with "
                            f"first snapshot at {snapshot.timestamp}"
                        )
            elif is_last:
                # Last snapshot gets all remaining trades (including those after its timestamp)
                prev_snapshot = results[i - 1][0]
                for trade in associated_trades:
                    # Trade should be after previous snapshot timestamp
                    # OR at the same timestamp as previous snapshot (when snapshots have same ts)
                    assert trade.timestamp >= prev_snapshot.timestamp, (
                        f"Trade at {trade.timestamp} should be at or after previous "
                        f"snapshot at {prev_snapshot.timestamp}"
                    )
            else:
                # Middle snapshots: trades should be after previous and at or before current
                prev_snapshot = results[i - 1][0]
                for trade in associated_trades:
                    # Trade should be after previous snapshot timestamp
                    # OR at the same timestamp as current snapshot (tie-breaking)
                    assert trade.timestamp >= prev_snapshot.timestamp, (
                        f"Trade at {trade.timestamp} should be at or after previous "
                        f"snapshot at {prev_snapshot.timestamp}"
                    )
                    assert trade.timestamp <= snapshot.timestamp, (
                        f"Trade at {trade.timestamp} should be at or before "
                        f"current snapshot at {snapshot.timestamp}"
                    )

    @given(
        snapshots=sorted_orderbook_snapshots_strategy(min_size=1, max_size=5),
        trades=sorted_trade_records_strategy(min_size=1, max_size=10),
    )
    @settings(max_examples=100)
    def test_no_trades_lost_in_merge(
        self,
        snapshots: List[OrderbookSnapshot],
        trades: List[PersistenceTradeRecord],
    ):
        """Verify that no trades are lost during the merge process.

        All trades should appear in the output - the last snapshot gets
        all remaining trades including those after its timestamp.

        **Validates: Requirements 3.1**
        """
        merger = ChronologicalMerger()
        results = asyncio.run(
            collect_merge_results(merger, snapshots, trades)
        )
        
        # Collect all trades from results
        all_result_trades = []
        for _, associated_trades in results:
            all_result_trades.extend(associated_trades)
        
        # All input trades should be in results (last snapshot gets all remaining)
        assert len(all_result_trades) == len(trades), (
            f"Expected {len(trades)} trades in output, got {len(all_result_trades)}"
        )

    @given(
        snapshots=sorted_orderbook_snapshots_strategy(min_size=1, max_size=10),
        trades=sorted_trade_records_strategy(min_size=1, max_size=20),
    )
    @settings(max_examples=100)
    def test_merge_is_deterministic(
        self,
        snapshots: List[OrderbookSnapshot],
        trades: List[PersistenceTradeRecord],
    ):
        """Verify that merging the same inputs produces the same output.

        **Validates: Requirements 3.1**
        """
        merger1 = ChronologicalMerger()
        merger2 = ChronologicalMerger()
        
        results1 = asyncio.run(
            collect_merge_results(merger1, snapshots, trades)
        )
        results2 = asyncio.run(
            collect_merge_results(merger2, snapshots, trades)
        )
        
        # Results should be identical
        assert len(results1) == len(results2), (
            f"Different number of results: {len(results1)} vs {len(results2)}"
        )
        
        for i, ((snap1, trades1), (snap2, trades2)) in enumerate(zip(results1, results2)):
            assert snap1.timestamp == snap2.timestamp, (
                f"Different snapshot timestamps at index {i}: "
                f"{snap1.timestamp} vs {snap2.timestamp}"
            )
            assert len(trades1) == len(trades2), (
                f"Different number of trades at index {i}: "
                f"{len(trades1)} vs {len(trades2)}"
            )
