"""
Property-based tests for Context Vector Parity.

Feature: context-vector-parity

These tests verify the correctness properties of the unified ContextVector
builder and its helper functions, ensuring parity between live and backtest
context construction.

Uses hypothesis library with minimum 100 iterations per property test.
"""

import time
import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

from quantgambit.deeptrader_core.profiles.context_vector import (
    ContextVectorConfig,
    SpreadValidationResult,
    CostFieldsResult,
    TrendFieldsResult,
    validate_spread_bps,
    calculate_cost_fields,
    derive_trend_fields,
)


# ═══════════════════════════════════════════════════════════════
# STRATEGIES FOR PROPERTY-BASED TESTING
# ═══════════════════════════════════════════════════════════════

# Spread values including edge cases
spread_bps_strategy = st.floats(
    min_value=-100.0,
    max_value=200.0,
    allow_nan=False,
    allow_infinity=False,
)

# Valid spread values (positive, reasonable range)
valid_spread_bps_strategy = st.floats(
    min_value=0.1,
    max_value=100.0,
    allow_nan=False,
    allow_infinity=False,
)

# Price values (positive, reasonable for crypto)
price_strategy = st.floats(
    min_value=0.01,
    max_value=100000.0,
    allow_nan=False,
    allow_infinity=False,
)

# Depth values in USD
depth_usd_strategy = st.floats(
    min_value=0.0,
    max_value=1000000.0,
    allow_nan=False,
    allow_infinity=False,
)

# Trend direction
trend_direction_strategy = st.sampled_from(["up", "down", "flat", "neutral", "UP", "DOWN", "FLAT"])

# Trend strength (0 to 1)
trend_strength_strategy = st.floats(
    min_value=0.0,
    max_value=1.0,
    allow_nan=False,
    allow_infinity=False,
)

# Volatility regime
vol_regime_strategy = st.sampled_from(["low", "normal", "high", "extreme", "LOW", "NORMAL", "HIGH", "EXTREME"])

# Fee values in bps
fee_bps_strategy = st.floats(
    min_value=0.0,
    max_value=50.0,
    allow_nan=False,
    allow_infinity=False,
)


# ═══════════════════════════════════════════════════════════════
# PROPERTY 2: SPREAD VALIDATION BOUNDS
# Validates: Requirements 2.1
# ═══════════════════════════════════════════════════════════════

class TestSpreadValidationBounds:
    """
    Feature: context-vector-parity, Property 2: Spread Validation Bounds
    
    For any spread_bps value (including negative, zero, and extreme values),
    the validated spread SHALL be in the range [0.1, 100.0] bps.
    
    Validates: Requirements 2.1
    """
    
    @settings(max_examples=100)
    @given(spread_bps=spread_bps_strategy)
    def test_spread_always_in_valid_range(self, spread_bps: float):
        """
        **Validates: Requirements 2.1**
        
        Property: For any input spread_bps, the output is always in [0.1, 100.0].
        """
        result = validate_spread_bps(spread_bps)
        
        assert result.spread_bps >= 0.1, f"Spread {result.spread_bps} below minimum 0.1"
        assert result.spread_bps <= 100.0, f"Spread {result.spread_bps} above maximum 100.0"
    
    @settings(max_examples=100)
    @given(spread_bps=st.floats(min_value=-1000.0, max_value=0.0, allow_nan=False, allow_infinity=False))
    def test_negative_spread_defaults(self, spread_bps: float):
        """
        **Validates: Requirements 2.2**
        
        Property: Negative or zero spread defaults to 5.0 bps.
        """
        result = validate_spread_bps(spread_bps)
        
        assert result.was_defaulted or result.was_clamped, "Negative spread should be defaulted or clamped"
        assert result.spread_bps >= 0.1, "Result should be at least minimum"
    
    @settings(max_examples=100)
    @given(
        bid=price_strategy,
        spread_pct=st.floats(min_value=0.001, max_value=0.1, allow_nan=False, allow_infinity=False),
    )
    def test_crossed_book_detection(self, bid: float, spread_pct: float):
        """
        **Validates: Requirements 2.3, 2.5**
        
        Property: When bid >= ask (crossed book), spread is defaulted.
        """
        # Create crossed book scenario
        ask = bid * (1 - spread_pct)  # ask < bid (crossed)
        assume(ask < bid)
        
        result = validate_spread_bps(
            spread_bps=5.0,  # Valid spread, but book is crossed
            bid=bid,
            ask=ask,
        )
        
        assert result.was_defaulted, "Crossed book should trigger default"
        assert result.warning_message is not None, "Should have warning message"
        assert "Crossed book" in result.warning_message


