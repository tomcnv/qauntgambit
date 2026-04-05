"""
Property-based tests for Coverage Guardrails.

Feature: midvol-coverage-restoration
Tests correctness properties for:
- Property 7: Guardrail Alert Triggering

**Validates: Requirements 8.1, 8.2, 8.3**
"""

import pytest
import time
from hypothesis import given, strategies as st, settings, assume
from typing import List, Optional

from quantgambit.observability.coverage_guardrails import (
    CoverageGuardrailsTracker,
    CoverageMetrics,
    TradeRecord,
    GuardrailAlert,
    AlertType,
    AlertSeverity,
    calculate_expectancy,
    calculate_win_rate,
    get_atr_bucket,
)


# =============================================================================
# Test Strategies (Generators)
# =============================================================================

# PnL values (can be positive or negative)
pnl_value = st.floats(min_value=-1000.0, max_value=1000.0, allow_nan=False, allow_infinity=False)

# Positive PnL (wins)
positive_pnl = st.floats(min_value=0.01, max_value=1000.0, allow_nan=False, allow_infinity=False)

# Negative PnL (losses)
negative_pnl = st.floats(min_value=-1000.0, max_value=-0.01, allow_nan=False, allow_infinity=False)

# Win rate (0.0 to 1.0)
win_rate_value = st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False)

# Average win/loss (positive values)
avg_value = st.floats(min_value=0.0, max_value=1000.0, allow_nan=False, allow_infinity=False)

# Trade count
trade_count = st.integers(min_value=0, max_value=100)

# Profile IDs
profile_id = st.sampled_from([
    "midvol_mean_reversion",
    "midvol_expansion",
    "range_market_scalp",
    "breakout_scalp",
    "low_vol_grind",
])

# Symbols
symbol = st.sampled_from(["BTCUSDT", "ETHUSDT", "SOLUSDT"])

# ATR ratios
atr_ratio = st.floats(min_value=0.1, max_value=5.0, allow_nan=False, allow_infinity=False)

# Baseline trade count
baseline_count = st.integers(min_value=1, max_value=50)

# Trade count multiplier
multiplier = st.floats(min_value=1.5, max_value=10.0, allow_nan=False, allow_infinity=False)

# Minimum win rate threshold
min_win_rate = st.floats(min_value=0.3, max_value=0.7, allow_nan=False, allow_infinity=False)


@st.composite
def trade_record(draw):
    """Generate a single trade record."""
    return TradeRecord(
        timestamp=time.time() - draw(st.floats(min_value=0, max_value=3600)),
        pnl=draw(pnl_value),
        profile_id=draw(profile_id),
        symbol=draw(symbol),
        atr_ratio_at_entry=draw(st.one_of(st.none(), atr_ratio)),
    )


@st.composite
def winning_trade_record(draw):
    """Generate a winning trade record (pnl > 0)."""
    return TradeRecord(
        timestamp=time.time() - draw(st.floats(min_value=0, max_value=3600)),
        pnl=draw(positive_pnl),
        profile_id=draw(profile_id),
        symbol=draw(symbol),
        atr_ratio_at_entry=draw(st.one_of(st.none(), atr_ratio)),
    )


@st.composite
def losing_trade_record(draw):
    """Generate a losing trade record (pnl <= 0)."""
    return TradeRecord(
        timestamp=time.time() - draw(st.floats(min_value=0, max_value=3600)),
        pnl=draw(negative_pnl),
        profile_id=draw(profile_id),
        symbol=draw(symbol),
        atr_ratio_at_entry=draw(st.one_of(st.none(), atr_ratio)),
    )


@st.composite
def trade_list(draw, min_size=0, max_size=50):
    """Generate a list of trade records."""
    return draw(st.lists(trade_record(), min_size=min_size, max_size=max_size))


# =============================================================================
# Property 7: Guardrail Alert Triggering
# Feature: midvol-coverage-restoration, Property 7: Guardrail Alert Triggering
# Validates: Requirements 8.1, 8.2, 8.3
# =============================================================================

