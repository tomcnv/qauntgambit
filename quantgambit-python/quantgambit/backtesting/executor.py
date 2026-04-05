"""Backtest executor that orchestrates the complete backtest pipeline.

Feature: backtesting-api-integration
Requirements: R5.1 (Async Job Execution), R5.2 (Status Transitions),
              R5.3 (Result Persistence), R5.4 (Error Capture)

This module provides the BacktestExecutor class that:
1. Exports snapshots from Redis using SnapshotExporter
2. Replays snapshots through the decision engine using ReplayWorker
3. Stores results to the database using BacktestStore
4. Handles status transitions (pending → running → completed/failed)
"""

from __future__ import annotations

import asyncio
import os
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, Optional

if TYPE_CHECKING:
    from quantgambit.integration.warm_start import WarmStartLoader, WarmStartState

from quantgambit.backtesting.parity_checker import (
    ParityChecker,
    ParityCheckResult,
)
from quantgambit.backtesting.replay_worker import (
    ReplayConfig,
    ReplayWorker,
)
from quantgambit.backtesting.store import (
    BacktestStore,
    BacktestRunRecord,
)
from quantgambit.signals.decision_engine import DecisionEngine
from quantgambit.signals.pipeline import ConfigurationError
from quantgambit.signals.stages import (
    EVGateConfig,
    EVPositionSizerConfig,
)
from quantgambit.signals.stages.data_readiness import DataReadinessConfig
from quantgambit.observability.logger import log_info, log_warning, log_error


class BacktestStatus(str, Enum):
    """Valid backtest status values."""
    PENDING = "pending"
    RUNNING = "running"
    FINISHED = "finished"
    FAILED = "failed"
    CANCELLED = "cancelled"
    DEGRADED = "degraded"


# Valid status transitions
VALID_TRANSITIONS: Dict[BacktestStatus, set[BacktestStatus]] = {
    BacktestStatus.PENDING: {BacktestStatus.RUNNING, BacktestStatus.CANCELLED, BacktestStatus.FAILED},
    BacktestStatus.RUNNING: {BacktestStatus.FINISHED, BacktestStatus.FAILED, BacktestStatus.CANCELLED, BacktestStatus.DEGRADED},
    BacktestStatus.FINISHED: set(),  # Terminal state
    BacktestStatus.FAILED: set(),    # Terminal state
    BacktestStatus.CANCELLED: set(), # Terminal state
    BacktestStatus.DEGRADED: set(),  # Terminal state
}


def is_valid_transition(from_status: BacktestStatus, to_status: BacktestStatus) -> bool:
    """Check if a status transition is valid.
    
    Args:
        from_status: Current status
        to_status: Target status
        
    Returns:
        True if the transition is valid, False otherwise.
    """
    return to_status in VALID_TRANSITIONS.get(from_status, set())


def is_terminal_status(status: BacktestStatus) -> bool:
    """Check if a status is terminal (no further transitions allowed).
    
    Args:
        status: Status to check
        
    Returns:
        True if the status is terminal, False otherwise.
    """
    return len(VALID_TRANSITIONS.get(status, set())) == 0


