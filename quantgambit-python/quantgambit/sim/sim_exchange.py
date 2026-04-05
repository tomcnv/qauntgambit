"""
Simulated exchange for deterministic integration tests.

SimExchange provides:
- In-process order matching
- Deterministic execution events
- Configurable latency, fills, rejects
- WebSocket-like event emission

This enables integration testing without:
- Testnet flakiness
- Rate limits
- Inconsistent execution semantics
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Dict, Any, List, Callable, Awaitable
import uuid
import random

from quantgambit.core.clock import SimClock
from quantgambit.core.lifecycle import OrderState, ManagedOrder
from quantgambit.core.ids import IntentIdentity
from quantgambit.core.book.types import OrderBook, Level, BookSide


class FillMode(str, Enum):
    """How orders are filled."""
    
    IMMEDIATE = "immediate"  # Fill immediately at current price
    DELAYED = "delayed"  # Fill after configured delay
    PARTIAL = "partial"  # Partial fills over time
    NEVER = "never"  # Never fill (for testing timeouts)


@dataclass
class SimExchangeConfig:
    """
    Configuration for simulated exchange.
    
    Attributes:
        ack_latency_ms: Latency for order acknowledgment
        fill_latency_ms: Latency for fills (after ack)
        reject_prob: Probability of random rejection
        partial_fill_prob: Probability of partial fill
        partial_fill_pct: Percentage filled on partial
        cancel_latency_ms: Latency for cancel confirmation
        slippage_bps: Slippage in basis points
        fee_rate: Fee rate (e.g., 0.001 = 0.1%)
    """
    
    ack_latency_ms: float = 50.0
    fill_latency_ms: float = 10.0
    reject_prob: float = 0.0
    partial_fill_prob: float = 0.0
    partial_fill_pct: float = 0.5
    cancel_latency_ms: float = 30.0
    slippage_bps: float = 0.0
    fee_rate: float = 0.001


@dataclass
class SimPosition:
    """Simulated position."""
    
    symbol: str
    size: float  # Positive = long, negative = short
    entry_price: float
    unrealized_pnl: float = 0.0


@dataclass
class SimOrder:
    """Simulated order state."""
    
    client_order_id: str
    exchange_order_id: str
    symbol: str
    side: str
    size: float
    order_type: str
    price: Optional[float]
    state: OrderState
    filled_size: float = 0.0
    avg_fill_price: Optional[float] = None
    fees: float = 0.0
    reduce_only: bool = False
    created_at: float = 0.0


# Callback type for WS-like events
WSCallback = Callable[[Dict[str, Any]], Awaitable[None]]


class SimExchange:
    """
    In-process simulated exchange for integration tests.
    
    Provides deterministic order execution with configurable
    latency, fills, rejects, and partial fills.
    
    Usage:
        clock = SimClock()
        sim = SimExchange(clock, config)
        
        # Register WS listener
        async def on_update(update):
            print(f"Got update: {update}")
        sim.add_ws_listener(on_update)
        
        # Place order
        await sim.place_order(order)
        
        # Advance time to trigger fills
        clock.advance(0.1)
        await sim.process_pending()
    """
    
    def __init__(
        self,
        clock: SimClock,
        config: Optional[SimExchangeConfig] = None,
        seed: Optional[int] = None,
    ):
        """
        Initialize simulated exchange.
        
        Args:
            clock: SimClock for deterministic time
            config: Exchange configuration
            seed: Random seed for reproducibility
        """
        self._clock = clock
        self._config = config or SimExchangeConfig()
        self._rng = random.Random(seed)
        
        # Order tracking
        self._orders: Dict[str, SimOrder] = {}  # client_order_id -> order
        self._by_exchange_id: Dict[str, str] = {}  # exchange_id -> client_order_id
        
        # Position tracking
        self._positions: Dict[str, SimPosition] = {}  # symbol -> position
        
        # Order book (for price reference)
        self._books: Dict[str, OrderBook] = {}
        
        # Pending events (scheduled for future)
        self._pending_events: List[tuple[float, str, Dict[str, Any]]] = []
        
        # WS listeners
        self._ws_listeners: List[WSCallback] = []
        
        # Reject patterns (for scenario testing)
        self._reject_patterns: Dict[str, float] = {}  # order_type -> reject_prob
        
        # Statistics
        self._total_orders = 0
        self._total_fills = 0
        self._total_rejects = 0
        self._total_cancels = 0
    
    def add_ws_listener(self, callback: WSCallback) -> None:
        """Add a WebSocket-like event listener."""
        self._ws_listeners.append(callback)
    
    def remove_ws_listener(self, callback: WSCallback) -> None:
        """Remove a WebSocket listener."""
        self._ws_listeners.remove(callback)
    
    def set_book(self, symbol: str, book: OrderBook) -> None:
        """Set order book for a symbol."""
        self._books[symbol] = book
    
    def get_book(self, symbol: str) -> Optional[OrderBook]:
        """Get order book for a symbol."""
        return self._books.get(symbol)
    
    def set_reject_pattern(self, order_type: str, prob: float) -> None:
        """Configure rejection probability for an order type."""
        self._reject_patterns[order_type] = prob
    
    def clear_reject_patterns(self) -> None:
        """Clear all rejection patterns."""
        self._reject_patterns.clear()
    
    async def place_order(self, order: ManagedOrder) -> None:
        """
        Place an order on the simulated exchange.
        
        Args:
            order: Order to place
        """
        self._total_orders += 1
        
        # Generate exchange order ID
        exchange_order_id = f"SIM_{uuid.uuid4().hex[:12]}"
        
        # Create sim order
        sim_order = SimOrder(
            client_order_id=order.identity.client_order_id,
            exchange_order_id=exchange_order_id,
            symbol=order.symbol,
            side=order.side,
            size=order.qty,
            order_type=order.order_type,
            price=order.price,
            state=OrderState.SENT,
            reduce_only=order.reduce_only,
            created_at=self._clock.now_mono(),
        )
        
        self._orders[sim_order.client_order_id] = sim_order
        self._by_exchange_id[exchange_order_id] = sim_order.client_order_id
        
        # Schedule ack (with potential reject)
        ack_time = self._clock.now_mono() + (self._config.ack_latency_ms / 1000)
        
        # Check for rejection
        should_reject = self._should_reject(order)
        
        if should_reject:
            self._schedule_event(ack_time, "reject", {
                "client_order_id": sim_order.client_order_id,
                "exchange_order_id": exchange_order_id,
                "reason": "SIMULATED_REJECT",
            })
        else:
            self._schedule_event(ack_time, "ack", {
                "client_order_id": sim_order.client_order_id,
                "exchange_order_id": exchange_order_id,
            })
            
            # Schedule fill for market orders
            if order.order_type == "market":
                fill_time = ack_time + (self._config.fill_latency_ms / 1000)
                self._schedule_fill(sim_order, fill_time)
    
    async def cancel_order(
        self,
        client_order_id: Optional[str] = None,
        exchange_order_id: Optional[str] = None,
    ) -> bool:
        """
        Cancel an order.
        
        Args:
            client_order_id: Client order ID
            exchange_order_id: Exchange order ID
            
        Returns:
            True if cancel was accepted
        """
        # Find order
        coid = client_order_id
        if not coid and exchange_order_id:
            coid = self._by_exchange_id.get(exchange_order_id)
        
        if not coid or coid not in self._orders:
            return False
        
        order = self._orders[coid]
        
        # Can't cancel terminal orders
        if order.state in {OrderState.FILLED, OrderState.CANCELED, OrderState.REJECTED}:
            return False
        
        # Schedule cancel confirmation
        cancel_time = self._clock.now_mono() + (self._config.cancel_latency_ms / 1000)
        self._schedule_event(cancel_time, "canceled", {
            "client_order_id": coid,
            "exchange_order_id": order.exchange_order_id,
            "filled_size": order.filled_size,
        })
        
        return True
    
    async def cancel_all(self, symbol: Optional[str] = None) -> int:
        """
        Cancel all open orders.
        
        Args:
            symbol: Optional symbol filter
            
        Returns:
            Number of orders canceled
        """
        canceled = 0
        for coid, order in list(self._orders.items()):
            if symbol and order.symbol != symbol:
                continue
            if order.state not in {OrderState.FILLED, OrderState.CANCELED, OrderState.REJECTED}:
                await self.cancel_order(client_order_id=coid)
                canceled += 1
        return canceled
    
    async def process_pending(self) -> int:
        """
        Process all pending events up to current time.
        
        Call this after advancing the clock.
        
        Returns:
            Number of events processed
        """
        now = self._clock.now_mono()
        processed = 0
        
        # Sort by time
        self._pending_events.sort(key=lambda x: x[0])
        
        while self._pending_events and self._pending_events[0][0] <= now:
            _, event_type, data = self._pending_events.pop(0)
            await self._process_event(event_type, data)
            processed += 1
        
        return processed
    
    async def _process_event(self, event_type: str, data: Dict[str, Any]) -> None:
        """Process a single event."""
        if event_type == "ack":
            await self._handle_ack(data)
        elif event_type == "reject":
            await self._handle_reject(data)
        elif event_type == "fill":
            await self._handle_fill(data)
        elif event_type == "partial":
            await self._handle_partial(data)
        elif event_type == "canceled":
            await self._handle_canceled(data)
    
    async def _handle_ack(self, data: Dict[str, Any]) -> None:
        """Handle order acknowledgment."""
        coid = data["client_order_id"]
        order = self._orders.get(coid)
        if order:
            order.state = OrderState.ACKED
            await self._emit_ws({
                "type": "order_update",
                "client_order_id": coid,
                "exchange_order_id": data["exchange_order_id"],
                "status": "NEW",
            })
    
    async def _handle_reject(self, data: Dict[str, Any]) -> None:
        """Handle order rejection."""
        coid = data["client_order_id"]
        order = self._orders.get(coid)
        if order:
            order.state = OrderState.REJECTED
            self._total_rejects += 1
            await self._emit_ws({
                "type": "order_update",
                "client_order_id": coid,
                "exchange_order_id": data["exchange_order_id"],
                "status": "REJECTED",
                "reject_reason": data.get("reason", "UNKNOWN"),
            })
    
    async def _handle_fill(self, data: Dict[str, Any]) -> None:
        """Handle full fill."""
        coid = data["client_order_id"]
        order = self._orders.get(coid)
        if not order or order.state in {OrderState.FILLED, OrderState.CANCELED, OrderState.REJECTED}:
            return
        
        fill_price = data["fill_price"]
        fill_size = data["fill_size"]
        fees = fill_size * fill_price * self._config.fee_rate
        
        order.filled_size = fill_size
        order.avg_fill_price = fill_price
        order.fees = fees
        order.state = OrderState.FILLED
        self._total_fills += 1
        
        # Update position
        self._update_position(order, fill_size, fill_price)
        
        await self._emit_ws({
            "type": "order_update",
            "client_order_id": coid,
            "exchange_order_id": order.exchange_order_id,
            "status": "FILLED",
            "filled_qty": fill_size,
            "avg_price": fill_price,
            "fees": fees,
        })
    
    async def _handle_partial(self, data: Dict[str, Any]) -> None:
        """Handle partial fill."""
        coid = data["client_order_id"]
        order = self._orders.get(coid)
        if not order or order.state in {OrderState.FILLED, OrderState.CANCELED, OrderState.REJECTED}:
            return
        
        fill_price = data["fill_price"]
        fill_size = data["fill_size"]
        fees = fill_size * fill_price * self._config.fee_rate
        
        order.filled_size += fill_size
        order.avg_fill_price = fill_price  # Simplified - should be VWAP
        order.fees += fees
        order.state = OrderState.PARTIAL
        
        # Update position
        self._update_position(order, fill_size, fill_price)
        
        await self._emit_ws({
            "type": "order_update",
            "client_order_id": coid,
            "exchange_order_id": order.exchange_order_id,
            "status": "PARTIALLY_FILLED",
            "filled_qty": order.filled_size,
            "avg_price": fill_price,
            "fees": order.fees,
        })
    
    async def _handle_canceled(self, data: Dict[str, Any]) -> None:
        """Handle cancel confirmation."""
        coid = data["client_order_id"]
        order = self._orders.get(coid)
        if order and order.state not in {OrderState.FILLED, OrderState.REJECTED}:
            order.state = OrderState.CANCELED
            self._total_cancels += 1
            await self._emit_ws({
                "type": "order_update",
                "client_order_id": coid,
                "exchange_order_id": order.exchange_order_id,
                "status": "CANCELED" if order.filled_size == 0 else "PARTIALLY_FILLED_CANCELED",
                "filled_qty": order.filled_size,
            })
    
    def _should_reject(self, order: ManagedOrder) -> bool:
        """Determine if order should be rejected."""
        # Check order type pattern
        if order.order_type in self._reject_patterns:
            if self._rng.random() < self._reject_patterns[order.order_type]:
                return True
        
        # Check global reject probability
        if self._rng.random() < self._config.reject_prob:
            return True
        
        return False
    
    def _schedule_event(self, time: float, event_type: str, data: Dict[str, Any]) -> None:
        """Schedule an event for future processing."""
        self._pending_events.append((time, event_type, data))
    
    def _schedule_fill(self, order: SimOrder, fill_time: float) -> None:
        """Schedule fill event(s) for an order."""
        # Get fill price
        fill_price = self._get_fill_price(order)
        
        # Check for partial fill
        if self._rng.random() < self._config.partial_fill_prob:
            # Partial fill first
            partial_size = order.size * self._config.partial_fill_pct
            self._schedule_event(fill_time, "partial", {
                "client_order_id": order.client_order_id,
                "fill_price": fill_price,
                "fill_size": partial_size,
            })
            
            # Then complete fill
            complete_time = fill_time + (self._config.fill_latency_ms / 1000)
            self._schedule_event(complete_time, "fill", {
                "client_order_id": order.client_order_id,
                "fill_price": fill_price,
                "fill_size": order.size,
            })
        else:
            # Full fill
            self._schedule_event(fill_time, "fill", {
                "client_order_id": order.client_order_id,
                "fill_price": fill_price,
                "fill_size": order.size,
            })
    
    def _get_fill_price(self, order: SimOrder) -> float:
        """Get fill price for an order."""
        book = self._books.get(order.symbol)
        
        if order.price:
            # Limit order - fill at limit price
            base_price = order.price
        elif book:
            # Market order - fill at current market
            if order.side == "buy":
                base_price = book.best_ask_price or 100.0
            else:
                base_price = book.best_bid_price or 100.0
        else:
            base_price = 100.0
        
        # Apply slippage
        slippage_mult = 1 + (self._config.slippage_bps / 10000)
        if order.side == "buy":
            return base_price * slippage_mult
        else:
            return base_price / slippage_mult
    
    def _update_position(self, order: SimOrder, fill_size: float, fill_price: float) -> None:
        """Update position after fill."""
        pos = self._positions.get(order.symbol)
        
        if pos is None:
            # New position
            size = fill_size if order.side == "buy" else -fill_size
            self._positions[order.symbol] = SimPosition(
                symbol=order.symbol,
                size=size,
                entry_price=fill_price,
            )
        else:
            # Update existing position
            if order.side == "buy":
                pos.size += fill_size
            else:
                pos.size -= fill_size
            
            # Close position if size is zero
            if abs(pos.size) < 1e-10:
                del self._positions[order.symbol]
    
    async def _emit_ws(self, update: Dict[str, Any]) -> None:
        """Emit WebSocket-like update to listeners."""
        for listener in self._ws_listeners:
            await listener(update)
    
    def get_position(self, symbol: str) -> Optional[SimPosition]:
        """Get position for a symbol."""
        return self._positions.get(symbol)
    
    def get_all_positions(self) -> Dict[str, SimPosition]:
        """Get all positions."""
        return dict(self._positions)
    
    def get_order(self, client_order_id: str) -> Optional[SimOrder]:
        """Get order by client order ID."""
        return self._orders.get(client_order_id)
    
    def get_open_orders(self, symbol: Optional[str] = None) -> List[SimOrder]:
        """Get all open orders."""
        open_states = {OrderState.SENT, OrderState.ACKED, OrderState.PARTIAL}
        orders = [o for o in self._orders.values() if o.state in open_states]
        if symbol:
            orders = [o for o in orders if o.symbol == symbol]
        return orders
    
    def stats(self) -> Dict[str, Any]:
        """Get exchange statistics."""
        return {
            "total_orders": self._total_orders,
            "total_fills": self._total_fills,
            "total_rejects": self._total_rejects,
            "total_cancels": self._total_cancels,
            "open_orders": len(self.get_open_orders()),
            "positions": len(self._positions),
            "pending_events": len(self._pending_events),
        }
    
    def reset(self) -> None:
        """Reset exchange state."""
        self._orders.clear()
        self._by_exchange_id.clear()
        self._positions.clear()
        self._pending_events.clear()
        self._total_orders = 0
        self._total_fills = 0
        self._total_rejects = 0
        self._total_cancels = 0