# ═══════════════════════════════════════════════════════════════
# PROPERTY 3: COST FORMULA CORRECTNESS
# Validates: Requirements 3.2
# ═══════════════════════════════════════════════════════════════

class TestCostFormulaCorrectness:
    """
    Feature: context-vector-parity, Property 3: Cost Formula Correctness
    
    For any valid spread_bps, expected_fee_bps, and slippage_estimate,
    the expected_cost_bps SHALL equal spread_bps + expected_fee_bps + slippage_estimate.
    
    Validates: Requirements 3.2
    """
    
    @settings(max_examples=100)
    @given(
        spread_bps=valid_spread_bps_strategy,
        bid_depth_usd=depth_usd_strategy,
        ask_depth_usd=depth_usd_strategy,
    )
    def test_cost_equals_sum_of_components(
        self,
        spread_bps: float,
        bid_depth_usd: float,
        ask_depth_usd: float,
    ):
        """
        **Validates: Requirements 3.2**
        
        Property: expected_cost_bps = spread_bps + expected_fee_bps + slippage_estimate_bps
        """
        result = calculate_cost_fields(spread_bps, bid_depth_usd, ask_depth_usd)
        
        expected_sum = spread_bps + result.expected_fee_bps + result.slippage_estimate_bps
        
        assert abs(result.expected_cost_bps - expected_sum) < 0.0001, (
            f"Cost {result.expected_cost_bps} != sum {expected_sum} "
            f"(spread={spread_bps}, fee={result.expected_fee_bps}, slip={result.slippage_estimate_bps})"
        )


# ═══════════════════════════════════════════════════════════════
# PROPERTY 4: SLIPPAGE TIERS BASED ON DEPTH
# Validates: Requirements 3.3, 3.4, 3.5
# ═══════════════════════════════════════════════════════════════

class TestSlippageTiers:
    """
    Feature: context-vector-parity, Property 4: Slippage Tiers Based on Depth
    
    For any bid_depth_usd and ask_depth_usd values:
    - If total_depth > $100k, slippage_estimate SHALL be 0.5 bps
    - If $50k < total_depth <= $100k, slippage_estimate SHALL be 1.0 bps
    - If total_depth <= $50k, slippage_estimate SHALL be 2.0 bps
    
    Validates: Requirements 3.3, 3.4, 3.5
    """
    
    @settings(max_examples=100)
    @given(
        bid_depth=st.floats(min_value=50001.0, max_value=500000.0, allow_nan=False, allow_infinity=False),
        ask_depth=st.floats(min_value=50001.0, max_value=500000.0, allow_nan=False, allow_infinity=False),
    )
    def test_high_depth_slippage(self, bid_depth: float, ask_depth: float):
        """
        **Validates: Requirements 3.3**
        
        Property: When total_depth > $100k, slippage = 0.5 bps.
        """
        assume(bid_depth + ask_depth > 100000.0)
        
        result = calculate_cost_fields(5.0, bid_depth, ask_depth)
        
        assert result.slippage_estimate_bps == 0.5, (
            f"High depth ({bid_depth + ask_depth}) should have 0.5 bps slippage, got {result.slippage_estimate_bps}"
        )
    
    @settings(max_examples=100)
    @given(
        bid_depth=st.floats(min_value=25001.0, max_value=50000.0, allow_nan=False, allow_infinity=False),
        ask_depth=st.floats(min_value=25001.0, max_value=50000.0, allow_nan=False, allow_infinity=False),
    )
    def test_medium_depth_slippage(self, bid_depth: float, ask_depth: float):
        """
        **Validates: Requirements 3.4**
        
        Property: When $50k < total_depth <= $100k, slippage = 1.0 bps.
        """
        total = bid_depth + ask_depth
        assume(total > 50000.0 and total <= 100000.0)
        
        result = calculate_cost_fields(5.0, bid_depth, ask_depth)
        
        assert result.slippage_estimate_bps == 1.0, (
            f"Medium depth ({total}) should have 1.0 bps slippage, got {result.slippage_estimate_bps}"
        )
    
    @settings(max_examples=100)
    @given(
        bid_depth=st.floats(min_value=0.0, max_value=25000.0, allow_nan=False, allow_infinity=False),
        ask_depth=st.floats(min_value=0.0, max_value=25000.0, allow_nan=False, allow_infinity=False),
    )
    def test_low_depth_slippage(self, bid_depth: float, ask_depth: float):
        """
        **Validates: Requirements 3.5**
        
        Property: When total_depth <= $50k, slippage = 2.0 bps.
        """
        assume(bid_depth + ask_depth <= 50000.0)
        
        result = calculate_cost_fields(5.0, bid_depth, ask_depth)
        
        assert result.slippage_estimate_bps == 2.0, (
            f"Low depth ({bid_depth + ask_depth}) should have 2.0 bps slippage, got {result.slippage_estimate_bps}"
        )


