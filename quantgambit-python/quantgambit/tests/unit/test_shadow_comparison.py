"""Unit tests for shadow comparison data structures.

Feature: trading-pipeline-integration
Requirements: 4.2 - WHEN shadow mode is enabled THEN the System SHALL record
              both live and shadow decisions for each market event
Requirements: 4.3 - THE System SHALL compute decision agreement rate between
              live and shadow pipelines

Tests verify:
1. ComparisonResult can be created with all required fields
2. ComparisonMetrics can be created with all required fields
3. ComparisonResult.agrees is True when live_decision == shadow_decision
4. ComparisonMetrics.agreement_rate is calculated correctly
"""

from datetime import datetime, timezone

import pytest

from quantgambit.integration.shadow_comparison import (
    ComparisonMetrics,
    ComparisonResult,
)


class TestComparisonResult:
    """Tests for ComparisonResult dataclass."""
    
    def test_create_with_all_required_fields(self) -> None:
        """Test ComparisonResult can be created with all required fields.
        
        Validates: Requirements 4.2
        """
        timestamp = datetime.now(timezone.utc)
        result = ComparisonResult(
            timestamp=timestamp,
            symbol="BTCUSDT",
            live_decision="accepted",
            shadow_decision="accepted",
            agrees=True,
        )
        
        assert result.timestamp == timestamp
        assert result.symbol == "BTCUSDT"
        assert result.live_decision == "accepted"
        assert result.shadow_decision == "accepted"
        assert result.agrees is True
    
    def test_create_with_all_optional_fields(self) -> None:
        """Test ComparisonResult can be created with all optional fields.
        
        Validates: Requirements 4.2
        """
        timestamp = datetime.now(timezone.utc)
        live_signal = {"side": "buy", "size": 0.1}
        shadow_signal = {"side": "buy", "size": 0.15}
        
        result = ComparisonResult(
            timestamp=timestamp,
            symbol="ETHUSDT",
            live_decision="accepted",
            shadow_decision="accepted",
            agrees=True,
            divergence_reason=None,
            live_signal=live_signal,
            shadow_signal=shadow_signal,
            live_rejection_stage=None,
            shadow_rejection_stage=None,
            live_config_version="v1.0.0",
            shadow_config_version="v1.1.0",
        )
        
        assert result.live_signal == live_signal
        assert result.shadow_signal == shadow_signal
        assert result.live_config_version == "v1.0.0"
        assert result.shadow_config_version == "v1.1.0"
    
    def test_agrees_true_when_decisions_match(self) -> None:
        """Test ComparisonResult.agrees is True when live_decision == shadow_decision.
        
        Validates: Requirements 4.3
        """
        # Both accepted
        result1 = ComparisonResult.create(
            timestamp=datetime.now(timezone.utc),
            symbol="BTCUSDT",
            live_decision="accepted",
            shadow_decision="accepted",
        )
        assert result1.agrees is True
        
        # Both rejected
        result2 = ComparisonResult.create(
            timestamp=datetime.now(timezone.utc),
            symbol="BTCUSDT",
            live_decision="rejected",
            shadow_decision="rejected",
        )
        assert result2.agrees is True
    
    def test_agrees_false_when_decisions_differ(self) -> None:
        """Test ComparisonResult.agrees is False when decisions differ.
        
        Validates: Requirements 4.3
        """
        # Live accepted, shadow rejected
        result1 = ComparisonResult.create(
            timestamp=datetime.now(timezone.utc),
            symbol="BTCUSDT",
            live_decision="accepted",
            shadow_decision="rejected",
            divergence_reason="stage_diff:ev_gate",
        )
        assert result1.agrees is False
        
        # Live rejected, shadow accepted
        result2 = ComparisonResult.create(
            timestamp=datetime.now(timezone.utc),
            symbol="BTCUSDT",
            live_decision="rejected",
            shadow_decision="accepted",
            divergence_reason="profile_diff:aggressive_vs_conservative",
        )
        assert result2.agrees is False
    
    def test_auto_computes_agrees_in_post_init(self) -> None:
        """Test that __post_init__ auto-corrects agrees field.
        
        Validates: Requirements 4.3
        """
        # Pass wrong agrees value, should be corrected
        result = ComparisonResult(
            timestamp=datetime.now(timezone.utc),
            symbol="BTCUSDT",
            live_decision="accepted",
            shadow_decision="rejected",
            agrees=True,  # Wrong value
        )
        # Should be corrected to False
        assert result.agrees is False
    
    def test_create_factory_method(self) -> None:
        """Test ComparisonResult.create factory method auto-computes agrees.
        
        Validates: Requirements 4.3
        """
        result = ComparisonResult.create(
            timestamp=datetime.now(timezone.utc),
            symbol="BTCUSDT",
            live_decision="accepted",
            shadow_decision="rejected",
        )
        assert result.agrees is False
    
    def test_to_dict_serialization(self) -> None:
        """Test ComparisonResult.to_dict serialization.
        
        Validates: Requirements 4.2
        """
        timestamp = datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
        result = ComparisonResult.create(
            timestamp=timestamp,
            symbol="BTCUSDT",
            live_decision="accepted",
            shadow_decision="accepted",
            live_signal={"side": "buy"},
        )
        
        data = result.to_dict()
        
        assert data["timestamp"] == "2024-01-15T12:00:00+00:00"
        assert data["symbol"] == "BTCUSDT"
        assert data["live_decision"] == "accepted"
        assert data["shadow_decision"] == "accepted"
        assert data["agrees"] is True
        assert data["live_signal"] == {"side": "buy"}
    
    def test_from_dict_deserialization(self) -> None:
        """Test ComparisonResult.from_dict deserialization.
        
        Validates: Requirements 4.2
        """
        data = {
            "timestamp": "2024-01-15T12:00:00+00:00",
            "symbol": "BTCUSDT",
            "live_decision": "rejected",
            "shadow_decision": "rejected",
            "agrees": True,
            "divergence_reason": None,
            "live_rejection_stage": "ev_gate",
            "shadow_rejection_stage": "ev_gate",
        }
        
        result = ComparisonResult.from_dict(data)
        
        assert result.symbol == "BTCUSDT"
        assert result.live_decision == "rejected"
        assert result.agrees is True
        assert result.live_rejection_stage == "ev_gate"
    
    def test_to_db_tuple(self) -> None:
        """Test ComparisonResult.to_db_tuple for database insertion.
        
        Validates: Requirements 4.2
        """
        timestamp = datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
        result = ComparisonResult.create(
            timestamp=timestamp,
            symbol="BTCUSDT",
            live_decision="accepted",
            shadow_decision="rejected",
            divergence_reason="stage_diff",
            live_config_version="v1.0",
            shadow_config_version="v1.1",
        )
        
        db_tuple = result.to_db_tuple()
        
        assert db_tuple[0] == timestamp
        assert db_tuple[1] == "BTCUSDT"
        assert db_tuple[2] == "accepted"
        assert db_tuple[3] == "rejected"
        assert db_tuple[4] is False  # agrees
        assert db_tuple[5] == "stage_diff"
        assert db_tuple[6] == "v1.0"
        assert db_tuple[7] == "v1.1"
    
    def test_is_agreement_and_is_divergence(self) -> None:
        """Test is_agreement and is_divergence helper methods.
        
        Validates: Requirements 4.3
        """
        agreement = ComparisonResult.create(
            timestamp=datetime.now(timezone.utc),
            symbol="BTCUSDT",
            live_decision="accepted",
            shadow_decision="accepted",
        )
        assert agreement.is_agreement() is True
        assert agreement.is_divergence() is False
        
        divergence = ComparisonResult.create(
            timestamp=datetime.now(timezone.utc),
            symbol="BTCUSDT",
            live_decision="accepted",
            shadow_decision="rejected",
        )
        assert divergence.is_agreement() is False
        assert divergence.is_divergence() is True
    
    def test_validation_empty_symbol_raises(self) -> None:
        """Test that empty symbol raises ValueError.
        
        Validates: Requirements 4.2
        """
        with pytest.raises(ValueError, match="symbol cannot be empty"):
            ComparisonResult(
                timestamp=datetime.now(timezone.utc),
                symbol="",
                live_decision="accepted",
                shadow_decision="accepted",
                agrees=True,
            )
    
    def test_validation_invalid_live_decision_raises(self) -> None:
        """Test that invalid live_decision raises ValueError.
        
        Validates: Requirements 4.2
        """
        with pytest.raises(ValueError, match="live_decision must be"):
            ComparisonResult(
                timestamp=datetime.now(timezone.utc),
                symbol="BTCUSDT",
                live_decision="invalid",
                shadow_decision="accepted",
                agrees=True,
            )
    
    def test_validation_invalid_shadow_decision_raises(self) -> None:
        """Test that invalid shadow_decision raises ValueError.
        
        Validates: Requirements 4.2
        """
        with pytest.raises(ValueError, match="shadow_decision must be"):
            ComparisonResult(
                timestamp=datetime.now(timezone.utc),
                symbol="BTCUSDT",
                live_decision="accepted",
                shadow_decision="invalid",
                agrees=True,
            )
    
    def test_timestamp_without_timezone_gets_utc(self) -> None:
        """Test that timestamp without timezone gets UTC added.
        
        Validates: Requirements 4.2
        """
        naive_timestamp = datetime(2024, 1, 15, 12, 0, 0)
        result = ComparisonResult(
            timestamp=naive_timestamp,
            symbol="BTCUSDT",
            live_decision="accepted",
            shadow_decision="accepted",
            agrees=True,
        )
        
        assert result.timestamp.tzinfo is not None
        assert result.timestamp.tzinfo == timezone.utc


