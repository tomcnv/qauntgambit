#!/usr/bin/env python3
"""Run one-time backtest snapshot retention cleanup."""

import asyncio
import os

import asyncpg

from quantgambit.backtesting.retention import BacktestRetentionConfig, BacktestRetentionWorker


async def main() -> None:
    config = BacktestRetentionConfig.from_env()
    host = os.getenv("DASHBOARD_DB_HOST", "localhost")
    port = os.getenv("DASHBOARD_DB_PORT", "5432")
    name = os.getenv("DASHBOARD_DB_NAME", "deeptrader")
    user = os.getenv("DASHBOARD_DB_USER", "platform")
    password = os.getenv("DASHBOARD_DB_PASSWORD", "")
    auth = f"{user}:{password}@" if password else f"{user}@"
    pool = await asyncpg.create_pool(f"postgresql://{auth}{host}:{port}/{name}")
    worker = BacktestRetentionWorker(pool, config=config)
    await worker.prune()
    await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