# ═══════════════════════════════════════════════════════════════
# PROPERTY 5: CUSTOM CONFIG OVERRIDE
# Validates: Requirements 3.6
# ═══════════════════════════════════════════════════════════════

class TestCustomConfigOverride:
    """
    Feature: context-vector-parity, Property 5: Custom Config Override
    
    For any BacktestConfig with custom fee values, the resulting ContextVector
    SHALL use those custom values instead of defaults.
    
    Validates: Requirements 3.6
    """
    
    @settings(max_examples=100)
    @given(
        custom_fee=fee_bps_strategy,
        spread_bps=valid_spread_bps_strategy,
        bid_depth=depth_usd_strategy,
        ask_depth=depth_usd_strategy,
    )
    def test_custom_fee_override(
        self,
        custom_fee: float,
        spread_bps: float,
        bid_depth: float,
        ask_depth: float,
    ):
        """
        **Validates: Requirements 3.6**
        
        Property: Custom fee values override defaults.
        """
        result = calculate_cost_fields(
            spread_bps,
            bid_depth,
            ask_depth,
            custom_fee_bps=custom_fee,
        )
        
        assert result.expected_fee_bps == custom_fee, (
            f"Custom fee {custom_fee} should be used, got {result.expected_fee_bps}"
        )


# ═══════════════════════════════════════════════════════════════
# PROPERTY 6: EMA SPREAD DERIVATION FROM TREND DIRECTION
# Validates: Requirements 4.1, 4.2, 4.3, 4.4
# ═══════════════════════════════════════════════════════════════

