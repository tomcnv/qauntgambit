"""
Property-based tests for Execution Layer.

Feature: scalping-pipeline-audit

These tests verify correctness properties of the ExecutionWorker and ExecutionPolicy
related to maker entry price derivation, spread limit enforcement, strategy-type
mapping, and stop-out cooldown enforcement.

**Validates: Requirements 5.1, 5.4, 5.5, 5.8**
"""

from __future__ import annotations

import time
from dataclasses import replace
from typing import Dict, List, Optional, Set
from unittest.mock import MagicMock, patch

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

from quantgambit.execution.execution_policy import ExecutionPlan, ExecutionPolicy
from quantgambit.execution.execution_worker import (
    ExecutionWorker,
    ExecutionWorkerConfig,
    _safe_float,
)


# ═══════════════════════════════════════════════════════════════
# SHARED HYPOTHESIS STRATEGIES
# ═══════════════════════════════════════════════════════════════

symbols = st.sampled_from(["BTCUSDT", "ETHUSDT", "SOLUSDT"])

sides = st.sampled_from(["buy", "long", "sell", "short"])

# Strategy IDs covering all known setup types
mean_reversion_strategies = st.sampled_from([
    "mean_reversion_fade",
    "mean_reversion_scalp",
    "fade_extreme",
])

breakout_strategies = st.sampled_from([
    "breakout_scalp",
    "breakout_momentum",
    "momentum_burst",
])

trend_pullback_strategies = st.sampled_from([
    "trend_pullback",
    "pullback_scalp",
    "trend_continuation",
])

low_vol_grind_strategies = st.sampled_from([
    "low_vol_grind",
    "grind_scalp",
])

unknown_strategies = st.sampled_from([
    "poc_magnet_scalp",
    "custom_strategy_xyz",
    "range_bound",
])

all_strategies = st.one_of(
    mean_reversion_strategies,
    breakout_strategies,
    trend_pullback_strategies,
    low_vol_grind_strategies,
    unknown_strategies,
)

# Spread values in bps
spread_bps_values = st.floats(min_value=0.0, max_value=100.0, allow_nan=False, allow_infinity=False)

# Spread values in ticks
spread_ticks_values = st.floats(min_value=0.0, max_value=50.0, allow_nan=False, allow_infinity=False)


# ═══════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════

def _make_execution_worker(
    config: Optional[ExecutionWorkerConfig] = None,
) -> ExecutionWorker:
    """Build a minimal ExecutionWorker with mocked dependencies for unit testing."""
    redis_client = MagicMock()
    redis_client.redis = MagicMock()
    execution_manager = MagicMock()
    worker = ExecutionWorker(
        redis_client=redis_client,
        execution_manager=execution_manager,
        bot_id="test_bot",
        exchange="bybit",
        config=config or ExecutionWorkerConfig(),
    )
    return worker


# ═══════════════════════════════════════════════════════════════
# Property 15: Maker entry price derivation
# ═══════════════════════════════════════════════════════════════


