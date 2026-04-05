import json

import pytest

from quantgambit.config.confirmation_policy import load_confirmation_policy_config


def test_load_confirmation_policy_config_from_json(monkeypatch):
    payload = {
        "mode": "enforce",
        "entry": {"min_confidence": 0.7, "min_votes": 2},
        "exit_non_emergency": {"min_confidence": 0.55, "min_votes": 2},
        "weights": {"trend": 1.2, "flow": 1.0, "risk_stability": 0.8},
        "strategy_overrides": {
            "breakout_scalp": {
                "weights": {"trend": 1.5, "flow": 1.1, "risk_stability": 0.9},
                "thresholds": {"entry_min_confidence": 0.75, "exit_min_votes": 3},
            }
        },
    }
    monkeypatch.setenv("CONFIRMATION_POLICY_CONFIG_JSON", json.dumps(payload))

    config = load_confirmation_policy_config()

    assert config.mode == "enforce"
    assert config.entry.min_confidence == pytest.approx(0.7)
    assert config.exit_non_emergency.min_confidence == pytest.approx(0.55)
    assert "breakout_scalp" in config.strategy_overrides
    override = config.strategy_overrides["breakout_scalp"]
    assert override.weights is not None
    assert override.weights.trend == pytest.approx(1.5)
    assert override.entry_min_confidence == pytest.approx(0.75)
    assert override.exit_min_votes == 3


def test_load_confirmation_policy_config_strategy_override_env(monkeypatch):
    overrides = {
        "mean_reversion_fade": {
            "weights": {"trend": 0.9, "flow": 1.3, "risk_stability": 1.2},
            "entry_min_votes": 2,
            "exit_min_confidence": 0.58,
        }
    }
    monkeypatch.setenv("CONFIRMATION_POLICY_STRATEGY_OVERRIDES_JSON", json.dumps(overrides))

    config = load_confirmation_policy_config()

    assert "mean_reversion_fade" in config.strategy_overrides
    override = config.strategy_overrides["mean_reversion_fade"]
    assert override.weights is not None
    assert override.weights.flow == pytest.approx(1.3)
    assert override.entry_min_votes == 2
    assert override.exit_min_confidence == pytest.approx(0.58)


def test_load_confirmation_policy_config_rejects_invalid_override(monkeypatch):
    monkeypatch.setenv(
        "CONFIRMATION_POLICY_STRATEGY_OVERRIDES_JSON",
        json.dumps({
            "poc_magnet_scalp": {
                "weights": {"trend": 999.0, "flow": 1.0, "risk_stability": 1.0}
            }
        }),
    )

    with pytest.raises(ValueError, match="out of bounds"):
        load_confirmation_policy_config()


def test_load_confirmation_policy_config_shadow_overrides(monkeypatch):
    monkeypatch.delenv("CONFIRMATION_POLICY_CONFIG_JSON", raising=False)
    monkeypatch.delenv("CONFIRMATION_POLICY_STRATEGY_OVERRIDES_JSON", raising=False)

    config = load_confirmation_policy_config(
        {
            "confirmation_policy_mode": "enforce",
            "confirmation_policy_entry_min_confidence": 0.77,
            "confirmation_policy_strategy_overrides": {
                "breakout_scalp": {
                    "weights": {"trend": 1.4, "flow": 1.1, "risk_stability": 1.0},
                    "thresholds": {"entry_min_votes": 3},
                }
            },
        }
    )

    assert config.mode == "enforce"
    assert config.entry.min_confidence == pytest.approx(0.77)
    assert "breakout_scalp" in config.strategy_overrides
    assert config.strategy_overrides["breakout_scalp"].entry_min_votes == 3
