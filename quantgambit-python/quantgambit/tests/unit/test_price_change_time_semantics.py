from collections import deque

from quantgambit.signals.feature_worker import _price_change


def test_price_change_uses_last_price_at_or_before_cutoff():
    history = deque()
    # timestamps in microseconds: 0s, 5s, 10s
    history.append((0, 100.0))
    history.append((5_000_000, 110.0))
    history.append((10_000_000, 130.0))
    now_ts_us = 12_000_000
    # horizon 5s -> cutoff at 7s, so use price at 5s (110.0)
    change = _price_change(history, 5.0, 120.0, now_ts_us)
    assert round(change, 6) == round((120.0 - 110.0) / 110.0, 6)


def test_price_change_includes_boundary_timestamp():
    history = deque()
    history.append((5_000_000, 100.0))
    now_ts_us = 10_000_000
    # cutoff exactly 5s -> should include 5s price
    change = _price_change(history, 5.0, 110.0, now_ts_us)
    assert round(change, 6) == round((110.0 - 100.0) / 100.0, 6)