class TestEmaSpreadDerivation:
    """
    Feature: context-vector-parity, Property 6: EMA Spread Derivation from Trend Direction
    
    For any trend_direction and trend_strength:
    - If trend_direction is "up", ema_spread_pct SHALL be trend_strength * 0.01 (positive)
    - If trend_direction is "down", ema_spread_pct SHALL be -trend_strength * 0.01 (negative)
    - If trend_direction is "flat" or "neutral", ema_spread_pct SHALL be 0.0
    
    Validates: Requirements 4.1, 4.2, 4.3, 4.4
    """
    
    @settings(max_examples=100)
    @given(trend_strength=trend_strength_strategy)
    def test_up_trend_positive_ema_spread(self, trend_strength: float):
        """
        **Validates: Requirements 4.2**
        
        Property: "up" trend produces positive ema_spread_pct.
        """
        result = derive_trend_fields("up", trend_strength, "normal")
        
        expected = trend_strength * 0.01
        assert abs(result.ema_spread_pct - expected) < 0.0001, (
            f"Up trend with strength {trend_strength} should give {expected}, got {result.ema_spread_pct}"
        )
        assert result.ema_spread_pct >= 0, "Up trend should have non-negative ema_spread_pct"
    
    @settings(max_examples=100)
    @given(trend_strength=trend_strength_strategy)
    def test_down_trend_negative_ema_spread(self, trend_strength: float):
        """
        **Validates: Requirements 4.3**
        
        Property: "down" trend produces negative ema_spread_pct.
        """
        result = derive_trend_fields("down", trend_strength, "normal")
        
        expected = -trend_strength * 0.01
        assert abs(result.ema_spread_pct - expected) < 0.0001, (
            f"Down trend with strength {trend_strength} should give {expected}, got {result.ema_spread_pct}"
        )
        assert result.ema_spread_pct <= 0, "Down trend should have non-positive ema_spread_pct"
    
    @settings(max_examples=100)
    @given(
        trend_direction=st.sampled_from(["flat", "neutral", "FLAT", "NEUTRAL"]),
        trend_strength=trend_strength_strategy,
    )
    def test_flat_trend_zero_ema_spread(self, trend_direction: str, trend_strength: float):
        """
        **Validates: Requirements 4.4**
        
        Property: "flat" or "neutral" trend produces zero ema_spread_pct.
        """
        result = derive_trend_fields(trend_direction, trend_strength, "normal")
        
        assert result.ema_spread_pct == 0.0, (
            f"Flat/neutral trend should give 0.0, got {result.ema_spread_pct}"
        )


# ═══════════════════════════════════════════════════════════════
# PROPERTY 7: ATR RATIO DERIVATION FROM VOL REGIME
# Validates: Requirements 4.5
# ═══════════════════════════════════════════════════════════════

class TestAtrRatioDerivation:
    """
    Feature: context-vector-parity, Property 7: ATR Ratio Derivation from Vol Regime
    
    For any vol_regime value, atr_ratio SHALL be derived as:
    - "low" → 0.5
    - "normal" → 1.0
    - "high" → 1.5
    - "extreme" → 2.0
    
    Validates: Requirements 4.5
    """
    
    def test_low_vol_regime_atr_ratio(self):
        """
        **Validates: Requirements 4.5**
        
        Property: "low" vol_regime produces atr_ratio = 0.5.
        """
        result = derive_trend_fields("flat", 0.0, "low")
        assert result.atr_ratio == 0.5, f"Low vol should give 0.5, got {result.atr_ratio}"
        
        # Also test uppercase
        result_upper = derive_trend_fields("flat", 0.0, "LOW")
        assert result_upper.atr_ratio == 0.5
    
    def test_normal_vol_regime_atr_ratio(self):
        """
        **Validates: Requirements 4.5**
        
        Property: "normal" vol_regime produces atr_ratio = 1.0.
        """
        result = derive_trend_fields("flat", 0.0, "normal")
        assert result.atr_ratio == 1.0, f"Normal vol should give 1.0, got {result.atr_ratio}"
    
    def test_high_vol_regime_atr_ratio(self):
        """
        **Validates: Requirements 4.5**
        
        Property: "high" vol_regime produces atr_ratio = 1.5.
        """
        result = derive_trend_fields("flat", 0.0, "high")
        assert result.atr_ratio == 1.5, f"High vol should give 1.5, got {result.atr_ratio}"
    
    def test_extreme_vol_regime_atr_ratio(self):
        """
        **Validates: Requirements 4.5**
        
        Property: "extreme" vol_regime produces atr_ratio = 2.0.
        """
        result = derive_trend_fields("flat", 0.0, "extreme")
        assert result.atr_ratio == 2.0, f"Extreme vol should give 2.0, got {result.atr_ratio}"
    
    @settings(max_examples=100)
    @given(vol_regime=vol_regime_strategy)
    def test_atr_ratio_always_positive(self, vol_regime: str):
        """
        **Validates: Requirements 4.5**
        
        Property: atr_ratio is always positive for any vol_regime.
        """
        result = derive_trend_fields("flat", 0.0, vol_regime)
        assert result.atr_ratio > 0, f"ATR ratio should be positive, got {result.atr_ratio}"



# ═══════════════════════════════════════════════════════════════
# PROPERTY 1: REGIME FAMILY DERIVATION VIA REGIMEMAPPER
# Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 1.9
# ═══════════════════════════════════════════════════════════════

