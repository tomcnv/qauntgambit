"""
Property-based tests for BacktestStore.

Feature: backtesting-api-integration, Property 11: Result Persistence
Validates: Requirements R5.3

Tests that for any completed backtest, all result tables (runs, metrics,
equity_curve, trades, decision_snapshots) contain data for that run_id.
"""

import json
import uuid
import pytest
from datetime import datetime, timezone, timedelta
from hypothesis import given, strategies as st, settings, assume
from unittest.mock import AsyncMock, MagicMock
from typing import Dict, Any, List, Optional

from quantgambit.backtesting.store import (
    BacktestStore,
    BacktestRunRecord,
    BacktestMetricsRecord,
    BacktestTradeRecord,
    BacktestEquityPoint,
    BacktestDecisionSnapshot,
)


# ============================================================================
# Mock Database Pool
# ============================================================================

class MockConnection:
    """Mock database connection for testing."""
    
    def __init__(self, storage: Dict[str, Dict[str, Any]]):
        self.storage = storage
    
    async def execute(self, query: str, *args) -> str:
        """Mock execute that stores data in memory."""
        table = self._extract_table(query)
        if not table:
            return "EXECUTE 0"
        
        if "INSERT INTO" in query:
            run_id = str(args[0])
            if table not in self.storage:
                self.storage[table] = {}
            if run_id not in self.storage[table]:
                self.storage[table][run_id] = []
            self.storage[table][run_id].append(args)
            return "INSERT 1"
        elif "UPDATE" in query:
            run_id = str(args[0])
            if table in self.storage and run_id in self.storage[table]:
                # Update the status in the stored record
                if table == "backtest_runs" and self.storage[table][run_id]:
                    old_args = list(self.storage[table][run_id][0])
                    
                    # Check if this is an execution_diagnostics update
                    if "execution_diagnostics" in query and "status" not in query:
                        # args[1] is the diagnostics JSON
                        if len(old_args) > 13:
                            old_args[13] = args[1]
                        else:
                            # Extend the args to include diagnostics
                            while len(old_args) < 14:
                                old_args.append(None)
                            old_args[13] = args[1]
                    else:
                        # args[1] is the new status for update_run_status
                        old_args[3] = args[1]  # status is at index 3
                        # args[2] is error_message, args[3] is finished_at
                        if len(args) > 2 and args[2] is not None:
                            old_args[11] = args[2]  # error_message at index 11
                        if len(args) > 3 and args[3] is not None:
                            old_args[5] = args[3]  # finished_at at index 5
                    self.storage[table][run_id][0] = tuple(old_args)
                return "UPDATE 1"
            return "UPDATE 0"
        elif "DELETE FROM" in query:
            run_id = str(args[0])
            if table in self.storage and run_id in self.storage[table]:
                del self.storage[table][run_id]
                return "DELETE 1"
            return "DELETE 0"
        return "EXECUTE 0"
    
    async def fetchrow(self, query: str, *args) -> Optional[Dict]:
        """Mock fetchrow that retrieves data from memory."""
        table = self._extract_table(query)
        if not table:
            return None
        
        run_id = str(args[0])
        if table not in self.storage or run_id not in self.storage[table]:
            return None
        
        data = self.storage[table][run_id]
        if not data:
            return None
        
        # Return the first record as a dict-like object
        return self._args_to_row(table, data[0])
    
    async def fetch(self, query: str, *args) -> List[Dict]:
        """Mock fetch that retrieves multiple rows."""
        table = self._extract_table(query)
        if not table:
            return []
        
        run_id = str(args[0])
        if table not in self.storage or run_id not in self.storage[table]:
            return []
        
        return [self._args_to_row(table, row) for row in self.storage[table][run_id]]
    
    async def fetchval(self, query: str, *args):
        """Mock fetchval for single value queries."""
        if "COUNT" in query:
            table = self._extract_table(query)
            if not table or table not in self.storage:
                return 0
            return sum(len(v) for v in self.storage[table].values())
        
        # For existence checks
        table = self._extract_table(query)
        if not table:
            return None
        
        run_id = str(args[0])
        if table in self.storage and run_id in self.storage[table]:
            # Check for execution_diagnostics existence
            if "execution_diagnostics IS NOT NULL" in query:
                data = self.storage[table][run_id]
                if data and len(data[0]) > 13 and data[0][13] is not None:
                    return 1
                return None
            return 1
        return None
    
    def _extract_table(self, query: str) -> Optional[str]:
        """Extract table name from query."""
        tables = [
            "backtest_runs",
            "backtest_metrics",
            "backtest_trades",
            "backtest_equity_curve",
            "backtest_decision_snapshots",
            "backtest_position_snapshots",
        ]
        for table in tables:
            if table in query:
                return table
        return None
    
    def _args_to_row(self, table: str, args: tuple) -> Dict:
        """Convert args tuple to a row dict based on table schema."""
        # Helper to parse datetime - handles both str and datetime
        def parse_dt(val):
            if val is None:
                return None
            if isinstance(val, datetime):
                return val
            if isinstance(val, str):
                try:
                    return datetime.fromisoformat(val.replace('Z', '+00:00'))
                except ValueError:
                    return None
            return None

        if table == "backtest_runs":
            # Parse execution_diagnostics from args[13] if present
            execution_diagnostics = None
            if len(args) > 13 and args[13]:
                if isinstance(args[13], str):
                    try:
                        execution_diagnostics = json.loads(args[13])
                    except (json.JSONDecodeError, TypeError):
                        execution_diagnostics = None
                else:
                    execution_diagnostics = args[13]
            
            return MockRow({
                "run_id": args[0],
                "tenant_id": args[1],
                "bot_id": args[2],
                "status": args[3],
                "started_at": parse_dt(args[4]),
                "finished_at": parse_dt(args[5]),
                "config": json.loads(args[6]) if isinstance(args[6], str) else args[6],
                "name": args[7] if len(args) > 7 else None,
                "symbol": args[8] if len(args) > 8 else None,
                "start_date": parse_dt(args[9]) if len(args) > 9 else None,
                "end_date": parse_dt(args[10]) if len(args) > 10 else None,
                "error_message": args[11] if len(args) > 11 else None,
                "created_at": datetime.now(timezone.utc),
                "execution_diagnostics": execution_diagnostics,
            })
        elif table == "backtest_metrics":
            return MockRow({
                "run_id": args[0],
                "realized_pnl": args[1],
                "total_fees": args[2],
                "total_trades": args[3],
                "win_rate": args[4],
                "max_drawdown_pct": args[5],
                "avg_slippage_bps": args[6],
                "total_return_pct": args[7],
                "profit_factor": args[8],
                "avg_trade_pnl": args[9],
                "sharpe_ratio": 0.0,
                "sortino_ratio": 0.0,
                "trades_per_day": 0.0,
                "fee_drag_pct": 0.0,
                "slippage_drag_pct": 0.0,
                "gross_profit": 0.0,
                "gross_loss": 0.0,
                "avg_win": 0.0,
                "avg_loss": 0.0,
                "largest_win": 0.0,
                "largest_loss": 0.0,
                "winning_trades": 0,
                "losing_trades": 0,
            })
        elif table == "backtest_trades":
            return MockRow({
                "run_id": args[0],
                "ts": parse_dt(args[1]),
                "symbol": args[2],
                "side": args[3],
                "size": args[4],
                "entry_price": args[5],
                "exit_price": args[6],
                "pnl": args[7],
                "entry_fee": args[8],
                "exit_fee": args[9],
                "total_fees": args[10],
                "entry_slippage_bps": args[11],
                "exit_slippage_bps": args[12],
                "strategy_id": args[13],
                "profile_id": args[14],
                "reason": args[15],
            })
        elif table == "backtest_equity_curve":
            return MockRow({
                "run_id": args[0],
                "ts": parse_dt(args[1]),
                "equity": args[2],
                "realized_pnl": args[3],
                "open_positions": args[4],
            })
        elif table == "backtest_decision_snapshots":
            return MockRow({
                "run_id": args[0],
                "ts": parse_dt(args[1]),
                "symbol": args[2],
                "decision": args[3],
                "rejection_reason": args[4],
                "profile_id": args[5],
                "payload": json.loads(args[6]) if isinstance(args[6], str) else args[6],
            })
        return MockRow({})


