"""
Property-based tests for Position Guard exit logic.

Feature: scalping-pipeline-audit

These tests verify correctness properties of the PositionGuardWorker's
_should_close() cascade, trailing stop, breakeven stop, profit lock,
fee-aware exit gating, and TP limit exit fill window.

**Validates: Requirements 7.1, 7.2, 7.3, 7.4, 7.5, 7.7**
"""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch
import os

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

from quantgambit.execution.position_guard_worker import (
    PositionGuardConfig,
    PositionGuardWorker,
    _should_close,
    _check_trailing_stop,
    _compute_breakeven_stop_price,
    _is_long,
)
from quantgambit.execution.manager import PositionSnapshot
from quantgambit.risk.fee_model import FeeConfig, FeeModel, FeeAwareExitCheck


# ═══════════════════════════════════════════════════════════════
# SHARED HYPOTHESIS STRATEGIES
# ═══════════════════════════════════════════════════════════════

sides = st.sampled_from(["long", "short"])
symbols = st.sampled_from(["BTCUSDT", "ETHUSDT", "SOLUSDT"])

# Entry prices — realistic range for crypto
entry_prices = st.floats(min_value=10.0, max_value=100000.0, allow_nan=False, allow_infinity=False)

# Hold times in seconds
hold_times = st.floats(min_value=0.0, max_value=600.0, allow_nan=False, allow_infinity=False)

# PnL in basis points (MFE tracking)
mfe_bps = st.floats(min_value=-100.0, max_value=200.0, allow_nan=False, allow_infinity=False)

# Position sizes
sizes = st.floats(min_value=0.001, max_value=10.0, allow_nan=False, allow_infinity=False)


def _make_pos(
    symbol: str = "BTCUSDT",
    side: str = "long",
    size: float = 1.0,
    entry_price: float = 100.0,
    stop_loss: float | None = None,
    take_profit: float | None = None,
    opened_at: float | None = None,
    mfe_pct: float | None = None,
    max_hold_sec: float | None = None,
    time_to_work_sec: float | None = None,
    mfe_min_bps: float | None = None,
) -> PositionSnapshot:
    """Helper to build a PositionSnapshot with sensible defaults."""
    return PositionSnapshot(
        symbol=symbol,
        side=side,
        size=size,
        entry_price=entry_price,
        stop_loss=stop_loss,
        take_profit=take_profit,
        opened_at=opened_at,
        mfe_pct=mfe_pct,
        max_hold_sec=max_hold_sec,
        time_to_work_sec=time_to_work_sec,
        mfe_min_bps=mfe_min_bps,
    )


def _call_should_close(pos, price, config, trailing_peaks=None, fee_model=None, now_ts=None):
    """Wrapper around _should_close with sensible defaults."""
    if now_ts is None:
        now_ts = time.time()
    if trailing_peaks is None:
        trailing_peaks = {}
    return _should_close(pos, price, now_ts, config, trailing_peaks, fee_model)



# ═══════════════════════════════════════════════════════════════
# Property 21: Position guard time-based exit enforcement
# ═══════════════════════════════════════════════════════════════


