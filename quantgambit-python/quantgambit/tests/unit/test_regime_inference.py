"""
Unit tests for regime inference functionality.

Tests Requirement 11: Router/Regime Inference Rules
- Explicit and non-lethal regime inference rules
- Falls back to default regime when data is missing
- Logs warnings for partial/default inference
"""

import pytest
from typing import Dict, Any

from quantgambit.deeptrader_core.profiles.profile_router import (
    ProfileRouter,
    RegimeInferenceConfig,
    RegimeInference,
)
from quantgambit.deeptrader_core.profiles.context_vector import ContextVector


class TestRegimeInferenceConfig:
    """Tests for RegimeInferenceConfig dataclass."""
    
    def test_default_values(self):
        """Test that default values are set correctly."""
        config = RegimeInferenceConfig()
        
        assert config.volatility_low_threshold == 0.3
        assert config.volatility_high_threshold == 0.7
        assert config.trend_threshold == 0.5
        assert config.spread_tight_threshold == 0.3
        assert config.spread_wide_threshold == 0.7
    
    def test_custom_values(self):
        """Test that custom values can be set."""
        config = RegimeInferenceConfig(
            volatility_low_threshold=0.2,
            volatility_high_threshold=0.8,
            trend_threshold=0.6,
            spread_tight_threshold=0.25,
            spread_wide_threshold=0.75,
        )
        
        assert config.volatility_low_threshold == 0.2
        assert config.volatility_high_threshold == 0.8
        assert config.trend_threshold == 0.6
        assert config.spread_tight_threshold == 0.25
        assert config.spread_wide_threshold == 0.75


class TestRegimeInference:
    """Tests for RegimeInference dataclass."""
    
    def test_to_dict(self):
        """Test that to_dict returns correct dictionary."""
        inference = RegimeInference(
            volatility_regime="high",
            trend_regime="trending",
            spread_regime="wide",
            inference_quality="full",
            missing_fields=[],
        )
        
        result = inference.to_dict()
        
        assert result["volatility_regime"] == "high"
        assert result["trend_regime"] == "trending"
        assert result["spread_regime"] == "wide"
        assert result["inference_quality"] == "full"
        assert result["missing_fields"] == []
    
    def test_to_dict_with_missing_fields(self):
        """Test to_dict with missing fields."""
        inference = RegimeInference(
            volatility_regime="normal",
            trend_regime="ranging",
            spread_regime="normal",
            inference_quality="partial",
            missing_fields=["volatility_percentile"],
        )
        
        result = inference.to_dict()
        
        assert result["inference_quality"] == "partial"
        assert result["missing_fields"] == ["volatility_percentile"]


