"""
Latency tracking and instrumentation.

Tracks latency for various operations with periodic percentile computation.
Designed to be called from the hot path with minimal overhead.

Key design decisions:
- O(1) recording (just append to deque)
- Periodic percentile computation (not per-tick)
- Configurable SLO thresholds
- Determinism-safe (uses injected Clock)
"""

from dataclasses import dataclass, field
from collections import deque
from typing import Optional, Dict, Any, List, Callable
import asyncio

from quantgambit.core.clock import Clock, get_clock


@dataclass
class LatencySLO:
    """
    Service Level Objective for latency.
    
    Attributes:
        operation: Operation name
        p50_ms: P50 threshold in milliseconds
        p95_ms: P95 threshold in milliseconds
        p99_ms: P99 threshold in milliseconds
    """
    
    operation: str
    p50_ms: float
    p95_ms: float
    p99_ms: float


@dataclass
class LatencyStats:
    """
    Computed latency statistics.
    
    Attributes:
        operation: Operation name
        count: Number of samples
        p50_ms: P50 latency
        p95_ms: P95 latency
        p99_ms: P99 latency
        min_ms: Minimum latency
        max_ms: Maximum latency
        mean_ms: Mean latency
        slo_breaches: Number of SLO breaches
    """
    
    operation: str
    count: int = 0
    p50_ms: float = 0.0
    p95_ms: float = 0.0
    p99_ms: float = 0.0
    min_ms: float = 0.0
    max_ms: float = 0.0
    mean_ms: float = 0.0
    slo_breaches: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "operation": self.operation,
            "count": self.count,
            "p50_ms": self.p50_ms,
            "p95_ms": self.p95_ms,
            "p99_ms": self.p99_ms,
            "min_ms": self.min_ms,
            "max_ms": self.max_ms,
            "mean_ms": self.mean_ms,
            "slo_breaches": self.slo_breaches,
        }


@dataclass
class LatencySnapshot:
    """
    Point-in-time snapshot of latency metrics for history storage.
    
    Used for time-series graphs in the dashboard.
    """
    timestamp: float  # Wall clock timestamp
    metrics: Dict[str, Dict[str, float]]  # {operation: {p50, p95, p99, count}}
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "metrics": self.metrics,
        }


# Callback type for SLO breach alerts
SLOBreachCallback = Callable[[str, float, float], None]


