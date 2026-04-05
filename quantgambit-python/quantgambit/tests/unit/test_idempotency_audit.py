import asyncio

from quantgambit.execution.idempotency_store import RedisIdempotencyStore
from quantgambit.storage.postgres import PostgresIdempotencyStore


class FakeRedis:
    def __init__(self):
        self.store = {}
        self.calls = []

    async def set(self, key, value, nx=False, ex=None):
        self.calls.append((key, value, nx, ex))
        if nx and key in self.store:
            return None
        self.store[key] = value
        return True


class FakePool:
    def __init__(self):
        self.calls = []
        self.rows = []

    def acquire(self):
        calls = self.calls
        rows = self.rows

        class Conn:
            async def execute(self, query, *args):
                calls.append((query, args))

            async def fetchrow(self, query, *args):
                calls.append((query, args))
                return rows[-1] if rows else None

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return None

        return Conn()


def test_idempotency_store_audits_claims():
    pool = FakePool()
    audit = PostgresIdempotencyStore(pool)
    store = RedisIdempotencyStore(FakeRedis(), bot_id="b1", tenant_id="t1", audit_store=audit)

    async def run_once():
        await store.claim("c1")

    asyncio.run(run_once())
    assert pool.calls


def test_idempotency_store_uses_audit_for_replay_dedupe():
    class FakeAuditStore:
        async def is_claimed(self, tenant_id, bot_id, client_order_id):
            return True

        async def write_audit(self, record):
            return None

    store = RedisIdempotencyStore(FakeRedis(), bot_id="b1", tenant_id="t1", audit_store=FakeAuditStore())

    async def run_once():
        return await store.claim("c1")

    claimed = asyncio.run(run_once())
    assert claimed is False


def test_idempotency_store_replays_recent_claims():
    class FakeAuditStore:
        async def load_recent_claims(self, tenant_id, bot_id, since, limit):
            return [
                {
                    "client_order_id": "c1",
                    "status": "claimed",
                    "expires_at": "2999-01-01T00:00:00Z",
                },
                {
                    "client_order_id": "c2",
                    "status": "duplicate",
                    "expires_at": "2999-01-01T00:00:00Z",
                },
                {
                    "client_order_id": "c3",
                    "status": "claimed",
                    "expires_at": "1999-01-01T00:00:00Z",
                },
            ]

    redis = FakeRedis()
    store = RedisIdempotencyStore(redis, bot_id="b1", tenant_id="t1", audit_store=FakeAuditStore())

    async def run_once():
        return await store.replay_recent_claims(hours=1, limit=10)

    replayed = asyncio.run(run_once())
    assert replayed == 1
    assert any(call[0].endswith(":execution:dedupe:c1") for call in redis.calls)


def test_idempotency_store_handles_redis_failure():
    class FailingRedis(FakeRedis):
        async def set(self, key, value, nx=False, ex=None):
            raise RuntimeError("redis_down")

    class FakeAuditStore:
        def __init__(self):
            self.calls = []

        async def is_claimed(self, tenant_id, bot_id, client_order_id):
            return False

        async def write_audit(self, record):
            self.calls.append(record)

    audit = FakeAuditStore()
    store = RedisIdempotencyStore(FailingRedis(), bot_id="b1", tenant_id="t1", audit_store=audit)

    async def run_once():
        return await store.claim("c1")

    claimed = asyncio.run(run_once())
    assert claimed is False
    assert audit.calls
    assert audit.calls[0].reason.startswith("redis_unavailable:")


def test_idempotency_store_alerts_on_redis_failure():
    class FailingRedis(FakeRedis):
        async def set(self, key, value, nx=False, ex=None):
            raise RuntimeError("redis_down")

    class FakeAlerts:
        def __init__(self):
            self.calls = []

        async def send(self, alert_type, message, metadata=None):
            self.calls.append((alert_type, message, metadata))

    alerts = FakeAlerts()
    store = RedisIdempotencyStore(
        FailingRedis(),
        bot_id="b1",
        tenant_id="t1",
        alert_hook=alerts.send,
    )

    async def run_once():
        return await store.claim("c1")

    claimed = asyncio.run(run_once())
    assert claimed is False
    assert alerts.calls
    assert alerts.calls[0][0] == "idempotency_store_unavailable"
