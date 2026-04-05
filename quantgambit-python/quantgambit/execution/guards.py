"""Execution guards: rate limiting and circuit breaker."""

from __future__ import annotations

import time
from dataclasses import dataclass
import asyncio
from typing import Optional

from quantgambit.execution.manager import ExchangeClient, OrderStatus
from quantgambit.observability.telemetry import TelemetryContext, TelemetryPipeline


@dataclass(frozen=True)
class GuardConfig:
    max_calls_per_sec: float = 5.0
    failure_threshold: int = 5
    reset_after_sec: float = 10.0


class RateLimiter:
    """Token bucket rate limiter."""

    def __init__(self, max_calls_per_sec: float):
        self.max_calls_per_sec = max_calls_per_sec
        self._tokens = max_calls_per_sec
        self._last_refill = time.time()

    def allow(self) -> bool:
        now = time.time()
        elapsed = now - self._last_refill
        self._last_refill = now
        self._tokens = min(self.max_calls_per_sec, self._tokens + elapsed * self.max_calls_per_sec)
        if self._tokens >= 1:
            self._tokens -= 1
            return True
        return False


class CircuitBreaker:
    """Simple circuit breaker for repeated failures."""

    def __init__(self, failure_threshold: int, reset_after_sec: float):
        self.failure_threshold = failure_threshold
        self.reset_after_sec = reset_after_sec
        self._base_reset_sec = reset_after_sec
        self._max_reset_sec = max(reset_after_sec * 32, 300.0)  # Cap at ~5 min
        self._failures = 0
        self._consecutive_trips = 0
        self._opened_at: Optional[float] = None

    def allow(self) -> bool:
        if self._opened_at is None:
            return True
        if time.time() - self._opened_at >= self.reset_after_sec:
            self._opened_at = None
            self._failures = 0
            return True
        return False

    def record_success(self) -> None:
        self._failures = 0
        self._consecutive_trips = 0
        self.reset_after_sec = self._base_reset_sec
        self._opened_at = None

    def record_failure(self) -> None:
        self._failures += 1
        if self._failures >= self.failure_threshold:
            self._consecutive_trips += 1
            # Exponential backoff: double reset time on each consecutive trip
            self.reset_after_sec = min(
                self._base_reset_sec * (2 ** self._consecutive_trips),
                self._max_reset_sec,
            )
            self._opened_at = time.time()


