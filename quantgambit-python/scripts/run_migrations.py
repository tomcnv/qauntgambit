#!/usr/bin/env python3
"""Database migration runner for the trading bot.

This script applies SQL migration files to TimescaleDB in order,
tracking which migrations have been applied to support idempotent execution.

Usage:
    python scripts/run_migrations.py              # Apply all pending migrations
    python scripts/run_migrations.py --status     # Show migration status
    python scripts/run_migrations.py --dry-run    # Show what would be applied

Environment variables:
    BOT_DB_HOST     - Database host (default: localhost)
    BOT_DB_PORT     - Database port (default: 5432)
    BOT_DB_NAME     - Database name (default: quantgambit_bot)
    BOT_DB_USER     - Database user (default: quantgambit)
    BOT_DB_PASSWORD - Database password (default: empty)

Requirements: 2.5, 2.6
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import quote

import asyncpg
from quantgambit.config.env_loading import apply_layered_env_defaults

apply_layered_env_defaults(Path(__file__).resolve().parents[1], os.getenv("ENV_FILE"), os.environ)


@dataclass
class MigrationResult:
    """Result of a database migration.
    
    Attributes:
        name: Name of the migration file
        applied: Whether the migration was applied (True) or skipped (False)
        message: Human-readable status message
        error: Error message if migration failed, None otherwise
    """
    name: str
    applied: bool
    message: str
    error: Optional[str] = None


# Default migrations directory (relative to project root)
DEFAULT_MIGRATIONS_DIR = Path(__file__).parent.parent / "docs" / "sql" / "migrations"
EXTRA_SCHEMA_FILES = (
    Path(__file__).parent.parent / "docs" / "sql" / "analytics.sql",
)


def build_database_url() -> str:
    """Build database URL from environment variables.
    
    Returns:
        PostgreSQL connection URL
    """
    host = os.getenv("BOT_DB_HOST", "localhost")
    port = os.getenv("BOT_DB_PORT", "5432")
    name = os.getenv("BOT_DB_NAME", "quantgambit_bot")
    user = os.getenv("BOT_DB_USER", "quantgambit")
    password = os.getenv("BOT_DB_PASSWORD", "")
    
    encoded_user = quote(user, safe="")
    if password:
        encoded_password = quote(password, safe="")
        auth = f"{encoded_user}:{encoded_password}@"
    else:
        auth = f"{encoded_user}@"
    
    return f"postgresql://{auth}{host}:{port}/{name}"


async def ensure_migrations_table(pool: asyncpg.Pool) -> None:
    """Create the migrations tracking table if it doesn't exist.
    
    This table tracks which migrations have been applied to support
    idempotent execution (safe to run multiple times).
    
    Args:
        pool: Database connection pool
    """
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                checksum TEXT
            )
        """)
        # Create index for faster lookups
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS schema_migrations_name_idx 
            ON schema_migrations (name)
        """)


async def get_applied_migrations(pool: asyncpg.Pool) -> set[str]:
    """Get the set of migration names that have already been applied.
    
    Args:
        pool: Database connection pool
        
    Returns:
        Set of migration names that have been applied
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT name FROM schema_migrations")
        return {row["name"] for row in rows}


async def reconcile_bootstrap_baseline(pool: asyncpg.Pool, migrations_dir: Path) -> None:
    """Record a golden bootstrap baseline into schema_migrations when present.

    This bridges conservative schema bootstrap via schema_baseline_state with the
    authoritative migration ledger used by the runner.
    """
    migration_files = get_migration_files(migrations_dir)

    async with pool.acquire() as conn:
        async def _record(name: str, checksum: str) -> None:
            await conn.execute(
                """
                INSERT INTO schema_migrations (name, applied_at, checksum)
                VALUES ($1, $2, $3)
                ON CONFLICT (name) DO NOTHING
                """,
                name,
                datetime.now(timezone.utc),
                checksum,
            )

        baseline_exists = await conn.fetchval(
            """
            SELECT EXISTS (
                SELECT 1
                FROM information_schema.tables
                WHERE table_schema = 'public'
                  AND table_name = 'schema_baseline_state'
            )
            """
        )
        if baseline_exists:
            row = await conn.fetchrow(
                """
                SELECT schema_checksum
                FROM schema_baseline_state
                WHERE schema_name = 'quant'
                LIMIT 1
                """
            )
            if row:
                baseline_checksum = row["schema_checksum"]
                for migration_file in migration_files:
                    checksum = compute_checksum(migration_file.read_text())
                    if checksum != baseline_checksum:
                        continue
                    await _record(migration_file.name, checksum)
                    break

        orderbook_exists = await conn.fetchval(
            """
            SELECT EXISTS (
                SELECT 1
                FROM information_schema.tables
                WHERE table_schema = 'public'
                  AND table_name = 'orderbook_snapshots'
            )
            """
        )
        if not orderbook_exists:
            return
        for migration_file in migration_files:
            if migration_file.name != "000_golden_quant_schema.sql":
                continue
            checksum = compute_checksum(migration_file.read_text())
            await _record(migration_file.name, checksum)
            break


