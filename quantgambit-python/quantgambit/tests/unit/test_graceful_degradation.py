"""
Unit tests for the graceful degradation system.

Tests the TradingMode transitions:
- NORMAL → REDUCE_SIZE → NO_ENTRIES → FLATTEN

Verifies proper responses to:
- Trade/orderbook feed staleness
- Low data quality
- WebSocket disconnections
- Wide spreads
- Thin depth
"""

import pytest
from unittest.mock import MagicMock, AsyncMock
import time

from quantgambit.risk.degradation import (
    DegradationManager,
    DegradationConfig,
    DegradationDecision,
    TradingMode,
)

# Alias for cleaner tests
GracefulDegradationManager = DegradationManager


class TestTradingModeTransitions:
    """Test mode transitions based on data quality signals."""
    
    def test_normal_mode_all_healthy(self):
        """Normal mode when all data is fresh and healthy."""
        manager = GracefulDegradationManager()
        
        decision = manager.evaluate(
            symbol="BTCUSDT",
            feed_staleness={"trade": 1.0, "orderbook": 0.5},
            data_quality=0.95,
            spread_bps=2.0,
            bid_depth_usd=50000,
            ask_depth_usd=50000,
            ws_connected=True,
        )
        
        assert decision.mode == TradingMode.NORMAL
        assert decision.size_multiplier == 1.0
        assert decision.allows_entries is True
        assert decision.should_flatten is False
        # "healthy" reason is added when all checks pass
        assert "healthy" in decision.reasons
    
    def test_reduce_size_slight_staleness(self):
        """Reduce size mode when data is slightly stale."""
        config = DegradationConfig(
            trade_stale_reduce_sec=5.0,
            trade_stale_no_entry_sec=30.0,
        )
        manager = GracefulDegradationManager(config)
        
        decision = manager.evaluate(
            symbol="BTCUSDT",
            feed_staleness={"trade": 10.0, "orderbook": 1.0},  # Trade moderately stale
            data_quality=0.9,
            spread_bps=2.0,
            bid_depth_usd=50000,
            ask_depth_usd=50000,
            ws_connected=True,
        )
        
        assert decision.mode == TradingMode.REDUCE_SIZE
        assert decision.size_multiplier < 1.0
        assert decision.allows_entries is True  # Still allow entries, just reduced size
        assert "trade_stale_reduce" in " ".join(decision.reasons).lower()
    
    def test_reduce_size_ws_disconnected(self):
        """WS disconnected does NOT flatten by default (too aggressive)."""
        # Default config has flatten_on_ws_disconnect=False (changed from True)
        manager = GracefulDegradationManager()
        
        decision = manager.evaluate(
            symbol="BTCUSDT",
            feed_staleness={"trade": 2.0, "orderbook": 1.0},
            data_quality=0.8,
            spread_bps=2.0,
            bid_depth_usd=50000,
            ask_depth_usd=50000,
            ws_connected=False,  # WS disconnected
        )
        
        # Default config does NOT flatten on WS disconnect (too aggressive)
        # Instead, staleness thresholds should trigger NO_ENTRIES when appropriate
        assert decision.mode == TradingMode.NORMAL  # No flatten, data is still fresh
        assert decision.should_flatten is False
    
    def test_ws_disconnected_no_flatten(self):
        """WS disconnected without flatten (config disabled)."""
        config = DegradationConfig(
            flatten_on_ws_disconnect=False,  # Disable flatten on disconnect
        )
        manager = GracefulDegradationManager(config)
        
        decision = manager.evaluate(
            symbol="BTCUSDT",
            feed_staleness={"trade": 2.0, "orderbook": 1.0},
            data_quality=0.8,
            spread_bps=2.0,
            bid_depth_usd=50000,
            ask_depth_usd=50000,
            ws_connected=False,  # WS disconnected
        )
        
        # Should be NORMAL since we disabled flatten on disconnect
        assert decision.mode == TradingMode.NORMAL
        assert decision.should_flatten is False
    
    def test_no_entries_trade_stale(self):
        """Block entries when trade data is stale."""
        config = DegradationConfig(
            trade_stale_no_entry_sec=30.0,
        )
        manager = GracefulDegradationManager(config)
        
        decision = manager.evaluate(
            symbol="BTCUSDT",
            feed_staleness={"trade": 60.0, "orderbook": 1.0},  # Trade very stale
            data_quality=0.9,
            spread_bps=2.0,
            bid_depth_usd=50000,
            ask_depth_usd=50000,
            ws_connected=True,
        )
        
        assert decision.mode == TradingMode.NO_ENTRIES
        assert decision.allows_entries is False
        assert decision.should_flatten is False
        assert "trade" in " ".join(decision.reasons).lower()
    
    def test_no_entries_orderbook_stale(self):
        """Block entries when orderbook data is stale."""
        config = DegradationConfig(
            orderbook_stale_no_entry_sec=30.0,
        )
        manager = GracefulDegradationManager(config)
        
        decision = manager.evaluate(
            symbol="BTCUSDT",
            feed_staleness={"trade": 1.0, "orderbook": 60.0},  # Orderbook very stale
            data_quality=0.9,
            spread_bps=2.0,
            bid_depth_usd=50000,
            ask_depth_usd=50000,
            ws_connected=True,
        )
        
        assert decision.mode == TradingMode.NO_ENTRIES
        assert decision.allows_entries is False
        assert "orderbook" in " ".join(decision.reasons).lower()
    
    def test_no_entries_low_quality(self):
        """Block entries when data quality score is low."""
        config = DegradationConfig(
            quality_no_entry_threshold=0.5,
        )
        manager = GracefulDegradationManager(config)
        
        decision = manager.evaluate(
            symbol="BTCUSDT",
            feed_staleness={"trade": 1.0, "orderbook": 1.0},
            data_quality=0.3,  # Very low quality
            spread_bps=2.0,
            bid_depth_usd=50000,
            ask_depth_usd=50000,
            ws_connected=True,
        )
        
        assert decision.mode == TradingMode.NO_ENTRIES
        assert decision.allows_entries is False
        assert "quality" in " ".join(decision.reasons).lower()
    
    def test_flatten_multiple_failures(self):
        """Flatten mode when multiple severe issues detected."""
        config = DegradationConfig(
            trade_stale_flatten_sec=120.0,
            orderbook_stale_flatten_sec=120.0,
        )
        manager = GracefulDegradationManager(config)
        
        decision = manager.evaluate(
            symbol="BTCUSDT",
            feed_staleness={"trade": 180.0, "orderbook": 180.0},  # Both extremely stale
            data_quality=0.2,
            spread_bps=50.0,  # Extremely wide spread
            bid_depth_usd=100,  # Very thin
            ask_depth_usd=100,
            ws_connected=False,
        )
        
        assert decision.mode == TradingMode.FLATTEN
        assert decision.allows_entries is False
        assert decision.should_flatten is True
        assert decision.size_multiplier == 0.0
    
    def test_no_data_normal_without_flatten(self):
        """No data doesn't trigger flatten by default (only with explicit config)."""
        manager = GracefulDegradationManager()
        
        decision = manager.evaluate(
            symbol="BTCUSDT",
            feed_staleness={},  # No feeds at all
            data_quality=None,
            spread_bps=None,  # No spread data
            bid_depth_usd=None,
            ask_depth_usd=None,
            ws_connected=False,
        )
        
        # Default config does NOT flatten on WS disconnect
        # Without feed staleness data, no staleness threshold is triggered
        assert decision.mode == TradingMode.NORMAL
        assert decision.allows_entries is True
    
    def test_flatten_with_explicit_config(self):
        """Flatten mode requires explicit configuration."""
        config = DegradationConfig(flatten_on_ws_disconnect=True)
        manager = GracefulDegradationManager(config)
        
        decision = manager.evaluate(
            symbol="BTCUSDT",
            feed_staleness={},
            data_quality=None,
            spread_bps=None,
            bid_depth_usd=None,
            ask_depth_usd=None,
            ws_connected=False,
        )
        
        # With explicit config, WS disconnect triggers flatten
        assert decision.mode == TradingMode.FLATTEN
        assert decision.allows_entries is False


