"""Unified confirmation policy engine for entries and non-emergency exits."""

from __future__ import annotations

import os
from dataclasses import replace
from typing import Dict, Optional

from quantgambit.observability.logger import log_warning
from quantgambit.signals.confirmation.evidence import (
    evaluate_exit_orderflow,
    evaluate_exit_price_level,
    evaluate_exit_trend_reversal,
    evaluate_flow,
    evaluate_risk_stability,
    evaluate_trend,
    to_float,
)
from quantgambit.signals.confirmation.types import (
    ConfirmationPolicyConfig,
    ConfirmationPolicyResult,
    ConfirmationWeights,
    StrategyPolicyOverride,
)


class ConfirmationPolicyEngine:
    """Single source of truth for confirmation policy decisions."""

    def __init__(self, config: Optional[ConfirmationPolicyConfig] = None):
        self.config = config or default_policy_config_from_env()
        self._entry_flow_min_magnitude = self._clamp_unit_float(
            os.getenv("CONFIRMATION_POLICY_MIN_FLOW_MAGNITUDE"),
            0.5,
        )
        self._entry_flow_min_magnitude_by_symbol = self._parse_symbol_float_map(
            os.getenv("CONFIRMATION_POLICY_MIN_FLOW_MAGNITUDE_BY_SYMBOL", "")
        )

    def evaluate_entry(
        self,
        *,
        side: str,
        flow: float,
        trend: float,
        market_context: Optional[dict],
        strategy_id: Optional[str],
        requires_flow_reversal: bool,
        required_flow_direction: Optional[str],
        max_adverse_trend: float,
    ) -> ConfirmationPolicyResult:
        market_context = market_context or {}
        if not self.config.enabled:
            return self._result(
                confirm=True,
                confidence=1.0,
                votes={"trend": True, "flow": True, "risk_stability": True},
                failed_guards=[],
                reasons=["policy_disabled"],
                passed=["policy_disabled"],
            )

        failed_guards = self._evaluate_hard_guards(market_context)
        weights = self._resolve_weights(strategy_id)
        entry_threshold = self._resolve_entry_confidence(strategy_id)
        entry_votes_required = self._resolve_entry_votes(strategy_id)

        evidence_votes: Dict[str, bool] = {}
        reasons = []
        passed = []

        trend_ok, trend_reason, _ = evaluate_trend(side, trend, max_adverse_trend)
        evidence_votes["trend"] = trend_ok
        reasons.append(trend_reason)
        if trend_ok:
            passed.append(trend_reason)

        if requires_flow_reversal:
            symbol = str(market_context.get("symbol") or "").upper()
            flow_min_magnitude = self._entry_flow_min_magnitude_by_symbol.get(
                symbol,
                self._entry_flow_min_magnitude,
            )
            flow_ok, flow_reason, _ = evaluate_flow(
                side,
                flow,
                min_magnitude=flow_min_magnitude,
                required_direction=required_flow_direction,
            )
            evidence_votes["flow"] = flow_ok
            reasons.append(flow_reason)
            if flow_ok:
                passed.append(flow_reason)
        else:
            evidence_votes["flow"] = True
            reasons.append("flow_optional")
            passed.append("flow_optional")

        risk_ok, risk_reason, _ = evaluate_risk_stability(market_context)
        evidence_votes["risk_stability"] = risk_ok
        reasons.append(risk_reason)
        if risk_ok:
            passed.append(risk_reason)

        confidence = self._weighted_confidence(evidence_votes, weights)
        vote_count = sum(1 for v in evidence_votes.values() if v)

        confirm = not failed_guards and confidence >= entry_threshold and vote_count >= entry_votes_required
        if not confirm and not failed_guards:
            reasons.append("entry_threshold_not_met")

        return self._result(
            confirm=confirm,
            confidence=confidence,
            votes=evidence_votes,
            failed_guards=failed_guards,
            reasons=reasons,
            passed=passed,
        )

    def evaluate_exit_non_emergency(
        self,
        *,
        side: str,
        pnl_pct: float,
        current_price: float,
        entry_price: float,
        market_context: Optional[dict],
        strategy_id: Optional[str],
    ) -> ConfirmationPolicyResult:
        market_context = market_context or {}
        if not self.config.enabled:
            return self._result(
                confirm=True,
                confidence=1.0,
                votes={"trend": True, "flow": True, "risk_stability": True},
                failed_guards=[],
                reasons=["policy_disabled"],
                passed=["policy_disabled"],
            )

        failed_guards = self._evaluate_hard_guards(market_context, allow_stale=True)
        weights = self._resolve_weights(strategy_id)
        min_confidence = self._resolve_exit_confidence(strategy_id)
        min_votes = self._resolve_exit_votes(strategy_id)

        evidence_votes: Dict[str, bool] = {}
        reasons = []
        passed = []

        trend_bias = market_context.get("trend_bias") or market_context.get("trend_direction")
        trend_confidence = to_float(market_context.get("trend_confidence"), 0.0)
        if trend_confidence <= 0.0:
            trend_strength = to_float(market_context.get("trend_strength"), 0.0)
            trend_confidence = min(1.0, abs(trend_strength) * 100.0)
        trend_ok, trend_reason = evaluate_exit_trend_reversal(side, trend_bias, trend_confidence)
        evidence_votes["trend"] = trend_ok
        reasons.append(trend_reason)
        if trend_ok:
            passed.append(trend_reason)

        orderflow = to_float(market_context.get("orderflow_imbalance"), 0.0)
        flow_ok, flow_reason = evaluate_exit_orderflow(side, orderflow)
        evidence_votes["flow"] = flow_ok
        reasons.append(flow_reason)
        if flow_ok:
            passed.append(flow_reason)

        risk_votes = []
        risk_pass_reasons = []

        level_ok, level_reason = evaluate_exit_price_level(side, market_context, current_price or entry_price)
        risk_votes.append(level_ok)
        if level_ok:
            risk_pass_reasons.append(level_reason)

        vol_regime = str(market_context.get("volatility_regime") or "normal").lower()
        vol_pct = to_float(market_context.get("volatility_percentile"), 0.5)
        vol_spike = vol_regime == "high" and vol_pct > 0.8
        risk_votes.append(vol_spike)
        if vol_spike:
            risk_pass_reasons.append(f"volatility_spike (pct={vol_pct:.2f})")

        is_underwater = pnl_pct < -0.3
        adverse_underwater = False
        if is_underwater:
            if side == "long" and (trend_bias in {"short", "down"} or orderflow < -0.15):
                adverse_underwater = True
            if side == "short" and (trend_bias in {"long", "up"} or orderflow > 0.15):
                adverse_underwater = True
        risk_votes.append(adverse_underwater)
        if adverse_underwater:
            risk_pass_reasons.append(f"underwater_adverse_conditions (pnl={pnl_pct:.2f}%)")

        conservative_underwater = str(market_context.get("risk_mode") or "normal").lower() == "conservative" and is_underwater
        risk_votes.append(conservative_underwater)
        if conservative_underwater:
            risk_pass_reasons.append("conservative_mode_underwater")

        risk_ok = any(risk_votes)
        evidence_votes["risk_stability"] = risk_ok
        if risk_ok:
            passed.extend(risk_pass_reasons)
            reasons.extend(risk_pass_reasons)
        else:
            reasons.append("risk_no_exit_signal")

        confidence = self._weighted_confidence(evidence_votes, weights)
        vote_count = sum(1 for value in evidence_votes.values() if value)

        confirm = not failed_guards and confidence >= min_confidence and vote_count >= min_votes
        if not confirm and not failed_guards:
            reasons.append("exit_threshold_not_met")

        return self._result(
            confirm=confirm,
            confidence=confidence,
            votes=evidence_votes,
            failed_guards=failed_guards,
            reasons=reasons,
            passed=passed,
        )

    def _evaluate_hard_guards(self, market_context: dict, allow_stale: bool = False) -> list[str]:
        guards = []
        if str(market_context.get("risk_mode") or "normal").lower() == "off":
            guards.append("guard_risk_mode_off")
        if not allow_stale:
            data_quality_status = str(market_context.get("data_quality_status") or "ok").lower()
            if data_quality_status == "stale":
                guards.append("guard_data_stale")
        return guards

    def _resolve_override(self, strategy_id: Optional[str]) -> Optional[StrategyPolicyOverride]:
        if not strategy_id:
            return None
        override = self.config.strategy_overrides.get(strategy_id)
        if not override:
            return None
        return override

    def _resolve_weights(self, strategy_id: Optional[str]) -> ConfirmationWeights:
        weights = self.config.weights
        override = self._resolve_override(strategy_id)
        if not override or not override.weights:
            return weights

        bounded = []
        bounds = self.config.override_bounds
        for value in (override.weights.trend, override.weights.flow, override.weights.risk_stability):
            if value < bounds.min_weight or value > bounds.max_weight:
                raise ValueError(f"confirmation weight override out of bounds: {value}")
            bounded.append(value)
        return ConfirmationWeights(*bounded)

    def _resolve_entry_confidence(self, strategy_id: Optional[str]) -> float:
        value = self.config.entry.min_confidence
        override = self._resolve_override(strategy_id)
        if override and override.entry_min_confidence is not None:
            value = override.entry_min_confidence
        bounds = self.config.override_bounds
        if value < bounds.min_confidence or value > bounds.max_confidence:
            raise ValueError(f"entry confirmation threshold out of bounds: {value}")
        return value

    def _resolve_entry_votes(self, strategy_id: Optional[str]) -> int:
        value = self.config.entry.min_votes
        override = self._resolve_override(strategy_id)
        if override and override.entry_min_votes is not None:
            value = int(override.entry_min_votes)
        bounds = self.config.override_bounds
        if value < bounds.min_votes or value > bounds.max_votes:
            raise ValueError(f"entry min votes out of bounds: {value}")
        return value

    def _resolve_exit_confidence(self, strategy_id: Optional[str]) -> float:
        value = self.config.exit_non_emergency.min_confidence
        override = self._resolve_override(strategy_id)
        if override and override.exit_min_confidence is not None:
            value = override.exit_min_confidence
        bounds = self.config.override_bounds
        if value < bounds.min_confidence or value > bounds.max_confidence:
            raise ValueError(f"exit confirmation threshold out of bounds: {value}")
        return value

    def _resolve_exit_votes(self, strategy_id: Optional[str]) -> int:
        value = self.config.exit_non_emergency.min_votes
        override = self._resolve_override(strategy_id)
        if override and override.exit_min_votes is not None:
            value = int(override.exit_min_votes)
        bounds = self.config.override_bounds
        if value < bounds.min_votes or value > bounds.max_votes:
            raise ValueError(f"exit min votes out of bounds: {value}")
        return value

    @staticmethod
    def _weighted_confidence(votes: Dict[str, bool], weights: ConfirmationWeights) -> float:
        weight_map = {
            "trend": weights.trend,
            "flow": weights.flow,
            "risk_stability": weights.risk_stability,
        }
        total_weight = sum(weight_map.values())
        if total_weight <= 0:
            return 0.0
        score = sum(weight_map[name] for name, passed in votes.items() if passed)
        return max(0.0, min(1.0, score / total_weight))

    def _result(
        self,
        *,
        confirm: bool,
        confidence: float,
        votes: Dict[str, bool],
        failed_guards: list[str],
        reasons: list[str],
        passed: list[str],
    ) -> ConfirmationPolicyResult:
        return ConfirmationPolicyResult(
            confirm=confirm,
            confidence=confidence,
            evidence_votes=dict(votes),
            failed_hard_guards=list(failed_guards),
            decision_reason_codes=list(reasons),
            passed_evidence=list(passed),
            mode=self.config.mode,
            version=self.config.version,
        )

    @staticmethod
    def _clamp_unit_float(raw: Optional[str], default: float) -> float:
        try:
            value = float(raw) if raw is not None else default
        except (TypeError, ValueError):
            value = default
        return max(0.0, min(1.0, value))

    @classmethod
    def _parse_symbol_float_map(cls, raw: str) -> Dict[str, float]:
        out: Dict[str, float] = {}
        if not raw:
            return out
        for item in raw.split(","):
            token = item.strip()
            if not token or ":" not in token:
                continue
            symbol, value_text = token.split(":", 1)
            symbol = symbol.strip().upper()
            if not symbol:
                continue
            out[symbol] = cls._clamp_unit_float(value_text.strip(), 0.5)
        return out


