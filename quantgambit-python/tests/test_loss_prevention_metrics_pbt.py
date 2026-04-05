"""
Property-based tests for LossPreventionMetrics calculation.

Feature: trading-loss-fixes
Tests correctness properties for:
- Property 8: Loss Prevention Metrics Calculation

**Validates: Requirements 8.4**
"""

import pytest
import asyncio
from hypothesis import given, strategies as st, settings, assume
from typing import Dict, Any

from quantgambit.observability.loss_prevention_metrics import (
    LossPreventionMetrics,
    LossPreventionMetricsAggregator,
    DEFAULT_AVG_LOSS_PER_TRADE_USD,
)
from quantgambit.observability.blocked_signal_telemetry import (
    BlockedSignalRepository,
    BlockedSignalRecord,
)


# =============================================================================
# Test Strategies (Generators)
# =============================================================================

# Rejection reasons
rejection_reasons = st.sampled_from([
    "low_confidence",
    "confidence_gate",
    "strategy_trend_mismatch",
    "fee_trap",
    "session_mismatch",
    "execution_throttle",
    "cooldown",
    "hysteresis",
    "fee_check",
    "hourly_limit",
])

# Counts per reason (reasonable range)
count_per_reason = st.integers(min_value=0, max_value=1000)

# Average loss per trade (positive values)
avg_loss_per_trade = st.floats(min_value=0.01, max_value=1000.0, allow_nan=False, allow_infinity=False)

# Window hours
window_hours = st.floats(min_value=0.1, max_value=168.0, allow_nan=False, allow_infinity=False)

# Generate a dict of rejection reasons to counts
@st.composite
def rejection_counts_dict(draw):
    """Generate a dictionary of rejection reasons to counts."""
    reasons = draw(st.lists(rejection_reasons, min_size=0, max_size=10, unique=True))
    counts = {}
    for reason in reasons:
        counts[reason] = draw(count_per_reason)
    return counts


# =============================================================================
# Property 8: Loss Prevention Metrics Calculation
# Feature: trading-loss-fixes, Property 8: Loss Prevention Metrics Calculation
# Validates: Requirements 8.4
# =============================================================================

@settings(max_examples=100)
@given(
    counts=rejection_counts_dict(),
    avg_loss=avg_loss_per_trade,
)
def test_property_8_estimated_losses_equals_count_times_avg_loss(
    counts: Dict[str, int],
    avg_loss: float,
):
    """
    Property 8: Loss Prevention Metrics Calculation
    
    *For any* set of blocked signals, the estimated_losses_avoided SHALL equal
    (blocked_signal_count × average_loss_per_trade_usd) where average_loss_per_trade_usd
    is calculated from historical losing trades.
    
    **Validates: Requirements 8.4**
    """
    # Create aggregator with specified avg loss
    aggregator = LossPreventionMetricsAggregator(
        repository=None,
        avg_loss_per_trade_usd=avg_loss,
    )
    
    # Get metrics synchronously
    metrics = aggregator.get_metrics_sync(
        counts_by_reason=counts,
        window_hours=24.0,
    )
    
    # Calculate expected values
    total_rejected = sum(counts.values())
    expected_losses_avoided = total_rejected * avg_loss
    
    # Property: estimated_losses_avoided = count × avg_loss_per_trade
    assert abs(metrics.estimated_losses_avoided_usd - expected_losses_avoided) < 0.001, \
        f"Expected losses avoided {expected_losses_avoided}, got {metrics.estimated_losses_avoided_usd}"
    
    # Property: total_signals_rejected matches sum of counts
    assert metrics.total_signals_rejected == total_rejected, \
        f"Expected total rejected {total_rejected}, got {metrics.total_signals_rejected}"


@settings(max_examples=100)
@given(
    counts=rejection_counts_dict(),
    avg_loss=avg_loss_per_trade,
)
def test_property_8_rejection_breakdown_preserved(
    counts: Dict[str, int],
    avg_loss: float,
):
    """
    Property 8: Rejection Breakdown Preservation
    
    *For any* set of blocked signals, the rejection_breakdown in the metrics
    SHALL exactly match the input counts by reason.
    
    **Validates: Requirements 8.4**
    """
    # Create aggregator
    aggregator = LossPreventionMetricsAggregator(
        repository=None,
        avg_loss_per_trade_usd=avg_loss,
    )
    
    # Get metrics
    metrics = aggregator.get_metrics_sync(
        counts_by_reason=counts,
        window_hours=24.0,
    )
    
    # Property: rejection_breakdown matches input counts
    assert metrics.rejection_breakdown == counts, \
        f"Expected breakdown {counts}, got {metrics.rejection_breakdown}"


