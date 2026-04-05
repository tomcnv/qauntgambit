"""Composite API server for control + backtests."""

from __future__ import annotations

import asyncio
import os

import asyncpg
import redis.asyncio as redis
from fastapi import FastAPI

from quantgambit.backtesting.api import BacktestAPI
from quantgambit.backtesting.retention import BacktestRetentionConfig, BacktestRetentionWorker
from quantgambit.control.api import ControlAPI
from quantgambit.settings.api import DataSettingsAPI
from quantgambit.storage.redis_streams import RedisStreamsClient


async def _create_pool(prefix: str):
    host = os.getenv(f"{prefix}DB_HOST", "localhost")
    port = os.getenv(f"{prefix}DB_PORT", "5433" if prefix == "BOT_" else "5432")
    name = os.getenv(f"{prefix}DB_NAME", "quantgambit_bot" if prefix == "BOT_" else "deeptrader")
    user = os.getenv(f"{prefix}DB_USER", "quantgambit")
    password = os.getenv(f"{prefix}DB_PASSWORD", "")
    if password:
        dsn = f"postgresql://{user}:{password}@{host}:{port}/{name}"
    else:
        dsn = f"postgresql://{user}@{host}:{port}/{name}"
    return await asyncpg.create_pool(dsn)


def create_app() -> FastAPI:
    app = FastAPI(title="QuantGambit API", version="v1")

    @app.on_event("startup")
    async def _startup() -> None:
        redis_url = os.getenv("BOT_REDIS_URL", "redis://localhost:6380")
        app.state.redis = redis.from_url(redis_url)
        app.state.bot_pool = await _create_pool("BOT_")
        app.state.dashboard_pool = await _create_pool("DASHBOARD_")
        retention_worker = BacktestRetentionWorker(
            app.state.dashboard_pool,
            config=BacktestRetentionConfig.from_env(),
        )
        app.state.backtest_retention_task = asyncio.create_task(retention_worker.run_forever())
        control_api = ControlAPI(RedisStreamsClient(app.state.redis))
        backtest_api = BacktestAPI(app.state.dashboard_pool)
        settings_api = DataSettingsAPI(app.state.dashboard_pool)
        app.include_router(control_api.app.router, prefix="/api/v1")
        app.include_router(backtest_api.app.router, prefix="/api/v1")
        app.include_router(settings_api.app.router, prefix="/api/v1")

    @app.on_event("shutdown")
    async def _shutdown() -> None:
        retention_task = getattr(app.state, "backtest_retention_task", None)
        if retention_task:
            retention_task.cancel()
        if getattr(app.state, "redis", None):
            await app.state.redis.aclose()
        if getattr(app.state, "bot_pool", None):
            await app.state.bot_pool.close()
        if getattr(app.state, "dashboard_pool", None):
            await app.state.dashboard_pool.close()

    return app


app = create_app()
