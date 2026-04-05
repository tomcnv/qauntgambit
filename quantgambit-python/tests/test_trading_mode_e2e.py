"""
End-to-End Integration Tests for Trading Mode System.

Tests the full pipeline with different trading modes (SCALPING, SWING, CONSERVATIVE)
and verifies mode switching during operation.

Requirements tested:
- 5.1: System supports three Trading_Modes: "scalping", "swing", "conservative"
- 5.2: Trading_Mode applies all associated throttle parameters atomically
"""

import asyncio
import json
import time
import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from quantgambit.config.trading_mode import (
    TradingMode,
    TradingModeConfig,
    TradingModeManager,
    TRADING_MODE_PRESETS,
)
from quantgambit.signals.pipeline import (
    StageContext,
    StageResult,
    PositionEvaluationStage,
)
from quantgambit.signals.stages.cooldown import (
    CooldownStage,
    CooldownConfig,
    CooldownManager,
)
from quantgambit.execution.execution_worker import ExecutionWorker, ExecutionWorkerConfig
from quantgambit.storage.redis_streams import RedisStreamsClient
from quantgambit.deeptrader_core.types import TradeCandidate


# ============================================================================
# Test Fixtures and Helpers
# ============================================================================

class FakeRedis:
    """Fake Redis client for testing."""
    
    def __init__(self):
        self.store = {}

    async def xgroup_create(self, stream, group, id="0", mkstream=True):
        return None

    async def xreadgroup(self, group, consumer, streams, count=10, block=1000):
        return []

    async def xack(self, stream, group, message_id):
        return 1

    async def set(self, key, value, nx=False, ex=None):
        if nx and key in self.store:
            return None
        self.store[key] = value
        return True

    async def get(self, key):
        return self.store.get(key)

    async def expire(self, key, ttl):
        return True


class FakeExecutionManager:
    """Fake execution manager for testing."""
    
    def __init__(self, fail_times=0):
        self.fail_times = fail_times
        self.calls = 0
        self.intent = None
        self.order_store = FakeOrderStore()
        self.position_manager = FakePositionManager()
        self.executed_signals = []

    async def execute_intent(self, intent):
        self.calls += 1
        self.intent = intent
        self.executed_signals.append(intent)
        from quantgambit.execution.manager import OrderStatus
        status = "filled" if self.calls > self.fail_times else "rejected"
        return OrderStatus(order_id=f"order-{self.calls}", status=status)

    async def poll_order_status(self, order_id: str, symbol: str):
        return None

    async def record_order_status(self, intent, status):
        return status.status == "filled"


class FakePositionManager:
    """Fake position manager for testing."""
    
    def __init__(self, positions=None):
        self.positions = positions or []
    
    async def list_open_positions(self):
        return self.positions


class FakeOrderStore:
    """Fake order store for testing."""
    
    def __init__(self):
        self.errors = []
        self.intent = None

    async def record_error(self, **kwargs):
        self.errors.append(kwargs)

    async def load_intent_by_client_order_id(self, client_order_id):
        return self.intent

    async def record_intent(self, **kwargs):
        pass


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


def create_decision_payload(
    symbol: str = "BTCUSDT",
    side: str = "buy",
    size: float = 1.0,
    is_exit_signal: bool = False,
    reduce_only: bool = False,
    event_id: str = "evt-1",
) -> dict:
    """Create a test decision payload."""
    now = time.time()
    return {
        "event_id": event_id,
        "event_type": "risk_decision",
        "schema_version": "v1",
        "timestamp": str(now),
        "bot_id": "b1",
        "payload": {
            "symbol": symbol,
            "timestamp": now,
            "status": "accepted",
            "signal": {
                "side": side,
                "size": size,
                "is_exit_signal": is_exit_signal,
                "reduce_only": reduce_only,
            },
        },
    }


# ============================================================================
# End-to-End Integration Tests: Full Pipeline with SCALPING Mode
# ============================================================================

