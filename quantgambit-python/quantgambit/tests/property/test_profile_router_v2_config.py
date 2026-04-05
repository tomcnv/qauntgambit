"""
Property-based tests for Profile Router v2 Configuration.

Feature: profile-router-v2, Property 16: Config Validation
Validates: Requirements 9.3

Tests that for any RouterConfig with invalid values (negative thresholds,
weights not summing to 1.0, invalid ranges), the Profile_Router SHALL raise
ValueError with descriptive message.
"""

import pytest
from hypothesis import given, strategies as st, settings, assume
from typing import Dict, Tuple

from quantgambit.deeptrader_core.profiles.router_config import (
    RouterConfig,
    DEFAULT_COMPONENT_WEIGHTS,
    REQUIRED_COMPONENTS,
)


# ============================================================================
# Hypothesis Strategies
# ============================================================================

# Valid ranges for config parameters
positive_floats = st.floats(min_value=0.0, max_value=10000.0, allow_nan=False, allow_infinity=False)
unit_floats = st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False)
small_positive_floats = st.floats(min_value=0.001, max_value=100.0, allow_nan=False, allow_infinity=False)
positive_ints = st.integers(min_value=1, max_value=1000)


@st.composite
def valid_component_weights(draw) -> Dict[str, float]:
    """Generate valid component weights that sum to 1.0."""
    # Generate random positive values for each required component
    components = list(REQUIRED_COMPONENTS)
    raw_weights = [draw(st.floats(min_value=0.01, max_value=1.0, allow_nan=False, allow_infinity=False)) 
                   for _ in range(len(components))]
    total = sum(raw_weights)
    
    # Normalize to sum to 1.0
    return {comp: raw_weights[i] / total for i, comp in enumerate(components)}


@st.composite
def invalid_weights_wrong_sum(draw) -> Dict[str, float]:
    """Generate component weights that don't sum to 1.0."""
    # Generate weights that sum to something other than 1.0
    multiplier = draw(st.sampled_from([0.5, 0.8, 1.2, 1.5, 2.0]))
    weights = {comp: DEFAULT_COMPONENT_WEIGHTS[comp] * multiplier 
               for comp in REQUIRED_COMPONENTS}
    return weights


@st.composite
def invalid_weights_missing_component(draw) -> Dict[str, float]:
    """Generate component weights missing a required component."""
    weights = DEFAULT_COMPONENT_WEIGHTS.copy()
    # Remove one component
    component_to_remove = draw(st.sampled_from(list(REQUIRED_COMPONENTS)))
    del weights[component_to_remove]
    # Renormalize remaining
    total = sum(weights.values())
    if total > 0:
        weights = {k: v / total for k, v in weights.items()}
    return weights


@st.composite
def invalid_weights_unknown_component(draw) -> Dict[str, float]:
    """Generate component weights with an unknown component."""
    weights = DEFAULT_COMPONENT_WEIGHTS.copy()
    unknown_name = draw(st.text(min_size=5, max_size=20, alphabet="abcdefghijklmnopqrstuvwxyz_"))
    assume(unknown_name not in REQUIRED_COMPONENTS)
    # Add unknown component and renormalize
    weights[unknown_name] = 0.1
    total = sum(weights.values())
    weights = {k: v / total for k, v in weights.items()}
    return weights


@st.composite
def valid_hysteresis_low_band(draw) -> Tuple[float, float]:
    """Generate valid low band (entry < exit)."""
    entry = draw(st.floats(min_value=0.1, max_value=0.7, allow_nan=False, allow_infinity=False))
    exit_val = draw(st.floats(min_value=entry + 0.05, max_value=0.95, allow_nan=False, allow_infinity=False))
    return (entry, exit_val)


@st.composite
def valid_hysteresis_high_band(draw) -> Tuple[float, float]:
    """Generate valid high band (entry > exit)."""
    exit_val = draw(st.floats(min_value=1.05, max_value=1.4, allow_nan=False, allow_infinity=False))
    entry = draw(st.floats(min_value=exit_val + 0.05, max_value=2.0, allow_nan=False, allow_infinity=False))
    return (entry, exit_val)


