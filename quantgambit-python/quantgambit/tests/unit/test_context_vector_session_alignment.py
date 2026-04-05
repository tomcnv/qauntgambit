from datetime import datetime, timezone

from quantgambit.deeptrader_core.profiles.context_vector import ContextVectorInput, build_context_vector


def _ts(hour: int, minute: int = 0) -> float:
    dt = datetime(2026, 2, 25, hour, minute, 0, tzinfo=timezone.utc)
    return dt.timestamp()


def test_build_context_vector_derives_us_at_12_utc():
    cv = build_context_vector(
        ContextVectorInput(
            symbol="BTCUSDT",
            timestamp=_ts(12, 0),
            price=100.0,
        )
    )
    assert cv.hour_utc == 12
    assert cv.session == "us"


def test_build_context_vector_normalizes_mismatched_supplied_session_and_hour():
    cv = build_context_vector(
        ContextVectorInput(
            symbol="BTCUSDT",
            timestamp=_ts(12, 30),
            price=100.0,
            session="europe",  # intentionally inconsistent
            hour_utc=12,
        )
    )
    assert cv.hour_utc == 12
    assert cv.session == "us"

