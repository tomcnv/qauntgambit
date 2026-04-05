"""Candle-based indicator helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional


@dataclass
class ATRState:
    period: int
    value: Optional[float] = None

    def update(self, high: float, low: float, prev_close: Optional[float]) -> float:
        tr = _true_range(high, low, prev_close)
        if self.value is None:
            self.value = tr
        else:
            alpha = 1 / self.period
            self.value = (self.value * (1 - alpha)) + (tr * alpha)
        return self.value


@dataclass
class VWAPState:
    sum_price_volume: float = 0.0
    sum_volume: float = 0.0
    session_key: Optional[str] = None

    def update(self, price: float, volume: float, session_key: Optional[str] = None) -> float:
        if session_key and session_key != self.session_key:
            self.sum_price_volume = 0.0
            self.sum_volume = 0.0
            self.session_key = session_key
        self.sum_price_volume += price * volume
        self.sum_volume += volume
        if self.sum_volume <= 0:
            return price
        return self.sum_price_volume / self.sum_volume


def _true_range(high: float, low: float, prev_close: Optional[float]) -> float:
    if prev_close is None:
        return high - low
    return max(high - low, abs(high - prev_close), abs(low - prev_close))
