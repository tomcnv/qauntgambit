"""Unified confirmation policy configuration loader."""

from __future__ import annotations

import json
import os
from typing import Any, Dict, Mapping, Optional

from quantgambit.observability.logger import log_info, log_warning
from quantgambit.signals.confirmation import (
    ConfirmationPolicyConfig,
    ConfirmationWeights,
    EntryPolicyConfig,
    ExitPolicyConfig,
    StrategyPolicyOverride,
    default_policy_config_from_env,
)
from quantgambit.signals.confirmation.types import ConfirmationOverrideBounds


def _to_bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes"}


def _to_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _to_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _parse_json_env(key: str) -> Optional[dict[str, Any]]:
    raw = os.getenv(key)
    if not raw or not raw.strip():
        return None
    try:
        payload = json.loads(raw)
        if isinstance(payload, dict):
            return payload
    except Exception as exc:
        log_warning("confirmation_policy_json_parse_failed", env=key, error=str(exc))
    return None


def _build_strategy_overrides(raw: Mapping[str, Any]) -> Dict[str, StrategyPolicyOverride]:
    overrides: Dict[str, StrategyPolicyOverride] = {}
    for strategy_id, value in raw.items():
        if not isinstance(value, dict):
            continue

        raw_weights = value.get("weights") if isinstance(value.get("weights"), dict) else {}
        weights = None
        if raw_weights:
            weights = ConfirmationWeights(
                trend=_to_float(raw_weights.get("trend"), 1.0),
                flow=_to_float(raw_weights.get("flow"), 1.0),
                risk_stability=_to_float(raw_weights.get("risk_stability"), 1.0),
            )

        thresholds = value.get("thresholds") if isinstance(value.get("thresholds"), dict) else value
        overrides[str(strategy_id)] = StrategyPolicyOverride(
            weights=weights,
            entry_min_confidence=(
                _to_float(thresholds.get("entry_min_confidence"), 0.0)
                if "entry_min_confidence" in thresholds else None
            ),
            entry_min_votes=(
                _to_int(thresholds.get("entry_min_votes"), 0)
                if "entry_min_votes" in thresholds else None
            ),
            exit_min_confidence=(
                _to_float(thresholds.get("exit_min_confidence"), 0.0)
                if "exit_min_confidence" in thresholds else None
            ),
            exit_min_votes=(
                _to_int(thresholds.get("exit_min_votes"), 0)
                if "exit_min_votes" in thresholds else None
            ),
        )
    return overrides


def _merge_shadow_overrides(base: ConfirmationPolicyConfig, overrides: Optional[Dict[str, Any]]) -> ConfirmationPolicyConfig:
    if not overrides:
        return base

    nested = overrides.get("confirmation_policy")
    if not isinstance(nested, dict):
        nested = {}

    combined: Dict[str, Any] = dict(nested)
    for key, value in overrides.items():
        if not str(key).startswith("confirmation_policy_"):
            continue
        short = str(key)[len("confirmation_policy_"):]
        combined[short] = value

    if not combined:
        return base

    weights = base.weights
    entry = base.entry
    exit_policy = base.exit_non_emergency

    if any(k in combined for k in {"weight_trend", "weight_flow", "weight_risk_stability"}):
        weights = ConfirmationWeights(
            trend=_to_float(combined.get("weight_trend"), weights.trend),
            flow=_to_float(combined.get("weight_flow"), weights.flow),
            risk_stability=_to_float(combined.get("weight_risk_stability"), weights.risk_stability),
        )

    if any(k in combined for k in {"entry_min_confidence", "entry_min_votes"}):
        entry = EntryPolicyConfig(
            min_confidence=_to_float(combined.get("entry_min_confidence"), entry.min_confidence),
            min_votes=_to_int(combined.get("entry_min_votes"), entry.min_votes),
        )

    if any(k in combined for k in {"exit_min_confidence", "exit_min_votes"}):
        exit_policy = ExitPolicyConfig(
            min_confidence=_to_float(combined.get("exit_min_confidence"), exit_policy.min_confidence),
            min_votes=_to_int(combined.get("exit_min_votes"), exit_policy.min_votes),
        )

    mode = str(combined.get("mode", base.mode)).strip().lower()
    if mode not in {"shadow", "enforce"}:
        mode = base.mode

    enabled = _to_bool(combined.get("enabled"), base.enabled)
    version = str(combined.get("version", base.version))

    strategy_overrides = base.strategy_overrides
    raw_overrides = combined.get("strategy_overrides")
    if isinstance(raw_overrides, dict):
        strategy_overrides = _build_strategy_overrides(raw_overrides)

    return ConfirmationPolicyConfig(
        enabled=enabled,
        mode=mode,
        version=version,
        weights=weights,
        entry=entry,
        exit_non_emergency=exit_policy,
        override_bounds=base.override_bounds,
        strategy_overrides=strategy_overrides,
    )


