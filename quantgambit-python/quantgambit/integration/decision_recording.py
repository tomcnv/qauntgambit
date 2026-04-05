"""Decision recording for trading pipeline integration.

This module provides the RecordedDecision dataclass and DecisionRecorder class
for capturing complete decision context for replay and analysis.

Feature: trading-pipeline-integration
Requirements: 2.1 - WHEN a live trading decision is made THEN the System SHALL record
              the complete decision context including market snapshot, features,
              stage results, and final decision
Requirements: 2.2 - THE System SHALL store decision records in TimescaleDB with
              efficient time-range queries
Requirements: 2.3 - WHEN recording a decision THEN the System SHALL include all
              pipeline stage outputs and rejection reasons
Requirements: 2.5 - WHEN a decision is recorded THEN the System SHALL include
              the configuration version used for that decision
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
from dataclasses import asdict, dataclass, field
from decimal import Decimal
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Protocol
from uuid import uuid4

if TYPE_CHECKING:
    from quantgambit.integration.config_registry import ConfigurationRegistry

logger = logging.getLogger(__name__)


@dataclass
class RecordedDecision:
    """Complete decision record for replay.
    
    Represents a full snapshot of a trading decision including all input context,
    pipeline execution details, and final outcome. This enables replay and
    analysis of historical decisions.
    
    Feature: trading-pipeline-integration
    Requirements: 2.1, 2.3, 2.5
    
    Attributes:
        decision_id: Unique identifier for this decision record
        timestamp: When the decision was made
        symbol: Trading symbol (e.g., "BTCUSDT")
        config_version: Version ID of the configuration used for this decision
        
        market_snapshot: Complete market state at decision time (prices, orderbook, etc.)
        features: Computed features used for decision making
        positions: Current open positions at decision time
        account_state: Account state (equity, margin, etc.) at decision time
        
        stage_results: Output from each pipeline stage
        rejection_stage: Name of stage that rejected (if rejected)
        rejection_reason: Reason for rejection (if rejected)
        
        decision: Final decision outcome ("accepted", "rejected", "shadow")
        signal: Generated signal details (if accepted)
        profile_id: Trading profile ID used for this decision
    """
    # Core identifiers
    decision_id: str
    timestamp: datetime
    symbol: str
    config_version: str
    
    # Input context
    market_snapshot: Dict[str, Any] = field(default_factory=dict)
    features: Dict[str, Any] = field(default_factory=dict)
    positions: List[Dict[str, Any]] = field(default_factory=list)
    account_state: Dict[str, Any] = field(default_factory=dict)
    
    # Pipeline execution
    stage_results: List[Dict[str, Any]] = field(default_factory=list)
    rejection_stage: Optional[str] = None
    rejection_reason: Optional[str] = None
    
    # Final decision
    decision: str = "rejected"  # "accepted", "rejected", "shadow"
    signal: Optional[Dict[str, Any]] = None
    profile_id: Optional[str] = None
    
    def __post_init__(self) -> None:
        """Validate the RecordedDecision after initialization."""
        if not self.decision_id:
            raise ValueError("decision_id cannot be empty")
        if not self.symbol:
            raise ValueError("symbol cannot be empty")
        if not self.config_version:
            raise ValueError("config_version cannot be empty")
        if self.decision not in ("accepted", "rejected", "shadow"):
            raise ValueError(
                f"decision must be 'accepted', 'rejected', or 'shadow', got '{self.decision}'"
            )
        
        # Ensure timestamp has timezone info
        if self.timestamp.tzinfo is None:
            object.__setattr__(
                self,
                'timestamp',
                self.timestamp.replace(tzinfo=timezone.utc)
            )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization.
        
        Returns:
            Dictionary representation of the RecordedDecision
        """
        return {
            "decision_id": self.decision_id,
            "timestamp": self.timestamp.isoformat(),
            "symbol": self.symbol,
            "config_version": self.config_version,
            "market_snapshot": self.market_snapshot,
            "features": self.features,
            "positions": self.positions,
            "account_state": self.account_state,
            "stage_results": self.stage_results,
            "rejection_stage": self.rejection_stage,
            "rejection_reason": self.rejection_reason,
            "decision": self.decision,
            "signal": self.signal,
            "profile_id": self.profile_id,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RecordedDecision":
        """Create RecordedDecision from dictionary.
        
        Args:
            data: Dictionary with RecordedDecision fields
            
        Returns:
            RecordedDecision instance
        """
        timestamp = data["timestamp"]
        if isinstance(timestamp, str):
            # Parse ISO format string
            timestamp = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
        
        return cls(
            decision_id=data["decision_id"],
            timestamp=timestamp,
            symbol=data["symbol"],
            config_version=data["config_version"],
            market_snapshot=data.get("market_snapshot", {}),
            features=data.get("features", {}),
            positions=data.get("positions", []),
            account_state=data.get("account_state", {}),
            stage_results=data.get("stage_results", []),
            rejection_stage=data.get("rejection_stage"),
            rejection_reason=data.get("rejection_reason"),
            decision=data.get("decision", "rejected"),
            signal=data.get("signal"),
            profile_id=data.get("profile_id"),
        )
    
    def to_db_tuple(self) -> tuple:
        """Convert to tuple for database insertion.
        
        Returns:
            Tuple of values in database column order for executemany
        """
        return (
            self.decision_id,
            self.timestamp,
            self.symbol,
            self.config_version,
            json.dumps(self.market_snapshot),
            json.dumps(self.features),
            json.dumps(self.positions) if self.positions else None,
            json.dumps(self.account_state) if self.account_state else None,
            json.dumps(self.stage_results) if self.stage_results else None,
            self.rejection_stage,
            self.rejection_reason,
            self.decision,
            json.dumps(self.signal) if self.signal else None,
            self.profile_id,
        )
    
    @classmethod
    def from_db_row(cls, row) -> "RecordedDecision":
        """Create RecordedDecision from database row.
        
        Args:
            row: Database row from asyncpg
            
        Returns:
            RecordedDecision instance
        """
        # Parse JSON fields
        def parse_json(value, default):
            if value is None:
                return default
            if isinstance(value, (dict, list)):
                return value
            try:
                return json.loads(value)
            except (json.JSONDecodeError, TypeError):
                return default
        
        # Ensure timestamp has timezone info
        timestamp = row["timestamp"]
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        
        return cls(
            decision_id=str(row["decision_id"]),
            timestamp=timestamp,
            symbol=row["symbol"],
            config_version=row["config_version"],
            market_snapshot=parse_json(row["market_snapshot"], {}),
            features=parse_json(row["features"], {}),
            positions=parse_json(row.get("positions"), []),
            account_state=parse_json(row.get("account_state"), {}),
            stage_results=parse_json(row.get("stage_results"), []),
            rejection_stage=row.get("rejection_stage"),
            rejection_reason=row.get("rejection_reason"),
            decision=row["decision"],
            signal=parse_json(row.get("signal"), None),
            profile_id=row.get("profile_id"),
        )
    
    def is_rejected(self) -> bool:
        """Check if this decision was rejected.
        
        Returns:
            True if decision was rejected
        """
        return self.decision == "rejected"
    
    def is_accepted(self) -> bool:
        """Check if this decision was accepted.
        
        Returns:
            True if decision was accepted
        """
        return self.decision == "accepted"
    
    def is_shadow(self) -> bool:
        """Check if this was a shadow decision.
        
        Returns:
            True if this was a shadow decision
        """
        return self.decision == "shadow"
    
    def get_stage_result(self, stage_name: str) -> Optional[Dict[str, Any]]:
        """Get the result from a specific pipeline stage.
        
        Args:
            stage_name: Name of the stage to look up
            
        Returns:
            Stage result dict if found, None otherwise
        """
        for stage in self.stage_results:
            if stage.get("stage") == stage_name or stage.get("name") == stage_name:
                return stage
        return None
    
    def has_complete_context(self) -> bool:
        """Check if this decision has complete context for replay.
        
        A decision has complete context if it has market_snapshot, features,
        and config_version set.
        
        Returns:
            True if decision has complete context
        """
        return bool(
            self.market_snapshot
            and self.features
            and self.config_version
        )



class MarketSnapshotProtocol(Protocol):
    """Protocol for market snapshot objects that can be converted to dict."""
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        ...


class StageContextProtocol(Protocol):
    """Protocol for stage context objects."""
    
    data: dict
    rejection_stage: Optional[str]
    rejection_reason: Optional[str]
    signal: Optional[dict]
    profile_id: Optional[str]
    stage_trace: Optional[list]


class DecisionRecorder:
    """Records live decisions with full context for replay and analysis.
    
    The DecisionRecorder captures complete decision context including market
    snapshots, features, pipeline stage results, and final decisions. It uses
    batched writes to TimescaleDB for efficient storage.
    
    Feature: trading-pipeline-integration
    Requirements: 2.1, 2.2
    
    Attributes:
        _pool: asyncpg connection pool for TimescaleDB
        _config_registry: ConfigurationRegistry for getting config versions
        _batch: List of RecordedDecision objects waiting to be flushed
        _batch_size: Maximum batch size before auto-flush (default: 100)
        _flush_interval_sec: Maximum time between flushes (default: 5.0)
        _max_buffer_size: Maximum buffer size before forced flush (default: 200)
        _last_flush_time: Timestamp of last flush
        _flush_lock: Lock to prevent concurrent flushes
    
    Example:
        >>> recorder = DecisionRecorder(pool, config_registry)
        >>> decision_id = await recorder.record(
        ...     symbol="BTCUSDT",
        ...     snapshot=market_snapshot,
        ...     features=features,
        ...     ctx=stage_context,
        ...     decision="accepted",
        ... )
        >>> await recorder.flush()  # Force flush remaining records
    """
    
    # Default configuration
    DEFAULT_BATCH_SIZE = 100
    DEFAULT_FLUSH_INTERVAL_SEC = 5.0
    DEFAULT_MAX_BUFFER_SIZE = 200
    
    def __init__(
        self,
        timescale_pool,
        config_registry: "ConfigurationRegistry",
        batch_size: int = DEFAULT_BATCH_SIZE,
        flush_interval_sec: float = DEFAULT_FLUSH_INTERVAL_SEC,
        max_buffer_size: int = DEFAULT_MAX_BUFFER_SIZE,
    ) -> None:
        """Initialize the DecisionRecorder.
        
        Args:
            timescale_pool: asyncpg connection pool for TimescaleDB
            config_registry: ConfigurationRegistry for getting config versions
            batch_size: Maximum batch size before auto-flush (default: 100)
            flush_interval_sec: Maximum time between flushes (default: 5.0)
            max_buffer_size: Maximum buffer size before forced flush (default: 200)
        """
        self._pool = timescale_pool
        self._config_registry = config_registry
        self._batch: List[RecordedDecision] = []
        self._batch_size = batch_size
        self._flush_interval_sec = flush_interval_sec
        self._max_buffer_size = max_buffer_size
        self._last_flush_time = datetime.now(timezone.utc)
        self._flush_lock = asyncio.Lock()
        self._flush_task: Optional[asyncio.Task] = None
    
    @property
    def batch_size(self) -> int:
        """Get the current batch size."""
        return self._batch_size
    
    @batch_size.setter
    def batch_size(self, value: int) -> None:
        """Set the batch size."""
        if value < 1:
            raise ValueError("batch_size must be at least 1")
        self._batch_size = value
    
    @property
    def flush_interval_sec(self) -> float:
        """Get the current flush interval in seconds."""
        return self._flush_interval_sec
    
    @flush_interval_sec.setter
    def flush_interval_sec(self, value: float) -> None:
        """Set the flush interval in seconds."""
        if value <= 0:
            raise ValueError("flush_interval_sec must be positive")
        self._flush_interval_sec = value
    
    @property
    def pending_count(self) -> int:
        """Get the number of pending records in the batch."""
        return len(self._batch)
    
    async def record(
        self,
        symbol: str,
        snapshot: Any,
        features: Any,
        ctx: Any,
        decision: str,
    ) -> str:
        """Record a decision with full context.
        
        Creates a RecordedDecision with all context and adds it to the batch.
        Automatically flushes when batch is full or buffer exceeds max size.
        
        Feature: trading-pipeline-integration
        Requirements: 2.1, 2.2
        
        Args:
            symbol: Trading symbol (e.g., "BTCUSDT")
            snapshot: MarketSnapshot or dict with market state
            features: Features object or dict with computed features
            ctx: StageContext with pipeline execution details
            decision: Decision outcome ("accepted", "rejected", "shadow")
            
        Returns:
            decision_id for reference
            
        Raises:
            ValueError: If decision is not a valid value
        """
        if decision not in ("accepted", "rejected", "shadow"):
            raise ValueError(
                f"decision must be 'accepted', 'rejected', or 'shadow', got '{decision}'"
            )
        
        # Get current config version
        config = await self._config_registry.get_live_config()
        
        # Convert snapshot to dict
        if hasattr(snapshot, 'to_dict'):
            market_snapshot_dict = snapshot.to_dict()
        elif hasattr(snapshot, '__dataclass_fields__'):
            market_snapshot_dict = asdict(snapshot)
        elif isinstance(snapshot, dict):
            market_snapshot_dict = snapshot
        else:
            market_snapshot_dict = {}
        market_snapshot_dict = _json_safe(market_snapshot_dict)
        
        # Convert features to dict
        if hasattr(features, '__dataclass_fields__'):
            features_dict = asdict(features)
        elif isinstance(features, dict):
            features_dict = features
        else:
            features_dict = {}
        features_dict = _json_safe(features_dict)
        
        # Extract context data
        ctx_data = getattr(ctx, 'data', {}) if ctx else {}
        positions = ctx_data.get("positions", []) if isinstance(ctx_data, dict) else []
        account_state = ctx_data.get("account", {}) if isinstance(ctx_data, dict) else {}
        positions = _normalize_positions(positions)
        if isinstance(account_state, dict):
            account_state = _json_safe(account_state)
        
        # Create the recorded decision
        record = RecordedDecision(
            decision_id=f"dec_{uuid4().hex[:12]}",
            timestamp=datetime.now(timezone.utc),
            symbol=symbol,
            config_version=config.version_id,
            market_snapshot=market_snapshot_dict,
            features=features_dict,
            positions=positions if isinstance(positions, list) else [],
            account_state=account_state if isinstance(account_state, dict) else {},
            stage_results=_json_safe(getattr(ctx, 'stage_trace', []) or [] if ctx else []),
            rejection_stage=getattr(ctx, 'rejection_stage', None) if ctx else None,
            rejection_reason=getattr(ctx, 'rejection_reason', None) if ctx else None,
            decision=decision,
            signal=_json_safe(_normalize_signal(getattr(ctx, 'signal', None) if ctx else None)),
            profile_id=getattr(ctx, 'profile_id', None) if ctx else None,
        )
        
        self._batch.append(record)
        
        # Auto-flush if batch is full
        if len(self._batch) >= self._batch_size:
            await self._flush()
        # Force flush if buffer exceeds max size (2x batch_size by default)
        elif len(self._batch) >= self._max_buffer_size:
            logger.warning(
                f"Decision buffer exceeded max size ({self._max_buffer_size}), "
                f"forcing flush"
            )
            await self._flush()
        
        return record.decision_id
    
    async def flush(self) -> int:
        """Flush all pending records to the database.
        
        Public method to force a flush of all pending records.
        
        Returns:
            Number of records flushed
        """
        return await self._flush()
    
    async def _flush(self) -> int:
        """Flush batch to database.
        
        Internal method that performs the actual database write.
        Uses a lock to prevent concurrent flushes.
        
        Feature: trading-pipeline-integration
        Requirements: 2.2
        
        Returns:
            Number of records flushed
            
        Raises:
            Exception: If database write fails after retries
        """
        if not self._batch:
            return 0
        
        async with self._flush_lock:
            if not self._batch:
                return 0
            
            # Take the current batch and clear it
            batch_to_flush = self._batch.copy()
            self._batch.clear()
            
            try:
                await self._write_batch(batch_to_flush)
                self._last_flush_time = datetime.now(timezone.utc)
                logger.debug(f"Flushed {len(batch_to_flush)} decision records")
                return len(batch_to_flush)
            except Exception as e:
                # On failure, put records back in batch for retry
                # But respect max buffer size
                remaining_capacity = self._max_buffer_size - len(self._batch)
                records_to_restore = batch_to_flush[:remaining_capacity]
                
                if records_to_restore:
                    self._batch = records_to_restore + self._batch
                
                dropped_count = len(batch_to_flush) - len(records_to_restore)
                if dropped_count > 0:
                    logger.error(
                        f"Dropped {dropped_count} decision records due to buffer overflow"
                    )
                
                logger.error(f"Failed to flush decision records: {e}")
                raise
    
    async def _write_batch(self, batch: List[RecordedDecision]) -> None:
        """Write a batch of records to the database.
        
        Args:
            batch: List of RecordedDecision objects to write
            
        Raises:
            Exception: If database write fails
        """
        if not batch:
            return
        
        async with self._pool.acquire() as conn:
            # Use executemany for efficient batch insert
            # Note: ON CONFLICT must include all columns in the composite primary key
            # (decision_id, timestamp) for TimescaleDB hypertable compatibility
            await conn.executemany(
                """
                INSERT INTO recorded_decisions (
                    decision_id, timestamp, symbol, config_version,
                    market_snapshot, features, positions, account_state,
                    stage_results, rejection_stage, rejection_reason,
                    decision, signal, profile_id
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14)
                ON CONFLICT (decision_id, timestamp) DO NOTHING
                """,
                [r.to_db_tuple() for r in batch]
            )
    
    async def start_periodic_flush(self) -> None:
        """Start a background task that periodically flushes the batch.
        
        This ensures records are flushed even if the batch doesn't fill up.
        """
        if self._flush_task is not None:
            return
        
        self._flush_task = asyncio.create_task(self._periodic_flush_loop())
    
    async def stop_periodic_flush(self) -> None:
        """Stop the periodic flush background task and flush remaining records."""
        if self._flush_task is not None:
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass
            self._flush_task = None
        
        # Flush any remaining records
        await self._flush()
    
    async def _periodic_flush_loop(self) -> None:
        """Background loop that periodically flushes the batch."""
        while True:
            try:
                await asyncio.sleep(self._flush_interval_sec)
                
                # Check if we have pending records and enough time has passed
                if self._batch:
                    time_since_flush = (
                        datetime.now(timezone.utc) - self._last_flush_time
                    ).total_seconds()
                    
                    if time_since_flush >= self._flush_interval_sec:
                        await self._flush()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in periodic flush loop: {e}")
    
    async def __aenter__(self) -> "DecisionRecorder":
        """Async context manager entry."""
        await self.start_periodic_flush()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit."""
        await self.stop_periodic_flush()
    
    async def query_by_time_range(
        self,
        start_time: datetime,
        end_time: datetime,
        symbol: Optional[str] = None,
        decision: Optional[str] = None,
        rejection_stage: Optional[str] = None,
        limit: int = 1000,
    ) -> List[RecordedDecision]:
        """Query decisions by time range with optional filters.
        
        Queries the recorded_decisions table for decisions within the specified
        time range, with optional filtering by symbol, decision outcome, and
        rejection stage.
        
        Feature: trading-pipeline-integration
        Requirements: 2.4 - THE System SHALL support querying decisions by time range,
                      symbol, decision outcome, and rejection stage
        
        Args:
            start_time: Start of time range (inclusive)
            end_time: End of time range (inclusive)
            symbol: Optional filter by trading symbol (e.g., "BTCUSDT")
            decision: Optional filter by decision outcome ("accepted", "rejected", "shadow")
            rejection_stage: Optional filter by rejection stage name
            limit: Maximum number of results to return (default: 1000)
            
        Returns:
            List of RecordedDecision objects matching the filters, ordered by
            timestamp descending (most recent first)
            
        Raises:
            ValueError: If decision is not a valid value
            
        Example:
            >>> decisions = await recorder.query_by_time_range(
            ...     start_time=datetime(2024, 1, 1, tzinfo=timezone.utc),
            ...     end_time=datetime(2024, 1, 2, tzinfo=timezone.utc),
            ...     symbol="BTCUSDT",
            ...     decision="rejected",
            ... )
        """
        # Validate decision filter if provided
        if decision is not None and decision not in ("accepted", "rejected", "shadow"):
            raise ValueError(
                f"decision must be 'accepted', 'rejected', or 'shadow', got '{decision}'"
            )
        
        # Ensure timestamps have timezone info
        if start_time.tzinfo is None:
            start_time = start_time.replace(tzinfo=timezone.utc)
        if end_time.tzinfo is None:
            end_time = end_time.replace(tzinfo=timezone.utc)
        
        # Build query with dynamic filters
        query_parts = [
            "SELECT * FROM recorded_decisions",
            "WHERE timestamp >= $1 AND timestamp <= $2",
        ]
        params: List[Any] = [start_time, end_time]
        param_idx = 3
        
        if symbol is not None:
            query_parts.append(f"AND symbol = ${param_idx}")
            params.append(symbol)
            param_idx += 1
        
        if decision is not None:
            query_parts.append(f"AND decision = ${param_idx}")
            params.append(decision)
            param_idx += 1
        
        if rejection_stage is not None:
            query_parts.append(f"AND rejection_stage = ${param_idx}")
            params.append(rejection_stage)
            param_idx += 1
        
        query_parts.append("ORDER BY timestamp DESC")
        query_parts.append(f"LIMIT ${param_idx}")
        params.append(limit)
        
        query = " ".join(query_parts)
        
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(query, *params)
            return [RecordedDecision.from_db_row(row) for row in rows]
    
    async def count_by_time_range(
        self,
        start_time: datetime,
        end_time: datetime,
        symbol: Optional[str] = None,
        decision: Optional[str] = None,
        rejection_stage: Optional[str] = None,
    ) -> int:
        """Count decisions by time range with optional filters.
        
        Counts the number of recorded decisions within the specified time range,
        with optional filtering by symbol, decision outcome, and rejection stage.
        
        Feature: trading-pipeline-integration
        Requirements: 2.4 - THE System SHALL support querying decisions by time range,
                      symbol, decision outcome, and rejection stage
        
        Args:
            start_time: Start of time range (inclusive)
            end_time: End of time range (inclusive)
            symbol: Optional filter by trading symbol (e.g., "BTCUSDT")
            decision: Optional filter by decision outcome ("accepted", "rejected", "shadow")
            rejection_stage: Optional filter by rejection stage name
            
        Returns:
            Count of decisions matching the filters
            
        Raises:
            ValueError: If decision is not a valid value
            
        Example:
            >>> count = await recorder.count_by_time_range(
            ...     start_time=datetime(2024, 1, 1, tzinfo=timezone.utc),
            ...     end_time=datetime(2024, 1, 2, tzinfo=timezone.utc),
            ...     decision="accepted",
            ... )
        """
        # Validate decision filter if provided
        if decision is not None and decision not in ("accepted", "rejected", "shadow"):
            raise ValueError(
                f"decision must be 'accepted', 'rejected', or 'shadow', got '{decision}'"
            )
        
        # Ensure timestamps have timezone info
        if start_time.tzinfo is None:
            start_time = start_time.replace(tzinfo=timezone.utc)
        if end_time.tzinfo is None:
            end_time = end_time.replace(tzinfo=timezone.utc)
        
        # Build query with dynamic filters
        query_parts = [
            "SELECT COUNT(*) FROM recorded_decisions",
            "WHERE timestamp >= $1 AND timestamp <= $2",
        ]
        params: List[Any] = [start_time, end_time]
        param_idx = 3
        
        if symbol is not None:
            query_parts.append(f"AND symbol = ${param_idx}")
            params.append(symbol)
            param_idx += 1
        
        if decision is not None:
            query_parts.append(f"AND decision = ${param_idx}")
            params.append(decision)
            param_idx += 1
        
        if rejection_stage is not None:
            query_parts.append(f"AND rejection_stage = ${param_idx}")
            params.append(rejection_stage)
            param_idx += 1
        
        query = " ".join(query_parts)
        
        async with self._pool.acquire() as conn:
            result = await conn.fetchval(query, *params)
            return result or 0
    
    async def get_by_id(self, decision_id: str) -> Optional[RecordedDecision]:
        """Get a single decision by its ID.
        
        Retrieves a specific recorded decision by its unique identifier.
        
        Feature: trading-pipeline-integration
        Requirements: 2.4 - THE System SHALL support querying decisions by time range,
                      symbol, decision outcome, and rejection stage
        
        Args:
            decision_id: Unique identifier of the decision (e.g., "dec_abc123def456")
            
        Returns:
            RecordedDecision if found, None otherwise
            
        Example:
            >>> decision = await recorder.get_by_id("dec_abc123def456")
            >>> if decision:
            ...     print(f"Decision: {decision.decision}")
        """
        if not decision_id:
            return None
        
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM recorded_decisions WHERE decision_id = $1",
                decision_id
            )
            if row is None:
                return None
            return RecordedDecision.from_db_row(row)


def _normalize_signal(signal: Any) -> Optional[Dict[str, Any]]:
    """Convert StrategySignal-like objects into JSON-safe dicts."""
    if signal is None:
        return None
    if isinstance(signal, dict):
        return signal
    if hasattr(signal, "__dataclass_fields__"):
        return asdict(signal)
    if hasattr(signal, "__dict__"):
        return dict(signal.__dict__)
    return {"value": str(signal)}


def _json_safe(value: Any) -> Any:
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, Decimal):
        coerced = float(value)
        return coerced if math.isfinite(coerced) else None
    if isinstance(value, dict):
        return {key: _json_safe(val) for key, val in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(val) for val in value]
    if hasattr(value, "item"):
        try:
            return _json_safe(value.item())
        except Exception:
            return value
    return value


def _normalize_positions(positions: Any) -> List[Dict[str, Any]]:
    """Convert positions payloads into JSON-safe dicts."""
    if not isinstance(positions, list):
        return []
    normalized: List[Dict[str, Any]] = []
    for position in positions:
        if isinstance(position, dict):
            normalized.append(_json_safe(position))
            continue
        if hasattr(position, "to_dict"):
            normalized.append(_json_safe(position.to_dict()))
            continue
        if hasattr(position, "__dataclass_fields__"):
            normalized.append(_json_safe(asdict(position)))
            continue
        if hasattr(position, "__dict__"):
            normalized.append(_json_safe(dict(position.__dict__)))
            continue
        logger.warning("decision_recording_position_unserializable: %s", type(position))
    return normalized
