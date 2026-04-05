"""Dataset scanner for discovering available historical data in Redis streams.

Scans Redis streams to determine what historical data is available for backtesting,
including date ranges, data quality metrics, and completeness information.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, List

import redis.asyncio as redis

from quantgambit.observability.logger import log_info, log_warning


@dataclass
class DatasetMetadata:
    """Metadata about an available dataset for backtesting."""
    
    symbol: str
    exchange: str
    earliest_date: str  # ISO format
    latest_date: str  # ISO format
    candle_count: int
    gaps: int
    gap_dates: List[str] = field(default_factory=list)
    completeness_pct: float = 100.0
    last_updated: str = ""  # ISO format
    
    def to_dict(self) -> dict:
        """Convert to dictionary for API response."""
        return {
            "symbol": self.symbol,
            "exchange": self.exchange,
            "earliest_date": self.earliest_date,
            "latest_date": self.latest_date,
            "candle_count": self.candle_count,
            "gaps": self.gaps,
            "gap_dates": self.gap_dates,
            "completeness_pct": self.completeness_pct,
            "last_updated": self.last_updated,
        }


@dataclass
class ScanConfig:
    """Configuration for dataset scanning."""
    
    redis_url: str = "redis://localhost:6379"
    stream_key: str = "events:feature_snapshots"
    batch_size: int = 1000
    max_gap_minutes: int = 5  # Gap threshold in minutes
    exchange: str = "OKX"  # Default exchange


class DatasetScanner:
    """Scans Redis streams to discover available historical data for backtesting.
    
    This class provides functionality to:
    - Scan Redis streams for available feature snapshots
    - Calculate date ranges for each symbol
    - Detect data gaps and calculate completeness metrics
    - Return dataset metadata for API consumption
    """

    def __init__(self, redis_client: redis.Redis, config: Optional[ScanConfig] = None):
        """Initialize the dataset scanner.
        
        Args:
            redis_client: Async Redis client instance
            config: Optional scan configuration
        """
        self.redis = redis_client
        self.config = config or ScanConfig()

    async def scan_datasets(
        self,
        symbol_filter: Optional[str] = None,
    ) -> List[DatasetMetadata]:
        """Scan Redis streams to determine available data coverage.
        
        Args:
            symbol_filter: Optional symbol to filter results (e.g., "BTC-USDT-SWAP")
            
        Returns:
            List of DatasetMetadata objects with coverage information
        """
        log_info(
            "dataset_scan_start",
            stream_key=self.config.stream_key,
            symbol_filter=symbol_filter,
        )
        
        # Collect snapshots by symbol
        symbol_data: dict[str, list[float]] = {}
        
        last_id = "0"
        total_entries = 0
        
        while True:
            entries = await self.redis.xrange(
                self.config.stream_key,
                min=last_id,
                max="+",
                count=self.config.batch_size,
            )
            
            if not entries:
                break
            
            for entry_id, data in entries:
                # Skip if same as last_id (already processed)
                if entry_id == last_id and last_id != "0":
                    continue
                
                snapshot = self._parse_entry(entry_id, data)
                if snapshot is None:
                    continue
                
                symbol = snapshot.get("symbol")
                timestamp = snapshot.get("timestamp")
                
                if symbol is None or timestamp is None:
                    continue
                
                # Apply symbol filter if specified
                if symbol_filter and symbol != symbol_filter:
                    continue
                
                if symbol not in symbol_data:
                    symbol_data[symbol] = []
                symbol_data[symbol].append(timestamp)
                total_entries += 1
                
                last_id = entry_id
            
            # If we got fewer entries than batch size, we're done
            if len(entries) < self.config.batch_size:
                break
        
        log_info("dataset_scan_entries_read", total_entries=total_entries)
        
        # Build metadata for each symbol
        datasets: List[DatasetMetadata] = []
        for symbol, timestamps in symbol_data.items():
            metadata = self._build_metadata(symbol, timestamps)
            datasets.append(metadata)
        
        # Sort by symbol for consistent ordering
        datasets.sort(key=lambda d: d.symbol)
        
        log_info(
            "dataset_scan_complete",
            datasets_found=len(datasets),
            total_entries=total_entries,
        )
        
        return datasets

    def _parse_entry(self, entry_id: bytes | str, data: dict) -> Optional[dict]:
        """Parse a Redis stream entry into a snapshot dict.
        
        Args:
            entry_id: Redis stream entry ID
            data: Entry data dictionary
            
        Returns:
            Parsed snapshot dict or None if parsing fails
        """
        try:
            import json
            
            # Entry ID format: timestamp-sequence
            if isinstance(entry_id, bytes):
                entry_id = entry_id.decode("utf-8")
            
            timestamp_ms = int(entry_id.split("-")[0])
            timestamp = timestamp_ms / 1000.0
            
            # Data may be stored as JSON string or as individual fields
            if b"data" in data or "data" in data:
                raw = data.get(b"data") or data.get("data")
                if isinstance(raw, bytes):
                    raw = raw.decode("utf-8")
                snapshot = json.loads(raw)
            else:
                # Reconstruct from individual fields
                snapshot = {}
                for key, value in data.items():
                    if isinstance(key, bytes):
                        key = key.decode("utf-8")
                    if isinstance(value, bytes):
                        value = value.decode("utf-8")
                    try:
                        snapshot[key] = json.loads(value)
                    except (json.JSONDecodeError, TypeError):
                        snapshot[key] = value
            
            # Handle payload wrapper
            if "payload" in snapshot:
                payload = snapshot["payload"]
                symbol = payload.get("symbol") or snapshot.get("symbol")
                ts = payload.get("timestamp") or timestamp
            else:
                symbol = snapshot.get("symbol")
                ts = snapshot.get("timestamp", timestamp)
            
            # Extract symbol from data fields if not in snapshot
            if not symbol:
                symbol = data.get(b"symbol") or data.get("symbol")
                if isinstance(symbol, bytes):
                    symbol = symbol.decode("utf-8")
            
            return {
                "symbol": symbol,
                "timestamp": ts,
            }
            
        except Exception as e:
            log_warning("dataset_scan_parse_error", entry_id=str(entry_id), error=str(e))
            return None

    def _build_metadata(self, symbol: str, timestamps: list[float]) -> DatasetMetadata:
        """Build dataset metadata from collected timestamps.
        
        Args:
            symbol: Trading symbol
            timestamps: List of Unix timestamps
            
        Returns:
            DatasetMetadata with calculated metrics
        """
        if not timestamps:
            return DatasetMetadata(
                symbol=symbol,
                exchange=self.config.exchange,
                earliest_date="",
                latest_date="",
                candle_count=0,
                gaps=0,
                gap_dates=[],
                completeness_pct=0.0,
                last_updated="",
            )
        
        # Sort timestamps
        timestamps = sorted(timestamps)
        
        # Calculate date range
        earliest_ts = timestamps[0]
        latest_ts = timestamps[-1]
        
        earliest_dt = datetime.fromtimestamp(earliest_ts, tz=timezone.utc)
        latest_dt = datetime.fromtimestamp(latest_ts, tz=timezone.utc)
        
        # Detect gaps (periods > max_gap_minutes without data)
        gap_threshold_seconds = self.config.max_gap_minutes * 60
        gaps = 0
        gap_dates: List[str] = []
        
        for i in range(1, len(timestamps)):
            delta = timestamps[i] - timestamps[i - 1]
            if delta > gap_threshold_seconds:
                gaps += 1
                gap_dt = datetime.fromtimestamp(timestamps[i - 1], tz=timezone.utc)
                gap_dates.append(gap_dt.isoformat())
        
        # Calculate completeness
        # Expected entries: one per minute over the date range
        total_minutes = (latest_ts - earliest_ts) / 60.0
        expected_entries = max(1, int(total_minutes))
        actual_entries = len(timestamps)
        completeness_pct = min(100.0, (actual_entries / expected_entries) * 100.0)
        
        return DatasetMetadata(
            symbol=symbol,
            exchange=self.config.exchange,
            earliest_date=earliest_dt.isoformat(),
            latest_date=latest_dt.isoformat(),
            candle_count=len(timestamps),
            gaps=gaps,
            gap_dates=gap_dates[:10],  # Limit to first 10 gaps
            completeness_pct=round(completeness_pct, 2),
            last_updated=latest_dt.isoformat(),
        )


async def scan_datasets(
    redis_client: redis.Redis,
    symbol_filter: Optional[str] = None,
    stream_key: str = "events:feature_snapshots",
    exchange: str = "OKX",
) -> List[DatasetMetadata]:
    """Convenience function to scan datasets.
    
    Args:
        redis_client: Async Redis client
        symbol_filter: Optional symbol filter
        stream_key: Redis stream key to scan
        exchange: Exchange name for metadata
        
    Returns:
        List of DatasetMetadata objects
    """
    config = ScanConfig(stream_key=stream_key, exchange=exchange)
    scanner = DatasetScanner(redis_client, config)
    return await scanner.scan_datasets(symbol_filter=symbol_filter)
