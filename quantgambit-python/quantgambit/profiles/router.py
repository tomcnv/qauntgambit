"""Profile router interface."""

from __future__ import annotations

import logging
import os
import time
from typing import Optional


def _get_attr(source, key, default=None):
    if source is None:
        return default
    if isinstance(source, dict):
        return source.get(key, default)
    return getattr(source, key, default)


def _safe_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _build_context_vector(symbol: str, market_context, features):
    try:
        # IMPORTANT:
        # Do not instantiate ContextVector directly here. The canonical builder
        # (`build_context_vector`) derives session/hour_utc (and other fields)
        # from timestamp when not explicitly provided. Direct construction can
        # silently default hour_utc=0, which breaks session gating.
        from quantgambit.deeptrader_core.profiles.context_vector import (  # type: ignore
            ContextVector,
            ContextVectorInput,
            build_context_vector,
        )
    except Exception:
        return None
    if isinstance(market_context, ContextVector):
        return market_context
    nested = _get_attr(market_context, "context_vector")
    if isinstance(nested, dict):
        market_context = nested
    timestamp = _get_attr(market_context, "timestamp") or _get_attr(features, "timestamp") or time.time()
    price = _get_attr(market_context, "price") or _get_attr(features, "price") or _get_attr(features, "last")
    if price is None:
        return None
    values: dict = {"symbol": symbol, "timestamp": timestamp, "price": price}
    # ContextVectorInput is a strict dataclass. Keep this mapping explicit so
    # legacy feature keys do not crash runtime when the schema evolves.
    key_map = {
        "bid": ("bid",),
        "ask": ("ask",),
        "spread_bps": ("spread_bps",),
        "bid_depth_usd": ("bid_depth_usd",),
        "ask_depth_usd": ("ask_depth_usd",),
        "orderbook_imbalance": ("orderbook_imbalance",),
        "trend_direction": ("trend_direction",),
        "trend_strength": ("trend_strength",),
        "ema_spread_pct": ("ema_spread_pct",),
        "vol_regime": ("vol_regime", "volatility_regime"),
        "atr_ratio": ("atr_ratio",),
        "market_regime": ("market_regime",),
        "poc_price": ("poc_price", "point_of_control"),
        "vah_price": ("vah_price", "value_area_high"),
        "val_price": ("val_price", "value_area_low"),
        "position_in_value": ("position_in_value",),
        "expected_fee_bps": ("expected_fee_bps", "fee_bps"),
        "expected_cost_bps": ("expected_cost_bps", "total_cost_bps"),
        "trades_per_second": ("trades_per_second",),
        "book_age_ms": ("book_age_ms",),
        "trade_age_ms": ("trade_age_ms",),
        "data_quality_score": ("data_quality_score",),
        "session": ("session",),
        "hour_utc": ("hour_utc",),
    }
    for target_key, source_keys in key_map.items():
        value = None
        for source_key in source_keys:
            value = _get_attr(market_context, source_key)
            if value is None:
                value = _get_attr(features, source_key)
            if value is not None:
                break
        if value is not None:
            values[target_key] = value
    combined_depth = None
    for source_key in ("depth_usd", "book_depth_usd", "orderbook_depth_usd", "total_depth_usd"):
        combined_depth = _get_attr(market_context, source_key)
        if combined_depth is None:
            combined_depth = _get_attr(features, source_key)
        if combined_depth is not None:
            break
    if combined_depth is not None:
        try:
            combined_depth_value = max(0.0, float(combined_depth))
        except (TypeError, ValueError):
            combined_depth_value = 0.0
        bid_depth = values.get("bid_depth_usd")
        ask_depth = values.get("ask_depth_usd")
        if bid_depth is None and ask_depth is None:
            split_depth = combined_depth_value / 2.0
            values["bid_depth_usd"] = split_depth
            values["ask_depth_usd"] = split_depth
        elif bid_depth is None:
            try:
                ask_depth_value = max(0.0, float(ask_depth or 0.0))
            except (TypeError, ValueError):
                ask_depth_value = 0.0
            values["bid_depth_usd"] = max(0.0, combined_depth_value - ask_depth_value)
        elif ask_depth is None:
            try:
                bid_depth_value = max(0.0, float(bid_depth or 0.0))
            except (TypeError, ValueError):
                bid_depth_value = 0.0
            values["ask_depth_usd"] = max(0.0, combined_depth_value - bid_depth_value)
    # Build via canonical entrypoint to ensure correct derived fields
    # (session/hour_utc) and consistent defaults.
    input = ContextVectorInput(**values)
    return build_context_vector(input)


