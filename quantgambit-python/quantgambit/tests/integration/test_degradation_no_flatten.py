"""
Integration tests for graceful degradation - verifying NO_ENTRIES instead of FLATTEN.

Tests:
- Staleness triggers NO_ENTRIES, not FLATTEN (unless extreme)
- WS disconnect doesn't trigger FLATTEN by default
- Exits are always allowed regardless of mode
- Mode transitions follow proper cooldowns
"""

import pytest
import time
from quantgambit.risk.degradation import (
    DegradationManager,
    DegradationConfig,
    TradingMode,
)


class TestNoFlattenOnStaleness:
    """Verify staleness doesn't trigger flatten prematurely."""
    
    def test_trade_stale_30s_triggers_no_entries(self):
        """30s trade staleness should trigger NO_ENTRIES, not FLATTEN."""
        config = DegradationConfig(
            trade_stale_reduce_sec=15.0,
            trade_stale_no_entry_sec=30.0,
            trade_stale_flatten_sec=600.0,  # 10 min - very conservative
        )
        manager = DegradationManager(config)
        
        decision = manager.evaluate(
            symbol="BTCUSDT",
            feed_staleness={"trade": 35.0},  # 35s stale
        )
        
        assert decision.mode == TradingMode.NO_ENTRIES
        assert decision.allows_entries is False
        assert decision.allows_exits is True  # Exits always allowed
        assert decision.should_flatten is False
        assert "trade_stale_no_entry" in decision.reasons[0]
    
    def test_orderbook_stale_30s_triggers_no_entries(self):
        """30s orderbook staleness should trigger NO_ENTRIES, not FLATTEN."""
        config = DegradationConfig(
            orderbook_stale_reduce_sec=10.0,
            orderbook_stale_no_entry_sec=30.0,
            orderbook_stale_flatten_sec=600.0,
        )
        manager = DegradationManager(config)
        
        decision = manager.evaluate(
            symbol="BTCUSDT",
            feed_staleness={"orderbook": 45.0},  # 45s stale
        )
        
        assert decision.mode == TradingMode.NO_ENTRIES
        assert decision.allows_entries is False
        assert decision.allows_exits is True
        assert decision.should_flatten is False
    
    def test_extreme_staleness_triggers_flatten(self):
        """Only extreme staleness (10+ min) should trigger FLATTEN."""
        config = DegradationConfig(
            trade_stale_flatten_sec=600.0,  # 10 min
        )
        manager = DegradationManager(config)
        
        decision = manager.evaluate(
            symbol="BTCUSDT",
            feed_staleness={"trade": 650.0},  # 10+ min stale
        )
        
        assert decision.mode == TradingMode.FLATTEN
        assert decision.should_flatten is True
        assert "trade_stale_flatten" in decision.reasons[0]
    
    def test_moderate_staleness_reduce_size(self):
        """Moderate staleness should reduce size, not block entries."""
        config = DegradationConfig(
            trade_stale_reduce_sec=15.0,
            trade_stale_no_entry_sec=30.0,
        )
        manager = DegradationManager(config)
        
        decision = manager.evaluate(
            symbol="BTCUSDT",
            feed_staleness={"trade": 20.0},  # 20s stale
        )
        
        assert decision.mode == TradingMode.REDUCE_SIZE
        assert decision.allows_entries is True
        assert decision.size_multiplier == 0.5
        assert "trade_stale_reduce" in decision.reasons[0]


class TestWsDisconnectNoFlatten:
    """Verify WS disconnect doesn't trigger flatten by default."""
    
    def test_ws_disconnect_no_flatten_default(self):
        """WS disconnect should NOT trigger flatten with default config."""
        config = DegradationConfig(
            flatten_on_ws_disconnect=False,  # Default
        )
        manager = DegradationManager(config)
        
        decision = manager.evaluate(
            symbol="BTCUSDT",
            ws_connected=False,
        )
        
        # Should be NORMAL because flatten_on_ws_disconnect is False
        assert decision.mode == TradingMode.NORMAL
        assert decision.should_flatten is False
    
    def test_ws_disconnect_flatten_when_enabled(self):
        """WS disconnect should trigger flatten only when explicitly enabled."""
        config = DegradationConfig(
            flatten_on_ws_disconnect=True,  # Explicitly enabled
        )
        manager = DegradationManager(config)
        
        decision = manager.evaluate(
            symbol="BTCUSDT",
            ws_connected=False,
        )
        
        assert decision.mode == TradingMode.FLATTEN
        assert decision.should_flatten is True
        assert "ws_disconnected" in decision.reasons


class TestExitsAlwaysAllowed:
    """Verify exits are allowed in all modes."""
    
    def test_exits_allowed_in_no_entries(self):
        """Exits should be allowed even in NO_ENTRIES mode."""
        config = DegradationConfig()
        manager = DegradationManager(config)
        
        decision = manager.evaluate(
            symbol="BTCUSDT",
            feed_staleness={"trade": 60.0},  # Triggers NO_ENTRIES
        )
        
        assert decision.mode == TradingMode.NO_ENTRIES
        assert decision.allows_exits is True
    
    def test_exits_allowed_in_flatten(self):
        """Exits should be allowed even in FLATTEN mode."""
        config = DegradationConfig(
            trade_stale_flatten_sec=60.0,  # Lower threshold for test
        )
        manager = DegradationManager(config)
        
        decision = manager.evaluate(
            symbol="BTCUSDT",
            feed_staleness={"trade": 120.0},  # Triggers FLATTEN
        )
        
        assert decision.mode == TradingMode.FLATTEN
        assert decision.allows_exits is True
    
    def test_exits_allowed_in_reduce_size(self):
        """Exits should be allowed in REDUCE_SIZE mode."""
        config = DegradationConfig()
        manager = DegradationManager(config)
        
        decision = manager.evaluate(
            symbol="BTCUSDT",
            feed_staleness={"trade": 20.0},  # Triggers REDUCE_SIZE
        )
        
        assert decision.mode == TradingMode.REDUCE_SIZE
        assert decision.allows_exits is True