class LatencyTracker:
    """
    Track latency with periodic percentile computation.
    
    Usage:
        tracker = LatencyTracker(clock)
        
        # Record samples (O(1))
        tracker.record("tick_to_decision", 15.5)
        tracker.record("tick_to_decision", 18.2)
        
        # Get stats (computed periodically, not per-call)
        stats = tracker.get_stats("tick_to_decision")
        print(f"P95: {stats.p95_ms}ms")
    """
    
    def __init__(
        self,
        clock: Optional[Clock] = None,
        window_sec: float = 60.0,
        max_samples: int = 100000,
        compute_interval_sec: float = 5.0,
        history_max_size: int = 360,  # 6 hours at 1-minute intervals
        history_snapshot_interval_sec: float = 60.0,  # 1 minute
    ):
        """
        Initialize tracker.
        
        Args:
            clock: Clock for timestamps
            window_sec: Time window for samples
            max_samples: Maximum samples to keep per operation
            compute_interval_sec: How often to compute percentiles
            history_max_size: Max number of history snapshots to keep
            history_snapshot_interval_sec: How often to record history snapshots
        """
        self._clock = clock or get_clock()
        self._window_sec = window_sec
        self._max_samples = max_samples
        self._compute_interval_sec = compute_interval_sec
        
        # Samples: operation -> deque of (ts_mono, latency_ms)
        self._samples: Dict[str, deque] = {}
        
        # Cached stats (computed periodically)
        self._stats: Dict[str, LatencyStats] = {}
        
        # SLOs
        self._slos: Dict[str, LatencySLO] = {}
        
        # Breach callback
        self._on_breach: Optional[SLOBreachCallback] = None
        
        # Control
        self._running = False
        self._compute_task: Optional[asyncio.Task] = None
        
        # History for time-series graphs
        self._history: List[LatencySnapshot] = []
        self._history_max_size = history_max_size
        self._history_snapshot_interval_sec = history_snapshot_interval_sec
        self._last_snapshot_ts: float = 0.0
    
    def record(self, operation: str, latency_ms: float) -> None:
        """
        Record a latency sample.
        
        This is O(1) and safe to call from the hot path.
        
        Args:
            operation: Operation name
            latency_ms: Latency in milliseconds
        """
        if operation not in self._samples:
            self._samples[operation] = deque(maxlen=self._max_samples)
        
        ts = self._clock.now_mono()
        self._samples[operation].append((ts, latency_ms))
    
    def start_timer(self, operation: str) -> float:
        """
        Start a timer for an operation.
        
        Returns the start time to be passed to end_timer.
        
        Args:
            operation: Operation name (for documentation)
            
        Returns:
            Start time (monotonic)
        """
        return self._clock.now_mono()
    
    def end_timer(self, operation: str, start_time: float) -> float:
        """
        End a timer and record the latency.
        
        Args:
            operation: Operation name
            start_time: Start time from start_timer()
            
        Returns:
            Duration in milliseconds
        """
        duration_ms = (self._clock.now_mono() - start_time) * 1000
        self.record(operation, duration_ms)
        return duration_ms
    
    def record_duration(self, operation: str, start_mono: float) -> float:
        """
        Record duration since a start time.
        
        Args:
            operation: Operation name
            start_mono: Start monotonic time
            
        Returns:
            Duration in milliseconds
        """
        duration_ms = (self._clock.now_mono() - start_mono) * 1000
        self.record(operation, duration_ms)
        return duration_ms
    
    def set_slo(self, slo: LatencySLO) -> None:
        """Set SLO for an operation."""
        self._slos[slo.operation] = slo
    
    def set_breach_callback(self, callback: SLOBreachCallback) -> None:
        """Set callback for SLO breaches."""
        self._on_breach = callback
    
    def get_stats(self, operation: str) -> Optional[LatencyStats]:
        """
        Get cached stats for an operation.
        
        Returns cached stats computed by background task.
        Call compute_stats() manually if you need fresh stats.
        """
        return self._stats.get(operation)
    
    def get_all_stats(self) -> Dict[str, LatencyStats]:
        """Get all cached stats."""
        return dict(self._stats)
    
    def get_all_percentiles(self) -> Dict[str, Dict[str, float]]:
        """
        Get percentile summaries for all operations.
        
        Returns a simplified dict suitable for JSON serialization.
        
        Returns:
            Dict mapping operation names to percentile dicts
        """
        # Compute fresh stats for all operations
        self.compute_all_stats()
        
        result = {}
        for op, stats in self._stats.items():
            result[op] = {
                "count": stats.count,
                "p50_ms": stats.p50_ms,
                "p95_ms": stats.p95_ms,
                "p99_ms": stats.p99_ms,
                "min_ms": stats.min_ms,
                "max_ms": stats.max_ms,
            }
        return result
    
    def _maybe_record_history_snapshot(self) -> None:
        """
        Record a history snapshot if enough time has passed.
        
        Called during compute_all_stats to record time-series data.
        """
        now = self._clock.now()
        if now - self._last_snapshot_ts < self._history_snapshot_interval_sec:
            return
        
        self._last_snapshot_ts = now
        
        # Build metrics dict from current stats
        metrics = {}
        for op, stats in self._stats.items():
            metrics[op] = {
                "p50_ms": stats.p50_ms,
                "p95_ms": stats.p95_ms,
                "p99_ms": stats.p99_ms,
                "count": stats.count,
            }
        
        snapshot = LatencySnapshot(
            timestamp=now,
            metrics=metrics,
        )
        self._history.append(snapshot)
        
        # Trim old entries
        while len(self._history) > self._history_max_size:
            self._history.pop(0)
    
    def get_history(
        self,
        since_ts: float = 0,
        operation: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Get latency history for time-series graphs.
        
        Args:
            since_ts: Only return snapshots after this timestamp (Unix)
            operation: Filter by operation (None = all)
        
        Returns:
            List of snapshot dicts with timestamp and metrics
        """
        result = []
        for snapshot in self._history:
            if snapshot.timestamp < since_ts:
                continue
            
            if operation:
                # Filter to specific operation
                op_metrics = snapshot.metrics.get(operation, {})
                if op_metrics:
                    result.append({
                        "timestamp": snapshot.timestamp,
                        "metrics": {operation: op_metrics},
                    })
            else:
                result.append(snapshot.to_dict())
        
        return result
    
    def get_history_for_operation(
        self,
        operation: str,
        since_ts: float = 0,
    ) -> List[Dict[str, Any]]:
        """
        Get flattened history for a single operation.
        
        Convenient for charting - returns list of {timestamp, p50, p95, p99, count}
        
        Args:
            operation: Operation name
            since_ts: Only return snapshots after this timestamp
        
        Returns:
            List of {timestamp, p50_ms, p95_ms, p99_ms, count} dicts
        """
        result = []
        for snapshot in self._history:
            if snapshot.timestamp < since_ts:
                continue
            
            op_metrics = snapshot.metrics.get(operation)
            if op_metrics:
                result.append({
                    "timestamp": snapshot.timestamp,
                    "p50_ms": op_metrics.get("p50_ms", 0),
                    "p95_ms": op_metrics.get("p95_ms", 0),
                    "p99_ms": op_metrics.get("p99_ms", 0),
                    "count": op_metrics.get("count", 0),
                })
        
        return result
    
    def get_available_operations(self) -> List[str]:
        """Get list of all operations that have recorded samples."""
        return list(self._samples.keys())
    
    def compute_stats(self, operation: str) -> LatencyStats:
        """
        Compute stats for an operation.
        
        This sorts samples, so don't call per-tick.
        
        Args:
            operation: Operation name
            
        Returns:
            Computed LatencyStats
        """
        samples = self._samples.get(operation)
        if not samples:
            return LatencyStats(operation=operation)
        
        now = self._clock.now_mono()
        cutoff = now - self._window_sec
        
        # Filter to window and extract latencies
        latencies = sorted(
            lat for ts, lat in samples if ts >= cutoff
        )
        
        if not latencies:
            return LatencyStats(operation=operation)
        
        n = len(latencies)
        
        # Compute percentiles
        p50 = latencies[int(n * 0.50)]
        p95 = latencies[int(n * 0.95)]
        p99 = latencies[int(n * 0.99)]
        
        # Check SLO
        slo_breaches = 0
        slo = self._slos.get(operation)
        if slo:
            if p95 > slo.p95_ms:
                slo_breaches += 1
                if self._on_breach:
                    self._on_breach(operation, p95, slo.p95_ms)
        
        stats = LatencyStats(
            operation=operation,
            count=n,
            p50_ms=p50,
            p95_ms=p95,
            p99_ms=p99,
            min_ms=latencies[0],
            max_ms=latencies[-1],
            mean_ms=sum(latencies) / n,
            slo_breaches=slo_breaches,
        )
        
        self._stats[operation] = stats
        return stats
    
    def compute_all_stats(self) -> Dict[str, LatencyStats]:
        """Compute stats for all operations."""
        for operation in self._samples.keys():
            self.compute_stats(operation)
        
        # Record history snapshot for time-series graphs
        self._maybe_record_history_snapshot()
        
        return dict(self._stats)
    
    async def start_background_compute(self) -> None:
        """Start background task to compute stats periodically."""
        self._running = True
        self._compute_task = asyncio.create_task(self._compute_loop())
    
    async def stop_background_compute(self) -> None:
        """Stop background compute task."""
        self._running = False
        if self._compute_task:
            self._compute_task.cancel()
            try:
                await self._compute_task
            except asyncio.CancelledError:
                pass
    
    async def _compute_loop(self) -> None:
        """Background loop to compute stats."""
        while self._running:
            try:
                await self._clock.sleep(self._compute_interval_sec)
                self.compute_all_stats()
            except asyncio.CancelledError:
                break
    
    def clear(self, operation: Optional[str] = None) -> None:
        """
        Clear samples.
        
        Args:
            operation: Operation to clear (None = all)
        """
        if operation:
            self._samples.pop(operation, None)
            self._stats.pop(operation, None)
        else:
            self._samples.clear()
            self._stats.clear()


class LatencyContext:
    """
    Context manager for timing a block of code.
    
    Usage:
        tracker = LatencyTracker()
        
        with LatencyContext(tracker, "my_operation"):
            do_something()
    """
    
    def __init__(self, tracker: LatencyTracker, operation: str):
        self._tracker = tracker
        self._operation = operation
        self._start: float = 0.0
    
    def __enter__(self) -> "LatencyContext":
        self._start = self._tracker._clock.now_mono()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self._tracker.record_duration(self._operation, self._start)


# Default SLOs for common operations
DEFAULT_SLOS = [
    LatencySLO("tick_to_feature", p50_ms=5.0, p95_ms=15.0, p99_ms=30.0),
    LatencySLO("feature_to_decision", p50_ms=5.0, p95_ms=15.0, p99_ms=30.0),
    LatencySLO("decision_to_risk", p50_ms=2.0, p95_ms=5.0, p99_ms=10.0),
    LatencySLO("risk_to_execution", p50_ms=2.0, p95_ms=5.0, p99_ms=10.0),
    LatencySLO("tick_to_execution", p50_ms=20.0, p95_ms=50.0, p99_ms=100.0),
    LatencySLO("order_send_to_ack", p50_ms=50.0, p95_ms=100.0, p99_ms=200.0),
    LatencySLO("order_ack_to_fill", p50_ms=20.0, p95_ms=50.0, p99_ms=100.0),
]


def create_tracker_with_default_slos(clock: Optional[Clock] = None) -> LatencyTracker:
    """Create a tracker with default SLOs configured."""
    tracker = LatencyTracker(clock=clock)
    for slo in DEFAULT_SLOS:
        tracker.set_slo(slo)
    return tracker
