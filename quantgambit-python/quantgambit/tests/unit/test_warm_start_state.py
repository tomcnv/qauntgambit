"""Unit tests for WarmStartState dataclass.

Feature: trading-pipeline-integration
Requirements: 3.5 - THE System SHALL validate that warm start state is consistent
              (positions match account equity)
Requirements: 3.6 - IF warm start state is stale (>5 minutes old) THEN the System
              SHALL warn the user and require confirmation
"""

from datetime import datetime, timedelta, timezone

import pytest

from quantgambit.integration.warm_start import WarmStartState


class TestWarmStartStateCreation:
    """Tests for WarmStartState creation and initialization."""
    
    def test_create_with_all_required_fields(self) -> None:
        """WarmStartState can be created with all required fields."""
        now = datetime.now(timezone.utc)
        
        state = WarmStartState(
            snapshot_time=now,
            positions=[
                {"symbol": "BTCUSDT", "size": 0.1, "entry_price": 50000.0}
            ],
            account_state={"equity": 10000.0, "margin": 500.0},
            recent_decisions=[],
            candle_history={
                "BTCUSDT": [
                    {"open": 50000, "high": 50100, "low": 49900, "close": 50050}
                ]
            },
            pipeline_state={"cooldown_until": None},
        )
        
        assert state.snapshot_time == now
        assert len(state.positions) == 1
        assert state.positions[0]["symbol"] == "BTCUSDT"
        assert state.account_state["equity"] == 10000.0
        assert len(state.recent_decisions) == 0
        assert "BTCUSDT" in state.candle_history
        assert state.pipeline_state["cooldown_until"] is None
    
    def test_create_with_minimal_fields(self) -> None:
        """WarmStartState can be created with minimal fields using defaults."""
        now = datetime.now(timezone.utc)
        
        state = WarmStartState(snapshot_time=now)
        
        assert state.snapshot_time == now
        assert state.positions == []
        assert state.account_state == {}
        assert state.recent_decisions == []
        assert state.candle_history == {}
        assert state.pipeline_state == {}
    
    def test_snapshot_time_without_timezone_gets_utc(self) -> None:
        """Snapshot time without timezone info gets UTC timezone added."""
        naive_time = datetime(2024, 1, 15, 12, 0, 0)
        
        state = WarmStartState(snapshot_time=naive_time)
        
        assert state.snapshot_time.tzinfo is not None
        assert state.snapshot_time.tzinfo == timezone.utc


class TestWarmStartStateIsStale:
    """Tests for WarmStartState.is_stale() method."""
    
    def test_is_stale_returns_true_when_older_than_max_age(self) -> None:
        """is_stale() returns True when snapshot_time is older than max_age_sec.
        
        Requirements: 3.6
        """
        # Create a snapshot from 10 minutes ago
        old_time = datetime.now(timezone.utc) - timedelta(minutes=10)
        state = WarmStartState(
            snapshot_time=old_time,
            account_state={"equity": 10000.0},
        )
        
        # Default max_age_sec is 300 (5 minutes)
        assert state.is_stale() is True
    
    def test_is_stale_returns_false_when_within_max_age(self) -> None:
        """is_stale() returns False when snapshot_time is within max_age_sec.
        
        Requirements: 3.6
        """
        # Create a snapshot from 2 minutes ago
        recent_time = datetime.now(timezone.utc) - timedelta(minutes=2)
        state = WarmStartState(
            snapshot_time=recent_time,
            account_state={"equity": 10000.0},
        )
        
        # Default max_age_sec is 300 (5 minutes)
        assert state.is_stale() is False
    
    def test_is_stale_with_custom_max_age(self) -> None:
        """is_stale() respects custom max_age_sec parameter.
        
        Requirements: 3.6
        """
        # Create a snapshot from 10 minutes ago
        old_time = datetime.now(timezone.utc) - timedelta(minutes=10)
        state = WarmStartState(
            snapshot_time=old_time,
            account_state={"equity": 10000.0},
        )
        
        # With 15 minute threshold, should not be stale
        assert state.is_stale(max_age_sec=900) is False
        
        # With 5 minute threshold, should be stale
        assert state.is_stale(max_age_sec=300) is True
    
    def test_is_stale_at_exact_boundary(self) -> None:
        """is_stale() returns False at exactly max_age_sec boundary."""
        # Create a snapshot from exactly 5 minutes ago
        boundary_time = datetime.now(timezone.utc) - timedelta(seconds=300)
        state = WarmStartState(
            snapshot_time=boundary_time,
            account_state={"equity": 10000.0},
        )
        
        # At exactly the boundary, should not be stale (age <= max_age)
        # Due to timing, we use a slightly larger threshold
        assert state.is_stale(max_age_sec=301) is False
    
    def test_is_stale_with_naive_snapshot_time(self) -> None:
        """is_stale() handles naive datetime by treating as UTC."""
        # Create with naive datetime that represents UTC time
        # We use utcnow() to get a naive datetime that represents UTC
        # When converted to aware UTC, it should still be 10 minutes old
        naive_old_time = datetime.utcnow() - timedelta(minutes=10)
        state = WarmStartState(snapshot_time=naive_old_time)
        
        # Should still correctly detect staleness
        assert state.is_stale() is True


