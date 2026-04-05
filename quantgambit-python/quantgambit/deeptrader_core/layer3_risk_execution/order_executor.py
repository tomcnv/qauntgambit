"""
Order Executor - Execute orders

Handles:
1. Order submission (market/limit)
2. Order status tracking
3. Fill confirmation
4. Partial fills
5. Order cancellation

Returns execution results.
"""

from dataclasses import dataclass
from typing import Dict, Optional
from enum import Enum
import time


class OrderType(Enum):
    """Order type"""
    MARKET = "market"
    LIMIT = "limit"


class OrderStatus(Enum):
    """Order status"""
    PENDING = "pending"
    SUBMITTED = "submitted"
    FILLED = "filled"
    PARTIALLY_FILLED = "partially_filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


@dataclass
class ExecutionResult:
    """Order execution result"""
    order_id: str
    symbol: str
    side: str  # 'buy' or 'sell'
    order_type: OrderType
    size_units: float
    price: float
    status: OrderStatus
    filled_size: float = 0.0
    avg_fill_price: float = 0.0
    slippage_bps: float = 0.0
    execution_time_ms: float = 0.0
    error_message: Optional[str] = None
    
    def to_dict(self) -> Dict:
        """Convert to dictionary"""
        return {
            'order_id': self.order_id,
            'symbol': self.symbol,
            'side': self.side,
            'order_type': self.order_type.value,
            'size_units': self.size_units,
            'price': self.price,
            'status': self.status.value,
            'filled_size': self.filled_size,
            'avg_fill_price': self.avg_fill_price,
            'slippage_bps': self.slippage_bps,
            'execution_time_ms': self.execution_time_ms,
            'error_message': self.error_message,
        }


class OrderExecutor:
    """Execute orders"""
    
    def __init__(self, exchange_client=None):
        self.exchange_client = exchange_client
        
        # Stats
        self.orders_submitted = 0
        self.orders_filled = 0
        self.orders_rejected = 0
        self.total_slippage_bps = 0.0
        self.total_execution_time_ms = 0.0
    
    async def execute_market_order(
        self,
        symbol: str,
        side: str,
        size_units: float,
        expected_price: float
    ) -> ExecutionResult:
        """
        Execute a market order
        
        Args:
            symbol: Trading symbol
            side: Order side ('buy' or 'sell')
            size_units: Order size in units
            expected_price: Expected execution price
            
        Returns:
            ExecutionResult
        """
        start_time = time.time()
        order_id = f"{symbol}_{side}_{int(time.time() * 1000)}"
        
        self.orders_submitted += 1
        
        # If no exchange client, simulate execution
        if self.exchange_client is None:
            # Simulate market order execution
            # Assume 2 bps slippage for market orders
            slippage_bps = 2.0
            if side == "buy":
                fill_price = expected_price * (1 + slippage_bps / 10000)
            else:
                fill_price = expected_price * (1 - slippage_bps / 10000)
            
            execution_time_ms = (time.time() - start_time) * 1000
            
            self.orders_filled += 1
            self.total_slippage_bps += slippage_bps
            self.total_execution_time_ms += execution_time_ms
            
            return ExecutionResult(
                order_id=order_id,
                symbol=symbol,
                side=side,
                order_type=OrderType.MARKET,
                size_units=size_units,
                price=expected_price,
                status=OrderStatus.FILLED,
                filled_size=size_units,
                avg_fill_price=fill_price,
                slippage_bps=slippage_bps,
                execution_time_ms=execution_time_ms,
            )
        
        response = await _place_exchange_order(
            self.exchange_client,
            symbol=symbol,
            side=side,
            size_units=size_units,
            order_type=OrderType.MARKET,
            price=expected_price,
        )
        execution_time_ms = (time.time() - start_time) * 1000
        return _build_execution_result(
            order_id=order_id,
            symbol=symbol,
            side=side,
            order_type=OrderType.MARKET,
            size_units=size_units,
            expected_price=expected_price,
            execution_time_ms=execution_time_ms,
            response=response,
        )
    
    async def execute_limit_order(
        self,
        symbol: str,
        side: str,
        size_units: float,
        limit_price: float
    ) -> ExecutionResult:
        """
        Execute a limit order
        
        Args:
            symbol: Trading symbol
            side: Order side ('buy' or 'sell')
            size_units: Order size in units
            limit_price: Limit price
            
        Returns:
            ExecutionResult
        """
        start_time = time.time()
        order_id = f"{symbol}_{side}_limit_{int(time.time() * 1000)}"
        
        self.orders_submitted += 1
        
        # If no exchange client, simulate execution
        if self.exchange_client is None:
            # Simulate limit order execution
            # Assume limit orders get filled at limit price (no slippage)
            execution_time_ms = (time.time() - start_time) * 1000
            
            self.orders_filled += 1
            self.total_execution_time_ms += execution_time_ms
            
            return ExecutionResult(
                order_id=order_id,
                symbol=symbol,
                side=side,
                order_type=OrderType.LIMIT,
                size_units=size_units,
                price=limit_price,
                status=OrderStatus.FILLED,
                filled_size=size_units,
                avg_fill_price=limit_price,
                slippage_bps=0.0,  # No slippage for limit orders
                execution_time_ms=execution_time_ms,
            )
        
        response = await _place_exchange_order(
            self.exchange_client,
            symbol=symbol,
            side=side,
            size_units=size_units,
            order_type=OrderType.LIMIT,
            price=limit_price,
        )
        execution_time_ms = (time.time() - start_time) * 1000
        return _build_execution_result(
            order_id=order_id,
            symbol=symbol,
            side=side,
            order_type=OrderType.LIMIT,
            size_units=size_units,
            expected_price=limit_price,
            execution_time_ms=execution_time_ms,
            response=response,
        )
    
    def get_stats(self) -> Dict:
        """Get order executor statistics"""
        avg_slippage_bps = self.total_slippage_bps / self.orders_filled if self.orders_filled > 0 else 0.0
        avg_execution_time_ms = self.total_execution_time_ms / self.orders_filled if self.orders_filled > 0 else 0.0
        fill_rate = (self.orders_filled / self.orders_submitted * 100) if self.orders_submitted > 0 else 0.0
        
        return {
            'orders_submitted': self.orders_submitted,
            'orders_filled': self.orders_filled,
            'orders_rejected': self.orders_rejected,
            'fill_rate': fill_rate,
            'avg_slippage_bps': avg_slippage_bps,
            'avg_execution_time_ms': avg_execution_time_ms,
        }


