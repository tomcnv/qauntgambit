"""
Property-based tests for SymbolCharacteristicsStage.

Feature: symbol-adaptive-parameters
Tests correctness properties for the pipeline stage that injects
symbol characteristics into the context.
"""

import pytest
from hypothesis import given, strategies as st, settings, assume

from quantgambit.signals.pipeline import StageContext, StageResult
from quantgambit.signals.stages.symbol_characteristics_stage import (
    SymbolCharacteristicsStage,
    SymbolCharacteristicsStageConfig,
)
from quantgambit.signals.services.symbol_characteristics import SymbolCharacteristicsService
from quantgambit.signals.services.parameter_resolver import AdaptiveParameterResolver
from quantgambit.deeptrader_core.types import SymbolCharacteristics


# =============================================================================
# Test Strategies (Generators)
# =============================================================================

# Realistic symbol names
symbol = st.text(
    alphabet=st.characters(whitelist_categories=("Lu", "Nd")),
    min_size=3,
    max_size=20,
).filter(lambda s: len(s) >= 3)

# Price (positive, realistic range for crypto)
price = st.floats(min_value=0.01, max_value=100000.0, allow_nan=False, allow_infinity=False)

# Spread in basis points (0.1 to 100 bps - realistic range)
spread_bps = st.floats(min_value=0.1, max_value=100.0, allow_nan=False, allow_infinity=False)

# Depth in USD ($100 to $10M - realistic range)
depth_usd = st.floats(min_value=100.0, max_value=10_000_000.0, allow_nan=False, allow_infinity=False)

# ATR value (positive, realistic range)
atr_value = st.floats(min_value=0.0, max_value=10000.0, allow_nan=False, allow_infinity=False)

# Volatility regime
volatility_regime = st.sampled_from(["low", "normal", "high"])

# Profile multipliers (positive, reasonable range)
multiplier = st.floats(min_value=0.1, max_value=10.0, allow_nan=False, allow_infinity=False)


# =============================================================================
# Property 6: Stage Context Injection
# Feature: symbol-adaptive-parameters, Property 6: Stage Context Injection
# Validates: Requirements 5.2, 5.3
# =============================================================================

@settings(max_examples=100)
@given(
    sym=symbol,
    price_val=price,
    spread_val=spread_bps,
    bid_depth=depth_usd,
    ask_depth=depth_usd,
    atr=atr_value,
    vol_regime=volatility_regime,
)
@pytest.mark.asyncio
async def test_property_6_stage_context_injection(
    sym: str,
    price_val: float,
    spread_val: float,
    bid_depth: float,
    ask_depth: float,
    atr: float,
    vol_regime: str,
):
    """
    Property 6: Stage Context Injection
    
    For any pipeline execution, after SymbolCharacteristicsStage runs,
    ctx.data["symbol_characteristics"] SHALL contain a valid
    SymbolCharacteristics object.
    
    This test verifies that:
    1. The stage always returns CONTINUE (never rejects)
    2. ctx.data["symbol_characteristics"] is set after stage runs
    3. The characteristics object has the correct symbol
    4. ctx.data["resolved_params"] is set after stage runs
    
    **Validates: Requirements 5.2, 5.3**
    """
    assume(price_val > 0)
    assume(bid_depth > 0)
    assume(ask_depth > 0)
    
    # Create service and stage
    service = SymbolCharacteristicsService(redis_client=None)
    resolver = AdaptiveParameterResolver()
    stage = SymbolCharacteristicsStage(
        characteristics_service=service,
        resolver=resolver,
        config=SymbolCharacteristicsStageConfig(log_defaults=False),
    )
    
    # Create context with features
    ctx = StageContext(
        symbol=sym,
        data={
            "features": {
                "price": price_val,
                "bid": price_val * 0.999,
                "ask": price_val * 1.001,
                "spread_bps": spread_val,
                "bid_depth_usd": bid_depth,
                "ask_depth_usd": ask_depth,
                "atr": atr,
            },
            "market_context": {
                "volatility_regime": vol_regime,
            },
        },
    )
    
    # Run the stage
    result = await stage.run(ctx)
    
    # Property 1: Stage always returns CONTINUE
    assert result == StageResult.CONTINUE, (
        f"Stage should always return CONTINUE, got {result}"
    )
    
    # Property 2: symbol_characteristics is set (Requirement 5.3)
    assert "symbol_characteristics" in ctx.data, (
        "ctx.data['symbol_characteristics'] should be set after stage runs"
    )
    
    # Property 3: characteristics is a valid SymbolCharacteristics object
    characteristics = ctx.data["symbol_characteristics"]
    assert isinstance(characteristics, SymbolCharacteristics), (
        f"Expected SymbolCharacteristics, got {type(characteristics)}"
    )
    
    # Property 4: characteristics has correct symbol
    assert characteristics.symbol == sym, (
        f"Symbol mismatch: {characteristics.symbol} != {sym}"
    )
    
    # Property 5: resolved_params is set
    assert "resolved_params" in ctx.data, (
        "ctx.data['resolved_params'] should be set after stage runs"
    )
    
    # Property 6: resolved_params has expected fields
    resolved = ctx.data["resolved_params"]
    assert hasattr(resolved, "min_distance_from_poc_pct"), (
        "resolved_params should have min_distance_from_poc_pct"
    )
    assert hasattr(resolved, "max_spread_bps"), (
        "resolved_params should have max_spread_bps"
    )
    assert hasattr(resolved, "min_depth_per_side_usd"), (
        "resolved_params should have min_depth_per_side_usd"
    )


