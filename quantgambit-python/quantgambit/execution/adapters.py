"""Exchange and position manager adapters for concrete exchanges."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Optional, Protocol

from quantgambit.execution.manager import ExchangeClient, PositionManager, PositionSnapshot, OrderStatus
from quantgambit.execution.order_statuses import normalize_order_status
from quantgambit.observability.logger import log_warning


class ExchangeAdapterProtocol(Protocol):
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
    ) -> Any:
        """Place an order. Returns True if accepted."""

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

    async def fetch_order_status(self, order_id: str, symbol: str) -> Any:
        """Fetch order status from the exchange."""

    async def fetch_order_status_by_client_id(self, client_order_id: str, symbol: str) -> Any:
        """Fetch order status by client order id."""

    async def cancel_order(self, order_id: str, symbol: str) -> Any:
        """Cancel an order by exchange order id."""

    async def cancel_order_by_client_id(self, client_order_id: str, symbol: str) -> Any:
        """Cancel an order by client order id."""

    async def replace_order(
        self,
        order_id: str,
        symbol: str,
        price: Optional[float] = None,
        size: Optional[float] = None,
    ) -> Any:
        """Replace an order (edit or cancel+new)."""


class FillMetadataProvider(Protocol):
    """Optional adapter protocol to expose last fill metadata."""

    @property
    def last_fill(self):  # pragma: no cover - protocol only
        """Return last fill metadata with fill_price/fee_usd if available."""


class ReferencePriceProvider(Protocol):
    """Market data provider for reference prices."""

    def get_reference_price(self, symbol: str) -> Optional[float]:
        """Return latest reference price for slippage computation."""


@dataclass(frozen=True)
class AdapterConfig:
    order_type: str = "market"


@dataclass(frozen=True)
class OrderPlacementResult:
    success: bool
    status: str
    order_id: Optional[str] = None
    fill_price: Optional[float] = None
    fee_usd: Optional[float] = None
    reason: Optional[str] = None


class BaseExchangeClient(ExchangeClient):
    """Base exchange client that delegates to a concrete adapter."""

    def __init__(
        self,
        adapter: ExchangeAdapterProtocol,
        config: Optional[AdapterConfig] = None,
        reference_prices: Optional[ReferencePriceProvider] = None,
    ):
        self.adapter = adapter
        self.config = config or AdapterConfig()
        self.reference_prices = reference_prices

    async def close_position(
        self,
        symbol: str,
        side: str,
        size: float,
        client_order_id: Optional[str] = None,
        order_type: str = "market",
        limit_price: Optional[float] = None,
        post_only: bool = False,
        time_in_force: Optional[str] = None,
    ) -> OrderStatus:
        exit_side = _exit_side(side)
        order_kwargs = {
            "symbol": symbol,
            "side": exit_side,
            "size": size,
            "order_type": order_type or self.config.order_type,
            "price": limit_price,
            "post_only": post_only,
            "time_in_force": time_in_force,
            "reduce_only": True,
            "client_order_id": client_order_id,
        }
        try:
            supported_params = inspect.signature(self.adapter.place_order).parameters
            filtered_kwargs = {key: value for key, value in order_kwargs.items() if key in supported_params}
        except (TypeError, ValueError):
            filtered_kwargs = order_kwargs
        response = await self.adapter.place_order(**filtered_kwargs)
        placement = _normalize_placement_response(response)
        if (
            isinstance(response, bool)
            and response
            and placement.status == "pending"
            and hasattr(self.adapter, "last_fill")
        ):
            placement = OrderPlacementResult(
                success=placement.success,
                status="filled",
                order_id=placement.order_id,
                fill_price=placement.fill_price,
                fee_usd=placement.fee_usd,
            )
        fill_price = placement.fill_price
        fee_usd = placement.fee_usd
        if (fill_price is None or fee_usd is None) and hasattr(self.adapter, "last_fill"):
            last_fill = getattr(self.adapter, "last_fill")
            fill_price = fill_price or getattr(last_fill, "fill_price", None)
            fee_usd = fee_usd or getattr(last_fill, "fee_usd", None)
        reference_price = None
        if self.reference_prices:
            reference_price = self.reference_prices.get_reference_price(symbol)
        return OrderStatus(
            order_id=placement.order_id,
            status=placement.status,
            fill_price=fill_price,
            fee_usd=fee_usd,
            reference_price=reference_price,
            reason=placement.reason,
        )

    async def open_position(
        self,
        symbol: str,
        side: str,
        size: float,
        order_type: str = "market",
        limit_price: Optional[float] = None,
        post_only: bool = False,
        time_in_force: Optional[str] = None,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
        client_order_id: Optional[str] = None,
    ) -> OrderStatus:
        response = await self.adapter.place_order(
            symbol=symbol,
            side=side,
            size=size,
            order_type=order_type or self.config.order_type,
            price=limit_price,
            post_only=post_only,
            time_in_force=time_in_force,
            reduce_only=False,
            stop_loss=stop_loss,
            take_profit=take_profit,
            client_order_id=client_order_id,
        )
        placement = _normalize_placement_response(response)
        fill_price = placement.fill_price
        fee_usd = placement.fee_usd
        if (fill_price is None or fee_usd is None) and hasattr(self.adapter, "last_fill"):
            last_fill = getattr(self.adapter, "last_fill")
            fill_price = fill_price or getattr(last_fill, "fill_price", None)
            fee_usd = fee_usd or getattr(last_fill, "fee_usd", None)
        reference_price = None
        if self.reference_prices:
            reference_price = self.reference_prices.get_reference_price(symbol)
        return OrderStatus(
            order_id=placement.order_id,
            status=placement.status,
            fill_price=fill_price,
            fee_usd=fee_usd,
            reference_price=reference_price,
            reason=placement.reason,
        )

    async def fetch_positions(self, symbols: Optional[list[str]] = None) -> Optional[list]:
        """Fetch positions from the underlying adapter if supported."""
        if hasattr(self.adapter, "fetch_positions"):
            return await self.adapter.fetch_positions(symbols)
        return None

    async def fetch_executions(
        self,
        symbol: str,
        order_id: Optional[str] = None,
        client_order_id: Optional[str] = None,
        since_ms: Optional[int] = None,
        limit: int = 100,
    ) -> list:
        """Fetch recent executions/trades for a symbol (best-effort)."""
        if hasattr(self.adapter, "fetch_executions"):
            return await self.adapter.fetch_executions(
                symbol=symbol,
                since_ms=since_ms,
                limit=limit,
                order_id=order_id,
                client_order_id=client_order_id,
            )
        return []

    async def place_protective_orders(
        self,
        symbol: str,
        side: str,
        size: float,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
        client_order_id: Optional[str] = None,
    ) -> bool:
        if not stop_loss and not take_profit:
            return True
        
        # Bybit perp: Skip separate protective orders - SL/TP is attached natively to the main order
        # Bybit spot: Must place protective orders separately (SL/TP only works on limit orders)
        exchange_id = getattr(self.adapter, "exchange_id", None) or getattr(getattr(self.adapter, "client", None), "exchange_id", None)
        market_type = getattr(getattr(self.adapter, "client", None), "market_type", "perp")
        if exchange_id == "bybit" and market_type != "spot":
            return True
        
        if hasattr(self.adapter, "place_protective_orders"):
            if stop_loss is not None and take_profit is not None:
                client_order_id = _apply_protective_suffix(client_order_id, "tpsl")
            elif stop_loss is not None:
                client_order_id = _apply_protective_suffix(client_order_id, "sl")
            elif take_profit is not None:
                client_order_id = _apply_protective_suffix(client_order_id, "tp")
            response = await self.adapter.place_protective_orders(
                symbol=symbol,
                side=side,
                size=size,
                stop_loss=stop_loss,
                take_profit=take_profit,
                client_order_id=client_order_id,
            )
            return bool(getattr(response, "success", response if response is not None else True))
        
        # Bybit spot: Use the client's _place_spot_tpsl method
        client = getattr(self.adapter, "client", None)
        if exchange_id == "bybit" and market_type == "spot" and client and hasattr(client, "_place_spot_tpsl"):
            try:
                await client._place_spot_tpsl(
                    symbol=symbol,
                    side=side,
                    size=size,
                    stop_loss=stop_loss,
                    take_profit=take_profit,
                    parent_order_id=client_order_id or "manual",
                )
                return True
            except Exception as exc:
                log_warning("bybit_spot_tpsl_failed", symbol=symbol, error=str(exc))
                return False
        
        exit_side = _exit_side(side)
        try:
            if stop_loss is not None:
                await self.adapter.place_order(
                    symbol=symbol,
                    side=exit_side,
                    size=size,
                    order_type="stop",
                    price=None,
                    reduce_only=True,
                    stop_loss=stop_loss,
                    client_order_id=_apply_protective_suffix(client_order_id, "sl"),
                )
            if take_profit is not None:
                await self.adapter.place_order(
                    symbol=symbol,
                    side=exit_side,
                    size=size,
                    order_type="take_profit",
                    price=None,
                    reduce_only=True,
                    take_profit=take_profit,
                    client_order_id=_apply_protective_suffix(client_order_id, "tp"),
                )
        except Exception as exc:
            log_warning("protective_orders_unsupported", symbol=symbol, error=str(exc))
            return False
        return True

    async def fetch_balance(self, currency: str = "USDT") -> Optional[float]:
        """Fetch total account equity from the exchange.
        
        Delegates to the underlying adapter if it supports balance fetching.
        Returns None if balance fetching is not supported.
        """
        if hasattr(self.adapter, "fetch_balance"):
            return await self.adapter.fetch_balance(currency)
        return None

    async def fetch_order_status(self, order_id: str, symbol: str) -> Optional[OrderStatus]:
        if not hasattr(self.adapter, "fetch_order_status"):
            return None
        response = await self.adapter.fetch_order_status(order_id, symbol)
        placement = _normalize_placement_response(response, default_order_id=order_id)
        reference_price = None
        if self.reference_prices:
            reference_price = self.reference_prices.get_reference_price(symbol)
        return OrderStatus(
            order_id=placement.order_id,
            status=placement.status,
            fill_price=placement.fill_price,
            fee_usd=placement.fee_usd,
            reference_price=reference_price,
            reason=placement.reason,
        )

    async def fetch_order_status_by_client_id(self, client_order_id: str, symbol: str) -> Optional[OrderStatus]:
        if not hasattr(self.adapter, "fetch_order_status_by_client_id"):
            return None
        response = await self.adapter.fetch_order_status_by_client_id(client_order_id, symbol)
        placement = _normalize_placement_response(response, default_order_id=client_order_id)
        reference_price = None
        if self.reference_prices:
            reference_price = self.reference_prices.get_reference_price(symbol)
        return OrderStatus(
            order_id=placement.order_id,
            status=placement.status,
            fill_price=placement.fill_price,
            fee_usd=placement.fee_usd,
            reference_price=reference_price,
            reason=placement.reason,
        )

    async def cancel_order(
        self,
        order_id: Optional[str],
        client_order_id: Optional[str],
        symbol: Optional[str],
    ) -> OrderStatus:
        def _is_cancel_race(exc: Exception) -> bool:
            msg = str(exc or "").lower()
            return (
                "order not exists" in msg
                or "too late to cancel" in msg
                or "already closed" in msg
                or "already canceled" in msg
                or "already cancelled" in msg
            )

        if not symbol:
            return OrderStatus(order_id=order_id or client_order_id, status="rejected", reason="symbol_required")
        if order_id and hasattr(self.adapter, "cancel_order"):
            try:
                response = await self.adapter.cancel_order(order_id, symbol)
            except Exception as exc:
                if _is_cancel_race(exc):
                    return OrderStatus(order_id=order_id, status="canceled", reason="cancel_race_already_closed")
                raise
            placement = _normalize_placement_response(response, default_order_id=order_id)
            status = placement.status
            if status == "filled":
                status = "canceled"
            return OrderStatus(order_id=placement.order_id, status=status, reason="manual_cancel")
        if client_order_id and hasattr(self.adapter, "cancel_order_by_client_id"):
            try:
                response = await self.adapter.cancel_order_by_client_id(client_order_id, symbol)
            except Exception as exc:
                if _is_cancel_race(exc):
                    return OrderStatus(order_id=client_order_id, status="canceled", reason="cancel_race_already_closed")
                raise
            placement = _normalize_placement_response(response, default_order_id=client_order_id)
            status = placement.status
            if status == "filled":
                status = "canceled"
            return OrderStatus(order_id=placement.order_id, status=status, reason="manual_cancel")
        if client_order_id and hasattr(self.adapter, "fetch_order_status_by_client_id"):
            response = await self.adapter.fetch_order_status_by_client_id(client_order_id, symbol)
            placement = _normalize_placement_response(response, default_order_id=client_order_id)
            if placement.order_id and hasattr(self.adapter, "cancel_order"):
                try:
                    cancel_response = await self.adapter.cancel_order(placement.order_id, symbol)
                except Exception as exc:
                    if _is_cancel_race(exc):
                        return OrderStatus(order_id=placement.order_id, status="canceled", reason="cancel_race_already_closed")
                    raise
                cancel_status = _normalize_placement_response(cancel_response, default_order_id=placement.order_id)
                status = cancel_status.status
                if status == "filled":
                    status = "canceled"
                return OrderStatus(order_id=cancel_status.order_id, status=status, reason="manual_cancel")
        return OrderStatus(order_id=order_id or client_order_id, status="rejected", reason="cancel_not_supported")

    async def replace_order(
        self,
        order_id: Optional[str],
        client_order_id: Optional[str],
        symbol: Optional[str],
        price: Optional[float],
        size: Optional[float],
    ) -> OrderStatus:
        if not symbol:
            return OrderStatus(order_id=order_id or client_order_id, status="rejected", reason="symbol_required")
        if order_id and hasattr(self.adapter, "replace_order"):
            response = await self.adapter.replace_order(order_id, symbol, price=price, size=size)
            placement = _normalize_placement_response(response, default_order_id=order_id)
            return OrderStatus(order_id=placement.order_id, status=placement.status, reason="manual_replace")
        if client_order_id and hasattr(self.adapter, "fetch_order_status_by_client_id"):
            response = await self.adapter.fetch_order_status_by_client_id(client_order_id, symbol)
            placement = _normalize_placement_response(response, default_order_id=client_order_id)
            if placement.order_id and hasattr(self.adapter, "replace_order"):
                replace_response = await self.adapter.replace_order(placement.order_id, symbol, price=price, size=size)
                replace_status = _normalize_placement_response(replace_response, default_order_id=placement.order_id)
                return OrderStatus(order_id=replace_status.order_id, status=replace_status.status, reason="manual_replace")
        return OrderStatus(order_id=order_id or client_order_id, status="rejected", reason="replace_not_supported")


class OkxExchangeClient(BaseExchangeClient):
    """OKX exchange adapter wrapper."""

    exchange_name = "okx"


class BybitExchangeClient(BaseExchangeClient):
    """Bybit exchange adapter wrapper."""

    exchange_name = "bybit"


class BinanceExchangeClient(BaseExchangeClient):
    """Binance exchange adapter wrapper."""

    exchange_name = "binance"


class PositionStoreProtocol(Protocol):
    async def list_positions(self) -> List[PositionSnapshot]:
        """Return open positions as PositionSnapshot list."""

    async def upsert_position(self, snapshot: PositionSnapshot, accumulate: bool = True) -> None:
        """Insert or update a position snapshot.
        
        If accumulate=True (default), adds to existing position on same side.
        If accumulate=False, replaces position entirely.
        """

    async def mark_closing(self, symbol: str, reason: str) -> None:
        """Mark position as closing."""

    async def finalize_close(self, symbol: str) -> None:
        """Finalize a position close."""


class PositionManagerAdapter(PositionManager):
    """Position manager adapter delegating to a position store."""

    def __init__(self, store: PositionStoreProtocol):
        self.store = store

    async def list_open_positions(self) -> List[PositionSnapshot]:
        return await self.store.list_positions()

    async def list_positions(self) -> List[PositionSnapshot]:
        return await self.store.list_positions()

    async def upsert_position(self, snapshot: PositionSnapshot, accumulate: bool = True) -> None:
        """Update or create a position.
        
        By default accumulates position size for same-side fills.
        """
        await self.store.upsert_position(snapshot, accumulate=accumulate)

    async def mark_closing(self, symbol: str, reason: str) -> None:
        await self.store.mark_closing(symbol, reason)

    async def finalize_close(self, symbol: str) -> None:
        await self.store.finalize_close(symbol)

    def update_mfe_mae(self, symbol: str, current_price: float) -> None:
        """Update MFE/MAE for a position based on current price."""
        if hasattr(self.store, "update_mfe_mae"):
            self.store.update_mfe_mae(symbol, current_price)


def _exit_side(side: str) -> str:
    normalized = (side or "").lower()
    if normalized in {"long", "buy"}:
        return "sell"
    if normalized in {"short", "sell"}:
        return "buy"
    return "sell"


def _normalize_placement_response(response: Any, default_order_id: Optional[str] = None) -> OrderPlacementResult:
    if isinstance(response, OrderPlacementResult):
        return response
    if response is None:
        return OrderPlacementResult(success=False, status="rejected", order_id=default_order_id)
    if isinstance(response, bool):
        return OrderPlacementResult(
            success=response,
            status="pending" if response else "rejected",
            order_id=default_order_id,
        )
    if isinstance(response, dict):
        success = response.get("success", True)
        raw_status = response.get("status")
        status = normalize_order_status(raw_status) if raw_status is not None else ("pending" if success else "rejected")
        order_id = response.get("order_id") or response.get("ordId") or response.get("orderId") or default_order_id
        fill_price = response.get("fill_price") or response.get("avg_fill_price") or response.get("avgPx")
        fee_usd = response.get("fee_usd") or response.get("fee") or response.get("commission")
        reason = response.get("reason") or response.get("message") or response.get("retMsg") or response.get("error")
        return OrderPlacementResult(
            success=bool(success),
            status=str(status).lower(),
            order_id=order_id,
            fill_price=_to_float(fill_price),
            fee_usd=_to_float(fee_usd),
            reason=str(reason) if reason is not None else None,
        )
    success = getattr(response, "success", True)
    raw_status = getattr(response, "status", None)
    status = normalize_order_status(raw_status) if raw_status is not None else ("pending" if success else "rejected")
    order_id = getattr(response, "order_id", None) or getattr(response, "ordId", None) or default_order_id
    fill_price = getattr(response, "fill_price", None) or getattr(response, "avg_fill_price", None)
    fee_usd = getattr(response, "fee_usd", None)
    reason = (
        getattr(response, "reason", None)
        or getattr(response, "message", None)
        or getattr(response, "retMsg", None)
        or getattr(response, "error", None)
    )
    return OrderPlacementResult(
        success=bool(success),
        status=str(status).lower(),
        order_id=order_id,
        fill_price=_to_float(fill_price),
        fee_usd=_to_float(fee_usd),
        reason=str(reason) if reason is not None else None,
    )


def _to_float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _protective_client_id(base_id: Optional[str], suffix: str) -> Optional[str]:
    if not base_id:
        return None
    return f"{base_id}:{suffix}"


def _apply_protective_suffix(base_id: Optional[str], suffix: str) -> Optional[str]:
    if not base_id:
        return None
    existing = str(base_id).rsplit(":", 1)[-1].lower()
    if existing in {"sl", "tp", "ts", "tpsl", "oco"}:
        return base_id
    return f"{base_id}:{suffix}"
import inspect
