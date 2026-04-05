"""Orderbook ingestion worker with sequence validation."""

from __future__ import annotations

from dataclasses import dataclass
import json
import time
import uuid
from typing import Dict, Optional, TYPE_CHECKING

from quantgambit.ingest.schemas import validate_orderbook_snapshot, validate_orderbook_delta, validate_market_tick
from quantgambit.market.orderbooks import OrderbookState
from quantgambit.market.reference_prices import ReferencePriceCache
from quantgambit.market.quality import MarketDataQualityTracker
from quantgambit.observability.logger import log_warning, log_info
from quantgambit.observability.telemetry import TelemetryContext, TelemetryPipeline
from quantgambit.storage.redis_streams import RedisStreamsClient, decode_and_validate_event, Event
from quantgambit.ingest.time_utils import now_recv_us, us_to_sec

if TYPE_CHECKING:
    from quantgambit.storage.orderbook_snapshot_writer import OrderbookSnapshotWriter
    from quantgambit.storage.live_data_validator import LiveDataValidator


@dataclass
class OrderbookWorkerConfig:
    source_stream: str = "events:orderbook_feed"
    consumer_group: str = "quantgambit_orderbook"
    consumer_name: str = "orderbook_worker"
    block_ms: int = 1000
    depth: int = 20
    emit_market_ticks: bool = False
    market_data_stream: str = "events:market_data"
    # Increase resync interval to reduce churn - give more time for recovery
    resync_min_interval_sec: float = 5.0
    allow_delta_bootstrap: bool = True


