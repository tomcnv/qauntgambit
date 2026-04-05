"""
DataReadinessStage - First stage in the pipeline.

Performs sanity checks before any trading logic runs:
- Book data present (bids and asks non-empty)
- Trade data present (last trade within threshold)
- Clock sync OK (exchange time vs local time drift)
- WebSocket connected (not in REST fallback mode)
- Exchange timestamp (cts) based latency gates

Tiered gates based on production playbook:
- GREEN: Full speed (book_lag ≤150ms, trade_lag ≤200ms)
- YELLOW: Degraded - reduce size (book_lag ≤300ms, trade_lag ≤400ms)
- RED: No new entries - exits only (book_lag ≤800ms, trade_lag ≤1000ms)
- EMERGENCY: Data unreliable
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Optional

from quantgambit.signals.pipeline import Stage, StageContext, StageResult
from quantgambit.deeptrader_core.types import GateDecision
from quantgambit.observability.logger import log_info, log_warning
from quantgambit.core.data_readiness import ReadinessLevel


@dataclass
class DataReadinessConfig:
    """Configuration for DataReadinessStage."""
    # Maximum age of last trade in seconds (receive-time fallback)
    # 30s is reasonable for crypto - activity can be sporadic
    max_trade_age_sec: float = 30.0
    # Maximum clock drift between exchange and local time
    max_clock_drift_sec: float = 1.0
    # Minimum required bid depth in USD
    min_bid_depth_usd: float = 1000.0
    # Minimum required ask depth in USD
    min_ask_depth_usd: float = 1000.0
    # Whether to require WebSocket connection (not REST fallback)
    require_ws_connected: bool = True
    
    # Per-feed staleness thresholds (seconds) - receive-time based
    # These detect issues with individual data feeds
    max_orderbook_feed_age_sec: float = 10.0   # Orderbook updates every ~1s
    max_trade_feed_age_sec: float = 30.0       # Trade feed (can be sporadic)
    max_candle_feed_age_sec: float = 120.0     # Candles come every minute
    
    # === Exchange timestamp (cts) based latency gates ===
    # These use matching engine timestamps for accurate latency measurement
    use_cts_latency_gates: bool = True
    
    # Book lag thresholds (cts-based, in ms)
    book_lag_green_ms: int = 150   # Full speed
    book_lag_yellow_ms: int = 300  # Degraded - reduce size
    book_lag_red_ms: int = 800     # Emergency - exits only
    
    # Trade lag thresholds (T-based, in ms)  
    trade_lag_green_ms: int = 200
    trade_lag_yellow_ms: int = 400
    trade_lag_red_ms: int = 1000

    # Hard safety cap for exchange-side orderbook lag.
    # If exceeded, always block new entries regardless of tier tuning.
    # Set to <= 0 to disable.
    max_orderbook_exchange_lag_ms: int = 3000
    
    # Receive gap thresholds (detect frozen feeds, in ms)
    # Relaxed to account for throttled market data (100-200ms per tick)
    # and processing latency in feature worker
    book_gap_green_ms: int = 2000
    book_gap_yellow_ms: int = 5000
    book_gap_red_ms: int = 10000
    
    trade_gap_green_ms: int = 2000
    trade_gap_yellow_ms: int = 5000
    trade_gap_red_ms: int = 10000


class DataReadinessStage(Stage):
    """
    First stage: verify data quality before any trading logic.
    
    This is a side-agnostic global gate that runs very early to fail fast
    on obviously bad data conditions.
    
    Checks:
    1. Features dict exists and has required fields
    2. Book data present (bid/ask prices, depth)
    3. Trade data is fresh (not stale)
    4. Clock sync is within tolerance
    5. WebSocket connected (optional)
    6. Exchange timestamp (cts) latency gates
    
    Outputs:
    - ctx.data["readiness_level"]: GREEN/YELLOW/RED/EMERGENCY
    - ctx.data["size_multiplier"]: 1.0 (GREEN), 0.5 (YELLOW), 0.0 (RED/EMERGENCY)
    """
    name = "data_readiness"
    
    def __init__(self, config: Optional[DataReadinessConfig] = None):
        self.config = config or DataReadinessConfig()
        # Diagnostic override to ignore feed gap/staleness checks (for validation)
        self._ignore_feed_gaps = os.getenv("IGNORE_FEED_GAPS", "false").lower() in {"1", "true", "yes"}

    @staticmethod
    def _coerce_ms(value: object) -> Optional[int]:
        """Coerce lag values in ms to int, tolerating numeric strings."""
        if value is None:
            return None
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return None

    def _resolve_trade_lag_thresholds(
        self,
        ctx: StageContext,
        book_gap_ms: Optional[int],
    ) -> tuple[int, int, int]:
        """
        Resolve effective trade lag thresholds for the current symbol.

        SOLUSDT can produce sparse trade ticks while the orderbook is still
        clearly live. In that case we allow a small symbol-specific extension
        to avoid false EMERGENCY blocks from slightly delayed trade feeds.
        """
        cfg = self.config
        green = cfg.trade_lag_green_ms
        yellow = cfg.trade_lag_yellow_ms
        red = cfg.trade_lag_red_ms

        if (
            isinstance(ctx.symbol, str)
            and ctx.symbol.upper() == "SOLUSDT"
            and book_gap_ms is not None
            and book_gap_ms <= cfg.book_gap_green_ms
        ):
            green = max(green, 4000)
            yellow = max(yellow, 8000)
            red = max(red, 12000)

        return green, yellow, red

    def _resolve_trade_lag_emergency_threshold(
        self,
        ctx: StageContext,
        book_gap_ms: Optional[int],
        red_threshold_ms: int,
    ) -> int:
        """
        Resolve the threshold for EMERGENCY trade-lag blocking.

        For liquid symbols, a short receive-time trade lull can happen even while the
        orderbook is clearly fresh. In that case, crossing the RED trade-lag band
        should degrade entries, not immediately escalate to EMERGENCY. Keep the
        stricter behavior when the book itself is no longer fresh.
        """
        emergency_threshold_ms = red_threshold_ms

        if book_gap_ms is not None and book_gap_ms <= self.config.book_gap_green_ms:
            emergency_threshold_ms = max(emergency_threshold_ms, 2000)

        return emergency_threshold_ms

    def _resolve_trade_gap_thresholds(
        self,
        ctx: StageContext,
        book_gap_ms: Optional[int],
    ) -> tuple[int, int, int]:
        """
        Resolve effective trade feed-gap thresholds for the current symbol.

        SOLUSDT can have sparse trade ticks even while the book is fresh. Use a
        wider trade-gap band in that case so we do not false-block on feed
        sparsity when the orderbook is still clearly live.
        """
        cfg = self.config
        green = cfg.trade_gap_green_ms
        yellow = cfg.trade_gap_yellow_ms
        red = cfg.trade_gap_red_ms

        if (
            isinstance(ctx.symbol, str)
            and ctx.symbol.upper() == "SOLUSDT"
            and book_gap_ms is not None
            and book_gap_ms <= cfg.book_gap_green_ms
        ):
            green = max(green, 4000)
            yellow = max(yellow, 8000)
            red = max(red, 12000)

        return green, yellow, red
    
    async def run(self, ctx: StageContext) -> StageResult:
        reasons = []
        metrics = {}
        readiness_level = ReadinessLevel.GREEN
        
        features = ctx.data.get("features") or {}
        market_context = ctx.data.get("market_context") or {}
        
        # Check 1: Features exist
        if not features:
            reasons.append("no_features")
            return self._reject(ctx, reasons, metrics)
        
        # Check 2: Price data present
        price = features.get("price")
        bid = features.get("bid")
        ask = features.get("ask")
        
        if price is None:
            reasons.append("no_price")
        if bid is None:
            reasons.append("no_bid")
        if ask is None:
            reasons.append("no_ask")
        
        if reasons:
            return self._reject(ctx, reasons, metrics)
        
        # Check 3: Book depth present and sufficient
        bid_depth = features.get("bid_depth_usd") or 0.0
        ask_depth = features.get("ask_depth_usd") or 0.0
        
        metrics["bid_depth_usd"] = bid_depth
        metrics["ask_depth_usd"] = ask_depth
        
        # Critical: Low depth is a hard rejection (can't trade safely)
        if bid_depth < self.config.min_bid_depth_usd:
            reasons.append(f"bid_depth_low:{bid_depth:.0f}<{self.config.min_bid_depth_usd:.0f}")
            return self._reject(ctx, reasons, metrics)
        if ask_depth < self.config.min_ask_depth_usd:
            reasons.append(f"ask_depth_low:{ask_depth:.0f}<{self.config.min_ask_depth_usd:.0f}")
            return self._reject(ctx, reasons, metrics)
        
        # Check 4: Trade data freshness
        trade_age = 0.0
        trade_recv_ms = market_context.get("trade_recv_ms")
        feed_staleness = market_context.get("feed_staleness") or {}
        trade_age_candidates = []
        try:
            if trade_recv_ms is not None:
                trade_age_candidates.append(max(0.0, time.time() - (float(trade_recv_ms) / 1000.0)))
            if feed_staleness.get("trade") is not None:
                trade_age_candidates.append(max(0.0, float(feed_staleness.get("trade"))))
            if trade_age_candidates:
                trade_age = min(trade_age_candidates)
            else:
                trade_ts = features.get("timestamp")
                if trade_ts is None:
                    trade_ts = market_context.get("timestamp")
                trade_ts = float(trade_ts) if trade_ts is not None else None
                if trade_ts is not None:
                    if trade_ts > 1e15:
                        trade_ts = trade_ts / 1_000_000.0
                    elif trade_ts > 1e12:
                        trade_ts = trade_ts / 1000.0
                    trade_age = max(0.0, time.time() - trade_ts)
        except (TypeError, ValueError):
            trade_age = 0.0
        metrics["trade_age_sec"] = trade_age
        if trade_age > self.config.max_trade_age_sec:
            reasons.append(
                f"trade_stale:{trade_age:.1f}s>{self.config.max_trade_age_sec:.1f}s"
            )
            return self._reject(ctx, reasons, metrics)
        
        # Check 5: Data quality status
        quality_status = market_context.get("data_quality_status")
        if quality_status == "stale":
            reasons.append("data_quality_stale")
        
        # Check 6: WebSocket connection (not REST fallback)
        if self.config.require_ws_connected:
            # Check for indicators that we're in REST fallback mode
            trade_sync_state = market_context.get("trade_sync_state")
            orderbook_sync_state = market_context.get("orderbook_sync_state")
            
            if trade_sync_state == "stale" and orderbook_sync_state == "stale":
                reasons.append("ws_disconnected_both_stale")
        
        # Check 7: Per-feed staleness (individual data feed health)
        feed_staleness = market_context.get("feed_staleness") or {}
        
        # Skip feed staleness checks when override enabled (diagnostic)
        if not self._ignore_feed_gaps:
            # Orderbook feed staleness
            ob_stale = feed_staleness.get("orderbook")
            if ob_stale is not None:
                metrics["orderbook_feed_age_sec"] = ob_stale
                if ob_stale > self.config.max_orderbook_feed_age_sec:
                    reasons.append(f"orderbook_feed_stale:{ob_stale:.1f}s>{self.config.max_orderbook_feed_age_sec:.0f}s")
            
            # Trade feed staleness
            trade_stale = feed_staleness.get("trade")
            if trade_stale is not None:
                metrics["trade_feed_age_sec"] = trade_stale
                if trade_stale > self.config.max_trade_feed_age_sec:
                    reasons.append(f"trade_feed_stale:{trade_stale:.1f}s>{self.config.max_trade_feed_age_sec:.0f}s")
            
            # Candle feed staleness (less critical, warn but don't block)
            candle_stale = feed_staleness.get("candle")
            if candle_stale is not None:
                metrics["candle_feed_age_sec"] = candle_stale
                # Candles are less critical - only warn, don't block
        
        # Check 8: Exchange timestamp (cts) based latency gates
        # This is the most accurate measure of data freshness
        if self.config.use_cts_latency_gates and not self._ignore_feed_gaps:
            now_ms = time.time() * 1000
            cfg = self.config
            
            # Get cts_ms from features/market_context (set by orderbook parser)
            book_cts_ms = features.get("cts_ms") or market_context.get("book_cts_ms")
            trade_ts_ms = features.get("trade_ts_ms") or market_context.get("trade_ts_ms")

            # Receive-time gaps should be based on the most reliable source available.
            # Prefer the minimum gap implied by:
            # 1. reference cache recv timestamps (book_recv_ms/trade_recv_ms), and
            # 2. feed staleness (orderbook/trade) in market_context.
            #
            # This avoids false EMERGENCY states when one component fails to update
            # recv timestamps even though the feed is live (or vice versa).
            book_recv_ms = market_context.get("book_recv_ms")
            trade_recv_ms = market_context.get("trade_recv_ms")
            book_stale_ms = int((ob_stale or 0) * 1000) if ob_stale is not None else None
            trade_stale_ms = int((trade_stale or 0) * 1000) if trade_stale is not None else None
            
            # Calculate exchange-time based lags
            book_lag_ms = int(now_ms - book_cts_ms) if book_cts_ms else None
            trade_lag_ms = None

            # Accept MDS-computed exchange lag when provided in market_context.
            # Only consume second-based fallback when source is explicitly marked
            # as matching-engine; gateway/server ts can lag and create false blocks.
            mds_exchange_lag_ms = self._coerce_ms(market_context.get("orderbook_exchange_lag_ms"))
            mds_exchange_lag_source = market_context.get("orderbook_exchange_lag_source")
            if (
                mds_exchange_lag_ms is None
                and mds_exchange_lag_source == "matching_engine"
            ):
                lag_sec = market_context.get("orderbook_exchange_lag")
                if lag_sec is not None:
                    try:
                        mds_exchange_lag_ms = int(float(lag_sec) * 1000.0)
                    except (TypeError, ValueError):
                        mds_exchange_lag_ms = None
            if mds_exchange_lag_ms is not None:
                book_lag_ms = max(book_lag_ms or 0, mds_exchange_lag_ms)
            
            # Calculate receive-time based gaps (take the min across sources when both exist)
            book_gap_ms = int(now_ms - book_recv_ms) if book_recv_ms is not None else None
            trade_gap_ms = int(now_ms - trade_recv_ms) if trade_recv_ms is not None else None
            if book_stale_ms is not None:
                book_gap_ms = book_stale_ms if book_gap_ms is None else min(book_gap_ms, book_stale_ms)
            if trade_stale_ms is not None:
                trade_gap_ms = trade_stale_ms if trade_gap_ms is None else min(trade_gap_ms, trade_stale_ms)
            
            # Trade gating should use receive-time freshness, not exchange-side trade
            # timestamps. Exchange timestamps can lag or batch even when the local
            # feed is current. Only fall back to timestamp-style freshness if we have
            # neither receive-time nor feed-staleness coverage.
            trade_age_ms_fallback = (
                int(float(trade_age) * 1000.0)
                if trade_age is not None
                else None
            )
            trade_lag_raw_ms = int(now_ms - trade_ts_ms) if trade_ts_ms else None
            if (
                trade_gap_ms is None
                and trade_lag_raw_ms is not None
                and trade_age_ms_fallback is not None
                and trade_age_ms_fallback <= cfg.trade_gap_green_ms
                and trade_lag_raw_ms > (trade_age_ms_fallback + 2000)
            ):
                metrics["trade_lag_raw_divergent"] = trade_lag_raw_ms
                trade_lag_raw_ms = trade_age_ms_fallback
            if trade_gap_ms is not None:
                trade_lag_ms = trade_gap_ms
            elif trade_lag_raw_ms is not None:
                trade_lag_ms = trade_lag_raw_ms
            elif trade_age_ms_fallback is not None:
                trade_lag_ms = trade_age_ms_fallback

            # Record metrics
            if book_lag_ms is not None:
                metrics["book_lag_ms"] = book_lag_ms
                metrics["orderbook_exchange_lag_ms"] = book_lag_ms
            if trade_lag_ms is not None:
                metrics["trade_lag_ms"] = trade_lag_ms
            if trade_lag_raw_ms is not None:
                metrics["trade_lag_raw_ms"] = trade_lag_raw_ms
            if trade_age_ms_fallback is not None:
                metrics["trade_age_ms_fallback"] = trade_age_ms_fallback
            if book_gap_ms is not None:
                metrics["book_gap_ms"] = book_gap_ms
            if trade_gap_ms is not None:
                metrics["trade_gap_ms"] = trade_gap_ms
            
            # Evaluate tiered readiness level
            # Start at GREEN, downgrade based on worst condition

            # Hard safety cap: always reject entries if exchange lag is too high.
            has_reliable_exchange_lag = (book_cts_ms is not None) or (mds_exchange_lag_ms is not None)
            if (
                cfg.max_orderbook_exchange_lag_ms > 0
                and has_reliable_exchange_lag
                and book_lag_ms is not None
                and book_lag_ms > cfg.max_orderbook_exchange_lag_ms
            ):
                reasons.append(
                    f"orderbook_exchange_lag_hard_block:{book_lag_ms}ms>{cfg.max_orderbook_exchange_lag_ms}ms"
                )
                readiness_level = ReadinessLevel.EMERGENCY
                return self._reject(ctx, reasons, metrics)

            # Book lag evaluation
            if book_lag_ms is not None:
                if book_lag_ms > cfg.book_lag_red_ms:
                    readiness_level = ReadinessLevel.EMERGENCY
                    reasons.append(f"book_lag_emergency:{book_lag_ms}ms>{cfg.book_lag_red_ms}ms")
                elif book_lag_ms > cfg.book_lag_yellow_ms:
                    if readiness_level.value not in ("red", "emergency"):
                        readiness_level = ReadinessLevel.RED
                    reasons.append(f"book_lag_red:{book_lag_ms}ms>{cfg.book_lag_yellow_ms}ms")
                elif book_lag_ms > cfg.book_lag_green_ms:
                    if readiness_level == ReadinessLevel.GREEN:
                        readiness_level = ReadinessLevel.YELLOW
            
            trade_lag_green_ms, trade_lag_yellow_ms, trade_lag_red_ms = self._resolve_trade_lag_thresholds(
                ctx,
                book_gap_ms,
            )

            trade_lag_emergency_ms = self._resolve_trade_lag_emergency_threshold(
                ctx,
                book_gap_ms,
                trade_lag_red_ms,
            )

            # Trade lag evaluation
            if trade_lag_ms is not None:
                if trade_lag_ms > trade_lag_emergency_ms:
                    readiness_level = ReadinessLevel.EMERGENCY
                    reasons.append(f"trade_lag_emergency:{trade_lag_ms}ms>{trade_lag_emergency_ms}ms")
                elif trade_lag_ms > trade_lag_yellow_ms:
                    if readiness_level.value not in ("red", "emergency"):
                        readiness_level = ReadinessLevel.RED
                    reasons.append(f"trade_lag_red:{trade_lag_ms}ms>{trade_lag_yellow_ms}ms")
                elif trade_lag_ms > trade_lag_green_ms:
                    if readiness_level == ReadinessLevel.GREEN:
                        readiness_level = ReadinessLevel.YELLOW
            
            # Book gap evaluation (frozen feed detection)
            if book_gap_ms is not None:
                if book_gap_ms > cfg.book_gap_red_ms:
                    readiness_level = ReadinessLevel.EMERGENCY
                    reasons.append(f"book_gap_emergency:{book_gap_ms}ms>{cfg.book_gap_red_ms}ms")
                elif book_gap_ms > cfg.book_gap_yellow_ms:
                    if readiness_level.value not in ("red", "emergency"):
                        readiness_level = ReadinessLevel.RED
                    reasons.append(f"book_gap_red:{book_gap_ms}ms>{cfg.book_gap_yellow_ms}ms")
                elif book_gap_ms > cfg.book_gap_green_ms:
                    if readiness_level == ReadinessLevel.GREEN:
                        readiness_level = ReadinessLevel.YELLOW
            
            # Trade gap evaluation
            trade_gap_green_ms, trade_gap_yellow_ms, trade_gap_red_ms = self._resolve_trade_gap_thresholds(
                ctx,
                book_gap_ms,
            )

            if trade_gap_ms is not None:
                if trade_gap_ms > trade_gap_red_ms:
                    readiness_level = ReadinessLevel.EMERGENCY
                    reasons.append(f"trade_gap_emergency:{trade_gap_ms}ms>{trade_gap_red_ms}ms")
                elif trade_gap_ms > trade_gap_yellow_ms:
                    if readiness_level.value not in ("red", "emergency"):
                        readiness_level = ReadinessLevel.RED
                    reasons.append(f"trade_gap_red:{trade_gap_ms}ms>{trade_gap_yellow_ms}ms")
                elif trade_gap_ms > trade_gap_green_ms:
                    if readiness_level == ReadinessLevel.GREEN:
                        readiness_level = ReadinessLevel.YELLOW
        
        # Store readiness level and size multiplier for downstream stages
        metrics["readiness_level"] = readiness_level.value
        ctx.data["readiness_level"] = readiness_level
        
        # Size multiplier: 1.0 for GREEN, 0.5 for YELLOW, 0.0 for RED/EMERGENCY
        if readiness_level == ReadinessLevel.GREEN:
            size_multiplier = 1.0
        elif readiness_level == ReadinessLevel.YELLOW:
            size_multiplier = 0.5
        else:
            size_multiplier = 0.0
        ctx.data["size_multiplier"] = size_multiplier
        metrics["size_multiplier"] = size_multiplier
        
        # Reject if RED or EMERGENCY (no new entries)
        if readiness_level in (ReadinessLevel.RED, ReadinessLevel.EMERGENCY):
            return self._reject(ctx, reasons, metrics)
        
        # Pass with degraded status if YELLOW
        if reasons and readiness_level == ReadinessLevel.YELLOW:
            log_info(
                "data_readiness_degraded",
                symbol=ctx.symbol,
                level=readiness_level.value,
                reasons=reasons,
                size_multiplier=size_multiplier,
            )
        
        # Store gate decision for telemetry
        ctx.data["gate_decisions"] = ctx.data.get("gate_decisions") or []
        ctx.data["gate_decisions"].append(GateDecision(
            allowed=True,
            gate_name=self.name,
            reasons=reasons,  # Include yellow reasons
            metrics=metrics,
        ))
        
        return StageResult.CONTINUE
    
    def _reject(self, ctx: StageContext, reasons: list, metrics: dict) -> StageResult:
        """Record rejection and return REJECT result."""
        ctx.rejection_reason = reasons[0] if reasons else "data_not_ready"
        ctx.rejection_stage = self.name
        ctx.rejection_detail = {
            "reasons": reasons,
            "metrics": metrics,
        }
        
        # Store gate decision for telemetry
        ctx.data["gate_decisions"] = ctx.data.get("gate_decisions") or []
        ctx.data["gate_decisions"].append(GateDecision(
            allowed=False,
            gate_name=self.name,
            reasons=reasons,
            metrics=metrics,
        ))
        
        log_warning(
            "data_readiness_reject",
            symbol=ctx.symbol,
            reasons=reasons,
            metrics=metrics,
        )
        
        return StageResult.REJECT
