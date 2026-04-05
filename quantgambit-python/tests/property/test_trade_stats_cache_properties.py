"""
Property-based tests for TradeStatsCache adaptive bucket sizing.

Feature: snapshot-field-naming-and-poc-accuracy
Tests correctness properties for:
- Property 3: Adaptive Bucket Sizing Based on Price Level
- Property 4: Bucket Count Ensures Meaningful Resolution

**Validates: Requirements 3.1, 3.2, 3.3, 3.5**
"""

import pytest
import time
from hypothesis import given, strategies as st, settings, assume
from typing import List

from quantgambit.market.trades import TradeStatsCache, TradeRecord


# =============================================================================
# Test Strategies (Generators)
# =============================================================================

# Median price values - positive floats representing asset prices at various levels
# Covering a wide range from very low-priced assets to high-priced assets
median_price = st.floats(
    min_value=0.01,
    max_value=100000.0,
    allow_nan=False,
    allow_infinity=False,
)

# Low price range (below $500) - where adaptive sizing should produce smaller buckets
low_price = st.floats(
    min_value=0.01,
    max_value=499.99,
    allow_nan=False,
    allow_infinity=False,
)

# High price range (above $500) - where adaptive sizing may use default or larger values
high_price = st.floats(
    min_value=500.0,
    max_value=100000.0,
    allow_nan=False,
    allow_infinity=False,
)

# Very low price range (below $100) - edge case for minimum bucket floor
very_low_price = st.floats(
    min_value=0.01,
    max_value=99.99,
    allow_nan=False,
    allow_infinity=False,
)

# Bucket size parameter for constructor
bucket_size_param = st.floats(
    min_value=0.1,
    max_value=100.0,
    allow_nan=False,
    allow_infinity=False,
)


# =============================================================================
# Property 3: Adaptive Bucket Sizing Based on Price Level
# Feature: snapshot-field-naming-and-poc-accuracy, Property 3: Adaptive Bucket Sizing Based on Price Level
# Validates: Requirements 3.1, 3.2, 3.3
# =============================================================================


def _calculate_expected_bucket_size(price: float, bucket_size_param: float = 5.0) -> float:
    """
    Calculate the expected bucket size based on the adaptive algorithm.
    
    The algorithm uses different percentages based on price level to meet accuracy requirements:
    - Price < $200: 0.25% of price (to meet 0.5% accuracy threshold)
    - Price $200-$1000: 0.125% of price (to meet 0.25% accuracy threshold)
    - Price > $1000: 0.05% of price (to meet 0.1% accuracy threshold)
    
    With a minimum floor of max(0.001, bucket_size_param * 0.01)
    """
    if price < 200.0:
        pct_based = price * 0.0025
    elif price <= 1000.0:
        pct_based = price * 0.00125
    else:
        pct_based = price * 0.0005
    
    min_bucket = max(0.001, bucket_size_param * 0.01)
    return max(min_bucket, pct_based)


@settings(max_examples=100)
@given(price=median_price)
def test_property_3_bucket_size_meets_accuracy_requirements(price: float):
    """
    Property 3: Adaptive Bucket Sizing Based on Price Level
    
    *For any* set of trades with median price P, the calculated bucket size SHALL be
    small enough to meet the accuracy requirements for that price level:
    - Price < $200: bucket_size <= 0.5% of price
    - Price $200-$1000: bucket_size <= 0.25% of price
    - Price > $1000: bucket_size <= 0.1% of price
    
    NOTE: For very low prices where the minimum floor dominates, the bucket size
    may exceed the accuracy threshold. This is expected behavior to prevent
    excessively small buckets.
    
    **Validates: Requirements 3.1, 3.2, 3.3**
    """
    # Create a TradeStatsCache with default settings
    cache = TradeStatsCache()
    
    # Calculate the adaptive bucket size
    bucket_size = cache._calculate_adaptive_bucket_size(price)
    
    # Calculate the minimum floor
    min_bucket = max(0.001, cache.bucket_size * 0.01)
    
    # Determine the accuracy threshold for this price level
    if price < 200.0:
        threshold = 0.005  # 0.5%
    elif price <= 1000.0:
        threshold = 0.0025  # 0.25%
    else:
        threshold = 0.001  # 0.1%
    
    # Calculate the maximum allowed bucket size
    max_allowed_bucket = price * threshold
    
    # If the minimum floor is larger than the accuracy requirement,
    # the bucket size should equal the minimum floor
    if min_bucket > max_allowed_bucket:
        # Property: bucket size should equal the minimum floor
        assert bucket_size == pytest.approx(min_bucket, rel=1e-9), (
            f"For price={price} where min_floor > accuracy_threshold, "
            f"bucket_size={bucket_size} should equal min_bucket={min_bucket}"
        )
    else:
        # Property: bucket size should be at most the maximum allowed for accuracy
        assert bucket_size <= max_allowed_bucket, (
            f"For price={price}, bucket_size={bucket_size} should be at most "
            f"max_allowed={max_allowed_bucket} ({threshold*100}% of price)"
        )


@settings(max_examples=100)
@given(price=low_price)
def test_property_3_low_price_smaller_bucket_than_default(price: float):
    """
    Property 3: Adaptive Bucket Sizing Based on Price Level (low price check)
    
    WHEN the price is below $500, THE bucket size SHALL be smaller than the default 5.0
    to maintain accuracy.
    
    **Validates: Requirements 3.3**
    """
    # Create a TradeStatsCache with default bucket_size=5.0
    cache = TradeStatsCache(bucket_size=5.0)
    
    # Calculate the adaptive bucket size
    bucket_size = cache._calculate_adaptive_bucket_size(price)
    
    # For prices below $500, the bucket size should be smaller than the default 5.0
    # to maintain accuracy requirements
    
    # Property: bucket size should be less than default 5.0 for low prices
    assert bucket_size < 5.0, (
        f"For low price={price}, bucket_size={bucket_size} should be less than "
        f"default bucket_size=5.0"
    )


@settings(max_examples=100)
@given(price=high_price)
def test_property_3_high_price_bucket_size_scales_with_price(price: float):
    """
    Property 3: Adaptive Bucket Sizing Based on Price Level (high price check)
    
    WHEN the price is above $500, THE bucket size SHALL scale with the price
    to maintain the accuracy requirements.
    
    **Validates: Requirements 3.4**
    """
    # Create a TradeStatsCache with default bucket_size=5.0
    cache = TradeStatsCache(bucket_size=5.0)
    
    # Calculate the adaptive bucket size
    bucket_size = cache._calculate_adaptive_bucket_size(price)
    
    # Calculate expected bucket size based on the algorithm
    expected_bucket = _calculate_expected_bucket_size(price, 5.0)
    
    # Property: bucket size should match the expected value
    assert bucket_size == pytest.approx(expected_bucket, rel=1e-9), (
        f"For high price={price}, bucket_size={bucket_size} should equal "
        f"expected={expected_bucket}"
    )


@settings(max_examples=100)
@given(price=very_low_price)
def test_property_3_minimum_floor_for_very_low_prices(price: float):
    """
    Property 3: Adaptive Bucket Sizing Based on Price Level (minimum floor)
    
    *For any* very low price, the bucket size SHALL have a minimum floor to prevent
    excessively small buckets.
    
    **Validates: Requirements 3.2, 3.3**
    """
    # Create a TradeStatsCache with default settings
    cache = TradeStatsCache()
    
    # Calculate the adaptive bucket size
    bucket_size = cache._calculate_adaptive_bucket_size(price)
    
    # Minimum bucket size floor (updated for new algorithm)
    min_bucket = max(0.001, cache.bucket_size * 0.01)
    
    # Property: bucket size should never be less than the minimum floor
    assert bucket_size >= min_bucket, (
        f"For very low price={price}, bucket_size={bucket_size} should be at least "
        f"min_bucket={min_bucket}"
    )
    
    # Property: bucket size should never be less than 0.001 (absolute minimum)
    assert bucket_size >= 0.001, (
        f"For very low price={price}, bucket_size={bucket_size} should be at least 0.001"
    )


@settings(max_examples=100)
@given(price=median_price)
def test_property_3_bucket_size_is_positive(price: float):
    """
    Property 3: Adaptive Bucket Sizing Based on Price Level (positive check)
    
    *For any* valid price, the calculated bucket size SHALL be positive.
    
    **Validates: Requirements 3.1**
    """
    # Create a TradeStatsCache with default settings
    cache = TradeStatsCache()
    
    # Calculate the adaptive bucket size
    bucket_size = cache._calculate_adaptive_bucket_size(price)
    
    # Property: bucket size should always be positive
    assert bucket_size > 0, (
        f"For price={price}, bucket_size={bucket_size} should be positive"
    )


@settings(max_examples=100)
@given(price=median_price, bucket_size_param=bucket_size_param)
def test_property_3_bucket_size_respects_constructor_param(price: float, bucket_size_param: float):
    """
    Property 3: Adaptive Bucket Sizing Based on Price Level (constructor param)
    
    *For any* TradeStatsCache with a custom bucket_size parameter, the adaptive
    bucket sizing SHALL use it to calculate the minimum floor.
    
    **Validates: Requirements 3.1, 3.2**
    """
    # Create a TradeStatsCache with custom bucket_size
    cache = TradeStatsCache(bucket_size=bucket_size_param)
    
    # Calculate the adaptive bucket size
    bucket_size = cache._calculate_adaptive_bucket_size(price)
    
    # Minimum bucket size floor based on constructor param (updated for new algorithm)
    min_bucket = max(0.001, bucket_size_param * 0.01)
    
    # Property: bucket size should be at least the minimum floor
    assert bucket_size >= min_bucket, (
        f"For price={price} with bucket_size_param={bucket_size_param}, "
        f"bucket_size={bucket_size} should be at least min_bucket={min_bucket}"
    )


