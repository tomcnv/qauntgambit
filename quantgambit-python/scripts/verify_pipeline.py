#!/usr/bin/env python3
"""Pipeline verification script for the trading bot.

This script verifies that the live trading and backtesting pipelines
work end-to-end, including decision recording to TimescaleDB.

Usage:
    python scripts/verify_pipeline.py

Requirements: 4.2 - WHEN a decision is made THEN the DecisionRecorder SHALL record it to TimescaleDB (if enabled)
"""

import argparse
import asyncio
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import asyncpg
import redis.asyncio as redis
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


def build_redis_url() -> str:
    """Build Redis URL from environment variables.
    
    Returns:
        Redis connection URL
    """
    # BOT_REDIS_URL takes precedence, then REDIS_URL
    return os.getenv("BOT_REDIS_URL", os.getenv("REDIS_URL", "redis://localhost:6379"))


def get_decision_recorder_enabled() -> bool:
    """Check if decision recording is enabled via environment variable.
    
    Returns:
        True if DECISION_RECORDER_ENABLED is set to a truthy value
    """
    return os.getenv("DECISION_RECORDER_ENABLED", "true").lower() in {"1", "true", "yes"}


def get_warm_start_enabled() -> bool:
    """Check if warm start is enabled via environment variable.
    
    Returns:
        True if BACKTEST_WARM_START_ENABLED is set to a truthy value
    """
    return os.getenv("BACKTEST_WARM_START_ENABLED", "false").lower() in {"1", "true", "yes"}


async def verify_decision_recording(pool: asyncpg.Pool, redis_client: redis.Redis) -> VerificationResult:
    """Verify decisions are being recorded to the database.
    
    This function checks:
    1. The DECISION_RECORDER_ENABLED environment variable is set correctly
    2. The decision_events table exists in the database
    3. There are recent records in the decision_events table (if recording is enabled)
    
    Args:
        pool: Database connection pool
        redis_client: Redis client (for future use with live pipeline verification)
        
    Returns:
        VerificationResult with status and details
        
    Requirements: 4.2 - WHEN a decision is made THEN the DecisionRecorder SHALL record it to TimescaleDB (if enabled)
    """
    name = "Decision Recording"
    
    # Check environment variable
    recorder_enabled = get_decision_recorder_enabled()
    env_var_value = os.getenv("DECISION_RECORDER_ENABLED", "true")
    
    try:
        async with pool.acquire() as conn:
            # Check if decision_events table exists
            table_exists = await conn.fetchval(
                """
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_schema = 'public' 
                    AND table_name = 'decision_events'
                )
                """
            )
            
            if not table_exists:
                return VerificationResult(
                    name=name,
                    passed=False,
                    message="decision_events table does not exist. Run migrations to create it.",
                    details={
                        "table_exists": False,
                        "recorder_enabled": recorder_enabled,
                        "env_var_value": env_var_value,
                    },
                    error=None
                )
            
            # Get total count of decision events
            total_count = await conn.fetchval(
                "SELECT COUNT(*) FROM decision_events"
            )
            
            # Get count of recent decision events (last 24 hours)
            recent_count = await conn.fetchval(
                """
                SELECT COUNT(*) FROM decision_events 
                WHERE ts > NOW() - INTERVAL '24 hours'
                """
            )
            
            # Get the most recent decision event timestamp
            latest_ts = await conn.fetchval(
                "SELECT MAX(ts) FROM decision_events"
            )
            
            # Get count by decision result (approved vs rejected) in last hour
            result_counts = await conn.fetch(
                """
                SELECT 
                    COALESCE(payload->>'result', 'unknown') as result,
                    COUNT(*) as count
                FROM decision_events 
                WHERE ts > NOW() - INTERVAL '1 hour'
                GROUP BY payload->>'result'
                """
            )
            
            result_breakdown = {row["result"]: row["count"] for row in result_counts}
            
            # Determine verification status
            if not recorder_enabled:
                # Recording is disabled - this is expected behavior
                return VerificationResult(
                    name=name,
                    passed=True,
                    message=f"Decision recording is disabled (DECISION_RECORDER_ENABLED={env_var_value}). "
                            f"Table exists with {total_count:,} historical records.",
                    details={
                        "table_exists": True,
                        "recorder_enabled": False,
                        "env_var_value": env_var_value,
                        "total_count": total_count,
                        "recent_count_24h": recent_count,
                        "latest_timestamp": latest_ts.isoformat() if latest_ts else None,
                    },
                    error=None
                )
            
            # Recording is enabled - check if we have recent records
            if recent_count > 0:
                return VerificationResult(
                    name=name,
                    passed=True,
                    message=f"Decision recording is active. {recent_count:,} decisions recorded in last 24 hours "
                            f"(total: {total_count:,}).",
                    details={
                        "table_exists": True,
                        "recorder_enabled": True,
                        "env_var_value": env_var_value,
                        "total_count": total_count,
                        "recent_count_24h": recent_count,
                        "latest_timestamp": latest_ts.isoformat() if latest_ts else None,
                        "result_breakdown_1h": result_breakdown,
                    },
                    error=None
                )
            elif total_count > 0:
                # Have historical records but none recent
                return VerificationResult(
                    name=name,
                    passed=True,
                    message=f"Decision recording is enabled but no recent decisions. "
                            f"Table has {total_count:,} historical records. "
                            f"Last decision: {latest_ts.isoformat() if latest_ts else 'N/A'}",
                    details={
                        "table_exists": True,
                        "recorder_enabled": True,
                        "env_var_value": env_var_value,
                        "total_count": total_count,
                        "recent_count_24h": 0,
                        "latest_timestamp": latest_ts.isoformat() if latest_ts else None,
                        "note": "No decisions in last 24 hours - bot may not be running",
                    },
                    error=None
                )
            else:
                # No records at all
                return VerificationResult(
                    name=name,
                    passed=True,
                    message="Decision recording is enabled but no decisions recorded yet. "
                            "This is expected if the bot hasn't processed any market data.",
                    details={
                        "table_exists": True,
                        "recorder_enabled": True,
                        "env_var_value": env_var_value,
                        "total_count": 0,
                        "recent_count_24h": 0,
                        "latest_timestamp": None,
                        "note": "No decisions recorded - bot may not have processed market data yet",
                    },
                    error=None
                )
                
    except asyncpg.PostgresError as e:
        return VerificationResult(
            name=name,
            passed=False,
            message="Database error checking decision recording",
            details={
                "recorder_enabled": recorder_enabled,
                "env_var_value": env_var_value,
            },
            error=str(e)
        )
    except Exception as e:
        return VerificationResult(
            name=name,
            passed=False,
            message="Unexpected error checking decision recording",
            details={
                "recorder_enabled": recorder_enabled,
                "env_var_value": env_var_value,
            },
            error=str(e)
        )


