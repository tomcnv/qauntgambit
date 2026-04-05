#!/usr/bin/env python3
"""Check decision pipeline status"""
import redis
import json
import time

r = redis.from_url("redis://localhost:6379", decode_responses=False)

# Check decision stream
print("=== Decision Stream ===")
decision_key = "events:decisions:11111111-1111-1111-1111-111111111111:bf167763-fee1-4f11-ab9a-6fddadf125de"
try:
    info = r.xinfo_stream(decision_key)
    print(f"Stream length: {info.get('length')}")
    print(f"Last entry ID: {info.get('last-generated-id')}")
    
    # Get last 10 messages
    messages = r.xrevrange(decision_key, count=10)
    print(f"\nLast {len(messages)} decisions:")
    for msg_id, data in messages:
        raw = data.get(b"data") or data.get("data")
        if not raw:
            continue
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        event = json.loads(raw)
        payload = event.get("payload", {})
        action = payload.get("action") or payload.get("decision") or "unknown"
        symbol = payload.get("symbol")
        side = payload.get("side")
        profile_id = payload.get("profile_id")
        pred_conf = payload.get("prediction_confidence")
        signal = payload.get("signal") or {}
        signal_side = signal.get("side")
        strategy_id = signal.get("strategy_id")
        reason = payload.get("rejection_reason") or payload.get("reason") or payload.get("skip_reason")
        print(
            f"  {symbol}: action={action}, side={side}, reason={reason}, "
            f"profile={profile_id}, pred_conf={pred_conf}, "
            f"signal_side={signal_side}, strategy={strategy_id}"
        )
except Exception as e:
    print(f"Error: {e}")

# Check feature stream
print("\n=== Feature Stream ===")
feature_key = "events:features:11111111-1111-1111-1111-111111111111:bf167763-fee1-4f11-ab9a-6fddadf125de"
try:
    info = r.xinfo_stream(feature_key)
    print(f"Stream length: {info.get('length')}")
    
    # Get last message
    messages = r.xrevrange(feature_key, count=1)
    for msg_id, data in messages:
        raw = data.get(b"data") or data.get("data")
        if not raw:
            continue
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        event = json.loads(raw)
        payload = event.get("payload", {})
        symbol = payload.get("symbol")
        market_ctx = payload.get("market_context", {})
        print(f"\nLatest feature for {symbol}:")
        print(f"  data_quality_score: {market_ctx.get('data_quality_score')}")
        print(f"  data_quality_status: {market_ctx.get('data_quality_status')}")
        print(f"  orderbook_sync_state: {market_ctx.get('orderbook_sync_state')}")
        print(f"  trade_sync_state: {market_ctx.get('trade_sync_state')}")
        print(f"  candle_sync_state: {market_ctx.get('candle_sync_state')}")
        print(f"  prediction_blocked: {market_ctx.get('prediction_blocked')}")
except Exception as e:
    print(f"Error: {e}")

# Check risk stream
print("\n=== Risk Decisions Stream ===")
risk_key = "events:risk_decisions:11111111-1111-1111-1111-111111111111:bf167763-fee1-4f11-ab9a-6fddadf125de"
try:
    info = r.xinfo_stream(risk_key)
    print(f"Stream length: {info.get('length')}")
    
    messages = r.xrevrange(risk_key, count=5)
    print(f"\nLast {len(messages)} risk decisions:")
    for msg_id, data in messages:
        raw = data.get(b"data") or data.get("data")
        if not raw:
            continue
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        event = json.loads(raw)
        payload = event.get("payload", {})
        action = payload.get("action") or payload.get("decision")
        symbol = payload.get("symbol")
        reason = payload.get("rejection_reason") or payload.get("reason")
        print(f"  {symbol}: action={action}, reason={reason}")
except Exception as e:
    print(f"Error: {e}")

# Check for any blocking conditions
print("\n=== Blocking Conditions ===")
# Kill switch
ks_key = "quantgambit:11111111-1111-1111-1111-111111111111:bf167763-fee1-4f11-ab9a-6fddadf125de:kill_switch"
val = r.get(ks_key)
if val:
    print(f"Kill switch: {val.decode()}")
else:
    print("Kill switch: not set")

# Shadow mode
print("\nChecking for shadow mode or other blocks...")
