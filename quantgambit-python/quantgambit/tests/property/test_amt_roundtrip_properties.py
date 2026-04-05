"""Property-based tests for AMT Fields Persistence Round-Trip.

Feature: amt-fields-in-decision-events

Tests the AMT fields serialization/deserialization properties:
- Property 5: AMT Fields Persistence Round-Trip

**Validates: Requirements 6.1, 6.2, 6.3, 6.4, 7.5**

These tests use Hypothesis to generate random MarketSnapshot objects with all
AMT fields populated and verify that serializing to decision_events payload
format (to_dict) preserves all AMT field values.
"""

import pytest
from hypothesis import given, strategies as st, settings, assume

from quantgambit.deeptrader_core.types import MarketSnapshot


# =============================================================================
# Strategies for generating test data
# =============================================================================

# Generate realistic price values (crypto range)
price_strategy = st.floats(
    min_value=0.01,
    max_value=1000000.0,
    allow_nan=False,
    allow_infinity=False,
)

# Generate positive price values for AMT levels
amt_level_strategy = st.floats(
    min_value=0.01,
    max_value=1000000.0,
    allow_nan=False,
    allow_infinity=False,
)

# Generate optional AMT level (can be None)
optional_amt_level_strategy = st.one_of(
    st.none(),
    amt_level_strategy,
)

# Generate position_in_value classification
position_in_value_strategy = st.sampled_from(["above", "below", "inside"])

# Generate distance values (can be positive or negative for signed distances)
distance_strategy = st.floats(
    min_value=-100000.0,
    max_value=100000.0,
    allow_nan=False,
    allow_infinity=False,
)


# Generate absolute distance values (always positive)
absolute_distance_strategy = st.floats(
    min_value=0.0,
    max_value=100000.0,
    allow_nan=False,
    allow_infinity=False,
)

# Generate rotation factor values (approximately -15 to +15 range)
rotation_factor_strategy = st.floats(
    min_value=-15.0,
    max_value=15.0,
    allow_nan=False,
    allow_infinity=False,
)

# Generate spread in basis points
spread_bps_strategy = st.floats(
    min_value=0.1,
    max_value=100.0,
    allow_nan=False,
    allow_infinity=False,
)

# Generate depth in USD
depth_usd_strategy = st.floats(
    min_value=100.0,
    max_value=10000000.0,
    allow_nan=False,
    allow_infinity=False,
)

# Generate imbalance values (-1 to +1)
imbalance_strategy = st.floats(
    min_value=-1.0,
    max_value=1.0,
    allow_nan=False,
    allow_infinity=False,
)

# Generate volatility values (small positive)
volatility_strategy = st.floats(
    min_value=0.0001,
    max_value=0.1,
    allow_nan=False,
    allow_infinity=False,
)

# Generate regime score (0 to 1)
regime_score_strategy = st.floats(
    min_value=0.0,
    max_value=1.0,
    allow_nan=False,
    allow_infinity=False,
)

# Generate vol regime classification
vol_regime_strategy = st.sampled_from(["low", "normal", "high", "extreme"])

# Generate trend direction
trend_direction_strategy = st.sampled_from(["up", "down", "neutral"])

# Generate timestamp in nanoseconds
timestamp_ns_strategy = st.integers(
    min_value=1000000000000000000,  # ~2001
    max_value=2000000000000000000,  # ~2033
)

# Generate age in milliseconds
age_ms_strategy = st.floats(
    min_value=0.0,
    max_value=1000.0,
    allow_nan=False,
    allow_infinity=False,
)

# Generate persistence in seconds
persistence_sec_strategy = st.floats(
    min_value=0.0,
    max_value=300.0,
    allow_nan=False,
    allow_infinity=False,
)


