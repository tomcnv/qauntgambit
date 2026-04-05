"""
Unit tests for AMT Calculator module.

Tests the position classification, distance calculations, and other AMT calculation functions.
"""

import pytest

from quantgambit.signals.stages.amt_calculator import (
    _classify_position,
    _calculate_distances,
    _calculate_rotation_factor,
    AMTCalculatorConfig,
    AMTLevels,
)


class TestClassifyPosition:
    """Tests for _classify_position function."""

    def test_price_above_vah_returns_above(self):
        """When price > VAH, should return 'above'. (Requirement 2.1)"""
        result = _classify_position(
            price=100.0,
            value_area_high=90.0,
            value_area_low=80.0,
        )
        assert result == "above"

    def test_price_below_val_returns_below(self):
        """When price < VAL, should return 'below'. (Requirement 2.2)"""
        result = _classify_position(
            price=70.0,
            value_area_high=90.0,
            value_area_low=80.0,
        )
        assert result == "below"

    def test_price_inside_value_area_returns_inside(self):
        """When VAL <= price <= VAH, should return 'inside'. (Requirement 2.3)"""
        result = _classify_position(
            price=85.0,
            value_area_high=90.0,
            value_area_low=80.0,
        )
        assert result == "inside"

    def test_price_at_vah_boundary_returns_inside(self):
        """When price == VAH, should return 'inside' (inclusive). (Requirement 2.3)"""
        result = _classify_position(
            price=90.0,
            value_area_high=90.0,
            value_area_low=80.0,
        )
        assert result == "inside"

    def test_price_at_val_boundary_returns_inside(self):
        """When price == VAL, should return 'inside' (inclusive). (Requirement 2.3)"""
        result = _classify_position(
            price=80.0,
            value_area_high=90.0,
            value_area_low=80.0,
        )
        assert result == "inside"

    def test_vah_none_returns_inside(self):
        """When VAH is None, should default to 'inside'. (Requirement 2.4)"""
        result = _classify_position(
            price=100.0,
            value_area_high=None,
            value_area_low=80.0,
        )
        assert result == "inside"

    def test_val_none_returns_inside(self):
        """When VAL is None, should default to 'inside'. (Requirement 2.4)"""
        result = _classify_position(
            price=70.0,
            value_area_high=90.0,
            value_area_low=None,
        )
        assert result == "inside"

    def test_both_none_returns_inside(self):
        """When both VAH and VAL are None, should default to 'inside'. (Requirement 2.4)"""
        result = _classify_position(
            price=100.0,
            value_area_high=None,
            value_area_low=None,
        )
        assert result == "inside"

    def test_narrow_value_area(self):
        """Test with a very narrow value area."""
        # Price above narrow area
        assert _classify_position(100.0, 90.01, 90.0) == "above"
        # Price below narrow area
        assert _classify_position(89.99, 90.01, 90.0) == "below"
        # Price inside narrow area
        assert _classify_position(90.005, 90.01, 90.0) == "inside"

    def test_large_price_values(self):
        """Test with large price values (e.g., BTC prices)."""
        result = _classify_position(
            price=50000.0,
            value_area_high=49000.0,
            value_area_low=48000.0,
        )
        assert result == "above"

    def test_small_price_values(self):
        """Test with small price values (e.g., low-cap tokens)."""
        result = _classify_position(
            price=0.00001,
            value_area_high=0.00002,
            value_area_low=0.000005,
        )
        assert result == "inside"


