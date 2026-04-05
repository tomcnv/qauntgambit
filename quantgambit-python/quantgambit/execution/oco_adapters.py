"""Exchange adapters that use exchange-specific OCO/trigger orders."""

from __future__ import annotations

from typing import Optional, Any

from quantgambit.execution.live_adapters import LiveExchangeAdapterBase
from quantgambit.observability.logger import log_warning


class OcoLiveAdapterBase(LiveExchangeAdapterBase):
    """Live adapter that delegates protective orders to exchange-native endpoints."""

    async def place_protective_orders(
        self,
        symbol: str,
        side: str,
        size: float,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
        client_order_id: Optional[str] = None,
    ) -> Any:
        if stop_loss is None and take_profit is None:
            return []
        
        # Bybit: Skip separate protective orders - SL/TP is attached natively to the main order
        # via tpslMode="Full" in place_order(). Placing separate orders is redundant and fails.
        exchange_name = getattr(self, "exchange_name", None) or getattr(self.client, "exchange_id", None)
        if exchange_name == "bybit":
            return []
        if stop_loss is not None and take_profit is not None:
            client_order_id = _apply_protective_suffix(client_order_id, "tpsl")
        elif stop_loss is not None:
            client_order_id = _apply_protective_suffix(client_order_id, "sl")
        elif take_profit is not None:
            client_order_id = _apply_protective_suffix(client_order_id, "tp")
        if hasattr(self.client, "place_native_oco"):
            response = await self.client.place_native_oco(
                symbol=symbol,
                side=side,
                size=size,
                stop_loss=stop_loss,
                take_profit=take_profit,
                client_order_id=client_order_id,
            )
            if response is not None:
                return response
        if hasattr(self.client, "place_protective_orders"):
            return await self.client.place_protective_orders(
                symbol=symbol,
                side=side,
                size=size,
                stop_loss=stop_loss,
                take_profit=take_profit,
                client_order_id=client_order_id,
            )
        try:
            exit_side = _exit_side(side)
            results = []
            if stop_loss is not None:
                results.append(
                    await self.client.place_order(
                        symbol=symbol,
                        side=exit_side,
                        size=size,
                        order_type="stop",
                        price=None,
                        reduce_only=True,
                        stop_loss=stop_loss,
                        client_order_id=_apply_protective_suffix(client_order_id, "sl"),
                    )
                )
            if take_profit is not None:
                results.append(
                    await self.client.place_order(
                        symbol=symbol,
                        side=exit_side,
                        size=size,
                        order_type="take_profit",
                        price=None,
                        reduce_only=True,
                        take_profit=take_profit,
                        client_order_id=_apply_protective_suffix(client_order_id, "tp"),
                    )
                )
            return results
        except Exception as exc:
            log_warning("oco_protective_orders_failed", error=str(exc))
            return []


class OkxOcoLiveAdapter(OcoLiveAdapterBase):
    exchange_name = "okx"


class BybitOcoLiveAdapter(OcoLiveAdapterBase):
    exchange_name = "bybit"


class BinanceOcoLiveAdapter(OcoLiveAdapterBase):
    exchange_name = "binance"


def _exit_side(side: str) -> str:
    normalized = (side or "").lower()
    if normalized in {"long", "buy"}:
        return "sell"
    if normalized in {"short", "sell"}:
        return "buy"
    return "sell"


def _apply_protective_suffix(base_id: Optional[str], suffix: str) -> Optional[str]:
    if not base_id:
        return None
    existing = str(base_id).rsplit(":", 1)[-1].lower()
    if existing in {"sl", "tp", "ts", "tpsl", "oco"}:
        return base_id
    return f"{base_id}:{suffix}"