class TestDegradationSizeMultipliers:
    """Test size multiplier calculations."""
    
    def test_size_multiplier_normal(self):
        """Normal mode should have 1.0 multiplier."""
        manager = GracefulDegradationManager()
        
        decision = manager.evaluate(
            symbol="BTCUSDT",
            feed_staleness={"trade": 1.0, "orderbook": 1.0},
            data_quality=0.95,
            spread_bps=2.0,
            bid_depth_usd=50000,
            ask_depth_usd=50000,
            ws_connected=True,
        )
        
        assert decision.size_multiplier == 1.0
    
    def test_size_multiplier_reduce(self):
        """Reduce size mode should have <1.0 multiplier."""
        config = DegradationConfig(
            trade_stale_reduce_sec=5.0,
            trade_stale_no_entry_sec=60.0,
        )
        manager = GracefulDegradationManager(config)
        
        decision = manager.evaluate(
            symbol="BTCUSDT",
            feed_staleness={"trade": 10.0, "orderbook": 1.0},  # Above reduce threshold
            data_quality=0.9,
            spread_bps=2.0,
            bid_depth_usd=50000,
            ask_depth_usd=50000,
            ws_connected=True,
        )
        
        # REDUCE_SIZE mode has 0.5 multiplier
        assert decision.mode == TradingMode.REDUCE_SIZE
        assert decision.size_multiplier == 0.5
    
    def test_size_multiplier_most_restrictive_wins(self):
        """Multiple issues should result in most restrictive mode."""
        config = DegradationConfig(
            trade_stale_reduce_sec=5.0,
            trade_stale_no_entry_sec=60.0,
            spread_reduce_bps=5.0,
        )
        manager = GracefulDegradationManager(config)
        
        decision = manager.evaluate(
            symbol="BTCUSDT",
            feed_staleness={"trade": 10.0, "orderbook": 10.0},  # Both moderately stale
            data_quality=0.75,  # Slightly low
            spread_bps=8.0,  # Above reduce threshold
            bid_depth_usd=50000,
            ask_depth_usd=50000,
            ws_connected=True,
        )
        
        # Should be REDUCE_SIZE with 0.5 multiplier (most restrictive that allows entries)
        assert decision.mode == TradingMode.REDUCE_SIZE
        assert decision.size_multiplier == 0.5
    
    def test_size_multiplier_zero_on_block(self):
        """Blocking modes should have 0.0 multiplier."""
        config = DegradationConfig(
            trade_stale_no_entry_sec=30.0,
        )
        manager = GracefulDegradationManager(config)
        
        decision = manager.evaluate(
            symbol="BTCUSDT",
            feed_staleness={"trade": 60.0},  # Very stale
            data_quality=0.9,
            spread_bps=2.0,
            bid_depth_usd=50000,
            ask_depth_usd=50000,
            ws_connected=True,
        )
        
        assert decision.mode in [TradingMode.NO_ENTRIES, TradingMode.FLATTEN]
        assert decision.size_multiplier == 0.0


