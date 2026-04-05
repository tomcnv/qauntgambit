"""Property tests for trade round-trip replay.

Feature: live-orderbook-data-storage, Property 15: Trade Round-Trip Replay

This module tests that storing a TradeRecord and then querying it back
produces a TradeRecord with identical fields.

**Validates: Requirements 6.6**
"""

from __future__ import annotations

import math
from datetime import datetime, timezone

from hypothesis import given, settings, strategies as st

from quantgambit.storage.persistence import PersistenceTradeRecord
from quantgambit.storage.trade_record_reader import TradeRecordReader


# Generator strategies for trade data
trade_symbol = st.text(
    min_size=1,
    max_size=20,
    alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="/-"),
)

trade_exchange = st.sampled_from(["binance", "coinbase", "kraken", "okx", "bybit"])

trade_timestamp = st.floats(
    min_value=1600000000.0,
    max_value=2000000000.0,
    allow_nan=False,
    allow_infinity=False,
)

trade_price = st.floats(
    min_value=0.01,
    max_value=100000.0,
    allow_nan=False,
    allow_infinity=False,
)

trade_size = st.floats(
    min_value=0.0001,
    max_value=10000.0,
    allow_nan=False,
    allow_infinity=False,
)

trade_side = st.sampled_from(["buy", "sell"])

trade_id = st.text(
    min_size=1,
    max_size=50,
    alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="-_"),
)


def trades_are_identical(
    original: PersistenceTradeRecord,
    retrieved: PersistenceTradeRecord,
    price_tolerance: float = 1e-9,
    size_tolerance: float = 1e-9,
) -> bool:
    """Check if two PersistenceTradeRecord objects are identical.
    
    String fields are compared exactly. Floating-point fields are
    compared with a tolerance to account for serialization/deserialization.
    Timestamps are compared for equality.
    """
    if original.symbol != retrieved.symbol:
        return False
    
    if original.exchange != retrieved.exchange:
        return False
    
    if original.side != retrieved.side:
        return False
    
    if original.trade_id != retrieved.trade_id:
        return False
    
    # Compare timestamps - they should be equal
    if original.timestamp != retrieved.timestamp:
        return False
    
    # Compare floating-point fields with tolerance
    if not math.isclose(original.price, retrieved.price, rel_tol=price_tolerance):
        return False
    
    if not math.isclose(original.size, retrieved.size, rel_tol=size_tolerance):
        return False
    
    return True


def create_trade_record(
    symbol: str,
    exchange: str,
    timestamp: float,
    price: float,
    size: float,
    side: str,
    trade_id: str,
) -> PersistenceTradeRecord:
    """Create a PersistenceTradeRecord from raw values."""
    return PersistenceTradeRecord(
        symbol=symbol,
        exchange=exchange,
        timestamp=datetime.fromtimestamp(timestamp, tz=timezone.utc),
        price=price,
        size=size,
        side=side,
        trade_id=trade_id,
    )


