"""Persistence for backtest runs and metrics."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List


def _parse_datetime(value: Optional[str]) -> Optional[datetime]:
    """Parse a datetime string to a datetime object.
    
    Handles ISO format strings with or without timezone.
    Returns None if value is None or empty.
    """
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    # Backtest callers sometimes provide timestamps as epoch seconds (float/int).
    # Accept those for backwards compatibility with older tests/callers.
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    # Try various ISO formats
    formats = [
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
    ]
    for fmt in formats:
        try:
            dt = datetime.strptime(value, fmt)
            # Add UTC timezone if not present
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue
    # Last resort: try fromisoformat
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        return None


@dataclass(frozen=True)
class BacktestRunRecord:
    """Record for a backtest run."""
    run_id: str
    tenant_id: str
    bot_id: str
    status: str
    started_at: str
    finished_at: Optional[str] = None
    config: Dict[str, Any] = field(default_factory=dict)
    name: Optional[str] = None
    symbol: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    error_message: Optional[str] = None
    created_at: Optional[str] = None
    execution_diagnostics: Optional[Dict[str, Any]] = None


@dataclass(frozen=True)
class BacktestMetricsRecord:
    """Record for backtest metrics."""
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
    # Extended metrics
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    trades_per_day: float = 0.0
    fee_drag_pct: float = 0.0
    slippage_drag_pct: float = 0.0
    gross_profit: float = 0.0
    gross_loss: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    largest_win: float = 0.0
    largest_loss: float = 0.0
    winning_trades: int = 0
    losing_trades: int = 0


@dataclass(frozen=True)
class BacktestTradeRecord:
    """Record for a backtest trade."""
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
    strategy_id: Optional[str] = None
    profile_id: Optional[str] = None
    reason: Optional[str] = None


@dataclass(frozen=True)
class BacktestEquityPoint:
    """Record for an equity curve point."""
    run_id: str
    ts: str
    equity: float
    realized_pnl: float
    open_positions: int


@dataclass(frozen=True)
class BacktestSymbolEquityPoint:
    """Record for a per-symbol equity curve point."""
    run_id: str
    symbol: str
    ts: str
    equity: float
    realized_pnl: float
    open_positions: int


@dataclass(frozen=True)
class BacktestSymbolMetricsRecord:
    """Record for per-symbol metrics."""
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
    """Record for a decision snapshot."""
    run_id: str
    ts: str
    symbol: str
    decision: str
    rejection_reason: Optional[str]
    profile_id: Optional[str]
    payload: Dict[str, Any]


@dataclass(frozen=True)
class BacktestPositionSnapshot:
    """Record for a position snapshot."""
    run_id: str
    ts: str
    payload: Dict[str, Any]


@dataclass(frozen=True)
class WFORunRecord:
    """Record for a walk-forward optimization run."""
    run_id: str
    tenant_id: str
    bot_id: str
    status: str
    profile_id: Optional[str] = None
    symbol: Optional[str] = None
    config: Dict[str, Any] = field(default_factory=dict)
    results: Dict[str, Any] = field(default_factory=dict)
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    created_at: Optional[str] = None
    error_message: Optional[str] = None


class BacktestStore:
    """Postgres store for backtest runs and metrics.
    
    Provides both write and read operations for all backtest-related tables.
    """

    def __init__(self, pool):
        """Initialize the store with a database connection pool.
        
        Args:
            pool: asyncpg connection pool
        """
        self.pool = pool

    # =========================================================================
    # Write Operations
    # =========================================================================

    async def write_run(self, record: BacktestRunRecord) -> None:
        """Write or update a backtest run record.
        
        Feature: backtest-diagnostics
        Requirements: 1.4 - THE Execution_Diagnostics SHALL be stored with the backtest results
        """
        query = (
            "INSERT INTO backtest_runs "
            "(run_id, tenant_id, bot_id, status, started_at, finished_at, config, "
            "name, symbol, start_date, end_date, error_message, created_at, execution_diagnostics) "
            "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,COALESCE($13, NOW()),$14) "
            "ON CONFLICT (run_id) DO UPDATE SET "
            "status=EXCLUDED.status, finished_at=EXCLUDED.finished_at, config=EXCLUDED.config, "
            "name=EXCLUDED.name, symbol=EXCLUDED.symbol, start_date=EXCLUDED.start_date, "
            "end_date=EXCLUDED.end_date, error_message=EXCLUDED.error_message, "
            "execution_diagnostics=COALESCE(EXCLUDED.execution_diagnostics, backtest_runs.execution_diagnostics)"
        )
        async with self.pool.acquire() as conn:
            await conn.execute(
                query,
                record.run_id,
                record.tenant_id,
                record.bot_id,
                record.status,
                _parse_datetime(record.started_at),
                _parse_datetime(record.finished_at),
                json.dumps(record.config) if isinstance(record.config, dict) else record.config,
                record.name,
                record.symbol,
                _parse_datetime(record.start_date),
                _parse_datetime(record.end_date),
                record.error_message,
                _parse_datetime(record.created_at),
                json.dumps(record.execution_diagnostics) if record.execution_diagnostics else None,
            )

    async def write_metrics(self, record: BacktestMetricsRecord) -> None:
        """Write or update backtest metrics."""
        query = (
            "INSERT INTO backtest_metrics "
            "(run_id, realized_pnl, total_fees, total_trades, win_rate, max_drawdown_pct, avg_slippage_bps, "
            "total_return_pct, profit_factor, avg_trade_pnl, sharpe_ratio, sortino_ratio, trades_per_day, "
            "fee_drag_pct, slippage_drag_pct, gross_profit, gross_loss, avg_win, avg_loss, largest_win, "
            "largest_loss, winning_trades, losing_trades) "
            "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20,$21,$22,$23) "
            "ON CONFLICT (run_id) DO UPDATE SET "
            "realized_pnl=EXCLUDED.realized_pnl, total_fees=EXCLUDED.total_fees, total_trades=EXCLUDED.total_trades, "
            "win_rate=EXCLUDED.win_rate, max_drawdown_pct=EXCLUDED.max_drawdown_pct, "
            "avg_slippage_bps=EXCLUDED.avg_slippage_bps, total_return_pct=EXCLUDED.total_return_pct, "
            "profit_factor=EXCLUDED.profit_factor, avg_trade_pnl=EXCLUDED.avg_trade_pnl, "
            "sharpe_ratio=EXCLUDED.sharpe_ratio, sortino_ratio=EXCLUDED.sortino_ratio, "
            "trades_per_day=EXCLUDED.trades_per_day, fee_drag_pct=EXCLUDED.fee_drag_pct, "
            "slippage_drag_pct=EXCLUDED.slippage_drag_pct, gross_profit=EXCLUDED.gross_profit, "
            "gross_loss=EXCLUDED.gross_loss, avg_win=EXCLUDED.avg_win, avg_loss=EXCLUDED.avg_loss, "
            "largest_win=EXCLUDED.largest_win, largest_loss=EXCLUDED.largest_loss, "
            "winning_trades=EXCLUDED.winning_trades, losing_trades=EXCLUDED.losing_trades"
        )
        async with self.pool.acquire() as conn:
            await conn.execute(
                query,
                record.run_id,
                record.realized_pnl,
                record.total_fees,
                record.total_trades,
                record.win_rate,
                record.max_drawdown_pct,
                record.avg_slippage_bps,
                record.total_return_pct,
                record.profit_factor,
                record.avg_trade_pnl,
                record.sharpe_ratio,
                record.sortino_ratio,
                record.trades_per_day,
                record.fee_drag_pct,
                record.slippage_drag_pct,
                record.gross_profit,
                record.gross_loss,
                record.avg_win,
                record.avg_loss,
                record.largest_win,
                record.largest_loss,
                record.winning_trades,
                record.losing_trades,
            )

    async def write_trades(self, trades: List[BacktestTradeRecord]) -> None:
        """Write backtest trades in batch."""
        if not trades:
            return
        query = (
            "INSERT INTO backtest_trades "
            "(run_id, ts, symbol, side, size, entry_price, exit_price, pnl, entry_fee, exit_fee, total_fees, "
            "entry_slippage_bps, exit_slippage_bps, strategy_id, profile_id, reason) "
            "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16)"
        )
        async with self.pool.acquire() as conn:
            for trade in trades:
                await conn.execute(
                    query,
                    trade.run_id,
                    _parse_datetime(trade.ts),
                    trade.symbol,
                    trade.side,
                    trade.size,
                    trade.entry_price,
                    trade.exit_price,
                    trade.pnl,
                    trade.entry_fee,
                    trade.exit_fee,
                    trade.total_fees,
                    trade.entry_slippage_bps,
                    trade.exit_slippage_bps,
                    trade.strategy_id,
                    trade.profile_id,
                    trade.reason,
                )

    async def write_equity_points(self, points: List[BacktestEquityPoint]) -> None:
        """Write equity curve points in batch."""
        if not points:
            return
        query = (
            "INSERT INTO backtest_equity_curve "
            "(run_id, ts, equity, realized_pnl, open_positions) "
            "VALUES ($1,$2,$3,$4,$5)"
        )
        async with self.pool.acquire() as conn:
            for point in points:
                await conn.execute(
                    query,
                    point.run_id,
                    _parse_datetime(point.ts),
                    point.equity,
                    point.realized_pnl,
                    point.open_positions,
                )

    async def write_trade(self, trade: BacktestTradeRecord) -> None:
        """Write a single backtest trade."""
        await self.write_trades([trade])

    async def write_equity_point(self, point: BacktestEquityPoint) -> None:
        """Write a single equity curve point."""
        await self.write_equity_points([point])


    async def write_symbol_equity_points(self, points: List[BacktestSymbolEquityPoint]) -> None:
        """Write per-symbol equity curve points in batch."""
        if not points:
            return
        query = (
            "INSERT INTO backtest_symbol_equity_curve "
            "(run_id, symbol, ts, equity, realized_pnl, open_positions) "
            "VALUES ($1,$2,$3,$4,$5,$6)"
        )
        async with self.pool.acquire() as conn:
            for point in points:
                await conn.execute(
                    query,
                    point.run_id,
                    point.symbol,
                    point.ts,
                    point.equity,
                    point.realized_pnl,
                    point.open_positions,
                )

    async def write_symbol_metrics(self, metrics: List[BacktestSymbolMetricsRecord]) -> None:
        """Write per-symbol metrics in batch."""
        if not metrics:
            return
        query = (
            "INSERT INTO backtest_symbol_metrics "
            "(run_id, symbol, realized_pnl, total_fees, total_trades, win_rate, avg_trade_pnl, "
            "profit_factor, avg_slippage_bps) "
            "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9) "
            "ON CONFLICT (run_id, symbol) DO UPDATE SET "
            "realized_pnl=EXCLUDED.realized_pnl, total_fees=EXCLUDED.total_fees, "
            "total_trades=EXCLUDED.total_trades, win_rate=EXCLUDED.win_rate, "
            "avg_trade_pnl=EXCLUDED.avg_trade_pnl, profit_factor=EXCLUDED.profit_factor, "
            "avg_slippage_bps=EXCLUDED.avg_slippage_bps"
        )
        async with self.pool.acquire() as conn:
            for record in metrics:
                await conn.execute(
                    query,
                    record.run_id,
                    record.symbol,
                    record.realized_pnl,
                    record.total_fees,
                    record.total_trades,
                    record.win_rate,
                    record.avg_trade_pnl,
                    record.profit_factor,
                    record.avg_slippage_bps,
                )

    async def write_decision_snapshots(self, snapshots: List[BacktestDecisionSnapshot]) -> None:
        """Write decision snapshots in batch."""
        if not snapshots:
            return
        query = (
            "INSERT INTO backtest_decision_snapshots "
            "(run_id, ts, symbol, decision, rejection_reason, profile_id, payload) "
            "VALUES ($1,$2,$3,$4,$5,$6,$7)"
        )
        async with self.pool.acquire() as conn:
            for snapshot in snapshots:
                await conn.execute(
                    query,
                    snapshot.run_id,
                    snapshot.ts,
                    snapshot.symbol,
                    snapshot.decision,
                    snapshot.rejection_reason,
                    snapshot.profile_id,
                    json.dumps(snapshot.payload) if isinstance(snapshot.payload, dict) else snapshot.payload,
                )

    async def write_position_snapshots(self, snapshots: List[BacktestPositionSnapshot]) -> None:
        """Write position snapshots in batch."""
        if not snapshots:
            return
        query = (
            "INSERT INTO backtest_position_snapshots "
            "(run_id, ts, payload) "
            "VALUES ($1,$2,$3)"
        )
        async with self.pool.acquire() as conn:
            for snapshot in snapshots:
                await conn.execute(
                    query,
                    snapshot.run_id,
                    snapshot.ts,
                    json.dumps(snapshot.payload) if isinstance(snapshot.payload, dict) else snapshot.payload,
                )

    async def write_quality_metrics(
        self,
        run_id: str,
        data_quality_grade: str,
        data_completeness_pct: float,
        total_gaps: int,
        critical_gaps: int,
        missing_price_count: int,
        missing_depth_count: int,
        quality_warnings: List[str],
    ) -> None:
        """Write data quality metrics for a backtest run.
        
        Feature: backtest-data-validation
        Requirements: 5.1, 5.2, 5.3, 7.5
        
        Args:
            run_id: Backtest run ID
            data_quality_grade: Quality grade (A, B, C, D, F)
            data_completeness_pct: Overall data completeness percentage
            total_gaps: Total number of gaps detected
            critical_gaps: Number of critical gaps
            missing_price_count: Count of snapshots missing price data
            missing_depth_count: Count of snapshots missing depth data
            quality_warnings: List of warning messages
        """
        query = """
            INSERT INTO backtest_quality_metrics 
            (run_id, data_quality_grade, data_completeness_pct, total_gaps, critical_gaps,
             missing_price_count, missing_depth_count, quality_warnings)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            ON CONFLICT (run_id) DO UPDATE SET
            data_quality_grade = EXCLUDED.data_quality_grade,
            data_completeness_pct = EXCLUDED.data_completeness_pct,
            total_gaps = EXCLUDED.total_gaps,
            critical_gaps = EXCLUDED.critical_gaps,
            missing_price_count = EXCLUDED.missing_price_count,
            missing_depth_count = EXCLUDED.missing_depth_count,
            quality_warnings = EXCLUDED.quality_warnings
        """
        async with self.pool.acquire() as conn:
            await conn.execute(
                query,
                run_id,
                data_quality_grade,
                data_completeness_pct,
                total_gaps,
                critical_gaps,
                missing_price_count,
                missing_depth_count,
                json.dumps(quality_warnings),
            )

    async def get_quality_metrics(self, run_id: str) -> Optional[Dict[str, Any]]:
        """Get quality metrics for a backtest run.
        
        Feature: backtest-data-validation
        Requirements: 5.1, 5.2
        
        Args:
            run_id: Backtest run ID
            
        Returns:
            Dict with quality metrics or None if not found
        """
        query = """
            SELECT run_id, data_quality_grade, data_completeness_pct, total_gaps, critical_gaps,
                   missing_price_count, missing_depth_count, quality_warnings
            FROM backtest_quality_metrics
            WHERE run_id = $1
        """
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(query, run_id)
            if not row:
                return None
            
            warnings = row["quality_warnings"]
            if isinstance(warnings, str):
                try:
                    warnings = json.loads(warnings)
                except (json.JSONDecodeError, TypeError):
                    warnings = []
            
            return {
                "run_id": str(row["run_id"]),
                "data_quality_grade": row["data_quality_grade"],
                "data_completeness_pct": float(row["data_completeness_pct"]),
                "total_gaps": int(row["total_gaps"]),
                "critical_gaps": int(row["critical_gaps"]),
                "missing_price_count": int(row["missing_price_count"]),
                "missing_depth_count": int(row["missing_depth_count"]),
                "quality_warnings": warnings or [],
            }

    async def has_quality_metrics(self, run_id: str) -> bool:
        """Check if quality metrics exist for a backtest run."""
        query = "SELECT 1 FROM backtest_quality_metrics WHERE run_id = $1"
        async with self.pool.acquire() as conn:
            result = await conn.fetchval(query, run_id)
            return result is not None

    # =========================================================================
    # Read Operations
    # =========================================================================

    async def get_run(self, run_id: str) -> Optional[BacktestRunRecord]:
        """Get a backtest run by ID.
        
        Feature: backtest-diagnostics
        Requirements: 1.4 - Returns execution_diagnostics with the backtest results
        """
        query = (
            "SELECT run_id, tenant_id, bot_id, status, started_at, finished_at, config, "
            "name, symbol, start_date, end_date, error_message, created_at, execution_diagnostics "
            "FROM backtest_runs WHERE run_id = $1"
        )
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(query, run_id)
            if not row:
                return None
            
            # Parse config - handle both dict and string
            config = row["config"]
            if isinstance(config, str):
                try:
                    config = json.loads(config)
                except (json.JSONDecodeError, TypeError):
                    config = {}
            elif config is None:
                config = {}
            
            # Parse execution_diagnostics - handle both dict and string
            execution_diagnostics = row.get("execution_diagnostics")
            if isinstance(execution_diagnostics, str):
                try:
                    execution_diagnostics = json.loads(execution_diagnostics)
                except (json.JSONDecodeError, TypeError):
                    execution_diagnostics = None
            
            return BacktestRunRecord(
                run_id=str(row["run_id"]),
                tenant_id=row["tenant_id"],
                bot_id=row["bot_id"],
                status=row["status"],
                started_at=row["started_at"].isoformat() if row["started_at"] else None,
                finished_at=row["finished_at"].isoformat() if row["finished_at"] else None,
                config=config,
                name=row["name"],
                symbol=row["symbol"],
                start_date=row["start_date"].isoformat() if row["start_date"] else None,
                end_date=row["end_date"].isoformat() if row["end_date"] else None,
                error_message=row["error_message"],
                created_at=row["created_at"].isoformat() if row["created_at"] else None,
                execution_diagnostics=execution_diagnostics,
            )


    async def list_runs(
        self,
        tenant_id: Optional[str] = None,
        status: Optional[str] = None,
        symbol: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[BacktestRunRecord]:
        """List backtest runs with optional filtering.
        
        Feature: backtest-diagnostics
        Requirements: 1.4 - Returns execution_diagnostics with the backtest results
        """
        conditions = []
        params = []
        param_idx = 1
        
        if tenant_id:
            conditions.append(f"tenant_id = ${param_idx}")
            params.append(tenant_id)
            param_idx += 1
        if status:
            conditions.append(f"status = ${param_idx}")
            params.append(status)
            param_idx += 1
        if symbol:
            conditions.append(f"symbol = ${param_idx}")
            params.append(symbol)
            param_idx += 1
        
        where_clause = " AND ".join(conditions) if conditions else "1=1"
        
        query = f"""
            SELECT run_id, tenant_id, bot_id, status, started_at, finished_at, config,
                   name, symbol, start_date, end_date, error_message, created_at, execution_diagnostics
            FROM backtest_runs
            WHERE {where_clause}
            ORDER BY started_at DESC
            LIMIT ${param_idx} OFFSET ${param_idx + 1}
        """
        params.extend([limit, offset])
        
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(query, *params)
            results = []
            for row in rows:
                # Parse config - handle both dict and string
                config = row["config"]
                if isinstance(config, str):
                    try:
                        config = json.loads(config)
                    except (json.JSONDecodeError, TypeError):
                        config = {}
                elif config is None:
                    config = {}
                
                # Parse execution_diagnostics - handle both dict and string
                execution_diagnostics = row.get("execution_diagnostics")
                if isinstance(execution_diagnostics, str):
                    try:
                        execution_diagnostics = json.loads(execution_diagnostics)
                    except (json.JSONDecodeError, TypeError):
                        execution_diagnostics = None
                
                results.append(BacktestRunRecord(
                    run_id=str(row["run_id"]),
                    tenant_id=row["tenant_id"],
                    bot_id=row["bot_id"],
                    status=row["status"],
                    started_at=row["started_at"].isoformat() if row["started_at"] else None,
                    finished_at=row["finished_at"].isoformat() if row["finished_at"] else None,
                    config=config,
                    name=row["name"],
                    symbol=row["symbol"],
                    start_date=row["start_date"].isoformat() if row["start_date"] else None,
                    end_date=row["end_date"].isoformat() if row["end_date"] else None,
                    error_message=row["error_message"],
                    created_at=row["created_at"].isoformat() if row["created_at"] else None,
                    execution_diagnostics=execution_diagnostics,
                ))
            return results

    async def count_runs(
        self,
        tenant_id: Optional[str] = None,
        status: Optional[str] = None,
        symbol: Optional[str] = None,
    ) -> int:
        """Count backtest runs with optional filtering."""
        conditions = []
        params = []
        param_idx = 1
        
        if tenant_id:
            conditions.append(f"tenant_id = ${param_idx}")
            params.append(tenant_id)
            param_idx += 1
        if status:
            conditions.append(f"status = ${param_idx}")
            params.append(status)
            param_idx += 1
        if symbol:
            conditions.append(f"symbol = ${param_idx}")
            params.append(symbol)
            param_idx += 1
        
        where_clause = " AND ".join(conditions) if conditions else "1=1"
        query = f"SELECT COUNT(*) FROM backtest_runs WHERE {where_clause}"
        
        async with self.pool.acquire() as conn:
            return await conn.fetchval(query, *params)

    async def get_metrics(self, run_id: str) -> Optional[BacktestMetricsRecord]:
        """Get metrics for a backtest run."""
        query = (
            "SELECT run_id, realized_pnl, total_fees, total_trades, win_rate, "
            "max_drawdown_pct, avg_slippage_bps, total_return_pct, profit_factor, avg_trade_pnl, "
            "COALESCE(sharpe_ratio, 0) as sharpe_ratio, COALESCE(sortino_ratio, 0) as sortino_ratio, "
            "COALESCE(trades_per_day, 0) as trades_per_day, COALESCE(fee_drag_pct, 0) as fee_drag_pct, "
            "COALESCE(slippage_drag_pct, 0) as slippage_drag_pct, COALESCE(gross_profit, 0) as gross_profit, "
            "COALESCE(gross_loss, 0) as gross_loss, COALESCE(avg_win, 0) as avg_win, "
            "COALESCE(avg_loss, 0) as avg_loss, COALESCE(largest_win, 0) as largest_win, "
            "COALESCE(largest_loss, 0) as largest_loss, COALESCE(winning_trades, 0) as winning_trades, "
            "COALESCE(losing_trades, 0) as losing_trades "
            "FROM backtest_metrics WHERE run_id = $1"
        )
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(query, run_id)
            if not row:
                return None
            return BacktestMetricsRecord(
                run_id=str(row["run_id"]),
                realized_pnl=float(row["realized_pnl"]),
                total_fees=float(row["total_fees"]),
                total_trades=int(row["total_trades"]),
                win_rate=float(row["win_rate"]),
                max_drawdown_pct=float(row["max_drawdown_pct"]),
                avg_slippage_bps=float(row["avg_slippage_bps"]),
                total_return_pct=float(row["total_return_pct"]),
                profit_factor=float(row["profit_factor"]),
                avg_trade_pnl=float(row["avg_trade_pnl"]),
                sharpe_ratio=float(row["sharpe_ratio"]),
                sortino_ratio=float(row["sortino_ratio"]),
                trades_per_day=float(row["trades_per_day"]),
                fee_drag_pct=float(row["fee_drag_pct"]),
                slippage_drag_pct=float(row["slippage_drag_pct"]),
                gross_profit=float(row["gross_profit"]),
                gross_loss=float(row["gross_loss"]),
                avg_win=float(row["avg_win"]),
                avg_loss=float(row["avg_loss"]),
                largest_win=float(row["largest_win"]),
                largest_loss=float(row["largest_loss"]),
                winning_trades=int(row["winning_trades"]),
                losing_trades=int(row["losing_trades"]),
            )

    async def get_trades(self, run_id: str, limit: int = 1000) -> List[BacktestTradeRecord]:
        """Get trades for a backtest run."""
        query = (
            "SELECT run_id, ts, symbol, side, size, entry_price, exit_price, pnl, "
            "entry_fee, exit_fee, total_fees, entry_slippage_bps, exit_slippage_bps, "
            "strategy_id, profile_id, reason "
            "FROM backtest_trades WHERE run_id = $1 ORDER BY ts LIMIT $2"
        )
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(query, run_id, limit)
            return [
                BacktestTradeRecord(
                    run_id=str(row["run_id"]),
                    ts=row["ts"].isoformat() if row["ts"] else None,
                    symbol=row["symbol"],
                    side=row["side"],
                    size=float(row["size"]),
                    entry_price=float(row["entry_price"]),
                    exit_price=float(row["exit_price"]),
                    pnl=float(row["pnl"]),
                    entry_fee=float(row["entry_fee"]),
                    exit_fee=float(row["exit_fee"]),
                    total_fees=float(row["total_fees"]),
                    entry_slippage_bps=float(row["entry_slippage_bps"]),
                    exit_slippage_bps=float(row["exit_slippage_bps"]),
                    strategy_id=row["strategy_id"],
                    profile_id=row["profile_id"],
                    reason=row["reason"],
                )
                for row in rows
            ]


    async def get_equity_curve(self, run_id: str, limit: int = 10000) -> List[BacktestEquityPoint]:
        """Get equity curve for a backtest run."""
        query = (
            "SELECT run_id, ts, equity, realized_pnl, open_positions "
            "FROM backtest_equity_curve WHERE run_id = $1 ORDER BY ts LIMIT $2"
        )
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(query, run_id, limit)
            return [
                BacktestEquityPoint(
                    run_id=str(row["run_id"]),
                    ts=row["ts"].isoformat() if row["ts"] else None,
                    equity=float(row["equity"]),
                    realized_pnl=float(row["realized_pnl"]),
                    open_positions=int(row["open_positions"]),
                )
                for row in rows
            ]

    async def get_decision_snapshots(self, run_id: str, limit: int = 10000) -> List[BacktestDecisionSnapshot]:
        """Get decision snapshots for a backtest run."""
        query = (
            "SELECT run_id, ts, symbol, decision, rejection_reason, profile_id, payload "
            "FROM backtest_decision_snapshots WHERE run_id = $1 ORDER BY ts LIMIT $2"
        )
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(query, run_id, limit)
            return [
                BacktestDecisionSnapshot(
                    run_id=str(row["run_id"]),
                    ts=row["ts"].isoformat() if row["ts"] else None,
                    symbol=row["symbol"],
                    decision=row["decision"],
                    rejection_reason=row["rejection_reason"],
                    profile_id=row["profile_id"],
                    payload=row["payload"] if row["payload"] else {},
                )
                for row in rows
            ]

    async def update_run_status(
        self,
        run_id: str,
        status: str,
        error_message: Optional[str] = None,
        finished_at: Optional[str] = None,
    ) -> bool:
        """Update the status of a backtest run.
        
        Returns True if the run was found and updated, False otherwise.
        """
        query = """
            UPDATE backtest_runs 
            SET status = $2, error_message = COALESCE($3, error_message),
                finished_at = COALESCE($4, finished_at)
            WHERE run_id = $1
        """
        async with self.pool.acquire() as conn:
            result = await conn.execute(query, run_id, status, error_message, finished_at)
            return result != "UPDATE 0"

    async def write_execution_diagnostics(
        self,
        run_id: str,
        diagnostics: Dict[str, Any],
    ) -> bool:
        """Write or update execution diagnostics for a backtest run.
        
        Feature: backtest-diagnostics
        Requirements: 1.4 - THE Execution_Diagnostics SHALL be stored with the backtest results
        
        Args:
            run_id: Backtest run ID
            diagnostics: Execution diagnostics dict containing:
                - total_snapshots: int
                - snapshots_processed: int
                - snapshots_skipped: int
                - global_gate_rejections: int
                - rejection_breakdown: Dict[str, int]
                - profiles_selected: int
                - signals_generated: int
                - cooldown_rejections: int
                - summary: str
                - primary_issue: Optional[str]
                - suggestions: List[str]
        
        Returns:
            True if the run was found and updated, False otherwise.
        """
        query = """
            UPDATE backtest_runs 
            SET execution_diagnostics = $2
            WHERE run_id = $1
        """
        async with self.pool.acquire() as conn:
            diagnostics_json = json.dumps(diagnostics) if isinstance(diagnostics, dict) else diagnostics
            result = await conn.execute(query, run_id, diagnostics_json)
            return result != "UPDATE 0"

    async def get_execution_diagnostics(self, run_id: str) -> Optional[Dict[str, Any]]:
        """Get execution diagnostics for a backtest run.
        
        Feature: backtest-diagnostics
        Requirements: 1.4 - Returns execution_diagnostics stored with the backtest results
        
        Args:
            run_id: Backtest run ID
            
        Returns:
            Dict with execution diagnostics or None if not found
        """
        query = "SELECT execution_diagnostics FROM backtest_runs WHERE run_id = $1"
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(query, run_id)
            if not row:
                return None
            
            diagnostics = row["execution_diagnostics"]
            if isinstance(diagnostics, str):
                try:
                    return json.loads(diagnostics)
                except (json.JSONDecodeError, TypeError):
                    return None
            return diagnostics

    async def has_execution_diagnostics(self, run_id: str) -> bool:
        """Check if execution diagnostics exist for a backtest run.
        
        Feature: backtest-diagnostics
        Requirements: 1.4
        """
        query = "SELECT 1 FROM backtest_runs WHERE run_id = $1 AND execution_diagnostics IS NOT NULL"
        async with self.pool.acquire() as conn:
            result = await conn.fetchval(query, run_id)
            return result is not None

    async def delete_run(self, run_id: str) -> bool:
        """Delete a backtest run and all associated data.
        
        Returns True if the run was found and deleted, False otherwise.
        """
        query = "DELETE FROM backtest_runs WHERE run_id = $1"
        async with self.pool.acquire() as conn:
            result = await conn.execute(query, run_id)
            return result != "DELETE 0"

    async def run_exists(self, run_id: str) -> bool:
        """Check if a backtest run exists."""
        query = "SELECT 1 FROM backtest_runs WHERE run_id = $1"
        async with self.pool.acquire() as conn:
            result = await conn.fetchval(query, run_id)
            return result is not None

    async def has_metrics(self, run_id: str) -> bool:
        """Check if metrics exist for a backtest run."""
        query = "SELECT 1 FROM backtest_metrics WHERE run_id = $1"
        async with self.pool.acquire() as conn:
            result = await conn.fetchval(query, run_id)
            return result is not None

    async def has_trades(self, run_id: str) -> bool:
        """Check if trades exist for a backtest run."""
        query = "SELECT 1 FROM backtest_trades WHERE run_id = $1 LIMIT 1"
        async with self.pool.acquire() as conn:
            result = await conn.fetchval(query, run_id)
            return result is not None

    async def has_equity_curve(self, run_id: str) -> bool:
        """Check if equity curve exists for a backtest run."""
        query = "SELECT 1 FROM backtest_equity_curve WHERE run_id = $1 LIMIT 1"
        async with self.pool.acquire() as conn:
            result = await conn.fetchval(query, run_id)
            return result is not None

    async def has_decision_snapshots(self, run_id: str) -> bool:
        """Check if decision snapshots exist for a backtest run."""
        query = "SELECT 1 FROM backtest_decision_snapshots WHERE run_id = $1 LIMIT 1"
        async with self.pool.acquire() as conn:
            result = await conn.fetchval(query, run_id)
            return result is not None

    async def verify_result_persistence(self, run_id: str) -> Dict[str, bool]:
        """Verify that all result tables contain data for a run.
        
        Returns a dict with table names as keys and boolean values indicating
        whether data exists in each table.
        
        This is useful for validating Property 11: Result Persistence.
        """
        return {
            "runs": await self.run_exists(run_id),
            "metrics": await self.has_metrics(run_id),
            "trades": await self.has_trades(run_id),
            "equity_curve": await self.has_equity_curve(run_id),
            "decision_snapshots": await self.has_decision_snapshots(run_id),
        }

    # =========================================================================
    # WFO (Walk-Forward Optimization) Operations
    # =========================================================================

    async def write_wfo_run(self, record: WFORunRecord) -> None:
        """Write or update a WFO run record."""
        query = (
            "INSERT INTO wfo_runs "
            "(run_id, tenant_id, bot_id, profile_id, symbol, status, config, results, "
            "started_at, finished_at, created_at) "
            "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,COALESCE($11, NOW())) "
            "ON CONFLICT (run_id) DO UPDATE SET "
            "status=EXCLUDED.status, config=EXCLUDED.config, results=EXCLUDED.results, "
            "finished_at=EXCLUDED.finished_at"
        )
        async with self.pool.acquire() as conn:
            await conn.execute(
                query,
                record.run_id,
                record.tenant_id,
                record.bot_id,
                record.profile_id,
                record.symbol,
                record.status,
                json.dumps(record.config) if isinstance(record.config, dict) else record.config,
                json.dumps(record.results) if isinstance(record.results, dict) else record.results,
                record.started_at,
                record.finished_at,
                record.created_at,
            )

    async def get_wfo_run(self, run_id: str) -> Optional[WFORunRecord]:
        """Get a WFO run by ID."""
        query = (
            "SELECT run_id, tenant_id, bot_id, profile_id, symbol, status, config, results, "
            "started_at, finished_at, created_at "
            "FROM wfo_runs WHERE run_id = $1"
        )
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(query, run_id)
            if not row:
                return None
            return WFORunRecord(
                run_id=str(row["run_id"]),
                tenant_id=row["tenant_id"],
                bot_id=row["bot_id"],
                profile_id=row["profile_id"],
                symbol=row["symbol"],
                status=row["status"],
                config=row["config"] if row["config"] else {},
                results=row["results"] if row["results"] else {},
                started_at=row["started_at"].isoformat() if row["started_at"] else None,
                finished_at=row["finished_at"].isoformat() if row["finished_at"] else None,
                created_at=row["created_at"].isoformat() if row["created_at"] else None,
            )

    async def list_wfo_runs(
        self,
        tenant_id: Optional[str] = None,
        profile_id: Optional[str] = None,
        symbol: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[WFORunRecord]:
        """List WFO runs with optional filtering."""
        conditions = []
        params = []
        param_idx = 1
        
        if tenant_id:
            conditions.append(f"tenant_id = ${param_idx}")
            params.append(tenant_id)
            param_idx += 1
        if profile_id:
            conditions.append(f"profile_id = ${param_idx}")
            params.append(profile_id)
            param_idx += 1
        if symbol:
            conditions.append(f"symbol = ${param_idx}")
            params.append(symbol)
            param_idx += 1
        if status:
            conditions.append(f"status = ${param_idx}")
            params.append(status)
            param_idx += 1
        
        where_clause = " AND ".join(conditions) if conditions else "1=1"
        
        query = f"""
            SELECT run_id, tenant_id, bot_id, profile_id, symbol, status, config, results,
                   started_at, finished_at, created_at
            FROM wfo_runs
            WHERE {where_clause}
            ORDER BY created_at DESC
            LIMIT ${param_idx} OFFSET ${param_idx + 1}
        """
        params.extend([limit, offset])
        
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(query, *params)
            return [
                WFORunRecord(
                    run_id=str(row["run_id"]),
                    tenant_id=row["tenant_id"],
                    bot_id=row["bot_id"],
                    profile_id=row["profile_id"],
                    symbol=row["symbol"],
                    status=row["status"],
                    config=row["config"] if row["config"] else {},
                    results=row["results"] if row["results"] else {},
                    started_at=row["started_at"].isoformat() if row["started_at"] else None,
                    finished_at=row["finished_at"].isoformat() if row["finished_at"] else None,
                    created_at=row["created_at"].isoformat() if row["created_at"] else None,
                )
                for row in rows
            ]

    async def count_wfo_runs(
        self,
        tenant_id: Optional[str] = None,
        profile_id: Optional[str] = None,
        symbol: Optional[str] = None,
        status: Optional[str] = None,
    ) -> int:
        """Count WFO runs with optional filtering."""
        conditions = []
        params = []
        param_idx = 1
        
        if tenant_id:
            conditions.append(f"tenant_id = ${param_idx}")
            params.append(tenant_id)
            param_idx += 1
        if profile_id:
            conditions.append(f"profile_id = ${param_idx}")
            params.append(profile_id)
            param_idx += 1
        if symbol:
            conditions.append(f"symbol = ${param_idx}")
            params.append(symbol)
            param_idx += 1
        if status:
            conditions.append(f"status = ${param_idx}")
            params.append(status)
            param_idx += 1
        
        where_clause = " AND ".join(conditions) if conditions else "1=1"
        query = f"SELECT COUNT(*) FROM wfo_runs WHERE {where_clause}"
        
        async with self.pool.acquire() as conn:
            return await conn.fetchval(query, *params)

    async def update_wfo_run_status(
        self,
        run_id: str,
        status: str,
        results: Optional[Dict[str, Any]] = None,
        error_message: Optional[str] = None,
        finished_at: Optional[str] = None,
    ) -> bool:
        """Update the status of a WFO run.
        
        Returns True if the run was found and updated, False otherwise.
        """
        # Build dynamic update query based on provided fields
        set_clauses = ["status = $2"]
        params = [run_id, status]
        param_idx = 3
        
        if results is not None:
            set_clauses.append(f"results = ${param_idx}")
            params.append(json.dumps(results) if isinstance(results, dict) else results)
            param_idx += 1
        
        if finished_at is not None:
            set_clauses.append(f"finished_at = ${param_idx}")
            params.append(finished_at)
            param_idx += 1
        
        query = f"""
            UPDATE wfo_runs 
            SET {", ".join(set_clauses)}
            WHERE run_id = $1
        """
        async with self.pool.acquire() as conn:
            result = await conn.execute(query, *params)
            return result != "UPDATE 0"

    async def wfo_run_exists(self, run_id: str) -> bool:
        """Check if a WFO run exists."""
        query = "SELECT 1 FROM wfo_runs WHERE run_id = $1"
        async with self.pool.acquire() as conn:
            result = await conn.fetchval(query, run_id)
            return result is not None
