"""Order lifecycle store for execution tracking."""

from __future__ import annotations

import time
import uuid
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Dict, Optional

from quantgambit.observability.logger import log_warning
from quantgambit.execution.order_statuses import normalize_order_status, is_terminal_status, is_valid_transition
from quantgambit.storage.redis_snapshots import RedisSnapshotWriter, RedisSnapshotReader
from quantgambit.storage.postgres import (
    PostgresOrderStore,
    OrderStatusRecord,
    OrderEventRecord,
    OrderIntentRecord,
    OrderErrorRecord,
    TradeCostRecord,
)


@dataclass
class OrderStatusUpdate:
    status: str
    timestamp: float
    reason: Optional[str] = None
    fill_price: Optional[float] = None
    fee_usd: Optional[float] = None
    filled_size: Optional[float] = None
    remaining_size: Optional[float] = None
    source: Optional[str] = None
    raw_exchange_status: Optional[str] = None


@dataclass
class OrderRecord:
    symbol: str
    side: str
    size: float
    status: str
    order_id: Optional[str] = None
    client_order_id: Optional[str] = None
    filled_size: Optional[float] = None
    remaining_size: Optional[float] = None
    order_type: Optional[str] = None  # market, limit, etc.
    history: list[OrderStatusUpdate] = field(default_factory=list)


@dataclass
class OrderIntentMeta:
    symbol: Optional[str] = None
    side: Optional[str] = None
    size: Optional[float] = None
    strategy_id: Optional[str] = None
    profile_id: Optional[str] = None
    entry_price: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None


