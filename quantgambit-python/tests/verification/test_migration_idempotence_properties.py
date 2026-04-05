"""
Property-based tests for migration idempotence.

Feature: end-to-end-integration-verification
Tests correctness properties for:
- Property 1: Migration Idempotence

**Validates: Requirements 2.6**

For any database migration script, running it twice in succession SHALL produce
the same database state as running it once. The second run SHALL not fail and
SHALL not create duplicate objects.
"""

from __future__ import annotations

import os
import sys
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Dict, List, Optional, Set
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hypothesis import given, strategies as st, settings, assume

# Add scripts directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'scripts'))

from run_migrations import (
    MigrationResult,
    get_migration_files,
    compute_checksum,
    ensure_migrations_table,
    get_applied_migrations,
    record_migration,
    apply_migration,
    run_migrations,
)


# =============================================================================
# Mock Database State
# =============================================================================

@dataclass
class MockDatabaseState:
    """Simulates database state for testing migration idempotence.
    
    This class tracks:
    - Which migrations have been applied
    - What tables/objects exist in the database
    - Any errors that should be raised
    """
    applied_migrations: Set[str] = field(default_factory=set)
    created_objects: Set[str] = field(default_factory=set)
    execute_count: int = 0
    
    def reset(self):
        """Reset the database state."""
        self.applied_migrations = set()
        self.created_objects = set()
        self.execute_count = 0
    
    def copy(self) -> "MockDatabaseState":
        """Create a copy of the current state."""
        return MockDatabaseState(
            applied_migrations=self.applied_migrations.copy(),
            created_objects=self.created_objects.copy(),
            execute_count=self.execute_count,
        )


def create_mock_pool_with_state(db_state: MockDatabaseState):
    """Create a mock pool that tracks database state.
    
    Args:
        db_state: The MockDatabaseState to track changes
        
    Returns:
        A mock pool with proper async context manager support
    """
    mock_conn = AsyncMock()
    
    async def mock_execute(sql, *args, **kwargs):
        """Mock execute that tracks state changes."""
        db_state.execute_count += 1
        
        # Track CREATE TABLE statements
        sql_upper = sql.upper()
        if "CREATE TABLE" in sql_upper:
            # Extract table name (simplified parsing)
            if "IF NOT EXISTS" in sql_upper:
                # Idempotent - don't fail if exists
                pass
            else:
                # Non-idempotent - would fail if exists
                # For testing, we track but don't fail
                pass
        
        # Track INSERT statements for migration recording
        if "INSERT INTO SCHEMA_MIGRATIONS" in sql_upper:
            if len(args) > 0:
                migration_name = args[0]
                db_state.applied_migrations.add(migration_name)
    
    async def mock_fetch(sql, *args, **kwargs):
        """Mock fetch that returns applied migrations."""
        if "SELECT" in sql.upper() and "SCHEMA_MIGRATIONS" in sql.upper():
            return [{"name": name} for name in db_state.applied_migrations]
        return []
    
    mock_conn.execute = AsyncMock(side_effect=mock_execute)
    mock_conn.fetch = AsyncMock(side_effect=mock_fetch)
    
    @asynccontextmanager
    async def mock_transaction():
        yield
    
    mock_conn.transaction = mock_transaction
    
    mock_pool = MagicMock()
    
    @asynccontextmanager
    async def mock_acquire():
        yield mock_conn
    
    mock_pool.acquire = mock_acquire
    return mock_pool


# =============================================================================
# Test Strategies (Generators)
# =============================================================================

# Strategy for generating valid migration file names
migration_name_strategy = st.from_regex(
    r"[0-9]{3}_[a-z_]+\.sql",
    fullmatch=True
).filter(lambda x: len(x) <= 50)

# Strategy for generating valid SQL content (simplified)
sql_content_strategy = st.sampled_from([
    "CREATE TABLE IF NOT EXISTS test_table (id SERIAL PRIMARY KEY);",
    "CREATE INDEX IF NOT EXISTS test_idx ON test_table (id);",
    "ALTER TABLE test_table ADD COLUMN IF NOT EXISTS name TEXT;",
    "INSERT INTO test_table (id) VALUES (1) ON CONFLICT DO NOTHING;",
    "-- Comment only migration",
    "CREATE TABLE IF NOT EXISTS users (id SERIAL PRIMARY KEY, name TEXT);",
    "CREATE TABLE IF NOT EXISTS orders (id SERIAL PRIMARY KEY, user_id INT);",
])

# Strategy for generating a list of migration files
@st.composite
def migration_files_strategy(draw):
    """Generate a list of migration files with unique names."""
    num_migrations = draw(st.integers(min_value=1, max_value=5))
    
    migrations = []
    for i in range(num_migrations):
        # Generate unique prefix
        prefix = f"{i:03d}"
        suffix = draw(st.sampled_from([
            "initial", "add_users", "add_orders", "add_index", "update_schema"
        ]))
        name = f"{prefix}_{suffix}.sql"
        content = draw(sql_content_strategy)
        migrations.append((name, content))
    
    return migrations


