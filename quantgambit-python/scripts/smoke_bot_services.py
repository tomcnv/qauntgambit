#!/usr/bin/env python3
import os
import asyncio

import asyncpg
import redis.asyncio as redis


async def main() -> int:
    redis_url = os.getenv("BOT_REDIS_URL", "redis://localhost:6380")
    db_user = os.getenv("BOT_DB_USER", "quantgambit")
    db_host = os.getenv("BOT_DB_HOST", "localhost")
    db_port = os.getenv("BOT_DB_PORT", "5433")
    db_name = os.getenv("BOT_DB_NAME", "quantgambit_bot")
    db_password = os.getenv("BOT_DB_PASSWORD", "")

    if db_password:
        dsn = f"postgresql://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}"
    else:
        dsn = f"postgresql://{db_user}@{db_host}:{db_port}/{db_name}"

    r = redis.from_url(redis_url)
    pong = await r.ping()
    print("redis_ping", pong)
    await r.aclose()

    conn = await asyncpg.connect(dsn)
    val = await conn.fetchval("select 1")
    print("pg_select", val)
    await conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
