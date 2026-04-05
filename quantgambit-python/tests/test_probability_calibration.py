"""
Tests for Probability Calibration Module.

Tests validate:
- CalibrationStorage interface and InMemoryCalibrationStorage
- ProbabilityCalibrator with Platt scaling
- Calibration tiering logic (pooled, per-symbol, per-symbol-regime)
- Uncalibrated fallback
- Leakage prevention in TradeOutcomeCollector
- CalibrationManager integration

Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.8, 4.10
"""

import pytest
import time
import math
from hypothesis import given, strategies as st, settings, assume

from quantgambit.signals.services.probability_calibration import (
    CalibrationMethod,
    CalibrationParams,
    CalibrationMetrics,
    TradeOutcome,
    CalibrationStorage,
    InMemoryCalibrationStorage,
    ProbabilityCalibrationConfig,
    ProbabilityCalibrator,
    TradeOutcomeCollector,
    CalibrationManager,
    get_ev_min_adjustment,
)


# =============================================================================
# Test CalibrationStorage Interface (Requirement 4.2)
# =============================================================================

class TestInMemoryCalibrationStorage:
    """Tests for InMemoryCalibrationStorage."""
    
    def test_store_and_retrieve_params(self):
        """Should store and retrieve calibration parameters."""
        storage = InMemoryCalibrationStorage()
        
        params = CalibrationParams(
            method=CalibrationMethod.PER_SYMBOL,
            a=-1.2,
            b=0.1,
            sample_count=500,
            last_fit_ts=time.time(),
            brier_score=0.15,
            ece=0.05,
            reliability_score=0.95,
        )
        
        storage.set_params("BTCUSDT", None, params)
        retrieved = storage.get_params("BTCUSDT", None)
        
        assert retrieved is not None
        assert retrieved.method == CalibrationMethod.PER_SYMBOL
        assert retrieved.a == -1.2
        assert retrieved.b == 0.1
        assert retrieved.sample_count == 500
    
    def test_store_and_retrieve_with_regime(self):
        """Should store and retrieve params with regime."""
        storage = InMemoryCalibrationStorage()
        
        params = CalibrationParams(
            method=CalibrationMethod.PER_SYMBOL_REGIME,
            a=-1.5,
            b=0.2,
            sample_count=1500,
        )
        
        storage.set_params("BTCUSDT", "trending", params)
        
        # Should retrieve with regime
        retrieved = storage.get_params("BTCUSDT", "trending")
        assert retrieved is not None
        assert retrieved.sample_count == 1500
        
        # Should not retrieve without regime
        retrieved_no_regime = storage.get_params("BTCUSDT", None)
        assert retrieved_no_regime is None
    
    def test_pooled_params(self):
        """Should store and retrieve pooled params."""
        storage = InMemoryCalibrationStorage()
        
        params = CalibrationParams(
            method=CalibrationMethod.POOLED,
            a=-1.0,
            b=0.0,
            sample_count=5000,
        )
        
        storage.set_pooled_params(params)
        retrieved = storage.get_pooled_params()
        
        assert retrieved is not None
        assert retrieved.method == CalibrationMethod.POOLED
        assert retrieved.sample_count == 5000
    
    def test_sample_counts(self):
        """Should track sample counts correctly."""
        storage = InMemoryCalibrationStorage()
        
        params = CalibrationParams(sample_count=300)
        storage.set_params("ETHUSDT", None, params)
        
        assert storage.get_sample_count("ETHUSDT", None) == 300
        assert storage.get_sample_count("BTCUSDT", None) == 0
    
    def test_clear(self):
        """Should clear all data."""
        storage = InMemoryCalibrationStorage()
        
        storage.set_params("BTCUSDT", None, CalibrationParams(sample_count=100))
        storage.set_pooled_params(CalibrationParams(sample_count=1000))
        
        storage.clear()
        
        assert storage.get_params("BTCUSDT", None) is None
        assert storage.get_pooled_params() is None
        assert storage.get_sample_count("BTCUSDT", None) == 0


