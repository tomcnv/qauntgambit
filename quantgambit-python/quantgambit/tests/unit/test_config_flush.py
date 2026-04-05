import asyncio

from quantgambit.config.safety import SafeConfigApplier
from quantgambit.control.runtime_state import ControlRuntimeState
from quantgambit.execution.manager import PositionSnapshot


class FakePositionManager:
    def __init__(self, positions):
        self.positions = positions

    async def list_open_positions(self):
        return list(self.positions)


class FakeRepository:
    def __init__(self):
        self.applied = []

    def apply(self, config):
        self.applied.append(config)


class FakeDelegate:
    def __init__(self):
        self.applied = []

    async def apply(self, config):
        self.applied.append(config)


def test_config_flush_when_safe():
    runtime_state = ControlRuntimeState(trading_paused=True)
    applier = SafeConfigApplier(runtime_state, FakePositionManager([]), FakeRepository(), FakeDelegate())

    cfg = type("Cfg", (), {"version": 1})()
    asyncio.run(applier.apply(cfg))
    asyncio.run(applier.flush_if_safe())

    assert applier._pending == []


def test_config_flush_blocked_with_positions():
    runtime_state = ControlRuntimeState(trading_paused=True)
    applier = SafeConfigApplier(
        runtime_state,
        FakePositionManager([PositionSnapshot("BTC", "long", 1.0)]),
        FakeRepository(),
        FakeDelegate(),
    )

    cfg = type("Cfg", (), {"version": 1})()
    asyncio.run(applier.apply(cfg))
    asyncio.run(applier.flush_if_safe())

    assert applier._pending
