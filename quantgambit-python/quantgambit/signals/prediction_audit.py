"""Shared helpers for prediction/side telemetry normalization."""

from __future__ import annotations

from typing import Any, Optional, Dict

from quantgambit.ingest.schemas import coerce_float


def normalize_side(value: Optional[str]) -> Optional[str]:
    side = str(value or "").strip().lower()
    if side in {"long", "buy", "up"}:
        return "long"
    if side in {"short", "sell", "down"}:
        return "short"
    return None


def build_directional_fields(prediction: Optional[dict[str, Any]], signal_side: Optional[str]) -> dict[str, Any]:
    fields: Dict[str, Any] = {}
    signal_side_norm = normalize_side(signal_side)
    if signal_side_norm is not None:
        fields["signal_side"] = signal_side_norm

    if not isinstance(prediction, dict):
        fields["prediction_present"] = False
        fields["direction_alignment_match"] = None
        return fields

    fields["prediction_present"] = True
    direction = str(prediction.get("direction") or "").strip().lower()
    source = prediction.get("source")
    p_long = coerce_float(prediction.get("p_long_win"))
    p_short = coerce_float(prediction.get("p_short_win"))
    probs = prediction.get("probs")
    if (p_long is None or p_short is None) and isinstance(probs, dict):
        p_long = coerce_float(p_long if p_long is not None else probs.get("p_long_win"))
        p_short = coerce_float(p_short if p_short is not None else probs.get("p_short_win"))

    model_side = None
    p_margin = None
    if p_long is not None and p_short is not None:
        model_side = "long" if p_long >= p_short else "short"
        p_margin = abs(float(p_long) - float(p_short))
    else:
        model_side = normalize_side(direction)

    if direction:
        fields["prediction_direction"] = direction
    if source is not None:
        fields["prediction_source"] = source
    if p_long is not None:
        fields["p_long_win"] = float(p_long)
    if p_short is not None:
        fields["p_short_win"] = float(p_short)
    if p_margin is not None:
        fields["p_margin"] = float(p_margin)
    if model_side is not None:
        fields["model_side"] = model_side
    if signal_side_norm is not None and model_side is not None:
        fields["direction_alignment_match"] = bool(signal_side_norm == model_side)
    else:
        fields["direction_alignment_match"] = None
    return fields
