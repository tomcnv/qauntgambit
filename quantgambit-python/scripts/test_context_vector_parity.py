#!/usr/bin/env python3
"""
Test script to verify Context Vector Parity fix.

This script demonstrates that the unified builder now correctly derives:
1. regime_family from market_regime (was always "unknown" before)
2. ema_spread_pct from trend_direction and trend_strength
3. atr_ratio from vol_regime
4. expected_cost_bps from spread + fees + slippage
5. spread_bps validation (clamped to [0.1, 100.0])

Run: python scripts/test_context_vector_parity.py
"""

import time
from quantgambit.deeptrader_core.profiles.context_vector import (
    ContextVectorInput,
    ContextVectorConfig,
    build_context_vector,
    validate_spread_bps,
    calculate_cost_fields,
    derive_trend_fields,
    _derive_regime_family,
)


def test_regime_family_derivation():
    """Test that regime_family is now correctly derived from market_regime."""
    print("\n" + "=" * 60)
    print("TEST 1: Regime Family Derivation")
    print("=" * 60)
    
    test_cases = [
        # (market_regime, trend_strength, liquidity_score, expected_cost, expected_family)
        ("range", 0.1, 0.5, 10.0, "mean_revert"),  # Low trend → mean_revert
        ("range", 0.5, 0.5, 10.0, "trend"),        # High trend → trend
        ("breakout", 0.0, 0.5, 10.0, "trend"),     # Always trend
        ("squeeze", 0.5, 0.2, 10.0, "avoid"),      # Low liquidity → avoid
        ("squeeze", 0.5, 0.5, 10.0, "trend"),      # Good liquidity → trend
        ("chop", 0.5, 0.5, 20.0, "avoid"),         # High cost → avoid
        ("chop", 0.5, 0.5, 10.0, "mean_revert"),   # Low cost → mean_revert
        ("unknown", 0.5, 0.5, 10.0, "unknown"),    # Unknown → unknown
        ("", 0.5, 0.5, 10.0, "unknown"),           # Empty → unknown
    ]
    
    all_passed = True
    for market_regime, trend_strength, liquidity_score, expected_cost, expected_family in test_cases:
        result = _derive_regime_family(market_regime, trend_strength, liquidity_score, expected_cost)
        status = "✅" if result == expected_family else "❌"
        if result != expected_family:
            all_passed = False
        print(f"  {status} market_regime='{market_regime}', trend={trend_strength:.1f}, liq={liquidity_score:.1f}, cost={expected_cost:.1f}")
        print(f"      → regime_family='{result}' (expected: '{expected_family}')")
    
    print(f"\n  {'✅ All regime family tests passed!' if all_passed else '❌ Some tests failed!'}")
    return all_passed


def test_spread_validation():
    """Test that spread_bps is validated and clamped correctly."""
    print("\n" + "=" * 60)
    print("TEST 2: Spread Validation")
    print("=" * 60)
    
    test_cases = [
        # (input_spread, expected_spread, should_warn)
        (5.0, 5.0, False),      # Valid spread
        (0.0, 5.0, True),       # Zero → default
        (-10.0, 5.0, True),     # Negative → default
        (0.05, 0.1, True),      # Below min → clamp to 0.1
        (150.0, 100.0, True),   # Above max → clamp to 100.0
    ]
    
    all_passed = True
    for input_spread, expected_spread, should_warn in test_cases:
        result = validate_spread_bps(input_spread)
        passed = abs(result.spread_bps - expected_spread) < 0.001
        warned = result.was_clamped or result.was_defaulted
        status = "✅" if passed and (warned == should_warn) else "❌"
        if not (passed and (warned == should_warn)):
            all_passed = False
        print(f"  {status} input={input_spread:.2f} → output={result.spread_bps:.2f} (expected: {expected_spread:.2f})")
        if result.warning_message:
            print(f"      Warning: {result.warning_message}")
    
    print(f"\n  {'✅ All spread validation tests passed!' if all_passed else '❌ Some tests failed!'}")
    return all_passed


