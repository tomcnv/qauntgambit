"""
Property-based tests for fee-aware exit logic in PositionGuardWorker.

Feature: fee-aware-exits
Tests correctness properties for:
- Property 10: Position Guard Fee Awareness
"""

import pytest
from hypothesis import given, strategies as st, settings, assume
from unittest.mock import MagicMock, AsyncMock
from dataclasses import dataclass
from typing import Optional

from quantgambit.execution.position_guard_worker import (
    PositionGuardWorker,
    PositionGuardConfig,
    _should_close,
    _is_long,
    _is_short,
)
from quantgambit.risk.fee_model import FeeModel, FeeConfig


# =============================================================================
# Mock PositionSnapshot for testing
# =============================================================================

@dataclass
class MockPositionSnapshot:
    """Mock position snapshot for testing."""
    symbol: str = "BTCUSDT"
    side: str = "long"
    size: float = 0.2
    entry_price: float = 50000.0
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    opened_at: Optional[float] = None
    max_hold_sec: Optional[float] = None
    time_to_work_sec: Optional[float] = None
    mfe_min_bps: Optional[float] = None
    mfe_pct: Optional[float] = None
    reference_price: Optional[float] = None


# =============================================================================
# Test Strategies (Generators)
# =============================================================================

position_size = st.floats(min_value=0.001, max_value=100.0, allow_nan=False, allow_infinity=False)
price = st.floats(min_value=100.0, max_value=200000.0, allow_nan=False, allow_infinity=False)
side = st.sampled_from(["long", "short"])

# Exit reasons that should apply fee check
fee_check_reasons = st.sampled_from([
    "trailing_stop_hit",
    "max_age_exceeded",
    "max_hold_exceeded",
    "time_to_work_fail",
])

# Exit reasons that should bypass fee check (safety exits)
bypass_reasons = st.sampled_from([
    "stop_loss_hit",
    "take_profit_hit",
])


# =============================================================================
# Property 10: Position Guard Fee Awareness
# Feature: fee-aware-exits, Property 10: Position Guard Fee Awareness
# Validates: Requirements 8.1, 8.2, 8.3
# =============================================================================

@settings(max_examples=100)
@given(
    size=position_size,
    entry_price=price,
    position_side=side,
    reason=fee_check_reasons,
)
def test_property_10_guard_applies_fee_check_for_non_safety_exits(
    size: float,
    entry_price: float,
    position_side: str,
    reason: str,
):
    """
    Property 10: Position Guard Fee Awareness
    
    For trailing_stop_hit and max_age_exceeded exits, fee check should be applied.
    If below threshold, exit should be blocked.
    """
    # Create fee model with high fees to ensure fee check would block
    config = FeeConfig(taker_fee_rate=0.01)  # 1% fee
    fee_model = FeeModel(config)
    
    # Create mock exchange client and position manager
    exchange_client = MagicMock()
    position_manager = MagicMock()
    
    worker = PositionGuardWorker(
        exchange_client=exchange_client,
        position_manager=position_manager,
        fee_model=fee_model,
        min_profit_buffer_bps=100.0,  # High buffer
    )
    
    # Create position with small profit (below fee threshold)
    if position_side == "long":
        current_price = entry_price * 1.001  # +10 bps (below 200 bps threshold)
    else:
        current_price = entry_price * 0.999
    
    pos = MockPositionSnapshot(
        symbol="BTCUSDT",
        side=position_side,
        size=size,
        entry_price=entry_price,
    )
    
    # Apply fee check
    fee_check = worker._apply_fee_check(pos, current_price, reason)
    
    # Fee check should be applied (not None)
    assert fee_check is not None, (
        f"Fee check should be applied for reason={reason}, but got None"
    )
    
    # Fee check should block (profit below threshold)
    assert fee_check.should_allow_exit is False, (
        f"Fee check should block exit for reason={reason} when below threshold, "
        f"but got should_allow_exit={fee_check.should_allow_exit}"
    )


