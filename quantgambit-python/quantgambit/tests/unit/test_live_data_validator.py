"""Unit tests for LiveDataValidator.

Feature: live-orderbook-data-storage
"""

import pytest

from quantgambit.storage.live_data_validator import LiveDataValidator, GapWarning
from quantgambit.storage.persistence import LiveValidationConfig


class TestDetectOrderbookGap:
    """Tests for detect_orderbook_gap method."""
    
    def test_no_gap_consecutive_sequences(self):
        """No gap when actual_seq = expected_seq + 1."""
        validator = LiveDataValidator()
        
        # expected 100, got 101 - no gap
        result = validator.detect_orderbook_gap("BTC/USDT", 100, 101)
        assert result is None
    
    def test_no_gap_same_sequence(self):
        """No gap when actual_seq = expected_seq (duplicate)."""
        validator = LiveDataValidator()
        
        # expected 100, got 100 - no gap (duplicate)
        result = validator.detect_orderbook_gap("BTC/USDT", 100, 100)
        assert result is None
    
    def test_no_gap_lower_sequence(self):
        """No gap when actual_seq < expected_seq (out of order)."""
        validator = LiveDataValidator()
        
        # expected 100, got 99 - no gap (out of order)
        result = validator.detect_orderbook_gap("BTC/USDT", 100, 99)
        assert result is None
    
    def test_gap_of_one(self):
        """Gap of 1 when actual_seq = expected_seq + 2."""
        validator = LiveDataValidator()
        
        # expected 100, got 102 - gap of 1 (missed 101)
        result = validator.detect_orderbook_gap("BTC/USDT", 100, 102)
        assert result == 1
    
    def test_gap_of_five(self):
        """Gap of 5 when actual_seq = expected_seq + 6."""
        validator = LiveDataValidator()
        
        # expected 100, got 106 - gap of 5 (missed 101-105)
        result = validator.detect_orderbook_gap("BTC/USDT", 100, 106)
        assert result == 5
    
    def test_large_gap(self):
        """Large gap detection."""
        validator = LiveDataValidator()
        
        # expected 1000, got 2000 - gap of 999
        result = validator.detect_orderbook_gap("BTC/USDT", 1000, 2000)
        assert result == 999
    
    def test_gap_from_zero(self):
        """Gap detection starting from sequence 0."""
        validator = LiveDataValidator()
        
        # expected 0, got 5 - gap of 4 (missed 1-4)
        result = validator.detect_orderbook_gap("BTC/USDT", 0, 5)
        assert result == 4


class TestRecordOrderbookUpdate:
    """Tests for record_orderbook_update method."""
    
    def test_first_update_no_gap(self):
        """First update should not trigger a gap."""
        validator = LiveDataValidator()
        
        # First update - no previous sequence to compare
        validator.record_orderbook_update("BTC/USDT", "binance", 1000.0, 100)
        
        assert validator.get_expected_seq("BTC/USDT", "binance") == 100
        assert validator.get_seq_gap_count("BTC/USDT", "binance") == 0
    
    def test_consecutive_updates_no_gap(self):
        """Consecutive updates should not trigger gaps."""
        validator = LiveDataValidator()
        
        validator.record_orderbook_update("BTC/USDT", "binance", 1000.0, 100)
        validator.record_orderbook_update("BTC/USDT", "binance", 1001.0, 101)
        validator.record_orderbook_update("BTC/USDT", "binance", 1002.0, 102)
        
        assert validator.get_expected_seq("BTC/USDT", "binance") == 102
        assert validator.get_seq_gap_count("BTC/USDT", "binance") == 0
    
    def test_gap_detected_and_counted(self):
        """Gap should be detected and counted."""
        validator = LiveDataValidator()
        
        validator.record_orderbook_update("BTC/USDT", "binance", 1000.0, 100)
        validator.record_orderbook_update("BTC/USDT", "binance", 1001.0, 105)  # Gap!
        
        assert validator.get_expected_seq("BTC/USDT", "binance") == 105
        assert validator.get_seq_gap_count("BTC/USDT", "binance") == 1
    
    def test_multiple_gaps_counted(self):
        """Multiple gaps should be counted."""
        validator = LiveDataValidator()
        
        validator.record_orderbook_update("BTC/USDT", "binance", 1000.0, 100)
        validator.record_orderbook_update("BTC/USDT", "binance", 1001.0, 105)  # Gap 1
        validator.record_orderbook_update("BTC/USDT", "binance", 1002.0, 110)  # Gap 2
        validator.record_orderbook_update("BTC/USDT", "binance", 1003.0, 111)  # No gap
        validator.record_orderbook_update("BTC/USDT", "binance", 1004.0, 120)  # Gap 3
        
        assert validator.get_seq_gap_count("BTC/USDT", "binance") == 3
    
    def test_different_symbols_tracked_separately(self):
        """Different symbols should be tracked separately."""
        validator = LiveDataValidator()
        
        validator.record_orderbook_update("BTC/USDT", "binance", 1000.0, 100)
        validator.record_orderbook_update("ETH/USDT", "binance", 1000.0, 200)
        
        validator.record_orderbook_update("BTC/USDT", "binance", 1001.0, 105)  # Gap
        validator.record_orderbook_update("ETH/USDT", "binance", 1001.0, 201)  # No gap
        
        assert validator.get_seq_gap_count("BTC/USDT", "binance") == 1
        assert validator.get_seq_gap_count("ETH/USDT", "binance") == 0
    
    def test_different_exchanges_tracked_separately(self):
        """Different exchanges should be tracked separately."""
        validator = LiveDataValidator()
        
        validator.record_orderbook_update("BTC/USDT", "binance", 1000.0, 100)
        validator.record_orderbook_update("BTC/USDT", "coinbase", 1000.0, 100)
        
        validator.record_orderbook_update("BTC/USDT", "binance", 1001.0, 105)  # Gap
        validator.record_orderbook_update("BTC/USDT", "coinbase", 1001.0, 101)  # No gap
        
        assert validator.get_seq_gap_count("BTC/USDT", "binance") == 1
        assert validator.get_seq_gap_count("BTC/USDT", "coinbase") == 0
    
    def test_disabled_config_skips_tracking(self):
        """When disabled, no tracking should occur."""
        config = LiveValidationConfig(enabled=False)
        validator = LiveDataValidator(config=config)
        
        validator.record_orderbook_update("BTC/USDT", "binance", 1000.0, 100)
        validator.record_orderbook_update("BTC/USDT", "binance", 1001.0, 105)  # Would be gap
        
        assert validator.get_expected_seq("BTC/USDT", "binance") is None
        assert validator.get_seq_gap_count("BTC/USDT", "binance") == 0