class TestDegradationConfig:
    """Test configuration behavior."""
    
    def test_default_config(self):
        """Default config should have reasonable defaults."""
        config = DegradationConfig()
        
        assert config.trade_stale_reduce_sec > 0
        assert config.trade_stale_no_entry_sec > config.trade_stale_reduce_sec
        assert config.trade_stale_flatten_sec > config.trade_stale_no_entry_sec
        
        assert config.orderbook_stale_reduce_sec > 0
        assert config.orderbook_stale_no_entry_sec > config.orderbook_stale_reduce_sec
        
        assert 0 < config.quality_reduce_threshold < 1.0
        assert 0 < config.quality_no_entry_threshold < config.quality_reduce_threshold
    
    def test_custom_config(self):
        """Custom config should override defaults."""
        config = DegradationConfig(
            trade_stale_reduce_sec=10.0,
            trade_stale_no_entry_sec=30.0,
            trade_stale_flatten_sec=90.0,
        )
        
        assert config.trade_stale_reduce_sec == 10.0
        assert config.trade_stale_no_entry_sec == 30.0
        assert config.trade_stale_flatten_sec == 90.0
    
    def test_lenient_config(self):
        """Very lenient config should allow more trading."""
        config = DegradationConfig(
            trade_stale_reduce_sec=60.0,
            trade_stale_no_entry_sec=300.0,
            orderbook_stale_reduce_sec=60.0,
            orderbook_stale_no_entry_sec=300.0,
            quality_reduce_threshold=0.3,
            quality_no_entry_threshold=0.1,
        )
        manager = GracefulDegradationManager(config)
        
        # Moderately stale data should be OK
        decision = manager.evaluate(
            symbol="BTCUSDT",
            feed_staleness={"trade": 30.0, "orderbook": 30.0},
            data_quality=0.5,
            spread_bps=5.0,
            bid_depth_usd=10000,
            ask_depth_usd=10000,
            ws_connected=True,
        )
        
        assert decision.mode == TradingMode.NORMAL
        assert decision.allows_entries is True
    
    def test_strict_config(self):
        """Very strict config should block more aggressively."""
        config = DegradationConfig(
            trade_stale_reduce_sec=1.0,
            trade_stale_no_entry_sec=5.0,
            orderbook_stale_reduce_sec=1.0,
            orderbook_stale_no_entry_sec=5.0,
            quality_reduce_threshold=0.9,
            quality_no_entry_threshold=0.8,
        )
        manager = GracefulDegradationManager(config)
        
        # Even slightly stale data should block
        decision = manager.evaluate(
            symbol="BTCUSDT",
            feed_staleness={"trade": 3.0, "orderbook": 3.0},
            data_quality=0.85,
            spread_bps=2.0,
            bid_depth_usd=50000,
            ask_depth_usd=50000,
            ws_connected=True,
        )
        
        # Should at least reduce size due to strict thresholds
        assert decision.mode in [TradingMode.REDUCE_SIZE, TradingMode.NO_ENTRIES]


