"""Candle aggregation utilities."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional


@dataclass
class Candle:
    symbol: str
    timeframe_sec: int
    start_ts: float
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0


class CandleAggregator:
    """Aggregate ticks into OHLCV candles per symbol/timeframe."""

    def __init__(self, timeframe_sec: int):
        self.timeframe_sec = timeframe_sec
        self._current: Dict[str, Candle] = {}

    def update(self, symbol: str, ts: float, price: float, volume: float = 0.0) -> Optional[Candle]:
        start_ts = _bucket_start(ts, self.timeframe_sec)
        candle = self._current.get(symbol)
        if candle is None or candle.start_ts != start_ts:
            finalized = candle
            self._current[symbol] = Candle(
                symbol=symbol,
                timeframe_sec=self.timeframe_sec,
                start_ts=start_ts,
                open=price,
                high=price,
                low=price,
                close=price,
                volume=volume,
            )
            return finalized
        candle.high = max(candle.high, price)
        candle.low = min(candle.low, price)
        candle.close = price
        candle.volume += volume
        return None


def _bucket_start(ts: float, timeframe_sec: int) -> float:
    return ts - (ts % timeframe_sec)
