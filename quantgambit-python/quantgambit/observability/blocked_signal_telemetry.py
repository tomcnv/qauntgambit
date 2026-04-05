"""Blocked Signal Telemetry - Tracks signals blocked by various gates.

This module provides telemetry for tracking and aggregating blocked signals
across different gates (execution_throttle, cooldown, hysteresis, fee_check, hourly_limit,
confidence_gate, strategy_trend_mismatch, fee_trap, session_mismatch).

Requirements: 6.1, 6.2, 6.5, 9.1, 9.2, 9.3, 9.4
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, asdict, field
from typing import Any, Dict, List, Optional, TYPE_CHECKING
from collections import defaultdict

from quantgambit.observability.logger import log_info

if TYPE_CHECKING:
    from quantgambit.observability.telemetry import TelemetryPipeline, TelemetryContext


# Valid gate names for blocked signals
VALID_GATES = frozenset({
    "execution_throttle",
    "cooldown",
    "hysteresis",
    "fee_check",
    "hourly_limit",
    "confidence_gate",
    "strategy_trend_mismatch",
    "fee_trap",
    "session_mismatch",
    "ev_gate",
})

# Retention period for blocked signal records (7 days in seconds)
BLOCKED_SIGNAL_RETENTION_SECONDS = 7 * 24 * 60 * 60


@dataclass
class BlockedSignalEvent:
    """Event emitted when a signal is blocked by a gate.
    
    Attributes:
        timestamp: Unix timestamp when the signal was blocked
        symbol: Trading symbol (e.g., BTCUSDT)
        gate_name: Name of the gate that blocked the signal
        reason: Human-readable reason for blocking
        metrics: Additional metrics about the blocking decision
    """
    timestamp: float
    symbol: str
    gate_name: str
    reason: str
    metrics: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return asdict(self)


@dataclass
class BlockedSignalRecord:
    """Extended record for blocked signals with full context for forensics.
    
    This dataclass captures all required fields for the blocked_signals table
    as specified in Requirements 6.1 and 6.2.
    
    Attributes:
        id: Unique identifier (UUID)
        timestamp: Unix timestamp when the signal was blocked
        symbol: Trading symbol (e.g., BTCUSDT)
        direction: Signal direction ("long" or "short")
        strategy_id: ID of the strategy that generated the signal
        confidence: Model confidence (0.0 to 1.0)
        rejection_reason: Reason for rejection (e.g., "low_confidence", "fee_trap")
        rejection_stage: Name of the stage that rejected the signal
        profile_id: Market profile ID at rejection time
        snapshot_metrics: Full market context at rejection time
        
        # Fee trap specific fields
        expected_edge_usd: Expected profit in USD (for fee_trap rejections)
        round_trip_fee_usd: Round-trip fees in USD (for fee_trap rejections)
        
        # Strategy-trend specific fields
        trend: Market trend at rejection time (for strategy_trend_mismatch)
        signal_side: Signal side that was rejected (for strategy_trend_mismatch)
        
        # Session specific fields
        session: Trading session at rejection time (for session_mismatch)
        utc_hour: UTC hour at rejection time (for session_mismatch)
    
    Requirements: 6.1, 6.2
    """
    id: str
    timestamp: float
    symbol: str
    direction: str
    strategy_id: str
    confidence: float
    rejection_reason: str
    rejection_stage: str
    profile_id: str
    snapshot_metrics: Dict[str, Any]
    
    # Fee trap specific (optional)
    expected_edge_usd: Optional[float] = None
    round_trip_fee_usd: Optional[float] = None
    
    # Strategy-trend specific (optional)
    trend: Optional[str] = None
    signal_side: Optional[str] = None
    
    # Session specific (optional)
    session: Optional[str] = None
    utc_hour: Optional[int] = None
    
    @classmethod
    def create(
        cls,
        symbol: str,
        direction: str,
        strategy_id: str,
        confidence: float,
        rejection_reason: str,
        rejection_stage: str,
        profile_id: str,
        snapshot_metrics: Optional[Dict[str, Any]] = None,
        **kwargs,
    ) -> "BlockedSignalRecord":
        """Factory method to create a BlockedSignalRecord with auto-generated ID and timestamp.
        
        Args:
            symbol: Trading symbol
            direction: Signal direction ("long" or "short")
            strategy_id: Strategy that generated the signal
            confidence: Model confidence
            rejection_reason: Reason for rejection
            rejection_stage: Stage that rejected the signal
            profile_id: Market profile ID
            snapshot_metrics: Market context snapshot
            **kwargs: Optional fields (expected_edge_usd, round_trip_fee_usd, trend, etc.)
        
        Returns:
            BlockedSignalRecord with generated ID and current timestamp
        """
        return cls(
            id=str(uuid.uuid4()),
            timestamp=time.time(),
            symbol=symbol,
            direction=direction,
            strategy_id=strategy_id,
            confidence=confidence,
            rejection_reason=rejection_reason,
            rejection_stage=rejection_stage,
            profile_id=profile_id,
            snapshot_metrics=snapshot_metrics or {},
            expected_edge_usd=kwargs.get("expected_edge_usd"),
            round_trip_fee_usd=kwargs.get("round_trip_fee_usd"),
            trend=kwargs.get("trend"),
            signal_side=kwargs.get("signal_side"),
            session=kwargs.get("session"),
            utc_hour=kwargs.get("utc_hour"),
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization/persistence."""
        return asdict(self)
    
    def is_expired(self, retention_seconds: float = BLOCKED_SIGNAL_RETENTION_SECONDS) -> bool:
        """Check if this record has exceeded the retention period.
        
        Args:
            retention_seconds: Retention period in seconds (default: 7 days)
        
        Returns:
            True if record is older than retention period
        """
        return (time.time() - self.timestamp) > retention_seconds


