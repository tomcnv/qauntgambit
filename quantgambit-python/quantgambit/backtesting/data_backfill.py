"""Data backfill service for fetching historical candle data from exchanges.

This module provides functionality to backfill missing candle data from exchanges
using ccxt. It supports Bybit, Binance, and OKX exchanges.

Usage:
    from quantgambit.backtesting.data_backfill import DataBackfillService
    
    service = DataBackfillService(timescale_pool)
    result = await service.backfill(
        symbol="BTCUSDT",
        exchange="bybit",
        start_date="2024-01-01",
        end_date="2024-01-31",
        timeframe="5m"
    )
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple

import ccxt.async_support as ccxt

logger = logging.getLogger(__name__)


@dataclass
class BackfillConfig:
    """Configuration for data backfill."""
    batch_size: int = 1000  # Max candles per API request
    rate_limit_delay_ms: int = 100  # Delay between API requests
    max_retries: int = 3  # Max retries per batch
    retry_delay_sec: float = 1.0  # Delay between retries


@dataclass
class BackfillProgress:
    """Progress tracking for backfill operation."""
    total_candles: int = 0
    inserted_candles: int = 0
    skipped_candles: int = 0  # Already existed
    failed_batches: int = 0
    current_date: Optional[str] = None
    status: str = "pending"  # pending, running, completed, failed
    error: Optional[str] = None
    started_at: Optional[str] = None
    finished_at: Optional[str] = None


@dataclass
class BackfillResult:
    """Result of a backfill operation."""
    symbol: str
    exchange: str
    start_date: str
    end_date: str
    timeframe: str
    total_candles: int
    inserted_candles: int
    skipped_candles: int
    failed_batches: int
    duration_sec: float
    status: str
    error: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "exchange": self.exchange,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "timeframe": self.timeframe,
            "total_candles": self.total_candles,
            "inserted_candles": self.inserted_candles,
            "skipped_candles": self.skipped_candles,
            "failed_batches": self.failed_batches,
            "duration_sec": round(self.duration_sec, 2),
            "status": self.status,
            "error": self.error,
        }


# Timeframe to seconds mapping
TIMEFRAME_SECONDS = {
    "1m": 60,
    "3m": 180,
    "5m": 300,
    "15m": 900,
    "30m": 1800,
    "1h": 3600,
    "2h": 7200,
    "4h": 14400,
    "6h": 21600,
    "12h": 43200,
    "1d": 86400,
}


def _normalize_symbol(exchange: str, symbol: str) -> str:
    """Normalize symbol format for exchange."""
    exchange = exchange.lower()
    symbol = symbol.upper().replace("-", "").replace("/", "").replace("_", "")
    
    # Remove common suffixes
    for suffix in ["SWAP", "PERP", "PERPETUAL"]:
        if symbol.endswith(suffix):
            symbol = symbol[:-len(suffix)]
    
    if exchange == "bybit":
        # Bybit linear perps use BTCUSDT format
        return symbol
    elif exchange == "binance":
        # Binance futures use BTCUSDT format
        return symbol
    elif exchange == "okx":
        # OKX uses BTC-USDT-SWAP format
        if "USDT" in symbol:
            base = symbol.replace("USDT", "")
            return f"{base}-USDT-SWAP"
        return symbol
    return symbol


def _create_exchange(exchange_name: str, testnet: bool = False) -> ccxt.Exchange:
    """Create ccxt exchange instance."""
    exchange_name = exchange_name.lower()
    
    options = {
        "enableRateLimit": True,
        "timeout": 30000,
    }
    
    if exchange_name == "bybit":
        exchange = ccxt.bybit(options)
        if testnet:
            exchange.set_sandbox_mode(True)
        exchange.options["defaultType"] = "linear"
    elif exchange_name == "binance":
        exchange = ccxt.binance(options)
        if testnet:
            exchange.set_sandbox_mode(True)
        exchange.options["defaultType"] = "future"
    elif exchange_name == "okx":
        exchange = ccxt.okx(options)
        if testnet:
            exchange.set_sandbox_mode(True)
        exchange.options["defaultType"] = "swap"
    else:
        raise ValueError(f"Unsupported exchange: {exchange_name}")
    
    return exchange


class DataBackfillService:
    """Service for backfilling historical candle data from exchanges."""
    
    def __init__(
        self,
        timescale_pool,
        config: Optional[BackfillConfig] = None,
    ):
        """Initialize the backfill service.
        
        Args:
            timescale_pool: asyncpg connection pool for TimescaleDB
            config: Optional backfill configuration
        """
        self.pool = timescale_pool
        self.config = config or BackfillConfig()
        self._progress: Dict[str, BackfillProgress] = {}
    
    def get_progress(self, job_id: str) -> Optional[BackfillProgress]:
        """Get progress for a backfill job."""
        return self._progress.get(job_id)
    
    async def backfill(
        self,
        symbol: str,
        exchange: str,
        start_date: str,
        end_date: str,
        timeframe: str = "5m",
        job_id: Optional[str] = None,
        testnet: bool = False,
    ) -> BackfillResult:
        """Backfill historical candle data from exchange.
        
        Args:
            symbol: Trading symbol (e.g., BTCUSDT)
            exchange: Exchange name (bybit, binance, okx)
            start_date: Start date (YYYY-MM-DD or ISO format)
            end_date: End date (YYYY-MM-DD or ISO format)
            timeframe: Candle timeframe (1m, 5m, 15m, 1h, etc.)
            job_id: Optional job ID for progress tracking
            testnet: Whether to use testnet
            
        Returns:
            BackfillResult with operation details
        """
        job_id = job_id or f"{exchange}:{symbol}:{start_date}:{end_date}"
        progress = BackfillProgress(
            status="running",
            started_at=datetime.now(timezone.utc).isoformat(),
        )
        self._progress[job_id] = progress
        
        start_time = datetime.now(timezone.utc)
        
        try:
            # Parse dates
            start_dt = self._parse_date(start_date)
            end_dt = self._parse_date(end_date)
            
            if start_dt >= end_dt:
                raise ValueError("start_date must be before end_date")
            
            # Validate timeframe
            if timeframe not in TIMEFRAME_SECONDS:
                raise ValueError(f"Invalid timeframe: {timeframe}. Valid: {list(TIMEFRAME_SECONDS.keys())}")
            
            timeframe_sec = TIMEFRAME_SECONDS[timeframe]
            
            # Normalize symbol for exchange
            normalized_symbol = _normalize_symbol(exchange, symbol)
            
            logger.info(
                f"Starting backfill: {exchange}:{normalized_symbol} "
                f"from {start_date} to {end_date} ({timeframe})"
            )
            
            # Create exchange instance
            ex = _create_exchange(exchange, testnet)
            
            try:
                # Fetch and insert candles in batches
                total_inserted = 0
                total_skipped = 0
                failed_batches = 0
                
                current_start = start_dt
                batch_duration = timedelta(seconds=timeframe_sec * self.config.batch_size)
                
                while current_start < end_dt:
                    current_end = min(current_start + batch_duration, end_dt)
                    progress.current_date = current_start.strftime("%Y-%m-%d %H:%M")
                    
                    try:
                        # Fetch candles from exchange
                        candles = await self._fetch_candles(
                            ex, normalized_symbol, timeframe,
                            int(current_start.timestamp() * 1000),
                            int(current_end.timestamp() * 1000),
                        )
                        
                        if candles:
                            # Insert into database
                            inserted, skipped = await self._insert_candles(
                                symbol, exchange, timeframe_sec, candles
                            )
                            total_inserted += inserted
                            total_skipped += skipped
                            progress.inserted_candles = total_inserted
                            progress.skipped_candles = total_skipped
                            progress.total_candles = total_inserted + total_skipped
                        
                        # Rate limiting
                        await asyncio.sleep(self.config.rate_limit_delay_ms / 1000)
                        
                    except Exception as e:
                        logger.warning(f"Failed batch {current_start}: {e}")
                        failed_batches += 1
                        progress.failed_batches = failed_batches
                    
                    current_start = current_end
                
                # Success
                duration = (datetime.now(timezone.utc) - start_time).total_seconds()
                progress.status = "completed"
                progress.finished_at = datetime.now(timezone.utc).isoformat()
                
                logger.info(
                    f"Backfill completed: {total_inserted} inserted, "
                    f"{total_skipped} skipped, {failed_batches} failed batches"
                )
                
                return BackfillResult(
                    symbol=symbol,
                    exchange=exchange,
                    start_date=start_date,
                    end_date=end_date,
                    timeframe=timeframe,
                    total_candles=total_inserted + total_skipped,
                    inserted_candles=total_inserted,
                    skipped_candles=total_skipped,
                    failed_batches=failed_batches,
                    duration_sec=duration,
                    status="completed",
                )
                
            finally:
                await ex.close()
                
        except Exception as e:
            logger.exception(f"Backfill failed: {e}")
            duration = (datetime.now(timezone.utc) - start_time).total_seconds()
            progress.status = "failed"
            progress.error = str(e)
            progress.finished_at = datetime.now(timezone.utc).isoformat()
            
            return BackfillResult(
                symbol=symbol,
                exchange=exchange,
                start_date=start_date,
                end_date=end_date,
                timeframe=timeframe,
                total_candles=progress.total_candles,
                inserted_candles=progress.inserted_candles,
                skipped_candles=progress.skipped_candles,
                failed_batches=progress.failed_batches,
                duration_sec=duration,
                status="failed",
                error=str(e),
            )
    
    async def _fetch_candles(
        self,
        exchange: ccxt.Exchange,
        symbol: str,
        timeframe: str,
        since_ms: int,
        until_ms: int,
    ) -> List[List]:
        """Fetch candles from exchange with retry logic."""
        for attempt in range(self.config.max_retries):
            try:
                # ccxt fetch_ohlcv returns [[timestamp, open, high, low, close, volume], ...]
                candles = await exchange.fetch_ohlcv(
                    symbol,
                    timeframe,
                    since=since_ms,
                    limit=self.config.batch_size,
                )
                
                # Filter to requested range
                candles = [c for c in candles if c[0] < until_ms]
                return candles
                
            except Exception as e:
                if attempt < self.config.max_retries - 1:
                    logger.warning(f"Fetch attempt {attempt + 1} failed: {e}, retrying...")
                    await asyncio.sleep(self.config.retry_delay_sec * (attempt + 1))
                else:
                    raise
        
        return []
    
    async def _insert_candles(
        self,
        symbol: str,
        exchange: str,
        timeframe_sec: int,
        candles: List[List],
    ) -> Tuple[int, int]:
        """Insert candles into TimescaleDB.
        
        Returns:
            Tuple of (inserted_count, skipped_count)
        """
        if not candles:
            return 0, 0
        
        inserted = 0
        skipped = 0
        
        async with self.pool.acquire() as conn:
            for candle in candles:
                ts_ms, open_price, high, low, close, volume = candle[:6]
                ts = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
                
                try:
                    # Use INSERT ... ON CONFLICT DO NOTHING to skip duplicates
                    result = await conn.execute(
                        """
                        INSERT INTO market_candles (ts, symbol, timeframe_sec, open, high, low, close, volume)
                        VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                        ON CONFLICT (ts, symbol, timeframe_sec) DO NOTHING
                        """,
                        ts, symbol, timeframe_sec, open_price, high, low, close, volume
                    )
                    
                    # Check if row was inserted
                    if result == "INSERT 0 1":
                        inserted += 1
                    else:
                        skipped += 1
                        
                except Exception as e:
                    logger.warning(f"Failed to insert candle at {ts}: {e}")
                    skipped += 1
        
        return inserted, skipped
    
    def _parse_date(self, date_str: str) -> datetime:
        """Parse date string to datetime."""
        formats = [
            "%Y-%m-%d",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%dT%H:%M:%SZ",
            "%Y-%m-%d %H:%M:%S",
        ]
        
        for fmt in formats:
            try:
                dt = datetime.strptime(date_str, fmt)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt
            except ValueError:
                continue
        
        # Try ISO format with timezone
        try:
            dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            return dt
        except ValueError:
            pass
        
        raise ValueError(f"Unable to parse date: {date_str}")


async def backfill_gaps(
    timescale_pool,
    symbol: str,
    exchange: str,
    gaps: List[Dict[str, Any]],
    timeframe: str = "5m",
) -> List[BackfillResult]:
    """Backfill multiple gaps for a symbol.
    
    Args:
        timescale_pool: asyncpg connection pool
        symbol: Trading symbol
        exchange: Exchange name
        gaps: List of gap info dicts with start_time and end_time
        timeframe: Candle timeframe
        
    Returns:
        List of BackfillResult for each gap
    """
    service = DataBackfillService(timescale_pool)
    results = []
    
    for gap in gaps:
        start_time = gap.get("start_time") or gap.get("start")
        end_time = gap.get("end_time") or gap.get("end")
        
        if not start_time or not end_time:
            continue
        
        result = await service.backfill(
            symbol=symbol,
            exchange=exchange,
            start_date=start_time,
            end_date=end_time,
            timeframe=timeframe,
        )
        results.append(result)
    
    return results
