"""Websocket orderbook providers for OKX/Bybit/Binance."""

from __future__ import annotations

import asyncio
import json
import time
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable, Optional

try:
    import orjson as _json
except ImportError:
    _json = json  # type: ignore[assignment]

try:
    import websockets  # type: ignore
except ImportError:  # pragma: no cover - optional dependency
    websockets = None

from quantgambit.observability.logger import log_info, log_warning
from quantgambit.observability.telemetry import TelemetryContext, TelemetryPipeline
from quantgambit.net.ws_connect import ws_connect_with_dns_fallback


@dataclass
class WebsocketConfig:
    reconnect_delay_sec: float = 1.0
    max_reconnect_delay_sec: float = 10.0
    backoff_multiplier: float = 2.0
    heartbeat_interval_sec: float = 20.0
    snapshot_interval_sec: float = 30.0
    recv_timeout_sec: float = 5.0
    # Proactive watchdog: force reconnect if no valid update for this long
    stale_watchdog_sec: float = 45.0
    # Force resync if sequence gap detected (Binance specific)
    resync_on_gap: bool = True


class WebsocketOrderbookProvider:
    """Base websocket provider returning snapshot/delta updates."""

    def __init__(
        self,
        endpoint: str,
        subscribe_payload: Optional[dict],
        parse_message: Callable[[dict], Optional[dict]],
        exchange: str,
        snapshot_fetcher: Optional[Callable[[], Optional[dict]]] = None,
        error_classifier: Optional[Callable[[dict], Optional[dict]]] = None,
        config: Optional[WebsocketConfig] = None,
    ):
        self.endpoint = endpoint
        self.subscribe_payload = subscribe_payload
        self.parse_message = parse_message
        self.exchange = exchange
        self.snapshot_fetcher = snapshot_fetcher
        self.error_classifier = error_classifier
        self.config = config or WebsocketConfig()
        self._ws = None
        self._pending_snapshot: Optional[dict] = None
        self._reconnect_attempts = 0
        self._reconnect_delay = self.config.reconnect_delay_sec
        self._telemetry: Optional[TelemetryPipeline] = None
        self._telemetry_ctx: Optional[TelemetryContext] = None
        self._last_auth_emit: float = 0.0
        self._last_backoff_emit: float = 0.0
        self._last_heartbeat_at: float = 0.0
        self._last_snapshot_at: float = 0.0
        self._last_valid_update_at: float = 0.0  # For stale watchdog
        self._last_watchdog_log: float = 0.0
        self._last_seq: Optional[int] = None  # For gap detection
        self._snapshot_seq: Optional[int] = None  # REST snapshot lastUpdateId

    async def next_update(self) -> Optional[dict]:
        if self._pending_snapshot:
            snapshot = self._pending_snapshot
            self._pending_snapshot = None
            # Track snapshot seq for gap detection
            payload = snapshot.get("payload") if isinstance(snapshot, dict) else None
            if payload and isinstance(payload, dict):
                self._snapshot_seq = payload.get("seq")
                self._last_seq = None  # Reset delta tracking after snapshot
            return snapshot
        await self._ensure_connection()
        if self._pending_snapshot:
            snapshot = self._pending_snapshot
            self._pending_snapshot = None
            payload = snapshot.get("payload") if isinstance(snapshot, dict) else None
            if payload and isinstance(payload, dict):
                self._snapshot_seq = payload.get("seq")
                self._last_seq = None
            return snapshot
        if not self._ws:
            await asyncio.sleep(self._reconnect_delay)
            return None
        # Proactive stale watchdog
        await self._check_stale_watchdog()
        await self._maybe_snapshot()
        await self._maybe_heartbeat()
        try:
            if self.config.recv_timeout_sec and self.config.recv_timeout_sec > 0:
                raw = await asyncio.wait_for(self._ws.recv(), timeout=self.config.recv_timeout_sec)
            else:
                raw = await self._ws.recv()
        except asyncio.TimeoutError:
            self._register_failure("recv_timeout", None)
            await self._reset_connection()
            return None
        except Exception:
            self._register_failure("connection_lost", None)
            await self._reset_connection()
            return None
        try:
            message = _json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            return None
        if self._handle_error(message):
            return None
        parsed = self.parse_message(message)
        if parsed:
            self._last_valid_update_at = time.time()
            if self.config.resync_on_gap:
                action, gap_size = self._check_seq_gap(parsed)
                if action == "drop":
                    return None
                if action == "resync":
                    payload = parsed.get("payload") if isinstance(parsed, dict) else None
                    if isinstance(payload, dict):
                        payload["gap_detected"] = True
                        payload["gap_size"] = gap_size
                    log_warning(
                        "orderbook_seq_gap_detected",
                        exchange=self.exchange,
                        last_seq=self._last_seq,
                        snapshot_seq=self._snapshot_seq,
                        new_seq=(payload or {}).get("seq") if isinstance(payload, dict) else None,
                        gap_size=gap_size,
                    )
                    await self.request_snapshot()
            return parsed
        return None

    async def force_reconnect(self) -> None:
        """Force reconnect to obtain a fresh WS snapshot (no REST snapshot)."""
        await self._reset_connection()
        # Reset snapshot/sequence tracking so the next WS snapshot becomes the baseline.
        self._pending_snapshot = None
        self._last_snapshot_at = 0.0
        self._last_seq = None
        self._snapshot_seq = None

    async def _check_stale_watchdog(self) -> None:
        """Force reconnect if no valid orderbook update for stale_watchdog_sec."""
        if self.config.stale_watchdog_sec <= 0:
            return
        if self._last_valid_update_at == 0:
            return
        now = time.time()
        elapsed = now - self._last_valid_update_at
        if elapsed > self.config.stale_watchdog_sec:
            if now - self._last_watchdog_log > 60:  # Log at most once per minute
                self._last_watchdog_log = now
                log_warning(
                    "orderbook_ws_stale_watchdog_triggered",
                    exchange=self.exchange,
                    stale_sec=round(elapsed, 1),
                    threshold=self.config.stale_watchdog_sec,
                )
            self._register_failure("watchdog_no_updates", None)
            await self._reset_connection()

    def _check_seq_gap(self, update: dict) -> tuple[str, int]:
        """Check for sequence gaps or out-of-order updates.

        Returns:
            ("ok", 0) for normal updates
            ("drop", 0) for stale/duplicate updates to skip
            ("resync", gap_size) for gaps requiring resync
        """
        payload = update.get("payload") if isinstance(update, dict) else None
        if not payload:
            return ("ok", 0)

        update_type = update.get("type") or ""
        seq = payload.get("seq")

        # L1 updates are heartbeat/BB/A-only and should not drive book sync gaps.
        if payload.get("is_l1") or payload.get("book_level") == 1:
            return ("ok", 0)

        # Snapshot resets sequence tracking for all exchanges.
        if update_type == "snapshot" and seq is not None:
            self._snapshot_seq = seq
            self._last_seq = None
            return ("ok", 0)

        if self.exchange == "binance":
            first_seq = payload.get("first_seq")
            last_seq = payload.get("last_seq")
            prev_seq = payload.get("prev_seq")

            if first_seq is None or last_seq is None:
                return ("ok", 0)

            # Drop duplicate/old updates
            if self._last_seq is not None and last_seq <= self._last_seq:
                return ("drop", 0)

            # First delta after snapshot - validate alignment
            if self._snapshot_seq is not None and self._last_seq is None:
                if last_seq < self._snapshot_seq:
                    return ("drop", 0)
                self._last_seq = last_seq
                return ("ok", 0)

            # Validate against previous delta (continuous updates)
            if self._last_seq is not None:
                if prev_seq is not None:
                    if prev_seq != self._last_seq:
                        gap = first_seq - self._last_seq - 1
                        if gap > 100:
                            return ("resync", gap)
                else:
                    gap = first_seq - self._last_seq - 1
                    if gap > 100:
                        return ("resync", gap)

            self._last_seq = last_seq
            return ("ok", 0)

        if self.exchange == "bybit":
            if seq is None:
                return ("ok", 0)

            if self._snapshot_seq is None and self._last_seq is None:
                # We should not process deltas without a snapshot baseline.
                return ("resync", 0)

            if self._last_seq is None:
                expected = self._snapshot_seq + 1 if self._snapshot_seq is not None else None
                if expected is None:
                    self._last_seq = seq
                    return ("ok", 0)
                if seq < expected:
                    return ("drop", 0)
                if seq > expected:
                    return ("resync", seq - expected)
                self._last_seq = seq
                return ("ok", 0)

            expected = self._last_seq + 1
            if seq < expected:
                return ("drop", 0)
            if seq > expected:
                return ("resync", seq - expected)
            self._last_seq = seq
            return ("ok", 0)

        return ("ok", 0)

    async def request_snapshot(self) -> None:
        if not self.snapshot_fetcher:
            return
        snapshot = self._fetch_snapshot("resync")
        if snapshot:
            self._pending_snapshot = snapshot
            self._last_snapshot_at = time.time()
            payload = snapshot.get("payload") if isinstance(snapshot, dict) else None
            symbol = payload.get("symbol") if isinstance(payload, dict) else None
            log_info(
                "orderbook_snapshot_fetched",
                exchange=self.exchange,
                source="resync",
                symbol=symbol,
            )

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
            self._register_failure("connect_failed", None)
            return
        self._reconnect_attempts = 0
        self._reconnect_delay = self.config.reconnect_delay_sec
        # Reset watchdog and sequence tracking on fresh connection
        self._last_valid_update_at = time.time()
        self._last_seq = None
        self._snapshot_seq = None
        log_info("orderbook_ws_connected", exchange=self.exchange, endpoint=self.endpoint[:80])
        if self.subscribe_payload:
            await self._ws.send(json.dumps(self.subscribe_payload))
        if self.snapshot_fetcher:
            snapshot = self._fetch_snapshot("connect")
            if snapshot:
                self._pending_snapshot = snapshot
                self._last_snapshot_at = time.time()

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
            self._register_failure("heartbeat_failed", None)
            await self._reset_connection()
            return
        self._last_heartbeat_at = now

    async def _maybe_snapshot(self) -> None:
        if not self.snapshot_fetcher:
            return
        interval = self.config.snapshot_interval_sec
        if interval <= 0:
            return
        now = time.time()
        if now - self._last_snapshot_at < interval:
            return
        snapshot = self._fetch_snapshot("periodic")
        if snapshot:
            self._pending_snapshot = snapshot
            self._last_snapshot_at = now

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

    def _register_failure(self, reason: str, detail: Optional[str]) -> None:
        self._reconnect_attempts += 1
        delay = self.config.reconnect_delay_sec * (self.config.backoff_multiplier ** (self._reconnect_attempts - 1))
        self._reconnect_delay = min(self.config.max_reconnect_delay_sec, delay)
        log_warning(
            "orderbook_ws_backoff",
            exchange=self.exchange,
            reason=reason,
            delay_sec=self._reconnect_delay,
            attempt=self._reconnect_attempts,
        )
        self._emit_backoff(reason, detail, self._reconnect_delay, self._reconnect_attempts)

    def _emit_backoff(self, reason: str, detail: Optional[str], delay: float, attempt: int) -> None:
        if not (self._telemetry and self._telemetry_ctx):
            return
        now = time.time()
        if now - self._last_backoff_emit < 5:
            return
        self._last_backoff_emit = now
        payload = {
            "type": "ws_backoff",
            "provider": "orderbook",
            "exchange": self.exchange,
            "reason": reason,
            "delay_sec": delay,
            "attempt": attempt,
        }
        if detail:
            payload["detail"] = detail
        asyncio.create_task(self._telemetry.publish_guardrail(self._telemetry_ctx, payload))
        asyncio.create_task(
            self._telemetry.publish_health_snapshot(
                self._telemetry_ctx,
                {"status": "reconnecting", "provider": "orderbook", "exchange": self.exchange, "reason": reason},
            )
        )

    def _emit_auth_failure(self, reason: Optional[str], detail: Optional[str]) -> None:
        if not (self._telemetry and self._telemetry_ctx):
            return
        now = time.time()
        if now - self._last_auth_emit < 60:
            return
        self._last_auth_emit = now
        payload = {"type": "auth_failed", "provider": "orderbook", "exchange": self.exchange, "reason": reason}
        if detail:
            payload["detail"] = detail
        asyncio.create_task(self._telemetry.publish_guardrail(self._telemetry_ctx, payload))
        asyncio.create_task(
            self._telemetry.publish_health_snapshot(
                self._telemetry_ctx,
                {"status": "auth_failed", "provider": "orderbook", "exchange": self.exchange, "reason": reason},
            )
        )

    def _emit_guardrail(self, reason: Optional[str], detail: Optional[str]) -> None:
        if not (self._telemetry and self._telemetry_ctx):
            return
        payload = {"type": "ws_error", "provider": "orderbook", "exchange": self.exchange, "reason": reason}
        if detail:
            payload["detail"] = detail
        asyncio.create_task(self._telemetry.publish_guardrail(self._telemetry_ctx, payload))

    def _fetch_snapshot(self, source: str) -> Optional[dict]:
        try:
            snapshot = self.snapshot_fetcher()
        except Exception as exc:
            log_warning(
                "orderbook_snapshot_fetch_failed",
                exchange=self.exchange,
                source=source,
                error=str(exc),
            )
            return None
        if not snapshot:
            log_warning(
                "orderbook_snapshot_fetch_empty",
                exchange=self.exchange,
                source=source,
            )
            return None
        return snapshot


