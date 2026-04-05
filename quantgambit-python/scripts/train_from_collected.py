"""Train a model from collected feature snapshots.

Labels features using trade_records from TimescaleDB for future price movement.
Designed to work with output from collect_features.py.

Usage:
    python scripts/train_from_collected.py --input features_collected.csv
"""
import argparse
import asyncio
import csv
import json
import os
import subprocess
import sys
from collections import Counter

import asyncpg
import numpy as np


# Features that actually have predictive value for 60-120s horizons.
# Removed: price (absolute, not predictive), trend_strength (duplicate of ema_spread_pct),
#          price_change_1s (77% zero at 5s sampling)
# Added: distance_to_poc_bps, position_in_value (collected but previously unused)
FEATURE_KEYS = [
    "spread_bps",
    "price_change_5s", "price_change_30s", "price_change_5m",
    "rotation_factor",
    "ema_spread_pct",
    "atr_5m",
    "orderbook_imbalance", "orderflow_imbalance",
    "bid_depth_usd", "ask_depth_usd",
    "imb_1s", "imb_5s", "imb_30s",
    "trades_per_second",
    "distance_to_poc_bps",
]


async def _label_with_trades(rows, pool, horizon_sec=120, tp_bps=8, sl_bps=8):
    """Label feature rows using trade_records for future price.
    
    Uses barrier method: first to hit TP or SL wins, else flat.
    Horizon and barriers tuned to match actual trade characteristics:
    - 120s horizon (matches max_hold_sec for scalp profiles)
    - 8 bps barriers (matches actual MFE/MAE from backtests)
    """
    symbols = list(set(r["symbol"] for r in rows))
    trade_cache = {}

    for sym in symbols:
        trades = await pool.fetch(
            "SELECT ts, price FROM trade_records WHERE symbol=$1 ORDER BY ts ASC",
            sym,
        )
        trade_cache[sym] = (
            np.array([r["ts"].timestamp() for r in trades]),
            np.array([float(r["price"]) for r in trades]),
        )
        print(f"  {sym}: {len(trades)} trades loaded for labeling")

    labeled = []
    for row in rows:
        sym = row["symbol"]
        if sym not in trade_cache:
            continue
        ts_arr, px_arr = trade_cache[sym]
        t0 = float(row["timestamp"])
        p0 = float(row.get("price", 0))
        if p0 <= 0:
            continue

        end_ts = t0 + horizon_sec
        idx = np.searchsorted(ts_arr, t0)
        end_idx = np.searchsorted(ts_arr, end_ts)

        if end_idx <= idx or end_idx - idx < 5:
            continue

        future = px_arr[idx:end_idx]
        tp_p = p0 * (1 + tp_bps / 10000)
        sl_p = p0 * (1 - sl_bps / 10000)

        label = "flat"
        for px in future:
            if px >= tp_p:
                label = "up"
                break
            if px <= sl_p:
                label = "down"
                break

        row_out = dict(row)
        row_out["label"] = label
        # Normalize depth features to log scale to reduce BTC/SOL magnitude gap
        for k in ("bid_depth_usd", "ask_depth_usd"):
            try:
                v = float(row_out.get(k, 0))
                row_out[k] = np.log1p(max(0, v))
            except (ValueError, TypeError):
                row_out[k] = 0
        # Handle non-numeric position_in_value
        piv = row_out.get("position_in_value", "")
        try:
            row_out["position_in_value"] = float(piv)
        except (ValueError, TypeError):
            row_out["position_in_value"] = 0.5  # default to mid-value
        labeled.append(row_out)

    return labeled