def test_cost_calculation():
    """Test that expected_cost_bps is calculated correctly."""
    print("\n" + "=" * 60)
    print("TEST 3: Cost Calculation")
    print("=" * 60)
    
    test_cases = [
        # (spread, bid_depth, ask_depth, expected_slippage)
        (5.0, 60000, 60000, 0.5),   # High depth → 0.5 bps slippage
        (5.0, 30000, 30000, 1.0),   # Medium depth → 1.0 bps slippage
        (5.0, 10000, 10000, 2.0),   # Low depth → 2.0 bps slippage
    ]
    
    all_passed = True
    for spread, bid_depth, ask_depth, expected_slippage in test_cases:
        result = calculate_cost_fields(spread, bid_depth, ask_depth)
        total_depth = bid_depth + ask_depth
        expected_cost = spread + 12.0 + expected_slippage  # 12.0 is default fee
        
        passed = (
            abs(result.slippage_estimate_bps - expected_slippage) < 0.001 and
            abs(result.expected_cost_bps - expected_cost) < 0.001
        )
        status = "✅" if passed else "❌"
        if not passed:
            all_passed = False
        
        print(f"  {status} depth=${total_depth/1000:.0f}k → slippage={result.slippage_estimate_bps:.1f} bps")
        print(f"      cost = spread({spread:.1f}) + fee({result.expected_fee_bps:.1f}) + slip({result.slippage_estimate_bps:.1f}) = {result.expected_cost_bps:.1f} bps")
    
    print(f"\n  {'✅ All cost calculation tests passed!' if all_passed else '❌ Some tests failed!'}")
    return all_passed


def test_trend_field_derivation():
    """Test that ema_spread_pct and atr_ratio are derived correctly."""
    print("\n" + "=" * 60)
    print("TEST 4: Trend Field Derivation")
    print("=" * 60)
    
    test_cases = [
        # (trend_direction, trend_strength, vol_regime, expected_ema_sign, expected_atr)
        ("up", 0.5, "normal", "+", 1.0),
        ("down", 0.5, "normal", "-", 1.0),
        ("flat", 0.5, "normal", "0", 1.0),
        ("up", 0.5, "low", "+", 0.5),
        ("up", 0.5, "high", "+", 1.5),
        ("up", 0.5, "extreme", "+", 2.0),
    ]
    
    all_passed = True
    for trend_dir, trend_str, vol_regime, expected_sign, expected_atr in test_cases:
        result = derive_trend_fields(trend_dir, trend_str, vol_regime)
        
        # Check sign
        if expected_sign == "+":
            sign_ok = result.ema_spread_pct >= 0
        elif expected_sign == "-":
            sign_ok = result.ema_spread_pct <= 0
        else:
            sign_ok = result.ema_spread_pct == 0
        
        atr_ok = abs(result.atr_ratio - expected_atr) < 0.001
        passed = sign_ok and atr_ok
        status = "✅" if passed else "❌"
        if not passed:
            all_passed = False
        
        print(f"  {status} trend={trend_dir}, vol={vol_regime}")
        print(f"      → ema_spread_pct={result.ema_spread_pct:.4f} (sign: {expected_sign}), atr_ratio={result.atr_ratio:.1f}")
    
    print(f"\n  {'✅ All trend field tests passed!' if all_passed else '❌ Some tests failed!'}")
    return all_passed


