#!/usr/bin/env python3
"""Add missing dashboard data_settings columns."""

from __future__ import annotations

import asyncio
import os

import asyncpg


def _dsn() -> str:
    host = os.getenv("DASHBOARD_DB_HOST", "localhost")
    port = os.getenv("DASHBOARD_DB_PORT", "5432")
    name = os.getenv("DASHBOARD_DB_NAME", "deeptrader")
    user = os.getenv("DASHBOARD_DB_USER", "platform")
    password = os.getenv("DASHBOARD_DB_PASSWORD", "")
    if password:
        return f"postgresql://{user}:{password}@{host}:{port}/{name}"
    return f"postgresql://{user}@{host}:{port}/{name}"


async def _migrate() -> None:
    dsn = _dsn()
    conn = await asyncpg.connect(dsn)
    try:
        await conn.execute(
            "ALTER TABLE IF EXISTS data_settings "
            "ADD COLUMN IF NOT EXISTS backtest_history_retention_days INTEGER"
        )
    finally:
        await conn.close()


def main() -> None:
    asyncio.run(_migrate())


if __name__ == "__main__":
    main()
