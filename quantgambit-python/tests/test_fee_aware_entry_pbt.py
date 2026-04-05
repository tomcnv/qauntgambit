"""
Property-based tests for FeeAwareEntryStage.

Feature: trading-loss-fixes
Tests correctness properties for:
- Property 3: Fee Trap Prevention

**Validates: Requirements 4.1, 4.2, 4.3, 4.4**

Note: FeeAwareEntryStage is deprecated in favor of EVGate. These tests
validate legacy behavior and suppress deprecation warnings.
"""

import pytest
import asyncio
import warnings
from hypothesis import given, strategies as st, settings, assume

from quantgambit.signals.stages.fee_aware_entry import FeeAwareEntryStage, FeeAwareEntryConfig
from quantgambit.signals.pipeline import StageContext, StageResult
from quantgambit.observability.blocked_signal_telemetry import BlockedSignalTelemetry


# Suppress deprecation warnings for these tests (testing legacy behavior)
pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")


# =============================================================================
# Test Strategies (Generators)
# =============================================================================

# Position size in USD (realistic range)
position_size_usd = st.floats(min_value=10.0, max_value=100000.0, allow_nan=False, allow_infinity=False)

# Expected edge percentage (0-10% is realistic for scalping)
expected_edge_pct = st.floats(min_value=0.0, max_value=10.0, allow_nan=False, allow_infinity=False)

# Fee rate in basis points (1-20 bps is realistic)
fee_rate_bps = st.floats(min_value=1.0, max_value=20.0, allow_nan=False, allow_infinity=False)

# Slippage in basis points (0-10 bps is realistic)
slippage_bps = st.floats(min_value=0.0, max_value=10.0, allow_nan=False, allow_infinity=False)

# Edge multiplier (1-5x is realistic)
edge_multiplier = st.floats(min_value=1.0, max_value=5.0, allow_nan=False, allow_infinity=False)

# Symbols
symbol = st.sampled_from(["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT"])

# Signal sides (entry signals only)
signal_side = st.sampled_from(["long", "short"])


# =============================================================================
# Property 3: Fee Trap Prevention
# Feature: trading-loss-fixes, Property 3: Fee Trap Prevention
# Validates: Requirements 4.1, 4.2, 4.3, 4.4
# =============================================================================

@settings(max_examples=100)
@given(
    size_usd=position_size_usd,
    edge_pct=expected_edge_pct,
    fee_bps=fee_rate_bps,
    slip_bps=slippage_bps,
    multiplier=edge_multiplier,
    sym=symbol,
    side=signal_side,
)
def test_property_3_fee_trap_prevention(
    size_usd: float,
    edge_pct: float,
    fee_bps: float,
    slip_bps: float,
    multiplier: float,
    sym: str,
    side: str,
):
    """
    Property 3: Fee Trap Prevention
    
    *For any* signal where the expected profit in dollars is less than 
    min_edge_multiplier × round-trip fees, the FeeAwareEntryStage SHALL 
    reject the signal and emit telemetry with the edge amount, fee amount, 
    and ratio.
    
    **Validates: Requirements 4.1, 4.2, 4.3, 4.4**
    """
    # Create stage with the given configuration
    config = FeeAwareEntryConfig(
        fee_rate_bps=fee_bps,
        slippage_bps=slip_bps,
        min_edge_multiplier=multiplier,
    )
    stage = FeeAwareEntryStage(config=config)
    
    # Calculate expected values
    round_trip_fee_bps = fee_bps * 2 + slip_bps
    round_trip_fee_usd = size_usd * (round_trip_fee_bps / 10000)
    expected_profit_usd = size_usd * (edge_pct / 100)
    min_required_profit = round_trip_fee_usd * multiplier
    
    # Create context with signal
    ctx = StageContext(
        symbol=sym,
        data={
            "market_context": {"price": 100.0},
        },
        signal={
            "side": side,
            "size_usd": size_usd,
            "expected_edge_pct": edge_pct,
        },
    )
    
    # Run the stage
    result = asyncio.run(stage.run(ctx))
    
    # Property: signals with insufficient edge are rejected
    if expected_profit_usd < min_required_profit:
        assert result == StageResult.REJECT, \
            f"Signal with profit ${expected_profit_usd:.4f} < min ${min_required_profit:.4f} should be REJECTED"
        assert ctx.rejection_reason == "fee_trap", \
            f"Rejection reason should be 'fee_trap', got {ctx.rejection_reason}"
        assert ctx.rejection_stage == "fee_aware_entry", \
            f"Rejection stage should be 'fee_aware_entry', got {ctx.rejection_stage}"
        assert ctx.rejection_detail is not None, \
            "Rejection detail should be set"
    else:
        assert result == StageResult.CONTINUE, \
            f"Signal with profit ${expected_profit_usd:.4f} >= min ${min_required_profit:.4f} should CONTINUE"
        assert ctx.rejection_reason is None, \
            f"Rejection reason should be None for passing signals, got {ctx.rejection_reason}"


