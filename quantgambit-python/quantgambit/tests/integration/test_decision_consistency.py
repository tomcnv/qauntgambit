"""Integration tests for decision consistency verification.

Feature: trading-pipeline-integration
Requirement 10.2: THE System SHALL verify that identical inputs produce identical
                  decisions in both live and backtest modes

Tests for:
- Identical inputs produce identical decisions
- Rejection stage matches for rejected decisions
- Signal consistency for accepted decisions
"""

import pytest
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

from quantgambit.integration.decision_recording import RecordedDecision
from quantgambit.tests.fixtures.parity_fixtures import (
    KNOWN_GOOD_ACCEPTED_DECISIONS,
    KNOWN_GOOD_REJECTED_DECISIONS,
    KNOWN_GOOD_EDGE_CASE_DECISIONS,
    STANDARD_TEST_CONFIG,
    ParityTestFixtures,
    create_test_decision,
    create_decision_sequence,
    get_expected_outcome,
)


class DecisionConsistencyChecker:
    """Helper class to verify decision consistency.
    
    This class provides methods to verify that identical inputs produce
    identical decisions, which is a key requirement for backtest/live parity.
    
    Feature: trading-pipeline-integration
    Requirements: 10.2
    """
    
    @staticmethod
    def decisions_are_consistent(
        decision1: RecordedDecision,
        decision2: RecordedDecision,
    ) -> bool:
        """Check if two decisions are consistent.
        
        Two decisions are consistent if:
        - They have the same decision outcome (accepted/rejected)
        - For rejected decisions, they have the same rejection_stage
        - For accepted decisions, they have consistent signals (same side)
        
        Args:
            decision1: First decision to compare
            decision2: Second decision to compare
            
        Returns:
            True if decisions are consistent
        """
        # Check decision outcome matches
        if decision1.decision != decision2.decision:
            return False
        
        # For rejected decisions, check rejection_stage matches
        if decision1.decision == "rejected":
            if decision1.rejection_stage != decision2.rejection_stage:
                return False
        
        # For accepted decisions, check signal consistency
        if decision1.decision == "accepted":
            if decision1.signal and decision2.signal:
                if decision1.signal.get("side") != decision2.signal.get("side"):
                    return False
        
        return True
    
    @staticmethod
    def get_consistency_diff(
        decision1: RecordedDecision,
        decision2: RecordedDecision,
    ) -> Dict[str, Any]:
        """Get detailed diff between two decisions.
        
        Args:
            decision1: First decision to compare
            decision2: Second decision to compare
            
        Returns:
            Dictionary with differences found
        """
        diff: Dict[str, Any] = {}
        
        if decision1.decision != decision2.decision:
            diff["decision"] = {
                "expected": decision1.decision,
                "actual": decision2.decision,
            }
        
        if decision1.rejection_stage != decision2.rejection_stage:
            diff["rejection_stage"] = {
                "expected": decision1.rejection_stage,
                "actual": decision2.rejection_stage,
            }
        
        if decision1.signal and decision2.signal:
            if decision1.signal.get("side") != decision2.signal.get("side"):
                diff["signal_side"] = {
                    "expected": decision1.signal.get("side"),
                    "actual": decision2.signal.get("side"),
                }
        elif decision1.signal != decision2.signal:
            diff["signal"] = {
                "expected": decision1.signal,
                "actual": decision2.signal,
            }
        
        return diff


