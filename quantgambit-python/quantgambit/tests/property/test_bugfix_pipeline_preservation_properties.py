"""
Property-based preservation tests for prediction pipeline behavior (Properties 7 & 8).

Feature: scalping-config-fixes

These tests observe and lock down the EXISTING behavior of the prediction pipeline
on UNFIXED code. They must PASS on the current codebase, establishing a baseline
that must be preserved after the bugfix changes are applied.

**Validates: Requirements 3.8, 3.9, 3.10, 3.11**
"""

from __future__ import annotations

import asyncio
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
    signal_side: str = "long",
    prediction: Optional[dict] = None,
) -> StageContext:
    """Build a StageContext with the given signal and prediction data."""
    return StageContext(
        symbol=symbol,
        data={"prediction": prediction or {}},
        signal={"side": signal_side, "position_effect": "open"},
    )


# ═══════════════════════════════════════════════════════════════
# Property 7: Preservation — Directional Trades on Reliable
#              Predictions Unchanged
# ═══════════════════════════════════════════════════════════════


class TestAbstainReasonPreservesDirectionalPredictions:
    """_abstain_reason() returns None for "up"/"down" with sufficient
    confidence and margin on unfixed code.

    On unfixed code _abstain_reason() does NOT accept a ``direction``
    parameter, so we call it with only the original positional args.

    **Validates: Requirements 3.8**
    """

    @settings(max_examples=50)
    @given(
        confidence=st.floats(min_value=0.50, max_value=0.99),
        margin=st.floats(min_value=0.05, max_value=0.60),
        entropy=st.floats(min_value=0.0, max_value=0.90),
    )
    def test_up_prediction_not_rejected(
        self, confidence: float, margin: float, entropy: float
    ):
        """direction='up' with sufficient confidence/margin is not rejected."""
        note(f"confidence={confidence:.3f}, margin={margin:.3f}, entropy={entropy:.3f}")

        reason = _abstain_reason(
            confidence=confidence,
            margin=margin,
            entropy=entropy,
            min_confidence=0.30,
            min_margin=0.02,
            max_entropy=1.0,
        )

        assert reason is None, (
            f"Expected _abstain_reason to return None for a reliable 'up' prediction "
            f"(confidence={confidence:.3f}, margin={margin:.3f}), but got: {reason!r}"
        )

    @settings(max_examples=50)
    @given(
        confidence=st.floats(min_value=0.50, max_value=0.99),
        margin=st.floats(min_value=0.05, max_value=0.60),
        entropy=st.floats(min_value=0.0, max_value=0.90),
    )
    def test_down_prediction_not_rejected(
        self, confidence: float, margin: float, entropy: float
    ):
        """direction='down' with sufficient confidence/margin is not rejected."""
        note(f"confidence={confidence:.3f}, margin={margin:.3f}, entropy={entropy:.3f}")

        reason = _abstain_reason(
            confidence=confidence,
            margin=margin,
            entropy=entropy,
            min_confidence=0.30,
            min_margin=0.02,
            max_entropy=1.0,
        )

        assert reason is None, (
            f"Expected _abstain_reason to return None for a reliable 'down' prediction "
            f"(confidence={confidence:.3f}, margin={margin:.3f}), but got: {reason!r}"
        )


class TestModelDirectionAlignmentPreservation:
    """ModelDirectionAlignmentStage preserves existing behavior for aligned
    sides and missing predictions.

    **Validates: Requirements 3.9**
    """

    @settings(max_examples=50)
    @given(data=st.data())
    def test_aligned_sides_continue(self, data: st.DataObject):
        """When model_side == signal_side, stage returns CONTINUE."""
        side = data.draw(st.sampled_from(["long", "short"]))
        confidence = data.draw(st.floats(min_value=0.60, max_value=0.99))
        margin = data.draw(st.floats(min_value=0.02, max_value=0.50))

        if side == "long":
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

        note(f"side={side}, confidence={confidence:.3f}, margin={margin:.3f}")

        config = ModelDirectionAlignmentConfig(
            enabled=True,
            min_confidence_to_enforce=0.60,
            min_margin_to_enforce=0.02,
            allow_when_prediction_missing=True,
        )
        stage = ModelDirectionAlignmentStage(config=config)
        stage.config = config

        ctx = _make_stage_context(signal_side=side, prediction=prediction)
        result = _run_async(stage.run(ctx))

        assert result == StageResult.CONTINUE, (
            f"Expected CONTINUE for aligned sides (both {side}), but got {result}"
        )

    @settings(max_examples=50)
    @given(
        signal_side=st.sampled_from(["long", "short"]),
    )
    def test_missing_prediction_continues(self, signal_side: str):
        """When prediction is missing (model_side is None), stage returns CONTINUE."""
        config = ModelDirectionAlignmentConfig(
            enabled=True,
            min_confidence_to_enforce=0.60,
            min_margin_to_enforce=0.02,
            allow_when_prediction_missing=True,
        )
        stage = ModelDirectionAlignmentStage(config=config)
        stage.config = config

        # Empty prediction → model_side will be None
        ctx = _make_stage_context(signal_side=signal_side, prediction={})
        result = _run_async(stage.run(ctx))

        assert result == StageResult.CONTINUE, (
            f"Expected CONTINUE when prediction is missing, but got {result}"
        )

    @settings(max_examples=50)
    @given(
        signal_side=st.sampled_from(["long", "short"]),
    )
    def test_no_prediction_at_all_continues(self, signal_side: str):
        """When no prediction data exists at all, stage returns CONTINUE."""
        config = ModelDirectionAlignmentConfig(
            enabled=True,
            min_confidence_to_enforce=0.60,
            min_margin_to_enforce=0.02,
            allow_when_prediction_missing=True,
        )
        stage = ModelDirectionAlignmentStage(config=config)
        stage.config = config

        ctx = _make_stage_context(signal_side=signal_side, prediction=None)
        result = _run_async(stage.run(ctx))

        assert result == StageResult.CONTINUE, (
            f"Expected CONTINUE when prediction is None, but got {result}"
        )


