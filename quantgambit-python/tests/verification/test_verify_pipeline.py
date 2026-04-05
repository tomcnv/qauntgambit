"""
Unit tests for pipeline verification script.

Tests the verify_pipeline.py script functions for decision recording verification.

Requirements: 4.2 - WHEN a decision is made THEN the DecisionRecorder SHALL record it to TimescaleDB (if enabled)
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import datetime, timezone
import os
import sys

# Add scripts directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'scripts'))

from verify_pipeline import (
    VerificationResult,
    verify_decision_recording,
    verify_backtest_execution,
    verify_warm_start_loading,
    verify_database_connection,
    verify_redis_connection,
    build_database_url,
    build_redis_url,
    get_decision_recorder_enabled,
    get_warm_start_enabled,
)


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
            details={"url": "postgresql://localhost:5432"},
            error="Connection refused"
        )
        
        assert result.name == "Test Check"
        assert result.passed is False
        assert result.message == "Check failed"
        assert result.error == "Connection refused"
    
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


class TestBuildDatabaseUrl:
    """Tests for build_database_url function."""
    
    def test_default_values(self):
        """Test database URL with default values."""
        with patch.dict(os.environ, {}, clear=True):
            url = build_database_url()
            assert "localhost" in url
            assert "5432" in url
            assert "platform_db" in url
            assert "platform@" in url
    
    def test_custom_values(self):
        """Test database URL with custom environment variables."""
        env = {
            "BOT_DB_HOST": "custom-host",
            "BOT_DB_PORT": "5433",
            "BOT_DB_NAME": "custom_db",
            "BOT_DB_USER": "custom_user",
            "BOT_DB_PASSWORD": "secret123",
        }
        with patch.dict(os.environ, env, clear=True):
            url = build_database_url()
            assert "custom-host" in url
            assert "5433" in url
            assert "custom_db" in url
            assert "custom_user:secret123@" in url
    
    def test_no_password(self):
        """Test database URL without password."""
        env = {
            "BOT_DB_HOST": "localhost",
            "BOT_DB_USER": "testuser",
            "BOT_DB_PASSWORD": "",
        }
        with patch.dict(os.environ, env, clear=True):
            url = build_database_url()
            assert "testuser@" in url
            assert ":@" not in url


class TestBuildRedisUrl:
    """Tests for build_redis_url function."""
    
    def test_default_value(self):
        """Test Redis URL with default value."""
        with patch.dict(os.environ, {}, clear=True):
            url = build_redis_url()
            assert url == "redis://localhost:6379"
    
    def test_bot_redis_url_takes_precedence(self):
        """Test BOT_REDIS_URL takes precedence over REDIS_URL."""
        env = {
            "BOT_REDIS_URL": "redis://bot-redis:6380",
            "REDIS_URL": "redis://fallback-redis:6381",
        }
        with patch.dict(os.environ, env, clear=True):
            url = build_redis_url()
            assert url == "redis://bot-redis:6380"
    
    def test_redis_url_fallback(self):
        """Test REDIS_URL is used when BOT_REDIS_URL is not set."""
        env = {
            "REDIS_URL": "redis://fallback-redis:6381",
        }
        with patch.dict(os.environ, env, clear=True):
            url = build_redis_url()
            assert url == "redis://fallback-redis:6381"


class TestGetDecisionRecorderEnabled:
    """Tests for get_decision_recorder_enabled function."""
    
    def test_default_is_true(self):
        """Test default value is True when env var not set."""
        with patch.dict(os.environ, {}, clear=True):
            assert get_decision_recorder_enabled() is True
    
    def test_truthy_values(self):
        """Test truthy values return True."""
        for value in ["true", "True", "TRUE", "yes", "Yes", "YES", "1"]:
            with patch.dict(os.environ, {"DECISION_RECORDER_ENABLED": value}, clear=True):
                assert get_decision_recorder_enabled() is True, f"Expected True for '{value}'"
    
    def test_falsy_values(self):
        """Test falsy values return False."""
        for value in ["false", "False", "FALSE", "no", "No", "NO", "0", ""]:
            with patch.dict(os.environ, {"DECISION_RECORDER_ENABLED": value}, clear=True):
                assert get_decision_recorder_enabled() is False, f"Expected False for '{value}'"


class TestGetWarmStartEnabled:
    """Tests for get_warm_start_enabled function."""
    
    def test_default_is_false(self):
        """Test default value is False when env var not set."""
        with patch.dict(os.environ, {}, clear=True):
            assert get_warm_start_enabled() is False
    
    def test_truthy_values(self):
        """Test truthy values return True."""
        for value in ["true", "True", "TRUE", "yes", "Yes", "YES", "1"]:
            with patch.dict(os.environ, {"BACKTEST_WARM_START_ENABLED": value}, clear=True):
                assert get_warm_start_enabled() is True, f"Expected True for '{value}'"
    
    def test_falsy_values(self):
        """Test falsy values return False."""
        for value in ["false", "False", "FALSE", "no", "No", "NO", "0", ""]:
            with patch.dict(os.environ, {"BACKTEST_WARM_START_ENABLED": value}, clear=True):
                assert get_warm_start_enabled() is False, f"Expected False for '{value}'"


class MockAsyncConnection:
    """Mock async database connection."""
    
    def __init__(self, fetchval_results=None, fetch_results=None):
        self.fetchval_results = fetchval_results or {}
        self.fetch_results = fetch_results or {}
        self._fetchval_call_count = 0
        self._fetch_call_count = 0
    
    async def fetchval(self, query, *args):
        self._fetchval_call_count += 1
        # Return results based on call order
        if self._fetchval_call_count in self.fetchval_results:
            return self.fetchval_results[self._fetchval_call_count]
        return None
    
    async def fetch(self, query, *args):
        self._fetch_call_count += 1
        if self._fetch_call_count in self.fetch_results:
            return self.fetch_results[self._fetch_call_count]
        return []


class MockAsyncPool:
    """Mock async database pool."""
    
    def __init__(self, connection=None):
        self._connection = connection or MockAsyncConnection()
    
    def acquire(self):
        return MockAsyncContextManager(self._connection)
    
    async def close(self):
        pass


class MockAsyncContextManager:
    """Mock async context manager for pool.acquire()."""
    
    def __init__(self, connection):
        self._connection = connection
    
    async def __aenter__(self):
        return self._connection
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass


@pytest.mark.asyncio
class TestVerifyDecisionRecording:
    """Tests for verify_decision_recording function.
    
    **Validates: Requirements 4.2**
    """
    
    async def test_table_does_not_exist(self):
        """Test verification fails when decision_events table doesn't exist.
        
        **Validates: Requirements 4.2**
        """
        # Mock connection that returns False for table existence check
        conn = MockAsyncConnection(fetchval_results={1: False})
        pool = MockAsyncPool(conn)
        redis_client = MagicMock()
        
        with patch.dict(os.environ, {"DECISION_RECORDER_ENABLED": "true"}, clear=True):
            result = await verify_decision_recording(pool, redis_client)
        
        assert result.passed is False
        assert result.name == "Decision Recording"
        assert "does not exist" in result.message
        assert result.details["table_exists"] is False
    
    async def test_recording_enabled_with_recent_records(self):
        """Test verification passes when recording is enabled and has recent records.
        
        **Validates: Requirements 4.2**
        """
        now = datetime.now(timezone.utc)
        # Mock connection: table exists, total=1000, recent=50, latest_ts=now
        conn = MockAsyncConnection(
            fetchval_results={
                1: True,   # table exists
                2: 1000,   # total count
                3: 50,     # recent count (24h)
                4: now,    # latest timestamp
            },
            fetch_results={
                1: [  # result breakdown
                    {"result": "APPROVE", "count": 40},
                    {"result": "REJECT", "count": 10},
                ]
            }
        )
        pool = MockAsyncPool(conn)
        redis_client = MagicMock()
        
        with patch.dict(os.environ, {"DECISION_RECORDER_ENABLED": "true"}, clear=True):
            result = await verify_decision_recording(pool, redis_client)
        
        assert result.passed is True
        assert result.name == "Decision Recording"
        assert "active" in result.message
        assert "50" in result.message  # recent count
        assert result.details["recorder_enabled"] is True
        assert result.details["total_count"] == 1000
        assert result.details["recent_count_24h"] == 50
    
    async def test_recording_enabled_no_recent_records(self):
        """Test verification passes when recording is enabled but no recent records.
        
        **Validates: Requirements 4.2**
        """
        old_ts = datetime(2024, 1, 1, tzinfo=timezone.utc)
        # Mock connection: table exists, total=500, recent=0, latest_ts=old
        conn = MockAsyncConnection(
            fetchval_results={
                1: True,   # table exists
                2: 500,    # total count
                3: 0,      # recent count (24h)
                4: old_ts, # latest timestamp
            },
            fetch_results={1: []}
        )
        pool = MockAsyncPool(conn)
        redis_client = MagicMock()
        
        with patch.dict(os.environ, {"DECISION_RECORDER_ENABLED": "true"}, clear=True):
            result = await verify_decision_recording(pool, redis_client)
        
        assert result.passed is True
        assert "no recent decisions" in result.message.lower()
        assert result.details["total_count"] == 500
        assert result.details["recent_count_24h"] == 0
        assert "note" in result.details
    
    async def test_recording_enabled_no_records_at_all(self):
        """Test verification passes when recording is enabled but no records exist.
        
        **Validates: Requirements 4.2**
        """
        # Mock connection: table exists, total=0, recent=0, latest_ts=None
        conn = MockAsyncConnection(
            fetchval_results={
                1: True,  # table exists
                2: 0,     # total count
                3: 0,     # recent count (24h)
                4: None,  # latest timestamp
            },
            fetch_results={1: []}
        )
        pool = MockAsyncPool(conn)
        redis_client = MagicMock()
        
        with patch.dict(os.environ, {"DECISION_RECORDER_ENABLED": "true"}, clear=True):
            result = await verify_decision_recording(pool, redis_client)
        
        assert result.passed is True
        assert "no decisions recorded yet" in result.message.lower()
        assert result.details["total_count"] == 0
        assert result.details["recent_count_24h"] == 0
    
    async def test_recording_disabled(self):
        """Test verification passes when recording is disabled.
        
        **Validates: Requirements 4.2**
        """
        # Mock connection: table exists, total=100
        conn = MockAsyncConnection(
            fetchval_results={
                1: True,  # table exists
                2: 100,   # total count
                3: 0,     # recent count (24h)
                4: None,  # latest timestamp
            },
            fetch_results={1: []}
        )
        pool = MockAsyncPool(conn)
        redis_client = MagicMock()
        
        with patch.dict(os.environ, {"DECISION_RECORDER_ENABLED": "false"}, clear=True):
            result = await verify_decision_recording(pool, redis_client)
        
        assert result.passed is True
        assert "disabled" in result.message.lower()
        assert result.details["recorder_enabled"] is False
        assert result.details["env_var_value"] == "false"
    
    async def test_database_error(self):
        """Test verification fails on database error.
        
        **Validates: Requirements 4.2**
        """
        import asyncpg
        
        # Create a mock pool that raises an error
        pool = MagicMock()
        mock_conn = MagicMock()
        mock_conn.fetchval = AsyncMock(side_effect=asyncpg.PostgresError("Connection lost"))
        
        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_cm.__aexit__ = AsyncMock(return_value=None)
        pool.acquire.return_value = mock_cm
        
        redis_client = MagicMock()
        
        with patch.dict(os.environ, {"DECISION_RECORDER_ENABLED": "true"}, clear=True):
            result = await verify_decision_recording(pool, redis_client)
        
        assert result.passed is False
        assert "Database error" in result.message
        assert result.error is not None
    
    async def test_unexpected_error(self):
        """Test verification fails on unexpected error.
        
        **Validates: Requirements 4.2**
        """
        # Create a mock pool that raises an unexpected error
        pool = MagicMock()
        mock_conn = MagicMock()
        mock_conn.fetchval = AsyncMock(side_effect=RuntimeError("Unexpected error"))
        
        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_cm.__aexit__ = AsyncMock(return_value=None)
        pool.acquire.return_value = mock_cm
        
        redis_client = MagicMock()
        
        with patch.dict(os.environ, {"DECISION_RECORDER_ENABLED": "true"}, clear=True):
            result = await verify_decision_recording(pool, redis_client)
        
        assert result.passed is False
        assert "Unexpected error" in result.message
        assert result.error is not None


@pytest.mark.asyncio
class TestVerifyDatabaseConnection:
    """Tests for verify_database_connection function."""
    
    async def test_successful_connection(self):
        """Test successful database connection."""
        import asyncpg
        
        with patch('verify_pipeline.asyncpg.create_pool') as mock_create_pool:
            mock_pool = MagicMock()
            mock_conn = MagicMock()
            mock_conn.fetchval = AsyncMock(return_value="PostgreSQL 14.0")
            
            mock_cm = MagicMock()
            mock_cm.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_cm.__aexit__ = AsyncMock(return_value=None)
            mock_pool.acquire.return_value = mock_cm
            
            # create_pool is async, so we need to return a coroutine
            mock_create_pool.return_value = mock_pool
            mock_create_pool.side_effect = None
            
            # Use AsyncMock for the async function
            async def mock_create_pool_coro(*args, **kwargs):
                return mock_pool
            
            mock_create_pool.side_effect = mock_create_pool_coro
            
            pool, result = await verify_database_connection("postgresql://user:pass@localhost:5432/db")
        
        assert pool is not None
        assert result.passed is True
        assert "Successfully connected" in result.message
        assert "***@localhost" in result.details["url"]  # Password masked
    
    async def test_connection_error(self):
        """Test database connection error."""
        with patch('verify_pipeline.asyncpg.create_pool') as mock_create_pool:
            mock_create_pool.side_effect = OSError("Connection refused")
            
            pool, result = await verify_database_connection("postgresql://user:pass@localhost:5432/db")
        
        assert pool is None
        assert result.passed is False
        assert "Could not connect" in result.message
        assert result.error is not None
    
    async def test_invalid_database(self):
        """Test connection to non-existent database."""
        import asyncpg
        
        with patch('verify_pipeline.asyncpg.create_pool') as mock_create_pool:
            mock_create_pool.side_effect = asyncpg.InvalidCatalogNameError("database does not exist")
            
            pool, result = await verify_database_connection("postgresql://user:pass@localhost:5432/nonexistent")
        
        assert pool is None
        assert result.passed is False
        assert "does not exist" in result.message
    
    async def test_invalid_password(self):
        """Test connection with invalid password."""
        import asyncpg
        
        with patch('verify_pipeline.asyncpg.create_pool') as mock_create_pool:
            mock_create_pool.side_effect = asyncpg.InvalidPasswordError("password authentication failed")
            
            pool, result = await verify_database_connection("postgresql://user:wrongpass@localhost:5432/db")
        
        assert pool is None
        assert result.passed is False
        assert "Invalid database credentials" in result.message


@pytest.mark.asyncio
class TestVerifyRedisConnection:
    """Tests for verify_redis_connection function."""
    
    async def test_successful_connection(self):
        """Test successful Redis connection."""
        with patch('verify_pipeline.redis.from_url') as mock_from_url:
            mock_client = MagicMock()
            mock_client.info = AsyncMock(return_value={"redis_version": "7.0.0"})
            mock_client.close = AsyncMock()
            mock_from_url.return_value = mock_client
            
            client, result = await verify_redis_connection("redis://localhost:6379")
        
        assert client is not None
        assert result.passed is True
        assert "Successfully connected" in result.message
        assert result.details["redis_version"] == "7.0.0"
    
    async def test_connection_error(self):
        """Test Redis connection error."""
        import redis.asyncio as redis_module
        
        with patch('verify_pipeline.redis.from_url') as mock_from_url:
            mock_client = MagicMock()
            mock_client.info = AsyncMock(side_effect=redis_module.ConnectionError("Connection refused"))
            mock_from_url.return_value = mock_client
            
            client, result = await verify_redis_connection("redis://localhost:6379")
        
        assert client is None
        assert result.passed is False
        assert "Could not connect" in result.message
        assert result.error is not None
    
    async def test_unexpected_error(self):
        """Test Redis unexpected error."""
        import redis.asyncio as redis_module
        
        with patch('verify_pipeline.redis.from_url') as mock_from_url:
            mock_client = MagicMock()
            # Use a generic Exception that will be caught by the general except clause
            mock_client.info = AsyncMock(side_effect=ValueError("Unexpected error"))
            mock_from_url.return_value = mock_client
            
            client, result = await verify_redis_connection("redis://localhost:6379")
        
        assert client is None
        assert result.passed is False
        assert "Unexpected error" in result.message
        assert result.error is not None


class MockBacktestAsyncConnection:
    """Mock async database connection for backtest verification tests."""
    
    def __init__(self, fetchval_results=None, fetch_results=None, fetchrow_results=None):
        self.fetchval_results = fetchval_results or {}
        self.fetch_results = fetch_results or {}
        self.fetchrow_results = fetchrow_results or {}
        self._fetchval_call_count = 0
        self._fetch_call_count = 0
        self._fetchrow_call_count = 0
    
    async def fetchval(self, query, *args):
        self._fetchval_call_count += 1
        if self._fetchval_call_count in self.fetchval_results:
            return self.fetchval_results[self._fetchval_call_count]
        return None
    
    async def fetch(self, query, *args):
        self._fetch_call_count += 1
        if self._fetch_call_count in self.fetch_results:
            return self.fetch_results[self._fetch_call_count]
        return []
    
    async def fetchrow(self, query, *args):
        self._fetchrow_call_count += 1
        if self._fetchrow_call_count in self.fetchrow_results:
            return self.fetchrow_results[self._fetchrow_call_count]
        return None


class MockBacktestAsyncPool:
    """Mock async database pool for backtest verification tests."""
    
    def __init__(self, connection=None):
        self._connection = connection or MockBacktestAsyncConnection()
    
    def acquire(self):
        return MockAsyncContextManager(self._connection)
    
    async def close(self):
        pass


@pytest.mark.asyncio
class TestVerifyBacktestExecution:
    """Tests for verify_backtest_execution function.
    
    **Validates: Requirements 5.1, 5.2, 5.3**
    """
    
    async def test_table_does_not_exist(self):
        """Test verification fails when backtest_runs table doesn't exist.
        
        **Validates: Requirements 5.3**
        """
        # Mock connection that returns False for table existence check
        conn = MockBacktestAsyncConnection(fetchval_results={1: False})
        pool = MockBacktestAsyncPool(conn)
        
        result = await verify_backtest_execution(pool)
        
        assert result.passed is False
        assert result.name == "Backtest Execution"
        assert "does not exist" in result.message
        assert result.details["table_exists"] is False
    
    async def test_missing_required_columns(self):
        """Test verification fails when required columns are missing.
        
        **Validates: Requirements 5.3**
        """
        # Mock connection: table exists but missing columns
        conn = MockBacktestAsyncConnection(
            fetchval_results={1: True},  # table exists
            fetch_results={
                1: [  # existing columns - missing 'config'
                    {"column_name": "run_id"},
                    {"column_name": "tenant_id"},
                    {"column_name": "bot_id"},
                    {"column_name": "status"},
                    {"column_name": "started_at"},
                ]
            }
        )
        pool = MockBacktestAsyncPool(conn)
        
        result = await verify_backtest_execution(pool)
        
        assert result.passed is False
        assert "missing required columns" in result.message
        assert "config" in result.details["missing_columns"]
    
    async def test_executor_import_failure(self):
        """Test verification fails when BacktestExecutor cannot be imported.
        
        **Validates: Requirements 5.1, 5.2**
        """
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        
        # Mock connection: table exists with all columns, but executor import fails
        conn = MockBacktestAsyncConnection(
            fetchval_results={
                1: True,  # table exists
                2: 5,     # total count
            },
            fetch_results={
                1: [  # existing columns
                    {"column_name": "run_id"},
                    {"column_name": "tenant_id"},
                    {"column_name": "bot_id"},
                    {"column_name": "status"},
                    {"column_name": "started_at"},
                    {"column_name": "config"},
                ],
                2: [  # status breakdown
                    {"status": "finished", "count": 3},
                    {"status": "failed", "count": 2},
                ]
            },
            fetchrow_results={
                1: {
                    "run_id": "test-run-123",
                    "status": "finished",
                    "started_at": now,
                    "finished_at": now,
                    "symbol": "BTC-USDT",
                }
            }
        )
        pool = MockBacktestAsyncPool(conn)
        
        # Mock the import to fail
        with patch.dict('sys.modules', {'quantgambit.backtesting.executor': None}):
            with patch('builtins.__import__', side_effect=ImportError("Module not found")):
                result = await verify_backtest_execution(pool)
        
        assert result.passed is False
        assert "cannot be imported" in result.message
    
    async def test_verification_passes_with_runs(self):
        """Test verification passes when table exists with backtest runs.
        
        **Validates: Requirements 5.1, 5.2, 5.3**
        """
        from datetime import datetime, timezone
        import uuid
        
        now = datetime.now(timezone.utc)
        run_id = uuid.uuid4()
        
        # Mock connection: table exists with all columns and runs
        conn = MockBacktestAsyncConnection(
            fetchval_results={
                1: True,  # table exists
                2: 10,    # total count
            },
            fetch_results={
                1: [  # existing columns
                    {"column_name": "run_id"},
                    {"column_name": "tenant_id"},
                    {"column_name": "bot_id"},
                    {"column_name": "status"},
                    {"column_name": "started_at"},
                    {"column_name": "config"},
                    {"column_name": "finished_at"},
                    {"column_name": "symbol"},
                ],
                2: [  # status breakdown
                    {"status": "finished", "count": 7},
                    {"status": "failed", "count": 2},
                    {"status": "running", "count": 1},
                ]
            },
            fetchrow_results={
                1: {
                    "run_id": run_id,
                    "status": "finished",
                    "started_at": now,
                    "finished_at": now,
                    "symbol": "BTC-USDT",
                }
            }
        )
        pool = MockBacktestAsyncPool(conn)
        
        result = await verify_backtest_execution(pool)
        
        assert result.passed is True
        assert result.name == "Backtest Execution"
        assert "10 total runs" in result.message
        assert "7 completed" in result.message
        assert "2 failed" in result.message
        assert result.details["total_runs"] == 10
        assert result.details["table_exists"] is True
        assert result.details["executor_importable"] is True
        assert result.details["latest_run"] is not None
        assert result.details["latest_run"]["status"] == "finished"
    
    async def test_verification_passes_no_runs(self):
        """Test verification passes when table exists but no runs recorded.
        
        **Validates: Requirements 5.3**
        """
        # Mock connection: table exists with all columns but no runs
        conn = MockBacktestAsyncConnection(
            fetchval_results={
                1: True,  # table exists
                2: 0,     # total count
            },
            fetch_results={
                1: [  # existing columns
                    {"column_name": "run_id"},
                    {"column_name": "tenant_id"},
                    {"column_name": "bot_id"},
                    {"column_name": "status"},
                    {"column_name": "started_at"},
                    {"column_name": "config"},
                ],
                2: []  # no status breakdown
            },
            fetchrow_results={1: None}  # no latest run
        )
        pool = MockBacktestAsyncPool(conn)
        
        result = await verify_backtest_execution(pool)
        
        assert result.passed is True
        assert "No backtest runs recorded yet" in result.message
        assert result.details["total_runs"] == 0
        assert result.details["latest_run"] is None
    
    async def test_database_error(self):
        """Test verification fails on database error.
        
        **Validates: Requirements 5.3**
        """
        import asyncpg
        
        # Create a mock pool that raises an error
        pool = MagicMock()
        mock_conn = MagicMock()
        mock_conn.fetchval = AsyncMock(side_effect=asyncpg.PostgresError("Connection lost"))
        
        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_cm.__aexit__ = AsyncMock(return_value=None)
        pool.acquire.return_value = mock_cm
        
        result = await verify_backtest_execution(pool)
        
        assert result.passed is False
        assert "Database error" in result.message
        assert result.error is not None
    
    async def test_unexpected_error(self):
        """Test verification fails on unexpected error.
        
        **Validates: Requirements 5.3**
        """
        # Create a mock pool that raises an unexpected error
        pool = MagicMock()
        mock_conn = MagicMock()
        mock_conn.fetchval = AsyncMock(side_effect=RuntimeError("Unexpected error"))
        
        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_cm.__aexit__ = AsyncMock(return_value=None)
        pool.acquire.return_value = mock_cm
        
        result = await verify_backtest_execution(pool)
        
        assert result.passed is False
        assert "Unexpected error" in result.message
        assert result.error is not None
    
    async def test_completed_status_variants(self):
        """Test verification correctly counts both 'finished' and 'completed' statuses.
        
        **Validates: Requirements 5.3**
        """
        from datetime import datetime, timezone
        import uuid
        
        now = datetime.now(timezone.utc)
        run_id = uuid.uuid4()
        
        # Mock connection with both 'finished' and 'completed' statuses
        conn = MockBacktestAsyncConnection(
            fetchval_results={
                1: True,  # table exists
                2: 15,    # total count
            },
            fetch_results={
                1: [  # existing columns
                    {"column_name": "run_id"},
                    {"column_name": "tenant_id"},
                    {"column_name": "bot_id"},
                    {"column_name": "status"},
                    {"column_name": "started_at"},
                    {"column_name": "config"},
                ],
                2: [  # status breakdown with both variants
                    {"status": "finished", "count": 5},
                    {"status": "completed", "count": 3},
                    {"status": "failed", "count": 4},
                    {"status": "running", "count": 3},
                ]
            },
            fetchrow_results={
                1: {
                    "run_id": run_id,
                    "status": "running",
                    "started_at": now,
                    "finished_at": None,
                    "symbol": "ETH-USDT",
                }
            }
        )
        pool = MockBacktestAsyncPool(conn)
        
        result = await verify_backtest_execution(pool)
        
        assert result.passed is True
        assert "15 total runs" in result.message
        # Should count both 'finished' (5) and 'completed' (3) = 8
        assert "8 completed" in result.message
        assert "4 failed" in result.message


@pytest.mark.asyncio
class TestVerifyWarmStartLoading:
    """Tests for verify_warm_start_loading function.
    
    **Validates: Requirements 5.4**
    """
    
    async def test_warm_start_disabled(self):
        """Test verification passes when warm start is disabled.
        
        **Validates: Requirements 5.4**
        """
        pool = MagicMock()
        redis_client = MagicMock()
        
        with patch.dict(os.environ, {
            "BACKTEST_WARM_START_ENABLED": "false",
            "BACKTEST_WARM_START_STALE_SEC": "300.0",
            "TENANT_ID": "default",
            "BOT_ID": "default",
        }, clear=True):
            result = await verify_warm_start_loading(pool, redis_client)
        
        assert result.passed is True
        assert result.name == "Warm Start Loading"
        assert "disabled" in result.message.lower()
    
    async def test_loader_import_failure(self):
        """Test verification fails when WarmStartLoader cannot be imported.
        
        **Validates: Requirements 5.4**
        """
        pool = MagicMock()
        redis_client = MagicMock()
        
        with patch.dict(os.environ, {"BACKTEST_WARM_START_ENABLED": "true"}, clear=True):
            # Mock the import to fail
            with patch('builtins.__import__', side_effect=ImportError("Module not found")):
                result = await verify_warm_start_loading(pool, redis_client)
        
        assert result.passed is False
        assert "cannot be imported" in result.message
    
    async def test_config_import_failure(self):
        """Test verification fails when ExecutorConfig cannot be imported.
        
        **Validates: Requirements 5.4**
        """
        pool = MagicMock()
        redis_client = MagicMock()
        
        with patch.dict(os.environ, {"BACKTEST_WARM_START_ENABLED": "true"}, clear=True):
            # Mock WarmStartLoader import to succeed but ExecutorConfig to fail
            def mock_import(name, *args, **kwargs):
                if 'warm_start' in name:
                    return MagicMock()
                elif 'executor' in name:
                    raise ImportError("ExecutorConfig not found")
                return __builtins__.__import__(name, *args, **kwargs)
            
            with patch('builtins.__import__', side_effect=mock_import):
                result = await verify_warm_start_loading(pool, redis_client)
        
        # Should fail because ExecutorConfig cannot be imported
        assert result.passed is False
    
    async def test_redis_not_available_when_enabled(self):
        """Test verification fails when warm start is enabled but Redis is not available.
        
        **Validates: Requirements 5.4**
        """
        pool = MagicMock()
        redis_client = None  # Redis not available
        
        with patch.dict(os.environ, {
            "BACKTEST_WARM_START_ENABLED": "true",
            "BACKTEST_WARM_START_STALE_SEC": "300.0",
            "TENANT_ID": "default",
            "BOT_ID": "default",
        }, clear=True):
            result = await verify_warm_start_loading(pool, redis_client)
        
        assert result.passed is False
        assert "Redis" in result.message
    
    async def test_warm_start_enabled_loader_instantiated(self):
        """Test verification passes when warm start is enabled and loader can be instantiated.
        
        **Validates: Requirements 5.4**
        """
        pool = MagicMock()
        redis_client = MagicMock()
        
        # Create a mock WarmStartState
        mock_state = MagicMock()
        mock_state.timestamp = datetime.now(timezone.utc)
        mock_state.positions = []
        mock_state.is_stale = MagicMock(return_value=False)
        
        # Create a mock WarmStartLoader
        mock_loader_instance = MagicMock()
        mock_loader_instance.tenant_id = "default"
        mock_loader_instance.bot_id = "default"
        mock_loader_instance.load_current_state = AsyncMock(return_value=mock_state)
        
        mock_loader_class = MagicMock(return_value=mock_loader_instance)
        
        # Create a mock ExecutorConfig
        mock_config = MagicMock()
        mock_config.warm_start_enabled = True
        mock_config_class = MagicMock()
        mock_config_class.from_env = MagicMock(return_value=mock_config)
        
        with patch.dict(os.environ, {
            "BACKTEST_WARM_START_ENABLED": "true",
            "BACKTEST_WARM_START_STALE_SEC": "300.0",
            "TENANT_ID": "default",
            "BOT_ID": "default",
        }, clear=True):
            with patch.dict('sys.modules', {
                'quantgambit.integration.warm_start': MagicMock(
                    WarmStartLoader=mock_loader_class,
                    WarmStartState=MagicMock(),
                ),
                'quantgambit.backtesting.executor': MagicMock(
                    ExecutorConfig=mock_config_class,
                ),
            }):
                result = await verify_warm_start_loading(pool, redis_client)
        
        assert result.passed is True
        assert "enabled" in result.message.lower()
    
    async def test_warm_start_state_load_failure(self):
        """Test verification passes with warning when state loading fails.
        
        **Validates: Requirements 5.4**
        """
        pool = MagicMock()
        redis_client = MagicMock()
        
        # Create a mock WarmStartLoader that fails to load state
        mock_loader_instance = MagicMock()
        mock_loader_instance.tenant_id = "default"
        mock_loader_instance.bot_id = "default"
        mock_loader_instance.load_current_state = AsyncMock(
            side_effect=Exception("No state available")
        )
        
        mock_loader_class = MagicMock(return_value=mock_loader_instance)
        
        # Create a mock ExecutorConfig
        mock_config = MagicMock()
        mock_config.warm_start_enabled = True
        mock_config_class = MagicMock()
        mock_config_class.from_env = MagicMock(return_value=mock_config)
        
        with patch.dict(os.environ, {
            "BACKTEST_WARM_START_ENABLED": "true",
            "BACKTEST_WARM_START_STALE_SEC": "300.0",
            "TENANT_ID": "default",
            "BOT_ID": "default",
        }, clear=True):
            with patch.dict('sys.modules', {
                'quantgambit.integration.warm_start': MagicMock(
                    WarmStartLoader=mock_loader_class,
                    WarmStartState=MagicMock(),
                ),
                'quantgambit.backtesting.executor': MagicMock(
                    ExecutorConfig=mock_config_class,
                ),
            }):
                result = await verify_warm_start_loading(pool, redis_client)
        
        # Should still pass - state loading failure is OK if no state exists
        assert result.passed is True
        assert "No current state available" in result.message or "loader instantiated" in result.message
    
    async def test_warm_start_stale_state(self):
        """Test verification passes with warning when state is stale.
        
        **Validates: Requirements 5.4**
        """
        pool = MagicMock()
        redis_client = MagicMock()
        
        # Create a mock WarmStartState that is stale
        mock_state = MagicMock()
        mock_state.timestamp = datetime.now(timezone.utc)
        mock_state.positions = [{"symbol": "BTC-USDT", "size": 1.0}]
        mock_state.is_stale = MagicMock(return_value=True)
        
        # Create a mock WarmStartLoader
        mock_loader_instance = MagicMock()
        mock_loader_instance.tenant_id = "default"
        mock_loader_instance.bot_id = "default"
        mock_loader_instance.load_current_state = AsyncMock(return_value=mock_state)
        
        mock_loader_class = MagicMock(return_value=mock_loader_instance)
        
        # Create a mock ExecutorConfig
        mock_config = MagicMock()
        mock_config.warm_start_enabled = True
        mock_config_class = MagicMock()
        mock_config_class.from_env = MagicMock(return_value=mock_config)
        
        with patch.dict(os.environ, {
            "BACKTEST_WARM_START_ENABLED": "true",
            "BACKTEST_WARM_START_STALE_SEC": "300.0",
            "TENANT_ID": "default",
            "BOT_ID": "default",
        }, clear=True):
            with patch.dict('sys.modules', {
                'quantgambit.integration.warm_start': MagicMock(
                    WarmStartLoader=mock_loader_class,
                    WarmStartState=MagicMock(),
                ),
                'quantgambit.backtesting.executor': MagicMock(
                    ExecutorConfig=mock_config_class,
                ),
            }):
                result = await verify_warm_start_loading(pool, redis_client)
        
        assert result.passed is True
        assert "stale" in result.message.lower()


# =============================================================================
# Integration Tests for Pipeline Verification
# =============================================================================
# These tests verify the complete flows work together with real services.
# They require REAL_SERVICES=true environment variable to run.
#
# **Validates: Requirements 4.2, 5.1, 5.2, 5.3, 5.4**
# =============================================================================


def _require_real_services():
    """Skip test if REAL_SERVICES is not enabled."""
    if os.getenv("REAL_SERVICES", "").lower() not in {"1", "true", "yes"}:
        pytest.skip("REAL_SERVICES not enabled - skipping integration test")


def _get_timescale_dsn() -> str:
    """Build TimescaleDB connection string from environment."""
    explicit = os.getenv("BOT_TIMESCALE_URL") or os.getenv("TIMESCALE_URL")
    if explicit:
        return explicit
    host = os.getenv("BOT_DB_HOST", "localhost")
    port = os.getenv("BOT_DB_PORT", "5432")
    name = os.getenv("BOT_DB_NAME", "platform_db")
    user = os.getenv("BOT_DB_USER", "platform")
    password = os.getenv("BOT_DB_PASSWORD", "")
    auth = f"{user}:{password}@" if password else f"{user}@"
    return f"postgresql://{auth}{host}:{port}/{name}"


def _get_redis_url() -> str:
    """Get Redis URL from environment."""
    return os.getenv("BOT_REDIS_URL") or os.getenv("REDIS_URL") or "redis://localhost:6379"


@pytest.mark.integration
class TestDecisionRecordingIntegration:
    """Integration tests for decision recording verification flow.
    
    Tests the complete decision recording verification flow with real database.
    
    **Validates: Requirements 4.2**
    - WHEN a decision is made THEN the DecisionRecorder SHALL record it to TimescaleDB (if enabled)
    """
    
    def test_decision_recording_verification_flow(self):
        """Test complete decision recording verification flow with real database.
        
        **Validates: Requirements 4.2**
        """
        _require_real_services()
        
        async def run_test():
            import asyncpg
            import redis.asyncio as redis_module
            
            dsn = _get_timescale_dsn()
            redis_url = _get_redis_url()
            
            pool = None
            redis_client = None
            
            try:
                # Connect to real database
                pool = await asyncpg.create_pool(dsn, min_size=1, max_size=3)
                
                # Connect to real Redis
                redis_client = redis_module.from_url(redis_url, decode_responses=True)
                await redis_client.ping()
                
                # Run the verification function
                result = await verify_decision_recording(pool, redis_client)
                
                # Verify the result structure
                assert result.name == "Decision Recording"
                assert isinstance(result.passed, bool)
                assert isinstance(result.message, str)
                assert result.details is not None
                
                # Verify expected details are present
                assert "recorder_enabled" in result.details
                assert "env_var_value" in result.details
                
                # If table exists, verify additional details
                if result.details.get("table_exists"):
                    assert "total_count" in result.details
                    assert "recent_count_24h" in result.details
                
            finally:
                if pool:
                    await pool.close()
                if redis_client:
                    await redis_client.close()
        
        asyncio.run(run_test())
    
    def test_decision_recording_with_disabled_recorder(self):
        """Test decision recording verification when recorder is disabled.
        
        **Validates: Requirements 4.2**
        """
        _require_real_services()
        
        async def run_test():
            import asyncpg
            import redis.asyncio as redis_module
            
            dsn = _get_timescale_dsn()
            redis_url = _get_redis_url()
            
            pool = None
            redis_client = None
            
            try:
                pool = await asyncpg.create_pool(dsn, min_size=1, max_size=3)
                redis_client = redis_module.from_url(redis_url, decode_responses=True)
                await redis_client.ping()
                
                # Run with recorder disabled
                with patch.dict(os.environ, {"DECISION_RECORDER_ENABLED": "false"}):
                    result = await verify_decision_recording(pool, redis_client)
                
                # Should pass with disabled message
                assert result.passed is True
                assert "disabled" in result.message.lower()
                assert result.details["recorder_enabled"] is False
                
            finally:
                if pool:
                    await pool.close()
                if redis_client:
                    await redis_client.close()
        
        asyncio.run(run_test())


@pytest.mark.integration
class TestBacktestExecutionIntegration:
    """Integration tests for backtest execution verification flow.
    
    Tests the complete backtest execution verification flow with real database.
    
    **Validates: Requirements 5.1, 5.2, 5.3**
    - 5.1: WHEN a backtest is started THEN the BacktestExecutor SHALL load historical data from TimescaleDB
    - 5.2: WHEN a backtest is running THEN the BacktestExecutor SHALL process each candle through the signal pipeline
    - 5.3: WHEN a backtest completes THEN the BacktestExecutor SHALL store results in the backtest_runs table
    """
    
    def test_backtest_execution_verification_flow(self):
        """Test complete backtest execution verification flow with real database.
        
        **Validates: Requirements 5.1, 5.2, 5.3**
        """
        _require_real_services()
        
        async def run_test():
            import asyncpg
            
            dsn = _get_timescale_dsn()
            pool = None
            
            try:
                # Connect to real database
                pool = await asyncpg.create_pool(dsn, min_size=1, max_size=3)
                
                # Run the verification function
                result = await verify_backtest_execution(pool)
                
                # Verify the result structure
                assert result.name == "Backtest Execution"
                assert isinstance(result.passed, bool)
                assert isinstance(result.message, str)
                assert result.details is not None
                
                # Verify expected details are present
                assert "table_exists" in result.details
                assert "executor_importable" in result.details
                
                # If table exists, verify additional details
                if result.details.get("table_exists"):
                    assert "total_runs" in result.details
                    assert "status_breakdown" in result.details
                    assert "latest_run" in result.details
                
            finally:
                if pool:
                    await pool.close()
        
        asyncio.run(run_test())
    
    def test_backtest_table_schema_verification(self):
        """Test that backtest_runs table has correct schema.
        
        **Validates: Requirements 5.3**
        """
        _require_real_services()
        
        async def run_test():
            import asyncpg
            
            dsn = _get_timescale_dsn()
            pool = None
            
            try:
                pool = await asyncpg.create_pool(dsn, min_size=1, max_size=3)
                
                # Run verification
                result = await verify_backtest_execution(pool)
                
                # If table exists, verify no missing columns
                if result.details.get("table_exists"):
                    assert "missing_columns" not in result.details or \
                           len(result.details.get("missing_columns", [])) == 0, \
                           f"Missing columns: {result.details.get('missing_columns')}"
                
            finally:
                if pool:
                    await pool.close()
        
        asyncio.run(run_test())


@pytest.mark.integration
class TestWarmStartLoadingIntegration:
    """Integration tests for warm start loading verification flow.
    
    Tests the complete warm start loading verification flow with real services.
    
    **Validates: Requirements 5.4**
    - WHEN warm start is enabled THEN the BacktestExecutor SHALL load previous state from the database
    """
    
    def test_warm_start_loading_verification_flow(self):
        """Test complete warm start loading verification flow with real services.
        
        **Validates: Requirements 5.4**
        """
        _require_real_services()
        
        async def run_test():
            import asyncpg
            import redis.asyncio as redis_module
            
            dsn = _get_timescale_dsn()
            redis_url = _get_redis_url()
            
            pool = None
            redis_client = None
            
            try:
                # Connect to real database
                pool = await asyncpg.create_pool(dsn, min_size=1, max_size=3)
                
                # Connect to real Redis
                redis_client = redis_module.from_url(redis_url, decode_responses=True)
                await redis_client.ping()
                
                # Run the verification function
                result = await verify_warm_start_loading(pool, redis_client)
                
                # Verify the result structure
                assert result.name == "Warm Start Loading"
                assert isinstance(result.passed, bool)
                assert isinstance(result.message, str)
                assert result.details is not None
                
                # Verify expected details are present
                assert "warm_start_enabled" in result.details
                assert "env_var_value" in result.details
                assert "loader_importable" in result.details
                assert "config_importable" in result.details
                
            finally:
                if pool:
                    await pool.close()
                if redis_client:
                    await redis_client.close()
        
        asyncio.run(run_test())
    
    def test_warm_start_disabled_verification(self):
        """Test warm start verification when disabled.
        
        **Validates: Requirements 5.4**
        """
        _require_real_services()
        
        async def run_test():
            import asyncpg
            import redis.asyncio as redis_module
            
            dsn = _get_timescale_dsn()
            redis_url = _get_redis_url()
            
            pool = None
            redis_client = None
            
            try:
                pool = await asyncpg.create_pool(dsn, min_size=1, max_size=3)
                redis_client = redis_module.from_url(redis_url, decode_responses=True)
                await redis_client.ping()
                
                # Run with warm start disabled
                with patch.dict(os.environ, {"BACKTEST_WARM_START_ENABLED": "false"}):
                    result = await verify_warm_start_loading(pool, redis_client)
                
                # Should pass with disabled message
                assert result.passed is True
                assert "disabled" in result.message.lower()
                assert result.details["warm_start_enabled"] is False
                
            finally:
                if pool:
                    await pool.close()
                if redis_client:
                    await redis_client.close()
        
        asyncio.run(run_test())
    
    def test_warm_start_enabled_verification(self):
        """Test warm start verification when enabled.
        
        **Validates: Requirements 5.4**
        """
        _require_real_services()
        
        async def run_test():
            import asyncpg
            import redis.asyncio as redis_module
            
            dsn = _get_timescale_dsn()
            redis_url = _get_redis_url()
            
            pool = None
            redis_client = None
            
            try:
                pool = await asyncpg.create_pool(dsn, min_size=1, max_size=3)
                redis_client = redis_module.from_url(redis_url, decode_responses=True)
                await redis_client.ping()
                
                # Run with warm start enabled
                with patch.dict(os.environ, {
                    "BACKTEST_WARM_START_ENABLED": "true",
                    "TENANT_ID": "test-tenant",
                    "BOT_ID": "test-bot",
                }):
                    result = await verify_warm_start_loading(pool, redis_client)
                
                # Verify result
                assert isinstance(result.passed, bool)
                assert result.details["warm_start_enabled"] is True
                
                # If loader is importable, verify additional details
                if result.details.get("loader_importable"):
                    assert "config_warm_start_enabled" in result.details
                
            finally:
                if pool:
                    await pool.close()
                if redis_client:
                    await redis_client.close()
        
        asyncio.run(run_test())


@pytest.mark.integration
class TestFullPipelineVerificationIntegration:
    """Integration tests for the complete pipeline verification flow.
    
    Tests all verification functions together as they would run in production.
    
    **Validates: Requirements 4.2, 5.1, 5.2, 5.3, 5.4**
    """
    
    def test_full_pipeline_verification_flow(self):
        """Test complete pipeline verification flow with all checks.
        
        **Validates: Requirements 4.2, 5.1, 5.2, 5.3, 5.4**
        """
        _require_real_services()
        
        async def run_test():
            import asyncpg
            import redis.asyncio as redis_module
            
            dsn = _get_timescale_dsn()
            redis_url = _get_redis_url()
            
            pool = None
            redis_client = None
            results = []
            
            try:
                # Step 1: Verify database connection
                pool, db_result = await verify_database_connection(dsn)
                results.append(db_result)
                
                assert db_result.passed is True, f"Database connection failed: {db_result.error}"
                assert pool is not None
                
                # Step 2: Verify Redis connection
                redis_client, redis_result = await verify_redis_connection(redis_url)
                results.append(redis_result)
                
                # Redis may not be available in all environments
                if not redis_result.passed:
                    pytest.skip(f"Redis not available: {redis_result.error}")
                
                # Step 3: Verify decision recording
                decision_result = await verify_decision_recording(pool, redis_client)
                results.append(decision_result)
                
                # Decision recording should pass (either enabled or disabled)
                assert decision_result.passed is True, \
                    f"Decision recording verification failed: {decision_result.message}"
                
                # Step 4: Verify backtest execution
                backtest_result = await verify_backtest_execution(pool)
                results.append(backtest_result)
                
                # Backtest execution should pass
                assert backtest_result.passed is True, \
                    f"Backtest execution verification failed: {backtest_result.message}"
                
                # Step 5: Verify warm start loading
                warm_start_result = await verify_warm_start_loading(pool, redis_client)
                results.append(warm_start_result)
                
                # Warm start should pass (either enabled or disabled)
                assert warm_start_result.passed is True, \
                    f"Warm start verification failed: {warm_start_result.message}"
                
                # Verify all results have proper structure
                for result in results:
                    assert result.name is not None
                    assert isinstance(result.passed, bool)
                    assert result.message is not None
                
            finally:
                if pool:
                    await pool.close()
                if redis_client:
                    await redis_client.close()
        
        asyncio.run(run_test())
    
    def test_database_connection_verification(self):
        """Test database connection verification with real database.
        
        **Validates: Requirements 5.1, 5.3**
        """
        _require_real_services()
        
        async def run_test():
            dsn = _get_timescale_dsn()
            
            pool, result = await verify_database_connection(dsn)
            
            try:
                assert result.passed is True, f"Database connection failed: {result.error}"
                assert pool is not None
                assert "Successfully connected" in result.message
                assert result.details is not None
                assert "url" in result.details
                assert "version" in result.details
            finally:
                if pool:
                    await pool.close()
        
        asyncio.run(run_test())
    
    def test_redis_connection_verification(self):
        """Test Redis connection verification with real Redis.
        
        **Validates: Requirements 5.4**
        """
        _require_real_services()
        
        async def run_test():
            redis_url = _get_redis_url()
            
            client, result = await verify_redis_connection(redis_url)
            
            try:
                # Redis may not be available in all environments
                if not result.passed:
                    pytest.skip(f"Redis not available: {result.error}")
                
                assert client is not None
                assert "Successfully connected" in result.message
                assert result.details is not None
                assert "url" in result.details
                assert "redis_version" in result.details
            finally:
                if client:
                    await client.close()
        
        asyncio.run(run_test())