def validate_confirmation_policy_config(config: ConfirmationPolicyConfig) -> None:
    bounds = config.override_bounds

    def _validate_weight(value: float, field: str) -> None:
        if value < bounds.min_weight or value > bounds.max_weight:
            raise ValueError(f"{field} out of bounds: {value}")

    _validate_weight(config.weights.trend, "weights.trend")
    _validate_weight(config.weights.flow, "weights.flow")
    _validate_weight(config.weights.risk_stability, "weights.risk_stability")

    if config.entry.min_confidence < bounds.min_confidence or config.entry.min_confidence > bounds.max_confidence:
        raise ValueError(f"entry.min_confidence out of bounds: {config.entry.min_confidence}")
    if config.exit_non_emergency.min_confidence < bounds.min_confidence or config.exit_non_emergency.min_confidence > bounds.max_confidence:
        raise ValueError(f"exit_non_emergency.min_confidence out of bounds: {config.exit_non_emergency.min_confidence}")
    if config.entry.min_votes < bounds.min_votes or config.entry.min_votes > bounds.max_votes:
        raise ValueError(f"entry.min_votes out of bounds: {config.entry.min_votes}")
    if config.exit_non_emergency.min_votes < bounds.min_votes or config.exit_non_emergency.min_votes > bounds.max_votes:
        raise ValueError(f"exit_non_emergency.min_votes out of bounds: {config.exit_non_emergency.min_votes}")

    for strategy_id, override in config.strategy_overrides.items():
        if override.weights is not None:
            _validate_weight(override.weights.trend, f"strategy_overrides[{strategy_id}].weights.trend")
            _validate_weight(override.weights.flow, f"strategy_overrides[{strategy_id}].weights.flow")
            _validate_weight(override.weights.risk_stability, f"strategy_overrides[{strategy_id}].weights.risk_stability")

        if override.entry_min_confidence is not None:
            if override.entry_min_confidence < bounds.min_confidence or override.entry_min_confidence > bounds.max_confidence:
                raise ValueError(f"strategy_overrides[{strategy_id}].entry_min_confidence out of bounds: {override.entry_min_confidence}")
        if override.exit_min_confidence is not None:
            if override.exit_min_confidence < bounds.min_confidence or override.exit_min_confidence > bounds.max_confidence:
                raise ValueError(f"strategy_overrides[{strategy_id}].exit_min_confidence out of bounds: {override.exit_min_confidence}")
        if override.entry_min_votes is not None:
            if override.entry_min_votes < bounds.min_votes or override.entry_min_votes > bounds.max_votes:
                raise ValueError(f"strategy_overrides[{strategy_id}].entry_min_votes out of bounds: {override.entry_min_votes}")
        if override.exit_min_votes is not None:
            if override.exit_min_votes < bounds.min_votes or override.exit_min_votes > bounds.max_votes:
                raise ValueError(f"strategy_overrides[{strategy_id}].exit_min_votes out of bounds: {override.exit_min_votes}")