@settings(max_examples=100)
@given(
    counts=rejection_counts_dict(),
)
def test_property_8_per_reason_counts_extracted_correctly(
    counts: Dict[str, int],
):
    """
    Property 8: Per-Reason Counts Extraction
    
    *For any* set of blocked signals, the per-reason counts (low_confidence_count,
    strategy_trend_mismatch_count, fee_trap_count, session_mismatch_count) SHALL
    be correctly extracted from the rejection breakdown.
    
    **Validates: Requirements 8.4**
    """
    # Create aggregator
    aggregator = LossPreventionMetricsAggregator(repository=None)
    
    # Get metrics
    metrics = aggregator.get_metrics_sync(
        counts_by_reason=counts,
        window_hours=24.0,
    )
    
    # Calculate expected per-reason counts
    expected_low_confidence = (
        counts.get("low_confidence", 0) +
        counts.get("confidence_gate", 0)
    )
    expected_strategy_trend = counts.get("strategy_trend_mismatch", 0)
    expected_fee_trap = counts.get("fee_trap", 0)
    expected_session = counts.get("session_mismatch", 0)
    
    # Property: Per-reason counts match expected values
    assert metrics.low_confidence_count == expected_low_confidence, \
        f"Expected low_confidence_count {expected_low_confidence}, got {metrics.low_confidence_count}"
    assert metrics.strategy_trend_mismatch_count == expected_strategy_trend, \
        f"Expected strategy_trend_mismatch_count {expected_strategy_trend}, got {metrics.strategy_trend_mismatch_count}"
    assert metrics.fee_trap_count == expected_fee_trap, \
        f"Expected fee_trap_count {expected_fee_trap}, got {metrics.fee_trap_count}"
    assert metrics.session_mismatch_count == expected_session, \
        f"Expected session_mismatch_count {expected_session}, got {metrics.session_mismatch_count}"


@settings(max_examples=100)
@given(
    rejected_count=st.integers(min_value=0, max_value=10000),
    avg_loss=avg_loss_per_trade,
)
def test_property_8_static_calculation_formula(
    rejected_count: int,
    avg_loss: float,
):
    """
    Property 8: Static Calculation Formula
    
    *For any* rejected count and average loss, the calculate_estimated_losses_avoided
    static method SHALL return exactly (rejected_count × avg_loss).
    
    **Validates: Requirements 8.4**
    """
    # Calculate using static method
    result = LossPreventionMetricsAggregator.calculate_estimated_losses_avoided(
        rejected_count=rejected_count,
        avg_loss_per_trade=avg_loss,
    )
    
    # Expected value
    expected = rejected_count * avg_loss
    
    # Property: Result equals count × avg_loss
    assert abs(result - expected) < 0.001, \
        f"Expected {expected}, got {result}"


@settings(max_examples=100)
@given(
    counts=rejection_counts_dict(),
    hours=window_hours,
)
def test_property_8_time_window_set_correctly(
    counts: Dict[str, int],
    hours: float,
):
    """
    Property 8: Time Window Configuration
    
    *For any* window_hours value, the metrics SHALL have window_start and window_end
    set such that (window_end - window_start) equals window_hours × 3600 seconds.
    
    **Validates: Requirements 8.4**
    """
    # Create aggregator
    aggregator = LossPreventionMetricsAggregator(repository=None)
    
    # Get metrics with specified window
    metrics = aggregator.get_metrics_sync(
        counts_by_reason=counts,
        window_hours=hours,
    )
    
    # Calculate window duration
    window_duration = metrics.window_end - metrics.window_start
    expected_duration = hours * 3600
    
    # Property: Window duration matches expected (within 1 second tolerance for timing)
    assert abs(window_duration - expected_duration) < 1.0, \
        f"Expected window duration {expected_duration}s, got {window_duration}s"