class TestWarmStartStateValidate:
    """Tests for WarmStartState.validate() method."""
    
    def test_validate_returns_true_for_valid_state(self) -> None:
        """validate() returns (True, []) for valid state.
        
        Requirements: 3.5
        """
        state = WarmStartState(
            snapshot_time=datetime.now(timezone.utc),
            positions=[
                {"symbol": "BTCUSDT", "size": 0.1, "entry_price": 50000.0}
            ],
            account_state={"equity": 10000.0},
        )
        
        valid, errors = state.validate()
        
        assert valid is True
        assert errors == []
    
    def test_validate_returns_false_when_position_value_exceeds_10x_equity(self) -> None:
        """validate() returns (False, [errors]) when position value exceeds 10x equity.
        
        Requirements: 3.5
        """
        # Position value: 100 * 50000 = 5,000,000
        # Equity: 1000
        # Ratio: 5000x (exceeds 10x limit)
        state = WarmStartState(
            snapshot_time=datetime.now(timezone.utc),
            positions=[
                {"symbol": "BTCUSDT", "size": 100, "entry_price": 50000.0}
            ],
            account_state={"equity": 1000.0},
        )
        
        valid, errors = state.validate()
        
        assert valid is False
        assert len(errors) == 1
        assert "Position value" in errors[0]
        assert "exceeds" in errors[0]
        assert "10" in errors[0]  # 10x
    
    def test_validate_returns_false_when_equity_is_missing(self) -> None:
        """validate() returns (False, [errors]) when equity is missing.
        
        Requirements: 3.5
        """
        state = WarmStartState(
            snapshot_time=datetime.now(timezone.utc),
            positions=[],
            account_state={},  # No equity
        )
        
        valid, errors = state.validate()
        
        assert valid is False
        assert len(errors) == 1
        assert "Missing equity" in errors[0]
    
    def test_validate_returns_false_when_equity_is_zero(self) -> None:
        """validate() returns (False, [errors]) when equity is zero."""
        state = WarmStartState(
            snapshot_time=datetime.now(timezone.utc),
            positions=[],
            account_state={"equity": 0},
        )
        
        valid, errors = state.validate()
        
        assert valid is False
        assert "Missing equity" in errors[0]
    
    def test_validate_returns_false_when_equity_is_none(self) -> None:
        """validate() returns (False, [errors]) when equity is None."""
        state = WarmStartState(
            snapshot_time=datetime.now(timezone.utc),
            positions=[],
            account_state={"equity": None},
        )
        
        valid, errors = state.validate()
        
        assert valid is False
        assert "Missing equity" in errors[0]
    
    def test_validate_with_multiple_positions(self) -> None:
        """validate() correctly sums position values across multiple positions."""
        # Total position value: (0.1 * 50000) + (1.0 * 3000) = 5000 + 3000 = 8000
        # Equity: 10000
        # Ratio: 0.8x (within 10x limit)
        state = WarmStartState(
            snapshot_time=datetime.now(timezone.utc),
            positions=[
                {"symbol": "BTCUSDT", "size": 0.1, "entry_price": 50000.0},
                {"symbol": "ETHUSDT", "size": 1.0, "entry_price": 3000.0},
            ],
            account_state={"equity": 10000.0},
        )
        
        valid, errors = state.validate()
        
        assert valid is True
        assert errors == []
    
    def test_validate_with_negative_position_size(self) -> None:
        """validate() uses absolute value for position sizes (short positions)."""
        # Position value: abs(-0.1) * 50000 = 5000
        # Equity: 10000
        # Ratio: 0.5x (within 10x limit)
        state = WarmStartState(
            snapshot_time=datetime.now(timezone.utc),
            positions=[
                {"symbol": "BTCUSDT", "size": -0.1, "entry_price": 50000.0}
            ],
            account_state={"equity": 10000.0},
        )
        
        valid, errors = state.validate()
        
        assert valid is True
        assert errors == []
    
    def test_validate_with_empty_positions(self) -> None:
        """validate() passes with empty positions and valid equity."""
        state = WarmStartState(
            snapshot_time=datetime.now(timezone.utc),
            positions=[],
            account_state={"equity": 10000.0},
        )
        
        valid, errors = state.validate()
        
        assert valid is True
        assert errors == []
    
    def test_validate_with_missing_position_fields(self) -> None:
        """validate() handles positions with missing size or entry_price."""
        state = WarmStartState(
            snapshot_time=datetime.now(timezone.utc),
            positions=[
                {"symbol": "BTCUSDT"},  # Missing size and entry_price
                {"symbol": "ETHUSDT", "size": 1.0},  # Missing entry_price
            ],
            account_state={"equity": 10000.0},
        )
        
        # Should not raise, missing fields default to 0
        valid, errors = state.validate()
        
        assert valid is True
        assert errors == []


