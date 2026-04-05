#!/usr/bin/env python3
"""Optimize runtime knobs from executed trade outcomes.

Fallback optimizer for periods where replay cannot reconstruct signals reliably.
It pairs close outcomes to nearest entry intents and searches robust thresholds
using walk-forward folds over historical rows.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import asyncpg


ROOT = Path(__file__).resolve().parents[2]


def _read_dotenv_value(key: str) -> str | None:
    path = ROOT / ".env"
    if not path.exists():
        return None
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or line.lstrip().startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        if k.strip() == key:
            return v.strip().strip('"').strip("'")
    return None


def _env_float(key: str, default: float) -> float:
    raw = os.getenv(key) or _read_dotenv_value(key)
    try:
        return float(raw) if raw is not None else default
    except Exception:
        return default


def _fmt(value: float) -> str:
    return f"{value:.6f}".rstrip("0").rstrip(".")


def _normalize_prob(value: float) -> float:
    # Some historical fields are stored as percentages (0-100) instead of probabilities (0-1).
    if value > 1.0 and value <= 100.0:
        return value / 100.0
    return value


@dataclass
class TradeRow:
    ts: float
    net_pnl: float
    p_hat: float
    pred_conf: float
    side: str
    symbol: str


async def _get_pool() -> asyncpg.Pool:
    db_url = os.getenv("BOT_TIMESCALE_URL") or _read_dotenv_value("BOT_TIMESCALE_URL")
    if not db_url:
        raise RuntimeError("BOT_TIMESCALE_URL not found in env")
    return await asyncpg.create_pool(db_url, min_size=1, max_size=4, timeout=10.0)


async def _load_rows(pool: asyncpg.Pool, tenant_id: str, bot_id: str, since: datetime) -> list[TradeRow]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            WITH closes AS (
              SELECT ts AS close_ts,
                     symbol,
                     LOWER(COALESCE(payload->>'side','')) AS close_side,
                     COALESCE((payload->>'net_pnl')::double precision,0) AS net_pnl
              FROM order_events
              WHERE tenant_id=$1 AND bot_id=$2
                AND LOWER(COALESCE(payload->>'status',''))='filled'
                AND LOWER(COALESCE(payload->>'position_effect',''))='close'
                AND ts >= $3
            ),
            paired AS (
              SELECT c.close_ts,
                     c.close_side,
                     c.symbol,
                     c.net_pnl,
                     i.snapshot_metrics,
                     ROW_NUMBER() OVER (PARTITION BY c.close_ts, c.symbol ORDER BY ABS(EXTRACT(EPOCH FROM (c.close_ts - i.created_at)))) AS rn
              FROM closes c
              JOIN order_intents i
                ON i.tenant_id=$1 AND i.bot_id=$2
               AND i.symbol=c.symbol
               AND i.created_at BETWEEN c.close_ts - INTERVAL '2 hours' AND c.close_ts
               AND LOWER(COALESCE(i.side,'')) <> c.close_side
            )
            SELECT close_ts, close_side, symbol, net_pnl, snapshot_metrics
            FROM paired
            WHERE rn=1
            """,
            tenant_id,
            bot_id,
            since,
        )

    out: list[TradeRow] = []
    for row in rows:
        sm = row["snapshot_metrics"]
        if isinstance(sm, str):
            try:
                sm = json.loads(sm)
            except Exception:
                sm = {}
        if not isinstance(sm, dict):
            sm = {}
        p_hat = sm.get("entry_p_hat")
        conf = sm.get("prediction_confidence")
        try:
            p_hat_f = _normalize_prob(float(p_hat) if p_hat is not None else 0.0)
            conf_f = _normalize_prob(float(conf) if conf is not None else 0.0)
        except Exception:
            continue
        if not (0.0 <= p_hat_f <= 1.0 and 0.0 <= conf_f <= 1.0):
            continue
        out.append(
            TradeRow(
                ts=float(row["close_ts"].timestamp()) if row["close_ts"] is not None else 0.0,
                net_pnl=float(row["net_pnl"] or 0.0),
                p_hat=p_hat_f,
                pred_conf=conf_f,
                side=str(row["close_side"] or ""),
                symbol=str(row["symbol"] or ""),
            )
        )
    return out


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _default_knobs() -> dict[str, float]:
    base_p_hat = _normalize_prob(_env_float("PREDICTION_SCORE_MIN_ML_SCORE", 0.45))
    base_conf = _normalize_prob(_env_float("PREDICTION_ONNX_MIN_CONFIDENCE", 0.39))
    base_margin = _env_float("PREDICTION_ONNX_MIN_MARGIN", 0.05)
    base_ev_min = _env_float("EV_GATE_EV_MIN", 0.021)
    base_rel = _env_float("EV_GATE_MIN_RELIABILITY_SCORE", 0.63)
    base_edge = _env_float("MIN_NET_EDGE_BPS", 10.0)
    base_be = _env_float("POSITION_GUARD_BREAKEVEN_BUFFER_BPS", 12.0)
    base_profit = _env_float("POSITION_GUARD_MIN_PROFIT_BUFFER_BPS", 14.0)
    return {
        "PREDICTION_SCORE_MIN_ML_SCORE": _clamp(base_p_hat, 0.30, 0.85),
        "PREDICTION_ONNX_MIN_CONFIDENCE": _clamp(base_conf, 0.30, 0.85),
        "PREDICTION_ONNX_MIN_MARGIN": _clamp(base_margin, 0.01, 0.20),
        "EV_GATE_EV_MIN": _clamp(base_ev_min, 0.005, 0.06),
        "EV_GATE_MIN_RELIABILITY_SCORE": _clamp(base_rel, 0.45, 0.90),
        "MIN_NET_EDGE_BPS": _clamp(base_edge, 4.0, 25.0),
        "POSITION_GUARD_BREAKEVEN_BUFFER_BPS": _clamp(base_be, 2.0, 25.0),
        "POSITION_GUARD_MIN_PROFIT_BUFFER_BPS": _clamp(base_profit, 4.0, 30.0),
    }


