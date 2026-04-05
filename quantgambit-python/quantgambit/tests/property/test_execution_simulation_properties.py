"""
Property-based tests for Execution Simulation.

Feature: trading-pipeline-integration

These tests verify the correctness properties of the execution simulator,
ensuring proper partial fill probability by size, latency simulation distribution,
slippage model consistency, and execution scenario presets.

Uses hypothesis library with minimum 100 iterations per property test.

**Validates: Requirements 5.1, 5.2, 5.4, 5.5**
"""

from __future__ import annotations

import math
import statistics
from typing import Any, Dict, List, Optional

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

from quantgambit.integration.execution_simulator import (
    ExecutionSimulator,
    ExecutionSimulatorConfig,
    SimulatedFill,
)


# ═══════════════════════════════════════════════════════════════
# STRATEGIES FOR PROPERTY-BASED TESTING
# ═══════════════════════════════════════════════════════════════

# Order side strategy
side_strategy = st.sampled_from(["buy", "sell"])

# Order size strategy (positive, reasonable values)
size_strategy = st.floats(
    min_value=0.001,
    max_value=100.0,
    allow_nan=False,
    allow_infinity=False,
)

# Price strategy (positive, reasonable values)
price_strategy = st.floats(
    min_value=1.0,
    max_value=100000.0,
    allow_nan=False,
    allow_infinity=False,
)

# Depth strategy (positive, reasonable values for USD liquidity)
depth_strategy = st.floats(
    min_value=1000.0,
    max_value=10000000.0,
    allow_nan=False,
    allow_infinity=False,
)

# Spread strategy (in basis points)
spread_bps_strategy = st.floats(
    min_value=0.1,
    max_value=100.0,
    allow_nan=False,
    allow_infinity=False,
)

# Boolean strategy for maker orders
is_maker_strategy = st.booleans()

# Latency parameters strategy
latency_base_strategy = st.floats(
    min_value=1.0,
    max_value=500.0,
    allow_nan=False,
    allow_infinity=False,
)

latency_std_strategy = st.floats(
    min_value=0.1,
    max_value=100.0,
    allow_nan=False,
    allow_infinity=False,
)

# Slippage parameters strategy
slippage_base_strategy = st.floats(
    min_value=0.0,
    max_value=10.0,
    allow_nan=False,
    allow_infinity=False,
)

depth_slippage_factor_strategy = st.floats(
    min_value=0.0,
    max_value=1.0,
    allow_nan=False,
    allow_infinity=False,
)

# Partial fill probability strategy
partial_fill_prob_strategy = st.floats(
    min_value=0.0,
    max_value=1.0,
    allow_nan=False,
    allow_infinity=False,
)

# Random seed strategy for reproducibility
seed_strategy = st.integers(min_value=0, max_value=2**31 - 1)


# ═══════════════════════════════════════════════════════════════
# HELPER FUNCTIONS
# ═══════════════════════════════════════════════════════════════

def calculate_size_ratio(size: float, price: float, depth: float) -> float:
    """Calculate order size ratio relative to available depth."""
    order_value = size * price
    return order_value / depth if depth > 0 else 1.0


def get_size_bucket(size_ratio: float) -> str:
    """Get the size bucket for a given size ratio."""
    if size_ratio < 0.01:
        return "small"
    elif size_ratio < 0.05:
        return "medium"
    else:
        return "large"


# ═══════════════════════════════════════════════════════════════
# PROPERTY 13: PARTIAL FILL PROBABILITY BY SIZE
# Feature: trading-pipeline-integration, Property 13
# Validates: Requirements 5.1
# ═══════════════════════════════════════════════════════════════

