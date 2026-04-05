#!/usr/bin/env python3
"""CLI script for backfilling historical candle data from exchanges.

Usage:
    python scripts/backfill_candles.py --symbol BTCUSDT --exchange bybit \
        --start 2024-01-01 --end 2024-01-31 --timeframe 5m

    # Backfill multiple symbols
    python scripts/backfill_candles.py --symbol BTCUSDT,ETHUSDT --exchange bybit \
        --start 2024-01-01 --end 2024-01-31

    # Use testnet
    python scripts/backfill_candles.py --symbol BTCUSDT --exchange bybit \
        --start 2024-01-01 --end 2024-01-31 --testnet
"""

import argparse
import asyncio
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from quantgambit.config.env_loading import apply_layered_env_defaults
from quantgambit.backtesting.data_backfill import DataBackfillService, BackfillConfig

apply_layered_env_defaults(Path(__file__).resolve().parents[1], os.getenv("ENV_FILE"), os.environ)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


async def create_pool():
    """Create asyncpg connection pool."""
    import asyncpg
    
    database_url = os.getenv(
        "BOT_TIMESCALE_URL",
        os.getenv(
            "TIMESCALE_URL",
            os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/deeptrader")
        )
    )
    
    return await asyncpg.create_pool(database_url, min_size=1, max_size=5)


async def run_backfill(
    symbols: list[str],
    exchange: str,
    start_date: str,
    end_date: str,
    timeframe: str,
    testnet: bool = False,
    batch_size: int = 1000,
    rate_limit_ms: int = 100,
):
    """Run backfill for specified symbols."""
    pool = await create_pool()
    
    try:
        config = BackfillConfig(
            batch_size=batch_size,
            rate_limit_delay_ms=rate_limit_ms,
        )
        service = DataBackfillService(pool, config)
        
        results = []
        for symbol in symbols:
            logger.info(f"Starting backfill for {symbol}...")
            
            result = await service.backfill(
                symbol=symbol,
                exchange=exchange,
                start_date=start_date,
                end_date=end_date,
                timeframe=timeframe,
                testnet=testnet,
            )
            
            results.append(result)
            
            # Print result
            print(f"\n{'='*60}")
            print(f"Symbol: {result.symbol}")
            print(f"Exchange: {result.exchange}")
            print(f"Period: {result.start_date} to {result.end_date}")
            print(f"Timeframe: {result.timeframe}")
            print(f"Status: {result.status}")
            print(f"Total candles: {result.total_candles}")
            print(f"Inserted: {result.inserted_candles}")
            print(f"Skipped (duplicates): {result.skipped_candles}")
            print(f"Failed batches: {result.failed_batches}")
            print(f"Duration: {result.duration_sec:.2f}s")
            if result.error:
                print(f"Error: {result.error}")
            print(f"{'='*60}\n")
        
        # Summary
        total_inserted = sum(r.inserted_candles for r in results)
        total_skipped = sum(r.skipped_candles for r in results)
        total_failed = sum(r.failed_batches for r in results)
        
        print(f"\n{'='*60}")
        print("SUMMARY")
        print(f"{'='*60}")
        print(f"Symbols processed: {len(results)}")
        print(f"Total inserted: {total_inserted}")
        print(f"Total skipped: {total_skipped}")
        print(f"Total failed batches: {total_failed}")
        print(f"{'='*60}\n")
        
        return results
        
    finally:
        await pool.close()


def main():
    parser = argparse.ArgumentParser(
        description="Backfill historical candle data from exchanges",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    
    parser.add_argument(
        "--symbol", "-s",
        required=True,
        help="Trading symbol(s), comma-separated (e.g., BTCUSDT or BTCUSDT,ETHUSDT)",
    )
    parser.add_argument(
        "--exchange", "-e",
        default="bybit",
        choices=["bybit", "binance", "okx"],
        help="Exchange name (default: bybit)",
    )
    parser.add_argument(
        "--start", "-S",
        required=True,
        help="Start date (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--end", "-E",
        required=True,
        help="End date (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--timeframe", "-t",
        default="5m",
        choices=["1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "12h", "1d"],
        help="Candle timeframe (default: 5m)",
    )
    parser.add_argument(
        "--testnet",
        action="store_true",
        help="Use testnet instead of mainnet",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=1000,
        help="Number of candles per API request (default: 1000)",
    )
    parser.add_argument(
        "--rate-limit",
        type=int,
        default=100,
        help="Delay between API requests in milliseconds (default: 100)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose logging",
    )
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    # Parse symbols
    symbols = [s.strip().upper() for s in args.symbol.split(",")]
    
    # Validate dates
    try:
        datetime.strptime(args.start, "%Y-%m-%d")
        datetime.strptime(args.end, "%Y-%m-%d")
    except ValueError as e:
        print(f"Error: Invalid date format. Use YYYY-MM-DD. {e}")
        sys.exit(1)
    
    print(f"\nBackfill Configuration:")
    print(f"  Symbols: {', '.join(symbols)}")
    print(f"  Exchange: {args.exchange}")
    print(f"  Period: {args.start} to {args.end}")
    print(f"  Timeframe: {args.timeframe}")
    print(f"  Testnet: {args.testnet}")
    print(f"  Batch size: {args.batch_size}")
    print(f"  Rate limit: {args.rate_limit}ms")
    print()
    
    # Run backfill
    asyncio.run(run_backfill(
        symbols=symbols,
        exchange=args.exchange,
        start_date=args.start,
        end_date=args.end,
        timeframe=args.timeframe,
        testnet=args.testnet,
        batch_size=args.batch_size,
        rate_limit_ms=args.rate_limit,
    ))


if __name__ == "__main__":
    main()
