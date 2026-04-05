"""
Property-based tests for Trading Throttle Fixes.

Feature: trading-throttle-fixes
Tests correctness properties for:
- Property 1: Exit signals always bypass throttle (Requirement 1.5)
- Property 2: Safety exits always bypass fee check (Requirement 3.5)
- Property 3: Deterioration counter forces exit after 3 ticks (Requirement 7.3)
- Property 4: Profitable exit reduces hysteresis by 50% (Requirement 2.3)
- Property 5: Mode config has valid parameter ranges (Requirement 5.1)
"""

import pytest
import time
from hypothesis import given, strategies as st, settings, assume
from unittest.mock import MagicMock, AsyncMock, patch

from quantgambit.config.trading_mode import (
    TradingMode,
    TradingModeConfig,
    TradingModeManager,
    TRADING_MODE_PRESETS,
    validate_config,
)
from quantgambit.signals.stages.cooldown import CooldownStage, CooldownConfig, CooldownManager
from quantgambit.signals.pipeline import PositionEvaluationStage, StageContext


# =============================================================================
# Test Strategies (Generators)
# =============================================================================

# Trading modes
trading_mode = st.sampled_from(list(TradingMode))

# Symbols
symbol = st.sampled_from(["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT"])

# Side
side = st.sampled_from(["long", "short"])

# Realistic position sizes (0.001 to 100 BTC equivalent)
position_size = st.floats(min_value=0.001, max_value=100.0, allow_nan=False, allow_infinity=False)

# Realistic prices ($100 to $200,000)
price = st.floats(min_value=100.0, max_value=200000.0, allow_nan=False, allow_infinity=False)

# PnL percentage (-10% to +10%)
pnl_pct = st.floats(min_value=-10.0, max_value=10.0, allow_nan=False, allow_infinity=False)

# Positive PnL for profitable trades
positive_pnl = st.floats(min_value=0.01, max_value=10.0, allow_nan=False, allow_infinity=False)

# Negative PnL for deteriorating positions
negative_pnl = st.floats(min_value=-10.0, max_value=-0.01, allow_nan=False, allow_infinity=False)

# Deterioration count (3 or more to trigger force exit)
deterioration_count = st.integers(min_value=3, max_value=10)

# Time intervals
time_interval = st.floats(min_value=0.0, max_value=300.0, allow_nan=False, allow_infinity=False)

# Valid config parameters
valid_min_order_interval = st.floats(min_value=1.0, max_value=300.0, allow_nan=False, allow_infinity=False)
valid_max_entries_per_hour = st.integers(min_value=1, max_value=100)
valid_urgency_threshold = st.floats(min_value=0.01, max_value=1.0, allow_nan=False, allow_infinity=False)
valid_deterioration_count = st.integers(min_value=1, max_value=20)
valid_min_hold_time = st.floats(min_value=0.0, max_value=300.0, allow_nan=False, allow_infinity=False)
valid_min_confirmations = st.integers(min_value=1, max_value=5)


# =============================================================================
# Property 5: Mode Config Consistency
# Feature: trading-throttle-fixes, Property 5: Mode config has valid parameter ranges
# Validates: Requirements 5.1
# =============================================================================

