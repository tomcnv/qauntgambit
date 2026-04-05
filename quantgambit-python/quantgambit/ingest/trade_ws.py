"""Websocket trade providers for OKX/Bybit/Binance."""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from typing import Awaitable, Callable, Optional

try:
    import orjson as _json
except ImportError:
    _json = json  # type: ignore[assignment]

import aiohttp

try:
    import websockets  # type: ignore
except ImportError:  # pragma: no cover - optional dependency
    websockets = None

from quantgambit.observability.logger import log_warning, log_info
from quantgambit.observability.telemetry import TelemetryContext, TelemetryPipeline
from quantgambit.net.ws_connect import ws_connect_with_dns_fallback


@dataclass
class TradeWebsocketConfig:
    reconnect_delay_sec: float = 1.0
    max_reconnect_delay_sec: float = 10.0
    backoff_multiplier: float = 2.0
    heartbeat_interval_sec: float = 20.0
    message_timeout_sec: float = 30.0
    stale_guardrail_sec: float = 60.0
    # Proactive watchdog: force reconnect if no valid trade data for this long
    stale_watchdog_sec: float = 45.0
    rest_fallback_enabled: bool = False
    rest_fallback_interval_sec: float = 30.0
    rest_fallback_limit: int = 5


class WebsocketTradeProvider:
    def __init__(
        self,
        endpoint: str,
        subscribe_payload: Optional[dict],
        parse_message: Callable[[dict], list[dict]],
        exchange: str,
        error_classifier: Optional[Callable[[dict], Optional[dict]]] = None,
        rest_fetcher: Optional[Callable[[], Awaitable[list[dict]]]] = None,
        config: Optional[TradeWebsocketConfig] = None,
    ):
        self.endpoint = endpoint
        self.subscribe_payload = subscribe_payload
        self.parse_message = parse_message
        self.exchange = exchange
        self.error_classifier = error_classifier
        self.rest_fetcher = rest_fetcher
        self.config = config or TradeWebsocketConfig()
        self._ws = None
        self._queue: asyncio.Queue = asyncio.Queue()
        self._reconnect_attempts = 0
        self._reconnect_delay = self.config.reconnect_delay_sec
        self._last_heartbeat_at: float = 0.0
        self._last_message_at: float = 0.0
        self._last_valid_trade_at: float = 0.0  # Tracks when we last got actual trade data
        self._telemetry: Optional[TelemetryPipeline] = None
        self._telemetry_ctx: Optional[TelemetryContext] = None
        self._last_backoff_emit: float = 0.0
        self._last_auth_emit: float = 0.0
        self._last_stale_emit: float = 0.0
        self._last_rest_fetch_at: float = 0.0
        self._last_watchdog_log: float = 0.0

    async def next_trade(self) -> Optional[dict]:
        if self._queue.empty():
            await self._pump()
        if self._queue.empty():
            return None
        return await self._queue.get()

    async def _pump(self) -> None:
        await self._ensure_connection()
        if not self._ws:
            await asyncio.sleep(self._reconnect_delay)
            return
        # Proactive stale watchdog: force reconnect if no valid trade data for too long
        await self._check_stale_watchdog()
        await self._maybe_heartbeat()
        try:
            if self.config.message_timeout_sec > 0:
                raw = await asyncio.wait_for(self._ws.recv(), timeout=self.config.message_timeout_sec)
            else:
                raw = await self._ws.recv()
        except asyncio.TimeoutError:
            # Timeout just means no data was received - NOT a connection failure!
            # The ping/pong mechanism (ping_interval=20, ping_timeout=30) will detect dead connections.
            # Don't reset the connection, just return and let _pump be called again.
            # Optionally fetch via REST if enabled, but don't treat as failure.
            await self._maybe_rest_fetch("idle_timeout")
            return
        except Exception as e:
            # Actual connection error (ConnectionClosed, WebSocketException, etc.)
            log_warning("trade_ws_connection_error", exchange=self.exchange, error=str(e)[:100])
            await self._maybe_rest_fetch("connection_error")
            self._emit_stale_guardrail("connection_error")
            self._register_failure()
            await self._reset_connection()
            return
        try:
            message = _json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            return
        self._last_message_at = time.time()
        if self._handle_error(message):
            return
        trades = self.parse_message(message)
        if trades:
            self._last_valid_trade_at = time.time()  # Update watchdog timer on valid trade
        for trade in trades:
            await self._queue.put(trade)

    async def _check_stale_watchdog(self) -> None:
        """Force reconnect if no valid trade data for stale_watchdog_sec."""
        if self.config.stale_watchdog_sec <= 0:
            return
        if self._last_valid_trade_at == 0:
            # Not yet received any trade, give it time
            return
        now = time.time()
        elapsed = now - self._last_valid_trade_at
        if elapsed > self.config.stale_watchdog_sec:
            # Log at most once per stale_guardrail_sec to avoid spam
            if now - self._last_watchdog_log > self.config.stale_guardrail_sec:
                self._last_watchdog_log = now
                log_warning(
                    "trade_ws_stale_watchdog_triggered",
                    exchange=self.exchange,
                    stale_sec=round(elapsed, 1),
                    threshold=self.config.stale_watchdog_sec,
                )
                self._emit_stale_guardrail("watchdog_no_trades")
            await self._maybe_rest_fetch("watchdog")
            self._register_failure()
            await self._reset_connection()

    async def _maybe_rest_fetch(self, reason: str) -> None:
        if not self.rest_fetcher:
            return
        if not self.config.rest_fallback_enabled:
            return
        now = time.time()
        if now - self._last_rest_fetch_at < self.config.rest_fallback_interval_sec:
            return
        self._last_rest_fetch_at = now
        try:
            trades = await self.rest_fetcher()
        except Exception:
            trades = []
        if not trades:
            return
        for trade in trades:
            await self._queue.put(trade)
        # Emit telemetry/log so we can confirm fallback ran
        log_info("trade_rest_fallback_triggered", exchange=self.exchange, reason=reason, count=len(trades))
        if self._telemetry and self._telemetry_ctx:
            payload = {"type": "rest_fallback", "provider": "trade", "exchange": self.exchange, "reason": reason}
            asyncio.create_task(self._telemetry.publish_guardrail(self._telemetry_ctx, payload))
        if self._telemetry and self._telemetry_ctx:
            payload = {"type": "rest_fallback", "provider": "trade", "exchange": self.exchange, "reason": reason}
            asyncio.create_task(self._telemetry.publish_guardrail(self._telemetry_ctx, payload))

    async def _ensure_connection(self) -> None:
        if self._ws is not None:
            return
        if websockets is None:
            raise RuntimeError("websockets dependency is required for websocket providers")
        try:
            # Configure ping/pong handling:
            # - ping_interval: how often we send pings (None = server-initiated only)
            # - ping_timeout: how long to wait for pong before considering dead
            # - close_timeout: how long to wait for clean close
            # The library automatically responds to server pings with pongs.
            self._ws = await ws_connect_with_dns_fallback(
                self.endpoint,
                ping_interval=20,  # Send our own pings every 20s
                ping_timeout=30,   # Consider dead if no pong in 30s
                close_timeout=5,   # Quick close on failure
            )
        except Exception:
            self._ws = None
            self._register_failure()
            return
        self._reconnect_attempts = 0
        self._reconnect_delay = self.config.reconnect_delay_sec
        # Reset watchdog timer on fresh connection
        self._last_valid_trade_at = time.time()
        log_info("trade_ws_connected", exchange=self.exchange, endpoint=self.endpoint[:80])
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
            self._register_failure()
            await self._reset_connection()
            return
        self._last_heartbeat_at = now

    def _handle_error(self, message: dict) -> bool:
        if not self.error_classifier:
            return False
        classification = self.error_classifier(message)
        if not classification:
            return False
        error_type = classification.get("type")
        reason = classification.get("reason")
        detail = classification.get("detail")
        if error_type == "auth_failed":
            self._emit_auth_failure(reason, detail)
            return True
        if error_type == "error":
            self._emit_guardrail(reason, detail)
            return True
        return False

    def set_telemetry(self, telemetry: TelemetryPipeline, ctx: TelemetryContext) -> None:
        self._telemetry = telemetry
        self._telemetry_ctx = ctx

    def _register_failure(self) -> None:
        self._reconnect_attempts += 1
        delay = self.config.reconnect_delay_sec * (self.config.backoff_multiplier ** (self._reconnect_attempts - 1))
        self._reconnect_delay = min(self.config.max_reconnect_delay_sec, delay)
        log_warning("trade_ws_backoff", exchange=self.exchange, delay_sec=self._reconnect_delay)
        self._emit_backoff(self._reconnect_delay, self._reconnect_attempts)

    def _emit_backoff(self, delay: float, attempt: int) -> None:
        if not (self._telemetry and self._telemetry_ctx):
            return
        now = time.time()
        if now - self._last_backoff_emit < 5:
            return
        self._last_backoff_emit = now
        payload = {
            "type": "ws_backoff",
            "provider": "trade",
            "exchange": self.exchange,
            "delay_sec": delay,
            "attempt": attempt,
        }
        asyncio.create_task(self._telemetry.publish_guardrail(self._telemetry_ctx, payload))
        asyncio.create_task(
            self._telemetry.publish_health_snapshot(
                self._telemetry_ctx,
                {"status": "reconnecting", "provider": "trade", "exchange": self.exchange},
            )
        )

    def _emit_auth_failure(self, reason: Optional[str], detail: Optional[str]) -> None:
        if not (self._telemetry and self._telemetry_ctx):
            return
        now = time.time()
        if now - self._last_auth_emit < 60:
            return
        self._last_auth_emit = now
        payload = {"type": "auth_failed", "provider": "trade", "exchange": self.exchange, "reason": reason}
        if detail:
            payload["detail"] = detail
        asyncio.create_task(self._telemetry.publish_guardrail(self._telemetry_ctx, payload))
        asyncio.create_task(
            self._telemetry.publish_health_snapshot(
                self._telemetry_ctx,
                {"status": "auth_failed", "provider": "trade", "exchange": self.exchange, "reason": reason},
            )
        )

    def _emit_guardrail(self, reason: Optional[str], detail: Optional[str]) -> None:
        if not (self._telemetry and self._telemetry_ctx):
            return
        payload = {"type": "ws_error", "provider": "trade", "exchange": self.exchange, "reason": reason}
        if detail:
            payload["detail"] = detail
        asyncio.create_task(self._telemetry.publish_guardrail(self._telemetry_ctx, payload))

    def _emit_stale_guardrail(self, reason: str) -> None:
        if not (self._telemetry and self._telemetry_ctx):
            return
        now = time.time()
        if now - self._last_stale_emit < self.config.stale_guardrail_sec:
            return
        self._last_stale_emit = now
        payload = {"type": "ws_stale", "provider": "trade", "exchange": self.exchange, "reason": reason}
        asyncio.create_task(self._telemetry.publish_guardrail(self._telemetry_ctx, payload))
        asyncio.create_task(
            self._telemetry.publish_health_snapshot(
                self._telemetry_ctx,
                {"status": "stale", "provider": "trade", "exchange": self.exchange, "reason": reason},
            )
        )


