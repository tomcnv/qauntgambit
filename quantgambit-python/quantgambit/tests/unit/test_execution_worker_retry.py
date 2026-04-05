import asyncio
import json
import time

from quantgambit.execution.execution_worker import ExecutionWorker, ExecutionWorkerConfig
from quantgambit.execution.manager import ExecutionIntent, OrderActionResult, OrderStatus
from quantgambit.execution.order_store import InMemoryOrderStore
from quantgambit.observability.telemetry import TelemetryContext
from quantgambit.storage.redis_streams import RedisStreamsClient


class FakeRedis:
    def __init__(self):
        self.store = {}

    async def xgroup_create(self, stream, group, id="0", mkstream=True):
        return None

    async def xreadgroup(self, group, consumer, streams, count=10, block=1000):
        return []

    async def xack(self, stream, group, message_id):
        return 1

    async def set(self, key, value, nx=False, ex=None):
        if nx and key in self.store:
            return None
        self.store[key] = value
        return True

    async def expire(self, key, ttl):
        return True


class FakeExecutionManager:
    def __init__(self, fail_times=1):
        self.fail_times = fail_times
        self.calls = 0
        self.intent = None
        self.order_store = None

    async def execute_intent(self, intent):
        self.calls += 1
        self.intent = intent
        status = "filled" if self.calls > self.fail_times else "rejected"
        return OrderStatus(order_id=f"order-{self.calls}", status=status)

    async def poll_order_status(self, order_id: str, symbol: str):
        return None

    async def record_order_status(self, intent, status):
        return status.status == "filled"


class FakeOrderStore:
    def __init__(self):
        self.errors = []
        self.intent = None

    async def record_error(self, **kwargs):
        self.errors.append(kwargs)

    async def load_intent_by_client_order_id(self, client_order_id):
        return self.intent


class CaptureIntentOrderStore(FakeOrderStore):
    def __init__(self):
        super().__init__()
        self.intents = []

    async def record_intent(self, **kwargs):
        self.intents.append(kwargs)


class FakeTelemetry:
    def __init__(self):
        self.guardrails = []
        self.orders = []

    async def publish_guardrail(self, ctx, payload):
        self.guardrails.append(payload)

    async def publish_order(self, ctx, symbol, payload):
        self.orders.append(payload)


class MakerRetryExecutionManager:
    def __init__(self, order_store):
        self.order_store = order_store
        self.calls = []
        self.reconciler = None

    async def execute_intent(self, intent):
        self.calls.append(intent.client_order_id)
        return OrderStatus(order_id=f"order-{len(self.calls)}", status="pending")

    async def poll_order_status(self, order_id: str, symbol: str):
        return None

    async def cancel_order(self, order_id: str | None, client_order_id: str | None, symbol: str):
        return OrderActionResult(status="ok", message="cancelled")

    async def record_order_status(self, intent, status):
        return False


class MakerFallbackExecutionManager(MakerRetryExecutionManager):
    async def execute_intent(self, intent):
        self.calls.append(intent.client_order_id)
        if str(intent.client_order_id).endswith(":f"):
            return OrderStatus(order_id=f"order-{len(self.calls)}", status="filled")
        return OrderStatus(order_id=f"order-{len(self.calls)}", status="pending")


class MakerFillOnPollExecutionManager(MakerRetryExecutionManager):
    async def poll_order_status(self, order_id: str, symbol: str):
        return OrderStatus(order_id=order_id, status="filled", filled_size=1.0, fill_price=100.0)

    async def record_order_status(self, intent, status):
        return status.status == "filled"


def test_execution_worker_retries_then_succeeds():
    worker = ExecutionWorker(
        redis_client=RedisStreamsClient(FakeRedis()),
        execution_manager=FakeExecutionManager(fail_times=1),
        bot_id="b1",
        exchange="okx",
        config=ExecutionWorkerConfig(max_retries=2, base_backoff_sec=0.0, max_backoff_sec=0.0),
    )
    intent = ExecutionIntent(symbol="BTC", side="buy", size=1.0)

    async def run_once():
        await worker._execute_with_retry(intent, timestamp=100.0)

    asyncio.run(run_once())
    assert worker.execution_manager.calls == 2


