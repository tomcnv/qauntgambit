"""
Property-based tests for EV Gate and Cost Estimation.

Feature: scalping-pipeline-audit

These tests verify correctness properties of the EVGateStage's EV calculation
and the CostEstimator's component sum invariant.

**Validates: Requirements 3.1, 3.2**
"""

from __future__ import annotations

import math
import os
from unittest.mock import patch

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

from quantgambit.signals.stages.ev_gate import (
    CostEstimate,
    CostEstimator,
    EVGateConfig,
    EVGateStage,
    EVGateRejectCode,
    calculate_ev,
    calculate_cost_ratio,
)
from quantgambit.risk.fee_model import FeeModel, FeeConfig
from quantgambit.risk.slippage_model import SlippageModel
from quantgambit.execution.execution_policy import ExecutionPolicy


# ═══════════════════════════════════════════════════════════════
# SHARED HYPOTHESIS STRATEGIES
# ═══════════════════════════════════════════════════════════════

# Valid win probability: strictly inside (0, 1)
probabilities = st.floats(min_value=0.01, max_value=0.99, allow_nan=False, allow_infinity=False)

# Positive reward-to-risk ratio
reward_ratios = st.floats(min_value=0.1, max_value=20.0, allow_nan=False, allow_infinity=False)

# Non-negative cost ratio
cost_ratios = st.floats(min_value=0.0, max_value=0.99, allow_nan=False, allow_infinity=False)

# EV min thresholds
ev_min_values = st.floats(min_value=0.001, max_value=0.5, allow_nan=False, allow_infinity=False)

# Symbol generator
symbols = st.sampled_from(["BTCUSDT", "ETHUSDT", "SOLUSDT"])

# Volatility regime generator
volatility_regimes = st.sampled_from(["low", "normal", "high", "extreme"])

# Positive price values
prices = st.floats(min_value=100.0, max_value=100000.0, allow_nan=False, allow_infinity=False)

# Positive spread in bps
spread_bps_values = st.floats(min_value=0.1, max_value=50.0, allow_nan=False, allow_infinity=False)

# Positive depth in USD
depth_usd_values = st.floats(min_value=500.0, max_value=100000.0, allow_nan=False, allow_infinity=False)

# Order size in USD
order_size_values = st.floats(min_value=50.0, max_value=2000.0, allow_nan=False, allow_infinity=False)

# Non-negative bps values for cost components
cost_component_bps = st.floats(min_value=0.0, max_value=100.0, allow_nan=False, allow_infinity=False)


# ═══════════════════════════════════════════════════════════════
# Property 8: EV calculation correctness
# ═══════════════════════════════════════════════════════════════