@st.composite
def market_snapshot_strategy(draw):
    """Generate a valid MarketSnapshot with all AMT fields populated.
    
    This strategy generates a complete MarketSnapshot object with realistic
    values for all fields, including all AMT-related fields.
    """
    # Generate base price
    mid_price = draw(price_strategy)
    
    # Generate spread and calculate bid/ask
    spread_bps = draw(spread_bps_strategy)
    half_spread = mid_price * spread_bps / 10000 / 2
    bid = mid_price - half_spread
    ask = mid_price + half_spread
    
    # Generate AMT levels (optional, but we want them populated for this test)
    poc_price = draw(amt_level_strategy)
    vah_price = draw(amt_level_strategy)
    val_price = draw(amt_level_strategy)
    
    # Ensure VAL <= VAH for valid AMT levels
    if val_price > vah_price:
        val_price, vah_price = vah_price, val_price
    
    # Generate position_in_value
    position_in_value = draw(position_in_value_strategy)
    
    # Generate distance fields (using _bps suffix per Requirement 2.3)
    distance_to_poc_bps = draw(distance_strategy)  # Signed distance in bps
    distance_to_vah_bps = draw(absolute_distance_strategy)  # Absolute distance in bps
    distance_to_val_bps = draw(absolute_distance_strategy)  # Absolute distance in bps
    
    # Generate rotation factor
    rotation_factor = draw(rotation_factor_strategy)
    
    # Generate other required fields
    bid_depth_usd = draw(depth_usd_strategy)
    ask_depth_usd = draw(depth_usd_strategy)
    depth_imbalance = draw(imbalance_strategy)
    
    imb_1s = draw(imbalance_strategy)
    imb_5s = draw(imbalance_strategy)
    imb_30s = draw(imbalance_strategy)
    orderflow_persistence_sec = draw(persistence_sec_strategy)
    
    rv_1s = draw(volatility_strategy)
    rv_10s = draw(volatility_strategy)
    rv_1m = draw(volatility_strategy)
    vol_shock = draw(st.booleans())
    
    vol_regime = draw(vol_regime_strategy)
    vol_regime_score = draw(regime_score_strategy)
    trend_direction = draw(trend_direction_strategy)
    trend_strength = draw(regime_score_strategy)
    
    expected_fill_slippage_bps = draw(spread_bps_strategy)
    typical_spread_bps = draw(spread_bps_strategy)
    
    data_quality_score = draw(regime_score_strategy)
    ws_connected = draw(st.booleans())
    
    timestamp_ns = draw(timestamp_ns_strategy)
    snapshot_age_ms = draw(age_ms_strategy)
    
    return MarketSnapshot(
        symbol="BTCUSDT",
        exchange="binance",
        timestamp_ns=timestamp_ns,
        snapshot_age_ms=snapshot_age_ms,
        mid_price=mid_price,
        bid=bid,
        ask=ask,
        spread_bps=spread_bps,
        bid_depth_usd=bid_depth_usd,
        ask_depth_usd=ask_depth_usd,
        depth_imbalance=depth_imbalance,
        imb_1s=imb_1s,
        imb_5s=imb_5s,
        imb_30s=imb_30s,
        orderflow_persistence_sec=orderflow_persistence_sec,
        rv_1s=rv_1s,
        rv_10s=rv_10s,
        rv_1m=rv_1m,
        vol_shock=vol_shock,
        vol_regime=vol_regime,
        vol_regime_score=vol_regime_score,
        trend_direction=trend_direction,
        trend_strength=trend_strength,
        poc_price=poc_price,
        vah_price=vah_price,
        val_price=val_price,
        position_in_value=position_in_value,
        expected_fill_slippage_bps=expected_fill_slippage_bps,
        typical_spread_bps=typical_spread_bps,
        data_quality_score=data_quality_score,
        ws_connected=ws_connected,
        distance_to_poc_bps=distance_to_poc_bps,
        distance_to_vah_bps=distance_to_vah_bps,
        distance_to_val_bps=distance_to_val_bps,
        rotation_factor=rotation_factor,
    )


