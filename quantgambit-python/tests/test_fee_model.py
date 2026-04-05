"""
Property-based tests for FeeModel.

Feature: fee-aware-exits
Tests correctness properties for fee calculations, breakeven thresholds,
and exit profitability checks.
"""

import pytest
from hypothesis import given, strategies as st, settings, assume

from quantgambit.risk.fee_model import (
    FeeConfig,
    FeeModel,
    BreakevenResult,
    FeeAwareExitCheck,
    calculate_breakeven_bps,
)


# =============================================================================
# Test Strategies (Generators)
# =============================================================================

# Realistic position sizes (0.001 to 100 BTC equivalent)
position_size = st.floats(min_value=0.001, max_value=100.0, allow_nan=False, allow_infinity=False)

# Realistic prices ($100 to $200,000)
price = st.floats(min_value=100.0, max_value=200000.0, allow_nan=False, allow_infinity=False)

# Fee rates (0 to 1% - realistic range)
fee_rate = st.floats(min_value=0.0, max_value=0.01, allow_nan=False, allow_infinity=False)

# Profit buffer (0 to 100 bps)
profit_buffer = st.floats(min_value=-10.0, max_value=100.0, allow_nan=False, allow_infinity=False)

# Side
side = st.sampled_from(["long", "short"])

# Is maker
is_maker = st.booleans()


# =============================================================================
# Property 1: Fee Calculation Correctness
# Feature: fee-aware-exits, Property 1: Fee Calculation Correctness
# Validates: Requirements 1.1, 1.2
# =============================================================================

@settings(max_examples=100)
@given(
    size=position_size,
    entry_price=price,
    taker_rate=fee_rate,
    maker_rate=fee_rate,
    rebate_rate=st.floats(min_value=0.0, max_value=0.001, allow_nan=False, allow_infinity=False),
    entry_is_maker=is_maker,
)
def test_property_1_fee_calculation_correctness(
    size: float,
    entry_price: float,
    taker_rate: float,
    maker_rate: float,
    rebate_rate: float,
    entry_is_maker: bool,
):
    """
    Property 1: Fee Calculation Correctness
    
    For any valid position size > 0, price > 0, and fee rate >= 0,
    the calculated fee SHALL equal size × price × fee_rate (for taker)
    or size × price × (maker_rate - rebate_rate) (for maker).
    """
    config = FeeConfig(
        taker_fee_rate=taker_rate,
        maker_fee_rate=maker_rate,
        maker_rebate_rate=rebate_rate,
    )
    model = FeeModel(config)
    
    notional = size * entry_price
    calculated_fee = model.calculate_entry_fee(size, entry_price, entry_is_maker)
    
    if entry_is_maker:
        effective_rate = max(0.0, maker_rate - rebate_rate)
        expected_fee = notional * effective_rate
    else:
        expected_fee = notional * taker_rate
    
    # Allow small floating point tolerance
    assert abs(calculated_fee - expected_fee) < 1e-6, (
        f"Fee mismatch: calculated={calculated_fee}, expected={expected_fee}"
    )


# =============================================================================
# Property 2: Round-Trip Fee Additivity
# Feature: fee-aware-exits, Property 2: Round-Trip Fee Additivity
# Validates: Requirements 1.3
# =============================================================================

@settings(max_examples=100)
@given(
    size=position_size,
    entry_price=price,
    exit_price=price,
    entry_is_maker=is_maker,
    exit_is_maker=is_maker,
)
def test_property_2_round_trip_fee_additivity(
    size: float,
    entry_price: float,
    exit_price: float,
    entry_is_maker: bool,
    exit_is_maker: bool,
):
    """
    Property 2: Round-Trip Fee Additivity
    
    For any valid position parameters, the round-trip fee SHALL equal
    the sum of entry fee and exit fee: round_trip_fee == entry_fee + exit_fee.
    """
    model = FeeModel()
    
    entry_fee = model.calculate_entry_fee(size, entry_price, entry_is_maker)
    exit_fee = model.calculate_exit_fee(size, exit_price, exit_is_maker)
    round_trip_fee = model.calculate_round_trip_fee(
        size, entry_price, exit_price, entry_is_maker, exit_is_maker
    )
    
    expected_total = entry_fee + exit_fee
    
    assert abs(round_trip_fee - expected_total) < 1e-6, (
        f"Round-trip fee mismatch: {round_trip_fee} != {entry_fee} + {exit_fee}"
    )


