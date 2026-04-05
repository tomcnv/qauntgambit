"""
Performance test harness for hot path.

Measures latency percentiles and throughput using SimExchange.
Fails if latency exceeds specified ceilings.
"""

import asyncio
import statistics
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from quantgambit.core.clock import SimClock
from quantgambit.core.book.types import OrderBook, Level
from quantgambit.sim.sim_exchange import SimExchange, SimExchangeConfig


@dataclass
class LatencyCeiling:
    """Latency ceiling specification."""
    
    p50_ms: float = 10.0
    p95_ms: float = 30.0
    p99_ms: float = 50.0


@dataclass
class PerfResult:
    """Performance test result."""
    
    name: str
    iterations: int
    duration_s: float
    throughput_ops_s: float
    
    # Latencies in milliseconds
    p50_ms: float
    p95_ms: float
    p99_ms: float
    min_ms: float
    max_ms: float
    mean_ms: float
    
    # Pass/fail
    passed: bool
    failure_reason: Optional[str] = None
    
    def summary(self) -> str:
        """Generate summary string."""
        status = "✓ PASS" if self.passed else "✗ FAIL"
        return (
            f"{self.name}: {status}\n"
            f"  Iterations: {self.iterations:,}\n"
            f"  Duration: {self.duration_s:.2f}s\n"
            f"  Throughput: {self.throughput_ops_s:,.0f} ops/s\n"
            f"  Latency p50: {self.p50_ms:.2f}ms\n"
            f"  Latency p95: {self.p95_ms:.2f}ms\n"
            f"  Latency p99: {self.p99_ms:.2f}ms\n"
            f"  Latency min: {self.min_ms:.2f}ms\n"
            f"  Latency max: {self.max_ms:.2f}ms"
        )