class OkxTradeWebsocketProvider(WebsocketTradeProvider):
    def __init__(self, symbol: str, testnet: bool = False, config: Optional[TradeWebsocketConfig] = None):
        endpoint = "wss://wspap.okx.com:8443/ws/v5/public" if testnet else "wss://ws.okx.com:8443/ws/v5/public"
        subscribe = {"op": "subscribe", "args": [{"channel": "trades", "instId": symbol}]}
        rest_limit = config.rest_fallback_limit if config else 5
        super().__init__(
            endpoint=endpoint,
            subscribe_payload=subscribe,
            parse_message=lambda msg: _parse_okx_trades(msg, symbol),
            exchange="okx",
            rest_fetcher=_build_okx_trade_rest_fetcher(symbol, testnet, rest_limit),
            config=config,
        )


class BybitTradeWebsocketProvider(WebsocketTradeProvider):
    def __init__(
        self,
        symbol: str,
        market_type: str = "perp",
        testnet: bool = False,
        config: Optional[TradeWebsocketConfig] = None,
    ):
        normalized = (market_type or "perp").lower()
        public_type = "spot" if normalized == "spot" else "linear"
        base = "wss://stream-testnet.bybit.com/v5/public" if testnet else "wss://stream.bybit.com/v5/public"
        endpoint = f"{base}/{public_type}"
        subscribe = {"op": "subscribe", "args": [f"publicTrade.{symbol}"]}
        rest_limit = config.rest_fallback_limit if config else 5
        super().__init__(
            endpoint=endpoint,
            subscribe_payload=subscribe,
            parse_message=lambda msg: _parse_bybit_trades(msg, symbol),
            exchange="bybit",
            rest_fetcher=_build_bybit_trade_rest_fetcher(symbol, market_type, testnet, rest_limit),
            config=config,
        )