class ProfileRouter:
    """Minimal profile routing interface."""
    require_profile = False

    def route(self, market_context: dict) -> Optional[str]:
        return market_context.get("profile_id") if isinstance(market_context, dict) else None

    def route_with_context(self, symbol: str, market_context, features):
        return self.route(market_context)


class DeepTraderProfileRouter(ProfileRouter):
    """Adapter to deeptrader profile router when available."""
    require_profile = True

    def __init__(self, backtesting_mode: bool = False):
        try:
            from quantgambit.deeptrader_core.profiles.profile_router import get_profile_router  # type: ignore
            from quantgambit.deeptrader_core.profiles.router_config import RouterConfig  # type: ignore
            
            if backtesting_mode:
                # Create a router with backtesting mode enabled (skips data freshness checks)
                config = RouterConfig(backtesting_mode=True)
                self._router = get_profile_router(config=config, force_new=True)
            else:
                self._router = get_profile_router()
        except Exception:
            self._router = None
        self.last_scores: list[dict] = []
        self._policy: dict = {}
        self._profile_first_seen: dict[str, float] = {}
        self._profile_seen_counts: dict[str, int] = {}
        self._profile_versions: dict[str, float] = {}

    def _fallback_profile_id(self) -> str | None:
        fallback = (
            self._policy.get("default_profile_id")
            or self._policy.get("fallback_profile_id")
            or os.getenv("PROFILE_FALLBACK_PROFILE_ID")
        )
        fallback = str(fallback).strip() if fallback is not None else ""
        return fallback or None

    def set_policy(self, policy: dict | None) -> None:
        self._policy = policy or {}

    def record_trade(self, profile_id: str, symbol: str, pnl: float) -> None:
        if not self._router:
            return
        record_fn = getattr(self._router, "record_trade", None)
        if not record_fn:
            return
        record_fn(profile_id, symbol, pnl)

    def _filter_scores(self, scores, risk_mode: str | None, market_context, features) -> list[dict]:
        policy = self._policy or {}
        allow = set(policy.get("allow_profiles") or policy.get("allowlist") or [])
        block = set(policy.get("block_profiles") or policy.get("denylist") or [])
        min_score = policy.get("min_score")
        min_confidence = policy.get("min_confidence") or policy.get("min_confidence_score")
        feature_gates = policy.get("feature_gates") or policy.get("profile_feature_gates") or {}
        profile_regimes = (
            policy.get("profile_regimes")
            or policy.get("profile_regime_map")
            or policy.get("regime_map")
            or {}
        )
        risk_bias_start = policy.get("risk_bias_start_pct")
        min_risk_bias = policy.get("min_risk_bias_multiplier")
        risk_bias_start = _safe_float(risk_bias_start, 70.0) if risk_bias_start is not None else 70.0
        min_risk_bias = _safe_float(min_risk_bias, 0.25) if min_risk_bias is not None else 0.25
        quarantine_sec = _safe_float(policy.get("profile_quarantine_sec"), 0.0)
        warmup_min_samples = policy.get("profile_warmup_min_samples") or policy.get("profile_quarantine_min_samples")
        try:
            warmup_min_samples = int(warmup_min_samples) if warmup_min_samples is not None else 0
        except (TypeError, ValueError):
            warmup_min_samples = 0
        profile_versions = (
            policy.get("profile_versions")
            or policy.get("profile_version_map")
            or policy.get("profile_revision_map")
            or {}
        )
        profile_updated_at = (
            policy.get("profile_updated_at")
            or policy.get("profile_update_ts")
            or policy.get("profile_updated_ts")
            or {}
        )
        if min_score is not None:
            try:
                min_score = float(min_score)
            except (TypeError, ValueError):
                min_score = None
        if min_confidence is not None:
            try:
                min_confidence = float(min_confidence)
            except (TypeError, ValueError):
                min_confidence = None
        mode_policy = policy.get("risk_mode") or policy.get("risk_modes") or {}
        mode = mode_policy.get(risk_mode) if risk_mode else None
        mode_allow = set(mode.get("allow") or mode.get("allow_profiles") or []) if mode else set()
        mode_block = set(mode.get("block") or mode.get("block_profiles") or []) if mode else set()

        data_quality_raw = (
            _get_attr(market_context, "data_quality_score")
            or _get_attr(features, "data_quality_score")
            or _get_attr(features, "quality_score")
        )
        data_quality_score = _safe_float(data_quality_raw, 1.0)
        data_quality_score = max(0.0, min(1.0, data_quality_score))

        exposure_pct = _get_attr(market_context, "total_exposure_pct")
        max_exposure_pct = _get_attr(market_context, "max_total_exposure_pct")
        risk_bias_multiplier = 1.0
        if exposure_pct is not None and max_exposure_pct:
            exposure_pct = _safe_float(exposure_pct, None)
            max_exposure_pct = _safe_float(max_exposure_pct, None)
            if exposure_pct is not None and max_exposure_pct and max_exposure_pct > 0:
                threshold = max(0.0, min(100.0, risk_bias_start))
                if exposure_pct >= threshold:
                    span = max(1.0, max_exposure_pct - threshold)
                    over = min(max_exposure_pct, exposure_pct) - threshold
                    ratio = max(0.0, min(1.0, over / span))
                    risk_bias_multiplier = max(min_risk_bias, 1.0 - ratio)

        eligible = []
        annotated = []
        regime_family = _get_attr(market_context, "regime_family")
        market_regime = _get_attr(market_context, "market_regime")
        now = time.time()
        for score in scores:
            reasons = []
            is_ok = True
            profile_id = score.profile_id
            profile_version = None
            if isinstance(profile_versions, dict):
                profile_version = profile_versions.get(profile_id)
            if profile_version is None and isinstance(profile_updated_at, dict):
                profile_version = profile_updated_at.get(profile_id)
            profile_version = _safe_float(profile_version, None) if profile_version is not None else None
            last_version = self._profile_versions.get(profile_id)
            if profile_version is not None and profile_version != last_version:
                self._profile_versions[profile_id] = profile_version
                self._profile_first_seen[profile_id] = now
                self._profile_seen_counts[profile_id] = 0
            if profile_id not in self._profile_first_seen:
                self._profile_first_seen[profile_id] = now
                self._profile_seen_counts[profile_id] = 0
            self._profile_seen_counts[profile_id] = self._profile_seen_counts.get(profile_id, 0) + 1
            if allow and score.profile_id not in allow:
                is_ok = False
                reasons.append("policy_allowlist")
            if score.profile_id in block:
                is_ok = False
                reasons.append("policy_blocklist")
            if mode_allow and score.profile_id not in mode_allow:
                is_ok = False
                reasons.append("risk_mode_allowlist")
            if score.profile_id in mode_block:
                is_ok = False
                reasons.append("risk_mode_blocklist")
            if min_score is not None and score.score < min_score:
                is_ok = False
                reasons.append("policy_min_score")
            if min_confidence is not None and score.confidence < min_confidence:
                is_ok = False
                reasons.append("policy_min_confidence")

            profile_regime_allow = None
            if isinstance(profile_regimes, dict):
                profile_regime_allow = profile_regimes.get(score.profile_id)
            if profile_regime_allow:
                if isinstance(profile_regime_allow, str):
                    profile_regime_allow = [profile_regime_allow]
                if regime_family and regime_family not in profile_regime_allow and market_regime not in profile_regime_allow:
                    is_ok = False
                    reasons.append("regime_mismatch")

            gate = feature_gates.get(score.profile_id) if isinstance(feature_gates, dict) else None
            if gate:
                required = gate.get("required") or gate.get("require") or gate.get("features") or []
                missing = []
                for key in required:
                    if _get_attr(market_context, key) is None and _get_attr(features, key) is None:
                        missing.append(key)
                if missing:
                    is_ok = False
                    reasons.append("missing_features")
                gate_min_quality = gate.get("min_quality") or gate.get("min_quality_score")
                if gate_min_quality is not None:
                    try:
                        gate_min_quality = float(gate_min_quality)
                    except (TypeError, ValueError):
                        gate_min_quality = None
                if gate_min_quality is not None and data_quality_score < gate_min_quality:
                    is_ok = False
                    reasons.append("profile_min_quality")

            quarantine_remaining = None
            warmup_remaining = None
            if quarantine_sec and quarantine_sec > 0:
                since = now - self._profile_first_seen.get(profile_id, now)
                if since < quarantine_sec:
                    is_ok = False
                    reasons.append("profile_quarantine")
                    quarantine_remaining = max(0.0, quarantine_sec - since)
            if warmup_min_samples and warmup_min_samples > 0:
                seen = self._profile_seen_counts.get(profile_id, 0)
                if seen < warmup_min_samples:
                    is_ok = False
                    reasons.append("profile_warmup")
                    warmup_remaining = max(0, warmup_min_samples - seen)

            adjusted_score = (
                _safe_float(score.score, 0.0)
                * _safe_float(score.confidence, 1.0)
                * data_quality_score
                * risk_bias_multiplier
            )
            annotated.append(
                {
                    "profile_id": score.profile_id,
                    "score": score.score,
                    "confidence": score.confidence,
                    "reasons": score.reasons,
                    "data_quality_score": data_quality_score,
                    "adjusted_score": adjusted_score,
                    "risk_bias_multiplier": risk_bias_multiplier,
                    "eligible": is_ok,
                    "eligibility_reasons": reasons,
                    "quarantine_remaining_sec": quarantine_remaining,
                    "warmup_samples_remaining": warmup_remaining,
                }
            )
            if is_ok:
                eligible.append(
                    {
                        "profile_id": score.profile_id,
                        "score": score.score,
                        "confidence": score.confidence,
                        "adjusted_score": adjusted_score,
                    }
                )
        self.last_scores = annotated
        return eligible

    def route(self, market_context: dict) -> Optional[str]:
        if not self._router:
            return super().route(market_context)
        try:
            return self._router.route(market_context)
        except Exception:
            return super().route(market_context)

    def route_with_context(self, symbol: str, market_context, features):
        if not self._router:
            return super().route_with_context(symbol, market_context, features)
        explicit_profile = _get_attr(market_context, "profile_id") or _get_attr(features, "profile_id")
        if explicit_profile:
            self.last_scores = [
                {
                    "profile_id": explicit_profile,
                    "score": 1.0,
                    "confidence": 1.0,
                    "data_quality_score": _get_attr(market_context, "data_quality_score"),
                    "adjusted_score": 1.0,
                    "risk_bias_multiplier": 1.0,
                    "reasons": ["explicit_profile_override"],
                    "eligible": True,
                    "eligibility_reasons": [],
                }
            ]
            return explicit_profile
        context_vector = _build_context_vector(symbol, market_context, features)
        if not context_vector:
            return super().route_with_context(symbol, market_context, features)
        top_k = self._policy.get("top_k") or 10
        try:
            top_k = int(top_k)
        except (TypeError, ValueError):
            top_k = 10
        try:
            scores = self._router.select_profiles(context_vector, top_k=top_k, symbol=symbol)
        except Exception:
            return super().route_with_context(symbol, market_context, features)
        risk_mode = _get_attr(market_context, "risk_mode") or _get_attr(features, "risk_mode")
        eligible_scores = self._filter_scores(scores, risk_mode, market_context, features)
        if not eligible_scores:
            fallback_profile_id = self._fallback_profile_id()
            if scores:
                fallback = scores[0]
                logging.getLogger(__name__).warning(
                    "[%s] strategy router fallback: no eligible profiles after policy filtering; "
                    "using top raw profile_id=%s score=%.3f",
                    symbol,
                    fallback.profile_id,
                    getattr(fallback, "score", 0.0) or 0.0,
                )
                return fallback.profile_id
            if fallback_profile_id:
                logging.getLogger(__name__).warning(
                    "[%s] strategy router fallback: no scored profiles available; "
                    "using default profile_id=%s",
                    symbol,
                    fallback_profile_id,
                )
                self.last_scores = [
                    {
                        "profile_id": fallback_profile_id,
                        "score": 0.0,
                        "confidence": 0.0,
                        "data_quality_score": _get_attr(market_context, "data_quality_score"),
                        "adjusted_score": 0.0,
                        "risk_bias_multiplier": 1.0,
                        "reasons": ["fallback_profile_no_scores"],
                        "eligible": True,
                        "eligibility_reasons": ["no_scored_profiles"],
                    }
                ]
                return fallback_profile_id
            return None
        best = max(eligible_scores, key=lambda item: item.get("adjusted_score") or item.get("score") or 0.0)
        return best.get("profile_id")
