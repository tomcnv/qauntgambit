"""Market data ingestion worker."""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass
from typing import Optional

from quantgambit.ingest.schemas import validate_market_tick
from quantgambit.ingest.time_utils import resolve_exchange_timestamp, now_recv_us, us_to_sec
from quantgambit.ingest.monotonic_clock import MonotonicClock
from quantgambit.market.reference_prices import ReferencePriceCache
from quantgambit.market.source_policy import (
    SourceFusionPolicy,
    classify_tick_source,
    SOURCE_ORDERBOOK,
    SOURCE_TICKER,
    SOURCE_TRADE,
)
from quantgambit.market.quality import MarketDataQualityTracker
from quantgambit.market.ticks import normalize_tick
from quantgambit.market.updater import _is_stale_tick, _reference_price
from quantgambit.execution.symbols import normalize_exchange_symbol
from quantgambit.observability.logger import log_warning, log_info
from quantgambit.observability.telemetry import TelemetryContext, TelemetryPipeline
from quantgambit.storage.redis_streams import Event, RedisStreamsClient


@dataclass
class MarketDataWorkerConfig:
    stream: str = "events:market_data"
    stale_threshold_sec: float = 5.0
    idle_backoff_sec: float = 0.05
    heartbeat_interval_sec: float = 5.0
    orderbook_depth_min: int = 1
    timestamp_source: str = "exchange"  # exchange|local
    # Increase tolerance to 30s to handle Binance timestamp drift without constant skew warnings
    max_clock_skew_sec: float = 30.0
    prefer_trade_ticks: bool = True
    source_priority: Optional[tuple[str, ...]] = None
    source_stale_sec: float = 5.0