@settings(max_examples=100)
@given(
    avg_win=avg_value,
    avg_loss=avg_value,
    win_rate=win_rate_value,
)
def test_property_7_expectancy_formula(
    avg_win: float,
    avg_loss: float,
    win_rate: float,
):
    """
    Property 7: Expectancy Formula Correctness
    
    *For any* trading session metrics, expectancy SHALL equal
    (avg_win * win_rate) - (avg_loss * (1 - win_rate))
    
    **Validates: Requirements 8.3**
    """
    # Calculate expectancy using the function
    result = calculate_expectancy(avg_win, avg_loss, win_rate)
    
    # Calculate expected value manually
    loss_rate = 1.0 - win_rate
    expected = (avg_win * win_rate) - (avg_loss * loss_rate)
    
    # Property: Result matches formula
    assert abs(result - expected) < 0.0001, \
        f"Expected expectancy {expected}, got {result}"


@settings(max_examples=100)
@given(
    win_count=st.integers(min_value=0, max_value=100),
    total_count=st.integers(min_value=0, max_value=100),
)
def test_property_7_win_rate_calculation(
    win_count: int,
    total_count: int,
):
    """
    Property 7: Win Rate Calculation
    
    *For any* win count and total count, win_rate SHALL equal
    win_count / total_count (or 0 if total_count is 0)
    
    **Validates: Requirements 8.2**
    """
    # Ensure win_count <= total_count
    if total_count > 0:
        win_count = min(win_count, total_count)
    
    result = calculate_win_rate(win_count, total_count)
    
    if total_count == 0:
        assert result == 0.0, "Win rate should be 0 when no trades"
    else:
        expected = win_count / total_count
        assert abs(result - expected) < 0.0001, \
            f"Expected win rate {expected}, got {result}"



@settings(max_examples=100)
@given(
    baseline=baseline_count,
    mult=multiplier,
    num_trades=st.integers(min_value=0, max_value=200),
)
def test_property_7_trade_count_spike_alert(
    baseline: int,
    mult: float,
    num_trades: int,
):
    """
    Property 7: Trade Count Spike Alert
    
    *For any* trading session, if trade_count > (baseline × multiplier),
    the system SHALL emit a warning alert.
    
    **Validates: Requirements 8.1**
    """
    # Create tracker with specified baseline and multiplier
    tracker = CoverageGuardrailsTracker(
        baseline_trade_count_24h=baseline,
        trade_count_multiplier=mult,
        window_hours=24.0,
    )
    tracker.set_alert_cooldown(0)  # Disable cooldown for testing
    
    # Add trades
    now = time.time()
    for i in range(num_trades):
        tracker.record_trade_simple(
            pnl=10.0,  # All wins to avoid other alerts
            profile_id="test_profile",
            symbol="BTCUSDT",
            timestamp=now - i,
        )
    
    # Check alerts
    alerts = tracker.check_alerts()
    
    # Calculate threshold
    threshold = baseline * mult
    
    # Property: Alert emitted if and only if trade_count > threshold
    trade_count_alerts = [a for a in alerts if a.alert_type == AlertType.TRADE_COUNT_SPIKE]
    
    if num_trades > threshold:
        assert len(trade_count_alerts) == 1, \
            f"Expected trade count spike alert when {num_trades} > {threshold}"
        assert trade_count_alerts[0].severity == AlertSeverity.WARNING
        assert trade_count_alerts[0].current_value == num_trades
    else:
        assert len(trade_count_alerts) == 0, \
            f"Should not emit trade count spike alert when {num_trades} <= {threshold}"


