"""
Strategy Diagnostics - Per-strategy metrics with predicate-level breakdown.

This module implements granular strategy diagnostics as specified in Requirement 7:
- StrategyMetrics: Per-strategy counters and rate calculations
- StrategyDiagnostics: Service for tracking and logging diagnostics

Requirement 7.1: Track per-strategy counters: setup_count, confirm_count, ev_pass_count, signal_count
Requirement 7.2: Track predicate-level failure counters: fail_distance, fail_spread, fail_flow, etc.
Requirement 7.3: Compute rates: setup_rate, confirm_rate, ev_rate, execution_rate
Requirement 7.8: Expose get_bottleneck(strategy_id) returning "setup", "confirm", "ev", or "execution"
Requirement 7.9: Expose get_failure_breakdown(strategy_id) returning counts for each fail_* predicate
Requirement 7.10: Log diagnostic summary every 1000 ticks with rates AND top failure predicates
Requirement 7.11: Accessible via API endpoint /api/v1/diagnostics/strategies
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Any

from quantgambit.observability.logger import log_info


@dataclass
class StrategyMetrics:
    """
    Metrics for a single strategy with predicate-level breakdown.
    
    Requirement 7.1: Track per-strategy counters
    Requirement 7.2: Track predicate-level failure counters
    Requirement 7.3: Compute rates
    
    Attributes:
        strategy_id: Unique identifier for the strategy
        tick_count: Number of ticks processed
        setup_count: Number of setups detected (CandidateSignal emitted)
        confirm_count: Number of confirmations passed
        ev_pass_count: Number of signals that passed EVGate
        signal_count: Number of signals sent for execution
        
        fail_distance_count: Failed due to distance threshold
        fail_spread_count: Failed due to spread too wide
        fail_flow_count: Failed due to flow_rotation not confirming
        fail_trend_count: Failed due to adverse trend_bias
        fail_ev_count: Failed due to EV below threshold
        fail_cost_count: Failed due to costs exceeding potential profit
        fail_data_count: Failed due to missing or invalid data
    """
    strategy_id: str
    
    # Pipeline stage counters (Requirement 7.1)
    tick_count: int = 0
    setup_count: int = 0
    confirm_count: int = 0
    ev_pass_count: int = 0
    signal_count: int = 0
    
    # Predicate-level failure counters (Requirement 7.2)
    fail_distance_count: int = 0
    fail_spread_count: int = 0
    fail_flow_count: int = 0
    fail_trend_count: int = 0
    fail_ev_count: int = 0
    fail_cost_count: int = 0
    fail_data_count: int = 0
    
    @property
    def setup_rate(self) -> float:
        """
        Calculate setup rate: setup_count / tick_count.
        
        Requirement 7.3: Compute rates
        
        Returns:
            Setup rate as a float between 0 and 1, or 0 if no ticks.
        """
        if self.tick_count <= 0:
            return 0.0
        return self.setup_count / self.tick_count
    
    @property
    def confirm_rate(self) -> float:
        """
        Calculate confirmation rate: confirm_count / setup_count.
        
        Requirement 7.3: Compute rates
        
        Returns:
            Confirmation rate as a float between 0 and 1, or 0 if no setups.
        """
        if self.setup_count <= 0:
            return 0.0
        return self.confirm_count / self.setup_count
    
    @property
    def ev_rate(self) -> float:
        """
        Calculate EV pass rate: ev_pass_count / confirm_count.
        
        Requirement 7.3: Compute rates
        
        Returns:
            EV pass rate as a float between 0 and 1, or 0 if no confirmations.
        """
        if self.confirm_count <= 0:
            return 0.0
        return self.ev_pass_count / self.confirm_count
    
    @property
    def execution_rate(self) -> float:
        """
        Calculate execution rate: signal_count / ev_pass_count.
        
        Requirement 7.3: Compute rates
        
        Returns:
            Execution rate as a float between 0 and 1, or 0 if no EV passes.
        """
        if self.ev_pass_count <= 0:
            return 0.0
        return self.signal_count / self.ev_pass_count
    
    def get_bottleneck(self) -> str:
        """
        Identify the pipeline stage with lowest pass rate.
        
        Requirement 7.8: Expose get_bottleneck(strategy_id) returning
        "setup", "confirm", "ev", or "execution"
        
        Returns:
            Name of the bottleneck stage. Returns "none" if all rates are healthy.
        """
        # Check rates in pipeline order
        # A rate below 0.1 (10%) or exactly 0 indicates a bottleneck
        rates = [
            ("setup", self.setup_rate),
            ("confirm", self.confirm_rate),
            ("ev", self.ev_rate),
            ("execution", self.execution_rate),
        ]
        
        for name, rate in rates:
            if rate == 0 or rate < 0.1:
                return name
        
        return "none"
    
    def get_failure_breakdown(self) -> Dict[str, int]:
        """
        Get predicate-level failure counts.
        
        Requirement 7.9: Expose get_failure_breakdown(strategy_id) returning
        counts for each fail_* predicate
        
        Returns:
            Dictionary mapping failure type to count.
        """
        return {
            "fail_distance": self.fail_distance_count,
            "fail_spread": self.fail_spread_count,
            "fail_flow": self.fail_flow_count,
            "fail_trend": self.fail_trend_count,
            "fail_ev": self.fail_ev_count,
            "fail_cost": self.fail_cost_count,
            "fail_data": self.fail_data_count,
        }
    
    def get_top_failures(self, n: int = 3) -> List[Tuple[str, int]]:
        """
        Get top N failure predicates by count.
        
        Args:
            n: Number of top failures to return (default 3)
            
        Returns:
            List of (failure_type, count) tuples sorted by count descending.
        """
        breakdown = self.get_failure_breakdown()
        sorted_failures = sorted(
            breakdown.items(),
            key=lambda x: x[1],
            reverse=True
        )
        return sorted_failures[:n]
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Convert metrics to dictionary for API response.
        
        Returns:
            Dictionary representation of all metrics.
        """
        return {
            "strategy_id": self.strategy_id,
            "tick_count": self.tick_count,
            "setup_count": self.setup_count,
            "confirm_count": self.confirm_count,
            "ev_pass_count": self.ev_pass_count,
            "signal_count": self.signal_count,
            "setup_rate": round(self.setup_rate, 6),
            "confirm_rate": round(self.confirm_rate, 6),
            "ev_rate": round(self.ev_rate, 6),
            "execution_rate": round(self.execution_rate, 6),
            "bottleneck": self.get_bottleneck(),
            "failure_breakdown": self.get_failure_breakdown(),
            "top_failures": self.get_top_failures(3),
        }


