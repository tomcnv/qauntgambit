"""Property-based tests for timestamp preservation.

Feature: live-orderbook-data-storage, Property 7: Timestamp Preservation

Tests that for any trade with an exchange timestamp, the persisted TradeRecord's
timestamp SHALL equal the original exchange timestamp (not the local processing time).

**Validates: Requirements 2.6**
"""

from __future__ import annotations

import time
from datetime import datetime, timezone, timedelta
from typing import Dict, Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from hypothesis import given, strategies as st, settings, assume

from quantgambit.storage.persistence import (
    PersistenceTradeRecord,
    TradeRecordWriterConfig,
)
from quantgambit.storage.trade_record_writer import TradeRecordWriter


# =============================================================================
# Strategies for generating test data
# =============================================================================

# Symbol generator - non-empty strings
symbol_strategy = st.text(
    alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd"), whitelist_characters="/-_"),
    min_size=1,
    max_size=20,
).filter(lambda s: len(s.strip()) > 0)

# Exchange generator - sampled from common exchanges
exchange_strategy = st.sampled_from(["binance", "coinbase", "kraken"])

# Timestamp generator (realistic Unix timestamps)
# Range: 2020-09-13 to 2033-05-18 (reasonable trading timestamps)
timestamp_strategy = st.floats(
    min_value=1600000000.0,
    max_value=2000000000.0,
    allow_nan=False,
    allow_infinity=False,
)

# Price generator - positive floats
price_strategy = st.floats(
    min_value=0.01,
    max_value=100000.0,
    allow_nan=False,
    allow_infinity=False,
)

# Size generator - positive floats
size_strategy = st.floats(
    min_value=0.0001,
    max_value=10000.0,
    allow_nan=False,
    allow_infinity=False,
)

# Side generator - "buy" or "sell"
side_strategy = st.sampled_from(["buy", "sell"])

# Trade ID generator - non-empty strings
trade_id_strategy = st.text(
    alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd"), whitelist_characters="-_"),
    min_size=1,
    max_size=50,
).filter(lambda s: len(s.strip()) > 0)

# Complete trade record generator as specified in design.md
trade_record_strategy = st.fixed_dictionaries({
    "symbol": symbol_strategy,
    "exchange": exchange_strategy,
    "timestamp": timestamp_strategy,
    "price": price_strategy,
    "size": size_strategy,
    "side": side_strategy,
    "trade_id": trade_id_strategy,
})


def create_trade_record_from_dict(trade_dict: Dict[str, Any]) -> PersistenceTradeRecord:
    """Create a PersistenceTradeRecord from a dictionary of trade data."""
    return PersistenceTradeRecord(
        symbol=trade_dict["symbol"],
        exchange=trade_dict["exchange"],
        timestamp=datetime.fromtimestamp(trade_dict["timestamp"], tz=timezone.utc),
        price=trade_dict["price"],
        size=trade_dict["size"],
        side=trade_dict["side"],
        trade_id=trade_dict["trade_id"],
    )


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
# Property 7: Timestamp Preservation
# =============================================================================


