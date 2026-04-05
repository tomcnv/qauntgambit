"""Export feature snapshots from Redis to JSONL for backtesting replay."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import AsyncIterator, Optional

import redis.asyncio as redis

from quantgambit.observability.logger import log_info, log_warning


@dataclass
class ExportConfig:
    """Configuration for snapshot export."""
    
    output_path: Path
    symbol: Optional[str] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    redis_url: str = "redis://localhost:6379"
    stream_key: str = "events:feature_snapshots"
    batch_size: int = 1000
    max_snapshots: Optional[int] = None

    @classmethod
    def from_env(cls, output_path: Path) -> "ExportConfig":
        """Create config from environment variables."""
        start_str = os.getenv("EXPORT_START_TIME")
        end_str = os.getenv("EXPORT_END_TIME")
        return cls(
            output_path=output_path,
            symbol=os.getenv("EXPORT_SYMBOL"),
            start_time=_parse_datetime(start_str) if start_str else None,
            end_time=_parse_datetime(end_str) if end_str else None,
            redis_url=os.getenv("REDIS_URL", "redis://localhost:6379"),
            stream_key=os.getenv("EXPORT_STREAM_KEY", "events:feature_snapshots"),
            batch_size=int(os.getenv("EXPORT_BATCH_SIZE", "1000")),
            max_snapshots=_parse_int(os.getenv("EXPORT_MAX_SNAPSHOTS")),
        )


class SnapshotExporter:
    """Exports feature snapshots from Redis streams to JSONL files."""

    def __init__(self, config: ExportConfig):
        self.config = config
        self._redis: Optional[redis.Redis] = None

    async def connect(self) -> None:
        """Connect to Redis."""
        self._redis = redis.from_url(self.config.redis_url)
        await self._redis.ping()
        log_info("snapshot_exporter_connected", redis_url=self.config.redis_url)

    async def close(self) -> None:
        """Close Redis connection."""
        if self._redis:
            await self._redis.close()
            self._redis = None

    async def export(self) -> int:
        """Export snapshots to JSONL file. Returns count of exported snapshots."""
        if not self._redis:
            await self.connect()

        log_info(
            "snapshot_export_start",
            output=str(self.config.output_path),
            symbol=self.config.symbol,
            start_time=str(self.config.start_time) if self.config.start_time else None,
            end_time=str(self.config.end_time) if self.config.end_time else None,
        )

        count = 0
        self.config.output_path.parent.mkdir(parents=True, exist_ok=True)

        with self.config.output_path.open("w", encoding="utf-8") as handle:
            async for snapshot in self._read_snapshots():
                if self.config.max_snapshots and count >= self.config.max_snapshots:
                    break
                handle.write(json.dumps(snapshot) + "\n")
                count += 1
                if count % 10000 == 0:
                    log_info("snapshot_export_progress", count=count)

        log_info("snapshot_export_complete", count=count, output=str(self.config.output_path))
        return count

    async def _read_snapshots(self) -> AsyncIterator[dict]:
        """Read snapshots from Redis stream with filtering."""
        start_id = self._time_to_stream_id(self.config.start_time) if self.config.start_time else "0"
        end_id = self._time_to_stream_id(self.config.end_time) if self.config.end_time else "+"

        last_id = start_id
        while True:
            # Use XRANGE to read in batches
            entries = await self._redis.xrange(
                self.config.stream_key,
                min=last_id,
                max=end_id,
                count=self.config.batch_size,
            )

            if not entries:
                break

            for entry_id, data in entries:
                # Skip the first entry if it's the same as last_id (already processed)
                if entry_id == last_id and last_id != start_id:
                    continue

                snapshot = self._parse_entry(entry_id, data)
                if snapshot and self._matches_filter(snapshot):
                    yield snapshot

                last_id = entry_id

            # If we got fewer entries than batch size, we're done
            if len(entries) < self.config.batch_size:
                break

    def _parse_entry(self, entry_id: bytes | str, data: dict) -> Optional[dict]:
        """Parse a Redis stream entry into a snapshot dict."""
        try:
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

            # Ensure required fields
            if "timestamp" not in snapshot:
                snapshot["timestamp"] = timestamp
            if "symbol" not in snapshot:
                symbol = data.get(b"symbol") or data.get("symbol")
                if isinstance(symbol, bytes):
                    symbol = symbol.decode("utf-8")
                snapshot["symbol"] = symbol

            return self._normalize_snapshot(snapshot)

        except Exception as e:
            log_warning("snapshot_parse_error", entry_id=str(entry_id), error=str(e))
            return None

    def _normalize_snapshot(self, snapshot: dict) -> dict:
        """Normalize snapshot to expected format for ReplayWorker."""
        # Handle payload wrapper from events:features stream
        if "payload" in snapshot:
            payload = snapshot["payload"]
            # Extract from payload
            symbol = payload.get("symbol") or snapshot.get("symbol")
            timestamp = payload.get("timestamp") or snapshot.get("timestamp")
            market_context = payload.get("market_context", {})
            features = payload.get("features", {})
            prediction = payload.get("prediction", {})
            warmup_ready = payload.get("warmup_ready", True)
        else:
            symbol = snapshot.get("symbol")
            timestamp = snapshot.get("timestamp")
            market_context = snapshot.get("market_context", {})
            features = snapshot.get("features", {})
            prediction = snapshot.get("prediction", {})
            warmup_ready = snapshot.get("warmup_ready", True)

        # Ensure market_context and features exist
        if not market_context:
            market_context = {}
        if not features:
            features = {}

        # Move common fields to market_context if at top level
        market_fields = ["price", "bid", "ask", "spread_bps", "bid_depth_usd", "ask_depth_usd"]
        for field in market_fields:
            if field in snapshot and field not in market_context:
                market_context[field] = snapshot[field]

        # Move feature fields
        feature_fields = ["confidence", "stop_loss", "take_profit", "volatility_regime", "atr_5m"]
        for field in feature_fields:
            if field in snapshot and field not in features:
                features[field] = snapshot[field]

        # Add prediction confidence to features if available
        if prediction and "confidence" in prediction:
            features["confidence"] = prediction["confidence"]
            features["direction"] = prediction.get("direction")

        return {
            "symbol": symbol,
            "timestamp": timestamp,
            "market_context": market_context,
            "features": features,
            "prediction": prediction,
            "warmup_ready": warmup_ready,
        }

    def _matches_filter(self, snapshot: dict) -> bool:
        """Check if snapshot matches configured filters."""
        if self.config.symbol:
            if snapshot.get("symbol") != self.config.symbol:
                return False
        return True

    def _time_to_stream_id(self, dt: datetime) -> str:
        """Convert datetime to Redis stream ID."""
        timestamp_ms = int(dt.timestamp() * 1000)
        return f"{timestamp_ms}-0"


def _parse_datetime(value: str) -> Optional[datetime]:
    """Parse datetime from various formats."""
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


def _parse_int(value: Optional[str]) -> Optional[int]:
    """Parse optional integer."""
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


async def export_snapshots(
    output_path: Path,
    symbol: Optional[str] = None,
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
    redis_url: str = "redis://localhost:6379",
    stream_key: str = "events:feature_snapshots",
    max_snapshots: Optional[int] = None,
) -> int:
    """Convenience function to export snapshots.
    
    Args:
        output_path: Path to output JSONL file
        symbol: Optional symbol filter (e.g., "BTC-USDT-SWAP")
        start_time: Optional start time filter
        end_time: Optional end time filter
        redis_url: Redis connection URL
        stream_key: Redis stream key to read from
        max_snapshots: Maximum number of snapshots to export
        
    Returns:
        Number of snapshots exported
    """
    config = ExportConfig(
        output_path=output_path,
        symbol=symbol,
        start_time=start_time,
        end_time=end_time,
        redis_url=redis_url,
        stream_key=stream_key,
        max_snapshots=max_snapshots,
    )
    exporter = SnapshotExporter(config)
    try:
        await exporter.connect()
        return await exporter.export()
    finally:
        await exporter.close()
