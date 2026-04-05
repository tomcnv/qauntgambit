"""Orderbook feed producer publishing snapshots/deltas to Redis."""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass
from typing import Optional, Protocol

from quantgambit.ingest.schemas import (
    validate_orderbook_snapshot,
    validate_orderbook_delta,
    validate_market_tick,
)
from quantgambit.ingest.time_utils import resolve_exchange_timestamp, now_recv_us, us_to_sec
from quantgambit.ingest.monotonic_clock import MonotonicClock
from quantgambit.observability.logger import log_warning, log_info
from quantgambit.execution.symbols import normalize_exchange_symbol
from quantgambit.storage.redis_streams import Event, RedisStreamsClient, decode_message


class OrderbookFeedProvider(Protocol):
    async def next_update(self) -> Optional[dict]:
        """Return the next orderbook update with type snapshot|delta."""


@dataclass
class OrderbookFeedConfig:
    stream: str = "events:orderbook_feed"
    idle_backoff_sec: float = 0.05
    timestamp_source: str = "exchange"  # exchange|local
    # Increase tolerance to 30s to handle Binance timestamp drift without constant skew warnings
    max_clock_skew_sec: float = 30.0
    emit_market_ticks: bool = False
    market_data_stream: str = "events:market_data"
    resync_stream: str = "events:orderbook_resync"
    resync_group: str = "quantgambit_orderbook_resync"
    resync_consumer: str = "orderbook_feed"
    resync_block_ms: int = 1
    binance_sync_window_sec: float = 3.0
    binance_resync_cooldown_sec: float = 5.0


