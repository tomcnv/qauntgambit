"""Unit tests for persistence configuration dataclasses.

Feature: live-orderbook-data-storage
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from quantgambit.storage.persistence import (
    OrderbookSnapshot,
    OrderbookSnapshotWriterConfig,
    TradeRecordWriterConfig,
)


class TestOrderbookSnapshotWriterConfig:
    """Tests for OrderbookSnapshotWriterConfig dataclass."""

    def test_default_values(self) -> None:
        """Test that default values are set correctly."""
        config = OrderbookSnapshotWriterConfig()
        
        assert config.enabled is True
        assert config.snapshot_interval_sec == 1.0
        assert config.max_depth_levels == 20
        assert config.batch_size == 100
        assert config.flush_interval_sec == 5.0
        assert config.max_buffer_size == 1000
        assert config.retry_max_attempts == 3
        assert config.retry_base_delay_sec == 0.1

    def test_custom_values(self) -> None:
        """Test that custom values can be set."""
        config = OrderbookSnapshotWriterConfig(
            enabled=False,
            snapshot_interval_sec=2.5,
            batch_size=50,
            flush_interval_sec=10.0,
            max_buffer_size=500,
            retry_max_attempts=5,
            retry_base_delay_sec=0.2,
        )
        
        assert config.enabled is False
        assert config.snapshot_interval_sec == 2.5
        assert config.max_depth_levels == 20
        assert config.batch_size == 50
        assert config.flush_interval_sec == 10.0
        assert config.max_buffer_size == 500
        assert config.retry_max_attempts == 5
        assert config.retry_base_delay_sec == 0.2

    def test_partial_custom_values(self) -> None:
        """Test that partial custom values work with defaults."""
        config = OrderbookSnapshotWriterConfig(
            enabled=False,
            snapshot_interval_sec=5.0,
        )
        
        # Custom values
        assert config.enabled is False
        assert config.snapshot_interval_sec == 5.0
        
        # Default values
        assert config.max_depth_levels == 20
        assert config.batch_size == 100
        assert config.flush_interval_sec == 5.0
        assert config.max_buffer_size == 1000
        assert config.retry_max_attempts == 3
        assert config.retry_base_delay_sec == 0.1

    def test_disabled_config(self) -> None:
        """Test configuration with persistence disabled."""
        config = OrderbookSnapshotWriterConfig(enabled=False)
        
        assert config.enabled is False
        # Other values should still be accessible
        assert config.snapshot_interval_sec == 1.0

    def test_high_frequency_config(self) -> None:
        """Test configuration for high-frequency snapshot capture."""
        config = OrderbookSnapshotWriterConfig(
            snapshot_interval_sec=0.1,  # 100ms intervals
            batch_size=500,
            flush_interval_sec=1.0,
            max_buffer_size=5000,
        )
        
        assert config.snapshot_interval_sec == 0.1
        assert config.batch_size == 500
        assert config.flush_interval_sec == 1.0
        assert config.max_buffer_size == 5000

    def test_aggressive_retry_config(self) -> None:
        """Test configuration with aggressive retry settings."""
        config = OrderbookSnapshotWriterConfig(
            retry_max_attempts=10,
            retry_base_delay_sec=0.05,
        )
        
        assert config.retry_max_attempts == 10
        assert config.retry_base_delay_sec == 0.05


class TestTradeRecordWriterConfig:
    """Tests for TradeRecordWriterConfig dataclass.
    
    Validates: Requirements 2.5
    """

    def test_default_values(self) -> None:
        """Test that default values are set correctly."""
        config = TradeRecordWriterConfig()
        
        assert config.enabled is True
        assert config.batch_size == 500
        assert config.flush_interval_sec == 1.0
        assert config.max_buffer_size == 10000
        assert config.retry_max_attempts == 3
        assert config.retry_base_delay_sec == 0.1

    def test_custom_values(self) -> None:
        """Test that custom values can be set."""
        config = TradeRecordWriterConfig(
            enabled=False,
            batch_size=1000,
            flush_interval_sec=2.0,
            max_buffer_size=20000,
            retry_max_attempts=5,
            retry_base_delay_sec=0.2,
        )
        
        assert config.enabled is False
        assert config.batch_size == 1000
        assert config.flush_interval_sec == 2.0
        assert config.max_buffer_size == 20000
        assert config.retry_max_attempts == 5
        assert config.retry_base_delay_sec == 0.2

    def test_partial_custom_values(self) -> None:
        """Test that partial custom values work with defaults."""
        config = TradeRecordWriterConfig(
            enabled=False,
            batch_size=250,
        )
        
        # Custom values
        assert config.enabled is False
        assert config.batch_size == 250
        
        # Default values
        assert config.flush_interval_sec == 1.0
        assert config.max_buffer_size == 10000
        assert config.retry_max_attempts == 3
        assert config.retry_base_delay_sec == 0.1

    def test_disabled_config(self) -> None:
        """Test configuration with persistence disabled."""
        config = TradeRecordWriterConfig(enabled=False)
        
        assert config.enabled is False
        # Other values should still be accessible
        assert config.batch_size == 500

    def test_high_throughput_config(self) -> None:
        """Test configuration for high-throughput trade recording.
        
        This configuration is suitable for handling 100+ trades/second
        per symbol as specified in Requirements 2.5.
        """
        config = TradeRecordWriterConfig(
            batch_size=1000,
            flush_interval_sec=0.5,  # 500ms intervals
            max_buffer_size=50000,
        )
        
        assert config.batch_size == 1000
        assert config.flush_interval_sec == 0.5
        assert config.max_buffer_size == 50000

    def test_aggressive_retry_config(self) -> None:
        """Test configuration with aggressive retry settings."""
        config = TradeRecordWriterConfig(
            retry_max_attempts=10,
            retry_base_delay_sec=0.05,
        )
        
        assert config.retry_max_attempts == 10
        assert config.retry_base_delay_sec == 0.05

    def test_low_latency_config(self) -> None:
        """Test configuration optimized for low latency flushing."""
        config = TradeRecordWriterConfig(
            batch_size=100,
            flush_interval_sec=0.1,  # 100ms flush interval
            retry_base_delay_sec=0.05,
        )
        
        assert config.batch_size == 100
        assert config.flush_interval_sec == 0.1
        assert config.retry_base_delay_sec == 0.05


class TestOrderbookSnapshot:
    """Tests for OrderbookSnapshot dataclass.
    
    Validates: Requirements 1.2, 1.3
    """

    def test_create_snapshot_with_all_fields(self) -> None:
        """Test creating a snapshot with all required fields."""
        timestamp = datetime.now(timezone.utc)
        bids = [[50000.0, 1.5], [49999.0, 2.0], [49998.0, 0.5]]
        asks = [[50001.0, 1.0], [50002.0, 2.5], [50003.0, 1.2]]
        
        snapshot = OrderbookSnapshot(
            symbol="BTC/USDT",
            exchange="binance",
            timestamp=timestamp,
            seq=12345,
            bids=bids,
            asks=asks,
            spread_bps=2.0,
            bid_depth_usd=174996.5,
            ask_depth_usd=175009.9,
            orderbook_imbalance=0.4999,
        )
        
        assert snapshot.symbol == "BTC/USDT"
        assert snapshot.exchange == "binance"
        assert snapshot.timestamp == timestamp
        assert snapshot.seq == 12345
        assert snapshot.bids == bids
        assert snapshot.asks == asks
        assert snapshot.spread_bps == 2.0
        assert snapshot.bid_depth_usd == 174996.5
        assert snapshot.ask_depth_usd == 175009.9
        assert snapshot.orderbook_imbalance == 0.4999

    def test_snapshot_with_empty_orderbook(self) -> None:
        """Test creating a snapshot with empty bids and asks."""
        timestamp = datetime.now(timezone.utc)
        
        snapshot = OrderbookSnapshot(
            symbol="ETH/USDT",
            exchange="coinbase",
            timestamp=timestamp,
            seq=1,
            bids=[],
            asks=[],
            spread_bps=0.0,
            bid_depth_usd=0.0,
            ask_depth_usd=0.0,
            orderbook_imbalance=0.0,  # Default when both depths are zero
        )
        
        assert snapshot.bids == []
        assert snapshot.asks == []
        assert snapshot.spread_bps == 0.0
        assert snapshot.bid_depth_usd == 0.0
        assert snapshot.ask_depth_usd == 0.0
        assert snapshot.orderbook_imbalance == 0.0

    def test_snapshot_with_full_20_levels(self) -> None:
        """Test creating a snapshot with full 20 levels of depth."""
        timestamp = datetime.now(timezone.utc)
        
        # Generate 20 bid levels (descending prices)
        bids = [[50000.0 - i, 1.0] for i in range(20)]
        # Generate 20 ask levels (ascending prices)
        asks = [[50001.0 + i, 1.0] for i in range(20)]
        
        snapshot = OrderbookSnapshot(
            symbol="BTC/USDT",
            exchange="kraken",
            timestamp=timestamp,
            seq=999999,
            bids=bids,
            asks=asks,
            spread_bps=2.0,
            bid_depth_usd=999810.0,
            ask_depth_usd=1000210.0,
            orderbook_imbalance=0.4999,
        )
        
        assert len(snapshot.bids) == 20
        assert len(snapshot.asks) == 20
        assert snapshot.bids[0][0] == 50000.0  # Best bid
        assert snapshot.asks[0][0] == 50001.0  # Best ask

    def test_snapshot_with_single_level(self) -> None:
        """Test creating a snapshot with single level orderbook."""
        timestamp = datetime.now(timezone.utc)
        
        snapshot = OrderbookSnapshot(
            symbol="SOL/USDT",
            exchange="binance",
            timestamp=timestamp,
            seq=100,
            bids=[[150.0, 10.0]],
            asks=[[150.5, 10.0]],
            spread_bps=33.33,
            bid_depth_usd=1500.0,
            ask_depth_usd=1505.0,
            orderbook_imbalance=0.4992,
        )
        
        assert len(snapshot.bids) == 1
        assert len(snapshot.asks) == 1
        assert snapshot.bids[0] == [150.0, 10.0]
        assert snapshot.asks[0] == [150.5, 10.0]

    def test_snapshot_with_high_imbalance(self) -> None:
        """Test snapshot with high buying pressure (imbalance > 0.0)."""
        timestamp = datetime.now(timezone.utc)
        
        # More bid depth than ask depth
        snapshot = OrderbookSnapshot(
            symbol="BTC/USDT",
            exchange="binance",
            timestamp=timestamp,
            seq=500,
            bids=[[50000.0, 10.0]],  # 500,000 USD
            asks=[[50001.0, 1.0]],   # 50,001 USD
            spread_bps=2.0,
            bid_depth_usd=500000.0,
            ask_depth_usd=50001.0,
            orderbook_imbalance=0.818,  # High buying pressure
        )
        
        assert snapshot.orderbook_imbalance > 0.0

    def test_snapshot_with_low_imbalance(self) -> None:
        """Test snapshot with high selling pressure (imbalance < 0.0)."""
        timestamp = datetime.now(timezone.utc)
        
        # More ask depth than bid depth
        snapshot = OrderbookSnapshot(
            symbol="BTC/USDT",
            exchange="binance",
            timestamp=timestamp,
            seq=600,
            bids=[[50000.0, 1.0]],   # 50,000 USD
            asks=[[50001.0, 10.0]],  # 500,010 USD
            spread_bps=2.0,
            bid_depth_usd=50000.0,
            ask_depth_usd=500010.0,
            orderbook_imbalance=-0.818,  # High selling pressure
        )
        
        assert snapshot.orderbook_imbalance < 0.0

    def test_snapshot_equality(self) -> None:
        """Test that two snapshots with same values are equal."""
        timestamp = datetime.now(timezone.utc)
        bids = [[50000.0, 1.0]]
        asks = [[50001.0, 1.0]]
        
        snapshot1 = OrderbookSnapshot(
            symbol="BTC/USDT",
            exchange="binance",
            timestamp=timestamp,
            seq=100,
            bids=bids,
            asks=asks,
            spread_bps=2.0,
            bid_depth_usd=50000.0,
            ask_depth_usd=50001.0,
            orderbook_imbalance=0.5,
        )
        
        snapshot2 = OrderbookSnapshot(
            symbol="BTC/USDT",
            exchange="binance",
            timestamp=timestamp,
            seq=100,
            bids=bids,
            asks=asks,
            spread_bps=2.0,
            bid_depth_usd=50000.0,
            ask_depth_usd=50001.0,
            orderbook_imbalance=0.5,
        )
        
        assert snapshot1 == snapshot2

    def test_snapshot_different_exchanges(self) -> None:
        """Test snapshots from different exchanges."""
        timestamp = datetime.now(timezone.utc)
        
        binance_snapshot = OrderbookSnapshot(
            symbol="BTC/USDT",
            exchange="binance",
            timestamp=timestamp,
            seq=100,
            bids=[[50000.0, 1.0]],
            asks=[[50001.0, 1.0]],
            spread_bps=2.0,
            bid_depth_usd=50000.0,
            ask_depth_usd=50001.0,
            orderbook_imbalance=0.5,
        )
        
        coinbase_snapshot = OrderbookSnapshot(
            symbol="BTC/USDT",
            exchange="coinbase",
            timestamp=timestamp,
            seq=200,
            bids=[[50000.0, 1.0]],
            asks=[[50001.0, 1.0]],
            spread_bps=2.0,
            bid_depth_usd=50000.0,
            ask_depth_usd=50001.0,
            orderbook_imbalance=0.5,
        )
        
        assert binance_snapshot.exchange == "binance"
        assert coinbase_snapshot.exchange == "coinbase"
        assert binance_snapshot != coinbase_snapshot