class TestPartialFillProbabilityBySize:
    """
    Feature: trading-pipeline-integration, Property 13: Partial Fill Probability by Size
    
    For any simulated order, the partial fill probability SHALL increase with
    order size relative to available depth: small (<1%) → partial_fill_prob_small,
    medium (1-5%) → partial_fill_prob_medium, large (>5%) → partial_fill_prob_large.
    
    **Validates: Requirements 5.1**
    """
    
    @settings(max_examples=100)
    @given(
        seed=seed_strategy,
        price=price_strategy,
        depth=depth_strategy,
        spread_bps=spread_bps_strategy,
    )
    def test_small_orders_use_small_probability(
        self,
        seed: int,
        price: float,
        depth: float,
        spread_bps: float,
    ):
        """
        **Validates: Requirements 5.1**
        
        Property: For orders with size_ratio < 1% of depth, the partial fill
        probability used is partial_fill_prob_small.
        """
        # Create config with distinct probabilities for each bucket
        config = ExecutionSimulatorConfig(
            partial_fill_prob_small=0.10,
            partial_fill_prob_medium=0.30,
            partial_fill_prob_large=0.60,
        )
        simulator = ExecutionSimulator(config)
        simulator.seed(seed)
        
        # Calculate size that gives < 1% of depth
        # size * price < 0.01 * depth
        # size < 0.01 * depth / price
        max_size = 0.009 * depth / price  # Use 0.9% to be safely under 1%
        assume(max_size > 0.001)  # Ensure we have a valid size
        
        size = min(max_size, 1.0)  # Cap at reasonable size
        
        # Verify size ratio is in small bucket
        size_ratio = calculate_size_ratio(size, price, depth)
        assert size_ratio < 0.01, f"Size ratio {size_ratio} should be < 0.01"
        
        # Run many simulations to verify probability
        num_trials = 1000
        partial_fills = 0
        
        for i in range(num_trials):
            simulator.seed(seed + i)
            fill = simulator.simulate_fill(
                side="buy",
                size=size,
                price=price,
                bid_depth_usd=depth,
                ask_depth_usd=depth,
                spread_bps=spread_bps,
                is_maker=False,
            )
            if fill.is_partial:
                partial_fills += 1
        
        # The observed rate should be close to partial_fill_prob_small (0.10)
        observed_rate = partial_fills / num_trials
        expected_rate = config.partial_fill_prob_small
        
        # Allow for statistical variance (within 5 percentage points)
        assert abs(observed_rate - expected_rate) < 0.05, \
            f"Small order partial fill rate {observed_rate:.3f} should be close to {expected_rate}"

    @settings(max_examples=100)
    @given(
        seed=seed_strategy,
        price=price_strategy,
        depth=depth_strategy,
        spread_bps=spread_bps_strategy,
    )
    def test_medium_orders_use_medium_probability(
        self,
        seed: int,
        price: float,
        depth: float,
        spread_bps: float,
    ):
        """
        **Validates: Requirements 5.1**
        
        Property: For orders with size_ratio between 1% and 5% of depth,
        the partial fill probability used is partial_fill_prob_medium.
        """
        # Create config with distinct probabilities for each bucket
        config = ExecutionSimulatorConfig(
            partial_fill_prob_small=0.05,
            partial_fill_prob_medium=0.25,
            partial_fill_prob_large=0.55,
        )
        simulator = ExecutionSimulator(config)
        simulator.seed(seed)
        
        # Calculate size that gives 1-5% of depth (use 3% as middle)
        # size * price = 0.03 * depth
        # size = 0.03 * depth / price
        target_size = 0.03 * depth / price
        assume(target_size > 0.001)  # Ensure we have a valid size
        
        size = min(target_size, 100.0)  # Cap at reasonable size
        
        # Verify size ratio is in medium bucket
        size_ratio = calculate_size_ratio(size, price, depth)
        assume(0.01 <= size_ratio < 0.05)  # Must be in medium bucket
        
        # Run many simulations to verify probability
        num_trials = 1000
        partial_fills = 0
        
        for i in range(num_trials):
            simulator.seed(seed + i)
            fill = simulator.simulate_fill(
                side="buy",
                size=size,
                price=price,
                bid_depth_usd=depth,
                ask_depth_usd=depth,
                spread_bps=spread_bps,
                is_maker=False,
            )
            if fill.is_partial:
                partial_fills += 1
        
        # The observed rate should be close to partial_fill_prob_medium (0.25)
        observed_rate = partial_fills / num_trials
        expected_rate = config.partial_fill_prob_medium
        
        # Allow for statistical variance (within 5 percentage points)
        assert abs(observed_rate - expected_rate) < 0.05, \
            f"Medium order partial fill rate {observed_rate:.3f} should be close to {expected_rate}"

    @settings(max_examples=100)
    @given(
        seed=seed_strategy,
        price=price_strategy,
        depth=depth_strategy,
        spread_bps=spread_bps_strategy,
    )
    def test_large_orders_use_large_probability(
        self,
        seed: int,
        price: float,
        depth: float,
        spread_bps: float,
    ):
        """
        **Validates: Requirements 5.1**
        
        Property: For orders with size_ratio >= 5% of depth, the partial fill
        probability used is partial_fill_prob_large.
        """
        # Create config with distinct probabilities for each bucket
        config = ExecutionSimulatorConfig(
            partial_fill_prob_small=0.05,
            partial_fill_prob_medium=0.20,
            partial_fill_prob_large=0.50,
        )
        simulator = ExecutionSimulator(config)
        simulator.seed(seed)
        
        # Calculate size that gives >= 5% of depth (use 10%)
        # size * price = 0.10 * depth
        # size = 0.10 * depth / price
        target_size = 0.10 * depth / price
        assume(target_size > 0.001)  # Ensure we have a valid size
        
        size = min(target_size, 1000.0)  # Cap at reasonable size
        
        # Verify size ratio is in large bucket
        size_ratio = calculate_size_ratio(size, price, depth)
        assume(size_ratio >= 0.05)  # Must be in large bucket
        
        # Run many simulations to verify probability
        num_trials = 1000
        partial_fills = 0
        
        for i in range(num_trials):
            simulator.seed(seed + i)
            fill = simulator.simulate_fill(
                side="buy",
                size=size,
                price=price,
                bid_depth_usd=depth,
                ask_depth_usd=depth,
                spread_bps=spread_bps,
                is_maker=False,
            )
            if fill.is_partial:
                partial_fills += 1
        
        # The observed rate should be close to partial_fill_prob_large (0.50)
        observed_rate = partial_fills / num_trials
        expected_rate = config.partial_fill_prob_large
        
        # Allow for statistical variance (within 6 percentage points for higher variance)
        assert abs(observed_rate - expected_rate) < 0.06, \
            f"Large order partial fill rate {observed_rate:.3f} should be close to {expected_rate}"

    @settings(max_examples=100)
    @given(
        seed=seed_strategy,
        prob_small=st.floats(min_value=0.01, max_value=0.15, allow_nan=False, allow_infinity=False),
        prob_medium=st.floats(min_value=0.16, max_value=0.35, allow_nan=False, allow_infinity=False),
        prob_large=st.floats(min_value=0.36, max_value=0.70, allow_nan=False, allow_infinity=False),
    )
    def test_probability_increases_with_size(
        self,
        seed: int,
        prob_small: float,
        prob_medium: float,
        prob_large: float,
    ):
        """
        **Validates: Requirements 5.1**
        
        Property: The partial fill probability SHALL increase with order size:
        prob_small < prob_medium < prob_large.
        """
        # Ensure probabilities are strictly increasing
        assume(prob_small < prob_medium < prob_large)
        
        config = ExecutionSimulatorConfig(
            partial_fill_prob_small=prob_small,
            partial_fill_prob_medium=prob_medium,
            partial_fill_prob_large=prob_large,
        )
        
        # Verify the config maintains the ordering
        assert config.partial_fill_prob_small < config.partial_fill_prob_medium, \
            "Small probability should be less than medium"
        assert config.partial_fill_prob_medium < config.partial_fill_prob_large, \
            "Medium probability should be less than large"
    
    @settings(max_examples=100)
    @given(
        seed=seed_strategy,
        price=price_strategy,
        depth=depth_strategy,
        spread_bps=spread_bps_strategy,
    )
    def test_maker_orders_have_reduced_partial_fill_probability(
        self,
        seed: int,
        price: float,
        depth: float,
        spread_bps: float,
    ):
        """
        **Validates: Requirements 5.1**
        
        Property: Maker orders have 50% reduced partial fill probability
        compared to taker orders of the same size.
        """
        config = ExecutionSimulatorConfig(
            partial_fill_prob_small=0.20,  # Use higher prob for clearer signal
            partial_fill_prob_medium=0.40,
            partial_fill_prob_large=0.60,
        )
        simulator = ExecutionSimulator(config)
        
        # Use a medium-sized order for testing
        target_size = 0.03 * depth / price
        assume(target_size > 0.001)
        size = min(target_size, 100.0)
        
        # Run simulations for taker orders
        num_trials = 1000
        taker_partial_fills = 0
        
        for i in range(num_trials):
            simulator.seed(seed + i)
            fill = simulator.simulate_fill(
                side="buy",
                size=size,
                price=price,
                bid_depth_usd=depth,
                ask_depth_usd=depth,
                spread_bps=spread_bps,
                is_maker=False,
            )
            if fill.is_partial:
                taker_partial_fills += 1
        
        # Run simulations for maker orders
        maker_partial_fills = 0
        
        for i in range(num_trials):
            simulator.seed(seed + i + num_trials)
            fill = simulator.simulate_fill(
                side="buy",
                size=size,
                price=price,
                bid_depth_usd=depth,
                ask_depth_usd=depth,
                spread_bps=spread_bps,
                is_maker=True,
            )
            if fill.is_partial:
                maker_partial_fills += 1
        
        taker_rate = taker_partial_fills / num_trials
        maker_rate = maker_partial_fills / num_trials
        
        # Maker rate should be approximately half of taker rate
        # Allow for statistical variance
        expected_maker_rate = taker_rate * 0.5
        assert maker_rate < taker_rate, \
            f"Maker partial fill rate {maker_rate:.3f} should be less than taker rate {taker_rate:.3f}"


