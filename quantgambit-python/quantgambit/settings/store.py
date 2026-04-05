"""Persistence for data retention/settings."""

from __future__ import annotations

from typing import Optional

from quantgambit.settings.models import DataSettings


class DataSettingsStore:
    def __init__(self, pool):
        self.pool = pool

    async def get(self, tenant_id: str) -> Optional[DataSettings]:
        query = (
            "SELECT tenant_id, trade_history_retention_days, replay_snapshot_retention_days, "
            "backtest_history_retention_days, "
            "backtest_equity_sample_every, backtest_max_equity_points, backtest_max_symbol_equity_points, "
            "backtest_max_decision_snapshots, backtest_max_position_snapshots, "
            "capture_decision_traces, capture_feature_values, capture_orderbook "
            "FROM data_settings WHERE tenant_id=$1"
        )
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(query, tenant_id)
        return DataSettings(**dict(row)) if row else None

    async def upsert(self, settings: DataSettings) -> None:
        query = (
            "INSERT INTO data_settings "
            "(tenant_id, trade_history_retention_days, replay_snapshot_retention_days, "
            "backtest_history_retention_days, "
            "backtest_equity_sample_every, backtest_max_equity_points, backtest_max_symbol_equity_points, "
            "backtest_max_decision_snapshots, backtest_max_position_snapshots, "
            "capture_decision_traces, capture_feature_values, capture_orderbook, updated_at) "
            "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,NOW()) "
            "ON CONFLICT (tenant_id) DO UPDATE SET "
            "trade_history_retention_days=EXCLUDED.trade_history_retention_days, "
            "replay_snapshot_retention_days=EXCLUDED.replay_snapshot_retention_days, "
            "backtest_history_retention_days=EXCLUDED.backtest_history_retention_days, "
            "backtest_equity_sample_every=EXCLUDED.backtest_equity_sample_every, "
            "backtest_max_equity_points=EXCLUDED.backtest_max_equity_points, "
            "backtest_max_symbol_equity_points=EXCLUDED.backtest_max_symbol_equity_points, "
            "backtest_max_decision_snapshots=EXCLUDED.backtest_max_decision_snapshots, "
            "backtest_max_position_snapshots=EXCLUDED.backtest_max_position_snapshots, "
            "capture_decision_traces=EXCLUDED.capture_decision_traces, "
            "capture_feature_values=EXCLUDED.capture_feature_values, "
            "capture_orderbook=EXCLUDED.capture_orderbook, "
            "updated_at=NOW()"
        )
        async with self.pool.acquire() as conn:
            await conn.execute(
                query,
                settings.tenant_id,
                settings.trade_history_retention_days,
                settings.replay_snapshot_retention_days,
                settings.backtest_history_retention_days,
                settings.backtest_equity_sample_every,
                settings.backtest_max_equity_points,
                settings.backtest_max_symbol_equity_points,
                settings.backtest_max_decision_snapshots,
                settings.backtest_max_position_snapshots,
                settings.capture_decision_traces,
                settings.capture_feature_values,
                settings.capture_orderbook,
            )