class TestRecordTrade:
    """Tests for record_trade method."""
    
    def test_first_trade_no_gap(self):
        """First trade should not trigger a gap."""
        validator = LiveDataValidator()
        
        validator.record_trade("BTC/USDT", "binance", 1000.0)
        
        assert validator.get_last_trade_ts("BTC/USDT", "binance") == 1000.0
        assert validator.get_trade_gap_count("BTC/USDT", "binance") == 0
    
    def test_consecutive_trades_no_gap(self):
        """Trades within threshold should not trigger gaps."""
        config = LiveValidationConfig(gap_threshold_sec=5.0)
        validator = LiveDataValidator(config=config)
        
        validator.record_trade("BTC/USDT", "binance", 1000.0)
        validator.record_trade("BTC/USDT", "binance", 1002.0)  # 2s later
        validator.record_trade("BTC/USDT", "binance", 1005.0)  # 3s later
        
        assert validator.get_trade_gap_count("BTC/USDT", "binance") == 0
    
    def test_gap_detected_when_threshold_exceeded(self):
        """Gap should be detected when time delta exceeds threshold."""
        config = LiveValidationConfig(gap_threshold_sec=5.0)
        validator = LiveDataValidator(config=config)
        
        validator.record_trade("BTC/USDT", "binance", 1000.0)
        validator.record_trade("BTC/USDT", "binance", 1010.0)  # 10s later - gap!
        
        assert validator.get_trade_gap_count("BTC/USDT", "binance") == 1
    
    def test_gap_at_exact_threshold_no_gap(self):
        """Gap should not be detected at exactly the threshold."""
        config = LiveValidationConfig(gap_threshold_sec=5.0)
        validator = LiveDataValidator(config=config)
        
        validator.record_trade("BTC/USDT", "binance", 1000.0)
        validator.record_trade("BTC/USDT", "binance", 1005.0)  # Exactly 5s - no gap
        
        assert validator.get_trade_gap_count("BTC/USDT", "binance") == 0


class TestResetSymbol:
    """Tests for reset_symbol method."""
    
    def test_reset_clears_all_state(self):
        """Reset should clear all tracking state for a symbol."""
        validator = LiveDataValidator()
        
        # Record some data
        validator.record_orderbook_update("BTC/USDT", "binance", 1000.0, 100)
        validator.record_orderbook_update("BTC/USDT", "binance", 1001.0, 105)  # Gap
        validator.record_trade("BTC/USDT", "binance", 1000.0)
        
        # Verify state exists
        assert validator.get_expected_seq("BTC/USDT", "binance") == 105
        assert validator.get_seq_gap_count("BTC/USDT", "binance") == 1
        assert validator.get_last_trade_ts("BTC/USDT", "binance") == 1000.0
        
        # Reset
        validator.reset_symbol("BTC/USDT", "binance")
        
        # Verify state is cleared
        assert validator.get_expected_seq("BTC/USDT", "binance") is None
        assert validator.get_seq_gap_count("BTC/USDT", "binance") == 0
        assert validator.get_last_trade_ts("BTC/USDT", "binance") is None
    
    def test_reset_does_not_affect_other_symbols(self):
        """Reset should not affect other symbols."""
        validator = LiveDataValidator()
        
        # Record data for two symbols
        validator.record_orderbook_update("BTC/USDT", "binance", 1000.0, 100)
        validator.record_orderbook_update("ETH/USDT", "binance", 1000.0, 200)
        
        # Reset only BTC
        validator.reset_symbol("BTC/USDT", "binance")
        
        # BTC should be cleared
        assert validator.get_expected_seq("BTC/USDT", "binance") is None
        
        # ETH should still have data
        assert validator.get_expected_seq("ETH/USDT", "binance") == 200