class BinanceTradeWebsocketProvider(WebsocketTradeProvider):
    def __init__(
        self,
        symbol: str,
        market_type: str = "perp",
        testnet: bool = False,
        config: Optional[TradeWebsocketConfig] = None,
    ):
        lower = symbol.lower()
        normalized = (market_type or "perp").lower()
        is_spot = normalized == "spot"
        if is_spot:
            # Binance testnet requires explicit :9443 port per docs
            base = "wss://stream.testnet.binance.vision:9443/ws" if testnet else "wss://stream.binance.com:9443/ws"
        else:
            # Futures testnet uses fstream.binancefuture.com
            base = "wss://fstream.binancefuture.com/ws" if testnet else "wss://fstream.binance.com/ws"
        endpoint = f"{base}/{lower}@aggTrade"
        rest_limit = config.rest_fallback_limit if config else 5
        super().__init__(
            endpoint=endpoint,
            subscribe_payload=None,
            parse_message=lambda msg: _parse_binance_trades(msg, symbol),
            exchange="binance",
            rest_fetcher=_build_binance_trade_rest_fetcher(symbol, market_type, testnet, rest_limit),
            config=config,
        )


class MultiplexTradeProvider:
    def __init__(self, providers: list[WebsocketTradeProvider]):
        self.providers = providers
        self._queue: asyncio.Queue = asyncio.Queue()
        self._started = False

    def set_telemetry(self, telemetry: TelemetryPipeline, ctx: TelemetryContext) -> None:
        for provider in self.providers:
            if hasattr(provider, "set_telemetry"):
                provider.set_telemetry(telemetry, ctx)

    async def next_trade(self) -> Optional[dict]:
        if not self._started:
            self._started = True
            for provider in self.providers:
                asyncio.create_task(self._drain(provider))
        return await self._queue.get()

    async def _drain(self, provider: WebsocketTradeProvider) -> None:
        while True:
            try:
                trade = await provider.next_trade()
            except Exception:
                await asyncio.sleep(1.0)
                continue
            if trade:
                await self._queue.put(trade)