@st.composite
def valid_trend_band(draw) -> Tuple[float, float]:
    """Generate valid trend direction band (entry > exit)."""
    exit_val = draw(st.floats(min_value=0.0001, max_value=0.005, allow_nan=False, allow_infinity=False))
    entry = draw(st.floats(min_value=exit_val + 0.0001, max_value=0.01, allow_nan=False, allow_infinity=False))
    return (entry, exit_val)


@st.composite
def valid_perf_multiplier_range(draw) -> Tuple[float, float]:
    """Generate valid performance multiplier range (min <= max)."""
    min_val = draw(st.floats(min_value=0.1, max_value=1.0, allow_nan=False, allow_infinity=False))
    max_val = draw(st.floats(min_value=min_val, max_value=5.0, allow_nan=False, allow_infinity=False))
    return (min_val, max_val)


@st.composite
def valid_router_configs(draw) -> RouterConfig:
    """Generate valid RouterConfig instances."""
    return RouterConfig(
        min_profile_ttl_sec=draw(positive_floats),
        switch_margin=draw(unit_floats),
        component_weights=draw(valid_component_weights()),
        max_safe_spread_bps=draw(positive_floats),
        min_safe_depth_usd=draw(positive_floats),
        min_safe_tps=draw(positive_floats),
        max_book_age_ms=draw(positive_floats),
        max_trade_age_ms=draw(positive_floats),
        vol_regime_low_band=draw(valid_hysteresis_low_band()),
        vol_regime_high_band=draw(valid_hysteresis_high_band()),
        trend_direction_band=draw(valid_trend_band()),
        min_trades_for_perf_adjustment=draw(st.integers(min_value=0, max_value=1000)),
        perf_multiplier_range=draw(valid_perf_multiplier_range()),
        perf_decay_half_life_trades=draw(positive_ints),
        regime_soft_penalty=draw(unit_floats),
        squeeze_liquidity_threshold=draw(unit_floats),
        chop_cost_threshold_bps=draw(positive_floats),
        trend_strength_for_range_to_trend=draw(positive_floats),
        use_v2_scoring=draw(st.booleans()),
    )


# ============================================================================
# Property Tests
# ============================================================================

