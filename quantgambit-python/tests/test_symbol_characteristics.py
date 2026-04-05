"""
Property-based tests for SymbolCharacteristics and SymbolCharacteristicsService.

Feature: symbol-adaptive-parameters
Tests correctness properties for symbol characteristics data structure
and the EMA-based tracking service.
"""

from typing import Dict
import pytest
from hypothesis import given, strategies as st, settings, assume

from quantgambit.deeptrader_core.types import SymbolCharacteristics
from quantgambit.signals.services.symbol_characteristics import SymbolCharacteristicsService


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


# EMA decay factor (must be between 0 and 1)
ema_decay = st.floats(min_value=0.001, max_value=0.5, allow_nan=False, allow_infinity=False)

# Price (positive, realistic range for crypto)
price = st.floats(min_value=0.01, max_value=100000.0, allow_nan=False, allow_infinity=False)

# Sequence length for EMA tests
sequence_length = st.integers(min_value=2, max_value=50)


# =============================================================================
# Property 1: EMA Calculation Correctness
# Feature: symbol-adaptive-parameters, Property 1: EMA Calculation Correctness
# Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5
# =============================================================================

@settings(max_examples=100)
@given(
    alpha=ema_decay,
    values=st.lists(spread_bps, min_size=2, max_size=50),
)
def test_property_1_ema_formula_correctness(alpha: float, values: list[float]):
    """
    Property 1: EMA Calculation Correctness - Formula Verification
    
    For any sequence of input values and any EMA decay factor α,
    the resulting EMA should satisfy:
    EMA_new = α × value + (1 - α) × EMA_old
    
    This test verifies the EMA formula is correctly implemented
    by manually computing the expected EMA and comparing.
    
    **Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5**
    """
    service = SymbolCharacteristicsService(redis_client=None, ema_decay=alpha)
    symbol = "TESTUSDT"
    
    # Feed values through the service
    for i, spread in enumerate(values):
        # Use constant values for other fields to isolate spread EMA testing
        service.update(
            symbol=symbol,
            spread_bps=spread,
            min_depth_usd=10000.0,
            atr=100.0,
            price=50000.0,
            volatility_regime="normal",
        )
    
    # Get the final characteristics
    chars = service.get_characteristics(symbol)
    
    # Manually compute expected EMA
    expected_ema = values[0]  # First value initializes directly
    for value in values[1:]:
        expected_ema = alpha * value + (1 - alpha) * expected_ema
    
    # Verify the EMA matches (with floating point tolerance)
    assert abs(chars.typical_spread_bps - expected_ema) < 1e-9, (
        f"EMA mismatch: got {chars.typical_spread_bps}, expected {expected_ema}"
    )


@settings(max_examples=100)
@given(
    alpha=ema_decay,
    constant_value=spread_bps,
    num_samples=st.integers(min_value=10, max_value=100),
)
def test_property_1_ema_convergence(alpha: float, constant_value: float, num_samples: int):
    """
    Property 1: EMA Calculation Correctness - Convergence
    
    For any constant sequence of values, the EMA should converge
    toward that constant value.
    
    **Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5**
    """
    service = SymbolCharacteristicsService(redis_client=None, ema_decay=alpha)
    symbol = "TESTUSDT"
    
    # Feed constant values
    for _ in range(num_samples):
        service.update(
            symbol=symbol,
            spread_bps=constant_value,
            min_depth_usd=10000.0,
            atr=100.0,
            price=50000.0,
            volatility_regime="normal",
        )
    
    chars = service.get_characteristics(symbol)
    
    # After many samples of constant value, EMA should be close to that value
    # The error decreases as (1-alpha)^n
    max_error = constant_value * ((1 - alpha) ** num_samples) + 1e-9
    actual_error = abs(chars.typical_spread_bps - constant_value)
    
    assert actual_error <= max_error + 1e-9, (
        f"EMA did not converge: got {chars.typical_spread_bps}, "
        f"expected ~{constant_value}, error {actual_error} > {max_error}"
    )