class MultiplexOrderbookProvider:
    """Fan-in provider that merges updates from multiple providers."""

    def __init__(self, providers: list[WebsocketOrderbookProvider]):
        self.providers = providers
        self._queue: asyncio.Queue = asyncio.Queue()
        self._started = False

    def set_telemetry(self, telemetry: TelemetryPipeline, ctx: TelemetryContext) -> None:
        for provider in self.providers:
            if hasattr(provider, "set_telemetry"):
                provider.set_telemetry(telemetry, ctx)

    async def next_update(self) -> Optional[dict]:
        if not self._started:
            self._started = True
            for provider in self.providers:
                asyncio.create_task(self._drain_provider(provider))
        return await self._queue.get()

    async def _drain_provider(self, provider: WebsocketOrderbookProvider) -> None:
        loop = asyncio.get_running_loop()

        async def _sleep(delay_sec: float) -> None:
            # Avoid relying on asyncio.sleep() directly; tests may patch it and
            # accidentally eliminate the suspension point (busy-loop).
            fut = loop.create_future()
            loop.call_later(max(0.0, float(delay_sec)), fut.set_result, None)
            await fut

        while True:
            try:
                update = await provider.next_update()
            except Exception:
                await _sleep(1.0)
                continue
            if update:
                await self._queue.put(update)
            else:
                # Provider returned no update; yield to avoid starving the loop.
                await _sleep(0.01)

    async def request_snapshot(self) -> None:
        for provider in self.providers:
            if hasattr(provider, "request_snapshot"):
                await provider.request_snapshot()

    async def force_reconnect(self) -> None:
        for provider in self.providers:
            if hasattr(provider, "force_reconnect"):
                await provider.force_reconnect()