from quantgambit.deeptrader_core.profiles.context_vector import (
    ContextVectorInput,
    build_context_vector,
    _derive_regime_family,
)


# Market regime strategy
market_regime_strategy = st.sampled_from(["range", "breakout", "squeeze", "chop", "unknown", ""])

# Liquidity score (0 to 1)
liquidity_score_strategy = st.floats(
    min_value=0.0,
    max_value=1.0,
    allow_nan=False,
    allow_infinity=False,
)

# Expected cost in bps
expected_cost_strategy = st.floats(
    min_value=0.0,
    max_value=50.0,
    allow_nan=False,
    allow_infinity=False,
)


class TestRegimeFamilyDerivation:
    """
    Feature: context-vector-parity, Property 1: Regime Family Derivation via RegimeMapper
    
    For any valid MarketSnapshot with a known market_regime, the backtest
    ContextVector's regime_family SHALL equal the result of calling
    RegimeMapper.map_regime() with the same context values.
    
    Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 1.9
    """
    
    @settings(max_examples=100)
    @given(trend_strength=trend_strength_strategy)
    def test_range_regime_mapping(self, trend_strength: float):
        """
        **Validates: Requirements 1.2, 1.3**
        
        Property: "range" maps to "mean_revert" unless trend_strength >= 0.3.
        """
        result = _derive_regime_family(
            market_regime="range",
            trend_strength=trend_strength,
            liquidity_score=0.5,
            expected_cost_bps=10.0,
        )
        
        if trend_strength >= 0.3:
            assert result == "trend", f"Range with high trend_strength should be 'trend', got {result}"
        else:
            assert result == "mean_revert", f"Range with low trend_strength should be 'mean_revert', got {result}"
    
    def test_breakout_regime_mapping(self):
        """
        **Validates: Requirements 1.4**
        
        Property: "breakout" always maps to "trend".
        """
        result = _derive_regime_family(
            market_regime="breakout",
            trend_strength=0.0,
            liquidity_score=0.5,
            expected_cost_bps=10.0,
        )
        assert result == "trend", f"Breakout should always be 'trend', got {result}"
    
    @settings(max_examples=100)
    @given(liquidity_score=liquidity_score_strategy)
    def test_squeeze_regime_mapping(self, liquidity_score: float):
        """
        **Validates: Requirements 1.5, 1.6**
        
        Property: "squeeze" maps to "avoid" if liquidity < 0.3, else "trend".
        """
        result = _derive_regime_family(
            market_regime="squeeze",
            trend_strength=0.5,
            liquidity_score=liquidity_score,
            expected_cost_bps=10.0,
        )
        
        if liquidity_score < 0.3:
            assert result == "avoid", f"Squeeze with low liquidity should be 'avoid', got {result}"
        else:
            assert result == "trend", f"Squeeze with good liquidity should be 'trend', got {result}"
    
    @settings(max_examples=100)
    @given(expected_cost=expected_cost_strategy)
    def test_chop_regime_mapping(self, expected_cost: float):
        """
        **Validates: Requirements 1.7, 1.8**
        
        Property: "chop" maps to "avoid" if cost > 15 bps, else "mean_revert".
        """
        result = _derive_regime_family(
            market_regime="chop",
            trend_strength=0.5,
            liquidity_score=0.5,
            expected_cost_bps=expected_cost,
        )
        
        if expected_cost > 15.0:
            assert result == "avoid", f"Chop with high cost should be 'avoid', got {result}"
        else:
            assert result == "mean_revert", f"Chop with low cost should be 'mean_revert', got {result}"
    
    @settings(max_examples=100)
    @given(market_regime=st.sampled_from(["unknown", "", "invalid", "xyz"]))
    def test_unknown_regime_mapping(self, market_regime: str):
        """
        **Validates: Requirements 1.9**
        
        Property: Unknown market_regime maps to "unknown".
        """
        result = _derive_regime_family(
            market_regime=market_regime,
            trend_strength=0.5,
            liquidity_score=0.5,
            expected_cost_bps=10.0,
        )
        assert result == "unknown", f"Unknown regime should map to 'unknown', got {result}"


