"""
Phase 4 Validation Tests - Cost Model Validation

This module validates the Phase 3 cost model against expected distributions
and ensures costs are in reasonable ranges.

Requirements from V2 Proposal Section 10 (Testing Plan):
1. Cost distribution analysis (P50, P75, P90)
2. Decision delta analysis (old vs new)
3. Golden tests for regression prevention
4. Validate costs are in reasonable ranges (8-20 bps typical)
"""

import pytest
from quantgambit.signals.stages.ev_gate import CostEstimator, EVGateConfig
from quantgambit.execution.execution_policy import ExecutionPolicy
from quantgambit.risk.slippage_model import SlippageModel
from quantgambit.risk.fee_model import FeeModel, FeeConfig


# =============================================================================
# Golden Tests - Freeze Known-Good Cost Calculations
# =============================================================================

GOLDEN_TESTS = [
    {
        "name": "BTC Mean Reversion Normal Volatility",
        "symbol": "BTCUSDT",
        "strategy_id": "mean_reversion_fade",
        "setup_type": "mean_reversion",
        "entry_price": 50000.0,
        "exit_price": 50500.0,
        "size": 0.1,
        "best_bid": 49999.0,
        "best_ask": 50001.0,
        "order_size_usd": 5000.0,
        "volatility_regime": "normal",
        "spread_percentile": 50.0,
        "bid_depth_usd": 100000.0,
        "ask_depth_usd": 100000.0,
        "hold_time_expected_sec": 600.0,
        "expected_total_bps": 13.2,  # 10.6 fee + 0.4 spread + 1.2 slippage + 1.0 adverse
        "tolerance_bps": 0.5,
    },
    {
        "name": "BTC Breakout Normal Volatility",
        "symbol": "BTCUSDT",
        "strategy_id": "breakout_momentum",
        "setup_type": "breakout",
        "entry_price": 50000.0,
        "exit_price": 51000.0,
        "size": 0.1,
        "best_bid": 49999.0,
        "best_ask": 50001.0,
        "order_size_usd": 5000.0,
        "volatility_regime": "normal",
        "spread_percentile": 50.0,
        "bid_depth_usd": 100000.0,
        "ask_depth_usd": 100000.0,
        "hold_time_expected_sec": 1200.0,
        "expected_total_bps": 14.6,  # 12.0 fee + 0.4 spread + 1.2 slippage + 1.0 adverse
        "tolerance_bps": 0.5,
    },
    {
        "name": "ETH Mean Reversion Low Volatility",
        "symbol": "ETHUSDT",
        "strategy_id": "mean_reversion_fade",
        "setup_type": "mean_reversion",
        "entry_price": 3000.0,
        "exit_price": 3030.0,
        "size": 1.0,
        "best_bid": 2999.0,
        "best_ask": 3001.0,
        "order_size_usd": 3000.0,
        "volatility_regime": "low",
        "spread_percentile": 30.0,
        "bid_depth_usd": 50000.0,
        "ask_depth_usd": 50000.0,
        "hold_time_expected_sec": 600.0,
        "expected_total_bps": 22.6,  # 10.6 fee + 6.7 spread + 4.1 slippage + 1.2 adverse
        "tolerance_bps": 1.0,
    },
    {
        "name": "SOL Mean Reversion High Volatility",
        "symbol": "SOLUSDT",
        "strategy_id": "mean_reversion_fade",
        "setup_type": "mean_reversion",
        "entry_price": 100.0,
        "exit_price": 102.0,
        "size": 10.0,
        "best_bid": 99.9,
        "best_ask": 100.1,
        "order_size_usd": 1000.0,
        "volatility_regime": "high",
        "spread_percentile": 70.0,
        "bid_depth_usd": 20000.0,
        "ask_depth_usd": 20000.0,
        "hold_time_expected_sec": 600.0,
        "expected_total_bps": 88.3,  # 10.7 fee + 20.0 spread + 54.0 slippage + 3.6 adverse
        "tolerance_bps": 2.0,
    },
]


