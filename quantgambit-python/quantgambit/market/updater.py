"""Market data updater for reference prices."""

from __future__ import annotations

import time
import asyncio
from typing import Optional, Protocol

from quantgambit.market.reference_prices import ReferencePriceCache
from quantgambit.market.ticks import normalize_tick
from quantgambit.observability.logger import log_warning
from quantgambit.observability.telemetry import TelemetryContext, TelemetryPipeline


class MarketDataProvider(Protocol):
    async def next_tick(self) -> Optional[dict]:
        """Return the next market data tick with symbol/bid/ask/last."""


class MarketDataUpdater:
    """Updates reference prices from market data ticks."""

    def __init__(
        self,
        cache: ReferencePriceCache,
        provider: MarketDataProvider,
        telemetry: TelemetryPipeline | None = None,
        telemetry_context: TelemetryContext | None = None,
        stale_threshold_sec: float = 5.0,
        idle_backoff_sec: float = 0.1,
        heartbeat_interval_sec: float = 5.0,
    ):
        self.cache = cache
        self.provider = provider
        self.telemetry = telemetry
        self.telemetry_context = telemetry_context
        self.stale_threshold_sec = stale_threshold_sec
        self.idle_backoff_sec = idle_backoff_sec
        self.heartbeat_interval_sec = heartbeat_interval_sec
        self._last_tick_at: float = time.time()
        self._last_heartbeat_at: float = 0.0

    async def run(self) -> None:
        loop = asyncio.get_running_loop()

        async def _sleep(delay_sec: float) -> None:
            # Do not rely on asyncio.sleep() directly; some tests patch it and can
            # accidentally remove the suspension point (busy-loop), preventing
            # timeouts/cancellation from firing.
            fut = loop.create_future()
            loop.call_later(max(0.0, float(delay_sec)), fut.set_result, None)
            await fut

        while True:
            raw_tick = await self.provider.next_tick()
            if not raw_tick:
                await self._heartbeat()
                await _sleep(self.idle_backoff_sec)
                continue
            tick = normalize_tick(raw_tick)
            if not tick:
                log_warning("tick_invalid", raw=str(raw_tick)[:200])
                continue
            if _is_stale_tick(tick.get("timestamp"), self.stale_threshold_sec):
                log_warning("tick_stale", symbol=tick.get("symbol"), ts=tick.get("timestamp"))
                if self.telemetry and self.telemetry_context:
                    await self.telemetry.publish_latency(
                        ctx=self.telemetry_context,
                        payload={
                            "market_data_stale": True,
                            "symbol": tick.get("symbol"),
                        },
                    )
                continue
            price = _reference_price(tick.get("bid"), tick.get("ask"), tick.get("last"))
            if price is not None:
                self.cache.update(tick["symbol"], price)
            self._last_tick_at = time.time()
            await self._heartbeat()

    async def _heartbeat(self) -> None:
        now = time.time()
        if now - self._last_heartbeat_at < self.heartbeat_interval_sec:
            return
        self._last_heartbeat_at = now
        if not (self.telemetry and self.telemetry_context):
            return
        await self.telemetry.publish_latency(
            ctx=self.telemetry_context,
            payload={
                "market_data_heartbeat": True,
                "last_tick_age_sec": round(now - self._last_tick_at, 3),
            },
        )


def _reference_price(bid: Optional[float], ask: Optional[float], last: Optional[float]) -> Optional[float]:
    """Calculate reference price for mark-to-market.
    
    IMPORTANT: We prefer mid-price (from orderbook) over last trade price for stability.
    Trade prices can spike momentarily and cause PnL oscillation.
    Only fall back to last trade price if no bid/ask available AND no existing mid-price.
    """
    if bid is not None and ask is not None:
        return (bid + ask) / 2.0
    # Don't use trade price for reference - it causes PnL oscillation
    # Return None to signal "no update" - caller should keep existing price
    return None


def _is_stale_tick(raw_ts: Optional[object], threshold_sec: float) -> bool:
    if raw_ts is None:
        return False
    ts = _to_epoch_seconds(raw_ts)
    if ts is None:
        return False
    return (time.time() - ts) > threshold_sec


def _to_epoch_seconds(raw_ts: object) -> Optional[float]:
    try:
        ts = float(raw_ts)
        if ts > 10_000_000_000:  # ms epoch
            return ts / 1000.0
        return ts
    except (TypeError, ValueError):
        return None