class OkxOrderbookWebsocketProvider(WebsocketOrderbookProvider):
    """OKX orderbook websocket provider."""

    def __init__(
        self,
        symbol: str,
        testnet: bool = False,
        market_type: str = "perp",
        config: Optional[WebsocketConfig] = None,
    ):
        endpoint = "wss://wspap.okx.com:8443/ws/v5/public" if testnet else "wss://ws.okx.com:8443/ws/v5/public"
        subscribe = {"op": "subscribe", "args": [{"channel": "books", "instId": symbol}]}
        super().__init__(
            endpoint=endpoint,
            subscribe_payload=subscribe,
            parse_message=lambda msg: _parse_okx_message(msg, symbol),
            exchange="okx",
            error_classifier=_classify_okx_error,
            snapshot_fetcher=lambda: _fetch_okx_snapshot(symbol, testnet=testnet),
            config=config,
        )


class BybitOrderbookWebsocketProvider(WebsocketOrderbookProvider):
    """Bybit orderbook websocket provider with L1 heartbeat.
    
    Subscribes to both orderbook.1 (10ms, L1 heartbeat + best bid/ask) and 
    orderbook.50 (20ms, depth for imbalance signals).
    
    L1 provides:
    - Fastest updates (~10ms)
    - Re-pushed every 3s if unchanged (heartbeat)
    - Best bid/ask only
    
    L50 provides:
    - 50 levels of depth (~20ms)
    - Sufficient for most scalping signals
    """

    def __init__(
        self,
        symbol: str,
        testnet: bool = False,
        market_type: str = "perp",
        config: Optional[WebsocketConfig] = None,
        include_l1_heartbeat: bool = True,
        include_l2_depth: bool = True,
        use_rest_snapshot: bool = True,
    ):
        normalized = (market_type or "perp").lower()
        public_type = "spot" if normalized == "spot" else "linear"
        base = "wss://stream-testnet.bybit.com/v5/public" if testnet else "wss://stream.bybit.com/v5/public"
        endpoint = f"{base}/{public_type}"
        
        # Subscribe to both L1 (heartbeat) and L50 (depth) on same connection
        # L1: ~10ms push, re-pushed every 3s if unchanged (acts as heartbeat)
        # L50: ~20ms push, 50 levels depth for imbalance signals
        args = []
        if include_l1_heartbeat:
            args.append(f"orderbook.1.{symbol}")
        if include_l2_depth:
            args.append(f"orderbook.50.{symbol}")
        if not args:
            # Safe default: keep depth stream enabled.
            args.append(f"orderbook.50.{symbol}")
        subscribe = {"op": "subscribe", "args": args}
        
        super().__init__(
            endpoint=endpoint,
            subscribe_payload=subscribe,
            parse_message=lambda msg: _parse_bybit_message(msg, symbol),
            exchange="bybit",
            error_classifier=_classify_bybit_error,
            snapshot_fetcher=(lambda: _fetch_bybit_snapshot(symbol, public_type, testnet=testnet)) if use_rest_snapshot else None,
            config=config,
        )