def test_execution_worker_treats_exit_no_position_as_terminal_noop():
    class ExitNoPositionManager(FakeExecutionManager):
        def __init__(self, order_store):
            super().__init__(fail_times=0)
            self.order_store = order_store

        async def execute_intent(self, intent):
            return OrderStatus(order_id=None, status="rejected", reason="exit_no_position")

    store = CaptureIntentOrderStore()
    worker = ExecutionWorker(
        redis_client=RedisStreamsClient(FakeRedis()),
        execution_manager=ExitNoPositionManager(store),
        bot_id="b1",
        exchange="okx",
        config=ExecutionWorkerConfig(max_retries=2, base_backoff_sec=0.0, max_backoff_sec=0.0),
    )
    intent = ExecutionIntent(
        symbol="ETH",
        side="sell",
        size=0.25,
        client_order_id="cid-exit-no-position",
        reduce_only=True,
        is_exit_signal=True,
    )

    async def run_once():
        return await worker._execute_with_retry(intent, timestamp=100.0)

    result = asyncio.run(run_once())
    assert result is True
    assert store.intents[-1]["status"] == "canceled"
    assert store.intents[-1]["last_error"] == "exit_no_position"
    assert worker._exit_no_position_until["ETH"] > time.time()


def test_execution_worker_blocks_repeated_exit_after_exit_no_position():
    class ExitNoPositionManager(FakeExecutionManager):
        def __init__(self, order_store):
            super().__init__(fail_times=0)
            self.order_store = order_store

        async def execute_intent(self, intent):
            return OrderStatus(order_id=None, status="rejected", reason="exit_no_position")

    store = CaptureIntentOrderStore()
    worker = ExecutionWorker(
        redis_client=RedisStreamsClient(FakeRedis()),
        execution_manager=ExitNoPositionManager(store),
        bot_id="b1",
        exchange="okx",
        config=ExecutionWorkerConfig(
            max_retries=2,
            base_backoff_sec=0.0,
            max_backoff_sec=0.0,
            exit_no_position_cooldown_sec=10.0,
        ),
    )
    worker.execution_manager.order_store = store

    payload = {
        "data": json.dumps(
            {
                "event_id": "evt-exit-repeat-1",
                "event_type": "risk_decision",
                "schema_version": "v1",
                "timestamp": str(time.time()),
                "ts_recv_us": int(time.time() * 1_000_000),
                "ts_canon_us": int(time.time() * 1_000_000),
                "ts_exchange_s": None,
                "bot_id": "b1",
                "payload": {
                    "symbol": "ETH",
                    "timestamp": time.time(),
                    "status": "accepted",
                    "signal": {
                        "side": "sell",
                        "size": 0.25,
                        "is_exit_signal": True,
                        "reduce_only": True,
                    },
                },
            }
        )
    }
    payload2 = {
        "data": payload["data"].replace("evt-exit-repeat-1", "evt-exit-repeat-2")
    }

    async def run_twice():
        await worker._handle_message(payload)
        await worker._handle_message(payload2)

    asyncio.run(run_twice())
    error_codes = [e.get("error_code") for e in store.errors]
    assert "exit_signal_no_position_cooldown" in error_codes


