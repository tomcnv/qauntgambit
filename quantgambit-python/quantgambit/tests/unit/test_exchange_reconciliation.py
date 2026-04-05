import asyncio

from quantgambit.execution.reconciliation import SimpleExchangeReconciler
from quantgambit.execution.manager import PositionSnapshot
from quantgambit.portfolio.state_manager import InMemoryStateManager


class FakeProvider:
    def __init__(self, positions):
        self.positions = positions

    async def list_open_positions(self):
        return list(self.positions)


def test_reconciliation_updates_state():
    state = InMemoryStateManager()
    state.add_position("BTC", "long", 1.0)
    state.add_position("ETH", "short", 2.0)

    provider = FakeProvider([
        PositionSnapshot(symbol="BTC", side="long", size=1.5),
        PositionSnapshot(symbol="SOL", side="long", size=3.0),
    ])

    reconciler = SimpleExchangeReconciler(provider, state)
    asyncio.run(reconciler.reconcile())

    assert "ETH" not in state.list_symbols()
    assert "BTC" in state.list_symbols()
    assert "SOL" in state.list_symbols()

