"""Unit tests for RecordedDecision dataclass.

Feature: trading-pipeline-integration
Requirements: 2.1, 2.3, 2.5
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from quantgambit.integration.decision_recording import RecordedDecision


class TestRecordedDecisionCreation:
    """Tests for RecordedDecision creation and validation."""
    
    @pytest.fixture
    def sample_decision(self):
        """Create a sample RecordedDecision."""
        return RecordedDecision(
            decision_id="dec_test123456",
            timestamp=datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc),
            symbol="BTCUSDT",
            config_version="v1_abc123",
            market_snapshot={"mid_price": 50000.0, "spread_bps": 1.5},
            features={"volatility": 0.02, "trend": 0.5},
            positions=[{"symbol": "BTCUSDT", "size": 0.1, "entry_price": 49000.0}],
            account_state={"equity": 10000.0, "margin_used": 500.0},
            stage_results=[
                {"stage": "data_readiness", "passed": True},
                {"stage": "ev_gate", "passed": True, "ev": 0.05},
            ],
            rejection_stage=None,
            rejection_reason=None,
            decision="accepted",
            signal={"side": "buy", "size": 0.05, "entry": 50000.0},
            profile_id="aggressive",
        )
    
    def test_basic_creation(self, sample_decision):
        """RecordedDecision should be created with all fields."""
        assert sample_decision.decision_id == "dec_test123456"
        assert sample_decision.symbol == "BTCUSDT"
        assert sample_decision.config_version == "v1_abc123"
        assert sample_decision.decision == "accepted"
        assert sample_decision.profile_id == "aggressive"
    
    def test_creation_with_minimal_fields(self):
        """RecordedDecision should work with minimal required fields."""
        decision = RecordedDecision(
            decision_id="dec_minimal",
            timestamp=datetime.now(timezone.utc),
            symbol="ETHUSDT",
            config_version="v1",
            decision="rejected",
        )
        
        assert decision.decision_id == "dec_minimal"
        assert decision.market_snapshot == {}
        assert decision.features == {}
        assert decision.positions == []
        assert decision.account_state == {}
        assert decision.stage_results == []
        assert decision.signal is None
    
    def test_creation_rejected_decision(self):
        """RecordedDecision should capture rejection details."""
        decision = RecordedDecision(
            decision_id="dec_rejected",
            timestamp=datetime.now(timezone.utc),
            symbol="BTCUSDT",
            config_version="v1",
            decision="rejected",
            rejection_stage="ev_gate",
            rejection_reason="EV below threshold: -0.02 < 0.01",
        )
        
        assert decision.decision == "rejected"
        assert decision.rejection_stage == "ev_gate"
        assert decision.rejection_reason == "EV below threshold: -0.02 < 0.01"
    
    def test_creation_shadow_decision(self):
        """RecordedDecision should support shadow decisions."""
        decision = RecordedDecision(
            decision_id="dec_shadow",
            timestamp=datetime.now(timezone.utc),
            symbol="BTCUSDT",
            config_version="v1",
            decision="shadow",
        )
        
        assert decision.decision == "shadow"
        assert decision.is_shadow()


class TestRecordedDecisionValidation:
    """Tests for RecordedDecision validation."""
    
    def test_empty_decision_id_raises(self):
        """Empty decision_id should raise ValueError."""
        with pytest.raises(ValueError) as exc_info:
            RecordedDecision(
                decision_id="",
                timestamp=datetime.now(timezone.utc),
                symbol="BTCUSDT",
                config_version="v1",
                decision="accepted",
            )
        
        assert "decision_id cannot be empty" in str(exc_info.value)
    
    def test_empty_symbol_raises(self):
        """Empty symbol should raise ValueError."""
        with pytest.raises(ValueError) as exc_info:
            RecordedDecision(
                decision_id="dec_test",
                timestamp=datetime.now(timezone.utc),
                symbol="",
                config_version="v1",
                decision="accepted",
            )
        
        assert "symbol cannot be empty" in str(exc_info.value)
    
    def test_empty_config_version_raises(self):
        """Empty config_version should raise ValueError."""
        with pytest.raises(ValueError) as exc_info:
            RecordedDecision(
                decision_id="dec_test",
                timestamp=datetime.now(timezone.utc),
                symbol="BTCUSDT",
                config_version="",
                decision="accepted",
            )
        
        assert "config_version cannot be empty" in str(exc_info.value)
    
    def test_invalid_decision_raises(self):
        """Invalid decision value should raise ValueError."""
        with pytest.raises(ValueError) as exc_info:
            RecordedDecision(
                decision_id="dec_test",
                timestamp=datetime.now(timezone.utc),
                symbol="BTCUSDT",
                config_version="v1",
                decision="invalid",
            )
        
        assert "decision must be 'accepted', 'rejected', or 'shadow'" in str(exc_info.value)
    
    def test_naive_timestamp_gets_utc(self):
        """Naive timestamp should be converted to UTC."""
        naive_ts = datetime(2024, 1, 15, 12, 0, 0)
        
        decision = RecordedDecision(
            decision_id="dec_test",
            timestamp=naive_ts,
            symbol="BTCUSDT",
            config_version="v1",
            decision="accepted",
        )
        
        assert decision.timestamp.tzinfo is not None
        assert decision.timestamp.tzinfo == timezone.utc


class TestRecordedDecisionSerialization:
    """Tests for RecordedDecision serialization methods."""
    
    @pytest.fixture
    def sample_decision(self):
        """Create a sample RecordedDecision."""
        return RecordedDecision(
            decision_id="dec_test123456",
            timestamp=datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc),
            symbol="BTCUSDT",
            config_version="v1_abc123",
            market_snapshot={"mid_price": 50000.0, "spread_bps": 1.5},
            features={"volatility": 0.02, "trend": 0.5},
            positions=[{"symbol": "BTCUSDT", "size": 0.1}],
            account_state={"equity": 10000.0},
            stage_results=[{"stage": "data_readiness", "passed": True}],
            rejection_stage=None,
            rejection_reason=None,
            decision="accepted",
            signal={"side": "buy", "size": 0.05},
            profile_id="aggressive",
        )
    
    def test_to_dict(self, sample_decision):
        """to_dict should serialize all fields."""
        d = sample_decision.to_dict()
        
        assert d["decision_id"] == "dec_test123456"
        assert d["timestamp"] == "2024-01-15T12:00:00+00:00"
        assert d["symbol"] == "BTCUSDT"
        assert d["config_version"] == "v1_abc123"
        assert d["market_snapshot"] == {"mid_price": 50000.0, "spread_bps": 1.5}
        assert d["features"] == {"volatility": 0.02, "trend": 0.5}
        assert d["positions"] == [{"symbol": "BTCUSDT", "size": 0.1}]
        assert d["account_state"] == {"equity": 10000.0}
        assert d["stage_results"] == [{"stage": "data_readiness", "passed": True}]
        assert d["rejection_stage"] is None
        assert d["rejection_reason"] is None
        assert d["decision"] == "accepted"
        assert d["signal"] == {"side": "buy", "size": 0.05}
        assert d["profile_id"] == "aggressive"
    
    def test_from_dict(self, sample_decision):
        """from_dict should deserialize all fields."""
        d = sample_decision.to_dict()
        
        restored = RecordedDecision.from_dict(d)
        
        assert restored.decision_id == sample_decision.decision_id
        assert restored.timestamp == sample_decision.timestamp
        assert restored.symbol == sample_decision.symbol
        assert restored.config_version == sample_decision.config_version
        assert restored.market_snapshot == sample_decision.market_snapshot
        assert restored.features == sample_decision.features
        assert restored.positions == sample_decision.positions
        assert restored.account_state == sample_decision.account_state
        assert restored.stage_results == sample_decision.stage_results
        assert restored.rejection_stage == sample_decision.rejection_stage
        assert restored.rejection_reason == sample_decision.rejection_reason
        assert restored.decision == sample_decision.decision
        assert restored.signal == sample_decision.signal
        assert restored.profile_id == sample_decision.profile_id
    
    def test_from_dict_with_z_timestamp(self):
        """from_dict should handle Z-suffix timestamps."""
        d = {
            "decision_id": "dec_test",
            "timestamp": "2024-01-15T12:00:00Z",
            "symbol": "BTCUSDT",
            "config_version": "v1",
            "decision": "accepted",
        }
        
        decision = RecordedDecision.from_dict(d)
        
        assert decision.timestamp.tzinfo is not None
    
    def test_from_dict_with_missing_optional_fields(self):
        """from_dict should handle missing optional fields."""
        d = {
            "decision_id": "dec_test",
            "timestamp": "2024-01-15T12:00:00+00:00",
            "symbol": "BTCUSDT",
            "config_version": "v1",
            "decision": "rejected",
        }
        
        decision = RecordedDecision.from_dict(d)
        
        assert decision.market_snapshot == {}
        assert decision.features == {}
        assert decision.positions == []
        assert decision.account_state == {}
        assert decision.stage_results == []
        assert decision.signal is None
        assert decision.profile_id is None
    
    def test_round_trip_serialization(self, sample_decision):
        """to_dict -> from_dict should preserve all data."""
        d = sample_decision.to_dict()
        restored = RecordedDecision.from_dict(d)
        d2 = restored.to_dict()
        
        assert d == d2


class TestRecordedDecisionDatabaseMethods:
    """Tests for RecordedDecision database methods."""
    
    @pytest.fixture
    def sample_decision(self):
        """Create a sample RecordedDecision."""
        return RecordedDecision(
            decision_id="dec_test123456",
            timestamp=datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc),
            symbol="BTCUSDT",
            config_version="v1_abc123",
            market_snapshot={"mid_price": 50000.0},
            features={"volatility": 0.02},
            positions=[{"symbol": "BTCUSDT", "size": 0.1}],
            account_state={"equity": 10000.0},
            stage_results=[{"stage": "data_readiness", "passed": True}],
            rejection_stage=None,
            rejection_reason=None,
            decision="accepted",
            signal={"side": "buy", "size": 0.05},
            profile_id="aggressive",
        )
    
    def test_to_db_tuple(self, sample_decision):
        """to_db_tuple should return correct tuple for database insertion."""
        db_tuple = sample_decision.to_db_tuple()
        
        assert len(db_tuple) == 14
        assert db_tuple[0] == "dec_test123456"  # decision_id
        assert db_tuple[1] == sample_decision.timestamp  # timestamp
        assert db_tuple[2] == "BTCUSDT"  # symbol
        assert db_tuple[3] == "v1_abc123"  # config_version
        assert '"mid_price": 50000.0' in db_tuple[4]  # market_snapshot JSON
        assert '"volatility": 0.02' in db_tuple[5]  # features JSON
        assert db_tuple[9] is None  # rejection_stage
        assert db_tuple[10] is None  # rejection_reason
        assert db_tuple[11] == "accepted"  # decision
        assert '"side": "buy"' in db_tuple[12]  # signal JSON
        assert db_tuple[13] == "aggressive"  # profile_id
    
    def test_to_db_tuple_with_none_values(self):
        """to_db_tuple should handle None values correctly."""
        decision = RecordedDecision(
            decision_id="dec_test",
            timestamp=datetime.now(timezone.utc),
            symbol="BTCUSDT",
            config_version="v1",
            decision="rejected",
            rejection_stage="ev_gate",
            rejection_reason="EV too low",
        )
        
        db_tuple = decision.to_db_tuple()
        
        # Empty lists/dicts should become None
        assert db_tuple[6] is None  # positions (empty list)
        assert db_tuple[7] is None  # account_state (empty dict)
        assert db_tuple[8] is None  # stage_results (empty list)
        assert db_tuple[9] == "ev_gate"  # rejection_stage
        assert db_tuple[10] == "EV too low"  # rejection_reason
        assert db_tuple[12] is None  # signal
    
    def test_from_db_row(self, sample_decision):
        """from_db_row should create RecordedDecision from database row."""
        # Simulate a database row (dict-like object)
        row = {
            "decision_id": "dec_test123456",
            "timestamp": datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc),
            "symbol": "BTCUSDT",
            "config_version": "v1_abc123",
            "market_snapshot": {"mid_price": 50000.0},
            "features": {"volatility": 0.02},
            "positions": [{"symbol": "BTCUSDT", "size": 0.1}],
            "account_state": {"equity": 10000.0},
            "stage_results": [{"stage": "data_readiness", "passed": True}],
            "rejection_stage": None,
            "rejection_reason": None,
            "decision": "accepted",
            "signal": {"side": "buy", "size": 0.05},
            "profile_id": "aggressive",
        }
        
        decision = RecordedDecision.from_db_row(row)
        
        assert decision.decision_id == "dec_test123456"
        assert decision.symbol == "BTCUSDT"
        assert decision.market_snapshot == {"mid_price": 50000.0}
        assert decision.decision == "accepted"
    
    def test_from_db_row_with_json_strings(self):
        """from_db_row should handle JSON string values."""
        row = {
            "decision_id": "dec_test",
            "timestamp": datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc),
            "symbol": "BTCUSDT",
            "config_version": "v1",
            "market_snapshot": '{"mid_price": 50000.0}',
            "features": '{"volatility": 0.02}',
            "positions": '[{"symbol": "BTCUSDT"}]',
            "account_state": '{"equity": 10000.0}',
            "stage_results": '[{"stage": "test"}]',
            "rejection_stage": None,
            "rejection_reason": None,
            "decision": "accepted",
            "signal": '{"side": "buy"}',
            "profile_id": "test",
        }
        
        decision = RecordedDecision.from_db_row(row)
        
        assert decision.market_snapshot == {"mid_price": 50000.0}
        assert decision.features == {"volatility": 0.02}
        assert decision.positions == [{"symbol": "BTCUSDT"}]
        assert decision.signal == {"side": "buy"}
    
    def test_from_db_row_with_naive_timestamp(self):
        """from_db_row should handle naive timestamps."""
        row = {
            "decision_id": "dec_test",
            "timestamp": datetime(2024, 1, 15, 12, 0, 0),  # Naive
            "symbol": "BTCUSDT",
            "config_version": "v1",
            "market_snapshot": {},
            "features": {},
            "decision": "accepted",
        }
        
        decision = RecordedDecision.from_db_row(row)
        
        assert decision.timestamp.tzinfo == timezone.utc


class TestRecordedDecisionHelperMethods:
    """Tests for RecordedDecision helper methods."""
    
    def test_is_rejected(self):
        """is_rejected should return True for rejected decisions."""
        decision = RecordedDecision(
            decision_id="dec_test",
            timestamp=datetime.now(timezone.utc),
            symbol="BTCUSDT",
            config_version="v1",
            decision="rejected",
        )
        
        assert decision.is_rejected() is True
        assert decision.is_accepted() is False
        assert decision.is_shadow() is False
    
    def test_is_accepted(self):
        """is_accepted should return True for accepted decisions."""
        decision = RecordedDecision(
            decision_id="dec_test",
            timestamp=datetime.now(timezone.utc),
            symbol="BTCUSDT",
            config_version="v1",
            decision="accepted",
        )
        
        assert decision.is_accepted() is True
        assert decision.is_rejected() is False
        assert decision.is_shadow() is False
    
    def test_is_shadow(self):
        """is_shadow should return True for shadow decisions."""
        decision = RecordedDecision(
            decision_id="dec_test",
            timestamp=datetime.now(timezone.utc),
            symbol="BTCUSDT",
            config_version="v1",
            decision="shadow",
        )
        
        assert decision.is_shadow() is True
        assert decision.is_accepted() is False
        assert decision.is_rejected() is False
    
    def test_get_stage_result_found(self):
        """get_stage_result should return stage result when found."""
        decision = RecordedDecision(
            decision_id="dec_test",
            timestamp=datetime.now(timezone.utc),
            symbol="BTCUSDT",
            config_version="v1",
            decision="accepted",
            stage_results=[
                {"stage": "data_readiness", "passed": True},
                {"stage": "ev_gate", "passed": True, "ev": 0.05},
                {"stage": "confirmation", "passed": True},
            ],
        )
        
        result = decision.get_stage_result("ev_gate")
        
        assert result is not None
        assert result["stage"] == "ev_gate"
        assert result["ev"] == 0.05
    
    def test_get_stage_result_not_found(self):
        """get_stage_result should return None when stage not found."""
        decision = RecordedDecision(
            decision_id="dec_test",
            timestamp=datetime.now(timezone.utc),
            symbol="BTCUSDT",
            config_version="v1",
            decision="accepted",
            stage_results=[
                {"stage": "data_readiness", "passed": True},
            ],
        )
        
        result = decision.get_stage_result("ev_gate")
        
        assert result is None
    
    def test_get_stage_result_with_name_key(self):
        """get_stage_result should also check 'name' key."""
        decision = RecordedDecision(
            decision_id="dec_test",
            timestamp=datetime.now(timezone.utc),
            symbol="BTCUSDT",
            config_version="v1",
            decision="accepted",
            stage_results=[
                {"name": "data_readiness", "passed": True},
            ],
        )
        
        result = decision.get_stage_result("data_readiness")
        
        assert result is not None
        assert result["name"] == "data_readiness"
    
    def test_has_complete_context_true(self):
        """has_complete_context should return True when all required fields present."""
        decision = RecordedDecision(
            decision_id="dec_test",
            timestamp=datetime.now(timezone.utc),
            symbol="BTCUSDT",
            config_version="v1",
            market_snapshot={"mid_price": 50000.0},
            features={"volatility": 0.02},
            decision="accepted",
        )
        
        assert decision.has_complete_context() is True
    
    def test_has_complete_context_false_no_snapshot(self):
        """has_complete_context should return False without market_snapshot."""
        decision = RecordedDecision(
            decision_id="dec_test",
            timestamp=datetime.now(timezone.utc),
            symbol="BTCUSDT",
            config_version="v1",
            features={"volatility": 0.02},
            decision="accepted",
        )
        
        assert decision.has_complete_context() is False
    
    def test_has_complete_context_false_no_features(self):
        """has_complete_context should return False without features."""
        decision = RecordedDecision(
            decision_id="dec_test",
            timestamp=datetime.now(timezone.utc),
            symbol="BTCUSDT",
            config_version="v1",
            market_snapshot={"mid_price": 50000.0},
            decision="accepted",
        )
        
        assert decision.has_complete_context() is False


class TestRecordedDecisionRequirements:
    """Tests verifying requirements compliance."""
    
    def test_requirement_2_1_complete_decision_context(self):
        """Requirement 2.1: Record complete decision context.
        
        WHEN a live trading decision is made THEN the System SHALL record
        the complete decision context including market snapshot, features,
        stage results, and final decision.
        """
        decision = RecordedDecision(
            decision_id="dec_req_2_1",
            timestamp=datetime.now(timezone.utc),
            symbol="BTCUSDT",
            config_version="v1",
            market_snapshot={
                "mid_price": 50000.0,
                "bid": 49999.0,
                "ask": 50001.0,
                "spread_bps": 0.4,
            },
            features={
                "volatility": 0.02,
                "trend": 0.5,
                "amt_distance": 0.01,
            },
            positions=[{"symbol": "BTCUSDT", "size": 0.1}],
            account_state={"equity": 10000.0, "margin": 500.0},
            stage_results=[
                {"stage": "data_readiness", "passed": True},
                {"stage": "ev_gate", "passed": True, "ev": 0.05},
            ],
            decision="accepted",
            signal={"side": "buy", "size": 0.05},
        )
        
        # Verify all context is captured
        assert decision.market_snapshot is not None
        assert "mid_price" in decision.market_snapshot
        assert decision.features is not None
        assert "volatility" in decision.features
        assert len(decision.stage_results) > 0
        assert decision.decision in ("accepted", "rejected", "shadow")
    
    def test_requirement_2_3_pipeline_stage_outputs(self):
        """Requirement 2.3: Include all pipeline stage outputs and rejection reasons.
        
        WHEN recording a decision THEN the System SHALL include all pipeline
        stage outputs and rejection reasons.
        """
        decision = RecordedDecision(
            decision_id="dec_req_2_3",
            timestamp=datetime.now(timezone.utc),
            symbol="BTCUSDT",
            config_version="v1",
            stage_results=[
                {"stage": "data_readiness", "passed": True, "data_age_ms": 50},
                {"stage": "ev_gate", "passed": False, "ev": -0.02, "threshold": 0.01},
            ],
            rejection_stage="ev_gate",
            rejection_reason="EV below threshold: -0.02 < 0.01",
            decision="rejected",
        )
        
        # Verify stage outputs are captured
        assert len(decision.stage_results) == 2
        assert decision.stage_results[0]["stage"] == "data_readiness"
        assert decision.stage_results[1]["stage"] == "ev_gate"
        
        # Verify rejection details are captured
        assert decision.rejection_stage == "ev_gate"
        assert decision.rejection_reason is not None
        assert "EV below threshold" in decision.rejection_reason
    
    def test_requirement_2_5_config_version(self):
        """Requirement 2.5: Include configuration version.
        
        WHEN a decision is recorded THEN the System SHALL include the
        configuration version used for that decision.
        """
        decision = RecordedDecision(
            decision_id="dec_req_2_5",
            timestamp=datetime.now(timezone.utc),
            symbol="BTCUSDT",
            config_version="live_v1_abc123",
            decision="accepted",
        )
        
        # Verify config version is captured
        assert decision.config_version is not None
        assert decision.config_version == "live_v1_abc123"
        
        # Verify it's included in serialization
        d = decision.to_dict()
        assert "config_version" in d
        assert d["config_version"] == "live_v1_abc123"
        
        # Verify it's included in database tuple
        db_tuple = decision.to_db_tuple()
        assert db_tuple[3] == "live_v1_abc123"
