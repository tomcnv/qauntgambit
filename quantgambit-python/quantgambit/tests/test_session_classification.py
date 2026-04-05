"""
Session Classification Unit Tests

Tests that classify_session() correctly maps UTC hours to trading sessions:
- Asia: 0-6 UTC (0 <= h < 7)
- Europe: 7-11 UTC (7 <= h < 12)
- US: 12-21 UTC (12 <= h < 22)
- Overnight: 22-23 UTC (h >= 22)

Requirements: US-2 (AC2.1, AC2.4)
"""

import pytest
from datetime import datetime, timezone
from quantgambit.deeptrader_core.profiles.profile_classifier import classify_session


def _make_timestamp(hour: int, minute: int = 0) -> float:
    """Create a UTC timestamp for a specific hour and minute."""
    dt = datetime(2025, 11, 20, hour, minute, 0, tzinfo=timezone.utc)
    return dt.timestamp()


class TestSessionClassification:
    """Tests for classify_session() function."""

    # -------------------------------------------------------------------------
    # Asia Session Tests (0-6 UTC)
    # -------------------------------------------------------------------------
    
    def test_classify_session_asia_hour_0(self):
        """Test hour 0 UTC returns 'asia'."""
        timestamp = _make_timestamp(hour=0)
        assert classify_session(timestamp) == "asia"

    def test_classify_session_asia_hour_3(self):
        """Test hour 3 UTC (middle of Asia session) returns 'asia'."""
        timestamp = _make_timestamp(hour=3)
        assert classify_session(timestamp) == "asia"

    def test_classify_session_asia_hour_6(self):
        """Test hour 6 UTC (last hour of Asia session) returns 'asia'."""
        timestamp = _make_timestamp(hour=6)
        assert classify_session(timestamp) == "asia"

    # -------------------------------------------------------------------------
    # Europe Session Tests (7-11 UTC)
    # -------------------------------------------------------------------------
    
    def test_classify_session_europe_hour_7(self):
        """Test hour 7 UTC (first hour of Europe session) returns 'europe'."""
        timestamp = _make_timestamp(hour=7)
        assert classify_session(timestamp) == "europe"

    def test_classify_session_europe_hour_9(self):
        """Test hour 9 UTC (middle of Europe session) returns 'europe'."""
        timestamp = _make_timestamp(hour=9)
        assert classify_session(timestamp) == "europe"

    def test_classify_session_europe_hour_11(self):
        """Test hour 11 UTC (last hour of Europe session) returns 'europe'."""
        timestamp = _make_timestamp(hour=11)
        assert classify_session(timestamp) == "europe"

    # -------------------------------------------------------------------------
    # US Session Tests (12-21 UTC)
    # -------------------------------------------------------------------------
    
    def test_classify_session_us_hour_12(self):
        """Test hour 12 UTC (first hour of US session) returns 'us'."""
        timestamp = _make_timestamp(hour=12)
        assert classify_session(timestamp) == "us"

    def test_classify_session_us_hour_15(self):
        """Test hour 15 UTC (middle of US session) returns 'us'."""
        timestamp = _make_timestamp(hour=15)
        assert classify_session(timestamp) == "us"

    def test_classify_session_us_hour_20(self):
        """Test hour 20 UTC returns 'us' (this was the bug - overnight_thin was selected here)."""
        timestamp = _make_timestamp(hour=20)
        assert classify_session(timestamp) == "us"

    def test_classify_session_us_hour_21(self):
        """Test hour 21 UTC (last hour of US session) returns 'us'."""
        timestamp = _make_timestamp(hour=21)
        assert classify_session(timestamp) == "us"

    # -------------------------------------------------------------------------
    # Overnight Session Tests (22-23 UTC)
    # -------------------------------------------------------------------------
    
    def test_classify_session_overnight_hour_22(self):
        """Test hour 22 UTC (first hour of overnight session) returns 'overnight'."""
        timestamp = _make_timestamp(hour=22)
        assert classify_session(timestamp) == "overnight"

    def test_classify_session_overnight_hour_23(self):
        """Test hour 23 UTC (last hour of overnight session) returns 'overnight'."""
        timestamp = _make_timestamp(hour=23)
        assert classify_session(timestamp) == "overnight"

    # -------------------------------------------------------------------------
    # Boundary Condition Tests (exact hour transitions)
    # -------------------------------------------------------------------------
    
    def test_boundary_asia_to_europe_6_59(self):
        """Test 6:59 UTC is still 'asia' (just before Europe transition)."""
        timestamp = _make_timestamp(hour=6, minute=59)
        assert classify_session(timestamp) == "asia"

    def test_boundary_asia_to_europe_7_00(self):
        """Test 7:00 UTC is 'europe' (exact transition from Asia)."""
        timestamp = _make_timestamp(hour=7, minute=0)
        assert classify_session(timestamp) == "europe"

    def test_boundary_europe_to_us_11_59(self):
        """Test 11:59 UTC is still 'europe' (just before US transition)."""
        timestamp = _make_timestamp(hour=11, minute=59)
        assert classify_session(timestamp) == "europe"

    def test_boundary_europe_to_us_12_00(self):
        """Test 12:00 UTC is 'us' (exact transition from Europe)."""
        timestamp = _make_timestamp(hour=12, minute=0)
        assert classify_session(timestamp) == "us"

    def test_boundary_us_to_overnight_21_59(self):
        """Test 21:59 UTC is still 'us' (just before overnight transition)."""
        timestamp = _make_timestamp(hour=21, minute=59)
        assert classify_session(timestamp) == "us"

    def test_boundary_us_to_overnight_22_00(self):
        """Test 22:00 UTC is 'overnight' (exact transition from US)."""
        timestamp = _make_timestamp(hour=22, minute=0)
        assert classify_session(timestamp) == "overnight"

    def test_boundary_overnight_to_asia_23_59(self):
        """Test 23:59 UTC is still 'overnight' (just before Asia transition)."""
        timestamp = _make_timestamp(hour=23, minute=59)
        assert classify_session(timestamp) == "overnight"

    def test_boundary_overnight_to_asia_0_00(self):
        """Test 0:00 UTC is 'asia' (exact transition from overnight)."""
        timestamp = _make_timestamp(hour=0, minute=0)
        assert classify_session(timestamp) == "asia"

