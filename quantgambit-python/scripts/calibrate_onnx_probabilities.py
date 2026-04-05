#!/usr/bin/env python3
"""
Fit per-class Platt calibration for ONNX class probabilities and persist to model metadata.

This script:
1) loads model metadata (feature_keys, class_labels)
2) runs ONNX inference over a labeled dataset CSV
3) fits one-vs-rest Platt scaling per class on a holdout split
4) writes probability_calibration.per_class to metadata JSON

Usage:
  source venv/bin/activate
  python scripts/calibrate_onnx_probabilities.py \
    --dataset prediction_dataset.csv \
    --model-meta models/registry/latest.json \
    --model-path models/registry/latest.onnx
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import pathlib
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from typing import Any

_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from quantgambit.signals.prediction_providers import OnnxPredictionProvider


@dataclass
class CalibrationClassResult:
    a: float
    b: float
    sample_count: int
    brier_before: float
    brier_after: float
    ece_before: float
    ece_after: float
    reliability_after: float


def _logit(p: float) -> float:
    eps = 1e-6
    p = max(eps, min(1.0 - eps, float(p)))
    return math.log(p / (1.0 - p))


def _sigmoid(z: float) -> float:
    if z >= 40:
        return 1.0
    if z <= -40:
        return 0.0
    return 1.0 / (1.0 + math.exp(-z))


def _apply_logit_affine(prob: float, a: float, b: float) -> float:
    return _sigmoid((a * _logit(prob)) + b)


def _fit_logit_affine_platt(
    predictions: list[float],
    outcomes: list[int],
    max_iter: int = 500,
    lr: float = 0.05,
    tol: float = 1e-7,
) -> tuple[float, float]:
    # Identity transform in the provider's calibration space.
    a = 1.0
    b = 0.0
    n = max(1, len(predictions))
    x = [_logit(p) for p in predictions]

    for _ in range(max_iter):
        grad_a = 0.0
        grad_b = 0.0
        for xi, y in zip(x, outcomes):
            p = _sigmoid((a * xi) + b)
            err = p - y
            grad_a += err * xi
            grad_b += err
        grad_a /= n
        grad_b /= n
        a_new = a - (lr * grad_a)
        b_new = b - (lr * grad_b)
        if abs(a_new - a) < tol and abs(b_new - b) < tol:
            a, b = a_new, b_new
            break
        a, b = a_new, b_new
    return float(a), float(b)


def _binary_metrics(predictions: list[float], outcomes: list[int], a: float | None = None, b: float | None = None) -> tuple[float, float, float]:
    n = len(predictions)
    if n == 0:
        return 1.0, 1.0, 0.0
    if a is None or b is None:
        calibrated = [max(0.0, min(1.0, p)) for p in predictions]
    else:
        calibrated = [_apply_logit_affine(p, a, b) for p in predictions]

    brier = sum((p - y) ** 2 for p, y in zip(calibrated, outcomes)) / n

    # 10-bin ECE
    ece = 0.0
    bins = 10
    for bi in range(bins):
        lo = bi / bins
        hi = (bi + 1) / bins
        idx = [i for i, p in enumerate(calibrated) if (lo <= p < hi) or (bi == bins - 1 and p == hi)]
        if not idx:
            continue
        conf = sum(calibrated[i] for i in idx) / len(idx)
        acc = sum(outcomes[i] for i in idx) / len(idx)
        ece += (len(idx) / n) * abs(acc - conf)
    reliability = 1.0 - ece
    return float(brier), float(ece), float(reliability)


def _load_meta(path: pathlib.Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    feature_keys = data.get("feature_keys")
    class_labels = data.get("class_labels")
    if not isinstance(feature_keys, list) or not feature_keys:
        raise ValueError(f"Invalid feature_keys in {path}")
    if not isinstance(class_labels, list) or not class_labels:
        raise ValueError(f"Invalid class_labels in {path}")
    return data


def _resolve_model_path(model_path: str, meta_path: pathlib.Path) -> str:
    if not model_path:
        return model_path
    path = pathlib.Path(model_path)
    if path.is_absolute():
        return str(path)
    candidate = (meta_path.parent / path).resolve()
    if candidate.exists():
        return str(candidate)
    return str(path)


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _load_rows(dataset: pathlib.Path, feature_keys: list[str], class_labels: list[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with dataset.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            label = str(row.get("label", "")).strip()
            if label not in class_labels:
                continue
            ts = _to_float(row.get("timestamp"), default=0.0)
            features = {k: _to_float(row.get(k), default=0.0) for k in feature_keys}
            rows.append({"timestamp": ts, "label": label, "features": features})
    rows.sort(key=lambda x: x["timestamp"])
    return rows


def _class_balance(rows: list[dict[str, Any]], class_labels: list[str]) -> dict[str, float]:
    total = len(rows)
    if total <= 0:
        return {label: 0.0 for label in class_labels}
    counts = {label: 0 for label in class_labels}
    for row in rows:
        label = str(row.get("label") or "")
        if label in counts:
            counts[label] += 1
    return {label: (counts[label] / total) for label in class_labels}


def select_calibration_source(
    *,
    class_labels: list[str],
    live_rows: list[dict[str, Any]],
    fallback_rows: list[dict[str, Any]],
    min_live_samples: int,
    min_class_ratio: float,
) -> tuple[str, list[dict[str, Any]], str | None]:
    if live_rows:
        ratios = _class_balance(live_rows, class_labels)
        min_ratio = min(ratios.values()) if ratios else 0.0
        if len(live_rows) >= int(min_live_samples) and min_ratio >= float(min_class_ratio):
            return "live", live_rows, None
        return (
            "fallback",
            fallback_rows,
            f"live_guardrail_failed:min_samples={len(live_rows)},min_ratio={min_ratio:.4f}",
        )
    return "fallback", fallback_rows, "live_dataset_unavailable"


def _fit_ovr_platt(
    samples: list[dict[str, Any]],
    class_labels: list[str],
    provider: OnnxPredictionProvider,
) -> tuple[dict[str, CalibrationClassResult], dict[str, Any]]:
    total = len(samples)
    if total < 120:
        return {}, {
            "total_samples": total,
            "fit_samples": 0,
            "eval_samples": 0,
            "dropped_samples": total,
            "calibrated_classes": [],
            "skipped_classes": {"_global": "insufficient_samples"},
        }
    # Fit on earlier rows, validate acceptance on newer rows.
    split = max(60, int(total * 0.7))
    split = min(total - 60, split)
    fit_samples = samples[:split]
    eval_samples = samples[split:]
    probs_fit: dict[str, list[float]] = {label: [] for label in class_labels}
    outcomes_fit: dict[str, list[int]] = {label: [] for label in class_labels}
    probs_eval: dict[str, list[float]] = {label: [] for label in class_labels}
    outcomes_eval: dict[str, list[int]] = {label: [] for label in class_labels}
    dropped = 0

    for idx, sample in enumerate(samples):
        pred = provider.build_prediction(sample["features"], {}, timestamp=sample["timestamp"])
        if not isinstance(pred, dict):
            dropped += 1
            continue
        probs = pred.get("probs_raw") or pred.get("probs")
        if not isinstance(probs, dict):
            dropped += 1
            continue

        true_label = sample["label"]
        for label in class_labels:
            value = _to_float(probs.get(label), default=0.0)
            outcome = 1 if true_label == label else 0
            if idx < split:
                probs_fit[label].append(value)
                outcomes_fit[label].append(outcome)
            else:
                probs_eval[label].append(value)
                outcomes_eval[label].append(outcome)

    results: dict[str, CalibrationClassResult] = {}
    skipped: dict[str, str] = {}

    for label in class_labels:
        preds_fit = probs_fit[label]
        outcomes_fit_label = outcomes_fit[label]
        preds_eval = probs_eval[label]
        outcomes_eval_label = outcomes_eval[label]
        n = len(preds_fit)
        pos = sum(outcomes_fit_label)
        neg = n - pos
        if n < 50:
            skipped[label] = f"insufficient_samples:{n}"
            continue
        if len(preds_eval) < 30:
            skipped[label] = f"insufficient_eval_samples:{len(preds_eval)}"
            continue
        if pos < 10 or neg < 10:
            skipped[label] = f"class_imbalance:pos={pos},neg={neg}"
            continue

        a, b = _fit_logit_affine_platt(preds_fit, outcomes_fit_label)
        # Reject numerically unstable calibrators.
        if not (0.1 <= a <= 10.0 and -10.0 <= b <= 10.0):
            skipped[label] = f"unstable_params:a={a:.4f},b={b:.4f}"
            continue
        brier_before, ece_before, _ = _binary_metrics(preds_eval, outcomes_eval_label)
        brier_after, ece_after, rel_after = _binary_metrics(preds_eval, outcomes_eval_label, a, b)
        # Accept only when out-of-sample quality does not worsen materially.
        if (ece_after > (ece_before + 0.003)) or (brier_after > (brier_before + 0.003)):
            skipped[label] = (
                f"no_improvement:"
                f"ece_before={ece_before:.4f},ece_after={ece_after:.4f},"
                f"brier_before={brier_before:.4f},brier_after={brier_after:.4f}"
            )
            continue
        results[label] = CalibrationClassResult(
            a=float(a),
            b=float(b),
            sample_count=n,
            brier_before=float(brier_before),
            brier_after=float(brier_after),
            ece_before=float(ece_before),
            ece_after=float(ece_after),
            reliability_after=float(rel_after),
        )

    summary = {
        "total_samples": len(samples),
        "fit_samples": len(fit_samples),
        "eval_samples": len(eval_samples),
        "dropped_samples": dropped,
        "calibrated_classes": list(results.keys()),
        "skipped_classes": skipped,
    }
    return results, summary


def _classify_skipped_classes(skipped: Any) -> str:
    if not isinstance(skipped, dict):
        return "unknown"
    values = [str(v or "") for v in skipped.values()]
    if any("unstable_params" in v for v in values):
        return "unstable_params"
    if any("no_improvement" in v for v in values):
        return "no_improvement"
    if any("class_imbalance" in v for v in values):
        return "class_imbalance"
    if any("insufficient_eval_samples" in v for v in values):
        return "insufficient_eval_samples"
    if any("insufficient_samples" in v for v in values):
        return "insufficient_samples"
    return "unknown"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default="prediction_dataset.csv")
    parser.add_argument(
        "--live-dataset",
        default="",
        help="Optional live rolling dataset CSV. Used first when it meets guardrails.",
    )
    parser.add_argument(
        "--live-from-stream",
        action="store_true",
        help="Export a fresh live dataset from Redis stream before calibration.",
    )
    parser.add_argument(
        "--fallback-dataset",
        default="",
        help="Optional fallback dataset CSV. Defaults to --dataset, or metadata fields.",
    )
    parser.add_argument("--model-meta", default="models/registry/latest.json")
    parser.add_argument("--model-path", default=None)
    parser.add_argument(
        "--expert-id",
        default="",
        help="Optional expert id when calibrating a routed ONNX expert inside model metadata.",
    )
    parser.add_argument(
        "--calibration-fraction",
        type=float,
        default=0.30,
        help="Fraction of most recent rows to use for calibration holdout.",
    )
    parser.add_argument("--min-calibration-samples", type=int, default=500)
    parser.add_argument(
        "--min-live-samples",
        type=int,
        default=1500,
        help="Minimum rows required to accept --live-dataset for calibration.",
    )
    parser.add_argument(
        "--min-class-ratio",
        type=float,
        default=0.05,
        help="Minimum ratio each class must have in the selected dataset.",
    )
    parser.add_argument("--redis-url", default=None, help="Redis URL override for live export.")
    parser.add_argument("--stream", default="events:features", help="Feature stream for live export.")
    parser.add_argument("--tail-count", type=int, default=50000, help="Tail count for live export.")
    parser.add_argument("--hours", type=float, default=24.0, help="Lookback window in hours for live export.")
    parser.add_argument("--horizon-sec", type=float, default=60.0, help="Label horizon for live export.")
    parser.add_argument("--up-threshold", type=float, default=0.001, help="Up threshold for live export.")
    parser.add_argument("--down-threshold", type=float, default=-0.001, help="Down threshold for live export.")
    parser.add_argument(
        "--label-source",
        default="future_return",
        choices=["future_return", "tp_sl", "order_fill", "order_pnl", "order_exit_pnl"],
        help="Label source for live export.",
    )
    parser.add_argument("--tenant-id", default=None, help="Tenant ID for live export (order labels).")
    parser.add_argument("--bot-id", default=None, help="Bot ID for live export (order labels).")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    meta_path = pathlib.Path(args.model_meta)
    if not meta_path.exists():
        raise SystemExit(f"model_meta_not_found: {meta_path}")

    meta = _load_meta(meta_path)
    expert_id = str(args.expert_id or "").strip()
    selected_expert_index: int | None = None
    selected_expert_payload: dict[str, Any] | None = None
    if expert_id:
        experts = meta.get("experts")
        if not isinstance(experts, list):
            raise SystemExit("expert_id_requested_but_no_experts_in_meta")
        for idx, item in enumerate(experts):
            if isinstance(item, dict) and str(item.get("id") or "").strip() == expert_id:
                selected_expert_index = idx
                selected_expert_payload = item
                break
        if selected_expert_payload is None:
            raise SystemExit(f"expert_not_found:{expert_id}")

    feature_keys = [str(x) for x in meta["feature_keys"]]
    class_labels = [str(x) for x in meta["class_labels"]]
    if selected_expert_payload is not None:
        expert_feature_keys = selected_expert_payload.get("feature_keys")
        expert_class_labels = selected_expert_payload.get("class_labels")
        if isinstance(expert_feature_keys, list) and expert_feature_keys:
            feature_keys = [str(x) for x in expert_feature_keys]
        if isinstance(expert_class_labels, list) and expert_class_labels:
            class_labels = [str(x) for x in expert_class_labels]

    model_path = args.model_path or str(
        (selected_expert_payload or {}).get("model_path")
        or (selected_expert_payload or {}).get("onnx_path")
        or meta.get("onnx_path")
        or ""
    )
    if not model_path:
        raise SystemExit("model_path_missing")
    model_path = _resolve_model_path(model_path, meta_path)

    provider_config: dict[str, Any] = {}
    if selected_expert_payload is not None:
        existing = selected_expert_payload.get("provider_config")
        if isinstance(existing, dict):
            provider_config = dict(existing)
        if isinstance(selected_expert_payload.get("probability_calibration"), dict):
            provider_config["probability_calibration"] = selected_expert_payload.get("probability_calibration")
    else:
        existing = meta.get("provider_config")
        if isinstance(existing, dict):
            provider_config = dict(existing)

    provider = OnnxPredictionProvider(
        model_path=model_path,
        feature_keys=feature_keys,
        class_labels=class_labels,
        provider_config=provider_config,
        refresh_interval_sec=0.0,
    )
    if not provider.validate(time.time()):
        raise SystemExit("onnx_session_init_failed")

    generated_live_dataset: pathlib.Path | None = None
    if args.live_from_stream and not args.live_dataset:
        with tempfile.NamedTemporaryFile(prefix="live_prediction_dataset_", suffix=".csv", delete=False) as tmp:
            generated_live_dataset = pathlib.Path(tmp.name)
        export_cmd = [
            sys.executable,
            str(_ROOT / "scripts" / "export_prediction_dataset.py"),
            "--output",
            str(generated_live_dataset),
            "--stream",
            str(args.stream),
            "--tail-count",
            str(args.tail_count),
            "--hours",
            str(args.hours),
            "--horizon-sec",
            str(args.horizon_sec),
            "--up-threshold",
            str(args.up_threshold),
            "--down-threshold",
            str(args.down_threshold),
            "--label-source",
            str(args.label_source),
        ]
        if args.redis_url:
            export_cmd.extend(["--redis-url", str(args.redis_url)])
        if args.tenant_id:
            export_cmd.extend(["--tenant-id", str(args.tenant_id)])
        if args.bot_id:
            export_cmd.extend(["--bot-id", str(args.bot_id)])
        subprocess.run(export_cmd, check=True)
        args.live_dataset = str(generated_live_dataset)

    # Hybrid source selection: prefer live dataset when quality guardrails pass.
    fallback_candidates = [
        args.fallback_dataset.strip(),
        args.dataset.strip(),
        str(((meta.get("probability_calibration") or {}).get("dataset") or "")).strip(),
        str(meta.get("input") or "").strip(),
    ]
    fallback_dataset_raw = next((item for item in fallback_candidates if item), "")
    live_dataset_raw = args.live_dataset.strip()

    def _load_dataset(path_raw: str) -> tuple[pathlib.Path | None, list[dict[str, Any]], str | None]:
        if not path_raw:
            return None, [], "path_missing"
        path = pathlib.Path(path_raw)
        if not path.exists():
            return path, [], "dataset_not_found"
        rows_local = _load_rows(path, feature_keys, class_labels)
        if len(rows_local) < args.min_calibration_samples:
            return path, rows_local, f"insufficient_rows:{len(rows_local)}"
        return path, rows_local, None

    selected_source = "fallback"
    selected_reason: str | None = None
    selected_path: pathlib.Path | None = None
    selected_rows: list[dict[str, Any]] = []
    live_rows_count = 0

    live_path, live_rows, live_error = _load_dataset(live_dataset_raw)
    if live_path is not None:
        live_rows_count = len(live_rows)
        if live_error is not None:
            selected_reason = live_error
        else:
            selected_source, selected_rows, selected_reason = select_calibration_source(
                class_labels=class_labels,
                live_rows=live_rows,
                fallback_rows=[],
                min_live_samples=args.min_live_samples,
                min_class_ratio=args.min_class_ratio,
            )
            if selected_source == "live":
                selected_path = live_path

    if not selected_rows:
        fallback_path, fallback_rows, fallback_error = _load_dataset(fallback_dataset_raw)
        if fallback_path is None:
            raise SystemExit(f"fallback_dataset_missing:{fallback_dataset_raw}")
        if fallback_error is not None:
            raise SystemExit(f"fallback_dataset_invalid:{fallback_path}:{fallback_error}")
        selected_path = fallback_path
        selected_rows = fallback_rows
        selected_source = "fallback"

    frac = max(0.05, min(0.95, float(args.calibration_fraction)))
    split_at = int(len(selected_rows) * (1.0 - frac))
    calib_rows = selected_rows[split_at:]
    if len(calib_rows) < 100:
        raise SystemExit(f"insufficient_holdout_rows:{len(calib_rows)}")

    fitted, summary = _fit_ovr_platt(calib_rows, class_labels, provider)
    if not fitted:
        skipped_kind = _classify_skipped_classes(summary.get("skipped_classes"))
        retryable = bool(
            selected_source == "live"
            and skipped_kind
            in {
                "unstable_params",
                "no_improvement",
                "class_imbalance",
                "insufficient_eval_samples",
                "insufficient_samples",
            }
        )
        print(
            json.dumps(
                {
                    "status": "failed",
                    "reason": "no_calibration_fitted",
                    "failure_kind": skipped_kind,
                    "retryable": retryable,
                    "source": selected_source,
                    "dataset": str(selected_path),
                    "summary": summary,
                },
                sort_keys=True,
            )
        )
        return 1

    calibration_payload = {
        "method": "platt_ovr",
        "fitted_at": time.time(),
        "expert_id": expert_id or None,
        "dataset": str(selected_path),
        "source": selected_source,
        "selection": {
            "preferred": "live",
            "selected": selected_source,
            "fallback_reason": selected_reason,
            "live_dataset": str(live_path) if live_path else None,
            "fallback_dataset": str(fallback_dataset_raw or ""),
            "live_rows": live_rows_count,
            "selected_rows": len(selected_rows),
            "min_live_samples": int(args.min_live_samples),
            "min_class_ratio": float(args.min_class_ratio),
        },
        "holdout_samples": len(calib_rows),
        "calibration_fraction": frac,
        "per_class": {
            label: {
                "a": res.a,
                "b": res.b,
                "sample_count": res.sample_count,
                "brier_before": res.brier_before,
                "brier_after": res.brier_after,
                "ece_before": res.ece_before,
                "ece_after": res.ece_after,
                "reliability_score": res.reliability_after,
            }
            for label, res in fitted.items()
        },
        "summary": summary,
    }

    output = dict(meta)
    if selected_expert_index is not None and selected_expert_payload is not None:
        experts_out = list(output.get("experts") or [])
        expert_out = dict(experts_out[selected_expert_index] or {})
        expert_out["probability_calibration"] = calibration_payload
        provider_cfg = expert_out.get("provider_config")
        if isinstance(provider_cfg, dict):
            provider_cfg = dict(provider_cfg)
        else:
            provider_cfg = {}
        provider_cfg["probability_calibration"] = calibration_payload
        expert_out["provider_config"] = provider_cfg
        experts_out[selected_expert_index] = expert_out
        output["experts"] = experts_out
    else:
        output["probability_calibration"] = calibration_payload

    print(json.dumps({"status": "ok", "calibration_summary": calibration_payload["summary"]}, indent=2))

    if args.dry_run:
        return 0

    backup = meta_path.with_suffix(meta_path.suffix + f".bak.{int(time.time())}")
    shutil.copy2(meta_path, backup)
    meta_path.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": "written", "model_meta": str(meta_path), "backup": str(backup)}))
    if generated_live_dataset is not None and generated_live_dataset.exists():
        generated_live_dataset.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
