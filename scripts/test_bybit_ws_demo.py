#!/usr/bin/env python3
"""Test Bybit WebSocket authentication with demo mode."""

import asyncio
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "quantgambit-python"))

from quantgambit.storage.secrets import get_exchange_credentials
from quantgambit.execution.order_updates_ws import BybitOrderUpdateProvider, BybitWsCredentials

async def main():
    secret_id = 'deeptrader/dev/11111111-1111-1111-1111-111111111111/bybit/fb213790-5ba6-4637-bccc-25e3d68d4c0c'
    
    creds = get_exchange_credentials(secret_id)
    if not creds:
        print("❌ Credentials not found!")
        return
    
    print(f"API Key: {creds.api_key[:8]}...")
    print(f"Secret Key: {creds.secret_key[:8]}...")
    print()
    
    # Test with demo=True (Bybit demo mode)
    print("=== Testing with DEMO=True ===")
    ws_creds = BybitWsCredentials(
        api_key=creds.api_key,
        secret_key=creds.secret_key,
        testnet=False,
        demo=True,
    )
    
    provider = BybitOrderUpdateProvider(ws_creds, market_type="perp")
    print(f"Endpoint: {provider._endpoint}")
    
    try:
        await provider._ensure_connection()
        if provider._ws:
            print("✅ WebSocket connected!")
            # Try to receive a message
            try:
                import json
                raw = await asyncio.wait_for(provider._ws.recv(), timeout=5.0)
                msg = json.loads(raw)
                print(f"Received: {msg}")
                if msg.get("op") == "auth":
                    if msg.get("success"):
                        print("✅ Authentication successful!")
                    else:
                        print(f"❌ Authentication failed: {msg.get('ret_msg')}")
            except asyncio.TimeoutError:
                print("⚠️ No message received within 5 seconds")
        else:
            print("❌ WebSocket connection failed")
    except Exception as e:
        print(f"❌ Error: {e}")
    finally:
        await provider._reset_connection()

if __name__ == "__main__":
    asyncio.run(main())
