"""Helpers for normalizing stage inputs."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class StageInputs:
    symbol: str
    market_context: Dict[str, Any]
    features: Dict[str, Any]
    errors: List[str] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return not self.errors


def build_stage_inputs(
    symbol: str,
    market_context: Any,
    features: Any,
) -> StageInputs:
    market_dict = _to_dict(market_context)
    feature_dict = _to_dict(features)
    errors: List[str] = []

    market_dict.setdefault("symbol", symbol)
    feature_dict.setdefault("symbol", symbol)

    price = _coerce_float(
        market_dict.get("price")
        or feature_dict.get("price")
        or market_dict.get("last")
        or feature_dict.get("last"),
        "price",
        errors,
    )
    bid = _coerce_float(market_dict.get("bid") or feature_dict.get("bid"), "bid", errors)
    ask = _coerce_float(market_dict.get("ask") or feature_dict.get("ask"), "ask", errors)
    if price is None and bid is not None and ask is not None:
        price = (bid + ask) / 2.0
    if price is None:
        errors.append("missing_price")
    else:
        market_dict.setdefault("price", price)
        feature_dict.setdefault("price", price)

    timestamp = _coerce_float(
        market_dict.get("timestamp") or feature_dict.get("timestamp"),
        "timestamp",
        errors,
    )
    if timestamp is None:
        errors.append("missing_timestamp")
        timestamp = 0.0
    market_dict.setdefault("timestamp", timestamp)
    feature_dict.setdefault("timestamp", timestamp)

    spread = _coerce_float(market_dict.get("spread") or feature_dict.get("spread"), "spread", errors)
    if spread is None and bid is not None and ask is not None and price:
        spread = (ask - bid) / price
    if spread is not None:
        market_dict.setdefault("spread", spread)
        feature_dict.setdefault("spread", spread)

    spread_bps = _coerce_float(
        market_dict.get("spread_bps") or feature_dict.get("spread_bps"),
        "spread_bps",
        errors,
    )
    if spread_bps is None and spread is not None and price:
        spread_bps = spread * 10000.0
    if spread_bps is not None:
        market_dict.setdefault("spread_bps", spread_bps)

    return StageInputs(
        symbol=symbol,
        market_context=market_dict,
        features=feature_dict,
        errors=errors,
    )


def _to_dict(value: Any) -> Dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    if hasattr(value, "__dict__"):
        return dict(value.__dict__)
    return {}


def _coerce_float(value: Any, field: str, errors: List[str]) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        errors.append(f"invalid_{field}")
        return None