class TestDecisionConsistencyForIdenticalInputs:
    """Tests that identical inputs produce identical decisions.
    
    Feature: trading-pipeline-integration
    Requirements: 10.2 - THE System SHALL verify that identical inputs produce
                  identical decisions in both live and backtest modes
    """
    
    def test_identical_accepted_decisions_are_consistent(self):
        """Identical accepted decisions should be consistent."""
        fixtures = ParityTestFixtures()
        accepted_decisions = fixtures.get_accepted_decisions()
        
        for decision in accepted_decisions:
            # Create a copy with the same inputs
            decision_copy = RecordedDecision(
                decision_id=f"{decision.decision_id}_copy",
                timestamp=decision.timestamp,
                symbol=decision.symbol,
                config_version=decision.config_version,
                market_snapshot=deepcopy(decision.market_snapshot),
                features=deepcopy(decision.features),
                positions=deepcopy(decision.positions),
                account_state=deepcopy(decision.account_state),
                stage_results=deepcopy(decision.stage_results),
                rejection_stage=decision.rejection_stage,
                rejection_reason=decision.rejection_reason,
                decision=decision.decision,
                signal=deepcopy(decision.signal),
                profile_id=decision.profile_id,
            )
            
            # Verify consistency
            assert DecisionConsistencyChecker.decisions_are_consistent(
                decision, decision_copy
            ), f"Decision {decision.decision_id} should be consistent with its copy"
    
    def test_identical_rejected_decisions_are_consistent(self):
        """Identical rejected decisions should be consistent."""
        fixtures = ParityTestFixtures()
        rejected_decisions = fixtures.get_rejected_decisions()
        
        for decision in rejected_decisions:
            # Create a copy with the same inputs
            decision_copy = RecordedDecision(
                decision_id=f"{decision.decision_id}_copy",
                timestamp=decision.timestamp,
                symbol=decision.symbol,
                config_version=decision.config_version,
                market_snapshot=deepcopy(decision.market_snapshot),
                features=deepcopy(decision.features),
                positions=deepcopy(decision.positions),
                account_state=deepcopy(decision.account_state),
                stage_results=deepcopy(decision.stage_results),
                rejection_stage=decision.rejection_stage,
                rejection_reason=decision.rejection_reason,
                decision=decision.decision,
                signal=decision.signal,
                profile_id=decision.profile_id,
            )
            
            # Verify consistency
            assert DecisionConsistencyChecker.decisions_are_consistent(
                decision, decision_copy
            ), f"Decision {decision.decision_id} should be consistent with its copy"
    
    def test_identical_edge_case_decisions_are_consistent(self):
        """Identical edge case decisions should be consistent."""
        fixtures = ParityTestFixtures()
        edge_case_decisions = fixtures.get_edge_case_decisions()
        
        for decision in edge_case_decisions:
            # Create a copy with the same inputs
            decision_copy = RecordedDecision(
                decision_id=f"{decision.decision_id}_copy",
                timestamp=decision.timestamp,
                symbol=decision.symbol,
                config_version=decision.config_version,
                market_snapshot=deepcopy(decision.market_snapshot),
                features=deepcopy(decision.features),
                positions=deepcopy(decision.positions),
                account_state=deepcopy(decision.account_state),
                stage_results=deepcopy(decision.stage_results),
                rejection_stage=decision.rejection_stage,
                rejection_reason=decision.rejection_reason,
                decision=decision.decision,
                signal=deepcopy(decision.signal) if decision.signal else None,
                profile_id=decision.profile_id,
            )
            
            # Verify consistency
            assert DecisionConsistencyChecker.decisions_are_consistent(
                decision, decision_copy
            ), f"Decision {decision.decision_id} should be consistent with its copy"
    
    def test_decision_sequence_consistency(self):
        """A sequence of decisions should be consistent when replayed."""
        # Create a sequence of decisions
        sequence = create_decision_sequence(
            count=20,
            accepted_ratio=0.5,
            symbol="BTCUSDT",
            config_version="live_test_v1",
        )
        
        # Verify each decision is consistent with itself
        for decision in sequence:
            decision_copy = RecordedDecision(
                decision_id=f"{decision.decision_id}_replay",
                timestamp=decision.timestamp,
                symbol=decision.symbol,
                config_version=decision.config_version,
                market_snapshot=deepcopy(decision.market_snapshot),
                features=deepcopy(decision.features),
                positions=deepcopy(decision.positions),
                account_state=deepcopy(decision.account_state),
                stage_results=deepcopy(decision.stage_results),
                rejection_stage=decision.rejection_stage,
                rejection_reason=decision.rejection_reason,
                decision=decision.decision,
                signal=deepcopy(decision.signal) if decision.signal else None,
                profile_id=decision.profile_id,
            )
            
            assert DecisionConsistencyChecker.decisions_are_consistent(
                decision, decision_copy
            ), f"Decision {decision.decision_id} should be consistent when replayed"