class OrderbookFeedWorker:
    """Publish orderbook snapshots/deltas from a provider to Redis streams."""

    def __init__(
        self,
        provider: OrderbookFeedProvider,
        redis_client: RedisStreamsClient,
        bot_id: str,
        exchange: str,
        config: Optional[OrderbookFeedConfig] = None,
        monotonic_clock: Optional[MonotonicClock] = None,
    ):
        self.provider = provider
        self.redis = redis_client
        self.bot_id = bot_id
        self.exchange = exchange
        self.config = config or OrderbookFeedConfig()
        self._binance_pending_seq: dict[str, int] = {}
        self._binance_pending_since: dict[str, float] = {}
        self._binance_last_seq: dict[str, int] = {}
        self._binance_last_resync_at: dict[str, float] = {}
        self._monotonic_clock = monotonic_clock

    async def run(self) -> None:
        log_info("orderbook_feed_start", stream=self.config.stream, exchange=self.exchange)
        await self.redis.create_group(self.config.resync_stream, self.config.resync_group)
        while True:
            await self._handle_resync()
            update = await self.provider.next_update()
            if not update:
                await asyncio.sleep(self.config.idle_backoff_sec)
                continue
            event_type = update.get("type")
            payload = update.get("payload") or {}
            recv_us = now_recv_us()
            recv_ts = us_to_sec(recv_us)
            raw_ts = payload.get("timestamp")
            exchange_ts, skewed, skew_sec = resolve_exchange_timestamp(
                raw_ts,
                recv_ts,
                self.config.max_clock_skew_sec,
            )
            symbol = payload.get("symbol")
            ts_canon_us = self._monotonic_clock.update(symbol, recv_us) if self._monotonic_clock else recv_us
            # Canonical timestamp for all windows/staleness: receive time (microseconds)
            payload["ts_recv_us"] = recv_us
            payload["ts_canon_us"] = ts_canon_us
            payload["ts_exchange_s"] = exchange_ts
            payload["timestamp"] = us_to_sec(ts_canon_us)
            if skewed:
                log_warning(
                    "orderbook_timestamp_skew",
                    symbol=payload.get("symbol"),
                    raw_ts=raw_ts,
                    skew_sec=round(skew_sec or 0.0, 6),
                )
            if event_type == "snapshot":
                await self._publish_snapshot(payload)
            elif event_type == "delta":
                await self._publish_delta(payload)
            else:
                log_warning("orderbook_feed_unknown_type", event_type=event_type)

    async def _publish_snapshot(self, payload: dict) -> None:
        payload["exchange"] = self.exchange
        payload["symbol"] = normalize_exchange_symbol(self.exchange, payload.get("symbol"))
        payload["bids"] = _normalize_levels(payload.get("bids") or [])
        payload["asks"] = _normalize_levels(payload.get("asks") or [])
        if self.exchange == "binance":
            try:
                seq_val = int(payload.get("seq") or 0)
            except (TypeError, ValueError):
                seq_val = 0
            self._binance_pending_seq[payload["symbol"]] = seq_val
            self._binance_pending_since[payload["symbol"]] = time.time()
            self._binance_last_seq[payload["symbol"]] = seq_val
        try:
            validate_orderbook_snapshot(payload)
        except Exception as exc:
            log_warning("orderbook_snapshot_invalid", error=str(exc))
            return
        event = Event(
            event_id=str(uuid.uuid4()),
            event_type="orderbook_snapshot",
            schema_version="v1",
            timestamp=str(payload.get("timestamp")),
            ts_recv_us=payload.get("ts_recv_us"),
            ts_canon_us=payload.get("ts_canon_us"),
            ts_exchange_s=payload.get("ts_exchange_s"),
            bot_id=self.bot_id,
            symbol=payload.get("symbol"),
            exchange=self.exchange,
            payload=payload,
        )
        await self.redis.publish_event(self.config.stream, event)
        log_info(
            "orderbook_snapshot_published",
            exchange=self.exchange,
            symbol=payload.get("symbol"),
            bot_id=self.bot_id,
        )
        await self._publish_market_tick(payload)

    async def _publish_delta(self, payload: dict) -> None:
        payload["exchange"] = self.exchange
        payload["symbol"] = normalize_exchange_symbol(self.exchange, payload.get("symbol"))
        payload["bids"] = _normalize_levels(payload.get("bids") or [])
        payload["asks"] = _normalize_levels(payload.get("asks") or [])
        if self.exchange == "binance":
            first_seq = _coerce_int(payload.get("first_seq"))
            last_seq = _coerce_int(payload.get("last_seq") or payload.get("seq"))
            symbol = payload["symbol"]
            if first_seq is not None and last_seq is not None:
                pending_seq = self._binance_pending_seq.get(symbol)
                if pending_seq is not None:
                    expected = pending_seq + 1
                    if last_seq < expected:
                        return
                    if first_seq > expected:
                        pending_since = self._binance_pending_since.get(symbol, 0.0)
                        if time.time() - pending_since >= self.config.binance_sync_window_sec:
                            await self._request_snapshot_direct(symbol, reason="gap_before_sync")
                        return
                    self._binance_pending_seq.pop(symbol, None)
                    self._binance_pending_since.pop(symbol, None)
                last_seen = self._binance_last_seq.get(symbol)
                if last_seen is not None:
                    expected = last_seen + 1
                    if last_seq <= last_seen:
                        return
                    if first_seq > expected:
                        await self._request_snapshot_direct(symbol, reason="gap_after_sync")
                        return
                    if last_seq < expected:
                        return
                self._binance_last_seq[symbol] = last_seq
        try:
            validate_orderbook_delta(payload)
        except Exception as exc:
            log_warning("orderbook_delta_invalid", error=str(exc))
            return
        event = Event(
            event_id=str(uuid.uuid4()),
            event_type="orderbook_delta",
            schema_version="v1",
            timestamp=str(payload.get("timestamp")),
            ts_recv_us=payload.get("ts_recv_us"),
            ts_canon_us=payload.get("ts_canon_us"),
            ts_exchange_s=payload.get("ts_exchange_s"),
            bot_id=self.bot_id,
            symbol=payload.get("symbol"),
            exchange=self.exchange,
            payload=payload,
        )
        await self.redis.publish_event(self.config.stream, event)
        await self._publish_market_tick(payload)

    async def _publish_market_tick(self, payload: dict) -> None:
        if not self.config.emit_market_ticks:
            return
        best_bid, best_ask = _best_bid_ask(payload.get("bids") or [], payload.get("asks") or [])
        if best_bid is None or best_ask is None:
            return
        tick = {
            "symbol": payload.get("symbol"),
            "timestamp": payload.get("timestamp"),
            "ts_recv_us": payload.get("ts_recv_us"),
            "ts_canon_us": payload.get("ts_canon_us"),
            "ts_exchange_s": payload.get("ts_exchange_s"),
            "bid": best_bid,
            "ask": best_ask,
            "last": None,
            "source": "orderbook_feed",
        }
        try:
            validate_market_tick(tick)
        except Exception as exc:
            log_warning("orderbook_market_tick_invalid", error=str(exc))
            return
        event = Event(
            event_id=str(uuid.uuid4()),
            event_type="market_tick",
            schema_version="v1",
            timestamp=str(payload.get("timestamp")),
            ts_recv_us=tick.get("ts_recv_us"),
            ts_canon_us=tick.get("ts_canon_us"),
            ts_exchange_s=tick.get("ts_exchange_s"),
            bot_id=self.bot_id,
            symbol=tick.get("symbol"),
            exchange=self.exchange,
            payload=tick,
        )
        await self.redis.publish_event(self.config.market_data_stream, event)

    async def _handle_resync(self) -> None:
        try:
            messages = await self.redis.read_group(
                self.config.resync_group,
                self.config.resync_consumer,
                {self.config.resync_stream: ">"},
                count=5,
                block_ms=self.config.resync_block_ms,
            )
        except Exception as exc:
            log_warning("orderbook_resync_read_failed", error=str(exc))
            return
        if not messages:
            return
        log_info(
            "orderbook_resync_received",
            exchange=self.exchange,
            stream=self.config.resync_stream,
            count=sum(len(entries) for _, entries in messages),
        )
        for stream_name, entries in messages:
            for message_id, payload in entries:
                await self._request_snapshot(payload)
                await self.redis.ack(stream_name, self.config.resync_group, message_id)

    async def _request_snapshot(self, payload: dict) -> None:
        try:
            event = decode_message(payload)
        except Exception:
            return
        if event.get("event_type") != "orderbook_resync":
            return
        if hasattr(self.provider, "request_snapshot"):
            log_info(
                "orderbook_resync_request",
                exchange=self.exchange,
                symbol=event.get("symbol"),
                bot_id=event.get("bot_id"),
            )
            await self.provider.request_snapshot()
            return
        log_warning(
            "orderbook_resync_no_snapshot_provider",
            exchange=self.exchange,
            symbol=event.get("symbol"),
            bot_id=event.get("bot_id"),
        )

    async def _request_snapshot_direct(self, symbol: str, reason: str) -> None:
        now = time.time()
        last = self._binance_last_resync_at.get(symbol, 0.0)
        if now - last < self.config.binance_resync_cooldown_sec:
            return
        self._binance_last_resync_at[symbol] = now
        if hasattr(self.provider, "request_snapshot"):
            log_info(
                "orderbook_resync_request",
                exchange=self.exchange,
                symbol=symbol,
                reason=reason,
            )
            await self.provider.request_snapshot()


