#!/usr/bin/env python3
"""
Prediction outcome report for live and shadow providers.

This script evaluates prediction accuracy against realized market movement from
feature snapshots (no trade execution required), so you can validate ONNX in
shadow mode even when the bot is not placing orders.

Usage:
  ./venv311/bin/python scripts/prediction_shadow_outcome_report.py \
    --tenant-id ... --bot-id ... --hours 6 --horizon-sec 60
"""

from __future__ import annotations

import argparse
import bisect
import json
import math
import os
import pathlib
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import redis  # type: ignore

_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


VALID_DIRS = {"up", "down", "flat"}
CLASS_ORDER = ("down", "flat", "up")


def _safe_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _extract_ts_seconds(event: dict[str, Any], payload: dict[str, Any]) -> Optional[float]:
    for key in ("ts_canon_us", "ts_recv_us"):
        raw = event.get(key)
        if raw is None:
            continue
        ts = _safe_float(raw)
        if ts is None:
            continue
        # Canonical timestamps are microseconds in this pipeline.
        if ts > 1_000_000_000_000:
            return ts / 1_000_000.0
        return ts
    for raw in (payload.get("timestamp"), event.get("timestamp")):
        ts = _safe_float(raw)
        if ts is not None:
            return ts
    return None


def _extract_price(payload: dict[str, Any]) -> Optional[float]:
    features = payload.get("features") or {}
    market_context = payload.get("market_context") or {}
    for raw in (
        market_context.get("price"),
        features.get("price"),
        market_context.get("last"),
        features.get("last"),
    ):
        price = _safe_float(raw)
        if price is not None and price > 0:
            return price
    return None


def _normalize_probs(prediction: dict[str, Any]) -> Optional[dict[str, float]]:
    probs_raw = prediction.get("probs")
    probs: dict[str, float] = {}
    if isinstance(probs_raw, dict):
        for key in CLASS_ORDER:
            value = _safe_float(probs_raw.get(key))
            if value is None:
                return None
            probs[key] = max(0.0, min(1.0, value))
    else:
        p_up = _safe_float(prediction.get("p_up"))
        p_down = _safe_float(prediction.get("p_down"))
        p_flat = _safe_float(prediction.get("p_flat"))
        if p_up is None or p_down is None:
            return None
        if p_flat is None:
            p_flat = max(0.0, 1.0 - p_up - p_down)
        probs = {
            "up": max(0.0, min(1.0, p_up)),
            "down": max(0.0, min(1.0, p_down)),
            "flat": max(0.0, min(1.0, p_flat)),
        }

    total = sum(probs.values())
    if total <= 0:
        return None
    if abs(total - 1.0) > 0.005:
        # Normalize for robust scoring while keeping deterministic behavior.
        for key in probs:
            probs[key] = probs[key] / total
    return probs


def _extract_prediction(payload: dict[str, Any], key: str) -> Optional[dict[str, Any]]:
    pred = payload.get(key)
    if not isinstance(pred, dict):
        return None

    direction = str(pred.get("direction") or "").lower().strip()
    if direction not in VALID_DIRS:
        return None

    confidence = _safe_float(pred.get("confidence"))
    probs = _normalize_probs(pred)
    if confidence is None and probs is not None:
        confidence = _safe_float(probs.get(direction), 0.0)

    return {
        "direction": direction,
        "confidence": confidence if confidence is not None else 0.0,
        "source": pred.get("source"),
        "probs": probs,
    }


def _classify_outcome(ret_bps: float, flat_threshold_bps: float) -> str:
    if ret_bps >= flat_threshold_bps:
        return "up"
    if ret_bps <= -flat_threshold_bps:
        return "down"
    return "flat"


def _brier_term(probs: dict[str, float], outcome: str) -> float:
    acc = 0.0
    for cls in CLASS_ORDER:
        target = 1.0 if cls == outcome else 0.0
        p = float(probs.get(cls, 0.0))
        acc += (p - target) ** 2
    return acc / float(len(CLASS_ORDER))


def _conf_bin_label(value: float) -> str:
    idx = max(0, min(4, int(value * 5.0)))
    lo = idx * 0.2
    hi = lo + 0.2
    return f"{lo:.1f}-{hi:.1f}"


