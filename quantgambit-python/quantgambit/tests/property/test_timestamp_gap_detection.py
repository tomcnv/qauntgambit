"""Property-based tests for timestamp gap detection.

Feature: live-orderbook-data-storage, Property 9: Timestamp Gap Detection

Tests that for any sequence of trades with timestamps, if the time between
consecutive trades exceeds the configured gap_threshold_sec, the LiveDataValidator
SHALL detect a gap with duration equal to the time difference.

**Validates: Requirements 4.2**
"""

from __future__ import annotations

import pytest
from hypothesis import given, strategies as st, settings, assume

from quantgambit.storage.live_data_validator import LiveDataValidator
from quantgambit.storage.persistence import LiveValidationConfig


# =============================================================================
# Strategies for generating test data
# =============================================================================

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
# Property 9: Timestamp Gap Detection
# =============================================================================

class TestTimestampGapDetection:
    """Property 9: Timestamp Gap Detection
    
    For any sequence of trades with timestamps, if the time between
    consecutive trades exceeds the configured gap_threshold_sec, the
    LiveDataValidator SHALL detect a gap with duration equal to the
    time difference.
    
    **Validates: Requirements 4.2**
    """

    @given(
        first_ts=timestamp,
        threshold=gap_threshold,
        extra_time=st.floats(min_value=0.001, max_value=100.0, allow_nan=False, allow_infinity=False),
        sym=symbol,
        exch=exchange,
    )
    @settings(max_examples=100)
    def test_gap_detected_when_time_exceeds_threshold(
        self,
        first_ts: float,
        threshold: float,
        extra_time: float,
        sym: str,
        exch: str,
    ):
        """Verify that a gap is detected when time between trades > threshold.
        
        When the time between consecutive trades exceeds the configured
        gap_threshold_sec, the validator should detect and count the gap.
        
        **Validates: Requirements 4.2**
        """
        config = LiveValidationConfig(
            enabled=True,
            gap_threshold_sec=threshold,
        )
        validator = LiveDataValidator(config=config)
        
        # Record first trade
        validator.record_trade(sym, exch, first_ts)
        
        # Calculate second timestamp that exceeds threshold
        # second_ts = first_ts + threshold + extra_time (guaranteed to exceed threshold)
        second_ts = first_ts + threshold + extra_time
        
        # Record second trade (should detect gap)
        validator.record_trade(sym, exch, second_ts)
        
        # Gap should be detected
        gap_count = validator.get_trade_gap_count(sym, exch)
        assert gap_count == 1, (
            f"Gap should be detected when time delta > threshold. "
            f"first_ts={first_ts}, second_ts={second_ts}, "
            f"time_delta={second_ts - first_ts}, threshold={threshold}, "
            f"gap_count={gap_count}"
        )

    @given(
        threshold=gap_threshold,
        sym=symbol,
        exch=exchange,
    )
    @settings(max_examples=100)
    def test_no_gap_when_time_equals_threshold(
        self,
        threshold: float,
        sym: str,
        exch: str,
    ):
        """Verify no gap is detected when time between trades == threshold.
        
        When the time between consecutive trades equals exactly the
        gap_threshold_sec, no gap should be detected (boundary condition).
        
        Note: We use integer timestamps to avoid floating-point precision
        issues that can cause the time delta to be slightly different from
        the threshold.
        
        **Validates: Requirements 4.2**
        """
        config = LiveValidationConfig(
            enabled=True,
            gap_threshold_sec=threshold,
        )
        validator = LiveDataValidator(config=config)
        
        # Use a fixed integer timestamp to avoid floating-point precision issues
        first_ts = 1600000000.0
        
        # Record first trade
        validator.record_trade(sym, exch, first_ts)
        
        # Calculate second timestamp that equals threshold exactly
        # The time_delta will be exactly threshold
        second_ts = first_ts + threshold
        
        # Compute the actual time delta to verify
        actual_time_delta = second_ts - first_ts
        
        # Record second trade (should NOT detect gap since time_delta == threshold, not > threshold)
        validator.record_trade(sym, exch, second_ts)
        
        # No gap should be detected (gap is only when time_delta > threshold)
        gap_count = validator.get_trade_gap_count(sym, exch)
        
        # Due to floating-point precision, actual_time_delta may be slightly different
        # from threshold. The implementation uses strict > comparison, so we need to
        # check if the actual comparison would detect a gap.
        # If actual_time_delta > threshold (due to FP precision), a gap is expected.
        if actual_time_delta > threshold:
            # Floating-point precision caused time_delta to exceed threshold
            assert gap_count == 1, (
                f"Gap should be detected due to floating-point precision. "
                f"actual_time_delta={actual_time_delta}, threshold={threshold}, "
                f"gap_count={gap_count}"
            )
        else:
            # No gap should be detected
            assert gap_count == 0, (
                f"No gap should be detected when time delta <= threshold. "
                f"actual_time_delta={actual_time_delta}, threshold={threshold}, "
                f"gap_count={gap_count}"
            )

    @given(
        first_ts=timestamp,
        threshold=gap_threshold,
        fraction=st.floats(min_value=0.01, max_value=0.99, allow_nan=False, allow_infinity=False),
        sym=symbol,
        exch=exchange,
    )
    @settings(max_examples=100)
    def test_no_gap_when_time_less_than_threshold(
        self,
        first_ts: float,
        threshold: float,
        fraction: float,
        sym: str,
        exch: str,
    ):
        """Verify no gap is detected when time between trades < threshold.
        
        When the time between consecutive trades is less than the
        gap_threshold_sec, no gap should be detected.
        
        **Validates: Requirements 4.2**
        """
        config = LiveValidationConfig(
            enabled=True,
            gap_threshold_sec=threshold,
        )
        validator = LiveDataValidator(config=config)
        
        # Record first trade
        validator.record_trade(sym, exch, first_ts)
        
        # Calculate second timestamp that is less than threshold
        time_delta_val = threshold * fraction  # fraction of threshold
        second_ts = first_ts + time_delta_val
        
        # Record second trade (should NOT detect gap)
        validator.record_trade(sym, exch, second_ts)
        
        # No gap should be detected
        gap_count = validator.get_trade_gap_count(sym, exch)
        assert gap_count == 0, (
            f"No gap should be detected when time delta < threshold. "
            f"first_ts={first_ts}, second_ts={second_ts}, "
            f"time_delta={time_delta_val}, threshold={threshold}, "
            f"gap_count={gap_count}"
        )

    @given(
        first_ts=timestamp,
        threshold=gap_threshold,
        num_gaps=st.integers(min_value=1, max_value=10),
        extra_time=st.floats(min_value=0.001, max_value=10.0, allow_nan=False, allow_infinity=False),
        sym=symbol,
        exch=exchange,
    )
    @settings(max_examples=100)
    def test_gap_count_incremented_correctly(
        self,
        first_ts: float,
        threshold: float,
        num_gaps: int,
        extra_time: float,
        sym: str,
        exch: str,
    ):
        """Verify that gap count is incremented correctly for multiple gaps.
        
        When multiple gaps occur (time between trades > threshold multiple
        times), the gap count should be incremented for each gap.
        
        **Validates: Requirements 4.2**
        """
        config = LiveValidationConfig(
            enabled=True,
            gap_threshold_sec=threshold,
        )
        validator = LiveDataValidator(config=config)
        
        current_ts = first_ts
        
        # Record first trade
        validator.record_trade(sym, exch, current_ts)
        
        # Create num_gaps gaps by recording trades with time > threshold
        for i in range(num_gaps):
            # Move time forward by more than threshold
            current_ts = current_ts + threshold + extra_time
            validator.record_trade(sym, exch, current_ts)
        
        # Gap count should equal num_gaps
        gap_count = validator.get_trade_gap_count(sym, exch)
        assert gap_count == num_gaps, (
            f"Gap count should equal number of gaps created. "
            f"Expected: {num_gaps}, Actual: {gap_count}"
        )

    @given(
        first_ts=timestamp,
        threshold=gap_threshold,
        sym=symbol,
        exch=exchange,
    )
    @settings(max_examples=100)
    def test_first_trade_does_not_create_gap(
        self,
        first_ts: float,
        threshold: float,
        sym: str,
        exch: str,
    ):
        """Verify that the first trade does not create a gap.
        
        When recording the first trade for a symbol, there is no previous
        trade to compare against, so no gap should be detected.
        
        **Validates: Requirements 4.2**
        """
        config = LiveValidationConfig(
            enabled=True,
            gap_threshold_sec=threshold,
        )
        validator = LiveDataValidator(config=config)
        
        # Record first trade
        validator.record_trade(sym, exch, first_ts)
        
        # No gap should be detected for first trade
        gap_count = validator.get_trade_gap_count(sym, exch)
        assert gap_count == 0, (
            f"First trade should not create a gap. "
            f"gap_count={gap_count}"
        )

    @given(
        first_ts=timestamp,
        threshold=gap_threshold,
        extra_time=st.floats(min_value=0.001, max_value=100.0, allow_nan=False, allow_infinity=False),
        sym=symbol,
        exch=exchange,
    )
    @settings(max_examples=100)
    def test_last_trade_timestamp_updated(
        self,
        first_ts: float,
        threshold: float,
        extra_time: float,
        sym: str,
        exch: str,
    ):
        """Verify that last trade timestamp is updated after each trade.
        
        After recording a trade, the validator should update the last
        trade timestamp for that symbol/exchange pair.
        
        **Validates: Requirements 4.2**
        """
        config = LiveValidationConfig(
            enabled=True,
            gap_threshold_sec=threshold,
        )
        validator = LiveDataValidator(config=config)
        
        # Record first trade
        validator.record_trade(sym, exch, first_ts)
        
        # Verify last trade timestamp is updated
        last_ts = validator.get_last_trade_ts(sym, exch)
        assert last_ts == first_ts, (
            f"Last trade timestamp should be updated after first trade. "
            f"Expected: {first_ts}, Actual: {last_ts}"
        )
        
        # Record second trade
        second_ts = first_ts + threshold + extra_time
        validator.record_trade(sym, exch, second_ts)
        
        # Verify last trade timestamp is updated again
        last_ts = validator.get_last_trade_ts(sym, exch)
        assert last_ts == second_ts, (
            f"Last trade timestamp should be updated after second trade. "
            f"Expected: {second_ts}, Actual: {last_ts}"
        )

    @given(
        first_ts=timestamp,
        threshold=gap_threshold,
        extra_time=st.floats(min_value=0.001, max_value=100.0, allow_nan=False, allow_infinity=False),
        sym1=symbol,
        sym2=symbol,
        exch=exchange,
    )
    @settings(max_examples=100)
    def test_gap_detection_independent_per_symbol(
        self,
        first_ts: float,
        threshold: float,
        extra_time: float,
        sym1: str,
        sym2: str,
        exch: str,
    ):
        """Verify that gap detection is independent per symbol.
        
        Gaps should be tracked separately for each symbol. A gap in one
        symbol should not affect the gap count for another symbol.
        
        **Validates: Requirements 4.2**
        """
        # Ensure we have two different symbols
        assume(sym1 != sym2)
        
        config = LiveValidationConfig(
            enabled=True,
            gap_threshold_sec=threshold,
        )
        validator = LiveDataValidator(config=config)
        
        # Record trades for sym1 with a gap
        validator.record_trade(sym1, exch, first_ts)
        validator.record_trade(sym1, exch, first_ts + threshold + extra_time)
        
        # Record trades for sym2 without a gap
        validator.record_trade(sym2, exch, first_ts)
        validator.record_trade(sym2, exch, first_ts + threshold * 0.5)  # Less than threshold
        
        # sym1 should have 1 gap
        gap_count_sym1 = validator.get_trade_gap_count(sym1, exch)
        assert gap_count_sym1 == 1, (
            f"sym1 should have 1 gap. gap_count={gap_count_sym1}"
        )
        
        # sym2 should have 0 gaps
        gap_count_sym2 = validator.get_trade_gap_count(sym2, exch)
        assert gap_count_sym2 == 0, (
            f"sym2 should have 0 gaps. gap_count={gap_count_sym2}"
        )

    @given(
        first_ts=timestamp,
        threshold=gap_threshold,
        extra_time=st.floats(min_value=0.001, max_value=100.0, allow_nan=False, allow_infinity=False),
        sym=symbol,
        exch1=exchange,
        exch2=exchange,
    )
    @settings(max_examples=100)
    def test_gap_detection_independent_per_exchange(
        self,
        first_ts: float,
        threshold: float,
        extra_time: float,
        sym: str,
        exch1: str,
        exch2: str,
    ):
        """Verify that gap detection is independent per exchange.
        
        Gaps should be tracked separately for each exchange. A gap on one
        exchange should not affect the gap count for another exchange.
        
        **Validates: Requirements 4.2**
        """
        # Ensure we have two different exchanges
        assume(exch1 != exch2)
        
        config = LiveValidationConfig(
            enabled=True,
            gap_threshold_sec=threshold,
        )
        validator = LiveDataValidator(config=config)
        
        # Record trades for exch1 with a gap
        validator.record_trade(sym, exch1, first_ts)
        validator.record_trade(sym, exch1, first_ts + threshold + extra_time)
        
        # Record trades for exch2 without a gap
        validator.record_trade(sym, exch2, first_ts)
        validator.record_trade(sym, exch2, first_ts + threshold * 0.5)  # Less than threshold
        
        # exch1 should have 1 gap
        gap_count_exch1 = validator.get_trade_gap_count(sym, exch1)
        assert gap_count_exch1 == 1, (
            f"exch1 should have 1 gap. gap_count={gap_count_exch1}"
        )
        
        # exch2 should have 0 gaps
        gap_count_exch2 = validator.get_trade_gap_count(sym, exch2)
        assert gap_count_exch2 == 0, (
            f"exch2 should have 0 gaps. gap_count={gap_count_exch2}"
        )

    @given(
        first_ts=timestamp,
        threshold=gap_threshold,
        sym=symbol,
        exch=exchange,
    )
    @settings(max_examples=100)
    def test_validation_disabled_no_gap_tracking(
        self,
        first_ts: float,
        threshold: float,
        sym: str,
        exch: str,
    ):
        """Verify that gap tracking is disabled when config.enabled is False.
        
        When the validator is disabled, no gaps should be tracked even
        if the time between trades exceeds the threshold.
        
        **Validates: Requirements 4.2**
        """
        config = LiveValidationConfig(
            enabled=False,  # Disabled
            gap_threshold_sec=threshold,
        )
        validator = LiveDataValidator(config=config)
        
        # Record trades with a gap
        validator.record_trade(sym, exch, first_ts)
        validator.record_trade(sym, exch, first_ts + threshold + 10.0)  # Exceeds threshold
        
        # No gap should be tracked when disabled
        gap_count = validator.get_trade_gap_count(sym, exch)
        assert gap_count == 0, (
            f"No gaps should be tracked when validator is disabled. "
            f"gap_count={gap_count}"
        )
        
        # Last trade timestamp should also not be tracked
        last_ts = validator.get_last_trade_ts(sym, exch)
        assert last_ts is None, (
            f"Last trade timestamp should not be tracked when disabled. "
            f"last_ts={last_ts}"
        )

    @given(
        first_ts=timestamp,
        threshold=gap_threshold,
        extra_time=st.floats(min_value=0.001, max_value=100.0, allow_nan=False, allow_infinity=False),
        sym=symbol,
        exch=exchange,
    )
    @settings(max_examples=100)
    def test_boundary_just_above_threshold(
        self,
        first_ts: float,
        threshold: float,
        extra_time: float,
        sym: str,
        exch: str,
    ):
        """Verify boundary condition: time just above threshold is a gap.
        
        When the time between trades is just slightly above the threshold,
        a gap should be detected.
        
        **Validates: Requirements 4.2**
        """
        config = LiveValidationConfig(
            enabled=True,
            gap_threshold_sec=threshold,
        )
        validator = LiveDataValidator(config=config)
        
        # Record first trade
        validator.record_trade(sym, exch, first_ts)
        
        # Record second trade just above threshold
        # Use a small epsilon to ensure we're just above
        epsilon = 0.0001
        second_ts = first_ts + threshold + epsilon
        validator.record_trade(sym, exch, second_ts)
        
        # Gap should be detected
        gap_count = validator.get_trade_gap_count(sym, exch)
        assert gap_count == 1, (
            f"Gap should be detected when time is just above threshold. "
            f"time_delta={second_ts - first_ts}, threshold={threshold}, "
            f"gap_count={gap_count}"
        )

    @given(
        first_ts=timestamp,
        threshold=gap_threshold,
        sym=symbol,
        exch=exchange,
    )
    @settings(max_examples=100)
    def test_boundary_just_below_threshold(
        self,
        first_ts: float,
        threshold: float,
        sym: str,
        exch: str,
    ):
        """Verify boundary condition: time just below threshold is not a gap.
        
        When the time between trades is just slightly below the threshold,
        no gap should be detected.
        
        **Validates: Requirements 4.2**
        """
        config = LiveValidationConfig(
            enabled=True,
            gap_threshold_sec=threshold,
        )
        validator = LiveDataValidator(config=config)
        
        # Record first trade
        validator.record_trade(sym, exch, first_ts)
        
        # Record second trade just below threshold
        # Use a small epsilon to ensure we're just below
        epsilon = 0.0001
        second_ts = first_ts + threshold - epsilon
        validator.record_trade(sym, exch, second_ts)
        
        # No gap should be detected
        gap_count = validator.get_trade_gap_count(sym, exch)
        assert gap_count == 0, (
            f"No gap should be detected when time is just below threshold. "
            f"time_delta={second_ts - first_ts}, threshold={threshold}, "
            f"gap_count={gap_count}"
        )

    @given(
        first_ts=timestamp,
        threshold=gap_threshold,
        num_trades=st.integers(min_value=3, max_value=20),
        sym=symbol,
        exch=exchange,
    )
    @settings(max_examples=100)
    def test_mixed_gaps_and_no_gaps(
        self,
        first_ts: float,
        threshold: float,
        num_trades: int,
        sym: str,
        exch: str,
    ):
        """Verify correct gap counting with mixed gap and no-gap intervals.
        
        When some intervals exceed the threshold and some don't, only
        the intervals that exceed the threshold should be counted as gaps.
        
        **Validates: Requirements 4.2**
        """
        config = LiveValidationConfig(
            enabled=True,
            gap_threshold_sec=threshold,
        )
        validator = LiveDataValidator(config=config)
        
        current_ts = first_ts
        expected_gaps = 0
        
        # Record first trade
        validator.record_trade(sym, exch, current_ts)
        
        # Alternate between gap and no-gap intervals
        for i in range(num_trades - 1):
            if i % 2 == 0:
                # Create a gap (time > threshold)
                current_ts = current_ts + threshold + 1.0
                expected_gaps += 1
            else:
                # No gap (time < threshold)
                current_ts = current_ts + threshold * 0.5
            
            validator.record_trade(sym, exch, current_ts)
        
        # Verify gap count
        gap_count = validator.get_trade_gap_count(sym, exch)
        assert gap_count == expected_gaps, (
            f"Gap count should match expected gaps. "
            f"Expected: {expected_gaps}, Actual: {gap_count}"
        )

    @given(
        first_ts=timestamp,
        threshold=gap_threshold,
        extra_time=st.floats(min_value=0.001, max_value=100.0, allow_nan=False, allow_infinity=False),
        sym=symbol,
        exch=exchange,
    )
    @settings(max_examples=100)
    def test_reset_clears_gap_tracking(
        self,
        first_ts: float,
        threshold: float,
        extra_time: float,
        sym: str,
        exch: str,
    ):
        """Verify that reset_symbol clears gap tracking state.
        
        After calling reset_symbol, the gap count and last trade timestamp
        should be cleared for that symbol/exchange pair.
        
        **Validates: Requirements 4.2**
        """
        config = LiveValidationConfig(
            enabled=True,
            gap_threshold_sec=threshold,
        )
        validator = LiveDataValidator(config=config)
        
        # Record trades with a gap
        validator.record_trade(sym, exch, first_ts)
        validator.record_trade(sym, exch, first_ts + threshold + extra_time)
        
        # Verify gap was detected
        assert validator.get_trade_gap_count(sym, exch) == 1
        assert validator.get_last_trade_ts(sym, exch) is not None
        
        # Reset the symbol
        validator.reset_symbol(sym, exch)
        
        # Verify state is cleared
        gap_count = validator.get_trade_gap_count(sym, exch)
        assert gap_count == 0, (
            f"Gap count should be 0 after reset. gap_count={gap_count}"
        )
        
        last_ts = validator.get_last_trade_ts(sym, exch)
        assert last_ts is None, (
            f"Last trade timestamp should be None after reset. last_ts={last_ts}"
        )