class TestFullPipelineScalpingMode:
    """
    E2E tests for full pipeline with SCALPING mode.
    
    Requirement 5.1: System supports "scalping" Trading_Mode
    Requirement 5.2: Trading_Mode applies all associated throttle parameters atomically
    """
    
    def test_scalping_mode_config_values(self):
        """
        Verify SCALPING mode has correct parameter values.
        
        Requirement 5.1: System supports "scalping" Trading_Mode
        """
        config = TRADING_MODE_PRESETS[TradingMode.SCALPING]
        
        # Verify all SCALPING-specific values
        assert config.min_order_interval_sec == 15.0, "SCALPING should use 15s order interval"
        assert config.entry_cooldown_sec == 15.0, "SCALPING should use 15s entry cooldown"
        assert config.exit_cooldown_sec == 10.0, "SCALPING should use 10s exit cooldown"
        assert config.same_direction_hysteresis_sec == 30.0, "SCALPING should use 30s hysteresis"
        assert config.max_entries_per_hour == 50, "SCALPING should allow 50 entries/hour"
        assert config.min_hold_time_sec == 10.0, "SCALPING should use 10s min hold"
        assert config.min_confirmations_for_exit == 1, "SCALPING should require 1 confirmation"
    
    @pytest.mark.asyncio
    async def test_scalping_mode_cooldown_allows_high_frequency(self):
        """
        E2E: SCALPING mode allows high-frequency entries.
        
        Requirement 5.2: Trading_Mode applies all associated throttle parameters atomically
        """
        mode_manager = TradingModeManager(default_mode=TradingMode.SCALPING)
        cooldown_manager = CooldownManager()
        
        stage = CooldownStage(
            manager=cooldown_manager,
            trading_mode_manager=mode_manager,
        )
        
        # Record 40 entries (under SCALPING limit of 50)
        for i in range(40):
            cooldown_manager.record_entry("BTCUSDT", f"strategy{i}", "long")
        
        # Create a new entry candidate
        candidate = make_candidate(symbol="BTCUSDT", side="short", strategy_id="new_strategy")
        ctx = StageContext(
            symbol="BTCUSDT",
            data={"candidate": candidate},
        )
        
        result = await stage.run(ctx)
        
        # Should pass - SCALPING allows 50 entries/hour
        assert result == StageResult.CONTINUE, \
            "SCALPING mode should allow entry when under 50/hour limit"
    
    @pytest.mark.asyncio
    async def test_scalping_mode_blocks_at_limit(self):
        """
        E2E: SCALPING mode blocks entries at hourly limit.
        
        Requirement 5.2: Trading_Mode applies all associated throttle parameters atomically
        """
        mode_manager = TradingModeManager(default_mode=TradingMode.SCALPING)
        cooldown_manager = CooldownManager()
        
        stage = CooldownStage(
            manager=cooldown_manager,
            trading_mode_manager=mode_manager,
        )
        
        # Record 50 entries (at SCALPING limit)
        for i in range(50):
            cooldown_manager.record_entry("BTCUSDT", f"strategy{i}", "long")
        
        # Create a new entry candidate
        candidate = make_candidate(symbol="BTCUSDT", side="short", strategy_id="new_strategy")
        ctx = StageContext(
            symbol="BTCUSDT",
            data={"candidate": candidate},
        )
        
        result = await stage.run(ctx)
        
        # Should reject - at SCALPING limit of 50
        assert result == StageResult.REJECT, \
            "SCALPING mode should block entry at 50/hour limit"
        assert "hourly_limit_reached" in ctx.rejection_reason
    
    @pytest.mark.asyncio
    async def test_scalping_mode_short_hysteresis(self):
        """
        E2E: SCALPING mode uses short hysteresis (30s).
        
        Requirement 5.2: Trading_Mode applies all associated throttle parameters atomically
        """
        mode_manager = TradingModeManager(default_mode=TradingMode.SCALPING)
        cooldown_manager = CooldownManager()
        
        # Record an entry 35 seconds ago (beyond 30s SCALPING hysteresis)
        cooldown_manager._last_entry[("BTCUSDT", "test_strategy")] = time.time() - 35
        cooldown_manager._last_direction["BTCUSDT"] = "long"
        
        stage = CooldownStage(
            manager=cooldown_manager,
            trading_mode_manager=mode_manager,
        )
        
        # Try same-direction entry
        candidate = make_candidate(symbol="BTCUSDT", side="long", strategy_id="test_strategy")
        ctx = StageContext(
            symbol="BTCUSDT",
            data={"candidate": candidate},
        )
        
        result = await stage.run(ctx)
        
        # Should pass - 35s > 30s SCALPING hysteresis
        assert result == StageResult.CONTINUE, \
            "SCALPING mode should allow same-direction entry after 30s hysteresis"


