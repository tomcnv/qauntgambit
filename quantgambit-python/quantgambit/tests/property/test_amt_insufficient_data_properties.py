"""Property-based tests for AMT Insufficient Data Handling.

Feature: amt-fields-in-decision-events

Tests Property 6: Insufficient Data Graceful Handling

*For any* AMT calculation request with fewer than min_candles (default 10),
the calculator SHALL return None for all AMT fields and the pipeline SHALL
continue processing without raising an exception.

**Validates: Requirements 1.5**

These tests use Hypothesis to generate candle lists with 0 to min_candles-1 items
and verify that the AMT calculation handles insufficient data gracefully.
"""

import pytest
from hypothesis import given, strategies as st, settings, assume
from typing import Any, Dict, List, Optional

from quantgambit.signals.stages.amt_calculator import (
    AMTCalculatorStage,
    AMTCalculatorConfig,
    AMTLevels,
    _calculate_volume_profile,
)
from quantgambit.core.volume_profile import (
    calculate_volume_profile_from_candles,
    VolumeProfileConfig,
)
from quantgambit.signals.pipeline import StageContext, StageResult


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
        "ts": draw(st.floats(min_value=1000000000.0, max_value=2000000000.0)),
    }


def insufficient_candle_list_strategy(min_candles: int = 10):
    """Generate candle lists with 0 to min_candles-1 items (insufficient data).
    
    Args:
        min_candles: The minimum candles threshold. Lists will have 0 to min_candles-1 items.
    
    Returns:
        Strategy that generates lists of candles with insufficient data.
    """
    return st.lists(
        candle_strategy(),
        min_size=0,
        max_size=min_candles - 1,
    )


# Strategy for generating min_candles configuration values
min_candles_strategy = st.integers(min_value=5, max_value=20)


# =============================================================================
# Property Tests
# =============================================================================

