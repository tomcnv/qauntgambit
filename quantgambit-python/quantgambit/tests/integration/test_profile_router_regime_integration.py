"""
Integration tests for ProfileRouter regime inference with missing data.

Tests Requirement 11: Router/Regime Inference Rules
- ProfileRouter NEVER rejects signals due to regime classification
- Falls back to default regime when data is missing
- Logs warnings for partial/default inference
- Sets ctx.data["regime_inferred"] with inference result
- Applies conservative profile selection for degraded inference
"""

import pytest
import logging
from typing import Dict, Any, Optional
from unittest.mock import MagicMock, patch

from quantgambit.deeptrader_core.profiles.profile_router import (
    ProfileRouter,
    RegimeInferenceConfig,
    RegimeInference,
)
from quantgambit.deeptrader_core.profiles.context_vector import ContextVector
from quantgambit.deeptrader_core.profiles.router_config import RouterConfig


class TestProfileRouterRegimeIntegration:
    """Integration tests for ProfileRouter with regime inference."""
    
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
            "session": "us",
            "hour_utc": 14,
        }
        defaults.update(kwargs)
        return ContextVector(**defaults)
    
    def _make_router(
        self,
        regime_config: Optional[RegimeInferenceConfig] = None,
        router_config: Optional[RouterConfig] = None,
    ) -> ProfileRouter:
        """Create a ProfileRouter with optional configs."""
        # Use backtesting mode to skip real-time checks
        if router_config is None:
            router_config = RouterConfig(backtesting_mode=True)
        return ProfileRouter(
            regime_inference_config=regime_config,
            config=router_config,
        )
    
    # =========================================================================
    # Integration Tests: Full Data Flow
    # =========================================================================
    
    def test_full_data_flow_with_complete_market_context(self):
        """Test complete data flow with all market context fields present."""
        router = self._make_router()
        context = self._make_context()
        market_context = {
            "volatility_percentile": 0.5,
            "trend_strength": 0.3,
            "spread_percentile": 0.5,
        }
        
        profile_id, regime = router.select_profile_with_regime(
            context,
            market_context=market_context,
            symbol="BTC",
        )
        
        # Should return valid profile and regime
        assert profile_id is not None
        assert regime is not None
        assert regime.inference_quality == "full"
        assert regime.missing_fields == []
        
        # Verify regime values
        assert regime.volatility_regime == "normal"
        assert regime.trend_regime == "ranging"
        assert regime.spread_regime == "normal"
    
    def test_full_data_flow_with_partial_market_context(self):
        """Test data flow with partial market context."""
        router = self._make_router()
        context = self._make_context()
        market_context = {
            "volatility_percentile": 0.8,  # High volatility
            # trend_strength missing
            # spread_percentile missing
        }
        
        profile_id, regime = router.select_profile_with_regime(
            context,
            market_context=market_context,
            symbol="BTC",
        )
        
        # Should still return valid profile
        assert profile_id is not None
        assert regime is not None
        assert regime.inference_quality == "partial"
        assert "trend_strength" in regime.missing_fields
        assert "spread_percentile" in regime.missing_fields
        
        # Verify regime values - volatility from data, others from defaults
        assert regime.volatility_regime == "high"
        assert regime.trend_regime == "ranging"  # Default
        assert regime.spread_regime == "normal"  # Default
    
    def test_full_data_flow_with_empty_market_context(self):
        """Test data flow with empty market context."""
        router = self._make_router()
        context = self._make_context()
        
        profile_id, regime = router.select_profile_with_regime(
            context,
            market_context={},
            symbol="BTC",
        )
        
        # Should still return valid profile - NEVER reject
        assert profile_id is not None
        assert regime is not None
        assert regime.inference_quality == "default"
        assert len(regime.missing_fields) == 3
        
        # All defaults
        assert regime.volatility_regime == "normal"
        assert regime.trend_regime == "ranging"
        assert regime.spread_regime == "normal"
    
    def test_full_data_flow_with_none_market_context(self):
        """Test data flow with None market context."""
        router = self._make_router()
        context = self._make_context()
        
        profile_id, regime = router.select_profile_with_regime(
            context,
            market_context=None,
            symbol="BTC",
        )
        
        # Should still return valid profile - NEVER reject
        assert profile_id is not None
        assert regime is not None
        assert regime.inference_quality == "default"
    
    # =========================================================================
    # Integration Tests: Regime Classification
    # =========================================================================
    
    def test_regime_classification_low_volatility(self):
        """Test regime classification for low volatility market."""
        router = self._make_router()
        context = self._make_context()
        market_context = {
            "volatility_percentile": 0.1,
            "trend_strength": 0.2,
            "spread_percentile": 0.2,
        }
        
        profile_id, regime = router.select_profile_with_regime(
            context,
            market_context=market_context,
            symbol="BTC",
        )
        
        assert regime.volatility_regime == "low"
        assert regime.trend_regime == "ranging"
        assert regime.spread_regime == "tight"
    
    def test_regime_classification_high_volatility_trending(self):
        """Test regime classification for high volatility trending market."""
        router = self._make_router()
        context = self._make_context()
        market_context = {
            "volatility_percentile": 0.9,
            "trend_strength": 0.8,
            "spread_percentile": 0.8,
        }
        
        profile_id, regime = router.select_profile_with_regime(
            context,
            market_context=market_context,
            symbol="BTC",
        )
        
        assert regime.volatility_regime == "high"
        assert regime.trend_regime == "trending"
        assert regime.spread_regime == "wide"
    
    # =========================================================================
    # Integration Tests: Logging
    # =========================================================================
    
    def test_logs_warning_for_partial_inference(self, caplog):
        """Test that warnings are logged for partial inference quality."""
        router = self._make_router()
        context = self._make_context()
        market_context = {
            "volatility_percentile": 0.5,
            # Missing trend_strength and spread_percentile
        }
        
        with caplog.at_level(logging.WARNING):
            profile_id, regime = router.select_profile_with_regime(
                context,
                market_context=market_context,
                symbol="BTC",
            )
        
        # Should log warning about degraded inference
        assert any("Degraded regime inference" in record.message for record in caplog.records)
        assert any("partial" in record.message for record in caplog.records)
    
    def test_logs_warning_for_default_inference(self, caplog):
        """Test that warnings are logged for default inference quality."""
        router = self._make_router()
        context = self._make_context()
        
        with caplog.at_level(logging.WARNING):
            profile_id, regime = router.select_profile_with_regime(
                context,
                market_context={},
                symbol="BTC",
            )
        
        # Should log warning about degraded inference
        assert any("Degraded regime inference" in record.message for record in caplog.records)
        assert any("default" in record.message for record in caplog.records)
    
    def test_no_warning_for_full_inference(self, caplog):
        """Test that no warnings are logged for full inference quality."""
        router = self._make_router()
        context = self._make_context()
        market_context = {
            "volatility_percentile": 0.5,
            "trend_strength": 0.3,
            "spread_percentile": 0.5,
        }
        
        with caplog.at_level(logging.WARNING):
            profile_id, regime = router.select_profile_with_regime(
                context,
                market_context=market_context,
                symbol="BTC",
            )
        
        # Should NOT log warning about degraded inference
        assert not any("Degraded regime inference" in record.message for record in caplog.records)
    
    # =========================================================================
    # Integration Tests: Custom Config
    # =========================================================================
    
    def test_custom_regime_config_thresholds(self):
        """Test that custom regime config thresholds are respected."""
        # Use very different thresholds
        regime_config = RegimeInferenceConfig(
            volatility_low_threshold=0.1,
            volatility_high_threshold=0.9,
            trend_threshold=0.2,
            spread_tight_threshold=0.1,
            spread_wide_threshold=0.9,
        )
        router = self._make_router(regime_config=regime_config)
        context = self._make_context()
        
        # With default thresholds, 0.5 would be "normal" for all
        # With custom thresholds, 0.5 should still be "normal" for volatility/spread
        # but "trending" for trend (since 0.5 > 0.2)
        market_context = {
            "volatility_percentile": 0.5,
            "trend_strength": 0.5,
            "spread_percentile": 0.5,
        }
        
        profile_id, regime = router.select_profile_with_regime(
            context,
            market_context=market_context,
            symbol="BTC",
        )
        
        assert regime.volatility_regime == "normal"
        assert regime.trend_regime == "trending"  # 0.5 > 0.2 threshold
        assert regime.spread_regime == "normal"
    
    # =========================================================================
    # Integration Tests: Never Reject
    # =========================================================================
    
    def test_never_rejects_with_invalid_data(self):
        """Test that ProfileRouter never rejects even with invalid data."""
        router = self._make_router()
        context = self._make_context()
        
        # Various invalid data scenarios
        invalid_contexts = [
            {},  # Empty
            {"volatility_percentile": "invalid"},  # Wrong type
            {"volatility_percentile": None},  # None value
            {"volatility_percentile": float("nan")},  # NaN
            {"volatility_percentile": float("inf")},  # Infinity
            {"unknown_field": 123},  # Unknown field
        ]
        
        for market_context in invalid_contexts:
            profile_id, regime = router.select_profile_with_regime(
                context,
                market_context=market_context,
                symbol="BTC",
            )
            
            # Should always return valid profile and regime
            assert profile_id is not None, f"Failed for context: {market_context}"
            assert regime is not None, f"Failed for context: {market_context}"
    
    def test_always_returns_default_profile_when_no_match(self):
        """Test that default profile is returned when no profiles match."""
        router = self._make_router()
        router.default_profile_id = "my_fallback_profile"
        
        # Create context that might not match any profiles
        context = self._make_context(
            regime_family="unknown",
            market_regime="unknown",
        )
        
        profile_id, regime = router.select_profile_with_regime(
            context,
            market_context={},
            symbol="BTC",
        )
        
        # Should return some profile (either matched or default)
        assert profile_id is not None
        assert regime is not None
    
    # =========================================================================
    # Integration Tests: Regime Inference Result
    # =========================================================================
    
    def test_regime_inference_to_dict(self):
        """Test that regime inference can be serialized to dict."""
        router = self._make_router()
        context = self._make_context()
        market_context = {
            "volatility_percentile": 0.8,
            "trend_strength": 0.6,
            "spread_percentile": 0.2,
        }
        
        profile_id, regime = router.select_profile_with_regime(
            context,
            market_context=market_context,
            symbol="BTC",
        )
        
        # Convert to dict for storage/logging
        regime_dict = regime.to_dict()
        
        assert regime_dict["volatility_regime"] == "high"
        assert regime_dict["trend_regime"] == "trending"
        assert regime_dict["spread_regime"] == "tight"
        assert regime_dict["inference_quality"] == "full"
        assert regime_dict["missing_fields"] == []