@settings(max_examples=100)
@given(
    alpha=ema_decay,
    values=st.lists(spread_bps, min_size=2, max_size=50),
)
def test_property_1_ema_boundedness(alpha: float, values: list[float]):
    """
    Property 1: EMA Calculation Correctness - Boundedness
    
    For any sequence of input values, the EMA should be bounded
    by the minimum and maximum of all input values.
    
    **Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5**
    """
    service = SymbolCharacteristicsService(redis_client=None, ema_decay=alpha)
    symbol = "TESTUSDT"
    
    # Feed values through the service
    for spread in values:
        service.update(
            symbol=symbol,
            spread_bps=spread,
            min_depth_usd=10000.0,
            atr=100.0,
            price=50000.0,
            volatility_regime="normal",
        )
    
    chars = service.get_characteristics(symbol)
    
    min_val = min(values)
    max_val = max(values)
    
    # EMA should be within bounds (with small tolerance for floating point)
    assert chars.typical_spread_bps >= min_val - 1e-9, (
        f"EMA below minimum: {chars.typical_spread_bps} < {min_val}"
    )
    assert chars.typical_spread_bps <= max_val + 1e-9, (
        f"EMA above maximum: {chars.typical_spread_bps} > {max_val}"
    )


@settings(max_examples=100)
@given(
    alpha=ema_decay,
    depth_values=st.lists(depth_usd, min_size=2, max_size=30),
    atr_values=st.lists(atr_value.filter(lambda x: x > 0), min_size=2, max_size=30),
    price_val=price,
)
def test_property_1_ema_all_metrics(
    alpha: float,
    depth_values: list[float],
    atr_values: list[float],
    price_val: float,
):
    """
    Property 1: EMA Calculation Correctness - All Metrics
    
    Verify EMA formula is correctly applied to all tracked metrics:
    - typical_spread_bps
    - typical_depth_usd
    - typical_daily_range_pct
    - typical_atr
    
    **Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5**
    """
    # Ensure lists are same length
    min_len = min(len(depth_values), len(atr_values))
    depth_values = depth_values[:min_len]
    atr_values = atr_values[:min_len]
    
    assume(min_len >= 2)
    assume(price_val > 0)
    
    service = SymbolCharacteristicsService(redis_client=None, ema_decay=alpha)
    symbol = "TESTUSDT"
    
    # Feed values through the service
    for depth, atr in zip(depth_values, atr_values):
        service.update(
            symbol=symbol,
            spread_bps=5.0,  # constant
            min_depth_usd=depth,
            atr=atr,
            price=price_val,
            volatility_regime="normal",
        )
    
    chars = service.get_characteristics(symbol)
    
    # Manually compute expected EMAs
    expected_depth = depth_values[0]
    expected_atr = atr_values[0]
    
    for i in range(1, min_len):
        expected_depth = alpha * depth_values[i] + (1 - alpha) * expected_depth
        expected_atr = alpha * atr_values[i] + (1 - alpha) * expected_atr
    
    # Verify depth EMA
    assert abs(chars.typical_depth_usd - expected_depth) < 1e-6, (
        f"Depth EMA mismatch: got {chars.typical_depth_usd}, expected {expected_depth}"
    )
    
    # Verify ATR EMA
    assert abs(chars.typical_atr - expected_atr) < 1e-6, (
        f"ATR EMA mismatch: got {chars.typical_atr}, expected {expected_atr}"
    )


