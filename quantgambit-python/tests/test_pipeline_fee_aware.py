"""
Property-based tests for fee-aware exit logic in PositionEvaluationStage.

Feature: fee-aware-exits
Tests correctness properties for:
- Property 7: Safety Exit Bypass Invariant
- Property 9: Time Budget Exit with Grace Period
"""

import pytest
import time
from hypothesis import given, strategies as st, settings, assume
from unittest.mock import MagicMock, AsyncMock

from quantgambit.signals.pipeline import PositionEvaluationStage, StageContext
from quantgambit.risk.fee_model import FeeModel, FeeConfig
from quantgambit.deeptrader_core.types import ExitType


# =============================================================================
# Test Strategies (Generators)
# =============================================================================

# Realistic position sizes (0.001 to 100 BTC equivalent)
position_size = st.floats(min_value=0.001, max_value=100.0, allow_nan=False, allow_infinity=False)

# Realistic prices ($100 to $200,000)
price = st.floats(min_value=100.0, max_value=200000.0, allow_nan=False, allow_infinity=False)

# PnL percentage (-10% to +10%)
pnl_pct = st.floats(min_value=-10.0, max_value=10.0, allow_nan=False, allow_infinity=False)

# Hold time in seconds (0 to 3600)
hold_time = st.floats(min_value=0.0, max_value=3600.0, allow_nan=False, allow_infinity=False)

# Side
side = st.sampled_from(["long", "short"])

# Safety exit conditions
safety_condition = st.sampled_from([
    "hard_stop_hit",
    "stop_loss_hit", 
    "data_stale",
    "deeply_underwater",
])


# =============================================================================
# Property 7: Safety Exit Bypass Invariant
# Feature: fee-aware-exits, Property 7: Safety Exit Bypass Invariant
# Validates: Requirements 3.5, 6.1, 6.2, 6.3, 6.5
# =============================================================================

@settings(max_examples=100)
@given(
    size=position_size,
    entry_price=price,
    position_side=side,
    condition=safety_condition,
)
def test_property_7_safety_exit_bypass_invariant(
    size: float,
    entry_price: float,
    position_side: str,
    condition: str,
):
    """
    Property 7: Safety Exit Bypass Invariant
    
    For any safety exit condition (hard_stop_hit, liquidation_proximity, 
    data_stale, deeply_underwater), the exit SHALL proceed regardless of 
    fee calculations. Fee checks SHALL never block a safety exit.
    """
    # Create fee model with high fees to ensure fee check would normally block
    config = FeeConfig(taker_fee_rate=0.01)  # 1% fee - very high
    fee_model = FeeModel(config)
    
    stage = PositionEvaluationStage(
        fee_model=fee_model,
        min_profit_buffer_bps=100.0,  # High buffer to ensure fee check would block
        hard_stop_pct=2.0,
        exit_underwater_threshold_pct=-0.3,
    )
    
    # Build market context based on safety condition
    market_context = {"price": entry_price}
    stop_loss = None
    
    if condition == "hard_stop_hit":
        # PnL below hard stop (-2%)
        if position_side == "long":
            current_price = entry_price * 0.97  # -3% loss
        else:
            current_price = entry_price * 1.03  # -3% loss for short
        pnl = -3.0
    elif condition == "stop_loss_hit":
        # Price at stop loss
        stop_loss = entry_price * 0.99 if position_side == "long" else entry_price * 1.01
        current_price = stop_loss
        pnl = -1.0
    elif condition == "data_stale":
        # Data quality is stale
        market_context["data_quality_status"] = "stale"
        current_price = entry_price
        pnl = 0.0
    elif condition == "deeply_underwater":
        # Deeply underwater (3x threshold)
        if position_side == "long":
            current_price = entry_price * 0.99  # -1% loss (3x -0.3% threshold)
        else:
            current_price = entry_price * 1.01
        pnl = -1.0
    
    market_context["price"] = current_price
    
    ctx = StageContext(
        symbol="BTCUSDT",
        data={"market_context": market_context},
    )
    
    # Call safety exit check
    decision = stage._check_safety_exits(
        side=position_side,
        pnl_pct=pnl,
        current_price=current_price,
        entry_price=entry_price,
        stop_loss=stop_loss,
        market_context=market_context,
        ctx=ctx,
    )
    
    # Safety exit should ALWAYS be allowed regardless of fees
    if decision is not None:
        assert decision.should_exit is True, (
            f"Safety exit ({condition}) should always be allowed, "
            f"but got should_exit={decision.should_exit}"
        )
        assert decision.exit_type == ExitType.SAFETY, (
            f"Safety exit should have exit_type=SAFETY, got {decision.exit_type}"
        )
        # Fee check result should be None (bypassed)
        assert decision.fee_check_result is None, (
            f"Safety exit should bypass fee check (fee_check_result=None), "
            f"but got {decision.fee_check_result}"
        )