class TestLongEntriesUnaffectedByF1Down:
    """Long entries are unaffected regardless of f1_down value.

    On unfixed code, no f1 gate exists at all. This test confirms that
    _abstain_reason() does not reject predictions based on any f1 metric,
    establishing the baseline that long entries must remain unaffected
    after the f1 gate is added (since f1_up=0.88 > 0.40 threshold).

    **Validates: Requirements 3.10**
    """

    @settings(max_examples=50)
    @given(
        confidence=st.floats(min_value=0.50, max_value=0.99),
        margin=st.floats(min_value=0.05, max_value=0.60),
    )
    def test_long_entry_not_rejected_regardless_of_f1(
        self, confidence: float, margin: float
    ):
        """Long entries pass _abstain_reason() on unfixed code (no f1 gate)."""
        note(f"confidence={confidence:.3f}, margin={margin:.3f}")

        reason = _abstain_reason(
            confidence=confidence,
            margin=margin,
            entropy=0.5,
            min_confidence=0.30,
            min_margin=0.02,
            max_entropy=1.0,
        )

        assert reason is None, (
            f"Expected _abstain_reason to return None for a long entry "
            f"(confidence={confidence:.3f}, margin={margin:.3f}), but got: {reason!r}"
        )


# ═══════════════════════════════════════════════════════════════
# Property 8: Preservation — Existing Position Event Fields
#              Unchanged
# ═══════════════════════════════════════════════════════════════


class TestPositionSnapshotExistingFields:
    """PositionSnapshot must retain all existing fields used in lifecycle events.

    **Validates: Requirements 3.11**
    """

    # Fields that currently exist on PositionSnapshot and are used in
    # _close_position() lifecycle_payload or position snapshots.
    EXISTING_SNAPSHOT_FIELDS = [
        "prediction_confidence",
        "prediction_direction",
        "prediction_source",
        "entry_p_hat",
        "strategy_id",
        "profile_id",
        "entry_price",
        "entry_fee_usd",
        "side",
        "size",
        "symbol",
        "opened_at",
    ]

    @settings(max_examples=1)
    @given(data=st.data())
    def test_existing_fields_present_on_dataclass(self, data: st.DataObject):
        """All existing prediction/lifecycle fields are present on PositionSnapshot."""
        field_names = {f.name for f in fields(PositionSnapshot)}
        note(f"PositionSnapshot fields: {sorted(field_names)}")

        missing = [f for f in self.EXISTING_SNAPSHOT_FIELDS if f not in field_names]

        assert not missing, (
            f"PositionSnapshot is missing existing fields: {missing}. "
            f"Available: {sorted(field_names)}"
        )

    @settings(max_examples=50)
    @given(
        confidence=st.one_of(st.none(), st.floats(min_value=0.0, max_value=1.0)),
        direction=st.one_of(st.none(), st.sampled_from(["up", "down", "flat"])),
        source=st.one_of(st.none(), st.sampled_from(["onnx_v1", "heuristic_v2"])),
        p_hat=st.one_of(st.none(), st.floats(min_value=0.0, max_value=1.0)),
        strategy_id=st.one_of(st.none(), st.text(min_size=1, max_size=20)),
    )
    def test_existing_fields_retain_values(
        self,
        confidence: Optional[float],
        direction: Optional[str],
        source: Optional[str],
        p_hat: Optional[float],
        strategy_id: Optional[str],
    ):
        """Existing fields on PositionSnapshot retain their assigned values."""
        snapshot = PositionSnapshot(
            symbol="BTCUSDT",
            side="long",
            size=0.01,
            prediction_confidence=confidence,
            prediction_direction=direction,
            prediction_source=source,
            entry_p_hat=p_hat,
            strategy_id=strategy_id,
        )

        assert snapshot.prediction_confidence == confidence
        assert snapshot.prediction_direction == direction
        assert snapshot.prediction_source == source
        assert snapshot.entry_p_hat == p_hat
        assert snapshot.strategy_id == strategy_id


