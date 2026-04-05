"""Feature and prediction worker."""

from __future__ import annotations

import os
import re
import time
import uuid
from dataclasses import dataclass
from typing import Dict, Optional, TYPE_CHECKING
from collections import deque
import math

from quantgambit.ai.context import get_global_context, get_symbol_context
from quantgambit.ingest.schemas import validate_feature_snapshot, coerce_float
from quantgambit.features.candle_indicators import ATRState, VWAPState
from quantgambit.market.trades import TradeStatsCache
from quantgambit.market.quality import MarketDataQualityTracker
from quantgambit.observability.logger import log_warning, log_info
from quantgambit.storage.redis_streams import (
    Event,
    RedisStreamsClient,
    decode_and_validate_event,
    decode_message,
    encode_event as _to_json,
)
from quantgambit.ingest.time_utils import sec_to_us, in_window_us
from quantgambit.storage.redis_snapshots import RedisSnapshotReader, RedisSnapshotWriter
from quantgambit.signals.prediction_providers import (
    PredictionProvider,
    HeuristicPredictionProvider,
    OnnxPredictionProvider,
)
from quantgambit.risk.symbol_calibrator import SymbolCalibrator, get_symbol_calibrator

if TYPE_CHECKING:
    from quantgambit.core.latency import LatencyTracker
    from quantgambit.signals.stages.amt_calculator import CandleCache


@dataclass
class FeatureWorkerConfig:
    source_stream: str = "events:market_data"
    output_stream: str = "events:features"
    consumer_group: str = "quantgambit_features"
    consumer_name: str = "feature_worker"
    block_ms: int = 1000
    candle_stream: str = "events:candles"
    candle_group: str = "quantgambit_features_candles"
    candle_consumer: str = "feature_candle_worker"
    trading_session_start_hour_utc: int = 0
    trading_session_end_hour_utc: int = 24
    orderbook_emit_interval_ms: int = 500
    orderbook_emit_min_ticks: int = 5
    min_quality_for_prediction: float = 0.6
    gate_on_orderbook_gap: bool = True
    gate_on_orderbook_stale: bool = True
    gate_on_trade_stale: bool = True
    gate_on_candle_stale: bool = True
    # Increase candle_stale tolerance to 5 minutes to handle resyncs more gracefully
    candle_stale_sec: float = 300.0
    degraded_risk_scale: float = 0.5
    drift_check_interval_sec: float = 30.0
    # When True, emit features even when quality is low (with degraded flag set)
    # This allows warmup/decision workers to track progress even during data issues
    emit_degraded_features: bool = True
    # Retained per-second price points for multi-horizon returns.
    # 7200 ~= 2h at 1 sample/sec.
    price_history_maxlen: int = 7200