class InMemoryOrderStore:
    """In-memory order store with optional Redis history snapshots."""

    def __init__(
        self,
        snapshot_writer: Optional[RedisSnapshotWriter] = None,
        snapshot_reader: Optional["RedisSnapshotReader"] = None,
        snapshot_history_key: Optional[str] = None,
        intent_snapshot_key: Optional[str] = None,
        intent_history_key: Optional[str] = None,
        tenant_id: Optional[str] = None,
        bot_id: Optional[str] = None,
        max_history: int = 200,
        max_intent_age_sec: Optional[float] = None,
        postgres_store: Optional[PostgresOrderStore] = None,
    ):
        self._orders: Dict[str, OrderRecord] = {}
        self._snapshot_writer = snapshot_writer
        self._snapshot_reader = snapshot_reader
        self._snapshot_history_key = snapshot_history_key
        self._intent_snapshot_key = intent_snapshot_key
        self._intent_history_key = intent_history_key
        self._tenant_id = tenant_id
        self._bot_id = bot_id
        self._max_history = max_history
        self._max_intent_age_sec = max_intent_age_sec
        self._postgres_store = postgres_store
        self._last_intent_drop_stats: Optional[dict] = None
        self._intent_meta: Dict[str, OrderIntentMeta] = {}
        if self._tenant_id and self._bot_id:
            if not self._intent_snapshot_key:
                self._intent_snapshot_key = f"quantgambit:{self._tenant_id}:{self._bot_id}:order_intents:latest"
            if not self._intent_history_key:
                self._intent_history_key = f"quantgambit:{self._tenant_id}:{self._bot_id}:order_intents:history"

    async def record(
        self,
        symbol: str,
        side: str,
        size: float,
        status: str,
        order_id: Optional[str] = None,
        client_order_id: Optional[str] = None,
        reason: Optional[str] = None,
        fill_price: Optional[float] = None,
        fee_usd: Optional[float] = None,
        filled_size: Optional[float] = None,
        remaining_size: Optional[float] = None,
        timestamp: Optional[float] = None,
        source: Optional[str] = None,
        exchange: Optional[str] = None,
        raw_exchange_status: Optional[str] = None,
        submitted_at: Optional[str] = None,
        accepted_at: Optional[str] = None,
        open_at: Optional[str] = None,
        filled_at: Optional[str] = None,
        event_type: Optional[str] = None,
        persist: bool = True,
        slippage_bps: Optional[float] = None,
    ) -> OrderRecord:
        normalized_status = normalize_order_status(status)
        key = order_id or client_order_id or f"{symbol}:{side}:{size}"
        record = self._orders.get(key)
        if not record:
            record = OrderRecord(
                symbol=symbol,
                side=side,
                size=size,
                status=normalized_status,
                order_id=order_id,
                client_order_id=client_order_id,
            )
            self._orders[key] = record
        update_ts = timestamp or time.time()
        if record.history and not self._should_accept_update(record, normalized_status, update_ts, source):
            return record
        record.status = normalized_status
        record.order_id = order_id or record.order_id
        record.client_order_id = client_order_id or record.client_order_id
        record.filled_size = filled_size if filled_size is not None else record.filled_size
        record.remaining_size = remaining_size if remaining_size is not None else record.remaining_size
        record.history.append(
            OrderStatusUpdate(
                status=normalized_status,
                timestamp=update_ts,
                reason=reason,
                fill_price=fill_price,
                fee_usd=fee_usd,
                filled_size=filled_size,
                remaining_size=remaining_size,
                source=source,
                raw_exchange_status=raw_exchange_status,
            )
        )
        if len(record.history) > self._max_history:
            record.history = record.history[-self._max_history :]
        if self._snapshot_writer and self._tenant_id and self._bot_id:
            payload = {
                "symbol": record.symbol,
                "side": record.side,
                "size": record.size,
                "status": record.status,
                "order_id": record.order_id,
                "client_order_id": record.client_order_id,
                "filled_size": record.filled_size,
                "remaining_size": record.remaining_size,
                "timestamp": record.history[-1].timestamp,
            }
            key_latest = f"quantgambit:{self._tenant_id}:{self._bot_id}:orders:latest"
            key_history = f"quantgambit:{self._tenant_id}:{self._bot_id}:orders:history"
            await self._snapshot_writer.write(key_latest, payload)
            await self._snapshot_writer.append_history(key_history, payload, max_items=self._max_history)
        if persist and self._postgres_store and self._tenant_id and self._bot_id:
            updated_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(update_ts))
            if order_id or client_order_id:
                await self._postgres_store.write_order_status(
                    OrderStatusRecord(
                        tenant_id=self._tenant_id,
                        bot_id=self._bot_id,
                        exchange=exchange,
                        symbol=symbol,
                        side=side,
                        size=size,
                        status=status,
                        order_id=order_id,
                        client_order_id=client_order_id,
                        reason=reason,
                        fill_price=fill_price,
                        fee_usd=fee_usd,
                        filled_size=filled_size,
                        remaining_size=remaining_size,
                        state_source=source,
                        raw_exchange_status=raw_exchange_status,
                        submitted_at=submitted_at,
                        accepted_at=accepted_at,
                        open_at=open_at,
                        filled_at=filled_at,
                        updated_at=updated_at,
                        slippage_bps=slippage_bps,
                    )
                )
            await self._postgres_store.write_order_event(
                OrderEventRecord(
                    tenant_id=self._tenant_id,
                    bot_id=self._bot_id,
                    exchange=exchange,
                    symbol=symbol,
                    side=side,
                    size=size,
                    status=status,
                    event_type=event_type or status,
                    order_id=order_id,
                    client_order_id=client_order_id,
                    reason=reason,
                    fill_price=fill_price,
                    fee_usd=fee_usd,
                    filled_size=filled_size,
                    remaining_size=remaining_size,
                    state_source=source,
                    raw_exchange_status=raw_exchange_status,
                    created_at=updated_at,
                    slippage_bps=slippage_bps,
                )
            )
        return record

    async def record_intent(
        self,
        intent_id: str,
        symbol: str,
        side: str,
        size: float,
        client_order_id: str,
        status: str,
        decision_id: Optional[str] = None,
        entry_price: Optional[float] = None,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
        strategy_id: Optional[str] = None,
        profile_id: Optional[str] = None,
        order_id: Optional[str] = None,
        last_error: Optional[str] = None,
        created_at: Optional[str] = None,
        submitted_at: Optional[str] = None,
        snapshot_metrics: Optional[dict] = None,  # Market conditions at entry time
    ) -> None:
        created_at = _coerce_iso(created_at) or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        submitted_at = _coerce_iso(submitted_at)
        if self._snapshot_writer and self._intent_history_key:
            payload = {
                "intent_id": _coerce_str(intent_id),
                "decision_id": _coerce_str(decision_id),
                "client_order_id": _coerce_str(client_order_id),
                "symbol": symbol,
                "side": side,
                "size": size,
                "entry_price": entry_price,
                "stop_loss": stop_loss,
                "take_profit": take_profit,
                "strategy_id": strategy_id,
                "profile_id": profile_id,
                "status": status,
                "order_id": _coerce_str(order_id),
                "last_error": last_error,
                "created_at": created_at,
                "submitted_at": submitted_at,
                "timestamp": time.time(),
                "snapshot_metrics": snapshot_metrics,  # Entry conditions for post-trade analysis
            }
            if self._intent_snapshot_key:
                await self._snapshot_writer.write(self._intent_snapshot_key, payload)
            await self._snapshot_writer.append_history(self._intent_history_key, payload, max_items=self._max_history)
        if not (self._postgres_store and self._tenant_id and self._bot_id):
            if client_order_id:
                self._intent_meta[client_order_id] = OrderIntentMeta(
                    symbol=symbol,
                    side=side,
                    size=size,
                    strategy_id=strategy_id,
                    profile_id=profile_id,
                    entry_price=entry_price,
                    stop_loss=stop_loss,
                    take_profit=take_profit,
                )
            return
        await self._postgres_store.write_order_intent(
            OrderIntentRecord(
                intent_id=_coerce_str(intent_id),
                tenant_id=self._tenant_id,
                bot_id=self._bot_id,
                decision_id=_coerce_str(decision_id),
                client_order_id=_coerce_str(client_order_id),
                symbol=symbol,
                side=side,
                size=size,
                entry_price=entry_price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                strategy_id=strategy_id,
                profile_id=profile_id,
                status=status,
                order_id=_coerce_str(order_id),
                last_error=last_error,
                created_at=created_at,
                submitted_at=submitted_at,
                snapshot_metrics=snapshot_metrics,
            )
        )
        if client_order_id:
            self._intent_meta[client_order_id] = OrderIntentMeta(
                symbol=symbol,
                side=side,
                size=size,
                strategy_id=strategy_id,
                profile_id=profile_id,
                entry_price=entry_price,
                stop_loss=stop_loss,
                take_profit=take_profit,
            )

    async def record_error(
        self,
        stage: str,
        error_message: str,
        error_code: Optional[str] = None,
        symbol: Optional[str] = None,
        order_id: Optional[str] = None,
        client_order_id: Optional[str] = None,
        payload: Optional[dict] = None,
    ) -> None:
        if not (self._postgres_store and self._tenant_id and self._bot_id):
            return
        created_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        exchange = payload.get("exchange") if isinstance(payload, dict) else None
        payload_value = payload
        if isinstance(payload, dict):
            payload_value = json.dumps(payload, separators=(",", ":"), sort_keys=True)
        await self._postgres_store.write_order_error(
            OrderErrorRecord(
                error_id=str(uuid.uuid4()),
                tenant_id=self._tenant_id,
                bot_id=self._bot_id,
                exchange=exchange,
                symbol=symbol,
                order_id=order_id,
                client_order_id=client_order_id,
                stage=stage,
                error_code=error_code,
                error_message=error_message,
                payload=payload_value,
                created_at=created_at,
            )
        )

    async def record_trade_cost(
        self,
        trade_id: str,
        symbol: str,
        profile_id: Optional[str],
        execution_price: float,
        decision_mid_price: float,
        slippage_bps: float,
        fees: float,
        funding_cost: float,
        total_cost: float,
        order_size: Optional[float],
        side: Optional[str],
        timestamp: Optional[str] = None,
        entry_fee_usd: Optional[float] = None,
        exit_fee_usd: Optional[float] = None,
        entry_fee_bps: Optional[float] = None,
        exit_fee_bps: Optional[float] = None,
        entry_slippage_bps: Optional[float] = None,
        exit_slippage_bps: Optional[float] = None,
        spread_cost_bps: Optional[float] = None,
        adverse_selection_bps: Optional[float] = None,
        total_cost_bps: Optional[float] = None,
    ) -> None:
        if not self._postgres_store:
            return
        await self._postgres_store.write_trade_cost(
            TradeCostRecord(
                trade_id=str(trade_id),
                symbol=symbol,
                profile_id=profile_id,
                execution_price=execution_price,
                decision_mid_price=decision_mid_price,
                slippage_bps=slippage_bps,
                fees=fees,
                funding_cost=funding_cost,
                total_cost=total_cost,
                order_size=order_size,
                side=side,
                timestamp=timestamp,
                entry_fee_usd=entry_fee_usd,
                exit_fee_usd=exit_fee_usd,
                entry_fee_bps=entry_fee_bps,
                exit_fee_bps=exit_fee_bps,
                entry_slippage_bps=entry_slippage_bps,
                exit_slippage_bps=exit_slippage_bps,
                spread_cost_bps=spread_cost_bps,
                adverse_selection_bps=adverse_selection_bps,
                total_cost_bps=total_cost_bps,
            )
        )

    def should_accept_update(
        self,
        order_id: Optional[str],
        client_order_id: Optional[str],
        status: str,
        timestamp: Optional[float] = None,
        source: Optional[str] = None,
    ) -> bool:
        record = self.get(order_id, client_order_id)
        if not record:
            return True
        update_ts = timestamp or time.time()
        normalized_status = normalize_order_status(status)
        return self._should_accept_update(record, normalized_status, update_ts, source)

    def _should_accept_update(
        self,
        record: OrderRecord,
        normalized_status: str,
        update_ts: float,
        source: Optional[str],
    ) -> bool:
        if record.history and update_ts < record.history[-1].timestamp:
            log_warning(
                "order_store_stale_update",
                order_id=record.order_id,
                client_order_id=record.client_order_id,
                previous_status=record.status,
                next_status=normalized_status,
                source=source,
            )
            return False
        if record.history and not is_valid_transition(record.status, normalized_status):
            if source == "rest" and is_terminal_status(normalized_status):
                return True
            log_warning(
                "order_store_invalid_transition",
                order_id=record.order_id,
                client_order_id=record.client_order_id,
                previous_status=record.status,
                next_status=normalized_status,
                source=source,
            )
            return False
        return True

    def get(self, order_id: Optional[str], client_order_id: Optional[str] = None) -> Optional[OrderRecord]:
        key = order_id or client_order_id
        if not key:
            return None
        return self._orders.get(key)

    def list_orders(self) -> list[OrderRecord]:
        return list(self._orders.values())

    def get_intent_meta(self, client_order_id: Optional[str]) -> Optional[OrderIntentMeta]:
        if not client_order_id:
            return None
        return self._intent_meta.get(client_order_id)

    async def resolve_intent_meta(self, client_order_id: Optional[str]) -> Optional[OrderIntentMeta]:
        if not client_order_id:
            return None
        meta = self._intent_meta.get(client_order_id)
        if meta:
            return meta
        if not (self._postgres_store and self._tenant_id and self._bot_id):
            return None
        row = await self._postgres_store.load_intent_by_client_order_id(
            self._tenant_id,
            self._bot_id,
            client_order_id,
        )
        if not row:
            return None
        meta = OrderIntentMeta(
            symbol=row.get("symbol"),
            side=row.get("side"),
            size=row.get("size"),
            strategy_id=row.get("strategy_id"),
            profile_id=row.get("profile_id"),
            entry_price=row.get("entry_price"),
            stop_loss=row.get("stop_loss"),
            take_profit=row.get("take_profit"),
        )
        self._intent_meta[client_order_id] = meta
        return meta

    async def load(self) -> int:
        if not (self._postgres_store and self._tenant_id and self._bot_id):
            await self._load_from_snapshots()
            return len(self._orders)
        rows = await self._postgres_store.load_latest(self._tenant_id, self._bot_id)
        for row in rows:
            key = row.get("order_id") or row.get("client_order_id")
            if not key:
                continue
            record = OrderRecord(
                symbol=row.get("symbol"),
                side=row.get("side"),
                size=row.get("size"),
                status=row.get("status"),
                order_id=row.get("order_id"),
                client_order_id=row.get("client_order_id"),
                filled_size=row.get("filled_size"),
                remaining_size=row.get("remaining_size"),
            )
            self._orders[key] = record
        await self._load_from_snapshots()
        return len(self._orders)

    async def replay_recent_events(self, hours: float, limit: int = 500) -> int:
        if not (self._postgres_store and self._tenant_id and self._bot_id):
            return 0
        since = None
        if hours and hours > 0:
            since = datetime.now(timezone.utc) - timedelta(hours=hours)
        rows = await self._postgres_store.load_order_events(self._tenant_id, self._bot_id, since, limit)
        for row in rows:
            timestamp = _event_timestamp(row.get("created_at"))
            await self.record(
                symbol=row.get("symbol"),
                side=row.get("side"),
                size=row.get("size"),
                status=row.get("status"),
                order_id=row.get("order_id"),
                client_order_id=row.get("client_order_id"),
                reason=row.get("reason"),
                fill_price=row.get("fill_price"),
                fee_usd=row.get("fee_usd"),
                filled_size=row.get("filled_size"),
                remaining_size=row.get("remaining_size"),
                timestamp=timestamp,
                source=row.get("state_source"),
                exchange=row.get("exchange"),
                raw_exchange_status=row.get("raw_exchange_status"),
                event_type=row.get("event_type"),
                persist=False,
            )
        return len(rows)

    async def load_pending_intents(self) -> list[dict]:
        if self._postgres_store and self._tenant_id and self._bot_id:
            self._last_intent_drop_stats = None
            return await self._postgres_store.load_pending_intents(self._tenant_id, self._bot_id)
        if not (self._snapshot_reader and self._intent_history_key):
            self._last_intent_drop_stats = None
            return []
        now = time.time()
        items = await self._snapshot_reader.read_history(self._intent_history_key, limit=self._max_history)
        pending: dict[str, dict] = {}
        stale_dropped = 0
        for item in items:
            status = normalize_order_status(item.get("status"))
            if is_terminal_status(status):
                continue
            if self._max_intent_age_sec is not None:
                ts = item.get("timestamp")
                if ts is None:
                    continue
                try:
                    age = now - float(ts)
                except (TypeError, ValueError):
                    continue
                if age > self._max_intent_age_sec:
                    stale_dropped += 1
                    continue
            key = item.get("client_order_id") or item.get("intent_id")
            if not key or key in pending:
                continue
            item = dict(item)
            item["status"] = status
            pending[key] = item
        self._last_intent_drop_stats = {"stale": stale_dropped} if stale_dropped else None
        return list(pending.values())

    def pop_intent_drop_stats(self) -> Optional[dict]:
        stats = self._last_intent_drop_stats
        self._last_intent_drop_stats = None
        return stats

    async def load_intent_by_client_order_id(self, client_order_id: str) -> Optional[dict]:
        if not (self._postgres_store and self._tenant_id and self._bot_id):
            return None
        return await self._postgres_store.load_intent_by_client_order_id(
            self._tenant_id,
            self._bot_id,
            client_order_id,
        )

    async def _load_from_snapshots(self) -> None:
        if not (self._snapshot_reader and self._snapshot_history_key):
            return
        items = await self._snapshot_reader.read_history(self._snapshot_history_key, limit=self._max_history)
        if not items:
            return
        if self._postgres_store:
            for item in items:
                key = item.get("order_id") or item.get("client_order_id")
                if not key or key in self._orders:
                    continue
                record = OrderRecord(
                    symbol=item.get("symbol"),
                    side=item.get("side"),
                    size=item.get("size"),
                    status=item.get("status"),
                    order_id=item.get("order_id"),
                    client_order_id=item.get("client_order_id"),
                    filled_size=item.get("filled_size"),
                    remaining_size=item.get("remaining_size"),
                )
                self._orders[key] = record
            return
        ordered = sorted(items, key=_snapshot_timestamp)
        for item in ordered:
            key = item.get("order_id") or item.get("client_order_id")
            if not key:
                continue
            normalized_status = normalize_order_status(item.get("status"))
            timestamp = _snapshot_timestamp(item)
            record = self._orders.get(key)
            if not record:
                record = OrderRecord(
                    symbol=item.get("symbol"),
                    side=item.get("side"),
                    size=item.get("size"),
                    status=normalized_status,
                    order_id=item.get("order_id"),
                    client_order_id=item.get("client_order_id"),
                    filled_size=item.get("filled_size"),
                    remaining_size=item.get("remaining_size"),
                )
                self._orders[key] = record
            record.status = normalized_status
            record.order_id = item.get("order_id") or record.order_id
            record.client_order_id = item.get("client_order_id") or record.client_order_id
            if item.get("filled_size") is not None:
                record.filled_size = item.get("filled_size")
            if item.get("remaining_size") is not None:
                record.remaining_size = item.get("remaining_size")
            record.history.append(
                OrderStatusUpdate(
                    status=normalized_status,
                    timestamp=timestamp,
                    filled_size=item.get("filled_size"),
                    remaining_size=item.get("remaining_size"),
                )
            )
            if len(record.history) > self._max_history:
                record.history = record.history[-self._max_history :]


def _event_timestamp(value) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=timezone.utc).timestamp()
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _snapshot_timestamp(item: dict) -> float:
    ts = item.get("timestamp")
    if ts is None:
        return 0.0
    try:
        return float(ts)
    except (TypeError, ValueError):
        return 0.0


def _coerce_str(value: Optional[object]) -> Optional[str]:
    if value is None:
        return None
    return str(value)


def _coerce_iso(value: Optional[object]) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return str(value)