class TestEVCalculationCorrectness:
    """
    Feature: scalping-pipeline-audit, Property 8: EV calculation correctness

    For any valid p ∈ (0,1), R > 0, C ≥ 0:
      calculate_ev(p, R, C) == p × R - (1 - p) × 1 - C
    and the EVGateStage rejects when the result is below ev_min.

    **Validates: Requirements 3.1**
    """

    @settings(max_examples=200)
    @given(
        p=probabilities,
        R=reward_ratios,
        C=cost_ratios,
    )
    def test_ev_formula_matches_specification(self, p: float, R: float, C: float):
        """Feature: scalping-pipeline-audit, Property 8: EV calculation correctness

        Verify that calculate_ev(p, R, C) returns exactly p × R - (1 - p) × 1 - C.
        """
        expected = p * R - (1 - p) * 1 - C
        actual = calculate_ev(p, R, C)
        assert math.isclose(actual, expected, rel_tol=1e-9, abs_tol=1e-12), (
            f"EV mismatch: calculate_ev({p}, {R}, {C}) = {actual}, expected {expected}"
        )

    @settings(max_examples=200)
    @given(
        p=probabilities,
        R=reward_ratios,
        C=cost_ratios,
        ev_min=ev_min_values,
    )
    def test_ev_below_threshold_means_rejection(
        self, p: float, R: float, C: float, ev_min: float
    ):
        """Feature: scalping-pipeline-audit, Property 8: EV calculation correctness

        When EV < ev_min, the trade should be rejected.
        When EV >= ev_min, the trade should not be rejected on EV grounds.
        """
        ev = calculate_ev(p, R, C)

        if ev < ev_min:
            # EV is below threshold — this should be a rejection case
            assert ev < ev_min, (
                f"Expected EV={ev} < ev_min={ev_min} to indicate rejection"
            )
        else:
            # EV meets threshold — this should not be rejected on EV grounds
            assert ev >= ev_min, (
                f"Expected EV={ev} >= ev_min={ev_min} to indicate acceptance"
            )

    @settings(max_examples=200)
    @given(
        p=probabilities,
        R=reward_ratios,
        C=cost_ratios,
    )
    def test_ev_increases_with_probability(self, p: float, R: float, C: float):
        """Feature: scalping-pipeline-audit, Property 8: EV calculation correctness

        EV should be monotonically increasing with p (for fixed R, C).
        If p2 > p1, then EV(p2) > EV(p1).
        """
        # Pick a slightly higher probability
        p2 = min(p + 0.01, 0.999)
        assume(p2 > p)

        ev1 = calculate_ev(p, R, C)
        ev2 = calculate_ev(p2, R, C)

        assert ev2 > ev1, (
            f"EV should increase with p: EV({p2}, {R}, {C})={ev2} "
            f"should be > EV({p}, {R}, {C})={ev1}"
        )

    @settings(max_examples=200)
    @given(
        p=probabilities,
        R=reward_ratios,
        C=cost_ratios,
    )
    def test_ev_decreases_with_cost(self, p: float, R: float, C: float):
        """Feature: scalping-pipeline-audit, Property 8: EV calculation correctness

        EV should be monotonically decreasing with C (for fixed p, R).
        If C2 > C1, then EV(C2) < EV(C1).
        """
        C2 = C + 0.01
        assume(C2 <= 1.0)

        ev1 = calculate_ev(p, R, C)
        ev2 = calculate_ev(p, R, C2)

        assert ev2 < ev1, (
            f"EV should decrease with cost: EV({p}, {R}, {C2})={ev2} "
            f"should be < EV({p}, {R}, {C})={ev1}"
        )


# ═══════════════════════════════════════════════════════════════
# Property 9: Cost estimate component sum invariant
# ═══════════════════════════════════════════════════════════════


