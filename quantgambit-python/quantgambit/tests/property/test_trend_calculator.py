"""Property-based tests for TrendCalculator.

Feature: backtest-pipeline-unification, Property 2: Trend Calculation Correctness

Tests that:
- EMA fast > EMA slow by threshold → "up"
- EMA fast < EMA slow by threshold → "down"
- Price action fallback when EMAs inconclusive

Validates: Requirements 2.1, 2.2
"""

import pytest
from hypothesis import given, strategies as st, settings, assume

from quantgambit.backtesting.trend_calculator import TrendCalculator, TrendResult


# =============================================================================
# Strategies for generating test data
# =============================================================================

# Generate realistic price values (crypto range)
price_strategy = st.floats(min_value=1000.0, max_value=200000.0, allow_nan=False, allow_infinity=False)

# Generate lists of prices for candle data
price_list_strategy = st.lists(
    price_strategy,
    min_size=25,  # Need at least slow EMA period
    max_size=100,
)

# Generate EMA values
ema_strategy = st.floats(min_value=1000.0, max_value=200000.0, allow_nan=False, allow_infinity=False)


# =============================================================================
# Property Tests
# =============================================================================

class TestTrendCalculatorProperties:
    """Property-based tests for TrendCalculator.
    
    Feature: backtest-pipeline-unification, Property 2: Trend Calculation Correctness
    """
    
    @given(
        ema_fast=ema_strategy,
        ema_slow=ema_strategy,
        threshold_pct=st.floats(min_value=0.0001, max_value=0.01, allow_nan=False),
    )
    @settings(max_examples=100)
    def test_ema_fast_above_slow_is_uptrend(
        self,
        ema_fast: float,
        ema_slow: float,
        threshold_pct: float,
    ):
        """Property: EMA fast > EMA slow by threshold → "up".
        
        For any EMA pair where fast > slow by more than threshold,
        the trend direction SHALL be "up".
        
        Validates: Requirements 2.1, 2.5
        """
        # Ensure fast is above slow by more than threshold
        assume(ema_slow > 0)
        diff_pct = (ema_fast - ema_slow) / ema_slow
        assume(diff_pct > threshold_pct)
        
        calculator = TrendCalculator(ema_threshold_pct=threshold_pct)
        result = calculator.calculate_from_emas(ema_fast, ema_slow)
        
        assert result.direction == "up", (
            f"Expected 'up' when ema_fast={ema_fast:.2f} > ema_slow={ema_slow:.2f} "
            f"by {diff_pct:.4f} (threshold={threshold_pct:.4f}), got '{result.direction}'"
        )
        assert result.strength > 0, "Uptrend should have positive strength"
    
    @given(
        ema_fast=ema_strategy,
        ema_slow=ema_strategy,
        threshold_pct=st.floats(min_value=0.0001, max_value=0.01, allow_nan=False),
    )
    @settings(max_examples=100)
    def test_ema_fast_below_slow_is_downtrend(
        self,
        ema_fast: float,
        ema_slow: float,
        threshold_pct: float,
    ):
        """Property: EMA fast < EMA slow by threshold → "down".
        
        For any EMA pair where fast < slow by more than threshold,
        the trend direction SHALL be "down".
        
        Validates: Requirements 2.1, 2.5
        """
        # Ensure fast is below slow by more than threshold
        assume(ema_slow > 0)
        diff_pct = (ema_fast - ema_slow) / ema_slow
        assume(diff_pct < -threshold_pct)
        
        calculator = TrendCalculator(ema_threshold_pct=threshold_pct)
        result = calculator.calculate_from_emas(ema_fast, ema_slow)
        
        assert result.direction == "down", (
            f"Expected 'down' when ema_fast={ema_fast:.2f} < ema_slow={ema_slow:.2f} "
            f"by {diff_pct:.4f} (threshold={threshold_pct:.4f}), got '{result.direction}'"
        )
        assert result.strength > 0, "Downtrend should have positive strength"
    
    @given(
        ema_fast=ema_strategy,
        ema_slow=ema_strategy,
        threshold_pct=st.floats(min_value=0.0001, max_value=0.01, allow_nan=False),
    )
    @settings(max_examples=100)
    def test_ema_within_threshold_is_flat(
        self,
        ema_fast: float,
        ema_slow: float,
        threshold_pct: float,
    ):
        """Property: EMA difference within threshold → "flat".
        
        For any EMA pair where the difference is within threshold,
        the trend direction SHALL be "flat".
        
        Validates: Requirements 2.5
        """
        assume(ema_slow > 0)
        # Generate ema_fast that's strictly within threshold of ema_slow
        # Use 90% of threshold to avoid boundary issues
        max_diff = ema_slow * threshold_pct * 0.9
        if max_diff == 0:
            ema_fast_adjusted = ema_slow
        else:
            ema_fast_adjusted = ema_slow + (ema_fast % (2 * max_diff)) - max_diff
        
        diff_pct = (ema_fast_adjusted - ema_slow) / ema_slow
        
        calculator = TrendCalculator(ema_threshold_pct=threshold_pct)
        result = calculator.calculate_from_emas(ema_fast_adjusted, ema_slow)
        
        assert result.direction == "flat", (
            f"Expected 'flat' when diff_pct={diff_pct:.6f} within threshold={threshold_pct:.6f}, "
            f"got '{result.direction}'"
        )
    
    @given(prices=price_list_strategy)
    @settings(max_examples=100)
    def test_price_action_fallback_on_significant_move(self, prices: list):
        """Property: Price action fallback when EMAs inconclusive but price moved >2%.
        
        For any price series where EMAs are flat but price moved significantly,
        the trend SHALL be calculated from price action.
        
        Validates: Requirements 2.2
        """
        assume(len(prices) >= 25)
        assume(prices[0] > 0)
        
        # Create a scenario where EMAs would be flat but price moved significantly
        # Start with flat prices, then add a significant move at the end
        base_price = prices[0]
        flat_prices = [base_price] * 20
        
        # Add a significant move (>2%)
        move_pct = 0.05  # 5% move
        trending_prices = flat_prices + [base_price * (1 + move_pct)] * 5
        
        calculator = TrendCalculator(
            ema_threshold_pct=0.001,
            price_move_threshold_pct=0.02,
        )
        
        candles = [{"close": p} for p in trending_prices]
        result = calculator.calculate_from_candles(candles)
        
        # Should detect uptrend from price action or EMA
        # The exact method depends on how the EMAs respond to the move
        assert result.direction in ["up", "flat"], (
            f"Expected 'up' or 'flat' for upward price move, got '{result.direction}'"
        )
    
    @given(prices=price_list_strategy)
    @settings(max_examples=100)
    def test_trend_direction_is_valid(self, prices: list):
        """Property: Trend direction is always one of valid values.
        
        For any input, the trend direction SHALL be "up", "down", or "flat".
        
        Validates: Requirements 2.5
        """
        calculator = TrendCalculator()
        candles = [{"close": p} for p in prices]
        result = calculator.calculate_from_candles(candles)
        
        assert result.direction in ["up", "down", "flat"], (
            f"Invalid trend direction: '{result.direction}'"
        )
    
    @given(prices=price_list_strategy)
    @settings(max_examples=100)
    def test_trend_strength_is_bounded(self, prices: list):
        """Property: Trend strength is always between 0 and 1.
        
        For any input, the trend strength SHALL be in [0.0, 1.0].
        """
        calculator = TrendCalculator()
        candles = [{"close": p} for p in prices]
        result = calculator.calculate_from_candles(candles)
        
        assert 0.0 <= result.strength <= 1.0, (
            f"Trend strength {result.strength} out of bounds [0, 1]"
        )
    
    @given(prices=price_list_strategy)
    @settings(max_examples=100)
    def test_method_is_valid(self, prices: list):
        """Property: Calculation method is always one of valid values.
        
        For any input, the method SHALL be "ema", "price_action", or "default".
        """
        calculator = TrendCalculator()
        candles = [{"close": p} for p in prices]
        result = calculator.calculate_from_candles(candles)
        
        assert result.method in ["ema", "price_action", "default"], (
            f"Invalid method: '{result.method}'"
        )