@settings(max_examples=100)
@given(
    size=position_size,
    entry_price=price,
    position_side=side,
)
def test_property_7_safety_exit_never_blocked_by_fees(
    size: float,
    entry_price: float,
    position_side: str,
):
    """
    Property 7 (additional): Safety exits are never blocked by fee calculations.
    
    Even with extremely high fees and profit requirements, safety exits proceed.
    """
    # Create fee model with absurdly high fees
    config = FeeConfig(taker_fee_rate=0.10)  # 10% fee - absurd
    fee_model = FeeModel(config)
    
    stage = PositionEvaluationStage(
        fee_model=fee_model,
        min_profit_buffer_bps=1000.0,  # 10% buffer - absurd
        hard_stop_pct=2.0,
    )
    
    # Trigger hard stop condition
    if position_side == "long":
        current_price = entry_price * 0.97  # -3% loss
    else:
        current_price = entry_price * 1.03
    
    ctx = StageContext(
        symbol="BTCUSDT",
        data={"market_context": {"price": current_price}},
    )
    
    decision = stage._check_safety_exits(
        side=position_side,
        pnl_pct=-3.0,
        current_price=current_price,
        entry_price=entry_price,
        stop_loss=None,
        market_context={"price": current_price},
        ctx=ctx,
    )
    
    assert decision is not None, "Hard stop should trigger safety exit"
    assert decision.should_exit is True, "Safety exit should always be allowed"
    assert decision.exit_type == ExitType.SAFETY


# =============================================================================
# Property 9: Time Budget Exit with Grace Period
# Feature: fee-aware-exits, Property 9: Time Budget Exit with Grace Period
# Validates: Requirements 7.1, 7.2, 7.3, 7.5
# =============================================================================

@settings(max_examples=100)
@given(
    size=position_size,
    entry_price=price,
    position_side=side,
    max_hold=st.floats(min_value=60.0, max_value=600.0, allow_nan=False, allow_infinity=False),
    grace_period=st.floats(min_value=10.0, max_value=60.0, allow_nan=False, allow_infinity=False),
)
def test_property_9_time_budget_grace_period_extends_hold(
    size: float,
    entry_price: float,
    position_side: str,
    max_hold: float,
    grace_period: float,
):
    """
    Property 9: Time Budget Exit with Grace Period
    
    If net_pnl_bps < min_required_bps and hold_time < max_hold + grace_period,
    the exit should be delayed (return None to extend hold).
    """
    # Create fee model
    config = FeeConfig.okx_regular()  # 12 bps round-trip
    fee_model = FeeModel(config)
    
    stage = PositionEvaluationStage(
        fee_model=fee_model,
        min_profit_buffer_bps=5.0,  # 17 bps total required
        fee_check_grace_period_sec=grace_period,
    )
    
    # Set current price to be below fee threshold (e.g., +5 bps gross, below 17 bps required)
    if position_side == "long":
        current_price = entry_price * 1.0005  # +5 bps
    else:
        current_price = entry_price * 0.9995  # +5 bps for short
    
    # Hold time is past max_hold but within grace period
    hold_time_sec = max_hold + (grace_period * 0.5)  # Halfway through grace period
    
    ctx = StageContext(
        symbol="BTCUSDT",
        data={"market_context": {"price": current_price, "volatility_regime": "normal"}},
    )
    
    decision = stage._check_time_budget_exits(
        side=position_side,
        pnl_pct=0.05,  # +5 bps
        hold_time_sec=hold_time_sec,
        time_to_work_sec=None,
        max_hold_sec=max_hold,
        mfe_min_bps=None,
        mfe_pct=None,
        market_context={"volatility_regime": "normal"},
        ctx=ctx,
        size=size,
        entry_price=entry_price,
        current_price=current_price,
    )
    
    # Should return None (extend hold) because within grace period
    assert decision is None, (
        f"Within grace period ({hold_time_sec:.1f}s < {max_hold + grace_period:.1f}s), "
        f"should extend hold (return None), but got decision={decision}"
    )


