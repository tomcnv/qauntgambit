"""
Property-based tests for POC Distance Tiered Entry Logic.

Feature: midvol-coverage-restoration
Tests correctness properties for:
- Property 4: POC Distance Tiered Entry Logic

**Validates: Requirements 4.1, 4.2, 4.3**

Tests that the mean_reversion_fade strategy correctly applies the POC distance
threshold to accept or reject entries based on the min_distance_from_poc_pct parameter.
"""

import pytest
from hypothesis import given, strategies as st, settings, assume

from quantgambit.deeptrader_core.strategies.mean_reversion_fade import (
    MeanReversionFade,
    DEFAULT_MIN_DISTANCE_FROM_POC_PCT,
)
from quantgambit.deeptrader_core.types import Features, AccountState, Profile


# =============================================================================
# Constants
# =============================================================================

# Floating point tolerance for comparisons
EPSILON = 1e-9


# =============================================================================
# Test Strategies (Generators)
# =============================================================================

# Price in realistic range for crypto
price = st.floats(min_value=10.0, max_value=100000.0, allow_nan=False, allow_infinity=False)

# POC distance percentage (0.01% to 10%)
poc_distance_pct = st.floats(min_value=0.0001, max_value=0.10, allow_nan=False, allow_infinity=False)

# Min distance threshold (0.01% to 5%)
min_distance_threshold = st.floats(min_value=0.0001, max_value=0.05, allow_nan=False, allow_infinity=False)

# Rotation factor for reversal signals
rotation_factor = st.floats(min_value=-10.0, max_value=10.0, allow_nan=False, allow_infinity=False)

# Symbols
symbol = st.sampled_from(["BTCUSDT", "ETHUSDT", "SOLUSDT"])

# Position relative to POC
position_above_poc = st.booleans()


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def strategy():
    return MeanReversionFade()


@pytest.fixture
def account():
    return AccountState(
        equity=10000.0,
        daily_pnl=0.0,
        max_daily_loss=-500.0,
        open_positions=0,
        symbol_open_positions=0,
        symbol_daily_pnl=0.0,
    )


@pytest.fixture
def profile():
    return Profile(
        id="test_profile",
        trend="flat",
        volatility="low",
        value_location="below",
        session="us",
        risk_mode="normal",
    )


def make_features(
    sym: str,
    current_price: float,
    poc_distance_pct: float,
    above_poc: bool,
    rotation: float,
) -> Features:
    """Create Features with specified POC distance.
    
    The POC distance is calculated as: abs(price - poc) / price
    So if we want a specific distance_pct, we calculate:
    - If above POC: poc = price * (1 - distance_pct)
    - If below POC: poc = price * (1 + distance_pct)
    """
    if above_poc:
        # Price above POC: poc = price * (1 - distance_pct)
        # So distance_to_poc = price - poc = price * distance_pct (positive)
        poc = current_price * (1 - poc_distance_pct)
        distance_to_poc = current_price - poc  # Positive
        position_in_value = "above"
    else:
        # Price below POC: poc = price * (1 + distance_pct)
        # So distance_to_poc = price - poc = -price * distance_pct (negative)
        poc = current_price * (1 + poc_distance_pct)
        distance_to_poc = current_price - poc  # Negative
        position_in_value = "below"
    
    return Features(
        symbol=sym,
        price=current_price,
        spread=0.0001,  # Low spread to pass spread check
        rotation_factor=rotation,
        position_in_value=position_in_value,
        point_of_control=poc,
        distance_to_poc=distance_to_poc,
        orderflow_imbalance=0.0,  # Neutral orderflow
        atr_5m=0.5,  # Low ATR
        atr_5m_baseline=1.0,  # ATR ratio = 0.5 (calm market)
    )


# =============================================================================
# Property 4: POC Distance Tiered Entry Logic
# Feature: midvol-coverage-restoration, Property 4: POC Distance Tiered Entry Logic
# Validates: Requirements 4.1, 4.2, 4.3
# =============================================================================

