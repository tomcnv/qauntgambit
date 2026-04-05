"""Property-based tests for StageRejectionDiagnostics.

Feature: backtest-pipeline-unification, Property 5: Rejection Recording

Tests that:
- Rejections are recorded with stage name
- Stage-level counts are incremented correctly

Validates: Requirements 4.1, 4.3
"""

import pytest
from hypothesis import given, strategies as st, settings

from quantgambit.backtesting.stage_rejection_diagnostics import (
    StageRejectionDiagnostics,
    create_diagnostics_from_context,
)


# =============================================================================
# Strategies for generating test data
# =============================================================================

# Generate stage names
stage_name_strategy = st.sampled_from([
    "data_readiness",
    "global_gate",
    "strategy_trend_alignment",
    "ev_gate",
    "fee_aware_entry",
    "session_filter",
    "candidate_veto",
    "cooldown",
    "confidence_gate",
    "risk_stage",
    "custom_stage",
])

# Generate rejection reasons
reason_strategy = st.sampled_from([
    "spread_too_wide",
    "depth_too_thin",
    "counter_trend",
    "low_ev",
    "session_blocked",
    "cooldown_active",
    None,
])

# Generate symbols
symbol_strategy = st.sampled_from(["BTCUSDT", "ETHUSDT", "SOLUSDT", None])


# =============================================================================
# Property Tests
# =============================================================================

class TestStageRejectionDiagnosticsProperties:
    """Property-based tests for StageRejectionDiagnostics.
    
    Feature: backtest-pipeline-unification, Property 5: Rejection Recording
    """
    
    @given(
        stage_name=stage_name_strategy,
        reason=reason_strategy,
        symbol=symbol_strategy,
    )
    @settings(max_examples=100)
    def test_rejection_recorded_with_stage_name(
        self,
        stage_name: str,
        reason,
        symbol,
    ):
        """Property: Rejections are recorded with stage name.
        
        For any rejection, the stage name SHALL be recorded in by_stage.
        
        Validates: Requirements 4.1
        """
        diagnostics = StageRejectionDiagnostics()
        
        diagnostics.record_rejection(
            stage_name=stage_name,
            reason=reason,
            symbol=symbol,
        )
        
        assert stage_name in diagnostics.by_stage, (
            f"Stage '{stage_name}' not recorded in by_stage"
        )
        assert diagnostics.by_stage[stage_name] == 1
    
    @given(
        stage_name=stage_name_strategy,
        num_rejections=st.integers(min_value=1, max_value=100),
    )
    @settings(max_examples=100)
    def test_stage_counts_increment_correctly(
        self,
        stage_name: str,
        num_rejections: int,
    ):
        """Property: Stage-level counts are incremented correctly.
        
        For any number of rejections from a stage, the count SHALL equal
        the number of times record_rejection was called.
        
        Validates: Requirements 4.3
        """
        diagnostics = StageRejectionDiagnostics()
        
        for _ in range(num_rejections):
            diagnostics.record_rejection(stage_name=stage_name)
        
        assert diagnostics.by_stage[stage_name] == num_rejections
        assert diagnostics.total_rejections == num_rejections
    
    @given(
        rejections=st.lists(
            st.tuples(stage_name_strategy, reason_strategy),
            min_size=1,
            max_size=50,
        ),
    )
    @settings(max_examples=100)
    def test_total_rejections_equals_sum_of_stages(
        self,
        rejections: list,
    ):
        """Property: Total rejections equals sum of all stage counts.
        
        For any set of rejections, total_rejections SHALL equal the sum
        of all by_stage counts.
        
        Validates: Requirements 4.2
        """
        diagnostics = StageRejectionDiagnostics()
        
        for stage_name, reason in rejections:
            diagnostics.record_rejection(stage_name=stage_name, reason=reason)
        
        sum_of_stages = sum(diagnostics.by_stage.values())
        
        assert diagnostics.total_rejections == sum_of_stages
        assert diagnostics.total_rejections == len(rejections)
    
    @given(
        reason=st.text(min_size=1, max_size=50).filter(lambda x: x.strip()),
        num_rejections=st.integers(min_value=1, max_value=50),
    )
    @settings(max_examples=100)
    def test_reason_counts_increment_correctly(
        self,
        reason: str,
        num_rejections: int,
    ):
        """Property: Reason counts are incremented correctly.
        
        For any number of rejections with the same reason, the count SHALL
        equal the number of times that reason was recorded.
        """
        diagnostics = StageRejectionDiagnostics()
        
        for _ in range(num_rejections):
            diagnostics.record_rejection(
                stage_name="test_stage",
                reason=reason,
            )
        
        assert diagnostics.by_reason[reason] == num_rejections
    
    @given(
        rejections=st.lists(
            st.tuples(stage_name_strategy, reason_strategy, symbol_strategy),
            min_size=0,
            max_size=50,
        ),
    )
    @settings(max_examples=100)
    def test_summary_contains_all_stages(
        self,
        rejections: list,
    ):
        """Property: Summary contains all recorded stages.
        
        For any set of rejections, get_summary() SHALL include all stages
        that had rejections.
        """
        diagnostics = StageRejectionDiagnostics()
        
        recorded_stages = set()
        for stage_name, reason, symbol in rejections:
            diagnostics.record_rejection(
                stage_name=stage_name,
                reason=reason,
                symbol=symbol,
            )
            recorded_stages.add(stage_name)
        
        summary = diagnostics.get_summary()
        
        for stage in recorded_stages:
            assert stage in summary["by_stage"], (
                f"Stage '{stage}' missing from summary"
            )
    
    @given(
        stage_name=st.sampled_from([
            "data_readiness",
            "global_gate",
            "strategy_trend_alignment",
            "ev_gate",
        ]),
        num_rejections=st.integers(min_value=1, max_value=20),
    )
    @settings(max_examples=100)
    def test_known_stage_counters_updated(
        self,
        stage_name: str,
        num_rejections: int,
    ):
        """Property: Known stage counters are updated.
        
        For known stages, the specific counter attribute SHALL be updated.
        """
        diagnostics = StageRejectionDiagnostics()
        
        for _ in range(num_rejections):
            diagnostics.record_rejection(stage_name=stage_name)
        
        # Get the counter attribute
        counter_value = getattr(diagnostics, stage_name)
        
        assert counter_value == num_rejections, (
            f"Counter for '{stage_name}' is {counter_value}, expected {num_rejections}"
        )


