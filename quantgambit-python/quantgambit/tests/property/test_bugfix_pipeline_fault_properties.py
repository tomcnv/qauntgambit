"""
Property-based exploration tests for prediction pipeline fault conditions (Bugs 5–8).

Feature: scalping-config-fixes

These tests encode the EXPECTED behavior for each prediction pipeline gate.
On UNFIXED code they are expected to FAIL — failure confirms the bugs exist.
After the pipeline fixes are applied, these same tests should PASS.

**Validates: Requirements 1.5, 1.6, 1.7, 1.8**
"""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import fields
from pathlib import Path
from typing import Optional

import pytest
from hypothesis import given, settings, note, assume
from hypothesis import strategies as st

# ---------------------------------------------------------------------------
# Load .env from project root so tests see the actual config values
# ---------------------------------------------------------------------------
try:
    from dotenv import load_dotenv

    _env_path = Path(__file__).resolve().parents[4] / ".env"
    if _env_path.exists():
        load_dotenv(_env_path, override=True)
except ImportError:
    pass

# ---------------------------------------------------------------------------
# Imports from the codebase under test
# ---------------------------------------------------------------------------
from quantgambit.signals.prediction_providers import _abstain_reason
from quantgambit.signals.stages.model_direction_alignment import (
    ModelDirectionAlignmentConfig,
    ModelDirectionAlignmentStage,
)
from quantgambit.signals.pipeline import StageContext, StageResult
from quantgambit.execution.manager import PositionSnapshot


# ---------------------------------------------------------------------------
# Model registry path for f1 scores
# ---------------------------------------------------------------------------
_REGISTRY_PATH = Path(__file__).resolve().parents[3] / "models" / "registry" / "latest.json"