class MockRow(dict):
    """Dict subclass that supports attribute access."""
    def __getitem__(self, key):
        return super().get(key)


class MockPool:
    """Mock connection pool for testing."""
    
    def __init__(self):
        self.storage: Dict[str, Dict[str, Any]] = {}
    
    def acquire(self):
        return MockConnectionContext(self.storage)


class MockConnectionContext:
    """Context manager for mock connections."""
    
    def __init__(self, storage: Dict[str, Dict[str, Any]]):
        self.storage = storage
        self.conn = None
    
    async def __aenter__(self):
        self.conn = MockConnection(self.storage)
        return self.conn
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass


# ============================================================================
# Hypothesis Strategies
# ============================================================================

run_ids = st.uuids().map(str)
tenant_ids = st.text(min_size=1, max_size=20, alphabet="abcdefghijklmnopqrstuvwxyz0123456789-_")
bot_ids = st.text(min_size=1, max_size=20, alphabet="abcdefghijklmnopqrstuvwxyz0123456789-_")
statuses = st.sampled_from(["pending", "running", "finished", "failed", "cancelled", "degraded"])
symbols = st.sampled_from(["BTC-USDT-SWAP", "ETH-USDT-SWAP", "SOL-USDT-SWAP"])
sides = st.sampled_from(["buy", "sell"])
decisions = st.sampled_from(["accepted", "rejected", "warmup"])