def _session_label(ts_sec: float) -> str:
    hour = time.gmtime(ts_sec).tm_hour
    if 12 <= hour < 20:
        return "us"
    if 7 <= hour < 15:
        return "europe"
    return "asia"


def _ece_from_confidence_bins(confidence_bins: dict[str, dict[str, int]]) -> Optional[float]:
    total = 0
    weighted = 0.0
    for label, data in confidence_bins.items():
        n = int(data.get("n") or 0)
        correct = int(data.get("correct") or 0)
        if n <= 0:
            continue
        try:
            lo_s, hi_s = label.split("-", 1)
            conf = (float(lo_s) + float(hi_s)) / 2.0
        except Exception:
            conf = 0.5
        acc = float(correct) / float(n)
        weighted += abs(acc - conf) * float(n)
        total += n
    if total <= 0:
        return None
    return weighted / float(total)


def _compute_ml_score(
    exact_accuracy: Optional[float],
    directional_accuracy: Optional[float],
    ece_top1: Optional[float],
) -> Optional[float]:
    if exact_accuracy is None:
        return None
    dir_acc = directional_accuracy if directional_accuracy is not None else exact_accuracy
    cal_component = 1.0 - min(1.0, ece_top1 if ece_top1 is not None else 1.0)
    score = ((exact_accuracy * 0.55) + (dir_acc * 0.30) + (cal_component * 0.15)) * 100.0
    return max(0.0, min(100.0, score))


def _compute_promotion_score_v2_report(
    exact_accuracy: Optional[float],
    directional_accuracy: Optional[float],
    ece_top1: Optional[float],
    brier: Optional[float],
    avg_realized_bps: Optional[float],
) -> Optional[float]:
    if exact_accuracy is None:
        return None
    dir_acc = directional_accuracy if directional_accuracy is not None else exact_accuracy
    ece_component = 1.0 - min(1.0, (ece_top1 if ece_top1 is not None else 1.0) / 0.25)
    brier_component = 1.0 - min(1.0, (brier if brier is not None else 1.0) / 0.25)
    realized = float(avg_realized_bps if avg_realized_bps is not None else 0.0)
    realized_component = 0.5 + (0.5 * math.tanh(realized / 2.0))
    score = (
        (exact_accuracy * 0.30)
        + (dir_acc * 0.25)
        + (realized_component * 0.25)
        + (ece_component * 0.10)
        + (brier_component * 0.10)
    ) * 100.0
    return max(0.0, min(100.0, score))


def _optimize_threshold(
    samples: List[dict[str, float]],
    min_samples: int,
    min_coverage: float,
) -> dict[str, Any]:
    total = len(samples)
    if total < max(1, min_samples):
        return {
            "status": "insufficient_samples",
            "total_samples": total,
            "recommended_min_confidence": None,
        }
    best = None
    thresholds = [i / 100.0 for i in range(5, 96, 2)]
    for threshold in thresholds:
        selected = [item for item in samples if float(item.get("confidence", 0.0)) >= threshold]
        selected_n = len(selected)
        if selected_n < min_samples:
            continue
        coverage = selected_n / float(total)
        if coverage < min_coverage:
            continue
        correct = sum(1 for item in selected if int(item.get("correct", 0)) == 1)
        accuracy = correct / float(selected_n)
        score = (accuracy * 0.85) + (coverage * 0.15)
        candidate = {
            "threshold": threshold,
            "selected_samples": selected_n,
            "coverage": coverage,
            "accuracy": accuracy,
            "score": score,
        }
        if best is None:
            best = candidate
            continue
        if candidate["score"] > best["score"]:
            best = candidate
            continue
        if candidate["score"] == best["score"] and candidate["accuracy"] > best["accuracy"]:
            best = candidate
            continue
        if (
            candidate["score"] == best["score"]
            and candidate["accuracy"] == best["accuracy"]
            and candidate["coverage"] > best["coverage"]
        ):
            best = candidate
    if best is None:
        return {
            "status": "no_threshold_met_coverage_constraints",
            "total_samples": total,
            "recommended_min_confidence": None,
        }
    return {
        "status": "ok",
        "total_samples": total,
        "recommended_min_confidence": round(float(best["threshold"]), 4),
        "selected_samples": int(best["selected_samples"]),
        "coverage": round(float(best["coverage"]), 4),
        "accuracy": round(float(best["accuracy"]), 4),
        "score": round(float(best["score"]), 4),
    }


