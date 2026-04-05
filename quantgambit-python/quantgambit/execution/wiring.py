"""Wiring helpers for execution manager setup."""

from __future__ import annotations

from typing import Optional

from quantgambit.execution.adapters import (
    AdapterConfig,
    BaseExchangeClient,
    BinanceExchangeClient,
    BybitExchangeClient,
    OkxExchangeClient,
    PositionManagerAdapter,
    ExchangeAdapterProtocol,
    ReferencePriceProvider,
)
from quantgambit.execution.manager import (
    ExecutionManager,
    RealExecutionManager,
    RiskManager,
    ExchangeRouter,
    ExchangeReconciler,
)
from quantgambit.execution.order_store import InMemoryOrderStore
from quantgambit.observability.telemetry import TelemetryContext, TelemetryPipeline
from quantgambit.execution.position_store import InMemoryPositionStore
from quantgambit.execution.paper import PaperExchangeAdapter, PaperFillEngine, PaperTradingConfig
from quantgambit.portfolio.state_manager import InMemoryStateManager
from quantgambit.storage.redis_streams import RedisStreamsClient
from quantgambit.execution.guards import GuardConfig, GuardedExchangeClient


def build_execution_manager(
    exchange_name: str,
    adapter: Optional[ExchangeAdapterProtocol],
    state_manager: InMemoryStateManager,
    risk_manager: Optional[RiskManager] = None,
    exchange_router: Optional[ExchangeRouter] = None,
    reconciler: Optional[ExchangeReconciler] = None,
    adapter_config: Optional[AdapterConfig] = None,
    trading_mode: str = "live",
    paper_fill_engine: Optional[PaperFillEngine] = None,
    paper_config: Optional[PaperTradingConfig] = None,
    redis_client: Optional[RedisStreamsClient] = None,
    bot_id: Optional[str] = None,
    reference_prices: Optional[ReferencePriceProvider] = None,
    telemetry: Optional[TelemetryPipeline] = None,
    telemetry_context: Optional[TelemetryContext] = None,
    order_store: Optional[InMemoryOrderStore] = None,
    guard_config: Optional[GuardConfig] = None,
    snapshot_reader=None,
    profile_feedback=None,
) -> ExecutionManager:
    """Create a RealExecutionManager wired to the in-memory position store."""

    position_store = InMemoryPositionStore(state_manager)
    position_manager = PositionManagerAdapter(position_store)
    exchange_client = _build_exchange_client(
        exchange_name,
        adapter,
        adapter_config,
        trading_mode=trading_mode,
        paper_fill_engine=paper_fill_engine,
        paper_config=paper_config,
        redis_client=redis_client,
        bot_id=bot_id,
        reference_prices=reference_prices,
    )
    if guard_config:
        exchange_client = GuardedExchangeClient(
            exchange_client,
            guard_config,
            telemetry=telemetry,
            telemetry_context=telemetry_context,
        )

    return RealExecutionManager(
        exchange_client=exchange_client,
        position_manager=position_manager,
        risk_manager=risk_manager,
        exchange_router=exchange_router,
        reconciler=reconciler,
        telemetry=telemetry,
        telemetry_context=telemetry_context,
        order_store=order_store,
        snapshot_reader=snapshot_reader,
        profile_feedback=profile_feedback,
        reference_prices=reference_prices,
    )


def _build_exchange_client(
    exchange_name: str,
    adapter: Optional[ExchangeAdapterProtocol],
    config: Optional[AdapterConfig],
    trading_mode: str,
    paper_fill_engine: Optional[PaperFillEngine],
    paper_config: Optional[PaperTradingConfig],
    redis_client: Optional[RedisStreamsClient],
    bot_id: Optional[str],
    reference_prices: Optional[ReferencePriceProvider],
) -> BaseExchangeClient:
    normalized = exchange_name.strip().lower()
    if trading_mode.lower() == "paper":
        fill_engine = paper_fill_engine or PaperFillEngine()
        adapter = PaperExchangeAdapter(
            fill_engine=fill_engine,
            config=paper_config,
            redis_client=redis_client,
            bot_id=bot_id,
            exchange=normalized,
        )
        return BaseExchangeClient(adapter, config, reference_prices=reference_prices)
    if adapter is None:
        raise ValueError("adapter is required for live trading mode")
    if normalized == "okx":
        return OkxExchangeClient(adapter, config, reference_prices=reference_prices)
    if normalized == "bybit":
        return BybitExchangeClient(adapter, config, reference_prices=reference_prices)
    if normalized == "binance":
        return BinanceExchangeClient(adapter, config, reference_prices=reference_prices)
    if adapter is None:
        raise ValueError("adapter is required for live trading mode")
    return BaseExchangeClient(adapter, config, reference_prices=reference_prices)
