"""Unit tests for derived metrics calculator.

Feature: live-orderbook-data-storage
Tests specific examples and edge cases for orderbook-derived metrics.
"""

import pytest
from quantgambit.market.derived_metrics import (
    calculate_spread_bps,
    calculate_depth_usd,
    calculate_orderbook_imbalance,
)


class TestCalculateSpreadBps:
    """Unit tests for calculate_spread_bps function."""
    
    def test_basic_spread_calculation(self):
        """Test basic spread calculation with typical values."""
        # Best bid = 100, best ask = 101
        # Mid price = 100.5
        # Spread = 1
        # Spread BPS = (1 / 100.5) * 10000 = 99.50248756...
        result = calculate_spread_bps(100.0, 101.0)
        expected = (1.0 / 100.5) * 10000.0
        assert abs(result - expected) < 0.0001
    
    def test_tight_spread(self):
        """Test with a very tight spread (typical for liquid markets)."""
        # BTC at ~50000 with 0.01 spread
        result = calculate_spread_bps(50000.0, 50000.01)
        # Mid = 50000.005, spread = 0.01
        # BPS = (0.01 / 50000.005) * 10000 ≈ 0.002
        expected = (0.01 / 50000.005) * 10000.0
        assert abs(result - expected) < 0.0001
    
    def test_wide_spread(self):
        """Test with a wide spread (typical for illiquid markets)."""
        # Wide spread: bid=95, ask=105
        result = calculate_spread_bps(95.0, 105.0)
        # Mid = 100, spread = 10
        # BPS = (10 / 100) * 10000 = 1000
        expected = 1000.0
        assert abs(result - expected) < 0.0001
    
    def test_zero_bid_returns_zero(self):
        """Test that zero bid returns 0.0."""
        result = calculate_spread_bps(0.0, 100.0)
        assert result == 0.0
    
    def test_zero_ask_returns_zero(self):
        """Test that zero ask returns 0.0."""
        result = calculate_spread_bps(100.0, 0.0)
        assert result == 0.0
    
    def test_negative_bid_returns_zero(self):
        """Test that negative bid returns 0.0."""
        result = calculate_spread_bps(-100.0, 100.0)
        assert result == 0.0
    
    def test_negative_ask_returns_zero(self):
        """Test that negative ask returns 0.0."""
        result = calculate_spread_bps(100.0, -100.0)
        assert result == 0.0
    
    def test_equal_bid_ask(self):
        """Test when bid equals ask (zero spread)."""
        result = calculate_spread_bps(100.0, 100.0)
        assert result == 0.0
    
    def test_inverted_spread(self):
        """Test when bid > ask (crossed market)."""
        # This is an unusual case but should still calculate
        result = calculate_spread_bps(101.0, 100.0)
        # Mid = 100.5, spread = -1
        # BPS = (-1 / 100.5) * 10000 = -99.50...
        expected = (-1.0 / 100.5) * 10000.0
        assert abs(result - expected) < 0.0001


class TestCalculateDepthUsd:
    """Unit tests for calculate_depth_usd function."""
    
    def test_basic_depth_calculation(self):
        """Test basic depth calculation with typical values."""
        levels = [
            [100.0, 10.0],  # 100 * 10 = 1000
            [99.0, 20.0],   # 99 * 20 = 1980
            [98.0, 30.0],   # 98 * 30 = 2940
        ]
        result = calculate_depth_usd(levels)
        expected = 1000.0 + 1980.0 + 2940.0  # 5920
        assert abs(result - expected) < 0.0001
    
    def test_single_level(self):
        """Test with a single level."""
        levels = [[50000.0, 0.5]]  # 50000 * 0.5 = 25000
        result = calculate_depth_usd(levels)
        assert abs(result - 25000.0) < 0.0001
    
    def test_empty_levels(self):
        """Test with empty levels list."""
        result = calculate_depth_usd([])
        assert result == 0.0
    
    def test_none_levels(self):
        """Test with None-like empty input."""
        result = calculate_depth_usd([])
        assert result == 0.0
    
    def test_zero_size_levels_skipped(self):
        """Test that zero-size levels are skipped."""
        levels = [
            [100.0, 10.0],  # 1000
            [99.0, 0.0],    # skipped
            [98.0, 5.0],    # 490
        ]
        result = calculate_depth_usd(levels)
        expected = 1000.0 + 490.0  # 1490
        assert abs(result - expected) < 0.0001
    
    def test_zero_price_levels_skipped(self):
        """Test that zero-price levels are skipped."""
        levels = [
            [100.0, 10.0],  # 1000
            [0.0, 20.0],    # skipped
            [98.0, 5.0],    # 490
        ]
        result = calculate_depth_usd(levels)
        expected = 1000.0 + 490.0  # 1490
        assert abs(result - expected) < 0.0001
    
    def test_negative_values_skipped(self):
        """Test that negative values are skipped."""
        levels = [
            [100.0, 10.0],   # 1000
            [-99.0, 20.0],   # skipped (negative price)
            [98.0, -5.0],    # skipped (negative size)
        ]
        result = calculate_depth_usd(levels)
        assert abs(result - 1000.0) < 0.0001
    
    def test_malformed_levels_skipped(self):
        """Test that malformed levels are skipped."""
        levels = [
            [100.0, 10.0],  # 1000
            [99.0],         # skipped (missing size)
            [],             # skipped (empty)
            [98.0, 5.0],    # 490
        ]
        result = calculate_depth_usd(levels)
        expected = 1000.0 + 490.0  # 1490
        assert abs(result - expected) < 0.0001
    
    def test_tuple_format(self):
        """Test with tuple format instead of list."""
        levels = [
            (100.0, 10.0),  # 1000
            (99.0, 20.0),   # 1980
        ]
        result = calculate_depth_usd(levels)
        expected = 1000.0 + 1980.0  # 2980
        assert abs(result - expected) < 0.0001
    
    def test_string_values_converted(self):
        """Test that string values are converted to float."""
        levels = [
            ["100.0", "10.0"],  # 1000
            ["99.0", "20.0"],   # 1980
        ]
        result = calculate_depth_usd(levels)
        expected = 1000.0 + 1980.0  # 2980
        assert abs(result - expected) < 0.0001
    
    def test_large_orderbook(self):
        """Test with 20 levels (typical full orderbook)."""
        levels = [[100.0 - i, 10.0 + i] for i in range(20)]
        result = calculate_depth_usd(levels)
        expected = sum((100.0 - i) * (10.0 + i) for i in range(20))
        assert abs(result - expected) < 0.0001