def test_execution_worker_treats_spot_exit_insufficient_balance_as_terminal():
    class SpotInsufficientBalanceManager(FakeExecutionManager):
        def __init__(self, order_store):
            super().__init__(fail_times=0)
            self.order_store = order_store
            self.reconciler = None

        async def execute_intent(self, intent):
            return OrderStatus(
                order_id=None,
                status="rejected",
                reason='exchange_error: bybit {"retCode":170131,"retMsg":"Insufficient balance."}',
            )

    store = CaptureIntentOrderStore()
    worker = ExecutionWorker(
        redis_client=RedisStreamsClient(FakeRedis()),
        execution_manager=SpotInsufficientBalanceManager(store),
        bot_id="b1",
        exchange="bybit",
        config=ExecutionWorkerConfig(
            market_type="spot",
            max_retries=2,
            base_backoff_sec=0.0,
            max_backoff_sec=0.0,
            exit_no_position_cooldown_sec=10.0,
        ),
    )
    intent = ExecutionIntent(
        symbol="BTCUSDT",
        side="sell",
        size=0.1,
        client_order_id="cid-spot-balance-miss",
        reduce_only=True,
        is_exit_signal=True,
    )

    async def run_once():
        return await worker._execute_with_retry(intent, timestamp=100.0)

    result = asyncio.run(run_once())
    assert result is True
    assert store.intents[-1]["status"] == "canceled"
    assert "170131" in str(store.intents[-1]["last_error"])
    assert worker._exit_no_position_until["BTCUSDT"] > time.time()


def test_execution_worker_polls_pending_orders():
    class PendingExecutionManager(FakeExecutionManager):
        def __init__(self):
            super().__init__(fail_times=0)
            self.polled = 0

        async def execute_intent(self, intent):
            return OrderStatus(order_id="order-1", status="pending")

        async def poll_order_status(self, order_id: str, symbol: str):
            self.polled += 1
            return OrderStatus(order_id=order_id, status="filled")

    telemetry = FakeTelemetry()
    ctx = TelemetryContext(tenant_id="t1", bot_id="b1", exchange="okx")
    worker = ExecutionWorker(
        redis_client=RedisStreamsClient(FakeRedis()),
        execution_manager=PendingExecutionManager(),
        bot_id="b1",
        exchange="okx",
        config=ExecutionWorkerConfig(
            status_poll_interval_sec=0.0,
            status_poll_attempts=1,
            base_backoff_sec=0.0,
            max_backoff_sec=0.0,
        ),
        telemetry=telemetry,
        telemetry_context=ctx,
    )
    intent = ExecutionIntent(symbol="BTC", side="buy", size=1.0)

    async def run_once():
        await worker._execute_with_retry(intent, timestamp=100.0)

    asyncio.run(run_once())
    assert worker.execution_manager.polled == 1
    payload = next(item for item in telemetry.guardrails if item.get("type") == "order_status_rest_poll")
    assert payload.get("reason") == "ws_gap_rest_poll"


def test_execution_worker_emits_poll_failed_guardrail():
    class PendingExecutionManager(FakeExecutionManager):
        def __init__(self):
            super().__init__(fail_times=0)
            self.polled = 0

        async def execute_intent(self, intent):
            return OrderStatus(order_id="order-1", status="pending")

        async def poll_order_status(self, order_id: str, symbol: str):
            self.polled += 1
            return None

    telemetry = FakeTelemetry()
    ctx = TelemetryContext(tenant_id="t1", bot_id="b1", exchange="okx")
    worker = ExecutionWorker(
        redis_client=RedisStreamsClient(FakeRedis()),
        execution_manager=PendingExecutionManager(),
        bot_id="b1",
        exchange="okx",
        config=ExecutionWorkerConfig(
            status_poll_interval_sec=0.0,
            status_poll_attempts=1,
            base_backoff_sec=0.0,
            max_backoff_sec=0.0,
        ),
        telemetry=telemetry,
        telemetry_context=ctx,
    )
    intent = ExecutionIntent(symbol="BTC", side="buy", size=1.0)

    async def run_once():
        await worker._execute_with_retry(intent, timestamp=100.0)

    asyncio.run(run_once())
    payload = next(item for item in telemetry.guardrails if item.get("type") == "order_status_poll_failed")
    assert payload.get("reason") == "ws_gap_poll_failed"


