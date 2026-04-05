"""
Property-based tests for Profile-to-Strategy Parameter Merging.

Feature: midvol-coverage-restoration
Tests correctness properties for:
- Property 1: Profile-to-Strategy Parameter Merging

**Validates: Requirements 1.2, 1.3, 3.1, 3.2, 3.3, 3.4**

Tests that profiles correctly pass parameter overrides to strategies, with
strategy_params taking precedence over profile risk defaults.
"""

import pytest
from hypothesis import given, strategies as st, settings, assume
from typing import Dict, Any, Optional

from quantgambit.deeptrader_core.strategies.chessboard.profile_spec import (
    ProfileSpec,
    ProfileConditions,
    ProfileRiskParameters,
    ProfileLifecycle,
    ProfileRegistry,
)
from quantgambit.strategies.registry import _strategy_params


# =============================================================================
# Test Strategies (Generators)
# =============================================================================

# Profile IDs
profile_id = st.text(min_size=1, max_size=20, alphabet=st.characters(whitelist_categories=('L', 'N'), whitelist_characters='_'))

# Strategy IDs
strategy_id = st.text(min_size=1, max_size=20, alphabet=st.characters(whitelist_categories=('L', 'N'), whitelist_characters='_'))

# Risk parameters
risk_per_trade_pct = st.floats(min_value=0.1, max_value=5.0, allow_nan=False, allow_infinity=False)
max_leverage = st.floats(min_value=1.0, max_value=10.0, allow_nan=False, allow_infinity=False)
stop_loss_pct = st.floats(min_value=0.001, max_value=0.1, allow_nan=False, allow_infinity=False)
take_profit_pct = st.floats(min_value=0.001, max_value=0.2, allow_nan=False, allow_infinity=False)
max_hold_time = st.floats(min_value=10.0, max_value=3600.0, allow_nan=False, allow_infinity=False)
min_hold_time = st.floats(min_value=1.0, max_value=60.0, allow_nan=False, allow_infinity=False)
time_to_work = st.floats(min_value=1.0, max_value=120.0, allow_nan=False, allow_infinity=False)
mfe_min = st.floats(min_value=1.0, max_value=20.0, allow_nan=False, allow_infinity=False)
expected_horizon = st.floats(min_value=5.0, max_value=300.0, allow_nan=False, allow_infinity=False)

# Strategy-specific override parameters
max_atr_ratio = st.floats(min_value=0.5, max_value=3.0, allow_nan=False, allow_infinity=False)
min_distance_from_poc_pct = st.floats(min_value=0.001, max_value=0.05, allow_nan=False, allow_infinity=False)
rotation_threshold = st.floats(min_value=1.0, max_value=10.0, allow_nan=False, allow_infinity=False)
min_edge_bps = st.floats(min_value=0.0, max_value=20.0, allow_nan=False, allow_infinity=False)
fee_bps = st.floats(min_value=0.0, max_value=10.0, allow_nan=False, allow_infinity=False)
slippage_bps = st.floats(min_value=0.0, max_value=10.0, allow_nan=False, allow_infinity=False)


# =============================================================================
# Helper Functions
# =============================================================================

def create_profile_spec(
    pid: str,
    risk_params: ProfileRiskParameters,
    strategy_ids: list,
    strategy_params: Dict[str, Dict[str, Any]],
) -> ProfileSpec:
    """Create a ProfileSpec with given parameters."""
    return ProfileSpec(
        id=pid,
        name=f"Test Profile {pid}",
        description="Test profile for parameter merging",
        conditions=ProfileConditions(),
        risk=risk_params,
        lifecycle=ProfileLifecycle(),
        strategy_ids=strategy_ids,
        strategy_params=strategy_params,
        tags=["test"],
    )


def create_registry_with_profile(spec: ProfileSpec) -> ProfileRegistry:
    """Create a ProfileRegistry with a single profile registered."""
    registry = ProfileRegistry()
    registry.register(spec)
    return registry


# =============================================================================
# Property 1: Profile-to-Strategy Parameter Merging
# Feature: midvol-coverage-restoration, Property 1: Profile-to-Strategy Parameter Merging
# Validates: Requirements 1.2, 1.3, 3.1, 3.2, 3.3, 3.4
# =============================================================================