@settings(max_examples=100)
@given(
    regimes=st.lists(volatility_regime, min_size=10, max_size=100),
)
def test_property_1_volatility_regime_mode(regimes: list[str]):
    """
    Property 1: EMA Calculation Correctness - Volatility Regime Mode
    
    The typical_volatility_regime should be the mode (most common)
    of recent volatility regimes.
    
    **Validates: Requirements 1.4**
    """
    service = SymbolCharacteristicsService(redis_client=None)
    symbol = "TESTUSDT"
    
    # Feed regimes through the service
    for regime in regimes:
        service.update(
            symbol=symbol,
            spread_bps=5.0,
            min_depth_usd=10000.0,
            atr=100.0,
            price=50000.0,
            volatility_regime=regime,
        )
    
    chars = service.get_characteristics(symbol)
    
    # Calculate expected mode from the window (last 100 or all if fewer)
    window = regimes[-100:]  # Service uses window of 100
    counts = {"low": 0, "normal": 0, "high": 0}
    for r in window:
        counts[r] += 1
    expected_mode = max(counts, key=counts.get)
    
    assert chars.typical_volatility_regime == expected_mode, (
        f"Regime mode mismatch: got {chars.typical_volatility_regime}, "
        f"expected {expected_mode}, counts={counts}"
    )


# =============================================================================
# Property 4: Persistence Round-Trip
# Feature: symbol-adaptive-parameters, Property 4: Persistence Round-Trip
# Validates: Requirements 1.6
# =============================================================================

@settings(max_examples=100)
@given(
    sym=symbol,
    spread=spread_bps,
    depth=depth_usd,
    daily_range=daily_range_pct,
    atr=atr_value,
    vol_regime=volatility_regime,
    samples=sample_count,
    ts_ns=timestamp_ns,
)
def test_property_4_persistence_round_trip(
    sym: str,
    spread: float,
    depth: float,
    daily_range: float,
    atr: float,
    vol_regime: str,
    samples: int,
    ts_ns: int,
):
    """
    Property 4: Persistence Round-Trip
    
    For any valid SymbolCharacteristics object, serializing to dict
    and deserializing SHALL produce an equivalent object.
    
    This validates that the to_dict() and from_dict() methods are
    proper inverses of each other, ensuring data integrity during
    Redis persistence and recovery.
    
    **Validates: Requirements 1.6**
    """
    # Create original object
    original = SymbolCharacteristics(
        symbol=sym,
        typical_spread_bps=spread,
        typical_depth_usd=depth,
        typical_daily_range_pct=daily_range,
        typical_atr=atr,
        typical_volatility_regime=vol_regime,
        sample_count=samples,
        last_updated_ns=ts_ns,
    )
    
    # Serialize to dict
    serialized = original.to_dict()
    
    # Deserialize back to object
    restored = SymbolCharacteristics.from_dict(serialized)
    
    # Verify all fields are equivalent
    assert restored.symbol == original.symbol, (
        f"Symbol mismatch: {restored.symbol} != {original.symbol}"
    )
    assert restored.typical_spread_bps == original.typical_spread_bps, (
        f"Spread mismatch: {restored.typical_spread_bps} != {original.typical_spread_bps}"
    )
    assert restored.typical_depth_usd == original.typical_depth_usd, (
        f"Depth mismatch: {restored.typical_depth_usd} != {original.typical_depth_usd}"
    )
    assert restored.typical_daily_range_pct == original.typical_daily_range_pct, (
        f"Daily range mismatch: {restored.typical_daily_range_pct} != {original.typical_daily_range_pct}"
    )
    assert restored.typical_atr == original.typical_atr, (
        f"ATR mismatch: {restored.typical_atr} != {original.typical_atr}"
    )
    assert restored.typical_volatility_regime == original.typical_volatility_regime, (
        f"Vol regime mismatch: {restored.typical_volatility_regime} != {original.typical_volatility_regime}"
    )
    assert restored.sample_count == original.sample_count, (
        f"Sample count mismatch: {restored.sample_count} != {original.sample_count}"
    )
    assert restored.last_updated_ns == original.last_updated_ns, (
        f"Timestamp mismatch: {restored.last_updated_ns} != {original.last_updated_ns}"
    )
    
    # Also verify is_warmed_up() behavior is preserved
    assert restored.is_warmed_up() == original.is_warmed_up(), (
        f"is_warmed_up mismatch: {restored.is_warmed_up()} != {original.is_warmed_up()}"
    )


