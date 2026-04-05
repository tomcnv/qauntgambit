"""
Tests for EVGate Phase 3 Integration (Cost Model Integration).

This module tests the integration of ExecutionPolicy and SlippageModel
into EVGate's cost estimation.

Phase 3 Requirements:
- CostEstimator uses ExecutionPolicy for execution assumptions
- CostEstimator uses SlippageModel for adaptive slippage
- CostEstimator uses calculate_adverse_selection_bps for adverse selection
- EVGate calculates C = total_cost_bps / SL_distance_bps correctly
- EVGate logs all cost components
"""

import pytest
import time
from unittest.mock import Mock, patch
from dataclasses import asdict

from quantgambit.signals.stages.ev_gate import (
    EVGateStage,
    EVGateConfig,
    CostEstimator,
    EVGateResult,
    calculate_L_G_R,
    calculate_cost_ratio,
    calculate_ev,
)
from quantgambit.signals.pipeline import StageContext, StageResult
from quantgambit.execution.execution_policy import ExecutionPolicy, ExecutionPlan
from quantgambit.risk.slippage_model import SlippageModel
from quantgambit.risk.fee_model import FeeModel, FeeConfig


def _add_timestamp(market_context: dict) -> dict:
    """Add timestamp to market_context if not present."""
    if "timestamp_ms" not in market_context and "book_timestamp_ms" not in market_context:
        market_context["timestamp_ms"] = time.time() * 1000
    return market_context


# =============================================================================
# CostEstimator Integration Tests
# =============================================================================

def test_cost_estimator_uses_execution_policy():
    """Test that CostEstimator uses ExecutionPolicy for fee calculation."""
    fee_model = FeeModel(FeeConfig.okx_regular())
    execution_policy = ExecutionPolicy()
    slippage_model = SlippageModel()
    
    cost_estimator = CostEstimator(
        fee_model=fee_model,
        execution_policy=execution_policy,
        slippage_model=slippage_model,
    )
    
    # Mean reversion: taker entry (p_maker=0.1), maker exit (p_maker=0.6)
    cost = cost_estimator.estimate(
        symbol="BTCUSDT",
        strategy_id="mean_reversion_fade",
        setup_type="mean_reversion",
        entry_price=50000.0,
        exit_price=50500.0,
        size=0.1,
        best_bid=49999.0,
        best_ask=50001.0,
        order_size_usd=5000.0,
        volatility_regime="normal",
        spread_percentile=50.0,
        bid_depth_usd=100000.0,
        ask_depth_usd=100000.0,
        hold_time_expected_sec=600.0,
    )
    
    # Verify cost components are present
    assert cost.fee_bps > 0, "Fee should be positive"
    assert cost.spread_bps > 0, "Spread should be positive"
    assert cost.slippage_bps >= 0, "Slippage should be non-negative"
    assert cost.adverse_selection_bps > 0, "Adverse selection should be positive"
    assert cost.total_bps == cost.fee_bps + cost.spread_bps + cost.slippage_bps + cost.adverse_selection_bps
    
    # Fee should be between maker-maker (8 bps) and taker-taker (12 bps)
    # Mean reversion: ~10.6 bps (0.9*6 + 0.1*4 entry + 0.4*6 + 0.6*4 exit)
    assert 8.0 <= cost.fee_bps <= 12.0, f"Fee {cost.fee_bps} should be in [8, 12] bps range"


