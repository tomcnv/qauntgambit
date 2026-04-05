from quantgambit.signals.decision_worker import WarmupTracker


def test_warmup_tracker_requires_samples_and_age():
    tracker = WarmupTracker(min_samples=3, min_age_sec=10.0)
    tracker.min_candles = 2
    assert tracker.record("BTC", 100.0, 0)[0] is False
    assert tracker.record("BTC", 105.0, 1)[0] is False
    assert tracker.record("BTC", 109.0, 1)[0] is False
    assert tracker.record("BTC", 111.0, 2)[0] is True
