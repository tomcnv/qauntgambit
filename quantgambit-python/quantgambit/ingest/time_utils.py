"""Time utilities for canonical timestamp handling in ingestion."""

from __future__ import annotations

from typing import Optional, Tuple
import time

_future_event_excluded_count = 0


def now_recv_us() -> int:
    """Return receive time in microseconds (int)."""
    return int(time.time() * 1_000_000)


def sec_to_us(seconds: float) -> int:
    """Convert seconds float to integer microseconds."""
    return int(round(seconds * 1_000_000))


def ms_to_us(milliseconds: int) -> int:
    """Convert milliseconds int to integer microseconds."""
    return int(milliseconds) * 1000


def us_to_sec(microseconds: int) -> float:
    """Convert microseconds int to float seconds."""
    return float(microseconds) / 1_000_000.0


def in_window_us(ts_us: int, now_us: int, window_us: int) -> bool:
    """Return True when ts_us is within [now_us - window_us, now_us]."""
    global _future_event_excluded_count
    if ts_us > now_us:
        _future_event_excluded_count += 1
        return False
    return (now_us - window_us) <= ts_us <= now_us


def consume_future_event_excluded_count() -> int:
    """Return and reset the future-event exclusion counter."""
    global _future_event_excluded_count
    count = _future_event_excluded_count
    _future_event_excluded_count = 0
    return count


def normalize_exchange_ts_to_sec(raw_ts: Optional[object]) -> Optional[float]:
    """Normalize exchange timestamp to float seconds.

    Returns None when parsing fails. If the timestamp looks like milliseconds,
    it will be converted to seconds.
    """
    if raw_ts is None:
        return None
    try:
        ts_val = float(raw_ts)
    except (TypeError, ValueError):
        return None
    if ts_val > 10_000_000_000:  # ms epoch
        ts_val = ts_val / 1000.0
    return ts_val


def resolve_exchange_timestamp(
    raw_ts: Optional[object],
    recv_ts_sec: float,
    max_skew_sec: float,
) -> Tuple[Optional[float], bool, Optional[float]]:
    """Resolve exchange timestamp and detect skew vs receive time (seconds)."""
    exchange_ts = normalize_exchange_ts_to_sec(raw_ts)
    if exchange_ts is None:
        return None, False, None
    skew_sec = abs(recv_ts_sec - exchange_ts)
    if max_skew_sec > 0 and skew_sec > max_skew_sec:
        return exchange_ts, True, skew_sec
    return exchange_ts, False, skew_sec
