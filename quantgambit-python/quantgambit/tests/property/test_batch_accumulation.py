"""Property-based tests for batch accumulation.

Feature: live-orderbook-data-storage, Property 6: Batch Accumulation

Tests that the writer's buffer accumulates records until either:
(a) the buffer size reaches batch_size, or
(b) the flush_interval elapses.
Upon either condition, all buffered records SHALL be flushed together.

**Validates: Requirements 1.6, 2.5**
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import List, Tuple
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hypothesis import given, strategies as st, settings, assume

from quantgambit.market.orderbooks import OrderbookState
from quantgambit.storage.orderbook_snapshot_writer import OrderbookSnapshotWriter
from quantgambit.storage.persistence import OrderbookSnapshotWriterConfig


# =============================================================================
# Strategies for generating test data
# =============================================================================

# Batch size configuration (small values for testing)
batch_size = st.integers(min_value=2, max_value=50)

# Flush interval configuration (0.1 to 5 seconds)
flush_interval = st.floats(min_value=0.1, max_value=5.0, allow_nan=False, allow_infinity=False)

# Timestamp generator (realistic Unix timestamps)
timestamp = st.floats(min_value=1600000000.0, max_value=2000000000.0, allow_nan=False, allow_infinity=False)

# Symbol generator
symbol = st.sampled_from(["BTC/USDT", "ETH/USDT", "SOL/USDT", "DOGE/USDT", "XRP/USDT"])

# Exchange generator
exchange = st.sampled_from(["binance", "coinbase", "kraken", "okx", "bybit"])

# Orderbook level generator - price and size pairs
orderbook_level = st.tuples(
    st.floats(min_value=0.01, max_value=100000.0, allow_nan=False, allow_infinity=False),  # price
    st.floats(min_value=0.0001, max_value=10000.0, allow_nan=False, allow_infinity=False),  # size
)

# Non-empty orderbook levels (at least 1 level, up to 20)
non_empty_orderbook_levels = st.lists(orderbook_level, min_size=1, max_size=20)

# Sequence number generator
sequence_number = st.integers(min_value=1, max_value=1000000)

# Number of records to add (for testing accumulation)
num_records = st.integers(min_value=1, max_value=100)


def create_valid_orderbook_state(symbol: str, bids: List[Tuple[float, float]], asks: List[Tuple[float, float]], seq: int) -> OrderbookState:
    """Create a valid OrderbookState from bid/ask tuples."""
    state = OrderbookState(symbol=symbol)
    bids_list = [[p, s] for p, s in bids]
    asks_list = [[p, s] for p, s in asks]
    state.apply_snapshot(bids=bids_list, asks=asks_list, seq=seq)
    return state


def create_mock_pool():
    """Create a mock asyncpg pool for testing."""
    pool = MagicMock()
    conn = AsyncMock()
    conn.executemany = AsyncMock()
    pool.acquire = MagicMock(return_value=AsyncMock(__aenter__=AsyncMock(return_value=conn), __aexit__=AsyncMock()))
    return pool


# =============================================================================
# Property 6: Batch Accumulation
# =============================================================================

class TestBatchAccumulation:
    """Property 6: Batch Accumulation
    
    For any sequence of records added to a writer's buffer, the buffer SHALL
    accumulate records until either: (a) the buffer size reaches batch_size,
    or (b) the flush_interval elapses. Upon either condition, all buffered
    records SHALL be flushed together.
    
    **Validates: Requirements 1.6, 2.5**
    """

    @given(
        batch_sz=batch_size,
        base_timestamp=timestamp,
        bids=non_empty_orderbook_levels,
        asks=non_empty_orderbook_levels,
        seq=sequence_number,
    )
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_buffer_accumulates_until_batch_size(
        self,
        batch_sz: int,
        base_timestamp: float,
        bids: List[Tuple[float, float]],
        asks: List[Tuple[float, float]],
        seq: int,
    ):
        """Verify that buffer accumulates records until batch_size is reached.
        
        Records should accumulate in the buffer without being flushed until
        the buffer size reaches the configured batch_size.
        
        **Validates: Requirements 1.6**
        """
        pool = create_mock_pool()
        config = OrderbookSnapshotWriterConfig(
            enabled=True,
            snapshot_interval_sec=0.0,  # No throttling for this test
            batch_size=batch_sz,
            flush_interval_sec=1000.0,  # Very long to avoid time-based flush
        )
        writer = OrderbookSnapshotWriter(pool, config)
        
        state = create_valid_orderbook_state("BTC/USDT", bids, asks, seq)
        
        # Add records up to batch_size - 1 (should not trigger flush)
        for i in range(batch_sz - 1):
            await writer.maybe_capture(
                symbol="BTC/USDT",
                exchange="binance",
                state=state,
                timestamp=base_timestamp + i,
                seq=seq + i,
            )
        
        # Buffer should have accumulated all records
        assert writer.get_buffer_size() == batch_sz - 1, (
            f"Buffer should accumulate {batch_sz - 1} records before batch_size. "
            f"Actual buffer size: {writer.get_buffer_size()}"
        )

    @given(
        batch_sz=batch_size,
        base_timestamp=timestamp,
        bids=non_empty_orderbook_levels,
        asks=non_empty_orderbook_levels,
        seq=sequence_number,
    )
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_flush_triggered_at_batch_size(
        self,
        batch_sz: int,
        base_timestamp: float,
        bids: List[Tuple[float, float]],
        asks: List[Tuple[float, float]],
        seq: int,
    ):
        """Verify that flush is triggered when batch_size is reached.
        
        When the buffer size reaches batch_size, a flush should be triggered
        and all buffered records should be flushed together.
        
        **Validates: Requirements 1.6**
        """
        pool = create_mock_pool()
        config = OrderbookSnapshotWriterConfig(
            enabled=True,
            snapshot_interval_sec=0.0,  # No throttling for this test
            batch_size=batch_sz,
            flush_interval_sec=1000.0,  # Very long to avoid time-based flush
        )
        writer = OrderbookSnapshotWriter(pool, config)
        
        state = create_valid_orderbook_state("BTC/USDT", bids, asks, seq)
        
        # Add exactly batch_size records
        for i in range(batch_sz):
            await writer.maybe_capture(
                symbol="BTC/USDT",
                exchange="binance",
                state=state,
                timestamp=base_timestamp + i,
                seq=seq + i,
            )
        
        # Give async task time to complete
        await asyncio.sleep(0.01)
        
        # Buffer should be empty after flush (or have only new records)
        # The flush is triggered asynchronously, so buffer should be cleared
        assert writer.get_buffer_size() == 0, (
            f"Buffer should be empty after batch_size flush. "
            f"Batch size: {batch_sz}, Buffer size: {writer.get_buffer_size()}"
        )

    @given(
        batch_sz=batch_size,
        num_recs=num_records,
        base_timestamp=timestamp,
        bids=non_empty_orderbook_levels,
        asks=non_empty_orderbook_levels,
        seq=sequence_number,
    )
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_all_records_flushed_together(
        self,
        batch_sz: int,
        num_recs: int,
        base_timestamp: float,
        bids: List[Tuple[float, float]],
        asks: List[Tuple[float, float]],
        seq: int,
    ):
        """Verify that all buffered records are flushed together.
        
        When a flush is triggered (either by batch_size or manual flush),
        all records in the buffer should be flushed in a single batch operation.
        
        **Validates: Requirements 1.6, 2.5**
        """
        # Ensure we don't trigger automatic flush during accumulation
        assume(num_recs < batch_sz)
        
        pool = create_mock_pool()
        config = OrderbookSnapshotWriterConfig(
            enabled=True,
            snapshot_interval_sec=0.0,  # No throttling for this test
            batch_size=batch_sz,
            flush_interval_sec=1000.0,  # Very long to avoid time-based flush
        )
        writer = OrderbookSnapshotWriter(pool, config)
        
        state = create_valid_orderbook_state("BTC/USDT", bids, asks, seq)
        
        # Add records
        for i in range(num_recs):
            await writer.maybe_capture(
                symbol="BTC/USDT",
                exchange="binance",
                state=state,
                timestamp=base_timestamp + i,
                seq=seq + i,
            )
        
        # Verify buffer has accumulated records
        assert writer.get_buffer_size() == num_recs
        
        # Manually flush
        flushed_count = await writer.flush()
        
        # All records should be flushed together
        assert flushed_count == num_recs, (
            f"All {num_recs} records should be flushed together. "
            f"Actually flushed: {flushed_count}"
        )
        
        # Buffer should be empty after flush
        assert writer.get_buffer_size() == 0, (
            f"Buffer should be empty after flush. "
            f"Buffer size: {writer.get_buffer_size()}"
        )

    @given(
        batch_sz=batch_size,
        base_timestamp=timestamp,
        bids=non_empty_orderbook_levels,
        asks=non_empty_orderbook_levels,
        seq=sequence_number,
    )
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_multiple_batch_flushes(
        self,
        batch_sz: int,
        base_timestamp: float,
        bids: List[Tuple[float, float]],
        asks: List[Tuple[float, float]],
        seq: int,
    ):
        """Verify that multiple batches are flushed correctly.
        
        When adding more records than batch_size, multiple flushes should
        occur, each flushing exactly batch_size records.
        
        **Validates: Requirements 1.6**
        """
        pool = create_mock_pool()
        config = OrderbookSnapshotWriterConfig(
            enabled=True,
            snapshot_interval_sec=0.0,  # No throttling for this test
            batch_size=batch_sz,
            flush_interval_sec=1000.0,  # Very long to avoid time-based flush
        )
        writer = OrderbookSnapshotWriter(pool, config)
        
        state = create_valid_orderbook_state("BTC/USDT", bids, asks, seq)
        
        # Add 2 * batch_size records
        total_records = 2 * batch_sz
        for i in range(total_records):
            await writer.maybe_capture(
                symbol="BTC/USDT",
                exchange="binance",
                state=state,
                timestamp=base_timestamp + i,
                seq=seq + i,
            )
            # Give async tasks time to complete after each batch
            if (i + 1) % batch_sz == 0:
                await asyncio.sleep(0.01)
        
        # After 2 batches, buffer should be empty
        await asyncio.sleep(0.01)
        assert writer.get_buffer_size() == 0, (
            f"Buffer should be empty after 2 batch flushes. "
            f"Buffer size: {writer.get_buffer_size()}"
        )

    @given(
        batch_sz=batch_size,
        extra_records=st.integers(min_value=1, max_value=10),
        base_timestamp=timestamp,
        bids=non_empty_orderbook_levels,
        asks=non_empty_orderbook_levels,
        seq=sequence_number,
    )
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_partial_batch_after_full_flush(
        self,
        batch_sz: int,
        extra_records: int,
        base_timestamp: float,
        bids: List[Tuple[float, float]],
        asks: List[Tuple[float, float]],
        seq: int,
    ):
        """Verify partial batch remains in buffer after full batch flush.
        
        When adding batch_size records (triggering flush), then adding N more
        records, those N records should remain in the buffer until the next
        flush condition is met.
        
        **Validates: Requirements 1.6**
        """
        # Ensure extra_records is less than batch_size
        assume(extra_records < batch_sz)
        
        pool = create_mock_pool()
        config = OrderbookSnapshotWriterConfig(
            enabled=True,
            snapshot_interval_sec=0.0,  # No throttling for this test
            batch_size=batch_sz,
            flush_interval_sec=1000.0,  # Very long to avoid time-based flush
        )
        writer = OrderbookSnapshotWriter(pool, config)
        
        state = create_valid_orderbook_state("BTC/USDT", bids, asks, seq)
        
        # First, add exactly batch_size records to trigger flush
        for i in range(batch_sz):
            await writer.maybe_capture(
                symbol="BTC/USDT",
                exchange="binance",
                state=state,
                timestamp=base_timestamp + i,
                seq=seq + i,
            )
        
        # Wait for the async flush to complete
        await asyncio.sleep(0.02)
        
        # Buffer should be empty after batch flush
        assert writer.get_buffer_size() == 0, (
            f"Buffer should be empty after batch flush. "
            f"Buffer size: {writer.get_buffer_size()}"
        )
        
        # Now add extra_records (should accumulate without flush)
        for i in range(extra_records):
            await writer.maybe_capture(
                symbol="BTC/USDT",
                exchange="binance",
                state=state,
                timestamp=base_timestamp + batch_sz + i,
                seq=seq + batch_sz + i,
            )
        
        # Buffer should have extra_records remaining (no flush triggered)
        assert writer.get_buffer_size() == extra_records, (
            f"Buffer should have {extra_records} records after adding more. "
            f"Batch size: {batch_sz}, Extra added: {extra_records}, "
            f"Buffer size: {writer.get_buffer_size()}"
        )

    @given(
        batch_sz=batch_size,
        base_timestamp=timestamp,
        bids=non_empty_orderbook_levels,
        asks=non_empty_orderbook_levels,
        seq=sequence_number,
    )
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_empty_buffer_flush_returns_zero(
        self,
        batch_sz: int,
        base_timestamp: float,
        bids: List[Tuple[float, float]],
        asks: List[Tuple[float, float]],
        seq: int,
    ):
        """Verify that flushing an empty buffer returns zero.
        
        When flush is called on an empty buffer, it should return 0
        and not perform any database operations.
        
        **Validates: Requirements 1.6**
        """
        pool = create_mock_pool()
        config = OrderbookSnapshotWriterConfig(
            enabled=True,
            snapshot_interval_sec=0.0,
            batch_size=batch_sz,
            flush_interval_sec=1000.0,
        )
        writer = OrderbookSnapshotWriter(pool, config)
        
        # Flush empty buffer
        flushed_count = await writer.flush()
        
        assert flushed_count == 0, (
            f"Flushing empty buffer should return 0. "
            f"Returned: {flushed_count}"
        )
        assert writer.get_buffer_size() == 0

    @given(
        batch_sz=batch_size,
        num_recs=st.integers(min_value=1, max_value=20),
        base_timestamp=timestamp,
        bids=non_empty_orderbook_levels,
        asks=non_empty_orderbook_levels,
        seq=sequence_number,
    )
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_manual_flush_clears_buffer(
        self,
        batch_sz: int,
        num_recs: int,
        base_timestamp: float,
        bids: List[Tuple[float, float]],
        asks: List[Tuple[float, float]],
        seq: int,
    ):
        """Verify that manual flush clears the entire buffer.
        
        Calling flush() manually should clear all records from the buffer,
        regardless of whether batch_size has been reached.
        
        **Validates: Requirements 1.6, 2.5**
        """
        # Ensure we don't trigger automatic flush
        assume(num_recs < batch_sz)
        
        pool = create_mock_pool()
        config = OrderbookSnapshotWriterConfig(
            enabled=True,
            snapshot_interval_sec=0.0,
            batch_size=batch_sz,
            flush_interval_sec=1000.0,
        )
        writer = OrderbookSnapshotWriter(pool, config)
        
        state = create_valid_orderbook_state("BTC/USDT", bids, asks, seq)
        
        # Add records
        for i in range(num_recs):
            await writer.maybe_capture(
                symbol="BTC/USDT",
                exchange="binance",
                state=state,
                timestamp=base_timestamp + i,
                seq=seq + i,
            )
        
        # Verify buffer has records
        assert writer.get_buffer_size() == num_recs
        
        # Manual flush
        await writer.flush()
        
        # Buffer should be empty
        assert writer.get_buffer_size() == 0, (
            f"Buffer should be empty after manual flush. "
            f"Buffer size: {writer.get_buffer_size()}"
        )

    @given(
        batch_sz=batch_size,
        num_symbols=st.integers(min_value=2, max_value=5),
        records_per_symbol=st.integers(min_value=1, max_value=10),
        base_timestamp=timestamp,
        bids=non_empty_orderbook_levels,
        asks=non_empty_orderbook_levels,
        seq=sequence_number,
    )
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_buffer_accumulates_across_symbols(
        self,
        batch_sz: int,
        num_symbols: int,
        records_per_symbol: int,
        base_timestamp: float,
        bids: List[Tuple[float, float]],
        asks: List[Tuple[float, float]],
        seq: int,
    ):
        """Verify that buffer accumulates records from multiple symbols.
        
        Records from different symbols should all accumulate in the same
        buffer and be flushed together when batch_size is reached.
        
        **Validates: Requirements 1.6**
        """
        total_records = num_symbols * records_per_symbol
        # Ensure we don't trigger automatic flush
        assume(total_records < batch_sz)
        
        pool = create_mock_pool()
        config = OrderbookSnapshotWriterConfig(
            enabled=True,
            snapshot_interval_sec=0.0,
            batch_size=batch_sz,
            flush_interval_sec=1000.0,
        )
        writer = OrderbookSnapshotWriter(pool, config)
        
        symbols = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "DOGE/USDT", "XRP/USDT"][:num_symbols]
        
        # Add records for each symbol
        record_count = 0
        for sym in symbols:
            state = create_valid_orderbook_state(sym, bids, asks, seq)
            for i in range(records_per_symbol):
                await writer.maybe_capture(
                    symbol=sym,
                    exchange="binance",
                    state=state,
                    timestamp=base_timestamp + record_count,
                    seq=seq + record_count,
                )
                record_count += 1
        
        # Buffer should have all records
        assert writer.get_buffer_size() == total_records, (
            f"Buffer should accumulate records from all symbols. "
            f"Expected: {total_records}, Actual: {writer.get_buffer_size()}"
        )
        
        # Flush and verify all records are flushed together
        flushed_count = await writer.flush()
        assert flushed_count == total_records, (
            f"All records from all symbols should be flushed together. "
            f"Expected: {total_records}, Flushed: {flushed_count}"
        )

    @given(
        batch_sz=batch_size,
        base_timestamp=timestamp,
        bids=non_empty_orderbook_levels,
        asks=non_empty_orderbook_levels,
        seq=sequence_number,
    )
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_buffer_size_exactly_at_batch_size(
        self,
        batch_sz: int,
        base_timestamp: float,
        bids: List[Tuple[float, float]],
        asks: List[Tuple[float, float]],
        seq: int,
    ):
        """Verify flush is triggered exactly when buffer reaches batch_size.
        
        The flush should be triggered when the buffer size equals batch_size,
        not before or after.
        
        **Validates: Requirements 1.6**
        """
        pool = create_mock_pool()
        config = OrderbookSnapshotWriterConfig(
            enabled=True,
            snapshot_interval_sec=0.0,
            batch_size=batch_sz,
            flush_interval_sec=1000.0,
        )
        writer = OrderbookSnapshotWriter(pool, config)
        
        state = create_valid_orderbook_state("BTC/USDT", bids, asks, seq)
        
        # Add batch_size - 1 records
        for i in range(batch_sz - 1):
            await writer.maybe_capture(
                symbol="BTC/USDT",
                exchange="binance",
                state=state,
                timestamp=base_timestamp + i,
                seq=seq + i,
            )
        
        # Buffer should have batch_size - 1 records (no flush yet)
        assert writer.get_buffer_size() == batch_sz - 1
        
        # Add one more record to reach batch_size
        await writer.maybe_capture(
            symbol="BTC/USDT",
            exchange="binance",
            state=state,
            timestamp=base_timestamp + batch_sz - 1,
            seq=seq + batch_sz - 1,
        )
        
        # Give async task time to complete
        await asyncio.sleep(0.01)
        
        # Buffer should be empty after flush
        assert writer.get_buffer_size() == 0, (
            f"Buffer should be empty after reaching batch_size. "
            f"Batch size: {batch_sz}, Buffer size: {writer.get_buffer_size()}"
        )

    @given(
        batch_sz=batch_size,
        num_recs=st.integers(min_value=1, max_value=20),
        base_timestamp=timestamp,
        bids=non_empty_orderbook_levels,
        asks=non_empty_orderbook_levels,
        seq=sequence_number,
    )
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_stop_flushes_remaining_buffer(
        self,
        batch_sz: int,
        num_recs: int,
        base_timestamp: float,
        bids: List[Tuple[float, float]],
        asks: List[Tuple[float, float]],
        seq: int,
    ):
        """Verify that stop() flushes any remaining records in the buffer.
        
        When the writer is stopped, any records remaining in the buffer
        should be flushed before shutdown.
        
        **Validates: Requirements 1.6**
        """
        # Ensure we don't trigger automatic flush
        assume(num_recs < batch_sz)
        
        pool = create_mock_pool()
        config = OrderbookSnapshotWriterConfig(
            enabled=True,
            snapshot_interval_sec=0.0,
            batch_size=batch_sz,
            flush_interval_sec=1000.0,
        )
        writer = OrderbookSnapshotWriter(pool, config)
        
        state = create_valid_orderbook_state("BTC/USDT", bids, asks, seq)
        
        # Add records
        for i in range(num_recs):
            await writer.maybe_capture(
                symbol="BTC/USDT",
                exchange="binance",
                state=state,
                timestamp=base_timestamp + i,
                seq=seq + i,
            )
        
        # Verify buffer has records
        assert writer.get_buffer_size() == num_recs
        
        # Stop the writer (should flush remaining records)
        await writer.stop()
        
        # Buffer should be empty after stop
        assert writer.get_buffer_size() == 0, (
            f"Buffer should be empty after stop(). "
            f"Buffer size: {writer.get_buffer_size()}"
        )

    @given(
        batch_sz=batch_size,
        base_timestamp=timestamp,
        bids=non_empty_orderbook_levels,
        asks=non_empty_orderbook_levels,
        seq=sequence_number,
    )
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_concurrent_captures_accumulate_correctly(
        self,
        batch_sz: int,
        base_timestamp: float,
        bids: List[Tuple[float, float]],
        asks: List[Tuple[float, float]],
        seq: int,
    ):
        """Verify that concurrent captures accumulate correctly in the buffer.
        
        When multiple captures happen concurrently, all records should be
        accumulated in the buffer without loss.
        
        **Validates: Requirements 1.6**
        """
        num_concurrent = min(batch_sz - 1, 10)  # Ensure we don't trigger flush
        
        pool = create_mock_pool()
        config = OrderbookSnapshotWriterConfig(
            enabled=True,
            snapshot_interval_sec=0.0,
            batch_size=batch_sz,
            flush_interval_sec=1000.0,
        )
        writer = OrderbookSnapshotWriter(pool, config)
        
        # Create tasks for concurrent captures
        async def capture_task(i: int):
            state = create_valid_orderbook_state(f"SYM{i}/USDT", bids, asks, seq)
            await writer.maybe_capture(
                symbol=f"SYM{i}/USDT",
                exchange="binance",
                state=state,
                timestamp=base_timestamp + i,
                seq=seq + i,
            )
        
        # Run captures concurrently
        await asyncio.gather(*[capture_task(i) for i in range(num_concurrent)])
        
        # All records should be in the buffer
        assert writer.get_buffer_size() == num_concurrent, (
            f"All concurrent captures should be in buffer. "
            f"Expected: {num_concurrent}, Actual: {writer.get_buffer_size()}"
        )

    @given(
        num_recs=st.integers(min_value=1, max_value=10),
        base_timestamp=timestamp,
        bids=non_empty_orderbook_levels,
        asks=non_empty_orderbook_levels,
        seq=sequence_number,
    )
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_background_flush_at_interval(
        self,
        num_recs: int,
        base_timestamp: float,
        bids: List[Tuple[float, float]],
        asks: List[Tuple[float, float]],
        seq: int,
    ):
        """Verify that background flush occurs at flush_interval.
        
        When the background flush task is running, records should be flushed
        when the flush_interval elapses, even if batch_size is not reached.
        
        **Validates: Requirements 1.6, 2.5**
        """
        pool = create_mock_pool()
        config = OrderbookSnapshotWriterConfig(
            enabled=True,
            snapshot_interval_sec=0.0,
            batch_size=1000,  # Very large to avoid batch-triggered flush
            flush_interval_sec=0.05,  # 50ms flush interval for testing
        )
        writer = OrderbookSnapshotWriter(pool, config)
        
        state = create_valid_orderbook_state("BTC/USDT", bids, asks, seq)
        
        # Start background flush task
        await writer.start_background_flush()
        
        try:
            # Add records (less than batch_size)
            for i in range(num_recs):
                await writer.maybe_capture(
                    symbol="BTC/USDT",
                    exchange="binance",
                    state=state,
                    timestamp=base_timestamp + i,
                    seq=seq + i,
                )
            
            # Verify buffer has records
            assert writer.get_buffer_size() == num_recs
            
            # Wait for flush_interval to elapse (plus some margin)
            await asyncio.sleep(0.1)
            
            # Buffer should be empty after interval-based flush
            assert writer.get_buffer_size() == 0, (
                f"Buffer should be empty after flush_interval. "
                f"Buffer size: {writer.get_buffer_size()}"
            )
        finally:
            await writer.stop()

    @given(
        batch_sz=batch_size,
        num_recs=st.integers(min_value=1, max_value=10),
        base_timestamp=timestamp,
        bids=non_empty_orderbook_levels,
        asks=non_empty_orderbook_levels,
        seq=sequence_number,
    )
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_batch_size_flush_before_interval(
        self,
        batch_sz: int,
        num_recs: int,
        base_timestamp: float,
        bids: List[Tuple[float, float]],
        asks: List[Tuple[float, float]],
        seq: int,
    ):
        """Verify that batch_size flush occurs before flush_interval if reached first.
        
        When batch_size is reached before flush_interval elapses, the flush
        should be triggered immediately by the batch_size condition.
        
        **Validates: Requirements 1.6**
        """
        # Ensure we add exactly batch_size records
        pool = create_mock_pool()
        config = OrderbookSnapshotWriterConfig(
            enabled=True,
            snapshot_interval_sec=0.0,
            batch_size=batch_sz,
            flush_interval_sec=1000.0,  # Very long interval
        )
        writer = OrderbookSnapshotWriter(pool, config)
        
        state = create_valid_orderbook_state("BTC/USDT", bids, asks, seq)
        
        # Start background flush task (but interval is very long)
        await writer.start_background_flush()
        
        try:
            # Add exactly batch_size records
            for i in range(batch_sz):
                await writer.maybe_capture(
                    symbol="BTC/USDT",
                    exchange="binance",
                    state=state,
                    timestamp=base_timestamp + i,
                    seq=seq + i,
                )
            
            # Give async task time to complete
            await asyncio.sleep(0.02)
            
            # Buffer should be empty (flushed by batch_size, not interval)
            assert writer.get_buffer_size() == 0, (
                f"Buffer should be empty after batch_size flush. "
                f"Batch size: {batch_sz}, Buffer size: {writer.get_buffer_size()}"
            )
        finally:
            await writer.stop()