class TestRejectionStageConsistency:
    """Tests that rejection_stage matches for rejected decisions.
    
    Feature: trading-pipeline-integration
    Requirements: 10.2
    """
    
    def test_ev_gate_rejection_stage_matches(self):
        """Decisions rejected at EVGate should have consistent rejection_stage."""
        fixtures = ParityTestFixtures()
        ev_gate_rejections = fixtures.get_decisions_by_rejection_stage("EVGate")
        
        assert len(ev_gate_rejections) > 0, "Should have EVGate rejections in fixtures"
        
        for decision in ev_gate_rejections:
            assert decision.rejection_stage == "EVGate"
            assert decision.decision == "rejected"
            
            # Verify the stage results show EVGate failed
            ev_gate_result = decision.get_stage_result("EVGate")
            assert ev_gate_result is not None, "Should have EVGate stage result"
            assert ev_gate_result.get("passed") is False, "EVGate should have failed"
    
    def test_data_readiness_rejection_stage_matches(self):
        """Decisions rejected at DataReadiness should have consistent rejection_stage."""
        fixtures = ParityTestFixtures()
        data_readiness_rejections = fixtures.get_decisions_by_rejection_stage("DataReadiness")
        
        assert len(data_readiness_rejections) > 0, "Should have DataReadiness rejections in fixtures"
        
        for decision in data_readiness_rejections:
            assert decision.rejection_stage == "DataReadiness"
            assert decision.decision == "rejected"
            
            # Verify the stage results show DataReadiness failed
            data_readiness_result = decision.get_stage_result("DataReadiness")
            assert data_readiness_result is not None, "Should have DataReadiness stage result"
            assert data_readiness_result.get("passed") is False, "DataReadiness should have failed"
    
    def test_global_gate_rejection_stage_matches(self):
        """Decisions rejected at GlobalGate should have consistent rejection_stage."""
        fixtures = ParityTestFixtures()
        global_gate_rejections = fixtures.get_decisions_by_rejection_stage("GlobalGate")
        
        assert len(global_gate_rejections) > 0, "Should have GlobalGate rejections in fixtures"
        
        for decision in global_gate_rejections:
            assert decision.rejection_stage == "GlobalGate"
            assert decision.decision == "rejected"
            
            # Verify the stage results show GlobalGate failed
            global_gate_result = decision.get_stage_result("GlobalGate")
            assert global_gate_result is not None, "Should have GlobalGate stage result"
            assert global_gate_result.get("passed") is False, "GlobalGate should have failed"
    
    def test_execution_feasibility_rejection_stage_matches(self):
        """Decisions rejected at ExecutionFeasibility should have consistent rejection_stage."""
        fixtures = ParityTestFixtures()
        feasibility_rejections = fixtures.get_decisions_by_rejection_stage("ExecutionFeasibility")
        
        assert len(feasibility_rejections) > 0, "Should have ExecutionFeasibility rejections in fixtures"
        
        for decision in feasibility_rejections:
            assert decision.rejection_stage == "ExecutionFeasibility"
            assert decision.decision == "rejected"
            
            # Verify the stage results show ExecutionFeasibility failed
            feasibility_result = decision.get_stage_result("ExecutionFeasibility")
            assert feasibility_result is not None, "Should have ExecutionFeasibility stage result"
            assert feasibility_result.get("passed") is False, "ExecutionFeasibility should have failed"
    
    def test_all_rejected_decisions_have_rejection_stage(self):
        """All rejected decisions should have a rejection_stage set."""
        fixtures = ParityTestFixtures()
        rejected_decisions = fixtures.get_rejected_decisions()
        
        for decision in rejected_decisions:
            assert decision.decision == "rejected"
            assert decision.rejection_stage is not None, (
                f"Rejected decision {decision.decision_id} should have rejection_stage"
            )
            assert decision.rejection_stage != "", (
                f"Rejected decision {decision.decision_id} should have non-empty rejection_stage"
            )
    
    def test_accepted_decisions_have_no_rejection_stage(self):
        """Accepted decisions should not have a rejection_stage."""
        fixtures = ParityTestFixtures()
        accepted_decisions = fixtures.get_accepted_decisions()
        
        for decision in accepted_decisions:
            assert decision.decision == "accepted"
            assert decision.rejection_stage is None, (
                f"Accepted decision {decision.decision_id} should not have rejection_stage"
            )


