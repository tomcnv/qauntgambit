from scripts.feature_drift_check import (
    DriftThresholds,
    _compare_stats,
    _compute_stats,
)


def test_compute_stats():
    stats = _compute_stats({"price": [1.0, 3.0]})
    assert stats["price"]["count"] == 2
    assert stats["price"]["mean"] == 2.0


def test_compare_stats_flags_mean_shift():
    model = {"price": {"mean": 1.0, "std": 0.5}}
    current = {"price": {"count": 2, "mean": 2.5, "std": 0.5}}
    drift = _compare_stats(model, current, DriftThresholds(zscore=2.0))
    assert drift["price"]["status"] == "drift"


def test_compare_stats_handles_missing():
    model = {"price": {"mean": 1.0, "std": 0.5}}
    current = {"price": {"count": 0}}
    drift = _compare_stats(model, current, DriftThresholds())
    assert drift["price"]["status"] == "missing"