# =============================================================================
# Property 3: Breakeven Calculation Correctness
# Feature: fee-aware-exits, Property 3: Breakeven Calculation Correctness
# Validates: Requirements 1.6, 2.1, 2.2, 2.3
# =============================================================================

@settings(max_examples=100)
@given(
    size=position_size,
    entry_price=price,
    position_side=side,
    entry_is_maker=is_maker,
    exit_is_maker=is_maker,
)
def test_property_3_breakeven_calculation_correctness(
    size: float,
    entry_price: float,
    position_side: str,
    entry_is_maker: bool,
    exit_is_maker: bool,
):
    """
    Property 3: Breakeven Calculation Correctness
    
    For any valid position with size > 0 and entry_price > 0:
    - For long positions: breakeven_price == entry_price + (round_trip_fee / size)
    - For short positions: breakeven_price == entry_price - (round_trip_fee / size)
    - breakeven_bps == (round_trip_fee / (size × entry_price)) × 10000
    """
    model = FeeModel()
    
    result = model.calculate_breakeven(
        size, entry_price, position_side, entry_is_maker, exit_is_maker
    )
    
    assert result is not None, "Breakeven calculation should not return None for valid inputs"
    
    # Calculate expected values
    round_trip_fee = model.calculate_round_trip_fee(
        size, entry_price, entry_price, entry_is_maker, exit_is_maker
    )
    price_movement = round_trip_fee / size
    notional = size * entry_price
    expected_bps = (round_trip_fee / notional) * 10000.0
    
    if position_side == "long":
        expected_breakeven_price = entry_price + price_movement
    else:
        expected_breakeven_price = entry_price - price_movement
    
    # Verify breakeven price
    assert abs(result.breakeven_price - expected_breakeven_price) < 1e-6, (
        f"Breakeven price mismatch for {position_side}: "
        f"{result.breakeven_price} != {expected_breakeven_price}"
    )
    
    # Verify breakeven bps
    assert abs(result.breakeven_bps - expected_bps) < 1e-4, (
        f"Breakeven bps mismatch: {result.breakeven_bps} != {expected_bps}"
    )
    
    # Verify round-trip fee
    assert abs(result.round_trip_fee_usd - round_trip_fee) < 1e-6, (
        f"Round-trip fee mismatch: {result.round_trip_fee_usd} != {round_trip_fee}"
    )


# =============================================================================
# Property 4: Fee Structure Serialization Round-Trip
# Feature: fee-aware-exits, Property 4: Fee Structure Serialization Round-Trip
# Validates: Requirements 1.7
# =============================================================================

@settings(max_examples=100)
@given(
    taker_rate=fee_rate,
    maker_rate=fee_rate,
    rebate_rate=st.floats(min_value=0.0, max_value=0.001, allow_nan=False, allow_infinity=False),
)
def test_property_4_fee_config_serialization_round_trip(
    taker_rate: float,
    maker_rate: float,
    rebate_rate: float,
):
    """
    Property 4: Fee Structure Serialization Round-Trip
    
    For any valid FeeConfig, serializing to dict and deserializing
    SHALL produce an equivalent object.
    """
    original = FeeConfig(
        taker_fee_rate=taker_rate,
        maker_fee_rate=maker_rate,
        maker_rebate_rate=rebate_rate,
    )
    
    # Serialize and deserialize
    serialized = original.to_dict()
    restored = FeeConfig.from_dict(serialized)
    
    # Verify equivalence
    assert restored.taker_fee_rate == original.taker_fee_rate
    assert restored.maker_fee_rate == original.maker_fee_rate
    assert restored.maker_rebate_rate == original.maker_rebate_rate


@settings(max_examples=100)
@given(
    size=position_size,
    entry_price=price,
    position_side=side,
)
def test_property_4_breakeven_result_serialization_round_trip(
    size: float,
    entry_price: float,
    position_side: str,
):
    """
    Property 4: Fee Structure Serialization Round-Trip (BreakevenResult)
    
    For any valid BreakevenResult, serializing to dict and deserializing
    SHALL produce an equivalent object.
    """
    model = FeeModel()
    original = model.calculate_breakeven(size, entry_price, position_side)
    
    assert original is not None
    
    # Serialize and deserialize
    serialized = original.to_dict()
    restored = BreakevenResult.from_dict(serialized)
    
    # Verify equivalence (with floating point tolerance)
    assert abs(restored.breakeven_price - original.breakeven_price) < 1e-6
    assert abs(restored.breakeven_bps - original.breakeven_bps) < 1e-4
    assert abs(restored.round_trip_fee_usd - original.round_trip_fee_usd) < 1e-6
    assert restored.side == original.side
    assert abs(restored.entry_price - original.entry_price) < 1e-6
    assert abs(restored.size - original.size) < 1e-6


