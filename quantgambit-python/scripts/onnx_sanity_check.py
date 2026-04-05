#!/usr/bin/env python3
"""
ONNX sanity check against recent live feature snapshots.

This does NOT place orders. It only:
1) loads an ONNX model (+ metadata feature_keys/class_labels)
2) pulls the last N feature snapshots from Redis
3) runs inference and reports distribution + basic validity checks

Typical usage:
  ./venv/bin/python scripts/onnx_sanity_check.py \
    --tenant-id ... --bot-id ... --count 200
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
from collections import Counter, defaultdict
from typing import Any

import redis  # type: ignore

# Allow running as a script without installing the package.
_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from quantgambit.signals.prediction_providers import OnnxPredictionProvider


def _load_model_meta(path: str) -> dict[str, Any]:
    meta = json.loads(pathlib.Path(path).read_text())
    feature_keys = meta.get("feature_keys") or []
    class_labels = meta.get("class_labels") or ["down", "flat", "up"]
    if not isinstance(feature_keys, list) or not feature_keys:
        raise ValueError(f"invalid meta.feature_keys in {path}")
    if not isinstance(class_labels, list) or not class_labels:
        raise ValueError(f"invalid meta.class_labels in {path}")
    return {
        "feature_keys": feature_keys,
        "class_labels": class_labels,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--redis-url", default=os.getenv("REDIS_URL", "redis://localhost:6379"))
    ap.add_argument("--tenant-id", required=True)
    ap.add_argument("--bot-id", required=True)
    ap.add_argument("--count", type=int, default=200)
    ap.add_argument(
        "--model-path",
        default=str(pathlib.Path("models/registry/latest.onnx")),
        help="Path to ONNX model (relative to quantgambit-python/).",
    )
    ap.add_argument(
        "--model-meta",
        default=str(pathlib.Path("models/registry/latest.json")),
        help="Path to model metadata JSON with feature_keys/class_labels.",
    )
    args = ap.parse_args()

    stream = f"events:features:{args.tenant_id}:{args.bot_id}"
    r = redis.from_url(args.redis_url, decode_responses=True)
    rows = r.xrevrange(stream, count=int(args.count))
    if not rows:
        print(json.dumps({"ok": False, "error": "no_feature_snapshots", "stream": stream}))
        return 2

    meta = _load_model_meta(args.model_meta)
    provider = OnnxPredictionProvider(
        model_path=args.model_path,
        feature_keys=[str(x) for x in meta["feature_keys"]],
        class_labels=[str(x) for x in meta["class_labels"]],
        refresh_interval_sec=0.0,
    )

    direction_counts: Counter[str] = Counter()
    symbol_dir_counts: dict[str, Counter[str]] = defaultdict(Counter)
    conf_sum: Counter[str] = Counter()
    probs_sum_off: int = 0
    invalid_prob: int = 0
    total: int = 0
    compare_existing_source: Counter[str] = Counter()

    for _id, fields in rows:
        data = fields.get("data")
        if not data:
            continue
        event = json.loads(data)
        payload = event.get("payload") or {}
        features = payload.get("features") or {}
        market_context = payload.get("market_context") or {}
        ts = payload.get("timestamp") or event.get("timestamp") or 0.0
        try:
            ts_f = float(ts)
        except (TypeError, ValueError):
            ts_f = 0.0

        pred = provider.build_prediction(features, market_context, timestamp=ts_f)
        if not pred:
            continue

        total += 1
        sym = str(event.get("symbol") or payload.get("symbol") or "UNKNOWN")
        direction = str(pred.get("direction") or "unknown")
        conf = float(pred.get("confidence") or 0.0)

        direction_counts[direction] += 1
        symbol_dir_counts[sym][direction] += 1
        conf_sum[direction] += conf

        probs = pred.get("probs") or {}
        if probs:
            try:
                s = float(sum(float(v) for v in probs.values()))
            except Exception:
                invalid_prob += 1
            else:
                # Not all models output calibrated probabilities, but gross violations are useful to flag.
                if not (0.95 <= s <= 1.05):
                    probs_sum_off += 1

        existing = payload.get("prediction") or {}
        if isinstance(existing, dict):
            src = existing.get("source")
            if src:
                compare_existing_source[str(src)] += 1

    if total == 0:
        print(json.dumps({"ok": False, "error": "no_parsable_predictions", "stream": stream}))
        return 3

    avg_conf = {k: (conf_sum[k] / direction_counts[k]) for k in direction_counts}
    result = {
        "ok": True,
        "stream": stream,
        "n_rows": len(rows),
        "n_predictions": total,
        "direction_counts": dict(direction_counts),
        "avg_conf_by_direction": avg_conf,
        "per_symbol_direction_counts": {k: dict(v) for k, v in symbol_dir_counts.items()},
        "prob_sum_out_of_range_count": probs_sum_off,
        "invalid_prob_count": invalid_prob,
        "existing_prediction_sources_seen": dict(compare_existing_source),
        "model_path": args.model_path,
        "model_meta": args.model_meta,
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