def load_confirmation_policy_config(shadow_overrides: Optional[Dict[str, Any]] = None) -> ConfirmationPolicyConfig:
    """Load confirmation policy from env and optional runtime overrides.

    Env supports either fine-grained keys or JSON payloads:
    - `CONFIRMATION_POLICY_CONFIG_JSON`: full config payload
    - `CONFIRMATION_POLICY_STRATEGY_OVERRIDES_JSON`: per-strategy override map

    `shadow_overrides` is used by shadow-engine creation for comparative runs.
    """
    base = default_policy_config_from_env()

    config_json = _parse_json_env("CONFIRMATION_POLICY_CONFIG_JSON") or {}
    strategy_overrides_json = _parse_json_env("CONFIRMATION_POLICY_STRATEGY_OVERRIDES_JSON") or {}

    bounds = ConfirmationOverrideBounds(
        min_weight=_to_float(config_json.get("override_bounds", {}).get("min_weight"), base.override_bounds.min_weight),
        max_weight=_to_float(config_json.get("override_bounds", {}).get("max_weight"), base.override_bounds.max_weight),
        min_confidence=_to_float(config_json.get("override_bounds", {}).get("min_confidence"), base.override_bounds.min_confidence),
        max_confidence=_to_float(config_json.get("override_bounds", {}).get("max_confidence"), base.override_bounds.max_confidence),
        min_votes=_to_int(config_json.get("override_bounds", {}).get("min_votes"), base.override_bounds.min_votes),
        max_votes=_to_int(config_json.get("override_bounds", {}).get("max_votes"), base.override_bounds.max_votes),
    )

    weights_payload = config_json.get("weights") if isinstance(config_json.get("weights"), dict) else {}
    weights = ConfirmationWeights(
        trend=_to_float(weights_payload.get("trend"), base.weights.trend),
        flow=_to_float(weights_payload.get("flow"), base.weights.flow),
        risk_stability=_to_float(weights_payload.get("risk_stability"), base.weights.risk_stability),
    )

    entry_payload = config_json.get("entry") if isinstance(config_json.get("entry"), dict) else {}
    entry = EntryPolicyConfig(
        min_confidence=_to_float(entry_payload.get("min_confidence"), base.entry.min_confidence),
        min_votes=_to_int(entry_payload.get("min_votes"), base.entry.min_votes),
    )

    exit_payload = config_json.get("exit_non_emergency") if isinstance(config_json.get("exit_non_emergency"), dict) else {}
    exit_policy = ExitPolicyConfig(
        min_confidence=_to_float(exit_payload.get("min_confidence"), base.exit_non_emergency.min_confidence),
        min_votes=_to_int(exit_payload.get("min_votes"), base.exit_non_emergency.min_votes),
    )

    strategy_overrides = base.strategy_overrides
    if strategy_overrides_json:
        strategy_overrides = _build_strategy_overrides(strategy_overrides_json)
    elif isinstance(config_json.get("strategy_overrides"), dict):
        strategy_overrides = _build_strategy_overrides(config_json["strategy_overrides"])

    mode = str(config_json.get("mode", base.mode)).strip().lower()
    if mode not in {"shadow", "enforce"}:
        mode = base.mode

    config = ConfirmationPolicyConfig(
        enabled=_to_bool(config_json.get("enabled"), base.enabled),
        mode=mode,
        version=str(config_json.get("version", base.version)),
        weights=weights,
        entry=entry,
        exit_non_emergency=exit_policy,
        override_bounds=bounds,
        strategy_overrides=strategy_overrides,
    )

    config = _merge_shadow_overrides(config, shadow_overrides)

    validate_confirmation_policy_config(config)
    log_info(
        "confirmation_policy_config_loaded",
        enabled=config.enabled,
        mode=config.mode,
        version=config.version,
        strategy_override_count=len(config.strategy_overrides),
        entry_min_confidence=config.entry.min_confidence,
        exit_min_confidence=config.exit_non_emergency.min_confidence,
        entry_min_votes=config.entry.min_votes,
        exit_min_votes=config.exit_non_emergency.min_votes,
    )
    return config
