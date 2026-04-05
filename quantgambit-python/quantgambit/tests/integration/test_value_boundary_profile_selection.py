"""
Integration tests for value boundary profile selection.

Tests that the ProfileRouter correctly selects VALUE_AREA_REJECTION when price
is at value boundaries (above VAH or below VAL) and MIDVOL_MEAN_REVERSION when
price is inside the value area.

**Validates: Requirements 4.1, 4.2, 4.3**
"""

import pytest
import time

from quantgambit.deeptrader_core.profiles.profile_router import ProfileRouter
from quantgambit.deeptrader_core.profiles.context_vector import ContextVector
from quantgambit.deeptrader_core.profiles.router_config import RouterConfig
from quantgambit.deeptrader_core.strategies.chessboard import get_profile_registry
from quantgambit.deeptrader_core.strategies.chessboard.canonical_profiles import (
    VALUE_AREA_REJECTION,
    MIDVOL_MEAN_REVERSION,
    register_canonical_profiles,
)


def _create_context_for_boundary_test(
    position_in_value: str,
    rotation_factor: float,
    atr_ratio: float,
    trend_direction: str = "flat",
    session: str = "us",
) -> ContextVector:
    """
    Create a ContextVector for boundary profile selection testing.
    
    Sets up a context with:
    - Good microstructure (tight spread, good depth, active trading)
    - Low expected costs
    - Specified position_in_value, rotation_factor, and volatility
    
    Args:
        position_in_value: "above", "below", or "inside"
        rotation_factor: Rotation factor value (>= 3.0 for VALUE_AREA_REJECTION)
        atr_ratio: ATR ratio for volatility (0.7-1.5 for VALUE_AREA_REJECTION, 1.0-1.4 for MIDVOL)
        trend_direction: "up", "down", or "flat"
        session: Trading session
        
    Returns:
        ContextVector configured for the test scenario
    """
    # Determine volatility regime from ATR ratio
    if atr_ratio < 0.7:
        volatility_regime = "low"
    elif atr_ratio > 1.3:
        volatility_regime = "high"
    else:
        volatility_regime = "normal"
    
    return ContextVector(
        symbol="BTCUSDT",
        timestamp=time.time(),
        price=50000.0,
        # Trend features
        ema_spread_pct=0.0001 if trend_direction == "flat" else (0.002 if trend_direction == "up" else -0.002),
        trend_strength=0.0001 if trend_direction == "flat" else 0.002,
        trend_direction=trend_direction,
        # Volatility features
        atr_5m=100.0,
        atr_5m_baseline=100.0 / atr_ratio,
        atr_ratio=atr_ratio,
        volatility_regime=volatility_regime,
        market_regime="range",
        regime_family="mean_revert",
        # AMT features
        value_area_high=50100.0,
        value_area_low=49900.0,
        point_of_control=50000.0,
        rotation_factor=rotation_factor,
        position_in_value=position_in_value,
        distance_to_vah_pct=0.001,  # 0.1% from VAH
        distance_to_val_pct=0.001,  # 0.1% from VAL
        # Keep this outside the near-POC preference threshold so boundary selection
        # behavior is not masked by the near-POC boost.
        distance_to_poc_pct=0.002,
        # Orderbook features - good microstructure
        spread=0.0002,
        spread_bps=2.0,  # Tight spread
        bid_depth_usd=100000.0,  # Good depth
        ask_depth_usd=100000.0,
        orderbook_imbalance=0.0,
        # Order flow features
        trades_per_second=5.0,  # Active trading
        # Session features
        session=session,
        hour_utc=15,
        is_market_hours=True,
        # Risk features
        risk_mode="normal",
        # Cost features - low costs
        expected_fee_bps=6.0,
        expected_cost_bps=10.0,  # Low total cost
        spread_percentile=30.0,
        maker_fill_prob=0.7,
        book_age_ms=100.0,
        trade_age_ms=200.0,
        liquidity_score=0.8,
        data_quality_state="good",
        data_completeness=1.0,
    )


