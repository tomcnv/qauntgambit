from datetime import datetime, timedelta, timezone

import asyncio

from quantgambit.execution.order_store import InMemoryOrderStore


class FakePostgres:
    def __init__(self, base_time: datetime):
        self.base_time = base_time
        self.status_calls = 0
        self.event_calls = 0

    async def write_order_status(self, record):
        self.status_calls += 1

    async def write_order_event(self, record):
        self.event_calls += 1

    async def load_latest(self, tenant_id, bot_id):
        return [
            {
                "symbol": "BTC",
                "side": "buy",
                "size": 1.0,
                "status": "open",
                "order_id": "o1",
                "client_order_id": "c1",
                "filled_size": 0.0,
                "remaining_size": 1.0,
            }
        ]

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
                "created_at": self.base_time,
            },
            {
                "exchange": "okx",
                "symbol": "BTC",
                "side": "buy",
                "size": 1.0,
                "status": "filled",
                "event_type": "filled",
                "order_id": "o1",
                "client_order_id": "c1",
                "reason": "execution_update",
                "fill_price": 30000.0,
                "fee_usd": 0.1,
                "filled_size": 1.0,
                "remaining_size": 0.0,
                "state_source": "ws",
                "raw_exchange_status": "filled",
                "created_at": self.base_time + timedelta(seconds=5),
            },
        ]


def test_order_store_replays_postgres_events_after_load():
    base_time = datetime.now(timezone.utc)
    store = InMemoryOrderStore(tenant_id="t1", bot_id="b1", postgres_store=FakePostgres(base_time))

    async def run_once():
        await store.load()
        replayed = await store.replay_recent_events(hours=1, limit=10)
        return replayed

    replayed = asyncio.run(run_once())
    assert replayed == 2
    record = store.get("o1")
    assert record is not None
    assert record.status == "filled"
    assert len(record.history) == 2
    assert record.history[0].status == "open"
    assert record.history[1].status == "filled"
    assert store._postgres_store.status_calls == 0
    assert store._postgres_store.event_calls == 0
