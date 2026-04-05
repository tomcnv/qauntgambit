"""
Quant-grade component integration for Runtime.

This module integrates the new quant-grade components into the existing Runtime:
- PersistentKillSwitch with Redis persistence
- ReconciliationWorker for state healing
- LatencyTracker for performance metrics

These run alongside existing workers and publish their stats to Redis
for the API to read.
"""

import asyncio
import hashlib
import hmac
import json
import logging
import os
import time
import urllib.parse
import urllib.request
import uuid
from typing import Any, Dict, Optional

from quantgambit.core.clock import WallClock
from quantgambit.core.latency import LatencyTracker
from quantgambit.core.risk.kill_switch import KillSwitchTrigger
from quantgambit.core.risk.kill_switch_store import (
    PersistentKillSwitch,
    RedisKillSwitchStore,
)
from quantgambit.execution.reconciliation import (
    ReconciliationWorker,
    OrderStore,
    PositionStore,
    ExchangeClient,
)
from quantgambit.storage.secrets import SecretsProvider
from quantgambit.execution.symbols import to_ccxt_market_symbol

logger = logging.getLogger(__name__)


class QuantIntegration:
    """
    Integrates quant-grade components with the Runtime.
    
    Usage:
        quant = QuantIntegration(
            redis_client=redis,
            tenant_id=tenant_id,
            bot_id=bot_id,
            order_store=order_store,
            position_store=position_store,
            exchange_client=exchange_client,
        )
        await quant.start()
        
        # Check kill switch before trading
        if quant.kill_switch.is_active():
            return
        
        # Later...
        await quant.stop()
    """
    
    def __init__(
        self,
        redis_client,
        tenant_id: str,
        bot_id: str,
        order_store: Optional[OrderStore] = None,
        position_store: Optional[PositionStore] = None,
        exchange_client: Optional[ExchangeClient] = None,
        clock: Optional[WallClock] = None,
        side_channel_publisher=None,
    ):
        """
        Initialize quant integration.
        
        Args:
            redis_client: Async Redis client
            tenant_id: Tenant identifier
            bot_id: Bot identifier
            order_store: Order store for reconciliation
            position_store: Position store for reconciliation
            exchange_client: Exchange client for reconciliation
            clock: Clock instance (uses WallClock if not provided)
            side_channel_publisher: Optional publisher for events
        """
        self._redis = redis_client
        self._tenant_id = tenant_id
        self._bot_id = bot_id
        self._clock = clock or WallClock()
        self._publisher = side_channel_publisher
        
        # Latency tracker
        self._latency_tracker = LatencyTracker(
            clock=self._clock,
            max_samples=int(os.getenv("LATENCY_MAX_SAMPLES", "100000")),
            window_sec=float(os.getenv("LATENCY_WINDOW_SEC", "60.0")),
        )
        
        # Kill switch
        kill_switch_store = RedisKillSwitchStore(redis_client, tenant_id, bot_id)
        self._kill_switch = PersistentKillSwitch(
            clock=self._clock,
            store=kill_switch_store,
            side_channel_publisher=side_channel_publisher,
        )
        
        # Reconciliation worker (optional - requires stores)
        self._reconciliation_worker: Optional[ReconciliationWorker] = None
        if order_store and position_store and exchange_client:
            self._reconciliation_worker = ReconciliationWorker(
                clock=self._clock,
                order_store=order_store,
                position_store=position_store,
                exchange_client=exchange_client,
                side_channel=side_channel_publisher,
                interval_sec=float(os.getenv("RECONCILIATION_INTERVAL_SEC", "30.0")),
                enable_auto_healing=os.getenv("RECONCILIATION_AUTO_HEAL", "true").lower() in ("true", "1", "yes"),
            )
        
        # Background tasks
        self._stats_task: Optional[asyncio.Task] = None
        self._running = False
    
    @property
    def kill_switch(self) -> PersistentKillSwitch:
        """Get the kill switch instance."""
        return self._kill_switch
    
    @property
    def latency_tracker(self) -> LatencyTracker:
        """Get the latency tracker instance."""
        return self._latency_tracker
    
    @property
    def reconciliation_worker(self) -> Optional[ReconciliationWorker]:
        """Get the reconciliation worker instance."""
        return self._reconciliation_worker
    
    async def start(self) -> None:
        """Start all quant components."""
        logger.info(f"Starting quant integration for {self._tenant_id}:{self._bot_id}")
        
        # Initialize kill switch (loads state from Redis)
        await self._kill_switch.initialize()
        
        # Start reconciliation worker
        if self._reconciliation_worker:
            await self._reconciliation_worker.start()
        
        # Start stats publishing loop
        self._running = True
        self._stats_task = asyncio.create_task(self._stats_publish_loop())
        
        logger.info("Quant integration started")
    
    async def stop(self) -> None:
        """Stop all quant components."""
        logger.info("Stopping quant integration")
        
        self._running = False
        
        if self._stats_task:
            self._stats_task.cancel()
            try:
                await self._stats_task
            except asyncio.CancelledError:
                pass
        
        if self._reconciliation_worker:
            await self._reconciliation_worker.stop()
        
        # Final stats publish
        await self._publish_stats()
        
        logger.info("Quant integration stopped")
    
    async def _stats_publish_loop(self) -> None:
        """Periodically publish stats to Redis."""
        interval = float(os.getenv("QUANT_STATS_INTERVAL_SEC", "5.0"))
        
        while self._running:
            try:
                await asyncio.sleep(interval)
                await self._publish_stats()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"Error publishing quant stats: {e}")
    
    async def _publish_stats(self) -> None:
        """Publish all stats to Redis."""
        prefix = f"quantgambit:{self._tenant_id}:{self._bot_id}"
        
        # Publish latency metrics
        latency_key = f"{prefix}:latency:metrics"
        latency_metrics = self._latency_tracker.get_all_percentiles()
        await self._redis.set(latency_key, json.dumps(latency_metrics))
        
        # Publish reconciliation stats
        if self._reconciliation_worker:
            recon_key = f"{prefix}:reconciliation:status"
            recon_stats = self._reconciliation_worker.get_stats()
            await self._redis.set(recon_key, json.dumps(recon_stats))
    
    # Convenience methods for kill switch
    
    async def trigger_kill_switch(
        self,
        trigger: KillSwitchTrigger,
        message: str = "Kill switch triggered",
    ) -> None:
        """Trigger the kill switch."""
        await self._kill_switch.trigger(trigger, message)
    
    async def reset_kill_switch(self, operator_id: str = "system") -> None:
        """Reset the kill switch."""
        await self._kill_switch.reset(operator_id)
    
    def is_kill_switch_active(self) -> bool:
        """Check if kill switch is active."""
        return self._kill_switch.is_active()
    
    # Latency tracking helpers
    
    def start_latency_timer(self, metric_name: str) -> float:
        """Start a latency timer."""
        return self._latency_tracker.start_timer(metric_name)
    
    def end_latency_timer(self, metric_name: str, start_time: float) -> None:
        """End a latency timer."""
        self._latency_tracker.end_timer(metric_name, start_time)