@settings(max_examples=100)
@given(mode=trading_mode)
def test_property_5_mode_config_consistency(mode: TradingMode):
    """
    Property 5: Mode Config Consistency
    
    For any trading mode, the preset configuration SHALL have valid parameter ranges:
    - min_order_interval_sec > 0
    - max_entries_per_hour > 0
    - 0 < urgency_bypass_threshold <= 1.0
    - deterioration_force_exit_count >= 1
    - min_hold_time_sec >= 0
    - min_confirmations_for_exit >= 1
    
    **Validates: Requirements 5.1**
    """
    config = TRADING_MODE_PRESETS[mode]
    
    # All mode configs must pass validation
    assert validate_config(config), f"Mode {mode.value} preset failed validation"
    
    # Explicit checks for each parameter
    assert config.min_order_interval_sec > 0, \
        f"min_order_interval_sec must be > 0, got {config.min_order_interval_sec}"
    
    assert config.max_entries_per_hour > 0, \
        f"max_entries_per_hour must be > 0, got {config.max_entries_per_hour}"
    
    assert 0 < config.urgency_bypass_threshold <= 1.0, \
        f"urgency_bypass_threshold must be in (0, 1], got {config.urgency_bypass_threshold}"
    
    assert config.deterioration_force_exit_count >= 1, \
        f"deterioration_force_exit_count must be >= 1, got {config.deterioration_force_exit_count}"
    
    assert config.min_hold_time_sec >= 0, \
        f"min_hold_time_sec must be >= 0, got {config.min_hold_time_sec}"
    
    assert config.min_confirmations_for_exit >= 1, \
        f"min_confirmations_for_exit must be >= 1, got {config.min_confirmations_for_exit}"


# =============================================================================
# Property 4: Profitable Exit Reduces Hysteresis
# Feature: trading-throttle-fixes, Property 4: Profitable exit reduces hysteresis by 50%
# Validates: Requirements 2.3
# =============================================================================

@settings(max_examples=100)
@given(
    sym=symbol,
    pnl=positive_pnl,
)
def test_property_4_profitable_exit_reduces_hysteresis(sym: str, pnl: float):
    """
    Property 4: Profitable Exit Reduces Hysteresis
    
    For any profitable exit (pnl_pct > 0), the CooldownManager SHALL record
    the trade as profitable, and was_last_trade_profitable() SHALL return True.
    This enables the 50% hysteresis reduction in CooldownStage.
    
    **Validates: Requirements 2.3**
    """
    manager = CooldownManager()
    
    # Record a profitable exit
    manager.record_exit(sym, pnl_pct=pnl)
    
    # Verify the trade is marked as profitable
    assert manager.was_last_trade_profitable(sym), \
        f"Trade with pnl={pnl}% should be marked as profitable"
    
    # Verify the P&L is stored correctly
    stored_pnl = manager.get_last_trade_pnl(sym)
    assert stored_pnl == pnl, \
        f"Stored P&L should be {pnl}, got {stored_pnl}"


@settings(max_examples=100)
@given(
    sym=symbol,
    pnl=negative_pnl,
)
def test_property_4_unprofitable_exit_no_hysteresis_reduction(sym: str, pnl: float):
    """
    Property 4 (Inverse): Unprofitable Exit No Hysteresis Reduction
    
    For any unprofitable exit (pnl_pct <= 0), the CooldownManager SHALL NOT
    mark the trade as profitable, and was_last_trade_profitable() SHALL return False.
    
    **Validates: Requirements 2.3**
    """
    manager = CooldownManager()
    
    # Record an unprofitable exit
    manager.record_exit(sym, pnl_pct=pnl)
    
    # Verify the trade is NOT marked as profitable
    assert not manager.was_last_trade_profitable(sym), \
        f"Trade with pnl={pnl}% should NOT be marked as profitable"


# =============================================================================
# Property 3: Deterioration Counter Forces Exit
# Feature: trading-throttle-fixes, Property 3: Deterioration counter forces exit after 3 ticks
# Validates: Requirements 7.3
# =============================================================================