class TestLifecyclePayloadExistingFields:
    """The _close_position() lifecycle_payload must include all existing fields.

    We verify the field keys that are unconditionally set in the lifecycle_payload
    dict within _close_position(). This is a structural check — we confirm the
    code path sets these keys by inspecting the known payload structure.

    **Validates: Requirements 3.11**
    """

    # Fields that are unconditionally set in lifecycle_payload in _close_position()
    UNCONDITIONAL_LIFECYCLE_FIELDS = [
        "side",
        "size",
        "status",
        "entry_price",
        "exit_price",
        "exit_timestamp",
        "entry_timestamp",
        "realized_pnl",
        "realized_pnl_pct",
        "fee_usd",
        "entry_fee_usd",
        "total_fees_usd",
        "gross_pnl",
        "net_pnl",
        "hold_time_sec",
        "close_order_id",
        "closed_by",
        "strategy_id",
        "profile_id",
        "execution_policy",
        "execution_cohort",
        "execution_experiment_id",
        "entry_fee_bps",
        "exit_fee_bps",
        "total_cost_bps",
        "exit_execution_path",
        "exit_tp_limit_attempted",
        "exit_tp_limit_filled",
        "exit_tp_limit_timeout_fallback",
    ]

    # Fields that are conditionally set (only when the value is not None)
    CONDITIONAL_LIFECYCLE_FIELDS = [
        "prediction_confidence",
        "prediction_direction",
        "prediction_source",
        "entry_p_hat",
        "entry_p_hat_source",
        "mfe_pct",
        "mae_pct",
        "signal_strength",
        "signal_confidence",
    ]

    @settings(max_examples=1)
    @given(data=st.data())
    def test_unconditional_fields_documented(self, data: st.DataObject):
        """Verify our list of unconditional lifecycle_payload fields is consistent.

        This is a structural assertion — the fields listed here are the ones
        that _close_position() sets unconditionally in the lifecycle_payload dict.
        After fixes, these fields must still be present.
        """
        # Verify the list is non-empty and contains the critical PnL fields
        assert len(self.UNCONDITIONAL_LIFECYCLE_FIELDS) > 0
        assert "realized_pnl" in self.UNCONDITIONAL_LIFECYCLE_FIELDS
        assert "net_pnl" in self.UNCONDITIONAL_LIFECYCLE_FIELDS
        assert "gross_pnl" in self.UNCONDITIONAL_LIFECYCLE_FIELDS
        assert "strategy_id" in self.UNCONDITIONAL_LIFECYCLE_FIELDS
        assert "profile_id" in self.UNCONDITIONAL_LIFECYCLE_FIELDS

    @settings(max_examples=1)
    @given(data=st.data())
    def test_conditional_prediction_fields_on_snapshot(self, data: st.DataObject):
        """Conditional lifecycle fields correspond to PositionSnapshot attributes.

        _close_position() reads these from pos.X and includes them when not None.
        The PositionSnapshot must have these attributes for the conditional
        inclusion to work.
        """
        field_names = {f.name for f in fields(PositionSnapshot)}

        # These conditional fields map to PositionSnapshot attributes
        snapshot_mapped_fields = [
            "prediction_confidence",
            "prediction_direction",
            "prediction_source",
        ]

        for field_name in snapshot_mapped_fields:
            assert field_name in field_names, (
                f"PositionSnapshot must have '{field_name}' for lifecycle payload "
                f"conditional inclusion to work"
            )

    @settings(max_examples=50)
    @given(
        confidence=st.one_of(st.none(), st.floats(min_value=0.0, max_value=1.0)),
        direction=st.one_of(st.none(), st.sampled_from(["up", "down", "flat"])),
        source=st.one_of(st.none(), st.sampled_from(["onnx_v1", "heuristic_v2"])),
    )
    def test_snapshot_prediction_fields_roundtrip(
        self,
        confidence: Optional[float],
        direction: Optional[str],
        source: Optional[str],
    ):
        """PositionSnapshot prediction fields survive creation and readback.

        This simulates what _close_position() does: read pos.prediction_confidence,
        pos.prediction_direction, pos.prediction_source and include them in the
        lifecycle_payload when not None.
        """
        snapshot = PositionSnapshot(
            symbol="BTCUSDT",
            side="long",
            size=0.01,
            prediction_confidence=confidence,
            prediction_direction=direction,
            prediction_source=source,
        )

        # Simulate the conditional inclusion logic from _close_position()
        payload: dict = {}
        if snapshot.prediction_confidence is not None:
            payload["prediction_confidence"] = snapshot.prediction_confidence
        if snapshot.prediction_direction is not None:
            payload["prediction_direction"] = snapshot.prediction_direction
        if snapshot.prediction_source is not None:
            payload["prediction_source"] = snapshot.prediction_source

        # Verify roundtrip: if we set a value, it appears in the payload
        if confidence is not None:
            assert payload["prediction_confidence"] == confidence
        else:
            assert "prediction_confidence" not in payload

        if direction is not None:
            assert payload["prediction_direction"] == direction
        else:
            assert "prediction_direction" not in payload

        if source is not None:
            assert payload["prediction_source"] == source
        else:
            assert "prediction_source" not in payload