@settings(max_examples=100)
@given(
    size_usd=position_size_usd,
    edge_pct=expected_edge_pct,
    sym=symbol,
    side=signal_side,
)
def test_property_3_default_config_fee_trap(
    size_usd: float,
    edge_pct: float,
    sym: str,
    side: str,
):
    """
    Property 3 (Default Config): Fee trap with default Bybit fees
    
    *For any* signal, using default config (5.5 bps fee, 2 bps slippage, 2x multiplier),
    the stage SHALL reject signals where expected profit < 2 × round-trip fees.
    
    **Validates: Requirements 4.3, 4.5**
    """
    # Create stage with default config
    stage = FeeAwareEntryStage()
    
    # Default values
    fee_bps = 5.5
    slip_bps = 2.0
    multiplier = 2.0
    
    # Calculate expected values
    round_trip_fee_bps = fee_bps * 2 + slip_bps  # 13 bps
    round_trip_fee_usd = size_usd * (round_trip_fee_bps / 10000)
    expected_profit_usd = size_usd * (edge_pct / 100)
    min_required_profit = round_trip_fee_usd * multiplier
    
    # Create context with signal
    ctx = StageContext(
        symbol=sym,
        data={
            "market_context": {"price": 100.0},
        },
        signal={
            "side": side,
            "size_usd": size_usd,
            "expected_edge_pct": edge_pct,
        },
    )
    
    # Run the stage
    result = asyncio.run(stage.run(ctx))
    
    # Property: signals with insufficient edge are rejected
    if expected_profit_usd < min_required_profit:
        assert result == StageResult.REJECT, \
            f"Signal with profit ${expected_profit_usd:.4f} < min ${min_required_profit:.4f} should be REJECTED"
    else:
        assert result == StageResult.CONTINUE, \
            f"Signal with profit ${expected_profit_usd:.4f} >= min ${min_required_profit:.4f} should CONTINUE"


@settings(max_examples=100)
@given(
    size_usd=position_size_usd,
    edge_pct=expected_edge_pct,
    fee_bps=fee_rate_bps,
    slip_bps=slippage_bps,
    multiplier=edge_multiplier,
    sym=symbol,
    side=signal_side,
)
def test_property_3_telemetry_emission(
    size_usd: float,
    edge_pct: float,
    fee_bps: float,
    slip_bps: float,
    multiplier: float,
    sym: str,
    side: str,
):
    """
    Property 3 (Telemetry): Blocked signals emit telemetry with metrics
    
    *For any* signal rejected by the fee trap filter, telemetry SHALL be emitted
    with expected_profit_usd, round_trip_fee_usd, and ratio.
    
    **Validates: Requirements 4.4**
    """
    # Create telemetry instance
    telemetry = BlockedSignalTelemetry()
    
    # Create stage with telemetry
    config = FeeAwareEntryConfig(
        fee_rate_bps=fee_bps,
        slippage_bps=slip_bps,
        min_edge_multiplier=multiplier,
    )
    stage = FeeAwareEntryStage(config=config, telemetry=telemetry)
    
    # Calculate expected values
    round_trip_fee_bps = fee_bps * 2 + slip_bps
    round_trip_fee_usd = size_usd * (round_trip_fee_bps / 10000)
    expected_profit_usd = size_usd * (edge_pct / 100)
    min_required_profit = round_trip_fee_usd * multiplier
    
    # Get initial count
    initial_count = telemetry.get_count_for_gate("fee_trap")
    
    # Create context with signal
    ctx = StageContext(
        symbol=sym,
        data={
            "market_context": {"price": 100.0},
        },
        signal={
            "side": side,
            "size_usd": size_usd,
            "expected_edge_pct": edge_pct,
        },
    )
    
    # Run the stage
    result = asyncio.run(stage.run(ctx))
    
    # Get final count
    final_count = telemetry.get_count_for_gate("fee_trap")
    
    # Property: rejected signals increment telemetry count
    if expected_profit_usd < min_required_profit:
        assert final_count == initial_count + 1, \
            f"Telemetry count should increment by 1 for rejected signal"
    else:
        assert final_count == initial_count, \
            f"Telemetry count should not change for passing signal"


