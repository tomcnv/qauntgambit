"""Data settings models."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class DataSettings:
    tenant_id: str
    trade_history_retention_days: Optional[int]
    replay_snapshot_retention_days: Optional[int]
    backtest_history_retention_days: Optional[int]
    backtest_equity_sample_every: int
    backtest_max_equity_points: int
    backtest_max_symbol_equity_points: int
    backtest_max_decision_snapshots: int
    backtest_max_position_snapshots: int
    capture_decision_traces: bool
    capture_feature_values: bool
    capture_orderbook: bool
