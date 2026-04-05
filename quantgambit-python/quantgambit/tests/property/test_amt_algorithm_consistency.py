"""Property-based tests for AMT Algorithm Consistency.

Feature: amt-fields-in-decision-events

Tests Property 8: Algorithm Consistency Between Live and Backtest

**Validates: Requirements 8.2**

This test verifies that the volume profile calculation produces identical
POC, VAH, VAL values when given the same input candles and configuration,
regardless of whether it's called from AMTCalculatorStage (live) or
BacktestExecutor (backtest).

Both components use the shared algorithm from quantgambit.core.volume_profile:
- AMTCalculatorStage uses `_calculate_volume_profile` which wraps the shared algorithm
- BacktestExecutor uses `calculate_volume_profile` directly from the shared module

This ensures that backtests accurately reflect live trading behavior.
"""

import pytest
from hypothesis import given, strategies as st, settings, assume

from quantgambit.core.volume_profile import (
    calculate_volume_profile,
    calculate_volume_profile_from_candles,
    VolumeProfileConfig,
    VolumeProfileResult,
)
from quantgambit.signals.stages.amt_calculator import (
    _calculate_volume_profile as amt_stage_calculate_volume_profile,
    AMTCalculatorConfig,
)


# =============================================================================
# Strategies for generating test data
# =============================================================================

# Generate realistic price values (crypto range)
price_strategy = st.floats(
    min_value=100.0,
    max_value=100000.0,
    allow_nan=False,
    allow_infinity=False,
)

# Generate positive volume values
volume_strategy = st.floats(
    min_value=1.0,
    max_value=1000000.0,
    allow_nan=False,
    allow_infinity=False,
)


@st.composite
def candle_strategy(draw):
    """Generate a single valid candle with OHLCV data."""
    # Generate base price
    base_price = draw(st.floats(
        min_value=100.0,
        max_value=100000.0,
        allow_nan=False,
        allow_infinity=False,
    ))
    
    # Generate price variation (up to 5% from base)
    variation = draw(st.floats(
        min_value=0.001,
        max_value=0.05,
        allow_nan=False,
        allow_infinity=False,
    ))
    
    # Generate OHLC values within the variation range
    open_price = base_price * (1 + draw(st.floats(
        min_value=-variation,
        max_value=variation,
        allow_nan=False,
        allow_infinity=False,
    )))
    high_price = base_price * (1 + draw(st.floats(
        min_value=0,
        max_value=variation,
        allow_nan=False,
        allow_infinity=False,
    )))
    low_price = base_price * (1 - draw(st.floats(
        min_value=0,
        max_value=variation,
        allow_nan=False,
        allow_infinity=False,
    )))
    close_price = base_price * (1 + draw(st.floats(
        min_value=-variation,
        max_value=variation,
        allow_nan=False,
        allow_infinity=False,
    )))
    
    # Ensure high >= max(open, close) and low <= min(open, close)
    high_price = max(high_price, open_price, close_price)
    low_price = min(low_price, open_price, close_price)
    
    volume = draw(volume_strategy)
    
    return {
        "open": open_price,
        "high": high_price,
        "low": low_price,
        "close": close_price,
        "volume": volume,
    }


# Strategy for generating lists of candles
# Need at least min_data_points (default 10) for valid calculation
candle_list_strategy = st.lists(
    candle_strategy(),
    min_size=15,  # Ensure we have enough data points
    max_size=200,
)


# Strategy for generating value area percentage
value_area_pct_strategy = st.floats(
    min_value=50.0,
    max_value=95.0,
    allow_nan=False,
    allow_infinity=False,
)


# Strategy for generating bin count
bin_count_strategy = st.integers(min_value=5, max_value=50)


# =============================================================================
# Property Tests
# =============================================================================