class TestPositionGuardTimeBasedExit:
    """
    Feature: scalping-pipeline-audit, Property 21: Position guard time-based exit enforcement

    For any position where hold_time > MAX_AGE_SEC, _should_close() should
    recommend closing (returns "max_age_exceeded"). For any position where
    hold_time > MAX_AGE_HARD_SEC, the close should be forced regardless of
    other conditions.

    Note: _should_close() does not directly check max_age_hard_sec — that is
    handled by _evaluate_max_age_governance in the worker. _should_close()
    returns "max_age_exceeded" when hold_time >= max_position_age_sec.

    **Validates: Requirements 7.1**
    """

    @settings(max_examples=200)
    @given(
        side=sides,
        entry_price=entry_prices,
        max_age_sec=st.floats(min_value=30.0, max_value=600.0, allow_nan=False, allow_infinity=False),
        overshoot_sec=st.floats(min_value=0.1, max_value=300.0, allow_nan=False, allow_infinity=False),
    )
    def test_max_age_exceeded_triggers_close(
        self,
        side: str,
        entry_price: float,
        max_age_sec: float,
        overshoot_sec: float,
    ):
        """Feature: scalping-pipeline-audit, Property 21: Position guard time-based exit enforcement

        When hold_time >= max_position_age_sec, _should_close() returns "max_age_exceeded".
        """
        now = time.time()
        hold_time = max_age_sec + overshoot_sec
        opened_at = now - hold_time

        pos = _make_pos(
            side=side,
            entry_price=entry_price,
            opened_at=opened_at,
        )
        config = PositionGuardConfig(max_position_age_sec=max_age_sec)

        result = _call_should_close(pos, entry_price, config, now_ts=now)
        assert result == "max_age_exceeded", (
            f"Expected 'max_age_exceeded' for hold_time={hold_time:.1f}s > "
            f"max_age={max_age_sec:.1f}s, got {result!r}"
        )

    @settings(max_examples=200)
    @given(
        side=sides,
        entry_price=entry_prices,
        max_age_sec=st.floats(min_value=30.0, max_value=600.0, allow_nan=False, allow_infinity=False),
        hold_fraction=st.floats(min_value=0.01, max_value=0.99, allow_nan=False, allow_infinity=False),
    )
    def test_below_max_age_no_time_close(
        self,
        side: str,
        entry_price: float,
        max_age_sec: float,
        hold_fraction: float,
    ):
        """Feature: scalping-pipeline-audit, Property 21: Position guard time-based exit enforcement

        When hold_time < max_position_age_sec and no other exit triggers,
        _should_close() returns None (no close).
        """
        now = time.time()
        hold_time = max_age_sec * hold_fraction
        opened_at = now - hold_time

        pos = _make_pos(
            side=side,
            entry_price=entry_price,
            opened_at=opened_at,
        )
        config = PositionGuardConfig(max_position_age_sec=max_age_sec)

        result = _call_should_close(pos, entry_price, config, now_ts=now)
        assert result is None, (
            f"Expected None for hold_time={hold_time:.1f}s < "
            f"max_age={max_age_sec:.1f}s, got {result!r}"
        )

    @settings(max_examples=200)
    @given(
        side=sides,
        entry_price=entry_prices,
        max_age_sec=st.floats(min_value=60.0, max_value=300.0, allow_nan=False, allow_infinity=False),
        hard_extra=st.floats(min_value=30.0, max_value=300.0, allow_nan=False, allow_infinity=False),
    )
    def test_hard_max_age_concept(
        self,
        side: str,
        entry_price: float,
        max_age_sec: float,
        hard_extra: float,
    ):
        """Feature: scalping-pipeline-audit, Property 21: Position guard time-based exit enforcement

        Verify that max_age_hard_sec > max_age_sec is a valid configuration.
        When hold_time exceeds max_age_sec, _should_close() triggers regardless.
        The hard max age is enforced at the governance layer (_evaluate_max_age_governance).
        """
        hard_sec = max_age_sec + hard_extra
        now = time.time()
        # Position held past hard max age
        opened_at = now - (hard_sec + 10.0)

        pos = _make_pos(
            side=side,
            entry_price=entry_price,
            opened_at=opened_at,
        )
        config = PositionGuardConfig(
            max_position_age_sec=max_age_sec,
            max_age_hard_sec=hard_sec,
        )

        result = _call_should_close(pos, entry_price, config, now_ts=now)
        # At minimum, max_age_exceeded should fire since hold_time > max_age_sec
        assert result == "max_age_exceeded", (
            f"Expected 'max_age_exceeded' for hold past hard max age, got {result!r}"
        )


# ═══════════════════════════════════════════════════════════════
# Property 22: Position guard trailing stop activation and trail
# ═══════════════════════════════════════════════════════════════