@st.composite
def market_snapshot_with_none_amt_strategy(draw):
    """Generate a MarketSnapshot with some AMT fields set to None.
    
    This strategy tests the round-trip behavior when AMT levels are not available.
    """
    # Generate base price
    mid_price = draw(price_strategy)
    
    # Generate spread and calculate bid/ask
    spread_bps = draw(spread_bps_strategy)
    half_spread = mid_price * spread_bps / 10000 / 2
    bid = mid_price - half_spread
    ask = mid_price + half_spread
    
    # Generate optional AMT levels (can be None)
    poc_price = draw(optional_amt_level_strategy)
    vah_price = draw(optional_amt_level_strategy)
    val_price = draw(optional_amt_level_strategy)
    
    # Generate position_in_value (defaults to "inside" when levels are None)
    position_in_value = draw(position_in_value_strategy)
    
    # Generate distance fields (default to 0.0 when levels are None, using _bps suffix per Requirement 2.3)
    distance_to_poc_bps = draw(distance_strategy)
    distance_to_vah_bps = draw(absolute_distance_strategy)
    distance_to_val_bps = draw(absolute_distance_strategy)
    
    # Generate rotation factor
    rotation_factor = draw(rotation_factor_strategy)
    
    # Generate other required fields
    bid_depth_usd = draw(depth_usd_strategy)
    ask_depth_usd = draw(depth_usd_strategy)
    depth_imbalance = draw(imbalance_strategy)
    
    imb_1s = draw(imbalance_strategy)
    imb_5s = draw(imbalance_strategy)
    imb_30s = draw(imbalance_strategy)
    orderflow_persistence_sec = draw(persistence_sec_strategy)
    
    rv_1s = draw(volatility_strategy)
    rv_10s = draw(volatility_strategy)
    rv_1m = draw(volatility_strategy)
    vol_shock = draw(st.booleans())
    
    vol_regime = draw(vol_regime_strategy)
    vol_regime_score = draw(regime_score_strategy)
    trend_direction = draw(trend_direction_strategy)
    trend_strength = draw(regime_score_strategy)
    
    expected_fill_slippage_bps = draw(spread_bps_strategy)
    typical_spread_bps = draw(spread_bps_strategy)
    
    data_quality_score = draw(regime_score_strategy)
    ws_connected = draw(st.booleans())
    
    timestamp_ns = draw(timestamp_ns_strategy)
    snapshot_age_ms = draw(age_ms_strategy)
    
    return MarketSnapshot(
        symbol="BTCUSDT",
        exchange="binance",
        timestamp_ns=timestamp_ns,
        snapshot_age_ms=snapshot_age_ms,
        mid_price=mid_price,
        bid=bid,
        ask=ask,
        spread_bps=spread_bps,
        bid_depth_usd=bid_depth_usd,
        ask_depth_usd=ask_depth_usd,
        depth_imbalance=depth_imbalance,
        imb_1s=imb_1s,
        imb_5s=imb_5s,
        imb_30s=imb_30s,
        orderflow_persistence_sec=orderflow_persistence_sec,
        rv_1s=rv_1s,
        rv_10s=rv_10s,
        rv_1m=rv_1m,
        vol_shock=vol_shock,
        vol_regime=vol_regime,
        vol_regime_score=vol_regime_score,
        trend_direction=trend_direction,
        trend_strength=trend_strength,
        poc_price=poc_price,
        vah_price=vah_price,
        val_price=val_price,
        position_in_value=position_in_value,
        expected_fill_slippage_bps=expected_fill_slippage_bps,
        typical_spread_bps=typical_spread_bps,
        data_quality_score=data_quality_score,
        ws_connected=ws_connected,
        distance_to_poc_bps=distance_to_poc_bps,
        distance_to_vah_bps=distance_to_vah_bps,
        distance_to_val_bps=distance_to_val_bps,
        rotation_factor=rotation_factor,
    )


# =============================================================================
# Property Tests
# =============================================================================

