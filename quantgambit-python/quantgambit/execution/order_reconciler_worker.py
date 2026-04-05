"""Worker to reconcile order statuses via REST polling."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Optional

from quantgambit.execution.manager import ExecutionIntent, ExecutionManager, OrderStatus
from quantgambit.execution.order_statuses import normalize_order_status, is_open_status
from quantgambit.execution.order_store import InMemoryOrderStore, OrderRecord
from quantgambit.observability.logger import log_info, log_warning
from quantgambit.observability.telemetry import TelemetryContext, TelemetryPipeline


@dataclass
class OrderReconcilerConfig:
    interval_sec: float = 2.0
    max_orders_per_cycle: int = 50
    recent_order_age_sec: float = 300.0
    recent_order_poll_sec: float = 2.0
    aging_order_age_sec: float = 1800.0
    aging_order_poll_sec: float = 30.0
    stale_order_poll_sec: float = 120.0


class OrderReconcilerWorker:
    """Poll open orders and reconcile drift between WS and REST."""

    def __init__(
        self,
        execution_manager: ExecutionManager,
        order_store: InMemoryOrderStore,
        telemetry: Optional[TelemetryPipeline] = None,
        telemetry_context: Optional[TelemetryContext] = None,
        config: Optional[OrderReconcilerConfig] = None,
    ):
        self.execution_manager = execution_manager
        self.order_store = order_store
        self.telemetry = telemetry
        self.telemetry_context = telemetry_context
        self.config = config or OrderReconcilerConfig()
        self._last_rest_poll_emit: dict[str, float] = {}
        self._last_poll_failed_emit: dict[str, float] = {}
        self._last_checked_at: dict[str, float] = {}

    async def run(self) -> None:
        log_info("order_reconciler_start")
        while True:
            await self._reconcile_once()
            await asyncio.sleep(self.config.interval_sec)

    async def reconcile_once(self) -> None:
        await self._reconcile_once()

    async def _reconcile_once(self) -> None:
        if not self.order_store:
            return
        orders = [order for order in self.order_store.list_orders() if self._should_check(order)]
        if not orders:
            return
        max_per_cycle = _exchange_limit(getattr(self.telemetry_context, "exchange", None), self.config)
        for record in orders[: max_per_cycle]:
            await self._reconcile_order(record)

    def _should_check(self, record: OrderRecord) -> bool:
        if not (record.order_id or record.client_order_id):
            return False
        if not is_open_status(record.status):
            return False
        if _is_protective_client_order(record.client_order_id):
            return False
        dedupe_key = str(record.order_id or record.client_order_id or "")
        if not dedupe_key:
            return False
        now_ts = time.time()
        last_update_ts = record.history[-1].timestamp if record.history else now_ts
        age_sec = max(0.0, now_ts - last_update_ts)
        min_poll_sec = self._poll_interval_for_age(age_sec)
        last_checked_ts = self._last_checked_at.get(dedupe_key, 0.0)
        return (now_ts - last_checked_ts) >= min_poll_sec

    def _poll_interval_for_age(self, age_sec: float) -> float:
        if age_sec <= self.config.recent_order_age_sec:
            return self.config.recent_order_poll_sec
        if age_sec <= self.config.aging_order_age_sec:
            return self.config.aging_order_poll_sec
        return self.config.stale_order_poll_sec

    async def _reconcile_order(self, record: OrderRecord) -> None:
        dedupe_key = str(record.order_id or record.client_order_id or "")
        if dedupe_key:
            self._last_checked_at[dedupe_key] = time.time()
        await self._emit_rest_poll(record)
        if record.order_id:
            status = await self.execution_manager.poll_order_status(record.order_id, record.symbol)
        else:
            status = await self.execution_manager.poll_order_status_by_client_id(record.client_order_id, record.symbol)
        if not status:
            await self._emit_poll_failed(record)
            return
        normalized_status = normalize_order_status(status.status)
        if normalize_order_status(record.status) == normalized_status:
            return
        await self._emit_drift(record, status)
        intent_meta = None
        if record.client_order_id and hasattr(self.order_store, "resolve_intent_meta"):
            intent_meta = await self.order_store.resolve_intent_meta(record.client_order_id)
        intent = ExecutionIntent(
            symbol=record.symbol,
            side=record.side,
            size=record.size,
            client_order_id=record.client_order_id,
            entry_price=intent_meta.entry_price if intent_meta else None,
            stop_loss=intent_meta.stop_loss if intent_meta else None,
            take_profit=intent_meta.take_profit if intent_meta else None,
            strategy_id=intent_meta.strategy_id if intent_meta else None,
            profile_id=intent_meta.profile_id if intent_meta else None,
        )
        reconciled = OrderStatus(
            order_id=status.order_id or record.order_id,
            status=normalized_status,
            fill_price=status.fill_price,
            fee_usd=status.fee_usd,
            filled_size=status.filled_size,
            reference_price=status.reference_price,
            timestamp=time.time(),
            source="rest",
        )
        await self.execution_manager.record_order_status(intent, reconciled)

    async def _emit_drift(self, record: OrderRecord, status: OrderStatus) -> None:
        if not (self.telemetry and self.telemetry_context):
            return
        payload = {
            "type": "order_reconcile_override",
            "order_id": record.order_id,
            "client_order_id": record.client_order_id,
            "symbol": record.symbol,
            "previous_status": record.status,
            "current_status": status.status,
            "source": "rest",
            "reason": "ws_gap_rest_poll",
        }
        await self.telemetry.publish_guardrail(self.telemetry_context, payload)

    async def _emit_rest_poll(self, record: OrderRecord) -> None:
        if not (self.telemetry and self.telemetry_context):
            return
        dedupe_key = str(record.order_id or record.client_order_id or "")
        now_ts = time.time()
        last_ts = self._last_rest_poll_emit.get(dedupe_key, 0.0)
        if dedupe_key and (now_ts - last_ts) < 30.0:
            return
        if dedupe_key:
            self._last_rest_poll_emit[dedupe_key] = now_ts
        payload = {
            "type": "order_reconcile_rest_poll",
            "order_id": record.order_id,
            "client_order_id": record.client_order_id,
            "symbol": record.symbol,
            "current_status": record.status,
            "source": "rest",
            "reason": "ws_gap_rest_poll",
        }
        await self.telemetry.publish_guardrail(self.telemetry_context, payload)

    async def _emit_poll_failed(self, record: OrderRecord) -> None:
        if not (self.telemetry and self.telemetry_context):
            return
        dedupe_key = str(record.order_id or record.client_order_id or "")
        now_ts = time.time()
        last_ts = self._last_poll_failed_emit.get(dedupe_key, 0.0)
        if dedupe_key and (now_ts - last_ts) < 30.0:
            return
        if dedupe_key:
            self._last_poll_failed_emit[dedupe_key] = now_ts
        payload = {
            "type": "order_reconcile_poll_failed",
            "order_id": record.order_id,
            "client_order_id": record.client_order_id,
            "symbol": record.symbol,
            "current_status": record.status,
            "source": "rest",
            "reason": "ws_gap_poll_failed",
        }
        await self.telemetry.publish_guardrail(self.telemetry_context, payload)


def _exchange_limit(exchange: Optional[str], config: OrderReconcilerConfig) -> int:
    if not exchange:
        return config.max_orders_per_cycle
    caps = {
        "okx": 40,
        "bybit": 30,
        "binance": 25,
    }
    cap = caps.get(exchange.lower())
    if cap is None:
        return config.max_orders_per_cycle
    return min(config.max_orders_per_cycle, cap)


def _is_protective_client_order(client_order_id: Optional[str]) -> bool:
    if not client_order_id:
        return False
    lowered = client_order_id.lower()
    return (
        lowered.endswith(":sl")
        or lowered.endswith(":tp")
        or lowered.endswith(":tpl")
        or lowered.endswith(":tpsl")
    )