def test_cost_estimator_uses_slippage_model():
    """Test that CostEstimator uses SlippageModel for adaptive slippage."""
    fee_model = FeeModel(FeeConfig.okx_regular())
    execution_policy = ExecutionPolicy()
    slippage_model = SlippageModel()
    
    cost_estimator = CostEstimator(
        fee_model=fee_model,
        execution_policy=execution_policy,
        slippage_model=slippage_model,
    )
    
    # Test with high volatility - should have higher slippage
    cost_high_vol = cost_estimator.estimate(
        symbol="BTCUSDT",
        strategy_id="mean_reversion_fade",
        setup_type="mean_reversion",
        entry_price=50000.0,
        exit_price=50500.0,
        size=0.1,
        best_bid=49999.0,
        best_ask=50001.0,
        order_size_usd=5000.0,
        volatility_regime="high",
        spread_percentile=50.0,
        bid_depth_usd=100000.0,
        ask_depth_usd=100000.0,
        hold_time_expected_sec=600.0,
    )
    
    # Test with low volatility - should have lower slippage
    cost_low_vol = cost_estimator.estimate(
        symbol="BTCUSDT",
        strategy_id="mean_reversion_fade",
        setup_type="mean_reversion",
        entry_price=50000.0,
        exit_price=50500.0,
        size=0.1,
        best_bid=49999.0,
        best_ask=50001.0,
        order_size_usd=5000.0,
        volatility_regime="low",
        spread_percentile=50.0,
        bid_depth_usd=100000.0,
        ask_depth_usd=100000.0,
        hold_time_expected_sec=600.0,
    )
    
    # High volatility should have higher slippage
    assert cost_high_vol.slippage_bps > cost_low_vol.slippage_bps, \
        f"High vol slippage {cost_high_vol.slippage_bps} should be > low vol {cost_low_vol.slippage_bps}"


def test_cost_estimator_includes_adverse_selection():
    """Test that CostEstimator includes adverse selection costs."""
    fee_model = FeeModel(FeeConfig.okx_regular())
    execution_policy = ExecutionPolicy()
    slippage_model = SlippageModel()
    
    cost_estimator = CostEstimator(
        fee_model=fee_model,
        execution_policy=execution_policy,
        slippage_model=slippage_model,
    )
    
    cost = cost_estimator.estimate(
        symbol="BTCUSDT",
        strategy_id="mean_reversion_fade",
        setup_type="mean_reversion",
        entry_price=50000.0,
        exit_price=50500.0,
        size=0.1,
        best_bid=49999.0,
        best_ask=50001.0,
        order_size_usd=5000.0,
        volatility_regime="normal",
        spread_percentile=50.0,
        bid_depth_usd=100000.0,
        ask_depth_usd=100000.0,
        hold_time_expected_sec=600.0,
    )
    
    # Adverse selection should be positive
    assert cost.adverse_selection_bps > 0, "Adverse selection should be positive"
    
    # For BTC in normal volatility, should be around 1.0-1.5 bps
    assert 0.5 <= cost.adverse_selection_bps <= 3.0, \
        f"Adverse selection {cost.adverse_selection_bps} should be in reasonable range"


def test_cost_estimator_different_strategies():
    """Test that different strategies get different execution plans and costs."""
    fee_model = FeeModel(FeeConfig.okx_regular())
    execution_policy = ExecutionPolicy()
    slippage_model = SlippageModel()
    
    cost_estimator = CostEstimator(
        fee_model=fee_model,
        execution_policy=execution_policy,
        slippage_model=slippage_model,
    )
    
    # Mean reversion: patient entry, limit exit
    cost_mr = cost_estimator.estimate(
        symbol="BTCUSDT",
        strategy_id="mean_reversion_fade",
        setup_type="mean_reversion",
        entry_price=50000.0,
        exit_price=50500.0,
        size=0.1,
        best_bid=49999.0,
        best_ask=50001.0,
        order_size_usd=5000.0,
        volatility_regime="normal",
        spread_percentile=50.0,
        bid_depth_usd=100000.0,
        ask_depth_usd=100000.0,
        hold_time_expected_sec=600.0,
    )
    
    # Breakout: immediate entry and exit (all taker)
    cost_bo = cost_estimator.estimate(
        symbol="BTCUSDT",
        strategy_id="breakout_momentum",
        setup_type="breakout",
        entry_price=50000.0,
        exit_price=50500.0,
        size=0.1,
        best_bid=49999.0,
        best_ask=50001.0,
        order_size_usd=5000.0,
        volatility_regime="normal",
        spread_percentile=50.0,
        bid_depth_usd=100000.0,
        ask_depth_usd=100000.0,
        hold_time_expected_sec=1200.0,
    )
    
    # Breakout should have higher fees (more taker fills)
    assert cost_bo.fee_bps > cost_mr.fee_bps, \
        f"Breakout fees {cost_bo.fee_bps} should be > mean reversion {cost_mr.fee_bps}"