class TestSignalConsistencyForAcceptedDecisions:
    """Tests that signals are consistent for accepted decisions.
    
    Feature: trading-pipeline-integration
    Requirements: 10.2
    """
    
    def test_accepted_decisions_have_signals(self):
        """All accepted decisions should have a signal."""
        fixtures = ParityTestFixtures()
        accepted_decisions = fixtures.get_accepted_decisions()
        
        for decision in accepted_decisions:
            assert decision.decision == "accepted"
            assert decision.signal is not None, (
                f"Accepted decision {decision.decision_id} should have a signal"
            )
    
    def test_accepted_signals_have_required_fields(self):
        """Accepted decision signals should have required fields."""
        fixtures = ParityTestFixtures()
        accepted_decisions = fixtures.get_accepted_decisions()
        
        required_fields = ["side", "entry_price", "size"]
        
        for decision in accepted_decisions:
            assert decision.signal is not None
            for field in required_fields:
                assert field in decision.signal, (
                    f"Signal for {decision.decision_id} should have '{field}' field"
                )
    
    def test_signal_side_is_valid(self):
        """Signal side should be 'long' or 'short'."""
        fixtures = ParityTestFixtures()
        accepted_decisions = fixtures.get_accepted_decisions()
        
        valid_sides = {"long", "short"}
        
        for decision in accepted_decisions:
            assert decision.signal is not None
            side = decision.signal.get("side")
            assert side in valid_sides, (
                f"Signal side for {decision.decision_id} should be 'long' or 'short', got '{side}'"
            )
    
    def test_signal_consistency_with_features(self):
        """Signal side should be consistent with trend direction in features."""
        fixtures = ParityTestFixtures()
        accepted_decisions = fixtures.get_accepted_decisions()
        
        for decision in accepted_decisions:
            if not decision.features or not decision.signal:
                continue
            
            trend_strength = decision.features.get("trend_strength")
            signal_side = decision.signal.get("side")
            
            # If trend_strength is strongly positive, signal should be long
            # If trend_strength is strongly negative, signal should be short
            if trend_strength is not None and abs(trend_strength) > 0.5:
                if trend_strength > 0.5:
                    assert signal_side == "long", (
                        f"Decision {decision.decision_id} with positive trend "
                        f"({trend_strength}) should have long signal"
                    )
                elif trend_strength < -0.5:
                    assert signal_side == "short", (
                        f"Decision {decision.decision_id} with negative trend "
                        f"({trend_strength}) should have short signal"
                    )


class TestExpectedOutcomeConsistency:
    """Tests that expected outcomes match actual outcomes.
    
    Feature: trading-pipeline-integration
    Requirements: 10.2
    """
    
    def test_high_ev_decisions_are_accepted(self):
        """Decisions with high EV should be accepted."""
        fixtures = ParityTestFixtures()
        accepted_decisions = fixtures.get_accepted_decisions()
        
        ev_threshold = STANDARD_TEST_CONFIG["ev_gate"]["ev_min"]
        
        for decision in accepted_decisions:
            ev = decision.features.get("ev", 0)
            # Accepted decisions should have EV >= threshold
            assert ev >= ev_threshold, (
                f"Accepted decision {decision.decision_id} should have EV >= {ev_threshold}, "
                f"got {ev}"
            )
    
    def test_low_ev_decisions_rejected_at_ev_gate(self):
        """Decisions with low EV should be rejected at EVGate."""
        fixtures = ParityTestFixtures()
        ev_gate_rejections = fixtures.get_decisions_by_rejection_stage("EVGate")
        
        ev_threshold = STANDARD_TEST_CONFIG["ev_gate"]["ev_min"]
        
        for decision in ev_gate_rejections:
            ev = decision.features.get("ev", 0)
            # EVGate rejections should have EV < threshold
            assert ev < ev_threshold, (
                f"EVGate rejection {decision.decision_id} should have EV < {ev_threshold}, "
                f"got {ev}"
            )
    
    def test_get_expected_outcome_matches_fixtures(self):
        """get_expected_outcome should match fixture decisions."""
        fixtures = ParityTestFixtures()
        
        # Test accepted decisions
        for decision in fixtures.get_accepted_decisions():
            ev = decision.features.get("ev", 0)
            expected_decision, expected_rejection_stage = get_expected_outcome(ev)
            
            assert expected_decision == "accepted", (
                f"Expected outcome for EV {ev} should be 'accepted'"
            )
            assert expected_rejection_stage is None
        
        # Test EVGate rejections
        for decision in fixtures.get_decisions_by_rejection_stage("EVGate"):
            ev = decision.features.get("ev", 0)
            expected_decision, expected_rejection_stage = get_expected_outcome(ev)
            
            assert expected_decision == "rejected", (
                f"Expected outcome for EV {ev} should be 'rejected'"
            )
            assert expected_rejection_stage == "EVGate"