timestamps = st.datetimes(
    min_value=datetime(2024, 1, 1),
    max_value=datetime(2025, 12, 31),
).map(lambda dt: dt.replace(tzinfo=timezone.utc).isoformat())

positive_floats = st.floats(min_value=0.0, max_value=1000000.0, allow_nan=False, allow_infinity=False)
pnl_floats = st.floats(min_value=-100000.0, max_value=100000.0, allow_nan=False, allow_infinity=False)
percentages = st.floats(min_value=0.0, max_value=100.0, allow_nan=False, allow_infinity=False)
bps_floats = st.floats(min_value=0.0, max_value=1000.0, allow_nan=False, allow_infinity=False)
trade_counts = st.integers(min_value=0, max_value=10000)


@st.composite
def backtest_run_records(draw):
    """Generate valid BacktestRunRecord instances."""
    return BacktestRunRecord(
        run_id=draw(run_ids),
        tenant_id=draw(tenant_ids),
        bot_id=draw(bot_ids),
        status=draw(statuses),
        started_at=draw(timestamps),
        finished_at=draw(st.one_of(st.none(), timestamps)),
        config={"test": True},
        name=draw(st.one_of(st.none(), st.text(min_size=1, max_size=50))),
        symbol=draw(st.one_of(st.none(), symbols)),
        start_date=draw(st.one_of(st.none(), timestamps)),
        end_date=draw(st.one_of(st.none(), timestamps)),
        error_message=draw(st.one_of(st.none(), st.text(min_size=1, max_size=200))),
    )


@st.composite
def backtest_metrics_records(draw, run_id: str = None):
    """Generate valid BacktestMetricsRecord instances."""
    return BacktestMetricsRecord(
        run_id=run_id or draw(run_ids),
        realized_pnl=draw(pnl_floats),
        total_fees=draw(positive_floats),
        total_trades=draw(trade_counts),
        win_rate=draw(percentages),
        max_drawdown_pct=draw(percentages),
        avg_slippage_bps=draw(bps_floats),
        total_return_pct=draw(pnl_floats),
        profit_factor=draw(st.floats(min_value=0.0, max_value=100.0, allow_nan=False, allow_infinity=False)),
        avg_trade_pnl=draw(pnl_floats),
    )


@st.composite
def backtest_trade_records(draw, run_id: str = None):
    """Generate valid BacktestTradeRecord instances."""
    entry_price = draw(positive_floats.filter(lambda x: x > 0))
    exit_price = draw(positive_floats.filter(lambda x: x > 0))
    size = draw(positive_floats.filter(lambda x: x > 0))
    pnl = (exit_price - entry_price) * size
    
    return BacktestTradeRecord(
        run_id=run_id or draw(run_ids),
        ts=draw(timestamps),
        symbol=draw(symbols),
        side=draw(sides),
        size=size,
        entry_price=entry_price,
        exit_price=exit_price,
        pnl=pnl,
        entry_fee=draw(positive_floats),
        exit_fee=draw(positive_floats),
        total_fees=draw(positive_floats),
        entry_slippage_bps=draw(bps_floats),
        exit_slippage_bps=draw(bps_floats),
        strategy_id=draw(st.one_of(st.none(), st.text(min_size=1, max_size=20))),
        profile_id=draw(st.one_of(st.none(), st.text(min_size=1, max_size=20))),
        reason=draw(st.one_of(st.none(), st.text(min_size=1, max_size=100))),
    )


@st.composite
def backtest_equity_points(draw, run_id: str = None):
    """Generate valid BacktestEquityPoint instances."""
    return BacktestEquityPoint(
        run_id=run_id or draw(run_ids),
        ts=draw(timestamps),
        equity=draw(positive_floats),
        realized_pnl=draw(pnl_floats),
        open_positions=draw(st.integers(min_value=0, max_value=100)),
    )


