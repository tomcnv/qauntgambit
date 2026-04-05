"""Property-based tests for derived metrics correctness.

Feature: live-orderbook-data-storage, Property 4: Derived Metrics Correctness

Tests correctness properties for orderbook-derived metrics including
spread in basis points, depth in USD, and orderbook imbalance.

**Validates: Requirements 3.1, 3.2, 3.3, 3.4**
"""

import pytest
import math
from hypothesis import given, strategies as st, settings, assume

from quantgambit.market.derived_metrics import (
    calculate_spread_bps,
    calculate_depth_usd,
    calculate_orderbook_imbalance,
)


# =============================================================================
# Strategies for generating test data
# =============================================================================

# Orderbook level generator - price and size pairs
orderbook_level = st.tuples(
    st.floats(min_value=0.01, max_value=100000.0, allow_nan=False, allow_infinity=False),  # price
    st.floats(min_value=0.0001, max_value=10000.0, allow_nan=False, allow_infinity=False),  # size
)

# Orderbook generator (up to 20 levels)
orderbook_bids = st.lists(orderbook_level, min_size=0, max_size=20)
orderbook_asks = st.lists(orderbook_level, min_size=0, max_size=20)

# Non-empty orderbook generators for tests requiring at least one level
non_empty_orderbook_bids = st.lists(orderbook_level, min_size=1, max_size=20)
non_empty_orderbook_asks = st.lists(orderbook_level, min_size=1, max_size=20)

# Price generators for spread calculation
valid_price = st.floats(min_value=0.01, max_value=100000.0, allow_nan=False, allow_infinity=False)


# =============================================================================
# Property 4: Derived Metrics Correctness
# =============================================================================