def _parse_okx_trades(message: dict, symbol: str) -> list[dict]:
    data = message.get("data")
    if not data:
        return []
    trades = []
    for item in data:
        trades.append({
            "symbol": symbol,
            "timestamp": _coerce_ts(item.get("ts")),
            "price": _coerce_float(item.get("px")),
            "size": _coerce_float(item.get("sz")),
            "side": item.get("side"),
            "source": "okx_ws",
        })
    return trades


def _parse_bybit_trades(message: dict, symbol: str) -> list[dict]:
    data = message.get("data")
    if not data:
        return []
    trades = []
    for item in data:
        # Get raw ms timestamp for latency measurement
        raw_ts = item.get("T") or message.get("ts")
        ts_ms = None
        if raw_ts is not None:
            try:
                ts_ms = int(raw_ts)
            except (TypeError, ValueError):
                pass
        trades.append({
            "symbol": item.get("s") or symbol,
            "timestamp": _coerce_ts(raw_ts),
            "price": _coerce_float(item.get("p")),
            "size": _coerce_float(item.get("v")),
            "side": item.get("S"),
            "source": "bybit_ws",
            "trade_ts_ms": ts_ms,  # Raw ms timestamp for latency measurement
        })
    return trades


def _parse_binance_trades(message: dict, symbol: str) -> list[dict]:
    if message.get("e") not in {"aggTrade", "trade"}:
        return []
    return [
        {
            "symbol": message.get("s") or symbol,
            "timestamp": _coerce_ts(message.get("T")),
            "price": _coerce_float(message.get("p")),
            "size": _coerce_float(message.get("q")),
            "side": "buy" if not message.get("m") else "sell",
            "source": "binance_ws",
        }
    ]


