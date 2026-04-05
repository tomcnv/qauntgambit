"""
Property-based tests for StrategyTrendAlignmentStage.

Feature: trading-loss-fixes
Tests correctness properties for:
- Property 2: Strategy-Trend Alignment

**Validates: Requirements 2.1, 2.2**
"""

import pytest
import asyncio
from hypothesis import given, strategies as st, settings, assume

from quantgambit.signals.stages import (
    StrategyTrendAlignmentStage,
    StrategyTrendAlignmentConfig,
    STRATEGY_TREND_RULES,
)
from quantgambit.signals.pipeline import StageContext, StageResult
from quantgambit.observability.blocked_signal_telemetry import BlockedSignalTelemetry


# =============================================================================
# Test Strategies (Generators)
# =============================================================================

# Valid trends
trend_value = st.sampled_from(["up", "down", "flat"])

# Valid signal sides
signal_side = st.sampled_from(["long", "short"])

# Strategy IDs
strategy_id = st.sampled_from(["mean_reversion_fade", "trend_following"])

# Symbols
symbol = st.sampled_from(["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT"])


# =============================================================================
# Property 2: Strategy-Trend Alignment
# Feature: trading-loss-fixes, Property 2: Strategy-Trend Alignment
# Validates: Requirements 2.1, 2.2
# =============================================================================

@settings(max_examples=100)
@given(
    trend=trend_value,
    side=signal_side,
    sym=symbol,
)
def test_property_2_mean_reversion_trend_alignment(
    trend: str,
    side: str,
    sym: str,
):
    """
    Property 2: Strategy-Trend Alignment (Mean Reversion)
    
    *For any* mean reversion signal:
    - IF the market trend is "up" AND the signal is "short", THEN reject
    - IF the market trend is "down" AND the signal is "long", THEN reject
    - Otherwise, allow through
    
    **Validates: Requirements 2.1, 2.2**
    """
    strategy = "mean_reversion_fade"
    
    # Create stage
    stage = StrategyTrendAlignmentStage()
    
    # Create context with signal and trend
    ctx = StageContext(
        symbol=sym,
        data={
            "market_context": {"trend": trend},
        },
        signal={
            "strategy_id": strategy,
            "side": side,
        },
    )
    
    # Run the stage
    result = asyncio.run(stage.run(ctx))
    
    # Property: mean reversion shorts in uptrends are rejected (Requirement 2.1)
    if trend == "up" and side == "short":
        assert result == StageResult.REJECT, \
            f"Mean reversion SHORT in UP trend should be REJECTED"
        assert ctx.rejection_reason == "strategy_trend_mismatch", \
            f"Rejection reason should be 'strategy_trend_mismatch', got {ctx.rejection_reason}"
        assert ctx.rejection_detail["mismatch_reason"] == "mean_reversion_short_in_uptrend", \
            f"Mismatch reason should be 'mean_reversion_short_in_uptrend'"
    
    # Property: mean reversion longs in downtrends are rejected (Requirement 2.2)
    elif trend == "down" and side == "long":
        assert result == StageResult.REJECT, \
            f"Mean reversion LONG in DOWN trend should be REJECTED"
        assert ctx.rejection_reason == "strategy_trend_mismatch", \
            f"Rejection reason should be 'strategy_trend_mismatch', got {ctx.rejection_reason}"
        assert ctx.rejection_detail["mismatch_reason"] == "mean_reversion_long_in_downtrend", \
            f"Mismatch reason should be 'mean_reversion_long_in_downtrend'"
    
    # Property: all other combinations should pass
    else:
        assert result == StageResult.CONTINUE, \
            f"Mean reversion {side.upper()} in {trend.upper()} trend should CONTINUE"
        assert ctx.rejection_reason is None, \
            f"Rejection reason should be None for passing signals"