class TestPositionGuardTrailingStop:
    """
    Feature: scalping-pipeline-audit, Property 22: Position guard trailing stop activation and trail

    Trailing stop activates when PnL (MFE) >= TRAILING_ACTIVATION_BPS and
    position held >= TRAILING_MIN_HOLD_SEC. Once active, closes on retrace
    > TRAILING_BPS from peak.

    **Validates: Requirements 7.2**
    """

    @settings(max_examples=200)
    @given(
        side=sides,
        entry_price=st.floats(min_value=100.0, max_value=50000.0, allow_nan=False, allow_infinity=False),
        trailing_bps=st.floats(min_value=5.0, max_value=100.0, allow_nan=False, allow_infinity=False),
        activation_bps=st.floats(min_value=5.0, max_value=80.0, allow_nan=False, allow_infinity=False),
        min_hold_sec=st.floats(min_value=0.0, max_value=60.0, allow_nan=False, allow_infinity=False),
        hold_extra=st.floats(min_value=1.0, max_value=120.0, allow_nan=False, allow_infinity=False),
    )
    def test_trailing_stop_triggers_on_retrace_from_peak(
        self,
        side: str,
        entry_price: float,
        trailing_bps: float,
        activation_bps: float,
        min_hold_sec: float,
        hold_extra: float,
    ):
        """Feature: scalping-pipeline-audit, Property 22: Position guard trailing stop activation and trail

        When MFE >= activation threshold, held long enough, and price retraces
        > trailing_bps from peak, _should_close() returns "trailing_stop_hit".
        """
        now = time.time()
        hold_time = min_hold_sec + hold_extra
        opened_at = now - hold_time

        # MFE exceeds activation threshold
        mfe_pct = (activation_bps + 5.0) / 100.0  # Convert bps to pct

        pos = _make_pos(
            side=side,
            entry_price=entry_price,
            opened_at=opened_at,
            mfe_pct=mfe_pct,
        )

        config = PositionGuardConfig(
            trailing_stop_bps=trailing_bps,
            trailing_activation_bps=activation_bps,
            trailing_min_hold_sec=min_hold_sec,
        )

        # Set up a peak and a price that retraces beyond trailing_bps
        if side == "long":
            peak_price = entry_price * (1 + (activation_bps + 10.0) / 10000.0)
            # Price retraces more than trailing_bps from peak
            retrace_price = peak_price * (1 - (trailing_bps + 1.0) / 10000.0)
            trailing_peaks = {f"{pos.symbol}:long": peak_price}
        else:
            peak_price = entry_price * (1 - (activation_bps + 10.0) / 10000.0)
            retrace_price = peak_price * (1 + (trailing_bps + 1.0) / 10000.0)
            trailing_peaks = {f"{pos.symbol}:short": peak_price}

        result = _call_should_close(
            pos, retrace_price, config, trailing_peaks=trailing_peaks, now_ts=now
        )
        assert result == "trailing_stop_hit", (
            f"Expected 'trailing_stop_hit' for {side} with retrace from peak, got {result!r}"
        )

    @settings(max_examples=200)
    @given(
        side=sides,
        entry_price=st.floats(min_value=100.0, max_value=50000.0, allow_nan=False, allow_infinity=False),
        trailing_bps=st.floats(min_value=10.0, max_value=100.0, allow_nan=False, allow_infinity=False),
        activation_bps=st.floats(min_value=10.0, max_value=80.0, allow_nan=False, allow_infinity=False),
        min_hold_sec=st.floats(min_value=5.0, max_value=60.0, allow_nan=False, allow_infinity=False),
    )
    def test_trailing_stop_blocked_before_min_hold(
        self,
        side: str,
        entry_price: float,
        trailing_bps: float,
        activation_bps: float,
        min_hold_sec: float,
    ):
        """Feature: scalping-pipeline-audit, Property 22: Position guard trailing stop activation and trail

        When hold_time < trailing_min_hold_sec, trailing stop should not trigger
        even if MFE exceeds activation and price retraces.
        """
        now = time.time()
        # Hold time is less than min_hold_sec
        hold_time = min_hold_sec * 0.5
        assume(hold_time > 0.0)
        opened_at = now - hold_time

        mfe_pct = (activation_bps + 10.0) / 100.0

        pos = _make_pos(
            side=side,
            entry_price=entry_price,
            opened_at=opened_at,
            mfe_pct=mfe_pct,
        )

        config = PositionGuardConfig(
            trailing_stop_bps=trailing_bps,
            trailing_activation_bps=activation_bps,
            trailing_min_hold_sec=min_hold_sec,
        )

        # Set up peak and retrace that would normally trigger
        if side == "long":
            peak_price = entry_price * 1.01
            retrace_price = peak_price * (1 - (trailing_bps + 5.0) / 10000.0)
            trailing_peaks = {f"{pos.symbol}:long": peak_price}
        else:
            peak_price = entry_price * 0.99
            retrace_price = peak_price * (1 + (trailing_bps + 5.0) / 10000.0)
            trailing_peaks = {f"{pos.symbol}:short": peak_price}

        result = _call_should_close(
            pos, retrace_price, config, trailing_peaks=trailing_peaks, now_ts=now
        )
        # Min hold blocks trailing — returns None (early return)
        assert result is None, (
            f"Expected None (min hold blocks trailing) for hold_time={hold_time:.1f}s < "
            f"min_hold={min_hold_sec:.1f}s, got {result!r}"
        )

    @settings(max_examples=200)
    @given(
        side=sides,
        entry_price=st.floats(min_value=100.0, max_value=50000.0, allow_nan=False, allow_infinity=False),
        trailing_bps=st.floats(min_value=10.0, max_value=100.0, allow_nan=False, allow_infinity=False),
        activation_bps=st.floats(min_value=10.0, max_value=80.0, allow_nan=False, allow_infinity=False),
    )
    def test_trailing_stop_not_active_below_activation(
        self,
        side: str,
        entry_price: float,
        trailing_bps: float,
        activation_bps: float,
    ):
        """Feature: scalping-pipeline-audit, Property 22: Position guard trailing stop activation and trail

        When MFE < activation threshold, trailing stop should not activate.
        """
        now = time.time()
        opened_at = now - 120.0  # Held long enough

        # MFE below activation
        mfe_pct = (activation_bps - 1.0) / 100.0
        assume(mfe_pct > 0.0)

        pos = _make_pos(
            side=side,
            entry_price=entry_price,
            opened_at=opened_at,
            mfe_pct=mfe_pct,
        )

        config = PositionGuardConfig(
            trailing_stop_bps=trailing_bps,
            trailing_activation_bps=activation_bps,
            trailing_min_hold_sec=0.0,
        )

        # Even with a peak set, activation threshold not met
        if side == "long":
            trailing_peaks = {f"{pos.symbol}:long": entry_price * 1.005}
        else:
            trailing_peaks = {f"{pos.symbol}:short": entry_price * 0.995}

        result = _call_should_close(
            pos, entry_price, config, trailing_peaks=trailing_peaks, now_ts=now
        )
        assert result is None, (
            f"Expected None (MFE below activation) for mfe={mfe_pct*100:.1f}bps < "
            f"activation={activation_bps:.1f}bps, got {result!r}"
        )


# ═══════════════════════════════════════════════════════════════
# Property 23: Position guard breakeven stop
# ═══════════════════════════════════════════════════════════════


