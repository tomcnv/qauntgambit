"""Storage module for persistence and data access.

This module provides components for persisting market data to TimescaleDB
and accessing stored data for analysis and backtesting.
"""

from quantgambit.storage.live_data_validator import LiveDataValidator
from quantgambit.storage.orderbook_snapshot_reader import (
    OrderbookSnapshotReader,
    OrderbookSnapshotReaderConfig,
)
from quantgambit.storage.orderbook_snapshot_writer import OrderbookSnapshotWriter
from quantgambit.storage.persistence import (
    LiveQualityMetrics,
    LiveValidationConfig,
    OrderbookSnapshot,
    OrderbookSnapshotWriterConfig,
    PersistenceTradeRecord,
    TradeRecordWriterConfig,
)
from quantgambit.storage.persistence_bootstrap import (
    PersistenceComponents,
    initialize_persistence,
    start_persistence_background_tasks,
    stop_persistence,
)
from quantgambit.storage.persistence_config import (
    get_persistence_bot_id,
    get_persistence_tenant_id,
    is_persistence_enabled,
    load_live_validation_config,
    load_orderbook_snapshot_config,
    load_trade_record_config,
)
from quantgambit.storage.trade_record_reader import (
    TradeRecordReader,
    TradeRecordReaderConfig,
)
from quantgambit.storage.trade_record_writer import TradeRecordWriter

__all__ = [
    # Validators
    "LiveDataValidator",
    "LiveQualityMetrics",
    "LiveValidationConfig",
    # Orderbook persistence
    "OrderbookSnapshot",
    "OrderbookSnapshotReader",
    "OrderbookSnapshotReaderConfig",
    "OrderbookSnapshotWriter",
    "OrderbookSnapshotWriterConfig",
    # Trade persistence
    "PersistenceTradeRecord",
    "TradeRecordReader",
    "TradeRecordReaderConfig",
    "TradeRecordWriter",
    "TradeRecordWriterConfig",
    # Bootstrap
    "PersistenceComponents",
    "initialize_persistence",
    "start_persistence_background_tasks",
    "stop_persistence",
    # Configuration helpers
    "get_persistence_bot_id",
    "get_persistence_tenant_id",
    "is_persistence_enabled",
    "load_live_validation_config",
    "load_orderbook_snapshot_config",
    "load_trade_record_config",
]
