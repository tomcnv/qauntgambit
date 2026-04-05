"""Evidence evaluators shared by entry and exit confirmation paths."""

from __future__ import annotations

from typing import Any, Optional, Tuple


def get_field(source: Any, key: str, default: Any = None) -> Any:
    if source is None:
        return default
    if isinstance(source, dict):
        return source.get(key, default)
    return getattr(source, key, default)


def normalize_side(side: Optional[str]) -> Optional[str]:
    if not isinstance(side, str):
        return None
    value = side.lower()
    if value == "buy":
        return "long"
    if value == "sell":
        return "short"
    if value in {"long", "short"}:
        return value
    return None


def to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def evaluate_flow(
    side: str,
    flow: float,
    min_magnitude: float,
    required_direction: Optional[str] = None,
) -> Tuple[bool, str, float]:
    if required_direction == "positive":
        passed = flow >= min_magnitude
        return passed, ("flow_positive" if passed else f"flow_not_positive (flow={flow:.2f}<{min_magnitude})"), abs(flow)
    if required_direction == "negative":
        passed = flow <= -min_magnitude
        return passed, ("flow_negative" if passed else f"flow_not_negative (flow={flow:.2f}>-{min_magnitude})"), abs(flow)

    if side == "long":
        passed = flow >= min_magnitude
        return passed, ("flow_supports_long" if passed else f"flow_not_positive_for_long (flow={flow:.2f}<{min_magnitude})"), abs(flow)
    passed = flow <= -min_magnitude
    return passed, ("flow_supports_short" if passed else f"flow_not_negative_for_short (flow={flow:.2f}>-{min_magnitude})"), abs(flow)


def evaluate_trend(side: str, trend: float, max_adverse: float) -> Tuple[bool, str, float]:
    if side == "long":
        passed = trend >= -max_adverse
        return passed, ("trend_allows_long" if passed else f"trend_too_bearish (trend={trend:.2f}<-{max_adverse})"), abs(trend)
    passed = trend <= max_adverse
    return passed, ("trend_allows_short" if passed else f"trend_too_bullish (trend={trend:.2f}>{max_adverse})"), abs(trend)


def evaluate_risk_stability(market_context: dict, pnl_pct: Optional[float] = None) -> Tuple[bool, str, float]:
    volatility_regime = str(market_context.get("volatility_regime") or "normal").lower()
    volatility_percentile = to_float(market_context.get("volatility_percentile"), 0.5)
    data_quality = str(market_context.get("data_quality_status") or "ok").lower()
    risk_mode = str(market_context.get("risk_mode") or "normal").lower()

    unstable = False
    reasons = []

    if volatility_regime in {"shock", "extreme"}:
        unstable = True
        reasons.append("volatility_regime_unstable")
    if volatility_regime == "high" and volatility_percentile > 0.9:
        unstable = True
        reasons.append("volatility_spike")
    if data_quality == "stale":
        unstable = True
        reasons.append("data_stale")
    if risk_mode == "off":
        unstable = True
        reasons.append("risk_mode_off")
    if pnl_pct is not None and pnl_pct < -1.0:
        unstable = True
        reasons.append("deep_drawdown")

    score = max(0.0, 1.0 - min(1.0, volatility_percentile))
    if unstable:
        return False, reasons[0] if reasons else "risk_unstable", score
    return True, "risk_stable", score


def evaluate_exit_trend_reversal(side: str, trend_bias: Optional[str], trend_confidence: float) -> Tuple[bool, str]:
    normalized = normalize_side(trend_bias)
    if trend_bias == "up":
        normalized = "long"
    elif trend_bias == "down":
        normalized = "short"
    if side == "long" and normalized == "short" and trend_confidence >= 0.3:
        return True, f"trend_reversal_short (conf={trend_confidence:.2f})"
    if side == "short" and normalized == "long" and trend_confidence >= 0.3:
        return True, f"trend_reversal_long (conf={trend_confidence:.2f})"
    return False, "trend_not_reversed"


def evaluate_exit_orderflow(side: str, orderflow_imbalance: float) -> Tuple[bool, str]:
    if side == "long" and orderflow_imbalance < -0.75:
        return True, f"orderflow_sell_pressure (imb={orderflow_imbalance:+.2f})"
    if side == "short" and orderflow_imbalance > 0.75:
        return True, f"orderflow_buy_pressure (imb={orderflow_imbalance:+.2f})"
    return False, "orderflow_not_adverse"


def evaluate_exit_price_level(side: str, market_context: dict, price: float) -> Tuple[bool, str]:
    if side == "long":
        distance_to_vah = market_context.get("distance_to_vah_pct")
        if distance_to_vah is None:
            raw = market_context.get("distance_to_vah")
            distance_to_vah = (to_float(raw) / price) if raw is not None and price > 0 else 1.0
        if abs(to_float(distance_to_vah, 1.0)) < 0.001:
            return True, "price_at_resistance_vah"
        return False, "not_at_resistance"

    distance_to_val = market_context.get("distance_to_val_pct")
    if distance_to_val is None:
        raw = market_context.get("distance_to_val")
        distance_to_val = (to_float(raw) / price) if raw is not None and price > 0 else 1.0
    if abs(to_float(distance_to_val, 1.0)) < 0.001:
        return True, "price_at_support_val"
    return False, "not_at_support"