class TestWarmStartStateHelperMethods:
    """Tests for WarmStartState helper methods."""
    
    def test_get_age_seconds(self) -> None:
        """get_age_seconds() returns correct age."""
        old_time = datetime.now(timezone.utc) - timedelta(seconds=120)
        state = WarmStartState(snapshot_time=old_time)
        
        age = state.get_age_seconds()
        
        # Allow some tolerance for test execution time
        assert 119 <= age <= 125
    
    def test_get_position_count(self) -> None:
        """get_position_count() returns correct count."""
        state = WarmStartState(
            snapshot_time=datetime.now(timezone.utc),
            positions=[
                {"symbol": "BTCUSDT", "size": 0.1, "entry_price": 50000.0},
                {"symbol": "ETHUSDT", "size": 1.0, "entry_price": 3000.0},
            ],
        )
        
        assert state.get_position_count() == 2
    
    def test_get_total_position_value(self) -> None:
        """get_total_position_value() returns correct sum."""
        state = WarmStartState(
            snapshot_time=datetime.now(timezone.utc),
            positions=[
                {"symbol": "BTCUSDT", "size": 0.1, "entry_price": 50000.0},
                {"symbol": "ETHUSDT", "size": -1.0, "entry_price": 3000.0},
            ],
        )
        
        # abs(0.1 * 50000) + abs(-1.0 * 3000) = 5000 + 3000 = 8000
        assert state.get_total_position_value() == 8000.0
    
    def test_get_symbols_with_positions(self) -> None:
        """get_symbols_with_positions() returns unique symbols."""
        state = WarmStartState(
            snapshot_time=datetime.now(timezone.utc),
            positions=[
                {"symbol": "BTCUSDT", "size": 0.1, "entry_price": 50000.0},
                {"symbol": "ETHUSDT", "size": 1.0, "entry_price": 3000.0},
                {"symbol": "BTCUSDT", "size": 0.2, "entry_price": 51000.0},
            ],
        )
        
        symbols = state.get_symbols_with_positions()
        
        assert set(symbols) == {"BTCUSDT", "ETHUSDT"}
    
    def test_has_candle_history_for_positions_true(self) -> None:
        """has_candle_history_for_positions() returns True when all covered."""
        state = WarmStartState(
            snapshot_time=datetime.now(timezone.utc),
            positions=[
                {"symbol": "BTCUSDT", "size": 0.1, "entry_price": 50000.0},
            ],
            candle_history={
                "BTCUSDT": [{"open": 50000, "close": 50100}],
            },
        )
        
        assert state.has_candle_history_for_positions() is True
    
    def test_has_candle_history_for_positions_false(self) -> None:
        """has_candle_history_for_positions() returns False when missing."""
        state = WarmStartState(
            snapshot_time=datetime.now(timezone.utc),
            positions=[
                {"symbol": "BTCUSDT", "size": 0.1, "entry_price": 50000.0},
                {"symbol": "ETHUSDT", "size": 1.0, "entry_price": 3000.0},
            ],
            candle_history={
                "BTCUSDT": [{"open": 50000, "close": 50100}],
                # Missing ETHUSDT
            },
        )
        
        assert state.has_candle_history_for_positions() is False


