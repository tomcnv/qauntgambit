"""
Unit tests for Parameter Resolver BPS conversion functionality.

Tests the bps conversion and logging features added for Strategy Signal
Architecture Fixes Requirement 1.8.

Requirements: 1.8, 1.2.1, 1.2.2, 1.2.3
"""

import pytest
import logging
from quantgambit.deeptrader_core.types import SymbolCharacteristics
from quantgambit.signals.services.parameter_resolver import (
    AdaptiveParameterResolver,
    ResolvedParameters,
)
from quantgambit.core.unit_converter import pct_to_bps


class TestResolvedParametersBpsFields:
    """Tests for BPS fields in ResolvedParameters."""
    
    def test_bps_fields_calculated_from_pct(self):
        """BPS fields should be calculated from pct values."""
        chars = SymbolCharacteristics.default("BTCUSDT")
        resolver = AdaptiveParameterResolver()
        
        result = resolver.resolve({}, chars)
        
        # Verify bps fields are calculated correctly
        assert result.min_distance_from_poc_bps == pytest.approx(
            pct_to_bps(result.min_distance_from_poc_pct)
        )
        assert result.stop_loss_bps == pytest.approx(
            pct_to_bps(result.stop_loss_pct)
        )
        assert result.take_profit_bps == pytest.approx(
            pct_to_bps(result.take_profit_pct)
        )
    
    def test_bps_fields_in_to_dict(self):
        """BPS fields should be included in to_dict output."""
        chars = SymbolCharacteristics.default("BTCUSDT")
        resolver = AdaptiveParameterResolver()
        
        result = resolver.resolve({}, chars)
        result_dict = result.to_dict()
        
        assert "min_distance_from_poc_bps" in result_dict
        assert "stop_loss_bps" in result_dict
        assert "take_profit_bps" in result_dict
        assert "bps_conversion_logged" in result_dict
    
    def test_bps_conversion_logged_flag(self):
        """bps_conversion_logged flag should be True after resolve."""
        chars = SymbolCharacteristics.default("BTCUSDT")
        resolver = AdaptiveParameterResolver()
        
        result = resolver.resolve({}, chars)
        
        assert result.bps_conversion_logged is True


class TestResolveWithBpsLogging:
    """Tests for resolve_with_bps_logging method."""
    
    def test_logs_bps_conversion(self, caplog):
        """Should log bps conversion details."""
        chars = SymbolCharacteristics.default("BTCUSDT")
        resolver = AdaptiveParameterResolver()
        
        with caplog.at_level(logging.INFO):
            result = resolver.resolve_with_bps_logging({}, chars, "BTCUSDT")
        
        assert "parameter_bps_conversion" in caplog.text or len(caplog.records) > 0
    
    def test_returns_same_result_as_resolve(self):
        """Should return same values as resolve method."""
        chars = SymbolCharacteristics.default("BTCUSDT")
        resolver = AdaptiveParameterResolver()
        
        result1 = resolver.resolve({}, chars)
        result2 = resolver.resolve_with_bps_logging({}, chars, "BTCUSDT")
        
        assert result1.min_distance_from_poc_pct == result2.min_distance_from_poc_pct
        assert result1.min_distance_from_poc_bps == result2.min_distance_from_poc_bps
        assert result1.stop_loss_pct == result2.stop_loss_pct
        assert result1.stop_loss_bps == result2.stop_loss_bps
        assert result1.take_profit_pct == result2.take_profit_pct
        assert result1.take_profit_bps == result2.take_profit_bps


class TestBpsConversionAccuracy:
    """Tests for accuracy of BPS conversion."""
    
    def test_min_distance_conversion(self):
        """min_distance_from_poc_bps should be 10000x min_distance_from_poc_pct."""
        chars = SymbolCharacteristics(
            symbol="BTCUSDT",
            typical_spread_bps=5.0,
            typical_depth_usd=100000.0,
            typical_daily_range_pct=0.02,  # 2%
            typical_atr=1000.0,
            typical_volatility_regime="normal",
            sample_count=1000,
            last_updated_ns=0,
        )
        resolver = AdaptiveParameterResolver()
        
        result = resolver.resolve({}, chars)
        
        # 0.1 * 0.02 = 0.002 (0.2%) = 20 bps
        expected_pct = 0.1 * 0.02  # DEFAULT_POC_DISTANCE_MULTIPLIER * daily_range
        expected_bps = expected_pct * 10000
        
        assert result.min_distance_from_poc_pct == pytest.approx(expected_pct)
        assert result.min_distance_from_poc_bps == pytest.approx(expected_bps)
    
    def test_stop_loss_conversion(self):
        """stop_loss_bps should be 10000x stop_loss_pct."""
        chars = SymbolCharacteristics(
            symbol="BTCUSDT",
            typical_spread_bps=5.0,
            typical_depth_usd=100000.0,
            typical_daily_range_pct=0.02,  # 2%
            typical_atr=1000.0,
            typical_volatility_regime="normal",
            sample_count=1000,
            last_updated_ns=0,
        )
        resolver = AdaptiveParameterResolver()
        
        result = resolver.resolve({}, chars)
        
        raw_pct = resolver.DEFAULT_STOP_LOSS_MULTIPLIER * chars.typical_daily_range_pct
        expected_pct = max(resolver.MIN_STOP_LOSS_PCT, min(resolver.MAX_STOP_LOSS_PCT, raw_pct))
        expected_bps = expected_pct * 10000
        
        assert result.stop_loss_pct == pytest.approx(expected_pct)
        assert result.stop_loss_bps == pytest.approx(expected_bps)
    
    def test_take_profit_conversion(self):
        """take_profit_bps should be 10000x take_profit_pct."""
        chars = SymbolCharacteristics(
            symbol="BTCUSDT",
            typical_spread_bps=5.0,
            typical_depth_usd=100000.0,
            typical_daily_range_pct=0.02,  # 2%
            typical_atr=1000.0,
            typical_volatility_regime="normal",
            sample_count=1000,
            last_updated_ns=0,
        )
        resolver = AdaptiveParameterResolver()
        
        result = resolver.resolve({}, chars)
        
        raw_pct = resolver.DEFAULT_TAKE_PROFIT_MULTIPLIER * chars.typical_daily_range_pct
        expected_pct = max(resolver.MIN_TAKE_PROFIT_PCT, min(resolver.MAX_TAKE_PROFIT_PCT, raw_pct))
        expected_bps = expected_pct * 10000
        
        assert result.take_profit_pct == pytest.approx(expected_pct)
        assert result.take_profit_bps == pytest.approx(expected_bps)