def default_policy_config_from_env() -> ConfirmationPolicyConfig:
    enabled = os.getenv("ENABLE_UNIFIED_CONFIRMATION_POLICY", "true").lower() in {"1", "true", "yes"}
    mode = os.getenv("CONFIRMATION_POLICY_MODE", "shadow").strip().lower()
    if mode not in {"shadow", "enforce"}:
        log_warning("invalid_confirmation_policy_mode", mode=mode)
        mode = "shadow"

    try:
        entry_min_confidence = float(os.getenv("CONFIRMATION_POLICY_ENTRY_MIN_CONFIDENCE", "0.67"))
        exit_min_confidence = float(os.getenv("CONFIRMATION_POLICY_EXIT_MIN_CONFIDENCE", "0.50"))
        trend_weight = float(os.getenv("CONFIRMATION_POLICY_WEIGHT_TREND", "1.0"))
        flow_weight = float(os.getenv("CONFIRMATION_POLICY_WEIGHT_FLOW", "1.0"))
        risk_weight = float(os.getenv("CONFIRMATION_POLICY_WEIGHT_RISK_STABILITY", "1.0"))
        entry_min_votes = int(os.getenv("CONFIRMATION_POLICY_ENTRY_MIN_VOTES", "2"))
        exit_min_votes = int(os.getenv("CONFIRMATION_POLICY_EXIT_MIN_VOTES", "2"))
    except (TypeError, ValueError):
        log_warning("invalid_confirmation_policy_env", message="falling back to defaults")
        entry_min_confidence = 0.67
        exit_min_confidence = 0.50
        trend_weight = 1.0
        flow_weight = 1.0
        risk_weight = 1.0
        entry_min_votes = 2
        exit_min_votes = 2

    return ConfirmationPolicyConfig(
        enabled=enabled,
        mode=mode,
        version=os.getenv("CONFIRMATION_POLICY_VERSION", "v1"),
        weights=ConfirmationWeights(
            trend=trend_weight,
            flow=flow_weight,
            risk_stability=risk_weight,
        ),
        entry=replace(ConfirmationPolicyConfig().entry, min_confidence=entry_min_confidence, min_votes=entry_min_votes),
        exit_non_emergency=replace(
            ConfirmationPolicyConfig().exit_non_emergency,
            min_confidence=exit_min_confidence,
            min_votes=exit_min_votes,
        ),
    )