def _load_f1_down() -> Optional[float]:
    """Read f1_down from the model registry."""
    if _REGISTRY_PATH.exists():
        data = json.loads(_REGISTRY_PATH.read_text())
        return data.get("metrics", {}).get("f1_down")
    return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run_async(coro):
    """Run an async coroutine synchronously for testing."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _make_stage_context(
    symbol: str = "BTCUSDT",
    signal_side: str = "short",
    prediction: Optional[dict] = None,
) -> StageContext:
    """Build a StageContext with the given signal and prediction data."""
    return StageContext(
        symbol=symbol,
        data={"prediction": prediction or {}},
        signal={"side": signal_side, "position_effect": "open"},
    )


# ═══════════════════════════════════════════════════════════════
# Property 3 (Fault Condition): Flat Predictions Rejected
# Bug 5 — Flat predictions must be rejected by _abstain_reason()
# ═══════════════════════════════════════════════════════════════


class TestFlatPredictionFaultCondition:
    """Bug 5 — Flat predictions must be rejected.

    Current code: ``_abstain_reason()`` has no concept of predicted class.
    It only checks confidence, margin, and entropy — so flat predictions
    with sufficient confidence/margin pass through and derive a directional
    ``model_side``.

    Expected: ``_abstain_reason()`` returns ``"onnx_flat_class"`` when
    ``direction == "flat"``.

    **Validates: Requirements 1.5**
    """

    @settings(max_examples=50)
    @given(
        p_down=st.floats(min_value=0.01, max_value=0.99),
        p_up=st.floats(min_value=0.01, max_value=0.99),
        p_flat=st.floats(min_value=0.01, max_value=0.99),
    )
    def test_flat_prediction_rejected(
        self, p_down: float, p_up: float, p_flat: float
    ):
        """_abstain_reason() must return 'onnx_flat_class' for direction='flat'.

        We generate varying probability vectors where the predicted class
        is "flat" and assert the abstain logic catches it.
        """
        # Normalize to a valid probability distribution
        total = p_down + p_up + p_flat
        p_down_n = p_down / total
        p_up_n = p_up / total
        p_flat_n = p_flat / total

        # For a "flat" prediction, p_flat should be the argmax
        # (but the bug exists regardless — even when p_flat isn't argmax
        # but direction is set to "flat" by the model)
        direction = "flat"

        # Use generous thresholds so confidence/margin/entropy don't trigger
        confidence = max(p_down_n, p_up_n, p_flat_n)
        margin = abs(p_down_n - p_up_n)
        entropy = 0.5  # moderate entropy

        note(f"direction={direction}, p_down={p_down_n:.3f}, p_up={p_up_n:.3f}, p_flat={p_flat_n:.3f}")
        note(f"confidence={confidence:.3f}, margin={margin:.3f}")

        # Call _abstain_reason with direction parameter
        # On unfixed code, _abstain_reason doesn't accept direction and
        # won't return "onnx_flat_class"
        reason = _abstain_reason(
            confidence=confidence,
            margin=margin,
            entropy=entropy,
            min_confidence=0.0,  # Don't trigger confidence rejection
            min_margin=0.0,      # Don't trigger margin rejection
            max_entropy=2.0,     # Don't trigger entropy rejection
            direction=direction,
            reject_flat_class=True,
        )

        assert reason == "onnx_flat_class", (
            f"Expected _abstain_reason to return 'onnx_flat_class' for "
            f"direction='flat', but got: {reason!r}"
        )


# ═══════════════════════════════════════════════════════════════
# Property 4 (Fault Condition): Side Mismatch Unconditionally Rejected
# Bug 6 — Side mismatches must be rejected regardless of confidence/margin
# ═══════════════════════════════════════════════════════════════


class TestSideMismatchFaultCondition:
    """Bug 6 — Side mismatches must be rejected unconditionally.

    Current code: ``ModelDirectionAlignmentStage.run()`` returns
    ``StageResult.CONTINUE`` when confidence < 0.60 or margin < 0.02,
    even when ``model_side != signal_side``.

    Expected: ``StageResult.REJECT`` whenever model_side != signal_side,
    regardless of confidence or margin.

    **Validates: Requirements 1.6**
    """

    @settings(max_examples=50)
    @given(
        data=st.data(),
    )
    def test_side_mismatch_rejected_low_confidence(self, data: st.DataObject):
        """Mismatched sides with confidence < 0.60 must be REJECTED.

        On unfixed code, the stage returns CONTINUE (bypass) when
        confidence is below the threshold.
        """
        # Generate mismatched side pairs
        model_side = data.draw(st.sampled_from(["long", "short"]))
        signal_side = "short" if model_side == "long" else "long"

        # Generate confidence below the enforcement threshold (0.60)
        confidence = data.draw(st.floats(min_value=0.30, max_value=0.59))
        # Margin can be anything
        margin = data.draw(st.floats(min_value=0.001, max_value=0.10))

        # Build prediction with p_long_win / p_short_win that produce the model_side
        if model_side == "long":
            p_long_win = confidence
            p_short_win = confidence - margin
        else:
            p_short_win = confidence
            p_long_win = confidence - margin

        prediction = {
            "p_long_win": p_long_win,
            "p_short_win": p_short_win,
            "confidence": confidence,
        }

        note(f"model_side={model_side}, signal_side={signal_side}")
        note(f"confidence={confidence:.3f}, margin={margin:.3f}")

        # Construct stage with default config (thresholds: confidence=0.60, margin=0.02)
        config = ModelDirectionAlignmentConfig(
            enabled=True,
            min_confidence_to_enforce=0.60,
            min_margin_to_enforce=0.02,
            allow_when_prediction_missing=True,
        )
        stage = ModelDirectionAlignmentStage(config=config)
        # Override config to avoid env var interference
        stage.config = config

        ctx = _make_stage_context(
            signal_side=signal_side,
            prediction=prediction,
        )

        result = _run_async(stage.run(ctx))

        assert result == StageResult.REJECT, (
            f"Expected REJECT for model_side={model_side} vs signal_side={signal_side} "
            f"(confidence={confidence:.3f}, margin={margin:.3f}), but got {result}"
        )

    @settings(max_examples=50)
    @given(
        data=st.data(),
    )
    def test_side_mismatch_rejected_low_margin(self, data: st.DataObject):
        """Mismatched sides with margin < 0.02 must be REJECTED.

        On unfixed code, the stage returns CONTINUE (bypass) when
        margin is below the threshold.
        """
        model_side = data.draw(st.sampled_from(["long", "short"]))
        signal_side = "short" if model_side == "long" else "long"

        # Confidence above threshold but margin below threshold
        confidence = data.draw(st.floats(min_value=0.60, max_value=0.95))
        margin = data.draw(st.floats(min_value=0.001, max_value=0.019))

        if model_side == "long":
            p_long_win = confidence
            p_short_win = confidence - margin
        else:
            p_short_win = confidence
            p_long_win = confidence - margin

        prediction = {
            "p_long_win": p_long_win,
            "p_short_win": p_short_win,
            "confidence": confidence,
        }

        note(f"model_side={model_side}, signal_side={signal_side}")
        note(f"confidence={confidence:.3f}, margin={margin:.3f}")

        config = ModelDirectionAlignmentConfig(
            enabled=True,
            min_confidence_to_enforce=0.60,
            min_margin_to_enforce=0.02,
            allow_when_prediction_missing=True,
        )
        stage = ModelDirectionAlignmentStage(config=config)
        stage.config = config

        ctx = _make_stage_context(
            signal_side=signal_side,
            prediction=prediction,
        )

        result = _run_async(stage.run(ctx))

        assert result == StageResult.REJECT, (
            f"Expected REJECT for model_side={model_side} vs signal_side={signal_side} "
            f"(confidence={confidence:.3f}, margin={margin:.3f}), but got {result}"
        )


# ═══════════════════════════════════════════════════════════════
# Property 5 (Fault Condition): Unreliable Short Class Blocked
# Bug 7 — Shorts with f1_down < 0.40 must be blocked
# ═══════════════════════════════════════════════════════════════


class TestUnreliableShortFaultCondition:
    """Bug 7 — Short entries with unreliable down class must be blocked.

    Current code: No f1 threshold check exists. The system executes short
    trades based on "down" class predictions despite f1_down=0.23.

    Expected: When ``model_side="short"`` and ``f1_down < 0.40``, the
    prediction is blocked with reason ``"onnx_unreliable_down_class"``.

    **Validates: Requirements 1.7**
    """

    @settings(max_examples=50)
    @given(
        f1_down=st.floats(min_value=0.05, max_value=0.39),
    )
    def test_unreliable_short_blocked(self, f1_down: float):
        """Shorts with f1_down < 0.40 must be blocked.

        On unfixed code, no f1 gate exists so the prediction flows through
        without checking model reliability metrics.
        """
        # Read actual f1_down from registry to confirm the bug exists
        actual_f1_down = _load_f1_down()
        note(f"actual f1_down from registry: {actual_f1_down}")
        note(f"generated f1_down: {f1_down:.3f}")

        min_f1_threshold = 0.40

        # The bug: _abstain_reason has no f1 check at all.
        # We test by calling _abstain_reason with a "down" direction prediction
        # and checking if it returns the unreliable reason.
        # On unfixed code, _abstain_reason doesn't accept f1_down or direction.
        reason = _abstain_reason(
            confidence=0.80,       # High confidence — shouldn't trigger rejection
            margin=0.30,           # High margin — shouldn't trigger rejection
            entropy=0.50,          # Low entropy — shouldn't trigger rejection
            min_confidence=0.0,
            min_margin=0.0,
            max_entropy=2.0,
            direction="down",
            f1_down=f1_down,
            min_f1_down=min_f1_threshold,
        )

        assert reason == "onnx_unreliable_down_class", (
            f"Expected _abstain_reason to return 'onnx_unreliable_down_class' "
            f"for direction='down' with f1_down={f1_down:.3f} < {min_f1_threshold}, "
            f"but got: {reason!r}"
        )

    @settings(max_examples=1)
    @given(data=st.data())
    def test_actual_registry_f1_down_below_threshold(self, data: st.DataObject):
        """Confirm the actual model registry has f1_down < 0.40.

        This is a concrete check that the bug condition exists in the
        current model registry.
        """
        actual_f1_down = _load_f1_down()
        note(f"actual f1_down from registry: {actual_f1_down}")

        assert actual_f1_down is not None, "f1_down not found in model registry"
        assert actual_f1_down < 0.40, (
            f"Expected f1_down < 0.40 (bug condition), but got {actual_f1_down:.3f}"
        )


# ═══════════════════════════════════════════════════════════════
# Property 6 (Fault Condition): Position Closed Events Include Prediction Context
# Bug 8 — PositionSnapshot must have model_side, p_up, p_down, p_flat fields
# ═══════════════════════════════════════════════════════════════


class TestMissingPredictionContextFaultCondition:
    """Bug 8 — PositionSnapshot must include prediction context fields.

    Current code: ``PositionSnapshot`` has ``prediction_confidence``,
    ``prediction_direction``, ``prediction_source``, ``entry_p_hat``,
    ``strategy_id`` — but NOT ``model_side``, ``p_up``, ``p_down``, ``p_flat``.

    Expected: ``PositionSnapshot`` includes all four new fields.

    **Validates: Requirements 1.8**
    """

    REQUIRED_NEW_FIELDS = ["model_side", "p_up", "p_down", "p_flat"]

    @settings(max_examples=1)
    @given(data=st.data())
    def test_position_snapshot_has_prediction_context_fields(
        self, data: st.DataObject
    ):
        """PositionSnapshot must have model_side, p_up, p_down, p_flat fields.

        On unfixed code, these fields don't exist on the dataclass.
        """
        field_names = {f.name for f in fields(PositionSnapshot)}
        note(f"PositionSnapshot fields: {sorted(field_names)}")

        missing = [f for f in self.REQUIRED_NEW_FIELDS if f not in field_names]

        assert not missing, (
            f"PositionSnapshot is missing prediction context fields: {missing}. "
            f"Available fields: {sorted(field_names)}"
        )

    @settings(max_examples=1)
    @given(data=st.data())
    def test_position_snapshot_new_fields_are_optional(
        self, data: st.DataObject
    ):
        """New prediction context fields must be Optional with None default.

        This ensures backward compatibility — existing code that creates
        PositionSnapshot without these fields continues to work.
        """
        field_names = {f.name for f in fields(PositionSnapshot)}

        for field_name in self.REQUIRED_NEW_FIELDS:
            if field_name not in field_names:
                pytest.skip(
                    f"Field '{field_name}' not yet on PositionSnapshot "
                    f"(Bug 8 not fixed)"
                )

        # If fields exist, verify they default to None
        snapshot = PositionSnapshot(symbol="BTCUSDT", side="long", size=0.01)
        for field_name in self.REQUIRED_NEW_FIELDS:
            value = getattr(snapshot, field_name)
            assert value is None, (
                f"Expected {field_name} to default to None, got {value!r}"
            )
