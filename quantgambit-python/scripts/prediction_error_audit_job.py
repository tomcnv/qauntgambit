#!/usr/bin/env python3
"""
Daily prediction error audit for live trading.

Produces a timestamped JSON report with:
- directional alignment quality
- calibration quality (ECE/Brier from entry_p_hat)
- sample sufficiency checks

Usage:
  ./venv/bin/python scripts/prediction_error_audit_job.py --tenant-id ... --bot-id ...
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

import asyncpg


def _read_dotenv_value(key: str) -> Optional[str]:
    try:
        candidates = [Path(__file__).resolve().parents[2] / ".env", Path.cwd() / ".env"]
        for path in candidates:
            if not path.exists():
                continue
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line or line.lstrip().startswith("#"):
                    continue
                if line.startswith(f"{key}="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    except Exception:
        return None
    return None


def _env_value(key: str, default: Optional[str] = None) -> Optional[str]:
    return os.getenv(key) or _read_dotenv_value(key) or default


async def _get_pool() -> asyncpg.Pool:
    timescale_url = _env_value("BOT_TIMESCALE_URL")
    if timescale_url:
        return await asyncpg.create_pool(timescale_url, min_size=1, max_size=4, timeout=10.0)
    host = _env_value("BOT_DB_HOST", _env_value("DB_HOST", "localhost"))
    port = _env_value("BOT_DB_PORT", "5432")
    name = _env_value("BOT_DB_NAME", "platform_db")
    user = _env_value("BOT_DB_USER", "platform")
    password = _env_value("BOT_DB_PASSWORD", "platform_pw")
    dsn = f"postgresql://{user}:{password}@{host}:{port}/{name}"
    return await asyncpg.create_pool(dsn, min_size=1, max_size=4, timeout=10.0)


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


@dataclass
class AuditThresholds:
    min_trades: int
    min_aligned_win_rate_pct: float
    max_p_hat_ece: float
    min_directional_alignment_rate_pct: float


def _grade(summary: dict[str, Any], thresholds: AuditThresholds) -> dict[str, Any]:
    trades = int(summary.get("trades", 0) or 0)
    aligned_trades = int(summary.get("aligned_trades", 0) or 0)
    aligned_win_rate = _safe_float(summary.get("aligned_win_rate_pct"), 0.0)
    p_hat_ece = summary.get("p_hat_ece_10")
    p_hat_ece_f = _safe_float(p_hat_ece, 1.0) if p_hat_ece is not None else None
    alignment_rate = (aligned_trades / trades * 100.0) if trades > 0 else 0.0

    checks = {
        "min_trades": {
            "pass": trades >= thresholds.min_trades,
            "actual": trades,
            "threshold": thresholds.min_trades,
        },
        "alignment_rate": {
            "pass": alignment_rate >= thresholds.min_directional_alignment_rate_pct,
            "actual": round(alignment_rate, 4),
            "threshold": thresholds.min_directional_alignment_rate_pct,
        },
        "aligned_win_rate": {
            "pass": aligned_win_rate >= thresholds.min_aligned_win_rate_pct,
            "actual": round(aligned_win_rate, 4),
            "threshold": thresholds.min_aligned_win_rate_pct,
        },
        "p_hat_ece": {
            "pass": p_hat_ece_f is not None and p_hat_ece_f <= thresholds.max_p_hat_ece,
            "actual": None if p_hat_ece_f is None else round(p_hat_ece_f, 6),
            "threshold": thresholds.max_p_hat_ece,
        },
    }
    overall = all(bool(v.get("pass")) for v in checks.values())
    return {"overall_pass": overall, "checks": checks}


async def _build_summary(pool: asyncpg.Pool, tenant_id: str, bot_id: str, since: datetime) -> dict[str, Any]:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            WITH closes AS (
              SELECT
                ts,
                COALESCE(payload->>'side','') AS side,
                COALESCE(payload->>'prediction_direction','') AS prediction_direction,
                (payload->>'entry_p_hat')::double precision AS entry_p_hat,
                COALESCE((payload->>'net_pnl')::double precision, (payload->>'realized_pnl')::double precision) AS net_pnl
              FROM position_events
              WHERE tenant_id=$1
                AND bot_id=$2
                AND ts >= $3
                AND (payload->>'event_type')='closed'
            ),
            scored AS (
              SELECT
                *,
                CASE
                  WHEN LOWER(side) IN ('buy','long') AND LOWER(prediction_direction)='up' THEN true
                  WHEN LOWER(side) IN ('sell','short') AND LOWER(prediction_direction)='down' THEN true
                  WHEN prediction_direction='' OR side='' THEN NULL
                  ELSE false
                END AS aligned,
                CASE WHEN net_pnl IS NOT NULL THEN net_pnl > 0 ELSE NULL END AS win
              FROM closes
            )
            SELECT
              COUNT(*) AS trades,
              COUNT(*) FILTER (WHERE aligned IS TRUE) AS aligned_trades,
              COUNT(*) FILTER (WHERE aligned IS FALSE) AS misaligned_trades,
              AVG(CASE WHEN aligned IS TRUE AND win IS NOT NULL THEN (CASE WHEN win THEN 1.0 ELSE 0.0 END) END) * 100.0 AS aligned_win_rate_pct,
              AVG(CASE WHEN aligned IS NOT NULL THEN (CASE WHEN aligned THEN 1.0 ELSE 0.0 END) END) * 100.0 AS alignment_rate_pct
            FROM scored
            """,
            tenant_id,
            bot_id,
            since,
        )

        calib_rows = await conn.fetch(
            """
            SELECT
              (payload->>'entry_p_hat')::double precision AS p_hat,
              COALESCE((payload->>'net_pnl')::double precision, (payload->>'realized_pnl')::double precision) AS net_pnl
            FROM position_events
            WHERE tenant_id=$1
              AND bot_id=$2
              AND ts >= $3
              AND (payload->>'event_type')='closed'
              AND (payload->>'entry_p_hat') IS NOT NULL
            """,
            tenant_id,
            bot_id,
            since,
        )

    p_hat_pairs: list[tuple[float, float]] = []
    for r in calib_rows:
        p = _safe_float(r.get("p_hat"), -1.0)
        net = r.get("net_pnl")
        if p < 0.0 or p > 1.0 or net is None:
            continue
        y = 1.0 if _safe_float(net, 0.0) > 0.0 else 0.0
        p_hat_pairs.append((p, y))

    brier = None
    ece = None
    if p_hat_pairs:
        brier = sum((p - y) ** 2 for p, y in p_hat_pairs) / len(p_hat_pairs)
        bins = 10
        ece_acc = 0.0
        for idx in range(bins):
            lo = idx / bins
            hi = (idx + 1) / bins
            bucket = [(p, y) for p, y in p_hat_pairs if (p >= lo and (p <= hi if idx == bins - 1 else p < hi))]
            if not bucket:
                continue
            conf = sum(p for p, _ in bucket) / len(bucket)
            acc = sum(y for _, y in bucket) / len(bucket)
            ece_acc += abs(acc - conf) * (len(bucket) / len(p_hat_pairs))
        ece = ece_acc

    return {
        "trades": int(row["trades"] or 0),
        "aligned_trades": int(row["aligned_trades"] or 0),
        "misaligned_trades": int(row["misaligned_trades"] or 0),
        "aligned_win_rate_pct": round(_safe_float(row["aligned_win_rate_pct"], 0.0), 4),
        "alignment_rate_pct": round(_safe_float(row["alignment_rate_pct"], 0.0), 4),
        "p_hat_pairs": len(p_hat_pairs),
        "p_hat_brier": None if brier is None else round(float(brier), 6),
        "p_hat_ece_10": None if ece is None else round(float(ece), 6),
    }


