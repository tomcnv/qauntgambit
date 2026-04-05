"""Worker that publishes private order updates to Redis streams."""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass
from typing import Optional

from quantgambit.execution.order_updates import OrderUpdateProvider, OrderUpdate
from quantgambit.ingest.schemas import validate_order_update
from quantgambit.observability.logger import log_info, log_warning
from quantgambit.storage.redis_streams import Event, RedisStreamsClient
from quantgambit.ingest.time_utils import now_recv_us, us_to_sec, normalize_exchange_ts_to_sec
from quantgambit.ingest.monotonic_clock import MonotonicClock


@dataclass
class OrderUpdateWorkerConfig:
    stream: str = "events:order_updates"
    idle_backoff_sec: float = 0.05


class OrderUpdateWorker:
    """Reads private order updates and publishes them to Redis."""

    def __init__(
        self,
        provider: OrderUpdateProvider,
        redis_client: RedisStreamsClient,
        bot_id: str,
        exchange: str,
        config: Optional[OrderUpdateWorkerConfig] = None,
        telemetry=None,
        telemetry_context=None,
        monotonic_clock: Optional[MonotonicClock] = None,
    ):
        self.provider = provider
        self.redis = redis_client
        self.bot_id = bot_id
        self.exchange = exchange
        self.config = config or OrderUpdateWorkerConfig()
        self.telemetry = telemetry
        self.telemetry_context = telemetry_context
        self._monotonic_clock = monotonic_clock

    async def run(self) -> None:
        log_info("order_update_worker_start", stream=self.config.stream, exchange=self.exchange)
        while True:
            try:
                update = await self.provider.next_update()
            except asyncio.CancelledError:
                log_warning("order_update_provider_cancelled")
                raise
            except Exception as exc:
                log_warning("order_update_provider_error", error=str(exc))
                await asyncio.sleep(self.config.idle_backoff_sec)
                continue
            if update is None:
                await asyncio.sleep(self.config.idle_backoff_sec)
                continue
            payload = update.to_payload() if isinstance(update, OrderUpdate) else dict(update)
            exchange = payload.get("exchange") or getattr(self.provider, "exchange", self.exchange) or self.exchange
            log_info(
                "order_update_received",
                symbol=payload.get("symbol"),
                status=payload.get("status"),
                order_id=payload.get("order_id"),
                client_order_id=payload.get("client_order_id"),
                exchange=exchange,
            )
            recv_us = now_recv_us()
            if not payload.get("timestamp"):
                payload["timestamp"] = time.time()
            exchange_ts = normalize_exchange_ts_to_sec(payload.get("timestamp"))
            symbol = payload.get("symbol") or ""
            ts_canon_us = self._monotonic_clock.update(symbol, recv_us) if self._monotonic_clock else recv_us
            close_reason = payload.get("close_reason") or _infer_close_reason(payload.get("client_order_id"))
            if close_reason:
                payload["close_reason"] = close_reason
                payload.setdefault("position_effect", "close")
            try:
                validate_order_update(payload)
            except Exception as exc:
                log_warning("order_update_invalid_schema", error=str(exc))
                continue
            event = Event(
                event_id=str(uuid.uuid4()),
                event_type="order_update",
                schema_version="v1",
                timestamp=str(payload["timestamp"]),
                ts_recv_us=recv_us,
                ts_canon_us=ts_canon_us,
                ts_exchange_s=exchange_ts,
                bot_id=self.bot_id,
                symbol=payload.get("symbol"),
                exchange=exchange,
                payload=payload,
            )
            await self.redis.publish_event(self.config.stream, event)
            await self._maybe_publish_sltp(payload)
            await self._maybe_publish_log(payload)

    async def _maybe_publish_log(self, payload: dict) -> None:
        if not (self.telemetry and self.telemetry_context):
            return
        try:
            await self.telemetry.publish_log(
                self.telemetry_context,
                {
                    "level": payload.get("status", "").upper() or "INFO",
                    "msg": "order_update",
                    "symbol": payload.get("symbol"),
                    "status": payload.get("status"),
                    "close_reason": payload.get("close_reason"),
                    "order_id": payload.get("order_id"),
                    "client_order_id": payload.get("client_order_id"),
                },
            )
        except Exception:
            # logging path should not break the worker
            pass

    async def _maybe_publish_sltp(self, payload: dict) -> None:
        if not (self.telemetry and self.telemetry_context):
            return
        reason = (payload.get("close_reason") or "").lower()
        if reason not in {"stop_loss_hit", "take_profit_hit", "trailing_stop_hit"}:
            return
        try:
            await self.telemetry.publish_sltp_event(
                self.telemetry_context,
                {
                    "symbol": payload.get("symbol"),
                    "side": payload.get("side"),
                    "event_type": reason,
                    "pnl": payload.get("pnl"),
                    "order_id": payload.get("order_id"),
                    "client_order_id": payload.get("client_order_id"),
                    "exchange": payload.get("exchange") or self.exchange,
                },
            )
        except Exception:
            pass


def _infer_close_reason(client_order_id: Optional[str]) -> Optional[str]:
    if not client_order_id:
        return None
    suffix = str(client_order_id).rsplit(":", 1)[-1].lower()
    mapping = {
        "sl": "stop_loss_hit",
        "tp": "take_profit_hit",
        "ts": "trailing_stop_hit",
        "oco": "protective_oco",
        "tpsl": "protective_tpsl",
    }
    return mapping.get(suffix)