def _sample_knobs(rng: random.Random, base: dict[str, float], jitter_scale: float = 1.0) -> dict[str, float]:
    sampled = dict(base)
    js = max(0.05, jitter_scale)
    sampled["PREDICTION_SCORE_MIN_ML_SCORE"] = _clamp(base["PREDICTION_SCORE_MIN_ML_SCORE"] + rng.uniform(-0.20 * js, 0.25 * js), 0.30, 0.90)
    sampled["PREDICTION_ONNX_MIN_CONFIDENCE"] = _clamp(base["PREDICTION_ONNX_MIN_CONFIDENCE"] + rng.uniform(-0.15 * js, 0.20 * js), 0.25, 0.90)
    sampled["PREDICTION_ONNX_MIN_MARGIN"] = _clamp(base["PREDICTION_ONNX_MIN_MARGIN"] + rng.uniform(-0.03 * js, 0.08 * js), 0.0, 0.20)
    sampled["EV_GATE_EV_MIN"] = _clamp(base["EV_GATE_EV_MIN"] + rng.uniform(-0.01 * js, 0.02 * js), 0.0, 0.08)
    sampled["EV_GATE_MIN_RELIABILITY_SCORE"] = _clamp(base["EV_GATE_MIN_RELIABILITY_SCORE"] + rng.uniform(-0.15 * js, 0.20 * js), 0.30, 0.95)
    sampled["MIN_NET_EDGE_BPS"] = _clamp(base["MIN_NET_EDGE_BPS"] + rng.uniform(-4.0 * js, 8.0 * js), 2.0, 35.0)
    sampled["POSITION_GUARD_BREAKEVEN_BUFFER_BPS"] = _clamp(base["POSITION_GUARD_BREAKEVEN_BUFFER_BPS"] + rng.uniform(-4.0 * js, 6.0 * js), 0.0, 30.0)
    sampled["POSITION_GUARD_MIN_PROFIT_BUFFER_BPS"] = _clamp(base["POSITION_GUARD_MIN_PROFIT_BUFFER_BPS"] + rng.uniform(-4.0 * js, 8.0 * js), 0.0, 36.0)

    # Keep guard semantics valid.
    if sampled["POSITION_GUARD_MIN_PROFIT_BUFFER_BPS"] < sampled["POSITION_GUARD_BREAKEVEN_BUFFER_BPS"]:
        sampled["POSITION_GUARD_MIN_PROFIT_BUFFER_BPS"] = sampled["POSITION_GUARD_BREAKEVEN_BUFFER_BPS"]
    return sampled


