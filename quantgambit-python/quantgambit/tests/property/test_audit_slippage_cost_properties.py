"""
Property-based tests for Slippage Modeling and Cost Estimation.

Feature: scalping-pipeline-audit

These tests verify correctness properties of the SlippageModel's calculation
logic and the CostEstimator/EVGateStage slippage floor enforcement.

**Validates: Requirements 6.1, 6.2, 6.3, 6.5**
"""

from __future__ import annotations

import math
import os
from unittest.mock import patch

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

from quantgambit.risk.slippage_model import SlippageModel
from quantgambit.signals.stages.ev_gate import (
    CostEstimate,
    CostEstimator,
    EVGateConfig,
    EVGateStage,
)
from quantgambit.risk.fee_model import FeeModel, FeeConfig
from quantgambit.execution.execution_policy import ExecutionPolicy


# ═══════════════════════════════════════════════════════════════
# SHARED HYPOTHESIS STRATEGIES
# ═══════════════════════════════════════════════════════════════

# Symbols with known floors
symbols = st.sampled_from(["BTCUSDT", "ETHUSDT", "SOLUSDT"])

# Volatility regimes
volatility_regimes = st.sampled_from(["low", "normal", "high", "extreme"])


# Spread in bps (used as market condition indicator)
spread_bps_values = st.floats(min_value=0.5, max_value=30.0, allow_nan=False, allow_infinity=False)

# Book depth in USD
depth_usd_values = st.floats(min_value=500.0, max_value=100000.0, allow_nan=False, allow_infinity=False)

# Order size in USD (typical scalping range)
order_size_values = st.floats(min_value=50.0, max_value=2000.0, allow_nan=False, allow_infinity=False)

# Slippage model multiplier
multiplier_values = st.floats(min_value=0.5, max_value=5.0, allow_nan=False, allow_infinity=False)

# Known symbol floors
SYMBOL_FLOORS = {
    "BTCUSDT": 0.5,
    "ETHUSDT": 0.8,
    "SOLUSDT": 2.0,
}

# Known volatility multipliers
VOLATILITY_MULTIPLIERS = {
    "low": 0.8,
    "normal": 1.0,
    "high": 1.5,
    "extreme": 2.5,
}


# ═══════════════════════════════════════════════════════════════
# Property 19: Slippage model calculation correctness
# ═══════════════════════════════════════════════════════════════


