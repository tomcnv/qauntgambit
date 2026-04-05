import asyncio

from quantgambit.execution.wiring import build_execution_manager
from quantgambit.portfolio.state_manager import InMemoryStateManager
from quantgambit.execution.adapters import AdapterConfig


class FakeExchangeAdapter:
    def __init__(self):
        self.calls = []

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
        post_only=False,
        time_in_force=None,
    ):
        self.calls.append({
            "symbol": symbol,
            "side": side,
            "size": size,
            "order_type": order_type,
            "price": price,
            "reduce_only": reduce_only,
        })
        return {"success": True, "status": "filled", "order_id": "fake-1"}


def test_build_execution_manager_and_flatten():
    adapter = FakeExchangeAdapter()
    state = InMemoryStateManager()
    state.add_position("BTC", "long", 1.0)

    manager = build_execution_manager(
        exchange_name="okx",
        adapter=adapter,
        state_manager=state,
        adapter_config=AdapterConfig(order_type="market"),
    )

    result = asyncio.run(manager.flatten_positions())
    assert result.status == "executed"
    assert adapter.calls[0]["side"] == "sell"


def test_build_execution_manager_paper_mode():
    state = InMemoryStateManager()
    state.add_position("BTC", "long", 1.0)

    manager = build_execution_manager(
        exchange_name="okx",
        adapter=None,
        state_manager=state,
        trading_mode="paper",
    )

    result = asyncio.run(manager.flatten_positions())
    assert result.status == "executed"