# Strategy for generating a subset of migrations to pre-apply
@st.composite
def pre_applied_migrations_strategy(draw, migrations: List[tuple]):
    """Generate a subset of migrations that are already applied."""
    if not migrations:
        return set()
    
    # Randomly select which migrations are already applied
    num_to_apply = draw(st.integers(min_value=0, max_value=len(migrations)))
    indices = draw(st.lists(
        st.integers(min_value=0, max_value=len(migrations) - 1),
        min_size=num_to_apply,
        max_size=num_to_apply,
        unique=True
    ))
    
    return {migrations[i][0] for i in indices}


# =============================================================================
# Property 1: Migration Idempotence
# Feature: end-to-end-integration-verification, Property 1: Migration Idempotence
# Validates: Requirements 2.6
# =============================================================================

class TestMigrationIdempotence:
    """
    Feature: end-to-end-integration-verification, Property 1: Migration Idempotence
    
    For any database migration script, running it twice in succession SHALL produce
    the same database state as running it once. The second run SHALL not fail and
    SHALL not create duplicate objects.
    
    **Validates: Requirements 2.6**
    """
    
    @settings(max_examples=50)
    @given(migrations=migration_files_strategy())
    @pytest.mark.asyncio
    async def test_running_migrations_twice_produces_same_state(
        self,
        migrations: List[tuple],
    ):
        """
        Property 1: Running migrations twice produces the same database state
        
        *For any* set of migration scripts, running them twice in succession SHALL
        produce the same database state as running them once.
        
        **Validates: Requirements 2.6**
        """
        with TemporaryDirectory() as tmpdir:
            migrations_dir = Path(tmpdir)
            
            # Create migration files
            for name, content in migrations:
                (migrations_dir / name).write_text(content)
            
            # Create database state tracker
            db_state = MockDatabaseState()
            
            # First run
            mock_pool1 = create_mock_pool_with_state(db_state)
            results1 = await run_migrations(mock_pool1, migrations_dir)
            
            # Capture state after first run
            state_after_first_run = db_state.copy()
            applied_after_first = state_after_first_run.applied_migrations.copy()
            
            # Second run (same state, migrations already recorded)
            mock_pool2 = create_mock_pool_with_state(db_state)
            results2 = await run_migrations(mock_pool2, migrations_dir)
            
            # Capture state after second run
            state_after_second_run = db_state.copy()
            applied_after_second = state_after_second_run.applied_migrations.copy()
            
            # Property: Applied migrations should be the same after both runs
            assert applied_after_first == applied_after_second, \
                f"Applied migrations should be identical after first and second run. " \
                f"First: {applied_after_first}, Second: {applied_after_second}"
    
    @settings(max_examples=50)
    @given(migrations=migration_files_strategy())
    @pytest.mark.asyncio
    async def test_second_run_skips_already_applied_migrations(
        self,
        migrations: List[tuple],
    ):
        """
        Property 1: Second run skips already-applied migrations
        
        *For any* set of migration scripts, the second run SHALL skip all
        migrations that were applied in the first run.
        
        **Validates: Requirements 2.6**
        """
        with TemporaryDirectory() as tmpdir:
            migrations_dir = Path(tmpdir)
            
            # Create migration files
            for name, content in migrations:
                (migrations_dir / name).write_text(content)
            
            # Create database state tracker
            db_state = MockDatabaseState()
            
            # First run - all migrations should be applied
            mock_pool1 = create_mock_pool_with_state(db_state)
            results1 = await run_migrations(mock_pool1, migrations_dir)
            
            # Count applied migrations in first run
            applied_count_first = sum(1 for r in results1 if r.applied)
            
            # Second run - all migrations should be skipped
            mock_pool2 = create_mock_pool_with_state(db_state)
            results2 = await run_migrations(mock_pool2, migrations_dir)
            
            # Count applied and skipped in second run
            applied_count_second = sum(1 for r in results2 if r.applied)
            skipped_count_second = sum(
                1 for r in results2 
                if not r.applied and "already applied" in r.message
            )
            
            # Property: No migrations should be applied in second run
            assert applied_count_second == 0, \
                f"No migrations should be applied in second run, but {applied_count_second} were applied"
            
            # Property: All migrations should be skipped in second run
            assert skipped_count_second == len(migrations), \
                f"All {len(migrations)} migrations should be skipped in second run, " \
                f"but only {skipped_count_second} were skipped"
    
    @settings(max_examples=50)
    @given(migrations=migration_files_strategy())
    @pytest.mark.asyncio
    async def test_second_run_does_not_fail(
        self,
        migrations: List[tuple],
    ):
        """
        Property 1: Second run does not fail
        
        *For any* set of migration scripts, the second run SHALL not produce
        any errors.
        
        **Validates: Requirements 2.6**
        """
        with TemporaryDirectory() as tmpdir:
            migrations_dir = Path(tmpdir)
            
            # Create migration files
            for name, content in migrations:
                (migrations_dir / name).write_text(content)
            
            # Create database state tracker
            db_state = MockDatabaseState()
            
            # First run
            mock_pool1 = create_mock_pool_with_state(db_state)
            results1 = await run_migrations(mock_pool1, migrations_dir)
            
            # Second run
            mock_pool2 = create_mock_pool_with_state(db_state)
            results2 = await run_migrations(mock_pool2, migrations_dir)
            
            # Property: No errors in second run
            errors_in_second_run = [r for r in results2 if r.error is not None]
            assert len(errors_in_second_run) == 0, \
                f"Second run should not have any errors, but found: " \
                f"{[r.error for r in errors_in_second_run]}"
    
    @settings(max_examples=50)
    @given(migrations=migration_files_strategy())
    @pytest.mark.asyncio
    async def test_no_duplicate_migration_records(
        self,
        migrations: List[tuple],
    ):
        """
        Property 1: No duplicate migration records are created
        
        *For any* set of migration scripts, running them multiple times SHALL
        not create duplicate entries in the schema_migrations table.
        
        **Validates: Requirements 2.6**
        """
        with TemporaryDirectory() as tmpdir:
            migrations_dir = Path(tmpdir)
            
            # Create migration files
            for name, content in migrations:
                (migrations_dir / name).write_text(content)
            
            # Create database state tracker
            db_state = MockDatabaseState()
            
            # Run migrations three times
            for run_num in range(3):
                mock_pool = create_mock_pool_with_state(db_state)
                await run_migrations(mock_pool, migrations_dir)
            
            # Property: Number of recorded migrations should equal number of migration files
            expected_count = len(migrations)
            actual_count = len(db_state.applied_migrations)
            
            assert actual_count == expected_count, \
                f"Should have exactly {expected_count} migration records, " \
                f"but found {actual_count}. Records: {db_state.applied_migrations}"
    
    @settings(max_examples=30)
    @given(
        migrations=migration_files_strategy(),
        num_runs=st.integers(min_value=2, max_value=5)
    )
    @pytest.mark.asyncio
    async def test_multiple_runs_are_idempotent(
        self,
        migrations: List[tuple],
        num_runs: int,
    ):
        """
        Property 1: Multiple runs are idempotent
        
        *For any* set of migration scripts and *for any* number of runs N >= 2,
        running migrations N times SHALL produce the same state as running once.
        
        **Validates: Requirements 2.6**
        """
        with TemporaryDirectory() as tmpdir:
            migrations_dir = Path(tmpdir)
            
            # Create migration files
            for name, content in migrations:
                (migrations_dir / name).write_text(content)
            
            # Create database state tracker
            db_state = MockDatabaseState()
            
            # First run - capture baseline state
            mock_pool1 = create_mock_pool_with_state(db_state)
            await run_migrations(mock_pool1, migrations_dir)
            baseline_state = db_state.applied_migrations.copy()
            
            # Run N-1 more times
            for run_num in range(num_runs - 1):
                mock_pool = create_mock_pool_with_state(db_state)
                results = await run_migrations(mock_pool, migrations_dir)
                
                # Property: State should remain unchanged
                current_state = db_state.applied_migrations.copy()
                assert current_state == baseline_state, \
                    f"State after run {run_num + 2} should match baseline. " \
                    f"Baseline: {baseline_state}, Current: {current_state}"
                
                # Property: No errors in any run
                errors = [r for r in results if r.error is not None]
                assert len(errors) == 0, \
                    f"Run {run_num + 2} should not have errors: {errors}"
    
    @settings(max_examples=30)
    @given(migrations=migration_files_strategy())
    @pytest.mark.asyncio
    async def test_partial_application_then_full_run_is_idempotent(
        self,
        migrations: List[tuple],
    ):
        """
        Property 1: Partial application followed by full run is idempotent
        
        *For any* set of migration scripts, if some migrations are already applied,
        running all migrations SHALL only apply the pending ones and not fail.
        
        **Validates: Requirements 2.6**
        """
        assume(len(migrations) >= 2)  # Need at least 2 migrations for this test
        
        with TemporaryDirectory() as tmpdir:
            migrations_dir = Path(tmpdir)
            
            # Create migration files
            for name, content in migrations:
                (migrations_dir / name).write_text(content)
            
            # Create database state with some migrations pre-applied
            db_state = MockDatabaseState()
            
            # Pre-apply first half of migrations
            half = len(migrations) // 2
            for name, _ in migrations[:half]:
                db_state.applied_migrations.add(name)
            
            pre_applied_count = len(db_state.applied_migrations)
            
            # Run all migrations
            mock_pool = create_mock_pool_with_state(db_state)
            results = await run_migrations(mock_pool, migrations_dir)
            
            # Count results
            skipped = sum(1 for r in results if "already applied" in r.message)
            applied = sum(1 for r in results if r.applied)
            errors = sum(1 for r in results if r.error is not None)
            
            # Property: Pre-applied migrations should be skipped
            assert skipped == pre_applied_count, \
                f"Expected {pre_applied_count} skipped, got {skipped}"
            
            # Property: Remaining migrations should be applied
            expected_applied = len(migrations) - pre_applied_count
            assert applied == expected_applied, \
                f"Expected {expected_applied} applied, got {applied}"
            
            # Property: No errors
            assert errors == 0, \
                f"Expected no errors, got {errors}"
            
            # Run again - all should be skipped now
            mock_pool2 = create_mock_pool_with_state(db_state)
            results2 = await run_migrations(mock_pool2, migrations_dir)
            
            skipped2 = sum(1 for r in results2 if "already applied" in r.message)
            applied2 = sum(1 for r in results2 if r.applied)
            
            # Property: All migrations should be skipped on second run
            assert skipped2 == len(migrations), \
                f"All {len(migrations)} should be skipped, got {skipped2}"
            assert applied2 == 0, \
                f"None should be applied, got {applied2}"