class TestWarmStartStateSerialization:
    """Tests for WarmStartState serialization methods."""
    
    def test_to_dict(self) -> None:
        """to_dict() returns correct dictionary representation."""
        now = datetime.now(timezone.utc)
        state = WarmStartState(
            snapshot_time=now,
            positions=[{"symbol": "BTCUSDT", "size": 0.1, "entry_price": 50000.0}],
            account_state={"equity": 10000.0},
            recent_decisions=[],
            candle_history={"BTCUSDT": [{"open": 50000}]},
            pipeline_state={"cooldown": False},
        )
        
        data = state.to_dict()
        
        assert data["snapshot_time"] == now.isoformat()
        assert data["positions"] == [{"symbol": "BTCUSDT", "size": 0.1, "entry_price": 50000.0}]
        assert data["account_state"] == {"equity": 10000.0}
        assert data["recent_decisions"] == []
        assert data["candle_history"] == {"BTCUSDT": [{"open": 50000}]}
        assert data["pipeline_state"] == {"cooldown": False}
    
    def test_from_dict(self) -> None:
        """from_dict() creates correct WarmStartState from dictionary."""
        now = datetime.now(timezone.utc)
        data = {
            "snapshot_time": now.isoformat(),
            "positions": [{"symbol": "BTCUSDT", "size": 0.1, "entry_price": 50000.0}],
            "account_state": {"equity": 10000.0},
            "recent_decisions": [],
            "candle_history": {"BTCUSDT": [{"open": 50000}]},
            "pipeline_state": {"cooldown": False},
        }
        
        state = WarmStartState.from_dict(data)
        
        assert state.snapshot_time.replace(microsecond=0) == now.replace(microsecond=0)
        assert state.positions == [{"symbol": "BTCUSDT", "size": 0.1, "entry_price": 50000.0}]
        assert state.account_state == {"equity": 10000.0}
        assert state.recent_decisions == []
        assert state.candle_history == {"BTCUSDT": [{"open": 50000}]}
        assert state.pipeline_state == {"cooldown": False}
    
    def test_round_trip_serialization(self) -> None:
        """to_dict() and from_dict() round-trip correctly."""
        now = datetime.now(timezone.utc)
        original = WarmStartState(
            snapshot_time=now,
            positions=[{"symbol": "BTCUSDT", "size": 0.1, "entry_price": 50000.0}],
            account_state={"equity": 10000.0, "margin": 500.0},
            recent_decisions=[],
            candle_history={"BTCUSDT": [{"open": 50000, "close": 50100}]},
            pipeline_state={"cooldown": False, "hysteresis": 0.5},
        )
        
        data = original.to_dict()
        restored = WarmStartState.from_dict(data)
        
        assert restored.positions == original.positions
        assert restored.account_state == original.account_state
        assert restored.candle_history == original.candle_history
        assert restored.pipeline_state == original.pipeline_state


