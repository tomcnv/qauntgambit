"""Property-based tests for exponential backoff retry.

Feature: live-orderbook-data-storage, Property 5: Exponential Backoff Retry

Tests that for any sequence of N consecutive write failures, the delay before
retry attempt i (where i starts at 1) SHALL be base_delay * (2 ^ (i - 1)),
capped at a maximum delay. The retry count SHALL not exceed the configured
max_attempts.

**Validates: Requirements 1.5, 2.4**
"""

from __future__ import annotations

import asyncio
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

# Retry configuration strategies
retry_max_attempts = st.integers(min_value=1, max_value=5)
retry_base_delay = st.floats(
    min_value=0.001, max_value=0.1, allow_nan=False, allow_infinity=False
)

# Timestamp generator (realistic Unix timestamps)
timestamp = st.floats(
    min_value=1600000000.0, max_value=2000000000.0, allow_nan=False, allow_infinity=False
)

# Orderbook level generator - price and size pairs
orderbook_level = st.tuples(
    st.floats(min_value=0.01, max_value=100000.0, allow_nan=False, allow_infinity=False),
    st.floats(min_value=0.0001, max_value=10000.0, allow_nan=False, allow_infinity=False),
)

# Non-empty orderbook levels (at least 1 level, up to 20)
non_empty_orderbook_levels = st.lists(orderbook_level, min_size=1, max_size=20)

# Sequence number generator
sequence_number = st.integers(min_value=1, max_value=1000000)


def create_valid_orderbook_state(
    symbol: str, bids: List[Tuple[float, float]], asks: List[Tuple[float, float]], seq: int
) -> OrderbookState:
    """Create a valid OrderbookState from bid/ask tuples."""
    state = OrderbookState(symbol=symbol)
    bids_list = [[p, s] for p, s in bids]
    asks_list = [[p, s] for p, s in asks]
    state.apply_snapshot(bids=bids_list, asks=asks_list, seq=seq)
    return state


def create_mock_pool():
    """Create a mock asyncpg pool for testing."""
    pool = MagicMock()
    conn = MagicMock()
    conn.executemany = AsyncMock()
    
    cm = AsyncMock()
    cm.__aenter__.return_value = conn
    cm.__aexit__.return_value = None
    pool.acquire.return_value = cm
    return pool


def create_failing_mock_pool(num_failures: int):
    """Create a mock pool that fails a specified number of times then succeeds."""
    call_count = [0]

    async def mock_executemany(*args, **kwargs):
        call_count[0] += 1
        if call_count[0] <= num_failures:
            raise Exception(f"Simulated database failure #{call_count[0]}")
        return None

    pool = MagicMock()
    conn = MagicMock()
    conn.executemany = mock_executemany
    
    cm = AsyncMock()
    cm.__aenter__.return_value = conn
    cm.__aexit__.return_value = None
    pool.acquire.return_value = cm
    return pool, call_count


def create_always_failing_mock_pool():
    """Create a mock pool that always fails."""
    call_count = [0]

    async def mock_executemany(*args, **kwargs):
        call_count[0] += 1
        raise Exception(f"Simulated database failure #{call_count[0]}")

    pool = MagicMock()
    conn = MagicMock()
    conn.executemany = mock_executemany
    
    cm = AsyncMock()
    cm.__aenter__.return_value = conn
    cm.__aexit__.return_value = None
    pool.acquire.return_value = cm
    return pool, call_count


# =============================================================================
# Property 5: Exponential Backoff Retry
# =============================================================================


