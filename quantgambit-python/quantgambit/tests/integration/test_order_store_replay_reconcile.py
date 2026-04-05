import asyncio
from datetime import datetime, timezone

from quantgambit.execution.manager import ExecutionIntent, OrderStatus
from quantgambit.execution.order_reconciler_worker import OrderReconcilerWorker
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

    async def load_intent_by_client_order_id(self, tenant_id, bot_id, client_order_id):
        # Optional in reconciliation; return None when intent metadata is not persisted.
        return None


class FakeExecutionManager:
    def __init__(self, order_store: InMemoryOrderStore, status: OrderStatus):
        self.order_store = order_store
        self._status = status

    async def poll_order_status(self, order_id, symbol):
        return self._status

    async def poll_order_status_by_client_id(self, client_order_id, symbol):
        return self._status

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
            filled_size=status.filled_size,
            remaining_size=status.remaining_size,
            source=status.source,
            exchange="binance",
            raw_exchange_status=status.status,
            event_type=status.status,
        )
        return True


def test_order_store_replay_and_reconcile_updates_postgres():
    postgres = FakePostgres()
    store = InMemoryOrderStore(tenant_id="t1", bot_id="b1", postgres_store=postgres)

    async def seed_open_order():
        await store.record(
            symbol="BTCUSDT",
            side="buy",
            size=1.0,
            status="open",
            order_id="o1",
            client_order_id="c1",
            source="ws",
            exchange="binance",
            raw_exchange_status="open",
            event_type="open",
        )

    asyncio.run(seed_open_order())
    assert postgres.order_states["o1"]["status"] == "open"

    restart_store = InMemoryOrderStore(tenant_id="t1", bot_id="b1", postgres_store=postgres)

    async def replay_and_reconcile():
        await restart_store.load()
        await restart_store.replay_recent_events(hours=1, limit=10)
        status = OrderStatus(
            order_id="o1",
            status="filled",
            fill_price=100.0,
            fee_usd=0.1,
            filled_size=1.0,
            remaining_size=0.0,
            source="rest",
        )
        executor = FakeExecutionManager(restart_store, status)
        reconciler = OrderReconcilerWorker(executor, restart_store)
        await reconciler.reconcile_once()

    asyncio.run(replay_and_reconcile())
    record = restart_store.get("o1")
    assert record is not None
    assert record.status == "filled"
    assert postgres.order_states["o1"]["status"] == "filled"
    assert len(postgres.order_events) >= 2


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
