"""
Scenario builders for integration tests.

Pre-built scenarios for testing common execution flows:
- Bracket order success (entry + SL + TP)
- Bracket with TP rejection
- Partial fills
- WebSocket disconnect
- Kill-switch triggers
"""

from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List, Callable, Awaitable

from quantgambit.core.clock import SimClock
from quantgambit.core.book.types import OrderBook, Level
from quantgambit.core.lifecycle import ManagedOrder, OrderState
from quantgambit.core.ids import IntentIdentity
from quantgambit.sim.sim_exchange import SimExchange, SimExchangeConfig


@dataclass
class ScenarioResult:
    """Result of running a scenario."""
    
    success: bool
    orders: List[ManagedOrder]
    events: List[Dict[str, Any]]
    final_position_size: float
    final_pnl: float
    error: Optional[str] = None


class ScenarioBuilder:
    """
    Builder for test scenarios.
    
    Usage:
        scenario = (
            ScenarioBuilder(clock)
            .with_symbol("BTCUSDT")
            .with_book(bid=40000, ask=40010)
            .with_entry(side="buy", size=0.1)
            .with_stop_loss(39000)
            .with_take_profit(42000)
            .build()
        )
        
        result = await scenario.run()
    """
    
    def __init__(self, clock: SimClock, seed: int = 42):
        """
        Initialize scenario builder.
        
        Args:
            clock: SimClock for deterministic time
            seed: Random seed for reproducibility
        """
        self._clock = clock
        self._seed = seed
        
        # Scenario parameters
        self._symbol = "BTCUSDT"
        self._book: Optional[OrderBook] = None
        self._entry_side: Optional[str] = None
        self._entry_size: float = 0.1
        self._entry_type: str = "market"
        self._entry_price: Optional[float] = None
        self._stop_loss: Optional[float] = None
        self._take_profit: Optional[float] = None
        
        # Exchange config overrides
        self._exchange_config = SimExchangeConfig()
        
        # Rejection patterns
        self._reject_patterns: Dict[str, float] = {}
        
        # Events to inject
        self._injected_events: List[tuple[float, str, Dict[str, Any]]] = []
    
    def with_symbol(self, symbol: str) -> "ScenarioBuilder":
        """Set trading symbol."""
        self._symbol = symbol
        return self
    
    def with_book(
        self,
        bid: float,
        ask: float,
        bid_size: float = 10.0,
        ask_size: float = 10.0,
    ) -> "ScenarioBuilder":
        """Set order book."""
        self._book = OrderBook(
            symbol=self._symbol,
            bids=[Level(price=bid, size=bid_size)],
            asks=[Level(price=ask, size=ask_size)],
            update_id=1,
            timestamp=self._clock.now_wall(),
        )
        return self
    
    def with_entry(
        self,
        side: str,
        size: float,
        order_type: str = "market",
        price: Optional[float] = None,
    ) -> "ScenarioBuilder":
        """Set entry order parameters."""
        self._entry_side = side
        self._entry_size = size
        self._entry_type = order_type
        self._entry_price = price
        return self
    
    def with_stop_loss(self, price: float) -> "ScenarioBuilder":
        """Set stop loss price."""
        self._stop_loss = price
        return self
    
    def with_take_profit(self, price: float) -> "ScenarioBuilder":
        """Set take profit price."""
        self._take_profit = price
        return self
    
    def with_latency(
        self,
        ack_ms: float = 50.0,
        fill_ms: float = 10.0,
        cancel_ms: float = 30.0,
    ) -> "ScenarioBuilder":
        """Set exchange latencies."""
        self._exchange_config.ack_latency_ms = ack_ms
        self._exchange_config.fill_latency_ms = fill_ms
        self._exchange_config.cancel_latency_ms = cancel_ms
        return self
    
    def with_reject_pattern(self, order_type: str, prob: float) -> "ScenarioBuilder":
        """Configure rejection for an order type."""
        self._reject_patterns[order_type] = prob
        return self
    
    def with_partial_fills(self, prob: float = 0.5, pct: float = 0.5) -> "ScenarioBuilder":
        """Enable partial fills."""
        self._exchange_config.partial_fill_prob = prob
        self._exchange_config.partial_fill_pct = pct
        return self
    
    def with_slippage(self, bps: float) -> "ScenarioBuilder":
        """Set slippage in basis points."""
        self._exchange_config.slippage_bps = bps
        return self
    
    def build(self) -> "Scenario":
        """Build the scenario."""
        return Scenario(
            clock=self._clock,
            seed=self._seed,
            symbol=self._symbol,
            book=self._book,
            entry_side=self._entry_side,
            entry_size=self._entry_size,
            entry_type=self._entry_type,
            entry_price=self._entry_price,
            stop_loss=self._stop_loss,
            take_profit=self._take_profit,
            exchange_config=self._exchange_config,
            reject_patterns=self._reject_patterns,
        )


