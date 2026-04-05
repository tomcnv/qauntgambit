#!/usr/bin/env python3
"""Database verification script for the trading bot.

This script verifies that all required database tables exist in TimescaleDB
for the backtesting and trading system.

Usage:
    python scripts/verify_db.py
"""

import argparse
import asyncio
import os
from dataclasses import dataclass
from typing import Any, Optional

import asyncpg
from pathlib import Path

from quantgambit.config.env_loading import apply_layered_env_defaults

apply_layered_env_defaults(Path(__file__).resolve().parents[1], os.getenv("ENV_FILE"), os.environ)


@dataclass
class VerificationResult:
    """Result of a verification check."""
    name: str
    passed: bool
    message: str
    details: Optional[dict[str, Any]] = None
    error: Optional[str] = None


# Required tables for the backtesting system
REQUIRED_TABLES = [
    "backtest_runs",
    "backtest_trades",
    "backtest_equity_curve",
    "backtest_metrics",
]


def build_database_url() -> str:
    """Build database URL from environment variables.
    
    Returns:
        PostgreSQL connection URL
    """
    host = os.getenv("BOT_DB_HOST", "localhost")
    port = os.getenv("BOT_DB_PORT", "5432")
    name = os.getenv("BOT_DB_NAME", "platform_db")
    user = os.getenv("BOT_DB_USER", "platform")
    password = os.getenv("BOT_DB_PASSWORD", "")
    
    if password:
        auth = f"{user}:{password}@"
    else:
        auth = f"{user}@"
    
    return f"postgresql://{auth}{host}:{port}/{name}"


async def verify_table_exists(pool: asyncpg.Pool, table_name: str) -> VerificationResult:
    """Verify a table exists in the database.
    
    Args:
        pool: Database connection pool
        table_name: Name of the table to check
        
    Returns:
        VerificationResult with status and details
    """
    name = f"Table Exists: {table_name}"
    
    try:
        async with pool.acquire() as conn:
            exists = await conn.fetchval(
                """
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_schema = 'public' 
                    AND table_name = $1
                )
                """,
                table_name
            )
            
            if exists:
                # Get row count for additional info
                row_count = await conn.fetchval(f'SELECT COUNT(*) FROM "{table_name}"')
                
                return VerificationResult(
                    name=name,
                    passed=True,
                    message=f"Table '{table_name}' exists with {row_count:,} rows",
                    details={
                        "table_name": table_name,
                        "exists": True,
                        "row_count": row_count,
                    },
                    error=None
                )
            else:
                return VerificationResult(
                    name=name,
                    passed=False,
                    message=f"Table '{table_name}' does not exist. Run migrations to create it.",
                    details={
                        "table_name": table_name,
                        "exists": False,
                    },
                    error=None
                )
                
    except asyncpg.PostgresError as e:
        return VerificationResult(
            name=name,
            passed=False,
            message=f"Database error checking table '{table_name}'",
            details={"table_name": table_name},
            error=str(e)
        )
    except Exception as e:
        return VerificationResult(
            name=name,
            passed=False,
            message=f"Unexpected error checking table '{table_name}'",
            details={"table_name": table_name},
            error=str(e)
        )


# Required columns for each table (matching actual database schema)
REQUIRED_COLUMNS = {
    "backtest_runs": ["run_id", "tenant_id", "bot_id", "status", "created_at", "config"],
    "backtest_trades": ["run_id", "symbol", "side", "entry_price", "exit_price", "ts"],
    "backtest_equity_curve": ["run_id", "ts", "equity"],
    "backtest_metrics": ["run_id", "total_trades", "realized_pnl", "total_return_pct"],
}


