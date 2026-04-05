"""Property-based tests for snapshot interval throttling.

Feature: live-orderbook-data-storage, Property 1: Snapshot Interval Throttling

Tests that the Snapshot_Writer only captures snapshots when the configured
interval has elapsed since the last capture. No two snapshots for the same
symbol should have timestamps closer than the configured interval.

**Validates: Requirements 1.1**
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import List, Tuple
from unittest.mock import AsyncMock, MagicMock

import pytest
from hypothesis import given, strategies as st, settings, assume

from quantgambit.market.orderbooks import OrderbookState
from quantgambit.storage.orderbook_snapshot_writer import OrderbookSnapshotWriter
from quantgambit.storage.persistence import OrderbookSnapshotWriterConfig


# =============================================================================
# Strategies for generating test data
# =============================================================================

# Snapshot interval configuration (0.1 to 10 seconds)
snapshot_interval = st.floats(min_value=0.1, max_value=10.0, allow_nan=False, allow_infinity=False)

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

# Time delta generator for updates (0 to 30 seconds)
time_delta = st.floats(min_value=0.0, max_value=30.0, allow_nan=False, allow_infinity=False)


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
# Property 1: Snapshot Interval Throttling
# =============================================================================

class TestSnapshotIntervalThrottling:
    """Property 1: Snapshot Interval Throttling
    
    For any sequence of orderbook updates with timestamps, the Snapshot_Writer
    SHALL only capture snapshots when the configured interval has elapsed since
    the last capture. No two snapshots for the same symbol should have timestamps
    closer than the configured interval.
    
    **Validates: Requirements 1.1**
    """

    @given(
        interval_sec=snapshot_interval,
        base_timestamp=timestamp,
        bids=non_empty_orderbook_levels,
        asks=non_empty_orderbook_levels,
        seq=sequence_number,
    )
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_first_capture_always_succeeds(
        self,
        interval_sec: float,
        base_timestamp: float,
        bids: List[Tuple[float, float]],
        asks: List[Tuple[float, float]],
        seq: int,
    ):
        """Verify that the first capture for a symbol is always captured.
        
        The first update for any symbol/exchange pair should always be captured
        since there is no previous capture to compare against.
        
        **Validates: Requirements 1.1**
        """
        pool = create_mock_pool()
        config = OrderbookSnapshotWriterConfig(
            enabled=True,
            snapshot_interval_sec=interval_sec,
        )
        writer = OrderbookSnapshotWriter(pool, config)
        
        state = create_valid_orderbook_state("BTC/USDT", bids, asks, seq)
        
        await writer.maybe_capture(
            symbol="BTC/USDT",
            exchange="binance",
            state=state,
            timestamp=base_timestamp,
            seq=seq,
        )
        
        # First capture should always succeed
        assert writer.get_buffer_size() == 1, (
            f"First capture should always succeed, but buffer size is {writer.get_buffer_size()}"
        )
        assert writer.get_last_capture_time("BTC/USDT", "binance") == base_timestamp

    @given(
        interval_sec=snapshot_interval,
        base_timestamp=timestamp,
        delta=time_delta,
        bids=non_empty_orderbook_levels,
        asks=non_empty_orderbook_levels,
        seq=sequence_number,
    )
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_capture_skipped_within_interval(
        self,
        interval_sec: float,
        base_timestamp: float,
        delta: float,
        bids: List[Tuple[float, float]],
        asks: List[Tuple[float, float]],
        seq: int,
    ):
        """Verify that captures within the interval are skipped.
        
        If the time since the last capture is less than the configured interval,
        the capture should be skipped.
        
        **Validates: Requirements 1.1**
        """
        # Ensure delta is strictly less than interval
        assume(delta < interval_sec)
        
        pool = create_mock_pool()
        config = OrderbookSnapshotWriterConfig(
            enabled=True,
            snapshot_interval_sec=interval_sec,
        )
        writer = OrderbookSnapshotWriter(pool, config)
        
        state = create_valid_orderbook_state("BTC/USDT", bids, asks, seq)
        
        # First capture
        await writer.maybe_capture(
            symbol="BTC/USDT",
            exchange="binance",
            state=state,
            timestamp=base_timestamp,
            seq=seq,
        )
        assert writer.get_buffer_size() == 1
        
        # Second capture within interval - should be skipped
        await writer.maybe_capture(
            symbol="BTC/USDT",
            exchange="binance",
            state=state,
            timestamp=base_timestamp + delta,
            seq=seq + 1,
        )
        
        # Buffer should still have only 1 snapshot
        assert writer.get_buffer_size() == 1, (
            f"Capture within interval should be skipped. "
            f"Interval: {interval_sec}s, Delta: {delta}s, Buffer size: {writer.get_buffer_size()}"
        )
        # Last capture time should not have changed
        assert writer.get_last_capture_time("BTC/USDT", "binance") == base_timestamp

    @given(
        interval_sec=snapshot_interval,
        base_timestamp=timestamp,
        extra_time=st.floats(min_value=0.001, max_value=10.0, allow_nan=False, allow_infinity=False),
        bids=non_empty_orderbook_levels,
        asks=non_empty_orderbook_levels,
        seq=sequence_number,
    )
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_capture_succeeds_after_interval(
        self,
        interval_sec: float,
        base_timestamp: float,
        extra_time: float,
        bids: List[Tuple[float, float]],
        asks: List[Tuple[float, float]],
        seq: int,
    ):
        """Verify that captures succeed after the interval has elapsed.
        
        If the time since the last capture is clearly greater than the
        configured interval (accounting for floating-point precision),
        the capture should succeed.
        
        Note: Due to floating-point precision issues with large timestamps,
        we use extra_time >= 0.001 to ensure we're clearly past the interval.
        
        **Validates: Requirements 1.1**
        """
        pool = create_mock_pool()
        config = OrderbookSnapshotWriterConfig(
            enabled=True,
            snapshot_interval_sec=interval_sec,
        )
        writer = OrderbookSnapshotWriter(pool, config)
        
        state = create_valid_orderbook_state("BTC/USDT", bids, asks, seq)
        
        # First capture
        await writer.maybe_capture(
            symbol="BTC/USDT",
            exchange="binance",
            state=state,
            timestamp=base_timestamp,
            seq=seq,
        )
        assert writer.get_buffer_size() == 1
        
        # Second capture clearly after interval - should succeed
        # We add extra_time (>= 0.001) to ensure we're past the interval
        # even with floating-point precision loss
        second_timestamp = base_timestamp + interval_sec + extra_time
        await writer.maybe_capture(
            symbol="BTC/USDT",
            exchange="binance",
            state=state,
            timestamp=second_timestamp,
            seq=seq + 1,
        )
        
        # Buffer should now have 2 snapshots
        assert writer.get_buffer_size() == 2, (
            f"Capture after interval should succeed. "
            f"Interval: {interval_sec}s, Time elapsed: {interval_sec + extra_time}s, "
            f"Buffer size: {writer.get_buffer_size()}"
        )
        # Last capture time should be updated
        assert writer.get_last_capture_time("BTC/USDT", "binance") == second_timestamp

    @given(
        interval_sec=snapshot_interval,
        base_timestamp=timestamp,
        num_updates=st.integers(min_value=2, max_value=20),
        bids=non_empty_orderbook_levels,
        asks=non_empty_orderbook_levels,
        seq=sequence_number,
    )
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_no_two_snapshots_closer_than_interval(
        self,
        interval_sec: float,
        base_timestamp: float,
        num_updates: int,
        bids: List[Tuple[float, float]],
        asks: List[Tuple[float, float]],
        seq: int,
    ):
        """Verify no two captured snapshots have timestamps closer than the interval.
        
        This is the core property: for any sequence of updates, the captured
        snapshots should always be at least interval_sec apart.
        
        **Validates: Requirements 1.1**
        """
        pool = create_mock_pool()
        config = OrderbookSnapshotWriterConfig(
            enabled=True,
            snapshot_interval_sec=interval_sec,
        )
        writer = OrderbookSnapshotWriter(pool, config)
        
        state = create_valid_orderbook_state("BTC/USDT", bids, asks, seq)
        
        # Generate a sequence of updates with varying time deltas
        # Some will be within interval, some will be after
        captured_timestamps = []
        current_timestamp = base_timestamp
        
        for i in range(num_updates):
            await writer.maybe_capture(
                symbol="BTC/USDT",
                exchange="binance",
                state=state,
                timestamp=current_timestamp,
                seq=seq + i,
            )
            
            # Check if this update was captured by comparing buffer size
            if writer.get_buffer_size() > len(captured_timestamps):
                captured_timestamps.append(current_timestamp)
            
            # Advance time by a random amount (0.1 to 2x interval)
            current_timestamp += interval_sec * 0.5
        
        # Verify no two captured timestamps are closer than interval
        for i in range(1, len(captured_timestamps)):
            time_diff = captured_timestamps[i] - captured_timestamps[i - 1]
            assert time_diff >= interval_sec, (
                f"Two snapshots captured too close together. "
                f"Interval: {interval_sec}s, Time diff: {time_diff}s, "
                f"Timestamps: {captured_timestamps[i-1]} -> {captured_timestamps[i]}"
            )

    @given(
        interval_sec=snapshot_interval,
        base_timestamp=timestamp,
        time_deltas=st.lists(time_delta, min_size=5, max_size=50),
        bids=non_empty_orderbook_levels,
        asks=non_empty_orderbook_levels,
        seq=sequence_number,
    )
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_snapshot_timestamps_respect_interval_for_random_sequence(
        self,
        interval_sec: float,
        base_timestamp: float,
        time_deltas: List[float],
        bids: List[Tuple[float, float]],
        asks: List[Tuple[float, float]],
        seq: int,
    ):
        """Verify interval throttling holds for any random sequence of updates.
        
        Given a random sequence of time deltas between updates, verify that
        all captured snapshots respect the minimum interval constraint.
        
        **Validates: Requirements 1.1**
        """
        pool = create_mock_pool()
        config = OrderbookSnapshotWriterConfig(
            enabled=True,
            snapshot_interval_sec=interval_sec,
        )
        writer = OrderbookSnapshotWriter(pool, config)
        
        state = create_valid_orderbook_state("BTC/USDT", bids, asks, seq)
        
        # Process updates with random time deltas
        captured_timestamps = []
        current_timestamp = base_timestamp
        
        for i, delta in enumerate(time_deltas):
            await writer.maybe_capture(
                symbol="BTC/USDT",
                exchange="binance",
                state=state,
                timestamp=current_timestamp,
                seq=seq + i,
            )
            
            # Check if this update was captured
            if writer.get_buffer_size() > len(captured_timestamps):
                captured_timestamps.append(current_timestamp)
            
            current_timestamp += delta
        
        # Verify the interval property for all captured snapshots
        for i in range(1, len(captured_timestamps)):
            time_diff = captured_timestamps[i] - captured_timestamps[i - 1]
            assert time_diff >= interval_sec - 1e-9, (  # Small tolerance for floating point
                f"Interval violation detected. "
                f"Configured interval: {interval_sec}s, Actual diff: {time_diff}s"
            )

    @given(
        interval_sec=snapshot_interval,
        base_timestamp=timestamp,
        sym1=symbol,
        sym2=symbol,
        exch1=exchange,
        exch2=exchange,
        bids=non_empty_orderbook_levels,
        asks=non_empty_orderbook_levels,
        seq=sequence_number,
    )
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_different_symbols_have_independent_throttling(
        self,
        interval_sec: float,
        base_timestamp: float,
        sym1: str,
        sym2: str,
        exch1: str,
        exch2: str,
        bids: List[Tuple[float, float]],
        asks: List[Tuple[float, float]],
        seq: int,
    ):
        """Verify that different symbol/exchange pairs have independent throttling.
        
        Capturing a snapshot for one symbol should not affect the throttling
        of another symbol.
        
        **Validates: Requirements 1.1**
        """
        # Ensure we have different symbol/exchange combinations
        assume((sym1, exch1) != (sym2, exch2))
        
        pool = create_mock_pool()
        config = OrderbookSnapshotWriterConfig(
            enabled=True,
            snapshot_interval_sec=interval_sec,
        )
        writer = OrderbookSnapshotWriter(pool, config)
        
        state1 = create_valid_orderbook_state(sym1, bids, asks, seq)
        state2 = create_valid_orderbook_state(sym2, bids, asks, seq)
        
        # Capture for first symbol
        await writer.maybe_capture(
            symbol=sym1,
            exchange=exch1,
            state=state1,
            timestamp=base_timestamp,
            seq=seq,
        )
        assert writer.get_buffer_size() == 1
        
        # Capture for second symbol at same timestamp - should also succeed
        await writer.maybe_capture(
            symbol=sym2,
            exchange=exch2,
            state=state2,
            timestamp=base_timestamp,
            seq=seq,
        )
        
        # Both should be captured since they are independent
        assert writer.get_buffer_size() == 2, (
            f"Different symbols should have independent throttling. "
            f"Symbol1: {sym1}/{exch1}, Symbol2: {sym2}/{exch2}, "
            f"Buffer size: {writer.get_buffer_size()}"
        )

    @given(
        interval_sec=snapshot_interval,
        base_timestamp=timestamp,
        bids=non_empty_orderbook_levels,
        asks=non_empty_orderbook_levels,
        seq=sequence_number,
    )
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_same_symbol_different_exchange_independent(
        self,
        interval_sec: float,
        base_timestamp: float,
        bids: List[Tuple[float, float]],
        asks: List[Tuple[float, float]],
        seq: int,
    ):
        """Verify same symbol on different exchanges have independent throttling.
        
        BTC/USDT on Binance and BTC/USDT on Coinbase should be throttled
        independently.
        
        **Validates: Requirements 1.1**
        """
        pool = create_mock_pool()
        config = OrderbookSnapshotWriterConfig(
            enabled=True,
            snapshot_interval_sec=interval_sec,
        )
        writer = OrderbookSnapshotWriter(pool, config)
        
        state = create_valid_orderbook_state("BTC/USDT", bids, asks, seq)
        
        # Capture for Binance
        await writer.maybe_capture(
            symbol="BTC/USDT",
            exchange="binance",
            state=state,
            timestamp=base_timestamp,
            seq=seq,
        )
        
        # Capture for Coinbase at same timestamp - should also succeed
        await writer.maybe_capture(
            symbol="BTC/USDT",
            exchange="coinbase",
            state=state,
            timestamp=base_timestamp,
            seq=seq,
        )
        
        # Both should be captured
        assert writer.get_buffer_size() == 2, (
            f"Same symbol on different exchanges should be independent. "
            f"Buffer size: {writer.get_buffer_size()}"
        )

    @given(
        interval_sec=snapshot_interval,
        base_timestamp=timestamp,
        bids=non_empty_orderbook_levels,
        asks=non_empty_orderbook_levels,
        seq=sequence_number,
    )
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_capture_at_interval_boundary_with_epsilon(
        self,
        interval_sec: float,
        base_timestamp: float,
        bids: List[Tuple[float, float]],
        asks: List[Tuple[float, float]],
        seq: int,
    ):
        """Verify capture behavior at the interval boundary with small epsilon.
        
        Due to floating-point precision issues with large timestamps, captures
        at exactly interval_sec may not succeed. This test verifies that captures
        at interval_sec + small_epsilon succeed reliably.
        
        **Validates: Requirements 1.1**
        """
        pool = create_mock_pool()
        config = OrderbookSnapshotWriterConfig(
            enabled=True,
            snapshot_interval_sec=interval_sec,
        )
        writer = OrderbookSnapshotWriter(pool, config)
        
        state = create_valid_orderbook_state("BTC/USDT", bids, asks, seq)
        
        # First capture
        await writer.maybe_capture(
            symbol="BTC/USDT",
            exchange="binance",
            state=state,
            timestamp=base_timestamp,
            seq=seq,
        )
        assert writer.get_buffer_size() == 1
        
        # Capture at interval + small epsilon to account for floating-point precision
        # This ensures we're reliably past the interval boundary
        epsilon = 0.001  # 1ms epsilon
        await writer.maybe_capture(
            symbol="BTC/USDT",
            exchange="binance",
            state=state,
            timestamp=base_timestamp + interval_sec + epsilon,
            seq=seq + 1,
        )
        
        # Should succeed with epsilon past boundary
        assert writer.get_buffer_size() == 2, (
            f"Capture at interval + epsilon should succeed. "
            f"Interval: {interval_sec}s, Buffer size: {writer.get_buffer_size()}"
        )

    @given(
        interval_sec=snapshot_interval,
        base_timestamp=timestamp,
        bids=non_empty_orderbook_levels,
        asks=non_empty_orderbook_levels,
        seq=sequence_number,
    )
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_capture_just_before_interval_boundary(
        self,
        interval_sec: float,
        base_timestamp: float,
        bids: List[Tuple[float, float]],
        asks: List[Tuple[float, float]],
        seq: int,
    ):
        """Verify capture is skipped just before the interval boundary.
        
        A capture at (interval_sec - epsilon) after the last capture should be skipped.
        
        **Validates: Requirements 1.1**
        """
        pool = create_mock_pool()
        config = OrderbookSnapshotWriterConfig(
            enabled=True,
            snapshot_interval_sec=interval_sec,
        )
        writer = OrderbookSnapshotWriter(pool, config)
        
        state = create_valid_orderbook_state("BTC/USDT", bids, asks, seq)
        
        # First capture
        await writer.maybe_capture(
            symbol="BTC/USDT",
            exchange="binance",
            state=state,
            timestamp=base_timestamp,
            seq=seq,
        )
        assert writer.get_buffer_size() == 1
        
        # Capture just before interval boundary (1ms before)
        epsilon = 0.001
        await writer.maybe_capture(
            symbol="BTC/USDT",
            exchange="binance",
            state=state,
            timestamp=base_timestamp + interval_sec - epsilon,
            seq=seq + 1,
        )
        
        # Should be skipped
        assert writer.get_buffer_size() == 1, (
            f"Capture just before interval boundary should be skipped. "
            f"Interval: {interval_sec}s, Time elapsed: {interval_sec - epsilon}s, "
            f"Buffer size: {writer.get_buffer_size()}"
        )

    @given(
        interval_sec=snapshot_interval,
        base_timestamp=timestamp,
        num_rapid_updates=st.integers(min_value=10, max_value=100),
        bids=non_empty_orderbook_levels,
        asks=non_empty_orderbook_levels,
        seq=sequence_number,
    )
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_rapid_updates_only_capture_at_interval(
        self,
        interval_sec: float,
        base_timestamp: float,
        num_rapid_updates: int,
        bids: List[Tuple[float, float]],
        asks: List[Tuple[float, float]],
        seq: int,
    ):
        """Verify that rapid updates (faster than interval) only capture at interval.
        
        If updates come in faster than the configured interval, only one snapshot
        per interval should be captured.
        
        **Validates: Requirements 1.1**
        """
        pool = create_mock_pool()
        config = OrderbookSnapshotWriterConfig(
            enabled=True,
            snapshot_interval_sec=interval_sec,
        )
        writer = OrderbookSnapshotWriter(pool, config)
        
        state = create_valid_orderbook_state("BTC/USDT", bids, asks, seq)
        
        # Send rapid updates (10ms apart, much faster than interval)
        rapid_delta = 0.01  # 10ms
        total_time = num_rapid_updates * rapid_delta
        
        for i in range(num_rapid_updates):
            await writer.maybe_capture(
                symbol="BTC/USDT",
                exchange="binance",
                state=state,
                timestamp=base_timestamp + i * rapid_delta,
                seq=seq + i,
            )
        
        # Calculate expected number of captures
        # First capture always happens, then one per interval
        expected_captures = 1 + int(total_time / interval_sec)
        actual_captures = writer.get_buffer_size()
        
        # Allow for boundary conditions (could be +/- 1)
        assert abs(actual_captures - expected_captures) <= 1, (
            f"Rapid updates should only capture at interval. "
            f"Interval: {interval_sec}s, Total time: {total_time}s, "
            f"Expected captures: ~{expected_captures}, Actual: {actual_captures}"
        )
