"""Property-based tests for gap warning emission.

Feature: live-orderbook-data-storage, Property 10: Gap Warning Emission

Tests that for any detected gap (sequence or timestamp), the emitted warning
event SHALL contain: the affected symbol, the gap duration (in seconds or
sequence count), and the gap type.

**Validates: Requirements 4.3**
"""

from __future__ import annotations

import pytest
from hypothesis import given, strategies as st, settings, assume

from quantgambit.storage.live_data_validator import LiveDataValidator, GapWarning
from quantgambit.storage.persistence import LiveValidationConfig


# =============================================================================
# Strategies for generating test data
# =============================================================================

# Sequence number generator (positive integers)
sequence_number = st.integers(min_value=1, max_value=1_000_000)

# Gap size generator (positive integers representing missed sequences)
gap_size = st.integers(min_value=1, max_value=10_000)

# Timestamp generator (seconds since epoch, realistic range)
timestamp = st.floats(min_value=1600000000.0, max_value=2000000000.0, allow_nan=False, allow_infinity=False)

# Time delta generator (positive time differences)
time_delta = st.floats(min_value=0.001, max_value=3600.0, allow_nan=False, allow_infinity=False)

# Gap threshold generator (configurable threshold values)
gap_threshold = st.floats(min_value=0.1, max_value=60.0, allow_nan=False, allow_infinity=False)

# Symbol generator
symbol = st.sampled_from(["BTC/USDT", "ETH/USDT", "SOL/USDT", "DOGE/USDT", "XRP/USDT"])

# Exchange generator
exchange = st.sampled_from(["binance", "coinbase", "kraken", "okx", "bybit"])


# =============================================================================
# Property 10: Gap Warning Emission
# =============================================================================