@pytest.mark.parametrize("test_case", GOLDEN_TESTS, ids=lambda t: t["name"])
def test_golden_cost_calculation(test_case):
    """
    Golden Test: Verify cost calculations match expected values.
    
    These tests freeze known-good cost calculations to prevent regression.
    If these tests fail, it indicates the cost model has changed and needs review.
    """
    fee_model = FeeModel(FeeConfig.okx_regular())
    execution_policy = ExecutionPolicy()
    slippage_model = SlippageModel()
    
    cost_estimator = CostEstimator(
        fee_model=fee_model,
        execution_policy=execution_policy,
        slippage_model=slippage_model,
    )
    
    cost = cost_estimator.estimate(
        symbol=test_case["symbol"],
        strategy_id=test_case["strategy_id"],
        setup_type=test_case["setup_type"],
        entry_price=test_case["entry_price"],
        exit_price=test_case["exit_price"],
        size=test_case["size"],
        best_bid=test_case["best_bid"],
        best_ask=test_case["best_ask"],
        order_size_usd=test_case["order_size_usd"],
        volatility_regime=test_case["volatility_regime"],
        spread_percentile=test_case["spread_percentile"],
        bid_depth_usd=test_case["bid_depth_usd"],
        ask_depth_usd=test_case["ask_depth_usd"],
        hold_time_expected_sec=test_case["hold_time_expected_sec"],
    )
    
    # Verify total cost is within tolerance
    assert abs(cost.total_bps - test_case["expected_total_bps"]) <= test_case["tolerance_bps"], \
        f"{test_case['name']}: Expected {test_case['expected_total_bps']} bps, got {cost.total_bps} bps"
    
    # Verify all components are positive
    assert cost.fee_bps > 0, "Fee should be positive"
    assert cost.spread_bps >= 0, "Spread should be non-negative"
    assert cost.slippage_bps >= 0, "Slippage should be non-negative"
    assert cost.adverse_selection_bps > 0, "Adverse selection should be positive"
    
    # Verify total equals sum of components
    expected_total = cost.fee_bps + cost.spread_bps + cost.slippage_bps + cost.adverse_selection_bps
    assert abs(cost.total_bps - expected_total) < 0.01, \
        f"Total {cost.total_bps} should equal sum of components {expected_total}"


# =============================================================================
# Cost Distribution Tests
# =============================================================================

def test_cost_distribution_reasonable_ranges():
    """
    Test that costs are in reasonable ranges across various scenarios.
    
    Requirement: Costs should typically be 10-20 bps for normal conditions.
    """
    fee_model = FeeModel(FeeConfig.okx_regular())
    execution_policy = ExecutionPolicy()
    slippage_model = SlippageModel()
    
    cost_estimator = CostEstimator(
        fee_model=fee_model,
        execution_policy=execution_policy,
        slippage_model=slippage_model,
    )
    
    # Test various scenarios
    scenarios = [
        # (symbol, strategy, volatility, expected_min, expected_max)
        ("BTCUSDT", "mean_reversion", "low", 11.0, 14.0),
        ("BTCUSDT", "mean_reversion", "normal", 12.0, 15.0),
        ("BTCUSDT", "mean_reversion", "high", 14.0, 18.0),
        ("BTCUSDT", "breakout", "normal", 13.0, 16.0),
        ("ETHUSDT", "mean_reversion", "normal", 20.0, 26.0),  # Higher due to wider spread
        ("SOLUSDT", "mean_reversion", "normal", 60.0, 75.0),  # Much higher due to wide spread + high slippage
    ]
    
    for symbol, strategy, volatility, min_bps, max_bps in scenarios:
        cost = cost_estimator.estimate(
            symbol=symbol,
            strategy_id=f"{strategy}_fade",
            setup_type=strategy,
            entry_price=50000.0 if symbol == "BTCUSDT" else 3000.0 if symbol == "ETHUSDT" else 100.0,
            exit_price=50500.0 if symbol == "BTCUSDT" else 3030.0 if symbol == "ETHUSDT" else 102.0,
            size=0.1,
            best_bid=49999.0 if symbol == "BTCUSDT" else 2999.0 if symbol == "ETHUSDT" else 99.9,
            best_ask=50001.0 if symbol == "BTCUSDT" else 3001.0 if symbol == "ETHUSDT" else 100.1,
            order_size_usd=5000.0,
            volatility_regime=volatility,
            spread_percentile=50.0,
            bid_depth_usd=100000.0,
            ask_depth_usd=100000.0,
            hold_time_expected_sec=600.0,
        )
        
        assert min_bps <= cost.total_bps <= max_bps, \
            f"{symbol} {strategy} {volatility}: Cost {cost.total_bps} bps not in expected range [{min_bps}, {max_bps}]"