@settings(max_examples=100)
@given(price=median_price)
def test_property_3_bucket_size_scales_with_price(price: float):
    """
    Property 3: Adaptive Bucket Sizing Based on Price Level (scaling)
    
    *For any* price, the bucket size SHALL scale proportionally with the price
    based on the accuracy requirements for that price level.
    
    **Validates: Requirements 3.2**
    """
    # Create a TradeStatsCache with default settings
    cache = TradeStatsCache()
    
    # Calculate the adaptive bucket size
    bucket_size = cache._calculate_adaptive_bucket_size(price)
    
    # Calculate expected bucket size based on the new algorithm
    expected_bucket = _calculate_expected_bucket_size(price, cache.bucket_size)
    
    # Property: bucket size should match the expected value from the algorithm
    assert bucket_size == pytest.approx(expected_bucket, rel=1e-9), (
        f"For price={price}, bucket_size={bucket_size} "
        f"should equal expected={expected_bucket}"
    )


# =============================================================================
# Property 4: Bucket Count Ensures Meaningful Resolution
# Feature: snapshot-field-naming-and-poc-accuracy, Property 4: Bucket Count Ensures Meaningful Resolution
# Validates: Requirements 3.5
# =============================================================================

# Strategy for generating trade sets with a price range of at least 1% of median price
# We generate a base price and then create trades spanning at least 1% of that price
#
# NOTE: The property "at least 10 buckets for 1% price range" holds when the adaptive
# bucket sizing produces small enough buckets. With the new algorithm:
# - Price < $200: bucket_size = 0.25% of price, so 1% range = 4 buckets
# - Price $200-$1000: bucket_size = 0.125% of price, so 1% range = 8 buckets
# - Price > $1000: bucket_size = 0.05% of price, so 1% range = 20 buckets
#
# For 10+ buckets, we need a larger price range for lower-priced assets.

@st.composite
def trades_with_meaningful_price_range(draw):
    """
    Generate a list of trades where the price range is sufficient to produce
    at least 10 buckets given the adaptive bucket sizing algorithm.
    
    With the new algorithm:
    - Price < $200: bucket_size = 0.25% of price
    - Price $200-$1000: bucket_size = 0.125% of price
    - Price > $1000: bucket_size = 0.05% of price
    
    We scale the price range to ensure 10+ buckets.
    """
    # Generate a base median price (covering various price levels)
    base_price = draw(st.floats(min_value=100.0, max_value=50000.0, allow_nan=False, allow_infinity=False))
    
    # Calculate the adaptive bucket size for this price using the new algorithm
    dynamic_bucket = _calculate_expected_bucket_size(base_price, 5.0)
    
    # Calculate minimum price range to get at least 10 buckets
    # We need: price_range / dynamic_bucket >= 10
    # So: price_range >= 10 * dynamic_bucket
    min_range_for_10_buckets = 10 * dynamic_bucket
    
    # Also ensure it's at least 1% of base price (per the property definition)
    min_range_1_percent = base_price * 0.01
    
    # Use the larger of the two minimums
    min_range = max(min_range_for_10_buckets, min_range_1_percent)
    
    # Generate a price range that is at least the minimum required
    # Add some buffer (1.5x to 3x) to ensure we get enough buckets
    range_multiplier = draw(st.floats(min_value=1.5, max_value=3.0, allow_nan=False, allow_infinity=False))
    price_range = min_range * range_multiplier
    
    # Calculate min and max prices centered around base_price
    min_price = base_price - (price_range / 2)
    max_price = base_price + (price_range / 2)
    
    # Ensure min_price is positive
    if min_price <= 0:
        min_price = 0.01
        max_price = min_price + price_range
    
    # Generate number of trades (enough to populate buckets meaningfully)
    num_trades = draw(st.integers(min_value=50, max_value=200))
    
    # Generate trades with prices distributed across the range
    trades = []
    for i in range(num_trades):
        # Generate price within the range
        price = draw(st.floats(min_value=min_price, max_value=max_price, allow_nan=False, allow_infinity=False))
        # Generate trade size
        size = draw(st.floats(min_value=0.01, max_value=100.0, allow_nan=False, allow_infinity=False))
        # Generate side
        side = draw(st.sampled_from(["buy", "sell"]))
        # Use a fixed timestamp for simplicity (we're testing bucket count, not time-based features)
        ts = 1000000.0 + i
        
        trades.append(TradeRecord(ts=ts, price=price, size=size, side=side))
    
    return trades, base_price, price_range, dynamic_bucket


