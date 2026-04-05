from quantgambit.execution.adapters import AdapterConfig
from quantgambit.execution.router import AdapterRegistry
from quantgambit.portfolio.state_manager import InMemoryStateManager
from quantgambit.runtime.bootstrap import ExchangeBootstrap


class FakeAdapter:
    async def place_order(
        self,
        symbol,
        side,
        size,
        order_type,
        price=None,
        reduce_only=False,
        stop_loss=None,
        take_profit=None,
        client_order_id=None,
    ):
        return True

    async def list_positions(self):
        return []


def test_exchange_bootstrap_builds_router_and_reconciler():
    registry = AdapterRegistry()
    registry.register("okx", FakeAdapter())
    state = InMemoryStateManager()
    bootstrap = ExchangeBootstrap(registry, state, AdapterConfig(order_type="market"))

    router = bootstrap.build_router("okx", "bybit")
    assert router.state.active_exchange == "okx"

    reconciler = bootstrap.build_reconciler("okx", FakeAdapter())
    assert reconciler is not None
