"""
Property-based tests for AdaptiveParameterResolver.

Feature: symbol-adaptive-parameters
Tests correctness properties for parameter resolution and bounds enforcement.
"""

import pytest
from hypothesis import given, strategies as st, settings, assume

from quantgambit.deeptrader_core.types import SymbolCharacteristics
from quantgambit.signals.services.parameter_resolver import (
    AdaptiveParameterResolver,
    ResolvedParameters,
)


# =============================================================================
# Test Strategies (Generators)
# =============================================================================

# Realistic symbol names
symbol = st.text(
    alphabet=st.characters(whitelist_categories=("Lu", "Nd")),
    min_size=3,
    max_size=20,
).filter(lambda s: len(s) >= 3)

# Spread in basis points (0.1 to 100 bps - realistic range)
spread_bps = st.floats(min_value=0.1, max_value=100.0, allow_nan=False, allow_infinity=False)

# Depth in USD ($100 to $10M - realistic range)
depth_usd = st.floats(min_value=100.0, max_value=10_000_000.0, allow_nan=False, allow_infinity=False)

# Daily range percentage (0.1% to 50% - realistic range)
daily_range_pct = st.floats(min_value=0.001, max_value=0.5, allow_nan=False, allow_infinity=False)

# ATR value (positive, realistic range)
atr_value = st.floats(min_value=0.0, max_value=10000.0, allow_nan=False, allow_infinity=False)

# Volatility regime
volatility_regime = st.sampled_from(["low", "normal", "high"])

# Sample count (0 to 1M)
sample_count = st.integers(min_value=0, max_value=1_000_000)

# Timestamp in nanoseconds (realistic range)
timestamp_ns = st.integers(min_value=0, max_value=2**63 - 1)

# Multiplier values (positive, reasonable range)
multiplier = st.floats(min_value=0.01, max_value=10.0, allow_nan=False, allow_infinity=False)


# Strategy for generating SymbolCharacteristics
@st.composite
def symbol_characteristics(draw):
    """Generate valid SymbolCharacteristics objects."""
    return SymbolCharacteristics(
        symbol=draw(symbol),
        typical_spread_bps=draw(spread_bps),
        typical_depth_usd=draw(depth_usd),
        typical_daily_range_pct=draw(daily_range_pct),
        typical_atr=draw(atr_value),
        typical_volatility_regime=draw(volatility_regime),
        sample_count=draw(sample_count),
        last_updated_ns=draw(timestamp_ns),
    )


# Strategy for generating profile params with multipliers
@st.composite
def profile_params_with_multipliers(draw):
    """Generate profile params dict with optional multipliers."""
    params = {}
    
    # Randomly include each multiplier
    if draw(st.booleans()):
        params["poc_distance_atr_multiplier"] = draw(multiplier)
    if draw(st.booleans()):
        params["spread_typical_multiplier"] = draw(multiplier)
    if draw(st.booleans()):
        params["depth_typical_multiplier"] = draw(multiplier)
    if draw(st.booleans()):
        params["stop_loss_atr_multiplier"] = draw(multiplier)
    if draw(st.booleans()):
        params["take_profit_atr_multiplier"] = draw(multiplier)
    
    return params


# =============================================================================
# Property 2: Parameter Resolution Formula
# Feature: symbol-adaptive-parameters, Property 2: Parameter Resolution Formula
# Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.5, 2.6
# =============================================================================

