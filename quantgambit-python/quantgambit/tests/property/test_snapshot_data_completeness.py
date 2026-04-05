"""Property-based tests for snapshot data completeness.

Feature: live-orderbook-data-storage, Property 2: Snapshot Data Completeness

Tests that for any valid OrderbookState with bids and asks, the resulting
OrderbookSnapshot SHALL contain: symbol (non-empty string), exchange (non-empty
string), timestamp (valid datetime), seq (positive integer), bids (list of up
to 20 [price, size] pairs), and asks (list of up to 20 [price, size] pairs).

**Validates: Requirements 1.2**
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Tuple
from unittest.mock import AsyncMock, MagicMock

import pytest
from hypothesis import given, strategies as st, settings, assume

from quantgambit.market.orderbooks import OrderbookState
from quantgambit.storage.orderbook_snapshot_writer import OrderbookSnapshotWriter
from quantgambit.storage.persistence import (
    OrderbookSnapshot,
    OrderbookSnapshotWriterConfig,
)


# =============================================================================
# Strategies for generating test data
# =============================================================================

# Symbol generator - non-empty strings
symbol_strategy = st.text(
    alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd"), whitelist_characters="/-_"),
    min_size=1,
    max_size=20,
).filter(lambda s: len(s.strip()) > 0)

# Exchange generator - non-empty strings
exchange_strategy = st.text(
    alphabet=st.characters(whitelist_categories=("Ll", "Nd"), whitelist_characters="-_"),
    min_size=1,
    max_size=20,
).filter(lambda s: len(s.strip()) > 0)


# Timestamp generator (realistic Unix timestamps)
timestamp_strategy = st.floats(
    min_value=1600000000.0,
    max_value=2000000000.0,
    allow_nan=False,
    allow_infinity=False,
)

# Sequence number generator - positive integers
sequence_strategy = st.integers(min_value=1, max_value=1000000)

# Orderbook level generator - price and size pairs (positive values)
orderbook_level = st.tuples(
    st.floats(min_value=0.01, max_value=100000.0, allow_nan=False, allow_infinity=False),  # price
    st.floats(min_value=0.0001, max_value=10000.0, allow_nan=False, allow_infinity=False),  # size
)

# Non-empty orderbook levels (at least 1 level, up to 20)
non_empty_orderbook_levels = st.lists(orderbook_level, min_size=1, max_size=20)

# Orderbook levels (0 to 20 levels, can be empty)
orderbook_levels = st.lists(orderbook_level, min_size=0, max_size=20)

# Orderbook levels with more than 20 levels (to test truncation)
large_orderbook_levels = st.lists(orderbook_level, min_size=21, max_size=50)


def create_valid_orderbook_state(
    symbol: str,
    bids: List[Tuple[float, float]],
    asks: List[Tuple[float, float]],
    seq: int,
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
    conn = AsyncMock()
    conn.executemany = AsyncMock()
    pool.acquire = MagicMock(
        return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=conn),
            __aexit__=AsyncMock(),
        )
    )
    return pool


# =============================================================================
# Property 2: Snapshot Data Completeness
# =============================================================================


class TestSnapshotDataCompleteness:
    """Property 2: Snapshot Data Completeness

    For any valid OrderbookState with bids and asks, the resulting OrderbookSnapshot
    SHALL contain: symbol (non-empty string), exchange (non-empty string), timestamp
    (valid datetime), seq (positive integer), bids (list of up to 20 [price, size]
    pairs), and asks (list of up to 20 [price, size] pairs).

    **Validates: Requirements 1.2**
    """

    @given(
        symbol=symbol_strategy,
        exchange=exchange_strategy,
        timestamp=timestamp_strategy,
        seq=sequence_strategy,
        bids=non_empty_orderbook_levels,
        asks=non_empty_orderbook_levels,
    )
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_snapshot_contains_non_empty_symbol(
        self,
        symbol: str,
        exchange: str,
        timestamp: float,
        seq: int,
        bids: List[Tuple[float, float]],
        asks: List[Tuple[float, float]],
    ):
        """Verify that captured snapshot contains a non-empty symbol.

        **Validates: Requirements 1.2**
        """
        pool = create_mock_pool()
        config = OrderbookSnapshotWriterConfig(enabled=True, snapshot_interval_sec=0.0)
        writer = OrderbookSnapshotWriter(pool, config)

        state = create_valid_orderbook_state(symbol, bids, asks, seq)

        await writer.maybe_capture(
            symbol=symbol,
            exchange=exchange,
            state=state,
            timestamp=timestamp,
            seq=seq,
        )

        assert writer.get_buffer_size() == 1
        snapshot = writer._buffer[0]

        # Verify symbol is non-empty string
        assert isinstance(snapshot.symbol, str), f"Symbol should be a string, got {type(snapshot.symbol)}"
        assert len(snapshot.symbol) > 0, "Symbol should be non-empty"
        assert snapshot.symbol == symbol, f"Symbol should match input: {symbol}"


    @given(
        symbol=symbol_strategy,
        exchange=exchange_strategy,
        timestamp=timestamp_strategy,
        seq=sequence_strategy,
        bids=non_empty_orderbook_levels,
        asks=non_empty_orderbook_levels,
    )
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_snapshot_contains_non_empty_exchange(
        self,
        symbol: str,
        exchange: str,
        timestamp: float,
        seq: int,
        bids: List[Tuple[float, float]],
        asks: List[Tuple[float, float]],
    ):
        """Verify that captured snapshot contains a non-empty exchange.

        **Validates: Requirements 1.2**
        """
        pool = create_mock_pool()
        config = OrderbookSnapshotWriterConfig(enabled=True, snapshot_interval_sec=0.0)
        writer = OrderbookSnapshotWriter(pool, config)

        state = create_valid_orderbook_state(symbol, bids, asks, seq)

        await writer.maybe_capture(
            symbol=symbol,
            exchange=exchange,
            state=state,
            timestamp=timestamp,
            seq=seq,
        )

        assert writer.get_buffer_size() == 1
        snapshot = writer._buffer[0]

        # Verify exchange is non-empty string
        assert isinstance(snapshot.exchange, str), f"Exchange should be a string, got {type(snapshot.exchange)}"
        assert len(snapshot.exchange) > 0, "Exchange should be non-empty"
        assert snapshot.exchange == exchange, f"Exchange should match input: {exchange}"

    @given(
        symbol=symbol_strategy,
        exchange=exchange_strategy,
        timestamp=timestamp_strategy,
        seq=sequence_strategy,
        bids=non_empty_orderbook_levels,
        asks=non_empty_orderbook_levels,
    )
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_snapshot_contains_valid_timestamp(
        self,
        symbol: str,
        exchange: str,
        timestamp: float,
        seq: int,
        bids: List[Tuple[float, float]],
        asks: List[Tuple[float, float]],
    ):
        """Verify that captured snapshot contains a valid datetime timestamp.

        **Validates: Requirements 1.2**
        """
        pool = create_mock_pool()
        config = OrderbookSnapshotWriterConfig(enabled=True, snapshot_interval_sec=0.0)
        writer = OrderbookSnapshotWriter(pool, config)

        state = create_valid_orderbook_state(symbol, bids, asks, seq)

        await writer.maybe_capture(
            symbol=symbol,
            exchange=exchange,
            state=state,
            timestamp=timestamp,
            seq=seq,
        )

        assert writer.get_buffer_size() == 1
        snapshot = writer._buffer[0]

        # Verify timestamp is a valid datetime
        assert isinstance(snapshot.timestamp, datetime), (
            f"Timestamp should be a datetime, got {type(snapshot.timestamp)}"
        )
        # Verify timestamp has timezone info (UTC)
        assert snapshot.timestamp.tzinfo is not None, "Timestamp should have timezone info"
        # Verify timestamp matches input (converted from Unix timestamp)
        expected_dt = datetime.fromtimestamp(timestamp, tz=timezone.utc)
        assert snapshot.timestamp == expected_dt, (
            f"Timestamp should match input: expected {expected_dt}, got {snapshot.timestamp}"
        )


    @given(
        symbol=symbol_strategy,
        exchange=exchange_strategy,
        timestamp=timestamp_strategy,
        seq=sequence_strategy,
        bids=non_empty_orderbook_levels,
        asks=non_empty_orderbook_levels,
    )
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_snapshot_contains_positive_sequence_number(
        self,
        symbol: str,
        exchange: str,
        timestamp: float,
        seq: int,
        bids: List[Tuple[float, float]],
        asks: List[Tuple[float, float]],
    ):
        """Verify that captured snapshot contains a positive sequence number.

        **Validates: Requirements 1.2**
        """
        pool = create_mock_pool()
        config = OrderbookSnapshotWriterConfig(enabled=True, snapshot_interval_sec=0.0)
        writer = OrderbookSnapshotWriter(pool, config)

        state = create_valid_orderbook_state(symbol, bids, asks, seq)

        await writer.maybe_capture(
            symbol=symbol,
            exchange=exchange,
            state=state,
            timestamp=timestamp,
            seq=seq,
        )

        assert writer.get_buffer_size() == 1
        snapshot = writer._buffer[0]

        # Verify seq is a positive integer
        assert isinstance(snapshot.seq, int), f"Seq should be an integer, got {type(snapshot.seq)}"
        assert snapshot.seq > 0, f"Seq should be positive, got {snapshot.seq}"
        assert snapshot.seq == seq, f"Seq should match input: {seq}"

    @given(
        symbol=symbol_strategy,
        exchange=exchange_strategy,
        timestamp=timestamp_strategy,
        seq=sequence_strategy,
        bids=non_empty_orderbook_levels,
        asks=non_empty_orderbook_levels,
    )
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_snapshot_bids_is_list_of_price_size_pairs(
        self,
        symbol: str,
        exchange: str,
        timestamp: float,
        seq: int,
        bids: List[Tuple[float, float]],
        asks: List[Tuple[float, float]],
    ):
        """Verify that captured snapshot bids is a list of [price, size] pairs.

        **Validates: Requirements 1.2**
        """
        pool = create_mock_pool()
        config = OrderbookSnapshotWriterConfig(enabled=True, snapshot_interval_sec=0.0)
        writer = OrderbookSnapshotWriter(pool, config)

        state = create_valid_orderbook_state(symbol, bids, asks, seq)

        await writer.maybe_capture(
            symbol=symbol,
            exchange=exchange,
            state=state,
            timestamp=timestamp,
            seq=seq,
        )

        assert writer.get_buffer_size() == 1
        snapshot = writer._buffer[0]

        # Verify bids is a list
        assert isinstance(snapshot.bids, list), f"Bids should be a list, got {type(snapshot.bids)}"

        # Verify each bid is a [price, size] pair
        for i, bid in enumerate(snapshot.bids):
            assert isinstance(bid, list), f"Bid {i} should be a list, got {type(bid)}"
            assert len(bid) == 2, f"Bid {i} should have 2 elements, got {len(bid)}"
            price, size = bid
            assert isinstance(price, (int, float)), f"Bid {i} price should be numeric, got {type(price)}"
            assert isinstance(size, (int, float)), f"Bid {i} size should be numeric, got {type(size)}"
            assert price > 0, f"Bid {i} price should be positive, got {price}"
            assert size > 0, f"Bid {i} size should be positive, got {size}"


    @given(
        symbol=symbol_strategy,
        exchange=exchange_strategy,
        timestamp=timestamp_strategy,
        seq=sequence_strategy,
        bids=non_empty_orderbook_levels,
        asks=non_empty_orderbook_levels,
    )
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_snapshot_asks_is_list_of_price_size_pairs(
        self,
        symbol: str,
        exchange: str,
        timestamp: float,
        seq: int,
        bids: List[Tuple[float, float]],
        asks: List[Tuple[float, float]],
    ):
        """Verify that captured snapshot asks is a list of [price, size] pairs.

        **Validates: Requirements 1.2**
        """
        pool = create_mock_pool()
        config = OrderbookSnapshotWriterConfig(enabled=True, snapshot_interval_sec=0.0)
        writer = OrderbookSnapshotWriter(pool, config)

        state = create_valid_orderbook_state(symbol, bids, asks, seq)

        await writer.maybe_capture(
            symbol=symbol,
            exchange=exchange,
            state=state,
            timestamp=timestamp,
            seq=seq,
        )

        assert writer.get_buffer_size() == 1
        snapshot = writer._buffer[0]

        # Verify asks is a list
        assert isinstance(snapshot.asks, list), f"Asks should be a list, got {type(snapshot.asks)}"

        # Verify each ask is a [price, size] pair
        for i, ask in enumerate(snapshot.asks):
            assert isinstance(ask, list), f"Ask {i} should be a list, got {type(ask)}"
            assert len(ask) == 2, f"Ask {i} should have 2 elements, got {len(ask)}"
            price, size = ask
            assert isinstance(price, (int, float)), f"Ask {i} price should be numeric, got {type(price)}"
            assert isinstance(size, (int, float)), f"Ask {i} size should be numeric, got {type(size)}"
            assert price > 0, f"Ask {i} price should be positive, got {price}"
            assert size > 0, f"Ask {i} size should be positive, got {size}"

    @given(
        symbol=symbol_strategy,
        exchange=exchange_strategy,
        timestamp=timestamp_strategy,
        seq=sequence_strategy,
        bids=non_empty_orderbook_levels,
        asks=non_empty_orderbook_levels,
    )
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_snapshot_bids_limited_to_20_levels(
        self,
        symbol: str,
        exchange: str,
        timestamp: float,
        seq: int,
        bids: List[Tuple[float, float]],
        asks: List[Tuple[float, float]],
    ):
        """Verify that captured snapshot bids contains at most 20 levels.

        **Validates: Requirements 1.2**
        """
        pool = create_mock_pool()
        config = OrderbookSnapshotWriterConfig(enabled=True, snapshot_interval_sec=0.0)
        writer = OrderbookSnapshotWriter(pool, config)

        state = create_valid_orderbook_state(symbol, bids, asks, seq)

        await writer.maybe_capture(
            symbol=symbol,
            exchange=exchange,
            state=state,
            timestamp=timestamp,
            seq=seq,
        )

        assert writer.get_buffer_size() == 1
        snapshot = writer._buffer[0]

        # Verify bids has at most 20 levels
        assert len(snapshot.bids) <= 20, (
            f"Bids should have at most 20 levels, got {len(snapshot.bids)}"
        )


    @given(
        symbol=symbol_strategy,
        exchange=exchange_strategy,
        timestamp=timestamp_strategy,
        seq=sequence_strategy,
        bids=non_empty_orderbook_levels,
        asks=non_empty_orderbook_levels,
    )
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_snapshot_asks_limited_to_20_levels(
        self,
        symbol: str,
        exchange: str,
        timestamp: float,
        seq: int,
        bids: List[Tuple[float, float]],
        asks: List[Tuple[float, float]],
    ):
        """Verify that captured snapshot asks contains at most 20 levels.

        **Validates: Requirements 1.2**
        """
        pool = create_mock_pool()
        config = OrderbookSnapshotWriterConfig(enabled=True, snapshot_interval_sec=0.0)
        writer = OrderbookSnapshotWriter(pool, config)

        state = create_valid_orderbook_state(symbol, bids, asks, seq)

        await writer.maybe_capture(
            symbol=symbol,
            exchange=exchange,
            state=state,
            timestamp=timestamp,
            seq=seq,
        )

        assert writer.get_buffer_size() == 1
        snapshot = writer._buffer[0]

        # Verify asks has at most 20 levels
        assert len(snapshot.asks) <= 20, (
            f"Asks should have at most 20 levels, got {len(snapshot.asks)}"
        )

    @given(
        symbol=symbol_strategy,
        exchange=exchange_strategy,
        timestamp=timestamp_strategy,
        seq=sequence_strategy,
        bids=large_orderbook_levels,
        asks=large_orderbook_levels,
    )
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_snapshot_truncates_to_20_levels_when_more_provided(
        self,
        symbol: str,
        exchange: str,
        timestamp: float,
        seq: int,
        bids: List[Tuple[float, float]],
        asks: List[Tuple[float, float]],
    ):
        """Verify that snapshot truncates to 20 levels when more are provided.

        When the orderbook has more than 20 levels, the snapshot should only
        contain the top 20 levels (best prices).

        **Validates: Requirements 1.2**
        """
        pool = create_mock_pool()
        config = OrderbookSnapshotWriterConfig(enabled=True, snapshot_interval_sec=0.0)
        writer = OrderbookSnapshotWriter(pool, config)

        state = create_valid_orderbook_state(symbol, bids, asks, seq)

        await writer.maybe_capture(
            symbol=symbol,
            exchange=exchange,
            state=state,
            timestamp=timestamp,
            seq=seq,
        )

        assert writer.get_buffer_size() == 1
        snapshot = writer._buffer[0]

        # Verify bids and asks are truncated to 20 levels
        assert len(snapshot.bids) <= 20, (
            f"Bids should be truncated to 20 levels, got {len(snapshot.bids)}"
        )
        assert len(snapshot.asks) <= 20, (
            f"Asks should be truncated to 20 levels, got {len(snapshot.asks)}"
        )


    @given(
        symbol=symbol_strategy,
        exchange=exchange_strategy,
        timestamp=timestamp_strategy,
        seq=sequence_strategy,
        bids=non_empty_orderbook_levels,
        asks=non_empty_orderbook_levels,
    )
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_snapshot_all_fields_present(
        self,
        symbol: str,
        exchange: str,
        timestamp: float,
        seq: int,
        bids: List[Tuple[float, float]],
        asks: List[Tuple[float, float]],
    ):
        """Verify that captured snapshot contains all required fields.

        This is the comprehensive test that verifies all fields are present
        and have the correct types in a single test.

        **Validates: Requirements 1.2**
        """
        pool = create_mock_pool()
        config = OrderbookSnapshotWriterConfig(enabled=True, snapshot_interval_sec=0.0)
        writer = OrderbookSnapshotWriter(pool, config)

        state = create_valid_orderbook_state(symbol, bids, asks, seq)

        await writer.maybe_capture(
            symbol=symbol,
            exchange=exchange,
            state=state,
            timestamp=timestamp,
            seq=seq,
        )

        assert writer.get_buffer_size() == 1
        snapshot = writer._buffer[0]

        # Verify all required fields are present and have correct types
        # 1. Symbol - non-empty string
        assert isinstance(snapshot.symbol, str) and len(snapshot.symbol) > 0, (
            f"Symbol should be non-empty string, got {snapshot.symbol!r}"
        )

        # 2. Exchange - non-empty string
        assert isinstance(snapshot.exchange, str) and len(snapshot.exchange) > 0, (
            f"Exchange should be non-empty string, got {snapshot.exchange!r}"
        )

        # 3. Timestamp - valid datetime
        assert isinstance(snapshot.timestamp, datetime), (
            f"Timestamp should be datetime, got {type(snapshot.timestamp)}"
        )

        # 4. Seq - positive integer
        assert isinstance(snapshot.seq, int) and snapshot.seq > 0, (
            f"Seq should be positive integer, got {snapshot.seq}"
        )

        # 5. Bids - list of up to 20 [price, size] pairs
        assert isinstance(snapshot.bids, list), f"Bids should be list, got {type(snapshot.bids)}"
        assert len(snapshot.bids) <= 20, f"Bids should have at most 20 levels, got {len(snapshot.bids)}"
        for bid in snapshot.bids:
            assert isinstance(bid, list) and len(bid) == 2, f"Each bid should be [price, size], got {bid}"

        # 6. Asks - list of up to 20 [price, size] pairs
        assert isinstance(snapshot.asks, list), f"Asks should be list, got {type(snapshot.asks)}"
        assert len(snapshot.asks) <= 20, f"Asks should have at most 20 levels, got {len(snapshot.asks)}"
        for ask in snapshot.asks:
            assert isinstance(ask, list) and len(ask) == 2, f"Each ask should be [price, size], got {ask}"


    @given(
        symbol=symbol_strategy,
        exchange=exchange_strategy,
        timestamp=timestamp_strategy,
        seq=sequence_strategy,
        bids=non_empty_orderbook_levels,
        asks=non_empty_orderbook_levels,
    )
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_snapshot_bids_sorted_by_price_descending(
        self,
        symbol: str,
        exchange: str,
        timestamp: float,
        seq: int,
        bids: List[Tuple[float, float]],
        asks: List[Tuple[float, float]],
    ):
        """Verify that snapshot bids are sorted by price in descending order.

        Bids should be ordered from best (highest) to worst (lowest) price.

        **Validates: Requirements 1.2**
        """
        pool = create_mock_pool()
        config = OrderbookSnapshotWriterConfig(enabled=True, snapshot_interval_sec=0.0)
        writer = OrderbookSnapshotWriter(pool, config)

        state = create_valid_orderbook_state(symbol, bids, asks, seq)

        await writer.maybe_capture(
            symbol=symbol,
            exchange=exchange,
            state=state,
            timestamp=timestamp,
            seq=seq,
        )

        assert writer.get_buffer_size() == 1
        snapshot = writer._buffer[0]

        # Verify bids are sorted by price descending (best to worst)
        if len(snapshot.bids) > 1:
            prices = [bid[0] for bid in snapshot.bids]
            for i in range(1, len(prices)):
                assert prices[i - 1] >= prices[i], (
                    f"Bids should be sorted by price descending. "
                    f"Price at index {i-1} ({prices[i-1]}) should be >= price at index {i} ({prices[i]})"
                )

    @given(
        symbol=symbol_strategy,
        exchange=exchange_strategy,
        timestamp=timestamp_strategy,
        seq=sequence_strategy,
        bids=non_empty_orderbook_levels,
        asks=non_empty_orderbook_levels,
    )
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_snapshot_asks_sorted_by_price_ascending(
        self,
        symbol: str,
        exchange: str,
        timestamp: float,
        seq: int,
        bids: List[Tuple[float, float]],
        asks: List[Tuple[float, float]],
    ):
        """Verify that snapshot asks are sorted by price in ascending order.

        Asks should be ordered from best (lowest) to worst (highest) price.

        **Validates: Requirements 1.2**
        """
        pool = create_mock_pool()
        config = OrderbookSnapshotWriterConfig(enabled=True, snapshot_interval_sec=0.0)
        writer = OrderbookSnapshotWriter(pool, config)

        state = create_valid_orderbook_state(symbol, bids, asks, seq)

        await writer.maybe_capture(
            symbol=symbol,
            exchange=exchange,
            state=state,
            timestamp=timestamp,
            seq=seq,
        )

        assert writer.get_buffer_size() == 1
        snapshot = writer._buffer[0]

        # Verify asks are sorted by price ascending (best to worst)
        if len(snapshot.asks) > 1:
            prices = [ask[0] for ask in snapshot.asks]
            for i in range(1, len(prices)):
                assert prices[i - 1] <= prices[i], (
                    f"Asks should be sorted by price ascending. "
                    f"Price at index {i-1} ({prices[i-1]}) should be <= price at index {i} ({prices[i]})"
                )


    @given(
        symbol=symbol_strategy,
        exchange=exchange_strategy,
        timestamp=timestamp_strategy,
        seq=sequence_strategy,
        bids=non_empty_orderbook_levels,
        asks=non_empty_orderbook_levels,
    )
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_snapshot_preserves_input_data(
        self,
        symbol: str,
        exchange: str,
        timestamp: float,
        seq: int,
        bids: List[Tuple[float, float]],
        asks: List[Tuple[float, float]],
    ):
        """Verify that snapshot preserves the input symbol, exchange, and seq.

        The snapshot should contain the exact values passed to maybe_capture.

        **Validates: Requirements 1.2**
        """
        pool = create_mock_pool()
        config = OrderbookSnapshotWriterConfig(enabled=True, snapshot_interval_sec=0.0)
        writer = OrderbookSnapshotWriter(pool, config)

        state = create_valid_orderbook_state(symbol, bids, asks, seq)

        await writer.maybe_capture(
            symbol=symbol,
            exchange=exchange,
            state=state,
            timestamp=timestamp,
            seq=seq,
        )

        assert writer.get_buffer_size() == 1
        snapshot = writer._buffer[0]

        # Verify input data is preserved
        assert snapshot.symbol == symbol, f"Symbol mismatch: expected {symbol}, got {snapshot.symbol}"
        assert snapshot.exchange == exchange, f"Exchange mismatch: expected {exchange}, got {snapshot.exchange}"
        assert snapshot.seq == seq, f"Seq mismatch: expected {seq}, got {snapshot.seq}"

    @given(
        symbol=symbol_strategy,
        exchange=exchange_strategy,
        timestamp=timestamp_strategy,
        seq=sequence_strategy,
        bids=non_empty_orderbook_levels,
        asks=non_empty_orderbook_levels,
    )
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_snapshot_contains_derived_metrics(
        self,
        symbol: str,
        exchange: str,
        timestamp: float,
        seq: int,
        bids: List[Tuple[float, float]],
        asks: List[Tuple[float, float]],
    ):
        """Verify that snapshot contains derived metrics fields.

        The snapshot should include spread_bps, bid_depth_usd, ask_depth_usd,
        and orderbook_imbalance as numeric values.

        **Validates: Requirements 1.2, 1.3**
        """
        pool = create_mock_pool()
        config = OrderbookSnapshotWriterConfig(enabled=True, snapshot_interval_sec=0.0)
        writer = OrderbookSnapshotWriter(pool, config)

        state = create_valid_orderbook_state(symbol, bids, asks, seq)

        await writer.maybe_capture(
            symbol=symbol,
            exchange=exchange,
            state=state,
            timestamp=timestamp,
            seq=seq,
        )

        assert writer.get_buffer_size() == 1
        snapshot = writer._buffer[0]

        # Verify derived metrics are present and numeric
        assert isinstance(snapshot.spread_bps, (int, float)), (
            f"spread_bps should be numeric, got {type(snapshot.spread_bps)}"
        )
        assert isinstance(snapshot.bid_depth_usd, (int, float)), (
            f"bid_depth_usd should be numeric, got {type(snapshot.bid_depth_usd)}"
        )
        assert isinstance(snapshot.ask_depth_usd, (int, float)), (
            f"ask_depth_usd should be numeric, got {type(snapshot.ask_depth_usd)}"
        )
        assert isinstance(snapshot.orderbook_imbalance, (int, float)), (
            f"orderbook_imbalance should be numeric, got {type(snapshot.orderbook_imbalance)}"
        )

        # Verify derived metrics have valid values
        # Note: spread_bps can be negative for crossed orderbooks (ask < bid)
        assert isinstance(snapshot.spread_bps, (int, float)) and not (
            snapshot.spread_bps != snapshot.spread_bps  # NaN check
        ), f"spread_bps should be a valid number, got {snapshot.spread_bps}"
        assert snapshot.bid_depth_usd >= 0, f"bid_depth_usd should be non-negative, got {snapshot.bid_depth_usd}"
        assert snapshot.ask_depth_usd >= 0, f"ask_depth_usd should be non-negative, got {snapshot.ask_depth_usd}"
        assert -1 <= snapshot.orderbook_imbalance <= 1, (
            f"orderbook_imbalance should be between -1 and 1, got {snapshot.orderbook_imbalance}"
        )