class TestAMTAlgorithmConsistency:
    """Property-based tests for AMT Algorithm Consistency.
    
    Feature: amt-fields-in-decision-events, Property 8: Algorithm Consistency
    **Validates: Requirements 8.2**
    
    These tests verify that the volume profile calculation in AMTCalculatorStage
    and BacktestExecutor produce identical POC, VAH, VAL values when given the
    same input candles and configuration.
    """
    
    @given(candles=candle_list_strategy)
    @settings(max_examples=100)
    def test_property_8_algorithm_consistency_default_config(self, candles: list):
        """Property 8: Algorithm Consistency Between Live and Backtest.
        
        *For any* set of candle data, the volume profile calculation in
        AMTCalculatorStage and BacktestExecutor SHALL produce identical
        POC, VAH, VAL values when given the same input candles and configuration.
        
        This test uses default configuration values.
        
        Feature: amt-fields-in-decision-events, Property 8: Algorithm Consistency
        **Validates: Requirements 8.2**
        """
        # Both AMTCalculatorStage and BacktestExecutor use the same shared algorithm
        # from quantgambit.core.volume_profile
        
        # Create default configs that match between live and backtest
        shared_config = VolumeProfileConfig(
            bin_count=20,
            value_area_pct=68.0,
            min_data_points=10,
        )
        
        amt_config = AMTCalculatorConfig(
            bin_count=20,
            value_area_pct=68.0,
            min_candles=10,
        )
        
        # Calculate using the shared function (used by BacktestExecutor)
        result_backtest = calculate_volume_profile_from_candles(candles, shared_config)
        
        # Calculate using AMTCalculatorStage's wrapper function
        result_live = amt_stage_calculate_volume_profile(candles, amt_config)
        
        # Skip if insufficient data (both should return None/empty)
        if result_backtest is None:
            # AMTCalculatorStage returns empty dict when insufficient data
            assert result_live == {}, (
                f"AMTCalculatorStage should return empty dict when shared algorithm returns None, "
                f"got {result_live}"
            )
            return
        
        # Both should have valid results
        assume(result_backtest is not None)
        assume(result_live)  # Non-empty dict
        
        # Results should be identical
        assert result_live.get("point_of_control") == result_backtest.point_of_control, (
            f"POC mismatch: live={result_live.get('point_of_control')}, "
            f"backtest={result_backtest.point_of_control}"
        )
        assert result_live.get("value_area_high") == result_backtest.value_area_high, (
            f"VAH mismatch: live={result_live.get('value_area_high')}, "
            f"backtest={result_backtest.value_area_high}"
        )
        assert result_live.get("value_area_low") == result_backtest.value_area_low, (
            f"VAL mismatch: live={result_live.get('value_area_low')}, "
            f"backtest={result_backtest.value_area_low}"
        )
    
    @given(
        candles=candle_list_strategy,
        value_area_pct=value_area_pct_strategy,
        bin_count=bin_count_strategy,
    )
    @settings(max_examples=100)
    def test_property_8_algorithm_consistency_custom_config(
        self,
        candles: list,
        value_area_pct: float,
        bin_count: int,
    ):
        """Property 8: Algorithm Consistency with custom configuration.
        
        The algorithm consistency property should hold regardless of the
        configured value area percentage or bin count.
        
        Feature: amt-fields-in-decision-events, Property 8: Algorithm Consistency
        **Validates: Requirements 8.2**
        """
        # Create matching configs for both paths
        shared_config = VolumeProfileConfig(
            bin_count=bin_count,
            value_area_pct=value_area_pct,
            min_data_points=10,
        )
        
        amt_config = AMTCalculatorConfig(
            bin_count=bin_count,
            value_area_pct=value_area_pct,
            min_candles=10,
        )
        
        # Calculate using the shared function (used by BacktestExecutor)
        result_backtest = calculate_volume_profile_from_candles(candles, shared_config)
        
        # Calculate using AMTCalculatorStage's wrapper function
        result_live = amt_stage_calculate_volume_profile(candles, amt_config)
        
        # Skip if insufficient data
        if result_backtest is None:
            assert result_live == {}, (
                f"AMTCalculatorStage should return empty dict when shared algorithm returns None"
            )
            return
        
        assume(result_backtest is not None)
        assume(result_live)
        
        # Results should be identical
        assert result_live.get("point_of_control") == result_backtest.point_of_control, (
            f"POC mismatch with config (bin_count={bin_count}, value_area_pct={value_area_pct}): "
            f"live={result_live.get('point_of_control')}, backtest={result_backtest.point_of_control}"
        )
        assert result_live.get("value_area_high") == result_backtest.value_area_high, (
            f"VAH mismatch with config (bin_count={bin_count}, value_area_pct={value_area_pct}): "
            f"live={result_live.get('value_area_high')}, backtest={result_backtest.value_area_high}"
        )
        assert result_live.get("value_area_low") == result_backtest.value_area_low, (
            f"VAL mismatch with config (bin_count={bin_count}, value_area_pct={value_area_pct}): "
            f"live={result_live.get('value_area_low')}, backtest={result_backtest.value_area_low}"
        )
    
    @given(candles=candle_list_strategy)
    @settings(max_examples=100)
    def test_property_8_deterministic_results(self, candles: list):
        """Property 8: Deterministic results - same input produces same output.
        
        Multiple calls to the volume profile calculation with the same input
        should produce identical results.
        
        Feature: amt-fields-in-decision-events, Property 8: Algorithm Consistency
        **Validates: Requirements 8.2**
        """
        config = VolumeProfileConfig(
            bin_count=20,
            value_area_pct=68.0,
            min_data_points=10,
        )
        
        # Calculate multiple times
        result1 = calculate_volume_profile_from_candles(candles, config)
        result2 = calculate_volume_profile_from_candles(candles, config)
        result3 = calculate_volume_profile_from_candles(candles, config)
        
        # All results should be identical
        if result1 is None:
            assert result2 is None and result3 is None, (
                "Determinism violation: some calls returned None while others didn't"
            )
            return
        
        assume(result1 is not None)
        
        # Compare all three results
        assert result1.point_of_control == result2.point_of_control == result3.point_of_control, (
            f"POC not deterministic: {result1.point_of_control}, {result2.point_of_control}, {result3.point_of_control}"
        )
        assert result1.value_area_high == result2.value_area_high == result3.value_area_high, (
            f"VAH not deterministic: {result1.value_area_high}, {result2.value_area_high}, {result3.value_area_high}"
        )
        assert result1.value_area_low == result2.value_area_low == result3.value_area_low, (
            f"VAL not deterministic: {result1.value_area_low}, {result2.value_area_low}, {result3.value_area_low}"
        )


