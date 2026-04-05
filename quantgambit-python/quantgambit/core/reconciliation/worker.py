"""
Reconciliation worker implementation.

Periodically compares local state with exchange state and heals
any discrepancies. Critical for ensuring execution correctness.

The worker:
1. Fetches current positions from exchange
2. Fetches open orders from exchange
3. Compares with local state
4. Emits discrepancy events
5. Optionally heals discrepancies
"""

import asyncio
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Protocol

from quantgambit.core.clock import Clock
from quantgambit.core.events import EventEnvelope, EventType
from quantgambit.core.lifecycle import OrderState
from quantgambit.io.sidechannel import SideChannelPublisher
from quantgambit.core.ids import generate_trace_id

logger = logging.getLogger(__name__)


class DiscrepancyType(str, Enum):
    """Types of state discrepancies."""
    
    # Position discrepancies
    POSITION_MISSING_LOCAL = "position_missing_local"  # Exchange has position, local doesn't
    POSITION_MISSING_REMOTE = "position_missing_remote"  # Local has position, exchange doesn't
    POSITION_SIZE_MISMATCH = "position_size_mismatch"  # Size differs
    POSITION_SIDE_MISMATCH = "position_side_mismatch"  # Side differs
    
    # Order discrepancies
    ORDER_MISSING_LOCAL = "order_missing_local"  # Exchange has order, local doesn't
    ORDER_MISSING_REMOTE = "order_missing_remote"  # Local has order, exchange doesn't
    ORDER_STATE_MISMATCH = "order_state_mismatch"  # State differs
    ORDER_SIZE_MISMATCH = "order_size_mismatch"  # Size/filled differs
    
    # Unknown
    UNKNOWN = "unknown"


@dataclass
class Discrepancy:
    """A detected discrepancy between local and exchange state."""
    
    type: DiscrepancyType
    symbol: str
    local_value: Any
    remote_value: Any
    details: str
    detected_at: float
    healed: bool = False
    heal_action: str = ""


@dataclass
class ExchangePosition:
    """Position data from exchange."""
    
    symbol: str
    size: float  # Signed
    entry_price: float
    unrealized_pnl: float = 0.0
    liquidation_price: Optional[float] = None
    leverage: float = 1.0


@dataclass
class ExchangeOrder:
    """Order data from exchange."""
    
    exchange_order_id: str
    client_order_id: Optional[str]
    symbol: str
    side: str
    order_type: str
    price: Optional[float]
    size: float
    filled_size: float
    status: str  # Exchange-specific status string
    created_at: float


@dataclass
class LocalPosition:
    """Position in local state."""
    
    symbol: str
    size: float
    entry_price: float


@dataclass
class LocalOrder:
    """Order in local state."""
    
    client_order_id: str
    exchange_order_id: Optional[str]
    symbol: str
    side: str
    order_type: str
    price: Optional[float]
    size: float
    filled_size: float
    state: OrderState


class ExchangeClient(Protocol):
    """Protocol for exchange client used by reconciliation."""
    
    async def get_positions(self) -> List[ExchangePosition]:
        """Fetch all positions from exchange."""
        ...
    
    async def get_open_orders(self, symbol: Optional[str] = None) -> List[ExchangeOrder]:
        """Fetch open orders from exchange."""
        ...
    
    async def cancel_order(self, exchange_order_id: str) -> bool:
        """Cancel an order on the exchange."""
        ...
    
    async def flatten_position(self, symbol: str) -> bool:
        """Close a position on the exchange."""
        ...


class LocalStateManager(Protocol):
    """Protocol for local state manager used by reconciliation."""
    
    def get_positions(self) -> Dict[str, LocalPosition]:
        """Get all local positions."""
        ...
    
    def get_open_orders(self, symbol: Optional[str] = None) -> List[LocalOrder]:
        """Get all open orders in local state."""
        ...
    
    def update_position(self, symbol: str, size: float, entry_price: float) -> None:
        """Update local position state."""
        ...
    
    def remove_position(self, symbol: str) -> None:
        """Remove position from local state."""
        ...
    
    def update_order_state(self, client_order_id: str, state: OrderState) -> None:
        """Update order state in local state."""
        ...
    
    def add_order(self, order: LocalOrder) -> None:
        """Add order to local state."""
        ...


