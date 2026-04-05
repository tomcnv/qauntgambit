from datetime import datetime, timezone

from quantgambit.signals.feature_worker import _session_label


def _ts(hour: int, minute: int = 0) -> float:
    dt = datetime(2025, 11, 20, hour, minute, 0, tzinfo=timezone.utc)
    return dt.timestamp()


def test_session_label_matches_canonical_classifier_boundaries():
    # These boundaries are defined by deeptrader_core.profiles.profile_classifier.classify_session
    assert _session_label(_ts(6, 59)) == "asia"
    assert _session_label(_ts(7, 0)) == "europe"
    assert _session_label(_ts(11, 59)) == "europe"
    assert _session_label(_ts(12, 0)) == "us"
    assert _session_label(_ts(21, 59)) == "us"
    assert _session_label(_ts(22, 0)) == "overnight"

