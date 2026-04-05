from scripts.retrain_prediction_baseline import (
    _build_drift_cmd,
    _candidate_beats_latest,
    _resolve_horizon_profile,
)


def test_build_drift_cmd_includes_thresholds():
    cmd = _build_drift_cmd(
        "python",
        "models/registry/latest.json",
        "events:features",
        1000,
        2.5,
        4.0,
        0.25,
    )
    assert cmd[0] == "python"
    assert "--model-config" in cmd
    assert "models/registry/latest.json" in cmd
    assert "--zscore" in cmd and "2.5" in cmd
    assert "--std-ratio-high" in cmd and "4.0" in cmd
    assert "--std-ratio-low" in cmd and "0.25" in cmd


def test_resolve_horizon_profile_scalp_3m():
    horizon_sec, up_th, down_th = _resolve_horizon_profile("scalp_3m", 999.0, 1.0, -1.0)
    assert horizon_sec == 180.0
    assert up_th == 0.0007
    assert down_th == -0.0007


def test_candidate_beats_latest_blocks_low_short_f1():
    latest = {
        "metrics": {"directional_f1_macro": 0.30},
        "trading_metrics": {"ev_after_costs_mean": 0.01},
    }
    candidate = {
        "metrics": {
            "directional_f1_macro": 0.40,
            "f1_down": 0.20,
            "f1_up": 0.80,
            "confusion_matrix": [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
        },
        "trading_metrics": {
            "ev_after_costs_mean": 0.02,
            "directional_accuracy_long": 0.60,
            "directional_accuracy_short": 0.60,
            "directional_samples": 300,
        },
        "samples": {"total": 1000},
        "label_balance": {"ratios": {"flat": 0.3}},
        "class_labels": ["down", "flat", "up"],
        "probability_calibration": {"metrics_after": {"ece_top1": 0.10}},
        "walk_forward": {
            "directional_f1_macro_mean": 0.35,
            "ev_after_costs_mean": 0.01,
            "promotion_score_v2_mean": 60.0,
        },
        "promotion_score_v2": {"score": 65.0},
    }
    ok, reason = _candidate_beats_latest(
        latest_payload=latest,
        candidate_payload=candidate,
        min_f1_delta=0.0,
        min_ev_delta=0.0,
        min_directional_f1=0.25,
        min_ev_after_costs=0.0,
        min_walk_forward_directional_f1=0.2,
        min_walk_forward_ev_after_costs=0.0,
        min_promotion_score_v2=0.0,
        min_walk_forward_promotion_score_v2=0.0,
        min_prediction_ratio_down=0.0,
        min_prediction_ratio_up=0.0,
        min_directional_prediction_coverage=0.0,
        min_flat_label_ratio=0.0,
        min_f1_down=0.35,
        min_f1_up=0.70,
        min_directional_accuracy_long=0.5,
        min_directional_accuracy_short=0.5,
        max_ece_top1=0.22,
        min_total_samples=100,
        min_directional_samples=50,
    )
    assert not ok
    assert reason.startswith("candidate_f1_down_below_min")


def test_candidate_beats_latest_blocks_rollout_gate_fail():
    latest = {
        "metrics": {"directional_f1_macro": 0.30},
        "trading_metrics": {"ev_after_costs_mean": 0.01},
    }
    candidate = {
        "rollout_gate": {"short_f1_pass": False, "f1_down": 0.20, "threshold": 0.40},
        "metrics": {
            "directional_f1_macro": 0.50,
            "f1_down": 0.50,
            "f1_up": 0.80,
            "confusion_matrix": [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
        },
        "trading_metrics": {
            "ev_after_costs_mean": 0.03,
            "directional_accuracy_long": 0.60,
            "directional_accuracy_short": 0.60,
            "directional_samples": 300,
        },
        "samples": {"total": 1000},
        "label_balance": {"ratios": {"flat": 0.3}},
        "class_labels": ["down", "flat", "up"],
        "probability_calibration": {"metrics_after": {"ece_top1": 0.10}},
        "walk_forward": {
            "directional_f1_macro_mean": 0.35,
            "ev_after_costs_mean": 0.01,
            "promotion_score_v2_mean": 60.0,
        },
        "promotion_score_v2": {"score": 65.0},
    }
    ok, reason = _candidate_beats_latest(
        latest_payload=latest,
        candidate_payload=candidate,
        min_f1_delta=0.0,
        min_ev_delta=0.0,
        min_directional_f1=0.25,
        min_ev_after_costs=0.0,
        min_walk_forward_directional_f1=0.2,
        min_walk_forward_ev_after_costs=0.0,
        min_promotion_score_v2=0.0,
        min_walk_forward_promotion_score_v2=0.0,
        min_prediction_ratio_down=0.0,
        min_prediction_ratio_up=0.0,
        min_directional_prediction_coverage=0.0,
        min_flat_label_ratio=0.0,
        min_f1_down=0.35,
        min_f1_up=0.70,
        min_directional_accuracy_long=0.5,
        min_directional_accuracy_short=0.5,
        max_ece_top1=0.22,
        min_total_samples=100,
        min_directional_samples=50,
    )
    assert not ok
    assert reason.startswith("candidate_rollout_gate_short_f1_fail")