class TestInsufficientDataProperties:
    """Property-based tests for Insufficient Data Graceful Handling.
    
    Feature: amt-fields-in-decision-events, Property 6: Insufficient Data Graceful Handling
    **Validates: Requirements 1.5**
    """
    
    @given(candles=insufficient_candle_list_strategy(min_candles=10))
    @settings(max_examples=100)
    def test_property_6_volume_profile_returns_none_for_insufficient_data(
        self,
        candles: List[Dict[str, Any]],
    ):
        """Property 6: Volume profile returns None for insufficient data.
        
        *For any* AMT calculation request with fewer than min_candles (default 10),
        the calculator SHALL return None for all AMT fields.
        
        Feature: amt-fields-in-decision-events, Property 6: Insufficient Data Graceful Handling
        **Validates: Requirements 1.5**
        """
        config = VolumeProfileConfig(
            bin_count=20,
            value_area_pct=68.0,
            min_data_points=10,  # Default min_candles
        )
        
        # Attempt AMT calculation using calculate_volume_profile_from_candles
        result = calculate_volume_profile_from_candles(candles, config)
        
        # Property 6: Result should be None for insufficient data
        assert result is None, (
            f"Expected None for insufficient data ({len(candles)} candles < 10 min_candles), "
            f"but got {result}"
        )
    
    @given(candles=insufficient_candle_list_strategy(min_candles=10))
    @settings(max_examples=100)
    def test_property_6_amt_calculator_returns_empty_dict_for_insufficient_data(
        self,
        candles: List[Dict[str, Any]],
    ):
        """Property 6: _calculate_volume_profile returns empty dict for insufficient data.
        
        *For any* AMT calculation request with fewer than min_candles (default 10),
        the _calculate_volume_profile function SHALL return an empty dict.
        
        Feature: amt-fields-in-decision-events, Property 6: Insufficient Data Graceful Handling
        **Validates: Requirements 1.5**
        """
        config = AMTCalculatorConfig(
            lookback_candles=100,
            value_area_pct=68.0,
            bin_count=20,
            min_candles=10,  # Default min_candles
        )
        
        # Attempt AMT calculation using _calculate_volume_profile
        result = _calculate_volume_profile(candles, config)
        
        # Property 6: Result should be empty dict for insufficient data
        assert result == {}, (
            f"Expected empty dict for insufficient data ({len(candles)} candles < 10 min_candles), "
            f"but got {result}"
        )
    
    @given(candles=insufficient_candle_list_strategy(min_candles=10))
    @settings(max_examples=100)
    def test_property_6_no_exception_raised_for_insufficient_data(
        self,
        candles: List[Dict[str, Any]],
    ):
        """Property 6: No exception raised for insufficient data.
        
        *For any* AMT calculation request with fewer than min_candles,
        the pipeline SHALL continue processing without raising an exception.
        
        Feature: amt-fields-in-decision-events, Property 6: Insufficient Data Graceful Handling
        **Validates: Requirements 1.5**
        """
        config = AMTCalculatorConfig(
            lookback_candles=100,
            value_area_pct=68.0,
            bin_count=20,
            min_candles=10,
        )
        
        # This should NOT raise any exception
        try:
            result = _calculate_volume_profile(candles, config)
            # If we get here, no exception was raised - test passes
            assert result == {}, f"Expected empty dict, got {result}"
        except Exception as e:
            pytest.fail(
                f"Exception raised for insufficient data ({len(candles)} candles): {type(e).__name__}: {e}"
            )
    
    @given(
        min_candles=min_candles_strategy,
        data=st.data(),
    )
    @settings(max_examples=100)
    def test_property_6_with_custom_min_candles(
        self,
        min_candles: int,
        data,
    ):
        """Property 6: Insufficient data handling with custom min_candles.
        
        *For any* min_candles configuration value, AMT calculation with fewer
        candles SHALL return None/empty and not raise exceptions.
        
        Feature: amt-fields-in-decision-events, Property 6: Insufficient Data Graceful Handling
        **Validates: Requirements 1.5**
        """
        # Generate candles with 0 to min_candles-1 items
        candles = data.draw(st.lists(
            candle_strategy(),
            min_size=0,
            max_size=min_candles - 1,
        ))
        
        config = AMTCalculatorConfig(
            lookback_candles=100,
            value_area_pct=68.0,
            bin_count=20,
            min_candles=min_candles,
        )
        
        # This should NOT raise any exception
        try:
            result = _calculate_volume_profile(candles, config)
            # Property 6: Result should be empty dict for insufficient data
            assert result == {}, (
                f"Expected empty dict for insufficient data "
                f"({len(candles)} candles < {min_candles} min_candles), "
                f"but got {result}"
            )
        except Exception as e:
            pytest.fail(
                f"Exception raised for insufficient data "
                f"({len(candles)} candles < {min_candles} min_candles): "
                f"{type(e).__name__}: {e}"
            )


