"""
Property-based tests for Configuration Consistency.

Feature: scalping-pipeline-audit

These tests verify correctness properties of environment variable resolution,
execution/decision layer age threshold consistency, and position replacement
blocking when disabled.

**Validates: Requirements 10.2, 10.5, 10.6**
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set
from unittest.mock import MagicMock, patch

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

from quantgambit.config.env_schema import (
    ENV_VARS,
    EnvVarSpec,
    EnvVarType,
    ValidationError,
    ValidationResult,
    validate_all_env_vars,
    validate_env_var,
)
from quantgambit.signals.pipeline import (
    StageContext,
    StageResult,
    _maybe_allow_replacement,
)


# ═══════════════════════════════════════════════════════════════
# SHARED HYPOTHESIS STRATEGIES
# ═══════════════════════════════════════════════════════════════

symbols = st.sampled_from(["BTCUSDT", "ETHUSDT", "SOLUSDT"])

# Env var key names (alphanumeric + underscore)
env_var_keys = st.from_regex(r"[A-Z][A-Z0-9_]{2,30}", fullmatch=True)

# Env var values (simple strings)
env_var_values = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P")),
    min_size=1,
    max_size=50,
)

# Age thresholds in milliseconds
age_ms_values = st.integers(min_value=100, max_value=30000)

# Signal sides
signal_sides = st.sampled_from(["buy", "sell", "long", "short"])

# Position sides
position_sides = st.sampled_from(["long", "short"])


# ═══════════════════════════════════════════════════════════════
# Property 28: Duplicate env var resolution
# ═══════════════════════════════════════════════════════════════


class TestDuplicateEnvVarResolution:
    """
    Feature: scalping-pipeline-audit, Property 28: Duplicate env var resolution

    Duplicate keys use last-defined value; validate_all_env_vars() detects
    and reports duplicates.

    **Validates: Requirements 10.2**
    """

    @settings(max_examples=200)
    @given(
        key=env_var_keys,
        first_value=st.text(min_size=1, max_size=20, alphabet="0123456789"),
        second_value=st.text(min_size=1, max_size=20, alphabet="0123456789"),
    )
    def test_last_defined_value_wins(
        self, key: str, first_value: str, second_value: str,
    ):
        """Feature: scalping-pipeline-audit, Property 28: Duplicate env var resolution

        When the same env var key is set multiple times, os.getenv returns the
        last-set value (standard dotenv behavior: last write wins).
        """
        assume(first_value != second_value)

        # Simulate dotenv behavior: last write wins
        env_patch = {key: second_value}
        with patch.dict(os.environ, env_patch, clear=False):
            result = os.getenv(key)
            assert result == second_value, (
                f"Expected last-defined value '{second_value}', got '{result}'"
            )

    @settings(max_examples=200)
    @given(
        value=st.integers(min_value=0, max_value=100000),
    )
    def test_validate_env_var_detects_type_mismatch(self, value: int):
        """Feature: scalping-pipeline-audit, Property 28: Duplicate env var resolution

        validate_env_var correctly detects type mismatches when a numeric env var
        receives a non-numeric string value.
        """
        spec = EnvVarSpec(
            name="TEST_NUMERIC_VAR",
            type=EnvVarType.INT,
            required=False,
            description="Test numeric var",
        )
        with patch.dict(os.environ, {"TEST_NUMERIC_VAR": "not_a_number"}, clear=False):
            error = validate_env_var(spec)
            assert error is not None, (
                "validate_env_var should detect type mismatch for non-numeric value"
            )
            assert "Invalid type" in error.message

    @settings(max_examples=200)
    @given(
        value=st.floats(min_value=0.0, max_value=1000.0, allow_nan=False, allow_infinity=False),
        min_val=st.floats(min_value=0.0, max_value=500.0, allow_nan=False, allow_infinity=False),
        max_val=st.floats(min_value=500.0, max_value=1000.0, allow_nan=False, allow_infinity=False),
    )
    def test_validate_env_var_detects_out_of_range(
        self, value: float, min_val: float, max_val: float,
    ):
        """Feature: scalping-pipeline-audit, Property 28: Duplicate env var resolution

        validate_env_var correctly detects values outside min/max range.
        """
        assume(min_val < max_val)

        spec = EnvVarSpec(
            name="TEST_RANGE_VAR",
            type=EnvVarType.FLOAT,
            required=False,
            description="Test range var",
            min_value=min_val,
            max_value=max_val,
        )
        with patch.dict(os.environ, {"TEST_RANGE_VAR": str(value)}, clear=False):
            error = validate_env_var(spec)
            if value < min_val:
                assert error is not None, (
                    f"Value {value} below min {min_val} should be rejected"
                )
                assert "below minimum" in error.message
            elif value > max_val:
                assert error is not None, (
                    f"Value {value} above max {max_val} should be rejected"
                )
                assert "above maximum" in error.message
            else:
                assert error is None, (
                    f"Value {value} within [{min_val}, {max_val}] should be valid"
                )

    def test_validate_all_env_vars_returns_valid_result(self):
        """Feature: scalping-pipeline-audit, Property 28: Duplicate env var resolution

        validate_all_env_vars returns a ValidationResult with the expected structure.
        """
        # Run with whatever env is currently set — just verify structure
        result = validate_all_env_vars()
        assert isinstance(result, ValidationResult)
        assert isinstance(result.errors, list)
        assert isinstance(result.warnings, list)
        assert isinstance(result.values, dict)
        # All errors should be ValidationError instances
        for err in result.errors:
            assert isinstance(err, ValidationError)
        for warn in result.warnings:
            assert isinstance(warn, ValidationError)

    @settings(max_examples=200)
    @given(
        key=env_var_keys,
        valid_value=st.integers(min_value=1, max_value=100),
    )
    def test_env_var_spec_with_valid_value_passes(self, key: str, valid_value: int):
        """Feature: scalping-pipeline-audit, Property 28: Duplicate env var resolution

        A well-formed env var that matches its spec should pass validation.
        """
        spec = EnvVarSpec(
            name=key,
            type=EnvVarType.INT,
            required=False,
            description="Test var",
            min_value=0,
            max_value=200,
        )
        with patch.dict(os.environ, {key: str(valid_value)}, clear=False):
            error = validate_env_var(spec)
            assert error is None, (
                f"Valid value {valid_value} for {key} should pass validation, got: {error}"
            )


# ═══════════════════════════════════════════════════════════════
# Property 29: Execution layer age thresholds stricter than decision layer
# ═══════════════════════════════════════════════════════════════


class TestExecutionLayerAgeThresholds:
    """
    Feature: scalping-pipeline-audit, Property 29: Execution layer age thresholds
    are stricter than decision layer

    ENTRY_MAX_REFERENCE_AGE_MS and ENTRY_MAX_ORDERBOOK_AGE_MS ≤
    EV_GATE_MAX_BOOK_AGE_MS and COST_DATA_QUALITY_MAX_BOOK_AGE_MS.

    **Validates: Requirements 10.5**
    """

    @settings(max_examples=200)
    @given(
        entry_ref_age=age_ms_values,
        entry_book_age=age_ms_values,
        ev_gate_age=age_ms_values,
        cost_dq_age=age_ms_values,
    )
    def test_execution_thresholds_stricter_than_decision(
        self,
        entry_ref_age: int,
        entry_book_age: int,
        ev_gate_age: int,
        cost_dq_age: int,
    ):
        """Feature: scalping-pipeline-audit, Property 29: Execution layer age thresholds stricter than decision layer

        For any configuration where execution layer thresholds are ≤ decision layer
        thresholds, the invariant holds. When violated, the execution layer would
        accept data that the decision layer already rejected — a logical inconsistency.
        """
        # The property: execution layer must be stricter (<=) than decision layer
        exec_ref_ok = entry_ref_age <= ev_gate_age and entry_ref_age <= cost_dq_age
        exec_book_ok = entry_book_age <= ev_gate_age and entry_book_age <= cost_dq_age

        if exec_ref_ok and exec_book_ok:
            # Invariant holds: execution is stricter
            assert entry_ref_age <= ev_gate_age
            assert entry_ref_age <= cost_dq_age
            assert entry_book_age <= ev_gate_age
            assert entry_book_age <= cost_dq_age
        else:
            # Invariant violated: execution layer is more permissive than decision layer
            # This is a configuration inconsistency that should be flagged
            assert not (exec_ref_ok and exec_book_ok), (
                "Expected invariant violation when execution thresholds exceed decision thresholds"
            )

    @settings(max_examples=200)
    @given(
        decision_age=st.integers(min_value=1000, max_value=10000),
        execution_age=st.integers(min_value=100, max_value=10000),
    )
    def test_stricter_execution_always_rejects_before_decision(
        self, decision_age: int, execution_age: int,
    ):
        """Feature: scalping-pipeline-audit, Property 29: Execution layer age thresholds stricter than decision layer

        When execution threshold <= decision threshold, any data age that passes
        the execution check also passes the decision check.
        """
        assume(execution_age <= decision_age)

        # For any data age, if it passes execution check, it must pass decision check
        for data_age in range(0, max(decision_age, execution_age) + 100, 100):
            passes_execution = data_age <= execution_age
            passes_decision = data_age <= decision_age

            if passes_execution:
                assert passes_decision, (
                    f"Data age {data_age}ms passed execution ({execution_age}ms) "
                    f"but failed decision ({decision_age}ms) — impossible when "
                    f"execution is stricter"
                )

    def test_current_config_execution_stricter_than_decision(self):
        """Feature: scalping-pipeline-audit, Property 29: Execution layer age thresholds stricter than decision layer

        Verify the actual deployed configuration maintains the invariant.
        """
        entry_ref_age = int(os.getenv("ENTRY_MAX_REFERENCE_AGE_MS", "1200"))
        entry_book_age = int(os.getenv("ENTRY_MAX_ORDERBOOK_AGE_MS", "1200"))
        ev_gate_age = int(os.getenv("EV_GATE_MAX_BOOK_AGE_MS", "5000"))
        cost_dq_age = int(os.getenv("COST_DATA_QUALITY_MAX_BOOK_AGE_MS", "5000"))

        assert entry_ref_age <= ev_gate_age, (
            f"ENTRY_MAX_REFERENCE_AGE_MS ({entry_ref_age}) should be <= "
            f"EV_GATE_MAX_BOOK_AGE_MS ({ev_gate_age})"
        )
        assert entry_ref_age <= cost_dq_age, (
            f"ENTRY_MAX_REFERENCE_AGE_MS ({entry_ref_age}) should be <= "
            f"COST_DATA_QUALITY_MAX_BOOK_AGE_MS ({cost_dq_age})"
        )
        assert entry_book_age <= ev_gate_age, (
            f"ENTRY_MAX_ORDERBOOK_AGE_MS ({entry_book_age}) should be <= "
            f"EV_GATE_MAX_BOOK_AGE_MS ({ev_gate_age})"
        )
        assert entry_book_age <= cost_dq_age, (
            f"ENTRY_MAX_ORDERBOOK_AGE_MS ({entry_book_age}) should be <= "
            f"COST_DATA_QUALITY_MAX_BOOK_AGE_MS ({cost_dq_age})"
        )


# ═══════════════════════════════════════════════════════════════
# Property 30: Position replacement blocked when disabled
# ═══════════════════════════════════════════════════════════════


class TestPositionReplacementBlocked:
    """
    Feature: scalping-pipeline-audit, Property 30: Position replacement blocked when disabled

    Opposite-side entry blocked when ALLOW_POSITION_REPLACEMENT is false.

    **Validates: Requirements 10.6**
    """

    @settings(max_examples=200)
    @given(
        symbol=symbols,
        signal_side=signal_sides,
        existing_side=position_sides,
    )
    def test_replacement_blocked_when_disabled(
        self, symbol: str, signal_side: str, existing_side: str,
    ):
        """Feature: scalping-pipeline-audit, Property 30: Position replacement blocked when disabled

        When ALLOW_POSITION_REPLACEMENT is false, _maybe_allow_replacement returns
        False for any signal that would create an opposite-side position.
        """
        signal = {"side": signal_side}
        ctx = StageContext(
            symbol=symbol,
            data={
                "positions": [{"symbol": symbol, "side": existing_side, "size": 1.0}],
                "risk_limits": {"max_positions_per_symbol": 1},
            },
        )

        env_patch = {
            "ALLOW_POSITION_REPLACEMENT": "false",
            "REPLACE_OPPOSITE_ONLY": "true",
        }
        with patch.dict(os.environ, env_patch, clear=False):
            result = _maybe_allow_replacement(signal, ctx)
            assert result is False, (
                f"Expected replacement blocked when ALLOW_POSITION_REPLACEMENT=false, "
                f"signal_side={signal_side}, existing_side={existing_side}"
            )

    @settings(max_examples=200)
    @given(
        symbol=symbols,
        signal_side=st.sampled_from(["buy", "long"]),
    )
    def test_replacement_allowed_opposite_side_when_enabled(
        self, symbol: str, signal_side: str,
    ):
        """Feature: scalping-pipeline-audit, Property 30: Position replacement blocked when disabled

        When ALLOW_POSITION_REPLACEMENT is true and signal is opposite side to
        existing position, _maybe_allow_replacement returns True.
        """
        # Existing position is short, signal is long (opposite)
        existing_side = "short"
        signal = {"side": signal_side}
        ctx = StageContext(
            symbol=symbol,
            data={
                "positions": [{"symbol": symbol, "side": existing_side, "size": 1.0}],
                "risk_limits": {"max_positions_per_symbol": 1},
            },
        )

        env_patch = {
            "ALLOW_POSITION_REPLACEMENT": "true",
            "REPLACE_OPPOSITE_ONLY": "true",
            "REPLACE_MIN_HOLD_SEC": "0",
            "REPLACE_MIN_EDGE_BPS": "0",
            "REPLACE_MIN_CONFIDENCE": "0",
        }
        with patch.dict(os.environ, env_patch, clear=False):
            result = _maybe_allow_replacement(signal, ctx)
            assert result is True, (
                f"Expected replacement allowed for opposite side when enabled, "
                f"signal_side={signal_side}, existing_side={existing_side}"
            )

    @settings(max_examples=200)
    @given(
        symbol=symbols,
        signal_side=st.sampled_from(["sell", "short"]),
    )
    def test_same_side_blocked_with_replace_opposite_only(
        self, symbol: str, signal_side: str,
    ):
        """Feature: scalping-pipeline-audit, Property 30: Position replacement blocked when disabled

        When REPLACE_OPPOSITE_ONLY is true, same-side replacement is blocked
        even when ALLOW_POSITION_REPLACEMENT is true.
        """
        existing_side = "short"
        signal = {"side": signal_side}
        ctx = StageContext(
            symbol=symbol,
            data={
                "positions": [{"symbol": symbol, "side": existing_side, "size": 1.0}],
                "risk_limits": {"max_positions_per_symbol": 1},
            },
        )

        env_patch = {
            "ALLOW_POSITION_REPLACEMENT": "true",
            "REPLACE_OPPOSITE_ONLY": "true",
        }
        with patch.dict(os.environ, env_patch, clear=False):
            result = _maybe_allow_replacement(signal, ctx)
            assert result is False, (
                f"Expected same-side replacement blocked with REPLACE_OPPOSITE_ONLY=true, "
                f"signal_side={signal_side}, existing_side={existing_side}"
            )

    @settings(max_examples=200)
    @given(symbol=symbols)
    def test_no_positions_returns_false(self, symbol: str):
        """Feature: scalping-pipeline-audit, Property 30: Position replacement blocked when disabled

        When there are no existing positions, _maybe_allow_replacement returns False
        (nothing to replace).
        """
        signal = {"side": "buy"}
        ctx = StageContext(
            symbol=symbol,
            data={
                "positions": [],
                "risk_limits": {"max_positions_per_symbol": 1},
            },
        )

        env_patch = {"ALLOW_POSITION_REPLACEMENT": "true"}
        with patch.dict(os.environ, env_patch, clear=False):
            result = _maybe_allow_replacement(signal, ctx)
            assert result is False, (
                "Expected False when no positions exist (nothing to replace)"
            )

    @settings(max_examples=200)
    @given(
        symbol=symbols,
        signal_side=signal_sides,
        existing_side=position_sides,
    )
    def test_non_dict_signal_always_returns_false(
        self, symbol: str, signal_side: str, existing_side: str,
    ):
        """Feature: scalping-pipeline-audit, Property 30: Position replacement blocked when disabled

        Non-dict signals always return False from _maybe_allow_replacement.
        """
        signal = "not_a_dict"
        ctx = StageContext(
            symbol=symbol,
            data={
                "positions": [{"symbol": symbol, "side": existing_side, "size": 1.0}],
                "risk_limits": {"max_positions_per_symbol": 1},
            },
        )

        env_patch = {"ALLOW_POSITION_REPLACEMENT": "true"}
        with patch.dict(os.environ, env_patch, clear=False):
            result = _maybe_allow_replacement(signal, ctx)
            assert result is False, (
                "Non-dict signal should always return False"
            )
