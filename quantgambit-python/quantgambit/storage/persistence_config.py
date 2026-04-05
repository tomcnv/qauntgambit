"""Persistence layer configuration from environment variables.

This module provides functions to load persistence configuration from
environment variables for the live orderbook data storage feature.

Feature: live-orderbook-data-storage
"""

from __future__ import annotations

import os
from typing import Optional

from quantgambit.storage.persistence import (
    OrderbookSnapshotWriterConfig,
    TradeRecordWriterConfig,
    LiveValidationConfig,
)


def load_orderbook_snapshot_config() -> OrderbookSnapshotWriterConfig:
    """Load OrderbookSnapshotWriterConfig from environment variables.
    
    Environment Variables:
        PERSISTENCE_ORDERBOOK_ENABLED: Enable/disable orderbook persistence (default: false)
        PERSISTENCE_ORDERBOOK_INTERVAL_SEC: Snapshot interval in seconds (default: 1.0)
        PERSISTENCE_ORDERBOOK_MAX_LEVELS: Max levels per side to persist (default: 20)
        PERSISTENCE_ORDERBOOK_BATCH_SIZE: Max snapshots per batch write (default: 100)
        PERSISTENCE_ORDERBOOK_FLUSH_SEC: Max time before forced flush (default: 5.0)
        PERSISTENCE_ORDERBOOK_MAX_BUFFER: Max buffered snapshots (default: 1000)
        PERSISTENCE_RETRY_MAX_ATTEMPTS: Max retry attempts (default: 3)
        PERSISTENCE_RETRY_BASE_DELAY_SEC: Base delay for exponential backoff (default: 0.1)
    
    Returns:
        OrderbookSnapshotWriterConfig with values from environment.
    
    Validates: Requirements 5.1, 6.1
    """
    return OrderbookSnapshotWriterConfig(
        enabled=os.getenv("PERSISTENCE_ORDERBOOK_ENABLED", "false").lower() in {"1", "true", "yes"},
        snapshot_interval_sec=float(os.getenv("PERSISTENCE_ORDERBOOK_INTERVAL_SEC", "1.0")),
        max_depth_levels=int(os.getenv("PERSISTENCE_ORDERBOOK_MAX_LEVELS", "20")),
        batch_size=int(os.getenv("PERSISTENCE_ORDERBOOK_BATCH_SIZE", "100")),
        flush_interval_sec=float(os.getenv("PERSISTENCE_ORDERBOOK_FLUSH_SEC", "5.0")),
        max_buffer_size=int(os.getenv("PERSISTENCE_ORDERBOOK_MAX_BUFFER", "1000")),
        retry_max_attempts=int(os.getenv("PERSISTENCE_RETRY_MAX_ATTEMPTS", "3")),
        retry_base_delay_sec=float(os.getenv("PERSISTENCE_RETRY_BASE_DELAY_SEC", "0.1")),
    )


def load_trade_record_config() -> TradeRecordWriterConfig:
    """Load TradeRecordWriterConfig from environment variables.
    
    Environment Variables:
        PERSISTENCE_TRADES_ENABLED: Enable/disable trade persistence (default: false)
        PERSISTENCE_TRADES_BATCH_SIZE: Max trades per batch write (default: 500)
        PERSISTENCE_TRADES_FLUSH_SEC: Max time before forced flush (default: 1.0)
        PERSISTENCE_TRADES_MAX_BUFFER: Max buffered trades (default: 10000)
        PERSISTENCE_RETRY_MAX_ATTEMPTS: Max retry attempts (default: 3)
        PERSISTENCE_RETRY_BASE_DELAY_SEC: Base delay for exponential backoff (default: 0.1)
    
    Returns:
        TradeRecordWriterConfig with values from environment.
    
    Validates: Requirements 5.1, 6.2
    """
    return TradeRecordWriterConfig(
        enabled=os.getenv("PERSISTENCE_TRADES_ENABLED", "false").lower() in {"1", "true", "yes"},
        batch_size=int(os.getenv("PERSISTENCE_TRADES_BATCH_SIZE", "500")),
        flush_interval_sec=float(os.getenv("PERSISTENCE_TRADES_FLUSH_SEC", "1.0")),
        max_buffer_size=int(os.getenv("PERSISTENCE_TRADES_MAX_BUFFER", "10000")),
        retry_max_attempts=int(os.getenv("PERSISTENCE_RETRY_MAX_ATTEMPTS", "3")),
        retry_base_delay_sec=float(os.getenv("PERSISTENCE_RETRY_BASE_DELAY_SEC", "0.1")),
    )


def load_live_validation_config() -> LiveValidationConfig:
    """Load LiveValidationConfig from environment variables.
    
    Environment Variables:
        PERSISTENCE_VALIDATION_ENABLED: Enable/disable live validation (default: false)
        PERSISTENCE_GAP_THRESHOLD_SEC: Seconds without data to count as gap (default: 5.0)
        PERSISTENCE_CRITICAL_GAP_SEC: Seconds to classify as critical gap (default: 30.0)
        PERSISTENCE_COMPLETENESS_WINDOW_SEC: Rolling window for completeness (default: 60.0)
        PERSISTENCE_MIN_COMPLETENESS_PCT: Min completeness before warning (default: 80.0)
        PERSISTENCE_EMIT_INTERVAL_SEC: Interval for emitting metrics (default: 10.0)
        PERSISTENCE_EXPECTED_OB_UPDATES_SEC: Expected orderbook updates/sec (default: 1.0)
        PERSISTENCE_EXPECTED_TRADES_SEC: Expected trades/sec (default: 1.0)
    
    Returns:
        LiveValidationConfig with values from environment.
    
    Validates: Requirements 5.1
    """
    return LiveValidationConfig(
        enabled=os.getenv("PERSISTENCE_VALIDATION_ENABLED", "false").lower() in {"1", "true", "yes"},
        gap_threshold_sec=float(os.getenv("PERSISTENCE_GAP_THRESHOLD_SEC", "5.0")),
        critical_gap_sec=float(os.getenv("PERSISTENCE_CRITICAL_GAP_SEC", "30.0")),
        completeness_window_sec=float(os.getenv("PERSISTENCE_COMPLETENESS_WINDOW_SEC", "60.0")),
        min_completeness_pct=float(os.getenv("PERSISTENCE_MIN_COMPLETENESS_PCT", "80.0")),
        emit_interval_sec=float(os.getenv("PERSISTENCE_EMIT_INTERVAL_SEC", "10.0")),
        expected_orderbook_updates_per_sec=float(os.getenv("PERSISTENCE_EXPECTED_OB_UPDATES_SEC", "1.0")),
        expected_trades_per_sec=float(os.getenv("PERSISTENCE_EXPECTED_TRADES_SEC", "1.0")),
    )


def is_persistence_enabled() -> bool:
    """Check if any persistence feature is enabled.
    
    Returns:
        True if orderbook or trade persistence is enabled.
    """
    orderbook_enabled = os.getenv("PERSISTENCE_ORDERBOOK_ENABLED", "false").lower() in {"1", "true", "yes"}
    trades_enabled = os.getenv("PERSISTENCE_TRADES_ENABLED", "false").lower() in {"1", "true", "yes"}
    return orderbook_enabled or trades_enabled


def get_persistence_tenant_id() -> str:
    """Get the tenant ID for persistence operations.
    
    Returns:
        Tenant ID from environment or "default".
    """
    return os.getenv("TENANT_ID", "default")


def get_persistence_bot_id() -> str:
    """Get the bot ID for persistence operations.
    
    Returns:
        Bot ID from environment or "default".
    """
    return os.getenv("BOT_ID", "default")