class FeaturePredictionWorker:
    """Consumes market ticks and emits feature + market context snapshots."""

    def __init__(
        self,
        redis_client: RedisStreamsClient,
        bot_id: str,
        exchange: str,
        config: Optional[FeatureWorkerConfig] = None,
        telemetry=None,
        telemetry_context=None,
        orderbook_cache=None,
        prediction_provider: Optional[PredictionProvider] = None,
        shadow_prediction_provider: Optional[PredictionProvider] = None,
        prediction_confidence_scale: float = 1.0,
        prediction_confidence_bias: float = 0.0,
        trade_cache: Optional[TradeStatsCache] = None,
        quality_tracker: Optional[MarketDataQualityTracker] = None,
        latency_tracker: Optional["LatencyTracker"] = None,
        symbol_calibrator: Optional[SymbolCalibrator] = None,
        candle_cache: Optional["CandleCache"] = None,
    ):
        self.redis = redis_client
        self.bot_id = bot_id
        self.exchange = exchange
        self.telemetry = telemetry
        self.telemetry_context = telemetry_context
        self.orderbook_cache = orderbook_cache
        self.config = config or FeatureWorkerConfig()
        self.prediction_provider = prediction_provider or HeuristicPredictionProvider()
        self.shadow_prediction_provider = shadow_prediction_provider
        self.prediction_confidence_scale = prediction_confidence_scale
        self.prediction_confidence_bias = prediction_confidence_bias
        self.trade_cache = trade_cache
        self._ingest_trade_ticks_from_market_stream = (
            os.getenv("TRADE_SOURCE", "").lower() in {"external", "shared"}
            or os.getenv("TRADES_EXTERNAL", "false").lower() in {"1", "true", "yes"}
        )
        self.quality_tracker = quality_tracker
        self._latency_tracker = latency_tracker
        # Symbol calibrator for per-symbol threshold calibration (spread/depth norms)
        self._symbol_calibrator = symbol_calibrator or get_symbol_calibrator()
        # Candle cache for AMT calculations (shared with DecisionEngine)
        self._candle_cache = candle_cache
        self.snapshot_reader = RedisSnapshotReader(redis_client.redis)
        self.snapshot_writer = RedisSnapshotWriter(redis_client.redis)
        # Extract tenant_id from telemetry context for warmup status writing
        self.tenant_id = getattr(telemetry_context, "tenant_id", None) or os.getenv("TENANT_ID", "t1")
        self.drift_block_enabled = os.getenv("PREDICTION_DRIFT_BLOCK", "false").lower() in {
            "1",
            "true",
            "yes",
        }
        self._drift_fail_closed = os.getenv("PREDICTION_DRIFT_FAIL_CLOSED", "false").lower() in {
            "1",
            "true",
            "yes",
        }
        self._drift_max_age_sec = float(os.getenv("PREDICTION_DRIFT_STALE_SEC", "300.0"))
        self.drift_snapshot_key = os.getenv("PREDICTION_DRIFT_SNAPSHOT_KEY", "")
        if not self.drift_snapshot_key:
            tenant_id = os.getenv("TENANT_ID", "")
            if tenant_id:
                self.drift_snapshot_key = (
                    f"quantgambit:{tenant_id}:{self.bot_id}:prediction:drift:latest"
                )
        self._drift_last_checked = 0.0
        self._drift_blocked = False
        self._drift_block_reason: Optional[str] = None
        self.score_gate_enabled = os.getenv("PREDICTION_SCORE_GATE_ENABLED", "false").lower() in {
            "1",
            "true",
            "yes",
        }
        self._score_gate_fail_closed = os.getenv("PREDICTION_SCORE_FAIL_CLOSED", "false").lower() in {
            "1",
            "true",
            "yes",
        }
        self._score_gate_interval_sec = float(
            os.getenv("PREDICTION_SCORE_GATE_CHECK_INTERVAL_SEC", str(self.config.drift_check_interval_sec))
        )
        self._score_gate_max_age_sec = float(os.getenv("PREDICTION_SCORE_STALE_SEC", "900.0"))
        self._score_gate_min_samples = int(os.getenv("PREDICTION_SCORE_MIN_SAMPLES", "200"))
        self._score_gate_min_ml_score = float(os.getenv("PREDICTION_SCORE_MIN_ML_SCORE", "60.0"))
        self._score_gate_min_exact_acc = float(os.getenv("PREDICTION_SCORE_MIN_EXACT_ACCURACY", "0.50"))
        self._score_gate_min_directional_acc = float(
            os.getenv("PREDICTION_SCORE_MIN_DIRECTIONAL_ACCURACY", "0.50")
        )
        self._score_gate_min_directional_acc_long = coerce_float(
            os.getenv("PREDICTION_SCORE_MIN_DIRECTIONAL_ACCURACY_LONG")
        )
        self._score_gate_min_directional_acc_short = coerce_float(
            os.getenv("PREDICTION_SCORE_MIN_DIRECTIONAL_ACCURACY_SHORT")
        )
        self._score_gate_max_ece = float(os.getenv("PREDICTION_SCORE_MAX_ECE", "0.20"))
        self._score_gate_max_ece_long = coerce_float(os.getenv("PREDICTION_SCORE_MAX_ECE_LONG"))
        self._score_gate_max_ece_short = coerce_float(os.getenv("PREDICTION_SCORE_MAX_ECE_SHORT"))
        self._score_gate_mode = os.getenv("PREDICTION_SCORE_GATE_MODE", "block").strip().lower()
        if self._score_gate_mode not in {"block", "fallback_heuristic"}:
            self._score_gate_mode = "block"
        self._score_gate_respect_symbol_status = (
            os.getenv("PREDICTION_SCORE_RESPECT_SYMBOL_STATUS", "true").strip().lower()
            in {"1", "true", "yes", "on"}
        )
        self._score_gate_last_checked = 0.0
        self._score_gate_payload: Optional[dict] = None
        self.score_snapshot_key = os.getenv("PREDICTION_SCORE_SNAPSHOT_KEY", "")
        tenant_id = os.getenv("TENANT_ID", "")
        scoped_score_snapshot_key = (
            f"quantgambit:{tenant_id}:{self.bot_id}:prediction:score:latest"
            if tenant_id
            else ""
        )
        if scoped_score_snapshot_key:
            self.score_snapshot_key = _normalize_scoped_snapshot_key(
                candidate=self.score_snapshot_key,
                expected=scoped_score_snapshot_key,
                snapshot_type="score",
            )
        self._fallback_prediction_provider = HeuristicPredictionProvider()
        self._latency_log_last: Dict[str, float] = {}
        self._latency_log_interval_sec = float(os.getenv("FEATURE_LATENCY_LOG_INTERVAL_SEC", "30"))
        # Training data stream: throttled to 1 snapshot/sec/symbol for ML dataset accumulation
        self._training_stream_enabled = os.getenv(
            "FEATURE_TRAINING_STREAM_ENABLED", "true"
        ).lower() in {"1", "true", "yes"}
        self._training_stream_name = os.getenv(
            "FEATURE_TRAINING_STREAM", self.config.output_stream + ":training"
        )
        self._training_stream_interval_sec = float(
            os.getenv("FEATURE_TRAINING_STREAM_INTERVAL_SEC", "1.0")
        )
        self._training_stream_maxlen = int(
            os.getenv("FEATURE_TRAINING_STREAM_MAXLEN", "500000")
        )
        self._training_stream_last_emit: Dict[str, float] = {}
        self._latency_log_threshold_ms = float(os.getenv("FEATURE_LATENCY_LOG_THRESHOLD_MS", "1000"))
        self._last_ticks: Dict[str, dict] = {}
        self._price_history: Dict[str, deque] = {}
        self._return_history: Dict[str, deque] = {}
        self._ema_state: Dict[str, dict] = {}
        self._candle_history: Dict[str, deque] = {}
        self._atr_state: Dict[str, ATRState] = {}
        self._vwap_state: Dict[str, VWAPState] = {}
        self._atr_baseline_state: Dict[str, ATRState] = {}
        self._latest_candle_count: Dict[str, int] = {}
        self._latest_candle_ts: Dict[str, float] = {}
        self._amt_candle_timeframe_sec = int(os.getenv("AMT_CANDLE_TIMEFRAME_SEC", "300"))
        self._orderbook_tasks: list = []
        self._orderbook_last_emit: Dict[str, float] = {}
        self._orderbook_tick_count: Dict[str, int] = {}
        # Cache bid/ask from orderbook_feed ticks to use when processing trade ticks
        self._bid_ask_cache: Dict[str, Dict[str, float]] = {}
        # Multi-timeframe orderflow imbalance buffers for persistence tracking
        # Each buffer stores (timestamp, imbalance) tuples
        self._imb_buffer_1s: Dict[str, deque] = {}   # 1-second rolling
        self._imb_buffer_5s: Dict[str, deque] = {}   # 5-second rolling
        self._imb_buffer_30s: Dict[str, deque] = {}  # 30-second rolling
        self._imb_sign_history: Dict[str, deque] = {}  # For persistence tracking
        
        # Per-feed staleness tracking: last update timestamp per feed type per symbol
        # This allows detecting issues with individual data feeds (not just overall snapshot age)
        self._feed_timestamps: Dict[str, Dict[str, float]] = {}  # {symbol: {feed_type: timestamp}}
        self._price_history_maxlen = max(
            1200,
            int(
                os.getenv(
                    "FEATURE_PRICE_HISTORY_MAXLEN",
                    str(getattr(self.config, "price_history_maxlen", 7200)),
                )
            ),
        )

    async def run(self) -> None:
        log_info("feature_worker_start", source=self.config.source_stream, output=self.config.output_stream)
        await self._warmup_price_history_from_stream()
        await self._warmup_indicator_state_from_candle_stream()
        await self.redis.create_group(self.config.source_stream, self.config.consumer_group, start_id="$")
        await self.redis.create_group(self.config.candle_stream, self.config.candle_group)
        while True:
            tick_messages = await self.redis.read_group(
                self.config.consumer_group,
                self.config.consumer_name,
                {self.config.source_stream: ">"},
                block_ms=self.config.block_ms,
            )
            for stream_name, entries in tick_messages:
                for message_id, payload in entries:
                    await self._handle_message(payload)
                    await self.redis.ack(stream_name, self.config.consumer_group, message_id)
            candle_messages = await self.redis.read_group(
                self.config.candle_group,
                self.config.candle_consumer,
                {self.config.candle_stream: ">"},
                block_ms=1,
            )
            for stream_name, entries in candle_messages:
                for message_id, payload in entries:
                    await self._handle_candle(payload)
                    await self.redis.ack(stream_name, self.config.candle_group, message_id)
            await self._flush_orderbook_tasks()

    async def _warmup_price_history_from_stream(self) -> None:
        """Backfill per-symbol price history from recent market ticks on startup."""
        def _normalize_symbol_key(value: str) -> str:
            normalized = re.sub(r"[^A-Z0-9]", "", str(value or "").upper())
            normalized = normalized.replace("SWAP", "").replace("PERP", "")
            return normalized

        backfill_count = max(
            0,
            int(os.getenv("FEATURE_PRICE_HISTORY_BACKFILL_COUNT", "150000")),
        )
        backfill_window_sec = max(
            0.0,
            float(os.getenv("FEATURE_PRICE_HISTORY_BACKFILL_SEC", "900")),
        )
        if backfill_count <= 0:
            return
        redis_raw = getattr(self.redis, "redis", None)
        if redis_raw is None or not hasattr(redis_raw, "xrevrange"):
            return
        min_stream_ms = max(0, int(time.time() * 1000 - backfill_window_sec * 1000))
        try:
            entries = await redis_raw.xrevrange(
                self.config.source_stream,
                "+",
                f"{min_stream_ms}-0",
                count=backfill_count,
            )
        except Exception as exc:
            log_warning("feature_history_warmup_failed", error=str(exc))
            return
        warmed = 0
        symbols = set()
        expected_exchange = str(self.exchange or "").strip().lower()
        expected_market_type = str(os.getenv("MARKET_TYPE", "") or "").strip().lower()
        configured_symbols = {
            _normalize_symbol_key(part)
            for part in os.getenv("ORDERBOOK_SYMBOLS", "").split(",")
            if _normalize_symbol_key(part)
        }
        for _, payload in reversed(entries):
            try:
                message = decode_message(payload)
            except Exception:
                continue
            event_type = str(message.get("event_type") or "")
            if event_type and event_type not in {"market_tick", "market_data"}:
                continue
            message_exchange = str(message.get("exchange") or "").strip().lower()
            if expected_exchange and message_exchange and message_exchange != expected_exchange:
                continue
            message_market_type = str(message.get("market_type") or "").strip().lower()
            if expected_market_type and message_market_type and message_market_type != expected_market_type:
                continue
            body = message.get("payload") or {}
            symbol = body.get("symbol") or message.get("symbol")
            if not symbol:
                continue
            symbol = str(symbol)
            symbol_upper = symbol.upper()
            symbol_key = _normalize_symbol_key(symbol_upper)
            if configured_symbols and symbol_key not in configured_symbols:
                continue
            message_bot_id = str(message.get("bot_id") or "").strip()
            if (
                message_bot_id
                and message_bot_id != str(self.bot_id)
                and not message_market_type
                and not configured_symbols
            ):
                continue
            ts = coerce_float(body.get("timestamp")) or coerce_float(message.get("timestamp"))
            if ts is None:
                continue
            price = coerce_float(body.get("last"))
            if price is None:
                bid = coerce_float(body.get("bid"))
                ask = coerce_float(body.get("ask"))
                if bid is not None and ask is not None and ask > bid:
                    price = (bid + ask) / 2.0
            if price is None:
                continue
            self._update_history(symbol_upper, sec_to_us(ts), price)
            symbols.add(symbol_upper)
            warmed += 1
        if warmed > 0:
            log_info(
                "feature_history_warmed",
                points=warmed,
                symbols=sorted(symbols),
                source_stream=self.config.source_stream,
            )

    async def _warmup_indicator_state_from_candle_stream(self) -> None:
        """Backfill EMA/ATR/VWAP state from recent candle events on startup."""
        backfill_count = max(
            0,
            int(os.getenv("FEATURE_CANDLE_STATE_BACKFILL_COUNT", os.getenv("AMT_CANDLE_BOOTSTRAP_COUNT", "500"))),
        )
        if backfill_count <= 0:
            return
        redis_raw = getattr(self.redis, "redis", None)
        if redis_raw is None or not hasattr(redis_raw, "xrevrange"):
            return
        try:
            entries = await redis_raw.xrevrange(self.config.candle_stream, count=backfill_count)
        except Exception as exc:
            log_warning("feature_indicator_warmup_failed", error=str(exc))
            return
        warmed = 0
        symbols = set()
        for _, payload in reversed(entries):
            try:
                message = decode_message(payload)
            except Exception:
                continue
            if str(message.get("event_type") or "") != "candle":
                continue
            candle = message.get("payload") or {}
            symbol = candle.get("symbol")
            if not symbol:
                continue
            timeframe = None
            raw_tf = candle.get("timeframe_sec") or candle.get("timeframe")
            if raw_tf is not None:
                try:
                    timeframe = int(raw_tf)
                except (TypeError, ValueError):
                    timeframe = None
            if timeframe is not None and timeframe != self._amt_candle_timeframe_sec:
                continue
            history = self._candle_history.setdefault(str(symbol), deque(maxlen=500))
            history.append(candle)
            self._update_ema(str(symbol), candle)
            self._update_indicators(str(symbol), candle)
            self._latest_candle_count[str(symbol)] = len(history)
            warmed += 1
            symbols.add(str(symbol))
        if warmed > 0:
            log_info(
                "feature_indicator_warmed",
                candles=warmed,
                symbols=sorted(symbols),
                candle_stream=self.config.candle_stream,
            )

    async def _handle_message(self, payload: dict) -> None:
        # Start latency tracking
        latency_start = None
        if self._latency_tracker:
            latency_start = self._latency_tracker.start_timer("feature_worker")
        
        try:
            await self._handle_message_inner(payload)
        finally:
            # End latency tracking
            if self._latency_tracker and latency_start is not None:
                self._latency_tracker.end_timer("feature_worker", latency_start)

    def _update_feed_timestamp(self, symbol: str, feed_type: str, ts: Optional[float] = None) -> None:
        """Update last update timestamp for a specific feed type.
        
        IMPORTANT: staleness should reflect **receive time**, not exchange time.
        We ignore exchange timestamps for feed staleness to avoid false STALE_BOOK.
        """
        if symbol not in self._feed_timestamps:
            self._feed_timestamps[symbol] = {}
        # Always use canonical receive time for staleness tracking
        if ts is None:
            return
        self._feed_timestamps[symbol][feed_type] = ts
    
    def _get_feed_staleness(self, symbol: str, now_ts: float) -> Dict[str, float]:
        """Get staleness (seconds since last update) for each feed type."""
        now = now_ts
        feed_ts = self._feed_timestamps.get(symbol, {})
        result = {}
        for feed, ts in feed_ts.items():
            if ts is not None:
                try:
                    result[feed] = now - float(ts)
                except (TypeError, ValueError):
                    result[feed] = None
            else:
                result[feed] = None
        return result
    
    def _get_latency_data(self, symbol: str) -> Dict[str, Optional[int]]:
        """Get exchange timestamp (cts) latency data for DataReadinessGate.
        
        Returns dict with:
        - book_cts_ms: Orderbook matching engine timestamp (ms) - from orderbook cache
        - book_recv_ms: When we received the orderbook update (ms) - from _feed_timestamps
        - trade_ts_ms: Trade T timestamp from exchange (ms) - from orderbook cache
        - trade_recv_ms: When we received the trade (ms) - from _feed_timestamps
        
        Note: book_recv_ms and trade_recv_ms are derived from _feed_timestamps to ensure
        consistency with orderbook_feed_age_sec and trade_feed_age_sec calculations.
        This avoids timing mismatches between different event streams.
        """
        # Get exchange timestamps (cts) from orderbook cache
        cache_data = {}
        if self.orderbook_cache and hasattr(self.orderbook_cache, 'get_latency_data'):
            cache_data = self.orderbook_cache.get_latency_data(symbol)
        
        # Get receive timestamps from _feed_timestamps (consistent with feed_staleness)
        feed_ts = self._feed_timestamps.get(symbol, {})
        
        # Convert orderbook feed timestamp to ms (if available)
        book_recv_ms = None
        ob_ts = feed_ts.get("orderbook")
        if ob_ts is not None:
            try:
                book_recv_ms = int(float(ob_ts) * 1000)
            except (TypeError, ValueError):
                pass
        
        # Convert trade feed timestamp to ms (if available)
        trade_recv_ms = None
        trade_ts = feed_ts.get("trade")
        if trade_ts is not None:
            try:
                trade_recv_ms = int(float(trade_ts) * 1000)
            except (TypeError, ValueError):
                pass
        book_cts_ms = cache_data.get("book_cts_ms")
        trade_ts_ms = cache_data.get("trade_ts_ms")
        book_timestamp_ms = book_cts_ms if book_cts_ms is not None else book_recv_ms
        timestamp_ms = trade_ts_ms if trade_ts_ms is not None else trade_recv_ms
        
        return {
            "book_cts_ms": book_cts_ms,
            "book_recv_ms": book_recv_ms,
            "trade_ts_ms": trade_ts_ms,
            "trade_recv_ms": trade_recv_ms,
            # Legacy aliases still consumed by EV/cost-quality stages and diagnostics.
            "book_timestamp_ms": book_timestamp_ms,
            "timestamp_ms": timestamp_ms,
        }

    def _log_feed_latency(self, symbol: str, tick_ts: float, market_context: dict, now_ts: float) -> None:
        now = now_ts
        last_log = self._latency_log_last.get(symbol, 0.0)
        snapshot_age_ms = max(0.0, (now - (tick_ts or now)) * 1000.0)
        book_recv_ms = market_context.get("book_recv_ms")
        trade_recv_ms = market_context.get("trade_recv_ms")
        book_age_ms = (
            max(0.0, now * 1000.0 - float(book_recv_ms))
            if book_recv_ms is not None
            else None
        )
        trade_age_ms = (
            max(0.0, now * 1000.0 - float(trade_recv_ms))
            if trade_recv_ms is not None
            else None
        )
        feed_staleness = market_context.get("feed_staleness") or {}
        orderbook_stale = feed_staleness.get("orderbook")
        trade_stale = feed_staleness.get("trade")
        if snapshot_age_ms >= self._latency_log_threshold_ms or (now - last_log) >= self._latency_log_interval_sec:
            self._latency_log_last[symbol] = now
            log_info(
                "feature_feed_latency",
                symbol=symbol,
                snapshot_age_ms=round(snapshot_age_ms, 1),
                book_age_ms=round(book_age_ms, 1) if book_age_ms is not None else None,
                trade_age_ms=round(trade_age_ms, 1) if trade_age_ms is not None else None,
                orderbook_staleness_sec=round(orderbook_stale, 3) if orderbook_stale is not None else None,
                trade_staleness_sec=round(trade_stale, 3) if trade_stale is not None else None,
                book_recv_ms=book_recv_ms,
                trade_recv_ms=trade_recv_ms,
            )

    async def _handle_message_inner(self, payload: dict) -> None:
        try:
            event = decode_and_validate_event(payload)
        except Exception as exc:
            log_warning("feature_worker_invalid_event", error=str(exc))
            return
        if event.get("event_type") != "market_tick":
            return
        event_bot_id = str(event.get("bot_id") or "").strip()
        if event_bot_id and event_bot_id != str(self.bot_id):
            return
        tick = event.get("payload") or {}
        symbol = tick.get("symbol")
        if not symbol:
            return
        
        # Update feed timestamp based on tick source
        # Tick classification:
        # - source="orderbook_feed" + has bid/ask → orderbook tick
        # - source=None/missing + has "last" → trade tick
        tick_source = tick.get("source") or ""
        has_bid_ask = tick.get("bid") is not None or tick.get("ask") is not None
        has_last = tick.get("last") is not None
        
        tick_ts = coerce_float(tick.get("timestamp"))
        tick_canon_us = tick.get("ts_canon_us")
        try:
            tick_canon_us = int(tick_canon_us) if tick_canon_us is not None else None
        except (TypeError, ValueError):
            tick_canon_us = None
        if tick_canon_us is None:
            tick_canon_us = sec_to_us(tick_ts or 0.0)
        if "orderbook" in tick_source or (has_bid_ask and not has_last):
            self._update_feed_timestamp(symbol, "orderbook", tick_ts)
        if "trade" in tick_source or has_last:
            self._update_feed_timestamp(symbol, "trade", tick_ts)
            if self._ingest_trade_ticks_from_market_stream and self.trade_cache is not None:
                trade_price = coerce_float(tick.get("last"))
                trade_size = coerce_float(tick.get("volume")) or 0.0
                if trade_price is not None and trade_size > 0.0:
                    self.trade_cache.update_trade(
                        symbol=symbol,
                        timestamp_us=tick_canon_us,
                        price=trade_price,
                        size=trade_size,
                        side=str(tick.get("side") or ""),
                    )
        snapshot = await self._build_snapshot(symbol, tick)
        if snapshot is None:
            log_warning("feature_worker_gap_blocked", symbol=symbol)
            return
        try:
            validate_feature_snapshot(snapshot)
        except Exception as exc:
            log_warning("feature_snapshot_invalid", error=str(exc))
            return
        
        # Feed symbol calibrator with spread and depth observations
        if self._symbol_calibrator:
            self._symbol_calibrator.observe(
                symbol=symbol,
                spread_bps=snapshot.get("spread_bps"),
                bid_depth_usd=snapshot.get("bid_depth_usd"),
                ask_depth_usd=snapshot.get("ask_depth_usd"),
                timestamp=snapshot.get("timestamp"),
            )
        ts_us = sec_to_us(float(snapshot["timestamp"])) if snapshot.get("timestamp") is not None else None
        out_event = Event(
            event_id=str(uuid.uuid4()),
            event_type="feature_snapshot",
            schema_version="v1",
            timestamp=str(snapshot["timestamp"]),
            ts_recv_us=ts_us,
            ts_canon_us=ts_us,
            ts_exchange_s=None,
            bot_id=self.bot_id,
            symbol=symbol,
            exchange=self.exchange,
            payload=snapshot,
        )
        await self.redis.publish_event(self.config.output_stream, out_event)
        # Throttled training stream: 1 snapshot/sec/symbol for ML dataset accumulation
        if self._training_stream_enabled:
            now_ts = float(snapshot.get("timestamp", 0))
            last = self._training_stream_last_emit.get(symbol, 0.0)
            if (now_ts - last) >= self._training_stream_interval_sec:
                self._training_stream_last_emit[symbol] = now_ts
                try:
                    await self.redis.redis.xadd(
                        self._training_stream_name,
                        {"data": _to_json({
                            "event_id": out_event.event_id,
                            "event_type": out_event.event_type,
                            "schema_version": out_event.schema_version,
                            "timestamp": out_event.timestamp,
                            "ts_recv_us": out_event.ts_recv_us,
                            "ts_canon_us": out_event.ts_canon_us,
                            "ts_exchange_s": out_event.ts_exchange_s,
                            "bot_id": out_event.bot_id,
                            "symbol": out_event.symbol,
                            "exchange": out_event.exchange,
                            "payload": out_event.payload,
                        })},
                        maxlen=self._training_stream_maxlen,
                        approximate=True,
                    )
                except Exception:
                    pass  # non-critical, don't break hot path
        prediction = snapshot.get("prediction")
        prediction_shadow = snapshot.get("prediction_shadow")
        prediction_status = snapshot.get("prediction_status")
        if (
            prediction
            and self.telemetry
            and self.telemetry_context
            and hasattr(self.telemetry, "publish_prediction")
        ):
            await self.telemetry.publish_prediction(
                ctx=self.telemetry_context,
                symbol=symbol,
                payload=prediction,
            )
        if (
            prediction_shadow
            and self.telemetry
            and self.telemetry_context
            and hasattr(self.telemetry, "publish_prediction_shadow")
        ):
            await self.telemetry.publish_prediction_shadow(
                ctx=self.telemetry_context,
                symbol=symbol,
                payload=prediction_shadow,
            )
        elif (
            prediction_status
            and self.telemetry
            and self.telemetry_context
            and hasattr(self.telemetry, "publish_prediction")
        ):
            suppressed_payload = {
                "provider": "suppressed",
                "status": prediction_status.get("status") or "suppressed",
                "reject": True,
                "abstain": True,
                "reason": prediction_status.get("reason"),
                "prediction_blocked_reason": prediction_status.get("reason"),
                "abstain_reason": prediction_status.get("reason"),
                "quality_score": prediction_status.get("quality_score"),
                "orderbook_sync_state": prediction_status.get("orderbook_sync_state"),
                "trade_sync_state": prediction_status.get("trade_sync_state"),
                "flags": prediction_status.get("flags"),
                "timestamp": snapshot.get("timestamp"),
            }
            await self.telemetry.publish_prediction(
                ctx=self.telemetry_context,
                symbol=symbol,
                payload=suppressed_payload,
            )

    async def _handle_candle(self, payload: dict) -> None:
        try:
            event = decode_and_validate_event(payload)
        except Exception as exc:
            log_warning("feature_worker_invalid_candle_event", error=str(exc))
            return
        if event.get("event_type") != "candle":
            return
        candle = event.get("payload") or {}
        symbol = candle.get("symbol")
        if not symbol:
            return
        
        # Track candle feed timestamp.
        #
        # IMPORTANT:
        # - `candle["timestamp"]` is the candle *bucket start* (e.g., 5m candle at 03:20:00 is emitted ~03:25:05).
        #   Using bucket start for staleness makes candles appear "stale" for most of the next bucket.
        # - For feed health / staleness gating we must use receive/canonical time, not bucket start/end.
        candle_start_ts = coerce_float(candle.get("timestamp"))
        emit_ts_us = event.get("ts_canon_us") or candle.get("ts_canon_us") or candle.get("ts_recv_us")
        emit_ts = None
        if emit_ts_us is not None:
            try:
                emit_ts = float(int(emit_ts_us)) / 1_000_000.0
            except (TypeError, ValueError):
                emit_ts = None
        self._update_feed_timestamp(symbol, "candle", emit_ts or candle_start_ts)
        
        history = self._candle_history.setdefault(symbol, deque(maxlen=500))
        history.append(candle)

        timeframe = None
        raw_tf = candle.get("timeframe_sec") or candle.get("timeframe")
        if raw_tf is not None:
            try:
                timeframe = int(raw_tf)
            except (TypeError, ValueError):
                timeframe = None

        # Populate candle cache for AMT calculations (shared with DecisionEngine)
        if self._candle_cache is not None and (timeframe is None or timeframe == self._amt_candle_timeframe_sec):
            cache_candle = {
                "open": coerce_float(candle.get("open")),
                "high": coerce_float(candle.get("high")),
                "low": coerce_float(candle.get("low")),
                "close": coerce_float(candle.get("close")),
                "volume": coerce_float(candle.get("volume")),
                # Keep candle start timestamp in cache; staleness gating uses `emit_ts` instead.
                "ts": candle_start_ts,
            }
            self._candle_cache.add_candle(symbol, cache_candle)

        candle_count = candle.get("candle_count")
        if candle_count is not None and (timeframe is None or timeframe == self._amt_candle_timeframe_sec):
            try:
                self._latest_candle_count[symbol] = int(candle_count)
            except (TypeError, ValueError):
                pass
        elif self._candle_cache is not None and (timeframe is None or timeframe == self._amt_candle_timeframe_sec):
            self._latest_candle_count[symbol] = self._candle_cache.get_candle_count(symbol)
        if emit_ts is not None:
            # `_latest_candle_ts` is used for feed-health staleness gating. This should track
            # the freshest candle event regardless of timeframe to avoid false stale states
            # when AMT timeframe differs from emitted candle timeframe.
            self._latest_candle_ts[symbol] = emit_ts
        self._update_ema(symbol, candle)
        self._update_indicators(symbol, candle)

    async def _flush_orderbook_tasks(self) -> None:
        if not self._orderbook_tasks:
            return
        tasks = list(self._orderbook_tasks)
        self._orderbook_tasks.clear()
        for task in tasks:
            await task

    async def _build_snapshot(self, symbol: str, tick: dict) -> Optional[dict]:
        bid = coerce_float(tick.get("bid"))
        ask = coerce_float(tick.get("ask"))
        last = coerce_float(tick.get("last"))
        timestamp = coerce_float(tick.get("timestamp"))
        if timestamp is None:
            log_warning("feature_tick_missing_timestamp", symbol=symbol)
            return None
        recv_ts = timestamp
        ts_canon_us = tick.get("ts_canon_us")
        try:
            ts_canon_us = int(ts_canon_us) if ts_canon_us is not None else None
        except (TypeError, ValueError):
            ts_canon_us = None
        if ts_canon_us is None:
            ts_canon_us = sec_to_us(timestamp)
        
        # Cache bid/ask from orderbook_feed ticks
        source = tick.get("source")
        if source == "orderbook_feed" and bid is not None and ask is not None:
            self._bid_ask_cache[symbol] = {"bid": bid, "ask": ask, "timestamp": timestamp}
        
        # Use cached bid/ask if tick doesn't have them
        if (bid is None or ask is None) and symbol in self._bid_ask_cache:
            cached = self._bid_ask_cache[symbol]
            # Only use cache if it's not too old (< 10 seconds)
            if timestamp - cached.get("timestamp", 0) < 10.0:
                bid = bid if bid is not None else cached.get("bid")
                ask = ask if ask is not None else cached.get("ask")
        
        price = last
        if price is None and bid is not None and ask is not None:
            price = (bid + ask) / 2.0
        spread = None
        spread_bps = None
        if bid is not None and ask is not None and price:
            # Validate bid < ask (not a crossed book)
            if ask > bid:
                spread = (ask - bid) / price
                spread_bps = spread * 10000.0
                # Clamp to reasonable range [0.1, 100.0] bps
                spread_bps = max(0.1, min(100.0, spread_bps))
            else:
                # Crossed book - use default spread
                spread_bps = 5.0
                spread = spread_bps / 10000.0
        best_bid = bid if bid is not None else None
        best_ask = ask if ask is not None else None
        self._last_ticks[symbol] = tick
        # Use receive time for history to keep 1s/5s/30s windows consistent
        self._update_history(symbol, ts_canon_us, price)
        price_change_1s = _price_change(self._price_history.get(symbol), 1.0, price, ts_canon_us)
        price_change_5s = _price_change(self._price_history.get(symbol), 5.0, price, ts_canon_us)
        price_change_30s = _price_change(self._price_history.get(symbol), 30.0, price, ts_canon_us)
        price_change_5m = _price_change(self._price_history.get(symbol), 300.0, price, ts_canon_us)
        price_change_1m = _price_change(self._price_history.get(symbol), 60.0, price, ts_canon_us)
        price_change_1h = _price_change(self._price_history.get(symbol), 3600.0, price, ts_canon_us)
        if price_change_5m == 0.0:
            price_change_5m = _candle_price_change(
                self._candle_history.get(symbol),
                300.0,
                price,
                self._amt_candle_timeframe_sec,
            )
        volatility = _volatility(self._return_history.get(symbol))
        volatility_regime = _volatility_regime(volatility)
        ema_fast, ema_slow = _ema_values(self._ema_state.get(symbol))
        atr = _indicator_value(self._atr_state.get(symbol))
        vwap = _indicator_value(self._vwap_state.get(symbol))
        atr_baseline = _indicator_value(self._atr_baseline_state.get(symbol)) or atr or volatility
        atr_ratio = (atr / atr_baseline) if (atr is not None and atr_baseline) else 1.0
        trend_direction = _trend_direction(price_change_30s, price_change_5m, ema_fast, ema_slow)
        trend_strength = _trend_strength(ema_fast, ema_slow, price)
        bid_depth, ask_depth, imbalance = _orderbook_metrics(tick, getattr(self, "orderbook_cache", None), symbol)
        trade_stats = self.trade_cache.snapshot(symbol, now_ts_us=ts_canon_us) if self.trade_cache else {}
        trade_vwap = coerce_float(trade_stats.get("vwap"))
        trade_poc = coerce_float(trade_stats.get("point_of_control"))
        trade_val = coerce_float(trade_stats.get("value_area_low"))
        trade_vah = coerce_float(trade_stats.get("value_area_high"))
        trades_per_second = coerce_float(trade_stats.get("trades_per_second"))
        orderflow_imbalance = coerce_float(trade_stats.get("orderflow_imbalance"))
        buy_volume = coerce_float(trade_stats.get("buy_volume"))
        sell_volume = coerce_float(trade_stats.get("sell_volume"))
        
        # Compute multi-timeframe orderflow metrics
        imb_1s, imb_5s, imb_30s, orderflow_persistence = self._get_multi_timeframe_orderflow(
            symbol, ts_canon_us, orderflow_imbalance
        )
        if vwap is None:
            vwap = trade_vwap
        position_in_value = _position_in_value(price, trade_val, trade_vah)
        distance_to_val = _distance_abs(price, trade_val)
        distance_to_vah = _distance_abs(price, trade_vah)
        distance_to_poc = _distance_signed(price, trade_poc)
        mid_price = None
        if bid is not None and ask is not None and ask > bid:
            mid_price = (bid + ask) / 2.0
        if mid_price is None:
            mid_price = price
        distance_to_val_bps = _distance_abs_bps(price, trade_val, mid_price)
        distance_to_vah_bps = _distance_abs_bps(price, trade_vah, mid_price)
        distance_to_poc_bps = _distance_signed_bps(price, trade_poc, mid_price)
        session_label = _session_label(timestamp)
        is_market_hours = _is_market_hours(
            timestamp,
            self.config.trading_session_start_hour_utc,
            self.config.trading_session_end_hour_utc,
        )
        quality = {}
        prediction_status = None
        if self.quality_tracker:
            quality = await self.quality_tracker.snapshot(symbol, now_ts=timestamp)
        candle_age = None
        candle_sync_state = "unknown"
        candle_ts = self._latest_candle_ts.get(symbol)
        if candle_ts is None and self._candle_cache is not None:
            recent = self._candle_cache.get_recent_candles(symbol, count=1)
            if recent:
                # Candle cache stores candle start timestamps. For staleness gating we want an
                # approximate "latest candle time" closer to now, so use candle end time.
                candle_ts = coerce_float(recent[-1].get("ts"))
                if candle_ts is not None:
                    candle_ts = candle_ts + float(self._amt_candle_timeframe_sec)
                self._latest_candle_ts[symbol] = candle_ts
                self._latest_candle_count[symbol] = self._candle_cache.get_candle_count(symbol)
        if candle_ts is not None:
            candle_age = max(0.0, timestamp - candle_ts)
            candle_sync_state = "stale" if candle_age > self.config.candle_stale_sec else "synced"

        if quality:
            flags = set(quality.get("flags") or [])
            blocked_reason = None
            if quality.get("status") == "stale":
                blocked_reason = "stale_data"
            elif self.config.gate_on_orderbook_gap and {"orderbook_gap", "out_of_order"}.intersection(flags):
                blocked_reason = "orderbook_gap"
            elif self.config.gate_on_orderbook_stale and "orderbook_stale" in flags:
                blocked_reason = "orderbook_stale"
            elif self.config.gate_on_trade_stale and "trade_stale" in flags:
                blocked_reason = "trade_stale"
            elif self.config.gate_on_candle_stale and candle_sync_state == "stale":
                blocked_reason = "candle_stale"
            if blocked_reason:
                prediction_status = {
                    "status": "suppressed",
                    "reason": blocked_reason,
                    "quality_score": quality.get("quality_score"),
                    "flags": list(flags) or None,
                    "orderbook_sync_state": quality.get("orderbook_sync_state", "unknown"),
                    "trade_sync_state": quality.get("trade_sync_state", "unknown"),
                    "candle_sync_state": candle_sync_state,
                }
                if self.telemetry and self.telemetry_context:
                    await self.telemetry.publish_guardrail(
                        self.telemetry_context,
                        {
                            "type": "prediction_blocked",
                            "symbol": symbol,
                            "reason": blocked_reason,
                        },
                    )
                # NOTE: Warmup status is written by decision_worker only to avoid conflicts
                # The decision_worker has authoritative candle counts and warmup tracking
                pass
        trade_stale = quality and "trade_stale" in (quality.get("flags") or [])
        if (bid_depth or ask_depth) and self.telemetry and self.telemetry_context:
            self._orderbook_tick_count[symbol] = self._orderbook_tick_count.get(symbol, 0) + 1
            if _should_emit_orderbook(
                symbol,
                timestamp,
                self._orderbook_last_emit,
                self._orderbook_tick_count,
                self.config.orderbook_emit_interval_ms,
                self.config.orderbook_emit_min_ticks,
            ):
                self._emit_orderbook_snapshot(symbol, timestamp, bid_depth, ask_depth, imbalance)
        market_regime = "unknown"
        regime_confidence = 0.0
        regime_family = "unknown"
        try:
            from quantgambit.deeptrader_core.layer1_predictions.regime_classifier import classify_regime

            if spread_bps is not None and trend_strength is not None:
                market_regime, regime_confidence = classify_regime(
                    _rotation_factor(price_change_5s, price_change_30s),
                    atr_ratio,
                    trend_strength,
                    spread_bps,
                )
                # Use unified regime_family derivation for parity with backtest
                regime_family = _derive_regime_family_from_context(
                    market_regime=market_regime,
                    trend_strength=trend_strength,
                    spread_bps=spread_bps,
                    bid_depth_usd=bid_depth,
                    ask_depth_usd=ask_depth,
                )
        except Exception:
            market_regime = "unknown"
            regime_confidence = 0.0
            regime_family = "unknown"
        features = {
            "symbol": symbol,
            "timestamp": timestamp,
            "price": price,
            "bid": bid,
            "ask": ask,
            "best_bid": best_bid,
            "best_ask": best_ask,
            "spread": spread,
            "spread_bps": spread_bps,
            "price_change_1s": price_change_1s,
            "price_change_5s": price_change_5s,
            "price_change_30s": price_change_30s,
            "price_change_5m": price_change_5m,
            "price_change_1m": price_change_1m,
            "price_change_1h": price_change_1h,
            "rotation_factor": _rotation_factor(price_change_5s, price_change_30s),
            "position_in_value": position_in_value,
            "distance_to_val": distance_to_val,
            "distance_to_vah": distance_to_vah,
            "distance_to_poc": distance_to_poc,
            "distance_to_val_bps": distance_to_val_bps,
            "distance_to_vah_bps": distance_to_vah_bps,
            "distance_to_poc_bps": distance_to_poc_bps,
            "ema_fast_15m": ema_fast,
            "ema_slow_15m": ema_slow,
            "ema_spread_pct": trend_strength,
            "trend_strength": trend_strength,
            "atr_5m": atr or volatility,
            "atr_5m_baseline": atr_baseline or 0.0,
            "atr_ratio": atr_ratio,
            "vwap": vwap,
            "point_of_control": trade_poc,
            "value_area_low": trade_val,
            "value_area_high": trade_vah,
            "trades_per_second": trades_per_second or 0.0,
            "orderflow_imbalance": orderflow_imbalance,
            # Multi-timeframe orderflow (for pre-trade gating)
            "imb_1s": imb_1s,
            "imb_5s": imb_5s,
            "imb_30s": imb_30s,
            "orderflow_persistence_sec": orderflow_persistence,
            "buy_volume": buy_volume or 0.0,
            "sell_volume": sell_volume or 0.0,
            "bid_depth_usd": bid_depth,
            "ask_depth_usd": ask_depth,
            "orderbook_imbalance": imbalance,
            "market_regime": market_regime,
            "regime_confidence": regime_confidence,
            "regime_family": regime_family,
        }
        trade_age = quality.get("trade_age_sec") if quality else None
        trade_sync_state = "unknown" if (quality and trade_age is None) else ("stale" if trade_stale else ("synced" if quality else "unknown"))
        market_context = {
            "symbol": symbol,
            "timestamp": timestamp,
            "price": price,
            "spread": spread,
            "spread_bps": spread_bps,
            "best_bid": best_bid,
            "best_ask": best_ask,
            "trend_direction": trend_direction,
            "trend_strength": trend_strength,
            "volatility_regime": volatility_regime,
            "market_regime": market_regime,
            "regime_confidence": regime_confidence,
            "regime_family": regime_family,
            "position_in_value": position_in_value,
            "distance_to_val": distance_to_val,
            "distance_to_vah": distance_to_vah,
            "distance_to_poc": distance_to_poc,
            "distance_to_val_bps": distance_to_val_bps,
            "distance_to_vah_bps": distance_to_vah_bps,
            "distance_to_poc_bps": distance_to_poc_bps,
            "point_of_control": trade_poc,
            "value_area_low": trade_val,
            "value_area_high": trade_vah,
            "trades_per_second": trades_per_second or 0.0,
            "orderflow_imbalance": orderflow_imbalance,
            # Multi-timeframe orderflow (for pre-trade gating)
            "imb_1s": imb_1s,
            "imb_5s": imb_5s,
            "imb_30s": imb_30s,
            "orderflow_persistence_sec": orderflow_persistence,
            "risk_mode": "normal",
            "session": session_label,
            "is_market_hours": is_market_hours,
            "data_completeness": _data_completeness(price, spread_bps, ema_fast, ema_slow),
            "price_change_1m": price_change_1m,
            "price_change_1h": price_change_1h,
            "price_change_5m": price_change_5m,
            "data_quality_score": quality.get("quality_score") if quality else None,
            "data_quality_status": quality.get("status") if quality else None,
            "data_quality_flags": quality.get("flags") if quality else None,
            "orderbook_sync_state": quality.get("orderbook_sync_state", "unknown") if quality else "unknown",
            "trade_sync_state": trade_sync_state,
            "candle_sync_state": candle_sync_state,
            "candle_age_sec": candle_age,
            "vwap": vwap,
            "candle_count": self._latest_candle_count.get(symbol, 0),
            "bid_depth_usd": bid_depth,
            "ask_depth_usd": ask_depth,
            "orderbook_imbalance": imbalance,
            # Per-feed staleness tracking (seconds since last update)
            "feed_staleness": self._get_feed_staleness(symbol, timestamp),
            "feed_timestamps": self._feed_timestamps.get(symbol, {}),
            # Per-symbol calibrated thresholds
            "calibrated_thresholds": (
                self._symbol_calibrator.get_thresholds(symbol, now_ts=timestamp).to_dict()
                if self._symbol_calibrator else None
            ),
            # Exchange timestamp (cts) based latency data for DataReadinessGate
            # book_cts_ms: orderbook matching engine timestamp (ms)
            # trade_ts_ms: trade T timestamp (ms)
            # *_recv_ms: when we received the update (ms)
            **self._get_latency_data(symbol),
        }
        ai_context = get_symbol_context(symbol)
        global_ai_context = get_global_context()
        if ai_context:
            sentiment_payload = ai_context.get("sentiment") if isinstance(ai_context, dict) else None
            if isinstance(sentiment_payload, dict):
                market_context["sentiment_score"] = sentiment_payload.get(
                    "combined_sentiment",
                    sentiment_payload.get("score"),
                )
            ai_context = dict(ai_context)
            if global_ai_context:
                ai_context["global_context"] = global_ai_context
            market_context["context"] = ai_context
            features["context"] = ai_context
        # Inject observed slippage (EMA) from recent fills if available
        slip_key = f"quantgambit:{self.tenant_id}:{self.bot_id}:slippage:{symbol}"
        slippage_stats = await self.snapshot_reader.read(slip_key)
        if slippage_stats and slippage_stats.get("ema_bps") is not None:
            try:
                observed_slip = float(slippage_stats.get("ema_bps"))
                if observed_slip > 0:
                    market_context["observed_slippage_bps"] = observed_slip
                    features["observed_slippage_bps"] = observed_slip
            except (TypeError, ValueError):
                pass
        self._log_feed_latency(symbol, timestamp, market_context, now_ts=timestamp)
        forced_profile = os.getenv("FORCE_PROFILE_ID")
        if forced_profile:
            market_context["profile_id"] = forced_profile
        if trade_stale:
            market_context["trade_feed_stale"] = True
            market_context["risk_mode"] = "conservative"
            market_context["risk_scale"] = self.config.degraded_risk_scale
            market_context["ui_banner"] = {
                "type": "trade_feed_stale",
                "level": "warning",
                "message": "Trade feed stale. Conservative mode enabled.",
            }
        prediction = None
        prediction_status = None
        # If quality gating already determined suppression, propagate to market_context
        if prediction_status:
            market_context["prediction_blocked"] = prediction_status.get("reason")
        if await self._is_drift_blocked(timestamp, symbol=symbol):
            block_reason = self._drift_block_reason or "drift_detected"
            market_context["prediction_blocked"] = block_reason
            market_context["drift_status"] = block_reason
            prediction_status = {
                "status": "suppressed",
                "reason": block_reason,
                "orderbook_sync_state": market_context["orderbook_sync_state"],
                "trade_sync_state": market_context["trade_sync_state"],
                "quality_score": market_context.get("data_quality_score"),
            }
            if self.telemetry and self.telemetry_context:
                await self.telemetry.publish_guardrail(
                    self.telemetry_context,
                    {"type": "prediction_blocked", "symbol": symbol, "reason": block_reason},
                )
        quality_status = market_context.get("data_quality_status")
        quality_score = market_context.get("data_quality_score")
        quality_flags = set(quality.get("flags") or []) if quality else set()
        if prediction_status is None and quality_flags:
            if self.config.gate_on_orderbook_gap and {"orderbook_gap", "out_of_order"}.intersection(quality_flags):
                prediction_status = {
                    "status": "suppressed",
                    "reason": "orderbook_gap",
                    "quality_score": quality_score,
                    "flags": list(quality_flags),
                    "orderbook_sync_state": market_context["orderbook_sync_state"],
                    "trade_sync_state": market_context["trade_sync_state"],
                    "candle_sync_state": candle_sync_state,
                }
            if self.config.gate_on_trade_stale and "trade_stale" in quality_flags and prediction_status is None:
                prediction_status = {
                    "status": "suppressed",
                    "reason": "trade_stale",
                    "quality_score": quality_score,
                    "flags": list(quality_flags),
                    "orderbook_sync_state": market_context["orderbook_sync_state"],
                    "trade_sync_state": market_context["trade_sync_state"],
                    "candle_sync_state": candle_sync_state,
                }
        if prediction_status is None and self.config.gate_on_candle_stale and candle_sync_state == "stale":
            prediction_status = {
                "status": "suppressed",
                "reason": "candle_stale",
                "quality_score": quality_score,
                "flags": list(quality_flags) if quality_flags else None,
                "orderbook_sync_state": market_context["orderbook_sync_state"],
                "trade_sync_state": market_context["trade_sync_state"],
                "candle_sync_state": candle_sync_state,
            }
        if quality_status == "stale":
            market_context["prediction_blocked"] = "stale_data"
            prediction_status = prediction_status or {
                "status": "suppressed",
                "reason": "stale_data",
                "quality_score": quality_score,
                "orderbook_sync_state": market_context["orderbook_sync_state"],
                "trade_sync_state": market_context["trade_sync_state"],
            }
        elif quality_score is not None and quality_score < self.config.min_quality_for_prediction:
            market_context["prediction_blocked"] = "low_quality"
            prediction_status = prediction_status or {
                "status": "suppressed",
                "reason": "low_quality",
                "quality_score": quality_score,
                "orderbook_sync_state": market_context["orderbook_sync_state"],
                "trade_sync_state": market_context["trade_sync_state"],
            }
        if prediction_status is None:
            prediction = self._build_prediction(features, market_context, timestamp)
            if prediction is not None:
                score_gate_result = await self._evaluate_score_gate(
                    now_ts=timestamp,
                    symbol=symbol,
                    prediction=prediction,
                )
                gate_status = str(score_gate_result.get("status") or "").strip().lower()
                if gate_status:
                    market_context["prediction_score_gate_status"] = gate_status
                global_status = str(score_gate_result.get("global_status") or "").strip().lower()
                if global_status:
                    market_context["prediction_score_gate_global_status"] = global_status
                provider = str(score_gate_result.get("provider") or "").strip().lower()
                if provider:
                    market_context["prediction_score_gate_provider"] = provider
                score_gate_metrics = score_gate_result.get("metrics")
                if isinstance(score_gate_metrics, dict):
                    market_context["prediction_score_gate_metrics"] = score_gate_metrics
                if score_gate_result.get("blocked"):
                    reason = score_gate_result.get("reason") or "prediction_score_gate"
                    mode = self._score_gate_mode
                    if mode == "fallback_heuristic":
                        fallback_prediction = self._build_fallback_prediction(
                            features, market_context, timestamp, reason=reason
                        )
                        if fallback_prediction is not None:
                            prediction = fallback_prediction
                            market_context["prediction_score_gate_status"] = "fallback"
                            market_context["prediction_score_gate_reason"] = reason
                        else:
                            prediction = None
                            market_context["prediction_blocked"] = reason
                            prediction_status = {
                                "status": "suppressed",
                                "reason": reason,
                                "quality_score": quality_score,
                                "orderbook_sync_state": market_context["orderbook_sync_state"],
                                "trade_sync_state": market_context["trade_sync_state"],
                            }
                    else:
                        prediction = None
                        market_context["prediction_blocked"] = reason
                        market_context["prediction_score_gate_status"] = "blocked"
                        market_context["prediction_score_gate_reason"] = reason
                        prediction_status = {
                            "status": "suppressed",
                            "reason": reason,
                            "quality_score": quality_score,
                            "orderbook_sync_state": market_context["orderbook_sync_state"],
                            "trade_sync_state": market_context["trade_sync_state"],
                        }
        prediction_shadow = None
        shadow_allowed_when_suppressed = bool(
            prediction_status
            and str(prediction_status.get("status") or "").strip().lower() == "suppressed"
            and str(prediction_status.get("reason") or "").strip().lower().startswith("score_")
        )
        if prediction_status is None or shadow_allowed_when_suppressed:
            # Keep shadow predictions flowing during score-gate suppression so
            # outcome audits can continue evaluating model quality.
            prediction_shadow = self._build_shadow_prediction(features, market_context, timestamp)
        invalid_reasons = set()
        if not timestamp or timestamp <= 0:
            invalid_reasons.add("timestamp_missing")
        if quality_status == "stale":
            invalid_reasons.add("quality_stale")
        if quality_score is not None and quality_score < self.config.min_quality_for_prediction:
            invalid_reasons.add("quality_low")
        if self.config.gate_on_candle_stale and candle_sync_state == "stale":
            invalid_reasons.add("candle_stale")
        if prediction_status and prediction_status.get("status") == "suppressed":
            reason = prediction_status.get("reason") or "prediction_suppressed"
            invalid_reasons.add(reason)
        snapshot_valid = not invalid_reasons
        snapshot = {
            "symbol": symbol,
            "timestamp": timestamp,
            "features": features,
            "market_context": market_context,
            "prediction": prediction,
            "prediction_shadow": prediction_shadow,
            "valid": snapshot_valid,
            "invalid_reasons": sorted(invalid_reasons) if invalid_reasons else None,
        }
        if prediction_status:
            snapshot["prediction_status"] = prediction_status
        return snapshot

    async def _is_drift_blocked(self, now_ts: float, symbol: Optional[str] = None) -> bool:
        if not self.drift_block_enabled or not self.drift_snapshot_key:
            return False
        now = now_ts
        if now - self._drift_last_checked < self.config.drift_check_interval_sec:
            return self._drift_blocked
        self._drift_last_checked = now
        payload = await self.snapshot_reader.read(self.drift_snapshot_key)
        if not payload:
            self._drift_block_reason = "drift_snapshot_missing" if self._drift_fail_closed else None
            self._drift_blocked = bool(self._drift_fail_closed)
            return self._drift_blocked
        status = payload.get("status")
        updated_at = payload.get("timestamp") or payload.get("ts") or payload.get("updated_at")
        try:
            updated_at = float(updated_at) if updated_at is not None else None
        except (TypeError, ValueError):
            updated_at = None
        if updated_at and updated_at > 1e12:
            updated_at = updated_at / 1_000_000 if updated_at > 1e15 else updated_at / 1000.0
        if updated_at and (now - updated_at) > self._drift_max_age_sec:
            self._drift_block_reason = "drift_snapshot_stale" if self._drift_fail_closed else None
            self._drift_blocked = bool(self._drift_fail_closed)
            return self._drift_blocked
        symbol_status = None
        symbols_payload = payload.get("symbols")
        if isinstance(symbols_payload, dict) and symbol:
            symbol_status = symbols_payload.get(symbol) or symbols_payload.get(symbol.upper())
        if isinstance(symbol_status, dict):
            symbol_state = str(symbol_status.get("status") or "").lower()
            if symbol_state in {"drift", "blocked"}:
                self._drift_block_reason = "drift_detected"
                self._drift_blocked = True
                return True
            if symbol_state == "stale":
                self._drift_block_reason = "drift_snapshot_stale"
                self._drift_blocked = bool(self._drift_fail_closed)
                return self._drift_blocked
        if status == "drift":
            self._drift_block_reason = "drift_detected"
            self._drift_blocked = True
            return True
        self._drift_block_reason = None
        self._drift_blocked = False
        return self._drift_blocked

    async def _evaluate_score_gate(
        self,
        now_ts: float,
        symbol: str,
        prediction: Optional[dict],
    ) -> dict:
        result = {"blocked": False, "reason": None, "status": "unknown", "global_status": None, "provider": None}
        if not self.score_gate_enabled or not prediction:
            return result
        source = str(prediction.get("source") or "").lower()
        if "onnx" not in source:
            return result
        if not self.score_snapshot_key:
            if self._score_gate_fail_closed:
                return {"blocked": True, "reason": "score_snapshot_key_missing"}
            return result
        now = now_ts
        if (now - self._score_gate_last_checked) >= self._score_gate_interval_sec:
            self._score_gate_last_checked = now
            self._score_gate_payload = await self.snapshot_reader.read(self.score_snapshot_key)

        payload = self._score_gate_payload
        if not payload:
            if self._score_gate_fail_closed:
                return {"blocked": True, "reason": "score_snapshot_missing"}
            return result
        result["global_status"] = str(payload.get("status") or "").strip().lower() or None
        result["provider"] = str(payload.get("provider") or "").strip().lower() or None

        updated_at = payload.get("timestamp") or payload.get("updated_at")
        try:
            updated_at = float(updated_at) if updated_at is not None else None
        except (TypeError, ValueError):
            updated_at = None
        if updated_at and updated_at > 1e12:
            updated_at = updated_at / 1_000_000 if updated_at > 1e15 else updated_at / 1000.0
        if updated_at and (now - updated_at) > self._score_gate_max_age_sec:
            if self._score_gate_fail_closed:
                return {"blocked": True, "reason": "score_snapshot_stale"}
            return result

        symbol_payload = {}
        symbols = payload.get("symbols")
        if isinstance(symbols, dict):
            symbol_payload = symbols.get(symbol) or symbols.get(symbol.upper()) or {}
        if not isinstance(symbol_payload, dict):
            symbol_payload = {}
        if not symbol_payload:
            if self._score_gate_fail_closed:
                return {"blocked": True, "reason": "score_symbol_missing"}
            return result

        status = str(symbol_payload.get("status") or "").lower()
        result["status"] = status or "unknown"
        if status == "drift":
            return {"blocked": True, "reason": "score_status_drift"}
        if status in {"blocked", "insufficient"}:
            return {"blocked": True, "reason": f"score_status_{status}"}

        def _as_ratio(raw: object) -> Optional[float]:
            value = coerce_float(raw)
            if value is None:
                return None
            if value > 1.0:
                value = value / 100.0
            return max(0.0, min(1.0, float(value)))

        pred_direction = str(prediction.get("direction") or "").strip().lower()
        pred_side = None
        if pred_direction in {"up", "long", "buy"}:
            pred_side = "long"
        elif pred_direction in {"down", "short", "sell"}:
            pred_side = "short"

        def _blocked(reason: str, metrics: dict) -> dict:
            return {"blocked": True, "reason": reason, "metrics": metrics}

        samples = int(symbol_payload.get("samples") or 0)
        ml_score = coerce_float(symbol_payload.get("ml_score"))
        exact_acc = _as_ratio(symbol_payload.get("exact_accuracy"))
        directional_acc = _as_ratio(
            symbol_payload.get("directional_accuracy")
            or symbol_payload.get("directional_accuracy_nonflat")
            or symbol_payload.get("directional_accuracy_nonflat_pct")
            or symbol_payload.get("directional_accuracy_pct")
        )
        long_directional_acc = _as_ratio(
            symbol_payload.get("directional_accuracy_long")
            or symbol_payload.get("long_directional_accuracy")
            or symbol_payload.get("long_accuracy")
        )
        short_directional_acc = _as_ratio(
            symbol_payload.get("directional_accuracy_short")
            or symbol_payload.get("short_directional_accuracy")
            or symbol_payload.get("short_accuracy")
        )
        ece = _as_ratio(symbol_payload.get("ece_top1"))
        long_ece = _as_ratio(symbol_payload.get("ece_top1_long") or symbol_payload.get("long_ece_top1"))
        short_ece = _as_ratio(symbol_payload.get("ece_top1_short") or symbol_payload.get("short_ece_top1"))
        metrics = {
            "status": status,
            "samples": samples,
            "ml_score": ml_score,
            "exact_accuracy": exact_acc,
            "directional_accuracy": directional_acc,
            "directional_accuracy_long": long_directional_acc,
            "directional_accuracy_short": short_directional_acc,
            "ece_top1": ece,
            "ece_top1_long": long_ece,
            "ece_top1_short": short_ece,
            "predicted_side": pred_side,
        }
        if exact_acc is not None and (exact_acc < 0.0 or exact_acc > 1.0):
            log_warning(
                "score_gate_invalid_exact_accuracy",
                symbol=symbol,
                value=exact_acc,
                snapshot_key=self.score_snapshot_key,
            )
            if self._score_gate_fail_closed:
                return _blocked("score_invalid_exact_accuracy", metrics)
            return result
        if ece is not None and (ece < 0.0 or ece > 1.0):
            log_warning(
                "score_gate_invalid_ece",
                symbol=symbol,
                value=ece,
                snapshot_key=self.score_snapshot_key,
            )
            if self._score_gate_fail_closed:
                return _blocked("score_invalid_ece", metrics)
            return result

        if samples < self._score_gate_min_samples:
            return _blocked("score_low_samples", metrics)
        if ml_score is not None and ml_score < self._score_gate_min_ml_score:
            return _blocked("score_low_ml_score", metrics)
        if exact_acc is not None and exact_acc < self._score_gate_min_exact_acc:
            return _blocked("score_low_accuracy", metrics)
        if directional_acc is not None and directional_acc < self._score_gate_min_directional_acc:
            return _blocked("score_low_directional_accuracy", metrics)
        if pred_side == "long":
            long_acc_threshold = (
                self._score_gate_min_directional_acc_long
                if self._score_gate_min_directional_acc_long is not None
                else self._score_gate_min_directional_acc
            )
            if long_directional_acc is not None and long_directional_acc < float(long_acc_threshold):
                return _blocked("score_low_directional_accuracy_long", metrics)
            max_long_ece = (
                self._score_gate_max_ece_long
                if self._score_gate_max_ece_long is not None
                else self._score_gate_max_ece
            )
            if long_ece is not None and long_ece > float(max_long_ece):
                return _blocked("score_high_ece_long", metrics)
        if pred_side == "short":
            short_acc_threshold = (
                self._score_gate_min_directional_acc_short
                if self._score_gate_min_directional_acc_short is not None
                else self._score_gate_min_directional_acc
            )
            if short_directional_acc is not None and short_directional_acc < float(short_acc_threshold):
                return _blocked("score_low_directional_accuracy_short", metrics)
            max_short_ece = (
                self._score_gate_max_ece_short
                if self._score_gate_max_ece_short is not None
                else self._score_gate_max_ece
            )
            if short_ece is not None and short_ece > float(max_short_ece):
                return _blocked("score_high_ece_short", metrics)
        if ece is not None and ece > self._score_gate_max_ece:
            return _blocked("score_high_ece", metrics)
        result["metrics"] = metrics
        if status:
            result["status"] = status
        return result

    def _build_fallback_prediction(
        self,
        features: dict,
        market_context: dict,
        timestamp: float,
        reason: str,
    ) -> Optional[dict]:
        prediction = self._fallback_prediction_provider.build_prediction(features, market_context, timestamp)
        if not prediction:
            return None
        prediction["score_gate_fallback"] = True
        prediction["score_gate_reason"] = reason
        prediction["score_gate_original_source"] = "onnx_v1"
        self._attach_fallback_p_hat(prediction)
        return prediction

    def _attach_fallback_p_hat(self, prediction: dict) -> None:
        """
        Ensure fallback predictions carry a conservative side-aware p_hat.

        Without this, EVGate defaults to uncalibrated regime constants (e.g. 0.48),
        which can over-reject borderline trades regardless of fallback confidence.
        """
        if prediction.get("p_hat") is not None:
            return
        direction = str(prediction.get("direction") or "").lower()
        if direction not in {"up", "down"}:
            prediction["p_hat"] = 0.5
            prediction["p_hat_source"] = "fallback_heuristic_flat"
            return
        confidence = coerce_float(prediction.get("confidence"))
        if confidence is None:
            p_hat = 0.52
        else:
            confidence = max(0.0, min(1.0, float(confidence)))
            # Conservative shrink toward 0.5 to avoid over-trusting heuristic confidence.
            p_hat = 0.5 + ((confidence - 0.5) * 0.35)
            p_hat = max(0.5, min(0.70, p_hat))
        prediction["p_hat"] = float(round(p_hat, 6))
        prediction["p_hat_source"] = "fallback_heuristic"

    def _build_prediction(self, features: dict, market_context: dict, timestamp: float) -> Optional[dict]:
        if not self.prediction_provider:
            return None
        onnx_failure_reason: Optional[str] = None
        try:
            prediction = self.prediction_provider.build_prediction(features, market_context, timestamp)
        except Exception as exc:
            prediction = None
            onnx_failure_reason = "provider_exception"
            log_warning("feature_worker_prediction_provider_failed", error=str(exc))
        if not prediction:
            if isinstance(self.prediction_provider, OnnxPredictionProvider):
                fallback = self._fallback_prediction_provider.build_prediction(features, market_context, timestamp)
                if fallback:
                    fallback["onnx_failure_fallback"] = True
                    fallback["onnx_failure_reason"] = onnx_failure_reason or "prediction_unavailable"
                    self._attach_fallback_p_hat(fallback)
                    prediction = fallback
                else:
                    return None
            else:
                return None
        confidence = coerce_float(prediction.get("confidence"))
        if confidence is not None:
            prediction["confidence_raw"] = confidence
            calibrated = (confidence * self.prediction_confidence_scale) + self.prediction_confidence_bias
            prediction["confidence"] = max(0.0, min(1.0, calibrated))
        if bool(prediction.get("reject")) and not prediction.get("reason"):
            if prediction.get("score_gate_fallback"):
                prediction["reason"] = str(prediction.get("score_gate_reason") or "score_gate_blocked")
            elif prediction.get("onnx_failure_fallback"):
                prediction["reason"] = str(prediction.get("onnx_failure_reason") or "onnx_failure")
            else:
                prediction["reason"] = "provider_reject_unspecified"
        return prediction

    def _build_shadow_prediction(
        self, features: dict, market_context: dict, timestamp: float
    ) -> Optional[dict]:
        """Compute a secondary prediction for shadow evaluation.

        This must never affect decisions; it is emitted only for comparison/analysis.
        """
        if not self.shadow_prediction_provider:
            return None
        prediction = self.shadow_prediction_provider.build_prediction(features, market_context, timestamp)
        if not prediction:
            return None
        # Do not apply confidence scale/bias here; shadow should reflect raw provider outputs.
        return prediction

    async def _write_warmup_status(
        self,
        symbol: str,
        ready: bool,
        reasons: list,
        quality_score: Optional[float],
        quality_flags: Optional[list],
        orderbook_sync_state: str,
        trade_sync_state: str,
        candle_sync_state: str,
        now_ts: float,
    ) -> None:
        """Write warmup status from feature worker for quality/sync info.
        
        Note: Uses a separate key from decision_worker to avoid overwriting
        the authoritative candle count tracking. The API reads from the
        decision_worker's warmup key for progress/candle counts.
        """
        key = f"quantgambit:{self.tenant_id}:{self.bot_id}:warmup_quality:{symbol}"
        snapshot = {
            "symbol": symbol,
            "ready": ready,
            "reasons": reasons,
            "sample_count": 0,  # Feature worker doesn't track samples like decision worker
            "first_ts": None,
            "latest_ts": now_ts,
            "min_samples": 0,
            "min_age_sec": 0,
            "candle_count": len(self._candle_history.get(symbol) or []),
            "min_candles": 3,  # Default, decision worker may override
            "quality_score": quality_score,
            "orderbook_sync_state": orderbook_sync_state,
            "trade_sync_state": trade_sync_state,
            "candle_sync_state": candle_sync_state,
            "quality_flags": quality_flags,
            "source": "feature_worker",  # Mark source for debugging
        }
        await self.snapshot_writer.write(key, snapshot)

    def _emit_orderbook_snapshot(
        self,
        symbol: str,
        timestamp: float,
        bid_depth: float,
        ask_depth: float,
        imbalance: float,
    ) -> None:
        if not hasattr(self, "telemetry") or self.telemetry is None:
            return
        if not hasattr(self, "telemetry_context") or self.telemetry_context is None:
            return
        payload = {
            "symbol": symbol,
            "timestamp": timestamp,
            "bid_depth_usd": bid_depth,
            "ask_depth_usd": ask_depth,
            "orderbook_imbalance": imbalance,
        }
        self._orderbook_tasks.append(
            self.telemetry.publish_orderbook(ctx=self.telemetry_context, payload=payload)
        )

    def _update_history(self, symbol: str, timestamp_us: int, price: Optional[float]) -> None:
        if price is None:
            return
        history = self._price_history.setdefault(symbol, deque(maxlen=self._price_history_maxlen))
        # Store at 1-second granularity to avoid pruning 5m/1h horizons under high tick rates.
        # Keep the latest price observed within each second.
        ts_us_int = int(timestamp_us)
        bucket_ts_us = (ts_us_int // 1_000_000) * 1_000_000
        if history and history[-1][0] == bucket_ts_us:
            history[-1] = (bucket_ts_us, price)
            return
        history.append((bucket_ts_us, price))
        returns = self._return_history.setdefault(symbol, deque(maxlen=300))
        if len(history) >= 2:
            _, prev_price = history[-2]
            if prev_price:
                returns.append((price - prev_price) / prev_price)

    def _update_ema(self, symbol: str, candle: dict) -> None:
        close = coerce_float(candle.get("close"))
        if close is None:
            return
        state = self._ema_state.setdefault(symbol, {"ema_fast": close, "ema_slow": close})
        state["ema_fast"] = _ema_step(state["ema_fast"], close, period=12)
        state["ema_slow"] = _ema_step(state["ema_slow"], close, period=26)

    def _update_indicators(self, symbol: str, candle: dict) -> None:
        high = coerce_float(candle.get("high"))
        low = coerce_float(candle.get("low"))
        close = coerce_float(candle.get("close"))
        volume = coerce_float(candle.get("volume")) or 0.0
        if high is None or low is None or close is None:
            return
        atr_state = self._atr_state.setdefault(symbol, ATRState(period=14))
        atr_baseline_state = self._atr_baseline_state.setdefault(symbol, ATRState(period=50))
        prev_close = None
        history = self._candle_history.get(symbol)
        if history and len(history) >= 2:
            prev_close = coerce_float(history[-2].get("close"))
        atr_state.update(high, low, prev_close)
        atr_baseline_state.update(high, low, prev_close)
        vwap_state = self._vwap_state.setdefault(symbol, VWAPState())
        session_key = _session_key(
            candle.get("timestamp"),
            self.config.trading_session_start_hour_utc,
        )
        vwap_state.update(close, volume, session_key=session_key)
    
    def _update_orderflow_buffers(
        self, symbol: str, timestamp_us: int, orderflow_imbalance: Optional[float]
    ) -> None:
        """
        Update multi-timeframe orderflow imbalance buffers.
        
        Maintains rolling buffers for 1s, 5s, and 30s imbalance averaging,
        plus sign history for persistence tracking.
        """
        if orderflow_imbalance is None:
            return
        
        # Initialize buffers if needed
        if symbol not in self._imb_buffer_1s:
            self._imb_buffer_1s[symbol] = deque(maxlen=100)
            self._imb_buffer_5s[symbol] = deque(maxlen=500)
            self._imb_buffer_30s[symbol] = deque(maxlen=3000)
            self._imb_sign_history[symbol] = deque(maxlen=300)
        
        # Add to all buffers
        entry = (timestamp_us, orderflow_imbalance)
        self._imb_buffer_1s[symbol].append(entry)
        self._imb_buffer_5s[symbol].append(entry)
        self._imb_buffer_30s[symbol].append(entry)
        
        # Track sign for persistence
        sign = 1 if orderflow_imbalance > 0 else (-1 if orderflow_imbalance < 0 else 0)
        self._imb_sign_history[symbol].append((timestamp_us, sign))
    
    def _compute_rolling_imbalance(
        self, symbol: str, timestamp_us: int, horizon_sec: float
    ) -> float:
        """Compute rolling average imbalance over given horizon."""
        if horizon_sec <= 1.0:
            buffer = self._imb_buffer_1s.get(symbol)
        elif horizon_sec <= 5.0:
            buffer = self._imb_buffer_5s.get(symbol)
        else:
            buffer = self._imb_buffer_30s.get(symbol)
        
        if not buffer:
            return 0.0
        
        horizon_us = int(horizon_sec * 1_000_000)
        values = [imb for ts, imb in buffer if in_window_us(ts, timestamp_us, horizon_us)]
        
        if not values:
            return 0.0
        
        return sum(values) / len(values)
    
    def _compute_orderflow_persistence(self, symbol: str, timestamp_us: int) -> float:
        """
        Compute how long the orderflow imbalance has maintained the same sign.
        
        Returns seconds of persistence (how long imbalance has been same direction).
        """
        history = self._imb_sign_history.get(symbol)
        if not history or len(history) < 2:
            return 0.0
        
        # Get current sign
        current_ts, current_sign = history[-1]
        if current_sign == 0:
            return 0.0
        
        # Walk backwards to find when sign changed
        persistence_start = current_ts
        for ts, sign in reversed(history):
            if sign != current_sign:
                break
            persistence_start = ts
        return max(0.0, (current_ts - persistence_start) / 1_000_000.0)
    
    def _get_multi_timeframe_orderflow(
        self, symbol: str, timestamp_us: int, orderflow_imbalance: Optional[float]
    ) -> tuple[float, float, float, float]:
        """
        Update buffers and return multi-timeframe orderflow metrics.
        
        Returns: (imb_1s, imb_5s, imb_30s, persistence_sec)
        """
        # Update buffers with current value
        self._update_orderflow_buffers(symbol, timestamp_us, orderflow_imbalance)
        
        # Compute rolling averages
        imb_1s = self._compute_rolling_imbalance(symbol, timestamp_us, 1.0)
        imb_5s = self._compute_rolling_imbalance(symbol, timestamp_us, 5.0)
        imb_30s = self._compute_rolling_imbalance(symbol, timestamp_us, 30.0)
        
        # Compute persistence
        persistence = self._compute_orderflow_persistence(symbol, timestamp_us)
        
        return imb_1s, imb_5s, imb_30s, persistence


def _price_change(
    history: Optional[deque],
    horizon_sec: float,
    price: Optional[float],
    now_ts_us: Optional[int],
) -> float:
    if price is None or not history or now_ts_us is None:
        return 0.0
    cutoff_us = int(now_ts_us) - int(horizon_sec * 1_000_000)
    for ts_us, past_price in reversed(history):
        if ts_us <= cutoff_us:
            return (price - past_price) / past_price if past_price else 0.0
    return 0.0


def _candle_price_change(
    candle_history: Optional[deque],
    horizon_sec: float,
    price: Optional[float],
    candle_timeframe_sec: int,
) -> float:
    if price is None or not candle_history or candle_timeframe_sec <= 0:
        return 0.0
    steps = max(1, int(round(horizon_sec / float(candle_timeframe_sec))))
    candles = list(candle_history)
    if len(candles) < steps:
        return 0.0
    reference_candle = candles[-steps]
    past_price = coerce_float(reference_candle.get("close"))
    if past_price in (None, 0.0):
        return 0.0
    return (price - past_price) / past_price


def _volatility(returns: Optional[deque]) -> float:
    if not returns:
        return 0.0
    values = list(returns)
    mean = sum(values) / len(values)
    var = sum((val - mean) ** 2 for val in values) / len(values)
    return math.sqrt(var)


def _regime_family(market_regime: str) -> str:
    """DEPRECATED: Use _derive_regime_family_from_context instead.
    
    This simple mapping doesn't consider trend_strength, liquidity_score,
    or expected_cost_bps. Kept for backward compatibility only.
    """
    if market_regime == "breakout":
        return "trend"
    if market_regime in {"range", "squeeze"}:
        return "mean_revert"
    if market_regime == "chop":
        return "avoid"
    return "unknown"


def _derive_regime_family_from_context(
    market_regime: str,
    trend_strength: float,
    spread_bps: float,
    bid_depth_usd: float,
    ask_depth_usd: float,
) -> str:
    """Derive regime_family using the unified context vector logic.
    
    This ensures parity between live and backtest regime_family derivation.
    Uses the same logic as context_vector._derive_regime_family.
    """
    from quantgambit.deeptrader_core.profiles.context_vector import _derive_regime_family
    
    # Calculate liquidity score
    total_depth = bid_depth_usd + ask_depth_usd
    spread_score = max(0.0, 1.0 - (spread_bps / 50.0)) if spread_bps else 0.5
    depth_score = min(1.0, total_depth / 100000.0) if total_depth > 0 else 0.0
    liquidity_score = 0.5 * spread_score + 0.5 * depth_score
    
    # Calculate expected cost
    if total_depth > 100000:
        slippage = 0.5
    elif total_depth > 50000:
        slippage = 1.0
    else:
        slippage = 2.0
    expected_cost_bps = (spread_bps or 5.0) + 12.0 + slippage
    
    return _derive_regime_family(
        market_regime=market_regime,
        trend_strength=trend_strength or 0.0,
        liquidity_score=liquidity_score,
        expected_cost_bps=expected_cost_bps,
        )


def _normalize_scoped_snapshot_key(candidate: str, expected: str, snapshot_type: str) -> str:
    raw = str(candidate or "").strip()
    if not raw:
        return expected
    if raw == expected:
        return raw
    expected_parts = expected.split(":")
    candidate_parts = raw.split(":")
    if len(candidate_parts) >= 5 and len(expected_parts) >= 5:
        same_suffix = candidate_parts[-3:] == expected_parts[-3:]
        same_scope = candidate_parts[1:3] == expected_parts[1:3]
        if same_suffix and same_scope:
            return raw
    log_warning(
        "feature_worker_ignoring_foreign_snapshot_key",
        snapshot_type=snapshot_type,
        candidate=raw,
        expected=expected,
    )
    return expected


def _volatility_regime(volatility: float) -> str:
    if volatility <= 0:
        return "unknown"
    if volatility < 0.001:
        return "low"
    if volatility < 0.003:
        return "normal"
    return "high"


def _trend_direction(change_30s: float, change_5m: float, ema_fast: Optional[float], ema_slow: Optional[float]) -> str:
    if ema_fast is not None and ema_slow is not None:
        if ema_fast > ema_slow * 1.0005:
            return "up"
        if ema_fast < ema_slow * 0.9995:
            return "down"
    change = change_5m if abs(change_5m) >= abs(change_30s) else change_30s
    if change > 0.001:
        return "up"
    if change < -0.001:
        return "down"
    return "flat"


def _trend_strength(ema_fast: Optional[float], ema_slow: Optional[float], price: Optional[float]) -> float:
    if ema_fast is None or ema_slow is None or not price:
        return 0.0
    return abs(ema_fast - ema_slow) / price


def _rotation_factor(change_5s: float, change_30s: float) -> float:
    if change_30s == 0:
        return change_5s * 10000.0
    return (change_5s / change_30s) if change_30s else 0.0


def _data_completeness(
    price: Optional[float],
    spread_bps: Optional[float],
    ema_fast: Optional[float],
    ema_slow: Optional[float],
) -> float:
    score = 0.0
    if price is not None:
        score += 0.4
    if spread_bps is not None:
        score += 0.3
    if ema_fast is not None and ema_slow is not None:
        score += 0.3
    return score


def _ema_step(prev: float, price: float, period: int) -> float:
    alpha = 2 / (period + 1)
    return (price * alpha) + (prev * (1 - alpha))


def _ema_values(state: Optional[dict]) -> tuple[Optional[float], Optional[float]]:
    if not state:
        return None, None
    return state.get("ema_fast"), state.get("ema_slow")


def _indicator_value(state) -> Optional[float]:
    if state is None:
        return None
    return getattr(state, "value", None) if hasattr(state, "value") else None


def _orderbook_metrics(tick: dict, cache, symbol: str) -> tuple[float, float, float]:
    bids = tick.get("bids") or []
    asks = tick.get("asks") or []
    if (not bids or not asks) and cache is not None:
        cached = cache.get_orderbook(symbol)
        if cached:
            bids = cached.get("bids") or bids
            asks = cached.get("asks") or asks
    bid_depth = _depth_usd(bids)
    ask_depth = _depth_usd(asks)
    total = bid_depth + ask_depth
    imbalance = (bid_depth - ask_depth) / total if total > 0 else 0.0
    return bid_depth, ask_depth, imbalance


def _position_in_value(price: Optional[float], val: Optional[float], vah: Optional[float]) -> str:
    if price is None or val is None or vah is None:
        return "inside"
    if price < val:
        return "below"
    if price > vah:
        return "above"
    return "inside"


def _distance_abs(price: Optional[float], target: Optional[float]) -> float:
    if price is None or target is None:
        return 0.0
    return abs(price - target)


def _distance_signed(price: Optional[float], target: Optional[float]) -> float:
    if price is None or target is None:
        return 0.0
    return price - target


def _distance_abs_bps(price: Optional[float], target: Optional[float], mid_price: Optional[float]) -> float:
    if price is None or target is None or mid_price is None or mid_price <= 0:
        return 0.0
    return abs(price - target) / mid_price * 10000.0


def _distance_signed_bps(price: Optional[float], target: Optional[float], mid_price: Optional[float]) -> float:
    if price is None or target is None or mid_price is None or mid_price <= 0:
        return 0.0
    return (price - target) / mid_price * 10000.0


def _depth_usd(levels) -> float:
    depth = 0.0
    max_levels = None
    try:
        max_levels = int(os.getenv("ORDERBOOK_DEPTH_LEVELS", "50"))
    except (TypeError, ValueError):
        max_levels = 50
    if max_levels <= 0:
        max_levels = None
    for level in levels[:max_levels] if max_levels else levels:
        if not isinstance(level, (list, tuple)) or len(level) < 2:
            continue
        price = coerce_float(level[0])
        size = coerce_float(level[1])
        if price is None or size is None:
            continue
        depth += price * size
    return depth


def _session_key(timestamp, session_start_hour_utc: int) -> Optional[str]:
    ts = coerce_float(timestamp)
    if ts is None:
        return None
    session_start_hour_utc = max(0, min(23, session_start_hour_utc))
    seconds = int(ts)
    day = seconds // 86400
    day_start = day * 86400 + session_start_hour_utc * 3600
    if seconds < day_start:
        day -= 1
    return f"utc_session:{day}"


def _session_label(timestamp) -> str:
    ts = coerce_float(timestamp)
    if ts is None:
        return "unknown"
    # Canonical session classifier (kept in deeptrader_core and test-covered).
    # This must match ProfileRouter session semantics; otherwise strategies will
    # run with a different "session" than what the router selected.
    try:
        from quantgambit.deeptrader_core.profiles.profile_classifier import classify_session

        return classify_session(ts)
    except Exception:
        # Safe fallback (should rarely be used).
        hour = int((ts % 86400) // 3600)
        if 0 <= hour < 7:
            return "asia"
        if 7 <= hour < 12:
            return "europe"
        if 12 <= hour < 22:
            return "us"
        return "overnight"


def _is_market_hours(timestamp, start_hour: int, end_hour: int) -> bool:
    ts = coerce_float(timestamp)
    if ts is None:
        return False
    start_hour = max(0, min(23, start_hour))
    end_hour = max(0, min(24, end_hour))
    hour = int((ts % 86400) // 3600)
    if start_hour == end_hour:
        return True
    if start_hour < end_hour:
        return start_hour <= hour < end_hour
    return hour >= start_hour or hour < end_hour


def _should_emit_orderbook(
    symbol: str,
    timestamp: float,
    last_emit: dict,
    tick_count: dict,
    interval_ms: int,
    min_ticks: int,
) -> bool:
    last = last_emit.get(symbol, 0.0)
    ticks = tick_count.get(symbol, 0)
    if ticks < min_ticks:
        return False
    if (timestamp - last) * 1000.0 < interval_ms:
        return False
    last_emit[symbol] = timestamp
    tick_count[symbol] = 0
    return True
