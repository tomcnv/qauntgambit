import asyncio
import time
from datetime import datetime, timezone

from quantgambit.execution.order_store import InMemoryOrderStore
from quantgambit.storage.redis_snapshots import RedisSnapshotWriter, RedisSnapshotReader


def test_order_store_records_history():
    store = InMemoryOrderStore()

    async def run_once():
        await store.record(
            symbol="BTC",
            side="buy",
            size=1.0,
            status="pending",
            order_id="o1",
            client_order_id="c1",
        )
        await store.record(
            symbol="BTC",
            side="buy",
            size=1.0,
            status="filled",
            order_id="o1",
            client_order_id="c1",
        )

    asyncio.run(run_once())
    record = store.get("o1")
    assert record is not None
    assert record.status == "filled"
    assert len(record.history) == 2


def test_order_store_persists_status_with_client_order_id():
    class FakePostgres:
        def __init__(self):
            self.status_calls = 0
            self.event_calls = 0

        async def write_order_status(self, record):
            self.status_calls += 1

        async def write_order_event(self, record):
            self.event_calls += 1

        async def load_latest(self, tenant_id, bot_id):
            return []

    store = InMemoryOrderStore(
        tenant_id="t1",
        bot_id="b1",
        postgres_store=FakePostgres(),
    )

    async def run_once():
        await store.record(
            symbol="BTC",
            side="buy",
            size=1.0,
            status="rejected",
            order_id=None,
            client_order_id="c1",
        )

    asyncio.run(run_once())
    assert store._postgres_store.status_calls == 1
    assert store._postgres_store.event_calls == 1


def test_order_store_loads_from_snapshot_history():
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

    redis = FakeRedis()
    history_key = "quantgambit:t1:b1:orders:history"
    writer = RedisSnapshotWriter(redis)
    reader = RedisSnapshotReader(redis)
    store = InMemoryOrderStore(
        snapshot_writer=writer,
        snapshot_reader=reader,
        snapshot_history_key=history_key,
        tenant_id="t1",
        bot_id="b1",
    )

    async def seed_and_load():
        await store.record(
            symbol="BTC",
            side="buy",
            size=1.0,
            status="open",
            client_order_id="c1",
        )
        new_store = InMemoryOrderStore(
            snapshot_reader=reader,
            snapshot_history_key=history_key,
            tenant_id="t1",
            bot_id="b1",
        )
        await new_store.load()
        return new_store

    new_store = asyncio.run(seed_and_load())
    record = new_store.get(None, "c1")
    assert record is not None
    assert record.history
    assert record.history[0].status == "open"


def test_order_store_skips_stale_updates():
    store = InMemoryOrderStore()

    async def run_once():
        await store.record(
            symbol="BTC",
            side="buy",
            size=1.0,
            status="open",
            order_id="o1",
            timestamp=10.0,
        )
        await store.record(
            symbol="BTC",
            side="buy",
            size=1.0,
            status="filled",
            order_id="o1",
            timestamp=5.0,
        )

    asyncio.run(run_once())
    record = store.get("o1")
    assert record is not None
    assert record.status == "open"
    assert len(record.history) == 1


def test_order_store_records_error():
    class FakePostgres:
        def __init__(self):
            self.errors = []

        async def write_order_status(self, record):
            return None

        async def write_order_event(self, record):
            return None

        async def write_order_intent(self, record):
            return None

        async def load_latest(self, tenant_id, bot_id):
            return []

        async def write_order_error(self, record):
            self.errors.append(record)

    store = InMemoryOrderStore(tenant_id="t1", bot_id="b1", postgres_store=FakePostgres())

    async def run_once():
        await store.record_error(stage="execute", error_message="boom", symbol="BTC", client_order_id="c1")

    asyncio.run(run_once())
    assert store._postgres_store.errors


def test_order_store_replays_events_without_persisting():
    class FakePostgres:
        def __init__(self):
            self.status_calls = 0
            self.event_calls = 0

        async def write_order_status(self, record):
            self.status_calls += 1

        async def write_order_event(self, record):
            self.event_calls += 1

        async def load_latest(self, tenant_id, bot_id):
            return []

        async def load_order_events(self, tenant_id, bot_id, since, limit):
            return [
                {
                    "exchange": "okx",
                    "symbol": "BTC",
                    "side": "buy",
                    "size": 1.0,
                    "status": "open",
                    "event_type": "open",
                    "order_id": "o1",
                    "client_order_id": "c1",
                    "reason": None,
                    "fill_price": None,
                    "fee_usd": None,
                    "filled_size": 0.0,
                    "remaining_size": 1.0,
                    "state_source": "ws",
                    "raw_exchange_status": "open",
                    "created_at": datetime.now(timezone.utc),
                }
            ]

    store = InMemoryOrderStore(tenant_id="t1", bot_id="b1", postgres_store=FakePostgres())

    async def run_once():
        return await store.replay_recent_events(hours=1, limit=10)

    replayed = asyncio.run(run_once())
    assert replayed == 1
    record = store.get("o1")
    assert record is not None
    assert record.status == "open"
    assert store._postgres_store.status_calls == 0
    assert store._postgres_store.event_calls == 0


def test_order_store_recovers_pending_intents_from_snapshots():
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

    redis = FakeRedis()
    writer = RedisSnapshotWriter(redis)
    reader = RedisSnapshotReader(redis)
    store = InMemoryOrderStore(snapshot_writer=writer, snapshot_reader=reader, tenant_id="t1", bot_id="b1")

    async def seed_and_load():
        await store.record_intent(
            intent_id="i1",
            symbol="BTC",
            side="buy",
            size=1.0,
            client_order_id="c1",
            status="created",
        )
        await store.record_intent(
            intent_id="i1",
            symbol="BTC",
            side="buy",
            size=1.0,
            client_order_id="c1",
            status="open",
        )
        await store.record_intent(
            intent_id="i2",
            symbol="ETH",
            side="sell",
            size=2.0,
            client_order_id="c2",
            status="filled",
        )
        new_store = InMemoryOrderStore(snapshot_reader=reader, tenant_id="t1", bot_id="b1")
        return await new_store.load_pending_intents()

    pending = asyncio.run(seed_and_load())
    assert len(pending) == 1
    assert pending[0]["client_order_id"] == "c1"
    assert pending[0]["status"] == "open"


def test_order_store_respects_intent_age_guardrail():
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

    redis = FakeRedis()
    writer = RedisSnapshotWriter(redis)
    reader = RedisSnapshotReader(redis)
    store = InMemoryOrderStore(
        snapshot_writer=writer,
        snapshot_reader=reader,
        tenant_id="t1",
        bot_id="b1",
        max_intent_age_sec=10.0,
    )

    async def seed_and_load():
        now = time.time()
        await writer.append_history(
            store._intent_history_key,
            {
                "intent_id": "old",
                "client_order_id": "old",
                "symbol": "BTC",
                "side": "buy",
                "size": 1.0,
                "status": "open",
                "timestamp": now - 100.0,
            },
        )
        await writer.append_history(
            store._intent_history_key,
            {
                "intent_id": "new",
                "client_order_id": "new",
                "symbol": "ETH",
                "side": "sell",
                "size": 2.0,
                "status": "open",
                "timestamp": now - 1.0,
            },
        )
        return await store.load_pending_intents()

    pending = asyncio.run(seed_and_load())
    assert len(pending) == 1
    assert pending[0]["client_order_id"] == "new"
