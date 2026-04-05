"""Runtime wiring for control, telemetry, and market data."""

from __future__ import annotations

import asyncio
import json
import os
import time
import hashlib
import uuid
from dataclasses import dataclass
from typing import Any, Optional


def _env_float(key: str, default: float) -> float:
    """Get env var as float, handling empty strings."""
    val = os.getenv(key)
    if not val or not val.strip():
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def _env_int(key: str, default: int) -> int:
    """Get env var as int, handling empty strings."""
    val = os.getenv(key)
    if not val or not val.strip():
        return default
    try:
        return int(val)
    except (ValueError, TypeError):
        return default


def _env_float_or_none(key: str) -> Optional[float]:
    """Get env var as float or None if not set/empty."""
    val = os.getenv(key)
    if not val or not val.strip():
        return None
    try:
        result = float(val)
        return result if result > 0 else None
    except (ValueError, TypeError):
        return None


def _env_pct(key: str, default: float) -> float:
    """Get env var as decimal percent (e.g., 5 -> 0.05)."""
    val = _env_float(key, default)
    if val > 1.0:
        return val / 100.0
    return val


def _env_bool(key: str, default: bool) -> bool:
    raw = os.getenv(key)
    if raw is None or not raw.strip():
        return default
    return raw.lower() in {"1", "true", "yes"}


def _env_symbol_float_map(key: str) -> dict[str, float]:
    raw = os.getenv(key)
    if raw is None or not raw.strip():
        return {}
    try:
        payload = json.loads(raw)
    except Exception:
        return {}
    if not isinstance(payload, dict):
        return {}
    mapped: dict[str, float] = {}
    for symbol, value in payload.items():
        try:
            mapped[str(symbol).upper()] = float(value)
        except (TypeError, ValueError):
            continue
    return mapped


def _env_csv_set(key: str, default_csv: str = "") -> set[str]:
    raw = os.getenv(key)
    source = raw if (raw is not None and raw.strip()) else default_csv
    values: set[str] = set()
    for token in (source or "").split(","):
        item = token.strip().lower()
        if item:
            values.add(item)
    return values


def _build_guard_fee_model(exchange: Optional[str]) -> FeeModel:
    """Select a reasonable fee model based on exchange name."""
    exchange_name = (exchange or "").lower()
    fee_config_name = (os.getenv("POSITION_GUARD_FEE_CONFIG") or "").strip().lower()
    if fee_config_name:
        try:
            return FeeModel(getattr(FeeConfig, fee_config_name)())
        except AttributeError:
            pass
    if "bybit" in exchange_name:
        return FeeModel(FeeConfig.bybit_regular())
    if "okx" in exchange_name:
        return FeeModel(FeeConfig.okx_regular())
    return FeeModel(FeeConfig.okx_regular())


def _parse_symbol_list(raw: str) -> list[str]:
    return [s.strip() for s in raw.split(",") if s.strip()]


def _normalize_symbol(symbol: str) -> str:
    return str(to_storage_symbol(symbol) or "")

from quantgambit.control.command_consumer import CommandConsumer
from quantgambit.control.manager import ControlManager, ControlManagerConfig
from quantgambit.control.runtime_state import ControlRuntimeState

from quantgambit.integration.config_registry import ConfigurationRegistry
from quantgambit.integration.decision_recording import DecisionRecorder
from quantgambit.integration.shadow_comparison import ShadowComparator
from quantgambit.integration.warm_start import WarmStartLoader, WarmStartState
from quantgambit.config.watcher import ConfigWatcher, ConfigApplier
from quantgambit.config.safety import SafeConfigApplier
from quantgambit.config.repository import ConfigRepository
from quantgambit.runtime.config_apply import RuntimeConfigApplier
from quantgambit.execution.actions import ExecutionActionHandler
from quantgambit.execution.manager import ExecutionManager, ExchangeReconciler, ExecutionIntent, PositionSnapshot
from quantgambit.execution.wiring import build_execution_manager
from quantgambit.market.reference_prices import ReferencePriceCache
from quantgambit.market.updater import MarketDataProvider
from quantgambit.ingest.market_data_worker import MarketDataWorker, MarketDataWorkerConfig
from quantgambit.ingest.orderbook_worker import OrderbookWorker, OrderbookWorkerConfig
from quantgambit.ingest.orderbook_feed import OrderbookFeedWorker, OrderbookFeedConfig
from quantgambit.ingest.order_update_worker import OrderUpdateWorker
from quantgambit.ingest.candle_worker import CandleWorker, CandleWorkerConfig
from quantgambit.ingest.trade_feed import TradeFeedWorker, TradeFeedConfig
from quantgambit.ingest.trade_worker import TradeWorker, TradeWorkerConfig
from quantgambit.ingest.monotonic_clock import MonotonicClock
from quantgambit.signals.feature_worker import FeaturePredictionWorker, FeatureWorkerConfig
from quantgambit.signals.decision_worker import DecisionWorker, DecisionWorkerConfig
from quantgambit.signals.decision_engine import DecisionEngine
from quantgambit.signals.services.symbol_characteristics import SymbolCharacteristicsService
from quantgambit.signals.stages.symbol_characteristics_stage import SymbolCharacteristicsStageConfig
from quantgambit.signals.stages.data_readiness import DataReadinessConfig
from quantgambit.signals.stages.amt_calculator import CandleCache
from quantgambit.execution.execution_worker import ExecutionWorker, ExecutionWorkerConfig
from quantgambit.execution.order_update_consumer import OrderUpdateConsumer
from quantgambit.execution.order_reconciler_worker import OrderReconcilerWorker
from quantgambit.execution.position_guard_worker import PositionGuardWorker, PositionGuardConfig
from quantgambit.execution.idempotency_store import RedisIdempotencyStore
from quantgambit.risk.risk_worker import RiskWorker, RiskWorkerConfig
from quantgambit.risk.overrides import RiskOverrideStore
from quantgambit.risk.fee_model import FeeModel, FeeConfig
from quantgambit.core.risk.correlation_guard import CorrelationGuard, CorrelationGuardConfig
from quantgambit.execution.order_store import InMemoryOrderStore
from quantgambit.execution.order_statuses import is_open_status, normalize_order_status, is_terminal_status
from quantgambit.execution.symbols import normalize_exchange_symbol, to_storage_symbol
from quantgambit.diagnostics.health_worker import HealthWorker, HealthWorkerConfig
from quantgambit.market.deeptrader_provider import DeepTraderMarketDataProvider
from quantgambit.market.quality import MarketDataQualityTracker
from quantgambit.market.trades import TradeStatsCache
from quantgambit.observability.telemetry import TelemetryPipeline, TelemetryContext
from quantgambit.observability.logger import log_info, log_error, log_warning
from quantgambit.observability.alerts import AlertsClient, AlertConfig
from quantgambit.storage.redis_streams import (
    RedisStreamsClient,
    command_stream_name,
    command_result_stream_name,
)
from quantgambit.storage.redis_snapshots import RedisSnapshotWriter, RedisSnapshotReader
from quantgambit.storage.timescale import NullTimescaleWriter, TimescaleReader, TimescaleWriter
from quantgambit.storage.postgres import PostgresOrderStore, PostgresIdempotencyStore
from quantgambit.config.store import ConfigStore
from quantgambit.config.trading_mode import TradingModeManager, create_trading_mode_manager_from_env
from quantgambit.config.loss_prevention import load_loss_prevention_config, get_config_manager
from quantgambit.config.confirmation_policy import load_confirmation_policy_config
from quantgambit.portfolio.state_manager import InMemoryStateManager
from quantgambit.runtime.quant_integration import (
    QuantIntegration,
    OrderStoreAdapter,
    PositionStoreAdapter,
    ExchangeClientAdapter,
)


@dataclass
class RuntimeConfig:
    tenant_id: str
    bot_id: str
    exchange: str
    orderbook_symbols: Optional[list[str]] = None
    trading_mode: str = "live"
    market_type: str = "perp"
    margin_mode: str = "isolated"
    trading_hours_start: int = 0
    trading_hours_end: int = 24
    order_intent_max_age_sec: Optional[float] = None
    version: Optional[int] = None


def _scoped_stream(env_name: str, base: str, tenant_id: str, bot_id: str) -> str:
    """Return env override or tenant/bot scoped stream name."""
    override = os.getenv(env_name, "").strip()
    if override:
        return override
    if tenant_id and bot_id:
        return f"{base}:{tenant_id}:{bot_id}"
    return base


def _scoped_group(env_name: str, base: str, tenant_id: str, bot_id: str) -> str:
    """Return env override or tenant/bot scoped consumer group name."""
    override = os.getenv(env_name, "").strip()
    if override:
        return override
    if tenant_id and bot_id:
        return f"{base}:{tenant_id}:{bot_id}"
    return base


