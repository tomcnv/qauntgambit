"""
Unit tests for per-symbol threshold calibration.

Tests:
- Rolling statistics computation
- Dynamic threshold calculation
- Fallback behavior with insufficient data
- Calibration quality indicators
"""

import pytest
import time
from quantgambit.risk.symbol_calibrator import (
    SymbolCalibrator,
    CalibrationConfig,
    SymbolThresholds,
    SymbolStats,
)


class TestSymbolCalibrator:
    """Test SymbolCalibrator core functionality."""
    
    def test_observe_records_samples(self):
        """Basic observation recording."""
        calibrator = SymbolCalibrator()
        
        calibrator.observe("BTCUSDT", spread_bps=2.0, bid_depth_usd=50000, ask_depth_usd=48000)
        
        stats = calibrator.get_stats_summary("BTCUSDT")
        assert stats is not None
        assert stats["spread_sample_count"] == 1
        assert stats["depth_sample_count"] == 1
    
    def test_observe_respects_interval(self):
        """Observations should be rate-limited."""
        config = CalibrationConfig(sample_interval_sec=1.0)
        calibrator = SymbolCalibrator(config)
        
        now = time.time()
        calibrator.observe("BTCUSDT", spread_bps=2.0, bid_depth_usd=50000, ask_depth_usd=48000, timestamp=now)
        calibrator.observe("BTCUSDT", spread_bps=3.0, bid_depth_usd=45000, ask_depth_usd=44000, timestamp=now + 0.5)
        
        stats = calibrator.get_stats_summary("BTCUSDT")
        assert stats["spread_sample_count"] == 1  # Second observation ignored (too soon)
        
        # After interval
        calibrator.observe("BTCUSDT", spread_bps=4.0, bid_depth_usd=40000, ask_depth_usd=39000, timestamp=now + 1.5)
        stats = calibrator.get_stats_summary("BTCUSDT")
        assert stats["spread_sample_count"] == 2
    
    def test_fallback_thresholds_no_data(self):
        """Fallback thresholds when no data."""
        calibrator = SymbolCalibrator()
        
        thresholds = calibrator.get_thresholds("BTCUSDT")
        
        assert thresholds.symbol == "BTCUSDT"
        assert thresholds.calibration_quality == "poor"
        assert thresholds.sample_count == 0
        # Should use fallback values
        assert thresholds.spread_warn_bps == calibrator.config.fallback_spread_warn_bps
        assert thresholds.spread_block_bps == calibrator.config.fallback_spread_block_bps
    
    def test_fallback_thresholds_insufficient_data(self):
        """Fallback thresholds with insufficient samples."""
        config = CalibrationConfig(
            min_samples_for_calibration=20,
            sample_interval_sec=0.0,  # No rate limiting for test
        )
        calibrator = SymbolCalibrator(config)
        
        # Add only 10 samples
        for i in range(10):
            calibrator.observe("BTCUSDT", spread_bps=2.0 + i * 0.1, bid_depth_usd=50000, ask_depth_usd=48000)
        
        thresholds = calibrator.get_thresholds("BTCUSDT")
        
        assert thresholds.calibration_quality == "poor"
        assert thresholds.sample_count == 10
        # Still using fallback values
        assert thresholds.spread_warn_bps == config.fallback_spread_warn_bps
    
    def test_calibrated_thresholds_sufficient_data(self):
        """Dynamic thresholds with sufficient data."""
        config = CalibrationConfig(
            min_samples_for_calibration=20,
            good_samples_threshold=50,
            sample_interval_sec=0.0,  # No rate limiting for test
        )
        calibrator = SymbolCalibrator(config)
        
        # Add 30 samples with spread around 2.5 bps
        for i in range(30):
            spread = 2.0 + (i % 5) * 0.2  # 2.0, 2.2, 2.4, 2.6, 2.8 repeating
            calibrator.observe("BTCUSDT", spread_bps=spread, bid_depth_usd=50000, ask_depth_usd=48000)
        
        thresholds = calibrator.get_thresholds("BTCUSDT")
        
        assert thresholds.calibration_quality == "fair"
        assert thresholds.sample_count == 30
        # Median spread should be around 2.4 bps
        assert 2.0 <= thresholds.spread_typical_bps <= 3.0
        # Warn should be ~2x typical
        assert thresholds.spread_warn_bps > thresholds.spread_typical_bps
        # Block should be higher than warn
        assert thresholds.spread_block_bps > thresholds.spread_warn_bps
    
    def test_good_calibration_quality(self):
        """Good calibration quality with many samples."""
        config = CalibrationConfig(
            min_samples_for_calibration=20,
            good_samples_threshold=100,
            sample_interval_sec=0.0,
        )
        calibrator = SymbolCalibrator(config)
        
        # Add 150 samples
        for i in range(150):
            calibrator.observe("BTCUSDT", spread_bps=3.0, bid_depth_usd=40000, ask_depth_usd=40000)
        
        thresholds = calibrator.get_thresholds("BTCUSDT")
        
        assert thresholds.calibration_quality == "good"
        assert thresholds.sample_count == 150
    
    def test_depth_thresholds(self):
        """Depth thresholds are calibrated correctly."""
        config = CalibrationConfig(
            min_samples_for_calibration=10,
            sample_interval_sec=0.0,
            depth_warn_fraction=0.5,
            depth_block_fraction=0.25,
        )
        calibrator = SymbolCalibrator(config)
        
        # Add samples with depth around 100k
        for i in range(20):
            calibrator.observe("BTCUSDT", spread_bps=2.0, bid_depth_usd=100000, ask_depth_usd=100000)
        
        thresholds = calibrator.get_thresholds("BTCUSDT")
        
        # Typical should be ~100k
        assert 90000 <= thresholds.depth_typical_usd <= 110000
        # Warn should be 50% of typical (~50k)
        assert 40000 <= thresholds.depth_warn_usd <= 60000
        # Block should be 25% of typical (~25k) but at least $500
        assert 500 <= thresholds.depth_block_usd <= 30000
    
    def test_uses_min_depth(self):
        """Uses minimum of bid/ask depth."""
        config = CalibrationConfig(sample_interval_sec=0.0)
        calibrator = SymbolCalibrator(config)
        
        # Bid depth is lower
        calibrator.observe("BTCUSDT", spread_bps=2.0, bid_depth_usd=30000, ask_depth_usd=50000)
        
        stats = calibrator.get_stats_summary("BTCUSDT")
        # Should have recorded the min (30000)
        assert stats["depth_sample_count"] == 1
    
    def test_multiple_symbols(self):
        """Track multiple symbols independently."""
        config = CalibrationConfig(
            min_samples_for_calibration=5,
            sample_interval_sec=0.0,
        )
        calibrator = SymbolCalibrator(config)
        
        # BTC with tight spreads
        for i in range(10):
            calibrator.observe("BTCUSDT", spread_bps=2.0, bid_depth_usd=100000, ask_depth_usd=100000)
        
        # ETH with wider spreads
        for i in range(10):
            calibrator.observe("ETHUSDT", spread_bps=5.0, bid_depth_usd=50000, ask_depth_usd=50000)
        
        btc_thresholds = calibrator.get_thresholds("BTCUSDT")
        eth_thresholds = calibrator.get_thresholds("ETHUSDT")
        
        # BTC should have tighter thresholds
        assert btc_thresholds.spread_typical_bps < eth_thresholds.spread_typical_bps
        # ETH should have lower depth thresholds
        assert btc_thresholds.depth_typical_usd > eth_thresholds.depth_typical_usd
    
    def test_threshold_minimums(self):
        """Thresholds have minimum floors."""
        config = CalibrationConfig(
            min_samples_for_calibration=10,
            sample_interval_sec=0.0,
        )
        calibrator = SymbolCalibrator(config)
        
        # Add samples with very tight spreads
        for i in range(20):
            calibrator.observe("BTCUSDT", spread_bps=0.5, bid_depth_usd=1000000, ask_depth_usd=1000000)
        
        thresholds = calibrator.get_thresholds("BTCUSDT")
        
        # Even with 0.5 bps typical, warn should be at least 2 bps
        assert thresholds.spread_warn_bps >= 2.0
        # Block should be at least 5 bps
        assert thresholds.spread_block_bps >= 5.0
        # Depth block should be at least $500
        assert thresholds.depth_block_usd >= 500.0
    
    def test_caching(self):
        """Thresholds are cached."""
        config = CalibrationConfig(sample_interval_sec=0.0)
        calibrator = SymbolCalibrator(config)
        calibrator._cache_ttl_sec = 10.0
        
        for i in range(30):
            calibrator.observe("BTCUSDT", spread_bps=2.0, bid_depth_usd=50000, ask_depth_usd=50000)
        
        # First call computes
        t1 = calibrator.get_thresholds("BTCUSDT")
        # Second call should return cached (same object)
        t2 = calibrator.get_thresholds("BTCUSDT")
        
        assert t1.last_updated == t2.last_updated
    
    def test_reset_symbol(self):
        """Reset single symbol."""
        config = CalibrationConfig(sample_interval_sec=0.0)
        calibrator = SymbolCalibrator(config)
        
        calibrator.observe("BTCUSDT", spread_bps=2.0, bid_depth_usd=50000, ask_depth_usd=50000)
        calibrator.observe("ETHUSDT", spread_bps=3.0, bid_depth_usd=40000, ask_depth_usd=40000)
        
        calibrator.reset("BTCUSDT")
        
        assert calibrator.get_stats_summary("BTCUSDT") is None
        assert calibrator.get_stats_summary("ETHUSDT") is not None
    
    def test_reset_all(self):
        """Reset all symbols."""
        config = CalibrationConfig(sample_interval_sec=0.0)
        calibrator = SymbolCalibrator(config)
        
        calibrator.observe("BTCUSDT", spread_bps=2.0, bid_depth_usd=50000, ask_depth_usd=50000)
        calibrator.observe("ETHUSDT", spread_bps=3.0, bid_depth_usd=40000, ask_depth_usd=40000)
        
        calibrator.reset()
        
        assert calibrator.get_stats_summary("BTCUSDT") is None
        assert calibrator.get_stats_summary("ETHUSDT") is None
    
    def test_get_all_thresholds(self):
        """Get thresholds for all symbols."""
        config = CalibrationConfig(sample_interval_sec=0.0)
        calibrator = SymbolCalibrator(config)
        
        calibrator.observe("BTCUSDT", spread_bps=2.0, bid_depth_usd=50000, ask_depth_usd=50000)
        calibrator.observe("ETHUSDT", spread_bps=3.0, bid_depth_usd=40000, ask_depth_usd=40000)
        
        all_thresholds = calibrator.get_all_thresholds()
        
        assert "BTCUSDT" in all_thresholds
        assert "ETHUSDT" in all_thresholds
        assert all_thresholds["BTCUSDT"].symbol == "BTCUSDT"
        assert all_thresholds["ETHUSDT"].symbol == "ETHUSDT"


