"""
Order lifecycle state machine (pure).

This module implements a strict state machine for order lifecycle management.
All transitions are validated and recorded. The state machine is pure - it
has no side effects and can be tested deterministically.

States:
    NEW -> SENT -> ACKED -> PARTIAL -> FILLED
               \-> REJECTED (terminal)
                      \-> CANCEL_REQUESTED -> CANCELED (terminal)
                                          \-> FAILED (terminal)
                                          \-> EXPIRED (terminal)

Invariants (must hold under fuzz testing):
    - 0 <= filled_qty <= qty
    - Terminal states remain terminal
    - FILLED implies filled_qty == qty
    - Duplicate/out-of-order updates cannot corrupt state
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Set, List, Dict, Any
import copy

from quantgambit.core.clock import Clock, get_clock
from quantgambit.core.events import EventEnvelope, EventType, EventSource
from quantgambit.core.ids import IntentIdentity


class OrderState(str, Enum):
    """
    Order lifecycle states.
    
    Using str enum for easy serialization and logging.
    """
    
    # Initial state
    NEW = "new"
    
    # Order sent to exchange
    SENT = "sent"
    
    # Exchange acknowledged the order
    ACKED = "acked"
    
    # Partially filled
    PARTIAL = "partial"
    
    # Terminal: fully filled
    FILLED = "filled"
    
    # Terminal: rejected by exchange
    REJECTED = "rejected"
    
    # Cancel requested
    CANCEL_REQUESTED = "cancel_requested"
    
    # Terminal: successfully canceled
    CANCELED = "canceled"
    
    # Terminal: order failed (e.g., cancel failed)
    FAILED = "failed"
    
    # Terminal: order expired
    EXPIRED = "expired"


# Define valid state transitions
VALID_TRANSITIONS: Dict[OrderState, Set[OrderState]] = {
    OrderState.NEW: {OrderState.SENT, OrderState.CANCELED},
    OrderState.SENT: {
        OrderState.ACKED,
        OrderState.REJECTED,
        OrderState.FILLED,  # Market orders can fill immediately
        OrderState.PARTIAL,  # Can get partial before ack in some cases
        OrderState.CANCELED,  # Can be canceled before ack
        OrderState.EXPIRED,
    },
    OrderState.ACKED: {
        OrderState.PARTIAL,
        OrderState.FILLED,
        OrderState.CANCEL_REQUESTED,
        OrderState.CANCELED,  # Exchange can cancel (e.g., self-trade prevention)
        OrderState.EXPIRED,
    },
    OrderState.PARTIAL: {
        OrderState.PARTIAL,  # More partial fills
        OrderState.FILLED,
        OrderState.CANCEL_REQUESTED,
        OrderState.CANCELED,
        OrderState.EXPIRED,
    },
    OrderState.CANCEL_REQUESTED: {
        OrderState.CANCELED,
        OrderState.FILLED,  # Can fill while cancel in flight
        OrderState.PARTIAL,  # Can get more fills while cancel in flight
        OrderState.FAILED,  # Cancel failed
        OrderState.EXPIRED,
    },
    # Terminal states - no outgoing transitions
    OrderState.FILLED: set(),
    OrderState.REJECTED: set(),
    OrderState.CANCELED: set(),
    OrderState.FAILED: set(),
    OrderState.EXPIRED: set(),
}

# Terminal states
TERMINAL_STATES: Set[OrderState] = {
    OrderState.FILLED,
    OrderState.REJECTED,
    OrderState.CANCELED,
    OrderState.FAILED,
    OrderState.EXPIRED,
}

# States where the order is considered "live" on the exchange
LIVE_STATES: Set[OrderState] = {
    OrderState.SENT,
    OrderState.ACKED,
    OrderState.PARTIAL,
    OrderState.CANCEL_REQUESTED,
}


@dataclass
class OrderTransition:
    """
    Record of a state transition.
    
    Immutable record of what happened and when.
    """
    
    from_state: OrderState
    to_state: OrderState
    ts_mono: float
    ts_wall: float
    reason: Optional[str] = None
    exchange_data: Optional[Dict[str, Any]] = None


@dataclass
class ManagedOrder:
    """
    Order with full lifecycle state management.
    
    This is the core data structure for tracking an order through
    its entire lifecycle. All state changes go through the transition()
    method which validates and records the change.
    
    Attributes:
        identity: Intent ID and client order ID
        symbol: Trading symbol
        side: Order side ("buy" or "sell")
        qty: Order quantity
        order_type: Order type ("market", "limit", etc.)
        price: Limit price (None for market orders)
        reduce_only: Whether this is a reduce-only order
        state: Current lifecycle state
        exchange_order_id: Exchange-assigned order ID
        filled_qty: Total filled quantity
        avg_fill_price: Volume-weighted average fill price
        fees: Total fees paid
        transitions: History of state transitions
        created_at_mono: Monotonic time of creation
        created_at_wall: Wall time of creation
    """
    
    # Identity
    identity: IntentIdentity
    
    # Order parameters
    symbol: str
    side: str
    qty: float
    order_type: str
    price: Optional[float] = None
    reduce_only: bool = False
    
    # State
    state: OrderState = OrderState.NEW
    
    # Exchange-assigned
    exchange_order_id: Optional[str] = None
    
    # Fill tracking
    filled_qty: float = 0.0
    avg_fill_price: Optional[float] = None
    fees: float = 0.0
    
    # Transition history
    transitions: List[OrderTransition] = field(default_factory=list)
    
    # Timestamps
    created_at_mono: float = 0.0
    created_at_wall: float = 0.0
    sent_at_mono: Optional[float] = None
    acked_at_mono: Optional[float] = None
    first_fill_at_mono: Optional[float] = None
    terminal_at_mono: Optional[float] = None
    
    def __post_init__(self):
        """Initialize timestamps if not set."""
        if self.created_at_mono == 0.0:
            clock = get_clock()
            self.created_at_mono = clock.now_mono()
            self.created_at_wall = clock.now_wall()
    
    def can_transition(self, new_state: OrderState) -> bool:
        """
        Check if a transition to new_state is valid.
        
        Args:
            new_state: Target state
            
        Returns:
            True if transition is valid
        """
        return new_state in VALID_TRANSITIONS.get(self.state, set())
    
    def transition(
        self,
        new_state: OrderState,
        clock: Optional[Clock] = None,
        reason: Optional[str] = None,
        exchange_data: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Attempt a state transition.
        
        Args:
            new_state: Target state
            clock: Clock for timestamps (uses global if not provided)
            reason: Optional reason for the transition
            exchange_data: Optional exchange data associated with transition
            
        Returns:
            True if transition succeeded, False if invalid
        """
        if not self.can_transition(new_state):
            return False
        
        clock = clock or get_clock()
        ts_mono = clock.now_mono()
        ts_wall = clock.now_wall()
        
        # Record transition
        transition = OrderTransition(
            from_state=self.state,
            to_state=new_state,
            ts_mono=ts_mono,
            ts_wall=ts_wall,
            reason=reason,
            exchange_data=exchange_data,
        )
        self.transitions.append(transition)
        
        # Update state
        old_state = self.state
        self.state = new_state
        
        # Update timestamps based on new state
        if new_state == OrderState.SENT:
            self.sent_at_mono = ts_mono
        elif new_state == OrderState.ACKED:
            self.acked_at_mono = ts_mono
        elif new_state in {OrderState.PARTIAL, OrderState.FILLED}:
            if self.first_fill_at_mono is None:
                self.first_fill_at_mono = ts_mono
        
        if new_state in TERMINAL_STATES:
            self.terminal_at_mono = ts_mono
        
        return True
    
    def update_fill(
        self,
        filled_qty: float,
        avg_price: float,
        fees: float = 0.0,
    ) -> bool:
        """
        Update fill information.
        
        Args:
            filled_qty: New total filled quantity (must be >= current)
            avg_price: New average fill price
            fees: New total fees
            
        Returns:
            True if update was valid, False if it would violate invariants
        """
        # Invariant: filled_qty must be monotonically increasing
        if filled_qty < self.filled_qty:
            return False
        
        # Invariant: filled_qty cannot exceed order qty
        if filled_qty > self.qty:
            return False
        
        self.filled_qty = filled_qty
        self.avg_fill_price = avg_price
        self.fees = fees
        
        return True
    
    def is_terminal(self) -> bool:
        """Check if order is in a terminal state."""
        return self.state in TERMINAL_STATES
    
    def is_live(self) -> bool:
        """Check if order is live on the exchange."""
        return self.state in LIVE_STATES
    
    def is_filled(self) -> bool:
        """Check if order is fully filled."""
        return self.state == OrderState.FILLED
    
    def is_canceled(self) -> bool:
        """Check if order was canceled."""
        return self.state == OrderState.CANCELED
    
    def remaining_qty(self) -> float:
        """Get unfilled quantity."""
        return self.qty - self.filled_qty
    
    def fill_pct(self) -> float:
        """Get fill percentage (0-100)."""
        if self.qty == 0:
            return 0.0
        return (self.filled_qty / self.qty) * 100
    
    def latency_to_ack_ms(self) -> Optional[float]:
        """Get latency from sent to acked in milliseconds."""
        if self.sent_at_mono is None or self.acked_at_mono is None:
            return None
        return (self.acked_at_mono - self.sent_at_mono) * 1000
    
    def latency_to_first_fill_ms(self) -> Optional[float]:
        """Get latency from sent to first fill in milliseconds."""
        if self.sent_at_mono is None or self.first_fill_at_mono is None:
            return None
        return (self.first_fill_at_mono - self.sent_at_mono) * 1000
    
    def latency_to_terminal_ms(self) -> Optional[float]:
        """Get latency from sent to terminal state in milliseconds."""
        if self.sent_at_mono is None or self.terminal_at_mono is None:
            return None
        return (self.terminal_at_mono - self.sent_at_mono) * 1000
    
    def to_event(self, event_type: EventType, source: EventSource | str) -> EventEnvelope:
        """
        Create an event envelope for this order.
        
        Args:
            event_type: Type of event to create
            source: Event source
            
        Returns:
            EventEnvelope with order data
        """
        return EventEnvelope.create(
            event_type=event_type,
            source=source,
            payload=self.to_dict(),
            symbol=self.symbol,
            trace_id=self.identity.intent_id,
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "intent_id": self.identity.intent_id,
            "client_order_id": self.identity.client_order_id,
            "attempt": self.identity.attempt,
            "symbol": self.symbol,
            "side": self.side,
            "qty": self.qty,
            "order_type": self.order_type,
            "price": self.price,
            "reduce_only": self.reduce_only,
            "state": self.state.value,
            "exchange_order_id": self.exchange_order_id,
            "filled_qty": self.filled_qty,
            "avg_fill_price": self.avg_fill_price,
            "fees": self.fees,
            "created_at_wall": self.created_at_wall,
        }
    
    def copy(self) -> "ManagedOrder":
        """Create a deep copy of this order."""
        return copy.deepcopy(self)


