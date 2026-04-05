import asyncio
import time
from pathlib import Path

from quantgambit.runtime.app import Runtime, RuntimeConfig
from quantgambit.storage.redis_snapshots import RedisSnapshotWriter, RedisSnapshotReader
from quantgambit.storage.timescale import TimescaleReader
from quantgambit.execution.order_statuses import normalize_order_status
from quantgambit.execution.order_store import InMemoryOrderStore
from quantgambit.observability.telemetry import TelemetryContext


class FakeRedis:
    def __init__(self):
        self.snapshots = {}
        self.histories = {}

    async def set(self, key, value):
        self.snapshots[key] = value

    async def get(self, key):
        return self.snapshots.get(key)

    async def expire(self, key, ttl):
        return True

    async def lpush(self, key, value):
        lst = self.histories.setdefault(key, [])
        lst.insert(0, value)
        return len(lst)

    async def ltrim(self, key, start, stop):
        # no-op for tests
        return True

    async def lrange(self, key, start, stop):
        lst = self.histories.get(key, [])
        return lst[start : stop + 1 if stop >= 0 else None]

    async def xadd(self, stream, data):
        lst = self.histories.setdefault(stream, [])
        lst.append(data)
        return "1-0"

    async def xrevrange(self, stream, count=1):
        lst = self.histories.get(stream, [])
        return lst[-count:]


class FakeTimescaleReader(TimescaleReader):
    def __init__(self, order_payload=None, position_payload=None):
        self.order_payload = order_payload
        self.position_payload = position_payload

    async def load_latest_order_event(self, tenant_id, bot_id):
        return self.order_payload

    async def load_latest_positions(self, tenant_id, bot_id):
        return self.position_payload


class FakeExecutionManager:
    def __init__(self):
        self.recorded_status = None

    async def poll_and_update_status(self, intent):
        return await self.poll_order_status_by_client_id(intent.client_order_id, intent.symbol)

    async def poll_order_status(self, order_id: str, symbol: str):
        return await self.poll_order_status_by_client_id(order_id, symbol)

    async def poll_order_status_by_client_id(self, client_order_id: str, symbol: str):
        from quantgambit.execution.manager import OrderStatus

        self.recorded_status = "filled"
        return OrderStatus(order_id=client_order_id, status="filled", filled_size=1.0, remaining_size=0.0)

    async def record_order_status(self, intent, status):
        self.recorded_status = status.status


class FakeTelemetry:
    def __init__(self):
        self.guardrails = []

    async def publish_guardrail(self, ctx, payload):
        self.guardrails.append(payload)

    async def publish_health_snapshot(self, ctx, payload):
        pass


def test_runtime_restores_positions_and_orders_for_dashboard_after_restart():
    redis = FakeRedis()
    snapshots = RedisSnapshotWriter(redis)
    reader = RedisSnapshotReader(redis)
    order_store = InMemoryOrderStore(
        snapshot_writer=snapshots,
        snapshot_reader=reader,
        tenant_id="t1",
        bot_id="b1",
    )

    async def seed_and_recover():
        # Seed a pending intent (persisted before restart)
        await order_store.record_intent(
            intent_id="intent-2",
            symbol="BTCUSDT",
            side="buy",
            size=1.0,
            client_order_id="cid-2",
            status="submitted",
            created_at=time.time(),
        )
        runtime = Runtime.__new__(Runtime)
        runtime.config = RuntimeConfig(tenant_id="t1", bot_id="b1", exchange="okx")
        runtime.snapshots = snapshots
        runtime.snapshot_reader = reader
        from quantgambit.portfolio.state_manager import InMemoryStateManager

        runtime.state_manager = InMemoryStateManager()
        runtime.timescale_reader = FakeTimescaleReader(
            order_payload={
                "symbol": "BTCUSDT",
                "status": "submitted",
                "order_id": "order-from-timescale-2",
                "client_order_id": "cid-2",
                },
                position_payload={
                    "positions": [{"symbol": "BTCUSDT", "side": "long", "size": 1.0, "entry_price": 25000.0}]
                },
            )
        runtime.order_store = order_store
        runtime.execution_manager = FakeExecutionManager()
        runtime.telemetry = FakeTelemetry()
        runtime.telemetry_context = TelemetryContext(tenant_id="t1", bot_id="b1", exchange="okx")

        await runtime._restore_order_snapshot_from_timescale()
        await runtime._restore_positions_from_timescale()
        await runtime._recover_pending_intents()
        return runtime

    runtime = asyncio.run(seed_and_recover())

    # Order history should be written for dashboard restore
    assert redis.histories, "expected Redis order history to be written"
    # Positions restored into state manager
    assert "BTCUSDT" in runtime.state_manager.list_symbols()
    # Pending intent should be resolved via execution manager poll
    assert normalize_order_status(runtime.execution_manager.recorded_status) == "filled"
    # Guardrail emitted for recovery success
    assert any(gr.get("type") == "order_recovery_resolved" for gr in runtime.telemetry.guardrails)