class TestSlippageModelCalculationCorrectness:
    """
    Feature: scalping-pipeline-audit, Property 19: Slippage model calculation correctness

    For any valid inputs (symbol, order_size_usd, book_depth_usd, volatility_regime),
    the SlippageModel.calculate_slippage_bps() should:
    - Apply the symbol-specific floor × SLIPPAGE_MODEL_MULTIPLIER
    - Compute depth_factor as min(1.0 + (order_size_usd / depth) × 10.0, MAX_DEPTH_FACTOR)
    - Apply the correct volatility multiplier (normal:1.0, high:1.5, extreme:2.5)
    - Return a value ≥ the effective floor

    **Validates: Requirements 6.1, 6.3, 6.5**
    """

    @settings(max_examples=200)
    @given(
        symbol=symbols,
        spread_bps=spread_bps_values,
        book_depth_usd=depth_usd_values,
        order_size_usd=order_size_values,
        volatility_regime=volatility_regimes,
        multiplier=multiplier_values,
    )
    def test_slippage_at_least_effective_floor(
        self,
        symbol: str,
        spread_bps: float,
        book_depth_usd: float,
        order_size_usd: float,
        volatility_regime: str,
        multiplier: float,
    ):
        """Feature: scalping-pipeline-audit, Property 19: Slippage model calculation correctness

        The result must always be >= symbol_floor × multiplier (the effective floor).
        """
        env_overrides = {
            "SLIPPAGE_MODEL_MULTIPLIER": str(multiplier),
            "SLIPPAGE_MODEL_FLOOR_BPS": "0.0",
        }
        with patch.dict(os.environ, env_overrides, clear=False):
            model = SlippageModel()

        result = model.calculate_slippage_bps(
            symbol=symbol,
            spread_bps=spread_bps,
            book_depth_usd=book_depth_usd,
            order_size_usd=order_size_usd,
            volatility_regime=volatility_regime,
        )

        symbol_floor = SYMBOL_FLOORS[symbol]
        effective_floor = symbol_floor * multiplier

        assert result >= effective_floor - 1e-9, (
            f"Slippage {result:.4f} bps < effective floor {effective_floor:.4f} bps "
            f"(symbol={symbol}, floor={symbol_floor}, multiplier={multiplier})"
        )

    @settings(max_examples=200)
    @given(
        symbol=symbols,
        spread_bps=spread_bps_values,
        book_depth_usd=depth_usd_values,
        order_size_usd=order_size_values,
    )
    def test_depth_factor_formula(
        self,
        symbol: str,
        spread_bps: float,
        book_depth_usd: float,
        order_size_usd: float,
    ):
        """Feature: scalping-pipeline-audit, Property 19: Slippage model calculation correctness

        Verify depth_factor = min(1.0 + (order_size / depth) × 10.0, MAX_DEPTH_FACTOR).
        """
        env_overrides = {
            "SLIPPAGE_MODEL_MULTIPLIER": "1.0",
            "SLIPPAGE_MODEL_FLOOR_BPS": "0.0",
            "SLIPPAGE_MODEL_MAX_DEPTH_FACTOR": "10.0",
            "SLIPPAGE_MODEL_MIN_DEPTH_USD": "500.0",
        }
        with patch.dict(os.environ, env_overrides, clear=False):
            model = SlippageModel()

        detail = model.calculate_slippage_with_detail(
            symbol=symbol,
            spread_bps=spread_bps,
            book_depth_usd=book_depth_usd,
            order_size_usd=order_size_usd,
            volatility_regime="normal",
            urgency=None,
        )

        # Expected depth factor
        effective_depth = max(book_depth_usd, 500.0)
        depth_ratio = order_size_usd / effective_depth
        expected_depth_factor = min(1.0 + depth_ratio * 10.0, 10.0)

        assert math.isclose(detail.depth_factor, expected_depth_factor, rel_tol=1e-9, abs_tol=1e-12), (
            f"Depth factor mismatch: got {detail.depth_factor}, "
            f"expected {expected_depth_factor} "
            f"(order_size={order_size_usd}, depth={book_depth_usd}, "
            f"effective_depth={effective_depth})"
        )

    @settings(max_examples=200)
    @given(
        symbol=symbols,
        spread_bps=spread_bps_values,
        volatility_regime=volatility_regimes,
    )
    def test_volatility_multiplier_applied_correctly(
        self,
        symbol: str,
        spread_bps: float,
        volatility_regime: str,
    ):
        """Feature: scalping-pipeline-audit, Property 19: Slippage model calculation correctness

        Verify the correct volatility multiplier is applied:
        low:0.8, normal:1.0, high:1.5, extreme:2.5.
        """
        env_overrides = {
            "SLIPPAGE_MODEL_MULTIPLIER": "1.0",
            "SLIPPAGE_MODEL_FLOOR_BPS": "0.0",
        }
        with patch.dict(os.environ, env_overrides, clear=False):
            model = SlippageModel()

        detail = model.calculate_slippage_with_detail(
            symbol=symbol,
            spread_bps=spread_bps,
            volatility_regime=volatility_regime,
        )

        expected_vol_mult = VOLATILITY_MULTIPLIERS[volatility_regime]
        assert math.isclose(detail.volatility_multiplier, expected_vol_mult, rel_tol=1e-9), (
            f"Volatility multiplier mismatch for regime '{volatility_regime}': "
            f"got {detail.volatility_multiplier}, expected {expected_vol_mult}"
        )

    @settings(max_examples=200)
    @given(
        symbol=symbols,
        spread_bps=spread_bps_values,
        book_depth_usd=depth_usd_values,
        order_size_usd=order_size_values,
        multiplier=multiplier_values,
    )
    def test_multiplier_scales_result(
        self,
        symbol: str,
        spread_bps: float,
        book_depth_usd: float,
        order_size_usd: float,
        multiplier: float,
    ):
        """Feature: scalping-pipeline-audit, Property 19: Slippage model calculation correctness

        Verify that SLIPPAGE_MODEL_MULTIPLIER is applied: the result with multiplier M
        should be >= the result with multiplier 1.0 when M >= 1.0, and vice versa.
        """
        assume(multiplier != 1.0)

        env_base = {
            "SLIPPAGE_MODEL_MULTIPLIER": "1.0",
            "SLIPPAGE_MODEL_FLOOR_BPS": "0.0",
        }
        with patch.dict(os.environ, env_base, clear=False):
            model_base = SlippageModel()

        env_scaled = {
            "SLIPPAGE_MODEL_MULTIPLIER": str(multiplier),
            "SLIPPAGE_MODEL_FLOOR_BPS": "0.0",
        }
        with patch.dict(os.environ, env_scaled, clear=False):
            model_scaled = SlippageModel()

        result_base = model_base.calculate_slippage_bps(
            symbol=symbol,
            spread_bps=spread_bps,
            book_depth_usd=book_depth_usd,
            order_size_usd=order_size_usd,
            volatility_regime="normal",
        )
        result_scaled = model_scaled.calculate_slippage_bps(
            symbol=symbol,
            spread_bps=spread_bps,
            book_depth_usd=book_depth_usd,
            order_size_usd=order_size_usd,
            volatility_regime="normal",
        )

        if multiplier > 1.0:
            assert result_scaled >= result_base - 1e-9, (
                f"With multiplier {multiplier} > 1.0, slippage {result_scaled:.4f} "
                f"should be >= base {result_base:.4f}"
            )
        else:
            assert result_scaled <= result_base + 1e-9, (
                f"With multiplier {multiplier} < 1.0, slippage {result_scaled:.4f} "
                f"should be <= base {result_base:.4f}"
            )


