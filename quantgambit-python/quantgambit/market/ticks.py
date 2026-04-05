"""Tick schema normalization and validation."""

from __future__ import annotations

from typing import Any, Dict, Optional


REQUIRED_FIELDS = {"symbol"}
MAX_DEPTH = 20


def normalize_tick(raw: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not isinstance(raw, dict):
        return None
    symbol = raw.get("symbol") or raw.get("instId") or raw.get("instrument")
    if not symbol:
        return None
    bid = _to_float(raw.get("bid") or raw.get("bestBid"))
    ask = _to_float(raw.get("ask") or raw.get("bestAsk"))
    last = _to_float(raw.get("last") or raw.get("lastPrice"))
    volume = _to_float(raw.get("volume") or raw.get("size") or raw.get("qty"))
    ts = raw.get("timestamp") or raw.get("ts")
    bids = _normalize_levels(raw.get("bids") or raw.get("buy"), side="bid")
    asks = _normalize_levels(raw.get("asks") or raw.get("sell"), side="ask")
    return {
        "symbol": symbol,
        "bid": bid,
        "ask": ask,
        "last": last,
        "volume": volume,
        "timestamp": ts,
        "bids": bids,
        "asks": asks,
        "source": raw.get("source"),
    }


def _to_float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalize_levels(levels: Any, side: str) -> list[list[float]]:
    if not isinstance(levels, (list, tuple)):
        return []
    cleaned: list[list[float]] = []
    for level in levels:
        if not isinstance(level, (list, tuple)) or len(level) < 2:
            continue
        price = _to_float(level[0])
        size = _to_float(level[1])
        if price is None or size is None:
            continue
        if price <= 0 or size <= 0:
            continue
        cleaned.append([price, size])
        if len(cleaned) >= MAX_DEPTH:
            break
    if side == "bid":
        cleaned.sort(key=lambda x: x[0], reverse=True)
    elif side == "ask":
        cleaned.sort(key=lambda x: x[0])
    return cleaned