class TestConfigValidation:
    """
    Property 16: Config Validation
    
    For any RouterConfig with invalid values (negative thresholds, weights not
    summing to 1.0, invalid ranges), the Profile_Router SHALL raise ValueError
    with descriptive message.
    
    **Feature: profile-router-v2, Property 16: Config Validation**
    **Validates: Requirements 9.3**
    """
    
    @given(config=valid_router_configs())
    @settings(max_examples=100)
    def test_valid_config_does_not_raise(self, config: RouterConfig):
        """
        Property 16: Config Validation
        
        For any valid RouterConfig, initialization should succeed without raising.
        
        **Validates: Requirements 9.3**
        """
        # If we got here, the config was created successfully
        # Verify it can be validated again without error
        config.validate()
        assert True
    
    @given(negative_ttl=st.floats(min_value=-10000.0, max_value=-0.001, allow_nan=False, allow_infinity=False))
    @settings(max_examples=100)
    def test_negative_ttl_raises_error(self, negative_ttl: float):
        """
        Property 16: Config Validation
        
        For any negative min_profile_ttl_sec, RouterConfig SHALL raise ValueError.
        
        **Validates: Requirements 9.3**
        """
        with pytest.raises(ValueError) as exc_info:
            RouterConfig(min_profile_ttl_sec=negative_ttl)
        
        assert "min_profile_ttl_sec" in str(exc_info.value)
    
    @given(invalid_margin=st.one_of(
        st.floats(min_value=-10.0, max_value=-0.001, allow_nan=False, allow_infinity=False),
        st.floats(min_value=1.001, max_value=10.0, allow_nan=False, allow_infinity=False)
    ))
    @settings(max_examples=100)
    def test_invalid_switch_margin_raises_error(self, invalid_margin: float):
        """
        Property 16: Config Validation
        
        For any switch_margin outside [0.0, 1.0], RouterConfig SHALL raise ValueError.
        
        **Validates: Requirements 9.3**
        """
        with pytest.raises(ValueError) as exc_info:
            RouterConfig(switch_margin=invalid_margin)
        
        assert "switch_margin" in str(exc_info.value)
    
    @given(weights=invalid_weights_wrong_sum())
    @settings(max_examples=100)
    def test_weights_not_summing_to_one_raises_error(self, weights: Dict[str, float]):
        """
        Property 16: Config Validation
        
        For any component_weights not summing to 1.0, RouterConfig SHALL raise ValueError.
        
        **Validates: Requirements 9.3**
        """
        total = sum(weights.values())
        assume(abs(total - 1.0) > 0.001)  # Ensure weights don't accidentally sum to 1.0
        
        with pytest.raises(ValueError) as exc_info:
            RouterConfig(component_weights=weights)
        
        assert "sum to 1.0" in str(exc_info.value)
    
    @given(weights=invalid_weights_missing_component())
    @settings(max_examples=100)
    def test_missing_component_raises_error(self, weights: Dict[str, float]):
        """
        Property 16: Config Validation
        
        For any component_weights missing required components, RouterConfig SHALL raise ValueError.
        
        **Validates: Requirements 9.3**
        """
        with pytest.raises(ValueError) as exc_info:
            RouterConfig(component_weights=weights)
        
        assert "missing required components" in str(exc_info.value)
    
    @given(weights=invalid_weights_unknown_component())
    @settings(max_examples=100)
    def test_unknown_component_raises_error(self, weights: Dict[str, float]):
        """
        Property 16: Config Validation
        
        For any component_weights with unknown components, RouterConfig SHALL raise ValueError.
        
        **Validates: Requirements 9.3**
        """
        with pytest.raises(ValueError) as exc_info:
            RouterConfig(component_weights=weights)
        
        assert "unknown components" in str(exc_info.value)
    
    @given(
        entry=st.floats(min_value=0.7, max_value=0.95, allow_nan=False, allow_infinity=False),
        exit_val=st.floats(min_value=0.1, max_value=0.65, allow_nan=False, allow_infinity=False)
    )
    @settings(max_examples=100)
    def test_invalid_low_band_raises_error(self, entry: float, exit_val: float):
        """
        Property 16: Config Validation
        
        For vol_regime_low_band where entry >= exit, RouterConfig SHALL raise ValueError.
        
        **Validates: Requirements 9.3**
        """
        assume(entry >= exit_val)  # Ensure invalid condition
        
        with pytest.raises(ValueError) as exc_info:
            RouterConfig(vol_regime_low_band=(entry, exit_val))
        
        assert "vol_regime_low_band" in str(exc_info.value)
    
    @given(
        entry=st.floats(min_value=1.0, max_value=1.2, allow_nan=False, allow_infinity=False),
        exit_val=st.floats(min_value=1.25, max_value=1.5, allow_nan=False, allow_infinity=False)
    )
    @settings(max_examples=100)
    def test_invalid_high_band_raises_error(self, entry: float, exit_val: float):
        """
        Property 16: Config Validation
        
        For vol_regime_high_band where entry <= exit, RouterConfig SHALL raise ValueError.
        
        **Validates: Requirements 9.3**
        """
        assume(entry <= exit_val)  # Ensure invalid condition
        
        with pytest.raises(ValueError) as exc_info:
            RouterConfig(vol_regime_high_band=(entry, exit_val))
        
        assert "vol_regime_high_band" in str(exc_info.value)
    
    @given(
        min_mult=st.floats(min_value=1.5, max_value=3.0, allow_nan=False, allow_infinity=False),
        max_mult=st.floats(min_value=0.5, max_value=1.4, allow_nan=False, allow_infinity=False)
    )
    @settings(max_examples=100)
    def test_invalid_perf_multiplier_range_raises_error(self, min_mult: float, max_mult: float):
        """
        Property 16: Config Validation
        
        For perf_multiplier_range where max < min, RouterConfig SHALL raise ValueError.
        
        **Validates: Requirements 9.3**
        """
        assume(max_mult < min_mult)  # Ensure invalid condition
        
        with pytest.raises(ValueError) as exc_info:
            RouterConfig(perf_multiplier_range=(min_mult, max_mult))
        
        assert "perf_multiplier_range" in str(exc_info.value)
    
    @given(negative_threshold=st.floats(min_value=-10000.0, max_value=-0.001, allow_nan=False, allow_infinity=False))
    @settings(max_examples=100)
    def test_negative_spread_threshold_raises_error(self, negative_threshold: float):
        """
        Property 16: Config Validation
        
        For any negative max_safe_spread_bps, RouterConfig SHALL raise ValueError.
        
        **Validates: Requirements 9.3**
        """
        with pytest.raises(ValueError) as exc_info:
            RouterConfig(max_safe_spread_bps=negative_threshold)
        
        assert "max_safe_spread_bps" in str(exc_info.value)
    
    @given(zero_or_negative=st.integers(min_value=-100, max_value=0))
    @settings(max_examples=100)
    def test_non_positive_decay_half_life_raises_error(self, zero_or_negative: int):
        """
        Property 16: Config Validation
        
        For any non-positive perf_decay_half_life_trades, RouterConfig SHALL raise ValueError.
        
        **Validates: Requirements 9.3**
        """
        with pytest.raises(ValueError) as exc_info:
            RouterConfig(perf_decay_half_life_trades=zero_or_negative)
        
        assert "perf_decay_half_life_trades" in str(exc_info.value)