def test_cost_percentiles():
    """
    Test cost percentiles (P50, P75, P90) across many scenarios.
    
    Requirement: Validate cost distributions are reasonable.
    """
    fee_model = FeeModel(FeeConfig.okx_regular())
    execution_policy = ExecutionPolicy()
    slippage_model = SlippageModel()
    
    cost_estimator = CostEstimator(
        fee_model=fee_model,
        execution_policy=execution_policy,
        slippage_model=slippage_model,
    )
    
    # Generate costs for many scenarios
    costs = []
    
    symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    strategies = ["mean_reversion", "breakout"]
    volatilities = ["low", "normal", "high"]
    
    for symbol in symbols:
        for strategy in strategies:
            for volatility in volatilities:
                cost = cost_estimator.estimate(
                    symbol=symbol,
                    strategy_id=f"{strategy}_fade",
                    setup_type=strategy,
                    entry_price=50000.0 if symbol == "BTCUSDT" else 3000.0 if symbol == "ETHUSDT" else 100.0,
                    exit_price=50500.0 if symbol == "BTCUSDT" else 3030.0 if symbol == "ETHUSDT" else 102.0,
                    size=0.1,
                    best_bid=49999.0 if symbol == "BTCUSDT" else 2999.0 if symbol == "ETHUSDT" else 99.9,
                    best_ask=50001.0 if symbol == "BTCUSDT" else 3001.0 if symbol == "ETHUSDT" else 100.1,
                    order_size_usd=5000.0,
                    volatility_regime=volatility,
                    spread_percentile=50.0,
                    bid_depth_usd=100000.0,
                    ask_depth_usd=100000.0,
                    hold_time_expected_sec=600.0,
                )
                costs.append(cost.total_bps)
    
    # Calculate percentiles
    costs_sorted = sorted(costs)
    n = len(costs_sorted)
    p50 = costs_sorted[int(n * 0.50)]
    p75 = costs_sorted[int(n * 0.75)]
    p90 = costs_sorted[int(n * 0.90)]
    
    print(f"\nCost Distribution:")
    print(f"  P50: {p50:.1f} bps")
    print(f"  P75: {p75:.1f} bps")
    print(f"  P90: {p90:.1f} bps")
    
    # Verify percentiles are in reasonable ranges
    assert 12.0 <= p50 <= 30.0, f"P50 {p50} should be in [12, 30] bps"
    assert 20.0 <= p75 <= 70.0, f"P75 {p75} should be in [20, 70] bps"
    assert 30.0 <= p90 <= 100.0, f"P90 {p90} should be in [30, 100] bps"


# =============================================================================
# Component Contribution Tests
# =============================================================================

def test_fee_component_dominates():
    """Test that fees are typically the largest cost component."""
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
    
    # Fees should be the largest component in normal conditions
    assert cost.fee_bps > cost.spread_bps, "Fees should be > spread"
    assert cost.fee_bps > cost.slippage_bps, "Fees should be > slippage"
    assert cost.fee_bps > cost.adverse_selection_bps, "Fees should be > adverse selection"
    
    # Fees should be 70-85% of total cost
    fee_percentage = cost.fee_bps / cost.total_bps
    assert 0.70 <= fee_percentage <= 0.85, \
        f"Fees should be 70-85% of total, got {fee_percentage:.1%}"


