#!/usr/bin/env python3
"""Compare baseline market execution vs maker-first cohorts from order_events."""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
from pathlib import Path

import asyncpg


QUERY = """
WITH closes_raw AS (
  SELECT
    ts,
    symbol,
    payload,
    COALESCE(
      NULLIF(payload->>'entry_client_order_id', ''),
      NULLIF(payload->>'client_order_id', ''),
      NULLIF(payload->>'order_id', ''),
      CONCAT('row:', ts::text)
    ) AS trade_key,
    COALESCE((payload->>'entry_order_type'), (payload->>'order_type'), 'market') AS order_type,
    COALESCE((payload->>'entry_post_only')::boolean, (payload->>'post_only')::boolean, false) AS post_only,
    (payload->>'net_pnl')::double precision AS net_pnl,
    COALESCE(
      (payload->>'total_cost_bps')::double precision,
      (
        (
          COALESCE((payload->>'entry_fee_usd')::double precision, 0.0)
          + COALESCE((payload->>'fee_usd')::double precision, 0.0)
        )
        / NULLIF(
            ABS(
              COALESCE(
                (payload->>'entry_price')::double precision,
                (payload->>'fill_price')::double precision,
                (payload->>'exit_price')::double precision
              )
              * COALESCE((payload->>'filled_size')::double precision, (payload->>'size')::double precision)
            ),
            0.0
          )
        * 10000.0
      )
      + COALESCE((payload->>'entry_slippage_bps')::double precision, 0.0)
      + COALESCE((payload->>'exit_slippage_bps')::double precision, 0.0)
    ) AS total_cost_bps
  FROM order_events
  WHERE ts >= NOW() - make_interval(days => $1::int)
    AND ($2::text IS NULL OR tenant_id::text = $2::text)
    AND ($3::text IS NULL OR bot_id::text = $3::text)
    AND ($4::text IS NULL OR symbol = $4::text)
    AND (
      payload->>'position_effect' = 'close'
      OR payload->>'reason' IN ('position_close', 'strategic_exit', 'stop_loss', 'take_profit', 'exchange_reconcile')
    )
    AND payload ? 'net_pnl'
),
deduped AS (
  SELECT *
  FROM (
    SELECT
      *,
      ROW_NUMBER() OVER (PARTITION BY trade_key ORDER BY ts DESC) AS rn
    FROM closes_raw
  ) t
  WHERE rn = 1
),
tagged AS (
  SELECT *,
    CASE
      WHEN COALESCE(payload->>'execution_cohort', '') <> '' THEN payload->>'execution_cohort'
      WHEN COALESCE(payload->>'execution_policy', '') = 'maker_first' THEN 'maker_first'
      WHEN post_only OR order_type = 'limit' THEN 'maker_first'
      ELSE 'baseline_market'
    END AS cohort
  FROM deduped
)
SELECT
  cohort,
  COUNT(*)::int AS trades,
  AVG(CASE WHEN net_pnl > 0 THEN 1.0 ELSE 0.0 END)::double precision AS win_rate,
  AVG(net_pnl)::double precision AS avg_net_pnl,
  SUM(net_pnl)::double precision AS total_net_pnl,
  AVG(total_cost_bps)::double precision AS avg_total_cost_bps
FROM tagged
GROUP BY cohort
ORDER BY cohort;
"""


async def run_report(args: argparse.Namespace) -> dict:
    conn = await asyncpg.connect(args.dsn)
    try:
        rows = [
            dict(r)
            for r in await conn.fetch(
                QUERY,
                int(args.window_days),
                args.tenant_id or None,
                args.bot_id or None,
                args.symbol or None,
            )
        ]
    finally:
        await conn.close()

    by = {row["cohort"]: row for row in rows}
    baseline = by.get("baseline_market")
    maker = by.get("maker_first")
    checks: list[dict] = []
    decision = "hold"

    if not baseline:
        checks.append({"name": "baseline_present", "pass": False, "details": "no baseline_market rows"})
    if not maker:
        checks.append({"name": "maker_present", "pass": False, "details": "no maker_first rows"})

    if baseline and maker:
        checks.append(
            {
                "name": "sample_size",
                "pass": baseline["trades"] >= args.min_trades and maker["trades"] >= args.min_trades,
                "details": f"baseline={baseline['trades']} maker={maker['trades']}",
            }
        )
        win_rate_delta_pp = (maker["win_rate"] - baseline["win_rate"]) * 100.0
        checks.append(
            {
                "name": "win_rate_guard",
                "pass": win_rate_delta_pp >= -args.max_win_rate_regression_pp,
                "details": f"win_rate_delta_pp={win_rate_delta_pp:.2f}",
            }
        )
        if baseline.get("avg_total_cost_bps") and maker.get("avg_total_cost_bps"):
            cost_improvement_pct = (
                (baseline["avg_total_cost_bps"] - maker["avg_total_cost_bps"]) / baseline["avg_total_cost_bps"]
            ) * 100.0
            checks.append(
                {
                    "name": "cost_improvement",
                    "pass": cost_improvement_pct >= args.min_cost_improvement_pct,
                    "details": f"cost_improvement_pct={cost_improvement_pct:.2f}",
                }
            )
        else:
            checks.append(
                {
                    "name": "cost_improvement",
                    "pass": False,
                    "details": "missing avg_total_cost_bps for one or both cohorts",
                }
            )
        checks.append(
            {
                "name": "net_pnl_guard",
                "pass": maker["total_net_pnl"] >= baseline["total_net_pnl"],
                "details": f"maker={maker['total_net_pnl']:.4f} baseline={baseline['total_net_pnl']:.4f}",
            }
        )
        decision = "promote" if all(check["pass"] for check in checks) else "hold"

    return {
        "generated_at": dt.datetime.utcnow().isoformat() + "Z",
        "window_days": args.window_days,
        "cohorts": rows,
        "criteria": {
            "min_trades_per_cohort": args.min_trades,
            "max_win_rate_regression_pp": args.max_win_rate_regression_pp,
            "min_cost_improvement_pct": args.min_cost_improvement_pct,
        },
        "checks": checks,
        "rollout_decision": decision,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run maker-first execution ablation from order_events.")
    parser.add_argument("--dsn", required=True, help="Postgres DSN (TimescaleDB order_events source).")
    parser.add_argument("--window-days", type=int, default=14)
    parser.add_argument("--tenant-id", default="", help="Optional tenant UUID filter.")
    parser.add_argument("--bot-id", default="", help="Optional bot UUID filter.")
    parser.add_argument("--symbol", default="", help="Optional symbol filter (e.g., BTCUSDT).")
    parser.add_argument("--min-trades", type=int, default=30)
    parser.add_argument("--max-win-rate-regression-pp", type=float, default=2.0)
    parser.add_argument("--min-cost-improvement-pct", type=float, default=15.0)
    parser.add_argument("--output", default="", help="Optional output JSON path.")
    args = parser.parse_args()

    payload = asyncio.run(run_report(args))
    rendered = json.dumps(payload, indent=2)
    if args.output:
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(rendered, encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()