class TestBpsWithBoundsEnforcement:
    """Tests for BPS conversion with bounds enforcement."""
    
    def test_bps_respects_min_bounds(self):
        """BPS values should respect minimum bounds."""
        # Create characteristics that would produce values below minimums
        chars = SymbolCharacteristics(
            symbol="BTCUSDT",
            typical_spread_bps=0.01,  # Very small
            typical_depth_usd=10.0,  # Very small
            typical_daily_range_pct=0.0001,  # Very small (0.01%)
            typical_atr=0.1,
            typical_volatility_regime="low",
            sample_count=1000,
            last_updated_ns=0,
        )
        resolver = AdaptiveParameterResolver()
        
        result = resolver.resolve({}, chars)
        
        # Should be clamped to minimums
        assert result.min_distance_from_poc_pct >= resolver.MIN_POC_DISTANCE_PCT
        assert result.stop_loss_pct >= resolver.MIN_STOP_LOSS_PCT
        assert result.take_profit_pct >= resolver.MIN_TAKE_PROFIT_PCT
        
        # BPS should match the clamped pct values
        assert result.min_distance_from_poc_bps == pytest.approx(
            pct_to_bps(result.min_distance_from_poc_pct)
        )
        assert result.stop_loss_bps == pytest.approx(
            pct_to_bps(result.stop_loss_pct)
        )
        assert result.take_profit_bps == pytest.approx(
            pct_to_bps(result.take_profit_pct)
        )
    
    def test_bps_respects_max_bounds(self):
        """BPS values should respect maximum bounds."""
        # Create characteristics that would produce values above maximums
        chars = SymbolCharacteristics(
            symbol="BTCUSDT",
            typical_spread_bps=1000.0,  # Very large
            typical_depth_usd=100_000_000.0,  # Very large
            typical_daily_range_pct=1.0,  # 100% - very large
            typical_atr=100000.0,
            typical_volatility_regime="high",
            sample_count=1000,
            last_updated_ns=0,
        )
        resolver = AdaptiveParameterResolver()
        
        result = resolver.resolve({}, chars)
        
        # Should be clamped to maximums
        assert result.min_distance_from_poc_pct <= resolver.MAX_POC_DISTANCE_PCT
        assert result.stop_loss_pct <= resolver.MAX_STOP_LOSS_PCT
        assert result.take_profit_pct <= resolver.MAX_TAKE_PROFIT_PCT
        
        # BPS should match the clamped pct values
        assert result.min_distance_from_poc_bps == pytest.approx(
            pct_to_bps(result.min_distance_from_poc_pct)
        )
        assert result.stop_loss_bps == pytest.approx(
            pct_to_bps(result.stop_loss_pct)
        )
        assert result.take_profit_bps == pytest.approx(
            pct_to_bps(result.take_profit_pct)
        )


class TestBpsWithCustomMultipliers:
    """Tests for BPS conversion with custom multipliers."""
    
    def test_custom_poc_distance_multiplier(self):
        """Custom POC distance multiplier should affect BPS value."""
        chars = SymbolCharacteristics(
            symbol="BTCUSDT",
            typical_spread_bps=5.0,
            typical_depth_usd=100000.0,
            typical_daily_range_pct=0.02,  # 2%
            typical_atr=1000.0,
            typical_volatility_regime="normal",
            sample_count=1000,
            last_updated_ns=0,
        )
        resolver = AdaptiveParameterResolver()
        
        # Use custom multiplier
        result = resolver.resolve({"poc_distance_atr_multiplier": 1.0}, chars)
        
        # 1.0 * 0.02 = 0.02 (2%) = 200 bps
        expected_pct = 1.0 * 0.02
        expected_bps = expected_pct * 10000
        
        assert result.min_distance_from_poc_pct == pytest.approx(expected_pct)
        assert result.min_distance_from_poc_bps == pytest.approx(expected_bps)
    
    def test_custom_stop_loss_multiplier(self):
        """Custom stop loss multiplier should affect BPS value."""
        chars = SymbolCharacteristics(
            symbol="BTCUSDT",
            typical_spread_bps=5.0,
            typical_depth_usd=100000.0,
            typical_daily_range_pct=0.02,  # 2%
            typical_atr=1000.0,
            typical_volatility_regime="normal",
            sample_count=1000,
            last_updated_ns=0,
        )
        resolver = AdaptiveParameterResolver()
        
        # Use custom multiplier
        result = resolver.resolve({"stop_loss_atr_multiplier": 0.5}, chars)
        
        # 0.5 * 0.02 = 0.01 (1%) = 100 bps, but resolver applies max bound.
        expected_pct = resolver.MAX_STOP_LOSS_PCT
        expected_bps = resolver.MAX_STOP_LOSS_BPS

        assert result.stop_loss_pct == pytest.approx(expected_pct)
        assert result.stop_loss_bps == pytest.approx(expected_bps)
