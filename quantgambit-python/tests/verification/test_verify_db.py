"""
Unit tests for database verification script.

Tests the verify_db.py script functions for table existence checks,
column validation, and foreign key validation.

Requirements: 2.1, 2.2, 2.3, 2.4
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from contextlib import asynccontextmanager
import asyncpg

import sys
import os

# Add scripts directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'scripts'))

from verify_db import (
    VerificationResult,
    verify_table_exists,
    verify_table_columns,
    verify_foreign_keys,
    REQUIRED_TABLES,
    REQUIRED_COLUMNS,
    EXPECTED_FOREIGN_KEYS,
)


def create_mock_pool(mock_conn):
    """Create a mock pool with proper async context manager support."""
    mock_pool = MagicMock()
    
    @asynccontextmanager
    async def mock_acquire():
        yield mock_conn
    
    mock_pool.acquire = mock_acquire
    return mock_pool


class TestVerificationResult:
    """Tests for VerificationResult dataclass."""
    
    def test_create_passing_result(self):
        """Test creating a passing verification result."""
        result = VerificationResult(
            name="Test Check",
            passed=True,
            message="Check passed successfully",
            details={"key": "value"},
            error=None
        )
        
        assert result.name == "Test Check"
        assert result.passed is True
        assert result.message == "Check passed successfully"
        assert result.details == {"key": "value"}
        assert result.error is None
    
    def test_create_failing_result(self):
        """Test creating a failing verification result."""
        result = VerificationResult(
            name="Test Check",
            passed=False,
            message="Check failed",
            details={"table": "test_table"},
            error="Table not found"
        )
        
        assert result.name == "Test Check"
        assert result.passed is False
        assert result.message == "Check failed"
        assert result.error == "Table not found"
    
    def test_result_with_no_optional_fields(self):
        """Test creating a result without optional fields."""
        result = VerificationResult(
            name="Simple Check",
            passed=True,
            message="OK"
        )
        
        assert result.name == "Simple Check"
        assert result.passed is True
        assert result.message == "OK"
        assert result.details is None
        assert result.error is None


class TestRequiredTablesAndColumns:
    """Tests for required tables and columns constants."""
    
    def test_required_tables_defined(self):
        """Test that all required tables are defined."""
        assert "backtest_runs" in REQUIRED_TABLES
        assert "backtest_trades" in REQUIRED_TABLES
        assert "backtest_equity_curve" in REQUIRED_TABLES
        assert "backtest_metrics" in REQUIRED_TABLES
    
    def test_required_columns_for_backtest_runs(self):
        """Test required columns for backtest_runs table."""
        columns = REQUIRED_COLUMNS["backtest_runs"]
        assert "run_id" in columns
        assert "tenant_id" in columns
        assert "bot_id" in columns
        assert "status" in columns
        assert "created_at" in columns
        assert "config" in columns
    
    def test_required_columns_for_backtest_trades(self):
        """Test required columns for backtest_trades table."""
        columns = REQUIRED_COLUMNS["backtest_trades"]
        assert "run_id" in columns
        assert "symbol" in columns
        assert "side" in columns
        assert "entry_price" in columns
        assert "exit_price" in columns
        assert "ts" in columns
    
    def test_required_columns_for_backtest_equity_curve(self):
        """Test required columns for backtest_equity_curve table."""
        columns = REQUIRED_COLUMNS["backtest_equity_curve"]
        assert "run_id" in columns
        assert "ts" in columns
        assert "equity" in columns
    
    def test_required_columns_for_backtest_metrics(self):
        """Test required columns for backtest_metrics table."""
        columns = REQUIRED_COLUMNS["backtest_metrics"]
        assert "run_id" in columns
        assert "total_trades" in columns
        assert "realized_pnl" in columns
        assert "total_return_pct" in columns


@pytest.mark.asyncio
class TestVerifyTableExists:
    """Tests for verify_table_exists function.
    
    **Validates: Requirements 2.1, 2.2, 2.3, 2.4**
    """
    
    async def test_table_exists_success(self):
        """Test successful table existence check.
        
        **Validates: Requirements 2.1**
        """
        mock_conn = AsyncMock()
        # First call returns True (table exists), second returns row count
        mock_conn.fetchval.side_effect = [True, 100]
        
        mock_pool = create_mock_pool(mock_conn)
        result = await verify_table_exists(mock_pool, "backtest_runs")
        
        assert result.passed is True
        assert result.name == "Table Exists: backtest_runs"
        assert "exists" in result.message
        assert result.details["table_name"] == "backtest_runs"
        assert result.details["exists"] is True
        assert result.details["row_count"] == 100
    
    async def test_table_does_not_exist(self):
        """Test table existence check when table is missing.
        
        **Validates: Requirements 2.1**
        """
        mock_conn = AsyncMock()
        mock_conn.fetchval.return_value = False
        
        mock_pool = create_mock_pool(mock_conn)
        result = await verify_table_exists(mock_pool, "missing_table")
        
        assert result.passed is False
        assert "does not exist" in result.message
        assert "Run migrations" in result.message
        assert result.details["table_name"] == "missing_table"
        assert result.details["exists"] is False
    
    async def test_table_exists_database_error(self):
        """Test table existence check with database error.
        
        **Validates: Requirements 2.1**
        """
        mock_conn = AsyncMock()
        mock_conn.fetchval.side_effect = asyncpg.PostgresError("Connection lost")
        
        mock_pool = create_mock_pool(mock_conn)
        result = await verify_table_exists(mock_pool, "backtest_runs")
        
        assert result.passed is False
        assert "Database error" in result.message
        assert result.error is not None


@pytest.mark.asyncio
class TestVerifyTableColumns:
    """Tests for verify_table_columns function.
    
    **Validates: Requirements 2.1, 2.2, 2.3, 2.4**
    """
    
    async def test_all_columns_present(self):
        """Test successful column verification when all columns exist.
        
        **Validates: Requirements 2.1, 2.2, 2.3, 2.4**
        """
        mock_conn = AsyncMock()
        # Simulate database returning all required columns plus some extra
        mock_conn.fetch.return_value = [
            {"column_name": "run_id"},
            {"column_name": "tenant_id"},
            {"column_name": "bot_id"},
            {"column_name": "status"},
            {"column_name": "created_at"},
            {"column_name": "config"},
            {"column_name": "updated_at"},  # Extra column
        ]
        
        mock_pool = create_mock_pool(mock_conn)
        required_columns = ["run_id", "tenant_id", "bot_id", "status", "created_at", "config"]
        result = await verify_table_columns(mock_pool, "backtest_runs", required_columns)
        
        assert result.passed is True
        assert result.name == "Table Columns: backtest_runs"
        assert "all 6 required columns" in result.message
        assert result.details["table_name"] == "backtest_runs"
        assert result.details["required_columns"] == required_columns
        assert "run_id" in result.details["actual_columns"]
    
    async def test_missing_single_column(self):
        """Test column verification when one column is missing.
        
        **Validates: Requirements 2.1, 2.2, 2.3, 2.4**
        """
        mock_conn = AsyncMock()
        # Missing 'status' column
        mock_conn.fetch.return_value = [
            {"column_name": "run_id"},
            {"column_name": "tenant_id"},
            {"column_name": "bot_id"},
            {"column_name": "created_at"},
            {"column_name": "config"},
        ]
        
        mock_pool = create_mock_pool(mock_conn)
        required_columns = ["run_id", "tenant_id", "bot_id", "status", "created_at", "config"]
        result = await verify_table_columns(mock_pool, "backtest_runs", required_columns)
        
        assert result.passed is False
        assert "missing 1 required column" in result.message
        assert "status" in str(result.details["missing_columns"])
    
    async def test_missing_multiple_columns(self):
        """Test column verification when multiple columns are missing.
        
        **Validates: Requirements 2.1, 2.2, 2.3, 2.4**
        """
        mock_conn = AsyncMock()
        # Missing 'status' and 'created_at' columns
        mock_conn.fetch.return_value = [
            {"column_name": "run_id"},
            {"column_name": "tenant_id"},
            {"column_name": "bot_id"},
            {"column_name": "config"},
        ]
        
        mock_pool = create_mock_pool(mock_conn)
        required_columns = ["run_id", "tenant_id", "bot_id", "status", "created_at", "config"]
        result = await verify_table_columns(mock_pool, "backtest_runs", required_columns)
        
        assert result.passed is False
        assert "missing 2 required column" in result.message
        assert "status" in result.details["missing_columns"]
        assert "created_at" in result.details["missing_columns"]
    
    async def test_empty_table_no_columns(self):
        """Test column verification when table has no columns (edge case).
        
        **Validates: Requirements 2.1, 2.2, 2.3, 2.4**
        """
        mock_conn = AsyncMock()
        # No columns returned
        mock_conn.fetch.return_value = []
        
        mock_pool = create_mock_pool(mock_conn)
        required_columns = ["run_id", "symbol", "side"]
        result = await verify_table_columns(mock_pool, "backtest_trades", required_columns)
        
        assert result.passed is False
        assert "missing 3 required column" in result.message
        assert len(result.details["missing_columns"]) == 3
    
    async def test_backtest_trades_columns(self):
        """Test column verification for backtest_trades table.
        
        **Validates: Requirements 2.2**
        """
        mock_conn = AsyncMock()
        mock_conn.fetch.return_value = [
            {"column_name": "run_id"},
            {"column_name": "symbol"},
            {"column_name": "side"},
            {"column_name": "entry_price"},
            {"column_name": "exit_price"},
            {"column_name": "ts"},
        ]
        
        mock_pool = create_mock_pool(mock_conn)
        required_columns = REQUIRED_COLUMNS["backtest_trades"]
        result = await verify_table_columns(mock_pool, "backtest_trades", required_columns)
        
        assert result.passed is True
        assert result.details["table_name"] == "backtest_trades"
    
    async def test_backtest_equity_curve_columns(self):
        """Test column verification for backtest_equity_curve table.
        
        **Validates: Requirements 2.3**
        """
        mock_conn = AsyncMock()
        mock_conn.fetch.return_value = [
            {"column_name": "run_id"},
            {"column_name": "ts"},
            {"column_name": "equity"},
        ]
        
        mock_pool = create_mock_pool(mock_conn)
        required_columns = REQUIRED_COLUMNS["backtest_equity_curve"]
        result = await verify_table_columns(mock_pool, "backtest_equity_curve", required_columns)
        
        assert result.passed is True
        assert result.details["table_name"] == "backtest_equity_curve"
    
    async def test_backtest_metrics_columns(self):
        """Test column verification for backtest_metrics table.
        
        **Validates: Requirements 2.4**
        """
        mock_conn = AsyncMock()
        mock_conn.fetch.return_value = [
            {"column_name": "run_id"},
            {"column_name": "total_trades"},
            {"column_name": "realized_pnl"},
            {"column_name": "total_return_pct"},
        ]
        
        mock_pool = create_mock_pool(mock_conn)
        required_columns = REQUIRED_COLUMNS["backtest_metrics"]
        result = await verify_table_columns(mock_pool, "backtest_metrics", required_columns)
        
        assert result.passed is True
        assert result.details["table_name"] == "backtest_metrics"
    
    async def test_column_verification_database_error(self):
        """Test column verification with database error.
        
        **Validates: Requirements 2.1, 2.2, 2.3, 2.4**
        """
        mock_conn = AsyncMock()
        mock_conn.fetch.side_effect = asyncpg.PostgresError("Connection lost")
        
        mock_pool = create_mock_pool(mock_conn)
        required_columns = ["id", "tenant_id"]
        result = await verify_table_columns(mock_pool, "backtest_runs", required_columns)
        
        assert result.passed is False
        assert "Database error" in result.message
        assert result.error is not None
        assert "Connection lost" in result.error
    
    async def test_column_verification_unexpected_error(self):
        """Test column verification with unexpected error.
        
        **Validates: Requirements 2.1, 2.2, 2.3, 2.4**
        """
        mock_conn = AsyncMock()
        mock_conn.fetch.side_effect = RuntimeError("Unexpected error")
        
        mock_pool = create_mock_pool(mock_conn)
        required_columns = ["id", "tenant_id"]
        result = await verify_table_columns(mock_pool, "backtest_runs", required_columns)
        
        assert result.passed is False
        assert "Unexpected error" in result.message
        assert result.error is not None
    
    async def test_column_verification_empty_required_list(self):
        """Test column verification with empty required columns list.
        
        **Validates: Requirements 2.1, 2.2, 2.3, 2.4**
        """
        mock_conn = AsyncMock()
        mock_conn.fetch.return_value = [
            {"column_name": "id"},
            {"column_name": "name"},
        ]
        
        mock_pool = create_mock_pool(mock_conn)
        # Empty required columns list - should pass
        result = await verify_table_columns(mock_pool, "test_table", [])
        
        assert result.passed is True
        assert "all 0 required columns" in result.message
    
    async def test_column_verification_queries_correct_schema(self):
        """Test that column verification queries the correct schema.
        
        **Validates: Requirements 2.1, 2.2, 2.3, 2.4**
        """
        mock_conn = AsyncMock()
        mock_conn.fetch.return_value = [{"column_name": "id"}]
        
        mock_pool = create_mock_pool(mock_conn)
        await verify_table_columns(mock_pool, "test_table", ["id"])
        
        # Verify the query was called with correct parameters
        mock_conn.fetch.assert_called_once()
        call_args = mock_conn.fetch.call_args
        query = call_args[0][0]
        table_name = call_args[0][1]
        
        assert "information_schema.columns" in query
        assert "table_schema = 'public'" in query
        assert table_name == "test_table"


class TestExpectedForeignKeys:
    """Tests for expected foreign keys constants."""
    
    def test_expected_foreign_keys_defined(self):
        """Test that expected foreign keys are defined for child tables."""
        assert "backtest_trades" in EXPECTED_FOREIGN_KEYS
        assert "backtest_equity_curve" in EXPECTED_FOREIGN_KEYS
        assert "backtest_metrics" in EXPECTED_FOREIGN_KEYS
    
    def test_backtest_trades_references_backtest_runs(self):
        """Test backtest_trades has foreign key to backtest_runs.
        
        **Validates: Requirements 2.2**
        """
        assert "backtest_runs" in EXPECTED_FOREIGN_KEYS["backtest_trades"]
    
    def test_backtest_equity_curve_references_backtest_runs(self):
        """Test backtest_equity_curve has foreign key to backtest_runs.
        
        **Validates: Requirements 2.3**
        """
        assert "backtest_runs" in EXPECTED_FOREIGN_KEYS["backtest_equity_curve"]
    
    def test_backtest_metrics_references_backtest_runs(self):
        """Test backtest_metrics has foreign key to backtest_runs.
        
        **Validates: Requirements 2.4**
        """
        assert "backtest_runs" in EXPECTED_FOREIGN_KEYS["backtest_metrics"]
    
    def test_backtest_runs_has_no_expected_foreign_keys(self):
        """Test backtest_runs is not in expected foreign keys (it's the parent table)."""
        assert "backtest_runs" not in EXPECTED_FOREIGN_KEYS


@pytest.mark.asyncio
class TestVerifyForeignKeys:
    """Tests for verify_foreign_keys function.
    
    **Validates: Requirements 2.2, 2.3, 2.4**
    """
    
    async def test_all_foreign_keys_present(self):
        """Test successful foreign key verification when all FKs exist.
        
        **Validates: Requirements 2.2, 2.3, 2.4**
        """
        mock_conn = AsyncMock()
        # Simulate database returning foreign key constraint to backtest_runs
        mock_conn.fetch.return_value = [
            {"constraint_name": "fk_backtest_trades_run", "referenced_table": "backtest_runs"},
        ]
        
        mock_pool = create_mock_pool(mock_conn)
        result = await verify_foreign_keys(mock_pool, "backtest_trades", ["backtest_runs"])
        
        assert result.passed is True
        assert result.name == "Foreign Keys: backtest_trades"
        assert "all 1 expected foreign key" in result.message
        assert result.details["table_name"] == "backtest_trades"
        assert "backtest_runs" in result.details["expected_fks"]
        assert "backtest_runs" in result.details["actual_fks"]
    
    async def test_missing_foreign_key(self):
        """Test foreign key verification when FK is missing.
        
        **Validates: Requirements 2.2, 2.3, 2.4**
        """
        mock_conn = AsyncMock()
        # No foreign keys returned
        mock_conn.fetch.return_value = []
        
        mock_pool = create_mock_pool(mock_conn)
        result = await verify_foreign_keys(mock_pool, "backtest_trades", ["backtest_runs"])
        
        assert result.passed is False
        assert "missing foreign key" in result.message
        assert "backtest_runs" in str(result.details["missing_fks"])
    
    async def test_multiple_expected_foreign_keys(self):
        """Test foreign key verification with multiple expected FKs.
        
        **Validates: Requirements 2.2, 2.3, 2.4**
        """
        mock_conn = AsyncMock()
        # Simulate database returning multiple foreign key constraints
        mock_conn.fetch.return_value = [
            {"constraint_name": "fk_table_runs", "referenced_table": "backtest_runs"},
            {"constraint_name": "fk_table_users", "referenced_table": "users"},
        ]
        
        mock_pool = create_mock_pool(mock_conn)
        result = await verify_foreign_keys(mock_pool, "test_table", ["backtest_runs", "users"])
        
        assert result.passed is True
        assert "all 2 expected foreign key" in result.message
        assert "backtest_runs" in result.details["actual_fks"]
        assert "users" in result.details["actual_fks"]
    
    async def test_partial_foreign_keys_present(self):
        """Test foreign key verification when only some FKs exist.
        
        **Validates: Requirements 2.2, 2.3, 2.4**
        """
        mock_conn = AsyncMock()
        # Only one of two expected FKs exists
        mock_conn.fetch.return_value = [
            {"constraint_name": "fk_table_runs", "referenced_table": "backtest_runs"},
        ]
        
        mock_pool = create_mock_pool(mock_conn)
        result = await verify_foreign_keys(mock_pool, "test_table", ["backtest_runs", "users"])
        
        assert result.passed is False
        assert "missing foreign key" in result.message
        assert "users" in result.details["missing_fks"]
        assert "backtest_runs" not in result.details["missing_fks"]
    
    async def test_extra_foreign_keys_allowed(self):
        """Test that extra foreign keys don't cause failure.
        
        **Validates: Requirements 2.2, 2.3, 2.4**
        """
        mock_conn = AsyncMock()
        # Database has more FKs than expected
        mock_conn.fetch.return_value = [
            {"constraint_name": "fk_table_runs", "referenced_table": "backtest_runs"},
            {"constraint_name": "fk_table_extra", "referenced_table": "extra_table"},
        ]
        
        mock_pool = create_mock_pool(mock_conn)
        result = await verify_foreign_keys(mock_pool, "backtest_trades", ["backtest_runs"])
        
        assert result.passed is True
        assert "extra_table" in result.details["actual_fks"]
    
    async def test_empty_expected_foreign_keys(self):
        """Test foreign key verification with empty expected list.
        
        **Validates: Requirements 2.2, 2.3, 2.4**
        """
        mock_conn = AsyncMock()
        mock_conn.fetch.return_value = []
        
        mock_pool = create_mock_pool(mock_conn)
        result = await verify_foreign_keys(mock_pool, "test_table", [])
        
        assert result.passed is True
        assert "all 0 expected foreign key" in result.message
    
    async def test_backtest_trades_foreign_key(self):
        """Test foreign key verification for backtest_trades table.
        
        **Validates: Requirements 2.2**
        """
        mock_conn = AsyncMock()
        mock_conn.fetch.return_value = [
            {"constraint_name": "fk_backtest_trades_run_id", "referenced_table": "backtest_runs"},
        ]
        
        mock_pool = create_mock_pool(mock_conn)
        expected_fks = EXPECTED_FOREIGN_KEYS["backtest_trades"]
        result = await verify_foreign_keys(mock_pool, "backtest_trades", expected_fks)
        
        assert result.passed is True
        assert result.details["table_name"] == "backtest_trades"
    
    async def test_backtest_equity_curve_foreign_key(self):
        """Test foreign key verification for backtest_equity_curve table.
        
        **Validates: Requirements 2.3**
        """
        mock_conn = AsyncMock()
        mock_conn.fetch.return_value = [
            {"constraint_name": "fk_backtest_equity_curve_run_id", "referenced_table": "backtest_runs"},
        ]
        
        mock_pool = create_mock_pool(mock_conn)
        expected_fks = EXPECTED_FOREIGN_KEYS["backtest_equity_curve"]
        result = await verify_foreign_keys(mock_pool, "backtest_equity_curve", expected_fks)
        
        assert result.passed is True
        assert result.details["table_name"] == "backtest_equity_curve"
    
    async def test_backtest_metrics_foreign_key(self):
        """Test foreign key verification for backtest_metrics table.
        
        **Validates: Requirements 2.4**
        """
        mock_conn = AsyncMock()
        mock_conn.fetch.return_value = [
            {"constraint_name": "fk_backtest_metrics_run_id", "referenced_table": "backtest_runs"},
        ]
        
        mock_pool = create_mock_pool(mock_conn)
        expected_fks = EXPECTED_FOREIGN_KEYS["backtest_metrics"]
        result = await verify_foreign_keys(mock_pool, "backtest_metrics", expected_fks)
        
        assert result.passed is True
        assert result.details["table_name"] == "backtest_metrics"
    
    async def test_foreign_key_verification_database_error(self):
        """Test foreign key verification with database error.
        
        **Validates: Requirements 2.2, 2.3, 2.4**
        """
        mock_conn = AsyncMock()
        mock_conn.fetch.side_effect = asyncpg.PostgresError("Connection lost")
        
        mock_pool = create_mock_pool(mock_conn)
        result = await verify_foreign_keys(mock_pool, "backtest_trades", ["backtest_runs"])
        
        assert result.passed is False
        assert "Database error" in result.message
        assert result.error is not None
        assert "Connection lost" in result.error
    
    async def test_foreign_key_verification_unexpected_error(self):
        """Test foreign key verification with unexpected error.
        
        **Validates: Requirements 2.2, 2.3, 2.4**
        """
        mock_conn = AsyncMock()
        mock_conn.fetch.side_effect = RuntimeError("Unexpected error")
        
        mock_pool = create_mock_pool(mock_conn)
        result = await verify_foreign_keys(mock_pool, "backtest_trades", ["backtest_runs"])
        
        assert result.passed is False
        assert "Unexpected error" in result.message
        assert result.error is not None
    
    async def test_foreign_key_verification_queries_correct_schema(self):
        """Test that foreign key verification queries the correct schema.
        
        **Validates: Requirements 2.2, 2.3, 2.4**
        """
        mock_conn = AsyncMock()
        mock_conn.fetch.return_value = []
        
        mock_pool = create_mock_pool(mock_conn)
        await verify_foreign_keys(mock_pool, "test_table", ["backtest_runs"])
        
        # Verify the query was called with correct parameters
        mock_conn.fetch.assert_called_once()
        call_args = mock_conn.fetch.call_args
        query = call_args[0][0]
        table_name = call_args[0][1]
        
        assert "information_schema.table_constraints" in query
        assert "information_schema.constraint_column_usage" in query
        assert "table_schema = 'public'" in query
        assert "FOREIGN KEY" in query
        assert table_name == "test_table"
