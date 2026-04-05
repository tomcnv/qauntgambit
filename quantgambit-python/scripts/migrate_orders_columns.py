#!/usr/bin/env python3
"""Add missing order lifecycle columns for partial fills."""

from __future__ import annotations

import asyncio
import os

import asyncpg


def _dsn() -> str:
    host = os.getenv("BOT_DB_HOST", "localhost")
    port = os.getenv("BOT_DB_PORT", "5433")
    name = os.getenv("BOT_DB_NAME", "quantgambit_bot")
    user = os.getenv("BOT_DB_USER", "quantgambit")
    password = os.getenv("BOT_DB_PASSWORD", "")
    if password:
        return f"postgresql://{user}:{password}@{host}:{port}/{name}"
    return f"postgresql://{user}@{host}:{port}/{name}"


async def _migrate() -> None:
    dsn = _dsn()
    conn = await asyncpg.connect(dsn)
    try:
        await conn.execute(
            "ALTER TABLE IF EXISTS order_states "
            "ADD COLUMN IF NOT EXISTS filled_size DOUBLE PRECISION"
        )
        await conn.execute(
            "ALTER TABLE IF EXISTS order_states "
            "ADD COLUMN IF NOT EXISTS remaining_size DOUBLE PRECISION"
        )
        await conn.execute(
            "ALTER TABLE IF EXISTS order_lifecycle_events "
            "ADD COLUMN IF NOT EXISTS filled_size DOUBLE PRECISION"
        )
        await conn.execute(
            "ALTER TABLE IF EXISTS order_lifecycle_events "
            "ADD COLUMN IF NOT EXISTS remaining_size DOUBLE PRECISION"
        )
    finally:
        await conn.close()


def main() -> None:
    asyncio.run(_migrate())


if __name__ == "__main__":
    main()
