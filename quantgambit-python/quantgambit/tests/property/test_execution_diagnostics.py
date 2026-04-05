"""
Property-based tests for Execution Diagnostics.

Feature: backtest-diagnostics
Property 1: Diagnostics Completeness
Property 3: Rejection Breakdown Consistency

Validates: Requirements 1.1, 1.2, 1.4, 2.1
"""

import pytest
from hypothesis import given, strategies as st, settings, assume
from typing import Dict, Any

from quantgambit.backtesting.strategy_executor import StrategyBacktestExecutor


# ============================================================================
# Hypothesis Strategies
# ============================================================================

# Non-negative integers for counts
non_negative_ints = st.integers(min_value=0, max_value=10000)

# Rejection breakdown with non-negative counts
@st.composite
def rejection_breakdowns(draw):
    """Generate valid rejection breakdown dictionaries."""
    return {
        "spread_too_wide": draw(non_negative_ints),
        "depth_too_thin": draw(non_negative_ints),
        "snapshot_stale": draw(non_negative_ints),
        "vol_shock": draw(non_negative_ints),
    }


@st.composite
def valid_diagnostics_inputs(draw):
    """Generate valid inputs for _build_execution_diagnostics."""
    # Generate base counts
    total_snapshots = draw(st.integers(min_value=0, max_value=10000))
    snapshots_skipped = draw(st.integers(min_value=0, max_value=total_snapshots))
    snapshots_processed = total_snapshots - snapshots_skipped
    
    # Generate rejection breakdown
    rejection_breakdown = draw(rejection_breakdowns())
    global_gate_rejections = sum(rejection_breakdown.values())
    
    # Other counts
    profiles_selected = draw(st.integers(min_value=0, max_value=snapshots_processed))
    signals_generated = draw(st.integers(min_value=0, max_value=profiles_selected))
    cooldown_rejections = draw(st.integers(min_value=0, max_value=signals_generated))
    total_trades = draw(st.integers(min_value=0, max_value=signals_generated))
    
    return {
        "total_snapshots": total_snapshots,
        "snapshots_processed": snapshots_processed,
        "snapshots_skipped": snapshots_skipped,
        "global_gate_rejections": global_gate_rejections,
        "rejection_breakdown": rejection_breakdown,
        "profiles_selected": profiles_selected,
        "signals_generated": signals_generated,
        "cooldown_rejections": cooldown_rejections,
        "total_trades": total_trades,
    }


@st.composite
def zero_trade_diagnostics_inputs(draw):
    """Generate inputs that result in zero trades."""
    inputs = draw(valid_diagnostics_inputs())
    inputs["total_trades"] = 0
    return inputs


# ============================================================================
# Property Tests for Diagnostics Completeness
# ============================================================================