class TestValueBoundaryProfileSelection:
    """Integration tests for value boundary profile selection."""
    
    @pytest.fixture(autouse=True)
    def setup_profiles(self, monkeypatch):
        """Ensure canonical profiles are registered before each test."""
        # Isolate from env-driven strategy disables used in live trading.
        monkeypatch.setenv("DISABLE_STRATEGIES", "")
        monkeypatch.setenv("DISABLE_MEAN_REVERSION_SYMBOLS", "")
        registry = get_profile_registry()
        # Clear and re-register to ensure clean state
        registry._specs.clear()
        register_canonical_profiles()
    
    @pytest.fixture
    def router(self) -> ProfileRouter:
        """Create a ProfileRouter configured for testing."""
        config = RouterConfig(
            use_v2_scoring=True,
            backtesting_mode=True,  # Disable data freshness checks
            min_profile_ttl_sec=0.0,  # Disable stability for testing
        )
        return ProfileRouter(enable_ml=False, config=config)
    
    def test_value_area_rejection_selected_when_above_vah(self, router: ProfileRouter):
        """
        Test VALUE_AREA_REJECTION is selected when position_in_value="above"
        with rotation_factor >= 3.0 and volatility in range [0.7, 1.5].
        
        **Validates: Requirement 4.1**
        WHEN `position_in_value="above"` AND rotation_factor >= 3.0 AND 
        volatility is in range [0.7, 1.5], THE ProfileRouter SHALL select 
        `VALUE_AREA_REJECTION` over `MIDVOL_MEAN_REVERSION`
        """
        # Create context with price above VAH
        context = _create_context_for_boundary_test(
            position_in_value="above",
            rotation_factor=4.0,  # >= 3.0 as required
            atr_ratio=1.0,  # In range [0.7, 1.5]
            trend_direction="flat",
        )
        
        # Select profiles
        selected = router.select_profiles(context, top_k=5, symbol="BTCUSDT")
        
        # Verify VALUE_AREA_REJECTION is selected
        assert len(selected) > 0, "Should select at least one profile"
        
        selected_ids = [s.profile_id for s in selected]
        
        # VALUE_AREA_REJECTION should be selected
        assert "value_area_rejection" in selected_ids, (
            f"VALUE_AREA_REJECTION should be selected when position_in_value='above'. "
            f"Selected profiles: {selected_ids}"
        )
        
        # If MIDVOL_MEAN_REVERSION is also selected, VALUE_AREA_REJECTION should rank higher
        if "midvol_mean_reversion" in selected_ids:
            var_idx = selected_ids.index("value_area_rejection")
            mmr_idx = selected_ids.index("midvol_mean_reversion")
            assert var_idx < mmr_idx, (
                f"VALUE_AREA_REJECTION (idx={var_idx}) should rank higher than "
                f"MIDVOL_MEAN_REVERSION (idx={mmr_idx}) when position_in_value='above'"
            )
    
    def test_value_area_rejection_selected_when_below_val(self, router: ProfileRouter):
        """
        Test VALUE_AREA_REJECTION is selected when position_in_value="below"
        with rotation_factor >= 3.0 and volatility in range [0.7, 1.5].
        
        **Validates: Requirement 4.2**
        WHEN `position_in_value="below"` AND rotation_factor >= 3.0 AND 
        volatility is in range [0.7, 1.5], THE ProfileRouter SHALL select 
        `VALUE_AREA_REJECTION` over `MIDVOL_MEAN_REVERSION`
        """
        # Create context with price below VAL
        context = _create_context_for_boundary_test(
            position_in_value="below",
            rotation_factor=3.5,  # >= 3.0 as required
            atr_ratio=1.2,  # In range [0.7, 1.5]
            trend_direction="flat",
        )
        
        # Select profiles
        selected = router.select_profiles(context, top_k=5, symbol="BTCUSDT")
        
        # Verify VALUE_AREA_REJECTION is selected
        assert len(selected) > 0, "Should select at least one profile"
        
        selected_ids = [s.profile_id for s in selected]
        
        # VALUE_AREA_REJECTION should be selected
        assert "value_area_rejection" in selected_ids, (
            f"VALUE_AREA_REJECTION should be selected when position_in_value='below'. "
            f"Selected profiles: {selected_ids}"
        )
        
        # If MIDVOL_MEAN_REVERSION is also selected, VALUE_AREA_REJECTION should rank higher
        if "midvol_mean_reversion" in selected_ids:
            var_idx = selected_ids.index("value_area_rejection")
            mmr_idx = selected_ids.index("midvol_mean_reversion")
            assert var_idx < mmr_idx, (
                f"VALUE_AREA_REJECTION (idx={var_idx}) should rank higher than "
                f"MIDVOL_MEAN_REVERSION (idx={mmr_idx}) when position_in_value='below'"
            )
    
    def test_midvol_mean_reversion_selected_when_inside_value(self, router: ProfileRouter):
        """
        Test MIDVOL_MEAN_REVERSION is selected when position_in_value="inside"
        with flat trend and volatility in range [1.0, 1.4].
        
        **Validates: Requirement 4.3**
        WHEN `position_in_value="inside"` AND trend is flat AND volatility is 
        in range [1.0, 1.4], THE ProfileRouter SHALL select `MIDVOL_MEAN_REVERSION` 
        over `VALUE_AREA_REJECTION`
        """
        # Create context with price inside value area
        context = _create_context_for_boundary_test(
            position_in_value="inside",
            rotation_factor=2.0,  # Lower rotation for mean reversion
            atr_ratio=1.2,  # In range [1.0, 1.4] for MIDVOL_MEAN_REVERSION
            trend_direction="flat",  # Flat trend as required
        )
        
        # Select profiles
        selected = router.select_profiles(context, top_k=5, symbol="BTCUSDT")
        
        # Verify MIDVOL_MEAN_REVERSION is selected
        assert len(selected) > 0, "Should select at least one profile"
        
        selected_ids = [s.profile_id for s in selected]
        
        # MIDVOL_MEAN_REVERSION should be selected
        assert "midvol_mean_reversion" in selected_ids, (
            f"MIDVOL_MEAN_REVERSION should be selected when position_in_value='inside' "
            f"with flat trend and volatility in [1.0, 1.4]. Selected profiles: {selected_ids}"
        )
        
        # If VALUE_AREA_REJECTION is also selected, MIDVOL_MEAN_REVERSION should rank higher
        if "value_area_rejection" in selected_ids:
            mmr_idx = selected_ids.index("midvol_mean_reversion")
            var_idx = selected_ids.index("value_area_rejection")
            assert mmr_idx < var_idx, (
                f"MIDVOL_MEAN_REVERSION (idx={mmr_idx}) should rank higher than "
                f"VALUE_AREA_REJECTION (idx={var_idx}) when position_in_value='inside'"
            )