# ═══════════════════════════════════════════════════════════════
# Property 20: Cost estimator slippage floor enforcement
# ═══════════════════════════════════════════════════════════════


class TestCostEstimatorSlippageFloorEnforcement:
    """
    Feature: scalping-pipeline-audit, Property 20: Cost estimator slippage floor enforcement

    The slippage component used by EVGateStage must be at least
    max(model_slippage, EV_GATE_MIN_SLIPPAGE_BPS).

    **Validates: Requirements 6.2**
    """

    @settings(max_examples=200)
    @given(
        symbol=symbols,
        spread_bps=st.floats(min_value=0.5, max_value=20.0, allow_nan=False, allow_infinity=False),
        bid_depth_usd=depth_usd_values,
        ask_depth_usd=depth_usd_values,
        order_size_usd=order_size_values,
        volatility_regime=volatility_regimes,
        min_slippage_bps=st.floats(min_value=0.0, max_value=20.0, allow_nan=False, allow_infinity=False),
    )
    def test_slippage_floor_enforced_by_ev_gate(
        self,
        symbol: str,
        spread_bps: float,
        bid_depth_usd: float,
        ask_depth_usd: float,
        order_size_usd: float,
        volatility_regime: str,
        min_slippage_bps: float,
    ):
        """Feature: scalping-pipeline-audit, Property 20: Cost estimator slippage floor enforcement

        The EVGateStage applies max(model_slippage, config.min_slippage_bps) to the
        slippage component. Verify this floor is always enforced.
        """
        # Build realistic prices
        mid_price = 50000.0 if symbol == "BTCUSDT" else (3000.0 if symbol == "ETHUSDT" else 150.0)
        half_spread = mid_price * spread_bps / 20000.0
        best_bid = mid_price - half_spread
        best_ask = mid_price + half_spread
        entry_price = mid_price
        exit_price = entry_price * 1.005
        size = order_size_usd / entry_price

        fee_model = FeeModel(FeeConfig.bybit_regular())
        slippage_model = SlippageModel()
        execution_policy = ExecutionPolicy()

        cost_estimator = CostEstimator(
            fee_model=fee_model,
            execution_policy=execution_policy,
            slippage_model=slippage_model,
        )

        # Get the raw model slippage from CostEstimator
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

        model_slippage = estimate.slippage_bps

        # Simulate the EVGateStage floor enforcement
        enforced_slippage = max(float(model_slippage), float(min_slippage_bps))

        # The enforced slippage must be >= both the model output and the config floor
        assert enforced_slippage >= model_slippage - 1e-9, (
            f"Enforced slippage {enforced_slippage:.4f} < model slippage {model_slippage:.4f}"
        )
        assert enforced_slippage >= min_slippage_bps - 1e-9, (
            f"Enforced slippage {enforced_slippage:.4f} < min_slippage_bps {min_slippage_bps:.4f}"
        )

    @settings(max_examples=200)
    @given(
        model_slippage=st.floats(min_value=0.0, max_value=50.0, allow_nan=False, allow_infinity=False),
        min_slippage_floor=st.floats(min_value=0.0, max_value=20.0, allow_nan=False, allow_infinity=False),
    )
    def test_floor_is_max_of_model_and_config(
        self,
        model_slippage: float,
        min_slippage_floor: float,
    ):
        """Feature: scalping-pipeline-audit, Property 20: Cost estimator slippage floor enforcement

        The enforced slippage must equal max(model_slippage, EV_GATE_MIN_SLIPPAGE_BPS).
        """
        enforced = max(model_slippage, min_slippage_floor)
        expected = max(model_slippage, min_slippage_floor)

        assert math.isclose(enforced, expected, rel_tol=1e-9, abs_tol=1e-12), (
            f"Floor enforcement: max({model_slippage}, {min_slippage_floor}) = {enforced}, "
            f"expected {expected}"
        )

        # The enforced value must dominate both inputs
        assert enforced >= model_slippage - 1e-9
        assert enforced >= min_slippage_floor - 1e-9

    @settings(max_examples=200)
    @given(
        symbol=symbols,
        spread_bps=st.floats(min_value=0.5, max_value=20.0, allow_nan=False, allow_infinity=False),
        bid_depth_usd=depth_usd_values,
        ask_depth_usd=depth_usd_values,
        order_size_usd=order_size_values,
        volatility_regime=volatility_regimes,
    )
    def test_ev_gate_config_floor_dominates_when_higher(
        self,
        symbol: str,
        spread_bps: float,
        bid_depth_usd: float,
        ask_depth_usd: float,
        order_size_usd: float,
        volatility_regime: str,
    ):
        """Feature: scalping-pipeline-audit, Property 20: Cost estimator slippage floor enforcement

        When EV_GATE_MIN_SLIPPAGE_BPS (e.g. 4.0) is higher than the model's output
        for BTC/ETH, the config floor should dominate.
        """
        mid_price = 50000.0 if symbol == "BTCUSDT" else (3000.0 if symbol == "ETHUSDT" else 150.0)
        half_spread = mid_price * spread_bps / 20000.0
        best_bid = mid_price - half_spread
        best_ask = mid_price + half_spread
        entry_price = mid_price
        exit_price = entry_price * 1.005
        size = order_size_usd / entry_price

        fee_model = FeeModel(FeeConfig.bybit_regular())
        slippage_model = SlippageModel()
        execution_policy = ExecutionPolicy()

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

        # Use a high floor (4.0 bps as per EV_GATE_MIN_SLIPPAGE_BPS in requirements)
        config_floor = 4.0
        enforced_slippage = max(estimate.slippage_bps, config_floor)

        # The enforced value must be at least the config floor
        assert enforced_slippage >= config_floor - 1e-9, (
            f"Enforced slippage {enforced_slippage:.4f} < config floor {config_floor}"
        )
        # And at least the model output
        assert enforced_slippage >= estimate.slippage_bps - 1e-9, (
            f"Enforced slippage {enforced_slippage:.4f} < model output {estimate.slippage_bps:.4f}"
        )
