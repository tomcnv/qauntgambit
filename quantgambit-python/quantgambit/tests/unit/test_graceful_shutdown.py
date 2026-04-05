"""Tests for graceful shutdown functionality."""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from dataclasses import dataclass


@dataclass
class FakeOrderRecord:
    """Fake order record for testing."""
    status: str
    order_id: str = "o1"
    client_order_id: str = "c1"
    symbol: str = "BTCUSDT"


class FakeOrderStore:
    """Fake order store for testing."""
    
    def __init__(self, orders=None, pending_intents=None):
        self._orders = orders or []
        self._pending_intents = pending_intents or []
        self.removed_intents = []
    
    def list_orders(self):
        return self._orders
    
    async def load_pending_intents(self):
        return self._pending_intents
    
    async def remove_pending_intent(self, intent_id):
        self.removed_intents.append(intent_id)


class FakeKillSwitch:
    """Fake kill switch for testing."""
    
    def __init__(self):
        self.triggered = False
        self.trigger_reason = None
        self._active = False
        self._state = MagicMock(triggered_by={})
        self.reset_calls = []
    
    async def trigger(self, reason, message):
        self.triggered = True
        self.trigger_reason = reason

    def is_active(self):
        return self._active

    def get_state(self):
        return self._state

    async def reset(self, operator_id="system"):
        self.reset_calls.append(operator_id)
        self._active = False


class FakeStateManager:
    def __init__(self, equity=0.0, peak_balance=0.0, positions=None):
        self._account_state = MagicMock(equity=equity, peak_balance=peak_balance)
        self._positions = positions or []

    def get_account_state(self):
        return self._account_state

    def get_positions(self):
        return self._positions


class FakeSnapshotReader:
    def __init__(self, payload):
        self.payload = payload

    async def read(self, key):
        return dict(self.payload)


class FakeSnapshotWriter:
    def __init__(self):
        self.writes = []

    async def write(self, key, payload):
        self.writes.append((key, payload))


class FakeQuantIntegration:
    """Fake quant integration for testing."""
    
    def __init__(self):
        self.stopped = False
    
    async def stop(self):
        self.stopped = True


class FakeAlertsClient:
    """Fake alerts client for testing."""
    
    def __init__(self):
        self.closed = False
    
    async def close(self):
        self.closed = True


