#!/usr/bin/env python3
"""
Compare primary predictions vs shadow predictions over recent feature snapshots.

This is evaluation-only. It does not place orders.

Example:
  ./venv/bin/python scripts/prediction_shadow_compare.py \
    --tenant-id ... --bot-id ... --count 1000
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
from collections import Counter, defaultdict
from typing import Any, Optional

import redis  # type: ignore


_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def _get_dir(pred: dict | None) -> Optional[str]:
    if not isinstance(pred, dict):
        return None
    d = pred.get("direction")
    if not d:
        return None
    return str(d)


def _get_conf(pred: dict | None) -> Optional[float]:
    if not isinstance(pred, dict):
        return None
    c = pred.get("confidence")
    if c is None:
        return None
    try:
        return float(c)
    except (TypeError, ValueError):
        return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--redis-url", default=os.getenv("REDIS_URL", "redis://localhost:6379"))
    ap.add_argument("--tenant-id", required=True)
    ap.add_argument("--bot-id", required=True)
    ap.add_argument("--count", type=int, default=1000)
    args = ap.parse_args()

    stream = f"events:features:{args.tenant_id}:{args.bot_id}"
    r = redis.from_url(args.redis_url, decode_responses=True)
    rows = r.xrevrange(stream, count=int(args.count))
    if not rows:
        print(json.dumps({"ok": False, "error": "no_feature_snapshots", "stream": stream}))
        return 2

    total = 0
    both_present = 0
    agree = 0
    disagree = 0
    primary_missing = 0
    shadow_missing = 0

    confusion: dict[str, Counter[str]] = defaultdict(Counter)  # primary_dir -> shadow_dir counts
    by_symbol = defaultdict(lambda: {
        "total": 0,
        "both_present": 0,
        "agree": 0,
        "disagree": 0,
        "primary_missing": 0,
        "shadow_missing": 0,
        "confusion": defaultdict(Counter),
        "primary_avg_conf_sum": 0.0,
        "primary_avg_conf_n": 0,
        "shadow_avg_conf_sum": 0.0,
        "shadow_avg_conf_n": 0,
    })

    primary_sources = Counter()
    shadow_sources = Counter()

    for _id, fields in rows:
        data = fields.get("data")
        if not data:
            continue
        event = json.loads(data)
        payload = event.get("payload") or {}
        sym = str(event.get("symbol") or payload.get("symbol") or "UNKNOWN")
        primary = payload.get("prediction")
        shadow = payload.get("prediction_shadow")

        total += 1
        by_symbol[sym]["total"] += 1

        if isinstance(primary, dict) and primary.get("source"):
            primary_sources[str(primary.get("source"))] += 1
        if isinstance(shadow, dict) and shadow.get("source"):
            shadow_sources[str(shadow.get("source"))] += 1

        pdir = _get_dir(primary)
        sdir = _get_dir(shadow)
        if pdir is None:
            primary_missing += 1
            by_symbol[sym]["primary_missing"] += 1
        if sdir is None:
            shadow_missing += 1
            by_symbol[sym]["shadow_missing"] += 1

        if pdir is None or sdir is None:
            continue

        both_present += 1
        by_symbol[sym]["both_present"] += 1

        confusion[pdir][sdir] += 1
        by_symbol[sym]["confusion"][pdir][sdir] += 1

        if pdir == sdir:
            agree += 1
            by_symbol[sym]["agree"] += 1
        else:
            disagree += 1
            by_symbol[sym]["disagree"] += 1

        pc = _get_conf(primary)
        if pc is not None:
            by_symbol[sym]["primary_avg_conf_sum"] += pc
            by_symbol[sym]["primary_avg_conf_n"] += 1
        sc = _get_conf(shadow)
        if sc is not None:
            by_symbol[sym]["shadow_avg_conf_sum"] += sc
            by_symbol[sym]["shadow_avg_conf_n"] += 1

    def _conf_to_dict(c: dict[str, Counter[str]]) -> dict[str, dict[str, int]]:
        return {k: dict(v) for k, v in c.items()}

    per_symbol_out: dict[str, Any] = {}
    for sym, stats in by_symbol.items():
        p_n = stats["primary_avg_conf_n"] or 0
        s_n = stats["shadow_avg_conf_n"] or 0
        per_symbol_out[sym] = {
            "total": stats["total"],
            "both_present": stats["both_present"],
            "agree": stats["agree"],
            "disagree": stats["disagree"],
            "agree_rate": (stats["agree"] / stats["both_present"]) if stats["both_present"] else None,
            "primary_missing": stats["primary_missing"],
            "shadow_missing": stats["shadow_missing"],
            "primary_avg_conf": (stats["primary_avg_conf_sum"] / p_n) if p_n else None,
            "shadow_avg_conf": (stats["shadow_avg_conf_sum"] / s_n) if s_n else None,
            "confusion": _conf_to_dict(stats["confusion"]),
        }

    out = {
        "ok": True,
        "stream": stream,
        "n_rows": len(rows),
        "total": total,
        "both_present": both_present,
        "agree": agree,
        "disagree": disagree,
        "agree_rate": (agree / both_present) if both_present else None,
        "primary_missing": primary_missing,
        "shadow_missing": shadow_missing,
        "primary_sources": dict(primary_sources),
        "shadow_sources": dict(shadow_sources),
        "confusion": _conf_to_dict(confusion),
        "per_symbol": dict(sorted(per_symbol_out.items(), key=lambda kv: kv[0])),
    }
    print(json.dumps(out, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