@settings(max_examples=100)
@given(
    sym=symbol,
    current_price=price,
    distance_pct=poc_distance_pct,
    threshold_pct=min_distance_threshold,
    above_poc=position_above_poc,
)
def test_property_4_poc_distance_below_threshold_rejects(
    sym: str,
    current_price: float,
    distance_pct: float,
    threshold_pct: float,
    above_poc: bool,
):
    """
    Property 4: POC Distance Below Threshold Rejects Entry
    
    *For any* mean_reversion_fade signal evaluation where POC distance < min_distance_from_poc_pct,
    the strategy SHALL reject the entry (return None).
    
    **Validates: Requirements 4.1**
    """
    # Only test cases where distance is clearly below threshold (with buffer for floating point)
    assume(distance_pct < threshold_pct - EPSILON)
    
    strategy = MeanReversionFade()
    account = AccountState(
        equity=10000.0,
        daily_pnl=0.0,
        max_daily_loss=-500.0,
        open_positions=0,
        symbol_open_positions=0,
        symbol_daily_pnl=0.0,
    )
    profile = Profile(
        id="test_profile",
        trend="flat",
        volatility="low",
        value_location="below" if not above_poc else "above",
        session="us",
        risk_mode="normal",
    )
    
    # Set rotation to trigger reversal signal
    rotation = -1.0 if above_poc else 1.0  # Reversal direction
    
    features = make_features(
        sym=sym,
        current_price=current_price,
        poc_distance_pct=distance_pct,
        above_poc=above_poc,
        rotation=rotation,
    )
    
    params = {
        "min_distance_from_poc_pct": threshold_pct,
        "max_atr_ratio": 1.0,  # Allow calm markets
        "min_edge_bps": 0.0,  # Disable fee filtering for this test
        "fee_bps": 0.0,
        "slippage_bps": 0.0,
    }
    
    signal = strategy.generate_signal(features, account, profile, params)
    
    # Property: distance below threshold should reject
    assert signal is None, \
        f"Signal should be rejected when POC distance {distance_pct:.4%} < threshold {threshold_pct:.4%}"


@settings(max_examples=100)
@given(
    sym=symbol,
    current_price=price,
    distance_pct=poc_distance_pct,
    threshold_pct=min_distance_threshold,
    above_poc=position_above_poc,
)
def test_property_4_poc_distance_above_threshold_accepts(
    sym: str,
    current_price: float,
    distance_pct: float,
    threshold_pct: float,
    above_poc: bool,
):
    """
    Property 4: POC Distance Above Threshold Accepts Entry
    
    *For any* mean_reversion_fade signal evaluation where POC distance >= min_distance_from_poc_pct
    AND all other conditions are met, the strategy SHALL accept the entry (return signal).
    
    **Validates: Requirements 4.2, 4.3**
    """
    # Only test cases where distance is clearly above threshold (with buffer for floating point)
    assume(distance_pct > threshold_pct + EPSILON)
    # Ensure distance is large enough for fee-aware check to pass
    assume(distance_pct >= 0.001)  # At least 0.1% for edge
    
    strategy = MeanReversionFade()
    account = AccountState(
        equity=10000.0,
        daily_pnl=0.0,
        max_daily_loss=-500.0,
        open_positions=0,
        symbol_open_positions=0,
        symbol_daily_pnl=0.0,
    )
    profile = Profile(
        id="test_profile",
        trend="flat",
        volatility="low",
        value_location="below" if not above_poc else "above",
        session="us",
        risk_mode="normal",
    )
    
    # Set rotation to trigger reversal signal
    rotation = -1.0 if above_poc else 1.0  # Reversal direction
    
    features = make_features(
        sym=sym,
        current_price=current_price,
        poc_distance_pct=distance_pct,
        above_poc=above_poc,
        rotation=rotation,
    )
    
    params = {
        "min_distance_from_poc_pct": threshold_pct,
        "max_atr_ratio": 1.0,  # Allow calm markets
        "min_edge_bps": 0.0,  # Disable fee filtering for this test
        "fee_bps": 0.0,
        "slippage_bps": 0.0,
    }
    
    signal = strategy.generate_signal(features, account, profile, params)
    
    # Property: distance at or above threshold should accept (if other conditions met)
    assert signal is not None, \
        f"Signal should be accepted when POC distance {distance_pct:.4%} > threshold {threshold_pct:.4%}"
    
    # Verify signal direction matches position
    if above_poc:
        assert signal.side == "short", "Should be SHORT when price above POC"
    else:
        assert signal.side == "long", "Should be LONG when price below POC"


