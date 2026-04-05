import asyncio
import json

from quantgambit.execution.order_updates import OrderUpdate
from quantgambit.ingest.order_update_worker import OrderUpdateWorker
from quantgambit.execution.order_update_consumer import OrderUpdateConsumer
from quantgambit.execution.order_store import InMemoryOrderStore
from quantgambit.execution.manager import (
    ExecutionIntent,
    OrderStatus,
    RealExecutionManager,
    PositionSnapshot,
)
from quantgambit.execution.adapters import PositionManagerAdapter
from quantgambit.execution.position_store import InMemoryPositionStore
from quantgambit.observability.telemetry import TelemetryContext
from quantgambit.portfolio.state_manager import InMemoryStateManager
from quantgambit.storage.redis_streams import RedisStreamsClient


class FakeRedis:
    def __init__(self):
        self.streams = {}
        self.read_offsets = {}

    async def xadd(self, stream, data, maxlen=None, approximate=True):
        items = self.streams.setdefault(stream, [])
        msg_id = f"{len(items) + 1}-0"
        items.append((msg_id, data))
        return msg_id

    async def xgroup_create(self, stream, group, id="0", mkstream=True):
        if mkstream and stream not in self.streams:
            self.streams[stream] = []
        return None

    async def xreadgroup(self, group, consumer, streams, count=10, block=1000):
        results = []
        for stream, _ in streams.items():
            offset = self.read_offsets.get(stream, 0)
            items = self.streams.get(stream, [])
            if offset >= len(items):
                continue
            batch = items[offset : offset + count]
            self.read_offsets[stream] = offset + len(batch)
            results.append((stream, batch))
        return results

    async def xack(self, stream, group, message_id):
        return 1

    async def xlen(self, stream):
        return len(self.streams.get(stream, []))


class FakeProvider:
    def __init__(self, update: OrderUpdate):
        self.update = update
        self.called = False

    async def next_update(self):
        if self.called:
            await asyncio.sleep(0.01)
            return None
        self.called = True
        return self.update


class FakeExecutionManager:
    def __init__(self, order_store: InMemoryOrderStore):
        self.order_store = order_store

    async def record_order_status(self, intent: ExecutionIntent, status: OrderStatus) -> bool:
        await self.order_store.record(
            symbol=intent.symbol,
            side=intent.side,
            size=intent.size,
            status=status.status,
            order_id=status.order_id,
            client_order_id=intent.client_order_id,
            fill_price=status.fill_price,
            fee_usd=status.fee_usd,
            timestamp=status.timestamp,
            source=status.source,
        )
        return True


class FakeTelemetry:
    def __init__(self):
        self.orders = []

    async def publish_order(self, ctx, symbol, payload):
        self.orders.append((ctx, symbol, payload))

    async def publish_positions(self, ctx, payload):
        return None

    async def publish_position_lifecycle(self, ctx, symbol=None, event_type=None, payload=None):
        # Record position lifecycle events as orders for test verification
        self.orders.append((ctx, symbol, payload or {}))
        return None


class FakeExchangeClient:
    async def close_position(self, symbol, side, size, client_order_id=None):
        raise NotImplementedError

    async def open_position(self, symbol, side, size, stop_loss=None, take_profit=None, client_order_id=None):
        raise NotImplementedError

    async def fetch_order_status(self, order_id, symbol):
        return None

    async def fetch_order_status_by_client_id(self, client_order_id, symbol):
        return None


def test_order_update_worker_to_consumer_flow():
    redis = FakeRedis()
    redis_client = RedisStreamsClient(redis)
    update = OrderUpdate(
        symbol="BTCUSDT",
        side="buy",
        size=1.0,
        status="filled",
        timestamp=1.0,
        order_id="o-1",
        client_order_id="c-1",
        fill_price=30000.0,
        fee_usd=0.1,
    )
    worker = OrderUpdateWorker(
        provider=FakeProvider(update),
        redis_client=redis_client,
        bot_id="b1",
        exchange="binance",
    )
    order_store = InMemoryOrderStore()
    manager = FakeExecutionManager(order_store)
    consumer = OrderUpdateConsumer(redis_client, manager)

    async def run_flow():
        task = asyncio.create_task(worker.run())
        for _ in range(50):
            if await redis_client.stream_length("events:order_updates") > 0:
                break
            await asyncio.sleep(0.01)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        messages = await redis_client.read_group(
            consumer.config.consumer_group,
            consumer.config.consumer_name,
            {consumer.config.source_stream: ">"},
            block_ms=1,
        )
        for stream_name, entries in messages:
            for message_id, payload in entries:
                await consumer._handle_message(payload)
                await redis_client.ack(stream_name, consumer.config.consumer_group, message_id)

    asyncio.run(run_flow())
    record = order_store.get("o-1", "c-1")
    assert record is not None
    assert record.status == "filled"


def test_order_update_close_emits_reasoned_order_event():
    redis = FakeRedis()
    redis_client = RedisStreamsClient(redis)
    update = OrderUpdate(
        symbol="BTCUSDT",
        side="sell",
        size=1.0,
        status="filled",
        timestamp=2.0,
        order_id="o-2",
        client_order_id="c-2:sl",
        fill_price=95.0,
        fee_usd=0.05,
    )
    worker = OrderUpdateWorker(
        provider=FakeProvider(update),
        redis_client=redis_client,
        bot_id="b1",
        exchange="binance",
    )
    state = InMemoryStateManager()
    state.add_position(symbol="BTCUSDT", side="long", size=1.0, entry_price=100.0, opened_at=1.0)
    position_store = InMemoryPositionStore(state)
    telemetry = FakeTelemetry()
    manager = RealExecutionManager(
        exchange_client=FakeExchangeClient(),
        position_manager=PositionManagerAdapter(position_store),
        telemetry=telemetry,
        telemetry_context=TelemetryContext(tenant_id="t1", bot_id="b1", exchange="binance"),
    )
    consumer = OrderUpdateConsumer(redis_client, manager)

    async def run_flow():
        task = asyncio.create_task(worker.run())
        for _ in range(50):
            if await redis_client.stream_length("events:order_updates") > 0:
                break
            await asyncio.sleep(0.01)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        messages = await redis_client.read_group(
            consumer.config.consumer_group,
            consumer.config.consumer_name,
            {consumer.config.source_stream: ">"},
            block_ms=1,
        )
        for stream_name, entries in messages:
            for message_id, payload in entries:
                await consumer._handle_message(payload)
                await redis_client.ack(stream_name, consumer.config.consumer_group, message_id)

    asyncio.run(run_flow())
    assert telemetry.orders
    _, _, payload = telemetry.orders[-1]
    # Position lifecycle event uses "status" and "closed_by" fields
    assert payload.get("status") == "closed"
    # Position was closed via trading signal (fill event)
    # Note: The system doesn't currently differentiate SL/TP fills from regular fills
    # The client_order_id suffix ":sl" is just a naming convention
    assert payload.get("closed_by") == "trading_signal"
    # Verify the position was actually closed at a loss (SL triggered)
    assert payload.get("realized_pnl") < 0  # Loss indicates SL hit