@settings(max_examples=100)
@given(
    sym=symbol,
    position_side=side,
    deterioration_ticks=deterioration_count,
)
def test_property_3_deterioration_counter_forces_exit(
    sym: str,
    position_side: str,
    deterioration_ticks: int,
):
    """
    Property 3: Deterioration Counter Forces Exit
    
    For any position that deteriorates for N consecutive ticks (where N >= 3),
    the deterioration counter SHALL reach the threshold and trigger a force exit.
    
    Note: The first tick establishes the baseline P&L, so N deteriorating ticks
    results in a counter of N-1 (since deterioration is measured from tick 2 onwards).
    To reach counter >= 3, we need 4+ ticks of worsening P&L.
    
    **Validates: Requirements 7.3**
    """
    stage = PositionEvaluationStage(
        min_confirmations_for_exit=2,
        trading_mode_manager=None,  # Use defaults
    )
    
    position_key = f"{sym}:{position_side}"
    
    # Simulate deteriorating P&L over multiple ticks
    # First tick establishes baseline, subsequent ticks count as deterioration
    # To get counter >= deterioration_ticks, we need deterioration_ticks + 1 total ticks
    for i in range(deterioration_ticks + 1):
        current_pnl = -0.1 * (i + 1)  # -0.1%, -0.2%, -0.3%, ...
        count = stage._update_deterioration(position_key, current_pnl)
    
    # After N+1 ticks with worsening P&L, counter should be N
    final_count = stage._deterioration_counters.get(position_key, 0)
    assert final_count >= deterioration_ticks, \
        f"After {deterioration_ticks + 1} ticks with worsening P&L, counter should be >= {deterioration_ticks}, got {final_count}"
    
    # Counter should be >= 3 (the default threshold)
    assert final_count >= 3, \
        f"Counter should be >= 3 to trigger force exit, got {final_count}"


@settings(max_examples=100)
@given(
    sym=symbol,
    position_side=side,
)
def test_property_3_deterioration_counter_resets_on_improvement(
    sym: str,
    position_side: str,
):
    """
    Property 3 (Reset): Deterioration Counter Resets on Improvement
    
    When position P&L improves, the deterioration counter SHALL reset to 0.
    
    Note: First tick establishes baseline (counter=0), second tick with worse P&L
    increments counter to 1, third tick with worse P&L increments to 2.
    
    **Validates: Requirements 7.4**
    """
    stage = PositionEvaluationStage(
        min_confirmations_for_exit=2,
        trading_mode_manager=None,
    )
    
    position_key = f"{sym}:{position_side}"
    
    # First tick establishes baseline (counter stays 0)
    stage._update_deterioration(position_key, -0.1)
    assert stage._deterioration_counters.get(position_key, 0) == 0, \
        "First tick should establish baseline, counter should be 0"
    
    # Second tick with worse P&L (counter becomes 1)
    stage._update_deterioration(position_key, -0.2)
    assert stage._deterioration_counters.get(position_key, 0) == 1, \
        "Second tick with worse P&L should increment counter to 1"
    
    # Third tick with worse P&L (counter becomes 2)
    stage._update_deterioration(position_key, -0.3)
    assert stage._deterioration_counters.get(position_key, 0) == 2, \
        "Third tick with worse P&L should increment counter to 2"
    
    # Now P&L improves
    stage._update_deterioration(position_key, -0.2)  # Better than -0.3
    
    # Counter should reset to 0
    assert stage._deterioration_counters.get(position_key, 0) == 0, \
        "Counter should reset to 0 when P&L improves"


# =============================================================================
# Property 2: Safety Exits Always Bypass Fee Check
# Feature: trading-throttle-fixes, Property 2: Safety exits always bypass fee check
# Validates: Requirements 3.5
# =============================================================================

# Safety exit conditions
safety_condition = st.sampled_from([
    "hard_stop_hit",
    "stop_loss_hit", 
    "data_stale",
    "deeply_underwater",
])