# =============================================================================
# Test ProbabilityCalibrator (Requirements 4.1, 4.3, 4.4, 4.5)
# =============================================================================

class TestProbabilityCalibrator:
    """Tests for ProbabilityCalibrator."""
    
    def test_calibrate_uncalibrated_returns_raw(self):
        """When no calibration available, should return raw probability."""
        calibrator = ProbabilityCalibrator()
        
        p_cal, method, reliability = calibrator.calibrate(0.65, "BTCUSDT")
        
        assert p_cal == 0.65
        assert method == CalibrationMethod.UNCALIBRATED
        assert reliability == 0.0
    
    def test_calibrate_uses_pooled_when_available(self):
        """Should use pooled calibration when available."""
        storage = InMemoryCalibrationStorage()
        config = ProbabilityCalibrationConfig(min_samples_pooled=100)
        calibrator = ProbabilityCalibrator(storage, config)
        
        # Set up pooled calibration
        pooled_params = CalibrationParams(
            method=CalibrationMethod.POOLED,
            a=-1.0,
            b=0.0,
            sample_count=500,
            reliability_score=0.9,
        )
        storage.set_pooled_params(pooled_params)
        
        p_cal, method, reliability = calibrator.calibrate(0.65, "NEWUSDT")
        
        assert method == CalibrationMethod.POOLED
        assert reliability == 0.9
        # With a=-1, b=0, p_cal should be close to raw (identity transform)
        assert 0.6 < p_cal < 0.7
    
    def test_calibrate_uses_per_symbol_when_available(self):
        """Should prefer per-symbol over pooled when available."""
        storage = InMemoryCalibrationStorage()
        config = ProbabilityCalibrationConfig(
            min_samples_pooled=100,
            min_samples_per_symbol=200,
        )
        calibrator = ProbabilityCalibrator(storage, config)
        
        # Set up both pooled and per-symbol
        storage.set_pooled_params(CalibrationParams(
            method=CalibrationMethod.POOLED,
            a=-1.0, b=0.0, sample_count=500, reliability_score=0.85,
        ))
        storage.set_params("BTCUSDT", None, CalibrationParams(
            method=CalibrationMethod.PER_SYMBOL,
            a=-1.1, b=0.05, sample_count=300, reliability_score=0.92,
        ))
        
        p_cal, method, reliability = calibrator.calibrate(0.65, "BTCUSDT")
        
        assert method == CalibrationMethod.PER_SYMBOL
        assert reliability == 0.92
    
    def test_calibrate_uses_per_symbol_regime_when_available(self):
        """Should prefer per-symbol-regime when available."""
        storage = InMemoryCalibrationStorage()
        config = ProbabilityCalibrationConfig(
            min_samples_pooled=100,
            min_samples_per_symbol=200,
            min_samples_per_symbol_regime=1000,
        )
        calibrator = ProbabilityCalibrator(storage, config)
        
        # Set up all tiers
        storage.set_pooled_params(CalibrationParams(
            method=CalibrationMethod.POOLED,
            a=-1.0, b=0.0, sample_count=5000, reliability_score=0.85,
        ))
        storage.set_params("BTCUSDT", None, CalibrationParams(
            method=CalibrationMethod.PER_SYMBOL,
            a=-1.1, b=0.05, sample_count=800, reliability_score=0.90,
        ))
        storage.set_params("BTCUSDT", "trending", CalibrationParams(
            method=CalibrationMethod.PER_SYMBOL_REGIME,
            a=-1.2, b=0.1, sample_count=1500, reliability_score=0.95,
        ))
        
        p_cal, method, reliability = calibrator.calibrate(0.65, "BTCUSDT", "trending")
        
        assert method == CalibrationMethod.PER_SYMBOL_REGIME
        assert reliability == 0.95
    
    def test_fit_produces_valid_params(self):
        """Fit should produce valid calibration parameters."""
        calibrator = ProbabilityCalibrator()
        
        # Generate synthetic data with known calibration
        predictions = [0.3, 0.4, 0.5, 0.6, 0.7] * 50
        outcomes = [0, 0, 0, 1, 1] * 50  # 40% win rate
        
        params = calibrator.fit(predictions, outcomes)
        
        assert params.method == CalibrationMethod.POOLED
        assert params.sample_count == 250
        assert not math.isnan(params.a)
        assert not math.isnan(params.b)
        assert 0 <= params.brier_score <= 1
        assert 0 <= params.ece <= 1
    
    def test_compute_metrics_perfect_calibration(self):
        """Compute metrics for perfectly calibrated predictions."""
        calibrator = ProbabilityCalibrator()
        
        # Perfect calibration: 50% confidence, 50% win rate
        predictions = [0.5] * 100
        outcomes = [0] * 50 + [1] * 50
        
        metrics = calibrator.compute_metrics(predictions, outcomes)
        
        # Brier score should be 0.25 for 50% predictions with 50% outcomes
        assert abs(metrics.brier_score - 0.25) < 0.01
        # ECE should be low for well-calibrated predictions
        assert metrics.ece < 0.1
        assert metrics.reliability_score > 0.9
    
    def test_clamps_input_probability(self):
        """Should clamp input probability to [0, 1]."""
        calibrator = ProbabilityCalibrator()
        
        p_cal, _, _ = calibrator.calibrate(-0.1, "BTCUSDT")
        assert p_cal == 0.0
        
        p_cal, _, _ = calibrator.calibrate(1.5, "BTCUSDT")
        assert p_cal == 1.0


