"""
Unit tests for database migration runner script.

Tests the run_migrations.py script functions for migration execution,
idempotent behavior, and migration tracking.

Requirements: 2.5, 2.6
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from contextlib import asynccontextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
import asyncpg

import sys
import os

# Add scripts directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'scripts'))

from run_migrations import (
    MigrationResult,
    build_database_url,
    get_migration_files,
    compute_checksum,
    ensure_migrations_table,
    get_applied_migrations,
    record_migration,
    apply_migration,
    run_migrations,
)


def create_mock_pool(mock_conn):
    """Create a mock pool with proper async context manager support."""
    mock_pool = MagicMock()
    
    @asynccontextmanager
    async def mock_acquire():
        yield mock_conn
    
    mock_pool.acquire = mock_acquire
    return mock_pool


def setup_mock_transaction(mock_conn):
    """Set up mock connection with proper transaction context manager."""
    @asynccontextmanager
    async def mock_transaction():
        yield
    
    mock_conn.transaction = mock_transaction


class TestMigrationResult:
    """Tests for MigrationResult dataclass."""
    
    def test_create_applied_result(self):
        """Test creating a result for an applied migration."""
        result = MigrationResult(
            name="001_initial.sql",
            applied=True,
            message="Successfully applied migration '001_initial.sql'",
            error=None
        )
        
        assert result.name == "001_initial.sql"
        assert result.applied is True
        assert result.message == "Successfully applied migration '001_initial.sql'"
        assert result.error is None
    
    def test_create_skipped_result(self):
        """Test creating a result for a skipped migration."""
        result = MigrationResult(
            name="001_initial.sql",
            applied=False,
            message="Migration '001_initial.sql' already applied (skipped)",
            error=None
        )
        
        assert result.name == "001_initial.sql"
        assert result.applied is False
        assert result.message == "Migration '001_initial.sql' already applied (skipped)"
        assert result.error is None
    
    def test_create_error_result(self):
        """Test creating a result for a failed migration."""
        result = MigrationResult(
            name="001_initial.sql",
            applied=False,
            message="Database error applying migration '001_initial.sql'",
            error="relation already exists"
        )
        
        assert result.name == "001_initial.sql"
        assert result.applied is False
        assert result.error == "relation already exists"


class TestBuildDatabaseUrl:
    """Tests for build_database_url function."""
    
    def test_default_values(self):
        """Test database URL with default values."""
        with patch.dict(os.environ, {}, clear=True):
            url = build_database_url()
            assert "localhost" in url
            assert "5432" in url
            assert "platform_db" in url
            assert "platform" in url
    
    def test_custom_values(self):
        """Test database URL with custom environment variables."""
        env = {
            "BOT_DB_HOST": "db.example.com",
            "BOT_DB_PORT": "5433",
            "BOT_DB_NAME": "test_db",
            "BOT_DB_USER": "test_user",
            "BOT_DB_PASSWORD": "secret123",
        }
        with patch.dict(os.environ, env, clear=True):
            url = build_database_url()
            assert "db.example.com" in url
            assert "5433" in url
            assert "test_db" in url
            assert "test_user" in url
            assert "secret123" in url
    
    def test_no_password(self):
        """Test database URL without password."""
        env = {
            "BOT_DB_HOST": "localhost",
            "BOT_DB_USER": "platform",
            "BOT_DB_PASSWORD": "",
        }
        with patch.dict(os.environ, env, clear=True):
            url = build_database_url()
            # Should have user@ but no :password
            assert "platform@" in url
            assert ":@" not in url


class TestGetMigrationFiles:
    """Tests for get_migration_files function."""
    
    def test_returns_sorted_files(self):
        """Test that migration files are returned sorted by name."""
        with TemporaryDirectory() as tmpdir:
            migrations_dir = Path(tmpdir)
            
            # Create files in non-sorted order
            (migrations_dir / "002_second.sql").write_text("-- second")
            (migrations_dir / "001_first.sql").write_text("-- first")
            (migrations_dir / "003_third.sql").write_text("-- third")
            
            files = get_migration_files(migrations_dir)
            
            assert len(files) == 3
            assert files[0].name == "001_first.sql"
            assert files[1].name == "002_second.sql"
            assert files[2].name == "003_third.sql"
    
    def test_only_sql_files(self):
        """Test that only .sql files are returned."""
        with TemporaryDirectory() as tmpdir:
            migrations_dir = Path(tmpdir)
            
            (migrations_dir / "001_migration.sql").write_text("-- sql")
            (migrations_dir / "README.md").write_text("# readme")
            (migrations_dir / "script.py").write_text("# python")
            
            files = get_migration_files(migrations_dir)
            
            assert len(files) == 1
            assert files[0].name == "001_migration.sql"
    
    def test_empty_directory(self):
        """Test with empty migrations directory."""
        with TemporaryDirectory() as tmpdir:
            migrations_dir = Path(tmpdir)
            
            files = get_migration_files(migrations_dir)
            
            assert len(files) == 0
    
    def test_nonexistent_directory(self):
        """Test with non-existent migrations directory."""
        files = get_migration_files(Path("/nonexistent/path"))
        
        assert len(files) == 0


class TestComputeChecksum:
    """Tests for compute_checksum function."""
    
    def test_consistent_checksum(self):
        """Test that same content produces same checksum."""
        content = "CREATE TABLE test (id INT);"
        
        checksum1 = compute_checksum(content)
        checksum2 = compute_checksum(content)
        
        assert checksum1 == checksum2
    
    def test_different_content_different_checksum(self):
        """Test that different content produces different checksum."""
        content1 = "CREATE TABLE test1 (id INT);"
        content2 = "CREATE TABLE test2 (id INT);"
        
        checksum1 = compute_checksum(content1)
        checksum2 = compute_checksum(content2)
        
        assert checksum1 != checksum2
    
    def test_checksum_length(self):
        """Test that checksum has expected length (16 hex chars)."""
        content = "CREATE TABLE test (id INT);"
        
        checksum = compute_checksum(content)
        
        assert len(checksum) == 16


@pytest.mark.asyncio
class TestEnsureMigrationsTable:
    """Tests for ensure_migrations_table function.
    
    **Validates: Requirements 2.5, 2.6**
    """
    
    async def test_creates_table(self):
        """Test that migrations table is created.
        
        **Validates: Requirements 2.5**
        """
        mock_conn = AsyncMock()
        mock_pool = create_mock_pool(mock_conn)
        
        await ensure_migrations_table(mock_pool)
        
        # Verify CREATE TABLE was called
        assert mock_conn.execute.call_count == 2  # Table + index
        calls = [str(call) for call in mock_conn.execute.call_args_list]
        assert any("CREATE TABLE IF NOT EXISTS schema_migrations" in str(c) for c in calls)
        assert any("CREATE INDEX IF NOT EXISTS" in str(c) for c in calls)


@pytest.mark.asyncio
class TestGetAppliedMigrations:
    """Tests for get_applied_migrations function.
    
    **Validates: Requirements 2.6**
    """
    
    async def test_returns_applied_migrations(self):
        """Test that applied migrations are returned as a set.
        
        **Validates: Requirements 2.6**
        """
        mock_conn = AsyncMock()
        mock_conn.fetch.return_value = [
            {"name": "001_initial.sql"},
            {"name": "002_users.sql"},
        ]
        mock_pool = create_mock_pool(mock_conn)
        
        applied = await get_applied_migrations(mock_pool)
        
        assert applied == {"001_initial.sql", "002_users.sql"}
    
    async def test_returns_empty_set_when_no_migrations(self):
        """Test that empty set is returned when no migrations applied.
        
        **Validates: Requirements 2.6**
        """
        mock_conn = AsyncMock()
        mock_conn.fetch.return_value = []
        mock_pool = create_mock_pool(mock_conn)
        
        applied = await get_applied_migrations(mock_pool)
        
        assert applied == set()


@pytest.mark.asyncio
class TestRecordMigration:
    """Tests for record_migration function.
    
    **Validates: Requirements 2.6**
    """
    
    async def test_records_migration(self):
        """Test that migration is recorded in database.
        
        **Validates: Requirements 2.6**
        """
        mock_conn = AsyncMock()
        mock_pool = create_mock_pool(mock_conn)
        
        await record_migration(mock_pool, "001_initial.sql", "abc123")
        
        mock_conn.execute.assert_called_once()
        call_args = mock_conn.execute.call_args[0]
        assert "INSERT INTO schema_migrations" in call_args[0]
        assert call_args[1] == "001_initial.sql"
        assert call_args[3] == "abc123"
    
    async def test_uses_on_conflict_do_nothing(self):
        """Test that duplicate migrations are handled gracefully.
        
        **Validates: Requirements 2.6**
        """
        mock_conn = AsyncMock()
        mock_pool = create_mock_pool(mock_conn)
        
        await record_migration(mock_pool, "001_initial.sql")
        
        call_args = mock_conn.execute.call_args[0]
        assert "ON CONFLICT" in call_args[0]
        assert "DO NOTHING" in call_args[0]


@pytest.mark.asyncio
class TestApplyMigration:
    """Tests for apply_migration function.
    
    **Validates: Requirements 2.5, 2.6**
    """
    
    async def test_applies_migration_successfully(self):
        """Test successful migration application.
        
        **Validates: Requirements 2.5**
        """
        with TemporaryDirectory() as tmpdir:
            migration_file = Path(tmpdir) / "001_test.sql"
            migration_file.write_text("CREATE TABLE test (id INT);")
            
            mock_conn = AsyncMock()
            setup_mock_transaction(mock_conn)
            mock_pool = create_mock_pool(mock_conn)
            
            result = await apply_migration(mock_pool, migration_file)
            
            assert result.applied is True
            assert result.name == "001_test.sql"
            assert "Successfully applied" in result.message
            assert result.error is None
    
    async def test_dry_run_does_not_apply(self):
        """Test that dry run doesn't actually apply migration.
        
        **Validates: Requirements 2.5**
        """
        with TemporaryDirectory() as tmpdir:
            migration_file = Path(tmpdir) / "001_test.sql"
            migration_file.write_text("CREATE TABLE test (id INT);")
            
            mock_conn = AsyncMock()
            mock_pool = create_mock_pool(mock_conn)
            
            result = await apply_migration(mock_pool, migration_file, dry_run=True)
            
            assert result.applied is False
            assert "dry run" in result.message
            assert result.error is None
            # Connection should not have been used for execution
            mock_conn.execute.assert_not_called()
    
    async def test_handles_database_error(self):
        """Test handling of database errors during migration.
        
        **Validates: Requirements 2.5**
        """
        with TemporaryDirectory() as tmpdir:
            migration_file = Path(tmpdir) / "001_test.sql"
            migration_file.write_text("CREATE TABLE test (id INT);")
            
            mock_conn = AsyncMock()
            
            @asynccontextmanager
            async def mock_transaction_error():
                yield
            
            mock_conn.transaction = mock_transaction_error
            mock_conn.execute.side_effect = asyncpg.PostgresError("relation already exists")
            mock_pool = create_mock_pool(mock_conn)
            
            result = await apply_migration(mock_pool, migration_file)
            
            assert result.applied is False
            assert "Database error" in result.message
            assert result.error is not None
            assert "relation already exists" in result.error


@pytest.mark.asyncio
class TestRunMigrations:
    """Tests for run_migrations function.
    
    **Validates: Requirements 2.5, 2.6**
    """
    
    async def test_skips_already_applied_migrations(self):
        """Test that already-applied migrations are skipped (idempotent).
        
        **Validates: Requirements 2.6**
        """
        with TemporaryDirectory() as tmpdir:
            migrations_dir = Path(tmpdir)
            (migrations_dir / "001_first.sql").write_text("-- first")
            (migrations_dir / "002_second.sql").write_text("-- second")
            
            mock_conn = AsyncMock()
            # First call: ensure_migrations_table (2 calls)
            # Second call: get_applied_migrations
            mock_conn.fetch.return_value = [{"name": "001_first.sql"}]
            setup_mock_transaction(mock_conn)
            mock_pool = create_mock_pool(mock_conn)
            
            results = await run_migrations(mock_pool, migrations_dir)
            
            # First migration should be skipped, second should be applied
            assert len(results) == 2
            assert results[0].name == "001_first.sql"
            assert results[0].applied is False
            assert "already applied" in results[0].message
            assert results[1].name == "002_second.sql"
            assert results[1].applied is True
    
    async def test_applies_pending_migrations_in_order(self):
        """Test that pending migrations are applied in order.
        
        **Validates: Requirements 2.5**
        """
        with TemporaryDirectory() as tmpdir:
            migrations_dir = Path(tmpdir)
            (migrations_dir / "001_first.sql").write_text("-- first")
            (migrations_dir / "002_second.sql").write_text("-- second")
            (migrations_dir / "003_third.sql").write_text("-- third")
            
            mock_conn = AsyncMock()
            mock_conn.fetch.return_value = []  # No migrations applied yet
            setup_mock_transaction(mock_conn)
            mock_pool = create_mock_pool(mock_conn)
            
            results = await run_migrations(mock_pool, migrations_dir)
            
            assert len(results) == 3
            assert results[0].name == "001_first.sql"
            assert results[1].name == "002_second.sql"
            assert results[2].name == "003_third.sql"
            assert all(r.applied for r in results)
    
    async def test_stops_on_error(self):
        """Test that migration stops on first error.
        
        **Validates: Requirements 2.5**
        """
        with TemporaryDirectory() as tmpdir:
            migrations_dir = Path(tmpdir)
            (migrations_dir / "001_first.sql").write_text("-- first")
            (migrations_dir / "002_second.sql").write_text("-- second (will fail)")
            (migrations_dir / "003_third.sql").write_text("-- third")
            
            mock_conn = AsyncMock()
            mock_conn.fetch.return_value = []  # No migrations applied yet
            
            # Track execute calls to fail on second migration
            execute_call_count = [0]
            async def execute_side_effect(*args, **kwargs):
                execute_call_count[0] += 1
                # First 2 calls are for ensure_migrations_table
                # 3rd call is first migration, 4th is record_migration
                # 5th call is second migration - make it fail
                if execute_call_count[0] == 5:
                    raise asyncpg.PostgresError("syntax error")
            
            mock_conn.execute = AsyncMock(side_effect=execute_side_effect)
            
            @asynccontextmanager
            async def mock_transaction():
                yield
            
            mock_conn.transaction = mock_transaction
            mock_pool = create_mock_pool(mock_conn)
            
            results = await run_migrations(mock_pool, migrations_dir)
            
            # Should have results for first two migrations only
            # (third should not be attempted after second fails)
            assert len(results) == 2
            assert results[0].applied is True
            assert results[1].applied is False
            assert results[1].error is not None
    
    async def test_handles_empty_migrations_directory(self):
        """Test handling of empty migrations directory.
        
        **Validates: Requirements 2.5**
        """
        with TemporaryDirectory() as tmpdir:
            migrations_dir = Path(tmpdir)
            
            mock_conn = AsyncMock()
            mock_conn.fetch.return_value = []
            mock_pool = create_mock_pool(mock_conn)
            
            results = await run_migrations(mock_pool, migrations_dir)
            
            assert len(results) == 1
            assert "No migration files found" in results[0].message
    
    async def test_dry_run_mode(self):
        """Test dry run mode doesn't apply migrations.
        
        **Validates: Requirements 2.5**
        """
        with TemporaryDirectory() as tmpdir:
            migrations_dir = Path(tmpdir)
            (migrations_dir / "001_first.sql").write_text("-- first")
            
            mock_conn = AsyncMock()
            mock_conn.fetch.return_value = []  # No migrations applied yet
            mock_pool = create_mock_pool(mock_conn)
            
            results = await run_migrations(mock_pool, migrations_dir, dry_run=True)
            
            assert len(results) == 1
            assert results[0].applied is False
            assert "dry run" in results[0].message


class TestIdempotentExecution:
    """Tests for idempotent migration execution.
    
    **Validates: Requirements 2.6**
    """
    
    @pytest.mark.asyncio
    async def test_running_twice_produces_same_result(self):
        """Test that running migrations twice is safe (idempotent).
        
        **Validates: Requirements 2.6**
        """
        with TemporaryDirectory() as tmpdir:
            migrations_dir = Path(tmpdir)
            (migrations_dir / "001_first.sql").write_text("-- first")
            
            # First run: no migrations applied
            mock_conn1 = AsyncMock()
            mock_conn1.fetch.return_value = []
            setup_mock_transaction(mock_conn1)
            mock_pool1 = create_mock_pool(mock_conn1)
            
            results1 = await run_migrations(mock_pool1, migrations_dir)
            
            # Second run: migration already applied
            mock_conn2 = AsyncMock()
            mock_conn2.fetch.return_value = [{"name": "001_first.sql"}]
            mock_pool2 = create_mock_pool(mock_conn2)
            
            results2 = await run_migrations(mock_pool2, migrations_dir)
            
            # First run should apply, second should skip
            assert results1[0].applied is True
            assert results2[0].applied is False
            assert "already applied" in results2[0].message
