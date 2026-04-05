"""
Integration tests for ReconciliationWorker.

Tests:
- Ghost order detection and healing
- Orphan order detection and healing
- Position drift detection and healing
- Periodic reconciliation
"""

import pytest
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field

from quantgambit.core.clock import SimClock
from quantgambit.core.lifecycle import ManagedOrder, OrderState
from quantgambit.core.ids import IntentIdentity, generate_intent_id, generate_client_order_id
from quantgambit.execution.reconciliation import (
    ReconciliationWorker,
    DiscrepancyType,
    OrderStore,
    PositionStore,
    ExchangeClient,
)


# Mock implementations for testing


@dataclass
class MockOrderStore:
    """Mock order store for testing."""
    
    orders: Dict[str, ManagedOrder] = field(default_factory=dict)
    
    def get_open_orders(self, symbol: Optional[str] = None) -> List[ManagedOrder]:
        orders = [o for o in self.orders.values() if o.is_live()]
        if symbol:
            orders = [o for o in orders if o.symbol == symbol]
        return orders
    
    def get_order(self, client_order_id: str) -> Optional[ManagedOrder]:
        return self.orders.get(client_order_id)
    
    def update_order(self, order: ManagedOrder) -> None:
        self.orders[order.identity.client_order_id] = order
    
    def remove_order(self, client_order_id: str) -> None:
        self.orders.pop(client_order_id, None)
    
    def add_order(self, order: ManagedOrder) -> None:
        self.orders[order.identity.client_order_id] = order


@dataclass
class MockPositionStore:
    """Mock position store for testing."""
    
    positions: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    
    def get_position(self, symbol: str) -> Optional[Dict[str, Any]]:
        return self.positions.get(symbol)
    
    def get_all_positions(self) -> Dict[str, Dict[str, Any]]:
        return dict(self.positions)
    
    def update_position(self, symbol: str, size: float, entry_price: float) -> None:
        self.positions[symbol] = {"size": size, "entry_price": entry_price}
    
    def clear_position(self, symbol: str) -> None:
        self.positions.pop(symbol, None)