@settings(max_examples=100)
@given(
    size=position_size,
    entry_price=price,
    position_side=side,
    max_hold=st.floats(min_value=60.0, max_value=600.0, allow_nan=False, allow_infinity=False),
    grace_period=st.floats(min_value=10.0, max_value=60.0, allow_nan=False, allow_infinity=False),
)
def test_property_9_time_budget_grace_expired_exits_anyway(
    size: float,
    entry_price: float,
    position_side: str,
    max_hold: float,
    grace_period: float,
):
    """
    Property 9: Time Budget Exit with Grace Period
    
    If net_pnl_bps < min_required_bps and hold_time >= max_hold + grace_period,
    the exit should proceed anyway (stale trade).
    """
    config = FeeConfig.okx_regular()
    fee_model = FeeModel(config)
    
    stage = PositionEvaluationStage(
        fee_model=fee_model,
        min_profit_buffer_bps=5.0,
        fee_check_grace_period_sec=grace_period,
    )
    
    # Set current price to be below fee threshold
    if position_side == "long":
        current_price = entry_price * 1.0005  # +5 bps
    else:
        current_price = entry_price * 0.9995
    
    # Hold time is past grace period
    hold_time_sec = max_hold + grace_period + 10.0  # Past grace period
    
    ctx = StageContext(
        symbol="BTCUSDT",
        data={"market_context": {"price": current_price, "volatility_regime": "normal"}},
    )
    
    decision = stage._check_time_budget_exits(
        side=position_side,
        pnl_pct=0.05,
        hold_time_sec=hold_time_sec,
        time_to_work_sec=None,
        max_hold_sec=max_hold,
        mfe_min_bps=None,
        mfe_pct=None,
        market_context={"volatility_regime": "normal"},
        ctx=ctx,
        size=size,
        entry_price=entry_price,
        current_price=current_price,
    )
    
    # Should exit anyway because grace period expired
    assert decision is not None, (
        f"Past grace period ({hold_time_sec:.1f}s >= {max_hold + grace_period:.1f}s), "
        f"should exit anyway, but got None"
    )
    assert decision.should_exit is True, "Should exit when grace period expired"


@settings(max_examples=100)
@given(
    size=position_size,
    entry_price=price,
    position_side=side,
    max_hold=st.floats(min_value=60.0, max_value=600.0, allow_nan=False, allow_infinity=False),
)
def test_property_9_time_budget_profitable_exits_immediately(
    size: float,
    entry_price: float,
    position_side: str,
    max_hold: float,
):
    """
    Property 9: Time Budget Exit with Grace Period
    
    If net_pnl_bps >= min_required_bps, exit immediately without grace period.
    """
    config = FeeConfig.okx_regular()  # 12 bps round-trip
    fee_model = FeeModel(config)
    
    stage = PositionEvaluationStage(
        fee_model=fee_model,
        min_profit_buffer_bps=5.0,  # 17 bps total required
        fee_check_grace_period_sec=30.0,
    )
    
    # Set current price to be ABOVE fee threshold (e.g., +25 bps gross, above 17 bps required)
    if position_side == "long":
        current_price = entry_price * 1.0025  # +25 bps
    else:
        current_price = entry_price * 0.9975
    
    # Hold time just past max_hold
    hold_time_sec = max_hold + 1.0
    
    ctx = StageContext(
        symbol="BTCUSDT",
        data={"market_context": {"price": current_price, "volatility_regime": "normal"}},
    )
    
    decision = stage._check_time_budget_exits(
        side=position_side,
        pnl_pct=0.25,  # +25 bps
        hold_time_sec=hold_time_sec,
        time_to_work_sec=None,
        max_hold_sec=max_hold,
        mfe_min_bps=None,
        mfe_pct=None,
        market_context={"volatility_regime": "normal"},
        ctx=ctx,
        size=size,
        entry_price=entry_price,
        current_price=current_price,
    )
    
    # Should exit immediately because profitable
    assert decision is not None, "Profitable trade should exit immediately"
    assert decision.should_exit is True, "Profitable trade should exit"


# =============================================================================
# Unit Tests for Fee-Aware Exit Logic
# =============================================================================

