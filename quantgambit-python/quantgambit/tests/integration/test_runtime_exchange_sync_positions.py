import asyncio
import time

from quantgambit.runtime.app import Runtime, RuntimeConfig
from quantgambit.execution.position_store import InMemoryPositionStore
from quantgambit.execution.adapters import PositionManagerAdapter
from quantgambit.portfolio.state_manager import InMemoryStateManager


class FakeExchangeClient:
    def __init__(self, positions):
        self._positions = positions

    async def fetch_positions(self):
        return list(self._positions)


class FakeExecutionManager:
    def __init__(self, exchange_client, position_manager):
        self.exchange_client = exchange_client
        self.position_manager = position_manager


def test_runtime_sync_positions_removes_and_updates():
    state_manager = InMemoryStateManager()
    # Local positions: BTC + ETH
    opened_at_btc = time.time() - 3600.0
    state_manager.add_position("BTCUSDT", "long", 1.0, entry_price=100.0, opened_at=opened_at_btc)
    state_manager.add_position("ETHUSDT", "long", 2.0, entry_price=2000.0, opened_at=time.time())

    position_store = InMemoryPositionStore(state_manager)
    position_manager = PositionManagerAdapter(position_store)

    exchange_positions = [
        {
            "symbol": "BTCUSDT",
            "size": 2.5,
            "side": "long",
            "entryPrice": 105.0,
            "stopLoss": 95.0,
            "takeProfit": 120.0,
            "updatedTime": int(time.time() * 1000),
        },
        {
            "symbol": "SOLUSDT",
            "size": -3.0,
            "side": "short",
            "entryPrice": 90.0,
            "stopLoss": 98.0,
            "takeProfit": 80.0,
            "updatedTime": int(time.time() * 1000),
        },
    ]
    exchange_client = FakeExchangeClient(exchange_positions)
    execution_manager = FakeExecutionManager(exchange_client, position_manager)

    runtime = Runtime.__new__(Runtime)
    runtime.config = RuntimeConfig(tenant_id="t1", bot_id="b1", exchange="bybit", trading_mode="live")
    runtime.execution_manager = execution_manager
    runtime.exchange_positions_remove_after_misses = 2
    runtime._exchange_position_miss_counts = {}

    # First sync should defer removal for transient exchange gaps.
    asyncio.run(runtime._sync_positions_from_exchange())
    symbols_first = set(state_manager.list_symbols())
    assert "ETHUSDT" in symbols_first

    # Second consecutive miss should remove stale local position.
    asyncio.run(runtime._sync_positions_from_exchange())
    symbols = set(state_manager.list_symbols())
    assert "ETHUSDT" not in symbols  # stale local removed
    assert "BTCUSDT" in symbols
    assert "SOLUSDT" in symbols

    btc = next(pos for pos in asyncio.run(position_manager.list_positions()) if pos.symbol == "BTCUSDT")
    sol = next(pos for pos in asyncio.run(position_manager.list_positions()) if pos.symbol == "SOLUSDT")
    assert abs(btc.size - 2.5) < 1e-6
    assert btc.stop_loss == 95.0
    assert btc.take_profit == 120.0
    # Exchange sync must not "refresh" opened_at, otherwise time-based exits never trigger.
    assert btc.opened_at == opened_at_btc
    assert sol.side == "short"
    assert abs(sol.size - 3.0) < 1e-6


def test_runtime_sync_positions_preserves_first_seen_opened_at_when_local_state_churns():
    state_manager = InMemoryStateManager()
    position_store = InMemoryPositionStore(state_manager)
    position_manager = PositionManagerAdapter(position_store)
    execution_manager = FakeExecutionManager(FakeExchangeClient([]), position_manager)

    runtime = Runtime.__new__(Runtime)
    runtime.config = RuntimeConfig(tenant_id="t1", bot_id="b1", exchange="bybit", trading_mode="live")
    runtime.execution_manager = execution_manager
    runtime.exchange_positions_remove_after_misses = 3
    runtime._exchange_position_miss_counts = {}
    runtime._exchange_position_first_seen_opened_at = {}

    first_ts = int((time.time() - 120.0) * 1000)
    execution_manager.exchange_client._positions = [
        {"symbol": "SOLUSDT", "size": -1.0, "side": "short", "entryPrice": 90.0, "updatedTime": first_ts}
    ]
    asyncio.run(runtime._sync_positions_from_exchange())
    first_pos = next(pos for pos in asyncio.run(position_manager.list_positions()) if pos.symbol == "SOLUSDT")
    first_opened_at = float(first_pos.opened_at or 0.0)
    assert first_opened_at > 0

    # Simulate transient local-state loss while exchange keeps returning a newer "updatedTime".
    asyncio.run(position_manager.finalize_close("SOLUSDT"))
    later_ts = int(time.time() * 1000)
    execution_manager.exchange_client._positions = [
        {"symbol": "SOLUSDT", "size": -1.0, "side": "short", "entryPrice": 90.0, "updatedTime": later_ts}
    ]
    asyncio.run(runtime._sync_positions_from_exchange())

    recovered_pos = next(pos for pos in asyncio.run(position_manager.list_positions()) if pos.symbol == "SOLUSDT")
    assert recovered_pos.opened_at == first_opened_at