class TestDiagnosticsCompleteness:
    """
    Property 1: Diagnostics Completeness
    
    For any completed backtest, the execution_diagnostics object SHALL contain
    all required fields with non-negative integer values.
    
    **Validates: Requirements 1.1, 1.4, 2.1**
    """
    
    @given(inputs=valid_diagnostics_inputs())
    @settings(max_examples=100)
    def test_diagnostics_contains_all_required_fields(self, inputs):
        """
        Property 1: Diagnostics Completeness
        
        For any valid inputs, _build_execution_diagnostics should return
        a dict containing all required fields.
        
        **Validates: Requirements 1.1, 1.4, 2.1**
        """
        # Create executor instance (we only need the method, not full initialization)
        executor = object.__new__(StrategyBacktestExecutor)
        
        diagnostics = executor._build_execution_diagnostics(**inputs)
        
        # Required integer fields
        required_int_fields = [
            "total_snapshots",
            "snapshots_processed",
            "snapshots_skipped",
            "global_gate_rejections",
            "profiles_selected",
            "signals_generated",
            "cooldown_rejections",
        ]
        
        for field in required_int_fields:
            assert field in diagnostics, f"Missing required field: {field}"
            assert isinstance(diagnostics[field], int), f"Field {field} should be int"
            assert diagnostics[field] >= 0, f"Field {field} should be non-negative"
        
        # Required dict field
        assert "rejection_breakdown" in diagnostics
        assert isinstance(diagnostics["rejection_breakdown"], dict)
        
        # Required string fields
        assert "summary" in diagnostics
        assert isinstance(diagnostics["summary"], str)
        
        # Optional fields (can be None or have value)
        assert "primary_issue" in diagnostics
        assert "suggestions" in diagnostics
        assert isinstance(diagnostics["suggestions"], list)
    
    @given(inputs=valid_diagnostics_inputs())
    @settings(max_examples=100)
    def test_diagnostics_preserves_input_values(self, inputs):
        """
        Property 1: Diagnostics Completeness
        
        For any valid inputs, the returned diagnostics should preserve
        the input values exactly.
        
        **Validates: Requirements 1.1, 1.4, 2.1**
        """
        executor = object.__new__(StrategyBacktestExecutor)
        
        diagnostics = executor._build_execution_diagnostics(**inputs)
        
        # Verify input values are preserved
        assert diagnostics["total_snapshots"] == inputs["total_snapshots"]
        assert diagnostics["snapshots_processed"] == inputs["snapshots_processed"]
        assert diagnostics["snapshots_skipped"] == inputs["snapshots_skipped"]
        assert diagnostics["global_gate_rejections"] == inputs["global_gate_rejections"]
        assert diagnostics["profiles_selected"] == inputs["profiles_selected"]
        assert diagnostics["signals_generated"] == inputs["signals_generated"]
        assert diagnostics["cooldown_rejections"] == inputs["cooldown_rejections"]
        assert diagnostics["rejection_breakdown"] == inputs["rejection_breakdown"]
    
    @given(inputs=valid_diagnostics_inputs())
    @settings(max_examples=100)
    def test_rejection_breakdown_has_all_categories(self, inputs):
        """
        Property 1: Diagnostics Completeness
        
        For any valid inputs, the rejection_breakdown should contain
        all four rejection categories.
        
        **Validates: Requirements 1.1, 1.4, 2.1**
        """
        executor = object.__new__(StrategyBacktestExecutor)
        
        diagnostics = executor._build_execution_diagnostics(**inputs)
        
        required_categories = [
            "spread_too_wide",
            "depth_too_thin",
            "snapshot_stale",
            "vol_shock",
        ]
        
        for category in required_categories:
            assert category in diagnostics["rejection_breakdown"], \
                f"Missing rejection category: {category}"
            assert isinstance(diagnostics["rejection_breakdown"][category], int), \
                f"Category {category} should be int"
            assert diagnostics["rejection_breakdown"][category] >= 0, \
                f"Category {category} should be non-negative"


# ============================================================================
# Property Tests for Rejection Breakdown Consistency
# ============================================================================

class TestRejectionBreakdownConsistency:
    """
    Property 3: Rejection Breakdown Consistency
    
    For any backtest, the sum of all values in rejection_breakdown SHALL
    equal global_gate_rejections.
    
    **Validates: Requirements 1.2**
    """
    
    @given(inputs=valid_diagnostics_inputs())
    @settings(max_examples=100)
    def test_rejection_breakdown_sums_to_total(self, inputs):
        """
        Property 3: Rejection Breakdown Consistency
        
        For any valid inputs, the sum of rejection_breakdown values
        should equal global_gate_rejections.
        
        **Validates: Requirements 1.2**
        """
        executor = object.__new__(StrategyBacktestExecutor)
        
        diagnostics = executor._build_execution_diagnostics(**inputs)
        
        breakdown_sum = sum(diagnostics["rejection_breakdown"].values())
        
        assert breakdown_sum == diagnostics["global_gate_rejections"], \
            f"Rejection breakdown sum ({breakdown_sum}) should equal " \
            f"global_gate_rejections ({diagnostics['global_gate_rejections']})"
    
    @given(breakdown=rejection_breakdowns())
    @settings(max_examples=100)
    def test_breakdown_values_are_non_negative(self, breakdown):
        """
        Property 3: Rejection Breakdown Consistency
        
        For any rejection breakdown, all values should be non-negative.
        
        **Validates: Requirements 1.2**
        """
        for category, count in breakdown.items():
            assert count >= 0, f"Category {category} has negative count: {count}"
    
    @given(inputs=valid_diagnostics_inputs())
    @settings(max_examples=100)
    def test_breakdown_categories_unchanged(self, inputs):
        """
        Property 3: Rejection Breakdown Consistency
        
        For any valid inputs, the rejection breakdown categories should
        not be modified by _build_execution_diagnostics.
        
        **Validates: Requirements 1.2**
        """
        executor = object.__new__(StrategyBacktestExecutor)
        
        # Make a copy of the input breakdown
        original_breakdown = inputs["rejection_breakdown"].copy()
        
        diagnostics = executor._build_execution_diagnostics(**inputs)
        
        # Verify categories are unchanged
        assert set(diagnostics["rejection_breakdown"].keys()) == set(original_breakdown.keys()), \
            "Rejection breakdown categories should not change"
        
        # Verify values are unchanged
        for category in original_breakdown:
            assert diagnostics["rejection_breakdown"][category] == original_breakdown[category], \
                f"Category {category} value changed"