@settings(max_examples=100)
@given(
    pid=profile_id,
    sid=strategy_id,
    risk_pct=risk_per_trade_pct,
    leverage=max_leverage,
    sl_pct=stop_loss_pct,
    tp_pct=take_profit_pct,
)
def test_property_1_risk_params_merged_as_base(
    pid: str,
    sid: str,
    risk_pct: float,
    leverage: float,
    sl_pct: float,
    tp_pct: float,
):
    """
    Property 1: Risk Parameters Merged as Base
    
    *For any* profile with risk parameters defined, when _strategy_params is called,
    the returned params dict SHALL contain all risk parameters as base values.
    
    **Validates: Requirements 3.1**
    """
    assume(len(pid) > 0 and len(sid) > 0)
    
    risk_params = ProfileRiskParameters(
        risk_per_trade_pct=risk_pct,
        max_leverage=leverage,
        stop_loss_pct=sl_pct,
        take_profit_pct=tp_pct,
    )
    
    spec = create_profile_spec(
        pid=pid,
        risk_params=risk_params,
        strategy_ids=[sid],
        strategy_params={},  # No strategy-specific overrides
    )
    
    registry = create_registry_with_profile(spec)
    
    params = _strategy_params(pid, sid, registry)
    
    # Property: risk params should be in the result
    assert params["risk_per_trade_pct"] == risk_pct, \
        f"risk_per_trade_pct should be {risk_pct}, got {params.get('risk_per_trade_pct')}"
    assert params["max_leverage"] == leverage, \
        f"max_leverage should be {leverage}, got {params.get('max_leverage')}"
    assert params["stop_loss_pct"] == sl_pct, \
        f"stop_loss_pct should be {sl_pct}, got {params.get('stop_loss_pct')}"
    assert params["take_profit_pct"] == tp_pct, \
        f"take_profit_pct should be {tp_pct}, got {params.get('take_profit_pct')}"


@settings(max_examples=100)
@given(
    pid=profile_id,
    sid=strategy_id,
    risk_pct=risk_per_trade_pct,
    override_atr=max_atr_ratio,
    override_poc=min_distance_from_poc_pct,
)
def test_property_1_strategy_params_override_defaults(
    pid: str,
    sid: str,
    risk_pct: float,
    override_atr: float,
    override_poc: float,
):
    """
    Property 1: Strategy Params Override Defaults
    
    *For any* profile with strategy_params defined for a strategy_id, when _strategy_params
    is called, the strategy_params SHALL override any conflicting base values.
    
    **Validates: Requirements 1.2, 1.3, 3.2, 3.3**
    """
    assume(len(pid) > 0 and len(sid) > 0)
    
    risk_params = ProfileRiskParameters(
        risk_per_trade_pct=risk_pct,
        max_leverage=2.0,
        stop_loss_pct=0.005,
    )
    
    # Define strategy-specific overrides
    strategy_overrides = {
        sid: {
            "max_atr_ratio": override_atr,
            "min_distance_from_poc_pct": override_poc,
        }
    }
    
    spec = create_profile_spec(
        pid=pid,
        risk_params=risk_params,
        strategy_ids=[sid],
        strategy_params=strategy_overrides,
    )
    
    registry = create_registry_with_profile(spec)
    
    params = _strategy_params(pid, sid, registry)
    
    # Property: strategy-specific params should be present
    assert params["max_atr_ratio"] == override_atr, \
        f"max_atr_ratio should be {override_atr}, got {params.get('max_atr_ratio')}"
    assert params["min_distance_from_poc_pct"] == override_poc, \
        f"min_distance_from_poc_pct should be {override_poc}, got {params.get('min_distance_from_poc_pct')}"
    
    # Property: base risk params should still be present
    assert params["risk_per_trade_pct"] == risk_pct, \
        f"risk_per_trade_pct should still be {risk_pct}"


@settings(max_examples=100)
@given(
    pid=profile_id,
    sid=strategy_id,
    base_risk_pct=risk_per_trade_pct,
    override_risk_pct=risk_per_trade_pct,
)
def test_property_1_strategy_params_take_precedence(
    pid: str,
    sid: str,
    base_risk_pct: float,
    override_risk_pct: float,
):
    """
    Property 1: Strategy Params Take Precedence Over Risk Defaults
    
    *For any* profile where both risk params and strategy_params define the same key,
    the strategy_params value SHALL take precedence.
    
    **Validates: Requirements 3.1, 3.2**
    """
    assume(len(pid) > 0 and len(sid) > 0)
    # Ensure they're different to test precedence
    assume(abs(base_risk_pct - override_risk_pct) > 0.01)
    
    risk_params = ProfileRiskParameters(
        risk_per_trade_pct=base_risk_pct,
        max_leverage=2.0,
        stop_loss_pct=0.005,
    )
    
    # Override risk_per_trade_pct in strategy_params
    strategy_overrides = {
        sid: {
            "risk_per_trade_pct": override_risk_pct,
        }
    }
    
    spec = create_profile_spec(
        pid=pid,
        risk_params=risk_params,
        strategy_ids=[sid],
        strategy_params=strategy_overrides,
    )
    
    registry = create_registry_with_profile(spec)
    
    params = _strategy_params(pid, sid, registry)
    
    # Property: strategy_params should override base risk params
    assert params["risk_per_trade_pct"] == override_risk_pct, \
        f"risk_per_trade_pct should be overridden to {override_risk_pct}, got {params.get('risk_per_trade_pct')}"


