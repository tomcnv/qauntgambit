import asyncio
from types import SimpleNamespace

from quantgambit.runtime.app import Runtime, RuntimeConfig


class FakeExchangeClient:
    async def fetch_executions(self, symbol: str, since_ms: int, limit: int):
        return [
            {
                "order": "o-1",
                "clientOrderId": "c-1",
                "symbol": symbol,
                "side": "buy",
                "price": 100.0,
                "amount": 2.0,
                "timestamp": since_ms + 1,
                "fee": {"cost": 0.5},
            }
        ]


class FakeOrderStore:
    def __init__(self):
        self.records = []
        self.intents = []

    async def record(self, **kwargs):
        self.records.append(dict(kwargs))

    async def record_intent(self, **kwargs):
        self.intents.append(dict(kwargs))


def test_sync_exchange_executions_mirrors_terminal_intent():
    runtime = Runtime.__new__(Runtime)
    runtime.config = RuntimeConfig(
        tenant_id="t1",
        bot_id="b1",
        exchange="bybit",
        trading_mode="live",
    )
    runtime.order_store = FakeOrderStore()
    runtime._timescale_pool = None

    async def fake_upsert_execution_ledger_rows(trades):
        return 0

    async def fake_fetch_latest_order_summaries(order_ids):
        return {}

    runtime._upsert_execution_ledger_rows = fake_upsert_execution_ledger_rows
    runtime._fetch_latest_order_summaries = fake_fetch_latest_order_summaries
    runtime._should_upsert_exchange_sync = lambda agg, existing: True

    runtime.execution_manager = SimpleNamespace(exchange_client=FakeExchangeClient())

    result = asyncio.run(runtime._sync_executions_once(["SOLUSDT"], 0, 200))

    assert result["synced"] == 1
    assert len(runtime.order_store.records) == 1
    assert len(runtime.order_store.intents) == 1
    assert runtime.order_store.intents[0]["client_order_id"] == "c-1"
    assert runtime.order_store.intents[0]["status"] == "filled"
    assert runtime.order_store.intents[0]["last_error"] == "exchange_sync"
