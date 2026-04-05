import asyncio
import json
from pathlib import Path

from quantgambit.execution.order_updates_ws import _parse_bybit_order_update
from quantgambit.execution.order_update_consumer import OrderUpdateConsumer
from quantgambit.ingest.order_update_worker import OrderUpdateWorker
from quantgambit.execution.order_store import InMemoryOrderStore
from quantgambit.execution.manager import ExecutionIntent, OrderStatus
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


class FixtureProvider:
    def __init__(self, update):
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


def test_order_updates_ws_bybit_flow():
    fixture_path = Path(__file__).resolve().parent.parent / "fixtures" / "order_updates" / "bybit_order_filled.json"
    message = json.loads(fixture_path.read_text())
    update = _parse_bybit_order_update(message)
    assert update is not None

    redis = FakeRedis()
    redis_client = RedisStreamsClient(redis)
    worker = OrderUpdateWorker(
        provider=FixtureProvider(update),
        redis_client=redis_client,
        bot_id="b1",
        exchange="bybit",
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
    record = order_store.get("bybit-123", "cid-bybit-1")
    assert record is not None
    assert record.status == "filled"
