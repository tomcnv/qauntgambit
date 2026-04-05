"""Data source abstraction for backtesting.

This module provides the DataSource protocol and DataSourceFactory for
creating data sources based on configuration. It supports both Redis-based
(legacy) and TimescaleDB-based data sources for backtest replay.

Feature: backtest-timescaledb-replay
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol, TYPE_CHECKING

if TYPE_CHECKING:
    import asyncpg
    import redis.asyncio as redis


class DataSourceType(str, Enum):
    """Supported data source types.
    
    Attributes:
        REDIS: Use Redis streams for feature snapshots (legacy behavior).
            Reads from events:feature_snapshots stream.
        TIMESCALEDB: Use TimescaleDB for orderbook snapshots and trade records.
            Reads from orderbook_snapshots and trade_records tables.
    
    Validates: Requirements 4.1
    """
    
    REDIS = "redis"
    TIMESCALEDB = "timescaledb"


@dataclass
class DataValidationResult:
    """Result of data availability validation.
    
    This dataclass contains the results of validating data availability
    before starting a backtest. It includes counts, timestamps, coverage
    metrics, and any warnings or errors.
    
    Attributes:
        is_valid: Whether the data is valid for backtesting.
            False if no data exists or critical errors occurred.
        snapshot_count: Number of orderbook snapshots in the time range.
        trade_count: Number of trade records in the time range.
        first_timestamp: Timestamp of the first available data point.
            None if no data exists.
        last_timestamp: Timestamp of the last available data point.
            None if no data exists.
        coverage_pct: Percentage of requested time range covered by data.
            Calculated as (actual_range / requested_range) * 100.
        warnings: List of warning messages (e.g., low coverage warnings).
        error_message: Error message if validation failed.
            None if validation succeeded.
    
    Validates: Requirements 5.2, 5.3, 5.5
    """
    
    is_valid: bool
    snapshot_count: int
    trade_count: int
    first_timestamp: Optional[datetime]
    last_timestamp: Optional[datetime]
    coverage_pct: float
    warnings: List[str] = field(default_factory=list)
    error_message: Optional[str] = None


class DataSource(Protocol):
    """Protocol for backtest data sources.
    
    This protocol defines the interface that all data sources must implement.
    It provides methods for exporting data to JSONL files, validating data
    availability, and releasing resources.
    
    Implementations:
        - SnapshotExporter: Redis-based data source (legacy)
        - TimescaleDBDataSource: TimescaleDB-based data source (new)
    
    Validates: Requirements 1.1, 4.4
    """
    
    async def export(self, output_path: Path) -> int:
        """Export data to JSONL file.
        
        Reads data from the source, transforms it to feature snapshot format,
        and writes to a JSONL file for replay.
        
        Args:
            output_path: Path to the output JSONL file.
        
        Returns:
            Number of snapshots exported.
        
        Raises:
            ValueError: If no data exists for the specified range.
        """
        ...
    
    async def validate(self) -> DataValidationResult:
        """Validate data availability before export.
        
        Checks that data exists for the specified time range and reports
        coverage statistics.
        
        Returns:
            DataValidationResult with availability information.
        """
        ...
    
    async def close(self) -> None:
        """Release resources.
        
        Closes any open connections or file handles.
        """
        ...


class DataSourceFactory:
    """Factory for creating data sources.
    
    This factory creates the appropriate data source implementation based
    on the configuration. It supports both Redis-based (legacy) and
    TimescaleDB-based data sources.
    
    The factory validates configuration parameters and raises ValueError
    for invalid configurations.
    
    Example:
        >>> config = {
        ...     "data_source": "timescaledb",
        ...     "symbol": "BTC/USDT",
        ...     "exchange": "binance",
        ...     "start_date": "2024-01-01",
        ...     "end_date": "2024-01-31",
        ... }
        >>> source = DataSourceFactory.create(config, db_pool=pool)
        >>> count = await source.export(Path("/tmp/snapshots.jsonl"))
    
    Validates: Requirements 1.1, 1.3, 4.1, 4.2, 4.4, 4.5
    """
    
    @staticmethod
    def create(
        config: Dict[str, Any],
        db_pool: Optional["asyncpg.Pool"] = None,
        redis_client: Optional["redis.Redis"] = None,
    ) -> DataSource:
        """Create a data source based on configuration.
        
        Args:
            config: Backtest configuration containing:
                - data_source: "redis" or "timescaledb" (default: "redis")
                - symbol: Trading symbol (required)
                - exchange: Exchange identifier (required for timescaledb)
                - start_date: Start of time range (YYYY-MM-DD or datetime)
                - end_date: End of time range (YYYY-MM-DD or datetime)
                - tenant_id: Optional tenant filter (default: "default")
                - bot_id: Optional bot filter (default: "default")
                - redis_url: Redis URL (for redis data source)
                - stream_key: Redis stream key (for redis data source)
                - batch_size: Batch size for queries (for timescaledb)
            db_pool: Database connection pool (required for timescaledb).
            redis_client: Redis client (optional for redis, will create if needed).
        
        Returns:
            DataSource implementation based on configuration.
        
        Raises:
            ValueError: If required parameters are missing or invalid.
        
        Validates: Requirements 1.1, 1.3, 4.1, 4.2, 4.4, 4.5
        """
        # Get data source type, defaulting to redis for backward compatibility
        data_source_str = config.get("data_source", "redis")
        
        # Validate data source type
        try:
            data_source_type = DataSourceType(data_source_str.lower())
        except ValueError:
            valid_types = [t.value for t in DataSourceType]
            raise ValueError(
                f"Invalid data_source '{data_source_str}'. "
                f"Valid options are: {valid_types}"
            )
        
        # Validate required symbol
        symbol = config.get("symbol")
        if not symbol:
            raise ValueError("symbol is required in configuration")
        
        if data_source_type == DataSourceType.REDIS:
            return DataSourceFactory._create_redis_source(config, redis_client)
        elif data_source_type == DataSourceType.TIMESCALEDB:
            return DataSourceFactory._create_timescaledb_source(config, db_pool)
        else:
            # This should never happen due to enum validation above
            raise ValueError(f"Unsupported data source type: {data_source_type}")
    
    @staticmethod
    def _create_redis_source(
        config: Dict[str, Any],
        redis_client: Optional["redis.Redis"] = None,
    ) -> DataSource:
        """Create a Redis-based data source (SnapshotExporter).
        
        Args:
            config: Backtest configuration.
            redis_client: Optional Redis client.
        
        Returns:
            SnapshotExporter instance.
        
        Validates: Requirements 1.3, 4.4
        """
        from quantgambit.backtesting.snapshot_exporter import (
            ExportConfig,
            SnapshotExporter,
        )
        
        # Parse dates
        start_time = DataSourceFactory._parse_datetime(config.get("start_date"))
        end_time = DataSourceFactory._parse_datetime(config.get("end_date"))
        
        # Create export config
        # Note: output_path will be set when export() is called
        export_config = ExportConfig(
            output_path=Path("/tmp/placeholder.jsonl"),  # Will be overridden
            symbol=config.get("symbol"),
            start_time=start_time,
            end_time=end_time,
            redis_url=config.get("redis_url", "redis://localhost:6379"),
            stream_key=config.get("stream_key", "events:feature_snapshots"),
            batch_size=config.get("batch_size", 1000),
            max_snapshots=config.get("max_snapshots"),
        )
        
        # Wrap SnapshotExporter to conform to DataSource protocol
        return _RedisDataSourceAdapter(export_config, redis_client)
    
    @staticmethod
    def _create_timescaledb_source(
        config: Dict[str, Any],
        db_pool: Optional["asyncpg.Pool"] = None,
    ) -> DataSource:
        """Create a TimescaleDB-based data source.
        
        Args:
            config: Backtest configuration.
            db_pool: Database connection pool.
        
        Returns:
            TimescaleDBDataSource instance.
        
        Raises:
            ValueError: If exchange is missing or db_pool is None.
        
        Validates: Requirements 1.1, 4.2
        """
        from quantgambit.backtesting.timescaledb_data_source import (
            TimescaleDBDataSource,
            TimescaleDBDataSourceConfig,
        )
        
        # Validate exchange is provided for timescaledb
        exchange = config.get("exchange")
        if not exchange:
            raise ValueError(
                "exchange is required when data_source='timescaledb'"
            )
        
        # Validate db_pool is provided
        if db_pool is None:
            raise ValueError(
                "db_pool is required when data_source='timescaledb'"
            )
        
        # Parse dates
        start_time = DataSourceFactory._parse_datetime(config.get("start_date"))
        end_time = DataSourceFactory._parse_datetime(config.get("end_date"))
        
        # Create TimescaleDB data source config
        ts_config = TimescaleDBDataSourceConfig(
            symbol=config.get("symbol"),
            exchange=exchange,
            start_time=start_time,
            end_time=end_time,
            tenant_id=config.get("tenant_id", "default"),
            bot_id=config.get("bot_id", "default"),
            batch_size=config.get("batch_size", 1000),
            include_trades=config.get("include_trades", True),
        )
        
        return TimescaleDBDataSource(db_pool, ts_config)
    
    @staticmethod
    def _parse_datetime(value: Any) -> Optional[datetime]:
        """Parse datetime from various formats.
        
        Args:
            value: String or datetime value.
        
        Returns:
            Parsed datetime or None if value is None.
        """
        if value is None:
            return None
        
        if isinstance(value, datetime):
            return value
        
        if isinstance(value, str):
            formats = [
                "%Y-%m-%d",
                "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%dT%H:%M:%SZ",
                "%Y-%m-%d %H:%M:%S",
            ]
            for fmt in formats:
                try:
                    return datetime.strptime(value, fmt)
                except ValueError:
                    continue
        
        return None


class _RedisDataSourceAdapter:
    """Adapter to make SnapshotExporter conform to DataSource protocol.
    
    This adapter wraps the existing SnapshotExporter to provide the
    DataSource protocol interface. It handles the differences in
    method signatures and adds the validate() method.
    
    Validates: Requirements 1.3, 4.4
    """
    
    def __init__(
        self,
        config: "ExportConfig",
        redis_client: Optional["redis.Redis"] = None,
    ) -> None:
        """Initialize the adapter.
        
        Args:
            config: Export configuration.
            redis_client: Optional Redis client.
        """
        from quantgambit.backtesting.snapshot_exporter import (
            ExportConfig,
            SnapshotExporter,
        )
        
        self._config = config
        self._redis_client = redis_client
        self._exporter: Optional[SnapshotExporter] = None
    
    async def export(self, output_path: Path) -> int:
        """Export data to JSONL file.
        
        Args:
            output_path: Path to the output JSONL file.
        
        Returns:
            Number of snapshots exported.
        """
        from quantgambit.backtesting.snapshot_exporter import (
            ExportConfig,
            SnapshotExporter,
        )
        
        # Create a new config with the correct output path
        export_config = ExportConfig(
            output_path=output_path,
            symbol=self._config.symbol,
            start_time=self._config.start_time,
            end_time=self._config.end_time,
            redis_url=self._config.redis_url,
            stream_key=self._config.stream_key,
            batch_size=self._config.batch_size,
            max_snapshots=self._config.max_snapshots,
        )
        
        self._exporter = SnapshotExporter(export_config)
        
        try:
            await self._exporter.connect()
            return await self._exporter.export()
        finally:
            await self._exporter.close()
    
    async def validate(self) -> DataValidationResult:
        """Validate data availability.
        
        For Redis data source, we don't have a way to validate data
        availability without actually reading the stream. This method
        returns a result indicating validation is not supported.
        
        Returns:
            DataValidationResult indicating validation is not supported.
        """
        # Redis data source doesn't support pre-validation
        # Return a result that allows the export to proceed
        return DataValidationResult(
            is_valid=True,
            snapshot_count=0,  # Unknown
            trade_count=0,  # Not applicable for Redis
            first_timestamp=None,  # Unknown
            last_timestamp=None,  # Unknown
            coverage_pct=100.0,  # Assume full coverage
            warnings=["Redis data source does not support pre-validation"],
            error_message=None,
        )
    
    async def close(self) -> None:
        """Release resources."""
        if self._exporter:
            await self._exporter.close()
            self._exporter = None
