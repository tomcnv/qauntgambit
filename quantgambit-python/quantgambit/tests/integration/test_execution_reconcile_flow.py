import asyncio

import pytest

from quantgambit.execution.manager import ExecutionIntent, OrderStatus, RealExecutionManager
from quantgambit.execution.order_store import InMemoryOrderStore
from quantgambit.execution.adapters import PositionManagerAdapter
from quantgambit.execution.position_store import InMemoryPositionStore
from quantgambit.portfolio.state_manager import InMemoryStateManager


class FakeExchangeClient:
    def __init__(self, trades):
        self._trades = trades
        self.fetch_calls = []

    async def open_position(self, symbol, side, size, stop_loss=None, take_profit=None, client_order_id=None):
        return OrderStatus(
            order_id="order-1",
            status="filled",
            fill_price=105.0,
            fee_usd=0.05,
            filled_size=size,
            timestamp=1000.0,
        )

    async def close_position(self, symbol, side, size, client_order_id=None):
        raise NotImplementedError

    async def fetch_executions(self, symbol, order_id=None, client_order_id=None, since_ms=None, limit=100):
        self.fetch_calls.append(
            {
                "symbol": symbol,
                "order_id": order_id,
                "client_order_id": client_order_id,
                "since_ms": since_ms,
                "limit": limit,
            }
        )
        return list(self._trades)


def test_execute_intent_reconciles_exchange_fills():
    trades = [
        {"orderId": "order-1", "qty": 0.4, "price": 100.0, "fee": 0.25, "timestamp": 1000},
        {"orderId": "order-1", "qty": 0.6, "price": 98.0, "fee": 0.35, "timestamp": 1001},
    ]
    exchange = FakeExchangeClient(trades)
    state_manager = InMemoryStateManager()
    position_store = InMemoryPositionStore(state_manager)
    position_manager = PositionManagerAdapter(position_store)
    order_store = InMemoryOrderStore()
    manager = RealExecutionManager(
        exchange_client=exchange,
        position_manager=position_manager,
        order_store=order_store,
    )
    intent = ExecutionIntent(
        symbol="BTCUSDT",
        side="buy",
        size=1.0,
        client_order_id="client-1",
    )

    asyncio.run(manager.execute_intent(intent))

    record = order_store.get("order-1")
    assert record is not None
    assert record.filled_size == pytest.approx(1.0)
    latest = record.history[-1]
    assert latest.fill_price == pytest.approx(98.8)
    assert latest.fee_usd == pytest.approx(0.6)
    assert exchange.fetch_calls
    assert exchange.fetch_calls[-1]["order_id"] == "order-1"
    assert exchange.fetch_calls[-1]["client_order_id"] == "client-1"

    positions = asyncio.run(position_manager.list_positions())
    assert len(positions) == 1
    assert positions[0].entry_price == pytest.approx(98.8)