def test_execution_worker_resolves_from_ws_store():
    class PendingExecutionManager(FakeExecutionManager):
        def __init__(self, store):
            super().__init__(fail_times=0)
            self.order_store = store
            self.polled = 0

        async def execute_intent(self, intent):
            return OrderStatus(order_id="order-1", status="pending")

        async def poll_order_status(self, order_id: str, symbol: str):
            self.polled += 1
            return OrderStatus(order_id=order_id, status="filled")

    telemetry = FakeTelemetry()
    ctx = TelemetryContext(tenant_id="t1", bot_id="b1", exchange="okx")
    store = InMemoryOrderStore()

    async def seed():
        await store.record(
            symbol="BTC",
            side="buy",
            size=1.0,
            status="filled",
            order_id="order-1",
            client_order_id="c1",
            timestamp=1.0,
            source="ws",
        )

    asyncio.run(seed())
    worker = ExecutionWorker(
        redis_client=RedisStreamsClient(FakeRedis()),
        execution_manager=PendingExecutionManager(store),
        bot_id="b1",
        exchange="okx",
        config=ExecutionWorkerConfig(
            status_poll_interval_sec=0.0,
            status_poll_attempts=2,
            base_backoff_sec=0.0,
            max_backoff_sec=0.0,
        ),
        telemetry=telemetry,
        telemetry_context=ctx,
    )
    intent = ExecutionIntent(symbol="BTC", side="buy", size=1.0, client_order_id="c1")

    async def run_once():
        await worker._execute_with_retry(intent, timestamp=100.0)

    asyncio.run(run_once())
    assert worker.execution_manager.polled == 0
    assert any(item.get("type") == "order_status_ws_resolved" for item in telemetry.guardrails)


def test_execution_worker_polls_by_client_order_id_when_missing_order_id():
    class PendingExecutionManager(FakeExecutionManager):
        def __init__(self):
            super().__init__(fail_times=0)
            self.polled = 0

        async def execute_intent(self, intent):
            return OrderStatus(order_id=None, status="pending")

        async def poll_order_status_by_client_id(self, client_order_id: str, symbol: str):
            self.polled += 1
            return OrderStatus(order_id=client_order_id, status="filled")

    worker = ExecutionWorker(
        redis_client=RedisStreamsClient(FakeRedis()),
        execution_manager=PendingExecutionManager(),
        bot_id="b1",
        exchange="okx",
        config=ExecutionWorkerConfig(
            status_poll_interval_sec=0.0,
            status_poll_attempts=1,
            base_backoff_sec=0.0,
            max_backoff_sec=0.0,
        ),
    )
    intent = ExecutionIntent(symbol="BTC", side="buy", size=1.0, client_order_id="c1")

    async def run_once():
        await worker._execute_with_retry(intent, timestamp=100.0)

    asyncio.run(run_once())
    assert worker.execution_manager.polled == 1


def test_execution_worker_sets_client_order_id():
    worker = ExecutionWorker(
        redis_client=RedisStreamsClient(FakeRedis()),
        execution_manager=FakeExecutionManager(fail_times=0),
        bot_id="b1",
        exchange="okx",
        config=ExecutionWorkerConfig(
            max_retries=0,
            base_backoff_sec=0.0,
            max_backoff_sec=0.0,
            max_decision_age_sec=999.0,
        ),
    )
    now = __import__("time").time()
    ts_us = int(now * 1_000_000)
    payload = {
        "event_id": "evt-1",
        "event_type": "risk_decision",
        "schema_version": "v1",
        "timestamp": "1",
        "ts_recv_us": ts_us,
        "ts_canon_us": ts_us,
        "ts_exchange_s": None,
        "bot_id": "b1",
        "payload": {
            "symbol": "BTC",
            "timestamp": now,
            "status": "accepted",
            "signal": {"side": "buy", "size": 1.0},
        },
    }

    async def run_once():
        await worker._handle_message({"data": __import__("json").dumps(payload)})

    asyncio.run(run_once())
    assert worker.execution_manager.intent.client_order_id.startswith("qg-")