class StrategyDiagnostics:
    """
    Tracks per-strategy metrics with predicate-level breakdown.
    
    This service provides thread-safe tracking of strategy performance
    metrics and periodic logging of diagnostic summaries.
    
    Requirement 7.4: When a strategy emits a CandidateSignal, increment setup_count
    Requirement 7.5: When a candidate fails confirmation, increment specific fail_*_count
    Requirement 7.6: When a signal passes EVGate, increment ev_pass_count
    Requirement 7.7: When a signal is sent for execution, increment signal_count
    Requirement 7.10: Log diagnostic summary every 1000 ticks
    
    Thread Safety:
        All public methods are thread-safe using a reentrant lock.
    
    Usage:
        diagnostics = StrategyDiagnostics()
        diagnostics.record_tick("mean_reversion_fade")
        diagnostics.record_setup("mean_reversion_fade")
        diagnostics.record_predicate_failure("mean_reversion_fade", "fail_flow")
    """
    
    def __init__(self, log_interval: int = 1000):
        """
        Initialize the diagnostics service.
        
        Args:
            log_interval: Number of ticks between diagnostic log summaries.
                         Default is 1000 as per Requirement 7.10.
        """
        self._metrics: Dict[str, StrategyMetrics] = {}
        self._lock = threading.RLock()
        self._tick_counter = 0
        self._log_interval = log_interval
    
    def _get_or_create(self, strategy_id: str) -> StrategyMetrics:
        """
        Get or create metrics for a strategy.
        
        Must be called with lock held.
        
        Args:
            strategy_id: Strategy identifier
            
        Returns:
            StrategyMetrics instance for the strategy
        """
        if strategy_id not in self._metrics:
            self._metrics[strategy_id] = StrategyMetrics(strategy_id=strategy_id)
        return self._metrics[strategy_id]
    
    def record_tick(self, strategy_id: str) -> None:
        """
        Record a tick for a strategy.
        
        Increments tick_count and triggers periodic logging.
        
        Requirement 7.10: Log diagnostic summary every 1000 ticks
        
        Args:
            strategy_id: Strategy identifier
        """
        with self._lock:
            metrics = self._get_or_create(strategy_id)
            metrics.tick_count += 1
            self._tick_counter += 1
            
            if self._tick_counter % self._log_interval == 0:
                self._log_summary()
    
    def record_setup(self, strategy_id: str) -> None:
        """
        Record a setup detection (CandidateSignal emitted).
        
        Requirement 7.4: When a strategy emits a CandidateSignal,
        increment setup_count for that strategy
        
        Args:
            strategy_id: Strategy identifier
        """
        with self._lock:
            metrics = self._get_or_create(strategy_id)
            metrics.setup_count += 1
    
    def record_confirm(self, strategy_id: str) -> None:
        """
        Record a confirmation pass.
        
        Args:
            strategy_id: Strategy identifier
        """
        with self._lock:
            metrics = self._get_or_create(strategy_id)
            metrics.confirm_count += 1
    
    def record_ev_pass(self, strategy_id: str) -> None:
        """
        Record an EV gate pass.
        
        Requirement 7.6: When a signal passes EVGate,
        increment ev_pass_count for that strategy
        
        Args:
            strategy_id: Strategy identifier
        """
        with self._lock:
            metrics = self._get_or_create(strategy_id)
            metrics.ev_pass_count += 1
    
    def record_signal(self, strategy_id: str) -> None:
        """
        Record a signal sent for execution.
        
        Requirement 7.7: When a signal is sent for execution,
        increment signal_count for that strategy
        
        Args:
            strategy_id: Strategy identifier
        """
        with self._lock:
            metrics = self._get_or_create(strategy_id)
            metrics.signal_count += 1
    
    def record_predicate_failure(self, strategy_id: str, failure_type: str) -> None:
        """
        Record a predicate-level failure.
        
        Requirement 7.5: When a candidate fails confirmation,
        increment the specific fail_*_count for the failing predicate
        
        Args:
            strategy_id: Strategy identifier
            failure_type: Type of failure. Must be one of:
                - "fail_distance": Failed due to distance threshold
                - "fail_spread": Failed due to spread too wide
                - "fail_flow": Failed due to flow_rotation not confirming
                - "fail_trend": Failed due to adverse trend_bias
                - "fail_ev": Failed due to EV below threshold
                - "fail_cost": Failed due to costs exceeding potential profit
                - "fail_data": Failed due to missing or invalid data
        """
        with self._lock:
            metrics = self._get_or_create(strategy_id)
            attr_name = f"{failure_type}_count"
            if hasattr(metrics, attr_name):
                current_value = getattr(metrics, attr_name)
                setattr(metrics, attr_name, current_value + 1)
    
    def get_metrics(self, strategy_id: str) -> Optional[StrategyMetrics]:
        """
        Get metrics for a specific strategy.
        
        Args:
            strategy_id: Strategy identifier
            
        Returns:
            StrategyMetrics instance or None if strategy not found
        """
        with self._lock:
            return self._metrics.get(strategy_id)
    
    def get_all_metrics(self) -> Dict[str, StrategyMetrics]:
        """
        Get metrics for all strategies.
        
        Returns:
            Dictionary mapping strategy_id to StrategyMetrics
        """
        with self._lock:
            # Return a copy to avoid external modification
            return dict(self._metrics)
    
    def get_bottleneck(self, strategy_id: str) -> str:
        """
        Get the bottleneck stage for a strategy.
        
        Requirement 7.8: Expose get_bottleneck(strategy_id)
        
        Args:
            strategy_id: Strategy identifier
            
        Returns:
            Bottleneck stage name or "unknown" if strategy not found
        """
        with self._lock:
            metrics = self._metrics.get(strategy_id)
            if metrics is None:
                return "unknown"
            return metrics.get_bottleneck()
    
    def get_failure_breakdown(self, strategy_id: str) -> Dict[str, int]:
        """
        Get failure breakdown for a strategy.
        
        Requirement 7.9: Expose get_failure_breakdown(strategy_id)
        
        Args:
            strategy_id: Strategy identifier
            
        Returns:
            Dictionary of failure counts or empty dict if strategy not found
        """
        with self._lock:
            metrics = self._metrics.get(strategy_id)
            if metrics is None:
                return {}
            return metrics.get_failure_breakdown()
    
    def get_api_response(self) -> Dict[str, Any]:
        """
        Get all metrics formatted for API response.
        
        Requirement 7.11: Accessible via API endpoint
        Requirement 7.12: Include both aggregate rates AND predicate-level breakdown
        
        Returns:
            Dictionary with strategies list and aggregate statistics
        """
        with self._lock:
            strategies = []
            total_ticks = 0
            total_setups = 0
            total_confirms = 0
            total_ev_passes = 0
            total_signals = 0
            
            for strategy_id, metrics in self._metrics.items():
                strategies.append(metrics.to_dict())
                total_ticks += metrics.tick_count
                total_setups += metrics.setup_count
                total_confirms += metrics.confirm_count
                total_ev_passes += metrics.ev_pass_count
                total_signals += metrics.signal_count
            
            return {
                "strategies": strategies,
                "aggregate": {
                    "total_ticks": total_ticks,
                    "total_setups": total_setups,
                    "total_confirms": total_confirms,
                    "total_ev_passes": total_ev_passes,
                    "total_signals": total_signals,
                    "overall_setup_rate": round(total_setups / total_ticks, 6) if total_ticks > 0 else 0.0,
                    "overall_confirm_rate": round(total_confirms / total_setups, 6) if total_setups > 0 else 0.0,
                    "overall_ev_rate": round(total_ev_passes / total_confirms, 6) if total_confirms > 0 else 0.0,
                    "overall_execution_rate": round(total_signals / total_ev_passes, 6) if total_ev_passes > 0 else 0.0,
                },
                "tick_counter": self._tick_counter,
                "log_interval": self._log_interval,
            }
    
    def reset(self) -> None:
        """
        Reset all metrics.
        
        Useful for testing or starting a new session.
        """
        with self._lock:
            self._metrics.clear()
            self._tick_counter = 0
    
    def _log_summary(self) -> None:
        """
        Log diagnostic summary for all strategies.
        
        Requirement 7.10: Log diagnostic summary every 1000 ticks
        with rates AND top failure predicates for each active strategy
        
        Must be called with lock held.
        """
        for strategy_id, metrics in self._metrics.items():
            top_failures = metrics.get_top_failures(3)
            
            # Format top failures for logging
            top_failures_formatted = [
                {"type": f[0], "count": f[1]} for f in top_failures if f[1] > 0
            ]
            
            log_info(
                "strategy_diagnostics_summary",
                strategy_id=strategy_id,
                tick_count=metrics.tick_count,
                setup_count=metrics.setup_count,
                confirm_count=metrics.confirm_count,
                ev_pass_count=metrics.ev_pass_count,
                signal_count=metrics.signal_count,
                setup_rate=round(metrics.setup_rate, 4),
                confirm_rate=round(metrics.confirm_rate, 4),
                ev_rate=round(metrics.ev_rate, 4),
                execution_rate=round(metrics.execution_rate, 4),
                bottleneck=metrics.get_bottleneck(),
                top_failures=top_failures_formatted,
            )


# Global singleton instance for easy access
_global_diagnostics: Optional[StrategyDiagnostics] = None
_global_lock = threading.Lock()


def get_strategy_diagnostics() -> StrategyDiagnostics:
    """
    Get the global StrategyDiagnostics singleton.
    
    Creates the instance on first call.
    
    Returns:
        Global StrategyDiagnostics instance
    """
    global _global_diagnostics
    
    if _global_diagnostics is None:
        with _global_lock:
            if _global_diagnostics is None:
                _global_diagnostics = StrategyDiagnostics()
    
    return _global_diagnostics


def reset_strategy_diagnostics() -> None:
    """
    Reset the global StrategyDiagnostics singleton.
    
    Useful for testing.
    """
    global _global_diagnostics
    
    with _global_lock:
        if _global_diagnostics is not None:
            _global_diagnostics.reset()
