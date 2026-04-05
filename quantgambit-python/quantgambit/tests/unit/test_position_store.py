import asyncio

from quantgambit.execution.position_store import InMemoryPositionStore
from quantgambit.portfolio.state_manager import InMemoryStateManager


def test_in_memory_position_store_lifecycle():
    state = InMemoryStateManager()
    state.add_position("BTC", "long", 1.0, reference_price=100.0)

    store = InMemoryPositionStore(state)
    positions = asyncio.run(store.list_positions())
    assert len(positions) == 1
    assert positions[0].reference_price == 100.0

    asyncio.run(store.mark_closing("BTC", "manual"))
    positions_after = asyncio.run(store.list_positions())
    assert len(positions_after) == 0

    asyncio.run(store.finalize_close("BTC"))
    positions_final = asyncio.run(store.list_positions())
    assert len(positions_final) == 0