def test_execution_worker_rejects_stale_decision():
    worker = ExecutionWorker(
        redis_client=RedisStreamsClient(FakeRedis()),
        execution_manager=FakeExecutionManager(fail_times=0),
        bot_id="b1",
        exchange="okx",
        config=ExecutionWorkerConfig(max_decision_age_sec=0.0),
    )
    ts_us = int(1 * 1_000_000)
    payload = {
        "event_id": "evt-2",
        "event_type": "risk_decision",
        "schema_version": "v1",
        "timestamp": "1",
        "ts_recv_us": ts_us,
        "ts_canon_us": ts_us,
        "ts_exchange_s": None,
        "bot_id": "b1",
        "payload": {
            "symbol": "BTC",
            "timestamp": 1,
            "status": "accepted",
            "signal": {"side": "buy", "size": 1.0},
        },
    }

    async def run_once():
        await worker._handle_message({"data": __import__("json").dumps(payload)})

    asyncio.run(run_once())
    assert worker.execution_manager.calls == 0


def test_execution_worker_rejects_stale_reference_price():
    class FakePriceCache:
        def get_reference_price_with_ts(self, symbol):
            return (100.0, __import__("time").time() - 999)

    class PriceAwareExecutionManager(FakeExecutionManager):
        def __init__(self):
            super().__init__(fail_times=0)
            self.exchange_client = type("Client", (), {"reference_prices": FakePriceCache()})()

    worker = ExecutionWorker(
        redis_client=RedisStreamsClient(FakeRedis()),
        execution_manager=PriceAwareExecutionManager(),
        bot_id="b1",
        exchange="okx",
        config=ExecutionWorkerConfig(max_reference_price_age_sec=1.0, max_decision_age_sec=999.0),
    )
    now = __import__("time").time()
    ts_us = int(now * 1_000_000)
    payload = {
        "event_id": "evt-3",
        "event_type": "risk_decision",
        "schema_version": "v1",
        "timestamp": "1",
        "ts_recv_us": ts_us,
        "ts_canon_us": ts_us,
        "ts_exchange_s": None,
        "bot_id": "b1",
        "payload": {
            "symbol": "BTC",
            "timestamp": now,
            "status": "accepted",
            "signal": {"side": "buy", "size": 1.0},
        },
    }

    async def run_once():
        await worker._handle_message({"data": __import__("json").dumps(payload)})

    asyncio.run(run_once())
    assert worker.execution_manager.calls == 0


def test_execution_worker_records_decode_error():
    store = FakeOrderStore()
    manager = FakeExecutionManager(fail_times=0)
    manager.order_store = store
    worker = ExecutionWorker(
        redis_client=RedisStreamsClient(FakeRedis()),
        execution_manager=manager,
        bot_id="b1",
        exchange="okx",
    )

    async def run_once():
        await worker._handle_message({"data": "not-json"})

    asyncio.run(run_once())
    assert store.errors
    assert store.errors[0]["stage"] == "decode"


def test_execution_worker_uses_db_intent_guard():
    store = FakeOrderStore()
    store.intent = {"status": "submitted"}
    manager = FakeExecutionManager(fail_times=0)
    manager.order_store = store
    worker = ExecutionWorker(
        redis_client=RedisStreamsClient(FakeRedis()),
        execution_manager=manager,
        bot_id="b1",
        exchange="okx",
        config=ExecutionWorkerConfig(max_decision_age_sec=999.0),
    )
    now = __import__("time").time()
    ts_us = int(now * 1_000_000)
    payload = {
        "event_id": "evt-guard",
        "event_type": "risk_decision",
        "schema_version": "v1",
        "timestamp": "1",
        "ts_recv_us": ts_us,
        "ts_canon_us": ts_us,
        "ts_exchange_s": None,
        "bot_id": "b1",
        "payload": {
            "symbol": "BTC",
            "timestamp": now,
            "status": "accepted",
            "signal": {"side": "buy", "size": 1.0},
        },
    }

    async def run_once():
        await worker._handle_message({"data": __import__("json").dumps(payload)})

    asyncio.run(run_once())
    assert manager.calls == 0
    assert store.errors
    assert store.errors[0]["error_code"] == "intent_exists"