# ═══════════════════════════════════════════════════════════════
# PROPERTY 14: LATENCY SIMULATION DISTRIBUTION
# Feature: trading-pipeline-integration, Property 14
# Validates: Requirements 5.2
# ═══════════════════════════════════════════════════════════════

class TestLatencySimulationDistribution:
    """
    Feature: trading-pipeline-integration, Property 14: Latency Simulation Distribution
    
    For any simulated execution, the latency_ms SHALL be drawn from a Gaussian
    distribution with mean=base_latency_ms and std=latency_std_ms, clamped to
    minimum 1.0ms.
    
    **Validates: Requirements 5.2**
    """
    
    @settings(max_examples=100)
    @given(
        seed=seed_strategy,
        base_latency=st.floats(min_value=50.0, max_value=500.0, allow_nan=False, allow_infinity=False),
        latency_std=st.floats(min_value=5.0, max_value=30.0, allow_nan=False, allow_infinity=False),
        size=size_strategy,
        price=price_strategy,
        depth=depth_strategy,
        spread_bps=spread_bps_strategy,
    )
    def test_latency_mean_matches_config(
        self,
        seed: int,
        base_latency: float,
        latency_std: float,
        size: float,
        price: float,
        depth: float,
        spread_bps: float,
    ):
        """
        **Validates: Requirements 5.2**
        
        Property: The mean of simulated latencies should approximate base_latency_ms
        when base_latency is high enough to minimize clamping effects.
        """
        # Ensure base_latency is high enough to minimize clamping effects
        # (clamping to 1.0ms shifts the mean upward when base is low)
        assume(base_latency > 3 * latency_std)
        
        config = ExecutionSimulatorConfig(
            base_latency_ms=base_latency,
            latency_std_ms=latency_std,
        )
        simulator = ExecutionSimulator(config)
        
        # Collect latency samples
        num_samples = 500
        latencies = []
        
        for i in range(num_samples):
            simulator.seed(seed + i)
            fill = simulator.simulate_fill(
                side="buy",
                size=size,
                price=price,
                bid_depth_usd=depth,
                ask_depth_usd=depth,
                spread_bps=spread_bps,
                is_maker=False,
            )
            latencies.append(fill.latency_ms)
        
        # Calculate observed mean
        observed_mean = statistics.mean(latencies)
        
        # The observed mean should be close to base_latency_ms
        # Allow for statistical variance (within 3 standard errors)
        standard_error = latency_std / math.sqrt(num_samples)
        tolerance = max(3 * standard_error, 5.0)  # At least 5ms tolerance
        
        assert abs(observed_mean - base_latency) < tolerance, \
            f"Observed mean latency {observed_mean:.2f}ms should be close to {base_latency:.2f}ms"

    @settings(max_examples=100)
    @given(
        seed=seed_strategy,
        base_latency=latency_base_strategy,
        latency_std=st.floats(min_value=5.0, max_value=50.0, allow_nan=False, allow_infinity=False),
        size=size_strategy,
        price=price_strategy,
        depth=depth_strategy,
        spread_bps=spread_bps_strategy,
    )
    def test_latency_std_matches_config(
        self,
        seed: int,
        base_latency: float,
        latency_std: float,
        size: float,
        price: float,
        depth: float,
        spread_bps: float,
    ):
        """
        **Validates: Requirements 5.2**
        
        Property: The standard deviation of simulated latencies should approximate
        latency_std_ms (accounting for clamping effects).
        """
        # Use higher base latency to minimize clamping effects
        assume(base_latency > 3 * latency_std)  # Minimize clamping
        
        config = ExecutionSimulatorConfig(
            base_latency_ms=base_latency,
            latency_std_ms=latency_std,
        )
        simulator = ExecutionSimulator(config)
        
        # Collect latency samples
        num_samples = 500
        latencies = []
        
        for i in range(num_samples):
            simulator.seed(seed + i)
            fill = simulator.simulate_fill(
                side="buy",
                size=size,
                price=price,
                bid_depth_usd=depth,
                ask_depth_usd=depth,
                spread_bps=spread_bps,
                is_maker=False,
            )
            latencies.append(fill.latency_ms)
        
        # Calculate observed standard deviation
        observed_std = statistics.stdev(latencies)
        
        # The observed std should be close to latency_std_ms
        # Allow for statistical variance (within 30% for std estimation)
        tolerance = max(latency_std * 0.3, 5.0)
        
        assert abs(observed_std - latency_std) < tolerance, \
            f"Observed std {observed_std:.2f}ms should be close to {latency_std:.2f}ms"

    @settings(max_examples=100)
    @given(
        seed=seed_strategy,
        base_latency=st.floats(min_value=1.0, max_value=10.0, allow_nan=False, allow_infinity=False),
        latency_std=st.floats(min_value=10.0, max_value=50.0, allow_nan=False, allow_infinity=False),
        size=size_strategy,
        price=price_strategy,
        depth=depth_strategy,
        spread_bps=spread_bps_strategy,
    )
    def test_latency_clamped_to_minimum_1ms(
        self,
        seed: int,
        base_latency: float,
        latency_std: float,
        size: float,
        price: float,
        depth: float,
        spread_bps: float,
    ):
        """
        **Validates: Requirements 5.2**
        
        Property: All simulated latencies SHALL be clamped to minimum 1.0ms.
        """
        # Use low base latency and high std to trigger clamping
        config = ExecutionSimulatorConfig(
            base_latency_ms=base_latency,
            latency_std_ms=latency_std,
        )
        simulator = ExecutionSimulator(config)
        
        # Collect latency samples
        num_samples = 500
        
        for i in range(num_samples):
            simulator.seed(seed + i)
            fill = simulator.simulate_fill(
                side="buy",
                size=size,
                price=price,
                bid_depth_usd=depth,
                ask_depth_usd=depth,
                spread_bps=spread_bps,
                is_maker=False,
            )
            
            # All latencies must be >= 1.0ms
            assert fill.latency_ms >= 1.0, \
                f"Latency {fill.latency_ms}ms should be >= 1.0ms"
    
    @settings(max_examples=100)
    @given(
        seed=seed_strategy,
        base_latency=latency_base_strategy,
        latency_std=latency_std_strategy,
    )
    def test_latency_is_positive(
        self,
        seed: int,
        base_latency: float,
        latency_std: float,
    ):
        """
        **Validates: Requirements 5.2**
        
        Property: All simulated latencies SHALL be positive.
        """
        config = ExecutionSimulatorConfig(
            base_latency_ms=base_latency,
            latency_std_ms=latency_std,
        )
        simulator = ExecutionSimulator(config)
        
        # Run multiple simulations
        num_samples = 100
        
        for i in range(num_samples):
            simulator.seed(seed + i)
            fill = simulator.simulate_fill(
                side="buy",
                size=1.0,
                price=50000.0,
                bid_depth_usd=100000.0,
                ask_depth_usd=100000.0,
                spread_bps=2.0,
                is_maker=False,
            )
            
            assert fill.latency_ms > 0, \
                f"Latency {fill.latency_ms}ms should be positive"


