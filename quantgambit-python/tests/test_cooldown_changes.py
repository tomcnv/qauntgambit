"""
Unit tests for CooldownStage changes related to trading throttle fixes.

Tests for:
- Mode-aware cooldown parameters (Requirements 2.1, 2.2, 4.1, 4.2, 4.3)
- Profitable exit hysteresis reduction (Requirement 2.3)
- Exit signal cooldown bypass (Requirements 2.4, 8.2, 8.3)
- Per-symbol entry tracking (Requirement 4.4)
- Hourly counter reset (Requirement 4.5)
"""

import asyncio
import pytest
import time
from unittest.mock import MagicMock

from quantgambit.signals.pipeline import StageContext, StageResult
from quantgambit.signals.stages.cooldown import (
    CooldownStage,
    CooldownConfig,
    CooldownManager,
)
from quantgambit.config.trading_mode import (
    TradingMode,
    TradingModeManager,
    TRADING_MODE_PRESETS,
)
from quantgambit.deeptrader_core.types import TradeCandidate


def make_candidate(
    symbol: str = "BTCUSDT",
    side: str = "long",
    strategy_id: str = "test_strategy",
) -> TradeCandidate:
    """Create a test TradeCandidate."""
    return TradeCandidate(
        symbol=symbol,
        side=side,
        strategy_id=strategy_id,
        profile_id="test_profile",
        expected_edge_bps=20.0,
        confidence=0.7,
        entry_price=50000.0,
        stop_loss=49800.0,
        take_profit=50300.0,
        max_position_usd=5000.0,
        generation_reason="test",
        snapshot_timestamp_ns=int(time.time() * 1e9),
    )


class TestCooldownManagerPnLTracking:
    """Tests for CooldownManager P&L tracking (Requirement 2.3)."""
    
    def test_record_exit_with_positive_pnl(self):
        """Should mark trade as profitable when pnl_pct > 0."""
        manager = CooldownManager()
        
        manager.record_exit("BTCUSDT", pnl_pct=1.5)
        
        assert manager.was_last_trade_profitable("BTCUSDT") is True
        assert manager.get_last_trade_pnl("BTCUSDT") == 1.5
    
    def test_record_exit_with_negative_pnl(self):
        """Should NOT mark trade as profitable when pnl_pct < 0."""
        manager = CooldownManager()
        
        manager.record_exit("BTCUSDT", pnl_pct=-0.5)
        
        assert manager.was_last_trade_profitable("BTCUSDT") is False
        assert manager.get_last_trade_pnl("BTCUSDT") == -0.5
    
    def test_record_exit_with_zero_pnl(self):
        """Should NOT mark trade as profitable when pnl_pct = 0."""
        manager = CooldownManager()
        
        manager.record_exit("BTCUSDT", pnl_pct=0.0)
        
        assert manager.was_last_trade_profitable("BTCUSDT") is False
    
    def test_record_exit_without_pnl(self):
        """Should NOT mark trade as profitable when pnl_pct is None."""
        manager = CooldownManager()
        
        manager.record_exit("BTCUSDT")  # No pnl_pct
        
        assert manager.was_last_trade_profitable("BTCUSDT") is False
        assert manager.get_last_trade_pnl("BTCUSDT") is None
    
    def test_pnl_tracking_per_symbol(self):
        """Should track P&L independently per symbol (Requirement 4.4)."""
        manager = CooldownManager()
        
        manager.record_exit("BTCUSDT", pnl_pct=2.0)
        manager.record_exit("ETHUSDT", pnl_pct=-1.0)
        
        assert manager.was_last_trade_profitable("BTCUSDT") is True
        assert manager.was_last_trade_profitable("ETHUSDT") is False
        assert manager.get_last_trade_pnl("BTCUSDT") == 2.0
        assert manager.get_last_trade_pnl("ETHUSDT") == -1.0


