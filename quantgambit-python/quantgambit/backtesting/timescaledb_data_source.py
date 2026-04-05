"""TimescaleDB data source for backtesting.

This module provides the TimescaleDBDataSource class that reads orderbook
snapshots and trade records from TimescaleDB, transforms them into the
feature snapshot format expected by ReplayWorker, and exports them to JSONL.

Feature: backtest-timescaledb-replay
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncIterator, List, Optional, TYPE_CHECKING

from quantgambit.backtesting.chronological_merger import ChronologicalMerger
from quantgambit.backtesting.data_source import DataValidationResult
from quantgambit.backtesting.snapshot_transformer import SnapshotTransformer, TradeContext
from quantgambit.storage.orderbook_snapshot_reader import (
    OrderbookSnapshotReader,
    OrderbookSnapshotReaderConfig,
)
from quantgambit.storage.trade_record_reader import (
    TradeRecordReader,
    TradeRecordReaderConfig,
)

if TYPE_CHECKING:
    import asyncpg

logger = logging.getLogger(__name__)


def _normalize_datetime_pair(
    left: Optional[datetime],
    right: Optional[datetime],
) -> tuple[Optional[datetime], Optional[datetime]]:
    """Normalize tz-awareness so datetime comparisons don't fail."""
    if left is None or right is None:
        return left, right
    left_has_tz = left.tzinfo is not None and left.tzinfo.utcoffset(left) is not None
    right_has_tz = right.tzinfo is not None and right.tzinfo.utcoffset(right) is not None
    if left_has_tz == right_has_tz:
        return left, right
    if left_has_tz and not right_has_tz:
        return left, right.replace(tzinfo=timezone.utc)
    if right_has_tz and not left_has_tz:
        return left.replace(tzinfo=timezone.utc), right
    return left, right


@dataclass
class TimescaleDBDataSourceConfig:
    """Configuration for TimescaleDB data source.
    
    This configuration specifies the parameters for reading orderbook
    snapshots and trade records from TimescaleDB for backtest replay.
    
    Attributes:
        symbol: The trading pair symbol (e.g., "BTC/USDT").
        exchange: The exchange identifier (e.g., "binance", "okx").
        start_time: Start of the time range (inclusive).
        end_time: End of the time range (inclusive).
        tenant_id: Tenant ID filter for multi-tenant deployments.
            Default is "default".
        bot_id: Bot ID filter for multi-bot deployments.
            Default is "default".
        batch_size: Number of orderbook snapshots to fetch per query batch.
            Larger batches are more efficient but use more memory.
            Default is 1000 snapshots.
        include_trades: Whether to include trade records in the export.
            When True, trade-derived features are included in snapshots.
            Default is True.
    
    Validates: Requirements 4.2, 4.3, 6.1
    """
    
    symbol: str
    exchange: str
    start_time: datetime
    end_time: datetime
    tenant_id: str = "default"
    bot_id: str = "default"
    batch_size: int = 1000
    include_trades: bool = True