# =============================================================================
# Property 5: Invalidation Exit Gating
# Feature: fee-aware-exits, Property 5: Invalidation Exit Gating
# Validates: Requirements 3.2
# =============================================================================

@settings(max_examples=100)
@given(
    size=position_size,
    entry_price=price,
    position_side=side,
    buffer_bps=profit_buffer,
)
def test_property_5_invalidation_exit_gating(
    size: float,
    entry_price: float,
    position_side: str,
    buffer_bps: float,
):
    """
    Property 5: Invalidation Exit Gating
    
    For any invalidation exit where gross_pnl_bps < breakeven_bps + min_profit_buffer_bps,
    the exit SHALL be rejected (should_allow_exit == False).
    """
    model = FeeModel()
    
    # Calculate breakeven
    breakeven = model.calculate_breakeven(size, entry_price, position_side)
    assert breakeven is not None
    
    effective_buffer = max(0.0, buffer_bps)
    min_required_bps = breakeven.breakeven_bps + effective_buffer
    
    # Generate a price that results in profit BELOW the threshold
    # We want gross_pnl_bps < min_required_bps
    # For a long: gross_pnl_bps = ((current - entry) / entry) * 10000
    # So current = entry * (1 + gross_pnl_bps / 10000)
    
    # Pick a gross PnL that's below the threshold
    target_gross_pnl_bps = min_required_bps - 1.0  # 1 bps below threshold
    
    if position_side == "long":
        current_price = entry_price * (1 + target_gross_pnl_bps / 10000.0)
    else:
        current_price = entry_price * (1 - target_gross_pnl_bps / 10000.0)
    
    # Ensure price is positive
    assume(current_price > 0)
    
    result = model.check_exit_profitability(
        size, entry_price, current_price, position_side, buffer_bps
    )
    
    # Exit should be rejected because profit is below threshold
    assert result.should_allow_exit is False, (
        f"Exit should be rejected when gross_pnl_bps ({result.gross_pnl_bps}) < "
        f"min_required_bps ({result.min_required_bps})"
    )


# =============================================================================
# Property 6: Invalidation Exit Allowing
# Feature: fee-aware-exits, Property 6: Invalidation Exit Allowing
# Validates: Requirements 3.3
# =============================================================================

@settings(max_examples=100)
@given(
    size=position_size,
    entry_price=price,
    position_side=side,
    buffer_bps=profit_buffer,
)
def test_property_6_invalidation_exit_allowing(
    size: float,
    entry_price: float,
    position_side: str,
    buffer_bps: float,
):
    """
    Property 6: Invalidation Exit Allowing
    
    For any invalidation exit where gross_pnl_bps >= breakeven_bps + min_profit_buffer_bps,
    the exit SHALL be allowed (should_allow_exit == True).
    """
    model = FeeModel()
    
    # Calculate breakeven
    breakeven = model.calculate_breakeven(size, entry_price, position_side)
    assert breakeven is not None
    
    effective_buffer = max(0.0, buffer_bps)
    min_required_bps = breakeven.breakeven_bps + effective_buffer
    
    # Generate a price that results in profit AT OR ABOVE the threshold
    target_gross_pnl_bps = min_required_bps + 1.0  # 1 bps above threshold
    
    if position_side == "long":
        current_price = entry_price * (1 + target_gross_pnl_bps / 10000.0)
    else:
        current_price = entry_price * (1 - target_gross_pnl_bps / 10000.0)
    
    # Ensure price is positive
    assume(current_price > 0)
    
    result = model.check_exit_profitability(
        size, entry_price, current_price, position_side, buffer_bps
    )
    
    # Exit should be allowed because profit meets threshold
    assert result.should_allow_exit is True, (
        f"Exit should be allowed when gross_pnl_bps ({result.gross_pnl_bps}) >= "
        f"min_required_bps ({result.min_required_bps})"
    )


# =============================================================================
# Property 8: Profit Threshold Formula
# Feature: fee-aware-exits, Property 8: Profit Threshold Formula
# Validates: Requirements 4.2, 4.3, 4.5
# =============================================================================

