"""Retention cleanup for backtest snapshot tables."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import os
from typing import Optional

from quantgambit.observability.logger import log_info, log_warning


@dataclass
class BacktestRetentionConfig:
    snapshot_retention_days: int = 30
    history_retention_days: int = 365
    interval_seconds: int = 3600

    @classmethod
    def from_env(cls) -> "BacktestRetentionConfig":
        return cls(
            snapshot_retention_days=int(os.getenv("BACKTEST_SNAPSHOT_RETENTION_DAYS", "30")),
            history_retention_days=int(os.getenv("BACKTEST_HISTORY_RETENTION_DAYS", "365")),
            interval_seconds=int(os.getenv("BACKTEST_RETENTION_INTERVAL_SEC", "3600")),
        )


class BacktestRetentionWorker:
    """Deletes old backtest snapshots on a schedule."""

    def __init__(self, pool, config: Optional[BacktestRetentionConfig] = None):
        self.pool = pool
        self.config = config or BacktestRetentionConfig()

    async def prune(self) -> None:
        tenant_retention = await self._load_tenant_retentions()
        if not tenant_retention:
            return
        async with self.pool.acquire() as conn:
            for tenant_id, retention in tenant_retention.items():
                snapshot_days = retention["snapshots"]
                history_days = retention["history"]
                if snapshot_days <= 0:
                    log_warning(
                        "backtest_retention_disabled",
                        tenant_id=tenant_id,
                        reason="snapshot_retention_days <= 0",
                    )
                else:
                    cutoff = datetime.now(timezone.utc) - timedelta(days=snapshot_days)
                    cutoff_iso = cutoff.isoformat().replace("+00:00", "Z")
                    await conn.execute(
                        "DELETE FROM backtest_decision_snapshots USING backtest_runs "
                        "WHERE backtest_decision_snapshots.run_id = backtest_runs.run_id "
                        "AND backtest_runs.tenant_id = $1 AND backtest_decision_snapshots.ts < $2",
                        tenant_id,
                        cutoff_iso,
                    )
                    await conn.execute(
                        "DELETE FROM backtest_position_snapshots USING backtest_runs "
                        "WHERE backtest_position_snapshots.run_id = backtest_runs.run_id "
                        "AND backtest_runs.tenant_id = $1 AND backtest_position_snapshots.ts < $2",
                        tenant_id,
                        cutoff_iso,
                    )
                    await conn.execute(
                        "DELETE FROM backtest_equity_curve USING backtest_runs "
                        "WHERE backtest_equity_curve.run_id = backtest_runs.run_id "
                        "AND backtest_runs.tenant_id = $1 AND backtest_equity_curve.ts < $2",
                        tenant_id,
                        cutoff_iso,
                    )
                    await conn.execute(
                        "DELETE FROM backtest_symbol_equity_curve USING backtest_runs "
                        "WHERE backtest_symbol_equity_curve.run_id = backtest_runs.run_id "
                        "AND backtest_runs.tenant_id = $1 AND backtest_symbol_equity_curve.ts < $2",
                        tenant_id,
                        cutoff_iso,
                    )
                    log_info(
                        "backtest_snapshot_retention_pruned",
                        tenant_id=tenant_id,
                        cutoff=cutoff_iso,
                    )
                if history_days <= 0:
                    log_warning(
                        "backtest_history_retention_disabled",
                        tenant_id=tenant_id,
                        reason="history_retention_days <= 0",
                    )
                    continue
                if history_days < snapshot_days:
                    log_warning(
                        "backtest_history_retention_lt_snapshot",
                        tenant_id=tenant_id,
                        history_days=history_days,
                        snapshot_days=snapshot_days,
                    )
                    history_days = snapshot_days
                history_cutoff = datetime.now(timezone.utc) - timedelta(days=history_days)
                history_cutoff_iso = history_cutoff.isoformat().replace("+00:00", "Z")
                await conn.execute(
                    "DELETE FROM backtest_runs "
                    "WHERE tenant_id = $1 AND finished_at IS NOT NULL AND finished_at < $2",
                    tenant_id,
                    history_cutoff_iso,
                )
                log_info(
                    "backtest_history_retention_pruned",
                    tenant_id=tenant_id,
                    cutoff=history_cutoff_iso,
                )

    async def run_forever(self) -> None:
        while True:
            await self.prune()
            await asyncio.sleep(self.config.interval_seconds)

    async def _load_tenant_retentions(self) -> dict[str, dict[str, int]]:
        default_snapshot_days = self.config.snapshot_retention_days
        default_history_days = self.config.history_retention_days
        if default_snapshot_days <= 0 and default_history_days <= 0:
            log_warning("backtest_retention_disabled", reason="both defaults <= 0")
            return {}
        async with self.pool.acquire() as conn:
            tenants = await conn.fetch("SELECT DISTINCT tenant_id FROM backtest_runs")
            settings = await conn.fetch(
                "SELECT tenant_id, replay_snapshot_retention_days, backtest_history_retention_days "
                "FROM data_settings"
            )
        retention_by_tenant = {
            row["tenant_id"]: {"snapshots": default_snapshot_days, "history": default_history_days}
            for row in tenants
        }
        for row in settings:
            tenant_id = row["tenant_id"]
            snapshot_days = row["replay_snapshot_retention_days"]
            history_days = row["backtest_history_retention_days"]
            entry = retention_by_tenant.setdefault(
                tenant_id,
                {"snapshots": default_snapshot_days, "history": default_history_days},
            )
            if snapshot_days is not None:
                entry["snapshots"] = int(snapshot_days)
            if history_days is not None:
                entry["history"] = int(history_days)
        return retention_by_tenant