def _select_rows(rows: list[TradeRow], knobs: dict[str, float]) -> list[TradeRow]:
    p_hat_thr = knobs["PREDICTION_SCORE_MIN_ML_SCORE"]
    conf_thr = knobs["PREDICTION_ONNX_MIN_CONFIDENCE"]
    margin_thr = knobs["PREDICTION_ONNX_MIN_MARGIN"]
    rel_thr = knobs["EV_GATE_MIN_RELIABILITY_SCORE"]
    # Proxy for directional margin when only p_hat/conf are available.
    return [
        r
        for r in rows
        if r.p_hat >= p_hat_thr
        and r.pred_conf >= conf_thr
        and r.pred_conf >= rel_thr
        and (r.p_hat - 0.5) >= margin_thr
    ]


def _score(rows: list[TradeRow], knobs: dict[str, float], min_trades: int) -> tuple[float, dict[str, Any]]:
    selected = _select_rows(rows, knobs)
    n = len(selected)
    sum_net = sum(r.net_pnl for r in selected)
    win_rate = (sum(1 for r in selected if r.net_pnl > 0) / n) if n else 0.0
    avg_net = (sum_net / n) if n else 0.0

    trade_penalty = max(0, min_trades - n) * 35.0
    # Keep anti-overfitting pressure: overly permissive knobs are penalized.
    aggressiveness_penalty = max(0.0, 0.45 - knobs["PREDICTION_SCORE_MIN_ML_SCORE"]) * 220.0
    loose_conf_penalty = max(0.0, 0.35 - knobs["PREDICTION_ONNX_MIN_CONFIDENCE"]) * 180.0

    score = sum_net + (win_rate * 120.0) + (avg_net * 20.0) - trade_penalty - aggressiveness_penalty - loose_conf_penalty
    return score, {
        "n": n,
        "sum_net": sum_net,
        "win_rate": win_rate,
        "avg_net": avg_net,
        "trade_penalty": trade_penalty,
        "aggressiveness_penalty": aggressiveness_penalty,
        "loose_conf_penalty": loose_conf_penalty,
    }


