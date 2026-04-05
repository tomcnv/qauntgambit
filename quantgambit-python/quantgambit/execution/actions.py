"""Execution actions invoked by the control plane."""

from __future__ import annotations

from typing import Optional, Tuple, Dict, Iterable

import json
import os
import time

from quantgambit.control.runtime_state import ControlRuntimeState
from quantgambit.execution.manager import ExecutionManager, NoopExecutionManager
from quantgambit.execution.symbols import normalize_exchange_symbol, to_storage_symbol


class ExecutionActionHandler:
    """Default execution action handler.

    This is intentionally lightweight and should be wired to real execution
    services in production (flatten positions, risk overrides, etc.).
    """

    def __init__(
        self,
        runtime_state: ControlRuntimeState,
        execution_manager: Optional[ExecutionManager] = None,
        redis_client=None,
        exchange: Optional[str] = None,
        orderbook_symbols: Optional[Iterable[str]] = None,
        orderbook_required: bool = True,
        orderbook_staleness_ms: int = 5000,
        kill_switch=None,
    ):
        self.runtime_state = runtime_state
        self.execution_manager = execution_manager or NoopExecutionManager()
        self.redis_client = redis_client
        self.exchange = exchange
        self.orderbook_symbols = [s.strip() for s in (orderbook_symbols or []) if s]
        self.orderbook_required = orderbook_required
        self.orderbook_staleness_ms = orderbook_staleness_ms
        self._kill_switch = kill_switch
        self.runtime_state.execution_readiness_probe = self.refresh_execution_readiness
        self.runtime_state.trading_disabled = os.getenv("TRADING_DISABLED", "false").lower() in {"1", "true", "yes"}
        self._set_execution_state(*self._static_execution_prereq())

    def _set_execution_state(self, ready: bool, reason: Optional[str]) -> None:
        self.runtime_state.execution_ready = bool(ready)
        self.runtime_state.execution_block_reason = None if ready else (reason or "execution_not_ready")
        self.runtime_state.execution_last_checked_at = time.time()

    def _static_execution_prereq(self) -> Tuple[bool, str]:
        trading_mode = (os.getenv("TRADING_MODE") or "").strip().lower()
        execution_provider = (os.getenv("EXECUTION_PROVIDER") or "").strip().lower()
        needs_exchange_credentials = (
            trading_mode in {"live", "demo"}
            or execution_provider in {"live", "ccxt"}
        )
        has_exchange_credentials = bool(
            (os.getenv("EXCHANGE_ACCOUNT_ID") or "").strip()
            or (os.getenv("EXCHANGE_SECRET_ID") or "").strip()
        )
        self.runtime_state.exchange_credentials_configured = has_exchange_credentials
        if self.runtime_state.trading_disabled:
            return False, "trading_disabled"
        if self.runtime_state.config_drift_active:
            return False, "config_drift"
        if self.runtime_state.trading_paused:
            return False, str(self.runtime_state.pause_reason or "trading_paused")
        if self._kill_switch and getattr(self._kill_switch, "is_active", lambda: False)():
            self.runtime_state.kill_switch_active = True
            return False, "kill_switch_active"
        self.runtime_state.kill_switch_active = False
        if needs_exchange_credentials and not has_exchange_credentials:
            return False, "exchange_credentials_missing"
        if not self.orderbook_required:
            return True, "orderbook_not_required"
        if self.redis_client is None:
            return False, "orderbook_health_unavailable"
        exchange = (self.exchange or os.getenv("ACTIVE_EXCHANGE") or "").lower()
        if not exchange:
            return False, "exchange_missing"
        symbols = self.orderbook_symbols
        if not symbols:
            env_symbols = os.getenv("ORDERBOOK_SYMBOLS") or os.getenv("ORDERBOOK_SYMBOL") or ""
            symbols = [s.strip() for s in env_symbols.split(",") if s.strip()]
        if not symbols:
            return False, "orderbook_symbols_missing"
        return True, "orderbook_pending_check"

    async def pause(self, reason: Optional[str]) -> Tuple[str, str]:
        self.runtime_state.trading_paused = True
        self.runtime_state.pause_reason = reason or "manual_pause"
        await self.refresh_execution_readiness()
        return "executed", "paused"

    async def resume(self) -> Tuple[str, str]:
        await self.refresh_execution_readiness()
        if not self.runtime_state.execution_ready:
            return "rejected", str(self.runtime_state.execution_block_reason or "execution_not_ready")
        self.runtime_state.trading_paused = False
        self.runtime_state.pause_reason = None
        return "executed", "resumed"

    async def halt(self) -> Tuple[str, str]:
        self.runtime_state.trading_paused = True
        self.runtime_state.pause_reason = "halted"
        self.runtime_state.failover_state.apply("HALT")
        await self.refresh_execution_readiness()
        return "executed", "halted"

    async def failover_arm(self, primary_exchange: Optional[str], secondary_exchange: Optional[str]) -> Tuple[str, str]:
        ctx = self.runtime_state.failover_state.context
        ctx.primary_exchange = primary_exchange
        ctx.secondary_exchange = secondary_exchange
        self.runtime_state.failover_state.apply("FAILOVER_ARM")
        if hasattr(self.execution_manager, "set_failover_targets"):
            self.execution_manager.set_failover_targets(primary_exchange, secondary_exchange)
        return "executed", "failover_armed"

    async def failover_exec(self) -> Tuple[str, str]:
        self.runtime_state.failover_state.apply("FAILOVER_EXEC")
        result = await self.execution_manager.execute_failover()
        return result.status, result.message

    async def recover_arm(self, primary_exchange: Optional[str], secondary_exchange: Optional[str]) -> Tuple[str, str]:
        ctx = self.runtime_state.failover_state.context
        ctx.primary_exchange = primary_exchange
        ctx.secondary_exchange = secondary_exchange
        self.runtime_state.failover_state.apply("RECOVER_ARM")
        if hasattr(self.execution_manager, "set_failover_targets"):
            self.execution_manager.set_failover_targets(primary_exchange, secondary_exchange)
        return "executed", "recovery_armed"

    async def recover_exec(self) -> Tuple[str, str]:
        self.runtime_state.failover_state.apply("RECOVER_EXEC")
        result = await self.execution_manager.execute_recovery()
        return result.status, result.message

    async def flatten(self, symbol: Optional[str] = None) -> Tuple[str, str]:
        result = await self.execution_manager.flatten_positions(symbol=symbol)
        return result.status, result.message

    async def risk_override(
        self,
        overrides: Dict[str, float],
        ttl_seconds: int,
        scope: Optional[Dict[str, str]] = None,
    ) -> Tuple[str, str]:
        result = await self.execution_manager.apply_risk_override(overrides, ttl_seconds, scope=scope)
        return result.status, result.message

    async def reload_config(self) -> Tuple[str, str]:
        result = await self.execution_manager.reload_config()
        return result.status, result.message

    async def cancel_order(
        self,
        order_id: Optional[str],
        client_order_id: Optional[str],
        symbol: Optional[str],
    ) -> Tuple[str, str]:
        handler = getattr(self.execution_manager, "cancel_order", None)
        if handler is None:
            return "rejected", "cancel_not_supported"
        result = await handler(order_id=order_id, client_order_id=client_order_id, symbol=symbol)
        return result.status, result.message

    async def replace_order(
        self,
        order_id: Optional[str],
        client_order_id: Optional[str],
        symbol: Optional[str],
        price: Optional[float],
        size: Optional[float],
    ) -> Tuple[str, str]:
        handler = getattr(self.execution_manager, "replace_order", None)
        if handler is None:
            return "rejected", "replace_not_supported"
        result = await handler(
            order_id=order_id,
            client_order_id=client_order_id,
            symbol=symbol,
            price=price,
            size=size,
        )
        return result.status, result.message

    async def _check_orderbook_health(self) -> Tuple[bool, str]:
        # If no redis client, cannot validate; reject to fail safe.
        if self.redis_client is None:
            return False, "orderbook_health_unavailable"
        exchange = (self.exchange or os.getenv("ACTIVE_EXCHANGE") or "").lower()
        if not exchange:
            return False, "exchange_missing"
        symbols = self.orderbook_symbols
        if not symbols:
            env_symbols = os.getenv("ORDERBOOK_SYMBOLS") or os.getenv("ORDERBOOK_SYMBOL") or ""
            symbols = [s.strip() for s in env_symbols.split(",") if s.strip()]
        if not symbols:
            return False, "orderbook_symbols_missing"

        now_ms = int(time.time() * 1000)
        for sym in symbols:
            lookup_symbol = sym
            try:
                normalized = normalize_exchange_symbol(exchange, sym)
                lookup_symbol = to_storage_symbol(normalized) or normalized or sym
            except Exception:
                lookup_symbol = sym
            redis_handle = getattr(self.redis_client, "redis", self.redis_client)
            staleness = None
            for key_symbol in dict.fromkeys([lookup_symbol, sym]):
                key = f"orderbook_health:{exchange}:{key_symbol}"
                data = await redis_handle.hgetall(key)
                if not data:
                    continue
                raw = data.get("staleness_ms") or data.get(b"staleness_ms")
                try:
                    staleness = int(raw)
                except (TypeError, ValueError):
                    staleness = None
                last_ts_raw = data.get("last_ts") or data.get(b"last_ts")
                if staleness is None and last_ts_raw:
                    try:
                        last_ts = int(last_ts_raw)
                        staleness = now_ms - last_ts
                    except (TypeError, ValueError):
                        staleness = None
                if staleness is not None:
                    break
            # Newer runtimes publish per-symbol quality snapshots instead of legacy
            # orderbook_health hashes. Fall back to those snapshots before declaring
            # the orderbook stale.
            if staleness is None:
                tenant_id = (os.getenv("TENANT_ID") or "").strip()
                bot_id = (os.getenv("BOT_ID") or "").strip()
                if not tenant_id or not bot_id:
                    tenant_id = ""
                    bot_id = ""
                for key_symbol in dict.fromkeys([lookup_symbol, sym]):
                    if not tenant_id or not bot_id:
                        continue
                    quality_key = f"quantgambit:{tenant_id}:{bot_id}:quality:{key_symbol}:latest"
                    raw_quality = await redis_handle.get(quality_key)
                    if not raw_quality:
                        continue
                    try:
                        quality = json.loads(raw_quality)
                    except Exception:
                        continue
                    orderbook_age_sec = quality.get("orderbook_age_sec")
                    try:
                        orderbook_age_ms = int(float(orderbook_age_sec) * 1000.0)
                    except (TypeError, ValueError):
                        orderbook_age_ms = None
                    if orderbook_age_ms is None:
                        continue
                    staleness = orderbook_age_ms
                    break
            if staleness is None:
                return False, f"orderbook_stale:{sym}"
            if staleness > self.orderbook_staleness_ms:
                return False, f"orderbook_stale:{sym}"
        return True, "orderbook_ok"

    async def refresh_execution_readiness(self) -> None:
        static_ok, static_reason = self._static_execution_prereq()
        if not static_ok:
            self._set_execution_state(False, static_reason)
            return
        if not self.orderbook_required:
            self._set_execution_state(True, "orderbook_not_required")
            return
        ok, msg = await self._check_orderbook_health()
        self._set_execution_state(ok, None if ok else msg)