class TestCalculateDistances:
    """Tests for _calculate_distances function."""

    def test_distance_to_val_absolute(self):
        """distance_to_val should be absolute distance |price - VAL|. (Requirement 3.1)"""
        # Price above VAL
        result = _calculate_distances(
            price=100.0,
            point_of_control=90.0,
            value_area_high=95.0,
            value_area_low=85.0,
        )
        assert result["distance_to_val"] == 15.0  # |100 - 85| = 15
        
        # Price below VAL
        result = _calculate_distances(
            price=80.0,
            point_of_control=90.0,
            value_area_high=95.0,
            value_area_low=85.0,
        )
        assert result["distance_to_val"] == 5.0  # |80 - 85| = 5

    def test_distance_to_vah_absolute(self):
        """distance_to_vah should be absolute distance |price - VAH|. (Requirement 3.2)"""
        # Price above VAH
        result = _calculate_distances(
            price=100.0,
            point_of_control=90.0,
            value_area_high=95.0,
            value_area_low=85.0,
        )
        assert result["distance_to_vah"] == 5.0  # |100 - 95| = 5
        
        # Price below VAH
        result = _calculate_distances(
            price=80.0,
            point_of_control=90.0,
            value_area_high=95.0,
            value_area_low=85.0,
        )
        assert result["distance_to_vah"] == 15.0  # |80 - 95| = 15

    def test_distance_to_poc_signed_positive(self):
        """distance_to_poc should be positive when price > POC. (Requirement 3.3)"""
        result = _calculate_distances(
            price=100.0,
            point_of_control=90.0,
            value_area_high=95.0,
            value_area_low=85.0,
        )
        assert result["distance_to_poc"] == 10.0  # 100 - 90 = 10 (positive)

    def test_distance_to_poc_signed_negative(self):
        """distance_to_poc should be negative when price < POC. (Requirement 3.3)"""
        result = _calculate_distances(
            price=80.0,
            point_of_control=90.0,
            value_area_high=95.0,
            value_area_low=85.0,
        )
        assert result["distance_to_poc"] == -10.0  # 80 - 90 = -10 (negative)

    def test_distance_to_poc_zero_when_equal(self):
        """distance_to_poc should be zero when price equals POC. (Requirement 3.3)"""
        result = _calculate_distances(
            price=90.0,
            point_of_control=90.0,
            value_area_high=95.0,
            value_area_low=85.0,
        )
        assert result["distance_to_poc"] == 0.0

    def test_val_none_returns_zero(self):
        """distance_to_val should be 0.0 when VAL is None. (Requirement 3.4)"""
        result = _calculate_distances(
            price=100.0,
            point_of_control=90.0,
            value_area_high=95.0,
            value_area_low=None,
        )
        assert result["distance_to_val"] == 0.0
        # Other distances should still be calculated
        assert result["distance_to_vah"] == 5.0
        assert result["distance_to_poc"] == 10.0

    def test_vah_none_returns_zero(self):
        """distance_to_vah should be 0.0 when VAH is None. (Requirement 3.4)"""
        result = _calculate_distances(
            price=100.0,
            point_of_control=90.0,
            value_area_high=None,
            value_area_low=85.0,
        )
        assert result["distance_to_vah"] == 0.0
        # Other distances should still be calculated
        assert result["distance_to_val"] == 15.0
        assert result["distance_to_poc"] == 10.0

    def test_poc_none_returns_zero(self):
        """distance_to_poc should be 0.0 when POC is None. (Requirement 3.4)"""
        result = _calculate_distances(
            price=100.0,
            point_of_control=None,
            value_area_high=95.0,
            value_area_low=85.0,
        )
        assert result["distance_to_poc"] == 0.0
        # Other distances should still be calculated
        assert result["distance_to_val"] == 15.0
        assert result["distance_to_vah"] == 5.0

    def test_all_none_returns_all_zeros(self):
        """All distances should be 0.0 when all AMT levels are None. (Requirement 3.4)"""
        result = _calculate_distances(
            price=100.0,
            point_of_control=None,
            value_area_high=None,
            value_area_low=None,
        )
        assert result["distance_to_val"] == 0.0
        assert result["distance_to_vah"] == 0.0
        assert result["distance_to_poc"] == 0.0

    def test_large_price_values(self):
        """Test with large price values (e.g., BTC prices)."""
        result = _calculate_distances(
            price=50000.0,
            point_of_control=49500.0,
            value_area_high=49800.0,
            value_area_low=49200.0,
        )
        assert result["distance_to_val"] == 800.0  # |50000 - 49200| = 800
        assert result["distance_to_vah"] == 200.0  # |50000 - 49800| = 200
        assert result["distance_to_poc"] == 500.0  # 50000 - 49500 = 500

    def test_small_price_values(self):
        """Test with small price values (e.g., low-cap tokens)."""
        result = _calculate_distances(
            price=0.00001,
            point_of_control=0.000012,
            value_area_high=0.000015,
            value_area_low=0.000008,
        )
        assert result["distance_to_val"] == pytest.approx(0.000002, rel=1e-9)
        assert result["distance_to_vah"] == pytest.approx(0.000005, rel=1e-9)
        assert result["distance_to_poc"] == pytest.approx(-0.000002, rel=1e-9)

    def test_price_at_val_boundary(self):
        """Test when price is exactly at VAL."""
        result = _calculate_distances(
            price=85.0,
            point_of_control=90.0,
            value_area_high=95.0,
            value_area_low=85.0,
        )
        assert result["distance_to_val"] == 0.0
        assert result["distance_to_vah"] == 10.0
        assert result["distance_to_poc"] == -5.0

    def test_price_at_vah_boundary(self):
        """Test when price is exactly at VAH."""
        result = _calculate_distances(
            price=95.0,
            point_of_control=90.0,
            value_area_high=95.0,
            value_area_low=85.0,
        )
        assert result["distance_to_val"] == 10.0
        assert result["distance_to_vah"] == 0.0
        assert result["distance_to_poc"] == 5.0

    def test_price_at_poc(self):
        """Test when price is exactly at POC."""
        result = _calculate_distances(
            price=90.0,
            point_of_control=90.0,
            value_area_high=95.0,
            value_area_low=85.0,
        )
        assert result["distance_to_val"] == 5.0
        assert result["distance_to_vah"] == 5.0
        assert result["distance_to_poc"] == 0.0

    def test_returns_dict_with_correct_keys(self):
        """Result should be a dict with exactly the expected keys (including bps fields)."""
        result = _calculate_distances(
            price=100.0,
            point_of_control=90.0,
            value_area_high=95.0,
            value_area_low=85.0,
        )
        assert isinstance(result, dict)
        expected_keys = {
            # Legacy keys
            "distance_to_val", "distance_to_vah", "distance_to_poc",
            # BPS keys (Requirement 1.3)
            "distance_to_val_bps", "distance_to_vah_bps", "distance_to_poc_bps", "va_width_bps"
        }
        assert set(result.keys()) == expected_keys


