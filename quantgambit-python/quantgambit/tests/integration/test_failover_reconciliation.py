import asyncio

from quantgambit.execution.manager import RealExecutionManager, ExchangeReconciler
from quantgambit.execution.router import ExchangeRouterImpl, AdapterRegistry, ExchangeRouterState
from quantgambit.execution.adapters import AdapterConfig
from quantgambit.execution.position_store import InMemoryPositionStore
from quantgambit.execution.adapters import PositionManagerAdapter
from quantgambit.portfolio.state_manager import InMemoryStateManager


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


class FakeReconciler(ExchangeReconciler):
    def __init__(self):
        self.called = 0

    async def reconcile(self) -> bool:
        self.called += 1
        return True


def test_failover_triggers_reconciliation():
    registry = AdapterRegistry()
    registry.register("okx", FakeAdapter())
    registry.register("bybit", FakeAdapter())

    router = ExchangeRouterImpl(
        ExchangeRouterState(
            active_exchange="okx",
            primary_exchange="okx",
            secondary_exchange="bybit",
        ),
        registry,
        adapter_config=AdapterConfig(order_type="market"),
    )

    state = InMemoryStateManager()
    store = InMemoryPositionStore(state)
    position_manager = PositionManagerAdapter(store)

    reconciler = FakeReconciler()
    manager = RealExecutionManager(
        exchange_client=router.active_client,
        position_manager=position_manager,
        exchange_router=router,
        reconciler=reconciler,
    )

    result = asyncio.run(manager.execute_failover())
    assert result.status == "executed"
    assert reconciler.called == 1
