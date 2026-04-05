#!/usr/bin/env python3
"""Diagnostic script to verify position exit logic is working.

Run this to check:
1. Are positions being tracked correctly?
2. Are exit conditions being evaluated?
3. Why aren't exits triggering?

Usage:
    python scripts/diagnose_exits.py --redis-url redis://localhost:6379 --tenant-id t1 --bot-id b1
    
Or enable runtime tracing:
    POSITION_EXIT_TRACE=1 python -m quantgambit.runtime.cli start ...
"""

import asyncio
import argparse
import json
import sys
from datetime import datetime

try:
    import redis.asyncio as aioredis
except ImportError:
    print("ERROR: redis package not installed. Run: pip install redis")
    sys.exit(1)


async def get_redis_client(url: str):
    return await aioredis.from_url(url)


async def check_positions(redis_client, tenant_id: str, bot_id: str):
    """Check what positions are stored in Redis."""
    print("\n" + "="*60)
    print("POSITIONS STATUS")
    print("="*60)
    
    # Check position snapshots
    patterns = [
        f"quantgambit:{tenant_id}:{bot_id}:position:*",
        f"quantgambit:{tenant_id}:{bot_id}:positions:*",
    ]
    
    for pattern in patterns:
        keys = []
        async for key in redis_client.scan_iter(match=pattern):
            keys.append(key)
        
        if keys:
            print(f"\nFound {len(keys)} keys matching {pattern}:")
            for key in keys[:10]:
                data = await redis_client.get(key)
                if data:
                    try:
                        parsed = json.loads(data)
                        print(f"  {key}: {json.dumps(parsed, indent=2)[:200]}...")
                    except:
                        print(f"  {key}: (raw) {data[:100]}...")
    
    # Check latest positions snapshot
    latest_key = f"quantgambit:{tenant_id}:{bot_id}:positions:latest"
    data = await redis_client.get(latest_key)
    if data:
        try:
            parsed = json.loads(data)
            print(f"\n📊 Latest positions snapshot:")
            print(json.dumps(parsed, indent=2))
        except:
            pass


async def check_decisions(redis_client, tenant_id: str, bot_id: str):
    """Check recent decisions from the stream."""
    print("\n" + "="*60)
    print("RECENT DECISIONS")
    print("="*60)
    
    stream = f"events:decisions:{tenant_id}:{bot_id}"
    try:
        entries = await redis_client.xrevrange(stream, count=10)
        if not entries:
            print(f"⚠️  No decisions found in stream: {stream}")
            return
        
        print(f"Found {len(entries)} recent decisions:")
        for msg_id, data in entries:
            try:
                payload = json.loads(data.get(b"data", b"{}"))
                decision = payload.get("payload", {})
                print(f"\n  [{msg_id.decode()}]")
                print(f"    Symbol: {decision.get('symbol')}")
                print(f"    Decision: {decision.get('decision')}")
                print(f"    Rejection: {decision.get('rejection_reason')}")
                signal = decision.get("signal")
                if signal:
                    print(f"    Signal side: {signal.get('side')}")
                    print(f"    Signal type: {signal.get('signal_type')}")
                    print(f"    Is exit: {signal.get('is_exit_signal')}")
                    print(f"    Meta reason: {signal.get('meta_reason')}")
            except Exception as e:
                print(f"    Error parsing: {e}")
    except Exception as e:
        print(f"⚠️  Error reading stream: {e}")


async def check_risk_decisions(redis_client, tenant_id: str, bot_id: str):
    """Check recent risk decisions."""
    print("\n" + "="*60)
    print("RECENT RISK DECISIONS")
    print("="*60)
    
    stream = f"events:risk_decisions:{tenant_id}:{bot_id}"
    try:
        entries = await redis_client.xrevrange(stream, count=10)
        if not entries:
            print(f"⚠️  No risk decisions found in stream: {stream}")
            return
        
        print(f"Found {len(entries)} recent risk decisions:")
        for msg_id, data in entries:
            try:
                payload = json.loads(data.get(b"data", b"{}"))
                decision = payload.get("payload", {})
                print(f"\n  [{msg_id.decode()}]")
                print(f"    Symbol: {decision.get('symbol')}")
                print(f"    Status: {decision.get('status')}")
                print(f"    Exit passthrough: {decision.get('exit_passthrough')}")
                signal = decision.get("signal")
                if signal:
                    print(f"    Signal: {signal.get('side')} {signal.get('signal_type')}")
                    print(f"    Reduce only: {signal.get('reduce_only')}")
            except Exception as e:
                print(f"    Error parsing: {e}")
    except Exception as e:
        print(f"⚠️  Error reading stream: {e}")


async def check_warmup(redis_client, tenant_id: str, bot_id: str):
    """Check warmup status."""
    print("\n" + "="*60)
    print("WARMUP STATUS")
    print("="*60)
    
    pattern = f"quantgambit:{tenant_id}:{bot_id}:warmup:*"
    async for key in redis_client.scan_iter(match=pattern):
        data = await redis_client.get(key)
        if data:
            try:
                parsed = json.loads(data)
                symbol = parsed.get("symbol", "?")
                ready = parsed.get("ready", False)
                reasons = parsed.get("reasons", [])
                print(f"  {symbol}: {'✅ READY' if ready else '⏳ WARMING'} {reasons}")
            except:
                pass