async def _place_exchange_order(
    exchange_client,
    symbol: str,
    side: str,
    size_units: float,
    order_type: OrderType,
    price: float,
) -> Optional[Dict]:
    if exchange_client is None:
        return None
    if hasattr(exchange_client, "place_order"):
        return await exchange_client.place_order(
            symbol=symbol,
            side=side,
            size=size_units,
            order_type=order_type.value,
            price=price if order_type == OrderType.LIMIT else None,
            reduce_only=False,
        )
    if hasattr(exchange_client, "open_position") and order_type == OrderType.MARKET:
        return await exchange_client.open_position(
            symbol=symbol,
            side=side,
            size=size_units,
        )
    return None


def _build_execution_result(
    order_id: str,
    symbol: str,
    side: str,
    order_type: OrderType,
    size_units: float,
    expected_price: float,
    execution_time_ms: float,
    response: Optional[Dict],
) -> ExecutionResult:
    if not response:
        return ExecutionResult(
            order_id=order_id,
            symbol=symbol,
            side=side,
            order_type=order_type,
            size_units=size_units,
            price=expected_price,
            status=OrderStatus.PENDING,
            error_message="Exchange client not implemented",
        )
    status = str(response.get("status") or "").lower()
    if status in {"filled", "closed"}:
        exec_status = OrderStatus.FILLED
    elif status in {"open", "submitted", "new"}:
        exec_status = OrderStatus.SUBMITTED
    elif status in {"canceled", "cancelled"}:
        exec_status = OrderStatus.CANCELLED
    elif status in {"rejected", "rejected"}:
        exec_status = OrderStatus.REJECTED
    else:
        exec_status = OrderStatus.PENDING
    fill_price = response.get("price") or response.get("avg_fill_price") or expected_price
    filled_size = response.get("filled") or response.get("filled_size") or size_units
    return ExecutionResult(
        order_id=response.get("id") or response.get("order_id") or order_id,
        symbol=symbol,
        side=side,
        order_type=order_type,
        size_units=size_units,
        price=expected_price,
        status=exec_status,
        filled_size=float(filled_size) if filled_size is not None else 0.0,
        avg_fill_price=float(fill_price) if fill_price is not None else 0.0,
        execution_time_ms=execution_time_ms,
    )





