class GuardedExchangeClient(ExchangeClient):
    """Wrap exchange client with rate limiting and circuit breaker."""

    def __init__(
        self,
        inner: ExchangeClient,
        config: GuardConfig,
        telemetry: TelemetryPipeline | None = None,
        telemetry_context: TelemetryContext | None = None,
    ):
        self._inner = inner
        self._rate_limiter = RateLimiter(config.max_calls_per_sec)
        self._breaker = CircuitBreaker(config.failure_threshold, config.reset_after_sec)
        self._telemetry = telemetry
        self._telemetry_context = telemetry_context

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
        block_reason = self._allow_reason(symbol, "close")
        if block_reason:
            return OrderStatus(order_id=None, status="rejected", reason=block_reason)
        try:
            result = await self._inner.close_position(
                symbol,
                side,
                size,
                client_order_id=client_order_id,
                order_type=order_type,
                limit_price=limit_price,
                post_only=post_only,
                time_in_force=time_in_force,
            )
        except Exception as exc:
            self._breaker.record_failure()
            # Pass exception info in reason so caller can detect specific errors like "position is zero"
            return OrderStatus(order_id=None, status="rejected", reason=f"exchange_error: {str(exc)[:500]}")
        self._record_result(result.status)
        return result

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
        block_reason = self._allow_reason(symbol, "open")
        if block_reason:
            return OrderStatus(order_id=None, status="rejected", reason=block_reason)
        try:
            result = await self._inner.open_position(
                symbol,
                side,
                size,
                order_type=order_type,
                limit_price=limit_price,
                post_only=post_only,
                time_in_force=time_in_force,
                stop_loss=stop_loss,
                take_profit=take_profit,
                client_order_id=client_order_id,
            )
        except Exception as exc:
            self._breaker.record_failure()
            return OrderStatus(order_id=None, status="rejected", reason=f"exchange_error: {str(exc)[:500]}")
        self._record_result(result.status)
        return result

    async def fetch_order_status(self, order_id: str, symbol: str) -> Optional[OrderStatus]:
        try:
            return await self._inner.fetch_order_status(order_id, symbol)
        except Exception:
            return None

    async def fetch_order_status_by_client_id(self, client_order_id: str, symbol: str) -> Optional[OrderStatus]:
        if not hasattr(self._inner, "fetch_order_status_by_client_id"):
            return None
        try:
            return await self._inner.fetch_order_status_by_client_id(client_order_id, symbol)
        except Exception:
            return None

    async def cancel_order(
        self,
        order_id: Optional[str],
        client_order_id: Optional[str],
        symbol: Optional[str],
    ) -> OrderStatus:
        if not self._allow(symbol, "cancel"):
            return OrderStatus(order_id=order_id or client_order_id, status="rejected", reason="guard_blocked")
        if not hasattr(self._inner, "cancel_order"):
            return OrderStatus(order_id=order_id or client_order_id, status="rejected", reason="cancel_not_supported")
        try:
            result = await self._inner.cancel_order(order_id, client_order_id, symbol)
        except Exception as exc:
            self._breaker.record_failure()
            return OrderStatus(
                order_id=order_id or client_order_id,
                status="rejected",
                reason=f"exchange_error: {str(exc)[:500]}",
            )
        self._record_result(result.status)
        return result

    async def replace_order(
        self,
        order_id: Optional[str],
        client_order_id: Optional[str],
        symbol: Optional[str],
        price: Optional[float],
        size: Optional[float],
    ) -> OrderStatus:
        if not self._allow(symbol, "replace"):
            return OrderStatus(order_id=order_id or client_order_id, status="rejected", reason="guard_blocked")
        if not hasattr(self._inner, "replace_order"):
            return OrderStatus(order_id=order_id or client_order_id, status="rejected", reason="replace_not_supported")
        try:
            result = await self._inner.replace_order(order_id, client_order_id, symbol, price, size)
        except Exception as exc:
            self._breaker.record_failure()
            return OrderStatus(
                order_id=order_id or client_order_id,
                status="rejected",
                reason=f"exchange_error: {str(exc)[:500]}",
            )
        self._record_result(result.status)
        return result

    async def place_protective_orders(
        self,
        symbol: str,
        side: str,
        size: float,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
        client_order_id: Optional[str] = None,
    ) -> bool:
        if not self._allow(symbol, "protective"):
            return False
        if not hasattr(self._inner, "place_protective_orders"):
            return False
        try:
            return await self._inner.place_protective_orders(
                symbol,
                side,
                size,
                stop_loss=stop_loss,
                take_profit=take_profit,
                client_order_id=client_order_id,
            )
        except Exception:
            self._breaker.record_failure()
            return False

    async def fetch_balance(self, currency: str = "USDT") -> Optional[float]:
        """Fetch account equity from exchange.
        
        Delegates to the inner client without rate limiting (balance fetch is
        low frequency and shouldn't count against order limits).
        """
        if not hasattr(self._inner, "fetch_balance"):
            return None
        try:
            return await self._inner.fetch_balance(currency)
        except Exception:
            return None

    async def fetch_positions(self, symbols: Optional[list[str]] = None) -> list:
        """Fetch positions from exchange, delegating to the inner client."""
        if not hasattr(self._inner, "fetch_positions"):
            return []
        try:
            return await self._inner.fetch_positions(symbols)
        except Exception:
            return []

    async def fetch_executions(
        self,
        symbol: str,
        since_ms: Optional[int] = None,
        limit: int = 100,
        order_id: Optional[str] = None,
        client_order_id: Optional[str] = None,
    ) -> list:
        """Fetch executions/trades from exchange."""
        if not hasattr(self._inner, "fetch_executions"):
            return []
        try:
            return await self._inner.fetch_executions(
                symbol=symbol,
                since_ms=since_ms,
                limit=limit,
                order_id=order_id,
                client_order_id=client_order_id,
            )
        except Exception:
            return []

    @property
    def inner(self) -> ExchangeClient:
        """Expose inner client for introspection (e.g., equity refresh)."""
        return self._inner

    def _allow_reason(self, symbol: Optional[str], operation: str) -> Optional[str]:
        if not self._rate_limiter.allow():
            self._emit_guardrail(symbol, "rate_limited", operation)
            return "rate_limited"
        if not self._breaker.allow():
            self._emit_guardrail(symbol, "circuit_open", operation)
            return "circuit_open"
        return None

    def _allow(self, symbol: Optional[str], operation: str) -> bool:
        return self._allow_reason(symbol, operation) is None

    def _record_result(self, status: str) -> None:
        normalized = (status or "").lower()
        # Canceled is expected in maker-first repost loops; treating it as a
        # breaker failure self-throttles execution and causes guard_blocked churn.
        if normalized in {"rejected", "failed", "expired"}:
            self._breaker.record_failure()
            if self._breaker._opened_at is not None:
                self._emit_guardrail(None, "circuit_open", "result")
        elif normalized:
            self._breaker.record_success()
            self._emit_guardrail(None, "circuit_reset", "result")

    def _emit_guardrail(self, symbol: Optional[str], guard_type: str, operation: str) -> None:
        if not (self._telemetry and self._telemetry_context):
            return
        payload = {
            "type": guard_type,
            "operation": operation,
            "symbol": symbol,
        }
        # Fire and forget; caller already in async context.
        asyncio.create_task(self._telemetry.publish_guardrail(self._telemetry_context, payload))