class TestGapWarningEmission:
    """Tests for gap warning emission functionality.
    
    Validates: Requirements 4.3
    """
    
    def test_sequence_gap_emits_warning(self):
        """Sequence gap should emit a warning with correct fields."""
        validator = LiveDataValidator()
        
        # Record first update
        validator.record_orderbook_update("BTC/USDT", "binance", 1000.0, 100)
        
        # Record update with gap
        validator.record_orderbook_update("BTC/USDT", "binance", 1001.0, 105)
        
        # Check warning was emitted
        warnings = validator.get_emitted_warnings()
        assert len(warnings) == 1
        
        warning = warnings[0]
        assert warning.symbol == "BTC/USDT"
        assert warning.exchange == "binance"
        assert warning.gap_type == "sequence"
        assert warning.duration == 4.0  # Gap of 4 (missed 101, 102, 103, 104)
        assert warning.timestamp == 1001.0
    
    def test_timestamp_gap_emits_warning(self):
        """Timestamp gap should emit a warning with correct fields."""
        config = LiveValidationConfig(gap_threshold_sec=5.0)
        validator = LiveDataValidator(config=config)
        
        # Record first trade
        validator.record_trade("BTC/USDT", "binance", 1000.0)
        
        # Record trade with gap (10 seconds later, threshold is 5)
        validator.record_trade("BTC/USDT", "binance", 1010.0)
        
        # Check warning was emitted
        warnings = validator.get_emitted_warnings()
        assert len(warnings) == 1
        
        warning = warnings[0]
        assert warning.symbol == "BTC/USDT"
        assert warning.exchange == "binance"
        assert warning.gap_type == "timestamp"
        assert warning.duration == 10.0  # 10 seconds gap
        assert warning.timestamp == 1010.0
    
    def test_multiple_gaps_emit_multiple_warnings(self):
        """Multiple gaps should emit multiple warnings."""
        validator = LiveDataValidator()
        
        # Record updates with multiple gaps
        validator.record_orderbook_update("BTC/USDT", "binance", 1000.0, 100)
        validator.record_orderbook_update("BTC/USDT", "binance", 1001.0, 105)  # Gap 1
        validator.record_orderbook_update("BTC/USDT", "binance", 1002.0, 110)  # Gap 2
        validator.record_orderbook_update("BTC/USDT", "binance", 1003.0, 111)  # No gap
        validator.record_orderbook_update("BTC/USDT", "binance", 1004.0, 120)  # Gap 3
        
        # Check warnings
        warnings = validator.get_emitted_warnings()
        assert len(warnings) == 3
        
        # All should be sequence gaps
        for warning in warnings:
            assert warning.gap_type == "sequence"
            assert warning.symbol == "BTC/USDT"
            assert warning.exchange == "binance"
    
    def test_warning_contains_symbol(self):
        """Warning should contain the affected symbol."""
        validator = LiveDataValidator()
        
        validator.record_orderbook_update("ETH/USDT", "coinbase", 1000.0, 100)
        validator.record_orderbook_update("ETH/USDT", "coinbase", 1001.0, 105)
        
        warnings = validator.get_emitted_warnings()
        assert len(warnings) == 1
        assert warnings[0].symbol == "ETH/USDT"
    
    def test_warning_contains_duration_for_sequence_gap(self):
        """Warning should contain duration (sequence count) for sequence gaps."""
        validator = LiveDataValidator()
        
        validator.record_orderbook_update("BTC/USDT", "binance", 1000.0, 100)
        validator.record_orderbook_update("BTC/USDT", "binance", 1001.0, 110)  # Gap of 9
        
        warnings = validator.get_emitted_warnings()
        assert len(warnings) == 1
        assert warnings[0].duration == 9.0
    
    def test_warning_contains_duration_for_timestamp_gap(self):
        """Warning should contain duration (seconds) for timestamp gaps."""
        config = LiveValidationConfig(gap_threshold_sec=5.0)
        validator = LiveDataValidator(config=config)
        
        validator.record_trade("BTC/USDT", "binance", 1000.0)
        validator.record_trade("BTC/USDT", "binance", 1025.5)  # 25.5 seconds gap
        
        warnings = validator.get_emitted_warnings()
        assert len(warnings) == 1
        assert warnings[0].duration == 25.5
    
    def test_warning_contains_gap_type_sequence(self):
        """Warning should have gap_type='sequence' for orderbook gaps."""
        validator = LiveDataValidator()
        
        validator.record_orderbook_update("BTC/USDT", "binance", 1000.0, 100)
        validator.record_orderbook_update("BTC/USDT", "binance", 1001.0, 105)
        
        warnings = validator.get_emitted_warnings()
        assert len(warnings) == 1
        assert warnings[0].gap_type == "sequence"
    
    def test_warning_contains_gap_type_timestamp(self):
        """Warning should have gap_type='timestamp' for trade gaps."""
        config = LiveValidationConfig(gap_threshold_sec=5.0)
        validator = LiveDataValidator(config=config)
        
        validator.record_trade("BTC/USDT", "binance", 1000.0)
        validator.record_trade("BTC/USDT", "binance", 1010.0)
        
        warnings = validator.get_emitted_warnings()
        assert len(warnings) == 1
        assert warnings[0].gap_type == "timestamp"
    
    def test_no_warning_when_no_gap(self):
        """No warning should be emitted when there's no gap."""
        validator = LiveDataValidator()
        
        # Consecutive updates - no gap
        validator.record_orderbook_update("BTC/USDT", "binance", 1000.0, 100)
        validator.record_orderbook_update("BTC/USDT", "binance", 1001.0, 101)
        validator.record_orderbook_update("BTC/USDT", "binance", 1002.0, 102)
        
        warnings = validator.get_emitted_warnings()
        assert len(warnings) == 0
    
    def test_no_warning_when_disabled(self):
        """No warning should be emitted when validator is disabled."""
        config = LiveValidationConfig(enabled=False)
        validator = LiveDataValidator(config=config)
        
        # Would be a gap if enabled
        validator.record_orderbook_update("BTC/USDT", "binance", 1000.0, 100)
        validator.record_orderbook_update("BTC/USDT", "binance", 1001.0, 105)
        
        warnings = validator.get_emitted_warnings()
        assert len(warnings) == 0
    
    def test_get_warnings_for_symbol(self):
        """get_warnings_for_symbol should filter by symbol and exchange."""
        validator = LiveDataValidator()
        
        # Create gaps for different symbols
        validator.record_orderbook_update("BTC/USDT", "binance", 1000.0, 100)
        validator.record_orderbook_update("BTC/USDT", "binance", 1001.0, 105)  # Gap
        
        validator.record_orderbook_update("ETH/USDT", "binance", 1000.0, 200)
        validator.record_orderbook_update("ETH/USDT", "binance", 1001.0, 210)  # Gap
        
        # Get warnings for BTC only
        btc_warnings = validator.get_warnings_for_symbol("BTC/USDT", "binance")
        assert len(btc_warnings) == 1
        assert btc_warnings[0].symbol == "BTC/USDT"
        
        # Get warnings for ETH only
        eth_warnings = validator.get_warnings_for_symbol("ETH/USDT", "binance")
        assert len(eth_warnings) == 1
        assert eth_warnings[0].symbol == "ETH/USDT"
    
    def test_clear_warnings(self):
        """clear_warnings should remove all warnings."""
        validator = LiveDataValidator()
        
        # Create a gap
        validator.record_orderbook_update("BTC/USDT", "binance", 1000.0, 100)
        validator.record_orderbook_update("BTC/USDT", "binance", 1001.0, 105)
        
        assert len(validator.get_emitted_warnings()) == 1
        
        # Clear warnings
        validator.clear_warnings()
        
        assert len(validator.get_emitted_warnings()) == 0
    
    def test_warning_has_timestamp(self):
        """Warning should have the timestamp when the gap was detected."""
        validator = LiveDataValidator()
        
        validator.record_orderbook_update("BTC/USDT", "binance", 1000.0, 100)
        validator.record_orderbook_update("BTC/USDT", "binance", 1005.5, 105)
        
        warnings = validator.get_emitted_warnings()
        assert len(warnings) == 1
        assert warnings[0].timestamp == 1005.5
    
    def test_warning_has_details(self):
        """Warning should have details about the gap."""
        validator = LiveDataValidator()
        
        validator.record_orderbook_update("BTC/USDT", "binance", 1000.0, 100)
        validator.record_orderbook_update("BTC/USDT", "binance", 1001.0, 105)
        
        warnings = validator.get_emitted_warnings()
        assert len(warnings) == 1
        assert warnings[0].details is not None
        assert "expected seq 101" in warnings[0].details
        assert "got 105" in warnings[0].details


