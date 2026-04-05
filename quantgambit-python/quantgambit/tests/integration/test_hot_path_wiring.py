"""
Integration tests for hot path wiring components.

Tests the individual components that make up the hot path wiring:
- LatencyTracker timer methods
- SimExchange basic operations
- ExecutionIntent creation
- Position handling

Note: Full hot path integration requires aligning all component interfaces.
These tests verify the wiring layer works correctly.
"""

import asyncio
import pytest
from typing import Dict, Any, List

from quantgambit.core.clock import SimClock
from quantgambit.core.book.types import OrderBook, Level
from quantgambit.core.decision import ExecutionIntent, Position
from quantgambit.core.latency import LatencyTracker
from quantgambit.core.lifecycle import ManagedOrder, OrderState
from quantgambit.core.ids import IntentIdentity
from quantgambit.sim.sim_exchange import SimExchange, SimExchangeConfig


def create_book(symbol: str, bid: float, ask: float, seq: int = 1) -> OrderBook:
    """Create a simple order book."""
    return OrderBook(
        symbol=symbol,
        bids=[Level(price=bid, size=10.0)],
        asks=[Level(price=ask, size=10.0)],
        update_id=seq,
        timestamp=0.0,
    )


def create_managed_order(
    symbol: str,
    side: str,
    size: float,
    order_type: str = "market",
    price: float = None,
) -> ManagedOrder:
    """Create a ManagedOrder for testing."""
    identity = IntentIdentity.create(
        strategy_id="test",
        symbol=symbol,
        side=side,
        qty=size,
        entry_type=order_type,
        entry_price=price,
        stop_loss=None,
        take_profit=None,
        risk_mode="normal",
        decision_ts_bucket=0,
    )
    
    return ManagedOrder(
        identity=identity,
        symbol=symbol,
        side=side,
        qty=size,
        order_type=order_type,
        price=price,
        state=OrderState.NEW,
    )


@pytest.fixture
def clock():
    """Create a SimClock."""
    return SimClock()


@pytest.fixture
def sim_exchange(clock):
    """Create a SimExchange."""
    config = SimExchangeConfig(
        ack_latency_ms=0.0,  # Immediate for testing
        fill_latency_ms=0.0,
        reject_prob=0.0,
    )
    sim = SimExchange(clock, config)
    
    # Set up initial book
    book = create_book("BTCUSDT", 50000.0, 50001.0)
    sim.set_book("BTCUSDT", book)
    
    return sim


@pytest.fixture
def latency_tracker(clock):
    """Create a LatencyTracker."""
    return LatencyTracker(clock)


class TestLatencyTracker:
    """Test LatencyTracker timer methods."""
    
    def test_start_end_timer(self, latency_tracker, clock):
        """Test start_timer and end_timer."""
        start = latency_tracker.start_timer("test_op")
        
        # Advance clock
        clock.advance(0.01)  # 10ms
        
        duration = latency_tracker.end_timer("test_op", start)
        
        assert duration >= 9.0  # At least 9ms (allowing for float precision)
        assert duration <= 11.0  # At most 11ms
    
    def test_record_latency(self, latency_tracker):
        """Test recording latency directly."""
        latency_tracker.record("test_op", 15.5)
        latency_tracker.record("test_op", 18.2)
        
        # Should have recorded samples
        assert "test_op" in latency_tracker._samples
        assert len(latency_tracker._samples["test_op"]) == 2
    
    def test_multiple_operations(self, latency_tracker, clock):
        """Test tracking multiple operations."""
        # Track two different operations
        start1 = latency_tracker.start_timer("op1")
        clock.advance(0.005)  # 5ms
        latency_tracker.end_timer("op1", start1)
        
        start2 = latency_tracker.start_timer("op2")
        clock.advance(0.015)  # 15ms
        latency_tracker.end_timer("op2", start2)
        
        assert "op1" in latency_tracker._samples
        assert "op2" in latency_tracker._samples


class TestSimExchangeBasics:
    """Test SimExchange basic operations."""
    
    @pytest.mark.asyncio
    async def test_place_market_order(self, sim_exchange, clock):
        """Test placing a market order."""
        updates = []
        
        async def on_update(update):
            updates.append(update)
        
        sim_exchange.add_ws_listener(on_update)
        
        order = create_managed_order("BTCUSDT", "buy", 0.1, "market")
        await sim_exchange.place_order(order)
        
        # Process pending events
        await sim_exchange.process_pending()
        
        # Should have received updates
        assert len(updates) >= 1
    
    @pytest.mark.asyncio
    async def test_position_after_fill(self, sim_exchange, clock):
        """Test position updates after fill."""
        order = create_managed_order("BTCUSDT", "buy", 0.1, "market")
        await sim_exchange.place_order(order)
        await sim_exchange.process_pending()
        
        pos = sim_exchange.get_position("BTCUSDT")
        assert pos is not None
        assert pos.size == 0.1
    
    @pytest.mark.asyncio
    async def test_multiple_orders(self, sim_exchange, clock):
        """Test multiple orders."""
        order1 = create_managed_order("BTCUSDT", "buy", 0.1, "market")
        await sim_exchange.place_order(order1)
        await sim_exchange.process_pending()
        
        order2 = create_managed_order("BTCUSDT", "buy", 0.05, "market")
        await sim_exchange.place_order(order2)
        await sim_exchange.process_pending()
        
        pos = sim_exchange.get_position("BTCUSDT")
        assert pos is not None
        assert abs(pos.size - 0.15) < 0.0001  # 0.1 + 0.05 (float tolerance)


