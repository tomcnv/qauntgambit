"""Property tests for config-based invocation of persistence layer.

Feature: live-orderbook-data-storage
Property 13: Config-Based Invocation

For any worker processing an update, if the writer's config.enabled is False,
the writer SHALL NOT be invoked. If config.enabled is True, the writer SHALL
be invoked.

Validates: Requirements 6.1, 6.2
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest
from hypothesis import given, settings, strategies as st

from quantgambit.storage.persistence import (
    OrderbookSnapshotWriterConfig,
    TradeRecordWriterConfig,
    LiveValidationConfig,
    PersistenceTradeRecord,
)


# Test configuration
PROPERTY_TEST_EXAMPLES = 100


# Strategies for generating test data
symbol_strategy = st.text(
    alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd"), whitelist_characters="/"),
    min_size=3,
    max_size=15,
).filter(lambda s: "/" in s or len(s) >= 3)

exchange_strategy = st.sampled_from(["binance", "coinbase", "kraken", "okx"])


@dataclass
class MockOrderbookState:
    """Mock OrderbookState for testing."""
    symbol: str
    seq: int = 0
    valid: bool = True
    _bids: List[List[float]] = None
    _asks: List[List[float]] = None
    
    def __post_init__(self):
        if self._bids is None:
            self._bids = [[100.0, 1.0], [99.0, 2.0]]
        if self._asks is None:
            self._asks = [[101.0, 1.0], [102.0, 2.0]]
    
    def as_levels(self, depth: int = 20):
        return self._bids[:depth], self._asks[:depth]
    
    def apply_snapshot(self, bids, asks, seq):
        self._bids = bids
        self._asks = asks
        self.seq = seq
        self.valid = True
    
    def apply_delta(self, bids, asks, seq):
        self.seq = seq


class TestConfigBasedInvocation:
    """Property tests for config-based invocation.
    
    Property 13: Config-Based Invocation
    
    For any worker processing an update, if the writer's config.enabled is False,
    the writer SHALL NOT be invoked. If config.enabled is True, the writer SHALL
    be invoked.
    
    Validates: Requirements 6.1, 6.2
    """
    
    @settings(max_examples=PROPERTY_TEST_EXAMPLES)
    @given(
        symbol=symbol_strategy,
        exchange=exchange_strategy,
        enabled=st.booleans(),
    )
    def test_snapshot_writer_respects_enabled_config(
        self,
        symbol: str,
        exchange: str,
        enabled: bool,
    ) -> None:
        """Property: Snapshot writer SHALL only be invoked when enabled.
        
        **Validates: Requirements 6.1**
        
        When config.enabled is False, the snapshot writer should not capture
        any snapshots. When enabled is True, it should capture snapshots
        according to the interval.
        """
        from quantgambit.storage.orderbook_snapshot_writer import OrderbookSnapshotWriter
        
        config = OrderbookSnapshotWriterConfig(
            enabled=enabled,
            snapshot_interval_sec=0.0,  # Always capture when enabled
        )
        
        # Create a mock pool
        mock_pool = MagicMock()
        
        writer = OrderbookSnapshotWriter(pool=mock_pool, config=config)
        
        # Create mock state
        state = MockOrderbookState(symbol=symbol)
        
        # Capture a snapshot
        import asyncio
        asyncio.run(
            writer.maybe_capture(
                symbol=symbol,
                exchange=exchange,
                state=state,
                timestamp=1700000000.0,
                seq=100,
            )
        )
        
        # Check buffer state
        if enabled:
            # When enabled, snapshot should be captured
            assert len(writer._buffer) > 0, (
                f"Snapshot should be captured when enabled=True"
            )
        else:
            # When disabled, no snapshot should be captured
            assert len(writer._buffer) == 0, (
                f"No snapshot should be captured when enabled=False"
            )
    
    @settings(max_examples=PROPERTY_TEST_EXAMPLES)
    @given(
        symbol=symbol_strategy,
        exchange=exchange_strategy,
        enabled=st.booleans(),
    )
    def test_trade_writer_respects_enabled_config(
        self,
        symbol: str,
        exchange: str,
        enabled: bool,
    ) -> None:
        """Property: Trade writer SHALL only be invoked when enabled.
        
        **Validates: Requirements 6.2**
        
        When config.enabled is False, the trade writer should not record
        any trades. When enabled is True, it should record trades.
        """
        from quantgambit.storage.trade_record_writer import TradeRecordWriter
        
        config = TradeRecordWriterConfig(enabled=enabled)
        
        # Create a mock pool
        mock_pool = MagicMock()
        
        writer = TradeRecordWriter(pool=mock_pool, config=config)
        
        # Create a trade record
        record = PersistenceTradeRecord(
            symbol=symbol,
            exchange=exchange,
            timestamp=datetime.fromtimestamp(1700000000.0, tz=timezone.utc),
            price=100.0,
            size=1.0,
            side="buy",
            trade_id="test-123",
        )
        
        # Record the trade
        import asyncio
        asyncio.run(writer.record(record))
        
        # Check buffer state
        if enabled:
            # When enabled, trade should be recorded
            assert len(writer._buffer) > 0, (
                f"Trade should be recorded when enabled=True"
            )
        else:
            # When disabled, no trade should be recorded
            assert len(writer._buffer) == 0, (
                f"No trade should be recorded when enabled=False"
            )
    
    @settings(max_examples=PROPERTY_TEST_EXAMPLES)
    @given(
        symbol=symbol_strategy,
        exchange=exchange_strategy,
        enabled=st.booleans(),
    )
    def test_live_validator_respects_enabled_config(
        self,
        symbol: str,
        exchange: str,
        enabled: bool,
    ) -> None:
        """Property: Live validator SHALL only track when enabled.
        
        **Validates: Requirements 6.1, 6.2**
        
        When config.enabled is False, the validator should not track
        any updates. When enabled is True, it should track updates.
        """
        from quantgambit.storage.live_data_validator import LiveDataValidator
        
        config = LiveValidationConfig(enabled=enabled)
        
        validator = LiveDataValidator(config=config)
        
        # Record an orderbook update
        validator.record_orderbook_update(
            symbol=symbol,
            exchange=exchange,
            timestamp=1700000000.0,
            seq=100,
        )
        
        # Record a trade
        validator.record_trade(
            symbol=symbol,
            exchange=exchange,
            timestamp=1700000000.0,
        )
        
        # Check tracking state
        if enabled:
            # When enabled, updates should be tracked
            assert validator.get_expected_seq(symbol, exchange) == 100, (
                f"Orderbook update should be tracked when enabled=True"
            )
            assert validator.get_last_trade_ts(symbol, exchange) == 1700000000.0, (
                f"Trade should be tracked when enabled=True"
            )
        else:
            # When disabled, no updates should be tracked
            assert validator.get_expected_seq(symbol, exchange) is None, (
                f"Orderbook update should not be tracked when enabled=False"
            )
            assert validator.get_last_trade_ts(symbol, exchange) is None, (
                f"Trade should not be tracked when enabled=False"
            )
    
    @settings(max_examples=PROPERTY_TEST_EXAMPLES)
    @given(
        symbol=symbol_strategy,
        exchange=exchange_strategy,
    )
    def test_disabled_writer_has_zero_overhead(
        self,
        symbol: str,
        exchange: str,
    ) -> None:
        """Property: Disabled writer SHALL have zero overhead.
        
        **Validates: Requirements 6.4**
        
        When persistence is disabled, there should be no buffer allocations
        or processing overhead.
        """
        from quantgambit.storage.orderbook_snapshot_writer import OrderbookSnapshotWriter
        from quantgambit.storage.trade_record_writer import TradeRecordWriter
        
        # Create disabled writers
        snapshot_config = OrderbookSnapshotWriterConfig(enabled=False)
        trade_config = TradeRecordWriterConfig(enabled=False)
        
        mock_pool = MagicMock()
        
        snapshot_writer = OrderbookSnapshotWriter(pool=mock_pool, config=snapshot_config)
        trade_writer = TradeRecordWriter(pool=mock_pool, config=trade_config)
        
        # Process many updates
        import asyncio
        state = MockOrderbookState(symbol=symbol)
        
        for i in range(100):
            asyncio.run(
                snapshot_writer.maybe_capture(
                    symbol=symbol,
                    exchange=exchange,
                    state=state,
                    timestamp=1700000000.0 + i,
                    seq=100 + i,
                )
            )
            
            record = PersistenceTradeRecord(
                symbol=symbol,
                exchange=exchange,
                timestamp=datetime.fromtimestamp(1700000000.0 + i, tz=timezone.utc),
                price=100.0 + i,
                size=1.0,
                side="buy",
                trade_id=f"test-{i}",
            )
            asyncio.run(trade_writer.record(record))
        
        # Verify no data was buffered
        assert len(snapshot_writer._buffer) == 0, (
            "Disabled snapshot writer should have empty buffer"
        )
        assert len(trade_writer._buffer) == 0, (
            "Disabled trade writer should have empty buffer"
        )
    
    @settings(max_examples=PROPERTY_TEST_EXAMPLES)
    @given(
        symbol=symbol_strategy,
        exchange=exchange_strategy,
        num_updates=st.integers(min_value=1, max_value=10),
    )
    def test_enabled_writer_captures_all_updates(
        self,
        symbol: str,
        exchange: str,
        num_updates: int,
    ) -> None:
        """Property: Enabled writer SHALL capture all updates.
        
        **Validates: Requirements 6.1, 6.2**
        
        When persistence is enabled, all updates should be captured
        (subject to interval throttling for snapshots).
        """
        from quantgambit.storage.trade_record_writer import TradeRecordWriter
        
        config = TradeRecordWriterConfig(enabled=True)
        mock_pool = MagicMock()
        
        writer = TradeRecordWriter(pool=mock_pool, config=config)
        
        # Record multiple trades
        import asyncio
        for i in range(num_updates):
            record = PersistenceTradeRecord(
                symbol=symbol,
                exchange=exchange,
                timestamp=datetime.fromtimestamp(1700000000.0 + i, tz=timezone.utc),
                price=100.0 + i,
                size=1.0,
                side="buy",
                trade_id=f"test-{i}",
            )
            asyncio.run(writer.record(record))
        
        # Verify all trades were captured
        assert len(writer._buffer) == num_updates, (
            f"Expected {num_updates} trades in buffer, got {len(writer._buffer)}"
        )
