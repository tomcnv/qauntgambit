#!/usr/bin/env python3
"""Check candle_stale and timeout issues"""
import redis
import json
import time

r = redis.from_url("redis://localhost:6379")

# Check warmup data for candle info
print("=== Warmup Data (candle info) ===")
for symbol in ["BTCUSDT", "ETHUSDT", "SOLUSDT"]:
    key = f"quantgambit:11111111-1111-1111-1111-111111111111:bf167763-fee1-4f11-ab9a-6fddadf125de:warmup:{symbol}"
    val = r.get(key)
    if val:
        data = json.loads(val)
        print(f"\n{symbol}:")
        css = data.get("candle_sync_state")
        cc = data.get("candle_count")
        print(f"  candle_sync_state: {css}")
        print(f"  candle_count: {cc}")
        latest_ts = data.get("latest_ts")
        if latest_ts:
            age = time.time() - latest_ts
            print(f"  latest_ts age: {age:.1f}s ago")

# Check the guardrail for timeout details
print("\n=== Latest Guardrail ===")
val = r.get("quantgambit:11111111-1111-1111-1111-111111111111:bf167763-fee1-4f11-ab9a-6fddadf125de:guardrail:latest")
if val:
    print(json.dumps(json.loads(val), indent=2))

# Check candle stream
print("\n=== Candle Stream Status ===")
candle_keys = list(r.keys("events:candles:*"))
for key in candle_keys[:2]:
    try:
        info = r.xinfo_stream(key)
        length = info.get("length")
        last_id = info.get("last-generated-id")
        print(f"{key.decode()}:")
        print(f"  length: {length}")
        print(f"  last-entry: {last_id}")
    except Exception as e:
        print(f"{key.decode()}: Error - {e}")

# Check feature stream for candle_age_sec
print("\n=== Feature Stream (candle_age_sec) ===")
stream_key = "events:features:11111111-1111-1111-1111-111111111111:bf167763-fee1-4f11-ab9a-6fddadf125de"
try:
    messages = r.xrevrange(stream_key, count=3)
    for msg_id, data in messages:
        if b'payload' in data:
            payload = json.loads(data[b'payload'])
            market_ctx = payload.get('market_context', {})
            symbol = payload.get('symbol')
            candle_age = market_ctx.get('candle_age_sec')
            candle_sync = market_ctx.get('candle_sync_state')
            feed_staleness = market_ctx.get('feed_staleness', {})
            candle_feed_stale = feed_staleness.get('candle')
            print(f"\n{symbol}:")
            print(f"  candle_age_sec: {candle_age}")
            print(f"  candle_sync_state: {candle_sync}")
            print(f"  feed_staleness.candle: {candle_feed_stale}")
except Exception as e:
    print(f"Error: {e}")

# Check decision stream for rejection reasons
print("\n=== Decision Stream (rejection reasons) ===")
decision_key = "events:decisions:11111111-1111-1111-1111-111111111111:bf167763-fee1-4f11-ab9a-6fddadf125de"
try:
    messages = r.xrevrange(decision_key, count=20)
    reasons = {}
    for msg_id, data in messages:
        if b'payload' in data:
            payload = json.loads(data[b'payload'])
            reason = payload.get('rejection_reason') or payload.get('reason')
            if reason:
                reasons[reason] = reasons.get(reason, 0) + 1
    print(f"Rejection reasons (last 20): {reasons}")
except Exception as e:
    print(f"Error: {e}")
