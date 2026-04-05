#!/usr/bin/env python3
"""Export features, train a baseline model, and register artifacts."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_REGISTRY = BASE_DIR / "models/registry"


def _prediction_contract(label_source: str) -> str:
    if label_source == "tp_sl":
        return "tp_before_sl_within_horizon"
    if label_source == "policy_replay":
        return "action_conditional_pnl_winprob"
    return "directional_return_over_horizon"


def _resolve_horizon_profile(profile: str, custom_horizon: float, custom_up: float, custom_down: float) -> tuple[float, float, float]:
    name = str(profile or "").strip().lower()
    presets: dict[str, tuple[float, float, float]] = {
        "legacy_5m": (300.0, 0.0012, -0.0012),
        "scalp_5m": (300.0, 0.0010, -0.0010),
        "scalp_3m": (180.0, 0.0007, -0.0007),
        "scalp_1m": (60.0, 0.0004, -0.0004),
        "custom": (float(custom_horizon), float(custom_up), float(custom_down)),
    }
    if name not in presets:
        raise SystemExit(f"invalid_horizon_profile:{profile}")
    return presets[name]


def _timestamp() -> str:
    return dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")


def _run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True)


def _safe_float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _score_v2_from_payload(payload: dict) -> float:
    score_payload = (payload.get("promotion_score_v2") or {}) if isinstance(payload, dict) else {}
    score = _safe_float(score_payload.get("score"), float("nan"))
    if score == score:  # not NaN
        return max(0.0, min(100.0, score))
    metrics = payload.get("metrics") or {}
    trade = payload.get("trading_metrics") or {}
    cal = ((payload.get("probability_calibration") or {}).get("metrics_after") or {})
    directional_f1 = _clamp01(_safe_float(metrics.get("directional_f1_macro"), 0.0))
    directional_accuracy = _clamp01(_safe_float(trade.get("directional_accuracy"), 0.0))
    ev_after_costs = _safe_float(trade.get("ev_after_costs_mean"), 0.0)
    ev_component = 0.5 + (0.5 * __import__("math").tanh(ev_after_costs * 5.0))
    ece = _safe_float(cal.get("ece_top1"), 0.15)
    brier = _safe_float(cal.get("multiclass_brier"), 0.16)
    ece_component = _clamp01(1.0 - min(1.0, ece / 0.25))
    brier_component = _clamp01(1.0 - min(1.0, brier / 0.25))
    score_v2 = (
        (directional_f1 * 0.30)
        + (directional_accuracy * 0.25)
        + (ev_component * 0.25)
        + (ece_component * 0.10)
        + (brier_component * 0.10)
    ) * 100.0
    return max(0.0, min(100.0, score_v2))


def _walk_forward_score_v2(payload: dict) -> float:
    walk = payload.get("walk_forward") or {}
    score = _safe_float(walk.get("promotion_score_v2_mean"), float("nan"))
    if score == score:  # not NaN
        return max(0.0, min(100.0, score))
    wf_f1 = _safe_float(walk.get("directional_f1_macro_mean"), 0.0)
    wf_ev = _safe_float(walk.get("ev_after_costs_mean"), 0.0)
    wf_f1_component = _clamp01(wf_f1)
    wf_ev_component = 0.5 + (0.5 * __import__("math").tanh(wf_ev * 5.0))
    score_v2 = ((wf_f1_component * 0.6) + (wf_ev_component * 0.4)) * 100.0
    return max(0.0, min(100.0, score_v2))


def _prediction_distribution(payload: dict) -> tuple[float, float, float]:
    """
    Compute predicted class distribution from confusion matrix columns.
    Returns (down_ratio, flat_ratio, up_ratio).
    """
    labels = [str(x) for x in (payload.get("class_labels") or [])]
    matrix = ((payload.get("metrics") or {}).get("confusion_matrix") or [])
    if not isinstance(matrix, list) or not matrix or not labels:
        return 0.0, 0.0, 0.0
    index = {label: idx for idx, label in enumerate(labels)}
    down_idx = index.get("down")
    flat_idx = index.get("flat")
    up_idx = index.get("up")
    if down_idx is None or flat_idx is None or up_idx is None:
        return 0.0, 0.0, 0.0
    pred_totals = [0.0 for _ in range(len(labels))]
    try:
        for row in matrix:
            if not isinstance(row, list):
                continue
            for i in range(min(len(row), len(pred_totals))):
                pred_totals[i] += _safe_float(row[i], 0.0)
        total = sum(pred_totals)
        if total <= 0:
            return 0.0, 0.0, 0.0
        return (
            float(pred_totals[down_idx] / total),
            float(pred_totals[flat_idx] / total),
            float(pred_totals[up_idx] / total),
        )
    except Exception:
        return 0.0, 0.0, 0.0


def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _guess_active_config_artifact(registry: Path, latest_payload: dict) -> str | None:
    if not latest_payload:
        return None
    latest_metrics = latest_payload.get("metrics") or {}
    latest_samples = latest_payload.get("samples") or {}
    latest_contract = str(latest_payload.get("prediction_contract") or "")
    candidates = sorted(registry.glob("prediction_baseline_*.json"), reverse=True)
    for candidate in candidates:
        payload = _load_json(candidate)
        if not payload:
            continue
        metrics = payload.get("metrics") or {}
        samples = payload.get("samples") or {}
        contract = str(payload.get("prediction_contract") or "")
        if (
            _safe_float(metrics.get("accuracy"), -1.0) == _safe_float(latest_metrics.get("accuracy"), -2.0)
            and int(samples.get("total") or -1) == int(latest_samples.get("total") or -2)
            and contract == latest_contract
        ):
            return candidate.name
    return None


def _load_or_init_pointer(registry: Path, latest_payload: dict) -> dict:
    pointer_path = registry / "latest_pointer.json"
    pointer = _load_json(pointer_path)
    if pointer:
        return pointer
    guessed_config = _guess_active_config_artifact(registry, latest_payload)
    guessed_model = guessed_config.replace(".json", ".onnx") if guessed_config else None
    return {
        "updated_at": _timestamp(),
        "current": {"model": guessed_model, "config": guessed_config},
        "previous": {"model": None, "config": None},
    }


def _candidate_beats_latest(
    latest_payload: dict,
    candidate_payload: dict,
    min_f1_delta: float,
    min_ev_delta: float,
    min_directional_f1: float,
    min_ev_after_costs: float,
    min_walk_forward_directional_f1: float,
    min_walk_forward_ev_after_costs: float,
    min_promotion_score_v2: float,
    min_walk_forward_promotion_score_v2: float,
    min_prediction_ratio_down: float,
    min_prediction_ratio_up: float,
    min_directional_prediction_coverage: float,
    min_flat_label_ratio: float,
    min_f1_down: float,
    min_f1_up: float,
    min_directional_accuracy_long: float,
    min_directional_accuracy_short: float,
    max_ece_top1: float,
    min_total_samples: int,
    min_directional_samples: int,
) -> tuple[bool, str]:
    rollout_gate = candidate_payload.get("rollout_gate") or {}
    short_f1_pass = rollout_gate.get("short_f1_pass")
    if short_f1_pass is False:
        f1_down = _safe_float(rollout_gate.get("f1_down"), -1.0)
        threshold = _safe_float(rollout_gate.get("threshold"), -1.0)
        return False, f"candidate_rollout_gate_short_f1_fail:{f1_down:.6f}<{threshold:.6f}"

    contract = str(candidate_payload.get("prediction_contract") or "")
    if contract == "action_conditional_pnl_winprob":
        cand_metrics = candidate_payload.get("metrics") or {}
        latest_metrics = latest_payload.get("metrics") if isinstance(latest_payload, dict) else {}
        cand_auc = _safe_float(cand_metrics.get("win_auc_macro"), -1.0)
        latest_auc = _safe_float((latest_metrics or {}).get("win_auc_macro"), -1.0)
        if cand_auc < 0:
            return False, "candidate_missing_win_auc_macro"
        min_auc = max(float(min_directional_f1), 0.5)
        if cand_auc < min_auc:
            return False, f"candidate_win_auc_macro_below_min:{cand_auc:.6f}"
        if latest_auc >= 0 and (cand_auc - latest_auc) < float(min_f1_delta):
            return False, f"candidate_win_auc_delta_too_low:{cand_auc - latest_auc:.6f}"
        return True, "action_conditional_candidate_ok"
    if not latest_payload:
        return True, "no_latest_baseline"
    latest_metrics = latest_payload.get("metrics") or {}
    latest_trade = latest_payload.get("trading_metrics") or {}
    cand_metrics = candidate_payload.get("metrics") or {}
    cand_trade = candidate_payload.get("trading_metrics") or {}
    cand_cal = ((candidate_payload.get("probability_calibration") or {}).get("metrics_after") or {})

    latest_f1 = _safe_float(latest_metrics.get("directional_f1_macro"), -1.0)
    cand_f1 = _safe_float(cand_metrics.get("directional_f1_macro"), -1.0)
    latest_ev = _safe_float(latest_trade.get("ev_after_costs_mean"), float("-inf"))
    cand_ev = _safe_float(cand_trade.get("ev_after_costs_mean"), float("-inf"))
    cand_f1_down = _safe_float(cand_metrics.get("f1_down"), -1.0)
    cand_f1_up = _safe_float(cand_metrics.get("f1_up"), -1.0)
    cand_da_long = _safe_float(cand_trade.get("directional_accuracy_long"), -1.0)
    cand_da_short = _safe_float(cand_trade.get("directional_accuracy_short"), -1.0)
    cand_ece_top1 = _safe_float(cand_cal.get("ece_top1"), 1.0)
    cand_total_samples = int(_safe_float((candidate_payload.get("samples") or {}).get("total"), 0))
    cand_directional_samples = int(_safe_float(cand_trade.get("directional_samples"), 0))

    if cand_f1 < 0 or cand_ev == float("-inf"):
        return False, "candidate_missing_required_metrics"
    if cand_total_samples < int(min_total_samples):
        return False, f"candidate_total_samples_below_min:{cand_total_samples}<{int(min_total_samples)}"
    if cand_directional_samples < int(min_directional_samples):
        return False, (
            "candidate_directional_samples_below_min:"
            f"{cand_directional_samples}<{int(min_directional_samples)}"
        )
    if cand_f1_down < float(min_f1_down):
        return False, f"candidate_f1_down_below_min:{cand_f1_down:.6f}"
    if cand_f1_up < float(min_f1_up):
        return False, f"candidate_f1_up_below_min:{cand_f1_up:.6f}"
    if cand_da_long < float(min_directional_accuracy_long):
        return False, f"candidate_directional_accuracy_long_below_min:{cand_da_long:.6f}"
    if cand_da_short < float(min_directional_accuracy_short):
        return False, f"candidate_directional_accuracy_short_below_min:{cand_da_short:.6f}"
    if cand_ece_top1 > float(max_ece_top1):
        return False, f"candidate_ece_top1_above_max:{cand_ece_top1:.6f}>{float(max_ece_top1):.6f}"
    label_balance = candidate_payload.get("label_balance") or {}
    label_ratios = label_balance.get("ratios") or {}
    flat_label_ratio = _safe_float(label_ratios.get("flat"), 0.0)
    if flat_label_ratio < float(min_flat_label_ratio):
        return False, f"candidate_flat_label_ratio_below_min:{flat_label_ratio:.6f}"
    cand_score_v2 = _score_v2_from_payload(candidate_payload)
    if cand_score_v2 < float(min_promotion_score_v2):
        return False, f"candidate_promotion_score_v2_below_min:{cand_score_v2:.6f}"
    if cand_f1 < float(min_directional_f1):
        return False, f"candidate_directional_f1_below_min:{cand_f1:.6f}"
    if cand_ev < float(min_ev_after_costs):
        return False, f"candidate_ev_after_costs_below_min:{cand_ev:.6f}"
    down_ratio, _flat_ratio, up_ratio = _prediction_distribution(candidate_payload)
    directional_prediction_coverage = max(0.0, min(1.0, down_ratio + up_ratio))
    if down_ratio < float(min_prediction_ratio_down):
        return False, f"candidate_down_prediction_ratio_below_min:{down_ratio:.6f}"
    if up_ratio < float(min_prediction_ratio_up):
        return False, f"candidate_up_prediction_ratio_below_min:{up_ratio:.6f}"
    if directional_prediction_coverage < float(min_directional_prediction_coverage):
        return False, (
            "candidate_directional_prediction_coverage_below_min:"
            f"{directional_prediction_coverage:.6f}"
        )
    cand_walk = candidate_payload.get("walk_forward") or {}
    wf_f1 = _safe_float(cand_walk.get("directional_f1_macro_mean"), -1.0)
    wf_ev = _safe_float(cand_walk.get("ev_after_costs_mean"), float("-inf"))
    if wf_f1 >= 0 and wf_f1 < float(min_walk_forward_directional_f1):
        return False, f"candidate_walk_forward_directional_f1_below_min:{wf_f1:.6f}"
    if wf_ev != float("-inf") and wf_ev < float(min_walk_forward_ev_after_costs):
        return False, f"candidate_walk_forward_ev_after_costs_below_min:{wf_ev:.6f}"
    wf_score_v2 = _walk_forward_score_v2(candidate_payload)
    if wf_score_v2 < float(min_walk_forward_promotion_score_v2):
        return False, f"candidate_walk_forward_promotion_score_v2_below_min:{wf_score_v2:.6f}"
    if latest_f1 < 0 or latest_ev == float("-inf"):
        return True, "latest_missing_required_metrics_allow_bootstrap"

    f1_delta = cand_f1 - latest_f1
    ev_delta = cand_ev - latest_ev
    if f1_delta < float(min_f1_delta):
        return False, f"directional_f1_macro_delta_too_low:{f1_delta:.6f}"
    if ev_delta < float(min_ev_delta):
        return False, f"ev_after_costs_delta_too_low:{ev_delta:.6f}"
    return True, f"improved:f1_delta={f1_delta:.6f},ev_delta={ev_delta:.6f}"


def _build_drift_cmd(
    python_bin: str,
    model_config: str,
    stream: str,
    limit: int,
    zscore: float,
    std_ratio_high: float,
    std_ratio_low: float,
) -> list[str]:
    return [
        python_bin,
        "scripts/feature_drift_check.py",
        "--model-config",
        model_config,
        "--stream",
        stream,
        "--limit",
        str(limit),
        "--zscore",
        str(zscore),
        "--std-ratio-high",
        str(std_ratio_high),
        "--std-ratio-low",
        str(std_ratio_low),
    ]


def _coerce_probs(value: Any, class_count: int) -> list[float] | None:
    if hasattr(value, "tolist"):
        value = value.tolist()
    if isinstance(value, list) and len(value) == 1 and isinstance(value[0], (list, dict)):
        value = value[0]
    if isinstance(value, dict):
        if all(isinstance(k, int) for k in value.keys()):
            return [float(value.get(i, 0.0)) for i in range(class_count)]
        return [float(v) for v in list(value.values())[:class_count]]
    if isinstance(value, list) and len(value) == class_count:
        return [float(v) for v in value]
    return None


def _extract_probabilities_from_outputs(outputs: list[Any], output_names: list[str], class_count: int) -> list[list[float]]:
    # Batch zipmap output: list[dict]
    for value in outputs:
        if isinstance(value, list) and value and isinstance(value[0], dict):
            rows: list[list[float]] = []
            for row in value:
                probs = _coerce_probs(row, class_count)
                if probs is None:
                    return []
                rows.append(probs)
            return rows
    # Tensor output: ndarray/list
    for name, value in zip(output_names, outputs):
        if "prob" in name.lower():
            if hasattr(value, "tolist"):
                value = value.tolist()
            if isinstance(value, list) and value and isinstance(value[0], list):
                return [[float(x) for x in row[:class_count]] for row in value]
    for value in outputs:
        if hasattr(value, "tolist"):
            value = value.tolist()
        if isinstance(value, list) and value and isinstance(value[0], list):
            return [[float(x) for x in row[:class_count]] for row in value]
    return []


def _apply_platt_calibration(
    probs: list[list[float]],
    labels: list[str],
    calibration_payload: dict[str, Any],
) -> list[list[float]]:
    if not probs:
        return probs
    per_class = ((calibration_payload or {}).get("per_class") or {}) if isinstance(calibration_payload, dict) else {}
    calibrated: list[list[float]] = []
    for row in probs:
        adj: list[float] = []
        for idx, label in enumerate(labels):
            p = max(1e-6, min(1.0 - 1e-6, float(row[idx]) if idx < len(row) else 0.0))
            cls = per_class.get(label) if isinstance(per_class, dict) else None
            if isinstance(cls, dict) and cls.get("fitted"):
                a = _safe_float(cls.get("a"), 1.0)
                b = _safe_float(cls.get("b"), 0.0)
                logit = __import__("math").log(p / (1.0 - p))
                z = max(-40.0, min(40.0, (a * logit) + b))
                p = 1.0 / (1.0 + __import__("math").exp(-z))
            adj.append(float(p))
        s = sum(adj)
        if s <= 0:
            calibrated.append([1.0 / max(1, len(labels)) for _ in labels])
        else:
            calibrated.append([float(v / s) for v in adj])
    return calibrated


def _evaluate_onnx_on_dataset(
    *,
    model_config_path: Path,
    dataset_path: Path,
    ev_reward_ratio: float,
    ev_cost_bps: float,
) -> dict[str, Any]:
    import onnxruntime as ort  # type: ignore
    import numpy as np  # type: ignore

    payload = _load_json(model_config_path)
    feature_keys = [str(x) for x in (payload.get("feature_keys") or [])]
    labels = [str(x) for x in (payload.get("class_labels") or [])]
    if not feature_keys or not labels:
        return {}
    if set(["down", "flat", "up"]).difference(set(labels)):
        # Skip paired directional check for non-directional contracts.
        return {}
    label_map = {label: idx for idx, label in enumerate(labels)}
    rows_x: list[list[float]] = []
    rows_y: list[int] = []
    with open(dataset_path, "r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            lb = str(row.get("label") or "")
            if lb not in label_map:
                continue
            vec: list[float] = []
            for key in feature_keys:
                raw = row.get(key)
                try:
                    vec.append(float(raw))
                except (TypeError, ValueError):
                    vec.append(0.0)
            rows_x.append(vec)
            rows_y.append(int(label_map[lb]))
    if not rows_x:
        return {}
    x = np.asarray(rows_x, dtype=np.float32)
    y = np.asarray(rows_y, dtype=np.int64)

    onnx_path_raw = str(payload.get("onnx_path") or "").strip()
    if not onnx_path_raw:
        return {}
    onnx_path = Path(onnx_path_raw)
    if not onnx_path.is_absolute():
        onnx_path = (BASE_DIR / onnx_path).resolve()
    if not onnx_path.exists():
        return {}

    session = ort.InferenceSession(str(onnx_path))
    input_name = session.get_inputs()[0].name
    output_names = [out.name for out in session.get_outputs()]
    preferred_outputs = [name for name in output_names if "prob" in name.lower()]
    outputs = session.run(preferred_outputs or None, {input_name: x})
    if preferred_outputs:
        output_names = preferred_outputs
    probs = _extract_probabilities_from_outputs(outputs, output_names, class_count=len(labels))
    if not probs or len(probs) != len(rows_y):
        return {}
    probs = _apply_platt_calibration(
        probs,
        labels=labels,
        calibration_payload=payload.get("probability_calibration") or {},
    )

    probs_np = np.asarray(probs, dtype=np.float64)
    preds = np.argmax(probs_np, axis=1)
    accuracy = float(np.mean((preds == y).astype(np.float64)))
    class_count = len(labels)
    cm = np.zeros((class_count, class_count), dtype=np.int64)
    for yt, yp in zip(y.tolist(), preds.tolist()):
        if 0 <= int(yt) < class_count and 0 <= int(yp) < class_count:
            cm[int(yt), int(yp)] += 1

    up_idx = int(label_map.get("up", max(label_map.values())))
    down_idx = int(label_map.get("down", min(label_map.values())))
    flat_idx = int(label_map.get("flat", -1))
    # Binary f1 for side classes
    def _f1_binary(y_true: np.ndarray, y_pred: np.ndarray) -> float:
        tp = float(np.sum((y_true == 1) & (y_pred == 1)))
        fp = float(np.sum((y_true == 0) & (y_pred == 1)))
        fn = float(np.sum((y_true == 1) & (y_pred == 0)))
        if tp <= 0:
            return 0.0
        precision = tp / max(1e-12, tp + fp)
        recall = tp / max(1e-12, tp + fn)
        return 0.0 if (precision + recall) <= 0 else float(2.0 * precision * recall / (precision + recall))

    f1_up = _f1_binary((y == up_idx).astype(int), (preds == up_idx).astype(int))
    f1_down = _f1_binary((y == down_idx).astype(int), (preds == down_idx).astype(int))
    directional_f1_macro = float((f1_up + f1_down) / 2.0)

    directional_mask = y != flat_idx if flat_idx >= 0 else np.ones_like(y, dtype=bool)
    directional_samples = int(np.sum(directional_mask))
    directional_accuracy = 0.0
    if directional_samples > 0:
        directional_accuracy = float(np.mean((preds[directional_mask] == y[directional_mask]).astype(np.float64)))
    long_mask = y == up_idx
    short_mask = y == down_idx
    directional_accuracy_long = float(np.mean((preds[long_mask] == y[long_mask]).astype(np.float64))) if np.any(long_mask) else 0.0
    directional_accuracy_short = float(np.mean((preds[short_mask] == y[short_mask]).astype(np.float64))) if np.any(short_mask) else 0.0

    row_idx = np.arange(len(y))
    p_true = probs_np[row_idx, y]
    ev_cost = float(ev_cost_bps) / 10000.0
    ev_values = (p_true * float(ev_reward_ratio)) - ((1.0 - p_true) * 1.0) - ev_cost
    ev_after_costs_mean = float(np.mean(ev_values))

    return {
        "metrics": {
            "accuracy": accuracy,
            "confusion_matrix": cm.tolist(),
            "f1_up": f1_up,
            "f1_down": f1_down,
            "directional_f1_macro": directional_f1_macro,
        },
        "trading_metrics": {
            "samples": int(len(y)),
            "directional_samples": directional_samples,
            "directional_accuracy": directional_accuracy,
            "directional_accuracy_long": directional_accuracy_long,
            "directional_accuracy_short": directional_accuracy_short,
            "ev_after_costs_mean": ev_after_costs_mean,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Export data, train baseline, register artifacts.")
    parser.add_argument("--redis-url", default=None, help="Redis URL override.")
    parser.add_argument("--tenant-id", default=None, help="Tenant id for namespaced streams.")
    parser.add_argument("--bot-id", default=None, help="Bot id for namespaced streams.")
    parser.add_argument("--limit", type=int, default=100000, help="Max stream entries to read.")
    parser.add_argument("--hours", type=float, default=None, help="Optional lookback window in hours.")
    parser.add_argument(
        "--horizon-profile",
        default="scalp_5m",
        choices=["legacy_5m", "scalp_5m", "scalp_3m", "scalp_1m", "custom"],
        help="Label horizon preset for scalping alignment.",
    )
    parser.add_argument("--horizon-sec", type=float, default=300.0, help="Label horizon in seconds.")
    parser.add_argument("--up-threshold", type=float, default=0.0012, help="Up label return threshold.")
    parser.add_argument("--down-threshold", type=float, default=-0.0012, help="Down label return threshold.")
    parser.add_argument(
        "--label-source",
        default="future_return",
        choices=["future_return", "tp_sl", "policy_replay"],
        help="Label source for training dataset (future_return, tp_sl, or policy_replay).",
    )
    parser.add_argument("--registry", default=str(DEFAULT_REGISTRY), help="Registry directory.")
    parser.add_argument("--stream", default="events:features", help="Feature stream name.")
    parser.add_argument("--dataset", default="prediction_dataset.csv", help="Dataset CSV path.")
    parser.add_argument("--keep-dataset", action="store_true", help="Keep dataset CSV in registry.")
    parser.add_argument(
        "--min-class-ratio",
        type=float,
        default=0.05,
        help="Minimum fraction required for each class.",
    )
    parser.add_argument(
        "--allow-imbalance",
        action="store_true",
        help="Allow training to proceed even when class balance is below minimum ratio.",
    )
    parser.add_argument(
        "--drift-check",
        action="store_true",
        help="Run feature drift check against the latest model config before training.",
    )
    parser.add_argument(
        "--drift-model-config",
        default=None,
        help="Optional model config path for drift check (defaults to registry/latest.json).",
    )
    parser.add_argument("--drift-zscore", type=float, default=3.0, help="Drift mean z-score threshold.")
    parser.add_argument("--drift-std-ratio-high", type=float, default=3.0, help="Drift std ratio high threshold.")
    parser.add_argument("--drift-std-ratio-low", type=float, default=0.33, help="Drift std ratio low threshold.")
    parser.add_argument(
        "--fail-on-drift",
        action="store_true",
        help="Abort training if drift check reports drift.",
    )
    parser.add_argument(
        "--min-feature-std",
        type=float,
        default=1e-9,
        help="Minimum absolute std per feature (passed to training script).",
    )
    parser.add_argument(
        "--min-relative-std-ratio",
        type=float,
        default=0.001,
        help="Minimum feature std ratio vs median std (passed to training script).",
    )
    parser.add_argument(
        "--fail-on-low-variance",
        action="store_true",
        help="Abort training when low-variance features are detected.",
    )
    parser.add_argument(
        "--allow-poor-feature-quality",
        action="store_true",
        help="Allow training when feature quality checks fail.",
    )
    parser.add_argument(
        "--max-missing-ratio",
        type=float,
        default=0.10,
        help="Maximum allowed raw missing ratio per feature in training dataset.",
    )
    parser.add_argument(
        "--max-invalid-ratio",
        type=float,
        default=0.02,
        help="Maximum allowed raw invalid ratio per feature in training dataset.",
    )
    parser.add_argument(
        "--min-unique-count-critical",
        type=int,
        default=2,
        help="Minimum unique count required for critical features.",
    )
    parser.add_argument(
        "--critical-features",
        default="ema_fast_15m,ema_slow_15m,atr_5m,atr_5m_baseline,spread_bps",
        help="Comma-separated critical feature names.",
    )
    parser.add_argument(
        "--max-dead-feature-ratio",
        type=float,
        default=0.25,
        help="Maximum allowed dead/constant feature ratio in training dataset.",
    )
    parser.add_argument(
        "--dead-feature-std-threshold",
        type=float,
        default=1e-12,
        help="Std threshold below which a feature is considered dead.",
    )
    parser.add_argument(
        "--walk-forward-folds",
        type=int,
        default=3,
        help="Walk-forward fold count for out-of-time validation in training metrics.",
    )
    parser.add_argument(
        "--ev-cost-bps",
        type=float,
        default=12.0,
        help="Cost assumption (bps) used for EV-after-cost metrics.",
    )
    parser.add_argument(
        "--ev-reward-ratio",
        type=float,
        default=1.5,
        help="Reward ratio used for EV-after-cost metrics.",
    )
    parser.add_argument(
        "--allow-regression",
        action="store_true",
        help="Allow promoting model even if directional/EV metrics regress vs latest.",
    )
    parser.add_argument(
        "--disable-paired-promotion-check",
        action="store_true",
        help="Disable paired candidate-vs-latest evaluation on the same exported dataset.",
    )
    parser.add_argument(
        "--min-directional-f1-delta",
        type=float,
        default=0.0,
        help="Minimum required improvement in directional_f1_macro vs latest.",
    )
    parser.add_argument(
        "--min-ev-delta",
        type=float,
        default=0.0,
        help="Minimum required improvement in ev_after_costs_mean vs latest.",
    )
    parser.add_argument(
        "--min-directional-f1",
        type=float,
        default=0.25,
        help="Absolute minimum candidate directional_f1_macro required for promotion.",
    )
    parser.add_argument(
        "--min-ev-after-costs",
        type=float,
        default=0.0,
        help="Absolute minimum candidate ev_after_costs_mean required for promotion.",
    )
    parser.add_argument(
        "--min-walk-forward-directional-f1",
        type=float,
        default=0.20,
        help="Absolute minimum walk-forward directional_f1_macro_mean for promotion.",
    )
    parser.add_argument(
        "--min-walk-forward-ev-after-costs",
        type=float,
        default=0.0,
        help="Absolute minimum walk-forward ev_after_costs_mean for promotion.",
    )
    parser.add_argument(
        "--min-promotion-score-v2",
        type=float,
        default=0.0,
        help="Absolute minimum candidate promotion score v2 (0-100).",
    )
    parser.add_argument(
        "--min-walk-forward-promotion-score-v2",
        type=float,
        default=0.0,
        help="Absolute minimum walk-forward promotion score v2 (0-100).",
    )
    parser.add_argument(
        "--min-prediction-ratio-down",
        type=float,
        default=0.03,
        help="Minimum predicted down class ratio required for promotion.",
    )
    parser.add_argument(
        "--min-prediction-ratio-up",
        type=float,
        default=0.03,
        help="Minimum predicted up class ratio required for promotion.",
    )
    parser.add_argument(
        "--min-directional-prediction-coverage",
        type=float,
        default=0.15,
        help="Minimum combined predicted (down+up) coverage required for promotion.",
    )
    parser.add_argument(
        "--min-flat-label-ratio",
        type=float,
        default=0.02,
        help="Minimum flat class ratio required in label_balance for promotion.",
    )
    parser.add_argument(
        "--min-f1-down",
        type=float,
        default=0.35,
        help="Minimum candidate f1_down required for promotion.",
    )
    parser.add_argument(
        "--min-f1-up",
        type=float,
        default=0.70,
        help="Minimum candidate f1_up required for promotion.",
    )
    parser.add_argument(
        "--min-directional-accuracy-long",
        type=float,
        default=0.50,
        help="Minimum candidate directional_accuracy_long required for promotion.",
    )
    parser.add_argument(
        "--min-directional-accuracy-short",
        type=float,
        default=0.50,
        help="Minimum candidate directional_accuracy_short required for promotion.",
    )
    parser.add_argument(
        "--max-ece-top1",
        type=float,
        default=0.22,
        help="Maximum allowed calibration ece_top1 for promotion.",
    )
    parser.add_argument(
        "--min-total-samples",
        type=int,
        default=400,
        help="Minimum candidate total samples required for promotion.",
    )
    parser.add_argument(
        "--min-directional-samples",
        type=int,
        default=120,
        help="Minimum candidate directional samples required for promotion.",
    )
    args = parser.parse_args()

    resolved_horizon, resolved_up, resolved_down = _resolve_horizon_profile(
        args.horizon_profile,
        args.horizon_sec,
        args.up_threshold,
        args.down_threshold,
    )

    registry = Path(args.registry)
    registry.mkdir(parents=True, exist_ok=True)
    ts = _timestamp()

    dataset_path = Path(args.dataset)
    model_path = registry / f"prediction_baseline_{ts}.onnx"
    config_path = registry / f"prediction_baseline_{ts}.json"
    latest_json = registry / "latest.json"
    latest_payload = _load_json(latest_json)
    pointer = _load_or_init_pointer(registry, latest_payload)

    if args.drift_check:
        drift_config = args.drift_model_config or str(latest_json)
        drift_cmd = _build_drift_cmd(
            sys.executable,
            drift_config,
            args.stream,
            args.limit,
            args.drift_zscore,
            args.drift_std_ratio_high,
            args.drift_std_ratio_low,
        )
        try:
            result = subprocess.run(drift_cmd, check=False, capture_output=True, text=True)
        except Exception as exc:
            raise SystemExit(f"drift_check_failed:{exc}") from exc
        if result.returncode != 0:
            raise SystemExit(result.stderr.strip() or "drift_check_failed")
        if "drift:" in result.stdout and "drift:none" not in result.stdout:
            if args.fail_on_drift:
                raise SystemExit(f"drift_detected:{result.stdout.strip()}")
            print(f"warn:drift_detected:{result.stdout.strip()}")

    replay_meta_path = registry / f"policy_replay_meta_{ts}.json"
    export_cmd = [
        sys.executable,
        str(BASE_DIR / "scripts" / "export_prediction_dataset.py"),
        "--output",
        str(dataset_path),
        "--limit",
        str(args.limit),
        "--horizon-sec",
        str(resolved_horizon),
        "--up-threshold",
        str(resolved_up),
        "--down-threshold",
        str(resolved_down),
        "--label-source",
        str(args.label_source),
        "--stream",
        args.stream,
    ]
    if args.hours is not None:
        export_cmd.extend(["--hours", str(args.hours)])
    if args.label_source == "policy_replay":
        export_cmd.extend(
            [
                "--metadata-output",
                str(replay_meta_path),
            ]
        )
    if args.redis_url:
        export_cmd.extend(["--redis-url", args.redis_url])
    if args.tenant_id and args.bot_id:
        export_cmd.extend(["--tenant-id", str(args.tenant_id), "--bot-id", str(args.bot_id)])

    _run(export_cmd)

    train_cmd = [
        sys.executable,
        str(BASE_DIR / "scripts" / "train_prediction_baseline.py"),
        "--input",
        str(dataset_path),
        "--output",
        str(model_path),
        "--config",
        str(config_path),
        "--min-class-ratio",
        str(args.min_class_ratio),
        "--prediction-contract",
        _prediction_contract(args.label_source),
        "--min-feature-std",
        str(args.min_feature_std),
        "--min-relative-std-ratio",
        str(args.min_relative_std_ratio),
        "--max-missing-ratio",
        str(args.max_missing_ratio),
        "--max-invalid-ratio",
        str(args.max_invalid_ratio),
        "--min-unique-count-critical",
        str(args.min_unique_count_critical),
        "--critical-features",
        str(args.critical_features),
        "--max-dead-feature-ratio",
        str(args.max_dead_feature_ratio),
        "--dead-feature-std-threshold",
        str(args.dead_feature_std_threshold),
        "--walk-forward-folds",
        str(args.walk_forward_folds),
        "--ev-cost-bps",
        str(args.ev_cost_bps),
        "--ev-reward-ratio",
        str(args.ev_reward_ratio),
    ]
    if args.label_source == "policy_replay":
        train_cmd.extend(["--dataset-metadata", str(replay_meta_path)])
    if not args.allow_imbalance:
        train_cmd.append("--fail-on-imbalance")
    if args.fail_on_low_variance:
        train_cmd.append("--fail-on-low-variance")
    if not args.allow_poor_feature_quality:
        train_cmd.append("--fail-on-feature-quality")
        train_cmd.append("--fail-on-dead-features")
    _run(train_cmd)

    candidate_payload = _load_json(config_path)
    latest_payload_for_cmp = latest_payload
    candidate_payload_for_cmp = candidate_payload
    if (not args.disable_paired_promotion_check) and latest_payload:
        try:
            latest_pair = _evaluate_onnx_on_dataset(
                model_config_path=latest_json,
                dataset_path=dataset_path,
                ev_reward_ratio=float(args.ev_reward_ratio),
                ev_cost_bps=float(args.ev_cost_bps),
            )
            candidate_pair = _evaluate_onnx_on_dataset(
                model_config_path=config_path,
                dataset_path=dataset_path,
                ev_reward_ratio=float(args.ev_reward_ratio),
                ev_cost_bps=float(args.ev_cost_bps),
            )
            if latest_pair and candidate_pair:
                latest_payload_for_cmp = dict(latest_payload)
                latest_payload_for_cmp["metrics"] = dict(latest_pair.get("metrics") or {})
                latest_payload_for_cmp["trading_metrics"] = dict(latest_pair.get("trading_metrics") or {})
                candidate_payload_for_cmp = dict(candidate_payload)
                candidate_payload_for_cmp["metrics"] = dict(candidate_pair.get("metrics") or {})
                candidate_payload_for_cmp["trading_metrics"] = dict(candidate_pair.get("trading_metrics") or {})
                print(
                    "paired_check:"
                    f"candidate_f1={_safe_float((candidate_pair.get('metrics') or {}).get('directional_f1_macro'), 0.0):.6f},"
                    f"latest_f1={_safe_float((latest_pair.get('metrics') or {}).get('directional_f1_macro'), 0.0):.6f},"
                    f"candidate_ev={_safe_float((candidate_pair.get('trading_metrics') or {}).get('ev_after_costs_mean'), 0.0):.6f},"
                    f"latest_ev={_safe_float((latest_pair.get('trading_metrics') or {}).get('ev_after_costs_mean'), 0.0):.6f}"
                )
            else:
                print("warn:paired_check_skipped:insufficient_directional_contract_or_data")
        except Exception as exc:
            print(f"warn:paired_check_failed:{exc}")

    if not args.allow_regression:
        ok_to_promote, reason = _candidate_beats_latest(
            latest_payload_for_cmp,
            candidate_payload_for_cmp,
            min_f1_delta=args.min_directional_f1_delta,
            min_ev_delta=args.min_ev_delta,
            min_directional_f1=args.min_directional_f1,
            min_ev_after_costs=args.min_ev_after_costs,
            min_walk_forward_directional_f1=args.min_walk_forward_directional_f1,
            min_walk_forward_ev_after_costs=args.min_walk_forward_ev_after_costs,
            min_promotion_score_v2=args.min_promotion_score_v2,
            min_walk_forward_promotion_score_v2=args.min_walk_forward_promotion_score_v2,
            min_prediction_ratio_down=args.min_prediction_ratio_down,
            min_prediction_ratio_up=args.min_prediction_ratio_up,
            min_directional_prediction_coverage=args.min_directional_prediction_coverage,
            min_flat_label_ratio=args.min_flat_label_ratio,
            min_f1_down=args.min_f1_down,
            min_f1_up=args.min_f1_up,
            min_directional_accuracy_long=args.min_directional_accuracy_long,
            min_directional_accuracy_short=args.min_directional_accuracy_short,
            max_ece_top1=args.max_ece_top1,
            min_total_samples=args.min_total_samples,
            min_directional_samples=args.min_directional_samples,
        )
        if not ok_to_promote:
            raise SystemExit(f"promotion_blocked:{reason}")
        print(f"promotion_check:{reason}")

    latest_onnx = registry / "latest.onnx"
    shutil.copy2(model_path, latest_onnx)
    # Rewrite the copied config so runtime can resolve the model path from its cwd
    # (quantgambit-python). The training output path is intentionally not used as a
    # runtime reference.
    with open(config_path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    payload["onnx_path"] = "models/registry/latest.onnx"
    payload["promotion"] = {
        "promoted_at": ts,
        "source_model_file": model_path.name,
        "source_config_file": config_path.name,
        "previous_model_file": ((pointer.get("current") or {}).get("model")),
        "previous_config_file": ((pointer.get("current") or {}).get("config")),
        "gates": {
            "min_directional_f1": float(args.min_directional_f1),
            "min_ev_after_costs": float(args.min_ev_after_costs),
            "min_walk_forward_directional_f1": float(args.min_walk_forward_directional_f1),
            "min_walk_forward_ev_after_costs": float(args.min_walk_forward_ev_after_costs),
            "min_promotion_score_v2": float(args.min_promotion_score_v2),
            "min_walk_forward_promotion_score_v2": float(args.min_walk_forward_promotion_score_v2),
            "min_directional_f1_delta": float(args.min_directional_f1_delta),
            "min_ev_delta": float(args.min_ev_delta),
            "min_prediction_ratio_down": float(args.min_prediction_ratio_down),
            "min_prediction_ratio_up": float(args.min_prediction_ratio_up),
            "min_directional_prediction_coverage": float(args.min_directional_prediction_coverage),
            "min_flat_label_ratio": float(args.min_flat_label_ratio),
            "min_f1_down": float(args.min_f1_down),
            "min_f1_up": float(args.min_f1_up),
            "min_directional_accuracy_long": float(args.min_directional_accuracy_long),
            "min_directional_accuracy_short": float(args.min_directional_accuracy_short),
            "max_ece_top1": float(args.max_ece_top1),
            "min_total_samples": int(args.min_total_samples),
            "min_directional_samples": int(args.min_directional_samples),
            "horizon_profile": str(args.horizon_profile),
            "horizon_sec": float(resolved_horizon),
            "up_threshold": float(resolved_up),
            "down_threshold": float(resolved_down),
        },
    }
    with open(latest_json, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
    pointer_path = registry / "latest_pointer.json"
    updated_pointer = {
        "updated_at": ts,
        "current": {"model": model_path.name, "config": config_path.name},
        "previous": {
            "model": ((pointer.get("current") or {}).get("model")),
            "config": ((pointer.get("current") or {}).get("config")),
        },
    }
    pointer_path.write_text(json.dumps(updated_pointer, indent=2, sort_keys=True), encoding="utf-8")

    if args.keep_dataset:
        dataset_dest = registry / f"prediction_dataset_{ts}.csv"
        shutil.copy2(dataset_path, dataset_dest)

    print(f"registered:{model_path}")
    print(f"registered:{config_path}")
    print(f"latest:{latest_onnx}")
    print(f"latest:{latest_json}")
    print(f"env:PREDICTION_MODEL_CONFIG={latest_json}")


if __name__ == "__main__":
    main()