@st.composite
def backtest_decision_snapshots(draw, run_id: str = None):
    """Generate valid BacktestDecisionSnapshot instances."""
    decision = draw(decisions)
    return BacktestDecisionSnapshot(
        run_id=run_id or draw(run_ids),
        ts=draw(timestamps),
        symbol=draw(symbols),
        decision=decision,
        rejection_reason=draw(st.text(min_size=1, max_size=100)) if decision == "rejected" else None,
        profile_id=draw(st.one_of(st.none(), st.text(min_size=1, max_size=20))),
        payload={"test": True, "value": draw(st.integers())},
    )


# ============================================================================
# Property Tests
# ============================================================================

class TestResultPersistence:
    """
    Property 11: Result Persistence
    
    For any completed backtest, all result tables (runs, metrics, equity_curve,
    trades, decision_snapshots) should contain data for that run_id.
    
    **Validates: Requirements R5.3**
    """
    
    @given(
        run_record=backtest_run_records(),
        num_trades=st.integers(min_value=1, max_value=5),
        num_equity_points=st.integers(min_value=1, max_value=5),
        num_decisions=st.integers(min_value=1, max_value=5),
    )
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_complete_backtest_has_all_data(
        self, run_record, num_trades, num_equity_points, num_decisions
    ):
        """
        Property 11: Result Persistence
        
        For any completed backtest with run data, metrics, trades, equity curve,
        and decision snapshots written, verify_result_persistence should return
        True for all tables.
        
        **Validates: Requirements R5.3**
        """
        # Create store with mock pool
        pool = MockPool()
        store = BacktestStore(pool)
        
        run_id = run_record.run_id
        
        # Write run record
        await store.write_run(run_record)
        
        # Write metrics
        metrics = BacktestMetricsRecord(
            run_id=run_id,
            realized_pnl=100.0,
            total_fees=10.0,
            total_trades=num_trades,
            win_rate=50.0,
            max_drawdown_pct=5.0,
            avg_slippage_bps=2.0,
            total_return_pct=10.0,
            profit_factor=1.5,
            avg_trade_pnl=10.0,
        )
        await store.write_metrics(metrics)
        
        # Write trades
        trades = []
        for i in range(num_trades):
            trade = BacktestTradeRecord(
                run_id=run_id,
                ts=datetime.now(timezone.utc).isoformat(),
                symbol="BTC-USDT-SWAP",
                side="buy",
                size=1.0,
                entry_price=50000.0,
                exit_price=50100.0,
                pnl=100.0,
                entry_fee=5.0,
                exit_fee=5.0,
                total_fees=10.0,
                entry_slippage_bps=1.0,
                exit_slippage_bps=1.0,
            )
            trades.append(trade)
        await store.write_trades(trades)
        
        # Write equity points
        equity_points = []
        for i in range(num_equity_points):
            point = BacktestEquityPoint(
                run_id=run_id,
                ts=datetime.now(timezone.utc).isoformat(),
                equity=10000.0 + i * 100,
                realized_pnl=i * 100.0,
                open_positions=1,
            )
            equity_points.append(point)
        await store.write_equity_points(equity_points)
        
        # Write decision snapshots
        decisions = []
        for i in range(num_decisions):
            decision = BacktestDecisionSnapshot(
                run_id=run_id,
                ts=datetime.now(timezone.utc).isoformat(),
                symbol="BTC-USDT-SWAP",
                decision="accepted",
                rejection_reason=None,
                profile_id="test-profile",
                payload={"test": True},
            )
            decisions.append(decision)
        await store.write_decision_snapshots(decisions)
        
        # Verify all data persisted
        persistence = await store.verify_result_persistence(run_id)
        
        assert persistence["runs"] is True, "Run record not persisted"
        assert persistence["metrics"] is True, "Metrics not persisted"
        assert persistence["trades"] is True, "Trades not persisted"
        assert persistence["equity_curve"] is True, "Equity curve not persisted"
        assert persistence["decision_snapshots"] is True, "Decision snapshots not persisted"
    
    @given(run_record=backtest_run_records())
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_run_record_round_trip(self, run_record):
        """
        Property: For any valid BacktestRunRecord, writing and reading should
        preserve all fields.
        
        **Validates: Requirements R5.3**
        """
        pool = MockPool()
        store = BacktestStore(pool)
        
        # Write the record
        await store.write_run(run_record)
        
        # Read it back
        retrieved = await store.get_run(run_record.run_id)
        
        assert retrieved is not None, "Run record not found after write"
        assert retrieved.run_id == run_record.run_id
        assert retrieved.tenant_id == run_record.tenant_id
        assert retrieved.bot_id == run_record.bot_id
        assert retrieved.status == run_record.status
        # Note: timestamps may have slight formatting differences
        assert retrieved.name == run_record.name
        assert retrieved.symbol == run_record.symbol
        assert retrieved.error_message == run_record.error_message
    
    @given(
        run_id=run_ids,
        metrics=backtest_metrics_records(),
    )
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_metrics_round_trip(self, run_id, metrics):
        """
        Property: For any valid BacktestMetricsRecord, writing and reading
        should preserve all numeric fields within floating point tolerance.
        
        **Validates: Requirements R5.3**
        """
        pool = MockPool()
        store = BacktestStore(pool)
        
        # Create metrics with the given run_id
        metrics_with_id = BacktestMetricsRecord(
            run_id=run_id,
            realized_pnl=metrics.realized_pnl,
            total_fees=metrics.total_fees,
            total_trades=metrics.total_trades,
            win_rate=metrics.win_rate,
            max_drawdown_pct=metrics.max_drawdown_pct,
            avg_slippage_bps=metrics.avg_slippage_bps,
            total_return_pct=metrics.total_return_pct,
            profit_factor=metrics.profit_factor,
            avg_trade_pnl=metrics.avg_trade_pnl,
        )
        
        # Write the metrics
        await store.write_metrics(metrics_with_id)
        
        # Read it back
        retrieved = await store.get_metrics(run_id)
        
        assert retrieved is not None, "Metrics not found after write"
        assert retrieved.run_id == run_id
        assert abs(retrieved.realized_pnl - metrics.realized_pnl) < 0.001
        assert abs(retrieved.total_fees - metrics.total_fees) < 0.001
        assert retrieved.total_trades == metrics.total_trades
        assert abs(retrieved.win_rate - metrics.win_rate) < 0.001
    
    @given(
        run_id=run_ids,
        num_trades=st.integers(min_value=1, max_value=10),
    )
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_trades_count_preserved(self, run_id, num_trades):
        """
        Property: For any number of trades written, the same number should
        be retrievable.
        
        **Validates: Requirements R5.3**
        """
        pool = MockPool()
        store = BacktestStore(pool)
        
        # Generate and write trades
        trades = []
        for i in range(num_trades):
            trade = BacktestTradeRecord(
                run_id=run_id,
                ts=datetime.now(timezone.utc).isoformat(),
                symbol="BTC-USDT-SWAP",
                side="buy" if i % 2 == 0 else "sell",
                size=1.0 + i,
                entry_price=50000.0,
                exit_price=50100.0,
                pnl=100.0,
                entry_fee=5.0,
                exit_fee=5.0,
                total_fees=10.0,
                entry_slippage_bps=1.0,
                exit_slippage_bps=1.0,
            )
            trades.append(trade)
        
        await store.write_trades(trades)
        
        # Read trades back
        retrieved = await store.get_trades(run_id)
        
        assert len(retrieved) == num_trades, \
            f"Expected {num_trades} trades, got {len(retrieved)}"
    
    @given(run_id=run_ids)
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_nonexistent_run_returns_none(self, run_id):
        """
        Property: For any run_id that hasn't been written, get_run should
        return None.
        
        **Validates: Requirements R5.3**
        """
        pool = MockPool()
        store = BacktestStore(pool)
        
        # Don't write anything
        
        # Try to read
        retrieved = await store.get_run(run_id)
        
        assert retrieved is None, "Expected None for nonexistent run"
    
    @given(run_id=run_ids)
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_empty_persistence_check(self, run_id):
        """
        Property: For any run_id without data, verify_result_persistence
        should return False for all tables.
        
        **Validates: Requirements R5.3**
        """
        pool = MockPool()
        store = BacktestStore(pool)
        
        # Don't write anything
        
        # Check persistence
        persistence = await store.verify_result_persistence(run_id)
        
        assert persistence["runs"] is False
        assert persistence["metrics"] is False
        assert persistence["trades"] is False
        assert persistence["equity_curve"] is False
        assert persistence["decision_snapshots"] is False


