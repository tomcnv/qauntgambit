"""
Unit tests for Strategy Diagnostics module.

Tests for StrategyMetrics dataclass and StrategyDiagnostics service
as specified in Requirement 7.
"""

from __future__ import annotations

import threading
import time
from unittest.mock import patch, MagicMock

import pytest

from quantgambit.signals.services.strategy_diagnostics import (
    StrategyMetrics,
    StrategyDiagnostics,
    get_strategy_diagnostics,
    reset_strategy_diagnostics,
)


# =============================================================================
# StrategyMetrics Tests
# =============================================================================

class TestStrategyMetricsCounters:
    """Tests for StrategyMetrics counter fields (Requirement 7.1)."""
    
    def test_default_counters_are_zero(self):
        """All counters should default to zero."""
        metrics = StrategyMetrics(strategy_id="test_strategy")
        
        assert metrics.tick_count == 0
        assert metrics.setup_count == 0
        assert metrics.confirm_count == 0
        assert metrics.ev_pass_count == 0
        assert metrics.signal_count == 0
    
    def test_counters_can_be_set(self):
        """Counters can be initialized with values."""
        metrics = StrategyMetrics(
            strategy_id="test_strategy",
            tick_count=1000,
            setup_count=100,
            confirm_count=50,
            ev_pass_count=25,
            signal_count=10,
        )
        
        assert metrics.tick_count == 1000
        assert metrics.setup_count == 100
        assert metrics.confirm_count == 50
        assert metrics.ev_pass_count == 25
        assert metrics.signal_count == 10


class TestStrategyMetricsFailureCounters:
    """Tests for predicate-level failure counters (Requirement 7.2)."""
    
    def test_default_failure_counters_are_zero(self):
        """All failure counters should default to zero."""
        metrics = StrategyMetrics(strategy_id="test_strategy")
        
        assert metrics.fail_distance_count == 0
        assert metrics.fail_spread_count == 0
        assert metrics.fail_flow_count == 0
        assert metrics.fail_trend_count == 0
        assert metrics.fail_ev_count == 0
        assert metrics.fail_cost_count == 0
        assert metrics.fail_data_count == 0
    
    def test_failure_counters_can_be_set(self):
        """Failure counters can be initialized with values."""
        metrics = StrategyMetrics(
            strategy_id="test_strategy",
            fail_distance_count=10,
            fail_spread_count=20,
            fail_flow_count=30,
            fail_trend_count=40,
            fail_ev_count=50,
            fail_cost_count=60,
            fail_data_count=70,
        )
        
        assert metrics.fail_distance_count == 10
        assert metrics.fail_spread_count == 20
        assert metrics.fail_flow_count == 30
        assert metrics.fail_trend_count == 40
        assert metrics.fail_ev_count == 50
        assert metrics.fail_cost_count == 60
        assert metrics.fail_data_count == 70


class TestStrategyMetricsRates:
    """Tests for rate properties (Requirement 7.3)."""
    
    def test_setup_rate_with_ticks(self):
        """setup_rate = setup_count / tick_count."""
        metrics = StrategyMetrics(
            strategy_id="test",
            tick_count=1000,
            setup_count=100,
        )
        
        assert metrics.setup_rate == 0.1
    
    def test_setup_rate_zero_ticks(self):
        """setup_rate should be 0 when tick_count is 0."""
        metrics = StrategyMetrics(strategy_id="test", tick_count=0)
        
        assert metrics.setup_rate == 0.0
    
    def test_confirm_rate_with_setups(self):
        """confirm_rate = confirm_count / setup_count."""
        metrics = StrategyMetrics(
            strategy_id="test",
            setup_count=100,
            confirm_count=50,
        )
        
        assert metrics.confirm_rate == 0.5
    
    def test_confirm_rate_zero_setups(self):
        """confirm_rate should be 0 when setup_count is 0."""
        metrics = StrategyMetrics(strategy_id="test", setup_count=0)
        
        assert metrics.confirm_rate == 0.0
    
    def test_ev_rate_with_confirms(self):
        """ev_rate = ev_pass_count / confirm_count."""
        metrics = StrategyMetrics(
            strategy_id="test",
            confirm_count=50,
            ev_pass_count=25,
        )
        
        assert metrics.ev_rate == 0.5
    
    def test_ev_rate_zero_confirms(self):
        """ev_rate should be 0 when confirm_count is 0."""
        metrics = StrategyMetrics(strategy_id="test", confirm_count=0)
        
        assert metrics.ev_rate == 0.0
    
    def test_execution_rate_with_ev_passes(self):
        """execution_rate = signal_count / ev_pass_count."""
        metrics = StrategyMetrics(
            strategy_id="test",
            ev_pass_count=25,
            signal_count=20,
        )
        
        assert metrics.execution_rate == 0.8
    
    def test_execution_rate_zero_ev_passes(self):
        """execution_rate should be 0 when ev_pass_count is 0."""
        metrics = StrategyMetrics(strategy_id="test", ev_pass_count=0)
        
        assert metrics.execution_rate == 0.0