class OrderbookWorker:
    """Consume orderbook snapshots and deltas, validate sequences, update cache."""

    def __init__(
        self,
        redis_client: RedisStreamsClient,
        cache: ReferencePriceCache,
        quality_tracker: Optional[MarketDataQualityTracker] = None,
        config: Optional[OrderbookWorkerConfig] = None,
        telemetry: Optional[TelemetryPipeline] = None,
        telemetry_context: Optional[TelemetryContext] = None,
        snapshot_writer: Optional["OrderbookSnapshotWriter"] = None,
        live_validator: Optional["LiveDataValidator"] = None,
    ):
        self.redis = redis_client
        self.cache = cache
        self.quality_tracker = quality_tracker
        self.config = config or OrderbookWorkerConfig()
        self.telemetry = telemetry
        self.telemetry_context = telemetry_context
        self.snapshot_writer = snapshot_writer
        self.live_validator = live_validator
        self._books: Dict[str, OrderbookState] = {}
        self._pending_snapshot_seq: Dict[str, int] = {}
        self._resync_stream = "events:orderbook_resync"
        self._last_resync_at: Dict[str, float] = {}
        self._warmup_emitted: Dict[str, bool] = {}
        # Track exchange per symbol for persistence
        self._symbol_exchange: Dict[str, str] = {}

    async def run(self) -> None:
        log_info("orderbook_worker_start", source=self.config.source_stream)
        await self.redis.create_group(self.config.source_stream, self.config.consumer_group, start_id="$")
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

    async def _invoke_persistence(
        self,
        symbol: str,
        exchange: Optional[str],
        state: OrderbookState,
        timestamp: float,
        seq: int,
    ) -> None:
        """Invoke snapshot writer and live validator after successful orderbook update.
        
        This helper method is called after each successful orderbook update to:
        1. Capture a snapshot if the interval has elapsed (Requirement 6.1)
        2. Record the update for quality tracking (Requirement 4.1)
        
        Both operations are non-blocking and respect their respective config.enabled flags.
        """
        exchange_name = exchange or self._symbol_exchange.get(symbol, "unknown")
        
        # Invoke snapshot writer if configured (Requirement 6.1)
        if self.snapshot_writer:
            try:
                await self.snapshot_writer.maybe_capture(
                    symbol=symbol,
                    exchange=exchange_name,
                    state=state,
                    timestamp=timestamp,
                    seq=seq,
                )
            except Exception as exc:
                log_warning("orderbook_snapshot_write_error", symbol=symbol, error=str(exc))
        
        # Invoke live data validator if configured (Requirement 4.1)
        if self.live_validator:
            try:
                self.live_validator.record_orderbook_update(
                    symbol=symbol,
                    exchange=exchange_name,
                    timestamp=timestamp,
                    seq=seq,
                )
            except Exception as exc:
                log_warning("orderbook_validation_error", symbol=symbol, error=str(exc))

    async def _handle_message(self, payload: dict) -> None:
        try:
            event = decode_and_validate_event(payload)
        except Exception as exc:
            log_warning("orderbook_worker_invalid_event", error=str(exc))
            return
        event_type = event.get("event_type")
        data = event.get("payload") or {}
        exchange = data.get("exchange") or event.get("exchange")
        if event_type == "orderbook_snapshot":
            try:
                validate_orderbook_snapshot(data)
            except Exception as exc:
                log_warning("orderbook_snapshot_invalid", error=str(exc))
                return
            await self._apply_snapshot(data, exchange=exchange)
        elif event_type == "orderbook_delta":
            try:
                validate_orderbook_delta(data)
            except Exception as exc:
                log_warning("orderbook_delta_invalid", error=str(exc))
                return
            await self._apply_delta(data, exchange=exchange)

    async def _apply_snapshot(self, data: dict, exchange: Optional[str] = None) -> None:
        symbol = data["symbol"]
        seq = int(data["seq"])
        timestamp = data.get("timestamp")
        try:
            timestamp = float(timestamp)
        except (TypeError, ValueError):
            timestamp = time.time()
        state = self._books.get(symbol) or OrderbookState(symbol=symbol)
        state.apply_snapshot(data.get("bids") or [], data.get("asks") or [], seq=seq)
        self._books[symbol] = state
        # Track exchange for this symbol for persistence
        if exchange:
            self._symbol_exchange[symbol] = exchange
        if exchange == "binance":
            # Binance requires the first delta to bracket snapshot_seq + 1 before we go live.
            self._pending_snapshot_seq[symbol] = seq
        bids, asks = state.as_levels(self.config.depth)
        _update_mid_price_cache(self.cache, symbol, bids, asks, timestamp)
        # Pass cts_ms (exchange matching engine timestamp) for latency measurement
        cts_ms = data.get("cts_ms")
        self.cache.update_orderbook(symbol, bids, asks, timestamp=timestamp, cts_ms=cts_ms)
        if self.quality_tracker:
            self.quality_tracker.update_orderbook(symbol, timestamp, now_ts=timestamp, gap=False)
            # Fresh snapshot clears any prior gap state
            if hasattr(self.quality_tracker, 'reset_counters'):
                self.quality_tracker.reset_counters(symbol, now_ts=timestamp)
        
        # Invoke persistence layer (Requirements 6.1, 4.1)
        await self._invoke_persistence(symbol, exchange, state, timestamp, seq)
        await self._publish_market_tick(symbol, exchange, timestamp, bids, asks)
        await self._mark_warmup(symbol, ready=True, reasons=[], timestamp=timestamp, sync_state="snapshot")
        log_info("orderbook_snapshot_applied", symbol=symbol, seq=seq)

    async def _apply_delta(self, data: dict, exchange: Optional[str] = None) -> None:
        symbol = data["symbol"]
        seq = int(data["seq"])
        first_seq = data.get("first_seq")
        last_seq = data.get("last_seq")
        prev_seq = data.get("prev_seq")
        seq_tolerant = bool(data.get("seq_tolerant"))
        # Extract cts_ms (exchange matching engine timestamp) for latency measurement
        cts_ms = data.get("cts_ms")
        # Track exchange for this symbol for persistence
        if exchange:
            self._symbol_exchange[symbol] = exchange
        if first_seq is not None:
            try:
                first_seq = int(first_seq)
            except (TypeError, ValueError):
                first_seq = None
        if last_seq is not None:
            try:
                last_seq = int(last_seq)
            except (TypeError, ValueError):
                last_seq = None
        if prev_seq is not None:
            try:
                prev_seq = int(prev_seq)
            except (TypeError, ValueError):
                prev_seq = None
        timestamp = data.get("timestamp")
        try:
            timestamp = float(timestamp)
        except (TypeError, ValueError):
            timestamp = time.time()
        state = self._books.get(symbol)
        if not state:
            if self.config.allow_delta_bootstrap and data.get("bids") and data.get("asks"):
                if await self._bootstrap_from_delta(symbol, data, timestamp, seq, last_seq, cts_ms=cts_ms, exchange=exchange):
                    return
            log_warning("orderbook_delta_no_snapshot", symbol=symbol)
            if self.quality_tracker:
                self.quality_tracker.update_orderbook(symbol, timestamp, now_ts=timestamp, gap=True)
            await self._publish_resync(symbol, timestamp)
            return
        if not state.valid:
            if self.config.allow_delta_bootstrap and data.get("bids") and data.get("asks"):
                if await self._bootstrap_from_delta(symbol, data, timestamp, seq, last_seq, cts_ms=cts_ms, exchange=exchange):
                    return
            log_warning("orderbook_delta_waiting_snapshot", symbol=symbol)
            if self.quality_tracker:
                self.quality_tracker.update_orderbook(symbol, timestamp, now_ts=timestamp, gap=True)
            await self._publish_resync(symbol, timestamp)
            await self._mark_warmup(symbol, ready=False, reasons=["orderbook_unsynced"], timestamp=timestamp, sync_state="waiting_snapshot")
            return
        if exchange == "binance" and first_seq is not None and last_seq is not None:
            pending_seq = self._pending_snapshot_seq.get(symbol)
            if pending_seq is not None:
                expected = pending_seq + 1
                if last_seq < expected:
                    log_info(
                        "orderbook_delta_before_snapshot",
                        symbol=symbol,
                        snapshot_seq=pending_seq,
                        first_seq=first_seq,
                        last_seq_range=last_seq,
                    )
                    return
                if first_seq > expected:
                    log_warning(
                        "orderbook_delta_gap",
                        symbol=symbol,
                        seq=seq,
                        last_seq=state.seq,
                        first_seq=first_seq,
                        last_seq_range=last_seq,
                    )
                    state.valid = False
                    self._pending_snapshot_seq.pop(symbol, None)
                    self.cache.clear_orderbook(symbol)
                    if self.quality_tracker:
                        self.quality_tracker.update_orderbook(symbol, timestamp, now_ts=timestamp, gap=True)
                    await self._publish_resync(symbol, timestamp)
                    await self._mark_warmup(symbol, ready=False, reasons=["orderbook_gap"], timestamp=timestamp, sync_state="resyncing")
                    return
                log_info("orderbook_delta_sync_complete", symbol=symbol, snapshot_seq=pending_seq)
                self._pending_snapshot_seq.pop(symbol, None)
                seq = last_seq
                state.apply_delta(data.get("bids") or [], data.get("asks") or [], seq=seq)
                bids, asks = state.as_levels(self.config.depth)
                _update_mid_price_cache(self.cache, symbol, bids, asks, timestamp)
                self.cache.update_orderbook(symbol, bids, asks, timestamp=timestamp, cts_ms=cts_ms)
                if self.quality_tracker:
                    self.quality_tracker.update_orderbook(symbol, timestamp, now_ts=timestamp, gap=False)
                await self._invoke_persistence(symbol, exchange, state, timestamp, seq)
                await self._publish_market_tick(symbol, exchange, timestamp, bids, asks)
                return
            if last_seq <= state.seq:
                log_info(
                    "orderbook_delta_duplicate",
                    symbol=symbol,
                    seq=seq,
                    last_seq=state.seq,
                    first_seq=first_seq,
                    last_seq_range=last_seq,
                )
                return
            expected = state.seq + 1
            if first_seq > expected or last_seq < expected:
                log_warning(
                    "orderbook_delta_gap",
                    symbol=symbol,
                    seq=seq,
                    last_seq=state.seq,
                    first_seq=first_seq,
                    last_seq_range=last_seq,
                )
                state.valid = False
                self.cache.clear_orderbook(symbol)
                if self.quality_tracker:
                    self.quality_tracker.update_orderbook(symbol, timestamp, now_ts=timestamp, gap=True)
                await self._publish_resync(symbol, timestamp)
                await self._mark_warmup(symbol, ready=False, reasons=["orderbook_gap"], timestamp=timestamp, sync_state="resyncing")
                return
            seq = last_seq
            state.apply_delta(data.get("bids") or [], data.get("asks") or [], seq=seq)
            bids, asks = state.as_levels(self.config.depth)
            _update_mid_price_cache(self.cache, symbol, bids, asks, timestamp)
            self.cache.update_orderbook(symbol, bids, asks, timestamp=timestamp, cts_ms=cts_ms)
            if self.quality_tracker:
                self.quality_tracker.update_orderbook(symbol, timestamp, now_ts=timestamp, gap=False)
            await self._invoke_persistence(symbol, exchange, state, timestamp, seq)
            await self._publish_market_tick(symbol, exchange, timestamp, bids, asks)
            return
        if seq_tolerant:
            if seq <= state.seq:
                seq = state.seq + 1
            # log_info("orderbook_delta_seq_tolerant", ...) — suppressed: 100+/sec on Bybit spot demo starved event loop
            state.apply_delta(data.get("bids") or [], data.get("asks") or [], seq=seq)
            bids, asks = state.as_levels(self.config.depth)
            _update_mid_price_cache(self.cache, symbol, bids, asks, timestamp)
            self.cache.update_orderbook(symbol, bids, asks, timestamp=timestamp, cts_ms=cts_ms)
            if self.quality_tracker:
                self.quality_tracker.update_orderbook(symbol, timestamp, now_ts=timestamp, gap=False)
            await self._invoke_persistence(symbol, exchange, state, timestamp, seq)
            await self._publish_market_tick(symbol, exchange, timestamp, bids, asks)
            return
        if exchange != "binance" and prev_seq is not None:
            if prev_seq != state.seq:
                log_warning(
                    "orderbook_delta_gap",
                    symbol=symbol,
                    seq=seq,
                    last_seq=state.seq,
                    prev_seq=prev_seq,
                )
                state.valid = False
                self.cache.clear_orderbook(symbol)
                if self.quality_tracker:
                    self.quality_tracker.update_orderbook(symbol, timestamp, now_ts=timestamp, gap=True)
                await self._publish_resync(symbol, timestamp)
                await self._mark_warmup(symbol, ready=False, reasons=["orderbook_gap"], timestamp=timestamp, sync_state="resyncing")
                return
            state.apply_delta(data.get("bids") or [], data.get("asks") or [], seq=seq)
            bids, asks = state.as_levels(self.config.depth)
            _update_mid_price_cache(self.cache, symbol, bids, asks, timestamp)
            self.cache.update_orderbook(symbol, bids, asks, timestamp=timestamp, cts_ms=cts_ms)
            if self.quality_tracker:
                self.quality_tracker.update_orderbook(symbol, timestamp, now_ts=timestamp, gap=False)
            await self._invoke_persistence(symbol, exchange, state, timestamp, seq)
            await self._mark_warmup(symbol, ready=True, reasons=[], timestamp=timestamp, sync_state="synced")
            return
        if first_seq is not None and last_seq is not None:
            if last_seq <= state.seq:
                log_info(
                    "orderbook_delta_duplicate",
                    symbol=symbol,
                    seq=seq,
                    last_seq=state.seq,
                    first_seq=first_seq,
                    last_seq_range=last_seq,
                )
                return
        else:
            if seq <= state.seq:
                log_warning("orderbook_delta_out_of_order", symbol=symbol, seq=seq, last_seq=state.seq)
                state.valid = False
                self.cache.clear_orderbook(symbol)
                if self.quality_tracker:
                    self.quality_tracker.update_orderbook(symbol, timestamp, now_ts=timestamp, gap=True, out_of_order=True)
                await self._publish_resync(symbol, timestamp)
                await self._mark_warmup(symbol, ready=False, reasons=["orderbook_out_of_order"], timestamp=timestamp, sync_state="resyncing")
                return
        if first_seq is not None and last_seq is not None:
            expected = state.seq + 1
            if first_seq > expected or last_seq < expected:
                log_warning(
                    "orderbook_delta_gap",
                    symbol=symbol,
                    seq=seq,
                    last_seq=state.seq,
                    first_seq=first_seq,
                    last_seq_range=last_seq,
                )
                state.valid = False
                self.cache.clear_orderbook(symbol)
                if self.quality_tracker:
                    self.quality_tracker.update_orderbook(symbol, timestamp, now_ts=timestamp, gap=True)
                await self._publish_resync(symbol, timestamp)
                await self._mark_warmup(symbol, ready=False, reasons=["orderbook_gap"], timestamp=timestamp, sync_state="resyncing")
                return
            seq = last_seq
        else:
            if seq != state.seq + 1:
                log_warning("orderbook_delta_gap", symbol=symbol, seq=seq, last_seq=state.seq)
                state.valid = False
                self.cache.clear_orderbook(symbol)
                if self.quality_tracker:
                    self.quality_tracker.update_orderbook(symbol, timestamp, now_ts=timestamp, gap=True)
                await self._publish_resync(symbol, timestamp)
                await self._mark_warmup(symbol, ready=False, reasons=["orderbook_gap"], timestamp=timestamp, sync_state="resyncing")
                return
        state.apply_delta(data.get("bids") or [], data.get("asks") or [], seq=seq)
        bids, asks = state.as_levels(self.config.depth)
        _update_mid_price_cache(self.cache, symbol, bids, asks, timestamp)
        self.cache.update_orderbook(symbol, bids, asks, timestamp=timestamp, cts_ms=cts_ms)
        if self.quality_tracker:
            self.quality_tracker.update_orderbook(symbol, timestamp, now_ts=timestamp, gap=False)
        await self._invoke_persistence(symbol, exchange, state, timestamp, seq)
        await self._mark_warmup(symbol, ready=True, reasons=[], timestamp=timestamp, sync_state="synced")

    async def _publish_resync(self, symbol: str, timestamp: Optional[float]) -> None:
        now_us = now_recv_us()
        now = us_to_sec(now_us)
        last = self._last_resync_at.get(symbol, 0.0)
        if now - last < self.config.resync_min_interval_sec:
            return
        self._last_resync_at[symbol] = now
        event = Event(
            event_id=str(now),
            event_type="orderbook_resync",
            schema_version="v1",
            timestamp=str(timestamp or now),
            ts_recv_us=now_us,
            ts_canon_us=now_us,
            bot_id="system",
            symbol=symbol,
            exchange=None,
            payload={"symbol": symbol},
        )
        await self.redis.publish_event(self._resync_stream, event)
        if self.telemetry and self.telemetry_context:
            await self.telemetry.publish_guardrail(
                self.telemetry_context,
                {
                    "type": "order_resync",
                    "symbol": symbol,
                    "reason": "gap_detected",
                    "last_seq": int(now),
                },
            )

    async def _mark_warmup(self, symbol: str, ready: bool, reasons: list, timestamp: Optional[float], sync_state: str) -> None:
        """Publish orderbook sync state to a separate key (does NOT overwrite decision_worker's warmup key)."""
        if not self.telemetry_context:
            return
        tenant = getattr(self.telemetry_context, "tenant_id", None)
        bot = getattr(self.telemetry_context, "bot_id", None)
        if not (tenant and bot):
            return
        # Write to a separate key so we don't overwrite decision_worker's full warmup data
        key = f"quantgambit:{tenant}:{bot}:warmup_orderbook:{symbol}"
        snapshot = {
            "symbol": symbol,
            "ready": ready,
            "reasons": reasons,
            "orderbook_sync_state": sync_state,
            "timestamp": timestamp or time.time(),
        }
        try:
            await self.redis.redis.set(key, json.dumps(snapshot))
            await self.redis.redis.expire(key, 180)
            if ready:
                self._warmup_emitted[symbol] = True
        except Exception:
            return

    async def _bootstrap_from_delta(
        self, symbol: str, data: dict, timestamp: float, seq: int, last_seq: Optional[int], cts_ms: Optional[int] = None, exchange: Optional[str] = None
    ) -> bool:
        """Force state from a delta payload to clear gaps/out-of-sync conditions."""
        if not self.config.allow_delta_bootstrap:
            return False
        if not (data.get("bids") and data.get("asks")):
            return False
        seq_to_use = last_seq or seq
        # Extract cts_ms from data if not provided
        if cts_ms is None:
            cts_ms = data.get("cts_ms")
        # Track exchange for this symbol for persistence
        if exchange:
            self._symbol_exchange[symbol] = exchange
        state = OrderbookState(symbol=symbol)
        try:
            state.apply_snapshot(data.get("bids") or [], data.get("asks") or [], seq=seq_to_use)
            self._books[symbol] = state
            bids, asks = state.as_levels(self.config.depth)
            _update_mid_price_cache(self.cache, symbol, bids, asks, timestamp)
            self.cache.update_orderbook(symbol, bids, asks, timestamp=timestamp, cts_ms=cts_ms)
            if self.quality_tracker:
                # After successful bootstrap, update as healthy and reset counters
                self.quality_tracker.update_orderbook(symbol, timestamp, now_ts=timestamp, gap=False)
                # Reset error counters to clear stale gap/out_of_order flags
                if hasattr(self.quality_tracker, 'reset_counters'):
                    self.quality_tracker.reset_counters(symbol, now_ts=timestamp)
            # Invoke persistence layer (Requirements 6.1, 4.1)
            await self._invoke_persistence(symbol, exchange, state, timestamp, seq_to_use)
            await self._publish_market_tick(symbol, exchange, timestamp, bids, asks)
            await self._mark_warmup(symbol, ready=True, reasons=[], timestamp=timestamp, sync_state="bootstrap_from_delta")
            log_info("orderbook_bootstrap_success", symbol=symbol, seq=seq_to_use)
            return True
        except Exception:
            return False

    async def _publish_market_tick(
        self,
        symbol: str,
        exchange: Optional[str],
        timestamp: float,
        bids: list,
        asks: list,
    ) -> None:
        if not self.config.emit_market_ticks:
            return
        if not bids or not asks:
            return
        try:
            best_bid = float(bids[0][0])
            best_ask = float(asks[0][0])
        except (TypeError, ValueError, IndexError):
            return
        ts_us = int((timestamp or time.time()) * 1_000_000)
        tick = {
            "symbol": symbol,
            "timestamp": timestamp,
            "ts_recv_us": ts_us,
            "ts_canon_us": ts_us,
            "ts_exchange_s": timestamp,
            "bid": best_bid,
            "ask": best_ask,
            "last": None,
            "source": "orderbook_feed",
        }
        try:
            validate_market_tick(tick)
        except Exception as exc:
            log_warning("orderbook_worker_market_tick_invalid", symbol=symbol, error=str(exc))
            return
        event = Event(
            event_id=str(uuid.uuid4()),
            event_type="market_tick",
            schema_version="v1",
            timestamp=str(timestamp),
            ts_recv_us=ts_us,
            ts_canon_us=ts_us,
            ts_exchange_s=timestamp,
            bot_id=getattr(self.telemetry_context, "bot_id", "system") if self.telemetry_context else "system",
            symbol=symbol,
            exchange=exchange,
            payload=tick,
        )
        await self.redis.publish_event(self.config.market_data_stream, event)


def _update_mid_price_cache(
    cache: ReferencePriceCache,
    symbol: str,
    bids: list,
    asks: list,
    timestamp: Optional[float],
) -> None:
    if not bids or not asks:
        return
    try:
        best_bid = float(bids[0][0])
        best_ask = float(asks[0][0])
    except (TypeError, ValueError, IndexError):
        return
    price = (best_bid + best_ask) / 2.0
    cache.update(symbol, price, timestamp=timestamp)