class TestCalculateRotationFactor:
    """Tests for _calculate_rotation_factor function."""

    def test_base_calculation_from_orderflow(self):
        """Base rotation should be orderflow_imbalance * scale_factor. (Requirement 4.1)"""
        # Positive orderflow imbalance with no trend
        result = _calculate_rotation_factor(
            orderflow_imbalance=0.5,
            trend_direction=None,
            trend_strength=0.0,
        )
        assert result == 2.5  # 0.5 * 5.0 = 2.5

        # Negative orderflow imbalance with no trend
        result = _calculate_rotation_factor(
            orderflow_imbalance=-0.4,
            trend_direction=None,
            trend_strength=0.0,
        )
        assert result == -2.0  # -0.4 * 5.0 = -2.0

    def test_trend_up_adds_contribution(self):
        """When trend is 'up', should add trend_strength * contribution_factor. (Requirement 4.2)"""
        result = _calculate_rotation_factor(
            orderflow_imbalance=0.5,
            trend_direction="up",
            trend_strength=0.8,
        )
        # Base: 0.5 * 5.0 = 2.5
        # Trend contribution: 0.8 * 5.0 = 4.0
        # Total: 2.5 + 4.0 = 6.5
        assert result == 6.5

    def test_trend_down_subtracts_contribution(self):
        """When trend is 'down', should subtract trend_strength * contribution_factor. (Requirement 4.3)"""
        result = _calculate_rotation_factor(
            orderflow_imbalance=0.5,
            trend_direction="down",
            trend_strength=0.8,
        )
        # Base: 0.5 * 5.0 = 2.5
        # Trend contribution: -0.8 * 5.0 = -4.0
        # Total: 2.5 - 4.0 = -1.5
        assert result == -1.5

    def test_clamp_to_positive_15(self):
        """Result should be clamped to maximum +15. (Requirement 4.4)"""
        # Large positive orderflow + strong uptrend should clamp to 15
        result = _calculate_rotation_factor(
            orderflow_imbalance=2.0,  # Would give 10.0 base
            trend_direction="up",
            trend_strength=2.0,  # Would add 10.0
        )
        # Unclamped: 10.0 + 10.0 = 20.0
        # Clamped: 15.0
        assert result == 15.0

    def test_clamp_to_negative_15(self):
        """Result should be clamped to minimum -15. (Requirement 4.4)"""
        # Large negative orderflow + strong downtrend should clamp to -15
        result = _calculate_rotation_factor(
            orderflow_imbalance=-2.0,  # Would give -10.0 base
            trend_direction="down",
            trend_strength=2.0,  # Would subtract 10.0
        )
        # Unclamped: -10.0 - 10.0 = -20.0
        # Clamped: -15.0
        assert result == -15.0

    def test_no_trend_direction_no_contribution(self):
        """When trend_direction is None, no trend contribution should be applied."""
        result = _calculate_rotation_factor(
            orderflow_imbalance=0.3,
            trend_direction=None,
            trend_strength=1.0,  # Should be ignored
        )
        # Only base: 0.3 * 5.0 = 1.5
        assert result == 1.5

    def test_unknown_trend_direction_no_contribution(self):
        """When trend_direction is unknown value, no trend contribution should be applied."""
        result = _calculate_rotation_factor(
            orderflow_imbalance=0.3,
            trend_direction="sideways",  # Unknown value
            trend_strength=1.0,  # Should be ignored
        )
        # Only base: 0.3 * 5.0 = 1.5
        assert result == 1.5

    def test_zero_orderflow_with_uptrend(self):
        """Zero orderflow with uptrend should only have trend contribution."""
        result = _calculate_rotation_factor(
            orderflow_imbalance=0.0,
            trend_direction="up",
            trend_strength=0.6,
        )
        # Base: 0.0 * 5.0 = 0.0
        # Trend contribution: 0.6 * 5.0 = 3.0
        # Total: 0.0 + 3.0 = 3.0
        assert result == 3.0

    def test_zero_orderflow_with_downtrend(self):
        """Zero orderflow with downtrend should only have negative trend contribution."""
        result = _calculate_rotation_factor(
            orderflow_imbalance=0.0,
            trend_direction="down",
            trend_strength=0.6,
        )
        # Base: 0.0 * 5.0 = 0.0
        # Trend contribution: -0.6 * 5.0 = -3.0
        # Total: 0.0 - 3.0 = -3.0
        assert result == -3.0

    def test_zero_trend_strength_no_contribution(self):
        """Zero trend_strength should result in no trend contribution."""
        result = _calculate_rotation_factor(
            orderflow_imbalance=0.4,
            trend_direction="up",
            trend_strength=0.0,
        )
        # Base: 0.4 * 5.0 = 2.0
        # Trend contribution: 0.0 * 5.0 = 0.0
        # Total: 2.0 + 0.0 = 2.0
        assert result == 2.0

    def test_custom_scale_factor(self):
        """Custom scale_factor should be applied to orderflow."""
        result = _calculate_rotation_factor(
            orderflow_imbalance=0.5,
            trend_direction=None,
            trend_strength=0.0,
            scale_factor=10.0,  # Custom scale
        )
        # Base: 0.5 * 10.0 = 5.0
        assert result == 5.0

    def test_custom_contribution_factor(self):
        """Custom contribution_factor should be applied to trend."""
        result = _calculate_rotation_factor(
            orderflow_imbalance=0.0,
            trend_direction="up",
            trend_strength=0.5,
            contribution_factor=10.0,  # Custom contribution
        )
        # Trend contribution: 0.5 * 10.0 = 5.0
        assert result == 5.0

    def test_negative_orderflow_with_uptrend(self):
        """Negative orderflow with uptrend can result in positive or negative."""
        result = _calculate_rotation_factor(
            orderflow_imbalance=-0.3,
            trend_direction="up",
            trend_strength=0.8,
        )
        # Base: -0.3 * 5.0 = -1.5
        # Trend contribution: 0.8 * 5.0 = 4.0
        # Total: -1.5 + 4.0 = 2.5
        assert result == 2.5

    def test_positive_orderflow_with_downtrend(self):
        """Positive orderflow with downtrend can result in positive or negative."""
        result = _calculate_rotation_factor(
            orderflow_imbalance=0.3,
            trend_direction="down",
            trend_strength=0.8,
        )
        # Base: 0.3 * 5.0 = 1.5
        # Trend contribution: -0.8 * 5.0 = -4.0
        # Total: 1.5 - 4.0 = -2.5
        assert result == -2.5

    def test_result_at_boundary_15(self):
        """Test when result is exactly at +15 boundary."""
        result = _calculate_rotation_factor(
            orderflow_imbalance=1.0,  # 5.0 base
            trend_direction="up",
            trend_strength=2.0,  # 10.0 contribution
        )
        # Total: 5.0 + 10.0 = 15.0 (exactly at boundary)
        assert result == 15.0

    def test_result_at_boundary_negative_15(self):
        """Test when result is exactly at -15 boundary."""
        result = _calculate_rotation_factor(
            orderflow_imbalance=-1.0,  # -5.0 base
            trend_direction="down",
            trend_strength=2.0,  # -10.0 contribution
        )
        # Total: -5.0 - 10.0 = -15.0 (exactly at boundary)
        assert result == -15.0

    def test_typical_market_values(self):
        """Test with typical market values (imbalance in [-1, 1], strength in [0, 1])."""
        # Bullish scenario: positive imbalance, uptrend
        result = _calculate_rotation_factor(
            orderflow_imbalance=0.6,
            trend_direction="up",
            trend_strength=0.7,
        )
        # Base: 0.6 * 5.0 = 3.0
        # Trend: 0.7 * 5.0 = 3.5
        # Total: 6.5
        assert result == 6.5

        # Bearish scenario: negative imbalance, downtrend
        result = _calculate_rotation_factor(
            orderflow_imbalance=-0.6,
            trend_direction="down",
            trend_strength=0.7,
        )
        # Base: -0.6 * 5.0 = -3.0
        # Trend: -0.7 * 5.0 = -3.5
        # Total: -6.5
        assert result == -6.5

    def test_returns_float(self):
        """Result should always be a float."""
        result = _calculate_rotation_factor(
            orderflow_imbalance=0.5,
            trend_direction="up",
            trend_strength=0.5,
        )
        assert isinstance(result, float)


