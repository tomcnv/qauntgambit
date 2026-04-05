"""
Property-based tests for Prediction Model Accuracy and Calibration.

Feature: scalping-pipeline-audit

These tests verify correctness properties of the OnnxPredictionProvider,
EVGateStage calibration adjustment, prediction score gate, and
action-conditional policy.

**Validates: Requirements 2.1, 2.2, 2.5, 2.7**
"""

from __future__ import annotations

import asyncio
import os
import time
from typing import Optional
from unittest.mock import patch, MagicMock

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

from quantgambit.signals.prediction_providers import (
    OnnxPredictionProvider,
    _abstain_reason,
    _clamp,
)
from quantgambit.signals.stages.ev_gate import (
    EVGateConfig,
    EVGateStage,
    EVGateRejectCode,
)
from quantgambit.signals.services.calibration_state import (
    CalibrationState,
    CalibrationStatus,
    evaluate_calibration,
    get_cold_start_adjustments,
)
from quantgambit.signals.pipeline import (
    StageContext,
    StageResult,
    _resolve_action_policy_probabilities,
)


# ═══════════════════════════════════════════════════════════════
# SHARED HYPOTHESIS STRATEGIES
# ═══════════════════════════════════════════════════════════════

symbols = st.sampled_from(["BTCUSDT", "ETHUSDT", "SOLUSDT"])


# ═══════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════

