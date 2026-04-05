import asyncio

from quantgambit.execution.manager import RealExecutionManager, ExecutionIntent, OrderStatus, PositionSnapshot


class FakePositionManager:
    def __init__(self):
        self.upserts = 0
        self.finalized = []
        self.positions = []

    async def list_open_positions(self):
        return self.positions

    async def upsert_position(self, snapshot):
        self.upserts += 1

    async def mark_closing(self, symbol, reason):
        return None

    async def finalize_close(self, symbol):
        self.finalized.append(symbol)


class FakeExchangeClient:
    async def close_position(self, symbol, side, size, client_order_id=None):
        raise NotImplementedError

    async def open_position(self, symbol, side, size, stop_loss=None, take_profit=None, client_order_id=None):
        raise NotImplementedError

    async def fetch_order_status(self, order_id, symbol):
        return None


def test_partial_fill_does_not_upsert_position():
    manager = RealExecutionManager(
        exchange_client=FakeExchangeClient(),
        position_manager=FakePositionManager(),
    )
    intent = ExecutionIntent(symbol="BTC", side="buy", size=1.0)
    status = OrderStatus(order_id="o1", status="partially_filled", fill_price=100.0)

    async def run_once():
        await manager.record_order_status(intent, status)

    asyncio.run(run_once())
    assert manager.position_manager.upserts == 0


def test_filled_exit_closes_position():
    manager = RealExecutionManager(
        exchange_client=FakeExchangeClient(),
        position_manager=FakePositionManager(),
    )
    manager.position_manager.positions = [
        PositionSnapshot(
            symbol="BTC",
            side="long",
            size=2.0,
            entry_price=100.0,
            opened_at=10.0,
        )
    ]
    intent = ExecutionIntent(symbol="BTC", side="sell", size=2.0)
    status = OrderStatus(order_id="o2", status="filled", fill_price=110.0)

    async def run_once():
        return await manager.record_order_status(intent, status)

    result = asyncio.run(run_once())
    assert result is True
    assert manager.position_manager.upserts == 0
    assert manager.position_manager.finalized == ["BTC"]