async def record_migration(
    pool: asyncpg.Pool, 
    name: str, 
    checksum: Optional[str] = None
) -> None:
    """Record that a migration has been applied.
    
    Args:
        pool: Database connection pool
        name: Name of the migration
        checksum: Optional checksum of the migration file
    """
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO schema_migrations (name, applied_at, checksum)
            VALUES ($1, $2, $3)
            ON CONFLICT (name) DO NOTHING
            """,
            name,
            datetime.now(timezone.utc),
            checksum
        )


def get_migration_files(migrations_dir: Path) -> list[Path]:
    """Get all SQL migration files sorted by name.
    
    Migration files should be named with a numeric prefix for ordering,
    e.g., 000_initial.sql, 001_add_users.sql, etc.
    
    Args:
        migrations_dir: Directory containing migration files
        
    Returns:
        List of migration file paths sorted by name
    """
    if not migrations_dir.exists():
        return []
    
    # Get all .sql files
    sql_files = list(migrations_dir.glob("*.sql"))
    
    # Sort by filename (numeric prefix ensures correct order)
    sql_files.sort(key=lambda p: p.name)
    
    return sql_files


def compute_checksum(content: str) -> str:
    """Compute a simple checksum for migration content.
    
    Args:
        content: Migration file content
        
    Returns:
        Hex digest of the content
    """
    import hashlib
    return hashlib.sha256(content.encode()).hexdigest()[:16]


async def apply_migration(
    pool: asyncpg.Pool,
    migration_file: Path,
    dry_run: bool = False
) -> MigrationResult:
    """Apply a single migration file.
    
    Args:
        pool: Database connection pool
        migration_file: Path to the SQL migration file
        dry_run: If True, don't actually apply the migration
        
    Returns:
        MigrationResult with status and details
    """
    name = migration_file.name
    
    try:
        # Read migration content
        content = migration_file.read_text()
        checksum = compute_checksum(content)
        
        if dry_run:
            return MigrationResult(
                name=name,
                applied=False,
                message=f"Would apply migration '{name}' (dry run)",
                error=None
            )
        
        # Apply the migration in a transaction
        async with pool.acquire() as conn:
            async with conn.transaction():
                # Execute the SQL
                await conn.execute(content)
        
        # Record the migration as applied
        await record_migration(pool, name, checksum)
        
        return MigrationResult(
            name=name,
            applied=True,
            message=f"Successfully applied migration '{name}'",
            error=None
        )
        
    except asyncpg.PostgresError as e:
        return MigrationResult(
            name=name,
            applied=False,
            message=f"Database error applying migration '{name}'",
            error=str(e)
        )
    except Exception as e:
        return MigrationResult(
            name=name,
            applied=False,
            message=f"Error applying migration '{name}'",
            error=str(e)
        )


def get_all_migration_files(migrations_dir: Path) -> list[Path]:
    migration_files = get_migration_files(migrations_dir)
    for extra_file in EXTRA_SCHEMA_FILES:
        if extra_file.exists():
            migration_files.append(extra_file)
    return migration_files


async def run_migrations(
    pool: asyncpg.Pool,
    migrations_dir: Optional[Path] = None,
    dry_run: bool = False
) -> list[MigrationResult]:
    """Run all pending database migrations.
    
    This function:
    1. Ensures the migrations tracking table exists
    2. Gets the list of already-applied migrations
    3. Applies any pending migrations in order
    4. Records each applied migration
    
    The function is idempotent - safe to run multiple times.
    Already-applied migrations are skipped.
    
    Args:
        pool: Database connection pool
        migrations_dir: Directory containing SQL migration files
                       (defaults to docs/sql/migrations)
        dry_run: If True, don't actually apply migrations
        
    Returns:
        List of MigrationResult objects for each migration processed
    """
    if migrations_dir is None:
        migrations_dir = DEFAULT_MIGRATIONS_DIR
    
    results: list[MigrationResult] = []
    
    # Ensure migrations table exists
    await ensure_migrations_table(pool)
    await reconcile_bootstrap_baseline(pool, migrations_dir)
    
    # Get already-applied migrations
    applied = await get_applied_migrations(pool)
    
    # Get all migration files
    migration_files = get_all_migration_files(migrations_dir)
    
    if not migration_files:
        return [MigrationResult(
            name="(none)",
            applied=False,
            message=f"No migration files found in {migrations_dir}",
            error=None
        )]
    
    # Process each migration
    for migration_file in migration_files:
        name = migration_file.name
        
        if name in applied:
            # Already applied - skip
            results.append(MigrationResult(
                name=name,
                applied=False,
                message=f"Migration '{name}' already applied (skipped)",
                error=None
            ))
        else:
            # Apply the migration
            result = await apply_migration(pool, migration_file, dry_run)
            results.append(result)
            
            # Stop on error
            if result.error:
                break
    
    return results


async def show_status(pool: asyncpg.Pool, migrations_dir: Path) -> None:
    """Show the status of all migrations.
    
    Args:
        pool: Database connection pool
        migrations_dir: Directory containing migration files
    """
    await ensure_migrations_table(pool)
    await reconcile_bootstrap_baseline(pool, migrations_dir)
    applied = await get_applied_migrations(pool)
    migration_files = get_all_migration_files(migrations_dir)
    
    print("\nMigration Status:")
    print("-" * 60)
    
    if not migration_files:
        print(f"No migration files found in {migrations_dir}")
        return
    
    pending_count = 0
    for migration_file in migration_files:
        name = migration_file.name
        if name in applied:
            status = "✅ Applied"
        else:
            status = "⏳ Pending"
            pending_count += 1
        print(f"  {status}: {name}")
    
    print("-" * 60)
    print(f"Total: {len(migration_files)} migrations, {pending_count} pending")


def print_result(result: MigrationResult) -> None:
    """Print a migration result in a formatted way."""
    if result.error:
        status = "❌ ERROR"
    elif result.applied:
        status = "✅ APPLIED"
    else:
        status = "⏭️  SKIPPED"
    
    print(f"  {status}: {result.name}")
    if result.error:
        print(f"    Error: {result.error}")


async def main() -> int:
    """Run migrations from command line.
    
    Returns:
        Exit code (0 for success, 1 for failure)
    """
    parser = argparse.ArgumentParser(
        description="Run database migrations for trading bot"
    )
    parser.add_argument(
        "--db-url",
        default=None,
        help="Database URL (overrides environment variables)"
    )
    parser.add_argument(
        "--migrations-dir",
        type=Path,
        default=DEFAULT_MIGRATIONS_DIR,
        help=f"Directory containing SQL migration files (default: {DEFAULT_MIGRATIONS_DIR})"
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Show migration status without applying"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be applied without actually applying"
    )
    args = parser.parse_args()
    
    # Build database URL
    if args.db_url:
        db_url = args.db_url
    else:
        db_url = build_database_url()
    
    # Mask password for display
    display_url = db_url
    if "@" in db_url:
        parts = db_url.split("@")
        display_url = f"postgresql://***@{parts[1]}"
    
    print("=" * 60)
    print(f"Database Migrations - {display_url}")
    print("=" * 60)
    
    try:
        pool = await asyncpg.create_pool(db_url, min_size=1, max_size=3)
    except asyncpg.InvalidCatalogNameError as e:
        print(f"\n❌ Database does not exist: {e}")
        return 1
    except asyncpg.InvalidPasswordError as e:
        print(f"\n❌ Invalid database credentials: {e}")
        return 1
    except OSError as e:
        print(f"\n❌ Could not connect to database server: {e}")
        return 1
    except Exception as e:
        print(f"\n❌ Unexpected error connecting to database: {e}")
        return 1
    
    try:
        if args.status:
            await show_status(pool, args.migrations_dir)
            return 0
        
        # Run migrations
        mode = "(dry run)" if args.dry_run else ""
        print(f"\nRunning migrations {mode}...")
        print(f"Migrations directory: {args.migrations_dir}")
        print()
        
        results = await run_migrations(
            pool,
            migrations_dir=args.migrations_dir,
            dry_run=args.dry_run
        )
        
        # Print results
        for result in results:
            print_result(result)
        
        # Summary
        print()
        print("-" * 60)
        applied_count = sum(1 for r in results if r.applied)
        skipped_count = sum(1 for r in results if not r.applied and not r.error)
        error_count = sum(1 for r in results if r.error)
        
        print(f"Summary: {applied_count} applied, {skipped_count} skipped, {error_count} errors")
        
        if error_count > 0:
            print("\n⚠️  Some migrations failed. Please fix the errors and try again.")
            return 1
        
        if applied_count > 0:
            print("\n✅ All migrations applied successfully!")
        else:
            print("\n✅ Database is up to date (no pending migrations)")
        
        return 0
        
    finally:
        await pool.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