@dataclass
class MockExchangeClient:
    """Mock exchange client for testing."""
    
    exchange_orders: List[Dict[str, Any]] = field(default_factory=list)
    exchange_positions: List[Dict[str, Any]] = field(default_factory=list)
    cancel_calls: List[tuple] = field(default_factory=list)
    
    async def get_open_orders(self, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        orders = self.exchange_orders
        if symbol:
            orders = [o for o in orders if o.get("symbol") == symbol]
        return orders
    
    async def get_positions(self) -> List[Dict[str, Any]]:
        return self.exchange_positions
    
    async def cancel_order(self, symbol: str, order_id: str) -> bool:
        self.cancel_calls.append((symbol, order_id))
        return True


def create_test_order(
    symbol: str = "BTCUSD",
    side: str = "buy",
    qty: float = 1.0,
    state: OrderState = OrderState.ACKED,
) -> ManagedOrder:
    """Create a test order."""
    intent_id = generate_intent_id("test", symbol, side, qty, "market", None, None, None, "test", 0)
    client_order_id = generate_client_order_id(intent_id, 1)
    identity = IntentIdentity(intent_id=intent_id, client_order_id=client_order_id, attempt=1)
    
    order = ManagedOrder(
        identity=identity,
        symbol=symbol,
        side=side,
        qty=qty,
        order_type="market",
    )
    order.state = state
    return order


@pytest.fixture
def clock() -> SimClock:
    return SimClock()


@pytest.fixture
def order_store() -> MockOrderStore:
    return MockOrderStore()


@pytest.fixture
def position_store() -> MockPositionStore:
    return MockPositionStore()


@pytest.fixture
def exchange_client() -> MockExchangeClient:
    return MockExchangeClient()


@pytest.fixture
def worker(clock, order_store, position_store, exchange_client) -> ReconciliationWorker:
    return ReconciliationWorker(
        clock=clock,
        order_store=order_store,
        position_store=position_store,
        exchange_client=exchange_client,
        interval_sec=30.0,
        enable_auto_healing=True,
    )


class TestGhostOrderDetection:
    """Tests for ghost order detection (local has it, exchange doesn't)."""
    
    @pytest.mark.asyncio
    async def test_detects_ghost_order(self, worker, order_store, exchange_client):
        """Should detect when local has order that exchange doesn't."""
        # Add order to local store
        order = create_test_order()
        order_store.add_order(order)
        
        # Exchange has no orders
        exchange_client.exchange_orders = []
        
        # Run reconciliation
        result = await worker.reconcile()
        
        # Should detect ghost order
        assert result.has_discrepancies
        assert len(result.discrepancies) == 1
        assert result.discrepancies[0].type == DiscrepancyType.GHOST_ORDER
    
    @pytest.mark.asyncio
    async def test_heals_ghost_order(self, worker, order_store, exchange_client):
        """Should mark ghost order as canceled."""
        order = create_test_order()
        order_store.add_order(order)
        exchange_client.exchange_orders = []
        
        result = await worker.reconcile()
        
        # Order should be marked as canceled
        healed_order = order_store.get_order(order.identity.client_order_id)
        assert healed_order.state == OrderState.CANCELED
        assert result.healing_actions_taken == 1


class TestOrphanOrderDetection:
    """Tests for orphan order detection (exchange has it, local doesn't)."""
    
    @pytest.mark.asyncio
    async def test_detects_orphan_order(self, worker, order_store, exchange_client):
        """Should detect when exchange has order that local doesn't."""
        # Local has no orders
        
        # Exchange has an order
        exchange_client.exchange_orders = [
            {
                "clientOrderId": "orphan_123",
                "orderId": "exch_456",
                "symbol": "BTCUSD",
                "status": "NEW",
                "qty": 1.0,
            }
        ]
        
        result = await worker.reconcile()
        
        assert result.has_discrepancies
        assert len(result.discrepancies) == 1
        assert result.discrepancies[0].type == DiscrepancyType.ORPHAN_ORDER
    
    @pytest.mark.asyncio
    async def test_heals_orphan_order_by_canceling(self, worker, order_store, exchange_client):
        """Should cancel orphan order on exchange."""
        exchange_client.exchange_orders = [
            {
                "clientOrderId": "orphan_123",
                "orderId": "exch_456",
                "symbol": "BTCUSD",
                "status": "NEW",
                "qty": 1.0,
            }
        ]
        
        result = await worker.reconcile()
        
        # Should have called cancel
        assert len(exchange_client.cancel_calls) == 1
        assert exchange_client.cancel_calls[0] == ("BTCUSD", "exch_456")
        assert result.healing_actions_taken == 1


class TestGhostPositionDetection:
    """Tests for ghost position detection."""
    
    @pytest.mark.asyncio
    async def test_detects_ghost_position(self, worker, position_store, exchange_client):
        """Should detect when local has position that exchange doesn't."""
        # Add position to local
        position_store.update_position("BTCUSD", 1.0, 100.0)
        
        # Exchange has no positions
        exchange_client.exchange_positions = []
        
        result = await worker.reconcile()
        
        assert result.has_discrepancies
        ghost_disc = [d for d in result.discrepancies if d.type == DiscrepancyType.GHOST_POSITION]
        assert len(ghost_disc) == 1
    
    @pytest.mark.asyncio
    async def test_heals_ghost_position(self, worker, position_store, exchange_client):
        """Should clear ghost position locally."""
        position_store.update_position("BTCUSD", 1.0, 100.0)
        exchange_client.exchange_positions = []
        
        result = await worker.reconcile()
        
        # Position should be cleared
        assert position_store.get_position("BTCUSD") is None
        assert result.healing_actions_taken >= 1


class TestOrphanPositionDetection:
    """Tests for orphan position detection."""
    
    @pytest.mark.asyncio
    async def test_detects_orphan_position(self, worker, position_store, exchange_client):
        """Should detect when exchange has position that local doesn't."""
        # Local has no positions
        
        # Exchange has a position
        exchange_client.exchange_positions = [
            {"symbol": "BTCUSD", "size": 2.0, "avgPrice": 100.0}
        ]
        
        result = await worker.reconcile()
        
        assert result.has_discrepancies
        orphan_disc = [d for d in result.discrepancies if d.type == DiscrepancyType.ORPHAN_POSITION]
        assert len(orphan_disc) == 1
    
    @pytest.mark.asyncio
    async def test_heals_orphan_position(self, worker, position_store, exchange_client):
        """Should sync orphan position to local."""
        exchange_client.exchange_positions = [
            {"symbol": "BTCUSD", "size": 2.0, "avgPrice": 100.0}
        ]
        
        result = await worker.reconcile()
        
        # Position should be synced
        pos = position_store.get_position("BTCUSD")
        assert pos is not None
        assert pos["size"] == 2.0
        assert result.healing_actions_taken >= 1


class TestPositionSizeMismatch:
    """Tests for position size mismatch detection."""
    
    @pytest.mark.asyncio
    async def test_detects_size_mismatch(self, worker, position_store, exchange_client):
        """Should detect when position sizes differ."""
        # Local has 1.0
        position_store.update_position("BTCUSD", 1.0, 100.0)
        
        # Exchange has 2.0
        exchange_client.exchange_positions = [
            {"symbol": "BTCUSD", "size": 2.0, "avgPrice": 100.0}
        ]
        
        result = await worker.reconcile()
        
        assert result.has_discrepancies
        mismatch_disc = [d for d in result.discrepancies if d.type == DiscrepancyType.POSITION_SIZE_MISMATCH]
        assert len(mismatch_disc) == 1
    
    @pytest.mark.asyncio
    async def test_heals_size_mismatch_trusts_exchange(self, worker, position_store, exchange_client):
        """Should update local to match exchange."""
        position_store.update_position("BTCUSD", 1.0, 100.0)
        exchange_client.exchange_positions = [
            {"symbol": "BTCUSD", "size": 2.0, "avgPrice": 100.0}
        ]
        
        result = await worker.reconcile()
        
        # Local should match exchange
        pos = position_store.get_position("BTCUSD")
        assert pos["size"] == 2.0


class TestFilledQtyMismatch:
    """Tests for order filled quantity mismatch."""
    
    @pytest.mark.asyncio
    async def test_detects_filled_qty_mismatch(self, worker, order_store, exchange_client):
        """Should detect when filled quantities differ."""
        # Create order with local filled_qty = 0.5
        order = create_test_order()
        order.filled_qty = 0.5
        order_store.add_order(order)
        
        # Exchange shows filled_qty = 1.0
        exchange_client.exchange_orders = [
            {
                "clientOrderId": order.identity.client_order_id,
                "orderId": "exch_123",
                "symbol": "BTCUSD",
                "status": "PARTIALLY_FILLED",
                "cumExecQty": 1.0,
            }
        ]
        
        result = await worker.reconcile()
        
        assert result.has_discrepancies
        mismatch_disc = [d for d in result.discrepancies if d.type == DiscrepancyType.ORDER_FILLED_QTY_MISMATCH]
        assert len(mismatch_disc) == 1
    
    @pytest.mark.asyncio
    async def test_heals_filled_qty_mismatch(self, worker, order_store, exchange_client):
        """Should update local filled_qty to match exchange."""
        order = create_test_order()
        order.filled_qty = 0.5
        order_store.add_order(order)
        
        exchange_client.exchange_orders = [
            {
                "clientOrderId": order.identity.client_order_id,
                "orderId": "exch_123",
                "symbol": "BTCUSD",
                "status": "PARTIALLY_FILLED",
                "cumExecQty": 1.0,
            }
        ]
        
        result = await worker.reconcile()
        
        # Local should match exchange
        updated_order = order_store.get_order(order.identity.client_order_id)
        assert updated_order.filled_qty == 1.0


class TestNoDiscrepancies:
    """Tests for when everything is in sync."""
    
    @pytest.mark.asyncio
    async def test_no_discrepancies_when_synced(self, worker, order_store, position_store, exchange_client):
        """Should report no discrepancies when synced."""
        # Add matching order
        order = create_test_order()
        order_store.add_order(order)
        exchange_client.exchange_orders = [
            {
                "clientOrderId": order.identity.client_order_id,
                "orderId": "exch_123",
                "symbol": "BTCUSD",
                "status": "NEW",
                "cumExecQty": 0.0,
            }
        ]
        
        # Add matching position
        position_store.update_position("BTCUSD", 1.0, 100.0)
        exchange_client.exchange_positions = [
            {"symbol": "BTCUSD", "size": 1.0, "avgPrice": 100.0}
        ]
        
        result = await worker.reconcile()
        
        assert not result.has_discrepancies
        assert result.healing_actions_taken == 0


class TestAutoHealingDisabled:
    """Tests for when auto-healing is disabled."""
    
    @pytest.mark.asyncio
    async def test_no_healing_when_disabled(self, clock, order_store, position_store, exchange_client):
        """Should not heal when auto-healing is disabled."""
        worker = ReconciliationWorker(
            clock=clock,
            order_store=order_store,
            position_store=position_store,
            exchange_client=exchange_client,
            enable_auto_healing=False,  # Disabled
        )
        
        # Add ghost order
        order = create_test_order()
        order_store.add_order(order)
        exchange_client.exchange_orders = []
        
        result = await worker.reconcile()
        
        # Should detect but not heal
        assert result.has_discrepancies
        assert result.healing_actions_taken == 0
        
        # Order should still be in original state
        assert order_store.get_order(order.identity.client_order_id).state == OrderState.ACKED


class TestStatistics:
    """Tests for reconciliation statistics."""
    
    @pytest.mark.asyncio
    async def test_stats_tracking(self, worker, order_store, exchange_client):
        """Should track reconciliation statistics."""
        # Run a few reconciliations
        await worker.reconcile()
        await worker.reconcile()
        
        stats = worker.get_stats()
        
        assert stats["total_runs"] == 2
        assert "running" in stats
        assert "interval_sec" in stats