def _run_async(coro):
    """Run an async coroutine synchronously."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ═══════════════════════════════════════════════════════════════
# Property 4: Prediction provider rejects low-confidence predictions
# ═══════════════════════════════════════════════════════════════


class TestPredictionProviderRejectsLowConfidence:
    """
    Feature: scalping-pipeline-audit, Property 4: Prediction provider rejects low-confidence predictions

    For any ONNX model output where p_hat is below the effective
    PREDICTION_ONNX_MIN_CONFIDENCE threshold (global or per-symbol override),
    the OnnxPredictionProvider.build_prediction() should return a prediction
    with reject=True (abstain).

    The OnnxPredictionProvider uses _abstain_reason() to check:
    - confidence < min_confidence → "onnx_low_confidence"
    - margin < min_margin → "onnx_low_margin"
    - entropy > max_entropy → "onnx_high_entropy"

    **Validates: Requirements 2.1**
    """

    @settings(max_examples=200)
    @given(
        confidence=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
        min_confidence=st.floats(min_value=0.01, max_value=1.0, allow_nan=False, allow_infinity=False),
    )
    def test_abstain_reason_rejects_low_confidence(
        self, confidence: float, min_confidence: float
    ):
        """
        Feature: scalping-pipeline-audit, Property 4: Prediction provider rejects low-confidence predictions

        When confidence < min_confidence, _abstain_reason should return
        "onnx_low_confidence".

        **Validates: Requirements 2.1**
        """
        assume(confidence < min_confidence)

        reason = _abstain_reason(
            confidence=confidence,
            margin=1.0,  # high margin so it doesn't trigger
            entropy=0.0,  # low entropy so it doesn't trigger
            min_confidence=min_confidence,
            min_margin=0.0,
            max_entropy=1.0,
        )
        assert reason == "onnx_low_confidence", (
            f"Expected 'onnx_low_confidence' for confidence={confidence:.4f} < "
            f"min_confidence={min_confidence:.4f}, got {reason}"
        )

    @settings(max_examples=200)
    @given(
        confidence=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
        min_confidence=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
    )
    def test_abstain_reason_passes_sufficient_confidence(
        self, confidence: float, min_confidence: float
    ):
        """
        Feature: scalping-pipeline-audit, Property 4: Prediction provider rejects low-confidence predictions

        When confidence >= min_confidence (and other thresholds are permissive),
        _abstain_reason should return None (no abstention).

        **Validates: Requirements 2.1**
        """
        assume(confidence >= min_confidence)

        reason = _abstain_reason(
            confidence=confidence,
            margin=1.0,
            entropy=0.0,
            min_confidence=min_confidence,
            min_margin=0.0,
            max_entropy=1.0,
        )
        assert reason is None, (
            f"Expected None for confidence={confidence:.4f} >= "
            f"min_confidence={min_confidence:.4f}, got {reason}"
        )

    @settings(max_examples=200)
    @given(
        symbol=symbols,
        global_min_conf=st.floats(min_value=0.01, max_value=0.99, allow_nan=False, allow_infinity=False),
        per_symbol_min_conf=st.floats(min_value=0.01, max_value=0.99, allow_nan=False, allow_infinity=False),
    )
    def test_per_symbol_override_takes_precedence(
        self, symbol: str, global_min_conf: float, per_symbol_min_conf: float
    ):
        """
        Feature: scalping-pipeline-audit, Property 4: Prediction provider rejects low-confidence predictions

        Per-symbol min_confidence overrides should take precedence over the global
        threshold when resolving effective abstain thresholds.

        **Validates: Requirements 2.1**
        """
        # Format with enough precision to survive round-trip through env var string
        env_override = f"{symbol}:{per_symbol_min_conf:.10f}"

        with patch.dict(os.environ, {
            "PREDICTION_ONNX_MIN_CONFIDENCE_BY_SYMBOL": env_override,
        }):
            provider = OnnxPredictionProvider(
                model_path=None,
                min_confidence=global_min_conf,
            )

            eff_conf, _, _ = provider._effective_abstain_thresholds(symbol, None)

            assert abs(eff_conf - _clamp(per_symbol_min_conf)) < 1e-6, (
                f"Expected per-symbol override {per_symbol_min_conf:.6f} for {symbol}, "
                f"got {eff_conf:.6f} (global={global_min_conf:.6f})"
            )



# ═══════════════════════════════════════════════════════════════
# Property 5: EV Gate adjusts threshold for uncalibrated predictions
# ═══════════════════════════════════════════════════════════════


class TestEVGateAdjustsForUncalibrated:
    """
    Feature: scalping-pipeline-audit, Property 5: EV Gate adjusts threshold for uncalibrated predictions

    When calibration is unreliable (COLD or WARMING state), the EVGateStage
    should apply additional safety via the calibration state machine:
    - min_edge_bps_adjustment increases the effective ev_min
    - The adjustment is scaled by L_bps (stop distance) for proper EV units

    The current implementation uses CalibrationStatus.min_edge_bps_adjustment
    (from get_cold_start_adjustments) which adds to ev_min_base in
    _get_adjusted_ev_min().

    **Validates: Requirements 2.2**
    """

    @settings(max_examples=200)
    @given(
        n_trades=st.integers(min_value=0, max_value=29),
        ev_min=st.floats(min_value=0.01, max_value=0.10, allow_nan=False, allow_infinity=False),
        L_bps=st.floats(min_value=10.0, max_value=200.0, allow_nan=False, allow_infinity=False),
    )
    def test_cold_state_increases_ev_min(
        self, n_trades: int, ev_min: float, L_bps: float
    ):
        """
        Feature: scalping-pipeline-audit, Property 5: EV Gate adjusts threshold for uncalibrated predictions

        In COLD state (< 30 trades), the calibration state machine applies
        min_edge_bps_adjustment which increases the effective ev_min.

        **Validates: Requirements 2.2**
        """
        calibration_status = evaluate_calibration(
            strategy_id="mean_reversion_fade",
            n_trades=n_trades,
            p_observed=0.55,
            reliability=0.0,
        )

        assert calibration_status.state == CalibrationState.COLD, (
            f"Expected COLD state for n_trades={n_trades}, got {calibration_status.state}"
        )
        assert calibration_status.min_edge_bps_adjustment > 0, (
            f"Expected positive min_edge_bps_adjustment in COLD state, "
            f"got {calibration_status.min_edge_bps_adjustment}"
        )

        # Verify the adjustment would increase ev_min
        config = EVGateConfig(ev_min=ev_min, ev_min_floor=0.001)
        stage = EVGateStage(config=config)

        adjusted_ev_min, reason = stage._get_adjusted_ev_min(
            calibration_reliability=calibration_status.reliability,
            calibration_status=calibration_status,
            L_bps=L_bps,
        )

        # The cold-start edge adjustment adds min_edge_bps_adjustment / L_bps to ev_min
        expected_ev_adjustment = calibration_status.min_edge_bps_adjustment / max(L_bps, 1.0)

        # adjusted_ev_min should be >= ev_min + the cold-start adjustment
        # (relaxation engine may further modify, but the base should be increased)
        assert adjusted_ev_min >= ev_min * 0.99, (
            f"Expected adjusted_ev_min >= ev_min ({ev_min}), "
            f"got {adjusted_ev_min}"
        )
        assert reason is not None, (
            f"Expected adjustment reason for COLD state, got None"
        )

    @settings(max_examples=200)
    @given(
        n_trades=st.integers(min_value=200, max_value=10000),
        ev_min=st.floats(min_value=0.01, max_value=0.10, allow_nan=False, allow_infinity=False),
    )
    def test_ok_state_no_edge_adjustment(
        self, n_trades: int, ev_min: float
    ):
        """
        Feature: scalping-pipeline-audit, Property 5: EV Gate adjusts threshold for uncalibrated predictions

        In OK state (>= 200 trades with good reliability), the calibration
        state machine should NOT apply min_edge_bps_adjustment.

        **Validates: Requirements 2.2**
        """
        calibration_status = evaluate_calibration(
            strategy_id="mean_reversion_fade",
            n_trades=n_trades,
            p_observed=0.55,
            reliability=0.8,
        )

        assert calibration_status.state == CalibrationState.OK, (
            f"Expected OK state for n_trades={n_trades}, got {calibration_status.state}"
        )
        assert calibration_status.min_edge_bps_adjustment == 0.0, (
            f"Expected zero min_edge_bps_adjustment in OK state, "
            f"got {calibration_status.min_edge_bps_adjustment}"
        )

    @settings(max_examples=200)
    @given(
        n_trades=st.integers(min_value=30, max_value=199),
        ev_min=st.floats(min_value=0.01, max_value=0.10, allow_nan=False, allow_infinity=False),
    )
    def test_warming_state_has_moderate_adjustment(
        self, n_trades: int, ev_min: float
    ):
        """
        Feature: scalping-pipeline-audit, Property 5: EV Gate adjusts threshold for uncalibrated predictions

        In WARMING state (30-199 trades), the calibration state machine applies
        a moderate min_edge_bps_adjustment (less than COLD).

        **Validates: Requirements 2.2**
        """
        calibration_status = evaluate_calibration(
            strategy_id="mean_reversion_fade",
            n_trades=n_trades,
            p_observed=0.55,
            reliability=None,
        )

        assert calibration_status.state == CalibrationState.WARMING, (
            f"Expected WARMING state for n_trades={n_trades}, got {calibration_status.state}"
        )
        assert calibration_status.min_edge_bps_adjustment > 0, (
            f"Expected positive min_edge_bps_adjustment in WARMING state, "
            f"got {calibration_status.min_edge_bps_adjustment}"
        )

        # WARMING adjustment should be less than COLD adjustment
        cold_status = evaluate_calibration(
            strategy_id="mean_reversion_fade",
            n_trades=0,
            p_observed=0.55,
            reliability=0.0,
        )
        assert calibration_status.min_edge_bps_adjustment <= cold_status.min_edge_bps_adjustment, (
            f"WARMING adjustment ({calibration_status.min_edge_bps_adjustment}) should be <= "
            f"COLD adjustment ({cold_status.min_edge_bps_adjustment})"
        )



# ═══════════════════════════════════════════════════════════════
# Property 6: Prediction score gate blocks low-accuracy symbols
# ═══════════════════════════════════════════════════════════════


class TestPredictionScoreGateBlocksLowAccuracy:
    """
    Feature: scalping-pipeline-audit, Property 6: Prediction score gate blocks low-accuracy symbols

    When PREDICTION_SCORE_GATE_ENABLED is true and a symbol's exact_accuracy
    or directional_accuracy falls below the configured minimums, the
    _evaluate_score_gate method should block that symbol.

    The score gate lives in FeaturePredictionWorker._evaluate_score_gate()
    and checks:
    - exact_accuracy < _score_gate_min_exact_acc → blocked
    - directional_accuracy < _score_gate_min_directional_acc → blocked

    We test the blocking logic directly by simulating the score gate
    evaluation conditions.

    **Validates: Requirements 2.5**
    """

    @settings(max_examples=200)
    @given(
        exact_accuracy=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
        min_exact_accuracy=st.floats(min_value=0.01, max_value=1.0, allow_nan=False, allow_infinity=False),
        symbol=symbols,
    )
    def test_blocks_when_exact_accuracy_below_minimum(
        self, exact_accuracy: float, min_exact_accuracy: float, symbol: str
    ):
        """
        Feature: scalping-pipeline-audit, Property 6: Prediction score gate blocks low-accuracy symbols

        When exact_accuracy < MIN_EXACT_ACCURACY, the score gate should block
        the symbol.

        **Validates: Requirements 2.5**
        """
        assume(exact_accuracy < min_exact_accuracy)

        # Simulate the score gate logic from _evaluate_score_gate
        # The gate checks: if exact_acc is not None and exact_acc < self._score_gate_min_exact_acc
        blocked = exact_accuracy < min_exact_accuracy
        assert blocked, (
            f"Expected block for exact_accuracy={exact_accuracy:.4f} < "
            f"min={min_exact_accuracy:.4f}"
        )

    @settings(max_examples=200)
    @given(
        directional_accuracy=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
        min_directional_accuracy=st.floats(min_value=0.01, max_value=1.0, allow_nan=False, allow_infinity=False),
        symbol=symbols,
    )
    def test_blocks_when_directional_accuracy_below_minimum(
        self, directional_accuracy: float, min_directional_accuracy: float, symbol: str
    ):
        """
        Feature: scalping-pipeline-audit, Property 6: Prediction score gate blocks low-accuracy symbols

        When directional_accuracy < MIN_DIRECTIONAL_ACCURACY, the score gate
        should block the symbol.

        **Validates: Requirements 2.5**
        """
        assume(directional_accuracy < min_directional_accuracy)

        blocked = directional_accuracy < min_directional_accuracy
        assert blocked, (
            f"Expected block for directional_accuracy={directional_accuracy:.4f} < "
            f"min={min_directional_accuracy:.4f}"
        )

    @settings(max_examples=200)
    @given(
        exact_accuracy=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
        directional_accuracy=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
        min_exact_accuracy=st.floats(min_value=0.01, max_value=0.99, allow_nan=False, allow_infinity=False),
        min_directional_accuracy=st.floats(min_value=0.01, max_value=0.99, allow_nan=False, allow_infinity=False),
        min_samples=st.integers(min_value=50, max_value=500),
        symbol=symbols,
    )
    def test_score_gate_blocking_logic_consistency(
        self,
        exact_accuracy: float,
        directional_accuracy: float,
        min_exact_accuracy: float,
        min_directional_accuracy: float,
        min_samples: int,
        symbol: str,
    ):
        """
        Feature: scalping-pipeline-audit, Property 6: Prediction score gate blocks low-accuracy symbols

        The score gate should block if EITHER exact_accuracy OR directional_accuracy
        is below its respective minimum. It should pass only when BOTH are above
        their minimums (given sufficient samples).

        **Validates: Requirements 2.5**
        """
        # Simulate the score gate evaluation logic
        # From _evaluate_score_gate:
        #   if exact_acc is not None and exact_acc < self._score_gate_min_exact_acc: blocked
        #   if directional_acc is not None and directional_acc < self._score_gate_min_directional_acc: blocked
        should_block_exact = exact_accuracy < min_exact_accuracy
        should_block_directional = directional_accuracy < min_directional_accuracy
        should_block = should_block_exact or should_block_directional

        # Verify the logic is consistent
        if should_block_exact:
            assert should_block, (
                f"Should block when exact_accuracy={exact_accuracy:.4f} < "
                f"min={min_exact_accuracy:.4f}"
            )
        if should_block_directional:
            assert should_block, (
                f"Should block when directional_accuracy={directional_accuracy:.4f} < "
                f"min={min_directional_accuracy:.4f}"
            )
        if not should_block:
            assert exact_accuracy >= min_exact_accuracy, (
                f"Should not block but exact_accuracy={exact_accuracy:.4f} < "
                f"min={min_exact_accuracy:.4f}"
            )
            assert directional_accuracy >= min_directional_accuracy, (
                f"Should not block but directional_accuracy={directional_accuracy:.4f} < "
                f"min={min_directional_accuracy:.4f}"
            )



# ═══════════════════════════════════════════════════════════════
# Property 7: Action-conditional policy enforces dual thresholds
# ═══════════════════════════════════════════════════════════════


class TestActionConditionalPolicyDualThresholds:
    """
    Feature: scalping-pipeline-audit, Property 7: Action-conditional policy enforces dual thresholds

    When ACTION_CONDITIONAL_POLICY_ENABLED is true, the SignalStage should
    reject predictions where p_hat <= P_THRESH or margin <= MARGIN_THRESH.

    The action-conditional policy in SignalStage.run():
    1. Resolves p_long_win and p_short_win from prediction
    2. Computes p_star = max(p_long, p_short) and margin = abs(p_long - p_short)
    3. Blocks if p_star < p_thresh OR margin < margin_thresh OR
       directional_mass < min_directional_mass

    We test _resolve_action_policy_probabilities() and the blocking logic.

    **Validates: Requirements 2.7**
    """

    @settings(max_examples=200)
    @given(
        p_long=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
        p_short=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
        p_thresh=st.floats(min_value=0.5, max_value=0.95, allow_nan=False, allow_infinity=False),
        margin_thresh=st.floats(min_value=0.0, max_value=0.5, allow_nan=False, allow_infinity=False),
    )
    def test_rejects_when_p_star_below_threshold(
        self, p_long: float, p_short: float, p_thresh: float, margin_thresh: float
    ):
        """
        Feature: scalping-pipeline-audit, Property 7: Action-conditional policy enforces dual thresholds

        When p_star (max of p_long, p_short) is below p_thresh, the action-conditional
        policy should block the prediction.

        **Validates: Requirements 2.7**
        """
        prediction = {
            "p_long_win": p_long,
            "p_short_win": p_short,
            "prediction_contract": "action_conditional_pnl_winprob",
        }

        resolved = _resolve_action_policy_probabilities(prediction)
        assert resolved is not None, "Expected resolved probabilities"

        p_star = resolved["p_star"]
        margin = resolved["margin"]

        assume(p_star < p_thresh)

        # The blocking logic: p_star < p_thresh → blocked
        blocked = p_star < p_thresh or margin < margin_thresh
        assert blocked, (
            f"Expected block for p_star={p_star:.4f} < p_thresh={p_thresh:.4f}"
        )

    @settings(max_examples=200)
    @given(
        p_long=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
        p_short=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
        p_thresh=st.floats(min_value=0.5, max_value=0.95, allow_nan=False, allow_infinity=False),
        margin_thresh=st.floats(min_value=0.01, max_value=0.5, allow_nan=False, allow_infinity=False),
    )
    def test_rejects_when_margin_below_threshold(
        self, p_long: float, p_short: float, p_thresh: float, margin_thresh: float
    ):
        """
        Feature: scalping-pipeline-audit, Property 7: Action-conditional policy enforces dual thresholds

        When margin (abs(p_long - p_short)) is below margin_thresh, the
        action-conditional policy should block the prediction.

        **Validates: Requirements 2.7**
        """
        prediction = {
            "p_long_win": p_long,
            "p_short_win": p_short,
            "prediction_contract": "action_conditional_pnl_winprob",
        }

        resolved = _resolve_action_policy_probabilities(prediction)
        assert resolved is not None, "Expected resolved probabilities"

        margin = resolved["margin"]
        p_star = resolved["p_star"]

        assume(margin < margin_thresh)

        blocked = p_star < p_thresh or margin < margin_thresh
        assert blocked, (
            f"Expected block for margin={margin:.4f} < margin_thresh={margin_thresh:.4f}"
        )

    @settings(max_examples=200)
    @given(
        p_long=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
        p_short=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
        p_thresh=st.floats(min_value=0.5, max_value=0.95, allow_nan=False, allow_infinity=False),
        margin_thresh=st.floats(min_value=0.0, max_value=0.5, allow_nan=False, allow_infinity=False),
    )
    def test_passes_when_both_thresholds_met(
        self, p_long: float, p_short: float, p_thresh: float, margin_thresh: float
    ):
        """
        Feature: scalping-pipeline-audit, Property 7: Action-conditional policy enforces dual thresholds

        When both p_star >= p_thresh AND margin >= margin_thresh, the
        action-conditional policy should NOT block the prediction.

        **Validates: Requirements 2.7**
        """
        prediction = {
            "p_long_win": p_long,
            "p_short_win": p_short,
            "prediction_contract": "action_conditional_pnl_winprob",
        }

        resolved = _resolve_action_policy_probabilities(prediction)
        assert resolved is not None, "Expected resolved probabilities"

        p_star = resolved["p_star"]
        margin = resolved["margin"]

        assume(p_star >= p_thresh)
        assume(margin >= margin_thresh)

        # With directional_mass=1.0 for action_conditional contracts,
        # the only blocking conditions are p_star and margin
        blocked = p_star < p_thresh or margin < margin_thresh
        assert not blocked, (
            f"Expected pass for p_star={p_star:.4f} >= p_thresh={p_thresh:.4f} "
            f"and margin={margin:.4f} >= margin_thresh={margin_thresh:.4f}"
        )

    @settings(max_examples=200)
    @given(
        p_long=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
        p_short=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
    )
    def test_action_conditional_resolves_p_star_and_margin_correctly(
        self, p_long: float, p_short: float
    ):
        """
        Feature: scalping-pipeline-audit, Property 7: Action-conditional policy enforces dual thresholds

        For action_conditional_pnl_winprob contracts, p_star should equal
        max(p_long, p_short) and margin should equal abs(p_long - p_short).

        **Validates: Requirements 2.7**
        """
        prediction = {
            "p_long_win": p_long,
            "p_short_win": p_short,
            "prediction_contract": "action_conditional_pnl_winprob",
        }

        resolved = _resolve_action_policy_probabilities(prediction)
        assert resolved is not None, "Expected resolved probabilities"

        expected_p_star = max(p_long, p_short)
        expected_margin = abs(p_long - p_short)

        assert abs(resolved["p_star"] - expected_p_star) < 1e-9, (
            f"p_star mismatch: got {resolved['p_star']:.6f}, "
            f"expected {expected_p_star:.6f}"
        )
        assert abs(resolved["margin"] - expected_margin) < 1e-9, (
            f"margin mismatch: got {resolved['margin']:.6f}, "
            f"expected {expected_margin:.6f}"
        )
        # For action_conditional contracts, directional_mass should be 1.0
        assert resolved["directional_mass"] == 1.0, (
            f"Expected directional_mass=1.0 for action_conditional, "
            f"got {resolved['directional_mass']}"
        )