class TestExecutionIntent:
    """Test ExecutionIntent creation."""
    
    def test_create_intent(self):
        """Test creating an ExecutionIntent."""
        intent = ExecutionIntent(
            intent_id="test_intent",
            client_order_id="test_order_123",
            symbol="BTCUSDT",
            side="buy",
            order_type="MARKET",
            qty=0.01,
        )
        
        assert intent.intent_id == "test_intent"
        assert intent.client_order_id == "test_order_123"
        assert intent.symbol == "BTCUSDT"
        assert intent.side == "buy"
        assert intent.qty == 0.01
    
    def test_intent_with_protective_orders(self):
        """Test intent with stop loss and take profit."""
        intent = ExecutionIntent(
            intent_id="test_intent",
            client_order_id="test_order_456",
            symbol="BTCUSDT",
            side="buy",
            order_type="MARKET",
            qty=0.01,
            sl_price=49000.0,
            tp_price=52000.0,
        )
        
        assert intent.sl_price == 49000.0
        assert intent.tp_price == 52000.0
    
    def test_intent_reduce_only(self):
        """Test reduce-only intent."""
        intent = ExecutionIntent(
            intent_id="exit_intent",
            client_order_id="exit_order",
            symbol="BTCUSDT",
            side="sell",
            order_type="MARKET",
            qty=0.01,
            reduce_only=True,
        )
        
        assert intent.reduce_only is True


class TestPosition:
    """Test Position dataclass."""
    
    def test_create_position(self):
        """Test creating a Position."""
        pos = Position(
            size=0.1,
            entry_price=50000.0,
            unrealized_pnl=100.0,
        )
        
        assert pos.size == 0.1
        assert pos.entry_price == 50000.0
        assert pos.unrealized_pnl == 100.0
    
    def test_short_position(self):
        """Test short position (negative size)."""
        pos = Position(
            size=-0.1,
            entry_price=50000.0,
            unrealized_pnl=-50.0,
        )
        
        assert pos.size == -0.1


class TestIntentIdentity:
    """Test IntentIdentity generation."""
    
    def test_create_identity(self):
        """Test creating an IntentIdentity."""
        identity = IntentIdentity.create(
            strategy_id="scalper",
            symbol="BTCUSDT",
            side="buy",
            qty=0.1,
            entry_type="market",
            entry_price=None,
            stop_loss=49000.0,
            take_profit=51000.0,
            risk_mode="normal",
            decision_ts_bucket=1000,
        )
        
        assert identity.intent_id.startswith("i_")
        assert identity.client_order_id.startswith("qg_")
        assert identity.attempt == 1
    
    def test_same_params_same_intent(self):
        """Test that same parameters produce same intent ID."""
        params = {
            "strategy_id": "scalper",
            "symbol": "BTCUSDT",
            "side": "buy",
            "qty": 0.1,
            "entry_type": "market",
            "entry_price": None,
            "stop_loss": 49000.0,
            "take_profit": 51000.0,
            "risk_mode": "normal",
            "decision_ts_bucket": 1000,
        }
        
        id1 = IntentIdentity.create(**params)
        id2 = IntentIdentity.create(**params)
        
        assert id1.intent_id == id2.intent_id
    
    def test_next_attempt(self):
        """Test incrementing attempt counter."""
        identity = IntentIdentity.create(
            strategy_id="scalper",
            symbol="BTCUSDT",
            side="buy",
            qty=0.1,
            entry_type="market",
            entry_price=None,
            stop_loss=None,
            take_profit=None,
            risk_mode="normal",
            decision_ts_bucket=1000,
        )
        
        next_id = identity.next_attempt()
        
        assert next_id.intent_id == identity.intent_id
        assert next_id.attempt == 2
        assert next_id.client_order_id != identity.client_order_id


class TestWebSocketCallbackPatterns:
    """Test patterns for WebSocket callback handling."""
    
    @pytest.mark.asyncio
    async def test_order_update_callback(self, sim_exchange):
        """Test order update callback pattern."""
        updates = []
        
        async def handle_update(update: Dict[str, Any]) -> None:
            updates.append(update)
        
        sim_exchange.add_ws_listener(handle_update)
        
        order = create_managed_order("BTCUSDT", "buy", 0.1, "market")
        await sim_exchange.place_order(order)
        await sim_exchange.process_pending()
        
        # Should have received updates
        assert len(updates) > 0
        
        # Check update structure
        order_updates = [u for u in updates if u.get("type") == "order_update"]
        assert len(order_updates) > 0
    
    @pytest.mark.asyncio
    async def test_position_update_callback(self, sim_exchange):
        """Test position update callback pattern."""
        updates = []
        
        async def handle_update(update: Dict[str, Any]) -> None:
            updates.append(update)
        
        sim_exchange.add_ws_listener(handle_update)
        
        order = create_managed_order("BTCUSDT", "buy", 0.1, "market")
        await sim_exchange.place_order(order)
        await sim_exchange.process_pending()
        
        # Should have updates (may be order_update or position_update depending on implementation)
        assert len(updates) > 0
        
        # Verify position was updated
        pos = sim_exchange.get_position("BTCUSDT")
        assert pos is not None
        assert pos.size == 0.1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
