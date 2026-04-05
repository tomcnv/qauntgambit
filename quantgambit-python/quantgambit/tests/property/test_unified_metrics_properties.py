"""
Property-based tests for Unified Metrics.

Feature: trading-pipeline-integration

These tests verify the correctness properties of the unified metrics system,
ensuring consistent metric computation between live and backtest modes.

Uses hypothesis library with minimum 100 iterations per property test.

**Validates: Requirements 9.1, 9.2, 9.4, 9.6**
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Tuple

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

from quantgambit.integration.unified_metrics import (
    UnifiedMetrics,
    MetricsComparison,
    MetricsReconciler,
    empty_metrics,
    SIGNIFICANT_DIFFERENCE_THRESHOLD,
)


# ═══════════════════════════════════════════════════════════════
# STRATEGIES FOR PROPERTY-BASED TESTING
# ═══════════════════════════════════════════════════════════════

# Timestamp strategy for equity curve points
timestamp_strategy = st.datetimes(
    min_value=datetime(2020, 1, 1),
    max_value=datetime(2025, 12, 31),
    timezones=st.just(timezone.utc),
)

# Equity value strategy (positive values representing account equity)
equity_value_strategy = st.floats(
    min_value=1000.0,
    max_value=1000000.0,
    allow_nan=False,
    allow_infinity=False,
)


# PnL strategy for trades (can be positive or negative)
pnl_strategy = st.floats(
    min_value=-10000.0,
    max_value=10000.0,
    allow_nan=False,
    allow_infinity=False,
)

# PnL percentage strategy
pnl_pct_strategy = st.floats(
    min_value=-50.0,
    max_value=100.0,
    allow_nan=False,
    allow_infinity=False,
)

# Slippage in basis points
slippage_bps_strategy = st.floats(
    min_value=0.0,
    max_value=20.0,
    allow_nan=False,
    allow_infinity=False,
)

# Latency in milliseconds
latency_ms_strategy = st.floats(
    min_value=1.0,
    max_value=500.0,
    allow_nan=False,
    allow_infinity=False,
)

# Boolean strategy for partial fills
is_partial_strategy = st.booleans()


# Trade dictionary strategy
@st.composite
def trade_strategy(draw):
    """Generate a single trade dictionary."""
    pnl = draw(pnl_strategy)
    return {
        "pnl": pnl,
        "pnl_pct": draw(pnl_pct_strategy),
        "slippage_bps": draw(slippage_bps_strategy),
        "latency_ms": draw(latency_ms_strategy),
        "is_partial": draw(is_partial_strategy),
    }


# Trade list strategy
trade_list_strategy = st.lists(
    trade_strategy(),
    min_size=1,
    max_size=100,
)


@st.composite
def equity_curve_strategy(draw, min_size=2, max_size=100):
    """Generate a chronologically sorted equity curve.
    
    Returns a list of (datetime, equity) tuples sorted by timestamp.
    """
    size = draw(st.integers(min_value=min_size, max_value=max_size))
    
    # Generate a starting timestamp
    start_time = draw(timestamp_strategy)
    
    # Generate equity values
    initial_equity = draw(equity_value_strategy)
    
    # Generate equity curve with realistic changes
    curve = [(start_time, initial_equity)]
    current_equity = initial_equity
    
    for i in range(1, size):
        # Add time increment (1 hour to 1 day)
        time_delta = timedelta(hours=draw(st.integers(min_value=1, max_value=24)))
        next_time = curve[-1][0] + time_delta
        
        # Generate equity change (-5% to +5%)
        change_pct = draw(st.floats(min_value=-0.05, max_value=0.05, allow_nan=False, allow_infinity=False))
        current_equity = max(100.0, current_equity * (1 + change_pct))  # Ensure positive
        
        curve.append((next_time, current_equity))
    
    return curve


# Strategy for generating UnifiedMetrics with specific characteristics
@st.composite
def unified_metrics_strategy(draw):
    """Generate a UnifiedMetrics instance with valid values."""
    total_trades = draw(st.integers(min_value=1, max_value=1000))
    winning_trades = draw(st.integers(min_value=0, max_value=total_trades))
    losing_trades = total_trades - winning_trades
    
    win_rate = winning_trades / total_trades if total_trades > 0 else 0.0
    
    return UnifiedMetrics(
        total_return_pct=draw(st.floats(min_value=-50.0, max_value=200.0, allow_nan=False, allow_infinity=False)),
        annualized_return_pct=draw(st.floats(min_value=-100.0, max_value=500.0, allow_nan=False, allow_infinity=False)),
        sharpe_ratio=draw(st.floats(min_value=-3.0, max_value=5.0, allow_nan=False, allow_infinity=False)),
        sortino_ratio=draw(st.floats(min_value=-3.0, max_value=10.0, allow_nan=False, allow_infinity=False)),
        max_drawdown_pct=draw(st.floats(min_value=0.0, max_value=50.0, allow_nan=False, allow_infinity=False)),
        max_drawdown_duration_sec=draw(st.floats(min_value=0.0, max_value=86400 * 30, allow_nan=False, allow_infinity=False)),
        total_trades=total_trades,
        winning_trades=winning_trades,
        losing_trades=losing_trades,
        win_rate=win_rate,
        profit_factor=draw(st.floats(min_value=0.0, max_value=10.0, allow_nan=False, allow_infinity=False)),
        avg_trade_pnl=draw(st.floats(min_value=-1000.0, max_value=1000.0, allow_nan=False, allow_infinity=False)),
        avg_win_pct=draw(st.floats(min_value=0.0, max_value=50.0, allow_nan=False, allow_infinity=False)),
        avg_loss_pct=draw(st.floats(min_value=-50.0, max_value=0.0, allow_nan=False, allow_infinity=False)),
        avg_slippage_bps=draw(st.floats(min_value=0.0, max_value=20.0, allow_nan=False, allow_infinity=False)),
        avg_latency_ms=draw(st.floats(min_value=1.0, max_value=500.0, allow_nan=False, allow_infinity=False)),
        partial_fill_rate=draw(st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False)),
    )


@st.composite
def divergent_metrics_pair_strategy(draw):
    """Generate a pair of UnifiedMetrics with significant differences.
    
    Ensures at least one divergence factor threshold is exceeded.
    The implementation uses these thresholds:
    - slippage_diff: >0.5 bps
    - latency_diff: >10 ms
    - partial_fill_diff: >5%
    - drawdown_diff: >2%
    - sharpe_diff: >0.2
    - win_rate_diff: >5%
    - profit_factor_diff: >0.2
    - trade_count_diff: >10% of live trades
    - avg_pnl_diff: >10% of live avg
    - return_diff: >5 percentage points
    """
    # Generate base metrics
    base_return = draw(st.floats(min_value=10.0, max_value=100.0, allow_nan=False, allow_infinity=False))
    
    # Generate divergent return with absolute difference > 5 percentage points
    return_diff_abs = draw(st.floats(min_value=6.0, max_value=30.0, allow_nan=False, allow_infinity=False))
    return_sign = draw(st.sampled_from([-1, 1]))
    divergent_return = base_return + (return_diff_abs * return_sign)
    
    # Generate other metrics with some differences that exceed thresholds
    base_win_rate = draw(st.floats(min_value=0.3, max_value=0.6, allow_nan=False, allow_infinity=False))
    # Win rate diff > 5%
    win_rate_diff = draw(st.floats(min_value=0.06, max_value=0.15, allow_nan=False, allow_infinity=False))
    win_rate_sign = draw(st.sampled_from([-1, 1]))
    divergent_win_rate = max(0.0, min(1.0, base_win_rate + (win_rate_diff * win_rate_sign)))
    
    base_slippage = draw(st.floats(min_value=1.0, max_value=5.0, allow_nan=False, allow_infinity=False))
    # Slippage diff > 0.5 bps
    slippage_diff = draw(st.floats(min_value=0.6, max_value=3.0, allow_nan=False, allow_infinity=False))
    slippage_sign = draw(st.sampled_from([-1, 1]))
    divergent_slippage = max(0.0, base_slippage + (slippage_diff * slippage_sign))
    
    base_trades = draw(st.integers(min_value=50, max_value=200))
    # Trade count diff > 10% of live trades
    trade_diff_pct = draw(st.floats(min_value=0.12, max_value=0.3, allow_nan=False, allow_infinity=False))
    trade_sign = draw(st.sampled_from([-1, 1]))
    trade_diff = int(base_trades * trade_diff_pct * trade_sign)
    divergent_trades = max(1, base_trades + trade_diff)
    
    live_metrics = UnifiedMetrics(
        total_return_pct=base_return,
        annualized_return_pct=base_return * 2,
        sharpe_ratio=draw(st.floats(min_value=0.5, max_value=2.0, allow_nan=False, allow_infinity=False)),
        sortino_ratio=draw(st.floats(min_value=0.5, max_value=3.0, allow_nan=False, allow_infinity=False)),
        max_drawdown_pct=draw(st.floats(min_value=5.0, max_value=20.0, allow_nan=False, allow_infinity=False)),
        max_drawdown_duration_sec=draw(st.floats(min_value=3600.0, max_value=86400.0, allow_nan=False, allow_infinity=False)),
        total_trades=base_trades,
        winning_trades=int(base_trades * base_win_rate),
        losing_trades=base_trades - int(base_trades * base_win_rate),
        win_rate=base_win_rate,
        profit_factor=draw(st.floats(min_value=1.0, max_value=3.0, allow_nan=False, allow_infinity=False)),
        avg_trade_pnl=draw(st.floats(min_value=10.0, max_value=100.0, allow_nan=False, allow_infinity=False)),
        avg_win_pct=draw(st.floats(min_value=1.0, max_value=10.0, allow_nan=False, allow_infinity=False)),
        avg_loss_pct=draw(st.floats(min_value=-10.0, max_value=-1.0, allow_nan=False, allow_infinity=False)),
        avg_slippage_bps=base_slippage,
        avg_latency_ms=draw(st.floats(min_value=20.0, max_value=100.0, allow_nan=False, allow_infinity=False)),
        partial_fill_rate=draw(st.floats(min_value=0.0, max_value=0.3, allow_nan=False, allow_infinity=False)),
    )
    
    backtest_metrics = UnifiedMetrics(
        total_return_pct=divergent_return,
        annualized_return_pct=divergent_return * 2,
        sharpe_ratio=live_metrics.sharpe_ratio + draw(st.floats(min_value=-0.5, max_value=0.5, allow_nan=False, allow_infinity=False)),
        sortino_ratio=live_metrics.sortino_ratio + draw(st.floats(min_value=-0.5, max_value=0.5, allow_nan=False, allow_infinity=False)),
        max_drawdown_pct=live_metrics.max_drawdown_pct + draw(st.floats(min_value=-5.0, max_value=5.0, allow_nan=False, allow_infinity=False)),
        max_drawdown_duration_sec=live_metrics.max_drawdown_duration_sec,
        total_trades=divergent_trades,
        winning_trades=int(divergent_trades * divergent_win_rate),
        losing_trades=divergent_trades - int(divergent_trades * divergent_win_rate),
        win_rate=divergent_win_rate,
        profit_factor=live_metrics.profit_factor + draw(st.floats(min_value=-0.5, max_value=0.5, allow_nan=False, allow_infinity=False)),
        avg_trade_pnl=live_metrics.avg_trade_pnl + draw(st.floats(min_value=-20.0, max_value=20.0, allow_nan=False, allow_infinity=False)),
        avg_win_pct=live_metrics.avg_win_pct,
        avg_loss_pct=live_metrics.avg_loss_pct,
        avg_slippage_bps=divergent_slippage,
        avg_latency_ms=live_metrics.avg_latency_ms + draw(st.floats(min_value=-20.0, max_value=20.0, allow_nan=False, allow_infinity=False)),
        partial_fill_rate=live_metrics.partial_fill_rate,
    )
    
    return live_metrics, backtest_metrics


# ═══════════════════════════════════════════════════════════════
# PROPERTY 22: METRIC CALCULATION PARITY
# Feature: trading-pipeline-integration, Property 22
# Validates: Requirements 9.1, 9.2
# ═══════════════════════════════════════════════════════════════

class TestMetricCalculationParity:
    """
    Feature: trading-pipeline-integration, Property 22: Metric Calculation Parity
    
    For any identical set of trades and equity curve, the MetricsReconciler
    SHALL compute identical UnifiedMetrics values regardless of whether the
    data came from live or backtest mode.
    
    This tests that metric computation is deterministic.
    
    **Validates: Requirements 9.1, 9.2**
    """
    
    @settings(max_examples=100)
    @given(
        equity_curve=equity_curve_strategy(),
        trades=trade_list_strategy,
    )
    def test_compute_metrics_is_deterministic(
        self,
        equity_curve: List[Tuple[datetime, float]],
        trades: List[Dict[str, Any]],
    ):
        """
        **Validates: Requirements 9.1, 9.2**
        
        Property: FOR ALL equity curves E and trade lists T
        WHEN compute_metrics(E, T) is called twice THEN results are identical.
        
        This verifies that metric computation is deterministic - the same
        inputs always produce the same outputs.
        """
        reconciler = MetricsReconciler()
        
        # Compute metrics twice with identical inputs
        metrics1 = reconciler.compute_metrics(equity_curve, trades)
        metrics2 = reconciler.compute_metrics(equity_curve, trades)
        
        # All fields should be identical
        assert metrics1.total_return_pct == metrics2.total_return_pct, \
            "total_return_pct should be deterministic"
        assert metrics1.annualized_return_pct == metrics2.annualized_return_pct, \
            "annualized_return_pct should be deterministic"
        assert metrics1.sharpe_ratio == metrics2.sharpe_ratio, \
            "sharpe_ratio should be deterministic"
        assert metrics1.sortino_ratio == metrics2.sortino_ratio, \
            "sortino_ratio should be deterministic"
        assert metrics1.max_drawdown_pct == metrics2.max_drawdown_pct, \
            "max_drawdown_pct should be deterministic"
        assert metrics1.max_drawdown_duration_sec == metrics2.max_drawdown_duration_sec, \
            "max_drawdown_duration_sec should be deterministic"
        assert metrics1.total_trades == metrics2.total_trades, \
            "total_trades should be deterministic"
        assert metrics1.winning_trades == metrics2.winning_trades, \
            "winning_trades should be deterministic"
        assert metrics1.losing_trades == metrics2.losing_trades, \
            "losing_trades should be deterministic"
        assert metrics1.win_rate == metrics2.win_rate, \
            "win_rate should be deterministic"
        assert metrics1.profit_factor == metrics2.profit_factor, \
            "profit_factor should be deterministic"
        assert metrics1.avg_trade_pnl == metrics2.avg_trade_pnl, \
            "avg_trade_pnl should be deterministic"
        assert metrics1.avg_win_pct == metrics2.avg_win_pct, \
            "avg_win_pct should be deterministic"
        assert metrics1.avg_loss_pct == metrics2.avg_loss_pct, \
            "avg_loss_pct should be deterministic"
        assert metrics1.avg_slippage_bps == metrics2.avg_slippage_bps, \
            "avg_slippage_bps should be deterministic"
        assert metrics1.avg_latency_ms == metrics2.avg_latency_ms, \
            "avg_latency_ms should be deterministic"
        assert metrics1.partial_fill_rate == metrics2.partial_fill_rate, \
            "partial_fill_rate should be deterministic"


    @settings(max_examples=100)
    @given(
        equity_curve=equity_curve_strategy(),
        trades=trade_list_strategy,
        risk_free_rate=st.floats(min_value=0.0, max_value=0.1, allow_nan=False, allow_infinity=False),
    )
    def test_same_reconciler_produces_identical_results(
        self,
        equity_curve: List[Tuple[datetime, float]],
        trades: List[Dict[str, Any]],
        risk_free_rate: float,
    ):
        """
        **Validates: Requirements 9.1, 9.2**
        
        Property: For any equity curve and trades, using the same
        MetricsReconciler instance produces identical results on
        repeated calls.
        """
        reconciler = MetricsReconciler(risk_free_rate=risk_free_rate)
        
        # Compute metrics multiple times
        results = [reconciler.compute_metrics(equity_curve, trades) for _ in range(3)]
        
        # All results should be identical
        for i in range(1, len(results)):
            assert results[0].to_dict() == results[i].to_dict(), \
                f"Result {i} should match result 0"

    @settings(max_examples=100)
    @given(
        equity_curve=equity_curve_strategy(),
        trades=trade_list_strategy,
    )
    def test_different_reconciler_instances_produce_same_results(
        self,
        equity_curve: List[Tuple[datetime, float]],
        trades: List[Dict[str, Any]],
    ):
        """
        **Validates: Requirements 9.1, 9.2**
        
        Property: Different MetricsReconciler instances with the same
        configuration produce identical results for the same inputs.
        
        This ensures the calculation is not dependent on instance state.
        """
        reconciler1 = MetricsReconciler(risk_free_rate=0.05)
        reconciler2 = MetricsReconciler(risk_free_rate=0.05)
        
        metrics1 = reconciler1.compute_metrics(equity_curve, trades)
        metrics2 = reconciler2.compute_metrics(equity_curve, trades)
        
        # Results should be identical
        assert metrics1.to_dict() == metrics2.to_dict(), \
            "Different reconciler instances should produce identical results"

    @settings(max_examples=100)
    @given(
        equity_curve=equity_curve_strategy(),
        trades=trade_list_strategy,
    )
    def test_metrics_serialization_preserves_values(
        self,
        equity_curve: List[Tuple[datetime, float]],
        trades: List[Dict[str, Any]],
    ):
        """
        **Validates: Requirements 9.1**
        
        Property: Serializing metrics to dict and back preserves all values.
        """
        reconciler = MetricsReconciler()
        metrics = reconciler.compute_metrics(equity_curve, trades)
        
        # Serialize and deserialize
        metrics_dict = metrics.to_dict()
        restored = UnifiedMetrics.from_dict(metrics_dict)
        
        # All values should be preserved
        assert restored.to_dict() == metrics.to_dict(), \
            "Serialization round-trip should preserve all values"


    @settings(max_examples=100)
    @given(
        equity_curve=equity_curve_strategy(),
        trades=trade_list_strategy,
    )
    def test_trade_count_matches_input(
        self,
        equity_curve: List[Tuple[datetime, float]],
        trades: List[Dict[str, Any]],
    ):
        """
        **Validates: Requirements 9.1**
        
        Property: The total_trades metric equals the number of input trades.
        """
        reconciler = MetricsReconciler()
        metrics = reconciler.compute_metrics(equity_curve, trades)
        
        assert metrics.total_trades == len(trades), \
            "total_trades should equal input trade count"

    @settings(max_examples=100)
    @given(
        equity_curve=equity_curve_strategy(),
        trades=trade_list_strategy,
    )
    def test_winning_plus_losing_equals_total(
        self,
        equity_curve: List[Tuple[datetime, float]],
        trades: List[Dict[str, Any]],
    ):
        """
        **Validates: Requirements 9.1**
        
        Property: winning_trades + losing_trades <= total_trades
        (may not equal if some trades have pnl=0).
        """
        reconciler = MetricsReconciler()
        metrics = reconciler.compute_metrics(equity_curve, trades)
        
        assert metrics.winning_trades + metrics.losing_trades <= metrics.total_trades, \
            "winning + losing trades should not exceed total"

    @settings(max_examples=100)
    @given(
        equity_curve=equity_curve_strategy(),
        trades=trade_list_strategy,
    )
    def test_win_rate_is_valid_ratio(
        self,
        equity_curve: List[Tuple[datetime, float]],
        trades: List[Dict[str, Any]],
    ):
        """
        **Validates: Requirements 9.1**
        
        Property: win_rate is between 0 and 1 (inclusive).
        """
        reconciler = MetricsReconciler()
        metrics = reconciler.compute_metrics(equity_curve, trades)
        
        assert 0.0 <= metrics.win_rate <= 1.0, \
            f"win_rate should be between 0 and 1, got {metrics.win_rate}"

    @settings(max_examples=100)
    @given(
        equity_curve=equity_curve_strategy(),
        trades=trade_list_strategy,
    )
    def test_partial_fill_rate_is_valid_ratio(
        self,
        equity_curve: List[Tuple[datetime, float]],
        trades: List[Dict[str, Any]],
    ):
        """
        **Validates: Requirements 9.1**
        
        Property: partial_fill_rate is between 0 and 1 (inclusive).
        """
        reconciler = MetricsReconciler()
        metrics = reconciler.compute_metrics(equity_curve, trades)
        
        assert 0.0 <= metrics.partial_fill_rate <= 1.0, \
            f"partial_fill_rate should be between 0 and 1, got {metrics.partial_fill_rate}"


    @settings(max_examples=100)
    @given(
        equity_curve=equity_curve_strategy(),
        trades=trade_list_strategy,
    )
    def test_max_drawdown_is_non_negative(
        self,
        equity_curve: List[Tuple[datetime, float]],
        trades: List[Dict[str, Any]],
    ):
        """
        **Validates: Requirements 9.1**
        
        Property: max_drawdown_pct is non-negative (drawdown is a loss measure).
        """
        reconciler = MetricsReconciler()
        metrics = reconciler.compute_metrics(equity_curve, trades)
        
        assert metrics.max_drawdown_pct >= 0.0, \
            f"max_drawdown_pct should be non-negative, got {metrics.max_drawdown_pct}"

    @settings(max_examples=100)
    @given(
        equity_curve=equity_curve_strategy(),
        trades=trade_list_strategy,
    )
    def test_max_drawdown_duration_is_non_negative(
        self,
        equity_curve: List[Tuple[datetime, float]],
        trades: List[Dict[str, Any]],
    ):
        """
        **Validates: Requirements 9.1**
        
        Property: max_drawdown_duration_sec is non-negative.
        """
        reconciler = MetricsReconciler()
        metrics = reconciler.compute_metrics(equity_curve, trades)
        
        assert metrics.max_drawdown_duration_sec >= 0.0, \
            f"max_drawdown_duration_sec should be non-negative, got {metrics.max_drawdown_duration_sec}"


# ═══════════════════════════════════════════════════════════════
# PROPERTY 23: METRIC DIVERGENCE ATTRIBUTION
# Feature: trading-pipeline-integration, Property 23
# Validates: Requirements 9.4, 9.6
# ═══════════════════════════════════════════════════════════════

class TestMetricDivergenceAttribution:
    """
    Feature: trading-pipeline-integration, Property 23: Metric Divergence Attribution
    
    For any pairs of UnifiedMetrics (live, backtest) with significant differences,
    WHEN compare_metrics(live, backtest) is called THEN divergence_factors is non-empty.
    
    This tests that divergence attribution identifies contributing factors.
    
    **Validates: Requirements 9.4, 9.6**
    """
    
    @settings(max_examples=100)
    @given(metrics_pair=divergent_metrics_pair_strategy())
    def test_significant_divergence_produces_attribution_factors(
        self,
        metrics_pair: Tuple[UnifiedMetrics, UnifiedMetrics],
    ):
        """
        **Validates: Requirements 9.4, 9.6**
        
        Property: FOR ALL pairs of UnifiedMetrics (live, backtest) with
        significant differences WHEN compare_metrics(live, backtest) is called
        THEN divergence_factors is non-empty.
        
        The divergent_metrics_pair_strategy generates metrics that exceed
        at least one of the implementation's attribution thresholds:
        - return_diff: >5 percentage points
        - slippage_diff: >0.5 bps
        - win_rate_diff: >5%
        - trade_count_diff: >10% of live trades
        """
        live_metrics, backtest_metrics = metrics_pair
        
        reconciler = MetricsReconciler()
        comparison = reconciler.compare_metrics(live_metrics, backtest_metrics)
        
        # Divergence factors should be non-empty since the strategy generates
        # metrics that exceed at least one attribution threshold
        assert len(comparison.divergence_factors) > 0, \
            f"Divergence factors should be non-empty for divergent metrics pair. " \
            f"Live: return={live_metrics.total_return_pct:.1f}%, slippage={live_metrics.avg_slippage_bps:.1f}bps, " \
            f"win_rate={live_metrics.win_rate:.1%}, trades={live_metrics.total_trades}. " \
            f"Backtest: return={backtest_metrics.total_return_pct:.1f}%, slippage={backtest_metrics.avg_slippage_bps:.1f}bps, " \
            f"win_rate={backtest_metrics.win_rate:.1%}, trades={backtest_metrics.total_trades}"


    @settings(max_examples=100)
    @given(
        live_metrics=unified_metrics_strategy(),
        backtest_metrics=unified_metrics_strategy(),
    )
    def test_comparison_identifies_significant_differences(
        self,
        live_metrics: UnifiedMetrics,
        backtest_metrics: UnifiedMetrics,
    ):
        """
        **Validates: Requirements 9.4**
        
        Property: compare_metrics identifies all metrics that differ by
        more than the threshold (default 10%).
        """
        reconciler = MetricsReconciler()
        comparison = reconciler.compare_metrics(live_metrics, backtest_metrics)
        
        # Verify significant_differences contains only metrics with >10% difference
        for field_name, diff_info in comparison.significant_differences.items():
            assert diff_info["significant"] is True, \
                f"Field {field_name} in significant_differences should be marked significant"
            assert abs(diff_info["diff_pct"]) > SIGNIFICANT_DIFFERENCE_THRESHOLD, \
                f"Field {field_name} should have >10% difference"

    @settings(max_examples=100)
    @given(metrics=unified_metrics_strategy())
    def test_identical_metrics_have_no_divergence(
        self,
        metrics: UnifiedMetrics,
    ):
        """
        **Validates: Requirements 9.4**
        
        Property: When comparing identical metrics, there should be no
        significant differences and no divergence factors.
        """
        reconciler = MetricsReconciler()
        comparison = reconciler.compare_metrics(metrics, metrics)
        
        # No significant differences for identical metrics
        assert len(comparison.significant_differences) == 0, \
            "Identical metrics should have no significant differences"
        
        # No divergence factors for identical metrics
        assert len(comparison.divergence_factors) == 0, \
            "Identical metrics should have no divergence factors"
        
        # Overall similarity should be 1.0 (perfect match)
        assert comparison.overall_similarity == 1.0, \
            "Identical metrics should have similarity of 1.0"

    @settings(max_examples=100)
    @given(
        live_metrics=unified_metrics_strategy(),
        backtest_metrics=unified_metrics_strategy(),
    )
    def test_comparison_overall_similarity_is_valid(
        self,
        live_metrics: UnifiedMetrics,
        backtest_metrics: UnifiedMetrics,
    ):
        """
        **Validates: Requirements 9.4**
        
        Property: overall_similarity is between 0 and 1 (inclusive).
        """
        reconciler = MetricsReconciler()
        comparison = reconciler.compare_metrics(live_metrics, backtest_metrics)
        
        assert 0.0 <= comparison.overall_similarity <= 1.0, \
            f"overall_similarity should be between 0 and 1, got {comparison.overall_similarity}"

    @settings(max_examples=100)
    @given(
        live_metrics=unified_metrics_strategy(),
        backtest_metrics=unified_metrics_strategy(),
    )
    def test_comparison_has_timestamp(
        self,
        live_metrics: UnifiedMetrics,
        backtest_metrics: UnifiedMetrics,
    ):
        """
        **Validates: Requirements 9.4**
        
        Property: MetricsComparison has a valid comparison_timestamp.
        """
        reconciler = MetricsReconciler()
        comparison = reconciler.compare_metrics(live_metrics, backtest_metrics)
        
        assert comparison.comparison_timestamp is not None, \
            "comparison_timestamp should not be None"
        assert isinstance(comparison.comparison_timestamp, datetime), \
            "comparison_timestamp should be a datetime"


    @settings(max_examples=100)
    @given(
        live_metrics=unified_metrics_strategy(),
        backtest_metrics=unified_metrics_strategy(),
    )
    def test_comparison_preserves_input_metrics(
        self,
        live_metrics: UnifiedMetrics,
        backtest_metrics: UnifiedMetrics,
    ):
        """
        **Validates: Requirements 9.4**
        
        Property: MetricsComparison preserves the original live and backtest
        metrics exactly.
        """
        reconciler = MetricsReconciler()
        comparison = reconciler.compare_metrics(live_metrics, backtest_metrics)
        
        # Verify metrics are preserved
        assert comparison.live_metrics.to_dict() == live_metrics.to_dict(), \
            "live_metrics should be preserved in comparison"
        assert comparison.backtest_metrics.to_dict() == backtest_metrics.to_dict(), \
            "backtest_metrics should be preserved in comparison"

    @settings(max_examples=100)
    @given(
        live_metrics=unified_metrics_strategy(),
        backtest_metrics=unified_metrics_strategy(),
    )
    def test_comparison_serialization_round_trip(
        self,
        live_metrics: UnifiedMetrics,
        backtest_metrics: UnifiedMetrics,
    ):
        """
        **Validates: Requirements 9.4**
        
        Property: MetricsComparison can be serialized to dict and back
        without losing information.
        """
        reconciler = MetricsReconciler()
        comparison = reconciler.compare_metrics(live_metrics, backtest_metrics)
        
        # Serialize and deserialize
        comparison_dict = comparison.to_dict()
        restored = MetricsComparison.from_dict(comparison_dict)
        
        # Verify key fields are preserved
        assert restored.live_metrics.to_dict() == comparison.live_metrics.to_dict(), \
            "live_metrics should survive serialization"
        assert restored.backtest_metrics.to_dict() == comparison.backtest_metrics.to_dict(), \
            "backtest_metrics should survive serialization"
        assert restored.significant_differences == comparison.significant_differences, \
            "significant_differences should survive serialization"
        assert restored.divergence_factors == comparison.divergence_factors, \
            "divergence_factors should survive serialization"
        assert restored.overall_similarity == comparison.overall_similarity, \
            "overall_similarity should survive serialization"

    @settings(max_examples=100)
    @given(metrics_pair=divergent_metrics_pair_strategy())
    def test_divergence_factors_are_descriptive_strings(
        self,
        metrics_pair: Tuple[UnifiedMetrics, UnifiedMetrics],
    ):
        """
        **Validates: Requirements 9.6**
        
        Property: Each divergence factor is a non-empty descriptive string
        that identifies the contributing factor.
        """
        live_metrics, backtest_metrics = metrics_pair
        
        reconciler = MetricsReconciler()
        comparison = reconciler.compare_metrics(live_metrics, backtest_metrics)
        
        for factor in comparison.divergence_factors:
            assert isinstance(factor, str), \
                f"Divergence factor should be a string, got {type(factor)}"
            assert len(factor) > 0, \
                "Divergence factor should not be empty"
            # Factors should contain a colon separating the factor name from value
            assert ":" in factor or "_diff" in factor, \
                f"Divergence factor should be descriptive: {factor}"


    @settings(max_examples=100)
    @given(
        base_slippage=st.floats(min_value=1.0, max_value=5.0, allow_nan=False, allow_infinity=False),
        slippage_diff=st.floats(min_value=1.0, max_value=5.0, allow_nan=False, allow_infinity=False),
    )
    def test_slippage_difference_produces_attribution(
        self,
        base_slippage: float,
        slippage_diff: float,
    ):
        """
        **Validates: Requirements 9.6**
        
        Property: When slippage differs by more than 0.5 bps, the attribution
        should include a slippage_diff factor.
        """
        # Ensure difference is significant (>0.5 bps)
        assume(slippage_diff > 0.5)
        
        live_metrics = UnifiedMetrics(
            total_return_pct=10.0,
            avg_slippage_bps=base_slippage,
            total_trades=100,
            winning_trades=50,
            losing_trades=50,
            win_rate=0.5,
        )
        
        backtest_metrics = UnifiedMetrics(
            total_return_pct=10.0,
            avg_slippage_bps=base_slippage + slippage_diff,
            total_trades=100,
            winning_trades=50,
            losing_trades=50,
            win_rate=0.5,
        )
        
        reconciler = MetricsReconciler()
        comparison = reconciler.compare_metrics(live_metrics, backtest_metrics)
        
        # Should have slippage_diff in factors
        slippage_factors = [f for f in comparison.divergence_factors if "slippage_diff" in f]
        assert len(slippage_factors) > 0, \
            f"Should have slippage_diff factor when slippage differs by {slippage_diff:.1f} bps"

    @settings(max_examples=100)
    @given(
        base_win_rate=st.floats(min_value=0.3, max_value=0.6, allow_nan=False, allow_infinity=False),
        win_rate_diff=st.floats(min_value=0.06, max_value=0.2, allow_nan=False, allow_infinity=False),
    )
    def test_win_rate_difference_produces_attribution(
        self,
        base_win_rate: float,
        win_rate_diff: float,
    ):
        """
        **Validates: Requirements 9.6**
        
        Property: When win rate differs by more than 5%, the attribution
        should include a win_rate_diff factor.
        """
        # Ensure difference is significant (>5%)
        assume(win_rate_diff > 0.05)
        
        live_metrics = UnifiedMetrics(
            total_return_pct=10.0,
            total_trades=100,
            winning_trades=int(100 * base_win_rate),
            losing_trades=100 - int(100 * base_win_rate),
            win_rate=base_win_rate,
        )
        
        new_win_rate = min(1.0, base_win_rate + win_rate_diff)
        backtest_metrics = UnifiedMetrics(
            total_return_pct=10.0,
            total_trades=100,
            winning_trades=int(100 * new_win_rate),
            losing_trades=100 - int(100 * new_win_rate),
            win_rate=new_win_rate,
        )
        
        reconciler = MetricsReconciler()
        comparison = reconciler.compare_metrics(live_metrics, backtest_metrics)
        
        # Should have win_rate_diff in factors
        win_rate_factors = [f for f in comparison.divergence_factors if "win_rate_diff" in f]
        assert len(win_rate_factors) > 0, \
            f"Should have win_rate_diff factor when win rate differs by {win_rate_diff:.1%}"


    @settings(max_examples=100)
    @given(
        base_trades=st.integers(min_value=50, max_value=200),
        trade_diff_pct=st.floats(min_value=0.15, max_value=0.5, allow_nan=False, allow_infinity=False),
    )
    def test_trade_count_difference_produces_attribution(
        self,
        base_trades: int,
        trade_diff_pct: float,
    ):
        """
        **Validates: Requirements 9.6**
        
        Property: When trade count differs by more than 10%, the attribution
        should include a trade_count_diff factor.
        """
        # Ensure difference is significant (>10%)
        assume(trade_diff_pct > 0.1)
        
        trade_diff = int(base_trades * trade_diff_pct)
        assume(trade_diff > base_trades * 0.1)  # Ensure it exceeds threshold
        
        live_metrics = UnifiedMetrics(
            total_return_pct=10.0,
            total_trades=base_trades,
            winning_trades=base_trades // 2,
            losing_trades=base_trades - base_trades // 2,
            win_rate=0.5,
        )
        
        new_trades = base_trades + trade_diff
        backtest_metrics = UnifiedMetrics(
            total_return_pct=10.0,
            total_trades=new_trades,
            winning_trades=new_trades // 2,
            losing_trades=new_trades - new_trades // 2,
            win_rate=0.5,
        )
        
        reconciler = MetricsReconciler()
        comparison = reconciler.compare_metrics(live_metrics, backtest_metrics)
        
        # Should have trade_count_diff in factors
        trade_factors = [f for f in comparison.divergence_factors if "trade_count_diff" in f]
        assert len(trade_factors) > 0, \
            f"Should have trade_count_diff factor when trades differ by {trade_diff}"

    @settings(max_examples=100)
    @given(
        live_metrics=unified_metrics_strategy(),
        backtest_metrics=unified_metrics_strategy(),
    )
    def test_has_significant_differences_method(
        self,
        live_metrics: UnifiedMetrics,
        backtest_metrics: UnifiedMetrics,
    ):
        """
        **Validates: Requirements 9.4**
        
        Property: has_significant_differences() returns True if and only if
        significant_differences is non-empty.
        """
        reconciler = MetricsReconciler()
        comparison = reconciler.compare_metrics(live_metrics, backtest_metrics)
        
        has_diffs = comparison.has_significant_differences()
        has_entries = len(comparison.significant_differences) > 0
        
        assert has_diffs == has_entries, \
            "has_significant_differences() should match significant_differences content"

    @settings(max_examples=100)
    @given(
        live_metrics=unified_metrics_strategy(),
        backtest_metrics=unified_metrics_strategy(),
    )
    def test_get_most_significant_difference(
        self,
        live_metrics: UnifiedMetrics,
        backtest_metrics: UnifiedMetrics,
    ):
        """
        **Validates: Requirements 9.4**
        
        Property: get_most_significant_difference() returns the metric with
        the largest percentage difference, or None if no differences.
        """
        reconciler = MetricsReconciler()
        comparison = reconciler.compare_metrics(live_metrics, backtest_metrics)
        
        most_sig = comparison.get_most_significant_difference()
        
        if len(comparison.significant_differences) == 0:
            assert most_sig is None, \
                "Should return None when no significant differences"
        else:
            assert most_sig is not None, \
                "Should return a value when significant differences exist"
            
            metric_name, diff_info = most_sig
            
            # Verify it's actually the largest difference
            for other_name, other_info in comparison.significant_differences.items():
                assert abs(diff_info["diff_pct"]) >= abs(other_info["diff_pct"]), \
                    f"{metric_name} should have largest diff, but {other_name} has larger"