def _build_folds(rows: list[TradeRow], folds: int) -> list[list[TradeRow]]:
    if folds <= 1 or len(rows) < folds:
        return [rows]
    ordered = sorted(rows, key=lambda r: r.ts)
    n = len(ordered)
    step = max(1, n // folds)
    out: list[list[TradeRow]] = []
    start = 0
    for i in range(folds):
        end = n if i == folds - 1 else min(n, start + step)
        if start < end:
            out.append(ordered[start:end])
        start = end
    return out or [ordered]


def _evaluate_walk_forward(rows: list[TradeRow], knobs: dict[str, float], min_trades: int, folds: int) -> tuple[float, dict[str, Any]]:
    fold_sets = _build_folds(rows, folds)
    fold_scores: list[float] = []
    fold_n = 0
    fold_sum_net = 0.0
    fold_win_weighted = 0.0
    for fold_rows in fold_sets:
        s, meta = _score(fold_rows, knobs, min_trades=max(1, min_trades // max(1, folds)))
        fold_scores.append(s)
        fold_n += int(meta["n"])
        fold_sum_net += float(meta["sum_net"])
        fold_win_weighted += float(meta["win_rate"]) * int(meta["n"])
    mean_score = sum(fold_scores) / max(1, len(fold_scores))
    agg_win = (fold_win_weighted / fold_n) if fold_n else 0.0
    return mean_score, {
        "n": fold_n,
        "sum_net": fold_sum_net,
        "win_rate": agg_win,
        "fold_scores": fold_scores,
    }


def _side_breakdown(rows: list[TradeRow], knobs: dict[str, float]) -> dict[str, Any]:
    selected = _select_rows(rows, knobs)
    out: dict[str, dict[str, float]] = {}
    for side in ("buy", "sell"):
        bucket = [r for r in selected if r.side == side]
        n = len(bucket)
        sum_net = sum(r.net_pnl for r in bucket)
        win = (sum(1 for r in bucket if r.net_pnl > 0) / n) if n else 0.0
        out[side] = {"n": float(n), "sum_net": float(sum_net), "win_rate": float(win)}
    return out


def _write_env(path: Path, knobs: dict[str, float], meta: dict[str, Any]) -> None:
    text = "\n".join(
        [
            "# Auto-generated by optimize_env_from_executed_trades.py",
            f"# generated_at={datetime.now(timezone.utc).isoformat()}",
            f"# score={meta.get('score')}",
            f"# selected_trades={meta.get('n')}",
            f"# sum_net={meta.get('sum_net')}",
            f"# win_rate={meta.get('win_rate')}",
            "",
            f"PREDICTION_SCORE_MIN_ML_SCORE={_fmt(knobs['PREDICTION_SCORE_MIN_ML_SCORE'])}",
            f"PREDICTION_ONNX_MIN_CONFIDENCE={_fmt(knobs['PREDICTION_ONNX_MIN_CONFIDENCE'])}",
            f"PREDICTION_ONNX_MIN_MARGIN={_fmt(knobs['PREDICTION_ONNX_MIN_MARGIN'])}",
            f"EV_GATE_EV_MIN={_fmt(knobs['EV_GATE_EV_MIN'])}",
            f"EV_GATE_MIN_RELIABILITY_SCORE={_fmt(knobs['EV_GATE_MIN_RELIABILITY_SCORE'])}",
            f"MIN_NET_EDGE_BPS={_fmt(knobs['MIN_NET_EDGE_BPS'])}",
            f"POSITION_GUARD_BREAKEVEN_BUFFER_BPS={_fmt(knobs['POSITION_GUARD_BREAKEVEN_BUFFER_BPS'])}",
            f"POSITION_GUARD_MIN_PROFIT_BUFFER_BPS={_fmt(knobs['POSITION_GUARD_MIN_PROFIT_BUFFER_BPS'])}",
            "",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


async def _run(args: argparse.Namespace) -> int:
    since = datetime.now(timezone.utc) - timedelta(hours=args.hours)
    pool = await _get_pool()
    try:
        rows = await _load_rows(pool, args.tenant_id, args.bot_id, since)
    finally:
        await pool.close()

    if not rows:
        raise SystemExit("no paired close rows found for window")

    base_knobs = _default_knobs()
    rng = random.Random(args.seed)

    candidates: list[dict[str, Any]] = []
    baseline_candidate: dict[str, Any] | None = None
    for i in range(args.iterations):
        if i == 0:
            knobs = dict(base_knobs)
            is_baseline = True
        else:
            knobs = _sample_knobs(rng, base_knobs, jitter_scale=args.jitter_scale)
            is_baseline = False
        score, wf_stats = _evaluate_walk_forward(rows, knobs, args.min_trades, args.folds)
        _, in_sample = _score(rows, knobs, args.min_trades)
        side_stats = _side_breakdown(rows, knobs)
        candidates.append(
            {
                "score": score,
                "knobs": knobs,
                **wf_stats,
                "in_sample": in_sample,
                "side_breakdown": side_stats,
                "is_baseline": is_baseline,
            }
        )
        if is_baseline:
            baseline_candidate = candidates[-1]

    candidates.sort(key=lambda x: x["score"], reverse=True)
    best = candidates[0]

    output_env = Path(args.output_env)
    _write_env(output_env, best["knobs"], best)

    output_json = Path(args.output_json)
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(
        json.dumps(
            {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "tenant_id": args.tenant_id,
                "bot_id": args.bot_id,
                "hours": args.hours,
                "folds": args.folds,
                "rows": len(rows),
                "iterations": args.iterations,
                "jitter_scale": args.jitter_scale,
                "baseline": baseline_candidate,
                "best": best,
                "top5": candidates[:5],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    print(json.dumps({"rows": len(rows), "best": best}, indent=2, sort_keys=True))
    print(f"Wrote env: {output_env}")
    print(f"Wrote report: {output_json}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Optimize runtime knobs from executed trade history.")
    parser.add_argument("--tenant-id", default=os.getenv("TENANT_ID", "11111111-1111-1111-1111-111111111111"))
    parser.add_argument("--bot-id", default=os.getenv("BOT_ID", "bf167763-fee1-4f11-ab9a-6fddadf125de"))
    parser.add_argument("--hours", type=float, default=168.0)
    parser.add_argument("--iterations", type=int, default=80)
    parser.add_argument("--min-trades", type=int, default=20)
    parser.add_argument("--folds", type=int, default=3)
    parser.add_argument("--jitter-scale", type=float, default=1.0)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output-env", default=str(ROOT / "quantgambit-python" / "outputs" / "optimized.from_closes.env"))
    parser.add_argument("--output-json", default=str(ROOT / "quantgambit-python" / "outputs" / "optimization_from_closes.json"))
    args = parser.parse_args()
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