# ═══════════════════════════════════════════════════════════════
# PROPERTY 8: REGIME FAMILY INVARIANT
# Validates: Requirements 6.1
# ═══════════════════════════════════════════════════════════════

class TestRegimeFamilyInvariant:
    """
    Feature: context-vector-parity, Property 8: Regime Family Invariant
    
    For any valid MarketSnapshot, the resulting ContextVector's regime_family
    SHALL be one of ["trend", "mean_revert", "avoid", "unknown"].
    
    Validates: Requirements 6.1
    """
    
    @settings(max_examples=100)
    @given(
        market_regime=market_regime_strategy,
        trend_strength=trend_strength_strategy,
        liquidity_score=liquidity_score_strategy,
        expected_cost=expected_cost_strategy,
    )
    def test_regime_family_always_valid(
        self,
        market_regime: str,
        trend_strength: float,
        liquidity_score: float,
        expected_cost: float,
    ):
        """
        **Validates: Requirements 6.1**
        
        Property: regime_family is always one of the valid values.
        """
        result = _derive_regime_family(
            market_regime=market_regime,
            trend_strength=trend_strength,
            liquidity_score=liquidity_score,
            expected_cost_bps=expected_cost,
        )
        
        valid_families = ["trend", "mean_revert", "avoid", "unknown"]
        assert result in valid_families, f"Invalid regime_family: {result}"


# ═══════════════════════════════════════════════════════════════
# PROPERTY 9: SPREAD BOUNDS INVARIANT (via unified builder)
# Validates: Requirements 6.2
# ═══════════════════════════════════════════════════════════════

class TestSpreadBoundsInvariant:
    """
    Feature: context-vector-parity, Property 9: Spread Bounds Invariant
    
    For any valid MarketSnapshot, the resulting ContextVector's spread_bps
    SHALL be in range [0.1, 100.0].
    
    Validates: Requirements 6.2
    """
    
    @settings(max_examples=100)
    @given(
        spread_bps=spread_bps_strategy,
        price=price_strategy,
    )
    def test_spread_bounds_via_builder(self, spread_bps: float, price: float):
        """
        **Validates: Requirements 6.2**
        
        Property: spread_bps in ContextVector is always in valid range.
        """
        input_data = ContextVectorInput(
            symbol="BTCUSDT",
            timestamp=time.time(),
            price=price,
            spread_bps=spread_bps,
        )
        
        result = build_context_vector(input_data)
        
        assert result.spread_bps >= 0.1, f"Spread {result.spread_bps} below minimum"
        assert result.spread_bps <= 100.0, f"Spread {result.spread_bps} above maximum"


# ═══════════════════════════════════════════════════════════════
# PROPERTY 10: COST GREATER THAN OR EQUAL TO SPREAD
# Validates: Requirements 6.3
# ═══════════════════════════════════════════════════════════════

class TestCostGreaterThanSpread:
    """
    Feature: context-vector-parity, Property 10: Cost Greater Than or Equal to Spread
    
    For any valid MarketSnapshot, the resulting ContextVector's expected_cost_bps
    SHALL be greater than or equal to spread_bps.
    
    Validates: Requirements 6.3
    """
    
    @settings(max_examples=100)
    @given(
        spread_bps=valid_spread_bps_strategy,
        bid_depth=depth_usd_strategy,
        ask_depth=depth_usd_strategy,
        price=price_strategy,
    )
    def test_cost_gte_spread(
        self,
        spread_bps: float,
        bid_depth: float,
        ask_depth: float,
        price: float,
    ):
        """
        **Validates: Requirements 6.3**
        
        Property: expected_cost_bps >= spread_bps.
        """
        input_data = ContextVectorInput(
            symbol="BTCUSDT",
            timestamp=time.time(),
            price=price,
            spread_bps=spread_bps,
            bid_depth_usd=bid_depth,
            ask_depth_usd=ask_depth,
        )
        
        result = build_context_vector(input_data)
        
        assert result.expected_cost_bps >= result.spread_bps, (
            f"Cost {result.expected_cost_bps} should be >= spread {result.spread_bps}"
        )