@settings(max_examples=100)
@given(
    min_wr=min_win_rate,
    num_wins=st.integers(min_value=0, max_value=50),
    num_losses=st.integers(min_value=0, max_value=50),
)
def test_property_7_win_rate_low_alert(
    min_wr: float,
    num_wins: int,
    num_losses: int,
):
    """
    Property 7: Win Rate Low Alert
    
    *For any* trading session with >= 10 trades, if win_rate < min_win_rate,
    the system SHALL emit a warning alert.
    
    **Validates: Requirements 8.2**
    """
    total_trades = num_wins + num_losses
    
    # Skip if not enough trades for statistical significance
    assume(total_trades >= 10)
    
    # Create tracker
    tracker = CoverageGuardrailsTracker(
        baseline_trade_count_24h=1000,  # High baseline to avoid trade count alerts
        min_win_rate=min_wr,
        window_hours=24.0,
    )
    tracker.set_alert_cooldown(0)  # Disable cooldown for testing
    
    # Add winning trades
    now = time.time()
    for i in range(num_wins):
        tracker.record_trade_simple(
            pnl=10.0,
            profile_id="test_profile",
            symbol="BTCUSDT",
            timestamp=now - i,
        )
    
    # Add losing trades
    for i in range(num_losses):
        tracker.record_trade_simple(
            pnl=-10.0,
            profile_id="test_profile",
            symbol="BTCUSDT",
            timestamp=now - num_wins - i,
        )
    
    # Check alerts
    alerts = tracker.check_alerts()
    
    # Calculate actual win rate
    actual_win_rate = num_wins / total_trades if total_trades > 0 else 0.0
    
    # Property: Alert emitted if and only if win_rate < min_win_rate
    win_rate_alerts = [a for a in alerts if a.alert_type == AlertType.WIN_RATE_LOW]
    
    if actual_win_rate < min_wr:
        assert len(win_rate_alerts) == 1, \
            f"Expected win rate low alert when {actual_win_rate:.2%} < {min_wr:.2%}"
        assert win_rate_alerts[0].severity == AlertSeverity.WARNING
        assert abs(win_rate_alerts[0].current_value - actual_win_rate) < 0.0001
    else:
        assert len(win_rate_alerts) == 0, \
            f"Should not emit win rate low alert when {actual_win_rate:.2%} >= {min_wr:.2%}"


@settings(max_examples=100)
@given(
    num_wins=st.integers(min_value=0, max_value=30),
    num_losses=st.integers(min_value=0, max_value=30),
    avg_win_pnl=positive_pnl,
    avg_loss_pnl=positive_pnl,  # Will be negated
)
def test_property_7_expectancy_negative_alert(
    num_wins: int,
    num_losses: int,
    avg_win_pnl: float,
    avg_loss_pnl: float,
):
    """
    Property 7: Expectancy Negative Alert
    
    *For any* trading session with >= 10 trades, if expectancy < 0,
    the system SHALL emit a critical alert.
    
    **Validates: Requirements 8.3**
    """
    total_trades = num_wins + num_losses
    
    # Skip if not enough trades for statistical significance
    assume(total_trades >= 10)
    
    # Create tracker
    tracker = CoverageGuardrailsTracker(
        baseline_trade_count_24h=1000,  # High baseline to avoid trade count alerts
        min_win_rate=0.0,  # Disable win rate alerts
        window_hours=24.0,
    )
    tracker.set_alert_cooldown(0)  # Disable cooldown for testing
    
    # Add winning trades
    now = time.time()
    for i in range(num_wins):
        tracker.record_trade_simple(
            pnl=avg_win_pnl,
            profile_id="test_profile",
            symbol="BTCUSDT",
            timestamp=now - i,
        )
    
    # Add losing trades (negative PnL)
    for i in range(num_losses):
        tracker.record_trade_simple(
            pnl=-avg_loss_pnl,
            profile_id="test_profile",
            symbol="BTCUSDT",
            timestamp=now - num_wins - i,
        )
    
    # Check alerts
    alerts = tracker.check_alerts()
    
    # Calculate expected expectancy
    win_rate = num_wins / total_trades if total_trades > 0 else 0.0
    expected_expectancy = calculate_expectancy(avg_win_pnl, avg_loss_pnl, win_rate)
    
    # Property: Alert emitted if and only if expectancy < 0
    expectancy_alerts = [a for a in alerts if a.alert_type == AlertType.EXPECTANCY_NEGATIVE]
    
    if expected_expectancy < 0:
        assert len(expectancy_alerts) == 1, \
            f"Expected expectancy negative alert when expectancy = {expected_expectancy:.2f}"
        assert expectancy_alerts[0].severity == AlertSeverity.CRITICAL
    else:
        assert len(expectancy_alerts) == 0, \
            f"Should not emit expectancy negative alert when expectancy = {expected_expectancy:.2f}"