class TestCooldownManagerHourlyTracking:
    """Tests for CooldownManager hourly entry tracking (Requirements 4.4, 4.5)."""
    
    def test_hourly_entry_count_starts_at_zero(self):
        """Should return 0 for symbols with no entries."""
        manager = CooldownManager()
        
        assert manager.get_hourly_entry_count("BTCUSDT") == 0
    
    def test_hourly_entry_count_increments(self):
        """Should increment count on each entry."""
        manager = CooldownManager()
        
        manager.record_entry("BTCUSDT", "strategy1", "long")
        assert manager.get_hourly_entry_count("BTCUSDT") == 1
        
        manager.record_entry("BTCUSDT", "strategy2", "short")
        assert manager.get_hourly_entry_count("BTCUSDT") == 2
    
    def test_hourly_entry_count_per_symbol(self):
        """Should track entries independently per symbol (Requirement 4.4)."""
        manager = CooldownManager()
        
        manager.record_entry("BTCUSDT", "strategy1", "long")
        manager.record_entry("BTCUSDT", "strategy1", "long")
        manager.record_entry("ETHUSDT", "strategy1", "long")
        
        assert manager.get_hourly_entry_count("BTCUSDT") == 2
        assert manager.get_hourly_entry_count("ETHUSDT") == 1
        assert manager.get_hourly_entry_count("SOLUSDT") == 0
    
    def test_hourly_entry_count_cleans_old_entries(self):
        """Should clean up entries older than 1 hour (Requirement 4.5)."""
        manager = CooldownManager()
        
        # Manually add an old entry (more than 1 hour ago)
        old_time = time.time() - 3700  # 1 hour + 100 seconds ago
        manager._hourly_entries["BTCUSDT"] = [old_time]
        
        # Add a recent entry
        manager.record_entry("BTCUSDT", "strategy1", "long")
        
        # Old entry should be cleaned up
        assert manager.get_hourly_entry_count("BTCUSDT") == 1


class TestCooldownStageExitBypass:
    """Tests for exit signal cooldown bypass (Requirements 2.4, 8.2, 8.3)."""
    
    def test_exit_signal_bypasses_entry_cooldown(self):
        """Exit signals should bypass entry cooldown."""
        config = CooldownConfig(default_entry_cooldown_sec=300.0)
        manager = CooldownManager()
        manager.record_entry("BTCUSDT", "test_strategy", "long")
        
        stage = CooldownStage(config=config, manager=manager)
        
        ctx = StageContext(
            symbol="BTCUSDT",
            data={},
            signal={"is_exit_signal": True, "side": "sell"},
        )
        
        result = asyncio.run(stage.run(ctx))
        
        assert result == StageResult.CONTINUE
    
    def test_exit_signal_bypasses_exit_cooldown(self):
        """Exit signals should bypass exit cooldown."""
        config = CooldownConfig(exit_cooldown_sec=300.0)
        manager = CooldownManager()
        manager.record_exit("BTCUSDT")
        
        stage = CooldownStage(config=config, manager=manager)
        
        ctx = StageContext(
            symbol="BTCUSDT",
            data={},
            signal={"is_exit_signal": True, "side": "sell"},
        )
        
        result = asyncio.run(stage.run(ctx))
        
        assert result == StageResult.CONTINUE
    
    def test_exit_signal_bypasses_hysteresis(self):
        """Exit signals should bypass same-direction hysteresis."""
        config = CooldownConfig(same_direction_hysteresis_sec=600.0)
        manager = CooldownManager()
        manager.record_entry("BTCUSDT", "test_strategy", "long")
        
        stage = CooldownStage(config=config, manager=manager)
        
        ctx = StageContext(
            symbol="BTCUSDT",
            data={},
            signal={"is_exit_signal": True, "side": "sell"},
        )
        
        result = asyncio.run(stage.run(ctx))
        
        assert result == StageResult.CONTINUE
    
    def test_exit_signal_bypasses_hourly_limit(self):
        """Exit signals should bypass hourly entry limit."""
        config = CooldownConfig(max_entries_per_hour=1)
        manager = CooldownManager()
        # Record many entries to exceed limit
        for i in range(10):
            manager.record_entry("BTCUSDT", f"strategy{i}", "long")
        
        stage = CooldownStage(config=config, manager=manager)
        
        ctx = StageContext(
            symbol="BTCUSDT",
            data={},
            signal={"is_exit_signal": True, "side": "sell"},
        )
        
        result = asyncio.run(stage.run(ctx))
        
        assert result == StageResult.CONTINUE
    
    def test_reduce_only_signal_bypasses_cooldown(self):
        """reduce_only signals should bypass all cooldowns."""
        config = CooldownConfig(
            default_entry_cooldown_sec=300.0,
            exit_cooldown_sec=300.0,
            same_direction_hysteresis_sec=600.0,
            max_entries_per_hour=1,
        )
        manager = CooldownManager()
        manager.record_entry("BTCUSDT", "test_strategy", "long")
        
        stage = CooldownStage(config=config, manager=manager)
        
        ctx = StageContext(
            symbol="BTCUSDT",
            data={},
            signal={"reduce_only": True, "side": "sell"},
        )
        
        result = asyncio.run(stage.run(ctx))
        
        assert result == StageResult.CONTINUE
    
    def test_exit_signal_records_exit_with_pnl(self):
        """Exit signals should record exit with P&L for hysteresis reduction."""
        manager = CooldownManager()
        stage = CooldownStage(manager=manager)
        
        ctx = StageContext(
            symbol="BTCUSDT",
            data={},
            signal={"is_exit_signal": True, "pnl_pct": 1.5},
        )
        
        asyncio.run(stage.run(ctx))
        
        assert manager.get_time_since_exit("BTCUSDT") is not None
        assert manager.get_last_trade_pnl("BTCUSDT") == 1.5
        assert manager.was_last_trade_profitable("BTCUSDT") is True


