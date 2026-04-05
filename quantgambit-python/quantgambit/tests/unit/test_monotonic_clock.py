from quantgambit.ingest.monotonic_clock import MonotonicClock


def test_monotonic_clock_adjusts_and_tracks_metrics() -> None:
    clock = MonotonicClock(epsilon_us=1)
    first = clock.update("BTCUSDT", 100)
    second = clock.update("BTCUSDT", 99)
    assert second > first
    metrics = clock.metrics("BTCUSDT")
    assert metrics.adjustments_count == 1
    assert metrics.total_drift_us == (second - 99)
    assert metrics.max_adjustment_us == metrics.total_drift_us
