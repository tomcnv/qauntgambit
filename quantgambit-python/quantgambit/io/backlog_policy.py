"""
Backlog policy for MDS streams with tiered management.

Provides:
1. Per-stream backlog tiers (soft/hard) with configurable thresholds
2. Safe trimming with post-trim resync to maintain consistency
3. Prioritization (trades > orderbook) under load
4. Protection for exit-relevant data (never trim critical signals)
5. Metrics for monitoring backlog health

CRITICAL: After any trim/compact operation, a resync MUST be triggered
to ensure downstream consumers have consistent state.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Dict, List, Callable, Awaitable
import logging

logger = logging.getLogger(__name__)


class BacklogTier(str, Enum):
    """Backlog tier indicating severity of backlog."""
    
    NORMAL = "normal"       # Backlog within acceptable limits
    SOFT = "soft"           # Elevated backlog - warn, reduce size, no drops
    HARD = "hard"           # Critical backlog - trim/compact with resync


class StreamType(str, Enum):
    """Type of data stream for differentiated handling."""
    
    TRADES = "trades"           # Trade stream - highest priority
    ORDERBOOK = "orderbook"     # Orderbook stream - can compact to top-N
    MARKET_DATA = "market_data" # Combined market data stream
    FEATURES = "features"       # Feature stream
    DECISIONS = "decisions"     # Decision stream


@dataclass
class StreamBacklogConfig:
    """
    Configuration for a single stream's backlog policy.
    
    Attributes:
        stream_type: Type of stream for differentiated handling
        soft_threshold: Depth at which to enter soft tier (warn, reduce)
        hard_threshold: Depth at which to enter hard tier (trim/compact)
        max_depth: Absolute maximum depth before aggressive trimming
        top_n_levels: For orderbook, keep top N levels when compacting
        trim_batch_size: How many entries to trim at once
        min_retain_sec: Minimum age of entries to retain (protect recent)
        protect_exit_signals: Never trim entries with exit-relevant data
        resync_after_trim: Trigger resync after any trim operation
    """
    
    stream_type: StreamType = StreamType.MARKET_DATA
    soft_threshold: int = 5000      # Enter soft tier
    hard_threshold: int = 15000     # Enter hard tier
    max_depth: int = 50000          # Absolute max
    top_n_levels: int = 20          # For orderbook compaction
    trim_batch_size: int = 1000     # Entries to trim per batch
    min_retain_sec: float = 5.0     # Protect entries newer than this
    protect_exit_signals: bool = True
    resync_after_trim: bool = True


@dataclass
class BacklogPolicyConfig:
    """
    Global backlog policy configuration.
    
    Attributes:
        streams: Per-stream configurations
        check_interval_sec: How often to check backlog levels
        lag_soft_threshold: Consumer lag (entries) for soft tier
        lag_hard_threshold: Consumer lag (entries) for hard tier
        enable_compaction: Allow orderbook compaction
        enable_trimming: Allow oldest entry trimming
    """
    
    streams: Dict[str, StreamBacklogConfig] = field(default_factory=dict)
    check_interval_sec: float = 1.0
    lag_soft_threshold: int = 1000   # Consumer lag for soft tier
    lag_hard_threshold: int = 5000   # Consumer lag for hard tier
    enable_compaction: bool = True
    enable_trimming: bool = True
    
    def __post_init__(self):
        # Set defaults for common streams if not provided
        defaults = {
            "events:market_data": StreamBacklogConfig(
                stream_type=StreamType.MARKET_DATA,
                soft_threshold=10000,
                hard_threshold=30000,
                max_depth=50000,
            ),
            "events:trades": StreamBacklogConfig(
                stream_type=StreamType.TRADES,
                soft_threshold=5000,
                hard_threshold=15000,
                max_depth=30000,
                protect_exit_signals=True,  # Trades are critical for exits
            ),
            "events:orderbook_feed": StreamBacklogConfig(
                stream_type=StreamType.ORDERBOOK,
                soft_threshold=5000,
                hard_threshold=15000,
                max_depth=30000,
                top_n_levels=20,
            ),
            "events:features": StreamBacklogConfig(
                stream_type=StreamType.FEATURES,
                soft_threshold=10000,
                hard_threshold=30000,
                max_depth=50000,
            ),
            "events:decisions": StreamBacklogConfig(
                stream_type=StreamType.DECISIONS,
                soft_threshold=2000,
                hard_threshold=5000,
                max_depth=10000,
            ),
        }
        for stream, cfg in defaults.items():
            if stream not in self.streams:
                self.streams[stream] = cfg


@dataclass
class BacklogState:
    """Current state of a stream's backlog."""
    
    stream_name: str
    depth: int = 0
    consumer_lag: int = 0
    tier: BacklogTier = BacklogTier.NORMAL
    last_trim_ts: float = 0.0
    trim_count: int = 0
    compact_count: int = 0
    resync_count: int = 0
    entries_trimmed: int = 0
    
    def to_dict(self) -> dict:
        """Convert to dictionary for metrics."""
        return {
            "stream": self.stream_name,
            "depth": self.depth,
            "consumer_lag": self.consumer_lag,
            "tier": self.tier.value,
            "last_trim_ts": self.last_trim_ts,
            "trim_count": self.trim_count,
            "compact_count": self.compact_count,
            "resync_count": self.resync_count,
            "entries_trimmed": self.entries_trimmed,
        }