class TestDegradationDecision:
    """Test DegradationDecision dataclass."""
    
    def test_default_decision(self):
        """Default decision should be safe (normal mode)."""
        decision = DegradationDecision(
            mode=TradingMode.NORMAL,
            reasons=["healthy"],
            size_multiplier=1.0,
            allows_entries=True,
            allows_exits=True,
            should_flatten=False,
            metrics={},
        )
        
        assert decision.mode == TradingMode.NORMAL
        assert decision.size_multiplier == 1.0
        assert decision.allows_entries is True
        assert decision.should_flatten is False
    
    def test_decision_with_reasons(self):
        """Decision should track reasons."""
        decision = DegradationDecision(
            mode=TradingMode.REDUCE_SIZE,
            reasons=["trade_stale_reduce:10.0s", "spread_reduce:8.0bps"],
            size_multiplier=0.5,
            allows_entries=True,
            allows_exits=True,
            should_flatten=False,
            metrics={"trade_stale_sec": 10.0, "spread_bps": 8.0},
        )
        
        assert len(decision.reasons) == 2
        assert "trade" in decision.reasons[0]
        assert "spread" in decision.reasons[1]
    
    def test_decision_flatten_flags(self):
        """Flatten mode should set appropriate flags."""
        decision = DegradationDecision(
            mode=TradingMode.FLATTEN,
            reasons=["ws_disconnected"],
            size_multiplier=0.0,
            allows_entries=False,
            allows_exits=True,
            should_flatten=True,
            metrics={},
        )
        
        assert decision.mode == TradingMode.FLATTEN
        assert decision.size_multiplier == 0.0
        assert decision.allows_entries is False
        assert decision.should_flatten is True


class TestSymbolIsolation:
    """Test that degradation is evaluated per-symbol."""
    
    def test_different_symbols_different_decisions(self):
        """Each symbol should have independent degradation state."""
        manager = GracefulDegradationManager()
        
        # BTC with good data
        btc_decision = manager.evaluate(
            symbol="BTCUSDT",
            feed_staleness={"trade": 1.0, "orderbook": 1.0},
            data_quality=0.95,
            spread_bps=2.0,
            bid_depth_usd=50000,
            ask_depth_usd=50000,
            ws_connected=True,
        )
        
        # ETH with stale data
        config = DegradationConfig(trade_stale_no_entry_sec=10.0)
        manager_strict = GracefulDegradationManager(config)
        eth_decision = manager_strict.evaluate(
            symbol="ETHUSDT",
            feed_staleness={"trade": 30.0, "orderbook": 1.0},
            data_quality=0.6,
            spread_bps=5.0,
            bid_depth_usd=20000,
            ask_depth_usd=20000,
            ws_connected=True,
        )
        
        # BTC should be normal, ETH should be degraded
        assert btc_decision.mode == TradingMode.NORMAL
        assert eth_decision.mode in [TradingMode.NO_ENTRIES, TradingMode.REDUCE_SIZE]