@settings(max_examples=100)
@given(
    size=position_size,
    entry_price=price,
    position_side=side,
    reason=bypass_reasons,
)
def test_property_10_guard_bypasses_fee_check_for_safety_exits(
    size: float,
    entry_price: float,
    position_side: str,
    reason: str,
):
    """
    Property 10: Position Guard Fee Awareness
    
    For stop_loss_hit and take_profit_hit exits, fee check should be bypassed.
    These are safety exits that must execute immediately.
    """
    # Create fee model with high fees
    config = FeeConfig(taker_fee_rate=0.01)
    fee_model = FeeModel(config)
    
    exchange_client = MagicMock()
    position_manager = MagicMock()
    
    worker = PositionGuardWorker(
        exchange_client=exchange_client,
        position_manager=position_manager,
        fee_model=fee_model,
        min_profit_buffer_bps=100.0,
    )
    
    # Create position (price doesn't matter for bypass test)
    pos = MockPositionSnapshot(
        symbol="BTCUSDT",
        side=position_side,
        size=size,
        entry_price=entry_price,
    )
    
    # Apply fee check
    fee_check = worker._apply_fee_check(pos, entry_price, reason)
    
    # Fee check should be bypassed (return None)
    assert fee_check is None, (
        f"Fee check should be bypassed for safety exit reason={reason}, "
        f"but got fee_check={fee_check}"
    )


@settings(max_examples=100)
@given(
    size=position_size,
    entry_price=price,
    position_side=side,
    reason=fee_check_reasons,
)
def test_property_10_guard_allows_profitable_exits(
    size: float,
    entry_price: float,
    position_side: str,
    reason: str,
):
    """
    Property 10: Position Guard Fee Awareness
    
    When profit exceeds fee threshold, exit should be allowed.
    """
    config = FeeConfig.okx_regular()  # 12 bps round-trip
    fee_model = FeeModel(config)
    
    exchange_client = MagicMock()
    position_manager = MagicMock()
    
    worker = PositionGuardWorker(
        exchange_client=exchange_client,
        position_manager=position_manager,
        fee_model=fee_model,
        min_profit_buffer_bps=5.0,  # 17 bps total required
    )
    
    # Create position with good profit (above fee threshold)
    if position_side == "long":
        current_price = entry_price * 1.003  # +30 bps (above 17 bps threshold)
    else:
        current_price = entry_price * 0.997
    
    pos = MockPositionSnapshot(
        symbol="BTCUSDT",
        side=position_side,
        size=size,
        entry_price=entry_price,
    )
    
    # Apply fee check
    fee_check = worker._apply_fee_check(pos, current_price, reason)
    
    # Fee check should be applied
    assert fee_check is not None
    
    # Fee check should allow exit
    assert fee_check.should_allow_exit is True, (
        f"Fee check should allow exit when profitable, "
        f"but got should_allow_exit={fee_check.should_allow_exit}, "
        f"gross_pnl_bps={fee_check.gross_pnl_bps}, min_required={fee_check.min_required_bps}"
    )


# =============================================================================
# Unit Tests for Position Guard Fee Awareness
# =============================================================================