class BlockedSignalRepository:
    """Repository for persisting blocked signal records to database.
    
    This class handles:
    1. Writing blocked signal records to the blocked_signals table
    2. Querying blocked signals by various criteria
    3. Automatic cleanup of records older than retention period (7 days)
    
    Requirements: 6.1, 6.5
    """
    
    def __init__(
        self,
        connection_string: Optional[str] = None,
        retention_seconds: float = BLOCKED_SIGNAL_RETENTION_SECONDS,
    ):
        """Initialize BlockedSignalRepository.
        
        Args:
            connection_string: Database connection string. If None, uses in-memory storage.
            retention_seconds: How long to retain records (default: 7 days)
        """
        self._connection_string = connection_string
        self._retention_seconds = retention_seconds
        
        # In-memory storage for when database is unavailable
        self._in_memory_records: List[BlockedSignalRecord] = []
        self._use_database = connection_string is not None
    
    async def persist(self, record: BlockedSignalRecord) -> bool:
        """Persist a blocked signal record.
        
        Args:
            record: The BlockedSignalRecord to persist
        
        Returns:
            True if persistence succeeded, False otherwise
        
        Requirements: 6.1
        """
        if self._use_database:
            return await self._persist_to_database(record)
        else:
            return self._persist_to_memory(record)
    
    async def _persist_to_database(self, record: BlockedSignalRecord) -> bool:
        """Persist record to PostgreSQL database.
        
        Args:
            record: The BlockedSignalRecord to persist
        
        Returns:
            True if persistence succeeded
        """
        try:
            import asyncpg
            import json
            
            conn = await asyncpg.connect(self._connection_string)
            try:
                query = """
                    INSERT INTO blocked_signals (
                        id, timestamp, symbol, direction, strategy_id, confidence,
                        rejection_reason, rejection_stage, profile_id, snapshot_metrics,
                        expected_edge_usd, round_trip_fee_usd, trend, signal_side,
                        session, utc_hour
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16)
                """
                
                await conn.execute(
                    query,
                    record.id,
                    record.timestamp,
                    record.symbol,
                    record.direction,
                    record.strategy_id,
                    record.confidence,
                    record.rejection_reason,
                    record.rejection_stage,
                    record.profile_id,
                    json.dumps(record.snapshot_metrics),
                    record.expected_edge_usd,
                    record.round_trip_fee_usd,
                    record.trend,
                    record.signal_side,
                    record.session,
                    record.utc_hour,
                )
                
                log_info(
                    "blocked_signal_persisted",
                    record_id=record.id,
                    symbol=record.symbol,
                    rejection_reason=record.rejection_reason,
                )
                return True
                
            finally:
                await conn.close()
                
        except Exception as e:
            log_info(
                "blocked_signal_persist_failed",
                error=str(e),
                record_id=record.id,
            )
            # Fall back to in-memory storage
            self._persist_to_memory(record)
            return False
    
    def _persist_to_memory(self, record: BlockedSignalRecord) -> bool:
        """Persist record to in-memory storage.
        
        Args:
            record: The BlockedSignalRecord to persist
        
        Returns:
            True (always succeeds)
        """
        self._in_memory_records.append(record)
        self._cleanup_expired_records()
        return True
    
    def _cleanup_expired_records(self) -> None:
        """Remove expired records from in-memory storage.
        
        Requirements: 6.5 (7-day retention)
        """
        self._in_memory_records = [
            r for r in self._in_memory_records
            if not r.is_expired(self._retention_seconds)
        ]
    
    async def get_by_reason(
        self,
        rejection_reason: str,
        limit: int = 100,
    ) -> List[BlockedSignalRecord]:
        """Get blocked signals by rejection reason.
        
        Args:
            rejection_reason: The rejection reason to filter by
            limit: Maximum number of records to return
        
        Returns:
            List of BlockedSignalRecord matching the criteria
        """
        if self._use_database:
            return await self._query_database_by_reason(rejection_reason, limit)
        else:
            return self._query_memory_by_reason(rejection_reason, limit)
    
    async def _query_database_by_reason(
        self,
        rejection_reason: str,
        limit: int,
    ) -> List[BlockedSignalRecord]:
        """Query database for records by rejection reason."""
        try:
            import asyncpg
            import json
            
            conn = await asyncpg.connect(self._connection_string)
            try:
                cutoff_time = time.time() - self._retention_seconds
                query = """
                    SELECT * FROM blocked_signals
                    WHERE rejection_reason = $1 AND timestamp > $2
                    ORDER BY timestamp DESC
                    LIMIT $3
                """
                
                rows = await conn.fetch(query, rejection_reason, cutoff_time, limit)
                return [self._row_to_record(row) for row in rows]
                
            finally:
                await conn.close()
                
        except Exception as e:
            log_info("blocked_signal_query_failed", error=str(e))
            return self._query_memory_by_reason(rejection_reason, limit)
    
    def _query_memory_by_reason(
        self,
        rejection_reason: str,
        limit: int,
    ) -> List[BlockedSignalRecord]:
        """Query in-memory storage for records by rejection reason."""
        self._cleanup_expired_records()
        matching = [
            r for r in self._in_memory_records
            if r.rejection_reason == rejection_reason
        ]
        # Sort by timestamp descending
        matching.sort(key=lambda r: r.timestamp, reverse=True)
        return matching[:limit]
    
    async def get_counts_by_reason(self) -> Dict[str, int]:
        """Get counts of blocked signals grouped by rejection reason.
        
        Returns:
            Dict mapping rejection_reason -> count
        """
        if self._use_database:
            return await self._get_database_counts_by_reason()
        else:
            return self._get_memory_counts_by_reason()
    
    async def _get_database_counts_by_reason(self) -> Dict[str, int]:
        """Get counts from database grouped by rejection reason."""
        try:
            import asyncpg
            
            conn = await asyncpg.connect(self._connection_string)
            try:
                cutoff_time = time.time() - self._retention_seconds
                query = """
                    SELECT rejection_reason, COUNT(*) as count
                    FROM blocked_signals
                    WHERE timestamp > $1
                    GROUP BY rejection_reason
                """
                
                rows = await conn.fetch(query, cutoff_time)
                return {row["rejection_reason"]: row["count"] for row in rows}
                
            finally:
                await conn.close()
                
        except Exception as e:
            log_info("blocked_signal_count_query_failed", error=str(e))
            return self._get_memory_counts_by_reason()
    
    def _get_memory_counts_by_reason(self) -> Dict[str, int]:
        """Get counts from in-memory storage grouped by rejection reason."""
        self._cleanup_expired_records()
        counts: Dict[str, int] = defaultdict(int)
        for record in self._in_memory_records:
            counts[record.rejection_reason] += 1
        return dict(counts)
    
    async def cleanup_expired(self) -> int:
        """Remove expired records from storage.
        
        Returns:
            Number of records removed
        
        Requirements: 6.5 (7-day retention)
        """
        if self._use_database:
            return await self._cleanup_database_expired()
        else:
            return self._cleanup_memory_expired()
    
    async def _cleanup_database_expired(self) -> int:
        """Remove expired records from database."""
        try:
            import asyncpg
            
            conn = await asyncpg.connect(self._connection_string)
            try:
                cutoff_time = time.time() - self._retention_seconds
                query = """
                    DELETE FROM blocked_signals
                    WHERE timestamp < $1
                """
                
                result = await conn.execute(query, cutoff_time)
                # Parse "DELETE N" result
                count = int(result.split()[-1]) if result else 0
                
                log_info("blocked_signals_cleanup", records_removed=count)
                return count
                
            finally:
                await conn.close()
                
        except Exception as e:
            log_info("blocked_signals_cleanup_failed", error=str(e))
            return 0
    
    def _cleanup_memory_expired(self) -> int:
        """Remove expired records from in-memory storage."""
        before_count = len(self._in_memory_records)
        self._cleanup_expired_records()
        removed = before_count - len(self._in_memory_records)
        return removed
    
    def _row_to_record(self, row: Any) -> BlockedSignalRecord:
        """Convert a database row to a BlockedSignalRecord.
        
        Args:
            row: Database row (asyncpg Record)
        
        Returns:
            BlockedSignalRecord instance
        """
        import json
        
        snapshot_metrics = row["snapshot_metrics"]
        if isinstance(snapshot_metrics, str):
            snapshot_metrics = json.loads(snapshot_metrics)
        
        return BlockedSignalRecord(
            id=row["id"],
            timestamp=row["timestamp"],
            symbol=row["symbol"],
            direction=row["direction"],
            strategy_id=row["strategy_id"],
            confidence=row["confidence"],
            rejection_reason=row["rejection_reason"],
            rejection_stage=row["rejection_stage"],
            profile_id=row["profile_id"],
            snapshot_metrics=snapshot_metrics,
            expected_edge_usd=row.get("expected_edge_usd"),
            round_trip_fee_usd=row.get("round_trip_fee_usd"),
            trend=row.get("trend"),
            signal_side=row.get("signal_side"),
            session=row.get("session"),
            utc_hour=row.get("utc_hour"),
        )
    
    def get_in_memory_records(self) -> List[BlockedSignalRecord]:
        """Get all in-memory records (for testing/debugging).
        
        Returns:
            List of all in-memory BlockedSignalRecord instances
        """
        self._cleanup_expired_records()
        return list(self._in_memory_records)


