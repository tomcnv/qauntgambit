"""
Canonical event model for the QuantGambit system.

All events flowing through the system use a single EventEnvelope wrapper.
This enables:
- Consistent serialization/deserialization
- Unified audit trail
- Deterministic replay
- Type-safe event handling

Event Type Taxonomy:
- Market: book.snapshot, book.delta, trades, tick
- Strategy: features, decision, risk.block
- Execution: exec.intent, exec.order_send, exec.order_ack, exec.order_reject,
             exec.order_fill, exec.order_cancel, exec.order_canceled
- Ops: ops.kill_switch, ops.health, ops.alert
"""

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Dict, Optional
import json
import uuid

from quantgambit.core.clock import get_clock


# Schema version for EventEnvelope - increment on breaking changes
SCHEMA_VERSION = 1


class EventType(str, Enum):
    """
    Canonical event type taxonomy.
    
    Using str enum for easy serialization and pattern matching.
    """
    
    # Market data events
    BOOK_SNAPSHOT = "book.snapshot"
    BOOK_DELTA = "book.delta"
    TRADES = "trades"
    TICK = "tick"
    
    # Strategy/pipeline events
    FEATURES = "features"
    DECISION = "decision"
    RISK_BLOCK = "risk.block"
    
    # Execution events
    EXEC_INTENT = "exec.intent"
    EXEC_ORDER_SEND = "exec.order_send"
    EXEC_ORDER_ACK = "exec.order_ack"
    EXEC_ORDER_REJECT = "exec.order_reject"
    EXEC_ORDER_FILL = "exec.order_fill"
    EXEC_ORDER_PARTIAL = "exec.order_partial"
    EXEC_ORDER_CANCEL = "exec.order_cancel"
    EXEC_ORDER_CANCELED = "exec.order_canceled"
    EXEC_ORDER_EXPIRED = "exec.order_expired"
    
    # Position events
    POSITION_OPENED = "position.opened"
    POSITION_CLOSED = "position.closed"
    POSITION_UPDATED = "position.updated"
    POSITION_DESYNC = "position.desync"
    POSITION_ORPHAN = "position.orphan"
    POSITION_HEALED = "position.healed"
    
    # Protection/bracket events
    PROTECTION_PLACED = "protection.placed"
    PROTECTION_FAILED = "protection.failed"
    PROTECTION_TRIGGERED = "protection.triggered"
    
    # Book integrity events
    BOOK_UNSAFE = "book.unsafe"
    BOOK_RECOVERED = "book.recovered"
    BOOK_RESYNC = "book.resync"
    
    # Ops/control events
    OPS_KILL_SWITCH = "ops.kill_switch"
    OPS_HEALTH = "ops.health"
    OPS_ALERT = "ops.alert"
    OPS_TRADING_DISABLED = "ops.trading_disabled"
    OPS_TRADING_ENABLED = "ops.trading_enabled"
    
    # Reconciliation events
    RECONCILIATION_START = "reconciliation.start"
    RECONCILIATION_COMPLETE = "reconciliation.complete"
    RECONCILIATION_MISMATCH = "reconciliation.mismatch"
    
    # Raw/debug events
    RAW_WS_MESSAGE = "raw.ws_message"
    RAW_REST_RESPONSE = "raw.rest_response"


class EventSource(str, Enum):
    """
    Event source identifiers.
    
    Format: {venue}.{channel} or {component}
    """
    
    # Venue public feeds
    BYBIT_PUBLIC = "bybit.public"
    OKX_PUBLIC = "okx.public"
    BINANCE_PUBLIC = "binance.public"
    
    # Venue private feeds
    BYBIT_PRIVATE = "bybit.private"
    OKX_PRIVATE = "okx.private"
    BINANCE_PRIVATE = "binance.private"
    
    # Simulator
    SIM_PUBLIC = "sim.public"
    SIM_PRIVATE = "sim.private"
    
    # Internal components
    BOOK_GUARDIAN = "book_guardian"
    FEATURE_ENGINE = "feature_engine"
    DECISION_ENGINE = "decision_engine"
    RISK_ENGINE = "risk_engine"
    EXECUTION_ENGINE = "execution_engine"
    KILL_SWITCH = "kill_switch"
    RECONCILIATION = "reconciliation"
    HOT_PATH = "hot_path"
    RECORDER = "recorder"
    REPLAYER = "replayer"