class TestMigrationIdempotenceEdgeCases:
    """
    Edge case tests for migration idempotence.
    
    **Validates: Requirements 2.6**
    """
    
    @pytest.mark.asyncio
    async def test_empty_migrations_directory_is_idempotent(self):
        """
        Edge case: Empty migrations directory is idempotent
        
        Running migrations on an empty directory multiple times should not fail.
        
        **Validates: Requirements 2.6**
        """
        with TemporaryDirectory() as tmpdir:
            migrations_dir = Path(tmpdir)
            
            db_state = MockDatabaseState()
            
            # Run twice on empty directory
            for _ in range(2):
                mock_pool = create_mock_pool_with_state(db_state)
                results = await run_migrations(mock_pool, migrations_dir)
                
                # Should return a single result indicating no migrations found
                assert len(results) == 1
                assert "No migration files found" in results[0].message
                assert results[0].error is None
    
    @pytest.mark.asyncio
    async def test_single_migration_is_idempotent(self):
        """
        Edge case: Single migration is idempotent
        
        Running a single migration multiple times should apply it once and skip thereafter.
        
        **Validates: Requirements 2.6**
        """
        with TemporaryDirectory() as tmpdir:
            migrations_dir = Path(tmpdir)
            (migrations_dir / "001_initial.sql").write_text(
                "CREATE TABLE IF NOT EXISTS test (id INT);"
            )
            
            db_state = MockDatabaseState()
            
            # First run
            mock_pool1 = create_mock_pool_with_state(db_state)
            results1 = await run_migrations(mock_pool1, migrations_dir)
            
            assert len(results1) == 1
            assert results1[0].applied is True
            assert results1[0].error is None
            
            # Second run
            mock_pool2 = create_mock_pool_with_state(db_state)
            results2 = await run_migrations(mock_pool2, migrations_dir)
            
            assert len(results2) == 1
            assert results2[0].applied is False
            assert "already applied" in results2[0].message
            assert results2[0].error is None
    
    @pytest.mark.asyncio
    async def test_dry_run_does_not_affect_idempotence(self):
        """
        Edge case: Dry run does not affect idempotence
        
        Running in dry-run mode should not record migrations, so subsequent
        real runs should still apply them.
        
        **Validates: Requirements 2.6**
        """
        with TemporaryDirectory() as tmpdir:
            migrations_dir = Path(tmpdir)
            (migrations_dir / "001_initial.sql").write_text(
                "CREATE TABLE IF NOT EXISTS test (id INT);"
            )
            
            db_state = MockDatabaseState()
            
            # Dry run - should not record
            mock_pool1 = create_mock_pool_with_state(db_state)
            results1 = await run_migrations(mock_pool1, migrations_dir, dry_run=True)
            
            assert len(results1) == 1
            assert results1[0].applied is False
            assert "dry run" in results1[0].message
            
            # Real run - should apply
            mock_pool2 = create_mock_pool_with_state(db_state)
            results2 = await run_migrations(mock_pool2, migrations_dir, dry_run=False)
            
            assert len(results2) == 1
            assert results2[0].applied is True
            
            # Second real run - should skip
            mock_pool3 = create_mock_pool_with_state(db_state)
            results3 = await run_migrations(mock_pool3, migrations_dir, dry_run=False)
            
            assert len(results3) == 1
            assert results3[0].applied is False
            assert "already applied" in results3[0].message
