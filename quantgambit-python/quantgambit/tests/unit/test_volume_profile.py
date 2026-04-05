"""
Unit tests for the shared volume profile calculation module.

Tests the core volume profile algorithm that is shared between
AMTCalculatorStage (live) and BacktestExecutor (backtest).

Requirements: 8.2 - Algorithm Consistency Between Live and Backtest
"""

import pytest
from quantgambit.core.volume_profile import (
    calculate_volume_profile,
    calculate_volume_profile_from_candles,
    VolumeProfileConfig,
    VolumeProfileResult,
)


class TestCalculateVolumeProfile:
    """Tests for the calculate_volume_profile function."""
    
    def test_basic_calculation(self):
        """Test basic volume profile calculation with valid data."""
        prices = [100.0, 101.0, 102.0, 101.5, 100.5, 101.0, 101.5, 102.0, 101.0, 100.5]
        volumes = [1000.0, 2000.0, 1500.0, 2500.0, 1000.0, 1800.0, 2200.0, 1600.0, 1900.0, 1100.0]
        
        result = calculate_volume_profile(prices, volumes)
        
        assert result is not None
        assert isinstance(result, VolumeProfileResult)
        assert result.point_of_control > 0
        assert result.value_area_low > 0
        assert result.value_area_high > 0
        assert result.value_area_low <= result.point_of_control <= result.value_area_high
    
    def test_empty_prices_returns_none(self):
        """Test that empty prices list returns None."""
        result = calculate_volume_profile([], [])
        assert result is None
    
    def test_insufficient_data_returns_none(self):
        """Test that insufficient data returns None."""
        prices = [100.0, 101.0, 102.0]
        volumes = [1000.0, 2000.0, 1500.0]
        
        config = VolumeProfileConfig(min_data_points=10)
        result = calculate_volume_profile(prices, volumes, config)
        
        assert result is None
    
    def test_mismatched_lengths_returns_none(self):
        """Test that mismatched prices/volumes lengths returns None."""
        prices = [100.0, 101.0, 102.0]
        volumes = [1000.0, 2000.0]
        
        result = calculate_volume_profile(prices, volumes)
        assert result is None
    
    def test_all_same_prices(self):
        """Test handling of all same prices."""
        prices = [100.0] * 10
        volumes = [1000.0] * 10
        
        result = calculate_volume_profile(prices, volumes)
        
        assert result is not None
        assert result.point_of_control == 100.0
        assert result.value_area_low == 100.0
        assert result.value_area_high == 100.0
    
    def test_custom_config(self):
        """Test with custom configuration."""
        prices = [100.0, 101.0, 102.0, 101.5, 100.5, 101.0, 101.5, 102.0, 101.0, 100.5]
        volumes = [1000.0, 2000.0, 1500.0, 2500.0, 1000.0, 1800.0, 2200.0, 1600.0, 1900.0, 1100.0]
        
        config = VolumeProfileConfig(
            bin_count=10,
            value_area_pct=70.0,
            min_data_points=5,
        )
        
        result = calculate_volume_profile(prices, volumes, config)
        
        assert result is not None
        assert result.value_area_low <= result.point_of_control <= result.value_area_high
    
    def test_value_area_contains_poc(self):
        """Test that value area always contains POC (Property 1)."""
        prices = [100.0, 105.0, 110.0, 108.0, 103.0, 107.0, 104.0, 109.0, 102.0, 106.0]
        volumes = [1000.0, 3000.0, 1500.0, 2500.0, 1000.0, 2800.0, 1200.0, 1600.0, 900.0, 2100.0]
        
        result = calculate_volume_profile(prices, volumes)
        
        assert result is not None
        assert result.value_area_low <= result.point_of_control
        assert result.point_of_control <= result.value_area_high
        assert result.value_area_low <= result.value_area_high
    
    def test_to_dict(self):
        """Test the to_dict method."""
        prices = [100.0, 101.0, 102.0, 101.5, 100.5, 101.0, 101.5, 102.0, 101.0, 100.5]
        volumes = [1000.0, 2000.0, 1500.0, 2500.0, 1000.0, 1800.0, 2200.0, 1600.0, 1900.0, 1100.0]
        
        result = calculate_volume_profile(prices, volumes)
        d = result.to_dict()
        
        assert "point_of_control" in d
        assert "value_area_low" in d
        assert "value_area_high" in d
        assert d["point_of_control"] == result.point_of_control
        assert d["value_area_low"] == result.value_area_low
        assert d["value_area_high"] == result.value_area_high