@settings(max_examples=100)
@given(
    trades=trade_list(min_size=0, max_size=30),
)
def test_property_7_metrics_consistency(
    trades: List[TradeRecord],
):
    """
    Property 7: Metrics Consistency
    
    *For any* set of trades, the metrics SHALL be internally consistent:
    - trade_count = win_count + loss_count
    - win_rate = win_count / trade_count (or 0 if no trades)
    - total_pnl = sum of all trade PnLs
    
    **Validates: Requirements 8.1, 8.2, 8.3**
    """
    # Create tracker
    tracker = CoverageGuardrailsTracker(window_hours=24.0)
    
    # Add trades
    for trade in trades:
        tracker.record_trade(trade)
    
    # Get metrics
    metrics = tracker.get_metrics()
    
    # Property: trade_count = win_count + loss_count
    assert metrics.trade_count == metrics.win_count + metrics.loss_count, \
        f"trade_count ({metrics.trade_count}) != win_count ({metrics.win_count}) + loss_count ({metrics.loss_count})"
    
    # Property: win_rate consistency
    if metrics.trade_count > 0:
        expected_win_rate = metrics.win_count / metrics.trade_count
        assert abs(metrics.win_rate - expected_win_rate) < 0.0001, \
            f"win_rate ({metrics.win_rate}) != win_count/trade_count ({expected_win_rate})"
    else:
        assert metrics.win_rate == 0.0, "win_rate should be 0 when no trades"
    
    # Property: total_pnl = sum of trade PnLs
    expected_total_pnl = sum(t.pnl for t in trades)
    assert abs(metrics.total_pnl - expected_total_pnl) < 0.01, \
        f"total_pnl ({metrics.total_pnl}) != sum of PnLs ({expected_total_pnl})"


@settings(max_examples=100)
@given(
    atr=st.one_of(
        st.none(),
        st.floats(min_value=0.0, max_value=10.0, allow_nan=False, allow_infinity=False),
    ),
)
def test_property_7_atr_bucket_assignment(
    atr: Optional[float],
):
    """
    Property 7: ATR Bucket Assignment
    
    *For any* ATR ratio, the bucket assignment SHALL be deterministic
    and fall into one of the defined buckets.
    
    **Validates: Requirements 8.4**
    """
    bucket = get_atr_bucket(atr)
    
    valid_buckets = [
        "unknown",
        "very_low_<0.5",
        "low_0.5-1.0",
        "midvol_low_1.0-1.4",
        "midvol_high_1.4-2.0",
        "high_2.0-3.0",
        "very_high_>3.0",
    ]
    
    # Property: Bucket is one of the valid buckets
    assert bucket in valid_buckets, f"Invalid bucket: {bucket}"
    
    # Property: Bucket assignment is correct based on ATR value
    if atr is None:
        assert bucket == "unknown"
    elif atr < 0.5:
        assert bucket == "very_low_<0.5"
    elif atr < 1.0:
        assert bucket == "low_0.5-1.0"
    elif atr < 1.4:
        assert bucket == "midvol_low_1.0-1.4"
    elif atr < 2.0:
        assert bucket == "midvol_high_1.4-2.0"
    elif atr < 3.0:
        assert bucket == "high_2.0-3.0"
    else:
        assert bucket == "very_high_>3.0"