class TestModeTransitions:
    """Test mode transition logic."""
    
    def test_downgrade_immediate(self):
        """Downgrades (worse mode) should be immediate."""
        config = DegradationConfig(
            upgrade_cooldown_sec=60.0,
            downgrade_cooldown_sec=0.0,
        )
        manager = DegradationManager(config)
        
        # Start in NORMAL
        decision1 = manager.evaluate(symbol="BTCUSDT")
        assert decision1.mode == TradingMode.NORMAL
        
        # Immediate downgrade to NO_ENTRIES
        decision2 = manager.evaluate(
            symbol="BTCUSDT",
            feed_staleness={"trade": 60.0},
        )
        assert decision2.mode == TradingMode.NO_ENTRIES
    
    def test_upgrade_requires_cooldown(self):
        """Upgrades (better mode) should require cooldown."""
        config = DegradationConfig(
            upgrade_cooldown_sec=60.0,
            trade_stale_no_entry_sec=30.0,
        )
        manager = DegradationManager(config)
        
        # Start in NO_ENTRIES
        decision1 = manager.evaluate(
            symbol="BTCUSDT",
            feed_staleness={"trade": 60.0},
        )
        assert decision1.mode == TradingMode.NO_ENTRIES
        
        # Try to upgrade immediately (should stay in NO_ENTRIES due to cooldown)
        decision2 = manager.evaluate(
            symbol="BTCUSDT",
            feed_staleness={"trade": 5.0},  # Data is fresh now
        )
        # Should still be NO_ENTRIES because cooldown hasn't passed
        assert decision2.mode == TradingMode.NO_ENTRIES
    
    def test_upgrade_one_level_at_time(self):
        """Upgrades should only go one level at a time."""
        config = DegradationConfig(
            upgrade_cooldown_sec=0.0,  # Disable cooldown for test
        )
        manager = DegradationManager(config)
        
        # Force into FLATTEN
        manager.force_mode("BTCUSDT", TradingMode.FLATTEN, "test")
        
        # Try to upgrade to NORMAL
        decision = manager.evaluate(
            symbol="BTCUSDT",
            # All healthy conditions
        )
        
        # Should only upgrade one level (FLATTEN -> NO_ENTRIES)
        assert decision.mode == TradingMode.NO_ENTRIES


class TestDataQualityThresholds:
    """Test data quality threshold behavior."""
    
    def test_low_quality_no_entries(self):
        """Low data quality should trigger NO_ENTRIES."""
        config = DegradationConfig(
            quality_reduce_threshold=0.5,
            quality_no_entry_threshold=0.3,
            quality_flatten_threshold=0.05,
        )
        manager = DegradationManager(config)
        
        decision = manager.evaluate(
            symbol="BTCUSDT",
            data_quality=0.2,  # Below no_entry threshold
        )
        
        assert decision.mode == TradingMode.NO_ENTRIES
        assert "quality_no_entry" in decision.reasons[0]
    
    def test_very_low_quality_flatten(self):
        """Very low data quality should trigger FLATTEN."""
        config = DegradationConfig(
            quality_flatten_threshold=0.05,
        )
        manager = DegradationManager(config)
        
        decision = manager.evaluate(
            symbol="BTCUSDT",
            data_quality=0.02,  # Below flatten threshold
        )
        
        assert decision.mode == TradingMode.FLATTEN
        assert "quality_flatten" in decision.reasons[0]


class TestSpreadAndDepthThresholds:
    """Test spread and depth threshold behavior."""
    
    def test_wide_spread_no_entries(self):
        """Wide spread should trigger NO_ENTRIES."""
        config = DegradationConfig(
            spread_reduce_bps=20.0,
            spread_no_entry_bps=50.0,
        )
        manager = DegradationManager(config)
        
        decision = manager.evaluate(
            symbol="BTCUSDT",
            spread_bps=60.0,  # Above no_entry threshold
        )
        
        assert decision.mode == TradingMode.NO_ENTRIES
        assert "spread_no_entry" in decision.reasons[0]
    
    def test_thin_depth_no_entries(self):
        """Thin depth should trigger NO_ENTRIES."""
        config = DegradationConfig(
            depth_reduce_usd=5000.0,
            depth_no_entry_usd=1000.0,
        )
        manager = DegradationManager(config)
        
        decision = manager.evaluate(
            symbol="BTCUSDT",
            bid_depth_usd=500.0,  # Below no_entry threshold
            ask_depth_usd=10000.0,
        )
        
        assert decision.mode == TradingMode.NO_ENTRIES
        assert "depth_no_entry" in decision.reasons[0]


class TestMultipleConditions:
    """Test behavior with multiple degradation conditions."""
    
    def test_most_restrictive_wins(self):
        """Most restrictive mode should win when multiple conditions apply."""
        config = DegradationConfig(
            trade_stale_reduce_sec=15.0,
            spread_no_entry_bps=50.0,
        )
        manager = DegradationManager(config)
        
        decision = manager.evaluate(
            symbol="BTCUSDT",
            feed_staleness={"trade": 20.0},  # REDUCE_SIZE
            spread_bps=60.0,  # NO_ENTRIES
        )
        
        # NO_ENTRIES is more restrictive than REDUCE_SIZE
        assert decision.mode == TradingMode.NO_ENTRIES
        # Both reasons should be present
        assert any("trade_stale_reduce" in r for r in decision.reasons)
        assert any("spread_no_entry" in r for r in decision.reasons)
