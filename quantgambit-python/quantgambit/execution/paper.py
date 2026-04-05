"""Paper trading adapter that mirrors real execution interfaces."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional
import asyncio
import random
import time
import uuid

from quantgambit.execution.adapters import ExchangeAdapterProtocol, OrderPlacementResult
from quantgambit.storage.redis_streams import Event, RedisStreamsClient
from quantgambit.ingest.time_utils import now_recv_us


@dataclass(frozen=True)
class PaperTradingConfig:
    enable_latency: bool = True
    min_latency_ms: int = 5
    max_latency_ms: int = 25
    slippage_bps: float = 0.0
    emit_events: bool = True


@dataclass(frozen=True)
class PaperFill:
    symbol: str
    side: str
    size: float
    order_type: str
    price: Optional[float]
    fill_price: Optional[float]
    reduce_only: bool
    stop_loss: Optional[float]
    take_profit: Optional[float]
    order_id: str
    fee_usd: Optional[float]
    timestamp: float


class PaperFillEngine:
    """Records simulated fills for paper trading."""

    def __init__(self) -> None:
        self.fills: List[PaperFill] = []

    def record_fill(self, fill: PaperFill) -> None:
        self.fills.append(fill)


class PaperExchangeAdapter(ExchangeAdapterProtocol):
    """Paper trading adapter implementing the same interface as real adapters."""

    def __init__(
        self,
        fill_engine: PaperFillEngine,
        config: Optional[PaperTradingConfig] = None,
        redis_client: Optional[RedisStreamsClient] = None,
        bot_id: Optional[str] = None,
        exchange: str = "paper",
        event_stream: str = "events:order",
    ):
        self.fill_engine = fill_engine
        self.config = config or PaperTradingConfig()
        self.redis_client = redis_client
        self.bot_id = bot_id or "paper-bot"
        self.exchange = exchange
        self.event_stream = event_stream
        self.last_fill: Optional[PaperFill] = None
        self._orders: dict[str, PaperFill] = {}

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
        if self.config.enable_latency:
            delay_ms = _clamp_latency(self.config.min_latency_ms, self.config.max_latency_ms)
            await asyncio.sleep(delay_ms / 1000.0)

        fill_price = _apply_slippage(price, side, self.config.slippage_bps)
        order_id = client_order_id or str(uuid.uuid4())

        fill = PaperFill(
            symbol=symbol,
            side=side,
            size=size,
            order_type=order_type,
            price=price,
            fill_price=fill_price,
            reduce_only=reduce_only,
            stop_loss=stop_loss,
            take_profit=take_profit,
            order_id=order_id,
            fee_usd=_estimate_fee(fill_price, size),
            timestamp=time.time(),
        )
        self.fill_engine.record_fill(fill)
        self.last_fill = fill
        self._orders[order_id] = fill

        if self.config.emit_events and self.redis_client:
            ts_recv_us = now_recv_us()
            await self.redis_client.publish_event(
                self.event_stream,
                Event(
                    event_id=order_id,
                    event_type="order",
                    schema_version="v1",
                    timestamp=_now_iso(),
                    ts_recv_us=ts_recv_us,
                    ts_canon_us=ts_recv_us,
                    ts_exchange_s=None,
                    bot_id=self.bot_id,
                    symbol=symbol,
                    exchange=self.exchange,
                    payload={
                        "order_id": order_id,
                        "client_order_id": client_order_id,
                        "side": side,
                        "order_type": order_type,
                        "post_only": post_only,
                        "time_in_force": time_in_force,
                        "status": "filled",
                        "price": price,
                        "fill_price": fill_price,
                        "size": size,
                        "reduce_only": reduce_only,
                        "stop_loss": stop_loss,
                        "take_profit": take_profit,
                        "paper": True,
                    },
                ),
            )
        return OrderPlacementResult(
            success=True,
            status="filled",
            order_id=order_id,
            fill_price=fill_price,
            fee_usd=fill.fee_usd,
        )

    async def fetch_order_status(self, order_id: str, symbol: str) -> Optional[dict]:
        fill = self._orders.get(order_id)
        if not fill:
            return None
        return {
            "order_id": order_id,
            "status": "filled",
            "fill_price": fill.fill_price,
            "fee_usd": fill.fee_usd,
        }

    async def fetch_order_status_by_client_id(self, client_order_id: str, symbol: str) -> Optional[dict]:
        return await self.fetch_order_status(client_order_id, symbol)

    async def place_protective_orders(
        self,
        symbol: str,
        side: str,
        size: float,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
        client_order_id: Optional[str] = None,
    ) -> bool:
        return True


def _apply_slippage(price: Optional[float], side: str, slippage_bps: float) -> Optional[float]:
    if price is None:
        return None
    slip = slippage_bps / 10000.0
    normalized = (side or "").lower()
    if normalized in {"buy", "long"}:
        return price * (1 + slip)
    if normalized in {"sell", "short"}:
        return price * (1 - slip)
    return price


def _clamp_latency(min_latency_ms: int, max_latency_ms: int) -> int:
    min_ms = max(min_latency_ms, 0)
    max_ms = max(max_latency_ms, min_ms)
    if max_ms == min_ms:
        return min_ms
    return random.randint(min_ms, max_ms)


def _estimate_fee(fill_price: Optional[float], size: float, fee_bps: float = 1.0) -> Optional[float]:
    if fill_price is None:
        return None
    return abs(fill_price * size) * (fee_bps / 10000.0)


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
