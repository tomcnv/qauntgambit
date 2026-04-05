"""Trade record reader for backtest replay.

This module provides the TradeRecordReader class that queries stored
trade records from TimescaleDB for backtest replay.

Feature: live-orderbook-data-storage
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import AsyncIterator, List, Optional, TYPE_CHECKING

from quantgambit.storage.persistence import PersistenceTradeRecord

if TYPE_CHECKING:
    import asyncpg

logger = logging.getLogger(__name__)


@dataclass
class TradeRecordReaderConfig:
    """Configuration for trade record reading.
    
    Attributes:
        batch_size: Number of trades to fetch per query batch.
            Larger batches are more efficient but use more memory.
            Default is 5000 trades.
        tenant_id: Tenant ID filter for multi-tenant deployments.
            Default is "default".
        bot_id: Bot ID filter for multi-bot deployments.
            Default is "default".
    """
    
    batch_size: int = 5000
    tenant_id: str = "default"
    bot_id: str = "default"


class TradeRecordReader:
    """Reads trade records from TimescaleDB for backtest replay.
    
    This class queries stored trade records and returns them in
    chronological order for use in backtesting. It supports time-range
    queries and streaming iteration for memory-efficient processing.
    
    The reader preserves all stored data including the original exchange
    timestamp, enabling accurate replay of historical trade flow.
    
    Attributes:
        pool: The asyncpg connection pool for database operations.
        config: Configuration for trade record reading.
    
    Example:
        >>> reader = TradeRecordReader(pool, config)
        >>> async for trade in reader.iter_trades("BTC/USDT", "binance", start, end):
        ...     # Process trade in backtest
        ...     process_trade(trade)
    
    Validates: Requirements 6.6
    """
    
    def __init__(
        self,
        pool: "asyncpg.Pool",
        config: Optional[TradeRecordReaderConfig] = None,
    ) -> None:
        """Initialize the TradeRecordReader.
        
        Args:
            pool: The asyncpg connection pool for database operations.
            config: Configuration for trade record reading.
                If None, uses default configuration.
        """
        self.pool = pool
        self.config = config or TradeRecordReaderConfig()
    
    async def get_trades(
        self,
        symbol: str,
        exchange: str,
        start_time: datetime,
        end_time: datetime,
        limit: Optional[int] = None,
    ) -> List[PersistenceTradeRecord]:
        """Query trade records by symbol, exchange, and time range.
        
        Returns all trades within the specified time range, ordered
        chronologically. Use iter_trades() for large result sets to
        avoid loading all data into memory at once.
        
        Args:
            symbol: The trading pair symbol (e.g., "BTC/USDT").
            exchange: The exchange identifier (e.g., "binance").
            start_time: Start of the time range (inclusive).
            end_time: End of the time range (inclusive).
            limit: Maximum number of trades to return.
                If None, returns all matching trades.
        
        Returns:
            List of PersistenceTradeRecord objects ordered by timestamp.
        
        Validates: Requirements 6.6
        """
        query = """
            SELECT ts, symbol, exchange, price, size, side, trade_id
            FROM trade_records
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
        
        return [self._row_to_trade(row) for row in rows]
    
    async def iter_trades(
        self,
        symbol: str,
        exchange: str,
        start_time: datetime,
        end_time: datetime,
    ) -> AsyncIterator[PersistenceTradeRecord]:
        """Iterate over trade records in batches.
        
        This method streams trades in batches for memory-efficient
        processing of large time ranges. Each batch is fetched from the
        database as needed.
        
        Args:
            symbol: The trading pair symbol (e.g., "BTC/USDT").
            exchange: The exchange identifier (e.g., "binance").
            start_time: Start of the time range (inclusive).
            end_time: End of the time range (inclusive).
        
        Yields:
            PersistenceTradeRecord objects in chronological order.
        
        Validates: Requirements 6.6
        """
        query = """
            SELECT ts, symbol, exchange, price, size, side, trade_id
            FROM trade_records
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
                yield self._row_to_trade(row)
            
            offset += len(rows)
            
            # If we got fewer rows than batch_size, we've reached the end
            if len(rows) < self.config.batch_size:
                break
    
    async def get_trade_by_id(
        self,
        trade_id: str,
        symbol: Optional[str] = None,
        exchange: Optional[str] = None,
    ) -> Optional[PersistenceTradeRecord]:
        """Get a specific trade by its trade_id.
        
        This is useful for verifying specific trades or debugging.
        Optionally filter by symbol and exchange for faster lookup.
        
        Args:
            trade_id: The unique trade identifier from the exchange.
            symbol: Optional symbol filter for faster lookup.
            exchange: Optional exchange filter for faster lookup.
        
        Returns:
            The matching PersistenceTradeRecord, or None if not found.
        
        Validates: Requirements 6.6
        """
        if symbol is not None and exchange is not None:
            query = """
                SELECT ts, symbol, exchange, price, size, side, trade_id
                FROM trade_records
                WHERE trade_id = $1
                  AND symbol = $2
                  AND exchange = $3
                  AND tenant_id = $4
                  AND bot_id = $5
                LIMIT 1
            """
            params = (trade_id, symbol, exchange, self.config.tenant_id, self.config.bot_id)
        else:
            query = """
                SELECT ts, symbol, exchange, price, size, side, trade_id
                FROM trade_records
                WHERE trade_id = $1
                  AND tenant_id = $2
                  AND bot_id = $3
                LIMIT 1
            """
            params = (trade_id, self.config.tenant_id, self.config.bot_id)
        
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(query, *params)
        
        if row is None:
            return None
        
        return self._row_to_trade(row)
    
    async def get_trade_count(
        self,
        symbol: str,
        exchange: str,
        start_time: datetime,
        end_time: datetime,
    ) -> int:
        """Get the count of trades in a time range.
        
        Useful for estimating backtest duration or validating data
        availability before starting a replay.
        
        Args:
            symbol: The trading pair symbol (e.g., "BTC/USDT").
            exchange: The exchange identifier (e.g., "binance").
            start_time: Start of the time range (inclusive).
            end_time: End of the time range (inclusive).
        
        Returns:
            The number of trades in the time range.
        """
        query = """
            SELECT COUNT(*)
            FROM trade_records
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
    
    async def get_trade_volume(
        self,
        symbol: str,
        exchange: str,
        start_time: datetime,
        end_time: datetime,
    ) -> tuple[float, float]:
        """Get total trade volume in a time range.
        
        Returns both the total size (quantity) and total value (price * size)
        of all trades in the time range.
        
        Args:
            symbol: The trading pair symbol (e.g., "BTC/USDT").
            exchange: The exchange identifier (e.g., "binance").
            start_time: Start of the time range (inclusive).
            end_time: End of the time range (inclusive).
        
        Returns:
            Tuple of (total_size, total_value).
        """
        query = """
            SELECT COALESCE(SUM(size), 0) as total_size,
                   COALESCE(SUM(price * size), 0) as total_value
            FROM trade_records
            WHERE symbol = $1
              AND exchange = $2
              AND ts >= $3
              AND ts <= $4
              AND tenant_id = $5
              AND bot_id = $6
        """
        
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                query,
                symbol,
                exchange,
                start_time,
                end_time,
                self.config.tenant_id,
                self.config.bot_id,
            )
        
        return (float(row["total_size"]), float(row["total_value"]))
    
    async def get_first_trade_time(
        self,
        symbol: str,
        exchange: str,
    ) -> Optional[datetime]:
        """Get the timestamp of the first trade for a symbol/exchange.
        
        Useful for determining the available data range.
        
        Args:
            symbol: The trading pair symbol (e.g., "BTC/USDT").
            exchange: The exchange identifier (e.g., "binance").
        
        Returns:
            The timestamp of the first trade, or None if no trades exist.
        """
        query = """
            SELECT MIN(ts)
            FROM trade_records
            WHERE symbol = $1
              AND exchange = $2
              AND tenant_id = $3
              AND bot_id = $4
        """
        
        async with self.pool.acquire() as conn:
            ts = await conn.fetchval(
                query,
                symbol,
                exchange,
                self.config.tenant_id,
                self.config.bot_id,
            )
        
        return ts
    
    async def get_last_trade_time(
        self,
        symbol: str,
        exchange: str,
    ) -> Optional[datetime]:
        """Get the timestamp of the last trade for a symbol/exchange.
        
        Useful for determining the available data range.
        
        Args:
            symbol: The trading pair symbol (e.g., "BTC/USDT").
            exchange: The exchange identifier (e.g., "binance").
        
        Returns:
            The timestamp of the last trade, or None if no trades exist.
        """
        query = """
            SELECT MAX(ts)
            FROM trade_records
            WHERE symbol = $1
              AND exchange = $2
              AND tenant_id = $3
              AND bot_id = $4
        """
        
        async with self.pool.acquire() as conn:
            ts = await conn.fetchval(
                query,
                symbol,
                exchange,
                self.config.tenant_id,
                self.config.bot_id,
            )
        
        return ts
    
    def _row_to_trade(self, row) -> PersistenceTradeRecord:
        """Convert a database row to a PersistenceTradeRecord."""
        return PersistenceTradeRecord(
            symbol=row["symbol"],
            exchange=row["exchange"],
            timestamp=row["ts"],
            price=float(row["price"]),
            size=float(row["size"]),
            side=row["side"],
            trade_id=row["trade_id"],
        )
