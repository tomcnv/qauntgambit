"""Trade consumer updating trade stats cache."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional, TYPE_CHECKING
import time

from quantgambit.ingest.schemas import validate_trade
from quantgambit.market.trades import TradeStatsCache
from quantgambit.market.quality import MarketDataQualityTracker
from quantgambit.observability.logger import log_warning, log_info
from quantgambit.storage.redis_streams import RedisStreamsClient, decode_and_validate_event
from quantgambit.ingest.time_utils import us_to_sec

if TYPE_CHECKING:
    from quantgambit.market.reference_prices import ReferencePriceCache
    from quantgambit.storage.trade_record_writer import TradeRecordWriter
    from quantgambit.storage.live_data_validator import LiveDataValidator


@dataclass
class TradeWorkerConfig:
    source_stream: str = "events:trades"
    consumer_group: str = "quantgambit_trades"
    consumer_name: str = "trade_worker"
    block_ms: int = 1000


class TradeWorker:
    """Consume trade events and update stats cache."""

    def __init__(
        self,
        redis_client: RedisStreamsClient,
        cache: TradeStatsCache,
        quality_tracker: Optional[MarketDataQualityTracker] = None,
        config: Optional[TradeWorkerConfig] = None,
        reference_cache: Optional["ReferencePriceCache"] = None,
        trade_writer: Optional["TradeRecordWriter"] = None,
        live_validator: Optional["LiveDataValidator"] = None,
    ):
        self.redis = redis_client
        self.cache = cache
        self.quality_tracker = quality_tracker
        self.config = config or TradeWorkerConfig()
        self.reference_cache = reference_cache  # For latency measurement
        self.trade_writer = trade_writer
        self.live_validator = live_validator

    async def run(self) -> None:
        log_info("trade_worker_start", source=self.config.source_stream)
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

    async def _handle_message(self, payload: dict) -> None:
        try:
            event = decode_and_validate_event(payload)
        except Exception as exc:
            log_warning("trade_worker_invalid_event", error=str(exc))
            return
        event_type = event.get("event_type")
        if event_type != "trade":
            # Count skipped messages for debugging
            if not hasattr(self, "_skip_count"):
                self._skip_count = 0
            self._skip_count += 1
            if self._skip_count % 100 == 0:
                log_info("trade_worker_skip_count", skip_count=self._skip_count, skipped_type=event_type)
            return
        trade = event.get("payload") or {}
        try:
            validate_trade(trade)
        except Exception as exc:
            log_warning("trade_worker_invalid_trade", error=str(exc))
            return
        symbol = trade.get("symbol")
        raw = trade.get("raw") or {}
        now = time.time()
        recv_us = trade.get("ts_recv_us")
        try:
            recv_us = int(recv_us) if recv_us is not None else None
        except (TypeError, ValueError):
            recv_us = None
        if recv_us is None:
            recv_us = int(now * 1_000_000)
        ts_canon_us = trade.get("ts_canon_us")
        try:
            ts_canon_us = int(ts_canon_us) if ts_canon_us is not None else None
        except (TypeError, ValueError):
            ts_canon_us = None
        if ts_canon_us is None:
            ts_canon_us = recv_us
        recv_ts = us_to_sec(ts_canon_us)
        exchange_ts = trade.get("ts_exchange_s") or raw.get("timestamp")
        try:
            exchange_ts = float(exchange_ts) if exchange_ts is not None else None
        except (TypeError, ValueError):
            exchange_ts = None
        # If timestamp looks like ms, coerce to seconds.
        if exchange_ts and exchange_ts > 1e12:
            exchange_ts = exchange_ts / 1000.0
        # Canonical timestamp for windows: receive time (microseconds)
        cache_ts_us = ts_canon_us
        self.cache.update_trade(
            symbol=symbol,
            timestamp_us=cache_ts_us,
            price=float(trade.get("price")),
            size=float(trade.get("size")),
            side=str(trade.get("side") or "")
        )
        # Update reference cache with raw ms timestamp for latency measurement
        if self.reference_cache:
            trade_ts_ms = trade.get("trade_ts_ms") or raw.get("trade_ts_ms")
            if trade_ts_ms is not None:
                try:
                    trade_ts_ms = int(trade_ts_ms)
                except (TypeError, ValueError):
                    trade_ts_ms = None
            if trade_ts_ms is not None:
                now_ms = int(now * 1000)
                max_age_ms = int((self.cache.window_sec if self.cache else 60.0) * 1000)
                if abs(now_ms - trade_ts_ms) > max_age_ms:
                    trade_ts_ms = now_ms
                    if not hasattr(self, "_ts_ms_override_count"):
                        self._ts_ms_override_count = 0
                    self._ts_ms_override_count += 1
                    if self._ts_ms_override_count % 50 == 0:
                        log_info(
                            "trade_timestamp_ms_overridden",
                            symbol=symbol,
                            trade_ts_ms=trade_ts_ms,
                            now_ms=now_ms,
                            max_age_ms=max_age_ms,
                        )
                self.reference_cache.update_trade_timestamp(symbol, trade_ts_ms)
        # Debug: log cache state periodically
        if hasattr(self, "_trade_count"):
            self._trade_count += 1
        else:
            self._trade_count = 1
        if self._trade_count % 50 == 0:  # Log every 50 trades
            snap = self.cache.snapshot(symbol, now_ts_us=cache_ts_us)
            trade_ts = float(trade.get("timestamp") or recv_ts)
            current_ts = us_to_sec(cache_ts_us)
            age = current_ts - trade_ts
            log_info("trade_cache_debug", 
                symbol=symbol,
                trade_count=self._trade_count,
                poc=snap.get("point_of_control"),
                vwap=snap.get("vwap"),
                tps=snap.get("trades_per_second"),
                trade_ts=trade_ts,
                current_ts=current_ts,
                trade_age_sec=round(age, 1),
            )
        if self.quality_tracker:
            self.quality_tracker.update_trade(
                symbol=trade.get("symbol"),
                timestamp=recv_ts,
            )
        
        # Get exchange from event or trade payload
        exchange = trade.get("exchange") or event.get("exchange") or "unknown"
        trade_timestamp = exchange_ts if exchange_ts is not None else cache_ts
        
        # Invoke trade record writer if configured (Requirement 6.2)
        if self.trade_writer:
            try:
                from quantgambit.storage.persistence import PersistenceTradeRecord
                
                record = PersistenceTradeRecord(
                    symbol=symbol,
                    exchange=exchange,
                    timestamp=datetime.fromtimestamp(trade_timestamp, tz=timezone.utc),
                    price=float(trade.get("price")),
                    size=float(trade.get("size")),
                    side=str(trade.get("side") or "unknown"),
                    trade_id=str(trade.get("trade_id") or trade.get("id") or ""),
                )
                await self.trade_writer.record(record)
            except Exception as exc:
                log_warning("trade_record_write_error", symbol=symbol, error=str(exc))
        
        # Invoke live data validator if configured (Requirement 4.2)
        if self.live_validator:
            try:
                self.live_validator.record_trade(
                    symbol=symbol,
                    exchange=exchange,
                    timestamp=trade_timestamp,
                )
            except Exception as exc:
                log_warning("trade_validation_error", symbol=symbol, error=str(exc))