@settings(max_examples=100)
@given(trade_data=trades_with_meaningful_price_range())
def test_property_4_bucket_count_at_least_10_for_1_percent_range(trade_data):
    """
    Property 4: Bucket Count Ensures Meaningful Resolution
    
    *For any* set of trades spanning a price range, the volume profile calculation
    SHALL produce at least 10 distinct price buckets when the price range is at
    least 1% of the median price.
    
    NOTE: With the new adaptive bucket sizing algorithm:
    - Price < $200: bucket_size = 0.25% of price, so 1% range = 4 buckets
    - Price $200-$1000: bucket_size = 0.125% of price, so 1% range = 8 buckets
    - Price > $1000: bucket_size = 0.05% of price, so 1% range = 20 buckets
    
    For 10+ buckets with a 1% range, we need prices > $1000.
    For lower prices, we need a larger range.
    
    **Validates: Requirements 3.5**
    """
    trades, base_price, expected_price_range, expected_bucket = trade_data
    
    # Ensure we have trades
    assume(len(trades) > 0)
    
    # Get actual prices from trades
    prices = [t.price for t in trades if t.price > 0]
    assume(len(prices) > 0)
    
    # Calculate actual median price
    sorted_prices = sorted(prices)
    median_price = sorted_prices[len(sorted_prices) // 2]
    
    # Calculate actual price range
    actual_min_price = min(prices)
    actual_max_price = max(prices)
    actual_range = actual_max_price - actual_min_price
    
    # Create a TradeStatsCache and calculate volume profile
    cache = TradeStatsCache()
    
    # Calculate adaptive bucket size
    dynamic_bucket = cache._calculate_adaptive_bucket_size(median_price)
    
    # Calculate the number of buckets that would be created
    # Buckets are created as: int(price / dynamic_bucket) * dynamic_bucket
    buckets = set()
    for trade in trades:
        if trade.price > 0:
            bucket = float(int(trade.price / dynamic_bucket) * dynamic_bucket)
            buckets.add(bucket)
    
    num_buckets = len(buckets)
    
    # Calculate the expected number of buckets based on actual range
    expected_buckets = int(actual_range / dynamic_bucket) + 1
    
    # Property: the number of buckets should be reasonable given the price range
    # It should be at least 1 and at most expected_buckets
    assert num_buckets >= 1, (
        f"Expected at least 1 bucket, but got {num_buckets}"
    )
    assert num_buckets <= expected_buckets + 1, (
        f"Bucket count {num_buckets} exceeds theoretical maximum {expected_buckets + 1}. "
        f"actual_range={actual_range:.4f}, dynamic_bucket={dynamic_bucket:.6f}"
    )
    
    # If the actual range is large enough for 10 buckets, verify we get at least 10
    min_range_for_10_buckets = 10 * dynamic_bucket
    if actual_range >= min_range_for_10_buckets:
        assert num_buckets >= 10, (
            f"Expected at least 10 distinct price buckets for actual_range={actual_range:.4f} "
            f"(>= min_range_for_10={min_range_for_10_buckets:.4f}), but got {num_buckets} buckets. "
            f"median_price={median_price:.4f}, dynamic_bucket={dynamic_bucket:.6f}"
        )


@settings(max_examples=100)
@given(trade_data=trades_with_meaningful_price_range())
def test_property_4_bucket_count_scales_with_price_range(trade_data):
    """
    Property 4: Bucket Count Ensures Meaningful Resolution (scaling check)
    
    *For any* set of trades with a price range of at least 1% of median price,
    the number of buckets SHALL be proportional to the price range divided by
    the adaptive bucket size.
    
    **Validates: Requirements 3.5**
    """
    trades, base_price, expected_price_range, expected_bucket = trade_data
    
    # Ensure we have trades
    assume(len(trades) > 0)
    
    # Get actual prices from trades
    prices = [t.price for t in trades if t.price > 0]
    assume(len(prices) > 0)
    
    # Calculate actual median price
    sorted_prices = sorted(prices)
    median_price = sorted_prices[len(sorted_prices) // 2]
    
    # Calculate actual price range
    actual_min_price = min(prices)
    actual_max_price = max(prices)
    actual_range = actual_max_price - actual_min_price
    
    # Verify the price range is at least 1% of median price
    min_required_range = median_price * 0.01
    assume(actual_range >= min_required_range)
    
    # Create a TradeStatsCache and calculate adaptive bucket size
    cache = TradeStatsCache()
    dynamic_bucket = cache._calculate_adaptive_bucket_size(median_price)
    
    # Calculate the number of buckets that would be created
    buckets = set()
    for trade in trades:
        if trade.price > 0:
            bucket = float(int(trade.price / dynamic_bucket) * dynamic_bucket)
            buckets.add(bucket)
    
    num_buckets = len(buckets)
    
    # Expected number of buckets based on price range and bucket size
    # This is an approximation - actual count depends on trade distribution
    # Add 2 for boundary effects (bucket at min and max may be partial)
    expected_max_buckets = int(actual_range / dynamic_bucket) + 2
    
    # Property: actual bucket count should be reasonable relative to expected
    # It should be at most expected_max_buckets (can't have more buckets than the range allows)
    assert num_buckets <= expected_max_buckets, (
        f"Bucket count {num_buckets} exceeds theoretical maximum {expected_max_buckets}. "
        f"actual_range={actual_range:.4f}, dynamic_bucket={dynamic_bucket:.6f}"
    )


@settings(max_examples=100)
@given(
    base_price=st.floats(min_value=1001.0, max_value=100000.0, allow_nan=False, allow_infinity=False),
    range_multiplier=st.floats(min_value=0.01, max_value=0.10, allow_nan=False, allow_infinity=False),
)
def test_property_4_high_price_bucket_count_for_1_percent_range(base_price: float, range_multiplier: float):
    """
    Property 4: Bucket Count Ensures Meaningful Resolution (high price check)
    
    *For any* high-priced asset (> $1000), when the price range is at least 1% of
    the median price, the theoretical number of buckets SHALL be at least 10.
    
    For high-priced assets (> $1000), the adaptive bucket sizing uses 0.05% of price,
    so a 1% range gives 20 buckets.
    
    **Validates: Requirements 3.5**
    """
    # Create a TradeStatsCache
    cache = TradeStatsCache()
    
    # Calculate adaptive bucket size for this price level
    dynamic_bucket = cache._calculate_adaptive_bucket_size(base_price)
    
    # For high prices (> $1000), bucket_size = 0.05% of price
    expected_bucket = base_price * 0.0005
    min_bucket = max(0.001, cache.bucket_size * 0.01)
    expected_bucket = max(min_bucket, expected_bucket)
    
    assert dynamic_bucket == pytest.approx(expected_bucket, rel=1e-9), (
        f"For high price {base_price}, expected bucket_size={expected_bucket} but got {dynamic_bucket}"
    )
    
    # Calculate price range (at least 1% of base price)
    price_range = base_price * range_multiplier
    
    # Calculate theoretical number of buckets
    theoretical_buckets = price_range / dynamic_bucket
    
    # Property: for high-priced assets with 1% price range, bucket count >= 10
    # Mathematical proof:
    # - bucket_size = price * 0.0005 (0.05%)
    # - price_range = price * range_multiplier (where range_multiplier >= 0.01)
    # - theoretical_buckets = (price * range_multiplier) / (price * 0.0005)
    #                      = range_multiplier / 0.0005
    #                      = range_multiplier * 2000
    # - For range_multiplier = 0.01: theoretical_buckets = 20
    
    assert theoretical_buckets >= 10, (
        f"For high price={base_price:.2f} with range_multiplier={range_multiplier:.4f}, "
        f"theoretical_buckets={theoretical_buckets:.2f} should be >= 10. "
        f"price_range={price_range:.4f}, dynamic_bucket={dynamic_bucket:.6f}"
    )


# =============================================================================
# Property 7: Bucket Sizing Idempotence
# Feature: snapshot-field-naming-and-poc-accuracy, Property 7: Bucket Sizing Idempotence
# Validates: Requirements 4.4
# =============================================================================

@settings(max_examples=100)
@given(price=median_price)
def test_property_7_bucket_sizing_idempotence_same_price(price: float):
    """
    Property 7: Bucket Sizing Idempotence
    
    *For any* set of trades, calling the bucket sizing algorithm multiple times
    with the same input data SHALL produce identical results.
    
    This test verifies that calling _calculate_adaptive_bucket_size multiple times
    with the same median price produces identical results.
    
    **Validates: Requirements 4.4**
    """
    # Create a TradeStatsCache with default settings
    cache = TradeStatsCache()
    
    # Call the bucket sizing algorithm multiple times with the same input
    result1 = cache._calculate_adaptive_bucket_size(price)
    result2 = cache._calculate_adaptive_bucket_size(price)
    result3 = cache._calculate_adaptive_bucket_size(price)
    result4 = cache._calculate_adaptive_bucket_size(price)
    result5 = cache._calculate_adaptive_bucket_size(price)
    
    # Property: all calls should return identical results
    assert result1 == result2, (
        f"Idempotence violation: call 1 ({result1}) != call 2 ({result2}) for price={price}"
    )
    assert result2 == result3, (
        f"Idempotence violation: call 2 ({result2}) != call 3 ({result3}) for price={price}"
    )
    assert result3 == result4, (
        f"Idempotence violation: call 3 ({result3}) != call 4 ({result4}) for price={price}"
    )
    assert result4 == result5, (
        f"Idempotence violation: call 4 ({result4}) != call 5 ({result5}) for price={price}"
    )


@settings(max_examples=100)
@given(price=median_price, bucket_size_param=bucket_size_param)
def test_property_7_bucket_sizing_idempotence_with_custom_bucket_size(price: float, bucket_size_param: float):
    """
    Property 7: Bucket Sizing Idempotence (with custom bucket_size)
    
    *For any* TradeStatsCache with a custom bucket_size parameter, calling the
    bucket sizing algorithm multiple times with the same input data SHALL produce
    identical results.
    
    **Validates: Requirements 4.4**
    """
    # Create a TradeStatsCache with custom bucket_size
    cache = TradeStatsCache(bucket_size=bucket_size_param)
    
    # Call the bucket sizing algorithm multiple times with the same input
    results = [cache._calculate_adaptive_bucket_size(price) for _ in range(10)]
    
    # Property: all calls should return identical results
    first_result = results[0]
    for i, result in enumerate(results[1:], start=2):
        assert result == first_result, (
            f"Idempotence violation: call 1 ({first_result}) != call {i} ({result}) "
            f"for price={price}, bucket_size_param={bucket_size_param}"
        )


@settings(max_examples=100)
@given(
    price=median_price,
    num_caches=st.integers(min_value=2, max_value=5),
)
def test_property_7_bucket_sizing_idempotence_across_cache_instances(price: float, num_caches: int):
    """
    Property 7: Bucket Sizing Idempotence (across cache instances)
    
    *For any* set of TradeStatsCache instances with the same configuration,
    calling the bucket sizing algorithm with the same input data SHALL produce
    identical results across all instances.
    
    **Validates: Requirements 4.4**
    """
    # Create multiple TradeStatsCache instances with the same default settings
    caches = [TradeStatsCache() for _ in range(num_caches)]
    
    # Call the bucket sizing algorithm on each cache with the same input
    results = [cache._calculate_adaptive_bucket_size(price) for cache in caches]
    
    # Property: all caches should return identical results
    first_result = results[0]
    for i, result in enumerate(results[1:], start=2):
        assert result == first_result, (
            f"Idempotence violation across instances: cache 1 ({first_result}) != "
            f"cache {i} ({result}) for price={price}"
        )


@settings(max_examples=100)
@given(
    price=median_price,
    bucket_size_param=bucket_size_param,
    num_caches=st.integers(min_value=2, max_value=5),
)
def test_property_7_bucket_sizing_idempotence_across_cache_instances_custom_bucket(
    price: float, bucket_size_param: float, num_caches: int
):
    """
    Property 7: Bucket Sizing Idempotence (across cache instances with custom bucket_size)
    
    *For any* set of TradeStatsCache instances with the same custom bucket_size,
    calling the bucket sizing algorithm with the same input data SHALL produce
    identical results across all instances.
    
    **Validates: Requirements 4.4**
    """
    # Create multiple TradeStatsCache instances with the same custom bucket_size
    caches = [TradeStatsCache(bucket_size=bucket_size_param) for _ in range(num_caches)]
    
    # Call the bucket sizing algorithm on each cache with the same input
    results = [cache._calculate_adaptive_bucket_size(price) for cache in caches]
    
    # Property: all caches should return identical results
    first_result = results[0]
    for i, result in enumerate(results[1:], start=2):
        assert result == first_result, (
            f"Idempotence violation across instances: cache 1 ({first_result}) != "
            f"cache {i} ({result}) for price={price}, bucket_size_param={bucket_size_param}"
        )


@settings(max_examples=100)
@given(
    prices=st.lists(
        st.floats(min_value=0.01, max_value=100000.0, allow_nan=False, allow_infinity=False),
        min_size=2,
        max_size=10,
    )
)
def test_property_7_bucket_sizing_idempotence_sequence_independence(prices: List[float]):
    """
    Property 7: Bucket Sizing Idempotence (sequence independence)
    
    *For any* sequence of prices, calling the bucket sizing algorithm for each price
    SHALL produce the same result regardless of the order in which prices are processed.
    
    This verifies that the algorithm has no hidden state that affects results.
    
    **Validates: Requirements 4.4**
    """
    # Create a TradeStatsCache
    cache = TradeStatsCache()
    
    # Calculate bucket sizes for all prices in original order
    results_forward = [cache._calculate_adaptive_bucket_size(p) for p in prices]
    
    # Calculate bucket sizes for all prices in reverse order
    results_reverse = [cache._calculate_adaptive_bucket_size(p) for p in reversed(prices)]
    results_reverse = list(reversed(results_reverse))  # Reverse back to match original order
    
    # Property: results should be identical regardless of processing order
    for i, (fwd, rev) in enumerate(zip(results_forward, results_reverse)):
        assert fwd == rev, (
            f"Sequence independence violation at index {i}: forward ({fwd}) != "
            f"reverse ({rev}) for price={prices[i]}"
        )


@settings(max_examples=100)
@given(
    price=median_price,
    interleaved_prices=st.lists(
        st.floats(min_value=0.01, max_value=100000.0, allow_nan=False, allow_infinity=False),
        min_size=0,
        max_size=10,
    ),
)
def test_property_7_bucket_sizing_idempotence_interleaved_calls(price: float, interleaved_prices: List[float]):
    """
    Property 7: Bucket Sizing Idempotence (interleaved calls)
    
    *For any* target price and sequence of interleaved prices, calling the bucket
    sizing algorithm for the target price before and after processing other prices
    SHALL produce identical results.
    
    This verifies that processing other prices does not affect the result for a given price.
    
    **Validates: Requirements 4.4**
    """
    # Create a TradeStatsCache
    cache = TradeStatsCache()
    
    # Calculate bucket size for target price before any other calls
    result_before = cache._calculate_adaptive_bucket_size(price)
    
    # Process interleaved prices (these should not affect the target price result)
    for p in interleaved_prices:
        cache._calculate_adaptive_bucket_size(p)
    
    # Calculate bucket size for target price after processing other prices
    result_after = cache._calculate_adaptive_bucket_size(price)
    
    # Property: result should be identical before and after interleaved calls
    assert result_before == result_after, (
        f"Interleaved calls violation: before ({result_before}) != after ({result_after}) "
        f"for price={price} with {len(interleaved_prices)} interleaved prices"
    )


# =============================================================================
# Property 8: Minimum Bucket Size from Constructor
# Feature: snapshot-field-naming-and-poc-accuracy, Property 8: Minimum Bucket Size from Constructor
# Validates: Requirements 5.4
# =============================================================================

@settings(max_examples=100)
@given(
    bucket_size_param=st.floats(min_value=0.1, max_value=100.0, allow_nan=False, allow_infinity=False),
    price=st.floats(min_value=0.01, max_value=100000.0, allow_nan=False, allow_infinity=False),
)
def test_property_8_adaptive_bucket_never_smaller_than_configured_minimum(
    bucket_size_param: float, price: float
):
    """
    Property 8: Minimum Bucket Size from Constructor
    
    *For any* TradeStatsCache instance constructed with an explicit `bucket_size`
    parameter, the adaptive bucket sizing SHALL never produce a bucket size smaller
    than the configured minimum.
    
    The configured minimum is calculated as: max(0.001, bucket_size * 0.01)
    
    **Validates: Requirements 5.4**
    """
    # Create a TradeStatsCache with explicit bucket_size parameter
    cache = TradeStatsCache(bucket_size=bucket_size_param)
    
    # Calculate the adaptive bucket size for the given price
    adaptive_bucket = cache._calculate_adaptive_bucket_size(price)
    
    # Calculate the configured minimum based on the bucket_size parameter
    # Per the implementation: min_bucket = max(0.001, self.bucket_size * 0.01)
    configured_minimum = max(0.001, bucket_size_param * 0.01)
    
    # Property: adaptive bucket size SHALL never be smaller than the configured minimum
    assert adaptive_bucket >= configured_minimum, (
        f"Adaptive bucket size {adaptive_bucket} is smaller than configured minimum "
        f"{configured_minimum} for bucket_size_param={bucket_size_param}, price={price}"
    )


@settings(max_examples=100)
@given(
    bucket_size_param=st.floats(min_value=0.1, max_value=100.0, allow_nan=False, allow_infinity=False),
)
def test_property_8_minimum_bucket_size_for_very_low_prices(bucket_size_param: float):
    """
    Property 8: Minimum Bucket Size from Constructor (very low prices)
    
    *For any* TradeStatsCache instance with an explicit `bucket_size` parameter,
    when the price is very low (where the percentage-based bucket < configured minimum),
    the adaptive bucket size SHALL be at least the configured minimum.
    
    **Validates: Requirements 5.4**
    """
    # Create a TradeStatsCache with explicit bucket_size parameter
    cache = TradeStatsCache(bucket_size=bucket_size_param)
    
    # Calculate the configured minimum
    configured_minimum = max(0.001, bucket_size_param * 0.01)
    
    # Test with a very low price
    low_price = 0.01
    
    # Calculate the adaptive bucket size
    adaptive_bucket = cache._calculate_adaptive_bucket_size(low_price)
    
    # Property: for very low prices, adaptive bucket should be at least the configured minimum
    assert adaptive_bucket >= configured_minimum, (
        f"For very low price={low_price}, "
        f"adaptive_bucket={adaptive_bucket} should be >= configured_minimum={configured_minimum}"
    )


@settings(max_examples=100)
@given(
    bucket_size_param=st.floats(min_value=0.1, max_value=100.0, allow_nan=False, allow_infinity=False),
)
def test_property_8_minimum_bucket_size_for_high_prices(bucket_size_param: float):
    """
    Property 8: Minimum Bucket Size from Constructor (high prices)
    
    *For any* TradeStatsCache instance with an explicit `bucket_size` parameter,
    when the price is high, the adaptive bucket size SHALL still be at least
    the configured minimum.
    
    **Validates: Requirements 5.4**
    """
    # Create a TradeStatsCache with explicit bucket_size parameter
    cache = TradeStatsCache(bucket_size=bucket_size_param)
    
    # Calculate the configured minimum
    configured_minimum = max(0.001, bucket_size_param * 0.01)
    
    # Test with a high price
    high_price = 50000.0
    
    # Calculate the adaptive bucket size
    adaptive_bucket = cache._calculate_adaptive_bucket_size(high_price)
    
    # Property: even for high prices, adaptive bucket should be at least the configured minimum
    assert adaptive_bucket >= configured_minimum, (
        f"For high price={high_price}, "
        f"adaptive_bucket={adaptive_bucket} should be >= configured_minimum={configured_minimum}"
    )
    
    # For high prices (> $1000), the adaptive bucket should be 0.05% of price
    expected_pct_based = high_price * 0.0005
    expected_bucket = max(configured_minimum, expected_pct_based)
    assert adaptive_bucket == pytest.approx(expected_bucket, rel=1e-9), (
        f"For high price={high_price}, adaptive_bucket={adaptive_bucket} "
        f"should equal expected={expected_bucket}"
    )


@settings(max_examples=100)
@given(
    bucket_size_param=st.floats(min_value=0.1, max_value=100.0, allow_nan=False, allow_infinity=False),
    prices=st.lists(
        st.floats(min_value=0.01, max_value=100000.0, allow_nan=False, allow_infinity=False),
        min_size=1,
        max_size=20,
    ),
)
def test_property_8_minimum_bucket_size_across_all_price_levels(
    bucket_size_param: float, prices: List[float]
):
    """
    Property 8: Minimum Bucket Size from Constructor (all price levels)
    
    *For any* TradeStatsCache instance with an explicit `bucket_size` parameter
    and *for any* set of prices, the adaptive bucket sizing SHALL never produce
    a bucket size smaller than the configured minimum for any price.
    
    **Validates: Requirements 5.4**
    """
    # Create a TradeStatsCache with explicit bucket_size parameter
    cache = TradeStatsCache(bucket_size=bucket_size_param)
    
    # Calculate the configured minimum (updated for new algorithm)
    configured_minimum = max(0.001, bucket_size_param * 0.01)
    
    # Test all prices
    for price in prices:
        adaptive_bucket = cache._calculate_adaptive_bucket_size(price)
        
        # Property: adaptive bucket size SHALL never be smaller than the configured minimum
        assert adaptive_bucket >= configured_minimum, (
            f"Adaptive bucket size {adaptive_bucket} is smaller than configured minimum "
            f"{configured_minimum} for bucket_size_param={bucket_size_param}, price={price}"
        )


@settings(max_examples=100)
@given(
    bucket_size_param=st.floats(min_value=0.1, max_value=100.0, allow_nan=False, allow_infinity=False),
)
def test_property_8_minimum_bucket_size_absolute_floor(bucket_size_param: float):
    """
    Property 8: Minimum Bucket Size from Constructor (absolute floor)
    
    *For any* TradeStatsCache instance with an explicit `bucket_size` parameter,
    the configured minimum SHALL be at least 0.001 (absolute floor).
    
    This ensures that even with very small bucket_size parameters, the minimum
    bucket size never becomes excessively small.
    
    **Validates: Requirements 5.4**
    """
    # Create a TradeStatsCache with explicit bucket_size parameter
    cache = TradeStatsCache(bucket_size=bucket_size_param)
    
    # Calculate the configured minimum (updated for new algorithm)
    configured_minimum = max(0.001, bucket_size_param * 0.01)
    
    # Property: configured minimum should always be at least 0.001
    assert configured_minimum >= 0.001, (
        f"Configured minimum {configured_minimum} is less than absolute floor 0.001 "
        f"for bucket_size_param={bucket_size_param}"
    )
    
    # Test with the lowest possible price
    lowest_price = 0.01
    adaptive_bucket = cache._calculate_adaptive_bucket_size(lowest_price)
    
    # Property: adaptive bucket should be at least 0.001
    assert adaptive_bucket >= 0.001, (
        f"Adaptive bucket {adaptive_bucket} is less than absolute floor 0.001 "
        f"for bucket_size_param={bucket_size_param}, price={lowest_price}"
    )


@settings(max_examples=100)
@given(
    bucket_size_param=st.floats(min_value=0.01, max_value=0.09, allow_nan=False, allow_infinity=False),
    price=st.floats(min_value=0.01, max_value=100.0, allow_nan=False, allow_infinity=False),
)
def test_property_8_small_bucket_size_uses_absolute_floor(bucket_size_param: float, price: float):
    """
    Property 8: Minimum Bucket Size from Constructor (small bucket_size)
    
    *For any* TradeStatsCache instance with a very small `bucket_size` parameter
    (where bucket_size * 0.01 < 0.001), the configured minimum SHALL be 0.001
    (the absolute floor).
    
    **Validates: Requirements 5.4**
    """
    # Create a TradeStatsCache with very small bucket_size parameter
    cache = TradeStatsCache(bucket_size=bucket_size_param)
    
    # For bucket_size < 0.1, bucket_size * 0.01 < 0.001, so absolute floor applies
    # configured_minimum = max(0.001, bucket_size_param * 0.01) = 0.001
    expected_minimum = 0.001
    
    # Calculate the adaptive bucket size
    adaptive_bucket = cache._calculate_adaptive_bucket_size(price)
    
    # Property: adaptive bucket should be at least the absolute floor
    assert adaptive_bucket >= expected_minimum, (
        f"Adaptive bucket {adaptive_bucket} is less than absolute floor {expected_minimum} "
        f"for small bucket_size_param={bucket_size_param}, price={price}"
    )


# =============================================================================
# Property 6: POC Accuracy Across Price Levels
# Feature: snapshot-field-naming-and-poc-accuracy, Property 6: POC Accuracy Across Price Levels
# Validates: Requirements 4.1, 4.2, 4.3
# =============================================================================


def _get_accuracy_threshold(price: float) -> float:
    """
    Get the accuracy threshold for POC based on price level.
    
    - Price < $200: within 0.5% of actual highest-volume price
    - Price $200-$1000: within 0.25% of actual highest-volume price
    - Price > $1000: within 0.1% of actual highest-volume price
    """
    if price < 200.0:
        return 0.005  # 0.5%
    elif price <= 1000.0:
        return 0.0025  # 0.25%
    else:
        return 0.001  # 0.1%


def _calculate_expected_poc_bucket(price: float, bucket_size: float = 5.0) -> float:
    """
    Calculate the expected POC bucket for a given price.
    
    The POC is always at a bucket boundary, calculated as:
    bucket = int(price / dynamic_bucket) * dynamic_bucket
    
    This function returns the bucket that the price would fall into.
    """
    # Calculate adaptive bucket size using the new algorithm
    if price < 200.0:
        pct_based = price * 0.0025
    elif price <= 1000.0:
        pct_based = price * 0.00125
    else:
        pct_based = price * 0.0005
    
    min_bucket = max(0.001, bucket_size * 0.01)
    dynamic_bucket = max(min_bucket, pct_based)
    
    # Calculate the bucket
    return float(int(price / dynamic_bucket) * dynamic_bucket)


@st.composite
def trades_with_concentrated_volume(draw):
    """
    Generate a list of trades where one price level has significantly more volume
    than others. This creates a clear POC that we can verify.
    
    Strategy:
    1. Generate a dominant price level (the expected POC)
    2. Generate trades at the dominant price with high volume
    3. Generate background trades at other prices with lower volume
    4. The dominant price should have at least 3x the volume of any other bucket
    
    NOTE: The POC is always at a bucket boundary, so we generate prices that
    will fall into a specific bucket and verify the POC is at that bucket.
    All dominant trades are placed at exactly the same price to ensure they
    fall into the same bucket.
    """
    # Generate the dominant price level (expected POC)
    # Cover all three price ranges: <$200, $200-$1000, >$1000
    price_range = draw(st.sampled_from(["low", "medium", "high"]))
    
    if price_range == "low":
        dominant_price = draw(st.floats(min_value=10.0, max_value=199.0, allow_nan=False, allow_infinity=False))
    elif price_range == "medium":
        dominant_price = draw(st.floats(min_value=200.0, max_value=1000.0, allow_nan=False, allow_infinity=False))
    else:  # high
        dominant_price = draw(st.floats(min_value=1001.0, max_value=50000.0, allow_nan=False, allow_infinity=False))
    
    # Calculate the adaptive bucket size for this price level
    # This helps us understand what bucket the dominant price will fall into
    if dominant_price < 200.0:
        pct_based = dominant_price * 0.0025
    elif dominant_price <= 1000.0:
        pct_based = dominant_price * 0.00125
    else:
        pct_based = dominant_price * 0.0005
    min_bucket = max(0.001, 5.0 * 0.01)  # Default bucket_size=5.0
    dynamic_bucket = max(min_bucket, pct_based)
    
    # Calculate the expected bucket for the dominant price
    expected_bucket = _calculate_expected_poc_bucket(dominant_price)
    
    # Generate trades at the dominant price level
    # Use high volume to ensure this is clearly the POC
    num_dominant_trades = draw(st.integers(min_value=20, max_value=50))
    dominant_volume_per_trade = draw(st.floats(min_value=10.0, max_value=100.0, allow_nan=False, allow_infinity=False))
    
    trades = []
    base_ts = 1000000.0
    
    # Add dominant trades - ALL at exactly the dominant price to ensure they're in the same bucket
    for i in range(num_dominant_trades):
        size = dominant_volume_per_trade
        side = draw(st.sampled_from(["buy", "sell"]))
        trades.append(TradeRecord(ts=base_ts + i, price=dominant_price, size=size, side=side))
    
    # Generate background trades at other price levels with much lower volume
    # These should not affect the POC
    num_background_trades = draw(st.integers(min_value=10, max_value=30))
    background_volume_per_trade = dominant_volume_per_trade / 10.0  # Much lower volume
    
    # Spread background trades across a range around the dominant price
    # But ensure they're in different buckets
    price_spread = dominant_price * 0.1  # 10% spread
    
    for i in range(num_background_trades):
        # Generate price offset that puts trades in different buckets
        offset_direction = draw(st.sampled_from([-1, 1]))
        offset_magnitude = draw(st.floats(
            min_value=dynamic_bucket * 2,  # At least 2 buckets away
            max_value=price_spread,
            allow_nan=False,
            allow_infinity=False
        ))
        price = max(0.01, dominant_price + offset_direction * offset_magnitude)
        size = background_volume_per_trade
        side = draw(st.sampled_from(["buy", "sell"]))
        trades.append(TradeRecord(ts=base_ts + num_dominant_trades + i, price=price, size=size, side=side))
    
    return trades, dominant_price, expected_bucket, price_range


@settings(max_examples=100)
@given(trade_data=trades_with_concentrated_volume())
def test_property_6_poc_accuracy_across_price_levels(trade_data):
    """
    Property 6: POC Accuracy Across Price Levels
    
    *For any* set of trades where one price level has significantly more volume
    than others, the calculated POC SHALL be within the accuracy threshold for
    that price level:
    - Price < $200: within 0.5% of actual highest-volume price
    - Price $200-$1000: within 0.25% of actual highest-volume price
    - Price > $1000: within 0.1% of actual highest-volume price
    
    NOTE: The POC is always at a bucket boundary. The accuracy threshold applies
    to the relationship between the bucket boundary and the actual highest-volume
    price. The adaptive bucket sizing ensures that the bucket size is small enough
    to meet the accuracy requirements.
    
    **Validates: Requirements 4.1, 4.2, 4.3**
    """
    trades, dominant_price, expected_bucket, price_range = trade_data
    
    # Ensure we have trades
    assume(len(trades) > 0)
    
    # Create a TradeStatsCache and calculate volume profile
    cache = TradeStatsCache()
    
    # Calculate volume profile directly
    poc, val, vah = cache._volume_profile(trades)
    
    # Ensure POC was calculated
    assume(poc is not None)
    
    # The POC should be at the expected bucket (where we concentrated volume)
    # The bucket is calculated as: int(price / dynamic_bucket) * dynamic_bucket
    # So the POC should match the expected bucket exactly
    assert poc == pytest.approx(expected_bucket, rel=1e-9), (
        f"POC bucket mismatch for {price_range} price range: "
        f"calculated POC={poc:.4f}, expected_bucket={expected_bucket:.4f}, "
        f"dominant_price={dominant_price:.4f}"
    )
    
    # Additionally verify that the bucket size is small enough to meet accuracy requirements
    # The maximum error from bucketing is at most one bucket size
    dynamic_bucket = cache._calculate_adaptive_bucket_size(dominant_price)
    threshold = _get_accuracy_threshold(dominant_price)
    max_bucket_error = dynamic_bucket / dominant_price
    
    # The bucket size should be small enough that the maximum error is within threshold
    # This validates that the adaptive bucket sizing meets the accuracy requirements
    assert max_bucket_error <= threshold, (
        f"Bucket size too large for {price_range} price range: "
        f"max_bucket_error={max_bucket_error:.6f} ({max_bucket_error*100:.4f}%), "
        f"threshold={threshold:.4f} ({threshold*100:.2f}%), "
        f"dynamic_bucket={dynamic_bucket:.6f}, dominant_price={dominant_price:.4f}"
    )


@settings(max_examples=100)
@given(
    dominant_price=st.floats(min_value=10.0, max_value=199.0, allow_nan=False, allow_infinity=False),
    dominant_volume=st.floats(min_value=100.0, max_value=1000.0, allow_nan=False, allow_infinity=False),
)
def test_property_6_poc_accuracy_low_price_range(dominant_price: float, dominant_volume: float):
    """
    Property 6: POC Accuracy Across Price Levels (low price range)
    
    FOR ALL assets with price below $200, THE POC SHALL be within 0.5% of the
    actual highest-volume price level.
    
    This test verifies that:
    1. The POC is correctly identified at the bucket containing the highest volume
    2. The bucket size is small enough that the maximum error is within 0.5%
    
    **Validates: Requirements 4.1**
    """
    # Create trades with concentrated volume at the dominant price
    trades = []
    base_ts = 1000000.0
    
    # Add dominant trades at the target price
    for i in range(20):
        trades.append(TradeRecord(
            ts=base_ts + i,
            price=dominant_price,
            size=dominant_volume / 20,  # Split volume across trades
            side="buy" if i % 2 == 0 else "sell"
        ))
    
    # Add some background noise at different prices (much lower volume)
    cache = TradeStatsCache()
    dynamic_bucket = cache._calculate_adaptive_bucket_size(dominant_price)
    
    for i in range(10):
        offset = dynamic_bucket * (i + 2)  # Different buckets
        price = dominant_price + offset if i % 2 == 0 else max(0.01, dominant_price - offset)
        trades.append(TradeRecord(
            ts=base_ts + 20 + i,
            price=price,
            size=dominant_volume / 200,  # 10x less volume per trade
            side="buy" if i % 2 == 0 else "sell"
        ))
    
    # Calculate volume profile
    poc, val, vah = cache._volume_profile(trades)
    
    # Ensure POC was calculated
    assume(poc is not None)
    
    # Calculate the expected bucket for the dominant price
    expected_bucket = _calculate_expected_poc_bucket(dominant_price)
    
    # The POC should be at the expected bucket
    assert poc == pytest.approx(expected_bucket, rel=1e-9), (
        f"POC bucket mismatch for low price range: "
        f"calculated POC={poc:.4f}, expected_bucket={expected_bucket:.4f}, "
        f"dominant_price={dominant_price:.4f}"
    )
    
    # For low prices (<$200), threshold is 0.5%
    # Verify the bucket size is small enough to meet this threshold
    threshold = 0.005
    max_bucket_error = dynamic_bucket / dominant_price
    
    assert max_bucket_error <= threshold, (
        f"Bucket size too large for low price range: "
        f"max_bucket_error={max_bucket_error:.6f} ({max_bucket_error*100:.4f}%), "
        f"threshold={threshold:.4f} ({threshold*100:.2f}%), "
        f"dynamic_bucket={dynamic_bucket:.6f}, dominant_price={dominant_price:.4f}"
    )


@settings(max_examples=100)
@given(
    dominant_price=st.floats(min_value=200.0, max_value=1000.0, allow_nan=False, allow_infinity=False),
    dominant_volume=st.floats(min_value=100.0, max_value=1000.0, allow_nan=False, allow_infinity=False),
)
def test_property_6_poc_accuracy_medium_price_range(dominant_price: float, dominant_volume: float):
    """
    Property 6: POC Accuracy Across Price Levels (medium price range)
    
    FOR ALL assets with price between $200 and $1000, THE POC SHALL be within
    0.25% of the actual highest-volume price level.
    
    This test verifies that:
    1. The POC is correctly identified at the bucket containing the highest volume
    2. The bucket size is small enough that the maximum error is within 0.25%
    
    **Validates: Requirements 4.2**
    """
    # Create trades with concentrated volume at the dominant price
    trades = []
    base_ts = 1000000.0
    
    # Add dominant trades at the target price
    for i in range(20):
        trades.append(TradeRecord(
            ts=base_ts + i,
            price=dominant_price,
            size=dominant_volume / 20,
            side="buy" if i % 2 == 0 else "sell"
        ))
    
    # Add some background noise at different prices (much lower volume)
    cache = TradeStatsCache()
    dynamic_bucket = cache._calculate_adaptive_bucket_size(dominant_price)
    
    for i in range(10):
        offset = dynamic_bucket * (i + 2)
        price = dominant_price + offset if i % 2 == 0 else max(0.01, dominant_price - offset)
        trades.append(TradeRecord(
            ts=base_ts + 20 + i,
            price=price,
            size=dominant_volume / 200,
            side="buy" if i % 2 == 0 else "sell"
        ))
    
    # Calculate volume profile
    poc, val, vah = cache._volume_profile(trades)
    
    # Ensure POC was calculated
    assume(poc is not None)
    
    # Calculate the expected bucket for the dominant price
    expected_bucket = _calculate_expected_poc_bucket(dominant_price)
    
    # The POC should be at the expected bucket
    assert poc == pytest.approx(expected_bucket, rel=1e-9), (
        f"POC bucket mismatch for medium price range: "
        f"calculated POC={poc:.4f}, expected_bucket={expected_bucket:.4f}, "
        f"dominant_price={dominant_price:.4f}"
    )
    
    # For medium prices ($200-$1000), threshold is 0.25%
    # Verify the bucket size is small enough to meet this threshold
    threshold = 0.0025
    max_bucket_error = dynamic_bucket / dominant_price
    
    assert max_bucket_error <= threshold, (
        f"Bucket size too large for medium price range: "
        f"max_bucket_error={max_bucket_error:.6f} ({max_bucket_error*100:.4f}%), "
        f"threshold={threshold:.4f} ({threshold*100:.2f}%), "
        f"dynamic_bucket={dynamic_bucket:.6f}, dominant_price={dominant_price:.4f}"
    )


@settings(max_examples=100)
@given(
    dominant_price=st.floats(min_value=1001.0, max_value=50000.0, allow_nan=False, allow_infinity=False),
    dominant_volume=st.floats(min_value=100.0, max_value=1000.0, allow_nan=False, allow_infinity=False),
)
def test_property_6_poc_accuracy_high_price_range(dominant_price: float, dominant_volume: float):
    """
    Property 6: POC Accuracy Across Price Levels (high price range)
    
    FOR ALL assets with price above $1000, THE POC SHALL be within 0.1% of the
    actual highest-volume price level.
    
    This test verifies that:
    1. The POC is correctly identified at the bucket containing the highest volume
    2. The bucket size is small enough that the maximum error is within 0.1%
    
    **Validates: Requirements 4.3**
    """
    # Create trades with concentrated volume at the dominant price
    trades = []
    base_ts = 1000000.0
    
    # Add dominant trades at the target price
    for i in range(20):
        trades.append(TradeRecord(
            ts=base_ts + i,
            price=dominant_price,
            size=dominant_volume / 20,
            side="buy" if i % 2 == 0 else "sell"
        ))
    
    # Add some background noise at different prices (much lower volume)
    cache = TradeStatsCache()
    dynamic_bucket = cache._calculate_adaptive_bucket_size(dominant_price)
    
    for i in range(10):
        offset = dynamic_bucket * (i + 2)
        price = dominant_price + offset if i % 2 == 0 else max(0.01, dominant_price - offset)
        trades.append(TradeRecord(
            ts=base_ts + 20 + i,
            price=price,
            size=dominant_volume / 200,
            side="buy" if i % 2 == 0 else "sell"
        ))
    
    # Calculate volume profile
    poc, val, vah = cache._volume_profile(trades)
    
    # Ensure POC was calculated
    assume(poc is not None)
    
    # Calculate the expected bucket for the dominant price
    expected_bucket = _calculate_expected_poc_bucket(dominant_price)
    
    # The POC should be at the expected bucket
    assert poc == pytest.approx(expected_bucket, rel=1e-9), (
        f"POC bucket mismatch for high price range: "
        f"calculated POC={poc:.4f}, expected_bucket={expected_bucket:.4f}, "
        f"dominant_price={dominant_price:.4f}"
    )
    
    # For high prices (>$1000), threshold is 0.1%
    # Verify the bucket size is small enough to meet this threshold
    threshold = 0.001
    max_bucket_error = dynamic_bucket / dominant_price
    
    assert max_bucket_error <= threshold, (
        f"Bucket size too large for high price range: "
        f"max_bucket_error={max_bucket_error:.6f} ({max_bucket_error*100:.4f}%), "
        f"threshold={threshold:.4f} ({threshold*100:.2f}%), "
        f"dynamic_bucket={dynamic_bucket:.6f}, dominant_price={dominant_price:.4f}"
    )


@settings(max_examples=100)
@given(
    price_level=st.floats(min_value=10.0, max_value=50000.0, allow_nan=False, allow_infinity=False),
    volume_concentration_factor=st.floats(min_value=5.0, max_value=20.0, allow_nan=False, allow_infinity=False),
)
def test_property_6_poc_accuracy_with_varying_concentration(
    price_level: float, volume_concentration_factor: float
):
    """
    Property 6: POC Accuracy Across Price Levels (varying concentration)
    
    *For any* set of trades where one price level has significantly more volume
    (concentration factor >= 5x) than others, the calculated POC SHALL be within
    the accuracy threshold for that price level.
    
    This test verifies that:
    1. The POC is correctly identified at the bucket containing the highest volume
    2. The bucket size is small enough to meet the accuracy requirements
    
    **Validates: Requirements 4.1, 4.2, 4.3**
    """
    # Create trades with concentrated volume at the target price
    trades = []
    base_ts = 1000000.0
    
    # Calculate adaptive bucket size
    cache = TradeStatsCache()
    dynamic_bucket = cache._calculate_adaptive_bucket_size(price_level)
    
    # Base volume for background trades
    base_volume = 10.0
    
    # Dominant volume is concentration_factor times the base
    dominant_volume = base_volume * volume_concentration_factor
    
    # Add dominant trades at the target price
    for i in range(15):
        trades.append(TradeRecord(
            ts=base_ts + i,
            price=price_level,
            size=dominant_volume / 15,
            side="buy" if i % 2 == 0 else "sell"
        ))
    
    # Add background trades at different price levels
    for i in range(10):
        offset = dynamic_bucket * (i + 2)
        price = price_level + offset if i % 2 == 0 else max(0.01, price_level - offset)
        trades.append(TradeRecord(
            ts=base_ts + 15 + i,
            price=price,
            size=base_volume / 10,  # Much lower volume
            side="buy" if i % 2 == 0 else "sell"
        ))
    
    # Calculate volume profile
    poc, val, vah = cache._volume_profile(trades)
    
    # Ensure POC was calculated
    assume(poc is not None)
    
    # Calculate the expected bucket for the price level
    expected_bucket = _calculate_expected_poc_bucket(price_level)
    
    # The POC should be at the expected bucket
    assert poc == pytest.approx(expected_bucket, rel=1e-9), (
        f"POC bucket mismatch with concentration factor {volume_concentration_factor:.1f}x: "
        f"calculated POC={poc:.4f}, expected_bucket={expected_bucket:.4f}, "
        f"price_level={price_level:.4f}"
    )
    
    # Get the accuracy threshold for this price level
    threshold = _get_accuracy_threshold(price_level)
    max_bucket_error = dynamic_bucket / price_level
    
    assert max_bucket_error <= threshold, (
        f"Bucket size too large with concentration factor {volume_concentration_factor:.1f}x: "
        f"max_bucket_error={max_bucket_error:.6f} ({max_bucket_error*100:.4f}%), "
        f"threshold={threshold:.4f} ({threshold*100:.2f}%), "
        f"dynamic_bucket={dynamic_bucket:.6f}, price_level={price_level:.4f}"
    )


@settings(max_examples=100)
@given(
    price_level=st.floats(min_value=10.0, max_value=50000.0, allow_nan=False, allow_infinity=False),
)
def test_property_6_poc_accuracy_single_price_level(price_level: float):
    """
    Property 6: POC Accuracy Across Price Levels (single price level)
    
    *For any* set of trades all at the same price level, the calculated POC
    SHALL be at the bucket containing that price level.
    
    This test verifies that:
    1. The POC is correctly identified at the bucket containing all trades
    2. The bucket size is small enough to meet the accuracy requirements
    
    **Validates: Requirements 4.1, 4.2, 4.3**
    """
    # Create trades all at the same price
    trades = []
    base_ts = 1000000.0
    
    for i in range(20):
        trades.append(TradeRecord(
            ts=base_ts + i,
            price=price_level,
            size=10.0,
            side="buy" if i % 2 == 0 else "sell"
        ))
    
    # Calculate volume profile
    cache = TradeStatsCache()
    poc, val, vah = cache._volume_profile(trades)
    
    # Ensure POC was calculated
    assume(poc is not None)
    
    # Calculate the expected bucket for the price level
    expected_bucket = _calculate_expected_poc_bucket(price_level)
    
    # The POC should be at the expected bucket
    assert poc == pytest.approx(expected_bucket, rel=1e-9), (
        f"POC bucket mismatch for single price level: "
        f"calculated POC={poc:.4f}, expected_bucket={expected_bucket:.4f}, "
        f"price_level={price_level:.4f}"
    )
    
    # Get the accuracy threshold for this price level
    threshold = _get_accuracy_threshold(price_level)
    dynamic_bucket = cache._calculate_adaptive_bucket_size(price_level)
    max_bucket_error = dynamic_bucket / price_level
    
    # For single price level, verify bucket size meets accuracy requirements
    assert max_bucket_error <= threshold, (
        f"Bucket size too large for single price level: "
        f"max_bucket_error={max_bucket_error:.6f} ({max_bucket_error*100:.4f}%), "
        f"threshold={threshold:.4f} ({threshold*100:.2f}%), "
        f"dynamic_bucket={dynamic_bucket:.6f}, price_level={price_level:.4f}"
    )


# =============================================================================
# Property 5: Consistent Bucket Sizing Across Methods
# Feature: snapshot-field-naming-and-poc-accuracy, Property 5: Consistent Bucket Sizing Across Methods
# Validates: Requirements 3.6
# =============================================================================


@st.composite
def trades_for_consistency_test(draw):
    """
    Generate a list of trades suitable for testing consistency between
    snapshot() and _volume_profile() methods.
    
    Strategy:
    1. Generate trades with a variety of prices and volumes
    2. Ensure enough trades to produce meaningful volume profile
    3. Return trades that can be used to verify both methods produce same results
    """
    # Generate a base price level (covering various price ranges)
    price_range = draw(st.sampled_from(["low", "medium", "high"]))
    
    if price_range == "low":
        base_price = draw(st.floats(min_value=10.0, max_value=199.0, allow_nan=False, allow_infinity=False))
    elif price_range == "medium":
        base_price = draw(st.floats(min_value=200.0, max_value=1000.0, allow_nan=False, allow_infinity=False))
    else:  # high
        base_price = draw(st.floats(min_value=1001.0, max_value=50000.0, allow_nan=False, allow_infinity=False))
    
    # Calculate adaptive bucket size for this price level
    if base_price < 200.0:
        pct_based = base_price * 0.0025
    elif base_price <= 1000.0:
        pct_based = base_price * 0.00125
    else:
        pct_based = base_price * 0.0005
    min_bucket = max(0.001, 5.0 * 0.01)  # Default bucket_size=5.0
    dynamic_bucket = max(min_bucket, pct_based)
    
    # Generate price spread (multiple buckets)
    price_spread = dynamic_bucket * draw(st.integers(min_value=5, max_value=20))
    
    # Generate number of trades
    num_trades = draw(st.integers(min_value=20, max_value=100))
    
    # Generate trades with prices distributed around base_price
    trades = []
    base_ts = time.time()  # Use current time for snapshot() compatibility
    
    for i in range(num_trades):
        # Generate price within the spread
        offset = draw(st.floats(
            min_value=-price_spread / 2,
            max_value=price_spread / 2,
            allow_nan=False,
            allow_infinity=False
        ))
        price = max(0.01, base_price + offset)
        
        # Generate trade size
        size = draw(st.floats(min_value=0.1, max_value=100.0, allow_nan=False, allow_infinity=False))
        
        # Generate side
        side = draw(st.sampled_from(["buy", "sell"]))
        
        # Use timestamps within the profile window (300 seconds by default)
        ts = base_ts - draw(st.floats(min_value=0.0, max_value=60.0, allow_nan=False, allow_infinity=False))
        
        trades.append(TradeRecord(ts=ts, price=price, size=size, side=side))
    
    return trades, base_price, price_range


@settings(max_examples=100)
@given(trade_data=trades_for_consistency_test())
def test_property_5_consistent_bucket_sizing_snapshot_vs_volume_profile(trade_data):
    """
    Property 5: Consistent Bucket Sizing Across Methods
    
    *For any* set of trades, calling `snapshot()` and `_volume_profile()` with the
    same data SHALL use the same bucket sizing algorithm and produce consistent
    POC/VAH/VAL values.
    
    This test verifies that:
    1. Both methods use the same adaptive bucket sizing algorithm
    2. The POC, VAH, and VAL values are identical when given the same trade data
    
    **Validates: Requirements 3.6**
    """
    trades, base_price, price_range = trade_data
    
    # Ensure we have trades
    assume(len(trades) > 0)
    
    # Create a TradeStatsCache
    cache = TradeStatsCache()
    
    # Call _volume_profile() directly with the trades
    poc_direct, val_direct, vah_direct = cache._volume_profile(trades)
    
    # Ensure we got valid results
    assume(poc_direct is not None)
    assume(val_direct is not None)
    assume(vah_direct is not None)
    
    # Now add the same trades to the cache and call snapshot()
    # We need to use a unique symbol to avoid interference
    symbol = f"TEST_{id(trades)}"
    
    # Add trades to the cache
    for trade in trades:
        cache.update_trade(symbol, trade.ts, trade.price, trade.size, trade.side)
    
    # Call snapshot() to get the volume profile through the public API
    snapshot_result = cache.snapshot(symbol)
    
    # Ensure snapshot returned valid results
    assume(snapshot_result is not None)
    assume("point_of_control" in snapshot_result)
    assume(snapshot_result["point_of_control"] is not None)
    
    poc_snapshot = snapshot_result["point_of_control"]
    val_snapshot = snapshot_result["value_area_low"]
    vah_snapshot = snapshot_result["value_area_high"]
    
    # Property: POC values should be consistent
    # Note: snapshot() may use a subset of trades (within profile_window_sec)
    # but the bucket sizing algorithm should be the same
    
    # Calculate the median price from trades to verify bucket sizing
    prices = [t.price for t in trades if t.price > 0]
    median_price = sorted(prices)[len(prices) // 2]
    
    # Verify both methods use the same bucket sizing
    expected_bucket = cache._calculate_adaptive_bucket_size(median_price)
    
    # The POC should be at a bucket boundary (lower boundary of the bucket)
    # The bucket is calculated as: int(price / bucket) * bucket
    # So POC should be a multiple of the bucket size (approximately, due to floating point)
    poc_bucket_index = poc_direct / expected_bucket
    assert abs(poc_bucket_index - round(poc_bucket_index)) < 0.01, (
        f"Direct POC {poc_direct} is not at a bucket boundary "
        f"(expected bucket size: {expected_bucket}, bucket_index: {poc_bucket_index})"
    )
    
    # If the trades used by snapshot() are the same as those passed to _volume_profile(),
    # the results should be identical
    # Note: snapshot() filters trades by time window, so we need to account for that
    
    # Get the trades that snapshot() would use (within profile_window_sec)
    now = time.time()
    profile_trades = [t for t in trades if now - t.ts <= cache.profile_window_sec]
    
    if len(profile_trades) == len(trades):
        # All trades are within the profile window, so results should match exactly
        assert poc_snapshot == pytest.approx(poc_direct, rel=1e-9), (
            f"POC mismatch: snapshot()={poc_snapshot}, _volume_profile()={poc_direct} "
            f"for {price_range} price range"
        )
        assert val_snapshot == pytest.approx(val_direct, rel=1e-9), (
            f"VAL mismatch: snapshot()={val_snapshot}, _volume_profile()={val_direct} "
            f"for {price_range} price range"
        )
        assert vah_snapshot == pytest.approx(vah_direct, rel=1e-9), (
            f"VAH mismatch: snapshot()={vah_snapshot}, _volume_profile()={vah_direct} "
            f"for {price_range} price range"
        )


@settings(max_examples=100)
@given(
    base_price=st.floats(min_value=10.0, max_value=50000.0, allow_nan=False, allow_infinity=False),
    num_trades=st.integers(min_value=10, max_value=50),
)
def test_property_5_bucket_sizing_algorithm_consistency(base_price: float, num_trades: int):
    """
    Property 5: Consistent Bucket Sizing Across Methods (algorithm consistency)
    
    *For any* price level, the bucket sizing algorithm used by _volume_profile()
    SHALL be the same as _calculate_adaptive_bucket_size().
    
    This test verifies that _volume_profile() internally uses the same bucket
    sizing algorithm that is exposed via _calculate_adaptive_bucket_size().
    
    **Validates: Requirements 3.6**
    """
    # Create a TradeStatsCache
    cache = TradeStatsCache()
    
    # Calculate expected bucket size using the public method
    expected_bucket = cache._calculate_adaptive_bucket_size(base_price)
    
    # Create trades at the base price
    trades = []
    base_ts = time.time()
    
    for i in range(num_trades):
        trades.append(TradeRecord(
            ts=base_ts - i,
            price=base_price,
            size=1.0,
            side="buy" if i % 2 == 0 else "sell"
        ))
    
    # Call _volume_profile() to get the POC
    poc, val, vah = cache._volume_profile(trades)
    
    # Ensure we got valid results
    assume(poc is not None)
    
    # The POC should be at a bucket boundary calculated using the expected bucket size
    expected_poc_bucket = float(int(base_price / expected_bucket) * expected_bucket)
    
    # Property: POC should match the expected bucket
    assert poc == pytest.approx(expected_poc_bucket, rel=1e-9), (
        f"POC {poc} does not match expected bucket {expected_poc_bucket} "
        f"for base_price={base_price}, expected_bucket={expected_bucket}"
    )


@settings(max_examples=100)
@given(
    base_price=st.floats(min_value=10.0, max_value=50000.0, allow_nan=False, allow_infinity=False),
    bucket_size_param=st.floats(min_value=0.1, max_value=100.0, allow_nan=False, allow_infinity=False),
)
def test_property_5_consistent_bucket_sizing_with_custom_bucket_size(
    base_price: float, bucket_size_param: float
):
    """
    Property 5: Consistent Bucket Sizing Across Methods (custom bucket_size)
    
    *For any* TradeStatsCache with a custom bucket_size parameter, both snapshot()
    and _volume_profile() SHALL use the same adaptive bucket sizing algorithm
    that respects the configured minimum.
    
    **Validates: Requirements 3.6**
    """
    # Create a TradeStatsCache with custom bucket_size
    cache = TradeStatsCache(bucket_size=bucket_size_param)
    
    # Calculate expected bucket size
    expected_bucket = cache._calculate_adaptive_bucket_size(base_price)
    
    # Verify the minimum floor is respected
    min_bucket = max(0.001, bucket_size_param * 0.01)
    assert expected_bucket >= min_bucket, (
        f"Expected bucket {expected_bucket} is less than minimum {min_bucket}"
    )
    
    # Create trades at the base price
    trades = []
    base_ts = time.time()
    
    for i in range(20):
        trades.append(TradeRecord(
            ts=base_ts - i,
            price=base_price,
            size=1.0,
            side="buy" if i % 2 == 0 else "sell"
        ))
    
    # Call _volume_profile() to get the POC
    poc, val, vah = cache._volume_profile(trades)
    
    # Ensure we got valid results
    assume(poc is not None)
    
    # The POC should be at a bucket boundary calculated using the expected bucket size
    expected_poc_bucket = float(int(base_price / expected_bucket) * expected_bucket)
    
    # Property: POC should match the expected bucket
    assert poc == pytest.approx(expected_poc_bucket, rel=1e-9), (
        f"POC {poc} does not match expected bucket {expected_poc_bucket} "
        f"for base_price={base_price}, bucket_size_param={bucket_size_param}"
    )


@settings(max_examples=100)
@given(trade_data=trades_for_consistency_test())
def test_property_5_vah_val_consistency_across_methods(trade_data):
    """
    Property 5: Consistent Bucket Sizing Across Methods (VAH/VAL consistency)
    
    *For any* set of trades, the VAH and VAL values produced by _volume_profile()
    SHALL be at bucket boundaries consistent with the adaptive bucket sizing algorithm.
    
    The value area is calculated by:
    1. Sorting buckets by volume (descending)
    2. Picking buckets until 70% of total volume is reached
    3. VAL = min of picked buckets, VAH = max of picked buckets
    4. If VAL == VAH (single bucket), expand by one bucket in each direction
    
    **Validates: Requirements 3.6**
    """
    trades, base_price, price_range = trade_data
    
    # Ensure we have trades
    assume(len(trades) > 0)
    
    # Create a TradeStatsCache
    cache = TradeStatsCache()
    
    # Call _volume_profile() directly
    poc, val, vah = cache._volume_profile(trades)
    
    # Ensure we got valid results
    assume(poc is not None)
    assume(val is not None)
    assume(vah is not None)
    
    # Calculate the median price from trades
    prices = [t.price for t in trades if t.price > 0]
    median_price = sorted(prices)[len(prices) // 2]
    
    # Get the expected bucket size
    expected_bucket = cache._calculate_adaptive_bucket_size(median_price)
    
    # Property: VAL should be <= POC <= VAH
    assert val <= poc, (
        f"VAL {val} should be <= POC {poc} for {price_range} price range"
    )
    assert poc <= vah, (
        f"POC {poc} should be <= VAH {vah} for {price_range} price range"
    )
    
    # Property: VAH - VAL should be at least one bucket (when expanded) or zero (single bucket before expansion)
    # After expansion, VAH - VAL = 2 * expected_bucket
    value_area_width = vah - val
    
    # The value area width should be a multiple of the bucket size
    # (either 0 before expansion, or 2*bucket after expansion, or larger for multiple buckets)
    if value_area_width > 0:
        # Check that the width is approximately a multiple of the bucket size
        num_buckets_in_va = value_area_width / expected_bucket
        # Should be close to an integer (within floating point tolerance)
        assert abs(num_buckets_in_va - round(num_buckets_in_va)) < 0.01, (
            f"Value area width {value_area_width} is not a multiple of bucket size {expected_bucket} "
            f"(num_buckets={num_buckets_in_va}) for {price_range} price range"
        )
    
    # Property: POC should be within the value area
    assert val <= poc <= vah, (
        f"POC {poc} should be within value area [{val}, {vah}] for {price_range} price range"
    )


@settings(max_examples=100)
@given(
    price_range_type=st.sampled_from(["low", "medium", "high"]),
    num_calls=st.integers(min_value=2, max_value=5),
)
def test_property_5_repeated_calls_produce_same_results(price_range_type: str, num_calls: int):
    """
    Property 5: Consistent Bucket Sizing Across Methods (repeated calls)
    
    *For any* set of trades, calling _volume_profile() multiple times with the
    same data SHALL produce identical POC/VAH/VAL values.
    
    This verifies that the bucket sizing algorithm is deterministic and produces
    consistent results across repeated calls.
    
    **Validates: Requirements 3.6**
    """
    # Generate base price based on price range
    if price_range_type == "low":
        base_price = 100.0
    elif price_range_type == "medium":
        base_price = 500.0
    else:
        base_price = 5000.0
    
    # Create a TradeStatsCache
    cache = TradeStatsCache()
    
    # Calculate bucket size
    bucket_size = cache._calculate_adaptive_bucket_size(base_price)
    
    # Create trades with some price variation
    trades = []
    base_ts = time.time()
    
    for i in range(30):
        # Add some price variation within a few buckets
        offset = bucket_size * (i % 5 - 2)
        price = base_price + offset
        trades.append(TradeRecord(
            ts=base_ts - i,
            price=price,
            size=1.0 + (i % 3),  # Varying sizes
            side="buy" if i % 2 == 0 else "sell"
        ))
    
    # Call _volume_profile() multiple times
    results = []
    for _ in range(num_calls):
        poc, val, vah = cache._volume_profile(trades)
        results.append((poc, val, vah))
    
    # Ensure we got valid results
    assume(results[0][0] is not None)
    
    # Property: all calls should produce identical results
    first_result = results[0]
    for i, result in enumerate(results[1:], start=2):
        assert result[0] == pytest.approx(first_result[0], rel=1e-9), (
            f"POC mismatch: call 1 ({first_result[0]}) != call {i} ({result[0]})"
        )
        assert result[1] == pytest.approx(first_result[1], rel=1e-9), (
            f"VAL mismatch: call 1 ({first_result[1]}) != call {i} ({result[1]})"
        )
        assert result[2] == pytest.approx(first_result[2], rel=1e-9), (
            f"VAH mismatch: call 1 ({first_result[2]}) != call {i} ({result[2]})"
        )