class TestCalculateVolumeProfileFromCandles:
    """Tests for the calculate_volume_profile_from_candles function."""
    
    def test_basic_calculation(self):
        """Test basic calculation from candle data."""
        candles = [
            {"open": 100, "high": 102, "low": 99, "close": 101, "volume": 1000},
            {"open": 101, "high": 103, "low": 100, "close": 102, "volume": 1500},
            {"open": 102, "high": 104, "low": 101, "close": 103, "volume": 2000},
            {"open": 103, "high": 105, "low": 102, "close": 104, "volume": 1800},
            {"open": 104, "high": 106, "low": 103, "close": 105, "volume": 1600},
            {"open": 105, "high": 107, "low": 104, "close": 106, "volume": 1400},
            {"open": 106, "high": 108, "low": 105, "close": 107, "volume": 1200},
            {"open": 107, "high": 109, "low": 106, "close": 108, "volume": 1000},
            {"open": 108, "high": 110, "low": 107, "close": 109, "volume": 800},
            {"open": 109, "high": 111, "low": 108, "close": 110, "volume": 600},
        ]
        
        result = calculate_volume_profile_from_candles(candles)
        
        assert result is not None
        assert isinstance(result, VolumeProfileResult)
        assert result.point_of_control > 0
        assert result.value_area_low <= result.point_of_control <= result.value_area_high
    
    def test_empty_candles_returns_none(self):
        """Test that empty candles list returns None."""
        result = calculate_volume_profile_from_candles([])
        assert result is None
    
    def test_insufficient_candles_returns_none(self):
        """Test that insufficient candles returns None."""
        candles = [
            {"open": 100, "high": 102, "low": 99, "close": 101, "volume": 1000},
            {"open": 101, "high": 103, "low": 100, "close": 102, "volume": 1500},
        ]
        
        config = VolumeProfileConfig(min_data_points=10)
        result = calculate_volume_profile_from_candles(candles, config)
        
        assert result is None
    
    def test_invalid_candles_skipped(self):
        """Test that invalid candles are skipped."""
        candles = [
            {"open": 100, "high": 102, "low": 99, "close": 101, "volume": 1000},
            {"open": 0, "high": 0, "low": 0, "close": 0, "volume": 1500},  # Invalid
            {"open": 101, "high": 103, "low": 100, "close": 102, "volume": 1500},
            {"open": -1, "high": -1, "low": -1, "close": -1, "volume": 1000},  # Invalid
            {"open": 102, "high": 104, "low": 101, "close": 103, "volume": 2000},
            {"open": 103, "high": 105, "low": 102, "close": 104, "volume": 1800},
            {"open": 104, "high": 106, "low": 103, "close": 105, "volume": 1600},
            {"open": 105, "high": 107, "low": 104, "close": 106, "volume": 1400},
            {"open": 106, "high": 108, "low": 105, "close": 107, "volume": 1200},
            {"open": 107, "high": 109, "low": 106, "close": 108, "volume": 1000},
            {"open": 108, "high": 110, "low": 107, "close": 109, "volume": 800},
            {"open": 109, "high": 111, "low": 108, "close": 110, "volume": 600},
        ]
        
        result = calculate_volume_profile_from_candles(candles)
        
        assert result is not None
        # Should have processed 10 valid candles
    
    def test_uses_ohlc_average(self):
        """Test that OHLC average is used as representative price."""
        # Create candles where OHLC average is clearly different from close
        candles = [
            {"open": 100, "high": 110, "low": 90, "close": 100, "volume": 1000},  # avg = 100
        ] * 10
        
        result = calculate_volume_profile_from_candles(candles)
        
        assert result is not None
        # All candles have same OHLC average, so POC should be at that price
        assert result.point_of_control == 100.0


class TestVolumeProfileConfig:
    """Tests for VolumeProfileConfig."""
    
    def test_default_values(self):
        """Test default configuration values."""
        config = VolumeProfileConfig()
        
        assert config.bin_count == 20
        assert config.value_area_pct == 68.0
        assert config.min_data_points == 10
    
    def test_custom_values(self):
        """Test custom configuration values."""
        config = VolumeProfileConfig(
            bin_count=30,
            value_area_pct=70.0,
            min_data_points=5,
        )
        
        assert config.bin_count == 30
        assert config.value_area_pct == 70.0
        assert config.min_data_points == 5


class TestVolumeProfileResult:
    """Tests for VolumeProfileResult."""
    
    def test_frozen_dataclass(self):
        """Test that VolumeProfileResult is immutable."""
        result = VolumeProfileResult(
            point_of_control=100.0,
            value_area_high=105.0,
            value_area_low=95.0,
        )
        
        with pytest.raises(Exception):  # FrozenInstanceError
            result.point_of_control = 101.0
    
    def test_to_dict(self):
        """Test to_dict method."""
        result = VolumeProfileResult(
            point_of_control=100.0,
            value_area_high=105.0,
            value_area_low=95.0,
        )
        
        d = result.to_dict()
        
        assert d == {
            "point_of_control": 100.0,
            "value_area_low": 95.0,
            "value_area_high": 105.0,
        }