@settings(max_examples=100)
@given(
    poc_mult=multiplier,
    spread_mult=multiplier,
    depth_mult=multiplier,
    stop_loss_mult=multiplier,
    take_profit_mult=multiplier,
    chars=symbol_characteristics(),
)
def test_property_2_resolution_formula_poc_distance(
    poc_mult: float,
    spread_mult: float,
    depth_mult: float,
    stop_loss_mult: float,
    take_profit_mult: float,
    chars: SymbolCharacteristics,
):
    """
    Property 2: Parameter Resolution Formula - POC Distance
    
    For any multiplier value M and symbol characteristic value C,
    the resolved parameter should equal M × C (before bounds are applied).
    
    This test verifies: min_distance_from_poc = poc_multiplier × typical_daily_range_pct
    
    **Validates: Requirements 2.1, 2.2**
    """
    resolver = AdaptiveParameterResolver()
    
    profile_params = {
        "poc_distance_atr_multiplier": poc_mult,
        "spread_typical_multiplier": spread_mult,
        "depth_typical_multiplier": depth_mult,
        "stop_loss_atr_multiplier": stop_loss_mult,
        "take_profit_atr_multiplier": take_profit_mult,
    }
    
    result = resolver.resolve(profile_params, chars)
    
    # Calculate expected raw value (before bounds)
    expected_raw = poc_mult * chars.typical_daily_range_pct
    
    # Apply bounds manually
    expected_bounded = max(
        resolver.MIN_POC_DISTANCE_PCT,
        min(resolver.MAX_POC_DISTANCE_PCT, expected_raw)
    )
    
    # Verify the resolved value matches expected
    assert abs(result.min_distance_from_poc_pct - expected_bounded) < 1e-9, (
        f"POC distance mismatch: got {result.min_distance_from_poc_pct}, "
        f"expected {expected_bounded} (raw={expected_raw})"
    )
    
    # Verify multiplier is stored correctly
    assert result.poc_distance_multiplier == poc_mult


@settings(max_examples=100)
@given(
    spread_mult=multiplier,
    chars=symbol_characteristics(),
)
def test_property_2_resolution_formula_spread(
    spread_mult: float,
    chars: SymbolCharacteristics,
):
    """
    Property 2: Parameter Resolution Formula - Spread
    
    Verifies: max_spread = spread_multiplier × typical_spread_bps
    
    **Validates: Requirements 2.1, 2.3**
    """
    resolver = AdaptiveParameterResolver()
    
    profile_params = {"spread_typical_multiplier": spread_mult}
    
    result = resolver.resolve(profile_params, chars)
    
    # Calculate expected raw value (before bounds)
    expected_raw = spread_mult * chars.typical_spread_bps
    
    # Apply bounds manually
    expected_bounded = max(
        resolver.MIN_SPREAD_BPS,
        min(resolver.MAX_SPREAD_BPS, expected_raw)
    )
    
    # Verify the resolved value matches expected
    assert abs(result.max_spread_bps - expected_bounded) < 1e-9, (
        f"Spread mismatch: got {result.max_spread_bps}, "
        f"expected {expected_bounded} (raw={expected_raw})"
    )


@settings(max_examples=100)
@given(
    depth_mult=multiplier,
    chars=symbol_characteristics(),
)
def test_property_2_resolution_formula_depth(
    depth_mult: float,
    chars: SymbolCharacteristics,
):
    """
    Property 2: Parameter Resolution Formula - Depth
    
    Verifies: min_depth = depth_multiplier × typical_depth_usd
    
    **Validates: Requirements 2.1, 2.4**
    """
    resolver = AdaptiveParameterResolver()
    
    profile_params = {"depth_typical_multiplier": depth_mult}
    
    result = resolver.resolve(profile_params, chars)
    
    # Calculate expected raw value (before bounds)
    expected_raw = depth_mult * chars.typical_depth_usd
    
    # Apply bounds manually
    expected_bounded = max(
        resolver.MIN_DEPTH_USD,
        min(resolver.MAX_DEPTH_USD, expected_raw)
    )
    
    # Verify the resolved value matches expected
    assert abs(result.min_depth_per_side_usd - expected_bounded) < 1e-9, (
        f"Depth mismatch: got {result.min_depth_per_side_usd}, "
        f"expected {expected_bounded} (raw={expected_raw})"
    )


