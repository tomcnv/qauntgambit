"""Warm start state for trading pipeline integration.

This module provides the WarmStartState dataclass and WarmStartLoader class
for initializing backtests from live state snapshots, enabling testing of
strategy changes from the current market position.

Feature: trading-pipeline-integration
Requirements: 3.1 - THE System SHALL support initializing a backtest with current
              live positions, account state, and recent decision history
Requirements: 3.2 - WHEN warm starting a backtest THEN the System SHALL load the
              most recent state snapshot from Redis
Requirements: 3.3 - THE System SHALL include open positions with entry prices,
              sizes, and timestamps in the warm start state
Requirements: 3.4 - WHEN warm starting THEN the System SHALL include recent candle
              history for AMT calculations
Requirements: 3.5 - THE System SHALL validate that warm start state is consistent
              (positions match account equity)
Requirements: 3.6 - IF warm start state is stale (>5 minutes old) THEN the System
              SHALL warn the user and require confirmation
Requirements: 8.1 - THE System SHALL support exporting live state to a format
              consumable by backtest
Requirements: 8.2 - WHEN exporting state THEN the System SHALL include positions,
              account state, recent decisions, and pipeline state
Requirements: 8.5 - THE System SHALL support point-in-time state snapshots for
              reproducible testing
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple, Union, TYPE_CHECKING

if TYPE_CHECKING:
    from quantgambit.integration.decision_recording import RecordedDecision

logger = logging.getLogger(__name__)


class ImportValidationStatus(Enum):
    """Status of state import validation."""
    SUCCESS = "success"
    FAILED = "failed"
    WARNING = "warning"


@dataclass
class StateImportResult:
    """Result of importing state with validation details.
    
    Feature: trading-pipeline-integration
    Requirements: 8.3 - State import validates consistency before applying
    Requirements: 8.4 - State import reports specific inconsistencies on validation failure
    
    Attributes:
        status: Overall validation status (success, failed, warning)
        state: The imported WarmStartState (None if validation failed)
        errors: List of critical validation errors that caused failure
        warnings: List of non-critical validation warnings
        applied: Whether the state was applied to Redis (if requested)
    
    Example:
        >>> result = await loader.import_state(json_str)
        >>> if result.status == ImportValidationStatus.SUCCESS:
        ...     print(f"Imported state with {len(result.state.positions)} positions")
        >>> else:
        ...     print(f"Import failed: {result.errors}")
    """
    status: ImportValidationStatus
    state: Optional["WarmStartState"] = None
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    applied: bool = False
    
    @property
    def is_valid(self) -> bool:
        """Check if import was successful (no critical errors)."""
        return self.status in (ImportValidationStatus.SUCCESS, ImportValidationStatus.WARNING)
    
    @property
    def has_warnings(self) -> bool:
        """Check if there are any warnings."""
        return len(self.warnings) > 0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "status": self.status.value,
            "is_valid": self.is_valid,
            "errors": self.errors,
            "warnings": self.warnings,
            "applied": self.applied,
            "state_summary": {
                "snapshot_time": self.state.snapshot_time.isoformat() if self.state else None,
                "position_count": len(self.state.positions) if self.state else 0,
                "has_account_state": bool(self.state.account_state) if self.state else False,
                "decision_count": len(self.state.recent_decisions) if self.state else 0,
            } if self.state else None,
        }


@dataclass
class WarmStartState:
    """State snapshot for warm starting a backtest.
    
    Represents a complete snapshot of the live trading system state that can
    be used to initialize a backtest from the current market position. This
    enables testing strategy changes without starting from scratch.
    
    Feature: trading-pipeline-integration
    Requirements: 3.5, 3.6
    
    Attributes:
        snapshot_time: When this snapshot was taken (must have timezone info)
        positions: List of open positions with entry_price, size, symbol, etc.
        account_state: Account state including equity, margin, balance, etc.
        recent_decisions: Recent trading decisions for context
        candle_history: Historical candles by symbol for AMT calculations
        pipeline_state: Pipeline state including cooldowns, hysteresis, etc.
    
    Example:
        >>> state = WarmStartState(
        ...     snapshot_time=datetime.now(timezone.utc),
        ...     positions=[{"symbol": "BTCUSDT", "size": 0.1, "entry_price": 50000}],
        ...     account_state={"equity": 10000, "margin": 500},
        ...     recent_decisions=[],
        ...     candle_history={"BTCUSDT": [{"open": 50000, "close": 50100}]},
        ...     pipeline_state={"cooldown_until": None},
        ... )
        >>> state.is_stale()  # Check if snapshot is too old
        False
        >>> valid, errors = state.validate()  # Validate consistency
        >>> valid
        True
    """
    
    # Core state
    snapshot_time: datetime
    positions: List[Dict[str, Any]] = field(default_factory=list)
    account_state: Dict[str, Any] = field(default_factory=dict)
    recent_decisions: List["RecordedDecision"] = field(default_factory=list)
    candle_history: Dict[str, List[Dict[str, Any]]] = field(default_factory=dict)
    pipeline_state: Dict[str, Any] = field(default_factory=dict)
    
    # Default staleness threshold (5 minutes = 300 seconds)
    DEFAULT_MAX_AGE_SEC: float = 300.0
    
    # Default position value to equity ratio limit (10x)
    DEFAULT_MAX_POSITION_EQUITY_RATIO: float = 10.0
    
    def __post_init__(self) -> None:
        """Validate and normalize the WarmStartState after initialization."""
        # Ensure snapshot_time has timezone info
        if self.snapshot_time.tzinfo is None:
            object.__setattr__(
                self,
                'snapshot_time',
                self.snapshot_time.replace(tzinfo=timezone.utc)
            )
    
    def is_stale(self, max_age_sec: float = DEFAULT_MAX_AGE_SEC) -> bool:
        """Check if snapshot is too old.
        
        A snapshot is considered stale if it was taken more than max_age_sec
        seconds ago. Stale snapshots may not accurately reflect the current
        market state and should be used with caution.
        
        Feature: trading-pipeline-integration
        Requirements: 3.6 - IF warm start state is stale (>5 minutes old) THEN
                      the System SHALL warn the user and require confirmation
        
        Args:
            max_age_sec: Maximum age in seconds before snapshot is considered
                        stale. Default is 300 seconds (5 minutes).
        
        Returns:
            True if the snapshot is older than max_age_sec, False otherwise.
        
        Example:
            >>> from datetime import timedelta
            >>> old_time = datetime.now(timezone.utc) - timedelta(minutes=10)
            >>> state = WarmStartState(snapshot_time=old_time, account_state={"equity": 1000})
            >>> state.is_stale()  # Default 5 minute threshold
            True
            >>> state.is_stale(max_age_sec=900)  # 15 minute threshold
            False
        """
        now = datetime.now(timezone.utc)
        
        # Ensure snapshot_time has timezone info for comparison
        snapshot_time = self.snapshot_time
        if snapshot_time.tzinfo is None:
            snapshot_time = snapshot_time.replace(tzinfo=timezone.utc)
        
        age = (now - snapshot_time).total_seconds()
        return age > max_age_sec
    
    def validate(self) -> Tuple[bool, List[str]]:
        """Validate state consistency.
        
        Performs consistency checks on the warm start state to ensure it
        represents a valid trading state. Checks include:
        
        1. Position value vs equity ratio: Total position value should not
           exceed 10x account equity (indicates potential data inconsistency)
        2. Required fields: Account state must include equity
        
        Feature: trading-pipeline-integration
        Requirements: 3.5 - THE System SHALL validate that warm start state is
                      consistent (positions match account equity)
        
        Returns:
            Tuple of (is_valid, error_messages) where:
            - is_valid: True if all validation checks pass
            - error_messages: List of error descriptions (empty if valid)
        
        Example:
            >>> # Valid state
            >>> state = WarmStartState(
            ...     snapshot_time=datetime.now(timezone.utc),
            ...     positions=[{"symbol": "BTCUSDT", "size": 0.1, "entry_price": 50000}],
            ...     account_state={"equity": 10000},
            ... )
            >>> valid, errors = state.validate()
            >>> valid
            True
            >>> errors
            []
            
            >>> # Invalid state - position value exceeds 10x equity
            >>> state = WarmStartState(
            ...     snapshot_time=datetime.now(timezone.utc),
            ...     positions=[{"symbol": "BTCUSDT", "size": 100, "entry_price": 50000}],
            ...     account_state={"equity": 1000},
            ... )
            >>> valid, errors = state.validate()
            >>> valid
            False
            >>> len(errors) > 0
            True
        """
        errors: List[str] = []
        
        # Check for required fields in account state
        equity = self.account_state.get("equity")
        if not equity:
            errors.append("Missing equity in account state")
        
        # Check positions match account (position value shouldn't exceed 10x equity)
        total_position_value = sum(
            abs(p.get("size", 0) * p.get("entry_price", 0))
            for p in self.positions
        )
        
        # Only check ratio if we have valid equity
        if equity and equity > 0:
            max_allowed_value = equity * self.DEFAULT_MAX_POSITION_EQUITY_RATIO
            if total_position_value > max_allowed_value:
                errors.append(
                    f"Position value {total_position_value} exceeds "
                    f"{self.DEFAULT_MAX_POSITION_EQUITY_RATIO}x equity {equity}"
                )
        
        return len(errors) == 0, errors
    
    def get_age_seconds(self) -> float:
        """Get the age of this snapshot in seconds.
        
        Returns:
            Age of the snapshot in seconds (always non-negative).
        """
        now = datetime.now(timezone.utc)
        
        # Ensure snapshot_time has timezone info for comparison
        snapshot_time = self.snapshot_time
        if snapshot_time.tzinfo is None:
            snapshot_time = snapshot_time.replace(tzinfo=timezone.utc)
        
        age = (now - snapshot_time).total_seconds()
        return max(0.0, age)
    
    def get_position_count(self) -> int:
        """Get the number of open positions.
        
        Returns:
            Number of positions in the snapshot.
        """
        return len(self.positions)
    
    def get_total_position_value(self) -> float:
        """Calculate total absolute position value.
        
        Returns:
            Sum of abs(size * entry_price) for all positions.
        """
        return sum(
            abs(p.get("size", 0) * p.get("entry_price", 0))
            for p in self.positions
        )
    
    def get_symbols_with_positions(self) -> List[str]:
        """Get list of symbols that have open positions.
        
        Returns:
            List of unique symbols with positions.
        """
        return list(set(
            p.get("symbol") for p in self.positions 
            if p.get("symbol")
        ))
    
    def has_candle_history_for_positions(self) -> bool:
        """Check if candle history exists for all position symbols.
        
        Returns:
            True if candle_history contains data for all symbols with positions.
        """
        position_symbols = self.get_symbols_with_positions()
        for symbol in position_symbols:
            if symbol not in self.candle_history or not self.candle_history[symbol]:
                return False
        return True
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization.
        
        Returns:
            Dictionary representation of the WarmStartState.
        """
        # Handle recent_decisions which may be RecordedDecision objects
        recent_decisions_data = []
        for decision in self.recent_decisions:
            if hasattr(decision, 'to_dict'):
                recent_decisions_data.append(decision.to_dict())
            elif isinstance(decision, dict):
                recent_decisions_data.append(decision)
            else:
                # Skip invalid entries
                pass
        
        # Handle candle_history with datetime serialization
        serialized_candle_history = {}
        for symbol, candles in self.candle_history.items():
            serialized_candles = []
            for candle in candles:
                serialized_candle = {}
                for key, value in candle.items():
                    if isinstance(value, datetime):
                        serialized_candle[key] = value.isoformat()
                    else:
                        serialized_candle[key] = value
                serialized_candles.append(serialized_candle)
            serialized_candle_history[symbol] = serialized_candles
        
        return {
            "snapshot_time": self.snapshot_time.isoformat(),
            "positions": self.positions,
            "account_state": self.account_state,
            "recent_decisions": recent_decisions_data,
            "candle_history": serialized_candle_history,
            "pipeline_state": self.pipeline_state,
        }
    
    def to_json(self) -> str:
        """Convert to JSON string for serialization.
        
        Creates a JSON-serializable representation of the WarmStartState
        that can be used for state export and synchronization.
        
        Feature: trading-pipeline-integration
        Requirements: 8.5 - State export format is JSON-serializable
        
        Returns:
            JSON string representation of the WarmStartState.
            
        Example:
            >>> state = WarmStartState(
            ...     snapshot_time=datetime.now(timezone.utc),
            ...     positions=[{"symbol": "BTCUSDT", "size": 0.1, "entry_price": 50000}],
            ...     account_state={"equity": 10000},
            ... )
            >>> json_str = state.to_json()
            >>> # Can be parsed back with json.loads() and from_dict()
        """
        return json.dumps(self.to_dict(), indent=2, default=str)
    
    @classmethod
    def from_json(cls, json_str: str) -> "WarmStartState":
        """Create WarmStartState from JSON string.
        
        Args:
            json_str: JSON string representation of WarmStartState.
            
        Returns:
            WarmStartState instance.
            
        Example:
            >>> json_str = '{"snapshot_time": "2024-01-15T12:00:00+00:00", ...}'
            >>> state = WarmStartState.from_json(json_str)
        """
        data = json.loads(json_str)
        return cls.from_dict(data)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WarmStartState":
        """Create WarmStartState from dictionary.
        
        Args:
            data: Dictionary with WarmStartState fields.
            
        Returns:
            WarmStartState instance.
        """
        # Import here to avoid circular imports
        from quantgambit.integration.decision_recording import RecordedDecision
        
        # Parse snapshot_time
        snapshot_time = data["snapshot_time"]
        if isinstance(snapshot_time, str):
            snapshot_time = datetime.fromisoformat(
                snapshot_time.replace('Z', '+00:00')
            )
        
        # Parse recent_decisions
        recent_decisions = []
        for decision_data in data.get("recent_decisions", []):
            if isinstance(decision_data, dict):
                recent_decisions.append(RecordedDecision.from_dict(decision_data))
            else:
                recent_decisions.append(decision_data)
        
        return cls(
            snapshot_time=snapshot_time,
            positions=data.get("positions", []),
            account_state=data.get("account_state", {}),
            recent_decisions=recent_decisions,
            candle_history=data.get("candle_history", {}),
            pipeline_state=data.get("pipeline_state", {}),
        )


