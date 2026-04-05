"""Trade feed worker publishing trades to Redis."""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass
from typing import Optional, Protocol

from quantgambit.ingest.schemas import validate_trade, validate_market_tick
from quantgambit.ingest.time_utils import resolve_exchange_timestamp, now_recv_us, us_to_sec
from quantgambit.ingest.monotonic_clock import MonotonicClock
from quantgambit.execution.symbols import normalize_exchange_symbol
from quantgambit.observability.logger import log_warning, log_info
from quantgambit.storage.redis_streams import Event, RedisStreamsClient


class TradeFeedProvider(Protocol):
    async def next_trade(self) -> Optional[dict]:
        """Return next trade payload."""


@dataclass
class TradeFeedConfig:
    stream: str = "events:trades"
    idle_backoff_sec: float = 0.05
    emit_market_ticks: bool = False
    market_data_stream: str = "events:market_data"
    timestamp_source: str = "exchange"  # exchange|local
    # Increase tolerance to 30s to handle Binance timestamp drift without constant skew warnings
    max_clock_skew_sec: float = 30.0


class TradeFeedWorker:
    """Publish trades from a provider to Redis streams."""

    def __init__(
        self,
        provider: TradeFeedProvider,
        redis_client: RedisStreamsClient,
        bot_id: str,
        exchange: str,
        config: Optional[TradeFeedConfig] = None,
        monotonic_clock: Optional[MonotonicClock] = None,
    ):
        self.provider = provider
        self.redis = redis_client
        self.bot_id = bot_id
        self.exchange = exchange
        self.config = config or TradeFeedConfig()
        self._monotonic_clock = monotonic_clock

    async def run(self) -> None:
        log_info("trade_feed_start", stream=self.config.stream, exchange=self.exchange)
        while True:
            trade = await self.provider.next_trade()
            if not trade:
                await asyncio.sleep(self.config.idle_backoff_sec)
                continue
            trade["symbol"] = normalize_exchange_symbol(self.exchange, trade.get("symbol"))
            recv_us = now_recv_us()
            recv_ts = us_to_sec(recv_us)
            raw_ts = trade.get("timestamp")
            exchange_ts, skewed, skew_sec = resolve_exchange_timestamp(
                raw_ts,
                recv_ts,
                self.config.max_clock_skew_sec,
            )
            symbol = trade.get("symbol")
            ts_canon_us = self._monotonic_clock.update(symbol, recv_us) if self._monotonic_clock else recv_us
            # Canonical timestamp for all windows/staleness: receive time (microseconds)
            trade["ts_recv_us"] = recv_us
            trade["ts_canon_us"] = ts_canon_us
            trade["ts_exchange_s"] = exchange_ts
            trade["timestamp"] = us_to_sec(ts_canon_us)
            if skewed:
                log_warning(
                    "trade_timestamp_skew",
                    symbol=trade.get("symbol"),
                    raw_ts=raw_ts,
                    skew_sec=round(skew_sec or 0.0, 6),
                )
            try:
                validate_trade(trade)
            except Exception as exc:
                log_warning("trade_invalid", error=str(exc))
                continue
            event = Event(
                event_id=str(uuid.uuid4()),
                event_type="trade",
                schema_version="v1",
                timestamp=str(trade.get("timestamp") or time.time()),
                ts_recv_us=trade.get("ts_recv_us"),
                ts_canon_us=trade.get("ts_canon_us"),
                ts_exchange_s=trade.get("ts_exchange_s"),
                bot_id=self.bot_id,
                symbol=trade.get("symbol"),
                exchange=self.exchange,
                payload=trade,
            )
            await self.redis.publish_event(self.config.stream, event)
            await self._publish_market_tick(trade)

    async def _publish_market_tick(self, trade: dict) -> None:
        if not self.config.emit_market_ticks:
            return
        price = trade.get("price")
        if trade.get("ts_recv_us") is None:
            recv_us = now_recv_us()
            symbol = trade.get("symbol")
            trade["ts_recv_us"] = recv_us
            trade["ts_canon_us"] = (
                self._monotonic_clock.update(symbol, recv_us) if self._monotonic_clock else recv_us
            )
            trade["ts_exchange_s"] = trade.get("ts_exchange_s")
            trade["timestamp"] = us_to_sec(trade["ts_canon_us"])
        timestamp = trade.get("timestamp") or time.time()
        tick = {
            "symbol": trade.get("symbol"),
            "timestamp": timestamp,
            "ts_recv_us": trade.get("ts_recv_us"),
            "ts_canon_us": trade.get("ts_canon_us"),
            "ts_exchange_s": trade.get("ts_exchange_s"),
            "last": price,
            "volume": trade.get("size"),
            "source": "trade_feed",
        }
        try:
            validate_market_tick(tick)
        except Exception as exc:
            log_warning("trade_market_tick_invalid", error=str(exc))
            return
        event = Event(
            event_id=str(uuid.uuid4()),
            event_type="market_tick",
            schema_version="v1",
            timestamp=str(timestamp),
            ts_recv_us=tick.get("ts_recv_us"),
            ts_canon_us=tick.get("ts_canon_us"),
            ts_exchange_s=tick.get("ts_exchange_s"),
            bot_id=self.bot_id,
            symbol=tick.get("symbol"),
            exchange=self.exchange,
            payload=tick,
        )
        await self.redis.publish_event(self.config.market_data_stream, event)


def _resolve_trade_timestamp(
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
