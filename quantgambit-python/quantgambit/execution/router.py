"""Exchange router for manual failover switching."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from quantgambit.execution.adapters import (
    AdapterConfig,
    BaseExchangeClient,
    BinanceExchangeClient,
    BybitExchangeClient,
    OkxExchangeClient,
    ExchangeAdapterProtocol,
)
from quantgambit.execution.manager import ExchangeRouter


@dataclass
class ExchangeRouterState:
    active_exchange: str
    primary_exchange: str
    secondary_exchange: str


class AdapterRegistry:
    """Registry for exchange adapters keyed by exchange name."""

    def __init__(self):
        self._adapters = {}

    def register(self, exchange_name: str, adapter: ExchangeAdapterProtocol) -> None:
        self._adapters[exchange_name.strip().lower()] = adapter

    def get(self, exchange_name: str) -> Optional[ExchangeAdapterProtocol]:
        return self._adapters.get(exchange_name.strip().lower())


class ExchangeRouterImpl(ExchangeRouter):
    """Router that swaps the active exchange client on failover."""

    def __init__(
        self,
        state: ExchangeRouterState,
        adapter_registry: AdapterRegistry,
        adapter_config: Optional[AdapterConfig] = None,
    ):
        self.state = state
        self.registry = adapter_registry
        self.adapter_config = adapter_config
        self.active_client: BaseExchangeClient = self._build_client(state.active_exchange)

    async def switch_to_secondary(self) -> bool:
        if self.state.active_exchange == self.state.secondary_exchange:
            return True
        client = self._build_client(self.state.secondary_exchange)
        if not client:
            return False
        self.active_client = client
        self.state.active_exchange = self.state.secondary_exchange
        return True

    async def switch_to_primary(self) -> bool:
        if self.state.active_exchange == self.state.primary_exchange:
            return True
        client = self._build_client(self.state.primary_exchange)
        if not client:
            return False
        self.active_client = client
        self.state.active_exchange = self.state.primary_exchange
        return True

    def _build_client(self, exchange_name: str) -> BaseExchangeClient:
        adapter = self.registry.get(exchange_name)
        if not adapter:
            raise ValueError(f"adapter not registered for {exchange_name}")
        normalized = exchange_name.strip().lower()
        if normalized == "okx":
            return OkxExchangeClient(adapter, self.adapter_config)
        if normalized == "bybit":
            return BybitExchangeClient(adapter, self.adapter_config)
        if normalized == "binance":
            return BinanceExchangeClient(adapter, self.adapter_config)
        return BaseExchangeClient(adapter, self.adapter_config)

