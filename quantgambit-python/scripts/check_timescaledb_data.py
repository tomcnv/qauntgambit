#!/usr/bin/env python3
"""Check available data in TimescaleDB for backtesting.

This script queries the orderbook_snapshots and trade_records tables
to show what data is available for backtesting.

Usage:
    python scripts/check_timescaledb_data.py
"""

import asyncio
import os
from datetime import datetime, timedelta
from pathlib import Path

from quantgambit.config.env_loading import apply_layered_env_defaults

apply_layered_env_defaults(Path(__file__).resolve().parents[1], os.getenv("ENV_FILE"), os.environ)


async def main():
    import asyncpg
    
    # Get connection string from environment
    db_url = os.getenv(
        "BOT_TIMESCALE_URL",
        "postgresql://quantgambit:quantgambit_pw@localhost:5433/quantgambit_bot"
    )
    
    print(f"Connecting to: {db_url.split('@')[1] if '@' in db_url else db_url}")
    print("=" * 70)
    
    try:
        pool = await asyncpg.create_pool(db_url, min_size=1, max_size=2)
    except Exception as e:
        print(f"❌ Failed to connect to database: {e}")
        return
    
    async with pool.acquire() as conn:
        # Check if tables exist
        print("\n📊 TABLE STATUS")
        print("-" * 70)
        
        tables = ["orderbook_snapshots", "trade_records"]
        for table in tables:
            exists = await conn.fetchval(
                "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = $1)",
                table
            )
            if exists:
                count = await conn.fetchval(f"SELECT COUNT(*) FROM {table}")
                print(f"  ✅ {table}: {count:,} rows")
            else:
                print(f"  ❌ {table}: TABLE DOES NOT EXIST")
        
        # Check orderbook snapshots
        print("\n📈 ORDERBOOK SNAPSHOTS")
        print("-" * 70)
        
        orderbook_exists = await conn.fetchval(
            "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'orderbook_snapshots')"
        )
        
        if orderbook_exists:
            # Get summary by symbol/exchange
            summary = await conn.fetch("""
                SELECT 
                    symbol,
                    exchange,
                    COUNT(*) as count,
                    MIN(ts) as first_snapshot,
                    MAX(ts) as last_snapshot,
                    EXTRACT(EPOCH FROM (MAX(ts) - MIN(ts))) / 3600 as hours_of_data
                FROM orderbook_snapshots
                GROUP BY symbol, exchange
                ORDER BY count DESC
                LIMIT 10
            """)
            
            if summary:
                print(f"  {'Symbol':<20} {'Exchange':<10} {'Count':>12} {'First':>20} {'Last':>20} {'Hours':>8}")
                print(f"  {'-'*20} {'-'*10} {'-'*12} {'-'*20} {'-'*20} {'-'*8}")
                for row in summary:
                    first = row['first_snapshot'].strftime('%Y-%m-%d %H:%M') if row['first_snapshot'] else 'N/A'
                    last = row['last_snapshot'].strftime('%Y-%m-%d %H:%M') if row['last_snapshot'] else 'N/A'
                    hours = f"{row['hours_of_data']:.1f}" if row['hours_of_data'] else '0'
                    print(f"  {row['symbol']:<20} {row['exchange']:<10} {row['count']:>12,} {first:>20} {last:>20} {hours:>8}")
            else:
                print("  No orderbook snapshots found")
        
        # Check trade records
        print("\n📉 TRADE RECORDS")
        print("-" * 70)
        
        trades_exists = await conn.fetchval(
            "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'trade_records')"
        )
        
        if trades_exists:
            # Get summary by symbol/exchange
            summary = await conn.fetch("""
                SELECT 
                    symbol,
                    exchange,
                    COUNT(*) as count,
                    MIN(ts) as first_trade,
                    MAX(ts) as last_trade,
                    EXTRACT(EPOCH FROM (MAX(ts) - MIN(ts))) / 3600 as hours_of_data
                FROM trade_records
                GROUP BY symbol, exchange
                ORDER BY count DESC
                LIMIT 10
            """)
            
            if summary:
                print(f"  {'Symbol':<20} {'Exchange':<10} {'Count':>12} {'First':>20} {'Last':>20} {'Hours':>8}")
                print(f"  {'-'*20} {'-'*10} {'-'*12} {'-'*20} {'-'*20} {'-'*8}")
                for row in summary:
                    first = row['first_trade'].strftime('%Y-%m-%d %H:%M') if row['first_trade'] else 'N/A'
                    last = row['last_trade'].strftime('%Y-%m-%d %H:%M') if row['last_trade'] else 'N/A'
                    hours = f"{row['hours_of_data']:.1f}" if row['hours_of_data'] else '0'
                    print(f"  {row['symbol']:<20} {row['exchange']:<10} {row['count']:>12,} {first:>20} {last:>20} {hours:>8}")
            else:
                print("  No trade records found")
        
        # Check recent data (last 24 hours)
        print("\n⏰ RECENT DATA (Last 24 Hours)")
        print("-" * 70)
        
        yesterday = datetime.utcnow() - timedelta(hours=24)
        
        if orderbook_exists:
            recent_orderbooks = await conn.fetchval(
                "SELECT COUNT(*) FROM orderbook_snapshots WHERE ts > $1",
                yesterday
            )
            print(f"  Orderbook snapshots (24h): {recent_orderbooks:,}")
        
        if trades_exists:
            recent_trades = await conn.fetchval(
                "SELECT COUNT(*) FROM trade_records WHERE ts > $1",
                yesterday
            )
            print(f"  Trade records (24h): {recent_trades:,}")
        
        # Recommendations
        print("\n💡 RECOMMENDATIONS")
        print("-" * 70)
        
        total_orderbooks = await conn.fetchval("SELECT COUNT(*) FROM orderbook_snapshots") if orderbook_exists else 0
        total_trades = await conn.fetchval("SELECT COUNT(*) FROM trade_records") if trades_exists else 0
        
        if total_orderbooks == 0:
            print("  ⚠️  No orderbook data! You need to run the live system to collect data.")
            print("     Start the runtime with PERSISTENCE_ORDERBOOK_ENABLED=true")
        elif total_orderbooks < 1000:
            print(f"  ⚠️  Only {total_orderbooks} orderbook snapshots. Need more data for meaningful backtests.")
            print("     Let the system run for a few hours to collect more data.")
        else:
            print(f"  ✅ {total_orderbooks:,} orderbook snapshots available for backtesting")
        
        if total_trades == 0:
            print("  ⚠️  No trade data! Enable trade persistence with PERSISTENCE_TRADES_ENABLED=true")
        else:
            print(f"  ✅ {total_trades:,} trade records available")
    
    await pool.close()
    print("\n" + "=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