@settings(max_examples=100)
@given(
    sym=symbol,
    current_price=price,
    distance_pct=poc_distance_pct,
    above_poc=position_above_poc,
)
def test_property_4_default_threshold_applied(
    sym: str,
    current_price: float,
    distance_pct: float,
    above_poc: bool,
):
    """
    Property 4: Default Threshold Applied When Not Specified
    
    *For any* mean_reversion_fade signal evaluation without explicit min_distance_from_poc_pct,
    the strategy SHALL use DEFAULT_MIN_DISTANCE_FROM_POC_PCT (0.003 = 0.3%).
    
    **Validates: Requirements 4.1**
    """
    strategy = MeanReversionFade()
    account = AccountState(
        equity=10000.0,
        daily_pnl=0.0,
        max_daily_loss=-500.0,
        open_positions=0,
        symbol_open_positions=0,
        symbol_daily_pnl=0.0,
    )
    profile = Profile(
        id="test_profile",
        trend="flat",
        volatility="low",
        value_location="below" if not above_poc else "above",
        session="us",
        risk_mode="normal",
    )
    
    # Set rotation to trigger reversal signal
    rotation = -1.0 if above_poc else 1.0
    
    features = make_features(
        sym=sym,
        current_price=current_price,
        poc_distance_pct=distance_pct,
        above_poc=above_poc,
        rotation=rotation,
    )
    
    # No min_distance_from_poc_pct specified - should use default
    params = {
        "max_atr_ratio": 1.0,
        "min_edge_bps": 0.0,
        "fee_bps": 0.0,
        "slippage_bps": 0.0,
    }
    
    signal = strategy.generate_signal(features, account, profile, params)
    
    # Property: default threshold (0.003) should be applied
    # Use buffer to avoid floating point issues at boundary
    if distance_pct < DEFAULT_MIN_DISTANCE_FROM_POC_PCT - EPSILON:
        assert signal is None, \
            f"Signal should be rejected when distance {distance_pct:.4%} < default {DEFAULT_MIN_DISTANCE_FROM_POC_PCT:.4%}"
    elif distance_pct > DEFAULT_MIN_DISTANCE_FROM_POC_PCT + EPSILON and distance_pct >= 0.001:
        # Ensure enough edge for fee check
        assert signal is not None, \
            f"Signal should be accepted when distance {distance_pct:.4%} > default {DEFAULT_MIN_DISTANCE_FROM_POC_PCT:.4%}"


@settings(max_examples=100)
@given(
    sym=symbol,
    current_price=price,
    above_poc=position_above_poc,
)
def test_property_4_new_default_is_0_003(
    sym: str,
    current_price: float,
    above_poc: bool,
):
    """
    Property 4: New Default Threshold is 0.3%
    
    Verify that DEFAULT_MIN_DISTANCE_FROM_POC_PCT is 0.003 (0.3%) as per
    the midvol-coverage-restoration spec.
    
    **Validates: Requirements 4.1**
    """
    # Property: default threshold should be 0.003 (0.3%)
    assert DEFAULT_MIN_DISTANCE_FROM_POC_PCT == 0.003, \
        f"DEFAULT_MIN_DISTANCE_FROM_POC_PCT should be 0.003, got {DEFAULT_MIN_DISTANCE_FROM_POC_PCT}"


@settings(max_examples=100)
@given(
    sym=symbol,
    current_price=price,
    threshold_pct=min_distance_threshold,
    above_poc=position_above_poc,
)
def test_property_4_boundary_at_threshold(
    sym: str,
    current_price: float,
    threshold_pct: float,
    above_poc: bool,
):
    """
    Property 4: Boundary Condition at Exact Threshold
    
    *For any* mean_reversion_fade signal evaluation where POC distance is slightly above
    min_distance_from_poc_pct, the strategy SHALL accept the entry (>= comparison).
    
    Note: Due to floating point precision, we test with distance slightly above threshold
    rather than exactly at threshold.
    
    **Validates: Requirements 4.2**
    """
    # Ensure threshold is large enough for fee check
    assume(threshold_pct >= 0.001)
    
    strategy = MeanReversionFade()
    account = AccountState(
        equity=10000.0,
        daily_pnl=0.0,
        max_daily_loss=-500.0,
        open_positions=0,
        symbol_open_positions=0,
        symbol_daily_pnl=0.0,
    )
    profile = Profile(
        id="test_profile",
        trend="flat",
        volatility="low",
        value_location="below" if not above_poc else "above",
        session="us",
        risk_mode="normal",
    )
    
    # Set rotation to trigger reversal signal
    rotation = -1.0 if above_poc else 1.0
    
    # Use distance slightly above threshold to avoid floating point issues
    distance_pct = threshold_pct * 1.01  # 1% above threshold
    
    features = make_features(
        sym=sym,
        current_price=current_price,
        poc_distance_pct=distance_pct,
        above_poc=above_poc,
        rotation=rotation,
    )
    
    params = {
        "min_distance_from_poc_pct": threshold_pct,
        "max_atr_ratio": 1.0,
        "min_edge_bps": 0.0,
        "fee_bps": 0.0,
        "slippage_bps": 0.0,
    }
    
    signal = strategy.generate_signal(features, account, profile, params)
    
    # Property: slightly above threshold should accept
    assert signal is not None, \
        f"Signal should be accepted when POC distance {distance_pct:.4%} > threshold {threshold_pct:.4%}"