class TestWarmStartStateJsonSerialization:
    """Tests for WarmStartState JSON serialization methods.
    
    Feature: trading-pipeline-integration
    Requirements: 8.5 - State export format is JSON-serializable
    """
    
    def test_to_json_returns_valid_json_string(self) -> None:
        """to_json() returns a valid JSON string.
        
        Requirements: 8.5
        """
        import json
        
        now = datetime.now(timezone.utc)
        state = WarmStartState(
            snapshot_time=now,
            positions=[{"symbol": "BTCUSDT", "size": 0.1, "entry_price": 50000.0}],
            account_state={"equity": 10000.0},
            recent_decisions=[],
            candle_history={"BTCUSDT": [{"open": 50000, "close": 50100}]},
            pipeline_state={"cooldown": False},
        )
        
        json_str = state.to_json()
        
        assert isinstance(json_str, str)
        # Should be valid JSON
        parsed = json.loads(json_str)
        assert isinstance(parsed, dict)
    
    def test_to_json_includes_all_fields(self) -> None:
        """to_json() includes all WarmStartState fields.
        
        Requirements: 8.5
        """
        import json
        
        now = datetime.now(timezone.utc)
        state = WarmStartState(
            snapshot_time=now,
            positions=[{"symbol": "BTCUSDT", "size": 0.1, "entry_price": 50000.0}],
            account_state={"equity": 10000.0, "margin": 500.0},
            recent_decisions=[],
            candle_history={"BTCUSDT": [{"open": 50000, "close": 50100}]},
            pipeline_state={"cooldown": False, "hysteresis": 0.5},
        )
        
        json_str = state.to_json()
        parsed = json.loads(json_str)
        
        assert "snapshot_time" in parsed
        assert "positions" in parsed
        assert "account_state" in parsed
        assert "recent_decisions" in parsed
        assert "candle_history" in parsed
        assert "pipeline_state" in parsed
    
    def test_to_json_serializes_datetime_as_iso_format(self) -> None:
        """to_json() serializes datetime as ISO format string.
        
        Requirements: 8.5
        """
        import json
        
        now = datetime(2024, 1, 15, 12, 30, 45, tzinfo=timezone.utc)
        state = WarmStartState(
            snapshot_time=now,
            account_state={"equity": 10000.0},
        )
        
        json_str = state.to_json()
        parsed = json.loads(json_str)
        
        assert "2024-01-15" in parsed["snapshot_time"]
        assert "12:30:45" in parsed["snapshot_time"]
    
    def test_to_json_handles_candle_history_with_datetime(self) -> None:
        """to_json() handles candle_history with datetime values.
        
        Requirements: 8.5
        """
        import json
        
        now = datetime.now(timezone.utc)
        candle_time = datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
        
        state = WarmStartState(
            snapshot_time=now,
            account_state={"equity": 10000.0},
            candle_history={
                "BTCUSDT": [
                    {"ts": candle_time, "open": 50000, "close": 50100}
                ]
            },
        )
        
        json_str = state.to_json()
        parsed = json.loads(json_str)
        
        # Should serialize datetime in candle_history
        assert "2024-01-15" in parsed["candle_history"]["BTCUSDT"][0]["ts"]
    
    def test_from_json_creates_warm_start_state(self) -> None:
        """from_json() creates a WarmStartState from JSON string.
        
        Requirements: 8.5
        """
        json_str = '''{
            "snapshot_time": "2024-01-15T12:00:00+00:00",
            "positions": [{"symbol": "BTCUSDT", "size": 0.1, "entry_price": 50000.0}],
            "account_state": {"equity": 10000.0},
            "recent_decisions": [],
            "candle_history": {"BTCUSDT": [{"open": 50000, "close": 50100}]},
            "pipeline_state": {"cooldown": false}
        }'''
        
        state = WarmStartState.from_json(json_str)
        
        assert isinstance(state, WarmStartState)
        assert state.snapshot_time.year == 2024
        assert state.snapshot_time.month == 1
        assert state.snapshot_time.day == 15
        assert state.positions == [{"symbol": "BTCUSDT", "size": 0.1, "entry_price": 50000.0}]
        assert state.account_state == {"equity": 10000.0}
    
    def test_json_round_trip(self) -> None:
        """to_json() and from_json() round-trip correctly.
        
        Requirements: 8.5
        """
        now = datetime.now(timezone.utc)
        original = WarmStartState(
            snapshot_time=now,
            positions=[{"symbol": "BTCUSDT", "size": 0.1, "entry_price": 50000.0}],
            account_state={"equity": 10000.0, "margin": 500.0},
            recent_decisions=[],
            candle_history={"BTCUSDT": [{"open": 50000, "close": 50100}]},
            pipeline_state={"cooldown": False, "hysteresis": 0.5},
        )
        
        json_str = original.to_json()
        restored = WarmStartState.from_json(json_str)
        
        assert restored.positions == original.positions
        assert restored.account_state == original.account_state
        assert restored.candle_history == original.candle_history
        assert restored.pipeline_state == original.pipeline_state
    
    def test_to_json_with_empty_state(self) -> None:
        """to_json() works with minimal/empty state.
        
        Requirements: 8.5
        """
        import json
        
        now = datetime.now(timezone.utc)
        state = WarmStartState(snapshot_time=now)
        
        json_str = state.to_json()
        parsed = json.loads(json_str)
        
        assert parsed["positions"] == []
        assert parsed["account_state"] == {}
        assert parsed["recent_decisions"] == []
        assert parsed["candle_history"] == {}
        assert parsed["pipeline_state"] == {}
