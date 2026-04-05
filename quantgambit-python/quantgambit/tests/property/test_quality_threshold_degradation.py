"""Property tests for quality threshold degradation.

Feature: live-orderbook-data-storage
Property 11: Quality Threshold Degradation

For any symbol where quality_score falls below the configured min_completeness_pct
threshold, the LiveDataValidator SHALL set is_degraded to True and update the
MarketDataQualityTracker status to "degraded".

Validates: Requirements 4.4
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional
from unittest.mock import MagicMock

import pytest
from hypothesis import given, settings, strategies as st, assume

from quantgambit.storage.live_data_validator import LiveDataValidator
from quantgambit.storage.persistence import LiveValidationConfig


# Test configuration
PROPERTY_TEST_EXAMPLES = 100


@dataclass
class MockQualityTracker:
    """Mock MarketDataQualityTracker for testing."""
    
    updates: List[dict]
    
    def __init__(self) -> None:
        self.updates = []
    
    def update_orderbook(
        self,
        symbol: str,
        timestamp: float,
        now_ts: Optional[float] = None,
        gap: bool = False,
    ) -> None:
        """Record an orderbook update."""
        self.updates.append({
            "type": "orderbook",
            "symbol": symbol,
            "timestamp": timestamp,
            "now_ts": now_ts,
            "gap": gap,
        })
    
    def update_trade(
        self,
        symbol: str,
        timestamp: float,
    ) -> None:
        """Record a trade update."""
        self.updates.append({
            "type": "trade",
            "symbol": symbol,
            "timestamp": timestamp,
        })


# Strategies for generating test data
symbol_strategy = st.text(
    alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd"), whitelist_characters="/"),
    min_size=3,
    max_size=15,
).filter(lambda s: "/" in s or len(s) >= 3)

exchange_strategy = st.sampled_from(["binance", "coinbase", "kraken", "okx"])

# Threshold strategy - values between 0 and 100
threshold_strategy = st.floats(min_value=10.0, max_value=95.0, allow_nan=False, allow_infinity=False)

# Completeness percentage strategy
completeness_strategy = st.floats(min_value=0.0, max_value=100.0, allow_nan=False, allow_infinity=False)


class TestQualityThresholdDegradation:
    """Property tests for quality threshold degradation.
    
    Property 11: Quality Threshold Degradation
    
    For any symbol where quality_score falls below the configured min_completeness_pct
    threshold, the LiveDataValidator SHALL set is_degraded to True and update the
    MarketDataQualityTracker status to "degraded".
    
    Validates: Requirements 4.4
    """
    
    @settings(max_examples=PROPERTY_TEST_EXAMPLES)
    @given(
        symbol=symbol_strategy,
        exchange=exchange_strategy,
        threshold=threshold_strategy,
        quality_below_threshold=st.booleans(),
    )
    def test_degradation_status_matches_threshold_comparison(
        self,
        symbol: str,
        exchange: str,
        threshold: float,
        quality_below_threshold: bool,
    ) -> None:
        """Property: is_degraded SHALL be True iff quality_score < threshold.
        
        **Validates: Requirements 4.4**
        
        For any quality score and threshold, the degradation status must
        accurately reflect whether the quality is below the threshold.
        """
        # Create config with the given threshold
        config = LiveValidationConfig(
            enabled=True,
            min_completeness_pct=threshold,
            completeness_window_sec=60.0,
            expected_orderbook_updates_per_sec=1.0,
            expected_trades_per_sec=1.0,
        )
        
        quality_tracker = MockQualityTracker()
        validator = LiveDataValidator(
            quality_tracker=quality_tracker,
            config=config,
        )
        
        # Calculate how many updates we need to achieve target quality
        # Quality score = (orderbook_pct + trade_pct) / 200
        # We'll set both to the same value for simplicity
        
        if quality_below_threshold:
            # Target quality below threshold
            target_quality_pct = max(0.0, threshold - 10.0)
        else:
            # Target quality at or above threshold
            target_quality_pct = min(100.0, threshold + 10.0)
        
        # Calculate updates needed for target completeness
        # completeness_pct = (actual / expected) * 100
        # For a 60-second window with 1 update/sec expected, we need 60 updates for 100%
        window_sec = config.completeness_window_sec
        expected_updates = window_sec * config.expected_orderbook_updates_per_sec
        
        # Calculate actual updates needed
        actual_updates = int((target_quality_pct / 100.0) * expected_updates)
        actual_updates = max(1, actual_updates)  # At least 1 update
        
        # Generate timestamps spread across the window
        base_time = 1700000000.0
        
        # Record orderbook updates
        for i in range(actual_updates):
            timestamp = base_time + (i * window_sec / max(actual_updates, 1))
            validator.record_orderbook_update(
                symbol=symbol,
                exchange=exchange,
                timestamp=timestamp,
                seq=i + 1,
            )
        
        # Record trade updates (same count for equal contribution)
        for i in range(actual_updates):
            timestamp = base_time + (i * window_sec / max(actual_updates, 1))
            validator.record_trade(
                symbol=symbol,
                exchange=exchange,
                timestamp=timestamp,
            )
        
        # Check quality threshold at the end of the window
        current_time = base_time + window_sec
        is_degraded = validator.check_quality_threshold(symbol, exchange, current_time)
        
        # Get the actual quality score for verification
        quality_score = validator.calculate_quality_score(symbol, exchange, current_time)
        quality_score_pct = quality_score * 100.0
        
        # Verify the property: is_degraded should match threshold comparison
        expected_degraded = quality_score_pct < threshold
        
        assert is_degraded == expected_degraded, (
            f"Degradation status mismatch: is_degraded={is_degraded}, "
            f"expected={expected_degraded}, quality={quality_score_pct:.1f}%, "
            f"threshold={threshold:.1f}%"
        )
    
    @settings(max_examples=PROPERTY_TEST_EXAMPLES)
    @given(
        symbol=symbol_strategy,
        exchange=exchange_strategy,
        threshold=threshold_strategy,
    )
    def test_zero_updates_always_degraded(
        self,
        symbol: str,
        exchange: str,
        threshold: float,
    ) -> None:
        """Property: Zero updates SHALL always result in degraded status.
        
        **Validates: Requirements 4.4**
        
        When no updates have been recorded, the quality score is 0.0,
        which is always below any positive threshold.
        """
        assume(threshold > 0.0)  # Threshold must be positive
        
        config = LiveValidationConfig(
            enabled=True,
            min_completeness_pct=threshold,
        )
        
        quality_tracker = MockQualityTracker()
        validator = LiveDataValidator(
            quality_tracker=quality_tracker,
            config=config,
        )
        
        # Check quality without any updates
        current_time = 1700000000.0
        is_degraded = validator.check_quality_threshold(symbol, exchange, current_time)
        
        # With zero updates, quality score is 0.0, which is always below threshold
        assert is_degraded is True, (
            f"Zero updates should always be degraded with threshold={threshold}%"
        )
    
    @settings(max_examples=PROPERTY_TEST_EXAMPLES)
    @given(
        symbol=symbol_strategy,
        exchange=exchange_strategy,
    )
    def test_full_completeness_never_degraded(
        self,
        symbol: str,
        exchange: str,
    ) -> None:
        """Property: 100% completeness SHALL never be degraded.
        
        **Validates: Requirements 4.4**
        
        When completeness is at 100%, the quality score is 1.0,
        which is always at or above any threshold <= 100%.
        """
        config = LiveValidationConfig(
            enabled=True,
            min_completeness_pct=80.0,  # Standard threshold
            completeness_window_sec=10.0,
            expected_orderbook_updates_per_sec=1.0,
            expected_trades_per_sec=1.0,
        )
        
        quality_tracker = MockQualityTracker()
        validator = LiveDataValidator(
            quality_tracker=quality_tracker,
            config=config,
        )
        
        # Record exactly the expected number of updates
        base_time = 1700000000.0
        window_sec = config.completeness_window_sec
        expected_updates = int(window_sec * config.expected_orderbook_updates_per_sec)
        
        # Record orderbook updates at expected rate
        for i in range(expected_updates):
            timestamp = base_time + i
            validator.record_orderbook_update(
                symbol=symbol,
                exchange=exchange,
                timestamp=timestamp,
                seq=i + 1,
            )
        
        # Record trade updates at expected rate
        for i in range(expected_updates):
            timestamp = base_time + i
            validator.record_trade(
                symbol=symbol,
                exchange=exchange,
                timestamp=timestamp,
            )
        
        # Check quality at the end of the window
        current_time = base_time + window_sec
        is_degraded = validator.check_quality_threshold(symbol, exchange, current_time)
        
        # With full completeness, should not be degraded
        assert is_degraded is False, (
            f"Full completeness should never be degraded"
        )
    
    @settings(max_examples=PROPERTY_TEST_EXAMPLES)
    @given(
        symbol=symbol_strategy,
        exchange=exchange_strategy,
        threshold=threshold_strategy,
    )
    def test_is_degraded_reflects_last_check(
        self,
        symbol: str,
        exchange: str,
        threshold: float,
    ) -> None:
        """Property: is_degraded() SHALL return the result of the last check.
        
        **Validates: Requirements 4.4**
        
        The is_degraded() method should return the same value as the
        most recent call to check_quality_threshold().
        """
        config = LiveValidationConfig(
            enabled=True,
            min_completeness_pct=threshold,
            completeness_window_sec=10.0,
            expected_orderbook_updates_per_sec=1.0,
            expected_trades_per_sec=1.0,
        )
        
        quality_tracker = MockQualityTracker()
        validator = LiveDataValidator(
            quality_tracker=quality_tracker,
            config=config,
        )
        
        # Record some updates
        base_time = 1700000000.0
        for i in range(5):
            validator.record_orderbook_update(
                symbol=symbol,
                exchange=exchange,
                timestamp=base_time + i,
                seq=i + 1,
            )
            validator.record_trade(
                symbol=symbol,
                exchange=exchange,
                timestamp=base_time + i,
            )
        
        # Check quality threshold
        current_time = base_time + 10.0
        check_result = validator.check_quality_threshold(symbol, exchange, current_time)
        
        # is_degraded() should return the same value
        assert validator.is_degraded(symbol, exchange) == check_result, (
            f"is_degraded() should match check_quality_threshold() result"
        )
    
    @settings(max_examples=PROPERTY_TEST_EXAMPLES)
    @given(
        symbol=symbol_strategy,
        exchange=exchange_strategy,
    )
    def test_quality_tracker_updated_on_degradation(
        self,
        symbol: str,
        exchange: str,
    ) -> None:
        """Property: MarketDataQualityTracker SHALL be updated when degraded.
        
        **Validates: Requirements 4.4**
        
        When quality degrades below the threshold, the quality tracker
        should receive an update indicating the degradation.
        """
        config = LiveValidationConfig(
            enabled=True,
            min_completeness_pct=80.0,
            completeness_window_sec=60.0,
            expected_orderbook_updates_per_sec=1.0,
            expected_trades_per_sec=1.0,
        )
        
        quality_tracker = MockQualityTracker()
        validator = LiveDataValidator(
            quality_tracker=quality_tracker,
            config=config,
        )
        
        # Record very few updates to ensure degradation
        base_time = 1700000000.0
        validator.record_orderbook_update(
            symbol=symbol,
            exchange=exchange,
            timestamp=base_time,
            seq=1,
        )
        validator.record_trade(
            symbol=symbol,
            exchange=exchange,
            timestamp=base_time,
        )
        
        # Clear tracker updates from recording
        quality_tracker.updates.clear()
        
        # Check quality threshold - should be degraded
        current_time = base_time + 60.0
        is_degraded = validator.check_quality_threshold(symbol, exchange, current_time)
        
        # Verify degradation occurred
        assert is_degraded is True, "Should be degraded with minimal updates"
        
        # Verify quality tracker was updated with gap=True
        gap_updates = [u for u in quality_tracker.updates if u.get("gap") is True]
        assert len(gap_updates) > 0, (
            "Quality tracker should receive gap=True update on degradation"
        )
    
    @settings(max_examples=PROPERTY_TEST_EXAMPLES)
    @given(
        symbol=symbol_strategy,
        exchange=exchange_strategy,
        threshold=threshold_strategy,
    )
    def test_disabled_validator_never_degraded(
        self,
        symbol: str,
        exchange: str,
        threshold: float,
    ) -> None:
        """Property: Disabled validator SHALL never report degradation.
        
        **Validates: Requirements 4.4**
        
        When the validator is disabled, check_quality_threshold should
        always return False regardless of actual data quality.
        """
        config = LiveValidationConfig(
            enabled=False,  # Disabled
            min_completeness_pct=threshold,
        )
        
        quality_tracker = MockQualityTracker()
        validator = LiveDataValidator(
            quality_tracker=quality_tracker,
            config=config,
        )
        
        # Check quality without any updates
        current_time = 1700000000.0
        is_degraded = validator.check_quality_threshold(symbol, exchange, current_time)
        
        # Disabled validator should never report degradation
        assert is_degraded is False, (
            "Disabled validator should never report degradation"
        )
    
    @settings(max_examples=PROPERTY_TEST_EXAMPLES)
    @given(
        symbol=symbol_strategy,
        exchange=exchange_strategy,
    )
    def test_degradation_recovery(
        self,
        symbol: str,
        exchange: str,
    ) -> None:
        """Property: Degradation status SHALL recover when quality improves.
        
        **Validates: Requirements 4.4**
        
        When quality improves above the threshold after being degraded,
        the is_degraded status should be cleared.
        """
        config = LiveValidationConfig(
            enabled=True,
            min_completeness_pct=50.0,  # Low threshold for easier testing
            completeness_window_sec=10.0,
            expected_orderbook_updates_per_sec=1.0,
            expected_trades_per_sec=1.0,
        )
        
        quality_tracker = MockQualityTracker()
        validator = LiveDataValidator(
            quality_tracker=quality_tracker,
            config=config,
        )
        
        base_time = 1700000000.0
        
        # Phase 1: Record minimal updates to cause degradation
        validator.record_orderbook_update(
            symbol=symbol,
            exchange=exchange,
            timestamp=base_time,
            seq=1,
        )
        validator.record_trade(
            symbol=symbol,
            exchange=exchange,
            timestamp=base_time,
        )
        
        # Check - should be degraded
        is_degraded_1 = validator.check_quality_threshold(
            symbol, exchange, base_time + 10.0
        )
        assert is_degraded_1 is True, "Should be degraded with minimal updates"
        
        # Phase 2: Record many updates to recover
        for i in range(15):  # More than expected for 10-second window
            timestamp = base_time + 10.0 + i * 0.5
            validator.record_orderbook_update(
                symbol=symbol,
                exchange=exchange,
                timestamp=timestamp,
                seq=i + 2,
            )
            validator.record_trade(
                symbol=symbol,
                exchange=exchange,
                timestamp=timestamp,
            )
        
        # Check - should recover
        is_degraded_2 = validator.check_quality_threshold(
            symbol, exchange, base_time + 20.0
        )
        
        # With many updates in a short window, should recover
        assert is_degraded_2 is False, (
            "Should recover from degradation with sufficient updates"
        )
    
    @settings(max_examples=PROPERTY_TEST_EXAMPLES)
    @given(
        symbol=symbol_strategy,
        exchange=exchange_strategy,
        threshold=threshold_strategy,
    )
    def test_quality_metrics_include_degradation_status(
        self,
        symbol: str,
        exchange: str,
        threshold: float,
    ) -> None:
        """Property: get_quality_metrics SHALL include accurate is_degraded.
        
        **Validates: Requirements 4.4**
        
        The LiveQualityMetrics returned by get_quality_metrics should
        include the correct is_degraded status based on the threshold.
        """
        config = LiveValidationConfig(
            enabled=True,
            min_completeness_pct=threshold,
            completeness_window_sec=10.0,
            expected_orderbook_updates_per_sec=1.0,
            expected_trades_per_sec=1.0,
        )
        
        quality_tracker = MockQualityTracker()
        validator = LiveDataValidator(
            quality_tracker=quality_tracker,
            config=config,
        )
        
        # Record some updates
        base_time = 1700000000.0
        for i in range(5):
            validator.record_orderbook_update(
                symbol=symbol,
                exchange=exchange,
                timestamp=base_time + i,
                seq=i + 1,
            )
            validator.record_trade(
                symbol=symbol,
                exchange=exchange,
                timestamp=base_time + i,
            )
        
        # Get quality metrics
        current_time = base_time + 10.0
        metrics = validator.get_quality_metrics(symbol, exchange, current_time)
        
        # Verify is_degraded matches threshold comparison
        expected_degraded = (metrics.quality_score * 100.0) < threshold
        
        assert metrics.is_degraded == expected_degraded, (
            f"Metrics is_degraded={metrics.is_degraded} should match "
            f"expected={expected_degraded} for quality={metrics.quality_score * 100:.1f}%, "
            f"threshold={threshold:.1f}%"
        )