# =============================================================================
# Adapter classes to bridge existing stores to new interfaces
# =============================================================================

class OrderStoreAdapter:
    """
    Adapts the existing InMemoryOrderStore to the OrderStore protocol
    required by ReconciliationWorker.
    """
    
    def __init__(self, order_store):
        """
        Initialize adapter.
        
        Args:
            order_store: Existing InMemoryOrderStore instance
        """
        self._store = order_store
    
    def get_open_orders(self, symbol=None):
        """Get open orders."""
        from quantgambit.execution.order_statuses import is_open_status
        from quantgambit.core.lifecycle import ManagedOrder
        from quantgambit.core.ids import IntentIdentity
        
        orders = self._store.list_orders()
        open_orders = []
        
        for order in orders:
            if not is_open_status(order.status):
                continue
            if symbol and order.symbol != symbol:
                continue
            
            # Convert to ManagedOrder if needed
            # This is a simplified conversion
            identity = IntentIdentity(
                intent_id=order.client_order_id or order.order_id or "unknown",
                client_order_id=order.client_order_id or order.order_id or "unknown",
                attempt=1,
            )
            
            managed = ManagedOrder(
                identity=identity,
                symbol=order.symbol,
                side=order.side or "buy",
                qty=float(order.size or 0),
                order_type=order.order_type or "market",
            )
            managed.filled_qty = float(order.filled_size or 0)
            open_orders.append(managed)
        
        return open_orders
    
    def get_order(self, client_order_id):
        """Get order by client order ID."""
        for order in self._store.list_orders():
            if order.client_order_id == client_order_id:
                return order
        return None
    
    def update_order(self, order):
        """Update order."""
        client_order_id = getattr(getattr(order, "identity", None), "client_order_id", None)
        existing = self.get_order(client_order_id) if client_order_id else None
        status = getattr(getattr(order, "state", None), "value", None) or "unknown"
        symbol = getattr(order, "symbol", None) or getattr(existing, "symbol", None)
        side = getattr(order, "side", None) or getattr(existing, "side", None) or "buy"
        size = float(getattr(order, "qty", 0.0) or getattr(existing, "size", 0.0) or 0.0)
        filled_size = getattr(order, "filled_qty", None)
        if filled_size is None and existing is not None:
            filled_size = getattr(existing, "filled_size", None)
        order_id = getattr(existing, "order_id", None)
        if not symbol or not client_order_id:
            return
        self._submit_record(
            symbol=symbol,
            side=side,
            size=size,
            status=status,
            order_id=order_id,
            client_order_id=client_order_id,
            reason="reconciliation_heal",
            filled_size=filled_size,
            source="reconciliation",
            event_type="reconciliation_heal",
        )
    
    def remove_order(self, client_order_id):
        """Remove order."""
        existing = self.get_order(client_order_id)
        if not existing:
            return
        self._submit_record(
            symbol=existing.symbol,
            side=existing.side or "buy",
            size=float(existing.size or 0.0),
            status="canceled",
            order_id=existing.order_id,
            client_order_id=client_order_id,
            reason="reconciliation_remove",
            filled_size=existing.filled_size,
            remaining_size=existing.remaining_size,
            source="reconciliation",
            event_type="reconciliation_remove",
        )
    
    def add_order(self, order):
        """Add order."""
        client_order_id = getattr(getattr(order, "identity", None), "client_order_id", None)
        symbol = getattr(order, "symbol", None)
        side = getattr(order, "side", None) or "buy"
        size = float(getattr(order, "qty", 0.0) or 0.0)
        if not symbol or not client_order_id:
            return
        self._submit_record(
            symbol=symbol,
            side=side,
            size=size,
            status="pending",
            order_id=None,
            client_order_id=client_order_id,
            reason="reconciliation_add",
            source="reconciliation",
            event_type="reconciliation_add",
        )

    def _submit_record(
        self,
        *,
        symbol: str,
        side: str,
        size: float,
        status: str,
        order_id: Optional[str],
        client_order_id: Optional[str],
        reason: Optional[str],
        filled_size: Optional[float] = None,
        remaining_size: Optional[float] = None,
        source: Optional[str] = None,
        event_type: Optional[str] = None,
    ) -> None:
        async def _persist() -> None:
            await self._store.record(
                symbol=symbol,
                side=side,
                size=size,
                status=status,
                order_id=order_id,
                client_order_id=client_order_id,
                reason=reason,
                filled_size=filled_size,
                remaining_size=remaining_size,
                source=source,
                event_type=event_type,
            )
            if (
                client_order_id
                and hasattr(self._store, "record_intent")
                and str(status).lower() in {"filled", "canceled", "rejected", "failed", "expired"}
            ):
                await self._store.record_intent(
                    intent_id=str(uuid.uuid4()),
                    symbol=symbol,
                    side=side,
                    size=float(size or 0.0),
                    client_order_id=client_order_id,
                    status=status,
                    order_id=order_id,
                    last_error=reason,
                )

        coro = _persist()
        try:
            loop = asyncio.get_running_loop()
            task = loop.create_task(coro)
            task.add_done_callback(self._log_record_error)
        except RuntimeError:
            asyncio.run(coro)

    @staticmethod
    def _log_record_error(task: asyncio.Task) -> None:
        try:
            task.result()
        except Exception as exc:  # pragma: no cover - best effort logging
            logger.error("Failed to persist reconciliation order update: %s", exc)


