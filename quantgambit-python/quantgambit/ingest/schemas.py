"""Schemas for ingestion and feature events."""

from __future__ import annotations

from typing import Any, Dict, Iterable


def validate_market_tick(payload: Dict[str, Any]) -> None:
    required = {"symbol", "timestamp"}
    missing = required - set(payload.keys())
    if missing:
        raise ValueError(f"missing_fields:{','.join(sorted(missing))}")
    _validate_numeric(payload, "bid")
    _validate_numeric(payload, "ask")
    _validate_numeric(payload, "last")
    _validate_numeric(payload, "volume")


def validate_feature_snapshot(payload: Dict[str, Any]) -> None:
    required = {"symbol", "timestamp", "features", "market_context"}
    missing = required - set(payload.keys())
    if missing:
        raise ValueError(f"missing_fields:{','.join(sorted(missing))}")
    prediction = payload.get("prediction")
    if prediction is not None:
        validate_prediction_payload(prediction)


def validate_orderbook_snapshot(payload: Dict[str, Any]) -> None:
    required = {"symbol", "timestamp", "seq", "bids", "asks"}
    missing = required - set(payload.keys())
    if missing:
        raise ValueError(f"missing_fields:{','.join(sorted(missing))}")


def validate_orderbook_delta(payload: Dict[str, Any]) -> None:
    required = {"symbol", "timestamp", "seq", "bids", "asks"}
    missing = required - set(payload.keys())
    if missing:
        raise ValueError(f"missing_fields:{','.join(sorted(missing))}")


def validate_order_update(payload: Dict[str, Any]) -> None:
    required = {"symbol", "timestamp", "status", "side", "size"}
    missing = required - set(payload.keys())
    if missing:
        raise ValueError(f"missing_fields:{','.join(sorted(missing))}")


def validate_prediction_payload(payload: Dict[str, Any]) -> None:
    required = {"direction", "confidence", "timestamp"}
    missing = required - set(payload.keys())
    if missing:
        raise ValueError(f"missing_fields:{','.join(sorted(missing))}")


def validate_trade(payload: Dict[str, Any]) -> None:
    required = {"symbol", "timestamp", "price", "size", "side"}
    missing = required - set(payload.keys())
    if missing:
        raise ValueError(f"missing_fields:{','.join(sorted(missing))}")


def coerce_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _validate_numeric(payload: Dict[str, Any], key: str) -> None:
    if key not in payload:
        return
    value = payload.get(key)
    if value is None:
        return
    try:
        float(value)
    except (TypeError, ValueError):
        raise ValueError(f"invalid_{key}")


def coerce_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def compact_dict(data: Dict[str, Any], keys: Iterable[str]) -> Dict[str, Any]:
    return {key: data[key] for key in keys if key in data}