@dataclass
class Scenario:
    """
    Executable test scenario.
    
    Created by ScenarioBuilder.
    """
    
    clock: SimClock
    seed: int
    symbol: str
    book: Optional[OrderBook]
    entry_side: Optional[str]
    entry_size: float
    entry_type: str
    entry_price: Optional[float]
    stop_loss: Optional[float]
    take_profit: Optional[float]
    exchange_config: SimExchangeConfig
    reject_patterns: Dict[str, float]
    
    async def run(self) -> ScenarioResult:
        """
        Run the scenario.
        
        Returns:
            ScenarioResult with outcomes
        """
        # Create exchange
        exchange = SimExchange(self.clock, self.exchange_config, self.seed)
        
        # Set up book
        if self.book:
            exchange.set_book(self.symbol, self.book)
        
        # Set up reject patterns
        for order_type, prob in self.reject_patterns.items():
            exchange.set_reject_pattern(order_type, prob)
        
        # Collect events
        events: List[Dict[str, Any]] = []
        
        async def collect_events(event: Dict[str, Any]) -> None:
            events.append(event)
        
        exchange.add_ws_listener(collect_events)
        
        # Create and place entry order
        orders: List[ManagedOrder] = []
        
        if self.entry_side:
            entry_identity = IntentIdentity.create(
                strategy_id="test",
                symbol=self.symbol,
                side=self.entry_side,
                qty=self.entry_size,
                entry_type=self.entry_type,
                entry_price=self.entry_price,
                stop_loss=self.stop_loss,
                take_profit=self.take_profit,
                risk_mode="test",
                decision_ts_bucket=int(self.clock.now_wall() * 1000),
            )
            
            entry_order = ManagedOrder(
                identity=entry_identity,
                symbol=self.symbol,
                side=self.entry_side,
                qty=self.entry_size,
                order_type=self.entry_type,
                price=self.entry_price,
            )
            orders.append(entry_order)
            
            await exchange.place_order(entry_order)
        
        # Advance time and process events
        self.clock.advance(0.2)  # 200ms
        await exchange.process_pending()
        
        # Get final state
        position = exchange.get_position(self.symbol)
        final_size = position.size if position else 0.0
        final_pnl = position.unrealized_pnl if position else 0.0
        
        # Determine success
        success = True
        error = None
        
        # Check if entry filled
        if self.entry_side:
            entry_events = [e for e in events if e.get("status") == "FILLED"]
            if not entry_events:
                reject_events = [e for e in events if e.get("status") == "REJECTED"]
                if reject_events:
                    success = False
                    error = f"Entry rejected: {reject_events[0].get('reject_reason')}"
        
        return ScenarioResult(
            success=success,
            orders=orders,
            events=events,
            final_position_size=final_size,
            final_pnl=final_pnl,
            error=error,
        )


# =============================================================================
# Pre-built scenarios
# =============================================================================

def bracket_success_scenario(clock: SimClock) -> Scenario:
    """
    Scenario: Entry fills, then TP triggers.
    
    Expected outcome:
    - Entry order fills
    - Position opened
    - (TP would trigger if price moves - not simulated here)
    """
    return (
        ScenarioBuilder(clock)
        .with_symbol("BTCUSDT")
        .with_book(bid=40000, ask=40010)
        .with_entry(side="buy", size=0.1)
        .with_stop_loss(39000)
        .with_take_profit(42000)
        .build()
    )


def bracket_tp_reject_scenario(clock: SimClock) -> Scenario:
    """
    Scenario: Entry fills, but TP order is rejected.
    
    Expected outcome:
    - Entry order fills
    - TP order rejected
    - Should trigger flatten (in real system)
    """
    return (
        ScenarioBuilder(clock)
        .with_symbol("BTCUSDT")
        .with_book(bid=40000, ask=40010)
        .with_entry(side="buy", size=0.1)
        .with_stop_loss(39000)
        .with_take_profit(42000)
        .with_reject_pattern("take_profit", 1.0)  # Always reject TP
        .build()
    )


def partial_fill_scenario(clock: SimClock) -> Scenario:
    """
    Scenario: Order partially fills, then completes.
    
    Expected outcome:
    - Partial fill event
    - Full fill event
    - Position opened with full size
    """
    return (
        ScenarioBuilder(clock)
        .with_symbol("BTCUSDT")
        .with_book(bid=40000, ask=40010)
        .with_entry(side="buy", size=0.1)
        .with_partial_fills(prob=1.0, pct=0.5)  # Always partial
        .build()
    )


def ws_disconnect_scenario(clock: SimClock) -> Scenario:
    """
    Scenario: WebSocket disconnects during order.
    
    This scenario is for testing kill-switch behavior.
    The actual disconnect logic is handled by the test.
    """
    return (
        ScenarioBuilder(clock)
        .with_symbol("BTCUSDT")
        .with_book(bid=40000, ask=40010)
        .with_entry(side="buy", size=0.1)
        .with_latency(ack_ms=100, fill_ms=50)  # Slower to allow disconnect
        .build()
    )


def high_slippage_scenario(clock: SimClock) -> Scenario:
    """
    Scenario: Order fills with high slippage.
    
    Expected outcome:
    - Order fills
    - Fill price worse than expected
    - Should trigger slippage alert (in real system)
    """
    return (
        ScenarioBuilder(clock)
        .with_symbol("BTCUSDT")
        .with_book(bid=40000, ask=40010)
        .with_entry(side="buy", size=0.1)
        .with_slippage(bps=100)  # 1% slippage
        .build()
    )


def reject_scenario(clock: SimClock) -> Scenario:
    """
    Scenario: Order is rejected.
    
    Expected outcome:
    - Order rejected
    - No position opened
    """
    return (
        ScenarioBuilder(clock)
        .with_symbol("BTCUSDT")
        .with_book(bid=40000, ask=40010)
        .with_entry(side="buy", size=0.1)
        .with_reject_pattern("market", 1.0)  # Always reject
        .build()
    )
