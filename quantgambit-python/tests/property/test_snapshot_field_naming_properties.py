"""
Property-based tests for MarketSnapshot field naming and backward compatibility.

Feature: snapshot-field-naming-and-poc-accuracy
Tests correctness properties for:
- Property 1: to_dict() Serialization Uses New Field Names
- Property 2: Backward Compatibility Round-Trip

**Validates: Requirements 1.4, 1.5, 5.1**
"""

import pytest
from hypothesis import given, strategies as st, settings

from quantgambit.deeptrader_core.types import MarketSnapshot


# =============================================================================
# Test Strategies (Generators)
# =============================================================================

# Distance values in basis points - can be positive, negative, or zero
# Using a reasonable range for BPS values (-10000 to 10000 = -100% to +100%)
distance_bps = st.floats(
    min_value=-10000.0,
    max_value=10000.0,
    allow_nan=False,
    allow_infinity=False,
)

# Price values - positive floats representing asset prices
price = st.floats(
    min_value=0.01,
    max_value=100000.0,
    allow_nan=False,
    allow_infinity=False,
)

# Spread in basis points - positive values
spread_bps = st.floats(
    min_value=0.0,
    max_value=100.0,
    allow_nan=False,
    allow_infinity=False,
)

# Depth in USD - positive values
depth_usd = st.floats(
    min_value=0.0,
    max_value=10000000.0,
    allow_nan=False,
    allow_infinity=False,
)

# Imbalance values - between -1 and 1
imbalance = st.floats(
    min_value=-1.0,
    max_value=1.0,
    allow_nan=False,
    allow_infinity=False,
)

# Volatility values - non-negative
volatility = st.floats(
    min_value=0.0,
    max_value=1.0,
    allow_nan=False,
    allow_infinity=False,
)

# Score values - between 0 and 1
score = st.floats(
    min_value=0.0,
    max_value=1.0,
    allow_nan=False,
    allow_infinity=False,
)

# Timestamp in nanoseconds
timestamp_ns = st.integers(min_value=0, max_value=2**63 - 1)

# Age in milliseconds
age_ms = st.floats(
    min_value=0.0,
    max_value=10000.0,
    allow_nan=False,
    allow_infinity=False,
)

# Persistence in seconds
persistence_sec = st.floats(
    min_value=0.0,
    max_value=3600.0,
    allow_nan=False,
    allow_infinity=False,
)

# Vol regime options
vol_regime = st.sampled_from(["low", "normal", "high", "extreme"])

# Trend direction options
trend_direction = st.sampled_from(["up", "down", "neutral"])

# Position in value options
position_in_value = st.sampled_from(["above", "below", "inside"])

# Optional price (can be None or a positive float)
optional_price = st.one_of(st.none(), price)