@settings(max_examples=100)
@given(
    sym=symbol,
    price_val=price,
    spread_val=spread_bps,
    bid_depth=depth_usd,
    ask_depth=depth_usd,
    atr=atr_value,
    vol_regime=volatility_regime,
    num_updates=st.integers(min_value=1, max_value=20),
)
@pytest.mark.asyncio
async def test_property_6_characteristics_updated_on_tick(
    sym: str,
    price_val: float,
    spread_val: float,
    bid_depth: float,
    ask_depth: float,
    atr: float,
    vol_regime: str,
    num_updates: int,
):
    """
    Property 6: Stage Context Injection - Update on Tick
    
    For any sequence of pipeline executions with update_on_tick=True,
    the characteristics should be updated with each tick.
    
    **Validates: Requirements 5.2, 5.3**
    """
    assume(price_val > 0)
    assume(bid_depth > 0)
    assume(ask_depth > 0)
    
    # Create service and stage
    service = SymbolCharacteristicsService(redis_client=None)
    resolver = AdaptiveParameterResolver()
    stage = SymbolCharacteristicsStage(
        characteristics_service=service,
        resolver=resolver,
        config=SymbolCharacteristicsStageConfig(
            update_on_tick=True,
            log_defaults=False,
        ),
    )
    
    # Run stage multiple times
    for i in range(num_updates):
        ctx = StageContext(
            symbol=sym,
            data={
                "features": {
                    "price": price_val,
                    "bid": price_val * 0.999,
                    "ask": price_val * 1.001,
                    "spread_bps": spread_val,
                    "bid_depth_usd": bid_depth,
                    "ask_depth_usd": ask_depth,
                    "atr": atr,
                },
                "market_context": {
                    "volatility_regime": vol_regime,
                },
            },
        )
        await stage.run(ctx)
    
    # Verify sample count increased
    characteristics = service.get_characteristics(sym)
    assert characteristics.sample_count == num_updates, (
        f"Sample count should be {num_updates}, got {characteristics.sample_count}"
    )


@settings(max_examples=100)
@given(
    sym=symbol,
)
@pytest.mark.asyncio
async def test_property_6_defaults_used_when_no_features(sym: str):
    """
    Property 6: Stage Context Injection - Defaults on Missing Data
    
    When features are missing or empty, the stage should still inject
    valid characteristics (using defaults) and return CONTINUE.
    
    **Validates: Requirements 5.3, 5.4**
    """
    # Create service and stage
    service = SymbolCharacteristicsService(redis_client=None)
    resolver = AdaptiveParameterResolver()
    stage = SymbolCharacteristicsStage(
        characteristics_service=service,
        resolver=resolver,
        config=SymbolCharacteristicsStageConfig(log_defaults=False),
    )
    
    # Create context with empty features
    ctx = StageContext(
        symbol=sym,
        data={
            "features": {},
            "market_context": {},
        },
    )
    
    # Run the stage
    result = await stage.run(ctx)
    
    # Stage should still return CONTINUE
    assert result == StageResult.CONTINUE
    
    # Characteristics should be set (using defaults)
    assert "symbol_characteristics" in ctx.data
    characteristics = ctx.data["symbol_characteristics"]
    assert characteristics.symbol == sym
    
    # Should be using defaults (sample_count = 0)
    assert characteristics.sample_count == 0, (
        "Should be using defaults when no features provided"
    )
    
    # resolved_params should still be set
    assert "resolved_params" in ctx.data


