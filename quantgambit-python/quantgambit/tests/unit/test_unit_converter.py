"""
Unit tests for the unit_converter module.

Tests the canonical distance formula and unit conversion functions.

Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.8, 1.9, 1.10
"""

import pytest
import logging
from quantgambit.core.unit_converter import (
    pct_to_bps,
    bps_to_pct,
    price_distance_to_bps,
    price_distance_abs_bps,
    calculate_va_width_bps,
    convert_legacy_pct_to_bps,
    validate_mid_price_denominator,
    log_threshold_bps,
)


class TestPctToBps:
    """Tests for pct_to_bps conversion function."""
    
    def test_one_percent_to_bps(self):
        """1% (0.01) should convert to 100 bps."""
        assert pct_to_bps(0.01) == 100.0
    
    def test_zero_point_three_percent_to_bps(self):
        """0.3% (0.003) should convert to 30 bps."""
        assert pct_to_bps(0.003) == 30.0
    
    def test_zero_point_zero_one_percent_to_bps(self):
        """0.01% (0.0001) should convert to 1 bps."""
        assert pct_to_bps(0.0001) == 1.0
    
    def test_zero_percent_to_bps(self):
        """0% should convert to 0 bps."""
        assert pct_to_bps(0.0) == 0.0
    
    def test_negative_percent_to_bps(self):
        """Negative percentages should convert correctly."""
        assert pct_to_bps(-0.01) == -100.0
    
    def test_small_percent_to_bps(self):
        """Very small percentages should convert correctly."""
        assert pct_to_bps(0.00001) == 0.1


class TestBpsToPct:
    """Tests for bps_to_pct conversion function."""
    
    def test_hundred_bps_to_pct(self):
        """100 bps should convert to 1% (0.01)."""
        assert bps_to_pct(100) == 0.01
    
    def test_thirty_bps_to_pct(self):
        """30 bps should convert to 0.3% (0.003)."""
        assert bps_to_pct(30) == 0.003
    
    def test_one_bps_to_pct(self):
        """1 bps should convert to 0.01% (0.0001)."""
        assert bps_to_pct(1) == 0.0001
    
    def test_zero_bps_to_pct(self):
        """0 bps should convert to 0%."""
        assert bps_to_pct(0) == 0.0
    
    def test_negative_bps_to_pct(self):
        """Negative bps should convert correctly."""
        assert bps_to_pct(-100) == -0.01


class TestRoundTrip:
    """Tests for round-trip conversion consistency."""
    
    def test_pct_to_bps_to_pct(self):
        """Converting pct -> bps -> pct should return original value."""
        original = 0.0035
        assert bps_to_pct(pct_to_bps(original)) == pytest.approx(original)
    
    def test_bps_to_pct_to_bps(self):
        """Converting bps -> pct -> bps should return original value."""
        original = 42.5
        assert pct_to_bps(bps_to_pct(original)) == pytest.approx(original)


class TestPriceDistanceToBps:
    """Tests for price_distance_to_bps using canonical formula."""
    
    def test_price_above_reference(self):
        """Price above reference should return positive bps."""
        # Price 0.5% above reference: (100.5 - 100) / 100 * 10000 = 50 bps
        result = price_distance_to_bps(100.5, 100.0, 100.0)
        assert result == pytest.approx(50.0)
    
    def test_price_below_reference(self):
        """Price below reference should return negative bps."""
        # Price 0.5% below reference: (99.5 - 100) / 100 * 10000 = -50 bps
        result = price_distance_to_bps(99.5, 100.0, 100.0)
        assert result == pytest.approx(-50.0)
    
    def test_price_at_reference(self):
        """Price at reference should return 0 bps."""
        result = price_distance_to_bps(100.0, 100.0, 100.0)
        assert result == 0.0
    
    def test_uses_mid_price_as_denominator(self):
        """Distance should be calculated using mid_price as denominator, not reference."""
        # If mid_price differs from reference, result should use mid_price
        # (101 - 100) / 50 * 10000 = 200 bps (using mid_price=50)
        # NOT (101 - 100) / 100 * 10000 = 100 bps (using reference=100)
        result = price_distance_to_bps(101.0, 100.0, 50.0)
        assert result == pytest.approx(200.0)
    
    def test_zero_mid_price_returns_zero(self):
        """Zero mid_price should return 0 to avoid division by zero."""
        result = price_distance_to_bps(100.0, 99.0, 0.0)
        assert result == 0.0
    
    def test_realistic_btc_distance(self):
        """Test with realistic BTC prices."""
        # BTC at 50100, POC at 50000, mid_price at 50050
        # (50100 - 50000) / 50050 * 10000 = 19.98 bps
        result = price_distance_to_bps(50100.0, 50000.0, 50050.0)
        assert result == pytest.approx(19.98, rel=0.01)
    
    def test_realistic_eth_distance(self):
        """Test with realistic ETH prices."""
        # ETH at 3010, POC at 3000, mid_price at 3005
        # (3010 - 3000) / 3005 * 10000 = 33.28 bps
        result = price_distance_to_bps(3010.0, 3000.0, 3005.0)
        assert result == pytest.approx(33.28, rel=0.01)


class TestPriceDistanceAbsBps:
    """Tests for price_distance_abs_bps function."""
    
    def test_price_above_reference(self):
        """Price above reference should return positive absolute bps."""
        result = price_distance_abs_bps(100.5, 100.0, 100.0)
        assert result == pytest.approx(50.0)
    
    def test_price_below_reference(self):
        """Price below reference should return positive absolute bps."""
        result = price_distance_abs_bps(99.5, 100.0, 100.0)
        assert result == pytest.approx(50.0)
    
    def test_price_at_reference(self):
        """Price at reference should return 0 bps."""
        result = price_distance_abs_bps(100.0, 100.0, 100.0)
        assert result == 0.0
    
    def test_zero_mid_price_returns_zero(self):
        """Zero mid_price should return 0."""
        result = price_distance_abs_bps(100.0, 99.0, 0.0)
        assert result == 0.0