class TestStrategyMetricsBottleneck:
    """Tests for get_bottleneck() method (Requirement 7.8)."""
    
    def test_bottleneck_setup_when_no_setups(self):
        """Bottleneck is 'setup' when setup_rate is 0."""
        metrics = StrategyMetrics(
            strategy_id="test",
            tick_count=1000,
            setup_count=0,
        )
        
        assert metrics.get_bottleneck() == "setup"
    
    def test_bottleneck_confirm_when_no_confirms(self):
        """Bottleneck is 'confirm' when confirm_rate is 0."""
        metrics = StrategyMetrics(
            strategy_id="test",
            tick_count=1000,
            setup_count=100,
            confirm_count=0,
        )
        
        assert metrics.get_bottleneck() == "confirm"
    
    def test_bottleneck_ev_when_no_ev_passes(self):
        """Bottleneck is 'ev' when ev_rate is 0."""
        metrics = StrategyMetrics(
            strategy_id="test",
            tick_count=1000,
            setup_count=100,
            confirm_count=50,
            ev_pass_count=0,
        )
        
        assert metrics.get_bottleneck() == "ev"
    
    def test_bottleneck_execution_when_no_signals(self):
        """Bottleneck is 'execution' when execution_rate is 0."""
        metrics = StrategyMetrics(
            strategy_id="test",
            tick_count=1000,
            setup_count=100,
            confirm_count=50,
            ev_pass_count=25,
            signal_count=0,
        )
        
        assert metrics.get_bottleneck() == "execution"
    
    def test_bottleneck_none_when_all_healthy(self):
        """Bottleneck is 'none' when all rates are healthy (>= 0.1)."""
        metrics = StrategyMetrics(
            strategy_id="test",
            tick_count=1000,
            setup_count=200,  # 20% setup rate
            confirm_count=100,  # 50% confirm rate
            ev_pass_count=50,  # 50% ev rate
            signal_count=25,  # 50% execution rate
        )
        
        assert metrics.get_bottleneck() == "none"
    
    def test_bottleneck_setup_when_rate_below_threshold(self):
        """Bottleneck is 'setup' when setup_rate < 0.1."""
        metrics = StrategyMetrics(
            strategy_id="test",
            tick_count=1000,
            setup_count=50,  # 5% setup rate
            confirm_count=25,
            ev_pass_count=12,
            signal_count=6,
        )
        
        assert metrics.get_bottleneck() == "setup"


class TestStrategyMetricsFailureBreakdown:
    """Tests for get_failure_breakdown() method (Requirement 7.9)."""
    
    def test_failure_breakdown_returns_all_counters(self):
        """get_failure_breakdown() returns all failure counters."""
        metrics = StrategyMetrics(
            strategy_id="test",
            fail_distance_count=10,
            fail_spread_count=20,
            fail_flow_count=30,
            fail_trend_count=40,
            fail_ev_count=50,
            fail_cost_count=60,
            fail_data_count=70,
        )
        
        breakdown = metrics.get_failure_breakdown()
        
        assert breakdown == {
            "fail_distance": 10,
            "fail_spread": 20,
            "fail_flow": 30,
            "fail_trend": 40,
            "fail_ev": 50,
            "fail_cost": 60,
            "fail_data": 70,
        }
    
    def test_failure_breakdown_empty_when_no_failures(self):
        """get_failure_breakdown() returns zeros when no failures."""
        metrics = StrategyMetrics(strategy_id="test")
        
        breakdown = metrics.get_failure_breakdown()
        
        assert all(count == 0 for count in breakdown.values())


