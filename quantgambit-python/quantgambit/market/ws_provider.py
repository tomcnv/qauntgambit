"""Public websocket market data providers."""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from typing import Callable, Optional

try:
    import websockets  # type: ignore
except ImportError:  # pragma: no cover - optional dependency
    websockets = None

from quantgambit.observability.logger import log_warning
from quantgambit.net.ws_connect import ws_connect_with_dns_fallback


@dataclass
class TickerWebsocketConfig:
    reconnect_delay_sec: float = 1.0
    max_reconnect_delay_sec: float = 10.0
    backoff_multiplier: float = 2.0
    heartbeat_interval_sec: float = 20.0
    # Proactive watchdog: force reconnect if no valid tick for this long
    stale_watchdog_sec: float = 45.0


class WebsocketTickerProvider:
    """Base websocket ticker provider."""

    def __init__(
        self,
        endpoint: str,
        subscribe_payload: Optional[dict],
        parse_message: Callable[[dict], Optional[dict]],
        exchange: str,
        config: Optional[TickerWebsocketConfig] = None,
    ):
        self.endpoint = endpoint
        self.subscribe_payload = subscribe_payload
        self.parse_message = parse_message
        self.exchange = exchange
        self.config = config or TickerWebsocketConfig()
        self._ws = None
        self._reconnect_attempts = 0
        self._reconnect_delay = self.config.reconnect_delay_sec
        self._last_heartbeat_at: float = 0.0
        self._last_valid_tick_at: float = 0.0  # For stale watchdog
        self._last_watchdog_log: float = 0.0

    async def next_tick(self) -> Optional[dict]:
        await self._ensure_connection()
        if not self._ws:
            await asyncio.sleep(self._reconnect_delay)
            return None
        # Proactive stale watchdog
        await self._check_stale_watchdog()
        await self._maybe_heartbeat()
        try:
            raw = await self._ws.recv()
        except Exception:
            self._register_failure()
            await self._reset_connection()
            return None
        try:
            message = json.loads(raw)
        except json.JSONDecodeError:
            return None
        tick = self.parse_message(message)
        if tick:
            self._last_valid_tick_at = time.time()
        return tick

    async def _check_stale_watchdog(self) -> None:
        """Force reconnect if no valid tick for stale_watchdog_sec."""
        if self.config.stale_watchdog_sec <= 0:
            return
        if self._last_valid_tick_at == 0:
            return
        now = time.time()
        elapsed = now - self._last_valid_tick_at
        if elapsed > self.config.stale_watchdog_sec:
            if now - self._last_watchdog_log > 60:
                self._last_watchdog_log = now
                log_warning(
                    "ticker_ws_stale_watchdog_triggered",
                    exchange=self.exchange,
                    stale_sec=round(elapsed, 1),
                    threshold=self.config.stale_watchdog_sec,
                )
            self._register_failure()
            await self._reset_connection()

    async def _ensure_connection(self) -> None:
        if self._ws is not None:
            return
        if websockets is None:
            raise RuntimeError("websockets dependency is required for websocket providers")
        try:
            # Configure ping/pong handling for reliable connections
            self._ws = await ws_connect_with_dns_fallback(
                self.endpoint,
                ping_interval=20,  # Send pings every 20s
                ping_timeout=30,   # Consider dead if no pong in 30s
                close_timeout=5,
            )
        except Exception:
            self._ws = None
            self._register_failure()
            return
        self._reconnect_attempts = 0
        self._reconnect_delay = self.config.reconnect_delay_sec
        self._last_valid_tick_at = time.time()  # Reset watchdog
        if self.subscribe_payload:
            await self._ws.send(json.dumps(self.subscribe_payload))

    async def _reset_connection(self) -> None:
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
        self._ws = None
        self._last_heartbeat_at = 0.0

    async def _maybe_heartbeat(self) -> None:
        if not self._ws:
            return
        interval = self.config.heartbeat_interval_sec
        if interval <= 0:
            return
        now = time.time()
        if now - self._last_heartbeat_at < interval:
            return
        if not hasattr(self._ws, "ping"):
            self._last_heartbeat_at = now
            return
        try:
            await self._ws.ping()
        except Exception:
            await self._reset_connection()
            return
        self._last_heartbeat_at = now

    def _register_failure(self) -> None:
        self._reconnect_attempts += 1
        delay = self.config.reconnect_delay_sec * (self.config.backoff_multiplier ** (self._reconnect_attempts - 1))
        self._reconnect_delay = min(self.config.max_reconnect_delay_sec, delay)
        log_warning("ticker_ws_backoff", exchange=self.exchange, delay_sec=self._reconnect_delay)


