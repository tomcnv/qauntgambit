import asyncio

from quantgambit.execution.router import AdapterRegistry, ExchangeRouterImpl, ExchangeRouterState


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


def test_exchange_router_switches():
    registry = AdapterRegistry()
    registry.register("okx", FakeAdapter())
    registry.register("bybit", FakeAdapter())

    state = ExchangeRouterState(
        active_exchange="okx",
        primary_exchange="okx",
        secondary_exchange="bybit",
    )

    router = ExchangeRouterImpl(state, registry)
    assert router.state.active_exchange == "okx"

    result = asyncio.run(router.switch_to_secondary())
    assert result is True
    assert router.state.active_exchange == "bybit"

    result = asyncio.run(router.switch_to_primary())
    assert result is True
    assert router.state.active_exchange == "okx"