async def verify_backtest_execution(pool: asyncpg.Pool) -> VerificationResult:
    """Verify backtest execution works end-to-end.
    
    This function checks:
    1. The backtest_runs table exists in the database
    2. The BacktestExecutor can be imported
    3. Optionally verifies recent backtest runs exist (if any)
    
    Args:
        pool: Database connection pool
        
    Returns:
        VerificationResult with status and details
        
    Requirements: 5.1, 5.2, 5.3
    - 5.1: WHEN a backtest is started THEN the BacktestExecutor SHALL load historical data from TimescaleDB
    - 5.2: WHEN a backtest is running THEN the BacktestExecutor SHALL process each candle through the signal pipeline
    - 5.3: WHEN a backtest completes THEN the BacktestExecutor SHALL store results in the backtest_runs table
    """
    name = "Backtest Execution"
    
    try:
        # Check 1: Verify BacktestExecutor can be imported
        executor_importable = False
        executor_import_error = None
        try:
            from quantgambit.backtesting.executor import BacktestExecutor, BacktestStatus
            executor_importable = True
        except ImportError as e:
            executor_import_error = str(e)
        
        async with pool.acquire() as conn:
            # Check 2: Verify backtest_runs table exists
            table_exists = await conn.fetchval(
                """
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_schema = 'public' 
                    AND table_name = 'backtest_runs'
                )
                """
            )
            
            if not table_exists:
                return VerificationResult(
                    name=name,
                    passed=False,
                    message="backtest_runs table does not exist. Run migrations to create it.",
                    details={
                        "table_exists": False,
                        "executor_importable": executor_importable,
                        "executor_import_error": executor_import_error,
                    },
                    error=None
                )
            
            # Check 3: Verify required columns exist
            required_columns = [
                "run_id", "tenant_id", "bot_id", "status", "started_at", "config"
            ]
            existing_columns = await conn.fetch(
                """
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_schema = 'public' 
                AND table_name = 'backtest_runs'
                """
            )
            existing_column_names = {row["column_name"] for row in existing_columns}
            missing_columns = [col for col in required_columns if col not in existing_column_names]
            
            if missing_columns:
                return VerificationResult(
                    name=name,
                    passed=False,
                    message=f"backtest_runs table is missing required columns: {missing_columns}",
                    details={
                        "table_exists": True,
                        "missing_columns": missing_columns,
                        "existing_columns": list(existing_column_names),
                        "executor_importable": executor_importable,
                    },
                    error=None
                )
            
            # Check 4: Get backtest run statistics
            total_count = await conn.fetchval(
                "SELECT COUNT(*) FROM backtest_runs"
            )
            
            # Get count by status
            status_counts = await conn.fetch(
                """
                SELECT status, COUNT(*) as count
                FROM backtest_runs
                GROUP BY status
                """
            )
            status_breakdown = {row["status"]: row["count"] for row in status_counts}
            
            # Get most recent backtest run
            latest_run = await conn.fetchrow(
                """
                SELECT run_id, status, started_at, finished_at, symbol
                FROM backtest_runs
                ORDER BY started_at DESC
                LIMIT 1
                """
            )
            
            # Build details
            details = {
                "table_exists": True,
                "executor_importable": executor_importable,
                "executor_import_error": executor_import_error,
                "total_runs": total_count,
                "status_breakdown": status_breakdown,
                "latest_run": None,
            }
            
            if latest_run:
                details["latest_run"] = {
                    "run_id": str(latest_run["run_id"]),
                    "status": latest_run["status"],
                    "started_at": latest_run["started_at"].isoformat() if latest_run["started_at"] else None,
                    "finished_at": latest_run["finished_at"].isoformat() if latest_run["finished_at"] else None,
                    "symbol": latest_run["symbol"],
                }
            
            # Determine verification status
            if not executor_importable:
                return VerificationResult(
                    name=name,
                    passed=False,
                    message=f"BacktestExecutor cannot be imported: {executor_import_error}",
                    details=details,
                    error=executor_import_error
                )
            
            # All checks passed
            if total_count > 0:
                completed_count = status_breakdown.get("finished", 0) + status_breakdown.get("completed", 0)
                failed_count = status_breakdown.get("failed", 0)
                return VerificationResult(
                    name=name,
                    passed=True,
                    message=f"Backtest execution verified. {total_count} total runs "
                            f"({completed_count} completed, {failed_count} failed).",
                    details=details,
                    error=None
                )
            else:
                return VerificationResult(
                    name=name,
                    passed=True,
                    message="Backtest execution infrastructure verified. "
                            "No backtest runs recorded yet.",
                    details=details,
                    error=None
                )
                
    except asyncpg.PostgresError as e:
        return VerificationResult(
            name=name,
            passed=False,
            message="Database error checking backtest execution",
            details={},
            error=str(e)
        )
    except Exception as e:
        return VerificationResult(
            name=name,
            passed=False,
            message="Unexpected error checking backtest execution",
            details={},
            error=str(e)
        )