# ============================================================================
# End-to-End Integration Tests: Full Pipeline with SWING Mode
# ============================================================================

class TestFullPipelineSwingMode:
    """
    E2E tests for full pipeline with SWING mode.
    
    Requirement 5.1: System supports "swing" Trading_Mode
    Requirement 5.2: Trading_Mode applies all associated throttle parameters atomically
    """
    
    def test_swing_mode_config_values(self):
        """
        Verify SWING mode has correct parameter values.
        
        Requirement 5.1: System supports "swing" Trading_Mode
        """
        config = TRADING_MODE_PRESETS[TradingMode.SWING]
        
        # Verify all SWING-specific values
        assert config.min_order_interval_sec == 60.0, "SWING should use 60s order interval"
        assert config.entry_cooldown_sec == 60.0, "SWING should use 60s entry cooldown"
        assert config.exit_cooldown_sec == 30.0, "SWING should use 30s exit cooldown"
        assert config.same_direction_hysteresis_sec == 120.0, "SWING should use 120s hysteresis"
        assert config.max_entries_per_hour == 10, "SWING should allow 10 entries/hour"
        assert config.min_hold_time_sec == 30.0, "SWING should use 30s min hold"
        assert config.min_confirmations_for_exit == 2, "SWING should require 2 confirmations"
    
    @pytest.mark.asyncio
    async def test_swing_mode_blocks_high_frequency(self):
        """
        E2E: SWING mode blocks high-frequency entries.
        
        Requirement 5.2: Trading_Mode applies all associated throttle parameters atomically
        """
        mode_manager = TradingModeManager(default_mode=TradingMode.SWING)
        cooldown_manager = CooldownManager()
        
        stage = CooldownStage(
            manager=cooldown_manager,
            trading_mode_manager=mode_manager,
        )
        
        # Record 10 entries (at SWING limit)
        for i in range(10):
            cooldown_manager.record_entry("BTCUSDT", f"strategy{i}", "long")
        
        # Create a new entry candidate
        candidate = make_candidate(symbol="BTCUSDT", side="short", strategy_id="new_strategy")
        ctx = StageContext(
            symbol="BTCUSDT",
            data={"candidate": candidate},
        )
        
        result = await stage.run(ctx)
        
        # Should reject - at SWING limit of 10
        assert result == StageResult.REJECT, \
            "SWING mode should block entry at 10/hour limit"
        assert "hourly_limit_reached" in ctx.rejection_reason
    
    @pytest.mark.asyncio
    async def test_swing_mode_allows_moderate_frequency(self):
        """
        E2E: SWING mode allows moderate-frequency entries.
        
        Requirement 5.2: Trading_Mode applies all associated throttle parameters atomically
        """
        mode_manager = TradingModeManager(default_mode=TradingMode.SWING)
        cooldown_manager = CooldownManager()
        
        stage = CooldownStage(
            manager=cooldown_manager,
            trading_mode_manager=mode_manager,
        )
        
        # Record 5 entries (under SWING limit of 10)
        for i in range(5):
            cooldown_manager.record_entry("BTCUSDT", f"strategy{i}", "long")
        
        # Create a new entry candidate
        candidate = make_candidate(symbol="BTCUSDT", side="short", strategy_id="new_strategy")
        ctx = StageContext(
            symbol="BTCUSDT",
            data={"candidate": candidate},
        )
        
        result = await stage.run(ctx)
        
        # Should pass - under SWING limit of 10
        assert result == StageResult.CONTINUE, \
            "SWING mode should allow entry when under 10/hour limit"
    
    @pytest.mark.asyncio
    async def test_swing_mode_longer_hysteresis(self):
        """
        E2E: SWING mode uses longer hysteresis (120s).
        
        Requirement 5.2: Trading_Mode applies all associated throttle parameters atomically
        """
        mode_manager = TradingModeManager(default_mode=TradingMode.SWING)
        cooldown_manager = CooldownManager()
        
        # Record an entry 60 seconds ago (within 120s SWING hysteresis)
        cooldown_manager._last_entry[("BTCUSDT", "test_strategy")] = time.time() - 60
        cooldown_manager._last_direction["BTCUSDT"] = "long"
        
        stage = CooldownStage(
            manager=cooldown_manager,
            trading_mode_manager=mode_manager,
        )
        
        # Try same-direction entry
        candidate = make_candidate(symbol="BTCUSDT", side="long", strategy_id="test_strategy")
        ctx = StageContext(
            symbol="BTCUSDT",
            data={"candidate": candidate},
        )
        
        result = await stage.run(ctx)
        
        # Should reject - 60s < 120s SWING hysteresis
        assert result == StageResult.REJECT, \
            "SWING mode should block same-direction entry within 120s hysteresis"
        assert "same_direction_hysteresis" in ctx.rejection_reason
    
    @pytest.mark.asyncio
    async def test_swing_mode_allows_after_hysteresis(self):
        """
        E2E: SWING mode allows entry after hysteresis period.
        
        Requirement 5.2: Trading_Mode applies all associated throttle parameters atomically
        """
        mode_manager = TradingModeManager(default_mode=TradingMode.SWING)
        cooldown_manager = CooldownManager()
        
        # Record an entry 130 seconds ago (beyond 120s SWING hysteresis)
        cooldown_manager._last_entry[("BTCUSDT", "test_strategy")] = time.time() - 130
        cooldown_manager._last_direction["BTCUSDT"] = "long"
        
        stage = CooldownStage(
            manager=cooldown_manager,
            trading_mode_manager=mode_manager,
        )
        
        # Try same-direction entry
        candidate = make_candidate(symbol="BTCUSDT", side="long", strategy_id="test_strategy")
        ctx = StageContext(
            symbol="BTCUSDT",
            data={"candidate": candidate},
        )
        
        result = await stage.run(ctx)
        
        # Should pass - 130s > 120s SWING hysteresis
        assert result == StageResult.CONTINUE, \
            "SWING mode should allow same-direction entry after 120s hysteresis"