@settings(max_examples=100)
@given(
    sym=symbol,
    price_val=price,
    spread_val=spread_bps,
    bid_depth=depth_usd,
    ask_depth=depth_usd,
    poc_mult=multiplier,
    spread_mult=multiplier,
    depth_mult=multiplier,
)
@pytest.mark.asyncio
async def test_property_6_profile_params_used_in_resolution(
    sym: str,
    price_val: float,
    spread_val: float,
    bid_depth: float,
    ask_depth: float,
    poc_mult: float,
    spread_mult: float,
    depth_mult: float,
):
    """
    Property 6: Stage Context Injection - Profile Params Used
    
    When profile parameters are provided in context, they should be
    used in parameter resolution.
    
    **Validates: Requirements 5.2, 5.3**
    """
    assume(price_val > 0)
    assume(bid_depth > 0)
    assume(ask_depth > 0)
    
    # Create service and stage
    service = SymbolCharacteristicsService(redis_client=None)
    resolver = AdaptiveParameterResolver()
    stage = SymbolCharacteristicsStage(
        characteristics_service=service,
        resolver=resolver,
        config=SymbolCharacteristicsStageConfig(log_defaults=False),
    )
    
    # Create context with profile settings
    ctx = StageContext(
        symbol=sym,
        data={
            "features": {
                "price": price_val,
                "bid": price_val * 0.999,
                "ask": price_val * 1.001,
                "spread_bps": spread_val,
                "bid_depth_usd": bid_depth,
                "ask_depth_usd": ask_depth,
                "atr": 100.0,
            },
            "market_context": {
                "volatility_regime": "normal",
            },
            "profile_settings": {
                "poc_distance_atr_multiplier": poc_mult,
                "spread_typical_multiplier": spread_mult,
                "depth_typical_multiplier": depth_mult,
            },
        },
    )
    
    # Run the stage
    await stage.run(ctx)
    
    # Verify resolved params used the profile multipliers
    resolved = ctx.data["resolved_params"]
    assert resolved.poc_distance_multiplier == poc_mult, (
        f"POC multiplier should be {poc_mult}, got {resolved.poc_distance_multiplier}"
    )
    assert resolved.spread_multiplier == spread_mult, (
        f"Spread multiplier should be {spread_mult}, got {resolved.spread_multiplier}"
    )
    assert resolved.depth_multiplier == depth_mult, (
        f"Depth multiplier should be {depth_mult}, got {resolved.depth_multiplier}"
    )


# =============================================================================
# Unit Tests for Edge Cases
# =============================================================================

@pytest.mark.asyncio
async def test_stage_with_no_update_on_tick():
    """
    Test that update_on_tick=False prevents characteristic updates.
    """
    service = SymbolCharacteristicsService(redis_client=None)
    stage = SymbolCharacteristicsStage(
        characteristics_service=service,
        config=SymbolCharacteristicsStageConfig(
            update_on_tick=False,
            log_defaults=False,
        ),
    )
    
    ctx = StageContext(
        symbol="BTCUSDT",
        data={
            "features": {
                "price": 50000.0,
                "spread_bps": 5.0,
                "bid_depth_usd": 100000.0,
                "ask_depth_usd": 100000.0,
                "atr": 1000.0,
            },
            "market_context": {"volatility_regime": "normal"},
        },
    )
    
    await stage.run(ctx)
    
    # Characteristics should be defaults (not updated)
    chars = service.get_characteristics("BTCUSDT")
    assert chars.sample_count == 0, (
        "Sample count should be 0 when update_on_tick=False"
    )


@pytest.mark.asyncio
async def test_stage_extracts_spread_from_bid_ask():
    """
    Test that spread is calculated from bid/ask when spread_bps not provided.
    """
    service = SymbolCharacteristicsService(redis_client=None)
    stage = SymbolCharacteristicsStage(
        characteristics_service=service,
        config=SymbolCharacteristicsStageConfig(log_defaults=False),
    )
    
    price = 50000.0
    bid = 49990.0
    ask = 50010.0
    expected_spread_bps = (ask - bid) / price * 10000  # 4 bps
    
    ctx = StageContext(
        symbol="BTCUSDT",
        data={
            "features": {
                "price": price,
                "bid": bid,
                "ask": ask,
                # No spread_bps provided
                "bid_depth_usd": 100000.0,
                "ask_depth_usd": 100000.0,
                "atr": 1000.0,
            },
            "market_context": {"volatility_regime": "normal"},
        },
    )
    
    await stage.run(ctx)
    
    chars = service.get_characteristics("BTCUSDT")
    assert abs(chars.typical_spread_bps - expected_spread_bps) < 0.01, (
        f"Spread should be ~{expected_spread_bps}, got {chars.typical_spread_bps}"
    )