# =============================================================================
# Test Uncalibrated Fallback (Requirement 4.6)
# =============================================================================

class TestUncalibratedFallback:
    """Tests for uncalibrated fallback logic."""
    
    def test_uncalibrated_adds_margin(self):
        """Uncalibrated method should add EV_Min margin."""
        config = ProbabilityCalibrationConfig(p_margin_uncalibrated=0.02)
        
        margin, reason = get_ev_min_adjustment(
            CalibrationMethod.UNCALIBRATED, 0.0, config
        )
        
        assert margin == 0.02
        assert reason == "uncalibrated"
    
    def test_low_reliability_adds_margin(self):
        """Low reliability should add EV_Min margin."""
        config = ProbabilityCalibrationConfig(
            p_margin_uncalibrated=0.02,
            min_reliability_score=0.6,
        )
        
        margin, reason = get_ev_min_adjustment(
            CalibrationMethod.PER_SYMBOL, 0.5, config
        )
        
        assert margin == 0.02
        assert reason == "low_reliability"
    
    def test_good_calibration_no_margin(self):
        """Good calibration should not add margin."""
        config = ProbabilityCalibrationConfig(
            p_margin_uncalibrated=0.02,
            min_reliability_score=0.6,
        )
        
        margin, reason = get_ev_min_adjustment(
            CalibrationMethod.PER_SYMBOL, 0.9, config
        )
        
        assert margin == 0.0
        assert reason is None


# =============================================================================
# Test TradeOutcomeCollector with Leakage Prevention (Requirement 4.8)
# =============================================================================

