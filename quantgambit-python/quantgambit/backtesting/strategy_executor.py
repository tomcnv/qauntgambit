"""Strategy-based backtest executor using real strategy engine.

This executor uses the SAME DecisionEngine pipeline as the live bot to ensure
backtest results accurately reflect live trading behavior.

Pipeline Unification (Requirements 1.1, 1.2, 1.3):
- Routes all decisions through DecisionEngine with backtesting_mode=True
- Applies all loss prevention stages (StrategyTrendAlignmentStage, EVGateStage, etc.)
- Uses TrendCalculator to fix unreliable trend_direction in historical data

Data Pipeline:
1. Fetches historical decision_events from TimescaleDB (rich feature snapshots)
2. Fetches orderbook_events for real depth/imbalance data
3. Fetches market_candles for real AMT calculations (POC, VAH, VAL)
4. Builds proper MarketSnapshot objects like the live bot
5. Routes through DecisionEngine for consistent decision logic
6. Simulates trades with realistic fee/slippage models
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass, asdict
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple

from quantgambit.backtesting.store import (
    BacktestStore,
    BacktestRunRecord,
    BacktestMetricsRecord,
    BacktestTradeRecord,
    BacktestEquityPoint,
    BacktestSymbolMetricsRecord,
)
from quantgambit.integration.warm_start import WarmStartState
from quantgambit.integration.execution_simulator import (
    ExecutionSimulator,
    ExecutionSimulatorConfig,
    SimulatedFill,
)
from quantgambit.integration.config_registry import (
    ConfigurationRegistry,
    ConfigurationError,
)
from quantgambit.backtesting.data_validator import (
    DataValidator,
    ValidationConfig,
    RuntimeQualityTracker,
    QualityReport,
)
from quantgambit.backtesting.trend_calculator import TrendCalculator, get_trend_calculator
from quantgambit.backtesting.stage_context_builder import StageContextBuilder, get_stage_context_builder
from quantgambit.backtesting.decision_adapter import BacktestDecisionAdapter, DecisionResult
from quantgambit.backtesting.stage_rejection_diagnostics import StageRejectionDiagnostics
from quantgambit.core.volume_profile import (
    calculate_volume_profile,
    VolumeProfileConfig,
    VolumeProfileResult,
)
from quantgambit.deeptrader_core.types import Features, AccountState, Profile, MarketSnapshot
from quantgambit.deeptrader_core.strategies.registry import STRATEGIES
from quantgambit.deeptrader_core.profiles.profile_router import ProfileRouter, get_profile_router
from quantgambit.deeptrader_core.profiles.context_vector import ContextVector
from quantgambit.deeptrader_core.profiles.router_config import RouterConfig
from quantgambit.deeptrader_core.strategies.chessboard import get_profile_registry
from quantgambit.signals.decision_engine import DecisionEngine
from quantgambit.signals.stages.data_readiness import DataReadinessConfig
from quantgambit.signals.stages.global_gate import GlobalGateConfig
from quantgambit.signals.stages.amt_calculator import CandleCache, AMTLevels
from quantgambit.signals.stages.ev_gate import EVGateConfig
from quantgambit.signals.stages.ev_position_sizer import EVPositionSizerConfig
from quantgambit.signals.stages.session_filter import SessionFilterConfig
from quantgambit.ingest.candle_builder import CandleBuilder
from quantgambit.storage.trade_record_reader import TradeRecordReader, TradeRecordReaderConfig
from quantgambit.risk.fee_model import FeeConfig
from quantgambit.risk.slippage_model import SlippageModel

logger = logging.getLogger(__name__)


def _normalize_exchange_name(exchange: Optional[str]) -> str:
    if not exchange:
        return "bybit"
    return str(exchange).strip().lower()


def _resolve_fee_config(name: Optional[str], exchange: str) -> Optional[FeeConfig]:
    if not name:
        return None
    normalized = str(name).strip().lower()
    if normalized in {"bybit", "bybit_regular"}:
        return FeeConfig.bybit_regular()
    if normalized in {"okx", "okx_regular"}:
        return FeeConfig.okx_regular()
    attr = normalized.replace("-", "_")
    if hasattr(FeeConfig, attr):
        try:
            return getattr(FeeConfig, attr)()
        except Exception:
            return None
    return None


def _resolve_fee_bps(config: Dict[str, Any], exchange: Optional[str]) -> tuple[float, float, str]:
    exchange_name = _normalize_exchange_name(exchange)
    fee_model = config.get("fee_model") if isinstance(config.get("fee_model"), dict) else {}
    maker_fee = config.get("maker_fee_bps", fee_model.get("maker_fee_bps"))
    taker_fee = config.get("taker_fee_bps", fee_model.get("taker_fee_bps"))
    if maker_fee is None and taker_fee is None:
        flat_fee = config.get("fee_bps", fee_model.get("fee_bps"))
        if flat_fee is not None:
            maker_fee = flat_fee
            taker_fee = flat_fee
    if maker_fee is not None or taker_fee is not None:
        maker_fee = float(maker_fee if maker_fee is not None else taker_fee)
        taker_fee = float(taker_fee if taker_fee is not None else maker_fee)
        return maker_fee, taker_fee, "explicit"

    fee_config = config.get("fee_config")
    if fee_config is None:
        fee_config = os.getenv("BACKTEST_FEE_CONFIG") or os.getenv("POSITION_GUARD_FEE_CONFIG")
    if isinstance(fee_config, dict):
        fee_obj = FeeConfig.from_dict(fee_config)
        return fee_obj.maker_fee_rate * 10000.0, fee_obj.taker_fee_rate * 10000.0, "fee_config_dict"
    if isinstance(fee_config, str) and fee_config.strip():
        fee_obj = _resolve_fee_config(fee_config, exchange_name)
        if fee_obj:
            return fee_obj.maker_fee_rate * 10000.0, fee_obj.taker_fee_rate * 10000.0, f"fee_config:{fee_config}"

    if exchange_name:
        fee_obj = FeeConfig.bybit_regular() if "bybit" in exchange_name else FeeConfig.okx_regular()
        return fee_obj.maker_fee_rate * 10000.0, fee_obj.taker_fee_rate * 10000.0, f"exchange:{exchange_name}"

    return 2.0, 5.5, "default"


def _resolve_slippage_bps(
    config: Dict[str, Any],
    exchange: Optional[str],
    symbol: str,
    spread_bps: float,
    bid_depth_usd: float,
    ask_depth_usd: float,
    volatility_regime: Optional[str],
    order_size_usd: Optional[float],
    slippage_model: Optional[SlippageModel],
) -> float:
    model = (config.get("slippage_model") or os.getenv("BACKTEST_SLIPPAGE_MODEL", "fixed")).lower()
    if model in {"none", "off", "zero"}:
        return 0.0

    slippage_config = config.get("slippage_bps", 5.0)
    if isinstance(slippage_config, dict):
        exchange_name = _normalize_exchange_name(exchange)
        slippage_value = (
            slippage_config.get(symbol)
            or slippage_config.get(exchange_name)
            or slippage_config.get("default")
        )
        if slippage_value is not None:
            slippage_config = slippage_value

    if model in {"adaptive", "market", "symbol"} and slippage_model is not None:
        depth = None
        if bid_depth_usd > 0 and ask_depth_usd > 0:
            depth = min(bid_depth_usd, ask_depth_usd)
        return float(
            slippage_model.calculate_slippage_bps(
                symbol=symbol,
                spread_bps=spread_bps,
                book_depth_usd=depth,
                order_size_usd=order_size_usd,
                volatility_regime=volatility_regime,
            )
        )

    try:
        return float(slippage_config)
    except (TypeError, ValueError):
        return 0.0


@dataclass
class StrategyExecutorConfig:
    """Configuration for the strategy executor."""
    timescale_host: str = "localhost"
    timescale_port: int = 5433
    timescale_db: str = "quantgambit_bot"
    timescale_user: str = "quantgambit"
    timescale_password: str = ""
    
    # Sampling - decision_events are very high frequency (~6-8 per second)
    # Sample every N events to reduce computation
    sample_every: int = 10  # Process every 10th event (~0.6-0.8 per second)
    
    # AMT calculation settings
    amt_lookback_candles: int = 100  # Number of candles for volume profile
    amt_value_area_pct: float = 68.0  # Standard value area percentage
    
    # Gating thresholds (match live bot defaults)
    max_spread_bps: float = 15.0
    min_depth_usd: float = 10000.0
    max_snapshot_age_ms: float = 5000.0
    cooldown_seconds: float = 60.0
    
    # Execution simulation settings
    # Feature: trading-pipeline-integration
    # Requirements: 5.5 - THE System SHALL support configurable execution scenarios
    # (optimistic, realistic, pessimistic)
    # Requirements: 5.6 - WHEN execution simulation differs significantly from live
    # results THEN the System SHALL flag the backtest for review
    execution_scenario: str = "realistic"  # "optimistic", "realistic", "pessimistic"
    
    @classmethod
    def from_env(cls) -> "StrategyExecutorConfig":
        """Create config from environment variables."""
        return cls(
            timescale_host=os.getenv("TIMESCALE_HOST", os.getenv("BOT_DB_HOST", "localhost")),
            timescale_port=int(os.getenv("TIMESCALE_PORT", os.getenv("BOT_DB_PORT", "5433"))),
            timescale_db=os.getenv("TIMESCALE_DB", os.getenv("BOT_DB_NAME", "quantgambit_bot")),
            timescale_user=os.getenv("TIMESCALE_USER", os.getenv("BOT_DB_USER", "quantgambit")),
            timescale_password=os.getenv("TIMESCALE_PASSWORD", os.getenv("BOT_DB_PASSWORD", "")),
            sample_every=int(os.getenv("BACKTEST_SAMPLE_EVERY", "10")),
            amt_lookback_candles=int(os.getenv("BACKTEST_AMT_LOOKBACK", "100")),
            amt_value_area_pct=float(os.getenv("BACKTEST_VALUE_AREA_PCT", "68.0")),
            max_spread_bps=float(os.getenv("BACKTEST_MAX_SPREAD_BPS", "15.0")),
            min_depth_usd=float(os.getenv("BACKTEST_MIN_DEPTH_USD", "10000.0")),
            max_snapshot_age_ms=float(os.getenv("BACKTEST_MAX_SNAPSHOT_AGE_MS", "5000.0")),
            cooldown_seconds=float(os.getenv("BACKTEST_COOLDOWN_SECONDS", "60.0")),
            execution_scenario=os.getenv("BACKTEST_EXECUTION_SCENARIO", "realistic"),
        )


class StrategyBacktestExecutor:
    """Backtest executor using real strategy engine with full data pipeline."""
    
    def __init__(
        self,
        platform_pool,
        config: Optional[StrategyExecutorConfig] = None,
        config_registry: Optional[ConfigurationRegistry] = None,
    ):
        """Initialize the executor.
        
        Args:
            platform_pool: asyncpg connection pool for platform_db
            config: Optional executor configuration
            config_registry: Optional ConfigurationRegistry for configuration parity
                           enforcement. If provided, backtest configuration will be
                           loaded from the registry and parity checking will be enabled.
                           Feature: trading-pipeline-integration
                           Requirements: 1.1 - THE System SHALL maintain a single source
                           of truth for all trading configuration parameters
                           Requirements: 1.2 - WHEN a backtest is initiated THEN the System
                           SHALL automatically load the current live configuration unless
                           explicitly overridden
                           Requirements: 1.5 - WHEN critical configuration parameters differ
                           THEN the System SHALL require explicit acknowledgment before
                           proceeding
        """
        self.platform_pool = platform_pool
        self.config = config or StrategyExecutorConfig.from_env()
        self.store = BacktestStore(platform_pool)
        self._timescale_pool = None
        # Create profile router with backtesting_mode=True to skip stale data checks
        # Historical data will always fail book_age_ms and trade_age_ms safety filters
        router_config = RouterConfig(backtesting_mode=True)
        self._profile_router = get_profile_router(config=router_config)
        self._data_validator = None
        self._runtime_tracker = None
        # Configuration registry for parity enforcement
        # Feature: trading-pipeline-integration
        # Requirements: 1.1, 1.2, 1.5
        self._config_registry = config_registry
    
    async def _get_timescale_pool(self):
        """Get or create TimescaleDB connection pool."""
        if self._timescale_pool is None:
            import asyncpg
            auth = f"{self.config.timescale_user}:{self.config.timescale_password}@" if self.config.timescale_password else f"{self.config.timescale_user}@"
            dsn = f"postgresql://{auth}{self.config.timescale_host}:{self.config.timescale_port}/{self.config.timescale_db}"
            self._timescale_pool = await asyncpg.create_pool(dsn, min_size=1, max_size=5)
        return self._timescale_pool
    
    async def _get_data_validator(self) -> DataValidator:
        """Get or create DataValidator instance."""
        if self._data_validator is None:
            pool = await self._get_timescale_pool()
            self._data_validator = DataValidator(pool)
        return self._data_validator
    
    async def validate_data(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
        config: Optional[ValidationConfig] = None,
        force_run: bool = False,
    ) -> QualityReport:
        """Validate data quality before backtest execution.
        
        Args:
            symbol: Trading symbol
            start_date: Start date
            end_date: End date
            config: Optional validation config
            force_run: If True, allow backtest even if thresholds not met
            
        Returns:
            QualityReport with validation results
        """
        validator = await self._get_data_validator()
        return await validator.validate(symbol, start_date, end_date, config, force_run)
    
    async def execute(
        self,
        run_id: str,
        tenant_id: str,
        bot_id: str,
        config: Dict[str, Any],
        warm_start_state: Optional[WarmStartState] = None,
    ) -> Dict[str, Any]:
        """Execute a backtest using real strategy engine with full data pipeline.
        
        Args:
            run_id: Unique identifier for this backtest run
            tenant_id: Tenant ID
            bot_id: Bot ID
            config: Backtest configuration
            warm_start_state: Optional warm start state to initialize from live state.
                             If provided, positions, account state, and candle cache
                             will be initialized from this state instead of starting fresh.
                             Feature: trading-pipeline-integration
                             Requirements: 3.1 - THE System SHALL support initializing a backtest
                             with current live positions, account state, and recent decision history
            
        Returns:
            Dict with execution results
        """
        started_at = datetime.now(timezone.utc).isoformat()
        
        # Apply profile parameter overrides from config
        profile_overrides = config.get("profile_overrides", {})
        if profile_overrides:
            logger.info(f"Applying profile overrides to registry: {profile_overrides}")
            registry = self._profile_router.registry
            for profile_id, spec in list(registry._specs.items()):
                registry._specs[profile_id] = spec.apply_overrides(profile_overrides)
        
        # Initialize runtime quality tracker
        self._runtime_tracker = RuntimeQualityTracker()
        
        try:
            # Update status to running
            await self._update_status(run_id, tenant_id, bot_id, "running", config, started_at)
            logger.info(f"Starting strategy backtest {run_id} for {config.get('symbol')}")
            
            symbol = config.get("symbol")
            start_date = config.get("start_date")
            end_date = config.get("end_date")
            force_run = config.get("force_run", False)
            
            logger.info(f"Backtest {run_id}: force_run={force_run}, config keys={list(config.keys())}")
            
            # Pre-flight data validation
            validation_config = ValidationConfig(
                minimum_completeness_pct=config.get("minimum_completeness_pct", 80.0),
                max_critical_gaps=config.get("max_critical_gaps", 5),
                max_gap_duration_pct=config.get("max_gap_duration_pct", 10.0),
            )
            
            quality_report = await self.validate_data(
                symbol, start_date, end_date, validation_config, force_run
            )
            
            logger.info(
                f"Backtest {run_id}: validation result passes_threshold={quality_report.passes_threshold}, "
                f"threshold_overridden={quality_report.threshold_overridden}, errors={quality_report.errors}"
            )
            
            # Check if validation passed
            if not quality_report.passes_threshold:
                error_msg = "; ".join(quality_report.errors) or "Data quality validation failed"
                raise ValueError(f"Data validation failed: {error_msg}")
            
            # Log validation results
            logger.info(
                f"Data validation passed for {run_id}: "
                f"grade={quality_report.data_quality_grade}, "
                f"completeness={quality_report.overall_completeness_pct}%, "
                f"recommendation={quality_report.recommendation}"
            )
            
            # Fetch all required data in parallel
            exchange = config.get("exchange", "bybit")
            events, orderbook_data, candle_data = await asyncio.gather(
                self._fetch_decision_events(symbol, start_date, end_date),
                self._fetch_orderbook_events(symbol, start_date, end_date),
                self._fetch_candle_data(symbol, start_date, end_date, tenant_id, bot_id, exchange),
            )
            
            if not events:
                raise ValueError(f"No decision events found for {symbol} in the specified date range")
            
            logger.info(f"Fetched {len(events)} decision events, {len(orderbook_data)} orderbook events, {len(candle_data)} candles for backtest {run_id}")
            
            # Handle warm start state if provided
            # Feature: trading-pipeline-integration
            # Requirements: 3.1 - THE System SHALL support initializing a backtest with
            # current live positions, account state, and recent decision history
            if warm_start_state is not None:
                logger.info(
                    f"Warm start enabled for backtest {run_id}: "
                    f"{len(warm_start_state.positions)} positions, "
                    f"equity={warm_start_state.account_state.get('equity', 0)}, "
                    f"snapshot_age={warm_start_state.get_age_seconds():.1f}s"
                )
                
                # Validate warm start state
                is_valid, validation_errors = warm_start_state.validate()
                if not is_valid:
                    logger.warning(
                        f"Warm start state validation warnings for {run_id}: {validation_errors}"
                    )
                
                # Check for staleness
                if warm_start_state.is_stale():
                    logger.warning(
                        f"Warm start state is stale for {run_id}: "
                        f"age={warm_start_state.get_age_seconds():.1f}s "
                        f"(threshold={warm_start_state.DEFAULT_MAX_AGE_SEC}s)"
                    )
                
                # Pre-populate candle data from warm start candle_history
                # This ensures AMT calculations have sufficient history
                if warm_start_state.candle_history:
                    warm_start_candles = warm_start_state.candle_history.get(symbol, [])
                    if warm_start_candles:
                        # Prepend warm start candles to candle_data
                        # Filter out any duplicates based on timestamp
                        existing_timestamps = {c["ts"] for c in candle_data}
                        new_candles = [
                            c for c in warm_start_candles 
                            if c.get("ts") not in existing_timestamps
                        ]
                        candle_data = new_candles + candle_data
                        logger.info(
                            f"Pre-populated {len(new_candles)} candles from warm start state "
                            f"(total candles: {len(candle_data)})"
                        )
            
            # Load configuration from ConfigurationRegistry if available
            # Feature: trading-pipeline-integration
            # Requirements: 1.1 - THE System SHALL maintain a single source of truth for
            # all trading configuration parameters
            # Requirements: 1.2 - WHEN a backtest is initiated THEN the System SHALL
            # automatically load the current live configuration unless explicitly overridden
            # Requirements: 1.5 - WHEN critical configuration parameters differ THEN the
            # System SHALL require explicit acknowledgment before proceeding
            config_version = None
            config_diff = None
            
            if self._config_registry is not None:
                # Extract override parameters from backtest config
                override_params = config.get("override_params")
                require_parity = config.get("require_parity", True)
                
                try:
                    backtest_config, config_diff = await self._config_registry.get_config_for_backtest(
                        override_params=override_params,
                        require_parity=require_parity,
                    )
                    config_version = backtest_config.version_id
                    
                    # Merge registry parameters into backtest config
                    # Registry parameters take precedence for trading parameters
                    if backtest_config.parameters:
                        for key, value in backtest_config.parameters.items():
                            # Only override if not explicitly set in backtest config
                            if key not in config or config.get("use_registry_params", True):
                                config[key] = value
                    
                    logger.info(
                        f"Loaded configuration from registry for backtest {run_id}: "
                        f"version={config_version}, "
                        f"has_diff={config_diff is not None}"
                    )
                    
                    if config_diff and config_diff.has_diffs:
                        logger.info(
                            f"Configuration diff for backtest {run_id}: "
                            f"critical={len(config_diff.critical_diffs)}, "
                            f"warning={len(config_diff.warning_diffs)}, "
                            f"info={len(config_diff.info_diffs)}"
                        )
                        
                except ConfigurationError as e:
                    # Configuration parity check failed
                    # Requirements: 1.5 - WHEN critical configuration parameters differ
                    # THEN the System SHALL require explicit acknowledgment before proceeding
                    logger.error(
                        f"Configuration parity check failed for backtest {run_id}: {e}"
                    )
                    raise ValueError(
                        f"Configuration parity check failed: {e.message}. "
                        f"Critical differences: {e.critical_diffs}. "
                        f"Set require_parity=False to override."
                    )
            
            # Run strategy simulation with full data
            results = await self._run_strategy_simulation(
                run_id=run_id,
                events=events,
                orderbook_data=orderbook_data,
                candle_data=candle_data,
                config=config,
                warm_start_state=warm_start_state,
            )
            
            # Add config_version to results if available
            # Feature: trading-pipeline-integration
            # Requirements: 1.2 - Store config_version with backtest results
            if config_version is not None:
                results["config_version"] = config_version
                if config_diff is not None:
                    results["config_diff"] = {
                        "has_critical_diffs": config_diff.has_critical_diffs,
                        "has_warning_diffs": config_diff.has_warning_diffs,
                        "critical_count": len(config_diff.critical_diffs),
                        "warning_count": len(config_diff.warning_diffs),
                        "info_count": len(config_diff.info_diffs),
                    }
            
            # Store results with quality metrics
            await self._store_results(run_id, results, quality_report)
            
            # Determine final status based on runtime quality
            runtime_quality = results.get("runtime_quality", {})
            is_degraded = runtime_quality.get("is_degraded", False)
            final_status = "degraded" if is_degraded else "completed"
            
            # Update status to completed or degraded
            finished_at = datetime.now(timezone.utc).isoformat()
            await self._update_status(
                run_id, tenant_id, bot_id, final_status, config, started_at, finished_at
            )
            
            logger.info(f"Strategy backtest {run_id} {final_status}: {results['metrics']['total_trades']} trades, {results['metrics']['total_return_pct']:.2f}% return")
            
            # Build return dict with config_version if available
            # Feature: trading-pipeline-integration
            # Requirements: 1.2 - Store config_version with backtest results
            return_dict = {
                "status": final_status,
                "run_id": run_id,
                **results["metrics"],
                "runtime_quality": runtime_quality,
            }
            if config_version is not None:
                return_dict["config_version"] = config_version
            if config_diff is not None:
                return_dict["config_diff"] = results.get("config_diff")
            
            return return_dict
            
        except Exception as e:
            logger.exception(f"Strategy backtest {run_id} failed: {e}")
            finished_at = datetime.now(timezone.utc).isoformat()
            await self._update_status(
                run_id, tenant_id, bot_id, "failed", config, started_at, finished_at, str(e)
            )
            return {"status": "failed", "run_id": run_id, "error": str(e)}
    
    async def _fetch_decision_events(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
    ) -> List[Dict[str, Any]]:
        """Fetch historical decision events from TimescaleDB."""
        pool = await self._get_timescale_pool()
        
        query = """
            SELECT ts, payload
            FROM decision_events
            WHERE symbol = $1 AND ts >= $2 AND ts <= $3
            ORDER BY ts ASC
        """
        
        start_dt, end_dt = self._parse_date_range(start_date, end_date)
        
        async with pool.acquire() as conn:
            rows = await conn.fetch(query, symbol, start_dt, end_dt)
            
            # Sample events to reduce computation
            sampled = []
            for i, row in enumerate(rows):
                if i % self.config.sample_every == 0:
                    payload = row["payload"]
                    if isinstance(payload, str):
                        payload = json.loads(payload)
                    sampled.append({
                        "ts": row["ts"],
                        "payload": payload,
                    })
            
            return sampled
    
    async def _fetch_orderbook_events(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
    ) -> Dict[datetime, Dict[str, Any]]:
        """Fetch orderbook events and index by timestamp for fast lookup."""
        pool = await self._get_timescale_pool()
        
        query = """
            SELECT ts, payload
            FROM orderbook_events
            WHERE symbol = $1 AND ts >= $2 AND ts <= $3
            ORDER BY ts ASC
        """
        
        start_dt, end_dt = self._parse_date_range(start_date, end_date)
        
        async with pool.acquire() as conn:
            rows = await conn.fetch(query, symbol, start_dt, end_dt)
            
            # Index by timestamp (rounded to second for matching)
            orderbook_index = {}
            for row in rows:
                ts = row["ts"]
                payload = row["payload"]
                if isinstance(payload, str):
                    payload = json.loads(payload)
                # Round to second for matching with decision events
                ts_key = ts.replace(microsecond=0)
                orderbook_index[ts_key] = payload
            
            return orderbook_index
    
    async def _fetch_candle_data(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
        tenant_id: str,
        bot_id: str,
        exchange: str,
    ) -> List[Dict[str, Any]]:
        """Fetch candle data for AMT calculations using the live candle builder."""
        pool = await self._get_timescale_pool()

        start_dt, end_dt = self._parse_date_range(start_date, end_date)
        candle_start_dt = start_dt - timedelta(hours=12)

        reader = TradeRecordReader(
            pool,
            TradeRecordReaderConfig(
                tenant_id=tenant_id,
                bot_id=bot_id,
            ),
        )
        trades = await reader.get_trades(
            symbol=symbol,
            exchange=exchange,
            start_time=candle_start_dt,
            end_time=end_dt,
        )

        if not trades:
            logger.warning(
                "amt_candle_builder_no_trades",
                extra={
                    "symbol": symbol,
                    "exchange": exchange,
                    "start": candle_start_dt.isoformat(),
                    "end": end_dt.isoformat(),
                },
            )
            return []

        timeframe_sec = int(os.getenv("AMT_CANDLE_TIMEFRAME_SEC", "300"))
        builder = CandleBuilder(timeframes_sec=(timeframe_sec,))
        candles: List[Dict[str, Any]] = []

        for trade in trades:
            ts_us = int(trade.timestamp.timestamp() * 1_000_000)
            results = builder.process_tick(
                symbol=symbol,
                ts_canon_us=ts_us,
                price=trade.price,
                volume=trade.size,
                price_source="last",
                now_us=ts_us,
            )
            for result in results:
                candles.append(
                    {
                        "ts": datetime.fromtimestamp(result.candle.start_ts, tz=timezone.utc),
                        "open": result.candle.open,
                        "high": result.candle.high,
                        "low": result.candle.low,
                        "close": result.candle.close,
                        "volume": result.candle.volume,
                    }
                )

        flush_us = int(end_dt.timestamp() * 1_000_000) + builder.max_grace_us()
        for result in builder.flush(flush_us):
            candles.append(
                {
                    "ts": datetime.fromtimestamp(result.candle.start_ts, tz=timezone.utc),
                    "open": result.candle.open,
                    "high": result.candle.high,
                    "low": result.candle.low,
                    "close": result.candle.close,
                    "volume": result.candle.volume,
                }
            )

        candles.sort(key=lambda c: c["ts"])
        return candles
    
    def _parse_date_range(self, start_date: str, end_date: str) -> Tuple[datetime, datetime]:
        """Parse date strings to datetime objects."""
        if 'T' in start_date:
            start_dt = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
        else:
            start_dt = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        
        if 'T' in end_date:
            end_dt = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
        else:
            end_dt = datetime.strptime(end_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        
        # Ensure timezone-aware (asyncpg requires it for timestamptz columns)
        if start_dt.tzinfo is None:
            start_dt = start_dt.replace(tzinfo=timezone.utc)
        if end_dt.tzinfo is None:
            end_dt = end_dt.replace(tzinfo=timezone.utc)
        
        return start_dt, end_dt
    
    def _calculate_amt_levels(
        self,
        candles: List[Dict[str, Any]],
        current_ts: datetime,
    ) -> Dict[str, float]:
        """Calculate real AMT levels (POC, VAH, VAL) from candle data.
        
        Uses the shared volume profile algorithm (same as live AMTCalculatorStage)
        to ensure consistency between live and backtest calculations.
        
        Requirements: 8.2 - Algorithm Consistency Between Live and Backtest
        
        Args:
            candles: List of candle data with ts, open, high, low, close, volume
            current_ts: Current timestamp to filter candles
            
        Returns:
            Dict with point_of_control, value_area_low, value_area_high, or empty dict
            if insufficient data.
        """
        # Get candles up to current timestamp
        relevant_candles = [c for c in candles if c["ts"] <= current_ts]
        
        # Use last N candles for volume profile
        lookback = min(self.config.amt_lookback_candles, len(relevant_candles))
        if lookback < 10:
            # Requirement 8.4: Log warning when candle data unavailable
            logger.warning(
                f"amt_reconstruction_insufficient_candles: "
                f"only {lookback} candles available (need at least 10) at {current_ts}"
            )
            return {}
        
        recent_candles = relevant_candles[-lookback:]
        
        # Extract price and volume data
        prices = []
        volumes = []
        for candle in recent_candles:
            # Use OHLC average as representative price (same as live bot)
            price = (candle["open"] + candle["high"] + candle["low"] + candle["close"]) / 4
            prices.append(price)
            volumes.append(candle["volume"])
        
        # Calculate volume profile using shared algorithm
        # Requirement 8.2: Use same algorithm as live AMTCalculatorStage
        shared_config = VolumeProfileConfig(
            bin_count=20,  # Standard bin count
            value_area_pct=self.config.amt_value_area_pct,
            min_data_points=10,
        )
        
        # Use the shared volume profile calculation
        result = calculate_volume_profile(prices, volumes, shared_config)
        
        # Convert result to dict format (for backward compatibility)
        if result is None:
            # Requirement 8.4: Log warning when calculation fails
            logger.warning(
                f"amt_reconstruction_calculation_failed: "
                f"volume profile calculation returned None at {current_ts}"
            )
            return {}
        
        return result.to_dict()
    
    def _get_amt_from_decision_event(
        self,
        event: Dict[str, Any],
    ) -> Optional[Dict[str, float]]:
        """Extract AMT fields from decision_event if present.
        
        Checks if the decision_event payload already contains AMT fields
        (poc_price, vah_price, val_price). If all three are present and valid,
        returns them. Otherwise returns None to indicate reconstruction is needed.
        
        Requirements: 8.1 - Reconstruct AMT only when decision_events lack them
        
        Args:
            event: Decision event with payload containing snapshot data
            
        Returns:
            Dict with AMT fields if present and valid, None otherwise
        """
        payload = event.get("payload", {})
        snapshot_data = payload.get("snapshot", {})
        
        # Check for AMT fields in snapshot
        poc_price = snapshot_data.get("poc_price")
        vah_price = snapshot_data.get("vah_price")
        val_price = snapshot_data.get("val_price")
        
        # All three must be present and valid (non-None, positive)
        if (poc_price is not None and poc_price > 0 and
            vah_price is not None and vah_price > 0 and
            val_price is not None and val_price > 0):
            return {
                "point_of_control": poc_price,
                "value_area_high": vah_price,
                "value_area_low": val_price,
            }
        
        return None
    
    def _get_orderbook_at_time(
        self,
        orderbook_data: Dict[datetime, Dict[str, Any]],
        ts: datetime,
    ) -> Optional[Dict[str, Any]]:
        """Get orderbook data closest to the given timestamp."""
        ts_key = ts.replace(microsecond=0)
        
        # Try exact match first
        if ts_key in orderbook_data:
            return orderbook_data[ts_key]
        
        # Try within 1 second window
        for delta in range(-1, 2):
            check_ts = ts_key + timedelta(seconds=delta)
            if check_ts in orderbook_data:
                return orderbook_data[check_ts]
        
        return None

    def _build_market_snapshot(
        self,
        event: Dict[str, Any],
        symbol: str,
        orderbook: Optional[Dict[str, Any]],
        amt_levels: Dict[str, float],
    ) -> Optional[MarketSnapshot]:
        """Build a proper MarketSnapshot object like the live bot does.
        
        Uses data from:
        - decision_event payload (snapshot, metrics, resolved_params) - if available
        - orderbook_events (bid_depth_usd, ask_depth_usd, orderbook_imbalance)
        - AMT calculations from candles (POC, VAH, VAL)
        
        Note: decision_events may not have rich snapshot data. In that case,
        we build the snapshot primarily from orderbook_events and candle data.
        """
        payload = event.get("payload", {})
        snapshot_data = payload.get("snapshot", {})
        metrics = payload.get("metrics", {})
        resolved_params = payload.get("resolved_params", {})
        
        # Extract price - try multiple sources
        price = snapshot_data.get("mid_price")
        if not price and orderbook:
            # Try to get price from orderbook
            bid = orderbook.get("bid") or orderbook.get("best_bid")
            ask = orderbook.get("ask") or orderbook.get("best_ask")
            if bid and ask:
                price = (bid + ask) / 2
            elif bid:
                price = bid
            elif ask:
                price = ask
        if not price:
            # Try to get price from payload directly (some formats store it at top level)
            price = payload.get("price") or payload.get("mid_price")
        if not price:
            return None
        
        ts = event["ts"]
        timestamp_ns = int(ts.timestamp() * 1e9)
        
        # Get spread from snapshot or calculate from orderbook
        # CRITICAL: Validate spread_bps - historical data may contain invalid negative values
        # (Bug existed on 2026-01-13 08:00-17:00 UTC where ~216k records had negative spread_bps)
        spread_bps = snapshot_data.get("spread_bps", 0)
        if spread_bps <= 0 and orderbook:
            bid = orderbook.get("bid") or orderbook.get("best_bid")
            ask = orderbook.get("ask") or orderbook.get("best_ask")
            if bid and ask and price > 0:
                spread_bps = (ask - bid) / price * 10000
        
        # Final validation: spread_bps must be positive, default to 5.0 bps if invalid
        if spread_bps <= 0:
            spread_bps = 5.0  # Default spread for invalid/missing data
        # Clamp to reasonable range [0.1, 100.0] bps
        spread_bps = max(0.1, min(100.0, spread_bps))
        
        # Get depth from orderbook events (real data) or fall back to metrics
        if orderbook:
            bid_depth_usd = orderbook.get("bid_depth_usd", 0)
            ask_depth_usd = orderbook.get("ask_depth_usd", 0)
            orderbook_imbalance = orderbook.get("orderbook_imbalance", 0)
        else:
            bid_depth_usd = metrics.get("bid_depth_usd", 0)
            ask_depth_usd = metrics.get("ask_depth_usd", 0)
            total_depth = bid_depth_usd + ask_depth_usd
            orderbook_imbalance = (bid_depth_usd - ask_depth_usd) / total_depth if total_depth > 0 else 0
        
        # Floor depth to avoid "Depth Too Thin" rejections when orderbook data is missing
        if bid_depth_usd <= 0:
            bid_depth_usd = 50000.0
        if ask_depth_usd <= 0:
            ask_depth_usd = 50000.0
        
        # Calculate depth imbalance
        total_depth = bid_depth_usd + ask_depth_usd
        depth_imbalance = (bid_depth_usd - ask_depth_usd) / total_depth if total_depth > 0 else 0
        
        # Get orderflow imbalance from snapshot (multi-timeframe)
        imb_1s = snapshot_data.get("imb_1s", 0)
        imb_5s = snapshot_data.get("imb_5s", 0)
        imb_30s = snapshot_data.get("imb_30s", 0)
        
        # Get volatility data from snapshot
        vol_regime = snapshot_data.get("vol_regime", "normal")
        vol_shock = snapshot_data.get("vol_shock", False)
        trend_direction = snapshot_data.get("trend_direction", "flat")
        trend_strength = snapshot_data.get("trend_strength", 0)
        
        # Get AMT levels from real calculation (or fall back to snapshot if available)
        poc_price = amt_levels.get("point_of_control") or snapshot_data.get("poc_price")
        vah_price = amt_levels.get("value_area_high") or snapshot_data.get("vah_price")
        val_price = amt_levels.get("value_area_low") or snapshot_data.get("val_price")
        
        # Determine position in value
        if poc_price and vah_price and val_price:
            if price > vah_price:
                position_in_value = "above"
            elif price < val_price:
                position_in_value = "below"
            else:
                position_in_value = "inside"
        else:
            position_in_value = snapshot_data.get("position_in_value", "inside")
        
        # Get data quality and snapshot age
        data_quality_score = snapshot_data.get("data_quality_score", 1.0)
        snapshot_age_ms = 0.0  # Historical data has no meaningful "age"
        
        # Get typical spread from resolved params
        typical_spread_bps = resolved_params.get("typical_spread_bps", spread_bps)
        
        # Estimate slippage based on spread and depth
        expected_slippage = spread_bps / 2.0
        min_depth = min(bid_depth_usd, ask_depth_usd) if bid_depth_usd > 0 and ask_depth_usd > 0 else 0
        if min_depth < 10000 and min_depth > 0:
            expected_slippage += (10000 - min_depth) / 10000 * 2.0
        
        # Get bid/ask from orderbook if available, otherwise estimate from spread
        if orderbook:
            bid = orderbook.get("bid") or orderbook.get("best_bid") or (price - (price * spread_bps / 20000))
            ask = orderbook.get("ask") or orderbook.get("best_ask") or (price + (price * spread_bps / 20000))
        else:
            bid = price - (price * spread_bps / 20000)
            ask = price + (price * spread_bps / 20000)
        
        # Build MarketSnapshot (same structure as live bot)
        return MarketSnapshot(
            symbol=symbol,
            exchange="bybit",
            timestamp_ns=timestamp_ns,
            snapshot_age_ms=snapshot_age_ms,
            mid_price=price,
            bid=bid,
            ask=ask,
            spread_bps=spread_bps,
            bid_depth_usd=bid_depth_usd,
            ask_depth_usd=ask_depth_usd,
            depth_imbalance=depth_imbalance,
            imb_1s=imb_1s,
            imb_5s=imb_5s,
            imb_30s=imb_30s,
            orderflow_persistence_sec=0,  # Not available in historical data
            rv_1s=0,  # Would need tick data to calculate
            rv_10s=0,
            rv_1m=0,
            vol_shock=vol_shock,
            vol_regime=vol_regime,
            vol_regime_score=self._vol_regime_to_score(vol_regime),
            trend_direction=trend_direction,
            trend_strength=trend_strength,
            poc_price=poc_price,
            vah_price=vah_price,
            val_price=val_price,
            position_in_value=position_in_value,
            expected_fill_slippage_bps=expected_slippage,
            typical_spread_bps=typical_spread_bps,
            data_quality_score=data_quality_score,
            ws_connected=True,  # Historical data is always "connected"
            # Split rotation signals (Strategy Signal Architecture Fixes - Requirement 3.11)
            # In backtest, we don't have EWMA state, so use defaults
            # flow_rotation and trend_bias will be calculated by AMTCalculatorStage if used
            flow_rotation=0.0,
            trend_bias=0.0,
        )
    
    def _vol_regime_to_score(self, regime: str) -> float:
        """Convert volatility regime string to numeric score."""
        regime_scores = {
            "low": 0.2,
            "normal": 0.5,
            "high": 0.8,
            "extreme": 1.0,
            "unknown": 0.5,
        }
        return regime_scores.get(regime, 0.5)
    
    def _build_features_from_snapshot(
        self,
        snapshot: MarketSnapshot,
        symbol: str,
    ) -> Features:
        """Build Features object from MarketSnapshot.
        
        Requirements 7.1, 7.2, 7.3, 7.4, 7.5:
        - Populate distance_to_val, distance_to_vah, distance_to_poc from snapshot (using _bps suffixed fields)
        - Populate value_area_low, value_area_high, point_of_control from snapshot
        - Populate position_in_value and rotation_factor from snapshot
        
        Uses values directly from MarketSnapshot when available (non-zero),
        with fallback calculation for backward compatibility when snapshot
        fields are 0.0 (default).
        """
        price = snapshot.mid_price
        
        # Use distance fields from snapshot if available (non-zero),
        # otherwise calculate for backward compatibility
        # Requirement 7.1: distance_to_val_bps, distance_to_vah_bps, distance_to_poc_bps
        if snapshot.distance_to_vah_bps != 0.0:
            distance_to_vah = snapshot.distance_to_vah_bps
        else:
            distance_to_vah = abs(snapshot.vah_price - price) if snapshot.vah_price else 0.0
        
        if snapshot.distance_to_val_bps != 0.0:
            distance_to_val = snapshot.distance_to_val_bps
        else:
            distance_to_val = abs(price - snapshot.val_price) if snapshot.val_price else 0.0
        
        if snapshot.distance_to_poc_bps != 0.0:
            distance_to_poc = snapshot.distance_to_poc_bps
        else:
            distance_to_poc = (price - snapshot.poc_price) if snapshot.poc_price else 0.0
        
        # Use rotation_factor from snapshot if available (non-zero),
        # otherwise calculate for backward compatibility
        # Requirement 7.4: rotation_factor
        if snapshot.rotation_factor != 0.0:
            rotation_factor = snapshot.rotation_factor
        else:
            # Fallback calculation from orderflow imbalance
            rotation_factor = snapshot.imb_5s * 5  # Scale to rotation range
            if snapshot.trend_direction == "up":
                rotation_factor += snapshot.trend_strength * 5
            elif snapshot.trend_direction == "down":
                rotation_factor -= snapshot.trend_strength * 5
        
        return Features(
            symbol=symbol,
            price=price,
            spread=snapshot.spread_bps / 10000,  # Convert bps to decimal
            rotation_factor=rotation_factor,
            position_in_value=snapshot.position_in_value,
            timestamp=snapshot.timestamp_ns / 1e9,
            distance_to_val=distance_to_val,
            distance_to_vah=distance_to_vah,
            distance_to_poc=distance_to_poc,
            value_area_low=snapshot.val_price,
            value_area_high=snapshot.vah_price,
            point_of_control=snapshot.poc_price,
            atr_5m=price * 0.005,  # Estimate ATR as 0.5% of price
            atr_5m_baseline=price * 0.005,
            bid_depth_usd=snapshot.bid_depth_usd,
            ask_depth_usd=snapshot.ask_depth_usd,
            orderbook_imbalance=snapshot.depth_imbalance,
            orderflow_imbalance=snapshot.depth_imbalance,  # Use depth imbalance as proxy for orderflow
            # Trend indicators (Requirement 3.2)
            trend_direction=snapshot.trend_direction or "flat",
            trend_strength=snapshot.trend_strength or 0.0,
        )
    
    def _build_context_from_snapshot(
        self,
        snapshot: MarketSnapshot,
        symbol: str,
    ) -> ContextVector:
        """Build ContextVector from MarketSnapshot for profile routing.
        
        Uses the unified build_context_vector() function to ensure parity
        between live and backtest context construction.
        
        Context Vector Parity (Requirements 1-6):
        - Derives regime_family from market_regime via RegimeMapper logic
        - Validates spread_bps to [0.1, 100.0] range
        - Calculates expected_cost_bps = spread + fees + slippage
        - Derives ema_spread_pct from trend_direction and trend_strength
        - Derives atr_ratio from vol_regime
        """
        from quantgambit.deeptrader_core.profiles.context_vector import (
            ContextVectorInput,
            ContextVectorConfig,
            build_context_vector,
        )
        
        ts = datetime.fromtimestamp(snapshot.timestamp_ns / 1e9, tz=timezone.utc)
        
        # Calculate total depth for TPS estimation
        total_depth = snapshot.bid_depth_usd + snapshot.ask_depth_usd
        
        # Estimate trades_per_second based on depth (backtest doesn't have real TPS)
        estimated_tps = 1.0  # Default to 1 TPS
        if total_depth > 100000:
            estimated_tps = 5.0
        elif total_depth > 50000:
            estimated_tps = 3.0
        elif total_depth > 10000:
            estimated_tps = 1.0
        else:
            estimated_tps = 0.5
        
        # Build ContextVectorInput from MarketSnapshot
        input_data = ContextVectorInput(
            symbol=symbol,
            timestamp=snapshot.timestamp_ns / 1e9,
            price=snapshot.mid_price,
            # Orderbook data
            bid=snapshot.bid,
            ask=snapshot.ask,
            spread_bps=snapshot.spread_bps,
            bid_depth_usd=snapshot.bid_depth_usd,
            ask_depth_usd=snapshot.ask_depth_usd,
            orderbook_imbalance=snapshot.depth_imbalance,
            # Trend data
            trend_direction=snapshot.trend_direction,
            trend_strength=snapshot.trend_strength,
            # Volatility data
            vol_regime=snapshot.vol_regime,
            # Market regime - derive from vol_regime if not available
            market_regime=self._derive_market_regime_from_snapshot(snapshot),
            # AMT data
            poc_price=snapshot.poc_price,
            vah_price=snapshot.vah_price,
            val_price=snapshot.val_price,
            position_in_value=snapshot.position_in_value,
            # Data quality
            trades_per_second=estimated_tps,
            book_age_ms=0.0,  # Backtest mode skips age checks
            trade_age_ms=0.0,
            data_quality_score=snapshot.data_quality_score,
        )
        
        # Use unified builder with backtesting_mode=True
        return build_context_vector(input_data, backtesting_mode=True)
    
    def _derive_market_regime_from_snapshot(self, snapshot: MarketSnapshot) -> str:
        """Derive market_regime from snapshot data.
        
        Since historical data may not have market_regime, we derive it from
        available indicators:
        - vol_shock + high vol_regime → "breakout"
        - low vol_regime + low trend_strength → "squeeze"
        - high trend_strength → "breakout"
        - otherwise → "range"
        """
        vol_regime = snapshot.vol_regime.lower() if snapshot.vol_regime else "normal"
        trend_strength = snapshot.trend_strength if snapshot.trend_strength else 0.0
        vol_shock = snapshot.vol_shock if hasattr(snapshot, 'vol_shock') else False
        
        # Breakout: vol shock or high volatility with strong trend
        if vol_shock or (vol_regime in ["high", "extreme"] and trend_strength > 0.5):
            return "breakout"
        
        # Squeeze: low volatility with weak trend
        if vol_regime == "low" and trend_strength < 0.2:
            return "squeeze"
        
        # Strong trend without vol shock
        if trend_strength > 0.4:
            return "breakout"
        
        # Default to range
        return "range"
    
    def _apply_global_gate(
        self,
        snapshot: MarketSnapshot,
    ) -> Tuple[bool, str]:
        """Apply global gate checks like the live bot.
        
        Returns (passed, rejection_reason)
        """
        # Check spread
        if snapshot.spread_bps > self.config.max_spread_bps:
            return False, f"spread_too_wide:{snapshot.spread_bps:.1f}bps"
        
        # Check depth
        min_depth = min(snapshot.bid_depth_usd, snapshot.ask_depth_usd)
        if min_depth < self.config.min_depth_usd:
            return False, f"depth_too_thin:{min_depth:.0f}usd"
        
        # Check snapshot age
        if snapshot.snapshot_age_ms > self.config.max_snapshot_age_ms:
            return False, f"snapshot_stale:{snapshot.snapshot_age_ms:.0f}ms"
        
        # Check vol shock
        if snapshot.vol_shock:
            return False, "vol_shock"
        
        return True, ""

    def _build_execution_diagnostics(
        self,
        total_snapshots: int,
        snapshots_processed: int,
        snapshots_skipped: int,
        global_gate_rejections: int,
        rejection_breakdown: Dict[str, int],
        profiles_selected: int,
        signals_generated: int,
        cooldown_rejections: int,
        total_trades: int,
    ) -> Dict[str, Any]:
        """Build execution diagnostics with human-readable summary.
        
        Args:
            total_snapshots: Total number of snapshots in the backtest
            snapshots_processed: Number of snapshots successfully processed
            snapshots_skipped: Number of snapshots skipped (missing data)
            global_gate_rejections: Total global gate rejections
            rejection_breakdown: Dict with rejection counts by category
            profiles_selected: Number of times a profile was selected
            signals_generated: Number of signals generated
            cooldown_rejections: Number of signals blocked by cooldown
            total_trades: Number of trades executed
            
        Returns:
            Dict with execution diagnostics including summary and suggestions
        """
        primary_issue = None
        suggestions = []
        summary = ""
        
        if total_trades == 0:
            if signals_generated == 0:
                if profiles_selected == 0:
                    primary_issue = "no_profiles_matched"
                    summary = "No trading profiles matched the market conditions during this period."
                    suggestions = [
                        "Try a different date range with more varied market conditions",
                        "Check if the selected strategy is appropriate for this symbol"
                    ]
                elif global_gate_rejections > snapshots_processed * 0.8 and snapshots_processed > 0:
                    # Most snapshots rejected by safety filters
                    top_reason = max(rejection_breakdown, key=rejection_breakdown.get)
                    primary_issue = f"safety_filter_{top_reason}"
                    
                    if top_reason == "spread_too_wide":
                        summary = f"Most signals were blocked by wide spreads ({rejection_breakdown[top_reason]} rejections)."
                        suggestions = [
                            "Try a more liquid symbol or time period",
                            "Increase the max_spread_bps threshold in settings"
                        ]
                    elif top_reason == "depth_too_thin":
                        summary = f"Most signals were blocked by thin orderbook depth ({rejection_breakdown[top_reason]} rejections)."
                        suggestions = [
                            "Try a more liquid symbol",
                            "Reduce the min_depth_usd threshold"
                        ]
                    elif top_reason == "snapshot_stale":
                        summary = f"Most signals were blocked by stale data ({rejection_breakdown[top_reason]} rejections)."
                        suggestions = [
                            "Check data quality for this time period",
                            "Increase the max_snapshot_age_ms threshold"
                        ]
                    elif top_reason == "vol_shock":
                        summary = f"Most signals were blocked by volatility shocks ({rejection_breakdown[top_reason]} rejections)."
                        suggestions = [
                            "This period had high volatility - try a calmer market period",
                            "Consider strategies designed for high volatility"
                        ]
                    else:
                        summary = f"Most signals were blocked by safety filters ({global_gate_rejections} rejections)."
                        suggestions = [
                            "Review safety filter thresholds",
                            "Try a different time period"
                        ]
                else:
                    primary_issue = "no_signals"
                    summary = "Strategies did not generate any entry signals during this period."
                    suggestions = [
                        "The market conditions may not have matched strategy entry criteria",
                        "Try a longer date range or different market conditions"
                    ]
            else:
                # Signals were generated but no trades
                if cooldown_rejections > signals_generated * 0.5:
                    primary_issue = "cooldown_blocked"
                    summary = f"Signals were generated but blocked by cooldown ({cooldown_rejections} blocked)."
                    suggestions = [
                        "Reduce the cooldown_seconds setting",
                        "Try a longer date range"
                    ]
                else:
                    primary_issue = "signals_not_executed"
                    summary = f"{signals_generated} signals were generated but none resulted in trades."
                    suggestions = [
                        "Check position sizing and risk limits",
                        "Review strategy exit conditions"
                    ]
        else:
            summary = f"Backtest completed with {total_trades} trades."
        
        return {
            "total_snapshots": total_snapshots,
            "snapshots_processed": snapshots_processed,
            "snapshots_skipped": snapshots_skipped,
            "global_gate_rejections": global_gate_rejections,
            "rejection_breakdown": rejection_breakdown,
            "profiles_selected": profiles_selected,
            "signals_generated": signals_generated,
            "cooldown_rejections": cooldown_rejections,
            "summary": summary,
            "primary_issue": primary_issue,
            "suggestions": suggestions,
        }

    async def _run_strategy_simulation(
        self,
        run_id: str,
        events: List[Dict[str, Any]],
        orderbook_data: Dict[datetime, Dict[str, Any]],
        candle_data: List[Dict[str, Any]],
        config: Dict[str, Any],
        warm_start_state: Optional[WarmStartState] = None,
    ) -> Dict[str, Any]:
        """Run strategy simulation on historical events using DecisionEngine pipeline.
        
        Pipeline Unification (Requirements 1.1, 1.2, 1.3):
        - Routes all decisions through DecisionEngine with backtesting_mode=True
        - Applies all loss prevention stages (StrategyTrendAlignmentStage, EVGateStage, etc.)
        - Uses TrendCalculator to fix unreliable trend_direction in historical data
        
        Warm Start Support (Requirements 3.1):
        - If warm_start_state is provided, initializes positions, account state,
          and candle cache from the warm start state
        """
        symbol = config.get("symbol")
        exchange = _normalize_exchange_name(config.get("exchange"))
        initial_capital = config.get("initial_capital", 10000.0)
        maker_fee_bps, taker_fee_bps, fee_source = _resolve_fee_bps(config, exchange)
        slippage_model_name = (config.get("slippage_model") or os.getenv("BACKTEST_SLIPPAGE_MODEL", "fixed")).lower()
        slippage_model = SlippageModel() if slippage_model_name in {"adaptive", "market", "symbol"} else None
        
        # Fee calculation — use maker fees when maker execution is configured
        entry_mode = os.getenv("ENTRY_EXECUTION_MODE", "market").lower()
        if entry_mode in ("maker_post_only", "limit", "post_only_limit", "maker_limit"):
            fee_rate = maker_fee_bps / 10000
        else:
            fee_rate = taker_fee_bps / 10000

        if fee_source != "explicit":
            logger.info(
                "backtest_fee_model_resolved",
                extra={
                    "exchange": exchange,
                    "maker_fee_bps": maker_fee_bps,
                    "taker_fee_bps": taker_fee_bps,
                    "source": fee_source,
                },
            )
        
        # CRITICAL: Create a fresh DegradationManager for backtesting with NO upgrade cooldown
        # The singleton DegradationManager has state that persists across runs,
        # and the upgrade_cooldown_sec prevents mode transitions.
        # In backtesting, we process events quickly (not real-time), so the
        # cooldown never expires and the system stays stuck in NO_ENTRIES mode.
        from quantgambit.risk.degradation import (
            DegradationManager, DegradationConfig, set_degradation_manager
        )
        backtest_degradation_config = DegradationConfig(
            upgrade_cooldown_sec=0.0,  # No cooldown in backtesting - events are not real-time
        )
        backtest_degradation_manager = DegradationManager(backtest_degradation_config)
        set_degradation_manager(backtest_degradation_manager)
        logger.info(f"Created fresh DegradationManager for backtesting (no upgrade cooldown)")
        
        # CRITICAL: Create and warm up SymbolCharacteristicsService from historical data
        # This ensures symbol-adaptive parameters (min_distance_from_poc_pct, etc.) are
        # calculated from actual market data, matching live trading behavior.
        # Without warmup, the service uses conservative defaults (3% daily range) which
        # causes strategies to reject signals for symbols with smaller typical ranges.
        from quantgambit.signals.services.symbol_characteristics import SymbolCharacteristicsService
        
        symbol_characteristics_service = SymbolCharacteristicsService()
        warmup_samples = min(100, len(events))  # Use first 100 events or all if fewer
        
        # Collect prices to estimate ATR if not available in events
        prices = []
        for event in events[:warmup_samples]:
            payload = event.get("payload", {})
            snapshot = payload.get("snapshot", {})
            metrics = payload.get("metrics", {})
            price = snapshot.get("mid_price") or metrics.get("price") or 0.0
            if price > 0:
                prices.append(price)
        
        # Estimate ATR from price range if we have enough prices
        # ATR is typically ~1-2% of price for BTC in normal conditions
        estimated_atr = 0.0
        if len(prices) >= 10:
            price_range = max(prices) - min(prices)
            avg_price = sum(prices) / len(prices)
            # Use price range as a proxy for ATR (conservative estimate)
            # Scale up since we're only looking at a short window
            estimated_atr = price_range * 2  # Double the observed range as ATR estimate
            if estimated_atr == 0 and avg_price > 0:
                # If no price movement, use 0.5% of price as minimum ATR
                estimated_atr = avg_price * 0.005
        
        logger.info(f"Warming up SymbolCharacteristicsService with {warmup_samples} events (estimated_atr={estimated_atr:.2f})")
        for event in events[:warmup_samples]:
            # Extract market data from event for warmup
            payload = event.get("payload", {})
            snapshot = payload.get("snapshot", {})
            metrics = payload.get("metrics", {})
            
            # Get spread in bps
            spread_bps = snapshot.get("spread_bps")
            if spread_bps is None:
                mid_price = snapshot.get("mid_price") or metrics.get("price")
                bid = snapshot.get("bid") or metrics.get("bid")
                ask = snapshot.get("ask") or metrics.get("ask")
                if mid_price and bid and ask and mid_price > 0:
                    spread_bps = (ask - bid) / mid_price * 10000
                else:
                    spread_bps = 5.0  # Default
            
            # Get depth
            bid_depth = metrics.get("bid_depth_usd") or 50000.0
            ask_depth = metrics.get("ask_depth_usd") or 50000.0
            min_depth = min(bid_depth, ask_depth)
            
            # Get ATR and price - use estimated ATR if not available
            atr = metrics.get("atr_5m") or snapshot.get("atr_5m") or estimated_atr
            price = snapshot.get("mid_price") or metrics.get("price") or 0.0
            
            # Get volatility regime
            vol_regime = snapshot.get("vol_regime") or "normal"
            
            # Update service if we have valid data
            if price > 0 and spread_bps > 0:
                symbol_characteristics_service.update(
                    symbol=symbol,
                    spread_bps=spread_bps,
                    min_depth_usd=min_depth,
                    atr=atr,
                    price=price,
                    volatility_regime=vol_regime,
                )
        
        # Log the warmed-up characteristics
        chars = symbol_characteristics_service.get_characteristics(symbol)
        logger.info(
            f"SymbolCharacteristicsService warmed up: "
            f"typical_spread_bps={chars.typical_spread_bps:.2f}, "
            f"typical_depth_usd={chars.typical_depth_usd:.0f}, "
            f"typical_daily_range_pct={chars.typical_daily_range_pct:.4f}, "
            f"sample_count={chars.sample_count}"
        )
        
        # CRITICAL: Create and populate CandleCache for AMT calculations
        # The AMTCalculatorStage in the DecisionEngine pipeline needs candle data
        # to calculate POC, VAH, VAL levels. Without this, all AMT calculations fail.
        candle_cache = CandleCache(max_candles=self.config.amt_lookback_candles + 100)
        for candle in candle_data:
            candle_cache.add_candle(symbol, candle)
        logger.info(
            f"Populated CandleCache with {candle_cache.get_candle_count(symbol)} candles for {symbol}"
        )
        
        # Create DecisionEngine with backtesting_mode=True (Requirement 1.2)
        # This ensures the same pipeline stages are applied as in live trading
        # Use EVGateConfig and EVPositionSizerConfig to avoid deprecated stages
        # Disable execution depth check for backtesting — historical depth data is incomplete
        os.environ["EXECUTION_MIN_DEPTH_USD"] = "0"
        
        # Apply profile parameter overrides from backtest config
        # This allows testing different risk parameters without editing code
        profile_overrides = config.get("profile_overrides", {})
        if profile_overrides:
            logger.info(f"Applying profile overrides: {profile_overrides}")
            for key, value in profile_overrides.items():
                # Convert to env var format: risk_per_trade_pct -> PROFILE_OVERRIDE_RISK_PER_TRADE_PCT
                env_key = f"PROFILE_OVERRIDE_{key.upper()}"
                os.environ[env_key] = str(value)
        
        decision_engine = DecisionEngine(
            backtesting_mode=True,
            use_gating_system=True,
            # Pass the candle cache for AMT calculations
            candle_cache=candle_cache,
            # Pass the warmed-up symbol characteristics service
            # This ensures symbol-adaptive parameters are based on actual market data
            symbol_characteristics_service=symbol_characteristics_service,
            # Use relaxed data readiness config for historical data
            data_readiness_config=DataReadinessConfig(
                max_trade_age_sec=float('inf'),  # Historical data has no "age"
                max_orderbook_feed_age_sec=float('inf'),
                min_bid_depth_usd=0,  # Don't reject on depth in data readiness
                min_ask_depth_usd=0,
            ),
            # Use relaxed global gate config - let pipeline stages do filtering
            global_gate_config=GlobalGateConfig(
                max_spread_bps=self.config.max_spread_bps,
                min_depth_per_side_usd=0,  # Don't reject on depth in backtesting
                snapshot_age_block_ms=float('inf'),  # Historical data has no "age"
                block_on_vol_shock=True,
                depth_typical_multiplier=None,  # Disable multiplier-based depth check
            ),
            # Use EVGateConfig with relaxed data freshness for backtesting
            # Historical data will have stale timestamps, so we increase the max age limits
            ev_gate_config=EVGateConfig(
                max_book_age_ms=86400000,  # 24 hours - historical data is always "stale"
                max_spread_age_ms=86400000,  # 24 hours
                mode="shadow",  # Don't reject in backtesting — no calibrated p_hat available
            ),
            # Disable session preference enforcement in backtesting
            # so all strategies are tested regardless of time-of-day preferences
            session_filter_config=SessionFilterConfig(
                enforce_session_preferences=False,
            ),
            # Use EVPositionSizerConfig with default settings
            ev_position_sizer_config=EVPositionSizerConfig(
                enabled=True,
            ),
        )
        
        # Create BacktestDecisionAdapter (Requirement 1.1)
        trend_calculator = get_trend_calculator()
        context_builder = get_stage_context_builder()
        decision_adapter = BacktestDecisionAdapter(
            decision_engine=decision_engine,
            trend_calculator=trend_calculator,
            context_builder=context_builder,
        )
        
        # Stage rejection diagnostics (Requirement 4.1, 4.2, 4.3)
        stage_diagnostics = StageRejectionDiagnostics()
        
        # Initialize ExecutionSimulator for realistic fill simulation
        # Feature: trading-pipeline-integration
        # Requirements: 5.1 - THE System SHALL simulate partial fills based on order
        # size relative to available liquidity
        # Requirements: 5.2 - WHEN simulating execution THEN the System SHALL apply
        # realistic latency based on historical exchange response times
        # Requirements: 5.5 - THE System SHALL support configurable execution scenarios
        # (optimistic, realistic, pessimistic)
        execution_scenario = config.get("execution_scenario", self.config.execution_scenario)
        
        # Handle case where execution_scenario might be a dict (from frontend config)
        # Extract the scenario string if it's a dict with a 'scenario' or 'name' key
        if isinstance(execution_scenario, dict):
            execution_scenario = execution_scenario.get("scenario") or execution_scenario.get("name") or "realistic"
        
        # Ensure it's a string
        if not isinstance(execution_scenario, str):
            logger.warning(f"Invalid execution_scenario type {type(execution_scenario)}, using 'realistic'")
            execution_scenario = "realistic"
        
        execution_simulator: Optional[ExecutionSimulator] = None
        execution_overrides: Dict[str, Any] = {}
        if isinstance(config.get("execution_overrides"), dict):
            execution_overrides.update(config.get("execution_overrides") or {})
        if "execution_latency_ms" in config:
            execution_overrides["base_latency_ms"] = float(config["execution_latency_ms"])
            execution_overrides.setdefault("latency_std_ms", 0.0)
        if "execution_slippage_bps" in config:
            execution_overrides["base_slippage_bps"] = float(config["execution_slippage_bps"])
        
        try:
            exec_config = ExecutionSimulatorConfig.from_scenario(execution_scenario)
            if execution_overrides:
                exec_config_data = asdict(exec_config)
                exec_config_data.update(execution_overrides)
                exec_config = ExecutionSimulatorConfig(**exec_config_data)
            execution_simulator = ExecutionSimulator(exec_config)
            seed = config.get("execution_simulator_seed")
            if seed is not None:
                execution_simulator.seed(int(seed))
            logger.info(
                f"Initialized ExecutionSimulator with scenario '{execution_scenario}': "
                f"base_latency={exec_config.base_latency_ms}ms, "
                f"base_slippage={exec_config.base_slippage_bps}bps"
            )
        except ValueError as e:
            logger.warning(
                f"Invalid execution_scenario '{execution_scenario}', using simple fill logic: {e}"
            )
        
        # Execution metrics tracking
        # Requirements: 5.6 - Track execution metrics for comparison
        total_simulated_slippage_bps = 0.0
        total_simulated_latency_ms = 0.0
        partial_fill_count = 0
        total_fills = 0
        
        # Simulation state
        equity = initial_capital
        peak_equity = initial_capital
        max_drawdown = 0.0
        trades: List[Dict[str, Any]] = []
        equity_curve: List[Dict[str, Any]] = []
        
        # Position tracking
        position = None
        last_exit_ts = None  # for cooldown enforcement
        min_cooldown_sec = float(os.getenv("COOLDOWN_ENTRY_SEC", "45"))
        
        # Warm start initialization
        # Feature: trading-pipeline-integration
        # Requirements: 3.1 - THE System SHALL support initializing a backtest with
        # current live positions, account state, and recent decision history
        warm_start_positions: List[Dict[str, Any]] = []
        if warm_start_state is not None:
            # Initialize equity from warm start account state
            warm_start_equity = warm_start_state.account_state.get("equity")
            if warm_start_equity and warm_start_equity > 0:
                equity = warm_start_equity
                peak_equity = warm_start_equity
                logger.info(f"Warm start: initialized equity to {equity}")
            
            # Initialize positions from warm start state
            if warm_start_state.positions:
                warm_start_positions = warm_start_state.positions.copy()
                # If there's exactly one position, use it as the current position
                # (This executor currently supports single position tracking)
                if len(warm_start_positions) == 1:
                    ws_pos = warm_start_positions[0]
                    position = {
                        "side": ws_pos.get("side", "long"),
                        "entry_price": ws_pos.get("entry_price", 0),
                        "size": ws_pos.get("size", 0),
                        "entry_time": ws_pos.get("entry_time") or ws_pos.get("timestamp"),
                        "strategy_id": ws_pos.get("strategy_id", "warm_start"),
                        "profile_id": ws_pos.get("profile_id", "warm_start"),
                        "stop_loss": ws_pos.get("stop_loss", 0),
                        "take_profit": ws_pos.get("take_profit", 0),
                        "bars_held": 0,
                    }
                    logger.info(
                        f"Warm start: initialized position - "
                        f"side={position['side']}, size={position['size']}, "
                        f"entry_price={position['entry_price']}"
                    )
                elif len(warm_start_positions) > 1:
                    logger.warning(
                        f"Warm start: {len(warm_start_positions)} positions provided, "
                        f"but executor only supports single position. Using first position."
                    )
                    ws_pos = warm_start_positions[0]
                    position = {
                        "side": ws_pos.get("side", "long"),
                        "entry_price": ws_pos.get("entry_price", 0),
                        "size": ws_pos.get("size", 0),
                        "entry_time": ws_pos.get("entry_time") or ws_pos.get("timestamp"),
                        "strategy_id": ws_pos.get("strategy_id", "warm_start"),
                        "profile_id": ws_pos.get("profile_id", "warm_start"),
                        "stop_loss": ws_pos.get("stop_loss", 0),
                        "take_profit": ws_pos.get("take_profit", 0),
                        "bars_held": 0,
                    }
            
            # Pre-populate candle cache from warm start candle_history
            # This ensures AMT calculations have sufficient history from the start
            if warm_start_state.candle_history:
                warm_start_candles = warm_start_state.candle_history.get(symbol, [])
                for candle in warm_start_candles:
                    candle_cache.add_candle(symbol, candle)
                logger.info(
                    f"Warm start: pre-populated candle cache with {len(warm_start_candles)} candles "
                    f"(total: {candle_cache.get_candle_count(symbol)})"
                )
        
        # Sample equity every N events
        sample_interval = max(1, len(events) // 500)
        
        # Account state for strategies
        account = AccountState(
            equity=equity,
            daily_pnl=0.0,
            max_daily_loss=initial_capital * 0.02,
            open_positions=1 if position else 0,
            symbol_open_positions=1 if position else 0,
            symbol_daily_pnl=0.0,
        )
        
        # Statistics
        signals_generated = 0
        pipeline_decisions = 0
        snapshots_processed = 0
        snapshots_skipped = 0
        
        # AMT reconstruction tracking (Requirements 8.1, 8.3, 8.4)
        amt_from_events = 0
        amt_reconstructed = 0
        amt_unavailable = 0
        
        # Check first event to determine if AMT reconstruction will be needed
        if events:
            first_event_amt = self._get_amt_from_decision_event(events[0])
            if first_event_amt is None:
                logger.info(
                    f"amt_reconstruction_enabled: decision_events lack AMT fields, "
                    f"will reconstruct from {len(candle_data)} candles"
                )
            else:
                logger.info(
                    f"amt_fields_present: decision_events contain AMT fields, "
                    f"reconstruction not needed"
                )
        
        # Track rejection reasons by category (legacy format for backwards compatibility)
        rejection_breakdown = {
            "spread_too_wide": 0,
            "depth_too_thin": 0,
            "snapshot_stale": 0,
            "vol_shock": 0,
        }
        
        for i, event in enumerate(events):
            ts = event["ts"]
            
            # Requirement 8.1: Check if decision_events have AMT fields first
            # Only reconstruct from candles if AMT fields are missing
            amt_levels = self._get_amt_from_decision_event(event)
            
            if amt_levels is None:
                # AMT fields not in decision_event, reconstruct from candle data
                # Requirement 8.2: Use same algorithm as live AMTCalculatorStage
                amt_levels = self._calculate_amt_levels(candle_data, ts)
                if amt_levels:
                    amt_reconstructed += 1
                    if amt_reconstructed == 1:
                        # Log first reconstruction with details
                        logger.info(
                            f"amt_reconstruction_from_candles: "
                            f"first reconstruction at {ts} - POC={amt_levels.get('point_of_control'):.2f}, "
                            f"VAH={amt_levels.get('value_area_high'):.2f}, "
                            f"VAL={amt_levels.get('value_area_low'):.2f}"
                        )
                else:
                    # Requirement 8.4: Track when candle data unavailable
                    amt_unavailable += 1
            else:
                amt_from_events += 1
            
            # Get orderbook data at this timestamp
            orderbook = self._get_orderbook_at_time(orderbook_data, ts)
            
            # Build MarketSnapshot (like live bot)
            snapshot = self._build_market_snapshot(event, symbol, orderbook, amt_levels)
            if not snapshot:
                # Track skipped snapshot in runtime quality
                self._runtime_tracker.record_skipped()
                snapshots_skipped += 1
                continue
            
            price = snapshot.mid_price
            snapshots_processed += 1
            
            # Track runtime quality metrics
            has_price = price is not None and price > 0
            has_depth = snapshot.bid_depth_usd > 0 or snapshot.ask_depth_usd > 0
            has_orderbook = orderbook is not None
            self._runtime_tracker.record_snapshot(
                has_price=has_price,
                has_depth=has_depth,
                has_orderbook=has_orderbook,
            )
            
            # Build features
            features = self._build_features_from_snapshot(snapshot, symbol)
            
            # Update account state
            account = AccountState(
                equity=equity,
                daily_pnl=equity - initial_capital,
                max_daily_loss=initial_capital * 0.02,
                open_positions=1 if position else 0,
                symbol_open_positions=1 if position else 0,
                symbol_daily_pnl=equity - initial_capital,
            )
            
            # Get candle history for trend calculation
            candle_history = [c for c in candle_data if c["ts"] <= ts][-50:]  # Last 50 candles
            
            # Convert amt_levels dict to AMTLevels dataclass for pipeline
            # This allows the AMTCalculatorStage to skip recalculation
            amt_levels_obj = None
            if amt_levels:
                import time as time_module
                amt_levels_obj = AMTLevels(
                    point_of_control=amt_levels.get("point_of_control", 0),
                    value_area_high=amt_levels.get("value_area_high", 0),
                    value_area_low=amt_levels.get("value_area_low", 0),
                    position_in_value=snapshot.position_in_value or "inside",
                    distance_to_poc=getattr(features, "distance_to_poc", 0) or 0,
                    distance_to_vah=getattr(features, "distance_to_vah", 0) or 0,
                    distance_to_val=getattr(features, "distance_to_val", 0) or 0,
                    rotation_factor=getattr(features, "rotation_factor", 0) or 0,
                    candle_count=len(candle_history),
                    calculation_ts=time_module.time(),
                )
            
            # Route through DecisionEngine pipeline (Requirement 1.1)
            # Only process entry signals when flat and cooldown elapsed
            if position is None:
                # Enforce cooldown between trades using historical timestamps
                if last_exit_ts is not None:
                    secs_since_exit = (ts - last_exit_ts).total_seconds()
                    if secs_since_exit < min_cooldown_sec:
                        continue
                
                pipeline_decisions += 1
                
                # Process through BacktestDecisionAdapter
                decision_result = await decision_adapter.process_snapshot(
                    symbol=symbol,
                    snapshot=snapshot,
                    features=features,
                    account_state=account,
                    positions=[],
                    candle_history=candle_history,
                    amt_levels=amt_levels_obj,
                )
                
                if decision_result.should_trade and decision_result.signal:
                    signals_generated += 1
                    signal = decision_result.signal
                    
                    # Extract signal details
                    side = signal.get("side", "long")
                    size = signal.get("size", equity * 0.1 / price)
                    stop_loss = signal.get("stop_loss", price * 0.99 if side == "long" else price * 1.01)
                    take_profit = signal.get("take_profit", price * 1.01 if side == "long" else price * 0.99)
                    strategy_id = signal.get("strategy_id", "unknown")
                    
                    # Enter position using ExecutionSimulator for realistic fills
                    # Feature: trading-pipeline-integration
                    # Requirements: 5.1 - THE System SHALL simulate partial fills based on
                    # order size relative to available liquidity
                    # Requirements: 5.2 - WHEN simulating execution THEN the System SHALL
                    # apply realistic latency based on historical exchange response times
                    # Requirements: 5.4 - WHEN simulating slippage THEN the System SHALL
                    # use the same slippage model as live trading with historical calibration
                    actual_size = min(size, equity * 0.1 / price)
                    order_size_usd = actual_size * price if price > 0 else None
                    entry_slippage_bps = _resolve_slippage_bps(
                        config=config,
                        exchange=exchange,
                        symbol=symbol,
                        spread_bps=snapshot.spread_bps,
                        bid_depth_usd=snapshot.bid_depth_usd,
                        ask_depth_usd=snapshot.ask_depth_usd,
                        volatility_regime=snapshot.vol_regime,
                        order_size_usd=order_size_usd,
                        slippage_model=slippage_model,
                    )
                    entry_latency_ms = 0.0
                    entry_is_partial = False
                    
                    if execution_simulator:
                        # Use ExecutionSimulator for realistic fill simulation
                        entry_fill = execution_simulator.simulate_fill(
                            side=side,
                            size=actual_size,
                            price=price,
                            bid_depth_usd=snapshot.bid_depth_usd,
                            ask_depth_usd=snapshot.ask_depth_usd,
                            spread_bps=snapshot.spread_bps,
                            is_maker=signal.get("is_maker", False),
                            base_slippage_bps=entry_slippage_bps,
                        )
                        
                        entry_price = entry_fill.fill_price
                        actual_size = entry_fill.filled_size
                        entry_slippage_bps = entry_fill.slippage_bps
                        entry_latency_ms = entry_fill.latency_ms
                        entry_is_partial = entry_fill.is_partial
                        
                        # Track execution metrics
                        total_fills += 1
                        total_simulated_slippage_bps += abs(entry_slippage_bps)
                        total_simulated_latency_ms += entry_latency_ms
                        if entry_is_partial:
                            partial_fill_count += 1
                    else:
                        # Fall back to simple fill logic for backward compatibility
                        entry_rate = entry_slippage_bps / 10000.0
                        entry_price = price * (1 + entry_rate) if side == "long" else price * (1 - entry_rate)
                    
                    position = {
                        "side": side,
                        "entry_price": entry_price,
                        "size": actual_size,
                        "entry_time": ts,
                        "strategy_id": strategy_id,
                        "profile_id": signal.get("profile_id", "unknown"),
                        "stop_loss": stop_loss,
                        "take_profit": take_profit,
                        "bars_held": 0,
                        "max_hold_sec": signal.get("max_hold_sec") or 120.0,
                        "peak_pnl_bps": 0.0,
                        # Track entry execution metrics for trade record
                        "entry_slippage_bps": entry_slippage_bps,
                        "entry_latency_ms": entry_latency_ms,
                        "entry_is_partial": entry_is_partial,
                    }
                elif not decision_result.should_trade and decision_result.rejection_stage:
                    # Record rejection in diagnostics (Requirement 4.1)
                    stage_diagnostics.record_rejection(
                        stage_name=decision_result.rejection_stage,
                        reason=decision_result.rejection_reason,
                        symbol=symbol,
                    )
                    
                    # Also track in legacy format for backwards compatibility
                    reason = decision_result.rejection_reason or ""
                    if "spread" in reason.lower():
                        rejection_breakdown["spread_too_wide"] += 1
                    elif "depth" in reason.lower():
                        rejection_breakdown["depth_too_thin"] += 1
                    elif "stale" in reason.lower():
                        rejection_breakdown["snapshot_stale"] += 1
                    elif "vol_shock" in reason.lower() or "vol" in reason.lower():
                        rejection_breakdown["vol_shock"] += 1
            
            # Manage existing position (skip on entry tick)
            if position:
                position["bars_held"] += 1
                if position["bars_held"] <= 1:
                    continue  # Skip exit check on entry tick
                try:
                    hold_secs = (ts - position["entry_time"]).total_seconds()
                except (TypeError, AttributeError):
                    hold_secs = position["bars_held"] * 3.5  # fallback estimate
                max_hold = position.get("max_hold_sec") or 120.0
                
                # Track MFE for trailing/breakeven logic
                entry_p = position["entry_price"]
                if position["side"] == "long":
                    pnl_bps = (price - entry_p) / entry_p * 10000
                else:
                    pnl_bps = (entry_p - price) / entry_p * 10000
                peak = position.get("peak_pnl_bps", 0.0)
                if pnl_bps > peak:
                    peak = pnl_bps
                    position["peak_pnl_bps"] = peak
                
                should_exit = False
                exit_reason = ""
                
                sl = position["stop_loss"]
                tp = position["take_profit"]
                
                # Guard thresholds from env (match live position_guard_worker)
                trailing_activation = float(os.getenv("POSITION_GUARD_TRAILING_ACTIVATION_BPS", "10"))
                trailing_bps = float(os.getenv("POSITION_GUARD_TRAILING_BPS", "8"))
                trailing_min_hold = float(os.getenv("POSITION_GUARD_TRAILING_MIN_HOLD_SEC", "10"))
                breakeven_activation = float(os.getenv("POSITION_GUARD_BREAKEVEN_ACTIVATION_BPS", "8"))
                breakeven_buffer = float(os.getenv("POSITION_GUARD_BREAKEVEN_BUFFER_BPS", "3"))
                breakeven_min_hold = float(os.getenv("POSITION_GUARD_BREAKEVEN_MIN_HOLD_SEC", "15"))
                
                if position["side"] == "long":
                    if sl is not None and price <= sl:
                        should_exit = True
                        exit_reason = "stop_loss"
                    elif tp is not None and price >= tp:
                        should_exit = True
                        exit_reason = "take_profit"
                    elif hold_secs >= trailing_min_hold and peak >= trailing_activation and (peak - pnl_bps) >= trailing_bps:
                        should_exit = True
                        exit_reason = "trailing_stop"
                    elif hold_secs >= breakeven_min_hold and peak >= breakeven_activation and pnl_bps <= breakeven_buffer:
                        should_exit = True
                        exit_reason = "breakeven_stop"
                    elif hold_secs > max_hold:
                        should_exit = True
                        exit_reason = "time_exit"
                else:
                    if sl is not None and price >= sl:
                        should_exit = True
                        exit_reason = "stop_loss"
                    elif tp is not None and price <= tp:
                        should_exit = True
                        exit_reason = "take_profit"
                    elif hold_secs >= trailing_min_hold and peak >= trailing_activation and (peak - pnl_bps) >= trailing_bps:
                        should_exit = True
                        exit_reason = "trailing_stop"
                    elif hold_secs >= breakeven_min_hold and peak >= breakeven_activation and pnl_bps <= breakeven_buffer:
                        should_exit = True
                        exit_reason = "breakeven_stop"
                    elif hold_secs > max_hold:
                        should_exit = True
                        exit_reason = "time_exit"
                
                if should_exit:
                    # Exit position using ExecutionSimulator for realistic fills
                    # Feature: trading-pipeline-integration
                    # Requirements: 5.1, 5.2, 5.4 - Realistic execution simulation
                    exit_order_size_usd = position["size"] * price if price > 0 else None
                    exit_slippage_bps = _resolve_slippage_bps(
                        config=config,
                        exchange=exchange,
                        symbol=symbol,
                        spread_bps=snapshot.spread_bps,
                        bid_depth_usd=snapshot.bid_depth_usd,
                        ask_depth_usd=snapshot.ask_depth_usd,
                        volatility_regime=snapshot.vol_regime,
                        order_size_usd=exit_order_size_usd,
                        slippage_model=slippage_model,
                    )
                    exit_latency_ms = 0.0
                    exit_is_partial = False
                    
                    if execution_simulator:
                        # Use ExecutionSimulator for realistic fill simulation
                        exit_side = "sell" if position["side"] == "long" else "buy"
                        exit_fill = execution_simulator.simulate_fill(
                            side=exit_side,
                            size=position["size"],
                            price=price,
                            bid_depth_usd=snapshot.bid_depth_usd,
                            ask_depth_usd=snapshot.ask_depth_usd,
                            spread_bps=snapshot.spread_bps,
                            is_maker=False,  # Exits are typically taker orders
                            base_slippage_bps=exit_slippage_bps,
                        )
                        
                        exit_price = exit_fill.fill_price
                        exit_slippage_bps = exit_fill.slippage_bps
                        exit_latency_ms = exit_fill.latency_ms
                        exit_is_partial = exit_fill.is_partial
                        
                        # Track execution metrics
                        total_fills += 1
                        total_simulated_slippage_bps += abs(exit_slippage_bps)
                        total_simulated_latency_ms += exit_latency_ms
                        if exit_is_partial:
                            partial_fill_count += 1
                    else:
                        # Fall back to simple fill logic for backward compatibility
                        exit_rate = exit_slippage_bps / 10000.0
                        if position["side"] == "long":
                            exit_price = price * (1 - exit_rate)
                        else:
                            exit_price = price * (1 + exit_rate)
                    
                    # Calculate PnL
                    if position["side"] == "long":
                        pnl_pct = (exit_price - position["entry_price"]) / position["entry_price"]
                    else:
                        pnl_pct = (position["entry_price"] - exit_price) / position["entry_price"]
                    
                    trade_value = position["size"] * position["entry_price"]
                    gross_pnl = trade_value * pnl_pct
                    fees = trade_value * fee_rate * 2
                    net_pnl = gross_pnl - fees
                    
                    equity += net_pnl
                    
                    # Get entry execution metrics from position
                    entry_slippage_bps = position.get("entry_slippage_bps", 0.0)
                    entry_latency_ms = position.get("entry_latency_ms", 0.0)
                    
                    trades.append({
                        "ts": ts.isoformat(),
                        "symbol": symbol,
                        "side": position["side"],
                        "size": position["size"],
                        "entry_price": position["entry_price"],
                        "exit_price": exit_price,
                        "pnl": net_pnl,
                        "entry_fee": trade_value * fee_rate,
                        "exit_fee": trade_value * fee_rate,
                        "total_fees": fees,
                        "entry_slippage_bps": entry_slippage_bps,
                        "exit_slippage_bps": exit_slippage_bps,
                        # Execution simulation metrics
                        "entry_latency_ms": entry_latency_ms,
                        "exit_latency_ms": exit_latency_ms,
                        "entry_is_partial": position.get("entry_is_partial", False),
                        "exit_is_partial": exit_is_partial,
                        "strategy_id": position["strategy_id"],
                        "profile_id": position["profile_id"],
                        "exit_reason": exit_reason,
                    })
                    
                    last_exit_ts = ts
                    position = None
            
            # Track drawdown
            if equity > peak_equity:
                peak_equity = equity
            drawdown = (peak_equity - equity) / peak_equity
            if drawdown > max_drawdown:
                max_drawdown = drawdown
            
            # Sample equity curve
            if i % sample_interval == 0:
                equity_curve.append({
                    "ts": ts.isoformat(),
                    "equity": equity,
                    "realized_pnl": equity - initial_capital,
                    "open_positions": 1 if position else 0,
                })
        
        # Get runtime quality metrics
        runtime_metrics = self._runtime_tracker.get_metrics() if self._runtime_tracker else None
        runtime_grade = self._runtime_tracker.get_quality_grade() if self._runtime_tracker else "A"
        is_degraded = self._runtime_tracker.should_degrade_status() if self._runtime_tracker else False
        
        # Get adapter statistics
        adapter_stats = decision_adapter.get_statistics()
        
        logger.info(
            f"Strategy simulation: {signals_generated} signals from {pipeline_decisions} pipeline decisions, "
            f"{len(trades)} trades, {stage_diagnostics.total_rejections} stage rejections"
        )
        logger.info(
            f"Trend recalculations: {adapter_stats['trends_recalculated']}, "
            f"Rejections by stage: {adapter_stats['rejections_by_stage']}"
        )
        # Log AMT reconstruction statistics (Requirements 8.1, 8.3, 8.4)
        logger.info(
            f"AMT reconstruction: {amt_from_events} from events, {amt_reconstructed} reconstructed, "
            f"{amt_unavailable} unavailable"
        )
        if amt_unavailable > 0:
            logger.warning(
                f"amt_reconstruction_incomplete: {amt_unavailable} snapshots had no AMT data "
                f"(candle data unavailable)"
            )
        # Log detailed rejection reasons
        if stage_diagnostics.by_reason:
            top_reasons = stage_diagnostics.get_top_rejection_reasons(10)
            logger.info(f"Top rejection reasons: {dict(top_reasons)}")
        if runtime_metrics:
            logger.info(
                f"Runtime quality: {runtime_metrics.total_snapshots} snapshots, "
                f"{runtime_metrics.missing_price_pct:.1f}% missing price, "
                f"{runtime_metrics.missing_depth_pct:.1f}% missing depth, "
                f"degraded={is_degraded}"
            )
        
        results = self._calculate_metrics(trades, equity_curve, initial_capital, equity, max_drawdown, events)
        
        # Add runtime quality metrics to results
        results["runtime_quality"] = {
            "total_snapshots": runtime_metrics.total_snapshots if runtime_metrics else 0,
            "missing_price_count": runtime_metrics.missing_price_count if runtime_metrics else 0,
            "missing_depth_count": runtime_metrics.missing_depth_count if runtime_metrics else 0,
            "missing_price_pct": runtime_metrics.missing_price_pct if runtime_metrics else 0,
            "missing_depth_pct": runtime_metrics.missing_depth_pct if runtime_metrics else 0,
            "runtime_grade": runtime_grade,
            "is_degraded": is_degraded,
        }
        
        # Add execution simulation metrics
        # Feature: trading-pipeline-integration
        # Requirements: 5.6 - Track execution metrics for comparison
        avg_simulated_slippage_bps = (
            total_simulated_slippage_bps / total_fills if total_fills > 0 else 0.0
        )
        avg_simulated_latency_ms = (
            total_simulated_latency_ms / total_fills if total_fills > 0 else 0.0
        )
        partial_fill_rate = (
            partial_fill_count / total_fills if total_fills > 0 else 0.0
        )
        
        results["execution_simulation"] = {
            "scenario": execution_scenario,
            "total_fills": total_fills,
            "total_slippage_bps": total_simulated_slippage_bps,
            "avg_slippage_bps": avg_simulated_slippage_bps,
            "total_latency_ms": total_simulated_latency_ms,
            "avg_latency_ms": avg_simulated_latency_ms,
            "partial_fill_count": partial_fill_count,
            "partial_fill_rate": partial_fill_rate,
            "simulator_enabled": execution_simulator is not None,
        }
        
        # Log execution simulation metrics
        if execution_simulator:
            logger.info(
                f"Execution simulation ({execution_scenario}): "
                f"{total_fills} fills, avg_slippage={avg_simulated_slippage_bps:.2f}bps, "
                f"avg_latency={avg_simulated_latency_ms:.1f}ms, "
                f"partial_fill_rate={partial_fill_rate:.1%}"
            )
        
        # Add AMT reconstruction statistics (Requirements 8.1, 8.3, 8.4)
        results["amt_reconstruction"] = {
            "amt_from_events": amt_from_events,
            "amt_reconstructed": amt_reconstructed,
            "amt_unavailable": amt_unavailable,
            "reconstruction_needed": amt_reconstructed > 0 or amt_unavailable > 0,
        }
        
        # Build and add execution diagnostics with stage rejection info (Requirement 4.2)
        execution_diagnostics = self._build_execution_diagnostics(
            total_snapshots=len(events),
            snapshots_processed=snapshots_processed,
            snapshots_skipped=snapshots_skipped,
            global_gate_rejections=stage_diagnostics.global_gate,
            rejection_breakdown=rejection_breakdown,
            profiles_selected=pipeline_decisions,  # Each pipeline decision involves profile selection
            signals_generated=signals_generated,
            cooldown_rejections=stage_diagnostics.cooldown,
            total_trades=len(trades),
        )
        
        # Add stage rejection diagnostics (Requirement 4.3)
        execution_diagnostics["stage_rejections"] = stage_diagnostics.get_summary()
        execution_diagnostics["adapter_statistics"] = adapter_stats
        
        # Add AMT reconstruction info to execution diagnostics
        execution_diagnostics["amt_reconstruction"] = results["amt_reconstruction"]
        
        results["execution_diagnostics"] = execution_diagnostics
        
        return results

    def _calculate_metrics(
        self,
        trades: List[Dict[str, Any]],
        equity_curve: List[Dict[str, Any]],
        initial_capital: float,
        final_equity: float,
        max_drawdown: float,
        events: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Calculate comprehensive backtest metrics."""
        total_trades = len(trades)
        winning_trades = sum(1 for t in trades if t["pnl"] > 0)
        losing_trades = sum(1 for t in trades if t["pnl"] < 0)
        
        total_pnl = sum(t["pnl"] for t in trades)
        total_fees = sum(t["total_fees"] for t in trades)
        
        gross_profit = sum(t["pnl"] for t in trades if t["pnl"] > 0)
        gross_loss = abs(sum(t["pnl"] for t in trades if t["pnl"] < 0))
        
        win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0
        profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (float('inf') if gross_profit > 0 else 0)
        avg_trade_pnl = (total_pnl / total_trades) if total_trades > 0 else 0
        total_return_pct = ((final_equity - initial_capital) / initial_capital) * 100
        
        winning_pnls = [t["pnl"] for t in trades if t["pnl"] > 0]
        losing_pnls = [t["pnl"] for t in trades if t["pnl"] < 0]
        avg_win = (sum(winning_pnls) / len(winning_pnls)) if winning_pnls else 0
        avg_loss = (sum(losing_pnls) / len(losing_pnls)) if losing_pnls else 0
        largest_win = max(winning_pnls) if winning_pnls else 0
        largest_loss = min(losing_pnls) if losing_pnls else 0
        
        # Calculate trades per day
        if events and len(events) > 1:
            start_ts = events[0]["ts"]
            end_ts = events[-1]["ts"]
            days = (end_ts - start_ts).total_seconds() / 86400
            trades_per_day = total_trades / days if days > 0 else 0
        else:
            trades_per_day = 0
        
        fee_drag_pct = (total_fees / initial_capital) * 100 if initial_capital > 0 else 0
        
        total_slippage_cost = sum(
            t["size"] * t["entry_price"] * (t["entry_slippage_bps"] / 10000) +
            t["size"] * t["exit_price"] * (t["exit_slippage_bps"] / 10000)
            for t in trades
        )
        slippage_drag_pct = (total_slippage_cost / initial_capital) * 100 if initial_capital > 0 else 0
        
        # Calculate Sharpe ratio
        sharpe = 0.0
        sortino = 0.0
        if trades:
            trade_returns = [t["pnl"] / initial_capital for t in trades]
            avg_return = sum(trade_returns) / len(trade_returns)
            std_return = (sum((r - avg_return) ** 2 for r in trade_returns) / len(trade_returns)) ** 0.5
            sharpe = (avg_return / std_return * (252 ** 0.5)) if std_return > 0 else 0
            
            downside_returns = [r for r in trade_returns if r < 0]
            if downside_returns:
                downside_std = (sum(r ** 2 for r in downside_returns) / len(downside_returns)) ** 0.5
                sortino = (avg_return / downside_std * (252 ** 0.5)) if downside_std > 0 else 0
        
        avg_slippage_bps = 0.0
        if trades:
            avg_slippage_bps = sum(t["entry_slippage_bps"] + t["exit_slippage_bps"] for t in trades) / (2 * len(trades))
        
        symbol_metrics = self._build_symbol_metrics_payload(trades)

        return {
            "metrics": {
                "realized_pnl": total_pnl,
                "total_fees": total_fees,
                "total_trades": total_trades,
                "win_rate": win_rate,
                "max_drawdown_pct": max_drawdown * 100,
                "avg_slippage_bps": avg_slippage_bps,
                "total_return_pct": total_return_pct,
                "profit_factor": profit_factor,
                "avg_trade_pnl": avg_trade_pnl,
                "sharpe_ratio": sharpe,
                "sortino_ratio": sortino,
                "trades_per_day": trades_per_day,
                "fee_drag_pct": fee_drag_pct,
                "slippage_drag_pct": slippage_drag_pct,
                "gross_profit": gross_profit,
                "gross_loss": gross_loss,
                "avg_win": avg_win,
                "avg_loss": avg_loss,
                "largest_win": largest_win,
                "largest_loss": largest_loss,
                "winning_trades": winning_trades,
                "losing_trades": losing_trades,
            },
            "trades": trades,
            "equity_curve": equity_curve,
            "symbol_metrics": symbol_metrics,
        }

    async def _store_results(self, run_id: str, results: Dict[str, Any], quality_report: Optional[QualityReport] = None) -> None:
        """Store backtest results to the database."""
        metrics = results["metrics"]
        runtime_quality = results.get("runtime_quality", {})
        execution_diagnostics = results.get("execution_diagnostics")
        
        # Store execution diagnostics (Task 1.4)
        if execution_diagnostics:
            await self.store.write_execution_diagnostics(run_id, execution_diagnostics)
        
        # Store metrics
        metrics_record = BacktestMetricsRecord(
            run_id=run_id,
            realized_pnl=metrics["realized_pnl"],
            total_fees=metrics["total_fees"],
            total_trades=metrics["total_trades"],
            win_rate=metrics["win_rate"],
            max_drawdown_pct=metrics["max_drawdown_pct"],
            avg_slippage_bps=metrics["avg_slippage_bps"],
            total_return_pct=metrics["total_return_pct"],
            profit_factor=metrics["profit_factor"],
            avg_trade_pnl=metrics["avg_trade_pnl"],
            sharpe_ratio=metrics.get("sharpe_ratio", 0),
            sortino_ratio=metrics.get("sortino_ratio", 0),
            trades_per_day=metrics.get("trades_per_day", 0),
            fee_drag_pct=metrics.get("fee_drag_pct", 0),
            slippage_drag_pct=metrics.get("slippage_drag_pct", 0),
            gross_profit=metrics.get("gross_profit", 0),
            gross_loss=metrics.get("gross_loss", 0),
            avg_win=metrics.get("avg_win", 0),
            avg_loss=metrics.get("avg_loss", 0),
            largest_win=metrics.get("largest_win", 0),
            largest_loss=metrics.get("largest_loss", 0),
            winning_trades=metrics.get("winning_trades", 0),
            losing_trades=metrics.get("losing_trades", 0),
        )
        await self.store.write_metrics(metrics_record)
        
        # Store quality metrics if available
        if quality_report or runtime_quality:
            await self.store.write_quality_metrics(
                run_id=run_id,
                data_quality_grade=quality_report.data_quality_grade if quality_report else runtime_quality.get("runtime_grade", "A"),
                data_completeness_pct=quality_report.overall_completeness_pct if quality_report else 100.0,
                total_gaps=quality_report.total_gaps if quality_report else 0,
                critical_gaps=quality_report.critical_gaps if quality_report else 0,
                missing_price_count=runtime_quality.get("missing_price_count", 0),
                missing_depth_count=runtime_quality.get("missing_depth_count", 0),
                quality_warnings=quality_report.warnings if quality_report else [],
            )
        
        # Store trades (limit to 1000)
        for trade in results["trades"][:1000]:
            trade_record = BacktestTradeRecord(
                run_id=run_id,
                ts=trade["ts"],
                symbol=trade["symbol"],
                side=trade["side"],
                size=trade["size"],
                entry_price=trade["entry_price"],
                exit_price=trade["exit_price"],
                pnl=trade["pnl"],
                entry_fee=trade["entry_fee"],
                exit_fee=trade["exit_fee"],
                total_fees=trade["total_fees"],
                entry_slippage_bps=trade["entry_slippage_bps"],
                exit_slippage_bps=trade["exit_slippage_bps"],
                strategy_id=trade.get("strategy_id"),
                profile_id=trade.get("profile_id"),
                reason=trade.get("exit_reason"),
            )
            await self.store.write_trade(trade_record)
        
        # Store equity curve (limit to 500 points)
        for point in results["equity_curve"][:500]:
            curve_record = BacktestEquityPoint(
                run_id=run_id,
                ts=point["ts"],
                equity=point["equity"],
                realized_pnl=point["realized_pnl"],
                open_positions=point["open_positions"],
            )
            await self.store.write_equity_point(curve_record)

        symbol_records = self._build_symbol_metric_records(run_id, results["trades"])
        if symbol_records:
            await self.store.write_symbol_metrics(symbol_records)

    @staticmethod
    def _build_symbol_metrics_payload(trades: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not trades:
            return []
        buckets: Dict[str, List[Dict[str, Any]]] = {}
        for trade in trades:
            buckets.setdefault(trade.get("symbol", "unknown"), []).append(trade)
        payload: List[Dict[str, Any]] = []
        for symbol, symbol_trades in buckets.items():
            total_trades = len(symbol_trades)
            realized_pnl = sum(t.get("pnl", 0.0) for t in symbol_trades)
            total_fees = sum(t.get("total_fees", 0.0) for t in symbol_trades)
            wins = len([t for t in symbol_trades if t.get("pnl", 0.0) > 0])
            win_rate = wins / total_trades if total_trades else 0.0
            avg_trade_pnl = realized_pnl / total_trades if total_trades else 0.0
            gross_profit = sum(t.get("pnl", 0.0) for t in symbol_trades if t.get("pnl", 0.0) > 0)
            gross_loss = sum(abs(t.get("pnl", 0.0)) for t in symbol_trades if t.get("pnl", 0.0) < 0)
            profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else 0.0
            slippage_values = [
                (t.get("entry_slippage_bps", 0.0) + t.get("exit_slippage_bps", 0.0)) / 2.0
                for t in symbol_trades
            ]
            avg_slippage_bps = (sum(slippage_values) / len(slippage_values)) if slippage_values else 0.0
            payload.append(
                {
                    "symbol": symbol,
                    "realized_pnl": realized_pnl,
                    "total_fees": total_fees,
                    "total_trades": total_trades,
                    "win_rate": win_rate,
                    "avg_trade_pnl": avg_trade_pnl,
                    "profit_factor": profit_factor,
                    "avg_slippage_bps": avg_slippage_bps,
                }
            )
        return payload

    @classmethod
    def _build_symbol_metric_records(
        cls,
        run_id: str,
        trades: List[Dict[str, Any]],
    ) -> List[BacktestSymbolMetricsRecord]:
        payload = cls._build_symbol_metrics_payload(trades)
        records: List[BacktestSymbolMetricsRecord] = []
        for item in payload:
            records.append(
                BacktestSymbolMetricsRecord(
                    run_id=run_id,
                    symbol=item["symbol"],
                    realized_pnl=item["realized_pnl"],
                    total_fees=item["total_fees"],
                    total_trades=item["total_trades"],
                    win_rate=item["win_rate"],
                    avg_trade_pnl=item["avg_trade_pnl"],
                    profit_factor=item["profit_factor"],
                    avg_slippage_bps=item["avg_slippage_bps"],
                )
            )
        return records
    
    async def _update_status(
        self,
        run_id: str,
        tenant_id: str,
        bot_id: str,
        status: str,
        config: Dict[str, Any],
        started_at: str,
        finished_at: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> None:
        """Update backtest run status."""
        record = BacktestRunRecord(
            run_id=run_id,
            tenant_id=tenant_id,
            bot_id=bot_id,
            status=status,
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
    
    async def close(self):
        """Close database connections."""
        if self._timescale_pool:
            await self._timescale_pool.close()
            self._timescale_pool = None


async def create_strategy_executor_function(platform_pool, config: Optional[StrategyExecutorConfig] = None):
    """Create an executor function for use with BacktestJobQueue.
    
    Args:
        platform_pool: asyncpg connection pool for platform_db
        config: Optional executor configuration
        
    Returns:
        An async function with signature (run_id: str, config: dict) -> None
    """
    executor = StrategyBacktestExecutor(platform_pool, config)
    
    async def execute_backtest(run_id: str, job_config: Dict[str, Any]) -> None:
        """Execute a backtest job."""
        tenant_id = job_config.get("tenant_id", "default")
        bot_id = job_config.get("bot_id", "default")
        backtest_config = job_config.get("config", job_config)
        
        result = await executor.execute(
            run_id=run_id,
            tenant_id=tenant_id,
            bot_id=bot_id,
            config=backtest_config,
        )
        
        if result.get("status") == "failed":
            raise RuntimeError(result.get("error", "Backtest failed"))
    
    return execute_backtest