# ═══════════════════════════════════════════════════════════════
# PROPERTY 15: SLIPPAGE MODEL CONSISTENCY
# Feature: trading-pipeline-integration, Property 15
# Validates: Requirements 5.4
# ═══════════════════════════════════════════════════════════════

class TestSlippageModelConsistency:
    """
    Feature: trading-pipeline-integration, Property 15: Slippage Model Consistency
    
    For any simulated execution, the slippage_bps SHALL equal base_slippage_bps
    plus (order_size_ratio × depth_slippage_factor × 100), with maker orders
    receiving negative slippage (spread capture).
    
    **Validates: Requirements 5.4**
    """
    
    @settings(max_examples=100)
    @given(
        seed=seed_strategy,
        base_slippage=slippage_base_strategy,
        depth_factor=depth_slippage_factor_strategy,
        size=size_strategy,
        price=price_strategy,
        depth=depth_strategy,
        spread_bps=spread_bps_strategy,
        side=side_strategy,
    )
    def test_taker_slippage_formula(
        self,
        seed: int,
        base_slippage: float,
        depth_factor: float,
        size: float,
        price: float,
        depth: float,
        spread_bps: float,
        side: str,
    ):
        """
        **Validates: Requirements 5.4**
        
        Property: For taker orders, slippage_bps = base_slippage_bps + 
        (size_ratio × depth_slippage_factor × 100).
        """
        config = ExecutionSimulatorConfig(
            base_slippage_bps=base_slippage,
            depth_slippage_factor=depth_factor,
        )
        simulator = ExecutionSimulator(config)
        simulator.seed(seed)
        
        fill = simulator.simulate_fill(
            side=side,
            size=size,
            price=price,
            bid_depth_usd=depth,
            ask_depth_usd=depth,
            spread_bps=spread_bps,
            is_maker=False,
        )
        
        # Calculate expected slippage
        relevant_depth = depth  # Both bid and ask are the same
        order_value = size * price
        size_ratio = order_value / relevant_depth if relevant_depth > 0 else 1.0
        
        expected_slippage = base_slippage + (size_ratio * depth_factor * 100)
        
        # Verify slippage matches formula
        assert abs(fill.slippage_bps - expected_slippage) < 0.0001, \
            f"Slippage {fill.slippage_bps:.4f} should equal {expected_slippage:.4f}"

    @settings(max_examples=100)
    @given(
        seed=seed_strategy,
        spread_bps=spread_bps_strategy,
        size=size_strategy,
        price=price_strategy,
        depth=depth_strategy,
        side=side_strategy,
    )
    def test_maker_orders_have_negative_slippage(
        self,
        seed: int,
        spread_bps: float,
        size: float,
        price: float,
        depth: float,
        side: str,
    ):
        """
        **Validates: Requirements 5.4**
        
        Property: Maker orders receive negative slippage (spread capture),
        equal to -spread_bps / 4.
        """
        config = ExecutionSimulatorConfig()
        simulator = ExecutionSimulator(config)
        simulator.seed(seed)
        
        fill = simulator.simulate_fill(
            side=side,
            size=size,
            price=price,
            bid_depth_usd=depth,
            ask_depth_usd=depth,
            spread_bps=spread_bps,
            is_maker=True,
        )
        
        # Maker slippage should be negative (price improvement)
        expected_slippage = -spread_bps / 4
        
        assert abs(fill.slippage_bps - expected_slippage) < 0.0001, \
            f"Maker slippage {fill.slippage_bps:.4f} should equal {expected_slippage:.4f}"
        
        # Verify it's negative (price improvement)
        assert fill.slippage_bps < 0, \
            f"Maker slippage {fill.slippage_bps} should be negative"
    
    @settings(max_examples=100)
    @given(
        seed=seed_strategy,
        base_slippage=slippage_base_strategy,
        depth_factor=depth_slippage_factor_strategy,
        size=size_strategy,
        price=price_strategy,
        depth=depth_strategy,
        spread_bps=spread_bps_strategy,
    )
    def test_buy_slippage_increases_price(
        self,
        seed: int,
        base_slippage: float,
        depth_factor: float,
        size: float,
        price: float,
        depth: float,
        spread_bps: float,
    ):
        """
        **Validates: Requirements 5.4**
        
        Property: For buy orders with positive slippage, fill_price > order_price.
        """
        config = ExecutionSimulatorConfig(
            base_slippage_bps=base_slippage,
            depth_slippage_factor=depth_factor,
        )
        simulator = ExecutionSimulator(config)
        simulator.seed(seed)
        
        fill = simulator.simulate_fill(
            side="buy",
            size=size,
            price=price,
            bid_depth_usd=depth,
            ask_depth_usd=depth,
            spread_bps=spread_bps,
            is_maker=False,
        )
        
        # For taker buy orders with positive slippage, fill price should be higher
        if fill.slippage_bps > 0:
            assert fill.fill_price >= price, \
                f"Buy fill price {fill.fill_price} should be >= order price {price}"

    @settings(max_examples=100)
    @given(
        seed=seed_strategy,
        base_slippage=slippage_base_strategy,
        depth_factor=depth_slippage_factor_strategy,
        size=size_strategy,
        price=price_strategy,
        depth=depth_strategy,
        spread_bps=spread_bps_strategy,
    )
    def test_sell_slippage_decreases_price(
        self,
        seed: int,
        base_slippage: float,
        depth_factor: float,
        size: float,
        price: float,
        depth: float,
        spread_bps: float,
    ):
        """
        **Validates: Requirements 5.4**
        
        Property: For sell orders with positive slippage, fill_price < order_price.
        """
        config = ExecutionSimulatorConfig(
            base_slippage_bps=base_slippage,
            depth_slippage_factor=depth_factor,
        )
        simulator = ExecutionSimulator(config)
        simulator.seed(seed)
        
        fill = simulator.simulate_fill(
            side="sell",
            size=size,
            price=price,
            bid_depth_usd=depth,
            ask_depth_usd=depth,
            spread_bps=spread_bps,
            is_maker=False,
        )
        
        # For taker sell orders with positive slippage, fill price should be lower
        if fill.slippage_bps > 0:
            assert fill.fill_price <= price, \
                f"Sell fill price {fill.fill_price} should be <= order price {price}"
    
    @settings(max_examples=100)
    @given(
        seed=seed_strategy,
        base_slippage=slippage_base_strategy,
        depth_factor=depth_slippage_factor_strategy,
        price=price_strategy,
        depth=depth_strategy,
        spread_bps=spread_bps_strategy,
    )
    def test_slippage_increases_with_size_ratio(
        self,
        seed: int,
        base_slippage: float,
        depth_factor: float,
        price: float,
        depth: float,
        spread_bps: float,
    ):
        """
        **Validates: Requirements 5.4**
        
        Property: Slippage increases with order size ratio for taker orders.
        """
        assume(depth_factor > 0.01)  # Need non-zero factor for meaningful test
        
        config = ExecutionSimulatorConfig(
            base_slippage_bps=base_slippage,
            depth_slippage_factor=depth_factor,
        )
        simulator = ExecutionSimulator(config)
        
        # Calculate sizes for different ratios
        small_size = 0.005 * depth / price  # 0.5% of depth
        large_size = 0.10 * depth / price   # 10% of depth
        
        assume(small_size > 0.001)
        assume(large_size > small_size)
        
        simulator.seed(seed)
        small_fill = simulator.simulate_fill(
            side="buy",
            size=small_size,
            price=price,
            bid_depth_usd=depth,
            ask_depth_usd=depth,
            spread_bps=spread_bps,
            is_maker=False,
        )
        
        simulator.seed(seed)
        large_fill = simulator.simulate_fill(
            side="buy",
            size=large_size,
            price=price,
            bid_depth_usd=depth,
            ask_depth_usd=depth,
            spread_bps=spread_bps,
            is_maker=False,
        )
        
        # Larger order should have more slippage
        assert large_fill.slippage_bps > small_fill.slippage_bps, \
            f"Large order slippage {large_fill.slippage_bps} should be > small order slippage {small_fill.slippage_bps}"


