import asyncio

from quantgambit.execution.manager import PositionSnapshot
from quantgambit.portfolio.state_manager import InMemoryStateManager
from quantgambit.storage.timescale import TimescaleReader
from quantgambit.runtime.app import Runtime, RuntimeConfig


class FakeConn:
    def __init__(self, payload):
        self.payload = payload

    async def fetchrow(self, query, tenant_id, bot_id):
        return {"payload": self.payload}


class FakeAcquire:
    def __init__(self, payload):
        self.payload = payload

    async def __aenter__(self):
        return FakeConn(self.payload)

    async def __aexit__(self, exc_type, exc, tb):
        return False


class FakePool:
    def __init__(self, payload):
        self.payload = payload

    def acquire(self):
        return FakeAcquire(self.payload)


class FakeSnapshots:
    def __init__(self):
        self.writes = []
        self.histories = []

    async def write(self, key, payload):
        self.writes.append((key, payload))

    async def append_history(self, key, payload, max_items=100):
        self.histories.append((key, payload, max_items))


def test_timescale_reader_loads_latest_positions():
    reader = TimescaleReader(
        FakePool(
            {
                "positions": [
                    {
                        "symbol": "BTC",
                        "side": "long",
                        "size": 1.0,
                        "entry_price": 100.0,
                        "reference_price": 101.0,
                        "stop_loss": 95.0,
                        "take_profit": 110.0,
                        "opened_at": 1700000000.0,
                        "prediction_confidence": 0.7,
                        "strategy_id": "trend",
                        "profile_id": "aggressive",
                    }
                ]
            }
        )
    )

    async def run_once():
        return await reader.load_latest_positions("t1", "b1")

    payload = asyncio.run(run_once())
    assert payload
    assert payload["positions"][0]["symbol"] == "BTC"


def test_timescale_reader_loads_latest_order_event():
    reader = TimescaleReader(
        FakePool(
            {
                "symbol": "BTC",
                "status": "filled",
                "order_id": "o1",
            }
        )
    )

    async def run_once():
        return await reader.load_latest_order_event("t1", "b1")

    payload = asyncio.run(run_once())
    assert payload
    assert payload["order_id"] == "o1"


def test_state_manager_restore_positions():
    state = InMemoryStateManager()
    snapshots = [
        PositionSnapshot(
            symbol="BTC",
            side="long",
            size=1.0,
            entry_price=100.0,
            reference_price=101.0,
            stop_loss=95.0,
            take_profit=110.0,
            opened_at=1700000000.0,
            prediction_confidence=0.7,
            prediction_source="heuristic_v2",
            model_side="long",
            p_up=0.62,
            p_down=0.19,
            p_flat=0.19,
            strategy_id="trend",
            profile_id="aggressive",
        )
    ]
    state.restore_positions(snapshots)
    symbols = state.list_symbols()
    assert symbols == ["BTC"]
    restored = asyncio.run(state.list_open_positions())[0]
    assert restored.prediction_source == "heuristic_v2"
    assert restored.model_side == "long"
    assert restored.p_up == 0.62


def test_runtime_restores_positions_snapshot_to_redis():
    reader = TimescaleReader(
        FakePool(
            {
                "positions": [
                    {
                        "symbol": "BTC",
                        "side": "long",
                        "size": 1.0,
                    }
                ]
            }
        )
    )
    runtime = Runtime.__new__(Runtime)
    runtime.config = RuntimeConfig(tenant_id="t1", bot_id="b1", exchange="okx")
    runtime.timescale_reader = reader
    runtime.state_manager = InMemoryStateManager()
    runtime.snapshots = FakeSnapshots()

    async def run_once():
        await runtime._restore_positions_from_timescale()

    asyncio.run(run_once())
    assert runtime.snapshots.writes
    key, payload = runtime.snapshots.writes[0]
    assert key.endswith(":positions:latest")
    assert payload["positions"][0]["symbol"] == "BTC"


def test_runtime_restores_order_snapshot_to_redis():
    reader = TimescaleReader(
        FakePool(
            {
                "symbol": "BTC",
                "status": "filled",
                "order_id": "o1",
            }
        )
    )
    runtime = Runtime.__new__(Runtime)
    runtime.config = RuntimeConfig(tenant_id="t1", bot_id="b1", exchange="okx")
    runtime.timescale_reader = reader
    runtime.snapshots = FakeSnapshots()

    async def run_once():
        await runtime._restore_order_snapshot_from_timescale()

    asyncio.run(run_once())
    assert runtime.snapshots.histories
    key, payload, _ = runtime.snapshots.histories[0]
    assert key.endswith(":order:history")
    assert payload["order_id"] == "o1"
