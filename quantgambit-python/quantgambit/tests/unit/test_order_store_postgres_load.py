import asyncio

from quantgambit.execution.order_store import InMemoryOrderStore


class FakePostgres:
    def __init__(self):
        self.loaded = False

    async def load_latest(self, tenant_id: str, bot_id: str):
        self.loaded = True
        return [
            {
                "symbol": "BTC",
                "side": "buy",
                "size": 1.0,
                "status": "filled",
                "order_id": "o1",
                "client_order_id": "c1",
            }
        ]

    async def write_order_status(self, record):
        return None

    async def write_order_event(self, record):
        return None


def test_order_store_loads_from_postgres():
    store = InMemoryOrderStore(tenant_id="t1", bot_id="b1", postgres_store=FakePostgres())

    async def run_once():
        await store.load()

    asyncio.run(run_once())
    record = store.get("o1")
    assert record is not None
