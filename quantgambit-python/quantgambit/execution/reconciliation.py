"""
Reconciliation Worker.

Periodically compares local order/position state with exchange state
and heals any discrepancies.

This is critical for:
1. Recovering from missed WebSocket updates
2. Detecting ghost orders (local thinks exists, exchange says no)
3. Detecting orphan orders (exchange has it, we don't track it)
4. Position drift (local size != exchange size)
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Protocol, Set, TYPE_CHECKING

from quantgambit.core.clock import Clock
from quantgambit.core.events import EventEnvelope, EventType
from quantgambit.core.lifecycle import ManagedOrder, OrderState
from quantgambit.execution.symbols import to_storage_symbol
from quantgambit.io.sidechannel import SideChannelPublisher

if TYPE_CHECKING:
    from quantgambit.portfolio.state_manager import InMemoryStateManager

logger = logging.getLogger(__name__)


def _canonical_symbol(symbol: Optional[str]) -> str:
    return str(to_storage_symbol(symbol) or "")


class DiscrepancyType(str, Enum):
    """Types of reconciliation discrepancies."""
    
    # Order discrepancies
    GHOST_ORDER = "ghost_order"  # Local has order, exchange doesn't
    ORPHAN_ORDER = "orphan_order"  # Exchange has order, local doesn't
    ORDER_STATE_MISMATCH = "order_state_mismatch"  # State differs
    ORDER_FILLED_QTY_MISMATCH = "order_filled_qty_mismatch"  # Fill qty differs
    
    # Position discrepancies
    GHOST_POSITION = "ghost_position"  # Local has position, exchange doesn't
    ORPHAN_POSITION = "orphan_position"  # Exchange has position, local doesn't
    POSITION_SIZE_MISMATCH = "position_size_mismatch"  # Size differs
    POSITION_SIDE_MISMATCH = "position_side_mismatch"  # Side differs


@dataclass
class Discrepancy:
    """Represents a single discrepancy."""
    
    type: DiscrepancyType
    symbol: str
    description: str
    local_state: Dict[str, Any]
    exchange_state: Dict[str, Any]
    detected_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    resolved: bool = False
    resolution_action: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "type": self.type.value,
            "symbol": self.symbol,
            "description": self.description,
            "local_state": self.local_state,
            "exchange_state": self.exchange_state,
            "detected_at": self.detected_at,
            "resolved": self.resolved,
            "resolution_action": self.resolution_action,
        }


@dataclass
class ReconciliationResult:
    """Result of a reconciliation run."""
    
    started_at: str
    completed_at: str
    discrepancies: List[Discrepancy]
    orders_checked: int
    positions_checked: int
    symbols_checked: int
    healing_actions_taken: int
    
    @property
    def has_discrepancies(self) -> bool:
        return len(self.discrepancies) > 0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "discrepancies": [d.to_dict() for d in self.discrepancies],
            "orders_checked": self.orders_checked,
            "positions_checked": self.positions_checked,
            "symbols_checked": self.symbols_checked,
            "healing_actions_taken": self.healing_actions_taken,
        }


class OrderStore(Protocol):
    """Protocol for accessing local order state."""
    
    def get_open_orders(self, symbol: Optional[str] = None) -> List[ManagedOrder]:
        """Get open orders."""
        ...
    
    def get_order(self, client_order_id: str) -> Optional[ManagedOrder]:
        """Get order by client order ID."""
        ...
    
    def update_order(self, order: ManagedOrder) -> None:
        """Update order state."""
        ...
    
    def remove_order(self, client_order_id: str) -> None:
        """Remove order from tracking."""
        ...
    
    def add_order(self, order: ManagedOrder) -> None:
        """Add order to tracking."""
        ...


class PositionStore(Protocol):
    """Protocol for accessing local position state."""
    
    def get_position(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Get position for symbol."""
        ...
    
    def get_all_positions(self) -> Dict[str, Dict[str, Any]]:
        """Get all positions."""
        ...
    
    def update_position(self, symbol: str, size: float, entry_price: float) -> None:
        """Update position."""
        ...
    
    def clear_position(self, symbol: str) -> None:
        """Clear position."""
        ...