class TestPositionGuardBreakevenStop:
    """
    Feature: scalping-pipeline-audit, Property 23: Position guard breakeven stop

    When PnL (MFE) reaches BREAKEVEN_ACTIVATION_BPS, the effective stop moves
    to breakeven + BREAKEVEN_BUFFER_BPS. If price retraces to or below this
    level, _should_close() returns "breakeven_stop_hit".

    **Validates: Requirements 7.3**
    """

    @settings(max_examples=200)
    @given(
        side=sides,
        entry_price=st.floats(min_value=100.0, max_value=50000.0, allow_nan=False, allow_infinity=False),
        activation_bps=st.floats(min_value=10.0, max_value=80.0, allow_nan=False, allow_infinity=False),
        buffer_bps=st.floats(min_value=1.0, max_value=50.0, allow_nan=False, allow_infinity=False),
    )
    def test_breakeven_stop_triggers_after_activation(
        self,
        side: str,
        entry_price: float,
        activation_bps: float,
        buffer_bps: float,
    ):
        """Feature: scalping-pipeline-audit, Property 23: Position guard breakeven stop

        When MFE >= activation and price retraces to breakeven + buffer level,
        _should_close() returns "breakeven_stop_hit".
        """
        now = time.time()
        opened_at = now - 120.0  # Held long enough

        # MFE exceeds activation
        mfe_pct = (activation_bps + 5.0) / 100.0

        pos = _make_pos(
            side=side,
            entry_price=entry_price,
            size=1.0,
            opened_at=opened_at,
            mfe_pct=mfe_pct,
        )

        config = PositionGuardConfig(
            breakeven_activation_bps=activation_bps,
            breakeven_buffer_bps=buffer_bps,
        )

        # Without fee model, breakeven_bps = 0, so stop_price = entry * (1 + buffer/10000)
        # for long, or entry * (1 - buffer/10000) for short.
        # Price at or below the breakeven stop price triggers.
        if side == "long":
            stop_price = entry_price * (1 + buffer_bps / 10000.0)
            # Price just below the stop
            test_price = stop_price - entry_price * 0.0001
        else:
            stop_price = entry_price * (1 - buffer_bps / 10000.0)
            # Price just above the stop (for short, price >= stop triggers)
            test_price = stop_price + entry_price * 0.0001

        result = _call_should_close(pos, test_price, config, now_ts=now)
        assert result == "breakeven_stop_hit", (
            f"Expected 'breakeven_stop_hit' for {side} with MFE={mfe_pct*100:.1f}bps >= "
            f"activation={activation_bps:.1f}bps, got {result!r}"
        )

    @settings(max_examples=200)
    @given(
        side=sides,
        entry_price=st.floats(min_value=100.0, max_value=50000.0, allow_nan=False, allow_infinity=False),
        activation_bps=st.floats(min_value=10.0, max_value=80.0, allow_nan=False, allow_infinity=False),
        buffer_bps=st.floats(min_value=1.0, max_value=50.0, allow_nan=False, allow_infinity=False),
    )
    def test_breakeven_stop_not_active_below_mfe(
        self,
        side: str,
        entry_price: float,
        activation_bps: float,
        buffer_bps: float,
    ):
        """Feature: scalping-pipeline-audit, Property 23: Position guard breakeven stop

        When MFE < activation threshold, breakeven stop should not trigger.
        """
        now = time.time()
        opened_at = now - 120.0

        # MFE below activation
        mfe_pct = (activation_bps - 2.0) / 100.0
        assume(mfe_pct > 0.0)

        pos = _make_pos(
            side=side,
            entry_price=entry_price,
            size=1.0,
            opened_at=opened_at,
            mfe_pct=mfe_pct,
        )

        config = PositionGuardConfig(
            breakeven_activation_bps=activation_bps,
            breakeven_buffer_bps=buffer_bps,
        )

        # Price at entry (would trigger breakeven if active)
        result = _call_should_close(pos, entry_price, config, now_ts=now)
        assert result is None, (
            f"Expected None (MFE below activation) for mfe={mfe_pct*100:.1f}bps < "
            f"activation={activation_bps:.1f}bps, got {result!r}"
        )

    @settings(max_examples=200)
    @given(
        side=sides,
        entry_price=st.floats(min_value=100.0, max_value=50000.0, allow_nan=False, allow_infinity=False),
        activation_bps=st.floats(min_value=10.0, max_value=80.0, allow_nan=False, allow_infinity=False),
        buffer_bps=st.floats(min_value=5.0, max_value=50.0, allow_nan=False, allow_infinity=False),
    )
    def test_breakeven_stop_with_fee_model(
        self,
        side: str,
        entry_price: float,
        activation_bps: float,
        buffer_bps: float,
    ):
        """Feature: scalping-pipeline-audit, Property 23: Position guard breakeven stop

        With a fee model, the breakeven stop price accounts for round-trip fees
        plus the buffer. The stop should be further from entry than without fees.
        """
        now = time.time()
        opened_at = now - 120.0

        mfe_pct = (activation_bps + 10.0) / 100.0

        pos = _make_pos(
            side=side,
            entry_price=entry_price,
            size=1.0,
            opened_at=opened_at,
            mfe_pct=mfe_pct,
        )

        config = PositionGuardConfig(
            breakeven_activation_bps=activation_bps,
            breakeven_buffer_bps=buffer_bps,
        )

        fee_model = FeeModel(FeeConfig.bybit_regular())

        # Compute the breakeven stop price with fees
        stop_price = _compute_breakeven_stop_price(pos, fee_model, buffer_bps)
        assert stop_price is not None, "Breakeven stop price should be computable"

        # Stop price should be further from entry than just buffer alone
        stop_no_fees = _compute_breakeven_stop_price(pos, None, buffer_bps)
        assert stop_no_fees is not None

        if side == "long":
            # With fees, stop should be higher (further from entry for long)
            assert stop_price >= stop_no_fees - 1e-9, (
                f"With fees, long stop {stop_price:.6f} should be >= no-fee stop {stop_no_fees:.6f}"
            )
        else:
            # With fees, stop should be lower (further from entry for short)
            assert stop_price <= stop_no_fees + 1e-9, (
                f"With fees, short stop {stop_price:.6f} should be <= no-fee stop {stop_no_fees:.6f}"
            )