class BlockedSignalTelemetry:
    """Tracks and aggregates blocked signal metrics.
    
    This class provides:
    1. Recording of individual blocked signal events
    2. Hourly aggregation of blocked signals by gate and symbol
    3. Integration with the telemetry pipeline for persistence
    4. Database persistence via BlockedSignalRepository
    
    Requirements:
    - 6.1: Write records to blocked_signals table
    - 6.2: Include all required fields in blocked signal records
    - 6.5: 7-day retention for blocked signal records
    - 9.1: Emit telemetry for each signal blocked by execution throttle
    - 9.2: Emit telemetry for each signal blocked by cooldown/hysteresis
    - 9.3: Emit telemetry for each exit blocked by fee check
    - 9.4: Aggregate blocked signal counts per gate per hour
    """
    
    def __init__(
        self,
        telemetry: Optional["TelemetryPipeline"] = None,
        telemetry_context: Optional["TelemetryContext"] = None,
        repository: Optional[BlockedSignalRepository] = None,
    ):
        """Initialize BlockedSignalTelemetry.
        
        Args:
            telemetry: Optional telemetry pipeline for publishing events
            telemetry_context: Optional context for telemetry (tenant_id, bot_id)
            repository: Optional repository for database persistence
        """
        self._telemetry = telemetry
        self._telemetry_context = telemetry_context
        self._repository = repository
        
        # Hourly counts: gate_name -> symbol -> count
        self._hourly_counts: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
        
        # Track the current hour for reset logic
        self._current_hour: int = self._get_current_hour()
        
        # Total counts since last reset (for quick access)
        self._total_counts: Dict[str, int] = defaultdict(int)
    
    @staticmethod
    def _get_current_hour() -> int:
        """Get current hour as integer (0-23)."""
        return int(time.time() // 3600)
    
    def _maybe_reset_hourly_counts(self) -> None:
        """Reset hourly counts if we've crossed an hour boundary."""
        current_hour = self._get_current_hour()
        if current_hour != self._current_hour:
            self._hourly_counts.clear()
            self._total_counts.clear()
            self._current_hour = current_hour
    
    async def record_blocked(
        self,
        symbol: str,
        gate_name: str,
        reason: str,
        metrics: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Record a blocked signal event.
        
        Args:
            symbol: Trading symbol (e.g., BTCUSDT)
            gate_name: Name of the gate that blocked the signal
                       Must be one of: execution_throttle, cooldown, hysteresis, fee_check, hourly_limit
            reason: Human-readable reason for blocking
            metrics: Optional additional metrics about the blocking decision
        
        Requirements: 9.1, 9.2, 9.3
        """
        # Validate gate name
        if gate_name not in VALID_GATES:
            log_info(
                "blocked_signal_invalid_gate",
                gate_name=gate_name,
                valid_gates=list(VALID_GATES),
            )
            return
        
        # Check for hour boundary reset
        self._maybe_reset_hourly_counts()
        
        # Create event
        event = BlockedSignalEvent(
            timestamp=time.time(),
            symbol=symbol,
            gate_name=gate_name,
            reason=reason,
            metrics=metrics or {},
        )
        
        # Increment hourly counter (Requirement 9.4)
        self._hourly_counts[gate_name][symbol] += 1
        self._total_counts[gate_name] += 1
        
        # Emit to telemetry pipeline if available
        if self._telemetry and self._telemetry_context:
            await self._telemetry.publish_guardrail(
                ctx=self._telemetry_context,
                payload={
                    "type": "signal_blocked",
                    "symbol": symbol,
                    "gate_name": gate_name,
                    "reason": reason,
                    "metrics": metrics or {},
                    "hourly_count": self._hourly_counts[gate_name][symbol],
                    "total_gate_count": self._total_counts[gate_name],
                },
            )
        
        # Log for debugging
        log_info(
            "signal_blocked",
            symbol=symbol,
            gate_name=gate_name,
            reason=reason,
            hourly_count=self._hourly_counts[gate_name][symbol],
        )
    
    async def record_blocked_signal(
        self,
        record: BlockedSignalRecord,
    ) -> bool:
        """Record a full blocked signal record with database persistence.
        
        This method records a BlockedSignalRecord which includes all required
        fields for forensics analysis (Requirements 6.1, 6.2).
        
        Args:
            record: The BlockedSignalRecord to persist
        
        Returns:
            True if persistence succeeded, False otherwise
        
        Requirements: 6.1, 6.2
        """
        # Also record as a simple event for hourly aggregation
        await self.record_blocked(
            symbol=record.symbol,
            gate_name=record.rejection_reason,
            reason=f"{record.rejection_reason}: {record.rejection_stage}",
            metrics=record.snapshot_metrics,
        )
        
        # Persist to database if repository is available
        if self._repository:
            return await self._repository.persist(record)
        
        return True
    
    def get_hourly_summary(self) -> Dict[str, Dict[str, int]]:
        """Get hourly blocked signal counts by gate and symbol.
        
        Returns:
            Dict mapping gate_name -> symbol -> count
            
        Requirement: 9.4
        """
        self._maybe_reset_hourly_counts()
        # Return a copy to prevent external modification
        return {
            gate: dict(symbols)
            for gate, symbols in self._hourly_counts.items()
        }
    
    def get_total_counts(self) -> Dict[str, int]:
        """Get total blocked signal counts by gate for current hour.
        
        Returns:
            Dict mapping gate_name -> total_count
        """
        self._maybe_reset_hourly_counts()
        return dict(self._total_counts)
    
    def get_count_for_gate(self, gate_name: str) -> int:
        """Get total blocked count for a specific gate in current hour.
        
        Args:
            gate_name: Name of the gate
            
        Returns:
            Total count of blocked signals for this gate
        """
        self._maybe_reset_hourly_counts()
        return self._total_counts.get(gate_name, 0)
    
    def get_count_for_symbol(self, symbol: str, gate_name: Optional[str] = None) -> int:
        """Get blocked count for a specific symbol.
        
        Args:
            symbol: Trading symbol
            gate_name: Optional gate name to filter by
            
        Returns:
            Count of blocked signals for this symbol (optionally filtered by gate)
        """
        self._maybe_reset_hourly_counts()
        
        if gate_name:
            return self._hourly_counts.get(gate_name, {}).get(symbol, 0)
        
        # Sum across all gates
        total = 0
        for gate_counts in self._hourly_counts.values():
            total += gate_counts.get(symbol, 0)
        return total
    
    def reset_hourly_counts(self) -> None:
        """Manually reset hourly counters.
        
        This is typically called on hour boundary, but can be called
        manually for testing or administrative purposes.
        """
        self._hourly_counts.clear()
        self._total_counts.clear()
        self._current_hour = self._get_current_hour()
