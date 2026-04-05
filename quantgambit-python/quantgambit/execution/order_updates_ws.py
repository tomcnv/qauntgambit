"""Private websocket order update providers for OKX/Bybit/Binance."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import time
import urllib.request
from dataclasses import dataclass
from typing import Any, Optional

try:
    import websockets  # type: ignore
except ImportError:  # pragma: no cover - optional dependency
    websockets = None

from quantgambit.execution.order_updates import OrderUpdate, OrderUpdateProvider
from quantgambit.execution.order_statuses import normalize_order_status
from quantgambit.execution.symbols import normalize_exchange_symbol
from quantgambit.observability.telemetry import TelemetryPipeline, TelemetryContext
from quantgambit.observability.logger import log_warning
from quantgambit.net.ws_connect import ws_connect_with_dns_fallback


@dataclass(frozen=True)
class OkxWsCredentials:
    api_key: str
    secret_key: str
    passphrase: str
    testnet: bool = False


@dataclass(frozen=True)
class BybitWsCredentials:
    api_key: str
    secret_key: str
    testnet: bool = False
    demo: bool = False


@dataclass(frozen=True)
class BinanceWsCredentials:
    api_key: str
    secret_key: str
    testnet: bool = False


@dataclass(frozen=True)
class OrderUpdateWsConfig:
    reconnect_delay_sec: float = 1.0
    max_reconnect_delay_sec: float = 10.0
    backoff_multiplier: float = 2.0
    message_timeout_sec: float = 30.0
    stale_guardrail_sec: float = 60.0


class OkxOrderUpdateProvider(OrderUpdateProvider):
    """OKX private websocket provider for order updates."""

    def __init__(self, creds: OkxWsCredentials, config: Optional[OrderUpdateWsConfig] = None, market_type: str = "perp"):
        self.creds = creds
        self.config = config or OrderUpdateWsConfig()
        self.market_type = (market_type or "perp").lower()
        self.exchange = "okx"
        self._ws = None
        self._endpoint = "wss://wspap.okx.com:8443/ws/v5/private" if creds.testnet else "wss://ws.okx.com:8443/ws/v5/private"
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._ws_ref = [None]
        self._telemetry: Optional[TelemetryPipeline] = None
        self._telemetry_ctx: Optional[TelemetryContext] = None
        self._last_auth_emit: float = 0.0
        self._last_backoff_emit: float = 0.0
        self._last_stale_emit: float = 0.0
        self._reconnect_attempts = 0
        self._reconnect_delay = self.config.reconnect_delay_sec

    async def next_update(self) -> Optional[OrderUpdate]:
        await self._ensure_connection()
        if not self._ws:
            await asyncio.sleep(self._reconnect_delay)
            return None
        try:
            if self.config.message_timeout_sec > 0:
                raw = await asyncio.wait_for(self._ws.recv(), timeout=self.config.message_timeout_sec)
            else:
                raw = await self._ws.recv()
        except Exception:
            self._emit_stale_guardrail("timeout")
            self._register_failure("timeout", None)
            await self._reset_connection()
            return None
        try:
            message = json.loads(raw)
        except json.JSONDecodeError:
            return None
        if _is_okx_auth_failure(message):
            await self._emit_auth_failure("login_failed", detail=message.get("msg"))
            return None
        update = _parse_okx_order_update(message)
        if update:
            update.symbol = normalize_exchange_symbol(self.exchange, update.symbol, market_type=self.market_type)
        return update

    async def _ensure_connection(self) -> None:
        if self._ws is not None:
            return
        _ensure_websockets()
        try:
            self._ws = await ws_connect_with_dns_fallback(self._endpoint)
        except Exception as exc:
            self._ws = None
            self._register_failure("connect_failed", detail=str(exc))
            return
        self._ws_ref[0] = self._ws
        await self._authenticate()
        login_ok = await self._wait_for_login()
        if not login_ok:
            await self._emit_auth_failure("login_failed")
            await self._reset_connection()
            return
        inst_type = "SPOT" if self.market_type == "spot" else "SWAP"
        await self._ws.send(json.dumps({"op": "subscribe", "args": [{"channel": "orders", "instType": inst_type}]}))
        self._start_heartbeat(20.0)
        self._reconnect_attempts = 0
        self._reconnect_delay = self.config.reconnect_delay_sec

    async def _wait_for_login(self, timeout_sec: float = 5.0) -> bool:
        if not self._ws:
            return False
        deadline = time.time() + timeout_sec
        while time.time() < deadline:
            try:
                raw = await asyncio.wait_for(self._ws.recv(), timeout=timeout_sec)
            except Exception:
                return False
            try:
                message = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if message.get("event") == "login":
                return message.get("code") == "0"
            if message.get("event") == "error" and message.get("code") == "60011":
                continue
        return False

    async def _authenticate(self) -> None:
        timestamp = str(time.time())
        sign_payload = f"{timestamp}GET/users/self/verify"
        signature = _sign_okx(sign_payload, self.creds.secret_key)
        payload = {
            "op": "login",
            "args": [
                {
                    "apiKey": self.creds.api_key,
                    "passphrase": self.creds.passphrase,
                    "timestamp": timestamp,
                    "sign": signature,
                }
            ],
        }
        await self._ws.send(json.dumps(payload))

    async def _reset_connection(self) -> None:
        await self._stop_heartbeat()
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
        self._ws = None
        self._ws_ref[0] = None

    def set_telemetry(self, telemetry: TelemetryPipeline, ctx: TelemetryContext) -> None:
        self._telemetry = telemetry
        self._telemetry_ctx = ctx

    async def _emit_auth_failure(self, reason: str, detail: Optional[str] = None) -> None:
        if not (self._telemetry and self._telemetry_ctx):
            return
        if time.time() - self._last_auth_emit < 60:
            return
        self._last_auth_emit = time.time()
        payload = {"type": "auth_failed", "provider": "order_updates", "exchange": "okx", "reason": reason}
        if detail:
            payload["detail"] = detail
        await self._telemetry.publish_guardrail(self._telemetry_ctx, payload)
        await self._telemetry.publish_health_snapshot(
            self._telemetry_ctx,
            {"status": "auth_failed", "provider": "order_updates", "exchange": "okx", "reason": reason},
        )

    def _register_failure(self, reason: str, detail: Optional[str]) -> None:
        self._reconnect_attempts += 1
        delay = self.config.reconnect_delay_sec * (self.config.backoff_multiplier ** (self._reconnect_attempts - 1))
        self._reconnect_delay = min(self.config.max_reconnect_delay_sec, delay)
        log_warning(
            "order_updates_ws_backoff",
            exchange="okx",
            reason=reason,
            delay_sec=self._reconnect_delay,
            attempt=self._reconnect_attempts,
        )
        self._emit_backoff(reason, detail, self._reconnect_delay, self._reconnect_attempts)

    def _emit_stale_guardrail(self, reason: str) -> None:
        if not (self._telemetry and self._telemetry_ctx):
            return
        now = time.time()
        if now - self._last_stale_emit < self.config.stale_guardrail_sec:
            return
        self._last_stale_emit = now
        payload = {"type": "ws_stale", "provider": "order_updates", "exchange": "okx", "reason": reason}
        asyncio.create_task(self._telemetry.publish_guardrail(self._telemetry_ctx, payload))
        asyncio.create_task(
            self._telemetry.publish_health_snapshot(
                self._telemetry_ctx,
                {"status": "stale", "provider": "order_updates", "exchange": "okx", "reason": reason},
            )
        )

    def _emit_backoff(self, reason: str, detail: Optional[str], delay: float, attempt: int) -> None:
        if not (self._telemetry and self._telemetry_ctx):
            return
        now = time.time()
        if now - self._last_backoff_emit < 5:
            return
        self._last_backoff_emit = now
        payload = {
            "type": "ws_backoff",
            "provider": "order_updates",
            "exchange": "okx",
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
                {"status": "reconnecting", "provider": "order_updates", "exchange": "okx", "reason": reason},
            )
        )

    def _start_heartbeat(self, interval_sec: float) -> None:
        if self._heartbeat_task:
            return
        self._heartbeat_task = asyncio.create_task(_ping_loop(self._ws_ref, interval_sec))

    async def _stop_heartbeat(self) -> None:
        if not self._heartbeat_task:
            return
        self._heartbeat_task.cancel()
        try:
            await self._heartbeat_task
        except asyncio.CancelledError:
            pass
        except Exception:
            pass
        self._heartbeat_task = None


class BybitOrderUpdateProvider(OrderUpdateProvider):
    """Bybit private websocket provider for order updates."""

    def __init__(self, creds: BybitWsCredentials, config: Optional[OrderUpdateWsConfig] = None, market_type: str = "perp"):
        from quantgambit.observability.logger import log_info
        self.creds = creds
        self.config = config or OrderUpdateWsConfig()
        self.market_type = (market_type or "perp").lower()
        self.exchange = "bybit"
        self._ws = None
        # Bybit has three environments: mainnet, testnet, and demo
        if creds.demo:
            self._endpoint = "wss://stream-demo.bybit.com/v5/private"
        elif creds.testnet:
            self._endpoint = "wss://stream-testnet.bybit.com/v5/private"
        else:
            self._endpoint = "wss://stream.bybit.com/v5/private"
        log_info(
            "bybit_order_update_provider_init",
            endpoint=self._endpoint,
            is_demo=creds.demo,
            is_testnet=creds.testnet,
            market_type=self.market_type,
        )
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._ws_ref = [None]
        self._telemetry: Optional[TelemetryPipeline] = None
        self._telemetry_ctx: Optional[TelemetryContext] = None
        self._last_auth_emit: float = 0.0
        self._last_backoff_emit: float = 0.0
        self._last_stale_emit: float = 0.0
        self._reconnect_attempts = 0
        self._reconnect_delay = self.config.reconnect_delay_sec

    async def next_update(self) -> Optional[OrderUpdate]:
        await self._ensure_connection()
        if not self._ws:
            await asyncio.sleep(self._reconnect_delay)
            return None
        try:
            if self.config.message_timeout_sec > 0:
                raw = await asyncio.wait_for(self._ws.recv(), timeout=self.config.message_timeout_sec)
            else:
                raw = await self._ws.recv()
        except asyncio.TimeoutError:
            # Timeout waiting for order updates is NORMAL - order updates are sparse
            # Only happen when orders are placed/modified/filled
            # Don't treat this as a failure if the connection is still alive
            # The heartbeat ping keeps the connection alive
            return None
        except websockets.exceptions.ConnectionClosed as exc:
            # Connection was actually closed - this is a real failure
            log_warning(
                "order_updates_ws_connection_closed",
                exchange="bybit",
                code=exc.code if hasattr(exc, 'code') else None,
                reason=str(exc),
            )
            self._register_failure("connection_closed", detail=str(exc))
            await self._reset_connection()
            return None
        except Exception as exc:
            # Other errors - treat as failure
            self._emit_stale_guardrail("error")
            self._register_failure("recv_error", detail=str(exc))
            await self._reset_connection()
            return None
        try:
            message = json.loads(raw)
        except json.JSONDecodeError:
            return None
        if _is_bybit_auth_failure(message):
            await self._emit_auth_failure("auth_failed", detail=message.get("retMsg"))
            return None
        update = _parse_bybit_order_update(message)
        if update:
            update.symbol = normalize_exchange_symbol(self.exchange, update.symbol, market_type=self.market_type)
        return update

    async def _ensure_connection(self) -> None:
        if self._ws is not None:
            return
        _ensure_websockets()
        from quantgambit.observability.logger import log_info
        log_info(
            "bybit_order_ws_connecting",
            endpoint=self._endpoint,
            is_demo=self.creds.demo,
            is_testnet=self.creds.testnet,
        )
        try:
            self._ws = await asyncio.wait_for(
                ws_connect_with_dns_fallback(
                    self._endpoint,
                    open_timeout=10.0,
                    ping_interval=20.0,
                    ping_timeout=20.0,
                ),
                timeout=10.0,
            )
        except Exception as exc:
            self._ws = None
            log_warning(
                "bybit_order_ws_connect_failed",
                endpoint=self._endpoint,
                is_demo=self.creds.demo,
                is_testnet=self.creds.testnet,
                error=str(exc),
            )
            self._register_failure("connect_failed", detail=str(exc))
            return
        self._ws_ref[0] = self._ws
        
        # Authenticate and wait for response
        auth_ok = await self._authenticate()
        if not auth_ok:
            log_warning("bybit_order_ws_auth_failed", endpoint=self._endpoint)
            await self._reset_connection()
            return
        
        # Subscribe to order updates
        topic = "order.spot" if self.market_type == "spot" else "order"
        await self._ws.send(json.dumps({"op": "subscribe", "args": [topic]}))
        
        # Wait for subscribe response
        try:
            sub_response = await asyncio.wait_for(self._ws.recv(), timeout=5.0)
            sub_data = json.loads(sub_response)
            if sub_data.get("success") is True:
                log_info(
                    "bybit_order_ws_subscribed",
                    topic=topic,
                    conn_id=sub_data.get("conn_id"),
                )
            else:
                log_warning(
                    "bybit_order_ws_subscribe_failed",
                    response=sub_response,
                )
        except asyncio.TimeoutError:
            log_warning("bybit_order_ws_subscribe_timeout")
        except Exception as exc:
            log_warning("bybit_order_ws_subscribe_error", error=str(exc))
        
        self._start_heartbeat(20.0)
        self._reconnect_attempts = 0
        self._reconnect_delay = self.config.reconnect_delay_sec
        log_info(
            "bybit_order_ws_connected",
            endpoint=self._endpoint,
            is_demo=self.creds.demo,
        )

    async def _authenticate(self) -> bool:
        """Authenticate with Bybit WebSocket and wait for response."""
        expires = int(time.time() * 1000) + 10000
        sign_payload = f"GET/realtime{expires}"
        signature = _sign_hmac(sign_payload, self.creds.secret_key)
        payload = {"op": "auth", "args": [self.creds.api_key, expires, signature]}
        await self._ws.send(json.dumps(payload))
        
        # Wait for auth response
        try:
            response = await asyncio.wait_for(self._ws.recv(), timeout=10.0)
            data = json.loads(response)
            if data.get("success") is True:
                from quantgambit.observability.logger import log_info
                log_info(
                    "bybit_order_ws_auth_success",
                    conn_id=data.get("conn_id"),
                )
                return True
            else:
                log_warning(
                    "bybit_order_ws_auth_rejected",
                    ret_msg=data.get("ret_msg"),
                    ret_code=data.get("ret_code"),
                )
                return False
        except asyncio.TimeoutError:
            log_warning("bybit_order_ws_auth_timeout")
            return False
        except Exception as exc:
            log_warning("bybit_order_ws_auth_error", error=str(exc))
            return False

    async def _reset_connection(self) -> None:
        await self._stop_heartbeat()
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
        self._ws = None
        self._ws_ref[0] = None

    def set_telemetry(self, telemetry: TelemetryPipeline, ctx: TelemetryContext) -> None:
        self._telemetry = telemetry
        self._telemetry_ctx = ctx

    async def _emit_auth_failure(self, reason: str, detail: Optional[str] = None) -> None:
        if not (self._telemetry and self._telemetry_ctx):
            return
        if time.time() - self._last_auth_emit < 60:
            return
        self._last_auth_emit = time.time()
        payload = {"type": "auth_failed", "provider": "order_updates", "exchange": "bybit", "reason": reason}
        if detail:
            payload["detail"] = detail
        await self._telemetry.publish_guardrail(self._telemetry_ctx, payload)
        await self._telemetry.publish_health_snapshot(
            self._telemetry_ctx,
            {"status": "auth_failed", "provider": "order_updates", "exchange": "bybit", "reason": reason},
        )

    def _register_failure(self, reason: str, detail: Optional[str]) -> None:
        self._reconnect_attempts += 1
        delay = self.config.reconnect_delay_sec * (self.config.backoff_multiplier ** (self._reconnect_attempts - 1))
        self._reconnect_delay = min(self.config.max_reconnect_delay_sec, delay)
        log_warning(
            "order_updates_ws_backoff",
            exchange="bybit",
            reason=reason,
            delay_sec=self._reconnect_delay,
            attempt=self._reconnect_attempts,
        )
        self._emit_backoff(reason, detail, self._reconnect_delay, self._reconnect_attempts)

    def _emit_stale_guardrail(self, reason: str) -> None:
        if not (self._telemetry and self._telemetry_ctx):
            return
        now = time.time()
        if now - self._last_stale_emit < self.config.stale_guardrail_sec:
            return
        self._last_stale_emit = now
        payload = {"type": "ws_stale", "provider": "order_updates", "exchange": "bybit", "reason": reason}
        asyncio.create_task(self._telemetry.publish_guardrail(self._telemetry_ctx, payload))
        asyncio.create_task(
            self._telemetry.publish_health_snapshot(
                self._telemetry_ctx,
                {"status": "stale", "provider": "order_updates", "exchange": "bybit", "reason": reason},
            )
        )

    def _emit_backoff(self, reason: str, detail: Optional[str], delay: float, attempt: int) -> None:
        if not (self._telemetry and self._telemetry_ctx):
            return
        now = time.time()
        if now - self._last_backoff_emit < 5:
            return
        self._last_backoff_emit = now
        payload = {
            "type": "ws_backoff",
            "provider": "order_updates",
            "exchange": "bybit",
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
                {"status": "reconnecting", "provider": "order_updates", "exchange": "bybit", "reason": reason},
            )
        )

    def _start_heartbeat(self, interval_sec: float) -> None:
        if self._heartbeat_task:
            return
        self._heartbeat_task = asyncio.create_task(_ping_loop(self._ws_ref, interval_sec))

    async def _stop_heartbeat(self) -> None:
        if not self._heartbeat_task:
            return
        self._heartbeat_task.cancel()
        try:
            await self._heartbeat_task
        except asyncio.CancelledError:
            pass
        except Exception:
            pass
        self._heartbeat_task = None


class BinanceOrderUpdateProvider(OrderUpdateProvider):
    """Binance private websocket provider using listenKey."""

    def __init__(self, creds: BinanceWsCredentials, config: Optional[OrderUpdateWsConfig] = None, market_type: str = "perp"):
        self.creds = creds
        self.config = config or OrderUpdateWsConfig()
        self.market_type = (market_type or "perp").lower()
        self.exchange = "binance"
        self._ws = None
        self._listen_key: Optional[str] = None
        if self.market_type == "spot":
            self._rest_base = "https://testnet.binance.vision" if creds.testnet else "https://api.binance.com"
            # Binance testnet requires explicit :9443 port per docs
            self._ws_base = (
                "wss://stream.testnet.binance.vision:9443/ws"
                if creds.testnet
                else "wss://stream.binance.com:9443/ws"
            )
        else:
            self._rest_base = "https://testnet.binancefuture.com" if creds.testnet else "https://fapi.binance.com"
            # Futures testnet uses stream.binancefuture.com (not fstream)
            self._ws_base = "wss://stream.binancefuture.com/ws" if creds.testnet else "wss://fstream.binance.com/ws"
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._listen_keepalive_task: Optional[asyncio.Task] = None
        self._ws_ref = [None]
        self._telemetry: Optional[TelemetryPipeline] = None
        self._telemetry_ctx: Optional[TelemetryContext] = None
        self._last_auth_emit: float = 0.0
        self._last_backoff_emit: float = 0.0
        self._last_stale_emit: float = 0.0
        self._reconnect_attempts = 0
        self._reconnect_delay = self.config.reconnect_delay_sec

    async def next_update(self) -> Optional[OrderUpdate]:
        await self._ensure_connection()
        if not self._ws:
            await asyncio.sleep(self._reconnect_delay)
            return None
        try:
            if self.config.message_timeout_sec > 0:
                raw = await asyncio.wait_for(self._ws.recv(), timeout=self.config.message_timeout_sec)
            else:
                raw = await self._ws.recv()
        except Exception:
            self._emit_stale_guardrail("timeout")
            self._register_failure("timeout", None)
            await self._reset_connection()
            return None
        try:
            message = json.loads(raw)
        except json.JSONDecodeError:
            return None
        if self.market_type == "spot":
            update = _parse_binance_spot_order_update(message)
        else:
            update = _parse_binance_order_update(message)
        if update:
            update.symbol = normalize_exchange_symbol(self.exchange, update.symbol, market_type=self.market_type)
        return update

    async def _ensure_connection(self) -> None:
        if self._ws is not None:
            return
        _ensure_websockets()
        listen_key = self._listen_key or await self._fetch_listen_key()
        if not listen_key:
            return
        self._listen_key = listen_key
        endpoint = f"{self._ws_base}/{listen_key}"
        try:
            self._ws = await websockets.connect(endpoint)
        except Exception as exc:
            self._ws = None
            self._register_failure("connect_failed", detail=str(exc))
            return
        self._ws_ref[0] = self._ws
        self._start_heartbeat(20.0)
        self._start_keepalive(25 * 60)
        self._reconnect_attempts = 0
        self._reconnect_delay = self.config.reconnect_delay_sec

    async def _fetch_listen_key(self) -> Optional[str]:
        path = "/api/v3/userDataStream" if self.market_type == "spot" else "/fapi/v1/listenKey"
        url = f"{self._rest_base}{path}"
        req = urllib.request.Request(url, method="POST", headers={"X-MBX-APIKEY": self.creds.api_key})
        try:
            payload = await asyncio.to_thread(_http_json, req)
        except Exception as exc:
            await self._emit_auth_failure_if_needed("listen_key_fetch_failed", detail=str(exc))
            self._register_failure("listen_key_fetch_failed", detail=str(exc))
            return None
        return payload.get("listenKey")

    async def _reset_connection(self) -> None:
        await self._stop_heartbeat()
        await self._stop_keepalive()
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
        self._ws = None
        self._ws_ref[0] = None

    def set_telemetry(self, telemetry: TelemetryPipeline, ctx: TelemetryContext) -> None:
        self._telemetry = telemetry
        self._telemetry_ctx = ctx

    async def _emit_auth_failure_if_needed(self, reason: str, detail: Optional[str] = None) -> None:
        if not (self._telemetry and self._telemetry_ctx):
            return
        if time.time() - self._last_auth_emit < 60:
            return
        self._last_auth_emit = time.time()
        payload = {"type": "auth_failed", "provider": "order_updates", "exchange": "binance", "reason": reason}
        if detail:
            payload["detail"] = detail
        await self._telemetry.publish_guardrail(self._telemetry_ctx, payload)
        await self._telemetry.publish_health_snapshot(
            self._telemetry_ctx,
            {"status": "auth_failed", "provider": "order_updates", "exchange": "binance", "reason": reason},
        )

    def _start_heartbeat(self, interval_sec: float) -> None:
        if self._heartbeat_task:
            return
        self._heartbeat_task = asyncio.create_task(_ping_loop(self._ws_ref, interval_sec))

    async def _stop_heartbeat(self) -> None:
        if not self._heartbeat_task:
            return
        self._heartbeat_task.cancel()
        try:
            await self._heartbeat_task
        except asyncio.CancelledError:
            pass
        except Exception:
            pass
        self._heartbeat_task = None

    def _start_keepalive(self, interval_sec: float) -> None:
        if self._listen_keepalive_task:
            return
        self._listen_keepalive_task = asyncio.create_task(self._listen_key_keepalive(interval_sec))

    async def _stop_keepalive(self) -> None:
        if not self._listen_keepalive_task:
            return
        self._listen_keepalive_task.cancel()
        try:
            await self._listen_keepalive_task
        except asyncio.CancelledError:
            pass
        except Exception:
            pass
        self._listen_keepalive_task = None

    async def _listen_key_keepalive(self, interval_sec: float) -> None:
        while True:
            await asyncio.sleep(interval_sec)
            if not self._listen_key:
                continue
            path = "/api/v3/userDataStream" if self.market_type == "spot" else "/fapi/v1/listenKey"
            url = f"{self._rest_base}{path}"
            req = urllib.request.Request(
                url,
                method="PUT",
                headers={"X-MBX-APIKEY": self.creds.api_key},
            )
            try:
                await asyncio.to_thread(_http_json, req)
            except Exception as exc:
                await self._emit_auth_failure_if_needed("listen_key_keepalive_failed", detail=str(exc))
                self._register_failure("listen_key_keepalive_failed", detail=str(exc))
                continue
            self._reconnect_attempts = 0
            self._reconnect_delay = self.config.reconnect_delay_sec

    def _register_failure(self, reason: str, detail: Optional[str]) -> None:
        self._reconnect_attempts += 1
        delay = self.config.reconnect_delay_sec * (self.config.backoff_multiplier ** (self._reconnect_attempts - 1))
        self._reconnect_delay = min(self.config.max_reconnect_delay_sec, delay)
        log_warning(
            "order_updates_ws_backoff",
            exchange="binance",
            reason=reason,
            delay_sec=self._reconnect_delay,
            attempt=self._reconnect_attempts,
        )
        self._emit_backoff(reason, detail, self._reconnect_delay, self._reconnect_attempts)

    def _emit_stale_guardrail(self, reason: str) -> None:
        if not (self._telemetry and self._telemetry_ctx):
            return
        now = time.time()
        if now - self._last_stale_emit < self.config.stale_guardrail_sec:
            return
        self._last_stale_emit = now
        payload = {"type": "ws_stale", "provider": "order_updates", "exchange": "binance", "reason": reason}
        asyncio.create_task(self._telemetry.publish_guardrail(self._telemetry_ctx, payload))
        asyncio.create_task(
            self._telemetry.publish_health_snapshot(
                self._telemetry_ctx,
                {"status": "stale", "provider": "order_updates", "exchange": "binance", "reason": reason},
            )
        )

    def _emit_backoff(self, reason: str, detail: Optional[str], delay: float, attempt: int) -> None:
        if not (self._telemetry and self._telemetry_ctx):
            return
        now = time.time()
        if now - self._last_backoff_emit < 5:
            return
        self._last_backoff_emit = now
        payload = {
            "type": "ws_backoff",
            "provider": "order_updates",
            "exchange": "binance",
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
                {"status": "reconnecting", "provider": "order_updates", "exchange": "binance", "reason": reason},
            )
        )


def _parse_okx_order_update(message: dict) -> Optional[OrderUpdate]:
    if message.get("event") or message.get("code"):
        return None
    data = message.get("data") or []
    if not data:
        return None
    item = data[0]
    symbol = item.get("instId")
    side = _normalize_side(item.get("side"))
    status = item.get("state") or item.get("status")
    order_type = item.get("ordType")
    algo_client_id = item.get("algoClOrdId") or ""
    tp_trigger = item.get("tpTriggerPx") or item.get("tpOrdPx")
    sl_trigger = item.get("slTriggerPx") or item.get("slOrdPx")
    reduce_only = _coerce_bool(item.get("reduceOnly"))
    size = _to_float(item.get("sz") or item.get("accFillSz"))
    filled = _to_float(item.get("accFillSz"))
    if not symbol or not side or size is None or not status:
        return None
    close_reason = _infer_close_reason(
        order_type=order_type,
        reduce_only=reduce_only,
        tp_trigger=tp_trigger,
        sl_trigger=sl_trigger,
    )
    if not close_reason and algo_client_id:
        algo_norm = algo_client_id.strip().lower()
        if "tpsl" in algo_norm:
            close_reason = "protective_tpsl"
        elif "oco" in algo_norm:
            close_reason = "protective_oco"
    position_effect = "close" if reduce_only or close_reason else None
    return OrderUpdate(
        symbol=symbol,
        side=side,
        size=size,
        status=_normalize_status(status),
        timestamp=_coerce_ts(item.get("uTime") or item.get("ts")),
        order_id=item.get("ordId"),
        client_order_id=item.get("clOrdId"),
        fill_price=_to_float(item.get("avgPx") or item.get("fillPx")),
        fee_usd=_to_float(item.get("fee") or item.get("feeUsd")),
        filled_size=filled,
        remaining_size=_remaining_size(size, filled),
        close_reason=close_reason,
        position_effect=position_effect,
    )


def _parse_bybit_order_update(message: dict) -> Optional[OrderUpdate]:
    topic = message.get("topic")
    if topic not in {"order", "order.spot"}:
        return None
    data = message.get("data") or []
    if not data:
        return None
    item = data[0]
    symbol = item.get("symbol")
    side = _normalize_side(item.get("side"))
    status = item.get("orderStatus") or item.get("status")
    order_type = item.get("orderType")
    stop_order_type = item.get("stopOrderType")
    reduce_only = _coerce_bool(item.get("reduceOnly"))
    close_on_trigger = _coerce_bool(item.get("closeOnTrigger"))
    size = _to_float(item.get("qty") or item.get("orderQty") or item.get("cumExecQty"))
    filled = _to_float(item.get("cumExecQty"))
    if not symbol or not side or size is None or not status:
        return None
    close_reason = _infer_close_reason(
        order_type=order_type,
        stop_order_type=stop_order_type,
        reduce_only=reduce_only,
        close_on_trigger=close_on_trigger,
    )
    position_effect = "close" if reduce_only or close_reason else None
    avg_price = _to_float(item.get("avgPrice") or item.get("avg_price"))
    if not avg_price or avg_price == 0:
        cum_value = _to_float(item.get("cumExecValue") or item.get("cumExecQuote") or item.get("cumExecValueE8"))
        if cum_value is not None and item.get("cumExecValueE8"):
            # Bybit may return value scaled by 1e8
            cum_value = cum_value / 1e8
        if cum_value and filled:
            avg_price = cum_value / filled
    fallback_price = _to_float(item.get("price"))
    fill_price = avg_price or fallback_price
    return OrderUpdate(
        symbol=symbol.upper(),
        side=side,
        size=size,
        status=_normalize_status(status),
        timestamp=_coerce_ts(item.get("updatedTime") or item.get("createdTime")),
        order_id=item.get("orderId"),
        client_order_id=item.get("orderLinkId"),
        fill_price=fill_price,
        fee_usd=_to_float(item.get("cumExecFee")),
        filled_size=filled,
        remaining_size=_remaining_size(size, filled),
        close_reason=close_reason,
        position_effect=position_effect,
    )


def _parse_binance_order_update(message: dict) -> Optional[OrderUpdate]:
    if message.get("e") != "ORDER_TRADE_UPDATE":
        return None
    data = message.get("o") or {}
    symbol = data.get("s")
    side = _normalize_side(data.get("S"))
    status = data.get("X") or data.get("x")
    order_type = data.get("o")
    reduce_only = _coerce_bool(data.get("R"))
    close_position = _coerce_bool(data.get("cp"))
    size = _to_float(data.get("q") or data.get("z") or data.get("l"))
    filled = _to_float(data.get("z") or data.get("l"))
    if not symbol or not side or size is None or not status:
        return None
    close_reason = _infer_close_reason(
        order_type=order_type,
        reduce_only=reduce_only,
        close_position=close_position,
    )
    position_effect = "close" if reduce_only or close_position or close_reason else None
    return OrderUpdate(
        symbol=symbol.upper(),
        side=side,
        size=size,
        status=_normalize_status(status),
        timestamp=_coerce_ts(message.get("E")),
        order_id=str(data.get("i")) if data.get("i") is not None else None,
        client_order_id=data.get("c"),
        fill_price=_to_float(data.get("ap") or data.get("L")),
        fee_usd=_to_float(data.get("n")),
        filled_size=filled,
        remaining_size=_remaining_size(size, filled),
        close_reason=close_reason,
        position_effect=position_effect,
    )


def _parse_binance_spot_order_update(message: dict) -> Optional[OrderUpdate]:
    if message.get("e") != "executionReport":
        return None
    symbol = message.get("s")
    side = _normalize_side(message.get("S"))
    status = message.get("X")
    order_type = message.get("o")
    size = _to_float(message.get("q") or message.get("z") or message.get("l"))
    filled = _to_float(message.get("z") or message.get("l"))
    if not symbol or not side or size is None or not status:
        return None
    close_reason = _infer_close_reason(order_type=order_type)
    position_effect = "close" if close_reason else None
    return OrderUpdate(
        symbol=symbol.upper(),
        side=side,
        size=size,
        status=_normalize_status(status),
        timestamp=_coerce_ts(message.get("E")),
        order_id=str(message.get("i")) if message.get("i") is not None else None,
        client_order_id=message.get("c"),
        fill_price=_to_float(message.get("L") or message.get("p")),
        fee_usd=_to_float(message.get("n")),
        filled_size=filled,
        remaining_size=_remaining_size(size, filled),
        close_reason=close_reason,
        position_effect=position_effect,
    )


def _ensure_websockets() -> None:
    if websockets is None:
        raise RuntimeError("websockets dependency is required for private order updates")


async def _ping_loop(ws_ref: list, interval_sec: float) -> None:
    while True:
        await asyncio.sleep(interval_sec)
        ws = ws_ref[0]
        if not ws:
            continue
        try:
            await ws.ping()
        except Exception:
            return


def _sign_okx(payload: str, secret: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).digest()
    return base64.b64encode(digest).decode("utf-8")


def _sign_hmac(payload: str, secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()


def _normalize_side(side: Optional[str]) -> Optional[str]:
    if not side:
        return None
    normalized = side.lower()
    if normalized in {"buy", "sell"}:
        return normalized
    if normalized in {"bid"}:
        return "buy"
    if normalized in {"ask"}:
        return "sell"
    return normalized


def _normalize_status(status: str) -> str:
    return normalize_order_status(status)


def _to_float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _coerce_bool(value: Any) -> Optional[bool]:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"true", "1", "yes", "y"}:
        return True
    if text in {"false", "0", "no", "n"}:
        return False
    return None


def _infer_close_reason(
    order_type: Optional[str],
    stop_order_type: Optional[str] = None,
    reduce_only: Optional[bool] = None,
    close_position: Optional[bool] = None,
    close_on_trigger: Optional[bool] = None,
    tp_trigger: Optional[str] = None,
    sl_trigger: Optional[str] = None,
) -> Optional[str]:
    if tp_trigger not in (None, "", "0", "0.0"):
        return "take_profit_hit"
    if sl_trigger not in (None, "", "0", "0.0"):
        return "stop_loss_hit"
    if stop_order_type:
        normalized = stop_order_type.strip().lower()
        if "take" in normalized and "profit" in normalized:
            return "take_profit_hit"
        if "stop" in normalized:
            return "stop_loss_hit"
    normalized = (order_type or "").strip().lower()
    if "take" in normalized and "profit" in normalized:
        return "take_profit_hit"
    if "stop" in normalized and "trailing" in normalized:
        return "trailing_stop_hit"
    if "stop" in normalized:
        return "stop_loss_hit"
    if "oco" in normalized:
        return "protective_oco"
    if "tpsl" in normalized or ("tp" in normalized and "sl" in normalized):
        return "protective_tpsl"
    if reduce_only or close_position or close_on_trigger:
        return "position_close"
    return None


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


def _remaining_size(size: Optional[float], filled: Optional[float]) -> Optional[float]:
    if size is None or filled is None:
        return None
    remaining = size - filled
    return remaining if remaining >= 0 else 0.0


def _http_json(request: urllib.request.Request) -> dict:
    with urllib.request.urlopen(request, timeout=5) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _is_okx_auth_failure(message: dict) -> bool:
    if message.get("event") != "login":
        return False
    return str(message.get("code")) not in {"0", "None", "none", ""}


def _is_bybit_auth_failure(message: dict) -> bool:
    if message.get("op") != "auth":
        return False
    success = message.get("success")
    if success is False:
        return True
    ret_code = message.get("retCode")
    return ret_code not in (0, "0", None)