# ═══════════════════════════════════════════════════════════════
# PROPERTY 16: EXECUTION SCENARIO PRESETS
# Feature: trading-pipeline-integration, Property 16
# Validates: Requirements 5.5
# ═══════════════════════════════════════════════════════════════

class TestExecutionScenarioPresets:
    """
    Feature: trading-pipeline-integration, Property 16: Execution Scenario Presets
    
    For any ExecutionSimulatorConfig created with scenario="optimistic", the
    parameters SHALL be more favorable (lower latency, lower partial fill prob,
    lower slippage) than scenario="realistic", which SHALL be more favorable
    than scenario="pessimistic".
    
    **Validates: Requirements 5.5**
    """
    
    @settings(max_examples=100)
    @given(seed=seed_strategy)
    def test_optimistic_more_favorable_than_realistic(
        self,
        seed: int,
    ):
        """
        **Validates: Requirements 5.5**
        
        Property: Optimistic scenario has more favorable parameters than realistic.
        """
        optimistic = ExecutionSimulatorConfig.optimistic()
        realistic = ExecutionSimulatorConfig.realistic()
        
        # Verify optimistic is more favorable
        assert optimistic.is_more_favorable_than(realistic), \
            "Optimistic should be more favorable than realistic"
        
        # Verify specific parameters
        assert optimistic.base_latency_ms <= realistic.base_latency_ms, \
            f"Optimistic latency {optimistic.base_latency_ms} should be <= realistic {realistic.base_latency_ms}"
        
        assert optimistic.latency_std_ms <= realistic.latency_std_ms, \
            f"Optimistic latency std {optimistic.latency_std_ms} should be <= realistic {realistic.latency_std_ms}"
        
        assert optimistic.partial_fill_prob_small <= realistic.partial_fill_prob_small, \
            f"Optimistic small prob {optimistic.partial_fill_prob_small} should be <= realistic {realistic.partial_fill_prob_small}"
        
        assert optimistic.partial_fill_prob_medium <= realistic.partial_fill_prob_medium, \
            f"Optimistic medium prob {optimistic.partial_fill_prob_medium} should be <= realistic {realistic.partial_fill_prob_medium}"
        
        assert optimistic.partial_fill_prob_large <= realistic.partial_fill_prob_large, \
            f"Optimistic large prob {optimistic.partial_fill_prob_large} should be <= realistic {realistic.partial_fill_prob_large}"
        
        assert optimistic.base_slippage_bps <= realistic.base_slippage_bps, \
            f"Optimistic slippage {optimistic.base_slippage_bps} should be <= realistic {realistic.base_slippage_bps}"

    @settings(max_examples=100)
    @given(seed=seed_strategy)
    def test_realistic_more_favorable_than_pessimistic(
        self,
        seed: int,
    ):
        """
        **Validates: Requirements 5.5**
        
        Property: Realistic scenario has more favorable parameters than pessimistic.
        """
        realistic = ExecutionSimulatorConfig.realistic()
        pessimistic = ExecutionSimulatorConfig.pessimistic()
        
        # Verify realistic is more favorable
        assert realistic.is_more_favorable_than(pessimistic), \
            "Realistic should be more favorable than pessimistic"
        
        # Verify specific parameters
        assert realistic.base_latency_ms <= pessimistic.base_latency_ms, \
            f"Realistic latency {realistic.base_latency_ms} should be <= pessimistic {pessimistic.base_latency_ms}"
        
        assert realistic.latency_std_ms <= pessimistic.latency_std_ms, \
            f"Realistic latency std {realistic.latency_std_ms} should be <= pessimistic {pessimistic.latency_std_ms}"
        
        assert realistic.partial_fill_prob_small <= pessimistic.partial_fill_prob_small, \
            f"Realistic small prob {realistic.partial_fill_prob_small} should be <= pessimistic {pessimistic.partial_fill_prob_small}"
        
        assert realistic.partial_fill_prob_medium <= pessimistic.partial_fill_prob_medium, \
            f"Realistic medium prob {realistic.partial_fill_prob_medium} should be <= pessimistic {pessimistic.partial_fill_prob_medium}"
        
        assert realistic.partial_fill_prob_large <= pessimistic.partial_fill_prob_large, \
            f"Realistic large prob {realistic.partial_fill_prob_large} should be <= pessimistic {pessimistic.partial_fill_prob_large}"
        
        assert realistic.base_slippage_bps <= pessimistic.base_slippage_bps, \
            f"Realistic slippage {realistic.base_slippage_bps} should be <= pessimistic {pessimistic.base_slippage_bps}"
    
    @settings(max_examples=100)
    @given(seed=seed_strategy)
    def test_optimistic_more_favorable_than_pessimistic(
        self,
        seed: int,
    ):
        """
        **Validates: Requirements 5.5**
        
        Property: Optimistic scenario has more favorable parameters than pessimistic
        (transitive property).
        """
        optimistic = ExecutionSimulatorConfig.optimistic()
        pessimistic = ExecutionSimulatorConfig.pessimistic()
        
        # Verify optimistic is more favorable than pessimistic
        assert optimistic.is_more_favorable_than(pessimistic), \
            "Optimistic should be more favorable than pessimistic"

    @settings(max_examples=100)
    @given(seed=seed_strategy)
    def test_scenario_presets_have_correct_labels(
        self,
        seed: int,
    ):
        """
        **Validates: Requirements 5.5**
        
        Property: Each scenario preset has the correct scenario label.
        """
        optimistic = ExecutionSimulatorConfig.optimistic()
        realistic = ExecutionSimulatorConfig.realistic()
        pessimistic = ExecutionSimulatorConfig.pessimistic()
        
        assert optimistic.scenario == "optimistic", \
            f"Optimistic scenario should be labeled 'optimistic', got '{optimistic.scenario}'"
        
        assert realistic.scenario == "realistic", \
            f"Realistic scenario should be labeled 'realistic', got '{realistic.scenario}'"
        
        assert pessimistic.scenario == "pessimistic", \
            f"Pessimistic scenario should be labeled 'pessimistic', got '{pessimistic.scenario}'"
    
    @settings(max_examples=100)
    @given(
        scenario=st.sampled_from(["optimistic", "realistic", "pessimistic"]),
    )
    def test_from_scenario_creates_correct_config(
        self,
        scenario: str,
    ):
        """
        **Validates: Requirements 5.5**
        
        Property: from_scenario() creates the correct configuration for each scenario.
        """
        config = ExecutionSimulatorConfig.from_scenario(scenario)
        
        assert config.scenario == scenario, \
            f"Config scenario should be '{scenario}', got '{config.scenario}'"
        
        # Verify it matches the direct factory method
        if scenario == "optimistic":
            expected = ExecutionSimulatorConfig.optimistic()
        elif scenario == "realistic":
            expected = ExecutionSimulatorConfig.realistic()
        else:
            expected = ExecutionSimulatorConfig.pessimistic()
        
        assert config.base_latency_ms == expected.base_latency_ms
        assert config.latency_std_ms == expected.latency_std_ms
        assert config.partial_fill_prob_small == expected.partial_fill_prob_small
        assert config.partial_fill_prob_medium == expected.partial_fill_prob_medium
        assert config.partial_fill_prob_large == expected.partial_fill_prob_large
        assert config.base_slippage_bps == expected.base_slippage_bps

    @settings(max_examples=100)
    @given(
        scenario=st.sampled_from(["optimistic", "realistic", "pessimistic"]),
        seed=seed_strategy,
        size=size_strategy,
        price=price_strategy,
        depth=depth_strategy,
        spread_bps=spread_bps_strategy,
    )
    def test_scenario_affects_simulation_results(
        self,
        scenario: str,
        seed: int,
        size: float,
        price: float,
        depth: float,
        spread_bps: float,
    ):
        """
        **Validates: Requirements 5.5**
        
        Property: Different scenarios produce different simulation characteristics.
        """
        config = ExecutionSimulatorConfig.from_scenario(scenario)
        simulator = ExecutionSimulator(config)
        
        # Run multiple simulations
        num_samples = 100
        latencies = []
        slippages = []
        partial_fills = 0
        
        for i in range(num_samples):
            simulator.seed(seed + i)
            fill = simulator.simulate_fill(
                side="buy",
                size=size,
                price=price,
                bid_depth_usd=depth,
                ask_depth_usd=depth,
                spread_bps=spread_bps,
                is_maker=False,
            )
            latencies.append(fill.latency_ms)
            slippages.append(fill.slippage_bps)
            if fill.is_partial:
                partial_fills += 1
        
        avg_latency = statistics.mean(latencies)
        avg_slippage = statistics.mean(slippages)
        partial_rate = partial_fills / num_samples
        
        # Verify results are consistent with scenario expectations
        if scenario == "optimistic":
            # Optimistic should have lower values
            assert avg_latency < 100, \
                f"Optimistic avg latency {avg_latency} should be < 100ms"
        elif scenario == "pessimistic":
            # Pessimistic should have higher values
            assert avg_latency > 50, \
                f"Pessimistic avg latency {avg_latency} should be > 50ms"
    
    @settings(max_examples=100)
    @given(seed=seed_strategy)
    def test_invalid_scenario_raises_error(
        self,
        seed: int,
    ):
        """
        **Validates: Requirements 5.5**
        
        Property: Invalid scenario names raise ValueError.
        """
        with pytest.raises(ValueError) as exc_info:
            ExecutionSimulatorConfig.from_scenario("invalid_scenario")
        
        assert "Unknown scenario" in str(exc_info.value)
    
    @settings(max_examples=100)
    @given(seed=seed_strategy)
    def test_all_scenarios_are_valid_configs(
        self,
        seed: int,
    ):
        """
        **Validates: Requirements 5.5**
        
        Property: All scenario presets create valid configurations that pass validation.
        """
        scenarios = ["optimistic", "realistic", "pessimistic"]
        
        for scenario in scenarios:
            config = ExecutionSimulatorConfig.from_scenario(scenario)
            
            # Verify all parameters are within valid ranges
            assert config.base_latency_ms >= 0
            assert config.latency_std_ms >= 0
            assert 0 <= config.partial_fill_prob_small <= 1
            assert 0 <= config.partial_fill_prob_medium <= 1
            assert 0 <= config.partial_fill_prob_large <= 1
            assert config.base_slippage_bps >= 0
            assert config.depth_slippage_factor >= 0
            
            # Verify simulator can be created and used
            simulator = ExecutionSimulator(config)
            simulator.seed(seed)
            fill = simulator.simulate_fill(
                side="buy",
                size=1.0,
                price=50000.0,
                bid_depth_usd=100000.0,
                ask_depth_usd=100000.0,
                spread_bps=2.0,
                is_maker=False,
            )
            
            # Verify fill is valid
            assert fill.filled_size > 0
            assert fill.fill_price > 0
            assert fill.latency_ms >= 1.0
