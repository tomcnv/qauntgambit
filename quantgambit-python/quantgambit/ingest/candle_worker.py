"""Candle aggregation worker."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
import json
from typing import Optional

from quantgambit.ingest.candle_builder import CandleBuilder
from quantgambit.ingest.candles import Candle
from quantgambit.ingest.schemas import coerce_float, validate_market_tick
from quantgambit.observability.logger import log_warning, log_info
from quantgambit.storage.redis_streams import Event, RedisStreamsClient, decode_and_validate_event
from quantgambit.storage.timescale import TimescaleWriter, CandleRow
from quantgambit.ingest.time_utils import now_recv_us, sec_to_us, us_to_sec


@dataclass
class CandleWorkerConfig:
    source_stream: str = "events:market_data"
    output_stream: str = "events:candles"
    consumer_group: str = "quantgambit_candles"
    consumer_name: str = "candle_worker"
    block_ms: int = 1000
    timeframes_sec: tuple[int, ...] = (60, 300, 900)


class CandleWorker:
    """Consumes market ticks and emits OHLCV candles."""

    def __init__(
        self,
        redis_client: RedisStreamsClient,
        timescale: TimescaleWriter,
        tenant_id: str,
        bot_id: str,
        exchange: str,
        config: Optional[CandleWorkerConfig] = None,
        monotonic_clock=None,
    ):
        self.redis = redis_client
        self.timescale = timescale
        self.tenant_id = tenant_id
        self.bot_id = bot_id
        self.exchange = exchange
        self.config = config or CandleWorkerConfig()
        self._builder = CandleBuilder(timeframes_sec=self.config.timeframes_sec)
        self._counts: dict[tuple[str, int], int] = {}
        self._late_tick_counts_seen: dict[tuple[str, int], int] = {}
        self._counts_key = f"quantgambit:{tenant_id}:{bot_id}:candle_counts"
        self._late_tick_summary_key = f"quantgambit:{tenant_id}:{bot_id}:candle:late_ticks"
        self._monotonic_clock = monotonic_clock

    async def _load_counts(self) -> None:
        """Load persisted candle counts from Redis."""
        try:
            data = await self.redis.redis.hgetall(self._counts_key)
            for key, value in data.items():
                if isinstance(key, bytes):
                    key = key.decode()
                if isinstance(value, bytes):
                    value = value.decode()
                parts = key.split(":")
                if len(parts) == 2:
                    symbol, tf = parts[0], int(parts[1])
                    self._counts[(symbol, tf)] = int(value)
            if self._counts:
                log_info("candle_counts_loaded", count=len(self._counts))
        except Exception as e:
            log_warning("candle_counts_load_failed", error=str(e))

    async def _save_count(self, symbol: str, timeframe: int, count: int) -> None:
        """Persist candle count to Redis."""
        try:
            await self.redis.redis.hset(self._counts_key, f"{symbol}:{timeframe}", str(count))
        except Exception:
            pass  # Best-effort, don't block on persistence failures

    async def run(self) -> None:
        log_info("candle_worker_start", source=self.config.source_stream, output=self.config.output_stream)
        await self._load_counts()  # Restore counts from previous session
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
            log_warning("candle_worker_invalid_event", error=str(exc))
            return
        if event.get("event_type") != "market_tick":
            return
        tick = event.get("payload") or {}
        try:
            validate_market_tick(tick)
        except Exception as exc:
            log_warning("candle_worker_invalid_tick", error=str(exc))
            return
        symbol = tick.get("symbol")
        tick_ts_us = tick.get("ts_canon_us")
        if tick_ts_us is None:
            ts = coerce_float(tick.get("timestamp")) or us_to_sec(now_recv_us())
            tick_ts_us = int(ts * 1_000_000)
        else:
            ts = us_to_sec(int(tick_ts_us))
        price_source, price = _price_from_tick(tick)
        if price is None:
            return
        volume = coerce_float(tick.get("volume")) or coerce_float(tick.get("size")) or 0.0
        results = self._builder.process_tick(
            symbol=symbol,
            ts_canon_us=int(tick_ts_us),
            price=price,
            volume=volume,
            price_source=price_source,
            now_us=int(tick_ts_us),
        )
        for timeframe in self.config.timeframes_sec:
            key = (symbol, timeframe)
            late_count = self._builder.get_late_tick_count(symbol, timeframe)
            last_seen = self._late_tick_counts_seen.get(key, 0)
            if late_count > last_seen:
                log_warning(
                    "candle_late_tick_dropped",
                    symbol=symbol,
                    timeframe=timeframe,
                    count=late_count,
                )
                self._late_tick_counts_seen[key] = late_count
        if self._late_tick_counts_seen:
            await self._write_late_tick_summary()
        for result in results:
            await self._publish_candle(result.candle, result.stats)

    async def _publish_candle(self, candle: Candle, source_stats: Optional[dict] = None) -> None:
        emit_us = now_recv_us()
        ts_canon_us = (
            self._monotonic_clock.update(candle.symbol, emit_us) if self._monotonic_clock else emit_us
        )
        key = (candle.symbol, candle.timeframe_sec)
        self._counts[key] = self._counts.get(key, 0) + 1
        candle_count = self._counts[key]
        # Persist count to Redis so it survives restarts
        await self._save_count(candle.symbol, candle.timeframe_sec, candle_count)
        stats = source_stats or {}
        counts = stats.get("counts") or {}
        bucket_start_us = stats.get("start_us")
        if bucket_start_us is None:
            bucket_start_us = sec_to_us(candle.start_ts)
        bucket_end_us = bucket_start_us + int(candle.timeframe_sec * 1_000_000)
        price_source = _summarize_price_source(counts)
        is_derived = price_source != "last"
        payload = {
            "symbol": candle.symbol,
            "timestamp": candle.start_ts,
            "ts_recv_us": emit_us,
            "ts_canon_us": ts_canon_us,
            "ts_exchange_s": None,
            "bucket_start_us": bucket_start_us,
            "bucket_end_us": bucket_end_us,
            "min_tick_ts_us": stats.get("min_tick_ts_us"),
            "max_tick_ts_us": stats.get("max_tick_ts_us"),
            "timeframe_sec": candle.timeframe_sec,
            "open": candle.open,
            "high": candle.high,
            "low": candle.low,
            "close": candle.close,
            "volume": candle.volume,
            "candle_count": candle_count,
            "price_source": price_source,
            "is_derived": is_derived,
            "price_source_breakdown": counts,
        }
        event = Event(
            event_id=str(uuid.uuid4()),
            event_type="candle",
            schema_version="v1",
            timestamp=str(candle.start_ts),
            ts_recv_us=emit_us,
            ts_canon_us=ts_canon_us,
            ts_exchange_s=None,
            bot_id=self.bot_id,
            symbol=candle.symbol,
            exchange=self.exchange,
            payload=payload,
        )
        await self.redis.publish_event(self.config.output_stream, event)
        await self.timescale.write_candle(
            CandleRow(
                tenant_id=self.tenant_id,
                bot_id=self.bot_id,
                symbol=candle.symbol,
                exchange=self.exchange,
                timeframe_sec=candle.timeframe_sec,
                timestamp=str(candle.start_ts),
                open=candle.open,
                high=candle.high,
                low=candle.low,
                close=candle.close,
                volume=candle.volume,
            )
        )
        return None

    async def _write_late_tick_summary(self) -> None:
        summary = self._builder.late_tick_summary()
        if not summary:
            return
        payload = {
            "timestamp": us_to_sec(now_recv_us()),
            "summary": summary,
        }
        try:
            await self.redis.redis.set(self._late_tick_summary_key, json.dumps(payload))
        except Exception:
            return


def _price_from_tick(tick: dict) -> tuple[Optional[str], Optional[float]]:
    last = coerce_float(tick.get("last"))
    if last is not None:
        return "last", last
    bid = coerce_float(tick.get("bid"))
    ask = coerce_float(tick.get("ask"))
    if bid is not None and ask is not None:
        return "mid", (bid + ask) / 2.0
    if bid is not None:
        return "bid", bid
    if ask is not None:
        return "ask", ask
    return None, None


def _summarize_price_source(counts: dict) -> str:
    last = counts.get("last", 0)
    mid = counts.get("mid", 0)
    bid = counts.get("bid", 0)
    ask = counts.get("ask", 0)
    total = last + mid + bid + ask
    if total == 0:
        return "unknown"
    if last == total:
        return "last"
    if mid == total:
        return "mid"
    if bid == total:
        return "bid"
    if ask == total:
        return "ask"
    return "derived"