class TestCalculateOrderbookImbalance:
    """Unit tests for calculate_orderbook_imbalance function."""
    
    def test_balanced_orderbook(self):
        """Test with equal bid and ask depth."""
        result = calculate_orderbook_imbalance(1000.0, 1000.0)
        assert result == 0.0
    
    def test_all_bids(self):
        """Test with only bid depth (100% buying pressure)."""
        result = calculate_orderbook_imbalance(1000.0, 0.0)
        assert result == 1.0
    
    def test_all_asks(self):
        """Test with only ask depth (100% selling pressure)."""
        result = calculate_orderbook_imbalance(0.0, 1000.0)
        assert result == -1.0
    
    def test_both_zero(self):
        """Test with both depths zero (returns 0.0 by default)."""
        result = calculate_orderbook_imbalance(0.0, 0.0)
        assert result == 0.0
    
    def test_buying_pressure(self):
        """Test with more bid depth (buying pressure)."""
        # 70% bids, 30% asks
        result = calculate_orderbook_imbalance(7000.0, 3000.0)
        expected = (7000.0 - 3000.0) / 10000.0  # 0.4
        assert abs(result - expected) < 0.0001
    
    def test_selling_pressure(self):
        """Test with more ask depth (selling pressure)."""
        # 30% bids, 70% asks
        result = calculate_orderbook_imbalance(3000.0, 7000.0)
        expected = (3000.0 - 7000.0) / 10000.0  # -0.4
        assert abs(result - expected) < 0.0001
    
    def test_negative_bid_clamped(self):
        """Test that negative bid depth is clamped to zero."""
        result = calculate_orderbook_imbalance(-1000.0, 1000.0)
        # After clamping: bid=0, ask=1000
        assert result == -1.0
    
    def test_negative_ask_clamped(self):
        """Test that negative ask depth is clamped to zero."""
        result = calculate_orderbook_imbalance(1000.0, -1000.0)
        # After clamping: bid=1000, ask=0
        assert result == 1.0
    
    def test_both_negative_returns_balanced(self):
        """Test that both negative depths return 0.0."""
        result = calculate_orderbook_imbalance(-1000.0, -1000.0)
        # After clamping: bid=0, ask=0 -> returns 0.0
        assert result == 0.0
    
    def test_small_values(self):
        """Test with very small values."""
        result = calculate_orderbook_imbalance(0.001, 0.001)
        assert result == 0.0
    
    def test_large_values(self):
        """Test with very large values."""
        result = calculate_orderbook_imbalance(1e12, 1e12)
        assert result == 0.0
    
    def test_result_bounds(self):
        """Test that result is always between -1 and 1."""
        test_cases = [
            (0.0, 0.0),
            (1000.0, 0.0),
            (0.0, 1000.0),
            (500.0, 500.0),
            (999.0, 1.0),
            (1.0, 999.0),
        ]
        for bid, ask in test_cases:
            result = calculate_orderbook_imbalance(bid, ask)
            assert -1.0 <= result <= 1.0, f"Failed for bid={bid}, ask={ask}"