class TestGapWarningEmission:
    """Property 10: Gap Warning Emission
    
    For any detected gap (sequence or timestamp), the emitted warning event
    SHALL contain: the affected symbol, the gap duration (in seconds or
    sequence count), and the gap type.
    
    **Validates: Requirements 4.3**
    """

    # =========================================================================
    # Sequence Gap Warning Tests
    # =========================================================================

    @given(
        first_seq=sequence_number,
        gap=gap_size,
        ts=timestamp,
        sym=symbol,
        exch=exchange,
    )
    @settings(max_examples=100)
    def test_sequence_gap_warning_contains_symbol(
        self,
        first_seq: int,
        gap: int,
        ts: float,
        sym: str,
        exch: str,
    ):
        """Verify sequence gap warning contains the affected symbol.
        
        When a sequence gap is detected, the emitted warning event must
        contain the symbol that was affected by the gap.
        
        **Validates: Requirements 4.3**
        """
        config = LiveValidationConfig(enabled=True)
        validator = LiveDataValidator(config=config)
        
        # Record first orderbook update
        validator.record_orderbook_update(sym, exch, ts, first_seq)
        
        # Record second update with a gap (skip some sequences)
        second_seq = first_seq + 1 + gap
        validator.record_orderbook_update(sym, exch, ts + 1.0, second_seq)
        
        # Get emitted warnings
        warnings = validator.get_emitted_warnings()
        
        # Should have exactly one warning
        assert len(warnings) == 1, (
            f"Expected 1 warning, got {len(warnings)}"
        )
        
        # Warning should contain the correct symbol
        warning = warnings[0]
        assert warning.symbol == sym, (
            f"Warning symbol should be '{sym}', got '{warning.symbol}'"
        )

    @given(
        first_seq=sequence_number,
        gap=gap_size,
        ts=timestamp,
        sym=symbol,
        exch=exchange,
    )
    @settings(max_examples=100)
    def test_sequence_gap_warning_contains_duration(
        self,
        first_seq: int,
        gap: int,
        ts: float,
        sym: str,
        exch: str,
    ):
        """Verify sequence gap warning contains the gap duration (sequence count).
        
        When a sequence gap is detected, the emitted warning event must
        contain the duration as the number of missed sequences.
        
        **Validates: Requirements 4.3**
        """
        config = LiveValidationConfig(enabled=True)
        validator = LiveDataValidator(config=config)
        
        # Record first orderbook update
        validator.record_orderbook_update(sym, exch, ts, first_seq)
        
        # Record second update with a gap
        second_seq = first_seq + 1 + gap
        validator.record_orderbook_update(sym, exch, ts + 1.0, second_seq)
        
        # Get emitted warnings
        warnings = validator.get_emitted_warnings()
        
        # Should have exactly one warning
        assert len(warnings) == 1, (
            f"Expected 1 warning, got {len(warnings)}"
        )
        
        # Warning duration should equal the gap size (sequence count)
        warning = warnings[0]
        assert warning.duration == float(gap), (
            f"Warning duration should be {gap} (sequence count), got {warning.duration}"
        )

    @given(
        first_seq=sequence_number,
        gap=gap_size,
        ts=timestamp,
        sym=symbol,
        exch=exchange,
    )
    @settings(max_examples=100)
    def test_sequence_gap_warning_contains_gap_type(
        self,
        first_seq: int,
        gap: int,
        ts: float,
        sym: str,
        exch: str,
    ):
        """Verify sequence gap warning contains gap_type="sequence".
        
        When a sequence gap is detected, the emitted warning event must
        have gap_type set to "sequence" to distinguish it from timestamp gaps.
        
        **Validates: Requirements 4.3**
        """
        config = LiveValidationConfig(enabled=True)
        validator = LiveDataValidator(config=config)
        
        # Record first orderbook update
        validator.record_orderbook_update(sym, exch, ts, first_seq)
        
        # Record second update with a gap
        second_seq = first_seq + 1 + gap
        validator.record_orderbook_update(sym, exch, ts + 1.0, second_seq)
        
        # Get emitted warnings
        warnings = validator.get_emitted_warnings()
        
        # Should have exactly one warning
        assert len(warnings) == 1, (
            f"Expected 1 warning, got {len(warnings)}"
        )
        
        # Warning gap_type should be "sequence"
        warning = warnings[0]
        assert warning.gap_type == "sequence", (
            f"Warning gap_type should be 'sequence', got '{warning.gap_type}'"
        )

    @given(
        first_seq=sequence_number,
        gap=gap_size,
        ts=timestamp,
        sym=symbol,
        exch=exchange,
    )
    @settings(max_examples=100)
    def test_sequence_gap_warning_contains_all_required_fields(
        self,
        first_seq: int,
        gap: int,
        ts: float,
        sym: str,
        exch: str,
    ):
        """Verify sequence gap warning contains all required fields.
        
        When a sequence gap is detected, the emitted warning event must
        contain: symbol, duration (sequence count), and gap_type="sequence".
        
        **Validates: Requirements 4.3**
        """
        config = LiveValidationConfig(enabled=True)
        validator = LiveDataValidator(config=config)
        
        # Record first orderbook update
        validator.record_orderbook_update(sym, exch, ts, first_seq)
        
        # Record second update with a gap
        second_seq = first_seq + 1 + gap
        second_ts = ts + 1.0
        validator.record_orderbook_update(sym, exch, second_ts, second_seq)
        
        # Get emitted warnings
        warnings = validator.get_emitted_warnings()
        
        # Should have exactly one warning
        assert len(warnings) == 1, (
            f"Expected 1 warning, got {len(warnings)}"
        )
        
        warning = warnings[0]
        
        # Verify all required fields are present and correct
        assert warning.symbol == sym, (
            f"Warning symbol should be '{sym}', got '{warning.symbol}'"
        )
        assert warning.exchange == exch, (
            f"Warning exchange should be '{exch}', got '{warning.exchange}'"
        )
        assert warning.gap_type == "sequence", (
            f"Warning gap_type should be 'sequence', got '{warning.gap_type}'"
        )
        assert warning.duration == float(gap), (
            f"Warning duration should be {gap}, got {warning.duration}"
        )
        assert warning.timestamp == second_ts, (
            f"Warning timestamp should be {second_ts}, got {warning.timestamp}"
        )

    # =========================================================================
    # Timestamp Gap Warning Tests
    # =========================================================================

    @given(
        first_ts=timestamp,
        threshold=gap_threshold,
        extra_time=st.floats(min_value=0.001, max_value=100.0, allow_nan=False, allow_infinity=False),
        sym=symbol,
        exch=exchange,
    )
    @settings(max_examples=100)
    def test_timestamp_gap_warning_contains_symbol(
        self,
        first_ts: float,
        threshold: float,
        extra_time: float,
        sym: str,
        exch: str,
    ):
        """Verify timestamp gap warning contains the affected symbol.
        
        When a timestamp gap is detected, the emitted warning event must
        contain the symbol that was affected by the gap.
        
        **Validates: Requirements 4.3**
        """
        config = LiveValidationConfig(
            enabled=True,
            gap_threshold_sec=threshold,
        )
        validator = LiveDataValidator(config=config)
        
        # Record first trade
        validator.record_trade(sym, exch, first_ts)
        
        # Record second trade with a gap (time > threshold)
        second_ts = first_ts + threshold + extra_time
        validator.record_trade(sym, exch, second_ts)
        
        # Get emitted warnings
        warnings = validator.get_emitted_warnings()
        
        # Should have exactly one warning
        assert len(warnings) == 1, (
            f"Expected 1 warning, got {len(warnings)}"
        )
        
        # Warning should contain the correct symbol
        warning = warnings[0]
        assert warning.symbol == sym, (
            f"Warning symbol should be '{sym}', got '{warning.symbol}'"
        )

    @given(
        first_ts=timestamp,
        threshold=gap_threshold,
        extra_time=st.floats(min_value=0.001, max_value=100.0, allow_nan=False, allow_infinity=False),
        sym=symbol,
        exch=exchange,
    )
    @settings(max_examples=100)
    def test_timestamp_gap_warning_contains_duration(
        self,
        first_ts: float,
        threshold: float,
        extra_time: float,
        sym: str,
        exch: str,
    ):
        """Verify timestamp gap warning contains the gap duration (seconds).
        
        When a timestamp gap is detected, the emitted warning event must
        contain the duration as the time difference in seconds.
        
        **Validates: Requirements 4.3**
        """
        config = LiveValidationConfig(
            enabled=True,
            gap_threshold_sec=threshold,
        )
        validator = LiveDataValidator(config=config)
        
        # Record first trade
        validator.record_trade(sym, exch, first_ts)
        
        # Record second trade with a gap
        second_ts = first_ts + threshold + extra_time
        validator.record_trade(sym, exch, second_ts)
        
        # Get emitted warnings
        warnings = validator.get_emitted_warnings()
        
        # Should have exactly one warning
        assert len(warnings) == 1, (
            f"Expected 1 warning, got {len(warnings)}"
        )
        
        # Warning duration should equal the time delta
        warning = warnings[0]
        expected_duration = second_ts - first_ts
        assert abs(warning.duration - expected_duration) < 1e-9, (
            f"Warning duration should be {expected_duration} seconds, got {warning.duration}"
        )

    @given(
        first_ts=timestamp,
        threshold=gap_threshold,
        extra_time=st.floats(min_value=0.001, max_value=100.0, allow_nan=False, allow_infinity=False),
        sym=symbol,
        exch=exchange,
    )
    @settings(max_examples=100)
    def test_timestamp_gap_warning_contains_gap_type(
        self,
        first_ts: float,
        threshold: float,
        extra_time: float,
        sym: str,
        exch: str,
    ):
        """Verify timestamp gap warning contains gap_type="timestamp".
        
        When a timestamp gap is detected, the emitted warning event must
        have gap_type set to "timestamp" to distinguish it from sequence gaps.
        
        **Validates: Requirements 4.3**
        """
        config = LiveValidationConfig(
            enabled=True,
            gap_threshold_sec=threshold,
        )
        validator = LiveDataValidator(config=config)
        
        # Record first trade
        validator.record_trade(sym, exch, first_ts)
        
        # Record second trade with a gap
        second_ts = first_ts + threshold + extra_time
        validator.record_trade(sym, exch, second_ts)
        
        # Get emitted warnings
        warnings = validator.get_emitted_warnings()
        
        # Should have exactly one warning
        assert len(warnings) == 1, (
            f"Expected 1 warning, got {len(warnings)}"
        )
        
        # Warning gap_type should be "timestamp"
        warning = warnings[0]
        assert warning.gap_type == "timestamp", (
            f"Warning gap_type should be 'timestamp', got '{warning.gap_type}'"
        )

    @given(
        first_ts=timestamp,
        threshold=gap_threshold,
        extra_time=st.floats(min_value=0.001, max_value=100.0, allow_nan=False, allow_infinity=False),
        sym=symbol,
        exch=exchange,
    )
    @settings(max_examples=100)
    def test_timestamp_gap_warning_contains_all_required_fields(
        self,
        first_ts: float,
        threshold: float,
        extra_time: float,
        sym: str,
        exch: str,
    ):
        """Verify timestamp gap warning contains all required fields.
        
        When a timestamp gap is detected, the emitted warning event must
        contain: symbol, duration (seconds), and gap_type="timestamp".
        
        **Validates: Requirements 4.3**
        """
        config = LiveValidationConfig(
            enabled=True,
            gap_threshold_sec=threshold,
        )
        validator = LiveDataValidator(config=config)
        
        # Record first trade
        validator.record_trade(sym, exch, first_ts)
        
        # Record second trade with a gap
        second_ts = first_ts + threshold + extra_time
        validator.record_trade(sym, exch, second_ts)
        
        # Get emitted warnings
        warnings = validator.get_emitted_warnings()
        
        # Should have exactly one warning
        assert len(warnings) == 1, (
            f"Expected 1 warning, got {len(warnings)}"
        )
        
        warning = warnings[0]
        expected_duration = second_ts - first_ts
        
        # Verify all required fields are present and correct
        assert warning.symbol == sym, (
            f"Warning symbol should be '{sym}', got '{warning.symbol}'"
        )
        assert warning.exchange == exch, (
            f"Warning exchange should be '{exch}', got '{warning.exchange}'"
        )
        assert warning.gap_type == "timestamp", (
            f"Warning gap_type should be 'timestamp', got '{warning.gap_type}'"
        )
        assert abs(warning.duration - expected_duration) < 1e-9, (
            f"Warning duration should be {expected_duration}, got {warning.duration}"
        )
        assert warning.timestamp == second_ts, (
            f"Warning timestamp should be {second_ts}, got {warning.timestamp}"
        )

    # =========================================================================
    # Combined and Edge Case Tests
    # =========================================================================

    @given(
        first_seq=sequence_number,
        gap=gap_size,
        first_ts=timestamp,
        threshold=gap_threshold,
        extra_time=st.floats(min_value=0.001, max_value=100.0, allow_nan=False, allow_infinity=False),
        sym=symbol,
        exch=exchange,
    )
    @settings(max_examples=100)
    def test_both_gap_types_emit_distinct_warnings(
        self,
        first_seq: int,
        gap: int,
        first_ts: float,
        threshold: float,
        extra_time: float,
        sym: str,
        exch: str,
    ):
        """Verify both sequence and timestamp gaps emit distinct warnings.
        
        When both a sequence gap and a timestamp gap are detected, two
        separate warnings should be emitted with different gap_types.
        
        **Validates: Requirements 4.3**
        """
        config = LiveValidationConfig(
            enabled=True,
            gap_threshold_sec=threshold,
        )
        validator = LiveDataValidator(config=config)
        
        # Create a sequence gap
        validator.record_orderbook_update(sym, exch, first_ts, first_seq)
        second_seq = first_seq + 1 + gap
        validator.record_orderbook_update(sym, exch, first_ts + 1.0, second_seq)
        
        # Create a timestamp gap
        validator.record_trade(sym, exch, first_ts)
        second_ts = first_ts + threshold + extra_time
        validator.record_trade(sym, exch, second_ts)
        
        # Get emitted warnings
        warnings = validator.get_emitted_warnings()
        
        # Should have exactly two warnings
        assert len(warnings) == 2, (
            f"Expected 2 warnings, got {len(warnings)}"
        )
        
        # Extract gap types
        gap_types = {w.gap_type for w in warnings}
        
        # Both gap types should be present
        assert "sequence" in gap_types, (
            f"Expected 'sequence' gap type in warnings, got {gap_types}"
        )
        assert "timestamp" in gap_types, (
            f"Expected 'timestamp' gap type in warnings, got {gap_types}"
        )

    @given(
        first_seq=sequence_number,
        gap=gap_size,
        ts=timestamp,
        sym=symbol,
        exch=exchange,
    )
    @settings(max_examples=100)
    def test_warning_exchange_field_is_correct(
        self,
        first_seq: int,
        gap: int,
        ts: float,
        sym: str,
        exch: str,
    ):
        """Verify gap warning contains the correct exchange.
        
        The emitted warning event must contain the exchange where
        the gap was detected.
        
        **Validates: Requirements 4.3**
        """
        config = LiveValidationConfig(enabled=True)
        validator = LiveDataValidator(config=config)
        
        # Record orderbook updates with a gap
        validator.record_orderbook_update(sym, exch, ts, first_seq)
        second_seq = first_seq + 1 + gap
        validator.record_orderbook_update(sym, exch, ts + 1.0, second_seq)
        
        # Get emitted warnings
        warnings = validator.get_emitted_warnings()
        
        # Should have exactly one warning
        assert len(warnings) == 1, (
            f"Expected 1 warning, got {len(warnings)}"
        )
        
        # Warning should contain the correct exchange
        warning = warnings[0]
        assert warning.exchange == exch, (
            f"Warning exchange should be '{exch}', got '{warning.exchange}'"
        )

    @given(
        first_seq=sequence_number,
        num_gaps=st.integers(min_value=1, max_value=5),
        ts=timestamp,
        sym=symbol,
        exch=exchange,
    )
    @settings(max_examples=100)
    def test_multiple_sequence_gaps_emit_multiple_warnings(
        self,
        first_seq: int,
        num_gaps: int,
        ts: float,
        sym: str,
        exch: str,
    ):
        """Verify multiple sequence gaps emit multiple warnings.
        
        When multiple sequence gaps are detected, a warning should be
        emitted for each gap, and each warning should contain the
        correct symbol, duration, and gap_type.
        
        **Validates: Requirements 4.3**
        """
        config = LiveValidationConfig(enabled=True)
        validator = LiveDataValidator(config=config)
        
        current_seq = first_seq
        current_ts = ts
        
        # Record first update
        validator.record_orderbook_update(sym, exch, current_ts, current_seq)
        
        # Create multiple gaps
        for i in range(num_gaps):
            # Skip some sequences to create a gap
            gap_size_val = i + 1  # Gap sizes: 1, 2, 3, ...
            current_seq = current_seq + 1 + gap_size_val
            current_ts = current_ts + 1.0
            validator.record_orderbook_update(sym, exch, current_ts, current_seq)
        
        # Get emitted warnings
        warnings = validator.get_emitted_warnings()
        
        # Should have num_gaps warnings
        assert len(warnings) == num_gaps, (
            f"Expected {num_gaps} warnings, got {len(warnings)}"
        )
        
        # All warnings should have correct symbol and gap_type
        for warning in warnings:
            assert warning.symbol == sym, (
                f"Warning symbol should be '{sym}', got '{warning.symbol}'"
            )
            assert warning.gap_type == "sequence", (
                f"Warning gap_type should be 'sequence', got '{warning.gap_type}'"
            )
            assert warning.duration > 0, (
                f"Warning duration should be positive, got {warning.duration}"
            )

    @given(
        first_ts=timestamp,
        threshold=gap_threshold,
        num_gaps=st.integers(min_value=1, max_value=5),
        sym=symbol,
        exch=exchange,
    )
    @settings(max_examples=100)
    def test_multiple_timestamp_gaps_emit_multiple_warnings(
        self,
        first_ts: float,
        threshold: float,
        num_gaps: int,
        sym: str,
        exch: str,
    ):
        """Verify multiple timestamp gaps emit multiple warnings.
        
        When multiple timestamp gaps are detected, a warning should be
        emitted for each gap, and each warning should contain the
        correct symbol, duration, and gap_type.
        
        **Validates: Requirements 4.3**
        """
        config = LiveValidationConfig(
            enabled=True,
            gap_threshold_sec=threshold,
        )
        validator = LiveDataValidator(config=config)
        
        current_ts = first_ts
        
        # Record first trade
        validator.record_trade(sym, exch, current_ts)
        
        # Create multiple gaps
        for i in range(num_gaps):
            # Move time forward by more than threshold
            current_ts = current_ts + threshold + 1.0
            validator.record_trade(sym, exch, current_ts)
        
        # Get emitted warnings
        warnings = validator.get_emitted_warnings()
        
        # Should have num_gaps warnings
        assert len(warnings) == num_gaps, (
            f"Expected {num_gaps} warnings, got {len(warnings)}"
        )
        
        # All warnings should have correct symbol and gap_type
        for warning in warnings:
            assert warning.symbol == sym, (
                f"Warning symbol should be '{sym}', got '{warning.symbol}'"
            )
            assert warning.gap_type == "timestamp", (
                f"Warning gap_type should be 'timestamp', got '{warning.gap_type}'"
            )
            assert warning.duration > threshold, (
                f"Warning duration should be > {threshold}, got {warning.duration}"
            )

    @given(
        first_seq=sequence_number,
        gap=gap_size,
        ts=timestamp,
        sym=symbol,
        exch=exchange,
    )
    @settings(max_examples=100)
    def test_no_warning_when_no_gap(
        self,
        first_seq: int,
        gap: int,
        ts: float,
        sym: str,
        exch: str,
    ):
        """Verify no warning is emitted when there is no gap.
        
        When sequence numbers are consecutive (no gap), no warning
        should be emitted.
        
        **Validates: Requirements 4.3**
        """
        config = LiveValidationConfig(enabled=True)
        validator = LiveDataValidator(config=config)
        
        # Record consecutive orderbook updates (no gap)
        validator.record_orderbook_update(sym, exch, ts, first_seq)
        validator.record_orderbook_update(sym, exch, ts + 1.0, first_seq + 1)
        validator.record_orderbook_update(sym, exch, ts + 2.0, first_seq + 2)
        
        # Get emitted warnings
        warnings = validator.get_emitted_warnings()
        
        # Should have no warnings
        assert len(warnings) == 0, (
            f"Expected 0 warnings for consecutive sequences, got {len(warnings)}"
        )

    @given(
        first_ts=timestamp,
        threshold=gap_threshold,
        sym=symbol,
        exch=exchange,
    )
    @settings(max_examples=100)
    def test_no_warning_when_time_below_threshold(
        self,
        first_ts: float,
        threshold: float,
        sym: str,
        exch: str,
    ):
        """Verify no warning is emitted when time is below threshold.
        
        When the time between trades is less than the threshold, no
        warning should be emitted.
        
        **Validates: Requirements 4.3**
        """
        config = LiveValidationConfig(
            enabled=True,
            gap_threshold_sec=threshold,
        )
        validator = LiveDataValidator(config=config)
        
        # Record trades with time below threshold
        validator.record_trade(sym, exch, first_ts)
        validator.record_trade(sym, exch, first_ts + threshold * 0.5)
        validator.record_trade(sym, exch, first_ts + threshold * 0.9)
        
        # Get emitted warnings
        warnings = validator.get_emitted_warnings()
        
        # Should have no warnings
        assert len(warnings) == 0, (
            f"Expected 0 warnings when time < threshold, got {len(warnings)}"
        )

    @given(
        first_seq=sequence_number,
        gap=gap_size,
        ts=timestamp,
        sym=symbol,
        exch=exchange,
    )
    @settings(max_examples=100)
    def test_warning_is_gap_warning_type(
        self,
        first_seq: int,
        gap: int,
        ts: float,
        sym: str,
        exch: str,
    ):
        """Verify emitted warning is of type GapWarning.
        
        The emitted warning should be an instance of the GapWarning
        dataclass with all required attributes.
        
        **Validates: Requirements 4.3**
        """
        config = LiveValidationConfig(enabled=True)
        validator = LiveDataValidator(config=config)
        
        # Record orderbook updates with a gap
        validator.record_orderbook_update(sym, exch, ts, first_seq)
        second_seq = first_seq + 1 + gap
        validator.record_orderbook_update(sym, exch, ts + 1.0, second_seq)
        
        # Get emitted warnings
        warnings = validator.get_emitted_warnings()
        
        # Should have exactly one warning
        assert len(warnings) == 1, (
            f"Expected 1 warning, got {len(warnings)}"
        )
        
        # Warning should be a GapWarning instance
        warning = warnings[0]
        assert isinstance(warning, GapWarning), (
            f"Warning should be GapWarning instance, got {type(warning)}"
        )
        
        # Verify all required attributes exist
        assert hasattr(warning, 'symbol'), "Warning should have 'symbol' attribute"
        assert hasattr(warning, 'exchange'), "Warning should have 'exchange' attribute"
        assert hasattr(warning, 'gap_type'), "Warning should have 'gap_type' attribute"
        assert hasattr(warning, 'duration'), "Warning should have 'duration' attribute"
        assert hasattr(warning, 'timestamp'), "Warning should have 'timestamp' attribute"

    @given(
        first_seq=sequence_number,
        gap=gap_size,
        ts=timestamp,
        sym=symbol,
        exch=exchange,
    )
    @settings(max_examples=100)
    def test_clear_warnings_removes_all_warnings(
        self,
        first_seq: int,
        gap: int,
        ts: float,
        sym: str,
        exch: str,
    ):
        """Verify clear_warnings removes all emitted warnings.
        
        After calling clear_warnings, the list of emitted warnings
        should be empty.
        
        **Validates: Requirements 4.3**
        """
        config = LiveValidationConfig(enabled=True)
        validator = LiveDataValidator(config=config)
        
        # Record orderbook updates with a gap
        validator.record_orderbook_update(sym, exch, ts, first_seq)
        second_seq = first_seq + 1 + gap
        validator.record_orderbook_update(sym, exch, ts + 1.0, second_seq)
        
        # Verify warning was emitted
        warnings = validator.get_emitted_warnings()
        assert len(warnings) == 1, (
            f"Expected 1 warning before clear, got {len(warnings)}"
        )
        
        # Clear warnings
        validator.clear_warnings()
        
        # Verify warnings are cleared
        warnings = validator.get_emitted_warnings()
        assert len(warnings) == 0, (
            f"Expected 0 warnings after clear, got {len(warnings)}"
        )

    @given(
        first_seq=sequence_number,
        gap=gap_size,
        ts=timestamp,
        sym1=symbol,
        sym2=symbol,
        exch=exchange,
    )
    @settings(max_examples=100)
    def test_get_warnings_for_symbol_filters_correctly(
        self,
        first_seq: int,
        gap: int,
        ts: float,
        sym1: str,
        sym2: str,
        exch: str,
    ):
        """Verify get_warnings_for_symbol filters warnings correctly.
        
        When multiple symbols have gaps, get_warnings_for_symbol should
        return only the warnings for the specified symbol.
        
        **Validates: Requirements 4.3**
        """
        # Ensure we have two different symbols
        assume(sym1 != sym2)
        
        config = LiveValidationConfig(enabled=True)
        validator = LiveDataValidator(config=config)
        
        # Create gaps for both symbols
        validator.record_orderbook_update(sym1, exch, ts, first_seq)
        validator.record_orderbook_update(sym1, exch, ts + 1.0, first_seq + 1 + gap)
        
        validator.record_orderbook_update(sym2, exch, ts, first_seq)
        validator.record_orderbook_update(sym2, exch, ts + 1.0, first_seq + 1 + gap)
        
        # Get all warnings
        all_warnings = validator.get_emitted_warnings()
        assert len(all_warnings) == 2, (
            f"Expected 2 total warnings, got {len(all_warnings)}"
        )
        
        # Get warnings for sym1 only
        sym1_warnings = validator.get_warnings_for_symbol(sym1, exch)
        assert len(sym1_warnings) == 1, (
            f"Expected 1 warning for {sym1}, got {len(sym1_warnings)}"
        )
        assert sym1_warnings[0].symbol == sym1, (
            f"Warning symbol should be '{sym1}', got '{sym1_warnings[0].symbol}'"
        )
        
        # Get warnings for sym2 only
        sym2_warnings = validator.get_warnings_for_symbol(sym2, exch)
        assert len(sym2_warnings) == 1, (
            f"Expected 1 warning for {sym2}, got {len(sym2_warnings)}"
        )
        assert sym2_warnings[0].symbol == sym2, (
            f"Warning symbol should be '{sym2}', got '{sym2_warnings[0].symbol}'"
        )

    @given(
        first_seq=sequence_number,
        gap=gap_size,
        ts=timestamp,
        sym=symbol,
        exch=exchange,
    )
    @settings(max_examples=100)
    def test_warning_duration_is_positive(
        self,
        first_seq: int,
        gap: int,
        ts: float,
        sym: str,
        exch: str,
    ):
        """Verify warning duration is always positive.
        
        The duration field in a gap warning should always be a positive
        number representing the gap size.
        
        **Validates: Requirements 4.3**
        """
        config = LiveValidationConfig(enabled=True)
        validator = LiveDataValidator(config=config)
        
        # Record orderbook updates with a gap
        validator.record_orderbook_update(sym, exch, ts, first_seq)
        second_seq = first_seq + 1 + gap
        validator.record_orderbook_update(sym, exch, ts + 1.0, second_seq)
        
        # Get emitted warnings
        warnings = validator.get_emitted_warnings()
        
        # Should have exactly one warning
        assert len(warnings) == 1, (
            f"Expected 1 warning, got {len(warnings)}"
        )
        
        # Duration should be positive
        warning = warnings[0]
        assert warning.duration > 0, (
            f"Warning duration should be positive, got {warning.duration}"
        )