class PerfHarness:
    """
    Performance testing harness.
    
    Runs functions repeatedly and measures latency distribution.
    
    Usage:
        harness = PerfHarness()
        
        result = harness.run_sync(
            name="book_update",
            func=process_book_update,
            iterations=10000,
            ceiling=LatencyCeiling(p50_ms=1.0, p95_ms=5.0, p99_ms=10.0),
        )
        
        print(result.summary())
    """
    
    def __init__(self, warmup_iterations: int = 100):
        """Initialize harness."""
        self._warmup_iterations = warmup_iterations
        self._results: List[PerfResult] = []
    
    def run_sync(
        self,
        name: str,
        func: Callable[[], Any],
        iterations: int,
        ceiling: Optional[LatencyCeiling] = None,
        setup: Optional[Callable[[], None]] = None,
        teardown: Optional[Callable[[], None]] = None,
    ) -> PerfResult:
        """
        Run synchronous performance test.
        
        Args:
            name: Test name
            func: Function to benchmark
            iterations: Number of iterations
            ceiling: Optional latency ceiling
            setup: Optional setup function
            teardown: Optional teardown function
            
        Returns:
            PerfResult with metrics
        """
        # Setup
        if setup:
            setup()
        
        # Warmup
        for _ in range(self._warmup_iterations):
            func()
        
        # Measure
        latencies_ns: List[float] = []
        start_time = time.monotonic()
        
        for _ in range(iterations):
            iter_start = time.perf_counter_ns()
            func()
            iter_end = time.perf_counter_ns()
            latencies_ns.append(iter_end - iter_start)
        
        end_time = time.monotonic()
        duration_s = end_time - start_time
        
        # Teardown
        if teardown:
            teardown()
        
        # Calculate metrics
        latencies_ms = [ns / 1_000_000 for ns in latencies_ns]
        latencies_ms.sort()
        
        p50 = self._percentile(latencies_ms, 50)
        p95 = self._percentile(latencies_ms, 95)
        p99 = self._percentile(latencies_ms, 99)
        
        # Check ceiling
        passed = True
        failure_reason = None
        if ceiling:
            if p50 > ceiling.p50_ms:
                passed = False
                failure_reason = f"p50 {p50:.2f}ms > ceiling {ceiling.p50_ms}ms"
            elif p95 > ceiling.p95_ms:
                passed = False
                failure_reason = f"p95 {p95:.2f}ms > ceiling {ceiling.p95_ms}ms"
            elif p99 > ceiling.p99_ms:
                passed = False
                failure_reason = f"p99 {p99:.2f}ms > ceiling {ceiling.p99_ms}ms"
        
        result = PerfResult(
            name=name,
            iterations=iterations,
            duration_s=duration_s,
            throughput_ops_s=iterations / duration_s,
            p50_ms=p50,
            p95_ms=p95,
            p99_ms=p99,
            min_ms=min(latencies_ms),
            max_ms=max(latencies_ms),
            mean_ms=statistics.mean(latencies_ms),
            passed=passed,
            failure_reason=failure_reason,
        )
        
        self._results.append(result)
        return result
    
    async def run_async(
        self,
        name: str,
        func: Callable[[], Any],
        iterations: int,
        ceiling: Optional[LatencyCeiling] = None,
        setup: Optional[Callable[[], None]] = None,
        teardown: Optional[Callable[[], None]] = None,
    ) -> PerfResult:
        """
        Run async performance test.
        
        Args:
            name: Test name
            func: Async function to benchmark
            iterations: Number of iterations
            ceiling: Optional latency ceiling
            setup: Optional setup function
            teardown: Optional teardown function
            
        Returns:
            PerfResult with metrics
        """
        # Setup
        if setup:
            setup()
        
        # Warmup
        for _ in range(self._warmup_iterations):
            await func()
        
        # Measure
        latencies_ns: List[float] = []
        start_time = time.monotonic()
        
        for _ in range(iterations):
            iter_start = time.perf_counter_ns()
            await func()
            iter_end = time.perf_counter_ns()
            latencies_ns.append(iter_end - iter_start)
        
        end_time = time.monotonic()
        duration_s = end_time - start_time
        
        # Teardown
        if teardown:
            teardown()
        
        # Calculate metrics
        latencies_ms = [ns / 1_000_000 for ns in latencies_ns]
        latencies_ms.sort()
        
        p50 = self._percentile(latencies_ms, 50)
        p95 = self._percentile(latencies_ms, 95)
        p99 = self._percentile(latencies_ms, 99)
        
        # Check ceiling
        passed = True
        failure_reason = None
        if ceiling:
            if p50 > ceiling.p50_ms:
                passed = False
                failure_reason = f"p50 {p50:.2f}ms > ceiling {ceiling.p50_ms}ms"
            elif p95 > ceiling.p95_ms:
                passed = False
                failure_reason = f"p95 {p95:.2f}ms > ceiling {ceiling.p95_ms}ms"
            elif p99 > ceiling.p99_ms:
                passed = False
                failure_reason = f"p99 {p99:.2f}ms > ceiling {ceiling.p99_ms}ms"
        
        result = PerfResult(
            name=name,
            iterations=iterations,
            duration_s=duration_s,
            throughput_ops_s=iterations / duration_s,
            p50_ms=p50,
            p95_ms=p95,
            p99_ms=p99,
            min_ms=min(latencies_ms),
            max_ms=max(latencies_ms),
            mean_ms=statistics.mean(latencies_ms),
            passed=passed,
            failure_reason=failure_reason,
        )
        
        self._results.append(result)
        return result
    
    def _percentile(self, sorted_data: List[float], p: float) -> float:
        """Calculate percentile from sorted data."""
        if not sorted_data:
            return 0.0
        idx = int(len(sorted_data) * p / 100)
        idx = min(idx, len(sorted_data) - 1)
        return sorted_data[idx]
    
    def summary(self) -> str:
        """Generate summary of all results."""
        lines = ["Performance Test Results", "=" * 60]
        
        passed = sum(1 for r in self._results if r.passed)
        failed = len(self._results) - passed
        
        for result in self._results:
            lines.append("")
            lines.append(result.summary())
        
        lines.append("")
        lines.append("=" * 60)
        lines.append(f"Total: {len(self._results)} tests, {passed} passed, {failed} failed")
        
        return "\n".join(lines)
    
    def all_passed(self) -> bool:
        """Check if all tests passed."""
        return all(r.passed for r in self._results)


def create_test_book(symbol: str = "BTCUSDT", mid: float = 100.0, spread_bps: float = 10.0) -> OrderBook:
    """Create a test order book."""
    half_spread = mid * (spread_bps / 10000) / 2
    bid = mid - half_spread
    ask = mid + half_spread
    
    return OrderBook(
        symbol=symbol,
        bids=[Level(price=bid - i * 0.01, size=10.0) for i in range(10)],
        asks=[Level(price=ask + i * 0.01, size=10.0) for i in range(10)],
        timestamp=time.time(),
        sequence_id=1,
    )


# Default latency ceilings for different operations
CEILINGS = {
    "tick_to_decision": LatencyCeiling(p50_ms=10.0, p95_ms=30.0, p99_ms=50.0),
    "feature_build": LatencyCeiling(p50_ms=2.0, p95_ms=5.0, p99_ms=10.0),
    "model_infer": LatencyCeiling(p50_ms=5.0, p95_ms=15.0, p99_ms=25.0),
    "book_update": LatencyCeiling(p50_ms=0.5, p95_ms=1.0, p99_ms=2.0),
    "risk_map": LatencyCeiling(p50_ms=1.0, p95_ms=3.0, p99_ms=5.0),
    "order_send": LatencyCeiling(p50_ms=50.0, p95_ms=100.0, p99_ms=200.0),
}


if __name__ == "__main__":
    # Example usage
    harness = PerfHarness()
    
    # Simple sync benchmark
    def noop():
        pass
    
    result = harness.run_sync(
        name="noop_baseline",
        func=noop,
        iterations=100000,
        ceiling=LatencyCeiling(p50_ms=0.01, p95_ms=0.1, p99_ms=1.0),
    )
    
    print(harness.summary())
