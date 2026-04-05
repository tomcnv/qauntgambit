"""Source fusion policy for market data feeds."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional


SOURCE_TRADE = "trade"
SOURCE_ORDERBOOK = "orderbook"
SOURCE_TICKER = "ticker"
SOURCE_UNKNOWN = "unknown"


@dataclass(frozen=True)
class SourceFusionPolicy:
    """Select preferred data source based on freshness and priority."""

    priority: tuple[str, ...] = (SOURCE_TRADE, SOURCE_ORDERBOOK, SOURCE_TICKER)
    stale_us: int = 5_000_000

    def preferred_source(self, last_seen_us: Dict[str, int], now_us: int) -> Optional[str]:
        """Return the freshest preferred source within the stale window."""
        for source in self.priority:
            ts = last_seen_us.get(source)
            if ts is None:
                continue
            if (now_us - ts) <= self.stale_us:
                return source
        return None

    def should_update(
        self,
        source_kind: str,
        last_seen_us: Dict[str, int],
        now_us: int,
        has_reference: bool,
    ) -> bool:
        """Return True if this source should update reference price."""
        if not has_reference:
            return True
        preferred = self.preferred_source(last_seen_us, now_us)
        if preferred is None:
            return True
        return source_kind == preferred


def classify_tick_source(tick: dict) -> str:
    """Classify a market tick into a canonical source category."""
    source = (tick.get("source") or "").lower()
    bids = tick.get("bids") or []
    asks = tick.get("asks") or []
    bid = tick.get("bid")
    ask = tick.get("ask")
    last = tick.get("last")
    if bids and asks:
        return SOURCE_ORDERBOOK
    if "orderbook" in source or "book" in source:
        return SOURCE_ORDERBOOK
    if "trade" in source or "execution" in source or "fill" in source:
        return SOURCE_TRADE
    if last is not None and bid is None and ask is None:
        return SOURCE_TRADE
    if last is not None or bid is not None or ask is not None:
        return SOURCE_TICKER
    return SOURCE_UNKNOWN
