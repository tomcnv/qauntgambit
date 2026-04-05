"""FastAPI endpoints for data settings."""

from __future__ import annotations

from dataclasses import asdict

from fastapi import FastAPI, Depends

from quantgambit.auth.jwt_auth import build_auth_dependency
from quantgambit.settings.models import DataSettings
from quantgambit.settings.store import DataSettingsStore


def _default_settings(tenant_id: str) -> DataSettings:
    return DataSettings(
        tenant_id=tenant_id,
        trade_history_retention_days=365,
        replay_snapshot_retention_days=30,
        backtest_history_retention_days=365,
        backtest_equity_sample_every=1,
        backtest_max_equity_points=2000,
        backtest_max_symbol_equity_points=2000,
        backtest_max_decision_snapshots=2000,
        backtest_max_position_snapshots=2000,
        capture_decision_traces=True,
        capture_feature_values=True,
        capture_orderbook=False,
    )


class DataSettingsAPI:
    def __init__(self, pool):
        self.pool = pool
        self.store = DataSettingsStore(pool)
        self.app = FastAPI(title="QuantGambit Settings", version="v1")
        self._auth = build_auth_dependency()
        self._register_routes()

    def _register_routes(self) -> None:
        @self.app.get("/settings/data", dependencies=[Depends(self._auth)])
        async def get_settings(tenant_id: str):
            settings = await self.store.get(tenant_id)
            return asdict(settings) if settings else asdict(_default_settings(tenant_id))

        @self.app.post("/settings/data", dependencies=[Depends(self._auth)])
        async def update_settings(payload: DataSettings):
            await self.store.upsert(payload)
            return {"success": True, "settings": asdict(payload)}