class ExchangeClient(Protocol):
    """Protocol for exchange queries."""
    
    async def get_open_orders(self, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        """Query open orders from exchange."""
        ...
    
    async def get_positions(self) -> List[Dict[str, Any]]:
        """Query positions from exchange."""
        ...
    
    async def cancel_order(self, symbol: str, order_id: str) -> bool:
        """Cancel an order."""
        ...


class ReconciliationWorker:
    """
    Periodically reconciles local state with exchange.
    
    Usage:
        worker = ReconciliationWorker(
            clock=clock,
            order_store=order_store,
            position_store=position_store,
            exchange_client=exchange_client,
            interval_sec=30,  # Reconcile every 30 seconds
        )
        
        await worker.start()
        # ... later ...
        await worker.stop()
    """
    
    def __init__(
        self,
        clock: Clock,
        order_store: OrderStore,
        position_store: PositionStore,
        exchange_client: ExchangeClient,
        side_channel: Optional[SideChannelPublisher] = None,
        interval_sec: float = 30.0,
        position_size_tolerance: float = 1e-8,
        enable_auto_healing: bool = True,
        symbols: Optional[Set[str]] = None,
    ):
        """
        Initialize reconciliation worker.
        
        Args:
            clock: Time source
            order_store: Local order store
            position_store: Local position store
            exchange_client: Exchange client for queries
            side_channel: Optional event publisher
            interval_sec: Reconciliation interval
            position_size_tolerance: Tolerance for position size comparison
            enable_auto_healing: Whether to auto-heal discrepancies
            symbols: Optional set of symbols to reconcile (None = all)
        """
        self._clock = clock
        self._order_store = order_store
        self._position_store = position_store
        self._exchange_client = exchange_client
        self._side_channel = side_channel
        self._interval_sec = interval_sec
        self._position_size_tolerance = position_size_tolerance
        self._enable_auto_healing = enable_auto_healing
        self._symbols = {_canonical_symbol(symbol) for symbol in symbols} if symbols else None
        
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._last_result: Optional[ReconciliationResult] = None
        
        # Statistics
        self._total_runs = 0
        self._total_discrepancies = 0
        self._total_healed = 0
    
    async def start(self) -> None:
        """Start the reconciliation worker."""
        if self._running:
            return
        
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info(f"Reconciliation worker started (interval={self._interval_sec}s)")
    
    async def stop(self) -> None:
        """Stop the reconciliation worker."""
        if not self._running:
            return
        
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        
        logger.info("Reconciliation worker stopped")
    
    async def _run_loop(self) -> None:
        """Main loop."""
        while self._running:
            try:
                await asyncio.sleep(self._interval_sec)
                
                if not self._running:
                    break
                
                result = await self.reconcile()
                
                if result.has_discrepancies:
                    logger.warning(
                        f"Reconciliation found {len(result.discrepancies)} discrepancies, "
                        f"healed {result.healing_actions_taken}"
                    )
                else:
                    logger.debug("Reconciliation completed - no discrepancies")
                    
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"Reconciliation error: {e}", exc_info=True)
    
    async def reconcile(self) -> ReconciliationResult:
        """
        Perform a full reconciliation.
        
        Returns:
            ReconciliationResult with findings
        """
        started_at = datetime.utcnow().isoformat()
        discrepancies: List[Discrepancy] = []
        healing_actions = 0
        orders_checked = 0
        positions_checked = 0
        symbols_checked = 0
        
        try:
            # Reconcile orders
            order_discs, order_healed, orders_checked = await self._reconcile_orders()
            discrepancies.extend(order_discs)
            healing_actions += order_healed
            
            # Reconcile positions
            pos_discs, pos_healed, positions_checked = await self._reconcile_positions()
            discrepancies.extend(pos_discs)
            healing_actions += pos_healed
            
            # Count unique symbols
            symbols = set()
            for d in discrepancies:
                symbols.add(d.symbol)
            symbols_checked = len(symbols)
            
        except Exception as e:
            logger.error(f"Reconciliation failed: {e}", exc_info=True)
        
        completed_at = datetime.utcnow().isoformat()
        
        result = ReconciliationResult(
            started_at=started_at,
            completed_at=completed_at,
            discrepancies=discrepancies,
            orders_checked=orders_checked,
            positions_checked=positions_checked,
            symbols_checked=symbols_checked,
            healing_actions_taken=healing_actions,
        )
        
        self._last_result = result
        self._total_runs += 1
        self._total_discrepancies += len(discrepancies)
        self._total_healed += healing_actions
        
        # Publish result
        await self._publish_result(result)
        
        return result
    
    async def _reconcile_orders(self) -> tuple[List[Discrepancy], int, int]:
        """Reconcile orders."""
        discrepancies: List[Discrepancy] = []
        healed = 0
        
        # Get local orders
        local_orders = self._order_store.get_open_orders()
        local_by_coid = {o.identity.client_order_id: o for o in local_orders}
        
        # Get exchange orders
        exchange_orders = await self._exchange_client.get_open_orders()
        exchange_by_coid = {o.get("clientOrderId", ""): o for o in exchange_orders if o.get("clientOrderId")}
        
        checked = len(local_by_coid) + len(exchange_by_coid)
        
        # Check for ghost orders (local has it, exchange doesn't)
        for coid, local_order in local_by_coid.items():
            local_symbol = _canonical_symbol(local_order.symbol)
            if self._symbols and local_symbol not in self._symbols:
                continue
                
            if coid not in exchange_by_coid:
                disc = Discrepancy(
                    type=DiscrepancyType.GHOST_ORDER,
                    symbol=local_symbol,
                    description=f"Order {coid} exists locally but not on exchange",
                    local_state={
                        "client_order_id": coid,
                        "state": local_order.state.value,
                        "qty": local_order.qty,
                    },
                    exchange_state={},
                )
                discrepancies.append(disc)
                
                # Heal: mark as cancelled/expired
                if self._enable_auto_healing:
                    local_order.state = OrderState.CANCELED
                    self._order_store.update_order(local_order)
                    disc.resolved = True
                    disc.resolution_action = "Marked as CANCELED"
                    healed += 1
                    logger.info(f"Healed ghost order {coid}: marked as CANCELED")
        
        # Check for orphan orders (exchange has it, local doesn't)
        for coid, exch_order in exchange_by_coid.items():
            symbol = _canonical_symbol(exch_order.get("symbol", ""))
            if self._symbols and symbol not in self._symbols:
                continue
                
            if coid not in local_by_coid:
                disc = Discrepancy(
                    type=DiscrepancyType.ORPHAN_ORDER,
                    symbol=symbol,
                    description=f"Order {coid} exists on exchange but not locally",
                    local_state={},
                    exchange_state={
                        "client_order_id": coid,
                        "exchange_order_id": exch_order.get("orderId"),
                        "status": exch_order.get("status"),
                        "qty": exch_order.get("qty"),
                    },
                )
                discrepancies.append(disc)
                
                # Heal: cancel orphan order (safety measure)
                if self._enable_auto_healing:
                    try:
                        cancelled = await self._exchange_client.cancel_order(
                            symbol=symbol,
                            order_id=exch_order.get("orderId", ""),
                        )
                        if cancelled:
                            disc.resolved = True
                            disc.resolution_action = "Cancelled orphan order"
                            healed += 1
                            logger.warning(f"Healed orphan order {coid}: cancelled on exchange")
                    except Exception as e:
                        logger.error(f"Failed to cancel orphan order {coid}: {e}")
        
        # Check for state mismatches
        for coid in local_by_coid.keys() & exchange_by_coid.keys():
            local_order = local_by_coid[coid]
            exch_order = exchange_by_coid[coid]
            
            local_symbol = _canonical_symbol(local_order.symbol)
            if self._symbols and local_symbol not in self._symbols:
                continue
            
            # Check filled qty
            local_filled = local_order.filled_qty
            exch_filled = float(exch_order.get("cumExecQty", 0) or 0)
            
            if abs(local_filled - exch_filled) > 1e-8:
                disc = Discrepancy(
                    type=DiscrepancyType.ORDER_FILLED_QTY_MISMATCH,
                    symbol=local_symbol,
                    description=f"Filled qty mismatch for {coid}",
                    local_state={"filled_qty": local_filled},
                    exchange_state={"filled_qty": exch_filled},
                )
                discrepancies.append(disc)
                
                # Heal: trust exchange
                if self._enable_auto_healing:
                    local_order.filled_qty = exch_filled
                    self._order_store.update_order(local_order)
                    disc.resolved = True
                    disc.resolution_action = f"Updated filled_qty to {exch_filled}"
                    healed += 1
                    logger.info(f"Healed filled qty mismatch for {coid}")
        
        return discrepancies, healed, checked
    
    async def _reconcile_positions(self) -> tuple[List[Discrepancy], int, int]:
        """Reconcile positions."""
        discrepancies: List[Discrepancy] = []
        healed = 0
        
        # Get local positions
        local_positions = self._position_store.get_all_positions()
        
        # Get exchange positions
        exchange_positions = await self._exchange_client.get_positions()
        exchange_by_symbol = {_canonical_symbol(p.get("symbol", "")): p for p in exchange_positions}
        
        checked = len(local_positions) + len(exchange_by_symbol)
        
        # Check for ghost positions (local has it, exchange doesn't)
        for symbol, local_pos in local_positions.items():
            canonical_symbol = _canonical_symbol(symbol)
            if self._symbols and canonical_symbol not in self._symbols:
                continue
                
            local_size = float(local_pos.get("size", 0) or 0)
            
            if canonical_symbol not in exchange_by_symbol:
                if abs(local_size) > self._position_size_tolerance:
                    disc = Discrepancy(
                        type=DiscrepancyType.GHOST_POSITION,
                        symbol=canonical_symbol,
                        description=f"Position {canonical_symbol} exists locally but not on exchange",
                        local_state={"size": local_size},
                        exchange_state={},
                    )
                    discrepancies.append(disc)
                    
                    # Heal: clear local position
                    if self._enable_auto_healing:
                        self._position_store.clear_position(symbol)
                        disc.resolved = True
                        disc.resolution_action = "Cleared local position"
                        healed += 1
                        logger.warning(f"Healed ghost position {symbol}: cleared local")
        
        # Check for orphan positions (exchange has it, local doesn't)
        for symbol, exch_pos in exchange_by_symbol.items():
            if self._symbols and symbol not in self._symbols:
                continue
                
            exch_size = float(exch_pos.get("size", 0) or 0)
            
            has_local_position = any(_canonical_symbol(raw_symbol) == symbol for raw_symbol in local_positions.keys())
            if not has_local_position:
                if abs(exch_size) > self._position_size_tolerance:
                    disc = Discrepancy(
                        type=DiscrepancyType.ORPHAN_POSITION,
                        symbol=symbol,
                        description=f"Position {symbol} exists on exchange but not locally",
                        local_state={},
                        exchange_state={"size": exch_size},
                    )
                    discrepancies.append(disc)
                    
                    # Heal: sync local position
                    if self._enable_auto_healing:
                        entry_price = float(exch_pos.get("avgPrice", 0) or 0)
                        self._position_store.update_position(symbol, exch_size, entry_price)
                        disc.resolved = True
                        disc.resolution_action = f"Synced local position: size={exch_size}"
                        healed += 1
                        logger.warning(f"Healed orphan position {symbol}: synced local")
        
        # Check for size mismatches
        local_positions_by_symbol = {
            _canonical_symbol(symbol): (symbol, local_pos)
            for symbol, local_pos in local_positions.items()
        }
        for symbol in local_positions_by_symbol.keys() & exchange_by_symbol.keys():
            if self._symbols and symbol not in self._symbols:
                continue
                
            raw_symbol, local_pos = local_positions_by_symbol[symbol]
            exch_pos = exchange_by_symbol[symbol]
            
            local_size = float(local_pos.get("size", 0) or 0)
            exch_size = float(exch_pos.get("size", 0) or 0)
            
            if abs(local_size - exch_size) > self._position_size_tolerance:
                disc = Discrepancy(
                    type=DiscrepancyType.POSITION_SIZE_MISMATCH,
                    symbol=symbol,
                    description=f"Position size mismatch for {symbol}",
                    local_state={"size": local_size},
                    exchange_state={"size": exch_size},
                )
                discrepancies.append(disc)
                
                # Heal: trust exchange
                if self._enable_auto_healing:
                    entry_price = float(exch_pos.get("avgPrice", 0) or 0)
                    if abs(exch_size) > self._position_size_tolerance:
                        self._position_store.update_position(raw_symbol, exch_size, entry_price)
                    else:
                        self._position_store.clear_position(raw_symbol)
                    disc.resolved = True
                    disc.resolution_action = f"Updated size to {exch_size}"
                    healed += 1
                    logger.info(f"Healed position size mismatch for {symbol}")
        
        return discrepancies, healed, checked
    
    async def _publish_result(self, result: ReconciliationResult) -> None:
        """Publish reconciliation result."""
        if not self._side_channel:
            return
        
        event = EventEnvelope(
            v=1,
            type=EventType.OPS_HEALTH,
            source="reconciliation_worker",
            symbol=None,
            ts_wall=self._clock.get_time(),
            ts_mono=self._clock.get_monotonic_time(),
            trace_id="reconciliation",
            seq=self._total_runs,
            payload={
                "event": "reconciliation_complete",
                "discrepancy_count": len(result.discrepancies),
                "healing_actions": result.healing_actions_taken,
                "orders_checked": result.orders_checked,
                "positions_checked": result.positions_checked,
            },
        )
        self._side_channel.publish(event)
    
    def get_stats(self) -> Dict[str, Any]:
        """Get reconciliation statistics."""
        return {
            "total_runs": self._total_runs,
            "total_discrepancies": self._total_discrepancies,
            "total_healed": self._total_healed,
            "running": self._running,
            "interval_sec": self._interval_sec,
            "last_result": self._last_result.to_dict() if self._last_result else None,
        }


