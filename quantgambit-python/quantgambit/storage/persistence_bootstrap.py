"""Persistence layer bootstrap for application startup.

This module provides functions to initialize and wire up the persistence
components (OrderbookSnapshotWriter, TradeRecordWriter, LiveDataValidator)
during application startup.

Feature: live-orderbook-data-storage
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional, TYPE_CHECKING

from quantgambit.storage.live_data_validator import LiveDataValidator
from quantgambit.storage.orderbook_snapshot_writer import OrderbookSnapshotWriter
from quantgambit.storage.persistence_config import (
    is_persistence_enabled,
    load_live_validation_config,
    load_orderbook_snapshot_config,
    load_trade_record_config,
)
from quantgambit.storage.trade_record_writer import TradeRecordWriter

if TYPE_CHECKING:
    import asyncpg
    from quantgambit.market.quality import MarketDataQualityTracker
    from quantgambit.observability.telemetry import TelemetryContext, TelemetryPipeline
    from quantgambit.storage.redis_snapshots import RedisSnapshotWriter

logger = logging.getLogger(__name__)


@dataclass
class PersistenceComponents:
    """Container for initialized persistence components.
    
    This dataclass holds references to all persistence components that
    are initialized during application bootstrap. Components may be None
    if persistence is disabled or if initialization failed.
    
    Attributes:
        snapshot_writer: OrderbookSnapshotWriter for persisting orderbook snapshots.
            None if orderbook persistence is disabled.
        trade_writer: TradeRecordWriter for persisting trade records.
            None if trade persistence is disabled.
        live_validator: LiveDataValidator for real-time data quality monitoring.
            None if live validation is disabled.
        enabled: True if any persistence component is enabled.
    """
    
    snapshot_writer: Optional[OrderbookSnapshotWriter] = None
    trade_writer: Optional[TradeRecordWriter] = None
    live_validator: Optional[LiveDataValidator] = None
    enabled: bool = False


async def initialize_persistence(
    pool: "asyncpg.Pool",
    quality_tracker: Optional["MarketDataQualityTracker"] = None,
    snapshot_writer: Optional["RedisSnapshotWriter"] = None,
    telemetry: Optional["TelemetryPipeline"] = None,
    telemetry_context: Optional["TelemetryContext"] = None,
) -> PersistenceComponents:
    """Initialize persistence components from environment configuration.
    
    This function creates and configures all persistence components based
    on environment variables. It should be called during application
    bootstrap after the database pool is created.
    
    Args:
        pool: The asyncpg connection pool for database operations.
        quality_tracker: Optional MarketDataQualityTracker for quality updates.
        snapshot_writer: Optional RedisSnapshotWriter for dashboard metrics.
        telemetry: Optional TelemetryPipeline for telemetry events.
        telemetry_context: Optional TelemetryContext for telemetry events.
    
    Returns:
        PersistenceComponents containing all initialized components.
    
    Validates: Requirements 6.1, 6.2
    """
    if not is_persistence_enabled():
        logger.info("Persistence layer disabled - skipping initialization")
        return PersistenceComponents(enabled=False)
    
    logger.info("Initializing persistence layer components")
    
    # Initialize OrderbookSnapshotWriter
    orderbook_config = load_orderbook_snapshot_config()
    snapshot_writer_instance: Optional[OrderbookSnapshotWriter] = None
    if orderbook_config.enabled:
        snapshot_writer_instance = OrderbookSnapshotWriter(
            pool=pool,
            config=orderbook_config,
        )
        logger.info(
            "OrderbookSnapshotWriter initialized",
            extra={
                "interval_sec": orderbook_config.snapshot_interval_sec,
                "batch_size": orderbook_config.batch_size,
            },
        )
    
    # Initialize TradeRecordWriter
    trade_config = load_trade_record_config()
    trade_writer_instance: Optional[TradeRecordWriter] = None
    if trade_config.enabled:
        trade_writer_instance = TradeRecordWriter(
            pool=pool,
            config=trade_config,
        )
        logger.info(
            "TradeRecordWriter initialized",
            extra={
                "batch_size": trade_config.batch_size,
                "flush_interval_sec": trade_config.flush_interval_sec,
            },
        )
    
    # Initialize LiveDataValidator
    validation_config = load_live_validation_config()
    live_validator_instance: Optional[LiveDataValidator] = None
    if validation_config.enabled and quality_tracker is not None:
        live_validator_instance = LiveDataValidator(
            quality_tracker=quality_tracker,
            snapshot_writer=snapshot_writer,
            telemetry=telemetry,
            telemetry_context=telemetry_context,
            config=validation_config,
        )
        logger.info(
            "LiveDataValidator initialized",
            extra={
                "gap_threshold_sec": validation_config.gap_threshold_sec,
                "min_completeness_pct": validation_config.min_completeness_pct,
            },
        )
    
    return PersistenceComponents(
        snapshot_writer=snapshot_writer_instance,
        trade_writer=trade_writer_instance,
        live_validator=live_validator_instance,
        enabled=True,
    )


async def start_persistence_background_tasks(
    components: PersistenceComponents,
) -> None:
    """Start background flush tasks for persistence components.
    
    This function starts the background asyncio tasks that periodically
    flush buffered data to the database. It should be called after
    initialize_persistence() and before the main application loop starts.
    
    Args:
        components: The PersistenceComponents from initialize_persistence().
    
    Validates: Requirements 6.1, 6.2
    """
    if not components.enabled:
        return
    
    if components.snapshot_writer is not None:
        await components.snapshot_writer.start_background_flush()
        logger.info("OrderbookSnapshotWriter background flush started")
    
    if components.trade_writer is not None:
        await components.trade_writer.start_background_flush()
        logger.info("TradeRecordWriter background flush started")
    
    if components.live_validator is not None:
        await components.live_validator.start_background_emit()
        logger.info("LiveDataValidator background emit started")


async def stop_persistence(components: PersistenceComponents) -> None:
    """Stop persistence components and flush remaining buffers.
    
    This function stops all background tasks and performs a final flush
    to ensure all buffered data is persisted before shutdown. It should
    be called during graceful shutdown.
    
    Args:
        components: The PersistenceComponents to stop.
    
    Validates: Requirements 1.4, 2.3
    """
    if not components.enabled:
        return
    
    logger.info("Stopping persistence layer components")
    
    if components.snapshot_writer is not None:
        await components.snapshot_writer.stop()
        logger.info("OrderbookSnapshotWriter stopped and flushed")
    
    if components.trade_writer is not None:
        await components.trade_writer.stop()
        logger.info("TradeRecordWriter stopped and flushed")
    
    if components.live_validator is not None:
        await components.live_validator.stop()
        logger.info("LiveDataValidator stopped")
    
    logger.info("Persistence layer shutdown complete")