class TestCandleCache:
    """Tests for CandleCache class."""

    def test_add_and_get_candles(self):
        """Test adding and retrieving candles from cache."""
        from quantgambit.signals.stages.amt_calculator import CandleCache
        
        cache = CandleCache(max_candles=100)
        
        # Add some candles
        for i in range(5):
            cache.add_candle("BTCUSDT", {
                "open": 50000 + i,
                "high": 50100 + i,
                "low": 49900 + i,
                "close": 50050 + i,
                "volume": 100 + i,
                "ts": 1000 + i,
            })
        
        # Get candles
        candles = cache.get_recent_candles("BTCUSDT", count=10)
        assert len(candles) == 5
        assert candles[0]["ts"] == 1000  # Oldest first
        assert candles[-1]["ts"] == 1004  # Newest last

    def test_max_candles_limit(self):
        """Test that cache respects max_candles limit."""
        from quantgambit.signals.stages.amt_calculator import CandleCache
        
        cache = CandleCache(max_candles=3)
        
        # Add more candles than max
        for i in range(5):
            cache.add_candle("BTCUSDT", {"ts": i, "volume": i})
        
        # Should only have last 3
        candles = cache.get_recent_candles("BTCUSDT", count=10)
        assert len(candles) == 3
        assert candles[0]["ts"] == 2  # Oldest retained
        assert candles[-1]["ts"] == 4  # Newest

    def test_get_candles_with_count_limit(self):
        """Test getting limited number of candles."""
        from quantgambit.signals.stages.amt_calculator import CandleCache
        
        cache = CandleCache(max_candles=100)
        
        for i in range(10):
            cache.add_candle("BTCUSDT", {"ts": i, "volume": i})
        
        # Request fewer than available
        candles = cache.get_recent_candles("BTCUSDT", count=3)
        assert len(candles) == 3
        assert candles[0]["ts"] == 7  # Most recent 3
        assert candles[-1]["ts"] == 9

    def test_get_candles_before_timestamp(self):
        """Test filtering candles by timestamp."""
        from quantgambit.signals.stages.amt_calculator import CandleCache
        
        cache = CandleCache(max_candles=100)
        
        for i in range(10):
            cache.add_candle("BTCUSDT", {"ts": i, "volume": i})
        
        # Get candles before ts=5
        candles = cache.get_recent_candles("BTCUSDT", count=10, before_ts=5)
        assert len(candles) == 6  # ts 0-5 inclusive
        assert candles[-1]["ts"] == 5

    def test_get_candles_unknown_symbol(self):
        """Test getting candles for unknown symbol returns empty list."""
        from quantgambit.signals.stages.amt_calculator import CandleCache
        
        cache = CandleCache(max_candles=100)
        candles = cache.get_recent_candles("UNKNOWN", count=10)
        assert candles == []

    def test_clear_specific_symbol(self):
        """Test clearing candles for a specific symbol."""
        from quantgambit.signals.stages.amt_calculator import CandleCache
        
        cache = CandleCache(max_candles=100)
        cache.add_candle("BTCUSDT", {"ts": 1})
        cache.add_candle("ETHUSDT", {"ts": 2})
        
        cache.clear("BTCUSDT")
        
        assert cache.get_candle_count("BTCUSDT") == 0
        assert cache.get_candle_count("ETHUSDT") == 1

    def test_clear_all(self):
        """Test clearing all candles."""
        from quantgambit.signals.stages.amt_calculator import CandleCache
        
        cache = CandleCache(max_candles=100)
        cache.add_candle("BTCUSDT", {"ts": 1})
        cache.add_candle("ETHUSDT", {"ts": 2})
        
        cache.clear()
        
        assert cache.get_candle_count("BTCUSDT") == 0
        assert cache.get_candle_count("ETHUSDT") == 0

    def test_get_candle_count(self):
        """Test getting candle count for a symbol."""
        from quantgambit.signals.stages.amt_calculator import CandleCache
        
        cache = CandleCache(max_candles=100)
        
        assert cache.get_candle_count("BTCUSDT") == 0
        
        cache.add_candle("BTCUSDT", {"ts": 1})
        cache.add_candle("BTCUSDT", {"ts": 2})
        
        assert cache.get_candle_count("BTCUSDT") == 2


