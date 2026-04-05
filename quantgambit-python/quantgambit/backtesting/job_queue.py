"""Job queue manager for background backtest execution.

This module provides the BacktestJobQueue class that manages asyncio tasks
for running backtests in the background with concurrency control.

Feature: backtesting-api-integration
Requirements: R5.1 (Async Job Execution), R5.5 (Job Cancellation)
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Coroutine, Dict, Optional


class JobStatus(str, Enum):
    """Status of a backtest job."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class JobInfo:
    """Information about a queued job."""
    run_id: str
    status: JobStatus
    config: Dict[str, Any]
    created_at: float
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    error_message: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "run_id": self.run_id,
            "status": self.status.value,
            "config": self.config,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "error_message": self.error_message,
        }


# Type alias for the executor function
ExecutorFunc = Callable[[str, Dict[str, Any]], Coroutine[Any, Any, None]]


class BacktestJobQueue:
    """Manages background backtest execution using asyncio tasks.
    
    This class provides:
    - Job submission with immediate return of run_id
    - Concurrency control via semaphore
    - Job cancellation
    - Job status tracking
    - Cleanup of completed jobs
    
    Example usage:
        queue = BacktestJobQueue(max_concurrent=2)
        
        async def my_executor(run_id: str, config: dict) -> None:
            # Execute backtest logic
            pass
        
        run_id = await queue.submit(config, my_executor)
        status = queue.get_job_status(run_id)
        await queue.cancel(run_id)
    """
    
    def __init__(self, max_concurrent: int = 2, timeout_hours: float = 4.0):
        """Initialize the job queue.
        
        Args:
            max_concurrent: Maximum number of concurrent backtest jobs.
            timeout_hours: Maximum time a job can run before being cancelled.
        """
        if max_concurrent < 1:
            raise ValueError("max_concurrent must be at least 1")
        if timeout_hours <= 0:
            raise ValueError("timeout_hours must be positive")
            
        self.max_concurrent = max_concurrent
        self.timeout_seconds = timeout_hours * 3600
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._running_tasks: Dict[str, asyncio.Task] = {}
        self._job_info: Dict[str, JobInfo] = {}
        self._lock = asyncio.Lock()
    
    async def submit(
        self,
        config: Dict[str, Any],
        executor: ExecutorFunc,
        run_id: Optional[str] = None,
    ) -> str:
        """Submit a backtest job for execution.
        
        The job is queued and will start when a slot becomes available
        (controlled by the semaphore). This method returns immediately
        with the run_id.
        
        Args:
            config: Configuration for the backtest job.
            executor: Async function that executes the backtest.
                     Signature: async def executor(run_id: str, config: dict) -> None
            run_id: Optional run ID. If not provided, one will be generated.
        
        Returns:
            The run_id for the submitted job.
        
        Raises:
            ValueError: If a job with the same run_id already exists.
        """
        if run_id is None:
            run_id = str(uuid.uuid4())
        
        async with self._lock:
            if run_id in self._job_info:
                raise ValueError(f"Job with run_id {run_id} already exists")
            
            # Create job info
            job_info = JobInfo(
                run_id=run_id,
                status=JobStatus.PENDING,
                config=config,
                created_at=time.time(),
            )
            self._job_info[run_id] = job_info
            
            # Create and start the task
            task = asyncio.create_task(
                self._execute_job(run_id, config, executor)
            )
            self._running_tasks[run_id] = task
        
        return run_id
    
    async def cancel(self, run_id: str, timeout: float = 5.0) -> bool:
        """Cancel a running or pending backtest job.
        
        Args:
            run_id: The ID of the job to cancel.
            timeout: Maximum time to wait for cancellation to complete.
        
        Returns:
            True if the job was found and cancellation was initiated,
            False if the job was not found or already completed.
        """
        async with self._lock:
            task = self._running_tasks.get(run_id)
            job_info = self._job_info.get(run_id)
            
            if task is None or job_info is None:
                return False
            
            # Can only cancel pending or running jobs
            if job_info.status not in (JobStatus.PENDING, JobStatus.RUNNING):
                return False
            
            # Cancel the task
            task.cancel()
        
        # Wait for cancellation to complete (outside lock)
        try:
            await asyncio.wait_for(
                asyncio.shield(task),
                timeout=timeout
            )
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass

        # Ensure status is updated even if the task was cancelled before it reached
        # its CancelledError handler (e.g., cancelled while pending on the semaphore).
        async with self._lock:
            job_info = self._job_info.get(run_id)
            if job_info and job_info.status in (JobStatus.PENDING, JobStatus.RUNNING):
                self._job_info[run_id] = JobInfo(
                    run_id=run_id,
                    status=JobStatus.CANCELLED,
                    config=job_info.config,
                    created_at=job_info.created_at,
                    started_at=job_info.started_at,
                    finished_at=time.time(),
                )
        
        return True
    
    def get_job_status(self, run_id: str) -> Optional[JobStatus]:
        """Get the status of a job.
        
        Args:
            run_id: The ID of the job.
        
        Returns:
            The job status, or None if the job doesn't exist.
        """
        job_info = self._job_info.get(run_id)
        return job_info.status if job_info else None
    
    def get_job_info(self, run_id: str) -> Optional[JobInfo]:
        """Get full information about a job.
        
        Args:
            run_id: The ID of the job.
        
        Returns:
            The JobInfo object, or None if the job doesn't exist.
        """
        return self._job_info.get(run_id)
    
    def list_jobs(
        self,
        status: Optional[JobStatus] = None,
    ) -> list[JobInfo]:
        """List all jobs, optionally filtered by status.
        
        Args:
            status: Optional status filter.
        
        Returns:
            List of JobInfo objects.
        """
        jobs = list(self._job_info.values())
        if status is not None:
            jobs = [j for j in jobs if j.status == status]
        return jobs
    
    @property
    def running_count(self) -> int:
        """Number of currently running jobs."""
        return sum(
            1 for j in self._job_info.values()
            if j.status == JobStatus.RUNNING
        )
    
    @property
    def pending_count(self) -> int:
        """Number of pending jobs waiting to start."""
        return sum(
            1 for j in self._job_info.values()
            if j.status == JobStatus.PENDING
        )
    
    @property
    def active_count(self) -> int:
        """Number of active jobs (pending + running)."""
        return self.pending_count + self.running_count
    
    async def cleanup_completed(self, max_age_seconds: float = 3600) -> int:
        """Remove completed/failed/cancelled jobs older than max_age.
        
        Args:
            max_age_seconds: Maximum age of completed jobs to keep.
        
        Returns:
            Number of jobs removed.
        """
        now = time.time()
        to_remove = []
        
        async with self._lock:
            for run_id, job_info in self._job_info.items():
                if job_info.status in (
                    JobStatus.COMPLETED,
                    JobStatus.FAILED,
                    JobStatus.CANCELLED,
                ):
                    age = now - (job_info.finished_at or job_info.created_at)
                    if age > max_age_seconds:
                        to_remove.append(run_id)
            
            for run_id in to_remove:
                self._job_info.pop(run_id, None)
                self._running_tasks.pop(run_id, None)
        
        return len(to_remove)
    
    async def wait_for_job(
        self,
        run_id: str,
        timeout: Optional[float] = None,
    ) -> Optional[JobStatus]:
        """Wait for a job to complete.
        
        Args:
            run_id: The ID of the job to wait for.
            timeout: Maximum time to wait (None for no timeout).
        
        Returns:
            The final job status, or None if timeout or job not found.
        """
        task = self._running_tasks.get(run_id)
        if task is None:
            job_info = self._job_info.get(run_id)
            return job_info.status if job_info else None
        
        try:
            await asyncio.wait_for(task, timeout=timeout)
        except asyncio.TimeoutError:
            return None
        except asyncio.CancelledError:
            pass
        
        job_info = self._job_info.get(run_id)
        return job_info.status if job_info else None
    
    async def shutdown(self, timeout: float = 30.0) -> None:
        """Shutdown the queue, cancelling all running jobs.
        
        Args:
            timeout: Maximum time to wait for jobs to cancel.
        """
        # Cancel all running tasks
        async with self._lock:
            for task in self._running_tasks.values():
                task.cancel()
        
        # Wait for all tasks to complete
        if self._running_tasks:
            tasks = list(self._running_tasks.values())
            try:
                await asyncio.wait_for(
                    asyncio.gather(*tasks, return_exceptions=True),
                    timeout=timeout
                )
            except asyncio.TimeoutError:
                pass
    
    async def _execute_job(
        self,
        run_id: str,
        config: Dict[str, Any],
        executor: ExecutorFunc,
    ) -> None:
        """Execute a backtest job with concurrency control.
        
        This method:
        1. Acquires the semaphore (waits if at max concurrency)
        2. Updates status to RUNNING
        3. Executes the backtest
        4. Updates status to COMPLETED/FAILED/CANCELLED
        5. Releases the semaphore
        """
        try:
            # Wait for semaphore (concurrency control)
            async with self._semaphore:
                # Update status to running
                async with self._lock:
                    job_info = self._job_info.get(run_id)
                    if job_info is None:
                        return
                    
                    # Check if cancelled while waiting
                    if job_info.status == JobStatus.CANCELLED:
                        return
                    
                    job_info = JobInfo(
                        run_id=run_id,
                        status=JobStatus.RUNNING,
                        config=config,
                        created_at=job_info.created_at,
                        started_at=time.time(),
                    )
                    self._job_info[run_id] = job_info
                
                # Execute with timeout
                try:
                    await asyncio.wait_for(
                        executor(run_id, config),
                        timeout=self.timeout_seconds
                    )
                    
                    # Mark as completed
                    await self._mark_completed(run_id)
                    
                except asyncio.TimeoutError:
                    await self._mark_failed(
                        run_id,
                        f"Job timed out after {self.timeout_seconds / 3600:.1f} hours"
                    )
                    
        except asyncio.CancelledError:
            await self._mark_cancelled(run_id)
            raise
            
        except Exception as e:
            await self._mark_failed(run_id, str(e))
            
        finally:
            # Remove from running tasks
            async with self._lock:
                self._running_tasks.pop(run_id, None)
    
    async def _mark_completed(self, run_id: str) -> None:
        """Mark a job as completed."""
        async with self._lock:
            job_info = self._job_info.get(run_id)
            if job_info:
                self._job_info[run_id] = JobInfo(
                    run_id=run_id,
                    status=JobStatus.COMPLETED,
                    config=job_info.config,
                    created_at=job_info.created_at,
                    started_at=job_info.started_at,
                    finished_at=time.time(),
                )
    
    async def _mark_failed(self, run_id: str, error_message: str) -> None:
        """Mark a job as failed."""
        async with self._lock:
            job_info = self._job_info.get(run_id)
            if job_info:
                self._job_info[run_id] = JobInfo(
                    run_id=run_id,
                    status=JobStatus.FAILED,
                    config=job_info.config,
                    created_at=job_info.created_at,
                    started_at=job_info.started_at,
                    finished_at=time.time(),
                    error_message=error_message,
                )
    
    async def _mark_cancelled(self, run_id: str) -> None:
        """Mark a job as cancelled."""
        async with self._lock:
            job_info = self._job_info.get(run_id)
            if job_info:
                self._job_info[run_id] = JobInfo(
                    run_id=run_id,
                    status=JobStatus.CANCELLED,
                    config=job_info.config,
                    created_at=job_info.created_at,
                    started_at=job_info.started_at,
                    finished_at=time.time(),
                )
