"""
Bounded side-channel publisher for non-critical events.

The side-channel is used to publish events to Redis/external systems
without blocking the hot path. It provides:

1. Bounded queue to prevent memory exhaustion under load
2. Coalescing for snapshot-type events (keep only latest per symbol)
3. Configurable drop policy when queue is full
4. Batch publishing for efficiency
5. Statistics for monitoring

CRITICAL: The hot path must NEVER await on side-channel operations.
All publishing is fire-and-forget with bounded backpressure.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Awaitable, Dict, List, Optional, Set
from collections import deque
import asyncio
import logging

from quantgambit.core.events import EventEnvelope, EventType
from quantgambit.core.clock import Clock, get_clock


logger = logging.getLogger(__name__)


class DropPolicy(str, Enum):
    """Policy for handling queue overflow."""
    
    DROP_OLDEST = "drop_oldest"  # Drop oldest events (FIFO overflow)
    DROP_NEWEST = "drop_newest"  # Drop incoming events when full


@dataclass
class SideChannelConfig:
    """
    Configuration for the side-channel publisher.
    
    Attributes:
        max_queue_size: Maximum events in the audit queue
        drop_policy: What to do when queue is full
        coalesce_snapshots: Keep only latest snapshot per symbol
        coalesce_event_types: Event types to coalesce (if coalesce_snapshots=True)
        publish_interval_ms: How often to batch-publish
        max_batch_size: Maximum events per publish batch
        enabled: Whether publishing is enabled
    """
    
    max_queue_size: int = 10000
    drop_policy: DropPolicy = DropPolicy.DROP_OLDEST
    coalesce_snapshots: bool = True
    coalesce_event_types: Set[str] = field(default_factory=lambda: {
        EventType.FEATURES.value,
        EventType.TICK.value,
    })
    publish_interval_ms: float = 100.0
    max_batch_size: int = 1000
    enabled: bool = True


@dataclass
class SideChannelStats:
    """Statistics for monitoring side-channel health."""
    
    enqueued: int = 0
    published: int = 0
    dropped: int = 0
    coalesced: int = 0
    publish_errors: int = 0
    current_queue_size: int = 0
    current_coalesce_size: int = 0
    
    def to_dict(self) -> dict:
        """Convert to dictionary for logging/metrics."""
        return {
            "enqueued": self.enqueued,
            "published": self.published,
            "dropped": self.dropped,
            "coalesced": self.coalesced,
            "publish_errors": self.publish_errors,
            "current_queue_size": self.current_queue_size,
            "current_coalesce_size": self.current_coalesce_size,
        }


# Type alias for the publisher callback
PublisherCallback = Callable[[List[EventEnvelope]], Awaitable[None]]


class SideChannelPublisher:
    """
    Bounded async publisher for non-critical events.
    
    This class provides a non-blocking way to publish events to external
    systems (Redis, etc.) without impacting the hot path latency.
    
    Key features:
    - Bounded queue prevents memory exhaustion
    - Coalescing reduces redundant snapshot publishes
    - Batch publishing improves throughput
    - Fire-and-forget enqueue (never blocks caller)
    
    Usage:
        async def publish_to_redis(events: List[EventEnvelope]) -> None:
            for event in events:
                await redis.xadd(stream, event.to_dict())
        
        publisher = SideChannelPublisher(
            config=SideChannelConfig(),
            publish_callback=publish_to_redis,
        )
        
        # Start background publisher
        asyncio.create_task(publisher.run())
        
        # Enqueue events (non-blocking)
        publisher.enqueue(event)
    """
    
    def __init__(
        self,
        config: SideChannelConfig,
        publish_callback: PublisherCallback,
        clock: Optional[Clock] = None,
    ):
        """
        Initialize the side-channel publisher.
        
        Args:
            config: Publisher configuration
            publish_callback: Async function to publish event batches
            clock: Clock instance (uses global if not provided)
        """
        self._config = config
        self._publisher = publish_callback
        self._clock = clock or get_clock()
        
        # Main event queue (bounded)
        self._queue: deque[EventEnvelope] = deque(maxlen=config.max_queue_size)
        
        # Coalescing map: (event_type, symbol) -> latest event
        self._coalesce_map: Dict[tuple[str, Optional[str]], EventEnvelope] = {}
        
        # Statistics
        self._stats = SideChannelStats()
        
        # Control
        self._running = False
        self._task: Optional[asyncio.Task] = None
    
    def publish(self, event: EventEnvelope) -> bool:
        """
        Publish an event (alias for enqueue).
        
        This is the HotPath-compatible interface.
        
        Args:
            event: Event to publish
            
        Returns:
            True if enqueued successfully
        """
        return self.enqueue(event)
    
    def enqueue(self, event: EventEnvelope) -> bool:
        """
        Enqueue an event for publishing.
        
        This is a non-blocking operation. If the queue is full,
        the event may be dropped according to the drop policy.
        
        Args:
            event: Event to publish
            
        Returns:
            True if event was enqueued, False if dropped
        """
        if not self._config.enabled:
            return False
        
        self._stats.enqueued += 1
        
        # Check if this event type should be coalesced
        if (
            self._config.coalesce_snapshots
            and event.type in self._config.coalesce_event_types
        ):
            key = (event.type, event.symbol)
            old = self._coalesce_map.get(key)
            self._coalesce_map[key] = event
            
            if old is not None:
                self._stats.coalesced += 1
            
            self._stats.current_coalesce_size = len(self._coalesce_map)
            return True
        
        # Check queue capacity
        if len(self._queue) >= self._config.max_queue_size:
            if self._config.drop_policy == DropPolicy.DROP_NEWEST:
                self._stats.dropped += 1
                return False
            else:
                # DROP_OLDEST: deque with maxlen handles this automatically
                # but we need to count the drop
                self._stats.dropped += 1
        
        self._queue.append(event)
        self._stats.current_queue_size = len(self._queue)
        return True
    
    def enqueue_batch(self, events: List[EventEnvelope]) -> int:
        """
        Enqueue multiple events.
        
        Args:
            events: Events to publish
            
        Returns:
            Number of events successfully enqueued
        """
        enqueued = 0
        for event in events:
            if self.enqueue(event):
                enqueued += 1
        return enqueued
    
    async def run(self) -> None:
        """
        Run the background publisher loop.
        
        This should be started as an asyncio task and runs until stop() is called.
        """
        self._running = True
        interval_sec = self._config.publish_interval_ms / 1000.0
        
        logger.info(
            "SideChannelPublisher started",
            extra={
                "interval_ms": self._config.publish_interval_ms,
                "max_queue": self._config.max_queue_size,
            },
        )
        
        while self._running:
            try:
                await self._clock.sleep(interval_sec)
                await self._publish_batch()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"SideChannelPublisher error: {e}", exc_info=True)
                self._stats.publish_errors += 1
        
        # Final flush on shutdown
        await self._publish_batch()
        logger.info("SideChannelPublisher stopped")
    
    async def _publish_batch(self) -> None:
        """Collect and publish a batch of events."""
        batch: List[EventEnvelope] = []
        
        # First, collect coalesced events
        if self._coalesce_map:
            batch.extend(self._coalesce_map.values())
            self._coalesce_map.clear()
            self._stats.current_coalesce_size = 0
        
        # Then, collect queued events up to batch limit
        remaining = self._config.max_batch_size - len(batch)
        while self._queue and remaining > 0:
            batch.append(self._queue.popleft())
            remaining -= 1
        
        self._stats.current_queue_size = len(self._queue)
        
        if not batch:
            return
        
        try:
            await self._publisher(batch)
            self._stats.published += len(batch)
        except Exception as e:
            logger.error(
                f"Failed to publish {len(batch)} events: {e}",
                exc_info=True,
            )
            self._stats.publish_errors += 1
            # Events are lost on publish failure - this is acceptable
            # for side-channel (non-critical) events
    
    def stop(self) -> None:
        """Signal the publisher to stop."""
        self._running = False
    
    async def stop_and_wait(self) -> None:
        """Stop the publisher and wait for it to finish."""
        self.stop()
        if self._task:
            await self._task
    
    def start_background(self) -> asyncio.Task:
        """
        Start the publisher as a background task.
        
        Returns:
            The asyncio Task running the publisher
        """
        self._task = asyncio.create_task(self.run())
        return self._task
    
    def get_stats(self) -> SideChannelStats:
        """Get current statistics."""
        return self._stats
    
    def reset_stats(self) -> None:
        """Reset statistics counters."""
        self._stats = SideChannelStats()
        self._stats.current_queue_size = len(self._queue)
        self._stats.current_coalesce_size = len(self._coalesce_map)
    
    @property
    def is_running(self) -> bool:
        """Check if the publisher is running."""
        return self._running
    
    @property
    def queue_size(self) -> int:
        """Current number of events in the queue."""
        return len(self._queue)
    
    @property
    def coalesce_size(self) -> int:
        """Current number of coalesced events pending."""
        return len(self._coalesce_map)


class NullSideChannel(SideChannelPublisher):
    """
    No-op side-channel for testing or when publishing is disabled.
    
    All events are silently discarded.
    """
    
    def __init__(self):
        """Initialize with a no-op publisher."""
        async def noop_publisher(events: List[EventEnvelope]) -> None:
            pass
        
        super().__init__(
            config=SideChannelConfig(enabled=False),
            publish_callback=noop_publisher,
        )
    
    def enqueue(self, event: EventEnvelope) -> bool:
        """Discard event."""
        return False
    
    def publish(self, event: EventEnvelope) -> bool:
        """Alias for enqueue (HotPath compatibility)."""
        return self.enqueue(event)
    
    async def run(self) -> None:
        """No-op."""
        pass


class BufferingSideChannel(SideChannelPublisher):
    """
    Side-channel that buffers events in memory for testing.
    
    Events are stored in a list for later inspection.
    """
    
    def __init__(self, config: Optional[SideChannelConfig] = None):
        """Initialize with an in-memory buffer."""
        self._buffer: List[EventEnvelope] = []
        
        async def buffer_publisher(events: List[EventEnvelope]) -> None:
            self._buffer.extend(events)
        
        super().__init__(
            config=config or SideChannelConfig(),
            publish_callback=buffer_publisher,
        )
    
    def get_buffer(self) -> List[EventEnvelope]:
        """Get all buffered events."""
        return list(self._buffer)
    
    def clear_buffer(self) -> None:
        """Clear the buffer."""
        self._buffer.clear()
    
    def get_events_by_type(self, event_type: EventType | str) -> List[EventEnvelope]:
        """Get buffered events of a specific type."""
        type_str = event_type.value if isinstance(event_type, EventType) else event_type
        return [e for e in self._buffer if e.type == type_str]
    
    def get_events_for_symbol(self, symbol: str) -> List[EventEnvelope]:
        """Get buffered events for a specific symbol."""
        return [e for e in self._buffer if e.symbol == symbol]