class TimescaleDBDataSource:
    """Data source that reads from TimescaleDB orderbook_snapshots and trade_records.
    
    This class orchestrates reading orderbook snapshots and trade records from
    TimescaleDB, merging them chronologically, and transforming them into the
    feature snapshot format expected by ReplayWorker.
    
    The data source implements the DataSource protocol and can be used
    interchangeably with the Redis-based SnapshotExporter.
    
    Key features:
    - Validates data availability before export (Requirements 5.1-5.5)
    - Uses batch queries for efficient database access (Requirement 6.1)
    - Uses async iteration to avoid blocking (Requirement 6.2)
    - Releases connections promptly when cancelled (Requirement 6.3)
    - Reuses existing database connection pool (Requirement 6.4)
    
    Example:
        >>> config = TimescaleDBDataSourceConfig(
        ...     symbol="BTC/USDT",
        ...     exchange="binance",
        ...     start_time=datetime(2024, 1, 1),
        ...     end_time=datetime(2024, 1, 31),
        ... )
        >>> source = TimescaleDBDataSource(pool, config)
        >>> validation = await source.validate()
        >>> if validation.is_valid:
        ...     count = await source.export(Path("/tmp/snapshots.jsonl"))
    
    Validates: Requirements 1.1, 1.2, 1.4, 1.5, 5.1-5.5, 6.1-6.4
    """
    
    def __init__(
        self,
        pool: "asyncpg.Pool",
        config: TimescaleDBDataSourceConfig,
    ) -> None:
        """Initialize the data source.
        
        Args:
            pool: Database connection pool (reused, not owned).
            config: Data source configuration.
        
        Validates: Requirements 6.4
        """
        self.pool = pool
        self.config = config
        
        # Create readers with appropriate batch sizes
        # Requirement 6.1: Use batch queries with configurable batch size
        self._orderbook_reader = OrderbookSnapshotReader(
            pool,
            OrderbookSnapshotReaderConfig(
                batch_size=config.batch_size,
                tenant_id=config.tenant_id,
                bot_id=config.bot_id,
            ),
        )
        
        # Trades are typically more frequent, so use larger batch size
        self._trade_reader = TradeRecordReader(
            pool,
            TradeRecordReaderConfig(
                batch_size=config.batch_size * 5,
                tenant_id=config.tenant_id,
                bot_id=config.bot_id,
            ),
        )
        
        self._transformer = SnapshotTransformer()
        self._merger = ChronologicalMerger()
        self._closed = False
    
    async def validate(self) -> DataValidationResult:
        """Validate data availability before export.
        
        Checks that orderbook snapshots exist for the specified time range
        and reports coverage statistics. This method should be called before
        export() to ensure data is available.
        
        Returns:
            DataValidationResult with availability information including:
            - is_valid: True if data exists and can be exported
            - snapshot_count: Number of orderbook snapshots in range
            - trade_count: Number of trade records in range
            - first_timestamp: Timestamp of first snapshot
            - last_timestamp: Timestamp of last snapshot
            - coverage_pct: Percentage of requested range covered
            - warnings: List of warning messages
            - error_message: Error message if validation failed
        
        Validates: Requirements 1.5, 5.1, 5.2, 5.3, 5.4, 5.5
        """
        warnings: List[str] = []
        
        # Get snapshot count (Requirement 5.5)
        snapshot_count = await self._orderbook_reader.get_snapshot_count(
            symbol=self.config.symbol,
            exchange=self.config.exchange,
            start_time=self.config.start_time,
            end_time=self.config.end_time,
        )
        
        # Requirement 1.5, 5.1, 5.4: Validate orderbook snapshots exist
        if snapshot_count == 0:
            error_msg = (
                f"No orderbook snapshots found for {self.config.symbol} on "
                f"{self.config.exchange} between {self.config.start_time} and "
                f"{self.config.end_time} (tenant_id={self.config.tenant_id}, "
                f"bot_id={self.config.bot_id})"
            )
            logger.error(error_msg)
            return DataValidationResult(
                is_valid=False,
                snapshot_count=0,
                trade_count=0,
                first_timestamp=None,
                last_timestamp=None,
                coverage_pct=0.0,
                warnings=[],
                error_message=error_msg,
            )
        
        # Get trade count (Requirement 5.5)
        trade_count = 0
        if self.config.include_trades:
            trade_count = await self._trade_reader.get_trade_count(
                symbol=self.config.symbol,
                exchange=self.config.exchange,
                start_time=self.config.start_time,
                end_time=self.config.end_time,
            )
        
        # Get actual data range (Requirement 5.2)
        # Get first and last snapshots to determine actual range
        first_snapshots = await self._orderbook_reader.get_snapshots(
            symbol=self.config.symbol,
            exchange=self.config.exchange,
            start_time=self.config.start_time,
            end_time=self.config.end_time,
            limit=1,
        )
        first_timestamp = first_snapshots[0].timestamp if first_snapshots else None
        
        # Get last snapshot by querying with reverse order
        last_snapshot = await self._orderbook_reader.get_latest_snapshot(
            symbol=self.config.symbol,
            exchange=self.config.exchange,
            before_time=self.config.end_time,
        )
        last_timestamp = last_snapshot.timestamp if last_snapshot else None
        
        # Calculate coverage percentage (Requirement 5.2, 5.3)
        requested_range = (self.config.end_time - self.config.start_time).total_seconds()
        if requested_range > 0 and first_timestamp and last_timestamp:
            actual_range = (last_timestamp - first_timestamp).total_seconds()
            coverage_pct = (actual_range / requested_range) * 100.0
        else:
            coverage_pct = 0.0
        
        # Requirement 5.2: Report if actual range differs from requested
        first_cmp, start_cmp = _normalize_datetime_pair(first_timestamp, self.config.start_time)
        if first_cmp and start_cmp and first_cmp > start_cmp:
            warnings.append(
                f"Data starts at {first_timestamp}, later than requested "
                f"start time {self.config.start_time}"
            )
        
        last_cmp, end_cmp = _normalize_datetime_pair(last_timestamp, self.config.end_time)
        if last_cmp and end_cmp and last_cmp < end_cmp:
            warnings.append(
                f"Data ends at {last_timestamp}, earlier than requested "
                f"end time {self.config.end_time}"
            )
        
        # Requirement 5.3: Emit warning if coverage < 50%
        if coverage_pct < 50.0:
            warning_msg = (
                f"Data coverage is only {coverage_pct:.1f}% of requested range. "
                f"Proceeding with available data."
            )
            warnings.append(warning_msg)
            logger.warning(warning_msg)
        
        logger.info(
            f"Validated data for {self.config.symbol} on {self.config.exchange}: "
            f"{snapshot_count} snapshots, {trade_count} trades, "
            f"{coverage_pct:.1f}% coverage"
        )
        
        return DataValidationResult(
            is_valid=True,
            snapshot_count=snapshot_count,
            trade_count=trade_count,
            first_timestamp=first_timestamp,
            last_timestamp=last_timestamp,
            coverage_pct=coverage_pct,
            warnings=warnings,
            error_message=None,
        )
    
    async def export(self, output_path: Path) -> int:
        """Export data to JSONL file.
        
        Reads orderbook snapshots and trade records, merges them chronologically,
        transforms to feature snapshot format, and writes to JSONL file.
        
        Args:
            output_path: Path to output JSONL file.
            
        Returns:
            Number of snapshots exported.
            
        Raises:
            ValueError: If no data exists for the specified range.
        
        Validates: Requirements 1.1, 1.2, 6.2
        """
        if self._closed:
            raise RuntimeError("Data source has been closed")
        
        # Validate data availability first
        validation = await self.validate()
        if not validation.is_valid:
            raise ValueError(validation.error_message or "No data available")
        
        # Log any warnings
        for warning in validation.warnings:
            logger.warning(warning)
        
        # Export snapshots to JSONL
        count = 0
        with open(output_path, "w") as f:
            async for snapshot_dict in self.iter_snapshots():
                f.write(json.dumps(snapshot_dict) + "\n")
                count += 1
        
        logger.info(f"Exported {count} snapshots to {output_path}")
        return count
    
    async def iter_snapshots(self) -> AsyncIterator[dict]:
        """Iterate over transformed feature snapshots.
        
        Yields feature snapshots in chronological order, merging orderbook
        snapshots with trade records. Each snapshot is transformed to the
        format expected by ReplayWorker.
        
        This method uses async iteration to avoid blocking and supports
        cancellation by releasing resources promptly.
        
        Yields:
            Feature snapshot dictionaries ready for ReplayWorker.
        
        Validates: Requirements 1.1, 1.2, 3.1, 3.2, 6.2, 6.3
        """
        if self._closed:
            raise RuntimeError("Data source has been closed")
        
        # Requirement 1.1: Use OrderbookSnapshotReader and TradeRecordReader
        # Requirement 1.2: Query filtered by symbol, exchange, and time range
        orderbook_iter = self._orderbook_reader.iter_snapshots(
            symbol=self.config.symbol,
            exchange=self.config.exchange,
            start_time=self.config.start_time,
            end_time=self.config.end_time,
        )
        
        if self.config.include_trades:
            trade_iter = self._trade_reader.iter_trades(
                symbol=self.config.symbol,
                exchange=self.config.exchange,
                start_time=self.config.start_time,
                end_time=self.config.end_time,
            )
        else:
            # Create an empty async iterator if trades are not included
            trade_iter = self._empty_trade_iter()
        
        # Requirement 3.1, 3.2: Merge in chronological order
        # Requirement 6.2: Use async iteration
        async for orderbook_snapshot, trades in self._merger.merge(
            orderbook_iter, trade_iter
        ):
            # Build trade context from associated trades
            trade_context = self._build_trade_context(trades)
            
            # Transform to feature snapshot format
            snapshot_dict = self._transformer.transform(
                orderbook_snapshot, trade_context
            )
            
            yield snapshot_dict
    
    async def close(self) -> None:
        """Release resources.
        
        Marks the data source as closed. The database pool is not closed
        since it is owned by the caller and may be reused.
        
        Validates: Requirements 6.3, 6.4
        """
        self._closed = True
        # Note: We don't close the pool since it's owned by the caller
        # and may be reused for other operations (Requirement 6.4)
        logger.debug("TimescaleDBDataSource closed")
    
    def _build_trade_context(self, trades: List) -> Optional[TradeContext]:
        """Build trade context from a list of trades.
        
        Args:
            trades: List of PersistenceTradeRecord objects.
            
        Returns:
            TradeContext if trades exist, None otherwise.
        """
        if not trades:
            return None
        
        # Calculate aggregated trade metrics
        total_volume = 0.0
        buy_volume = 0.0
        sell_volume = 0.0
        
        for trade in trades:
            total_volume += trade.size
            if trade.side == "buy":
                buy_volume += trade.size
            else:
                sell_volume += trade.size
        
        # Last trade is the most recent (trades are in chronological order)
        last_trade = trades[-1]
        
        return TradeContext(
            last_trade_price=last_trade.price,
            last_trade_side=last_trade.side,
            trade_count=len(trades),
            total_volume=total_volume,
            buy_volume=buy_volume,
            sell_volume=sell_volume,
        )
    
    async def _empty_trade_iter(self) -> AsyncIterator:
        """Create an empty async iterator for when trades are not included."""
        # This is a generator that yields nothing
        return
        yield  # Make this a generator
