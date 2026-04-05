import asyncio

from quantgambit.execution.adapters import BaseExchangeClient
from quantgambit.execution.manager import RealExecutionManager
from quantgambit.execution.position_store import InMemoryPositionStore
from quantgambit.execution.adapters import PositionManagerAdapter
from quantgambit.market.reference_prices import ReferencePriceCache
from quantgambit.observability.telemetry import TelemetryContext
from quantgambit.portfolio.state_manager import InMemoryStateManager


class FakeAdapter:
    def __init__(self):
        self.last_fill = type("Fill", (), {"fill_price": 101.0, "fee_usd": 0.1})()

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


class FakeTelemetry:
    def __init__(self):
        self.orders = []

    async def publish_order(self, ctx, symbol, payload):
        self.orders.append(payload)

    async def publish_positions(self, ctx, payload):
        return None


def test_slippage_bps_calculation():
    state = InMemoryStateManager()
    state.add_position("BTC", "long", 1.0)

    cache = ReferencePriceCache()
    cache.update("BTC", 100.0)

    exchange_client = BaseExchangeClient(FakeAdapter(), reference_prices=cache)
    position_store = InMemoryPositionStore(state)
    position_manager = PositionManagerAdapter(position_store)
    telemetry = FakeTelemetry()
    ctx = TelemetryContext(tenant_id="t1", bot_id="b1", exchange="okx")

    manager = RealExecutionManager(
        exchange_client=exchange_client,
        position_manager=position_manager,
        telemetry=telemetry,
        telemetry_context=ctx,
    )

    result = asyncio.run(manager.flatten_positions())
    assert result.status == "executed"
    assert telemetry.orders
    assert telemetry.orders[0]["slippage_bps"] == 100.0
