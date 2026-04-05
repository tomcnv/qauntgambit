"""Unit tests for OrderbookSnapshotWriter.

Tests the snapshot capture with interval throttling functionality.

Feature: live-orderbook-data-storage
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from quantgambit.market.orderbooks import OrderbookState
from quantgambit.storage.orderbook_snapshot_writer import OrderbookSnapshotWriter
from quantgambit.storage.persistence import OrderbookSnapshotWriterConfig


class TestOrderbookSnapshotWriter:
    """Tests for OrderbookSnapshotWriter class."""

    @pytest.fixture
    def mock_pool(self):
        """Create a mock asyncpg pool."""
        pool = MagicMock()
        conn = AsyncMock()
        conn.executemany = AsyncMock()
        pool.acquire = MagicMock(return_value=AsyncMock(__aenter__=AsyncMock(return_value=conn), __aexit__=AsyncMock()))
        return pool

    @pytest.fixture
    def config(self):
        """Create a test configuration."""
        return OrderbookSnapshotWriterConfig(
            enabled=True,
            snapshot_interval_sec=1.0,
            batch_size=10,
            flush_interval_sec=5.0,
            max_buffer_size=100,
            retry_max_attempts=3,
            retry_base_delay_sec=0.01,
        )

    @pytest.fixture
    def writer(self, mock_pool, config):
        """Create a writer instance for testing."""
        return OrderbookSnapshotWriter(mock_pool, config)

    @pytest.fixture
    def valid_orderbook_state(self):
        """Create a valid orderbook state for testing."""
        state = OrderbookState(symbol="BTC/USDT")
        state.apply_snapshot(
            bids=[[50000.0, 1.0], [49999.0, 2.0], [49998.0, 3.0]],
            asks=[[50001.0, 1.0], [50002.0, 2.0], [50003.0, 3.0]],
            seq=100,
        )
        return state

    @pytest.mark.asyncio
    async def test_maybe_capture_first_capture(self, writer, valid_orderbook_state):
        """Test that first capture for a symbol is always captured."""
        timestamp = 1700000000.0
        
        await writer.maybe_capture(
            symbol="BTC/USDT",
            exchange="binance",
            state=valid_orderbook_state,
            timestamp=timestamp,
            seq=100,
        )
        
        # Should have captured (buffer size = 1)
        assert writer.get_buffer_size() == 1
        assert writer.get_last_capture_time("BTC/USDT", "binance") == timestamp

    @pytest.mark.asyncio
    async def test_maybe_capture_interval_throttling(self, writer, valid_orderbook_state):
        """Test that captures are throttled by interval."""
        base_timestamp = 1700000000.0
        
        # First capture
        await writer.maybe_capture(
            symbol="BTC/USDT",
            exchange="binance",
            state=valid_orderbook_state,
            timestamp=base_timestamp,
            seq=100,
        )
        assert writer.get_buffer_size() == 1
        
        # Second capture within interval (0.5 seconds later) - should be skipped
        await writer.maybe_capture(
            symbol="BTC/USDT",
            exchange="binance",
            state=valid_orderbook_state,
            timestamp=base_timestamp + 0.5,
            seq=101,
        )
        assert writer.get_buffer_size() == 1  # Still 1, not captured
        
        # Third capture after interval (1.5 seconds later) - should be captured
        await writer.maybe_capture(
            symbol="BTC/USDT",
            exchange="binance",
            state=valid_orderbook_state,
            timestamp=base_timestamp + 1.5,
            seq=102,
        )
        assert writer.get_buffer_size() == 2  # Now 2

    @pytest.mark.asyncio
    async def test_maybe_capture_different_symbols(self, writer, valid_orderbook_state):
        """Test that different symbols have independent throttling."""
        timestamp = 1700000000.0
        
        # Capture for BTC/USDT
        await writer.maybe_capture(
            symbol="BTC/USDT",
            exchange="binance",
            state=valid_orderbook_state,
            timestamp=timestamp,
            seq=100,
        )
        
        # Create state for ETH/USDT
        eth_state = OrderbookState(symbol="ETH/USDT")
        eth_state.apply_snapshot(
            bids=[[3000.0, 10.0], [2999.0, 20.0]],
            asks=[[3001.0, 10.0], [3002.0, 20.0]],
            seq=200,
        )
        
        # Capture for ETH/USDT at same timestamp - should be captured
        await writer.maybe_capture(
            symbol="ETH/USDT",
            exchange="binance",
            state=eth_state,
            timestamp=timestamp,
            seq=200,
        )
        
        # Both should be captured
        assert writer.get_buffer_size() == 2

    @pytest.mark.asyncio
    async def test_maybe_capture_disabled(self, mock_pool, valid_orderbook_state):
        """Test that capture is skipped when disabled."""
        config = OrderbookSnapshotWriterConfig(enabled=False)
        writer = OrderbookSnapshotWriter(mock_pool, config)
        
        await writer.maybe_capture(
            symbol="BTC/USDT",
            exchange="binance",
            state=valid_orderbook_state,
            timestamp=1700000000.0,
            seq=100,
        )
        
        # Should not capture when disabled
        assert writer.get_buffer_size() == 0

    @pytest.mark.asyncio
    async def test_maybe_capture_invalid_state(self, writer):
        """Test that capture is skipped for invalid orderbook state."""
        state = OrderbookState(symbol="BTC/USDT")
        # State is invalid by default (valid=False)
        
        await writer.maybe_capture(
            symbol="BTC/USDT",
            exchange="binance",
            state=state,
            timestamp=1700000000.0,
            seq=100,
        )
        
        # Should not capture invalid state
        assert writer.get_buffer_size() == 0

    @pytest.mark.asyncio
    async def test_maybe_capture_calculates_derived_metrics(self, writer, valid_orderbook_state):
        """Test that derived metrics are calculated correctly on capture."""
        await writer.maybe_capture(
            symbol="BTC/USDT",
            exchange="binance",
            state=valid_orderbook_state,
            timestamp=1700000000.0,
            seq=100,
        )
        
        # Get the captured snapshot from buffer
        assert writer.get_buffer_size() == 1
        snapshot = writer._buffer[0]
        
        # Verify derived metrics are calculated
        # spread_bps = ((50001 - 50000) / 50000.5) * 10000 ≈ 0.2
        assert snapshot.spread_bps > 0
        
        # bid_depth_usd = 50000*1 + 49999*2 + 49998*3 = 50000 + 99998 + 149994 = 299992
        assert snapshot.bid_depth_usd == pytest.approx(299992.0, rel=0.01)
        
        # ask_depth_usd = 50001*1 + 50002*2 + 50003*3 = 50001 + 100004 + 150009 = 300014
        assert snapshot.ask_depth_usd == pytest.approx(300014.0, rel=0.01)
        
        # orderbook_imbalance = (bid_depth - ask_depth) / (bid_depth + ask_depth)
        expected_imbalance = (299992.0 - 300014.0) / (299992.0 + 300014.0)
        assert snapshot.orderbook_imbalance == pytest.approx(expected_imbalance, rel=0.01)

    @pytest.mark.asyncio
    async def test_maybe_capture_preserves_orderbook_levels(self, writer, valid_orderbook_state):
        """Test that orderbook levels are preserved correctly."""
        await writer.maybe_capture(
            symbol="BTC/USDT",
            exchange="binance",
            state=valid_orderbook_state,
            timestamp=1700000000.0,
            seq=100,
        )
        
        snapshot = writer._buffer[0]
        
        # Verify bids are sorted by price descending
        assert len(snapshot.bids) == 3
        assert snapshot.bids[0][0] == 50000.0  # Best bid
        assert snapshot.bids[1][0] == 49999.0
        assert snapshot.bids[2][0] == 49998.0
        
        # Verify asks are sorted by price ascending
        assert len(snapshot.asks) == 3
        assert snapshot.asks[0][0] == 50001.0  # Best ask
        assert snapshot.asks[1][0] == 50002.0
        assert snapshot.asks[2][0] == 50003.0

    @pytest.mark.asyncio
    async def test_maybe_capture_timestamp_conversion(self, writer, valid_orderbook_state):
        """Test that timestamp is converted to datetime correctly."""
        timestamp = 1700000000.0
        
        await writer.maybe_capture(
            symbol="BTC/USDT",
            exchange="binance",
            state=valid_orderbook_state,
            timestamp=timestamp,
            seq=100,
        )
        
        snapshot = writer._buffer[0]
        
        # Verify timestamp is a datetime in UTC
        assert isinstance(snapshot.timestamp, datetime)
        assert snapshot.timestamp.tzinfo == timezone.utc
        assert snapshot.timestamp == datetime.fromtimestamp(timestamp, tz=timezone.utc)

    @pytest.mark.asyncio
    async def test_flush_empty_buffer(self, writer):
        """Test that flushing empty buffer returns 0."""
        count = await writer.flush()
        assert count == 0

    @pytest.mark.asyncio
    async def test_flush_clears_buffer(self, writer, valid_orderbook_state):
        """Test that flush clears the buffer."""
        await writer.maybe_capture(
            symbol="BTC/USDT",
            exchange="binance",
            state=valid_orderbook_state,
            timestamp=1700000000.0,
            seq=100,
        )
        
        assert writer.get_buffer_size() == 1
        
        count = await writer.flush()
        
        assert count == 1
        assert writer.get_buffer_size() == 0

    @pytest.mark.asyncio
    async def test_batch_size_triggers_flush(self, mock_pool, valid_orderbook_state):
        """Test that reaching batch_size triggers a flush."""
        config = OrderbookSnapshotWriterConfig(
            enabled=True,
            snapshot_interval_sec=0.0,  # No throttling for this test
            batch_size=3,
        )
        writer = OrderbookSnapshotWriter(mock_pool, config)
        
        # Capture 3 snapshots (batch_size)
        for i in range(3):
            await writer.maybe_capture(
                symbol="BTC/USDT",
                exchange="binance",
                state=valid_orderbook_state,
                timestamp=1700000000.0 + i,
                seq=100 + i,
            )
        
        # Give the async flush task time to run
        await asyncio.sleep(0.1)
        
        # Buffer should be cleared after batch flush
        assert writer.get_buffer_size() == 0