class TestTradeOutcomeCollector:
    """Tests for TradeOutcomeCollector with leakage prevention."""
    
    def test_record_entry_and_outcome(self):
        """Should record trade entry and outcome."""
        collector = TradeOutcomeCollector()
        
        collector.record_entry(
            trade_id="trade1",
            symbol="BTCUSDT",
            regime="trending",
            p_raw=0.65,
            timestamp=1000.0,
        )
        
        collector.record_outcome(
            trade_id="trade1",
            outcome=1,
            close_timestamp=1100.0,
        )
        
        preds, outcomes = collector.get_training_data(cutoff_timestamp=2000.0)
        
        assert len(preds) == 1
        assert preds[0] == 0.65
        assert outcomes[0] == 1
    
    def test_excludes_open_trades(self):
        """Should exclude open trades from training data."""
        collector = TradeOutcomeCollector()
        
        # Record two entries
        collector.record_entry("trade1", "BTCUSDT", "trending", 0.65, 1000.0)
        collector.record_entry("trade2", "BTCUSDT", "trending", 0.70, 1100.0)
        
        # Only close one
        collector.record_outcome("trade1", 1, 1200.0)
        
        preds, outcomes = collector.get_training_data(cutoff_timestamp=2000.0)
        
        # Should only include closed trade
        assert len(preds) == 1
        assert preds[0] == 0.65
    
    def test_excludes_data_after_cutoff(self):
        """Should exclude data after cutoff timestamp (no lookahead)."""
        collector = TradeOutcomeCollector()
        
        # Record trades at different times
        collector.record_entry("trade1", "BTCUSDT", "trending", 0.65, 1000.0)
        collector.record_outcome("trade1", 1, 1100.0)
        
        collector.record_entry("trade2", "BTCUSDT", "trending", 0.70, 2000.0)
        collector.record_outcome("trade2", 0, 2100.0)
        
        # Get data with cutoff before trade2
        preds, outcomes = collector.get_training_data(cutoff_timestamp=1500.0)
        
        # Should only include trade1
        assert len(preds) == 1
        assert preds[0] == 0.65
    
    def test_filters_by_symbol(self):
        """Should filter by symbol."""
        collector = TradeOutcomeCollector()
        
        collector.record_entry("trade1", "BTCUSDT", "trending", 0.65, 1000.0)
        collector.record_outcome("trade1", 1, 1100.0)
        
        collector.record_entry("trade2", "ETHUSDT", "trending", 0.70, 1000.0)
        collector.record_outcome("trade2", 0, 1100.0)
        
        preds, outcomes = collector.get_training_data(
            symbol="BTCUSDT", cutoff_timestamp=2000.0
        )
        
        assert len(preds) == 1
        assert preds[0] == 0.65
    
    def test_filters_by_regime(self):
        """Should filter by regime."""
        collector = TradeOutcomeCollector()
        
        collector.record_entry("trade1", "BTCUSDT", "trending", 0.65, 1000.0)
        collector.record_outcome("trade1", 1, 1100.0)
        
        collector.record_entry("trade2", "BTCUSDT", "ranging", 0.70, 1000.0)
        collector.record_outcome("trade2", 0, 1100.0)
        
        preds, outcomes = collector.get_training_data(
            symbol="BTCUSDT", regime="trending", cutoff_timestamp=2000.0
        )
        
        assert len(preds) == 1
        assert preds[0] == 0.65
    
    def test_sample_counts(self):
        """Should track sample counts correctly."""
        collector = TradeOutcomeCollector()
        
        # Add trades for different symbols/regimes
        for i in range(5):
            collector.record_entry(f"btc_trend_{i}", "BTCUSDT", "trending", 0.6, 1000.0)
            collector.record_outcome(f"btc_trend_{i}", 1, 1100.0)
        
        for i in range(3):
            collector.record_entry(f"btc_range_{i}", "BTCUSDT", "ranging", 0.5, 1000.0)
            collector.record_outcome(f"btc_range_{i}", 0, 1100.0)
        
        for i in range(2):
            collector.record_entry(f"eth_{i}", "ETHUSDT", "trending", 0.7, 1000.0)
            collector.record_outcome(f"eth_{i}", 1, 1100.0)
        
        counts = collector.get_sample_counts()
        
        assert counts["BTCUSDT"] == 8  # 5 + 3
        assert counts["BTCUSDT:trending"] == 5
        assert counts["BTCUSDT:ranging"] == 3
        assert counts["ETHUSDT"] == 2
        assert counts["_pooled"] == 10


# =============================================================================
# Test CalibrationManager Integration
# =============================================================================