class TestProfileRouterRegimeInference:
    """Tests for ProfileRouter.infer_regime method."""
    
    def _make_router(self, config: RegimeInferenceConfig = None) -> ProfileRouter:
        """Create a ProfileRouter with optional custom config."""
        return ProfileRouter(
            regime_inference_config=config or RegimeInferenceConfig()
        )
    
    # =========================================================================
    # Volatility Regime Tests
    # =========================================================================
    
    def test_volatility_regime_low(self):
        """Test that low volatility percentile results in 'low' regime."""
        router = self._make_router()
        market_context = {"volatility_percentile": 0.2}
        
        result = router.infer_regime(market_context)
        
        assert result.volatility_regime == "low"
        assert "volatility_percentile" not in result.missing_fields
    
    def test_volatility_regime_normal(self):
        """Test that mid-range volatility percentile results in 'normal' regime."""
        router = self._make_router()
        market_context = {"volatility_percentile": 0.5}
        
        result = router.infer_regime(market_context)
        
        assert result.volatility_regime == "normal"
    
    def test_volatility_regime_high(self):
        """Test that high volatility percentile results in 'high' regime."""
        router = self._make_router()
        market_context = {"volatility_percentile": 0.8}
        
        result = router.infer_regime(market_context)
        
        assert result.volatility_regime == "high"
    
    def test_volatility_regime_at_low_threshold(self):
        """Test volatility at exactly the low threshold."""
        router = self._make_router()
        market_context = {"volatility_percentile": 0.3}  # At threshold
        
        result = router.infer_regime(market_context)
        
        # At threshold should be "normal" (not strictly less than)
        assert result.volatility_regime == "normal"
    
    def test_volatility_regime_at_high_threshold(self):
        """Test volatility at exactly the high threshold."""
        router = self._make_router()
        market_context = {"volatility_percentile": 0.7}  # At threshold
        
        result = router.infer_regime(market_context)
        
        # At threshold should be "normal" (not strictly greater than)
        assert result.volatility_regime == "normal"
    
    def test_volatility_regime_missing_defaults_to_normal(self):
        """Test that missing volatility_percentile defaults to 'normal'."""
        router = self._make_router()
        market_context = {}  # No volatility data
        
        result = router.infer_regime(market_context)
        
        assert result.volatility_regime == "normal"
        assert "volatility_percentile" in result.missing_fields
    
    # =========================================================================
    # Trend Regime Tests
    # =========================================================================
    
    def test_trend_regime_trending_positive(self):
        """Test that high positive trend strength results in 'trending'."""
        router = self._make_router()
        market_context = {"trend_strength": 0.7}
        
        result = router.infer_regime(market_context)
        
        assert result.trend_regime == "trending"
    
    def test_trend_regime_trending_negative(self):
        """Test that high negative trend strength results in 'trending'."""
        router = self._make_router()
        market_context = {"trend_strength": -0.7}
        
        result = router.infer_regime(market_context)
        
        assert result.trend_regime == "trending"
    
    def test_trend_regime_ranging(self):
        """Test that low trend strength results in 'ranging'."""
        router = self._make_router()
        market_context = {"trend_strength": 0.3}
        
        result = router.infer_regime(market_context)
        
        assert result.trend_regime == "ranging"
    
    def test_trend_regime_at_threshold(self):
        """Test trend at exactly the threshold."""
        router = self._make_router()
        market_context = {"trend_strength": 0.5}  # At threshold
        
        result = router.infer_regime(market_context)
        
        # At threshold should be "ranging" (not strictly greater than)
        assert result.trend_regime == "ranging"
    
    def test_trend_regime_missing_defaults_to_ranging(self):
        """Test that missing trend_strength defaults to 'ranging' (conservative)."""
        router = self._make_router()
        market_context = {}  # No trend data
        
        result = router.infer_regime(market_context)
        
        assert result.trend_regime == "ranging"
        assert "trend_strength" in result.missing_fields
    
    # =========================================================================
    # Spread Regime Tests
    # =========================================================================
    
    def test_spread_regime_tight(self):
        """Test that low spread percentile results in 'tight' regime."""
        router = self._make_router()
        market_context = {"spread_percentile": 0.2}
        
        result = router.infer_regime(market_context)
        
        assert result.spread_regime == "tight"
    
    def test_spread_regime_normal(self):
        """Test that mid-range spread percentile results in 'normal' regime."""
        router = self._make_router()
        market_context = {"spread_percentile": 0.5}
        
        result = router.infer_regime(market_context)
        
        assert result.spread_regime == "normal"
    
    def test_spread_regime_wide(self):
        """Test that high spread percentile results in 'wide' regime."""
        router = self._make_router()
        market_context = {"spread_percentile": 0.8}
        
        result = router.infer_regime(market_context)
        
        assert result.spread_regime == "wide"
    
    def test_spread_regime_missing_defaults_to_normal(self):
        """Test that missing spread_percentile defaults to 'normal'."""
        router = self._make_router()
        market_context = {}  # No spread data
        
        result = router.infer_regime(market_context)
        
        assert result.spread_regime == "normal"
        assert "spread_percentile" in result.missing_fields
    
    # =========================================================================
    # Inference Quality Tests
    # =========================================================================
    
    def test_inference_quality_full(self):
        """Test that full data results in 'full' quality."""
        router = self._make_router()
        market_context = {
            "volatility_percentile": 0.5,
            "trend_strength": 0.3,
            "spread_percentile": 0.5,
        }
        
        result = router.infer_regime(market_context)
        
        assert result.inference_quality == "full"
        assert result.missing_fields == []
    
    def test_inference_quality_partial_one_missing(self):
        """Test that one missing field results in 'partial' quality."""
        router = self._make_router()
        market_context = {
            "volatility_percentile": 0.5,
            "trend_strength": 0.3,
            # spread_percentile missing
        }
        
        result = router.infer_regime(market_context)
        
        assert result.inference_quality == "partial"
        assert "spread_percentile" in result.missing_fields
        assert len(result.missing_fields) == 1
    
    def test_inference_quality_partial_two_missing(self):
        """Test that two missing fields results in 'partial' quality."""
        router = self._make_router()
        market_context = {
            "volatility_percentile": 0.5,
            # trend_strength missing
            # spread_percentile missing
        }
        
        result = router.infer_regime(market_context)
        
        assert result.inference_quality == "partial"
        assert len(result.missing_fields) == 2
    
    def test_inference_quality_default_all_missing(self):
        """Test that all missing fields results in 'default' quality."""
        router = self._make_router()
        market_context = {}  # All fields missing
        
        result = router.infer_regime(market_context)
        
        assert result.inference_quality == "default"
        assert len(result.missing_fields) == 3
        assert "volatility_percentile" in result.missing_fields
        assert "trend_strength" in result.missing_fields
        assert "spread_percentile" in result.missing_fields
    
    # =========================================================================
    # Custom Config Tests
    # =========================================================================
    
    def test_custom_volatility_thresholds(self):
        """Test that custom volatility thresholds are respected."""
        config = RegimeInferenceConfig(
            volatility_low_threshold=0.2,
            volatility_high_threshold=0.8,
        )
        router = self._make_router(config)
        
        # 0.25 should be "normal" with default thresholds but "low" with custom
        market_context = {"volatility_percentile": 0.15}
        result = router.infer_regime(market_context)
        assert result.volatility_regime == "low"
        
        # 0.75 should be "high" with default thresholds but "normal" with custom
        market_context = {"volatility_percentile": 0.75}
        result = router.infer_regime(market_context)
        assert result.volatility_regime == "normal"
    
    def test_custom_trend_threshold(self):
        """Test that custom trend threshold is respected."""
        config = RegimeInferenceConfig(trend_threshold=0.3)
        router = self._make_router(config)
        
        # 0.4 should be "ranging" with default threshold but "trending" with custom
        market_context = {"trend_strength": 0.4}
        result = router.infer_regime(market_context)
        assert result.trend_regime == "trending"
    
    def test_custom_spread_thresholds(self):
        """Test that custom spread thresholds are respected."""
        config = RegimeInferenceConfig(
            spread_tight_threshold=0.2,
            spread_wide_threshold=0.8,
        )
        router = self._make_router(config)
        
        # 0.25 should be "tight" with default thresholds but "normal" with custom
        market_context = {"spread_percentile": 0.25}
        result = router.infer_regime(market_context)
        assert result.spread_regime == "normal"
    
    # =========================================================================
    # Edge Cases
    # =========================================================================
    
    def test_none_values_treated_as_missing(self):
        """Test that None values are treated as missing."""
        router = self._make_router()
        market_context = {
            "volatility_percentile": None,
            "trend_strength": 0.3,
            "spread_percentile": 0.5,
        }
        
        result = router.infer_regime(market_context)
        
        assert result.volatility_regime == "normal"  # Default
        assert "volatility_percentile" in result.missing_fields
        assert result.inference_quality == "partial"
    
    def test_zero_values_are_valid(self):
        """Test that zero values are treated as valid data."""
        router = self._make_router()
        market_context = {
            "volatility_percentile": 0.0,
            "trend_strength": 0.0,
            "spread_percentile": 0.0,
        }
        
        result = router.infer_regime(market_context)
        
        assert result.volatility_regime == "low"  # 0.0 < 0.3
        assert result.trend_regime == "ranging"   # 0.0 < 0.5
        assert result.spread_regime == "tight"    # 0.0 < 0.3
        assert result.inference_quality == "full"
        assert result.missing_fields == []
    
    def test_boundary_values(self):
        """Test boundary values at thresholds."""
        router = self._make_router()
        
        # Just below low threshold
        market_context = {"volatility_percentile": 0.29}
        result = router.infer_regime(market_context)
        assert result.volatility_regime == "low"
        
        # Just above high threshold
        market_context = {"volatility_percentile": 0.71}
        result = router.infer_regime(market_context)
        assert result.volatility_regime == "high"


