#!/usr/bin/env python3
"""
Loss Learning Report

Purpose:
- Quantify where losses come from (gross edge vs fees).
- Break down expectancy by symbol/side and close reason.
- Join close rows to nearest entry intents and summarize ONNX-linked metrics.

Usage:
  python scripts/loss_learning_report.py --tenant-id ... --bot-id ... --hours 168
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, Optional

import asyncpg


def _read_dotenv_value(key: str) -> Optional[str]:
    try:
        candidates: list[Path] = []
        candidates.append(Path(__file__).resolve().parents[2] / ".env")
        candidates.append(Path.cwd() / ".env")
        for path in candidates:
            if not path.exists():
                continue
            for line in path.read_text().splitlines():
                if not line or line.lstrip().startswith("#"):
                    continue
                if not line.startswith(f"{key}="):
                    continue
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    except Exception:
        return None
    return None


def _env_value(key: str, default: Optional[str] = None) -> Optional[str]:
    return os.getenv(key) or _read_dotenv_value(key) or default


async def _get_pool() -> asyncpg.Pool:
    timescale_url = _env_value("BOT_TIMESCALE_URL")
    if timescale_url:
        return await asyncpg.create_pool(timescale_url, min_size=1, max_size=5, timeout=10.0)
    host = _env_value("BOT_DB_HOST", _env_value("DB_HOST", "localhost"))
    port = _env_value("BOT_DB_PORT", "5432")
    name = _env_value("BOT_DB_NAME", "platform_db")
    user = _env_value("BOT_DB_USER", "platform")
    password = _env_value("BOT_DB_PASSWORD", "platform_pw")
    dsn = f"postgresql://{user}:{password}@{host}:{port}/{name}"
    return await asyncpg.create_pool(dsn, min_size=1, max_size=5, timeout=10.0)


def _round_dict(values: Dict[str, Any], ndigits: int = 4) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for k, v in values.items():
        if isinstance(v, Decimal):
            v = float(v)
        if isinstance(v, float):
            out[k] = round(v, ndigits)
        else:
            out[k] = v
    return out


def _recommendations(headline: Dict[str, Any], by_symbol_side: list[Dict[str, Any]]) -> list[str]:
    recs: list[str] = []
    n = int(headline.get("n") or 0)
    if n <= 0:
        return ["No close rows in window; widen --hours or verify event ingestion."]

    edge_negative_rate = float(headline.get("edge_negative_rate_pct") or 0.0)
    fee_kill_rate = float(headline.get("fee_kill_rate_pct") or 0.0)

    if edge_negative_rate >= 55.0:
        recs.append(
            "Primary issue is directional edge (gross-negative majority). Tighten/disable worst symbol-side cohorts first, not global risk."
        )
    if fee_kill_rate >= 15.0:
        recs.append(
            "Secondary issue is fee-kill churn. Raise minimum net-edge and min-profit buffers or reduce taker-only churn windows."
        )

    worst = sorted(by_symbol_side, key=lambda x: float(x.get("sum_net") or 0.0))
    for row in worst[:3]:
        sym = row.get("symbol")
        side = row.get("close_side")
        win = float(row.get("win_rate") or 0.0)
        net = float(row.get("sum_net") or 0.0)
        if win <= 20.0 and net < 0:
            recs.append(
                f"Worst cohort `{sym}` `{side}` is strongly negative (win {win:.1f}%, net {net:.2f}). Apply side-specific gating or temporary disable."
            )

    if not recs:
        recs.append("No dominant pathology detected; continue collecting samples and monitor drift weekly.")
    return recs


async def _build_report(pool: asyncpg.Pool, tenant_id: str, bot_id: str, since: datetime) -> Dict[str, Any]:
    async with pool.acquire() as conn:
        headline = await conn.fetchrow(
            """
            WITH t AS (
              SELECT ts, symbol,
                     LOWER(COALESCE(payload->>'side','')) AS close_side,
                     (payload->>'net_pnl')::double precision AS net_pnl,
                     (payload->>'gross_pnl')::double precision AS gross_pnl,
                     COALESCE((payload->>'total_fees_usd')::double precision,0) AS fees
              FROM order_events
              WHERE tenant_id=$1 AND bot_id=$2
                AND LOWER(COALESCE(payload->>'status',''))='filled'
                AND LOWER(COALESCE(payload->>'position_effect',''))='close'
                AND ts >= $3
            )
            SELECT COUNT(*) AS n,
                   COALESCE(SUM(net_pnl),0) AS sum_net,
                   COALESCE(SUM(gross_pnl),0) AS sum_gross,
                   COALESCE(SUM(fees),0) AS sum_fees,
                   COALESCE(AVG(net_pnl),0) AS avg_net,
                   COALESCE(AVG(gross_pnl),0) AS avg_gross,
                   (SUM(CASE WHEN net_pnl>0 THEN 1 ELSE 0 END)::double precision/NULLIF(COUNT(*),0))*100.0 AS net_win_rate,
                   (SUM(CASE WHEN gross_pnl>0 THEN 1 ELSE 0 END)::double precision/NULLIF(COUNT(*),0))*100.0 AS gross_win_rate,
                   (SUM(CASE WHEN gross_pnl>0 AND net_pnl<=0 THEN 1 ELSE 0 END)::double precision/NULLIF(COUNT(*),0))*100.0 AS fee_kill_rate_pct,
                   (SUM(CASE WHEN gross_pnl<=0 THEN 1 ELSE 0 END)::double precision/NULLIF(COUNT(*),0))*100.0 AS edge_negative_rate_pct
            FROM t
            """,
            tenant_id,
            bot_id,
            since,
        )
        by_symbol_side_rows = await conn.fetch(
            """
            WITH t AS (
              SELECT symbol,
                     LOWER(COALESCE(payload->>'side','')) AS close_side,
                     (payload->>'net_pnl')::double precision AS net_pnl,
                     (payload->>'gross_pnl')::double precision AS gross_pnl
              FROM order_events
              WHERE tenant_id=$1 AND bot_id=$2
                AND LOWER(COALESCE(payload->>'status',''))='filled'
                AND LOWER(COALESCE(payload->>'position_effect',''))='close'
                AND ts >= $3
            )
            SELECT symbol, close_side, COUNT(*) AS n,
                   COALESCE(SUM(net_pnl),0) AS sum_net,
                   COALESCE(AVG(net_pnl),0) AS avg_net,
                   (SUM(CASE WHEN net_pnl>0 THEN 1 ELSE 0 END)::double precision/NULLIF(COUNT(*),0))*100.0 AS win_rate,
                   (SUM(CASE WHEN gross_pnl>0 AND net_pnl<=0 THEN 1 ELSE 0 END)::double precision/NULLIF(COUNT(*),0))*100.0 AS fee_kill_rate
            FROM t
            GROUP BY symbol, close_side
            ORDER BY sum_net ASC
            """,
            tenant_id,
            bot_id,
            since,
        )
        by_reason_rows = await conn.fetch(
            """
            WITH t AS (
              SELECT COALESCE(payload->>'reason','') AS reason,
                     (payload->>'net_pnl')::double precision AS net_pnl,
                     COALESCE((payload->>'total_fees_usd')::double precision,0) AS fees
              FROM order_events
              WHERE tenant_id=$1 AND bot_id=$2
                AND LOWER(COALESCE(payload->>'status',''))='filled'
                AND LOWER(COALESCE(payload->>'position_effect',''))='close'
                AND ts >= $3
            )
            SELECT reason, COUNT(*) AS n,
                   COALESCE(SUM(net_pnl),0) AS sum_net,
                   COALESCE(AVG(net_pnl),0) AS avg_net,
                   COALESCE(AVG(fees),0) AS avg_fees
            FROM t
            GROUP BY reason
            ORDER BY n DESC
            """,
            tenant_id,
            bot_id,
            since,
        )
        paired_headline = await conn.fetchrow(
            """
            WITH closes AS (
              SELECT ts AS close_ts,
                     symbol,
                     LOWER(COALESCE(payload->>'side','')) AS close_side,
                     (payload->>'net_pnl')::double precision AS net_pnl
              FROM order_events
              WHERE tenant_id=$1 AND bot_id=$2
                AND LOWER(COALESCE(payload->>'status',''))='filled'
                AND LOWER(COALESCE(payload->>'position_effect',''))='close'
                AND ts >= $3
            ),
            paired AS (
              SELECT c.close_ts, c.symbol, c.close_side, c.net_pnl, i.snapshot_metrics,
                     ABS(EXTRACT(EPOCH FROM (c.close_ts - i.created_at))) AS dt_sec,
                     ROW_NUMBER() OVER (PARTITION BY c.close_ts, c.symbol ORDER BY ABS(EXTRACT(EPOCH FROM (c.close_ts - i.created_at)))) AS rn
              FROM closes c
              JOIN order_intents i
                ON i.tenant_id=$1 AND i.bot_id=$2
               AND i.symbol=c.symbol
               AND i.created_at BETWEEN c.close_ts - INTERVAL '2 hours' AND c.close_ts
               AND LOWER(COALESCE(i.side,'')) <> c.close_side
            ),
            p AS (
              SELECT net_pnl, snapshot_metrics, dt_sec
              FROM paired WHERE rn=1
            )
            SELECT COUNT(*) AS matched,
                   COALESCE(SUM(net_pnl),0) AS sum_net,
                   COALESCE(AVG(net_pnl),0) AS avg_net,
                   (SUM(CASE WHEN net_pnl>0 THEN 1 ELSE 0 END)::double precision/NULLIF(COUNT(*),0))*100.0 AS win_rate,
                   COALESCE(AVG((snapshot_metrics->>'entry_p_hat')::double precision),0) AS avg_entry_p_hat,
                   COALESCE(AVG((snapshot_metrics->>'prediction_confidence')::double precision),0) AS avg_prediction_confidence,
                   COALESCE(AVG(dt_sec),0) AS avg_match_dt_sec
            FROM p
            """,
            tenant_id,
            bot_id,
            since,
        )
        paired_buckets_rows = await conn.fetch(
            """
            WITH closes AS (
              SELECT ts AS close_ts,
                     symbol,
                     LOWER(COALESCE(payload->>'side','')) AS close_side,
                     (payload->>'net_pnl')::double precision AS net_pnl
              FROM order_events
              WHERE tenant_id=$1 AND bot_id=$2
                AND LOWER(COALESCE(payload->>'status',''))='filled'
                AND LOWER(COALESCE(payload->>'position_effect',''))='close'
                AND ts >= $3
            ),
            paired AS (
              SELECT c.close_ts, c.symbol, c.close_side, c.net_pnl, i.snapshot_metrics,
                     ROW_NUMBER() OVER (PARTITION BY c.close_ts, c.symbol ORDER BY ABS(EXTRACT(EPOCH FROM (c.close_ts - i.created_at)))) AS rn
              FROM closes c
              JOIN order_intents i
                ON i.tenant_id=$1 AND i.bot_id=$2
               AND i.symbol=c.symbol
               AND i.created_at BETWEEN c.close_ts - INTERVAL '2 hours' AND c.close_ts
               AND LOWER(COALESCE(i.side,'')) <> c.close_side
            ),
            p AS (
              SELECT net_pnl, (snapshot_metrics->>'entry_p_hat')::double precision AS p_hat
              FROM paired WHERE rn=1
            )
            SELECT
              CASE
                WHEN p_hat IS NULL THEN 'missing'
                WHEN p_hat >= 0.60 THEN 'p_hat>=0.60'
                WHEN p_hat >= 0.55 THEN '0.55-0.60'
                WHEN p_hat >= 0.50 THEN '0.50-0.55'
                ELSE '<0.50'
              END AS bucket,
              COUNT(*) AS n,
              COALESCE(SUM(net_pnl),0) AS sum_net,
              COALESCE(AVG(net_pnl),0) AS avg_net,
              (SUM(CASE WHEN net_pnl>0 THEN 1 ELSE 0 END)::double precision/NULLIF(COUNT(*),0))*100.0 AS win_rate
            FROM p
            GROUP BY 1
            ORDER BY 1
            """,
            tenant_id,
            bot_id,
            since,
        )

    headline_dict = _round_dict(dict(headline or {}))
    by_symbol_side = [_round_dict(dict(r)) for r in by_symbol_side_rows]
    by_reason = [_round_dict(dict(r)) for r in by_reason_rows]
    paired_headline_dict = _round_dict(dict(paired_headline or {}))
    paired_buckets = [_round_dict(dict(r)) for r in paired_buckets_rows]

    return {
        "window": {"since": since.isoformat()},
        "headline": headline_dict,
        "by_symbol_side": by_symbol_side,
        "by_reason": by_reason,
        "onnx_linked": {
            "paired_headline": paired_headline_dict,
            "p_hat_buckets": paired_buckets,
        },
        "recommendations": _recommendations(headline_dict, by_symbol_side),
    }


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tenant-id", required=True)
    ap.add_argument("--bot-id", required=True)
    ap.add_argument("--hours", type=int, default=168, help="Lookback window in hours (default: 168 = 7 days)")
    ap.add_argument("--output", default="", help="Optional path to write JSON report")
    args = ap.parse_args()

    since = datetime.now(timezone.utc) - timedelta(hours=max(1, int(args.hours)))
    pool = await _get_pool()
    try:
        report = await _build_report(pool, args.tenant_id, args.bot_id, since)
    finally:
        await pool.close()

    print(json.dumps(report, indent=2, sort_keys=True))
    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
        print(f"\nWrote report to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