@settings(max_examples=100)
@given(
    trend=trend_value,
    side=signal_side,
    sym=symbol,
)
def test_property_2_trend_following_alignment(
    trend: str,
    side: str,
    sym: str,
):
    """
    Property 2: Strategy-Trend Alignment (Trend Following)
    
    *For any* trend following signal:
    - IF the market trend is "flat", THEN reject ALL signals
    - Otherwise, allow through
    
    **Validates: Requirements 2.3**
    """
    strategy = "trend_following"
    
    # Create stage
    stage = StrategyTrendAlignmentStage()
    
    # Create context with signal and trend
    ctx = StageContext(
        symbol=sym,
        data={
            "market_context": {"trend": trend},
        },
        signal={
            "strategy_id": strategy,
            "side": side,
        },
    )
    
    # Run the stage
    result = asyncio.run(stage.run(ctx))
    
    # Property: trend following in flat markets is rejected (Requirement 2.3)
    if trend == "flat":
        assert result == StageResult.REJECT, \
            f"Trend following {side.upper()} in FLAT market should be REJECTED"
        assert ctx.rejection_reason == "strategy_trend_mismatch", \
            f"Rejection reason should be 'strategy_trend_mismatch', got {ctx.rejection_reason}"
        assert ctx.rejection_detail["mismatch_reason"] == "trend_following_in_flat_market", \
            f"Mismatch reason should be 'trend_following_in_flat_market'"
    
    # Property: trend following in trending markets should pass
    else:
        assert result == StageResult.CONTINUE, \
            f"Trend following {side.upper()} in {trend.upper()} trend should CONTINUE"
        assert ctx.rejection_reason is None, \
            f"Rejection reason should be None for passing signals"


@settings(max_examples=100)
@given(
    trend=trend_value,
    side=signal_side,
    strat=strategy_id,
    sym=symbol,
)
def test_property_2_telemetry_emission(
    trend: str,
    side: str,
    strat: str,
    sym: str,
):
    """
    Property 2 (Telemetry): Blocked signals emit telemetry with strategy, side, and trend
    
    *For any* signal rejected by the strategy-trend alignment stage, telemetry SHALL
    be emitted with strategy_id, signal_side, and trend in the metrics.
    
    **Validates: Requirements 2.4**
    """
    # Create telemetry instance
    telemetry = BlockedSignalTelemetry()
    
    # Create stage with telemetry
    stage = StrategyTrendAlignmentStage(telemetry=telemetry)
    
    # Get initial count
    initial_count = telemetry.get_count_for_gate("strategy_trend_mismatch")
    
    # Create context with signal and trend
    ctx = StageContext(
        symbol=sym,
        data={
            "market_context": {"trend": trend},
        },
        signal={
            "strategy_id": strat,
            "side": side,
        },
    )
    
    # Run the stage
    result = asyncio.run(stage.run(ctx))
    
    # Get final count
    final_count = telemetry.get_count_for_gate("strategy_trend_mismatch")
    
    # Determine if this should be rejected
    should_reject = False
    if strat == "mean_reversion_fade":
        if (trend == "up" and side == "short") or (trend == "down" and side == "long"):
            should_reject = True
    elif strat == "trend_following":
        if trend == "flat":
            should_reject = True
    
    # Property: rejected signals increment telemetry count
    if should_reject:
        assert final_count == initial_count + 1, \
            f"Telemetry count should increment by 1 for rejected signal"
    else:
        assert final_count == initial_count, \
            f"Telemetry count should not change for passing signal"


@settings(max_examples=100)
@given(
    ema_fast=st.floats(min_value=100.0, max_value=200.0, allow_nan=False, allow_infinity=False),
    ema_slow=st.floats(min_value=100.0, max_value=200.0, allow_nan=False, allow_infinity=False),
    side=signal_side,
    sym=symbol,
)
def test_property_2_ema_trend_classification(
    ema_fast: float,
    ema_slow: float,
    side: str,
    sym: str,
):
    """
    Property 2 (EMA Classification): Trend is classified from EMA relationships
    
    *For any* EMA values:
    - IF fast EMA > slow EMA by threshold, trend is "up"
    - IF fast EMA < slow EMA by threshold, trend is "down"
    - Otherwise, trend is "flat"
    
    **Validates: Requirements 2.5**
    """
    # Skip if EMAs are too close (ambiguous)
    assume(abs(ema_fast - ema_slow) > 0.001 or ema_fast == ema_slow)
    
    strategy = "mean_reversion_fade"
    threshold = 0.001  # Default threshold
    
    # Create stage
    stage = StrategyTrendAlignmentStage()
    
    # Create context with EMA features (no explicit trend)
    ctx = StageContext(
        symbol=sym,
        data={
            "features": {
                "ema_fast_15m": ema_fast,
                "ema_slow_15m": ema_slow,
            },
            "market_context": {},  # No explicit trend
        },
        signal={
            "strategy_id": strategy,
            "side": side,
        },
    )
    
    # Calculate expected trend
    if ema_slow == 0:
        expected_trend = "flat"
    else:
        diff_pct = (ema_fast - ema_slow) / ema_slow
        if diff_pct > threshold:
            expected_trend = "up"
        elif diff_pct < -threshold:
            expected_trend = "down"
        else:
            expected_trend = "flat"
    
    # Run the stage
    result = asyncio.run(stage.run(ctx))
    
    # Verify the trend was classified correctly by checking rejection behavior
    if expected_trend == "up" and side == "short":
        assert result == StageResult.REJECT, \
            f"Mean reversion SHORT should be REJECTED when EMA indicates UP trend"
    elif expected_trend == "down" and side == "long":
        assert result == StageResult.REJECT, \
            f"Mean reversion LONG should be REJECTED when EMA indicates DOWN trend"
    else:
        assert result == StageResult.CONTINUE, \
            f"Signal should CONTINUE when trend is {expected_trend} and side is {side}"