class TestCooldownStageHysteresisReduction:
    """Tests for profitable exit hysteresis reduction (Requirement 2.3)."""
    
    def test_hysteresis_reduced_after_profitable_exit(self):
        """Hysteresis should be reduced by 50% after profitable exit."""
        config = CooldownConfig(
            default_entry_cooldown_sec=0.0,  # No entry cooldown
            exit_cooldown_sec=0.0,  # No exit cooldown
            same_direction_hysteresis_sec=100.0,  # 100 second hysteresis
        )
        manager = CooldownManager()
        
        # Record a profitable exit
        manager.record_exit("BTCUSDT", pnl_pct=2.0)
        
        # Record an entry 60 seconds ago (would fail 100s hysteresis, pass 50s)
        manager._last_entry[("BTCUSDT", "test_strategy")] = time.time() - 60
        manager._last_direction["BTCUSDT"] = "long"
        
        stage = CooldownStage(config=config, manager=manager)
        
        candidate = make_candidate(symbol="BTCUSDT", side="long")
        ctx = StageContext(
            symbol="BTCUSDT",
            data={"candidate": candidate},
        )
        
        result = asyncio.run(stage.run(ctx))
        
        # Should pass because 60s > 50s (reduced hysteresis)
        assert result == StageResult.CONTINUE
    
    def test_hysteresis_not_reduced_after_unprofitable_exit(self):
        """Hysteresis should NOT be reduced after unprofitable exit."""
        config = CooldownConfig(
            default_entry_cooldown_sec=0.0,
            exit_cooldown_sec=0.0,
            same_direction_hysteresis_sec=100.0,
        )
        manager = CooldownManager()
        
        # Record an unprofitable exit
        manager.record_exit("BTCUSDT", pnl_pct=-1.0)
        
        # Record an entry 60 seconds ago
        manager._last_entry[("BTCUSDT", "test_strategy")] = time.time() - 60
        manager._last_direction["BTCUSDT"] = "long"
        
        stage = CooldownStage(config=config, manager=manager)
        
        candidate = make_candidate(symbol="BTCUSDT", side="long")
        ctx = StageContext(
            symbol="BTCUSDT",
            data={"candidate": candidate},
        )
        
        result = asyncio.run(stage.run(ctx))
        
        # Should fail because 60s < 100s (full hysteresis)
        assert result == StageResult.REJECT
        assert "same_direction_hysteresis" in ctx.rejection_reason