@settings(max_examples=100)
@given(
    stop_loss_mult=multiplier,
    chars=symbol_characteristics(),
)
def test_property_2_resolution_formula_stop_loss(
    stop_loss_mult: float,
    chars: SymbolCharacteristics,
):
    """
    Property 2: Parameter Resolution Formula - Stop Loss
    
    Verifies: stop_loss = stop_loss_multiplier × typical_daily_range_pct
    
    **Validates: Requirements 2.1, 2.5**
    """
    resolver = AdaptiveParameterResolver()
    
    profile_params = {"stop_loss_atr_multiplier": stop_loss_mult}
    
    result = resolver.resolve(profile_params, chars)
    
    # Calculate expected raw value (before bounds)
    expected_raw = stop_loss_mult * chars.typical_daily_range_pct
    
    # Apply bounds manually
    expected_bounded = max(
        resolver.MIN_STOP_LOSS_PCT,
        min(resolver.MAX_STOP_LOSS_PCT, expected_raw)
    )
    
    # Verify the resolved value matches expected
    assert abs(result.stop_loss_pct - expected_bounded) < 1e-9, (
        f"Stop loss mismatch: got {result.stop_loss_pct}, "
        f"expected {expected_bounded} (raw={expected_raw})"
    )


@settings(max_examples=100)
@given(
    take_profit_mult=multiplier,
    chars=symbol_characteristics(),
)
def test_property_2_resolution_formula_take_profit(
    take_profit_mult: float,
    chars: SymbolCharacteristics,
):
    """
    Property 2: Parameter Resolution Formula - Take Profit
    
    Verifies: take_profit = take_profit_multiplier × typical_daily_range_pct
    
    **Validates: Requirements 2.1, 2.6**
    """
    resolver = AdaptiveParameterResolver()
    
    profile_params = {"take_profit_atr_multiplier": take_profit_mult}
    
    result = resolver.resolve(profile_params, chars)
    
    # Calculate expected raw value (before bounds)
    expected_raw = take_profit_mult * chars.typical_daily_range_pct
    
    # Apply bounds manually
    expected_bounded = max(
        resolver.MIN_TAKE_PROFIT_PCT,
        min(resolver.MAX_TAKE_PROFIT_PCT, expected_raw)
    )
    
    # Verify the resolved value matches expected
    assert abs(result.take_profit_pct - expected_bounded) < 1e-9, (
        f"Take profit mismatch: got {result.take_profit_pct}, "
        f"expected {expected_bounded} (raw={expected_raw})"
    )


@settings(max_examples=100)
@given(chars=symbol_characteristics())
def test_property_2_default_multipliers_used(chars: SymbolCharacteristics):
    """
    Property 2: Parameter Resolution Formula - Default Multipliers
    
    When no multipliers are specified in profile_params, the resolver
    should use the default multiplier constants.
    
    **Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.5, 2.6**
    """
    resolver = AdaptiveParameterResolver()
    
    # Empty profile params - should use all defaults
    profile_params = {}
    
    result = resolver.resolve(profile_params, chars)
    
    # Verify default multipliers are used
    assert result.poc_distance_multiplier == resolver.DEFAULT_POC_DISTANCE_MULTIPLIER
    assert result.spread_multiplier == resolver.DEFAULT_SPREAD_MULTIPLIER
    assert result.depth_multiplier == resolver.DEFAULT_DEPTH_MULTIPLIER
    assert result.stop_loss_multiplier == resolver.DEFAULT_STOP_LOSS_MULTIPLIER
    assert result.take_profit_multiplier == resolver.DEFAULT_TAKE_PROFIT_MULTIPLIER


# =============================================================================
# Property 3: Bounds Enforcement
# Feature: symbol-adaptive-parameters, Property 3: Bounds Enforcement
# Validates: Requirements 2.7
# =============================================================================