class OrderLifecycleManager:
    """
    Manages a collection of orders through their lifecycles.
    
    This is the main interface for order state management. It:
    - Tracks all orders by various keys (client_order_id, exchange_order_id, intent_id)
    - Processes exchange updates and transitions orders
    - Provides queries for order state
    - Emits events for state changes
    """
    
    def __init__(self, clock: Optional[Clock] = None):
        """
        Initialize the lifecycle manager.
        
        Args:
            clock: Clock for timestamps (uses global if not provided)
        """
        self._clock = clock or get_clock()
        
        # Primary storage: client_order_id -> ManagedOrder
        self._orders: Dict[str, ManagedOrder] = {}
        
        # Indexes for fast lookup
        self._by_exchange_id: Dict[str, str] = {}  # exchange_id -> client_order_id
        self._by_intent_id: Dict[str, List[str]] = {}  # intent_id -> [client_order_ids]
        self._by_symbol: Dict[str, Set[str]] = {}  # symbol -> {client_order_ids}
    
    def register(self, order: ManagedOrder) -> None:
        """
        Register a new order for tracking.
        
        Args:
            order: Order to track
            
        Raises:
            ValueError: If order with same client_order_id already exists
        """
        coid = order.identity.client_order_id
        
        if coid in self._orders:
            raise ValueError(f"Order {coid} already registered")
        
        self._orders[coid] = order
        
        # Update indexes
        intent_id = order.identity.intent_id
        if intent_id not in self._by_intent_id:
            self._by_intent_id[intent_id] = []
        self._by_intent_id[intent_id].append(coid)
        
        if order.symbol not in self._by_symbol:
            self._by_symbol[order.symbol] = set()
        self._by_symbol[order.symbol].add(coid)
    
    def get_by_client_order_id(self, client_order_id: str) -> Optional[ManagedOrder]:
        """Get order by client order ID."""
        return self._orders.get(client_order_id)
    
    def get_by_exchange_id(self, exchange_order_id: str) -> Optional[ManagedOrder]:
        """Get order by exchange order ID."""
        coid = self._by_exchange_id.get(exchange_order_id)
        if coid:
            return self._orders.get(coid)
        return None
    
    def get_by_intent_id(self, intent_id: str) -> List[ManagedOrder]:
        """Get all orders for an intent (including retries)."""
        coids = self._by_intent_id.get(intent_id, [])
        return [self._orders[coid] for coid in coids if coid in self._orders]
    
    def get_live_orders(self, symbol: Optional[str] = None) -> List[ManagedOrder]:
        """
        Get all live (non-terminal) orders.
        
        Args:
            symbol: Optional filter by symbol
            
        Returns:
            List of live orders
        """
        if symbol:
            coids = self._by_symbol.get(symbol, set())
            return [
                self._orders[coid]
                for coid in coids
                if coid in self._orders and self._orders[coid].is_live()
            ]
        return [o for o in self._orders.values() if o.is_live()]
    
    def get_orders_for_symbol(self, symbol: str) -> List[ManagedOrder]:
        """Get all orders for a symbol."""
        coids = self._by_symbol.get(symbol, set())
        return [self._orders[coid] for coid in coids if coid in self._orders]
    
    def process_ack(
        self,
        client_order_id: str,
        exchange_order_id: str,
        exchange_data: Optional[Dict[str, Any]] = None,
    ) -> Optional[ManagedOrder]:
        """
        Process an order acknowledgment from the exchange.
        
        Args:
            client_order_id: Our client order ID
            exchange_order_id: Exchange-assigned order ID
            exchange_data: Raw exchange data
            
        Returns:
            Updated order, or None if not found
        """
        order = self._orders.get(client_order_id)
        if not order:
            return None
        
        # Store exchange order ID
        order.exchange_order_id = exchange_order_id
        self._by_exchange_id[exchange_order_id] = client_order_id
        
        # Transition to ACKED
        order.transition(
            OrderState.ACKED,
            clock=self._clock,
            reason="exchange_ack",
            exchange_data=exchange_data,
        )
        
        return order
    
    def process_fill(
        self,
        client_order_id: Optional[str],
        exchange_order_id: Optional[str],
        filled_qty: float,
        avg_price: float,
        fees: float = 0.0,
        is_complete: bool = False,
        exchange_data: Optional[Dict[str, Any]] = None,
    ) -> Optional[ManagedOrder]:
        """
        Process a fill update from the exchange.
        
        Args:
            client_order_id: Our client order ID (if known)
            exchange_order_id: Exchange order ID (if known)
            filled_qty: Total filled quantity
            avg_price: Average fill price
            fees: Total fees
            is_complete: Whether order is fully filled
            exchange_data: Raw exchange data
            
        Returns:
            Updated order, or None if not found
        """
        # Find order by either ID
        order = None
        if client_order_id:
            order = self._orders.get(client_order_id)
        if not order and exchange_order_id:
            order = self.get_by_exchange_id(exchange_order_id)
        
        if not order:
            return None
        
        # Update fill info
        if not order.update_fill(filled_qty, avg_price, fees):
            # Invalid fill update (would violate invariants)
            return None
        
        # Determine new state
        if is_complete or filled_qty >= order.qty:
            new_state = OrderState.FILLED
        else:
            new_state = OrderState.PARTIAL
        
        # Transition
        order.transition(
            new_state,
            clock=self._clock,
            reason="fill",
            exchange_data=exchange_data,
        )
        
        return order
    
    def process_reject(
        self,
        client_order_id: str,
        reason: str,
        exchange_data: Optional[Dict[str, Any]] = None,
    ) -> Optional[ManagedOrder]:
        """
        Process an order rejection from the exchange.
        
        Args:
            client_order_id: Our client order ID
            reason: Rejection reason
            exchange_data: Raw exchange data
            
        Returns:
            Updated order, or None if not found
        """
        order = self._orders.get(client_order_id)
        if not order:
            return None
        
        order.transition(
            OrderState.REJECTED,
            clock=self._clock,
            reason=reason,
            exchange_data=exchange_data,
        )
        
        return order
    
    def process_cancel(
        self,
        client_order_id: Optional[str],
        exchange_order_id: Optional[str],
        reason: str = "canceled",
        exchange_data: Optional[Dict[str, Any]] = None,
    ) -> Optional[ManagedOrder]:
        """
        Process a cancel confirmation from the exchange.
        
        Args:
            client_order_id: Our client order ID (if known)
            exchange_order_id: Exchange order ID (if known)
            reason: Cancel reason
            exchange_data: Raw exchange data
            
        Returns:
            Updated order, or None if not found
        """
        # Find order by either ID
        order = None
        if client_order_id:
            order = self._orders.get(client_order_id)
        if not order and exchange_order_id:
            order = self.get_by_exchange_id(exchange_order_id)
        
        if not order:
            return None
        
        order.transition(
            OrderState.CANCELED,
            clock=self._clock,
            reason=reason,
            exchange_data=exchange_data,
        )
        
        return order
    
    def request_cancel(self, client_order_id: str) -> Optional[ManagedOrder]:
        """
        Mark an order as cancel requested.
        
        Args:
            client_order_id: Order to cancel
            
        Returns:
            Updated order, or None if not found or can't be canceled
        """
        order = self._orders.get(client_order_id)
        if not order:
            return None
        
        if order.transition(OrderState.CANCEL_REQUESTED, clock=self._clock):
            return order
        return None
    
    def cleanup_terminal(self, max_age_sec: float = 3600) -> int:
        """
        Remove old terminal orders from tracking.
        
        Args:
            max_age_sec: Maximum age of terminal orders to keep
            
        Returns:
            Number of orders removed
        """
        now = self._clock.now_mono()
        cutoff = now - max_age_sec
        
        to_remove = []
        for coid, order in self._orders.items():
            if order.is_terminal() and order.terminal_at_mono and order.terminal_at_mono < cutoff:
                to_remove.append(coid)
        
        for coid in to_remove:
            order = self._orders.pop(coid)
            
            # Clean up indexes
            if order.exchange_order_id:
                self._by_exchange_id.pop(order.exchange_order_id, None)
            
            intent_id = order.identity.intent_id
            if intent_id in self._by_intent_id:
                self._by_intent_id[intent_id] = [
                    c for c in self._by_intent_id[intent_id] if c != coid
                ]
                if not self._by_intent_id[intent_id]:
                    del self._by_intent_id[intent_id]
            
            if order.symbol in self._by_symbol:
                self._by_symbol[order.symbol].discard(coid)
        
        return len(to_remove)
    
    def stats(self) -> Dict[str, Any]:
        """Get manager statistics."""
        by_state = {}
        for order in self._orders.values():
            state = order.state.value
            by_state[state] = by_state.get(state, 0) + 1
        
        return {
            "total_orders": len(self._orders),
            "by_state": by_state,
            "unique_intents": len(self._by_intent_id),
            "symbols_tracked": len(self._by_symbol),
        }