# ═══════════════════════════════════════════════════════════════
# Property 24: Position guard profit lock
# ═══════════════════════════════════════════════════════════════


class TestPositionGuardProfitLock:
    """
    Feature: scalping-pipeline-audit, Property 24: Position guard profit lock

    When PnL (MFE) reaches PROFIT_LOCK_ACTIVATION_BPS, the position should be
    closed if current PnL retraces to <= PROFIT_LOCK_RETRACE_BPS.

    **Validates: Requirements 7.4**
    """

    @settings(max_examples=200)
    @given(
        side=sides,
        entry_price=st.floats(min_value=100.0, max_value=50000.0, allow_nan=False, allow_infinity=False),
        activation_bps=st.floats(min_value=15.0, max_value=100.0, allow_nan=False, allow_infinity=False),
        retrace_bps=st.floats(min_value=1.0, max_value=50.0, allow_nan=False, allow_infinity=False),
    )
    def test_profit_lock_triggers_on_retrace(
        self,
        side: str,
        entry_price: float,
        activation_bps: float,
        retrace_bps: float,
    ):
        """Feature: scalping-pipeline-audit, Property 24: Position guard profit lock

        When MFE >= activation and current PnL <= retrace_bps,
        _should_close() returns "profit_lock_retrace".
        """
        assume(activation_bps > retrace_bps)
        now = time.time()
        opened_at = now - 120.0

        # MFE exceeds activation
        mfe_pct = (activation_bps + 5.0) / 100.0

        # Current PnL at or below retrace threshold
        # For long: pnl_bps = (price - entry) / entry * 10000
        # We want pnl_bps <= retrace_bps
        if side == "long":
            # pnl_bps = (price - entry) / entry * 10000 = retrace_bps - 1
            target_pnl_bps = retrace_bps - 1.0
            price = entry_price * (1 + target_pnl_bps / 10000.0)
        else:
            # pnl_bps = (entry - price) / entry * 10000 = retrace_bps - 1
            target_pnl_bps = retrace_bps - 1.0
            price = entry_price * (1 - target_pnl_bps / 10000.0)

        pos = _make_pos(
            side=side,
            entry_price=entry_price,
            opened_at=opened_at,
            mfe_pct=mfe_pct,
        )

        config = PositionGuardConfig(
            profit_lock_activation_bps=activation_bps,
            profit_lock_retrace_bps=retrace_bps,
        )

        result = _call_should_close(pos, price, config, now_ts=now)
        assert result == "profit_lock_retrace", (
            f"Expected 'profit_lock_retrace' for {side} with MFE={mfe_pct*100:.1f}bps >= "
            f"activation={activation_bps:.1f}bps and pnl={target_pnl_bps:.1f}bps <= "
            f"retrace={retrace_bps:.1f}bps, got {result!r}"
        )

    @settings(max_examples=200)
    @given(
        side=sides,
        entry_price=st.floats(min_value=100.0, max_value=50000.0, allow_nan=False, allow_infinity=False),
        activation_bps=st.floats(min_value=15.0, max_value=100.0, allow_nan=False, allow_infinity=False),
        retrace_bps=st.floats(min_value=1.0, max_value=50.0, allow_nan=False, allow_infinity=False),
    )
    def test_profit_lock_not_active_below_mfe(
        self,
        side: str,
        entry_price: float,
        activation_bps: float,
        retrace_bps: float,
    ):
        """Feature: scalping-pipeline-audit, Property 24: Position guard profit lock

        When MFE < activation threshold, profit lock should not trigger.
        """
        now = time.time()
        opened_at = now - 120.0

        # MFE below activation
        mfe_pct = (activation_bps - 2.0) / 100.0
        assume(mfe_pct > 0.0)

        pos = _make_pos(
            side=side,
            entry_price=entry_price,
            opened_at=opened_at,
            mfe_pct=mfe_pct,
        )

        config = PositionGuardConfig(
            profit_lock_activation_bps=activation_bps,
            profit_lock_retrace_bps=retrace_bps,
        )

        # Price at entry (pnl = 0, which is below retrace_bps)
        result = _call_should_close(pos, entry_price, config, now_ts=now)
        assert result is None, (
            f"Expected None (MFE below activation) for mfe={mfe_pct*100:.1f}bps < "
            f"activation={activation_bps:.1f}bps, got {result!r}"
        )

    @settings(max_examples=200)
    @given(
        side=sides,
        entry_price=st.floats(min_value=100.0, max_value=50000.0, allow_nan=False, allow_infinity=False),
        activation_bps=st.floats(min_value=15.0, max_value=100.0, allow_nan=False, allow_infinity=False),
        retrace_bps=st.floats(min_value=5.0, max_value=50.0, allow_nan=False, allow_infinity=False),
        pnl_above_retrace=st.floats(min_value=1.0, max_value=50.0, allow_nan=False, allow_infinity=False),
    )
    def test_profit_lock_no_trigger_when_pnl_above_retrace(
        self,
        side: str,
        entry_price: float,
        activation_bps: float,
        retrace_bps: float,
        pnl_above_retrace: float,
    ):
        """Feature: scalping-pipeline-audit, Property 24: Position guard profit lock

        When MFE >= activation but current PnL > retrace_bps, profit lock
        should not trigger.
        """
        now = time.time()
        opened_at = now - 120.0

        mfe_pct = (activation_bps + 10.0) / 100.0

        # Current PnL above retrace threshold
        target_pnl_bps = retrace_bps + pnl_above_retrace
        if side == "long":
            price = entry_price * (1 + target_pnl_bps / 10000.0)
        else:
            price = entry_price * (1 - target_pnl_bps / 10000.0)

        pos = _make_pos(
            side=side,
            entry_price=entry_price,
            opened_at=opened_at,
            mfe_pct=mfe_pct,
        )

        config = PositionGuardConfig(
            profit_lock_activation_bps=activation_bps,
            profit_lock_retrace_bps=retrace_bps,
        )

        result = _call_should_close(pos, price, config, now_ts=now)
        assert result is None, (
            f"Expected None (PnL above retrace) for pnl={target_pnl_bps:.1f}bps > "
            f"retrace={retrace_bps:.1f}bps, got {result!r}"
        )