class TestAMTCalculatorStage:
    """Tests for AMTCalculatorStage class."""

    @pytest.fixture
    def sample_candles(self):
        """Generate sample candle data for testing."""
        candles = []
        base_price = 50000.0
        for i in range(20):
            # Create candles with varying prices and volumes
            price_offset = (i % 5) * 100 - 200  # -200 to +200
            candles.append({
                "open": base_price + price_offset,
                "high": base_price + price_offset + 50,
                "low": base_price + price_offset - 50,
                "close": base_price + price_offset + 25,
                "volume": 100 + (i % 3) * 50,  # 100, 150, 200
                "ts": 1000 + i * 300,  # 5-minute intervals
            })
        return candles

    @pytest.fixture
    def stage_context(self, sample_candles):
        """Create a StageContext for testing."""
        from quantgambit.signals.pipeline import StageContext
        
        return StageContext(
            symbol="BTCUSDT",
            data={
                "candles": sample_candles,
                "features": {
                    "price": 50000.0,
                    "orderflow_imbalance": 0.3,
                    "trend_direction": "up",
                    "trend_strength": 0.5,
                },
                "market_context": {},
            },
        )

    @pytest.mark.asyncio
    async def test_run_with_sufficient_data(self, stage_context):
        """Test stage run with sufficient candle data."""
        from quantgambit.signals.stages.amt_calculator import (
            AMTCalculatorStage,
            AMTCalculatorConfig,
            AMTLevels,
        )
        from quantgambit.signals.pipeline import StageResult
        
        config = AMTCalculatorConfig(min_candles=10)
        stage = AMTCalculatorStage(config=config)
        
        result = await stage.run(stage_context)
        
        # Should return CONTINUE
        assert result == StageResult.CONTINUE
        
        # Should have AMT levels in context
        amt_levels = stage_context.data.get("amt_levels")
        assert amt_levels is not None
        assert isinstance(amt_levels, AMTLevels)
        
        # Verify AMT levels are populated
        assert amt_levels.point_of_control is not None
        assert amt_levels.value_area_high is not None
        assert amt_levels.value_area_low is not None
        assert amt_levels.position_in_value in ("above", "below", "inside")
        assert amt_levels.candle_count == 20

    @pytest.mark.asyncio
    async def test_run_with_insufficient_data(self):
        """Test stage run with insufficient candle data. (Requirement 1.5)"""
        from quantgambit.signals.stages.amt_calculator import (
            AMTCalculatorStage,
            AMTCalculatorConfig,
        )
        from quantgambit.signals.pipeline import StageContext, StageResult
        
        config = AMTCalculatorConfig(min_candles=10)
        stage = AMTCalculatorStage(config=config)
        
        # Create context with only 5 candles (less than min_candles)
        ctx = StageContext(
            symbol="BTCUSDT",
            data={
                "candles": [{"open": 100, "high": 101, "low": 99, "close": 100, "volume": 10}] * 5,
                "features": {"price": 100.0},
            },
        )
        
        result = await stage.run(ctx)
        
        # Should return CONTINUE (never block pipeline)
        assert result == StageResult.CONTINUE
        
        # AMT levels should be None
        assert ctx.data.get("amt_levels") is None

    @pytest.mark.asyncio
    async def test_run_with_no_candles(self):
        """Test stage run with no candle data. (Requirement 1.5)"""
        from quantgambit.signals.stages.amt_calculator import AMTCalculatorStage
        from quantgambit.signals.pipeline import StageContext, StageResult
        
        stage = AMTCalculatorStage()
        
        ctx = StageContext(
            symbol="BTCUSDT",
            data={
                "features": {"price": 100.0},
            },
        )
        
        result = await stage.run(ctx)
        
        # Should return CONTINUE
        assert result == StageResult.CONTINUE
        
        # AMT levels should be None
        assert ctx.data.get("amt_levels") is None

    @pytest.mark.asyncio
    async def test_run_with_no_price(self, sample_candles):
        """Test stage run when no price is available."""
        from quantgambit.signals.stages.amt_calculator import AMTCalculatorStage
        from quantgambit.signals.pipeline import StageContext, StageResult
        
        stage = AMTCalculatorStage()
        
        ctx = StageContext(
            symbol="BTCUSDT",
            data={
                "candles": sample_candles,
                "features": {},  # No price
                "market_context": {},
            },
        )
        
        result = await stage.run(ctx)
        
        # Should return CONTINUE
        assert result == StageResult.CONTINUE
        
        # AMT levels should be None
        assert ctx.data.get("amt_levels") is None

    @pytest.mark.asyncio
    async def test_run_uses_candle_cache(self, sample_candles):
        """Test stage uses candle cache when available."""
        from quantgambit.signals.stages.amt_calculator import (
            AMTCalculatorStage,
            CandleCache,
            AMTLevels,
        )
        from quantgambit.signals.pipeline import StageContext, StageResult
        
        # Create cache with candles
        cache = CandleCache(max_candles=100)
        for candle in sample_candles:
            cache.add_candle("BTCUSDT", candle)
        
        stage = AMTCalculatorStage(candle_cache=cache)
        
        # Context without candles - should use cache
        ctx = StageContext(
            symbol="BTCUSDT",
            data={
                "features": {"price": 50000.0},
            },
        )
        
        result = await stage.run(ctx)
        
        assert result == StageResult.CONTINUE
        assert ctx.data.get("amt_levels") is not None
        assert isinstance(ctx.data["amt_levels"], AMTLevels)

    @pytest.mark.asyncio
    async def test_run_calculates_rotation_factor(self, stage_context):
        """Test that rotation factor is calculated correctly."""
        from quantgambit.signals.stages.amt_calculator import AMTCalculatorStage
        from quantgambit.signals.pipeline import StageResult
        
        stage = AMTCalculatorStage()
        
        result = await stage.run(stage_context)
        
        assert result == StageResult.CONTINUE
        
        amt_levels = stage_context.data.get("amt_levels")
        assert amt_levels is not None
        
        # With orderflow_imbalance=0.3, trend_direction="up", trend_strength=0.5
        # Expected: 0.3 * 5.0 + 0.5 * 5.0 = 1.5 + 2.5 = 4.0
        assert amt_levels.rotation_factor == pytest.approx(4.0, rel=0.01)

    @pytest.mark.asyncio
    async def test_run_stores_amt_levels_in_context(self, stage_context):
        """Test that AMT levels are stored in ctx.data['amt_levels']. (Requirement 1.4)"""
        from quantgambit.signals.stages.amt_calculator import AMTCalculatorStage, AMTLevels
        from quantgambit.signals.pipeline import StageResult
        
        stage = AMTCalculatorStage()
        
        result = await stage.run(stage_context)
        
        assert result == StageResult.CONTINUE
        assert "amt_levels" in stage_context.data
        assert isinstance(stage_context.data["amt_levels"], AMTLevels)

    @pytest.mark.asyncio
    async def test_run_always_returns_continue(self, stage_context):
        """Test that stage always returns CONTINUE. (Requirement 1.5)"""
        from quantgambit.signals.stages.amt_calculator import AMTCalculatorStage
        from quantgambit.signals.pipeline import StageContext, StageResult
        
        stage = AMTCalculatorStage()
        
        # Test with valid data
        result = await stage.run(stage_context)
        assert result == StageResult.CONTINUE
        
        # Test with no candles
        ctx_no_candles = StageContext(
            symbol="BTCUSDT",
            data={"features": {"price": 100.0}},
        )
        result = await stage.run(ctx_no_candles)
        assert result == StageResult.CONTINUE
        
        # Test with no price
        ctx_no_price = StageContext(
            symbol="BTCUSDT",
            data={"candles": [{"open": 100, "high": 101, "low": 99, "close": 100, "volume": 10}] * 20},
        )
        result = await stage.run(ctx_no_price)
        assert result == StageResult.CONTINUE

    def test_stage_name(self):
        """Test that stage has correct name."""
        from quantgambit.signals.stages.amt_calculator import AMTCalculatorStage
        
        stage = AMTCalculatorStage()
        assert stage.name == "amt_calculator"

    def test_default_config(self):
        """Test that stage uses default config when none provided."""
        from quantgambit.signals.stages.amt_calculator import (
            AMTCalculatorStage,
            AMTCalculatorConfig,
        )
        
        stage = AMTCalculatorStage()
        
        assert stage.config is not None
        assert isinstance(stage.config, AMTCalculatorConfig)
        assert stage.config.lookback_candles == 100
        assert stage.config.min_candles == 10

    def test_custom_config(self):
        """Test that stage uses custom config when provided."""
        from quantgambit.signals.stages.amt_calculator import (
            AMTCalculatorStage,
            AMTCalculatorConfig,
        )
        
        config = AMTCalculatorConfig(
            lookback_candles=50,
            min_candles=5,
            value_area_pct=70.0,
        )
        stage = AMTCalculatorStage(config=config)
        
        assert stage.config.lookback_candles == 50
        assert stage.config.min_candles == 5
        assert stage.config.value_area_pct == 70.0

    @pytest.mark.asyncio
    async def test_run_with_price_in_market_context(self, sample_candles):
        """Test stage uses price from market_context when not in features."""
        from quantgambit.signals.stages.amt_calculator import AMTCalculatorStage, AMTLevels
        from quantgambit.signals.pipeline import StageContext, StageResult
        
        stage = AMTCalculatorStage()
        
        ctx = StageContext(
            symbol="BTCUSDT",
            data={
                "candles": sample_candles,
                "features": {},  # No price in features
                "market_context": {"price": 50000.0},  # Price in market_context
            },
        )
        
        result = await stage.run(ctx)
        
        assert result == StageResult.CONTINUE
        assert ctx.data.get("amt_levels") is not None
        assert isinstance(ctx.data["amt_levels"], AMTLevels)