@settings(max_examples=100)
@given(
    profile_params=profile_params_with_multipliers(),
    chars=symbol_characteristics(),
)
def test_property_3_bounds_enforcement_all_params(
    profile_params: dict,
    chars: SymbolCharacteristics,
):
    """
    Property 3: Bounds Enforcement
    
    For any resolved parameter value, the final value should always
    be within the configured bounds [min, max].
    
    This test verifies all parameters are bounded correctly.
    
    **Validates: Requirements 2.7**
    """
    resolver = AdaptiveParameterResolver()
    
    result = resolver.resolve(profile_params, chars)
    
    # Verify POC distance is within bounds
    assert resolver.MIN_POC_DISTANCE_PCT <= result.min_distance_from_poc_pct <= resolver.MAX_POC_DISTANCE_PCT, (
        f"POC distance {result.min_distance_from_poc_pct} out of bounds "
        f"[{resolver.MIN_POC_DISTANCE_PCT}, {resolver.MAX_POC_DISTANCE_PCT}]"
    )
    
    # Verify spread is within bounds
    assert resolver.MIN_SPREAD_BPS <= result.max_spread_bps <= resolver.MAX_SPREAD_BPS, (
        f"Spread {result.max_spread_bps} out of bounds "
        f"[{resolver.MIN_SPREAD_BPS}, {resolver.MAX_SPREAD_BPS}]"
    )
    
    # Verify depth is within bounds
    assert resolver.MIN_DEPTH_USD <= result.min_depth_per_side_usd <= resolver.MAX_DEPTH_USD, (
        f"Depth {result.min_depth_per_side_usd} out of bounds "
        f"[{resolver.MIN_DEPTH_USD}, {resolver.MAX_DEPTH_USD}]"
    )
    
    # Verify stop loss is within bounds
    assert resolver.MIN_STOP_LOSS_PCT <= result.stop_loss_pct <= resolver.MAX_STOP_LOSS_PCT, (
        f"Stop loss {result.stop_loss_pct} out of bounds "
        f"[{resolver.MIN_STOP_LOSS_PCT}, {resolver.MAX_STOP_LOSS_PCT}]"
    )
    
    # Verify take profit is within bounds
    assert resolver.MIN_TAKE_PROFIT_PCT <= result.take_profit_pct <= resolver.MAX_TAKE_PROFIT_PCT, (
        f"Take profit {result.take_profit_pct} out of bounds "
        f"[{resolver.MIN_TAKE_PROFIT_PCT}, {resolver.MAX_TAKE_PROFIT_PCT}]"
    )


@settings(max_examples=100)
@given(
    very_small_mult=st.floats(min_value=0.0001, max_value=0.001, allow_nan=False, allow_infinity=False),
    chars=symbol_characteristics(),
)
def test_property_3_bounds_enforcement_minimum(
    very_small_mult: float,
    chars: SymbolCharacteristics,
):
    """
    Property 3: Bounds Enforcement - Minimum Bounds
    
    When multipliers are very small, the resolved values should
    be clamped to the minimum bounds.
    
    **Validates: Requirements 2.7**
    """
    resolver = AdaptiveParameterResolver()
    
    # Use very small multipliers that would produce values below minimums
    profile_params = {
        "poc_distance_atr_multiplier": very_small_mult,
        "spread_typical_multiplier": very_small_mult,
        "depth_typical_multiplier": very_small_mult,
        "stop_loss_atr_multiplier": very_small_mult,
        "take_profit_atr_multiplier": very_small_mult,
    }
    
    result = resolver.resolve(profile_params, chars)
    
    # All values should be at least the minimum
    assert result.min_distance_from_poc_pct >= resolver.MIN_POC_DISTANCE_PCT
    assert result.max_spread_bps >= resolver.MIN_SPREAD_BPS
    assert result.min_depth_per_side_usd >= resolver.MIN_DEPTH_USD
    assert result.stop_loss_pct >= resolver.MIN_STOP_LOSS_PCT
    assert result.take_profit_pct >= resolver.MIN_TAKE_PROFIT_PCT