class TestComparisonMetrics:
    """Tests for ComparisonMetrics dataclass."""
    
    def test_create_with_all_required_fields(self) -> None:
        """Test ComparisonMetrics can be created with all required fields.
        
        Validates: Requirements 4.3
        """
        metrics = ComparisonMetrics(
            total_comparisons=100,
            agreements=80,
            disagreements=20,
            agreement_rate=0.8,
        )
        
        assert metrics.total_comparisons == 100
        assert metrics.agreements == 80
        assert metrics.disagreements == 20
        assert metrics.agreement_rate == 0.8
    
    def test_create_with_all_optional_fields(self) -> None:
        """Test ComparisonMetrics can be created with all optional fields.
        
        Validates: Requirements 4.3
        """
        divergence_by_reason = {
            "stage_diff:ev_gate": 10,
            "profile_diff": 5,
            "unknown": 5,
        }
        
        metrics = ComparisonMetrics(
            total_comparisons=100,
            agreements=80,
            disagreements=20,
            agreement_rate=0.8,
            divergence_by_reason=divergence_by_reason,
            live_pnl_estimate=1000.0,
            shadow_pnl_estimate=1200.0,
        )
        
        assert metrics.divergence_by_reason == divergence_by_reason
        assert metrics.live_pnl_estimate == 1000.0
        assert metrics.shadow_pnl_estimate == 1200.0
    
    def test_agreement_rate_calculated_correctly(self) -> None:
        """Test ComparisonMetrics.agreement_rate is calculated correctly.
        
        Validates: Requirements 4.3
        """
        # 80% agreement
        metrics1 = ComparisonMetrics(
            total_comparisons=100,
            agreements=80,
            disagreements=20,
            agreement_rate=0.8,
        )
        assert metrics1.agreement_rate == 0.8
        
        # 100% agreement
        metrics2 = ComparisonMetrics(
            total_comparisons=50,
            agreements=50,
            disagreements=0,
            agreement_rate=1.0,
        )
        assert metrics2.agreement_rate == 1.0
        
        # 0% agreement
        metrics3 = ComparisonMetrics(
            total_comparisons=10,
            agreements=0,
            disagreements=10,
            agreement_rate=0.0,
        )
        assert metrics3.agreement_rate == 0.0
    
    def test_create_empty(self) -> None:
        """Test ComparisonMetrics.create_empty factory method.
        
        Validates: Requirements 4.3
        """
        metrics = ComparisonMetrics.create_empty()
        
        assert metrics.total_comparisons == 0
        assert metrics.agreements == 0
        assert metrics.disagreements == 0
        assert metrics.agreement_rate == 1.0
        assert metrics.divergence_by_reason == {}
        assert metrics.live_pnl_estimate == 0.0
        assert metrics.shadow_pnl_estimate == 0.0
    
    def test_from_comparisons_empty_list(self) -> None:
        """Test ComparisonMetrics.from_comparisons with empty list.
        
        Validates: Requirements 4.3
        """
        metrics = ComparisonMetrics.from_comparisons([])
        
        assert metrics.total_comparisons == 0
        assert metrics.agreement_rate == 1.0
    
    def test_from_comparisons_all_agreements(self) -> None:
        """Test ComparisonMetrics.from_comparisons with all agreements.
        
        Validates: Requirements 4.3
        """
        comparisons = [
            ComparisonResult.create(
                timestamp=datetime.now(timezone.utc),
                symbol="BTCUSDT",
                live_decision="accepted",
                shadow_decision="accepted",
            )
            for _ in range(10)
        ]
        
        metrics = ComparisonMetrics.from_comparisons(comparisons)
        
        assert metrics.total_comparisons == 10
        assert metrics.agreements == 10
        assert metrics.disagreements == 0
        assert metrics.agreement_rate == 1.0
    
    def test_from_comparisons_mixed(self) -> None:
        """Test ComparisonMetrics.from_comparisons with mixed results.
        
        Validates: Requirements 4.3
        """
        comparisons = [
            # 7 agreements
            ComparisonResult.create(
                timestamp=datetime.now(timezone.utc),
                symbol="BTCUSDT",
                live_decision="accepted",
                shadow_decision="accepted",
            )
            for _ in range(7)
        ] + [
            # 3 disagreements with reasons
            ComparisonResult.create(
                timestamp=datetime.now(timezone.utc),
                symbol="BTCUSDT",
                live_decision="accepted",
                shadow_decision="rejected",
                divergence_reason="stage_diff:ev_gate",
            ),
            ComparisonResult.create(
                timestamp=datetime.now(timezone.utc),
                symbol="BTCUSDT",
                live_decision="rejected",
                shadow_decision="accepted",
                divergence_reason="stage_diff:ev_gate",
            ),
            ComparisonResult.create(
                timestamp=datetime.now(timezone.utc),
                symbol="BTCUSDT",
                live_decision="accepted",
                shadow_decision="rejected",
                divergence_reason="profile_diff",
            ),
        ]
        
        metrics = ComparisonMetrics.from_comparisons(comparisons)
        
        assert metrics.total_comparisons == 10
        assert metrics.agreements == 7
        assert metrics.disagreements == 3
        assert metrics.agreement_rate == 0.7
        assert metrics.divergence_by_reason == {
            "stage_diff:ev_gate": 2,
            "profile_diff": 1,
        }
    
    def test_divergence_rate(self) -> None:
        """Test ComparisonMetrics.divergence_rate method.
        
        Validates: Requirements 4.3
        """
        metrics = ComparisonMetrics(
            total_comparisons=100,
            agreements=75,
            disagreements=25,
            agreement_rate=0.75,
        )
        
        assert metrics.divergence_rate() == 0.25
    
    def test_exceeds_threshold(self) -> None:
        """Test ComparisonMetrics.exceeds_threshold method.
        
        Validates: Requirements 4.3
        """
        # 25% divergence exceeds 20% threshold
        high_divergence = ComparisonMetrics(
            total_comparisons=100,
            agreements=75,
            disagreements=25,
            agreement_rate=0.75,
        )
        assert high_divergence.exceeds_threshold(0.20) is True
        
        # 15% divergence does not exceed 20% threshold
        low_divergence = ComparisonMetrics(
            total_comparisons=100,
            agreements=85,
            disagreements=15,
            agreement_rate=0.85,
        )
        assert low_divergence.exceeds_threshold(0.20) is False
        
        # Exactly at threshold
        at_threshold = ComparisonMetrics(
            total_comparisons=100,
            agreements=80,
            disagreements=20,
            agreement_rate=0.80,
        )
        assert at_threshold.exceeds_threshold(0.20) is False
    
    def test_top_divergence_reasons(self) -> None:
        """Test ComparisonMetrics.top_divergence_reasons method.
        
        Validates: Requirements 4.3
        """
        metrics = ComparisonMetrics(
            total_comparisons=100,
            agreements=80,
            disagreements=20,
            agreement_rate=0.8,
            divergence_by_reason={
                "stage_diff:ev_gate": 10,
                "profile_diff": 5,
                "unknown": 3,
                "config_diff": 2,
            },
        )
        
        top_3 = metrics.top_divergence_reasons(3)
        
        assert len(top_3) == 3
        assert top_3[0] == ("stage_diff:ev_gate", 10)
        assert top_3[1] == ("profile_diff", 5)
        assert top_3[2] == ("unknown", 3)
    
    def test_pnl_difference(self) -> None:
        """Test ComparisonMetrics.pnl_difference method.
        
        Validates: Requirements 4.3
        """
        metrics = ComparisonMetrics(
            total_comparisons=100,
            agreements=80,
            disagreements=20,
            agreement_rate=0.8,
            live_pnl_estimate=1000.0,
            shadow_pnl_estimate=1200.0,
        )
        
        assert metrics.pnl_difference() == 200.0
    
    def test_to_dict_serialization(self) -> None:
        """Test ComparisonMetrics.to_dict serialization.
        
        Validates: Requirements 4.3
        """
        metrics = ComparisonMetrics(
            total_comparisons=100,
            agreements=80,
            disagreements=20,
            agreement_rate=0.8,
            divergence_by_reason={"stage_diff": 20},
            live_pnl_estimate=1000.0,
            shadow_pnl_estimate=1200.0,
        )
        
        data = metrics.to_dict()
        
        assert data["total_comparisons"] == 100
        assert data["agreements"] == 80
        assert data["disagreements"] == 20
        assert data["agreement_rate"] == 0.8
        assert data["divergence_by_reason"] == {"stage_diff": 20}
        assert data["live_pnl_estimate"] == 1000.0
        assert data["shadow_pnl_estimate"] == 1200.0
    
    def test_from_dict_deserialization(self) -> None:
        """Test ComparisonMetrics.from_dict deserialization.
        
        Validates: Requirements 4.3
        """
        data = {
            "total_comparisons": 50,
            "agreements": 40,
            "disagreements": 10,
            "agreement_rate": 0.8,
            "divergence_by_reason": {"profile_diff": 10},
            "live_pnl_estimate": 500.0,
            "shadow_pnl_estimate": 600.0,
        }
        
        metrics = ComparisonMetrics.from_dict(data)
        
        assert metrics.total_comparisons == 50
        assert metrics.agreements == 40
        assert metrics.disagreements == 10
        assert metrics.agreement_rate == 0.8
        assert metrics.divergence_by_reason == {"profile_diff": 10}
    
    def test_validation_negative_total_raises(self) -> None:
        """Test that negative total_comparisons raises ValueError.
        
        Validates: Requirements 4.3
        """
        with pytest.raises(ValueError, match="total_comparisons cannot be negative"):
            ComparisonMetrics(
                total_comparisons=-1,
                agreements=0,
                disagreements=0,
                agreement_rate=1.0,
            )
    
    def test_validation_negative_agreements_raises(self) -> None:
        """Test that negative agreements raises ValueError.
        
        Validates: Requirements 4.3
        """
        with pytest.raises(ValueError, match="agreements cannot be negative"):
            ComparisonMetrics(
                total_comparisons=10,
                agreements=-1,
                disagreements=11,
                agreement_rate=0.0,
            )
    
    def test_validation_agreement_rate_out_of_range_raises(self) -> None:
        """Test that agreement_rate out of range raises ValueError.
        
        Validates: Requirements 4.3
        """
        with pytest.raises(ValueError, match="agreement_rate must be between"):
            ComparisonMetrics(
                total_comparisons=10,
                agreements=10,
                disagreements=0,
                agreement_rate=1.5,
            )
    
    def test_validation_inconsistent_totals_raises(self) -> None:
        """Test that inconsistent totals raise ValueError.
        
        Validates: Requirements 4.3
        """
        with pytest.raises(ValueError, match="must equal total_comparisons"):
            ComparisonMetrics(
                total_comparisons=100,
                agreements=50,
                disagreements=40,  # Should be 50
                agreement_rate=0.5,
            )
    
    def test_validation_inconsistent_rate_raises(self) -> None:
        """Test that inconsistent agreement_rate raises ValueError.
        
        Validates: Requirements 4.3
        """
        with pytest.raises(ValueError, match="agreement_rate.*is inconsistent"):
            ComparisonMetrics(
                total_comparisons=100,
                agreements=80,
                disagreements=20,
                agreement_rate=0.5,  # Should be 0.8
            )


