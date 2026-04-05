"""Property-based tests for completeness calculation.

Feature: live-orderbook-data-storage, Property 12: Completeness Calculation

Tests that for any rolling time window of duration W seconds, completeness_pct
SHALL equal (actual_updates_received / expected_updates) * 100, where
expected_updates is calculated based on the expected update frequency.

**Validates: Requirements 4.6**
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

# Window duration generator (configurable window sizes)
window_duration = st.floats(min_value=1.0, max_value=300.0, allow_nan=False, allow_infinity=False)

# Expected updates per second generator
expected_updates_per_sec = st.floats(min_value=0.1, max_value=100.0, allow_nan=False, allow_infinity=False)

# Symbol generator
symbol = st.sampled_from(["BTC/USDT", "ETH/USDT", "SOL/USDT", "DOGE/USDT", "XRP/USDT"])

# Exchange generator
exchange = st.sampled_from(["binance", "coinbase", "kraken", "okx", "bybit"])


# =============================================================================
# Property 12: Completeness Calculation
# =============================================================================

class TestCompletenessCalculation:
    """Property 12: Completeness Calculation
    
    For any rolling time window of duration W seconds, completeness_pct
    SHALL equal (actual_updates_received / expected_updates) * 100, where
    expected_updates is calculated based on the expected update frequency.
    
    **Validates: Requirements 4.6**
    """

    @given(
        start_ts=timestamp,
        window_sec=window_duration,
        expected_per_sec=expected_updates_per_sec,
        num_updates=st.integers(min_value=1, max_value=100),
        sym=symbol,
        exch=exchange,
    )
    @settings(max_examples=100)
    def test_orderbook_completeness_formula(
        self,
        start_ts: float,
        window_sec: float,
        expected_per_sec: float,
        num_updates: int,
        sym: str,
        exch: str,
    ):
        """Verify orderbook completeness formula: (actual / expected) * 100.
        
        The completeness percentage should be calculated as:
            completeness_pct = (actual_updates / expected_updates) * 100
        
        Where expected_updates = window_duration * expected_updates_per_sec.
        
        **Validates: Requirements 4.6**
        """
        config = LiveValidationConfig(
            enabled=True,
            completeness_window_sec=window_sec,
            expected_orderbook_updates_per_sec=expected_per_sec,
        )
        validator = LiveDataValidator(config=config)
        
        # Calculate time interval between updates to spread them evenly
        # across the window
        if num_updates > 1:
            interval = window_sec / (num_updates + 1)
        else:
            interval = window_sec / 2
        
        # Record updates spread across the window
        current_ts = start_ts
        for i in range(num_updates):
            current_ts = start_ts + interval * (i + 1)
            validator.record_orderbook_update(sym, exch, current_ts, seq=i + 1)
        
        # Calculate completeness at the end of the window
        end_ts = start_ts + window_sec
        completeness = validator.get_orderbook_completeness_pct(sym, exch, current_time=end_ts)
        
        # Calculate expected completeness
        # The window duration is from the first update to end_ts
        first_update_ts = start_ts + interval
        actual_window_duration = end_ts - first_update_ts
        
        if actual_window_duration < 0.001:
            # Very small window, completeness should be 100% if we have updates
            expected_completeness = 100.0 if num_updates > 0 else 0.0
        else:
            expected_updates = actual_window_duration * expected_per_sec
            if expected_updates <= 0:
                expected_completeness = 100.0 if num_updates > 0 else 0.0
            else:
                expected_completeness = min((num_updates / expected_updates) * 100.0, 100.0)
        
        # Allow for floating-point tolerance
        assert abs(completeness - expected_completeness) < 1.0, (
            f"Completeness should match formula. "
            f"Expected: {expected_completeness:.2f}%, Actual: {completeness:.2f}%, "
            f"num_updates={num_updates}, window_sec={window_sec}, "
            f"expected_per_sec={expected_per_sec}"
        )

    @given(
        start_ts=timestamp,
        window_sec=window_duration,
        expected_per_sec=expected_updates_per_sec,
        num_trades=st.integers(min_value=1, max_value=100),
        sym=symbol,
        exch=exchange,
    )
    @settings(max_examples=100)
    def test_trade_completeness_formula(
        self,
        start_ts: float,
        window_sec: float,
        expected_per_sec: float,
        num_trades: int,
        sym: str,
        exch: str,
    ):
        """Verify trade completeness formula: (actual / expected) * 100.
        
        The completeness percentage should be calculated as:
            completeness_pct = (actual_trades / expected_trades) * 100
        
        Where expected_trades = window_duration * expected_trades_per_sec.
        
        **Validates: Requirements 4.6**
        """
        config = LiveValidationConfig(
            enabled=True,
            completeness_window_sec=window_sec,
            expected_trades_per_sec=expected_per_sec,
            gap_threshold_sec=window_sec + 100.0,  # Avoid gap detection
        )
        validator = LiveDataValidator(config=config)
        
        # Calculate time interval between trades to spread them evenly
        if num_trades > 1:
            interval = window_sec / (num_trades + 1)
        else:
            interval = window_sec / 2
        
        # Record trades spread across the window
        current_ts = start_ts
        for i in range(num_trades):
            current_ts = start_ts + interval * (i + 1)
            validator.record_trade(sym, exch, current_ts)
        
        # Calculate completeness at the end of the window
        end_ts = start_ts + window_sec
        completeness = validator.get_trade_completeness_pct(sym, exch, current_time=end_ts)
        
        # Calculate expected completeness
        first_trade_ts = start_ts + interval
        actual_window_duration = end_ts - first_trade_ts
        
        if actual_window_duration < 0.001:
            expected_completeness = 100.0 if num_trades > 0 else 0.0
        else:
            expected_trades = actual_window_duration * expected_per_sec
            if expected_trades <= 0:
                expected_completeness = 100.0 if num_trades > 0 else 0.0
            else:
                expected_completeness = min((num_trades / expected_trades) * 100.0, 100.0)
        
        # Allow for floating-point tolerance
        assert abs(completeness - expected_completeness) < 1.0, (
            f"Trade completeness should match formula. "
            f"Expected: {expected_completeness:.2f}%, Actual: {completeness:.2f}%, "
            f"num_trades={num_trades}, window_sec={window_sec}, "
            f"expected_per_sec={expected_per_sec}"
        )

    @given(
        start_ts=timestamp,
        window_sec=st.floats(min_value=10.0, max_value=60.0, allow_nan=False, allow_infinity=False),
        expected_per_sec=st.floats(min_value=0.5, max_value=5.0, allow_nan=False, allow_infinity=False),
        multiplier=st.floats(min_value=1.5, max_value=10.0, allow_nan=False, allow_infinity=False),
        sym=symbol,
        exch=exchange,
    )
    @settings(max_examples=100)
    def test_completeness_capped_at_100_percent(
        self,
        start_ts: float,
        window_sec: float,
        expected_per_sec: float,
        multiplier: float,
        sym: str,
        exch: str,
    ):
        """Verify completeness is capped at 100% when updates exceed expected.
        
        When more updates are received than expected, the completeness
        percentage should be capped at 100.0 to avoid misleading values.
        
        **Validates: Requirements 4.6**
        """
        config = LiveValidationConfig(
            enabled=True,
            completeness_window_sec=window_sec,
            expected_orderbook_updates_per_sec=expected_per_sec,
        )
        validator = LiveDataValidator(config=config)
        
        # Calculate how many updates would exceed 100%
        expected_updates = window_sec * expected_per_sec
        num_updates = int(expected_updates * multiplier)  # More than expected
        
        # Ensure we have at least some updates
        num_updates = max(num_updates, 2)
        
        # Calculate interval to spread updates
        interval = window_sec / (num_updates + 1)
        
        # Record more updates than expected
        for i in range(num_updates):
            current_ts = start_ts + interval * (i + 1)
            validator.record_orderbook_update(sym, exch, current_ts, seq=i + 1)
        
        # Calculate completeness at the end of the window
        end_ts = start_ts + window_sec
        completeness = validator.get_orderbook_completeness_pct(sym, exch, current_time=end_ts)
        
        # Completeness should be capped at 100%
        assert completeness <= 100.0, (
            f"Completeness should be capped at 100%. "
            f"Actual: {completeness:.2f}%, num_updates={num_updates}, "
            f"expected_updates={expected_updates:.2f}"
        )

    @given(
        start_ts=timestamp,
        window_sec=st.floats(min_value=10.0, max_value=60.0, allow_nan=False, allow_infinity=False),
        expected_per_sec=st.floats(min_value=1.0, max_value=10.0, allow_nan=False, allow_infinity=False),
        sym=symbol,
        exch=exchange,
    )
    @settings(max_examples=100)
    def test_rolling_window_removes_old_updates(
        self,
        start_ts: float,
        window_sec: float,
        expected_per_sec: float,
        sym: str,
        exch: str,
    ):
        """Verify rolling window correctly removes updates outside the window.
        
        Updates that are older than the window duration should be removed
        from the rolling window and not counted in completeness calculation.
        
        **Validates: Requirements 4.6**
        """
        config = LiveValidationConfig(
            enabled=True,
            completeness_window_sec=window_sec,
            expected_orderbook_updates_per_sec=expected_per_sec,
        )
        validator = LiveDataValidator(config=config)
        
        # Record some updates at the start
        num_old_updates = 5
        for i in range(num_old_updates):
            ts = start_ts + i * 0.1
            validator.record_orderbook_update(sym, exch, ts, seq=i + 1)
        
        # Move time forward past the window
        new_start_ts = start_ts + window_sec + 10.0
        
        # Record new updates
        num_new_updates = 3
        for i in range(num_new_updates):
            ts = new_start_ts + i * 0.5
            validator.record_orderbook_update(sym, exch, ts, seq=num_old_updates + i + 1)
        
        # Calculate completeness at a time after the new updates
        current_time = new_start_ts + num_new_updates * 0.5 + 1.0
        
        # Get the update count in window
        update_count = validator.get_update_count_in_window(sym, exch, "orderbook")
        
        # Old updates should be removed, only new updates should be counted
        assert update_count <= num_new_updates, (
            f"Old updates should be removed from rolling window. "
            f"Expected at most {num_new_updates}, got {update_count}"
        )

    @given(
        start_ts=timestamp,
        window_sec=window_duration,
        expected_per_sec=expected_updates_per_sec,
        sym=symbol,
        exch=exchange,
    )
    @settings(max_examples=100)
    def test_no_updates_returns_zero_completeness(
        self,
        start_ts: float,
        window_sec: float,
        expected_per_sec: float,
        sym: str,
        exch: str,
    ):
        """Verify completeness is 0% when no updates have been recorded.
        
        When no updates have been recorded for a symbol, the completeness
        percentage should be 0.0.
        
        **Validates: Requirements 4.6**
        """
        config = LiveValidationConfig(
            enabled=True,
            completeness_window_sec=window_sec,
            expected_orderbook_updates_per_sec=expected_per_sec,
        )
        validator = LiveDataValidator(config=config)
        
        # Don't record any updates
        
        # Completeness should be 0%
        orderbook_completeness = validator.get_orderbook_completeness_pct(sym, exch, current_time=start_ts)
        trade_completeness = validator.get_trade_completeness_pct(sym, exch, current_time=start_ts)
        
        assert orderbook_completeness == 0.0, (
            f"Orderbook completeness should be 0% with no updates. "
            f"Actual: {orderbook_completeness:.2f}%"
        )
        assert trade_completeness == 0.0, (
            f"Trade completeness should be 0% with no updates. "
            f"Actual: {trade_completeness:.2f}%"
        )

    @given(
        start_ts=timestamp,
        window_sec=window_duration,
        expected_per_sec=expected_updates_per_sec,
        sym1=symbol,
        sym2=symbol,
        exch=exchange,
    )
    @settings(max_examples=100)
    def test_completeness_independent_per_symbol(
        self,
        start_ts: float,
        window_sec: float,
        expected_per_sec: float,
        sym1: str,
        sym2: str,
        exch: str,
    ):
        """Verify completeness is tracked independently per symbol.
        
        Updates for one symbol should not affect the completeness
        calculation for another symbol.
        
        **Validates: Requirements 4.6**
        """
        # Ensure we have two different symbols
        assume(sym1 != sym2)
        
        config = LiveValidationConfig(
            enabled=True,
            completeness_window_sec=window_sec,
            expected_orderbook_updates_per_sec=expected_per_sec,
        )
        validator = LiveDataValidator(config=config)
        
        # Record updates for sym1 only
        num_updates_sym1 = 10
        interval = window_sec / (num_updates_sym1 + 1)
        for i in range(num_updates_sym1):
            ts = start_ts + interval * (i + 1)
            validator.record_orderbook_update(sym1, exch, ts, seq=i + 1)
        
        # Calculate completeness for both symbols
        end_ts = start_ts + window_sec
        completeness_sym1 = validator.get_orderbook_completeness_pct(sym1, exch, current_time=end_ts)
        completeness_sym2 = validator.get_orderbook_completeness_pct(sym2, exch, current_time=end_ts)
        
        # sym1 should have some completeness
        assert completeness_sym1 > 0.0, (
            f"sym1 should have completeness > 0%. Actual: {completeness_sym1:.2f}%"
        )
        
        # sym2 should have 0% completeness (no updates)
        assert completeness_sym2 == 0.0, (
            f"sym2 should have 0% completeness. Actual: {completeness_sym2:.2f}%"
        )

    @given(
        start_ts=timestamp,
        window_sec=window_duration,
        expected_per_sec=expected_updates_per_sec,
        sym=symbol,
        exch1=exchange,
        exch2=exchange,
    )
    @settings(max_examples=100)
    def test_completeness_independent_per_exchange(
        self,
        start_ts: float,
        window_sec: float,
        expected_per_sec: float,
        sym: str,
        exch1: str,
        exch2: str,
    ):
        """Verify completeness is tracked independently per exchange.
        
        Updates for one exchange should not affect the completeness
        calculation for another exchange.
        
        **Validates: Requirements 4.6**
        """
        # Ensure we have two different exchanges
        assume(exch1 != exch2)
        
        config = LiveValidationConfig(
            enabled=True,
            completeness_window_sec=window_sec,
            expected_orderbook_updates_per_sec=expected_per_sec,
        )
        validator = LiveDataValidator(config=config)
        
        # Record updates for exch1 only
        num_updates_exch1 = 10
        interval = window_sec / (num_updates_exch1 + 1)
        for i in range(num_updates_exch1):
            ts = start_ts + interval * (i + 1)
            validator.record_orderbook_update(sym, exch1, ts, seq=i + 1)
        
        # Calculate completeness for both exchanges
        end_ts = start_ts + window_sec
        completeness_exch1 = validator.get_orderbook_completeness_pct(sym, exch1, current_time=end_ts)
        completeness_exch2 = validator.get_orderbook_completeness_pct(sym, exch2, current_time=end_ts)
        
        # exch1 should have some completeness
        assert completeness_exch1 > 0.0, (
            f"exch1 should have completeness > 0%. Actual: {completeness_exch1:.2f}%"
        )
        
        # exch2 should have 0% completeness (no updates)
        assert completeness_exch2 == 0.0, (
            f"exch2 should have 0% completeness. Actual: {completeness_exch2:.2f}%"
        )

    @given(
        start_ts=timestamp,
        window_sec=st.floats(min_value=10.0, max_value=60.0, allow_nan=False, allow_infinity=False),
        expected_per_sec=st.floats(min_value=1.0, max_value=10.0, allow_nan=False, allow_infinity=False),
        sym=symbol,
        exch=exchange,
    )
    @settings(max_examples=100)
    def test_get_completeness_metrics_returns_both(
        self,
        start_ts: float,
        window_sec: float,
        expected_per_sec: float,
        sym: str,
        exch: str,
    ):
        """Verify get_completeness_metrics returns both orderbook and trade completeness.
        
        The convenience method should return a tuple of (orderbook_pct, trade_pct)
        that matches the individual method results.
        
        **Validates: Requirements 4.6**
        """
        config = LiveValidationConfig(
            enabled=True,
            completeness_window_sec=window_sec,
            expected_orderbook_updates_per_sec=expected_per_sec,
            expected_trades_per_sec=expected_per_sec,
            gap_threshold_sec=window_sec + 100.0,  # Avoid gap detection
        )
        validator = LiveDataValidator(config=config)
        
        # Record some orderbook updates
        num_orderbook_updates = 5
        interval = window_sec / (num_orderbook_updates + 1)
        for i in range(num_orderbook_updates):
            ts = start_ts + interval * (i + 1)
            validator.record_orderbook_update(sym, exch, ts, seq=i + 1)
        
        # Record some trades
        num_trades = 3
        for i in range(num_trades):
            ts = start_ts + interval * (i + 1)
            validator.record_trade(sym, exch, ts)
        
        # Get completeness using both methods
        end_ts = start_ts + window_sec
        orderbook_pct = validator.get_orderbook_completeness_pct(sym, exch, current_time=end_ts)
        trade_pct = validator.get_trade_completeness_pct(sym, exch, current_time=end_ts)
        combined = validator.get_completeness_metrics(sym, exch, current_time=end_ts)
        
        # Combined should match individual results
        assert combined[0] == orderbook_pct, (
            f"Combined orderbook completeness should match individual. "
            f"Combined: {combined[0]:.2f}%, Individual: {orderbook_pct:.2f}%"
        )
        assert combined[1] == trade_pct, (
            f"Combined trade completeness should match individual. "
            f"Combined: {combined[1]:.2f}%, Individual: {trade_pct:.2f}%"
        )

    @given(
        start_ts=timestamp,
        window_sec=st.floats(min_value=10.0, max_value=60.0, allow_nan=False, allow_infinity=False),
        expected_per_sec=st.floats(min_value=1.0, max_value=10.0, allow_nan=False, allow_infinity=False),
        sym=symbol,
        exch=exchange,
    )
    @settings(max_examples=100)
    def test_reset_clears_completeness_tracking(
        self,
        start_ts: float,
        window_sec: float,
        expected_per_sec: float,
        sym: str,
        exch: str,
    ):
        """Verify reset_symbol clears completeness tracking state.
        
        After calling reset_symbol, the completeness should be 0% for
        that symbol/exchange pair.
        
        **Validates: Requirements 4.6**
        """
        config = LiveValidationConfig(
            enabled=True,
            completeness_window_sec=window_sec,
            expected_orderbook_updates_per_sec=expected_per_sec,
            expected_trades_per_sec=expected_per_sec,
            gap_threshold_sec=window_sec + 100.0,  # Avoid gap detection
        )
        validator = LiveDataValidator(config=config)
        
        # Record some updates
        num_updates = 5
        interval = window_sec / (num_updates + 1)
        for i in range(num_updates):
            ts = start_ts + interval * (i + 1)
            validator.record_orderbook_update(sym, exch, ts, seq=i + 1)
            validator.record_trade(sym, exch, ts)
        
        # Verify we have some completeness
        end_ts = start_ts + window_sec
        orderbook_pct = validator.get_orderbook_completeness_pct(sym, exch, current_time=end_ts)
        trade_pct = validator.get_trade_completeness_pct(sym, exch, current_time=end_ts)
        
        assert orderbook_pct > 0.0, "Should have orderbook completeness before reset"
        assert trade_pct > 0.0, "Should have trade completeness before reset"
        
        # Reset the symbol
        validator.reset_symbol(sym, exch)
        
        # Completeness should be 0% after reset
        orderbook_pct_after = validator.get_orderbook_completeness_pct(sym, exch, current_time=end_ts)
        trade_pct_after = validator.get_trade_completeness_pct(sym, exch, current_time=end_ts)
        
        assert orderbook_pct_after == 0.0, (
            f"Orderbook completeness should be 0% after reset. "
            f"Actual: {orderbook_pct_after:.2f}%"
        )
        assert trade_pct_after == 0.0, (
            f"Trade completeness should be 0% after reset. "
            f"Actual: {trade_pct_after:.2f}%"
        )

    @given(
        start_ts=timestamp,
        window_sec=st.floats(min_value=10.0, max_value=60.0, allow_nan=False, allow_infinity=False),
        expected_per_sec=st.floats(min_value=1.0, max_value=10.0, allow_nan=False, allow_infinity=False),
        sym=symbol,
        exch=exchange,
    )
    @settings(max_examples=100)
    def test_validation_disabled_no_completeness_tracking(
        self,
        start_ts: float,
        window_sec: float,
        expected_per_sec: float,
        sym: str,
        exch: str,
    ):
        """Verify completeness tracking is disabled when config.enabled is False.
        
        When the validator is disabled, no completeness should be tracked
        even if updates are recorded.
        
        **Validates: Requirements 4.6**
        """
        config = LiveValidationConfig(
            enabled=False,  # Disabled
            completeness_window_sec=window_sec,
            expected_orderbook_updates_per_sec=expected_per_sec,
            expected_trades_per_sec=expected_per_sec,
        )
        validator = LiveDataValidator(config=config)
        
        # Record some updates
        num_updates = 5
        interval = window_sec / (num_updates + 1)
        for i in range(num_updates):
            ts = start_ts + interval * (i + 1)
            validator.record_orderbook_update(sym, exch, ts, seq=i + 1)
            validator.record_trade(sym, exch, ts)
        
        # Completeness should be 0% when disabled
        end_ts = start_ts + window_sec
        orderbook_pct = validator.get_orderbook_completeness_pct(sym, exch, current_time=end_ts)
        trade_pct = validator.get_trade_completeness_pct(sym, exch, current_time=end_ts)
        
        assert orderbook_pct == 0.0, (
            f"Orderbook completeness should be 0% when disabled. "
            f"Actual: {orderbook_pct:.2f}%"
        )
        assert trade_pct == 0.0, (
            f"Trade completeness should be 0% when disabled. "
            f"Actual: {trade_pct:.2f}%"
        )

    @given(
        start_ts=timestamp,
        window_sec=st.floats(min_value=10.0, max_value=60.0, allow_nan=False, allow_infinity=False),
        expected_per_sec=st.floats(min_value=1.0, max_value=10.0, allow_nan=False, allow_infinity=False),
        completeness_fraction=st.floats(min_value=0.1, max_value=0.9, allow_nan=False, allow_infinity=False),
        sym=symbol,
        exch=exchange,
    )
    @settings(max_examples=100)
    def test_completeness_proportional_to_update_rate(
        self,
        start_ts: float,
        window_sec: float,
        expected_per_sec: float,
        completeness_fraction: float,
        sym: str,
        exch: str,
    ):
        """Verify completeness is proportional to the update rate.
        
        If we receive a fraction of the expected updates, the completeness
        should be approximately that fraction * 100%.
        
        **Validates: Requirements 4.6**
        """
        config = LiveValidationConfig(
            enabled=True,
            completeness_window_sec=window_sec,
            expected_orderbook_updates_per_sec=expected_per_sec,
        )
        validator = LiveDataValidator(config=config)
        
        # Calculate how many updates to send for the target completeness
        expected_updates = window_sec * expected_per_sec
        num_updates = max(1, int(expected_updates * completeness_fraction))
        
        # Calculate interval to spread updates evenly
        interval = window_sec / (num_updates + 1)
        
        # Record updates
        for i in range(num_updates):
            ts = start_ts + interval * (i + 1)
            validator.record_orderbook_update(sym, exch, ts, seq=i + 1)
        
        # Calculate completeness
        end_ts = start_ts + window_sec
        completeness = validator.get_orderbook_completeness_pct(sym, exch, current_time=end_ts)
        
        # Completeness should be approximately proportional to the fraction
        # Allow for some tolerance due to window calculation differences
        # The actual completeness depends on the window duration from first update to end_ts
        first_update_ts = start_ts + interval
        actual_window_duration = end_ts - first_update_ts
        
        if actual_window_duration > 0.001:
            actual_expected = actual_window_duration * expected_per_sec
            expected_completeness = min((num_updates / actual_expected) * 100.0, 100.0)
            
            # Allow 5% tolerance for floating-point and rounding differences
            assert abs(completeness - expected_completeness) < 5.0, (
                f"Completeness should be proportional to update rate. "
                f"Expected: ~{expected_completeness:.2f}%, Actual: {completeness:.2f}%, "
                f"num_updates={num_updates}, expected_updates={expected_updates:.2f}"
            )

    @given(
        start_ts=timestamp,
        window_sec=st.floats(min_value=10.0, max_value=60.0, allow_nan=False, allow_infinity=False),
        expected_per_sec=st.floats(min_value=1.0, max_value=10.0, allow_nan=False, allow_infinity=False),
        sym=symbol,
        exch=exchange,
    )
    @settings(max_examples=100)
    def test_update_count_in_window_matches_recorded(
        self,
        start_ts: float,
        window_sec: float,
        expected_per_sec: float,
        sym: str,
        exch: str,
    ):
        """Verify get_update_count_in_window returns correct count.
        
        The update count in the window should match the number of updates
        recorded within the window duration.
        
        **Validates: Requirements 4.6**
        """
        config = LiveValidationConfig(
            enabled=True,
            completeness_window_sec=window_sec,
            expected_orderbook_updates_per_sec=expected_per_sec,
            expected_trades_per_sec=expected_per_sec,
            gap_threshold_sec=window_sec + 100.0,  # Avoid gap detection
        )
        validator = LiveDataValidator(config=config)
        
        # Record some updates
        num_orderbook_updates = 7
        num_trade_updates = 5
        interval = window_sec / (max(num_orderbook_updates, num_trade_updates) + 1)
        
        for i in range(num_orderbook_updates):
            ts = start_ts + interval * (i + 1)
            validator.record_orderbook_update(sym, exch, ts, seq=i + 1)
        
        for i in range(num_trade_updates):
            ts = start_ts + interval * (i + 1)
            validator.record_trade(sym, exch, ts)
        
        # Get update counts
        orderbook_count = validator.get_update_count_in_window(sym, exch, "orderbook")
        trade_count = validator.get_update_count_in_window(sym, exch, "trade")
        
        # Counts should match recorded updates
        assert orderbook_count == num_orderbook_updates, (
            f"Orderbook update count should match recorded. "
            f"Expected: {num_orderbook_updates}, Actual: {orderbook_count}"
        )
        assert trade_count == num_trade_updates, (
            f"Trade update count should match recorded. "
            f"Expected: {num_trade_updates}, Actual: {trade_count}"
        )
