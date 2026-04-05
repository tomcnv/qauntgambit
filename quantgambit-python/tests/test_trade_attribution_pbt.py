"""
Property-based tests for Trade Attribution.

Feature: midvol-coverage-restoration
Tests correctness properties for:
- Property 8: Trade Attribution

**Validates: Requirements 8.5**

Tests that all generated StrategySignal outputs include profile_id matching
the profile that generated them.
"""

import pytest
from hypothesis import given, strategies as st, settings, assume

from quantgambit.deeptrader_core.strategies.mean_reversion_fade import MeanReversionFade
from quantgambit.deeptrader_core.strategies.vol_expansion import VolExpansion
from quantgambit.deeptrader_core.strategies.breakout_scalp import BreakoutScalp
from quantgambit.deeptrader_core.types import Features, AccountState, Profile, StrategySignal


# =============================================================================
# Constants
# =============================================================================

EPSILON = 1e-9


# =============================================================================
# Test Strategies (Generators)
# =============================================================================

# Price in realistic range for crypto
price = st.floats(min_value=1000.0, max_value=100000.0, allow_nan=False, allow_infinity=False)

# Profile IDs - realistic profile names
profile_id = st.sampled_from([
    "midvol_mean_reversion",
    "midvol_expansion",
    "range_market_scalp",
    "breakout_momentum",
    "low_vol_grind",
    "test_profile_123",
    "custom_profile",
])

# Symbols
symbol = st.sampled_from(["BTCUSDT", "ETHUSDT", "SOLUSDT"])

# Rotation factor for signals
rotation_factor = st.floats(min_value=-15.0, max_value=15.0, allow_nan=False, allow_infinity=False)

# ATR ratio
atr_ratio = st.floats(min_value=0.3, max_value=3.0, allow_nan=False, allow_infinity=False)


# =============================================================================
# Helper Functions
# =============================================================================

def make_mean_reversion_features(
    sym: str,
    current_price: float,
    rotation: float,
    atr_ratio_val: float,
    above_poc: bool,
) -> Features:
    """Create Features suitable for mean_reversion_fade strategy."""
    poc_distance_pct = 0.01  # 1% distance from POC
    
    if above_poc:
        poc = current_price * (1 - poc_distance_pct)
        distance_to_poc = current_price - poc
        position_in_value = "above"
    else:
        poc = current_price * (1 + poc_distance_pct)
        distance_to_poc = current_price - poc
        position_in_value = "below"
    
    return Features(
        symbol=sym,
        price=current_price,
        spread=0.0001,
        rotation_factor=rotation,
        position_in_value=position_in_value,
        point_of_control=poc,
        distance_to_poc=distance_to_poc,
        orderflow_imbalance=0.0,
        atr_5m=atr_ratio_val,
        atr_5m_baseline=1.0,
        value_area_high=current_price * 1.02,
        value_area_low=current_price * 0.98,
        ema_fast_15m=current_price,
        ema_slow_15m=current_price,
    )


def make_vol_expansion_features(
    sym: str,
    current_price: float,
    rotation: float,
    atr_ratio_val: float,
    breakout_long: bool,
) -> Features:
    """Create Features suitable for vol_expansion strategy."""
    if breakout_long:
        vah = current_price * 0.99  # Price above VAH
        val = current_price * 0.95
        poc = current_price * 0.97
        position_in_value = "above"
        ema_fast = current_price * 1.001  # Fast > slow for long
        ema_slow = current_price * 0.999
    else:
        vah = current_price * 1.05
        val = current_price * 1.01  # Price below VAL
        poc = current_price * 1.03
        position_in_value = "below"
        ema_fast = current_price * 0.999  # Fast < slow for short
        ema_slow = current_price * 1.001
    
    return Features(
        symbol=sym,
        price=current_price,
        spread=0.0001,
        rotation_factor=rotation,
        position_in_value=position_in_value,
        point_of_control=poc,
        distance_to_poc=current_price - poc,
        orderflow_imbalance=0.0,
        atr_5m=atr_ratio_val,
        atr_5m_baseline=1.0,
        value_area_high=vah,
        value_area_low=val,
        ema_fast_15m=ema_fast,
        ema_slow_15m=ema_slow,
    )


