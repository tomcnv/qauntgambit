"""Orderbook snapshot reader for backtest replay.

This module provides the OrderbookSnapshotReader class that queries stored
orderbook snapshots from TimescaleDB and reconstructs OrderbookState objects
for backtest replay.

Feature: live-orderbook-data-storage
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import AsyncIterator, List, Optional, TYPE_CHECKING

from quantgambit.market.orderbooks import OrderbookState
from quantgambit.storage.persistence import OrderbookSnapshot

if TYPE_CHECKING:
    import asyncpg

logger = logging.getLogger(__name__)


@dataclass
class OrderbookSnapshotReaderConfig:
    """Configuration for orderbook snapshot reading.
    
    Attributes:
        batch_size: Number of snapshots to fetch per query batch.
            Larger batches are more efficient but use more memory.
            Default is 1000 snapshots.
        tenant_id: Tenant ID filter for multi-tenant deployments.
            Default is "default".
        bot_id: Bot ID filter for multi-bot deployments.
            Default is "default".
    """
    
    batch_size: int = 1000
    tenant_id: str = "default"
    bot_id: str = "default"


class OrderbookSnapshotReader:
    """Reads orderbook snapshots from TimescaleDB for backtest replay.
    
    This class queries stored orderbook snapshots and can reconstruct
    OrderbookState objects for use in backtesting. It supports time-range
    queries and streaming iteration for memory-efficient processing.
    
    The reader preserves all stored data including derived metrics,
    enabling accurate replay of historical market conditions.
    
    Attributes:
        pool: The asyncpg connection pool for database operations.
        config: Configuration for snapshot reading.
    
    Example:
        >>> reader = OrderbookSnapshotReader(pool, config)
        >>> async for snapshot in reader.iter_snapshots("BTC/USDT", "binance", start, end):
        ...     state = reader.reconstruct_state(snapshot)
        ...     # Use state in backtest
    
    Validates: Requirements 6.5
    """
    
    def __init__(
        self,
        pool: "asyncpg.Pool",
        config: Optional[OrderbookSnapshotReaderConfig] = None,
    ) -> None:
        """Initialize the OrderbookSnapshotReader.
        
        Args:
            pool: The asyncpg connection pool for database operations.
            config: Configuration for snapshot reading.
                If None, uses default configuration.
        """
        self.pool = pool
        self.config = config or OrderbookSnapshotReaderConfig()
    
    async def get_snapshots(
        self,
        symbol: str,
        exchange: str,
        start_time: datetime,
        end_time: datetime,
        limit: Optional[int] = None,
    ) -> List[OrderbookSnapshot]:
        """Query orderbook snapshots by symbol, exchange, and time range.
        
        Returns all snapshots within the specified time range, ordered
        chronologically. Use iter_snapshots() for large result sets to
        avoid loading all data into memory at once.
        
        Args:
            symbol: The trading pair symbol (e.g., "BTC/USDT").
            exchange: The exchange identifier (e.g., "binance").
            start_time: Start of the time range (inclusive).
            end_time: End of the time range (inclusive).
            limit: Maximum number of snapshots to return.
                If None, returns all matching snapshots.
        
        Returns:
            List of OrderbookSnapshot objects ordered by timestamp.
        
        Validates: Requirements 6.5
        """
        query = """
            SELECT ts, symbol, exchange, seq, bids, asks,
                   spread_bps, bid_depth_usd, ask_depth_usd, orderbook_imbalance
            FROM orderbook_snapshots
            WHERE symbol = $1
              AND exchange = $2
              AND ts >= $3
              AND ts <= $4
              AND tenant_id = $5
              AND bot_id = $6
            ORDER BY ts ASC
        """
        
        if limit is not None:
            query += f" LIMIT {limit}"
        
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                query,
                symbol,
                exchange,
                start_time,
                end_time,
                self.config.tenant_id,
                self.config.bot_id,
            )
        
        return [self._row_to_snapshot(row) for row in rows]
    
    async def iter_snapshots(
        self,
        symbol: str,
        exchange: str,
        start_time: datetime,
        end_time: datetime,
    ) -> AsyncIterator[OrderbookSnapshot]:
        """Iterate over orderbook snapshots in batches.
        
        This method streams snapshots in batches for memory-efficient
        processing of large time ranges. Each batch is fetched from the
        database as needed.
        
        Args:
            symbol: The trading pair symbol (e.g., "BTC/USDT").
            exchange: The exchange identifier (e.g., "binance").
            start_time: Start of the time range (inclusive).
            end_time: End of the time range (inclusive).
        
        Yields:
            OrderbookSnapshot objects in chronological order.
        
        Validates: Requirements 6.5
        """
        query = """
            SELECT ts, symbol, exchange, seq, bids, asks,
                   spread_bps, bid_depth_usd, ask_depth_usd, orderbook_imbalance
            FROM orderbook_snapshots
            WHERE symbol = $1
              AND exchange = $2
              AND ts >= $3
              AND ts <= $4
              AND tenant_id = $5
              AND bot_id = $6
            ORDER BY ts ASC
            LIMIT $7
            OFFSET $8
        """
        
        offset = 0
        while True:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(
                    query,
                    symbol,
                    exchange,
                    start_time,
                    end_time,
                    self.config.tenant_id,
                    self.config.bot_id,
                    self.config.batch_size,
                    offset,
                )
            
            if not rows:
                break
            
            for row in rows:
                yield self._row_to_snapshot(row)
            
            offset += len(rows)
            
            # If we got fewer rows than batch_size, we've reached the end
            if len(rows) < self.config.batch_size:
                break
    
    async def get_latest_snapshot(
        self,
        symbol: str,
        exchange: str,
        before_time: Optional[datetime] = None,
    ) -> Optional[OrderbookSnapshot]:
        """Get the most recent snapshot for a symbol/exchange pair.
        
        This is useful for initializing orderbook state at the start
        of a backtest or for point-in-time queries.
        
        Args:
            symbol: The trading pair symbol (e.g., "BTC/USDT").
            exchange: The exchange identifier (e.g., "binance").
            before_time: If provided, returns the latest snapshot
                before this time. If None, returns the absolute latest.
        
        Returns:
            The most recent OrderbookSnapshot, or None if no snapshots exist.
        
        Validates: Requirements 6.5
        """
        if before_time is not None:
            query = """
                SELECT ts, symbol, exchange, seq, bids, asks,
                       spread_bps, bid_depth_usd, ask_depth_usd, orderbook_imbalance
                FROM orderbook_snapshots
                WHERE symbol = $1
                  AND exchange = $2
                  AND ts <= $3
                  AND tenant_id = $4
                  AND bot_id = $5
                ORDER BY ts DESC
                LIMIT 1
            """
            params = (symbol, exchange, before_time, self.config.tenant_id, self.config.bot_id)
        else:
            query = """
                SELECT ts, symbol, exchange, seq, bids, asks,
                       spread_bps, bid_depth_usd, ask_depth_usd, orderbook_imbalance
                FROM orderbook_snapshots
                WHERE symbol = $1
                  AND exchange = $2
                  AND tenant_id = $3
                  AND bot_id = $4
                ORDER BY ts DESC
                LIMIT 1
            """
            params = (symbol, exchange, self.config.tenant_id, self.config.bot_id)
        
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(query, *params)
        
        if row is None:
            return None
        
        return self._row_to_snapshot(row)
    
    async def get_snapshot_count(
        self,
        symbol: str,
        exchange: str,
        start_time: datetime,
        end_time: datetime,
    ) -> int:
        """Get the count of snapshots in a time range.
        
        Useful for estimating backtest duration or validating data
        availability before starting a replay.
        
        Args:
            symbol: The trading pair symbol (e.g., "BTC/USDT").
            exchange: The exchange identifier (e.g., "binance").
            start_time: Start of the time range (inclusive).
            end_time: End of the time range (inclusive).
        
        Returns:
            The number of snapshots in the time range.
        """
        query = """
            SELECT COUNT(*)
            FROM orderbook_snapshots
            WHERE symbol = $1
              AND exchange = $2
              AND ts >= $3
              AND ts <= $4
              AND tenant_id = $5
              AND bot_id = $6
        """
        
        async with self.pool.acquire() as conn:
            count = await conn.fetchval(
                query,
                symbol,
                exchange,
                start_time,
                end_time,
                self.config.tenant_id,
                self.config.bot_id,
            )
        
        return count or 0
    
    def reconstruct_state(self, snapshot: OrderbookSnapshot) -> OrderbookState:
        """Reconstruct an OrderbookState from a stored snapshot.
        
        This method creates a fully valid OrderbookState object from
        a stored snapshot, suitable for use in backtesting. The
        reconstructed state will have the same bids, asks, and sequence
        number as the original.
        
        Args:
            snapshot: The stored OrderbookSnapshot to reconstruct from.
        
        Returns:
            An OrderbookState with bids, asks, and seq populated from
            the snapshot. The state will have valid=True.
        
        Validates: Requirements 6.5
        """
        state = OrderbookState(symbol=snapshot.symbol)
        state.apply_snapshot(
            bids=snapshot.bids,
            asks=snapshot.asks,
            seq=snapshot.seq,
        )
        return state
    
    def _row_to_snapshot(self, row) -> OrderbookSnapshot:
        """Convert a database row to an OrderbookSnapshot."""
        # Parse JSON strings for bids and asks
        bids = json.loads(row["bids"]) if isinstance(row["bids"], str) else row["bids"]
        asks = json.loads(row["asks"]) if isinstance(row["asks"], str) else row["asks"]
        
        return OrderbookSnapshot(
            symbol=row["symbol"],
            exchange=row["exchange"],
            timestamp=row["ts"],
            seq=row["seq"],
            bids=bids,
            asks=asks,
            spread_bps=row["spread_bps"],
            bid_depth_usd=row["bid_depth_usd"],
            ask_depth_usd=row["ask_depth_usd"],
            orderbook_imbalance=row["orderbook_imbalance"],
        )