@settings(max_examples=100)
@given(
    pid=profile_id,
    sid1=strategy_id,
    sid2=strategy_id,
    override1_atr=max_atr_ratio,
    override2_atr=max_atr_ratio,
)
def test_property_1_different_strategies_get_different_params(
    pid: str,
    sid1: str,
    sid2: str,
    override1_atr: float,
    override2_atr: float,
):
    """
    Property 1: Different Strategies Get Different Params
    
    *For any* profile with different strategy_params for different strategy_ids,
    each strategy SHALL receive its own specific params.
    
    **Validates: Requirements 3.3, 3.4**
    """
    assume(len(pid) > 0 and len(sid1) > 0 and len(sid2) > 0)
    assume(sid1 != sid2)
    assume(abs(override1_atr - override2_atr) > 0.01)
    
    risk_params = ProfileRiskParameters(
        risk_per_trade_pct=1.0,
        max_leverage=2.0,
        stop_loss_pct=0.005,
    )
    
    # Different overrides for different strategies
    strategy_overrides = {
        sid1: {"max_atr_ratio": override1_atr},
        sid2: {"max_atr_ratio": override2_atr},
    }
    
    spec = create_profile_spec(
        pid=pid,
        risk_params=risk_params,
        strategy_ids=[sid1, sid2],
        strategy_params=strategy_overrides,
    )
    
    registry = create_registry_with_profile(spec)
    
    params1 = _strategy_params(pid, sid1, registry)
    params2 = _strategy_params(pid, sid2, registry)
    
    # Property: each strategy gets its own params
    assert params1["max_atr_ratio"] == override1_atr, \
        f"Strategy {sid1} should get max_atr_ratio={override1_atr}"
    assert params2["max_atr_ratio"] == override2_atr, \
        f"Strategy {sid2} should get max_atr_ratio={override2_atr}"


@settings(max_examples=100)
@given(
    pid=profile_id,
    sid=strategy_id,
)
def test_property_1_missing_profile_returns_empty(
    pid: str,
    sid: str,
):
    """
    Property 1: Missing Profile Returns Empty Dict
    
    *For any* profile_id that doesn't exist in the registry,
    _strategy_params SHALL return an empty dict.
    
    **Validates: Requirements 3.1 (error handling)**
    """
    assume(len(pid) > 0 and len(sid) > 0)
    
    registry = ProfileRegistry()  # Empty registry
    
    params = _strategy_params(pid, sid, registry)
    
    # Property: missing profile returns empty dict
    assert params == {}, f"Missing profile should return empty dict, got {params}"


@settings(max_examples=100)
@given(
    pid=profile_id,
    sid=strategy_id,
)
def test_property_1_none_profile_id_returns_empty(
    pid: str,
    sid: str,
):
    """
    Property 1: None Profile ID Returns Empty Dict
    
    *For any* None profile_id, _strategy_params SHALL return an empty dict.
    
    **Validates: Requirements 3.1 (error handling)**
    """
    assume(len(pid) > 0 and len(sid) > 0)
    
    risk_params = ProfileRiskParameters(
        risk_per_trade_pct=1.0,
        max_leverage=2.0,
        stop_loss_pct=0.005,
    )
    
    spec = create_profile_spec(
        pid=pid,
        risk_params=risk_params,
        strategy_ids=[sid],
        strategy_params={},
    )
    
    registry = create_registry_with_profile(spec)
    
    params = _strategy_params(None, sid, registry)
    
    # Property: None profile_id returns empty dict
    assert params == {}, f"None profile_id should return empty dict, got {params}"