class Runtime:
    """Run control plane, config watcher, telemetry, and market updater."""

    def __init__(
        self,
        config: RuntimeConfig,
        redis,
        timescale_pool,
        state_manager: InMemoryStateManager,
        market_data_queue: Optional[asyncio.Queue] = None,
        market_data_provider: Optional[MarketDataProvider] = None,
        orderbook_provider=None,
        order_update_provider=None,
        execution_adapter=None,
        exchange_router=None,
        reconciler: Optional[ExchangeReconciler] = None,
        adapter_config=None,
        paper_fill_engine=None,
        paper_config=None,
        guard_config=None,
        prediction_provider=None,
        prediction_shadow_provider=None,
        trade_provider=None,
        trade_cache: Optional[TradeStatsCache] = None,
    ):
        prediction_min_confidence = float(os.getenv("PREDICTION_MIN_CONFIDENCE", "0.0"))
        allowed_raw = os.getenv("PREDICTION_ALLOWED_DIRECTIONS", "")
        prediction_allowed_directions = {
            item.strip() for item in allowed_raw.split(",") if item.strip()
        } or None
        prediction_confidence_scale = float(os.getenv("PREDICTION_CONFIDENCE_SCALE", "1.0"))
        prediction_confidence_bias = float(os.getenv("PREDICTION_CONFIDENCE_BIAS", "0.0"))
        self.config = config
        # Ensure optional workers are always defined to avoid AttributeError on startup.
        self.orderbook_feed_worker = None
        self._timescale_pool = timescale_pool  # Store for persistence layer initialization
        self.redis_client = RedisStreamsClient(redis)
        self.snapshots = RedisSnapshotWriter(redis)
        self.snapshot_reader = RedisSnapshotReader(redis)
        self.telemetry = TelemetryPipeline(
            redis_client=self.redis_client,
            timescale_writer=TimescaleWriter(timescale_pool),
            snapshot_writer=self.snapshots,
        )
        self.alerts = _build_alerts_client()
        self.timescale_reader = TimescaleReader(timescale_pool) if timescale_pool else None
        self._execution_ledger_schema_ready = False
        self.telemetry_ctx = TelemetryContext(
            tenant_id=config.tenant_id,
            bot_id=config.bot_id,
            exchange=config.exchange,
        )

        symbol_chars_min_samples = _env_int("SYMBOL_CHARACTERISTICS_MIN_SAMPLES", 100)
        symbol_chars_log_defaults = os.getenv("SYMBOL_CHARACTERISTICS_LOG_DEFAULTS", "true").lower() in {"1", "true", "yes"}
        self._symbol_characteristics_service = SymbolCharacteristicsService(
            redis_client=self.redis_client.redis,
        )
        self._symbol_characteristics_config = SymbolCharacteristicsStageConfig(
            min_warmup_samples=symbol_chars_min_samples,
            log_defaults=symbol_chars_log_defaults,
        )
        self._configured_symbols = self._get_config_symbols()
        self._data_readiness_config = DataReadinessConfig(
            max_trade_age_sec=_env_float("DATA_READINESS_MAX_TRADE_AGE_SEC", 30.0),
            max_clock_drift_sec=_env_float("DATA_READINESS_MAX_CLOCK_DRIFT_SEC", 1.0),
            min_bid_depth_usd=_env_float("DATA_READINESS_MIN_BID_DEPTH_USD", 1000.0),
            min_ask_depth_usd=_env_float("DATA_READINESS_MIN_ASK_DEPTH_USD", 1000.0),
            require_ws_connected=_env_bool("DATA_READINESS_REQUIRE_WS_CONNECTED", True),
            max_orderbook_feed_age_sec=_env_float("DATA_READINESS_MAX_ORDERBOOK_FEED_AGE_SEC", 10.0),
            max_trade_feed_age_sec=_env_float("DATA_READINESS_MAX_TRADE_FEED_AGE_SEC", 30.0),
            max_candle_feed_age_sec=_env_float("DATA_READINESS_MAX_CANDLE_FEED_AGE_SEC", 120.0),
            use_cts_latency_gates=_env_bool("DATA_READINESS_USE_CTS_LATENCY_GATES", True),
            book_lag_green_ms=_env_int("DATA_READINESS_BOOK_LAG_GREEN_MS", 150),
            book_lag_yellow_ms=_env_int("DATA_READINESS_BOOK_LAG_YELLOW_MS", 300),
            book_lag_red_ms=_env_int("DATA_READINESS_BOOK_LAG_RED_MS", 800),
            max_orderbook_exchange_lag_ms=_env_int("DATA_READINESS_MAX_ORDERBOOK_EXCHANGE_LAG_MS", 3000),
            trade_lag_green_ms=_env_int("DATA_READINESS_TRADE_LAG_GREEN_MS", 1500),
            trade_lag_yellow_ms=_env_int("DATA_READINESS_TRADE_LAG_YELLOW_MS", 4000),
            trade_lag_red_ms=_env_int("DATA_READINESS_TRADE_LAG_RED_MS", 6000),
            book_gap_green_ms=_env_int("DATA_READINESS_BOOK_GAP_GREEN_MS", 2000),
            book_gap_yellow_ms=_env_int("DATA_READINESS_BOOK_GAP_YELLOW_MS", 5000),
            book_gap_red_ms=_env_int("DATA_READINESS_BOOK_GAP_RED_MS", 10000),
            trade_gap_green_ms=_env_int("DATA_READINESS_TRADE_GAP_GREEN_MS", 2000),
            trade_gap_yellow_ms=_env_int("DATA_READINESS_TRADE_GAP_YELLOW_MS", 5000),
            trade_gap_red_ms=_env_int("DATA_READINESS_TRADE_GAP_RED_MS", 10000),
        )
        
        # Initialize ConfigurationRegistry for configuration parity enforcement
        # Feature: trading-pipeline-integration
        # Requirements: 1.1, 1.2, 1.6
        self.config_registry = ConfigurationRegistry(timescale_pool, redis)
        
        # Initialize DecisionRecorder for recording live trading decisions
        # Feature: trading-pipeline-integration
        # Requirements: 2.1, 2.2
        # Feature: bot-integration-fixes
        # Requirements: 5.3 - Support DECISION_RECORDER_ENABLED env var with default "true"
        # Requirements: 5.7 - Skip DecisionRecorder initialization when disabled
        decision_recorder_enabled = os.getenv("DECISION_RECORDER_ENABLED", "true").lower() in {"1", "true", "yes"}
        decision_recorder_batch_size = _env_int("DECISION_RECORDER_BATCH_SIZE", 100)
        decision_recorder_flush_interval = _env_float("DECISION_RECORDER_FLUSH_INTERVAL_SEC", 5.0)
        self.decision_recorder: Optional[DecisionRecorder] = None
        if decision_recorder_enabled and timescale_pool:
            self.decision_recorder = DecisionRecorder(
                timescale_pool=timescale_pool,
                config_registry=self.config_registry,
                batch_size=decision_recorder_batch_size,
                flush_interval_sec=decision_recorder_flush_interval,
            )
        
        # Initialize WarmStartLoader for warm starting backtests from live state
        # Feature: trading-pipeline-integration
        # Requirements: 3.1 - Support initializing backtests from live state
        # Requirements: 3.2 - Load state snapshots from Redis
        # Requirements: 8.1 - Support exporting live state
        # Requirements: 8.2 - Include positions, account state, decisions, pipeline state
        self.warm_start_loader: Optional[WarmStartLoader] = None
        if redis and timescale_pool:
            self.warm_start_loader = WarmStartLoader(
                redis_client=redis,
                timescale_pool=timescale_pool,
                tenant_id=config.tenant_id,
                bot_id=config.bot_id,
            )
        
        # Periodic state snapshot configuration for warm start availability
        # Feature: trading-pipeline-integration
        # Requirements: 8.5 - Support point-in-time state snapshots
        self._state_snapshot_interval_sec = _env_float("STATE_SNAPSHOT_INTERVAL_SEC", 60.0)
        self._state_snapshot_enabled = os.getenv("STATE_SNAPSHOT_ENABLED", "true").lower() in {"1", "true", "yes"}
        
        market_data_stream = os.getenv("MARKET_DATA_STREAM", "events:market_data")
        feature_stream = _scoped_stream("FEATURES_STREAM", "events:features", config.tenant_id, config.bot_id)
        candle_stream = _scoped_stream("CANDLES_STREAM", "events:candles", config.tenant_id, config.bot_id)
        self.candle_stream = candle_stream
        decision_stream = _scoped_stream("DECISIONS_STREAM", "events:decisions", config.tenant_id, config.bot_id)
        decision_shadow_stream = _scoped_stream(
            "DECISIONS_SHADOW_STREAM",
            "events:decisions_shadow",
            config.tenant_id,
            config.bot_id,
        )
        risk_stream = _scoped_stream(
            "RISK_DECISIONS_STREAM",
            "events:risk_decisions",
            config.tenant_id,
            config.bot_id,
        )
        orderbook_group = _scoped_group(
            "ORDERBOOK_CONSUMER_GROUP",
            "quantgambit_orderbook",
            config.tenant_id,
            config.bot_id,
        )
        trade_group = _scoped_group(
            "TRADE_CONSUMER_GROUP",
            "quantgambit_trades",
            config.tenant_id,
            config.bot_id,
        )
        candle_group = _scoped_group(
            "CANDLE_CONSUMER_GROUP",
            "quantgambit_candles",
            config.tenant_id,
            config.bot_id,
        )
        feature_group = _scoped_group(
            "FEATURE_CONSUMER_GROUP",
            "quantgambit_features",
            config.tenant_id,
            config.bot_id,
        )
        feature_candle_group = _scoped_group(
            "FEATURE_CANDLE_GROUP",
            "quantgambit_features_candles",
            config.tenant_id,
            config.bot_id,
        )
        decision_group = _scoped_group(
            "DECISION_CONSUMER_GROUP",
            "quantgambit_decisions",
            config.tenant_id,
            config.bot_id,
        )
        risk_group = _scoped_group(
            "RISK_CONSUMER_GROUP",
            "quantgambit_risk",
            config.tenant_id,
            config.bot_id,
        )
        execution_group = _scoped_group(
            "EXECUTION_CONSUMER_GROUP",
            "quantgambit_execution",
            config.tenant_id,
            config.bot_id,
        )
        self.telemetry_context = self.telemetry_ctx
        self.config_store = ConfigStore(timescale_pool) if timescale_pool else None
        
        # Initialize TradingModeManager for mode-aware throttling
        # Uses THROTTLE_MODE env var (separate from TRADING_MODE which is live/paper)
        self.trading_mode_manager = create_trading_mode_manager_from_env(
            redis_client=redis,
            bot_id=config.bot_id,
            telemetry=self.telemetry,
            telemetry_context=self.telemetry_ctx,
        )
        self.positions_snapshot_interval = float(os.getenv("POSITIONS_SNAPSHOT_HEARTBEAT_SEC", "5.0"))
        self.exchange_positions_sync_interval = float(os.getenv("EXCHANGE_POSITIONS_SYNC_SEC", "60.0"))
        self.exchange_positions_remove_after_misses = max(
            1, int(os.getenv("EXCHANGE_POSITIONS_REMOVE_AFTER_MISSES", "3"))
        )
        self._exchange_position_miss_counts: dict[str, int] = {}
        self._exchange_position_first_seen_opened_at: dict[str, float] = {}

        self.reference_prices = ReferencePriceCache()
        # Keep feature/quality staleness defaults aligned with DataReadiness thresholds
        # unless explicit QUALITY_* overrides are provided.
        quality_tick_stale_sec = (
            float(os.getenv("QUALITY_TICK_STALE_SEC"))
            if os.getenv("QUALITY_TICK_STALE_SEC") is not None
            else float(self._data_readiness_config.max_orderbook_feed_age_sec)
        )
        quality_trade_stale_sec = (
            float(os.getenv("QUALITY_TRADE_STALE_SEC"))
            if os.getenv("QUALITY_TRADE_STALE_SEC") is not None
            else float(self._data_readiness_config.max_trade_feed_age_sec)
        )
        quality_orderbook_stale_sec = (
            float(os.getenv("QUALITY_ORDERBOOK_STALE_SEC"))
            if os.getenv("QUALITY_ORDERBOOK_STALE_SEC") is not None
            else float(self._data_readiness_config.max_orderbook_feed_age_sec)
        )
        self.quality_tracker = MarketDataQualityTracker(
            snapshot_writer=self.snapshots,
            telemetry=self.telemetry,
            telemetry_context=self.telemetry_ctx,
            tick_stale_sec=quality_tick_stale_sec,
            trade_stale_sec=quality_trade_stale_sec,
            orderbook_stale_sec=quality_orderbook_stale_sec,
            gap_window_sec=float(os.getenv("QUALITY_GAP_WINDOW_SEC", "30.0")),
            max_history=int(os.getenv("QUALITY_MAX_HISTORY", "200")),
        )
        
        # Create shared latency tracker and kill switch early so they can be passed to workers
        from quantgambit.core.latency import LatencyTracker
        from quantgambit.core.clock import WallClock
        from quantgambit.core.risk.kill_switch_store import PersistentKillSwitch, RedisKillSwitchStore
        
        self._clock = WallClock()
        self._latency_tracker = LatencyTracker(
            clock=self._clock,
            max_samples=int(os.getenv("LATENCY_MAX_SAMPLES", "100000")),
            window_sec=float(os.getenv("LATENCY_WINDOW_SEC", "60.0")),
        )
        
        # Create kill switch with Redis persistence
        self.quant_integration_enabled = os.getenv("QUANT_INTEGRATION_ENABLED", "true").lower() in ("true", "1", "yes")
        self._kill_switch = None
        if self.quant_integration_enabled:
            try:
                kill_switch_store = RedisKillSwitchStore(redis, config.tenant_id, config.bot_id)
                self._kill_switch = PersistentKillSwitch(
                    clock=self._clock,
                    store=kill_switch_store,
                    alerts_client=self.alerts,  # Pass alerts client for Slack/Discord
                    tenant_id=config.tenant_id,
                    bot_id=config.bot_id,
                )
            except Exception as exc:
                log_warning("kill_switch_init_failed", error=str(exc))
        
        self.state_manager = state_manager
        # Store capital cap for later use (optional budget limit)
        self._max_capital_usd: Optional[float] = None
        max_cap_str = os.getenv("MAX_CAPITAL_USD")
        if max_cap_str:
            try:
                self._max_capital_usd = float(max_cap_str)
            except (TypeError, ValueError):
                pass
        
        if self.state_manager:
            # Set a temporary initial equity from config
            # This will be updated with actual exchange balance in start()
            # For paper trading, use PAPER_EQUITY; for live, use a placeholder
            if config.trading_mode == "paper":
                initial_equity = float(os.getenv("PAPER_EQUITY", "100000.0"))
            else:
                # Use a placeholder - will be updated from exchange in start()
                # This prevents the old bug where TRADING_CAPITAL_USD was used as peak
                initial_equity = 0.0  # Will be set from exchange
            self.state_manager.update_account_state(equity=initial_equity, peak_balance=initial_equity)
            self._initial_equity_from_config = initial_equity
        self.execution_adapter = execution_adapter
        self.exchange_router = exchange_router
        self.reconciler = reconciler
        self.adapter_config = adapter_config
        self.paper_fill_engine = paper_fill_engine
        self.paper_config = paper_config
        self.risk_override_store = RiskOverrideStore(
            snapshot_writer=self.snapshots,
            snapshot_reader=self.snapshot_reader,
            snapshot_key=f"quantgambit:{config.tenant_id}:{config.bot_id}:risk:overrides",
        )
        self.order_store = InMemoryOrderStore(
            snapshot_writer=self.snapshots,
            snapshot_reader=self.snapshot_reader,
            snapshot_history_key=f"quantgambit:{config.tenant_id}:{config.bot_id}:orders:history",
            tenant_id=config.tenant_id,
            bot_id=config.bot_id,
            max_intent_age_sec=(
                config.order_intent_max_age_sec
                if config.order_intent_max_age_sec is not None
                else float(os.getenv("ORDER_INTENT_MAX_AGE_SEC", "0")) or None
            ),
            postgres_store=PostgresOrderStore(timescale_pool) if timescale_pool else None,
        )
        self.prediction_provider = prediction_provider
        self.prediction_shadow_provider = prediction_shadow_provider
        # Shared per-symbol monotonic clock across all ingestion event types
        self._monotonic_clock = MonotonicClock()
        if market_data_provider is None and market_data_queue is not None:
            market_data_provider = DeepTraderMarketDataProvider(market_data_queue)
        market_data_config = MarketDataWorkerConfig(
            timestamp_source=os.getenv("MARKET_DATA_TIMESTAMP_SOURCE", "exchange"),
            max_clock_skew_sec=float(os.getenv("MARKET_DATA_MAX_CLOCK_SKEW_SEC", "5.0")),
            stale_threshold_sec=float(os.getenv("MARKET_DATA_STALE_SEC", "5.0")),
        )
        self.market_worker = (
                MarketDataWorker(
                    market_data_provider,
                    self.reference_prices,
                    self.redis_client,
                    bot_id=config.bot_id,
                    exchange=config.exchange,
                    market_type=config.market_type,
                    telemetry=self.telemetry,
                    telemetry_context=self.telemetry_ctx,
                    quality_tracker=self.quality_tracker,
                    config=market_data_config,
                    monotonic_clock=self._monotonic_clock,
                )
            if market_data_provider
            else None
        )
        if market_data_provider and hasattr(market_data_provider, "set_telemetry"):
            market_data_provider.set_telemetry(self.telemetry, self.telemetry_ctx)
        if market_data_provider and hasattr(market_data_provider, "set_alerts"):
            market_data_provider.set_alerts(self.alerts)
        if market_data_provider and hasattr(market_data_provider, "set_snapshot_writer"):
            key = f"quantgambit:{config.tenant_id}:{config.bot_id}:market_data:provider"
            market_data_provider.set_snapshot_writer(self.snapshots, key)
        if market_data_provider and hasattr(market_data_provider, "set_timescale_writer") and timescale_pool:
            market_data_provider.set_timescale_writer(
                TimescaleWriter(timescale_pool),
                tenant_id=config.tenant_id,
                bot_id=config.bot_id,
                exchange=config.exchange,
            )
        orderbook_feed_config = None
        if orderbook_provider:
            emit_market_ticks = os.getenv("ORDERBOOK_EMIT_MARKET_TICKS", "true").lower() in {
                "1",
                "true",
                "yes",
            }
            orderbook_market_stream = os.getenv("ORDERBOOK_MARKET_STREAM", market_data_stream)
            orderbook_feed_config = OrderbookFeedConfig(
                timestamp_source=os.getenv("ORDERBOOK_TIMESTAMP_SOURCE", "exchange"),
                max_clock_skew_sec=float(os.getenv("ORDERBOOK_MAX_CLOCK_SKEW_SEC", "5.0")),
                emit_market_ticks=emit_market_ticks,
                market_data_stream=orderbook_market_stream,
            )
            self.orderbook_feed_worker = (
                OrderbookFeedWorker(
                    orderbook_provider,
                    self.redis_client,
                    bot_id=config.bot_id,
                    exchange=config.exchange,
                    config=orderbook_feed_config,
                    monotonic_clock=self._monotonic_clock,
                )
                if orderbook_provider
                else None
            )
        if orderbook_provider and hasattr(orderbook_provider, "set_telemetry"):
            orderbook_provider.set_telemetry(self.telemetry, self.telemetry_ctx)
        if order_update_provider and hasattr(order_update_provider, "set_telemetry"):
            order_update_provider.set_telemetry(self.telemetry, self.telemetry_ctx)
        if trade_provider and hasattr(trade_provider, "set_telemetry"):
            trade_provider.set_telemetry(self.telemetry, self.telemetry_ctx)
        self.order_update_worker = (
            OrderUpdateWorker(
                order_update_provider,
                self.redis_client,
                bot_id=config.bot_id,
                exchange=config.exchange,
                telemetry=self.telemetry,
                telemetry_context=self.telemetry_ctx,
                monotonic_clock=self._monotonic_clock,
            )
            if order_update_provider
            else None
        )
        trade_stream = os.getenv("TRADE_STREAM", "events:trades")
        trade_consumer = os.getenv("TRADE_CONSUMER_NAME", "trade_worker")
        trade_emit_ticks = os.getenv("TRADE_EMIT_MARKET_TICKS", "auto").lower()
        trade_external = os.getenv("TRADE_SOURCE", "").lower() in {"external", "shared"} or os.getenv(
            "TRADES_EXTERNAL", "false"
        ).lower() in {"1", "true", "yes"}
        self.trade_enabled = trade_provider is not None or trade_external
        if self.trade_enabled:
            if trade_cache is None:
                trade_cache = TradeStatsCache(
                    window_sec=float(os.getenv("TRADE_WINDOW_SEC", "60")),
                    profile_window_sec=float(os.getenv("TRADE_PROFILE_WINDOW_SEC", "300")),
                    bucket_size=float(os.getenv("TRADE_BUCKET_SIZE", "5")),
                    max_trades=int(os.getenv("TRADE_MAX_TRADES", "10000")),
                )
            self.trade_feed_worker = (
                TradeFeedWorker(
                    trade_provider,
                    self.redis_client,
                    bot_id=config.bot_id,
                    exchange=config.exchange,
                    config=TradeFeedConfig(
                        stream=trade_stream,
                        emit_market_ticks=(
                            trade_emit_ticks in {"1", "true", "yes"}
                            or (trade_emit_ticks == "auto" and not self.market_worker)
                        ),
                        market_data_stream=market_data_stream,
                    ),
                    monotonic_clock=self._monotonic_clock,
                )
                if trade_provider and not trade_external
                else None
            )
            self.trade_worker = TradeWorker(
                redis_client=self.redis_client,
                cache=trade_cache,
                quality_tracker=self.quality_tracker,
                config=TradeWorkerConfig(
                    source_stream=trade_stream,
                    consumer_group=trade_group,
                    consumer_name=trade_consumer,
                ),
                reference_cache=self.reference_prices,  # For latency measurement
            )
        else:
            self.trade_feed_worker = None
            self.trade_worker = None
        self.trade_cache = trade_cache
        orderbook_external = os.getenv("ORDERBOOK_SOURCE", "").lower() in {"external", "shared"} or os.getenv(
            "ORDERBOOK_EXTERNAL", "false"
        ).lower() in {"1", "true", "yes"}
        self.orderbook_worker = OrderbookWorker(
            redis_client=self.redis_client,
            cache=self.reference_prices,
            quality_tracker=self.quality_tracker,
            config=OrderbookWorkerConfig(
                source_stream=os.getenv("ORDERBOOK_EVENT_STREAM", "events:orderbook_feed"),
                consumer_group=orderbook_group,
                consumer_name=os.getenv("ORDERBOOK_CONSUMER_NAME", "orderbook_worker"),
                depth=_env_int("ORDERBOOK_DEPTH_LEVELS", 50),
                # In external/shared orderbook mode, downstream candle/feature workers still
                # need market_tick events even if a nominal market worker object exists.
                # Gate on the actual source mode, not on self.market_worker presence.
                emit_market_ticks=orderbook_external,
                market_data_stream=os.getenv("ORDERBOOK_MARKET_STREAM", market_data_stream),
            ),
            telemetry_context=self.telemetry_ctx,  # Enable warmup key publishing
        )
        candle_timescale = self.telemetry.timescale or NullTimescaleWriter()
        self.candle_worker = CandleWorker(
            redis_client=self.redis_client,
            timescale=candle_timescale,
            tenant_id=config.tenant_id,
            bot_id=config.bot_id,
            exchange=config.exchange,
            config=CandleWorkerConfig(
                # CandleWorker expects market_tick events from MARKET_DATA_STREAM.
                # Do NOT fall back to TRADE_STREAM - it contains trade events which are filtered out.
                source_stream=os.getenv("CANDLE_SOURCE_STREAM", market_data_stream),
                output_stream=candle_stream,
                consumer_group=candle_group,
                consumer_name=os.getenv("CANDLE_CONSUMER_NAME", "candle_worker"),
            ),
            monotonic_clock=self._monotonic_clock,
        )
        # Feature worker gating env vars - allows runtime tuning without code changes
        feature_gate_orderbook_gap = os.getenv("FEATURE_GATE_ORDERBOOK_GAP", "true").lower() in {"1", "true", "yes"}
        feature_gate_orderbook_stale = os.getenv("FEATURE_GATE_ORDERBOOK_STALE", "true").lower() in {"1", "true", "yes"}
        feature_gate_trade_stale = os.getenv("FEATURE_GATE_TRADE_STALE", "true").lower() in {"1", "true", "yes"}
        feature_gate_candle_stale = os.getenv("FEATURE_GATE_CANDLE_STALE", "true").lower() in {"1", "true", "yes"}
        feature_min_quality = float(os.getenv("FEATURE_MIN_QUALITY", "0.6"))
        feature_emit_degraded = os.getenv("FEATURE_EMIT_DEGRADED", "true").lower() in {"1", "true", "yes"}
        
        # Create candle cache for AMT calculations
        # This cache is shared between FeatureWorker (populates) and DecisionEngine (consumes)
        amt_candle_cache_size = int(os.getenv("AMT_CANDLE_CACHE_SIZE", "500"))
        self.candle_cache = CandleCache(max_candles=amt_candle_cache_size)
        
        self.feature_worker = FeaturePredictionWorker(
            redis_client=self.redis_client,
            bot_id=config.bot_id,
            exchange=config.exchange,
            telemetry=self.telemetry,
            telemetry_context=self.telemetry_ctx,
            orderbook_cache=self.reference_prices,
            prediction_provider=self.prediction_provider,
            shadow_prediction_provider=self.prediction_shadow_provider,
            prediction_confidence_scale=prediction_confidence_scale,
            prediction_confidence_bias=prediction_confidence_bias,
            trade_cache=self.trade_cache,
            quality_tracker=self.quality_tracker,
            latency_tracker=self._latency_tracker,
            candle_cache=self.candle_cache,  # For AMT calculations
            config=FeatureWorkerConfig(
                # FeatureWorker expects market_tick events from MARKET_DATA_STREAM.
                # Do NOT fall back to TRADE_STREAM - it contains trade events which are filtered out.
                source_stream=os.getenv("FEATURE_SOURCE_STREAM", market_data_stream),
                output_stream=feature_stream,
                consumer_group=feature_group,
                consumer_name=os.getenv("FEATURE_CONSUMER_NAME", "feature_worker"),
                candle_stream=candle_stream,
                candle_group=feature_candle_group,
                candle_consumer=os.getenv("FEATURE_CANDLE_CONSUMER", "feature_candle_worker"),
                gate_on_orderbook_gap=feature_gate_orderbook_gap,
                gate_on_orderbook_stale=feature_gate_orderbook_stale,
                gate_on_trade_stale=feature_gate_trade_stale if self.trade_enabled else False,
                gate_on_candle_stale=feature_gate_candle_stale,
                candle_stale_sec=float(
                    os.getenv(
                        "FEATURE_CANDLE_STALE_SEC",
                        str(self._data_readiness_config.max_candle_feed_age_sec),
                    )
                ),
                min_quality_for_prediction=feature_min_quality,
                emit_degraded_features=feature_emit_degraded,
            ),
        )
        self.feature_worker.config.trading_session_start_hour_utc = config.trading_hours_start
        self.feature_worker.config.trading_session_end_hour_utc = config.trading_hours_end
        
        # Load loss prevention configuration from environment
        loss_prevention_config = load_loss_prevention_config()
        confirmation_policy_config = load_confirmation_policy_config()

        # Correlation guard (optional)
        correlation_guard = None
        corr_enabled = os.getenv("CORRELATION_GUARD_ENABLED", "false").lower() in {"1", "true", "yes"}
        if corr_enabled:
            max_corr = float(os.getenv("CORRELATION_GUARD_MAX", "0.70"))
            max_corr_long_raw = os.getenv("CORRELATION_GUARD_MAX_LONG")
            max_corr_short_raw = os.getenv("CORRELATION_GUARD_MAX_SHORT")
            max_corr_long = float(max_corr_long_raw) if max_corr_long_raw else None
            max_corr_short = float(max_corr_short_raw) if max_corr_short_raw else None
            excluded = {
                s.strip().upper()
                for s in os.getenv("CORRELATION_GUARD_EXCLUDED_SYMBOLS", "").split(",")
                if s.strip()
            }
            correlation_guard = CorrelationGuard(
                config=CorrelationGuardConfig(
                    enabled=True,
                    max_correlation=max_corr,
                    max_correlation_long=max_corr_long,
                    max_correlation_short=max_corr_short,
                    excluded_symbols=excluded,
                ),
                tenant_id=config.tenant_id,
                bot_id=config.bot_id,
            )

        self.decision_engine = DecisionEngine(
            telemetry=self.telemetry,
            telemetry_context=self.telemetry_ctx,
            prediction_min_confidence=prediction_min_confidence,
            position_eval_min_confirmations=_env_int("POSITION_EVAL_MIN_CONFIRMATIONS", 2),
            position_eval_underwater_threshold_pct=_env_float("POSITION_EVAL_UNDERWATER_THRESHOLD_PCT", -0.3),
            prediction_allowed_directions=prediction_allowed_directions,
            trading_mode_manager=self.trading_mode_manager,
            symbol_characteristics_service=self._symbol_characteristics_service,
            symbol_characteristics_config=self._symbol_characteristics_config,
            data_readiness_config=self._data_readiness_config,
            # Candle cache for AMT calculations (shared with FeatureWorker)
            candle_cache=self.candle_cache,
            # Loss prevention stage configs (Requirements 1, 2, 4, 5)
            strategy_trend_alignment_config=loss_prevention_config.strategy_trend_alignment if loss_prevention_config.enabled else None,
            session_filter_config=loss_prevention_config.session_filter if loss_prevention_config.enabled else None,
            ev_gate_config=loss_prevention_config.ev_gate if loss_prevention_config.enabled else None,
            ev_position_sizer_config=loss_prevention_config.ev_position_sizer if loss_prevention_config.enabled else None,
            # Cost data quality stage (runs before EVGate) - disabled by default until timestamps verified
            cost_data_quality_config=loss_prevention_config.cost_data_quality if loss_prevention_config.enabled else None,
            # Global gate config (depth, spread thresholds)
            global_gate_config=loss_prevention_config.global_gate if loss_prevention_config.enabled else None,
            # Cooldown config (entry/exit cooldowns)
            cooldown_config=loss_prevention_config.cooldown if loss_prevention_config.enabled else None,
            # Unified confirmation policy (entry + non-emergency exit)
            confirmation_policy_config=confirmation_policy_config,
            correlation_guard=correlation_guard,
        )
        self.config_repository = ConfigRepository()
        decision_warmup_min_samples = int(os.getenv("DECISION_WARMUP_MIN_SAMPLES", "5"))
        decision_warmup_min_candles = int(os.getenv("DECISION_WARMUP_MIN_CANDLES", "0"))  # Disabled by default - candles not reliable
        decision_min_quality = float(os.getenv("DECISION_MIN_DATA_QUALITY_SCORE", "0.2"))  # Reduced to allow trading with degraded data
        decision_warmup_quality = float(os.getenv("DECISION_WARMUP_QUALITY_MIN_SCORE", str(decision_min_quality)))
        decision_warmup_gate_enabled = os.getenv("DECISION_WARMUP_GATE_ENABLED", "true").lower() in {"1", "true", "yes"}  # ENABLED - blocks trading until warmup samples received
        self.decision_worker = DecisionWorker(
            redis_client=self.redis_client,
            engine=self.decision_engine,
            bot_id=config.bot_id,
            exchange=config.exchange,
            tenant_id=config.tenant_id,
            state_manager=self.state_manager,
            config_repository=self.config_repository,
            telemetry=self.telemetry,
            telemetry_context=self.telemetry_ctx,
            config=DecisionWorkerConfig(
                source_stream=feature_stream,
                output_stream=decision_stream,
                consumer_group=decision_group,
                consumer_name=os.getenv("DECISION_CONSUMER_NAME", "decision_worker"),
                warmup_min_samples=decision_warmup_min_samples,
                warmup_min_candles=decision_warmup_min_candles,
                shadow_stream=decision_shadow_stream,
                min_data_quality_score=decision_min_quality,
                warmup_quality_min_score=decision_warmup_quality,
                warmup_gate_enabled=decision_warmup_gate_enabled,
                max_feature_age_sec=float(os.getenv("DECISION_MAX_FEATURE_AGE_SEC", "120")),
            ),
            kill_switch=self._kill_switch,
            latency_tracker=self._latency_tracker,
            decision_recorder=self.decision_recorder,  # Feature: trading-pipeline-integration, Requirements: 2.1, 2.2
            config_registry=self.config_registry,  # Feature: trading-pipeline-integration, Requirements: 1.1, 1.2, 1.6
        )
        shadow_mode = os.getenv("SHADOW_MODE", "false").strip().lower() in {"1", "true", "yes"}
        self.decision_worker.config.shadow_mode = shadow_mode
        self.decision_worker.config.shadow_reason = os.getenv(
            "SHADOW_REASON",
            self.decision_worker.config.shadow_reason,
        )
        
        # Initialize ShadowComparator for dual-pipeline comparison when shadow mode is enabled
        # Feature: trading-pipeline-integration
        # Requirements: 4.1 - THE System SHALL support running live and shadow pipelines in parallel
        # Requirements: 4.2 - THE System SHALL compare decisions from both pipelines in real-time
        self.shadow_comparator: Optional[ShadowComparator] = None
        shadow_mode_enabled = os.getenv("SHADOW_MODE_ENABLED", "false").strip().lower() in {"1", "true", "yes"}
        
        if shadow_mode_enabled:
            try:
                # Load shadow configuration from ConfigurationRegistry
                # The shadow config can have different parameters for comparison testing
                shadow_config_overrides = self._load_shadow_config_overrides()
                
                # Create a shadow decision engine with alternative configuration
                # This allows testing strategy changes before deployment
                shadow_engine = self._create_shadow_decision_engine(shadow_config_overrides)
                
                if shadow_engine:
                    # Configure alert threshold from environment
                    shadow_alert_threshold = _env_float("SHADOW_ALERT_THRESHOLD", 0.20)
                    shadow_window_size = _env_int("SHADOW_WINDOW_SIZE", 100)
                    
                    self.shadow_comparator = ShadowComparator(
                        live_engine=self.decision_engine,
                        shadow_engine=shadow_engine,
                        telemetry=self.telemetry,
                        alert_threshold=shadow_alert_threshold,
                        window_size=shadow_window_size,
                    )
                    
                    # Wire shadow comparator into DecisionWorker for dual-pipeline comparison
                    self.decision_worker._shadow_comparator = self.shadow_comparator
                    
                    log_info(
                        "shadow_comparator_initialized",
                        tenant_id=config.tenant_id,
                        bot_id=config.bot_id,
                        alert_threshold=shadow_alert_threshold,
                        window_size=shadow_window_size,
                        has_overrides=bool(shadow_config_overrides),
                    )
            except Exception as exc:
                log_warning(
                    "shadow_comparator_init_failed",
                    tenant_id=config.tenant_id,
                    bot_id=config.bot_id,
                    error=str(exc),
                )
                self.shadow_comparator = None
        
        self.execution_manager: ExecutionManager = build_execution_manager(
            exchange_name=config.exchange,
            adapter=execution_adapter,
            state_manager=state_manager,
            risk_manager=self.risk_override_store,
            trading_mode=config.trading_mode,
            redis_client=self.redis_client,
            bot_id=config.bot_id,
            reference_prices=self.reference_prices,
            exchange_router=exchange_router,
            reconciler=reconciler,
            adapter_config=adapter_config,
            paper_fill_engine=paper_fill_engine,
            paper_config=paper_config,
            telemetry=self.telemetry,
            telemetry_context=self.telemetry_ctx,
            order_store=self.order_store,
            guard_config=guard_config,
            snapshot_reader=self.snapshot_reader,
            profile_feedback=self.decision_engine.profile_router.record_trade,
        )

        self.risk_worker = RiskWorker(
            redis_client=self.redis_client,
            state_manager=self.state_manager,
            bot_id=config.bot_id,
            exchange=config.exchange,
            tenant_id=config.tenant_id,
            telemetry=self.telemetry,
            telemetry_context=self.telemetry_ctx,
            price_provider=self.reference_prices,
            override_store=self.risk_override_store,
            order_store=self.order_store,
            snapshot_writer=self.snapshots,
            snapshot_key=f"quantgambit:{config.tenant_id}:{config.bot_id}:risk:latest_decision",
            config=RiskWorkerConfig(
                source_stream=decision_stream,
                output_stream=risk_stream,
                consumer_group=risk_group,
                consumer_name=os.getenv("RISK_CONSUMER_NAME") or "risk_worker",
                # Risk parameters - loaded from exchange/bot config via env vars
                risk_per_trade_pct=_env_pct("RISK_PER_TRADE_PCT", 0.005),
                # Use TRADING_CAPITAL_USD as primary source, fallback to PAPER_EQUITY
                account_equity=_env_float("TRADING_CAPITAL_USD", _env_float("PAPER_EQUITY", 100000.0)),
                min_position_size_usd=_env_float("MIN_POSITION_SIZE_USD", 10.0),
                max_positions=_env_int("MAX_POSITIONS", 4),
                max_positions_per_symbol=_env_int("MAX_POSITIONS_PER_SYMBOL", 1),
                # Additional risk limits from config
                max_total_exposure_pct=_env_pct("MAX_TOTAL_EXPOSURE_PCT", 0.50),
                max_exposure_per_symbol_pct=_env_pct("MAX_EXPOSURE_PER_SYMBOL_PCT", 0.20),
                max_positions_per_strategy=_env_int("MAX_POSITIONS_PER_STRATEGY", 0),
                max_daily_loss_pct=_env_pct("MAX_DAILY_DRAWDOWN_PCT", 0.05),
                max_drawdown_pct=_env_pct("MAX_DRAWDOWN_PCT", 0.10),
                max_position_size_usd=_env_float_or_none("MAX_POSITION_SIZE_USD"),
                allow_position_replacement=os.getenv("ALLOW_POSITION_REPLACEMENT", "false").lower() in ("true", "1", "yes"),
                replace_opposite_only=os.getenv("REPLACE_OPPOSITE_ONLY", "true").lower() in ("true", "1", "yes"),
                replace_min_edge_bps=_env_float("REPLACE_MIN_EDGE_BPS", 0.0),
                replace_min_confidence=_env_float("REPLACE_MIN_CONFIDENCE", 0.0),
                replace_min_hold_sec=_env_float("REPLACE_MIN_HOLD_SEC", 0.0),
                include_pending_intents=_env_bool("INCLUDE_PENDING_INTENTS", True),
                trigger_kill_switch_on_guardrail=_env_bool("RISK_TRIGGER_KILL_SWITCH_ON_GUARDRAIL", True),
                flatten_on_guardrail=_env_bool("RISK_FLATTEN_ON_GUARDRAIL", True),
            ),
            latency_tracker=self._latency_tracker,
            kill_switch=self._kill_switch,
        )
        # Create shared idempotency store for execution worker and position guard
        self._idempotency_store = RedisIdempotencyStore(
            self.redis_client.redis,
            bot_id=config.bot_id,
            tenant_id=config.tenant_id,
            audit_store=PostgresIdempotencyStore(timescale_pool) if timescale_pool else None,
            alert_hook=self.alerts.send if self.alerts else None,
        )
        market_type = (os.getenv("MARKET_TYPE") or "").strip().lower()
        max_positions_per_symbol = _env_int("MAX_POSITIONS_PER_SYMBOL", 1)
        default_block_if_position_exists = not (
            market_type == "spot" and max_positions_per_symbol > 1
        )

        self.execution_worker = ExecutionWorker(
            redis_client=self.redis_client,
            execution_manager=self.execution_manager,
            bot_id=config.bot_id,
            exchange=config.exchange,
            tenant_id=config.tenant_id,
            telemetry=self.telemetry,
            telemetry_context=self.telemetry_ctx,
            idempotency_store=self._idempotency_store,
            config=ExecutionWorkerConfig(
                source_stream=risk_stream,
                consumer_group=execution_group,
                consumer_name=os.getenv("EXECUTION_CONSUMER_NAME") or "execution_worker",
                # Execution parameters from config
                max_decision_age_sec=_env_float("MAX_DECISION_AGE_SEC", 60.0),
                min_order_interval_sec=_env_float("MIN_ORDER_INTERVAL_SEC", 60.0),
                block_if_position_exists=_env_bool("BLOCK_IF_POSITION_EXISTS", default_block_if_position_exists),
                enforce_exchange_position_gate=_env_bool("EXECUTION_ENFORCE_EXCHANGE_POSITION_GATE", True),
                max_retries=_env_int("MAX_ORDER_RETRIES", 2),
                allow_position_replacement=os.getenv("ALLOW_POSITION_REPLACEMENT", "false").lower() in ("true", "1", "yes"),
                replace_opposite_only=os.getenv("REPLACE_OPPOSITE_ONLY", "true").lower() in ("true", "1", "yes"),
                hard_max_order_notional_usd=_env_float("EXECUTION_HARD_MAX_ORDER_NOTIONAL_USD", 0.0),
                hard_max_symbol_notional_usd=_env_float("EXECUTION_HARD_MAX_SYMBOL_NOTIONAL_USD", 0.0),
                exit_min_hold_sec=_env_float("EXIT_SIGNAL_MIN_HOLD_SEC", 0.0),
                exit_enforce_fee_check=_env_bool("EXIT_SIGNAL_ENFORCE_FEE_CHECK", True),
                dedupe_ttl_sec=_env_int("EXECUTION_DEDUPE_TTL_SEC", 300),
                exit_dedupe_ttl_sec=_env_int("EXIT_DEDUPE_TTL_SEC", 30),
                entry_execution_mode=os.getenv("ENTRY_EXECUTION_MODE", "market").strip().lower(),
                entry_maker_fill_window_ms=_env_int("ENTRY_MAKER_FILL_WINDOW_MS", 800),
                entry_maker_max_reposts=_env_int("ENTRY_MAKER_MAX_REPOSTS", 1),
                entry_maker_price_offset_ticks=_env_int("ENTRY_MAKER_PRICE_OFFSET_TICKS", 0),
                entry_maker_fallback_to_market=_env_bool("ENTRY_MAKER_FALLBACK_TO_MARKET", True),
                entry_maker_skip_cooldown_ms=_env_int("ENTRY_MAKER_SKIP_COOLDOWN_MS", 2000),
                entry_stop_out_cooldown_ms=_env_int("ENTRY_STOP_OUT_COOLDOWN_MS", 60000),
                entry_max_attempts_per_symbol_per_min=_env_int("ENTRY_MAX_ATTEMPTS_PER_SYMBOL_PER_MIN", 12),
                entry_maker_enable_symbols={
                    s.strip().upper() for s in (os.getenv("ENTRY_MAKER_ENABLE_BY_SYMBOL", "") or "").split(",") if s.strip()
                } or None,
                entry_partial_accept=_env_bool("ENTRY_PARTIAL_ACCEPT", True),
                entry_min_fill_notional_usd=_env_float("ENTRY_MIN_FILL_NOTIONAL_USD", 10.0),
                entry_max_spread_bps=_env_float("ENTRY_MAX_SPREAD_BPS", 20.0),
                entry_max_spread_ticks=_env_int("ENTRY_MAX_SPREAD_TICKS", 0),
                entry_max_reference_age_ms=_env_int("ENTRY_MAX_REFERENCE_AGE_MS", 1500),
                entry_max_orderbook_age_ms=_env_int("ENTRY_MAX_ORDERBOOK_AGE_MS", 1500),
                market_type=config.market_type,
                entry_auto_taker_edge_multiple=_env_float("ENTRY_AUTO_TAKER_EDGE_MULTIPLE", 8.0),
                entry_auto_taker_max_spread_bps=_env_float("ENTRY_AUTO_TAKER_MAX_SPREAD_BPS", 0.2),
                entry_auto_force_market_ttw_sec=_env_float("ENTRY_AUTO_FORCE_MARKET_TTW_SEC", 25.0),
                execution_experiment_id=(os.getenv("EXECUTION_EXPERIMENT_ID", "maker-first-v1").strip() or "maker-first-v1"),
            ),
            kill_switch=self._kill_switch,
            latency_tracker=self._latency_tracker,
            trading_mode_manager=self.trading_mode_manager,
        )
        # Per-bot position guardian - disabled by default when using tenant guardian
        self.position_guard_enabled = os.getenv("POSITION_GUARD_ENABLED", "false").lower() in ("true", "1", "yes")
        self.position_guard_worker = None
        self.position_guard_config = None
        if self.position_guard_enabled:
            position_guard_config = PositionGuardConfig(
                interval_sec=float(os.getenv("POSITION_GUARD_INTERVAL_SEC", "1.0")),
                max_position_age_sec=float(os.getenv("POSITION_GUARD_MAX_AGE_SEC", "0.0")),
                trailing_stop_bps=float(os.getenv("POSITION_GUARD_TRAILING_BPS", "30.0")),
                trailing_activation_bps=float(os.getenv("POSITION_GUARD_TRAILING_ACTIVATION_BPS", "15.0")),
                trailing_min_hold_sec=float(os.getenv("POSITION_GUARD_TRAILING_MIN_HOLD_SEC", "0.0")),
                breakeven_activation_bps=float(os.getenv("POSITION_GUARD_BREAKEVEN_ACTIVATION_BPS", "10.0")),
                breakeven_buffer_bps=float(os.getenv("POSITION_GUARD_BREAKEVEN_BUFFER_BPS", "2.0")),
                breakeven_min_hold_sec=float(os.getenv("POSITION_GUARD_BREAKEVEN_MIN_HOLD_SEC", "0.0")),
                profit_lock_activation_bps=float(os.getenv("POSITION_GUARD_PROFIT_LOCK_ACTIVATION_BPS", "0.0")),
                profit_lock_retrace_bps=float(os.getenv("POSITION_GUARD_PROFIT_LOCK_RETRACE_BPS", "0.0")),
                profit_lock_min_hold_sec=float(os.getenv("POSITION_GUARD_PROFIT_LOCK_MIN_HOLD_SEC", "0.0")),
                verify_exchange_protection=os.getenv("POSITION_GUARD_VERIFY_EXCHANGE_PROTECTION", "true").lower()
                in {"1", "true", "yes"},
                protection_grace_sec=float(os.getenv("POSITION_GUARD_PROTECTION_GRACE_SEC", "5.0")),
                require_protection=os.getenv("POSITION_GUARD_REQUIRE_PROTECTION", "true").lower() in {"1", "true", "yes"},
                require_stop_loss=os.getenv("POSITION_GUARD_REQUIRE_STOP_LOSS", "true").lower() in {"1", "true", "yes"},
                flatten_all_on_protection_failure=os.getenv("POSITION_GUARD_FLATTEN_ALL_ON_PROTECTION_FAILURE", "true").lower()
                in {"1", "true", "yes"},
                continuation_gate_enabled=os.getenv("POSITION_CONTINUATION_GATE_ENABLED", "true").lower() in {"1", "true", "yes"},
                continuation_min_confidence=float(os.getenv("POSITION_CONTINUATION_MIN_CONFIDENCE", "0.70")),
                continuation_min_pnl_bps=float(os.getenv("POSITION_CONTINUATION_MIN_PNL_BPS", "10.0")),
                continuation_max_prediction_age_sec=float(os.getenv("POSITION_CONTINUATION_MAX_PREDICTION_AGE_SEC", "20.0")),
                continuation_max_defer_sec=float(os.getenv("POSITION_CONTINUATION_MAX_DEFER_SEC", "90.0")),
                continuation_max_defers=int(os.getenv("POSITION_CONTINUATION_MAX_DEFERS", "60")),
                continuation_symbol_min_confidence=_env_symbol_float_map("POSITION_CONTINUATION_SYMBOL_MIN_CONFIDENCE_JSON"),
                continuation_symbol_min_pnl_bps=_env_symbol_float_map("POSITION_CONTINUATION_SYMBOL_MIN_PNL_BPS_JSON"),
                continuation_symbol_max_defer_sec=_env_symbol_float_map("POSITION_CONTINUATION_SYMBOL_MAX_DEFER_SEC_JSON"),
                tp_limit_exit_enabled=_env_bool("POSITION_GUARD_TP_LIMIT_EXIT_ENABLED", False),
                tp_limit_fill_window_ms=_env_int("POSITION_GUARD_TP_LIMIT_FILL_WINDOW_MS", 800),
                tp_limit_price_buffer_bps=_env_float("POSITION_GUARD_TP_LIMIT_PRICE_BUFFER_BPS", 0.5),
                tp_limit_poll_interval_ms=_env_int("POSITION_GUARD_TP_LIMIT_POLL_INTERVAL_MS", 150),
                tp_limit_time_in_force=os.getenv("POSITION_GUARD_TP_LIMIT_TIME_IN_FORCE", "GTC").strip().upper(),
                tp_limit_exit_reasons=_env_csv_set(
                    "POSITION_GUARD_TP_LIMIT_EXIT_REASONS",
                    "take_profit_hit,profit_lock_retrace,breakeven_stop_hit,trailing_stop_hit,max_hold_exceeded,max_age_exceeded,time_to_work_fail",
                ),
                max_age_hard_sec=_env_float("POSITION_GUARD_MAX_AGE_HARD_SEC", 0.0),
                max_age_confirmations=_env_int("POSITION_GUARD_MAX_AGE_CONFIRMATIONS", 1),
                max_age_recheck_sec=_env_float("POSITION_GUARD_MAX_AGE_RECHECK_SEC", 45.0),
                max_age_extension_sec=_env_float("POSITION_GUARD_MAX_AGE_EXTENSION_SEC", 0.0),
                max_age_max_extensions=_env_int("POSITION_GUARD_MAX_AGE_MAX_EXTENSIONS", 0),
                min_pnl_bps_to_extend=_env_float("POSITION_GUARD_MIN_PNL_BPS_TO_EXTEND", 6.0),
            )
            self.position_guard_config = position_guard_config
            self.position_guard_worker = PositionGuardWorker(
                exchange_client=self.execution_manager.exchange_client,
                position_manager=self.execution_manager.position_manager,
                config=position_guard_config,
                telemetry=self.telemetry,
                telemetry_context=self.telemetry_ctx,
                tenant_id=config.tenant_id,
                bot_id=config.bot_id,
                idempotency_store=self._idempotency_store,
                fee_model=_build_guard_fee_model(config.exchange),
                min_profit_buffer_bps=_env_float("POSITION_GUARD_MIN_PROFIT_BUFFER_BPS", 5.0),
                kill_switch=self._kill_switch,
                snapshot_reader=self.snapshot_reader,
            )
        self.order_reconciler = OrderReconcilerWorker(
            execution_manager=self.execution_manager,
            order_store=self.order_store,
            telemetry=self.telemetry,
            telemetry_context=self.telemetry_ctx,
        )
        self.order_update_consumer = OrderUpdateConsumer(
            redis_client=self.redis_client,
            execution_manager=self.execution_manager,
            telemetry=self.telemetry,
            telemetry_context=self.telemetry_ctx,
        )
        # Import backlog policy config for tiered overflow management
        from quantgambit.io.backlog_policy import BacklogPolicyConfig, StreamBacklogConfig, StreamType
        
        # Backlog thresholds: depth alone doesn't indicate overflow
        # Only lag > 0 indicates consumers are behind
        # High depth with lag=0 is just retention, not overflow
        backlog_config = BacklogPolicyConfig(
            streams={
                market_data_stream: StreamBacklogConfig(
                    stream_type=StreamType.MARKET_DATA,
                    soft_threshold=int(os.getenv("BACKLOG_SOFT_THRESHOLD", "100000")),  # 100k
                    hard_threshold=int(os.getenv("BACKLOG_HARD_THRESHOLD", "200000")),  # 200k
                ),
                feature_stream: StreamBacklogConfig(
                    stream_type=StreamType.FEATURES,
                    soft_threshold=int(os.getenv("BACKLOG_SOFT_THRESHOLD", "100000")),  # 100k
                    hard_threshold=int(os.getenv("BACKLOG_HARD_THRESHOLD", "200000")),  # 200k
                ),
                decision_stream: StreamBacklogConfig(
                    stream_type=StreamType.DECISIONS,
                    soft_threshold=int(os.getenv("DECISION_BACKLOG_SOFT", "20000")),  # 20k
                    hard_threshold=int(os.getenv("DECISION_BACKLOG_HARD", "50000")),  # 50k
                ),
            },
            # Lag thresholds: these are the real indicators of overflow
            lag_soft_threshold=int(os.getenv("LAG_SOFT_THRESHOLD", "100")),   # 100 entries behind
            lag_hard_threshold=int(os.getenv("LAG_HARD_THRESHOLD", "1000")),  # 1000 entries behind
        )
        
        self.health_worker = HealthWorker(
            redis_client=self.redis_client,
            telemetry=self.telemetry,
            telemetry_context=self.telemetry_ctx,
            quality_tracker=self.quality_tracker,
            monotonic_clock=self._monotonic_clock,
            config=HealthWorkerConfig(
                streams=(market_data_stream, feature_stream, decision_stream),
                max_stream_depth=int(os.getenv("HEALTH_MAX_STREAM_DEPTH", "50000")),  # Increased for retention
                backlog_config=backlog_config,
                track_consumer_lag=True,
                trading_mode=config.trading_mode,
                market_type=config.market_type,
                position_guard_enabled=self.position_guard_enabled,
                position_guard_max_age_sec=float(
                    self.position_guard_config.max_position_age_sec if self.position_guard_config is not None else 0.0
                ),
                position_guard_max_age_hard_sec=float(
                    self.position_guard_config.max_age_hard_sec if self.position_guard_config is not None else 0.0
                ),
                position_guard_tp_limit_exit_enabled=bool(
                    self.position_guard_config.tp_limit_exit_enabled if self.position_guard_config is not None else False
                ),
            ),
        )
        if self.market_worker:
            self.market_worker.health_worker = self.health_worker

        self.runtime_state = ControlRuntimeState()
        self.action_handler = ExecutionActionHandler(
            runtime_state=self.runtime_state,
            execution_manager=self.execution_manager,
            redis_client=self.redis_client,
            exchange=config.exchange,
            orderbook_symbols=self.config.orderbook_symbols if hasattr(self.config, "orderbook_symbols") else [],
            orderbook_required=os.getenv("ORDERBOOK_REQUIRED", "true").lower() not in {"0", "false", "no"},
            orderbook_staleness_ms=int(os.getenv("ORDERBOOK_STALENESS_MS", "5000")),
            kill_switch=self._kill_switch,
        )
        self.command_consumer = CommandConsumer(
            redis_client=self.redis_client,
            runtime_state=self.runtime_state,
            action_handler=self.action_handler,
            tenant_id=config.tenant_id,
            bot_id=config.bot_id,
            command_stream=command_stream_name(config.tenant_id, config.bot_id),
            result_stream=command_result_stream_name(config.tenant_id, config.bot_id),
        )
        self.control_manager = ControlManager(
            redis_client=self.redis_client,
            runtime_state=self.runtime_state,
            tenant_id=config.tenant_id,
            bot_id=config.bot_id,
            config=ControlManagerConfig(
                result_stream=command_result_stream_name(config.tenant_id, config.bot_id),
            ),
        )

        self.config_applier = RuntimeConfigApplier(self)
        self.config_watcher = ConfigWatcher(
            redis_client=self.redis_client,
            applier=SafeConfigApplier(
                self.runtime_state,
                self.execution_manager.position_manager,
                self.config_repository,
                self.config_applier,
            ),
        )

        # Initialize quant-grade integration (reconciliation worker)
        # Note: kill_switch and latency_tracker were created earlier and passed to workers
        self.quant: Optional[QuantIntegration] = None
        if self.quant_integration_enabled:
            try:
                self.quant = QuantIntegration(
                    redis_client=redis,
                    tenant_id=config.tenant_id,
                    bot_id=config.bot_id,
                    order_store=OrderStoreAdapter(self.order_store) if self.order_store else None,
                    position_store=PositionStoreAdapter(self.state_manager) if self.state_manager else None,
                    exchange_client=ExchangeClientAdapter(self.execution_manager.exchange_client) if self.execution_manager else None,
                    clock=self._clock,
                )
                # Use the shared instances
                self.quant._kill_switch = self._kill_switch
                self.quant._latency_tracker = self._latency_tracker
                log_info("quant_integration_initialized", tenant_id=config.tenant_id, bot_id=config.bot_id)
            except Exception as exc:
                log_warning("quant_integration_init_failed", error=str(exc))
                self.quant = None

    def _load_shadow_config_overrides(self) -> dict:
        """Load shadow configuration overrides from environment variables.
        
        Shadow mode allows testing alternative configurations in parallel with live.
        Configuration overrides can be specified via environment variables with
        the SHADOW_CONFIG_ prefix.
        
        Feature: trading-pipeline-integration
        Requirements: 4.1 - Support running shadow pipeline with alternative configuration
        
        Returns:
            Dictionary of configuration parameter overrides for shadow pipeline
        """
        overrides = {}
        
        # Load shadow-specific configuration overrides from environment
        # Format: SHADOW_CONFIG_<PARAM_NAME>=<value>
        # Example: SHADOW_CONFIG_SLIPPAGE_BPS=2.0
        for key, value in os.environ.items():
            if key.startswith("SHADOW_CONFIG_"):
                param_name = key[len("SHADOW_CONFIG_"):].lower()
                # Try to parse as number, fall back to string
                try:
                    if "." in value:
                        overrides[param_name] = float(value)
                    else:
                        overrides[param_name] = int(value)
                except ValueError:
                    # Handle boolean strings
                    if value.lower() in {"true", "yes", "1"}:
                        overrides[param_name] = True
                    elif value.lower() in {"false", "no", "0"}:
                        overrides[param_name] = False
                    else:
                        overrides[param_name] = value
        
        # Also support JSON-formatted shadow config
        shadow_config_json = os.getenv("SHADOW_CONFIG_JSON")
        if shadow_config_json:
            try:
                json_overrides = json.loads(shadow_config_json)
                if isinstance(json_overrides, dict):
                    overrides.update(json_overrides)
            except json.JSONDecodeError as exc:
                log_warning("shadow_config_json_parse_failed", error=str(exc))
        
        return overrides

    def _create_shadow_decision_engine(self, config_overrides: dict) -> Optional[DecisionEngine]:
        """Create a shadow decision engine with alternative configuration.
        
        Creates a separate DecisionEngine instance for shadow mode comparison.
        The shadow engine uses the same base configuration as the live engine
        but with optional parameter overrides for testing.
        
        Feature: trading-pipeline-integration
        Requirements: 4.1 - Support running shadow pipeline with alternative configuration
        Requirements: 4.2 - Compare decisions from both pipelines in real-time
        
        Args:
            config_overrides: Dictionary of configuration parameter overrides
            
        Returns:
            DecisionEngine configured for shadow mode, or None if creation fails
        """
        try:
            from quantgambit.config.loss_prevention import load_loss_prevention_config
            
            # Load loss prevention configuration (same as live engine)
            loss_prevention_config = load_loss_prevention_config()
            
            # Apply any shadow-specific overrides to loss prevention config
            # This allows testing different thresholds, gates, etc.
            if config_overrides:
                # Override prediction confidence if specified
                prediction_min_confidence = config_overrides.get(
                    "prediction_min_confidence",
                    float(os.getenv("PREDICTION_MIN_CONFIDENCE", "0.0"))
                )
            else:
                prediction_min_confidence = float(os.getenv("PREDICTION_MIN_CONFIDENCE", "0.0"))
            
            # Get prediction allowed directions (same as live)
            allowed_raw = os.getenv("PREDICTION_ALLOWED_DIRECTIONS", "")
            prediction_allowed_directions = {
                item.strip() for item in allowed_raw.split(",") if item.strip()
            } or None
            
            # Create shadow decision engine with same configuration as live
            # but potentially different parameters from overrides
            shadow_engine = DecisionEngine(
                telemetry=self.telemetry,
                telemetry_context=self.telemetry_ctx,
                prediction_min_confidence=prediction_min_confidence,
                prediction_allowed_directions=prediction_allowed_directions,
                trading_mode_manager=self.trading_mode_manager,
                symbol_characteristics_service=self._symbol_characteristics_service,
                symbol_characteristics_config=self._symbol_characteristics_config,
                data_readiness_config=self._data_readiness_config,
                candle_cache=self.candle_cache,  # Share candle cache with live engine
                # Loss prevention stage configs (same as live unless overridden)
                strategy_trend_alignment_config=loss_prevention_config.strategy_trend_alignment if loss_prevention_config.enabled else None,
                session_filter_config=loss_prevention_config.session_filter if loss_prevention_config.enabled else None,
                ev_gate_config=loss_prevention_config.ev_gate if loss_prevention_config.enabled else None,
                ev_position_sizer_config=loss_prevention_config.ev_position_sizer if loss_prevention_config.enabled else None,
                cost_data_quality_config=loss_prevention_config.cost_data_quality if loss_prevention_config.enabled else None,
                global_gate_config=loss_prevention_config.global_gate if loss_prevention_config.enabled else None,
                cooldown_config=loss_prevention_config.cooldown if loss_prevention_config.enabled else None,
                confirmation_policy_config=load_confirmation_policy_config(config_overrides),
            )
            
            return shadow_engine
            
        except Exception as exc:
            log_warning("shadow_engine_creation_failed", error=str(exc))
            return None

    async def _initialize_equity_from_exchange(self) -> None:
        """Initialize equity and peak_balance from actual exchange balance.
        
        This ensures drawdown calculations use real exchange data, not stale config values.
        For live trading, fetches balance from exchange.
        For paper trading, uses PAPER_EQUITY config.
        
        If MAX_CAPITAL_USD is set, caps the available capital at that amount.
        """
        if not self.state_manager:
            return
        
        async def _clear_live_equity_snapshot(reason: str) -> None:
            try:
                self.state_manager.update_account_state(equity=0.0, peak_balance=0.0)
            except Exception:
                pass
            if self.snapshots:
                try:
                    risk_snapshot_key = f"quantgambit:{self.config.tenant_id}:{self.config.bot_id}:risk:sizing"
                    existing = await self.snapshot_reader.read(risk_snapshot_key) if self.snapshot_reader else {}
                    if existing is None:
                        existing = {}
                    risk_snapshot = {
                        key: existing.get(key)
                        for key in (
                            "limits",
                            "remaining",
                            "exposure",
                            "config",
                            "risk_budget_usd",
                            "risk_multiplier",
                            "size_usd",
                            "total_exposure_usd",
                            "total_exposure_pct",
                            "long_exposure_usd",
                            "short_exposure_usd",
                            "net_exposure_usd",
                            "net_exposure_pct",
                            "symbol_exposure_usd",
                            "strategy_exposure_usd",
                            "max_capital_usd",
                        )
                        if key in existing
                    }
                    risk_snapshot["equity"] = None
                    risk_snapshot["account_balance"] = None
                    risk_snapshot["account_equity"] = None
                    risk_snapshot["peak_balance"] = None
                    risk_snapshot["equity_unavailable_reason"] = reason
                    await self.snapshots.write(risk_snapshot_key, risk_snapshot)
                except Exception as redis_exc:
                    log_warning("equity_clear_redis_update_failed", error=str(redis_exc), reason=reason)

        # Paper trading uses config value
        if self.config.trading_mode == "paper":
            paper_equity = float(os.getenv("PAPER_EQUITY", "100000.0"))
            if self._max_capital_usd:
                paper_equity = min(paper_equity, self._max_capital_usd)
            self.state_manager.update_account_state(equity=paper_equity, peak_balance=paper_equity)
            log_info(
                "equity_initialized_paper",
                equity=paper_equity,
                peak_balance=paper_equity,
                max_capital_usd=self._max_capital_usd,
            )
            return
        
        # Live trading - fetch from exchange
        if not self.execution_manager:
            log_warning("equity_init_no_execution_manager")
            return
        
        exchange_client = self.execution_manager.exchange_client
        if not hasattr(exchange_client, "fetch_balance"):
            log_warning("equity_init_no_fetch_balance", reason="Exchange client does not support fetch_balance")
            await _clear_live_equity_snapshot("no_fetch_balance")
            return
        
        balance_currency = os.getenv("BALANCE_CURRENCY", "USDT")
        
        try:
            exchange_balance = await exchange_client.fetch_balance(balance_currency)
            
            if exchange_balance is None or exchange_balance <= 0:
                log_warning("equity_init_invalid_balance", balance=exchange_balance)
                await _clear_live_equity_snapshot("invalid_balance")
                return
            
            # Apply capital cap for strategy sizing only. Do not overwrite real
            # account equity with the deployable-capital cap.
            available_capital = exchange_balance
            if self._max_capital_usd:
                available_capital = min(exchange_balance, self._max_capital_usd)
            
            # Account state equity should reflect real exchange equity.
            self.state_manager.update_account_state(
                equity=exchange_balance,
                peak_balance=exchange_balance,
            )
            
            log_info(
                "equity_initialized_from_exchange",
                exchange_balance=round(exchange_balance, 2),
                available_capital=round(available_capital, 2),
                peak_balance=round(exchange_balance, 2),
                max_capital_usd=self._max_capital_usd,
                currency=balance_currency,
            )
            
            # Also update Redis snapshot so API shows correct values immediately
            if self.snapshots:
                try:
                    risk_snapshot_key = f"quantgambit:{self.config.tenant_id}:{self.config.bot_id}:risk:sizing"
                    existing = await self.snapshot_reader.read(risk_snapshot_key) if self.snapshot_reader else {}
                    if existing is None:
                        existing = {}
                    risk_snapshot = {
                        key: existing.get(key)
                        for key in (
                            "limits",
                            "remaining",
                            "exposure",
                            "config",
                            "risk_budget_usd",
                            "risk_multiplier",
                            "size_usd",
                            "total_exposure_usd",
                            "total_exposure_pct",
                            "long_exposure_usd",
                            "short_exposure_usd",
                            "net_exposure_usd",
                            "net_exposure_pct",
                            "symbol_exposure_usd",
                            "strategy_exposure_usd",
                        )
                        if key in existing
                    }
                    risk_snapshot["equity"] = exchange_balance
                    risk_snapshot["account_balance"] = exchange_balance
                    risk_snapshot["account_equity"] = exchange_balance
                    risk_snapshot["peak_balance"] = exchange_balance
                    risk_snapshot["deployable_capital"] = available_capital
                    risk_snapshot["max_capital_usd"] = self._max_capital_usd
                    await self.snapshots.write(risk_snapshot_key, risk_snapshot)
                except Exception as redis_exc:
                    log_warning("equity_init_redis_update_failed", error=str(redis_exc))
                    
        except Exception as exc:
            log_warning("equity_init_fetch_failed", error=str(exc))
            await _clear_live_equity_snapshot("fetch_failed")

    async def _reset_stale_drawdown_kill_switch_if_flat(self, open_orders: list | None = None) -> bool:
        """Clear a persisted drawdown kill switch when startup proves the bot is flat and recovered.

        This is intentionally narrow. We only reset if:
        - the active trigger is drawdown-related only
        - there are no open positions
        - there are no open orders
        - current equity is already back at peak_balance
        """
        kill_switch = getattr(self, "_kill_switch", None)
        if not kill_switch or not getattr(kill_switch, "is_active", lambda: False)():
            return False

        try:
            state = kill_switch.get_state()
            triggers = {str(key.value if hasattr(key, "value") else key) for key in (state.triggered_by or {}).keys()}
        except Exception:
            return False

        if not triggers or not triggers.issubset({"equity_drawdown"}):
            return False

        positions = self.state_manager.get_positions() if self.state_manager else []
        if positions:
            return False

        if open_orders is None:
            open_orders = [
                order for order in self.order_store.list_orders() if is_open_status(order.status)
            ] if self.order_store else []
        if open_orders:
            return False

        account_state = self.state_manager.get_account_state() if self.state_manager else None
        equity = float(getattr(account_state, "equity", 0.0) or 0.0)
        peak_balance = float(getattr(account_state, "peak_balance", 0.0) or 0.0)

        if self.snapshot_reader:
            try:
                risk_snapshot_key = f"quantgambit:{self.config.tenant_id}:{self.config.bot_id}:risk:sizing"
                risk_snapshot = await self.snapshot_reader.read(risk_snapshot_key) or {}
                equity = float(risk_snapshot.get("equity") or risk_snapshot.get("account_equity") or equity or 0.0)
                peak_balance = float(risk_snapshot.get("peak_balance") or peak_balance or 0.0)
            except Exception:
                pass

        if equity <= 0 or peak_balance <= 0:
            return False

        tolerance = max(0.01, peak_balance * 0.0001)
        if abs(peak_balance - equity) > tolerance:
            return False

        try:
            await kill_switch.reset("runtime_flat_startup_sanity")
            if self.snapshots:
                risk_snapshot_key = f"quantgambit:{self.config.tenant_id}:{self.config.bot_id}:risk:sizing"
                risk_snapshot = await self.snapshot_reader.read(risk_snapshot_key) or {}
                risk_snapshot["equity"] = equity
                risk_snapshot["account_equity"] = equity
                risk_snapshot["account_balance"] = equity
                risk_snapshot["peak_balance"] = equity
                await self.snapshots.write(risk_snapshot_key, risk_snapshot)
            log_warning(
                "kill_switch_reset_flat_startup_sanity",
                tenant_id=self.config.tenant_id,
                bot_id=self.config.bot_id,
                equity=equity,
                peak_balance=peak_balance,
                trigger=list(triggers),
            )
            return True
        except Exception as exc:
            log_warning("kill_switch_reset_flat_startup_failed", error=str(exc))
            return False

    async def _bootstrap_candle_cache(self) -> None:
        candle_cache = getattr(self, "candle_cache", None)
        redis_client = getattr(self, "redis_client", None)
        if not candle_cache or not redis_client:
            return
        enabled = os.getenv("AMT_CANDLE_CACHE_BOOTSTRAP", "true").lower() in {"1", "true", "yes"}
        if not enabled:
            return
        stream = getattr(self, "candle_stream", None)
        if not stream:
            return
        try:
            limit = int(os.getenv("AMT_CANDLE_BOOTSTRAP_COUNT", "500"))
        except ValueError:
            limit = 500
        if limit <= 0:
            return
        try:
            entries = await redis_client.redis.xrevrange(stream, count=limit)
        except Exception as exc:
            log_warning("candle_cache_bootstrap_failed", error=str(exc))
            return
        if not entries:
            log_info("candle_cache_bootstrap_empty", stream=stream)
            return
        added = 0
        symbols = set()
        for _, data in reversed(entries):
            raw = data.get(b"data") or data.get("data")
            if raw is None:
                continue
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            try:
                event = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if event.get("event_type") != "candle":
                continue
            payload = event.get("payload") or {}
            symbol = payload.get("symbol")
            if not symbol:
                continue
            candle = {
                "open": payload.get("open"),
                "high": payload.get("high"),
                "low": payload.get("low"),
                "close": payload.get("close"),
                "volume": payload.get("volume"),
                "ts": payload.get("timestamp"),
            }
            candle_cache.add_candle(symbol, candle)
            added += 1
            symbols.add(symbol)
        log_info(
            "candle_cache_bootstrap_complete",
            stream=stream,
            entries=len(entries),
            added=added,
            symbols=len(symbols),
        )

    def _get_config_symbols(self) -> list[str]:
        if self.config.orderbook_symbols:
            return list(self.config.orderbook_symbols)
        raw = (
            os.getenv("ORDERBOOK_SYMBOLS")
            or os.getenv("MARKET_DATA_SYMBOLS")
            or os.getenv("TRADE_SYMBOLS")
            or os.getenv("SYMBOLS")
            or ""
        )
        return _parse_symbol_list(raw)

    def _candidate_symbol_keys(self, symbol: str) -> list[str]:
        normalized = _normalize_symbol(symbol)
        if normalized and normalized != symbol:
            return [symbol, normalized]
        return [symbol]

    async def _preload_symbol_characteristics(self) -> None:
        service = getattr(self, "_symbol_characteristics_service", None)
        if not service:
            return
        symbols = self._get_config_symbols()
        if not symbols:
            return
        loaded = 0
        requested = 0
        for symbol in symbols:
            for key in self._candidate_symbol_keys(symbol):
                requested += 1
                try:
                    result = await service.load(key)
                    if result is not None:
                        loaded += 1
                except Exception as exc:
                    log_warning(
                        "symbol_characteristics_preload_failed",
                        symbol=key,
                        error=str(exc),
                    )
        log_info(
            "symbol_characteristics_preload_complete",
            symbols=len(symbols),
            requested=requested,
            loaded=loaded,
        )

    async def _symbol_characteristics_persist_loop(self) -> None:
        interval_sec = _env_float("SYMBOL_CHARACTERISTICS_PERSIST_INTERVAL_SEC", 30.0)
        threshold_pct = _env_float("SYMBOL_CHARACTERISTICS_PERSIST_THRESHOLD_PCT", 0.20)
        if interval_sec <= 0:
            return
        while True:
            await asyncio.sleep(interval_sec)
            if not self._symbol_characteristics_service:
                continue
            try:
                symbols = self._symbol_characteristics_service.get_all_symbols()
                persisted = 0
                for symbol in symbols:
                    if await self._symbol_characteristics_service.persist_if_changed(symbol, threshold_pct):
                        persisted += 1
                if persisted:
                    log_info(
                        "symbol_characteristics_persisted_batch",
                        count=persisted,
                        symbols=len(symbols),
                    )
            except Exception as exc:
                log_warning("symbol_characteristics_persist_error", error=str(exc))

    async def start(self) -> None:
        log_info("runtime_starting", tenant_id=self.config.tenant_id, bot_id=self.config.bot_id)
        
        # Load trading mode configuration from Redis
        trading_mode_manager = getattr(self, "trading_mode_manager", None)
        if trading_mode_manager is not None:
            await trading_mode_manager.load()
        else:
            # Some integration tests construct Runtime via __new__ and only set a subset of attributes.
            log_warning("runtime_missing_trading_mode_manager", tenant_id=self.config.tenant_id, bot_id=self.config.bot_id)
        
        # Initialize equity from exchange FIRST before any risk checks
        await self._initialize_equity_from_exchange()

        # Hard no-trade gate (requested): keep trading disabled until test suite is green.
        # Uses persistent kill-switch so it blocks execution even in TRADING_MODE=live.
        trading_disabled = os.getenv("TRADING_DISABLED", "false").lower() in ("true", "1", "yes")
        runtime_state = getattr(self, "runtime_state", None)
        if runtime_state is not None:
            runtime_state.trading_disabled = trading_disabled
        if trading_disabled and self._kill_switch and hasattr(self._kill_switch, "trigger"):
            try:
                from quantgambit.core.risk.kill_switch import KillSwitchTrigger

                await self._kill_switch.trigger(
                    KillSwitchTrigger.MANUAL,
                    message="TRADING_DISABLED=true (tests not green)",
                )
                log_warning("trading_disabled_kill_switch_armed", reason="TRADING_DISABLED=true")
            except Exception as exc:
                log_warning("trading_disabled_kill_switch_failed", error=str(exc))
        
        await self._prune_warmup_keys()
        await self.risk_override_store.load()
        await self._check_config_drift()
        await self._preload_reference_prices()  # Pre-load prices before position restore
        await self._restore_positions_from_timescale()
        await self._sync_positions_from_exchange()  # Reconcile with exchange (source of truth)
        await self._hydrate_positions_from_intents()
        await self._restore_order_snapshot_from_timescale()
        await self._bootstrap_candle_cache()
        await self._preload_symbol_characteristics()
        order_count = await self.order_store.load()
        idempotency_replayed = 0
        idempotency_store = None
        if hasattr(self, "execution_worker") and self.execution_worker:
            idempotency_store = getattr(self.execution_worker, "idempotency_store", None)
        if idempotency_store and hasattr(idempotency_store, "replay_recent_claims"):
            replay_hours = float(os.getenv("IDEMPOTENCY_REPLAY_HOURS", "6"))
            replay_limit = int(os.getenv("IDEMPOTENCY_REPLAY_LIMIT", "1000"))
            try:
                idempotency_replayed = await idempotency_store.replay_recent_claims(
                    replay_hours,
                    replay_limit,
                )
            except Exception as exc:
                log_warning("idempotency_replay_failed", error=str(exc))
        replay_hours = float(os.getenv("ORDER_EVENT_REPLAY_HOURS", "6"))
        replay_limit = int(os.getenv("ORDER_EVENT_REPLAY_LIMIT", "500"))
        replayed = 0
        if replay_limit > 0 and hasattr(self.order_store, "replay_recent_events"):
            try:
                replayed = await self.order_store.replay_recent_events(replay_hours, replay_limit)
            except Exception as exc:
                log_warning("order_event_replay_failed", error=str(exc))
        await self._recover_pending_intents()
        open_orders = [
            order for order in self.order_store.list_orders() if is_open_status(order.status)
        ]
        log_info(
            "order_store_loaded",
            tenant_id=self.config.tenant_id,
            bot_id=self.config.bot_id,
            count=order_count,
            open_orders=len(open_orders),
            replayed_events=replayed,
            idempotency_replayed=idempotency_replayed,
        )
        if open_orders:
            try:
                await self.order_reconciler.reconcile_once()
                log_info(
                    "order_store_reconciled",
                    tenant_id=self.config.tenant_id,
                    bot_id=self.config.bot_id,
                    open_orders=len(open_orders),
                )
            except Exception as exc:
                log_warning(
                    "order_store_reconcile_failed",
                    tenant_id=self.config.tenant_id,
                    bot_id=self.config.bot_id,
                    error=str(exc),
                )
        if not self.market_worker:
            log_warning("market_worker_missing", tenant_id=self.config.tenant_id, bot_id=self.config.bot_id)
        if not self.order_update_worker:
            log_warning("order_update_worker_missing", tenant_id=self.config.tenant_id, bot_id=self.config.bot_id)
        if not self.orderbook_feed_worker:
            log_warning("orderbook_feed_worker_missing", tenant_id=self.config.tenant_id, bot_id=self.config.bot_id)
        if self.trade_enabled and not self.trade_feed_worker and not self.trade_worker:
            log_warning("trade_feed_worker_missing", tenant_id=self.config.tenant_id, bot_id=self.config.bot_id)
        
        # Initialize kill switch (load state from Redis)
        if self._kill_switch:
            try:
                await self._kill_switch.initialize()
                await self._reset_stale_drawdown_kill_switch_if_flat(open_orders=open_orders)
                if self._kill_switch.is_active():
                    log_warning(
                        "kill_switch_active_on_startup",
                        tenant_id=self.config.tenant_id,
                        bot_id=self.config.bot_id,
                        state=self._kill_switch.get_state().triggered_by,
                    )
            except Exception as exc:
                log_warning("kill_switch_init_failed", error=str(exc))
        live_perp_guard_required = (
            str(self.config.trading_mode or "").strip().lower() == "live"
            and str(self.config.market_type or "").strip().lower() not in {"", "spot"}
        )
        guard_max_age_sec = float(self.position_guard_config.max_position_age_sec) if self.position_guard_config is not None else 0.0
        guard_max_age_hard_sec = float(self.position_guard_config.max_age_hard_sec) if self.position_guard_config is not None else 0.0
        if live_perp_guard_required and (not self.position_guard_enabled or guard_max_age_sec <= 0):
            log_warning(
                "position_guard_live_misconfigured",
                tenant_id=self.config.tenant_id,
                bot_id=self.config.bot_id,
                trading_mode=self.config.trading_mode,
                market_type=self.config.market_type,
                position_guard_enabled=self.position_guard_enabled,
                max_position_age_sec=guard_max_age_sec,
                max_age_hard_sec=guard_max_age_hard_sec,
                env_file=os.getenv("ENV_FILE"),
            )
        
        # Start quant-grade integration (reconciliation worker, stats publishing)
        if self.quant:
            try:
                await self.quant.start()
                log_info("quant_integration_started", tenant_id=self.config.tenant_id, bot_id=self.config.bot_id)
            except Exception as exc:
                log_warning("quant_integration_start_failed", error=str(exc))
        
        # Start DecisionRecorder periodic flush (ensures decisions are persisted even if batch not full)
        # Feature: trading-pipeline-integration
        # Requirements: 2.2 - Batch decision records for efficient database writes
        decision_recorder = getattr(self, "decision_recorder", None)
        if decision_recorder:
            try:
                await decision_recorder.start_periodic_flush()
                log_info("decision_recorder_started")
            except Exception as exc:
                log_warning("decision_recorder_start_failed", error=str(exc))
        
        tasks = [
            _guarded_task(self.command_consumer.start, "command_consumer"),
            _guarded_task(self.control_manager.run, "control_manager"),
            _guarded_task(self.config_watcher.start, "config_watcher"),
            _guarded_task(self._config_flush_loop, "config_flush"),
            _guarded_task(self._override_cleanup_loop, "override_cleanup"),
        ]
        if self.market_worker:
            tasks.append(_guarded_task(self.market_worker.run, "market_worker"))
        if self.trade_feed_worker:
            tasks.append(_guarded_task(self.trade_feed_worker.run, "trade_feed_worker"))
        if self.trade_worker:
            tasks.append(_guarded_task(self.trade_worker.run, "trade_worker"))
        if self.orderbook_feed_worker:
            tasks.append(_guarded_task(self.orderbook_feed_worker.run, "orderbook_feed_worker"))
        if self.order_update_worker:
            tasks.append(_guarded_task(self.order_update_worker.run, "order_update_worker"))
        tasks.append(_guarded_task(self.orderbook_worker.run, "orderbook_worker"))
        if self.candle_worker:
            tasks.append(_guarded_task(self.candle_worker.run, "candle_worker"))
        tasks.append(_guarded_task(self.feature_worker.run, "feature_worker"))
        tasks.append(_guarded_task(self.decision_worker.run, "decision_worker"))
        tasks.append(_guarded_task(self.risk_worker.run, "risk_worker"))
        tasks.append(_guarded_task(self.execution_worker.run, "execution_worker"))
        if self.position_guard_worker:
            tasks.append(_guarded_task(self.position_guard_worker.run, "position_guard_worker"))
        tasks.append(_guarded_task(self.order_update_consumer.run, "order_update_consumer"))
        tasks.append(_guarded_task(self.order_reconciler.run, "order_reconciler"))
        tasks.append(_guarded_task(self.health_worker.run, "health_worker"))
        if self.positions_snapshot_interval > 0:
            tasks.append(_guarded_task(self._positions_snapshot_loop, "positions_snapshot_loop"))
        if self.exchange_positions_sync_interval > 0:
            tasks.append(_guarded_task(self._exchange_positions_sync_loop, "exchange_positions_sync_loop"))
        tasks.append(_guarded_task(self._execution_sync_loop, "execution_sync_loop"))
        # Equity refresh loop for live trading
        equity_refresh_interval = float(os.getenv("EQUITY_REFRESH_INTERVAL_SEC", "30.0"))
        if self.config.trading_mode == "live" and equity_refresh_interval > 0:
            tasks.append(_guarded_task(self._equity_refresh_loop, "equity_refresh_loop"))
        # Intent expiry loop to prevent stuck intents from blocking trading
        tasks.append(_guarded_task(self._intent_expiry_loop, "intent_expiry_loop"))
        tasks.append(_guarded_task(self._symbol_characteristics_persist_loop, "symbol_characteristics_persist_loop"))
        
        # Kill switch refresh loop to detect external triggers
        tasks.append(_guarded_task(self._kill_switch_refresh_loop, "kill_switch_refresh_loop"))
        
        # State snapshot loop for warm start availability
        # Feature: trading-pipeline-integration
        # Requirements: 8.5 - Support point-in-time state snapshots
        if self._state_snapshot_enabled and self.warm_start_loader:
            tasks.append(_guarded_task(self._state_snapshot_loop, "state_snapshot_loop"))
        
        # Store coroutines for graceful shutdown (will be converted to tasks by gather)
        self._running_coroutines = tasks
        
        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            log_info("runtime_shutdown_initiated", tenant_id=self.config.tenant_id, bot_id=self.config.bot_id)
            raise

    async def shutdown(self, timeout_sec: float = 30.0) -> None:
        """
        Gracefully shutdown the runtime.
        
        Shutdown sequence:
        1. Trigger kill switch to prevent new trades
        2. Cancel all pending intents
        3. Wait for open orders to settle (with timeout)
        4. Stop all background tasks
        5. Close connections
        
        Args:
            timeout_sec: Maximum time to wait for graceful shutdown
        """
        log_info("runtime_shutdown_starting", tenant_id=self.config.tenant_id, bot_id=self.config.bot_id)
        
        # 1. Trigger kill switch to prevent new trades
        if self._kill_switch:
            try:
                from quantgambit.core.risk.kill_switch import KillSwitchTrigger
                await self._kill_switch.trigger(
                    KillSwitchTrigger.MANUAL,
                    "Graceful shutdown initiated",
                )
                log_info("shutdown_kill_switch_triggered")
            except Exception as exc:
                log_warning("shutdown_kill_switch_failed", error=str(exc))
        
        # 2. Cancel all pending intents
        if self.order_store:
            try:
                pending_intents = await self.order_store.load_pending_intents()
                for intent in pending_intents:
                    await self.order_store.remove_pending_intent(intent.intent_id)
                log_info("shutdown_pending_intents_cancelled", count=len(pending_intents))
            except Exception as exc:
                log_warning("shutdown_cancel_intents_failed", error=str(exc))
        
        # 3. Wait for open orders to settle (with timeout)
        if self.execution_manager and self.execution_manager.exchange_client:
            try:
                loop = asyncio.get_running_loop()
                deadline = loop.time() + float(timeout_sec)

                async def _sleep(delay_sec: float) -> None:
                    # Avoid relying on asyncio.sleep() directly. Some tests patch it,
                    # and we still need to yield control for other tasks (e.g., order
                    # update consumers) during shutdown.
                    fut = loop.create_future()
                    loop.call_later(max(0.0, float(delay_sec)), fut.set_result, None)
                    await fut

                while loop.time() < deadline:
                    open_orders = [
                        order for order in self.order_store.list_orders()
                        if is_open_status(order.status)
                    ]
                    if not open_orders:
                        log_info("shutdown_all_orders_settled")
                        break
                    log_info("shutdown_waiting_for_orders", count=len(open_orders))
                    remaining = max(0.0, deadline - loop.time())
                    await _sleep(min(1.0, remaining))
                else:
                    log_warning("shutdown_orders_timeout", remaining_orders=len(open_orders))
            except Exception as exc:
                log_warning("shutdown_order_wait_failed", error=str(exc))
        
        # 4. Stop all background tasks
        # Note: Tasks are managed by asyncio.gather, we signal shutdown via CancelledError
        log_info("shutdown_tasks_signalled")
        
        # 5. Stop quant integration (reconciliation worker)
        if self.quant:
            try:
                await self.quant.stop()
                log_info("shutdown_quant_integration_stopped")
            except Exception as exc:
                log_warning("shutdown_quant_stop_failed", error=str(exc))
        
        # 6. Flush DecisionRecorder (ensure all recorded decisions are persisted)
        # Feature: trading-pipeline-integration
        # Requirements: 2.2 - Batch decision records for efficient database writes
        if getattr(self, "decision_recorder", None):
            try:
                await self.decision_recorder.stop_periodic_flush()
                log_info("shutdown_decision_recorder_flushed")
            except Exception as exc:
                log_warning("shutdown_decision_recorder_flush_failed", error=str(exc))
        
        # 7. Close alerts client
        if self.alerts:
            try:
                await self.alerts.close()
                log_info("shutdown_alerts_closed")
            except Exception as exc:
                log_warning("shutdown_alerts_close_failed", error=str(exc))
        
        log_info("runtime_shutdown_complete", tenant_id=self.config.tenant_id, bot_id=self.config.bot_id)

    async def _positions_snapshot_loop(self) -> None:
        if not self.telemetry or not self.telemetry_context:
            return
        if not self.execution_manager:
            return
        interval = max(1.0, self.positions_snapshot_interval)
        while True:
            try:
                await self.execution_manager._emit_positions_snapshot()
            except Exception as exc:
                log_warning("positions_snapshot_failed", error=str(exc))
            await asyncio.sleep(interval)

    async def _exchange_positions_sync_loop(self) -> None:
        if not self.execution_manager:
            return
        interval = max(5.0, self.exchange_positions_sync_interval)
        while True:
            try:
                await self._sync_positions_from_exchange()
                await self.execution_manager._emit_positions_snapshot()
            except Exception as exc:
                log_warning("exchange_positions_sync_failed", error=str(exc))
            await asyncio.sleep(interval)

    async def _execution_sync_loop(self) -> None:
        interval = _env_float("EXECUTION_SYNC_INTERVAL_SEC", 20.0)
        if interval <= 0:
            return
        interval = max(5.0, interval)
        log_info("execution_sync_loop_started", interval_sec=interval)
        while True:
            await self._execution_sync_tick()
            await asyncio.sleep(interval)

    async def _execution_sync_tick(self) -> None:
        if not self.execution_manager:
            log_warning("execution_sync_disabled", reason="execution_manager_missing")
            return
        if not self._timescale_pool:
            log_warning("execution_sync_disabled", reason="timescale_pool_missing")
            return
        if not self.redis_client:
            log_warning("execution_sync_disabled", reason="redis_missing")
            return
        exchange_client = self.execution_manager.exchange_client
        if not exchange_client or not hasattr(exchange_client, "fetch_executions"):
            log_warning("execution_sync_unavailable", reason="exchange_client_missing")
            return
        lookback_sec = max(30.0, _env_float("EXECUTION_SYNC_LOOKBACK_SEC", 300.0))
        overlap_sec = max(0.0, _env_float("EXECUTION_SYNC_OVERLAP_SEC", 30.0))
        limit = max(50, int(os.getenv("EXECUTION_SYNC_LIMIT", "200")))
        key = f"quantgambit:{self.config.tenant_id}:{self.config.bot_id}:execution_sync:last_ms"
        symbols = self._get_config_symbols()
        if not symbols:
            log_warning("execution_sync_no_symbols")
            return
        try:
            await self._ensure_execution_ledger_schema()
            raw_last = await self.redis_client.redis.get(key)
            last_ms = int(raw_last) if raw_last else None
            now_ms = int(time.time() * 1000)
            if last_ms is None:
                since_ms = now_ms - int(lookback_sec * 1000)
            else:
                since_ms = max(0, last_ms - int(overlap_sec * 1000))
            result = await self._sync_executions_once(
                symbols=symbols,
                since_ms=since_ms,
                limit=limit,
            )
            if result.get("max_ts_ms"):
                await self.redis_client.redis.set(key, int(result["max_ts_ms"]))
            elif last_ms is None:
                await self.redis_client.redis.set(key, now_ms - int(overlap_sec * 1000))
        except Exception as exc:
            log_warning("execution_sync_failed", error=str(exc))

    async def _sync_executions_once(
        self,
        symbols: list[str],
        since_ms: int,
        limit: int,
    ) -> dict:
        exchange_client = self.execution_manager.exchange_client
        max_pages = max(1, _env_int("EXECUTION_SYNC_MAX_PAGES", 5))
        trades: list[dict] = []
        for symbol in symbols:
            try:
                fetched = await self._fetch_executions_paginated(
                    exchange_client=exchange_client,
                    symbol=symbol,
                    since_ms=since_ms,
                    limit=limit,
                    max_pages=max_pages,
                )
                for trade in fetched or []:
                    if isinstance(trade, dict):
                        trade = dict(trade)
                    else:
                        continue
                    trade.setdefault("symbol", symbol)
                    trades.append(trade)
            except Exception as exc:
                log_warning("execution_sync_fetch_failed", symbol=symbol, error=str(exc))
        if not trades:
            return {"synced": 0, "max_ts_ms": None}
        fetched_max_ts = None
        for trade in trades:
            if not isinstance(trade, dict):
                continue
            info = trade.get("info") if isinstance(trade.get("info"), dict) else {}
            ts_ms = _coerce_int(trade.get("timestamp") or info.get("execTime"))
            if ts_ms is None:
                continue
            fetched_max_ts = ts_ms if fetched_max_ts is None else max(fetched_max_ts, ts_ms)
        ledger_upserted = await self._upsert_execution_ledger_rows(trades)
        aggregates = _aggregate_execution_sync_trades(trades)
        if not aggregates:
            return {"synced": 0, "max_ts_ms": fetched_max_ts}
        order_ids = [agg["order_id"] for agg in aggregates if agg.get("order_id")]
        existing_summaries = await self._fetch_latest_order_summaries(order_ids)
        inserted = 0
        upgraded = 0
        max_ts_ms = fetched_max_ts
        for agg in aggregates:
            order_id = agg.get("order_id")
            if not order_id:
                continue
            existing = existing_summaries.get(order_id)
            if not self._should_upsert_exchange_sync(agg, existing):
                continue
            ts_ms = agg.get("timestamp_ms")
            if ts_ms is not None:
                max_ts_ms = ts_ms if max_ts_ms is None else max(max_ts_ms, ts_ms)
            timestamp = ts_ms / 1000.0 if ts_ms else None
            await self.order_store.record(
                symbol=agg.get("symbol") or "",
                side=agg.get("side") or "",
                size=float(agg.get("total_qty") or 0.0),
                status="filled",
                order_id=order_id,
                client_order_id=agg.get("client_order_id"),
                reason="exchange_sync",
                fill_price=agg.get("avg_price"),
                fee_usd=agg.get("total_fees_usd"),
                filled_size=agg.get("total_qty"),
                remaining_size=0.0,
                timestamp=timestamp,
                source="exchange_sync",
                exchange=self.config.exchange,
                event_type="exchange_sync",
                persist=True,
            )
            client_order_id = agg.get("client_order_id")
            if client_order_id and hasattr(self.order_store, "record_intent"):
                await self.order_store.record_intent(
                    intent_id=str(uuid.uuid4()),
                    symbol=agg.get("symbol") or "",
                    side=agg.get("side") or "",
                    size=float(agg.get("total_qty") or 0.0),
                    client_order_id=client_order_id,
                    status="filled",
                    order_id=order_id,
                    last_error="exchange_sync",
                )
            inserted += 1
            if existing is not None:
                upgraded += 1
        log_info(
            "execution_sync_complete",
            since_ms=since_ms,
            fetched=len(trades),
            aggregated=len(aggregates),
            inserted=inserted,
            upgraded=upgraded,
            ledger_upserted=ledger_upserted,
        )
        return {"synced": inserted, "max_ts_ms": max_ts_ms}

    async def _fetch_latest_order_summaries(self, order_ids: list[str]) -> dict[str, dict]:
        if not order_ids or not self._timescale_pool:
            return {}
        async with self._timescale_pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT DISTINCT ON (payload->>'order_id') "
                "(payload->>'order_id') AS order_id, "
                "(payload->>'filled_size') AS filled_size, "
                "(payload->>'fill_price') AS fill_price, "
                "(payload->>'fee_usd') AS fee_usd, "
                "(payload->>'total_fees_usd') AS total_fees_usd, "
                "(payload->>'reason') AS reason "
                "FROM order_events "
                "WHERE tenant_id=$1 AND bot_id=$2 "
                "AND (payload->>'order_id') = ANY($3::text[]) "
                "ORDER BY (payload->>'order_id'), ts DESC",
                self.config.tenant_id,
                self.config.bot_id,
                order_ids,
            )
        summaries: dict[str, dict] = {}
        for row in rows:
            oid = row.get("order_id")
            if not oid:
                continue
            summaries[str(oid)] = {
                "filled_size": _coerce_float(row.get("filled_size")),
                "fill_price": _coerce_float(row.get("fill_price")),
                "fee_usd": _coerce_float(row.get("fee_usd")),
                "total_fees_usd": _coerce_float(row.get("total_fees_usd")),
                "reason": row.get("reason"),
            }
        return summaries

    async def _fetch_executions_paginated(
        self,
        exchange_client,
        symbol: str,
        since_ms: int,
        limit: int,
        max_pages: int,
    ) -> list[dict]:
        all_trades: list[dict] = []
        cursor_since = since_ms
        for _ in range(max_pages):
            fetched = await exchange_client.fetch_executions(
                symbol=symbol,
                since_ms=cursor_since,
                limit=limit,
            )
            items = [t for t in (fetched or []) if isinstance(t, dict)]
            if not items:
                break
            all_trades.extend(items)
            max_ts = None
            for t in items:
                info = t.get("info") if isinstance(t.get("info"), dict) else {}
                ts = _coerce_int(t.get("timestamp") or info.get("execTime"))
                if ts is not None:
                    max_ts = ts if max_ts is None else max(max_ts, ts)
            if max_ts is None:
                break
            # Advance one millisecond to avoid refetching identical boundary rows.
            cursor_since = max_ts + 1
            if len(items) < limit:
                break
        return all_trades

    async def _ensure_execution_ledger_schema(self) -> None:
        if self._execution_ledger_schema_ready or not self._timescale_pool:
            return
        async with self._timescale_pool.acquire() as conn:
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS execution_ledger (
                    tenant_id text NOT NULL,
                    bot_id text NOT NULL,
                    exchange text NOT NULL,
                    exec_id text NOT NULL,
                    order_id text,
                    client_order_id text,
                    symbol text NOT NULL,
                    side text,
                    exec_price double precision,
                    exec_qty double precision,
                    exec_value double precision,
                    exec_fee_usd double precision,
                    exec_time_ms bigint,
                    source text NOT NULL DEFAULT 'execution_sync',
                    raw jsonb NOT NULL DEFAULT '{}'::jsonb,
                    ingested_at timestamptz NOT NULL DEFAULT now(),
                    updated_at timestamptz NOT NULL DEFAULT now(),
                    PRIMARY KEY (tenant_id, bot_id, exchange, exec_id)
                )
                """
            )
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS execution_ledger_order_idx ON execution_ledger(tenant_id, bot_id, exchange, order_id)"
            )
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS execution_ledger_time_idx ON execution_ledger(tenant_id, bot_id, exchange, exec_time_ms DESC)"
            )
        self._execution_ledger_schema_ready = True

    async def _upsert_execution_ledger_rows(self, trades: list[dict]) -> int:
        if not trades or not self._timescale_pool:
            return 0
        rows = []
        for trade in trades:
            if not isinstance(trade, dict):
                continue
            info = trade.get("info") if isinstance(trade.get("info"), dict) else {}
            order_id = (
                trade.get("order")
                or info.get("orderId")
                or info.get("orderID")
                or info.get("order_id")
            )
            exec_id = (
                trade.get("id")
                or info.get("execId")
                or info.get("tradeId")
                or info.get("execID")
            )
            symbol = _normalize_symbol(str(trade.get("symbol") or info.get("symbol") or ""))
            if not symbol:
                continue
            price = _coerce_float(trade.get("price") or info.get("execPrice"))
            qty = _coerce_float(trade.get("amount") or info.get("execQty"))
            cost = _coerce_float(trade.get("cost") or info.get("execValue"))
            if cost is None and price is not None and qty is not None:
                cost = price * qty
            fee = trade.get("fee") if isinstance(trade.get("fee"), dict) else {}
            fee_usd = _coerce_float((fee or {}).get("cost")) if isinstance(fee, dict) else None
            if fee_usd is None:
                fee_usd = _coerce_float(info.get("execFee") or info.get("fee"))
            ts_ms = _coerce_int(trade.get("timestamp") or info.get("execTime"))
            client_order_id = (
                info.get("orderLinkId")
                or info.get("orderLinkID")
                or info.get("clientOrderId")
                or trade.get("clientOrderId")
            )
            side = (trade.get("side") or info.get("side") or "").lower() or None
            if not exec_id:
                # Stable fallback when exchange omits exec id.
                fallback = f"{order_id}|{symbol}|{ts_ms}|{price}|{qty}|{client_order_id}"
                exec_id = f"fallback:{hashlib.sha256(fallback.encode('utf-8')).hexdigest()}"
            rows.append(
                (
                    self.config.tenant_id,
                    self.config.bot_id,
                    self.config.exchange,
                    str(exec_id),
                    str(order_id) if order_id else None,
                    str(client_order_id) if client_order_id else None,
                    symbol,
                    side,
                    price,
                    qty,
                    cost,
                    fee_usd,
                    ts_ms,
                    "execution_sync",
                    json.dumps(trade),
                )
            )
        if not rows:
            return 0
        async with self._timescale_pool.acquire() as conn:
            await conn.executemany(
                """
                INSERT INTO execution_ledger (
                    tenant_id, bot_id, exchange, exec_id, order_id, client_order_id,
                    symbol, side, exec_price, exec_qty, exec_value, exec_fee_usd,
                    exec_time_ms, source, raw
                )
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15::jsonb)
                ON CONFLICT (tenant_id, bot_id, exchange, exec_id)
                DO UPDATE SET
                    order_id = COALESCE(EXCLUDED.order_id, execution_ledger.order_id),
                    client_order_id = COALESCE(EXCLUDED.client_order_id, execution_ledger.client_order_id),
                    symbol = COALESCE(EXCLUDED.symbol, execution_ledger.symbol),
                    side = COALESCE(EXCLUDED.side, execution_ledger.side),
                    exec_price = COALESCE(EXCLUDED.exec_price, execution_ledger.exec_price),
                    exec_qty = COALESCE(EXCLUDED.exec_qty, execution_ledger.exec_qty),
                    exec_value = COALESCE(EXCLUDED.exec_value, execution_ledger.exec_value),
                    exec_fee_usd = COALESCE(EXCLUDED.exec_fee_usd, execution_ledger.exec_fee_usd),
                    exec_time_ms = COALESCE(EXCLUDED.exec_time_ms, execution_ledger.exec_time_ms),
                    source = EXCLUDED.source,
                    raw = EXCLUDED.raw,
                    updated_at = now()
                """,
                rows,
            )
        return len(rows)

    def _should_upsert_exchange_sync(self, aggregate: dict, existing: Optional[dict]) -> bool:
        if not existing:
            return True
        existing_reason = (existing.get("reason") or "").lower()
        incoming_qty = _coerce_float(aggregate.get("total_qty")) or 0.0
        incoming_price = _coerce_float(aggregate.get("avg_price")) or 0.0
        incoming_fee = _coerce_float(aggregate.get("total_fees_usd")) or 0.0
        existing_qty = _coerce_float(existing.get("filled_size")) or 0.0
        existing_price = _coerce_float(existing.get("fill_price")) or 0.0
        existing_fee = _coerce_float(existing.get("total_fees_usd"))
        if existing_fee is None:
            existing_fee = _coerce_float(existing.get("fee_usd")) or 0.0

        qty_close = abs(incoming_qty - existing_qty) <= 1e-8
        price_close = abs(incoming_price - existing_price) <= max(1e-8, existing_price * 1e-8)
        fee_close = abs(incoming_fee - existing_fee) <= 1e-8
        if existing_reason in {"exchange_sync", "exchange_backfill", "exchange_reconcile"} and qty_close and price_close and fee_close:
            return False
        return True

    async def _equity_refresh_loop(self) -> None:
        """Periodically fetch account equity from exchange and update state.
        
        For live trading, the exchange is the source of truth for equity.
        This loop ensures risk calculations use fresh equity values.
        """
        if not self.execution_manager:
            return
        if not self.state_manager:
            return
        
        interval = max(10.0, float(os.getenv("EQUITY_REFRESH_INTERVAL_SEC", "30.0")))
        balance_currency = os.getenv("BALANCE_CURRENCY", "USDT")
        
        exchange_client = self.execution_manager.exchange_client
        if not hasattr(exchange_client, "fetch_balance"):
            log_warning("equity_refresh_no_client", reason="Exchange client does not support fetch_balance")
            return
        
        # Redis key for risk snapshot (read by API)
        risk_snapshot_key = f"quantgambit:{self.config.tenant_id}:{self.config.bot_id}:risk:sizing"
        # Redis key for account state (read by warm start loader)
        account_key = f"quantgambit:{self.config.tenant_id}:{self.config.bot_id}:account:latest"
            
        log_info(
            "equity_refresh_started",
            interval_sec=interval,
            currency=balance_currency,
        )
        
        while True:
            await asyncio.sleep(interval)
            try:
                # Fetch balance from exchange (through the adapter chain)
                new_equity = await exchange_client.fetch_balance(balance_currency)
                
                if new_equity is not None and new_equity > 0:
                    real_equity = new_equity
                    deployable_capital = new_equity
                    if self._max_capital_usd:
                        deployable_capital = min(new_equity, self._max_capital_usd)
                    old_equity = self.state_manager.get_account_state().equity
                    
                    # Update state manager with new equity
                    # Also update peak_balance if equity increased
                    current_peak = self.state_manager.get_account_state().peak_balance
                    new_peak = max(current_peak, real_equity) if current_peak else real_equity
                    
                    self.state_manager.update_account_state(
                        equity=real_equity,
                        peak_balance=new_peak,
                    )
                    
                    # Update Redis risk snapshot so API can read fresh equity
                    if self.snapshots:
                        try:
                            # Read existing snapshot and update equity fields
                            existing = await self.snapshot_reader.read(risk_snapshot_key) if self.snapshot_reader else {}
                            if existing is None:
                                existing = {}
                            risk_snapshot = {
                                key: existing.get(key)
                                for key in (
                                    "limits",
                                    "remaining",
                                    "exposure",
                                    "config",
                                    "risk_budget_usd",
                                    "risk_multiplier",
                                    "size_usd",
                                    "total_exposure_usd",
                                    "total_exposure_pct",
                                    "long_exposure_usd",
                                    "short_exposure_usd",
                                    "net_exposure_usd",
                                    "net_exposure_pct",
                                    "symbol_exposure_usd",
                                    "strategy_exposure_usd",
                                    "max_capital_usd",
                                )
                                if key in existing
                            }
                            risk_snapshot["equity"] = real_equity
                            risk_snapshot["account_balance"] = real_equity
                            risk_snapshot["account_equity"] = real_equity
                            risk_snapshot["deployable_capital"] = deployable_capital
                            risk_snapshot["peak_balance"] = new_peak
                            risk_snapshot["equity_updated_at"] = asyncio.get_event_loop().time()
                            await self.snapshots.write(risk_snapshot_key, risk_snapshot)
                            
                            # Also publish to account:latest for warm start loader
                            account_state = {
                                "equity": real_equity,
                                "balance": real_equity,
                                "peak_balance": new_peak,
                                "daily_pnl": self.state_manager.get_account_state().daily_pnl,
                                "updated_at": asyncio.get_event_loop().time(),
                            }
                            await self.snapshots.write(account_key, account_state)
                        except Exception as redis_exc:
                            log_warning("equity_redis_update_failed", error=str(redis_exc))
                    
                    # Log significant changes (>0.5%)
                    if old_equity and old_equity > 0:
                        change_pct = ((new_equity - old_equity) / old_equity) * 100
                        if abs(change_pct) > 0.5:
                            log_info(
                                "equity_refreshed",
                                old_equity=round(old_equity, 2),
                                new_equity=round(new_equity, 2),
                                change_pct=round(change_pct, 2),
                                peak_balance=round(new_peak, 2),
                            )
            except Exception as exc:
                log_warning("equity_refresh_failed", error=str(exc))

    async def export_state(
        self,
        include_decisions: bool = True,
        include_candles: bool = True,
        decision_hours: int = 1,
        candle_hours: int = 12,
    ) -> Optional[WarmStartState]:
        """Export current live trading state for warm starting backtests.
        
        Creates a complete snapshot of the current live trading state that can
        be used to initialize a backtest from the current market position.
        
        Feature: trading-pipeline-integration
        Requirements: 8.1 - THE System SHALL support exporting live state to a format
                      consumable by backtest
        Requirements: 8.2 - WHEN exporting state THEN the System SHALL include positions,
                      account state, recent decisions, and pipeline state
        
        Args:
            include_decisions: Whether to include recent decisions (default: True)
            include_candles: Whether to include candle history (default: True)
            decision_hours: Hours of decision history to include (default: 1)
            candle_hours: Hours of candle history to include (default: 12)
            
        Returns:
            WarmStartState containing the exported state snapshot, or None if
            WarmStartLoader is not available
            
        Example:
            >>> state = await runtime.export_state()
            >>> if state:
            ...     json_str = state.to_json()
            ...     # Use for warm starting a backtest
        """
        if not self.warm_start_loader:
            log_warning(
                "export_state_unavailable",
                tenant_id=self.config.tenant_id,
                bot_id=self.config.bot_id,
                reason="WarmStartLoader not initialized",
            )
            return None
        
        try:
            state = await self.warm_start_loader.export_state(
                include_decisions=include_decisions,
                include_candles=include_candles,
                decision_hours=decision_hours,
                candle_hours=candle_hours,
            )
            
            log_info(
                "state_exported",
                tenant_id=self.config.tenant_id,
                bot_id=self.config.bot_id,
                position_count=len(state.positions),
                decision_count=len(state.recent_decisions),
                candle_symbols=list(state.candle_history.keys()),
                snapshot_time=state.snapshot_time.isoformat(),
            )
            
            return state
            
        except Exception as exc:
            log_warning(
                "export_state_failed",
                tenant_id=self.config.tenant_id,
                bot_id=self.config.bot_id,
                error=str(exc),
            )
            return None

    async def export_state_json(
        self,
        include_decisions: bool = True,
        include_candles: bool = True,
        decision_hours: int = 1,
        candle_hours: int = 12,
    ) -> Optional[str]:
        """Export current live trading state as JSON string.
        
        Convenience method that combines export_state() and to_json() for
        direct JSON serialization.
        
        Feature: trading-pipeline-integration
        Requirements: 8.1, 8.2
        
        Args:
            include_decisions: Whether to include recent decisions (default: True)
            include_candles: Whether to include candle history (default: True)
            decision_hours: Hours of decision history to include (default: 1)
            candle_hours: Hours of candle history to include (default: 12)
            
        Returns:
            JSON string representation of the exported state, or None if export fails
        """
        state = await self.export_state(
            include_decisions=include_decisions,
            include_candles=include_candles,
            decision_hours=decision_hours,
            candle_hours=candle_hours,
        )
        
        if state:
            return state.to_json()
        return None

    async def _state_snapshot_loop(self) -> None:
        """Periodically create state snapshots for warm start availability.
        
        This loop creates periodic snapshots of the live trading state and
        stores them in Redis for quick access by the warm start system.
        
        Feature: trading-pipeline-integration
        Requirements: 8.5 - THE System SHALL support point-in-time state snapshots
                      for reproducible testing
        """
        if not self._state_snapshot_enabled:
            log_info(
                "state_snapshot_disabled",
                tenant_id=self.config.tenant_id,
                bot_id=self.config.bot_id,
            )
            return
        
        if not self.warm_start_loader:
            log_warning(
                "state_snapshot_unavailable",
                tenant_id=self.config.tenant_id,
                bot_id=self.config.bot_id,
                reason="WarmStartLoader not initialized",
            )
            return
        
        interval = max(10.0, self._state_snapshot_interval_sec)
        snapshot_key = f"quantgambit:{self.config.tenant_id}:{self.config.bot_id}:warm_start:latest"
        
        log_info(
            "state_snapshot_started",
            tenant_id=self.config.tenant_id,
            bot_id=self.config.bot_id,
            interval_sec=interval,
        )
        
        while True:
            await asyncio.sleep(interval)
            try:
                # Export current state (without decisions/candles for smaller snapshot)
                # Full state with decisions/candles can be loaded on-demand
                state = await self.warm_start_loader.export_state(
                    include_decisions=False,  # Skip for periodic snapshots (can be loaded on-demand)
                    include_candles=False,    # Skip for periodic snapshots (can be loaded on-demand)
                )
                
                if state:
                    # Store snapshot in Redis for quick access
                    snapshot_data = state.to_dict()
                    snapshot_data["_snapshot_type"] = "periodic"
                    snapshot_data["_interval_sec"] = interval
                    
                    await self.snapshots.write(snapshot_key, snapshot_data)
                    
                    # Log periodically (every 10 snapshots to avoid log spam)
                    # We track this via a simple counter attribute
                    if not hasattr(self, "_state_snapshot_count"):
                        self._state_snapshot_count = 0
                    self._state_snapshot_count += 1
                    
                    if self._state_snapshot_count % 10 == 1:  # Log first and every 10th
                        log_info(
                            "state_snapshot_created",
                            tenant_id=self.config.tenant_id,
                            bot_id=self.config.bot_id,
                            position_count=len(state.positions),
                            equity=state.account_state.get("equity"),
                            snapshot_count=self._state_snapshot_count,
                        )
                        
            except Exception as exc:
                log_warning(
                    "state_snapshot_failed",
                    tenant_id=self.config.tenant_id,
                    bot_id=self.config.bot_id,
                    error=str(exc),
                )

    async def get_warm_start_state(self) -> Optional[WarmStartState]:
        """Get the current live state for warm starting a backtest.
        
        This method loads the complete live trading state from Redis and
        TimescaleDB, including positions, account state, recent decisions,
        and candle history for AMT calculations.
        
        Feature: trading-pipeline-integration
        Requirements: 3.1 - THE System SHALL support initializing a backtest with
                      current live positions, account state, and recent decision history
        Requirements: 3.2 - WHEN warm starting a backtest THEN the System SHALL load
                      the most recent state snapshot from Redis
        
        Returns:
            WarmStartState containing the complete live state, or None if
            WarmStartLoader is not available
            
        Example:
            >>> state = await runtime.get_warm_start_state()
            >>> if state and not state.is_stale():
            ...     valid, errors = state.validate()
            ...     if valid:
            ...         # Use state to initialize backtest
            ...         pass
        """
        if not self.warm_start_loader:
            log_warning(
                "warm_start_unavailable",
                tenant_id=self.config.tenant_id,
                bot_id=self.config.bot_id,
                reason="WarmStartLoader not initialized",
            )
            return None
        
        try:
            state = await self.warm_start_loader.load_current_state()
            
            log_info(
                "warm_start_state_loaded",
                tenant_id=self.config.tenant_id,
                bot_id=self.config.bot_id,
                position_count=len(state.positions),
                decision_count=len(state.recent_decisions),
                is_stale=state.is_stale(),
                age_seconds=state.get_age_seconds(),
            )
            
            return state
            
        except Exception as exc:
            log_warning(
                "warm_start_load_failed",
                tenant_id=self.config.tenant_id,
                bot_id=self.config.bot_id,
                error=str(exc),
            )
            return None

    async def _intent_expiry_loop(self) -> None:
        """Periodically expire stale intents to prevent them from blocking trading.
        
        Intents stuck in 'created' or 'submitted' state for too long are expired,
        allowing new decisions to proceed without being blocked by stale intents.
        """
        # Get TTL from config or environment
        max_intent_age_sec = float(os.getenv("INTENT_TTL_SEC", "60.0"))
        if max_intent_age_sec <= 0:
            log_info("intent_expiry_disabled", reason="INTENT_TTL_SEC=0")
            return
        
        # Check less frequently than the TTL (every 30s or TTL/2, whichever is larger)
        interval = max(30.0, max_intent_age_sec / 2)
        
        log_info(
            "intent_expiry_started",
            max_age_sec=max_intent_age_sec,
            check_interval_sec=interval,
        )
        
        while True:
            await asyncio.sleep(interval)
            try:
                # Try PostgresOrderStore first if available
                postgres_store = None
                if hasattr(self, "order_store") and self.order_store:
                    postgres_store = getattr(self.order_store, "_postgres_store", None)
                
                if postgres_store and hasattr(postgres_store, "expire_stale_intents"):
                    expired_count = await postgres_store.expire_stale_intents(
                        self.config.tenant_id,
                        self.config.bot_id,
                        max_intent_age_sec,
                    )
                    if expired_count > 0:
                        log_info(
                            "intent_expiry_completed",
                            expired_count=expired_count,
                            max_age_sec=max_intent_age_sec,
                        )
                
            except Exception as exc:
                log_warning("intent_expiry_failed", error=str(exc))

    async def _kill_switch_refresh_loop(self) -> None:
        """Periodically refresh kill switch state from Redis.
        
        This ensures the runtime detects kill switch triggers from external sources
        (e.g., dashboard, API) without requiring a restart.
        """
        interval = float(os.getenv("KILL_SWITCH_REFRESH_INTERVAL_SEC", "2.0"))
        if interval <= 0:
            log_info("kill_switch_refresh_disabled", reason="KILL_SWITCH_REFRESH_INTERVAL_SEC=0")
            return
        
        log_info(
            "kill_switch_refresh_started",
            interval_sec=interval,
        )
        
        while True:
            await asyncio.sleep(interval)
            try:
                if self._kill_switch and hasattr(self._kill_switch, "refresh_state"):
                    await self._kill_switch.refresh_state()
            except Exception as exc:
                log_warning("kill_switch_refresh_failed", error=str(exc))

    async def _preload_reference_prices(self) -> None:
        """Pre-load reference prices from orderbook feed stream before starting workers.
        
        This ensures that when positions are restored and snapshots are emitted,
        they have accurate current market prices instead of stale/zero values.
        Works for all exchanges by reading from the exchange-specific orderbook feed stream.
        """
        if not self.reference_prices:
            return
        
        # Determine the orderbook feed stream for this exchange
        orderbook_stream = os.getenv(
            "ORDERBOOK_EVENT_STREAM",
            f"events:orderbook_feed:{self.config.exchange}"
        )
        
        try:
            # Read recent orderbook events to seed the reference price cache
            # We read from the end of the stream (most recent data)
            messages = await self.redis_client.redis.xrevrange(
                orderbook_stream,
                count=200,  # Read last 200 messages to cover all symbols
            )
            
            if not messages:
                log_warning(
                    "reference_price_preload_empty",
                    stream=orderbook_stream,
                    exchange=self.config.exchange,
                )
                return
            
            symbols_loaded = set()
            for msg_id, fields in messages:
                try:
                    data_raw = fields.get(b"data") or fields.get("data")
                    if not data_raw:
                        continue
                    if isinstance(data_raw, bytes):
                        data_raw = data_raw.decode("utf-8")
                    event = json.loads(data_raw)
                    payload = event.get("payload", {})
                    symbol = payload.get("symbol") or event.get("symbol")
                    
                    if not symbol or symbol in symbols_loaded:
                        continue
                    
                    bids = payload.get("bids", [])
                    asks = payload.get("asks", [])
                    
                    if bids and asks and len(bids) > 0 and len(asks) > 0:
                        try:
                            best_bid = float(bids[0][0])
                            best_ask = float(asks[0][0])
                            mid_price = (best_bid + best_ask) / 2.0
                            timestamp = payload.get("timestamp") or event.get("timestamp")
                            
                            self.reference_prices.update(symbol, mid_price, timestamp=timestamp)
                            symbols_loaded.add(symbol)
                        except (TypeError, ValueError, IndexError):
                            continue
                except Exception:
                    continue
            
            if symbols_loaded:
                log_info(
                    "reference_prices_preloaded",
                    exchange=self.config.exchange,
                    symbols=list(symbols_loaded),
                    count=len(symbols_loaded),
                )
            else:
                log_warning(
                    "reference_price_preload_no_prices",
                    stream=orderbook_stream,
                    exchange=self.config.exchange,
                )
        except Exception as exc:
            log_warning(
                "reference_price_preload_failed",
                exchange=self.config.exchange,
                error=str(exc),
            )

    async def _restore_positions_from_timescale(self) -> None:
        if not self.timescale_reader:
            return
        payload = await self.timescale_reader.load_latest_positions(self.config.tenant_id, self.config.bot_id)
        if not payload:
            return
        positions = payload.get("positions") if isinstance(payload, dict) else None
        if not positions:
            return
        snapshots = []
        for pos in positions:
            if not isinstance(pos, dict):
                continue
            symbol = pos.get("symbol")
            side = pos.get("side")
            size = pos.get("size")
            if not symbol or not side or size is None:
                continue
            snapshots.append(
                PositionSnapshot(
                    symbol=symbol,
                    side=side,
                    size=float(size),
                    entry_client_order_id=pos.get("entry_client_order_id"),
                    entry_decision_id=pos.get("entry_decision_id"),
                    reference_price=pos.get("reference_price"),
                    entry_price=pos.get("entry_price"),
                    entry_fee_usd=pos.get("entry_fee_usd"),
                    stop_loss=pos.get("stop_loss"),
                    take_profit=pos.get("take_profit"),
                    opened_at=pos.get("opened_at"),
                    prediction_confidence=pos.get("prediction_confidence"),
                    prediction_direction=pos.get("prediction_direction"),
                    prediction_source=pos.get("prediction_source"),
                    entry_p_hat=pos.get("entry_p_hat"),
                    entry_p_hat_source=pos.get("entry_p_hat_source"),
                    strategy_id=pos.get("strategy_id"),
                    profile_id=pos.get("profile_id"),
                    expected_horizon_sec=pos.get("expected_horizon_sec"),
                    time_to_work_sec=pos.get("time_to_work_sec"),
                    max_hold_sec=pos.get("max_hold_sec"),
                    mfe_min_bps=pos.get("mfe_min_bps"),
                    model_side=pos.get("model_side"),
                    p_up=pos.get("p_up"),
                    p_down=pos.get("p_down"),
                    p_flat=pos.get("p_flat"),
                )
            )
        if snapshots:
            self.state_manager.restore_positions(snapshots)
            log_info(
                "positions_restored_from_timescale",
                tenant_id=self.config.tenant_id,
                bot_id=self.config.bot_id,
                count=len(snapshots),
            )
            snapshots_writer = getattr(self, "snapshots", None)
            if snapshots_writer:
                key = f"quantgambit:{self.config.tenant_id}:{self.config.bot_id}:positions:latest"
                snapshot_payload = {
                    "exchange": self.config.exchange,
                    "timestamp": time.time(),
                    **payload,
                }
                await snapshots_writer.write(key, snapshot_payload)

    async def _hydrate_positions_from_intents(self) -> None:
        if not self.timescale_reader or not self.execution_manager:
            return
        positions = await self.execution_manager.position_manager.list_open_positions()
        if not positions:
            return
        updated = 0
        for pos in positions:
            # Hydrate missing metadata from the latest intent (SL/TP + strategy/profile + time budgets).
            needs_sltp = pos.stop_loss is None and pos.take_profit is None
            needs_meta = (
                (pos.strategy_id is None and pos.profile_id is None)
                or pos.expected_horizon_sec is None
                or pos.time_to_work_sec is None
                or pos.max_hold_sec is None
                or pos.mfe_min_bps is None
            )
            needs_attribution = (
                getattr(pos, "entry_client_order_id", None) is None
                or getattr(pos, "entry_decision_id", None) is None
            )
            if not needs_sltp and not needs_meta and not needs_attribution:
                continue
            intent = await self.timescale_reader.load_latest_order_intent_for_symbol(
                self.config.tenant_id,
                self.config.bot_id,
                pos.symbol,
            )
            if not intent:
                continue
            snapshot_metrics = intent.get("snapshot_metrics")
            if not isinstance(snapshot_metrics, dict):
                snapshot_metrics = {}
            def _intent_metric(*keys: str):
                for key in keys:
                    if key in intent and intent.get(key) is not None:
                        return intent.get(key)
                    if key in snapshot_metrics and snapshot_metrics.get(key) is not None:
                        return snapshot_metrics.get(key)
                return None
            stop_loss = intent.get("stop_loss")
            take_profit = intent.get("take_profit")
            # If we were only missing SL/TP and intent doesn't have them, skip.
            if needs_sltp and stop_loss is None and take_profit is None and not needs_meta:
                continue
            # Time budget fields are stored with a few legacy names in intents.
            expected_horizon_sec = _intent_metric("expected_horizon_sec")
            time_to_work_sec = _intent_metric("time_to_work_sec")
            max_hold_sec = _intent_metric("max_hold_sec", "max_hold_time_seconds")
            mfe_min_bps = _intent_metric("mfe_min_bps")
            strategy_id = _intent_metric("strategy_id")
            profile_id = _intent_metric("profile_id")
            entry_client_order_id = _intent_metric("client_order_id")
            entry_decision_id = _intent_metric("decision_id")
            await self.execution_manager.position_manager.upsert_position(
                PositionSnapshot(
                    symbol=pos.symbol,
                    side=pos.side,
                    size=0.0,
                    entry_client_order_id=(entry_client_order_id if needs_attribution else getattr(pos, "entry_client_order_id", None)),
                    entry_decision_id=(entry_decision_id if needs_attribution else getattr(pos, "entry_decision_id", None)),
                    reference_price=pos.reference_price,
                    entry_price=pos.entry_price or intent.get("entry_price"),
                    stop_loss=stop_loss if needs_sltp else pos.stop_loss,
                    take_profit=take_profit if needs_sltp else pos.take_profit,
                    opened_at=pos.opened_at,
                    prediction_confidence=pos.prediction_confidence,
                    strategy_id=strategy_id or pos.strategy_id,
                    profile_id=profile_id or pos.profile_id,
                    expected_horizon_sec=expected_horizon_sec if expected_horizon_sec is not None else pos.expected_horizon_sec,
                    time_to_work_sec=time_to_work_sec if time_to_work_sec is not None else pos.time_to_work_sec,
                    max_hold_sec=max_hold_sec if max_hold_sec is not None else pos.max_hold_sec,
                    mfe_min_bps=mfe_min_bps if mfe_min_bps is not None else pos.mfe_min_bps,
                    model_side=getattr(pos, "model_side", None),
                    p_up=getattr(pos, "p_up", None),
                    p_down=getattr(pos, "p_down", None),
                    p_flat=getattr(pos, "p_flat", None),
                ),
                accumulate=True,
            )
            updated += 1
        if updated:
            log_info(
                "positions_hydrated_sltp",
                tenant_id=self.config.tenant_id,
                bot_id=self.config.bot_id,
                updated=updated,
            )

    async def _sync_positions_from_exchange(self) -> None:
        """Sync positions from exchange to reconcile with local state.
        
        This ensures the runtime's position state matches the exchange's actual positions.
        Called after restoring from TimescaleDB to handle any positions that were
        closed externally (via dashboard, manually, or by another system).
        """
        if not self.execution_manager or not self.execution_manager.exchange_client:
            log_warning("exchange_sync_skipped", reason="no_exchange_client")
            return
        
        if self.config.trading_mode == "paper":
            log_info("exchange_sync_skipped", reason="paper_trading_mode")
            return
        
        try:
            if not hasattr(self, "_exchange_position_miss_counts"):
                self._exchange_position_miss_counts = {}
            if not hasattr(self, "exchange_positions_remove_after_misses"):
                # Debounce transient exchange/API gaps before dropping local position state.
                self.exchange_positions_remove_after_misses = 3
            if not hasattr(self, "_exchange_position_first_seen_opened_at"):
                self._exchange_position_first_seen_opened_at = {}
            log_info(
                "exchange_sync_start",
                tenant_id=self.config.tenant_id,
                bot_id=self.config.bot_id,
                exchange=self.config.exchange,
                trading_mode=self.config.trading_mode,
            )
            exchange_client = self.execution_manager.exchange_client

            def _extract_pos_price(pos: dict, keys: list[str]) -> Optional[float]:
                for key in keys:
                    if key not in pos:
                        continue
                    raw = pos.get(key)
                    if raw is None:
                        continue
                    try:
                        val = float(raw)
                    except (TypeError, ValueError):
                        continue
                    if val <= 0:
                        continue
                    return val
                return None
            
            # Check if the client supports fetching positions
            if not hasattr(exchange_client, "fetch_positions"):
                log_warning("exchange_sync_skipped", reason="client_no_fetch_positions")
                return
            
            exchange_positions = await exchange_client.fetch_positions()
            
            if exchange_positions is None:
                log_warning("exchange_sync_failed", reason="fetch_returned_none")
                return
            
            # Build set of symbols with actual positions on exchange (canonicalized)
            exchange_position_map = {}
            for pos in exchange_positions:
                raw_symbol = pos.get("symbol", "")
                symbol = normalize_exchange_symbol(self.config.exchange, raw_symbol, market_type=self.config.market_type)
                if not symbol:
                    continue
                raw_size = pos.get("contracts", None)
                if raw_size is None:
                    raw_size = pos.get("size", None)
                if raw_size is None:
                    raw_size = pos.get("positionAmt", None)
                try:
                    size_val = float(raw_size or 0)
                except (TypeError, ValueError):
                    size_val = 0.0
                if size_val == 0:
                    continue
                side = (pos.get("side") or ("short" if size_val < 0 else "long")).lower()
                size_abs = abs(size_val)
                stop_loss = _extract_pos_price(pos, ["stopLoss", "stop_loss", "sl", "slPrice", "stopLossPrice"])
                take_profit = _extract_pos_price(pos, ["takeProfit", "take_profit", "tp", "tpPrice", "takeProfitPrice"])
                exchange_position_map[symbol] = {
                    "symbol": symbol,
                    "raw_symbol": raw_symbol,
                    "side": side,
                    "size": size_abs,
                    "entry_price": float(pos.get("entryPrice", 0) or pos.get("entry_price", 0) or 0),
                    "timestamp": pos.get("timestamp") or pos.get("updatedTime") or pos.get("createdTime"),
                    "stop_loss": stop_loss,
                    "take_profit": take_profit,
                }
            
            # Get local positions
            local_positions = await self.execution_manager.position_manager.list_positions()
            local_position_symbols = {p.symbol for p in local_positions}
            
            def _normalize_symbol(raw: str) -> str:
                return normalize_exchange_symbol(self.config.exchange, raw, market_type=self.config.market_type) or ""

            # Remove duplicate local positions that map to the same canonical symbol
            local_by_norm: dict[str, Any] = {}
            duplicate_locals: list[Any] = []
            for pos in local_positions:
                norm = _normalize_symbol(pos.symbol)
                if norm in local_by_norm:
                    duplicate_locals.append(pos)
                else:
                    local_by_norm[norm] = pos
            for dup in duplicate_locals:
                await self.execution_manager.position_manager.mark_closing(dup.symbol, reason="exchange_sync_duplicate")
                await self.execution_manager.position_manager.finalize_close(dup.symbol)
                canonical = _normalize_symbol(dup.symbol)
                if canonical:
                    self._exchange_position_first_seen_opened_at.pop(canonical, None)
                log_warning(
                    "exchange_sync_removed_duplicate_position",
                    symbol=dup.symbol,
                    canonical=_normalize_symbol(dup.symbol),
                )

            # Find positions to remove (local but not on exchange), but debounce removals
            # to avoid transient exchange/API gaps from resetting local opened_at.
            positions_to_remove = []
            exchange_symbols = set(exchange_position_map.keys())
            for local_pos in local_positions:
                normalized_local = _normalize_symbol(local_pos.symbol)
                if normalized_local and normalized_local not in exchange_symbols:
                    misses = int(self._exchange_position_miss_counts.get(normalized_local, 0)) + 1
                    self._exchange_position_miss_counts[normalized_local] = misses
                    if misses >= int(self.exchange_positions_remove_after_misses):
                        positions_to_remove.append(local_pos.symbol)
                    else:
                        log_warning(
                            "exchange_sync_position_missing_deferred",
                            symbol=local_pos.symbol,
                            canonical=normalized_local,
                            misses=misses,
                            remove_after=int(self.exchange_positions_remove_after_misses),
                        )
                elif normalized_local:
                    self._exchange_position_miss_counts.pop(normalized_local, None)
            
            # Remove stale local positions
            for symbol in positions_to_remove:
                normalized = _normalize_symbol(symbol)
                await self.execution_manager.position_manager.mark_closing(symbol, reason="exchange_sync")
                await self.execution_manager.position_manager.finalize_close(symbol)
                if normalized:
                    self._exchange_position_miss_counts.pop(normalized, None)
                    self._exchange_position_first_seen_opened_at.pop(normalized, None)
                log_info(
                    "exchange_sync_removed_stale_position",
                    symbol=symbol,
                    reason="not_on_exchange",
                )

            # Add or refresh positions that exist on exchange but not locally
            positions_added = 0
            positions_updated = 0
            local_by_norm = { _normalize_symbol(p.symbol): p for p in local_positions }
            for ex_symbol, ex_pos in exchange_position_map.items():
                normalized_ex = _normalize_symbol(ex_symbol)
                if not normalized_ex:
                    continue
                local_pos = local_by_norm.get(normalized_ex)
                if local_pos and local_pos.symbol != normalized_ex:
                    await self.execution_manager.position_manager.mark_closing(local_pos.symbol, reason="exchange_sync_symbol_normalized")
                    await self.execution_manager.position_manager.finalize_close(local_pos.symbol)
                    local_pos = None
                needs_update = False
                if not local_pos:
                    needs_update = True
                else:
                    # Update if side/size mismatch (exchange is source of truth)
                    try:
                        size_delta = abs((local_pos.size or 0.0) - (ex_pos.get("size") or 0.0))
                        size_ratio = size_delta / max(1.0, abs(local_pos.size or 0.0))
                    except Exception:
                        size_ratio = 0.0
                    if (local_pos.side or "").lower() != (ex_pos.get("side") or "").lower() or size_ratio > 0.02:
                        needs_update = True
                    # Update protection if exchange provides new values
                    exchange_sl = ex_pos.get("stop_loss")
                    exchange_tp = ex_pos.get("take_profit")
                    if exchange_sl is not None and exchange_sl != local_pos.stop_loss:
                        needs_update = True
                    if exchange_tp is not None and exchange_tp != local_pos.take_profit:
                        needs_update = True
                if not needs_update:
                    if local_pos and local_pos.opened_at:
                        try:
                            self._exchange_position_first_seen_opened_at[normalized_ex] = float(local_pos.opened_at)
                        except (TypeError, ValueError):
                            pass
                    continue
                intent_attribution = None
                timescale_reader = getattr(self, "timescale_reader", None)
                if (
                    timescale_reader
                    and (
                        not local_pos
                        or getattr(local_pos, "entry_client_order_id", None) is None
                        or getattr(local_pos, "entry_decision_id", None) is None
                    )
                ):
                    intent_attribution = await timescale_reader.load_latest_order_intent_for_symbol(
                        self.config.tenant_id,
                        self.config.bot_id,
                        ex_symbol,
                    )
                entry_price = ex_pos.get("entry_price") or None
                if entry_price is not None:
                    try:
                        if float(entry_price) <= 0:
                            entry_price = None
                    except (TypeError, ValueError):
                        entry_price = None
                # Preserve local entry_price if exchange doesn't provide a usable one.
                if entry_price is None and local_pos and local_pos.entry_price:
                    entry_price = local_pos.entry_price
                exchange_sl = ex_pos.get("stop_loss")
                exchange_tp = ex_pos.get("take_profit")
                stop_loss = exchange_sl if exchange_sl is not None else (local_pos.stop_loss if local_pos else None)
                take_profit = exchange_tp if exchange_tp is not None else (local_pos.take_profit if local_pos else None)
                opened_at = None
                try:
                    ts = ex_pos.get("timestamp")
                    if ts:
                        opened_at = float(ts) / 1000.0 if float(ts) > 1e12 else float(ts)
                except Exception:
                    opened_at = None
                # Preserve the position's true open time.
                #
                # Some exchanges/ccxt payloads expose timestamps that are *not* the position open time
                # (often "last update"). If we keep overwriting `opened_at` on every sync, time-based
                # exits (POSITION_GUARD_MAX_AGE_SEC / max_hold_sec) will never trigger because the
                # position will appear perpetually "fresh".
                now_ts = time.time()
                cached_opened_at = self._exchange_position_first_seen_opened_at.get(normalized_ex)
                if local_pos and local_pos.opened_at:
                    try:
                        local_opened_at = float(local_pos.opened_at)
                    except (TypeError, ValueError):
                        local_opened_at = None
                    # If we already have a local open time, keep it.
                    if local_opened_at is not None:
                        opened_at = local_opened_at
                elif cached_opened_at is not None:
                    # Local state can be unexpectedly absent during reconciliation churn.
                    # Keep the first-seen value so hold-time does not restart every sync.
                    opened_at = float(cached_opened_at)
                # If we're still missing or the exchange timestamp is wildly old, treat it as "now".
                max_age_sec = float(os.getenv("EXCHANGE_SYNC_MAX_OPENED_AT_AGE_SEC", str(7 * 24 * 3600)))
                if opened_at is None or (opened_at < now_ts - max_age_sec):
                    opened_at = now_ts
                # Persist the earliest known opened_at for this symbol.
                prev_opened_at = self._exchange_position_first_seen_opened_at.get(normalized_ex)
                if prev_opened_at is not None:
                    try:
                        opened_at = min(float(opened_at), float(prev_opened_at))
                    except (TypeError, ValueError):
                        pass
                self._exchange_position_first_seen_opened_at[normalized_ex] = float(opened_at)
                await self.execution_manager.position_manager.upsert_position(
                    PositionSnapshot(
                        symbol=ex_symbol,
                        side=ex_pos.get("side") or "unknown",
                        size=float(ex_pos.get("size") or 0.0),
                        # Preserve stable attribution keys and prediction metadata from local state.
                        #
                        # Exchange position snapshots generally do not carry these fields, but we need them
                        # for accurate post-trade analysis (join intents -> positions) and prediction scoring.
                        entry_client_order_id=(
                            (getattr(local_pos, "entry_client_order_id", None) if local_pos else None)
                            or (intent_attribution.get("client_order_id") if isinstance(intent_attribution, dict) else None)
                        ),
                        entry_decision_id=(
                            (getattr(local_pos, "entry_decision_id", None) if local_pos else None)
                            or (intent_attribution.get("decision_id") if isinstance(intent_attribution, dict) else None)
                        ),
                        reference_price=entry_price,
                        entry_price=entry_price,
                        stop_loss=stop_loss,
                        take_profit=take_profit,
                        opened_at=opened_at,
                        entry_fee_usd=(local_pos.entry_fee_usd if local_pos else None),
                        prediction_confidence=(local_pos.prediction_confidence if local_pos else None),
                        prediction_direction=(getattr(local_pos, "prediction_direction", None) if local_pos else None),
                        prediction_source=(getattr(local_pos, "prediction_source", None) if local_pos else None),
                        entry_p_hat=(getattr(local_pos, "entry_p_hat", None) if local_pos else None),
                        entry_p_hat_source=(getattr(local_pos, "entry_p_hat_source", None) if local_pos else None),
                        strategy_id=(local_pos.strategy_id if local_pos else None),
                        profile_id=(local_pos.profile_id if local_pos else None),
                        entry_signal_strength=(getattr(local_pos, "entry_signal_strength", None) if local_pos else None),
                        entry_signal_confidence=(getattr(local_pos, "entry_signal_confidence", None) if local_pos else None),
                        entry_confirmation_count=(getattr(local_pos, "entry_confirmation_count", None) if local_pos else None),
                        expected_horizon_sec=(local_pos.expected_horizon_sec if local_pos else None),
                        time_to_work_sec=(local_pos.time_to_work_sec if local_pos else None),
                        max_hold_sec=(local_pos.max_hold_sec if local_pos else None),
                        mfe_min_bps=(local_pos.mfe_min_bps if local_pos else None),
                        model_side=(getattr(local_pos, "model_side", None) if local_pos else None),
                        p_up=(getattr(local_pos, "p_up", None) if local_pos else None),
                        p_down=(getattr(local_pos, "p_down", None) if local_pos else None),
                        p_flat=(getattr(local_pos, "p_flat", None) if local_pos else None),
                    ),
                    accumulate=False,
                )
                if local_pos:
                    positions_updated += 1
                else:
                    positions_added += 1
            
            # Log sync result
            log_info(
                "exchange_sync_complete",
                exchange_positions=len(exchange_position_map),
                local_positions=len(local_positions),
                removed_stale=len(positions_to_remove),
                added=positions_added,
                updated=positions_updated,
            )
            
        except Exception as exc:
            log_warning("exchange_sync_failed", error=str(exc))

    async def _restore_order_snapshot_from_timescale(self) -> None:
        if not self.timescale_reader:
            return
        payload = await self.timescale_reader.load_latest_order_event(self.config.tenant_id, self.config.bot_id)
        if not payload:
            return
        snapshots_writer = getattr(self, "snapshots", None)
        if not snapshots_writer:
            return
        key = f"quantgambit:{self.config.tenant_id}:{self.config.bot_id}:order:history"
        snapshot_payload = {
            "exchange": self.config.exchange,
            "timestamp": time.time(),
            **payload,
        }
        await snapshots_writer.append_history(key, snapshot_payload, max_items=200)

    async def _prune_warmup_keys(self) -> None:
        symbols = set(self.config.orderbook_symbols or [])
        if not symbols:
            return
        tenant_id = self.config.tenant_id
        bot_id = self.config.bot_id
        pattern = f"quantgambit:{tenant_id}:{bot_id}:warmup:*"
        try:
            keys = await self.redis_client.redis.keys(pattern)
        except Exception as exc:
            log_warning("warmup_prune_failed", error=str(exc))
            return
        removed = 0
        for raw_key in keys or []:
            key = raw_key.decode("utf-8") if isinstance(raw_key, bytes) else raw_key
            symbol = key.split(":")[-1]
            if symbol and symbol not in symbols:
                await self.redis_client.redis.delete(raw_key)
                removed += 1
        if removed:
            log_info(
                "warmup_pruned",
                tenant_id=tenant_id,
                bot_id=bot_id,
                removed=removed,
            )

    async def _check_config_drift(self) -> None:
        if not self.config_store:
            return
        record = await self.config_store.get_latest(self.config.tenant_id, self.config.bot_id)
        if not record:
            return
        applied_version = self.config_repository.current_version(self.config.tenant_id, self.config.bot_id)
        runtime_version = applied_version if applied_version is not None else self.config.version
        if runtime_version is None:
            return
        if record.version == runtime_version:
            runtime_state = getattr(self, "runtime_state", None)
            if runtime_state is not None:
                runtime_state.config_drift_active = False
            return
        runtime_state = getattr(self, "runtime_state", None)
        if runtime_state is not None:
            runtime_state.config_drift_active = True
        snapshots = getattr(self, "snapshots", None)
        if snapshots:
            key = f"quantgambit:{self.config.tenant_id}:{self.config.bot_id}:config:drift"
            await snapshots.write(
                key,
                {
                    "tenant_id": self.config.tenant_id,
                    "bot_id": self.config.bot_id,
                    "exchange": self.config.exchange,
                    "stored_version": record.version,
                    "runtime_version": runtime_version,
                    "timestamp": time.time(),
                },
            )
        if self.telemetry and self.telemetry_context:
            payload = {
                "type": "config_drift",
                "stored_version": record.version,
                "runtime_version": runtime_version,
            }
            await self.telemetry.publish_guardrail(self.telemetry_context, payload)
            if hasattr(self.telemetry, "publish_health_snapshot"):
                await self.telemetry.publish_health_snapshot(
                    self.telemetry_context,
                    {
                        "status": "config_drift",
                        "stored_version": record.version,
                        "runtime_version": runtime_version,
                    },
                )
        if self.alerts:
            await self.alerts.send(
                "config_drift",
                "Runtime config diverged from stored config.",
                {
                    "tenant_id": self.config.tenant_id,
                    "bot_id": self.config.bot_id,
                    "exchange": self.config.exchange,
                    "stored_version": record.version,
                    "runtime_version": runtime_version,
                },
            )

    async def _recover_pending_intents(self) -> None:
        try:
            pending = await self.order_store.load_pending_intents()
        except Exception as exc:
            log_warning("order_intent_recovery_failed", error=str(exc))
            if hasattr(self.order_store, "record_error"):
                await self.order_store.record_error(
                    stage="recovery",
                    error_message=str(exc),
                    payload={"type": "order_intent_load_failed"},
                )
            return
        if self.telemetry and self.telemetry_context and hasattr(self.order_store, "pop_intent_drop_stats"):
            stats = self.order_store.pop_intent_drop_stats()
            if stats:
                await self.telemetry.publish_guardrail(
                    self.telemetry_context,
                    {
                        "type": "order_intent_dropped",
                        "reason": "stale",
                        "count": stats.get("stale", 0),
                    },
                )
        if not pending:
            return
        log_info(
            "order_intent_recovery_start",
            tenant_id=self.config.tenant_id,
            bot_id=self.config.bot_id,
            count=len(pending),
        )
        resolved = 0
        idempotency_store = None
        if hasattr(self, "execution_worker") and self.execution_worker:
            idempotency_store = getattr(self.execution_worker, "idempotency_store", None)
        for item in pending:
            symbol = item.get("symbol")
            client_order_id = item.get("client_order_id")
            order_id = item.get("order_id")
            if not symbol or not client_order_id:
                continue
            if idempotency_store:
                try:
                    claimed = await idempotency_store.claim(client_order_id)
                    if not claimed:
                        log_warning(
                            "order_intent_recovery_duplicate",
                            client_order_id=client_order_id,
                            symbol=symbol,
                        )
                        if self.telemetry and self.telemetry_context:
                            await self.telemetry.publish_guardrail(
                                self.telemetry_context,
                                {
                                    "type": "order_recovery_duplicate",
                                    "symbol": symbol,
                                    "client_order_id": client_order_id,
                                },
                            )
                        continue
                except Exception as exc:
                    log_warning(
                        "order_intent_recovery_dedupe_failed",
                        client_order_id=client_order_id,
                        error=str(exc),
                    )
            intent = ExecutionIntent(
                symbol=symbol,
                side=item.get("side"),
                size=item.get("size"),
                client_order_id=client_order_id,
            )
            status = None
            if order_id:
                status = await self.execution_manager.poll_order_status(order_id, symbol)
            if not status and hasattr(self.execution_manager, "poll_order_status_by_client_id"):
                status = await self.execution_manager.poll_order_status_by_client_id(client_order_id, symbol)
            if not status:
                log_warning(
                    "order_intent_recovery_unresolved",
                    tenant_id=self.config.tenant_id,
                    bot_id=self.config.bot_id,
                    symbol=symbol,
                    client_order_id=client_order_id,
                )
                if hasattr(self.order_store, "record_error"):
                    await self.order_store.record_error(
                        stage="recovery",
                        error_message="order_intent_unresolved",
                        symbol=symbol,
                        client_order_id=client_order_id,
                        payload={"type": "order_recovery_unresolved"},
                    )
                if self.telemetry and self.telemetry_context:
                    await self.telemetry.publish_guardrail(
                        self.telemetry_context,
                        {
                            "type": "order_recovery_unresolved",
                            "symbol": symbol,
                            "client_order_id": client_order_id,
                        },
                    )
                continue
            status = status if status.order_id or order_id else status
            normalized = normalize_order_status(status.status)
            await self.execution_manager.record_order_status(intent, status)
            if self.telemetry and self.telemetry_context:
                await self.telemetry.publish_guardrail(
                    self.telemetry_context,
                    {
                        "type": "order_recovery_resolved",
                        "symbol": symbol,
                        "client_order_id": client_order_id,
                        "order_id": status.order_id or order_id,
                        "status": normalized,
                    },
                )
            await self.order_store.record_intent(
                intent_id=item.get("intent_id") or str(time.time()),
                symbol=symbol,
                side=item.get("side"),
                size=item.get("size"),
                client_order_id=client_order_id,
                status=normalized if is_terminal_status(normalized) else "submitted",
                decision_id=item.get("decision_id"),
                entry_price=item.get("entry_price"),
                stop_loss=item.get("stop_loss"),
                take_profit=item.get("take_profit"),
                strategy_id=item.get("strategy_id"),
                profile_id=item.get("profile_id"),
                order_id=status.order_id or order_id,
                last_error=item.get("last_error"),
                created_at=item.get("created_at"),
                submitted_at=item.get("submitted_at"),
            )
            resolved += 1
        log_info(
            "order_intent_recovery_complete",
            tenant_id=self.config.tenant_id,
            bot_id=self.config.bot_id,
            resolved=resolved,
            pending=len(pending),
        )

    async def _config_flush_loop(self) -> None:
        while True:
            applier = self.config_watcher.applier
            if hasattr(applier, "flush_if_safe"):
                await applier.flush_if_safe()
            await asyncio.sleep(1.0)

    async def _override_cleanup_loop(self) -> None:
        while True:
            stats = await self.risk_override_store.prune_expired()
            if stats and self.telemetry and self.telemetry_context:
                await self.telemetry.publish_guardrail(
                    self.telemetry_context,
                    {
                        "type": "risk_override_pruned",
                        "count": stats.get("dropped", 0),
                        "source": "override_cleanup",
                    },
                )
            await asyncio.sleep(60.0)


def _build_alerts_client() -> Optional[AlertsClient]:
    """
    Build alerts client from environment variables.
    
    Environment Variables:
        SLACK_WEBHOOK_URL: Slack incoming webhook URL (takes precedence)
        DISCORD_WEBHOOK_URL: Discord webhook URL
        ALERT_WEBHOOK_URL: Generic webhook URL (fallback)
        ALERT_CHANNEL: Optional channel override for Slack
        ALERT_USERNAME: Bot username (default: "QuantGambit Bot")
    
    Returns:
        AlertsClient if webhook configured, None otherwise
    """
    # Check for provider-specific webhooks first
    slack_webhook = os.getenv("SLACK_WEBHOOK_URL")
    discord_webhook = os.getenv("DISCORD_WEBHOOK_URL")
    generic_webhook = os.getenv("ALERT_WEBHOOK_URL")
    
    if slack_webhook:
        webhook = slack_webhook
        provider = "slack"
    elif discord_webhook:
        webhook = discord_webhook
        provider = "discord"
    elif generic_webhook:
        webhook = generic_webhook
        provider = "generic"
    else:
        return None
    
    channel = os.getenv("ALERT_CHANNEL")
    username = os.getenv("ALERT_USERNAME", "QuantGambit Bot")
    
    return AlertsClient(AlertConfig(
        webhook_url=webhook,
        provider=provider,
        channel=channel,
        username=username,
    ))


async def _guarded_task(coro_fn, name: str):
    try:
        await coro_fn()
    except asyncio.CancelledError:
        log_info("runtime_task_cancelled", task=name)
        return
    except Exception as exc:
        log_error("runtime_task_failed", task=name, error=str(exc))
        raise


def _aggregate_execution_sync_trades(trades: list[dict]) -> list[dict]:
    grouped: dict[str, dict] = {}
    for trade in trades:
        if not isinstance(trade, dict):
            continue
        info = trade.get("info") if isinstance(trade.get("info"), dict) else {}
        order_id = (
            trade.get("order")
            or info.get("orderId")
            or info.get("orderID")
            or info.get("order_id")
        )
        if not order_id:
            continue
        client_order_id = (
            info.get("orderLinkId")
            or info.get("orderLinkID")
            or info.get("clientOrderId")
            or trade.get("clientOrderId")
        )
        symbol = trade.get("symbol") or info.get("symbol") or ""
        symbol = _normalize_symbol(symbol)
        side = trade.get("side") or info.get("side") or ""
        price = _coerce_float(trade.get("price") or info.get("execPrice"))
        amount = _coerce_float(trade.get("amount") or info.get("execQty"))
        cost = _coerce_float(trade.get("cost") or info.get("execValue"))
        fee = trade.get("fee") if isinstance(trade.get("fee"), dict) else {}
        fee_cost = _coerce_float(fee.get("cost")) if isinstance(fee, dict) else None
        fee_cost = fee_cost if fee_cost is not None else _coerce_float(info.get("execFee") or info.get("fee"))
        timestamp_ms = _coerce_int(trade.get("timestamp") or info.get("execTime"))
        if cost is None and price is not None and amount is not None:
            cost = price * amount
        entry = grouped.get(str(order_id))
        if entry is None:
            entry = {
                "order_id": str(order_id),
                "client_order_id": client_order_id,
                "symbol": symbol,
                "side": side,
                "total_qty": 0.0,
                "total_cost": 0.0,
                "total_fees_usd": 0.0,
                "timestamp_ms": timestamp_ms,
            }
            grouped[str(order_id)] = entry
        qty_val = amount if amount is not None else 0.0
        cost_val = cost if cost is not None else 0.0
        entry["total_qty"] += qty_val
        entry["total_cost"] += cost_val
        if fee_cost is not None:
            entry["total_fees_usd"] += fee_cost
        if timestamp_ms is not None:
            existing_ts = entry.get("timestamp_ms")
            entry["timestamp_ms"] = timestamp_ms if existing_ts is None else max(existing_ts, timestamp_ms)
        if not entry.get("client_order_id") and client_order_id:
            entry["client_order_id"] = client_order_id
        if not entry.get("side") and side:
            entry["side"] = side
        if not entry.get("symbol") and symbol:
            entry["symbol"] = symbol
    results: list[dict] = []
    for entry in grouped.values():
        total_qty = entry.get("total_qty") or 0.0
        total_cost = entry.get("total_cost") or 0.0
        avg_price = total_cost / total_qty if total_qty else None
        entry["avg_price"] = avg_price
        results.append(entry)
    return results


def _coerce_float(value) -> Optional[float]:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _coerce_int(value) -> Optional[int]:
    try:
        if value is None:
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None


class _NoopConfigApplier(ConfigApplier):
    async def apply(self, config):
        log_info("config_apply_noop", tenant_id=config.tenant_id, bot_id=config.bot_id, version=config.version)
        return None
