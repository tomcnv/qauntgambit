import asyncio
import os
import uuid
from datetime import datetime, timezone

import asyncpg
import pytest
import redis.asyncio as redis

from quantgambit.execution.order_store import InMemoryOrderStore
from quantgambit.portfolio.state_manager import InMemoryStateManager
from quantgambit.runtime.app import Runtime, RuntimeConfig
from quantgambit.storage.postgres import PostgresOrderStore, OrderEventRecord, OrderStatusRecord
from quantgambit.storage.redis_snapshots import RedisSnapshotReader, RedisSnapshotWriter
from quantgambit.storage.timescale import TimescaleReader, TimescaleWriter, TelemetryRow


def _require_real_services():
    if os.getenv("REAL_SERVICES", "").lower() not in {"1", "true", "yes"}:
        pytest.skip("REAL_SERVICES not enabled")


def _timescale_dsn() -> str:
    explicit = os.getenv("BOT_TIMESCALE_URL") or os.getenv("TIMESCALE_URL")
    if explicit:
        return explicit
    host = os.getenv("BOT_DB_HOST", "localhost")
    port = os.getenv("BOT_DB_PORT", "5432")
    name = os.getenv("BOT_DB_NAME", "quantgambit_bot")
    user = os.getenv("BOT_DB_USER", "quantgambit")
    password = os.getenv("BOT_DB_PASSWORD", "")
    auth = f"{user}:{password}@" if password else f"{user}@"
    return f"postgresql://{auth}{host}:{port}/{name}"


@pytest.mark.integration
def test_runtime_recovery_real_services():
    _require_real_services()

    async def run_once():
        redis_url = os.getenv("BOT_REDIS_URL") or os.getenv("REDIS_URL")
        if not redis_url:
            pytest.skip("BOT_REDIS_URL/REDIS_URL not set")
        dsn = _timescale_dsn()
        if not dsn:
            pytest.skip("Timescale DSN not configured")

        tenant_id = f"rt-{uuid.uuid4().hex[:8]}"
        bot_id = f"bot-{uuid.uuid4().hex[:8]}"
        exchange = os.getenv("ACTIVE_EXCHANGE", "okx")

        redis_client = redis.from_url(redis_url)
        pool = await asyncpg.create_pool(dsn)
        snapshots = RedisSnapshotWriter(redis_client)
        reader = RedisSnapshotReader(redis_client)
        timescale_reader = TimescaleReader(pool)
        timescale_writer = TimescaleWriter(pool)
        postgres_store = PostgresOrderStore(pool)
        state_manager = InMemoryStateManager()
        order_store = InMemoryOrderStore(
            snapshot_writer=snapshots,
            snapshot_reader=reader,
            snapshot_history_key=f"quantgambit:{tenant_id}:{bot_id}:orders:history",
            tenant_id=tenant_id,
            bot_id=bot_id,
            postgres_store=postgres_store,
        )

        runtime = Runtime.__new__(Runtime)
        runtime.config = RuntimeConfig(tenant_id=tenant_id, bot_id=bot_id, exchange=exchange)
        runtime.timescale_reader = timescale_reader
        runtime.snapshots = snapshots
        runtime.snapshot_reader = reader
        runtime.state_manager = state_manager
        runtime.order_store = order_store

        order_id = f"o-{uuid.uuid4().hex[:10]}"
        client_order_id = f"c-{uuid.uuid4().hex[:10]}"
        now = datetime.now(timezone.utc)

        await timescale_writer.write_order(
            TelemetryRow(
                tenant_id=tenant_id,
                bot_id=bot_id,
                symbol="BTCUSDT",
                exchange=exchange,
                timestamp=now,
                payload={
                    "order_id": order_id,
                    "client_order_id": client_order_id,
                    "status": "open",
                },
            )
        )
        await timescale_writer.write(
            "position_events",
            TelemetryRow(
                tenant_id=tenant_id,
                bot_id=bot_id,
                symbol="BTCUSDT",
                exchange=exchange,
                timestamp=now,
                payload={
                    "positions": [
                        {
                            "symbol": "BTCUSDT",
                            "side": "long",
                            "size": 1.0,
                            "entry_price": 100.0,
                        }
                    ]
                },
            ),
        )
        await postgres_store.write_order_status(
            OrderStatusRecord(
                tenant_id=tenant_id,
                bot_id=bot_id,
                exchange=exchange,
                symbol="BTCUSDT",
                side="buy",
                size=1.0,
                status="open",
                order_id=order_id,
                client_order_id=client_order_id,
                updated_at=now.isoformat(),
            )
        )
        await postgres_store.write_order_event(
            OrderEventRecord(
                tenant_id=tenant_id,
                bot_id=bot_id,
                exchange=exchange,
                symbol="BTCUSDT",
                side="buy",
                size=1.0,
                status="open",
                event_type="open",
                order_id=order_id,
                client_order_id=client_order_id,
                created_at=now.isoformat(),
            )
        )

        try:
            await runtime._restore_positions_from_timescale()
            await runtime._restore_order_snapshot_from_timescale()
            await order_store.load()
            replayed = await order_store.replay_recent_events(hours=1, limit=10)

            positions = await state_manager.list_open_positions()
            assert positions
            assert order_store.get(order_id, client_order_id) is not None
            assert replayed >= 1

            positions_key = f"quantgambit:{tenant_id}:{bot_id}:positions:latest"
            history_key = f"quantgambit:{tenant_id}:{bot_id}:order:history"
            assert await redis_client.get(positions_key) is not None
            assert await redis_client.lrange(history_key, 0, 0)
        finally:
            async with pool.acquire() as conn:
                await conn.execute(
                    "DELETE FROM order_states WHERE tenant_id=$1 AND bot_id=$2",
                    tenant_id,
                    bot_id,
                )
                await conn.execute(
                    "DELETE FROM order_events WHERE tenant_id=$1 AND bot_id=$2",
                    tenant_id,
                    bot_id,
                )
                await conn.execute(
                    "DELETE FROM position_events WHERE tenant_id=$1 AND bot_id=$2",
                    tenant_id,
                    bot_id,
                )
            await redis_client.delete(
                f"quantgambit:{tenant_id}:{bot_id}:positions:latest",
                f"quantgambit:{tenant_id}:{bot_id}:order:history",
                f"quantgambit:{tenant_id}:{bot_id}:orders:history",
            )
            await pool.close()
            await redis_client.aclose()

    asyncio.run(run_once())
