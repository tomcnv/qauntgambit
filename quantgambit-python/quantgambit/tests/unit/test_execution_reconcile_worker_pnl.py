import asyncio
import json

from quantgambit.execution.execution_reconcile_worker import (
    ExecutionReconcileConfig,
    ExecutionReconcileWorker,
    _filter_trades_for_known_orders,
)


class _FakeConn:
    def __init__(self) -> None:
        self.inserts = []
        self.state_inserts = []
        self.updates = []

    async def execute(self, query, *args):
        if "INSERT INTO order_events" in query:
            self.inserts.append(args)
        elif "INSERT INTO order_states" in query:
            self.state_inserts.append(args)
        elif "UPDATE order_states SET" in query:
            self.updates.append(args)
            return "UPDATE 0"
        return "OK"


class _AcquireCtx:
    def __init__(self, conn: _FakeConn) -> None:
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakePool:
    def __init__(self, conn: _FakeConn) -> None:
        self._conn = conn

    def acquire(self):
        return _AcquireCtx(self._conn)


def _build_worker(*, closed_pnl_is_net: bool) -> tuple[ExecutionReconcileWorker, _FakeConn]:
    worker = ExecutionReconcileWorker(
        tenant_id="t",
        bot_id="b",
        exchange="bybit",
        secret_id="s",
        symbols=["BTCUSDT"],
        dsn="postgres://unused",
        redis_url="redis://unused",
        demo=False,
        testnet=False,
        config=ExecutionReconcileConfig(closed_pnl_is_net=closed_pnl_is_net),
    )
    conn = _FakeConn()
    worker._pool = _FakePool(conn)  # type: ignore[assignment]
    return worker, conn


def test_derive_pnl_fields_when_closed_pnl_is_net():
    worker, _ = _build_worker(closed_pnl_is_net=True)
    gross, net = worker._derive_pnl_fields(closed_pnl=-8.5, total_fee_usd=1.2)
    assert gross == -7.3
    assert net == -8.5


def test_derive_pnl_fields_when_closed_pnl_is_gross():
    worker, _ = _build_worker(closed_pnl_is_net=False)
    gross, net = worker._derive_pnl_fields(closed_pnl=-8.5, total_fee_usd=1.2)
    assert gross == -8.5
    assert net == -9.7


def test_insert_reconcile_payload_sets_gross_and_net_consistently():
    worker, conn = _build_worker(closed_pnl_is_net=True)
    agg = {
        "order_id": "o1",
        "client_order_id": "c1",
        "symbol": "BTCUSDT",
        "side": "sell",
        "total_qty": 0.1,
        "avg_price": 70000.0,
        "total_fee_usd": 2.0,
        # Legacy-only input: exec_pnl contains exchange closed_pnl.
        "exec_pnl": -10.0,
        "exec_count": 1,
        "first_exec_time_ms": 1700000000000,
        "last_exec_time_ms": 1700000001000,
        "closed_pnl_record": True,
    }

    asyncio.run(worker._insert_order_event_reconcile(agg))
    assert conn.inserts, "expected one INSERT INTO order_events call"
    payload_raw = conn.inserts[-1][-2]
    payload = json.loads(payload_raw)
    assert payload["gross_pnl"] == -8.0
    assert payload["net_pnl"] == -10.0
    assert payload["realized_pnl"] == -10.0
    assert payload["closed_pnl_is_net"] is True


def test_build_reconcile_payload_marks_open_side_without_pnl_fields():
    worker, _ = _build_worker(closed_pnl_is_net=True)
    agg = {
        "order_id": "o2",
        "client_order_id": "c2",
        "symbol": "BTCUSDT",
        "side": "buy",
        "total_qty": 0.2,
        "avg_price": 65000.0,
        "total_fee_usd": 1.5,
        "exec_count": 2,
        "first_exec_time_ms": 1700000000000,
        "last_exec_time_ms": 1700000002000,
    }

    _, payload = worker._build_reconcile_payload(agg)
    assert payload["position_effect"] == "open"
    assert payload["reason"] == "exchange_reconcile_open"
    assert payload["event_type"] == "exchange_reconcile_open"
    assert "gross_pnl" not in payload
    assert "net_pnl" not in payload
    assert "realized_pnl" not in payload


def test_upsert_order_state_reconcile_inserts_filled_state_for_open_side():
    worker, conn = _build_worker(closed_pnl_is_net=True)
    agg = {
        "order_id": "o3",
        "client_order_id": "c3",
        "symbol": "ETHUSDT",
        "side": "buy",
        "total_qty": 1.25,
        "avg_price": 3200.0,
        "total_fee_usd": 0.7,
        "exec_count": 1,
        "first_exec_time_ms": 1700000000000,
        "last_exec_time_ms": 1700000001000,
    }

    asyncio.run(worker._upsert_order_state_reconcile(agg))
    assert conn.state_inserts, "expected one INSERT INTO order_states call"
    insert_args = conn.state_inserts[-1]
    assert insert_args[6] == "filled"
    assert insert_args[7] == "o3"
    assert insert_args[8] == "c3"
    assert insert_args[9] == "exchange_reconcile_open"


def test_build_reconcile_payload_marks_stop_link_orders_as_close_even_without_closed_pnl():
    worker, _ = _build_worker(closed_pnl_is_net=True)
    agg = {
        "order_id": "o4",
        "client_order_id": "qg-123:sl",
        "symbol": "BTCUSDT",
        "side": "sell",
        "total_qty": 0.05,
        "avg_price": 67000.0,
        "total_fee_usd": 0.4,
        "exec_count": 1,
        "first_exec_time_ms": 1700000000000,
        "last_exec_time_ms": 1700000001000,
        "raw": {"stopOrderType": "tpslOrder"},
    }

    _, payload = worker._build_reconcile_payload(agg)
    assert payload["position_effect"] == "close"
    assert payload["reason"] == "exchange_reconcile_close"


def test_filter_trades_for_known_orders_keeps_only_bot_owned_lineage():
    trades = [
        {"order_id": "o1", "client_order_id": "c1"},
        {"order_id": "o2", "client_order_id": "foreign"},
        {"order_id": "foreign-order", "client_order_id": "c3"},
        {"order_id": "foreign-order-2", "client_order_id": "foreign-2"},
    ]
    filtered = _filter_trades_for_known_orders(
        trades,
        known_client_order_ids={"c1", "c3"},
        known_order_ids={"o1"},
    )
    assert filtered == [
        {"order_id": "o1", "client_order_id": "c1"},
        {"order_id": "foreign-order", "client_order_id": "c3"},
    ]
