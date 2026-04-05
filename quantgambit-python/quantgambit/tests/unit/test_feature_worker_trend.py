from collections import deque

from quantgambit.signals.feature_worker import (
    _trend_direction,
    _ema_step,
    _trend_strength,
    _session_key,
    _is_market_hours,
    _should_emit_orderbook,
)
from quantgambit.features.candle_indicators import VWAPState


def test_trend_direction_uses_ema():
    ema_fast = 101.0
    ema_slow = 100.0
    direction = _trend_direction(0.0, 0.0, ema_fast, ema_slow)
    assert direction == "up"


def test_ema_step_increases_toward_price():
    ema = _ema_step(100.0, 110.0, period=10)
    assert ema > 100.0


def test_trend_strength_zero_without_price():
    strength = _trend_strength(100.0, 100.0, None)
    assert strength == 0.0


def test_vwap_resets_on_new_session():
    state = VWAPState()
    first = state.update(100.0, 1.0, session_key="utc:1")
    second = state.update(110.0, 1.0, session_key="utc:2")
    assert first != second
    assert state.sum_volume == 1.0


def test_session_key_respects_start_hour():
    key1 = _session_key(3600, session_start_hour_utc=2)
    key2 = _session_key(3600 * 25, session_start_hour_utc=2)
    assert key1 != key2


def test_market_hours_wraps_midnight():
    assert _is_market_hours(23 * 3600, start_hour=22, end_hour=2) is True
    assert _is_market_hours(12 * 3600, start_hour=22, end_hour=2) is False


def test_orderbook_emit_rate_limit():
    last_emit = {}
    tick_count = {}
    tick_count["BTC"] = 1
    assert _should_emit_orderbook("BTC", 100.0, last_emit, tick_count, 500, 3) is False
    tick_count["BTC"] = 2
    assert _should_emit_orderbook("BTC", 100.1, last_emit, tick_count, 500, 3) is False
    tick_count["BTC"] = 3
    assert _should_emit_orderbook("BTC", 100.6, last_emit, tick_count, 500, 3) is True