class TestInsufficientDataEdgeCases:
    """Property tests for edge cases with insufficient data.
    
    Feature: amt-fields-in-decision-events, Property 6: Insufficient Data Graceful Handling
    **Validates: Requirements 1.5**
    """
    
    @given(min_candles=min_candles_strategy)
    @settings(max_examples=100)
    def test_property_6_empty_candle_list(self, min_candles: int):
        """Property 6: Empty candle list returns None/empty.
        
        *For any* min_candles configuration, an empty candle list SHALL
        return None/empty and not raise exceptions.
        
        Feature: amt-fields-in-decision-events, Property 6: Insufficient Data Graceful Handling
        **Validates: Requirements 1.5**
        """
        candles: List[Dict[str, Any]] = []
        
        config = AMTCalculatorConfig(
            lookback_candles=100,
            value_area_pct=68.0,
            bin_count=20,
            min_candles=min_candles,
        )
        
        # Test _calculate_volume_profile
        result = _calculate_volume_profile(candles, config)
        assert result == {}, f"Expected empty dict for empty candle list, got {result}"
        
        # Test calculate_volume_profile_from_candles
        vp_config = VolumeProfileConfig(
            bin_count=20,
            value_area_pct=68.0,
            min_data_points=min_candles,
        )
        vp_result = calculate_volume_profile_from_candles(candles, vp_config)
        assert vp_result is None, f"Expected None for empty candle list, got {vp_result}"
    
    @given(min_candles=min_candles_strategy)
    @settings(max_examples=100)
    def test_property_6_exactly_one_less_than_min_candles(
        self,
        min_candles: int,
    ):
        """Property 6: Exactly min_candles-1 candles returns None/empty.
        
        *For any* min_candles configuration, a list with exactly min_candles-1
        candles SHALL return None/empty and not raise exceptions.
        
        Feature: amt-fields-in-decision-events, Property 6: Insufficient Data Graceful Handling
        **Validates: Requirements 1.5**
        """
        # Generate exactly min_candles - 1 candles
        candles = []
        for i in range(min_candles - 1):
            candles.append({
                "open": 50000.0 + i * 10,
                "high": 50100.0 + i * 10,
                "low": 49900.0 + i * 10,
                "close": 50050.0 + i * 10,
                "volume": 1000.0 + i * 100,
                "ts": 1700000000.0 + i * 300,
            })
        
        config = AMTCalculatorConfig(
            lookback_candles=100,
            value_area_pct=68.0,
            bin_count=20,
            min_candles=min_candles,
        )
        
        # Test _calculate_volume_profile
        result = _calculate_volume_profile(candles, config)
        assert result == {}, (
            f"Expected empty dict for {len(candles)} candles "
            f"(min_candles={min_candles}), got {result}"
        )
        
        # Test calculate_volume_profile_from_candles
        vp_config = VolumeProfileConfig(
            bin_count=20,
            value_area_pct=68.0,
            min_data_points=min_candles,
        )
        vp_result = calculate_volume_profile_from_candles(candles, vp_config)
        assert vp_result is None, (
            f"Expected None for {len(candles)} candles "
            f"(min_data_points={min_candles}), got {vp_result}"
        )
    
    @given(
        min_candles=min_candles_strategy,
        data=st.data(),
    )
    @settings(max_examples=100)
    def test_property_6_boundary_exactly_min_candles_succeeds(
        self,
        min_candles: int,
        data,
    ):
        """Boundary test: Exactly min_candles candles should succeed.
        
        This is a boundary test to verify that exactly min_candles candles
        produces a valid result (not None/empty), confirming the threshold
        is correctly implemented.
        
        Feature: amt-fields-in-decision-events, Property 6: Insufficient Data Graceful Handling
        **Validates: Requirements 1.5**
        """
        # Generate exactly min_candles candles
        candles = data.draw(st.lists(
            candle_strategy(),
            min_size=min_candles,
            max_size=min_candles,
        ))
        
        config = AMTCalculatorConfig(
            lookback_candles=100,
            value_area_pct=68.0,
            bin_count=20,
            min_candles=min_candles,
        )
        
        # Test _calculate_volume_profile - should return non-empty dict
        result = _calculate_volume_profile(candles, config)
        assert result != {}, (
            f"Expected non-empty dict for exactly {min_candles} candles "
            f"(min_candles={min_candles}), but got empty dict"
        )
        assert "point_of_control" in result, "Result should contain point_of_control"
        assert "value_area_high" in result, "Result should contain value_area_high"
        assert "value_area_low" in result, "Result should contain value_area_low"