class TestProfileRouterNeverRejects:
    """
    Tests that ProfileRouter NEVER rejects signals due to regime classification.
    
    Implements Requirement 11: Non-lethal regime inference rules.
    """
    
    def _make_context(self, **kwargs) -> ContextVector:
        """Create a context with valid safety values for v2 hard filters."""
        defaults = {
            "symbol": "BTC",
            "timestamp": 1.0,
            "price": 100.0,
            "data_completeness": 1.0,
            "bid_depth_usd": 50000.0,
            "ask_depth_usd": 50000.0,
            "spread_bps": 5.0,
            "trades_per_second": 10.0,
            "book_age_ms": 100.0,
            "trade_age_ms": 100.0,
            "risk_mode": "normal",
        }
        defaults.update(kwargs)
        return ContextVector(**defaults)
    
    def test_infer_regime_never_raises(self):
        """Test that infer_regime never raises exceptions."""
        router = ProfileRouter()
        
        # Empty context
        result = router.infer_regime({})
        assert result is not None
        
        # Invalid types should not crash
        result = router.infer_regime({"volatility_percentile": "invalid"})
        # Should handle gracefully (may use default)
        assert result is not None
    
    def test_select_profile_with_regime_always_returns_profile(self):
        """Test that select_profile_with_regime always returns a valid profile."""
        router = ProfileRouter(default_profile_id="fallback_profile")
        context = self._make_context()
        
        # With full data
        profile_id, regime = router.select_profile_with_regime(
            context,
            market_context={
                "volatility_percentile": 0.5,
                "trend_strength": 0.3,
                "spread_percentile": 0.5,
            },
            symbol="BTC",
        )
        assert profile_id is not None
        assert regime is not None
        
        # With no data - should still return a profile
        profile_id, regime = router.select_profile_with_regime(
            context,
            market_context={},
            symbol="BTC",
        )
        assert profile_id is not None
        assert regime is not None
        assert regime.inference_quality == "default"
    
    def test_missing_data_uses_defaults_not_rejection(self):
        """Test that missing data uses defaults instead of rejection."""
        router = ProfileRouter()
        
        # All data missing
        result = router.infer_regime({})
        
        # Should use conservative defaults
        assert result.volatility_regime == "normal"
        assert result.trend_regime == "ranging"
        assert result.spread_regime == "normal"
        
        # Should NOT raise or return None
        assert result is not None