def test_cost_components_sum_to_total():
    """Test that cost components always sum to total."""
    fee_model = FeeModel(FeeConfig.okx_regular())
    execution_policy = ExecutionPolicy()
    slippage_model = SlippageModel()
    
    cost_estimator = CostEstimator(
        fee_model=fee_model,
        execution_policy=execution_policy,
        slippage_model=slippage_model,
    )
    
    # Test many scenarios
    for _ in range(20):
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
        
        expected_total = cost.fee_bps + cost.spread_bps + cost.slippage_bps + cost.adverse_selection_bps
        assert abs(cost.total_bps - expected_total) < 0.01, \
            f"Total {cost.total_bps} should equal sum {expected_total}"


# =============================================================================
# Volatility Sensitivity Tests
# =============================================================================

def test_costs_increase_with_volatility():
    """Test that costs increase monotonically with volatility."""
    fee_model = FeeModel(FeeConfig.okx_regular())
    execution_policy = ExecutionPolicy()
    slippage_model = SlippageModel()
    
    cost_estimator = CostEstimator(
        fee_model=fee_model,
        execution_policy=execution_policy,
        slippage_model=slippage_model,
    )
    
    volatilities = ["low", "normal", "high", "extreme"]
    costs = []
    
    for vol in volatilities:
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
            volatility_regime=vol,
            spread_percentile=50.0,
            bid_depth_usd=100000.0,
            ask_depth_usd=100000.0,
            hold_time_expected_sec=600.0,
        )
        costs.append(cost.total_bps)
    
    # Verify monotonic increase
    for i in range(len(costs) - 1):
        assert costs[i] < costs[i + 1], \
            f"Cost should increase with volatility: {volatilities[i]} ({costs[i]}) < {volatilities[i+1]} ({costs[i+1]})"


def test_extreme_volatility_costs():
    """Test that extreme volatility produces significantly higher costs."""
    fee_model = FeeModel(FeeConfig.okx_regular())
    execution_policy = ExecutionPolicy()
    slippage_model = SlippageModel()
    
    cost_estimator = CostEstimator(
        fee_model=fee_model,
        execution_policy=execution_policy,
        slippage_model=slippage_model,
    )
    
    cost_normal = cost_estimator.estimate(
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
    
    cost_extreme = cost_estimator.estimate(
        symbol="BTCUSDT",
        strategy_id="mean_reversion_fade",
        setup_type="mean_reversion",
        entry_price=50000.0,
        exit_price=50500.0,
        size=0.1,
        best_bid=49999.0,
        best_ask=50001.0,
        order_size_usd=5000.0,
        volatility_regime="extreme",
        spread_percentile=50.0,
        bid_depth_usd=100000.0,
        ask_depth_usd=100000.0,
        hold_time_expected_sec=600.0,
    )
    
    # Extreme should be at least 20% higher than normal (not 50% due to fees dominating)
    assert cost_extreme.total_bps >= cost_normal.total_bps * 1.2, \
        f"Extreme volatility cost {cost_extreme.total_bps} should be >= 1.2x normal {cost_normal.total_bps}"


# =============================================================================
# Strategy-Specific Tests
# =============================================================================

def test_breakout_costs_higher_than_mean_reversion():
    """Test that breakout strategies have higher costs (more taker fills)."""
    fee_model = FeeModel(FeeConfig.okx_regular())
    execution_policy = ExecutionPolicy()
    slippage_model = SlippageModel()
    
    cost_estimator = CostEstimator(
        fee_model=fee_model,
        execution_policy=execution_policy,
        slippage_model=slippage_model,
    )
    
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
    
    # Breakout should have higher total costs
    assert cost_bo.total_bps > cost_mr.total_bps, \
        f"Breakout total {cost_bo.total_bps} should be > mean reversion {cost_mr.total_bps}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