async def verify_table_columns(pool: asyncpg.Pool, table_name: str, required_columns: list[str]) -> VerificationResult:
    """Verify a table has all required columns.
    
    Args:
        pool: Database connection pool
        table_name: Name of the table to check
        required_columns: List of required column names
        
    Returns:
        VerificationResult with status and details
    """
    name = f"Table Columns: {table_name}"
    
    try:
        async with pool.acquire() as conn:
            # Query information_schema.columns to get actual columns
            rows = await conn.fetch(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'public'
                AND table_name = $1
                """,
                table_name
            )
            
            actual_columns = {row["column_name"] for row in rows}
            required_set = set(required_columns)
            
            # Find missing columns
            missing_columns = required_set - actual_columns
            
            if not missing_columns:
                return VerificationResult(
                    name=name,
                    passed=True,
                    message=f"Table '{table_name}' has all {len(required_columns)} required columns",
                    details={
                        "table_name": table_name,
                        "required_columns": required_columns,
                        "actual_columns": sorted(actual_columns),
                    },
                    error=None
                )
            else:
                return VerificationResult(
                    name=name,
                    passed=False,
                    message=f"Table '{table_name}' is missing {len(missing_columns)} required column(s): {sorted(missing_columns)}",
                    details={
                        "table_name": table_name,
                        "required_columns": required_columns,
                        "actual_columns": sorted(actual_columns),
                        "missing_columns": sorted(missing_columns),
                    },
                    error=None
                )
                
    except asyncpg.PostgresError as e:
        return VerificationResult(
            name=name,
            passed=False,
            message=f"Database error checking columns for table '{table_name}'",
            details={"table_name": table_name, "required_columns": required_columns},
            error=str(e)
        )
    except Exception as e:
        return VerificationResult(
            name=name,
            passed=False,
            message=f"Unexpected error checking columns for table '{table_name}'",
            details={"table_name": table_name, "required_columns": required_columns},
            error=str(e)
        )


# Expected foreign keys for each table (table_name -> list of referenced tables)
EXPECTED_FOREIGN_KEYS = {
    "backtest_trades": ["backtest_runs"],
    "backtest_equity_curve": ["backtest_runs"],
    "backtest_metrics": ["backtest_runs"],
}


async def verify_foreign_keys(pool: asyncpg.Pool, table_name: str, expected_fks: list[str]) -> VerificationResult:
    """Verify a table has correct foreign key constraints.
    
    Args:
        pool: Database connection pool
        table_name: Name of the table to check
        expected_fks: List of expected foreign key references (table names)
        
    Returns:
        VerificationResult with status and details
    """
    name = f"Foreign Keys: {table_name}"
    
    try:
        async with pool.acquire() as conn:
            # Query information_schema to get foreign key constraints
            # This joins table_constraints with constraint_column_usage to get
            # the referenced table names
            rows = await conn.fetch(
                """
                SELECT DISTINCT
                    tc.constraint_name,
                    ccu.table_name AS referenced_table
                FROM information_schema.table_constraints tc
                JOIN information_schema.constraint_column_usage ccu
                    ON tc.constraint_name = ccu.constraint_name
                    AND tc.table_schema = ccu.table_schema
                WHERE tc.table_schema = 'public'
                AND tc.table_name = $1
                AND tc.constraint_type = 'FOREIGN KEY'
                """,
                table_name
            )
            
            # Extract the referenced table names
            actual_fk_tables = {row["referenced_table"] for row in rows}
            expected_set = set(expected_fks)
            
            # Find missing foreign keys
            missing_fks = expected_set - actual_fk_tables
            
            if not missing_fks:
                return VerificationResult(
                    name=name,
                    passed=True,
                    message=f"Table '{table_name}' has all {len(expected_fks)} expected foreign key(s) to: {sorted(expected_fks)}",
                    details={
                        "table_name": table_name,
                        "expected_fks": sorted(expected_fks),
                        "actual_fks": sorted(actual_fk_tables),
                        "constraint_count": len(rows),
                    },
                    error=None
                )
            else:
                return VerificationResult(
                    name=name,
                    passed=False,
                    message=f"Table '{table_name}' is missing foreign key(s) to: {sorted(missing_fks)}",
                    details={
                        "table_name": table_name,
                        "expected_fks": sorted(expected_fks),
                        "actual_fks": sorted(actual_fk_tables),
                        "missing_fks": sorted(missing_fks),
                    },
                    error=None
                )
                
    except asyncpg.PostgresError as e:
        return VerificationResult(
            name=name,
            passed=False,
            message=f"Database error checking foreign keys for table '{table_name}'",
            details={"table_name": table_name, "expected_fks": expected_fks},
            error=str(e)
        )
    except Exception as e:
        return VerificationResult(
            name=name,
            passed=False,
            message=f"Unexpected error checking foreign keys for table '{table_name}'",
            details={"table_name": table_name, "expected_fks": expected_fks},
            error=str(e)
        )


async def verify_database_connection(db_url: str) -> tuple[Optional[asyncpg.Pool], VerificationResult]:
    """Verify database connection can be established.
    
    Args:
        db_url: Database connection URL
        
    Returns:
        Tuple of (pool or None, VerificationResult)
    """
    name = "Database Connection"
    
    # Mask password in URL for display
    display_url = db_url
    if "@" in db_url:
        parts = db_url.split("@")
        display_url = f"postgresql://***@{parts[1]}"
    
    try:
        pool = await asyncpg.create_pool(db_url, min_size=1, max_size=3)
        
        # Test the connection
        async with pool.acquire() as conn:
            version = await conn.fetchval("SELECT version()")
        
        return pool, VerificationResult(
            name=name,
            passed=True,
            message="Successfully connected to database",
            details={
                "url": display_url,
                "version": version[:50] + "..." if len(version) > 50 else version,
            },
            error=None
        )
        
    except asyncpg.InvalidCatalogNameError as e:
        return None, VerificationResult(
            name=name,
            passed=False,
            message=f"Database does not exist",
            details={"url": display_url},
            error=str(e)
        )
    except asyncpg.InvalidPasswordError as e:
        return None, VerificationResult(
            name=name,
            passed=False,
            message="Invalid database credentials",
            details={"url": display_url},
            error=str(e)
        )
    except OSError as e:
        return None, VerificationResult(
            name=name,
            passed=False,
            message="Could not connect to database server",
            details={"url": display_url},
            error=str(e)
        )
    except Exception as e:
        return None, VerificationResult(
            name=name,
            passed=False,
            message="Unexpected error connecting to database",
            details={"url": display_url},
            error=str(e)
        )


def print_result(result: VerificationResult) -> None:
    """Print a verification result in a formatted way."""
    status = "✅ PASS" if result.passed else "❌ FAIL"
    print(f"\n{status}: {result.name}")
    print(f"  Message: {result.message}")
    if result.details:
        print(f"  Details: {result.details}")
    if result.error:
        print(f"  Error: {result.error}")


async def main() -> int:
    """Run all database verification checks."""
    parser = argparse.ArgumentParser(description="Verify database schema for trading bot")
    parser.add_argument(
        "--db-url",
        default=None,
        help="Database URL (overrides environment variables)"
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
    print(f"Database Verification - {display_url}")
    print("=" * 60)
    
    results: list[VerificationResult] = []
    
    # Verify database connection
    pool, conn_result = await verify_database_connection(db_url)
    results.append(conn_result)
    print_result(conn_result)
    
    if pool is None:
        # Cannot continue without database connection
        print(f"\n{'=' * 60}")
        print("Summary: 0/1 checks passed (connection failed)")
        print("=" * 60)
        return 1
    
    try:
        # Verify each required table exists
        for table_name in REQUIRED_TABLES:
            table_result = await verify_table_exists(pool, table_name)
            results.append(table_result)
            print_result(table_result)
            
            # If table exists, verify its columns
            if table_result.passed and table_name in REQUIRED_COLUMNS:
                columns_result = await verify_table_columns(
                    pool, table_name, REQUIRED_COLUMNS[table_name]
                )
                results.append(columns_result)
                print_result(columns_result)
            
            # If table exists and should have foreign keys, verify them
            if table_result.passed and table_name in EXPECTED_FOREIGN_KEYS:
                fk_result = await verify_foreign_keys(
                    pool, table_name, EXPECTED_FOREIGN_KEYS[table_name]
                )
                results.append(fk_result)
                print_result(fk_result)
    finally:
        await pool.close()
    
    # Summary
    print(f"\n{'=' * 60}")
    passed = sum(1 for r in results if r.passed)
    total = len(results)
    print(f"Summary: {passed}/{total} checks passed")
    
    if passed < total:
        print("\nTo fix missing tables, run the database migrations:")
        print("  python scripts/run_migrations.py")
    
    print("=" * 60)
    
    return 0 if all(r.passed for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