class TestStrategyMetricsTopFailures:
    """Tests for get_top_failures(n) method."""
    
    def test_top_failures_returns_sorted_list(self):
        """get_top_failures() returns failures sorted by count descending."""
        metrics = StrategyMetrics(
            strategy_id="test",
            fail_distance_count=10,
            fail_spread_count=50,
            fail_flow_count=30,
            fail_trend_count=20,
        )
        
        top = metrics.get_top_failures(3)
        
        assert len(top) == 3
        assert top[0] == ("fail_spread", 50)
        assert top[1] == ("fail_flow", 30)
        assert top[2] == ("fail_trend", 20)
    
    def test_top_failures_respects_n_parameter(self):
        """get_top_failures(n) returns at most n items."""
        metrics = StrategyMetrics(
            strategy_id="test",
            fail_distance_count=10,
            fail_spread_count=50,
            fail_flow_count=30,
        )
        
        top = metrics.get_top_failures(2)
        
        assert len(top) == 2
    
    def test_top_failures_default_n_is_3(self):
        """get_top_failures() defaults to n=3."""
        metrics = StrategyMetrics(
            strategy_id="test",
            fail_distance_count=10,
            fail_spread_count=50,
            fail_flow_count=30,
            fail_trend_count=20,
            fail_ev_count=40,
        )
        
        top = metrics.get_top_failures()
        
        assert len(top) == 3


class TestStrategyMetricsToDict:
    """Tests for to_dict() method."""
    
    def test_to_dict_includes_all_fields(self):
        """to_dict() includes all metrics fields."""
        metrics = StrategyMetrics(
            strategy_id="test_strategy",
            tick_count=1000,
            setup_count=100,
            confirm_count=50,
            ev_pass_count=25,
            signal_count=10,
        )
        
        result = metrics.to_dict()
        
        assert result["strategy_id"] == "test_strategy"
        assert result["tick_count"] == 1000
        assert result["setup_count"] == 100
        assert result["confirm_count"] == 50
        assert result["ev_pass_count"] == 25
        assert result["signal_count"] == 10
        assert "setup_rate" in result
        assert "confirm_rate" in result
        assert "ev_rate" in result
        assert "execution_rate" in result
        assert "bottleneck" in result
        assert "failure_breakdown" in result
        assert "top_failures" in result


# =============================================================================
# StrategyDiagnostics Tests
# =============================================================================

class TestStrategyDiagnosticsRecording:
    """Tests for recording methods (Requirements 7.4-7.7)."""
    
    def test_record_tick_increments_counter(self):
        """record_tick() increments tick_count."""
        diagnostics = StrategyDiagnostics()
        
        diagnostics.record_tick("test_strategy")
        diagnostics.record_tick("test_strategy")
        diagnostics.record_tick("test_strategy")
        
        metrics = diagnostics.get_metrics("test_strategy")
        assert metrics is not None
        assert metrics.tick_count == 3
    
    def test_record_setup_increments_counter(self):
        """record_setup() increments setup_count (Requirement 7.4)."""
        diagnostics = StrategyDiagnostics()
        
        diagnostics.record_setup("test_strategy")
        diagnostics.record_setup("test_strategy")
        
        metrics = diagnostics.get_metrics("test_strategy")
        assert metrics is not None
        assert metrics.setup_count == 2
    
    def test_record_confirm_increments_counter(self):
        """record_confirm() increments confirm_count."""
        diagnostics = StrategyDiagnostics()
        
        diagnostics.record_confirm("test_strategy")
        
        metrics = diagnostics.get_metrics("test_strategy")
        assert metrics is not None
        assert metrics.confirm_count == 1
    
    def test_record_ev_pass_increments_counter(self):
        """record_ev_pass() increments ev_pass_count (Requirement 7.6)."""
        diagnostics = StrategyDiagnostics()
        
        diagnostics.record_ev_pass("test_strategy")
        
        metrics = diagnostics.get_metrics("test_strategy")
        assert metrics is not None
        assert metrics.ev_pass_count == 1
    
    def test_record_signal_increments_counter(self):
        """record_signal() increments signal_count (Requirement 7.7)."""
        diagnostics = StrategyDiagnostics()
        
        diagnostics.record_signal("test_strategy")
        
        metrics = diagnostics.get_metrics("test_strategy")
        assert metrics is not None
        assert metrics.signal_count == 1