def test_unified_builder():
    """Test the unified build_context_vector function."""
    print("\n" + "=" * 60)
    print("TEST 5: Unified Builder Integration")
    print("=" * 60)
    
    # Create a realistic backtest-like input
    input_data = ContextVectorInput(
        symbol="BTCUSDT",
        timestamp=time.time(),
        price=50000.0,
        bid=49990.0,
        ask=50010.0,
        spread_bps=4.0,
        bid_depth_usd=75000.0,
        ask_depth_usd=75000.0,
        orderbook_imbalance=0.1,
        trend_direction="up",
        trend_strength=0.4,
        vol_regime="normal",
        market_regime="range",
        poc_price=49500.0,
        vah_price=50500.0,
        val_price=49000.0,
        position_in_value="inside",
        trades_per_second=3.0,
    )
    
    # Build context vector
    ctx = build_context_vector(input_data, backtesting_mode=True)
    
    print(f"  Input:")
    print(f"    symbol: {input_data.symbol}")
    print(f"    price: ${input_data.price:,.0f}")
    print(f"    spread_bps: {input_data.spread_bps}")
    print(f"    market_regime: {input_data.market_regime}")
    print(f"    trend_direction: {input_data.trend_direction}")
    print(f"    trend_strength: {input_data.trend_strength}")
    print(f"    vol_regime: {input_data.vol_regime}")
    print(f"    depth: ${(input_data.bid_depth_usd + input_data.ask_depth_usd)/1000:.0f}k")
    
    print(f"\n  Output (ContextVector):")
    print(f"    ✅ regime_family: '{ctx.regime_family}' (was always 'unknown' before!)")
    print(f"    ✅ ema_spread_pct: {ctx.ema_spread_pct:.4f} (was always 0.0 before!)")
    print(f"    ✅ atr_ratio: {ctx.atr_ratio:.1f} (was always 1.0 before!)")
    print(f"    ✅ expected_cost_bps: {ctx.expected_cost_bps:.1f} (was always 0.0 before!)")
    print(f"    ✅ expected_fee_bps: {ctx.expected_fee_bps:.1f}")
    print(f"    ✅ spread_bps: {ctx.spread_bps:.1f} (validated)")
    print(f"    ✅ liquidity_score: {ctx.liquidity_score:.2f}")
    print(f"    ✅ session: {ctx.session}")
    
    # Verify key fields are populated correctly
    checks = [
        ("regime_family != 'unknown'", ctx.regime_family != "unknown"),
        ("regime_family in valid set", ctx.regime_family in ["trend", "mean_revert", "avoid", "unknown"]),
        ("ema_spread_pct > 0 (up trend)", ctx.ema_spread_pct > 0),
        ("atr_ratio == 1.0 (normal vol)", ctx.atr_ratio == 1.0),
        ("expected_cost_bps > spread_bps", ctx.expected_cost_bps > ctx.spread_bps),
        ("spread_bps in [0.1, 100]", 0.1 <= ctx.spread_bps <= 100.0),
    ]
    
    print(f"\n  Verification:")
    all_passed = True
    for check_name, passed in checks:
        status = "✅" if passed else "❌"
        if not passed:
            all_passed = False
        print(f"    {status} {check_name}")
    
    print(f"\n  {'✅ Unified builder test passed!' if all_passed else '❌ Some checks failed!'}")
    return all_passed


def main():
    print("\n" + "=" * 60)
    print("CONTEXT VECTOR PARITY TEST SUITE")
    print("=" * 60)
    print("\nThis script verifies the fix for pipeline starvation caused by")
    print("regime_family='unknown' in backtest mode.")
    
    results = []
    results.append(("Regime Family Derivation", test_regime_family_derivation()))
    results.append(("Spread Validation", test_spread_validation()))
    results.append(("Cost Calculation", test_cost_calculation()))
    results.append(("Trend Field Derivation", test_trend_field_derivation()))
    results.append(("Unified Builder", test_unified_builder()))
    
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    
    all_passed = True
    for name, passed in results:
        status = "✅ PASS" if passed else "❌ FAIL"
        if not passed:
            all_passed = False
        print(f"  {status}: {name}")
    
    print("\n" + "=" * 60)
    if all_passed:
        print("✅ ALL TESTS PASSED!")
        print("\nThe context vector parity fix is working correctly.")
        print("Backtest should now generate signals instead of starving.")
    else:
        print("❌ SOME TESTS FAILED!")
        print("\nPlease review the failures above.")
    print("=" * 60 + "\n")
    
    return 0 if all_passed else 1


if __name__ == "__main__":
    exit(main())
