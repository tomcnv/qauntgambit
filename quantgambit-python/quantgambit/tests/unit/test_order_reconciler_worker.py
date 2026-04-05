import asyncio
import time

from quantgambit.execution.manager import ExecutionIntent, OrderStatus
from quantgambit.observability.telemetry import TelemetryContext
from quantgambit.execution.order_reconciler_worker import (
    OrderReconcilerConfig,
    OrderReconcilerWorker,
    _exchange_limit,
)
from quantgambit.execution.order_store import InMemoryOrderStore


class FakeExecutionManager:
    def __init__(self, status):
        self.status = status
        self.calls = []

    async def poll_order_status(self, order_id, symbol):
        return self.status

    async def poll_order_status_by_client_id(self, client_order_id, symbol):
        return self.status

    async def record_order_status(self, intent: ExecutionIntent, status: OrderStatus):
        self.calls.append((intent, status))
        return True


class FakeTelemetry:
    def __init__(self):
        self.guardrails = []

    async def publish_guardrail(self, ctx, payload):
        self.guardrails.append(payload)


def test_reconciler_updates_on_status_drift():
    store = InMemoryOrderStore()

    async def seed():
        await store.record(
            symbol="BTC",
            side="buy",
            size=1.0,
            status="open",
            order_id="o1",
            client_order_id="c1",
        )

    asyncio.run(seed())
    manager = FakeExecutionManager(OrderStatus(order_id="o1", status="filled"))
    telemetry = FakeTelemetry()
    ctx = TelemetryContext(tenant_id="t1", bot_id="b1", exchange="okx")
    reconciler = OrderReconcilerWorker(manager, store, telemetry=telemetry, telemetry_context=ctx)

    async def run_once():
        await reconciler._reconcile_once()

    asyncio.run(run_once())
    assert len(manager.calls) == 1
    payload = next(item for item in telemetry.guardrails if item.get("type") == "order_reconcile_rest_poll")
    assert payload.get("reason") == "ws_gap_rest_poll"


def test_reconciler_skips_when_no_drift():
    store = InMemoryOrderStore()

    async def seed():
        await store.record(
            symbol="BTC",
            side="buy",
            size=1.0,
            status="open",
            order_id="o1",
        )

    asyncio.run(seed())
    manager = FakeExecutionManager(OrderStatus(order_id="o1", status="open"))
    telemetry = FakeTelemetry()
    ctx = TelemetryContext(tenant_id="t1", bot_id="b1", exchange="okx")
    reconciler = OrderReconcilerWorker(manager, store, telemetry=telemetry, telemetry_context=ctx)

    async def run_once():
        await reconciler._reconcile_once()

    asyncio.run(run_once())
    assert manager.calls == []
    payload = next(item for item in telemetry.guardrails if item.get("type") == "order_reconcile_rest_poll")
    assert payload.get("reason") == "ws_gap_rest_poll"


def test_reconciler_uses_client_order_id_when_missing_order_id():
    store = InMemoryOrderStore()

    async def seed():
        await store.record(
            symbol="BTC",
            side="buy",
            size=1.0,
            status="open",
            client_order_id="c1",
        )

    asyncio.run(seed())
    manager = FakeExecutionManager(OrderStatus(order_id="c1", status="filled"))
    telemetry = FakeTelemetry()
    ctx = TelemetryContext(tenant_id="t1", bot_id="b1", exchange="okx")
    reconciler = OrderReconcilerWorker(manager, store, telemetry=telemetry, telemetry_context=ctx)

    async def run_once():
        await reconciler._reconcile_once()

    asyncio.run(run_once())
    assert len(manager.calls) == 1
    payload = next(item for item in telemetry.guardrails if item.get("type") == "order_reconcile_rest_poll")
    assert payload.get("reason") == "ws_gap_rest_poll"


def test_reconciler_emits_poll_failed_guardrail():
    store = InMemoryOrderStore()

    async def seed():
        await store.record(
            symbol="BTC",
            side="buy",
            size=1.0,
            status="open",
            order_id="o1",
        )

    asyncio.run(seed())
    manager = FakeExecutionManager(None)
    telemetry = FakeTelemetry()
    ctx = TelemetryContext(tenant_id="t1", bot_id="b1", exchange="okx")
    reconciler = OrderReconcilerWorker(manager, store, telemetry=telemetry, telemetry_context=ctx)

    async def run_once():
        await reconciler._reconcile_once()

    asyncio.run(run_once())
    payload = next(item for item in telemetry.guardrails if item.get("type") == "order_reconcile_poll_failed")
    assert payload.get("reason") == "ws_gap_poll_failed"
    assert payload.get("order_id") == "o1"
    assert payload.get("symbol") == "BTC"
    assert payload.get("source") == "rest"


