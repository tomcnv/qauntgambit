#!/usr/bin/env python3
"""
24h fundamental soundness audit runner.

Outputs:
- baseline_snapshot.json
- metrics_15m.json
- expected_vs_realized.json
- gate_evaluation.json
- audit_report.json
- audit_report.md
"""

from __future__ import annotations

import argparse
import asyncio
import asyncpg
import json
import math
import os
import subprocess
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import median
from typing import Any, Dict, Iterable, List, Optional, Tuple


ROOT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_ROOT = Path(__file__).resolve().parents[1] / "reports" / "soundness"


CRITICAL_ENV_KEYS = [
    "ENTRY_EXECUTION_MODE",
    "ENTRY_MAKER_FILL_WINDOW_MS",
    "ENTRY_MAKER_MAX_REPOSTS",
    "ENTRY_MAKER_PRICE_OFFSET_TICKS",
    "ENTRY_MAKER_FALLBACK_TO_MARKET",
    "MIN_ORDER_INTERVAL_SEC",
    "ENTRY_MAX_ATTEMPTS_PER_SYMBOL_PER_MIN",
    "MAX_POSITIONS_PER_SYMBOL",
    "EXIT_SIGNAL_MIN_HOLD_SEC",
    "COOLDOWN_ENTRY_SEC",
    "COOLDOWN_SAME_DIRECTION_SEC",
    "POSITION_CONTINUATION_GATE_ENABLED",
    "MIN_NET_EDGE_BPS",
    "NET_EDGE_BUFFER_BPS",
    "EXECUTION_HARD_MAX_ORDER_NOTIONAL_USD",
    "EV_GATE_MODE",
    "EV_GATE_COST_MULTIPLE",
    "EV_GATE_RECENT_COST_P75_BPS_BY_SYMBOL",
    "MODEL_DIRECTION_ALIGNMENT_MIN_CONFIDENCE",
    "PREDICTION_ONNX_MIN_CONFIDENCE_BY_SYMBOL",
    "PREDICTION_ONNX_MIN_MARGIN_BY_SYMBOL",
    "PREDICTION_ONNX_MAX_ENTROPY_BY_SYMBOL",
    "SYMBOLS",
]


