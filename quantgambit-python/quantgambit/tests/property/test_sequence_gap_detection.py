"""Property-based tests for sequence gap detection.

Feature: live-orderbook-data-storage, Property 8: Sequence Gap Detection

Tests that for any sequence of orderbook updates with sequence numbers,
if actual_seq > expected_seq + 1, the LiveDataValidator SHALL detect a gap
of size (actual_seq - expected_seq - 1).

**Validates: Requirements 4.1**
"""

from __future__ import annotations

from typing import Optional

import pytest
from hypothesis import given, strategies as st, settings, assume

from quantgambit.storage.live_data_validator import LiveDataValidator
from quantgambit.storage.persistence import LiveValidationConfig


# =============================================================================
# Strategies for generating test data
# =============================================================================

# Sequence number generator (positive integers)
sequence_number = st.integers(min_value=1, max_value=1_000_000)

# Gap size generator (positive integers representing missed sequences)
gap_size = st.integers(min_value=1, max_value=10_000)

# Symbol generator
symbol = st.sampled_from(["BTC/USDT", "ETH/USDT", "SOL/USDT", "DOGE/USDT", "XRP/USDT"])

# Exchange generator
exchange = st.sampled_from(["binance", "coinbase", "kraken", "okx", "bybit"])


# =============================================================================
# Property 8: Sequence Gap Detection
# =============================================================================