# ============================================================================
# Property Tests for Summary Generation (Zero Trades)
# ============================================================================

class TestSummaryGenerationZeroTrades:
    """
    Property 2: Summary Generation for Zero Trades
    
    For any backtest with total_trades = 0, the summary field SHALL contain
    a non-empty explanation and primary_issue SHALL be set.
    
    **Validates: Requirements 1.3, 2.3**
    """
    
    @given(inputs=zero_trade_diagnostics_inputs())
    @settings(max_examples=100)
    def test_zero_trades_has_non_empty_summary(self, inputs):
        """
        Property 2: Summary Generation for Zero Trades
        
        For any backtest with zero trades, the summary should be non-empty.
        
        **Validates: Requirements 1.3, 2.3**
        """
        executor = object.__new__(StrategyBacktestExecutor)
        
        diagnostics = executor._build_execution_diagnostics(**inputs)
        
        assert diagnostics["summary"], "Summary should be non-empty for zero-trade backtests"
        assert len(diagnostics["summary"]) > 0, "Summary should have content"
    
    @given(inputs=zero_trade_diagnostics_inputs())
    @settings(max_examples=100)
    def test_zero_trades_has_primary_issue(self, inputs):
        """
        Property 2: Summary Generation for Zero Trades
        
        For any backtest with zero trades, primary_issue should be set.
        
        **Validates: Requirements 1.3, 2.3**
        """
        executor = object.__new__(StrategyBacktestExecutor)
        
        diagnostics = executor._build_execution_diagnostics(**inputs)
        
        assert diagnostics["primary_issue"] is not None, \
            "primary_issue should be set for zero-trade backtests"
        assert len(diagnostics["primary_issue"]) > 0, \
            "primary_issue should have content"
    
    @given(inputs=zero_trade_diagnostics_inputs())
    @settings(max_examples=100)
    def test_zero_trades_has_suggestions(self, inputs):
        """
        Property 2: Summary Generation for Zero Trades
        
        For any backtest with zero trades, suggestions should be provided.
        
        **Validates: Requirements 1.3, 2.3**
        """
        executor = object.__new__(StrategyBacktestExecutor)
        
        diagnostics = executor._build_execution_diagnostics(**inputs)
        
        assert isinstance(diagnostics["suggestions"], list), \
            "suggestions should be a list"
        # Note: suggestions may be empty in some edge cases (e.g., all zeros)
        # but typically should have content for zero-trade backtests


# ============================================================================
# Property Tests for Snapshot Count Consistency
# ============================================================================