class TestStatusTransitions:
    """Tests for status update operations."""
    
    @given(
        run_record=backtest_run_records(),
        new_status=statuses,
    )
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_status_update_persists(self, run_record, new_status):
        """
        Property: After updating status, the new status should be retrievable.
        
        **Validates: Requirements R5.2**
        """
        pool = MockPool()
        store = BacktestStore(pool)
        
        # Write initial record
        await store.write_run(run_record)
        
        # Update status
        await store.update_run_status(run_record.run_id, new_status)
        
        # Read back
        retrieved = await store.get_run(run_record.run_id)
        
        assert retrieved is not None
        assert retrieved.status == new_status


class TestEmptyWrites:
    """Tests for edge cases with empty data."""
    
    @pytest.mark.asyncio
    async def test_empty_trades_list_no_error(self):
        """
        Edge case: Writing empty trades list should not raise an error.
        """
        pool = MockPool()
        store = BacktestStore(pool)
        
        # Should not raise
        await store.write_trades([])
    
    @pytest.mark.asyncio
    async def test_empty_equity_points_no_error(self):
        """
        Edge case: Writing empty equity points list should not raise an error.
        """
        pool = MockPool()
        store = BacktestStore(pool)
        
        # Should not raise
        await store.write_equity_points([])
    
    @pytest.mark.asyncio
    async def test_empty_decision_snapshots_no_error(self):
        """
        Edge case: Writing empty decision snapshots list should not raise an error.
        """
        pool = MockPool()
        store = BacktestStore(pool)
        
        # Should not raise
        await store.write_decision_snapshots([])