# =============================================================================
# EVGate Integration Tests
# =============================================================================

def test_ev_gate_calculates_c_correctly():
    """Test that EVGate calculates C = total_cost_bps / SL_distance_bps correctly."""
    config = EVGateConfig(mode="enforce", ev_min=0.02)
    stage = EVGateStage(config=config)
    
    # Create test context
    ctx = StageContext(
        symbol="BTCUSDT",
        signal={
            "entry_price": 50000.0,
            "stop_loss": 49500.0,  # 100 bps below entry
            "take_profit": 51000.0,  # 200 bps above entry
            "side": "long",
            "strategy_id": "mean_reversion_fade",
            "meta_reason": "mean_reversion_poc_target",
            "size": 0.1,
        },
        data={
            "market_context": _add_timestamp({
                "best_bid": 49999.0,
                "best_ask": 50001.0,
                "spread_percentile": 50.0,
                "volatility_regime": "normal",
                "bid_depth_usd": 100000.0,
                "ask_depth_usd": 100000.0,
            }),
            "features": {},
            "prediction": {
                "confidence": 0.65,
            },
        },
    )
    
    # Evaluate
    result = stage._evaluate(ctx, ctx.signal)
    
    # Verify C calculation
    # L = 100 bps (stop distance)
    # Total cost should be ~13-15 bps (10.6 fee + 0.4 spread + 1.2 slippage + 1.0 adverse)
    # C = total_cost / L = ~13-15 / 100 = 0.13-0.15
    assert result.L_bps == pytest.approx(100.0, abs=1.0), f"L should be ~100 bps, got {result.L_bps}"
    assert 12.0 <= result.total_cost_bps <= 16.0, f"Total cost should be 12-16 bps, got {result.total_cost_bps}"
    assert 0.12 <= result.C <= 0.16, f"C should be 0.12-0.16, got {result.C}"
    
    # Verify C = total_cost_bps / L_bps
    expected_C = result.total_cost_bps / result.L_bps
    assert result.C == pytest.approx(expected_C, abs=0.001), \
        f"C {result.C} should equal total_cost/L {expected_C}"


def test_ev_gate_logs_all_cost_components():
    """Test that EVGate logs all cost components in decisions."""
    config = EVGateConfig(mode="enforce", ev_min=0.02)
    stage = EVGateStage(config=config)
    
    # Create test context
    ctx = StageContext(
        symbol="BTCUSDT",
        signal={
            "entry_price": 50000.0,
            "stop_loss": 49500.0,
            "take_profit": 51000.0,
            "side": "long",
            "strategy_id": "mean_reversion_fade",
            "meta_reason": "mean_reversion_poc_target",
            "size": 0.1,
        },
        data={
            "market_context": _add_timestamp({
                "best_bid": 49999.0,
                "best_ask": 50001.0,
                "spread_percentile": 50.0,
                "volatility_regime": "normal",
                "bid_depth_usd": 100000.0,
                "ask_depth_usd": 100000.0,
            }),
            "features": {},
            "prediction": {
                "confidence": 0.65,
            },
        },
    )
    
    # Evaluate
    result = stage._evaluate(ctx, ctx.signal)
    
    # Verify all cost components are present
    assert result.fee_bps > 0, "Fee should be logged"
    assert result.spread_bps > 0, "Spread should be logged"
    assert result.slippage_bps >= 0, "Slippage should be logged"
    assert result.adverse_selection_bps > 0, "Adverse selection should be logged"
    assert result.total_cost_bps > 0, "Total cost should be logged"
    
    # Verify total equals sum of components
    expected_total = result.fee_bps + result.spread_bps + result.slippage_bps + result.adverse_selection_bps
    assert result.total_cost_bps == pytest.approx(expected_total, abs=0.01), \
        f"Total cost {result.total_cost_bps} should equal sum of components {expected_total}"


