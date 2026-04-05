import asyncio

from quantgambit.execution.reconciliation import build_reconciler
from quantgambit.execution.manager import PositionSnapshot
from quantgambit.portfolio.state_manager import InMemoryStateManager


class FakePositionsAdapter:
    def __init__(self, positions):
        self._positions = positions

    async def list_positions(self):
        return list(self._positions)


def test_build_reconciler_and_sync():
    state = InMemoryStateManager()
    state.add_position("BTC", "long", 1.0)

    adapter = FakePositionsAdapter([
        PositionSnapshot(symbol="ETH", side="short", size=2.0),
    ])

    reconciler = build_reconciler("okx", adapter, state)
    asyncio.run(reconciler.reconcile())

    assert "BTC" not in state.list_symbols()
    assert "ETH" in state.list_symbols()