# ============================================================================
# End-to-End Integration Tests: Mode Switching During Operation
# ============================================================================

class TestModeSwitchingDuringOperation:
    """
    E2E tests for mode switching during operation.
    
    Requirement 5.2: Trading_Mode applies all associated throttle parameters atomically
    """
    
    @pytest.mark.asyncio
    async def test_switch_from_swing_to_scalping(self):
        """
        E2E: Switching from SWING to SCALPING mode changes parameters immediately.
        
        Requirement 5.2: Trading_Mode applies all associated throttle parameters atomically
        """
        mode_manager = TradingModeManager(default_mode=TradingMode.SWING)
        cooldown_manager = CooldownManager()
        
        stage = CooldownStage(
            manager=cooldown_manager,
            trading_mode_manager=mode_manager,
        )
        
        # Record 10 entries (at SWING limit)
        for i in range(10):
            cooldown_manager.record_entry("BTCUSDT", f"strategy{i}", "long")
        
        # Verify blocked in SWING mode
        candidate = make_candidate(symbol="BTCUSDT", side="short", strategy_id="new_strategy")
        ctx = StageContext(
            symbol="BTCUSDT",
            data={"candidate": candidate},
        )
        
        result = await stage.run(ctx)
        assert result == StageResult.REJECT, "Should be blocked in SWING mode at 10 entries"
        
        # Switch to SCALPING mode
        await mode_manager.set_mode(TradingMode.SCALPING, persist=False)
        
        # Verify now allowed in SCALPING mode (limit is 50)
        ctx2 = StageContext(
            symbol="BTCUSDT",
            data={"candidate": candidate},
        )
        
        result2 = await stage.run(ctx2)
        assert result2 == StageResult.CONTINUE, \
            "Should be allowed after switching to SCALPING mode (limit 50)"
    
    @pytest.mark.asyncio
    async def test_switch_from_scalping_to_conservative(self):
        """
        E2E: Switching from SCALPING to CONSERVATIVE mode changes parameters immediately.
        
        Requirement 5.2: Trading_Mode applies all associated throttle parameters atomically
        """
        mode_manager = TradingModeManager(default_mode=TradingMode.SCALPING)
        cooldown_manager = CooldownManager()
        
        stage = CooldownStage(
            manager=cooldown_manager,
            trading_mode_manager=mode_manager,
        )
        
        # Record 6 entries with old timestamps (at CONSERVATIVE limit, under SCALPING limit)
        # Use old timestamps to avoid entry_cooldown blocking
        old_time = time.time() - 200  # 200 seconds ago
        for i in range(6):
            cooldown_manager._hourly_entries.setdefault("BTCUSDT", []).append(old_time + i)
        
        # Verify allowed in SCALPING mode (limit 50, we have 6)
        candidate = make_candidate(symbol="BTCUSDT", side="short", strategy_id="new_strategy")
        ctx = StageContext(
            symbol="BTCUSDT",
            data={"candidate": candidate},
        )
        
        result = await stage.run(ctx)
        assert result == StageResult.CONTINUE, "Should be allowed in SCALPING mode"
        
        # Switch to CONSERVATIVE mode
        await mode_manager.set_mode(TradingMode.CONSERVATIVE, persist=False)
        
        # Verify now blocked in CONSERVATIVE mode (limit is 6)
        ctx2 = StageContext(
            symbol="BTCUSDT",
            data={"candidate": candidate},
        )
        
        result2 = await stage.run(ctx2)
        assert result2 == StageResult.REJECT, \
            "Should be blocked after switching to CONSERVATIVE mode (limit 6)"
        # Check that hourly_limit_reached is in the rejection reasons
        assert ctx2.rejection_detail is not None
        reasons = ctx2.rejection_detail.get("reasons", [])
        assert any("hourly_limit_reached" in r for r in reasons), \
            f"hourly_limit_reached should be in rejection reasons: {reasons}"
    
    @pytest.mark.asyncio
    async def test_per_symbol_mode_override_during_operation(self):
        """
        E2E: Per-symbol mode override works during operation.
        
        Requirement 5.2: Trading_Mode applies all associated throttle parameters atomically
        """
        mode_manager = TradingModeManager(default_mode=TradingMode.SWING)
        cooldown_manager = CooldownManager()
        
        stage = CooldownStage(
            manager=cooldown_manager,
            trading_mode_manager=mode_manager,
        )
        
        # Record 10 entries for BTCUSDT (at SWING limit)
        for i in range(10):
            cooldown_manager.record_entry("BTCUSDT", f"strategy{i}", "long")
        
        # Record 10 entries for ETHUSDT (at SWING limit)
        for i in range(10):
            cooldown_manager.record_entry("ETHUSDT", f"strategy{i}", "long")
        
        # Both should be blocked in SWING mode
        btc_candidate = make_candidate(symbol="BTCUSDT", side="short", strategy_id="new_strategy")
        eth_candidate = make_candidate(symbol="ETHUSDT", side="short", strategy_id="new_strategy")
        
        btc_ctx = StageContext(symbol="BTCUSDT", data={"candidate": btc_candidate})
        eth_ctx = StageContext(symbol="ETHUSDT", data={"candidate": eth_candidate})
        
        assert await stage.run(btc_ctx) == StageResult.REJECT
        assert await stage.run(eth_ctx) == StageResult.REJECT
        
        # Set BTCUSDT to SCALPING mode (per-symbol override)
        await mode_manager.set_mode(TradingMode.SCALPING, symbol="BTCUSDT", persist=False)
        
        # BTCUSDT should now be allowed (SCALPING limit 50)
        btc_ctx2 = StageContext(symbol="BTCUSDT", data={"candidate": btc_candidate})
        assert await stage.run(btc_ctx2) == StageResult.CONTINUE, \
            "BTCUSDT should be allowed with SCALPING override"
        
        # ETHUSDT should still be blocked (still SWING mode)
        eth_ctx2 = StageContext(symbol="ETHUSDT", data={"candidate": eth_candidate})
        assert await stage.run(eth_ctx2) == StageResult.REJECT, \
            "ETHUSDT should still be blocked in SWING mode"
    
    @pytest.mark.asyncio
    async def test_mode_switch_affects_hysteresis_immediately(self):
        """
        E2E: Mode switch affects hysteresis parameters immediately.
        
        Requirement 5.2: Trading_Mode applies all associated throttle parameters atomically
        """
        mode_manager = TradingModeManager(default_mode=TradingMode.SWING)
        cooldown_manager = CooldownManager()
        
        # Record an entry 60 seconds ago
        cooldown_manager._last_entry[("BTCUSDT", "test_strategy")] = time.time() - 60
        cooldown_manager._last_direction["BTCUSDT"] = "long"
        
        stage = CooldownStage(
            manager=cooldown_manager,
            trading_mode_manager=mode_manager,
        )
        
        # In SWING mode (120s hysteresis), 60s should be blocked
        candidate = make_candidate(symbol="BTCUSDT", side="long", strategy_id="test_strategy")
        ctx = StageContext(symbol="BTCUSDT", data={"candidate": candidate})
        
        result = await stage.run(ctx)
        assert result == StageResult.REJECT, "Should be blocked in SWING mode (60s < 120s)"
        
        # Switch to SCALPING mode (30s hysteresis)
        await mode_manager.set_mode(TradingMode.SCALPING, persist=False)
        
        # Now 60s should be allowed (60s > 30s SCALPING hysteresis)
        ctx2 = StageContext(symbol="BTCUSDT", data={"candidate": candidate})
        result2 = await stage.run(ctx2)
        assert result2 == StageResult.CONTINUE, \
            "Should be allowed after switching to SCALPING mode (60s > 30s)"