class WarmStartLoader:
    """Loads live state for warm starting backtests.
    
    The WarmStartLoader retrieves the current live trading state from Redis
    and TimescaleDB to initialize a backtest from the current market position.
    This enables testing strategy changes without starting from scratch.
    
    Feature: trading-pipeline-integration
    Requirements: 3.1 - THE System SHALL support initializing a backtest with current
                  live positions, account state, and recent decision history
    Requirements: 3.2 - WHEN warm starting a backtest THEN the System SHALL load the
                  most recent state snapshot from Redis
    Requirements: 3.3 - THE System SHALL include open positions with entry prices,
                  sizes, and timestamps in the warm start state
    Requirements: 3.4 - WHEN warm starting THEN the System SHALL include recent candle
                  history for AMT calculations
    
    Attributes:
        _redis: Redis client for loading state snapshots
        _pool: TimescaleDB connection pool for loading historical data
        _tenant_id: Tenant identifier for multi-tenant support
        _bot_id: Bot identifier for the trading bot
    
    Example:
        >>> loader = WarmStartLoader(redis_client, timescale_pool, "tenant1", "bot1")
        >>> state = await loader.load_current_state()
        >>> if state.is_stale():
        ...     print("Warning: State is stale!")
        >>> valid, errors = state.validate()
        >>> if valid:
        ...     # Use state to initialize backtest
        ...     pass
    """
    
    # Default hours of decision history to load
    DEFAULT_DECISION_HISTORY_HOURS = 1
    
    # Default hours of candle history to load for AMT calculations
    DEFAULT_CANDLE_HISTORY_HOURS = 12
    
    # Default limit for recent decisions
    DEFAULT_DECISION_LIMIT = 1000
    
    # Default timeframe for candles (5 minutes = 300 seconds)
    DEFAULT_CANDLE_TIMEFRAME_SEC = 300
    
    def __init__(
        self,
        redis_client,
        timescale_pool,
        tenant_id: str,
        bot_id: str,
    ) -> None:
        """Initialize the WarmStartLoader.
        
        Args:
            redis_client: Redis client for loading state snapshots
            timescale_pool: TimescaleDB connection pool for loading historical data
            tenant_id: Tenant identifier for multi-tenant support
            bot_id: Bot identifier for the trading bot
        """
        self._redis = redis_client
        self._pool = timescale_pool
        self._tenant_id = tenant_id
        self._bot_id = bot_id
    
    @property
    def tenant_id(self) -> str:
        """Get the tenant ID."""
        return self._tenant_id
    
    @property
    def bot_id(self) -> str:
        """Get the bot ID."""
        return self._bot_id
    
    def _get_redis_key(self, key_type: str) -> str:
        """Generate a Redis key for the given key type.
        
        Args:
            key_type: Type of key (e.g., "positions", "account", "pipeline_state")
            
        Returns:
            Full Redis key string
        """
        # Map key types to actual Redis key patterns used by the bot
        # The bot uses ":latest" suffix for some keys
        key_suffix_map = {
            "positions": "positions:latest",
            "account": "account:latest",
            "pipeline_state": "pipeline_state",
            "warm_start": "warm_start:latest",
        }
        suffix = key_suffix_map.get(key_type, key_type)
        return f"quantgambit:{self._tenant_id}:{self._bot_id}:{suffix}"
    
    async def load_current_state(self) -> WarmStartState:
        """Load current live state from Redis and TimescaleDB.
        
        Loads the complete live trading state including positions, account state,
        recent decisions, candle history, and pipeline state. This state can be
        used to initialize a backtest from the current market position.
        
        Feature: trading-pipeline-integration
        Requirements: 3.1, 3.2, 3.3, 3.4
        
        Returns:
            WarmStartState containing the complete live state snapshot
            
        Example:
            >>> loader = WarmStartLoader(redis, pool, "tenant1", "bot1")
            >>> state = await loader.load_current_state()
            >>> print(f"Loaded {len(state.positions)} positions")
            >>> print(f"Account equity: {state.account_state.get('equity')}")
        """
        # Load positions from Redis snapshot.
        # Primary key uses ":latest", but accept legacy keys for older writers/tests.
        positions_key = self._get_redis_key("positions")
        positions_json = await self._redis.get(positions_key)
        if not positions_json:
            legacy_positions_key = f"quantgambit:{self._tenant_id}:{self._bot_id}:positions"
            positions_json = await self._redis.get(legacy_positions_key)
        positions_data = json.loads(positions_json) if positions_json else {}
        # Handle both wrapped {"positions": [...]} and direct [...] formats
        if isinstance(positions_data, dict):
            positions = positions_data.get("positions", [])
        elif isinstance(positions_data, list):
            positions = positions_data
        else:
            positions = []
        
        # Load account state from Redis (also accept legacy key without ":latest").
        account_key = self._get_redis_key("account")
        account_json = await self._redis.get(account_key)
        if not account_json:
            legacy_account_key = f"quantgambit:{self._tenant_id}:{self._bot_id}:account"
            account_json = await self._redis.get(legacy_account_key)
        account_data = json.loads(account_json) if account_json else {}
        # Handle both wrapped {"account_state": {...}} and direct {...} formats
        if isinstance(account_data, dict):
            # Check if it's wrapped
            if "account_state" in account_data:
                account_state = account_data.get("account_state", {})
            elif "equity" in account_data or "balance" in account_data:
                # Direct format with equity/balance
                account_state = account_data
            else:
                account_state = account_data
        else:
            account_state = {}
        
        # Load recent decisions from TimescaleDB
        recent_decisions = await self._load_recent_decisions(
            hours=self.DEFAULT_DECISION_HISTORY_HOURS
        )
        
        # Load candle history for AMT calculations
        # Get unique symbols from positions
        symbols = list(set(
            p.get("symbol") for p in positions if p.get("symbol")
        ))
        candle_history: Dict[str, List[Dict[str, Any]]] = {}
        for symbol in symbols:
            candle_history[symbol] = await self._load_candle_history(
                symbol, hours=self.DEFAULT_CANDLE_HISTORY_HOURS
            )
        
        # Load pipeline state (cooldowns, hysteresis). Accept legacy key without suffix.
        pipeline_key = self._get_redis_key("pipeline_state")
        pipeline_json = await self._redis.get(pipeline_key)
        if not pipeline_json:
            legacy_pipeline_key = f"quantgambit:{self._tenant_id}:{self._bot_id}:pipeline_state"
            pipeline_json = await self._redis.get(legacy_pipeline_key)
        pipeline_state = json.loads(pipeline_json) if pipeline_json else {}
        
        return WarmStartState(
            snapshot_time=datetime.now(timezone.utc),
            positions=positions,
            account_state=account_state,
            recent_decisions=recent_decisions,
            candle_history=candle_history,
            pipeline_state=pipeline_state,
        )
    
    async def _load_recent_decisions(
        self,
        hours: int = DEFAULT_DECISION_HISTORY_HOURS,
    ) -> List["RecordedDecision"]:
        """Load recent decisions from TimescaleDB.
        
        Retrieves recent trading decisions from the recorded_decisions table
        for context when warm starting a backtest.
        
        Feature: trading-pipeline-integration
        Requirements: 3.1 - THE System SHALL support initializing a backtest with
                      current live positions, account state, and recent decision history
        
        Args:
            hours: Number of hours of decision history to load (default: 1)
            
        Returns:
            List of RecordedDecision objects ordered by timestamp descending
            
        Example:
            >>> decisions = await loader._load_recent_decisions(hours=2)
            >>> print(f"Loaded {len(decisions)} recent decisions")
        """
        # Import here to avoid circular imports
        from quantgambit.integration.decision_recording import RecordedDecision
        
        try:
            async with self._pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT * FROM recorded_decisions
                    WHERE timestamp > NOW() - INTERVAL '1 hour' * $1
                    ORDER BY timestamp DESC
                    LIMIT $2
                    """,
                    hours,
                    self.DEFAULT_DECISION_LIMIT,
                )
                return [RecordedDecision.from_db_row(row) for row in rows]
        except Exception:
            # Table may not exist yet - return empty list
            return []
    
    async def _load_candle_history(
        self,
        symbol: str,
        hours: int = DEFAULT_CANDLE_HISTORY_HOURS,
    ) -> List[Dict[str, Any]]:
        """Load candle history for AMT calculations.
        
        Retrieves historical candle data from the market_candles table for
        calculating AMT (Average Market Trend) and other indicators.
        
        Feature: trading-pipeline-integration
        Requirements: 3.4 - WHEN warm starting THEN the System SHALL include recent
                      candle history for AMT calculations
        
        Args:
            symbol: Trading symbol (e.g., "BTCUSDT")
            hours: Number of hours of candle history to load (default: 12)
            
        Returns:
            List of candle dictionaries with ts, open, high, low, close, volume
            ordered by timestamp ascending
            
        Example:
            >>> candles = await loader._load_candle_history("BTCUSDT", hours=12)
            >>> print(f"Loaded {len(candles)} candles for BTCUSDT")
        """
        try:
            async with self._pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT ts, open, high, low, close, volume
                    FROM market_candles
                    WHERE symbol = $1 AND timeframe_sec = $2
                    AND ts > NOW() - INTERVAL '1 hour' * $3
                    ORDER BY ts ASC
                    """,
                    symbol,
                    self.DEFAULT_CANDLE_TIMEFRAME_SEC,
                    hours,
                )
                return [dict(row) for row in rows]
        except Exception:
            # Table may not exist yet - return empty list
            return []
    
    def _row_to_decision(self, row) -> "RecordedDecision":
        """Convert a database row to a RecordedDecision.
        
        This is a helper method that delegates to RecordedDecision.from_db_row.
        
        Args:
            row: Database row from asyncpg
            
        Returns:
            RecordedDecision instance
        """
        # Import here to avoid circular imports
        from quantgambit.integration.decision_recording import RecordedDecision
        return RecordedDecision.from_db_row(row)
    
    async def export_state(
        self,
        snapshot_time: Optional[datetime] = None,
        include_decisions: bool = True,
        include_candles: bool = True,
        decision_hours: int = DEFAULT_DECISION_HISTORY_HOURS,
        candle_hours: int = DEFAULT_CANDLE_HISTORY_HOURS,
    ) -> WarmStartState:
        """Export current live state to a serializable format.
        
        Creates a WarmStartState snapshot from the current live trading state
        that can be serialized to JSON for state synchronization, backup,
        or transfer to another system.
        
        Feature: trading-pipeline-integration
        Requirements: 8.1 - THE System SHALL support exporting live state to a format
                      consumable by backtest
        Requirements: 8.2 - WHEN exporting state THEN the System SHALL include positions,
                      account state, recent decisions, and pipeline state
        Requirements: 8.5 - THE System SHALL support point-in-time state snapshots for
                      reproducible testing
        
        Args:
            snapshot_time: Optional timestamp for the snapshot. If None, uses current
                          time. This allows creating point-in-time snapshots for
                          reproducible testing.
            include_decisions: Whether to include recent decisions (default: True)
            include_candles: Whether to include candle history (default: True)
            decision_hours: Hours of decision history to include (default: 1)
            candle_hours: Hours of candle history to include (default: 12)
            
        Returns:
            WarmStartState containing the exported state snapshot, ready for
            JSON serialization via to_json() or to_dict()
            
        Example:
            >>> loader = WarmStartLoader(redis, pool, "tenant1", "bot1")
            >>> # Export current state
            >>> state = await loader.export_state()
            >>> json_str = state.to_json()
            >>> 
            >>> # Export with custom snapshot time for reproducibility
            >>> from datetime import datetime, timezone
            >>> snapshot_time = datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
            >>> state = await loader.export_state(snapshot_time=snapshot_time)
            >>> 
            >>> # Export without decisions for smaller payload
            >>> state = await loader.export_state(include_decisions=False)
        """
        # Use provided snapshot_time or current time
        effective_snapshot_time = snapshot_time or datetime.now(timezone.utc)
        
        # Ensure snapshot_time has timezone info
        if effective_snapshot_time.tzinfo is None:
            effective_snapshot_time = effective_snapshot_time.replace(tzinfo=timezone.utc)
        
        # Load positions from Redis snapshot
        positions_key = self._get_redis_key("positions")
        positions_json = await self._redis.get(positions_key)
        if not positions_json:
            legacy_positions_key = f"quantgambit:{self._tenant_id}:{self._bot_id}:positions"
            positions_json = await self._redis.get(legacy_positions_key)
        positions_data = json.loads(positions_json) if positions_json else {}
        # Handle both wrapped {"positions": [...]} and direct [...] formats
        if isinstance(positions_data, dict):
            positions = positions_data.get("positions", [])
        elif isinstance(positions_data, list):
            positions = positions_data
        else:
            positions = []
        
        # Load account state from Redis
        account_key = self._get_redis_key("account")
        account_json = await self._redis.get(account_key)
        if not account_json:
            legacy_account_key = f"quantgambit:{self._tenant_id}:{self._bot_id}:account"
            account_json = await self._redis.get(legacy_account_key)
        account_data = json.loads(account_json) if account_json else {}
        # Handle both wrapped {"account_state": {...}} and direct {...} formats
        if isinstance(account_data, dict):
            if "account_state" in account_data:
                account_state = account_data.get("account_state", {})
            else:
                account_state = account_data
        else:
            account_state = {}
        
        # Load pipeline state (cooldowns, hysteresis)
        pipeline_key = self._get_redis_key("pipeline_state")
        pipeline_json = await self._redis.get(pipeline_key)
        if not pipeline_json:
            legacy_pipeline_key = f"quantgambit:{self._tenant_id}:{self._bot_id}:pipeline_state"
            pipeline_json = await self._redis.get(legacy_pipeline_key)
        pipeline_state = json.loads(pipeline_json) if pipeline_json else {}
        
        # Optionally load recent decisions from TimescaleDB
        recent_decisions: List["RecordedDecision"] = []
        if include_decisions:
            recent_decisions = await self._load_recent_decisions(hours=decision_hours)
        
        # Optionally load candle history for AMT calculations
        candle_history: Dict[str, List[Dict[str, Any]]] = {}
        if include_candles:
            # Get unique symbols from positions
            symbols = list(set(
                p.get("symbol") for p in positions if p.get("symbol")
            ))
            for symbol in symbols:
                candle_history[symbol] = await self._load_candle_history(
                    symbol, hours=candle_hours
                )
        
        return WarmStartState(
            snapshot_time=effective_snapshot_time,
            positions=positions,
            account_state=account_state,
            recent_decisions=recent_decisions,
            candle_history=candle_history,
            pipeline_state=pipeline_state,
        )
    
    async def export_state_json(
        self,
        snapshot_time: Optional[datetime] = None,
        include_decisions: bool = True,
        include_candles: bool = True,
        decision_hours: int = DEFAULT_DECISION_HISTORY_HOURS,
        candle_hours: int = DEFAULT_CANDLE_HISTORY_HOURS,
    ) -> str:
        """Export current live state directly to JSON string.
        
        Convenience method that combines export_state() and to_json() for
        direct JSON serialization.
        
        Feature: trading-pipeline-integration
        Requirements: 8.1, 8.2, 8.5
        
        Args:
            snapshot_time: Optional timestamp for the snapshot
            include_decisions: Whether to include recent decisions (default: True)
            include_candles: Whether to include candle history (default: True)
            decision_hours: Hours of decision history to include (default: 1)
            candle_hours: Hours of candle history to include (default: 12)
            
        Returns:
            JSON string representation of the exported state
            
        Example:
            >>> loader = WarmStartLoader(redis, pool, "tenant1", "bot1")
            >>> json_str = await loader.export_state_json()
            >>> # Save to file or send over network
            >>> with open("state_snapshot.json", "w") as f:
            ...     f.write(json_str)
        """
        state = await self.export_state(
            snapshot_time=snapshot_time,
            include_decisions=include_decisions,
            include_candles=include_candles,
            decision_hours=decision_hours,
            candle_hours=candle_hours,
        )
        return state.to_json()
    
    async def import_state(
        self,
        state_input: Union[str, Dict[str, Any], "WarmStartState"],
        apply_to_redis: bool = False,
        validate_against_live: bool = True,
    ) -> StateImportResult:
        """Import state from backtest final state or external source.
        
        Validates the imported state for consistency and optionally applies
        it to Redis for state synchronization. This enables importing backtest
        final state back to the live system for comparison or hybrid testing.
        
        Feature: trading-pipeline-integration
        Requirements: 8.3 - State import validates consistency before applying
        Requirements: 8.4 - State import reports specific inconsistencies on validation failure
        Requirements: 8.6 - State import supports importing backtest final state
        
        Args:
            state_input: The state to import. Can be:
                - JSON string from export_state_json() or backtest output
                - Dictionary from to_dict() or backtest result
                - WarmStartState object directly
            apply_to_redis: If True, apply the imported state to Redis after
                           successful validation. Default is False (validate only).
            validate_against_live: If True, compare imported state against current
                                  live state and report differences. Default is True.
        
        Returns:
            StateImportResult containing:
            - status: SUCCESS, FAILED, or WARNING
            - state: The parsed WarmStartState (None if parsing failed)
            - errors: List of critical validation errors
            - warnings: List of non-critical warnings
            - applied: Whether state was applied to Redis
        
        Example:
            >>> # Import from JSON string (e.g., backtest output)
            >>> result = await loader.import_state(json_str)
            >>> if result.is_valid:
            ...     print(f"Imported {len(result.state.positions)} positions")
            >>> else:
            ...     print(f"Validation failed: {result.errors}")
            
            >>> # Import and apply to Redis
            >>> result = await loader.import_state(json_str, apply_to_redis=True)
            >>> if result.applied:
            ...     print("State synchronized to Redis")
            
            >>> # Import WarmStartState directly
            >>> result = await loader.import_state(backtest_final_state)
        """
        errors: List[str] = []
        warnings: List[str] = []
        state: Optional[WarmStartState] = None
        
        # Step 1: Parse the input into a WarmStartState
        try:
            state = self._parse_state_input(state_input)
        except json.JSONDecodeError as e:
            errors.append(f"Invalid JSON format: {e}")
            return StateImportResult(
                status=ImportValidationStatus.FAILED,
                state=None,
                errors=errors,
                warnings=warnings,
                applied=False,
            )
        except KeyError as e:
            errors.append(f"Missing required field: {e}")
            return StateImportResult(
                status=ImportValidationStatus.FAILED,
                state=None,
                errors=errors,
                warnings=warnings,
                applied=False,
            )
        except Exception as e:
            errors.append(f"Failed to parse state: {type(e).__name__}: {e}")
            return StateImportResult(
                status=ImportValidationStatus.FAILED,
                state=None,
                errors=errors,
                warnings=warnings,
                applied=False,
            )
        
        # Step 2: Run basic validation on the parsed state
        basic_valid, basic_errors = state.validate()
        if not basic_valid:
            errors.extend(basic_errors)
        
        # Step 3: Run additional consistency checks
        consistency_errors, consistency_warnings = self._validate_state_consistency(state)
        errors.extend(consistency_errors)
        warnings.extend(consistency_warnings)
        
        # Step 4: Optionally validate against current live state
        if validate_against_live:
            live_warnings = await self._validate_against_live_state(state)
            warnings.extend(live_warnings)
        
        # Step 5: Check for staleness
        if state.is_stale():
            age_seconds = state.get_age_seconds()
            warnings.append(
                f"Imported state is stale (age: {age_seconds:.0f}s, "
                f"threshold: {WarmStartState.DEFAULT_MAX_AGE_SEC}s)"
            )
        
        # Determine final status
        if errors:
            status = ImportValidationStatus.FAILED
        elif warnings:
            status = ImportValidationStatus.WARNING
        else:
            status = ImportValidationStatus.SUCCESS
        
        # Step 6: Optionally apply to Redis if validation passed
        applied = False
        if apply_to_redis and status != ImportValidationStatus.FAILED:
            try:
                await self._apply_state_to_redis(state)
                applied = True
                logger.info(
                    f"Applied imported state to Redis: "
                    f"{len(state.positions)} positions, "
                    f"equity={state.account_state.get('equity')}"
                )
            except Exception as e:
                errors.append(f"Failed to apply state to Redis: {e}")
                status = ImportValidationStatus.FAILED
        
        return StateImportResult(
            status=status,
            state=state,
            errors=errors,
            warnings=warnings,
            applied=applied,
        )
    
    def _parse_state_input(
        self,
        state_input: Union[str, Dict[str, Any], "WarmStartState"],
    ) -> WarmStartState:
        """Parse state input into a WarmStartState object.
        
        Args:
            state_input: JSON string, dictionary, or WarmStartState
            
        Returns:
            WarmStartState object
            
        Raises:
            json.JSONDecodeError: If JSON string is invalid
            KeyError: If required fields are missing
        """
        if isinstance(state_input, WarmStartState):
            return state_input
        elif isinstance(state_input, str):
            return WarmStartState.from_json(state_input)
        elif isinstance(state_input, dict):
            return WarmStartState.from_dict(state_input)
        else:
            raise TypeError(
                f"state_input must be str, dict, or WarmStartState, "
                f"got {type(state_input).__name__}"
            )
    
    def _validate_state_consistency(
        self,
        state: WarmStartState,
    ) -> Tuple[List[str], List[str]]:
        """Validate additional state consistency beyond basic validation.
        
        Feature: trading-pipeline-integration
        Requirements: 8.3 - State import validates consistency before applying
        Requirements: 8.4 - State import reports specific inconsistencies on validation failure
        
        Args:
            state: The WarmStartState to validate
            
        Returns:
            Tuple of (errors, warnings)
        """
        errors: List[str] = []
        warnings: List[str] = []
        
        # Check position data completeness
        for i, position in enumerate(state.positions):
            if not position.get("symbol"):
                errors.append(f"Position {i}: missing 'symbol' field")
            if "size" not in position:
                errors.append(f"Position {i}: missing 'size' field")
            elif position.get("size") == 0:
                warnings.append(f"Position {i} ({position.get('symbol', 'unknown')}): size is zero")
            if "entry_price" not in position:
                warnings.append(f"Position {i} ({position.get('symbol', 'unknown')}): missing 'entry_price'")
            elif position.get("entry_price", 0) <= 0:
                warnings.append(
                    f"Position {i} ({position.get('symbol', 'unknown')}): "
                    f"invalid entry_price {position.get('entry_price')}"
                )
        
        # Check account state completeness
        if not state.account_state:
            errors.append("Account state is empty")
        else:
            equity = state.account_state.get("equity")
            if equity is None:
                errors.append("Account state missing 'equity' field")
            elif equity <= 0:
                errors.append(f"Account equity must be positive, got {equity}")
            
            # Check for negative balance (warning, not error)
            balance = state.account_state.get("balance")
            if balance is not None and balance < 0:
                warnings.append(f"Account balance is negative: {balance}")
            
            # Check margin usage
            margin = state.account_state.get("margin", 0)
            if equity and margin > equity:
                warnings.append(
                    f"Margin ({margin}) exceeds equity ({equity}), "
                    f"margin ratio: {margin/equity:.1%}"
                )
        
        # Check candle history for position symbols
        if state.positions and not state.has_candle_history_for_positions():
            missing_symbols = [
                p.get("symbol") for p in state.positions
                if p.get("symbol") and p.get("symbol") not in state.candle_history
            ]
            if missing_symbols:
                warnings.append(
                    f"Missing candle history for position symbols: {missing_symbols}"
                )
        
        # Check pipeline state for expected fields
        if state.pipeline_state:
            # These are optional but commonly expected
            expected_fields = ["cooldown_until", "hysteresis"]
            for field in expected_fields:
                if field not in state.pipeline_state:
                    # This is just informational, not a warning
                    pass
        
        return errors, warnings
    
    async def _validate_against_live_state(
        self,
        imported_state: WarmStartState,
    ) -> List[str]:
        """Compare imported state against current live state.
        
        Feature: trading-pipeline-integration
        Requirements: 8.4 - State import reports specific inconsistencies on validation failure
        
        Args:
            imported_state: The state being imported
            
        Returns:
            List of warning messages about differences from live state
        """
        warnings: List[str] = []
        
        try:
            # Load current live positions
            positions_key = self._get_redis_key("positions")
            positions_json = await self._redis.get(positions_key)
            live_positions = json.loads(positions_json) if positions_json else []
            
            # Load current live account state
            account_key = self._get_redis_key("account")
            account_json = await self._redis.get(account_key)
            live_account = json.loads(account_json) if account_json else {}
            
            # Compare position counts
            if len(imported_state.positions) != len(live_positions):
                warnings.append(
                    f"Position count differs: imported={len(imported_state.positions)}, "
                    f"live={len(live_positions)}"
                )
            
            # Compare position symbols
            imported_symbols = set(
                p.get("symbol") for p in imported_state.positions if p.get("symbol")
            )
            live_symbols = set(
                p.get("symbol") for p in live_positions if p.get("symbol")
            )
            
            new_symbols = imported_symbols - live_symbols
            removed_symbols = live_symbols - imported_symbols
            
            if new_symbols:
                warnings.append(f"New position symbols not in live: {new_symbols}")
            if removed_symbols:
                warnings.append(f"Live position symbols not in import: {removed_symbols}")
            
            # Compare equity
            imported_equity = imported_state.account_state.get("equity", 0)
            live_equity = live_account.get("equity", 0)
            
            if live_equity > 0 and imported_equity > 0:
                equity_diff_pct = abs(imported_equity - live_equity) / live_equity * 100
                if equity_diff_pct > 10:  # More than 10% difference
                    warnings.append(
                        f"Equity differs significantly: imported={imported_equity}, "
                        f"live={live_equity} ({equity_diff_pct:.1f}% difference)"
                    )
            
        except Exception as e:
            # Don't fail import if we can't compare to live state
            logger.warning(f"Could not validate against live state: {e}")
            warnings.append(f"Could not compare to live state: {e}")
        
        return warnings
    
    async def _apply_state_to_redis(self, state: WarmStartState) -> None:
        """Apply imported state to Redis.
        
        Args:
            state: The WarmStartState to apply
            
        Raises:
            Exception: If Redis operations fail
        """
        # Apply positions
        positions_key = self._get_redis_key("positions")
        await self._redis.set(positions_key, json.dumps(state.positions))
        
        # Apply account state
        account_key = self._get_redis_key("account")
        await self._redis.set(account_key, json.dumps(state.account_state))
        
        # Apply pipeline state
        pipeline_key = self._get_redis_key("pipeline_state")
        await self._redis.set(pipeline_key, json.dumps(state.pipeline_state))
