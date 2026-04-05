"""
Unit tests for mode-aware throttling in ExecutionWorker.

Tests Requirements 1.1-1.5, 8.1:
- 1.1: SCALPING mode uses min_order_interval_sec of 15 seconds
- 1.2: SWING mode uses min_order_interval_sec of 60 seconds
- 1.3: CONSERVATIVE mode uses min_order_interval_sec of 120 seconds
- 1.4: Runtime configuration of min_order_interval_sec without restart
- 1.5: Exit signals bypass min_order_interval_sec throttle
- 8.1: Exit signals (is_exit_signal=True or reduce_only=True) bypass throttle
"""

import asyncio
import json
import time
import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from quantgambit.execution.execution_worker import ExecutionWorker, ExecutionWorkerConfig
from quantgambit.execution.manager import ExecutionIntent, OrderStatus
from quantgambit.config.trading_mode import (
    TradingMode,
    TradingModeConfig,
    TradingModeManager,
    TRADING_MODE_PRESETS,
)
from quantgambit.storage.redis_streams import RedisStreamsClient


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

    async def expire(self, key, ttl):
        return True


class FakeExecutionManager:
    """Fake execution manager for testing."""
    
    def __init__(self, fail_times=0):
        self.fail_times = fail_times
        self.calls = 0
        self.intent = None
        self.order_store = None
        self.position_manager = FakePositionManager()

    async def execute_intent(self, intent):
        self.calls += 1
        self.intent = intent
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
    ts_us = int(now * 1_000_000)
    return {
        "event_id": event_id,
        "event_type": "risk_decision",
        "schema_version": "v1",
        "timestamp": str(now),
        "ts_recv_us": ts_us,
        "ts_canon_us": ts_us,
        "ts_exchange_s": None,
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


class TestModeAwareThrottleIntervals:
    """Tests for mode-specific min_order_interval_sec values."""
    
    def test_scalping_mode_uses_15s_interval(self):
        """
        Requirement 1.1: SCALPING mode uses min_order_interval_sec of 15 seconds.
        """
        manager = TradingModeManager(default_mode=TradingMode.SCALPING)
        config = manager.get_config("BTCUSDT")
        
        assert config.min_order_interval_sec == 15.0, \
            f"SCALPING mode should use 15s interval, got {config.min_order_interval_sec}"
    
    def test_swing_mode_uses_60s_interval(self):
        """
        Requirement 1.2: SWING mode uses min_order_interval_sec of 60 seconds.
        """
        manager = TradingModeManager(default_mode=TradingMode.SWING)
        config = manager.get_config("BTCUSDT")
        
        assert config.min_order_interval_sec == 60.0, \
            f"SWING mode should use 60s interval, got {config.min_order_interval_sec}"

    def test_spot_mode_uses_15s_interval(self):
        """
        Spot mode keeps the active 15s entry cadence without using the scalp label.
        """
        manager = TradingModeManager(default_mode=TradingMode.SPOT)
        config = manager.get_config("BTCUSDT")

        assert config.min_order_interval_sec == 15.0, \
            f"SPOT mode should use 15s interval, got {config.min_order_interval_sec}"
    
    def test_conservative_mode_uses_120s_interval(self):
        """
        Requirement 1.3: CONSERVATIVE mode uses min_order_interval_sec of 120 seconds.
        """
        manager = TradingModeManager(default_mode=TradingMode.CONSERVATIVE)
        config = manager.get_config("BTCUSDT")
        
        assert config.min_order_interval_sec == 120.0, \
            f"CONSERVATIVE mode should use 120s interval, got {config.min_order_interval_sec}"


class TestExecutionWorkerModeAwareThrottling:
    """Tests for ExecutionWorker using TradingModeManager for throttling."""
    
    def test_worker_uses_mode_manager_interval(self):
        """
        Requirement 1.4: ExecutionWorker uses TradingModeManager for min_order_interval_sec.
        """
        mode_manager = TradingModeManager(default_mode=TradingMode.SCALPING)
        store = FakeOrderStore()
        manager = FakeExecutionManager(fail_times=0)
        manager.order_store = store
        
        worker = ExecutionWorker(
            redis_client=RedisStreamsClient(FakeRedis()),
            execution_manager=manager,
            bot_id="b1",
            exchange="okx",
            config=ExecutionWorkerConfig(
                max_decision_age_sec=999.0,
                min_order_interval_sec=60.0,  # Default config value
            ),
            trading_mode_manager=mode_manager,
        )
        
        # Verify worker has the trading mode manager
        assert worker._trading_mode_manager is not None
        assert worker._trading_mode_manager.get_mode() == TradingMode.SCALPING
    
    @pytest.mark.asyncio
    async def test_worker_throttles_entry_within_interval(self):
        """
        Entry signals within min_order_interval should be throttled.
        """
        mode_manager = TradingModeManager(default_mode=TradingMode.SCALPING)
        store = FakeOrderStore()
        manager = FakeExecutionManager(fail_times=0)
        manager.order_store = store
        
        worker = ExecutionWorker(
            redis_client=RedisStreamsClient(FakeRedis()),
            execution_manager=manager,
            bot_id="b1",
            exchange="okx",
            config=ExecutionWorkerConfig(
                max_decision_age_sec=999.0,
                block_if_position_exists=False,
            ),
            trading_mode_manager=mode_manager,
        )
        
        # Simulate a recent order for BTCUSDT
        worker._last_order_time["BTCUSDT"] = time.time()
        
        # Try to send another entry signal immediately
        payload = create_decision_payload(
            symbol="BTCUSDT",
            side="buy",
            is_exit_signal=False,
            event_id="evt-throttle-1",
        )
        
        await worker._handle_message({"data": json.dumps(payload)})
        
        # Should be throttled - no execution
        assert manager.calls == 0, "Entry signal should be throttled within interval"
        
        # Check error was recorded
        throttle_errors = [e for e in store.errors if e.get("error_code") == "throttled_cooldown"]
        assert len(throttle_errors) > 0, "Throttle error should be recorded"
    
    @pytest.mark.asyncio
    async def test_worker_allows_entry_after_interval(self):
        """
        Entry signals after min_order_interval should be allowed.
        """
        mode_manager = TradingModeManager(default_mode=TradingMode.SCALPING)
        store = FakeOrderStore()
        manager = FakeExecutionManager(fail_times=0)
        manager.order_store = store
        
        worker = ExecutionWorker(
            redis_client=RedisStreamsClient(FakeRedis()),
            execution_manager=manager,
            bot_id="b1",
            exchange="okx",
            config=ExecutionWorkerConfig(
                max_decision_age_sec=999.0,
                block_if_position_exists=False,
            ),
            trading_mode_manager=mode_manager,
        )
        
        # Simulate an old order (20 seconds ago, beyond 15s scalping interval)
        worker._last_order_time["BTCUSDT"] = time.time() - 20.0
        
        payload = create_decision_payload(
            symbol="BTCUSDT",
            side="buy",
            is_exit_signal=False,
            event_id="evt-allowed-1",
        )
        
        await worker._handle_message({"data": json.dumps(payload)})
        
        # Should be allowed - execution happens
        assert manager.calls == 1, "Entry signal should be allowed after interval"

    @pytest.mark.asyncio
    async def test_worker_records_one_throttle_error_per_cooldown_window(self):
        """
        Repeated entry attempts inside one unchanged cooldown window should only
        record one throttle error.
        """
        mode_manager = TradingModeManager(default_mode=TradingMode.SCALPING)
        store = FakeOrderStore()
        manager = FakeExecutionManager(fail_times=0)
        manager.order_store = store

        worker = ExecutionWorker(
            redis_client=RedisStreamsClient(FakeRedis()),
            execution_manager=manager,
            bot_id="b1",
            exchange="okx",
            config=ExecutionWorkerConfig(
                max_decision_age_sec=999.0,
                block_if_position_exists=False,
            ),
            trading_mode_manager=mode_manager,
        )

        worker._last_order_time["BTCUSDT"] = time.time()

        payload1 = create_decision_payload(
            symbol="BTCUSDT",
            side="buy",
            is_exit_signal=False,
            event_id="evt-throttle-window-1",
        )
        payload2 = create_decision_payload(
            symbol="BTCUSDT",
            side="buy",
            is_exit_signal=False,
            event_id="evt-throttle-window-2",
        )

        await worker._handle_message({"data": json.dumps(payload1)})
        await worker._handle_message({"data": json.dumps(payload2)})

        throttle_errors = [e for e in store.errors if e.get("error_code") == "throttled_cooldown"]
        assert len(throttle_errors) == 1, "Throttle error should only be recorded once per cooldown window"

    @pytest.mark.asyncio
    async def test_position_exists_arms_cooldown_for_follow_up_attempts(self):
        mode_manager = TradingModeManager(default_mode=TradingMode.SCALPING)
        store = FakeOrderStore()
        manager = FakeExecutionManager(fail_times=0)
        manager.order_store = store
        manager.position_manager = FakePositionManager(
            positions=[
                type("Pos", (), {"symbol": "BTCUSDT", "side": "long", "size": 1.0})()
            ]
        )

        worker = ExecutionWorker(
            redis_client=RedisStreamsClient(FakeRedis()),
            execution_manager=manager,
            bot_id="b1",
            exchange="okx",
            config=ExecutionWorkerConfig(
                max_decision_age_sec=999.0,
                block_if_position_exists=True,
                enforce_exchange_position_gate=False,
            ),
            trading_mode_manager=mode_manager,
        )

        payload1 = create_decision_payload(
            symbol="BTCUSDT",
            side="buy",
            is_exit_signal=False,
            event_id="evt-position-exists-1",
        )
        payload2 = create_decision_payload(
            symbol="BTCUSDT",
            side="buy",
            is_exit_signal=False,
            event_id="evt-position-exists-2",
        )

        await worker._handle_message({"data": json.dumps(payload1)})
        await worker._handle_message({"data": json.dumps(payload2)})

        assert manager.calls == 0
        assert "BTCUSDT" in worker._last_order_time
        error_codes = [e.get("error_code") for e in store.errors]
        assert error_codes.count("position_exists") == 1
        assert error_codes.count("throttled_cooldown") == 1
        assert manager.calls == 0, "Repeated throttled entry signals should not execute"


class TestExitSignalThrottleBypass:
    """Tests for exit signal throttle bypass (Requirements 1.5, 8.1)."""
    
    @pytest.mark.asyncio
    async def test_exit_signal_bypasses_throttle(self):
        """
        Requirement 1.5, 8.1: Exit signals (is_exit_signal=True) bypass throttle.
        """
        mode_manager = TradingModeManager(default_mode=TradingMode.CONSERVATIVE)
        store = FakeOrderStore()
        manager = FakeExecutionManager(fail_times=0)
        manager.order_store = store
        
        # Add a fake position so exit signal has something to close
        fake_position = MagicMock()
        fake_position.symbol = "BTCUSDT"
        fake_position.side = "long"
        fake_position.size = 1.0
        manager.position_manager = FakePositionManager(positions=[fake_position])
        
        worker = ExecutionWorker(
            redis_client=RedisStreamsClient(FakeRedis()),
            execution_manager=manager,
            bot_id="b1",
            exchange="okx",
            config=ExecutionWorkerConfig(
                max_decision_age_sec=999.0,
                block_if_position_exists=True,
            ),
            trading_mode_manager=mode_manager,
        )
        
        # Simulate a very recent order (should normally be throttled)
        worker._last_order_time["BTCUSDT"] = time.time()
        
        # Send an exit signal
        payload = create_decision_payload(
            symbol="BTCUSDT",
            side="sell",
            is_exit_signal=True,
            reduce_only=False,
            event_id="evt-exit-1",
        )
        
        await worker._handle_message({"data": json.dumps(payload)})
        
        # Exit signal should bypass throttle
        assert manager.calls == 1, "Exit signal should bypass throttle"
    
    @pytest.mark.asyncio
    async def test_reduce_only_signal_bypasses_throttle(self):
        """
        Requirement 8.1: reduce_only signals bypass throttle.
        """
        mode_manager = TradingModeManager(default_mode=TradingMode.CONSERVATIVE)
        store = FakeOrderStore()
        manager = FakeExecutionManager(fail_times=0)
        manager.order_store = store
        
        # Add a fake position
        fake_position = MagicMock()
        fake_position.symbol = "BTCUSDT"
        fake_position.side = "long"
        fake_position.size = 1.0
        manager.position_manager = FakePositionManager(positions=[fake_position])
        
        worker = ExecutionWorker(
            redis_client=RedisStreamsClient(FakeRedis()),
            execution_manager=manager,
            bot_id="b1",
            exchange="okx",
            config=ExecutionWorkerConfig(
                max_decision_age_sec=999.0,
                block_if_position_exists=True,
            ),
            trading_mode_manager=mode_manager,
        )
        
        # Simulate a very recent order
        worker._last_order_time["BTCUSDT"] = time.time()
        
        # Send a reduce_only signal
        payload = create_decision_payload(
            symbol="BTCUSDT",
            side="sell",
            is_exit_signal=False,
            reduce_only=True,
            event_id="evt-reduce-1",
        )
        
        await worker._handle_message({"data": json.dumps(payload)})
        
        # reduce_only signal should bypass throttle
        assert manager.calls == 1, "reduce_only signal should bypass throttle"
    
    @pytest.mark.asyncio
    async def test_entry_signal_does_not_bypass_throttle(self):
        """
        Entry signals (is_exit_signal=False, reduce_only=False) should NOT bypass throttle.
        """
        mode_manager = TradingModeManager(default_mode=TradingMode.SCALPING)
        store = FakeOrderStore()
        manager = FakeExecutionManager(fail_times=0)
        manager.order_store = store
        
        worker = ExecutionWorker(
            redis_client=RedisStreamsClient(FakeRedis()),
            execution_manager=manager,
            bot_id="b1",
            exchange="okx",
            config=ExecutionWorkerConfig(
                max_decision_age_sec=999.0,
                block_if_position_exists=False,
            ),
            trading_mode_manager=mode_manager,
        )
        
        # Simulate a very recent order
        worker._last_order_time["BTCUSDT"] = time.time()
        
        # Send an entry signal
        payload = create_decision_payload(
            symbol="BTCUSDT",
            side="buy",
            is_exit_signal=False,
            reduce_only=False,
            event_id="evt-entry-1",
        )
        
        await worker._handle_message({"data": json.dumps(payload)})
        
        # Entry signal should be throttled
        assert manager.calls == 0, "Entry signal should NOT bypass throttle"


class TestRuntimeModeConfiguration:
    """Tests for runtime mode configuration (Requirement 1.4)."""
    
    @pytest.mark.asyncio
    async def test_mode_change_affects_throttle_interval(self):
        """
        Requirement 1.4: Runtime configuration of min_order_interval_sec without restart.
        """
        mode_manager = TradingModeManager(default_mode=TradingMode.SWING)
        
        # Initially SWING mode (60s interval)
        config = mode_manager.get_config("BTCUSDT")
        assert config.min_order_interval_sec == 60.0
        
        # Change to SCALPING mode at runtime
        await mode_manager.set_mode(TradingMode.SCALPING, persist=False)
        
        # Now should use SCALPING interval (15s)
        config = mode_manager.get_config("BTCUSDT")
        assert config.min_order_interval_sec == 15.0, \
            "Mode change should affect throttle interval immediately"
    
    @pytest.mark.asyncio
    async def test_per_symbol_mode_override(self):
        """
        Per-symbol mode overrides should affect throttle interval.
        """
        mode_manager = TradingModeManager(default_mode=TradingMode.SWING)
        
        # Set BTCUSDT to SCALPING mode
        await mode_manager.set_mode(TradingMode.SCALPING, symbol="BTCUSDT", persist=False)
        
        # BTCUSDT should use SCALPING interval
        btc_config = mode_manager.get_config("BTCUSDT")
        assert btc_config.min_order_interval_sec == 15.0
        
        # ETHUSDT should still use SWING interval
        eth_config = mode_manager.get_config("ETHUSDT")
        assert eth_config.min_order_interval_sec == 60.0


class TestWorkerWithoutModeManager:
    """Tests for ExecutionWorker without TradingModeManager (fallback behavior)."""
    
    @pytest.mark.asyncio
    async def test_worker_uses_config_interval_without_mode_manager(self):
        """
        Without TradingModeManager, worker should use config.min_order_interval_sec.
        """
        store = FakeOrderStore()
        manager = FakeExecutionManager(fail_times=0)
        manager.order_store = store
        
        worker = ExecutionWorker(
            redis_client=RedisStreamsClient(FakeRedis()),
            execution_manager=manager,
            bot_id="b1",
            exchange="okx",
            config=ExecutionWorkerConfig(
                max_decision_age_sec=999.0,
                min_order_interval_sec=30.0,  # Custom interval
                block_if_position_exists=False,
            ),
            trading_mode_manager=None,  # No mode manager
        )
        
        # Simulate a recent order (25 seconds ago)
        worker._last_order_time["BTCUSDT"] = time.time() - 25.0
        
        # Should be throttled (25s < 30s config interval)
        payload = create_decision_payload(
            symbol="BTCUSDT",
            side="buy",
            is_exit_signal=False,
            event_id="evt-no-manager-1",
        )
        
        await worker._handle_message({"data": json.dumps(payload)})
        
        # Should be throttled
        assert manager.calls == 0, "Should use config interval when no mode manager"