# ═══════════════════════════════════════════════════════════════
# Property 25: Fee-aware exit profitability check
# ═══════════════════════════════════════════════════════════════


class TestFeeAwareExitProfitabilityCheck:
    """
    Feature: scalping-pipeline-audit, Property 25: Fee-aware exit profitability check

    _apply_fee_check() blocks exit when gross profit < breakeven + MIN_PROFIT_BUFFER_BPS,
    unless the exit is a safety exit (stop-loss, hard time stop, etc.).

    In the current implementation, fee checks are ONLY applied to "trailing_stop_hit"
    exits. All other reasons bypass the fee check entirely.

    **Validates: Requirements 7.5**
    """

    @settings(max_examples=200)
    @given(
        side=sides,
        entry_price=st.floats(min_value=100.0, max_value=50000.0, allow_nan=False, allow_infinity=False),
        size=st.floats(min_value=0.01, max_value=5.0, allow_nan=False, allow_infinity=False),
        min_profit_buffer_bps=st.floats(min_value=1.0, max_value=30.0, allow_nan=False, allow_infinity=False),
    )
    def test_fee_check_blocks_unprofitable_trailing_exit(
        self,
        side: str,
        entry_price: float,
        size: float,
        min_profit_buffer_bps: float,
    ):
        """Feature: scalping-pipeline-audit, Property 25: Fee-aware exit profitability check

        When reason is "trailing_stop_hit" and gross profit < breakeven + buffer,
        the fee check should block the exit (should_allow_exit=False).
        """
        fee_model = FeeModel(FeeConfig.bybit_regular())

        # Price at entry (0 gross profit — definitely below breakeven + buffer)
        pos = _make_pos(
            side=side,
            entry_price=entry_price,
            size=size,
        )

        worker = PositionGuardWorker(
            exchange_client=MagicMock(),
            position_manager=MagicMock(),
            config=PositionGuardConfig(),
            fee_model=fee_model,
            min_profit_buffer_bps=min_profit_buffer_bps,
        )

        result = worker._apply_fee_check(pos, entry_price, "trailing_stop_hit")
        assert result is not None, "Fee check should be applied for trailing_stop_hit"
        assert result.should_allow_exit is False, (
            f"Fee check should block exit at entry price (0 gross profit), "
            f"but got should_allow_exit={result.should_allow_exit}"
        )

    @settings(max_examples=200)
    @given(
        side=sides,
        entry_price=st.floats(min_value=100.0, max_value=50000.0, allow_nan=False, allow_infinity=False),
        size=st.floats(min_value=0.01, max_value=5.0, allow_nan=False, allow_infinity=False),
        profit_bps=st.floats(min_value=50.0, max_value=200.0, allow_nan=False, allow_infinity=False),
    )
    def test_fee_check_allows_profitable_trailing_exit(
        self,
        side: str,
        entry_price: float,
        size: float,
        profit_bps: float,
    ):
        """Feature: scalping-pipeline-audit, Property 25: Fee-aware exit profitability check

        When reason is "trailing_stop_hit" and gross profit is well above
        breakeven + buffer, the fee check should allow the exit.
        """
        fee_model = FeeModel(FeeConfig.bybit_regular())
        min_profit_buffer_bps = 14.0

        # Price with significant profit
        if side == "long":
            price = entry_price * (1 + profit_bps / 10000.0)
        else:
            price = entry_price * (1 - profit_bps / 10000.0)

        pos = _make_pos(
            side=side,
            entry_price=entry_price,
            size=size,
        )

        worker = PositionGuardWorker(
            exchange_client=MagicMock(),
            position_manager=MagicMock(),
            config=PositionGuardConfig(),
            fee_model=fee_model,
            min_profit_buffer_bps=min_profit_buffer_bps,
        )

        result = worker._apply_fee_check(pos, price, "trailing_stop_hit")
        assert result is not None, "Fee check should be applied for trailing_stop_hit"
        assert result.should_allow_exit is True, (
            f"Fee check should allow exit with {profit_bps:.1f}bps profit, "
            f"but got should_allow_exit={result.should_allow_exit}, "
            f"min_required={result.min_required_bps:.2f}bps"
        )

    @settings(max_examples=200)
    @given(
        side=sides,
        entry_price=st.floats(min_value=100.0, max_value=50000.0, allow_nan=False, allow_infinity=False),
        size=st.floats(min_value=0.01, max_value=5.0, allow_nan=False, allow_infinity=False),
        reason=st.sampled_from([
            "stop_loss_hit",
            "take_profit_hit",
            "breakeven_stop_hit",
            "profit_lock_retrace",
            "max_age_exceeded",
            "max_hold_exceeded",
            "time_to_work_fail",
        ]),
    )
    def test_fee_check_bypassed_for_non_trailing_exits(
        self,
        side: str,
        entry_price: float,
        size: float,
        reason: str,
    ):
        """Feature: scalping-pipeline-audit, Property 25: Fee-aware exit profitability check

        For all exit reasons other than "trailing_stop_hit", _apply_fee_check()
        returns None (bypassed), allowing the exit regardless of profitability.
        """
        fee_model = FeeModel(FeeConfig.bybit_regular())

        pos = _make_pos(
            side=side,
            entry_price=entry_price,
            size=size,
        )

        worker = PositionGuardWorker(
            exchange_client=MagicMock(),
            position_manager=MagicMock(),
            config=PositionGuardConfig(),
            fee_model=fee_model,
            min_profit_buffer_bps=14.0,
        )

        result = worker._apply_fee_check(pos, entry_price, reason)
        assert result is None, (
            f"Fee check should be bypassed for reason={reason!r}, "
            f"but got {result!r}"
        )

    @settings(max_examples=200)
    @given(
        side=sides,
        entry_price=st.floats(min_value=100.0, max_value=50000.0, allow_nan=False, allow_infinity=False),
        size=st.floats(min_value=0.01, max_value=5.0, allow_nan=False, allow_infinity=False),
    )
    def test_fee_check_returns_none_without_fee_model(
        self,
        side: str,
        entry_price: float,
        size: float,
    ):
        """Feature: scalping-pipeline-audit, Property 25: Fee-aware exit profitability check

        When no fee model is configured, _apply_fee_check() returns None.
        """
        pos = _make_pos(
            side=side,
            entry_price=entry_price,
            size=size,
        )

        worker = PositionGuardWorker(
            exchange_client=MagicMock(),
            position_manager=MagicMock(),
            config=PositionGuardConfig(),
            fee_model=None,
            min_profit_buffer_bps=14.0,
        )

        result = worker._apply_fee_check(pos, entry_price, "trailing_stop_hit")
        assert result is None, (
            f"Fee check should return None without fee model, got {result!r}"
        )