class TestMakerEntryPriceDerivation:
    """
    Feature: scalping-pipeline-audit, Property 15: Maker entry price derivation

    In maker_post_only mode, the ExecutionWorker derives the limit price using
    ENTRY_MAKER_PRICE_OFFSET_TICKS offset from the best bid/ask, and the fill
    window is ENTRY_MAKER_FILL_WINDOW_MS.

    **Validates: Requirements 5.1**
    """

    @settings(max_examples=200)
    @given(
        side=sides,
        bid=st.floats(min_value=100.0, max_value=100000.0, allow_nan=False, allow_infinity=False),
        spread_pct=st.floats(min_value=0.001, max_value=0.01, allow_nan=False, allow_infinity=False),
        offset_ticks=st.integers(min_value=0, max_value=5),
    )
    def test_maker_price_offset_direction(self, side, bid, spread_pct, offset_ticks):
        """
        Feature: scalping-pipeline-audit, Property 15: Maker entry price derivation

        For any buy/long side, the derived maker price should be >= bid (offset nudges
        toward spread interior). For sell/short, the derived price should be <= ask.
        The price must always stay on the maker side of the book.

        **Validates: Requirements 5.1**
        """
        ask = bid * (1.0 + spread_pct)
        assume(ask > bid)

        config = ExecutionWorkerConfig(
            entry_execution_mode="maker_post_only",
            entry_maker_price_offset_ticks=offset_ticks,
        )
        worker = _make_execution_worker(config)
        price = worker._derive_maker_limit_price(
            side=side, bid=bid, ask=ask, offset_ticks=offset_ticks,
        )

        if side in {"buy", "long"}:
            # Buy maker price: at or above bid, strictly below ask
            assert price >= bid, (
                f"Buy maker price {price} should be >= bid {bid}"
            )
            assert price < ask, (
                f"Buy maker price {price} must be < ask {ask} to remain post-only"
            )
        else:
            # Sell maker price: at or below ask, strictly above bid
            assert price <= ask, (
                f"Sell maker price {price} should be <= ask {ask}"
            )
            assert price > bid, (
                f"Sell maker price {price} must be > bid {bid} to remain post-only"
            )

    @settings(max_examples=200)
    @given(
        side=sides,
        bid=st.floats(min_value=1000.0, max_value=80000.0, allow_nan=False, allow_infinity=False),
        spread_pct=st.floats(min_value=0.001, max_value=0.005, allow_nan=False, allow_infinity=False),
    )
    def test_maker_price_with_zero_offset_equals_touch(self, side, bid, spread_pct):
        """
        Feature: scalping-pipeline-audit, Property 15: Maker entry price derivation

        With offset_ticks=0, the derived price should equal the touch price
        (bid for buy, ask for sell).

        **Validates: Requirements 5.1**
        """
        ask = bid * (1.0 + spread_pct)
        assume(ask > bid)

        config = ExecutionWorkerConfig(
            entry_execution_mode="maker_post_only",
            entry_maker_price_offset_ticks=0,
        )
        worker = _make_execution_worker(config)
        price = worker._derive_maker_limit_price(
            side=side, bid=bid, ask=ask, offset_ticks=0,
        )

        if side in {"buy", "long"}:
            assert price == bid, f"Zero offset buy should equal bid {bid}, got {price}"
        else:
            assert price == ask, f"Zero offset sell should equal ask {ask}, got {price}"

    def test_fill_window_config_matches_spec(self):
        """
        Feature: scalping-pipeline-audit, Property 15: Maker entry price derivation

        The fill window for maker_post_only mode should be configurable via
        ENTRY_MAKER_FILL_WINDOW_MS. Default from design is 6000ms.

        **Validates: Requirements 5.1**
        """
        config = ExecutionWorkerConfig(
            entry_execution_mode="maker_post_only",
            entry_maker_fill_window_ms=6000,
            entry_maker_price_offset_ticks=1,
        )
        worker = _make_execution_worker(config)
        assert worker.config.entry_maker_fill_window_ms == 6000
        assert worker.config.entry_maker_price_offset_ticks == 1


# ═══════════════════════════════════════════════════════════════
# Property 16: Execution spread limit enforcement
# ═══════════════════════════════════════════════════════════════


