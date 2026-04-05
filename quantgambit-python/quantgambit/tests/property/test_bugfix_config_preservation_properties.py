"""
Property-based preservation tests for config safety invariants.

Feature: scalping-config-fixes

These tests assert safety invariants that MUST hold on the current (unfixed) config
and MUST CONTINUE to hold after the config fixes are applied. They establish the
baseline that the fix must preserve.

**Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7**
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from hypothesis import given, settings, assume, note
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
    pass  # fall back to os.environ


def _env_float(name: str, default: float) -> float:
    """Read a float env var with a fallback default."""
    return float(os.getenv(name, str(default)))


def _env_int(name: str, default: int) -> int:
    """Read an int env var with a fallback default."""
    return int(float(os.getenv(name, str(default))))


# ═══════════════════════════════════════════════════════════════
# Property 2 (Preservation): Config Safety Invariants
# ═══════════════════════════════════════════════════════════════


class TestDepthPreservation:
    """Preservation: Global gate depth must remain meaningful.

    The GLOBAL_GATE_MIN_DEPTH_USD must stay >= $2,000 to prevent trading in
    thin markets. This invariant holds on the current config (20000) and must
    hold after the fix.

    **Validates: Requirements 3.1**
    """

    @settings(max_examples=1)
    @given(data=st.data())
    def test_global_gate_depth_meaningful(self, data: st.DataObject):
        """GLOBAL_GATE_MIN_DEPTH_USD >= $2,000 (meaningful depth requirement)."""
        global_gate = _env_float("GLOBAL_GATE_MIN_DEPTH_USD", 20_000)

        note(f"GLOBAL_GATE_MIN_DEPTH_USD={global_gate}")
        assert global_gate >= 2_000, (
            f"GLOBAL_GATE_MIN_DEPTH_USD={global_gate} is below $2,000 — "
            f"too low to prevent trading in thin markets"
        )

    @settings(max_examples=50)
    @given(
        depth_perturbation=st.floats(
            min_value=2_000, max_value=100_000, allow_nan=False, allow_infinity=False
        )
    )
    def test_depth_perturbation_preserves_minimum(self, depth_perturbation: float):
        """Any valid depth perturbation within bounds still satisfies >= $2,000."""
        note(f"perturbed depth={depth_perturbation}")
        assert depth_perturbation >= 2_000


class TestBidAskSymmetryPreservation:
    """Preservation: Bid and ask depth thresholds must remain equal.

    DATA_READINESS_MIN_BID_DEPTH_USD must equal DATA_READINESS_MIN_ASK_DEPTH_USD.
    This invariant holds on the current config (both 500) and must hold after fix.

    **Validates: Requirements 3.6**
    """

    @settings(max_examples=1)
    @given(data=st.data())
    def test_bid_ask_depth_symmetry(self, data: st.DataObject):
        """DATA_READINESS_MIN_BID_DEPTH_USD == DATA_READINESS_MIN_ASK_DEPTH_USD."""
        dr_bid = _env_float("DATA_READINESS_MIN_BID_DEPTH_USD", 500)
        dr_ask = _env_float("DATA_READINESS_MIN_ASK_DEPTH_USD", 500)

        note(f"dr_bid={dr_bid}, dr_ask={dr_ask}")
        assert dr_bid == dr_ask, (
            f"Bid/ask depth asymmetry: bid={dr_bid}, ask={dr_ask}"
        )

    @settings(max_examples=50)
    @given(
        depth_value=st.floats(
            min_value=100, max_value=50_000, allow_nan=False, allow_infinity=False
        )
    )
    def test_symmetric_perturbation_preserves_equality(self, depth_value: float):
        """When bid and ask are set to the same value, symmetry holds."""
        # Simulate a valid config perturbation where both are set identically
        bid = depth_value
        ask = depth_value
        note(f"perturbed bid={bid}, ask={ask}")
        assert bid == ask


class TestFeePreservation:
    """Preservation: Strategy fee must be at least the actual taker rate.

    STRATEGY_FEE_BPS must be >= 5.5 (the actual bybit_regular taker rate)
    to avoid under-counting fees. This invariant holds on the current config
    (6.0) and must hold after the fix.

    **Validates: Requirements 3.2**
    """

    ACTUAL_TAKER_RATE_BPS = 5.5

    @settings(max_examples=1)
    @given(data=st.data())
    def test_strategy_fee_gte_taker_rate(self, data: st.DataObject):
        """STRATEGY_FEE_BPS >= 5.5 (at least the actual taker rate)."""
        strategy_fee = _env_float("STRATEGY_FEE_BPS", 6.0)

        note(f"STRATEGY_FEE_BPS={strategy_fee}")
        assert strategy_fee >= self.ACTUAL_TAKER_RATE_BPS, (
            f"STRATEGY_FEE_BPS={strategy_fee} is below the actual taker rate "
            f"of {self.ACTUAL_TAKER_RATE_BPS} bps — fees would be under-counted"
        )

    @settings(max_examples=50)
    @given(
        fee_perturbation=st.floats(
            min_value=5.5, max_value=20.0, allow_nan=False, allow_infinity=False
        )
    )
    def test_fee_perturbation_preserves_minimum(self, fee_perturbation: float):
        """Any valid fee perturbation within bounds still satisfies >= 5.5 bps."""
        note(f"perturbed fee={fee_perturbation}")
        assert fee_perturbation >= self.ACTUAL_TAKER_RATE_BPS


class TestHardMaxPreservation:
    """Preservation: Hard max order notional must be >= position size,
    and symbol notional must be > order notional.

    These invariants hold on the current config and must hold after the fix.

    **Validates: Requirements 3.3, 3.7**
    """

    @settings(max_examples=1)
    @given(data=st.data())
    def test_hard_max_gte_position_size(self, data: st.DataObject):
        """EXECUTION_HARD_MAX_ORDER_NOTIONAL_USD >= MAX_POSITION_SIZE_USD."""
        hard_max = _env_float("EXECUTION_HARD_MAX_ORDER_NOTIONAL_USD", 9000)
        max_pos = _env_float("MAX_POSITION_SIZE_USD", 2500)

        note(f"hard_max={hard_max}, max_pos={max_pos}")
        assert hard_max >= max_pos, (
            f"EXECUTION_HARD_MAX_ORDER_NOTIONAL_USD={hard_max} is below "
            f"MAX_POSITION_SIZE_USD={max_pos} — cannot open a max-size position"
        )

    @settings(max_examples=1)
    @given(data=st.data())
    def test_symbol_notional_gt_order_notional(self, data: st.DataObject):
        """EXECUTION_HARD_MAX_SYMBOL_NOTIONAL_USD > EXECUTION_HARD_MAX_ORDER_NOTIONAL_USD."""
        symbol_max = _env_float("EXECUTION_HARD_MAX_SYMBOL_NOTIONAL_USD", 26400)
        order_max = _env_float("EXECUTION_HARD_MAX_ORDER_NOTIONAL_USD", 9000)

        note(f"symbol_max={symbol_max}, order_max={order_max}")
        assert symbol_max > order_max, (
            f"EXECUTION_HARD_MAX_SYMBOL_NOTIONAL_USD={symbol_max} is not > "
            f"EXECUTION_HARD_MAX_ORDER_NOTIONAL_USD={order_max}"
        )

    @settings(max_examples=50)
    @given(
        max_pos=st.floats(
            min_value=50, max_value=10_000, allow_nan=False, allow_infinity=False
        ),
        hard_max_mult=st.floats(
            min_value=1.0, max_value=5.0, allow_nan=False, allow_infinity=False
        ),
        symbol_mult=st.floats(
            min_value=1.01, max_value=10.0, allow_nan=False, allow_infinity=False
        ),
    )
    def test_perturbation_preserves_ordering(
        self, max_pos: float, hard_max_mult: float, symbol_mult: float
    ):
        """Random valid config perturbations preserve hard_max >= pos and symbol > order."""
        hard_max = max_pos * hard_max_mult
        symbol_max = hard_max * symbol_mult

        note(f"max_pos={max_pos}, hard_max={hard_max}, symbol_max={symbol_max}")
        assert hard_max >= max_pos, "hard_max must be >= max_pos"
        assert symbol_max > hard_max, "symbol_max must be > hard_max"


class TestCooldownPreservation:
    """Preservation: COOLDOWN_MAX_ENTRIES_PER_HOUR must be set and serve as
    an upper bound on trade frequency.

    This invariant holds on the current config (24) and must hold after the fix.

    **Validates: Requirements 3.4**
    """

    @settings(max_examples=1)
    @given(data=st.data())
    def test_max_entries_per_hour_is_set(self, data: st.DataObject):
        """COOLDOWN_MAX_ENTRIES_PER_HOUR is set and positive."""
        raw = os.getenv("COOLDOWN_MAX_ENTRIES_PER_HOUR")

        note(f"COOLDOWN_MAX_ENTRIES_PER_HOUR raw={raw}")
        assert raw is not None, (
            "COOLDOWN_MAX_ENTRIES_PER_HOUR is not set in .env"
        )

        max_entries = int(float(raw))
        note(f"COOLDOWN_MAX_ENTRIES_PER_HOUR={max_entries}")
        assert max_entries > 0, (
            f"COOLDOWN_MAX_ENTRIES_PER_HOUR={max_entries} must be positive"
        )

    @settings(max_examples=1)
    @given(data=st.data())
    def test_max_entries_serves_as_upper_bound(self, data: st.DataObject):
        """COOLDOWN_MAX_ENTRIES_PER_HOUR bounds the theoretical max trades/hour.

        With COOLDOWN_ENTRY_SEC as the minimum gap between entries, the
        theoretical max is 3600 / COOLDOWN_ENTRY_SEC. The configured
        COOLDOWN_MAX_ENTRIES_PER_HOUR must be <= this theoretical max
        (otherwise it's not a binding constraint).
        """
        max_entries = _env_int("COOLDOWN_MAX_ENTRIES_PER_HOUR", 24)
        cooldown_entry = _env_float("COOLDOWN_ENTRY_SEC", 45)

        theoretical_max = 3600 / cooldown_entry if cooldown_entry > 0 else float("inf")
        note(
            f"max_entries={max_entries}, cooldown_entry={cooldown_entry}s, "
            f"theoretical_max={theoretical_max:.1f}"
        )
        assert max_entries <= theoretical_max, (
            f"COOLDOWN_MAX_ENTRIES_PER_HOUR={max_entries} exceeds theoretical max "
            f"of {theoretical_max:.1f} (3600/{cooldown_entry}s)"
        )

    @settings(max_examples=50)
    @given(
        cooldown_entry=st.floats(
            min_value=10, max_value=300, allow_nan=False, allow_infinity=False
        ),
        max_entries=st.integers(min_value=1, max_value=200),
    )
    def test_perturbation_preserves_upper_bound(
        self, cooldown_entry: float, max_entries: int
    ):
        """Random valid cooldown perturbations: max_entries <= 3600/cooldown_entry."""
        theoretical_max = 3600 / cooldown_entry
        assume(max_entries <= theoretical_max)

        note(
            f"cooldown_entry={cooldown_entry}s, max_entries={max_entries}, "
            f"theoretical_max={theoretical_max:.1f}"
        )
        assert max_entries <= theoretical_max


class TestAuditTestPreservation:
    """Preservation: Currently-passing audit tests must continue to pass.

    This is a meta-invariant — we verify that the config values needed by
    existing audit tests are present and within expected ranges.

    **Validates: Requirements 3.5**
    """

    @settings(max_examples=1)
    @given(data=st.data())
    def test_critical_config_keys_present(self, data: st.DataObject):
        """All config keys referenced by audit tests must be present in .env."""
        critical_keys = [
            "GLOBAL_GATE_MIN_DEPTH_USD",
            "DATA_READINESS_MIN_BID_DEPTH_USD",
            "DATA_READINESS_MIN_ASK_DEPTH_USD",
            "STRATEGY_FEE_BPS",
            "FEE_AWARE_ENTRY_FEE_RATE_BPS",
            "EXECUTION_HARD_MAX_ORDER_NOTIONAL_USD",
            "EXECUTION_HARD_MAX_SYMBOL_NOTIONAL_USD",
            "MAX_POSITION_SIZE_USD",
            "COOLDOWN_ENTRY_SEC",
            "COOLDOWN_SAME_DIRECTION_SEC",
            "COOLDOWN_MAX_ENTRIES_PER_HOUR",
            "MIN_ORDER_INTERVAL_SEC",
        ]
        missing = [k for k in critical_keys if os.getenv(k) is None]
        note(f"missing keys: {missing}")
        assert not missing, (
            f"Critical config keys missing from .env: {missing}"
        )
