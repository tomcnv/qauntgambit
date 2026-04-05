"""
Property-based exploration tests for config fault conditions (Bugs 1–4).

Feature: scalping-config-fixes

These tests encode the EXPECTED behavior for each config parameter relationship.
On UNFIXED config they are expected to FAIL — failure confirms the bugs exist.
After the config fix is applied, these same tests should PASS.

**Validates: Requirements 1.1, 1.2, 1.3, 1.4**
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


# ═══════════════════════════════════════════════════════════════
# Property 1 (Fault Condition): Config Contradictions
# ═══════════════════════════════════════════════════════════════


class TestDepthRatioFaultCondition:
    """Bug 1 — Depth threshold ratio must be ≤ 10×.

    Current .env: GLOBAL_GATE_MIN_DEPTH_USD=20000,
    DATA_READINESS_MIN_BID_DEPTH_USD=500 → ratio = 40×.

    **Validates: Requirements 1.1**
    """

    @settings(max_examples=1)
    @given(data=st.data())
    def test_depth_ratio_within_bounds(self, data: st.DataObject):
        """GLOBAL_GATE_MIN_DEPTH_USD / DATA_READINESS_MIN_BID_DEPTH_USD <= 10."""
        global_gate = _env_float("GLOBAL_GATE_MIN_DEPTH_USD", 20_000)
        dr_bid = _env_float("DATA_READINESS_MIN_BID_DEPTH_USD", 500)

        note(f"global_gate={global_gate}, dr_bid={dr_bid}")
        ratio = global_gate / dr_bid if dr_bid > 0 else float("inf")
        note(f"depth ratio = {ratio:.1f}×")

        assert ratio <= 10, (
            f"Depth ratio {ratio:.1f}× exceeds 10× "
            f"(GLOBAL_GATE={global_gate}, DR_BID={dr_bid})"
        )

    @settings(max_examples=1)
    @given(data=st.data())
    def test_bid_ask_depth_symmetry(self, data: st.DataObject):
        """Preservation: bid depth == ask depth."""
        dr_bid = _env_float("DATA_READINESS_MIN_BID_DEPTH_USD", 500)
        dr_ask = _env_float("DATA_READINESS_MIN_ASK_DEPTH_USD", 500)

        note(f"dr_bid={dr_bid}, dr_ask={dr_ask}")
        assert dr_bid == dr_ask, (
            f"Bid/ask depth asymmetry: bid={dr_bid}, ask={dr_ask}"
        )


class TestFeeAlignmentFaultCondition:
    """Bug 2 — Fee parameters must be aligned.

    Current .env: FEE_AWARE_ENTRY_FEE_RATE_BPS=5.5, STRATEGY_FEE_BPS=6.0
    → 0.5 bps disagreement.

    **Validates: Requirements 1.2**
    """

    @settings(max_examples=1)
    @given(data=st.data())
    def test_fee_parameters_aligned(self, data: st.DataObject):
        """FEE_AWARE_ENTRY_FEE_RATE_BPS == STRATEGY_FEE_BPS."""
        fee_aware = _env_float("FEE_AWARE_ENTRY_FEE_RATE_BPS", 5.5)
        strategy_fee = _env_float("STRATEGY_FEE_BPS", 6.0)

        note(f"fee_aware={fee_aware}, strategy_fee={strategy_fee}")
        assert fee_aware == strategy_fee, (
            f"Fee mismatch: FEE_AWARE_ENTRY={fee_aware} bps "
            f"!= STRATEGY_FEE={strategy_fee} bps (gap={abs(strategy_fee - fee_aware):.1f} bps)"
        )


class TestHardMaxRatioFaultCondition:
    """Bug 3 — Hard max order notional ratio must be ≤ 2×.

    Current .env: EXECUTION_HARD_MAX_ORDER_NOTIONAL_USD=9000,
    MAX_POSITION_SIZE_USD=2500 → ratio = 3.6×.

    **Validates: Requirements 1.3**
    """

    @settings(max_examples=1)
    @given(data=st.data())
    def test_hard_max_ratio_within_bounds(self, data: st.DataObject):
        """EXECUTION_HARD_MAX_ORDER_NOTIONAL_USD / MAX_POSITION_SIZE_USD <= 2.0."""
        hard_max = _env_float("EXECUTION_HARD_MAX_ORDER_NOTIONAL_USD", 9000)
        max_pos = _env_float("MAX_POSITION_SIZE_USD", 2500)

        note(f"hard_max={hard_max}, max_pos={max_pos}")
        ratio = hard_max / max_pos if max_pos > 0 else float("inf")
        note(f"hard max ratio = {ratio:.2f}×")

        assert ratio <= 2.0, (
            f"Hard max ratio {ratio:.2f}× exceeds 2.0× "
            f"(HARD_MAX={hard_max}, MAX_POS={max_pos})"
        )

    @settings(max_examples=1)
    @given(data=st.data())
    def test_hard_max_gte_position_size(self, data: st.DataObject):
        """Preservation: hard max >= position size."""
        hard_max = _env_float("EXECUTION_HARD_MAX_ORDER_NOTIONAL_USD", 9000)
        max_pos = _env_float("MAX_POSITION_SIZE_USD", 2500)

        note(f"hard_max={hard_max}, max_pos={max_pos}")
        assert hard_max >= max_pos, (
            f"Hard max ({hard_max}) < position size ({max_pos})"
        )

    @settings(max_examples=1)
    @given(data=st.data())
    def test_symbol_notional_gt_order_notional(self, data: st.DataObject):
        """Preservation: symbol notional > order notional."""
        symbol_max = _env_float("EXECUTION_HARD_MAX_SYMBOL_NOTIONAL_USD", 26400)
        order_max = _env_float("EXECUTION_HARD_MAX_ORDER_NOTIONAL_USD", 9000)

        note(f"symbol_max={symbol_max}, order_max={order_max}")
        assert symbol_max > order_max, (
            f"Symbol notional ({symbol_max}) not > order notional ({order_max})"
        )


class TestCooldownFaultCondition:
    """Bug 4 — Cooldown parameters must allow scalping frequency.

    Current .env: COOLDOWN_SAME_DIRECTION_SEC=300 (5 min lockout),
    MIN_ORDER_INTERVAL_SEC=180, COOLDOWN_ENTRY_SEC=45.

    **Validates: Requirements 1.4**
    """

    @settings(max_examples=1)
    @given(data=st.data())
    def test_same_direction_cooldown_within_bounds(self, data: st.DataObject):
        """COOLDOWN_SAME_DIRECTION_SEC <= 120."""
        cooldown_same = _env_float("COOLDOWN_SAME_DIRECTION_SEC", 300)

        note(f"cooldown_same_direction={cooldown_same}s")
        assert cooldown_same <= 120, (
            f"COOLDOWN_SAME_DIRECTION_SEC={cooldown_same}s exceeds 120s "
            f"(too restrictive for scalping)"
        )

    @settings(max_examples=1)
    @given(data=st.data())
    def test_min_order_interval_proportional_to_entry_cooldown(
        self, data: st.DataObject
    ):
        """MIN_ORDER_INTERVAL_SEC <= 2 * COOLDOWN_ENTRY_SEC."""
        min_interval = _env_float("MIN_ORDER_INTERVAL_SEC", 180)
        cooldown_entry = _env_float("COOLDOWN_ENTRY_SEC", 45)

        note(f"min_interval={min_interval}s, cooldown_entry={cooldown_entry}s")
        limit = 2 * cooldown_entry
        assert min_interval <= limit, (
            f"MIN_ORDER_INTERVAL_SEC={min_interval}s exceeds "
            f"2 × COOLDOWN_ENTRY_SEC={limit}s"
        )