def make_breakout_features(
    sym: str,
    current_price: float,
    rotation: float,
    atr_ratio_val: float,
    breakout_long: bool,
) -> Features:
    """Create Features suitable for breakout_scalp strategy."""
    if breakout_long:
        vah = current_price * 0.98  # Price well above VAH
        val = current_price * 0.94
        poc = current_price * 0.96
        position_in_value = "above"
    else:
        vah = current_price * 1.06
        val = current_price * 1.02  # Price well below VAL
        poc = current_price * 1.04
        position_in_value = "below"
    
    return Features(
        symbol=sym,
        price=current_price,
        spread=0.0001,
        rotation_factor=rotation,
        position_in_value=position_in_value,
        point_of_control=poc,
        distance_to_poc=current_price - poc,
        orderflow_imbalance=0.0,
        atr_5m=atr_ratio_val,
        atr_5m_baseline=1.0,
        value_area_high=vah,
        value_area_low=val,
        ema_fast_15m=current_price,
        ema_slow_15m=current_price,
    )


def make_account() -> AccountState:
    """Create standard account state for testing."""
    return AccountState(
        equity=10000.0,
        daily_pnl=0.0,
        max_daily_loss=-500.0,
        open_positions=0,
        symbol_open_positions=0,
        symbol_daily_pnl=0.0,
    )


# =============================================================================
# Property 8: Trade Attribution
# Feature: midvol-coverage-restoration, Property 8: Trade Attribution
# Validates: Requirements 8.5
# =============================================================================

@settings(max_examples=100)
@given(
    sym=symbol,
    current_price=price,
    prof_id=profile_id,
)
def test_property_8_mean_reversion_fade_includes_profile_id(
    sym: str,
    current_price: float,
    prof_id: str,
):
    """
    Property 8: Mean Reversion Fade Trade Attribution
    
    *For any* generated StrategySignal from mean_reversion_fade,
    the signal SHALL include profile_id matching the profile that generated it.
    
    **Validates: Requirements 8.5**
    """
    strategy = MeanReversionFade()
    account = make_account()
    
    # Create profile with the generated profile_id
    profile = Profile(
        id=prof_id,
        trend="flat",
        volatility="low",
        value_location="below",
        session="us",
        risk_mode="normal",
    )
    
    # Create features that will generate a signal (price below POC, rotation positive)
    features = make_mean_reversion_features(
        sym=sym,
        current_price=current_price,
        rotation=1.0,  # Positive rotation for long signal
        atr_ratio_val=0.5,  # Low ATR ratio
        above_poc=False,  # Below POC for long
    )
    
    params = {
        "min_distance_from_poc_pct": 0.001,  # Low threshold to ensure signal
        "max_atr_ratio": 1.0,
        "min_edge_bps": 0.0,
        "fee_bps": 0.0,
        "slippage_bps": 0.0,
    }
    
    signal = strategy.generate_signal(features, account, profile, params)
    
    # If signal is generated, verify profile_id matches
    if signal is not None:
        assert signal.profile_id == prof_id, \
            f"Signal profile_id should be '{prof_id}', got '{signal.profile_id}'"
        assert isinstance(signal, StrategySignal), \
            f"Signal should be StrategySignal, got {type(signal)}"


@settings(max_examples=100)
@given(
    sym=symbol,
    current_price=price,
    prof_id=profile_id,
)
def test_property_8_vol_expansion_includes_profile_id(
    sym: str,
    current_price: float,
    prof_id: str,
):
    """
    Property 8: Vol Expansion Trade Attribution
    
    *For any* generated StrategySignal from vol_expansion,
    the signal SHALL include profile_id matching the profile that generated it.
    
    **Validates: Requirements 8.5**
    """
    strategy = VolExpansion()
    account = make_account()
    
    # Create profile with the generated profile_id
    profile = Profile(
        id=prof_id,
        trend="up",
        volatility="normal",
        value_location="above",
        session="us",
        risk_mode="normal",
    )
    
    # Create features that will generate a long signal
    features = make_vol_expansion_features(
        sym=sym,
        current_price=current_price,
        rotation=8.0,  # Strong positive rotation
        atr_ratio_val=1.5,  # Expanding ATR
        breakout_long=True,
    )
    
    params = {
        "allow_longs": True,
        "allow_shorts": True,
        "expansion_threshold": 1.2,
        "max_atr_ratio": 2.0,
        "min_rotation_factor": 5.0,
        "max_spread": 0.01,
    }
    
    signal = strategy.generate_signal(features, account, profile, params)
    
    # If signal is generated, verify profile_id matches
    if signal is not None:
        assert signal.profile_id == prof_id, \
            f"Signal profile_id should be '{prof_id}', got '{signal.profile_id}'"
        assert isinstance(signal, StrategySignal), \
            f"Signal should be StrategySignal, got {type(signal)}"