class MarketDataWorker:
    """Consume market ticks, update reference prices, and publish tick events."""

    def __init__(
        self,
        provider,
        cache: ReferencePriceCache,
        redis_client: RedisStreamsClient,
        bot_id: str,
        exchange: str,
        market_type: str = "perp",
        telemetry: Optional[TelemetryPipeline] = None,
        telemetry_context: Optional[TelemetryContext] = None,
        quality_tracker: Optional[MarketDataQualityTracker] = None,
        config: Optional[MarketDataWorkerConfig] = None,
        monotonic_clock: Optional[MonotonicClock] = None,
    ):
        self.provider = provider
        self.cache = cache
        self.redis = redis_client
        self.bot_id = bot_id
        self.exchange = exchange
        self.market_type = market_type
        self.telemetry = telemetry
        self.telemetry_context = telemetry_context
        self.quality_tracker = quality_tracker
        self.config = config or MarketDataWorkerConfig()
        self._last_tick_at: float = time.time()
        self._last_heartbeat_at: float = 0.0
        self._last_tick_ts: dict[str, float] = {}
        self.health_worker = None
        self._monotonic_clock = monotonic_clock
        self._source_last_us: dict[str, dict[str, int]] = {}
        self._source_policy = self._build_source_policy()

    async def run(self) -> None:
        log_info("market_data_worker_start", exchange=self.exchange, stream=self.config.stream)
        while True:
            raw_tick = await self.provider.next_tick()
            if not raw_tick:
                await self._heartbeat()
                await asyncio.sleep(self.config.idle_backoff_sec)
                continue
            tick = normalize_tick(raw_tick)
            if not tick:
                log_warning("market_tick_invalid", raw=str(raw_tick)[:200])
                continue
            
            # Filter by market_type - skip events from wrong market
            tick_market_type = tick.get("market_type", "perp")
            if tick_market_type != self.market_type:
                continue
            
            tick["symbol"] = normalize_exchange_symbol(self.exchange, tick.get("symbol"))
            recv_us = now_recv_us()
            recv_ts = us_to_sec(recv_us)
            raw_ts = tick.get("timestamp")
            if self.config.timestamp_source == "local":
                exchange_ts = None
                skewed = False
                skew_sec = None
            else:
                exchange_ts, skewed, skew_sec = resolve_exchange_timestamp(
                    raw_ts,
                    recv_ts,
                    self.config.max_clock_skew_sec,
                )
            symbol = tick.get("symbol")
            ts_canon_us = self._monotonic_clock.update(symbol, recv_us) if self._monotonic_clock else recv_us
            # Canonical timestamp for all windows/staleness: receive time (microseconds)
            tick["ts_recv_us"] = recv_us
            tick["ts_canon_us"] = ts_canon_us
            tick["ts_exchange_s"] = exchange_ts
            tick["timestamp"] = us_to_sec(ts_canon_us)
            if skewed:
                log_warning("market_tick_timestamp_skew", symbol=tick.get("symbol"), raw_ts=raw_ts)
                if self.telemetry and self.telemetry_context:
                    await self.telemetry.publish_latency(
                        ctx=self.telemetry_context,
                        payload={
                            "market_data_clock_skew": True,
                            "symbol": tick.get("symbol"),
                            "skew_sec": round(skew_sec or 0.0, 6),
                        },
                    )
            sequence_ts = exchange_ts if exchange_ts is not None else us_to_sec(ts_canon_us)
            is_gap, is_out_of_order = self._check_tick_sequence(tick.get("symbol"), sequence_ts)
            if _is_stale_tick(tick.get("timestamp"), self.config.stale_threshold_sec):
                log_warning("market_tick_stale", symbol=tick.get("symbol"))
                self._record_qa(
                    now=recv_ts,
                    is_stale=True,
                    is_skew=skewed,
                    is_gap=is_gap,
                    is_out_of_order=is_out_of_order,
                )
                if self.telemetry and self.telemetry_context:
                    await self.telemetry.publish_latency(
                        ctx=self.telemetry_context,
                        payload={"market_data_stale": True, "symbol": tick.get("symbol")},
                    )
                if self.quality_tracker:
                    self.quality_tracker.update_tick(
                        symbol=tick.get("symbol"),
                        timestamp=tick.get("timestamp"),
                        now_ts=tick.get("timestamp"),
                        is_stale=True,
                        is_gap=is_gap,
                        is_skew=skewed,
                        is_out_of_order=is_out_of_order,
                        source=tick.get("source"),
                    )
                continue
            self._record_qa(
                now=recv_ts,
                is_stale=False,
                is_skew=skewed,
                is_gap=is_gap,
                is_out_of_order=is_out_of_order,
            )
            if self.quality_tracker:
                self.quality_tracker.update_tick(
                    symbol=tick.get("symbol"),
                    timestamp=tick.get("timestamp"),
                    now_ts=tick.get("timestamp"),
                    is_stale=False,
                    is_gap=is_gap,
                    is_skew=skewed,
                    is_out_of_order=is_out_of_order,
                    source=tick.get("source"),
                )
            price = _reference_price(tick.get("bid"), tick.get("ask"), tick.get("last"))
            if price is not None:
                source_kind = classify_tick_source(tick)
                self._update_source_seen(symbol, source_kind, ts_canon_us)
                if self._should_update_reference_price(symbol, source_kind, ts_canon_us):
                    self.cache.update(tick["symbol"], price, timestamp=tick.get("timestamp"))
            if tick.get("bids") and tick.get("asks"):
                if (
                    len(tick["bids"]) >= self.config.orderbook_depth_min
                    and len(tick["asks"]) >= self.config.orderbook_depth_min
                ):
                    self.cache.update_orderbook(tick["symbol"], tick["bids"], tick["asks"], timestamp=tick.get("timestamp"))
            self._last_tick_at = recv_ts
            await self._publish_tick(tick)
            await self._publish_market_context(tick)
            await self._heartbeat()

    async def _publish_tick(self, tick: dict) -> None:
        payload = {
            "symbol": tick.get("symbol"),
            "timestamp": tick.get("timestamp"),
            "ts_recv_us": tick.get("ts_recv_us"),
            "ts_canon_us": tick.get("ts_canon_us"),
            "ts_exchange_s": tick.get("ts_exchange_s"),
            "bid": tick.get("bid"),
            "ask": tick.get("ask"),
            "last": tick.get("last"),
            "source": tick.get("source"),
        }
        try:
            validate_market_tick(payload)
        except Exception as exc:
            log_warning("market_tick_invalid_schema", error=str(exc))
            return
        event = Event(
            event_id=str(uuid.uuid4()),
            event_type="market_tick",
            schema_version="v1",
            timestamp=str(payload["timestamp"]),
            ts_recv_us=payload.get("ts_recv_us"),
            ts_canon_us=payload.get("ts_canon_us"),
            ts_exchange_s=payload.get("ts_exchange_s"),
            bot_id=self.bot_id,
            symbol=payload.get("symbol"),
            exchange=self.exchange,
            payload=payload,
        )
        await self.redis.publish_event(self.config.stream, event)

    async def _publish_market_context(self, tick: dict) -> None:
        if not (self.telemetry and self.telemetry_context):
            return
        bid = tick.get("bid")
        ask = tick.get("ask")
        bids = tick.get("bids") or []
        asks = tick.get("asks") or []
        spread_bps = None
        depth_usd = None
        if bid is not None and ask is not None and ask > 0:
            mid = (bid + ask) / 2.0
            spread_bps = ((ask - bid) / mid) * 10000 if mid else None
        if bids and asks:
            top_bid = bids[0]
            top_ask = asks[0]
            try:
                depth_usd = (float(top_bid[0]) * float(top_bid[1])) + (float(top_ask[0]) * float(top_ask[1]))
            except Exception:
                depth_usd = None
        payload = {
            "symbol": tick.get("symbol"),
            "spread_bps": spread_bps,
            "depth_usd": depth_usd,
            "funding_rate": tick.get("funding_rate"),
            "iv": tick.get("iv"),
            "vol": tick.get("vol"),
            "timestamp": tick.get("timestamp"),
        }
        try:
            await self.telemetry.publish_market_context(self.telemetry_context, payload)
        except Exception:
            pass

    async def _heartbeat(self) -> None:
        now = time.time()
        if now - self._last_heartbeat_at < self.config.heartbeat_interval_sec:
            return
        self._last_heartbeat_at = now
        if not (self.telemetry and self.telemetry_context):
            return
        await self.telemetry.publish_latency(
            ctx=self.telemetry_context,
            payload={
                "market_data_heartbeat": True,
                "last_tick_age_sec": round(now - self._last_tick_at, 3),
            },
        )

    def _build_source_policy(self) -> SourceFusionPolicy:
        if self.config.source_priority:
            priority = tuple(self.config.source_priority)
        else:
            if self.config.prefer_trade_ticks:
                priority = (SOURCE_TRADE, SOURCE_ORDERBOOK, SOURCE_TICKER)
            else:
                priority = (SOURCE_ORDERBOOK, SOURCE_TRADE, SOURCE_TICKER)
        stale_us = int(round(self.config.source_stale_sec * 1_000_000))
        return SourceFusionPolicy(priority=priority, stale_us=stale_us)

    def _update_source_seen(self, symbol: Optional[str], source_kind: str, ts_canon_us: int) -> None:
        if not symbol:
            return
        if source_kind not in (SOURCE_TRADE, SOURCE_ORDERBOOK, SOURCE_TICKER):
            return
        last_seen = self._source_last_us.setdefault(symbol, {})
        last_seen[source_kind] = int(ts_canon_us)

    def _should_update_reference_price(self, symbol: Optional[str], source_kind: str, ts_canon_us: int) -> bool:
        if not symbol:
            return False
        if source_kind not in (SOURCE_TRADE, SOURCE_ORDERBOOK, SOURCE_TICKER):
            return False
        last_seen = self._source_last_us.get(symbol, {})
        has_reference = self.cache.get_reference_price_with_ts(symbol) is not None
        return self._source_policy.should_update(source_kind, last_seen, int(ts_canon_us), has_reference)

    def _record_qa(self, now: float, is_stale: bool, is_skew: bool, is_gap: bool, is_out_of_order: bool) -> None:
        if not self.health_worker:
            return
        age = now - self._last_tick_at
        self.health_worker.record_market_tick(
            age_sec=age,
            is_stale=is_stale,
            is_skew=is_skew,
            is_gap=is_gap,
            is_out_of_order=is_out_of_order,
        )

    def _check_tick_sequence(self, symbol: Optional[str], ts: Optional[float]) -> tuple[bool, bool]:
        if not symbol or ts is None:
            return False, False
        try:
            ts_val = float(ts)
        except (TypeError, ValueError):
            return False, False
        prev = self._last_tick_ts.get(symbol)
        self._last_tick_ts[symbol] = ts_val
        if prev is None:
            return False, False
        if ts_val < prev:
            return False, True
        if ts_val > prev + max(self.config.stale_threshold_sec, 0.0):
            return True, False
        return False, False


def _resolve_tick_timestamp(
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