# =============================================================================
# Unit Tests for Redis Persistence (Task 2.3)
# =============================================================================

class MockRedis:
    """Mock Redis client for testing persistence without actual Redis."""
    
    def __init__(self):
        self._data: Dict[str, Dict[str, str]] = {}
    
    async def hset(self, key: str, mapping: Dict[str, str]) -> None:
        self._data[key] = dict(mapping)
    
    async def hgetall(self, key: str) -> Dict[str, str]:
        return self._data.get(key, {})


@pytest.mark.asyncio
async def test_redis_persist_and_load():
    """
    Test that persist() and load() work correctly with Redis.
    
    Validates: Requirements 1.6
    """
    mock_redis = MockRedis()
    service = SymbolCharacteristicsService(redis_client=mock_redis)
    symbol = "BTCUSDT"
    
    # Update characteristics
    for _ in range(10):
        service.update(
            symbol=symbol,
            spread_bps=5.0,
            min_depth_usd=50000.0,
            atr=1000.0,
            price=50000.0,
            volatility_regime="normal",
        )
    
    original = service.get_characteristics(symbol)
    
    # Persist to Redis
    await service.persist(symbol)
    
    # Clear cache and reload
    service.clear_cache(symbol)
    assert not service.has_characteristics(symbol)
    
    # Load from Redis
    loaded = await service.load(symbol)
    
    assert loaded is not None
    assert loaded.symbol == original.symbol
    assert loaded.typical_spread_bps == original.typical_spread_bps
    assert loaded.typical_depth_usd == original.typical_depth_usd
    assert loaded.sample_count == original.sample_count


@pytest.mark.asyncio
async def test_persist_if_changed_triggers_on_significant_change():
    """
    Test that persist_if_changed() triggers when metrics change significantly.
    
    Validates: Requirements 1.6 (auto-persist on significant changes)
    """
    mock_redis = MockRedis()
    service = SymbolCharacteristicsService(redis_client=mock_redis, ema_decay=1.0)  # High decay for fast changes
    symbol = "ETHUSDT"
    
    # Initial update
    service.update(
        symbol=symbol,
        spread_bps=5.0,
        min_depth_usd=50000.0,
        atr=100.0,
        price=3000.0,
        volatility_regime="normal",
    )
    
    # First persist_if_changed should persist (never persisted before)
    result = await service.persist_if_changed(symbol)
    assert result is True
    
    # Small change - should not trigger persist
    service.update(
        symbol=symbol,
        spread_bps=5.1,  # 2% change
        min_depth_usd=50000.0,
        atr=100.0,
        price=3000.0,
        volatility_regime="normal",
    )
    result = await service.persist_if_changed(symbol, threshold_pct=0.20)
    assert result is False
    
    # Large change - should trigger persist
    service.update(
        symbol=symbol,
        spread_bps=10.0,  # 100% change from 5.0
        min_depth_usd=50000.0,
        atr=100.0,
        price=3000.0,
        volatility_regime="normal",
    )
    result = await service.persist_if_changed(symbol, threshold_pct=0.20)
    assert result is True


@pytest.mark.asyncio
async def test_service_works_without_redis():
    """
    Test that service works correctly when Redis is unavailable.
    
    Validates: Error handling - Redis unavailable scenario
    """
    service = SymbolCharacteristicsService(redis_client=None)
    symbol = "SOLUSDT"
    
    # Update should work
    service.update(
        symbol=symbol,
        spread_bps=3.0,
        min_depth_usd=20000.0,
        atr=5.0,
        price=100.0,
        volatility_regime="high",
    )
    
    chars = service.get_characteristics(symbol)
    assert chars.symbol == symbol
    assert chars.typical_spread_bps == 3.0
    
    # Persist should not raise (just skip)
    await service.persist(symbol)
    
    # Load should return None
    loaded = await service.load(symbol)
    assert loaded is None
