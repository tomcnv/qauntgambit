"""
Clock abstraction for deterministic time in tests and replay.

Core logic MUST NOT call time.time() / time.monotonic() / asyncio.sleep() directly.
Instead, inject a Clock instance and use its methods.

Production: WallClock (real time)
Tests/Sim/Replay: SimClock (deterministic, programmatic advance)
"""

from abc import ABC, abstractmethod
from typing import Optional, List, Tuple
import time as _time
import asyncio
import heapq


class Clock(ABC):
    """
    Abstract clock interface for deterministic time.
    
    All time-dependent code in core/ must use this interface,
    never raw time.time() or asyncio.sleep().
    """

    @abstractmethod
    def now_wall(self) -> float:
        """
        Wall clock time (epoch seconds).
        
        Use for timestamps that need to be human-readable or
        correlated with external systems.
        """
        pass

    @abstractmethod
    def now_mono(self) -> float:
        """
        Monotonic time for duration measurement.
        
        Use for latency tracking and elapsed time calculations.
        Guaranteed to never go backwards.
        """
        pass

    @abstractmethod
    async def sleep(self, seconds: float) -> None:
        """
        Sleep for the specified duration.
        
        In production, this is real sleep.
        In simulation, this registers a waiter that wakes on clock advance.
        """
        pass

    def now(self) -> float:
        """Alias for now_wall() for convenience."""
        return self.now_wall()


class WallClock(Clock):
    """
    Real wall clock for production use.
    
    Uses actual system time and real asyncio.sleep().
    """

    def __init__(self) -> None:
        # Capture the offset between wall and monotonic at init
        # This allows consistent relationship between the two
        self._mono_offset = _time.time() - _time.perf_counter()

    def now_wall(self) -> float:
        """Return current epoch time in seconds."""
        return _time.time()

    def now_mono(self) -> float:
        """Return monotonic time in seconds."""
        return _time.perf_counter()

    async def sleep(self, seconds: float) -> None:
        """Real async sleep."""
        if seconds > 0:
            await asyncio.sleep(seconds)


class SimClock(Clock):
    """
    Simulated clock for deterministic tests and replay.
    
    Time only advances when explicitly told to via advance() or set_time().
    Sleepers are woken deterministically when their wake time is reached.
    
    This enables:
    - Deterministic test execution (no timing flakiness)
    - Fast replay (no real waiting)
    - Reproducible scenarios
    
    Example:
        clock = SimClock(start_time=1704067200.0)  # 2024-01-01 00:00:00 UTC
        
        async def my_task():
            await clock.sleep(10.0)
            print("Woke up!")
        
        task = asyncio.create_task(my_task())
        await asyncio.sleep(0)  # Let task start
        
        clock.advance(10.0)  # This wakes the sleeper
        await asyncio.sleep(0)  # Let task complete
    """

    def __init__(self, start_time: float = 0.0, start_mono: float = 0.0) -> None:
        """
        Initialize simulated clock.
        
        Args:
            start_time: Initial wall clock time (epoch seconds)
            start_mono: Initial monotonic time (seconds)
        """
        self._wall = start_time
        self._mono = start_mono
        # Min-heap of (wake_mono, event) for sleeping tasks
        self._waiters: List[Tuple[float, asyncio.Event]] = []
        # Track total sleepers for debugging
        self._total_sleeps = 0
        self._total_wakes = 0

    def now_wall(self) -> float:
        """Return simulated wall clock time."""
        return self._wall

    def now_mono(self) -> float:
        """Return simulated monotonic time."""
        return self._mono

    async def sleep(self, seconds: float) -> None:
        """
        Register a sleep that wakes when clock advances past wake time.
        
        This is non-blocking in real time - it only blocks in simulated time.
        The sleeper wakes when advance() moves mono past the wake point.
        """
        if seconds <= 0:
            # Yield to event loop but don't actually wait
            await asyncio.sleep(0)
            return

        wake_at = self._mono + seconds
        event = asyncio.Event()
        
        # Use heapq for efficient wake ordering
        heapq.heappush(self._waiters, (wake_at, event))
        self._total_sleeps += 1
        
        await event.wait()
        self._total_wakes += 1

    def advance(self, delta: float) -> int:
        """
        Advance time by delta seconds and wake any sleepers.
        
        Args:
            delta: Seconds to advance (must be >= 0)
            
        Returns:
            Number of sleepers woken
            
        Raises:
            ValueError: If delta is negative
        """
        if delta < 0:
            raise ValueError(f"Cannot advance time backwards: {delta}")
        
        if delta == 0:
            return 0

        self._wall += delta
        self._mono += delta
        
        return self._wake_sleepers()

    def set_time(self, wall: float, mono: Optional[float] = None) -> int:
        """
        Jump to a specific time (for replay).
        
        Args:
            wall: New wall clock time (epoch seconds)
            mono: New monotonic time (if None, advances by same delta as wall)
            
        Returns:
            Number of sleepers woken
            
        Note:
            This can move time backwards for wall clock, but mono should
            generally only move forward to maintain monotonic guarantees.
        """
        if mono is None:
            # Advance mono by same delta as wall
            delta = wall - self._wall
            mono = self._mono + delta if delta > 0 else self._mono
        
        self._wall = wall
        old_mono = self._mono
        self._mono = mono
        
        # Only wake sleepers if mono advanced
        if mono > old_mono:
            return self._wake_sleepers()
        return 0

    def _wake_sleepers(self) -> int:
        """Wake all sleepers whose time has come."""
        woken = 0
        while self._waiters and self._waiters[0][0] <= self._mono:
            _, event = heapq.heappop(self._waiters)
            event.set()
            woken += 1
        return woken

    def pending_sleepers(self) -> int:
        """Return count of tasks waiting on sleep."""
        return len(self._waiters)

    def next_wake_time(self) -> Optional[float]:
        """Return mono time of next scheduled wake, or None if no sleepers."""
        if self._waiters:
            return self._waiters[0][0]
        return None

    def advance_to_next_wake(self) -> Tuple[float, int]:
        """
        Advance time to the next scheduled wake and wake those sleepers.
        
        Returns:
            Tuple of (delta_advanced, sleepers_woken)
            
        Raises:
            ValueError: If no sleepers are pending
        """
        if not self._waiters:
            raise ValueError("No pending sleepers to advance to")
        
        next_wake = self._waiters[0][0]
        delta = next_wake - self._mono
        woken = self.advance(delta)
        return (delta, woken)

    def stats(self) -> dict:
        """Return clock statistics for debugging."""
        return {
            "wall": self._wall,
            "mono": self._mono,
            "pending_sleepers": len(self._waiters),
            "total_sleeps": self._total_sleeps,
            "total_wakes": self._total_wakes,
        }


# Global clock instance - injected at startup
_clock: Clock = WallClock()


def get_clock() -> Clock:
    """Get the current global clock instance."""
    return _clock


def set_clock(clock: Clock) -> Clock:
    """
    Set the global clock instance.
    
    Args:
        clock: New clock to use globally
        
    Returns:
        The previous clock instance (for restoration in tests)
    """
    global _clock
    old = _clock
    _clock = clock
    return old


# Convenience functions that use the global clock
def now_wall() -> float:
    """Get current wall time from global clock."""
    return _clock.now_wall()


def now_mono() -> float:
    """Get current monotonic time from global clock."""
    return _clock.now_mono()


async def sleep(seconds: float) -> None:
    """Sleep using global clock."""
    await _clock.sleep(seconds)