class TestCompletenessCalculation:
    """Tests for completeness calculation functionality.
    
    Validates: Requirements 4.6
    """
    
    def test_no_updates_returns_zero(self):
        """Completeness should be 0% when no updates have been recorded."""
        validator = LiveDataValidator()
        
        assert validator.get_orderbook_completeness_pct("BTC/USDT", "binance") == 0.0
        assert validator.get_trade_completeness_pct("BTC/USDT", "binance") == 0.0
    
    def test_perfect_completeness(self):
        """Completeness should be 100% when actual matches expected."""
        config = LiveValidationConfig(
            completeness_window_sec=10.0,
            expected_orderbook_updates_per_sec=1.0,
        )
        validator = LiveDataValidator(config=config)
        
        # Record 10 updates over 10 seconds (1 per second = expected rate)
        base_time = 1000.0
        for i in range(10):
            validator.record_orderbook_update(
                "BTC/USDT", "binance", base_time + i, seq=100 + i
            )
        
        # At time 1009, we have 10 updates over ~9 seconds
        # Expected = 9 * 1.0 = 9, Actual = 10
        # Completeness = min(10/9 * 100, 100) = 100%
        completeness = validator.get_orderbook_completeness_pct(
            "BTC/USDT", "binance", current_time=base_time + 9
        )
        assert completeness == 100.0
    
    def test_partial_completeness(self):
        """Completeness should reflect actual/expected ratio."""
        config = LiveValidationConfig(
            completeness_window_sec=10.0,
            expected_orderbook_updates_per_sec=2.0,  # Expect 2 per second
        )
        validator = LiveDataValidator(config=config)
        
        # Record 10 updates over 10 seconds (1 per second, but expect 2)
        base_time = 1000.0
        for i in range(10):
            validator.record_orderbook_update(
                "BTC/USDT", "binance", base_time + i, seq=100 + i
            )
        
        # At time 1009, we have 10 updates over ~9 seconds
        # Expected = 9 * 2.0 = 18, Actual = 10
        # Completeness = 10/18 * 100 = 55.55%
        completeness = validator.get_orderbook_completeness_pct(
            "BTC/USDT", "binance", current_time=base_time + 9
        )
        assert 55.0 <= completeness <= 56.0
    
    def test_rolling_window_removes_old_updates(self):
        """Updates outside the rolling window should be removed."""
        config = LiveValidationConfig(
            completeness_window_sec=5.0,
            expected_orderbook_updates_per_sec=1.0,
        )
        validator = LiveDataValidator(config=config)
        
        # Record updates at times 1000, 1001, 1002, 1003, 1004
        base_time = 1000.0
        for i in range(5):
            validator.record_orderbook_update(
                "BTC/USDT", "binance", base_time + i, seq=100 + i
            )
        
        # At time 1004, all 5 updates are in window
        assert validator.get_update_count_in_window("BTC/USDT", "binance") == 5
        
        # Record update at time 1010 (5 seconds later)
        validator.record_orderbook_update("BTC/USDT", "binance", 1010.0, seq=105)
        
        # Now only updates from 1005+ should be in window
        # The update at 1010 is in window, but 1000-1004 are outside
        assert validator.get_update_count_in_window("BTC/USDT", "binance") == 1
    
    def test_trade_completeness(self):
        """Trade completeness should work similarly to orderbook completeness."""
        config = LiveValidationConfig(
            completeness_window_sec=10.0,
            expected_trades_per_sec=5.0,  # Expect 5 trades per second
            gap_threshold_sec=100.0,  # High threshold to avoid gap warnings
        )
        validator = LiveDataValidator(config=config)
        
        # Record 25 trades over 10 seconds (2.5 per second, expect 5)
        base_time = 1000.0
        for i in range(25):
            validator.record_trade("BTC/USDT", "binance", base_time + i * 0.4)
        
        # At time 1009.6, we have 25 trades over ~9.6 seconds
        # Expected = 9.6 * 5.0 = 48, Actual = 25
        # Completeness = 25/48 * 100 = 52.08%
        completeness = validator.get_trade_completeness_pct(
            "BTC/USDT", "binance", current_time=base_time + 9.6
        )
        assert 50.0 <= completeness <= 55.0
    
    def test_completeness_capped_at_100(self):
        """Completeness should be capped at 100% even if actual > expected."""
        config = LiveValidationConfig(
            completeness_window_sec=10.0,
            expected_orderbook_updates_per_sec=1.0,  # Expect 1 per second
        )
        validator = LiveDataValidator(config=config)
        
        # Record 50 updates over 10 seconds (5 per second, expect 1)
        base_time = 1000.0
        for i in range(50):
            validator.record_orderbook_update(
                "BTC/USDT", "binance", base_time + i * 0.2, seq=100 + i
            )
        
        # Completeness should be capped at 100%
        completeness = validator.get_orderbook_completeness_pct(
            "BTC/USDT", "binance", current_time=base_time + 9.8
        )
        assert completeness == 100.0
    
    def test_different_symbols_tracked_separately(self):
        """Completeness should be tracked separately for different symbols."""
        config = LiveValidationConfig(
            completeness_window_sec=10.0,
            expected_orderbook_updates_per_sec=1.0,
        )
        validator = LiveDataValidator(config=config)
        
        base_time = 1000.0
        
        # Record 10 updates for BTC
        for i in range(10):
            validator.record_orderbook_update(
                "BTC/USDT", "binance", base_time + i, seq=100 + i
            )
        
        # Record 5 updates for ETH
        for i in range(5):
            validator.record_orderbook_update(
                "ETH/USDT", "binance", base_time + i * 2, seq=200 + i
            )
        
        # BTC should have higher completeness than ETH
        btc_completeness = validator.get_orderbook_completeness_pct(
            "BTC/USDT", "binance", current_time=base_time + 9
        )
        eth_completeness = validator.get_orderbook_completeness_pct(
            "ETH/USDT", "binance", current_time=base_time + 8
        )
        
        assert btc_completeness > eth_completeness
    
    def test_get_completeness_metrics_returns_both(self):
        """get_completeness_metrics should return both orderbook and trade completeness."""
        config = LiveValidationConfig(
            completeness_window_sec=10.0,
            expected_orderbook_updates_per_sec=1.0,
            expected_trades_per_sec=2.0,
            gap_threshold_sec=100.0,
        )
        validator = LiveDataValidator(config=config)
        
        base_time = 1000.0
        
        # Record some orderbook updates
        for i in range(10):
            validator.record_orderbook_update(
                "BTC/USDT", "binance", base_time + i, seq=100 + i
            )
        
        # Record some trades
        for i in range(15):
            validator.record_trade("BTC/USDT", "binance", base_time + i * 0.6)
        
        orderbook_pct, trade_pct = validator.get_completeness_metrics(
            "BTC/USDT", "binance", current_time=base_time + 9
        )
        
        # Both should be non-zero
        assert orderbook_pct > 0.0
        assert trade_pct > 0.0
    
    def test_reset_clears_completeness_tracking(self):
        """reset_symbol should clear completeness tracking data."""
        config = LiveValidationConfig(
            completeness_window_sec=10.0,
            expected_orderbook_updates_per_sec=1.0,
        )
        validator = LiveDataValidator(config=config)
        
        # Record some updates
        for i in range(5):
            validator.record_orderbook_update(
                "BTC/USDT", "binance", 1000.0 + i, seq=100 + i
            )
        
        assert validator.get_update_count_in_window("BTC/USDT", "binance") == 5
        
        # Reset
        validator.reset_symbol("BTC/USDT", "binance")
        
        # Completeness tracking should be cleared
        assert validator.get_update_count_in_window("BTC/USDT", "binance") == 0
        assert validator.get_orderbook_completeness_pct("BTC/USDT", "binance") == 0.0
    
    def test_disabled_config_skips_completeness_tracking(self):
        """When disabled, completeness tracking should be skipped."""
        config = LiveValidationConfig(enabled=False)
        validator = LiveDataValidator(config=config)
        
        # Record updates (should be ignored)
        for i in range(10):
            validator.record_orderbook_update(
                "BTC/USDT", "binance", 1000.0 + i, seq=100 + i
            )
        
        # No updates should be tracked
        assert validator.get_update_count_in_window("BTC/USDT", "binance") == 0
        assert validator.get_orderbook_completeness_pct("BTC/USDT", "binance") == 0.0


