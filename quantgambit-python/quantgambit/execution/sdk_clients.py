"""SDK client wrappers for OKX/Bybit/Binance order placement."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, Protocol

from quantgambit.observability.logger import log_error
from quantgambit.observability.telemetry import TelemetryPipeline, TelemetryContext


@dataclass(frozen=True)
class OrderResponse:
    success: bool
    fill_price: Optional[float]
    fee_usd: Optional[float]
    order_id: Optional[str] = None
    status: Optional[str] = None
    raw: Any = None


class ExchangeOrderClient(Protocol):
    async def place_order(
        self,
        symbol: str,
        side: str,
        size: float,
        order_type: str,
        price: Optional[float] = None,
        post_only: bool = False,
        time_in_force: Optional[str] = None,
        client_order_id: Optional[str] = None,
        reduce_only: bool = False,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
    ) -> Any:
        """Place an order and return exchange-specific response."""

    async def fetch_order_status(self, order_id: str, symbol: str) -> Any:
        """Fetch order status from the exchange."""

    async def place_protective_orders(
        self,
        symbol: str,
        side: str,
        size: float,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
        client_order_id: Optional[str] = None,
    ) -> Any:
        """Place exchange-native protective orders if supported."""


class BaseSdkClient:
    """Base client that normalizes order responses."""

    def __init__(
        self,
        adaptor: ExchangeOrderClient,
        telemetry: Optional[TelemetryPipeline] = None,
        telemetry_context: Optional[TelemetryContext] = None,
        emit_telemetry: bool = False,
    ):
        self.adaptor = adaptor
        self.telemetry = telemetry
        self.telemetry_context = telemetry_context
        self.emit_telemetry = emit_telemetry

    async def place_order(
        self,
        symbol: str,
        side: str,
        size: float,
        order_type: str,
        price: Optional[float] = None,
        post_only: bool = False,
        time_in_force: Optional[str] = None,
        client_order_id: Optional[str] = None,
        reduce_only: bool = False,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
    ) -> OrderResponse:
        try:
            response = await self.adaptor.place_order(
                symbol=symbol,
                side=side,
                size=size,
                order_type=order_type,
                price=price,
                post_only=post_only,
                time_in_force=time_in_force,
                client_order_id=client_order_id,
                reduce_only=reduce_only,
                stop_loss=stop_loss,
                take_profit=take_profit,
            )
        except Exception as exc:
            log_error("sdk_place_order_failed", error=str(exc))
            return OrderResponse(success=False, fill_price=None, fee_usd=None, raw=None)
        result = _map_order_response(response)
        if self.emit_telemetry and self.telemetry and self.telemetry_context:
            await self.telemetry.publish_order(
                ctx=self.telemetry_context,
                symbol=symbol,
                payload={
                    "side": side,
                    "size": size,
                    "order_type": order_type,
                    "status": result.status or ("filled" if result.success else "rejected"),
                    "fill_price": result.fill_price,
                    "fee_usd": result.fee_usd,
                    "client_order_id": client_order_id,
                    "order_id": result.order_id,
                },
            )
        return result

    async def fetch_order_status(self, order_id: str, symbol: str) -> Any:
        if hasattr(self.adaptor, "fetch_order_status"):
            return await self.adaptor.fetch_order_status(order_id, symbol)
        return None

    async def place_protective_orders(
        self,
        symbol: str,
        side: str,
        size: float,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
        client_order_id: Optional[str] = None,
    ) -> Any:
        if hasattr(self.adaptor, "place_protective_orders"):
            return await self.adaptor.place_protective_orders(
                symbol=symbol,
                side=side,
                size=size,
                stop_loss=stop_loss,
                take_profit=take_profit,
                client_order_id=client_order_id,
            )
        return None


class OkxSdkClient(BaseSdkClient):
    exchange_name = "okx"


class BybitSdkClient(BaseSdkClient):
    exchange_name = "bybit"


class BinanceSdkClient(BaseSdkClient):
    exchange_name = "binance"


def _map_order_response(response: Any) -> OrderResponse:
    if response is None:
        return OrderResponse(success=False, fill_price=None, fee_usd=None, raw=None)
    if isinstance(response, dict):
        success = response.get("success", True)
        fill_price = response.get("avg_fill_price") or response.get("fill_price") or response.get("avgPx")
        fee_usd = response.get("fee_usd") or response.get("fee") or response.get("commission")
        order_id = response.get("order_id") or response.get("ordId") or response.get("orderId")
        status = response.get("status") or response.get("state")
        return OrderResponse(
            success=bool(success),
            fill_price=_to_float(fill_price),
            fee_usd=_to_float(fee_usd),
            order_id=order_id,
            status=status,
            raw=response,
        )
    success = getattr(response, "success", True)
    fill_price = getattr(response, "avg_fill_price", None) or getattr(response, "avgPx", None)
    fee_usd = getattr(response, "fee_usd", None)
    order_id = getattr(response, "order_id", None) or getattr(response, "ordId", None)
    status = getattr(response, "status", None)
    return OrderResponse(
        success=bool(success),
        fill_price=_to_float(fill_price),
        fee_usd=_to_float(fee_usd),
        order_id=order_id,
        status=status,
        raw=response,
    )


def _to_float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