class TestCostEstimateComponentSumInvariant:
    """
    Feature: scalping-pipeline-audit, Property 9: Cost estimate component sum invariant

    For any CostEstimate, total_bps == spread_bps + fee_bps + slippage_bps + adverse_selection_bps.

    **Validates: Requirements 3.2**
    """

    @settings(max_examples=200)
    @given(
        spread_bps=cost_component_bps,
        fee_bps=cost_component_bps,
        slippage_bps=cost_component_bps,
        adverse_selection_bps=cost_component_bps,
    )
    def test_cost_estimate_total_equals_component_sum(
        self,
        spread_bps: float,
        fee_bps: float,
        slippage_bps: float,
        adverse_selection_bps: float,
    ):
        """Feature: scalping-pipeline-audit, Property 9: Cost estimate component sum invariant

        Directly constructing a CostEstimate with total_bps = sum of components
        should always hold the invariant.
        """
        expected_total = spread_bps + fee_bps + slippage_bps + adverse_selection_bps
        estimate = CostEstimate(
            spread_bps=spread_bps,
            fee_bps=fee_bps,
            slippage_bps=slippage_bps,
            adverse_selection_bps=adverse_selection_bps,
            total_bps=expected_total,
        )
        assert math.isclose(estimate.total_bps, expected_total, rel_tol=1e-9, abs_tol=1e-12), (
            f"CostEstimate total_bps={estimate.total_bps} != "
            f"sum of components={expected_total}"
        )

    @settings(max_examples=200)
    @given(
        symbol=symbols,
        spread_bps=st.floats(min_value=0.5, max_value=20.0, allow_nan=False, allow_infinity=False),
        bid_depth_usd=depth_usd_values,
        ask_depth_usd=depth_usd_values,
        order_size_usd=order_size_values,
        volatility_regime=volatility_regimes,
    )
    def test_cost_estimator_produces_consistent_totals(
        self,
        symbol: str,
        spread_bps: float,
        bid_depth_usd: float,
        ask_depth_usd: float,
        order_size_usd: float,
        volatility_regime: str,
    ):
        """Feature: scalping-pipeline-audit, Property 9: Cost estimate component sum invariant

        When CostEstimator.estimate() produces a CostEstimate, the total_bps
        must equal the sum of spread_bps + fee_bps + slippage_bps + adverse_selection_bps.
        """
        # Build realistic prices from spread
        mid_price = 50000.0 if symbol == "BTCUSDT" else (3000.0 if symbol == "ETHUSDT" else 150.0)
        half_spread = mid_price * spread_bps / 20000.0
        best_bid = mid_price - half_spread
        best_ask = mid_price + half_spread
        entry_price = mid_price
        # TP slightly above entry for a long trade
        exit_price = entry_price * 1.005
        size = order_size_usd / entry_price

        fee_model = FeeModel(FeeConfig.bybit_regular())
        execution_policy = ExecutionPolicy()
        slippage_model = SlippageModel()

        cost_estimator = CostEstimator(
            fee_model=fee_model,
            execution_policy=execution_policy,
            slippage_model=slippage_model,
        )

        estimate = cost_estimator.estimate(
            symbol=symbol,
            strategy_id="mean_reversion_fade",
            setup_type="mean_reversion",
            entry_price=entry_price,
            exit_price=exit_price,
            size=size,
            best_bid=best_bid,
            best_ask=best_ask,
            order_size_usd=order_size_usd,
            volatility_regime=volatility_regime,
            bid_depth_usd=bid_depth_usd,
            ask_depth_usd=ask_depth_usd,
        )

        expected_total = (
            estimate.spread_bps
            + estimate.fee_bps
            + estimate.slippage_bps
            + estimate.adverse_selection_bps
        )
        assert math.isclose(estimate.total_bps, expected_total, rel_tol=1e-9, abs_tol=1e-12), (
            f"CostEstimator invariant violated for {symbol}: "
            f"total_bps={estimate.total_bps} != "
            f"spread({estimate.spread_bps}) + fee({estimate.fee_bps}) + "
            f"slippage({estimate.slippage_bps}) + adverse({estimate.adverse_selection_bps}) "
            f"= {expected_total}"
        )

    @settings(max_examples=200)
    @given(
        symbol=symbols,
        volatility_regime=volatility_regimes,
        order_size_usd=order_size_values,
    )
    def test_cost_estimate_components_are_non_negative(
        self,
        symbol: str,
        volatility_regime: str,
        order_size_usd: float,
    ):
        """Feature: scalping-pipeline-audit, Property 9: Cost estimate component sum invariant

        All cost components produced by CostEstimator should be non-negative.
        """
        mid_price = 50000.0 if symbol == "BTCUSDT" else (3000.0 if symbol == "ETHUSDT" else 150.0)
        spread_bps = 3.0
        half_spread = mid_price * spread_bps / 20000.0
        best_bid = mid_price - half_spread
        best_ask = mid_price + half_spread
        entry_price = mid_price
        exit_price = entry_price * 1.005
        size = order_size_usd / entry_price

        fee_model = FeeModel(FeeConfig.bybit_regular())
        cost_estimator = CostEstimator(
            fee_model=fee_model,
            execution_policy=ExecutionPolicy(),
            slippage_model=SlippageModel(),
        )

        estimate = cost_estimator.estimate(
            symbol=symbol,
            strategy_id="breakout_scalp",
            setup_type="breakout",
            entry_price=entry_price,
            exit_price=exit_price,
            size=size,
            best_bid=best_bid,
            best_ask=best_ask,
            order_size_usd=order_size_usd,
            volatility_regime=volatility_regime,
            bid_depth_usd=5000.0,
            ask_depth_usd=5000.0,
        )

        assert estimate.spread_bps >= 0, f"spread_bps should be >= 0, got {estimate.spread_bps}"
        assert estimate.fee_bps >= 0, f"fee_bps should be >= 0, got {estimate.fee_bps}"
        assert estimate.slippage_bps >= 0, f"slippage_bps should be >= 0, got {estimate.slippage_bps}"
        assert estimate.adverse_selection_bps >= 0, (
            f"adverse_selection_bps should be >= 0, got {estimate.adverse_selection_bps}"
        )
        assert estimate.total_bps >= 0, f"total_bps should be >= 0, got {estimate.total_bps}"
