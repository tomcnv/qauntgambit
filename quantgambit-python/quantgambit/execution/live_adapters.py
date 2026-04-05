"""Live exchange adapter wrappers that expose last_fill metadata."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Protocol, Any

from quantgambit.observability.logger import log_warning
from quantgambit.execution.order_statuses import normalize_order_status
from quantgambit.execution.sdk_clients import OrderResponse
from quantgambit.execution.adapters import OrderPlacementResult

@dataclass(frozen=True)
class FillMetadata:
    fill_price: Optional[float]
    fee_usd: Optional[float]
    order_id: Optional[str] = None
    status: Optional[str] = None


class LiveExchangeClientProtocol(Protocol):
    async def place_order(self, **kwargs: Any) -> Any:
        """Place an order with exchange-specific parameters."""

    async def fetch_order_status(self, order_id: str, symbol: str) -> Any:
        """Fetch order status from exchange."""

    async def cancel_order(self, order_id: str, symbol: str) -> Any:
        """Cancel an order by exchange id."""

    async def replace_order(self, order_id: str, symbol: str, price: Optional[float] = None, size: Optional[float] = None) -> Any:
        """Replace an order if supported."""


class LiveExchangeAdapterBase:
    """Base adapter that captures fill metadata."""

    def __init__(self, client: LiveExchangeClientProtocol):
        self.client = client
        self.last_fill: Optional[FillMetadata] = None

    async def place_order(
        self,
        symbol: str,
        side: str,
        size: float,
        order_type: str,
        price: Optional[float] = None,
        post_only: bool = False,
        time_in_force: Optional[str] = None,
        reduce_only: bool = False,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
        client_order_id: Optional[str] = None,
    ) -> OrderPlacementResult:
        response = await self.client.place_order(
            symbol=symbol,
            side=side,
            size=size,
            order_type=order_type,
            price=price,
            post_only=post_only,
            time_in_force=time_in_force,
            reduce_only=reduce_only,
            stop_loss=stop_loss,
            take_profit=take_profit,
            client_order_id=client_order_id,
        )
        if isinstance(response, OrderResponse):
            success = response.success
            fill_price = response.fill_price
            fee_usd = response.fee_usd
            order_id = response.order_id
            status = response.status
        else:
            success, fill_price, fee_usd, order_id, status = self._extract_fill(response)
        self.last_fill = FillMetadata(
            fill_price=fill_price,
            fee_usd=fee_usd,
            order_id=order_id,
            status=status,
        )
        normalized_status = (status or ("filled" if success else "rejected")).lower()
        return OrderPlacementResult(
            success=bool(success),
            status=normalized_status,
            order_id=order_id,
            fill_price=fill_price,
            fee_usd=fee_usd,
        )

    async def fetch_order_status(self, order_id: str, symbol: str) -> Any:
        if not hasattr(self.client, "fetch_order_status"):
            return None
        return await self.client.fetch_order_status(order_id, symbol)

    async def fetch_order_status_by_client_id(self, client_order_id: str, symbol: str) -> Any:
        if not hasattr(self.client, "fetch_order_status_by_client_id"):
            return None
        return await self.client.fetch_order_status_by_client_id(client_order_id, symbol)

    async def cancel_order(self, order_id: str, symbol: str) -> Any:
        if not hasattr(self.client, "cancel_order"):
            return None
        return await self.client.cancel_order(order_id, symbol)

    async def cancel_order_by_client_id(self, client_order_id: str, symbol: str) -> Any:
        if not hasattr(self.client, "cancel_order_by_client_id"):
            return None
        return await self.client.cancel_order_by_client_id(client_order_id, symbol)

    async def replace_order(
        self,
        order_id: str,
        symbol: str,
        price: Optional[float] = None,
        size: Optional[float] = None,
    ) -> Any:
        if not hasattr(self.client, "replace_order"):
            return None
        return await self.client.replace_order(order_id, symbol, price=price, size=size)

    async def fetch_balance(self, currency: str = "USDT") -> Optional[float]:
        """Fetch account equity from exchange.
        
        Delegates to the underlying CCXT client's fetch_balance method.
        """
        if hasattr(self.client, "fetch_balance"):
            return await self.client.fetch_balance(currency)
        return None

    async def fetch_positions(self, symbols: Optional[list[str]] = None) -> Optional[list]:
        """Fetch open positions from exchange (if supported by client)."""
        if hasattr(self.client, "fetch_positions"):
            return await self.client.fetch_positions(symbols)
        return None

    async def fetch_executions(
        self,
        symbol: str,
        since_ms: Optional[int] = None,
        limit: int = 100,
        order_id: Optional[str] = None,
        client_order_id: Optional[str] = None,
    ) -> list:
        """Fetch recent executions/trades for a symbol (best-effort)."""
        if hasattr(self.client, "fetch_executions"):
            return await self.client.fetch_executions(
                symbol=symbol,
                since_ms=since_ms,
                limit=limit,
                order_id=order_id,
                client_order_id=client_order_id,
            )
        return []

    def _extract_fill(self, response: Any) -> tuple[bool, Optional[float], Optional[float], Optional[str], Optional[str]]:
        return _extract_fill(response)


class OkxLiveAdapter(LiveExchangeAdapterBase):
    exchange_name = "okx"

    def _extract_fill(self, response: Any) -> tuple[bool, Optional[float], Optional[float], Optional[str], Optional[str]]:
        return _extract_okx_fill(response)

    async def fetch_order_status(self, order_id: str, symbol: str) -> Any:
        if not hasattr(self.client, "fetch_order_status"):
            return None
        response = await self.client.fetch_order_status(order_id, symbol)
        return _parse_okx_order_status(response, order_id)

    async def fetch_order_status_by_client_id(self, client_order_id: str, symbol: str) -> Any:
        if not hasattr(self.client, "fetch_order_status_by_client_id"):
            return None
        response = await self.client.fetch_order_status_by_client_id(client_order_id, symbol)
        return _parse_okx_order_status(response, client_order_id)


class BybitLiveAdapter(LiveExchangeAdapterBase):
    exchange_name = "bybit"

    def _extract_fill(self, response: Any) -> tuple[bool, Optional[float], Optional[float], Optional[str], Optional[str]]:
        return _extract_bybit_fill(response)

    async def fetch_order_status(self, order_id: str, symbol: str) -> Any:
        if not hasattr(self.client, "fetch_order_status"):
            return None
        response = await self.client.fetch_order_status(order_id, symbol)
        return _parse_bybit_order_status(response, order_id)

    async def fetch_order_status_by_client_id(self, client_order_id: str, symbol: str) -> Any:
        if not hasattr(self.client, "fetch_order_status_by_client_id"):
            return None
        response = await self.client.fetch_order_status_by_client_id(client_order_id, symbol)
        return _parse_bybit_order_status(response, client_order_id)


class BinanceLiveAdapter(LiveExchangeAdapterBase):
    exchange_name = "binance"

    def _extract_fill(self, response: Any) -> tuple[bool, Optional[float], Optional[float], Optional[str], Optional[str]]:
        return _extract_binance_fill(response)

    async def fetch_order_status(self, order_id: str, symbol: str) -> Any:
        if not hasattr(self.client, "fetch_order_status"):
            return None
        response = await self.client.fetch_order_status(order_id, symbol)
        return _parse_binance_order_status(response, order_id)

    async def fetch_order_status_by_client_id(self, client_order_id: str, symbol: str) -> Any:
        if not hasattr(self.client, "fetch_order_status_by_client_id"):
            return None
        response = await self.client.fetch_order_status_by_client_id(client_order_id, symbol)
        return _parse_binance_order_status(response, client_order_id)


class DeepTraderAdaptorWrapper(LiveExchangeAdapterBase):
    """Adapter wrapper for legacy ExchangeAdaptor results."""

    def _extract_fill(self, response: Any) -> tuple[bool, Optional[float], Optional[float], Optional[str], Optional[str]]:
        try:
            success = getattr(response, "success", True)
            fill_price = getattr(response, "avg_fill_price", None) or getattr(response, "price", None)
            fee_usd = None
            order_id = getattr(response, "order_id", None)
            status = getattr(response, "status", None)
            raw = getattr(response, "raw_response", None)
            if isinstance(raw, dict):
                fee_usd = raw.get("fee") or raw.get("feeUsd") or raw.get("commission")
                order_id = order_id or raw.get("ordId") or raw.get("orderId")
                status = status or raw.get("status") or raw.get("state")
            return bool(success), _to_float(fill_price), _to_float(fee_usd), order_id, _normalize_status(status, success)
        except Exception as exc:
            log_warning("fill_parse_failed", error=str(exc))
            return _extract_fill(response)


class OkxAdaptorWrapper(DeepTraderAdaptorWrapper):
    exchange_name = "okx"


class BybitAdaptorWrapper(DeepTraderAdaptorWrapper):
    exchange_name = "bybit"


class BinanceAdaptorWrapper(DeepTraderAdaptorWrapper):
    exchange_name = "binance"


def _extract_fee(fee_data: Any) -> Optional[float]:
    """Extract fee value from various formats (CCXT dict, raw value, etc.)."""
    if fee_data is None:
        return None
    if isinstance(fee_data, dict):
        # CCXT returns fee as {"cost": 0.05, "currency": "USDT"}
        return _to_float(fee_data.get("cost"))
    return _to_float(fee_data)


def _extract_fill(response: Any) -> tuple[bool, Optional[float], Optional[float]]:
    """Extract success/fill/fee from common exchange responses."""
    if response is None:
        return False, None, None, None, None
    if isinstance(response, dict):
        success = response.get("success", True)
        fill_price = response.get("fill_price") or response.get("avgPx") or response.get("average") or response.get("price")
        fee_usd = _extract_fee(response.get("fee_usd") or response.get("fee"))
        order_id = response.get("order_id") or response.get("ordId") or response.get("orderId") or response.get("id")
        status = response.get("status") or response.get("state")
        return bool(success), _to_float(fill_price), fee_usd, order_id, _normalize_status(status, success)
    success = getattr(response, "success", True)
    fill_price = getattr(response, "fill_price", None) or getattr(response, "avgPx", None) or getattr(response, "average", None)
    fee_usd = _extract_fee(getattr(response, "fee_usd", None) or getattr(response, "fee", None))
    order_id = getattr(response, "order_id", None) or getattr(response, "ordId", None) or getattr(response, "id", None)
    status = getattr(response, "status", None)
    return bool(success), _to_float(fill_price), fee_usd, order_id, _normalize_status(status, success)


def _extract_okx_fill(response: Any) -> tuple[bool, Optional[float], Optional[float], Optional[str], Optional[str]]:
    if isinstance(response, dict):
        # CCXT unified format - check for CCXT fields first
        if "id" in response or "average" in response:
            success = response.get("status") not in ("rejected", "canceled", "expired")
            fill_price = response.get("average") or response.get("price")
            fee_usd = _extract_fee(response.get("fee"))
            order_id = response.get("id") or response.get("orderId")
            status = response.get("status")
            return bool(success), _to_float(fill_price), fee_usd, order_id, _normalize_status(status, success)
        # Raw OKX format
        data = response.get("data") or []
        success = response.get("success", response.get("code") in (None, "0"))
        if data and isinstance(data, list):
            item = data[0]
            fill_price = item.get("fillPx") or item.get("avgPx") or item.get("px")
            fee_usd = _extract_fee(item.get("fee") or item.get("feeUsd"))
            order_id = item.get("ordId") or item.get("orderId")
            status = item.get("state") or item.get("status")
            return bool(success), _to_float(fill_price), fee_usd, order_id, _normalize_status(status, success)
    return _extract_fill(response)


def _extract_bybit_fill(response: Any) -> tuple[bool, Optional[float], Optional[float], Optional[str], Optional[str]]:
    if isinstance(response, dict):
        # CCXT unified format - check for CCXT fields first
        if "id" in response or "average" in response or "filled" in response:
            success = response.get("status") not in ("rejected", "canceled", "expired", "closed")
            fill_price = response.get("average") or response.get("price")
            fee_usd = _extract_fee(response.get("fee"))
            order_id = response.get("id") or response.get("order_id")
            status = response.get("status")
            # Also check info for raw Bybit data
            info = response.get("info") or {}
            if not fill_price and isinstance(info, dict):
                avg_price = _to_float(info.get("avgPrice") or info.get("avg_price"))
                if not avg_price or avg_price == 0:
                    cum_value = _to_float(info.get("cumExecValue") or info.get("cumExecQuote") or info.get("cumExecValueE8"))
                    cum_qty = _to_float(info.get("cumExecQty"))
                    if cum_value is not None and info.get("cumExecValueE8"):
                        cum_value = cum_value / 1e8
                    if cum_value and cum_qty:
                        avg_price = cum_value / cum_qty
                fill_price = avg_price or info.get("price")
            if not fee_usd and isinstance(info, dict):
                fee_usd = _to_float(info.get("cumExecFee")) or _to_float(info.get("fee"))
            if success or status in ("filled", "closed"):
                success = True
            return bool(success), _to_float(fill_price), fee_usd, order_id, _normalize_status(status, success)
        
        # Raw Bybit API format
        success = response.get("retCode") in (0, "0", None)
        result = response.get("result") or {}
        lst = result.get("list") or []
        if lst:
            item = lst[0]
            avg_price = _to_float(item.get("avgPrice") or item.get("avg_price"))
            if not avg_price or avg_price == 0:
                cum_value = _to_float(item.get("cumExecValue") or item.get("cumExecQuote") or item.get("cumExecValueE8"))
                cum_qty = _to_float(item.get("cumExecQty"))
                if cum_value is not None and item.get("cumExecValueE8"):
                    cum_value = cum_value / 1e8
                if cum_value and cum_qty:
                    avg_price = cum_value / cum_qty
            fill_price = avg_price or item.get("price")
            fee_usd = item.get("cumExecFee") or item.get("fee")
            order_id = item.get("orderId") or item.get("order_id")
            status = item.get("orderStatus") or item.get("status")
            return bool(success), _to_float(fill_price), _to_float(fee_usd), order_id, _normalize_status(status, success)
    return _extract_fill(response)


def _extract_binance_fill(response: Any) -> tuple[bool, Optional[float], Optional[float], Optional[str], Optional[str]]:
    if isinstance(response, dict):
        success = response.get("status") not in ("REJECTED", "EXPIRED")
        fills = response.get("fills") or []
        if fills:
            fill = fills[0]
            fill_price = fill.get("price")
            fee_usd = fill.get("commission") or response.get("commission")
            order_id = response.get("orderId") or response.get("order_id")
            status = response.get("status")
            return bool(success), _to_float(fill_price), _to_float(fee_usd), order_id, _normalize_status(status, success)
        fill_price = response.get("avgPrice") or response.get("price")
        fee_usd = response.get("commission") or response.get("fee")
        order_id = response.get("orderId") or response.get("order_id")
        status = response.get("status")
        return bool(success), _to_float(fill_price), _to_float(fee_usd), order_id, _normalize_status(status, success)
    return _extract_fill(response)


def _to_float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalize_status(status: Optional[str], success: bool) -> Optional[str]:
    if status is None:
        # Missing status in placement ack means "accepted", not "filled".
        # Filled should only be emitted from explicit exchange fill states.
        return "pending" if success else "rejected"
    return normalize_order_status(str(status))


def _parse_okx_order_status(response: Any, order_id: str) -> Optional[dict]:
    if response is None:
        return None
    if isinstance(response, dict) and "id" in response and "status" in response:
        return _parse_ccxt_order_status(response, order_id)
    if isinstance(response, dict):
        data = response.get("data") or []
        if data and isinstance(data, list):
            item = data[0]
            status = item.get("state") or item.get("status")
            fill_price = item.get("avgPx") or item.get("fillPx")
            fee_usd = item.get("fee") or item.get("feeUsd")
            return {
                "order_id": item.get("ordId") or order_id,
                "status": status,
                "fill_price": fill_price,
                "fee_usd": fee_usd,
                "success": response.get("code") in (None, "0"),
            }
    return {"order_id": order_id, "status": None, "success": False}


def _parse_bybit_order_status(response: Any, order_id: str) -> Optional[dict]:
    if response is None:
        return None
    if isinstance(response, dict) and "id" in response and "status" in response:
        return _parse_ccxt_order_status(response, order_id)
    if isinstance(response, dict):
        result = response.get("result") or {}
        lst = result.get("list") or []
        if lst:
            item = lst[0]
            status = item.get("orderStatus") or item.get("status")
            fill_price = item.get("avgPrice") or item.get("price")
            fee_usd = item.get("cumExecFee") or item.get("fee")
            return {
                "order_id": item.get("orderId") or order_id,
                "status": status,
                "fill_price": fill_price,
                "fee_usd": fee_usd,
                "success": response.get("retCode") in (0, "0", None),
            }
    return {"order_id": order_id, "status": None, "success": False}


def _parse_binance_order_status(response: Any, order_id: str) -> Optional[dict]:
    if response is None:
        return None
    if isinstance(response, dict) and "id" in response and "status" in response:
        return _parse_ccxt_order_status(response, order_id)
    if isinstance(response, dict):
        status = response.get("status")
        fill_price = response.get("avgPrice") or response.get("price")
        fee_usd = response.get("commission")
        return {
            "order_id": response.get("orderId") or order_id,
            "status": status,
            "fill_price": fill_price,
            "fee_usd": fee_usd,
            "success": response.get("status") not in ("REJECTED", "EXPIRED"),
        }
    return {"order_id": order_id, "status": None, "success": False}


def _parse_ccxt_order_status(response: dict, order_id: str) -> dict:
    status = response.get("status")
    fee = response.get("fee") or {}
    fee_cost = fee.get("cost") if isinstance(fee, dict) else fee
    return {
        "order_id": response.get("id") or response.get("orderId") or order_id,
        "status": status,
        "fill_price": response.get("average") or response.get("price"),
        "fee_usd": fee_cost,
        "success": normalize_order_status(status) not in {"rejected", "canceled", "expired"},
    }