def test_execution_worker_rejects_stale_orderbook():
    class FakeOrderbookCache:
        def get_reference_price_with_ts(self, symbol):
            return (100.0, __import__("time").time())

        def get_orderbook_with_ts(self, symbol):
            return ({"bids": [[100.0, 1.0]], "asks": [[101.0, 1.0]]}, __import__("time").time() - 999)

    class OrderbookExecutionManager(FakeExecutionManager):
        def __init__(self):
            super().__init__(fail_times=0)
            self.exchange_client = type("Client", (), {"reference_prices": FakeOrderbookCache()})()

    worker = ExecutionWorker(
        redis_client=RedisStreamsClient(FakeRedis()),
        execution_manager=OrderbookExecutionManager(),
        bot_id="b1",
        exchange="okx",
        config=ExecutionWorkerConfig(
            max_reference_price_age_sec=999.0,
            max_orderbook_age_sec=1.0,
            max_decision_age_sec=999.0,
        ),
    )
    now = __import__("time").time()
    payload = {
        "event_id": "evt-3b",
        "event_type": "risk_decision",
        "schema_version": "v1",
        "timestamp": "1",
        "bot_id": "b1",
        "payload": {
            "symbol": "BTC",
            "timestamp": now,
            "status": "accepted",
            "signal": {"side": "buy", "size": 1.0},
        },
    }

    async def run_once():
        await worker._handle_message({"data": __import__("json").dumps(payload)})

    asyncio.run(run_once())
    assert worker.execution_manager.calls == 0


def test_execution_worker_spot_accepts_fresh_book_with_stale_reference_cache():
    class FakeOrderbookCache:
        def get_reference_price_with_ts(self, symbol):
            return (100.0, __import__("time").time() - 999)

        def get_orderbook_with_ts(self, symbol):
            return ({"bids": [[100.0, 1.0]], "asks": [[101.0, 1.0]]}, __import__("time").time())

    class OrderbookExecutionManager(FakeExecutionManager):
        def __init__(self):
            super().__init__(fail_times=0)
            self.exchange_client = type("Client", (), {"reference_prices": FakeOrderbookCache()})()

    worker = ExecutionWorker(
        redis_client=RedisStreamsClient(FakeRedis()),
        execution_manager=OrderbookExecutionManager(),
        bot_id="b1",
        exchange="bybit",
        config=ExecutionWorkerConfig(
            market_type="spot",
            max_reference_price_age_sec=999.0,
            max_orderbook_age_sec=1.0,
            entry_max_reference_age_ms=1500,
            entry_max_orderbook_age_ms=1500,
            max_decision_age_sec=999.0,
        ),
    )
    now = __import__("time").time()
    ts_us = int(now * 1_000_000)
    payload = {
        "event_id": "evt-spot-freshness",
        "event_type": "risk_decision",
        "schema_version": "v1",
        "timestamp": "1",
        "ts_recv_us": ts_us,
        "ts_canon_us": ts_us,
        "ts_exchange_s": None,
        "bot_id": "b1",
        "payload": {
            "symbol": "BTCUSDT",
            "timestamp": now,
            "status": "accepted",
            "signal": {"side": "buy", "size": 1.0},
        },
    }

    async def run_once():
        await worker._handle_message({"data": __import__("json").dumps(payload)})

    asyncio.run(run_once())
    assert worker.execution_manager.calls == 1


def test_execution_worker_dedupes_duplicate_intents():
    redis = FakeRedis()
    worker = ExecutionWorker(
        redis_client=RedisStreamsClient(redis),
        execution_manager=FakeExecutionManager(fail_times=0),
        bot_id="b1",
        exchange="okx",
        config=ExecutionWorkerConfig(
            max_retries=0,
            base_backoff_sec=0.0,
            max_backoff_sec=0.0,
            max_decision_age_sec=999.0,
            dedupe_ttl_sec=60,
        ),
    )
    now = __import__("time").time()
    ts_us = int(now * 1_000_000)
    payload = {
        "event_id": "evt-dedupe",
        "event_type": "risk_decision",
        "schema_version": "v1",
        "timestamp": "1",
        "ts_recv_us": ts_us,
        "ts_canon_us": ts_us,
        "ts_exchange_s": None,
        "bot_id": "b1",
        "payload": {
            "symbol": "BTC",
            "timestamp": now,
            "status": "accepted",
            "signal": {"side": "buy", "size": 1.0},
        },
    }

    async def run_twice():
        await worker._handle_message({"data": __import__("json").dumps(payload)})
        await worker._handle_message({"data": __import__("json").dumps(payload)})

    asyncio.run(run_twice())
    assert worker.execution_manager.calls == 1