class TestSymbolStats:
    """Test SymbolStats helper class."""
    
    def test_median_calculation(self):
        """Median is computed correctly."""
        stats = SymbolStats()
        
        # Add odd number of samples
        for val in [1.0, 2.0, 3.0, 4.0, 5.0]:
            stats.spread_samples.append(val)
        
        assert stats.spread_median() == 3.0
    
    def test_median_even_samples(self):
        """Median with even samples."""
        stats = SymbolStats()
        
        for val in [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]:
            stats.spread_samples.append(val)
        
        # Median of 1-6 is (3+4)/2 = 3.5
        assert stats.spread_median() == 3.5
    
    def test_percentile_calculation(self):
        """Percentile calculation."""
        stats = SymbolStats()
        
        for val in range(1, 101):  # 1 to 100
            stats.spread_samples.append(float(val))
        
        # 95th percentile should be around 95
        p95 = stats.spread_percentile(95)
        assert p95 is not None
        assert 94 <= p95 <= 96
    
    def test_insufficient_samples_returns_none(self):
        """Median/percentile return None with insufficient samples."""
        stats = SymbolStats()
        
        # Only 3 samples (need 5 for median)
        for val in [1.0, 2.0, 3.0]:
            stats.spread_samples.append(val)
        
        assert stats.spread_median() is None
        assert stats.spread_percentile(50) is None  # Needs 20 samples