class TestAMTAlgorithmConsistencyWithRawData:
    """Property tests using raw prices and volumes lists.
    
    These tests verify algorithm consistency using the lower-level
    calculate_volume_profile function directly with generated price
    and volume lists.
    
    Feature: amt-fields-in-decision-events, Property 8: Algorithm Consistency
    **Validates: Requirements 8.2**
    """
    
    @given(
        base_price=price_strategy,
        spread_pct=st.floats(min_value=0.01, max_value=0.2, allow_nan=False, allow_infinity=False),
        count=st.integers(min_value=15, max_value=100),
        data=st.data(),
    )
    @settings(max_examples=100)
    def test_property_8_raw_data_consistency(
        self,
        base_price: float,
        spread_pct: float,
        count: int,
        data,
    ):
        """Property 8: Algorithm consistency with raw price/volume data.
        
        This test generates prices within a realistic spread around a base price
        and verifies that multiple calls produce identical results.
        
        Feature: amt-fields-in-decision-events, Property 8: Algorithm Consistency
        **Validates: Requirements 8.2**
        """
        # Generate prices within a realistic spread around base price
        prices = data.draw(st.lists(
            st.floats(
                min_value=base_price * (1 - spread_pct),
                max_value=base_price * (1 + spread_pct),
                allow_nan=False,
                allow_infinity=False,
            ),
            min_size=count,
            max_size=count,
        ))
        
        # Generate volumes matching the prices list size
        volumes = data.draw(st.lists(
            volume_strategy,
            min_size=count,
            max_size=count,
        ))
        
        config = VolumeProfileConfig(
            bin_count=20,
            value_area_pct=68.0,
            min_data_points=10,
        )
        
        # Calculate multiple times
        result1 = calculate_volume_profile(prices, volumes, config)
        result2 = calculate_volume_profile(prices, volumes, config)
        
        # Both should return the same result
        if result1 is None:
            assert result2 is None, "Inconsistent None results"
            return
        
        assume(result1 is not None)
        
        assert result1.point_of_control == result2.point_of_control, (
            f"POC not consistent: {result1.point_of_control} vs {result2.point_of_control}"
        )
        assert result1.value_area_high == result2.value_area_high, (
            f"VAH not consistent: {result1.value_area_high} vs {result2.value_area_high}"
        )
        assert result1.value_area_low == result2.value_area_low, (
            f"VAL not consistent: {result1.value_area_low} vs {result2.value_area_low}"
        )