@settings(max_examples=100)
@given(
    pid=profile_id,
    sid=strategy_id,
    hold_time=max_hold_time,
    min_hold=min_hold_time,
    ttw=time_to_work,
    mfe=mfe_min,
    horizon=expected_horizon,
)
def test_property_1_time_budget_params_merged(
    pid: str,
    sid: str,
    hold_time: float,
    min_hold: float,
    ttw: float,
    mfe: float,
    horizon: float,
):
    """
    Property 1: Time Budget Params Merged
    
    *For any* profile with time budget parameters (max_hold_time_seconds, min_hold_time_seconds,
    time_to_work_sec, mfe_min_bps, expected_horizon_sec), these SHALL be included in the
    merged params.
    
    **Validates: Requirements 3.1**
    """
    assume(len(pid) > 0 and len(sid) > 0)
    assume(min_hold < hold_time)  # min_hold must be less than max_hold
    
    risk_params = ProfileRiskParameters(
        risk_per_trade_pct=1.0,
        max_leverage=2.0,
        stop_loss_pct=0.005,
        max_hold_time_seconds=hold_time,
        min_hold_time_seconds=min_hold,
        time_to_work_sec=ttw,
        mfe_min_bps=mfe,
        expected_horizon_sec=horizon,
    )
    
    spec = create_profile_spec(
        pid=pid,
        risk_params=risk_params,
        strategy_ids=[sid],
        strategy_params={},
    )
    
    registry = create_registry_with_profile(spec)
    
    params = _strategy_params(pid, sid, registry)
    
    # Property: time budget params should be in the result
    assert params["max_hold_time_seconds"] == hold_time, \
        f"max_hold_time_seconds should be {hold_time}"
    assert params["min_hold_time_seconds"] == min_hold, \
        f"min_hold_time_seconds should be {min_hold}"
    assert params["time_to_work_sec"] == ttw, \
        f"time_to_work_sec should be {ttw}"
    assert params["mfe_min_bps"] == mfe, \
        f"mfe_min_bps should be {mfe}"
    assert params["expected_horizon_sec"] == horizon, \
        f"expected_horizon_sec should be {horizon}"


# =============================================================================
# Integration Tests with Real Profiles
# =============================================================================

def test_midvol_mean_reversion_profile_params():
    """
    Integration test: MIDVOL_MEAN_REVERSION profile passes correct params.
    
    Verifies that the MIDVOL_MEAN_REVERSION profile correctly passes:
    - max_atr_ratio: 1.4
    - min_distance_from_poc_pct: 0.003 (0.3%)
    
    **Validates: Requirements 1.2, 1.3**
    """
    from quantgambit.deeptrader_core.strategies.chessboard.canonical_profiles import (
        MIDVOL_MEAN_REVERSION,
    )
    
    registry = ProfileRegistry()
    registry.register(MIDVOL_MEAN_REVERSION)
    
    params = _strategy_params("midvol_mean_reversion", "mean_reversion_fade", registry)
    
    # Verify the key parameters are set correctly
    assert params["max_atr_ratio"] == 1.4, \
        f"max_atr_ratio should be 1.4, got {params.get('max_atr_ratio')}"
    assert params["min_distance_from_poc_pct"] == 0.003, \
        f"min_distance_from_poc_pct should be 0.003, got {params.get('min_distance_from_poc_pct')}"


def test_range_market_scalp_profile_params():
    """
    Integration test: RANGE_MARKET_SCALP profile passes correct params.
    
    Verifies that the RANGE_MARKET_SCALP profile correctly passes:
    - max_atr_ratio: 1.5
    - min_distance_from_poc_pct: 0.003 (0.3%)
    
    **Validates: Requirements 6.2**
    """
    from quantgambit.deeptrader_core.strategies.chessboard.canonical_profiles import (
        RANGE_MARKET_SCALP,
    )
    
    registry = ProfileRegistry()
    registry.register(RANGE_MARKET_SCALP)
    
    params = _strategy_params("range_market_scalp", "mean_reversion_fade", registry)
    
    # Verify the key parameters are set correctly
    assert params["max_atr_ratio"] == 1.5, \
        f"max_atr_ratio should be 1.5, got {params.get('max_atr_ratio')}"
    assert params["min_distance_from_poc_pct"] == 0.003, \
        f"min_distance_from_poc_pct should be 0.003, got {params.get('min_distance_from_poc_pct')}"


def test_midvol_expansion_profile_params():
    """
    Integration test: MIDVOL_EXPANSION profile passes correct params.
    
    Verifies that the MIDVOL_EXPANSION profile correctly passes:
    - expansion_threshold: 1.4
    - rotation_threshold: 3.0
    
    **Validates: Requirements 2.2, 2.3**
    """
    from quantgambit.deeptrader_core.strategies.chessboard.canonical_profiles import (
        MIDVOL_EXPANSION,
    )
    
    registry = ProfileRegistry()
    registry.register(MIDVOL_EXPANSION)
    
    params = _strategy_params("midvol_expansion", "vol_expansion", registry)
    
    # Verify the key parameters are set correctly
    assert params["expansion_threshold"] == 1.4, \
        f"expansion_threshold should be 1.4, got {params.get('expansion_threshold')}"
    assert params["rotation_threshold"] == 3.0, \
        f"rotation_threshold should be 3.0, got {params.get('rotation_threshold')}"
