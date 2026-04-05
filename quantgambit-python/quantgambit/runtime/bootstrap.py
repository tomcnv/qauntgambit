"""Runtime bootstrap helpers for wiring exchange adapters and reconcilers."""

from __future__ import annotations

from typing import Optional, Union

from quantgambit.execution.reconciliation import build_reconciler, SimpleExchangeReconciler
from quantgambit.execution.router import AdapterRegistry, ExchangeRouterImpl, ExchangeRouterState
from quantgambit.execution.adapters import AdapterConfig, ExchangeAdapterProtocol
from quantgambit.market.reference_prices import ReferencePriceCache
from quantgambit.market.updater import MarketDataProvider, MarketDataUpdater
from quantgambit.portfolio.state_manager import InMemoryStateManager


class ExchangeBootstrap:
    """Wire exchange adapters, router, and reconciler."""

    def __init__(
        self,
        adapter_registry: AdapterRegistry,
        state_manager: InMemoryStateManager,
        adapter_config: Optional[AdapterConfig] = None,
    ):
        self.registry = adapter_registry
        self.state_manager = state_manager
        self.adapter_config = adapter_config

    def build_router(self, primary_exchange: str, secondary_exchange: str) -> ExchangeRouterImpl:
        state = ExchangeRouterState(
            active_exchange=primary_exchange,
            primary_exchange=primary_exchange,
            secondary_exchange=secondary_exchange,
        )
        return ExchangeRouterImpl(state, self.registry, adapter_config=self.adapter_config)

    def build_reconciler(
        self, exchange_name: str, adapter: ExchangeAdapterProtocol
    ) -> SimpleExchangeReconciler:
        """Build a simple reconciler for the given exchange."""
        return build_reconciler(exchange_name, adapter, self.state_manager)

    def build_market_updater(
        self,
        cache: ReferencePriceCache,
        provider: MarketDataProvider,
    ) -> MarketDataUpdater:
        return MarketDataUpdater(cache, provider)