def _optimize_threshold_walk_forward(
    samples: List[dict[str, float]],
    min_samples: int,
    min_coverage: float,
    splits: int = 4,
    min_train_frac: float = 0.5,
) -> dict[str, Any]:
    total = len(samples)
    if total < max(1, min_samples):
        return {
            "status": "insufficient_samples",
            "total_samples": total,
            "recommended_min_confidence": None,
        }
    ordered = sorted(samples, key=lambda item: float(item.get("ts", 0.0)))
    min_train = max(min_samples, int(total * max(0.2, min(0.9, min_train_frac))))
    if min_train >= total:
        return {
            "status": "insufficient_oos_window",
            "total_samples": total,
            "recommended_min_confidence": None,
        }
    splits = max(1, int(splits))
    window = total - min_train
    step = max(1, window // splits)
    fold_thresholds: list[float] = []
    weighted_accuracy_sum = 0.0
    weighted_coverage_sum = 0.0
    weighted_count = 0
    folds_used = 0
    for fold in range(splits):
        train_end = min_train + (fold * step)
        if train_end >= total - 1:
            break
        test_end = min(total, train_end + step)
        train_samples = ordered[:train_end]
        test_samples = ordered[train_end:test_end]
        if len(test_samples) < min_samples:
            continue
        train_best = _optimize_threshold(
            train_samples,
            min_samples=min_samples,
            min_coverage=min_coverage,
        )
        threshold = _safe_float(train_best.get("recommended_min_confidence"))
        if threshold is None:
            continue
        selected = [item for item in test_samples if float(item.get("confidence", 0.0)) >= float(threshold)]
        if len(selected) < min_samples:
            continue
        coverage = len(selected) / float(len(test_samples))
        if coverage < min_coverage:
            continue
        correct = sum(1 for item in selected if int(item.get("correct", 0)) == 1)
        accuracy = correct / float(len(selected))
        folds_used += 1
        fold_thresholds.append(float(threshold))
        weighted_accuracy_sum += accuracy * float(len(selected))
        weighted_coverage_sum += coverage * float(len(test_samples))
        weighted_count += int(len(selected))
    if folds_used <= 0 or weighted_count <= 0:
        return {
            "status": "no_oos_threshold_met_coverage_constraints",
            "total_samples": total,
            "recommended_min_confidence": None,
        }
    fold_thresholds_sorted = sorted(fold_thresholds)
    mid = len(fold_thresholds_sorted) // 2
    if len(fold_thresholds_sorted) % 2 == 1:
        rec = fold_thresholds_sorted[mid]
    else:
        rec = (fold_thresholds_sorted[mid - 1] + fold_thresholds_sorted[mid]) / 2.0
    return {
        "status": "ok",
        "total_samples": total,
        "recommended_min_confidence": round(float(rec), 4),
        "folds_used": int(folds_used),
        "oos_accuracy": round(float(weighted_accuracy_sum / float(weighted_count)), 4),
        "oos_coverage": round(float(weighted_coverage_sum / float(folds_used)), 4),
        "thresholds_by_fold": [round(float(v), 4) for v in fold_thresholds],
    }


@dataclass
class ProviderStats:
    samples: int = 0
    exact_correct: int = 0
    directional_samples: int = 0
    directional_correct: int = 0
    avg_realized_bps_sum: float = 0.0
    avg_conf_sum: float = 0.0
    brier_sum: float = 0.0
    brier_count: int = 0
    confusion: dict[str, dict[str, int]] = field(
        default_factory=lambda: {d: {c: 0 for c in CLASS_ORDER} for d in CLASS_ORDER}
    )
    confidence_bins: dict[str, dict[str, int]] = field(
        default_factory=lambda: {f"{i*0.2:.1f}-{(i+1)*0.2:.1f}": {"n": 0, "correct": 0} for i in range(5)}
    )

    def add(
        self,
        pred_direction: str,
        pred_conf: float,
        probs: Optional[dict[str, float]],
        outcome: str,
        realized_bps: float,
    ) -> None:
        self.samples += 1
        self.avg_realized_bps_sum += realized_bps
        self.avg_conf_sum += pred_conf
        self.confusion[pred_direction][outcome] += 1

        correct = pred_direction == outcome
        if correct:
            self.exact_correct += 1

        if pred_direction in {"up", "down"}:
            self.directional_samples += 1
            if outcome == pred_direction:
                self.directional_correct += 1

        label = _conf_bin_label(pred_conf)
        self.confidence_bins[label]["n"] += 1
        if correct:
            self.confidence_bins[label]["correct"] += 1

        if probs is not None:
            self.brier_sum += _brier_term(probs, outcome)
            self.brier_count += 1

    def to_dict(self) -> dict[str, Any]:
        exact_acc = (self.exact_correct / self.samples) if self.samples else None
        dir_acc = (
            (self.directional_correct / self.directional_samples)
            if self.directional_samples
            else None
        )
        directional_coverage = (
            (self.directional_samples / self.samples) if self.samples else None
        )
        ece_top1 = _ece_from_confidence_bins(self.confidence_bins)
        return {
            "samples": self.samples,
            "exact_accuracy": exact_acc,
            "directional_accuracy_nonflat_preds": dir_acc,
            "directional_accuracy_all_preds": exact_acc,
            "directional_coverage_nonflat_preds": directional_coverage,
            "avg_realized_bps": (self.avg_realized_bps_sum / self.samples) if self.samples else None,
            "avg_confidence": (self.avg_conf_sum / self.samples) if self.samples else None,
            "ece_top1": ece_top1,
            "multiclass_brier": (self.brier_sum / self.brier_count) if self.brier_count else None,
            "brier_samples": self.brier_count,
            "confusion_pred_vs_outcome": self.confusion,
            "confidence_bins": {
                key: {
                    "n": value["n"],
                    "accuracy": (value["correct"] / value["n"]) if value["n"] else None,
                }
                for key, value in self.confidence_bins.items()
            },
        }


@dataclass
class SnapshotRow:
    ts: float
    price: float
    predictions: dict[str, dict[str, Any]]


def _load_rows(
    client: redis.Redis,
    stream: str,
    count: int,
    min_ts: Optional[float],
    symbol_filter: Optional[str],
) -> dict[str, List[SnapshotRow]]:
    rows_by_symbol: dict[str, List[SnapshotRow]] = defaultdict(list)
    raw_rows = client.xrevrange(stream, count=count)
    for _, fields in raw_rows:
        raw = fields.get("data")
        if not raw:
            continue
        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        payload = event.get("payload")
        if not isinstance(payload, dict):
            continue
        symbol = str(event.get("symbol") or payload.get("symbol") or "").strip()
        if not symbol:
            continue
        if symbol_filter and symbol != symbol_filter:
            continue
        ts = _extract_ts_seconds(event, payload)
        price = _extract_price(payload)
        if ts is None or price is None:
            continue
        if min_ts is not None and ts < min_ts:
            continue
        pred_live = _extract_prediction(payload, "prediction")
        pred_shadow = _extract_prediction(payload, "prediction_shadow")
        if pred_live is None and pred_shadow is None:
            continue
        predictions: dict[str, dict[str, Any]] = {}
        if pred_live is not None:
            predictions["live"] = pred_live
        if pred_shadow is not None:
            predictions["shadow"] = pred_shadow
        rows_by_symbol[symbol].append(SnapshotRow(ts=ts, price=price, predictions=predictions))

    for symbol in rows_by_symbol:
        rows_by_symbol[symbol].sort(key=lambda item: item.ts)
    return rows_by_symbol


def _evaluate_provider(
    rows_by_symbol: dict[str, List[SnapshotRow]],
    provider_key: str,
    horizon_sec: float,
    flat_threshold_bps: float,
    min_opt_samples: int,
    min_opt_coverage: float,
) -> dict[str, Any]:
    overall = ProviderStats()
    per_symbol: dict[str, ProviderStats] = {}
    per_symbol_session: dict[str, ProviderStats] = {}
    threshold_samples_overall: list[dict[str, float]] = []
    threshold_samples_by_symbol: dict[str, list[dict[str, float]]] = defaultdict(list)
    threshold_samples_by_symbol_session: dict[str, list[dict[str, float]]] = defaultdict(list)

    for symbol, rows in rows_by_symbol.items():
        timestamps = [row.ts for row in rows]
        symbol_stats = ProviderStats()
        for idx, row in enumerate(rows):
            pred = row.predictions.get(provider_key)
            if pred is None:
                continue
            target_ts = row.ts + horizon_sec
            j = bisect.bisect_left(timestamps, target_ts, lo=idx + 1)
            if j >= len(rows):
                continue
            future = rows[j]
            if row.price <= 0:
                continue
            ret_bps = ((future.price - row.price) / row.price) * 1e4
            outcome = _classify_outcome(ret_bps, flat_threshold_bps=flat_threshold_bps)
            conf = float(pred.get("confidence") or 0.0)
            probs = pred.get("probs")
            if probs is not None and not isinstance(probs, dict):
                probs = None
            session = _session_label(row.ts)
            symbol_session_key = f"{symbol}:{session}"
            session_stats = per_symbol_session.setdefault(symbol_session_key, ProviderStats())
            is_correct = int(str(pred.get("direction")) == outcome)
            sample = {"confidence": conf, "correct": float(is_correct), "ts": float(row.ts)}
            threshold_samples_overall.append(sample)
            threshold_samples_by_symbol[symbol].append(sample)
            threshold_samples_by_symbol_session[symbol_session_key].append(sample)

            symbol_stats.add(
                pred_direction=str(pred.get("direction")),
                pred_conf=conf,
                probs=probs,
                outcome=outcome,
                realized_bps=ret_bps,
            )
            session_stats.add(
                pred_direction=str(pred.get("direction")),
                pred_conf=conf,
                probs=probs,
                outcome=outcome,
                realized_bps=ret_bps,
            )
            overall.add(
                pred_direction=str(pred.get("direction")),
                pred_conf=conf,
                probs=probs,
                outcome=outcome,
                realized_bps=ret_bps,
            )
        per_symbol[symbol] = symbol_stats

    return {
        "overall": overall.to_dict(),
        "per_symbol": {
            symbol: stats.to_dict()
            for symbol, stats in sorted(per_symbol.items(), key=lambda item: item[0])
        },
        "per_symbol_session": {
            key: stats.to_dict()
            for key, stats in sorted(per_symbol_session.items(), key=lambda item: item[0])
        },
        "recommended_min_confidence": {
            "overall": _optimize_threshold(
                threshold_samples_overall,
                min_samples=min_opt_samples,
                min_coverage=min_opt_coverage,
            ),
            "by_symbol": {
                symbol: _optimize_threshold(
                    samples,
                    min_samples=min_opt_samples,
                    min_coverage=min_opt_coverage,
                )
                for symbol, samples in sorted(threshold_samples_by_symbol.items(), key=lambda item: item[0])
            },
            "by_symbol_session": {
                key: _optimize_threshold(
                    samples,
                    min_samples=min_opt_samples,
                    min_coverage=min_opt_coverage,
                )
                for key, samples in sorted(
                    threshold_samples_by_symbol_session.items(), key=lambda item: item[0]
                )
            },
        },
        "recommended_min_confidence_oos": {
            "overall": _optimize_threshold_walk_forward(
                threshold_samples_overall,
                min_samples=min_opt_samples,
                min_coverage=min_opt_coverage,
            ),
            "by_symbol": {
                symbol: _optimize_threshold_walk_forward(
                    samples,
                    min_samples=min_opt_samples,
                    min_coverage=min_opt_coverage,
                )
                for symbol, samples in sorted(threshold_samples_by_symbol.items(), key=lambda item: item[0])
            },
            "by_symbol_session": {
                key: _optimize_threshold_walk_forward(
                    samples,
                    min_samples=min_opt_samples,
                    min_coverage=min_opt_coverage,
                )
                for key, samples in sorted(
                    threshold_samples_by_symbol_session.items(), key=lambda item: item[0]
                )
            },
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--redis-url", default=os.getenv("REDIS_URL", "redis://localhost:6379"))
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--bot-id", required=True)
    parser.add_argument("--count", type=int, default=20000, help="Max feature snapshots to load")
    parser.add_argument("--hours", type=float, default=6.0, help="Lookback window from now")
    parser.add_argument("--horizon-sec", type=float, default=60.0, help="Outcome horizon in seconds")
    parser.add_argument(
        "--flat-threshold-bps",
        type=float,
        default=3.0,
        help="Absolute return threshold to classify as flat",
    )
    parser.add_argument(
        "--threshold-min-samples",
        type=int,
        default=60,
        help="Minimum samples required for confidence-threshold recommendation.",
    )
    parser.add_argument(
        "--threshold-min-coverage",
        type=float,
        default=0.20,
        help="Minimum coverage required for confidence-threshold recommendation.",
    )
    parser.add_argument(
        "--drift-provider",
        choices=["live", "shadow"],
        default="shadow",
        help="Provider report to use when emitting drift snapshot.",
    )
    parser.add_argument(
        "--drift-min-samples",
        type=int,
        default=80,
        help="Minimum samples required before declaring symbol-level drift status.",
    )
    parser.add_argument(
        "--drift-max-brier",
        type=float,
        default=0.26,
        help="Symbol-level drift threshold for multiclass Brier score.",
    )
    parser.add_argument(
        "--drift-max-ece",
        type=float,
        default=0.18,
        help="Symbol-level drift threshold for top-1 ECE.",
    )
    parser.add_argument(
        "--write-drift-snapshot",
        action="store_true",
        help="Write symbol-aware prediction drift snapshot to Redis for runtime blocking.",
    )
    parser.add_argument(
        "--drift-snapshot-key",
        default="",
        help="Redis snapshot key override (default: quantgambit:{tenant}:{bot}:prediction:drift:latest).",
    )
    parser.add_argument(
        "--drift-snapshot-ttl-sec",
        type=int,
        default=180,
        help="TTL for written drift snapshot key.",
    )
    parser.add_argument(
        "--score-provider",
        choices=["live", "shadow"],
        default="shadow",
        help="Provider report to use when emitting score snapshot.",
    )
    parser.add_argument(
        "--score-min-samples",
        type=int,
        default=200,
        help="Minimum per-symbol sample count for score snapshot gating status.",
    )
    parser.add_argument(
        "--score-min-ml-score",
        type=float,
        default=60.0,
        help="Minimum per-symbol ML score for status=ok in score snapshot.",
    )
    parser.add_argument(
        "--score-min-exact-accuracy",
        type=float,
        default=0.50,
        help="Minimum per-symbol exact accuracy ratio for status=ok in score snapshot.",
    )
    parser.add_argument(
        "--score-max-ece",
        type=float,
        default=0.20,
        help="Maximum per-symbol ECE ratio for status=ok in score snapshot.",
    )
    parser.add_argument(
        "--score-min-avg-realized-bps",
        type=float,
        default=-9999.0,
        help="Minimum per-symbol avg_realized_bps for status=ok in score snapshot.",
    )
    parser.add_argument(
        "--score-min-promotion-score-v2",
        type=float,
        default=0.0,
        help="Minimum per-symbol promotion_score_v2 for status=ok in score snapshot.",
    )
    parser.add_argument(
        "--score-min-directional-coverage",
        type=float,
        default=0.10,
        help="Minimum per-symbol directional_coverage_nonflat_preds ratio for status=ok in score snapshot.",
    )
    parser.add_argument(
        "--write-score-snapshot",
        action="store_true",
        help="Write symbol-aware prediction score snapshot to Redis for runtime ONNX symbol gating.",
    )
    parser.add_argument(
        "--score-snapshot-key",
        default="",
        help="Redis snapshot key override (default: quantgambit:{tenant}:{bot}:prediction:score:latest).",
    )
    parser.add_argument(
        "--score-snapshot-ttl-sec",
        type=int,
        default=300,
        help="TTL for written score snapshot key.",
    )
    parser.add_argument("--symbol", default="", help="Optional symbol filter (e.g. ETHUSDT)")
    args = parser.parse_args()

    stream = f"events:features:{args.tenant_id}:{args.bot_id}"
    symbol_filter = args.symbol.strip() or None
    min_ts = time.time() - float(args.hours) * 3600.0 if args.hours > 0 else None

    client = redis.from_url(args.redis_url, decode_responses=True)
    rows_by_symbol = _load_rows(
        client=client,
        stream=stream,
        count=max(1, int(args.count)),
        min_ts=min_ts,
        symbol_filter=symbol_filter,
    )

    if not rows_by_symbol:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": "no_prediction_rows",
                    "stream": stream,
                    "symbol": symbol_filter,
                }
            )
        )
        return 2

    live_report = _evaluate_provider(
        rows_by_symbol=rows_by_symbol,
        provider_key="live",
        horizon_sec=float(args.horizon_sec),
        flat_threshold_bps=float(args.flat_threshold_bps),
        min_opt_samples=max(1, int(args.threshold_min_samples)),
        min_opt_coverage=max(0.0, min(1.0, float(args.threshold_min_coverage))),
    )
    shadow_report = _evaluate_provider(
        rows_by_symbol=rows_by_symbol,
        provider_key="shadow",
        horizon_sec=float(args.horizon_sec),
        flat_threshold_bps=float(args.flat_threshold_bps),
        min_opt_samples=max(1, int(args.threshold_min_samples)),
        min_opt_coverage=max(0.0, min(1.0, float(args.threshold_min_coverage))),
    )

    live_samples = int(live_report["overall"]["samples"])
    shadow_samples = int(shadow_report["overall"]["samples"])
    comparison = {
        "sample_delta_shadow_minus_live": shadow_samples - live_samples,
        "exact_accuracy_delta_shadow_minus_live": None,
    }
    live_acc = live_report["overall"]["exact_accuracy"]
    shadow_acc = shadow_report["overall"]["exact_accuracy"]
    if live_acc is not None and shadow_acc is not None:
        comparison["exact_accuracy_delta_shadow_minus_live"] = shadow_acc - live_acc

    drift_provider_key = str(args.drift_provider)
    drift_source = shadow_report if drift_provider_key == "shadow" else live_report
    symbol_drift = {}
    drift_triggered = False
    for symbol, stats in (drift_source.get("per_symbol") or {}).items():
        samples = int(stats.get("samples") or 0)
        brier = _safe_float(stats.get("multiclass_brier"))
        ece_top1 = _safe_float(stats.get("ece_top1"))
        if samples < int(args.drift_min_samples):
            status = "insufficient"
        else:
            status = "ok"
            if brier is not None and brier > float(args.drift_max_brier):
                status = "drift"
            if ece_top1 is not None and ece_top1 > float(args.drift_max_ece):
                status = "drift"
        if status == "drift":
            drift_triggered = True
        symbol_drift[symbol] = {
            "status": status,
            "samples": samples,
            "multiclass_brier": brier,
            "ece_top1": ece_top1,
        }
    drift_snapshot = {
        "status": "drift" if drift_triggered else "ok",
        "provider": drift_provider_key,
        "timestamp": time.time(),
        "thresholds": {
            "min_samples": int(args.drift_min_samples),
            "max_brier": float(args.drift_max_brier),
            "max_ece_top1": float(args.drift_max_ece),
        },
        "symbols": symbol_drift,
    }
    if args.write_drift_snapshot:
        snapshot_key = args.drift_snapshot_key.strip() or (
            f"quantgambit:{args.tenant_id}:{args.bot_id}:prediction:drift:latest"
        )
        client.set(snapshot_key, json.dumps(drift_snapshot, allow_nan=False))
        client.expire(snapshot_key, max(30, int(args.drift_snapshot_ttl_sec)))
        drift_snapshot["snapshot_key"] = snapshot_key
        drift_snapshot["snapshot_ttl_sec"] = max(30, int(args.drift_snapshot_ttl_sec))

    score_provider_key = str(args.score_provider)
    score_source = shadow_report if score_provider_key == "shadow" else live_report
    symbol_scores = {}
    score_triggered = False
    for symbol, stats in (score_source.get("per_symbol") or {}).items():
        samples = int(stats.get("samples") or 0)
        exact_acc = _safe_float(stats.get("exact_accuracy"))
        dir_acc = _safe_float(stats.get("directional_accuracy_nonflat_preds"))
        directional_coverage = _safe_float(stats.get("directional_coverage_nonflat_preds"))
        ece_top1 = _safe_float(stats.get("ece_top1"))
        brier = _safe_float(stats.get("multiclass_brier"))
        avg_realized_bps = _safe_float(stats.get("avg_realized_bps"))
        ml_score = _compute_ml_score(exact_acc, dir_acc, ece_top1)
        promotion_score_v2 = _compute_promotion_score_v2_report(
            exact_accuracy=exact_acc,
            directional_accuracy=dir_acc,
            ece_top1=ece_top1,
            brier=brier,
            avg_realized_bps=avg_realized_bps,
        )
        status = "ok"
        if samples < int(args.score_min_samples):
            status = "insufficient"
        if exact_acc is not None and exact_acc < float(args.score_min_exact_accuracy):
            status = "blocked"
        if ece_top1 is not None and ece_top1 > float(args.score_max_ece):
            status = "blocked"
        if ml_score is not None and ml_score < float(args.score_min_ml_score):
            status = "blocked"
        if (
            promotion_score_v2 is not None
            and promotion_score_v2 < float(args.score_min_promotion_score_v2)
        ):
            status = "blocked"
        if avg_realized_bps is not None and avg_realized_bps < float(args.score_min_avg_realized_bps):
            status = "blocked"
        if (
            directional_coverage is not None
            and directional_coverage < float(args.score_min_directional_coverage)
        ):
            status = "blocked"
        if status == "blocked":
            score_triggered = True
        symbol_scores[symbol] = {
            "status": status,
            "samples": samples,
            "ml_score": ml_score,
            "promotion_score_v2": promotion_score_v2,
            "exact_accuracy": exact_acc,
            "directional_accuracy": dir_acc,
            "directional_coverage_nonflat_preds": directional_coverage,
            "avg_realized_bps": avg_realized_bps,
            "ece_top1": ece_top1,
            "multiclass_brier": brier,
        }
    score_snapshot = {
        "status": "blocked" if score_triggered else "ok",
        "provider": score_provider_key,
        "timestamp": time.time(),
        "thresholds": {
            "min_samples": int(args.score_min_samples),
            "min_ml_score": float(args.score_min_ml_score),
            "min_promotion_score_v2": float(args.score_min_promotion_score_v2),
            "min_exact_accuracy": float(args.score_min_exact_accuracy),
            "min_avg_realized_bps": float(args.score_min_avg_realized_bps),
            "min_directional_coverage_nonflat_preds": float(args.score_min_directional_coverage),
            "max_ece_top1": float(args.score_max_ece),
        },
        "symbols": symbol_scores,
    }
    if args.write_score_snapshot:
        score_key = args.score_snapshot_key.strip() or (
            f"quantgambit:{args.tenant_id}:{args.bot_id}:prediction:score:latest"
        )
        client.set(score_key, json.dumps(score_snapshot, allow_nan=False))
        client.expire(score_key, max(30, int(args.score_snapshot_ttl_sec)))
        score_snapshot["snapshot_key"] = score_key
        score_snapshot["snapshot_ttl_sec"] = max(30, int(args.score_snapshot_ttl_sec))

    result = {
        "ok": True,
        "stream": stream,
        "symbol_filter": symbol_filter,
        "lookback_hours": args.hours,
        "horizon_sec": args.horizon_sec,
        "flat_threshold_bps": args.flat_threshold_bps,
        "rows_loaded": sum(len(v) for v in rows_by_symbol.values()),
        "symbols_loaded": sorted(rows_by_symbol.keys()),
        "providers": {
            "shadow": shadow_report,
            "live": live_report,
        },
        "comparison": comparison,
        "drift_snapshot": drift_snapshot,
        "score_snapshot": score_snapshot,
    }
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