# =============================================================================
# Unit Tests for Edge Cases
# =============================================================================

class TestStageRejectionDiagnosticsEdgeCases:
    """Unit tests for edge cases."""
    
    def test_empty_diagnostics(self):
        """Empty diagnostics should have zero counts."""
        diagnostics = StageRejectionDiagnostics()
        
        assert diagnostics.total_rejections == 0
        assert len(diagnostics.by_stage) == 0
        assert len(diagnostics.by_reason) == 0
    
    def test_reset_clears_all(self):
        """Reset should clear all counters."""
        diagnostics = StageRejectionDiagnostics()
        
        diagnostics.record_rejection("global_gate", "spread_too_wide")
        diagnostics.record_rejection("strategy_trend_alignment", "counter_trend")
        
        diagnostics.reset()
        
        assert diagnostics.total_rejections == 0
        assert len(diagnostics.by_stage) == 0
        assert diagnostics.global_gate == 0
        assert diagnostics.strategy_trend_alignment == 0
    
    def test_merge_combines_diagnostics(self):
        """Merge should combine two diagnostics instances."""
        diag1 = StageRejectionDiagnostics()
        diag2 = StageRejectionDiagnostics()
        
        diag1.record_rejection("global_gate", "spread_too_wide")
        diag1.record_rejection("global_gate", "spread_too_wide")
        
        diag2.record_rejection("global_gate", "depth_too_thin")
        diag2.record_rejection("strategy_trend_alignment", "counter_trend")
        
        diag1.merge(diag2)
        
        assert diag1.total_rejections == 4
        assert diag1.by_stage["global_gate"] == 3
        assert diag1.by_stage["strategy_trend_alignment"] == 1
        assert diag1.global_gate == 3
        assert diag1.strategy_trend_alignment == 1
    
    def test_top_rejection_stages(self):
        """Top rejection stages should be sorted by count."""
        diagnostics = StageRejectionDiagnostics()
        
        for _ in range(10):
            diagnostics.record_rejection("global_gate")
        for _ in range(5):
            diagnostics.record_rejection("strategy_trend_alignment")
        for _ in range(3):
            diagnostics.record_rejection("ev_gate")
        
        top = diagnostics.get_top_rejection_stages(2)
        
        assert len(top) == 2
        assert top[0] == ("global_gate", 10)
        assert top[1] == ("strategy_trend_alignment", 5)
    
    def test_human_readable_summary(self):
        """Human readable summary should be formatted correctly."""
        diagnostics = StageRejectionDiagnostics()
        
        diagnostics.record_rejection("global_gate", "spread_too_wide")
        diagnostics.record_rejection("strategy_trend_alignment", "counter_trend")
        
        summary = diagnostics.get_human_readable_summary()
        
        assert "Total rejections: 2" in summary
        assert "global_gate" in summary
        assert "strategy_trend_alignment" in summary
    
    def test_recent_rejections_limited(self):
        """Recent rejections should be limited to max_recent_rejections."""
        diagnostics = StageRejectionDiagnostics()
        diagnostics.max_recent_rejections = 10
        
        for i in range(20):
            diagnostics.record_rejection(f"stage_{i}")
        
        assert len(diagnostics.recent_rejections) == 10
    
    def test_none_reason_not_recorded(self):
        """None reason should not be recorded in by_reason."""
        diagnostics = StageRejectionDiagnostics()
        
        diagnostics.record_rejection("global_gate", reason=None)
        
        assert len(diagnostics.by_reason) == 0
        assert diagnostics.total_rejections == 1