@settings(max_examples=100)
@given(
    counts=rejection_counts_dict(),
    avg_loss=avg_loss_per_trade,
)
def test_property_8_to_dict_serialization(
    counts: Dict[str, int],
    avg_loss: float,
):
    """
    Property 8: Metrics Serialization
    
    *For any* LossPreventionMetrics, converting to dict SHALL preserve all
    fields for JSON serialization.
    
    **Validates: Requirements 8.4**
    """
    # Create aggregator and get metrics
    aggregator = LossPreventionMetricsAggregator(
        repository=None,
        avg_loss_per_trade_usd=avg_loss,
    )
    metrics = aggregator.get_metrics_sync(
        counts_by_reason=counts,
        window_hours=24.0,
    )
    
    # Convert to dict
    metrics_dict = metrics.to_dict()
    
    # Property: All required fields are present
    required_fields = [
        "total_signals_rejected",
        "rejection_breakdown",
        "estimated_losses_avoided_usd",
        "average_loss_per_trade_usd",
        "low_confidence_count",
        "strategy_trend_mismatch_count",
        "fee_trap_count",
        "session_mismatch_count",
        "window_start",
        "window_end",
    ]
    
    for field in required_fields:
        assert field in metrics_dict, \
            f"Required field '{field}' missing from metrics dict"
    
    # Property: Values match original metrics
    assert metrics_dict["total_signals_rejected"] == metrics.total_signals_rejected
    assert metrics_dict["rejection_breakdown"] == metrics.rejection_breakdown
    assert metrics_dict["estimated_losses_avoided_usd"] == metrics.estimated_losses_avoided_usd
    assert metrics_dict["average_loss_per_trade_usd"] == metrics.average_loss_per_trade_usd


@settings(max_examples=100)
@given(
    new_avg_loss=avg_loss_per_trade,
)
def test_property_8_avg_loss_update(
    new_avg_loss: float,
):
    """
    Property 8: Average Loss Update
    
    *For any* positive average loss value, calling set_avg_loss_per_trade SHALL
    update the aggregator's average loss value.
    
    **Validates: Requirements 8.4**
    """
    # Create aggregator with default value
    aggregator = LossPreventionMetricsAggregator(repository=None)
    
    # Update average loss
    aggregator.set_avg_loss_per_trade(new_avg_loss)
    
    # Get metrics with some counts
    metrics = aggregator.get_metrics_sync(
        counts_by_reason={"fee_trap": 10},
        window_hours=24.0,
    )
    
    # Property: Average loss is updated
    assert metrics.average_loss_per_trade_usd == new_avg_loss, \
        f"Expected avg loss {new_avg_loss}, got {metrics.average_loss_per_trade_usd}"
    
    # Property: Estimated losses use new average
    expected_losses = 10 * new_avg_loss
    assert abs(metrics.estimated_losses_avoided_usd - expected_losses) < 0.001, \
        f"Expected losses {expected_losses}, got {metrics.estimated_losses_avoided_usd}"


@settings(max_examples=50)
@given(
    hours=window_hours,
)
def test_property_8_empty_metrics_factory(
    hours: float,
):
    """
    Property 8: Empty Metrics Factory
    
    *For any* window_hours value, LossPreventionMetrics.empty() SHALL return
    metrics with zero counts and correct time window.
    
    **Validates: Requirements 8.4**
    """
    # Create empty metrics
    metrics = LossPreventionMetrics.empty(window_hours=hours)
    
    # Property: All counts are zero
    assert metrics.total_signals_rejected == 0
    assert metrics.low_confidence_count == 0
    assert metrics.strategy_trend_mismatch_count == 0
    assert metrics.fee_trap_count == 0
    assert metrics.session_mismatch_count == 0
    assert metrics.estimated_losses_avoided_usd == 0.0
    assert metrics.rejection_breakdown == {}
    
    # Property: Default average loss is set
    assert metrics.average_loss_per_trade_usd == DEFAULT_AVG_LOSS_PER_TRADE_USD
    
    # Property: Time window is set correctly
    window_duration = metrics.window_end - metrics.window_start
    expected_duration = hours * 3600
    assert abs(window_duration - expected_duration) < 1.0, \
        f"Expected window duration {expected_duration}s, got {window_duration}s"
