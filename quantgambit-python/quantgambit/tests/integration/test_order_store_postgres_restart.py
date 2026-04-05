from datetime import datetime, timezone
import asyncio

from quantgambit.execution.order_store import InMemoryOrderStore


class FakePostgres:
    def __init__(self):
        self.order_states: dict[str, dict] = {}
        self.order_events: list[dict] = []

    async def write_order_status(self, record):
        key = record.order_id or record.client_order_id
        if not key:
            return
        self.order_states[key] = {
            "symbol": record.symbol,
            "side": record.side,
            "size": record.size,
            "status": record.status,
            "order_id": record.order_id,
            "client_order_id": record.client_order_id,
            "filled_size": record.filled_size,
            "remaining_size": record.remaining_size,
        }

    async def write_order_event(self, record):
        created_at = _parse_datetime(record.created_at) or datetime.now(timezone.utc)
        self.order_events.append(
            {
                "exchange": record.exchange,
                "symbol": record.symbol,
                "side": record.side,
                "size": record.size,
                "status": record.status,
                "event_type": record.event_type,
                "order_id": record.order_id,
                "client_order_id": record.client_order_id,
                "reason": record.reason,
                "fill_price": record.fill_price,
                "fee_usd": record.fee_usd,
                "filled_size": record.filled_size,
                "remaining_size": record.remaining_size,
                "state_source": record.state_source,
                "raw_exchange_status": record.raw_exchange_status,
                "created_at": created_at,
            }
        )

    async def load_latest(self, tenant_id, bot_id):
        return list(self.order_states.values())

    async def load_order_events(self, tenant_id, bot_id, since, limit):
        events = list(self.order_events)
        if since is not None:
            events = [event for event in events if event["created_at"] >= since]
        events.sort(key=lambda event: event["created_at"])
        if limit is not None and limit > 0:
            events = events[:limit]
        return events


def test_order_store_replays_after_restart():
    postgres = FakePostgres()
    store = InMemoryOrderStore(tenant_id="t1", bot_id="b1", postgres_store=postgres)

    async def seed_events():
        await store.record(
            symbol="BTC",
            side="buy",
            size=1.0,
            status="open",
            order_id="o1",
            client_order_id="c1",
            source="ws",
            exchange="okx",
            raw_exchange_status="open",
            event_type="open",
        )
        await store.record(
            symbol="BTC",
            side="buy",
            size=1.0,
            status="filled",
            order_id="o1",
            client_order_id="c1",
            source="ws",
            exchange="okx",
            raw_exchange_status="filled",
            event_type="filled",
            filled_size=1.0,
            remaining_size=0.0,
            fill_price=30000.0,
            fee_usd=0.1,
        )

    asyncio.run(seed_events())

    restart_store = InMemoryOrderStore(tenant_id="t1", bot_id="b1", postgres_store=postgres)

    async def replay_after_restart():
        await restart_store.load()
        replayed = await restart_store.replay_recent_events(hours=1, limit=10)
        return replayed

    replayed = asyncio.run(replay_after_restart())
    assert replayed == 2
    record = restart_store.get("o1")
    assert record is not None
    assert record.status == "filled"
    assert len(record.history) == 2
    assert record.history[0].status == "open"
    assert record.history[1].status == "filled"


def _parse_datetime(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None
