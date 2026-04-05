"""
Property-based tests for BacktestExecutor.

Feature: backtesting-api-integration
Property 10: Status Transition Validity
Property 12: Error Capture

Validates: Requirements R5.2, R5.4
"""

import asyncio
import json
import uuid
import pytest
from datetime import datetime, timezone
from hypothesis import given, strategies as st, settings, assume
from typing import Dict, Any, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path

from quantgambit.backtesting.executor import (
    BacktestExecutor,
    BacktestStatus,
    ExecutorConfig,
    ExecutionResult,
    is_valid_transition,
    is_terminal_status,
    VALID_TRANSITIONS,
)
from quantgambit.backtesting.store import (
    BacktestStore,
    BacktestRunRecord,
)


# ============================================================================
# Mock Database Pool (reused from test_backtest_store.py)
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
                if table == "backtest_runs" and self.storage[table][run_id]:
                    old_args = list(self.storage[table][run_id][0])
                    old_args[3] = args[1]  # status is at index 3
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
        
        table = self._extract_table(query)
        if not table:
            return None
        
        run_id = str(args[0])
        if table in self.storage and run_id in self.storage[table]:
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
        if table == "backtest_runs":
            return MockRow({
                "run_id": args[0],
                "tenant_id": args[1],
                "bot_id": args[2],
                "status": args[3],
                "started_at": datetime.fromisoformat(args[4]) if args[4] else None,
                "finished_at": datetime.fromisoformat(args[5]) if args[5] else None,
                "config": json.loads(args[6]) if isinstance(args[6], str) else args[6],
                "name": args[7] if len(args) > 7 else None,
                "symbol": args[8] if len(args) > 8 else None,
                "start_date": datetime.fromisoformat(args[9]) if len(args) > 9 and args[9] else None,
                "end_date": datetime.fromisoformat(args[10]) if len(args) > 10 and args[10] else None,
                "error_message": args[11] if len(args) > 11 else None,
                "created_at": datetime.now(timezone.utc),
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
symbols = st.sampled_from(["BTC-USDT-SWAP", "ETH-USDT-SWAP", "SOL-USDT-SWAP"])

# All valid statuses
all_statuses = st.sampled_from(list(BacktestStatus))

# Non-terminal statuses (can transition to other states)
non_terminal_statuses = st.sampled_from([
    BacktestStatus.PENDING,
    BacktestStatus.RUNNING,
])

# Terminal statuses (cannot transition further)
terminal_statuses = st.sampled_from([
    BacktestStatus.FINISHED,
    BacktestStatus.FAILED,
    BacktestStatus.CANCELLED,
    BacktestStatus.DEGRADED,
])

error_messages = st.text(min_size=1, max_size=200)


@st.composite
def backtest_configs(draw):
    """Generate valid backtest configurations."""
    return {
        "symbol": draw(symbols),
        "start_date": "2024-01-01",
        "end_date": "2024-01-31",
        "initial_capital": draw(st.floats(min_value=1000.0, max_value=100000.0, allow_nan=False)),
        "fee_bps": draw(st.floats(min_value=0.0, max_value=10.0, allow_nan=False)),
        "slippage_bps": draw(st.floats(min_value=0.0, max_value=10.0, allow_nan=False)),
    }


# ============================================================================
# Property Tests for Status Transitions
# ============================================================================

class TestStatusTransitionValidity:
    """
    Property 10: Status Transition Validity
    
    For any backtest job, status transitions should follow the valid state machine:
    pending → running → (completed | failed | cancelled | degraded).
    
    **Validates: Requirements R5.2**
    """
    
    @given(from_status=all_statuses, to_status=all_statuses)
    @settings(max_examples=100)
    def test_valid_transitions_are_allowed(self, from_status, to_status):
        """
        Property 10: Status Transition Validity
        
        For any pair of statuses, is_valid_transition should return True
        only if the transition is in the VALID_TRANSITIONS map.
        
        **Validates: Requirements R5.2**
        """
        expected = to_status in VALID_TRANSITIONS.get(from_status, set())
        actual = is_valid_transition(from_status, to_status)
        
        assert actual == expected, \
            f"Transition {from_status} → {to_status}: expected {expected}, got {actual}"
    
    @given(status=terminal_statuses)
    @settings(max_examples=100)
    def test_terminal_statuses_have_no_transitions(self, status):
        """
        Property 10: Status Transition Validity
        
        For any terminal status (finished, failed, cancelled, degraded),
        no further transitions should be allowed.
        
        **Validates: Requirements R5.2**
        """
        assert is_terminal_status(status), f"{status} should be terminal"
        
        # No transitions should be valid from terminal states
        for target in BacktestStatus:
            assert not is_valid_transition(status, target), \
                f"Terminal status {status} should not allow transition to {target}"
    
    @given(status=non_terminal_statuses)
    @settings(max_examples=100)
    def test_non_terminal_statuses_have_transitions(self, status):
        """
        Property 10: Status Transition Validity
        
        For any non-terminal status (pending, running), at least one
        transition should be allowed.
        
        **Validates: Requirements R5.2**
        """
        assert not is_terminal_status(status), f"{status} should not be terminal"
        
        # At least one transition should be valid
        valid_targets = [t for t in BacktestStatus if is_valid_transition(status, t)]
        assert len(valid_targets) > 0, \
            f"Non-terminal status {status} should have at least one valid transition"
    
    def test_pending_can_transition_to_running(self):
        """
        Property 10: Status Transition Validity
        
        PENDING status must be able to transition to RUNNING.
        
        **Validates: Requirements R5.2**
        """
        assert is_valid_transition(BacktestStatus.PENDING, BacktestStatus.RUNNING)
    
    def test_pending_can_transition_to_cancelled(self):
        """
        Property 10: Status Transition Validity
        
        PENDING status must be able to transition to CANCELLED.
        
        **Validates: Requirements R5.2**
        """
        assert is_valid_transition(BacktestStatus.PENDING, BacktestStatus.CANCELLED)
    
    def test_pending_can_transition_to_failed(self):
        """
        Property 10: Status Transition Validity
        
        PENDING status must be able to transition to FAILED.
        
        **Validates: Requirements R5.2**
        """
        assert is_valid_transition(BacktestStatus.PENDING, BacktestStatus.FAILED)
    
    def test_running_can_transition_to_finished(self):
        """
        Property 10: Status Transition Validity
        
        RUNNING status must be able to transition to FINISHED.
        
        **Validates: Requirements R5.2**
        """
        assert is_valid_transition(BacktestStatus.RUNNING, BacktestStatus.FINISHED)
    
    def test_running_can_transition_to_failed(self):
        """
        Property 10: Status Transition Validity
        
        RUNNING status must be able to transition to FAILED.
        
        **Validates: Requirements R5.2**
        """
        assert is_valid_transition(BacktestStatus.RUNNING, BacktestStatus.FAILED)
    
    def test_running_can_transition_to_cancelled(self):
        """
        Property 10: Status Transition Validity
        
        RUNNING status must be able to transition to CANCELLED.
        
        **Validates: Requirements R5.2**
        """
        assert is_valid_transition(BacktestStatus.RUNNING, BacktestStatus.CANCELLED)
    
    def test_running_can_transition_to_degraded(self):
        """
        Property 10: Status Transition Validity
        
        RUNNING status must be able to transition to DEGRADED.
        
        **Validates: Requirements R5.2**
        """
        assert is_valid_transition(BacktestStatus.RUNNING, BacktestStatus.DEGRADED)
    
    @given(status=all_statuses)
    @settings(max_examples=100)
    def test_no_self_transitions(self, status):
        """
        Property 10: Status Transition Validity
        
        For any status, transitioning to itself should not be valid
        (except implicitly through no-op).
        
        **Validates: Requirements R5.2**
        """
        # Self-transitions are not in the valid transitions map
        assert not is_valid_transition(status, status), \
            f"Self-transition {status} → {status} should not be valid"
    
    @given(
        run_id=run_ids,
        tenant_id=tenant_ids,
        bot_id=bot_ids,
        config=backtest_configs(),
    )
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_executor_follows_valid_transitions(
        self, run_id, tenant_id, bot_id, config
    ):
        """
        Property 10: Status Transition Validity
        
        For any backtest execution, the executor should only make valid
        status transitions (pending → running → terminal).
        
        **Validates: Requirements R5.2**
        """
        pool = MockPool()
        store = BacktestStore(pool)
        
        # Track status transitions
        transitions = []
        original_write_run = store.write_run
        
        async def tracking_write_run(record):
            transitions.append(record.status)
            return await original_write_run(record)
        
        store.write_run = tracking_write_run
        
        # Create executor with mocked dependencies
        executor = BacktestExecutor(
            db_pool=pool,
            redis_client=MagicMock(),
            config=ExecutorConfig(
                temp_dir="/tmp/test_backtests",
                cleanup_temp_files=False,
                parity_mode=False,  # Disable parity check for this test
            ),
        )
        executor.store = store
        
        # Mock the export and replay to fail (simpler test case)
        with patch.object(executor, '_export_snapshots', side_effect=ValueError("Test error")):
            result = await executor.execute(
                run_id=run_id,
                tenant_id=tenant_id,
                bot_id=bot_id,
                config=config,
            )
        
        # Verify transitions are valid
        assert len(transitions) >= 1, "At least one status should be recorded"
        
        # First status should be RUNNING (executor sets this first)
        assert transitions[0] == BacktestStatus.RUNNING.value, \
            f"First status should be RUNNING, got {transitions[0]}"
        
        # Last status should be terminal
        final_status = BacktestStatus(transitions[-1])
        assert is_terminal_status(final_status), \
            f"Final status {final_status} should be terminal"
        
        # Verify each transition is valid
        for i in range(len(transitions) - 1):
            from_status = BacktestStatus(transitions[i])
            to_status = BacktestStatus(transitions[i + 1])
            assert is_valid_transition(from_status, to_status), \
                f"Invalid transition: {from_status} → {to_status}"


# ============================================================================
# Property Tests for Error Capture
# ============================================================================

class TestErrorCapture:
    """
    Property 12: Error Capture
    
    For any failed backtest, the backtest_runs table should contain a
    non-null error_message field describing the failure.
    
    **Validates: Requirements R5.4**
    """
    
    @given(
        run_id=run_ids,
        tenant_id=tenant_ids,
        bot_id=bot_ids,
        config=backtest_configs(),
        error_message=error_messages,
    )
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_failed_backtest_captures_error(
        self, run_id, tenant_id, bot_id, config, error_message
    ):
        """
        Property 12: Error Capture
        
        For any backtest that fails with an exception, the error message
        should be captured in the run record.
        
        **Validates: Requirements R5.4**
        """
        pool = MockPool()
        store = BacktestStore(pool)
        
        executor = BacktestExecutor(
            db_pool=pool,
            redis_client=MagicMock(),
            config=ExecutorConfig(
                temp_dir="/tmp/test_backtests",
                cleanup_temp_files=False,
                parity_mode=False,  # Disable parity check for this test
            ),
        )
        executor.store = store
        
        # Mock export to raise the specific error
        with patch.object(executor, '_export_snapshots', side_effect=ValueError(error_message)):
            result = await executor.execute(
                run_id=run_id,
                tenant_id=tenant_id,
                bot_id=bot_id,
                config=config,
            )
        
        # Verify result indicates failure
        assert result.status == BacktestStatus.FAILED, \
            f"Expected FAILED status, got {result.status}"
        
        # Verify error message is captured in result
        assert result.error_message is not None, \
            "Error message should be captured in result"
        assert error_message in result.error_message, \
            f"Error message '{error_message}' should be in result.error_message"
        
        # Verify timestamps are set
        assert result.started_at is not None, "started_at should be set"
        assert result.finished_at is not None, "finished_at should be set"
    
    @given(
        run_id=run_ids,
        tenant_id=tenant_ids,
        bot_id=bot_ids,
        config=backtest_configs(),
    )
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_export_failure_captures_error(
        self, run_id, tenant_id, bot_id, config
    ):
        """
        Property 12: Error Capture
        
        For any backtest that fails during snapshot export, the error
        should be captured with a descriptive message.
        
        **Validates: Requirements R5.4**
        """
        pool = MockPool()
        store = BacktestStore(pool)
        
        executor = BacktestExecutor(
            db_pool=pool,
            redis_client=MagicMock(),
            config=ExecutorConfig(
                temp_dir="/tmp/test_backtests",
                cleanup_temp_files=False,
                parity_mode=False,  # Disable parity check for this test
            ),
        )
        executor.store = store
        
        # Mock export to fail with connection error
        with patch.object(executor, '_export_snapshots', side_effect=ConnectionError("Redis connection failed")):
            result = await executor.execute(
                run_id=run_id,
                tenant_id=tenant_id,
                bot_id=bot_id,
                config=config,
            )
        
        # Verify failure is captured
        assert result.status == BacktestStatus.FAILED
        assert result.error_message is not None
        assert "Redis connection failed" in result.error_message
        
        # Verify timestamps are set
        assert result.started_at is not None
        assert result.finished_at is not None
    
    @given(
        run_id=run_ids,
        tenant_id=tenant_ids,
        bot_id=bot_ids,
        config=backtest_configs(),
    )
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_replay_failure_captures_error(
        self, run_id, tenant_id, bot_id, config
    ):
        """
        Property 12: Error Capture
        
        For any backtest that fails during replay, the error should be
        captured with a descriptive message.
        
        **Validates: Requirements R5.4**
        """
        pool = MockPool()
        store = BacktestStore(pool)
        
        executor = BacktestExecutor(
            db_pool=pool,
            redis_client=MagicMock(),
            config=ExecutorConfig(
                temp_dir="/tmp/test_backtests",
                cleanup_temp_files=False,
                parity_mode=False,  # Disable parity check for this test
            ),
        )
        executor.store = store
        
        # Mock export to succeed but replay to fail
        mock_path = MagicMock(spec=Path)
        mock_path.exists.return_value = True
        mock_path.stat.return_value.st_size = 100
        
        with patch.object(executor, '_export_snapshots', return_value=mock_path):
            with patch('builtins.open', MagicMock(return_value=iter(['{"test": 1}']))):
                with patch.object(executor, '_replay_snapshots', side_effect=RuntimeError("Decision engine error")):
                    result = await executor.execute(
                        run_id=run_id,
                        tenant_id=tenant_id,
                        bot_id=bot_id,
                        config=config,
                    )
        
        # Verify failure is captured
        assert result.status == BacktestStatus.FAILED
        assert result.error_message is not None
        assert "Decision engine error" in result.error_message
    
    @given(
        run_id=run_ids,
        tenant_id=tenant_ids,
        bot_id=bot_ids,
        config=backtest_configs(),
    )
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_no_snapshots_captures_error(
        self, run_id, tenant_id, bot_id, config
    ):
        """
        Property 12: Error Capture
        
        For any backtest with no available snapshots, a descriptive error
        should be captured.
        
        **Validates: Requirements R5.4**
        """
        pool = MockPool()
        store = BacktestStore(pool)
        
        executor = BacktestExecutor(
            db_pool=pool,
            redis_client=MagicMock(),
            config=ExecutorConfig(
                temp_dir="/tmp/test_backtests",
                cleanup_temp_files=False,
                parity_mode=False,  # Disable parity check for this test
            ),
        )
        executor.store = store
        
        # Mock export to return empty file
        mock_path = MagicMock(spec=Path)
        mock_path.exists.return_value = True
        mock_path.stat.return_value.st_size = 0  # Empty file
        
        with patch.object(executor, '_export_snapshots', return_value=mock_path):
            result = await executor.execute(
                run_id=run_id,
                tenant_id=tenant_id,
                bot_id=bot_id,
                config=config,
            )
        
        # Verify failure is captured with descriptive message
        assert result.status == BacktestStatus.FAILED
        assert result.error_message is not None
        assert "No snapshots" in result.error_message or "snapshot" in result.error_message.lower()
    
    @given(
        run_id=run_ids,
        tenant_id=tenant_ids,
        bot_id=bot_ids,
        config=backtest_configs(),
    )
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_failed_run_has_finished_at(
        self, run_id, tenant_id, bot_id, config
    ):
        """
        Property 12: Error Capture
        
        For any failed backtest, the finished_at timestamp should be set.
        
        **Validates: Requirements R5.4**
        """
        pool = MockPool()
        store = BacktestStore(pool)
        
        executor = BacktestExecutor(
            db_pool=pool,
            redis_client=MagicMock(),
            config=ExecutorConfig(
                temp_dir="/tmp/test_backtests",
                cleanup_temp_files=False,
                parity_mode=False,  # Disable parity check for this test
            ),
        )
        executor.store = store
        
        with patch.object(executor, '_export_snapshots', side_effect=ValueError("Test error")):
            result = await executor.execute(
                run_id=run_id,
                tenant_id=tenant_id,
                bot_id=bot_id,
                config=config,
            )
        
        # Verify finished_at is set
        assert result.finished_at is not None, \
            "finished_at should be set for failed runs"
        
        # Verify started_at is also set
        assert result.started_at is not None, \
            "started_at should be set for failed runs"


# ============================================================================
# Edge Case Tests
# ============================================================================

class TestExecutorEdgeCases:
    """Edge case tests for BacktestExecutor."""
    
    @pytest.mark.asyncio
    async def test_executor_config_from_env(self):
        """ExecutorConfig.from_env() should load defaults."""
        config = ExecutorConfig.from_env()
        
        assert config.redis_url is not None
        assert config.temp_dir is not None
        assert config.fee_bps >= 0
        assert config.starting_equity > 0
    
    def test_all_statuses_in_valid_transitions(self):
        """All BacktestStatus values should be keys in VALID_TRANSITIONS."""
        for status in BacktestStatus:
            assert status in VALID_TRANSITIONS, \
                f"Status {status} should be in VALID_TRANSITIONS"
    
    def test_valid_transitions_only_contain_valid_statuses(self):
        """VALID_TRANSITIONS values should only contain valid BacktestStatus values."""
        for from_status, to_statuses in VALID_TRANSITIONS.items():
            for to_status in to_statuses:
                assert isinstance(to_status, BacktestStatus), \
                    f"Invalid status {to_status} in transitions from {from_status}"
    
    @pytest.mark.asyncio
    async def test_execution_result_fields(self):
        """ExecutionResult should have all required fields."""
        result = ExecutionResult(
            run_id="test-123",
            status=BacktestStatus.FINISHED,
            error_message=None,
            snapshot_count=100,
            started_at="2024-01-01T00:00:00Z",
            finished_at="2024-01-01T01:00:00Z",
        )
        
        assert result.run_id == "test-123"
        assert result.status == BacktestStatus.FINISHED
        assert result.error_message is None
        assert result.snapshot_count == 100
        assert result.started_at is not None
        assert result.finished_at is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