def test_reconciler_emits_drift_guardrail_payload():
    store = InMemoryOrderStore()

    async def seed():
        await store.record(
            symbol="BTC",
            side="buy",
            size=1.0,
            status="open",
            order_id="o1",
            client_order_id="c1",
        )

    asyncio.run(seed())
    manager = FakeExecutionManager(OrderStatus(order_id="o1", status="filled"))
    telemetry = FakeTelemetry()
    ctx = TelemetryContext(tenant_id="t1", bot_id="b1", exchange="okx")
    reconciler = OrderReconcilerWorker(manager, store, telemetry=telemetry, telemetry_context=ctx)

    asyncio.run(reconciler._reconcile_once())
    payload = next(item for item in telemetry.guardrails if item.get("type") == "order_reconcile_override")
    assert payload["reason"] == "ws_gap_rest_poll"
    assert payload["symbol"] == "BTC"
    assert payload["source"] == "rest"


def test_exchange_limit_caps_by_exchange():
    config = OrderReconcilerConfig(max_orders_per_cycle=100)
    assert _exchange_limit("okx", config) == 40
    assert _exchange_limit("bybit", config) == 30
    assert _exchange_limit("binance", config) == 25
    assert _exchange_limit("unknown", config) == 100


def test_reconciler_throttles_polling_for_stale_open_orders():
    store = InMemoryOrderStore()
    stale_ts = time.time() - 3600.0

    async def seed():
        await store.record(
            symbol="BTC",
            side="buy",
            size=1.0,
            status="open",
            order_id="o1",
            timestamp=stale_ts,
        )

    asyncio.run(seed())
    manager = FakeExecutionManager(None)
    telemetry = FakeTelemetry()
    ctx = TelemetryContext(tenant_id="t1", bot_id="b1", exchange="bybit")
    reconciler = OrderReconcilerWorker(
        manager,
        store,
        telemetry=telemetry,
        telemetry_context=ctx,
        config=OrderReconcilerConfig(interval_sec=2.0, stale_order_poll_sec=120.0),
    )

    asyncio.run(reconciler._reconcile_once())
    assert len([item for item in telemetry.guardrails if item.get("type") == "order_reconcile_rest_poll"]) == 1
    asyncio.run(reconciler._reconcile_once())
    assert len([item for item in telemetry.guardrails if item.get("type") == "order_reconcile_rest_poll"]) == 1


def test_reconciler_keeps_recent_open_orders_hot():
    store = InMemoryOrderStore()
    recent_ts = time.time() - 5.0

    async def seed():
        await store.record(
            symbol="BTC",
            side="buy",
            size=1.0,
            status="open",
            order_id="o1",
            timestamp=recent_ts,
        )

    asyncio.run(seed())
    manager = FakeExecutionManager(None)
    telemetry = FakeTelemetry()
    ctx = TelemetryContext(tenant_id="t1", bot_id="b1", exchange="bybit")
    reconciler = OrderReconcilerWorker(
        manager,
        store,
        telemetry=telemetry,
        telemetry_context=ctx,
        config=OrderReconcilerConfig(interval_sec=2.0, recent_order_poll_sec=2.0, stale_order_poll_sec=120.0),
    )

    asyncio.run(reconciler._reconcile_once())
    rest_polls = [item for item in telemetry.guardrails if item.get("type") == "order_reconcile_rest_poll"]
    assert len(rest_polls) == 1
    reconciler._last_rest_poll_emit.clear()
    reconciler._last_poll_failed_emit.clear()
    reconciler._last_checked_at["o1"] = time.time() - 3.0
    asyncio.run(reconciler._reconcile_once())
    rest_polls = [item for item in telemetry.guardrails if item.get("type") == "order_reconcile_rest_poll"]
    assert len(rest_polls) == 2


def test_reconciler_skips_protective_orders():
    store = InMemoryOrderStore()

    async def seed():
        await store.record(
            symbol="BTC",
            side="sell",
            size=1.0,
            status="open",
            order_id="o1",
            client_order_id="entry123:sl",
        )

    asyncio.run(seed())
    manager = FakeExecutionManager(None)
    telemetry = FakeTelemetry()
    ctx = TelemetryContext(tenant_id="t1", bot_id="b1", exchange="bybit")
    reconciler = OrderReconcilerWorker(manager, store, telemetry=telemetry, telemetry_context=ctx)

    asyncio.run(reconciler._reconcile_once())
    assert telemetry.guardrails == []
    assert manager.calls == []
