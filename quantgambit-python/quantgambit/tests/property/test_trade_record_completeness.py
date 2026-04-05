"""Property-based tests for trade record completeness.

Feature: live-orderbook-data-storage, Property 3: Trade Record Completeness

Tests that for any valid trade event, the resulting TradeRecord SHALL contain:
symbol (non-empty string), exchange (non-empty string), timestamp (valid datetime),
price (positive float), size (positive float), side ("buy" or "sell"), and
trade_id (non-empty string).

**Validates: Requirements 2.2**
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from hypothesis import given, strategies as st, settings

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
# Property 3: Trade Record Completeness
# =============================================================================


class TestTradeRecordCompleteness:
    """Property 3: Trade Record Completeness

    For any valid trade event, the resulting TradeRecord SHALL contain:
    symbol (non-empty string), exchange (non-empty string), timestamp (valid datetime),
    price (positive float), size (positive float), side ("buy" or "sell"), and
    trade_id (non-empty string).

    **Validates: Requirements 2.2**
    """

    @given(trade=trade_record_strategy)
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_trade_record_contains_non_empty_symbol(
        self,
        trade: Dict[str, Any],
    ):
        """Verify that recorded trade contains a non-empty symbol.

        **Validates: Requirements 2.2**
        """
        pool = create_mock_pool()
        config = TradeRecordWriterConfig(enabled=True, batch_size=1000)
        writer = TradeRecordWriter(pool, config)

        trade_record = create_trade_record_from_dict(trade)
        await writer.record(trade_record)

        assert writer.get_buffer_size() == 1
        buffered_trade = writer._buffer[0]

        # Verify symbol is non-empty string
        assert isinstance(buffered_trade.symbol, str), (
            f"Symbol should be a string, got {type(buffered_trade.symbol)}"
        )
        assert len(buffered_trade.symbol) > 0, "Symbol should be non-empty"
        assert buffered_trade.symbol == trade["symbol"], (
            f"Symbol should match input: {trade['symbol']}"
        )

    @given(trade=trade_record_strategy)
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_trade_record_contains_non_empty_exchange(
        self,
        trade: Dict[str, Any],
    ):
        """Verify that recorded trade contains a non-empty exchange.

        **Validates: Requirements 2.2**
        """
        pool = create_mock_pool()
        config = TradeRecordWriterConfig(enabled=True, batch_size=1000)
        writer = TradeRecordWriter(pool, config)

        trade_record = create_trade_record_from_dict(trade)
        await writer.record(trade_record)

        assert writer.get_buffer_size() == 1
        buffered_trade = writer._buffer[0]

        # Verify exchange is non-empty string
        assert isinstance(buffered_trade.exchange, str), (
            f"Exchange should be a string, got {type(buffered_trade.exchange)}"
        )
        assert len(buffered_trade.exchange) > 0, "Exchange should be non-empty"
        assert buffered_trade.exchange == trade["exchange"], (
            f"Exchange should match input: {trade['exchange']}"
        )

    @given(trade=trade_record_strategy)
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_trade_record_contains_valid_timestamp(
        self,
        trade: Dict[str, Any],
    ):
        """Verify that recorded trade contains a valid datetime timestamp.

        **Validates: Requirements 2.2**
        """
        pool = create_mock_pool()
        config = TradeRecordWriterConfig(enabled=True, batch_size=1000)
        writer = TradeRecordWriter(pool, config)

        trade_record = create_trade_record_from_dict(trade)
        await writer.record(trade_record)

        assert writer.get_buffer_size() == 1
        buffered_trade = writer._buffer[0]

        # Verify timestamp is a valid datetime
        assert isinstance(buffered_trade.timestamp, datetime), (
            f"Timestamp should be a datetime, got {type(buffered_trade.timestamp)}"
        )
        # Verify timestamp has timezone info (UTC)
        assert buffered_trade.timestamp.tzinfo is not None, (
            "Timestamp should have timezone info"
        )
        # Verify timestamp matches input (converted from Unix timestamp)
        expected_dt = datetime.fromtimestamp(trade["timestamp"], tz=timezone.utc)
        assert buffered_trade.timestamp == expected_dt, (
            f"Timestamp should match input: expected {expected_dt}, got {buffered_trade.timestamp}"
        )

    @given(trade=trade_record_strategy)
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_trade_record_contains_positive_price(
        self,
        trade: Dict[str, Any],
    ):
        """Verify that recorded trade contains a positive price.

        **Validates: Requirements 2.2**
        """
        pool = create_mock_pool()
        config = TradeRecordWriterConfig(enabled=True, batch_size=1000)
        writer = TradeRecordWriter(pool, config)

        trade_record = create_trade_record_from_dict(trade)
        await writer.record(trade_record)

        assert writer.get_buffer_size() == 1
        buffered_trade = writer._buffer[0]

        # Verify price is a positive float
        assert isinstance(buffered_trade.price, (int, float)), (
            f"Price should be numeric, got {type(buffered_trade.price)}"
        )
        assert buffered_trade.price > 0, (
            f"Price should be positive, got {buffered_trade.price}"
        )
        assert buffered_trade.price == trade["price"], (
            f"Price should match input: {trade['price']}"
        )

    @given(trade=trade_record_strategy)
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_trade_record_contains_positive_size(
        self,
        trade: Dict[str, Any],
    ):
        """Verify that recorded trade contains a positive size.

        **Validates: Requirements 2.2**
        """
        pool = create_mock_pool()
        config = TradeRecordWriterConfig(enabled=True, batch_size=1000)
        writer = TradeRecordWriter(pool, config)

        trade_record = create_trade_record_from_dict(trade)
        await writer.record(trade_record)

        assert writer.get_buffer_size() == 1
        buffered_trade = writer._buffer[0]

        # Verify size is a positive float
        assert isinstance(buffered_trade.size, (int, float)), (
            f"Size should be numeric, got {type(buffered_trade.size)}"
        )
        assert buffered_trade.size > 0, (
            f"Size should be positive, got {buffered_trade.size}"
        )
        assert buffered_trade.size == trade["size"], (
            f"Size should match input: {trade['size']}"
        )

    @given(trade=trade_record_strategy)
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_trade_record_contains_valid_side(
        self,
        trade: Dict[str, Any],
    ):
        """Verify that recorded trade contains a valid side ("buy" or "sell").

        **Validates: Requirements 2.2**
        """
        pool = create_mock_pool()
        config = TradeRecordWriterConfig(enabled=True, batch_size=1000)
        writer = TradeRecordWriter(pool, config)

        trade_record = create_trade_record_from_dict(trade)
        await writer.record(trade_record)

        assert writer.get_buffer_size() == 1
        buffered_trade = writer._buffer[0]

        # Verify side is "buy" or "sell"
        assert isinstance(buffered_trade.side, str), (
            f"Side should be a string, got {type(buffered_trade.side)}"
        )
        assert buffered_trade.side in ("buy", "sell"), (
            f"Side should be 'buy' or 'sell', got {buffered_trade.side!r}"
        )
        assert buffered_trade.side == trade["side"], (
            f"Side should match input: {trade['side']}"
        )

    @given(trade=trade_record_strategy)
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_trade_record_contains_non_empty_trade_id(
        self,
        trade: Dict[str, Any],
    ):
        """Verify that recorded trade contains a non-empty trade_id.

        **Validates: Requirements 2.2**
        """
        pool = create_mock_pool()
        config = TradeRecordWriterConfig(enabled=True, batch_size=1000)
        writer = TradeRecordWriter(pool, config)

        trade_record = create_trade_record_from_dict(trade)
        await writer.record(trade_record)

        assert writer.get_buffer_size() == 1
        buffered_trade = writer._buffer[0]

        # Verify trade_id is non-empty string
        assert isinstance(buffered_trade.trade_id, str), (
            f"Trade ID should be a string, got {type(buffered_trade.trade_id)}"
        )
        assert len(buffered_trade.trade_id) > 0, "Trade ID should be non-empty"
        assert buffered_trade.trade_id == trade["trade_id"], (
            f"Trade ID should match input: {trade['trade_id']}"
        )

    @given(trade=trade_record_strategy)
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_trade_record_all_fields_present(
        self,
        trade: Dict[str, Any],
    ):
        """Verify that recorded trade contains all required fields.

        This is the comprehensive test that verifies all fields are present
        and have the correct types in a single test.

        **Validates: Requirements 2.2**
        """
        pool = create_mock_pool()
        config = TradeRecordWriterConfig(enabled=True, batch_size=1000)
        writer = TradeRecordWriter(pool, config)

        trade_record = create_trade_record_from_dict(trade)
        await writer.record(trade_record)

        assert writer.get_buffer_size() == 1
        buffered_trade = writer._buffer[0]

        # Verify all required fields are present and have correct types
        # 1. Symbol - non-empty string
        assert isinstance(buffered_trade.symbol, str) and len(buffered_trade.symbol) > 0, (
            f"Symbol should be non-empty string, got {buffered_trade.symbol!r}"
        )

        # 2. Exchange - non-empty string
        assert isinstance(buffered_trade.exchange, str) and len(buffered_trade.exchange) > 0, (
            f"Exchange should be non-empty string, got {buffered_trade.exchange!r}"
        )

        # 3. Timestamp - valid datetime
        assert isinstance(buffered_trade.timestamp, datetime), (
            f"Timestamp should be datetime, got {type(buffered_trade.timestamp)}"
        )

        # 4. Price - positive float
        assert isinstance(buffered_trade.price, (int, float)) and buffered_trade.price > 0, (
            f"Price should be positive number, got {buffered_trade.price}"
        )

        # 5. Size - positive float
        assert isinstance(buffered_trade.size, (int, float)) and buffered_trade.size > 0, (
            f"Size should be positive number, got {buffered_trade.size}"
        )

        # 6. Side - "buy" or "sell"
        assert buffered_trade.side in ("buy", "sell"), (
            f"Side should be 'buy' or 'sell', got {buffered_trade.side!r}"
        )

        # 7. Trade ID - non-empty string
        assert isinstance(buffered_trade.trade_id, str) and len(buffered_trade.trade_id) > 0, (
            f"Trade ID should be non-empty string, got {buffered_trade.trade_id!r}"
        )

    @given(trade=trade_record_strategy)
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_trade_record_preserves_input_data(
        self,
        trade: Dict[str, Any],
    ):
        """Verify that trade record preserves all input data exactly.

        The trade record should contain the exact values passed to record().

        **Validates: Requirements 2.2**
        """
        pool = create_mock_pool()
        config = TradeRecordWriterConfig(enabled=True, batch_size=1000)
        writer = TradeRecordWriter(pool, config)

        trade_record = create_trade_record_from_dict(trade)
        await writer.record(trade_record)

        assert writer.get_buffer_size() == 1
        buffered_trade = writer._buffer[0]

        # Verify all input data is preserved
        assert buffered_trade.symbol == trade["symbol"], (
            f"Symbol mismatch: expected {trade['symbol']}, got {buffered_trade.symbol}"
        )
        assert buffered_trade.exchange == trade["exchange"], (
            f"Exchange mismatch: expected {trade['exchange']}, got {buffered_trade.exchange}"
        )
        expected_dt = datetime.fromtimestamp(trade["timestamp"], tz=timezone.utc)
        assert buffered_trade.timestamp == expected_dt, (
            f"Timestamp mismatch: expected {expected_dt}, got {buffered_trade.timestamp}"
        )
        assert buffered_trade.price == trade["price"], (
            f"Price mismatch: expected {trade['price']}, got {buffered_trade.price}"
        )
        assert buffered_trade.size == trade["size"], (
            f"Size mismatch: expected {trade['size']}, got {buffered_trade.size}"
        )
        assert buffered_trade.side == trade["side"], (
            f"Side mismatch: expected {trade['side']}, got {buffered_trade.side}"
        )
        assert buffered_trade.trade_id == trade["trade_id"], (
            f"Trade ID mismatch: expected {trade['trade_id']}, got {buffered_trade.trade_id}"
        )

    @given(trade=trade_record_strategy)
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_trade_record_not_buffered_when_disabled(
        self,
        trade: Dict[str, Any],
    ):
        """Verify that trade records are not buffered when writer is disabled.

        When config.enabled is False, the writer should not buffer any trades.

        **Validates: Requirements 2.2**
        """
        pool = create_mock_pool()
        config = TradeRecordWriterConfig(enabled=False, batch_size=1000)
        writer = TradeRecordWriter(pool, config)

        trade_record = create_trade_record_from_dict(trade)
        await writer.record(trade_record)

        # Verify no trade was buffered when disabled
        assert writer.get_buffer_size() == 0, (
            f"Buffer should be empty when disabled, got {writer.get_buffer_size()} trades"
        )

    @given(trades=st.lists(trade_record_strategy, min_size=1, max_size=10))
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_multiple_trade_records_all_complete(
        self,
        trades: list,
    ):
        """Verify that multiple trade records all contain complete data.

        When multiple trades are recorded, each should have all required fields.

        **Validates: Requirements 2.2**
        """
        pool = create_mock_pool()
        config = TradeRecordWriterConfig(enabled=True, batch_size=1000)
        writer = TradeRecordWriter(pool, config)

        for trade in trades:
            trade_record = create_trade_record_from_dict(trade)
            await writer.record(trade_record)

        assert writer.get_buffer_size() == len(trades), (
            f"Buffer should contain {len(trades)} trades, got {writer.get_buffer_size()}"
        )

        # Verify each buffered trade has all required fields
        for i, buffered_trade in enumerate(writer._buffer):
            # Symbol - non-empty string
            assert isinstance(buffered_trade.symbol, str) and len(buffered_trade.symbol) > 0, (
                f"Trade {i}: Symbol should be non-empty string"
            )

            # Exchange - non-empty string
            assert isinstance(buffered_trade.exchange, str) and len(buffered_trade.exchange) > 0, (
                f"Trade {i}: Exchange should be non-empty string"
            )

            # Timestamp - valid datetime
            assert isinstance(buffered_trade.timestamp, datetime), (
                f"Trade {i}: Timestamp should be datetime"
            )

            # Price - positive float
            assert isinstance(buffered_trade.price, (int, float)) and buffered_trade.price > 0, (
                f"Trade {i}: Price should be positive number"
            )

            # Size - positive float
            assert isinstance(buffered_trade.size, (int, float)) and buffered_trade.size > 0, (
                f"Trade {i}: Size should be positive number"
            )

            # Side - "buy" or "sell"
            assert buffered_trade.side in ("buy", "sell"), (
                f"Trade {i}: Side should be 'buy' or 'sell'"
            )

            # Trade ID - non-empty string
            assert isinstance(buffered_trade.trade_id, str) and len(buffered_trade.trade_id) > 0, (
                f"Trade {i}: Trade ID should be non-empty string"
            )