@dataclass(frozen=True)
class EventEnvelope:
    """
    Canonical event wrapper for all system events.
    
    This is the single envelope format used for:
    - In-process queues
    - Redis streams (side-channel)
    - Recorder files (JSONL)
    - Replay and regression tests
    
    Attributes:
        v: Schema version (for forward compatibility)
        type: Event type from EventType enum
        source: Event source from EventSource enum or string
        symbol: Trading symbol if applicable (e.g., "BTCUSDT")
        ts_wall: Wall clock timestamp (epoch seconds)
        ts_mono: Monotonic timestamp (for latency measurement)
        trace_id: Correlation ID linking decision -> intents -> orders -> fills
        seq: Optional venue sequence/update ID for ordering
        payload: Type-specific event data
        event_id: Unique event identifier (UUID)
    """
    
    v: int
    type: str
    source: str
    ts_wall: float
    ts_mono: float
    trace_id: str
    payload: Dict[str, Any]
    symbol: Optional[str] = None
    seq: Optional[int] = None
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    
    @classmethod
    def create(
        cls,
        event_type: EventType | str,
        source: EventSource | str,
        payload: Dict[str, Any],
        symbol: Optional[str] = None,
        trace_id: Optional[str] = None,
        seq: Optional[int] = None,
    ) -> "EventEnvelope":
        """
        Create a new event with current timestamps.
        
        Args:
            event_type: Type of event (EventType enum or string)
            source: Source of event (EventSource enum or string)
            payload: Event-specific data
            symbol: Trading symbol if applicable
            trace_id: Correlation ID (generated if not provided)
            seq: Venue sequence number if applicable
            
        Returns:
            New EventEnvelope with current timestamps
        """
        clock = get_clock()
        
        return cls(
            v=SCHEMA_VERSION,
            type=event_type.value if isinstance(event_type, EventType) else event_type,
            source=source.value if isinstance(source, EventSource) else source,
            ts_wall=clock.now_wall(),
            ts_mono=clock.now_mono(),
            trace_id=trace_id or str(uuid.uuid4()),
            payload=payload,
            symbol=symbol,
            seq=seq,
        )
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EventEnvelope":
        """
        Deserialize from dictionary.
        
        Args:
            data: Dictionary representation of event
            
        Returns:
            EventEnvelope instance
        """
        return cls(
            v=data["v"],
            type=data["type"],
            source=data["source"],
            ts_wall=data["ts_wall"],
            ts_mono=data["ts_mono"],
            trace_id=data["trace_id"],
            payload=data["payload"],
            symbol=data.get("symbol"),
            seq=data.get("seq"),
            event_id=data.get("event_id", str(uuid.uuid4())),
        )
    
    @classmethod
    def from_json(cls, json_str: str) -> "EventEnvelope":
        """
        Deserialize from JSON string.
        
        Args:
            json_str: JSON representation of event
            
        Returns:
            EventEnvelope instance
        """
        return cls.from_dict(json.loads(json_str))
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Serialize to dictionary.
        
        Returns:
            Dictionary representation suitable for JSON serialization
        """
        return asdict(self)
    
    def to_json(self) -> str:
        """
        Serialize to JSON string.
        
        Returns:
            JSON string representation
        """
        return json.dumps(self.to_dict())
    
    def with_trace_id(self, trace_id: str) -> "EventEnvelope":
        """
        Create a copy with a new trace_id.
        
        Args:
            trace_id: New trace ID
            
        Returns:
            New EventEnvelope with updated trace_id
        """
        return EventEnvelope(
            v=self.v,
            type=self.type,
            source=self.source,
            ts_wall=self.ts_wall,
            ts_mono=self.ts_mono,
            trace_id=trace_id,
            payload=self.payload,
            symbol=self.symbol,
            seq=self.seq,
            event_id=self.event_id,
        )
    
    def is_market_event(self) -> bool:
        """Check if this is a market data event."""
        return self.type in {
            EventType.BOOK_SNAPSHOT.value,
            EventType.BOOK_DELTA.value,
            EventType.TRADES.value,
            EventType.TICK.value,
        }
    
    def is_execution_event(self) -> bool:
        """Check if this is an execution event."""
        return self.type.startswith("exec.")
    
    def is_ops_event(self) -> bool:
        """Check if this is an ops/control event."""
        return self.type.startswith("ops.")
    
    def latency_since(self, earlier: "EventEnvelope") -> float:
        """
        Calculate latency in milliseconds since an earlier event.
        
        Args:
            earlier: Earlier event to measure from
            
        Returns:
            Latency in milliseconds
        """
        return (self.ts_mono - earlier.ts_mono) * 1000


# Type aliases for common payloads
BookSnapshotPayload = Dict[str, Any]  # {"bids": [...], "asks": [...], "update_id": int}
BookDeltaPayload = Dict[str, Any]  # {"bids": [...], "asks": [...], "update_id": int}
TradePayload = Dict[str, Any]  # {"price": float, "size": float, "side": str, "trade_id": str}
DecisionPayload = Dict[str, Any]  # Full DecisionRecord fields
OrderPayload = Dict[str, Any]  # Order lifecycle fields


def create_market_event(
    event_type: EventType,
    source: EventSource | str,
    symbol: str,
    payload: Dict[str, Any],
    seq: Optional[int] = None,
) -> EventEnvelope:
    """
    Convenience function to create market data events.
    
    Args:
        event_type: Market event type (BOOK_SNAPSHOT, BOOK_DELTA, TRADES, TICK)
        source: Venue source
        symbol: Trading symbol
        payload: Market data payload
        seq: Venue sequence number
        
    Returns:
        EventEnvelope for market data
    """
    return EventEnvelope.create(
        event_type=event_type,
        source=source,
        payload=payload,
        symbol=symbol,
        seq=seq,
    )


def create_execution_event(
    event_type: EventType,
    source: EventSource | str,
    symbol: str,
    payload: Dict[str, Any],
    trace_id: str,
) -> EventEnvelope:
    """
    Convenience function to create execution events.
    
    Args:
        event_type: Execution event type
        source: Component source
        symbol: Trading symbol
        payload: Order/execution data
        trace_id: Correlation ID
        
    Returns:
        EventEnvelope for execution
    """
    return EventEnvelope.create(
        event_type=event_type,
        source=source,
        payload=payload,
        symbol=symbol,
        trace_id=trace_id,
    )


def create_ops_event(
    event_type: EventType,
    source: EventSource | str,
    payload: Dict[str, Any],
    symbol: Optional[str] = None,
) -> EventEnvelope:
    """
    Convenience function to create ops/control events.
    
    Args:
        event_type: Ops event type
        source: Component source
        payload: Event data
        symbol: Optional symbol if event is symbol-specific
        
    Returns:
        EventEnvelope for ops
    """
    return EventEnvelope.create(
        event_type=event_type,
        source=source,
        payload=payload,
        symbol=symbol,
    )