class TestExecutionDiagnosticsPersistence:
    """
    Property 4: Snapshot Count Consistency
    
    For any backtest, snapshots_processed + snapshots_skipped SHALL equal total_snapshots.
    
    Feature: backtest-diagnostics
    **Validates: Requirements 1.1, 1.4**
    """
    
    @given(
        run_record=backtest_run_records(),
        total_snapshots=st.integers(min_value=0, max_value=10000),
        processed_ratio=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
    )
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_snapshot_count_consistency(
        self, run_record, total_snapshots, processed_ratio
    ):
        """
        Property 4: Snapshot Count Consistency
        
        For any backtest with execution diagnostics, snapshots_processed + snapshots_skipped
        SHALL equal total_snapshots.
        
        Feature: backtest-diagnostics
        **Validates: Requirements 1.1, 1.4**
        """
        pool = MockPool()
        store = BacktestStore(pool)
        
        # Calculate processed and skipped to ensure they sum to total
        snapshots_processed = int(total_snapshots * processed_ratio)
        snapshots_skipped = total_snapshots - snapshots_processed
        
        # Create valid execution diagnostics
        diagnostics = {
            "total_snapshots": total_snapshots,
            "snapshots_processed": snapshots_processed,
            "snapshots_skipped": snapshots_skipped,
            "global_gate_rejections": 0,
            "rejection_breakdown": {
                "spread_too_wide": 0,
                "depth_too_thin": 0,
                "snapshot_stale": 0,
                "vol_shock": 0,
            },
            "profiles_selected": 0,
            "signals_generated": 0,
            "cooldown_rejections": 0,
            "summary": "Test backtest",
            "primary_issue": None,
            "suggestions": [],
        }
        
        # Create run record with diagnostics
        run_with_diagnostics = BacktestRunRecord(
            run_id=run_record.run_id,
            tenant_id=run_record.tenant_id,
            bot_id=run_record.bot_id,
            status=run_record.status,
            started_at=run_record.started_at,
            finished_at=run_record.finished_at,
            config=run_record.config,
            name=run_record.name,
            symbol=run_record.symbol,
            start_date=run_record.start_date,
            end_date=run_record.end_date,
            error_message=run_record.error_message,
            created_at=run_record.created_at,
            execution_diagnostics=diagnostics,
        )
        
        # Write the record
        await store.write_run(run_with_diagnostics)
        
        # Read it back
        retrieved = await store.get_run(run_record.run_id)
        
        assert retrieved is not None, "Run record not found after write"
        assert retrieved.execution_diagnostics is not None, "Diagnostics not persisted"
        
        # Verify snapshot count consistency
        diag = retrieved.execution_diagnostics
        assert diag["total_snapshots"] == total_snapshots
        assert diag["snapshots_processed"] == snapshots_processed
        assert diag["snapshots_skipped"] == snapshots_skipped
        assert diag["snapshots_processed"] + diag["snapshots_skipped"] == diag["total_snapshots"], \
            "Snapshot count consistency violated: processed + skipped != total"
    
    @given(
        run_record=backtest_run_records(),
        global_gate_rejections=st.integers(min_value=0, max_value=1000),
        spread_ratio=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
        depth_ratio=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
        stale_ratio=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
    )
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_rejection_breakdown_consistency(
        self, run_record, global_gate_rejections, spread_ratio, depth_ratio, stale_ratio
    ):
        """
        Property 3: Rejection Breakdown Consistency
        
        For any backtest, the sum of all values in rejection_breakdown SHALL equal
        global_gate_rejections.
        
        Feature: backtest-diagnostics
        **Validates: Requirements 1.2**
        """
        pool = MockPool()
        store = BacktestStore(pool)
        
        # Normalize ratios to sum to 1.0
        total_ratio = spread_ratio + depth_ratio + stale_ratio
        if total_ratio == 0:
            spread_ratio = depth_ratio = stale_ratio = 0.0
            vol_shock_ratio = 1.0 if global_gate_rejections > 0 else 0.0
        else:
            spread_ratio = spread_ratio / total_ratio
            depth_ratio = depth_ratio / total_ratio
            stale_ratio = stale_ratio / total_ratio
            vol_shock_ratio = 0.0
        
        # Calculate breakdown to ensure they sum to total
        spread_too_wide = int(global_gate_rejections * spread_ratio)
        depth_too_thin = int(global_gate_rejections * depth_ratio)
        snapshot_stale = int(global_gate_rejections * stale_ratio)
        # Assign remainder to vol_shock to ensure exact sum
        vol_shock = global_gate_rejections - spread_too_wide - depth_too_thin - snapshot_stale
        
        # Create valid execution diagnostics
        diagnostics = {
            "total_snapshots": 1000,
            "snapshots_processed": 500,
            "snapshots_skipped": 500,
            "global_gate_rejections": global_gate_rejections,
            "rejection_breakdown": {
                "spread_too_wide": spread_too_wide,
                "depth_too_thin": depth_too_thin,
                "snapshot_stale": snapshot_stale,
                "vol_shock": vol_shock,
            },
            "profiles_selected": 0,
            "signals_generated": 0,
            "cooldown_rejections": 0,
            "summary": "Test backtest",
            "primary_issue": None,
            "suggestions": [],
        }
        
        # Create run record with diagnostics
        run_with_diagnostics = BacktestRunRecord(
            run_id=run_record.run_id,
            tenant_id=run_record.tenant_id,
            bot_id=run_record.bot_id,
            status=run_record.status,
            started_at=run_record.started_at,
            finished_at=run_record.finished_at,
            config=run_record.config,
            name=run_record.name,
            symbol=run_record.symbol,
            start_date=run_record.start_date,
            end_date=run_record.end_date,
            error_message=run_record.error_message,
            created_at=run_record.created_at,
            execution_diagnostics=diagnostics,
        )
        
        # Write the record
        await store.write_run(run_with_diagnostics)
        
        # Read it back
        retrieved = await store.get_run(run_record.run_id)
        
        assert retrieved is not None, "Run record not found after write"
        assert retrieved.execution_diagnostics is not None, "Diagnostics not persisted"
        
        # Verify rejection breakdown consistency
        diag = retrieved.execution_diagnostics
        breakdown = diag["rejection_breakdown"]
        breakdown_sum = sum(breakdown.values())
        
        assert breakdown_sum == diag["global_gate_rejections"], \
            f"Rejection breakdown consistency violated: sum({breakdown_sum}) != global_gate_rejections({diag['global_gate_rejections']})"
    
    @given(run_record=backtest_run_records())
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_diagnostics_round_trip(self, run_record):
        """
        Property: For any valid execution diagnostics, writing and reading should
        preserve all fields.
        
        Feature: backtest-diagnostics
        **Validates: Requirements 1.4**
        """
        pool = MockPool()
        store = BacktestStore(pool)
        
        # Create comprehensive diagnostics
        diagnostics = {
            "total_snapshots": 1000,
            "snapshots_processed": 800,
            "snapshots_skipped": 200,
            "global_gate_rejections": 150,
            "rejection_breakdown": {
                "spread_too_wide": 50,
                "depth_too_thin": 30,
                "snapshot_stale": 40,
                "vol_shock": 30,
            },
            "profiles_selected": 100,
            "signals_generated": 50,
            "cooldown_rejections": 10,
            "summary": "Test backtest completed with 40 trades",
            "primary_issue": None,
            "suggestions": ["Try a different date range"],
        }
        
        # Create run record with diagnostics
        run_with_diagnostics = BacktestRunRecord(
            run_id=run_record.run_id,
            tenant_id=run_record.tenant_id,
            bot_id=run_record.bot_id,
            status=run_record.status,
            started_at=run_record.started_at,
            finished_at=run_record.finished_at,
            config=run_record.config,
            name=run_record.name,
            symbol=run_record.symbol,
            start_date=run_record.start_date,
            end_date=run_record.end_date,
            error_message=run_record.error_message,
            created_at=run_record.created_at,
            execution_diagnostics=diagnostics,
        )
        
        # Write the record
        await store.write_run(run_with_diagnostics)
        
        # Read it back
        retrieved = await store.get_run(run_record.run_id)
        
        assert retrieved is not None, "Run record not found after write"
        assert retrieved.execution_diagnostics is not None, "Diagnostics not persisted"
        
        # Verify all fields preserved
        diag = retrieved.execution_diagnostics
        assert diag["total_snapshots"] == diagnostics["total_snapshots"]
        assert diag["snapshots_processed"] == diagnostics["snapshots_processed"]
        assert diag["snapshots_skipped"] == diagnostics["snapshots_skipped"]
        assert diag["global_gate_rejections"] == diagnostics["global_gate_rejections"]
        assert diag["rejection_breakdown"] == diagnostics["rejection_breakdown"]
        assert diag["profiles_selected"] == diagnostics["profiles_selected"]
        assert diag["signals_generated"] == diagnostics["signals_generated"]
        assert diag["cooldown_rejections"] == diagnostics["cooldown_rejections"]
        assert diag["summary"] == diagnostics["summary"]
        assert diag["primary_issue"] == diagnostics["primary_issue"]
        assert diag["suggestions"] == diagnostics["suggestions"]
    
    @given(run_record=backtest_run_records())
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_write_diagnostics_separately(self, run_record):
        """
        Property: Diagnostics can be written separately after the run record is created.
        
        Feature: backtest-diagnostics
        **Validates: Requirements 1.4**
        """
        pool = MockPool()
        store = BacktestStore(pool)
        
        # Write run record without diagnostics
        await store.write_run(run_record)
        
        # Verify no diagnostics initially
        retrieved = await store.get_run(run_record.run_id)
        assert retrieved is not None
        assert retrieved.execution_diagnostics is None
        
        # Write diagnostics separately
        diagnostics = {
            "total_snapshots": 500,
            "snapshots_processed": 400,
            "snapshots_skipped": 100,
            "global_gate_rejections": 50,
            "rejection_breakdown": {
                "spread_too_wide": 20,
                "depth_too_thin": 15,
                "snapshot_stale": 10,
                "vol_shock": 5,
            },
            "profiles_selected": 80,
            "signals_generated": 30,
            "cooldown_rejections": 5,
            "summary": "Backtest completed",
            "primary_issue": None,
            "suggestions": [],
        }
        
        await store.write_execution_diagnostics(run_record.run_id, diagnostics)
        
        # Verify diagnostics now present
        retrieved = await store.get_run(run_record.run_id)
        assert retrieved is not None
        assert retrieved.execution_diagnostics is not None
        assert retrieved.execution_diagnostics["total_snapshots"] == 500
    
    @given(run_record=backtest_run_records())
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_has_execution_diagnostics(self, run_record):
        """
        Property: has_execution_diagnostics returns correct boolean based on presence.
        
        Feature: backtest-diagnostics
        **Validates: Requirements 1.4**
        """
        pool = MockPool()
        store = BacktestStore(pool)
        
        # Write run record without diagnostics
        await store.write_run(run_record)
        
        # Should return False when no diagnostics
        has_diag = await store.has_execution_diagnostics(run_record.run_id)
        assert has_diag is False
        
        # Write diagnostics
        diagnostics = {
            "total_snapshots": 100,
            "snapshots_processed": 100,
            "snapshots_skipped": 0,
            "global_gate_rejections": 0,
            "rejection_breakdown": {},
            "profiles_selected": 0,
            "signals_generated": 0,
            "cooldown_rejections": 0,
            "summary": "Test",
            "primary_issue": None,
            "suggestions": [],
        }
        await store.write_execution_diagnostics(run_record.run_id, diagnostics)
        
        # Should return True when diagnostics present
        has_diag = await store.has_execution_diagnostics(run_record.run_id)
        assert has_diag is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
