"""Backtest worker that polls for pending jobs and executes them.

Run this as a background process to process backtest jobs:
    python -m quantgambit.backtesting.worker

Or with PM2:
    pm2 start python --name backtest-worker -- -m quantgambit.backtesting.worker
"""

import asyncio
import logging
import os
import signal
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote_plus

import asyncpg

from quantgambit.config.env_loading import apply_layered_env_defaults

apply_layered_env_defaults(Path(__file__).resolve().parents[2], os.getenv("ENV_FILE"), os.environ)

from quantgambit.backtesting.strategy_executor import StrategyBacktestExecutor, StrategyExecutorConfig
from quantgambit.backtesting.store import BacktestStore

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


class BacktestWorker:
    """Worker that polls for pending backtests and executes them."""
    
    def __init__(
        self,
        poll_interval: float = 5.0,
        max_concurrent: int = 2,
        job_timeout_seconds: float = 3600.0,
        stale_running_minutes: float = 30.0,
    ):
        """Initialize the worker.
        
        Args:
            poll_interval: Seconds between polling for new jobs
            max_concurrent: Maximum concurrent backtest executions
        """
        self.poll_interval = poll_interval
        self.max_concurrent = max_concurrent
        self.job_timeout_seconds = max(60.0, float(job_timeout_seconds))
        self.stale_running_minutes = max(1.0, float(stale_running_minutes))
        self._running = False
        self._platform_pool = None
        self._executor = None
        self._active_tasks: set = set()
        self._semaphore = None
    
    async def start(self):
        """Start the worker."""
        logger.info("Starting backtest worker...")
        
        # Create database pool
        db_host = os.getenv("DASHBOARD_DB_HOST", os.getenv("PLATFORM_DB_HOST", "localhost"))
        db_port = os.getenv("DASHBOARD_DB_PORT", "5432")
        db_name = os.getenv("DASHBOARD_DB_NAME", "platform_db")
        db_user = os.getenv("DASHBOARD_DB_USER", "platform")
        db_password = os.getenv("DASHBOARD_DB_PASSWORD", "platform_pw")
        
        encoded_user = quote_plus(db_user)
        encoded_password = quote_plus(db_password) if db_password else None
        auth = f"{encoded_user}:{encoded_password}@" if encoded_password else f"{encoded_user}@"
        ssl_query = "" if db_host in {"localhost", "127.0.0.1"} else "?sslmode=require"
        dsn = f"postgresql://{auth}{db_host}:{db_port}/{db_name}{ssl_query}"
        
        self._platform_pool = await asyncpg.create_pool(dsn, min_size=2, max_size=10)
        logger.info(f"Connected to platform database at {db_host}:{db_port}/{db_name}")
        
        # Create executor - use real strategy engine
        executor_config = StrategyExecutorConfig.from_env()
        self._executor = StrategyBacktestExecutor(self._platform_pool, executor_config)
        
        # Create semaphore for concurrency control
        self._semaphore = asyncio.Semaphore(self.max_concurrent)
        
        self._running = True
        logger.info(f"Backtest worker started (max_concurrent={self.max_concurrent}, poll_interval={self.poll_interval}s)")
        
        # Start polling loop
        await self._poll_loop()
    
    async def stop(self):
        """Stop the worker gracefully."""
        logger.info("Stopping backtest worker...")
        self._running = False
        
        # Wait for active tasks to complete
        if self._active_tasks:
            logger.info(f"Waiting for {len(self._active_tasks)} active tasks to complete...")
            await asyncio.gather(*self._active_tasks, return_exceptions=True)
        
        # Close connections
        if self._executor:
            await self._executor.close()
        if self._platform_pool:
            await self._platform_pool.close()
        
        logger.info("Backtest worker stopped")
    
    async def _poll_loop(self):
        """Main polling loop."""
        while self._running:
            try:
                await self._recover_stale_running_jobs()
                # Find pending jobs
                pending_jobs = await self._get_pending_jobs()
                
                for job in pending_jobs:
                    if not self._running:
                        break
                    
                    # Check if we can start a new task
                    if self._semaphore.locked():
                        logger.debug("Max concurrent jobs reached, waiting...")
                        break
                    
                    # Start execution task
                    task = asyncio.create_task(self._execute_job(job))
                    self._active_tasks.add(task)
                    task.add_done_callback(self._active_tasks.discard)
                
            except Exception as e:
                logger.exception(f"Error in poll loop: {e}")
            
            # Wait before next poll
            await asyncio.sleep(self.poll_interval)

    async def _recover_stale_running_jobs(self) -> None:
        """
        Requeue jobs stuck in `running` from previous worker crashes/restarts.

        The worker only picks `pending` jobs, so stale `running` rows can block
        backtesting forever unless we explicitly recover them.
        """
        cutoff_minutes = float(self.stale_running_minutes)
        async with self._platform_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                UPDATE backtest_runs
                SET status='pending',
                    started_at=COALESCE(started_at, created_at, NOW()),
                    error_message=COALESCE(error_message || E'\n', '') ||
                        format(
                            '[auto-recovered %s] stale running job requeued by worker',
                            to_char(NOW(), 'YYYY-MM-DD HH24:MI:SSOF')
                        )
                WHERE status='running'
                  AND started_at IS NOT NULL
                  AND started_at < NOW() - ($1::double precision * INTERVAL '1 minute')
                RETURNING run_id
                """,
                cutoff_minutes,
            )
        if rows:
            logger.warning(
                "Recovered %d stale running backtest job(s) older than %.1f minutes",
                len(rows),
                cutoff_minutes,
            )
    
    async def _get_pending_jobs(self) -> list:
        """Get pending backtest jobs from the database."""
        store = BacktestStore(self._platform_pool)
        runs = await store.list_runs(status="pending", limit=10)
        return runs
    
    async def _execute_job(self, job):
        """Execute a single backtest job."""
        async with self._semaphore:
            run_id = job.run_id
            logger.info(f"Starting backtest job {run_id}")
            
            try:
                # Parse config
                config = job.config if isinstance(job.config, dict) else {}
                
                # Execute backtest
                result = await asyncio.wait_for(
                    self._executor.execute(
                        run_id=run_id,
                        tenant_id=job.tenant_id,
                        bot_id=job.bot_id,
                        config=config,
                    ),
                    timeout=self.job_timeout_seconds,
                )
                
                if result.get("status") == "completed":
                    logger.info(f"Backtest {run_id} completed: return={result.get('total_return_pct', 0):.2f}%")
                else:
                    logger.warning(f"Backtest {run_id} failed: {result.get('error')}")
                    
            except asyncio.TimeoutError:
                logger.error(
                    "Backtest %s timed out after %.0fs",
                    run_id,
                    self.job_timeout_seconds,
                )
                await self._executor._update_status(
                    run_id=run_id,
                    tenant_id=job.tenant_id,
                    bot_id=job.bot_id,
                    status="failed",
                    config=config,
                    started_at=getattr(job, "started_at", datetime.now(timezone.utc).isoformat()),
                    finished_at=datetime.now(timezone.utc).isoformat(),
                    error_message=f"Backtest timed out after {int(self.job_timeout_seconds)}s",
                )
            except Exception as e:
                logger.exception(f"Error executing backtest {run_id}: {e}")


async def main():
    """Main entry point."""
    worker = BacktestWorker(
        poll_interval=float(os.getenv("BACKTEST_POLL_INTERVAL", "5")),
        max_concurrent=int(os.getenv("BACKTEST_MAX_CONCURRENT", "2")),
        job_timeout_seconds=float(os.getenv("BACKTEST_JOB_TIMEOUT_SECONDS", "3600")),
        stale_running_minutes=float(os.getenv("BACKTEST_STALE_RUNNING_MINUTES", "30")),
    )
    
    # Handle shutdown signals
    loop = asyncio.get_event_loop()
    
    def signal_handler():
        logger.info("Received shutdown signal")
        asyncio.create_task(worker.stop())
    
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, signal_handler)
    
    try:
        await worker.start()
    except asyncio.CancelledError:
        pass
    finally:
        await worker.stop()


if __name__ == "__main__":
    asyncio.run(main())