# ═══════════════════════════════════════════════════════════════
# Property 26: TP limit exit fill window
# ═══════════════════════════════════════════════════════════════


class TestTPLimitExitFillWindow:
    """
    Feature: scalping-pipeline-audit, Property 26: TP limit exit fill window

    When TP_LIMIT_EXIT_ENABLED is true, the position guard attempts a limit
    order exit for qualifying reasons (take_profit_hit, profit_lock_retrace)
    with a fill window of TP_LIMIT_FILL_WINDOW_MS.

    **Validates: Requirements 7.7**
    """

    @settings(max_examples=200)
    @given(
        tp_limit_enabled=st.booleans(),
        fill_window_ms=st.integers(min_value=100, max_value=5000),
        reason=st.sampled_from(["take_profit_hit", "profit_lock_retrace"]),
    )
    def test_tp_limit_config_respected(
        self,
        tp_limit_enabled: bool,
        fill_window_ms: int,
        reason: str,
    ):
        """Feature: scalping-pipeline-audit, Property 26: TP limit exit fill window

        When tp_limit_exit_enabled is configured, the worker stores the config
        and qualifying reasons include take_profit_hit and profit_lock_retrace.
        """
        config = PositionGuardConfig(
            tp_limit_exit_enabled=tp_limit_enabled,
            tp_limit_fill_window_ms=fill_window_ms,
        )

        worker = PositionGuardWorker(
            exchange_client=MagicMock(),
            position_manager=MagicMock(),
            config=config,
        )

        assert worker.config.tp_limit_exit_enabled == tp_limit_enabled
        assert worker.config.tp_limit_fill_window_ms == fill_window_ms

        # Verify qualifying reasons
        if tp_limit_enabled:
            assert reason in worker._tp_limit_reasons, (
                f"Reason {reason!r} should be in TP limit qualifying reasons"
            )

    @settings(max_examples=200)
    @given(
        reason=st.sampled_from([
            "stop_loss_hit",
            "trailing_stop_hit",
            "breakeven_stop_hit",
            "max_age_exceeded",
            "max_hold_exceeded",
            "time_to_work_fail",
        ]),
    )
    def test_non_qualifying_reasons_excluded(
        self,
        reason: str,
    ):
        """Feature: scalping-pipeline-audit, Property 26: TP limit exit fill window

        Non-qualifying exit reasons should NOT trigger TP limit exit path.
        """
        config = PositionGuardConfig(
            tp_limit_exit_enabled=True,
            tp_limit_fill_window_ms=800,
        )

        worker = PositionGuardWorker(
            exchange_client=MagicMock(),
            position_manager=MagicMock(),
            config=config,
        )

        assert reason not in worker._tp_limit_reasons, (
            f"Reason {reason!r} should NOT be in TP limit qualifying reasons"
        )

    @settings(max_examples=200)
    @given(
        side=sides,
        entry_price=st.floats(min_value=100.0, max_value=50000.0, allow_nan=False, allow_infinity=False),
        buffer_bps=st.floats(min_value=0.1, max_value=5.0, allow_nan=False, allow_infinity=False),
    )
    def test_tp_limit_price_computation(
        self,
        side: str,
        entry_price: float,
        buffer_bps: float,
    ):
        """Feature: scalping-pipeline-audit, Property 26: TP limit exit fill window

        _compute_tp_limit_price() derives the limit price from best bid/ask
        with a buffer. For long positions, it uses bid - buffer; for short,
        ask + buffer.
        """
        config = PositionGuardConfig(
            tp_limit_exit_enabled=True,
            tp_limit_fill_window_ms=800,
            tp_limit_price_buffer_bps=buffer_bps,
        )

        bid = entry_price * 1.002
        ask = entry_price * 1.003

        # _best_bid_ask reads exchange_client.reference_prices.get_orderbook_with_ts()
        # which returns a dict with bids/asks arrays
        mock_ref_prices = MagicMock()
        mock_ref_prices.get_orderbook_with_ts.return_value = (
            {"bids": [[str(bid), "1.0"]], "asks": [[str(ask), "1.0"]]},
            time.time(),
        )
        mock_ref_prices.get_reference_price.return_value = entry_price

        exchange_client = MagicMock()
        exchange_client.reference_prices = mock_ref_prices

        pos = _make_pos(
            side=side,
            entry_price=entry_price,
            size=1.0,
        )

        worker = PositionGuardWorker(
            exchange_client=exchange_client,
            position_manager=MagicMock(),
            config=config,
        )

        limit_price = worker._compute_tp_limit_price(pos)
        assert limit_price is not None, "TP limit price should be computable with valid bid/ask"

        if side == "long":
            # Long exit: sell at bid - buffer
            expected = bid * (1.0 - buffer_bps / 10000.0)
            assert abs(limit_price - expected) < entry_price * 0.001, (
                f"Long TP limit price {limit_price:.4f} should be near "
                f"bid({bid:.4f}) - buffer, expected ~{expected:.4f}"
            )
        else:
            # Short exit: buy at ask + buffer
            expected = ask * (1.0 + buffer_bps / 10000.0)
            assert abs(limit_price - expected) < entry_price * 0.001, (
                f"Short TP limit price {limit_price:.4f} should be near "
                f"ask({ask:.4f}) + buffer, expected ~{expected:.4f}"
            )

    @settings(max_examples=200)
    @given(
        fill_window_ms=st.integers(min_value=100, max_value=5000),
    )
    def test_fill_window_ms_stored_correctly(
        self,
        fill_window_ms: int,
    ):
        """Feature: scalping-pipeline-audit, Property 26: TP limit exit fill window

        The fill window configuration is correctly stored and accessible.
        """
        config = PositionGuardConfig(
            tp_limit_exit_enabled=True,
            tp_limit_fill_window_ms=fill_window_ms,
        )

        assert config.tp_limit_fill_window_ms == fill_window_ms
        # The fill window must be positive
        assert config.tp_limit_fill_window_ms > 0, (
            f"Fill window must be positive, got {config.tp_limit_fill_window_ms}"
        )
