"""Trade record writer for persisting trade records to TimescaleDB.

This module provides the TradeRecordWriter class that buffers trade records
and persists them asynchronously to TimescaleDB using batch inserts.

Feature: live-orderbook-data-storage
"""

from __future__ import annotations

import asyncio
import logging
from typing import List, Optional, TYPE_CHECKING

from quantgambit.storage.persistence import (
    PersistenceTradeRecord,
    TradeRecordWriterConfig,
)

if TYPE_CHECKING:
    import asyncpg

logger = logging.getLogger(__name__)

async def _sleep(delay_sec: float) -> None:
    """Event-loop-based sleep that remains a real suspension point if asyncio.sleep is patched."""
    loop = asyncio.get_running_loop()
    fut = loop.create_future()
    loop.call_later(max(0.0, float(delay_sec)), fut.set_result, None)
    await fut


class TradeRecordWriter:
    """Persists trade records to TimescaleDB asynchronously.
    
    This class buffers trade records and persists them to TimescaleDB using
    batch inserts. It is designed to handle high-frequency trade data
    (100+ trades/second per symbol) without blocking the main trade
    processing loop.
    
    The writer preserves the original exchange timestamp for each trade,
    ensuring accurate replay during backtesting. All database operations
    happen asynchronously in the background.
    
    Attributes:
        pool: The asyncpg connection pool for database operations.
        config: Configuration for trade record persistence.
    
    Example:
        >>> writer = TradeRecordWriter(pool, config)
        >>> await writer.start_background_flush()
        >>> # In the trade processing loop:
        >>> await writer.record(trade)
        >>> # On shutdown:
        >>> await writer.stop()
    
    Validates: Requirements 2.1, 2.3, 2.5, 2.6
    """
    
    def __init__(
        self,
        pool: "asyncpg.Pool",
        config: Optional[TradeRecordWriterConfig] = None,
    ) -> None:
        """Initialize the TradeRecordWriter.
        
        Args:
            pool: The asyncpg connection pool for database operations.
            config: Configuration for trade record persistence.
                If None, uses default configuration.
        """
        self.pool = pool
        self.config = config or TradeRecordWriterConfig()
        
        # Buffer for batch writes
        self._buffer: List[PersistenceTradeRecord] = []
        self._buffer_lock = asyncio.Lock()
        
        # Background flush task
        self._flush_task: Optional[asyncio.Task] = None
        self._running = False
    
    async def record(self, trade: PersistenceTradeRecord) -> None:
        """Buffer a trade for persistence. Non-blocking.
        
        This method adds a trade record to the buffer for batch persistence.
        The original exchange timestamp is preserved in the trade record
        to ensure accurate replay during backtesting.
        
        The method is non-blocking - it does not wait for database writes.
        Trades are buffered and flushed periodically by the background task
        or when the buffer reaches batch_size.
        
        Args:
            trade: The trade record to persist. The timestamp field MUST
                contain the original exchange timestamp, not the local
                processing time.
        
        Validates: Requirements 2.1, 2.6
        """
        if not self.config.enabled:
            return
        
        # Add to buffer. If batch_size is reached, clear the buffer immediately
        # (within the lock) and schedule the DB insert in the background. This
        # avoids relying on background scheduling to make buffer state consistent.
        trades_to_flush: Optional[List[PersistenceTradeRecord]] = None
        async with self._buffer_lock:
            self._buffer.append(trade)
            if len(self._buffer) >= self.config.batch_size:
                trades_to_flush = self._buffer[:]
                self._buffer.clear()

        if trades_to_flush:
            asyncio.create_task(self._batch_insert_with_retry(trades_to_flush))
    
    async def flush(self) -> int:
        """Flush buffered trades to database. Returns count written.
        
        This method flushes all buffered trades to the database using
        a batch insert. It handles retries with exponential backoff on
        failure.
        
        Returns:
            The number of trades written to the database.
        
        Validates: Requirements 2.3, 2.5
        """
        return await self._flush_buffer()
    
    async def _flush_buffer(self) -> int:
        """Internal method to flush the buffer to the database."""
        async with self._buffer_lock:
            if not self._buffer:
                return 0
            
            # Take all trades from buffer
            trades = self._buffer[:]
            self._buffer.clear()
        
        # Perform batch insert with retry
        return await self._batch_insert_with_retry(trades)
    
    async def _batch_insert_with_retry(self, trades: List[PersistenceTradeRecord]) -> int:
        """Insert trades with exponential backoff retry on failure.
        
        Validates: Requirements 2.4
        """
        if not trades:
            return 0
        
        for attempt in range(self.config.retry_max_attempts):
            try:
                await self._batch_insert(trades)
                return len(trades)
            except Exception as e:
                delay = self.config.retry_base_delay_sec * (2 ** attempt)
                logger.warning(
                    f"Trade batch insert failed (attempt {attempt + 1}/{self.config.retry_max_attempts}): {e}. "
                    f"Retrying in {delay:.2f}s"
                )
                if attempt < self.config.retry_max_attempts - 1:
                    await _sleep(delay)
        
        # All retries exhausted, log error and drop the batch
        logger.error(
            f"Failed to insert {len(trades)} trades after {self.config.retry_max_attempts} attempts. "
            "Dropping batch to protect live trading."
        )
        return 0
    
    async def _batch_insert(self, trades: List[PersistenceTradeRecord]) -> None:
        """Perform the actual batch insert to the database.
        
        The trade's timestamp is used directly, preserving the original
        exchange timestamp for accurate replay.
        """
        if not trades:
            return
        
        query = """
            INSERT INTO trade_records 
            (ts, symbol, exchange, price, size, side, trade_id, tenant_id, bot_id)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
        """
        
        # Prepare batch data - timestamp is preserved from the original trade
        records = [
            (
                trade.timestamp,  # Original exchange timestamp preserved
                trade.symbol,
                trade.exchange,
                trade.price,
                trade.size,
                trade.side,
                trade.trade_id,
                trade.tenant_id,
                trade.bot_id,
            )
            for trade in trades
        ]
        
        async with self.pool.acquire() as conn:
            await conn.executemany(query, records)
    
    async def start_background_flush(self) -> None:
        """Start background task for periodic flushing.
        
        This starts an asyncio task that periodically flushes the buffer
        to the database at the configured flush_interval_sec.
        
        Validates: Requirements 2.3
        """
        if self._running:
            return
        
        self._running = True
        await self._flush_buffer()
        self._flush_task = asyncio.create_task(self._background_flush_loop())
    
    async def _background_flush_loop(self) -> None:
        """Background loop that periodically flushes the buffer."""
        while self._running:
            try:
                await self._flush_buffer()
                await _sleep(self.config.flush_interval_sec)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in background flush loop: {e}")
    
    async def stop(self) -> None:
        """Stop background flush and drain buffer.
        
        This method stops the background flush task and performs a final
        flush to ensure all buffered trades are persisted before shutdown.
        
        Validates: Requirements 2.3
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
    
    def get_buffer_size(self) -> int:
        """Get the current buffer size.
        
        This is primarily useful for testing and monitoring.
        
        Returns:
            The number of trades currently in the buffer.
        """
        return len(self._buffer)