# ============================================================================
# End-to-End Integration Tests: Full Pipeline with CONSERVATIVE Mode
# ============================================================================

class TestFullPipelineConservativeMode:
    """
    E2E tests for full pipeline with CONSERVATIVE mode.
    
    Requirement 5.1: System supports "conservative" Trading_Mode
    Requirement 5.2: Trading_Mode applies all associated throttle parameters atomically
    """
    
    def test_conservative_mode_config_values(self):
        """
        Verify CONSERVATIVE mode has correct parameter values.
        
        Requirement 5.1: System supports "conservative" Trading_Mode
        """
        config = TRADING_MODE_PRESETS[TradingMode.CONSERVATIVE]
        
        # Verify all CONSERVATIVE-specific values
        assert config.min_order_interval_sec == 120.0, "CONSERVATIVE should use 120s order interval"
        assert config.entry_cooldown_sec == 120.0, "CONSERVATIVE should use 120s entry cooldown"
        assert config.exit_cooldown_sec == 60.0, "CONSERVATIVE should use 60s exit cooldown"
        assert config.same_direction_hysteresis_sec == 300.0, "CONSERVATIVE should use 300s hysteresis"
        assert config.max_entries_per_hour == 6, "CONSERVATIVE should allow 6 entries/hour"
        assert config.min_hold_time_sec == 60.0, "CONSERVATIVE should use 60s min hold"
        assert config.min_confirmations_for_exit == 2, "CONSERVATIVE should require 2 confirmations"
    
    @pytest.mark.asyncio
    async def test_conservative_mode_strict_limits(self):
        """
        E2E: CONSERVATIVE mode enforces strict entry limits.
        
        Requirement 5.2: Trading_Mode applies all associated throttle parameters atomically
        """
        mode_manager = TradingModeManager(default_mode=TradingMode.CONSERVATIVE)
        cooldown_manager = CooldownManager()
        
        stage = CooldownStage(
            manager=cooldown_manager,
            trading_mode_manager=mode_manager,
        )
        
        # Record 6 entries (at CONSERVATIVE limit)
        for i in range(6):
            cooldown_manager.record_entry("BTCUSDT", f"strategy{i}", "long")
        
        # Create a new entry candidate
        candidate = make_candidate(symbol="BTCUSDT", side="short", strategy_id="new_strategy")
        ctx = StageContext(
            symbol="BTCUSDT",
            data={"candidate": candidate},
        )
        
        result = await stage.run(ctx)
        
        # Should reject - at CONSERVATIVE limit of 6
        assert result == StageResult.REJECT, \
            "CONSERVATIVE mode should block entry at 6/hour limit"
        assert "hourly_limit_reached" in ctx.rejection_reason
    
    @pytest.mark.asyncio
    async def test_conservative_mode_long_hysteresis(self):
        """
        E2E: CONSERVATIVE mode uses long hysteresis (300s).
        
        Requirement 5.2: Trading_Mode applies all associated throttle parameters atomically
        """
        mode_manager = TradingModeManager(default_mode=TradingMode.CONSERVATIVE)
        cooldown_manager = CooldownManager()
        
        # Record an entry 200 seconds ago (within 300s CONSERVATIVE hysteresis)
        cooldown_manager._last_entry[("BTCUSDT", "test_strategy")] = time.time() - 200
        cooldown_manager._last_direction["BTCUSDT"] = "long"
        
        stage = CooldownStage(
            manager=cooldown_manager,
            trading_mode_manager=mode_manager,
        )
        
        # Try same-direction entry
        candidate = make_candidate(symbol="BTCUSDT", side="long", strategy_id="test_strategy")
        ctx = StageContext(
            symbol="BTCUSDT",
            data={"candidate": candidate},
        )
        
        result = await stage.run(ctx)
        
        # Should reject - 200s < 300s CONSERVATIVE hysteresis
        assert result == StageResult.REJECT, \
            "CONSERVATIVE mode should block same-direction entry within 300s hysteresis"
        assert "same_direction_hysteresis" in ctx.rejection_reason