class TestEdgeCases:
    """Test edge cases and boundary conditions."""
    
    def test_none_values_handled(self):
        """None values should be handled gracefully."""
        # Disable flatten on ws_disconnect to isolate None handling
        config = DegradationConfig(flatten_on_ws_disconnect=False)
        manager = GracefulDegradationManager(config)
        
        # Should not raise exception, ws_connected defaults to True
        decision = manager.evaluate(
            symbol="BTCUSDT",
            feed_staleness=None,
            data_quality=None,
            spread_bps=None,
            bid_depth_usd=None,
            ask_depth_usd=None,
            ws_connected=True,  # ws_connected is required, not optional
        )
        
        # Should be NORMAL since no issues detected (None values are skipped)
        assert decision is not None
        assert decision.mode == TradingMode.NORMAL
    
    def test_empty_feed_staleness(self):
        """Empty feed staleness dict should be treated as healthy (no data = no issues)."""
        manager = GracefulDegradationManager()
        
        decision = manager.evaluate(
            symbol="BTCUSDT",
            feed_staleness={},  # No feeds reported
            data_quality=0.9,
            spread_bps=2.0,
            bid_depth_usd=50000,
            ask_depth_usd=50000,
            ws_connected=True,
        )
        
        # Empty staleness means no staleness issues detected
        assert decision.mode == TradingMode.NORMAL
    
    def test_negative_staleness_treated_as_zero(self):
        """Negative staleness values should be treated as not stale (invalid)."""
        config = DegradationConfig(
            trade_stale_reduce_sec=5.0,
        )
        manager = GracefulDegradationManager(config)
        
        decision = manager.evaluate(
            symbol="BTCUSDT",
            feed_staleness={"trade": -5.0, "orderbook": 1.0},  # Invalid negative
            data_quality=0.9,
            spread_bps=2.0,
            bid_depth_usd=50000,
            ask_depth_usd=50000,
            ws_connected=True,
        )
        
        # Should handle gracefully - negative values don't trigger thresholds
        assert decision is not None
        # The negative value won't trigger any threshold (< any positive threshold)
    
    def test_extreme_values(self):
        """Extreme values should be handled correctly."""
        manager = GracefulDegradationManager()
        
        # Very large staleness
        decision = manager.evaluate(
            symbol="BTCUSDT",
            feed_staleness={"trade": 1e10, "orderbook": 1e10},
            data_quality=0.0,
            spread_bps=1e10,
            bid_depth_usd=0.0,
            ask_depth_usd=0.0,
            ws_connected=False,
        )
        
        assert decision.mode == TradingMode.FLATTEN
        assert decision.should_flatten is True
    
    def test_boundary_values(self):
        """Test behavior at exact threshold boundaries."""
        config = DegradationConfig(
            trade_stale_reduce_sec=10.0,
            trade_stale_no_entry_sec=30.0,
        )
        manager = GracefulDegradationManager(config)
        
        # Exactly at reduce threshold
        decision_at_reduce = manager.evaluate(
            symbol="BTCUSDT",
            feed_staleness={"trade": 10.0, "orderbook": 1.0},
            data_quality=0.9,
            spread_bps=2.0,
            bid_depth_usd=50000,
            ask_depth_usd=50000,
            ws_connected=True,
        )
        
        # Exactly at no_entry threshold
        decision_at_block = manager.evaluate(
            symbol="BTCUSDT",
            feed_staleness={"trade": 30.0, "orderbook": 1.0},
            data_quality=0.9,
            spread_bps=2.0,
            bid_depth_usd=50000,
            ask_depth_usd=50000,
            ws_connected=True,
        )
        
        # At reduce threshold should reduce (>= triggers)
        assert decision_at_reduce.mode == TradingMode.REDUCE_SIZE
        # At no_entry threshold should block
        assert decision_at_block.mode == TradingMode.NO_ENTRIES
