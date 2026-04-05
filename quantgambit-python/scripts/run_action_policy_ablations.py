#!/usr/bin/env python3
"""Run simple action-policy ablations on replay-labeled datasets."""

from __future__ import annotations

import argparse
import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass
class AblationRow:
    p_long: float
    p_short: float
    y_long: int
    y_short: int


def _to_float(value: str, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _to_int(value: str, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _load_rows(path: Path) -> list[AblationRow]:
    rows: list[AblationRow] = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for raw in reader:
            p_long = _to_float(raw.get("p_long_win"), _to_float(raw.get("pred_p_long_win"), 0.0))
            p_short = _to_float(raw.get("p_short_win"), _to_float(raw.get("pred_p_short_win"), 0.0))
            y_long = _to_int(raw.get("y_long"), 0)
            y_short = _to_int(raw.get("y_short"), 0)
            rows.append(AblationRow(p_long=p_long, p_short=p_short, y_long=y_long, y_short=y_short))
    return rows


def _score_policy(rows: Iterable[AblationRow], *, p_thresh: float, margin_thresh: float, mode: str) -> dict:
    trades = 0
    wins = 0
    long_trades = 0
    short_trades = 0
    for row in rows:
        p_star = max(row.p_long, row.p_short)
        margin = abs(row.p_long - row.p_short)
        if mode in {"gate_only", "direction_gate"} and (p_star < p_thresh or margin < margin_thresh):
            continue
        if mode == "baseline":
            # Baseline proxy for this script: choose long if both probabilities are unavailable.
            choose_long = True
        elif mode == "direction_only":
            choose_long = row.p_long >= row.p_short
        else:
            choose_long = row.p_long >= row.p_short
        trades += 1
        if choose_long:
            long_trades += 1
            wins += 1 if row.y_long == 1 else 0
        else:
            short_trades += 1
            wins += 1 if row.y_short == 1 else 0
    win_rate = (wins / trades) if trades else 0.0
    return {
        "mode": mode,
        "trades": trades,
        "wins": wins,
        "win_rate": win_rate,
        "long_trades": long_trades,
        "short_trades": short_trades,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run action-policy ablations from CSV predictions/labels.")
    parser.add_argument("--input", required=True, help="CSV containing p_long_win, p_short_win, y_long, y_short.")
    parser.add_argument("--output", default=None, help="Optional output JSON path.")
    parser.add_argument("--p-thresh", type=float, default=0.65, help="Minimum max win probability threshold.")
    parser.add_argument("--margin-thresh", type=float, default=0.0, help="Minimum |p_long-p_short| threshold.")
    args = parser.parse_args()

    rows = _load_rows(Path(args.input))
    if not rows:
        raise SystemExit("no_rows")
    result = {
        "input": str(args.input),
        "rows": len(rows),
        "p_thresh": float(args.p_thresh),
        "margin_thresh": float(args.margin_thresh),
        "ablations": [
            _score_policy(rows, p_thresh=args.p_thresh, margin_thresh=args.margin_thresh, mode="baseline"),
            _score_policy(rows, p_thresh=args.p_thresh, margin_thresh=args.margin_thresh, mode="gate_only"),
            _score_policy(rows, p_thresh=args.p_thresh, margin_thresh=args.margin_thresh, mode="direction_only"),
            _score_policy(rows, p_thresh=args.p_thresh, margin_thresh=args.margin_thresh, mode="direction_gate"),
        ],
    }
    payload = json.dumps(result, indent=2, sort_keys=True)
    if args.output:
        Path(args.output).write_text(payload, encoding="utf-8")
    print(payload)


if __name__ == "__main__":
    main()