# ═══════════════════════════════════════════════════════════════
# PROPERTY 11: EMA SPREAD SIGN CONSISTENCY
# Validates: Requirements 6.4
# ═══════════════════════════════════════════════════════════════

class TestEmaSpreadSignConsistency:
    """
    Feature: context-vector-parity, Property 11: EMA Spread Sign Consistency
    
    For any valid MarketSnapshot with trend_direction:
    - If trend_direction is "up", ema_spread_pct SHALL be >= 0
    - If trend_direction is "down", ema_spread_pct SHALL be <= 0
    - If trend_direction is "flat" or "neutral", ema_spread_pct SHALL be 0
    
    Validates: Requirements 6.4
    """
    
    @settings(max_examples=100)
    @given(
        trend_strength=trend_strength_strategy,
        price=price_strategy,
    )
    def test_up_trend_positive_ema(self, trend_strength: float, price: float):
        """
        **Validates: Requirements 6.4**
        
        Property: "up" trend produces non-negative ema_spread_pct.
        """
        input_data = ContextVectorInput(
            symbol="BTCUSDT",
            timestamp=time.time(),
            price=price,
            trend_direction="up",
            trend_strength=trend_strength,
        )
        
        result = build_context_vector(input_data)
        
        assert result.ema_spread_pct >= 0, (
            f"Up trend should have non-negative ema_spread_pct, got {result.ema_spread_pct}"
        )
    
    @settings(max_examples=100)
    @given(
        trend_strength=trend_strength_strategy,
        price=price_strategy,
    )
    def test_down_trend_negative_ema(self, trend_strength: float, price: float):
        """
        **Validates: Requirements 6.4**
        
        Property: "down" trend produces non-positive ema_spread_pct.
        """
        input_data = ContextVectorInput(
            symbol="BTCUSDT",
            timestamp=time.time(),
            price=price,
            trend_direction="down",
            trend_strength=trend_strength,
        )
        
        result = build_context_vector(input_data)
        
        assert result.ema_spread_pct <= 0, (
            f"Down trend should have non-positive ema_spread_pct, got {result.ema_spread_pct}"
        )
    
    @settings(max_examples=100)
    @given(
        trend_direction=st.sampled_from(["flat", "neutral"]),
        price=price_strategy,
    )
    def test_flat_trend_zero_ema(self, trend_direction: str, price: float):
        """
        **Validates: Requirements 6.4**
        
        Property: "flat" or "neutral" trend produces zero ema_spread_pct.
        """
        input_data = ContextVectorInput(
            symbol="BTCUSDT",
            timestamp=time.time(),
            price=price,
            trend_direction=trend_direction,
            trend_strength=0.5,  # Non-zero strength, but flat direction
        )
        
        result = build_context_vector(input_data)
        
        assert result.ema_spread_pct == 0.0, (
            f"Flat trend should have zero ema_spread_pct, got {result.ema_spread_pct}"
        )


# ═══════════════════════════════════════════════════════════════
# PROPERTY 12: ATR RATIO POSITIVITY
# Validates: Requirements 6.5
# ═══════════════════════════════════════════════════════════════

class TestAtrRatioPositivity:
    """
    Feature: context-vector-parity, Property 12: ATR Ratio Positivity
    
    For any valid MarketSnapshot, the resulting ContextVector's atr_ratio
    SHALL be > 0.
    
    Validates: Requirements 6.5
    """
    
    @settings(max_examples=100)
    @given(
        vol_regime=vol_regime_strategy,
        price=price_strategy,
    )
    def test_atr_ratio_always_positive(self, vol_regime: str, price: float):
        """
        **Validates: Requirements 6.5**
        
        Property: atr_ratio is always positive.
        """
        input_data = ContextVectorInput(
            symbol="BTCUSDT",
            timestamp=time.time(),
            price=price,
            vol_regime=vol_regime,
        )
        
        result = build_context_vector(input_data)
        
        assert result.atr_ratio > 0, f"ATR ratio should be positive, got {result.atr_ratio}"