class TestExecutionSpreadLimitEnforcement:
    """
    Feature: scalping-pipeline-audit, Property 16: Execution spread limit enforcement

    Entries are rejected when spread exceeds ENTRY_MAX_SPREAD_BPS or
    ENTRY_MAX_SPREAD_TICKS.

    **Validates: Requirements 5.4**
    """

    @settings(max_examples=200)
    @given(
        spread_bps=st.floats(min_value=0.01, max_value=100.0, allow_nan=False, allow_infinity=False),
        max_spread_bps=st.floats(min_value=0.01, max_value=50.0, allow_nan=False, allow_infinity=False),
    )
    def test_spread_bps_exceeding_limit_rejected(self, spread_bps, max_spread_bps):
        """
        Feature: scalping-pipeline-audit, Property 16: Execution spread limit enforcement

        When spread_bps > ENTRY_MAX_SPREAD_BPS, the entry should be rejected.
        When spread_bps <= ENTRY_MAX_SPREAD_BPS, the entry should pass (bps check).

        **Validates: Requirements 5.4**
        """
        config = ExecutionWorkerConfig(
            entry_max_spread_bps=max_spread_bps,
            entry_max_spread_ticks=0,  # disable ticks check
        )
        worker = _make_execution_worker(config)

        decision = {
            "risk_context": {
                "spread_bps": spread_bps,
                "spread_ticks": None,
            }
        }

        result = worker._check_entry_spread_limits(decision)

        if spread_bps > max_spread_bps:
            assert result is not None, (
                f"Spread {spread_bps} bps exceeds limit {max_spread_bps} bps, "
                f"should be rejected"
            )
            assert "spread_bps_too_wide" in result
        else:
            assert result is None, (
                f"Spread {spread_bps} bps within limit {max_spread_bps} bps, "
                f"should pass"
            )

    @settings(max_examples=200)
    @given(
        spread_ticks=st.floats(min_value=0.0, max_value=50.0, allow_nan=False, allow_infinity=False),
        max_spread_ticks=st.integers(min_value=1, max_value=20),
    )
    def test_spread_ticks_exceeding_limit_rejected(self, spread_ticks, max_spread_ticks):
        """
        Feature: scalping-pipeline-audit, Property 16: Execution spread limit enforcement

        When spread_ticks > ENTRY_MAX_SPREAD_TICKS, the entry should be rejected.
        When spread_ticks <= ENTRY_MAX_SPREAD_TICKS, the entry should pass (ticks check).

        **Validates: Requirements 5.4**
        """
        config = ExecutionWorkerConfig(
            entry_max_spread_bps=0.0,  # disable bps check
            entry_max_spread_ticks=max_spread_ticks,
        )
        worker = _make_execution_worker(config)

        decision = {
            "risk_context": {
                "spread_bps": None,
                "spread_ticks": spread_ticks,
            }
        }

        result = worker._check_entry_spread_limits(decision)

        if spread_ticks > max_spread_ticks:
            assert result is not None, (
                f"Spread {spread_ticks} ticks exceeds limit {max_spread_ticks} ticks, "
                f"should be rejected"
            )
            assert "spread_ticks_too_wide" in result
        else:
            assert result is None, (
                f"Spread {spread_ticks} ticks within limit {max_spread_ticks} ticks, "
                f"should pass"
            )

    @settings(max_examples=200)
    @given(
        spread_bps=st.floats(min_value=0.01, max_value=100.0, allow_nan=False, allow_infinity=False),
        spread_ticks=st.floats(min_value=0.0, max_value=50.0, allow_nan=False, allow_infinity=False),
    )
    def test_both_limits_disabled_always_passes(self, spread_bps, spread_ticks):
        """
        Feature: scalping-pipeline-audit, Property 16: Execution spread limit enforcement

        When both ENTRY_MAX_SPREAD_BPS and ENTRY_MAX_SPREAD_TICKS are <= 0,
        no spread check is performed and all entries pass.

        **Validates: Requirements 5.4**
        """
        config = ExecutionWorkerConfig(
            entry_max_spread_bps=0.0,
            entry_max_spread_ticks=0,
        )
        worker = _make_execution_worker(config)

        decision = {
            "risk_context": {
                "spread_bps": spread_bps,
                "spread_ticks": spread_ticks,
            }
        }

        result = worker._check_entry_spread_limits(decision)
        assert result is None, "Both limits disabled should always pass"


# ═══════════════════════════════════════════════════════════════
# Property 17: Execution policy strategy-type mapping
# ═══════════════════════════════════════════════════════════════