def test_ev_gate_accepts_profitable_signal():
    """Test that EVGate accepts a signal with good EV after Phase 3 costs."""
    config = EVGateConfig(mode="enforce", ev_min=0.02)
    stage = EVGateStage(config=config)
    
    # Create test context with high probability and good R
    ctx = StageContext(
        symbol="BTCUSDT",
        signal={
            "entry_price": 50000.0,
            "stop_loss": 49500.0,  # 100 bps below entry
            "take_profit": 51500.0,  # 300 bps above entry (R=3)
            "side": "long",
            "strategy_id": "mean_reversion_fade",
            "meta_reason": "mean_reversion_poc_target",
            "size": 0.1,
        },
        data={
            "market_context": _add_timestamp({
                "best_bid": 49999.0,
                "best_ask": 50001.0,
                "spread_percentile": 50.0,
                "volatility_regime": "normal",
                "bid_depth_usd": 100000.0,
                "ask_depth_usd": 100000.0,
            }),
            "features": {},
            "prediction": {
                "confidence": 0.65,  # 65% win probability
            },
        },
    )
    
    # Evaluate
    result = stage._evaluate(ctx, ctx.signal)
    
    # With R=3, C~0.13, p=0.65:
    # EV = 0.65*3 - 0.35*1 - 0.13 = 1.95 - 0.35 - 0.13 = 1.47 >> 0.02
    assert result.decision == "ACCEPT", f"Should accept profitable signal, got {result.reject_reason}"
    assert result.R == pytest.approx(3.0, abs=0.1), f"R should be ~3.0, got {result.R}"
    assert result.EV > 0.02, f"EV {result.EV} should be > 0.02"


def test_ev_gate_rejects_unprofitable_signal():
    """Test that EVGate rejects a signal with poor EV after Phase 3 costs."""
    config = EVGateConfig(mode="enforce", ev_min=0.02)
    stage = EVGateStage(config=config)
    
    # Create test context with low probability and poor R
    ctx = StageContext(
        symbol="BTCUSDT",
        signal={
            "entry_price": 50000.0,
            "stop_loss": 49500.0,  # 100 bps below entry
            "take_profit": 50500.0,  # 100 bps above entry (R=1)
            "side": "long",
            "strategy_id": "mean_reversion_fade",
            "meta_reason": "mean_reversion_poc_target",
            "size": 0.1,
        },
        data={
            "market_context": _add_timestamp({
                "best_bid": 49999.0,
                "best_ask": 50001.0,
                "spread_percentile": 50.0,
                "volatility_regime": "normal",
                "bid_depth_usd": 100000.0,
                "ask_depth_usd": 100000.0,
            }),
            "features": {},
            "prediction": {
                "confidence": 0.50,  # 50% win probability
            },
        },
    )
    
    # Evaluate
    result = stage._evaluate(ctx, ctx.signal)
    
    # With R=1, C~0.13, p=0.50:
    # EV = 0.50*1 - 0.50*1 - 0.13 = 0.50 - 0.50 - 0.13 = -0.13 < 0.02
    assert result.decision == "REJECT", "Should reject unprofitable signal"
    assert result.R == pytest.approx(1.0, abs=0.1), f"R should be ~1.0, got {result.R}"
    assert result.EV < 0.02, f"EV {result.EV} should be < 0.02"


