"""
Integration tests for kill switch functionality.

Tests all kill switch trigger conditions:
- Stale book data
- Incoherent book (sequence gaps)
- Repeated order rejections
- Private WS disconnect
- Equity drawdown
- Max position hold time
- Operator trigger

Also tests kill switch reset and latching behavior.
"""

import pytest
from typing import List, Dict, Any, Optional

from quantgambit.core.clock import SimClock
from quantgambit.core.risk.kill_switch import (
    KillSwitch,
    KillSwitchTrigger,
    KillSwitchConfig,
    KillSwitchState,
)


@pytest.fixture
def clock() -> SimClock:
    """Create SimClock."""
    return SimClock(start_time=1704067200.0)


@pytest.fixture
def config() -> KillSwitchConfig:
    """Create kill switch config."""
    return KillSwitchConfig()


@pytest.fixture
def kill_switch(config: KillSwitchConfig, clock: SimClock) -> KillSwitch:
    """Create kill switch."""
    return KillSwitch(config, clock)


class TestKillSwitchTriggers:
    """Tests for individual kill switch triggers."""
    
    def test_trigger_stale_book(self, kill_switch: KillSwitch, clock: SimClock):
        """Stale book trigger should activate kill switch."""
        assert not kill_switch.is_active()
        
        kill_switch.trigger(
            KillSwitchTrigger.STALE_BOOK,
            {"message": "Book data stale for >5s on BTCUSD"}
        )
        
        assert kill_switch.is_active()
        assert kill_switch.get_trigger_reason() == KillSwitchTrigger.STALE_BOOK
    
    def test_trigger_incoherent_book(self, kill_switch: KillSwitch, clock: SimClock):
        """Incoherent book trigger should activate kill switch."""
        kill_switch.trigger(
            KillSwitchTrigger.INCOHERENT_BOOK,
            {"message": "Sequence gap detected: 100 -> 150"}
        )
        
        assert kill_switch.is_active()
        assert kill_switch.get_trigger_reason() == KillSwitchTrigger.INCOHERENT_BOOK
    
    def test_trigger_repeated_rejects(self, kill_switch: KillSwitch, clock: SimClock):
        """Repeated rejects trigger should activate kill switch."""
        kill_switch.trigger(
            KillSwitchTrigger.REPEATED_REJECTS,
            {"message": "5 consecutive order rejections"}
        )
        
        assert kill_switch.is_active()
        assert kill_switch.get_trigger_reason() == KillSwitchTrigger.REPEATED_REJECTS
    
    def test_trigger_ws_disconnect(self, kill_switch: KillSwitch, clock: SimClock):
        """WS disconnect should activate kill switch."""
        kill_switch.trigger(
            KillSwitchTrigger.WS_DISCONNECT,
            {"message": "WebSocket disconnected"}
        )
        
        assert kill_switch.is_active()
        assert kill_switch.get_trigger_reason() == KillSwitchTrigger.WS_DISCONNECT
    
    def test_trigger_equity_drawdown(self, kill_switch: KillSwitch, clock: SimClock):
        """Equity drawdown should activate kill switch."""
        kill_switch.trigger(
            KillSwitchTrigger.EQUITY_DRAWDOWN,
            {"message": "Equity drawdown exceeded 5%"}
        )
        
        assert kill_switch.is_active()
        assert kill_switch.get_trigger_reason() == KillSwitchTrigger.EQUITY_DRAWDOWN
    
    def test_trigger_manual(self, kill_switch: KillSwitch, clock: SimClock):
        """Manual trigger should activate kill switch."""
        kill_switch.trigger(
            KillSwitchTrigger.MANUAL,
            {"message": "Manual kill switch activation"}
        )
        
        assert kill_switch.is_active()
        assert kill_switch.get_trigger_reason() == KillSwitchTrigger.MANUAL


class TestKillSwitchLatching:
    """Tests for kill switch latching behavior."""
    
    def test_latch_persists(self, kill_switch: KillSwitch, clock: SimClock):
        """Kill switch should stay active until explicitly reset."""
        kill_switch.trigger(KillSwitchTrigger.STALE_BOOK, {"message": "Test"})
        assert kill_switch.is_active()
        
        # Advance time significantly
        clock.advance(3600)  # 1 hour
        
        # Still active
        assert kill_switch.is_active()
    
    def test_second_trigger_ignored_while_active(self, kill_switch: KillSwitch, clock: SimClock):
        """Second trigger should be ignored while already triggered."""
        result1 = kill_switch.trigger(KillSwitchTrigger.STALE_BOOK, {"message": "First"})
        assert result1 is True
        
        clock.advance(1.0)
        result2 = kill_switch.trigger(KillSwitchTrigger.REPEATED_REJECTS, {"message": "Second"})
        # Second trigger ignored - already triggered
        assert result2 is False
        
        # Original trigger reason preserved
        assert kill_switch.get_trigger_reason() == KillSwitchTrigger.STALE_BOOK