# Strategy to generate a complete MarketSnapshot with random values
@st.composite
def market_snapshot_strategy(draw):
    """Generate a random MarketSnapshot with valid field values."""
    mid = draw(price)
    spread = draw(spread_bps) / 10000 * mid  # Convert bps to actual spread
    
    return MarketSnapshot(
        symbol=draw(st.text(min_size=1, max_size=10, alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZ")),
        exchange=draw(st.sampled_from(["binance", "bybit", "okx"])),
        timestamp_ns=draw(timestamp_ns),
        snapshot_age_ms=draw(age_ms),
        mid_price=mid,
        bid=mid - spread / 2,
        ask=mid + spread / 2,
        spread_bps=draw(spread_bps),
        bid_depth_usd=draw(depth_usd),
        ask_depth_usd=draw(depth_usd),
        depth_imbalance=draw(imbalance),
        imb_1s=draw(imbalance),
        imb_5s=draw(imbalance),
        imb_30s=draw(imbalance),
        orderflow_persistence_sec=draw(persistence_sec),
        rv_1s=draw(volatility),
        rv_10s=draw(volatility),
        rv_1m=draw(volatility),
        vol_shock=draw(st.booleans()),
        vol_regime=draw(vol_regime),
        vol_regime_score=draw(score),
        trend_direction=draw(trend_direction),
        trend_strength=draw(score),
        poc_price=draw(optional_price),
        vah_price=draw(optional_price),
        val_price=draw(optional_price),
        position_in_value=draw(position_in_value),
        expected_fill_slippage_bps=draw(spread_bps),
        typical_spread_bps=draw(spread_bps),
        data_quality_score=draw(score),
        ws_connected=draw(st.booleans()),
        # AMT distance fields with _bps suffix
        distance_to_poc_bps=draw(distance_bps),
        distance_to_vah_bps=draw(distance_bps),
        distance_to_val_bps=draw(distance_bps),
        # Rotation signals
        flow_rotation=draw(st.floats(min_value=-5.0, max_value=5.0, allow_nan=False, allow_infinity=False)),
        trend_bias=draw(st.floats(min_value=-1.0, max_value=1.0, allow_nan=False, allow_infinity=False)),
        rotation_factor=draw(st.floats(min_value=-15.0, max_value=15.0, allow_nan=False, allow_infinity=False)),
    )


# =============================================================================
# Property 1: to_dict() Serialization Uses New Field Names
# Feature: snapshot-field-naming-and-poc-accuracy, Property 1: to_dict() Serialization Uses New Field Names
# Validates: Requirements 1.4
# =============================================================================

@settings(max_examples=100)
@given(snapshot=market_snapshot_strategy())
def test_property_1_to_dict_contains_new_field_names(snapshot: MarketSnapshot):
    """
    Property 1: to_dict() Serialization Uses New Field Names
    
    *For any* MarketSnapshot instance with non-zero distance values, calling `to_dict()`
    SHALL produce a dictionary containing keys `distance_to_poc_bps`, `distance_to_vah_bps`,
    and `distance_to_val_bps` with the correct values.
    
    **Validates: Requirements 1.4**
    """
    # Call to_dict() to get the serialized dictionary
    result = snapshot.to_dict()
    
    # Property: to_dict() output SHALL contain the new _bps field names
    assert "distance_to_poc_bps" in result, (
        "to_dict() output should contain 'distance_to_poc_bps' key"
    )
    assert "distance_to_vah_bps" in result, (
        "to_dict() output should contain 'distance_to_vah_bps' key"
    )
    assert "distance_to_val_bps" in result, (
        "to_dict() output should contain 'distance_to_val_bps' key"
    )
    
    # Property: values in dict SHALL match field values on the snapshot
    assert result["distance_to_poc_bps"] == snapshot.distance_to_poc_bps, (
        f"to_dict()['distance_to_poc_bps']={result['distance_to_poc_bps']} "
        f"should equal snapshot.distance_to_poc_bps={snapshot.distance_to_poc_bps}"
    )
    assert result["distance_to_vah_bps"] == snapshot.distance_to_vah_bps, (
        f"to_dict()['distance_to_vah_bps']={result['distance_to_vah_bps']} "
        f"should equal snapshot.distance_to_vah_bps={snapshot.distance_to_vah_bps}"
    )
    assert result["distance_to_val_bps"] == snapshot.distance_to_val_bps, (
        f"to_dict()['distance_to_val_bps']={result['distance_to_val_bps']} "
        f"should equal snapshot.distance_to_val_bps={snapshot.distance_to_val_bps}"
    )


@settings(max_examples=100)
@given(snapshot=market_snapshot_strategy())
def test_property_1_to_dict_does_not_contain_old_field_names(snapshot: MarketSnapshot):
    """
    Property 1: to_dict() Serialization Uses New Field Names (negative check)
    
    *For any* MarketSnapshot instance, calling `to_dict()` SHALL NOT produce a dictionary
    containing the old field names `distance_to_poc`, `distance_to_vah`, or `distance_to_val`.
    
    **Validates: Requirements 1.4**
    """
    # Call to_dict() to get the serialized dictionary
    result = snapshot.to_dict()
    
    # Property: to_dict() output SHALL NOT contain the old field names
    assert "distance_to_poc" not in result, (
        "to_dict() output should NOT contain old 'distance_to_poc' key"
    )
    assert "distance_to_vah" not in result, (
        "to_dict() output should NOT contain old 'distance_to_vah' key"
    )
    assert "distance_to_val" not in result, (
        "to_dict() output should NOT contain old 'distance_to_val' key"
    )


@settings(max_examples=100)
@given(
    distance_poc=distance_bps,
    distance_vah=distance_bps,
    distance_val=distance_bps,
)
def test_property_1_to_dict_with_specific_distances(
    distance_poc: float,
    distance_vah: float,
    distance_val: float,
):
    """
    Property 1: to_dict() Serialization Uses New Field Names (specific values)
    
    *For any* distance values, creating a MarketSnapshot with those values and calling
    `to_dict()` SHALL produce a dictionary with the new _bps field names containing
    the exact values provided.
    
    **Validates: Requirements 1.4**
    """
    # Create a minimal MarketSnapshot with specific distance values
    snapshot = MarketSnapshot(
        symbol="TEST",
        exchange="test",
        timestamp_ns=0,
        snapshot_age_ms=0.0,
        mid_price=100.0,
        bid=99.99,
        ask=100.01,
        spread_bps=2.0,
        bid_depth_usd=10000.0,
        ask_depth_usd=10000.0,
        depth_imbalance=0.0,
        imb_1s=0.0,
        imb_5s=0.0,
        imb_30s=0.0,
        orderflow_persistence_sec=0.0,
        rv_1s=0.0,
        rv_10s=0.0,
        rv_1m=0.0,
        vol_shock=False,
        vol_regime="normal",
        vol_regime_score=0.5,
        trend_direction="neutral",
        trend_strength=0.0,
        poc_price=100.0,
        vah_price=101.0,
        val_price=99.0,
        position_in_value="inside",
        expected_fill_slippage_bps=1.0,
        typical_spread_bps=2.0,
        data_quality_score=1.0,
        ws_connected=True,
        # Set specific distance values
        distance_to_poc_bps=distance_poc,
        distance_to_vah_bps=distance_vah,
        distance_to_val_bps=distance_val,
    )
    
    # Call to_dict()
    result = snapshot.to_dict()
    
    # Verify new field names are present with correct values
    assert result["distance_to_poc_bps"] == distance_poc, (
        f"to_dict()['distance_to_poc_bps']={result['distance_to_poc_bps']} "
        f"should equal {distance_poc}"
    )
    assert result["distance_to_vah_bps"] == distance_vah, (
        f"to_dict()['distance_to_vah_bps']={result['distance_to_vah_bps']} "
        f"should equal {distance_vah}"
    )
    assert result["distance_to_val_bps"] == distance_val, (
        f"to_dict()['distance_to_val_bps']={result['distance_to_val_bps']} "
        f"should equal {distance_val}"
    )
    
    # Verify old field names are NOT present
    assert "distance_to_poc" not in result, (
        "to_dict() output should NOT contain old 'distance_to_poc' key"
    )
    assert "distance_to_vah" not in result, (
        "to_dict() output should NOT contain old 'distance_to_vah' key"
    )
    assert "distance_to_val" not in result, (
        "to_dict() output should NOT contain old 'distance_to_val' key"
    )


# =============================================================================
# Property 2: Backward Compatibility Round-Trip
# Feature: snapshot-field-naming-and-poc-accuracy, Property 2: Backward Compatibility Round-Trip
# Validates: Requirements 1.5, 5.1
# =============================================================================

@settings(max_examples=100)
@given(snapshot=market_snapshot_strategy())
def test_property_2_backward_compatibility_distance_to_poc(snapshot: MarketSnapshot):
    """
    Property 2: Backward Compatibility Round-Trip (distance_to_poc)
    
    *For any* MarketSnapshot instance, accessing the deprecated property `distance_to_poc`
    SHALL return the same value as `distance_to_poc_bps`.
    
    **Validates: Requirements 1.5, 5.1**
    """
    # Access the deprecated property (will emit deprecation warning)
    deprecated_value = snapshot.distance_to_poc
    
    # Access the new field directly
    new_value = snapshot.distance_to_poc_bps
    
    # Property: deprecated property returns same value as new field
    assert deprecated_value == new_value, (
        f"distance_to_poc={deprecated_value} should equal "
        f"distance_to_poc_bps={new_value}"
    )


@settings(max_examples=100)
@given(snapshot=market_snapshot_strategy())
def test_property_2_backward_compatibility_distance_to_vah(snapshot: MarketSnapshot):
    """
    Property 2: Backward Compatibility Round-Trip (distance_to_vah)
    
    *For any* MarketSnapshot instance, accessing the deprecated property `distance_to_vah`
    SHALL return the same value as `distance_to_vah_bps`.
    
    **Validates: Requirements 1.5, 5.1**
    """
    # Access the deprecated property (will emit deprecation warning)
    deprecated_value = snapshot.distance_to_vah
    
    # Access the new field directly
    new_value = snapshot.distance_to_vah_bps
    
    # Property: deprecated property returns same value as new field
    assert deprecated_value == new_value, (
        f"distance_to_vah={deprecated_value} should equal "
        f"distance_to_vah_bps={new_value}"
    )


@settings(max_examples=100)
@given(snapshot=market_snapshot_strategy())
def test_property_2_backward_compatibility_distance_to_val(snapshot: MarketSnapshot):
    """
    Property 2: Backward Compatibility Round-Trip (distance_to_val)
    
    *For any* MarketSnapshot instance, accessing the deprecated property `distance_to_val`
    SHALL return the same value as `distance_to_val_bps`.
    
    **Validates: Requirements 1.5, 5.1**
    """
    # Access the deprecated property (will emit deprecation warning)
    deprecated_value = snapshot.distance_to_val
    
    # Access the new field directly
    new_value = snapshot.distance_to_val_bps
    
    # Property: deprecated property returns same value as new field
    assert deprecated_value == new_value, (
        f"distance_to_val={deprecated_value} should equal "
        f"distance_to_val_bps={new_value}"
    )


@settings(max_examples=100)
@given(snapshot=market_snapshot_strategy())
def test_property_2_backward_compatibility_all_fields(snapshot: MarketSnapshot):
    """
    Property 2: Backward Compatibility Round-Trip (all distance fields)
    
    *For any* MarketSnapshot instance, accessing all deprecated distance properties
    SHALL return the same values as their corresponding _bps fields.
    
    **Validates: Requirements 1.5, 5.1**
    """
    # Test all three deprecated properties at once
    assert snapshot.distance_to_poc == snapshot.distance_to_poc_bps, (
        f"distance_to_poc mismatch: {snapshot.distance_to_poc} != {snapshot.distance_to_poc_bps}"
    )
    assert snapshot.distance_to_vah == snapshot.distance_to_vah_bps, (
        f"distance_to_vah mismatch: {snapshot.distance_to_vah} != {snapshot.distance_to_vah_bps}"
    )
    assert snapshot.distance_to_val == snapshot.distance_to_val_bps, (
        f"distance_to_val mismatch: {snapshot.distance_to_val} != {snapshot.distance_to_val_bps}"
    )


@settings(max_examples=100)
@given(
    distance_poc=distance_bps,
    distance_vah=distance_bps,
    distance_val=distance_bps,
)
def test_property_2_backward_compatibility_with_specific_distances(
    distance_poc: float,
    distance_vah: float,
    distance_val: float,
):
    """
    Property 2: Backward Compatibility Round-Trip (specific distance values)
    
    *For any* distance values, creating a MarketSnapshot with those values in the
    _bps fields SHALL make them accessible via the deprecated property names.
    
    **Validates: Requirements 1.5, 5.1**
    """
    # Create a minimal MarketSnapshot with specific distance values
    snapshot = MarketSnapshot(
        symbol="TEST",
        exchange="test",
        timestamp_ns=0,
        snapshot_age_ms=0.0,
        mid_price=100.0,
        bid=99.99,
        ask=100.01,
        spread_bps=2.0,
        bid_depth_usd=10000.0,
        ask_depth_usd=10000.0,
        depth_imbalance=0.0,
        imb_1s=0.0,
        imb_5s=0.0,
        imb_30s=0.0,
        orderflow_persistence_sec=0.0,
        rv_1s=0.0,
        rv_10s=0.0,
        rv_1m=0.0,
        vol_shock=False,
        vol_regime="normal",
        vol_regime_score=0.5,
        trend_direction="neutral",
        trend_strength=0.0,
        poc_price=100.0,
        vah_price=101.0,
        val_price=99.0,
        position_in_value="inside",
        expected_fill_slippage_bps=1.0,
        typical_spread_bps=2.0,
        data_quality_score=1.0,
        ws_connected=True,
        # Set specific distance values
        distance_to_poc_bps=distance_poc,
        distance_to_vah_bps=distance_vah,
        distance_to_val_bps=distance_val,
    )
    
    # Verify backward compatibility
    assert snapshot.distance_to_poc == distance_poc, (
        f"distance_to_poc={snapshot.distance_to_poc} should equal {distance_poc}"
    )
    assert snapshot.distance_to_vah == distance_vah, (
        f"distance_to_vah={snapshot.distance_to_vah} should equal {distance_vah}"
    )
    assert snapshot.distance_to_val == distance_val, (
        f"distance_to_val={snapshot.distance_to_val} should equal {distance_val}"
    )
