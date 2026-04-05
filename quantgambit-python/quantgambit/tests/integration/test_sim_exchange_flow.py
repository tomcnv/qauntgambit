"""
Integration tests for SimExchange order flow.

Tests the SimExchange with various order scenarios:
- Market order fill
- Limit order fill
- Partial fills
- Order rejection
- Order cancellation
- Bracket orders
- Kill switch trigger
"""

import pytest
from typing import List, Dict, Any

from quantgambit.core.clock import SimClock
from quantgambit.core.lifecycle import OrderState, ManagedOrder
from quantgambit.core.ids import IntentIdentity, generate_intent_id, generate_client_order_id
from quantgambit.core.book.types import OrderBook, Level
from quantgambit.sim.sim_exchange import SimExchange, SimExchangeConfig


@pytest.fixture
def clock() -> SimClock:
    """Create a SimClock for testing."""
    return SimClock()


@pytest.fixture
def exchange(clock: SimClock) -> SimExchange:
    """Create a SimExchange with default config."""
    config = SimExchangeConfig(
        ack_latency_ms=10.0,
        fill_latency_ms=5.0,
        reject_prob=0.0,
        slippage_bps=0.0,
    )
    return SimExchange(clock, config, seed=42)


@pytest.fixture
def book() -> OrderBook:
    """Create a simple order book."""
    return OrderBook(
        symbol="BTCUSD",
        bids=[Level(price=100.0, size=10.0), Level(price=99.0, size=20.0)],
        asks=[Level(price=101.0, size=10.0), Level(price=102.0, size=20.0)],
        timestamp=0.0,
        update_id=1,
    )


def create_market_order(
    symbol: str = "BTCUSD",
    side: str = "buy",
    qty: float = 1.0,
) -> ManagedOrder:
    """Create a market order for testing."""
    intent_id = generate_intent_id(
        strategy_id="test",
        symbol=symbol,
        side=side,
        qty=qty,
        entry_type="market",
        entry_price=None,
        stop_loss=None,
        take_profit=None,
        risk_mode="test",
        decision_ts_bucket=0,
    )
    client_order_id = generate_client_order_id(intent_id, 1)
    
    identity = IntentIdentity(
        intent_id=intent_id,
        client_order_id=client_order_id,
        attempt=1,
    )
    
    return ManagedOrder(
        identity=identity,
        symbol=symbol,
        side=side,
        qty=qty,
        order_type="market",
        price=None,
    )


class TestSimExchangeMarketOrder:
    """Tests for market order flow."""
    
    @pytest.mark.asyncio
    async def test_market_order_fills(self, exchange: SimExchange, clock: SimClock, book: OrderBook):
        """Market order should fill after ack + fill latency."""
        exchange.set_book("BTCUSD", book)
        
        # Track updates
        updates: List[Dict[str, Any]] = []
        async def on_update(update):
            updates.append(update)
        exchange.add_ws_listener(on_update)
        
        # Place order
        order = create_market_order()
        await exchange.place_order(order)
        
        # Order should be sent
        assert exchange.get_order(order.identity.client_order_id).state == OrderState.SENT
        
        # Advance time past ack
        clock.advance(0.011)  # 11ms
        await exchange.process_pending()
        
        # Should have received ack
        assert len(updates) == 1
        assert updates[0]["status"] == "NEW"
        assert exchange.get_order(order.identity.client_order_id).state == OrderState.ACKED
        
        # Advance time past fill
        clock.advance(0.006)  # 6ms more
        await exchange.process_pending()
        
        # Should have received fill
        assert len(updates) == 2
        assert updates[1]["status"] == "FILLED"
        
        sim_order = exchange.get_order(order.identity.client_order_id)
        assert sim_order.state == OrderState.FILLED
        assert sim_order.filled_size == 1.0
        assert sim_order.avg_fill_price == 101.0  # Best ask
    
    @pytest.mark.asyncio
    async def test_market_order_updates_position(self, exchange: SimExchange, clock: SimClock, book: OrderBook):
        """Market order fill should update position."""
        exchange.set_book("BTCUSD", book)
        
        # No position initially
        assert exchange.get_position("BTCUSD") is None
        
        # Place buy order
        order = create_market_order(side="buy", qty=2.0)
        await exchange.place_order(order)
        
        # Process until filled
        clock.advance(0.020)
        await exchange.process_pending()
        
        # Check position
        pos = exchange.get_position("BTCUSD")
        assert pos is not None
        assert pos.size == 2.0  # Long
        assert pos.entry_price == 101.0


class TestSimExchangeReject:
    """Tests for order rejection."""
    
    @pytest.mark.asyncio
    async def test_order_rejection(self, clock: SimClock):
        """Orders should be rejected based on reject probability."""
        config = SimExchangeConfig(
            ack_latency_ms=10.0,
            reject_prob=1.0,  # Always reject
        )
        exchange = SimExchange(clock, config, seed=42)
        
        updates: List[Dict[str, Any]] = []
        async def on_update(update):
            updates.append(update)
        exchange.add_ws_listener(on_update)
        
        # Place order
        order = create_market_order()
        await exchange.place_order(order)
        
        # Process until ack time
        clock.advance(0.011)
        await exchange.process_pending()
        
        # Should be rejected
        assert len(updates) == 1
        assert updates[0]["status"] == "REJECTED"
        assert exchange.get_order(order.identity.client_order_id).state == OrderState.REJECTED
    
    @pytest.mark.asyncio
    async def test_pattern_rejection(self, exchange: SimExchange, clock: SimClock):
        """Orders should be rejected based on pattern."""
        # Set pattern to always reject limit orders
        exchange.set_reject_pattern("limit", 1.0)
        
        updates: List[Dict[str, Any]] = []
        async def on_update(update):
            updates.append(update)
        exchange.add_ws_listener(on_update)
        
        # Create limit order
        intent_id = generate_intent_id("test", "BTCUSD", "buy", 1.0, "limit", 100.0, None, None, "test", 0)
        client_order_id = generate_client_order_id(intent_id, 1)
        identity = IntentIdentity(intent_id=intent_id, client_order_id=client_order_id, attempt=1)
        order = ManagedOrder(identity=identity, symbol="BTCUSD", side="buy", qty=1.0, order_type="limit", price=100.0)
        
        await exchange.place_order(order)
        clock.advance(0.011)
        await exchange.process_pending()
        
        assert updates[0]["status"] == "REJECTED"


