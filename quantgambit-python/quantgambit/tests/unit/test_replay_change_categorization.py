"""Unit tests for replay change categorization.

Feature: trading-pipeline-integration
Requirements: 7.3 - THE System SHALL report decision changes with categorization
              (expected, unexpected, improved, degraded)
Requirements: 7.6 - WHEN replay detects unexpected decision changes THEN the
              System SHALL provide detailed diff showing which stage caused
              the change
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock, AsyncMock

import pytest

from quantgambit.integration.replay_validation import (
    categorize_change,
    identify_stage_diff,
    aggregate_changes,
    ReplayResult,
    ReplayReport,
    VALID_CHANGE_CATEGORIES,
)
from quantgambit.integration.decision_recording import RecordedDecision


class TestCategorizeChange:
    """Tests for the categorize_change helper function.
    
    Feature: trading-pipeline-integration
    Requirements: 7.3
    """
    
    def test_expected_when_both_accepted(self):
        """When both decisions are accepted, category should be 'expected'."""
        result = categorize_change("accepted", "accepted")
        assert result == "expected"
    
    def test_expected_when_both_rejected(self):
        """When both decisions are rejected, category should be 'expected'."""
        result = categorize_change("rejected", "rejected")
        assert result == "expected"
    
    def test_improved_when_rejected_to_accepted(self):
        """When original was rejected and replay is accepted, category should be 'improved'.
        
        This represents a potential improvement where the pipeline is now
        accepting previously rejected decisions.
        """
        result = categorize_change("rejected", "accepted")
        assert result == "improved"
    
    def test_degraded_when_accepted_to_rejected(self):
        """When original was accepted and replay is rejected, category should be 'degraded'.
        
        This represents a potential regression where the pipeline is now
        rejecting previously accepted decisions.
        """
        result = categorize_change("accepted", "rejected")
        assert result == "degraded"
    
    def test_unexpected_for_shadow_changes(self):
        """When shadow decisions change, category should be 'unexpected'."""
        # Shadow to accepted
        result = categorize_change("shadow", "accepted")
        assert result == "unexpected"
        
        # Shadow to rejected
        result = categorize_change("shadow", "rejected")
        assert result == "unexpected"
        
        # Accepted to shadow
        result = categorize_change("accepted", "shadow")
        assert result == "unexpected"
        
        # Rejected to shadow
        result = categorize_change("rejected", "shadow")
        assert result == "unexpected"
    
    def test_expected_when_shadow_unchanged(self):
        """When shadow decisions remain shadow, category should be 'expected'."""
        result = categorize_change("shadow", "shadow")
        assert result == "expected"
    
    def test_all_valid_categories_returned(self):
        """All returned categories should be valid."""
        test_cases = [
            ("accepted", "accepted"),
            ("rejected", "rejected"),
            ("rejected", "accepted"),
            ("accepted", "rejected"),
            ("shadow", "accepted"),
            ("shadow", "rejected"),
        ]
        
        for original, replayed in test_cases:
            result = categorize_change(original, replayed)
            assert result in VALID_CHANGE_CATEGORIES, \
                f"Invalid category '{result}' for {original}->{replayed}"


class TestIdentifyStageDiff:
    """Tests for the identify_stage_diff helper function.
    
    Feature: trading-pipeline-integration
    Requirements: 7.6
    """
    
    def test_no_diff_when_same_stage(self):
        """When stages are the same, should return None."""
        result = identify_stage_diff("ev_gate", "ev_gate")
        assert result is None
    
    def test_no_diff_when_both_none(self):
        """When both stages are None (both accepted), should return None."""
        result = identify_stage_diff(None, None)
        assert result is None
    
    def test_diff_format_when_stages_differ(self):
        """When stages differ, should return '{original}->{replayed}' format."""
        result = identify_stage_diff("ev_gate", "confirmation")
        assert result == "ev_gate->confirmation"
    
    def test_diff_when_original_none(self):
        """When original was accepted (None) and replay rejected, should show 'none->{stage}'."""
        result = identify_stage_diff(None, "ev_gate")
        assert result == "none->ev_gate"
    
    def test_diff_when_replayed_none(self):
        """When original was rejected and replay accepted (None), should show '{stage}->none'."""
        result = identify_stage_diff("ev_gate", None)
        assert result == "ev_gate->none"
    
    def test_diff_with_various_stages(self):
        """Test diff format with various stage names."""
        test_cases = [
            ("data_readiness", "ev_gate", "data_readiness->ev_gate"),
            ("ev_gate", "confirmation", "ev_gate->confirmation"),
            ("confirmation", "arbitration", "confirmation->arbitration"),
            ("arbitration", "execution_feasibility", "arbitration->execution_feasibility"),
        ]
        
        for original, replayed, expected in test_cases:
            result = identify_stage_diff(original, replayed)
            assert result == expected


class TestAggregateChanges:
    """Tests for the aggregate_changes helper function.
    
    Feature: trading-pipeline-integration
    Requirements: 7.3
    """
    
    @pytest.fixture
    def sample_decision(self):
        """Create a sample RecordedDecision for testing."""
        return RecordedDecision(
            decision_id="dec_test",
            timestamp=datetime.now(timezone.utc),
            symbol="BTCUSDT",
            config_version="v1",
            decision="accepted",
        )
    
    def test_empty_results(self, sample_decision):
        """Empty results should return empty dictionaries."""
        by_category, by_stage = aggregate_changes([])
        assert by_category == {}
        assert by_stage == {}
    
    def test_all_matches(self, sample_decision):
        """When all results match, should return empty dictionaries."""
        results = [
            ReplayResult(
                original_decision=sample_decision,
                replayed_decision="accepted",
                matches=True,
                change_category="expected",
            ),
            ReplayResult(
                original_decision=sample_decision,
                replayed_decision="accepted",
                matches=True,
                change_category="expected",
            ),
        ]
        
        by_category, by_stage = aggregate_changes(results)
        assert by_category == {}
        assert by_stage == {}
    
    def test_single_improvement(self, sample_decision):
        """Single improvement should be counted correctly."""
        rejected_decision = RecordedDecision(
            decision_id="dec_rejected",
            timestamp=datetime.now(timezone.utc),
            symbol="BTCUSDT",
            config_version="v1",
            decision="rejected",
            rejection_stage="ev_gate",
        )
        
        results = [
            ReplayResult(
                original_decision=rejected_decision,
                replayed_decision="accepted",
                matches=False,
                change_category="improved",
                stage_diff="ev_gate->none",
            ),
        ]
        
        by_category, by_stage = aggregate_changes(results)
        assert by_category == {"improved": 1}
        assert by_stage == {"ev_gate->none": 1}
    
    def test_single_degradation(self, sample_decision):
        """Single degradation should be counted correctly."""
        results = [
            ReplayResult(
                original_decision=sample_decision,
                replayed_decision="rejected",
                replayed_rejection_stage="ev_gate",
                matches=False,
                change_category="degraded",
                stage_diff="none->ev_gate",
            ),
        ]
        
        by_category, by_stage = aggregate_changes(results)
        assert by_category == {"degraded": 1}
        assert by_stage == {"none->ev_gate": 1}
    
    def test_mixed_changes(self, sample_decision):
        """Mixed changes should be aggregated correctly."""
        rejected_decision = RecordedDecision(
            decision_id="dec_rejected",
            timestamp=datetime.now(timezone.utc),
            symbol="BTCUSDT",
            config_version="v1",
            decision="rejected",
            rejection_stage="ev_gate",
        )
        
        results = [
            # Match - should not be counted
            ReplayResult(
                original_decision=sample_decision,
                replayed_decision="accepted",
                matches=True,
                change_category="expected",
            ),
            # Improvement
            ReplayResult(
                original_decision=rejected_decision,
                replayed_decision="accepted",
                matches=False,
                change_category="improved",
                stage_diff="ev_gate->none",
            ),
            # Degradation
            ReplayResult(
                original_decision=sample_decision,
                replayed_decision="rejected",
                replayed_rejection_stage="confirmation",
                matches=False,
                change_category="degraded",
                stage_diff="none->confirmation",
            ),
            # Another improvement with same stage diff
            ReplayResult(
                original_decision=rejected_decision,
                replayed_decision="accepted",
                matches=False,
                change_category="improved",
                stage_diff="ev_gate->none",
            ),
        ]
        
        by_category, by_stage = aggregate_changes(results)
        
        assert by_category == {"improved": 2, "degraded": 1}
        assert by_stage == {"ev_gate->none": 2, "none->confirmation": 1}
    
    def test_changes_without_stage_diff(self, sample_decision):
        """Changes without stage_diff should only count in category."""
        results = [
            ReplayResult(
                original_decision=sample_decision,
                replayed_decision="rejected",
                matches=False,
                change_category="unexpected",
                stage_diff=None,  # No stage diff
            ),
        ]
        
        by_category, by_stage = aggregate_changes(results)
        assert by_category == {"unexpected": 1}
        assert by_stage == {}


class TestReplayResultChangeCategorization:
    """Tests for ReplayResult change categorization integration.
    
    Feature: trading-pipeline-integration
    Requirements: 7.3
    """
    
    @pytest.fixture
    def accepted_decision(self):
        """Create an accepted RecordedDecision."""
        return RecordedDecision(
            decision_id="dec_accepted",
            timestamp=datetime.now(timezone.utc),
            symbol="BTCUSDT",
            config_version="v1",
            decision="accepted",
            signal={"side": "buy", "size": 0.1},
        )
    
    @pytest.fixture
    def rejected_decision(self):
        """Create a rejected RecordedDecision."""
        return RecordedDecision(
            decision_id="dec_rejected",
            timestamp=datetime.now(timezone.utc),
            symbol="BTCUSDT",
            config_version="v1",
            decision="rejected",
            rejection_stage="ev_gate",
            rejection_reason="EV below threshold",
        )
    
    def test_replay_result_improvement_helpers(self, rejected_decision):
        """ReplayResult helper methods should correctly identify improvements."""
        result = ReplayResult(
            original_decision=rejected_decision,
            replayed_decision="accepted",
            matches=False,
            change_category="improved",
            stage_diff="ev_gate->none",
        )
        
        assert result.is_improvement() is True
        assert result.is_degradation() is False
        assert result.is_unexpected() is False
    
    def test_replay_result_degradation_helpers(self, accepted_decision):
        """ReplayResult helper methods should correctly identify degradations."""
        result = ReplayResult(
            original_decision=accepted_decision,
            replayed_decision="rejected",
            replayed_rejection_stage="ev_gate",
            matches=False,
            change_category="degraded",
            stage_diff="none->ev_gate",
        )
        
        assert result.is_degradation() is True
        assert result.is_improvement() is False
        assert result.is_unexpected() is False
    
    def test_replay_result_unexpected_helpers(self, accepted_decision):
        """ReplayResult helper methods should correctly identify unexpected changes."""
        # Create a result where the change is unexpected (e.g., different rejection stage)
        result = ReplayResult(
            original_decision=accepted_decision,
            replayed_decision="rejected",
            replayed_rejection_stage="ev_gate",
            matches=False,
            change_category="unexpected",  # Manually set to unexpected for testing
        )
        
        assert result.is_unexpected() is True
        assert result.is_improvement() is False
        assert result.is_degradation() is False
    
    def test_replay_result_validation_rejects_invalid_category(self, accepted_decision):
        """ReplayResult should reject invalid change categories."""
        with pytest.raises(ValueError) as exc_info:
            ReplayResult(
                original_decision=accepted_decision,
                replayed_decision="accepted",
                matches=True,
                change_category="invalid_category",
            )
        
        assert "change_category must be one of" in str(exc_info.value)


class TestReplayReportChangeCategorization:
    """Tests for ReplayReport change categorization integration.
    
    Feature: trading-pipeline-integration
    Requirements: 7.3
    """
    
    def test_report_has_degradations(self):
        """has_degradations should return True when degraded changes exist."""
        report = ReplayReport(
            total_replayed=10,
            matches=8,
            changes=2,
            match_rate=0.8,
            changes_by_category={"degraded": 2},
        )
        
        assert report.has_degradations() is True
        assert report.get_degradation_count() == 2
    
    def test_report_has_improvements(self):
        """has_improvements should return True when improved changes exist."""
        report = ReplayReport(
            total_replayed=10,
            matches=8,
            changes=2,
            match_rate=0.8,
            changes_by_category={"improved": 2},
        )
        
        assert report.has_improvements() is True
        assert report.get_improvement_count() == 2
    
    def test_report_has_unexpected_changes(self):
        """has_unexpected_changes should return True when unexpected changes exist."""
        report = ReplayReport(
            total_replayed=10,
            matches=9,
            changes=1,
            match_rate=0.9,
            changes_by_category={"unexpected": 1},
        )
        
        assert report.has_unexpected_changes() is True
        assert report.get_unexpected_count() == 1
    
    def test_report_is_passing_with_low_degradation(self):
        """is_passing should return True when degradation rate is below threshold."""
        report = ReplayReport(
            total_replayed=100,
            matches=96,
            changes=4,
            match_rate=0.96,
            changes_by_category={"degraded": 4},  # 4% degradation
        )
        
        assert report.is_passing(max_degradation_rate=0.05) is True
    
    def test_report_is_failing_with_high_degradation(self):
        """is_passing should return False when degradation rate exceeds threshold."""
        report = ReplayReport(
            total_replayed=100,
            matches=90,
            changes=10,
            match_rate=0.90,
            changes_by_category={"degraded": 10},  # 10% degradation
        )
        
        assert report.is_passing(max_degradation_rate=0.05) is False
    
    def test_report_validation_rejects_invalid_category(self):
        """ReplayReport should reject invalid change categories."""
        with pytest.raises(ValueError) as exc_info:
            ReplayReport(
                total_replayed=10,
                matches=9,
                changes=1,
                match_rate=0.9,
                changes_by_category={"invalid": 1},
            )
        
        assert "Invalid change category" in str(exc_info.value)
    
    def test_report_summary_includes_categories(self):
        """get_summary should include change categories."""
        report = ReplayReport(
            total_replayed=100,
            matches=95,
            changes=5,
            match_rate=0.95,
            changes_by_category={"improved": 3, "degraded": 2},
            changes_by_stage={"ev_gate->none": 3, "none->ev_gate": 2},
        )
        
        summary = report.get_summary()
        
        assert "improved: 3" in summary
        assert "degraded: 2" in summary
        assert "ev_gate->none: 3" in summary
        assert "none->ev_gate: 2" in summary


class TestRequirements:
    """Tests verifying requirements compliance.
    
    Feature: trading-pipeline-integration
    """
    
    def test_requirement_7_3_change_categorization(self):
        """Requirement 7.3: Report decision changes with categorization.
        
        THE System SHALL report decision changes with categorization
        (expected, unexpected, improved, degraded).
        """
        # Verify all four categories are supported
        assert "expected" in VALID_CHANGE_CATEGORIES
        assert "unexpected" in VALID_CHANGE_CATEGORIES
        assert "improved" in VALID_CHANGE_CATEGORIES
        assert "degraded" in VALID_CHANGE_CATEGORIES
        
        # Verify categorize_change returns correct categories
        assert categorize_change("accepted", "accepted") == "expected"
        assert categorize_change("rejected", "accepted") == "improved"
        assert categorize_change("accepted", "rejected") == "degraded"
        assert categorize_change("shadow", "accepted") == "unexpected"
    
    def test_requirement_7_6_stage_diff_identification(self):
        """Requirement 7.6: Provide detailed diff showing which stage caused change.
        
        WHEN replay detects unexpected decision changes THEN the System SHALL
        provide detailed diff showing which stage caused the change.
        """
        # Verify stage diff format
        diff = identify_stage_diff("ev_gate", "confirmation")
        assert diff == "ev_gate->confirmation"
        
        # Verify None handling
        diff = identify_stage_diff(None, "ev_gate")
        assert diff == "none->ev_gate"
        
        diff = identify_stage_diff("ev_gate", None)
        assert diff == "ev_gate->none"
        
        # Verify no diff when stages match
        diff = identify_stage_diff("ev_gate", "ev_gate")
        assert diff is None