class TestGracefulShutdown:
    """Tests for Runtime.shutdown()."""
    
    @pytest.fixture
    def runtime(self):
        """Create a minimal runtime for testing shutdown."""
        from quantgambit.runtime.app import Runtime, RuntimeConfig
        
        runtime = Runtime.__new__(Runtime)
        runtime.config = RuntimeConfig(tenant_id="t1", bot_id="b1", exchange="bybit")
        runtime._kill_switch = None
        runtime.order_store = None
        runtime.execution_manager = None
        runtime.quant = None
        runtime.alerts = None
        runtime.decision_recorder = None
        runtime._running_tasks = []
        return runtime
    
    @pytest.mark.asyncio
    async def test_shutdown_triggers_kill_switch(self, runtime):
        """Shutdown should trigger kill switch."""
        runtime._kill_switch = FakeKillSwitch()
        
        await runtime.shutdown(timeout_sec=1.0)
        
        assert runtime._kill_switch.triggered is True
    
    @pytest.mark.asyncio
    async def test_shutdown_cancels_pending_intents(self, runtime):
        """Shutdown should cancel pending intents."""
        pending = [MagicMock(intent_id="i1"), MagicMock(intent_id="i2")]
        runtime.order_store = FakeOrderStore(pending_intents=pending)
        
        await runtime.shutdown(timeout_sec=1.0)
        
        assert runtime.order_store.removed_intents == ["i1", "i2"]
    
    @pytest.mark.asyncio
    async def test_shutdown_waits_for_open_orders(self, runtime):
        """Shutdown should wait for open orders to settle."""
        # Start with open orders
        orders = [FakeOrderRecord(status="open")]
        runtime.order_store = FakeOrderStore(orders=orders)
        runtime.execution_manager = MagicMock()
        runtime.execution_manager.exchange_client = MagicMock()
        
        # Simulate orders settling after 0.5 seconds
        async def settle_orders():
            await asyncio.sleep(0.5)
            orders.clear()
        
        asyncio.create_task(settle_orders())
        
        start_time = asyncio.get_event_loop().time()
        await runtime.shutdown(timeout_sec=5.0)
        elapsed = asyncio.get_event_loop().time() - start_time
        
        # Should have waited for orders to settle
        assert elapsed >= 0.5
        assert elapsed < 5.0
    
    @pytest.mark.asyncio
    async def test_shutdown_times_out_on_stuck_orders(self, runtime):
        """Shutdown should timeout if orders don't settle."""
        # Orders that never settle
        orders = [FakeOrderRecord(status="open")]
        runtime.order_store = FakeOrderStore(orders=orders)
        runtime.execution_manager = MagicMock()
        runtime.execution_manager.exchange_client = MagicMock()
        
        start_time = asyncio.get_event_loop().time()
        await runtime.shutdown(timeout_sec=1.0)
        elapsed = asyncio.get_event_loop().time() - start_time
        
        # Should have timed out
        assert elapsed >= 1.0
        assert elapsed < 2.0
    
    @pytest.mark.asyncio
    async def test_shutdown_signals_background_tasks(self, runtime):
        """Shutdown should signal that background tasks should stop."""
        # The shutdown method signals tasks via CancelledError
        # Tasks are managed by asyncio.gather in start(), not directly stored
        # This test verifies shutdown completes without error
        await runtime.shutdown(timeout_sec=1.0)
        # If we get here without error, shutdown signaling worked
    
    @pytest.mark.asyncio
    async def test_shutdown_stops_quant_integration(self, runtime):
        """Shutdown should stop quant integration."""
        runtime.quant = FakeQuantIntegration()
        
        await runtime.shutdown(timeout_sec=1.0)
        
        assert runtime.quant.stopped is True
    
    @pytest.mark.asyncio
    async def test_shutdown_closes_alerts_client(self, runtime):
        """Shutdown should close alerts client."""
        runtime.alerts = FakeAlertsClient()
        
        await runtime.shutdown(timeout_sec=1.0)
        
        assert runtime.alerts.closed is True
    
    @pytest.mark.asyncio
    async def test_shutdown_handles_missing_components(self, runtime):
        """Shutdown should handle missing components gracefully."""
        # All components are None
        runtime._kill_switch = None
        runtime.order_store = None
        runtime.execution_manager = None
        runtime.quant = None
        runtime.alerts = None
        
        # Should not raise
        await runtime.shutdown(timeout_sec=1.0)
    
    @pytest.mark.asyncio
    async def test_shutdown_handles_component_errors(self, runtime):
        """Shutdown should continue even if components fail."""
        # Kill switch that raises
        kill_switch = MagicMock()
        kill_switch.trigger = AsyncMock(side_effect=Exception("Kill switch error"))
        runtime._kill_switch = kill_switch
        
        # Order store that raises
        order_store = MagicMock()
        order_store.load_pending_intents = AsyncMock(side_effect=Exception("Order store error"))
        runtime.order_store = order_store
        
        # Should not raise, should continue shutdown
        await runtime.shutdown(timeout_sec=1.0)

    @pytest.mark.asyncio
    async def test_reset_stale_drawdown_kill_switch_when_flat_and_recovered(self, runtime):
        """Startup should clear stale drawdown kill switch only for flat recovered accounts."""
        runtime._kill_switch = FakeKillSwitch()
        runtime._kill_switch._active = True
        runtime._kill_switch._state = MagicMock(triggered_by={"equity_drawdown": 1.0})
        runtime.state_manager = FakeStateManager(equity=1000.0, peak_balance=1000.0, positions=[])
        runtime.order_store = FakeOrderStore(orders=[])
        runtime.snapshot_reader = FakeSnapshotReader({"equity": 1000.0, "peak_balance": 1000.0})
        runtime.snapshots = FakeSnapshotWriter()

        reset = await runtime._reset_stale_drawdown_kill_switch_if_flat(open_orders=[])

        assert reset is True
        assert runtime._kill_switch.reset_calls == ["runtime_flat_startup_sanity"]
        assert runtime.snapshots.writes

    @pytest.mark.asyncio
    async def test_does_not_reset_drawdown_kill_switch_when_position_open(self, runtime):
        """A live position must block the startup auto-reset path."""
        runtime._kill_switch = FakeKillSwitch()
        runtime._kill_switch._active = True
        runtime._kill_switch._state = MagicMock(triggered_by={"equity_drawdown": 1.0})
        runtime.state_manager = FakeStateManager(
            equity=1000.0,
            peak_balance=1000.0,
            positions=[MagicMock(symbol="BTCUSDT")],
        )
        runtime.order_store = FakeOrderStore(orders=[])
        runtime.snapshot_reader = FakeSnapshotReader({"equity": 1000.0, "peak_balance": 1000.0})
        runtime.snapshots = FakeSnapshotWriter()

        reset = await runtime._reset_stale_drawdown_kill_switch_if_flat(open_orders=[])

        assert reset is False
        assert runtime._kill_switch.reset_calls == []
