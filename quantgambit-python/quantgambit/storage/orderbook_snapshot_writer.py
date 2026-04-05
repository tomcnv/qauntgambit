"""Orderbook snapshot writer for persisting orderbook state to TimescaleDB.

This module provides the OrderbookSnapshotWriter class that captures orderbook
snapshots at configurable intervals and persists them asynchronously to TimescaleDB.

Feature: live-orderbook-data-storage
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional, TYPE_CHECKING

from quantgambit.market.derived_metrics import (
    calculate_depth_usd,
    calculate_orderbook_imbalance,
    calculate_spread_bps,
)
from quantgambit.market.orderbooks import OrderbookState
from quantgambit.storage.persistence import (
    OrderbookSnapshot,
    OrderbookSnapshotWriterConfig,
)

if TYPE_CHECKING:
    import asyncpg

logger = logging.getLogger(__name__)


class OrderbookSnapshotWriter:
    """Persists orderbook snapshots to TimescaleDB asynchronously.
    
    This class captures orderbook state at configurable intervals and persists
    snapshots to TimescaleDB. It uses interval throttling to avoid capturing
    too frequently, and buffers snapshots for batch writes.
    
    The writer is designed to be non-blocking - all database operations happen
    asynchronously in the background to avoid impacting live trading latency.
    
    Attributes:
        pool: The asyncpg connection pool for database operations.
        config: Configuration for snapshot capture and persistence.
    
    Example:
        >>> writer = OrderbookSnapshotWriter(pool, config)
        >>> await writer.start_background_flush()
        >>> # In the orderbook processing loop:
        >>> await writer.maybe_capture(symbol, exchange, state, timestamp, seq)
        >>> # On shutdown:
        >>> await writer.stop()
    
    Validates: Requirements 1.1, 1.3, 1.4
    """
    
    def __init__(
        self,
        pool: "asyncpg.Pool",
        config: Optional[OrderbookSnapshotWriterConfig] = None,
        tenant_id: str = "default",
        bot_id: str = "default",
    ) -> None:
        """Initialize the OrderbookSnapshotWriter.
        
        Args:
            pool: The asyncpg connection pool for database operations.
            config: Configuration for snapshot capture and persistence.
                If None, uses default configuration.
        """
        self.pool = pool
        self.config = config or OrderbookSnapshotWriterConfig()
        self.tenant_id = str(tenant_id or "default")
        self.bot_id = str(bot_id or "default")
        
        # Track last capture time per symbol for interval throttling
        # Key: (symbol, exchange), Value: timestamp (float, seconds since epoch)
        self._last_capture_time: Dict[tuple[str, str], float] = {}
        
        # Buffer for batch writes
        self._buffer: List[OrderbookSnapshot] = []
        self._buffer_lock = asyncio.Lock()
        
        # Background flush task
        self._flush_task: Optional[asyncio.Task] = None
        self._running = False
    
    async def maybe_capture(
        self,
        symbol: str,
        exchange: str,
        state: OrderbookState,
        timestamp: float,
        seq: int,
        tenant_id: Optional[str] = None,
        bot_id: Optional[str] = None,
    ) -> None:
        """Capture snapshot if interval has elapsed. Non-blocking.
        
        This method checks if enough time has passed since the last capture
        for this symbol/exchange pair. If so, it creates a snapshot with
        derived metrics and adds it to the buffer for batch persistence.
        
        The method is non-blocking - it does not wait for database writes.
        Snapshots are buffered and flushed periodically by the background task.
        
        Args:
            symbol: The trading pair symbol (e.g., "BTC/USDT").
            exchange: The exchange identifier (e.g., "binance").
            state: The current orderbook state to capture.
            timestamp: The timestamp of the orderbook update (seconds since epoch).
            seq: The sequence number from the exchange orderbook feed.
        
        Validates: Requirements 1.1, 1.3
        """
        if not self.config.enabled:
            return
        
        # Check if orderbook state is valid
        if not state.valid:
            return
        
        # Check interval throttling
        key = (symbol, exchange)
        last_capture = self._last_capture_time.get(key, 0.0)
        
        if timestamp - last_capture < self.config.snapshot_interval_sec:
            # Interval has not elapsed, skip capture
            return
        
        # Update last capture time
        self._last_capture_time[key] = timestamp
        
        # Get orderbook levels (configurable depth; trimming saves a lot of space)
        depth = int(self.config.max_depth_levels) if int(self.config.max_depth_levels) > 0 else 20
        bids, asks = state.as_levels(depth=depth)
        
        # Calculate derived metrics
        best_bid = bids[0][0] if bids else 0.0
        best_ask = asks[0][0] if asks else 0.0
        
        spread_bps = calculate_spread_bps(best_bid, best_ask)
        bid_depth_usd = calculate_depth_usd(bids)
        ask_depth_usd = calculate_depth_usd(asks)
        orderbook_imbalance = calculate_orderbook_imbalance(bid_depth_usd, ask_depth_usd)
        
        # Create snapshot
        snapshot = OrderbookSnapshot(
            symbol=symbol,
            exchange=exchange,
            timestamp=datetime.fromtimestamp(timestamp, tz=timezone.utc),
            seq=seq,
            bids=bids,
            asks=asks,
            spread_bps=spread_bps,
            bid_depth_usd=bid_depth_usd,
            ask_depth_usd=ask_depth_usd,
            orderbook_imbalance=orderbook_imbalance,
            tenant_id=str(tenant_id or self.tenant_id or "default"),
            bot_id=str(bot_id or self.bot_id or "default"),
        )
        
        # Add to buffer. If batch_size is reached, clear the buffer immediately
        # (within the lock) and schedule the DB insert in the background.
        # This avoids relying on background task scheduling to make buffer state
        # consistent (unit tests and production backpressure both benefit).
        snapshots_to_flush: Optional[List[OrderbookSnapshot]] = None
        async with self._buffer_lock:
            self._buffer.append(snapshot)

            if len(self._buffer) >= self.config.batch_size:
                snapshots_to_flush = self._buffer[:]
                self._buffer.clear()

        if snapshots_to_flush:
            asyncio.create_task(self._batch_insert_with_retry(snapshots_to_flush))
    
    async def flush(self) -> int:
        """Flush buffered snapshots to database. Returns count written.
        
        This method flushes all buffered snapshots to the database using
        a batch insert. It handles retries with exponential backoff on
        failure.
        
        Returns:
            The number of snapshots written to the database.
        
        Validates: Requirements 1.4, 1.6
        """
        return await self._flush_buffer()
    
    async def _flush_buffer(self) -> int:
        """Internal method to flush the buffer to the database."""
        async with self._buffer_lock:
            if not self._buffer:
                return 0
            
            # Take all snapshots from buffer
            snapshots = self._buffer[:]
            self._buffer.clear()
        
        # Perform batch insert with retry
        return await self._batch_insert_with_retry(snapshots)
    
    async def _batch_insert_with_retry(self, snapshots: List[OrderbookSnapshot]) -> int:
        """Insert snapshots with exponential backoff retry on failure."""
        if not snapshots:
            return 0
        
        for attempt in range(self.config.retry_max_attempts):
            try:
                await self._batch_insert(snapshots)
                return len(snapshots)
            except Exception as e:
                delay = self.config.retry_base_delay_sec * (2 ** attempt)
                logger.warning(
                    f"Snapshot batch insert failed (attempt {attempt + 1}/{self.config.retry_max_attempts}): {e}. "
                    f"Retrying in {delay:.2f}s"
                )
                if attempt < self.config.retry_max_attempts - 1:
                    await asyncio.sleep(delay)
        
        # All retries exhausted, log error and drop the batch
        logger.error(
            f"Failed to insert {len(snapshots)} snapshots after {self.config.retry_max_attempts} attempts. "
            "Dropping batch to protect live trading."
        )
        return 0
    
    async def _batch_insert(self, snapshots: List[OrderbookSnapshot]) -> None:
        """Perform the actual batch insert to the database."""
        if not snapshots:
            return
        
        query = """
            INSERT INTO orderbook_snapshots 
            (ts, symbol, exchange, seq, bids, asks, spread_bps, bid_depth_usd, ask_depth_usd, orderbook_imbalance, tenant_id, bot_id)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
        """
        
        # Prepare batch data
        records = [
            (
                snapshot.timestamp,
                snapshot.symbol,
                snapshot.exchange,
                snapshot.seq,
                json.dumps(snapshot.bids),
                json.dumps(snapshot.asks),
                snapshot.spread_bps,
                snapshot.bid_depth_usd,
                snapshot.ask_depth_usd,
                snapshot.orderbook_imbalance,
                snapshot.tenant_id,
                snapshot.bot_id,
            )
            for snapshot in snapshots
        ]
        
        async with self.pool.acquire() as conn:
            await conn.executemany(query, records)
    
    async def start_background_flush(self) -> None:
        """Start background task for periodic flushing.
        
        This starts an asyncio task that periodically flushes the buffer
        to the database at the configured flush_interval_sec.
        
        Validates: Requirements 1.4
        """
        if self._running:
            return
        
        self._running = True
        self._flush_task = asyncio.create_task(self._background_flush_loop())
    
    async def _background_flush_loop(self) -> None:
        """Background loop that periodically flushes the buffer."""
        while self._running:
            try:
                await asyncio.sleep(self.config.flush_interval_sec)
                if self._running:  # Check again after sleep
                    await self._flush_buffer()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in background flush loop: {e}")
    
    async def stop(self) -> None:
        """Stop background flush and drain buffer.
        
        This method stops the background flush task and performs a final
        flush to ensure all buffered snapshots are persisted before shutdown.
        
        Validates: Requirements 1.4
        """
        self._running = False
        
        if self._flush_task:
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass
            self._flush_task = None
        
        # Final flush to drain buffer
        await self._flush_buffer()
    
    def get_last_capture_time(self, symbol: str, exchange: str) -> Optional[float]:
        """Get the last capture time for a symbol/exchange pair.
        
        This is primarily useful for testing and debugging.
        
        Args:
            symbol: The trading pair symbol.
            exchange: The exchange identifier.
        
        Returns:
            The timestamp of the last capture, or None if never captured.
        """
        return self._last_capture_time.get((symbol, exchange))
    
    def get_buffer_size(self) -> int:
        """Get the current buffer size.
        
        This is primarily useful for testing and monitoring.
        
        Returns:
            The number of snapshots currently in the buffer.
        """
        return len(self._buffer)
