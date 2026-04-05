import asyncio
import os
from datetime import datetime, timedelta, timezone

from quantgambit.execution.order_store import InMemoryOrderStore
from quantgambit.execution.order_statuses import is_open_status
from quantgambit.runtime.app import Runtime, RuntimeConfig


class FakeWorker:
    async def run(self):
        # Return immediately instead of infinite loop
        await asyncio.sleep(0)
        return None

    async def start(self):
        await asyncio.sleep(0)
        return None


class FakeRiskOverrideStore:
    async def load(self):
        return None

    async def prune_expired(self):
        return None


class FakePostgres:
    def __init__(self, base_time: datetime):
        self.base_time = base_time

    async def write_order_status(self, record):
        return None

    async def write_order_event(self, record):
        return None

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
            }
        ]

    async def load_pending_intents(self, tenant_id, bot_id):
        return []


class FakeReconciler:
    def __init__(self):
        self.reconcile_calls = 0

    async def reconcile_once(self):
        self.reconcile_calls += 1
        return None

    async def run(self):
        return None


class FakeReferencePriceCache:
    """Fake reference price cache for tests."""
    
    def __len__(self):
        return 0


def test_runtime_replays_postgres_orders_on_startup():
    base_time = datetime.now(timezone.utc)
    postgres_store = FakePostgres(base_time)
    order_store = InMemoryOrderStore(tenant_id="t1", bot_id="b1", postgres_store=postgres_store)

    runtime = Runtime.__new__(Runtime)
    runtime.config = RuntimeConfig(tenant_id="t1", bot_id="b1", exchange="okx")
    runtime.risk_override_store = FakeRiskOverrideStore()
    runtime.config_store = None
    runtime.config_repository = None
    runtime.telemetry = None
    runtime.telemetry_context = None
    runtime.timescale_reader = None
    runtime.state_manager = None
    runtime.order_store = order_store
    runtime.order_reconciler = FakeReconciler()
    runtime.market_worker = None
    runtime.trade_feed_worker = None
    runtime.trade_worker = None
    runtime.orderbook_feed_worker = None
    runtime.order_update_worker = None
    runtime.candle_worker = None
    runtime.trade_enabled = False
    runtime.reference_prices = FakeReferencePriceCache()
    runtime.quant = None
    runtime.quant_integration_enabled = False
    runtime.execution_manager = None
    runtime._kill_switch = None
    runtime.positions_snapshot_interval = 5.0
    # Runtime is constructed via __new__; set defaults normally initialized in __init__.
    runtime.exchange_positions_sync_interval = 0.0
    runtime._state_snapshot_enabled = False
    runtime.warm_start_loader = None

    runtime.command_consumer = FakeWorker()
    runtime.control_manager = FakeWorker()
    runtime.config_watcher = FakeWorker()
    runtime.orderbook_worker = FakeWorker()
    runtime.feature_worker = FakeWorker()
    runtime.decision_worker = FakeWorker()
    runtime.risk_worker = FakeWorker()
    runtime.execution_worker = FakeWorker()
    runtime.position_guard_worker = FakeWorker()
    runtime.order_update_consumer = FakeWorker()
    runtime.health_worker = FakeWorker()

    async def _noop_loop():
        # Return immediately instead of infinite loop
        await asyncio.sleep(0)
        return None

    runtime._config_flush_loop = _noop_loop
    runtime._override_cleanup_loop = _noop_loop
    runtime._positions_snapshot_loop = _noop_loop
    runtime._equity_refresh_loop = _noop_loop
    runtime._intent_expiry_loop = _noop_loop

    old_hours = os.environ.get("ORDER_EVENT_REPLAY_HOURS")
    old_limit = os.environ.get("ORDER_EVENT_REPLAY_LIMIT")
    os.environ["ORDER_EVENT_REPLAY_HOURS"] = "6"
    os.environ["ORDER_EVENT_REPLAY_LIMIT"] = "25"

    # Patch asyncio.gather to return immediately after a short delay
    original_gather = asyncio.gather
    
    async def mock_gather(*tasks, return_exceptions=False):
        # Start all tasks
        task_objects = [asyncio.create_task(task) for task in tasks]
        # Give initialization time to complete
        await asyncio.sleep(0.1)
        # Cancel all tasks that are still running
        for task in task_objects:
            if not task.done():
                task.cancel()
        # Wait for cancellations to complete
        results = []
        for task in task_objects:
            try:
                result = await task
                results.append(result)
            except asyncio.CancelledError:
                results.append(None)
            except Exception as e:
                if return_exceptions:
                    results.append(e)
                else:
                    raise
        return results

    async def run_once():
        # Patch asyncio.gather in the runtime module's namespace
        import quantgambit.runtime.app as runtime_module
        original_gather_module = runtime_module.asyncio.gather
        runtime_module.asyncio.gather = mock_gather
        try:
            await runtime.start()
        finally:
            runtime_module.asyncio.gather = original_gather_module

    asyncio.run(run_once())
    record = runtime.order_store.get("o1")
    assert record is not None
    assert is_open_status(record.status)
    assert runtime.order_reconciler.reconcile_calls == 1

    if old_hours is None:
        os.environ.pop("ORDER_EVENT_REPLAY_HOURS", None)
    else:
        os.environ["ORDER_EVENT_REPLAY_HOURS"] = old_hours
    if old_limit is None:
        os.environ.pop("ORDER_EVENT_REPLAY_LIMIT", None)
    else:
        os.environ["ORDER_EVENT_REPLAY_LIMIT"] = old_limit
