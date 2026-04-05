"""
Property-based tests for BacktestJobQueue.

Feature: backtesting-api-integration
Property 9: Async Job Execution
Property 13: Job Cancellation

Validates: Requirements R5.1, R5.5
"""

import asyncio
import time
import pytest
from hypothesis import given, strategies as st, settings, assume
from typing import Dict, Any

from quantgambit.backtesting.job_queue import (
    BacktestJobQueue,
    JobInfo,
    JobStatus,
)


# Strategies for generating test data
config_values = st.fixed_dictionaries({
    "symbol": st.sampled_from(["BTC-USDT-SWAP", "ETH-USDT-SWAP", "SOL-USDT-SWAP"]),
    "start_date": st.just("2024-01-01"),
    "end_date": st.just("2024-01-31"),
    "initial_capital": st.floats(min_value=1000.0, max_value=100000.0, allow_nan=False),
})

max_concurrent_values = st.integers(min_value=1, max_value=5)
num_jobs_values = st.integers(min_value=1, max_value=10)


async def fast_executor(run_id: str, config: Dict[str, Any]) -> None:
    """A fast executor that completes quickly."""
    await asyncio.sleep(0.01)  # 10ms


async def slow_executor(run_id: str, config: Dict[str, Any]) -> None:
    """A slow executor for testing cancellation."""
    await asyncio.sleep(10.0)  # 10 seconds


async def failing_executor(run_id: str, config: Dict[str, Any]) -> None:
    """An executor that always fails."""
    raise ValueError("Simulated failure")


class TestAsyncJobExecution:
    """
    Property 9: Async Job Execution
    
    For any backtest creation request, the API should return immediately
    (< 1 second) with a run_id, while the actual backtest executes asynchronously.
    
    **Validates: Requirements R5.1**
    """
    
    @given(config=config_values)
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_submit_returns_immediately(self, config):
        """
        Property 9: Async Job Execution
        
        For any valid config, submit() should return a run_id immediately
        (within 1 second) without waiting for the job to complete.
        
        **Validates: Requirements R5.1**
        """
        queue = BacktestJobQueue(max_concurrent=2)
        
        start_time = time.time()
        run_id = await queue.submit(config, slow_executor)
        elapsed = time.time() - start_time
        
        # Should return immediately (< 1 second)
        assert elapsed < 1.0, f"submit() took {elapsed:.2f}s, expected < 1s"
        
        # Should return a valid run_id
        assert run_id is not None
        assert isinstance(run_id, str)
        assert len(run_id) > 0
        
        # Job should be pending or running
        status = queue.get_job_status(run_id)
        assert status in (JobStatus.PENDING, JobStatus.RUNNING)
        
        # Cleanup
        await queue.shutdown(timeout=1.0)
    
    @given(config=config_values)
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_job_completes_asynchronously(self, config):
        """
        Property 9: Async Job Execution
        
        For any submitted job, it should eventually complete asynchronously.
        
        **Validates: Requirements R5.1**
        """
        queue = BacktestJobQueue(max_concurrent=2)
        
        run_id = await queue.submit(config, fast_executor)
        
        # Wait for completion
        final_status = await queue.wait_for_job(run_id, timeout=5.0)
        
        # Should complete successfully
        assert final_status == JobStatus.COMPLETED
        
        # Job info should reflect completion
        job_info = queue.get_job_info(run_id)
        assert job_info is not None
        assert job_info.status == JobStatus.COMPLETED
        assert job_info.finished_at is not None
        assert job_info.started_at is not None
        assert job_info.finished_at >= job_info.started_at
    
    @given(
        max_concurrent=max_concurrent_values,
        num_jobs=num_jobs_values,
    )
    @settings(max_examples=100, deadline=None)
    @pytest.mark.asyncio
    async def test_concurrency_control(self, max_concurrent, num_jobs):
        """
        Property 9: Async Job Execution
        
        For any number of submitted jobs, at most max_concurrent should
        be running at any time.
        
        **Validates: Requirements R5.1**
        """
        queue = BacktestJobQueue(max_concurrent=max_concurrent)
        
        # Track max concurrent running jobs
        max_observed_running = 0
        running_count_samples = []
        
        async def tracking_executor(run_id: str, config: Dict[str, Any]) -> None:
            nonlocal max_observed_running
            current_running = queue.running_count
            max_observed_running = max(max_observed_running, current_running)
            running_count_samples.append(current_running)
            await asyncio.sleep(0.05)  # 50ms
        
        # Submit all jobs
        run_ids = []
        for i in range(num_jobs):
            config = {"job_index": i}
            run_id = await queue.submit(config, tracking_executor)
            run_ids.append(run_id)
        
        # Wait for all to complete
        for run_id in run_ids:
            await queue.wait_for_job(run_id, timeout=10.0)
        
        # Verify concurrency was respected
        assert max_observed_running <= max_concurrent, \
            f"Max running ({max_observed_running}) exceeded limit ({max_concurrent})"
    
    @given(config=config_values)
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_unique_run_ids(self, config):
        """
        Property 9: Async Job Execution
        
        Each submitted job should receive a unique run_id.
        
        **Validates: Requirements R5.1**
        """
        queue = BacktestJobQueue(max_concurrent=5)
        
        run_ids = []
        for _ in range(5):
            run_id = await queue.submit(config.copy(), fast_executor)
            run_ids.append(run_id)
        
        # All run_ids should be unique
        assert len(run_ids) == len(set(run_ids)), "Duplicate run_ids generated"
        
        # Cleanup
        await queue.shutdown(timeout=5.0)
    
    @given(config=config_values)
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_failed_job_captures_error(self, config):
        """
        Property 9: Async Job Execution
        
        For any job that fails, the error should be captured in job info.
        
        **Validates: Requirements R5.1**
        """
        queue = BacktestJobQueue(max_concurrent=2)
        
        run_id = await queue.submit(config, failing_executor)
        
        # Wait for completion
        final_status = await queue.wait_for_job(run_id, timeout=5.0)
        
        # Should be marked as failed
        assert final_status == JobStatus.FAILED
        
        # Error message should be captured
        job_info = queue.get_job_info(run_id)
        assert job_info is not None
        assert job_info.error_message is not None
        assert "Simulated failure" in job_info.error_message