class TestDerivedMetricsCorrectness:
    """Property 4: Derived Metrics Correctness
    
    For any orderbook with non-empty bids and asks:
    - spread_bps SHALL equal ((best_ask - best_bid) / ((best_ask + best_bid) / 2)) * 10000
    - bid_depth_usd SHALL equal sum(price * size for each bid level)
    - ask_depth_usd SHALL equal sum(price * size for each ask level)
    - orderbook_imbalance SHALL equal (bid_depth_usd - ask_depth_usd) / (bid_depth_usd + ask_depth_usd),
      or 0.0 if both depths are zero
    
    **Validates: Requirements 3.1, 3.2, 3.3, 3.4**
    """

    # =========================================================================
    # Spread BPS Tests (Requirement 3.1)
    # =========================================================================

    @given(
        best_bid=valid_price,
        best_ask=valid_price,
    )
    @settings(max_examples=100)
    def test_spread_bps_formula_correctness(self, best_bid: float, best_ask: float):
        """Verify spread_bps equals ((best_ask - best_bid) / mid_price) * 10000.
        
        **Validates: Requirements 3.1**
        """
        # Calculate expected spread using the formula from the design doc
        mid_price = (best_ask + best_bid) / 2.0
        
        # Skip if mid_price would be zero (edge case handled separately)
        assume(mid_price > 0)
        
        expected_spread_bps = ((best_ask - best_bid) / mid_price) * 10000.0
        
        actual_spread_bps = calculate_spread_bps(best_bid, best_ask)
        
        # Allow small floating-point tolerance
        assert abs(actual_spread_bps - expected_spread_bps) < 1e-6, (
            f"Spread BPS mismatch: expected {expected_spread_bps}, got {actual_spread_bps}"
        )

    @given(
        best_bid=valid_price,
        best_ask=valid_price,
    )
    @settings(max_examples=100)
    def test_spread_bps_symmetry(self, best_bid: float, best_ask: float):
        """Verify spread_bps is symmetric with respect to bid/ask ordering.
        
        The absolute spread should be the same regardless of which price is higher.
        
        **Validates: Requirements 3.1**
        """
        spread1 = calculate_spread_bps(best_bid, best_ask)
        spread2 = calculate_spread_bps(best_ask, best_bid)
        
        # The spread should have opposite signs when bid/ask are swapped
        # (negative spread when bid > ask, positive when ask > bid)
        assert abs(spread1 + spread2) < 1e-6, (
            f"Spread should be symmetric: {spread1} vs {spread2}"
        )

    @given(price=valid_price)
    @settings(max_examples=100)
    def test_spread_bps_zero_when_equal(self, price: float):
        """Verify spread_bps is zero when best_bid equals best_ask.
        
        **Validates: Requirements 3.1**
        """
        spread_bps = calculate_spread_bps(price, price)
        
        assert abs(spread_bps) < 1e-10, (
            f"Spread should be zero when bid equals ask, got {spread_bps}"
        )

    @given(
        best_bid=valid_price,
        best_ask=valid_price,
    )
    @settings(max_examples=100)
    def test_spread_bps_positive_when_ask_greater(self, best_bid: float, best_ask: float):
        """Verify spread_bps is positive when best_ask > best_bid.
        
        **Validates: Requirements 3.1**
        """
        assume(best_ask > best_bid)
        
        spread_bps = calculate_spread_bps(best_bid, best_ask)
        
        assert spread_bps > 0, (
            f"Spread should be positive when ask > bid, got {spread_bps}"
        )

    # =========================================================================
    # Depth USD Tests (Requirements 3.2, 3.3)
    # =========================================================================

    @given(levels=non_empty_orderbook_bids)
    @settings(max_examples=100)
    def test_bid_depth_usd_formula_correctness(self, levels):
        """Verify bid_depth_usd equals sum(price * size for each bid level).
        
        **Validates: Requirements 3.2**
        """
        # Convert tuples to lists for the function
        levels_as_lists = [[price, size] for price, size in levels]
        
        # Calculate expected depth using the formula from the design doc
        expected_depth = sum(price * size for price, size in levels if price > 0 and size > 0)
        
        actual_depth = calculate_depth_usd(levels_as_lists)
        
        # Allow small floating-point tolerance (relative to the magnitude)
        tolerance = max(1e-6, abs(expected_depth) * 1e-9)
        assert abs(actual_depth - expected_depth) < tolerance, (
            f"Bid depth USD mismatch: expected {expected_depth}, got {actual_depth}"
        )

    @given(levels=non_empty_orderbook_asks)
    @settings(max_examples=100)
    def test_ask_depth_usd_formula_correctness(self, levels):
        """Verify ask_depth_usd equals sum(price * size for each ask level).
        
        **Validates: Requirements 3.3**
        """
        # Convert tuples to lists for the function
        levels_as_lists = [[price, size] for price, size in levels]
        
        # Calculate expected depth using the formula from the design doc
        expected_depth = sum(price * size for price, size in levels if price > 0 and size > 0)
        
        actual_depth = calculate_depth_usd(levels_as_lists)
        
        # Allow small floating-point tolerance (relative to the magnitude)
        tolerance = max(1e-6, abs(expected_depth) * 1e-9)
        assert abs(actual_depth - expected_depth) < tolerance, (
            f"Ask depth USD mismatch: expected {expected_depth}, got {actual_depth}"
        )

    def test_depth_usd_empty_levels(self):
        """Verify depth_usd returns 0.0 for empty levels.
        
        **Validates: Requirements 3.2, 3.3**
        """
        assert calculate_depth_usd([]) == 0.0

    @given(levels=orderbook_bids)
    @settings(max_examples=100)
    def test_depth_usd_non_negative(self, levels):
        """Verify depth_usd is always non-negative.
        
        **Validates: Requirements 3.2, 3.3**
        """
        levels_as_lists = [[price, size] for price, size in levels]
        depth = calculate_depth_usd(levels_as_lists)
        
        assert depth >= 0, f"Depth should be non-negative, got {depth}"

    @given(
        levels1=non_empty_orderbook_bids,
        levels2=non_empty_orderbook_bids,
    )
    @settings(max_examples=100)
    def test_depth_usd_additivity(self, levels1, levels2):
        """Verify depth_usd is additive when combining level lists.
        
        **Validates: Requirements 3.2, 3.3**
        """
        levels1_as_lists = [[price, size] for price, size in levels1]
        levels2_as_lists = [[price, size] for price, size in levels2]
        combined = levels1_as_lists + levels2_as_lists
        
        depth1 = calculate_depth_usd(levels1_as_lists)
        depth2 = calculate_depth_usd(levels2_as_lists)
        combined_depth = calculate_depth_usd(combined)
        
        # Allow small floating-point tolerance
        tolerance = max(1e-6, abs(depth1 + depth2) * 1e-9)
        assert abs(combined_depth - (depth1 + depth2)) < tolerance, (
            f"Depth should be additive: {depth1} + {depth2} != {combined_depth}"
        )

    # =========================================================================
    # Orderbook Imbalance Tests (Requirement 3.4)
    # =========================================================================

    @given(
        bid_depth=st.floats(min_value=0.0, max_value=1e12, allow_nan=False, allow_infinity=False),
        ask_depth=st.floats(min_value=0.0, max_value=1e12, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=100)
    def test_orderbook_imbalance_formula_correctness(self, bid_depth: float, ask_depth: float):
        """Verify orderbook_imbalance equals (bid_depth - ask_depth) / (bid_depth + ask_depth).
        
        **Validates: Requirements 3.4**
        """
        total_depth = bid_depth + ask_depth
        
        if total_depth == 0:
            # Special case: both depths are zero
            expected_imbalance = 0.0
        else:
            expected_imbalance = (bid_depth - ask_depth) / total_depth
        
        actual_imbalance = calculate_orderbook_imbalance(bid_depth, ask_depth)
        
        # Allow small floating-point tolerance
        assert abs(actual_imbalance - expected_imbalance) < 1e-9, (
            f"Imbalance mismatch: expected {expected_imbalance}, got {actual_imbalance}"
        )

    def test_orderbook_imbalance_zero_depths(self):
        """Verify orderbook_imbalance returns 0.0 when both depths are zero.
        
        **Validates: Requirements 3.4**
        """
        imbalance = calculate_orderbook_imbalance(0.0, 0.0)
        
        assert imbalance == 0.0, (
            f"Imbalance should be 0.0 when both depths are zero, got {imbalance}"
        )

    @given(
        bid_depth=st.floats(min_value=0.0, max_value=1e12, allow_nan=False, allow_infinity=False),
        ask_depth=st.floats(min_value=0.0, max_value=1e12, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=100)
    def test_orderbook_imbalance_bounds(self, bid_depth: float, ask_depth: float):
        """Verify orderbook_imbalance is always between -1.0 and 1.0.
        
        **Validates: Requirements 3.4**
        """
        imbalance = calculate_orderbook_imbalance(bid_depth, ask_depth)
        
        assert -1.0 <= imbalance <= 1.0, (
            f"Imbalance should be in [-1, 1], got {imbalance}"
        )

    @given(depth=st.floats(min_value=0.01, max_value=1e12, allow_nan=False, allow_infinity=False))
    @settings(max_examples=100)
    def test_orderbook_imbalance_balanced_when_equal(self, depth: float):
        """Verify orderbook_imbalance is 0.0 when bid_depth equals ask_depth.
        
        **Validates: Requirements 3.4**
        """
        imbalance = calculate_orderbook_imbalance(depth, depth)
        
        assert abs(imbalance) < 1e-9, (
            f"Imbalance should be 0.0 when depths are equal, got {imbalance}"
        )

    @given(
        bid_depth=st.floats(min_value=0.01, max_value=1e12, allow_nan=False, allow_infinity=False),
        ask_depth=st.floats(min_value=0.01, max_value=1e12, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=100)
    def test_orderbook_imbalance_buying_pressure(self, bid_depth: float, ask_depth: float):
        """Verify imbalance > 0 indicates more buying pressure (more bids than asks).
        
        **Validates: Requirements 3.4**
        """
        assume(bid_depth != ask_depth)
        
        imbalance = calculate_orderbook_imbalance(bid_depth, ask_depth)
        
        if bid_depth > ask_depth:
            assert imbalance > 0.0, (
                f"Imbalance should be > 0.0 when bid_depth > ask_depth, got {imbalance}"
            )
        else:
            assert imbalance < 0.0, (
                f"Imbalance should be < 0.0 when bid_depth < ask_depth, got {imbalance}"
            )

    @given(
        bid_depth=st.floats(min_value=0.0, max_value=1e12, allow_nan=False, allow_infinity=False),
        ask_depth=st.floats(min_value=0.0, max_value=1e12, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=100)
    def test_orderbook_imbalance_complement(self, bid_depth: float, ask_depth: float):
        """Verify imbalance(bid, ask) + imbalance(ask, bid) = 0.0.
        
        **Validates: Requirements 3.4**
        """
        imbalance1 = calculate_orderbook_imbalance(bid_depth, ask_depth)
        imbalance2 = calculate_orderbook_imbalance(ask_depth, bid_depth)
        
        # The two imbalances should sum to 0.0
        assert abs(imbalance1 + imbalance2) < 1e-9, (
            f"Imbalances should sum to 0.0: {imbalance1} + {imbalance2} = {imbalance1 + imbalance2}"
        )

    # =========================================================================
    # End-to-End Integration Tests
    # =========================================================================

    @given(
        bids=non_empty_orderbook_bids,
        asks=non_empty_orderbook_asks,
    )
    @settings(max_examples=100)
    def test_full_orderbook_metrics_consistency(self, bids, asks):
        """Verify all derived metrics are consistent for a full orderbook.
        
        This test validates that when we have a complete orderbook with bids and asks,
        all derived metrics are calculated correctly and consistently.
        
        **Validates: Requirements 3.1, 3.2, 3.3, 3.4**
        """
        # Convert to list format
        bids_as_lists = [[price, size] for price, size in bids]
        asks_as_lists = [[price, size] for price, size in asks]
        
        # Get best bid (highest) and best ask (lowest)
        valid_bids = [(p, s) for p, s in bids if p > 0 and s > 0]
        valid_asks = [(p, s) for p, s in asks if p > 0 and s > 0]
        
        assume(len(valid_bids) > 0 and len(valid_asks) > 0)
        
        best_bid = max(p for p, s in valid_bids)
        best_ask = min(p for p, s in valid_asks)
        
        # Calculate all metrics
        spread_bps = calculate_spread_bps(best_bid, best_ask)
        bid_depth_usd = calculate_depth_usd(bids_as_lists)
        ask_depth_usd = calculate_depth_usd(asks_as_lists)
        imbalance = calculate_orderbook_imbalance(bid_depth_usd, ask_depth_usd)
        
        # Verify spread formula
        mid_price = (best_ask + best_bid) / 2.0
        expected_spread = ((best_ask - best_bid) / mid_price) * 10000.0
        assert abs(spread_bps - expected_spread) < 1e-6
        
        # Verify depth formulas
        expected_bid_depth = sum(p * s for p, s in valid_bids)
        expected_ask_depth = sum(p * s for p, s in valid_asks)
        
        tolerance_bid = max(1e-6, abs(expected_bid_depth) * 1e-9)
        tolerance_ask = max(1e-6, abs(expected_ask_depth) * 1e-9)
        
        assert abs(bid_depth_usd - expected_bid_depth) < tolerance_bid
        assert abs(ask_depth_usd - expected_ask_depth) < tolerance_ask
        
        # Verify imbalance formula
        total_depth = bid_depth_usd + ask_depth_usd
        if total_depth > 0:
            expected_imbalance = (bid_depth_usd - ask_depth_usd) / total_depth
        else:
            expected_imbalance = 0.0
        
        assert abs(imbalance - expected_imbalance) < 1e-9
        
        # Verify imbalance bounds
        assert -1.0 <= imbalance <= 1.0
