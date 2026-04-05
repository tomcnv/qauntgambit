"""Consume order updates and reconcile execution state."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
import uuid

from quantgambit.execution.manager import ExecutionManager, ExecutionIntent, OrderStatus
from quantgambit.execution.order_statuses import normalize_order_status, is_terminal_status
from quantgambit.ingest.schemas import validate_order_update
from quantgambit.observability.logger import log_info, log_warning
from quantgambit.observability.telemetry import TelemetryPipeline, TelemetryContext
from quantgambit.storage.redis_streams import RedisStreamsClient, decode_and_validate_event


@dataclass
class OrderUpdateConsumerConfig:
    source_stream: str = "events:order_updates"
    consumer_group: str = "quantgambit_order_updates"
    consumer_name: str = "order_update_consumer"
    block_ms: int = 1000


class OrderUpdateConsumer:
    """Reads order updates and forwards them to the execution manager."""

    def __init__(
        self,
        redis_client: RedisStreamsClient,
        execution_manager: ExecutionManager,
        telemetry: Optional["TelemetryPipeline"] = None,
        telemetry_context: Optional["TelemetryContext"] = None,
        config: Optional[OrderUpdateConsumerConfig] = None,
    ):
        self.redis = redis_client
        self.execution_manager = execution_manager
        self.telemetry = telemetry
        self.telemetry_context = telemetry_context
        self.config = config or OrderUpdateConsumerConfig()

    async def run(self) -> None:
        log_info("order_update_consumer_start", stream=self.config.source_stream)
        await self.redis.create_group(self.config.source_stream, self.config.consumer_group)
        while True:
            messages = await self.redis.read_group(
                self.config.consumer_group,
                self.config.consumer_name,
                {self.config.source_stream: ">"},
                block_ms=self.config.block_ms,
            )
            for stream_name, entries in messages:
                for message_id, payload in entries:
                    await self._handle_message(payload)
                    await self.redis.ack(stream_name, self.config.consumer_group, message_id)

    async def _handle_message(self, payload: dict) -> None:
        try:
            event = decode_and_validate_event(payload)
        except Exception as exc:
            log_warning("order_update_invalid_event", error=str(exc))
            return
        if event.get("event_type") != "order_update":
            return
        update = event.get("payload") or {}
        try:
            validate_order_update(update)
        except Exception as exc:
            log_warning("order_update_invalid_payload", error=str(exc))
            return
        try:
            update_ts = float(update.get("timestamp")) if update.get("timestamp") is not None else None
        except (TypeError, ValueError):
            update_ts = None
        if update_ts is not None:
            update["timestamp"] = update_ts
        update["status"] = normalize_order_status(update.get("status"))
        record = None
        intent_meta = None
        order_store = getattr(self.execution_manager, "order_store", None)
        if order_store:
            record = order_store.get(update.get("order_id"), update.get("client_order_id"))
            if update.get("client_order_id") and hasattr(order_store, "resolve_intent_meta"):
                intent_meta = await order_store.resolve_intent_meta(update.get("client_order_id"))
        if self._is_duplicate(update):
            await self._heal_duplicate_terminal_intent(update, record, intent_meta)
            return
        resolved_symbol = record.symbol if record else (intent_meta.symbol if intent_meta else update.get("symbol"))
        resolved_side = record.side if record else (intent_meta.side if intent_meta else update.get("side"))
        resolved_size = record.size if record else (intent_meta.size if intent_meta else update.get("size"))
        await self._emit_telemetry({**update, "symbol": resolved_symbol, "side": resolved_side, "size": resolved_size})
        intent = ExecutionIntent(
            symbol=resolved_symbol,
            side=resolved_side,
            size=resolved_size,
            client_order_id=update.get("client_order_id"),
            entry_price=intent_meta.entry_price if intent_meta else None,
            stop_loss=intent_meta.stop_loss if intent_meta else None,
            take_profit=intent_meta.take_profit if intent_meta else None,
            strategy_id=intent_meta.strategy_id if intent_meta else None,
            profile_id=intent_meta.profile_id if intent_meta else None,
        )
        status = OrderStatus(
            order_id=update.get("order_id"),
            status=update.get("status"),
            fill_price=update.get("fill_price"),
            fee_usd=update.get("fee_usd"),
            filled_size=update.get("filled_size"),
            remaining_size=update.get("remaining_size"),
            reference_price=update.get("reference_price"),
            timestamp=update.get("timestamp"),
            source="ws",
            reason=update.get("close_reason"),
        )
        await self.execution_manager.record_order_status(intent, status)

    async def _heal_duplicate_terminal_intent(self, update: dict, record, intent_meta) -> None:
        client_order_id = update.get("client_order_id")
        if not client_order_id:
            return
        status = normalize_order_status(update.get("status"))
        if not is_terminal_status(status):
            return
        order_store = getattr(self.execution_manager, "order_store", None)
        if not (order_store and hasattr(order_store, "record_intent")):
            return
        symbol = record.symbol if record else (intent_meta.symbol if intent_meta else update.get("symbol"))
        side = record.side if record else (intent_meta.side if intent_meta else update.get("side"))
        size = record.size if record else (intent_meta.size if intent_meta else update.get("size"))
        if not symbol or not side or size is None:
            return
        await order_store.record_intent(
            intent_id=str(uuid.uuid4()),
            symbol=symbol,
            side=side,
            size=float(size or 0.0),
            client_order_id=client_order_id,
            status=status,
            order_id=update.get("order_id"),
            last_error=update.get("close_reason"),
        )

    def _is_duplicate(self, update: dict) -> bool:
        order_store = getattr(self.execution_manager, "order_store", None)
        if not order_store:
            return False
        record = order_store.get(update.get("order_id"), update.get("client_order_id"))
        if not record:
            return False
        if record.status != update.get("status"):
            return False
        if not record.history:
            return True
        update_ts = update.get("timestamp")
        try:
            update_ts_val = float(update_ts) if update_ts is not None else None
        except (TypeError, ValueError):
            update_ts_val = None
        if update_ts_val is None:
            return True
        return update_ts_val <= record.history[-1].timestamp

    async def _emit_telemetry(self, update: dict) -> None:
        if not (self.telemetry and self.telemetry_context):
            return
        payload = {
            "symbol": update.get("symbol"),
            "side": update.get("side"),
            "size": update.get("size"),
            "status": update.get("status"),
            "order_id": update.get("order_id"),
            "client_order_id": update.get("client_order_id"),
            "fill_price": update.get("fill_price"),
            "fee_usd": update.get("fee_usd"),
            "filled_size": update.get("filled_size"),
            "remaining_size": update.get("remaining_size"),
            "timestamp": update.get("timestamp"),
            "source": "ws",
            "close_reason": update.get("close_reason"),
        }
        await self.telemetry.publish_order_update(self.telemetry_context, payload)