@settings(max_examples=100)
@given(sym=symbol, side=signal_side)
def test_property_2_no_signal_passes_through(sym: str, side: str):
    """
    Property 2 (Edge Case): Missing signal or strategy passes through
    
    *For any* context without a signal or strategy_id, the stage SHALL
    allow the signal to pass through (CONTINUE).
    
    **Validates: Requirements 2.1, 2.2**
    """
    # Create stage
    stage = StrategyTrendAlignmentStage()
    
    # Test 1: No signal at all
    ctx1 = StageContext(
        symbol=sym,
        data={
            "market_context": {"trend": "up"},
        },
        signal=None,
    )
    result1 = asyncio.run(stage.run(ctx1))
    assert result1 == StageResult.CONTINUE, \
        "Missing signal should CONTINUE"
    
    # Test 2: Signal without strategy_id
    ctx2 = StageContext(
        symbol=sym,
        data={
            "market_context": {"trend": "up"},
        },
        signal={
            "side": side,
        },
    )
    result2 = asyncio.run(stage.run(ctx2))
    assert result2 == StageResult.CONTINUE, \
        "Signal without strategy_id should CONTINUE"
    
    # Test 3: Signal without side
    ctx3 = StageContext(
        symbol=sym,
        data={
            "market_context": {"trend": "up"},
        },
        signal={
            "strategy_id": "mean_reversion_fade",
        },
    )
    result3 = asyncio.run(stage.run(ctx3))
    assert result3 == StageResult.CONTINUE, \
        "Signal without side should CONTINUE"


@settings(max_examples=100)
@given(
    trend=trend_value,
    side=signal_side,
    sym=symbol,
)
def test_property_2_rejection_detail_completeness(
    trend: str,
    side: str,
    sym: str,
):
    """
    Property 2 (Rejection Detail): Rejected signals have complete rejection details
    
    *For any* rejected signal, the rejection_detail SHALL contain:
    - strategy_id
    - signal_side
    - trend
    - mismatch_reason
    
    **Validates: Requirements 2.4**
    """
    strategy = "mean_reversion_fade"
    
    # Only test cases that should be rejected
    assume(
        (trend == "up" and side == "short") or
        (trend == "down" and side == "long")
    )
    
    # Create stage
    stage = StrategyTrendAlignmentStage()
    
    # Create context
    ctx = StageContext(
        symbol=sym,
        data={
            "market_context": {"trend": trend},
        },
        signal={
            "strategy_id": strategy,
            "side": side,
        },
    )
    
    # Run the stage
    result = asyncio.run(stage.run(ctx))
    
    # Verify rejection
    assert result == StageResult.REJECT
    assert ctx.rejection_detail is not None, "Rejection detail should be set"
    
    # Verify all required fields are present
    assert "strategy_id" in ctx.rejection_detail, "strategy_id should be in rejection_detail"
    assert "signal_side" in ctx.rejection_detail, "signal_side should be in rejection_detail"
    assert "trend" in ctx.rejection_detail, "trend should be in rejection_detail"
    assert "mismatch_reason" in ctx.rejection_detail, "mismatch_reason should be in rejection_detail"
    
    # Verify values are correct
    assert ctx.rejection_detail["strategy_id"] == strategy
    assert ctx.rejection_detail["signal_side"] == side
    assert ctx.rejection_detail["trend"] == trend