async def _run(args):
    with open(args.input, newline="") as f:
        rows = list(csv.DictReader(f))
    print(f"Loaded {len(rows)} feature snapshots from {args.input}")

    if len(rows) < args.min_samples:
        print(f"Need at least {args.min_samples} samples, have {len(rows)}. Keep collecting.")
        sys.exit(1)

    url = os.getenv("BOT_TIMESCALE_URL",
                     "postgresql://quantgambit:quantgambit_pw@localhost:5433/quantgambit_bot")
    pool = await asyncpg.create_pool(url, min_size=1, max_size=3)

    print(f"Labeling with {args.horizon_sec}s horizon, {args.tp_bps}/{args.sl_bps} bps barriers...")
    labeled = await _label_with_trades(
        rows, pool, args.horizon_sec, args.tp_bps, args.sl_bps)
    await pool.close()

    lc = Counter(r["label"] for r in labeled)
    print(f"Labeled: {len(labeled)} samples — {dict(lc)}")

    if len(labeled) < args.min_samples:
        print(f"Only {len(labeled)} labeled (need {args.min_samples}). Some may lack future trade data.")
        sys.exit(1)

    # Write labeled dataset
    output_csv = args.labeled_output
    fieldnames = ["symbol", "timestamp", "label"] + FEATURE_KEYS
    with open(output_csv, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(labeled)
    print(f"Wrote labeled dataset: {output_csv}")

    # Train
    train_cmd = [
        sys.executable, "scripts/train_prediction_baseline.py",
        "--input", output_csv,
        "--output", args.model_output,
        "--config", args.config_output,
        "--labels", "down,flat,up",
        "--split", "time",
        "--train-ratio", "0.75",
        "--class-weight", "balanced",
        "--n-estimators", "200",
        "--max-depth", "4",
        "--learning-rate", "0.03",
        "--num-leaves", "15",
        "--min-child-samples", "30",
        "--walk-forward-folds", "3",
        "--ev-cost-bps", "8.0",
        "--calibration-ratio", "0.2",
        "--critical-features", "orderbook_imbalance,orderflow_imbalance,price_change_5s,distance_to_poc_bps",
        "--prediction-contract", "future_return",
    ]
    print(f"\nTraining model...")
    result = subprocess.run(train_cmd, capture_output=True, text=True)
    print(result.stdout)
    if result.stderr:
        print(result.stderr)

    if result.returncode != 0:
        print("Training failed!")
        sys.exit(1)

    try:
        with open(args.config_output) as f:
            config = json.load(f)
        # Write calibration-critical metadata so calibration auto-detects correctly
        config["label_source"] = "future_return"
        config["horizon_sec"] = args.horizon_sec
        config["tp_bps"] = args.tp_bps
        config["sl_bps"] = args.sl_bps
        config["flat_threshold_bps"] = args.tp_bps
        with open(args.config_output, "w") as f:
            json.dump(config, f, indent=2)
        da = config.get("trading_metrics", {}).get("directional_accuracy", 0)
        wf = config.get("walk_forward", {})
        wf_da = wf.get("directional_f1_macro_mean", 0) if wf else 0
        ev = config.get("trading_metrics", {}).get("ev_after_costs_mean", 0)
        print(f"\n{'='*50}")
        print(f"Directional accuracy: {da:.1%}")
        print(f"Walk-forward F1 mean: {wf_da:.3f}")
        # Structured output for dashboard parsing
        print(f"metrics:directional_accuracy={da:.4f}")
        print(f"metrics:walk_forward_f1_mean={wf_da:.4f}")
        print(f"metrics:ev_after_costs_mean={ev:.4f}")
        if da >= 0.52:
            print(f"✓ Model passes 52% threshold — ready to deploy!")
            print(f"  ONNX: {args.model_output}")
            print(f"  Config: {args.config_output}")
            print(f"promotion_check:passed da={da:.4f}")
        else:
            print(f"✗ Model below 52% — keep collecting data or tune features.")
            print(f"promotion_blocked:da={da:.4f} below 0.52 threshold")
    except Exception as e:
        print(f"Could not read config: {e}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--input", default="features_collected.csv")
    p.add_argument("--labeled-output", default="features_labeled.csv")
    p.add_argument("--model-output", default="models/prediction_v4.onnx")
    p.add_argument("--config-output", default="models/prediction_v4.json")
    p.add_argument("--horizon-sec", type=float, default=120)
    p.add_argument("--tp-bps", type=float, default=8)
    p.add_argument("--sl-bps", type=float, default=8)
    p.add_argument("--min-samples", type=int, default=500)
    asyncio.run(_run(p.parse_args()))


if __name__ == "__main__":
    main()