def test_idempotency_store_claims_once():
    from quantgambit.execution.idempotency_store import RedisIdempotencyStore

    redis = FakeRedis()
    store = RedisIdempotencyStore(redis, bot_id="b1", tenant_id="t1")

    async def run_once():
        first = await store.claim("c1")
        second = await store.claim("c1")
        return first, second

    first, second = asyncio.run(run_once())
    assert first is True
    assert second is False


def test_maker_retry_keeps_root_lineage_and_uses_attempt_ids_for_exchange():
    order_store = CaptureIntentOrderStore()
    manager = MakerRetryExecutionManager(order_store)
    worker = ExecutionWorker(
        redis_client=RedisStreamsClient(FakeRedis()),
        execution_manager=manager,
        bot_id="b1",
        exchange="okx",
        config=ExecutionWorkerConfig(
            entry_maker_max_reposts=1,
            entry_maker_fill_window_ms=1,
            entry_maker_fallback_to_market=False,
            status_poll_interval_sec=0.0,
            status_poll_attempts=1,
            base_backoff_sec=0.0,
            max_backoff_sec=0.0,
        ),
    )
    intent = ExecutionIntent(
        symbol="BTC",
        side="buy",
        size=1.0,
        order_type="limit",
        post_only=True,
        limit_price=100.0,
        client_order_id="qg-root",
    )

    async def run_once():
        ok = await worker._execute_maker_entry(intent, timestamp=100.0)
        assert ok is False

    asyncio.run(run_once())

    assert manager.calls == ["qg-root:m0", "qg-root:m1"]
    assert order_store.intents
    assert all(item["client_order_id"] == "qg-root" for item in order_store.intents)
    submitted = [item for item in order_store.intents if item["status"] == "submitted"]
    assert submitted
    attempt_ids = {item["snapshot_metrics"]["attempt_client_order_id"] for item in submitted}
    assert attempt_ids == {"qg-root:m0", "qg-root:m1"}


def test_maker_fallback_terminalizes_root_intent_before_market_fallback():
    order_store = CaptureIntentOrderStore()
    manager = MakerFallbackExecutionManager(order_store)
    worker = ExecutionWorker(
        redis_client=RedisStreamsClient(FakeRedis()),
        execution_manager=manager,
        bot_id="b1",
        exchange="okx",
        config=ExecutionWorkerConfig(
            entry_maker_max_reposts=0,
            entry_maker_fill_window_ms=1,
            entry_maker_fallback_to_market=True,
            status_poll_interval_sec=0.0,
            status_poll_attempts=1,
            base_backoff_sec=0.0,
            max_backoff_sec=0.0,
        ),
    )
    intent = ExecutionIntent(
        symbol="BTC",
        side="buy",
        size=1.0,
        order_type="limit",
        post_only=True,
        limit_price=100.0,
        client_order_id="qg-root",
    )

    async def run_once():
        ok = await worker._execute_maker_entry(intent, timestamp=100.0)
        assert ok is True

    asyncio.run(run_once())

    root_rows = [item for item in order_store.intents if item["client_order_id"] == "qg-root"]
    assert root_rows
    assert any(item["status"] == "submitted" for item in root_rows)
    assert any(
        item["status"] == "canceled"
        and item.get("last_error") == "maker_unfilled_timeout_fallback_market"
        for item in root_rows
    )


