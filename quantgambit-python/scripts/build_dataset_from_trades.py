"""Build a prediction dataset from trade_records in TimescaleDB.

Constructs features from raw trade ticks, labels using triple-barrier or
signed-return method. Filters out data gaps automatically.

Usage:
    python scripts/build_dataset_from_trades.py --output prediction_dataset_v3.csv
"""
import argparse
import asyncio
import csv
import math
import os
from collections import Counter

import asyncpg
import numpy as np


async def _fetch_trades(pool, symbol: str, limit: int = 2_000_000):
    rows = await pool.fetch(
        "SELECT ts, price, size, side FROM trade_records "
        "WHERE symbol=$1 ORDER BY ts ASC LIMIT $2",
        symbol, limit,
    )
    return [
        {"ts": r["ts"].timestamp(), "price": float(r["price"]),
         "size": float(r["size"]), "side": r["side"]}
        for r in rows
    ]


def _split_continuous_segments(trades, max_gap_sec=60):
    """Split trades into continuous segments, breaking at gaps > max_gap_sec."""
    if not trades:
        return []
    segments = []
    current = [trades[0]]
    for t in trades[1:]:
        if t["ts"] - current[-1]["ts"] > max_gap_sec:
            if len(current) > 100:
                segments.append(current)
            current = []
        current.append(t)
    if len(current) > 100:
        segments.append(current)
    return segments


def _ema(values, span):
    alpha = 2.0 / (span + 1)
    out = [values[0]]
    for v in values[1:]:
        out.append(alpha * v + (1 - alpha) * out[-1])
    return out


def _build_features(trades, sample_interval_sec=15.0, warmup_sec=600):
    """Build feature rows from a continuous segment of trades."""
    if len(trades) < 200:
        return [], [], []

    prices = np.array([t["price"] for t in trades])
    timestamps = np.array([t["ts"] for t in trades])
    sizes = np.array([t["size"] for t in trades])
    sides = [t["side"] for t in trades]

    t_start = timestamps[0] + warmup_sec
    t_end = timestamps[-1]
    if t_start >= t_end:
        return [], [], []

    sample_times = np.arange(t_start, t_end, sample_interval_sec)
    ema_fast_raw = np.array(_ema(prices.tolist(), 50))
    ema_slow_raw = np.array(_ema(prices.tolist(), 200))

    rows = []
    idx = 0
    for st in sample_times:
        while idx < len(timestamps) - 1 and timestamps[idx + 1] <= st:
            idx += 1
        if idx < 50:
            continue

        price = prices[idx]
        if price <= 0:
            continue

        def _price_at(sec):
            target = st - sec
            j = idx
            while j > 0 and timestamps[j] > target:
                j -= 1
            return prices[j]

        p_1s, p_5s, p_30s, p_5m = _price_at(1), _price_at(5), _price_at(30), _price_at(300)

        ema_fast = ema_fast_raw[idx]
        ema_slow = ema_slow_raw[idx]

        # Order flow in last ~30s
        flow_start = max(0, idx - 200)
        t_30s = st - 30
        buy_vol = sum(sizes[j] for j in range(flow_start, idx + 1) if timestamps[j] >= t_30s and sides[j].lower() == "buy")
        sell_vol = sum(sizes[j] for j in range(flow_start, idx + 1) if timestamps[j] >= t_30s and sides[j].lower() == "sell")
        total_flow = buy_vol + sell_vol

        # Volatility
        lb = max(0, idx - 300)
        wp = prices[lb:idx + 1]
        if len(wp) > 10:
            lr = np.diff(np.log(wp))
            realized_vol = float(np.std(lr)) * math.sqrt(len(lr))
        else:
            realized_vol = 0

        # VWAP
        vwap_lb = max(0, idx - 600)
        vp, vs = prices[vwap_lb:idx + 1], sizes[vwap_lb:idx + 1]
        tv = np.sum(vs)
        vwap = float(np.sum(vp * vs) / tv) if tv > 0 else price

        # Trade intensity
        trades_30s = sum(1 for j in range(flow_start, idx + 1) if timestamps[j] >= t_30s)

        # ATR
        atr_5m = float(np.mean(np.abs(np.diff(wp) / wp[:-1]))) * price if len(wp) > 1 else 0

        pc_5s_val = (price - p_5s) / p_5s if p_5s else 0
        pc_30s_val = (price - p_30s) / p_30s if p_30s else 0
        rotation_factor = pc_5s_val / pc_30s_val if abs(pc_30s_val) > abs(pc_5s_val) * 0.01 else 0.0
        rotation_factor = max(-5.0, min(5.0, rotation_factor))

        rows.append({
            "timestamp": st,
            "price": price,
            "spread_bps": 0.5,
            "price_change_1s": (price - p_1s) / p_1s if p_1s else 0,
            "price_change_5s": pc_5s_val,
            "price_change_30s": pc_30s_val,
            "price_change_5m": (price - p_5m) / p_5m if p_5m else 0,
            "rotation_factor": rotation_factor,
            "ema_spread_pct": (ema_fast - ema_slow) / ema_slow if ema_slow else 0,
            "trend_strength": (ema_fast - ema_slow) / ema_slow if ema_slow else 0,
            "atr_5m": atr_5m,
            "vwap": vwap,
            "orderflow_imbalance": (buy_vol - sell_vol) / total_flow if total_flow > 0 else 0,
            "trades_per_second": trades_30s / 30.0,
        })

    return rows, prices, timestamps


