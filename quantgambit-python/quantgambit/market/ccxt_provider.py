"""Public market data provider using CCXT ticker polling."""

from __future__ import annotations

import asyncio
import time
from typing import Optional

import ccxt.async_support as ccxt

from quantgambit.observability.logger import log_warning


class CcxtTickerProvider:
    """Fetch tickers from CCXT and emit normalized ticks."""

    def __init__(
        self,
        exchange: str,
        symbols: list[str],
        market_type: str = "perp",
        poll_interval_sec: float = 0.5,
        testnet: bool = False,
    ) -> None:
        self.exchange = (exchange or "").lower()
        self.symbols = [s for s in symbols if s]
        self.market_type = (market_type or "perp").lower()
        self.poll_interval_sec = max(0.05, poll_interval_sec)
        self.testnet = testnet
        self._client = _build_public_client(self.exchange, self.market_type, testnet)
        self._idx = 0
        self._last_fetch = 0.0

    async def next_tick(self) -> Optional[dict]:
        if not self.symbols:
            await asyncio.sleep(self.poll_interval_sec)
            return None
        now = time.time()
        elapsed = now - self._last_fetch
        if elapsed < self.poll_interval_sec:
            await asyncio.sleep(self.poll_interval_sec - elapsed)
        symbol = self.symbols[self._idx % len(self.symbols)]
        self._idx += 1
        try:
            ticker = await self._client.fetch_ticker(symbol)
        except Exception as exc:
            log_warning("ccxt_ticker_failed", exchange=self.exchange, symbol=symbol, error=str(exc))
            return None
        self._last_fetch = time.time()
        return {
            "symbol": symbol,
            "timestamp": ticker.get("timestamp") or time.time(),
            "bid": ticker.get("bid"),
            "ask": ticker.get("ask"),
            "last": ticker.get("last"),
            "source": "ccxt_ticker",
        }

    async def close(self) -> None:
        if self._client is not None:
            await self._client.close()


def _build_public_client(exchange: str, market_type: str, testnet: bool):
    options: dict = {}
    normalized = (market_type or "perp").lower()
    if exchange in {"okx", "bybit"}:
        options["defaultType"] = "swap" if normalized != "spot" else "spot"
    if exchange == "binance":
        options["defaultType"] = "future" if normalized != "spot" else "spot"
    cls = getattr(ccxt, exchange, None)
    if cls is None:
        raise ValueError(f"unsupported_exchange:{exchange}")
    client = cls({"enableRateLimit": True, "options": options})
    if testnet:
        if exchange == "okx":
            client.set_sandbox_mode(True)
        elif exchange == "bybit":
            client.set_sandbox_mode(True)
        elif exchange == "binance":
            client.set_sandbox_mode(True)
    return client