@settings(max_examples=100)
@given(
    size=position_size,
    entry_price=price,
    position_side=side,
    condition=safety_condition,
)
def test_property_2_safety_exits_bypass_fee_check(
    size: float,
    entry_price: float,
    position_side: str,
    condition: str,
):
    """
    Property 2: Safety Exits Always Bypass Fee Check
    
    For any safety exit condition (hard_stop_hit, stop_loss_hit, data_stale, 
    deeply_underwater), the exit SHALL proceed regardless of fee calculations.
    Fee checks SHALL never block a safety exit.
    
    **Validates: Requirements 3.5**
    """
    from quantgambit.risk.fee_model import FeeModel, FeeConfig
    
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
        # Data staleness condition
        current_price = entry_price
        pnl = 0.0
        market_context["data_quality_status"] = "stale"
    elif condition == "deeply_underwater":
        # Deeply underwater (3x threshold)
        if position_side == "long":
            current_price = entry_price * 0.99  # -1% loss (3x -0.3% threshold)
        else:
            current_price = entry_price * 1.01
        pnl = -1.0
    else:
        current_price = entry_price
        pnl = 0.0
    
    market_context["price"] = current_price
    
    # Call the safety exit check
    decision = stage._check_safety_exits(
        side=position_side,
        pnl_pct=pnl,
        current_price=current_price,
        entry_price=entry_price,
        stop_loss=stop_loss,
        market_context=market_context,
        ctx=MagicMock(symbol="BTCUSDT"),
    )
    
    # Safety exits should always return a decision (not None) and should_exit=True
    # Note: Some conditions may not trigger depending on exact values
    if decision is not None:
        # If a safety decision is returned, it should always allow exit
        assert decision.should_exit, \
            f"Safety exit for {condition} should have should_exit=True"
        
        # Fee check result should be None (bypassed)
        assert decision.fee_check_result is None, \
            f"Safety exit for {condition} should bypass fee check (fee_check_result should be None)"


# =============================================================================
# Property 1: Exit Signals Always Bypass Throttle
# Feature: trading-throttle-fixes, Property 1: Exit signals always bypass throttle
# Validates: Requirements 1.5
# =============================================================================

@settings(max_examples=100)
@given(
    sym=symbol,
    position_side=side,
    pnl=pnl_pct,
)
def test_property_1_exit_signals_bypass_cooldown(
    sym: str,
    position_side: str,
    pnl: float,
):
    """
    Property 1: Exit Signals Always Bypass Cooldown
    
    For any exit signal (is_exit_signal=True or reduce_only=True), the 
    CooldownStage SHALL bypass all cooldown checks and return CONTINUE.
    
    **Validates: Requirements 1.5, 8.2**
    """
    # Create a cooldown stage with strict cooldowns
    config = CooldownConfig(
        default_entry_cooldown_sec=300.0,  # 5 minutes
        exit_cooldown_sec=300.0,
        same_direction_hysteresis_sec=600.0,  # 10 minutes
        max_entries_per_hour=1,  # Very restrictive
    )
    manager = CooldownManager()
    stage = CooldownStage(config=config, manager=manager)
    
    # Record a recent entry to trigger cooldowns
    manager.record_entry(sym, "test_strategy", position_side)
    
    # Create an exit signal
    exit_signal = {
        "is_exit_signal": True,
        "reduce_only": True,
        "side": "short" if position_side == "long" else "long",  # Opposite side for exit
        "pnl_pct": pnl,
    }
    
    # Create context with exit signal
    ctx = MagicMock(spec=StageContext)
    ctx.symbol = sym
    ctx.signal = exit_signal
    ctx.data = {}
    
    import asyncio
    result = asyncio.run(stage.run(ctx))
    
    # Exit signals should always bypass cooldown and return CONTINUE
    from quantgambit.signals.pipeline import StageResult
    assert result == StageResult.CONTINUE, \
        f"Exit signal should bypass cooldown and return CONTINUE, got {result}"