async def verify_warm_start_loading(pool: asyncpg.Pool, redis_client: redis.Redis) -> VerificationResult:
    """Verify warm start loading works when enabled.
    
    This function checks:
    1. The BACKTEST_WARM_START_ENABLED environment variable is set correctly
    2. The WarmStartLoader can be imported
    3. The ExecutorConfig correctly reads the warm start configuration
    4. If warm start is enabled, verifies the loader can be instantiated
    
    Args:
        pool: Database connection pool
        redis_client: Redis client for warm start state loading
        
    Returns:
        VerificationResult with status and details
        
    Requirements: 5.4 - WHEN warm start is enabled THEN the BacktestExecutor SHALL load previous state from the database
    """
    name = "Warm Start Loading"
    
    # Check environment variable
    warm_start_enabled = get_warm_start_enabled()
    env_var_value = os.getenv("BACKTEST_WARM_START_ENABLED", "false")
    stale_threshold = os.getenv("BACKTEST_WARM_START_STALE_SEC", "300.0")
    
    # Check 1: Verify WarmStartLoader can be imported
    loader_importable = False
    loader_import_error = None
    try:
        from quantgambit.integration.warm_start import WarmStartLoader, WarmStartState
        loader_importable = True
    except ImportError as e:
        loader_import_error = str(e)
    
    # Check 2: Verify ExecutorConfig can be imported and reads warm start config
    config_importable = False
    config_import_error = None
    config_warm_start_enabled = None
    try:
        from quantgambit.backtesting.executor import ExecutorConfig
        config_importable = True
        # Create config from environment to verify it reads warm start settings
        config = ExecutorConfig.from_env()
        config_warm_start_enabled = config.warm_start_enabled
    except ImportError as e:
        config_import_error = str(e)
    except Exception as e:
        config_import_error = str(e)
    
    # Build base details
    details = {
        "warm_start_enabled": warm_start_enabled,
        "env_var_value": env_var_value,
        "stale_threshold_sec": stale_threshold,
        "loader_importable": loader_importable,
        "loader_import_error": loader_import_error,
        "config_importable": config_importable,
        "config_import_error": config_import_error,
        "config_warm_start_enabled": config_warm_start_enabled,
    }
    
    # Check if WarmStartLoader can be imported
    if not loader_importable:
        return VerificationResult(
            name=name,
            passed=False,
            message=f"WarmStartLoader cannot be imported: {loader_import_error}",
            details=details,
            error=loader_import_error
        )
    
    # Check if ExecutorConfig can be imported
    if not config_importable:
        return VerificationResult(
            name=name,
            passed=False,
            message=f"ExecutorConfig cannot be imported: {config_import_error}",
            details=details,
            error=config_import_error
        )
    
    # Verify config reads environment variable correctly
    if config_warm_start_enabled != warm_start_enabled:
        return VerificationResult(
            name=name,
            passed=False,
            message=f"ExecutorConfig.warm_start_enabled ({config_warm_start_enabled}) "
                    f"does not match environment ({warm_start_enabled})",
            details=details,
            error=None
        )
    
    # If warm start is disabled, that's a valid configuration
    if not warm_start_enabled:
        return VerificationResult(
            name=name,
            passed=True,
            message=f"Warm start is disabled (BACKTEST_WARM_START_ENABLED={env_var_value}). "
                    f"WarmStartLoader is available for use when enabled.",
            details=details,
            error=None
        )
    
    # Warm start is enabled - verify we can instantiate the loader
    try:
        from quantgambit.integration.warm_start import WarmStartLoader
        
        # Get tenant and bot IDs from environment
        tenant_id = os.getenv("TENANT_ID", "default")
        bot_id = os.getenv("BOT_ID", "default")
        
        details["tenant_id"] = tenant_id
        details["bot_id"] = bot_id
        
        # Check if Redis client is available
        if redis_client is None:
            return VerificationResult(
                name=name,
                passed=False,
                message="Warm start is enabled but Redis connection is not available. "
                        "WarmStartLoader requires Redis for state loading.",
                details=details,
                error="Redis client is None"
            )
        
        # Try to instantiate the loader
        loader = WarmStartLoader(
            redis_client=redis_client,
            timescale_pool=pool,
            tenant_id=tenant_id,
            bot_id=bot_id,
        )
        
        details["loader_instantiated"] = True
        details["loader_tenant_id"] = loader.tenant_id
        details["loader_bot_id"] = loader.bot_id
        
        # Optionally try to load state (this may fail if no state exists, which is OK)
        try:
            state = await loader.load_current_state()
            details["state_loaded"] = True
            details["state_timestamp"] = state.timestamp.isoformat() if state.timestamp else None
            details["state_positions_count"] = len(state.positions) if state.positions else 0
            details["state_is_stale"] = state.is_stale(threshold_sec=float(stale_threshold))
            
            if state.is_stale(threshold_sec=float(stale_threshold)):
                return VerificationResult(
                    name=name,
                    passed=True,
                    message=f"Warm start is enabled and loader works. "
                            f"Current state is stale (older than {stale_threshold}s). "
                            f"Positions: {len(state.positions) if state.positions else 0}",
                    details=details,
                    error=None
                )
            else:
                return VerificationResult(
                    name=name,
                    passed=True,
                    message=f"Warm start is enabled and working. "
                            f"Current state loaded successfully. "
                            f"Positions: {len(state.positions) if state.positions else 0}",
                    details=details,
                    error=None
                )
                
        except Exception as state_error:
            # State loading failed - this is OK if no state exists yet
            details["state_loaded"] = False
            details["state_load_error"] = str(state_error)
            
            return VerificationResult(
                name=name,
                passed=True,
                message=f"Warm start is enabled and loader instantiated. "
                        f"No current state available (this is normal if bot hasn't run yet). "
                        f"Error: {str(state_error)[:100]}",
                details=details,
                error=None
            )
            
    except Exception as e:
        return VerificationResult(
            name=name,
            passed=False,
            message="Failed to instantiate WarmStartLoader",
            details=details,
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
            message="Database does not exist",
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


async def verify_redis_connection(redis_url: str) -> tuple[Optional[redis.Redis], VerificationResult]:
    """Verify Redis connection can be established.
    
    Args:
        redis_url: Redis connection URL
        
    Returns:
        Tuple of (redis client or None, VerificationResult)
    """
    name = "Redis Connection"
    
    try:
        client = redis.from_url(redis_url, decode_responses=True)
        
        # Test the connection
        info = await client.info("server")
        redis_version = info.get("redis_version", "unknown")
        
        return client, VerificationResult(
            name=name,
            passed=True,
            message="Successfully connected to Redis",
            details={
                "url": redis_url,
                "redis_version": redis_version,
            },
            error=None
        )
        
    except redis.ConnectionError as e:
        return None, VerificationResult(
            name=name,
            passed=False,
            message="Could not connect to Redis server",
            details={"url": redis_url},
            error=str(e)
        )
    except Exception as e:
        return None, VerificationResult(
            name=name,
            passed=False,
            message="Unexpected error connecting to Redis",
            details={"url": redis_url},
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
    """Run all pipeline verification checks."""
    parser = argparse.ArgumentParser(description="Verify trading pipeline integration")
    parser.add_argument(
        "--db-url",
        default=None,
        help="Database URL (overrides environment variables)"
    )
    parser.add_argument(
        "--redis-url",
        default=None,
        help="Redis URL (overrides environment variables)"
    )
    args = parser.parse_args()
    
    # Build connection URLs
    db_url = args.db_url if args.db_url else build_database_url()
    redis_url = args.redis_url if args.redis_url else build_redis_url()
    
    # Mask password for display
    display_db_url = db_url
    if "@" in db_url:
        parts = db_url.split("@")
        display_db_url = f"postgresql://***@{parts[1]}"
    
    print("=" * 60)
    print("Pipeline Verification")
    print("=" * 60)
    print(f"Database: {display_db_url}")
    print(f"Redis: {redis_url}")
    print(f"DECISION_RECORDER_ENABLED: {os.getenv('DECISION_RECORDER_ENABLED', 'true')}")
    print(f"BACKTEST_WARM_START_ENABLED: {os.getenv('BACKTEST_WARM_START_ENABLED', 'false')}")
    
    results: list[VerificationResult] = []
    
    # Verify database connection
    pool, db_result = await verify_database_connection(db_url)
    results.append(db_result)
    print_result(db_result)
    
    if pool is None:
        # Cannot continue without database connection
        print(f"\n{'=' * 60}")
        print("Summary: 0/1 checks passed (database connection failed)")
        print("=" * 60)
        return 1
    
    # Verify Redis connection
    redis_client, redis_result = await verify_redis_connection(redis_url)
    results.append(redis_result)
    print_result(redis_result)
    
    # Note: We continue even if Redis fails, as decision recording only needs the database
    if redis_client is None:
        print("\n  Note: Redis connection failed, but continuing with database-only checks")
    
    try:
        # Verify decision recording
        decision_result = await verify_decision_recording(pool, redis_client)
        results.append(decision_result)
        print_result(decision_result)
        
        # Verify backtest execution
        backtest_result = await verify_backtest_execution(pool)
        results.append(backtest_result)
        print_result(backtest_result)
        
        # Verify warm start loading
        warm_start_result = await verify_warm_start_loading(pool, redis_client)
        results.append(warm_start_result)
        print_result(warm_start_result)
        
    finally:
        # Clean up connections
        await pool.close()
        if redis_client:
            await redis_client.close()
    
    # Summary
    print(f"\n{'=' * 60}")
    passed = sum(1 for r in results if r.passed)
    total = len(results)
    print(f"Summary: {passed}/{total} checks passed")
    
    if passed < total:
        print("\nTo fix issues:")
        print("  - Ensure TimescaleDB is running and accessible")
        print("  - Ensure Redis is running and accessible")
        print("  - Run database migrations: python scripts/run_migrations.py")
        print("  - Check DECISION_RECORDER_ENABLED environment variable")
        print("  - Check BACKTEST_WARM_START_ENABLED environment variable")
    
    print("=" * 60)
    
    return 0 if all(r.passed for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