class TestQualityThresholdDegradation:
    """Tests for quality threshold degradation functionality.
    
    Validates: Requirements 4.4
    """
    
    def test_calculate_quality_score_no_data(self):
        """Quality score should be 0.0 when no data has been recorded."""
        validator = LiveDataValidator()
        
        score = validator.calculate_quality_score("BTC/USDT", "binance")
        assert score == 0.0
    
    def test_calculate_quality_score_perfect(self):
        """Quality score should be 1.0 when completeness is 100%."""
        config = LiveValidationConfig(
            completeness_window_sec=10.0,
            expected_orderbook_updates_per_sec=1.0,
            expected_trades_per_sec=1.0,
            gap_threshold_sec=100.0,  # High threshold to avoid gaps
        )
        validator = LiveDataValidator(config=config)
        
        base_time = 1000.0
        # Record enough updates to achieve 100% completeness
        for i in range(10):
            validator.record_orderbook_update(
                "BTC/USDT", "binance", base_time + i, seq=100 + i
            )
            validator.record_trade("BTC/USDT", "binance", base_time + i)
        
        score = validator.calculate_quality_score(
            "BTC/USDT", "binance", current_time=base_time + 9
        )
        assert score == 1.0
    
    def test_calculate_quality_score_partial(self):
        """Quality score should reflect partial completeness."""
        config = LiveValidationConfig(
            completeness_window_sec=10.0,
            expected_orderbook_updates_per_sec=2.0,  # Expect 2 per second
            expected_trades_per_sec=2.0,  # Expect 2 per second
            gap_threshold_sec=100.0,
        )
        validator = LiveDataValidator(config=config)
        
        base_time = 1000.0
        # Record 10 updates over 10 seconds (1 per second, expect 2)
        for i in range(10):
            validator.record_orderbook_update(
                "BTC/USDT", "binance", base_time + i, seq=100 + i
            )
            validator.record_trade("BTC/USDT", "binance", base_time + i)
        
        score = validator.calculate_quality_score(
            "BTC/USDT", "binance", current_time=base_time + 9
        )
        # Both orderbook and trade completeness should be ~55%
        # Quality score = (55 + 55) / 200 = 0.55
        assert 0.5 <= score <= 0.6
    
    def test_is_degraded_initially_false(self):
        """is_degraded should be False initially."""
        validator = LiveDataValidator()
        
        assert validator.is_degraded("BTC/USDT", "binance") is False
    
    def test_check_quality_threshold_sets_degraded_true(self):
        """check_quality_threshold should set is_degraded to True when below threshold."""
        config = LiveValidationConfig(
            completeness_window_sec=10.0,
            expected_orderbook_updates_per_sec=10.0,  # High expectation
            expected_trades_per_sec=10.0,  # High expectation
            min_completeness_pct=80.0,  # 80% threshold
            gap_threshold_sec=100.0,
        )
        validator = LiveDataValidator(config=config)
        
        base_time = 1000.0
        # Record only 2 updates (expect 90 over 9 seconds)
        validator.record_orderbook_update("BTC/USDT", "binance", base_time, seq=100)
        validator.record_trade("BTC/USDT", "binance", base_time)
        validator.record_orderbook_update("BTC/USDT", "binance", base_time + 9, seq=101)
        validator.record_trade("BTC/USDT", "binance", base_time + 9)
        
        # Check threshold - should be degraded
        is_degraded = validator.check_quality_threshold(
            "BTC/USDT", "binance", current_time=base_time + 9
        )
        
        assert is_degraded is True
        assert validator.is_degraded("BTC/USDT", "binance") is True
    
    def test_check_quality_threshold_sets_degraded_false_when_above(self):
        """check_quality_threshold should set is_degraded to False when above threshold."""
        config = LiveValidationConfig(
            completeness_window_sec=10.0,
            expected_orderbook_updates_per_sec=1.0,
            expected_trades_per_sec=1.0,
            min_completeness_pct=50.0,  # Low threshold
            gap_threshold_sec=100.0,
        )
        validator = LiveDataValidator(config=config)
        
        base_time = 1000.0
        # Record enough updates to exceed threshold
        for i in range(10):
            validator.record_orderbook_update(
                "BTC/USDT", "binance", base_time + i, seq=100 + i
            )
            validator.record_trade("BTC/USDT", "binance", base_time + i)
        
        # Check threshold - should not be degraded
        is_degraded = validator.check_quality_threshold(
            "BTC/USDT", "binance", current_time=base_time + 9
        )
        
        assert is_degraded is False
        assert validator.is_degraded("BTC/USDT", "binance") is False
    
    def test_check_quality_threshold_disabled_returns_false(self):
        """check_quality_threshold should return False when disabled."""
        config = LiveValidationConfig(enabled=False)
        validator = LiveDataValidator(config=config)
        
        is_degraded = validator.check_quality_threshold("BTC/USDT", "binance")
        
        assert is_degraded is False
    
    def test_degradation_recovery(self):
        """Degradation status should recover when quality improves."""
        config = LiveValidationConfig(
            completeness_window_sec=5.0,
            expected_orderbook_updates_per_sec=1.0,
            expected_trades_per_sec=1.0,
            min_completeness_pct=80.0,
            gap_threshold_sec=100.0,
        )
        validator = LiveDataValidator(config=config)
        
        base_time = 1000.0
        
        # First, create degraded state with sparse updates
        validator.record_orderbook_update("BTC/USDT", "binance", base_time, seq=100)
        validator.record_trade("BTC/USDT", "binance", base_time)
        
        # Check - should be degraded (only 1 update over 5 seconds)
        is_degraded = validator.check_quality_threshold(
            "BTC/USDT", "binance", current_time=base_time + 5
        )
        assert is_degraded is True
        
        # Now add more updates to recover
        for i in range(10):
            validator.record_orderbook_update(
                "BTC/USDT", "binance", base_time + 6 + i * 0.5, seq=101 + i
            )
            validator.record_trade("BTC/USDT", "binance", base_time + 6 + i * 0.5)
        
        # Check again - should recover
        is_degraded = validator.check_quality_threshold(
            "BTC/USDT", "binance", current_time=base_time + 10
        )
        assert is_degraded is False
    
    def test_different_symbols_tracked_separately(self):
        """Degradation should be tracked separately for different symbols."""
        config = LiveValidationConfig(
            completeness_window_sec=10.0,
            expected_orderbook_updates_per_sec=10.0,
            expected_trades_per_sec=10.0,
            min_completeness_pct=80.0,
            gap_threshold_sec=100.0,
        )
        validator = LiveDataValidator(config=config)
        
        base_time = 1000.0
        
        # BTC: sparse updates (degraded)
        validator.record_orderbook_update("BTC/USDT", "binance", base_time, seq=100)
        validator.record_trade("BTC/USDT", "binance", base_time)
        
        # ETH: many updates (not degraded)
        for i in range(100):
            validator.record_orderbook_update(
                "ETH/USDT", "binance", base_time + i * 0.1, seq=200 + i
            )
            validator.record_trade("ETH/USDT", "binance", base_time + i * 0.1)
        
        # Check BTC - should be degraded
        btc_degraded = validator.check_quality_threshold(
            "BTC/USDT", "binance", current_time=base_time + 9
        )
        
        # Check ETH - should not be degraded
        eth_degraded = validator.check_quality_threshold(
            "ETH/USDT", "binance", current_time=base_time + 9
        )
        
        assert btc_degraded is True
        assert eth_degraded is False
    
    def test_reset_clears_degradation_status(self):
        """reset_symbol should clear degradation status."""
        config = LiveValidationConfig(
            completeness_window_sec=10.0,
            expected_orderbook_updates_per_sec=10.0,
            expected_trades_per_sec=10.0,
            min_completeness_pct=80.0,
            gap_threshold_sec=100.0,
        )
        validator = LiveDataValidator(config=config)
        
        base_time = 1000.0
        
        # Create degraded state
        validator.record_orderbook_update("BTC/USDT", "binance", base_time, seq=100)
        validator.record_trade("BTC/USDT", "binance", base_time)
        validator.check_quality_threshold(
            "BTC/USDT", "binance", current_time=base_time + 9
        )
        
        assert validator.is_degraded("BTC/USDT", "binance") is True
        
        # Reset
        validator.reset_symbol("BTC/USDT", "binance")
        
        # Should be cleared
        assert validator.is_degraded("BTC/USDT", "binance") is False


