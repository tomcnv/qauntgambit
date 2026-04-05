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
    def apply(self, config):
        return None


class FakeDelegate:
    async def apply(self, config):
        return None


def test_config_blocked_when_trading_active():
    runtime_state = ControlRuntimeState(trading_paused=False)
    applier = SafeConfigApplier(runtime_state, FakePositionManager([]), FakeRepository(), FakeDelegate())
    asyncio.run(applier.apply(type("Cfg", (), {"version": 1})()))


def test_config_blocked_with_positions():
    runtime_state = ControlRuntimeState(trading_paused=True)
    applier = SafeConfigApplier(
        runtime_state,
        FakePositionManager([PositionSnapshot("BTC", "long", 1.0)]),
        FakeRepository(),
        FakeDelegate(),
    )
    asyncio.run(applier.apply(type("Cfg", (), {"version": 1})()))