class TestCalibrationManager:
    """Tests for CalibrationManager integration."""
    
    def test_calibrate_probability_uncalibrated(self):
        """Should return uncalibrated with margin when no data."""
        manager = CalibrationManager()
        
        p_cal, method, reliability, margin = manager.calibrate_probability(
            0.65, "BTCUSDT", "trending"
        )
        
        assert p_cal == 0.65
        assert method == CalibrationMethod.UNCALIBRATED
        assert reliability == 0.0
        assert margin == 0.02  # Default p_margin_uncalibrated
    
    def test_record_and_recalibrate(self):
        """Should record trades and recalibrate."""
        config = ProbabilityCalibrationConfig(
            min_samples_pooled=10,  # Low threshold for testing
        )
        manager = CalibrationManager(config=config)
        
        # Use current time for realistic timestamps
        now = time.time()
        
        # Record enough trades
        for i in range(20):
            manager.record_trade_entry(
                trade_id=f"trade_{i}",
                symbol="BTCUSDT",
                regime="trending",
                p_raw=0.6,
                timestamp=now - 1000 + i,  # Recent timestamps
            )
            manager.record_trade_outcome(
                trade_id=f"trade_{i}",
                outcome=1 if i % 2 == 0 else 0,  # 50% win rate
                close_timestamp=now - 900 + i,
            )
        
        # Force recalibration
        results = manager.recalibrate_all(force=True)
        
        assert "_pooled" in results
        assert results["_pooled"].sample_count == 20
    
    def test_get_status(self):
        """Should return calibration status."""
        manager = CalibrationManager()
        
        status = manager.get_status("BTCUSDT", "trending")
        
        assert status["calibration_method"] == "uncalibrated"
        assert status["sample_count"] == 0
        assert status["reliability_score"] == 0.0


# =============================================================================
# Property-Based Tests
# =============================================================================

class TestCalibrationProperties:
    """Property-based tests for calibration."""
    
    @given(p_raw=st.floats(min_value=0.0, max_value=1.0))
    @settings(max_examples=100)
    def test_calibrated_probability_in_valid_range(self, p_raw: float):
        """
        *For any* raw probability in [0, 1], the calibrated probability
        should also be in [0, 1].
        """
        assume(not math.isnan(p_raw))
        
        calibrator = ProbabilityCalibrator()
        
        # Set up some calibration
        storage = InMemoryCalibrationStorage()
        storage.set_pooled_params(CalibrationParams(
            method=CalibrationMethod.POOLED,
            a=-1.5,
            b=0.3,
            sample_count=500,
            reliability_score=0.9,
        ))
        calibrator = ProbabilityCalibrator(storage)
        
        p_cal, _, _ = calibrator.calibrate(p_raw, "BTCUSDT")
        
        assert 0.0 <= p_cal <= 1.0
    
    @given(
        a=st.floats(min_value=-5.0, max_value=5.0),
        b=st.floats(min_value=-5.0, max_value=5.0),
        p_raw=st.floats(min_value=0.0, max_value=1.0),
    )
    @settings(max_examples=100)
    def test_platt_scaling_output_valid(self, a: float, b: float, p_raw: float):
        """
        *For any* Platt scaling parameters and raw probability,
        the output should be in [0, 1].
        """
        assume(not math.isnan(a) and not math.isnan(b) and not math.isnan(p_raw))
        
        calibrator = ProbabilityCalibrator()
        p_cal = calibrator._apply_platt_scaling(p_raw, a, b)
        
        assert 0.0 <= p_cal <= 1.0
    
    @given(
        predictions=st.lists(
            st.floats(min_value=0.0, max_value=1.0),
            min_size=20,
            max_size=100,
        ),
        outcomes=st.lists(
            st.integers(min_value=0, max_value=1),
            min_size=20,
            max_size=100,
        ),
    )
    @settings(max_examples=50)
    def test_brier_score_in_valid_range(
        self, predictions: list, outcomes: list
    ):
        """
        *For any* set of predictions and outcomes, Brier score should be in [0, 1].
        """
        # Make lists same length
        min_len = min(len(predictions), len(outcomes))
        predictions = predictions[:min_len]
        outcomes = outcomes[:min_len]
        
        assume(len(predictions) >= 10)
        assume(all(not math.isnan(p) for p in predictions))
        
        calibrator = ProbabilityCalibrator()
        metrics = calibrator.compute_metrics(predictions, outcomes)
        
        assert 0.0 <= metrics.brier_score <= 1.0
        assert 0.0 <= metrics.ece <= 1.0
        assert 0.0 <= metrics.reliability_score <= 1.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
