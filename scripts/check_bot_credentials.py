#!/usr/bin/env python3
"""Check bot credentials configuration."""

import asyncio
import asyncpg
import os
import sys

async def main():
    bot_id = "bf167763-fee1-4f11-ab9a-6fddadf125de"
    
    conn = await asyncpg.connect(
        host='localhost',
        database='platform_db',
        user='platform',
        password='platform_pw'
    )
    
    # Get bot config with exchange account
    row = await conn.fetchrow('''
        SELECT 
            b.id, 
            b.name, 
            b.exchange, 
            b.testnet as bot_testnet,
            ea.id as ea_id,
            ea.name as ea_name,
            ea.api_key,
            ea.testnet as ea_testnet,
            ea.exchange as ea_exchange
        FROM bots b
        LEFT JOIN exchange_accounts ea ON b.exchange_account_id = ea.id
        WHERE b.id = $1
    ''', bot_id)
    
    if row:
        print(f"=== Bot Configuration ===")
        print(f"Bot ID: {row['id']}")
        print(f"Bot Name: {row['name']}")
        print(f"Exchange: {row['exchange']}")
        print(f"Bot Testnet Flag: {row['bot_testnet']}")
        print()
        print(f"=== Exchange Account ===")
        print(f"EA ID: {row['ea_id']}")
        print(f"EA Name: {row['ea_name']}")
        print(f"EA Exchange: {row['ea_exchange']}")
        print(f"EA Testnet Flag: {row['ea_testnet']}")
        api_key = row['api_key']
        if api_key:
            print(f"API Key (first 8 chars): {api_key[:8]}...")
            print(f"API Key length: {len(api_key)}")
        else:
            print("API Key: None")
    else:
        print(f"Bot {bot_id} not found")
    
    # Check environment variables
    print()
    print("=== Environment Variables ===")
    print(f"BYBIT_TESTNET: {os.getenv('BYBIT_TESTNET', 'not set')}")
    print(f"BYBIT_API_KEY: {'set' if os.getenv('BYBIT_API_KEY') else 'not set'}")
    print(f"BYBIT_SECRET_KEY: {'set' if os.getenv('BYBIT_SECRET_KEY') else 'not set'}")
    
    await conn.close()

if __name__ == "__main__":
    asyncio.run(main())