class TestPositionGuardFeeAwareness:
    """Unit tests for fee-aware position guard logic."""
    
    def test_no_fee_model_returns_none(self):
        """Without fee model, _apply_fee_check should return None."""
        exchange_client = MagicMock()
        position_manager = MagicMock()
        
        worker = PositionGuardWorker(
            exchange_client=exchange_client,
            position_manager=position_manager,
            fee_model=None,  # No fee model
        )
        
        pos = MockPositionSnapshot()
        result = worker._apply_fee_check(pos, 50000.0, "trailing_stop_hit")
        
        assert result is None
    
    def test_invalid_position_returns_none(self):
        """Invalid position (no entry_price or size) should return None."""
        config = FeeConfig.okx_regular()
        fee_model = FeeModel(config)
        
        exchange_client = MagicMock()
        position_manager = MagicMock()
        
        worker = PositionGuardWorker(
            exchange_client=exchange_client,
            position_manager=position_manager,
            fee_model=fee_model,
        )
        
        # Position with no entry_price
        pos = MockPositionSnapshot(entry_price=None)
        result = worker._apply_fee_check(pos, 50000.0, "trailing_stop_hit")
        assert result is None
        
        # Position with zero size
        pos = MockPositionSnapshot(size=0)
        result = worker._apply_fee_check(pos, 50000.0, "trailing_stop_hit")
        assert result is None
    
    def test_concrete_fee_check_example(self):
        """Test a concrete fee check example."""
        config = FeeConfig.okx_regular()  # 12 bps round-trip
        fee_model = FeeModel(config)
        
        exchange_client = MagicMock()
        position_manager = MagicMock()
        
        worker = PositionGuardWorker(
            exchange_client=exchange_client,
            position_manager=position_manager,
            fee_model=fee_model,
            min_profit_buffer_bps=5.0,  # 17 bps total required
        )
        
        # Position: 0.2 BTC at $50,000 = $10,000 notional
        # Current: $50,050 = +10 bps gross (below 17 bps threshold)
        pos = MockPositionSnapshot(
            symbol="BTCUSDT",
            side="long",
            size=0.2,
            entry_price=50000.0,
        )
        
        result = worker._apply_fee_check(pos, 50050.0, "trailing_stop_hit")
        
        assert result is not None
        assert result.should_allow_exit is False
        assert result.gross_pnl_bps == pytest.approx(10.0, abs=0.5)
        assert result.min_required_bps == pytest.approx(17.0, abs=0.5)
    
    def test_stop_loss_always_bypasses(self):
        """Stop loss should always bypass fee check."""
        config = FeeConfig(taker_fee_rate=0.10)  # 10% fee - absurd
        fee_model = FeeModel(config)
        
        exchange_client = MagicMock()
        position_manager = MagicMock()
        
        worker = PositionGuardWorker(
            exchange_client=exchange_client,
            position_manager=position_manager,
            fee_model=fee_model,
            min_profit_buffer_bps=1000.0,  # Absurd buffer
        )
        
        pos = MockPositionSnapshot(
            symbol="BTCUSDT",
            side="long",
            size=0.2,
            entry_price=50000.0,
        )
        
        # Even with absurd fees, stop_loss should bypass
        result = worker._apply_fee_check(pos, 49000.0, "stop_loss_hit")
        assert result is None  # Bypassed
    
    def test_take_profit_always_bypasses(self):
        """Take profit should always bypass fee check."""
        config = FeeConfig(taker_fee_rate=0.10)
        fee_model = FeeModel(config)
        
        exchange_client = MagicMock()
        position_manager = MagicMock()
        
        worker = PositionGuardWorker(
            exchange_client=exchange_client,
            position_manager=position_manager,
            fee_model=fee_model,
            min_profit_buffer_bps=1000.0,
        )
        
        pos = MockPositionSnapshot(
            symbol="BTCUSDT",
            side="long",
            size=0.2,
            entry_price=50000.0,
        )
        
        # Take profit should bypass
        result = worker._apply_fee_check(pos, 51000.0, "take_profit_hit")
        assert result is None  # Bypassed


class TestShouldCloseFunction:
    """Unit tests for the _should_close function."""
    
    def test_stop_loss_long(self):
        """Stop loss should trigger for long position."""
        pos = MockPositionSnapshot(
            side="long",
            stop_loss=49000.0,
        )
        config = PositionGuardConfig()
        trailing_peaks = {}
        
        # Price at stop loss
        reason = _should_close(pos, 49000.0, config, trailing_peaks)
        assert reason == "stop_loss_hit"
        
        # Price below stop loss
        reason = _should_close(pos, 48000.0, config, trailing_peaks)
        assert reason == "stop_loss_hit"
        
        # Price above stop loss
        reason = _should_close(pos, 50000.0, config, trailing_peaks)
        assert reason is None
    
    def test_take_profit_long(self):
        """Take profit should trigger for long position."""
        pos = MockPositionSnapshot(
            side="long",
            take_profit=51000.0,
        )
        config = PositionGuardConfig()
        trailing_peaks = {}
        
        # Price at take profit
        reason = _should_close(pos, 51000.0, config, trailing_peaks)
        assert reason == "take_profit_hit"
        
        # Price above take profit
        reason = _should_close(pos, 52000.0, config, trailing_peaks)
        assert reason == "take_profit_hit"
        
        # Price below take profit
        reason = _should_close(pos, 50000.0, config, trailing_peaks)
        assert reason is None
    
    def test_max_hold_exceeded(self):
        """Max hold should trigger when exceeded."""
        import time
        
        pos = MockPositionSnapshot(
            side="long",
            max_hold_sec=60.0,
            opened_at=time.time() - 120.0,  # 2 minutes ago
        )
        config = PositionGuardConfig()
        trailing_peaks = {}
        
        reason = _should_close(pos, 50000.0, config, trailing_peaks)
        assert reason == "max_hold_exceeded"
