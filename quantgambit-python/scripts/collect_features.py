"""Collect feature snapshots from Redis stream and persist to CSV.

Runs continuously, sampling at a configurable interval to reduce
autocorrelation. Designed to run in background to accumulate training data.

Usage:
    nohup python scripts/collect_features.py --output features_collected.csv --interval 10 &
"""
import argparse
import csv
import json
import os
import signal
import sys
import time

import redis

FEATURE_KEYS = [
    "symbol", "timestamp", "price", "spread_bps",
    "price_change_1s", "price_change_5s", "price_change_30s", "price_change_5m",
    "rotation_factor", "ema_spread_pct", "trend_strength",
    "atr_5m", "atr_5m_baseline", "vwap",
    "orderbook_imbalance", "orderflow_imbalance",
    "bid_depth_usd", "ask_depth_usd",
    "imb_1s", "imb_5s", "imb_30s",
    "trades_per_second", "buy_volume", "sell_volume",
    "position_in_value", "distance_to_poc_bps",
]

running = True

def _handle_signal(sig, frame):
    global running
    running = False

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="features_collected.csv")
    parser.add_argument("--interval", type=float, default=10.0,
                        help="Seconds between samples")
    parser.add_argument("--stream",
                        default="events:features:11111111-1111-1111-1111-111111111111:bf167763-fee1-4f11-ab9a-6fddadf125de")
    args = parser.parse_args()

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    r = redis.Redis(host="localhost", port=6379, decode_responses=True)

    file_exists = os.path.exists(args.output) and os.path.getsize(args.output) > 0
    f = open(args.output, "a", newline="")
    writer = csv.DictWriter(f, fieldnames=FEATURE_KEYS, extrasaction="ignore")
    if not file_exists:
        writer.writeheader()

    last_id = "$"
    count = 0
    last_sample_time = 0

    print(f"Collecting features every {args.interval}s -> {args.output}")

    while running:
        try:
            result = r.xread({args.stream: last_id}, count=100, block=int(args.interval * 1000))
        except redis.ConnectionError:
            time.sleep(1)
            continue

        if not result:
            continue

        for stream_name, entries in result:
            for entry_id, data in entries:
                last_id = entry_id
                now = time.time()
                if now - last_sample_time < args.interval:
                    continue

                try:
                    payload = json.loads(data.get("data", "{}"))
                    inner = payload.get("payload", {})
                    if isinstance(inner, str):
                        inner = json.loads(inner)
                    features = inner.get("features", {})
                    if not features or not features.get("price"):
                        continue

                    row = {k: features.get(k, "") for k in FEATURE_KEYS}
                    row["timestamp"] = payload.get("timestamp", now)
                    writer.writerow(row)
                    f.flush()
                    count += 1
                    last_sample_time = now

                    if count % 100 == 0:
                        print(f"  {count} samples collected ({features.get('symbol')} @ {features.get('price')})")
                except (json.JSONDecodeError, KeyError):
                    continue

    f.close()
    print(f"\nDone. {count} samples written to {args.output}")


if __name__ == "__main__":
    main()