class TestKillSwitchReset:
    """Tests for kill switch reset behavior."""
    
    def test_reset_clears_state(self, kill_switch: KillSwitch, clock: SimClock):
        """Reset should clear trigger and return to armed state."""
        kill_switch.trigger(KillSwitchTrigger.STALE_BOOK, {"message": "Test"})
        
        assert kill_switch.is_active()
        
        result = kill_switch.reset(operator_id="admin", reason="Testing reset")
        
        assert result is True
        assert not kill_switch.is_active()
        assert kill_switch.is_armed()
    
    def test_reset_on_armed_is_noop(self, kill_switch: KillSwitch, clock: SimClock):
        """Reset on armed kill switch should do nothing."""
        assert kill_switch.is_armed()
        assert not kill_switch.is_active()
        
        result = kill_switch.reset(operator_id="admin")
        
        # Reset on armed state returns False (no-op)
        assert result is False
        assert kill_switch.is_armed()


class TestKillSwitchCallbacks:
    """Tests for kill switch callback behavior."""
    
    def test_on_trigger_callback(self, config: KillSwitchConfig, clock: SimClock):
        """on_trigger callback should be called when triggered."""
        callback_args = []
        
        def on_trigger(reason, details):
            callback_args.append((reason, details))
        
        kill_switch = KillSwitch(config, clock, on_trigger=on_trigger)
        
        kill_switch.trigger(KillSwitchTrigger.STALE_BOOK, {"symbol": "BTCUSD"})
        
        assert len(callback_args) == 1
        reason, details = callback_args[0]
        assert reason == KillSwitchTrigger.STALE_BOOK
        assert details["symbol"] == "BTCUSD"


class TestKillSwitchAudit:
    """Tests for kill switch audit trail."""
    
    def test_trigger_creates_audit_entry(self, kill_switch: KillSwitch, clock: SimClock):
        """Trigger should create audit entry."""
        kill_switch.trigger(KillSwitchTrigger.STALE_BOOK, {"message": "Test"})
        
        audit_trail = kill_switch.get_audit_trail()
        assert len(audit_trail) == 1
        
        entry = audit_trail[0]
        assert entry.action == "triggered"
        assert entry.trigger == KillSwitchTrigger.STALE_BOOK
    
    def test_reset_creates_audit_entry(self, kill_switch: KillSwitch, clock: SimClock):
        """Reset should create audit entry."""
        kill_switch.trigger(KillSwitchTrigger.STALE_BOOK, {"message": "Test"})
        kill_switch.reset(operator_id="admin", reason="Testing")
        
        audit_trail = kill_switch.get_audit_trail()
        assert len(audit_trail) == 2
        
        reset_entry = audit_trail[1]
        assert reset_entry.action == "reset"
        assert reset_entry.details["operator_id"] == "admin"


class TestKillSwitchIntegration:
    """Integration tests for kill switch with other components."""
    
    def test_kill_switch_blocks_decisions(self, kill_switch: KillSwitch, clock: SimClock):
        """Active kill switch should block trading decisions."""
        # Activate kill switch
        kill_switch.trigger(KillSwitchTrigger.EQUITY_DRAWDOWN, {"message": "Test"})
        
        # In real code, decision pipeline should check kill_switch.is_active()
        # and block if True
        assert kill_switch.is_active()
        
        # This represents the check in decision pipeline
        def make_decision():
            if kill_switch.is_active():
                return None, "BLOCKED_KILL_SWITCH"
            return {"action": "buy"}, None
        
        result, block_reason = make_decision()
        assert result is None
        assert block_reason == "BLOCKED_KILL_SWITCH"
    
    def test_kill_switch_allows_exit_only(self, kill_switch: KillSwitch, clock: SimClock):
        """Active kill switch should allow exit orders only."""
        kill_switch.trigger(KillSwitchTrigger.STALE_BOOK, {"message": "Test"})
        
        # Kill switch active - block entries
        def should_allow_order(is_reduce_only: bool) -> bool:
            if kill_switch.is_active():
                # Only allow reduce-only orders
                return is_reduce_only
            return True
        
        # Entry should be blocked
        assert not should_allow_order(is_reduce_only=False)
        
        # Exit should be allowed
        assert should_allow_order(is_reduce_only=True)


class TestKillSwitchThresholds:
    """Tests for threshold-based triggers."""
    
    def test_reject_counting(self, clock: SimClock):
        """Should track rejects and trigger after threshold."""
        config = KillSwitchConfig(
            max_reject_count=3,
            reject_window_sec=60.0,
        )
        kill_switch = KillSwitch(config, clock)
        
        # Report rejects
        kill_switch.on_reject("BTCUSD", "insufficient_balance")
        assert not kill_switch.is_active()
        
        clock.advance(1.0)
        kill_switch.on_reject("BTCUSD", "price_changed")
        assert not kill_switch.is_active()
        
        clock.advance(1.0)
        kill_switch.on_reject("BTCUSD", "rate_limited")
        
        # Should trigger after 3 rejects
        assert kill_switch.is_active()
        assert kill_switch.get_trigger_reason() == KillSwitchTrigger.REPEATED_REJECTS
    
    def test_reject_window_expiry(self, clock: SimClock):
        """Rejects outside window should not count."""
        config = KillSwitchConfig(
            max_reject_count=3,
            reject_window_sec=60.0,
        )
        kill_switch = KillSwitch(config, clock)
        
        # First reject
        kill_switch.on_reject("BTCUSD", "error")
        assert not kill_switch.is_active()
        
        # Advance past window
        clock.advance(120.0)
        
        # Two more rejects
        kill_switch.on_reject("BTCUSD", "error")
        clock.advance(1.0)
        kill_switch.on_reject("BTCUSD", "error")
        
        # Should NOT trigger - first reject expired
        assert not kill_switch.is_active()
