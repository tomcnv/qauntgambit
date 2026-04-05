"""
Kill-switch for emergency trading halt.

The kill-switch is a safety mechanism that:
1. Triggers on various failure conditions
2. Disables all new trading immediately
3. Initiates cancel-all and flatten-all
4. Latches until explicit operator reset

Trigger conditions:
- Stale book data
- Incoherent book (resync loop)
- Repeated order rejects
- Private WebSocket disconnect
- Slippage spike
- Latency breach
- Equity drawdown

The kill-switch is a LATCH - once triggered, it stays triggered
until explicitly reset by an operator. This prevents automated
recovery from masking serious issues.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Dict, Any, List, Callable
import uuid

from quantgambit.core.clock import Clock, get_clock
from quantgambit.core.events import EventEnvelope, EventType, EventSource


class KillSwitchTrigger(str, Enum):
    """Reasons for kill-switch activation."""
    
    STALE_BOOK = "stale_book"
    INCOHERENT_BOOK = "incoherent_book"
    RESYNC_LOOP = "resync_loop"
    REPEATED_REJECTS = "repeated_rejects"
    WS_DISCONNECT = "ws_disconnect"
    SLIPPAGE_SPIKE = "slippage_spike"
    LATENCY_BREACH = "latency_breach"
    EQUITY_DRAWDOWN = "equity_drawdown"
    MARGIN_CALL = "margin_call"
    MANUAL = "manual"
    PROTECTION_FAILURE = "protection_failure"
    RECONCILIATION_FAILURE = "reconciliation_failure"


class KillSwitchState(str, Enum):
    """Kill-switch states."""
    
    ARMED = "armed"  # Normal operation, monitoring
    TRIGGERED = "triggered"  # Kill-switch active, trading disabled
    RECOVERING = "recovering"  # Cleanup in progress
    DISABLED = "disabled"  # Kill-switch disabled (dangerous!)


@dataclass
class KillSwitchConfig:
    """
    Configuration for kill-switch triggers.
    
    Attributes:
        max_reject_count: Rejects before trigger
        reject_window_sec: Window for counting rejects
        max_resync_count: Resyncs before trigger
        resync_window_sec: Window for counting resyncs
        max_slippage_bps: Slippage threshold
        max_latency_p95_ms: Latency threshold
        max_drawdown_pct: Drawdown threshold
        ws_disconnect_timeout_sec: WS disconnect timeout
    """
    
    max_reject_count: int = 5
    reject_window_sec: float = 60.0
    max_resync_count: int = 3
    resync_window_sec: float = 60.0
    max_slippage_bps: float = 100.0  # 1%
    max_latency_p95_ms: float = 500.0
    max_drawdown_pct: float = 10.0
    ws_disconnect_timeout_sec: float = 5.0


@dataclass
class TriggerEvent:
    """Record of a trigger event."""
    
    trigger: KillSwitchTrigger
    ts_mono: float
    ts_wall: float
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class KillSwitchAudit:
    """Audit trail for kill-switch events."""
    
    event_id: str
    action: str  # "triggered", "reset", "cleanup_started", "cleanup_complete"
    trigger: Optional[KillSwitchTrigger]
    ts_wall: float
    ts_mono: float
    details: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "action": self.action,
            "trigger": self.trigger.value if self.trigger else None,
            "ts_wall": self.ts_wall,
            "ts_mono": self.ts_mono,
            "details": self.details,
        }


class KillSwitch:
    """
    Emergency trading halt with latch behavior.
    
    The kill-switch monitors various conditions and triggers
    an emergency halt when thresholds are exceeded.
    
    Key behaviors:
    - Trigger is immediate and synchronous (no I/O)
    - Once triggered, stays triggered until manual reset
    - Emits audit events for all state changes
    - Tracks trigger history for post-mortems
    
    Usage:
        kill_switch = KillSwitch(config, clock)
        
        # Check before trading
        if kill_switch.is_killed():
            return  # Don't trade
        
        # Report events
        kill_switch.on_reject(symbol, reason)
        kill_switch.on_resync(symbol)
        kill_switch.on_ws_disconnect()
        
        # Manual reset (operator action)
        kill_switch.reset(operator_id="ops@example.com")
    """
    
    def __init__(
        self,
        config: Optional[KillSwitchConfig] = None,
        clock: Optional[Clock] = None,
        on_trigger: Optional[Callable[[KillSwitchTrigger, Dict[str, Any]], None]] = None,
    ):
        """
        Initialize kill-switch.
        
        Args:
            config: Trigger configuration
            clock: Clock for timestamps
            on_trigger: Callback when triggered (for cleanup initiation)
        """
        self._config = config or KillSwitchConfig()
        self._clock = clock or get_clock()
        self._on_trigger = on_trigger
        
        # State
        self._state = KillSwitchState.ARMED
        self._trigger_reason: Optional[KillSwitchTrigger] = None
        self._trigger_time_mono: Optional[float] = None
        self._trigger_time_wall: Optional[float] = None
        self._trigger_details: Dict[str, Any] = {}
        
        # Tracking for threshold-based triggers
        self._reject_times: List[float] = []
        self._resync_times: List[float] = []
        self._last_ws_heartbeat: Optional[float] = None
        
        # Audit trail
        self._audit_trail: List[KillSwitchAudit] = []
        
        # Statistics
        self._total_triggers = 0
        self._total_resets = 0
    
    def is_killed(self) -> bool:
        """Check if kill-switch is active (trading disabled)."""
        return self._state in {KillSwitchState.TRIGGERED, KillSwitchState.RECOVERING}
    
    def is_active(self) -> bool:
        """Alias for is_killed() for HotPath compatibility."""
        return self.is_killed()
    
    def is_armed(self) -> bool:
        """Check if kill-switch is armed (normal operation)."""
        return self._state == KillSwitchState.ARMED
    
    def get_state(self) -> KillSwitchState:
        """Get current state."""
        return self._state
    
    def get_trigger_reason(self) -> Optional[KillSwitchTrigger]:
        """Get trigger reason if killed."""
        return self._trigger_reason
    
    def trigger(
        self,
        reason: KillSwitchTrigger,
        details: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Trigger the kill-switch.
        
        This is synchronous and immediate - no I/O.
        
        Args:
            reason: Why the kill-switch was triggered
            details: Additional context
            
        Returns:
            True if newly triggered, False if already triggered
        """
        if self._state != KillSwitchState.ARMED:
            return False  # Already triggered or disabled
        
        now_mono = self._clock.now_mono()
        now_wall = self._clock.now_wall()
        
        self._state = KillSwitchState.TRIGGERED
        self._trigger_reason = reason
        self._trigger_time_mono = now_mono
        self._trigger_time_wall = now_wall
        self._trigger_details = details or {}
        self._total_triggers += 1
        
        # Record audit event
        audit = KillSwitchAudit(
            event_id=str(uuid.uuid4()),
            action="triggered",
            trigger=reason,
            ts_wall=now_wall,
            ts_mono=now_mono,
            details=self._trigger_details,
        )
        self._audit_trail.append(audit)
        
        # Invoke callback (for cleanup initiation)
        if self._on_trigger:
            self._on_trigger(reason, self._trigger_details)
        
        return True
    
    def reset(
        self,
        operator_id: str,
        reason: str = "",
    ) -> bool:
        """
        Reset the kill-switch (operator action).
        
        Args:
            operator_id: Who is resetting
            reason: Why they're resetting
            
        Returns:
            True if reset, False if not triggered
        """
        if self._state not in {KillSwitchState.TRIGGERED, KillSwitchState.RECOVERING}:
            return False
        
        now_mono = self._clock.now_mono()
        now_wall = self._clock.now_wall()
        
        # Record audit event
        audit = KillSwitchAudit(
            event_id=str(uuid.uuid4()),
            action="reset",
            trigger=self._trigger_reason,
            ts_wall=now_wall,
            ts_mono=now_mono,
            details={
                "operator_id": operator_id,
                "reason": reason,
                "was_triggered_at": self._trigger_time_wall,
                "duration_sec": now_mono - (self._trigger_time_mono or now_mono),
            },
        )
        self._audit_trail.append(audit)
        
        # Reset state
        self._state = KillSwitchState.ARMED
        self._trigger_reason = None
        self._trigger_time_mono = None
        self._trigger_time_wall = None
        self._trigger_details = {}
        self._total_resets += 1
        
        # Clear tracking
        self._reject_times.clear()
        self._resync_times.clear()
        
        return True
    
    def mark_recovering(self) -> None:
        """Mark that cleanup is in progress."""
        if self._state == KillSwitchState.TRIGGERED:
            self._state = KillSwitchState.RECOVERING
            
            audit = KillSwitchAudit(
                event_id=str(uuid.uuid4()),
                action="cleanup_started",
                trigger=self._trigger_reason,
                ts_wall=self._clock.now_wall(),
                ts_mono=self._clock.now_mono(),
                details={},
            )
            self._audit_trail.append(audit)
    
    # =========================================================================
    # Event handlers for threshold-based triggers
    # =========================================================================
    
    def on_reject(self, symbol: str, reason: str) -> bool:
        """
        Report an order rejection.
        
        Args:
            symbol: Symbol that was rejected
            reason: Rejection reason
            
        Returns:
            True if this caused a trigger
        """
        if not self.is_armed():
            return False
        
        now = self._clock.now_mono()
        
        # Add to tracking
        self._reject_times.append(now)
        
        # Clean old entries
        cutoff = now - self._config.reject_window_sec
        self._reject_times = [t for t in self._reject_times if t >= cutoff]
        
        # Check threshold
        if len(self._reject_times) >= self._config.max_reject_count:
            return self.trigger(
                KillSwitchTrigger.REPEATED_REJECTS,
                {"symbol": symbol, "reason": reason, "count": len(self._reject_times)},
            )
        
        return False
    
    def on_resync(self, symbol: str) -> bool:
        """
        Report a book resync.
        
        Args:
            symbol: Symbol that needed resync
            
        Returns:
            True if this caused a trigger
        """
        if not self.is_armed():
            return False
        
        now = self._clock.now_mono()
        
        # Add to tracking
        self._resync_times.append(now)
        
        # Clean old entries
        cutoff = now - self._config.resync_window_sec
        self._resync_times = [t for t in self._resync_times if t >= cutoff]
        
        # Check threshold
        if len(self._resync_times) >= self._config.max_resync_count:
            return self.trigger(
                KillSwitchTrigger.RESYNC_LOOP,
                {"symbol": symbol, "count": len(self._resync_times)},
            )
        
        return False
    
    def on_ws_heartbeat(self) -> None:
        """Report WebSocket heartbeat (connection alive)."""
        self._last_ws_heartbeat = self._clock.now_mono()
    
    def check_ws_timeout(self) -> bool:
        """
        Check if WebSocket has timed out.
        
        Returns:
            True if this caused a trigger
        """
        if not self.is_armed():
            return False
        
        if self._last_ws_heartbeat is None:
            return False
        
        now = self._clock.now_mono()
        elapsed = now - self._last_ws_heartbeat
        
        if elapsed > self._config.ws_disconnect_timeout_sec:
            return self.trigger(
                KillSwitchTrigger.WS_DISCONNECT,
                {"elapsed_sec": elapsed, "timeout_sec": self._config.ws_disconnect_timeout_sec},
            )
        
        return False
    
    def on_slippage(self, symbol: str, slippage_bps: float) -> bool:
        """
        Report slippage on a fill.
        
        Args:
            symbol: Symbol
            slippage_bps: Slippage in basis points
            
        Returns:
            True if this caused a trigger
        """
        if not self.is_armed():
            return False
        
        if slippage_bps > self._config.max_slippage_bps:
            return self.trigger(
                KillSwitchTrigger.SLIPPAGE_SPIKE,
                {"symbol": symbol, "slippage_bps": slippage_bps, "threshold_bps": self._config.max_slippage_bps},
            )
        
        return False
    
    def on_latency(self, operation: str, latency_p95_ms: float) -> bool:
        """
        Report latency measurement.
        
        Args:
            operation: What operation was measured
            latency_p95_ms: P95 latency in milliseconds
            
        Returns:
            True if this caused a trigger
        """
        if not self.is_armed():
            return False
        
        if latency_p95_ms > self._config.max_latency_p95_ms:
            return self.trigger(
                KillSwitchTrigger.LATENCY_BREACH,
                {"operation": operation, "latency_p95_ms": latency_p95_ms, "threshold_ms": self._config.max_latency_p95_ms},
            )
        
        return False
    
    def on_drawdown(self, drawdown_pct: float) -> bool:
        """
        Report equity drawdown.
        
        Args:
            drawdown_pct: Drawdown percentage
            
        Returns:
            True if this caused a trigger
        """
        if not self.is_armed():
            return False
        
        if drawdown_pct > self._config.max_drawdown_pct:
            return self.trigger(
                KillSwitchTrigger.EQUITY_DRAWDOWN,
                {"drawdown_pct": drawdown_pct, "threshold_pct": self._config.max_drawdown_pct},
            )
        
        return False
    
    # =========================================================================
    # Audit and stats
    # =========================================================================
    
    def get_audit_trail(self) -> List[KillSwitchAudit]:
        """Get audit trail."""
        return list(self._audit_trail)
    
    def to_event(self) -> EventEnvelope:
        """Create an event envelope for current state."""
        return EventEnvelope.create(
            event_type=EventType.OPS_KILL_SWITCH,
            source=EventSource.KILL_SWITCH,
            payload={
                "state": self._state.value,
                "trigger": self._trigger_reason.value if self._trigger_reason else None,
                "trigger_time": self._trigger_time_wall,
                "details": self._trigger_details,
            },
        )
    
    def stats(self) -> Dict[str, Any]:
        """Get statistics."""
        return {
            "state": self._state.value,
            "trigger_reason": self._trigger_reason.value if self._trigger_reason else None,
            "trigger_time": self._trigger_time_wall,
            "total_triggers": self._total_triggers,
            "total_resets": self._total_resets,
            "recent_rejects": len(self._reject_times),
            "recent_resyncs": len(self._resync_times),
            "audit_trail_size": len(self._audit_trail),
        }