@dataclass
class AuditWindow:
    since: datetime
    until: datetime
    bucket_minutes: int


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _coerce_float(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _floor_bucket(ts: datetime, bucket_minutes: int) -> datetime:
    minute = (ts.minute // bucket_minutes) * bucket_minutes
    return ts.replace(minute=minute, second=0, microsecond=0)


def _read_dotenv(path: Path) -> Dict[str, str]:
    parsed: Dict[str, str] = {}
    if not path.exists():
        return parsed
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        parsed[key.strip()] = value.strip().strip('"').strip("'")
    return parsed


def _safe_git(command: List[str]) -> str:
    try:
        out = subprocess.run(
            command,
            cwd=str(ROOT_DIR),
            check=True,
            capture_output=True,
            text=True,
        )
        return out.stdout.strip()
    except Exception:
        return ""


def _parse_pm2_env(pm2_id: str) -> Dict[str, str]:
    try:
        out = subprocess.run(
            ["pm2", "env", pm2_id],
            cwd=str(ROOT_DIR),
            check=True,
            capture_output=True,
            text=True,
        )
    except Exception:
        return {}
    parsed: Dict[str, str] = {}
    for line in out.stdout.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        k = key.strip()
        if k in CRITICAL_ENV_KEYS:
            parsed[k] = value.strip()
    return parsed


def snapshot_baseline(window: AuditWindow, pm2_id: str) -> Dict[str, Any]:
    dotenv = _read_dotenv(ROOT_DIR / ".env")
    env_snapshot = {k: dotenv.get(k) for k in CRITICAL_ENV_KEYS if k in dotenv}
    pm2_snapshot = _parse_pm2_env(pm2_id)
    return {
        "captured_at_utc": _utc_now().isoformat(),
        "window": {
            "since_utc": window.since.isoformat(),
            "until_utc": window.until.isoformat(),
            "hours": round((window.until - window.since).total_seconds() / 3600.0, 3),
            "bucket_minutes": window.bucket_minutes,
        },
        "git": {
            "branch": _safe_git(["git", "rev-parse", "--abbrev-ref", "HEAD"]),
            "commit": _safe_git(["git", "rev-parse", "HEAD"]),
            "dirty": bool(_safe_git(["git", "status", "--porcelain"])),
        },
        "env_file": env_snapshot,
        "runtime_pm2": pm2_snapshot,
    }


async def _get_pool() -> asyncpg.Pool:
    bot_timescale = os.getenv("BOT_TIMESCALE_URL")
    if not bot_timescale:
        env_file = _read_dotenv(ROOT_DIR / ".env")
        bot_timescale = env_file.get("BOT_TIMESCALE_URL")
    if not bot_timescale:
        host = os.getenv("BOT_DB_HOST", "localhost")
        port = os.getenv("BOT_DB_PORT", "5433")
        name = os.getenv("BOT_DB_NAME", "quantgambit_bot")
        user = os.getenv("BOT_DB_USER", "quantgambit")
        password = os.getenv("BOT_DB_PASSWORD", "quantgambit_pw")
        bot_timescale = f"postgresql://{user}:{password}@{host}:{port}/{name}"
    return await asyncpg.create_pool(bot_timescale, min_size=1, max_size=5, timeout=15.0)


def _normalize_result(raw: str) -> str:
    upper = (raw or "").upper()
    if upper in {"ACCEPT", "ACCEPTED"}:
        return "accepted"
    if upper in {"REJECT", "REJECTED"}:
        return "rejected"
    return "other"


async def collect_decision_metrics(
    conn: asyncpg.Connection,
    tenant_id: str,
    bot_id: str,
    window: AuditWindow,
) -> Dict[str, Any]:
    rows = await conn.fetch(
        """
        WITH base AS (
            SELECT
                symbol,
                (
                    date_trunc('hour', ts)
                    + ((extract(minute from ts)::int / $5) * $5) * interval '1 minute'
                ) AS bucket_start,
                CASE
                    WHEN UPPER(COALESCE(payload->>'result', payload->>'status', '')) IN ('ACCEPT', 'ACCEPTED') THEN 'accepted'
                    WHEN UPPER(COALESCE(payload->>'result', payload->>'status', '')) IN ('REJECT', 'REJECTED') THEN 'rejected'
                    ELSE 'other'
                END AS normalized_result,
                COALESCE(payload->>'rejection_reason', '') AS rejection_reason
            FROM decision_events
            WHERE tenant_id = $1
              AND bot_id = $2
              AND ts >= $3
              AND ts <= $4
        )
        SELECT bucket_start, symbol, normalized_result, rejection_reason, COUNT(*) AS n
        FROM base
        GROUP BY 1, 2, 3, 4
        ORDER BY 1, 2
        """,
        tenant_id,
        bot_id,
        window.since,
        window.until,
        window.bucket_minutes,
    )

    by_bucket: Dict[str, Dict[str, Any]] = {}
    by_symbol: Dict[str, Dict[str, Any]] = defaultdict(lambda: {"accepted": 0, "rejected": 0, "other": 0, "rejection_reasons": Counter()})
    total_rows = 0

    for row in rows:
        symbol = (row["symbol"] or "UNKNOWN").upper()
        result = str(row["normalized_result"] or "other")
        reason = str(row["rejection_reason"] or "").strip() or None
        n = int(row["n"] or 0)
        total_rows += n
        bucket = row["bucket_start"].replace(tzinfo=timezone.utc).isoformat()
        key = f"{bucket}|{symbol}"
        if key not in by_bucket:
            by_bucket[key] = {
                "bucket_start_utc": bucket,
                "symbol": symbol,
                "accepted": 0,
                "rejected": 0,
                "other": 0,
                "rejection_reasons": Counter(),
            }
        by_bucket[key][result] += n
        by_symbol[symbol][result] += n
        if reason and result == "rejected":
            by_bucket[key]["rejection_reasons"][reason] += n
            by_symbol[symbol]["rejection_reasons"][reason] += n

    bucket_rows: List[Dict[str, Any]] = []
    for data in by_bucket.values():
        rejection_reasons = dict(data["rejection_reasons"].most_common(10))
        bucket_rows.append(
            {
                "bucket_start_utc": data["bucket_start_utc"],
                "symbol": data["symbol"],
                "accepted": data["accepted"],
                "rejected": data["rejected"],
                "other": data["other"],
                "rejection_reasons": rejection_reasons,
            }
        )
    bucket_rows.sort(key=lambda x: (x["bucket_start_utc"], x["symbol"]))

    symbol_summary = {}
    for symbol, data in by_symbol.items():
        total = data["accepted"] + data["rejected"] + data["other"]
        symbol_summary[symbol] = {
            "accepted": data["accepted"],
            "rejected": data["rejected"],
            "other": data["other"],
            "accept_rate_pct": round((100.0 * data["accepted"] / total), 3) if total else 0.0,
            "top_rejection_reasons": dict(data["rejection_reasons"].most_common(12)),
        }
    return {
        "total_rows": total_rows,
        "symbol_summary": symbol_summary,
        "buckets_15m": bucket_rows,
    }


async def collect_order_lifecycle_metrics(
    conn: asyncpg.Connection,
    tenant_id: str,
    bot_id: str,
    window: AuditWindow,
) -> Dict[str, Any]:
    rows = await conn.fetch(
        """
        SELECT
            (
                date_trunc('hour', updated_at)
                + ((extract(minute from updated_at)::int / $5) * $5) * interval '1 minute'
            ) AS bucket_start,
            symbol,
            LOWER(COALESCE(status, 'unknown')) AS status,
            SUM(CASE WHEN COALESCE(client_order_id, '') LIKE '%:m%' THEN 1 ELSE 0 END) AS maker_attempts,
            SUM(CASE WHEN COALESCE(client_order_id, '') LIKE '%:m%' AND LOWER(COALESCE(status, '')) = 'canceled' THEN 1 ELSE 0 END) AS maker_attempt_canceled,
            SUM(CASE WHEN COALESCE(client_order_id, '') LIKE '%:f' THEN 1 ELSE 0 END) AS fallback_orders,
            COUNT(*) AS n
        FROM order_states
        WHERE tenant_id = $1
          AND bot_id = $2
          AND updated_at >= $3
          AND updated_at <= $4
        GROUP BY 1, 2, 3
        ORDER BY 1, 2
        """,
        tenant_id,
        bot_id,
        window.since,
        window.until,
        window.bucket_minutes,
    )

    by_bucket: Dict[str, Dict[str, Any]] = {}
    by_symbol_status: Dict[str, Counter] = defaultdict(Counter)
    maker_attempt_counter = Counter()
    total_rows = 0

    for row in rows:
        symbol = (row["symbol"] or "UNKNOWN").upper()
        status = str(row["status"] or "unknown").lower()
        bucket = row["bucket_start"].replace(tzinfo=timezone.utc).isoformat()
        n = int(row["n"] or 0)
        maker_attempts = int(row["maker_attempts"] or 0)
        maker_attempt_canceled = int(row["maker_attempt_canceled"] or 0)
        fallback_orders = int(row["fallback_orders"] or 0)
        total_rows += n
        key = f"{bucket}|{symbol}"
        if key not in by_bucket:
            by_bucket[key] = {
                "bucket_start_utc": bucket,
                "symbol": symbol,
                "status_counts": Counter(),
                "maker_attempts": 0,
                "fallback_orders": 0,
            }
        by_bucket[key]["status_counts"][status] += n
        by_symbol_status[symbol][status] += n
        by_bucket[key]["maker_attempts"] += maker_attempts
        by_bucket[key]["fallback_orders"] += fallback_orders
        maker_attempt_counter["maker_attempts"] += maker_attempts
        maker_attempt_counter["maker_attempt_canceled"] += maker_attempt_canceled
        maker_attempt_counter["fallback_orders"] += fallback_orders

    bucket_rows = []
    for data in by_bucket.values():
        bucket_rows.append(
            {
                "bucket_start_utc": data["bucket_start_utc"],
                "symbol": data["symbol"],
                "status_counts": dict(data["status_counts"]),
                "maker_attempts": data["maker_attempts"],
                "fallback_orders": data["fallback_orders"],
            }
        )
    bucket_rows.sort(key=lambda x: (x["bucket_start_utc"], x["symbol"]))

    symbol_summary = {}
    for symbol, counts in by_symbol_status.items():
        filled = counts.get("filled", 0)
        canceled = counts.get("canceled", 0)
        ratio = (canceled / filled) if filled > 0 else math.inf
        symbol_summary[symbol] = {
            "status_counts": dict(counts),
            "canceled_to_filled_ratio": None if math.isinf(ratio) else round(ratio, 4),
            "filled_count": filled,
            "canceled_count": canceled,
        }

    return {
        "total_rows": total_rows,
        "symbol_summary": symbol_summary,
        "buckets_15m": bucket_rows,
        "maker_churn": {
            "maker_attempts": maker_attempt_counter["maker_attempts"],
            "maker_attempt_canceled": maker_attempt_counter["maker_attempt_canceled"],
            "maker_cancel_rate_pct": round(
                100.0 * maker_attempt_counter["maker_attempt_canceled"] / maker_attempt_counter["maker_attempts"], 3
            )
            if maker_attempt_counter["maker_attempts"] > 0
            else 0.0,
            "fallback_orders": maker_attempt_counter["fallback_orders"],
        },
    }


async def collect_close_pnl_metrics(
    conn: asyncpg.Connection,
    tenant_id: str,
    bot_id: str,
    window: AuditWindow,
) -> Dict[str, Any]:
    rows = await conn.fetch(
        """
        SELECT
            ts,
            symbol,
            COALESCE(payload->>'reason', '') AS reason,
            (payload->>'net_pnl')::double precision AS net_pnl,
            (payload->>'gross_pnl')::double precision AS gross_pnl,
            COALESCE((payload->>'total_fees_usd')::double precision, 0.0) AS total_fees_usd,
            (payload->>'total_cost_bps')::double precision AS total_cost_bps
        FROM order_events
        WHERE tenant_id = $1
          AND bot_id = $2
          AND ts >= $3
          AND ts <= $4
          AND LOWER(COALESCE(payload->>'status', '')) = 'filled'
          AND LOWER(COALESCE(payload->>'position_effect', '')) = 'close'
        ORDER BY ts ASC
        """,
        tenant_id,
        bot_id,
        window.since,
        window.until,
    )

    by_symbol = defaultdict(lambda: {"count": 0, "sum_net_pnl": 0.0, "sum_gross_pnl": 0.0, "sum_fees_usd": 0.0, "reasons": Counter()})
    by_bucket = {}
    forced_markers = ("safety_exit", "data_stale", "max_age_exceeded", "reconciliation_heal", "exchange_reconcile")
    forced_count = 0

    for row in rows:
        symbol = (row["symbol"] or "UNKNOWN").upper()
        reason = str(row["reason"] or "")
        net_pnl = _coerce_float(row["net_pnl"]) or 0.0
        gross_pnl = _coerce_float(row["gross_pnl"]) or 0.0
        fees = _coerce_float(row["total_fees_usd"]) or 0.0
        ts = row["ts"]
        bucket = _floor_bucket(ts, window.bucket_minutes).isoformat()
        key = f"{bucket}|{symbol}"
        if key not in by_bucket:
            by_bucket[key] = {
                "bucket_start_utc": bucket,
                "symbol": symbol,
                "close_count": 0,
                "sum_net_pnl": 0.0,
                "sum_gross_pnl": 0.0,
                "sum_fees_usd": 0.0,
                "forced_close_count": 0,
            }
        by_bucket[key]["close_count"] += 1
        by_bucket[key]["sum_net_pnl"] += net_pnl
        by_bucket[key]["sum_gross_pnl"] += gross_pnl
        by_bucket[key]["sum_fees_usd"] += fees
        by_symbol[symbol]["count"] += 1
        by_symbol[symbol]["sum_net_pnl"] += net_pnl
        by_symbol[symbol]["sum_gross_pnl"] += gross_pnl
        by_symbol[symbol]["sum_fees_usd"] += fees
        by_symbol[symbol]["reasons"][reason or "unknown"] += 1
        if any(marker in reason for marker in forced_markers):
            forced_count += 1
            by_bucket[key]["forced_close_count"] += 1

    symbol_summary = {}
    for symbol, d in by_symbol.items():
        symbol_summary[symbol] = {
            "close_count": d["count"],
            "sum_net_pnl": round(d["sum_net_pnl"], 6),
            "sum_gross_pnl": round(d["sum_gross_pnl"], 6),
            "sum_fees_usd": round(d["sum_fees_usd"], 6),
            "avg_net_pnl": round(d["sum_net_pnl"] / d["count"], 6) if d["count"] > 0 else 0.0,
            "top_close_reasons": dict(d["reasons"].most_common(12)),
        }

    bucket_rows = sorted(by_bucket.values(), key=lambda x: (x["bucket_start_utc"], x["symbol"]))
    for row in bucket_rows:
        row["sum_net_pnl"] = round(row["sum_net_pnl"], 6)
        row["sum_gross_pnl"] = round(row["sum_gross_pnl"], 6)
        row["sum_fees_usd"] = round(row["sum_fees_usd"], 6)

    return {
        "total_close_rows": len(rows),
        "forced_close_rows": forced_count,
        "forced_close_rate_pct": round(100.0 * forced_count / len(rows), 4) if rows else 0.0,
        "symbol_summary": symbol_summary,
        "buckets_15m": bucket_rows,
    }


async def collect_expected_vs_realized(
    conn: asyncpg.Connection,
    tenant_id: str,
    bot_id: str,
    window: AuditWindow,
) -> Dict[str, Any]:
    rows = await conn.fetch(
        """
        WITH accepted AS (
            SELECT
                ts,
                symbol,
                (payload->>'total_cost_bps')::double precision AS expected_cost_bps,
                (payload->>'p_min')::double precision AS p_min,
                (payload->>'p_calibrated')::double precision AS p_calibrated,
                (payload->>'ev')::double precision AS ev
            FROM decision_events
            WHERE tenant_id = $1
              AND bot_id = $2
              AND ts >= $3
              AND ts <= $4
              AND UPPER(COALESCE(payload->>'result', '')) IN ('ACCEPT', 'ACCEPTED')
              AND (payload->>'total_cost_bps') IS NOT NULL
        ),
        closes AS (
            SELECT
                ts AS close_ts,
                symbol,
                (payload->>'total_cost_bps')::double precision AS realized_cost_bps,
                (payload->>'net_pnl')::double precision AS net_pnl,
                COALESCE(payload->>'reason', '') AS close_reason
            FROM order_events
            WHERE tenant_id = $1
              AND bot_id = $2
              AND ts >= $3
              AND ts <= $4
              AND LOWER(COALESCE(payload->>'status', '')) = 'filled'
              AND LOWER(COALESCE(payload->>'position_effect', '')) = 'close'
              AND (payload->>'total_cost_bps') IS NOT NULL
        )
        SELECT
            c.close_ts,
            c.symbol,
            c.realized_cost_bps,
            c.net_pnl,
            c.close_reason,
            a.ts AS decision_ts,
            a.expected_cost_bps,
            a.p_min,
            a.p_calibrated,
            a.ev
        FROM closes c
        LEFT JOIN LATERAL (
            SELECT *
            FROM accepted a
            WHERE a.symbol = c.symbol
              AND a.ts <= c.close_ts
              AND a.ts >= c.close_ts - INTERVAL '2 hours'
            ORDER BY a.ts DESC
            LIMIT 1
        ) a ON TRUE
        ORDER BY c.close_ts ASC
        """,
        tenant_id,
        bot_id,
        window.since,
        window.until,
    )

    pairs: List[Dict[str, Any]] = []
    by_symbol_diffs: Dict[str, List[float]] = defaultdict(list)
    by_symbol_matched = Counter()
    by_symbol_unmatched = Counter()
    ev_positive_net_negative = Counter()

    for row in rows:
        symbol = (row["symbol"] or "UNKNOWN").upper()
        realized = _coerce_float(row["realized_cost_bps"])
        expected = _coerce_float(row["expected_cost_bps"])
        p_cal = _coerce_float(row["p_calibrated"])
        p_min = _coerce_float(row["p_min"])
        ev = _coerce_float(row["ev"])
        net = _coerce_float(row["net_pnl"])
        diff = None
        if realized is not None and expected is not None:
            diff = realized - expected
            by_symbol_diffs[symbol].append(diff)
            by_symbol_matched[symbol] += 1
        else:
            by_symbol_unmatched[symbol] += 1

        if ev is not None and ev > 0 and net is not None and net < 0:
            ev_positive_net_negative[symbol] += 1

        pairs.append(
            {
                "close_ts_utc": row["close_ts"].isoformat() if row["close_ts"] else None,
                "symbol": symbol,
                "close_reason": row["close_reason"],
                "realized_cost_bps": realized,
                "expected_cost_bps": expected,
                "cost_error_bps": round(diff, 6) if diff is not None else None,
                "p_calibrated": p_cal,
                "p_min": p_min,
                "ev": ev,
                "net_pnl": net,
                "decision_ts_utc": row["decision_ts"].isoformat() if row["decision_ts"] else None,
            }
        )

    symbol_summary = {}
    for symbol in sorted(set(list(by_symbol_diffs.keys()) + list(by_symbol_unmatched.keys()))):
        diffs = by_symbol_diffs.get(symbol, [])
        med = median(diffs) if diffs else None
        p75 = sorted(diffs)[int(0.75 * (len(diffs) - 1))] if diffs else None
        symbol_summary[symbol] = {
            "matched_pairs": by_symbol_matched[symbol],
            "unmatched_closes": by_symbol_unmatched[symbol],
            "median_cost_error_bps": round(med, 6) if med is not None else None,
            "p75_cost_error_bps": round(p75, 6) if p75 is not None else None,
            "ev_positive_net_negative_count": ev_positive_net_negative[symbol],
        }

    return {
        "pair_count": len(pairs),
        "symbol_summary": symbol_summary,
        "pairs": pairs[:4000],
    }


def evaluate_gates(
    close_metrics: Dict[str, Any],
    lifecycle_metrics: Dict[str, Any],
    ev_realized: Dict[str, Any],
) -> Dict[str, Any]:
    symbol_net = {s: float(d["sum_net_pnl"]) for s, d in close_metrics["symbol_summary"].items()}
    positive_symbols = [s for s, net in symbol_net.items() if net >= 0.0]
    aggregate_net = float(sum(symbol_net.values()))
    gate_a_pass = (len(positive_symbols) >= 2) and (aggregate_net >= 0.0)

    b_results = {}
    gate_b_pass = True
    for symbol, d in ev_realized["symbol_summary"].items():
        matched = int(d["matched_pairs"])
        med = d["median_cost_error_bps"]
        if matched < 5 or med is None:
            b_results[symbol] = {"status": "insufficient_data", "matched_pairs": matched, "median_cost_error_bps": med}
            gate_b_pass = False
            continue
        ok = med <= 3.0
        b_results[symbol] = {"status": "pass" if ok else "fail", "matched_pairs": matched, "median_cost_error_bps": med}
        gate_b_pass = gate_b_pass and ok

    lifecycle_by_symbol = lifecycle_metrics["symbol_summary"]
    active_symbols = [s for s, d in lifecycle_by_symbol.items() if int(d.get("filled_count", 0)) > 0]
    c_results = {}
    gate_c_pass = True
    for symbol in active_symbols:
        ratio = lifecycle_by_symbol[symbol].get("canceled_to_filled_ratio")
        if ratio is None:
            c_results[symbol] = {"status": "fail", "canceled_to_filled_ratio": None, "reason": "no_filled_orders"}
            gate_c_pass = False
            continue
        ok = ratio <= 3.0
        c_results[symbol] = {"status": "pass" if ok else "fail", "canceled_to_filled_ratio": ratio}
        gate_c_pass = gate_c_pass and ok
    if not active_symbols:
        gate_c_pass = False

    forced_rate = float(close_metrics.get("forced_close_rate_pct", 0.0))
    gate_d_pass = forced_rate < 10.0

    if not gate_c_pass or not gate_d_pass:
        next_action = "Execution-first fixes: reduce cancel/repost churn and forced exits before any signal threshold tuning."
        ladder_step = 1
    elif not gate_b_pass:
        next_action = "Cost-model calibration: align expected cost inputs (`recent_cost_p75`, slippage assumptions) to realized trade costs."
        ladder_step = 2
    elif not gate_a_pass:
        next_action = "Signal-threshold adjustments only: revise model/gate strictness after execution and cost realism are validated."
        ladder_step = 3
    else:
        next_action = "Hold current configuration; all gates pass for this window."
        ladder_step = 0

    return {
        "gate_a_net_economics": {
            "pass": gate_a_pass,
            "aggregate_net_pnl": round(aggregate_net, 6),
            "positive_symbols": positive_symbols,
            "symbol_net": {k: round(v, 6) for k, v in symbol_net.items()},
            "rule": ">=0 net in at least 2 symbols and aggregate >=0",
        },
        "gate_b_cost_realism": {
            "pass": gate_b_pass,
            "symbols": b_results,
            "rule": "median(realized_cost_bps - expected_cost_bps) <= 3 bps per symbol (>=5 matched pairs)",
        },
        "gate_c_churn": {
            "pass": gate_c_pass,
            "symbols": c_results,
            "active_symbols": active_symbols,
            "rule": "canceled-to-filled ratio <= 3:1 on active symbols",
        },
        "gate_d_exit_quality": {
            "pass": gate_d_pass,
            "forced_close_rate_pct": round(forced_rate, 6),
            "rule": "forced/safety exits < 10% of closes",
        },
        "overall_pass": gate_a_pass and gate_b_pass and gate_c_pass and gate_d_pass,
        "recommended_ladder_step": ladder_step,
        "next_action": next_action,
    }


def _json_dump(path: Path, data: Dict[str, Any]) -> None:
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def _build_markdown_report(
    baseline: Dict[str, Any],
    decisions: Dict[str, Any],
    lifecycle: Dict[str, Any],
    closes: Dict[str, Any],
    ev_realized: Dict[str, Any],
    gates: Dict[str, Any],
) -> str:
    lines = []
    lines.append("# 24h Soundness Audit Report")
    lines.append("")
    lines.append(f"- Captured at: `{baseline['captured_at_utc']}`")
    lines.append(f"- Window start: `{baseline['window']['since_utc']}`")
    lines.append(f"- Window end: `{baseline['window']['until_utc']}`")
    lines.append(f"- Git commit: `{baseline['git']['commit']}` on `{baseline['git']['branch']}`")
    lines.append(f"- Git dirty: `{baseline['git']['dirty']}`")
    lines.append("")
    lines.append("## Gate Verdict")
    for gate_name in ["gate_a_net_economics", "gate_b_cost_realism", "gate_c_churn", "gate_d_exit_quality"]:
        gate = gates[gate_name]
        lines.append(f"- `{gate_name}`: **{'PASS' if gate['pass'] else 'FAIL'}**")
    lines.append(f"- overall: **{'PASS' if gates['overall_pass'] else 'FAIL'}**")
    lines.append("")
    lines.append("## Net PnL Decomposition")
    for symbol, d in sorted(closes["symbol_summary"].items()):
        lines.append(
            f"- `{symbol}` closes={d['close_count']} gross={d['sum_gross_pnl']:.4f} fees={d['sum_fees_usd']:.4f} net={d['sum_net_pnl']:.4f}"
        )
    lines.append("")
    lines.append("## Fill/Churn Matrix")
    for symbol, d in sorted(lifecycle["symbol_summary"].items()):
        ratio = d.get("canceled_to_filled_ratio")
        ratio_text = "inf" if ratio is None else f"{ratio:.4f}"
        lines.append(
            f"- `{symbol}` filled={d.get('filled_count',0)} canceled={d.get('canceled_count',0)} canceled_to_filled={ratio_text}"
        )
    lines.append(
        f"- maker attempts={lifecycle['maker_churn']['maker_attempts']} canceled={lifecycle['maker_churn']['maker_attempt_canceled']} cancel_rate={lifecycle['maker_churn']['maker_cancel_rate_pct']:.3f}% fallback_orders={lifecycle['maker_churn']['fallback_orders']}"
    )
    lines.append("")
    lines.append("## Expected vs Realized Cost Error")
    for symbol, d in sorted(ev_realized["symbol_summary"].items()):
        lines.append(
            f"- `{symbol}` matched={d['matched_pairs']} unmatched={d['unmatched_closes']} median_error_bps={d['median_cost_error_bps']} p75_error_bps={d['p75_cost_error_bps']}"
        )
    lines.append("")
    lines.append("## Decision Mix")
    for symbol, d in sorted(decisions["symbol_summary"].items()):
        lines.append(
            f"- `{symbol}` accepted={d['accepted']} rejected={d['rejected']} accept_rate={d['accept_rate_pct']:.3f}%"
        )
    lines.append("")
    lines.append("## Next Action")
    lines.append(f"- {gates['next_action']}")
    lines.append("")
    return "\n".join(lines)


async def run_audit(args: argparse.Namespace) -> Dict[str, Any]:
    now = _utc_now()
    window = AuditWindow(
        since=now - timedelta(hours=max(1, int(args.hours))),
        until=now,
        bucket_minutes=max(1, int(args.bucket_minutes)),
    )
    baseline = snapshot_baseline(window, args.pm2_id)

    pool = await _get_pool()
    try:
        async with pool.acquire() as conn:
            decisions = await collect_decision_metrics(conn, args.tenant_id, args.bot_id, window)
            lifecycle = await collect_order_lifecycle_metrics(conn, args.tenant_id, args.bot_id, window)
            closes = await collect_close_pnl_metrics(conn, args.tenant_id, args.bot_id, window)
            ev_realized = await collect_expected_vs_realized(conn, args.tenant_id, args.bot_id, window)
    finally:
        await pool.close()

    gates = evaluate_gates(closes, lifecycle, ev_realized)
    return {
        "baseline": baseline,
        "decisions": decisions,
        "lifecycle": lifecycle,
        "closes": closes,
        "expected_vs_realized": ev_realized,
        "gates": gates,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run 24h soundness audit pack.")
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--bot-id", required=True)
    parser.add_argument("--hours", type=int, default=24)
    parser.add_argument("--bucket-minutes", type=int, default=15)
    parser.add_argument("--pm2-id", default="75")
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    stamp = _utc_now().strftime("%Y%m%dT%H%M%SZ")
    out_dir = Path(args.output_root) / f"audit_{stamp}"
    out_dir.mkdir(parents=True, exist_ok=True)

    report = asyncio.run(run_audit(args))
    baseline = report["baseline"]
    decisions = report["decisions"]
    lifecycle = report["lifecycle"]
    closes = report["closes"]
    ev_realized = report["expected_vs_realized"]
    gates = report["gates"]

    _json_dump(out_dir / "baseline_snapshot.json", baseline)
    _json_dump(out_dir / "metrics_15m.json", {"decisions": decisions, "lifecycle": lifecycle, "closes": closes})
    _json_dump(out_dir / "expected_vs_realized.json", ev_realized)
    _json_dump(out_dir / "gate_evaluation.json", gates)
    _json_dump(out_dir / "audit_report.json", report)

    markdown = _build_markdown_report(baseline, decisions, lifecycle, closes, ev_realized, gates)
    (out_dir / "audit_report.md").write_text(markdown + "\n")

    print(json.dumps({"output_dir": str(out_dir), "overall_pass": gates["overall_pass"], "next_action": gates["next_action"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