class TestJobCancellation:
    """
    Property 13: Job Cancellation
    
    For any running backtest, issuing a cancel request should stop the job
    and update status to "cancelled" within a reasonable timeout.
    
    **Validates: Requirements R5.5**
    """
    
    @given(config=config_values)
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_cancel_running_job(self, config):
        """
        Property 13: Job Cancellation
        
        For any running job, cancel() should stop it and update status
        to CANCELLED.
        
        **Validates: Requirements R5.5**
        """
        queue = BacktestJobQueue(max_concurrent=2)
        
        # Submit a slow job
        run_id = await queue.submit(config, slow_executor)
        
        # Wait a bit for it to start
        await asyncio.sleep(0.1)
        
        # Cancel it
        start_time = time.time()
        cancelled = await queue.cancel(run_id, timeout=5.0)
        elapsed = time.time() - start_time
        
        # Should cancel within reasonable time
        assert cancelled, "cancel() returned False"
        assert elapsed < 5.0, f"Cancellation took {elapsed:.2f}s"
        
        # Status should be cancelled
        status = queue.get_job_status(run_id)
        assert status == JobStatus.CANCELLED
        
        # Job info should reflect cancellation
        job_info = queue.get_job_info(run_id)
        assert job_info is not None
        assert job_info.status == JobStatus.CANCELLED
        assert job_info.finished_at is not None
    
    @given(config=config_values)
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_cancel_pending_job(self, config):
        """
        Property 13: Job Cancellation
        
        For any pending job (waiting for semaphore), cancel() should
        prevent it from running.
        
        **Validates: Requirements R5.5**
        """
        # Create queue with 1 slot
        queue = BacktestJobQueue(max_concurrent=1)
        
        # Submit a slow job to occupy the slot
        await queue.submit({"blocking": True}, slow_executor)
        
        # Submit another job - it will be pending
        run_id = await queue.submit(config, fast_executor)
        
        # Give it a moment
        await asyncio.sleep(0.05)
        
        # The second job should be pending
        status = queue.get_job_status(run_id)
        assert status == JobStatus.PENDING, f"Expected PENDING, got {status}"
        
        # Cancel the pending job
        cancelled = await queue.cancel(run_id, timeout=2.0)
        assert cancelled
        
        # Status should be cancelled
        status = queue.get_job_status(run_id)
        assert status == JobStatus.CANCELLED
        
        # Cleanup
        await queue.shutdown(timeout=1.0)
    
    @given(config=config_values)
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_cancel_completed_job_returns_false(self, config):
        """
        Property 13: Job Cancellation
        
        For any completed job, cancel() should return False (nothing to cancel).
        
        **Validates: Requirements R5.5**
        """
        queue = BacktestJobQueue(max_concurrent=2)
        
        # Submit and wait for completion
        run_id = await queue.submit(config, fast_executor)
        await queue.wait_for_job(run_id, timeout=5.0)
        
        # Try to cancel completed job
        cancelled = await queue.cancel(run_id)
        
        # Should return False
        assert not cancelled
        
        # Status should still be completed
        status = queue.get_job_status(run_id)
        assert status == JobStatus.COMPLETED
    
    @given(config=config_values)
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_cancel_nonexistent_job_returns_false(self, config):
        """
        Property 13: Job Cancellation
        
        For any non-existent run_id, cancel() should return False.
        
        **Validates: Requirements R5.5**
        """
        queue = BacktestJobQueue(max_concurrent=2)
        
        # Try to cancel non-existent job
        cancelled = await queue.cancel("nonexistent-run-id")
        
        # Should return False
        assert not cancelled