class TestTimestampPreservation:
    """Property 7: Timestamp Preservation

    For any trade with an exchange timestamp, the persisted TradeRecord's
    timestamp SHALL equal the original exchange timestamp (not the local
    processing time).

    **Validates: Requirements 2.6**
    """

    @given(trade=trade_record_strategy)
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_exchange_timestamp_preserved_in_buffer(
        self,
        trade: Dict[str, Any],
    ):
        """Verify that the exchange timestamp is preserved when buffering a trade.

        The buffered trade's timestamp should exactly match the original
        exchange timestamp provided, not the local processing time.

        **Validates: Requirements 2.6**
        """
        pool = create_mock_pool()
        config = TradeRecordWriterConfig(enabled=True, batch_size=1000)
        writer = TradeRecordWriter(pool, config)

        # Create trade record with specific exchange timestamp
        exchange_timestamp = datetime.fromtimestamp(trade["timestamp"], tz=timezone.utc)
        trade_record = PersistenceTradeRecord(
            symbol=trade["symbol"],
            exchange=trade["exchange"],
            timestamp=exchange_timestamp,
            price=trade["price"],
            size=trade["size"],
            side=trade["side"],
            trade_id=trade["trade_id"],
        )

        # Record the trade
        await writer.record(trade_record)

        # Verify the buffered trade has the exact exchange timestamp
        assert writer.get_buffer_size() == 1
        buffered_trade = writer._buffer[0]

        assert buffered_trade.timestamp == exchange_timestamp, (
            f"Timestamp should be preserved: expected {exchange_timestamp}, "
            f"got {buffered_trade.timestamp}"
        )

    @given(trade=trade_record_strategy)
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_timestamp_not_replaced_with_local_time(
        self,
        trade: Dict[str, Any],
    ):
        """Verify that the timestamp is not replaced with local processing time.

        Even if there's a delay between creating the trade record and
        recording it, the original exchange timestamp should be preserved.

        **Validates: Requirements 2.6**
        """
        pool = create_mock_pool()
        config = TradeRecordWriterConfig(enabled=True, batch_size=1000)
        writer = TradeRecordWriter(pool, config)

        # Create a trade with a timestamp in the past (simulating exchange timestamp)
        # Use a timestamp that is clearly different from "now"
        past_timestamp = datetime(2022, 6, 15, 12, 30, 45, 123456, tzinfo=timezone.utc)
        
        trade_record = PersistenceTradeRecord(
            symbol=trade["symbol"],
            exchange=trade["exchange"],
            timestamp=past_timestamp,
            price=trade["price"],
            size=trade["size"],
            side=trade["side"],
            trade_id=trade["trade_id"],
        )

        # Record the trade
        await writer.record(trade_record)

        # Verify the buffered trade has the exact past timestamp, not current time
        assert writer.get_buffer_size() == 1
        buffered_trade = writer._buffer[0]

        # The timestamp should be the past timestamp, not close to now
        assert buffered_trade.timestamp == past_timestamp, (
            f"Timestamp should be preserved as {past_timestamp}, "
            f"got {buffered_trade.timestamp}"
        )

        # Additional check: the timestamp should NOT be close to current time
        now = datetime.now(timezone.utc)
        time_diff = abs((now - buffered_trade.timestamp).total_seconds())
        # The past timestamp should be at least 1 year old
        assert time_diff > 365 * 24 * 3600, (
            f"Timestamp appears to have been replaced with local time. "
            f"Expected timestamp from 2022, got {buffered_trade.timestamp}"
        )

    @given(trade=trade_record_strategy)
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_timestamp_microsecond_precision_preserved(
        self,
        trade: Dict[str, Any],
    ):
        """Verify that microsecond precision is preserved in timestamps.

        Exchange timestamps often have microsecond precision which must
        be preserved for accurate replay.

        **Validates: Requirements 2.6**
        """
        pool = create_mock_pool()
        config = TradeRecordWriterConfig(enabled=True, batch_size=1000)
        writer = TradeRecordWriter(pool, config)

        # Create a timestamp with specific microseconds
        exchange_timestamp = datetime.fromtimestamp(trade["timestamp"], tz=timezone.utc)
        
        trade_record = PersistenceTradeRecord(
            symbol=trade["symbol"],
            exchange=trade["exchange"],
            timestamp=exchange_timestamp,
            price=trade["price"],
            size=trade["size"],
            side=trade["side"],
            trade_id=trade["trade_id"],
        )

        await writer.record(trade_record)

        assert writer.get_buffer_size() == 1
        buffered_trade = writer._buffer[0]

        # Verify microsecond precision is preserved
        assert buffered_trade.timestamp.microsecond == exchange_timestamp.microsecond, (
            f"Microsecond precision should be preserved: "
            f"expected {exchange_timestamp.microsecond}, "
            f"got {buffered_trade.timestamp.microsecond}"
        )

    @given(trade=trade_record_strategy)
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_timestamp_timezone_preserved(
        self,
        trade: Dict[str, Any],
    ):
        """Verify that timezone information is preserved in timestamps.

        The timestamp should maintain its UTC timezone information.

        **Validates: Requirements 2.6**
        """
        pool = create_mock_pool()
        config = TradeRecordWriterConfig(enabled=True, batch_size=1000)
        writer = TradeRecordWriter(pool, config)

        exchange_timestamp = datetime.fromtimestamp(trade["timestamp"], tz=timezone.utc)
        
        trade_record = PersistenceTradeRecord(
            symbol=trade["symbol"],
            exchange=trade["exchange"],
            timestamp=exchange_timestamp,
            price=trade["price"],
            size=trade["size"],
            side=trade["side"],
            trade_id=trade["trade_id"],
        )

        await writer.record(trade_record)

        assert writer.get_buffer_size() == 1
        buffered_trade = writer._buffer[0]

        # Verify timezone is preserved
        assert buffered_trade.timestamp.tzinfo is not None, (
            "Timestamp should have timezone info"
        )
        assert buffered_trade.timestamp.tzinfo == timezone.utc, (
            f"Timestamp should be in UTC, got {buffered_trade.timestamp.tzinfo}"
        )

    @given(trades=st.lists(trade_record_strategy, min_size=2, max_size=10))
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_multiple_trades_timestamps_preserved(
        self,
        trades: list,
    ):
        """Verify that timestamps are preserved for multiple trades.

        When multiple trades are recorded, each should preserve its
        original exchange timestamp.

        **Validates: Requirements 2.6**
        """
        pool = create_mock_pool()
        config = TradeRecordWriterConfig(enabled=True, batch_size=1000)
        writer = TradeRecordWriter(pool, config)

        # Create trade records with their exchange timestamps
        trade_records = []
        for trade in trades:
            exchange_timestamp = datetime.fromtimestamp(trade["timestamp"], tz=timezone.utc)
            trade_record = PersistenceTradeRecord(
                symbol=trade["symbol"],
                exchange=trade["exchange"],
                timestamp=exchange_timestamp,
                price=trade["price"],
                size=trade["size"],
                side=trade["side"],
                trade_id=trade["trade_id"],
            )
            trade_records.append(trade_record)
            await writer.record(trade_record)

        # Verify all timestamps are preserved
        assert writer.get_buffer_size() == len(trades)
        
        for i, (original, buffered) in enumerate(zip(trade_records, writer._buffer)):
            assert buffered.timestamp == original.timestamp, (
                f"Trade {i}: Timestamp should be preserved: "
                f"expected {original.timestamp}, got {buffered.timestamp}"
            )

    @given(trade=trade_record_strategy)
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_timestamp_preserved_through_batch_insert_preparation(
        self,
        trade: Dict[str, Any],
    ):
        """Verify that timestamp is preserved when preparing for batch insert.

        The _batch_insert method should use the original exchange timestamp
        when preparing records for database insertion.

        **Validates: Requirements 2.6**
        """
        pool = create_mock_pool()
        conn = AsyncMock()
        
        # Capture the records passed to executemany
        captured_records = []
        async def capture_executemany(query, records):
            captured_records.extend(records)
        
        conn.executemany = capture_executemany
        pool.acquire = MagicMock(
            return_value=AsyncMock(
                __aenter__=AsyncMock(return_value=conn),
                __aexit__=AsyncMock(),
            )
        )
        
        config = TradeRecordWriterConfig(enabled=True, batch_size=1000)
        writer = TradeRecordWriter(pool, config)

        exchange_timestamp = datetime.fromtimestamp(trade["timestamp"], tz=timezone.utc)
        trade_record = PersistenceTradeRecord(
            symbol=trade["symbol"],
            exchange=trade["exchange"],
            timestamp=exchange_timestamp,
            price=trade["price"],
            size=trade["size"],
            side=trade["side"],
            trade_id=trade["trade_id"],
        )

        await writer.record(trade_record)
        await writer.flush()

        # Verify the timestamp in the batch insert record
        assert len(captured_records) == 1
        # The first element of the tuple is the timestamp (ts)
        inserted_timestamp = captured_records[0][0]
        
        assert inserted_timestamp == exchange_timestamp, (
            f"Timestamp in batch insert should be preserved: "
            f"expected {exchange_timestamp}, got {inserted_timestamp}"
        )

    @given(
        trade=trade_record_strategy,
        offset_hours=st.integers(min_value=-12, max_value=12),
    )
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_timestamp_preserved_regardless_of_time_difference(
        self,
        trade: Dict[str, Any],
        offset_hours: int,
    ):
        """Verify timestamp preservation regardless of time difference from now.

        Exchange timestamps can be in the past (delayed data) or slightly
        in the future (clock skew). All should be preserved exactly.

        **Validates: Requirements 2.6**
        """
        pool = create_mock_pool()
        config = TradeRecordWriterConfig(enabled=True, batch_size=1000)
        writer = TradeRecordWriter(pool, config)

        # Create a timestamp with an offset from the generated timestamp
        base_timestamp = datetime.fromtimestamp(trade["timestamp"], tz=timezone.utc)
        exchange_timestamp = base_timestamp + timedelta(hours=offset_hours)
        
        trade_record = PersistenceTradeRecord(
            symbol=trade["symbol"],
            exchange=trade["exchange"],
            timestamp=exchange_timestamp,
            price=trade["price"],
            size=trade["size"],
            side=trade["side"],
            trade_id=trade["trade_id"],
        )

        await writer.record(trade_record)

        assert writer.get_buffer_size() == 1
        buffered_trade = writer._buffer[0]

        assert buffered_trade.timestamp == exchange_timestamp, (
            f"Timestamp should be preserved regardless of offset: "
            f"expected {exchange_timestamp}, got {buffered_trade.timestamp}"
        )

    @given(trade=trade_record_strategy)
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_timestamp_identity_property(
        self,
        trade: Dict[str, Any],
    ):
        """Verify the identity property: input timestamp equals output timestamp.

        This is the core property test: for any trade with an exchange
        timestamp T, the persisted TradeRecord's timestamp SHALL equal T.

        **Validates: Requirements 2.6**
        """
        pool = create_mock_pool()
        config = TradeRecordWriterConfig(enabled=True, batch_size=1000)
        writer = TradeRecordWriter(pool, config)

        # Create trade with exchange timestamp
        exchange_timestamp = datetime.fromtimestamp(trade["timestamp"], tz=timezone.utc)
        trade_record = PersistenceTradeRecord(
            symbol=trade["symbol"],
            exchange=trade["exchange"],
            timestamp=exchange_timestamp,
            price=trade["price"],
            size=trade["size"],
            side=trade["side"],
            trade_id=trade["trade_id"],
        )

        await writer.record(trade_record)

        assert writer.get_buffer_size() == 1
        buffered_trade = writer._buffer[0]

        # Core property: input timestamp == output timestamp
        assert buffered_trade.timestamp == exchange_timestamp, (
            f"Identity property violated: "
            f"input timestamp {exchange_timestamp} != "
            f"output timestamp {buffered_trade.timestamp}"
        )

        # Also verify the Unix timestamp representation is identical
        input_unix = exchange_timestamp.timestamp()
        output_unix = buffered_trade.timestamp.timestamp()
        assert input_unix == output_unix, (
            f"Unix timestamp identity violated: "
            f"input {input_unix} != output {output_unix}"
        )