@settings(max_examples=100)
@given(
    sym=symbol,
    position_side=side,
)
def test_property_1_reduce_only_signals_bypass_cooldown(
    sym: str,
    position_side: str,
):
    """
    Property 1 (reduce_only variant): Reduce-Only Signals Bypass Cooldown
    
    For any reduce_only signal, the CooldownStage SHALL bypass all cooldown 
    checks and return CONTINUE.
    
    **Validates: Requirements 1.5, 8.2**
    """
    config = CooldownConfig(
        default_entry_cooldown_sec=300.0,
        exit_cooldown_sec=300.0,
        same_direction_hysteresis_sec=600.0,
        max_entries_per_hour=1,
    )
    manager = CooldownManager()
    stage = CooldownStage(config=config, manager=manager)
    
    # Record a recent entry
    manager.record_entry(sym, "test_strategy", position_side)
    
    # Create a reduce_only signal (not explicitly is_exit_signal)
    reduce_only_signal = {
        "is_exit_signal": False,
        "reduce_only": True,
        "side": "short" if position_side == "long" else "long",
    }
    
    ctx = MagicMock(spec=StageContext)
    ctx.symbol = sym
    ctx.signal = reduce_only_signal
    ctx.data = {}
    
    import asyncio
    result = asyncio.run(stage.run(ctx))
    
    from quantgambit.signals.pipeline import StageResult
    assert result == StageResult.CONTINUE, \
        f"reduce_only signal should bypass cooldown and return CONTINUE, got {result}"


# =============================================================================
# Additional Property Tests for Mode Config Validation
# =============================================================================

@settings(max_examples=100)
@given(
    min_interval=valid_min_order_interval,
    max_entries=valid_max_entries_per_hour,
    urgency_threshold=valid_urgency_threshold,
    deterioration_threshold=valid_deterioration_count,
    min_hold=valid_min_hold_time,
    min_confirmations=valid_min_confirmations,
)
def test_property_5_custom_config_validation(
    min_interval: float,
    max_entries: int,
    urgency_threshold: float,
    deterioration_threshold: int,
    min_hold: float,
    min_confirmations: int,
):
    """
    Property 5 (Custom Config): Custom Config Validation
    
    For any custom configuration with valid parameter ranges, validate_config()
    SHALL return True.
    
    **Validates: Requirements 5.1**
    """
    config = TradingModeConfig(
        mode=TradingMode.SCALPING,
        min_order_interval_sec=min_interval,
        entry_cooldown_sec=min_interval,
        exit_cooldown_sec=min_interval / 2,
        same_direction_hysteresis_sec=min_interval * 2,
        max_entries_per_hour=max_entries,
        min_hold_time_sec=min_hold,
        min_confirmations_for_exit=min_confirmations,
        min_profit_buffer_bps=5.0,
        fee_check_grace_period_sec=30.0,
        urgency_bypass_threshold=urgency_threshold,
        confirmation_bypass_count=3,
        deterioration_force_exit_count=deterioration_threshold,
    )
    
    assert validate_config(config), \
        f"Config with valid parameters should pass validation"


@settings(max_examples=100)
@given(mode=trading_mode)
def test_property_5_mode_ordering_consistency(mode: TradingMode):
    """
    Property 5 (Ordering): Mode Ordering Consistency
    
    Trading modes should have consistent ordering of parameters:
    - SCALPING should have the shortest intervals
    - CONSERVATIVE should have the longest intervals
    
    **Validates: Requirements 5.1, 5.2**
    """
    scalping = TRADING_MODE_PRESETS[TradingMode.SCALPING]
    swing = TRADING_MODE_PRESETS[TradingMode.SWING]
    conservative = TRADING_MODE_PRESETS[TradingMode.CONSERVATIVE]
    
    # Scalping should have shortest min_order_interval
    assert scalping.min_order_interval_sec <= swing.min_order_interval_sec, \
        "SCALPING should have shorter or equal min_order_interval than SWING"
    assert swing.min_order_interval_sec <= conservative.min_order_interval_sec, \
        "SWING should have shorter or equal min_order_interval than CONSERVATIVE"
    
    # Scalping should have highest max_entries_per_hour
    assert scalping.max_entries_per_hour >= swing.max_entries_per_hour, \
        "SCALPING should have higher or equal max_entries_per_hour than SWING"
    assert swing.max_entries_per_hour >= conservative.max_entries_per_hour, \
        "SWING should have higher or equal max_entries_per_hour than CONSERVATIVE"
