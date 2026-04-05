"""Unit tests for TradeRecordWriter.

Tests the trade record buffering and timestamp preservation functionality.

Feature: live-orderbook-data-storage
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from quantgambit.storage.persistence import (
    PersistenceTradeRecord,
    TradeRecordWriterConfig,
)
from quantgambit.storage.trade_record_writer import TradeRecordWriter


class TestTradeRecordWriter:
    """Tests for TradeRecordWriter class."""

    @pytest.fixture
    def mock_pool(self):
        """Create a mock asyncpg pool."""
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

    @pytest.fixture
    def config(self):
        """Create a test configuration."""
        return TradeRecordWriterConfig(
            enabled=True,
            batch_size=10,
            flush_interval_sec=5.0,
            max_buffer_size=100,
            retry_max_attempts=3,
            retry_base_delay_sec=0.01,
        )

    @pytest.fixture
    def writer(self, mock_pool, config):
        """Create a writer instance for testing."""
        return TradeRecordWriter(mock_pool, config)

    @pytest.fixture
    def sample_trade(self):
        """Create a sample trade record for testing."""
        return PersistenceTradeRecord(
            symbol="BTC/USDT",
            exchange="binance",
            timestamp=datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc),
            price=50000.0,
            size=1.5,
            side="buy",
            trade_id="trade_123",
        )

    @pytest.mark.asyncio
    async def test_record_adds_to_buffer(self, writer, sample_trade):
        """Test that record() adds trade to buffer."""
        await writer.record(sample_trade)
        
        assert writer.get_buffer_size() == 1

    @pytest.mark.asyncio
    async def test_record_preserves_original_timestamp(self, writer, sample_trade):
        """Test that the original exchange timestamp is preserved.
        
        Validates: Requirements 2.6
        """
        original_timestamp = sample_trade.timestamp
        
        await writer.record(sample_trade)
        
        # Get the buffered trade
        buffered_trade = writer._buffer[0]
        
        # Verify timestamp is exactly the same as the original
        assert buffered_trade.timestamp == original_timestamp
        assert buffered_trade.timestamp.tzinfo == timezone.utc

    @pytest.mark.asyncio
    async def test_record_multiple_trades(self, writer):
        """Test that multiple trades can be buffered."""
        trades = [
            PersistenceTradeRecord(
                symbol="BTC/USDT",
                exchange="binance",
                timestamp=datetime(2024, 1, 15, 12, 0, i, tzinfo=timezone.utc),
                price=50000.0 + i,
                size=1.0,
                side="buy" if i % 2 == 0 else "sell",
                trade_id=f"trade_{i}",
            )
            for i in range(5)
        ]
        
        for trade in trades:
            await writer.record(trade)
        
        assert writer.get_buffer_size() == 5

    @pytest.mark.asyncio
    async def test_record_disabled(self, mock_pool):
        """Test that record is skipped when disabled."""
        config = TradeRecordWriterConfig(enabled=False)
        writer = TradeRecordWriter(mock_pool, config)
        
        trade = PersistenceTradeRecord(
            symbol="BTC/USDT",
            exchange="binance",
            timestamp=datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc),
            price=50000.0,
            size=1.0,
            side="buy",
            trade_id="trade_123",
        )
        
        await writer.record(trade)
        
        # Should not record when disabled
        assert writer.get_buffer_size() == 0

    @pytest.mark.asyncio
    async def test_flush_empty_buffer(self, writer):
        """Test that flushing empty buffer returns 0."""
        count = await writer.flush()
        assert count == 0

    @pytest.mark.asyncio
    async def test_flush_clears_buffer(self, writer, sample_trade):
        """Test that flush clears the buffer."""
        await writer.record(sample_trade)
        
        assert writer.get_buffer_size() == 1
        
        count = await writer.flush()
        
        assert count == 1
        assert writer.get_buffer_size() == 0

    @pytest.mark.asyncio
    async def test_batch_size_triggers_flush(self, mock_pool):
        """Test that reaching batch_size triggers a flush."""
        config = TradeRecordWriterConfig(
            enabled=True,
            batch_size=3,
        )
        writer = TradeRecordWriter(mock_pool, config)
        
        # Record 3 trades (batch_size)
        for i in range(3):
            trade = PersistenceTradeRecord(
                symbol="BTC/USDT",
                exchange="binance",
                timestamp=datetime(2024, 1, 15, 12, 0, i, tzinfo=timezone.utc),
                price=50000.0,
                size=1.0,
                side="buy",
                trade_id=f"trade_{i}",
            )
            await writer.record(trade)
        
        # Give the async flush task time to run
        await asyncio.sleep(0.1)
        
        # Buffer should be cleared after batch flush
        assert writer.get_buffer_size() == 0

    @pytest.mark.asyncio
    async def test_flush_calls_batch_insert(self, mock_pool, config, sample_trade):
        """Test that flush performs batch insert to database."""
        writer = TradeRecordWriter(mock_pool, config)
        
        await writer.record(sample_trade)
        await writer.flush()
        
        # Verify executemany was called
        conn = mock_pool.acquire.return_value.__aenter__.return_value
        conn.executemany.assert_called_once()
        
        # Verify the query and data
        call_args = conn.executemany.call_args
        query = call_args[0][0]
        records = call_args[0][1]
        
        assert "INSERT INTO trade_records" in query
        assert len(records) == 1
        
        # Verify the record contains the original timestamp
        record = records[0]
        assert record[0] == sample_trade.timestamp  # ts
        assert record[1] == sample_trade.symbol
        assert record[2] == sample_trade.exchange
        assert record[3] == sample_trade.price
        assert record[4] == sample_trade.size
        assert record[5] == sample_trade.side
        assert record[6] == sample_trade.trade_id

    @pytest.mark.asyncio
    async def test_start_and_stop_background_flush(self, writer):
        """Test starting and stopping background flush task.
        
        Validates: Requirements 2.3
        """
        await writer.start_background_flush()
        
        assert writer._running is True
        assert writer._flush_task is not None
        
        await writer.stop()
        
        assert writer._running is False
        assert writer._flush_task is None

    @pytest.mark.asyncio
    async def test_start_background_flush_idempotent(self, writer):
        """Test that calling start_background_flush multiple times is safe.
        
        Validates: Requirements 2.3
        """
        await writer.start_background_flush()
        first_task = writer._flush_task
        
        # Calling again should not create a new task
        await writer.start_background_flush()
        
        assert writer._flush_task is first_task
        assert writer._running is True
        
        await writer.stop()

    @pytest.mark.asyncio
    async def test_stop_flushes_remaining_buffer(self, writer, sample_trade):
        """Test that stop() flushes remaining buffer (graceful shutdown).
        
        Validates: Requirements 2.3
        """
        await writer.record(sample_trade)
        assert writer.get_buffer_size() == 1
        
        await writer.stop()
        
        # Buffer should be flushed on stop
        assert writer.get_buffer_size() == 0

    @pytest.mark.asyncio
    async def test_background_flush_periodic(self, mock_pool):
        """Test that background task flushes at configured interval.
        
        Validates: Requirements 2.3
        """
        config = TradeRecordWriterConfig(
            enabled=True,
            batch_size=1000,  # High batch size so it doesn't trigger
            flush_interval_sec=0.1,  # Short interval for testing
        )
        writer = TradeRecordWriter(mock_pool, config)
        
        # Add a trade
        trade = PersistenceTradeRecord(
            symbol="BTC/USDT",
            exchange="binance",
            timestamp=datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc),
            price=50000.0,
            size=1.0,
            side="buy",
            trade_id="trade_123",
        )
        await writer.record(trade)
        assert writer.get_buffer_size() == 1
        
        # Start background flush
        await writer.start_background_flush()
        
        # Wait for the flush interval to elapse
        await asyncio.sleep(0.2)
        
        # Buffer should be flushed by background task
        assert writer.get_buffer_size() == 0
        
        await writer.stop()

    @pytest.mark.asyncio
    async def test_stop_without_start(self, writer):
        """Test that stop() is safe to call without start().
        
        Validates: Requirements 2.3
        """
        # Should not raise any errors
        await writer.stop()
        
        assert writer._running is False
        assert writer._flush_task is None

    @pytest.mark.asyncio
    async def test_retry_on_failure(self, sample_trade):
        """Test exponential backoff retry on write failure."""
        config = TradeRecordWriterConfig(
            enabled=True,
            retry_max_attempts=3,
            retry_base_delay_sec=0.01,
        )
        
        # Create a shared connection mock that persists across acquire calls
        conn = AsyncMock()
        call_count = [0]
        
        async def executemany_side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] < 3:
                raise Exception("Connection error")
            return None
        
        conn.executemany = AsyncMock(side_effect=executemany_side_effect)
        
        # Create pool that returns the same connection each time
        pool = MagicMock()
        context_manager = AsyncMock()
        context_manager.__aenter__ = AsyncMock(return_value=conn)
        context_manager.__aexit__ = AsyncMock(return_value=None)
        pool.acquire = MagicMock(return_value=context_manager)
        
        writer = TradeRecordWriter(pool, config)
        
        await writer.record(sample_trade)
        count = await writer.flush()
        
        # Should succeed after retries
        assert count == 1
        assert call_count[0] == 3

    @pytest.mark.asyncio
    async def test_retry_exhausted_drops_batch(self, sample_trade):
        """Test that batch is dropped after max retries."""
        config = TradeRecordWriterConfig(
            enabled=True,
            retry_max_attempts=3,
            retry_base_delay_sec=0.01,
        )
        
        # Create a shared connection mock that always fails
        conn = AsyncMock()
        call_count = [0]
        
        async def executemany_side_effect(*args, **kwargs):
            call_count[0] += 1
            raise Exception("Connection error")
        
        conn.executemany = AsyncMock(side_effect=executemany_side_effect)
        
        # Create pool that returns the same connection each time
        pool = MagicMock()
        context_manager = AsyncMock()
        context_manager.__aenter__ = AsyncMock(return_value=conn)
        context_manager.__aexit__ = AsyncMock(return_value=None)
        pool.acquire = MagicMock(return_value=context_manager)
        
        writer = TradeRecordWriter(pool, config)
        
        await writer.record(sample_trade)
        count = await writer.flush()
        
        # Should return 0 after exhausting retries
        assert count == 0
        assert call_count[0] == 3

    @pytest.mark.asyncio
    async def test_preserves_all_trade_fields(self, mock_pool, config):
        """Test that all trade fields are preserved in batch insert."""
        writer = TradeRecordWriter(mock_pool, config)
        
        trade = PersistenceTradeRecord(
            symbol="ETH/USDT",
            exchange="coinbase",
            timestamp=datetime(2024, 6, 20, 15, 30, 45, 123456, tzinfo=timezone.utc),
            price=3500.50,
            size=2.75,
            side="sell",
            trade_id="unique_trade_id_456",
        )
        
        await writer.record(trade)
        await writer.flush()
        
        conn = mock_pool.acquire.return_value.__aenter__.return_value
        records = conn.executemany.call_args[0][1]
        record = records[0]
        
        # Verify all fields are preserved correctly
        assert record[0] == trade.timestamp  # Original timestamp preserved
        assert record[1] == "ETH/USDT"
        assert record[2] == "coinbase"
        assert record[3] == 3500.50
        assert record[4] == 2.75
        assert record[5] == "sell"
        assert record[6] == "unique_trade_id_456"
        assert record[7] == "default"  # tenant_id
        assert record[8] == "default"  # bot_id