class BinanceOrderbookWebsocketProvider(WebsocketOrderbookProvider):
    """Binance orderbook websocket provider with REST snapshot bootstrap."""

    def __init__(
        self,
        symbol: str,
        testnet: bool = False,
        market_type: str = "perp",
        config: Optional[WebsocketConfig] = None,
    ):
        lower = symbol.lower()
        normalized = (market_type or "perp").lower()
        is_spot = normalized == "spot"
        # Use combined stream endpoint - more reliable than single stream
        # Binance testnet requires explicit :9443 port per docs
        if is_spot:
            ws_base = "wss://stream.testnet.binance.vision:9443/stream" if testnet else "wss://stream.binance.com:9443/stream"
        else:
            ws_base = "wss://fstream.binancefuture.com/stream" if testnet else "wss://fstream.binance.com/stream"
        endpoint = f"{ws_base}?streams={lower}@depth@100ms"
        super().__init__(
            endpoint=endpoint,
            subscribe_payload=None,
            parse_message=lambda msg: _parse_binance_combined_message(msg, symbol),
            exchange="binance",
            error_classifier=_classify_binance_error,
            snapshot_fetcher=lambda: _fetch_binance_snapshot(symbol, testnet=testnet, market_type=normalized),
            config=config,
        )


def _parse_okx_message(message: dict, symbol: str) -> Optional[dict]:
    if message.get("event") == "error":
        return None
    data = message.get("data")
    if not data:
        return None
    item = data[0] if isinstance(data, list) else data
    action = message.get("action") or "snapshot"
    seq = item.get("seqId") or item.get("seq")
    try:
        seq_val = int(seq)
    except (TypeError, ValueError):
        seq_val = int(time.time() * 1000)
    payload = {
        "symbol": symbol,
        "timestamp": _coerce_ts(item.get("ts")),
        "seq": seq_val,
        "bids": item.get("bids") or [],
        "asks": item.get("asks") or [],
        "exchange": "okx",
        "seq_tolerant": True,
    }
    return {"type": "snapshot" if action == "snapshot" else "delta", "payload": payload}