async def simulate_exit_evaluation(market_context: dict, position: dict):
    """Simulate exit evaluation logic to show what would trigger."""
    print("\n" + "="*60)
    print("EXIT EVALUATION SIMULATION")
    print("="*60)
    
    side = position.get("side", "").lower()
    entry_price = float(position.get("entry_price", 0) or 0)
    current_price = float(market_context.get("price", 0) or 0)
    opened_at = position.get("opened_at")
    
    if not side or not entry_price or not current_price:
        print("❌ Missing required data (side, entry_price, or current_price)")
        return
    
    # Calculate PnL
    if side == "long":
        pnl_pct = (current_price - entry_price) / entry_price * 100
    else:
        pnl_pct = (entry_price - current_price) / entry_price * 100
    
    print(f"\n📊 Position Analysis:")
    print(f"  Side: {side}")
    print(f"  Entry: {entry_price}")
    print(f"  Current: {current_price}")
    print(f"  P&L: {pnl_pct:.2f}%")
    
    underwater_threshold = -1.0
    is_underwater = pnl_pct < underwater_threshold
    print(f"  Underwater (< {underwater_threshold}%): {'YES ⚠️' if is_underwater else 'NO'}")
    
    confirmations = []
    
    # Check each exit condition
    print(f"\n🔍 Exit Conditions Check:")
    
    # 1. Trend reversal
    trend_bias = market_context.get("trend_bias") or market_context.get("trend_direction")
    if trend_bias == "down":
        trend_bias = "short"
    elif trend_bias == "up":
        trend_bias = "long"
    trend_confidence = market_context.get("trend_confidence") or market_context.get("trend_strength", 0)
    if isinstance(trend_confidence, (int, float)) and trend_confidence < 1.0:
        trend_confidence = abs(trend_confidence) * 100  # Normalize
    
    print(f"  1. Trend Reversal: bias={trend_bias}, conf={trend_confidence}")
    if side == "long" and trend_bias == "short" and trend_confidence >= 0.3:
        confirmations.append("trend_reversal_short")
    elif side == "short" and trend_bias == "long" and trend_confidence >= 0.3:
        confirmations.append("trend_reversal_long")
    
    # 2. Orderflow
    orderflow = market_context.get("orderflow_imbalance", 0)
    print(f"  2. Orderflow Reversal: imbalance={orderflow}")
    if side == "long" and orderflow < -0.3:
        confirmations.append("orderflow_sell_pressure")
    elif side == "short" and orderflow > 0.3:
        confirmations.append("orderflow_buy_pressure")
    
    # 3-4. Price levels and volatility
    volatility_regime = market_context.get("volatility_regime")
    atr_ratio = market_context.get("atr_ratio", 1.0)
    print(f"  3-4. Volatility: regime={volatility_regime}, atr_ratio={atr_ratio}")
    
    # 5. Underwater with adverse
    print(f"  5. Underwater + Adverse: underwater={is_underwater}")
    if is_underwater:
        if side == "long" and (trend_bias == "short" or orderflow < -0.15):
            confirmations.append("underwater_adverse")
        elif side == "short" and (trend_bias == "long" or orderflow > 0.15):
            confirmations.append("underwater_adverse")
    
    # 6. Max hold time
    import time
    if opened_at:
        hold_time = time.time() - opened_at
        print(f"  6. Max Hold Time: {hold_time/3600:.1f}h (threshold: 1h)")
        if is_underwater and hold_time >= 3600:
            confirmations.append("max_underwater_hold")
    
    # 7. Risk mode
    risk_mode = market_context.get("risk_mode")
    print(f"  7. Risk Mode: {risk_mode}")
    if risk_mode == "conservative" and is_underwater:
        confirmations.append("conservative_mode")
    
    # 8. Deep underwater
    deep_threshold = underwater_threshold * 3
    print(f"  8. Deep Underwater (< {deep_threshold}%): {pnl_pct:.2f}%")
    if pnl_pct < deep_threshold:
        confirmations.append("deeply_underwater")
    
    print(f"\n📋 Confirmations Found: {len(confirmations)}")
    for c in confirmations:
        print(f"  ✅ {c}")
    
    if len(confirmations) >= 1:
        print(f"\n🚀 EXIT WOULD BE TRIGGERED!")
    else:
        print(f"\n⏸️  Exit NOT triggered (need at least 1 confirmation)")


async def main():
    parser = argparse.ArgumentParser(description="Diagnose position exit logic")
    parser.add_argument("--redis-url", default="redis://localhost:6379", help="Redis URL")
    parser.add_argument("--tenant-id", default="t1", help="Tenant ID")
    parser.add_argument("--bot-id", default="b1", help="Bot ID")
    args = parser.parse_args()
    
    print(f"🔍 Diagnosing exit logic for tenant={args.tenant_id}, bot={args.bot_id}")
    print(f"   Redis: {args.redis_url}")
    
    try:
        redis_client = await get_redis_client(args.redis_url)
    except Exception as e:
        print(f"❌ Failed to connect to Redis: {e}")
        sys.exit(1)
    
    await check_positions(redis_client, args.tenant_id, args.bot_id)
    await check_warmup(redis_client, args.tenant_id, args.bot_id)
    await check_decisions(redis_client, args.tenant_id, args.bot_id)
    await check_risk_decisions(redis_client, args.tenant_id, args.bot_id)
    
    print("\n" + "="*60)
    print("RECOMMENDATIONS")
    print("="*60)
    print("""
To enable detailed exit tracing, set these environment variables:

    export POSITION_EXIT_TRACE=1
    export DECISION_GATE_TRACE_VERBOSE=1

Then restart your runtime. You'll see logs like:
- position_eval_found: When a position is found for exit evaluation
- position_exit_not_triggered: Why an exit didn't trigger (with all values)
- position_exit_signal_generated: When an exit signal IS generated

If exits are still not working, check:
1. Is state_manager being passed to DecisionWorker? (check runtime logs)
2. Are positions being restored from exchange on startup?
3. Is the symbol format matching between positions and market data?
""")
    
    await redis_client.close()


if __name__ == "__main__":
    asyncio.run(main())