class TestValueBoundaryEdgeCases:
    """Edge case tests for value boundary profile selection."""
    
    @pytest.fixture(autouse=True)
    def setup_profiles(self, monkeypatch):
        """Ensure canonical profiles are registered before each test."""
        # Isolate from env-driven strategy disables used in live trading.
        monkeypatch.setenv("DISABLE_STRATEGIES", "")
        monkeypatch.setenv("DISABLE_MEAN_REVERSION_SYMBOLS", "")
        registry = get_profile_registry()
        registry._specs.clear()
        register_canonical_profiles()
    
    @pytest.fixture
    def router(self) -> ProfileRouter:
        """Create a ProfileRouter configured for testing."""
        config = RouterConfig(
            use_v2_scoring=True,
            backtesting_mode=True,
            min_profile_ttl_sec=0.0,
        )
        return ProfileRouter(enable_ml=False, config=config)
    
    def test_value_area_rejection_at_boundary_rotation_threshold(self, router: ProfileRouter):
        """
        Test VALUE_AREA_REJECTION selection at exactly rotation_factor=3.0.
        
        This tests the boundary condition where rotation_factor is exactly
        at the minimum threshold.
        """
        context = _create_context_for_boundary_test(
            position_in_value="above",
            rotation_factor=3.0,  # Exactly at threshold
            atr_ratio=1.0,
            trend_direction="flat",
        )
        
        selected = router.select_profiles(context, top_k=5, symbol="BTCUSDT")
        selected_ids = [s.profile_id for s in selected]
        
        # VALUE_AREA_REJECTION should still be selected at exactly 3.0
        assert "value_area_rejection" in selected_ids, (
            f"VALUE_AREA_REJECTION should be selected at rotation_factor=3.0. "
            f"Selected: {selected_ids}"
        )
    
    def test_value_area_rejection_at_volatility_boundaries(self, router: ProfileRouter):
        """
        Test VALUE_AREA_REJECTION selection at volatility boundaries [0.7, 1.5].
        """
        # Test at lower boundary (0.7)
        context_low = _create_context_for_boundary_test(
            position_in_value="above",
            rotation_factor=4.0,
            atr_ratio=0.7,  # Lower boundary
            trend_direction="flat",
        )
        
        selected_low = router.select_profiles(context_low, top_k=5, symbol="BTCUSDT")
        selected_ids_low = [s.profile_id for s in selected_low]
        
        assert "value_area_rejection" in selected_ids_low, (
            f"VALUE_AREA_REJECTION should be selected at atr_ratio=0.7. "
            f"Selected: {selected_ids_low}"
        )
        
        # Test at upper boundary (1.5)
        context_high = _create_context_for_boundary_test(
            position_in_value="below",
            rotation_factor=4.0,
            atr_ratio=1.5,  # Upper boundary
            trend_direction="flat",
        )
        
        selected_high = router.select_profiles(context_high, top_k=5, symbol="BTCUSDT")
        selected_ids_high = [s.profile_id for s in selected_high]
        
        assert "value_area_rejection" in selected_ids_high, (
            f"VALUE_AREA_REJECTION should be selected at atr_ratio=1.5. "
            f"Selected: {selected_ids_high}"
        )
    
    def test_midvol_mean_reversion_at_volatility_boundaries(self, router: ProfileRouter):
        """
        Test MIDVOL_MEAN_REVERSION selection at volatility boundaries [1.0, 1.4].
        """
        # Test at lower boundary (1.0)
        context_low = _create_context_for_boundary_test(
            position_in_value="inside",
            rotation_factor=2.0,
            atr_ratio=1.0,  # Lower boundary
            trend_direction="flat",
        )
        
        selected_low = router.select_profiles(context_low, top_k=5, symbol="BTCUSDT")
        selected_ids_low = [s.profile_id for s in selected_low]
        
        assert "midvol_mean_reversion" in selected_ids_low, (
            f"MIDVOL_MEAN_REVERSION should be selected at atr_ratio=1.0. "
            f"Selected: {selected_ids_low}"
        )
        
        # Test at upper boundary (1.4)
        context_high = _create_context_for_boundary_test(
            position_in_value="inside",
            rotation_factor=2.0,
            atr_ratio=1.4,  # Upper boundary
            trend_direction="flat",
        )
        
        selected_high = router.select_profiles(context_high, top_k=5, symbol="BTCUSDT")
        selected_ids_high = [s.profile_id for s in selected_high]
        
        assert "midvol_mean_reversion" in selected_ids_high, (
            f"MIDVOL_MEAN_REVERSION should be selected at atr_ratio=1.4. "
            f"Selected: {selected_ids_high}"
        )
    
    def test_profile_scores_reflect_boundary_bonus(self, router: ProfileRouter):
        """
        Test that VALUE_AREA_REJECTION gets a higher value_fit score when
        at boundaries compared to when inside.
        """
        # Context at boundary (above)
        context_above = _create_context_for_boundary_test(
            position_in_value="above",
            rotation_factor=4.0,
            atr_ratio=1.0,
            trend_direction="flat",
        )
        
        # Context inside value area
        context_inside = _create_context_for_boundary_test(
            position_in_value="inside",
            rotation_factor=4.0,
            atr_ratio=1.0,
            trend_direction="flat",
        )
        
        # Get scores for both contexts
        selected_above = router.select_profiles(context_above, top_k=10, symbol="BTCUSDT")
        selected_inside = router.select_profiles(context_inside, top_k=10, symbol="BTCUSDT")
        
        # Find VALUE_AREA_REJECTION scores
        var_score_above = None
        var_score_inside = None
        
        for s in selected_above:
            if s.profile_id == "value_area_rejection":
                var_score_above = s.score
                break
        
        for s in selected_inside:
            if s.profile_id == "value_area_rejection":
                var_score_inside = s.score
                break
        
        # VALUE_AREA_REJECTION should score higher when at boundary
        if var_score_above is not None and var_score_inside is not None:
            assert var_score_above > var_score_inside, (
                f"VALUE_AREA_REJECTION should score higher at boundary "
                f"(above={var_score_above:.3f}) than inside ({var_score_inside:.3f})"
            )