class TestJobQueueEdgeCases:
    """Edge case tests for BacktestJobQueue."""
    
    @pytest.mark.asyncio
    async def test_duplicate_run_id_raises_error(self):
        """Submitting with duplicate run_id should raise ValueError."""
        queue = BacktestJobQueue(max_concurrent=2)
        
        run_id = "test-run-id"
        await queue.submit({"test": 1}, fast_executor, run_id=run_id)
        
        with pytest.raises(ValueError, match="already exists"):
            await queue.submit({"test": 2}, fast_executor, run_id=run_id)
        
        await queue.shutdown(timeout=5.0)
    
    @pytest.mark.asyncio
    async def test_invalid_max_concurrent_raises_error(self):
        """Creating queue with invalid max_concurrent should raise ValueError."""
        with pytest.raises(ValueError, match="max_concurrent"):
            BacktestJobQueue(max_concurrent=0)
        
        with pytest.raises(ValueError, match="max_concurrent"):
            BacktestJobQueue(max_concurrent=-1)
    
    @pytest.mark.asyncio
    async def test_invalid_timeout_raises_error(self):
        """Creating queue with invalid timeout should raise ValueError."""
        with pytest.raises(ValueError, match="timeout_hours"):
            BacktestJobQueue(timeout_hours=0)
        
        with pytest.raises(ValueError, match="timeout_hours"):
            BacktestJobQueue(timeout_hours=-1)
    
    @pytest.mark.asyncio
    async def test_cleanup_removes_old_completed_jobs(self):
        """cleanup_completed should remove old completed jobs."""
        queue = BacktestJobQueue(max_concurrent=2)
        
        # Submit and complete a job
        run_id = await queue.submit({"test": 1}, fast_executor)
        await queue.wait_for_job(run_id, timeout=5.0)
        
        # Job should exist
        assert queue.get_job_info(run_id) is not None
        
        # Cleanup with 0 max age should remove it
        removed = await queue.cleanup_completed(max_age_seconds=0)
        assert removed == 1
        
        # Job should be gone
        assert queue.get_job_info(run_id) is None
    
    @pytest.mark.asyncio
    async def test_list_jobs_with_status_filter(self):
        """list_jobs should filter by status correctly."""
        queue = BacktestJobQueue(max_concurrent=5)
        
        # Submit multiple jobs
        run_ids = []
        for i in range(3):
            run_id = await queue.submit({"index": i}, fast_executor)
            run_ids.append(run_id)
        
        # Wait for all to complete
        for run_id in run_ids:
            await queue.wait_for_job(run_id, timeout=5.0)
        
        # All should be completed
        completed_jobs = queue.list_jobs(status=JobStatus.COMPLETED)
        assert len(completed_jobs) == 3
        
        # No pending jobs
        pending_jobs = queue.list_jobs(status=JobStatus.PENDING)
        assert len(pending_jobs) == 0
    
    @pytest.mark.asyncio
    async def test_job_info_to_dict(self):
        """JobInfo.to_dict() should return all fields."""
        queue = BacktestJobQueue(max_concurrent=2)
        
        config = {"symbol": "BTC-USDT-SWAP"}
        run_id = await queue.submit(config, fast_executor)
        await queue.wait_for_job(run_id, timeout=5.0)
        
        job_info = queue.get_job_info(run_id)
        assert job_info is not None
        
        result = job_info.to_dict()
        
        assert "run_id" in result
        assert "status" in result
        assert "config" in result
        assert "created_at" in result
        assert "started_at" in result
        assert "finished_at" in result
        assert "error_message" in result
        
        assert result["run_id"] == run_id
        assert result["status"] == "completed"
        assert result["config"] == config


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