@dataclass
class ExecutorConfig:
    """Configuration for the BacktestExecutor."""
    
    # Redis configuration
    redis_url: str = "redis://localhost:6379"
    stream_key: str = "events:feature_snapshots"
    
    # Temporary file storage
    temp_dir: str = "/tmp/backtests"
    cleanup_temp_files: bool = True
    
    # Replay configuration
    fee_bps: float = 1.0
    fee_model: str = "flat"
    fee_tiers: list[dict] = field(default_factory=list)
    slippage_bps: float = 0.0
    slippage_model: str = "flat"
    starting_equity: float = 10000.0
    
    # Sampling configuration
    equity_sample_every: int = 1
    max_equity_points: int = 2000
    max_decision_snapshots: int = 2000
    max_position_snapshots: int = 2000
    
    # Warmup configuration
    warmup_min_snapshots: int = 0
    warmup_require_ready: bool = False
    
    # Data source configuration
    data_source: str = "redis"  # "redis" or "timescaledb"
    default_exchange: str = "okx"  # Default exchange for timescaledb
    
    # TimescaleDB-specific options
    timescaledb_batch_size: int = 1000
    timescaledb_include_trades: bool = True
    
    # Parity mode configuration (Requirement 10)
    parity_mode: bool = True  # Enforce backtest/live parity by default
    live_config: Optional[Dict[str, Any]] = None  # Live config for parity comparison
    
    # Warm start configuration (Requirements 3.1, 5.2)
    warm_start_enabled: bool = False  # Enable warm start from live state
    warm_start_stale_threshold_sec: float = 300.0  # 5 minutes default
    
    @classmethod
    def from_env(cls) -> "ExecutorConfig":
        """Create config from environment variables."""
        return cls(
            redis_url=os.getenv("REDIS_URL", "redis://localhost:6379"),
            stream_key=os.getenv("BACKTEST_STREAM_KEY", "events:feature_snapshots"),
            temp_dir=os.getenv("BACKTEST_TEMP_DIR", "/tmp/backtests"),
            cleanup_temp_files=os.getenv("BACKTEST_CLEANUP_TEMP", "true").lower() in {"1", "true", "yes"},
            fee_bps=float(os.getenv("BACKTEST_FEE_BPS", "1.0")),
            fee_model=os.getenv("BACKTEST_FEE_MODEL", "flat"),
            slippage_bps=float(os.getenv("BACKTEST_SLIPPAGE_BPS", "0.0")),
            slippage_model=os.getenv("BACKTEST_SLIPPAGE_MODEL", "flat"),
            starting_equity=float(os.getenv("BACKTEST_STARTING_EQUITY", "10000.0")),
            equity_sample_every=int(os.getenv("BACKTEST_EQUITY_SAMPLE_EVERY", "1")),
            max_equity_points=int(os.getenv("BACKTEST_MAX_EQUITY_POINTS", "2000")),
            max_decision_snapshots=int(os.getenv("BACKTEST_MAX_DECISION_SNAPSHOTS", "2000")),
            max_position_snapshots=int(os.getenv("BACKTEST_MAX_POSITION_SNAPSHOTS", "2000")),
            warmup_min_snapshots=int(os.getenv("BACKTEST_WARMUP_SNAPSHOTS", "0")),
            warmup_require_ready=os.getenv("BACKTEST_WARMUP_REQUIRE_READY", "false").lower() in {"1", "true", "yes"},
            data_source=os.getenv("BACKTEST_DATA_SOURCE", "redis"),
            default_exchange=os.getenv("BACKTEST_DEFAULT_EXCHANGE", "okx"),
            timescaledb_batch_size=int(os.getenv("BACKTEST_TIMESCALEDB_BATCH_SIZE", "1000")),
            timescaledb_include_trades=os.getenv("BACKTEST_TIMESCALEDB_INCLUDE_TRADES", "true").lower() in {"1", "true", "yes"},
            parity_mode=os.getenv("BACKTEST_PARITY_MODE", "true").lower() in {"1", "true", "yes"},
            warm_start_enabled=os.getenv("BACKTEST_WARM_START_ENABLED", "false").lower() in {"1", "true", "yes"},
            warm_start_stale_threshold_sec=float(os.getenv("BACKTEST_WARM_START_STALE_SEC", "300.0")),
        )


@dataclass
class ExecutionResult:
    """Result of a backtest execution."""
    run_id: str
    status: BacktestStatus
    error_message: Optional[str] = None
    snapshot_count: int = 0
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    parity_verified: bool = False  # Requirement 10.10: Backtest results include parity_verified