async def _fetch_rest_json(url: str, params: Optional[dict] = None) -> Optional[object]:
    timeout = aiohttp.ClientTimeout(total=10)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, params=params) as resp:
                if resp.status != 200:
                    return None
                return await resp.json()
    except Exception:
        return None


def _build_okx_trade_rest_fetcher(
    symbol: str,
    testnet: bool,
    limit: int,
) -> Callable[[], Awaitable[list[dict]]]:
    endpoint = "https://www.okx.com/api/v5/market/trades"
    params = {"instId": symbol, "limit": str(limit)}

    async def _fetch() -> list[dict]:
        data = await _fetch_rest_json(endpoint, params=params)
        if not isinstance(data, dict):
            return []
        items = data.get("data") or []
        trades: list[dict] = []
        for item in items:
            trades.append({
                "symbol": symbol,
                "timestamp": _coerce_ts(item.get("ts")),
                "price": _coerce_float(item.get("px")),
                "size": _coerce_float(item.get("sz")),
                "side": item.get("side"),
                "source": "okx_rest",
            })
        return trades

    return _fetch


def _build_bybit_trade_rest_fetcher(
    symbol: str,
    market_type: str,
    testnet: bool,
    limit: int,
) -> Callable[[], Awaitable[list[dict]]]:
    normalized = (market_type or "perp").lower()
    category = "spot" if normalized == "spot" else "linear"
    base = "https://api-testnet.bybit.com" if testnet else "https://api.bybit.com"
    endpoint = f"{base}/v5/market/recent-trade"
    params = {"symbol": symbol, "category": category, "limit": str(limit)}

    async def _fetch() -> list[dict]:
        data = await _fetch_rest_json(endpoint, params=params)
        if not isinstance(data, dict):
            return []
        result = data.get("result") or {}
        items = result.get("list") or []
        trades: list[dict] = []
        for item in items:
            trades.append({
                "symbol": item.get("symbol") or symbol,
                "timestamp": _coerce_ts(item.get("time") or item.get("T") or item.get("ts")),
                "price": _coerce_float(item.get("price") or item.get("p")),
                "size": _coerce_float(item.get("size") or item.get("v")),
                "side": item.get("side") or item.get("S"),
                "source": "bybit_rest",
            })
        return trades

    return _fetch


def _build_binance_trade_rest_fetcher(
    symbol: str,
    market_type: str,
    testnet: bool,
    limit: int,
) -> Callable[[], Awaitable[list[dict]]]:
    normalized = (market_type or "perp").lower()
    is_spot = normalized == "spot"
    if is_spot:
        base = "https://testnet.binance.vision" if testnet else "https://api.binance.com"
        endpoint = f"{base}/api/v3/trades"
    else:
        base = "https://testnet.binancefuture.com" if testnet else "https://fapi.binance.com"
        endpoint = f"{base}/fapi/v1/trades"
    params = {"symbol": symbol, "limit": str(limit)}

    async def _fetch() -> list[dict]:
        data = await _fetch_rest_json(endpoint, params=params)
        if not isinstance(data, list):
            return []
        trades: list[dict] = []
        for item in data:
            trades.append({
                "symbol": item.get("symbol") or symbol,
                "timestamp": _coerce_ts(item.get("time")),
                "price": _coerce_float(item.get("price")),
                "size": _coerce_float(item.get("qty")),
                "side": "buy" if not item.get("isBuyerMaker") else "sell",
                "source": "binance_rest",
            })
        return trades

    return _fetch


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