def test_ev_gate_cost_increases_with_volatility():
    """Test that costs increase with volatility regime."""
    config = EVGateConfig(mode="enforce", ev_min=0.02)
    stage = EVGateStage(config=config)
    
    # Test with low volatility
    ctx_low = StageContext(
        symbol="BTCUSDT",
        signal={
            "entry_price": 50000.0,
            "stop_loss": 49500.0,
            "take_profit": 51000.0,
            "side": "long",
            "strategy_id": "mean_reversion_fade",
            "meta_reason": "mean_reversion_poc_target",
            "size": 0.1,
        },
        data={
            "market_context": _add_timestamp({
                "best_bid": 49999.0,
                "best_ask": 50001.0,
                "spread_percentile": 50.0,
                "volatility_regime": "low",
                "bid_depth_usd": 100000.0,
                "ask_depth_usd": 100000.0,
            }),
            "features": {},
            "prediction": {"confidence": 0.65},
        },
    )
    
    # Test with high volatility
    ctx_high = StageContext(
        symbol="BTCUSDT",
        signal={
            "entry_price": 50000.0,
            "stop_loss": 49500.0,
            "take_profit": 51000.0,
            "side": "long",
            "strategy_id": "mean_reversion_fade",
            "meta_reason": "mean_reversion_poc_target",
            "size": 0.1,
        },
        data={
            "market_context": _add_timestamp({
                "best_bid": 49999.0,
                "best_ask": 50001.0,
                "spread_percentile": 50.0,
                "volatility_regime": "high",
                "bid_depth_usd": 100000.0,
                "ask_depth_usd": 100000.0,
            }),
            "features": {},
            "prediction": {"confidence": 0.65},
        },
    )
    
    result_low = stage._evaluate(ctx_low, ctx_low.signal)
    result_high = stage._evaluate(ctx_high, ctx_high.signal)
    
    # High volatility should have higher total costs
    assert result_high.total_cost_bps > result_low.total_cost_bps, \
        f"High vol costs {result_high.total_cost_bps} should be > low vol {result_low.total_cost_bps}"
    
    # Specifically, slippage and adverse selection should be higher
    assert result_high.slippage_bps > result_low.slippage_bps, \
        "High vol slippage should be higher"
    assert result_high.adverse_selection_bps > result_low.adverse_selection_bps, \
        "High vol adverse selection should be higher"


# =============================================================================
# Helper Method Tests
# =============================================================================

def test_extract_setup_type():
    """Test setup type extraction from strategy_id and meta_reason."""
    stage = EVGateStage()
    
    # Test strategy_id extraction
    assert stage._extract_setup_type("mean_reversion_fade", "") == "mean_reversion"
    assert stage._extract_setup_type("breakout_momentum", "") == "breakout"
    assert stage._extract_setup_type("trend_pullback", "") == "trend_pullback"
    assert stage._extract_setup_type("low_vol_grind", "") == "low_vol_grind"
    
    # Test meta_reason extraction
    assert stage._extract_setup_type("unknown", "mean_reversion_poc_target") == "mean_reversion"
    assert stage._extract_setup_type("unknown", "breakout_volume_surge") == "breakout"
    
    # Test default
    assert stage._extract_setup_type("unknown", "unknown") == "mean_reversion"


def test_estimate_hold_time():
    """Test hold time estimation for different strategies."""
    stage = EVGateStage()
    
    # Mean reversion: quick (10 min)
    assert stage._estimate_hold_time("mean_reversion_fade", "mean_reversion") == 600.0
    
    # Breakout: medium (20 min)
    assert stage._estimate_hold_time("breakout_momentum", "breakout") == 1200.0
    
    # Trend pullback: longer (40 min)
    assert stage._estimate_hold_time("trend_pullback", "trend_pullback") == 2400.0
    
    # Low vol grind: very long (2 hours)
    assert stage._estimate_hold_time("low_vol_grind", "low_vol_grind") == 7200.0
    
    # Default: 5 min
    assert stage._estimate_hold_time("unknown", "unknown") == 300.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
