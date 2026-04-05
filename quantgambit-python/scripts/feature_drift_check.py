#!/usr/bin/env python3
"""Compare live feature stats vs model registry stats to detect drift."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import pathlib
import sys
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional

import asyncpg

import redis.asyncio as redis

_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from quantgambit.ingest.schemas import coerce_float
from quantgambit.storage.redis_snapshots import RedisSnapshotWriter
from quantgambit.storage.timescale import TimescaleWriter, TelemetryRow
from quantgambit.storage.redis_streams import decode_message


@dataclass
class DriftThresholds:
    zscore: float = 3.0
    std_ratio_high: float = 3.0
    std_ratio_low: float = 0.33


def _load_model_stats(path: str) -> dict:
    raw = json.loads(open(path, "r", encoding="utf-8").read())
    if not isinstance(raw, dict):
        raise SystemExit(f"invalid_model_config:{path}")
    stats = raw.get("feature_stats") or {}
    if not stats or "features" not in stats:
        raise SystemExit(f"missing_feature_stats:{path}")
    return raw


async def _load_feature_snapshots(
    redis_client,
    stream: str,
    limit: int,
) -> List[dict]:
    cursor = "-"
    remaining = limit
    rows: List[dict] = []
    while remaining > 0:
        count = min(1000, remaining)
        entries = await redis_client.xrange(stream, min=cursor, max="+", count=count)
        if not entries:
            break
        for entry_id, payload in entries:
            if cursor != "-" and entry_id == cursor:
                continue
            message = decode_message(payload)
            if message.get("event_type") != "feature_snapshot":
                continue
            snapshot = message.get("payload") or {}
            features = snapshot.get("features") or {}
            market_context = snapshot.get("market_context") or {}
            rows.append({"features": features, "market_context": market_context})
        cursor = entries[-1][0]
        remaining -= len(entries)
    return rows


def _extract_values(rows: Iterable[dict], feature_keys: List[str]) -> Dict[str, List[float]]:
    values: Dict[str, List[float]] = {key: [] for key in feature_keys}
    for row in rows:
        features = row.get("features") or {}
        market_context = row.get("market_context") or {}
        for key in feature_keys:
            value = coerce_float(features.get(key))
            if value is None:
                value = coerce_float(market_context.get(key))
            if value is not None:
                values[key].append(float(value))
    return values


def _compute_stats(values: Dict[str, List[float]]) -> Dict[str, dict]:
    stats: Dict[str, dict] = {}
    for key, items in values.items():
        if not items:
            stats[key] = {"count": 0}
            continue
        count = len(items)
        mean = sum(items) / count
        variance = sum((val - mean) ** 2 for val in items) / count
        std = variance ** 0.5
        stats[key] = {
            "count": count,
            "mean": mean,
            "std": std,
            "min": min(items),
            "max": max(items),
        }
    return stats


def _compare_stats(
    model_stats: Dict[str, dict],
    current_stats: Dict[str, dict],
    thresholds: DriftThresholds,
) -> Dict[str, dict]:
    drift: Dict[str, dict] = {}
    for key, baseline in model_stats.items():
        current = current_stats.get(key)
        if not current or not current.get("count"):
            drift[key] = {"status": "missing", "reason": "no_samples"}
            continue
        baseline_mean = baseline.get("mean") or 0.0
        baseline_std = baseline.get("std") or 0.0
        current_mean = current.get("mean") or 0.0
        current_std = current.get("std") or 0.0
        zscore = None
        if baseline_std > 0:
            zscore = (current_mean - baseline_mean) / baseline_std
        std_ratio = None
        if baseline_std > 0:
            std_ratio = current_std / baseline_std if baseline_std else None
        flagged = False
        reasons = []
        if zscore is not None and abs(zscore) >= thresholds.zscore:
            flagged = True
            reasons.append("mean_shift")
        if std_ratio is not None and (
            std_ratio >= thresholds.std_ratio_high or std_ratio <= thresholds.std_ratio_low
        ):
            flagged = True
            reasons.append("std_shift")
        drift[key] = {
            "status": "drift" if flagged else "ok",
            "zscore": zscore,
            "std_ratio": std_ratio,
            "reasons": reasons,
            "baseline": {"mean": baseline_mean, "std": baseline_std},
            "current": {"mean": current_mean, "std": current_std},
        }
    return drift


async def _run(args) -> None:
    config = _load_model_stats(args.model_config)
    feature_keys = config.get("feature_keys") or []
    if not feature_keys:
        raise SystemExit("missing_feature_keys")
    model_stats = config.get("feature_stats", {}).get("features") or {}
    thresholds = DriftThresholds(
        zscore=args.zscore,
        std_ratio_high=args.std_ratio_high,
        std_ratio_low=args.std_ratio_low,
    )
    redis_url = args.redis_url or os.getenv("BOT_REDIS_URL") or os.getenv("REDIS_URL", "redis://localhost:6379")
    redis_client = redis.from_url(redis_url)
    rows = await _load_feature_snapshots(redis_client, args.stream, args.limit)
    values = _extract_values(rows, feature_keys)
    current_stats = _compute_stats(values)
    drift = _compare_stats(model_stats, current_stats, thresholds)
    output = {
        "model_config": args.model_config,
        "stream": args.stream,
        "samples": sum(stat.get("count", 0) for stat in current_stats.values()),
        "thresholds": thresholds.__dict__,
        "drift": drift,
    }
    drift_keys = [key for key, item in drift.items() if item.get("status") == "drift"]
    status = "drift" if drift_keys else "ok"
    if args.write_snapshot:
        snapshot_key = args.snapshot_key
        if not snapshot_key:
            if args.tenant_id and args.bot_id:
                snapshot_key = f"quantgambit:{args.tenant_id}:{args.bot_id}:prediction:drift:latest"
            else:
                raise SystemExit("missing_snapshot_key")
        writer = RedisSnapshotWriter(redis_client, ttl_seconds=args.snapshot_ttl)
        await writer.write(
            snapshot_key,
            {
                "status": status,
                "drift_keys": drift_keys,
                "thresholds": thresholds.__dict__,
            },
        )
    if args.timescale_url:
        pool = await asyncpg.create_pool(args.timescale_url)
        writer = TimescaleWriter(pool)
        row = TelemetryRow(
            tenant_id=args.tenant_id or "unknown",
            bot_id=args.bot_id or "unknown",
            symbol=None,
            exchange=args.exchange,
            timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            payload={
                "type": "feature_drift",
                "status": status,
                "drift_keys": drift_keys,
                "thresholds": thresholds.__dict__,
            },
        )
        await writer.write("guardrail_events", row)
        await pool.close()
    await redis_client.aclose()
    if args.output:
        with open(args.output, "w", encoding="utf-8") as handle:
            json.dump(output, handle, indent=2, sort_keys=True)
    if drift_keys:
        print(f"drift:{','.join(drift_keys)}")
    else:
        print("drift:none")


def main() -> None:
    parser = argparse.ArgumentParser(description="Check feature drift against model stats.")
    parser.add_argument("--model-config", required=True, help="Path to model JSON config.")
    parser.add_argument("--stream", default="events:features", help="Feature stream name.")
    parser.add_argument("--limit", type=int, default=5000, help="Max stream entries to read.")
    parser.add_argument("--redis-url", default=None, help="Override Redis URL.")
    parser.add_argument("--zscore", type=float, default=3.0, help="Mean shift z-score threshold.")
    parser.add_argument("--std-ratio-high", type=float, default=3.0, help="Std ratio high threshold.")
    parser.add_argument("--std-ratio-low", type=float, default=0.33, help="Std ratio low threshold.")
    parser.add_argument("--output", default=None, help="Optional JSON output path.")
    parser.add_argument("--write-snapshot", action="store_true", help="Write drift status to Redis snapshot.")
    parser.add_argument("--snapshot-key", default=None, help="Redis snapshot key for drift status.")
    parser.add_argument("--tenant-id", default=None, help="Tenant id for snapshot key.")
    parser.add_argument("--bot-id", default=None, help="Bot id for snapshot key.")
    parser.add_argument("--exchange", default=None, help="Exchange for Timescale telemetry.")
    parser.add_argument("--snapshot-ttl", type=int, default=60, help="Snapshot TTL seconds.")
    parser.add_argument("--timescale-url", default=None, help="Timescale URL for guardrail telemetry.")
    args = parser.parse_args()
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