class TestFeeAwareInvalidationExits:
    """Unit tests for fee-aware invalidation exit logic."""
    
    def test_invalidation_exit_blocked_below_threshold(self):
        """Invalidation exit should be blocked when below fee threshold."""
        config = FeeConfig.okx_regular()  # 12 bps round-trip
        fee_model = FeeModel(config)
        
        stage = PositionEvaluationStage(
            fee_model=fee_model,
            min_profit_buffer_bps=5.0,  # 17 bps total required
            min_confirmations_for_exit=1,  # Lower for testing
        )
        
        # Position with +10 bps gross (below 17 bps threshold)
        entry_price = 50000.0
        current_price = 50050.0  # +10 bps
        size = 0.2
        
        ctx = StageContext(
            symbol="BTCUSDT",
            data={"market_context": {
                "price": current_price,
                "trend_bias": "short",  # Trigger trend reversal
                "trend_confidence": 0.5,
            }},
        )
        
        decision = stage._check_invalidation_exits(
            side="long",
            pnl_pct=0.10,
            current_price=current_price,
            entry_price=entry_price,
            market_context={
                "trend_bias": "short",
                "trend_confidence": 0.5,
            },
            ctx=ctx,
            size=size,
        )
        
        # Should be blocked
        assert decision is not None
        assert decision.should_exit is False, "Exit should be blocked below fee threshold"
        assert "fee_check_blocked" in decision.reason
    
    def test_invalidation_exit_allowed_above_threshold(self):
        """Invalidation exit should be allowed when above fee threshold."""
        config = FeeConfig.okx_regular()
        fee_model = FeeModel(config)
        
        stage = PositionEvaluationStage(
            fee_model=fee_model,
            min_profit_buffer_bps=5.0,
            min_confirmations_for_exit=1,
        )
        
        # Position with +25 bps gross (above 17 bps threshold)
        entry_price = 50000.0
        current_price = 50125.0  # +25 bps
        size = 0.2
        
        ctx = StageContext(
            symbol="BTCUSDT",
            data={"market_context": {
                "price": current_price,
                "trend_bias": "short",
                "trend_confidence": 0.5,
            }},
        )
        
        decision = stage._check_invalidation_exits(
            side="long",
            pnl_pct=0.25,
            current_price=current_price,
            entry_price=entry_price,
            market_context={
                "trend_bias": "short",
                "trend_confidence": 0.5,
            },
            ctx=ctx,
            size=size,
        )
        
        # Should be allowed
        assert decision is not None
        assert decision.should_exit is True, "Exit should be allowed above fee threshold"
    
    def test_invalidation_exit_no_fee_model_allows_exit(self):
        """Without fee model, invalidation exits should proceed normally."""
        stage = PositionEvaluationStage(
            fee_model=None,  # No fee model
            min_confirmations_for_exit=1,
        )
        
        entry_price = 50000.0
        current_price = 50010.0  # +2 bps (would be blocked with fee model)
        
        ctx = StageContext(
            symbol="BTCUSDT",
            data={"market_context": {"price": current_price}},
        )
        
        decision = stage._check_invalidation_exits(
            side="long",
            pnl_pct=0.02,
            current_price=current_price,
            entry_price=entry_price,
            market_context={
                "trend_bias": "short",
                "trend_confidence": 0.5,
            },
            ctx=ctx,
            size=0.2,
        )
        
        # Should be allowed (no fee model to block)
        assert decision is not None
        assert decision.should_exit is True