class TestStrategyDiagnosticsPredicateFailures:
    """Tests for predicate failure recording (Requirement 7.5)."""
    
    def test_record_predicate_failure_distance(self):
        """record_predicate_failure() increments fail_distance_count."""
        diagnostics = StrategyDiagnostics()
        
        diagnostics.record_predicate_failure("test_strategy", "fail_distance")
        
        metrics = diagnostics.get_metrics("test_strategy")
        assert metrics is not None
        assert metrics.fail_distance_count == 1
    
    def test_record_predicate_failure_spread(self):
        """record_predicate_failure() increments fail_spread_count."""
        diagnostics = StrategyDiagnostics()
        
        diagnostics.record_predicate_failure("test_strategy", "fail_spread")
        
        metrics = diagnostics.get_metrics("test_strategy")
        assert metrics is not None
        assert metrics.fail_spread_count == 1
    
    def test_record_predicate_failure_flow(self):
        """record_predicate_failure() increments fail_flow_count."""
        diagnostics = StrategyDiagnostics()
        
        diagnostics.record_predicate_failure("test_strategy", "fail_flow")
        
        metrics = diagnostics.get_metrics("test_strategy")
        assert metrics is not None
        assert metrics.fail_flow_count == 1
    
    def test_record_predicate_failure_trend(self):
        """record_predicate_failure() increments fail_trend_count."""
        diagnostics = StrategyDiagnostics()
        
        diagnostics.record_predicate_failure("test_strategy", "fail_trend")
        
        metrics = diagnostics.get_metrics("test_strategy")
        assert metrics is not None
        assert metrics.fail_trend_count == 1
    
    def test_record_predicate_failure_ev(self):
        """record_predicate_failure() increments fail_ev_count."""
        diagnostics = StrategyDiagnostics()
        
        diagnostics.record_predicate_failure("test_strategy", "fail_ev")
        
        metrics = diagnostics.get_metrics("test_strategy")
        assert metrics is not None
        assert metrics.fail_ev_count == 1
    
    def test_record_predicate_failure_cost(self):
        """record_predicate_failure() increments fail_cost_count."""
        diagnostics = StrategyDiagnostics()
        
        diagnostics.record_predicate_failure("test_strategy", "fail_cost")
        
        metrics = diagnostics.get_metrics("test_strategy")
        assert metrics is not None
        assert metrics.fail_cost_count == 1
    
    def test_record_predicate_failure_data(self):
        """record_predicate_failure() increments fail_data_count."""
        diagnostics = StrategyDiagnostics()
        
        diagnostics.record_predicate_failure("test_strategy", "fail_data")
        
        metrics = diagnostics.get_metrics("test_strategy")
        assert metrics is not None
        assert metrics.fail_data_count == 1
    
    def test_record_predicate_failure_unknown_type_ignored(self):
        """record_predicate_failure() ignores unknown failure types."""
        diagnostics = StrategyDiagnostics()
        
        # Should not raise an error
        diagnostics.record_predicate_failure("test_strategy", "fail_unknown")
        
        metrics = diagnostics.get_metrics("test_strategy")
        assert metrics is not None
        # All failure counters should be 0
        breakdown = metrics.get_failure_breakdown()
        assert all(count == 0 for count in breakdown.values())


class TestStrategyDiagnosticsPeriodicLogging:
    """Tests for periodic logging (Requirement 7.10)."""
    
    def test_log_summary_called_every_n_ticks(self):
        """_log_summary() is called every log_interval ticks."""
        diagnostics = StrategyDiagnostics(log_interval=10)
        
        with patch.object(diagnostics, '_log_summary') as mock_log:
            for _ in range(25):
                diagnostics.record_tick("test_strategy")
            
            # Should be called at tick 10 and tick 20
            assert mock_log.call_count == 2
    
    def test_log_summary_not_called_before_interval(self):
        """_log_summary() is not called before log_interval ticks."""
        diagnostics = StrategyDiagnostics(log_interval=100)
        
        with patch.object(diagnostics, '_log_summary') as mock_log:
            for _ in range(50):
                diagnostics.record_tick("test_strategy")
            
            assert mock_log.call_count == 0


class TestStrategyDiagnosticsThreadSafety:
    """Tests for thread-safe locking (Requirement 7.2.4)."""
    
    def test_concurrent_recording_is_thread_safe(self):
        """Concurrent recording from multiple threads is safe."""
        diagnostics = StrategyDiagnostics(log_interval=10000)  # Disable logging
        num_threads = 10
        iterations_per_thread = 100
        
        def record_metrics():
            for _ in range(iterations_per_thread):
                diagnostics.record_tick("test_strategy")
                diagnostics.record_setup("test_strategy")
        
        threads = [
            threading.Thread(target=record_metrics)
            for _ in range(num_threads)
        ]
        
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        metrics = diagnostics.get_metrics("test_strategy")
        assert metrics is not None
        assert metrics.tick_count == num_threads * iterations_per_thread
        assert metrics.setup_count == num_threads * iterations_per_thread