class TestAMTFieldsRoundTripProperties:
    """Property-based tests for AMT Fields Persistence Round-Trip.
    
    Feature: amt-fields-in-decision-events
    Property 5: AMT Fields Persistence Round-Trip
    **Validates: Requirements 6.1, 6.2, 6.3, 6.4, 7.5**
    """
    
    @given(snapshot=market_snapshot_strategy())
    @settings(max_examples=100)
    def test_property_5_amt_fields_roundtrip(self, snapshot: MarketSnapshot):
        """Property 5: AMT Fields Persistence Round-Trip.
        
        *For any* MarketSnapshot with AMT fields, serializing to decision_events
        payload format and deserializing back SHALL preserve all AMT field values
        (poc_price, vah_price, val_price, position_in_value, distance_to_poc,
        distance_to_vah, distance_to_val, rotation_factor).
        
        Feature: amt-fields-in-decision-events, Property 5: AMT Fields Persistence Round-Trip
        **Validates: Requirements 6.1, 6.2, 6.3, 6.4, 7.5**
        """
        # Serialize to dict (decision_events payload format)
        serialized = snapshot.to_dict()
        
        # Verify all AMT fields are preserved in serialized output
        # Requirement 6.1: poc_price, vah_price, val_price
        assert serialized["poc_price"] == snapshot.poc_price, (
            f"poc_price mismatch: expected {snapshot.poc_price}, got {serialized['poc_price']}"
        )
        assert serialized["vah_price"] == snapshot.vah_price, (
            f"vah_price mismatch: expected {snapshot.vah_price}, got {serialized['vah_price']}"
        )
        assert serialized["val_price"] == snapshot.val_price, (
            f"val_price mismatch: expected {snapshot.val_price}, got {serialized['val_price']}"
        )
        
        # Requirement 6.2: position_in_value
        assert serialized["position_in_value"] == snapshot.position_in_value, (
            f"position_in_value mismatch: expected {snapshot.position_in_value}, "
            f"got {serialized['position_in_value']}"
        )
        
        # Requirement 6.3: distance_to_poc_bps, distance_to_vah_bps, distance_to_val_bps
        assert serialized["distance_to_poc_bps"] == snapshot.distance_to_poc_bps, (
            f"distance_to_poc_bps mismatch: expected {snapshot.distance_to_poc_bps}, "
            f"got {serialized['distance_to_poc_bps']}"
        )
        assert serialized["distance_to_vah_bps"] == snapshot.distance_to_vah_bps, (
            f"distance_to_vah_bps mismatch: expected {snapshot.distance_to_vah_bps}, "
            f"got {serialized['distance_to_vah_bps']}"
        )
        assert serialized["distance_to_val_bps"] == snapshot.distance_to_val_bps, (
            f"distance_to_val_bps mismatch: expected {snapshot.distance_to_val_bps}, "
            f"got {serialized['distance_to_val_bps']}"
        )
        
        # Requirement 6.4: rotation_factor
        assert serialized["rotation_factor"] == snapshot.rotation_factor, (
            f"rotation_factor mismatch: expected {snapshot.rotation_factor}, "
            f"got {serialized['rotation_factor']}"
        )

    
    @given(snapshot=market_snapshot_with_none_amt_strategy())
    @settings(max_examples=100)
    def test_property_5_amt_fields_roundtrip_with_optional_none(
        self, snapshot: MarketSnapshot
    ):
        """Property 5: AMT Fields Round-Trip with Optional None Values.
        
        *For any* MarketSnapshot with optional AMT fields (some may be None),
        serializing to decision_events payload format SHALL preserve all AMT
        field values including None values.
        
        Feature: amt-fields-in-decision-events, Property 5: AMT Fields Persistence Round-Trip
        **Validates: Requirements 6.1, 6.2, 6.3, 6.4, 7.5**
        """
        # Serialize to dict (decision_events payload format)
        serialized = snapshot.to_dict()
        
        # Verify all AMT fields are preserved (including None values)
        assert serialized["poc_price"] == snapshot.poc_price, (
            f"poc_price mismatch: expected {snapshot.poc_price}, got {serialized['poc_price']}"
        )
        assert serialized["vah_price"] == snapshot.vah_price, (
            f"vah_price mismatch: expected {snapshot.vah_price}, got {serialized['vah_price']}"
        )
        assert serialized["val_price"] == snapshot.val_price, (
            f"val_price mismatch: expected {snapshot.val_price}, got {serialized['val_price']}"
        )
        assert serialized["position_in_value"] == snapshot.position_in_value, (
            f"position_in_value mismatch: expected {snapshot.position_in_value}, "
            f"got {serialized['position_in_value']}"
        )
        assert serialized["distance_to_poc_bps"] == snapshot.distance_to_poc_bps, (
            f"distance_to_poc_bps mismatch: expected {snapshot.distance_to_poc_bps}, "
            f"got {serialized['distance_to_poc_bps']}"
        )
        assert serialized["distance_to_vah_bps"] == snapshot.distance_to_vah_bps, (
            f"distance_to_vah_bps mismatch: expected {snapshot.distance_to_vah_bps}, "
            f"got {serialized['distance_to_vah_bps']}"
        )
        assert serialized["distance_to_val_bps"] == snapshot.distance_to_val_bps, (
            f"distance_to_val_bps mismatch: expected {snapshot.distance_to_val_bps}, "
            f"got {serialized['distance_to_val_bps']}"
        )
        assert serialized["rotation_factor"] == snapshot.rotation_factor, (
            f"rotation_factor mismatch: expected {snapshot.rotation_factor}, "
            f"got {serialized['rotation_factor']}"
        )
    
    @given(snapshot=market_snapshot_strategy())
    @settings(max_examples=100)
    def test_property_5_serialization_is_deterministic(self, snapshot: MarketSnapshot):
        """Property 5: Serialization is deterministic.
        
        *For any* MarketSnapshot, calling to_dict() multiple times SHALL
        return identical results.
        
        Feature: amt-fields-in-decision-events, Property 5: AMT Fields Persistence Round-Trip
        **Validates: Requirements 6.1, 6.2, 6.3, 6.4**
        """
        # Serialize multiple times
        serialized1 = snapshot.to_dict()
        serialized2 = snapshot.to_dict()
        serialized3 = snapshot.to_dict()
        
        # All serializations should be identical
        assert serialized1 == serialized2, "Serialization is not deterministic (1 vs 2)"
        assert serialized2 == serialized3, "Serialization is not deterministic (2 vs 3)"

    
    @given(snapshot=market_snapshot_strategy())
    @settings(max_examples=100)
    def test_property_5_all_amt_fields_present_in_serialized(
        self, snapshot: MarketSnapshot
    ):
        """Property 5: All AMT fields are present in serialized output.
        
        *For any* MarketSnapshot, the serialized dict SHALL contain all
        required AMT field keys.
        
        Feature: amt-fields-in-decision-events, Property 5: AMT Fields Persistence Round-Trip
        **Validates: Requirements 6.1, 6.2, 6.3, 6.4**
        """
        serialized = snapshot.to_dict()
        
        # All AMT field keys must be present (using _bps suffix per Requirement 2.3)
        required_amt_keys = [
            "poc_price",
            "vah_price",
            "val_price",
            "position_in_value",
            "distance_to_poc_bps",
            "distance_to_vah_bps",
            "distance_to_val_bps",
            "rotation_factor",
        ]
        
        for key in required_amt_keys:
            assert key in serialized, f"Missing required AMT field: {key}"