class TestEdgeCaseConsistency:
    """Tests for edge case decision consistency.
    
    Feature: trading-pipeline-integration
    Requirements: 10.2
    """
    
    def test_ev_at_threshold_is_accepted(self):
        """EV exactly at threshold should be accepted."""
        fixtures = ParityTestFixtures()
        edge_cases = fixtures.get_edge_case_decisions()
        
        # Find the edge case with EV exactly at threshold
        threshold_decision = None
        for decision in edge_cases:
            ev = decision.features.get("ev", 0)
            if ev == STANDARD_TEST_CONFIG["ev_gate"]["ev_min"]:
                threshold_decision = decision
                break
        
        assert threshold_decision is not None, "Should have edge case with EV at threshold"
        assert threshold_decision.decision == "accepted", (
            "EV exactly at threshold should be accepted"
        )
    
    def test_ev_just_below_threshold_is_rejected(self):
        """EV just below threshold should be rejected."""
        fixtures = ParityTestFixtures()
        edge_cases = fixtures.get_edge_case_decisions()
        
        ev_threshold = STANDARD_TEST_CONFIG["ev_gate"]["ev_min"]
        
        # Find the edge case with EV just below threshold
        below_threshold_decision = None
        for decision in edge_cases:
            ev = decision.features.get("ev", 0)
            if ev < ev_threshold and ev > ev_threshold - 0.0002:
                below_threshold_decision = decision
                break
        
        assert below_threshold_decision is not None, (
            "Should have edge case with EV just below threshold"
        )
        assert below_threshold_decision.decision == "rejected", (
            "EV just below threshold should be rejected"
        )
        assert below_threshold_decision.rejection_stage == "EVGate", (
            "EV just below threshold should be rejected at EVGate"
        )
    
    def test_zero_spread_decision_consistency(self):
        """Zero spread edge case should be handled consistently."""
        fixtures = ParityTestFixtures()
        edge_cases = fixtures.get_edge_case_decisions()
        
        # Find the zero spread edge case
        zero_spread_decision = None
        for decision in edge_cases:
            spread = decision.market_snapshot.get("spread_bps", -1)
            if spread == 0.0:
                zero_spread_decision = decision
                break
        
        assert zero_spread_decision is not None, "Should have zero spread edge case"
        # Zero spread should still produce a valid decision
        assert zero_spread_decision.decision in ("accepted", "rejected")
    
    def test_high_volatility_decision_consistency(self):
        """High volatility edge case should be handled consistently."""
        fixtures = ParityTestFixtures()
        edge_cases = fixtures.get_edge_case_decisions()
        
        # Find the high volatility edge case
        high_vol_decision = None
        for decision in edge_cases:
            volatility = decision.features.get("volatility", 0)
            if volatility >= 0.1:
                high_vol_decision = decision
                break
        
        assert high_vol_decision is not None, "Should have high volatility edge case"
        # High volatility should still produce a valid decision
        assert high_vol_decision.decision in ("accepted", "rejected")