def _parse_bybit_message(message: dict, symbol: str) -> Optional[dict]:
    if message.get("retCode") and message.get("retCode") != 0:
        return None
    data = message.get("data")
    if not data:
        return None
    
    # Check topic to distinguish L1 from L50 messages
    # L1 (orderbook.1.*) only has 1 level - treat as delta to avoid overwriting full book
    # L50 (orderbook.50.*) has 50 levels - can be snapshot or delta
    topic = message.get("topic") or ""
    is_l1_message = ".1." in topic or topic.startswith("orderbook.1")
    
    msg_type = message.get("type") or "snapshot"
    seq = data.get("u") or data.get("seq")
    try:
        seq_val = int(seq)
    except (TypeError, ValueError):
        seq_val = int(time.time() * 1000)
    
    # Capture cts (matching engine timestamp) for proper latency measurement
    # cts is in milliseconds from exchange matching engine
    cts_raw = data.get("cts")
    cts_ms = None
    if cts_raw is not None:
        try:
            cts_ms = int(cts_raw)
        except (TypeError, ValueError):
            pass
    
    # Detect service restart: u=1 means Bybit restarted, must reset local book
    is_service_restart = seq_val == 1
    
    payload = {
        "symbol": data.get("s") or symbol,
        "timestamp": _coerce_ts(message.get("ts")),
        "seq": seq_val,
        "bids": data.get("b") or [],
        "asks": data.get("a") or [],
        "cts_ms": cts_ms,  # Matching engine timestamp for latency measurement
        "cross_seq": data.get("seq"),  # Cross-sequence for multi-stream correlation
        "book_level": 1 if is_l1_message else 50,
        "is_l1": is_l1_message,
    }
    
    # Determine update type:
    # - L1 messages: ALWAYS treat as delta (only update best bid/ask, don't replace book)
    # - L50 messages: snapshot if type=snapshot or service restart, else delta
    # - Service restart (u=1): force snapshot to reset local book
    # - Bybit spot: sequence spaces differ between snapshot/delta, mark tolerant
    if is_l1_message:
        # L1 messages should never replace the full book - treat as delta
        # L1 has independent sequence space from L50, so mark seq_tolerant
        update_type = "delta"
        payload["seq_tolerant"] = True
    elif is_service_restart:
        # Service restart requires full book reset
        update_type = "snapshot"
    else:
        update_type = "snapshot" if msg_type == "snapshot" else "delta"
        # Bybit spot uses different seq spaces for ws snapshots vs deltas
        if update_type == "delta":
            payload["seq_tolerant"] = True
    
    return {"type": update_type, "payload": payload}