class TestTradeRoundTrip:
    """Property tests for trade round-trip replay.
    
    **Property 15: Trade Round-Trip Replay**
    
    *For any* valid TradeRecord, storing it and then querying it back
    SHALL produce a TradeRecord with identical symbol, exchange, timestamp,
    price, size, side, and trade_id.
    
    **Validates: Requirements 6.6**
    """
    
    @settings(max_examples=100)
    @given(
        symbol=trade_symbol,
        exchange=trade_exchange,
        timestamp=trade_timestamp,
        price=trade_price,
        size=trade_size,
        side=trade_side,
        trade_id_str=trade_id,
    )
    def test_trade_record_fields_preserved(
        self,
        symbol: str,
        exchange: str,
        timestamp: float,
        price: float,
        size: float,
        side: str,
        trade_id_str: str,
    ) -> None:
        """Test that all trade record fields are preserved through round-trip.
        
        This test simulates the round-trip by creating a trade record,
        converting it to database row format, and then converting back.
        The actual database round-trip is tested in integration tests.
        
        **Validates: Requirements 6.6**
        """
        # Create original trade record
        original = create_trade_record(
            symbol=symbol,
            exchange=exchange,
            timestamp=timestamp,
            price=price,
            size=size,
            side=side,
            trade_id=trade_id_str,
        )
        
        # Simulate database row (what would be stored and retrieved)
        # This mimics the _row_to_trade conversion in TradeRecordReader
        simulated_row = {
            "symbol": original.symbol,
            "exchange": original.exchange,
            "ts": original.timestamp,
            "price": original.price,
            "size": original.size,
            "side": original.side,
            "trade_id": original.trade_id,
        }
        
        # Create a mock reader to test the _row_to_trade method
        reader = TradeRecordReader.__new__(TradeRecordReader)
        reader.pool = None  # Not needed for _row_to_trade
        reader.config = None
        
        # Convert back from row format
        retrieved = reader._row_to_trade(simulated_row)
        
        # Verify all fields are identical
        assert trades_are_identical(original, retrieved), (
            f"Trade records not identical after round-trip:\n"
            f"Original: {original}\n"
            f"Retrieved: {retrieved}"
        )
    
    @settings(max_examples=100)
    @given(
        symbol=trade_symbol,
        exchange=trade_exchange,
        timestamp=trade_timestamp,
        price=trade_price,
        size=trade_size,
        side=trade_side,
        trade_id_str=trade_id,
    )
    def test_timestamp_preserved_exactly(
        self,
        symbol: str,
        exchange: str,
        timestamp: float,
        price: float,
        size: float,
        side: str,
        trade_id_str: str,
    ) -> None:
        """Test that timestamp is preserved exactly through round-trip.
        
        The original exchange timestamp must be preserved exactly to
        ensure accurate replay during backtesting.
        
        **Validates: Requirements 6.6**
        """
        # Create original trade record
        original = create_trade_record(
            symbol=symbol,
            exchange=exchange,
            timestamp=timestamp,
            price=price,
            size=size,
            side=side,
            trade_id=trade_id_str,
        )
        
        # Simulate database row
        simulated_row = {
            "symbol": original.symbol,
            "exchange": original.exchange,
            "ts": original.timestamp,
            "price": original.price,
            "size": original.size,
            "side": original.side,
            "trade_id": original.trade_id,
        }
        
        # Convert back from row format
        reader = TradeRecordReader.__new__(TradeRecordReader)
        reader.pool = None
        reader.config = None
        
        retrieved = reader._row_to_trade(simulated_row)
        
        # Verify timestamp is exactly equal
        assert original.timestamp == retrieved.timestamp, (
            f"Timestamp not preserved:\n"
            f"Original: {original.timestamp}\n"
            f"Retrieved: {retrieved.timestamp}"
        )
    
    @settings(max_examples=100)
    @given(
        symbol=trade_symbol,
        exchange=trade_exchange,
        timestamp=trade_timestamp,
        price=trade_price,
        size=trade_size,
        side=trade_side,
        trade_id_str=trade_id,
    )
    def test_trade_id_preserved_exactly(
        self,
        symbol: str,
        exchange: str,
        timestamp: float,
        price: float,
        size: float,
        side: str,
        trade_id_str: str,
    ) -> None:
        """Test that trade_id is preserved exactly through round-trip.
        
        The trade_id is used for deduplication and must be preserved
        exactly to ensure correct behavior.
        
        **Validates: Requirements 6.6**
        """
        # Create original trade record
        original = create_trade_record(
            symbol=symbol,
            exchange=exchange,
            timestamp=timestamp,
            price=price,
            size=size,
            side=side,
            trade_id=trade_id_str,
        )
        
        # Simulate database row
        simulated_row = {
            "symbol": original.symbol,
            "exchange": original.exchange,
            "ts": original.timestamp,
            "price": original.price,
            "size": original.size,
            "side": original.side,
            "trade_id": original.trade_id,
        }
        
        # Convert back from row format
        reader = TradeRecordReader.__new__(TradeRecordReader)
        reader.pool = None
        reader.config = None
        
        retrieved = reader._row_to_trade(simulated_row)
        
        # Verify trade_id is exactly equal
        assert original.trade_id == retrieved.trade_id, (
            f"Trade ID not preserved:\n"
            f"Original: {original.trade_id}\n"
            f"Retrieved: {retrieved.trade_id}"
        )
    
    @settings(max_examples=100)
    @given(
        symbol=trade_symbol,
        exchange=trade_exchange,
        timestamp=trade_timestamp,
        price=trade_price,
        size=trade_size,
        side=trade_side,
        trade_id_str=trade_id,
    )
    def test_side_preserved_exactly(
        self,
        symbol: str,
        exchange: str,
        timestamp: float,
        price: float,
        size: float,
        side: str,
        trade_id_str: str,
    ) -> None:
        """Test that side is preserved exactly through round-trip.
        
        The side (buy/sell) must be preserved exactly for accurate
        volume analysis and VWAP calculation.
        
        **Validates: Requirements 6.6**
        """
        # Create original trade record
        original = create_trade_record(
            symbol=symbol,
            exchange=exchange,
            timestamp=timestamp,
            price=price,
            size=size,
            side=side,
            trade_id=trade_id_str,
        )
        
        # Simulate database row
        simulated_row = {
            "symbol": original.symbol,
            "exchange": original.exchange,
            "ts": original.timestamp,
            "price": original.price,
            "size": original.size,
            "side": original.side,
            "trade_id": original.trade_id,
        }
        
        # Convert back from row format
        reader = TradeRecordReader.__new__(TradeRecordReader)
        reader.pool = None
        reader.config = None
        
        retrieved = reader._row_to_trade(simulated_row)
        
        # Verify side is exactly equal
        assert original.side == retrieved.side, (
            f"Side not preserved:\n"
            f"Original: {original.side}\n"
            f"Retrieved: {retrieved.side}"
        )
    
    @settings(max_examples=100)
    @given(
        symbol=trade_symbol,
        exchange=trade_exchange,
        timestamp=trade_timestamp,
        price=trade_price,
        size=trade_size,
        side=trade_side,
        trade_id_str=trade_id,
    )
    def test_price_and_size_preserved_within_tolerance(
        self,
        symbol: str,
        exchange: str,
        timestamp: float,
        price: float,
        size: float,
        side: str,
        trade_id_str: str,
    ) -> None:
        """Test that price and size are preserved within floating-point tolerance.
        
        Price and size may have minor floating-point differences due to
        serialization, but should be within acceptable tolerance.
        
        **Validates: Requirements 6.6**
        """
        # Create original trade record
        original = create_trade_record(
            symbol=symbol,
            exchange=exchange,
            timestamp=timestamp,
            price=price,
            size=size,
            side=side,
            trade_id=trade_id_str,
        )
        
        # Simulate database row
        simulated_row = {
            "symbol": original.symbol,
            "exchange": original.exchange,
            "ts": original.timestamp,
            "price": original.price,
            "size": original.size,
            "side": original.side,
            "trade_id": original.trade_id,
        }
        
        # Convert back from row format
        reader = TradeRecordReader.__new__(TradeRecordReader)
        reader.pool = None
        reader.config = None
        
        retrieved = reader._row_to_trade(simulated_row)
        
        # Verify price is within tolerance
        assert math.isclose(original.price, retrieved.price, rel_tol=1e-9), (
            f"Price not within tolerance:\n"
            f"Original: {original.price}\n"
            f"Retrieved: {retrieved.price}"
        )
        
        # Verify size is within tolerance
        assert math.isclose(original.size, retrieved.size, rel_tol=1e-9), (
            f"Size not within tolerance:\n"
            f"Original: {original.size}\n"
            f"Retrieved: {retrieved.size}"
        )