class TestStrategyDiagnosticsGetters:
    """Tests for getter methods (Requirements 7.8, 7.9)."""
    
    def test_get_bottleneck_returns_correct_stage(self):
        """get_bottleneck() returns correct bottleneck stage."""
        diagnostics = StrategyDiagnostics()
        
        diagnostics.record_tick("test_strategy")
        # No setups recorded, so bottleneck should be "setup"
        
        assert diagnostics.get_bottleneck("test_strategy") == "setup"
    
    def test_get_bottleneck_unknown_strategy(self):
        """get_bottleneck() returns 'unknown' for unknown strategy."""
        diagnostics = StrategyDiagnostics()
        
        assert diagnostics.get_bottleneck("unknown_strategy") == "unknown"
    
    def test_get_failure_breakdown_returns_counts(self):
        """get_failure_breakdown() returns failure counts."""
        diagnostics = StrategyDiagnostics()
        
        diagnostics.record_predicate_failure("test_strategy", "fail_flow")
        diagnostics.record_predicate_failure("test_strategy", "fail_flow")
        diagnostics.record_predicate_failure("test_strategy", "fail_trend")
        
        breakdown = diagnostics.get_failure_breakdown("test_strategy")
        
        assert breakdown["fail_flow"] == 2
        assert breakdown["fail_trend"] == 1
    
    def test_get_failure_breakdown_unknown_strategy(self):
        """get_failure_breakdown() returns empty dict for unknown strategy."""
        diagnostics = StrategyDiagnostics()
        
        breakdown = diagnostics.get_failure_breakdown("unknown_strategy")
        
        assert breakdown == {}
    
    def test_get_all_metrics_returns_all_strategies(self):
        """get_all_metrics() returns metrics for all strategies."""
        diagnostics = StrategyDiagnostics()
        
        diagnostics.record_tick("strategy_a")
        diagnostics.record_tick("strategy_b")
        diagnostics.record_tick("strategy_c")
        
        all_metrics = diagnostics.get_all_metrics()
        
        assert len(all_metrics) == 3
        assert "strategy_a" in all_metrics
        assert "strategy_b" in all_metrics
        assert "strategy_c" in all_metrics


class TestStrategyDiagnosticsAPIResponse:
    """Tests for API response formatting (Requirement 7.11, 7.12)."""
    
    def test_get_api_response_includes_strategies(self):
        """get_api_response() includes strategies list."""
        diagnostics = StrategyDiagnostics()
        
        diagnostics.record_tick("strategy_a")
        diagnostics.record_setup("strategy_a")
        diagnostics.record_tick("strategy_b")
        
        response = diagnostics.get_api_response()
        
        assert "strategies" in response
        assert len(response["strategies"]) == 2
    
    def test_get_api_response_includes_aggregate(self):
        """get_api_response() includes aggregate statistics."""
        diagnostics = StrategyDiagnostics()
        
        diagnostics.record_tick("strategy_a")
        diagnostics.record_tick("strategy_a")
        diagnostics.record_setup("strategy_a")
        
        response = diagnostics.get_api_response()
        
        assert "aggregate" in response
        assert response["aggregate"]["total_ticks"] == 2
        assert response["aggregate"]["total_setups"] == 1
    
    def test_get_api_response_includes_rates(self):
        """get_api_response() includes aggregate rates."""
        diagnostics = StrategyDiagnostics()
        
        for _ in range(100):
            diagnostics.record_tick("strategy_a")
        for _ in range(10):
            diagnostics.record_setup("strategy_a")
        
        response = diagnostics.get_api_response()
        
        assert response["aggregate"]["overall_setup_rate"] == 0.1


class TestStrategyDiagnosticsReset:
    """Tests for reset functionality."""
    
    def test_reset_clears_all_metrics(self):
        """reset() clears all metrics."""
        diagnostics = StrategyDiagnostics()
        
        diagnostics.record_tick("strategy_a")
        diagnostics.record_setup("strategy_a")
        
        diagnostics.reset()
        
        assert diagnostics.get_metrics("strategy_a") is None
        assert len(diagnostics.get_all_metrics()) == 0


class TestGlobalDiagnostics:
    """Tests for global singleton functions."""
    
    def test_get_strategy_diagnostics_returns_singleton(self):
        """get_strategy_diagnostics() returns the same instance."""
        reset_strategy_diagnostics()
        
        instance1 = get_strategy_diagnostics()
        instance2 = get_strategy_diagnostics()
        
        assert instance1 is instance2
    
    def test_reset_strategy_diagnostics_clears_data(self):
        """reset_strategy_diagnostics() clears the singleton data."""
        diagnostics = get_strategy_diagnostics()
        diagnostics.record_tick("test_strategy")
        
        reset_strategy_diagnostics()
        
        # Data should be cleared
        assert diagnostics.get_metrics("test_strategy") is None