# ============================================================================
# End-to-End Integration Tests: Mode Persistence
# ============================================================================

class TestModePersistence:
    """
    E2E tests for mode persistence across restarts.
    
    Requirement 5.4: System persists Trading_Mode selection across restarts
    """
    
    @pytest.mark.asyncio
    async def test_mode_persists_to_redis(self):
        """
        E2E: Mode changes are persisted to Redis.
        
        Requirement 5.4: System persists Trading_Mode selection across restarts
        """
        fake_redis = FakeRedis()
        mode_manager = TradingModeManager(
            redis_client=fake_redis,
            bot_id="test_bot",
            default_mode=TradingMode.SWING,
        )
        
        # Change mode
        await mode_manager.set_mode(TradingMode.SCALPING, persist=True)
        
        # Verify persisted to Redis
        key = "quantgambit:test_bot:config:trading_mode"
        assert key in fake_redis.store, "Mode should be persisted to Redis"
        
        data = json.loads(fake_redis.store[key])
        assert data["default_mode"] == "scalping", "Persisted mode should be scalping"
    
    @pytest.mark.asyncio
    async def test_mode_loads_from_redis(self):
        """
        E2E: Mode is loaded from Redis on startup.
        
        Requirement 5.4: System persists Trading_Mode selection across restarts
        """
        fake_redis = FakeRedis()
        
        # Pre-populate Redis with saved mode
        key = "quantgambit:test_bot:config:trading_mode"
        fake_redis.store[key] = json.dumps({
            "default_mode": "scalping",
            "symbol_overrides": {"BTCUSDT": "conservative"},
            "updated_at": time.time(),
        })
        
        # Create new manager and load
        mode_manager = TradingModeManager(
            redis_client=fake_redis,
            bot_id="test_bot",
            default_mode=TradingMode.SWING,  # Different default
        )
        
        await mode_manager.load()
        
        # Verify loaded from Redis
        assert mode_manager.default_mode == TradingMode.SCALPING, \
            "Should load default mode from Redis"
        assert mode_manager.get_mode("BTCUSDT") == TradingMode.CONSERVATIVE, \
            "Should load symbol override from Redis"
        assert mode_manager.get_mode("ETHUSDT") == TradingMode.SCALPING, \
            "Non-overridden symbol should use default"
    
    @pytest.mark.asyncio
    async def test_symbol_override_persists(self):
        """
        E2E: Per-symbol mode overrides are persisted.
        
        Requirement 5.4: System persists Trading_Mode selection across restarts
        """
        fake_redis = FakeRedis()
        mode_manager = TradingModeManager(
            redis_client=fake_redis,
            bot_id="test_bot",
            default_mode=TradingMode.SWING,
        )
        
        # Set per-symbol override
        await mode_manager.set_mode(TradingMode.SCALPING, symbol="BTCUSDT", persist=True)
        
        # Verify persisted
        key = "quantgambit:test_bot:config:trading_mode"
        data = json.loads(fake_redis.store[key])
        assert data["symbol_overrides"]["BTCUSDT"] == "scalping", \
            "Symbol override should be persisted"