@settings(max_examples=100)
@given(
    very_large_mult=st.floats(min_value=100.0, max_value=1000.0, allow_nan=False, allow_infinity=False),
    chars=symbol_characteristics(),
)
def test_property_3_bounds_enforcement_maximum(
    very_large_mult: float,
    chars: SymbolCharacteristics,
):
    """
    Property 3: Bounds Enforcement - Maximum Bounds
    
    When multipliers are very large, the resolved values should
    be clamped to the maximum bounds.
    
    **Validates: Requirements 2.7**
    """
    resolver = AdaptiveParameterResolver()
    
    # Use very large multipliers that would produce values above maximums
    profile_params = {
        "poc_distance_atr_multiplier": very_large_mult,
        "spread_typical_multiplier": very_large_mult,
        "depth_typical_multiplier": very_large_mult,
        "stop_loss_atr_multiplier": very_large_mult,
        "take_profit_atr_multiplier": very_large_mult,
    }
    
    result = resolver.resolve(profile_params, chars)
    
    # All values should be at most the maximum
    assert result.min_distance_from_poc_pct <= resolver.MAX_POC_DISTANCE_PCT
    assert result.max_spread_bps <= resolver.MAX_SPREAD_BPS
    assert result.min_depth_per_side_usd <= resolver.MAX_DEPTH_USD
    assert result.stop_loss_pct <= resolver.MAX_STOP_LOSS_PCT
    assert result.take_profit_pct <= resolver.MAX_TAKE_PROFIT_PCT


# =============================================================================
# Unit Tests for Additional Functionality
# =============================================================================

def test_resolve_with_fallback_uses_defaults():
    """
    Test that resolve_with_fallback uses default characteristics when None.
    
    Validates: Requirements 2.8
    """
    resolver = AdaptiveParameterResolver()
    
    result = resolver.resolve_with_fallback(
        profile_params={},
        characteristics=None,
        symbol="BTCUSDT",
    )
    
    # Should use default characteristics
    assert result.used_defaults is True
    assert result.symbol_characteristics.symbol == "BTCUSDT"
    assert result.symbol_characteristics.sample_count == 0


def test_resolved_parameters_to_dict():
    """
    Test that ResolvedParameters.to_dict() produces valid output.
    """
    chars = SymbolCharacteristics.default("ETHUSDT")
    resolver = AdaptiveParameterResolver()
    
    result = resolver.resolve({}, chars)
    result_dict = result.to_dict()
    
    # Verify all expected keys are present
    assert "min_distance_from_poc_pct" in result_dict
    assert "max_spread_bps" in result_dict
    assert "min_depth_per_side_usd" in result_dict
    assert "stop_loss_pct" in result_dict
    assert "take_profit_pct" in result_dict
    assert "poc_distance_multiplier" in result_dict
    assert "spread_multiplier" in result_dict
    assert "depth_multiplier" in result_dict
    assert "stop_loss_multiplier" in result_dict
    assert "take_profit_multiplier" in result_dict
    assert "symbol" in result_dict
    assert "used_defaults" in result_dict


def test_multiplier_from_profile_takes_precedence():
    """
    Test that multipliers from profile params override defaults.
    """
    chars = SymbolCharacteristics(
        symbol="SOLUSDT",
        typical_spread_bps=2.0,
        typical_depth_usd=100000.0,
        typical_daily_range_pct=0.05,  # 5%
        typical_atr=5.0,
        typical_volatility_regime="normal",
        sample_count=200,
        last_updated_ns=0,
    )
    
    resolver = AdaptiveParameterResolver()
    
    # Custom multiplier
    profile_params = {"poc_distance_atr_multiplier": 0.3}
    
    result = resolver.resolve(profile_params, chars)
    
    # Should use custom multiplier
    assert result.poc_distance_multiplier == 0.3
    
    # Expected: 0.3 * 0.05 = 0.015 (1.5%)
    expected = 0.3 * 0.05
    assert abs(result.min_distance_from_poc_pct - expected) < 1e-9