class TestCooldownStageHourlyLimit:
    """Tests for hourly entry limit (Requirements 4.1, 4.2, 4.3)."""
    
    def test_reject_when_hourly_limit_reached(self):
        """Should reject when hourly entry limit is reached."""
        config = CooldownConfig(
            default_entry_cooldown_sec=0.0,
            exit_cooldown_sec=0.0,
            same_direction_hysteresis_sec=0.0,
            max_entries_per_hour=3,
        )
        manager = CooldownManager()
        
        # Record 3 entries (at limit)
        for i in range(3):
            manager.record_entry("BTCUSDT", f"strategy{i}", "long")
        
        stage = CooldownStage(config=config, manager=manager)
        
        candidate = make_candidate(symbol="BTCUSDT", side="long")
        ctx = StageContext(
            symbol="BTCUSDT",
            data={"candidate": candidate},
        )
        
        result = asyncio.run(stage.run(ctx))
        
        assert result == StageResult.REJECT
        assert "hourly_limit_reached" in ctx.rejection_reason
    
    def test_pass_when_under_hourly_limit(self):
        """Should pass when under hourly entry limit."""
        config = CooldownConfig(
            default_entry_cooldown_sec=0.0,
            exit_cooldown_sec=0.0,
            same_direction_hysteresis_sec=0.0,
            max_entries_per_hour=10,
        )
        manager = CooldownManager()
        
        # Record 5 entries (under limit)
        for i in range(5):
            manager.record_entry("BTCUSDT", f"strategy{i}", "long")
        
        stage = CooldownStage(config=config, manager=manager)
        
        candidate = make_candidate(symbol="BTCUSDT", side="short", strategy_id="new_strategy")
        ctx = StageContext(
            symbol="BTCUSDT",
            data={"candidate": candidate},
        )
        
        result = asyncio.run(stage.run(ctx))
        
        assert result == StageResult.CONTINUE
    
    def test_unlimited_entries_when_zero(self):
        """Should allow unlimited entries when max_entries_per_hour is 0."""
        config = CooldownConfig(
            default_entry_cooldown_sec=0.0,
            exit_cooldown_sec=0.0,
            same_direction_hysteresis_sec=0.0,
            max_entries_per_hour=0,  # Unlimited
        )
        manager = CooldownManager()
        
        # Record many entries
        for i in range(100):
            manager.record_entry("BTCUSDT", f"strategy{i}", "long")
        
        stage = CooldownStage(config=config, manager=manager)
        
        candidate = make_candidate(symbol="BTCUSDT", side="short", strategy_id="new_strategy")
        ctx = StageContext(
            symbol="BTCUSDT",
            data={"candidate": candidate},
        )
        
        result = asyncio.run(stage.run(ctx))
        
        assert result == StageResult.CONTINUE


