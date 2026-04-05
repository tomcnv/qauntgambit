import asyncio

from quantgambit.execution.manager import OrderStatus
from quantgambit.execution.order_store import InMemoryOrderStore
from quantgambit.observability.telemetry import TelemetryContext
from quantgambit.runtime.app import Runtime, RuntimeConfig
from quantgambit.storage.redis_snapshots import RedisSnapshotReader, RedisSnapshotWriter


class FakeRedis:
    def __init__(self):
        self.data = {}
        self.lists = {}

    async def set(self, key, value):
        self.data[key] = value

    async def expire(self, key, ttl):
        return True

    async def lpush(self, key, value):
        self.lists.setdefault(key, []).insert(0, value)

    async def ltrim(self, key, start, end):
        self.lists[key] = self.lists.get(key, [])[start : end + 1]

    async def lrange(self, key, start, end):
        return self.lists.get(key, [])[start : end + 1]

    async def get(self, key):
        return self.data.get(key)


class FakeExecutionManager:
    def __init__(self):
        self.recorded = []

    async def poll_order_status(self, order_id, symbol):
        return None

    async def poll_order_status_by_client_id(self, client_order_id, symbol):
        return OrderStatus(order_id="o1", status="filled")

    async def record_order_status(self, intent, status):
        self.recorded.append((intent, status))
        return True


class FakeTelemetry:
    def __init__(self):
        self.guardrails = []

    async def publish_guardrail(self, ctx, payload):
        self.guardrails.append(payload)


def test_runtime_recovers_pending_intents_from_snapshots():
    redis = FakeRedis()
    writer = RedisSnapshotWriter(redis)
    reader = RedisSnapshotReader(redis)
    order_store = InMemoryOrderStore(
        snapshot_writer=writer,
        snapshot_reader=reader,
        tenant_id="t1",
        bot_id="b1",
    )

    async def seed_and_recover():
        await order_store.record_intent(
            intent_id="i1",
            symbol="BTC",
            side="buy",
            size=1.0,
            client_order_id="c1",
            status="submitted",
        )
        runtime = Runtime.__new__(Runtime)
        runtime.config = RuntimeConfig(tenant_id="t1", bot_id="b1", exchange="okx")
        runtime.order_store = order_store
        runtime.execution_manager = FakeExecutionManager()
        runtime.telemetry = FakeTelemetry()
        runtime.telemetry_context = TelemetryContext(tenant_id="t1", bot_id="b1", exchange="okx")
        await runtime._recover_pending_intents()
        return runtime

    runtime = asyncio.run(seed_and_recover())
    assert runtime.execution_manager.recorded
    assert any(item.get("type") == "order_recovery_resolved" for item in runtime.telemetry.guardrails)