class TestGetQualityMetrics:
    """Tests for get_quality_metrics method.
    
    Validates: Requirements 4.3, 4.4
    """
    
    def test_returns_live_quality_metrics(self):
        """get_quality_metrics should return a LiveQualityMetrics object."""
        validator = LiveDataValidator()
        
        metrics = validator.get_quality_metrics("BTC/USDT", "binance", current_time=1000.0)
        
        assert metrics.symbol == "BTC/USDT"
        assert metrics.exchange == "binance"
        assert metrics.timestamp == 1000.0
    
    def test_quality_grade_a(self):
        """Quality grade should be A when score >= 0.9."""
        config = LiveValidationConfig(
            completeness_window_sec=10.0,
            expected_orderbook_updates_per_sec=1.0,
            expected_trades_per_sec=1.0,
            gap_threshold_sec=100.0,
        )
        validator = LiveDataValidator(config=config)
        
        base_time = 1000.0
        # Record enough updates for 100% completeness
        for i in range(10):
            validator.record_orderbook_update(
                "BTC/USDT", "binance", base_time + i, seq=100 + i
            )
            validator.record_trade("BTC/USDT", "binance", base_time + i)
        
        metrics = validator.get_quality_metrics(
            "BTC/USDT", "binance", current_time=base_time + 9
        )
        
        assert metrics.quality_grade == "A"
        assert metrics.quality_score >= 0.9
    
    def test_quality_grade_f(self):
        """Quality grade should be F when score < 0.6."""
        config = LiveValidationConfig(
            completeness_window_sec=10.0,
            expected_orderbook_updates_per_sec=10.0,  # High expectation
            expected_trades_per_sec=10.0,
            gap_threshold_sec=100.0,
        )
        validator = LiveDataValidator(config=config)
        
        base_time = 1000.0
        # Record very few updates
        validator.record_orderbook_update("BTC/USDT", "binance", base_time, seq=100)
        validator.record_trade("BTC/USDT", "binance", base_time)
        
        metrics = validator.get_quality_metrics(
            "BTC/USDT", "binance", current_time=base_time + 9
        )
        
        assert metrics.quality_grade == "F"
        assert metrics.quality_score < 0.6
    
    def test_includes_completeness_metrics(self):
        """Metrics should include orderbook and trade completeness."""
        config = LiveValidationConfig(
            completeness_window_sec=10.0,
            expected_orderbook_updates_per_sec=1.0,
            expected_trades_per_sec=1.0,
            gap_threshold_sec=100.0,
        )
        validator = LiveDataValidator(config=config)
        
        base_time = 1000.0
        for i in range(5):
            validator.record_orderbook_update(
                "BTC/USDT", "binance", base_time + i, seq=100 + i
            )
            validator.record_trade("BTC/USDT", "binance", base_time + i)
        
        metrics = validator.get_quality_metrics(
            "BTC/USDT", "binance", current_time=base_time + 4
        )
        
        assert metrics.orderbook_completeness_pct > 0.0
        assert metrics.trade_completeness_pct > 0.0
    
    def test_includes_gap_counts(self):
        """Metrics should include gap counts."""
        validator = LiveDataValidator()
        
        # Create some gaps
        validator.record_orderbook_update("BTC/USDT", "binance", 1000.0, seq=100)
        validator.record_orderbook_update("BTC/USDT", "binance", 1001.0, seq=105)  # Gap
        validator.record_orderbook_update("BTC/USDT", "binance", 1002.0, seq=110)  # Gap
        
        metrics = validator.get_quality_metrics(
            "BTC/USDT", "binance", current_time=1002.0
        )
        
        assert metrics.orderbook_gap_count == 2
        assert metrics.orderbook_seq_gaps == 2
    
    def test_includes_degradation_status(self):
        """Metrics should include is_degraded status."""
        config = LiveValidationConfig(
            completeness_window_sec=10.0,
            expected_orderbook_updates_per_sec=10.0,
            expected_trades_per_sec=10.0,
            min_completeness_pct=80.0,
            gap_threshold_sec=100.0,
        )
        validator = LiveDataValidator(config=config)
        
        base_time = 1000.0
        # Sparse updates - should be degraded
        validator.record_orderbook_update("BTC/USDT", "binance", base_time, seq=100)
        validator.record_trade("BTC/USDT", "binance", base_time)
        
        metrics = validator.get_quality_metrics(
            "BTC/USDT", "binance", current_time=base_time + 9
        )
        
        assert metrics.is_degraded is True
    
    def test_includes_warnings_when_degraded(self):
        """Metrics should include warnings when quality is degraded."""
        config = LiveValidationConfig(
            completeness_window_sec=10.0,
            expected_orderbook_updates_per_sec=10.0,
            expected_trades_per_sec=10.0,
            min_completeness_pct=80.0,
            gap_threshold_sec=100.0,
        )
        validator = LiveDataValidator(config=config)
        
        base_time = 1000.0
        validator.record_orderbook_update("BTC/USDT", "binance", base_time, seq=100)
        validator.record_trade("BTC/USDT", "binance", base_time)
        
        metrics = validator.get_quality_metrics(
            "BTC/USDT", "binance", current_time=base_time + 9
        )
        
        assert len(metrics.warnings) > 0
        # Should have degradation warning
        assert any("degraded" in w.lower() for w in metrics.warnings)
    
    def test_no_warnings_when_healthy(self):
        """Metrics should have no warnings when quality is healthy."""
        config = LiveValidationConfig(
            completeness_window_sec=10.0,
            expected_orderbook_updates_per_sec=1.0,
            expected_trades_per_sec=1.0,
            min_completeness_pct=50.0,  # Low threshold
            gap_threshold_sec=100.0,
        )
        validator = LiveDataValidator(config=config)
        
        base_time = 1000.0
        for i in range(10):
            validator.record_orderbook_update(
                "BTC/USDT", "binance", base_time + i, seq=100 + i
            )
            validator.record_trade("BTC/USDT", "binance", base_time + i)
        
        metrics = validator.get_quality_metrics(
            "BTC/USDT", "binance", current_time=base_time + 9
        )
        
        # Should have no degradation warning
        assert not any("degraded" in w.lower() for w in metrics.warnings)
    
    def test_includes_last_seq_and_ts(self):
        """Metrics should include last sequence number and trade timestamp."""
        config = LiveValidationConfig(gap_threshold_sec=100.0)
        validator = LiveDataValidator(config=config)
        
        validator.record_orderbook_update("BTC/USDT", "binance", 1000.0, seq=12345)
        validator.record_trade("BTC/USDT", "binance", 1001.5)
        
        metrics = validator.get_quality_metrics(
            "BTC/USDT", "binance", current_time=1002.0
        )
        
        assert metrics.orderbook_last_seq == 12345
        assert metrics.trade_last_ts == 1001.5