@settings(max_examples=100)
@given(
    size=position_size,
    entry_price=price,
    current_price=price,
    position_side=side,
    buffer_bps=st.floats(min_value=-50.0, max_value=100.0, allow_nan=False, allow_infinity=False),
)
def test_property_8_profit_threshold_formula(
    size: float,
    entry_price: float,
    current_price: float,
    position_side: str,
    buffer_bps: float,
):
    """
    Property 8: Profit Threshold Formula
    
    For any exit evaluation, the minimum required profit in basis points
    SHALL equal breakeven_bps + max(0, min_profit_buffer_bps).
    Negative buffer values SHALL be treated as 0.
    
    Note: breakeven_bps in check_exit_profitability is calculated using
    actual entry and exit prices, not the estimate from calculate_breakeven.
    """
    model = FeeModel()
    
    result = model.check_exit_profitability(
        size, entry_price, current_price, position_side, buffer_bps
    )
    
    # Calculate expected min_required using the same method as check_exit_profitability
    # (which uses actual current_price for exit fee, not entry_price)
    entry_fee = model.calculate_entry_fee(size, entry_price, False)
    exit_fee = model.calculate_exit_fee(size, current_price, False)
    total_fees = entry_fee + exit_fee
    notional = size * entry_price
    actual_breakeven_bps = (total_fees / notional) * 10000.0 if notional > 0 else 0.0
    
    effective_buffer = max(0.0, buffer_bps)
    expected_min_required = actual_breakeven_bps + effective_buffer
    
    # Verify the formula (with tolerance for rounding)
    assert abs(result.min_required_bps - expected_min_required) < 0.5, (
        f"Min required mismatch: {result.min_required_bps} != "
        f"{actual_breakeven_bps} + {effective_buffer} = {expected_min_required}"
    )
    
    # Verify negative buffer is treated as 0
    if buffer_bps < 0:
        assert result.min_required_bps == pytest.approx(result.breakeven_bps, abs=0.5), (
            f"Negative buffer should be treated as 0: "
            f"min_required={result.min_required_bps}, breakeven={result.breakeven_bps}"
        )


# =============================================================================
# Unit Tests for Edge Cases
# =============================================================================

class TestFeeModelEdgeCases:
    """Unit tests for edge cases and specific scenarios."""
    
    def test_zero_size_returns_zero_fee(self):
        """Zero size should return zero fee."""
        model = FeeModel()
        assert model.calculate_entry_fee(0, 50000, False) == 0.0
        assert model.calculate_entry_fee(-1, 50000, False) == 0.0
    
    def test_zero_price_returns_zero_fee(self):
        """Zero price should return zero fee."""
        model = FeeModel()
        assert model.calculate_entry_fee(1.0, 0, False) == 0.0
        assert model.calculate_entry_fee(1.0, -100, False) == 0.0
    
    def test_breakeven_invalid_size_returns_none(self):
        """Invalid size should return None for breakeven."""
        model = FeeModel()
        assert model.calculate_breakeven(0, 50000, "long") is None
        assert model.calculate_breakeven(-1, 50000, "long") is None
    
    def test_breakeven_invalid_side_returns_none(self):
        """Invalid side should return None for breakeven."""
        model = FeeModel()
        assert model.calculate_breakeven(1.0, 50000, "invalid") is None
        assert model.calculate_breakeven(1.0, 50000, "") is None
    
    def test_exit_check_invalid_inputs(self):
        """Invalid inputs should return should_allow_exit=False."""
        model = FeeModel()
        
        result = model.check_exit_profitability(0, 50000, 50100, "long")
        assert result.should_allow_exit is False
        assert result.reason == "invalid_inputs"
        
        result = model.check_exit_profitability(1.0, 50000, 50100, "invalid")
        assert result.should_allow_exit is False
        assert result.reason == "invalid_side"
    
    def test_fee_config_presets(self):
        """Test exchange tier presets have expected values."""
        okx_regular = FeeConfig.okx_regular()
        assert okx_regular.taker_fee_rate == 0.0006
        assert okx_regular.maker_fee_rate == 0.0004
        
        okx_vip1 = FeeConfig.okx_vip1()
        assert okx_vip1.taker_fee_rate == 0.0004
        assert okx_vip1.maker_rebate_rate == 0.0001
        
        bybit_regular = FeeConfig.bybit_regular()
        assert bybit_regular.taker_fee_rate == 0.00055
    
    def test_concrete_breakeven_example(self):
        """Test a concrete example for sanity check."""
        # $10,000 position at $50,000 BTC = 0.2 BTC
        # Taker fee 0.06% = $6 per side = $12 round trip
        # Breakeven = 12 bps
        
        model = FeeModel(FeeConfig.okx_regular())
        result = model.calculate_breakeven(0.2, 50000, "long")
        
        assert result is not None
        assert result.round_trip_fee_usd == pytest.approx(12.0, abs=0.01)
        assert result.breakeven_bps == pytest.approx(12.0, abs=0.1)
        assert result.breakeven_price == pytest.approx(50060.0, abs=1.0)
    
    def test_concrete_exit_check_example(self):
        """Test a concrete exit check example."""
        # Entry: 0.2 BTC at $50,000 = $10,000 notional
        # Current: $50,050 = +$10 gross = +10 bps
        # Fees: $12 round trip = 12 bps breakeven
        # Buffer: 5 bps
        # Min required: 17 bps
        # Result: Should NOT allow exit (10 < 17)
        
        model = FeeModel(FeeConfig.okx_regular())
        result = model.check_exit_profitability(
            size=0.2,
            entry_price=50000,
            current_price=50050,
            side="long",
            min_profit_buffer_bps=5.0,
        )
        
        assert result.should_allow_exit is False
        assert result.gross_pnl_bps == pytest.approx(10.0, abs=0.5)
        assert result.breakeven_bps == pytest.approx(12.0, abs=0.5)
        assert result.min_required_bps == pytest.approx(17.0, abs=0.5)
        assert result.shortfall_bps > 0
    
    def test_profitable_exit_allowed(self):
        """Test that profitable exit is allowed."""
        # Entry: 0.2 BTC at $50,000
        # Current: $50,100 = +$20 gross = +20 bps
        # Fees: $12 = 12 bps
        # Buffer: 5 bps
        # Min required: 17 bps
        # Result: Should allow exit (20 >= 17)
        
        model = FeeModel(FeeConfig.okx_regular())
        result = model.check_exit_profitability(
            size=0.2,
            entry_price=50000,
            current_price=50100,
            side="long",
            min_profit_buffer_bps=5.0,
        )
        
        assert result.should_allow_exit is True
        assert result.gross_pnl_bps == pytest.approx(20.0, abs=0.5)
        assert result.shortfall_bps == 0.0