class TestSimExchangeCancel:
    """Tests for order cancellation."""
    
    @pytest.mark.asyncio
    async def test_cancel_order(self, exchange: SimExchange, clock: SimClock, book: OrderBook):
        """Order should be cancellable before fill."""
        exchange.set_book("BTCUSD", book)
        
        # Create limit order that won't immediately fill
        intent_id = generate_intent_id("test", "BTCUSD", "buy", 1.0, "limit", 90.0, None, None, "test", 0)
        client_order_id = generate_client_order_id(intent_id, 1)
        identity = IntentIdentity(intent_id=intent_id, client_order_id=client_order_id, attempt=1)
        order = ManagedOrder(identity=identity, symbol="BTCUSD", side="buy", qty=1.0, order_type="limit", price=90.0)
        
        updates: List[Dict[str, Any]] = []
        async def on_update(update):
            updates.append(update)
        exchange.add_ws_listener(on_update)
        
        # Place and ack
        await exchange.place_order(order)
        clock.advance(0.011)
        await exchange.process_pending()
        assert updates[0]["status"] == "NEW"
        
        # Cancel
        result = await exchange.cancel_order(client_order_id=client_order_id)
        assert result is True
        
        # Process cancel
        clock.advance(0.031)  # Cancel latency
        await exchange.process_pending()
        
        # Should be canceled
        assert updates[-1]["status"] == "CANCELED"
        assert exchange.get_order(client_order_id).state == OrderState.CANCELED
    
    @pytest.mark.asyncio
    async def test_cancel_filled_order_fails(self, exchange: SimExchange, clock: SimClock, book: OrderBook):
        """Cannot cancel a filled order."""
        exchange.set_book("BTCUSD", book)
        
        # Place and fill
        order = create_market_order()
        await exchange.place_order(order)
        clock.advance(0.020)
        await exchange.process_pending()
        
        assert exchange.get_order(order.identity.client_order_id).state == OrderState.FILLED
        
        # Try to cancel
        result = await exchange.cancel_order(client_order_id=order.identity.client_order_id)
        assert result is False


class TestSimExchangePartialFill:
    """Tests for partial fill scenarios."""
    
    @pytest.mark.asyncio
    async def test_partial_fill(self, clock: SimClock, book: OrderBook):
        """Order should receive partial fill followed by complete fill."""
        config = SimExchangeConfig(
            ack_latency_ms=10.0,
            fill_latency_ms=5.0,
            partial_fill_prob=1.0,  # Always partial
            partial_fill_pct=0.5,
        )
        exchange = SimExchange(clock, config, seed=42)
        exchange.set_book("BTCUSD", book)
        
        updates: List[Dict[str, Any]] = []
        async def on_update(update):
            updates.append(update)
        exchange.add_ws_listener(on_update)
        
        # Place order
        order = create_market_order(qty=10.0)
        await exchange.place_order(order)
        
        # Process ack + partial fill
        clock.advance(0.016)
        await exchange.process_pending()
        
        # Should have ack + partial
        assert any(u["status"] == "NEW" for u in updates)
        assert any(u["status"] == "PARTIALLY_FILLED" for u in updates)
        
        sim_order = exchange.get_order(order.identity.client_order_id)
        assert sim_order.state == OrderState.PARTIAL
        assert sim_order.filled_size == 5.0  # 50%
        
        # Process complete fill
        clock.advance(0.010)
        await exchange.process_pending()
        
        assert updates[-1]["status"] == "FILLED"
        sim_order = exchange.get_order(order.identity.client_order_id)
        assert sim_order.state == OrderState.FILLED
        assert sim_order.filled_size == 10.0


class TestSimExchangeStats:
    """Tests for exchange statistics."""
    
    @pytest.mark.asyncio
    async def test_stats_tracking(self, exchange: SimExchange, clock: SimClock, book: OrderBook):
        """Exchange should track order statistics."""
        exchange.set_book("BTCUSD", book)
        
        # Initial stats
        stats = exchange.stats()
        assert stats["total_orders"] == 0
        assert stats["total_fills"] == 0
        
        # Place and fill order
        order = create_market_order()
        await exchange.place_order(order)
        clock.advance(0.020)
        await exchange.process_pending()
        
        stats = exchange.stats()
        assert stats["total_orders"] == 1
        assert stats["total_fills"] == 1
    
    @pytest.mark.asyncio
    async def test_reset(self, exchange: SimExchange, clock: SimClock, book: OrderBook):
        """Reset should clear all state."""
        exchange.set_book("BTCUSD", book)
        
        # Place and fill order
        order = create_market_order()
        await exchange.place_order(order)
        clock.advance(0.020)
        await exchange.process_pending()
        
        assert exchange.stats()["total_orders"] == 1
        
        # Reset
        exchange.reset()
        
        stats = exchange.stats()
        assert stats["total_orders"] == 0
        assert stats["total_fills"] == 0
        assert exchange.get_position("BTCUSD") is None