class TestSequenceGapDetection:
    """Property 8: Sequence Gap Detection
    
    For any sequence of orderbook updates with sequence numbers, if
    actual_seq > expected_seq + 1, the LiveDataValidator SHALL detect
    a gap of size (actual_seq - expected_seq - 1).
    
    **Validates: Requirements 4.1**
    """

    @given(
        expected_seq=sequence_number,
        gap=gap_size,
        sym=symbol,
    )
    @settings(max_examples=100)
    def test_gap_detected_when_actual_exceeds_expected_plus_one(
        self,
        expected_seq: int,
        gap: int,
        sym: str,
    ):
        """Verify that a gap is detected when actual_seq > expected_seq + 1.
        
        When the actual sequence number is greater than expected_seq + 1,
        the detect_orderbook_gap method should return the gap size.
        
        **Validates: Requirements 4.1**
        """
        validator = LiveDataValidator()
        
        # Calculate actual_seq to create a gap
        # actual_seq = expected_seq + 1 + gap
        # This ensures actual_seq > expected_seq + 1
        actual_seq = expected_seq + 1 + gap
        
        # Detect the gap
        detected_gap = validator.detect_orderbook_gap(sym, expected_seq, actual_seq)
        
        # Gap should be detected
        assert detected_gap is not None, (
            f"Gap should be detected when actual_seq > expected_seq + 1. "
            f"expected_seq={expected_seq}, actual_seq={actual_seq}"
        )
        
        # Gap size should equal (actual_seq - expected_seq - 1)
        expected_gap_size = actual_seq - expected_seq - 1
        assert detected_gap == expected_gap_size, (
            f"Gap size should equal (actual_seq - expected_seq - 1). "
            f"Expected gap: {expected_gap_size}, Detected gap: {detected_gap}"
        )
        
        # Also verify the gap equals the input gap
        assert detected_gap == gap, (
            f"Detected gap should equal the input gap. "
            f"Input gap: {gap}, Detected gap: {detected_gap}"
        )

    @given(
        expected_seq=sequence_number,
        gap=gap_size,
        sym=symbol,
    )
    @settings(max_examples=100)
    def test_gap_size_equals_formula(
        self,
        expected_seq: int,
        gap: int,
        sym: str,
    ):
        """Verify that gap size equals (actual_seq - expected_seq - 1).
        
        The gap size formula should correctly calculate the number of
        missed sequence numbers.
        
        **Validates: Requirements 4.1**
        """
        validator = LiveDataValidator()
        
        # Create a gap scenario
        actual_seq = expected_seq + 1 + gap
        
        # Detect the gap
        detected_gap = validator.detect_orderbook_gap(sym, expected_seq, actual_seq)
        
        # Verify the formula
        assert detected_gap == (actual_seq - expected_seq - 1), (
            f"Gap size formula: (actual_seq - expected_seq - 1) = "
            f"({actual_seq} - {expected_seq} - 1) = {actual_seq - expected_seq - 1}. "
            f"Detected: {detected_gap}"
        )

    @given(
        expected_seq=sequence_number,
        sym=symbol,
    )
    @settings(max_examples=100)
    def test_no_gap_when_actual_equals_expected_plus_one(
        self,
        expected_seq: int,
        sym: str,
    ):
        """Verify no gap is detected when actual_seq == expected_seq + 1.
        
        When the actual sequence number is exactly expected_seq + 1,
        this is the normal case with no gap, and None should be returned.
        
        **Validates: Requirements 4.1**
        """
        validator = LiveDataValidator()
        
        # Normal case: actual_seq = expected_seq + 1 (no gap)
        actual_seq = expected_seq + 1
        
        # Detect the gap
        detected_gap = validator.detect_orderbook_gap(sym, expected_seq, actual_seq)
        
        # No gap should be detected
        assert detected_gap is None, (
            f"No gap should be detected when actual_seq == expected_seq + 1. "
            f"expected_seq={expected_seq}, actual_seq={actual_seq}, "
            f"detected_gap={detected_gap}"
        )

    @given(
        expected_seq=sequence_number,
        sym=symbol,
    )
    @settings(max_examples=100)
    def test_no_gap_when_actual_equals_expected(
        self,
        expected_seq: int,
        sym: str,
    ):
        """Verify no gap is detected when actual_seq == expected_seq.
        
        When the actual sequence number equals expected_seq (duplicate or
        same sequence), no gap should be detected.
        
        **Validates: Requirements 4.1**
        """
        validator = LiveDataValidator()
        
        # Duplicate case: actual_seq = expected_seq
        actual_seq = expected_seq
        
        # Detect the gap
        detected_gap = validator.detect_orderbook_gap(sym, expected_seq, actual_seq)
        
        # No gap should be detected
        assert detected_gap is None, (
            f"No gap should be detected when actual_seq == expected_seq. "
            f"expected_seq={expected_seq}, actual_seq={actual_seq}, "
            f"detected_gap={detected_gap}"
        )

    @given(
        expected_seq=st.integers(min_value=2, max_value=1_000_000),
        decrement=st.integers(min_value=1, max_value=100),
        sym=symbol,
    )
    @settings(max_examples=100)
    def test_no_gap_when_actual_less_than_expected(
        self,
        expected_seq: int,
        decrement: int,
        sym: str,
    ):
        """Verify no gap is detected when actual_seq < expected_seq.
        
        When the actual sequence number is less than expected_seq (out of
        order or old message), no gap should be detected.
        
        **Validates: Requirements 4.1**
        """
        # Ensure actual_seq is positive
        assume(expected_seq > decrement)
        
        validator = LiveDataValidator()
        
        # Out of order case: actual_seq < expected_seq
        actual_seq = expected_seq - decrement
        
        # Detect the gap
        detected_gap = validator.detect_orderbook_gap(sym, expected_seq, actual_seq)
        
        # No gap should be detected
        assert detected_gap is None, (
            f"No gap should be detected when actual_seq < expected_seq. "
            f"expected_seq={expected_seq}, actual_seq={actual_seq}, "
            f"detected_gap={detected_gap}"
        )

    @given(
        expected_seq=sequence_number,
        sym=symbol,
    )
    @settings(max_examples=100)
    def test_gap_of_one_detected_correctly(
        self,
        expected_seq: int,
        sym: str,
    ):
        """Verify that a gap of exactly 1 is detected correctly.
        
        When actual_seq = expected_seq + 2, exactly one sequence was missed,
        so the gap size should be 1.
        
        **Validates: Requirements 4.1**
        """
        validator = LiveDataValidator()
        
        # Gap of 1: actual_seq = expected_seq + 2
        # Missed: expected_seq + 1
        actual_seq = expected_seq + 2
        
        # Detect the gap
        detected_gap = validator.detect_orderbook_gap(sym, expected_seq, actual_seq)
        
        # Gap should be 1
        assert detected_gap == 1, (
            f"Gap of 1 should be detected when actual_seq = expected_seq + 2. "
            f"expected_seq={expected_seq}, actual_seq={actual_seq}, "
            f"detected_gap={detected_gap}"
        )

    @given(
        expected_seq=sequence_number,
        gap=gap_size,
        sym=symbol,
        exch=exchange,
    )
    @settings(max_examples=100)
    def test_gap_detection_independent_of_symbol_exchange(
        self,
        expected_seq: int,
        gap: int,
        sym: str,
        exch: str,
    ):
        """Verify gap detection works consistently across symbols/exchanges.
        
        The gap detection logic should work the same regardless of which
        symbol or exchange is being tracked.
        
        **Validates: Requirements 4.1**
        """
        validator = LiveDataValidator()
        
        actual_seq = expected_seq + 1 + gap
        
        # Detect gap for this symbol
        detected_gap = validator.detect_orderbook_gap(sym, expected_seq, actual_seq)
        
        # Gap should be detected correctly
        assert detected_gap == gap, (
            f"Gap detection should work for any symbol/exchange. "
            f"symbol={sym}, exchange={exch}, "
            f"expected_seq={expected_seq}, actual_seq={actual_seq}, "
            f"expected_gap={gap}, detected_gap={detected_gap}"
        )

    @given(
        expected_seq=sequence_number,
        sym=symbol,
    )
    @settings(max_examples=100)
    def test_boundary_no_gap_at_expected_plus_one(
        self,
        expected_seq: int,
        sym: str,
    ):
        """Verify boundary condition: actual_seq = expected_seq + 1 is not a gap.
        
        This is the boundary between gap and no-gap. When actual_seq equals
        expected_seq + 1, there is no gap (this is the expected next sequence).
        
        **Validates: Requirements 4.1**
        """
        validator = LiveDataValidator()
        
        # Boundary: actual_seq = expected_seq + 1 (no gap)
        actual_seq = expected_seq + 1
        
        detected_gap = validator.detect_orderbook_gap(sym, expected_seq, actual_seq)
        
        assert detected_gap is None, (
            f"Boundary condition: actual_seq = expected_seq + 1 should NOT be a gap. "
            f"expected_seq={expected_seq}, actual_seq={actual_seq}"
        )

    @given(
        expected_seq=sequence_number,
        sym=symbol,
    )
    @settings(max_examples=100)
    def test_boundary_gap_at_expected_plus_two(
        self,
        expected_seq: int,
        sym: str,
    ):
        """Verify boundary condition: actual_seq = expected_seq + 2 is a gap of 1.
        
        This is the boundary where a gap starts. When actual_seq equals
        expected_seq + 2, there is a gap of exactly 1.
        
        **Validates: Requirements 4.1**
        """
        validator = LiveDataValidator()
        
        # Boundary: actual_seq = expected_seq + 2 (gap of 1)
        actual_seq = expected_seq + 2
        
        detected_gap = validator.detect_orderbook_gap(sym, expected_seq, actual_seq)
        
        assert detected_gap == 1, (
            f"Boundary condition: actual_seq = expected_seq + 2 should be a gap of 1. "
            f"expected_seq={expected_seq}, actual_seq={actual_seq}, "
            f"detected_gap={detected_gap}"
        )

    @given(
        expected_seq=sequence_number,
        gap=gap_size,
        sym=symbol,
    )
    @settings(max_examples=100)
    def test_gap_size_is_positive_when_gap_exists(
        self,
        expected_seq: int,
        gap: int,
        sym: str,
    ):
        """Verify that detected gap size is always positive when a gap exists.
        
        When a gap is detected, the gap size should always be a positive
        integer representing the number of missed sequences.
        
        **Validates: Requirements 4.1**
        """
        validator = LiveDataValidator()
        
        actual_seq = expected_seq + 1 + gap
        
        detected_gap = validator.detect_orderbook_gap(sym, expected_seq, actual_seq)
        
        assert detected_gap is not None, "Gap should be detected"
        assert detected_gap > 0, (
            f"Gap size should be positive. "
            f"expected_seq={expected_seq}, actual_seq={actual_seq}, "
            f"detected_gap={detected_gap}"
        )

    @given(
        expected_seq=sequence_number,
        gap=gap_size,
        sym=symbol,
    )
    @settings(max_examples=100)
    def test_gap_size_is_integer(
        self,
        expected_seq: int,
        gap: int,
        sym: str,
    ):
        """Verify that detected gap size is an integer.
        
        The gap size should always be an integer since it represents
        the count of missed sequence numbers.
        
        **Validates: Requirements 4.1**
        """
        validator = LiveDataValidator()
        
        actual_seq = expected_seq + 1 + gap
        
        detected_gap = validator.detect_orderbook_gap(sym, expected_seq, actual_seq)
        
        assert detected_gap is not None, "Gap should be detected"
        assert isinstance(detected_gap, int), (
            f"Gap size should be an integer. "
            f"Type: {type(detected_gap)}, Value: {detected_gap}"
        )

    @given(
        expected_seq=sequence_number,
        gap=gap_size,
    )
    @settings(max_examples=100)
    def test_gap_detection_is_pure_function(
        self,
        expected_seq: int,
        gap: int,
    ):
        """Verify that gap detection is a pure function (same inputs = same outputs).
        
        Calling detect_orderbook_gap with the same inputs should always
        return the same result, regardless of validator state.
        
        **Validates: Requirements 4.1**
        """
        validator1 = LiveDataValidator()
        validator2 = LiveDataValidator()
        
        actual_seq = expected_seq + 1 + gap
        
        # Call on two different validator instances
        result1 = validator1.detect_orderbook_gap("BTC/USDT", expected_seq, actual_seq)
        result2 = validator2.detect_orderbook_gap("BTC/USDT", expected_seq, actual_seq)
        
        assert result1 == result2, (
            f"Gap detection should be a pure function. "
            f"Result1: {result1}, Result2: {result2}"
        )
        
        # Call multiple times on the same validator
        result3 = validator1.detect_orderbook_gap("BTC/USDT", expected_seq, actual_seq)
        
        assert result1 == result3, (
            f"Gap detection should return same result on repeated calls. "
            f"Result1: {result1}, Result3: {result3}"
        )