class TestCalculateDistancesBps:
    """Tests for BPS distance calculations in _calculate_distances function.
    
    Requirements: 1.3.1, 1.3.2, 1.3.3
    """

    def test_distance_to_poc_bps_uses_canonical_formula(self):
        """distance_to_poc_bps should use (price - poc) / mid_price * 10000."""
        result = _calculate_distances(
            price=100.5,
            point_of_control=100.0,
            value_area_high=101.0,
            value_area_low=99.0,
            mid_price=100.0,
        )
        # (100.5 - 100.0) / 100.0 * 10000 = 50 bps
        assert result["distance_to_poc_bps"] == pytest.approx(50.0)

    def test_distance_to_vah_bps_uses_canonical_formula(self):
        """distance_to_vah_bps should use |price - vah| / mid_price * 10000."""
        result = _calculate_distances(
            price=100.0,
            point_of_control=100.0,
            value_area_high=101.0,
            value_area_low=99.0,
            mid_price=100.0,
        )
        # |100.0 - 101.0| / 100.0 * 10000 = 100 bps
        assert result["distance_to_vah_bps"] == pytest.approx(100.0)

    def test_distance_to_val_bps_uses_canonical_formula(self):
        """distance_to_val_bps should use |price - val| / mid_price * 10000."""
        result = _calculate_distances(
            price=100.0,
            point_of_control=100.0,
            value_area_high=101.0,
            value_area_low=99.0,
            mid_price=100.0,
        )
        # |100.0 - 99.0| / 100.0 * 10000 = 100 bps
        assert result["distance_to_val_bps"] == pytest.approx(100.0)

    def test_va_width_bps_uses_canonical_formula(self):
        """va_width_bps should use (vah - val) / mid_price * 10000."""
        result = _calculate_distances(
            price=100.0,
            point_of_control=100.0,
            value_area_high=101.0,
            value_area_low=99.0,
            mid_price=100.0,
        )
        # (101.0 - 99.0) / 100.0 * 10000 = 200 bps
        assert result["va_width_bps"] == pytest.approx(200.0)

    def test_bps_uses_mid_price_not_reference(self):
        """BPS calculations should use mid_price as denominator, not reference price."""
        # If mid_price differs from reference, result should use mid_price
        result = _calculate_distances(
            price=101.0,
            point_of_control=100.0,
            value_area_high=102.0,
            value_area_low=98.0,
            mid_price=50.0,  # Different from reference prices
        )
        # (101.0 - 100.0) / 50.0 * 10000 = 200 bps (using mid_price=50)
        # NOT (101.0 - 100.0) / 100.0 * 10000 = 100 bps (using reference=100)
        assert result["distance_to_poc_bps"] == pytest.approx(200.0)

    def test_bps_fallback_to_price_when_mid_price_none(self):
        """When mid_price is None, should use price as fallback."""
        result = _calculate_distances(
            price=100.0,
            point_of_control=99.0,
            value_area_high=101.0,
            value_area_low=98.0,
            mid_price=None,
        )
        # (100.0 - 99.0) / 100.0 * 10000 = 100 bps (using price as fallback)
        assert result["distance_to_poc_bps"] == pytest.approx(100.0)

    def test_bps_with_realistic_btc_prices(self):
        """Test BPS calculations with realistic BTC prices."""
        result = _calculate_distances(
            price=50100.0,
            point_of_control=50000.0,
            value_area_high=50200.0,
            value_area_low=49800.0,
            mid_price=50050.0,
        )
        # (50100 - 50000) / 50050 * 10000 = 19.98 bps
        assert result["distance_to_poc_bps"] == pytest.approx(19.98, rel=0.01)
        # (50200 - 49800) / 50050 * 10000 = 79.92 bps
        assert result["va_width_bps"] == pytest.approx(79.92, rel=0.01)

    def test_bps_zero_when_amt_levels_none(self):
        """BPS values should be 0 when AMT levels are None."""
        result = _calculate_distances(
            price=100.0,
            point_of_control=None,
            value_area_high=None,
            value_area_low=None,
            mid_price=100.0,
        )
        assert result["distance_to_poc_bps"] == 0.0
        assert result["distance_to_vah_bps"] == 0.0
        assert result["distance_to_val_bps"] == 0.0
        assert result["va_width_bps"] == 0.0

    def test_distance_to_poc_bps_signed(self):
        """distance_to_poc_bps should be signed (positive when price > POC)."""
        # Price above POC
        result = _calculate_distances(
            price=101.0,
            point_of_control=100.0,
            value_area_high=102.0,
            value_area_low=98.0,
            mid_price=100.0,
        )
        assert result["distance_to_poc_bps"] > 0
        
        # Price below POC
        result = _calculate_distances(
            price=99.0,
            point_of_control=100.0,
            value_area_high=102.0,
            value_area_low=98.0,
            mid_price=100.0,
        )
        assert result["distance_to_poc_bps"] < 0

    def test_distance_to_vah_bps_absolute(self):
        """distance_to_vah_bps should always be absolute (non-negative)."""
        # Price above VAH
        result = _calculate_distances(
            price=103.0,
            point_of_control=100.0,
            value_area_high=102.0,
            value_area_low=98.0,
            mid_price=100.0,
        )
        assert result["distance_to_vah_bps"] >= 0
        
        # Price below VAH
        result = _calculate_distances(
            price=99.0,
            point_of_control=100.0,
            value_area_high=102.0,
            value_area_low=98.0,
            mid_price=100.0,
        )
        assert result["distance_to_vah_bps"] >= 0

    def test_distance_to_val_bps_absolute(self):
        """distance_to_val_bps should always be absolute (non-negative)."""
        # Price above VAL
        result = _calculate_distances(
            price=100.0,
            point_of_control=100.0,
            value_area_high=102.0,
            value_area_low=98.0,
            mid_price=100.0,
        )
        assert result["distance_to_val_bps"] >= 0
        
        # Price below VAL
        result = _calculate_distances(
            price=97.0,
            point_of_control=100.0,
            value_area_high=102.0,
            value_area_low=98.0,
            mid_price=100.0,
        )
        assert result["distance_to_val_bps"] >= 0