class PositionStoreAdapter:
    """
    Adapts the existing InMemoryStateManager to the PositionStore protocol
    required by ReconciliationWorker.
    """
    
    def __init__(self, state_manager):
        """
        Initialize adapter.
        
        Args:
            state_manager: Existing InMemoryStateManager instance
        """
        self._manager = state_manager
    
    def get_position(self, symbol):
        """Get position for symbol."""
        positions = self._manager.get_positions()
        for pos in positions:
            if pos.symbol == symbol:
                return {
                    "symbol": pos.symbol,
                    "size": pos.size,
                    "side": pos.side,
                    "entry_price": pos.entry_price,
                }
        return None
    
    def get_all_positions(self):
        """Get all positions."""
        positions = self._manager.get_positions()
        return {
            pos.symbol: {
                "symbol": pos.symbol,
                "size": pos.size,
                "side": pos.side,
                "entry_price": pos.entry_price,
            }
            for pos in positions
        }
    
    def update_position(self, symbol, size, entry_price):
        """Update position."""
        existing = None
        if hasattr(self._manager, "get_position"):
            existing = self._manager.get_position(symbol)
        if hasattr(self._manager, "update_position"):
            self._manager.update_position(
                symbol=symbol,
                side="long" if size >= 0 else "short",
                size=abs(size),
                entry_price=entry_price,
                reference_price=getattr(existing, "reference_price", None) if existing else None,
                entry_fee_usd=getattr(existing, "entry_fee_usd", None) if existing else None,
                stop_loss=getattr(existing, "stop_loss", None) if existing else None,
                take_profit=getattr(existing, "take_profit", None) if existing else None,
                opened_at=getattr(existing, "opened_at", None) if existing else None,
                prediction_confidence=getattr(existing, "prediction_confidence", None) if existing else None,
                strategy_id=getattr(existing, "strategy_id", None) if existing else None,
                profile_id=getattr(existing, "profile_id", None) if existing else None,
                entry_signal_strength=getattr(existing, "entry_signal_strength", None) if existing else None,
                entry_signal_confidence=getattr(existing, "entry_signal_confidence", None) if existing else None,
                entry_confirmation_count=getattr(existing, "entry_confirmation_count", None) if existing else None,
                expected_horizon_sec=getattr(existing, "expected_horizon_sec", None) if existing else None,
                time_to_work_sec=getattr(existing, "time_to_work_sec", None) if existing else None,
                max_hold_sec=getattr(existing, "max_hold_sec", None) if existing else None,
                mfe_min_bps=getattr(existing, "mfe_min_bps", None) if existing else None,
                accumulate=False,
            )
            return
        # Fallback: update internal storage if present
        if hasattr(self._manager, "_positions"):
            pos = self._manager._positions.get(symbol)
            if pos:
                pos.size = abs(size)
                pos.entry_price = entry_price

    def clear_position(self, symbol):
        """Clear position."""
        if hasattr(self._manager, "_positions"):
            self._manager._positions.pop(symbol, None)
            return
        # Best-effort async finalize if available
        if hasattr(self._manager, "finalize_close"):
            try:
                import asyncio
                loop = asyncio.get_running_loop()
                loop.create_task(self._manager.finalize_close(symbol))
            except RuntimeError:
                asyncio.run(self._manager.finalize_close(symbol))