def _label_rows(rows, prices, timestamps, horizon_sec, tp_bps, sl_bps, label_mode):
    """Label feature rows using triple-barrier or signed-return."""
    labeled = []
    pidx = 0
    for row in rows:
        t0, p0 = row["timestamp"], row["price"]
        if p0 <= 0:
            continue
        end_ts = t0 + horizon_sec

        while pidx < len(timestamps) - 1 and timestamps[pidx] < t0:
            pidx += 1

        # Check we have data through the horizon
        j = pidx
        while j < len(timestamps) and timestamps[j] <= end_ts:
            j += 1
        if j == pidx:
            continue
        last_ts = timestamps[min(j - 1, len(timestamps) - 1)]
        if last_ts < t0 + horizon_sec * 0.8:
            continue  # Not enough future data

        if label_mode == "triple_barrier":
            tp_p = p0 * (1 + tp_bps / 10000)
            sl_p = p0 * (1 - sl_bps / 10000)
            label = "flat"
            k = pidx
            while k < len(timestamps) and timestamps[k] <= end_ts:
                if prices[k] >= tp_p:
                    label = "up"; break
                if prices[k] <= sl_p:
                    label = "down"; break
                k += 1
        else:  # signed_return
            last_p = prices[min(j - 1, len(prices) - 1)]
            ret_bps = (last_p - p0) / p0 * 10000
            if ret_bps > tp_bps:
                label = "up"
            elif ret_bps < -sl_bps:
                label = "down"
            else:
                label = "flat"

        row_out = dict(row)
        row_out["label"] = label
        labeled.append(row_out)
    return labeled


async def _run(args):
    url = os.getenv("BOT_TIMESCALE_URL",
                     "postgresql://quantgambit:quantgambit_pw@localhost:5433/quantgambit_bot")
    pool = await asyncpg.create_pool(url, min_size=1, max_size=3)

    symbols = [s.strip() for s in args.symbols.split(",")]
    all_rows = []

    for symbol in symbols:
        print(f"Fetching trades for {symbol}...")
        trades = await _fetch_trades(pool, symbol, limit=args.max_trades)
        print(f"  {len(trades)} trades loaded")
        if len(trades) < 1000:
            print(f"  Skipping: insufficient"); continue

        segments = _split_continuous_segments(trades, max_gap_sec=60)
        print(f"  {len(segments)} continuous segments")
        for i, seg in enumerate(segments):
            dur = (seg[-1]["ts"] - seg[0]["ts"]) / 3600
            print(f"    seg {i}: {len(seg)} trades, {dur:.1f}h")

        for seg in segments:
            dur = seg[-1]["ts"] - seg[0]["ts"]
            if dur < 1800:  # skip segments < 30 min
                continue
            feat_rows, prices, timestamps = _build_features(
                seg, sample_interval_sec=args.sample_interval)
            if not feat_rows:
                continue
            labeled = _label_rows(
                feat_rows, prices, timestamps,
                args.horizon_sec, args.tp_bps, args.sl_bps, args.label_mode)
            for r in labeled:
                r["symbol"] = symbol
            all_rows.extend(labeled)

        lc = Counter(r["label"] for r in all_rows if r.get("symbol") == symbol)
        print(f"  Labels: {dict(lc)}")

    await pool.close()

    if not all_rows:
        print("No data exported"); return

    feature_keys = [
        "price", "spread_bps", "price_change_1s", "price_change_5s",
        "price_change_30s", "price_change_5m", "rotation_factor",
        "ema_spread_pct", "trend_strength", "atr_5m", "vwap",
        "orderflow_imbalance", "trades_per_second",
    ]
    fieldnames = ["symbol", "timestamp", "label"] + feature_keys

    with open(args.output, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(all_rows)

    total = Counter(r["label"] for r in all_rows)
    print(f"\nTotal: {len(all_rows)} samples -> {args.output}")
    for l, c in sorted(total.items()):
        print(f"  {l}: {c} ({c/len(all_rows)*100:.1f}%)")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--output", default="prediction_dataset_v3.csv")
    p.add_argument("--symbols", default="BTCUSDT,ETHUSDT,SOLUSDT")
    p.add_argument("--max-trades", type=int, default=2_000_000)
    p.add_argument("--sample-interval", type=float, default=15.0)
    p.add_argument("--horizon-sec", type=float, default=300.0)
    p.add_argument("--tp-bps", type=float, default=5.0)
    p.add_argument("--sl-bps", type=float, default=5.0)
    p.add_argument("--label-mode", choices=["triple_barrier", "signed_return"],
                   default="triple_barrier")
    asyncio.run(_run(p.parse_args()))


if __name__ == "__main__":
    main()