class TestFeeAwareExitSignalMetadata:
    """Unit tests for fee_aware metadata in exit signals."""
    
    def test_exit_signal_includes_fee_aware_metadata(self):
        """Exit signal should include fee_aware metadata dict."""
        config = FeeConfig.okx_regular()
        fee_model = FeeModel(config)
        
        stage = PositionEvaluationStage(
            fee_model=fee_model,
            min_profit_buffer_bps=5.0,
        )
        
        from quantgambit.deeptrader_core.types import ExitDecision, ExitType
        
        # Create a mock decision with fee check result
        fee_check = fee_model.check_exit_profitability(
            size=0.2,
            entry_price=50000.0,
            current_price=50100.0,
            side="long",
            min_profit_buffer_bps=5.0,
        )
        
        decision = ExitDecision(
            should_exit=True,
            exit_type=ExitType.INVALIDATION,
            reason="test_reason",
            urgency=0.5,
            confirmations=["test_confirmation"],
            fee_check_result=fee_check,
        )
        
        ctx = StageContext(symbol="BTCUSDT", data={})
        
        signal = stage._build_exit_signal(
            ctx=ctx,
            side="long",
            size=0.2,
            current_price=50100.0,
            entry_price=50000.0,
            pnl_pct=0.2,
            decision=decision,
            hold_time_sec=60.0,
        )
        
        # Check fee_aware metadata exists
        assert "fee_aware" in signal
        fee_aware = signal["fee_aware"]
        
        assert "fee_check_passed" in fee_aware
        assert "fee_check_bypassed" in fee_aware
        assert "gross_pnl_bps" in fee_aware
        assert "net_pnl_bps" in fee_aware
        assert "breakeven_bps" in fee_aware
    
    def test_safety_exit_signal_shows_bypassed(self):
        """Safety exit signal should show fee_check_bypassed=True."""
        config = FeeConfig.okx_regular()
        fee_model = FeeModel(config)
        
        stage = PositionEvaluationStage(
            fee_model=fee_model,
            min_profit_buffer_bps=5.0,
        )
        
        from quantgambit.deeptrader_core.types import ExitDecision, ExitType
        
        decision = ExitDecision(
            should_exit=True,
            exit_type=ExitType.SAFETY,
            reason="hard_stop_hit",
            urgency=1.0,
            confirmations=["hard_stop_hit"],
            fee_check_result=None,  # Safety exits don't have fee check
        )
        
        ctx = StageContext(symbol="BTCUSDT", data={})
        
        signal = stage._build_exit_signal(
            ctx=ctx,
            side="long",
            size=0.2,
            current_price=49000.0,
            entry_price=50000.0,
            pnl_pct=-2.0,
            decision=decision,
            hold_time_sec=60.0,
        )
        
        assert signal["fee_aware"]["fee_check_bypassed"] is True
        assert signal["fee_aware"]["bypass_reason"] == "hard_stop_hit"

    def test_invalidation_exit_signal_marks_fee_check_failed_when_not_profitable(self):
        config = FeeConfig.okx_regular()
        fee_model = FeeModel(config)
        stage = PositionEvaluationStage(
            fee_model=fee_model,
            min_profit_buffer_bps=5.0,
        )
        from quantgambit.deeptrader_core.types import ExitDecision, ExitType

        fee_check = fee_model.check_exit_profitability(
            size=0.2,
            entry_price=50000.0,
            current_price=50030.0,  # ~6 bps gross
            side="long",
            min_profit_buffer_bps=5.0,
        )
        assert fee_check is not None and fee_check.should_allow_exit is False
        decision = ExitDecision(
            should_exit=True,
            exit_type=ExitType.INVALIDATION,
            reason="trend_reversal",
            urgency=0.9,
            confirmations=["trend_reversal_short (conf=0.8)"],
            fee_check_result=fee_check,
            fee_check_bypassed=False,
            fee_bypass_reason=None,
        )
        ctx = StageContext(symbol="BTCUSDT", data={})
        signal = stage._build_exit_signal(
            ctx=ctx,
            side="long",
            size=0.2,
            current_price=50030.0,
            entry_price=50000.0,
            pnl_pct=0.06,
            decision=decision,
            hold_time_sec=80.0,
        )
        assert signal["fee_aware"]["fee_check_passed"] is False
        assert signal["fee_aware"]["fee_check_bypassed"] is False

    def test_invalidation_exit_signal_marks_fee_check_bypassed_when_forced(self):
        config = FeeConfig.okx_regular()
        fee_model = FeeModel(config)
        stage = PositionEvaluationStage(
            fee_model=fee_model,
            min_profit_buffer_bps=5.0,
        )
        from quantgambit.deeptrader_core.types import ExitDecision, ExitType

        fee_check = fee_model.check_exit_profitability(
            size=0.2,
            entry_price=50000.0,
            current_price=50030.0,
            side="long",
            min_profit_buffer_bps=5.0,
        )
        assert fee_check is not None and fee_check.should_allow_exit is False
        decision = ExitDecision(
            should_exit=True,
            exit_type=ExitType.INVALIDATION,
            reason="trend_reversal",
            urgency=1.0,
            confirmations=["trend_reversal_short (conf=0.9)"],
            fee_check_result=fee_check,
            fee_check_bypassed=True,
            fee_bypass_reason="urgency_bypass",
        )
        ctx = StageContext(symbol="BTCUSDT", data={})
        signal = stage._build_exit_signal(
            ctx=ctx,
            side="long",
            size=0.2,
            current_price=50030.0,
            entry_price=50000.0,
            pnl_pct=0.06,
            decision=decision,
            hold_time_sec=120.0,
        )
        assert signal["fee_aware"]["fee_check_passed"] is False
        assert signal["fee_aware"]["fee_check_bypassed"] is True
        assert signal["fee_aware"]["bypass_reason"] == "urgency_bypass"