class ExchangeClientAdapter:
    """
    Adapts the existing exchange client to the ExchangeClient protocol
    required by ReconciliationWorker.
    """
    
    def __init__(self, exchange_client):
        """
        Initialize adapter.
        
        Args:
            exchange_client: Existing exchange client instance
        """
        self._client = exchange_client
    
    async def get_open_orders(self, symbol=None):
        """Query open orders from exchange."""
        client = self._resolve_open_orders_client()
        symbols = [symbol] if symbol else self._configured_symbols()
        out: list[dict] = []
        if client is not None:
            for sym in symbols:
                rows = await self._fetch_open_orders_for_symbol(client, sym)
                for row in rows or []:
                    normalized = self._normalize_open_order(row, sym)
                    if normalized is not None:
                        out.append(normalized)
            # If no symbols are configured, do one broad fetch.
            if not symbols:
                try:
                    rows = await client.fetch_open_orders()
                except Exception:
                    rows = []
                for row in rows or []:
                    normalized = self._normalize_open_order(row, None)
                    if normalized is not None:
                        out.append(normalized)
        # Hard fallback: query Bybit V5 directly so reconciliation remains
        # exchange-authoritative even when CCXT/open-order polling is unavailable.
        if not out and self._is_bybit():
            out = self._fetch_bybit_v5_open_orders(symbols=symbols)
        return out

    @staticmethod
    async def _fetch_open_orders_for_symbol(client: Any, symbol: str) -> list:
        exchange_id = str(getattr(client, "id", "") or getattr(client, "exchange_id", "") or "").strip().lower()
        canonical = to_ccxt_market_symbol(exchange_id or "bybit", symbol, market_type="perp")
        attempts = [candidate for candidate in [symbol, canonical] if candidate]
        for candidate in attempts:
            try:
                rows = await client.fetch_open_orders(candidate)
                return rows or []
            except Exception:
                continue
        return []

    def _resolve_open_orders_client(self):
        if hasattr(self._client, "fetch_open_orders"):
            return self._client
        inner = getattr(self._client, "inner", None)
        if inner is not None and hasattr(inner, "fetch_open_orders"):
            return inner
        adapter = getattr(inner, "adapter", None)
        raw_client = getattr(adapter, "client", None)
        if raw_client is not None and hasattr(raw_client, "fetch_open_orders"):
            return raw_client
        return None

    @staticmethod
    def _is_bybit() -> bool:
        exchange = (os.getenv("ACTIVE_EXCHANGE") or os.getenv("EXCHANGE") or "").strip().lower()
        return exchange == "bybit"

    @staticmethod
    def _configured_symbols() -> list[str]:
        raw = os.getenv("SYMBOLS") or os.getenv("ORDERBOOK_SYMBOLS") or ""
        return [s.strip() for s in str(raw).split(",") if s.strip()]

    @staticmethod
    def _normalize_open_order(order: Any, fallback_symbol: Optional[str]) -> Optional[Dict[str, Any]]:
        if not isinstance(order, dict):
            return None
        info = order.get("info") if isinstance(order.get("info"), dict) else {}
        client_order_id = (
            order.get("clientOrderId")
            or order.get("client_order_id")
            or info.get("orderLinkId")
            or info.get("clientOrderId")
            or info.get("client_order_id")
        )
        if not client_order_id:
            return None
        return {
            "clientOrderId": client_order_id,
            "orderId": order.get("id") or order.get("orderId") or info.get("orderId"),
            "symbol": order.get("symbol") or info.get("symbol") or fallback_symbol,
            "status": order.get("status") or info.get("orderStatus") or info.get("status"),
            "qty": order.get("amount") or info.get("qty") or order.get("size"),
            "cumExecQty": order.get("filled") or info.get("cumExecQty"),
        }

    def _fetch_bybit_v5_open_orders(self, symbols: list[str]) -> list[dict]:
        secret_id = str(os.getenv("EXCHANGE_SECRET_ID") or "").strip()
        if not secret_id:
            return []
        creds = SecretsProvider().get_credentials(secret_id)
        if creds is None:
            return []
        target_symbols = symbols or self._configured_symbols()
        if not target_symbols:
            return []
        category = str(os.getenv("BYBIT_V5_CATEGORY") or "linear").strip() or "linear"
        base_url = "https://api.bybit.com"
        if str(os.getenv("BYBIT_DEMO", "false")).strip().lower() in {"1", "true", "yes"}:
            base_url = "https://api-demo.bybit.com"
        elif str(os.getenv("BYBIT_TESTNET", "false")).strip().lower() in {"1", "true", "yes"}:
            base_url = "https://api-testnet.bybit.com"
        out: list[dict] = []
        open_statuses = {"new", "partiallyfilled", "untriggered", "triggered", "active", "pendingcancel"}
        for symbol in target_symbols:
            try:
                payload = self._bybit_v5_get(
                    base_url=base_url,
                    api_key=creds.api_key,
                    api_secret=creds.secret_key,
                    path="/v5/order/realtime",
                    params={"category": category, "symbol": symbol, "openOnly": 0, "limit": 50},
                )
            except Exception:
                continue
            ret_code = payload.get("retCode")
            if ret_code not in (0, "0"):
                continue
            items = (payload.get("result") or {}).get("list") or []
            for item in items:
                status_raw = str(item.get("orderStatus") or item.get("status") or "")
                if status_raw.replace("_", "").lower() not in open_statuses:
                    continue
                client_order_id = item.get("orderLinkId") or item.get("clientOrderId")
                if not client_order_id:
                    continue
                out.append(
                    {
                        "clientOrderId": client_order_id,
                        "orderId": item.get("orderId") or item.get("orderID"),
                        "symbol": item.get("symbol") or symbol,
                        "status": status_raw,
                        "qty": item.get("qty"),
                        "cumExecQty": item.get("cumExecQty"),
                    }
                )
        return out

    @staticmethod
    def _bybit_v5_get(
        *,
        base_url: str,
        api_key: str,
        api_secret: str,
        path: str,
        params: Dict[str, Any],
        recv_window_ms: int = 5000,
    ) -> dict:
        query = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
        timestamp_ms = str(int(time.time() * 1000))
        recv_window = str(recv_window_ms)
        payload = f"{timestamp_ms}{api_key}{recv_window}{query}"
        signature = hmac.new(api_secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
        req = urllib.request.Request(
            f"{base_url}{path}?{query}",
            headers={
                "X-BAPI-API-KEY": api_key,
                "X-BAPI-SIGN": signature,
                "X-BAPI-TIMESTAMP": timestamp_ms,
                "X-BAPI-RECV-WINDOW": recv_window,
            },
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    
    async def get_positions(self):
        """Query positions from exchange."""
        if hasattr(self._client, "fetch_positions"):
            positions = await self._client.fetch_positions()
            return positions or []
        return []
    
    async def cancel_order(self, symbol, order_id):
        """Cancel an order."""
        if hasattr(self._client, "cancel_order"):
            try:
                await self._client.cancel_order(order_id, symbol)
                return True
            except Exception:
                return False
        return False