def _parse_binance_message(message: dict, symbol: str) -> Optional[dict]:
    if message.get("e") == "error":
        return None
    if message.get("e") != "depthUpdate":
        return None
    first_seq = message.get("U")
    last_seq = message.get("u") or first_seq
    prev_seq = message.get("pu")
    try:
        seq_val = int(last_seq)
    except (TypeError, ValueError):
        seq_val = int(time.time() * 1000)
    payload = {
        "symbol": symbol,
        "timestamp": _coerce_ts(message.get("E")),
        "seq": seq_val,
        "first_seq": first_seq,
        "last_seq": last_seq,
        "prev_seq": prev_seq,
        "bids": message.get("b") or [],
        "asks": message.get("a") or [],
        "exchange": "binance",
    }
    return {"type": "delta", "payload": payload}


def _parse_binance_combined_message(message: dict, symbol: str) -> Optional[dict]:
    """Parse Binance combined stream format: {stream: ..., data: ...}"""
    # Combined stream wraps messages in {stream: "...", data: {...}}
    data = message.get("data")
    if not data:
        # Fallback to direct message format
        return _parse_binance_message(message, symbol)
    return _parse_binance_message(data, symbol)


def _fetch_binance_snapshot(
    symbol: str,
    testnet: bool = False,
    market_type: str = "perp",
) -> Optional[dict]:
    normalized = (market_type or "perp").lower()
    if normalized == "spot":
        rest_base = "https://testnet.binance.vision/api" if testnet else "https://api.binance.com/api"
        url = f"{rest_base}/v3/depth?symbol={symbol}&limit=1000"
    else:
        rest_base = "https://testnet.binancefuture.com" if testnet else "https://fapi.binance.com"
        url = f"{rest_base}/fapi/v1/depth?symbol={symbol}&limit=1000"
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        log_warning("orderbook_snapshot_fetch_error", exchange="binance", url=url, error=str(exc))
        return None
    seq = payload.get("lastUpdateId")
    try:
        seq_val = int(seq)
    except (TypeError, ValueError):
        seq_val = int(time.time() * 1000)
    snapshot = {
        "symbol": symbol,
        "timestamp": time.time(),
        "seq": seq_val,
        "bids": payload.get("bids") or [],
        "asks": payload.get("asks") or [],
        "exchange": "binance",
    }
    return {"type": "snapshot", "payload": snapshot}