class OkxTickerWebsocketProvider(WebsocketTickerProvider):
    def __init__(self, symbol: str, testnet: bool = False):
        endpoint = "wss://wspap.okx.com:8443/ws/v5/public" if testnet else "wss://ws.okx.com:8443/ws/v5/public"
        subscribe = {"op": "subscribe", "args": [{"channel": "tickers", "instId": symbol}]}
        super().__init__(
            endpoint=endpoint,
            subscribe_payload=subscribe,
            parse_message=lambda msg: _parse_okx_ticker(msg, symbol),
            exchange="okx",
        )


class BybitTickerWebsocketProvider(WebsocketTickerProvider):
    def __init__(self, symbol: str, market_type: str = "perp", testnet: bool = False):
        normalized = (market_type or "perp").lower()
        public_type = "spot" if normalized == "spot" else "linear"
        base = "wss://stream-testnet.bybit.com/v5/public" if testnet else "wss://stream.bybit.com/v5/public"
        endpoint = f"{base}/{public_type}"
        subscribe = {"op": "subscribe", "args": [f"tickers.{symbol}"]}
        super().__init__(
            endpoint=endpoint,
            subscribe_payload=subscribe,
            parse_message=lambda msg: _parse_bybit_ticker(msg, symbol),
            exchange="bybit",
        )


class BinanceTickerWebsocketProvider(WebsocketTickerProvider):
    def __init__(self, symbol: str, market_type: str = "perp", testnet: bool = False):
        lower = symbol.lower()
        normalized = (market_type or "perp").lower()
        is_spot = normalized == "spot"
        # Binance testnet requires explicit :9443 port per docs
        if is_spot:
            base = "wss://stream.testnet.binance.vision:9443/ws" if testnet else "wss://stream.binance.com:9443/ws"
        else:
            base = "wss://fstream.binancefuture.com/ws" if testnet else "wss://fstream.binance.com/ws"
        endpoint = f"{base}/{lower}@bookTicker"
        super().__init__(
            endpoint=endpoint,
            subscribe_payload=None,
            parse_message=lambda msg: _parse_binance_ticker(msg, symbol),
            exchange="binance",
        )


class MultiplexTickerProvider:
    """Fan-in provider that merges ticks from multiple providers."""

    def __init__(self, providers: list[WebsocketTickerProvider]):
        self.providers = providers
        self._queue: asyncio.Queue = asyncio.Queue()
        self._started = False

    async def next_tick(self) -> Optional[dict]:
        if not self._started:
            self._started = True
            for provider in self.providers:
                asyncio.create_task(self._drain(provider))
        return await self._queue.get()

    async def _drain(self, provider: WebsocketTickerProvider) -> None:
        while True:
            try:
                tick = await provider.next_tick()
            except Exception:
                await asyncio.sleep(1.0)
                continue
            if tick:
                await self._queue.put(tick)


def _parse_okx_ticker(message: dict, symbol: str) -> Optional[dict]:
    data = message.get("data")
    if not data:
        return None
    item = data[0] if isinstance(data, list) else data
    return {
        "symbol": symbol,
        "timestamp": _coerce_ts(item.get("ts")),
        "bid": _coerce_float(item.get("bidPx")),
        "ask": _coerce_float(item.get("askPx")),
        "last": _coerce_float(item.get("last")),
        "source": "okx_ws",
    }


def _parse_bybit_ticker(message: dict, symbol: str) -> Optional[dict]:
    data = message.get("data")
    if not data:
        return None
    return {
        "symbol": data.get("symbol") or symbol,
        "timestamp": _coerce_ts(message.get("ts")),
        "bid": _coerce_float(data.get("bid1Price")),
        "ask": _coerce_float(data.get("ask1Price")),
        "last": _coerce_float(data.get("lastPrice")),
        "source": "bybit_ws",
    }


def _parse_binance_ticker(message: dict, symbol: str) -> Optional[dict]:
    if message.get("u") is None and message.get("s") is None:
        return None
    return {
        "symbol": message.get("s") or symbol,
        "timestamp": _coerce_ts(message.get("E")),
        "bid": _coerce_float(message.get("b")),
        "ask": _coerce_float(message.get("a")),
        "last": _coerce_float(message.get("c")),
        "source": "binance_ws",
    }


def _coerce_ts(value) -> float:
    if value is None:
        return time.time()
    try:
        ts = float(value)
    except (TypeError, ValueError):
        return time.time()
    if ts > 1e12:
        return ts / 1000.0
    return ts


def _coerce_float(value) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
