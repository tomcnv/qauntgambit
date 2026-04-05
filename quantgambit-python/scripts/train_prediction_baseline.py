#!/usr/bin/env python3
"""Train a baseline classifier and export to ONNX."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import random
import sys
import warnings
from typing import List, Tuple, Dict

import lightgbm as lgb
import numpy as np
import onnxmltools
from lightgbm import LGBMClassifier
from onnxmltools import convert_lightgbm
from onnxmltools.convert.common.data_types import FloatTensorType
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, confusion_matrix, f1_score, roc_auc_score
from sklearn.multioutput import MultiOutputClassifier
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler


DEFAULT_LABELS = ["down", "flat", "up"]
DEFAULT_META_COLUMNS = {
    "symbol",
    "timestamp",
    "label",
    "return",
    "pnl_long_net",
    "pnl_short_net",
    "y_long",
    "y_short",
    "exit_reason_long",
    "exit_reason_short",
    "forced_exit_long",
    "forced_exit_short",
    "forced_risk_exit_long",
    "forced_risk_exit_short",
    "forced_time_exit_long",
    "forced_time_exit_short",
    "strategy_exit_long",
    "strategy_exit_short",
    "cost_fee_entry_long",
    "cost_fee_exit_long",
    "cost_fee_entry_short",
    "cost_fee_exit_short",
    "entry_price_long",
    "entry_price_short",
    "exit_price_long",
    "exit_price_short",
    "hold_sec_long",
    "hold_sec_short",
}


def _load_rows(path: str) -> List[dict]:
    with open(path, "r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        return list(reader)


def _infer_features(rows: List[dict]) -> List[str]:
    if not rows:
        return []
    return [key for key in rows[0].keys() if key not in DEFAULT_META_COLUMNS]


def _build_arrays(
    rows: List[dict],
    feature_keys: List[str],
    labels: List[str],
) -> Tuple[np.ndarray, np.ndarray, Dict[str, int]]:
    label_map = {label: idx for idx, label in enumerate(labels)}
    label_counts = {label: 0 for label in labels}
    features = []
    targets = []
    for row in rows:
        label = row.get("label")
        if label not in label_map:
            continue
        label_counts[label] += 1
        vec = []
        for key in feature_keys:
            raw = row.get(key)
            try:
                vec.append(float(raw))
            except (TypeError, ValueError):
                vec.append(0.0)
        features.append(vec)
        targets.append(label_map[label])
    if not features:
        return (
            np.empty((0, len(feature_keys)), dtype=np.float32),
            np.empty((0,), dtype=np.int64),
            label_counts,
        )
    return np.asarray(features, dtype=np.float32), np.asarray(targets, dtype=np.int64), label_counts


def _build_action_conditional_arrays(
    rows: List[dict],
    feature_keys: List[str],
) -> Tuple[np.ndarray, np.ndarray]:
    features = []
    targets = []
    for row in rows:
        try:
            y_long = int(float(row.get("y_long", "")))
            y_short = int(float(row.get("y_short", "")))
        except (TypeError, ValueError):
            continue
        if y_long not in {0, 1} or y_short not in {0, 1}:
            continue
        vec = []
        for key in feature_keys:
            raw = row.get(key)
            try:
                vec.append(float(raw))
            except (TypeError, ValueError):
                vec.append(0.0)
        features.append(vec)
        targets.append([y_long, y_short])
    if not features:
        return (
            np.empty((0, len(feature_keys)), dtype=np.float32),
            np.empty((0, 2), dtype=np.int64),
        )
    return np.asarray(features, dtype=np.float32), np.asarray(targets, dtype=np.int64)


def _train_test_split(
    x: np.ndarray,
    y: np.ndarray,
    train_ratio: float,
    seed: int,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    indices = list(range(len(x)))
    random.Random(seed).shuffle(indices)
    split = int(len(indices) * train_ratio)
    train_idx = indices[:split]
    test_idx = indices[split:]
    return x[train_idx], x[test_idx], y[train_idx], y[test_idx]


def _time_split(
    rows: List[dict],
    x: np.ndarray,
    y: np.ndarray,
    train_ratio: float,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """
    Time-ordered split to reduce optimistic metrics from temporal autocorrelation.
    Assumes x/y are aligned with `rows` after filtering to supported labels.
    """
    if len(x) == 0:
        return x, x, y, y
    timestamps = []
    for row in rows:
        try:
            timestamps.append(float(row.get("timestamp") or 0.0))
        except (TypeError, ValueError):
            timestamps.append(0.0)
    order = sorted(range(len(timestamps)), key=lambda i: timestamps[i])
    split = int(len(order) * train_ratio)
    train_idx = order[:split]
    test_idx = order[split:]
    return x[train_idx], x[test_idx], y[train_idx], y[test_idx]


def _split_train_calibration(
    x_train: np.ndarray,
    y_train: np.ndarray,
    calibration_ratio: float,
    split_mode: str,
    seed: int,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """
    Split training rows into model-fit and calibration-fit subsets.

    - time mode: keep chronology and use the newest train rows for calibration fit.
    - random mode: deterministic random split within the training subset.
    """
    n = len(x_train)
    if n <= 1:
        return x_train, x_train[:0], y_train, y_train[:0]
    ratio = max(0.0, min(0.95, float(calibration_ratio)))
    cal_count = int(n * ratio)
    # Need enough rows in both subsets for model training and calibration fitting.
    cal_count = max(0, min(n - 1, cal_count))
    if cal_count <= 0:
        return x_train, x_train[:0], y_train, y_train[:0]
    if split_mode == "random":
        indices = list(range(n))
        random.Random(seed).shuffle(indices)
        cal_idx = indices[:cal_count]
        fit_idx = indices[cal_count:]
        return x_train[fit_idx], x_train[cal_idx], y_train[fit_idx], y_train[cal_idx]
    split = n - cal_count
    return x_train[:split], x_train[split:], y_train[:split], y_train[split:]

def _train_model(
    x_train: np.ndarray,
    y_train: np.ndarray,
    *,
    class_weight: str | None = None,
    n_estimators: int = 300,
    max_depth: int = 6,
    learning_rate: float = 0.05,
    num_leaves: int = 31,
    min_child_samples: int = 20,
    seed: int = 7,
) -> LGBMClassifier:
    model = LGBMClassifier(
        n_estimators=n_estimators,
        max_depth=max_depth,
        learning_rate=learning_rate,
        num_leaves=num_leaves,
        min_child_samples=min_child_samples,
        class_weight=class_weight,
        random_state=seed,
        verbose=-1,
    )
    model.fit(x_train, y_train)
    return model


def _train_action_model(x_train: np.ndarray, y_train: np.ndarray, *, class_weight: str | None = None) -> Pipeline:
    model = Pipeline(
        steps=[
            ("scaler", StandardScaler()),
            (
                "clf",
                MultiOutputClassifier(
                    LogisticRegression(
                        max_iter=1000,
                        class_weight=class_weight,
                    )
                ),
            ),
        ]
    )
    model.fit(x_train, y_train)
    return model


def _evaluate(model: Pipeline | LGBMClassifier, x_test: np.ndarray, y_test: np.ndarray, labels: List[str]) -> dict:
    if len(x_test) == 0:
        return {
            "accuracy": 0.0,
            "confusion_matrix": [],
            "f1_up": 0.0,
            "f1_down": 0.0,
            "directional_f1_macro": 0.0,
        }
    preds = _model_predict(model, x_test)
    label_map = {label: idx for idx, label in enumerate(labels)}
    up_idx = int(label_map.get("up", max(label_map.values()) if label_map else 0))
    down_idx = int(label_map.get("down", min(label_map.values()) if label_map else 0))
    f1_up = float(
        f1_score(
            (y_test == up_idx).astype(np.int32),
            (preds == up_idx).astype(np.int32),
            zero_division=0,
        )
    )
    f1_down = float(
        f1_score(
            (y_test == down_idx).astype(np.int32),
            (preds == down_idx).astype(np.int32),
            zero_division=0,
        )
    )
    return {
        "accuracy": float(accuracy_score(y_test, preds)),
        "confusion_matrix": confusion_matrix(y_test, preds).tolist(),
        "f1_up": f1_up,
        "f1_down": f1_down,
        "directional_f1_macro": float((f1_up + f1_down) / 2.0),
    }


def _evaluate_action_model(model: Pipeline, x_test: np.ndarray, y_test: np.ndarray) -> tuple[dict, dict]:
    if len(x_test) == 0:
        metrics = {
            "accuracy_long": 0.0,
            "accuracy_short": 0.0,
            "accuracy_joint": 0.0,
            "win_auc_long": 0.0,
            "win_auc_short": 0.0,
            "win_auc_macro": 0.0,
        }
        trading = {
            "samples": 0,
            "long_win_rate": 0.0,
            "short_win_rate": 0.0,
            "action_win_rate_mean": 0.0,
        }
        return metrics, trading
    preds = np.asarray(_model_predict(model, x_test), dtype=np.int64)
    probs_list = _model_predict_proba(model, x_test)
    prob_long = np.asarray(probs_list[0], dtype=np.float64)[:, 1] if probs_list else np.zeros((len(x_test),))
    prob_short = np.asarray(probs_list[1], dtype=np.float64)[:, 1] if len(probs_list) > 1 else np.zeros((len(x_test),))
    y_long = np.asarray(y_test[:, 0], dtype=np.int64)
    y_short = np.asarray(y_test[:, 1], dtype=np.int64)
    pred_long = preds[:, 0]
    pred_short = preds[:, 1]
    try:
        auc_long = float(roc_auc_score(y_long, prob_long))
    except ValueError:
        auc_long = 0.0
    try:
        auc_short = float(roc_auc_score(y_short, prob_short))
    except ValueError:
        auc_short = 0.0
    metrics = {
        "accuracy_long": float(accuracy_score(y_long, pred_long)),
        "accuracy_short": float(accuracy_score(y_short, pred_short)),
        "accuracy_joint": float(np.mean(((pred_long == y_long) & (pred_short == y_short)).astype(np.float64))),
        "win_auc_long": auc_long,
        "win_auc_short": auc_short,
        "win_auc_macro": float((auc_long + auc_short) / 2.0),
    }
    trading = {
        "samples": int(len(x_test)),
        "long_win_rate": float(np.mean(y_long.astype(np.float64))),
        "short_win_rate": float(np.mean(y_short.astype(np.float64))),
        "action_win_rate_mean": float((np.mean(y_long.astype(np.float64)) + np.mean(y_short.astype(np.float64))) / 2.0),
    }
    return metrics, trading


def _trading_objective_metrics(
    model: Pipeline | LGBMClassifier,
    x_test: np.ndarray,
    y_test: np.ndarray,
    labels: List[str],
    ev_reward_ratio: float,
    ev_cost_bps: float,
) -> dict:
    if len(x_test) == 0:
        return {
            "samples": 0,
            "directional_samples": 0,
            "directional_accuracy": 0.0,
            "ev_after_costs_mean": 0.0,
        }
    raw_probs = np.asarray(_model_predict_proba(model, x_test), dtype=np.float64)
    preds = _model_predict(model, x_test)
    # Some short windows can train with a missing class (e.g. only 2 classes present).
    # Align probabilities to full label space by classifier class index.
    probs = raw_probs
    classes = getattr(model, "classes_", None)
    if classes is None and isinstance(model, Pipeline):
        final_est = model.steps[-1][1] if model.steps else None
        classes = getattr(final_est, "classes_", None)
    if classes is not None:
        classes_arr = np.asarray(classes, dtype=np.int64)
        if raw_probs.ndim == 2 and raw_probs.shape[1] == len(classes_arr):
            aligned = np.zeros((raw_probs.shape[0], len(labels)), dtype=np.float64)
            for src_idx, class_idx in enumerate(classes_arr):
                if 0 <= int(class_idx) < len(labels):
                    aligned[:, int(class_idx)] = raw_probs[:, src_idx]
            probs = aligned

    ev_cost = float(ev_cost_bps) / 10000.0
    y_true = np.asarray(y_test, dtype=np.int64)
    row_idx = np.arange(len(y_true))
    valid = (y_true >= 0) & (y_true < probs.shape[1])
    y_safe = np.clip(y_true, 0, max(0, probs.shape[1] - 1))
    p_true = np.where(valid, probs[row_idx, y_safe], 0.0)
    ev_values = (p_true * float(ev_reward_ratio)) - ((1.0 - p_true) * 1.0) - ev_cost

    label_map = {label: idx for idx, label in enumerate(labels)}
    flat_idx = label_map.get("flat", -1)
    directional_mask = y_true != flat_idx if flat_idx >= 0 else np.ones_like(y_true, dtype=bool)
    directional_samples = int(np.sum(directional_mask))
    directional_accuracy = 0.0
    if directional_samples > 0:
        directional_accuracy = float(
            np.mean((preds[directional_mask] == y_true[directional_mask]).astype(np.float64))
        )
    up_idx = int(label_map.get("up", max(label_map.values()) if label_map else 0))
    down_idx = int(label_map.get("down", min(label_map.values()) if label_map else 0))
    long_mask = y_true == up_idx
    short_mask = y_true == down_idx
    directional_accuracy_long = float(
        np.mean((preds[long_mask] == y_true[long_mask]).astype(np.float64))
    ) if np.any(long_mask) else 0.0
    directional_accuracy_short = float(
        np.mean((preds[short_mask] == y_true[short_mask]).astype(np.float64))
    ) if np.any(short_mask) else 0.0
    return {
        "samples": int(len(y_true)),
        "directional_samples": directional_samples,
        "directional_accuracy": directional_accuracy,
        "directional_accuracy_long": directional_accuracy_long,
        "directional_accuracy_short": directional_accuracy_short,
        "ev_after_costs_mean": float(np.mean(ev_values)),
    }


def _safe_ece(confidence: np.ndarray, correct: np.ndarray, bins: int) -> float:
    if confidence.size == 0:
        return 0.0
    bins = max(2, int(bins))
    ece = 0.0
    n = float(confidence.size)
    for idx in range(bins):
        lo = idx / bins
        hi = (idx + 1) / bins
        if idx == bins - 1:
            mask = (confidence >= lo) & (confidence <= hi)
        else:
            mask = (confidence >= lo) & (confidence < hi)
        if not np.any(mask):
            continue
        conf_bin = float(np.mean(confidence[mask]))
        acc_bin = float(np.mean(correct[mask]))
        ece += abs(acc_bin - conf_bin) * (float(np.sum(mask)) / n)
    return float(ece)


def _multiclass_calibration_metrics(
    probs: np.ndarray,
    y_true: np.ndarray,
    labels: List[str],
    bins: int = 10,
) -> dict:
    if probs.size == 0 or y_true.size == 0:
        return {
            "samples": 0,
            "multiclass_brier": 0.0,
            "ece_top1": 0.0,
            "by_class": {},
        }
    probs = np.asarray(probs, dtype=np.float64)
    y_true = np.asarray(y_true, dtype=np.int64)
    n = probs.shape[0]
    k = probs.shape[1]
    target = np.zeros((n, k), dtype=np.float64)
    target[np.arange(n), y_true] = 1.0
    brier = float(np.mean(np.sum((probs - target) ** 2, axis=1) / float(k)))
    top_conf = np.max(probs, axis=1)
    top_pred = np.argmax(probs, axis=1)
    top_correct = (top_pred == y_true).astype(np.float64)
    ece_top1 = _safe_ece(top_conf, top_correct, bins=bins)

    by_class = {}
    for idx, label in enumerate(labels):
        p = probs[:, idx]
        y_bin = (y_true == idx).astype(np.float64)
        class_brier = float(np.mean((p - y_bin) ** 2))
        class_ece = _safe_ece(p, y_bin, bins=bins)
        by_class[label] = {
            "brier": class_brier,
            "ece": class_ece,
            "base_rate": float(np.mean(y_bin)),
        }

    return {
        "samples": int(n),
        "multiclass_brier": brier,
        "ece_top1": float(ece_top1),
        "by_class": by_class,
    }


def _clamp01(value: float) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, v))


def _compute_promotion_score_v2(
    metrics: dict,
    trading_metrics: dict,
    probability_calibration: dict,
) -> dict:
    exact_accuracy = _clamp01(metrics.get("accuracy", 0.0))
    directional_accuracy = _clamp01(trading_metrics.get("directional_accuracy", 0.0))
    ev_after_costs = float(trading_metrics.get("ev_after_costs_mean", 0.0) or 0.0)
    # Smoothly map EV to [0, 1] with neutral center at 0.
    ev_component = 0.5 + (0.5 * np.tanh(ev_after_costs * 5.0))
    cal_metrics = (
        (probability_calibration.get("metrics_after") if isinstance(probability_calibration, dict) else None)
        or {}
    )
    ece = float(cal_metrics.get("ece_top1", 0.15) or 0.15)
    brier = float(cal_metrics.get("multiclass_brier", 0.16) or 0.16)
    # Lower is better for ECE/Brier.
    ece_component = _clamp01(1.0 - min(1.0, ece / 0.25))
    brier_component = _clamp01(1.0 - min(1.0, brier / 0.25))
    score = (
        (exact_accuracy * 0.30)
        + (directional_accuracy * 0.25)
        + (float(ev_component) * 0.25)
        + (ece_component * 0.10)
        + (brier_component * 0.10)
    ) * 100.0
    return {
        "score": float(max(0.0, min(100.0, score))),
        "components": {
            "exact_accuracy": exact_accuracy,
            "directional_accuracy": directional_accuracy,
            "ev_component": float(ev_component),
            "ece_component": ece_component,
            "brier_component": brier_component,
        },
        "inputs": {
            "exact_accuracy": exact_accuracy,
            "ev_after_costs_mean": ev_after_costs,
            "ece_top1": ece,
            "multiclass_brier": brier,
        },
    }


def _fit_probability_calibration(
    model: Pipeline | LGBMClassifier,
    x_fit: np.ndarray,
    y_fit: np.ndarray,
    x_eval: np.ndarray,
    y_eval: np.ndarray,
    labels: List[str],
    bins: int = 10,
) -> dict:
    if len(x_fit) == 0 or len(x_eval) == 0:
        return {
            "enabled": False,
            "method": "identity",
            "samples": int(len(x_fit) + len(x_eval)),
            "fit_samples": int(len(x_fit)),
            "eval_samples": int(len(x_eval)),
            "per_class": {label: {"a": 1.0, "b": 0.0, "fitted": False} for label in labels},
            "metrics_before": {},
            "metrics_after": {},
        }
    fit_probs = np.asarray(_model_predict_proba(model, x_fit), dtype=np.float64)
    eval_probs = np.asarray(_model_predict_proba(model, x_eval), dtype=np.float64)
    calibrated_eval = np.array(eval_probs, copy=True)
    per_class: dict[str, dict] = {}

    for idx, label in enumerate(labels):
        y_bin = (y_fit == idx).astype(np.int64)
        positives = int(np.sum(y_bin))
        samples = int(len(y_bin))
        if samples == 0 or positives == 0 or positives == samples:
            per_class[label] = {
                "a": 1.0,
                "b": 0.0,
                "samples": samples,
                "positives": positives,
                "fitted": False,
                "reason": "insufficient_binary_support",
            }
            continue
        p = np.clip(fit_probs[:, idx], 1e-6, 1.0 - 1e-6)
        logit = np.log(p / (1.0 - p)).reshape(-1, 1)
        clf = LogisticRegression(max_iter=1000)
        clf.fit(logit, y_bin)
        a = float(clf.coef_[0][0])
        b = float(clf.intercept_[0])
        eval_logit = np.log(
            np.clip(eval_probs[:, idx], 1e-6, 1.0 - 1e-6)
            / (1.0 - np.clip(eval_probs[:, idx], 1e-6, 1.0 - 1e-6))
        )
        z = np.clip((a * eval_logit) + b, -40.0, 40.0)
        calibrated_eval[:, idx] = 1.0 / (1.0 + np.exp(-z))
        per_class[label] = {
            "a": a,
            "b": b,
            "samples": samples,
            "positives": positives,
            "fitted": True,
        }

    row_sum = np.sum(calibrated_eval, axis=1, keepdims=True)
    row_sum[row_sum <= 0] = 1.0
    calibrated_eval = calibrated_eval / row_sum

    metrics_before = _multiclass_calibration_metrics(eval_probs, y_eval, labels, bins=bins)
    metrics_after = _multiclass_calibration_metrics(calibrated_eval, y_eval, labels, bins=bins)
    return {
        "enabled": True,
        "method": "logit_affine_ovr",
        "samples": int(len(x_fit) + len(x_eval)),
        "fit_samples": int(len(x_fit)),
        "eval_samples": int(len(x_eval)),
        "per_class": per_class,
        "metrics_before": metrics_before,
        "metrics_after": metrics_after,
    }


def _feature_stats(x: np.ndarray, feature_keys: List[str]) -> dict:
    if x.size == 0 or not feature_keys:
        return {"count": 0, "features": {}}
    stats = {}
    for idx, key in enumerate(feature_keys):
        column = x[:, idx]
        stats[key] = {
            "mean": float(np.mean(column)),
            "std": float(np.std(column)),
            "min": float(np.min(column)),
            "max": float(np.max(column)),
        }
    return {"count": int(len(x)), "features": stats}


def _raw_feature_quality(rows: List[dict], feature_keys: List[str]) -> dict:
    if not rows or not feature_keys:
        return {"samples": 0, "features": {}}
    summary: dict[str, dict] = {}
    sample_count = int(len(rows))
    for key in feature_keys:
        missing = 0
        invalid = 0
        zero = 0
        numeric_vals: list[float] = []
        for row in rows:
            raw = row.get(key)
            if raw is None or raw == "":
                missing += 1
                continue
            try:
                val = float(raw)
            except (TypeError, ValueError):
                invalid += 1
                continue
            if not np.isfinite(val):
                invalid += 1
                continue
            if val == 0.0:
                zero += 1
            numeric_vals.append(float(val))
        unique = len(set(numeric_vals)) if numeric_vals else 0
        summary[key] = {
            "missing_ratio": float(missing / sample_count),
            "invalid_ratio": float(invalid / sample_count),
            "zero_ratio": float(zero / sample_count),
            "unique_count": int(unique),
            "valid_samples": int(len(numeric_vals)),
        }
    return {"samples": sample_count, "features": summary}


def _check_feature_variance(
    feature_stats: dict,
    min_feature_std: float,
    min_relative_std_ratio: float,
    fail_on_low_variance: bool,
) -> None:
    features = feature_stats.get("features", {}) if isinstance(feature_stats, dict) else {}
    if not features:
        return
    std_values = [
        float((meta or {}).get("std", 0.0) or 0.0)
        for meta in features.values()
        if isinstance(meta, dict)
    ]
    positive_stds = [v for v in std_values if v > 0]
    median_std = float(np.median(np.asarray(positive_stds, dtype=np.float64))) if positive_stds else 0.0

    low_abs = []
    low_rel = []
    for name, meta in features.items():
        if not isinstance(meta, dict):
            continue
        std = float(meta.get("std", 0.0) or 0.0)
        if std <= float(min_feature_std):
            low_abs.append(name)
            continue
        if median_std > 0 and std <= (median_std * float(min_relative_std_ratio)):
            low_rel.append(name)

    if not low_abs and not low_rel:
        return

    reasons = []
    if low_abs:
        reasons.append(f"abs_std<={min_feature_std:g}:{','.join(low_abs)}")
    if low_rel:
        reasons.append(f"rel_std<={min_relative_std_ratio:g}*median:{','.join(low_rel)}")
    message = f"low_feature_variance:{'|'.join(reasons)}"
    if fail_on_low_variance:
        raise SystemExit(message)
    print(f"warn:{message}")


def _check_feature_quality(
    feature_quality: dict,
    *,
    max_missing_ratio: float,
    max_invalid_ratio: float,
    min_unique_count: int,
    critical_features: List[str],
    fail_on_feature_quality: bool,
) -> None:
    features = feature_quality.get("features", {}) if isinstance(feature_quality, dict) else {}
    if not features:
        return
    bad: list[str] = []
    critical_set = {str(x).strip() for x in critical_features if str(x).strip()}
    for name, stats in features.items():
        if not isinstance(stats, dict):
            continue
        missing_ratio = float(stats.get("missing_ratio", 0.0) or 0.0)
        invalid_ratio = float(stats.get("invalid_ratio", 0.0) or 0.0)
        unique_count = int(stats.get("unique_count", 0) or 0)
        rules: list[str] = []
        if missing_ratio > float(max_missing_ratio):
            rules.append(f"missing>{max_missing_ratio:g}")
        if invalid_ratio > float(max_invalid_ratio):
            rules.append(f"invalid>{max_invalid_ratio:g}")
        if name in critical_set and unique_count < int(min_unique_count):
            rules.append(f"critical_unique<{int(min_unique_count)}")
        if rules:
            bad.append(f"{name}({','.join(rules)})")
    if not bad:
        return
    message = f"feature_quality_fail:{'|'.join(bad)}"
    if fail_on_feature_quality:
        raise SystemExit(message)
    print(f"warn:{message}")


def _check_dead_feature_ratio(
    *,
    feature_stats: dict,
    feature_quality: dict,
    max_dead_feature_ratio: float,
    dead_feature_std_threshold: float,
    critical_features: List[str],
    fail_on_dead_features: bool,
) -> None:
    stats_features = feature_stats.get("features", {}) if isinstance(feature_stats, dict) else {}
    quality_features = feature_quality.get("features", {}) if isinstance(feature_quality, dict) else {}
    if not stats_features:
        return
    critical_set = {str(x).strip() for x in critical_features if str(x).strip()}
    dead_features: list[str] = []
    dead_critical: list[str] = []
    for name, meta in stats_features.items():
        if not isinstance(meta, dict):
            continue
        std = float(meta.get("std", 0.0) or 0.0)
        uniq = int((quality_features.get(name) or {}).get("unique_count", 0) or 0)
        is_dead = std <= float(dead_feature_std_threshold) or uniq <= 1
        if not is_dead:
            continue
        dead_features.append(str(name))
        if str(name) in critical_set:
            dead_critical.append(str(name))
    if not dead_features:
        return
    total_features = max(1, len(stats_features))
    dead_ratio = float(len(dead_features) / float(total_features))
    if dead_critical:
        message = "dead_critical_features:" + ",".join(sorted(dead_critical))
        if fail_on_dead_features:
            raise SystemExit(message)
        print(f"warn:{message}")
    if dead_ratio > float(max_dead_feature_ratio):
        message = (
            f"dead_feature_ratio_too_high:{dead_ratio:.6f}>{float(max_dead_feature_ratio):.6f}"
            f":dead={','.join(sorted(dead_features))}"
        )
        if fail_on_dead_features:
            raise SystemExit(message)
        print(f"warn:{message}")


def _walk_forward_slices(
    row_count: int,
    train_ratio: float,
    folds: int,
) -> List[Tuple[int, int, int]]:
    if row_count <= 0 or folds <= 1:
        return []
    min_train = int(row_count * train_ratio)
    min_train = max(20, min_train)
    if min_train >= row_count - 1:
        return []
    remaining = row_count - min_train
    test_size = max(1, remaining // folds)
    slices: List[Tuple[int, int, int]] = []
    for fold in range(folds):
        train_end = min_train + (fold * test_size)
        test_end = min(row_count, train_end + test_size)
        if train_end < 20 or test_end <= train_end:
            continue
        slices.append((fold + 1, train_end, test_end))
    return slices



def _export_onnx(model, feature_count: int, output_path: str) -> None:
    from onnxmltools.convert.common.data_types import FloatTensorType

    initial_type = [("features", FloatTensorType([None, feature_count]))]
    try:
        onnx_model = convert_lightgbm(model, initial_types=initial_type)
    except Exception as exc:
        print(f"error:onnx_conversion_failed:{exc}")
        sys.exit(1)
    with open(output_path, "wb") as handle:
        handle.write(onnx_model.SerializeToString())

def _extract_probabilities_from_outputs(
    outputs: list, output_names: list[str], class_count: int
) -> list[float]:
    """Extract class probabilities from ONNX outputs, handling both zipmap and tensor formats."""
    for name, value in zip(output_names, outputs):
        if "prob" in name.lower():
            probs = _coerce_probs(value, class_count)
            if probs is not None:
                return probs
    # Fallback: try each output
    for value in outputs:
        probs = _coerce_probs(value, class_count)
        if probs is not None:
            return probs
    # Last resort: second output (index 1) is often probabilities
    if len(outputs) > 1:
        probs = _coerce_probs(outputs[1], class_count)
        if probs is not None:
            return probs
    raise ValueError(f"Could not extract {class_count} probabilities from ONNX outputs")


def _coerce_probs(value, class_count: int) -> list[float] | None:
    """Coerce a single ONNX output value into a flat list of floats."""
    if hasattr(value, "tolist"):
        value = value.tolist()
    # Unwrap nested list [[p0, p1, p2]] -> [p0, p1, p2]
    if isinstance(value, list) and len(value) == 1 and isinstance(value[0], (list, dict)):
        value = value[0]
    # Zipmap dict: {0: p0, 1: p1, 2: p2} or {"down": p0, ...}
    if isinstance(value, dict):
        if all(isinstance(k, int) for k in value.keys()):
            return [float(value.get(i, 0.0)) for i in range(class_count)]
        return [float(v) for v in list(value.values())[:class_count]]
    # Flat list of floats
    if isinstance(value, list) and len(value) == class_count:
        return [float(v) for v in value]
    return None


def _model_predict(model: Pipeline | LGBMClassifier, x: np.ndarray):
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message=r"X does not have valid feature names, but LGBMClassifier was fitted with feature names",
            category=UserWarning,
        )
        return model.predict(x)


def _model_predict_proba(model: Pipeline | LGBMClassifier, x: np.ndarray):
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message=r"X does not have valid feature names, but LGBMClassifier was fitted with feature names",
            category=UserWarning,
        )
        return model.predict_proba(x)


def _smoke_test_onnx(output_path: str, feature_count: int, class_count: int = 3) -> None:
    """Load exported ONNX model and verify it produces valid probability output."""
    import onnxruntime as ort

    session = ort.InferenceSession(output_path)
    dummy = np.zeros((1, feature_count), dtype=np.float32)
    input_name = session.get_inputs()[0].name
    outputs = session.run(None, {input_name: dummy})
    output_names = [o.name for o in session.get_outputs()]
    probs = _extract_probabilities_from_outputs(outputs, output_names, class_count)
    assert len(probs) == class_count, f"Expected {class_count} probs, got {len(probs)}"
    assert abs(sum(probs) - 1.0) < 1e-4, f"Probs sum to {sum(probs)}, expected ~1.0"
    print(f"onnx_smoke_test:pass:probs={[round(p, 4) for p in probs]}")




def _label_balance(label_counts: Dict[str, int]) -> dict:
    total = sum(label_counts.values())
    if total <= 0:
        return {"total": 0, "ratios": {}, "min_ratio": 0.0}
    ratios = {label: count / total for label, count in label_counts.items()}
    min_ratio = min(ratios.values()) if ratios else 0.0
    return {"total": total, "ratios": ratios, "min_ratio": min_ratio}

def _compute_dataset_fingerprint(csv_path: str) -> str:
    """Return SHA-256 hex digest of the raw CSV file bytes."""
    h = hashlib.sha256()
    try:
        with open(csv_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
    except IOError:
        return "error:unreadable"
    return h.hexdigest()



def main() -> None:
    parser = argparse.ArgumentParser(description="Train a baseline classifier and export to ONNX.")
    parser.add_argument("--input", default="prediction_dataset.csv", help="Input CSV path.")
    parser.add_argument("--output", default="prediction_baseline.onnx", help="Output ONNX path.")
    parser.add_argument(
        "--config",
        default="prediction_baseline.json",
        help="Output JSON config with features/labels.",
    )
    parser.add_argument(
        "--features",
        default=None,
        help="Comma-separated feature keys (default: infer from CSV).",
    )
    parser.add_argument("--labels", default=",".join(DEFAULT_LABELS), help="Comma-separated labels.")
    parser.add_argument("--train-ratio", type=float, default=0.8, help="Train split ratio.")
    parser.add_argument(
        "--calibration-ratio",
        type=float,
        default=0.2,
        help="Fraction of train rows used to fit probability calibration parameters.",
    )
    parser.add_argument("--seed", type=int, default=7, help="Random seed.")
    parser.add_argument(
        "--split",
        default="time",
        choices=["time", "random"],
        help="Train/test split method (time is safer; random can overstate metrics).",
    )
    parser.add_argument(
        "--class-weight",
        default="balanced",
        choices=["balanced", "none"],
        help="Class weighting strategy for logistic regression (default: balanced).",
    )
    parser.add_argument(
        "--min-class-ratio",
        type=float,
        default=0.05,
        help="Minimum fraction required for each class.",
    )
    parser.add_argument(
        "--fail-on-imbalance",
        action="store_true",
        help="Abort training if class balance is below the minimum ratio.",
    )
    parser.add_argument(
        "--calibration-bins",
        type=int,
        default=10,
        help="Number of bins for calibration ECE metrics.",
    )
    parser.add_argument(
        "--disable-calibration",
        action="store_true",
        help="Skip fitting probability calibration parameters.",
    )
    parser.add_argument(
        "--prediction-contract",
        default="tp_before_sl_within_horizon",
        help="Semantic contract for model probabilities (stored in config).",
    )
    parser.add_argument(
        "--min-feature-std",
        type=float,
        default=1e-9,
        help="Minimum absolute std per feature before warning/failing.",
    )
    parser.add_argument(
        "--min-relative-std-ratio",
        type=float,
        default=0.001,
        help="Minimum std ratio vs median(std) before warning/failing.",
    )
    parser.add_argument(
        "--fail-on-low-variance",
        action="store_true",
        help="Abort training when one or more features have very low variance.",
    )
    parser.add_argument(
        "--max-missing-ratio",
        type=float,
        default=0.10,
        help="Maximum allowed per-feature missing ratio in raw training rows.",
    )
    parser.add_argument(
        "--max-invalid-ratio",
        type=float,
        default=0.02,
        help="Maximum allowed per-feature invalid/non-finite ratio in raw training rows.",
    )
    parser.add_argument(
        "--min-unique-count-critical",
        type=int,
        default=2,
        help="Minimum unique numeric values required for critical features.",
    )
    parser.add_argument(
        "--critical-features",
        default="ema_fast_15m,ema_slow_15m,atr_5m,atr_5m_baseline,spread_bps",
        help="Comma-separated critical feature names subject to unique-count check.",
    )
    parser.add_argument(
        "--fail-on-feature-quality",
        action="store_true",
        help="Abort when feature quality checks (missing/invalid/critical uniqueness) fail.",
    )
    parser.add_argument(
        "--max-dead-feature-ratio",
        type=float,
        default=0.25,
        help="Maximum allowed ratio of dead/constant features.",
    )
    parser.add_argument(
        "--dead-feature-std-threshold",
        type=float,
        default=1e-12,
        help="Std threshold below which a feature is treated as dead.",
    )
    parser.add_argument(
        "--fail-on-dead-features",
        action="store_true",
        help="Abort when dead feature ratio/critical dead features exceed limits.",
    )
    parser.add_argument(
        "--walk-forward-folds",
        type=int,
        default=1,
        help="Walk-forward fold count for out-of-time validation (1 disables).",
    )
    parser.add_argument(
        "--ev-cost-bps",
        type=float,
        default=12.0,
        help="Cost assumption in bps for EV-after-cost metric.",
    )
    parser.add_argument(
        "--ev-reward-ratio",
        type=float,
        default=1.5,
        help="Reward ratio R used by EV-after-cost metric.",
    )
    parser.add_argument(
        "--n-estimators",
        type=int,
        default=300,
        help="Number of boosting rounds for LightGBM (default: 300).",
    )
    parser.add_argument(
        "--max-depth",
        type=int,
        default=6,
        help="Maximum tree depth for LightGBM (default: 6).",
    )
    parser.add_argument(
        "--learning-rate",
        type=float,
        default=0.05,
        help="Boosting learning rate for LightGBM (default: 0.05).",
    )
    parser.add_argument(
        "--num-leaves",
        type=int,
        default=31,
        help="Maximum number of leaves per tree for LightGBM (default: 31).",
    )
    parser.add_argument(
        "--min-child-samples",
        type=int,
        default=20,
        help="Minimum samples in a leaf for LightGBM (default: 20).",
    )
    parser.add_argument(
        "--dataset-metadata",
        default=None,
        help="Optional replay metadata JSON to persist training signatures.",
    )
    parser.add_argument(
        "--market-type",
        choices=["perp", "spot"],
        default=None,
        help="Market type. 'spot' auto-sets --ev-cost-bps=20 if not explicitly provided.",
    )
    args = parser.parse_args()
    if args.market_type == "spot" and args.ev_cost_bps == 12.0:
        args.ev_cost_bps = 20.0

    baseline_metrics = None
    baseline_path = os.path.join(os.path.dirname(args.config), "latest.json")
    try:
        with open(baseline_path, "r") as f:
            baseline_data = json.load(f)
        baseline_metrics = {
            "f1_down": baseline_data.get("metrics", {}).get("f1_down", 0.0),
            "f1_up": baseline_data.get("metrics", {}).get("f1_up", 0.0),
            "directional_f1_macro": baseline_data.get("metrics", {}).get("directional_f1_macro", 0.0),
            "ev_after_costs_mean": baseline_data.get("trading_metrics", {}).get("ev_after_costs_mean", 0.0),
            "directional_accuracy": baseline_data.get("trading_metrics", {}).get("directional_accuracy", 0.0),
        }
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        print("warn:baseline_not_found_skipping_comparison")
        baseline_metrics = None

    rows = _load_rows(args.input)
    if not rows:
        raise SystemExit("no_rows")

    feature_keys = [item.strip() for item in (args.features or "").split(",") if item.strip()]
    if not feature_keys:
        feature_keys = _infer_features(rows)
    labels = [item.strip() for item in args.labels.split(",") if item.strip()]
    if not labels:
        labels = DEFAULT_LABELS
    feature_quality = _raw_feature_quality(rows, feature_keys)
    critical_features = [item.strip() for item in str(args.critical_features or "").split(",") if item.strip()]
    _check_feature_quality(
        feature_quality,
        max_missing_ratio=float(args.max_missing_ratio),
        max_invalid_ratio=float(args.max_invalid_ratio),
        min_unique_count=int(args.min_unique_count_critical),
        critical_features=critical_features,
        fail_on_feature_quality=bool(args.fail_on_feature_quality),
    )

    action_contract = str(args.prediction_contract or "").strip().lower() == "action_conditional_pnl_winprob"
    if action_contract:
        x, y_multi = _build_action_conditional_arrays(rows, feature_keys)
        if len(x) == 0:
            raise SystemExit("no_training_rows")
        y = y_multi[:, 0]
        balance = {
            "total": int(len(y_multi)),
            "ratios": {
                "y_long_1": float(np.mean(y_multi[:, 0].astype(np.float64))),
                "y_short_1": float(np.mean(y_multi[:, 1].astype(np.float64))),
            },
            "min_ratio": float(
                min(
                    np.mean(y_multi[:, 0].astype(np.float64)),
                    1.0 - np.mean(y_multi[:, 0].astype(np.float64)),
                    np.mean(y_multi[:, 1].astype(np.float64)),
                    1.0 - np.mean(y_multi[:, 1].astype(np.float64)),
                )
            ),
        }
    else:
        x, y, label_counts = _build_arrays(rows, feature_keys, labels)
        if len(x) == 0:
            raise SystemExit("no_training_rows")
        balance = _label_balance(label_counts)
        if balance["total"] and balance["min_ratio"] < args.min_class_ratio:
            msg = f"class_imbalance:{balance['ratios']}"
            if args.fail_on_imbalance:
                raise SystemExit(msg)
            print(f"warn:{msg}")

    if args.split == "random":
        if action_contract:
            indices = list(range(len(x)))
            random.Random(args.seed).shuffle(indices)
            split = int(len(indices) * args.train_ratio)
            train_idx = indices[:split]
            test_idx = indices[split:]
            x_train, x_test = x[train_idx], x[test_idx]
            y_train, y_test = y_multi[train_idx], y_multi[test_idx]
        else:
            x_train, x_test, y_train, y_test = _train_test_split(x, y, args.train_ratio, args.seed)
    else:
        # We want the same filtered row set used to create x/y.
        if action_contract:
            timestamps = []
            for row in rows:
                try:
                    timestamps.append(float(row.get("timestamp") or 0.0))
                except (TypeError, ValueError):
                    timestamps.append(0.0)
            order = sorted(range(len(timestamps)), key=lambda i: timestamps[i])
            split = int(len(order) * args.train_ratio)
            train_idx = order[:split]
            test_idx = order[split:]
            x_train, x_test = x[train_idx], x[test_idx]
            y_train, y_test = y_multi[train_idx], y_multi[test_idx]
        else:
            filtered_rows = [r for r in rows if r.get("label") in set(labels)]
            x_train, x_test, y_train, y_test = _time_split(filtered_rows, x, y, args.train_ratio)
    if action_contract:
        x_fit, y_fit = x_train, y_train
        x_cal_fit, y_cal_fit = x_train[:0], y_train[:0]
    else:
        x_fit, x_cal_fit, y_fit, y_cal_fit = _split_train_calibration(
            x_train,
            y_train,
            calibration_ratio=args.calibration_ratio,
            split_mode=args.split,
            seed=args.seed,
        )
        if len(x_fit) == 0:
            x_fit, y_fit = x_train, y_train
            x_cal_fit, y_cal_fit = x_train[:0], y_train[:0]
    walk_forward = None
    if (not action_contract) and args.walk_forward_folds > 1 and args.split == "time":
        filtered_rows = [r for r in rows if r.get("label") in set(labels)]
        timestamps = []
        for row in filtered_rows:
            try:
                timestamps.append(float(row.get("timestamp") or 0.0))
            except (TypeError, ValueError):
                timestamps.append(0.0)
        order = sorted(range(len(timestamps)), key=lambda i: timestamps[i])
        slices = _walk_forward_slices(len(order), args.train_ratio, int(args.walk_forward_folds))
        fold_metrics = []
        for fold_idx, train_end, test_end in slices:
            train_idx = order[:train_end]
            test_idx = order[train_end:test_end]
            if not test_idx:
                continue
            model_fold = _train_model(
                x[train_idx],
                y[train_idx],
                class_weight=None if args.class_weight == "none" else args.class_weight,
                n_estimators=args.n_estimators,
                max_depth=args.max_depth,
                learning_rate=args.learning_rate,
                num_leaves=args.num_leaves,
                min_child_samples=args.min_child_samples,
                seed=args.seed,
            )
            eval_fold = _evaluate(model_fold, x[test_idx], y[test_idx], labels)
            trade_fold = _trading_objective_metrics(
                model_fold,
                x[test_idx],
                y[test_idx],
                labels,
                ev_reward_ratio=args.ev_reward_ratio,
                ev_cost_bps=args.ev_cost_bps,
            )
            fold_metrics.append(
                {
                    "fold": int(fold_idx),
                    "train_samples": int(len(train_idx)),
                    "test_samples": int(len(test_idx)),
                    "metrics": eval_fold,
                    "trading_metrics": trade_fold,
                }
            )
        if fold_metrics:
            directional_scores = [
                float((item.get("metrics") or {}).get("directional_f1_macro", 0.0))
                for item in fold_metrics
            ]
            ev_scores = [
                float((item.get("trading_metrics") or {}).get("ev_after_costs_mean", 0.0))
                for item in fold_metrics
            ]
            wf_score_v2_values = []
            for item in fold_metrics:
                wf_f1 = _clamp01(float((item.get("metrics") or {}).get("directional_f1_macro", 0.0) or 0.0))
                wf_ev = float((item.get("trading_metrics") or {}).get("ev_after_costs_mean", 0.0) or 0.0)
                wf_ev_component = 0.5 + (0.5 * np.tanh(wf_ev * 5.0))
                wf_score_v2_values.append(((wf_f1 * 0.6) + (float(wf_ev_component) * 0.4)) * 100.0)
            walk_forward = {
                "fold_count": int(len(fold_metrics)),
                "folds": fold_metrics,
                "directional_f1_macro_mean": float(np.mean(np.asarray(directional_scores, dtype=np.float64))),
                "directional_f1_macro_min": float(np.min(np.asarray(directional_scores, dtype=np.float64))),
                "ev_after_costs_mean": float(np.mean(np.asarray(ev_scores, dtype=np.float64))),
                "ev_after_costs_min": float(np.min(np.asarray(ev_scores, dtype=np.float64))),
                "promotion_score_v2_mean": float(np.mean(np.asarray(wf_score_v2_values, dtype=np.float64))),
                "promotion_score_v2_min": float(np.min(np.asarray(wf_score_v2_values, dtype=np.float64))),
            }
    class_weight = None if args.class_weight == "none" else args.class_weight
    feature_stats = _feature_stats(x, feature_keys)
    _check_feature_variance(
        feature_stats,
        min_feature_std=args.min_feature_std,
        min_relative_std_ratio=args.min_relative_std_ratio,
        fail_on_low_variance=args.fail_on_low_variance,
    )
    _check_dead_feature_ratio(
        feature_stats=feature_stats,
        feature_quality=feature_quality,
        max_dead_feature_ratio=float(args.max_dead_feature_ratio),
        dead_feature_std_threshold=float(args.dead_feature_std_threshold),
        critical_features=critical_features,
        fail_on_dead_features=bool(args.fail_on_dead_features),
    )
    if action_contract:
        model = _train_action_model(x_fit, y_fit, class_weight=class_weight)
        metrics, trading_metrics = _evaluate_action_model(model, x_test, y_test)
        probability_calibration = {
            "enabled": False,
            "method": "headwise_disabled_mvp",
            "samples": int(len(x_test)),
            "fit_samples": 0,
            "eval_samples": int(len(x_test)),
            "per_class": {
                "p_long_win": {"a": 1.0, "b": 0.0, "fitted": False},
                "p_short_win": {"a": 1.0, "b": 0.0, "fitted": False},
            },
            "metrics_before": {},
            "metrics_after": {},
        }
    else:
        model = _train_model(
            x_fit,
            y_fit,
            class_weight=class_weight,
            n_estimators=args.n_estimators,
            max_depth=args.max_depth,
            learning_rate=args.learning_rate,
            num_leaves=args.num_leaves,
            min_child_samples=args.min_child_samples,
            seed=args.seed,
        )
        metrics = _evaluate(model, x_test, y_test, labels)
        trading_metrics = _trading_objective_metrics(
            model,
            x_test,
            y_test,
            labels,
            ev_reward_ratio=args.ev_reward_ratio,
            ev_cost_bps=args.ev_cost_bps,
        )
        if args.disable_calibration:
            probability_calibration = {
                "enabled": False,
                "method": "disabled",
                "samples": int(len(x_test)),
                "fit_samples": 0,
                "eval_samples": int(len(x_test)),
                "per_class": {label: {"a": 1.0, "b": 0.0, "fitted": False} for label in labels},
                "metrics_before": _multiclass_calibration_metrics(
                    np.asarray(_model_predict_proba(model, x_test), dtype=np.float64)
                    if len(x_test)
                    else np.zeros((0, len(labels))),
                    y_test,
                    labels,
                    bins=args.calibration_bins,
                ),
                "metrics_after": {},
            }
        else:
            probability_calibration = _fit_probability_calibration(
                model,
                x_cal_fit,
                y_cal_fit,
                x_test,
                y_test,
                labels,
                bins=args.calibration_bins,
            )

    _export_onnx(model, len(feature_keys), args.output)
    _smoke_test_onnx(args.output, len(feature_keys))

    config = {
        "feature_keys": feature_keys,
        "class_labels": (["p_long_win", "p_short_win"] if action_contract else labels),
        "output_labels": (["p_long_win", "p_short_win"] if action_contract else labels),
        "prediction_contract": args.prediction_contract,
        "metrics": metrics,
        "trading_metrics": trading_metrics,
        "label_balance": balance,
        "feature_stats": feature_stats,
        "feature_quality": feature_quality,
        "probability_calibration": probability_calibration,
        "samples": {
            "total": int(len(x)),
            "train": int(len(x_train)),
            "fit": int(len(x_fit)),
            "calibration_fit": int(len(x_cal_fit)),
            "test": int(len(x_test)),
        },
        "onnx_path": args.output,
        "input": os.path.abspath(args.input),
    }
    if args.dataset_metadata:
        try:
            with open(args.dataset_metadata, "r", encoding="utf-8") as handle:
                dataset_meta = json.load(handle)
            config["replay_signature"] = {
                "step_hz": dataset_meta.get("replay_step_hz"),
                "sample_mode": dataset_meta.get("replay_sample_mode"),
                "fill_cost_model": dataset_meta.get("fill_cost_model"),
                "replay_engine_config": dataset_meta.get("replay_engine_config"),
            }
        except Exception:
            config["replay_signature"] = {"error": "dataset_metadata_unreadable"}
    output_labels = config.get("output_labels") or []
    output_order_hash = hashlib.sha256(",".join(output_labels).encode("utf-8")).hexdigest() if output_labels else ""
    config["contract_version"] = "v1"
    config["output_order_hash"] = output_order_hash
    config["output_order_check"] = {"labels": output_labels, "sha256": output_order_hash}
    config["model_type"] = "lightgbm"
    config["model_params"] = {
        "n_estimators": args.n_estimators,
        "max_depth": args.max_depth,
        "learning_rate": args.learning_rate,
        "num_leaves": args.num_leaves,
        "min_child_samples": args.min_child_samples,
        "class_weight": args.class_weight,
        "seed": args.seed,
    }
    config["build_info"] = {
        "onnx_converter": "onnxmltools",
        "onnxmltools_version": onnxmltools.__version__,
        "lightgbm_version": lgb.__version__,
        "python_version": sys.version,
    }
    config["dataset_fingerprint"] = _compute_dataset_fingerprint(args.input)
    min_f1_down_threshold = float(os.getenv("PREDICTION_MIN_F1_DOWN_FOR_SHORT", "0.40"))
    short_f1_pass = metrics.get("f1_down", 0.0) >= min_f1_down_threshold
    rollout_gate = {
        "short_f1_pass": short_f1_pass,
        "f1_down": metrics.get("f1_down", 0.0),
        "threshold": min_f1_down_threshold,
    }
    if not short_f1_pass:
        print(f"warn:rollout_gate_fail:f1_down={metrics.get('f1_down', 0.0):.4f}<threshold={min_f1_down_threshold}")
    config["rollout_gate"] = rollout_gate
    if walk_forward is not None:
        config["walk_forward"] = walk_forward
    config["promotion_score_v2"] = _compute_promotion_score_v2(
        metrics=metrics,
        trading_metrics=trading_metrics,
        probability_calibration=probability_calibration,
    )
    with open(args.config, "w", encoding="utf-8") as handle:
        json.dump(config, handle, indent=2, sort_keys=True)

    if baseline_metrics is not None:
        print(f"baseline_comparison:f1_down={metrics.get('f1_down', 0.0)}(baseline={baseline_metrics['f1_down']})")
        print(f"baseline_comparison:f1_up={metrics.get('f1_up', 0.0)}(baseline={baseline_metrics['f1_up']})")
        print(f"baseline_comparison:directional_f1_macro={metrics.get('directional_f1_macro', 0.0)}(baseline={baseline_metrics['directional_f1_macro']})")
        print(f"baseline_comparison:accuracy={metrics.get('accuracy', 0.0)}(baseline=None)")
        print(f"baseline_comparison:directional_accuracy={trading_metrics.get('directional_accuracy', 0.0)}(baseline={baseline_metrics['directional_accuracy']})")
        print(f"baseline_comparison:ev_after_costs_mean={trading_metrics.get('ev_after_costs_mean', 0.0)}(baseline={baseline_metrics['ev_after_costs_mean']})")

    if not short_f1_pass:
        print(f"warn:skipping_model_promotion:rollout_gate_fail")
    else:
        print(f"onnx:{args.output}")
    print(f"config:{args.config}")
    print("env:PREDICTION_PROVIDER=onnx")
    if short_f1_pass:
        print(f"env:PREDICTION_MODEL_PATH={args.output}")
    print(f"env:PREDICTION_MODEL_FEATURES={','.join(feature_keys)}")
    print(f"env:PREDICTION_MODEL_CLASSES={','.join(labels)}")
    print(f"metrics:accuracy={metrics['accuracy']}")
    print(f"metrics:directional_f1_macro={metrics.get('directional_f1_macro', 0.0)}")
    print(f"metrics:win_auc_macro={metrics.get('win_auc_macro', 0.0)}")
    print(f"metrics:ev_after_costs_mean={trading_metrics.get('ev_after_costs_mean', 0.0)}")
    print(f"metrics:action_win_rate_mean={trading_metrics.get('action_win_rate_mean', 0.0)}")


if __name__ == "__main__":
    main()