class TestGetTrackedSymbols:
    """Tests for get_tracked_symbols method."""
    
    def test_empty_when_no_updates(self):
        """Should return empty list when no updates recorded."""
        validator = LiveDataValidator()
        
        symbols = validator.get_tracked_symbols()
        
        assert symbols == []
    
    def test_returns_symbols_from_orderbook_updates(self):
        """Should return symbols that have orderbook updates."""
        validator = LiveDataValidator()
        
        validator.record_orderbook_update("BTC/USDT", "binance", 1000.0, 100)
        
        symbols = validator.get_tracked_symbols()
        
        assert ("BTC/USDT", "binance") in symbols
    
    def test_returns_symbols_from_trade_updates(self):
        """Should return symbols that have trade updates."""
        validator = LiveDataValidator()
        
        validator.record_trade("ETH/USDT", "coinbase", 1000.0)
        
        symbols = validator.get_tracked_symbols()
        
        assert ("ETH/USDT", "coinbase") in symbols
    
    def test_returns_unique_symbols(self):
        """Should return unique symbols even with multiple updates."""
        validator = LiveDataValidator()
        
        validator.record_orderbook_update("BTC/USDT", "binance", 1000.0, 100)
        validator.record_orderbook_update("BTC/USDT", "binance", 1001.0, 101)
        validator.record_trade("BTC/USDT", "binance", 1002.0)
        
        symbols = validator.get_tracked_symbols()
        
        # Should only have one entry for BTC/USDT@binance
        btc_entries = [s for s in symbols if s == ("BTC/USDT", "binance")]
        assert len(btc_entries) == 1
    
    def test_returns_multiple_symbols(self):
        """Should return all tracked symbols."""
        validator = LiveDataValidator()
        
        validator.record_orderbook_update("BTC/USDT", "binance", 1000.0, 100)
        validator.record_orderbook_update("ETH/USDT", "binance", 1000.0, 200)
        validator.record_trade("SOL/USDT", "coinbase", 1000.0)
        
        symbols = validator.get_tracked_symbols()
        
        assert len(symbols) == 3
        assert ("BTC/USDT", "binance") in symbols
        assert ("ETH/USDT", "binance") in symbols
        assert ("SOL/USDT", "coinbase") in symbols


