#!/usr/bin/env python3
"""
Prediction Accuracy Report

Computes basic live prediction performance metrics by joining:
- position_events (closed) for outcomes (win/loss + PnL)
- order_intents.snapshot_metrics for the prediction payload at entry time

This is intentionally simple and robust:
- No dependence on decision_events joins
- Tolerates missing prediction fields

Usage:
  python scripts/prediction_accuracy_report.py --tenant-id ... --bot-id ... --hours 12
  python scripts/prediction_accuracy_report.py --tenant-id ... --bot-id ... --symbol ETHUSDT --hours 72
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import asyncpg

sys.path.insert(0, str(Path(__file__).parent.parent))


def _read_dotenv_value(key: str) -> Optional[str]:
    try:
        # This script is often executed from `quantgambit-python/` or repo root.
        # Search for `.env` upwards from the script location first, then cwd,
        # so BOT_TIMESCALE_URL resolves consistently.
        candidates: list[Path] = []
        candidates.append(Path(__file__).resolve().parents[2] / ".env")  # repo root
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


def _coerce_payload(value: Any) -> Dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return {}
    return {}


def _win_label(payload: Dict[str, Any]) -> Optional[bool]:
    net_pnl = payload.get("net_pnl")
    if net_pnl is None:
        net_pnl = payload.get("realized_pnl")
    try:
        if net_pnl is None:
            return None
        return float(net_pnl) > 0
    except (TypeError, ValueError):
        return None


def _aligned_with_side(side: Optional[str], pred_dir: Optional[str]) -> Optional[bool]:
    if not side or not pred_dir:
        return None
    side_n = str(side).lower()
    pred_n = str(pred_dir).lower()
    if side_n in {"buy", "long"}:
        return pred_n == "up"
    if side_n in {"sell", "short"}:
        return pred_n == "down"
    return None


@dataclass
class Row:
    symbol: str
    side: str
    strategy_id: Optional[str]
    profile_id: Optional[str]
    closed_ts: datetime
    win: Optional[bool]
    net_pnl: Optional[float]
    pred_dir: Optional[str]
    pred_conf: Optional[float]
    pred_source: Optional[str]
    entry_p_hat: Optional[float]
    entry_p_hat_source: Optional[str]
    aligned: Optional[bool]


async def _query_closed_positions(
    pool: asyncpg.Pool,
    tenant_id: str,
    bot_id: str,
    since: datetime,
    symbol: Optional[str],
) -> List[Tuple[datetime, Dict[str, Any]]]:
    query = """
    SELECT ts, payload
    FROM position_events
    WHERE tenant_id=$1
      AND bot_id=$2
      AND ts >= $3
      AND (payload->>'event_type')='closed'
    """
    params: list[Any] = [tenant_id, bot_id, since]
    if symbol:
        query += " AND (payload->>'symbol')=$4"
        params.append(symbol)
    query += " ORDER BY ts DESC"
    rows = await pool.fetch(query, *params)
    result: List[Tuple[datetime, Dict[str, Any]]] = []
    for r in rows:
        payload = _coerce_payload(r["payload"])
        result.append((r["ts"], payload))
    return result


async def _query_intent_metrics_near_entry(
    pool: asyncpg.Pool,
    tenant_id: str,
    bot_id: str,
    symbol: str,
    side: str,
    entry_ts: datetime,
) -> Dict[str, Any]:
    # Keep same heuristic as trade_forensics.py: search within +/- 60s and pick closest.
    query = """
    SELECT snapshot_metrics
    FROM order_intents
    WHERE tenant_id=$1
      AND bot_id=$2
      AND symbol=$3
      AND side=$4
      AND created_at BETWEEN ($5::timestamptz - INTERVAL '60 seconds') AND ($5::timestamptz + INTERVAL '60 seconds')
    ORDER BY ABS(EXTRACT(EPOCH FROM (created_at - $5)))
    LIMIT 1
    """
    row = await pool.fetchrow(query, tenant_id, bot_id, symbol, side, entry_ts)
    if not row:
        return {}
    return _coerce_payload(row["snapshot_metrics"])


async def _query_intent_metrics_by_client_order_id(
    pool: asyncpg.Pool,
    tenant_id: str,
    bot_id: str,
    client_order_id: str,
) -> Dict[str, Any]:
    query = """
    SELECT snapshot_metrics
    FROM order_intents
    WHERE tenant_id=$1
      AND bot_id=$2
      AND client_order_id=$3
    LIMIT 1
    """
    row = await pool.fetchrow(query, tenant_id, bot_id, client_order_id)
    if not row:
        return {}
    return _coerce_payload(row["snapshot_metrics"])


def _safe_float(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _summarize(rows: List[Row]) -> Dict[str, Any]:
    total = len(rows)
    wins = [r for r in rows if r.win is True]
    losses = [r for r in rows if r.win is False]
    aligned = [r for r in rows if r.aligned is True]
    misaligned = [r for r in rows if r.aligned is False]
    with_p_hat = [r for r in rows if r.entry_p_hat is not None and r.win is not None]

    def _rate(n: int, d: int) -> float:
        return round((n / d) * 100.0, 2) if d else 0.0

    def _brier(samples: List[Row]) -> Optional[float]:
        if not samples:
            return None
        sse = 0.0
        for r in samples:
            y = 1.0 if r.win else 0.0
            p = float(r.entry_p_hat or 0.0)
            sse += (p - y) ** 2
        return round(sse / len(samples), 6)

    def _ece(samples: List[Row], bins: int = 10) -> Optional[float]:
        if not samples:
            return None
        counts = [0] * bins
        sum_p = [0.0] * bins
        sum_y = [0.0] * bins
        for r in samples:
            p = float(r.entry_p_hat or 0.0)
            p = max(0.0, min(1.0, p))
            b = min(bins - 1, int(p * bins))
            counts[b] += 1
            sum_p[b] += p
            sum_y[b] += 1.0 if r.win else 0.0
        total_n = sum(counts)
        if total_n <= 0:
            return None
        ece = 0.0
        for i in range(bins):
            if counts[i] <= 0:
                continue
            conf = sum_p[i] / counts[i]
            acc = sum_y[i] / counts[i]
            ece += abs(acc - conf) * (counts[i] / total_n)
        return round(ece, 6)

    def _group_summary(samples: List[Row], key_fn) -> Dict[str, Any]:
        groups: Dict[str, List[Row]] = {}
        for row in samples:
            key = key_fn(row)
            if not key:
                continue
            groups.setdefault(str(key), []).append(row)
        out: Dict[str, Any] = {}
        for key, subset in sorted(groups.items(), key=lambda item: item[0]):
            wins_subset = len([r for r in subset if r.win is True])
            out[key] = {
                "trades": len(subset),
                "win_rate_pct": _rate(wins_subset, len(subset)),
                "avg_net_pnl": round(
                    sum((r.net_pnl or 0.0) for r in subset) / len(subset),
                    6,
                ) if subset else 0.0,
                "aligned_win_rate_pct": _rate(
                    len([r for r in subset if r.aligned is True and r.win is True]),
                    len([r for r in subset if r.aligned is True]),
                ),
            }
        return out

    return {
        "trades": total,
        "win_rate_pct": _rate(len(wins), total),
        "aligned_trades": len(aligned),
        "aligned_win_rate_pct": _rate(len([r for r in aligned if r.win is True]), len(aligned)),
        "misaligned_trades": len(misaligned),
        "misaligned_win_rate_pct": _rate(len([r for r in misaligned if r.win is True]), len(misaligned)),
        "missing_alignment": len([r for r in rows if r.aligned is None]),
        "p_hat_trades": len(with_p_hat),
        "p_hat_brier": _brier(with_p_hat),
        "p_hat_ece_10": _ece(with_p_hat, bins=10),
        "prediction_source_breakdown": {
            src: len([r for r in rows if r.pred_source == src])
            for src in sorted({r.pred_source for r in rows if r.pred_source})
        },
        "by_symbol": _group_summary(rows, lambda r: r.symbol),
        "by_strategy": _group_summary(rows, lambda r: r.strategy_id),
        "by_profile": _group_summary(rows, lambda r: r.profile_id),
        "by_prediction_source": _group_summary(rows, lambda r: r.pred_source),
    }


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tenant-id", required=True)
    ap.add_argument("--bot-id", required=True)
    ap.add_argument("--hours", type=int, default=12)
    ap.add_argument("--symbol", default="")
    args = ap.parse_args()

    since = datetime.now(timezone.utc) - timedelta(hours=int(args.hours))
    symbol = args.symbol.strip() or None

    pool = await _get_pool()
    try:
        closed = await _query_closed_positions(pool, args.tenant_id, args.bot_id, since, symbol)
        rows: List[Row] = []
        for closed_ts, payload in closed:
            sym = payload.get("symbol") or ""
            side = payload.get("side") or ""
            if not sym or not side:
                continue

            # Prefer direct attribution from the close payload (exact, no heuristic join).
            pred_dir = payload.get("prediction_direction")
            pred_conf = _safe_float(payload.get("prediction_confidence"))
            pred_source = payload.get("prediction_source")
            entry_p_hat = _safe_float(payload.get("entry_p_hat"))
            entry_p_hat_source = payload.get("entry_p_hat_source")
            entry_client_order_id = payload.get("entry_client_order_id")

            entry_epoch = payload.get("entry_timestamp")
            entry_ts = None
            try:
                if entry_epoch is not None:
                    entry_ts = datetime.fromtimestamp(float(entry_epoch), tz=timezone.utc)
            except (TypeError, ValueError):
                entry_ts = None

            metrics = {}
            if pred_dir is None and pred_conf is None and pred_source is None:
                if entry_client_order_id:
                    metrics = await _query_intent_metrics_by_client_order_id(
                        pool, args.tenant_id, args.bot_id, str(entry_client_order_id)
                    )
                elif entry_ts is not None:
                    metrics = await _query_intent_metrics_near_entry(
                        pool, args.tenant_id, args.bot_id, sym, side, entry_ts
                    )

            if pred_dir is None:
                pred_dir = metrics.get("prediction_direction")
            if pred_conf is None:
                pred_conf = _safe_float(metrics.get("prediction_confidence"))
            if pred_source is None:
                pred_source = metrics.get("prediction_source")
            if entry_p_hat is None:
                entry_p_hat = _safe_float(metrics.get("entry_p_hat"))
            if entry_p_hat_source is None:
                entry_p_hat_source = metrics.get("entry_p_hat_source")
            win = _win_label(payload)
            aligned = _aligned_with_side(side, pred_dir)
            net_pnl = _safe_float(payload.get("net_pnl") or payload.get("realized_pnl"))

            rows.append(
                Row(
                    symbol=sym,
                    side=side,
                    strategy_id=payload.get("strategy_id"),
                    profile_id=payload.get("profile_id"),
                    closed_ts=closed_ts,
                    win=win,
                    net_pnl=net_pnl,
                    pred_dir=pred_dir,
                    pred_conf=pred_conf,
                    pred_source=pred_source,
                    entry_p_hat=entry_p_hat,
                    entry_p_hat_source=entry_p_hat_source,
                    aligned=aligned,
                )
            )

        summary = _summarize(rows)
        print(json.dumps({"since": since.isoformat(), "symbol": symbol, "summary": summary}, indent=2, sort_keys=True))
        return 0
    finally:
        await pool.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
