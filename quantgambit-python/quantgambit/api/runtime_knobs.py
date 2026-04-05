"""Runtime knob catalog and validation helpers for dashboard config editing."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Dict, Iterable, Optional


@dataclass(frozen=True)
class KnobSpec:
    key: str
    section: str
    label: str
    dtype: str
    minimum: Optional[float] = None
    maximum: Optional[float] = None
    default: Optional[Any] = None
    aliases: tuple[str, ...] = ()


_SPECS: tuple[KnobSpec, ...] = (
    KnobSpec("risk_per_trade_pct", "risk_config", "Risk Per Trade %", "float", 0.01, 10.0, 0.5, ("riskPerTradePct", "positionSizePct")),
    KnobSpec("max_total_exposure_pct", "risk_config", "Max Total Exposure %", "float", 1.0, 200.0, 100.0, ("maxTotalExposurePct",)),
    KnobSpec("max_exposure_per_symbol_pct", "risk_config", "Max Exposure Per Symbol %", "float", 0.5, 100.0, 40.0, ("maxExposurePerSymbolPct",)),
    KnobSpec("max_positions", "risk_config", "Max Positions", "int", 1, 100, 3, ("maxPositions",)),
    KnobSpec("max_positions_per_symbol", "risk_config", "Max Positions Per Symbol", "int", 1, 20, 1, ("maxPositionsPerSymbol",)),
    KnobSpec("max_daily_drawdown_pct", "risk_config", "Max Daily Drawdown %", "float", 0.1, 50.0, 5.0, ("maxDailyDrawdownPct", "maxDailyLossPct")),
    KnobSpec("max_drawdown_pct", "risk_config", "Max Drawdown %", "float", 0.5, 80.0, 20.0, ("maxDrawdownPct",)),
    KnobSpec("max_leverage", "risk_config", "Max Leverage", "float", 1.0, 100.0, 5.0, ("maxLeverage",)),
    KnobSpec("min_order_interval_sec", "execution_config", "Min Order Interval Sec", "float", 0.0, 3600.0, 60.0, ("minOrderIntervalSec", "minTradeIntervalSec")),
    KnobSpec("max_retries", "execution_config", "Max Order Retries", "int", 0, 20, 3, ("maxRetries",)),
    KnobSpec("retry_delay_sec", "execution_config", "Order Retry Delay Sec", "float", 0.0, 120.0, 1.0, ("retryDelaySec",)),
    KnobSpec("execution_timeout_sec", "execution_config", "Execution Timeout Sec", "float", 0.1, 600.0, 15.0, ("executionTimeoutSec",)),
    KnobSpec("max_slippage_bps", "execution_config", "Max Slippage Bps", "float", 0.0, 200.0, 20.0, ("maxSlippageBps",)),
    KnobSpec("default_stop_loss_pct", "execution_config", "Default Stop Loss %", "float", 0.01, 30.0, 0.4, ("defaultStopLossPct", "stopLossPct")),
    KnobSpec("default_take_profit_pct", "execution_config", "Default Take Profit %", "float", 0.01, 80.0, 0.8, ("defaultTakeProfitPct", "takeProfitPct")),
    KnobSpec("order_intent_max_age_sec", "execution_config", "Order Intent Max Age Sec", "float", 1.0, 86400.0, 900.0, ("orderIntentMaxAgeSec",)),
    KnobSpec("position_continuation_gate_enabled", "profile_overrides", "Position Continuation Gate", "bool", default=False),
    KnobSpec("enable_unified_confirmation_policy", "profile_overrides", "Unified Confirmation Policy", "bool", default=False),
    KnobSpec("prediction_score_gate_enabled", "profile_overrides", "Prediction Score Gate", "bool", default=False),
)

_SPEC_BY_KEY: Dict[str, KnobSpec] = {item.key: item for item in _SPECS}
_SPEC_BY_ALIAS: Dict[str, KnobSpec] = {}
for spec in _SPECS:
    for alias in spec.aliases:
        _SPEC_BY_ALIAS[alias] = spec


def knob_catalog() -> list[dict[str, Any]]:
    return [
        {
            "key": item.key,
            "section": item.section,
            "label": item.label,
            "type": item.dtype,
            "min": item.minimum,
            "max": item.maximum,
            "default": item.default,
        }
        for item in _SPECS
    ]


def validate_section_patch(
    section: str, patch: dict[str, Any], *, report_unknown: bool = True
) -> tuple[dict[str, Any], list[str]]:
    cleaned: dict[str, Any] = {}
    errors: list[str] = []
    for raw_key, raw in patch.items():
        key = str(raw_key)
        spec = _SPEC_BY_KEY.get(key) or _SPEC_BY_ALIAS.get(key)
        if not spec:
            if report_unknown:
                errors.append(f"unknown_key:{section}.{key}")
            continue
        if spec.section != section:
            errors.append(f"wrong_section:{section}.{key}->expected:{spec.section}")
            continue
        value, err = _coerce_value(raw, spec)
        if err:
            errors.append(f"{section}.{spec.key}:{err}")
            continue
        cleaned[spec.key] = value
    return cleaned, errors


def merge_runtime_config(
    current: dict[str, Any],
    *,
    risk_patch: Optional[dict[str, Any]] = None,
    execution_patch: Optional[dict[str, Any]] = None,
    profile_patch: Optional[dict[str, Any]] = None,
    enabled_symbols: Optional[Iterable[str]] = None,
) -> tuple[dict[str, Any], list[str]]:
    next_config = {
        "risk_config": _as_dict(current.get("risk_config")),
        "execution_config": _as_dict(current.get("execution_config")),
        "profile_overrides": _as_dict(current.get("profile_overrides")),
        "enabled_symbols": _as_list(current.get("enabled_symbols")),
    }
    errors: list[str] = []

    if risk_patch is not None:
        cleaned, err = validate_section_patch("risk_config", risk_patch, report_unknown=False)
        errors.extend(err)
        next_config["risk_config"].update(cleaned)
    if execution_patch is not None:
        cleaned, err = validate_section_patch("execution_config", execution_patch, report_unknown=False)
        errors.extend(err)
        next_config["execution_config"].update(cleaned)
    if profile_patch is not None:
        cleaned, err = validate_section_patch("profile_overrides", profile_patch, report_unknown=False)
        errors.extend(err)
        next_config["profile_overrides"].update(cleaned)
    if enabled_symbols is not None:
        symbols: list[str] = []
        for token in enabled_symbols:
            sym = str(token or "").strip().upper()
            if sym:
                symbols.append(sym)
        next_config["enabled_symbols"] = list(dict.fromkeys(symbols))
    _apply_defaults(next_config)
    errors.extend(_validate_cross_constraints(next_config))
    return next_config, errors


def _apply_defaults(next_config: dict[str, Any]) -> None:
    for spec in _SPECS:
        section = next_config.get(spec.section) or {}
        if not isinstance(section, dict):
            continue
        if spec.default is None:
            continue
        has_existing = spec.key in section or any(alias in section for alias in spec.aliases)
        if not has_existing:
            section[spec.key] = spec.default
        next_config[spec.section] = section


def _read_value(section: dict[str, Any], key: str) -> Any:
    spec = _SPEC_BY_KEY.get(key)
    if not spec:
        return section.get(key)
    if key in section:
        return section.get(key)
    for alias in spec.aliases:
        if alias in section:
            return section.get(alias)
    return None


def _validate_cross_constraints(next_config: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    risk = next_config.get("risk_config") or {}
    execution = next_config.get("execution_config") or {}
    if isinstance(risk, dict):
        max_positions = _coerce_int(_read_value(risk, "max_positions"))
        per_symbol_positions = _coerce_int(_read_value(risk, "max_positions_per_symbol"))
        if max_positions is not None and per_symbol_positions is not None and per_symbol_positions > max_positions:
            errors.append("risk_config.max_positions_per_symbol:gt_max_positions")

        max_total_exposure = _coerce_float(_read_value(risk, "max_total_exposure_pct"))
        per_symbol_exposure = _coerce_float(_read_value(risk, "max_exposure_per_symbol_pct"))
        if (
            max_total_exposure is not None
            and per_symbol_exposure is not None
            and per_symbol_exposure > max_total_exposure
        ):
            errors.append("risk_config.max_exposure_per_symbol_pct:gt_max_total_exposure_pct")

    if isinstance(execution, dict):
        sl = _coerce_float(_read_value(execution, "default_stop_loss_pct"))
        tp = _coerce_float(_read_value(execution, "default_take_profit_pct"))
        if sl is not None and tp is not None and tp < sl:
            errors.append("execution_config.default_take_profit_pct:lt_default_stop_loss_pct")
    return errors


def _coerce_value(raw: Any, spec: KnobSpec) -> tuple[Any, Optional[str]]:
    if spec.dtype == "bool":
        if isinstance(raw, bool):
            return raw, None
        if isinstance(raw, str):
            val = raw.strip().lower()
            if val in {"1", "true", "yes", "on"}:
                return True, None
            if val in {"0", "false", "no", "off"}:
                return False, None
        return None, "expected_bool"

    if spec.dtype == "int":
        try:
            value = int(raw)
        except (TypeError, ValueError):
            return None, "expected_int"
        if spec.minimum is not None and value < spec.minimum:
            return None, f"lt_min:{spec.minimum}"
        if spec.maximum is not None and value > spec.maximum:
            return None, f"gt_max:{spec.maximum}"
        return value, None

    if spec.dtype == "float":
        try:
            value = float(raw)
        except (TypeError, ValueError):
            return None, "expected_float"
        if spec.minimum is not None and value < spec.minimum:
            return None, f"lt_min:{spec.minimum}"
        if spec.maximum is not None and value > spec.maximum:
            return None, f"gt_max:{spec.maximum}"
        return value, None

    return None, "unsupported_type"


def _coerce_int(raw: Any) -> Optional[int]:
    try:
        if raw is None:
            return None
        return int(raw)
    except Exception:
        return None


def _coerce_float(raw: Any) -> Optional[float]:
    try:
        if raw is None:
            return None
        return float(raw)
    except Exception:
        return None


def _as_dict(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return dict(raw)
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return dict(parsed)
        except Exception:
            return {}
    return {}


def _as_list(raw: Any) -> list[Any]:
    if isinstance(raw, list):
        return list(raw)
    if isinstance(raw, tuple):
        return list(raw)
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                return list(parsed)
        except Exception:
            return []
    return []