# =============================================================================
# BACKWARD COMPATIBILITY
# =============================================================================
# These exports maintain compatibility with older tests

class SimpleExchangeReconciler:
    """
    Simple reconciler for backward compatibility.
    
    Reconciles positions between a provider and state manager.
    """
    
    def __init__(self, provider, state_manager: "InMemoryStateManager"):
        """
        Initialize reconciler.
        
        Args:
            provider: Object with list_open_positions() method
            state_manager: InMemoryStateManager instance
        """
        self._provider = provider
        self._state = state_manager
    
    async def reconcile(self) -> None:
        """
        Reconcile positions.
        
        - Removes local positions not on exchange
        - Adds exchange positions not local
        - Updates size mismatches
        """
        # Get exchange positions
        exchange_positions = await self._provider.list_open_positions()
        exchange_by_symbol = {p.symbol: p for p in exchange_positions}
        exchange_symbols = set(exchange_by_symbol.keys())
        
        # Get local symbols (access internal _positions dict)
        local_symbols = set(self._state._positions.keys())
        
        # Remove ghost positions (local but not on exchange)
        for symbol in local_symbols - exchange_symbols:
            # Remove by deleting from internal dict
            del self._state._positions[symbol]
        
        # Add/update exchange positions
        for pos in exchange_positions:
            self._state.add_position(pos.symbol, pos.side, pos.size)


def build_reconciler(
    exchange_name: str,
    adapter,
    state_manager: "InMemoryStateManager",
) -> SimpleExchangeReconciler:
    """
    Build a simple reconciler for backward compatibility.
    
    Args:
        exchange_name: Name of exchange (unused, for compat)
        adapter: Adapter with list_positions() method
        state_manager: InMemoryStateManager instance
        
    Returns:
        SimpleExchangeReconciler instance
    """
    
    class ProviderWrapper:
        """Wrap adapter to provide list_open_positions."""
        
        def __init__(self, adapter):
            self._adapter = adapter
        
        async def list_open_positions(self):
            return await self._adapter.list_positions()
    
    return SimpleExchangeReconciler(ProviderWrapper(adapter), state_manager)
