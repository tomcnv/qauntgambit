#!/usr/bin/env python3
"""Check exchange account configuration."""

import asyncio
import asyncpg

async def main():
    conn = await asyncpg.connect(
        host='localhost',
        database='platform_db',
        user='platform',
        password='platform_pw'
    )
    
    # Get exchange account for this bot
    row = await conn.fetchrow('''
        SELECT 
            ea.id,
            ea.name,
            ea.exchange,
            ea.testnet,
            ea.api_key,
            b.id as bot_id,
            b.name as bot_name,
            b.testnet as bot_testnet
        FROM exchange_accounts ea
        JOIN bots b ON b.exchange_account_id = ea.id
        WHERE ea.id = 'fb213790-5ba6-4637-bccc-25e3d68d4c0c'
    ''')
    
    if row:
        print("=== Exchange Account ===")
        print(f"ID: {row['id']}")
        print(f"Name: {row['name']}")
        print(f"Exchange: {row['exchange']}")
        print(f"Testnet flag: {row['testnet']}")
        print(f"API Key prefix: {row['api_key'][:8] if row['api_key'] else 'None'}...")
        print()
        print("=== Associated Bot ===")
        print(f"Bot ID: {row['bot_id']}")
        print(f"Bot Name: {row['bot_name']}")
        print(f"Bot Testnet flag: {row['bot_testnet']}")
    else:
        print("Exchange account not found")
    
    await conn.close()

if __name__ == "__main__":
    asyncio.run(main())