class TestDefaultConfig:
    """Tests for default configuration values."""
    
    def test_default_config_is_valid(self):
        """Default RouterConfig should be valid."""
        config = RouterConfig()
        config.validate()
        assert config.use_v2_scoring is True
        assert config.min_profile_ttl_sec == 75.0
        assert config.switch_margin == 0.06
    
    def test_default_weights_sum_to_one(self):
        """Default component weights should sum to 1.0."""
        config = RouterConfig()
        total = sum(config.component_weights.values())
        assert abs(total - 1.0) < 0.001


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


# ============================================================================
# Property Tests for Config Updates (Task 14.2)
# ============================================================================

class TestConfigUpdates:
    """
    Property tests for runtime config updates.
    
    Verifies that config changes affect router behavior.
    
    **Feature: profile-router-v2, Config Updates**
    **Validates: Requirements 9.2**
    """
    
    @given(
        initial_ttl=st.floats(min_value=60.0, max_value=300.0, allow_nan=False, allow_infinity=False),
        new_ttl=st.floats(min_value=60.0, max_value=300.0, allow_nan=False, allow_infinity=False)
    )
    @settings(max_examples=100)
    def test_update_config_changes_ttl(self, initial_ttl: float, new_ttl: float):
        """
        Config updates should change the TTL parameter.
        
        For any valid initial and new TTL values, updating the config
        should result in the router using the new TTL value.
        
        **Validates: Requirements 9.2**
        """
        from quantgambit.deeptrader_core.profiles.profile_router import ProfileRouter
        
        # Create router with initial config
        initial_config = RouterConfig(min_profile_ttl_sec=initial_ttl)
        router = ProfileRouter(config=initial_config)
        
        assert router.config.min_profile_ttl_sec == initial_ttl
        
        # Update config
        new_config = RouterConfig(min_profile_ttl_sec=new_ttl)
        router.update_config(new_config)
        
        # Verify config was updated
        assert router.config.min_profile_ttl_sec == new_ttl
        # Verify stability manager also got updated
        assert router.stability_manager.config.min_profile_ttl_sec == new_ttl
    
    @given(
        initial_margin=st.floats(min_value=0.05, max_value=0.3, allow_nan=False, allow_infinity=False),
        new_margin=st.floats(min_value=0.05, max_value=0.3, allow_nan=False, allow_infinity=False)
    )
    @settings(max_examples=100)
    def test_update_config_changes_switch_margin(self, initial_margin: float, new_margin: float):
        """
        Config updates should change the switch margin parameter.
        
        For any valid initial and new switch margin values, updating the config
        should result in the router using the new switch margin value.
        
        **Validates: Requirements 9.2**
        """
        from quantgambit.deeptrader_core.profiles.profile_router import ProfileRouter
        
        # Create router with initial config
        initial_config = RouterConfig(switch_margin=initial_margin)
        router = ProfileRouter(config=initial_config)
        
        assert router.config.switch_margin == initial_margin
        
        # Update config
        new_config = RouterConfig(switch_margin=new_margin)
        router.update_config(new_config)
        
        # Verify config was updated
        assert router.config.switch_margin == new_margin
        # Verify stability manager also got updated
        assert router.stability_manager.config.switch_margin == new_margin
    
    @given(
        initial_spread=st.floats(min_value=20.0, max_value=100.0, allow_nan=False, allow_infinity=False),
        new_spread=st.floats(min_value=20.0, max_value=100.0, allow_nan=False, allow_infinity=False)
    )
    @settings(max_examples=100)
    def test_update_config_changes_hard_filter_thresholds(self, initial_spread: float, new_spread: float):
        """
        Config updates should change hard filter threshold parameters.
        
        For any valid initial and new spread threshold values, updating the config
        should result in the router using the new threshold value.
        
        **Validates: Requirements 9.2**
        """
        from quantgambit.deeptrader_core.profiles.profile_router import ProfileRouter
        
        # Create router with initial config
        initial_config = RouterConfig(max_safe_spread_bps=initial_spread)
        router = ProfileRouter(config=initial_config)
        
        assert router.config.max_safe_spread_bps == initial_spread
        
        # Update config
        new_config = RouterConfig(max_safe_spread_bps=new_spread)
        router.update_config(new_config)
        
        # Verify config was updated
        assert router.config.max_safe_spread_bps == new_spread
    
    @given(
        initial_min_trades=st.integers(min_value=10, max_value=50),
        new_min_trades=st.integers(min_value=10, max_value=50)
    )
    @settings(max_examples=100)
    def test_update_config_changes_perf_adjustment_params(self, initial_min_trades: int, new_min_trades: int):
        """
        Config updates should change performance adjustment parameters.
        
        For any valid initial and new min_trades values, updating the config
        should result in the router using the new value.
        
        **Validates: Requirements 9.2**
        """
        from quantgambit.deeptrader_core.profiles.profile_router import ProfileRouter
        
        # Create router with initial config
        initial_config = RouterConfig(min_trades_for_perf_adjustment=initial_min_trades)
        router = ProfileRouter(config=initial_config)
        
        assert router.config.min_trades_for_perf_adjustment == initial_min_trades
        
        # Update config
        new_config = RouterConfig(min_trades_for_perf_adjustment=new_min_trades)
        router.update_config(new_config)
        
        # Verify config was updated
        assert router.config.min_trades_for_perf_adjustment == new_min_trades
    
    @given(new_config=valid_router_configs())
    @settings(max_examples=100)
    def test_update_config_validates_new_config(self, new_config: RouterConfig):
        """
        Config updates should validate the new config before applying.
        
        For any valid RouterConfig, update_config should succeed.
        
        **Validates: Requirements 9.2, 9.3**
        """
        from quantgambit.deeptrader_core.profiles.profile_router import ProfileRouter
        
        # Create router with default config
        router = ProfileRouter()
        
        # Update with valid config should succeed
        router.update_config(new_config)
        
        # Verify config was updated
        assert router.config == new_config
    
    @given(negative_ttl=st.floats(min_value=-10000.0, max_value=-0.001, allow_nan=False, allow_infinity=False))
    @settings(max_examples=100)
    def test_update_config_rejects_invalid_config(self, negative_ttl: float):
        """
        Config updates should reject invalid configs.
        
        For any invalid RouterConfig, update_config should raise ValueError
        and leave the original config unchanged.
        
        **Validates: Requirements 9.2, 9.3**
        """
        from quantgambit.deeptrader_core.profiles.profile_router import ProfileRouter
        
        # Create router with default config
        router = ProfileRouter()
        original_ttl = router.config.min_profile_ttl_sec
        
        # Create invalid config (negative TTL)
        # We need to bypass __post_init__ validation to create an invalid config
        # So we'll test that update_config validates properly
        invalid_config = RouterConfig.__new__(RouterConfig)
        invalid_config.min_profile_ttl_sec = negative_ttl
        invalid_config.switch_margin = 0.10
        invalid_config.component_weights = DEFAULT_COMPONENT_WEIGHTS.copy()
        invalid_config.max_safe_spread_bps = 50.0
        invalid_config.min_safe_depth_usd = 10000.0
        invalid_config.min_safe_tps = 0.1
        invalid_config.max_book_age_ms = 5000.0
        invalid_config.max_trade_age_ms = 10000.0
        invalid_config.vol_regime_low_band = (0.65, 0.75)
        invalid_config.vol_regime_high_band = (1.35, 1.25)
        invalid_config.trend_direction_band = (0.0012, 0.0008)
        invalid_config.min_trades_for_perf_adjustment = 20
        invalid_config.perf_multiplier_range = (0.7, 1.3)
        invalid_config.perf_decay_half_life_trades = 50
        invalid_config.regime_soft_penalty = 0.15
        invalid_config.squeeze_liquidity_threshold = 0.3
        invalid_config.chop_cost_threshold_bps = 5.0
        invalid_config.trend_strength_for_range_to_trend = 0.003
        invalid_config.use_v2_scoring = True
        
        # Update with invalid config should raise ValueError
        with pytest.raises(ValueError) as exc_info:
            router.update_config(invalid_config)
        
        assert "min_profile_ttl_sec" in str(exc_info.value)
        
        # Original config should be unchanged
        assert router.config.min_profile_ttl_sec == original_ttl
    
    def test_update_config_propagates_to_stability_manager(self):
        """
        Config updates should propagate to the stability manager.
        
        When update_config is called, the stability manager should
        receive the new config.
        
        **Validates: Requirements 9.2**
        """
        from quantgambit.deeptrader_core.profiles.profile_router import ProfileRouter
        
        # Create router with initial config
        initial_config = RouterConfig(
            min_profile_ttl_sec=60.0,
            switch_margin=0.05
        )
        router = ProfileRouter(config=initial_config)
        
        # Verify initial state
        assert router.stability_manager.config.min_profile_ttl_sec == 60.0
        assert router.stability_manager.config.switch_margin == 0.05
        
        # Update config
        new_config = RouterConfig(
            min_profile_ttl_sec=180.0,
            switch_margin=0.15
        )
        router.update_config(new_config)
        
        # Verify stability manager was updated
        assert router.stability_manager.config.min_profile_ttl_sec == 180.0
        assert router.stability_manager.config.switch_margin == 0.15
    
    def test_get_config_returns_current_config(self):
        """
        get_config should return the current configuration.
        
        **Validates: Requirements 9.2**
        """
        from quantgambit.deeptrader_core.profiles.profile_router import ProfileRouter
        
        # Create router with custom config
        custom_config = RouterConfig(
            min_profile_ttl_sec=90.0,
            switch_margin=0.08
        )
        router = ProfileRouter(config=custom_config)
        
        # get_config should return the same config
        retrieved_config = router.get_config()
        assert retrieved_config.min_profile_ttl_sec == 90.0
        assert retrieved_config.switch_margin == 0.08
        
        # Update config
        new_config = RouterConfig(
            min_profile_ttl_sec=150.0,
            switch_margin=0.12
        )
        router.update_config(new_config)
        
        # get_config should return the new config
        retrieved_config = router.get_config()
        assert retrieved_config.min_profile_ttl_sec == 150.0
        assert retrieved_config.switch_margin == 0.12