class TestEmitMetrics:
    """Tests for emit_metrics method."""
    
    @pytest.mark.asyncio
    async def test_returns_zero_when_disabled(self):
        """Should return 0 when validator is disabled."""
        config = LiveValidationConfig(enabled=False)
        validator = LiveDataValidator(config=config)
        
        count = await validator.emit_metrics()
        
        assert count == 0
    
    @pytest.mark.asyncio
    async def test_returns_zero_when_no_symbols(self):
        """Should return 0 when no symbols are tracked."""
        validator = LiveDataValidator()
        
        count = await validator.emit_metrics()
        
        assert count == 0
    
    @pytest.mark.asyncio
    async def test_returns_count_of_emitted_symbols(self):
        """Should return count of symbols for which metrics were emitted."""
        validator = LiveDataValidator()
        
        validator.record_orderbook_update("BTC/USDT", "binance", 1000.0, 100)
        validator.record_orderbook_update("ETH/USDT", "binance", 1000.0, 200)
        
        count = await validator.emit_metrics()
        
        assert count == 2
    
    @pytest.mark.asyncio
    async def test_emits_to_snapshot_writer(self):
        """Should emit metrics to Redis snapshot writer."""
        from unittest.mock import AsyncMock, MagicMock
        
        snapshot_writer = MagicMock()
        snapshot_writer.write = AsyncMock()
        
        validator = LiveDataValidator(snapshot_writer=snapshot_writer)
        validator.record_orderbook_update("BTC/USDT", "binance", 1000.0, 100)
        
        await validator.emit_metrics(current_time=1010.0)
        
        # Verify write was called
        snapshot_writer.write.assert_called_once()
        
        # Verify key format
        call_args = snapshot_writer.write.call_args
        key = call_args[0][0]
        assert key == "live_quality:BTC/USDT:binance"
        
        # Verify payload contains expected fields
        payload = call_args[0][1]
        assert payload["symbol"] == "BTC/USDT"
        assert payload["exchange"] == "binance"
        assert "quality_score" in payload
        assert "is_degraded" in payload
    
    @pytest.mark.asyncio
    async def test_emits_to_telemetry(self):
        """Should emit metrics to telemetry pipeline."""
        from unittest.mock import AsyncMock, MagicMock
        
        telemetry = MagicMock()
        telemetry.publish_guardrail = AsyncMock()
        telemetry_context = MagicMock()
        
        validator = LiveDataValidator(
            telemetry=telemetry,
            telemetry_context=telemetry_context,
        )
        validator.record_orderbook_update("BTC/USDT", "binance", 1000.0, 100)
        
        await validator.emit_metrics(current_time=1010.0)
        
        # Verify telemetry was called
        telemetry.publish_guardrail.assert_called_once()
        
        # Verify payload contains event_type
        call_args = telemetry.publish_guardrail.call_args
        payload = call_args[0][1]
        assert payload["event_type"] == "live_quality_metrics"
    
    @pytest.mark.asyncio
    async def test_handles_emission_errors_gracefully(self):
        """Should continue emitting for other symbols if one fails."""
        from unittest.mock import AsyncMock, MagicMock
        
        snapshot_writer = MagicMock()
        # First call raises, second succeeds
        snapshot_writer.write = AsyncMock(side_effect=[Exception("Test error"), None])
        
        validator = LiveDataValidator(snapshot_writer=snapshot_writer)
        validator.record_orderbook_update("BTC/USDT", "binance", 1000.0, 100)
        validator.record_orderbook_update("ETH/USDT", "binance", 1000.0, 200)
        
        # Should not raise, should return count of successful emissions
        count = await validator.emit_metrics(current_time=1010.0)
        
        # One succeeded, one failed
        assert count == 1


class TestBackgroundEmit:
    """Tests for start_background_emit and stop methods."""
    
    @pytest.mark.asyncio
    async def test_start_does_nothing_when_disabled(self):
        """Should not start background task when disabled."""
        config = LiveValidationConfig(enabled=False)
        validator = LiveDataValidator(config=config)
        
        await validator.start_background_emit()
        
        # Should not have a task
        assert not hasattr(validator, "_emit_task") or validator._emit_task is None
    
    @pytest.mark.asyncio
    async def test_stop_without_start_is_safe(self):
        """Should handle stop() when no task is running."""
        validator = LiveDataValidator()
        
        # Should not raise
        await validator.stop()
    
    @pytest.mark.asyncio
    async def test_start_creates_task(self):
        """Should create a background task when started."""
        import asyncio
        
        config = LiveValidationConfig(emit_interval_sec=0.1)
        validator = LiveDataValidator(config=config)
        
        await validator.start_background_emit()
        
        try:
            # Should have a task
            assert hasattr(validator, "_emit_task")
            assert validator._emit_task is not None
            assert not validator._emit_task.done()
        finally:
            await validator.stop()
    
    @pytest.mark.asyncio
    async def test_stop_cancels_task(self):
        """Should cancel the background task when stopped."""
        import asyncio
        
        config = LiveValidationConfig(emit_interval_sec=0.1)
        validator = LiveDataValidator(config=config)
        
        await validator.start_background_emit()
        task = validator._emit_task
        
        await validator.stop()
        
        # Task should be cancelled
        assert task.done()
        assert validator._emit_task is None
    
    @pytest.mark.asyncio
    async def test_background_emit_calls_emit_metrics(self):
        """Should periodically call emit_metrics."""
        import asyncio
        from unittest.mock import AsyncMock, MagicMock
        
        snapshot_writer = MagicMock()
        snapshot_writer.write = AsyncMock()
        
        config = LiveValidationConfig(emit_interval_sec=0.05)  # 50ms
        validator = LiveDataValidator(
            snapshot_writer=snapshot_writer,
            config=config,
        )
        validator.record_orderbook_update("BTC/USDT", "binance", 1000.0, 100)
        
        await validator.start_background_emit()
        
        try:
            # Wait for at least one emission cycle
            await asyncio.sleep(0.15)
            
            # Should have called write at least once
            assert snapshot_writer.write.call_count >= 1
        finally:
            await validator.stop()
    
    @pytest.mark.asyncio
    async def test_double_start_is_safe(self):
        """Should handle double start gracefully."""
        import asyncio
        
        config = LiveValidationConfig(emit_interval_sec=0.1)
        validator = LiveDataValidator(config=config)
        
        await validator.start_background_emit()
        first_task = validator._emit_task
        
        # Second start should not create a new task
        await validator.start_background_emit()
        
        try:
            assert validator._emit_task is first_task
        finally:
            await validator.stop()
    
    @pytest.mark.asyncio
    async def test_stop_performs_final_emission(self):
        """Should emit metrics one final time when stopping."""
        from unittest.mock import AsyncMock, MagicMock
        
        snapshot_writer = MagicMock()
        snapshot_writer.write = AsyncMock()
        
        config = LiveValidationConfig(emit_interval_sec=10.0)  # Long interval
        validator = LiveDataValidator(
            snapshot_writer=snapshot_writer,
            config=config,
        )
        validator.record_orderbook_update("BTC/USDT", "binance", 1000.0, 100)
        
        await validator.start_background_emit()
        
        # Clear any calls from startup
        snapshot_writer.write.reset_mock()
        
        # Stop should trigger final emission
        await validator.stop()
        
        # Should have called write for final emission
        assert snapshot_writer.write.call_count >= 1