# =============================================================================
# Property 5: Multiplier Precedence
# Feature: symbol-adaptive-parameters, Property 5: Multiplier Precedence
# Validates: Requirements 3.7
# =============================================================================

@settings(max_examples=100)
@given(
    multiplier_value=multiplier,
    absolute_value=st.floats(min_value=0.001, max_value=0.1, allow_nan=False, allow_infinity=False),
    chars=symbol_characteristics(),
)
def test_property_5_multiplier_precedence_poc_distance(
    multiplier_value: float,
    absolute_value: float,
    chars: SymbolCharacteristics,
):
    """
    Property 5: Multiplier Precedence - POC Distance
    
    For any profile parameters where both multiplier and absolute values
    are specified, the resolved value should be derived from the multiplier
    (not the absolute value).
    
    This test verifies that poc_distance_atr_multiplier takes precedence
    over any absolute poc_distance value that might be in the profile.
    
    **Validates: Requirements 3.7**
    """
    resolver = AdaptiveParameterResolver()
    
    # Profile params with BOTH multiplier and absolute value
    # The multiplier should take precedence
    profile_params = {
        "poc_distance_atr_multiplier": multiplier_value,
        "min_distance_from_poc": absolute_value,  # This should be ignored
    }
    
    result = resolver.resolve(profile_params, chars)
    
    # Calculate expected value from multiplier (not absolute)
    expected_raw = multiplier_value * chars.typical_daily_range_pct
    expected_bounded = max(
        resolver.MIN_POC_DISTANCE_PCT,
        min(resolver.MAX_POC_DISTANCE_PCT, expected_raw)
    )
    
    # Verify the resolved value comes from multiplier, not absolute
    assert abs(result.min_distance_from_poc_pct - expected_bounded) < 1e-9, (
        f"POC distance should be derived from multiplier ({multiplier_value} × {chars.typical_daily_range_pct}), "
        f"not absolute value ({absolute_value}). Got {result.min_distance_from_poc_pct}, expected {expected_bounded}"
    )
    
    # Verify the multiplier is stored correctly
    assert result.poc_distance_multiplier == multiplier_value


@settings(max_examples=100)
@given(
    multiplier_value=multiplier,
    absolute_value=st.floats(min_value=0.001, max_value=0.05, allow_nan=False, allow_infinity=False),
    chars=symbol_characteristics(),
)
def test_property_5_multiplier_precedence_stop_loss(
    multiplier_value: float,
    absolute_value: float,
    chars: SymbolCharacteristics,
):
    """
    Property 5: Multiplier Precedence - Stop Loss
    
    For any profile parameters where both stop_loss_atr_multiplier and
    stop_loss_pct are specified, the resolved value should be derived
    from the multiplier.
    
    **Validates: Requirements 3.7**
    """
    resolver = AdaptiveParameterResolver()
    
    # Profile params with BOTH multiplier and absolute value
    profile_params = {
        "stop_loss_atr_multiplier": multiplier_value,
        "stop_loss_pct": absolute_value,  # This should be ignored
    }
    
    result = resolver.resolve(profile_params, chars)
    
    # Calculate expected value from multiplier
    expected_raw = multiplier_value * chars.typical_daily_range_pct
    expected_bounded = max(
        resolver.MIN_STOP_LOSS_PCT,
        min(resolver.MAX_STOP_LOSS_PCT, expected_raw)
    )
    
    # Verify the resolved value comes from multiplier
    assert abs(result.stop_loss_pct - expected_bounded) < 1e-9, (
        f"Stop loss should be derived from multiplier ({multiplier_value} × {chars.typical_daily_range_pct}), "
        f"not absolute value ({absolute_value}). Got {result.stop_loss_pct}, expected {expected_bounded}"
    )