def _best_bid_ask(bids: list, asks: list) -> tuple[Optional[float], Optional[float]]:
    if not bids or not asks:
        return None, None
    try:
        best_bid = float(bids[0][0])
        best_ask = float(asks[0][0])
    except (TypeError, ValueError, IndexError):
        return None, None
    return best_bid, best_ask


def _normalize_levels(levels: list) -> list[list]:
    normalized = []
    for level in levels:
        if isinstance(level, dict):
            price = level.get("price")
            size = level.get("size")
        elif isinstance(level, (list, tuple)) and len(level) >= 2:
            price, size = level[0], level[1]
        else:
            continue
        try:
            price_val = float(price)
            size_val = float(size)
        except (TypeError, ValueError):
            continue
        normalized.append([price_val, size_val])
    return normalized


def _resolve_orderbook_timestamp(
    raw_ts: Optional[float],
    source: str,
    max_skew_sec: float,
) -> tuple[float, bool, Optional[float]]:
    """Deprecated: use resolve_exchange_timestamp with canonical recv_ts."""
    now = time.time()
    if (source or "").lower() == "local":
        return now, False, None
    if raw_ts is None:
        return now, False, None
    try:
        ts_val = float(raw_ts)
    except (TypeError, ValueError):
        return now, False, None
    if ts_val > 10_000_000_000:
        ts_val = ts_val / 1000.0
    skew = abs(now - ts_val)
    if max_skew_sec > 0 and skew > max_skew_sec:
        return now, True, skew
    return ts_val, False, skew


def _coerce_int(value: Optional[float]) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