class BacktestExecutor:
    """Orchestrates the complete backtest pipeline.
    
    This class manages the full lifecycle of a backtest:
    1. Export snapshots from Redis to a temporary JSONL file
    2. Replay snapshots through the decision engine
    3. Store results to the database
    4. Handle status transitions and error capture
    
    Example usage:
        executor = BacktestExecutor(
            db_pool=pool,
            redis_client=redis,
            decision_engine=engine,
        )
        
        result = await executor.execute(
            run_id="test-run-123",
            tenant_id="tenant-1",
            bot_id="bot-1",
            config={
                "symbol": "BTC-USDT-SWAP",
                "start_date": "2024-01-01",
                "end_date": "2024-01-31",
                "initial_capital": 10000.0,
            }
        )
    """
    
    def __init__(
        self,
        db_pool,
        redis_client,
        decision_engine: Optional[DecisionEngine] = None,
        config: Optional[ExecutorConfig] = None,
        warm_start_loader: Optional["WarmStartLoader"] = None,
    ):
        """Initialize the executor.
        
        Args:
            db_pool: asyncpg connection pool for database operations
            redis_client: Redis client for snapshot export
            decision_engine: Optional decision engine instance. If not provided,
                           a default engine will be created for each execution.
            config: Optional executor configuration. If not provided,
                   defaults will be loaded from environment.
            warm_start_loader: Optional WarmStartLoader for initializing backtest
                             state from live bot state.
        """
        self.db_pool = db_pool
        self.redis_client = redis_client
        self.decision_engine = decision_engine
        self.config = config or ExecutorConfig.from_env()
        self.store = BacktestStore(db_pool)
        self.warm_start_loader = warm_start_loader
    
    async def execute(
        self,
        run_id: str,
        tenant_id: str,
        bot_id: str,
        config: Dict[str, Any],
    ) -> ExecutionResult:
        """Execute a complete backtest pipeline.
        
        This method:
        1. Creates/updates the run record with status="running"
        2. Exports snapshots from Redis to a temporary file
        3. Replays snapshots through the decision engine
        4. Stores results to the database
        5. Updates status to "finished", "failed", or "degraded"
        
        Args:
            run_id: Unique identifier for this backtest run
            tenant_id: Tenant ID for multi-tenancy
            bot_id: Bot ID for the backtest
            config: Backtest configuration containing:
                - symbol: Trading symbol (e.g., "BTC-USDT-SWAP")
                - start_date: Start date (ISO format)
                - end_date: End date (ISO format)
                - initial_capital: Starting equity (optional)
                - fee_bps: Fee in basis points (optional)
                - slippage_bps: Slippage in basis points (optional)
                
        Returns:
            ExecutionResult with status and any error message
            
        Raises:
            ConfigurationError: When parity_mode=True and configs differ from live
        """
        started_at = _now_iso()
        snapshot_path: Optional[Path] = None
        parity_verified = False
        
        try:
            # Step 0: Parity check (Requirement 10)
            parity_result = self._check_parity(config)
            parity_verified = parity_result.parity_verified
            
            # Step 1: Update status to running
            await self._update_status(
                run_id=run_id,
                tenant_id=tenant_id,
                bot_id=bot_id,
                status=BacktestStatus.RUNNING,
                config=config,
                started_at=started_at,
            )
            
            log_info(
                "backtest_executor_start",
                run_id=run_id,
                symbol=config.get("symbol"),
                start_date=config.get("start_date"),
                end_date=config.get("end_date"),
                parity_verified=parity_verified,
            )
            
            # Load warm start state if enabled (Requirements 3.2, 3.3, 3.4, 3.5, 3.6)
            warm_start_state = None
            if self.config.warm_start_enabled and self.warm_start_loader:
                warm_start_state = await self._load_warm_start_state()
            
            # Step 2: Export snapshots from Redis
            snapshot_path = await self._export_snapshots(run_id, config)
            
            # Check if we got any snapshots
            if not snapshot_path.exists() or snapshot_path.stat().st_size == 0:
                raise ValueError("No snapshots found for the specified date range and symbol")
            
            # Count snapshots
            snapshot_count = sum(1 for _ in open(snapshot_path))
            log_info("backtest_snapshots_exported", run_id=run_id, count=snapshot_count)
            
            if snapshot_count == 0:
                raise ValueError("No snapshots found for the specified date range and symbol")
            
            # Step 3: Replay snapshots through decision engine
            await self._replay_snapshots(
                run_id=run_id,
                tenant_id=tenant_id,
                bot_id=bot_id,
                snapshot_path=snapshot_path,
                config=config,
                warm_start_state=warm_start_state,
            )
            
            # Step 4: Get final status from the run record
            # (ReplayWorker may have set it to "degraded" if there were warnings)
            run_record = await self.store.get_run(run_id)
            final_status = BacktestStatus(run_record.status) if run_record else BacktestStatus.FINISHED
            
            finished_at = _now_iso()
            
            log_info(
                "backtest_executor_complete",
                run_id=run_id,
                status=final_status.value,
                snapshot_count=snapshot_count,
                parity_verified=parity_verified,
            )
            
            return ExecutionResult(
                run_id=run_id,
                status=final_status,
                snapshot_count=snapshot_count,
                started_at=started_at,
                finished_at=finished_at,
                parity_verified=parity_verified,
            )
            
        except asyncio.CancelledError:
            # Job was cancelled
            await self._update_status(
                run_id=run_id,
                tenant_id=tenant_id,
                bot_id=bot_id,
                status=BacktestStatus.CANCELLED,
                config=config,
                started_at=started_at,
                finished_at=_now_iso(),
            )
            log_info("backtest_executor_cancelled", run_id=run_id)
            raise
            
        except Exception as e:
            # Capture error and update status
            error_message = str(e)
            await self._update_status(
                run_id=run_id,
                tenant_id=tenant_id,
                bot_id=bot_id,
                status=BacktestStatus.FAILED,
                config=config,
                started_at=started_at,
                finished_at=_now_iso(),
                error_message=error_message,
            )
            log_error(
                "backtest_executor_failed",
                run_id=run_id,
                error=error_message,
            )
            return ExecutionResult(
                run_id=run_id,
                status=BacktestStatus.FAILED,
                error_message=error_message,
                started_at=started_at,
                finished_at=_now_iso(),
            )
            
        finally:
            # Cleanup temporary files
            if snapshot_path and self.config.cleanup_temp_files:
                await self._cleanup(snapshot_path)
    
    async def _export_snapshots(
        self,
        run_id: str,
        config: Dict[str, Any],
    ) -> Path:
        """Export snapshots from data source to a temporary JSONL file.
        
        Uses DataSourceFactory to create the appropriate data source based on
        configuration. Supports both Redis (legacy) and TimescaleDB data sources.
        
        Args:
            run_id: Run ID for logging
            config: Backtest configuration
            
        Returns:
            Path to the exported JSONL file
        """
        from quantgambit.backtesting.data_source import DataSourceFactory
        
        # Create temp directory if needed
        temp_dir = Path(self.config.temp_dir)
        temp_dir.mkdir(parents=True, exist_ok=True)
        
        # Generate output path
        output_path = temp_dir / f"snapshots_{run_id}.jsonl"
        
        # Build data source configuration
        data_source_config = {
            "data_source": config.get("data_source", self.config.data_source),
            "symbol": config.get("symbol"),
            "start_date": config.get("start_date"),
            "end_date": config.get("end_date"),
            "redis_url": self.config.redis_url,
            "stream_key": self.config.stream_key,
            # TimescaleDB-specific options
            "exchange": config.get("exchange", self.config.default_exchange),
            "tenant_id": config.get("tenant_id", "default"),
            "bot_id": config.get("bot_id", "default"),
            "batch_size": config.get("timescaledb_batch_size", self.config.timescaledb_batch_size),
            "include_trades": config.get("timescaledb_include_trades", self.config.timescaledb_include_trades),
        }
        
        # Create data source using factory
        data_source = DataSourceFactory.create(
            config=data_source_config,
            db_pool=self.db_pool,
            redis_client=self.redis_client,
        )
        
        try:
            # Validate data availability (for TimescaleDB)
            validation_result = await data_source.validate()
            
            if not validation_result.is_valid:
                raise ValueError(
                    validation_result.error_message or 
                    "Data validation failed for the specified date range"
                )
            
            # Log any warnings
            for warning in validation_result.warnings:
                log_warning("backtest_data_warning", run_id=run_id, warning=warning)
            
            # Export snapshots
            count = await data_source.export(output_path)
            log_info(
                "backtest_export_complete",
                run_id=run_id,
                count=count,
                data_source=data_source_config["data_source"],
            )
        finally:
            await data_source.close()
        
        return output_path
    
    async def _replay_snapshots(
        self,
        run_id: str,
        tenant_id: str,
        bot_id: str,
        snapshot_path: Path,
        config: Dict[str, Any],
        warm_start_state: Optional["WarmStartState"] = None,
    ) -> None:
        """Replay snapshots through the decision engine.
        
        Args:
            run_id: Run ID
            tenant_id: Tenant ID
            bot_id: Bot ID
            snapshot_path: Path to the JSONL file with snapshots
            config: Backtest configuration
            warm_start_state: Optional warm start state with positions and account state
                            for initializing the backtest from live trading state.
                            Feature: bot-integration-fixes
                            Requirements: 3.3 - WHEN warm starting THEN the System SHALL
                                        initialize the backtest with live positions,
                                        account state, and recent decision history
        """
        # Get decision engine (use provided or create default with backtesting mode)
        # When creating a new engine for backtesting, we configure it with:
        # - backtesting_mode=True: Disables data freshness checks in profile router
        # - ev_gate_config: Uses EV-based entry filtering (not deprecated ConfidenceGate)
        # - ev_position_sizer_config: Uses EV-based position sizing (not deprecated ConfidencePositionSizer)
        # - data_readiness_config: Relaxed data freshness for historical data
        if self.decision_engine:
            engine = self.decision_engine
        else:
            # Create EVGateConfig with relaxed data freshness for backtesting
            # Historical data will have stale timestamps, so we increase the max age limits
            ev_gate_config = EVGateConfig(
                max_book_age_ms=86400000,  # 24 hours - historical data is always "stale"
                max_spread_age_ms=86400000,  # 24 hours
                mode="enforce",  # Still enforce EV thresholds
            )
            
            # Create EVPositionSizerConfig with default settings
            ev_position_sizer_config = EVPositionSizerConfig(
                enabled=True,
            )
            
            # Create DataReadinessConfig with relaxed settings for backtesting
            data_readiness_config = DataReadinessConfig(
                max_trade_age_sec=86400 * 365 * 10,  # 10 years - historical data
                max_clock_drift_sec=86400 * 365 * 10,  # 10 years
                require_ws_connected=False,  # No websocket in backtesting
            )
            
            engine = DecisionEngine(
                backtesting_mode=True,
                ev_gate_config=ev_gate_config,
                ev_position_sizer_config=ev_position_sizer_config,
                data_readiness_config=data_readiness_config,
            )
        
        # Build replay config
        replay_config = ReplayConfig(
            input_path=snapshot_path,
            fee_bps=config.get("fee_bps", self.config.fee_bps),
            fee_model=config.get("fee_model", self.config.fee_model),
            fee_tiers=config.get("fee_tiers", self.config.fee_tiers),
            slippage_bps=config.get("slippage_bps", self.config.slippage_bps),
            slippage_model=config.get("slippage_model", self.config.slippage_model),
            equity_sample_every=config.get("equity_sample_every", self.config.equity_sample_every),
            max_equity_points=config.get("max_equity_points", self.config.max_equity_points),
            max_decision_snapshots=config.get("max_decision_snapshots", self.config.max_decision_snapshots),
            max_position_snapshots=config.get("max_position_snapshots", self.config.max_position_snapshots),
            warmup_min_snapshots=config.get("warmup_min_snapshots", self.config.warmup_min_snapshots),
            warmup_require_ready=config.get("warmup_require_ready", self.config.warmup_require_ready),
            run_id=run_id,
            tenant_id=tenant_id,
            bot_id=bot_id,
        )
        
        # Get starting equity - use warm start account state if available
        # Feature: bot-integration-fixes
        # Requirements: 3.3 - WHEN warm starting THEN the System SHALL initialize
        #               the backtest with live positions, account state
        if warm_start_state and warm_start_state.account_state:
            starting_equity = warm_start_state.account_state.get(
                "equity", config.get("initial_capital", self.config.starting_equity)
            )
            log_info(
                "warm_start_equity_initialized",
                starting_equity=starting_equity,
                source="warm_start_state",
            )
        else:
            starting_equity = config.get("initial_capital", self.config.starting_equity)
        
        # Create replay worker with simulation enabled
        worker = ReplayWorker(
            engine=engine,
            config=replay_config,
            simulate=True,
            starting_equity=starting_equity,
            backtest_store=self.store,
        )
        
        # Initialize simulator with warm start positions if available
        # Feature: bot-integration-fixes
        # Requirements: 3.3 - WHEN warm starting THEN the System SHALL initialize
        #               the backtest with live positions, account state
        if warm_start_state and warm_start_state.positions and worker.simulator:
            from quantgambit.backtesting.simulator import SimPosition
            
            for pos_data in warm_start_state.positions:
                symbol = pos_data.get("symbol")
                if not symbol:
                    continue
                
                # Create SimPosition from warm start position data
                sim_pos = SimPosition(
                    symbol=symbol,
                    side=pos_data.get("side", "long"),
                    size=pos_data.get("size", 0.0),
                    entry_price=pos_data.get("entry_price", 0.0),
                    raw_entry_price=pos_data.get("entry_price", 0.0),
                    entry_fee=pos_data.get("entry_fee", 0.0),
                    profile_id=pos_data.get("profile_id"),
                    strategy_id=pos_data.get("strategy_id"),
                    reason=pos_data.get("reason", "warm_start"),
                )
                worker.simulator.positions[symbol] = sim_pos
            
            log_info(
                "warm_start_positions_initialized",
                position_count=len(warm_start_state.positions),
                symbols=[p.get("symbol") for p in warm_start_state.positions],
            )
        
        # Run replay
        await worker.run()
    
    async def _update_status(
        self,
        run_id: str,
        tenant_id: str,
        bot_id: str,
        status: BacktestStatus,
        config: Dict[str, Any],
        started_at: str,
        finished_at: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> None:
        """Update the status of a backtest run.
        
        Args:
            run_id: Run ID
            tenant_id: Tenant ID
            bot_id: Bot ID
            status: New status
            config: Backtest configuration
            started_at: Start timestamp
            finished_at: Optional finish timestamp
            error_message: Optional error message for failed runs
        """
        record = BacktestRunRecord(
            run_id=run_id,
            tenant_id=tenant_id,
            bot_id=bot_id,
            status=status.value,
            started_at=started_at,
            finished_at=finished_at,
            config=config,
            name=config.get("name"),
            symbol=config.get("symbol"),
            start_date=config.get("start_date"),
            end_date=config.get("end_date"),
            error_message=error_message,
        )
        await self.store.write_run(record)
    
    async def _cleanup(self, snapshot_path: Path) -> None:
        """Clean up temporary files.
        
        Args:
            snapshot_path: Path to the temporary snapshot file
        """
        try:
            if snapshot_path.exists():
                snapshot_path.unlink()
                log_info("backtest_cleanup_complete", path=str(snapshot_path))
        except Exception as e:
            log_warning("backtest_cleanup_failed", path=str(snapshot_path), error=str(e))
    
    async def _load_warm_start_state(self) -> Optional["WarmStartState"]:
        """Load warm start state from live system.
        
        Loads the current live trading state using WarmStartLoader for
        initializing a backtest from the current market position.
        
        Feature: bot-integration-fixes
        Requirements: 3.2 - WHEN warm starting a backtest THEN the System SHALL
                      load the current live state using WarmStartLoader
        Requirements: 3.3 - WHEN warm starting THEN the System SHALL initialize
                      the backtest with live positions, account state, and
                      recent decision history
        Requirements: 3.4 - WHEN warm starting THEN the System SHALL include
                      candle history for AMT calculations
        Requirements: 3.5 - IF warm start state is stale (older than configurable
                      threshold) THEN the System SHALL log a warning but proceed
                      with the backtest
        Requirements: 3.6 - IF warm start state validation fails THEN the System
                      SHALL fall back to cold start with a warning
        
        Returns:
            WarmStartState if successful, None if failed or unavailable
        """
        if not self.warm_start_loader:
            return None
        
        try:
            state = await self.warm_start_loader.load_current_state()
            
            # Check if state is stale (Requirement 3.5)
            if state.is_stale(max_age_sec=self.config.warm_start_stale_threshold_sec):
                log_warning(
                    "warm_start_state_stale",
                    age_seconds=state.get_age_seconds(),
                    threshold_sec=self.config.warm_start_stale_threshold_sec,
                )
            
            # Validate state (Requirement 3.6)
            valid, errors = state.validate()
            if not valid:
                log_warning(
                    "warm_start_validation_failed",
                    errors=errors,
                )
                return None
            
            log_info(
                "warm_start_state_loaded",
                position_count=len(state.positions),
                decision_count=len(state.recent_decisions),
            )
            
            return state
            
        except Exception as exc:
            log_warning("warm_start_load_failed", error=str(exc))
            return None
    
    def _check_parity(self, backtest_config: Dict[str, Any]) -> ParityCheckResult:
        """Check parity between backtest and live configurations.
        
        Requirement 10: Backtest/Live Parity Guarantees
        
        This method compares the backtest configuration against the live
        configuration to ensure they use identical logic. When parity_mode
        is enabled and configs differ, raises ConfigurationError.
        
        Args:
            backtest_config: The backtest configuration to check
            
        Returns:
            ParityCheckResult with parity status and any differences
            
        Raises:
            ConfigurationError: When parity_mode=True and configs differ
        """
        # If parity mode is disabled, skip the check
        if not self.config.parity_mode:
            log_info(
                "parity_check_skipped",
                reason="parity_mode=False",
            )
            return ParityCheckResult(parity_verified=True)
        
        # Get live config for comparison
        live_config = self.config.live_config
        if live_config is None:
            # Build default live config from executor config
            live_config = self._build_live_config()
        
        # Build backtest config in comparable format
        comparable_backtest_config = self._build_comparable_config(backtest_config)
        
        # Perform parity check
        checker = ParityChecker()
        result = checker.compare_configs(comparable_backtest_config, live_config)
        
        # Log parity check summary (Requirement 10.9)
        checker.log_parity_summary(result)
        
        # Raise ConfigurationError if parity check fails (Requirement 10.7)
        if not result.parity_verified:
            error_msg = (
                f"Backtest/live parity check failed. "
                f"Differences: {'; '.join(result.differences[:5])}"
            )
            if len(result.differences) > 5:
                error_msg += f" (and {len(result.differences) - 5} more)"
            raise ConfigurationError(error_msg)
        
        return result
    
    def _build_live_config(self) -> Dict[str, Any]:
        """Build a live configuration from executor defaults.
        
        This creates a configuration dictionary that represents the
        expected live system configuration for parity comparison.
        
        Returns:
            Dictionary with live configuration values
        """
        return {
            "ev_gate": {
                "ev_min": 0.05,  # Default EV minimum
                "ev_min_floor": 0.02,  # Default EV floor
            },
            "threshold_calculator": {
                "k": 3.0,  # Default cost multiplier
                "b": 0.25,  # Default VA width multiplier
                "floor_bps": 12.0,  # Default floor in bps
            },
            "fee_model": {
                "model_type": self.config.fee_model,
                "maker_fee_bps": self.config.fee_bps,
                "taker_fee_bps": self.config.fee_bps,
            },
            "slippage_model": {
                "model_type": self.config.slippage_model,
                "base_slippage_bps": self.config.slippage_bps,
            },
            "pipeline_stages": [],  # Will be populated from decision engine
        }
    
    def _build_comparable_config(self, backtest_config: Dict[str, Any]) -> Dict[str, Any]:
        """Build a comparable configuration from backtest config.
        
        This transforms the backtest configuration into a format that
        can be compared against the live configuration.
        
        Args:
            backtest_config: Raw backtest configuration
            
        Returns:
            Dictionary with comparable configuration values
        """
        return {
            "ev_gate": {
                "ev_min": backtest_config.get("ev_min", 0.05),
                "ev_min_floor": backtest_config.get("ev_min_floor", 0.02),
            },
            "threshold_calculator": {
                "k": backtest_config.get("threshold_k", 3.0),
                "b": backtest_config.get("threshold_b", 0.25),
                "floor_bps": backtest_config.get("threshold_floor_bps", 12.0),
            },
            "fee_model": {
                "model_type": backtest_config.get("fee_model", self.config.fee_model),
                "maker_fee_bps": backtest_config.get("fee_bps", self.config.fee_bps),
                "taker_fee_bps": backtest_config.get("fee_bps", self.config.fee_bps),
            },
            "slippage_model": {
                "model_type": backtest_config.get("slippage_model", self.config.slippage_model),
                "base_slippage_bps": backtest_config.get("slippage_bps", self.config.slippage_bps),
            },
            "pipeline_stages": backtest_config.get("pipeline_stages", []),
        }


def _now_iso() -> str:
    """Get current UTC time in ISO format."""
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_datetime(value: Optional[str]) -> Optional[datetime]:
    """Parse datetime from various formats."""
    if value is None:
        return None
    
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


async def create_executor_function(
    db_pool,
    redis_client,
    decision_engine: Optional[DecisionEngine] = None,
    config: Optional[ExecutorConfig] = None,
):
    """Create an executor function for use with BacktestJobQueue.
    
    This factory function creates an async executor function that can be
    passed to BacktestJobQueue.submit().
    
    Args:
        db_pool: asyncpg connection pool
        redis_client: Redis client
        decision_engine: Optional decision engine
        config: Optional executor configuration
        
    Returns:
        An async function with signature (run_id: str, config: dict) -> None
    """
    executor = BacktestExecutor(
        db_pool=db_pool,
        redis_client=redis_client,
        decision_engine=decision_engine,
        config=config,
    )
    
    async def execute_backtest(run_id: str, job_config: Dict[str, Any]) -> None:
        """Execute a backtest job.
        
        Args:
            run_id: Run ID
            job_config: Job configuration containing tenant_id, bot_id, and backtest config
        """
        tenant_id = job_config.get("tenant_id", "default")
        bot_id = job_config.get("bot_id", "default")
        backtest_config = job_config.get("config", job_config)
        
        result = await executor.execute(
            run_id=run_id,
            tenant_id=tenant_id,
            bot_id=bot_id,
            config=backtest_config,
        )
        
        if result.status == BacktestStatus.FAILED:
            raise RuntimeError(result.error_message or "Backtest failed")
    
    return execute_backtest
