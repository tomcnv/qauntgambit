"""Standalone data persistence worker for continuous TimescaleDB storage.

This worker consumes orderbook and trade data from Redis streams and persists
them to TimescaleDB continuously, independent of the trading runtime.

This enables:
- Continuous data collection for backtesting
- Strategy research with historical data
- Warm start capability
- Replay validation

Feature: live-orderbook-data-storage
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import signal
import sys
import time
import ssl
from datetime import datetime, timezone, timedelta
from typing import Optional, Any
from urllib.parse import urlparse

import asyncpg
import redis.asyncio as redis

from quantgambit.market.orderbooks import OrderbookState
from quantgambit.storage.orderbook_snapshot_writer import OrderbookSnapshotWriter
from quantgambit.storage.trade_record_writer import TradeRecordWriter
from quantgambit.storage.persistence import (
    OrderbookSnapshotWriterConfig,
    TradeRecordWriterConfig,
    PersistenceTradeRecord,
)
from quantgambit.storage.persistence_config import (
    load_orderbook_snapshot_config,
    load_trade_record_config,
)
from quantgambit.observability.telemetry import _normalize_order_payload

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("data_persistence_worker")


def _is_close_order_event(payload: dict[str, Any]) -> bool:
    position_effect = str(payload.get("position_effect") or "").strip().lower()
    if position_effect == "close":
        return True
    reason = str(payload.get("reason") or payload.get("exit_reason") or "").strip().lower()
    return reason.startswith("invalidation_exit") or reason in {
        "position_close",
        "exchange_reconcile",
        "strategic_exit",
        "stop_loss",
        "take_profit",
        "manual_flatten",
    }


def _build_order_event_semantic_key(payload: dict[str, Any], ts: datetime) -> str:
    event_id = str(payload.get("event_id") or "").strip()
    if event_id:
        return f"ev:{event_id}"
    decision_id = str(payload.get("decision_id") or "").strip()
    if decision_id:
        return f"dec:{decision_id}"
    order_id = str(payload.get("order_id") or "").strip()
    client_order_id = str(payload.get("client_order_id") or "").strip()
    if order_id or client_order_id:
        # Canonical close key: collapse reason churn for the same close order.
        if _is_close_order_event(payload):
            return "|".join(
                [
                    "ord_close",
                    order_id,
                    client_order_id,
                    str(payload.get("status") or "").strip(),
                    str(payload.get("filled_size") or "").strip(),
                    str(payload.get("fill_price") or "").strip(),
                    str(payload.get("fee_usd") or "").strip(),
                ]
            )
        return "|".join(
            [
                "ord",
                order_id,
                client_order_id,
                str(payload.get("status") or "").strip(),
                str(payload.get("event_type") or "").strip(),
                str(payload.get("reason") or "").strip(),
                str(payload.get("filled_size") or "").strip(),
                str(payload.get("remaining_size") or "").strip(),
                str(payload.get("fill_price") or "").strip(),
                str(payload.get("fee_usd") or "").strip(),
            ]
        )
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True, default=str)
    return "raw:" + hashlib.sha256(f"{raw}|{ts.isoformat()}".encode("utf-8")).hexdigest()[:24]


class DataPersistenceWorker:
    """Consumes market data from Redis and persists to TimescaleDB.
    
    This worker runs independently of the trading runtime, ensuring
    continuous data collection even when no bot is actively trading.
    """
    
    def __init__(
        self,
        redis_url: str,
        timescale_url: str,
        exchange: str = "bybit",
        orderbook_stream: Optional[str] = None,
        trade_stream: Optional[str] = None,
        order_stream: Optional[str] = None,
        consumer_group: str = "data_persistence",
        consumer_name: str = "worker_1",
        tenant_id: str = "default",
        bot_id: str = "default",
    ):
        self.redis_url = redis_url
        self.timescale_url = timescale_url
        self.exchange = exchange
        self.orderbook_stream = orderbook_stream or f"events:orderbook_feed:{exchange}"
        self.trade_stream = trade_stream or f"events:trades:{exchange}"
        self.order_stream = order_stream or "events:order"
        self.consumer_group = consumer_group
        self.consumer_name = consumer_name
        self.tenant_id = str(tenant_id or "default")
        self.bot_id = str(bot_id or "default")
        
        self._redis: Optional[redis.Redis] = None
        self._pool: Optional[asyncpg.Pool] = None
        self._snapshot_writer: Optional[OrderbookSnapshotWriter] = None
        self._trade_writer: Optional[TradeRecordWriter] = None
        self._running = False
        self._stop_event = asyncio.Event()
        self._retention_task: Optional[asyncio.Task] = None
        
        # Stats tracking
        self._orderbook_count = 0
        self._trade_count = 0
        self._order_event_count = 0
        self._last_orderbook_ts: dict[str, float] = {}
        self._last_trade_ts: dict[str, float] = {}
        self._last_order_ts: dict[str, float] = {}
        self._start_time = 0.0

        # Storage-control knobs. These are intentionally safe defaults.
        self._orderbook_events_enabled = os.getenv("PERSISTENCE_ORDERBOOK_EVENTS_ENABLED", "true").lower() in {"1", "true", "yes"}
        self._orderbook_events_interval_sec = float(os.getenv("PERSISTENCE_ORDERBOOK_EVENTS_INTERVAL_SEC", "1.0"))
        self._last_orderbook_event_write: dict[str, float] = {}

        self._retention_enabled = os.getenv("PERSISTENCE_RETENTION_ENABLED", "true").lower() in {"1", "true", "yes"}
        self._retention_sweep_sec = float(os.getenv("PERSISTENCE_RETENTION_SWEEP_SEC", "3600"))
        self._retention_telemetry_days = float(os.getenv("PERSISTENCE_RETENTION_TELEMETRY_DAYS", "14"))
        # Full orderbook snapshots/events are by far the biggest tables.
        self._retention_orderbook_days = float(os.getenv("PERSISTENCE_RETENTION_ORDERBOOK_DAYS", "2"))
        self._retention_order_updates_days = float(os.getenv("PERSISTENCE_RETENTION_ORDER_UPDATES_DAYS", "7"))
        self._retention_trades_days = float(os.getenv("PERSISTENCE_RETENTION_TRADES_DAYS", "90"))
        self._retention_candles_days = float(os.getenv("PERSISTENCE_RETENTION_CANDLES_DAYS", "30"))
    
    async def start(self) -> None:
        """Initialize connections and start processing."""
        logger.info(
            "Starting data persistence worker",
            extra={
                "exchange": self.exchange,
                "orderbook_stream": self.orderbook_stream,
                "trade_stream": self.trade_stream,
                "order_stream": self.order_stream,
            },
        )
        
        # Connect to Redis
        self._redis = redis.from_url(self.redis_url)
        await self._redis.ping()
        logger.info("Connected to Redis")
        
        # Connect to TimescaleDB / Postgres.
        #
        # - Local dev (docker timescale on localhost) typically does NOT support SSL.
        # - RDS requires SSL, but the container trust store may not include the full CA chain.
        #
        # So: only enable SSL when we expect it to be supported/required.
        #
        # - RDS Postgres typically requires SSL.
        # - Our EC2-hosted TimescaleDB does NOT (and may reject SSL upgrades).
        #
        # You can force SSL on/off via env if needed.
        ssl_param = None
        try:
            parsed = urlparse(self.timescale_url)
            host = (parsed.hostname or "").strip().lower()
            force_ssl = os.getenv("BOT_DB_SSL", "").strip().lower()
            ssl_forced_on = force_ssl in {"1", "true", "yes", "require", "on"}
            ssl_forced_off = force_ssl in {"0", "false", "no", "disable", "off"}
            looks_like_rds = host.endswith(".rds.amazonaws.com")

            if not ssl_forced_off and (ssl_forced_on or looks_like_rds):
                ssl_ctx = ssl.create_default_context()
                ssl_ctx.check_hostname = False
                ssl_ctx.verify_mode = ssl.CERT_NONE
                ssl_param = ssl_ctx
        except Exception:
            ssl_param = None
        # Timescale can come up slower than ECS (especially after EC2 replacements).
        # Retry a bit instead of crash-looping the service.
        last_exc: Exception | None = None
        for attempt in range(1, 61):  # ~5 minutes worst-case
            try:
                self._pool = await asyncpg.create_pool(
                    self.timescale_url,
                    min_size=2,
                    max_size=5,
                    ssl=ssl_param,
                    timeout=10,
                )
                break
            except Exception as exc:
                last_exc = exc
                logger.warning(
                    "TimescaleDB connect failed; retrying",
                    extra={
                        "attempt": attempt,
                        "error": repr(exc),
                    },
                )
                await asyncio.sleep(min(10.0, 0.5 * attempt))

        if not self._pool:
            raise RuntimeError(f"failed_to_connect_timescale: {last_exc!r}")
        logger.info("Connected to TimescaleDB")
        
        # Initialize writers
        orderbook_config = load_orderbook_snapshot_config()
        trade_config = load_trade_record_config()
        
        if orderbook_config.enabled:
            self._snapshot_writer = OrderbookSnapshotWriter(
                pool=self._pool,
                config=orderbook_config,
                tenant_id=self.tenant_id,
                bot_id=self.bot_id,
            )
            await self._snapshot_writer.start_background_flush()
            logger.info(
                "OrderbookSnapshotWriter initialized",
                extra={
                    "interval_sec": orderbook_config.snapshot_interval_sec,
                    "batch_size": orderbook_config.batch_size,
                },
            )
        
        if trade_config.enabled:
            self._trade_writer = TradeRecordWriter(
                pool=self._pool,
                config=trade_config,
            )
            await self._trade_writer.start_background_flush()
            logger.info(
                "TradeRecordWriter initialized",
                extra={
                    "batch_size": trade_config.batch_size,
                    "flush_interval_sec": trade_config.flush_interval_sec,
                },
            )
        
        # Create consumer groups (ignore if already exists)
        await self._ensure_consumer_group(self.orderbook_stream)
        await self._ensure_consumer_group(self.trade_stream)
        await self._ensure_consumer_group(self.order_stream)
        
        self._running = True
        self._start_time = time.time()
        
        # Start processing tasks
        tasks = []
        if self._snapshot_writer or self._orderbook_events_enabled:
            tasks.append(asyncio.create_task(self._process_orderbook_stream()))
        if self._trade_writer:
            tasks.append(asyncio.create_task(self._process_trade_stream()))
        tasks.append(asyncio.create_task(self._process_order_stream()))
        tasks.append(asyncio.create_task(self._log_stats_periodically()))
        if self._retention_enabled and self._retention_sweep_sec > 0:
            self._retention_task = asyncio.create_task(self._retention_loop())
            tasks.append(self._retention_task)
        
        logger.info("Data persistence worker started")
        
        # Wait for stop signal
        await self._stop_event.wait()
        
        # Cancel tasks
        for task in tasks:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        
        await self.stop()
    
    async def _ensure_consumer_group(self, stream: str) -> None:
        """Create consumer group if it doesn't exist."""
        try:
            await self._redis.xgroup_create(
                stream,
                self.consumer_group,
                id="0",
                mkstream=True,
            )
            logger.info(f"Created consumer group for {stream}")
        except redis.ResponseError as e:
            if "BUSYGROUP" in str(e):
                logger.debug(f"Consumer group already exists for {stream}")
            else:
                raise
    
    async def _process_orderbook_stream(self) -> None:
        """Process orderbook events from Redis stream."""
        logger.info(f"Starting orderbook stream processor: {self.orderbook_stream}")
        
        while self._running:
            try:
                # Read from stream with consumer group
                messages = await self._redis.xreadgroup(
                    groupname=self.consumer_group,
                    consumername=self.consumer_name,
                    streams={self.orderbook_stream: ">"},
                    count=100,
                    block=1000,  # 1 second timeout
                )
                
                if not messages:
                    continue
                
                for stream_name, entries in messages:
                    for message_id, data in entries:
                        try:
                            await self._handle_orderbook_message(data)
                            # Acknowledge message
                            await self._redis.xack(
                                stream_name,
                                self.consumer_group,
                                message_id,
                            )
                        except Exception as e:
                            logger.error(f"Error processing orderbook message: {e}")
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in orderbook stream processor: {e}")
                await asyncio.sleep(1)
    
    async def _process_trade_stream(self) -> None:
        """Process trade events from Redis stream."""
        logger.info(f"Starting trade stream processor: {self.trade_stream}")
        
        while self._running:
            try:
                # Read from stream with consumer group
                messages = await self._redis.xreadgroup(
                    groupname=self.consumer_group,
                    consumername=self.consumer_name,
                    streams={self.trade_stream: ">"},
                    count=500,
                    block=1000,  # 1 second timeout
                )
                
                if not messages:
                    continue
                
                for stream_name, entries in messages:
                    for message_id, data in entries:
                        try:
                            await self._handle_trade_message(data)
                            # Acknowledge message
                            await self._redis.xack(
                                stream_name,
                                self.consumer_group,
                                message_id,
                            )
                        except Exception as e:
                            logger.error(f"Error processing trade message: {e}")
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in trade stream processor: {e}")
                await asyncio.sleep(1)

    async def _process_order_stream(self) -> None:
        """Process order telemetry events from Redis stream."""
        logger.info(f"Starting order stream processor: {self.order_stream}")

        while self._running:
            try:
                messages = await self._redis.xreadgroup(
                    groupname=self.consumer_group,
                    consumername=self.consumer_name,
                    streams={self.order_stream: ">"},
                    count=500,
                    block=1000,
                )

                if not messages:
                    continue

                for stream_name, entries in messages:
                    for message_id, data in entries:
                        try:
                            await self._handle_order_message(data)
                            await self._redis.xack(
                                stream_name,
                                self.consumer_group,
                                message_id,
                            )
                        except Exception as e:
                            logger.error(f"Error processing order message: {e}")

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in order stream processor: {e}")
                await asyncio.sleep(1)
    
    async def _handle_orderbook_message(self, data: dict) -> None:
        """Handle a single orderbook message."""
        raw = data.get(b"data") or data.get("data")
        if not raw:
            return
        
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        
        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            return
        
        payload = event.get("payload") or event
        tenant_id = str(payload.get("tenant_id") or event.get("tenant_id") or self.tenant_id).strip() or self.tenant_id
        bot_id = str(payload.get("bot_id") or event.get("bot_id") or self.bot_id).strip() or self.bot_id
        symbol = payload.get("symbol")
        if not symbol:
            return
        tenant_id = str(payload.get("tenant_id") or event.get("tenant_id") or self.tenant_id).strip() or self.tenant_id
        bot_id = str(payload.get("bot_id") or event.get("bot_id") or self.bot_id).strip() or self.bot_id
        
        bids = payload.get("bids") or []
        asks = payload.get("asks") or []
        
        if not bids or not asks:
            return
        
        # Get timestamp
        ts = payload.get("timestamp") or payload.get("ts") or time.time()
        if isinstance(ts, str):
            ts = float(ts)
        
        # Get sequence number
        seq = payload.get("seq") or 0
        
        # Create OrderbookState for the writer
        state = OrderbookState(symbol=symbol)
        state.apply_snapshot(bids, asks, seq)
        
        # Capture snapshot (large) only when enabled.
        if self._snapshot_writer:
            await self._snapshot_writer.maybe_capture(
                symbol=symbol,
                exchange=self.exchange,
                state=state,
                timestamp=ts,
                seq=seq,
                tenant_id=tenant_id,
                bot_id=bot_id,
            )

        # Also persist a lightweight derived metrics row (small, good default for 2-week retention).
        if self._orderbook_events_enabled and self._pool:
            now_s = time.time()
            last_s = self._last_orderbook_event_write.get(symbol, 0.0)
            if now_s - last_s >= self._orderbook_events_interval_sec:
                self._last_orderbook_event_write[symbol] = now_s

                # Only store derived metrics; never store full bids/asks here.
                bids1, asks1 = state.as_levels(depth=1)
                best_bid = bids1[0][0] if bids1 else 0.0
                best_ask = asks1[0][0] if asks1 else 0.0
                mid = (best_bid + best_ask) / 2.0 if (best_bid > 0 and best_ask > 0) else 0.0
                spread_bps = ((best_ask - best_bid) / mid * 10000.0) if mid > 0 else 0.0

                # Depth is computed from a bounded slice of the state to keep CPU predictable.
                bids20, asks20 = state.as_levels(depth=20)
                bid_depth_usd = sum(p * s for p, s in bids20)
                ask_depth_usd = sum(p * s for p, s in asks20)
                denom = bid_depth_usd + ask_depth_usd
                imbalance = (bid_depth_usd / denom) if denom > 0 else 0.5

                payload_small = {
                    "symbol": symbol,
                    "timestamp": ts,
                    "seq": seq,
                    "best_bid": best_bid,
                    "best_ask": best_ask,
                    "spread_bps": spread_bps,
                    "bid_depth_usd": bid_depth_usd,
                    "ask_depth_usd": ask_depth_usd,
                    "orderbook_imbalance": imbalance,
                }

                event_ts = datetime.fromtimestamp(ts, tz=timezone.utc)
                async with self._pool.acquire() as conn:
                    await conn.execute(
                        "INSERT INTO orderbook_events (tenant_id, bot_id, symbol, exchange, ts, payload) VALUES ($1,$2,$3,$4,$5,$6::jsonb)",
                        tenant_id,
                        bot_id,
                        symbol,
                        self.exchange,
                        event_ts,
                        json.dumps(payload_small, separators=(",", ":"), default=str),
                    )
        
        self._orderbook_count += 1
        self._last_orderbook_ts[symbol] = time.time()

    async def _retention_loop(self) -> None:
        """Periodically delete old telemetry to cap DB growth.

        This runs in the background and must never take the worker down.
        """
        # Small jitter so multiple workers don't sweep in lockstep.
        await asyncio.sleep(3.0)
        while self._running and not self._stop_event.is_set():
            try:
                await self._run_retention_sweep()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning("retention_sweep_failed", extra={"error": str(exc)})
            await asyncio.sleep(max(self._retention_sweep_sec, 60.0))

    async def _run_retention_sweep(self) -> None:
        if not self._pool:
            return

        delete_batch = int(os.getenv("PERSISTENCE_RETENTION_DELETE_BATCH", "50000"))
        max_batches_per_table = int(os.getenv("PERSISTENCE_RETENTION_MAX_BATCHES_PER_TABLE", "20"))

        # Table -> (timestamp_column, retention_days)
        policies: list[tuple[str, str, float]] = [
            # Biggest tables: keep short unless you explicitly need them.
            ("orderbook_snapshots", "ts", self._retention_orderbook_days),
            ("orderbook_events", "ts", self._retention_orderbook_days),

            # General telemetry (2 weeks)
            ("decision_events", "ts", self._retention_telemetry_days),
            ("prediction_events", "ts", self._retention_telemetry_days),
            ("latency_events", "ts", self._retention_telemetry_days),
            ("fee_events", "ts", self._retention_telemetry_days),
            ("risk_events", "ts", self._retention_telemetry_days),
            ("guardrail_events", "ts", self._retention_telemetry_days),
            ("position_events", "ts", self._retention_telemetry_days),
            ("market_data_provider_events", "ts", self._retention_telemetry_days),
            ("order_events", "ts", self._retention_telemetry_days),

            # Order updates are often noisy; keep shorter than decisions.
            ("order_update_events", "ts", self._retention_order_updates_days),

            # Market data
            ("market_candles", "ts", self._retention_candles_days),
            ("trade_records", "ts", self._retention_trades_days),

            # Low-volume analytics tables (still enforce retention to avoid unbounded growth)
            ("timeline_events", "created_at", self._retention_telemetry_days),
            ("market_context", "created_at", self._retention_telemetry_days),
            ("signals", "created_at", self._retention_telemetry_days),
            ("risk_incidents", "created_at", self._retention_telemetry_days),
            ("sltp_events", "created_at", self._retention_telemetry_days),
        ]

        async with self._pool.acquire() as conn:
            for table, ts_col, days in policies:
                if days <= 0:
                    continue

                exists = await conn.fetchval(
                    "SELECT 1 FROM information_schema.tables WHERE table_schema='public' AND table_name=$1",
                    table,
                )
                if not exists:
                    continue

                cutoff = datetime.now(timezone.utc) - timedelta(days=float(days))

                # Chunked deletes to avoid long transactions/locks.
                total_deleted = 0
                for _ in range(max_batches_per_table):
                    deleted = await conn.fetchval(
                        f"""
                        WITH doomed AS (
                          SELECT ctid
                          FROM {table}
                          WHERE tenant_id = $1
                            AND bot_id = $2
                            AND {ts_col} < $3
                          LIMIT $4
                        ),
                        deleted AS (
                          DELETE FROM {table}
                          WHERE ctid IN (SELECT ctid FROM doomed)
                          RETURNING 1
                        )
                        SELECT COUNT(*)::bigint FROM deleted
                        """,
                        self.tenant_id,
                        self.bot_id,
                        cutoff,
                        delete_batch,
                    )
                    deleted = int(deleted or 0)
                    if deleted == 0:
                        break
                    total_deleted += deleted

                if total_deleted:
                    logger.info(
                        "retention_deleted_rows",
                        extra={"table": table, "deleted": total_deleted, "cutoff": cutoff.isoformat()},
                    )
    
    async def _handle_trade_message(self, data: dict) -> None:
        """Handle a single trade message."""
        raw = data.get(b"data") or data.get("data")
        if not raw:
            return
        
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        
        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            return
        
        payload = event.get("payload") or event
        tenant_id = str(payload.get("tenant_id") or event.get("tenant_id") or self.tenant_id).strip() or self.tenant_id
        bot_id = str(payload.get("bot_id") or event.get("bot_id") or self.bot_id).strip() or self.bot_id
        
        # Handle batch of trades
        trades = payload.get("trades") or [payload]
        
        for trade in trades:
            symbol = trade.get("symbol")
            if not symbol:
                continue
            
            # Get timestamp
            ts = trade.get("timestamp") or trade.get("ts") or time.time()
            if isinstance(ts, (int, float)):
                # Convert to datetime
                if ts > 10_000_000_000:
                    ts = ts / 1000.0
                ts = datetime.fromtimestamp(ts, tz=timezone.utc)
            elif isinstance(ts, str):
                ts = datetime.fromtimestamp(float(ts), tz=timezone.utc)
            
            # Create trade record
            trade_record = PersistenceTradeRecord(
                symbol=symbol,
                exchange=self.exchange,
                timestamp=ts,
                price=float(trade.get("price") or 0),
                size=float(trade.get("size") or trade.get("qty") or 0),
                side=trade.get("side") or "unknown",
                trade_id=str(trade.get("trade_id") or trade.get("id") or ""),
                tenant_id=tenant_id,
                bot_id=bot_id,
            )
            
            if trade_record.price > 0 and trade_record.size > 0:
                await self._trade_writer.record(trade_record)
                self._trade_count += 1
                self._last_trade_ts[symbol] = time.time()

    async def _handle_order_message(self, data: dict) -> None:
        """Persist order telemetry event into order_events and order_states."""
        raw = data.get(b"data") or data.get("data")
        if not raw:
            return
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            return

        payload = event.get("payload") if isinstance(event, dict) else None
        if not isinstance(payload, dict):
            return
        payload = _normalize_order_payload(payload)

        tenant_id = str(payload.get("tenant_id") or "").strip()
        bot_id = str(event.get("bot_id") or "").strip()
        symbol = (event.get("symbol") or payload.get("symbol") or "").strip()
        exchange = (event.get("exchange") or payload.get("exchange") or self.exchange)
        if not tenant_id or not bot_id:
            return

        event_ts = _parse_event_timestamp(event.get("timestamp")) or datetime.now(timezone.utc)
        semantic_key = _build_order_event_semantic_key(payload, event_ts)
        payload_json = json.dumps(payload, separators=(",", ":"), sort_keys=True, default=str)
        status = str(payload.get("status") or "").strip().lower()
        side = str(payload.get("side") or "").strip().lower()

        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                WITH incoming AS (
                    SELECT $6::jsonb AS payload
                )
                INSERT INTO order_events (
                    tenant_id, bot_id, symbol, exchange, ts,
                    order_id, client_order_id, event_type, status, reason,
                    fill_price, filled_size, fee_usd,
                    payload, semantic_key
                )
                SELECT
                    $1, $2, $3, $4, $5,
                    nullif(trim(coalesce(incoming.payload->>'order_id', '')), ''),
                    nullif(trim(coalesce(incoming.payload->>'client_order_id', '')), ''),
                    nullif(trim(coalesce(incoming.payload->>'event_type', '')), ''),
                    nullif(trim(coalesce(incoming.payload->>'status', '')), ''),
                    nullif(trim(coalesce(incoming.payload->>'reason', '')), ''),
                    NULLIF(incoming.payload->>'fill_price', '')::double precision,
                    NULLIF(incoming.payload->>'filled_size', '')::double precision,
                    NULLIF(incoming.payload->>'fee_usd', '')::double precision,
                    incoming.payload, $7
                FROM incoming
                WHERE NOT EXISTS (
                    SELECT 1
                    FROM order_events oe
                    WHERE oe.tenant_id = $1
                      AND oe.bot_id = $2
                      AND (
                          oe.semantic_key = $7
                          OR (
                              lower(coalesce(incoming.payload->>'position_effect',''))='close'
                              AND lower(coalesce(oe.payload->>'position_effect',''))='close'
                              AND nullif(trim(coalesce(incoming.payload->>'order_id','')), '') IS NOT NULL
                              AND (oe.payload->>'order_id') = (incoming.payload->>'order_id')
                              AND lower(coalesce(oe.payload->>'status',''))='filled'
                              AND lower(coalesce(incoming.payload->>'status',''))='filled'
                          )
                          OR (
                              oe.symbol IS NOT DISTINCT FROM $3
                              AND oe.exchange = $4
                              AND oe.ts = $5
                              AND oe.payload = incoming.payload
                          )
                      )
                )
                """,
                tenant_id,
                bot_id,
                symbol or None,
                exchange,
                event_ts,
                payload_json,
                semantic_key,
            )

            order_id = _as_text(payload.get("order_id"))
            client_order_id = _as_text(payload.get("client_order_id"))
            if status and side and (order_id or client_order_id):
                size = _to_float(payload.get("size"))
                if size is None:
                    size = _to_float(payload.get("filled_size")) or 0.0
                fill_price = _to_float(payload.get("fill_price"))
                fee_usd = _to_float(payload.get("fee_usd"))
                slippage_bps = _to_float(payload.get("slippage_bps"))
                filled_size = _to_float(payload.get("filled_size"))
                remaining_size = _to_float(payload.get("remaining_size"))
                reason = _as_text(payload.get("reason"))
                state_source = _as_text(payload.get("source")) or _as_text(payload.get("state_source")) or "stream"
                raw_exchange_status = _as_text(payload.get("raw_exchange_status"))
                submitted_at = _parse_event_timestamp(payload.get("submitted_at"))
                accepted_at = _parse_event_timestamp(payload.get("accepted_at"))
                open_at = _parse_event_timestamp(payload.get("open_at"))
                filled_at = _parse_event_timestamp(payload.get("filled_at"))
                await _upsert_order_state(
                    conn=conn,
                    tenant_id=tenant_id,
                    bot_id=bot_id,
                    exchange=exchange,
                    symbol=(symbol or None),
                    side=side,
                    size=float(size),
                    status=status,
                    order_id=order_id,
                    client_order_id=client_order_id,
                    reason=reason,
                    fill_price=fill_price,
                    fee_usd=fee_usd,
                    filled_size=filled_size,
                    remaining_size=remaining_size,
                    state_source=state_source,
                    raw_exchange_status=raw_exchange_status,
                    submitted_at=submitted_at,
                    accepted_at=accepted_at,
                    open_at=open_at,
                    filled_at=filled_at,
                    updated_at=event_ts,
                    slippage_bps=slippage_bps,
                )

        self._order_event_count += 1
        if symbol:
            self._last_order_ts[symbol] = time.time()

    async def _retention_loop(self) -> None:
        """Periodically delete old rows so the DB cannot grow unbounded.

        This is intentionally conservative: failures are logged and ignored.
        """
        # Short-circuit if disabled/misconfigured.
        if not self._retention_enabled or self._retention_sweep_sec <= 0:
            return
        while self._running and not self._stop_event.is_set():
            try:
                await self._run_retention_sweep()
            except Exception as exc:
                logger.warning("retention_sweep_failed", extra={"error": str(exc)})
            await asyncio.sleep(self._retention_sweep_sec)

    async def _run_retention_sweep(self) -> None:
        if not self._pool:
            return

        # Table -> (ts_column, days)
        policies: list[tuple[str, str, float]] = [
            ("orderbook_snapshots", "ts", self._retention_orderbook_days),
            ("orderbook_events", "ts", self._retention_orderbook_days),
            ("order_update_events", "ts", self._retention_order_updates_days),
            ("order_events", "ts", self._retention_telemetry_days),
            ("decision_events", "ts", self._retention_telemetry_days),
            ("prediction_events", "ts", self._retention_telemetry_days),
            ("latency_events", "ts", self._retention_telemetry_days),
            ("fee_events", "ts", self._retention_telemetry_days),
            ("risk_events", "ts", self._retention_telemetry_days),
            ("guardrail_events", "ts", self._retention_telemetry_days),
            ("position_events", "ts", self._retention_telemetry_days),
            ("market_data_provider_events", "ts", self._retention_telemetry_days),
            ("market_candles", "ts", self._retention_candles_days),
            ("trade_records", "ts", self._retention_trades_days),
        ]

        async with self._pool.acquire() as conn:
            for table, col, days in policies:
                if days <= 0:
                    continue
                cutoff = datetime.now(timezone.utc) - timedelta(days=float(days))
                # All targeted tables have tenant_id/bot_id; filtering keeps deletes index-friendly.
                await conn.execute(
                    f"DELETE FROM {table} WHERE tenant_id=$1 AND bot_id=$2 AND {col} < $3",
                    self.tenant_id,
                    self.bot_id,
                    cutoff,
                )
    
    async def _log_stats_periodically(self) -> None:
        """Log statistics every 60 seconds."""
        while self._running:
            try:
                await asyncio.sleep(60)
                
                uptime = time.time() - self._start_time
                ob_rate = self._orderbook_count / uptime if uptime > 0 else 0
                trade_rate = self._trade_count / uptime if uptime > 0 else 0
                order_rate = self._order_event_count / uptime if uptime > 0 else 0
                
                logger.info(
                    "Data persistence stats",
                    extra={
                        "uptime_sec": round(uptime, 1),
                        "orderbook_total": self._orderbook_count,
                        "orderbook_rate_per_sec": round(ob_rate, 2),
                        "trade_total": self._trade_count,
                        "trade_rate_per_sec": round(trade_rate, 2),
                        "order_total": self._order_event_count,
                        "order_rate_per_sec": round(order_rate, 2),
                        "symbols_with_orderbook": list(self._last_orderbook_ts.keys()),
                        "symbols_with_trades": list(self._last_trade_ts.keys()),
                        "symbols_with_orders": list(self._last_order_ts.keys()),
                    },
                )
                
                # Log buffer sizes
                if self._snapshot_writer:
                    logger.info(f"Orderbook buffer size: {self._snapshot_writer.get_buffer_size()}")
                if self._trade_writer:
                    logger.info(f"Trade buffer size: {self._trade_writer.get_buffer_size()}")
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error logging stats: {e}")
    
    async def stop(self) -> None:
        """Stop the worker and flush remaining data."""
        logger.info("Stopping data persistence worker...")
        self._running = False
        if self._retention_task:
            self._retention_task.cancel()
        
        # Stop writers (flushes remaining buffers)
        if self._snapshot_writer:
            await self._snapshot_writer.stop()
            logger.info("OrderbookSnapshotWriter stopped")
        
        if self._trade_writer:
            await self._trade_writer.stop()
            logger.info("TradeRecordWriter stopped")
        
        # Close connections
        if self._pool:
            await self._pool.close()
            logger.info("TimescaleDB connection closed")
        
        if self._redis:
            await self._redis.close()
            logger.info("Redis connection closed")
        
        logger.info(
            "Data persistence worker stopped",
            extra={
                "orderbook_total": self._orderbook_count,
                "trade_total": self._trade_count,
                "order_total": self._order_event_count,
            },
        )
    
    def request_stop(self) -> None:
        """Request graceful shutdown."""
        self._stop_event.set()


async def main() -> None:
    """Main entry point."""
    # Load configuration from environment
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
    # Prefer an explicit URL if provided, but fall back to BOT_DB_*.
    # This keeps ECS simple: we can inject BOT_DB_HOST/USER/PASSWORD and avoid
    # relying on a separate BOT_TIMESCALE_URL secret.
    explicit = os.getenv("BOT_TIMESCALE_URL") or os.getenv("TIMESCALE_URL")
    if explicit:
        timescale_url = explicit
    else:
        host = os.getenv("BOT_DB_HOST", "localhost")
        port = os.getenv("BOT_DB_PORT", "5433")  # local timescale default
        name = os.getenv("BOT_DB_NAME", "quantgambit_bot")
        user = os.getenv("BOT_DB_USER", "quantgambit")
        password = os.getenv("BOT_DB_PASSWORD", "")
        auth = f"{user}:{password}@" if password else f"{user}@"
        timescale_url = f"postgresql://{auth}{host}:{port}/{name}"
    exchange = os.getenv("EXCHANGE", "bybit")
    orderbook_stream = os.getenv("ORDERBOOK_EVENT_STREAM", f"events:orderbook_feed:{exchange}")
    trade_stream = os.getenv("TRADE_EVENT_STREAM", f"events:trades:{exchange}")
    order_stream = os.getenv("ORDER_EVENT_STREAM", "events:order")
    consumer_group = os.getenv("CONSUMER_GROUP", "data_persistence")
    consumer_name = os.getenv("CONSUMER_NAME", f"worker_{os.getpid()}")
    tenant_id = os.getenv("BOT_TENANT_ID", "default")
    bot_id = os.getenv("BOT_ID", "default")
    
    worker = DataPersistenceWorker(
        redis_url=redis_url,
        timescale_url=timescale_url,
        exchange=exchange,
        orderbook_stream=orderbook_stream,
        trade_stream=trade_stream,
        order_stream=order_stream,
        consumer_group=consumer_group,
        consumer_name=consumer_name,
        tenant_id=tenant_id,
        bot_id=bot_id,
    )
    
    # Handle signals
    def handle_signal(sig, frame):
        logger.info(f"Received signal {sig}, requesting shutdown...")
        worker.request_stop()
    
    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)
    
    await worker.start()


def _as_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _to_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_event_timestamp(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, (int, float)):
        raw = float(value)
        if raw > 10_000_000_000:
            raw /= 1000.0
        return datetime.fromtimestamp(raw, tz=timezone.utc)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            numeric = float(text)
            if numeric > 10_000_000_000:
                numeric /= 1000.0
            return datetime.fromtimestamp(numeric, tz=timezone.utc)
        except ValueError:
            pass
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            return None
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    return None


def _rows_affected(result: str) -> int:
    try:
        return int(str(result).split()[-1])
    except Exception:
        return 0


async def _upsert_order_state(
    conn,
    tenant_id: str,
    bot_id: str,
    exchange: Optional[str],
    symbol: Optional[str],
    side: str,
    size: float,
    status: str,
    order_id: Optional[str],
    client_order_id: Optional[str],
    reason: Optional[str],
    fill_price: Optional[float],
    fee_usd: Optional[float],
    filled_size: Optional[float],
    remaining_size: Optional[float],
    state_source: Optional[str],
    raw_exchange_status: Optional[str],
    submitted_at: Optional[datetime],
    accepted_at: Optional[datetime],
    open_at: Optional[datetime],
    filled_at: Optional[datetime],
    updated_at: datetime,
    slippage_bps: Optional[float],
) -> None:
    update_query = (
        "UPDATE order_states SET "
        "exchange=$4, symbol=$5, side=$6, size=$7, status=$8, "
        "order_id=COALESCE($9, order_id), client_order_id=COALESCE($10, client_order_id), "
        "reason=$11, fill_price=$12, fee_usd=$13, filled_size=$14, remaining_size=$15, "
        "state_source=$16, raw_exchange_status=$17, "
        "submitted_at=COALESCE($18, submitted_at), accepted_at=COALESCE($19, accepted_at), "
        "open_at=COALESCE($20, open_at), filled_at=COALESCE($21, filled_at), "
        "updated_at=$22, slippage_bps=COALESCE($23, slippage_bps) "
        "WHERE tenant_id=$1 AND bot_id=$2 AND {predicate}"
    )
    if client_order_id:
        updated = await conn.execute(
            update_query.format(predicate="client_order_id=$3"),
            tenant_id,
            bot_id,
            client_order_id,
            exchange,
            symbol,
            side,
            size,
            status,
            order_id,
            client_order_id,
            reason,
            fill_price,
            fee_usd,
            filled_size,
            remaining_size,
            state_source,
            raw_exchange_status,
            submitted_at,
            accepted_at,
            open_at,
            filled_at,
            updated_at,
            slippage_bps,
        )
        if _rows_affected(updated) > 0:
            return
    if order_id:
        updated = await conn.execute(
            update_query.format(predicate="order_id=$3"),
            tenant_id,
            bot_id,
            order_id,
            exchange,
            symbol,
            side,
            size,
            status,
            order_id,
            client_order_id,
            reason,
            fill_price,
            fee_usd,
            filled_size,
            remaining_size,
            state_source,
            raw_exchange_status,
            submitted_at,
            accepted_at,
            open_at,
            filled_at,
            updated_at,
            slippage_bps,
        )
        if _rows_affected(updated) > 0:
            return

    insert_query = (
        "INSERT INTO order_states "
        "(tenant_id, bot_id, exchange, symbol, side, size, status, order_id, client_order_id, "
        "reason, fill_price, fee_usd, filled_size, remaining_size, state_source, raw_exchange_status, "
        "submitted_at, accepted_at, open_at, filled_at, updated_at, slippage_bps) "
        "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20,$21,$22)"
    )
    try:
        await conn.execute(
            insert_query,
            tenant_id,
            bot_id,
            exchange,
            symbol,
            side,
            size,
            status,
            order_id,
            client_order_id,
            reason,
            fill_price,
            fee_usd,
            filled_size,
            remaining_size,
            state_source,
            raw_exchange_status,
            submitted_at,
            accepted_at,
            open_at,
            filled_at,
            updated_at,
            slippage_bps,
        )
    except asyncpg.UniqueViolationError:
        # Fallback for environments that have unique constraints but no deterministic key preference.
        if client_order_id:
            retry_result = await conn.execute(
                update_query.format(predicate="client_order_id=$3"),
                tenant_id,
                bot_id,
                client_order_id,
                exchange,
                symbol,
                side,
                size,
                status,
                order_id,
                client_order_id,
                reason,
                fill_price,
                fee_usd,
                filled_size,
                remaining_size,
                state_source,
                raw_exchange_status,
                submitted_at,
                accepted_at,
                open_at,
                filled_at,
                updated_at,
                slippage_bps,
            )
            if _rows_affected(retry_result) > 0:
                return
        if order_id:
            await conn.execute(
                update_query.format(predicate="order_id=$3"),
                tenant_id,
                bot_id,
                order_id,
                exchange,
                symbol,
                side,
                size,
                status,
                order_id,
                client_order_id,
                reason,
                fill_price,
                fee_usd,
                filled_size,
                remaining_size,
                state_source,
                raw_exchange_status,
                submitted_at,
                accepted_at,
                open_at,
                filled_at,
                updated_at,
                slippage_bps,
            )


if __name__ == "__main__":
    asyncio.run(main())