class TestAMTFieldsRoundTripEdgeCases:
    """Property tests for edge cases in AMT fields round-trip.
    
    Feature: amt-fields-in-decision-events
    Property 5: AMT Fields Persistence Round-Trip
    **Validates: Requirements 6.1, 6.2, 6.3, 6.4, 7.5**
    """
    
    @given(
        poc_price=amt_level_strategy,
        vah_price=amt_level_strategy,
        val_price=amt_level_strategy,
    )
    @settings(max_examples=100)
    def test_property_5_amt_levels_preserved_exactly(
        self, poc_price: float, vah_price: float, val_price: float
    ):
        """Property 5: AMT levels are preserved exactly.
        
        *For any* AMT level values, serialization SHALL preserve the exact
        floating-point values without loss of precision.
        
        Feature: amt-fields-in-decision-events, Property 5: AMT Fields Persistence Round-Trip
        **Validates: Requirements 6.1**
        """
        snapshot = MarketSnapshot(
            symbol="BTCUSDT",
            exchange="binance",
            timestamp_ns=1700000000000000000,
            snapshot_age_ms=10.0,
            mid_price=50000.0,
            bid=49999.0,
            ask=50001.0,
            spread_bps=4.0,
            bid_depth_usd=100000.0,
            ask_depth_usd=100000.0,
            depth_imbalance=0.0,
            imb_1s=0.0,
            imb_5s=0.0,
            imb_30s=0.0,
            orderflow_persistence_sec=0.0,
            rv_1s=0.001,
            rv_10s=0.001,
            rv_1m=0.001,
            vol_shock=False,
            vol_regime="normal",
            vol_regime_score=0.5,
            trend_direction="neutral",
            trend_strength=0.0,
            poc_price=poc_price,
            vah_price=vah_price,
            val_price=val_price,
            position_in_value="inside",
            expected_fill_slippage_bps=1.0,
            typical_spread_bps=4.0,
            data_quality_score=1.0,
            ws_connected=True,
            distance_to_poc_bps=0.0,
            distance_to_vah_bps=0.0,
            distance_to_val_bps=0.0,
            rotation_factor=0.0,
        )
        
        serialized = snapshot.to_dict()
        
        # Exact preservation of floating-point values
        assert serialized["poc_price"] == poc_price
        assert serialized["vah_price"] == vah_price
        assert serialized["val_price"] == val_price

    
    @given(
        distance_to_poc_bps=distance_strategy,
        distance_to_vah_bps=absolute_distance_strategy,
        distance_to_val_bps=absolute_distance_strategy,
    )
    @settings(max_examples=100)
    def test_property_5_distance_fields_preserved_exactly(
        self,
        distance_to_poc_bps: float,
        distance_to_vah_bps: float,
        distance_to_val_bps: float,
    ):
        """Property 5: Distance fields are preserved exactly.
        
        *For any* distance values, serialization SHALL preserve the exact
        floating-point values without loss of precision.
        
        Feature: amt-fields-in-decision-events, Property 5: AMT Fields Persistence Round-Trip
        **Validates: Requirements 6.3**
        """
        snapshot = MarketSnapshot(
            symbol="BTCUSDT",
            exchange="binance",
            timestamp_ns=1700000000000000000,
            snapshot_age_ms=10.0,
            mid_price=50000.0,
            bid=49999.0,
            ask=50001.0,
            spread_bps=4.0,
            bid_depth_usd=100000.0,
            ask_depth_usd=100000.0,
            depth_imbalance=0.0,
            imb_1s=0.0,
            imb_5s=0.0,
            imb_30s=0.0,
            orderflow_persistence_sec=0.0,
            rv_1s=0.001,
            rv_10s=0.001,
            rv_1m=0.001,
            vol_shock=False,
            vol_regime="normal",
            vol_regime_score=0.5,
            trend_direction="neutral",
            trend_strength=0.0,
            poc_price=50000.0,
            vah_price=50500.0,
            val_price=49500.0,
            position_in_value="inside",
            expected_fill_slippage_bps=1.0,
            typical_spread_bps=4.0,
            data_quality_score=1.0,
            ws_connected=True,
            distance_to_poc_bps=distance_to_poc_bps,
            distance_to_vah_bps=distance_to_vah_bps,
            distance_to_val_bps=distance_to_val_bps,
            rotation_factor=0.0,
        )
        
        serialized = snapshot.to_dict()
        
        # Exact preservation of floating-point values (using _bps suffix per Requirement 2.3)
        assert serialized["distance_to_poc_bps"] == distance_to_poc_bps
        assert serialized["distance_to_vah_bps"] == distance_to_vah_bps
        assert serialized["distance_to_val_bps"] == distance_to_val_bps
    
    @given(rotation_factor=rotation_factor_strategy)
    @settings(max_examples=100)
    def test_property_5_rotation_factor_preserved_exactly(
        self, rotation_factor: float
    ):
        """Property 5: Rotation factor is preserved exactly.
        
        *For any* rotation factor value, serialization SHALL preserve the exact
        floating-point value without loss of precision.
        
        Feature: amt-fields-in-decision-events, Property 5: AMT Fields Persistence Round-Trip
        **Validates: Requirements 6.4**
        """
        snapshot = MarketSnapshot(
            symbol="BTCUSDT",
            exchange="binance",
            timestamp_ns=1700000000000000000,
            snapshot_age_ms=10.0,
            mid_price=50000.0,
            bid=49999.0,
            ask=50001.0,
            spread_bps=4.0,
            bid_depth_usd=100000.0,
            ask_depth_usd=100000.0,
            depth_imbalance=0.0,
            imb_1s=0.0,
            imb_5s=0.0,
            imb_30s=0.0,
            orderflow_persistence_sec=0.0,
            rv_1s=0.001,
            rv_10s=0.001,
            rv_1m=0.001,
            vol_shock=False,
            vol_regime="normal",
            vol_regime_score=0.5,
            trend_direction="neutral",
            trend_strength=0.0,
            poc_price=50000.0,
            vah_price=50500.0,
            val_price=49500.0,
            position_in_value="inside",
            expected_fill_slippage_bps=1.0,
            typical_spread_bps=4.0,
            data_quality_score=1.0,
            ws_connected=True,
            distance_to_poc_bps=0.0,
            distance_to_vah_bps=0.0,
            distance_to_val_bps=0.0,
            rotation_factor=rotation_factor,
        )
        
        serialized = snapshot.to_dict()
        
        # Exact preservation of floating-point value
        assert serialized["rotation_factor"] == rotation_factor

    
    @given(position_in_value=position_in_value_strategy)
    @settings(max_examples=100)
    def test_property_5_position_in_value_preserved_exactly(
        self, position_in_value: str
    ):
        """Property 5: Position in value is preserved exactly.
        
        *For any* position_in_value classification, serialization SHALL preserve
        the exact string value.
        
        Feature: amt-fields-in-decision-events, Property 5: AMT Fields Persistence Round-Trip
        **Validates: Requirements 6.2**
        """
        snapshot = MarketSnapshot(
            symbol="BTCUSDT",
            exchange="binance",
            timestamp_ns=1700000000000000000,
            snapshot_age_ms=10.0,
            mid_price=50000.0,
            bid=49999.0,
            ask=50001.0,
            spread_bps=4.0,
            bid_depth_usd=100000.0,
            ask_depth_usd=100000.0,
            depth_imbalance=0.0,
            imb_1s=0.0,
            imb_5s=0.0,
            imb_30s=0.0,
            orderflow_persistence_sec=0.0,
            rv_1s=0.001,
            rv_10s=0.001,
            rv_1m=0.001,
            vol_shock=False,
            vol_regime="normal",
            vol_regime_score=0.5,
            trend_direction="neutral",
            trend_strength=0.0,
            poc_price=50000.0,
            vah_price=50500.0,
            val_price=49500.0,
            position_in_value=position_in_value,
            expected_fill_slippage_bps=1.0,
            typical_spread_bps=4.0,
            data_quality_score=1.0,
            ws_connected=True,
            distance_to_poc_bps=0.0,
            distance_to_vah_bps=0.0,
            distance_to_val_bps=0.0,
            rotation_factor=0.0,
        )
        
        serialized = snapshot.to_dict()
        
        # Exact preservation of string value
        assert serialized["position_in_value"] == position_in_value
    
    @given(snapshot=market_snapshot_strategy())
    @settings(max_examples=100)
    def test_property_5_serialized_dict_is_json_serializable(
        self, snapshot: MarketSnapshot
    ):
        """Property 5: Serialized dict is JSON serializable.
        
        *For any* MarketSnapshot, the serialized dict SHALL be JSON serializable
        for storage in decision_events payload.
        
        Feature: amt-fields-in-decision-events, Property 5: AMT Fields Persistence Round-Trip
        **Validates: Requirements 6.1, 6.2, 6.3, 6.4**
        """
        import json
        
        serialized = snapshot.to_dict()
        
        # Should not raise an exception
        json_str = json.dumps(serialized)
        
        # Should be able to deserialize back
        deserialized = json.loads(json_str)
        
        # AMT fields should be preserved through JSON round-trip (using _bps suffix per Requirement 2.3)
        assert deserialized["poc_price"] == serialized["poc_price"]
        assert deserialized["vah_price"] == serialized["vah_price"]
        assert deserialized["val_price"] == serialized["val_price"]
        assert deserialized["position_in_value"] == serialized["position_in_value"]
        assert deserialized["distance_to_poc_bps"] == serialized["distance_to_poc_bps"]
        assert deserialized["distance_to_vah_bps"] == serialized["distance_to_vah_bps"]
        assert deserialized["distance_to_val_bps"] == serialized["distance_to_val_bps"]
        assert deserialized["rotation_factor"] == serialized["rotation_factor"]