@settings(max_examples=100)
@given(
    multiplier_value=multiplier,
    absolute_value=st.floats(min_value=0.001, max_value=0.1, allow_nan=False, allow_infinity=False),
    chars=symbol_characteristics(),
)
def test_property_5_multiplier_precedence_take_profit(
    multiplier_value: float,
    absolute_value: float,
    chars: SymbolCharacteristics,
):
    """
    Property 5: Multiplier Precedence - Take Profit
    
    For any profile parameters where both take_profit_atr_multiplier and
    take_profit_pct are specified, the resolved value should be derived
    from the multiplier.
    
    **Validates: Requirements 3.7**
    """
    resolver = AdaptiveParameterResolver()
    
    # Profile params with BOTH multiplier and absolute value
    profile_params = {
        "take_profit_atr_multiplier": multiplier_value,
        "take_profit_pct": absolute_value,  # This should be ignored
    }
    
    result = resolver.resolve(profile_params, chars)
    
    # Calculate expected value from multiplier
    expected_raw = multiplier_value * chars.typical_daily_range_pct
    expected_bounded = max(
        resolver.MIN_TAKE_PROFIT_PCT,
        min(resolver.MAX_TAKE_PROFIT_PCT, expected_raw)
    )
    
    # Verify the resolved value comes from multiplier
    assert abs(result.take_profit_pct - expected_bounded) < 1e-9, (
        f"Take profit should be derived from multiplier ({multiplier_value} × {chars.typical_daily_range_pct}), "
        f"not absolute value ({absolute_value}). Got {result.take_profit_pct}, expected {expected_bounded}"
    )


@settings(max_examples=100)
@given(
    multiplier_value=multiplier,
    absolute_value=st.floats(min_value=0.5, max_value=50.0, allow_nan=False, allow_infinity=False),
    chars=symbol_characteristics(),
)
def test_property_5_multiplier_precedence_spread(
    multiplier_value: float,
    absolute_value: float,
    chars: SymbolCharacteristics,
):
    """
    Property 5: Multiplier Precedence - Spread
    
    For any profile parameters where both spread_typical_multiplier and
    max_spread are specified, the resolved value should be derived
    from the multiplier.
    
    **Validates: Requirements 3.7**
    """
    resolver = AdaptiveParameterResolver()
    
    # Profile params with BOTH multiplier and absolute value
    profile_params = {
        "spread_typical_multiplier": multiplier_value,
        "max_spread": absolute_value,  # This should be ignored
    }
    
    result = resolver.resolve(profile_params, chars)
    
    # Calculate expected value from multiplier
    expected_raw = multiplier_value * chars.typical_spread_bps
    expected_bounded = max(
        resolver.MIN_SPREAD_BPS,
        min(resolver.MAX_SPREAD_BPS, expected_raw)
    )
    
    # Verify the resolved value comes from multiplier
    assert abs(result.max_spread_bps - expected_bounded) < 1e-9, (
        f"Spread should be derived from multiplier ({multiplier_value} × {chars.typical_spread_bps}), "
        f"not absolute value ({absolute_value}). Got {result.max_spread_bps}, expected {expected_bounded}"
    )


@settings(max_examples=100)
@given(
    multiplier_value=multiplier,
    absolute_value=st.floats(min_value=1000.0, max_value=1000000.0, allow_nan=False, allow_infinity=False),
    chars=symbol_characteristics(),
)
def test_property_5_multiplier_precedence_depth(
    multiplier_value: float,
    absolute_value: float,
    chars: SymbolCharacteristics,
):
    """
    Property 5: Multiplier Precedence - Depth
    
    For any profile parameters where both depth_typical_multiplier and
    min_depth_per_side_usd are specified, the resolved value should be
    derived from the multiplier.
    
    **Validates: Requirements 3.7**
    """
    resolver = AdaptiveParameterResolver()
    
    # Profile params with BOTH multiplier and absolute value
    profile_params = {
        "depth_typical_multiplier": multiplier_value,
        "min_depth_per_side_usd": absolute_value,  # This should be ignored
    }
    
    result = resolver.resolve(profile_params, chars)
    
    # Calculate expected value from multiplier
    expected_raw = multiplier_value * chars.typical_depth_usd
    expected_bounded = max(
        resolver.MIN_DEPTH_USD,
        min(resolver.MAX_DEPTH_USD, expected_raw)
    )
    
    # Verify the resolved value comes from multiplier
    assert abs(result.min_depth_per_side_usd - expected_bounded) < 1e-9, (
        f"Depth should be derived from multiplier ({multiplier_value} × {chars.typical_depth_usd}), "
        f"not absolute value ({absolute_value}). Got {result.min_depth_per_side_usd}, expected {expected_bounded}"
    )