@dataclass
class ReconciliationConfig:
    """Configuration for reconciliation worker."""
    
    interval_seconds: float = 30.0  # How often to reconcile
    position_size_tolerance: float = 0.0001  # Size difference to consider equal
    auto_heal: bool = True  # Automatically heal discrepancies
    cancel_orphan_orders: bool = True  # Cancel orders not in local state
    flatten_orphan_positions: bool = False  # Flatten positions not in local state
    max_discrepancies_per_run: int = 10  # Max discrepancies to process per run
    enabled: bool = True


class ReconciliationWorker:
    """
    Worker that periodically reconciles local state with exchange.
    
    Runs at a configurable interval (default 30s) and:
    1. Fetches positions and orders from exchange
    2. Compares with local state
    3. Emits events for any discrepancies
    4. Optionally heals discrepancies
    
    Usage:
        worker = ReconciliationWorker(
            clock=clock,
            exchange_client=client,
            local_state=state_manager,
            publisher=publisher,
            config=config,
        )
        await worker.start()
        # ... later ...
        await worker.stop()
    """
    
    def __init__(
        self,
        clock: Clock,
        exchange_client: ExchangeClient,
        local_state: LocalStateManager,
        publisher: SideChannelPublisher,
        config: Optional[ReconciliationConfig] = None,
    ):
        """
        Initialize reconciliation worker.
        
        Args:
            clock: Clock for timestamps
            exchange_client: Client for exchange API calls
            local_state: Local state manager
            publisher: Side channel publisher for events
            config: Worker configuration
        """
        self._clock = clock
        self._exchange = exchange_client
        self._local = local_state
        self._publisher = publisher
        self._config = config or ReconciliationConfig()
        
        self._running = False
        self._task: Optional[asyncio.Task] = None
        
        # Statistics
        self._run_count = 0
        self._total_discrepancies = 0
        self._total_healed = 0
        self._last_run_at: Optional[float] = None
        self._last_discrepancies: List[Discrepancy] = []
    
    async def start(self) -> None:
        """Start the reconciliation worker."""
        if self._running:
            return
        
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info(f"ReconciliationWorker started with interval={self._config.interval_seconds}s")
    
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
        logger.info("ReconciliationWorker stopped")
    
    async def run_once(self) -> List[Discrepancy]:
        """
        Run a single reconciliation pass.
        
        Returns:
            List of detected discrepancies
        """
        if not self._config.enabled:
            return []
        
        self._run_count += 1
        self._last_run_at = self._clock.now()
        discrepancies: List[Discrepancy] = []
        
        try:
            # Reconcile positions
            pos_discrepancies = await self._reconcile_positions()
            discrepancies.extend(pos_discrepancies)
            
            # Reconcile orders
            order_discrepancies = await self._reconcile_orders()
            discrepancies.extend(order_discrepancies)
            
            # Limit discrepancies processed
            if len(discrepancies) > self._config.max_discrepancies_per_run:
                logger.warning(
                    f"Truncating discrepancies from {len(discrepancies)} to {self._config.max_discrepancies_per_run}"
                )
                discrepancies = discrepancies[:self._config.max_discrepancies_per_run]
            
            # Emit events and optionally heal
            for disc in discrepancies:
                self._emit_discrepancy_event(disc)
                
                if self._config.auto_heal:
                    await self._heal_discrepancy(disc)
            
            self._total_discrepancies += len(discrepancies)
            self._last_discrepancies = discrepancies
            
            if discrepancies:
                logger.warning(f"Reconciliation found {len(discrepancies)} discrepancies")
            else:
                logger.debug("Reconciliation complete, no discrepancies")
            
        except Exception as e:
            logger.error(f"Reconciliation error: {e}", exc_info=True)
            self._emit_error_event(str(e))
        
        return discrepancies
    
    async def _run_loop(self) -> None:
        """Main worker loop."""
        while self._running:
            await self.run_once()
            await self._clock.sleep(self._config.interval_seconds)
    
    async def _reconcile_positions(self) -> List[Discrepancy]:
        """Reconcile positions between local and exchange."""
        discrepancies: List[Discrepancy] = []
        
        # Fetch exchange positions
        try:
            exchange_positions = await self._exchange.get_positions()
        except Exception as e:
            logger.error(f"Failed to fetch exchange positions: {e}")
            return discrepancies
        
        # Get local positions
        local_positions = self._local.get_positions()
        
        # Build lookup
        exchange_by_symbol = {p.symbol: p for p in exchange_positions}
        
        # Check for discrepancies
        checked_symbols = set()
        
        # Check exchange positions against local
        for ex_pos in exchange_positions:
            checked_symbols.add(ex_pos.symbol)
            local_pos = local_positions.get(ex_pos.symbol)
            
            if local_pos is None:
                # Position exists on exchange but not locally
                discrepancies.append(Discrepancy(
                    type=DiscrepancyType.POSITION_MISSING_LOCAL,
                    symbol=ex_pos.symbol,
                    local_value=None,
                    remote_value=ex_pos.size,
                    details=f"Exchange has position size={ex_pos.size}, local has none",
                    detected_at=self._clock.now(),
                ))
            else:
                # Check size match
                size_diff = abs(ex_pos.size - local_pos.size)
                if size_diff > self._config.position_size_tolerance:
                    # Check if side differs
                    if (ex_pos.size > 0) != (local_pos.size > 0):
                        discrepancies.append(Discrepancy(
                            type=DiscrepancyType.POSITION_SIDE_MISMATCH,
                            symbol=ex_pos.symbol,
                            local_value=local_pos.size,
                            remote_value=ex_pos.size,
                            details=f"Side mismatch: local={local_pos.size}, exchange={ex_pos.size}",
                            detected_at=self._clock.now(),
                        ))
                    else:
                        discrepancies.append(Discrepancy(
                            type=DiscrepancyType.POSITION_SIZE_MISMATCH,
                            symbol=ex_pos.symbol,
                            local_value=local_pos.size,
                            remote_value=ex_pos.size,
                            details=f"Size mismatch: local={local_pos.size}, exchange={ex_pos.size}",
                            detected_at=self._clock.now(),
                        ))
        
        # Check for local positions missing from exchange
        for symbol, local_pos in local_positions.items():
            if symbol not in checked_symbols and abs(local_pos.size) > self._config.position_size_tolerance:
                discrepancies.append(Discrepancy(
                    type=DiscrepancyType.POSITION_MISSING_REMOTE,
                    symbol=symbol,
                    local_value=local_pos.size,
                    remote_value=None,
                    details=f"Local has position size={local_pos.size}, exchange has none",
                    detected_at=self._clock.now(),
                ))
        
        return discrepancies
    
    async def _reconcile_orders(self) -> List[Discrepancy]:
        """Reconcile orders between local and exchange."""
        discrepancies: List[Discrepancy] = []
        
        # Fetch exchange orders
        try:
            exchange_orders = await self._exchange.get_open_orders()
        except Exception as e:
            logger.error(f"Failed to fetch exchange orders: {e}")
            return discrepancies
        
        # Get local orders
        local_orders = self._local.get_open_orders()
        
        # Build lookups
        exchange_by_client_id = {
            o.client_order_id: o for o in exchange_orders if o.client_order_id
        }
        local_by_client_id = {o.client_order_id: o for o in local_orders}
        
        checked_client_ids = set()
        
        # Check exchange orders against local
        for ex_order in exchange_orders:
            if not ex_order.client_order_id:
                continue
            
            checked_client_ids.add(ex_order.client_order_id)
            local_order = local_by_client_id.get(ex_order.client_order_id)
            
            if local_order is None:
                # Orphan order on exchange
                discrepancies.append(Discrepancy(
                    type=DiscrepancyType.ORDER_MISSING_LOCAL,
                    symbol=ex_order.symbol,
                    local_value=None,
                    remote_value=ex_order.exchange_order_id,
                    details=f"Exchange has order {ex_order.exchange_order_id}, local doesn't track it",
                    detected_at=self._clock.now(),
                ))
            else:
                # Check filled size
                if abs(ex_order.filled_size - local_order.filled_size) > self._config.position_size_tolerance:
                    discrepancies.append(Discrepancy(
                        type=DiscrepancyType.ORDER_SIZE_MISMATCH,
                        symbol=ex_order.symbol,
                        local_value=local_order.filled_size,
                        remote_value=ex_order.filled_size,
                        details=f"Filled size mismatch: local={local_order.filled_size}, exchange={ex_order.filled_size}",
                        detected_at=self._clock.now(),
                    ))
        
        # Check for local orders missing from exchange
        for local_order in local_orders:
            if local_order.client_order_id not in checked_client_ids:
                # Local order not on exchange
                if local_order.state not in {OrderState.FILLED, OrderState.CANCELED, OrderState.REJECTED}:
                    discrepancies.append(Discrepancy(
                        type=DiscrepancyType.ORDER_MISSING_REMOTE,
                        symbol=local_order.symbol,
                        local_value=local_order.client_order_id,
                        remote_value=None,
                        details=f"Local has order {local_order.client_order_id} in state {local_order.state}, exchange doesn't",
                        detected_at=self._clock.now(),
                    ))
        
        return discrepancies
    
    async def _heal_discrepancy(self, disc: Discrepancy) -> None:
        """Attempt to heal a discrepancy."""
        try:
            if disc.type == DiscrepancyType.POSITION_MISSING_LOCAL:
                # Exchange has position we don't know about
                # Add it to local state
                self._local.update_position(
                    disc.symbol,
                    disc.remote_value,
                    0.0,  # Unknown entry price
                )
                disc.healed = True
                disc.heal_action = "added_to_local"
                logger.info(f"Healed {disc.type}: added position to local state")
            
            elif disc.type == DiscrepancyType.POSITION_MISSING_REMOTE:
                # We have position that exchange doesn't
                # Clear local state
                self._local.remove_position(disc.symbol)
                disc.healed = True
                disc.heal_action = "removed_from_local"
                logger.info(f"Healed {disc.type}: removed stale position from local state")
            
            elif disc.type in {DiscrepancyType.POSITION_SIZE_MISMATCH, DiscrepancyType.POSITION_SIDE_MISMATCH}:
                # Update local to match exchange
                self._local.update_position(
                    disc.symbol,
                    disc.remote_value,
                    0.0,  # Unknown entry price
                )
                disc.healed = True
                disc.heal_action = "updated_local"
                logger.info(f"Healed {disc.type}: updated local position to match exchange")
            
            elif disc.type == DiscrepancyType.ORDER_MISSING_LOCAL:
                # Exchange has order we don't track
                if self._config.cancel_orphan_orders:
                    # Cancel it
                    success = await self._exchange.cancel_order(disc.remote_value)
                    if success:
                        disc.healed = True
                        disc.heal_action = "canceled_orphan"
                        logger.info(f"Healed {disc.type}: canceled orphan order")
            
            elif disc.type == DiscrepancyType.ORDER_MISSING_REMOTE:
                # We have order that exchange doesn't
                # Mark as canceled in local state
                self._local.update_order_state(disc.local_value, OrderState.CANCELED)
                disc.healed = True
                disc.heal_action = "marked_canceled"
                logger.info(f"Healed {disc.type}: marked order as canceled")
            
            if disc.healed:
                self._total_healed += 1
        
        except Exception as e:
            logger.error(f"Failed to heal discrepancy {disc.type}: {e}")
    
    def _emit_discrepancy_event(self, disc: Discrepancy) -> None:
        """Emit event for a discrepancy."""
        event = EventEnvelope(
            v=1,
            type=EventType.OPS_ALERT,
            source="quantgambit.reconciliation",
            symbol=disc.symbol,
            ts_wall=self._clock.now(),
            ts_mono=self._clock.now_mono(),
            trace_id=generate_trace_id(),
            seq=None,
            payload={
                "alert_type": "state_discrepancy",
                "discrepancy_type": disc.type.value,
                "local_value": disc.local_value,
                "remote_value": disc.remote_value,
                "details": disc.details,
                "healed": disc.healed,
                "heal_action": disc.heal_action,
            },
        )
        self._publisher.publish(event)
    
    def _emit_error_event(self, message: str) -> None:
        """Emit event for reconciliation error."""
        event = EventEnvelope(
            v=1,
            type=EventType.OPS_ALERT,
            source="quantgambit.reconciliation",
            symbol=None,
            ts_wall=self._clock.now(),
            ts_mono=self._clock.now_mono(),
            trace_id=generate_trace_id(),
            seq=None,
            payload={
                "alert_type": "reconciliation_error",
                "message": message,
            },
        )
        self._publisher.publish(event)
    
    def stats(self) -> Dict[str, Any]:
        """Get worker statistics."""
        return {
            "run_count": self._run_count,
            "total_discrepancies": self._total_discrepancies,
            "total_healed": self._total_healed,
            "last_run_at": self._last_run_at,
            "last_discrepancy_count": len(self._last_discrepancies),
            "config": {
                "interval_seconds": self._config.interval_seconds,
                "auto_heal": self._config.auto_heal,
                "enabled": self._config.enabled,
            },
        }