class TestExecutionPolicyStrategyTypeMapping:
    """
    Feature: scalping-pipeline-audit, Property 17: Execution policy strategy-type mapping

    infer_setup_type() returns the correct type for each strategy, and
    plan_execution() produces correct maker/taker probabilities per strategy type.

    **Validates: Requirements 5.5**
    """

    @settings(max_examples=200)
    @given(strategy_id=mean_reversion_strategies)
    def test_mean_reversion_inferred_correctly(self, strategy_id):
        """
        Feature: scalping-pipeline-audit, Property 17: Execution policy strategy-type mapping

        Strategies containing 'mean_reversion' or 'fade' should map to 'mean_reversion'.

        **Validates: Requirements 5.5**
        """
        policy = ExecutionPolicy()
        setup_type = policy.infer_setup_type(strategy_id)
        assert setup_type == "mean_reversion", (
            f"Strategy '{strategy_id}' should map to 'mean_reversion', got '{setup_type}'"
        )

    @settings(max_examples=200)
    @given(strategy_id=breakout_strategies)
    def test_breakout_inferred_correctly(self, strategy_id):
        """
        Feature: scalping-pipeline-audit, Property 17: Execution policy strategy-type mapping

        Strategies containing 'breakout' or 'momentum' should map to 'breakout'.

        **Validates: Requirements 5.5**
        """
        policy = ExecutionPolicy()
        setup_type = policy.infer_setup_type(strategy_id)
        assert setup_type == "breakout", (
            f"Strategy '{strategy_id}' should map to 'breakout', got '{setup_type}'"
        )

    @settings(max_examples=200)
    @given(strategy_id=trend_pullback_strategies)
    def test_trend_pullback_inferred_correctly(self, strategy_id):
        """
        Feature: scalping-pipeline-audit, Property 17: Execution policy strategy-type mapping

        Strategies containing 'pullback' or 'trend' should map to 'trend_pullback'.

        **Validates: Requirements 5.5**
        """
        policy = ExecutionPolicy()
        setup_type = policy.infer_setup_type(strategy_id)
        assert setup_type == "trend_pullback", (
            f"Strategy '{strategy_id}' should map to 'trend_pullback', got '{setup_type}'"
        )

    @settings(max_examples=200)
    @given(strategy_id=low_vol_grind_strategies)
    def test_low_vol_grind_inferred_correctly(self, strategy_id):
        """
        Feature: scalping-pipeline-audit, Property 17: Execution policy strategy-type mapping

        Strategies containing 'low_vol' or 'grind' should map to 'low_vol_grind'.

        **Validates: Requirements 5.5**
        """
        policy = ExecutionPolicy()
        setup_type = policy.infer_setup_type(strategy_id)
        assert setup_type == "low_vol_grind", (
            f"Strategy '{strategy_id}' should map to 'low_vol_grind', got '{setup_type}'"
        )

    @settings(max_examples=200)
    @given(strategy_id=all_strategies)
    @patch.dict("os.environ", {"EXECUTION_POLICY_FORCE_TAKER": ""}, clear=False)
    def test_plan_execution_maker_taker_probabilities(self, strategy_id):
        """
        Feature: scalping-pipeline-audit, Property 17: Execution policy strategy-type mapping

        plan_execution() produces correct maker/taker probabilities per strategy type:
        - mean_reversion: p_entry_maker=0.1, p_exit_maker=0.6
        - breakout: p_entry_maker=0.0, p_exit_maker=0.1
        - trend_pullback: p_entry_maker=0.4, p_exit_maker=0.1
        - low_vol_grind: p_entry_maker=0.7, p_exit_maker=0.7
        - unknown: p_entry_maker=0.0, p_exit_maker=0.5

        **Validates: Requirements 5.5**
        """
        policy = ExecutionPolicy()
        plan = policy.plan_execution(strategy_id)
        setup_type = policy.infer_setup_type(strategy_id)

        expected = {
            "mean_reversion": (0.1, 0.6),
            "breakout": (0.0, 0.1),
            "trend_pullback": (0.4, 0.1),
            "low_vol_grind": (0.7, 0.7),
            "unknown": (0.0, 0.5),
        }

        exp_entry, exp_exit = expected[setup_type]
        assert plan.p_entry_maker == pytest.approx(exp_entry), (
            f"Strategy '{strategy_id}' (type={setup_type}): "
            f"p_entry_maker should be {exp_entry}, got {plan.p_entry_maker}"
        )
        assert plan.p_exit_maker == pytest.approx(exp_exit), (
            f"Strategy '{strategy_id}' (type={setup_type}): "
            f"p_exit_maker should be {exp_exit}, got {plan.p_exit_maker}"
        )

    @settings(max_examples=200)
    @given(strategy_id=all_strategies)
    def test_plan_execution_probabilities_in_valid_range(self, strategy_id):
        """
        Feature: scalping-pipeline-audit, Property 17: Execution policy strategy-type mapping

        All maker/taker probabilities must be in [0, 1].

        **Validates: Requirements 5.5**
        """
        policy = ExecutionPolicy()
        with patch.dict("os.environ", {"EXECUTION_POLICY_FORCE_TAKER": ""}, clear=False):
            plan = policy.plan_execution(strategy_id)

        assert 0.0 <= plan.p_entry_maker <= 1.0, (
            f"p_entry_maker {plan.p_entry_maker} out of [0,1] range"
        )
        assert 0.0 <= plan.p_exit_maker <= 1.0, (
            f"p_exit_maker {plan.p_exit_maker} out of [0,1] range"
        )

    @settings(max_examples=200)
    @given(strategy_id=all_strategies)
    def test_force_taker_overrides_all_strategies(self, strategy_id):
        """
        Feature: scalping-pipeline-audit, Property 17: Execution policy strategy-type mapping

        When EXECUTION_POLICY_FORCE_TAKER is true, all strategies should have
        p_entry_maker=0.0 and p_exit_maker=0.0.

        **Validates: Requirements 5.5**
        """
        policy = ExecutionPolicy()
        with patch.dict("os.environ", {"EXECUTION_POLICY_FORCE_TAKER": "true"}, clear=False):
            plan = policy.plan_execution(strategy_id)

        assert plan.p_entry_maker == 0.0, (
            f"Force taker: p_entry_maker should be 0.0, got {plan.p_entry_maker}"
        )
        assert plan.p_exit_maker == 0.0, (
            f"Force taker: p_exit_maker should be 0.0, got {plan.p_exit_maker}"
        )


