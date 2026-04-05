"""FastAPI endpoints for backtest metrics."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from fastapi import FastAPI, Depends

from quantgambit.auth.jwt_auth import build_auth_dependency


@dataclass(frozen=True)
class BacktestMetrics:
    run_id: str
    realized_pnl: float
    total_fees: float
    total_trades: int
    win_rate: float
    max_drawdown_pct: float
    avg_slippage_bps: float
    total_return_pct: float
    profit_factor: float
    avg_trade_pnl: float


@dataclass(frozen=True)
class BacktestRun:
    run_id: str
    tenant_id: str
    bot_id: str
    status: str
    started_at: str
    finished_at: Optional[str]
    config: dict


@dataclass(frozen=True)
class BacktestTrade:
    run_id: str
    ts: str
    symbol: str
    side: str
    size: float
    entry_price: float
    exit_price: float
    pnl: float
    entry_fee: float
    exit_fee: float
    total_fees: float
    entry_slippage_bps: float
    exit_slippage_bps: float
    strategy_id: Optional[str]
    profile_id: Optional[str]
    reason: Optional[str]


@dataclass(frozen=True)
class BacktestEquityPoint:
    run_id: str
    ts: str
    equity: float
    realized_pnl: float
    open_positions: int


@dataclass(frozen=True)
class BacktestSymbolEquityPoint:
    run_id: str
    symbol: str
    ts: str
    equity: float
    realized_pnl: float
    open_positions: int


@dataclass(frozen=True)
class BacktestSymbolMetrics:
    run_id: str
    symbol: str
    realized_pnl: float
    total_fees: float
    total_trades: int
    win_rate: float
    avg_trade_pnl: float
    profit_factor: float
    avg_slippage_bps: float


@dataclass(frozen=True)
class BacktestDecisionSnapshot:
    run_id: str
    ts: str
    symbol: str
    decision: str
    rejection_reason: Optional[str]
    profile_id: Optional[str]
    payload: dict


@dataclass(frozen=True)
class BacktestPositionSnapshot:
    run_id: str
    ts: str
    payload: dict


class BacktestAPI:
    """Read-only API for backtest runs/metrics."""

    def __init__(self, pool):
        self.pool = pool
        self.app = FastAPI(title="QuantGambit Backtests", version="v1")
        self._auth = build_auth_dependency()
        self._register_routes()

    def _register_routes(self) -> None:
        @self.app.get("/backtests/runs", response_model=list[BacktestRun], dependencies=[Depends(self._auth)])
        async def list_runs(tenant_id: str, bot_id: str, limit: int = 50):
            query = (
                "SELECT run_id, tenant_id, bot_id, status, started_at, finished_at, config "
                "FROM backtest_runs WHERE tenant_id=$1 AND bot_id=$2 "
                "ORDER BY started_at DESC LIMIT $3"
            )
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(query, tenant_id, bot_id, limit)
            return [BacktestRun(**dict(row)) for row in rows]

        @self.app.get("/backtests/metrics", response_model=list[BacktestMetrics], dependencies=[Depends(self._auth)])
        async def list_metrics(tenant_id: str, bot_id: str, limit: int = 50):
            query = (
                "SELECT r.run_id, m.realized_pnl, m.total_fees, m.total_trades, m.win_rate, "
                "m.max_drawdown_pct, m.avg_slippage_bps, m.total_return_pct, m.profit_factor, m.avg_trade_pnl "
                "FROM backtest_runs r JOIN backtest_metrics m ON r.run_id = m.run_id "
                "WHERE r.tenant_id=$1 AND r.bot_id=$2 "
                "ORDER BY r.started_at DESC LIMIT $3"
            )
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(query, tenant_id, bot_id, limit)
            return [BacktestMetrics(**dict(row)) for row in rows]

        @self.app.get("/backtests/trades", response_model=list[BacktestTrade], dependencies=[Depends(self._auth)])
        async def list_trades(run_id: str, limit: int = 500):
            query = (
                "SELECT run_id, ts, symbol, side, size, entry_price, exit_price, pnl, entry_fee, exit_fee, total_fees, "
                "entry_slippage_bps, exit_slippage_bps, strategy_id, profile_id, reason "
                "FROM backtest_trades WHERE run_id=$1 ORDER BY ts DESC LIMIT $2"
            )
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(query, run_id, limit)
            return [BacktestTrade(**dict(row)) for row in rows]

        @self.app.get("/backtests/equity", response_model=list[BacktestEquityPoint], dependencies=[Depends(self._auth)])
        async def list_equity(run_id: str, limit: int = 1000):
            query = (
                "SELECT run_id, ts, equity, realized_pnl, open_positions "
                "FROM backtest_equity_curve WHERE run_id=$1 ORDER BY ts DESC LIMIT $2"
            )
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(query, run_id, limit)
            return [BacktestEquityPoint(**dict(row)) for row in rows]

        @self.app.get("/backtests/equity/symbols", response_model=list[BacktestSymbolEquityPoint], dependencies=[Depends(self._auth)])
        async def list_symbol_equity(run_id: str, limit: int = 1000, symbol: Optional[str] = None):
            if symbol:
                query = (
                    "SELECT run_id, symbol, ts, equity, realized_pnl, open_positions "
                    "FROM backtest_symbol_equity_curve WHERE run_id=$1 AND symbol=$2 "
                    "ORDER BY ts DESC LIMIT $3"
                )
                args = (run_id, symbol, limit)
            else:
                query = (
                    "SELECT run_id, symbol, ts, equity, realized_pnl, open_positions "
                    "FROM backtest_symbol_equity_curve WHERE run_id=$1 ORDER BY ts DESC LIMIT $2"
                )
                args = (run_id, limit)
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(query, *args)
            return [BacktestSymbolEquityPoint(**dict(row)) for row in rows]

        @self.app.get("/backtests/metrics/symbols", response_model=list[BacktestSymbolMetrics], dependencies=[Depends(self._auth)])
        async def list_symbol_metrics(run_id: str):
            query = (
                "SELECT run_id, symbol, realized_pnl, total_fees, total_trades, win_rate, "
                "avg_trade_pnl, profit_factor, avg_slippage_bps "
                "FROM backtest_symbol_metrics WHERE run_id=$1 ORDER BY symbol"
            )
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(query, run_id)
            return [BacktestSymbolMetrics(**dict(row)) for row in rows]

        @self.app.get("/backtests/decisions", response_model=list[BacktestDecisionSnapshot], dependencies=[Depends(self._auth)])
        async def list_decisions(run_id: str, limit: int = 1000, symbol: Optional[str] = None):
            if symbol:
                query = (
                    "SELECT run_id, ts, symbol, decision, rejection_reason, profile_id, payload "
                    "FROM backtest_decision_snapshots WHERE run_id=$1 AND symbol=$2 "
                    "ORDER BY ts DESC LIMIT $3"
                )
                args = (run_id, symbol, limit)
            else:
                query = (
                    "SELECT run_id, ts, symbol, decision, rejection_reason, profile_id, payload "
                    "FROM backtest_decision_snapshots WHERE run_id=$1 ORDER BY ts DESC LIMIT $2"
                )
                args = (run_id, limit)
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(query, *args)
            return [BacktestDecisionSnapshot(**dict(row)) for row in rows]

        @self.app.get("/backtests/positions", response_model=list[BacktestPositionSnapshot], dependencies=[Depends(self._auth)])
        async def list_positions(run_id: str, limit: int = 1000, symbol: Optional[str] = None):
            query = (
                "SELECT run_id, ts, payload "
                "FROM backtest_position_snapshots WHERE run_id=$1 ORDER BY ts DESC LIMIT $2"
            )
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(query, run_id, limit)
            results = [BacktestPositionSnapshot(**dict(row)) for row in rows]
            if not symbol:
                return results
            filtered: list[BacktestPositionSnapshot] = []
            for snapshot in results:
                payload = snapshot.payload or {}
                positions = payload.get("positions") or []
                matches = [pos for pos in positions if pos.get("symbol") == symbol]
                if not matches:
                    continue
                filtered.append(
                    BacktestPositionSnapshot(
                        run_id=snapshot.run_id,
                        ts=snapshot.ts,
                        payload={**payload, "positions": matches},
                    )
                )
            return filtered