def _fetch_okx_snapshot(symbol: str, testnet: bool = False) -> Optional[dict]:
    base = "https://www.okx.com"
    url = f"{base}/api/v5/market/books?instId={symbol}&sz=50"
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        log_warning("orderbook_snapshot_fetch_error", exchange="okx", url=url, error=str(exc))
        return None
    data = payload.get("data") or []
    if not data:
        return None
    item = data[0]
    seq = item.get("seqId") or item.get("seq")
    try:
        seq_val = int(seq)
    except (TypeError, ValueError):
        seq_val = int(time.time() * 1000)
    snapshot = {
        "symbol": symbol,
        "timestamp": _coerce_ts(item.get("ts")),
        "seq": seq_val,
        "bids": item.get("bids") or [],
        "asks": item.get("asks") or [],
        "exchange": "okx",
        "seq_tolerant": True,
    }
    return {"type": "snapshot", "payload": snapshot}


def _fetch_bybit_snapshot(symbol: str, category: str, testnet: bool = False) -> Optional[dict]:
    base = "https://api-testnet.bybit.com" if testnet else "https://api.bybit.com"
    url = f"{base}/v5/market/orderbook?category={category}&symbol={symbol}&limit=50"
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        log_warning("orderbook_snapshot_fetch_error", exchange="bybit", url=url, error=str(exc))
        return None
    result = (payload.get("result") or {})
    seq = result.get("seq") or result.get("u")
    try:
        seq_val = int(seq)
    except (TypeError, ValueError):
        seq_val = int(time.time() * 1000)
    snapshot = {
        "symbol": symbol,
        "timestamp": _coerce_ts(result.get("ts") or payload.get("time")),
        "seq": seq_val,
        "bids": result.get("b") or [],
        "asks": result.get("a") or [],
    }
    return {"type": "snapshot", "payload": snapshot}


def _coerce_ts(value: Any) -> float:
    if value is None:
        return time.time()
    try:
        timestamp = float(value)
    except (TypeError, ValueError):
        return time.time()
    if timestamp > 1e12:
        return timestamp / 1000.0
    return timestamp


def _classify_okx_error(message: dict) -> Optional[dict]:
    if message.get("event") != "error":
        return None
    detail = message.get("msg") or message.get("message")
    code = str(message.get("code") or "")
    if "login" in str(detail).lower() or code in {"60001", "60002", "60003", "60004"}:
        return {"type": "auth_failed", "reason": "auth_failed", "detail": detail}
    return {"type": "error", "reason": "error", "detail": detail}


def _classify_bybit_error(message: dict) -> Optional[dict]:
    if "retCode" not in message:
        return None
    code = message.get("retCode")
    if code == 0:
        return None
    detail = message.get("retMsg")
    lower = str(detail).lower()
    if "auth" in lower or "permission" in lower:
        return {"type": "auth_failed", "reason": "auth_failed", "detail": detail}
    if code in {10001, 10002, 10003, 10004, 10005}:
        return {"type": "auth_failed", "reason": "auth_failed", "detail": detail}
    return {"type": "error", "reason": "error", "detail": detail}


def _classify_binance_error(message: dict) -> Optional[dict]:
    if message.get("e") == "error" or "code" in message:
        detail = message.get("msg") or message.get("message")
        lower = str(detail).lower()
        if "auth" in lower or "api-key" in lower:
            return {"type": "auth_failed", "reason": "auth_failed", "detail": detail}
        return {"type": "error", "reason": "error", "detail": detail}
    return None
