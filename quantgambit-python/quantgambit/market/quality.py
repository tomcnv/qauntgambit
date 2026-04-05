"""Market data quality tracker for per-symbol gating."""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, Optional

from quantgambit.observability.telemetry import TelemetryContext, TelemetryPipeline
from quantgambit.storage.redis_snapshots import RedisSnapshotWriter


@dataclass
class QualityState:
    last_tick_ts: Optional[float] = None
    last_trade_ts: Optional[float] = None
    last_orderbook_ts: Optional[float] = None
    last_gap_at: Optional[float] = None
    gap_count: int = 0
    stale_count: int = 0
    skew_count: int = 0
    out_of_order_count: int = 0
    last_quality: Optional[str] = None
    last_trade_alert_at: Optional[float] = None
    last_source: Optional[str] = None
    source_ts: Dict[str, float] = field(default_factory=dict)
    # Track when counters were last reset/decayed for recovery
    last_reset_at: Optional[float] = None
    consecutive_healthy_updates: int = 0


class MarketDataQualityTracker:
    """Track freshness, gaps, and data completeness per symbol."""

    def __init__(
        self,
        snapshot_writer: Optional[RedisSnapshotWriter] = None,
        telemetry: Optional[TelemetryPipeline] = None,
        telemetry_context: Optional[TelemetryContext] = None,
        tick_stale_sec: float = 5.0,
        trade_stale_sec: float = 5.0,
        orderbook_stale_sec: float = 5.0,
        gap_window_sec: float = 30.0,
        max_history: int = 200,
    ) -> None:
        self.snapshot_writer = snapshot_writer
        self.telemetry = telemetry
        self.telemetry_context = telemetry_context
        self.tick_stale_sec = tick_stale_sec
        self.trade_stale_sec = trade_stale_sec
        self.orderbook_stale_sec = orderbook_stale_sec
        self.gap_window_sec = gap_window_sec
        self.max_history = max_history
        self._state: Dict[str, QualityState] = {}

    def update_tick(
        self,
        symbol: str,
        timestamp: Optional[float],
        now_ts: Optional[float],
        is_stale: bool,
        is_gap: bool,
        is_skew: bool,
        is_out_of_order: bool,
        source: Optional[str] = None,
    ) -> None:
        if not symbol:
            return
        state = self._state.setdefault(symbol, QualityState())
        event_ts = timestamp if timestamp is not None else now_ts
        if event_ts is None:
            return
        state.last_tick_ts = float(event_ts)
        if source:
            state.last_source = source
            state.source_ts[source] = float(event_ts)
        if is_gap:
            state.gap_count += 1
            state.last_gap_at = float(event_ts)
        if is_stale:
            state.stale_count += 1
        if is_skew:
            state.skew_count += 1
        if is_out_of_order:
            state.out_of_order_count += 1

    def update_trade(self, symbol: str, timestamp: Optional[float]) -> None:
        if not symbol or timestamp is None:
            return
        state = self._state.setdefault(symbol, QualityState())
        state.last_trade_ts = float(timestamp)

    def clear_symbol(self, symbol: str) -> None:
        """Clear quality state for a symbol to force a fresh start."""
        if symbol in self._state:
            del self._state[symbol]

    def reset_counters(self, symbol: str, now_ts: Optional[float] = None) -> None:
        """Reset error counters for a symbol after recovery."""
        state = self._state.get(symbol)
        if state:
            state.gap_count = 0
            state.out_of_order_count = 0
            state.stale_count = 0
            state.skew_count = 0
            state.last_gap_at = None
            state.consecutive_healthy_updates = 0
            state.last_reset_at = float(now_ts) if now_ts is not None else None

    def update_orderbook(
        self,
        symbol: str,
        timestamp: Optional[float],
        now_ts: Optional[float] = None,
        gap: bool = False,
        out_of_order: bool = False,
    ) -> None:
        if not symbol:
            return
        state = self._state.setdefault(symbol, QualityState())
        event_ts = timestamp if timestamp is not None else now_ts
        if event_ts is None:
            return
        state.last_orderbook_ts = float(event_ts)
        if gap:
            state.gap_count += 1
            state.last_gap_at = float(event_ts)
            state.consecutive_healthy_updates = 0
        elif out_of_order:
            state.out_of_order_count += 1
            state.consecutive_healthy_updates = 0
        else:
            # Healthy update - decay counters after sustained recovery
            state.consecutive_healthy_updates += 1
            if state.consecutive_healthy_updates >= 10:
                # After 10 consecutive healthy updates, start decaying counters
                if state.gap_count > 0:
                    state.gap_count = max(0, state.gap_count - 1)
                if state.out_of_order_count > 0:
                    state.out_of_order_count = max(0, state.out_of_order_count - 1)
                # Clear last_gap_at if enough time has passed
                now = float(event_ts)
                if state.last_gap_at and (now - state.last_gap_at) > self.gap_window_sec * 2:
                    state.last_gap_at = None
                state.last_reset_at = now

    async def snapshot(self, symbol: str, now_ts: Optional[float] = None) -> dict:
        state = self._state.get(symbol)
        if not state:
            return {"quality_score": 0.0, "status": "unknown", "flags": ["no_data"]}
        if now_ts is None:
            raise ValueError("now_ts_required")
        now = float(now_ts)
        tick_age = _age_sec(state.last_tick_ts, now)
        trade_age = _age_sec(state.last_trade_ts, now)
        book_age = _age_sec(state.last_orderbook_ts, now)
        # If we don't have explicit market ticks, derive tick age from
        # the freshest available source (orderbook/trades).
        if tick_age is None:
            if trade_age is not None and book_age is not None:
                tick_age = min(trade_age, book_age)
            elif trade_age is not None:
                tick_age = trade_age
            elif book_age is not None:
                tick_age = book_age
        gap_recent = state.last_gap_at is not None and (now - state.last_gap_at) <= self.gap_window_sec
        preferred_source = None
        if state.source_ts:
            preferred_source = max(state.source_ts.items(), key=lambda item: item[1])[0]
        flags = []
        score = 1.0
        if tick_age is None or tick_age > self.tick_stale_sec:
            flags.append("tick_stale")
            score -= 0.35
        if book_age is None or book_age > self.orderbook_stale_sec:
            flags.append("orderbook_stale")
            score -= 0.2
        if trade_age is None or trade_age > self.trade_stale_sec:
            flags.append("trade_stale")
            score -= 0.2
        if gap_recent:
            flags.append("orderbook_gap")
            score -= 0.15
        # Only flag out_of_order if recent (within gap window) AND count is significant
        out_of_order_recent = state.out_of_order_count > 0 and (
            state.last_gap_at is not None and (now - state.last_gap_at) <= self.gap_window_sec
        )
        if out_of_order_recent and state.out_of_order_count >= 3:
            flags.append("out_of_order")
            score -= 0.1
        # Only flag clock_skew if significant
        if state.skew_count >= 5:
            flags.append("clock_skew")
            score -= 0.05
        score = max(0.0, min(1.0, score))
        status = "ok" if score >= 0.8 else "degraded" if score >= 0.6 else "stale"
        if gap_recent and state.consecutive_healthy_updates < 5:
            orderbook_sync_state = "resyncing"
        elif book_age is None or book_age > self.orderbook_stale_sec:
            orderbook_sync_state = "stale"
        else:
            # If we have healthy updates, consider synced even if there were recent gaps
            orderbook_sync_state = "synced"
        if trade_age is None:
            trade_sync_state = "unknown"
        elif trade_age > self.trade_stale_sec:
            trade_sync_state = "stale"
        else:
            trade_sync_state = "synced"
        payload = {
            "symbol": symbol,
            "quality_score": round(score, 4),
            "status": status,
            "flags": flags,
            "tick_age_sec": tick_age,
            "trade_age_sec": trade_age,
            "orderbook_age_sec": book_age,
            "gap_count": state.gap_count,
            "stale_count": state.stale_count,
            "skew_count": state.skew_count,
            "out_of_order_count": state.out_of_order_count,
            "preferred_source": preferred_source,
            "orderbook_sync_state": orderbook_sync_state,
            "trade_sync_state": trade_sync_state,
            "timestamp": now,
        }
        await self._emit_trade_stale(symbol, trade_age, payload, now)
        await self._emit_snapshot(symbol, payload)
        return payload

    async def _emit_snapshot(self, symbol: str, payload: dict) -> None:
        if self.snapshot_writer and self.telemetry_context:
            key = f"quantgambit:{self.telemetry_context.tenant_id}:{self.telemetry_context.bot_id}:quality:{symbol}:latest"
            await self.snapshot_writer.write(key, payload)
            latest_key = f"quantgambit:{self.telemetry_context.tenant_id}:{self.telemetry_context.bot_id}:quality:latest"
            await self.snapshot_writer.write(latest_key, payload)
            history_key = f"quantgambit:{self.telemetry_context.tenant_id}:{self.telemetry_context.bot_id}:quality:{symbol}:history"
            await self.snapshot_writer.append_history(history_key, payload, max_items=self.max_history)
        if self.telemetry and self.telemetry_context:
            status = payload.get("status")
            state = self._state.get(symbol)
            if state and status != state.last_quality:
                state.last_quality = status
                await self.telemetry.publish_guardrail(
                    self.telemetry_context,
                    {
                        "type": "market_data_quality",
                        "symbol": symbol,
                        "status": status,
                        "quality_score": payload.get("quality_score"),
                        "flags": payload.get("flags"),
                    },
                )

    async def _emit_trade_stale(
        self,
        symbol: str,
        trade_age: Optional[float],
        payload: dict,
        now_ts: float,
    ) -> None:
        if trade_age is None:
            return
        if trade_age <= self.trade_stale_sec * 2:
            return
        state = self._state.get(symbol)
        if not state:
            return
        now = float(now_ts)
        if state.last_trade_alert_at and now - state.last_trade_alert_at < 60:
            return
        state.last_trade_alert_at = now
        if self.telemetry and self.telemetry_context:
            await self.telemetry.publish_guardrail(
                self.telemetry_context,
                {
                    "type": "trade_feed_stale",
                    "symbol": symbol,
                    "trade_age_sec": trade_age,
                    "threshold_sec": self.trade_stale_sec,
                    "quality_score": payload.get("quality_score"),
                },
            )

    def orderbook_issue_summary(self, include_zero: bool = False) -> list[dict]:
        """Summarize per-symbol orderbook gap/out-of-order counters."""
        summary: list[dict] = []
        for symbol, state in self._state.items():
            if include_zero or state.gap_count > 0 or state.out_of_order_count > 0:
                summary.append(
                    {
                        "symbol": symbol,
                        "orderbook_gap_count": state.gap_count,
                        "orderbook_out_of_order_count": state.out_of_order_count,
                    }
                )
        summary.sort(key=lambda item: item["symbol"])
        return summary


def _age_sec(last_ts: Optional[float], now: float) -> Optional[float]:
    if last_ts is None:
        return None
    try:
        delta = now - float(last_ts)
        if delta < 0:
            return 0.0
        return round(delta, 3)
    except (TypeError, ValueError):
        return None