@settings(max_examples=100)
@given(
    size_usd=position_size_usd,
    edge_pct=expected_edge_pct,
    fee_bps=fee_rate_bps,
    slip_bps=slippage_bps,
    multiplier=edge_multiplier,
    sym=symbol,
    side=signal_side,
)
def test_property_3_rejection_detail_completeness(
    size_usd: float,
    edge_pct: float,
    fee_bps: float,
    slip_bps: float,
    multiplier: float,
    sym: str,
    side: str,
):
    """
    Property 3 (Detail): Rejection detail contains all required fields
    
    *For any* rejected signal, the rejection_detail SHALL contain:
    expected_profit_usd, round_trip_fee_usd, min_required_profit, and ratio.
    
    **Validates: Requirements 4.4, 4.7**
    """
    # Create stage
    config = FeeAwareEntryConfig(
        fee_rate_bps=fee_bps,
        slippage_bps=slip_bps,
        min_edge_multiplier=multiplier,
    )
    stage = FeeAwareEntryStage(config=config)
    
    # Calculate expected values
    round_trip_fee_bps = fee_bps * 2 + slip_bps
    round_trip_fee_usd = size_usd * (round_trip_fee_bps / 10000)
    expected_profit_usd = size_usd * (edge_pct / 100)
    min_required_profit = round_trip_fee_usd * multiplier
    
    # Only test rejection cases
    assume(expected_profit_usd < min_required_profit)
    
    # Create context with signal
    ctx = StageContext(
        symbol=sym,
        data={
            "market_context": {"price": 100.0},
        },
        signal={
            "side": side,
            "size_usd": size_usd,
            "expected_edge_pct": edge_pct,
        },
    )
    
    # Run the stage
    result = asyncio.run(stage.run(ctx))
    
    # Property: rejection detail contains all required fields
    assert result == StageResult.REJECT
    assert ctx.rejection_detail is not None
    
    required_fields = [
        "expected_profit_usd",
        "round_trip_fee_usd",
        "min_required_profit",
        "ratio",
    ]
    for field in required_fields:
        assert field in ctx.rejection_detail, \
            f"Rejection detail should contain '{field}'"


@settings(max_examples=100)
@given(sym=symbol)
def test_property_3_exit_signals_pass_through(sym: str):
    """
    Property 3 (Exit Bypass): Exit signals are not filtered
    
    *For any* exit signal (close_long, close_short), the stage SHALL
    allow it to pass through without fee checking.
    
    **Validates: Requirements 4.1 (entry filtering only)**
    """
    # Create stage with default config
    stage = FeeAwareEntryStage()
    
    for exit_side in ["close_long", "close_short", "close"]:
        # Create context with exit signal
        ctx = StageContext(
            symbol=sym,
            data={
                "market_context": {"price": 100.0},
            },
            signal={
                "side": exit_side,
                "size_usd": 1000.0,
                "expected_edge_pct": 0.0,  # Zero edge would normally be rejected
            },
        )
        
        # Run the stage
        result = asyncio.run(stage.run(ctx))
        
        # Property: exit signals always pass through
        assert result == StageResult.CONTINUE, \
            f"Exit signal '{exit_side}' should CONTINUE regardless of edge"


@settings(max_examples=100)
@given(sym=symbol)
def test_property_3_no_signal_pass_through(sym: str):
    """
    Property 3 (No Signal): Contexts without signals pass through
    
    *For any* context without a signal, the stage SHALL allow it to pass.
    
    **Validates: Requirements 4.1**
    """
    # Create stage with default config
    stage = FeeAwareEntryStage()
    
    # Create context without signal
    ctx = StageContext(
        symbol=sym,
        data={
            "market_context": {"price": 100.0},
        },
        signal=None,
    )
    
    # Run the stage
    result = asyncio.run(stage.run(ctx))
    
    # Property: no signal means pass through
    assert result == StageResult.CONTINUE, \
        "Context without signal should CONTINUE"


@settings(max_examples=100)
@given(
    size_usd=position_size_usd,
    fee_bps=fee_rate_bps,
    slip_bps=slippage_bps,
    multiplier=edge_multiplier,
    sym=symbol,
    side=signal_side,
)
def test_property_3_zero_edge_rejected(
    size_usd: float,
    fee_bps: float,
    slip_bps: float,
    multiplier: float,
    sym: str,
    side: str,
):
    """
    Property 3 (Zero Edge): Signals with zero expected edge are rejected
    
    *For any* signal with zero expected edge, the stage SHALL reject it
    since 0 < any positive fee amount.
    
    **Validates: Requirements 4.3**
    """
    # Create stage
    config = FeeAwareEntryConfig(
        fee_rate_bps=fee_bps,
        slippage_bps=slip_bps,
        min_edge_multiplier=multiplier,
    )
    stage = FeeAwareEntryStage(config=config)
    
    # Create context with zero edge signal
    ctx = StageContext(
        symbol=sym,
        data={
            "market_context": {"price": 100.0},
        },
        signal={
            "side": side,
            "size_usd": size_usd,
            "expected_edge_pct": 0.0,
        },
    )
    
    # Run the stage
    result = asyncio.run(stage.run(ctx))
    
    # Property: zero edge is always rejected (since fees > 0)
    assert result == StageResult.REJECT, \
        "Signal with zero edge should be REJECTED"
    assert ctx.rejection_reason == "fee_trap", \
        "Rejection reason should be 'fee_trap'"