class TestCooldownStageModeAware:
    """Tests for mode-aware cooldown parameters (Requirements 2.1, 2.2, 4.1-4.3)."""
    
    def test_scalping_mode_uses_30s_hysteresis(self):
        """SCALPING mode should use 30s hysteresis (Requirement 2.1)."""
        manager = TradingModeManager(default_mode=TradingMode.SCALPING)
        cooldown_manager = CooldownManager()
        
        stage = CooldownStage(
            manager=cooldown_manager,
            trading_mode_manager=manager,
        )
        
        config = manager.get_config("BTCUSDT")
        assert config.same_direction_hysteresis_sec == 30.0
    
    def test_swing_mode_uses_120s_hysteresis(self):
        """SWING mode should use 120s hysteresis (Requirement 2.2)."""
        manager = TradingModeManager(default_mode=TradingMode.SWING)
        cooldown_manager = CooldownManager()
        
        stage = CooldownStage(
            manager=cooldown_manager,
            trading_mode_manager=manager,
        )
        
        config = manager.get_config("BTCUSDT")
        assert config.same_direction_hysteresis_sec == 120.0
    
    def test_scalping_mode_uses_50_max_entries(self):
        """SCALPING mode should use max_entries_per_hour of 50 (Requirement 4.1)."""
        config = TRADING_MODE_PRESETS[TradingMode.SCALPING]
        assert config.max_entries_per_hour == 50
    
    def test_swing_mode_uses_10_max_entries(self):
        """SWING mode should use max_entries_per_hour of 10 (Requirement 4.2)."""
        config = TRADING_MODE_PRESETS[TradingMode.SWING]
        assert config.max_entries_per_hour == 10
    
    def test_conservative_mode_uses_6_max_entries(self):
        """CONSERVATIVE mode should use max_entries_per_hour of 6 (Requirement 4.3)."""
        config = TRADING_MODE_PRESETS[TradingMode.CONSERVATIVE]
        assert config.max_entries_per_hour == 6
    
    def test_mode_config_applied_to_cooldown_check(self):
        """Mode config should be applied during cooldown check."""
        mode_manager = TradingModeManager(default_mode=TradingMode.SCALPING)
        cooldown_manager = CooldownManager()
        
        # Record entries to reach SWING limit (10) but not SCALPING limit (50)
        for i in range(10):
            cooldown_manager.record_entry("BTCUSDT", f"strategy{i}", "long")
        
        stage = CooldownStage(
            manager=cooldown_manager,
            trading_mode_manager=mode_manager,
        )
        
        candidate = make_candidate(symbol="BTCUSDT", side="short", strategy_id="new_strategy")
        ctx = StageContext(
            symbol="BTCUSDT",
            data={"candidate": candidate},
        )
        
        result = asyncio.run(stage.run(ctx))
        
        # Should pass because SCALPING allows 50 entries
        assert result == StageResult.CONTINUE
    
    def test_mode_config_blocks_at_limit(self):
        """Mode config should block when limit is reached."""
        mode_manager = TradingModeManager(default_mode=TradingMode.CONSERVATIVE)
        cooldown_manager = CooldownManager()
        
        # Record entries to reach CONSERVATIVE limit (6)
        for i in range(6):
            cooldown_manager.record_entry("BTCUSDT", f"strategy{i}", "long")
        
        stage = CooldownStage(
            manager=cooldown_manager,
            trading_mode_manager=mode_manager,
        )
        
        candidate = make_candidate(symbol="BTCUSDT", side="short", strategy_id="new_strategy")
        ctx = StageContext(
            symbol="BTCUSDT",
            data={"candidate": candidate},
        )
        
        result = asyncio.run(stage.run(ctx))
        
        # Should reject because CONSERVATIVE allows only 6 entries
        assert result == StageResult.REJECT
        assert "hourly_limit_reached" in ctx.rejection_reason


class TestCooldownStageMetrics:
    """Tests for cooldown stage metrics tracking."""
    
    def test_metrics_include_trading_mode(self):
        """Metrics should include trading mode when mode manager is set."""
        mode_manager = TradingModeManager(default_mode=TradingMode.SCALPING)
        cooldown_manager = CooldownManager()
        
        stage = CooldownStage(
            manager=cooldown_manager,
            trading_mode_manager=mode_manager,
        )
        
        candidate = make_candidate(symbol="BTCUSDT", side="long")
        ctx = StageContext(
            symbol="BTCUSDT",
            data={"candidate": candidate},
        )
        
        asyncio.run(stage.run(ctx))
        
        # Check gate decisions for metrics
        gate_decisions = ctx.data.get("gate_decisions", [])
        assert len(gate_decisions) > 0
        
        cooldown_decision = gate_decisions[-1]
        assert cooldown_decision.metrics.get("trading_mode") == "scalping"
    
    def test_metrics_include_hysteresis_reduction(self):
        """Metrics should indicate when hysteresis was reduced."""
        config = CooldownConfig(
            default_entry_cooldown_sec=0.0,
            exit_cooldown_sec=0.0,
            same_direction_hysteresis_sec=100.0,
        )
        manager = CooldownManager()
        
        # Record a profitable exit
        manager.record_exit("BTCUSDT", pnl_pct=2.0)
        
        # Record an entry 60 seconds ago
        manager._last_entry[("BTCUSDT", "test_strategy")] = time.time() - 60
        manager._last_direction["BTCUSDT"] = "long"
        
        stage = CooldownStage(config=config, manager=manager)
        
        candidate = make_candidate(symbol="BTCUSDT", side="long")
        ctx = StageContext(
            symbol="BTCUSDT",
            data={"candidate": candidate},
        )
        
        asyncio.run(stage.run(ctx))
        
        gate_decisions = ctx.data.get("gate_decisions", [])
        assert len(gate_decisions) > 0
        
        cooldown_decision = gate_decisions[-1]
        assert cooldown_decision.metrics.get("hysteresis_reduced") is True
        assert cooldown_decision.metrics.get("last_trade_pnl") == 2.0