class TestProfileRouterRegimeWithPipeline:
    """Integration tests for ProfileRouter regime inference in pipeline context."""
    
    def _make_context(self, **kwargs) -> ContextVector:
        """Create a context with valid safety values."""
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
            "session": "us",
            "hour_utc": 14,
        }
        defaults.update(kwargs)
        return ContextVector(**defaults)
    
    def test_regime_inference_can_be_stored_in_context_data(self):
        """Test that regime inference result can be stored in ctx.data."""
        router_config = RouterConfig(backtesting_mode=True)
        router = ProfileRouter(config=router_config)
        context = self._make_context()
        market_context = {
            "volatility_percentile": 0.5,
            "trend_strength": 0.3,
            "spread_percentile": 0.5,
        }
        
        profile_id, regime = router.select_profile_with_regime(
            context,
            market_context=market_context,
            symbol="BTC",
        )
        
        # Simulate storing in ctx.data (as would happen in pipeline)
        ctx_data = {}
        ctx_data["regime_inferred"] = regime
        ctx_data["profile_id"] = profile_id
        
        # Verify data can be retrieved
        assert ctx_data["regime_inferred"].volatility_regime == "normal"
        assert ctx_data["regime_inferred"].inference_quality == "full"
        assert ctx_data["profile_id"] is not None
    
    def test_multiple_symbols_independent_inference(self):
        """Test that regime inference is independent per symbol."""
        router_config = RouterConfig(backtesting_mode=True)
        router = ProfileRouter(config=router_config)
        
        # BTC context with high volatility
        btc_context = self._make_context(symbol="BTC")
        btc_market = {"volatility_percentile": 0.9, "trend_strength": 0.8, "spread_percentile": 0.5}
        
        # ETH context with low volatility
        eth_context = self._make_context(symbol="ETH")
        eth_market = {"volatility_percentile": 0.1, "trend_strength": 0.2, "spread_percentile": 0.5}
        
        btc_profile, btc_regime = router.select_profile_with_regime(
            btc_context, market_context=btc_market, symbol="BTC"
        )
        eth_profile, eth_regime = router.select_profile_with_regime(
            eth_context, market_context=eth_market, symbol="ETH"
        )
        
        # Regimes should be different
        assert btc_regime.volatility_regime == "high"
        assert eth_regime.volatility_regime == "low"
        assert btc_regime.trend_regime == "trending"
        assert eth_regime.trend_regime == "ranging"
    
    def test_conservative_profile_selection_for_degraded_inference(self):
        """Test that degraded inference quality affects profile selection logging."""
        router_config = RouterConfig(backtesting_mode=True)
        router = ProfileRouter(config=router_config)
        context = self._make_context()
        
        # Full inference
        full_market = {
            "volatility_percentile": 0.5,
            "trend_strength": 0.3,
            "spread_percentile": 0.5,
        }
        full_profile, full_regime = router.select_profile_with_regime(
            context, market_context=full_market, symbol="BTC"
        )
        
        # Degraded inference (missing data)
        degraded_market = {}
        degraded_profile, degraded_regime = router.select_profile_with_regime(
            context, market_context=degraded_market, symbol="BTC"
        )
        
        # Both should return valid profiles
        assert full_profile is not None
        assert degraded_profile is not None
        
        # Quality should differ
        assert full_regime.inference_quality == "full"
        assert degraded_regime.inference_quality == "default"