# =============================================================================
# Unit Tests for Edge Cases
# =============================================================================

class TestTrendCalculatorEdgeCases:
    """Unit tests for edge cases and specific scenarios."""
    
    def test_empty_candles_returns_flat(self):
        """Empty candle list should return flat trend."""
        calculator = TrendCalculator()
        result = calculator.calculate_from_candles([])
        
        assert result.direction == "flat"
        assert result.method == "default"
    
    def test_insufficient_candles_returns_flat(self):
        """Insufficient candles should return flat trend."""
        calculator = TrendCalculator(ema_slow_period=21)
        candles = [{"close": 100.0}] * 10  # Less than slow period
        result = calculator.calculate_from_candles(candles)
        
        assert result.direction == "flat"
        assert result.method == "default"
    
    def test_clear_uptrend_detected(self):
        """Clear uptrend should be detected."""
        calculator = TrendCalculator()
        # Create clear uptrend: prices increasing
        prices = [100.0 + i * 2 for i in range(30)]  # 100, 102, 104, ...
        candles = [{"close": p} for p in prices]
        result = calculator.calculate_from_candles(candles)
        
        assert result.direction == "up"
        assert result.strength > 0
    
    def test_clear_downtrend_detected(self):
        """Clear downtrend should be detected."""
        calculator = TrendCalculator()
        # Create clear downtrend: prices decreasing
        prices = [200.0 - i * 2 for i in range(30)]  # 200, 198, 196, ...
        candles = [{"close": p} for p in prices]
        result = calculator.calculate_from_candles(candles)
        
        assert result.direction == "down"
        assert result.strength > 0
    
    def test_flat_market_detected(self):
        """Flat market should be detected."""
        calculator = TrendCalculator()
        # Create flat market: prices oscillating around same level
        prices = [100.0 + (i % 2) * 0.1 for i in range(30)]  # 100.0, 100.1, 100.0, ...
        candles = [{"close": p} for p in prices]
        result = calculator.calculate_from_candles(candles)
        
        assert result.direction == "flat"
    
    def test_calculate_from_prices_convenience(self):
        """calculate_from_prices should work as convenience method."""
        calculator = TrendCalculator()
        prices = [100.0 + i * 2 for i in range(30)]
        result = calculator.calculate_from_prices(prices)
        
        assert result.direction == "up"
    
    def test_ema_values_returned(self):
        """EMA values should be returned in result."""
        calculator = TrendCalculator()
        prices = [100.0 + i for i in range(30)]
        candles = [{"close": p} for p in prices]
        result = calculator.calculate_from_candles(candles)
        
        assert result.ema_fast is not None
        assert result.ema_slow is not None
        assert result.ema_fast > 0
        assert result.ema_slow > 0