@dataclass
class BacklogMetrics:
    """Aggregated backlog metrics across all streams."""
    
    streams: Dict[str, BacklogState] = field(default_factory=dict)
    overall_tier: BacklogTier = BacklogTier.NORMAL
    total_depth: int = 0
    total_lag: int = 0
    total_trimmed: int = 0
    total_compacted: int = 0
    total_resyncs: int = 0
    last_check_ts: float = 0.0
    
    def to_dict(self) -> dict:
        """Convert to dictionary for health reporting."""
        return {
            "overall_tier": self.overall_tier.value,
            "total_depth": self.total_depth,
            "total_lag": self.total_lag,
            "total_trimmed": self.total_trimmed,
            "total_compacted": self.total_compacted,
            "total_resyncs": self.total_resyncs,
            "last_check_ts": self.last_check_ts,
            "streams": {k: v.to_dict() for k, v in self.streams.items()},
        }


# Type aliases for callbacks
TrimCallback = Callable[[str, int], Awaitable[int]]  # stream, count -> trimmed
ResyncCallback = Callable[[str], Awaitable[None]]    # stream -> None
CompactCallback = Callable[[str, int], Awaitable[int]]  # stream, top_n -> compacted


class BacklogPolicy:
    """
    Manages backlog across multiple streams with tiered policies.
    
    Key responsibilities:
    1. Monitor stream depths and consumer lag
    2. Determine backlog tier based on thresholds
    3. Execute trim/compact operations when needed
    4. Trigger resync after any data modification
    5. Report metrics for observability
    
    Usage:
        policy = BacklogPolicy(
            config=BacklogPolicyConfig(),
            trim_callback=redis_trim,
            resync_callback=request_snapshot,
            compact_callback=compact_orderbook,
        )
        
        # In health loop
        metrics = await policy.check_and_enforce(stream_depths, consumer_lags)
    """
    
    def __init__(
        self,
        config: BacklogPolicyConfig,
        trim_callback: Optional[TrimCallback] = None,
        resync_callback: Optional[ResyncCallback] = None,
        compact_callback: Optional[CompactCallback] = None,
    ):
        """
        Initialize backlog policy.
        
        Args:
            config: Policy configuration
            trim_callback: Async function to trim oldest entries
            resync_callback: Async function to trigger resync/snapshot
            compact_callback: Async function to compact orderbook to top-N
        """
        self._config = config
        self._trim_callback = trim_callback
        self._resync_callback = resync_callback
        self._compact_callback = compact_callback
        
        # State tracking
        self._states: Dict[str, BacklogState] = {}
        self._metrics = BacklogMetrics()
        self._last_check = 0.0
    
    def _get_stream_config(self, stream_name: str) -> StreamBacklogConfig:
        """Get config for a stream, with fallback to defaults."""
        # Check exact match first
        if stream_name in self._config.streams:
            return self._config.streams[stream_name]
        
        # Check prefix match (e.g., "events:market_data:bybit" -> "events:market_data")
        for prefix, cfg in self._config.streams.items():
            if stream_name.startswith(prefix):
                return cfg
        
        # Default config
        return StreamBacklogConfig()
    
    def _get_state(self, stream_name: str) -> BacklogState:
        """Get or create state for a stream."""
        if stream_name not in self._states:
            self._states[stream_name] = BacklogState(stream_name=stream_name)
        return self._states[stream_name]
    
    def _compute_tier(
        self,
        depth: int,
        lag: int,
        cfg: StreamBacklogConfig,
    ) -> BacklogTier:
        """
        Compute backlog tier based on depth and lag.
        
        Uses the more severe of depth-based or lag-based tier.
        """
        # Depth-based tier
        if depth >= cfg.hard_threshold:
            depth_tier = BacklogTier.HARD
        elif depth >= cfg.soft_threshold:
            depth_tier = BacklogTier.SOFT
        else:
            depth_tier = BacklogTier.NORMAL
        
        # Lag-based tier
        if lag >= self._config.lag_hard_threshold:
            lag_tier = BacklogTier.HARD
        elif lag >= self._config.lag_soft_threshold:
            lag_tier = BacklogTier.SOFT
        else:
            lag_tier = BacklogTier.NORMAL
        
        # Return the more severe tier
        tier_order = [BacklogTier.NORMAL, BacklogTier.SOFT, BacklogTier.HARD]
        return max(depth_tier, lag_tier, key=lambda t: tier_order.index(t))
    
    async def check_and_enforce(
        self,
        stream_depths: Dict[str, int],
        consumer_lags: Optional[Dict[str, int]] = None,
    ) -> BacklogMetrics:
        """
        Check backlog levels and enforce policy.
        
        Args:
            stream_depths: Current depth of each stream
            consumer_lags: Current consumer lag for each stream (optional)
            
        Returns:
            Updated backlog metrics
        """
        now = time.time()
        consumer_lags = consumer_lags or {}
        
        # Update state for each stream
        overall_tier = BacklogTier.NORMAL
        total_depth = 0
        total_lag = 0
        
        for stream_name, depth in stream_depths.items():
            cfg = self._get_stream_config(stream_name)
            state = self._get_state(stream_name)
            lag = consumer_lags.get(stream_name, 0)
            
            # Update state
            state.depth = depth
            state.consumer_lag = lag
            state.tier = self._compute_tier(depth, lag, cfg)
            
            total_depth += depth
            total_lag += lag
            
            # Track overall tier (most severe)
            if state.tier == BacklogTier.HARD:
                overall_tier = BacklogTier.HARD
            elif state.tier == BacklogTier.SOFT and overall_tier != BacklogTier.HARD:
                overall_tier = BacklogTier.SOFT
            
            # Enforce policy based on tier
            if state.tier == BacklogTier.HARD:
                await self._enforce_hard_tier(stream_name, state, cfg)
            elif state.tier == BacklogTier.SOFT:
                await self._enforce_soft_tier(stream_name, state, cfg)
        
        # Update metrics
        self._metrics.streams = dict(self._states)
        self._metrics.overall_tier = overall_tier
        self._metrics.total_depth = total_depth
        self._metrics.total_lag = total_lag
        self._metrics.last_check_ts = now
        self._last_check = now
        
        return self._metrics
    
    async def _enforce_soft_tier(
        self,
        stream_name: str,
        state: BacklogState,
        cfg: StreamBacklogConfig,
    ) -> None:
        """
        Enforce soft tier policy.
        
        Actions:
        - Log warning
        - No trimming (exits must be allowed)
        - Signal to reduce position sizes
        """
        logger.warning(
            f"Backlog soft tier: {stream_name}",
            extra={
                "stream": stream_name,
                "depth": state.depth,
                "lag": state.consumer_lag,
                "soft_threshold": cfg.soft_threshold,
            },
        )
    
    async def _enforce_hard_tier(
        self,
        stream_name: str,
        state: BacklogState,
        cfg: StreamBacklogConfig,
    ) -> None:
        """
        Enforce hard tier policy.
        
        Actions:
        - Trim oldest entries (if enabled and not protecting exits)
        - Compact orderbook to top-N (if orderbook stream)
        - Trigger resync after any modification
        """
        trimmed = 0
        compacted = 0
        needs_resync = False
        
        # Determine action based on stream type
        if cfg.stream_type == StreamType.ORDERBOOK and self._config.enable_compaction:
            # Compact orderbook to top-N levels
            if self._compact_callback:
                try:
                    compacted = await self._compact_callback(stream_name, cfg.top_n_levels)
                    state.compact_count += 1
                    self._metrics.total_compacted += compacted
                    needs_resync = True
                    logger.info(
                        f"Backlog compacted: {stream_name}",
                        extra={
                            "stream": stream_name,
                            "compacted": compacted,
                            "top_n": cfg.top_n_levels,
                        },
                    )
                except Exception as e:
                    logger.error(f"Compact failed for {stream_name}: {e}")
        
        elif cfg.stream_type == StreamType.TRADES:
            # NEVER trim trades - they're critical for exits
            # Only log warning
            logger.warning(
                f"Backlog hard tier for trades (no trim): {stream_name}",
                extra={
                    "stream": stream_name,
                    "depth": state.depth,
                    "lag": state.consumer_lag,
                },
            )
        
        elif self._config.enable_trimming and not cfg.protect_exit_signals:
            # Trim oldest entries
            if self._trim_callback:
                try:
                    # Calculate how much to trim to get below soft threshold
                    excess = state.depth - cfg.soft_threshold
                    to_trim = min(excess, cfg.trim_batch_size)
                    
                    if to_trim > 0:
                        trimmed = await self._trim_callback(stream_name, to_trim)
                        state.trim_count += 1
                        state.entries_trimmed += trimmed
                        state.last_trim_ts = time.time()
                        self._metrics.total_trimmed += trimmed
                        needs_resync = True
                        logger.info(
                            f"Backlog trimmed: {stream_name}",
                            extra={
                                "stream": stream_name,
                                "trimmed": trimmed,
                                "requested": to_trim,
                            },
                        )
                except Exception as e:
                    logger.error(f"Trim failed for {stream_name}: {e}")
        
        # Trigger resync after any modification
        if needs_resync and cfg.resync_after_trim and self._resync_callback:
            try:
                await self._resync_callback(stream_name)
                state.resync_count += 1
                self._metrics.total_resyncs += 1
                logger.info(f"Backlog resync triggered: {stream_name}")
            except Exception as e:
                logger.error(f"Resync failed for {stream_name}: {e}")
    
    def get_metrics(self) -> BacklogMetrics:
        """Get current backlog metrics."""
        return self._metrics
    
    def get_stream_state(self, stream_name: str) -> Optional[BacklogState]:
        """Get state for a specific stream."""
        return self._states.get(stream_name)
    
    def get_overall_tier(self) -> BacklogTier:
        """Get the overall (most severe) backlog tier."""
        return self._metrics.overall_tier
    
    def should_reduce_size(self) -> bool:
        """Check if position sizes should be reduced due to backlog."""
        return self._metrics.overall_tier in (BacklogTier.SOFT, BacklogTier.HARD)
    
    def should_block_entries(self) -> bool:
        """Check if new entries should be blocked due to backlog."""
        return self._metrics.overall_tier == BacklogTier.HARD
    
    def reset_metrics(self) -> None:
        """Reset accumulated metrics (keep state)."""
        self._metrics = BacklogMetrics()
        for state in self._states.values():
            state.trim_count = 0
            state.compact_count = 0
            state.resync_count = 0
            state.entries_trimmed = 0