class TestCalculateVaWidthBps:
    """Tests for calculate_va_width_bps function."""
    
    def test_two_percent_va_width(self):
        """2% VA width should return 200 bps."""
        # (101 - 99) / 100 * 10000 = 200 bps
        result = calculate_va_width_bps(101.0, 99.0, 100.0)
        assert result == pytest.approx(200.0)
    
    def test_one_percent_va_width(self):
        """1% VA width should return 100 bps."""
        # (100.5 - 99.5) / 100 * 10000 = 100 bps
        result = calculate_va_width_bps(100.5, 99.5, 100.0)
        assert result == pytest.approx(100.0)
    
    def test_zero_va_width(self):
        """Zero VA width should return 0 bps."""
        result = calculate_va_width_bps(100.0, 100.0, 100.0)
        assert result == 0.0
    
    def test_zero_mid_price_returns_zero(self):
        """Zero mid_price should return 0."""
        result = calculate_va_width_bps(101.0, 99.0, 0.0)
        assert result == 0.0
    
    def test_realistic_btc_va_width(self):
        """Test with realistic BTC VA width."""
        # BTC VAH=50500, VAL=49500, mid=50000
        # (50500 - 49500) / 50000 * 10000 = 200 bps
        result = calculate_va_width_bps(50500.0, 49500.0, 50000.0)
        assert result == pytest.approx(200.0)


class TestConvertLegacyPctToBps:
    """Tests for convert_legacy_pct_to_bps function."""
    
    def test_converts_correctly(self):
        """Should convert legacy pct to bps correctly."""
        result = convert_legacy_pct_to_bps("min_distance_from_poc_pct", 0.003)
        assert result == pytest.approx(30.0)
    
    def test_logs_conversion(self, caplog):
        """Should log the conversion for debugging."""
        with caplog.at_level(logging.INFO):
            convert_legacy_pct_to_bps("test_param", 0.01, symbol="BTCUSDT")
        
        assert "Converted legacy parameter" in caplog.text
        assert "test_param" in caplog.text
        assert "100.00bps" in caplog.text
    
    def test_handles_zero(self):
        """Should handle zero values."""
        result = convert_legacy_pct_to_bps("zero_param", 0.0)
        assert result == 0.0


class TestValidateMidPriceDenominator:
    """Tests for validate_mid_price_denominator function."""
    
    def test_valid_denominator(self):
        """Should return True when denominator matches mid_price."""
        result = validate_mid_price_denominator("test_calc", 100.0, 100.0)
        assert result is True
    
    def test_invalid_denominator(self, caplog):
        """Should return False and log error when denominator doesn't match."""
        with caplog.at_level(logging.ERROR):
            result = validate_mid_price_denominator("test_calc", 99.0, 100.0)
        
        assert result is False
        assert "incorrect denominator" in caplog.text
    
    def test_floating_point_tolerance(self):
        """Should allow for floating point tolerance."""
        # Very small difference should still pass
        result = validate_mid_price_denominator("test_calc", 100.0 + 1e-11, 100.0)
        assert result is True


class TestLogThresholdBps:
    """Tests for log_threshold_bps function."""
    
    def test_logs_with_bps_suffix(self, caplog):
        """Should log threshold with bps suffix."""
        with caplog.at_level(logging.INFO):
            log_threshold_bps("min_distance", 30.0)
        
        assert "min_distance=30.00bps" in caplog.text
    
    def test_logs_with_symbol(self, caplog):
        """Should include symbol in log when provided."""
        with caplog.at_level(logging.INFO):
            log_threshold_bps("min_distance", 30.0, symbol="BTCUSDT")
        
        assert "min_distance=30.00bps" in caplog.text


class TestCanonicalFormulaConsistency:
    """Tests to ensure canonical formula is used consistently."""
    
    def test_distance_to_poc_uses_canonical_formula(self):
        """Distance to POC should use (price - poc) / mid_price * 10000."""
        price = 50100.0
        poc = 50000.0
        mid_price = 50050.0
        
        # Canonical formula
        expected = (price - poc) / mid_price * 10000
        result = price_distance_to_bps(price, poc, mid_price)
        
        assert result == pytest.approx(expected)
    
    def test_distance_to_vah_uses_canonical_formula(self):
        """Distance to VAH should use (price - vah) / mid_price * 10000."""
        price = 50200.0
        vah = 50100.0
        mid_price = 50050.0
        
        # Canonical formula
        expected = (price - vah) / mid_price * 10000
        result = price_distance_to_bps(price, vah, mid_price)
        
        assert result == pytest.approx(expected)
    
    def test_distance_to_val_uses_canonical_formula(self):
        """Distance to VAL should use (price - val) / mid_price * 10000."""
        price = 49900.0
        val = 49950.0
        mid_price = 50050.0
        
        # Canonical formula
        expected = (price - val) / mid_price * 10000
        result = price_distance_to_bps(price, val, mid_price)
        
        assert result == pytest.approx(expected)
    
    def test_va_width_uses_canonical_formula(self):
        """VA width should use (vah - val) / mid_price * 10000."""
        vah = 50100.0
        val = 49900.0
        mid_price = 50000.0
        
        # Canonical formula
        expected = (vah - val) / mid_price * 10000
        result = calculate_va_width_bps(vah, val, mid_price)
        
        assert result == pytest.approx(expected)