@settings(max_examples=100)
@given(
    poc_mult=multiplier,
    spread_mult=multiplier,
    depth_mult=multiplier,
    stop_loss_mult=multiplier,
    take_profit_mult=multiplier,
    chars=symbol_characteristics(),
)
def test_property_5_multiplier_precedence_all_params(
    poc_mult: float,
    spread_mult: float,
    depth_mult: float,
    stop_loss_mult: float,
    take_profit_mult: float,
    chars: SymbolCharacteristics,
):
    """
    Property 5: Multiplier Precedence - All Parameters Combined
    
    For any profile parameters where ALL multipliers and absolute values
    are specified, ALL resolved values should be derived from multipliers.
    
    **Validates: Requirements 3.7**
    """
    resolver = AdaptiveParameterResolver()
    
    # Profile params with ALL multipliers AND absolute values
    profile_params = {
        # Multipliers (should be used)
        "poc_distance_atr_multiplier": poc_mult,
        "spread_typical_multiplier": spread_mult,
        "depth_typical_multiplier": depth_mult,
        "stop_loss_atr_multiplier": stop_loss_mult,
        "take_profit_atr_multiplier": take_profit_mult,
        # Absolute values (should be ignored)
        "min_distance_from_poc": 0.05,
        "max_spread": 25.0,
        "min_depth_per_side_usd": 50000.0,
        "stop_loss_pct": 0.02,
        "take_profit_pct": 0.03,
    }
    
    result = resolver.resolve(profile_params, chars)
    
    # Verify all multipliers are stored correctly
    assert result.poc_distance_multiplier == poc_mult
    assert result.spread_multiplier == spread_mult
    assert result.depth_multiplier == depth_mult
    assert result.stop_loss_multiplier == stop_loss_mult
    assert result.take_profit_multiplier == take_profit_mult
    
    # Verify POC distance from multiplier
    expected_poc = max(
        resolver.MIN_POC_DISTANCE_PCT,
        min(resolver.MAX_POC_DISTANCE_PCT, poc_mult * chars.typical_daily_range_pct)
    )
    assert abs(result.min_distance_from_poc_pct - expected_poc) < 1e-9
    
    # Verify spread from multiplier
    expected_spread = max(
        resolver.MIN_SPREAD_BPS,
        min(resolver.MAX_SPREAD_BPS, spread_mult * chars.typical_spread_bps)
    )
    assert abs(result.max_spread_bps - expected_spread) < 1e-9
    
    # Verify depth from multiplier
    expected_depth = max(
        resolver.MIN_DEPTH_USD,
        min(resolver.MAX_DEPTH_USD, depth_mult * chars.typical_depth_usd)
    )
    assert abs(result.min_depth_per_side_usd - expected_depth) < 1e-9
    
    # Verify stop loss from multiplier
    expected_sl = max(
        resolver.MIN_STOP_LOSS_PCT,
        min(resolver.MAX_STOP_LOSS_PCT, stop_loss_mult * chars.typical_daily_range_pct)
    )
    assert abs(result.stop_loss_pct - expected_sl) < 1e-9
    
    # Verify take profit from multiplier
    expected_tp = max(
        resolver.MIN_TAKE_PROFIT_PCT,
        min(resolver.MAX_TAKE_PROFIT_PCT, take_profit_mult * chars.typical_daily_range_pct)
    )
    assert abs(result.take_profit_pct - expected_tp) < 1e-9