# =============================================================================
# Helper function tests
# =============================================================================

def test_calculate_breakeven_bps_helper():
    """Test the convenience function."""
    # Default taker both sides: 0.06% * 2 = 12 bps
    assert calculate_breakeven_bps() == pytest.approx(12.0, abs=0.1)
    
    # Maker both sides: 0.04% * 2 = 8 bps
    assert calculate_breakeven_bps(
        entry_is_maker=True, exit_is_maker=True
    ) == pytest.approx(8.0, abs=0.1)
    
    # Mixed: 0.04% + 0.06% = 10 bps
    assert calculate_breakeven_bps(
        entry_is_maker=True, exit_is_maker=False
    ) == pytest.approx(10.0, abs=0.1)


# =============================================================================
# Property 9: Size Independence (V2 Proposal Section 4)
# =============================================================================

@settings(max_examples=50)
@given(
    entry_price=price,
    position_side=side,
    entry_is_maker=is_maker,
    exit_is_maker=is_maker,
)
def test_property_9_size_independence(
    entry_price: float,
    position_side: str,
    entry_is_maker: bool,
    exit_is_maker: bool,
):
    """
    Property 9: Size Independence
    
    Breakeven percentage SHALL be size-independent because size cancels out
    in the calculation for linear fee structures (USDT perpetuals).
    
    This validates the assumption that breakeven_bps is constant across
    different position sizes for the same fee structure.
    
    Requirements: V2 Proposal Section 4 - Size-Independence Validation
    """
    fee_model = FeeModel(FeeConfig.okx_regular())
    
    # Test multiple position sizes
    sizes = [0.01, 0.1, 1.0, 10.0, 100.0]
    breakeven_bps_results = []
    
    for size in sizes:
        result = fee_model.calculate_breakeven(
            size=size,
            entry_price=entry_price,
            side=position_side,
            entry_is_maker=entry_is_maker,
            exit_is_maker=exit_is_maker,
        )
        assert result is not None, f"Breakeven calculation failed for size={size}"
        breakeven_bps_results.append(result.breakeven_bps)
    
    # All breakeven_bps values should be equal within epsilon
    reference_bps = breakeven_bps_results[0]
    for i, bps in enumerate(breakeven_bps_results):
        assert abs(bps - reference_bps) < 0.01, (
            f"Breakeven not size-independent: size={sizes[i]}, "
            f"bps={bps:.4f}, reference={reference_bps:.4f}, "
            f"all_results={breakeven_bps_results}"
        )