# ═══════════════════════════════════════════════════════════════
# Property 18: Stop-out cooldown enforcement
# ═══════════════════════════════════════════════════════════════


class TestStopOutCooldownEnforcement:
    """
    Feature: scalping-pipeline-audit, Property 18: Stop-out cooldown enforcement

    Re-entry within ENTRY_STOP_OUT_COOLDOWN_MS of a stop-out event returns False.

    **Validates: Requirements 5.8**
    """

    @settings(max_examples=200)
    @given(
        symbol=symbols,
        cooldown_ms=st.integers(min_value=1000, max_value=300000),
        elapsed_ms=st.integers(min_value=0, max_value=300000),
    )
    def test_stop_out_cooldown_blocks_early_reentry(self, symbol, cooldown_ms, elapsed_ms):
        """
        Feature: scalping-pipeline-audit, Property 18: Stop-out cooldown enforcement

        After a stop-out, re-entry within ENTRY_STOP_OUT_COOLDOWN_MS should be blocked.
        Re-entry after the cooldown has elapsed should be allowed.

        **Validates: Requirements 5.8**
        """
        config = ExecutionWorkerConfig(
            entry_stop_out_cooldown_ms=cooldown_ms,
        )
        worker = _make_execution_worker(config)

        # Simulate a stop-out by directly setting the cooldown expiry
        cooldown_sec = cooldown_ms / 1000.0
        now = time.time()
        worker._stop_out_skip_until[symbol.upper()] = now + cooldown_sec

        # Simulate time elapsed by adjusting the skip_until relative to "now"
        # If elapsed_ms < cooldown_ms, we're still in cooldown
        # If elapsed_ms >= cooldown_ms, cooldown has expired
        worker._stop_out_skip_until[symbol.upper()] = now + cooldown_sec - (elapsed_ms / 1000.0)

        allowed = worker._allow_entry_after_stop_out(symbol)

        if elapsed_ms < cooldown_ms:
            assert not allowed, (
                f"Re-entry after {elapsed_ms}ms should be blocked "
                f"(cooldown={cooldown_ms}ms)"
            )
        else:
            assert allowed, (
                f"Re-entry after {elapsed_ms}ms should be allowed "
                f"(cooldown={cooldown_ms}ms expired)"
            )

    @settings(max_examples=200)
    @given(symbol=symbols)
    def test_no_stop_out_allows_entry(self, symbol):
        """
        Feature: scalping-pipeline-audit, Property 18: Stop-out cooldown enforcement

        When no stop-out has been recorded for a symbol, entry should be allowed.

        **Validates: Requirements 5.8**
        """
        config = ExecutionWorkerConfig(
            entry_stop_out_cooldown_ms=90000,
        )
        worker = _make_execution_worker(config)

        # No stop-out recorded — _stop_out_skip_until is empty
        allowed = worker._allow_entry_after_stop_out(symbol)
        assert allowed, "No stop-out recorded, entry should be allowed"

    @settings(max_examples=200)
    @given(
        symbol=symbols,
        cooldown_ms=st.integers(min_value=1000, max_value=300000),
    )
    def test_record_stop_out_sets_cooldown(self, symbol, cooldown_ms):
        """
        Feature: scalping-pipeline-audit, Property 18: Stop-out cooldown enforcement

        _record_stop_out_exit() should set the cooldown expiry for the symbol
        when the exit reason contains 'stop_loss'.

        **Validates: Requirements 5.8**
        """
        config = ExecutionWorkerConfig(
            entry_stop_out_cooldown_ms=cooldown_ms,
        )
        worker = _make_execution_worker(config)

        decision = {"symbol": symbol}
        signal = {
            "is_exit_signal": True,
            "reason": "stop_loss_triggered",
        }

        before = time.time()
        worker._record_stop_out_exit(decision, signal)
        after = time.time()

        expected_cooldown_sec = cooldown_ms / 1000.0
        skip_until = worker._stop_out_skip_until.get(symbol.upper(), 0.0)

        # The skip_until should be approximately now + cooldown_sec
        assert skip_until >= before + expected_cooldown_sec - 0.1, (
            f"skip_until {skip_until} should be >= {before + expected_cooldown_sec}"
        )
        assert skip_until <= after + expected_cooldown_sec + 0.1, (
            f"skip_until {skip_until} should be <= {after + expected_cooldown_sec}"
        )

        # Immediately after recording, entry should be blocked
        allowed = worker._allow_entry_after_stop_out(symbol)
        assert not allowed, (
            f"Entry should be blocked immediately after stop-out "
            f"(cooldown={cooldown_ms}ms)"
        )