class TestAMTAlgorithmConsistencyEdgeCases:
    """Property tests for edge cases in algorithm consistency.
    
    Feature: amt-fields-in-decision-events, Property 8: Algorithm Consistency
    **Validates: Requirements 8.2**
    """
    
    @given(
        base_price=price_strategy,
        volume=volume_strategy,
        count=st.integers(min_value=15, max_value=50),
    )
    @settings(max_examples=100)
    def test_property_8_uniform_prices_consistency(
        self,
        base_price: float,
        volume: float,
        count: int,
    ):
        """Property 8: Consistency with uniform prices (all same price).
        
        When all prices are the same, both live and backtest paths should
        produce identical results (POC = VAL = VAH = base_price).
        
        Feature: amt-fields-in-decision-events, Property 8: Algorithm Consistency
        **Validates: Requirements 8.2**
        """
        # Create candles with uniform prices
        candles = [
            {
                "open": base_price,
                "high": base_price,
                "low": base_price,
                "close": base_price,
                "volume": volume,
            }
            for _ in range(count)
        ]
        
        shared_config = VolumeProfileConfig(
            bin_count=20,
            value_area_pct=68.0,
            min_data_points=10,
        )
        
        amt_config = AMTCalculatorConfig(
            bin_count=20,
            value_area_pct=68.0,
            min_candles=10,
        )
        
        # Calculate using both paths
        result_backtest = calculate_volume_profile_from_candles(candles, shared_config)
        result_live = amt_stage_calculate_volume_profile(candles, amt_config)
        
        assert result_backtest is not None
        assert result_live
        
        # All values should be equal to base_price
        assert result_backtest.point_of_control == base_price
        assert result_backtest.value_area_low == base_price
        assert result_backtest.value_area_high == base_price
        
        # Live should match backtest
        assert result_live.get("point_of_control") == result_backtest.point_of_control
        assert result_live.get("value_area_low") == result_backtest.value_area_low
        assert result_live.get("value_area_high") == result_backtest.value_area_high
    
    @given(
        base_price=price_strategy,
        spread=st.floats(min_value=0.01, max_value=0.1, allow_nan=False, allow_infinity=False),
        count=st.integers(min_value=15, max_value=50),
    )
    @settings(max_examples=100)
    def test_property_8_concentrated_volume_consistency(
        self,
        base_price: float,
        spread: float,
        count: int,
    ):
        """Property 8: Consistency with volume concentrated at one price level.
        
        When most volume is at one price level, both live and backtest paths
        should produce identical results.
        
        Feature: amt-fields-in-decision-events, Property 8: Algorithm Consistency
        **Validates: Requirements 8.2**
        """
        # Create candles with prices spread around base price
        candles = []
        for i in range(count):
            price_offset = spread * (i - count // 2) / count
            price = base_price * (1 + price_offset)
            
            # Concentrate volume at the middle candle
            volume = 1000.0 if i == count // 2 else 1.0
            
            candles.append({
                "open": price,
                "high": price * 1.001,
                "low": price * 0.999,
                "close": price,
                "volume": volume,
            })
        
        shared_config = VolumeProfileConfig(
            bin_count=20,
            value_area_pct=68.0,
            min_data_points=10,
        )
        
        amt_config = AMTCalculatorConfig(
            bin_count=20,
            value_area_pct=68.0,
            min_candles=10,
        )
        
        # Calculate using both paths
        result_backtest = calculate_volume_profile_from_candles(candles, shared_config)
        result_live = amt_stage_calculate_volume_profile(candles, amt_config)
        
        assume(result_backtest is not None)
        assume(result_live)
        
        # Results should be identical
        assert result_live.get("point_of_control") == result_backtest.point_of_control, (
            f"POC mismatch with concentrated volume: "
            f"live={result_live.get('point_of_control')}, backtest={result_backtest.point_of_control}"
        )
        assert result_live.get("value_area_high") == result_backtest.value_area_high, (
            f"VAH mismatch with concentrated volume: "
            f"live={result_live.get('value_area_high')}, backtest={result_backtest.value_area_high}"
        )
        assert result_live.get("value_area_low") == result_backtest.value_area_low, (
            f"VAL mismatch with concentrated volume: "
            f"live={result_live.get('value_area_low')}, backtest={result_backtest.value_area_low}"
        )
    
    @given(count=st.integers(min_value=0, max_value=9))
    @settings(max_examples=100)
    def test_property_8_insufficient_data_consistency(self, count: int):
        """Property 8: Consistency with insufficient data.
        
        When there's insufficient data (< min_data_points), both live and
        backtest paths should return None/empty consistently.
        
        Feature: amt-fields-in-decision-events, Property 8: Algorithm Consistency
        **Validates: Requirements 8.2**
        """
        # Create candles with insufficient count
        candles = [
            {
                "open": 50000.0,
                "high": 50100.0,
                "low": 49900.0,
                "close": 50050.0,
                "volume": 1000.0,
            }
            for _ in range(count)
        ]
        
        shared_config = VolumeProfileConfig(
            bin_count=20,
            value_area_pct=68.0,
            min_data_points=10,
        )
        
        amt_config = AMTCalculatorConfig(
            bin_count=20,
            value_area_pct=68.0,
            min_candles=10,
        )
        
        # Calculate using both paths
        result_backtest = calculate_volume_profile_from_candles(candles, shared_config)
        result_live = amt_stage_calculate_volume_profile(candles, amt_config)
        
        # Both should indicate insufficient data
        assert result_backtest is None, (
            f"Backtest should return None for {count} candles (< 10 min_data_points)"
        )
        assert result_live == {}, (
            f"Live should return empty dict for {count} candles (< 10 min_candles)"
        )