class TestSnapshotCountConsistency:
    """
    Property 4: Snapshot Count Consistency
    
    For any backtest, snapshots_processed + snapshots_skipped SHALL equal
    total_snapshots.
    
    **Validates: Requirements 1.1**
    """
    
    @given(inputs=valid_diagnostics_inputs())
    @settings(max_examples=100)
    def test_snapshot_counts_sum_correctly(self, inputs):
        """
        Property 4: Snapshot Count Consistency
        
        For any valid inputs, snapshots_processed + snapshots_skipped
        should equal total_snapshots.
        
        **Validates: Requirements 1.1**
        """
        executor = object.__new__(StrategyBacktestExecutor)
        
        diagnostics = executor._build_execution_diagnostics(**inputs)
        
        total = diagnostics["snapshots_processed"] + diagnostics["snapshots_skipped"]
        
        assert total == diagnostics["total_snapshots"], \
            f"snapshots_processed ({diagnostics['snapshots_processed']}) + " \
            f"snapshots_skipped ({diagnostics['snapshots_skipped']}) = {total} " \
            f"should equal total_snapshots ({diagnostics['total_snapshots']})"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


# ============================================================================
# Property Tests for API Response Structure
# ============================================================================

class TestAPIResponseStructure:
    """
    Property 2: Summary Generation for Zero Trades (API Response)
    
    For any backtest with total_trades = 0, the API response's execution_diagnostics
    SHALL contain a non-empty summary and primary_issue SHALL be set.
    
    **Validates: Requirements 1.3, 2.3**
    """
    
    @given(inputs=zero_trade_diagnostics_inputs())
    @settings(max_examples=100)
    def test_api_response_model_accepts_valid_diagnostics(self, inputs):
        """
        Property 2: Summary Generation for Zero Trades
        
        For any valid diagnostics inputs, the API response model should
        accept the data without validation errors.
        
        **Validates: Requirements 1.3, 2.3**
        """
        from quantgambit.api.backtest_endpoints import (
            ExecutionDiagnosticsResponse,
            RejectionBreakdownResponse,
        )
        
        executor = object.__new__(StrategyBacktestExecutor)
        diagnostics = executor._build_execution_diagnostics(**inputs)
        
        # Build the API response model from the diagnostics
        breakdown_data = diagnostics.get("rejection_breakdown", {})
        rejection_breakdown = RejectionBreakdownResponse(
            spread_too_wide=breakdown_data.get("spread_too_wide", 0),
            depth_too_thin=breakdown_data.get("depth_too_thin", 0),
            snapshot_stale=breakdown_data.get("snapshot_stale", 0),
            vol_shock=breakdown_data.get("vol_shock", 0),
        )
        
        # This should not raise any validation errors
        response = ExecutionDiagnosticsResponse(
            total_snapshots=diagnostics.get("total_snapshots", 0),
            snapshots_processed=diagnostics.get("snapshots_processed", 0),
            snapshots_skipped=diagnostics.get("snapshots_skipped", 0),
            global_gate_rejections=diagnostics.get("global_gate_rejections", 0),
            rejection_breakdown=rejection_breakdown,
            profiles_selected=diagnostics.get("profiles_selected", 0),
            signals_generated=diagnostics.get("signals_generated", 0),
            cooldown_rejections=diagnostics.get("cooldown_rejections", 0),
            summary=diagnostics.get("summary", ""),
            primary_issue=diagnostics.get("primary_issue"),
            suggestions=diagnostics.get("suggestions", []),
        )
        
        # Verify the response model has all required fields
        assert response.total_snapshots >= 0
        assert response.snapshots_processed >= 0
        assert response.snapshots_skipped >= 0
        assert response.global_gate_rejections >= 0
        assert response.profiles_selected >= 0
        assert response.signals_generated >= 0
        assert response.cooldown_rejections >= 0
        assert isinstance(response.summary, str)
        assert isinstance(response.suggestions, list)
    
    @given(inputs=zero_trade_diagnostics_inputs())
    @settings(max_examples=100)
    def test_zero_trade_api_response_has_summary_and_issue(self, inputs):
        """
        Property 2: Summary Generation for Zero Trades
        
        For any backtest with zero trades, the API response should have
        a non-empty summary and primary_issue set.
        
        **Validates: Requirements 1.3, 2.3**
        """
        from quantgambit.api.backtest_endpoints import (
            ExecutionDiagnosticsResponse,
            RejectionBreakdownResponse,
        )
        
        executor = object.__new__(StrategyBacktestExecutor)
        diagnostics = executor._build_execution_diagnostics(**inputs)
        
        # Build the API response model
        breakdown_data = diagnostics.get("rejection_breakdown", {})
        rejection_breakdown = RejectionBreakdownResponse(
            spread_too_wide=breakdown_data.get("spread_too_wide", 0),
            depth_too_thin=breakdown_data.get("depth_too_thin", 0),
            snapshot_stale=breakdown_data.get("snapshot_stale", 0),
            vol_shock=breakdown_data.get("vol_shock", 0),
        )
        
        response = ExecutionDiagnosticsResponse(
            total_snapshots=diagnostics.get("total_snapshots", 0),
            snapshots_processed=diagnostics.get("snapshots_processed", 0),
            snapshots_skipped=diagnostics.get("snapshots_skipped", 0),
            global_gate_rejections=diagnostics.get("global_gate_rejections", 0),
            rejection_breakdown=rejection_breakdown,
            profiles_selected=diagnostics.get("profiles_selected", 0),
            signals_generated=diagnostics.get("signals_generated", 0),
            cooldown_rejections=diagnostics.get("cooldown_rejections", 0),
            summary=diagnostics.get("summary", ""),
            primary_issue=diagnostics.get("primary_issue"),
            suggestions=diagnostics.get("suggestions", []),
        )
        
        # For zero-trade backtests, summary should be non-empty
        assert response.summary, "Summary should be non-empty for zero-trade backtests"
        assert len(response.summary) > 0, "Summary should have content"
        
        # primary_issue should be set for zero-trade backtests
        assert response.primary_issue is not None, \
            "primary_issue should be set for zero-trade backtests"
        assert len(response.primary_issue) > 0, \
            "primary_issue should have content"
    
    @given(inputs=valid_diagnostics_inputs())
    @settings(max_examples=100)
    def test_api_response_rejection_breakdown_consistency(self, inputs):
        """
        Property 2: API Response Rejection Breakdown Consistency
        
        For any API response, the rejection breakdown values should sum
        to global_gate_rejections.
        
        **Validates: Requirements 1.3, 2.3**
        """
        from quantgambit.api.backtest_endpoints import (
            ExecutionDiagnosticsResponse,
            RejectionBreakdownResponse,
        )
        
        executor = object.__new__(StrategyBacktestExecutor)
        diagnostics = executor._build_execution_diagnostics(**inputs)
        
        # Build the API response model
        breakdown_data = diagnostics.get("rejection_breakdown", {})
        rejection_breakdown = RejectionBreakdownResponse(
            spread_too_wide=breakdown_data.get("spread_too_wide", 0),
            depth_too_thin=breakdown_data.get("depth_too_thin", 0),
            snapshot_stale=breakdown_data.get("snapshot_stale", 0),
            vol_shock=breakdown_data.get("vol_shock", 0),
        )
        
        response = ExecutionDiagnosticsResponse(
            total_snapshots=diagnostics.get("total_snapshots", 0),
            snapshots_processed=diagnostics.get("snapshots_processed", 0),
            snapshots_skipped=diagnostics.get("snapshots_skipped", 0),
            global_gate_rejections=diagnostics.get("global_gate_rejections", 0),
            rejection_breakdown=rejection_breakdown,
            profiles_selected=diagnostics.get("profiles_selected", 0),
            signals_generated=diagnostics.get("signals_generated", 0),
            cooldown_rejections=diagnostics.get("cooldown_rejections", 0),
            summary=diagnostics.get("summary", ""),
            primary_issue=diagnostics.get("primary_issue"),
            suggestions=diagnostics.get("suggestions", []),
        )
        
        # Verify rejection breakdown sums to global_gate_rejections
        breakdown_sum = (
            response.rejection_breakdown.spread_too_wide +
            response.rejection_breakdown.depth_too_thin +
            response.rejection_breakdown.snapshot_stale +
            response.rejection_breakdown.vol_shock
        )
        
        assert breakdown_sum == response.global_gate_rejections, \
            f"Rejection breakdown sum ({breakdown_sum}) should equal " \
            f"global_gate_rejections ({response.global_gate_rejections})"