@settings(max_examples=100)
@given(
    sym=symbol,
    current_price=price,
    prof_id=profile_id,
)
def test_property_8_breakout_scalp_includes_profile_id(
    sym: str,
    current_price: float,
    prof_id: str,
):
    """
    Property 8: Breakout Scalp Trade Attribution
    
    *For any* generated StrategySignal from breakout_scalp,
    the signal SHALL include profile_id matching the profile that generated it.
    
    **Validates: Requirements 8.5**
    """
    strategy = BreakoutScalp()
    account = make_account()
    
    # Create profile with the generated profile_id
    profile = Profile(
        id=prof_id,
        trend="up",
        volatility="high",
        value_location="above",
        session="us",
        risk_mode="normal",
    )
    
    # Create features that will generate a long breakout signal
    features = make_breakout_features(
        sym=sym,
        current_price=current_price,
        rotation=10.0,  # Strong positive rotation
        atr_ratio_val=1.5,  # High ATR
        breakout_long=True,
    )
    
    params = {
        "allow_longs": True,
        "allow_shorts": True,
        "rotation_threshold": 7.0,
        "min_atr_ratio": 1.0,
        "max_spread": 0.01,
        "min_edge_bps": 0.0,
        "fee_bps": 0.0,
        "slippage_bps": 0.0,
    }
    
    signal = strategy.generate_signal(features, account, profile, params)
    
    # If signal is generated, verify profile_id matches
    if signal is not None:
        assert signal.profile_id == prof_id, \
            f"Signal profile_id should be '{prof_id}', got '{signal.profile_id}'"
        assert isinstance(signal, StrategySignal), \
            f"Signal should be StrategySignal, got {type(signal)}"


@settings(max_examples=100)
@given(
    sym=symbol,
    current_price=price,
    prof_id=profile_id,
)
def test_property_8_profile_id_is_required_field(
    sym: str,
    current_price: float,
    prof_id: str,
):
    """
    Property 8: Profile ID is Required Field
    
    *For any* StrategySignal, the profile_id field SHALL be a required field
    (not Optional) and SHALL be a non-empty string.
    
    **Validates: Requirements 8.5**
    """
    strategy = MeanReversionFade()
    account = make_account()
    
    profile = Profile(
        id=prof_id,
        trend="flat",
        volatility="low",
        value_location="below",
        session="us",
        risk_mode="normal",
    )
    
    features = make_mean_reversion_features(
        sym=sym,
        current_price=current_price,
        rotation=1.0,
        atr_ratio_val=0.5,
        above_poc=False,
    )
    
    params = {
        "min_distance_from_poc_pct": 0.001,
        "max_atr_ratio": 1.0,
        "min_edge_bps": 0.0,
        "fee_bps": 0.0,
        "slippage_bps": 0.0,
    }
    
    signal = strategy.generate_signal(features, account, profile, params)
    
    if signal is not None:
        # Property: profile_id must be a non-empty string
        assert hasattr(signal, 'profile_id'), \
            "StrategySignal must have profile_id attribute"
        assert signal.profile_id is not None, \
            "profile_id must not be None"
        assert isinstance(signal.profile_id, str), \
            f"profile_id must be a string, got {type(signal.profile_id)}"
        assert len(signal.profile_id) > 0, \
            "profile_id must not be empty"


@settings(max_examples=100)
@given(
    sym=symbol,
    current_price=price,
    prof_id=profile_id,
    side_long=st.booleans(),
)
def test_property_8_profile_id_preserved_across_sides(
    sym: str,
    current_price: float,
    prof_id: str,
    side_long: bool,
):
    """
    Property 8: Profile ID Preserved Across Both Sides
    
    *For any* generated StrategySignal (long or short),
    the signal SHALL include the same profile_id regardless of trade direction.
    
    **Validates: Requirements 8.5**
    """
    strategy = MeanReversionFade()
    account = make_account()
    
    profile = Profile(
        id=prof_id,
        trend="flat",
        volatility="low",
        value_location="above" if not side_long else "below",
        session="us",
        risk_mode="normal",
    )
    
    # Create features for the specified side
    features = make_mean_reversion_features(
        sym=sym,
        current_price=current_price,
        rotation=-1.0 if not side_long else 1.0,  # Reversal direction
        atr_ratio_val=0.5,
        above_poc=not side_long,  # Above POC for short, below for long
    )
    
    params = {
        "min_distance_from_poc_pct": 0.001,
        "max_atr_ratio": 1.0,
        "min_edge_bps": 0.0,
        "fee_bps": 0.0,
        "slippage_bps": 0.0,
    }
    
    signal = strategy.generate_signal(features, account, profile, params)
    
    if signal is not None:
        # Property: profile_id matches regardless of side
        assert signal.profile_id == prof_id, \
            f"Signal profile_id should be '{prof_id}' for {signal.side} side, got '{signal.profile_id}'"
