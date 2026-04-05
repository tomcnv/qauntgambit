#!/usr/bin/env python3
"""
Backtest-driven .env optimizer (calibration loop).

Runs repeated replay backtests with different knob sets, scores outcomes, and
writes the best configuration as an env fragment.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
VENV_PYTHON = ROOT / "quantgambit-python" / "venv" / "bin" / "python"


def _read_env_file(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        out[key.strip()] = value.strip().strip('"').strip("'")
    return out


def _float_env(env: dict[str, str], key: str, default: float) -> float:
    raw = env.get(key)
    if raw is None:
        return default
    try:
        return float(raw)
    except Exception:
        return default


def _format_env_value(value: float | int | str) -> str:
    if isinstance(value, float):
        return f"{value:.6f}".rstrip("0").rstrip(".")
    return str(value)


@dataclass
class CandidateResult:
    knobs: dict[str, float]
    score: float
    report: dict[str, Any]
    objective_parts: dict[str, float]
    fold_scores: list[float]
    fold_reports: list[dict[str, Any]]


def _build_search_space(base: dict[str, float]) -> dict[str, tuple[float, float]]:
    return {
        "EV_GATE_EV_MIN": (max(0.005, base["EV_GATE_EV_MIN"] - 0.008), min(0.05, base["EV_GATE_EV_MIN"] + 0.008)),
        "EV_GATE_MIN_RELIABILITY_SCORE": (0.50, 0.85),
        "PREDICTION_ONNX_MIN_CONFIDENCE": (0.30, 0.60),
        "PREDICTION_ONNX_MIN_MARGIN": (0.02, 0.15),
        "EV_GATE_P_MARGIN_UNCALIBRATED": (0.0, 0.08),
        "MIN_NET_EDGE_BPS": (5.0, 20.0),
        "POSITION_GUARD_BREAKEVEN_BUFFER_BPS": (3.0, 20.0),
        "POSITION_GUARD_MIN_PROFIT_BUFFER_BPS": (6.0, 24.0),
    }


def _sample_candidate(
    rng: random.Random,
    space: dict[str, tuple[float, float]],
    base: dict[str, float],
    jitter_scale: float = 0.35,
) -> dict[str, float]:
    candidate: dict[str, float] = {}
    for key, (lo, hi) in space.items():
        center = base.get(key, (lo + hi) / 2.0)
        span = (hi - lo) * jitter_scale
        sampled = center + rng.uniform(-span, span)
        sampled = max(lo, min(hi, sampled))
        candidate[key] = sampled
    # Maintain ordering relationship: min profit buffer should be >= breakeven buffer.
    if candidate["POSITION_GUARD_MIN_PROFIT_BUFFER_BPS"] < candidate["POSITION_GUARD_BREAKEVEN_BUFFER_BPS"]:
        candidate["POSITION_GUARD_MIN_PROFIT_BUFFER_BPS"] = candidate["POSITION_GUARD_BREAKEVEN_BUFFER_BPS"]
    return candidate


def _run_replay(input_path: Path, knobs: dict[str, float], timeout_sec: int) -> dict[str, Any]:
    with tempfile.NamedTemporaryFile(prefix="calib_replay_", suffix=".json", delete=False) as tmp:
        output_path = Path(tmp.name)
    cmd = [
        str(VENV_PYTHON),
        "-m",
        "quantgambit.backtesting.cli",
        "replay",
        "--input",
        str(input_path),
        "--simulate",
        "--output",
        str(output_path),
    ]
    env = os.environ.copy()
    for key, value in knobs.items():
        env[key] = _format_env_value(value)
    proc = subprocess.run(cmd, cwd=str(ROOT / "quantgambit-python"), env=env, capture_output=True, text=True, timeout=timeout_sec)
    if proc.returncode != 0:
        raise RuntimeError(f"replay failed ({proc.returncode}): {proc.stderr.strip() or proc.stdout.strip()}")
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    try:
        output_path.unlink(missing_ok=True)
    except Exception:
        pass
    return payload


def _load_jsonl_lines(path: Path) -> list[str]:
    lines: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            lines.append(line)
    return lines


def _write_jsonl_slice(lines: list[str], start: int, end: int) -> Path:
    with tempfile.NamedTemporaryFile(prefix="calib_slice_", suffix=".jsonl", delete=False) as tmp:
        out_path = Path(tmp.name)
    out_path.write_text("\n".join(lines[start:end]) + "\n", encoding="utf-8")
    return out_path


def _build_walk_forward_folds(total_rows: int, folds: int, train_ratio: float) -> list[tuple[int, int, int, int]]:
    if folds <= 1:
        return [(0, max(0, int(total_rows * train_ratio)), 0, total_rows)]
    train_end0 = max(1, min(total_rows - 1, int(total_rows * train_ratio)))
    remainder = total_rows - train_end0
    if remainder <= 0:
        return [(0, train_end0, 0, total_rows)]
    step = max(1, remainder // folds)
    out: list[tuple[int, int, int, int]] = []
    for i in range(folds):
        test_start = train_end0 + i * step
        test_end = total_rows if i == folds - 1 else min(total_rows, test_start + step)
        if test_start >= total_rows or test_start >= test_end:
            continue
        out.append((0, test_start, test_start, test_end))
    return out or [(0, train_end0, train_end0, total_rows)]


def _evaluate_candidate(
    *,
    input_path: Path,
    knobs: dict[str, float],
    timeout_sec: int,
    min_trades: int,
    drawdown_target_pct: float,
    walk_forward_folds: int,
    train_ratio: float,
) -> CandidateResult:
    if walk_forward_folds <= 1:
        payload = _run_replay(input_path, knobs, timeout_sec=timeout_sec)
        score, parts = _score_report(payload, min_trades=min_trades, drawdown_target_pct=drawdown_target_pct)
        return CandidateResult(
            knobs=dict(knobs),
            score=score,
            report=payload.get("report") or {},
            objective_parts=parts,
            fold_scores=[score],
            fold_reports=[payload.get("report") or {}],
        )

    lines = _load_jsonl_lines(input_path)
    folds = _build_walk_forward_folds(len(lines), walk_forward_folds, train_ratio)
    fold_scores: list[float] = []
    fold_reports: list[dict[str, Any]] = []
    total_trades = 0.0
    realized_pnl = 0.0
    max_dd = 0.0
    win_rate_weighted_num = 0.0

    for _, _, test_start, test_end in folds:
        test_file = _write_jsonl_slice(lines, test_start, test_end)
        try:
            payload = _run_replay(test_file, knobs, timeout_sec=timeout_sec)
        finally:
            try:
                test_file.unlink(missing_ok=True)
            except Exception:
                pass
        score, _ = _score_report(payload, min_trades=min_trades, drawdown_target_pct=drawdown_target_pct)
        fold_scores.append(score)
        rep = payload.get("report") or {}
        fold_reports.append(rep)
        trades = float(rep.get("total_trades") or 0.0)
        pnl = float(rep.get("realized_pnl") or 0.0)
        dd = float(rep.get("max_drawdown_pct") or 0.0)
        wr = float(rep.get("win_rate") or 0.0)
        total_trades += trades
        realized_pnl += pnl
        max_dd = max(max_dd, dd)
        win_rate_weighted_num += wr * trades

    mean_score = sum(fold_scores) / max(1, len(fold_scores))
    agg_win_rate = (win_rate_weighted_num / total_trades) if total_trades > 0 else 0.0
    aggregate_report = {
        "total_trades": int(total_trades),
        "realized_pnl": realized_pnl,
        "win_rate": agg_win_rate,
        "max_drawdown_pct": max_dd,
        "fold_count": len(fold_scores),
    }
    _, objective_parts = _score_report({"report": aggregate_report}, min_trades=min_trades, drawdown_target_pct=drawdown_target_pct)
    return CandidateResult(
        knobs=dict(knobs),
        score=mean_score,
        report=aggregate_report,
        objective_parts=objective_parts,
        fold_scores=fold_scores,
        fold_reports=fold_reports,
    )


def _score_report(payload: dict[str, Any], min_trades: int, drawdown_target_pct: float) -> tuple[float, dict[str, float]]:
    report = payload.get("report") or {}
    total_trades = float(report.get("total_trades") or 0.0)
    realized_pnl = float(report.get("realized_pnl") or 0.0)
    win_rate = float(report.get("win_rate") or 0.0)
    max_drawdown_pct = float(report.get("max_drawdown_pct") or 0.0)
    total_fees = float(report.get("total_fees") or 0.0)

    trade_penalty = 0.0
    if total_trades < min_trades:
        trade_penalty = (min_trades - total_trades) * 100.0
    drawdown_penalty = max(0.0, max_drawdown_pct - drawdown_target_pct) * 75.0
    fee_penalty = total_fees * 0.15
    win_bonus = win_rate * 40.0
    pnl_component = realized_pnl

    score = pnl_component + win_bonus - drawdown_penalty - trade_penalty - fee_penalty
    return score, {
        "pnl_component": pnl_component,
        "win_bonus": win_bonus,
        "drawdown_penalty": drawdown_penalty,
        "trade_penalty": trade_penalty,
        "fee_penalty": fee_penalty,
        "total_trades": total_trades,
    }


def _write_env_fragment(path: Path, knobs: dict[str, float], meta: dict[str, Any]) -> None:
    lines = [
        "# Auto-generated by optimize_env_via_backtest.py",
        f"# generated_at={datetime.now(timezone.utc).isoformat()}",
        f"# score={meta.get('score')}",
        f"# total_trades={meta.get('total_trades')}",
        f"# realized_pnl={meta.get('realized_pnl')}",
        f"# win_rate={meta.get('win_rate')}",
        f"# max_drawdown_pct={meta.get('max_drawdown_pct')}",
        "",
    ]
    for key in sorted(knobs.keys()):
        lines.append(f"{key}={_format_env_value(knobs[key])}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Optimize env knobs via replay calibration loop.")
    parser.add_argument("--input", required=True, help="Replay snapshots JSONL input.")
    parser.add_argument("--iterations", type=int, default=24, help="Number of candidates to evaluate.")
    parser.add_argument("--seed", type=int, default=42, help="Random seed.")
    parser.add_argument("--timeout-sec", type=int, default=120, help="Timeout per replay run.")
    parser.add_argument("--min-trades", type=int, default=10, help="Minimum acceptable trades.")
    parser.add_argument("--drawdown-target-pct", type=float, default=8.0, help="Max drawdown target percent.")
    parser.add_argument("--walk-forward-folds", type=int, default=1, help="Use N chronological out-of-sample folds (1 disables).")
    parser.add_argument("--train-ratio", type=float, default=0.7, help="Initial train ratio before first walk-forward fold.")
    parser.add_argument(
        "--output-env",
        default=str(ROOT / "quantgambit-python" / "outputs" / "optimized.env"),
        help="Path to write optimized env fragment.",
    )
    parser.add_argument(
        "--output-json",
        default=str(ROOT / "quantgambit-python" / "outputs" / "optimization_report.json"),
        help="Path to write optimization report JSON.",
    )
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        raise SystemExit(f"input not found: {input_path}")
    if not VENV_PYTHON.exists():
        raise SystemExit(f"venv python not found: {VENV_PYTHON}")
    if args.walk_forward_folds < 1:
        raise SystemExit("--walk-forward-folds must be >= 1")
    if args.train_ratio <= 0.0 or args.train_ratio >= 1.0:
        raise SystemExit("--train-ratio must be between 0 and 1")

    env_file = ROOT / ".env"
    raw_env = _read_env_file(env_file)
    baseline = {
        "EV_GATE_EV_MIN": _float_env(raw_env, "EV_GATE_EV_MIN", 0.021),
        "EV_GATE_MIN_RELIABILITY_SCORE": _float_env(raw_env, "EV_GATE_MIN_RELIABILITY_SCORE", 0.63),
        "PREDICTION_ONNX_MIN_CONFIDENCE": _float_env(raw_env, "PREDICTION_ONNX_MIN_CONFIDENCE", 0.39),
        "PREDICTION_ONNX_MIN_MARGIN": _float_env(raw_env, "PREDICTION_ONNX_MIN_MARGIN", 0.05),
        "EV_GATE_P_MARGIN_UNCALIBRATED": _float_env(raw_env, "EV_GATE_P_MARGIN_UNCALIBRATED", 0.02),
        "MIN_NET_EDGE_BPS": _float_env(raw_env, "MIN_NET_EDGE_BPS", 10.0),
        "POSITION_GUARD_BREAKEVEN_BUFFER_BPS": _float_env(raw_env, "POSITION_GUARD_BREAKEVEN_BUFFER_BPS", 12.0),
        "POSITION_GUARD_MIN_PROFIT_BUFFER_BPS": _float_env(raw_env, "POSITION_GUARD_MIN_PROFIT_BUFFER_BPS", 14.0),
    }
    search_space = _build_search_space(baseline)
    rng = random.Random(args.seed)

    results: list[CandidateResult] = []

    # Always evaluate baseline first.
    baseline_result = _evaluate_candidate(
        input_path=input_path,
        knobs=baseline,
        timeout_sec=args.timeout_sec,
        min_trades=args.min_trades,
        drawdown_target_pct=args.drawdown_target_pct,
        walk_forward_folds=args.walk_forward_folds,
        train_ratio=args.train_ratio,
    )
    results.append(baseline_result)

    for _ in range(max(0, args.iterations - 1)):
        knobs = _sample_candidate(rng, search_space, baseline)
        result = _evaluate_candidate(
            input_path=input_path,
            knobs=knobs,
            timeout_sec=args.timeout_sec,
            min_trades=args.min_trades,
            drawdown_target_pct=args.drawdown_target_pct,
            walk_forward_folds=args.walk_forward_folds,
            train_ratio=args.train_ratio,
        )
        results.append(result)

    results.sort(key=lambda r: r.score, reverse=True)
    best = results[0]

    output_env = Path(args.output_env)
    output_env.parent.mkdir(parents=True, exist_ok=True)
    _write_env_fragment(
        output_env,
        best.knobs,
        {
            "score": round(best.score, 4),
            "total_trades": best.report.get("total_trades"),
            "realized_pnl": best.report.get("realized_pnl"),
            "win_rate": best.report.get("win_rate"),
            "max_drawdown_pct": best.report.get("max_drawdown_pct"),
        },
    )

    output_json = Path(args.output_json)
    output_json.parent.mkdir(parents=True, exist_ok=True)
    report_payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "input": str(input_path),
        "iterations": args.iterations,
        "walk_forward_folds": args.walk_forward_folds,
        "train_ratio": args.train_ratio,
        "baseline": baseline,
        "best": {
            "score": round(best.score, 6),
            "knobs": best.knobs,
            "report": best.report,
            "objective_parts": best.objective_parts,
            "fold_scores": best.fold_scores,
            "fold_reports": best.fold_reports,
        },
        "top5": [
            {
                "rank": i + 1,
                "score": round(item.score, 6),
                "knobs": item.knobs,
                "report": item.report,
                "objective_parts": item.objective_parts,
                "fold_scores": item.fold_scores,
            }
            for i, item in enumerate(results[:5])
        ],
    }
    output_json.write_text(json.dumps(report_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(json.dumps(report_payload["best"], indent=2, sort_keys=True))
    print(f"\nWrote optimized env fragment: {output_env}")
    print(f"Wrote optimization report: {output_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