class TestAMTCalculatorStageInsufficientData:
    """Property tests for AMTCalculatorStage with insufficient data.
    
    These tests verify that the AMTCalculatorStage handles insufficient
    data gracefully by setting amt_levels to None and returning CONTINUE.
    
    Feature: amt-fields-in-decision-events, Property 6: Insufficient Data Graceful Handling
    **Validates: Requirements 1.5**
    """
    
    @given(candles=insufficient_candle_list_strategy(min_candles=10))
    @settings(max_examples=100)
    def test_property_6_stage_sets_amt_levels_to_none(
        self,
        candles: List[Dict[str, Any]],
    ):
        """Property 6: AMTCalculatorStage sets amt_levels to None for insufficient data.
        
        *For any* AMT calculation request with fewer than min_candles,
        the AMTCalculatorStage SHALL set ctx.data["amt_levels"] to None.
        
        Feature: amt-fields-in-decision-events, Property 6: Insufficient Data Graceful Handling
        **Validates: Requirements 1.5**
        """
        import asyncio
        
        config = AMTCalculatorConfig(
            lookback_candles=100,
            value_area_pct=68.0,
            bin_count=20,
            min_candles=10,
        )
        
        stage = AMTCalculatorStage(config=config)
        
        # Create a mock StageContext
        ctx = StageContext(
            symbol="BTCUSDT",
            data={
                "candles": candles,
                "features": {"price": 50000.0},
            },
        )
        
        # Run the stage
        result = asyncio.run(stage.run(ctx))
        
        # Property 6: amt_levels should be None for insufficient data
        assert ctx.data.get("amt_levels") is None, (
            f"Expected amt_levels to be None for insufficient data "
            f"({len(candles)} candles < 10 min_candles), "
            f"but got {ctx.data.get('amt_levels')}"
        )
    
    @given(candles=insufficient_candle_list_strategy(min_candles=10))
    @settings(max_examples=100)
    def test_property_6_stage_returns_continue(
        self,
        candles: List[Dict[str, Any]],
    ):
        """Property 6: AMTCalculatorStage returns CONTINUE for insufficient data.
        
        *For any* AMT calculation request with fewer than min_candles,
        the pipeline SHALL continue processing without blocking.
        
        Feature: amt-fields-in-decision-events, Property 6: Insufficient Data Graceful Handling
        **Validates: Requirements 1.5**
        """
        import asyncio
        
        config = AMTCalculatorConfig(
            lookback_candles=100,
            value_area_pct=68.0,
            bin_count=20,
            min_candles=10,
        )
        
        stage = AMTCalculatorStage(config=config)
        
        # Create a mock StageContext
        ctx = StageContext(
            symbol="BTCUSDT",
            data={
                "candles": candles,
                "features": {"price": 50000.0},
            },
        )
        
        # Run the stage
        result = asyncio.run(stage.run(ctx))
        
        # Property 6: Stage should return CONTINUE (never block pipeline)
        assert result == StageResult.CONTINUE, (
            f"Expected StageResult.CONTINUE for insufficient data "
            f"({len(candles)} candles < 10 min_candles), "
            f"but got {result}"
        )
    
    @given(candles=insufficient_candle_list_strategy(min_candles=10))
    @settings(max_examples=100)
    def test_property_6_stage_no_exception(
        self,
        candles: List[Dict[str, Any]],
    ):
        """Property 6: AMTCalculatorStage does not raise exceptions for insufficient data.
        
        *For any* AMT calculation request with fewer than min_candles,
        the pipeline SHALL continue processing without raising an exception.
        
        Feature: amt-fields-in-decision-events, Property 6: Insufficient Data Graceful Handling
        **Validates: Requirements 1.5**
        """
        import asyncio
        
        config = AMTCalculatorConfig(
            lookback_candles=100,
            value_area_pct=68.0,
            bin_count=20,
            min_candles=10,
        )
        
        stage = AMTCalculatorStage(config=config)
        
        # Create a mock StageContext
        ctx = StageContext(
            symbol="BTCUSDT",
            data={
                "candles": candles,
                "features": {"price": 50000.0},
            },
        )
        
        # This should NOT raise any exception
        try:
            result = asyncio.run(stage.run(ctx))
            # If we get here, no exception was raised - test passes
            assert result == StageResult.CONTINUE
        except Exception as e:
            pytest.fail(
                f"Exception raised for insufficient data "
                f"({len(candles)} candles): {type(e).__name__}: {e}"
            )
