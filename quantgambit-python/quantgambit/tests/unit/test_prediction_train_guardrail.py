import pytest

import numpy as np

from scripts.train_prediction_baseline import (
    _check_dead_feature_ratio,
    _label_balance,
    _feature_stats,
)


def test_label_balance_ratios():
    balance = _label_balance({"down": 2, "flat": 2, "up": 6})
    assert balance["total"] == 10
    assert balance["min_ratio"] == 0.2


def test_label_balance_handles_empty():
    balance = _label_balance({})
    assert balance["total"] == 0
    assert balance["min_ratio"] == 0.0


def test_feature_stats_summary():
    x = np.array([[1.0, 2.0], [3.0, 4.0]], dtype=np.float32)
    stats = _feature_stats(x, ["a", "b"])
    assert stats["count"] == 2
    assert stats["features"]["a"]["mean"] == 2.0


def test_dead_feature_ratio_raises_for_critical_when_fail_closed():
    feature_stats = {
        "features": {
            "ema_fast_15m": {"std": 0.0},
            "spread_bps": {"std": 0.5},
        }
    }
    feature_quality = {
        "features": {
            "ema_fast_15m": {"unique_count": 1},
            "spread_bps": {"unique_count": 10},
        }
    }
    with pytest.raises(SystemExit) as exc:
        _check_dead_feature_ratio(
            feature_stats=feature_stats,
            feature_quality=feature_quality,
            max_dead_feature_ratio=0.9,
            dead_feature_std_threshold=1e-12,
            critical_features=["ema_fast_15m"],
            fail_on_dead_features=True,
        )
    assert "dead_critical_features" in str(exc.value)
