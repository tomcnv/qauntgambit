import asyncio
import json

from quantgambit.execution.manager import ExecutionIntent, OrderStatus
from quantgambit.execution.order_store import InMemoryOrderStore
from quantgambit.execution.order_update_consumer import OrderUpdateConsumer
from quantgambit.observability.telemetry import TelemetryPipeline, TelemetryContext
from quantgambit.storage.redis_streams import RedisStreamsClient


class FakeRedis:
    async def xgroup_create(self, stream, group, id="0", mkstream=True):
        return None

    async def xreadgroup(self, group, consumer, streams, count=10, block=1000):
        return []

    async def xack(self, stream, group, message_id):
        return 1


class FakeExecutionManager:
    def __init__(self, order_store=None):
        self.calls = []
        self.order_store = order_store

    async def record_order_status(self, intent: ExecutionIntent, status: OrderStatus) -> bool:
        self.calls.append((intent, status))
        return True


class FakeTimescale:
    def __init__(self):
        self.writes = []

    async def write(self, table, row):
        self.writes.append((table, row))


def test_order_update_consumer_records_updates():
    manager = FakeExecutionManager()
    timescale = FakeTimescale()
    telemetry = TelemetryPipeline(timescale_writer=timescale)
    ctx = TelemetryContext(tenant_id="t1", bot_id="b1", exchange="okx")
    consumer = OrderUpdateConsumer(
        RedisStreamsClient(FakeRedis()),
        manager,
        telemetry=telemetry,
        telemetry_context=ctx,
    )
    ts_us = 1_000_000
    event = {
        "event_id": "evt-1",
        "event_type": "order_update",
        "schema_version": "v1",
        "timestamp": "1",
        "ts_recv_us": ts_us,
        "ts_canon_us": ts_us,
        "ts_exchange_s": None,
        "bot_id": "b1",
        "payload": {
            "symbol": "BTC",
            "side": "buy",
            "size": 1.0,
            "status": "filled",
            "timestamp": 1.0,
            "order_id": "o1",
            "client_order_id": "c1",
        },
    }

    async def run_once():
        await consumer._handle_message({"data": json.dumps(event)})

    asyncio.run(run_once())
    assert len(manager.calls) == 1
    assert timescale.writes


def test_order_update_consumer_skips_duplicates():
    store = InMemoryOrderStore()

    async def seed_store():
        await store.record(
            symbol="BTC",
            side="buy",
            size=1.0,
            status="filled",
            order_id="o1",
            client_order_id="c1",
        )

    asyncio.run(seed_store())
    manager = FakeExecutionManager(order_store=store)
    consumer = OrderUpdateConsumer(RedisStreamsClient(FakeRedis()), manager)
    ts_us = 1_000_000
    event = {
        "event_id": "evt-2",
        "event_type": "order_update",
        "schema_version": "v1",
        "timestamp": "1",
        "ts_recv_us": ts_us,
        "ts_canon_us": ts_us,
        "ts_exchange_s": None,
        "bot_id": "b1",
        "payload": {
            "symbol": "BTC",
            "side": "buy",
            "size": 1.0,
            "status": "filled",
            "timestamp": 1.0,
            "order_id": "o1",
            "client_order_id": "c1",
        },
    }

    async def run_once():
        await consumer._handle_message({"data": json.dumps(event)})

    asyncio.run(run_once())
    assert manager.calls == []


def test_order_update_consumer_heals_duplicate_terminal_intent():
    store = InMemoryOrderStore()
    recorded_intents = []
    original_record_intent = store.record_intent

    async def capture_record_intent(**kwargs):
        recorded_intents.append(dict(kwargs))
        await original_record_intent(**kwargs)

    store.record_intent = capture_record_intent

    async def seed_store():
        await store.record(
            symbol="BTC",
            side="buy",
            size=1.0,
            status="canceled",
            order_id="o1",
            client_order_id="c1",
        )
        await store.record_intent(
            intent_id="i1",
            symbol="BTC",
            side="buy",
            size=1.0,
            client_order_id="c1",
            status="pending",
        )

    asyncio.run(seed_store())
    manager = FakeExecutionManager(order_store=store)
    consumer = OrderUpdateConsumer(RedisStreamsClient(FakeRedis()), manager)
    ts_us = 1_000_000
    event = {
        "event_id": "evt-dup-heal",
        "event_type": "order_update",
        "schema_version": "v1",
        "timestamp": "1",
        "ts_recv_us": ts_us,
        "ts_canon_us": ts_us,
        "ts_exchange_s": None,
        "bot_id": "b1",
        "payload": {
            "symbol": "BTC",
            "side": "buy",
            "size": 1.0,
            "status": "canceled",
            "timestamp": 1.0,
            "order_id": "o1",
            "client_order_id": "c1",
            "close_reason": "position_close",
        },
    }

    async def run_once():
        await consumer._handle_message({"data": json.dumps(event)})

    asyncio.run(run_once())
    assert manager.calls == []
    assert recorded_intents[-1]["client_order_id"] == "c1"
    assert recorded_intents[-1]["status"] == "canceled"
    assert recorded_intents[-1]["last_error"] == "position_close"


def test_order_update_consumer_prefers_store_size():
    store = InMemoryOrderStore()

    async def seed_store():
        await store.record(
            symbol="BTC",
            side="buy",
            size=2.0,
            status="open",
            order_id="o2",
            client_order_id="c2",
        )

    asyncio.run(seed_store())
    manager = FakeExecutionManager(order_store=store)
    consumer = OrderUpdateConsumer(RedisStreamsClient(FakeRedis()), manager)
    ts_us = 1_000_000
    event = {
        "event_id": "evt-3",
        "event_type": "order_update",
        "schema_version": "v1",
        "timestamp": "1",
        "ts_recv_us": ts_us,
        "ts_canon_us": ts_us,
        "ts_exchange_s": None,
        "bot_id": "b1",
        "payload": {
            "symbol": "BTC",
            "side": "buy",
            "size": 0.5,
            "status": "filled",
            "timestamp": 1.0,
            "order_id": "o2",
            "client_order_id": "c2",
        },
    }

    async def run_once():
        await consumer._handle_message({"data": json.dumps(event)})

    asyncio.run(run_once())
    assert len(manager.calls) == 1
    intent, _status = manager.calls[0]
    assert intent.size == 2.0
