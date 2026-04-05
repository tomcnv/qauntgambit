"""Order update provider interfaces and payload helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Protocol, Dict, Any


@dataclass
class OrderUpdate:
    symbol: str
    side: str
    size: float
    status: str
    timestamp: float
    order_id: Optional[str] = None
    client_order_id: Optional[str] = None
    fill_price: Optional[float] = None
    fee_usd: Optional[float] = None
    reference_price: Optional[float] = None
    filled_size: Optional[float] = None
    remaining_size: Optional[float] = None
    close_reason: Optional[str] = None
    position_effect: Optional[str] = None

    def to_payload(self) -> Dict[str, Any]:
        payload = {
            "symbol": self.symbol,
            "side": self.side,
            "size": self.size,
            "status": self.status,
            "timestamp": self.timestamp,
            "order_id": self.order_id,
            "client_order_id": self.client_order_id,
            "fill_price": self.fill_price,
            "fee_usd": self.fee_usd,
            "reference_price": self.reference_price,
            "filled_size": self.filled_size,
            "remaining_size": self.remaining_size,
        }
        if self.close_reason:
            payload["close_reason"] = self.close_reason
        if self.position_effect:
            payload["position_effect"] = self.position_effect
        return payload


class OrderUpdateProvider(Protocol):
    async def next_update(self) -> Optional[OrderUpdate]:
        """Return the next private order update, or None if idle."""