@settings(max_examples=100)
@given(
    trades=trade_list(min_size=1, max_size=30),
)
def test_property_7_profile_attribution(
    trades: List[TradeRecord],
):
    """
    Property 7: Profile Attribution
    
    *For any* set of trades, the trades_by_profile in metrics SHALL
    correctly count trades per profile.
    
    **Validates: Requirements 8.5**
    """
    # Create tracker
    tracker = CoverageGuardrailsTracker(window_hours=24.0)
    
    # Add trades
    for trade in trades:
        tracker.record_trade(trade)
    
    # Get metrics
    metrics = tracker.get_metrics()
    
    # Calculate expected counts
    expected_counts = {}
    for trade in trades:
        expected_counts[trade.profile_id] = expected_counts.get(trade.profile_id, 0) + 1
    
    # Property: trades_by_profile matches expected counts
    assert metrics.trades_by_profile == expected_counts, \
        f"trades_by_profile ({metrics.trades_by_profile}) != expected ({expected_counts})"
    
    # Property: Sum of profile counts equals total trade count
    assert sum(metrics.trades_by_profile.values()) == metrics.trade_count, \
        "Sum of profile counts should equal total trade count"


@settings(max_examples=50)
@given(
    trades=trade_list(min_size=1, max_size=30),
)
def test_property_7_atr_distribution_tracking(
    trades: List[TradeRecord],
):
    """
    Property 7: ATR Distribution Tracking
    
    *For any* set of trades, the atr_distribution in metrics SHALL
    correctly count trades per ATR bucket.
    
    **Validates: Requirements 8.4**
    """
    # Create tracker
    tracker = CoverageGuardrailsTracker(window_hours=24.0)
    
    # Add trades
    for trade in trades:
        tracker.record_trade(trade)
    
    # Get metrics
    metrics = tracker.get_metrics()
    
    # Calculate expected distribution
    expected_distribution = {}
    for trade in trades:
        bucket = get_atr_bucket(trade.atr_ratio_at_entry)
        expected_distribution[bucket] = expected_distribution.get(bucket, 0) + 1
    
    # Property: atr_distribution matches expected
    assert metrics.atr_distribution == expected_distribution, \
        f"atr_distribution ({metrics.atr_distribution}) != expected ({expected_distribution})"
    
    # Property: Sum of distribution counts equals total trade count
    assert sum(metrics.atr_distribution.values()) == metrics.trade_count, \
        "Sum of ATR distribution counts should equal total trade count"


@settings(max_examples=50)
@given(
    # Use a minimum cooldown of 0.1 seconds to ensure meaningful cooldown behavior
    cooldown_seconds=st.floats(min_value=0.1, max_value=100.0, allow_nan=False, allow_infinity=False),
)
def test_property_7_alert_cooldown(
    cooldown_seconds: float,
):
    """
    Property 7: Alert Cooldown
    
    *For any* meaningful cooldown period (>= 0.1s), duplicate alerts SHALL NOT be emitted
    within the cooldown window.
    
    **Validates: Requirements 8.1, 8.2, 8.3**
    """
    # Create tracker with low thresholds to trigger alerts
    tracker = CoverageGuardrailsTracker(
        baseline_trade_count_24h=1,
        trade_count_multiplier=1.5,
        window_hours=24.0,
    )
    tracker.set_alert_cooldown(cooldown_seconds)
    
    # Add enough trades to trigger alert
    now = time.time()
    for i in range(10):
        tracker.record_trade_simple(
            pnl=10.0,
            profile_id="test_profile",
            symbol="BTCUSDT",
            timestamp=now - i,
        )
    
    # First check should emit alert
    alerts1 = tracker.check_alerts()
    trade_count_alerts1 = [a for a in alerts1 if a.alert_type == AlertType.TRADE_COUNT_SPIKE]
    
    # Second check immediately after should NOT emit alert (cooldown)
    alerts2 = tracker.check_alerts()
    trade_count_alerts2 = [a for a in alerts2 if a.alert_type == AlertType.TRADE_COUNT_SPIKE]
    
    # Property: First check emits alert
    assert len(trade_count_alerts1) == 1, "First check should emit alert"
    
    # Property: Second check does not emit alert (within cooldown)
    # Since cooldown >= 0.1s and checks are immediate, second check should be blocked
    assert len(trade_count_alerts2) == 0, \
        "Second check should not emit alert within cooldown"