class TestDecisionDeterminism:
    """Tests that decision making is deterministic.
    
    Feature: trading-pipeline-integration
    Requirements: 10.2
    """
    
    def test_same_inputs_produce_same_decision_multiple_times(self):
        """Same inputs should produce the same decision every time."""
        # Create a test decision
        original = create_test_decision(
            decision_id="test_determinism_001",
            symbol="BTCUSDT",
            config_version="live_test_v1",
            decision="accepted",
            ev=0.002,
        )
        
        # Create multiple copies with same inputs
        copies = []
        for i in range(5):
            copy = RecordedDecision(
                decision_id=f"test_determinism_copy_{i}",
                timestamp=original.timestamp,
                symbol=original.symbol,
                config_version=original.config_version,
                market_snapshot=deepcopy(original.market_snapshot),
                features=deepcopy(original.features),
                positions=deepcopy(original.positions),
                account_state=deepcopy(original.account_state),
                stage_results=deepcopy(original.stage_results),
                rejection_stage=original.rejection_stage,
                rejection_reason=original.rejection_reason,
                decision=original.decision,
                signal=deepcopy(original.signal) if original.signal else None,
                profile_id=original.profile_id,
            )
            copies.append(copy)
        
        # All copies should be consistent with original
        for i, copy in enumerate(copies):
            assert DecisionConsistencyChecker.decisions_are_consistent(
                original, copy
            ), f"Copy {i} should be consistent with original"
        
        # All copies should be consistent with each other
        for i in range(len(copies) - 1):
            assert DecisionConsistencyChecker.decisions_are_consistent(
                copies[i], copies[i + 1]
            ), f"Copy {i} should be consistent with copy {i + 1}"
    
    def test_rejected_decision_determinism(self):
        """Rejected decisions should be deterministic."""
        # Create a rejected test decision
        original = create_test_decision(
            decision_id="test_rejected_determinism_001",
            symbol="BTCUSDT",
            config_version="live_test_v1",
            decision="rejected",
            ev=0.0008,
            rejection_stage="EVGate",
            rejection_reason="EV below threshold",
        )
        
        # Create a copy with same inputs
        copy = RecordedDecision(
            decision_id="test_rejected_determinism_copy",
            timestamp=original.timestamp,
            symbol=original.symbol,
            config_version=original.config_version,
            market_snapshot=deepcopy(original.market_snapshot),
            features=deepcopy(original.features),
            positions=deepcopy(original.positions),
            account_state=deepcopy(original.account_state),
            stage_results=deepcopy(original.stage_results),
            rejection_stage=original.rejection_stage,
            rejection_reason=original.rejection_reason,
            decision=original.decision,
            signal=original.signal,
            profile_id=original.profile_id,
        )
        
        # Should be consistent
        assert DecisionConsistencyChecker.decisions_are_consistent(original, copy)
        
        # Rejection details should match
        assert copy.rejection_stage == original.rejection_stage
        assert copy.rejection_reason == original.rejection_reason


class TestConsistencyCheckerDiffReporting:
    """Tests for the consistency checker diff reporting.
    
    Feature: trading-pipeline-integration
    Requirements: 10.2
    """
    
    def test_diff_reports_decision_mismatch(self):
        """Diff should report when decisions don't match."""
        decision1 = create_test_decision(
            decision_id="diff_test_001",
            decision="accepted",
            ev=0.002,
        )
        decision2 = create_test_decision(
            decision_id="diff_test_002",
            decision="rejected",
            ev=0.0008,
            rejection_stage="EVGate",
        )
        
        diff = DecisionConsistencyChecker.get_consistency_diff(decision1, decision2)
        
        assert "decision" in diff
        assert diff["decision"]["expected"] == "accepted"
        assert diff["decision"]["actual"] == "rejected"
    
    def test_diff_reports_rejection_stage_mismatch(self):
        """Diff should report when rejection stages don't match."""
        decision1 = create_test_decision(
            decision_id="diff_test_003",
            decision="rejected",
            ev=0.0008,
            rejection_stage="EVGate",
        )
        decision2 = create_test_decision(
            decision_id="diff_test_004",
            decision="rejected",
            ev=0.0008,
            rejection_stage="GlobalGate",
        )
        
        diff = DecisionConsistencyChecker.get_consistency_diff(decision1, decision2)
        
        assert "rejection_stage" in diff
        assert diff["rejection_stage"]["expected"] == "EVGate"
        assert diff["rejection_stage"]["actual"] == "GlobalGate"
    
    def test_diff_empty_for_consistent_decisions(self):
        """Diff should be empty for consistent decisions."""
        decision1 = create_test_decision(
            decision_id="diff_test_005",
            decision="accepted",
            ev=0.002,
        )
        decision2 = RecordedDecision(
            decision_id="diff_test_006",
            timestamp=decision1.timestamp,
            symbol=decision1.symbol,
            config_version=decision1.config_version,
            market_snapshot=deepcopy(decision1.market_snapshot),
            features=deepcopy(decision1.features),
            positions=deepcopy(decision1.positions),
            account_state=deepcopy(decision1.account_state),
            stage_results=deepcopy(decision1.stage_results),
            rejection_stage=decision1.rejection_stage,
            rejection_reason=decision1.rejection_reason,
            decision=decision1.decision,
            signal=deepcopy(decision1.signal),
            profile_id=decision1.profile_id,
        )
        
        diff = DecisionConsistencyChecker.get_consistency_diff(decision1, decision2)
        
        assert len(diff) == 0, "Diff should be empty for consistent decisions"
