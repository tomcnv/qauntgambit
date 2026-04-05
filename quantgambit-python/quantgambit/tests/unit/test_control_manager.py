import asyncio
import json

from quantgambit.control.manager import ControlManager
from quantgambit.control.runtime_state import ControlRuntimeState
from quantgambit.storage.redis_streams import RedisStreamsClient


class FakeRedis:
    def __init__(self):
        self.snapshots = {}

    async def xgroup_create(self, stream, group, id="0", mkstream=True):
        return None

    async def xreadgroup(self, group, consumer, streams, count=10, block=1000):
        return []

    async def xack(self, stream, group, message_id):
        return 1

    async def set(self, key, value):
        self.snapshots[key] = value
        return True

    async def expire(self, key, ttl):
        return True


def test_control_manager_writes_state_snapshot():
    redis = FakeRedis()
    state = ControlRuntimeState(
        execution_ready=True,
        execution_block_reason=None,
        trading_disabled=False,
        kill_switch_active=False,
        config_drift_active=False,
        exchange_credentials_configured=True,
    )
    manager = ControlManager(
        redis_client=RedisStreamsClient(redis),
        runtime_state=state,
        tenant_id="t1",
        bot_id="b1",
    )

    async def run_once():
        await manager._snapshot_state_if_due()

    asyncio.run(run_once())
    key = "quantgambit:t1:b1:control:state"
    assert key in redis.snapshots
    snapshot = json.loads(redis.snapshots[key])
    assert snapshot["trading_paused"] is False
    assert snapshot["trading_active"] is True
    assert snapshot["trading_disabled"] is False
    assert snapshot["kill_switch_active"] is False
    assert snapshot["config_drift_active"] is False
    assert snapshot["exchange_credentials_configured"] is True
    assert snapshot["execution_ready"] is True