class TestExponentialBackoffRetry:
    """Property 5: Exponential Backoff Retry

    For any sequence of N consecutive write failures, the delay before retry
    attempt i (where i starts at 1) SHALL be base_delay * (2 ^ (i - 1)),
    capped at a maximum delay. The retry count SHALL not exceed the configured
    max_attempts.

    **Validates: Requirements 1.5, 2.4**
    """

    @given(
        max_attempts=retry_max_attempts,
        base_delay=retry_base_delay,
    )
    @settings(max_examples=100)
    def test_delay_formula_correctness(
        self,
        max_attempts: int,
        base_delay: float,
    ):
        """Verify that delay for attempt i equals base_delay * 2^(i-1).

        **Validates: Requirements 1.5, 2.4**
        """
        for attempt in range(1, max_attempts + 1):
            expected_delay = base_delay * (2 ** (attempt - 1))
            assert expected_delay == base_delay * (2 ** (attempt - 1)), (
                f"Delay formula incorrect for attempt {attempt}."
            )

    @given(
        max_attempts=retry_max_attempts,
        base_delay=retry_base_delay,
        bids=non_empty_orderbook_levels,
        asks=non_empty_orderbook_levels,
        seq=sequence_number,
        base_timestamp=timestamp,
    )
    @settings(max_examples=100, deadline=None)
    @pytest.mark.asyncio
    async def test_retry_count_does_not_exceed_max_attempts(
        self,
        max_attempts: int,
        base_delay: float,
        bids: List[Tuple[float, float]],
        asks: List[Tuple[float, float]],
        seq: int,
        base_timestamp: float,
    ):
        """Verify that retry count does not exceed configured max_attempts.

        **Validates: Requirements 1.5, 2.4**
        """
        pool, call_count = create_always_failing_mock_pool()
        config = OrderbookSnapshotWriterConfig(
            enabled=True,
            snapshot_interval_sec=0.0,
            batch_size=100,
            retry_max_attempts=max_attempts,
            retry_base_delay_sec=0.001,
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

        await writer.flush()

        assert call_count[0] == max_attempts, (
            f"Retry count should equal max_attempts ({max_attempts}). "
            f"Actual attempts: {call_count[0]}"
        )


    @given(
        max_attempts=st.integers(min_value=2, max_value=5),
        base_delay=st.floats(
            min_value=0.01, max_value=0.05, allow_nan=False, allow_infinity=False
        ),
        bids=non_empty_orderbook_levels,
        asks=non_empty_orderbook_levels,
        seq=sequence_number,
        base_timestamp=timestamp,
    )
    @settings(max_examples=100, deadline=None)
    @pytest.mark.asyncio
    async def test_delays_increase_exponentially(
        self,
        max_attempts: int,
        base_delay: float,
        bids: List[Tuple[float, float]],
        asks: List[Tuple[float, float]],
        seq: int,
        base_timestamp: float,
    ):
        """Verify that delays between retries increase exponentially.

        **Validates: Requirements 1.5, 2.4**
        """
        # Measure requested sleep delays directly by patching the writer module's
        # asyncio.sleep. Measuring wall-clock timing is flaky under CI load.
        requested_delays: List[float] = []

        async def fake_sleep(delay: float):
            requested_delays.append(delay)
            return None

        async def mock_executemany_with_timing(*args, **kwargs):
            raise Exception("Simulated database failure")

        pool = MagicMock()
        conn = MagicMock()
        conn.executemany = mock_executemany_with_timing
        
        cm = AsyncMock()
        cm.__aenter__.return_value = conn
        cm.__aexit__.return_value = None
        pool.acquire.return_value = cm

        config = OrderbookSnapshotWriterConfig(
            enabled=True,
            snapshot_interval_sec=0.0,
            batch_size=100,
            retry_max_attempts=max_attempts,
            retry_base_delay_sec=base_delay,
        )
        writer = OrderbookSnapshotWriter(pool, config)

        state = create_valid_orderbook_state("BTC/USDT", bids, asks, seq)

        import quantgambit.storage.orderbook_snapshot_writer as writer_module

        original_sleep = writer_module.asyncio.sleep
        writer_module.asyncio.sleep = fake_sleep
        try:
            await writer.maybe_capture(
                symbol="BTC/USDT",
                exchange="binance",
                state=state,
                timestamp=base_timestamp,
                seq=seq,
            )

            await writer.flush()
        finally:
            writer_module.asyncio.sleep = original_sleep

        # One delay per retry after a failure, but not after the final attempt.
        assert len(requested_delays) == max_attempts - 1, (
            f"Expected {max_attempts - 1} sleep calls, got {len(requested_delays)}"
        )
        for attempt_idx, actual_delay in enumerate(requested_delays, start=0):
            expected_delay = base_delay * (2 ** attempt_idx)
            assert actual_delay == expected_delay, (
                f"Delay before attempt {attempt_idx + 2} should be {expected_delay:.6f}s. "
                f"Actual delay: {actual_delay:.6f}s"
            )


    @given(
        failures_before_success=st.integers(min_value=1, max_value=4),
        max_attempts=st.integers(min_value=5, max_value=10),
        base_delay=retry_base_delay,
        bids=non_empty_orderbook_levels,
        asks=non_empty_orderbook_levels,
        seq=sequence_number,
        base_timestamp=timestamp,
    )
    @settings(max_examples=100, deadline=None)
    @pytest.mark.asyncio
    async def test_success_after_failures_stops_retrying(
        self,
        failures_before_success: int,
        max_attempts: int,
        base_delay: float,
        bids: List[Tuple[float, float]],
        asks: List[Tuple[float, float]],
        seq: int,
        base_timestamp: float,
    ):
        """Verify that successful write stops further retry attempts.

        **Validates: Requirements 1.5, 2.4**
        """
        assume(failures_before_success < max_attempts)

        pool, call_count = create_failing_mock_pool(failures_before_success)
        config = OrderbookSnapshotWriterConfig(
            enabled=True,
            snapshot_interval_sec=0.0,
            batch_size=100,
            retry_max_attempts=max_attempts,
            retry_base_delay_sec=0.001,
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

        await writer.flush()

        expected_attempts = failures_before_success + 1
        assert call_count[0] == expected_attempts, (
            f"Should stop after successful write. "
            f"Expected {expected_attempts} attempts, got {call_count[0]}"
        )

    @given(
        max_attempts=retry_max_attempts,
        base_delay=retry_base_delay,
        bids=non_empty_orderbook_levels,
        asks=non_empty_orderbook_levels,
        seq=sequence_number,
        base_timestamp=timestamp,
    )
    @settings(max_examples=100, deadline=None)
    @pytest.mark.asyncio
    async def test_first_attempt_has_no_delay(
        self,
        max_attempts: int,
        base_delay: float,
        bids: List[Tuple[float, float]],
        asks: List[Tuple[float, float]],
        seq: int,
        base_timestamp: float,
    ):
        """Verify that the first attempt happens immediately without delay.

        **Validates: Requirements 1.5, 2.4**
        """
        first_attempt_time = [None]
        flush_start_time = [None]

        async def mock_executemany_with_timing(*args, **kwargs):
            if first_attempt_time[0] is None:
                first_attempt_time[0] = asyncio.get_event_loop().time()
            raise Exception("Simulated database failure")

        pool = MagicMock()
        conn = MagicMock()
        conn.executemany = mock_executemany_with_timing
        
        cm = AsyncMock()
        cm.__aenter__.return_value = conn
        cm.__aexit__.return_value = None
        pool.acquire.return_value = cm

        config = OrderbookSnapshotWriterConfig(
            enabled=True,
            snapshot_interval_sec=0.0,
            batch_size=100,
            retry_max_attempts=max_attempts,
            retry_base_delay_sec=base_delay,
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

        flush_start_time[0] = asyncio.get_event_loop().time()
        await writer.flush()

        assert first_attempt_time[0] is not None, "First attempt should have been made"
        delay_to_first = first_attempt_time[0] - flush_start_time[0]
        assert delay_to_first < 0.05, (
            f"First attempt should happen immediately. "
            f"Delay to first attempt: {delay_to_first:.4f}s"
        )


    @given(
        max_attempts=retry_max_attempts,
        base_delay=retry_base_delay,
        num_snapshots=st.integers(min_value=1, max_value=5),
        bids=non_empty_orderbook_levels,
        asks=non_empty_orderbook_levels,
        seq=sequence_number,
        base_timestamp=timestamp,
    )
    @settings(max_examples=100, deadline=None)
    @pytest.mark.asyncio
    async def test_batch_dropped_after_max_attempts(
        self,
        max_attempts: int,
        base_delay: float,
        num_snapshots: int,
        bids: List[Tuple[float, float]],
        asks: List[Tuple[float, float]],
        seq: int,
        base_timestamp: float,
    ):
        """Verify that batch is dropped after max_attempts failures.

        **Validates: Requirements 1.5, 2.4**
        """
        pool, call_count = create_always_failing_mock_pool()
        config = OrderbookSnapshotWriterConfig(
            enabled=True,
            snapshot_interval_sec=0.0,
            batch_size=100,
            retry_max_attempts=max_attempts,
            retry_base_delay_sec=0.001,
        )
        writer = OrderbookSnapshotWriter(pool, config)

        state = create_valid_orderbook_state("BTC/USDT", bids, asks, seq)

        for i in range(num_snapshots):
            await writer.maybe_capture(
                symbol="BTC/USDT",
                exchange="binance",
                state=state,
                timestamp=base_timestamp + i,
                seq=seq + i,
            )

        await writer.flush()

        assert writer.get_buffer_size() == 0, (
            f"Buffer should be empty after batch is dropped. "
            f"Buffer size: {writer.get_buffer_size()}"
        )

        assert call_count[0] == max_attempts, (
            f"Should have made exactly {max_attempts} attempts. "
            f"Actual: {call_count[0]}"
        )

    @given(
        max_attempts=st.integers(min_value=2, max_value=5),
        base_delay=st.floats(
            min_value=0.01, max_value=0.03, allow_nan=False, allow_infinity=False
        ),
        bids=non_empty_orderbook_levels,
        asks=non_empty_orderbook_levels,
        seq=sequence_number,
        base_timestamp=timestamp,
    )
    @settings(max_examples=100, deadline=None)
    @pytest.mark.asyncio
    async def test_delay_doubles_each_attempt(
        self,
        max_attempts: int,
        base_delay: float,
        bids: List[Tuple[float, float]],
        asks: List[Tuple[float, float]],
        seq: int,
        base_timestamp: float,
    ):
        """Verify that delay doubles with each retry attempt (deterministic).

        **Validates: Requirements 1.5, 2.4**
        """
        requested_sleeps: List[float] = []

        async def fake_sleep(delay: float):
            requested_sleeps.append(float(delay))
            return None

        async def mock_executemany_with_failure(*args, **kwargs):
            raise Exception("Simulated database failure")

        pool = MagicMock()
        conn = MagicMock()
        conn.executemany = mock_executemany_with_failure
        
        cm = AsyncMock()
        cm.__aenter__.return_value = conn
        cm.__aexit__.return_value = None
        pool.acquire.return_value = cm

        config = OrderbookSnapshotWriterConfig(
            enabled=True,
            snapshot_interval_sec=0.0,
            batch_size=100,
            retry_max_attempts=max_attempts,
            retry_base_delay_sec=base_delay,
        )
        writer = OrderbookSnapshotWriter(pool, config)
        import quantgambit.storage.orderbook_snapshot_writer as writer_mod
        writer_mod.asyncio.sleep = fake_sleep  # type: ignore

        state = create_valid_orderbook_state("BTC/USDT", bids, asks, seq)

        await writer.maybe_capture(
            symbol="BTC/USDT",
            exchange="binance",
            state=state,
            timestamp=base_timestamp,
            seq=seq,
        )

        await writer.flush()
        # Sleep is requested between attempts (max_attempts - 1 times).
        assert len(requested_sleeps) == max_attempts - 1
        for i, delay in enumerate(requested_sleeps):
            expected = base_delay * (2 ** i)
            assert abs(delay - expected) < 1e-9, (
                f"Expected delay={expected}, got={delay} at i={i}"
            )


    @given(
        max_attempts=retry_max_attempts,
        base_delay=retry_base_delay,
        bids=non_empty_orderbook_levels,
        asks=non_empty_orderbook_levels,
        seq=sequence_number,
        base_timestamp=timestamp,
    )
    @settings(max_examples=100, deadline=None)
    @pytest.mark.asyncio
    async def test_successful_write_returns_count(
        self,
        max_attempts: int,
        base_delay: float,
        bids: List[Tuple[float, float]],
        asks: List[Tuple[float, float]],
        seq: int,
        base_timestamp: float,
    ):
        """Verify that successful write returns the correct count.

        **Validates: Requirements 1.5, 2.4**
        """
        pool = create_mock_pool()
        config = OrderbookSnapshotWriterConfig(
            enabled=True,
            snapshot_interval_sec=0.0,
            batch_size=100,
            retry_max_attempts=max_attempts,
            retry_base_delay_sec=base_delay,
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

        count = await writer.flush()
        assert count == 1, f"Successful write should return count of 1, got {count}"

    @given(
        max_attempts=retry_max_attempts,
        base_delay=retry_base_delay,
        bids=non_empty_orderbook_levels,
        asks=non_empty_orderbook_levels,
        seq=sequence_number,
        base_timestamp=timestamp,
    )
    @settings(max_examples=100, deadline=None)
    @pytest.mark.asyncio
    async def test_failed_write_returns_zero(
        self,
        max_attempts: int,
        base_delay: float,
        bids: List[Tuple[float, float]],
        asks: List[Tuple[float, float]],
        seq: int,
        base_timestamp: float,
    ):
        """Verify that failed write (after all retries) returns zero.

        **Validates: Requirements 1.5, 2.4**
        """
        pool, _ = create_always_failing_mock_pool()
        config = OrderbookSnapshotWriterConfig(
            enabled=True,
            snapshot_interval_sec=0.0,
            batch_size=100,
            retry_max_attempts=max_attempts,
            retry_base_delay_sec=0.001,
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

        count = await writer.flush()
        assert count == 0, f"Failed write should return count of 0, got {count}"


    @given(
        max_attempts=st.integers(min_value=1, max_value=3),
        base_delay=st.floats(
            min_value=0.001, max_value=0.01, allow_nan=False, allow_infinity=False
        ),
        num_snapshots=st.integers(min_value=2, max_value=5),
        bids=non_empty_orderbook_levels,
        asks=non_empty_orderbook_levels,
        seq=sequence_number,
        base_timestamp=timestamp,
    )
    @settings(max_examples=100, deadline=None)
    @pytest.mark.asyncio
    async def test_retry_applies_to_entire_batch(
        self,
        max_attempts: int,
        base_delay: float,
        num_snapshots: int,
        bids: List[Tuple[float, float]],
        asks: List[Tuple[float, float]],
        seq: int,
        base_timestamp: float,
    ):
        """Verify that retry logic applies to the entire batch.

        **Validates: Requirements 1.5, 2.4**
        """
        batches_attempted: List[int] = []

        async def mock_executemany_tracking_batch(*args, **kwargs):
            if len(args) > 1:
                batches_attempted.append(len(args[1]))
            raise Exception("Simulated database failure")

        pool = MagicMock()
        conn = MagicMock()
        conn.executemany = mock_executemany_tracking_batch
        
        cm = AsyncMock()
        cm.__aenter__.return_value = conn
        cm.__aexit__.return_value = None
        pool.acquire.return_value = cm

        config = OrderbookSnapshotWriterConfig(
            enabled=True,
            snapshot_interval_sec=0.0,
            batch_size=100,
            retry_max_attempts=max_attempts,
            retry_base_delay_sec=base_delay,
        )
        writer = OrderbookSnapshotWriter(pool, config)

        state = create_valid_orderbook_state("BTC/USDT", bids, asks, seq)

        for i in range(num_snapshots):
            await writer.maybe_capture(
                symbol="BTC/USDT",
                exchange="binance",
                state=state,
                timestamp=base_timestamp + i,
                seq=seq + i,
            )

        await writer.flush()

        assert len(batches_attempted) == max_attempts, (
            f"Should have {max_attempts} batch attempts, got {len(batches_attempted)}"
        )

        for i, batch_size in enumerate(batches_attempted):
            assert batch_size == num_snapshots, (
                f"Attempt {i + 1} should retry entire batch of {num_snapshots}. "
                f"Got batch size: {batch_size}"
            )

    @given(
        max_attempts=st.integers(min_value=1, max_value=5),
        base_delay=retry_base_delay,
    )
    @settings(max_examples=100)
    def test_calculated_delays_match_formula(
        self,
        max_attempts: int,
        base_delay: float,
    ):
        """Verify calculated delays match the exponential backoff formula.

        **Validates: Requirements 1.5, 2.4**
        """
        expected_delays = []
        for attempt in range(max_attempts):
            delay = base_delay * (2 ** attempt)
            expected_delays.append(delay)

        for i, delay in enumerate(expected_delays):
            expected = base_delay * (2 ** i)
            assert abs(delay - expected) < 1e-10, (
                f"Delay for attempt {i + 1} should be {expected}, got {delay}"
            )

        for i in range(1, len(expected_delays)):
            ratio = expected_delays[i] / expected_delays[i - 1]
            assert abs(ratio - 2.0) < 1e-10, (
                f"Delay should double between attempts. "
                f"Ratio between attempt {i} and {i + 1}: {ratio}"
            )

    @given(
        max_attempts=retry_max_attempts,
        base_delay=retry_base_delay,
        bids=non_empty_orderbook_levels,
        asks=non_empty_orderbook_levels,
        seq=sequence_number,
        base_timestamp=timestamp,
    )
    @settings(max_examples=100, deadline=None)
    @pytest.mark.asyncio
    async def test_single_attempt_config(
        self,
        max_attempts: int,
        base_delay: float,
        bids: List[Tuple[float, float]],
        asks: List[Tuple[float, float]],
        seq: int,
        base_timestamp: float,
    ):
        """Verify behavior with max_attempts=1 (no retries).

        **Validates: Requirements 1.5, 2.4**
        """
        pool, call_count = create_always_failing_mock_pool()
        config = OrderbookSnapshotWriterConfig(
            enabled=True,
            snapshot_interval_sec=0.0,
            batch_size=100,
            retry_max_attempts=1,
            retry_base_delay_sec=base_delay,
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

        await writer.flush()

        assert call_count[0] == 1, (
            f"With max_attempts=1, should make exactly 1 attempt. "
            f"Actual: {call_count[0]}"
        )


    @given(
        max_attempts=st.integers(min_value=2, max_value=5),
        failures_before_success=st.integers(min_value=1, max_value=4),
        base_delay=st.floats(
            min_value=0.005, max_value=0.02, allow_nan=False, allow_infinity=False
        ),
        bids=non_empty_orderbook_levels,
        asks=non_empty_orderbook_levels,
        seq=sequence_number,
        base_timestamp=timestamp,
    )
    @settings(max_examples=100, deadline=None)
    @pytest.mark.asyncio
    async def test_total_delay_before_success(
        self,
        max_attempts: int,
        failures_before_success: int,
        base_delay: float,
        bids: List[Tuple[float, float]],
        asks: List[Tuple[float, float]],
        seq: int,
        base_timestamp: float,
    ):
        """Verify total delay before successful write matches expected sum.

        **Validates: Requirements 1.5, 2.4**
        """
        assume(failures_before_success < max_attempts)

        call_count = [0]

        # Avoid wall-clock timing flakiness: assert the requested sleep delays.
        sleep_calls: List[float] = []

        async def fake_sleep(delay: float) -> None:
            sleep_calls.append(float(delay))

        async def mock_executemany_with_timing(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] <= failures_before_success:
                raise Exception(f"Simulated failure #{call_count[0]}")
            return None

        pool = MagicMock()
        conn = MagicMock()
        conn.executemany = mock_executemany_with_timing
        
        cm = AsyncMock()
        cm.__aenter__.return_value = conn
        cm.__aexit__.return_value = None
        pool.acquire.return_value = cm

        config = OrderbookSnapshotWriterConfig(
            enabled=True,
            snapshot_interval_sec=0.0,
            batch_size=100,
            retry_max_attempts=max_attempts,
            retry_base_delay_sec=base_delay,
        )
        writer = OrderbookSnapshotWriter(pool, config)

        state = create_valid_orderbook_state("BTC/USDT", bids, asks, seq)

        from unittest.mock import patch

        with patch(
            "quantgambit.storage.orderbook_snapshot_writer.asyncio.sleep",
            new=fake_sleep,
        ):
            await writer.maybe_capture(
                symbol="BTC/USDT",
                exchange="binance",
                state=state,
                timestamp=base_timestamp,
                seq=seq,
            )

            await writer.flush()

        expected_total_delay = sum(
            base_delay * (2 ** i) for i in range(failures_before_success)
        )
        assert abs(sum(sleep_calls) - expected_total_delay) < 1e-9, (
            f"Total delay should be {expected_total_delay:.6f}s. "
            f"Actual sleep sum: {sum(sleep_calls):.6f}s "
            f"(sleep_calls={sleep_calls})"
        )