# ============================================================================
# End-to-End Integration Tests: Atomic Parameter Application
# ============================================================================

class TestAtomicParameterApplication:
    """
    E2E tests verifying all parameters are applied atomically.
    
    Requirement 5.2: Trading_Mode applies all associated throttle parameters atomically
    """
    
    def test_all_parameters_change_together(self):
        """
        E2E: All parameters change atomically when mode changes.
        
        Requirement 5.2: Trading_Mode applies all associated throttle parameters atomically
        """
        mode_manager = TradingModeManager(default_mode=TradingMode.SWING)
        
        # Get SWING config
        swing_config = mode_manager.get_config("BTCUSDT")
        assert swing_config.mode == TradingMode.SWING
        assert swing_config.min_order_interval_sec == 60.0
        assert swing_config.max_entries_per_hour == 10
        assert swing_config.same_direction_hysteresis_sec == 120.0
        
        # Change to SCALPING (synchronous - no await needed for get_config)
        mode_manager._default_mode = TradingMode.SCALPING
        
        # All parameters should change atomically
        scalping_config = mode_manager.get_config("BTCUSDT")
        assert scalping_config.mode == TradingMode.SCALPING
        assert scalping_config.min_order_interval_sec == 15.0
        assert scalping_config.max_entries_per_hour == 50
        assert scalping_config.same_direction_hysteresis_sec == 30.0
        
        # Verify no partial state (all or nothing)
        assert scalping_config.entry_cooldown_sec == 15.0
        assert scalping_config.exit_cooldown_sec == 10.0
        assert scalping_config.min_hold_time_sec == 10.0
        assert scalping_config.min_confirmations_for_exit == 1
    
    def test_mode_config_is_immutable_preset(self):
        """
        E2E: Mode configs are immutable presets (no partial updates).
        
        Requirement 5.2: Trading_Mode applies all associated throttle parameters atomically
        """
        # Get preset configs
        scalping = TRADING_MODE_PRESETS[TradingMode.SCALPING]
        swing = TRADING_MODE_PRESETS[TradingMode.SWING]
        conservative = TRADING_MODE_PRESETS[TradingMode.CONSERVATIVE]
        
        # Verify each is a complete, consistent config
        for config in [scalping, swing, conservative]:
            assert config.min_order_interval_sec > 0
            assert config.entry_cooldown_sec > 0
            assert config.exit_cooldown_sec > 0
            assert config.same_direction_hysteresis_sec > 0
            assert config.max_entries_per_hour > 0
            assert config.min_hold_time_sec >= 0
            assert config.min_confirmations_for_exit >= 1
            assert 0 < config.urgency_bypass_threshold <= 1.0
            assert config.deterioration_force_exit_count >= 1
        
        # Verify ordering: SCALPING < SWING < CONSERVATIVE for restrictive params
        assert scalping.min_order_interval_sec < swing.min_order_interval_sec < conservative.min_order_interval_sec
        assert scalping.same_direction_hysteresis_sec < swing.same_direction_hysteresis_sec < conservative.same_direction_hysteresis_sec
        assert scalping.max_entries_per_hour > swing.max_entries_per_hour > conservative.max_entries_per_hour
