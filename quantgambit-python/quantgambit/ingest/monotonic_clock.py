"""Per-symbol monotonic clock for canonical timestamps."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict


@dataclass
class MonotonicMetrics:
    adjustments_count: int = 0
    total_drift_us: int = 0
    max_adjustment_us: int = 0


class MonotonicClock:
    """Monotonic timestamp adjuster keyed by symbol."""

    def __init__(self, epsilon_us: int = 1) -> None:
        self._epsilon_us = max(1, int(epsilon_us))
        self._last_ts_us: Dict[str, int] = {}
        self._metrics: Dict[str, MonotonicMetrics] = {}

    def update(self, symbol: str, ts_recv_us: int) -> int:
        """Return canonical monotonic timestamp for symbol."""
        if not symbol:
            return int(ts_recv_us)
        ts_recv_us = int(ts_recv_us)
        last = self._last_ts_us.get(symbol, 0)
        if ts_recv_us <= last:
            adjusted = last + self._epsilon_us
            drift = adjusted - ts_recv_us
            metrics = self._metrics.setdefault(symbol, MonotonicMetrics())
            metrics.adjustments_count += 1
            metrics.total_drift_us += drift
            if drift > metrics.max_adjustment_us:
                metrics.max_adjustment_us = drift
        else:
            adjusted = ts_recv_us
        self._last_ts_us[symbol] = adjusted
        return adjusted

    def metrics(self, symbol: str) -> MonotonicMetrics:
        return self._metrics.get(symbol, MonotonicMetrics())

    def summary(self, include_zero: bool = False) -> list[dict]:
        symbols = set(self._metrics.keys()) | set(self._last_ts_us.keys())
        summary: list[dict] = []
        for symbol in sorted(symbols):
            metrics = self._metrics.get(symbol, MonotonicMetrics())
            if include_zero or metrics.adjustments_count > 0:
                summary.append(
                    {
                        "symbol": symbol,
                        "monotonic_adjustments_count": metrics.adjustments_count,
                        "monotonic_total_drift_us": metrics.total_drift_us,
                        "monotonic_max_adjustment_us": metrics.max_adjustment_us,
                    }
                )
        return summary
