import asyncio
import time

from quantgambit.execution.manager import ExecutionIntent, OrderStatus
from quantgambit.execution.order_store import InMemoryOrderStore
from quantgambit.observability.telemetry import TelemetryContext
from quantgambit.runtime.app import Runtime, RuntimeConfig
from quantgambit.storage.redis_snapshots import RedisSnapshotWriter


class FakeRedis:
    def __init__(self):
        self.data = {}
        self.histories = {}

    async def set(self, key, value):
        self.data[key] = value

    async def expire(self, key, ttl):
        return True

    async def lpush(self, key, value):
        self.histories.setdefault(key, []).insert(0, value)

    async def ltrim(self, key, start, end):
        if key in self.histories:
            self.histories[key] = self.histories[key][start : end + 1]
        return True

    async def lrange(self, key, start, end):
        return self.histories.get(key, [])[start : end + 1]


class FakeTimescaleReader:
    def __init__(self, order_payload=None):
        self.order_payload = order_payload or {}
        self.calls = 0

    async def load_latest_order_event(self, tenant_id: str, bot_id: str):
        self.calls += 1
        return self.order_payload


class FakeExecutionManager:
    def __init__(self):
        self.recorded_status = []

    async def poll_order_status(self, order_id, symbol):
        return OrderStatus(order_id=order_id, status="filled")

    async def poll_order_status_by_client_id(self, client_order_id, symbol):
        return OrderStatus(order_id="recovered", status="filled")

    async def record_order_status(self, intent: ExecutionIntent, status: OrderStatus):
        self.recorded_status.append((intent, status))
        return True


class FakeTelemetry:
    def __init__(self):
        self.guardrails = []
        self.health = []

    async def publish_guardrail(self, ctx, payload):
        self.guardrails.append(payload)

    async def publish_health_snapshot(self, ctx, payload):
        self.health.append(payload)


def test_runtime_recovers_orders_from_timescale_and_resolves_pending_intents():
    redis = FakeRedis()
    snapshots = RedisSnapshotWriter(redis)
    from quantgambit.storage.redis_snapshots import RedisSnapshotReader

    order_store = InMemoryOrderStore(
        snapshot_writer=snapshots,
        snapshot_reader=RedisSnapshotReader(redis),
        tenant_id="t1",
        bot_id="b1",
    )

    async def seed_and_recover():
        await order_store.record_intent(
            intent_id="intent-1",
            symbol="BTCUSDT",
            side="buy",
            size=1.0,
            client_order_id="cid-1",
            status="submitted",
            created_at=time.time(),
        )
        runtime = Runtime.__new__(Runtime)
        runtime.config = RuntimeConfig(tenant_id="t1", bot_id="b1", exchange="okx")
        runtime.snapshots = snapshots
        runtime.timescale_reader = FakeTimescaleReader(
            {
                "symbol": "BTCUSDT",
                "status": "submitted",
                "order_id": "order-from-timescale",
                "client_order_id": "cid-1",
            }
        )
        runtime.order_store = order_store
        runtime.execution_manager = FakeExecutionManager()
        runtime.telemetry = FakeTelemetry()
        runtime.telemetry_context = TelemetryContext(tenant_id="t1", bot_id="b1", exchange="okx")

        await runtime._restore_order_snapshot_from_timescale()
        await runtime._recover_pending_intents()
        return runtime

    runtime = asyncio.run(seed_and_recover())
    # Timescale snapshot should be written to Redis history for dashboard restore
    assert redis.histories
    # Pending intent should be resolved via poll + record
    assert runtime.execution_manager.recorded_status
    # Guardrail emitted for recovery success
    assert any(gr.get("type") == "order_recovery_resolved" for gr in runtime.telemetry.guardrails)
