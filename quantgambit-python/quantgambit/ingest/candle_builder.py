"""Shared candle builder with grace + late-tick policy."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple

from quantgambit.ingest.candles import Candle, CandleAggregator, _bucket_start
from quantgambit.ingest.time_utils import sec_to_us, us_to_sec

DEFAULT_CANDLE_GRACE_SEC = {60: 2.0, 300: 5.0, 900: 10.0}


@dataclass(frozen=True)
class CandleBuildResult:
    candle: Candle
    stats: Dict[str, object]
    bucket_start_us: int
    bucket_end_us: int


class CandleBuilder:
    """Build candles from tick events with grace-based finalization."""

    def __init__(
        self,
        timeframes_sec: Iterable[int],
        grace_sec: Optional[Dict[int, float]] = None,
    ) -> None:
        self._aggregators = {tf: CandleAggregator(tf) for tf in timeframes_sec}
        self._source_stats: Dict[Tuple[str, int], Dict[str, object]] = {}
        self._pending_candles: Dict[Tuple[str, int], Dict[str, object]] = {}
        self._late_tick_counts: Dict[Tuple[str, int], int] = {}
        self._last_finalized_start_ts: Dict[Tuple[str, int], float] = {}
        self._grace_sec = grace_sec or DEFAULT_CANDLE_GRACE_SEC

    def process_tick(
        self,
        symbol: str,
        ts_canon_us: int,
        price: float,
        volume: float = 0.0,
        price_source: Optional[str] = None,
        now_us: Optional[int] = None,
    ) -> List[CandleBuildResult]:
        """Process a single tick and return finalized candles (if any)."""
        results: List[CandleBuildResult] = []
        if now_us is None:
            now_us = ts_canon_us
        ts_sec = us_to_sec(ts_canon_us)

        for timeframe, aggregator in self._aggregators.items():
            start_ts = _bucket_start(ts_sec, timeframe)
            key = (symbol, timeframe)

            last_finalized = self._last_finalized_start_ts.get(key)
            if last_finalized is not None and start_ts <= last_finalized:
                self._increment_late_tick(key)
                continue

            stats = self._source_stats.get(key)
            prev_stats = stats
            pending = self._pending_candles.get(key)

            if pending and pending["candle"].start_ts == start_ts:
                self._update_candle(pending["candle"], price, volume)
                self._update_stats(pending["stats"], price_source, ts_canon_us)
                results.extend(self._maybe_finalize(key, now_us))
                continue

            if pending and start_ts < pending["candle"].start_ts:
                self._increment_late_tick(key)
                continue

            if not stats or stats.get("start_ts") != start_ts:
                start_us = int(ts_canon_us // (timeframe * 1_000_000)) * (timeframe * 1_000_000)
                stats = {
                    "start_ts": start_ts,
                    "start_us": start_us,
                    "min_tick_ts_us": ts_canon_us,
                    "max_tick_ts_us": ts_canon_us,
                    "counts": {"last": 0, "mid": 0, "bid": 0, "ask": 0},
                }
                self._source_stats[key] = stats

            self._update_stats(stats, price_source, ts_canon_us)
            finalized = aggregator.update(symbol, ts_sec, price, volume)
            if finalized:
                ref_stats = prev_stats or stats
                start_us = ref_stats.get("start_us", sec_to_us(finalized.start_ts))
                self._pending_candles[key] = {
                    "candle": finalized,
                    "stats": ref_stats,
                    "bucket_end_us": int(start_us + (finalized.timeframe_sec * 1_000_000)),
                }

            results.extend(self._maybe_finalize(key, now_us))

        return results

    def flush(self, now_us: int) -> List[CandleBuildResult]:
        """Finalize any pending candles that are past grace at now_us."""
        results: List[CandleBuildResult] = []
        for key in list(self._pending_candles.keys()):
            results.extend(self._maybe_finalize(key, now_us))
        return results

    def get_late_tick_count(self, symbol: str, timeframe: int) -> int:
        return self._late_tick_counts.get((symbol, timeframe), 0)

    def late_tick_summary(self) -> list[dict]:
        summary = []
        for (symbol, timeframe), count in self._late_tick_counts.items():
            if count > 0:
                summary.append(
                    {
                        "symbol": symbol,
                        "timeframe_sec": timeframe,
                        "late_tick_count": count,
                    }
                )
        summary.sort(key=lambda item: (item["symbol"], item["timeframe_sec"]))
        return summary

    def max_grace_us(self) -> int:
        if not self._grace_sec:
            return 0
        return int(max(self._grace_sec.values()) * 1_000_000)

    def _maybe_finalize(self, key: Tuple[str, int], now_us: int) -> List[CandleBuildResult]:
        pending = self._pending_candles.get(key)
        if not pending:
            return []
        timeframe = key[1]
        grace_sec = self._grace_sec.get(timeframe, 2.0)
        if now_us < pending["bucket_end_us"] + int(grace_sec * 1_000_000):
            return []
        candle = pending["candle"]
        stats = pending["stats"]
        bucket_start_us = int(stats.get("start_us", sec_to_us(candle.start_ts)))
        bucket_end_us = bucket_start_us + int(candle.timeframe_sec * 1_000_000)
        self._last_finalized_start_ts[key] = candle.start_ts
        self._pending_candles.pop(key, None)
        return [
            CandleBuildResult(
                candle=candle,
                stats=stats,
                bucket_start_us=bucket_start_us,
                bucket_end_us=bucket_end_us,
            )
        ]

    def _increment_late_tick(self, key: Tuple[str, int]) -> None:
        self._late_tick_counts[key] = self._late_tick_counts.get(key, 0) + 1

    @staticmethod
    def _update_candle(candle: Candle, price: float, volume: float) -> None:
        candle.high = max(candle.high, price)
        candle.low = min(candle.low, price)
        candle.close = price
        candle.volume += volume

    @staticmethod
    def _update_stats(stats: Dict[str, object], price_source: Optional[str], tick_ts_us: Optional[int]) -> None:
        counts = stats.get("counts")
        if isinstance(counts, dict) and price_source:
            counts[price_source] = counts.get(price_source, 0) + 1
        if tick_ts_us is not None:
            min_ts = stats.get("min_tick_ts_us")
            max_ts = stats.get("max_tick_ts_us")
            stats["min_tick_ts_us"] = tick_ts_us if min_ts is None else min(min_ts, tick_ts_us)
            stats["max_tick_ts_us"] = tick_ts_us if max_ts is None else max(max_ts, tick_ts_us)
