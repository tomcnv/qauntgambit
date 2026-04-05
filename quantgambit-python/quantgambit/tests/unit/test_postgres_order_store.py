import asyncio

import asyncpg

from quantgambit.storage.postgres import OrderStatusRecord, PostgresOrderStore


class _FakeConn:
    def __init__(self):
        self.calls = []
        self._update_calls = 0
        self._insert_raised = False

    async def execute(self, query, *args):
        self.calls.append((query, args))
        normalized = " ".join(query.split())
        if normalized.startswith("UPDATE order_states SET"):
            self._update_calls += 1
            if self._update_calls in {1, 2, 3}:
                return "UPDATE 0"
            return "UPDATE 1"
        if normalized.startswith("INSERT INTO order_states"):
            self._insert_raised = True
            raise asyncpg.UniqueViolationError('duplicate key value violates unique constraint "order_states_order_id_idx"')
        raise AssertionError(f"unexpected query: {query}")


class _Acquire:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakePool:
    def __init__(self, conn):
        self._conn = conn

    def acquire(self):
        return _Acquire(self._conn)


def test_write_order_status_retries_on_order_id_after_client_id_unique_violation():
    conn = _FakeConn()
    store = PostgresOrderStore(_FakePool(conn))
    record = OrderStatusRecord(
        tenant_id="t1",
        bot_id="b1",
        exchange="bybit",
        symbol="ETHUSDT",
        side="buy",
        size=1.0,
        status="open",
        order_id="o1",
        client_order_id="c1",
        updated_at="2026-03-22T08:40:58Z",
    )

    asyncio.run(store.write_order_status(record))

    assert conn._insert_raised is True
    update_calls = [query for query, _args in conn.calls if "UPDATE order_states SET" in query]
    assert len(update_calls) == 4


class _ExpireFakeConn:
    def __init__(self):
        self.calls = []

    async def execute(self, query, *args):
        self.calls.append((query, args))
        normalized = " ".join(query.split())
        if normalized.startswith("UPDATE order_intents oi SET status='expired'"):
            return "UPDATE 1"
        raise AssertionError(f"unexpected query: {query}")


class _FetchFakeConn:
    def __init__(self):
        self.calls = []

    async def fetch(self, query, *args):
        self.calls.append((query, args))
        return []


def test_expire_stale_intents_skips_progressed_order_states():
    conn = _ExpireFakeConn()
    store = PostgresOrderStore(_FakePool(conn))

    expired = asyncio.run(store.expire_stale_intents("t1", "b1", 60.0))

    assert expired == 1
    assert conn.calls
    query, args = conn.calls[0]
    assert "NOT EXISTS" in query
    assert "FROM order_states os" in query
    assert "os.status NOT IN ('created', 'submitted', 'pending')" in query
    assert "oi.status IN ('created', 'submitted', 'pending')" in query
    assert args == ("t1", "b1", 60.0)


def test_load_pending_intents_includes_pending_status():
    conn = _FetchFakeConn()
    store = PostgresOrderStore(_FakePool(conn))

    intents = asyncio.run(store.load_pending_intents("t1", "b1"))

    assert intents == []
    assert conn.calls
    query, args = conn.calls[0]
    assert "status IN ('created', 'submitted', 'pending')" in query
    assert args == ("t1", "b1")