async def main() -> int:
    ap = argparse.ArgumentParser(description="Run daily prediction error audit and persist JSON report.")
    ap.add_argument("--tenant-id", required=True)
    ap.add_argument("--bot-id", required=True)
    ap.add_argument("--hours", type=int, default=24)
    ap.add_argument("--output-dir", default="reports/prediction_audit")
    ap.add_argument("--min-trades", type=int, default=40)
    ap.add_argument("--min-aligned-win-rate-pct", type=float, default=52.0)
    ap.add_argument("--max-p-hat-ece", type=float, default=0.22)
    ap.add_argument("--min-directional-alignment-rate-pct", type=float, default=45.0)
    args = ap.parse_args()

    since = datetime.now(timezone.utc) - timedelta(hours=int(args.hours))
    thresholds = AuditThresholds(
        min_trades=int(args.min_trades),
        min_aligned_win_rate_pct=float(args.min_aligned_win_rate_pct),
        max_p_hat_ece=float(args.max_p_hat_ece),
        min_directional_alignment_rate_pct=float(args.min_directional_alignment_rate_pct),
    )

    pool = await _get_pool()
    try:
        summary = await _build_summary(pool, args.tenant_id, args.bot_id, since)
    finally:
        await pool.close()

    grade = _grade(summary, thresholds)
    now = datetime.now(timezone.utc)
    payload = {
        "generated_at": now.isoformat(),
        "since": since.isoformat(),
        "tenant_id": args.tenant_id,
        "bot_id": args.bot_id,
        "window_hours": int(args.hours),
        "summary": summary,
        "thresholds": {
            "min_trades": thresholds.min_trades,
            "min_aligned_win_rate_pct": thresholds.min_aligned_win_rate_pct,
            "max_p_hat_ece": thresholds.max_p_hat_ece,
            "min_directional_alignment_rate_pct": thresholds.min_directional_alignment_rate_pct,
        },
        "grade": grade,
    }

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / f"prediction_error_audit_{now.strftime('%Y%m%dT%H%M%SZ')}.json"
    out_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    print(json.dumps({"report": str(out_path), "overall_pass": grade["overall_pass"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

