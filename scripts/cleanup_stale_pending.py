#!/usr/bin/env python3
"""Clean stale Redis stream pending entries for scoped runtime consumer groups.

Default behavior is dry-run. Use --apply to ACK stale pending IDs.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from dataclasses import dataclass
from typing import Iterable

import redis


@dataclass(frozen=True)
class StreamGroup:
    stream: str
    group: str


def _chunked(items: list[str], size: int) -> Iterable[list[str]]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


def _build_default_targets(tenant_id: str, bot_id: str) -> list[StreamGroup]:
    return [
        StreamGroup(
            stream=f"events:features:{tenant_id}:{bot_id}",
            group=f"quantgambit_decisions:{tenant_id}:{bot_id}",
        ),
        StreamGroup(
            stream=f"events:decisions:{tenant_id}:{bot_id}",
            group=f"quantgambit_risk:{tenant_id}:{bot_id}",
        ),
        StreamGroup(
            stream=f"events:risk_decisions:{tenant_id}:{bot_id}",
            group=f"quantgambit_execution:{tenant_id}:{bot_id}",
        ),
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description="Clean stale Redis stream pending entries")
    parser.add_argument("--tenant-id", default=os.getenv("TENANT_ID", ""))
    parser.add_argument("--bot-id", default=os.getenv("BOT_ID", ""))
    parser.add_argument("--redis-url", default=os.getenv("REDIS_URL", "redis://localhost:6379"))
    parser.add_argument(
        "--min-idle-sec",
        type=int,
        default=int(os.getenv("STALE_PENDING_MIN_IDLE_SEC", "21600")),
        help="Minimum idle time in seconds to treat pending message as stale (default: 6h)",
    )
    parser.add_argument(
        "--scan-batch",
        type=int,
        default=500,
        help="Max pending entries to fetch per XPENDING range batch",
    )
    parser.add_argument(
        "--max-scan",
        type=int,
        default=20000,
        help="Maximum pending entries to scan per stream/group",
    )
    parser.add_argument(
        "--ack-batch",
        type=int,
        default=500,
        help="Max IDs per XACK call when applying cleanup",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply cleanup by ACKing stale pending IDs. Default is dry-run.",
    )
    parser.add_argument(
        "--loop",
        action="store_true",
        help="Run continuously using --interval-sec between passes.",
    )
    parser.add_argument(
        "--interval-sec",
        type=int,
        default=int(os.getenv("STALE_PENDING_INTERVAL_SEC", "600")),
        help="Loop interval seconds when --loop is enabled (default: 600).",
    )
    args = parser.parse_args()

    if not args.tenant_id or not args.bot_id:
        raise SystemExit("tenant_id and bot_id are required (or set TENANT_ID/BOT_ID)")

    client = redis.Redis.from_url(args.redis_url, decode_responses=True)
    min_idle_ms = args.min_idle_sec * 1000
    targets = _build_default_targets(args.tenant_id, args.bot_id)

    def _run_pass() -> dict[str, object]:
        report: dict[str, object] = {
            "apply": bool(args.apply),
            "minIdleSec": args.min_idle_sec,
            "timestamp": int(time.time()),
            "targets": [],
        }
        for target in targets:
            target_report = {
                "stream": target.stream,
                "group": target.group,
                "pendingTotal": 0,
                "staleCount": 0,
                "acked": 0,
                "status": "ok",
                "error": None,
            }
            try:
                summary = client.execute_command("XPENDING", target.stream, target.group)
                if isinstance(summary, (list, tuple)) and summary:
                    pending_total = int(summary[0] or 0)
                elif isinstance(summary, dict):
                    pending_total = int(summary.get("pending", 0))
                else:
                    pending_total = 0
                target_report["pendingTotal"] = pending_total
                if pending_total <= 0:
                    report["targets"].append(target_report)
                    continue

                stale_ids: list[str] = []
                scanned = 0
                start = "-"
                while scanned < max(1, args.max_scan):
                    rows = client.xpending_range(
                        target.stream,
                        target.group,
                        start,
                        "+",
                        min(args.scan_batch, max(1, args.max_scan - scanned)),
                    )
                    if not rows:
                        break
                    for row in rows:
                        if isinstance(row, dict):
                            message_id = str(row.get("message_id") or "")
                            idle_ms = int(row.get("time_since_delivered") or 0)
                        else:
                            message_id = str(row[0])
                            idle_ms = int(row[2])
                        if not message_id:
                            continue
                        scanned += 1
                        start = f"({message_id}"
                        if idle_ms >= min_idle_ms:
                            stale_ids.append(message_id)
                        if scanned >= args.max_scan:
                            break

                target_report["staleCount"] = len(stale_ids)
                target_report["scanned"] = scanned
                if args.apply and stale_ids:
                    acked = 0
                    for ids in _chunked(stale_ids, max(1, args.ack_batch)):
                        acked += int(client.xack(target.stream, target.group, *ids))
                    target_report["acked"] = acked
            except Exception as exc:  # pragma: no cover - runtime safety path
                target_report["status"] = "error"
                target_report["error"] = str(exc)
            report["targets"].append(target_report)
        return report

    if args.loop:
        interval = max(10, int(args.interval_sec))
        while True:  # pragma: no cover - daemon mode
            print(json.dumps(_run_pass(), sort_keys=True), flush=True)
            time.sleep(interval)
    else:
        print(json.dumps(_run_pass(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