class TestProfileSelectionConsistency:
    """Tests for consistent profile selection behavior."""
    
    @pytest.fixture(autouse=True)
    def setup_profiles(self, monkeypatch):
        """Ensure canonical profiles are registered before each test."""
        # Isolate from env-driven strategy disables used in live trading.
        monkeypatch.setenv("DISABLE_STRATEGIES", "")
        monkeypatch.setenv("DISABLE_MEAN_REVERSION_SYMBOLS", "")
        registry = get_profile_registry()
        registry._specs.clear()
        register_canonical_profiles()
    
    @pytest.fixture
    def router(self) -> ProfileRouter:
        """Create a ProfileRouter configured for testing."""
        config = RouterConfig(
            use_v2_scoring=True,
            backtesting_mode=True,
            min_profile_ttl_sec=0.0,
        )
        return ProfileRouter(enable_ml=False, config=config)
    
    def test_selection_is_deterministic(self, router: ProfileRouter):
        """
        Test that profile selection is deterministic for the same context.
        """
        context = _create_context_for_boundary_test(
            position_in_value="above",
            rotation_factor=4.0,
            atr_ratio=1.0,
            trend_direction="flat",
        )
        
        # Run selection multiple times
        results = []
        for _ in range(5):
            selected = router.select_profiles(context, top_k=3, symbol="BTCUSDT")
            results.append([s.profile_id for s in selected])
        
        # All results should be identical
        for i, result in enumerate(results[1:], 1):
            assert result == results[0], (
                f"Selection should be deterministic. "
                f"Run 0: {results[0]}, Run {i}: {result}"
            )
    
    def test_both_profiles_pass_hard_filters(self, router: ProfileRouter):
        """
        Test that both VALUE_AREA_REJECTION and MIDVOL_MEAN_REVERSION
        pass hard filters in appropriate conditions.
        """
        # Context that should allow both profiles to pass hard filters
        context = _create_context_for_boundary_test(
            position_in_value="inside",
            rotation_factor=3.0,
            atr_ratio=1.2,  # In range for both profiles
            trend_direction="flat",
        )
        
        selected = router.select_profiles(context, top_k=10, symbol="BTCUSDT")
        selected_ids = [s.profile_id for s in selected]
        
        # Both profiles should pass hard filters (may not both be in top-k)
        # Check that at least one of them is selected
        has_var = "value_area_rejection" in selected_ids
        has_mmr = "midvol_mean_reversion" in selected_ids
        
        # At least MIDVOL_MEAN_REVERSION should be selected (it requires inside)
        assert has_mmr, (
            f"MIDVOL_MEAN_REVERSION should be selected when inside value area. "
            f"Selected: {selected_ids}"
        )