def test_maker_poll_fill_terminalizes_root_intent():
    order_store = CaptureIntentOrderStore()
    manager = MakerFillOnPollExecutionManager(order_store)
    worker = ExecutionWorker(
        redis_client=RedisStreamsClient(FakeRedis()),
        execution_manager=manager,
        bot_id="b1",
        exchange="okx",
        config=ExecutionWorkerConfig(
            entry_maker_max_reposts=0,
            entry_maker_fill_window_ms=5,
            entry_maker_fallback_to_market=False,
            status_poll_interval_sec=0.0,
            status_poll_attempts=1,
            base_backoff_sec=0.0,
            max_backoff_sec=0.0,
        ),
    )
    intent = ExecutionIntent(
        symbol="BTC",
        side="buy",
        size=1.0,
        order_type="limit",
        post_only=True,
        limit_price=100.0,
        client_order_id="qg-root",
    )

    async def run_once():
        ok = await worker._execute_maker_entry(intent, timestamp=100.0)
        assert ok is True

    asyncio.run(run_once())

    root_rows = [item for item in order_store.intents if item["client_order_id"] == "qg-root"]
    assert root_rows
    assert any(item["status"] == "submitted" for item in root_rows)
    assert any(item["status"] == "filled" for item in root_rows)


def test_execution_worker_throttles_rapid_non_safety_exits():
    worker = ExecutionWorker(
        redis_client=RedisStreamsClient(FakeRedis()),
        execution_manager=FakeExecutionManager(fail_times=0),
        bot_id="b1",
        exchange="okx",
        config=ExecutionWorkerConfig(
            max_retries=0,
            base_backoff_sec=0.0,
            max_backoff_sec=0.0,
            max_decision_age_sec=999.0,
            exit_min_signal_interval_sec=30.0,
        ),
    )
    now = __import__("time").time()
    ts_us = int(now * 1_000_000)

    def _payload(event_id: str):
        return {
            "event_id": event_id,
            "event_type": "risk_decision",
            "schema_version": "v1",
            "timestamp": "1",
            "ts_recv_us": ts_us,
            "ts_canon_us": ts_us,
            "ts_exchange_s": None,
            "bot_id": "b1",
            "payload": {
                "symbol": "BTC",
                "timestamp": now,
                "status": "accepted",
                "signal": {
                    "side": "sell",
                    "size": 1.0,
                    "is_exit_signal": True,
                    "reduce_only": True,
                    "exit_type": "invalidation",
                    "fee_aware": {"fee_check_passed": True},
                },
            },
        }

    async def run_twice():
        await worker._handle_message({"data": __import__("json").dumps(_payload("evt-exit-1"))})
        await worker._handle_message({"data": __import__("json").dumps(_payload("evt-exit-2"))})

    asyncio.run(run_twice())
    assert worker.execution_manager.calls == 1


def test_execution_worker_does_not_start_entry_cooldown_after_failed_attempt():
    worker = ExecutionWorker(
        redis_client=RedisStreamsClient(FakeRedis()),
        execution_manager=FakeExecutionManager(fail_times=99),
        bot_id="b1",
        exchange="okx",
        config=ExecutionWorkerConfig(
            max_retries=0,
            base_backoff_sec=0.0,
            max_backoff_sec=0.0,
            max_decision_age_sec=999.0,
        ),
    )
    now = __import__("time").time()
    ts_us = int(now * 1_000_000)

    def _payload(event_id: str):
        return {
            "event_id": event_id,
            "event_type": "risk_decision",
            "schema_version": "v1",
            "timestamp": "1",
            "ts_recv_us": ts_us,
            "ts_canon_us": ts_us,
            "ts_exchange_s": None,
            "bot_id": "b1",
            "payload": {
                "symbol": "BTC",
                "timestamp": now,
                "status": "accepted",
                "reference_price": 100.0,
                "signal": {
                    "side": "buy",
                    "size": 1.0,
                },
            },
        }

    async def run_twice():
        await worker._handle_message({"data": __import__("json").dumps(_payload("evt-entry-1"))})
        await worker._handle_message({"data": __import__("json").dumps(_payload("evt-entry-2"))})

    asyncio.run(run_twice())

    assert worker.execution_manager.calls == 2
    assert "BTC" not in worker._last_order_time