class TestComparisonResultAndMetricsIntegration:
    """Integration tests for ComparisonResult and ComparisonMetrics together."""
    
    def test_round_trip_serialization(self) -> None:
        """Test round-trip serialization of ComparisonResult.
        
        Validates: Requirements 4.2
        """
        original = ComparisonResult.create(
            timestamp=datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc),
            symbol="BTCUSDT",
            live_decision="accepted",
            shadow_decision="rejected",
            divergence_reason="stage_diff:ev_gate",
            live_signal={"side": "buy", "size": 0.1},
            shadow_signal=None,
            live_rejection_stage=None,
            shadow_rejection_stage="ev_gate",
            live_config_version="v1.0",
            shadow_config_version="v1.1",
        )
        
        # Serialize and deserialize
        data = original.to_dict()
        restored = ComparisonResult.from_dict(data)
        
        assert restored.timestamp == original.timestamp
        assert restored.symbol == original.symbol
        assert restored.live_decision == original.live_decision
        assert restored.shadow_decision == original.shadow_decision
        assert restored.agrees == original.agrees
        assert restored.divergence_reason == original.divergence_reason
        assert restored.live_signal == original.live_signal
    
    def test_metrics_from_comparisons_round_trip(self) -> None:
        """Test creating metrics from comparisons and serializing.
        
        Validates: Requirements 4.3
        """
        comparisons = [
            ComparisonResult.create(
                timestamp=datetime.now(timezone.utc),
                symbol="BTCUSDT",
                live_decision="accepted",
                shadow_decision="accepted",
            ),
            ComparisonResult.create(
                timestamp=datetime.now(timezone.utc),
                symbol="BTCUSDT",
                live_decision="accepted",
                shadow_decision="rejected",
                divergence_reason="stage_diff",
            ),
        ]
        
        metrics = ComparisonMetrics.from_comparisons(
            comparisons,
            live_pnl_estimate=100.0,
            shadow_pnl_estimate=80.0,
        )
        
        # Serialize and deserialize
        data = metrics.to_dict()
        restored = ComparisonMetrics.from_dict(data)
        
        assert restored.total_comparisons == 2
        assert restored.agreements == 1
        assert restored.disagreements == 1
        assert restored.agreement_rate == 0.5
        assert restored.divergence_by_reason == {"stage_diff": 1}
        assert restored.live_pnl_estimate == 100.0
        assert restored.shadow_pnl_estimate == 80.0