class TestSymbolThresholds:
    """Test SymbolThresholds dataclass."""
    
    def test_to_dict(self):
        """Serialization to dict."""
        thresholds = SymbolThresholds(
            symbol="BTCUSDT",
            spread_typical_bps=2.5,
            spread_warn_bps=5.0,
            spread_block_bps=10.0,
            depth_typical_usd=100000.0,
            depth_warn_usd=50000.0,
            depth_block_usd=25000.0,
            sample_count=100,
            calibration_quality="good",
            last_updated=time.time(),
        )
        
        d = thresholds.to_dict()
        
        assert d["symbol"] == "BTCUSDT"
        assert d["spread_typical_bps"] == 2.5
        assert d["spread_warn_bps"] == 5.0
        assert d["spread_block_bps"] == 10.0
        assert d["depth_typical_usd"] == 100000
        assert d["depth_warn_usd"] == 50000
        assert d["depth_block_usd"] == 25000
        assert d["sample_count"] == 100
        assert d["calibration_quality"] == "good"


class TestCalibrationConfig:
    """Test CalibrationConfig defaults and customization."""
    
    def test_default_config(self):
        """Default config values."""
        config = CalibrationConfig()
        
        assert config.max_samples > 0
        assert config.sample_interval_sec >= 0
        assert config.spread_warn_multiplier > 1.0
        assert config.spread_block_multiplier > config.spread_warn_multiplier
        assert 0 < config.depth_warn_fraction < 1.0
        assert 0 < config.depth_block_fraction < config.depth_warn_fraction
    
    def test_custom_config(self):
        """Custom config values."""
        config = CalibrationConfig(
            max_samples=500,
            spread_warn_multiplier=3.0,
            spread_block_multiplier=6.0,
        )
        
        assert config.max_samples == 500
        assert config.spread_warn_multiplier == 3.0
        assert config.spread_block_multiplier == 6.0
