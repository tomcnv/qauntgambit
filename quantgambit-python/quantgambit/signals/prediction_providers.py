"""Prediction provider implementations for feature snapshots."""

from __future__ import annotations

import math
import numbers
import os
import time
import json
import copy
from pathlib import Path
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Protocol

from quantgambit.ai import llm_complete_sync
from quantgambit.ai.context import (
    ProviderRequest,
    ProviderResponse,
    build_context_quality,
    get_global_context,
    get_symbol_context,
)
from quantgambit.ingest.schemas import coerce_float
from quantgambit.observability.logger import log_warning, log_info
from quantgambit.deeptrader_core.layer1_predictions import (
    classify_trend,
    classify_volatility,
    classify_liquidity,
    classify_regime,
)
from quantgambit.deeptrader_core.layer1_predictions.regime_classifier import should_trade_regime


def _parse_symbol_float_map(raw: str) -> Dict[str, float]:
    """
    Parse per-symbol float overrides.

    Format: "BTCUSDT:0.35,ETHUSDT:0.52"
    """
    parsed: Dict[str, float] = {}
    if not raw:
        return parsed
    for token in raw.split(","):
        token = token.strip()
        if not token or ":" not in token:
            continue
        sym_raw, val_raw = token.split(":", 1)
        sym = sym_raw.strip().upper()
        try:
            val = float(val_raw.strip())
        except ValueError:
            continue
        if sym:
            parsed[sym] = float(val)
    return parsed


def _parse_keyed_float_map(raw: str) -> Dict[str, float]:
    """
    Parse generic keyed float overrides.

    Format examples:
      "ASIA:0.45,EUROPE:0.50"
      "BTCUSDT@ASIA:0.40,ETHUSDT@EUROPE:0.55"
    """
    parsed: Dict[str, float] = {}
    if not raw:
        return parsed
    for token in raw.split(","):
        token = token.strip()
        if not token or ":" not in token:
            continue
        key_raw, val_raw = token.split(":", 1)
        key = key_raw.strip().upper()
        try:
            val = float(val_raw.strip())
        except ValueError:
            continue
        if key:
            parsed[key] = float(val)
    return parsed


def _parse_csv_tokens(raw: str) -> list[str]:
    if not raw:
        return []
    return [token.strip() for token in raw.split(",") if token and token.strip()]


def _resolve_bool(*values: Any, default: bool = False) -> bool:
    for value in values:
        if value is None:
            continue
        if isinstance(value, bool):
            return value
        normalized = str(value).strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    return default


class PredictionProvider(Protocol):
    def build_prediction(self, features: dict, market_context: dict, timestamp: float) -> Optional[dict]:
        """Return a prediction payload for the feature snapshot."""


def _normalize_ai_session(value: str | None) -> str:
    normalized = str(value or "").strip().lower()
    aliases = {
        "ny": "us",
        "new_york": "us",
        "newyork": "us",
        "us": "us",
        "usa": "us",
        "london": "europe",
        "ldn": "europe",
        "europe": "europe",
        "eu": "europe",
        "asia": "asia",
        "tokyo": "asia",
        "overnight": "overnight",
    }
    return aliases.get(normalized, normalized)


def is_ai_admissible(features: dict, market_context: dict, context_payload: dict | None) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    symbol = str(features.get("symbol") or market_context.get("symbol") or "").upper()
    enabled_symbols = {
        item.strip().upper()
        for item in _parse_csv_tokens(os.getenv("AI_ENABLED_SYMBOLS", ""))
        if item.strip()
    }
    enabled_sessions = {
        _normalize_ai_session(item)
        for item in _parse_csv_tokens(os.getenv("AI_ENABLED_SESSIONS", ""))
        if item.strip()
    }
    min_feature_completeness = max(0.0, _resolve_float(os.getenv("AI_MIN_FEATURE_COMPLETENESS"), 0.90))
    max_spread_bps = max(0.0, _resolve_float(os.getenv("AI_MAX_SPREAD_BPS"), 35.0))
    sentiment_max_age_ms = max(0, int(_resolve_float(os.getenv("SENTIMENT_MAX_AGE_MS"), 30000)))
    event_max_age_ms = max(0, int(_resolve_float(os.getenv("EVENT_CONTEXT_MAX_AGE_MS"), 60000)))
    min_source_quality = max(0.0, _resolve_float(os.getenv("MIN_SENTIMENT_SOURCE_QUALITY"), 0.70))
    min_news_count = max(0, int(_resolve_float(os.getenv("MIN_NEWS_COUNT_FOR_VALID_SENTIMENT"), 1)))

    if _resolve_bool(os.getenv("AI_KILL_SWITCH"), default=False):
        reasons.append("ai_kill_switch")
    if enabled_symbols and symbol and symbol not in enabled_symbols:
        reasons.append("symbol_not_enabled")
    session = _normalize_ai_session(market_context.get("session"))
    if enabled_sessions and session and session not in enabled_sessions:
        reasons.append("session_not_enabled")
    data_completeness = coerce_float(market_context.get("data_completeness")) or 0.0
    if data_completeness < min_feature_completeness:
        reasons.append("feature_completeness_low")
    if str(market_context.get("data_quality_status") or "").strip().lower() == "stale":
        reasons.append("market_data_stale")
    spread_bps = coerce_float(market_context.get("spread_bps")) or 0.0
    if spread_bps > max_spread_bps:
        reasons.append("wide_spread")

    sentiment = {}
    events = {}
    if isinstance(context_payload, dict):
        if isinstance(context_payload.get("sentiment"), dict):
            sentiment = context_payload.get("sentiment") or {}
        if isinstance(context_payload.get("events"), dict):
            events = context_payload.get("events") or {}
    if not sentiment:
        reasons.append("sentiment_missing")
    else:
        if bool(sentiment.get("is_stale")):
            reasons.append("sentiment_stale")
        age_ms = int(coerce_float(sentiment.get("age_ms")) or 0)
        if sentiment_max_age_ms and age_ms > sentiment_max_age_ms:
            reasons.append("sentiment_stale")
        if (coerce_float(sentiment.get("source_quality")) or 0.0) < min_source_quality:
            reasons.append("sentiment_quality_low")
        if int(sentiment.get("news_count_1h") or 0) < min_news_count:
            reasons.append("sentiment_volume_low")
    if events:
        event_age_ms = int(coerce_float(events.get("age_ms")) or 0)
        if event_max_age_ms and event_age_ms > event_max_age_ms:
            reasons.append("event_context_stale")
        if _resolve_bool(events.get("exchange_risk_flag"), default=False):
            reasons.append("exchange_risk_flag")
    return (len(reasons) == 0), reasons


class DeepSeekContextPredictionProvider:
    name = "deepseek_context"

    def __init__(self, provider_config: Optional[dict[str, Any]] = None):
        config = provider_config or {}
        self._timeout_ms = max(50, int(_resolve_float(config.get("timeout_ms"), os.getenv("AI_PROVIDER_TIMEOUT_MS"), 250)))
        self._model = str(
            config.get("model")
            or os.getenv("AI_PROVIDER_MODEL")
            or os.getenv("DEEPSEEK_CONTEXT_MODEL")
            or os.getenv("COPILOT_LLM_MODEL")
            or "deepseek-chat"
        ).strip()
        self._provider_version = str(config.get("version") or "v1").strip()
        self._min_confidence = _clamp(_resolve_float(config.get("min_confidence"), os.getenv("AI_PROVIDER_MIN_CONFIDENCE"), 0.74))
        self._expected_move_cap_bps = max(1.0, _resolve_float(config.get("expected_move_cap_bps"), 250.0))
        self._default_horizon_sec = max(300, int(_resolve_float(config.get("default_horizon_sec"), 14400)))
        self._valid_for_ms = max(1000, int(_resolve_float(config.get("valid_for_ms"), 300000)))
        self._temperature = max(0.0, min(1.0, _resolve_float(config.get("temperature"), 0.1)))
        self._max_tokens = max(128, int(_resolve_float(config.get("max_tokens"), 300)))
        self._fail_open_to = str(config.get("fail_open_to") or os.getenv("AI_PROVIDER_FAIL_OPEN_TO") or "heuristic").strip().lower()
        self._fallback_provider = HeuristicPredictionProvider()
        self._cache_enabled = _resolve_bool(
            config.get("cache_enabled"),
            os.getenv("AI_PROVIDER_CACHE_ENABLED"),
            default=True,
        )
        self._cache_min_valid_for_ms = max(
            1000,
            int(_resolve_float(config.get("cache_min_valid_for_ms"), os.getenv("AI_PROVIDER_CACHE_MIN_VALID_FOR_MS"), 30000)),
        )
        self._prediction_cache: dict[str, dict[str, Any]] = {}

    def build_prediction(self, features: dict, market_context: dict, timestamp: float) -> Optional[dict]:
        symbol = str(features.get("symbol") or market_context.get("symbol") or "").upper()
        cached_payload = self._get_cached_prediction(symbol, timestamp)
        if cached_payload is not None:
            return cached_payload
        symbol_context = get_symbol_context(symbol)
        global_context = get_global_context()
        if symbol_context and global_context and not symbol_context.get("global_context"):
            symbol_context = dict(symbol_context)
            symbol_context["global_context"] = global_context
        admissible, reasons = is_ai_admissible(features, market_context, symbol_context)
        if not admissible:
            payload = ProviderResponse(
                direction="abstain",
                confidence=0.0,
                expected_move_bps=None,
                horizon_sec=None,
                reason_codes=reasons,
                risk_flags=["ai_not_admissible"],
                valid_for_ms=0,
                provider_name=self.name,
                provider_version=self._provider_version,
                latency_ms=0,
            )
            return payload.to_prediction_payload(timestamp)

        request = ProviderRequest(
            symbol=symbol,
            ts_ms=int(timestamp * 1000),
            feature_snapshot=features,
            market_context=market_context,
            profile=str(market_context.get("profile_id") or ""),
            strategy=str(market_context.get("strategy_id") or ""),
            max_inference_ms=self._timeout_ms,
            trace_id=f"{symbol}:{int(timestamp * 1000)}",
        )
        started = time.perf_counter()
        try:
            raw = llm_complete_sync(
                self._build_prompt(request, symbol_context),
                system=self._system_prompt(),
                temperature=self._temperature,
                max_tokens=self._max_tokens,
                model=self._model,
                timeout_sec=self._timeout_ms / 1000.0,
            )
            latency_ms = max(1, int((time.perf_counter() - started) * 1000))
            response = self._validate_response(self._parse_response(raw), latency_ms=latency_ms)
            payload = response.to_prediction_payload(timestamp)
            self._store_cached_prediction(symbol, payload)
            return payload
        except Exception as exc:
            log_warning("deepseek_context_prediction_failed", symbol=symbol, error=str(exc))
            if self._fail_open_to in {"heuristic", "legacy_heuristic"}:
                fallback = self._fallback_provider.build_prediction(features, market_context, timestamp)
                if fallback:
                    fallback["fallback_used"] = True
                    fallback["fallback_reason"] = "context_model_fallback"
                    fallback["source"] = f"{fallback.get('source') or 'heuristic'}_fallback"
                    return fallback
            payload = ProviderResponse(
                direction="abstain",
                confidence=0.0,
                expected_move_bps=None,
                horizon_sec=None,
                reason_codes=["context_model_fallback", "provider_exception"],
                risk_flags=["provider_error"],
                valid_for_ms=0,
                provider_name=self.name,
                provider_version=self._provider_version,
                latency_ms=max(1, int((time.perf_counter() - started) * 1000)),
                fallback_used=True,
            )
            return payload.to_prediction_payload(timestamp)

    def _get_cached_prediction(self, symbol: str, timestamp: float) -> Optional[dict[str, Any]]:
        if not self._cache_enabled or not symbol:
            return None
        cached = self._prediction_cache.get(symbol)
        if not cached:
            return None
        now_ms = int(time.time() * 1000)
        expires_at_ms = int(cached.get("expires_at_ms") or 0)
        if expires_at_ms <= now_ms:
            self._prediction_cache.pop(symbol, None)
            return None
        payload = copy.deepcopy(cached.get("payload") or {})
        if not payload:
            self._prediction_cache.pop(symbol, None)
            return None
        payload["timestamp"] = timestamp
        payload["cached_prediction"] = True
        payload["cached_generated_at_ms"] = cached.get("generated_at_ms")
        payload["cache_expires_at_ms"] = expires_at_ms
        payload["provider_latency_ms"] = 0
        reason_codes = [str(item) for item in (payload.get("reason_codes") or []) if str(item).strip()]
        if "cached_prediction" not in reason_codes:
            payload["reason_codes"] = ["cached_prediction", *reason_codes]
        return payload

    def _store_cached_prediction(self, symbol: str, payload: dict[str, Any]) -> None:
        if not self._cache_enabled or not symbol:
            return
        valid_for_ms = max(
            self._cache_min_valid_for_ms,
            int(coerce_float(payload.get("valid_for_ms")) or 0),
        )
        if valid_for_ms <= 0:
            return
        source = str(payload.get("source") or "")
        if source != self.name:
            return
        generated_at_ms = int(time.time() * 1000)
        cache_payload = copy.deepcopy(payload)
        cache_payload.pop("cached_prediction", None)
        cache_payload.pop("cached_generated_at_ms", None)
        cache_payload.pop("cache_expires_at_ms", None)
        self._prediction_cache[symbol] = {
            "payload": cache_payload,
            "generated_at_ms": generated_at_ms,
            "expires_at_ms": generated_at_ms + valid_for_ms,
        }

    def _system_prompt(self) -> str:
        return (
            "You are a crypto spot and swing trading signal model. "
            "Return only strict JSON. "
            "Never emit order instructions, sizing, leverage, stop loss, or take profit. "
            "Abstain when evidence is mixed or stale."
        )

    def _build_prompt(self, request: ProviderRequest, context_payload: dict[str, Any]) -> str:
        micro = {
            "price": request.market_context.get("price"),
            "spread_bps": request.market_context.get("spread_bps"),
            "price_change_1m": request.market_context.get("price_change_1m"),
            "price_change_5m": request.market_context.get("price_change_5m"),
            "price_change_1h": request.market_context.get("price_change_1h"),
            "orderbook_imbalance": request.market_context.get("orderbook_imbalance"),
            "trades_per_second": request.market_context.get("trades_per_second"),
        }
        regime = {
            "trend_direction": request.market_context.get("trend_direction"),
            "trend_strength": request.market_context.get("trend_strength"),
            "volatility_regime": request.market_context.get("volatility_regime"),
            "market_regime": request.market_context.get("market_regime"),
            "session": request.market_context.get("session"),
        }
        quality = build_context_quality(request.market_context, context_payload).__dict__
        payload = {
            "symbol": request.symbol,
            "ts_ms": request.ts_ms,
            "profile": request.profile,
            "strategy": request.strategy,
            "horizon_preference_sec": self._default_horizon_sec,
            "microstructure": micro,
            "regime": regime,
            "context": context_payload,
            "quality": quality,
        }
        return (
            "Analyze this spot/swing trading context and output only JSON with keys "
            "direction, confidence, expected_move_bps, horizon_sec, reason_codes, risk_flags, valid_for_ms, raw_score. "
            "direction must be one of long, short, flat, abstain. "
            "confidence must be between 0 and 1. "
            "expected_move_bps must be bounded and realistic. "
            f"Use higher confidence only when catalyst, sentiment, and regime agree.\n{json.dumps(payload, separators=(',', ':'))}"
        )

    def _parse_response(self, raw: str) -> dict[str, Any]:
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start < 0 or end <= start:
            raise ValueError("deepseek_response_not_json")
        return json.loads(raw[start:end])

    def _validate_response(self, payload: dict[str, Any], *, latency_ms: int) -> ProviderResponse:
        direction = str(payload.get("direction") or "").strip().lower()
        if direction not in {"long", "short", "flat", "abstain"}:
            raise ValueError("invalid_direction")
        confidence = _clamp(payload.get("confidence"))
        expected_move_bps = coerce_float(payload.get("expected_move_bps"))
        if expected_move_bps is not None:
            expected_move_bps = max(-self._expected_move_cap_bps, min(self._expected_move_cap_bps, expected_move_bps))
        horizon_sec = int(max(60, coerce_float(payload.get("horizon_sec")) or self._default_horizon_sec))
        valid_for_ms = int(max(0, coerce_float(payload.get("valid_for_ms")) or self._valid_for_ms))
        reason_codes = [str(item) for item in (payload.get("reason_codes") or []) if str(item).strip()]
        risk_flags = [str(item) for item in (payload.get("risk_flags") or []) if str(item).strip()]
        raw_score = coerce_float(payload.get("raw_score"))
        if direction in {"long", "short"} and confidence < self._min_confidence:
            direction = "abstain"
            reason_codes = ["confidence_below_floor", *reason_codes]
        return ProviderResponse(
            direction=direction,  # type: ignore[arg-type]
            confidence=confidence if direction != "abstain" else 0.0,
            expected_move_bps=expected_move_bps,
            horizon_sec=horizon_sec if direction != "abstain" else None,
            reason_codes=reason_codes,
            risk_flags=risk_flags,
            valid_for_ms=valid_for_ms,
            provider_name=self.name,
            provider_version=self._provider_version,
            latency_ms=latency_ms,
            raw_score=raw_score,
        )


class HeuristicPredictionProvider:
    def __init__(self, provider_config: Optional[dict[str, Any]] = None):
        config = provider_config or {}
        version_override = str(config.get("heuristic_version") or "").strip().lower()
        self._version = version_override or str(os.getenv("PREDICTION_HEURISTIC_VERSION") or "v1").strip().lower()
        self._min_data_completeness = _clamp(
            _resolve_float(os.getenv("PREDICTION_HEURISTIC_V2_MIN_DATA_COMPLETENESS"), 0.45)
        )
        self._max_spread_bps = max(
            0.0,
            _resolve_float(os.getenv("PREDICTION_HEURISTIC_V2_MAX_SPREAD_BPS"), 3.0),
        )
        self._entry_score = max(
            0.01,
            _resolve_float(os.getenv("PREDICTION_HEURISTIC_V2_ENTRY_SCORE"), 0.20),
        )
        self._entry_score_long = max(
            0.01,
            _resolve_float(os.getenv("PREDICTION_HEURISTIC_V2_ENTRY_SCORE_LONG"), self._entry_score),
        )
        self._entry_score_short = max(
            0.01,
            _resolve_float(os.getenv("PREDICTION_HEURISTIC_V2_ENTRY_SCORE_SHORT"), self._entry_score),
        )
        self._min_confidence = _clamp(
            _resolve_float(os.getenv("PREDICTION_HEURISTIC_V2_MIN_CONFIDENCE"), 0.12)
        )
        self._min_confidence_long = _clamp(
            _resolve_float(os.getenv("PREDICTION_HEURISTIC_V2_MIN_CONFIDENCE_LONG"), self._min_confidence)
        )
        self._min_confidence_short = _clamp(
            _resolve_float(os.getenv("PREDICTION_HEURISTIC_V2_MIN_CONFIDENCE_SHORT"), self._min_confidence + 0.06)
        )
        self._min_net_edge_bps = _resolve_float(
            os.getenv("PREDICTION_HEURISTIC_V2_MIN_NET_EDGE_BPS"),
            3.0,
        )
        self._expected_move_per_score_bps = max(
            0.01,
            _resolve_float(os.getenv("PREDICTION_HEURISTIC_V2_EXPECTED_MOVE_PER_SCORE_BPS"), 25.0),
        )
        self._default_fee_bps = max(
            0.0,
            _resolve_float(os.getenv("PREDICTION_HEURISTIC_V2_FEE_BPS"), _resolve_float(os.getenv("FEE_AWARE_ENTRY_FEE_RATE_BPS"), 5.5)),
        )
        self._default_slippage_bps = max(
            0.0,
            _resolve_float(os.getenv("PREDICTION_HEURISTIC_V2_SLIPPAGE_BPS"), 2.0),
        )
        self._default_adverse_selection_bps = max(
            0.0,
            _resolve_float(os.getenv("PREDICTION_HEURISTIC_V2_ADVERSE_SELECTION_BPS"), 1.0),
        )
        self._w_imbalance = _resolve_float(os.getenv("PREDICTION_HEURISTIC_V2_WEIGHT_IMBALANCE"), 0.65)
        self._w_trend = _resolve_float(os.getenv("PREDICTION_HEURISTIC_V2_WEIGHT_TREND"), 0.25)
        self._w_rotation = _resolve_float(os.getenv("PREDICTION_HEURISTIC_V2_WEIGHT_ROTATION"), 0.10)
        self._symbol_bias = _parse_symbol_float_map(os.getenv("PREDICTION_HEURISTIC_V2_SYMBOL_BIAS", ""))
        self._session_bias = _parse_keyed_float_map(os.getenv("PREDICTION_HEURISTIC_V2_SESSION_BIAS", ""))
        self._symbol_session_bias = _parse_keyed_float_map(
            os.getenv("PREDICTION_HEURISTIC_V2_SYMBOL_SESSION_BIAS", "")
        )

    def _build_prediction_v2(self, features: dict, market_context: dict, timestamp: float) -> Optional[dict]:
        price = coerce_float(market_context.get("price"))
        if price is None:
            return None
        symbol = str(features.get("symbol") or market_context.get("symbol") or "").upper()
        session = str(market_context.get("session") or "").upper()
        spread_bps = coerce_float(market_context.get("spread_bps")) or 0.0
        data_completeness = coerce_float(market_context.get("data_completeness")) or 0.0
        trend_direction = str(market_context.get("trend_direction") or "flat").lower()
        trend_strength_raw = coerce_float(market_context.get("trend_strength")) or 0.0
        imbalance = max(-1.0, min(1.0, coerce_float(market_context.get("orderbook_imbalance")) or 0.0))
        rotation_raw = coerce_float(features.get("rotation_factor"))
        if rotation_raw is None:
            rotation_raw = coerce_float(market_context.get("rotation_factor")) or 0.0
        volatility_regime = str(market_context.get("volatility_regime") or "unknown").lower()

        trend_sign = 0.0
        if trend_direction == "up":
            trend_sign = 1.0
        elif trend_direction == "down":
            trend_sign = -1.0
        trend_component = trend_sign * math.tanh(abs(trend_strength_raw) * 3000.0)
        rotation_component = math.tanh(float(rotation_raw) / 6.0)
        score = (
            (self._w_imbalance * imbalance)
            + (self._w_trend * trend_component)
            + (self._w_rotation * rotation_component)
        )
        if symbol:
            score += float(self._symbol_bias.get(symbol, 0.0))
        if session:
            score += float(self._session_bias.get(session, 0.0))
        if symbol and session:
            score += float(self._symbol_session_bias.get(f"{symbol}@{session}", 0.0))

        direction = "flat"
        if score >= self._entry_score_long:
            direction = "up"
        elif score <= -self._entry_score_short:
            direction = "down"

        confidence = self._min_confidence + (1.0 - self._min_confidence) * min(1.0, abs(score))
        if spread_bps > self._max_spread_bps:
            confidence *= 0.8
        if volatility_regime == "high":
            confidence *= 0.88
        elif volatility_regime == "low":
            confidence = min(1.0, confidence + 0.05)
        if data_completeness < 0.7:
            confidence *= max(0.6, data_completeness)
        confidence = _clamp(confidence)

        if direction == "up":
            confidence = max(confidence, self._min_confidence_long)
        elif direction == "down":
            confidence = max(confidence, self._min_confidence_short)

        fee_bps = coerce_float(market_context.get("fee_bps")) or self._default_fee_bps
        slippage_bps = coerce_float(market_context.get("expected_slippage_bps")) or self._default_slippage_bps
        adverse_selection_bps = (
            coerce_float(market_context.get("adverse_selection_bps")) or self._default_adverse_selection_bps
        )
        spread_half_bps = max(0.0, spread_bps * 0.5)
        estimated_total_cost_bps = max(
            0.0,
            float(fee_bps) + float(slippage_bps) + float(adverse_selection_bps) + float(spread_half_bps),
        )
        expected_gross_edge_bps = abs(score) * self._expected_move_per_score_bps
        expected_net_edge_bps = expected_gross_edge_bps - estimated_total_cost_bps

        reject = bool(
            data_completeness < self._min_data_completeness
            or spread_bps > (self._max_spread_bps * 1.5)
        )
        reason = None
        if data_completeness < self._min_data_completeness:
            reason = "heuristic_low_data_completeness"
        elif spread_bps > (self._max_spread_bps * 1.5):
            reason = "heuristic_high_spread"
        elif direction == "down" and confidence < self._min_confidence_short:
            reject = True
            reason = "heuristic_short_low_confidence"
        elif direction == "up" and confidence < self._min_confidence_long:
            reject = True
            reason = "heuristic_long_low_confidence"
        elif direction in {"up", "down"} and expected_net_edge_bps < self._min_net_edge_bps:
            reject = True
            reason = "heuristic_low_net_edge"

        return {
            "timestamp": timestamp,
            "direction": direction,
            "confidence": confidence,
            "volatility_regime": volatility_regime or "unknown",
            "trend_strength": trend_strength_raw,
            "orderbook_imbalance": imbalance,
            "source": "heuristic_v2",
            "reject": reject,
            "reason": reason,
            "heuristic_score": float(score),
            "expected_gross_edge_bps": float(expected_gross_edge_bps),
            "expected_net_edge_bps": float(expected_net_edge_bps),
            "estimated_total_cost_bps": float(estimated_total_cost_bps),
        }

    def build_prediction(self, features: dict, market_context: dict, timestamp: float) -> Optional[dict]:
        if self._version in {"v2", "2"}:
            return self._build_prediction_v2(features, market_context, timestamp)
        price = coerce_float(market_context.get("price"))
        if price is None:
            return None
        trend_direction = market_context.get("trend_direction") or "flat"
        trend_strength = coerce_float(market_context.get("trend_strength")) or 0.0
        volatility_regime = market_context.get("volatility_regime") or "unknown"
        imbalance = coerce_float(market_context.get("orderbook_imbalance")) or 0.0
        data_completeness = coerce_float(market_context.get("data_completeness")) or 0.0
        confidence = min(1.0, max(0.05, abs(imbalance) * 2.0 + min(trend_strength * 10.0, 0.5)))
        if volatility_regime == "high":
            confidence *= 0.9
        elif volatility_regime == "low":
            confidence = min(1.0, confidence + 0.05)
        if abs(imbalance) >= 0.1:
            trend_direction = "up" if imbalance > 0 else "down"
        reject = data_completeness < 0.4
        reason = "heuristic_low_data_completeness" if reject else None
        return {
            "timestamp": timestamp,
            "direction": trend_direction,
            "confidence": confidence,
            "volatility_regime": volatility_regime,
            "trend_strength": trend_strength,
            "orderbook_imbalance": imbalance,
            "source": "heuristic_v1",
            "reject": reject,
            "reason": reason,
        }


class LegacyPredictionProvider:
    """Prediction provider backed by deeptrader_core Layer 1 classifiers."""

    def build_prediction(self, features: dict, market_context: dict, timestamp: float) -> Optional[dict]:
        price = coerce_float(market_context.get("price")) or coerce_float(features.get("price"))
        ema_fast = coerce_float(features.get("ema_fast_15m")) or 0.0
        ema_slow = coerce_float(features.get("ema_slow_15m")) or 0.0
        spread_bps = coerce_float(market_context.get("spread_bps")) or 0.0
        bid_depth = coerce_float(market_context.get("bid_depth_usd")) or 0.0
        ask_depth = coerce_float(market_context.get("ask_depth_usd")) or 0.0
        rotation_factor = coerce_float(features.get("rotation_factor")) or 0.0
        atr_5m = coerce_float(features.get("atr_5m")) or 0.0
        atr_baseline = coerce_float(features.get("atr_5m_baseline")) or 0.0
        if price is None or price <= 0:
            return None
        atr_ratio = atr_5m / atr_baseline if atr_baseline and atr_5m else 1.0
        trend_bias, trend_confidence = classify_trend(ema_fast, ema_slow, price)
        volatility_regime, volatility_percentile = classify_volatility(atr_ratio, rotation_factor)
        liquidity_regime = classify_liquidity(bid_depth, ask_depth, spread_bps)
        trend_strength = coerce_float(market_context.get("trend_strength")) or 0.0
        market_regime, regime_confidence = classify_regime(
            rotation_factor,
            atr_ratio,
            trend_strength,
            spread_bps,
        )
        orderbook_imbalance = coerce_float(market_context.get("orderbook_imbalance")) or 0.0
        direction = "flat"
        if trend_bias == "long":
            direction = "up"
        elif trend_bias == "short":
            direction = "down"
        confidence = (trend_confidence + regime_confidence) / 2.0
        if confidence == 0.0 and abs(orderbook_imbalance) > 0:
            confidence = min(1.0, abs(orderbook_imbalance))
        data_completeness = coerce_float(market_context.get("data_completeness")) or 0.0
        regime_allowed = should_trade_regime(market_regime, regime_confidence)
        reject = data_completeness < 0.4 or not regime_allowed
        reason = None
        if data_completeness < 0.4:
            reason = "legacy_low_data_completeness"
        elif not regime_allowed:
            reason = "legacy_regime_disallowed"
        return {
            "timestamp": timestamp,
            "direction": direction,
            "confidence": confidence,
            "volatility_regime": volatility_regime,
            "trend_strength": trend_strength,
            "orderbook_imbalance": orderbook_imbalance,
            "trend_bias": trend_bias,
            "trend_confidence": trend_confidence,
            "market_regime": market_regime,
            "regime_confidence": regime_confidence,
            "liquidity_regime": liquidity_regime,
            "volatility_percentile": volatility_percentile,
            "source": "legacy_layer1",
            "reject": reject,
            "reason": reason,
        }


class ModelPredictionProvider:
    """Placeholder for future ML-backed prediction model."""

    def __init__(self, model=None):
        self.model = model

    def build_prediction(self, features: dict, market_context: dict, timestamp: float) -> Optional[dict]:
        if self.model is None:
            return None
        result = self.model.predict(features, market_context)
        if not isinstance(result, dict):
            return None
        result.setdefault("timestamp", timestamp)
        result.setdefault("source", "model_v1")
        return result


try:
    import onnxruntime as ort  # type: ignore
except ImportError:  # pragma: no cover - optional dependency
    ort = None

try:
    import numpy as np  # type: ignore
except ImportError:  # pragma: no cover - optional dependency
    np = None


class OnnxPredictionProvider:
    """ONNX-backed prediction provider."""

    def __init__(
        self,
        model_path: Optional[str],
        feature_keys: Optional[list[str]] = None,
        class_labels: Optional[list[str]] = None,
        refresh_interval_sec: Optional[float] = None,
        provider_config: Optional[dict[str, Any]] = None,
        min_confidence: Optional[float] = None,
        min_margin: Optional[float] = None,
        max_entropy: Optional[float] = None,
    ):
        self.model_path = model_path
        self.feature_keys = feature_keys or []
        self.class_labels = class_labels or ["down", "flat", "up"]
        self.provider_config = provider_config or {}
        self._session = None
        self._input_name: Optional[str] = None
        self._output_names: list[str] = []
        self._refresh_interval_sec = (
            float(refresh_interval_sec)
            if refresh_interval_sec is not None
            else float(os.getenv("ONNX_REFRESH_INTERVAL_SEC", "300.0"))
        )
        self._last_refresh_check = 0.0
        self._model_mtime: Optional[float] = None
        self._probability_calibration = _parse_probability_calibration(self.provider_config, self.class_labels)
        self._prediction_contract = str(self.provider_config.get("prediction_contract") or "").strip().lower()
        if not self._prediction_contract:
            labels_normalized = [str(item).strip().lower() for item in self.class_labels]
            if labels_normalized == ["p_long_win", "p_short_win"]:
                self._prediction_contract = "action_conditional_pnl_winprob"
        self._warn_stale_calibration()
        self._abstain_min_confidence = _clamp(
            _resolve_float(
                min_confidence,
                _nested_get(self.provider_config, "abstain", "min_confidence"),
                0.0,
            )
        )
        self._abstain_min_margin = _clamp(
            _resolve_float(
                min_margin,
                _nested_get(self.provider_config, "abstain", "min_margin"),
                0.0,
            )
        )
        self._abstain_max_entropy = _clamp(
            _resolve_float(
                max_entropy,
                _nested_get(self.provider_config, "abstain", "max_entropy"),
                1.0,
            )
        )
        self._abstain_min_confidence_by_symbol = {
            k: _clamp(v)
            for k, v in _parse_symbol_float_map(os.getenv("PREDICTION_ONNX_MIN_CONFIDENCE_BY_SYMBOL", "")).items()
        }
        self._abstain_min_margin_by_symbol = {
            k: _clamp(v)
            for k, v in _parse_symbol_float_map(os.getenv("PREDICTION_ONNX_MIN_MARGIN_BY_SYMBOL", "")).items()
        }
        self._abstain_max_entropy_by_symbol = {
            k: _clamp(v)
            for k, v in _parse_symbol_float_map(os.getenv("PREDICTION_ONNX_MAX_ENTROPY_BY_SYMBOL", "")).items()
        }
        self._abstain_min_confidence_by_session = {
            k: _clamp(v)
            for k, v in _parse_keyed_float_map(os.getenv("PREDICTION_ONNX_MIN_CONFIDENCE_BY_SESSION", "")).items()
        }
        self._abstain_min_margin_by_session = {
            k: _clamp(v)
            for k, v in _parse_keyed_float_map(os.getenv("PREDICTION_ONNX_MIN_MARGIN_BY_SESSION", "")).items()
        }
        self._abstain_max_entropy_by_session = {
            k: _clamp(v)
            for k, v in _parse_keyed_float_map(os.getenv("PREDICTION_ONNX_MAX_ENTROPY_BY_SESSION", "")).items()
        }
        self._abstain_min_confidence_by_symbol_session = {
            k: _clamp(v)
            for k, v in _parse_keyed_float_map(
                os.getenv("PREDICTION_ONNX_MIN_CONFIDENCE_BY_SYMBOL_SESSION", "")
            ).items()
        }
        self._abstain_min_margin_by_symbol_session = {
            k: _clamp(v)
            for k, v in _parse_keyed_float_map(
                os.getenv("PREDICTION_ONNX_MIN_MARGIN_BY_SYMBOL_SESSION", "")
            ).items()
        }
        self._abstain_max_entropy_by_symbol_session = {
            k: _clamp(v)
            for k, v in _parse_keyed_float_map(
                os.getenv("PREDICTION_ONNX_MAX_ENTROPY_BY_SYMBOL_SESSION", "")
            ).items()
        }
        self._reject_flat_class = _resolve_bool(
            _nested_get(self.provider_config, "abstain", "reject_flat_class"),
            os.getenv("PREDICTION_ONNX_REJECT_FLAT"),
            default=True,
        )
        # f1_down from model registry for unreliable short class gating (Bug 7)
        self._f1_down: Optional[float] = _safe_float(
            _nested_get(self.provider_config, "metrics", "f1_down")
        )
        _min_f1_raw = os.getenv("PREDICTION_MIN_F1_DOWN_FOR_SHORT")
        self._min_f1_down: Optional[float] = float(_min_f1_raw) if _min_f1_raw else None
        gate_enabled_cfg = self.provider_config.get("critical_feature_gate_enabled")
        if gate_enabled_cfg is None:
            gate_enabled_raw = str(os.getenv("PREDICTION_ONNX_CRITICAL_FEATURE_GATE_ENABLED", "true")).strip().lower()
            self._critical_feature_gate_enabled = gate_enabled_raw in {"1", "true", "yes", "on"}
        else:
            self._critical_feature_gate_enabled = bool(gate_enabled_cfg)
        critical_raw_cfg = self.provider_config.get("critical_features")
        if isinstance(critical_raw_cfg, list):
            critical_features = [str(item).strip() for item in critical_raw_cfg if str(item).strip()]
        else:
            critical_features = _parse_csv_tokens(
                str(
                    os.getenv(
                        "PREDICTION_ONNX_CRITICAL_FEATURES",
                        "ema_fast_15m,ema_slow_15m,atr_5m,atr_5m_baseline,spread_bps,orderbook_imbalance,bid_depth_usd,ask_depth_usd,price",
                    )
                )
            )
        critical_feature_set = {item for item in critical_features if item}
        if self.feature_keys:
            self._critical_features = [key for key in self.feature_keys if key in critical_feature_set]
        else:
            self._critical_features = sorted(critical_feature_set)
        self._critical_feature_min_presence = _clamp(
            _resolve_float(
                self.provider_config.get("critical_feature_min_presence"),
                os.getenv("PREDICTION_ONNX_CRITICAL_FEATURE_MIN_PRESENCE"),
                1.0,
            )
        )

    def _effective_abstain_thresholds(self, symbol: Optional[str], session: Optional[str]) -> tuple[float, float, float]:
        sym = (symbol or "").upper()
        sess = (session or "").upper()
        sym_sess = f"{sym}@{sess}" if sym and sess else ""
        min_conf = self._abstain_min_confidence
        min_margin = self._abstain_min_margin
        max_entropy = self._abstain_max_entropy
        if sess:
            min_conf = self._abstain_min_confidence_by_session.get(sess, min_conf)
            min_margin = self._abstain_min_margin_by_session.get(sess, min_margin)
            max_entropy = self._abstain_max_entropy_by_session.get(sess, max_entropy)
        if sym:
            min_conf = self._abstain_min_confidence_by_symbol.get(sym, min_conf)
            min_margin = self._abstain_min_margin_by_symbol.get(sym, min_margin)
            max_entropy = self._abstain_max_entropy_by_symbol.get(sym, max_entropy)
        if sym_sess:
            min_conf = self._abstain_min_confidence_by_symbol_session.get(sym_sess, min_conf)
            min_margin = self._abstain_min_margin_by_symbol_session.get(sym_sess, min_margin)
            max_entropy = self._abstain_max_entropy_by_symbol_session.get(sym_sess, max_entropy)
        return (
            min_conf,
            min_margin,
            max_entropy,
        )

    def build_prediction(self, features: dict, market_context: dict, timestamp: float) -> Optional[dict]:
        # IMPORTANT: keep prediction execution deterministic and avoid wall-clock reads.
        # Use the snapshot's timestamp as "now" for model reload checks.
        if not self._ensure_session(timestamp):
            return None
        if not self.feature_keys:
            log_warning("onnx_prediction_missing_features")
            return None
        values = []
        missing_features: set[str] = set()
        for key in self.feature_keys:
            value = coerce_float(features.get(key))
            if value is None:
                value = coerce_float(market_context.get(key))
            if value is None:
                missing_features.add(key)
            values.append(value if value is not None else 0.0)
        if self._critical_feature_gate_enabled and self._critical_features:
            missing_critical = [key for key in self._critical_features if key in missing_features]
            present_count = len(self._critical_features) - len(missing_critical)
            present_ratio = present_count / float(max(1, len(self._critical_features)))
            if present_ratio < self._critical_feature_min_presence:
                reason = "onnx_missing_critical_feature"
                return {
                    "timestamp": timestamp,
                    "direction": "flat",
                    "confidence": 0.0,
                    "confidence_raw": 0.0,
                    "source": "onnx_v1",
                    "reject": True,
                    "reason": reason,
                    "critical_feature_gate": {
                        "enabled": True,
                        "min_presence": self._critical_feature_min_presence,
                        "present_ratio": present_ratio,
                        "critical_features": self._critical_features,
                        "missing_critical_features": missing_critical,
                    },
                    "probs": None,
                    "probs_raw": None,
                    "p_up": None,
                    "p_down": None,
                    "p_flat": None,
                    "p_long_win": None,
                    "p_short_win": None,
                    "margin": None,
                    "entropy": None,
                    "calibration_applied": False,
                }
        inputs = {self._input_name: np.asarray([values], dtype=np.float32)}
        try:
            outputs = self._session.run(None, inputs)
        except Exception as exc:
            log_warning("onnx_prediction_inference_failed", error=str(exc))
            self._session = None
            self._input_name = None
            self._output_names = []
            return None
        if self._prediction_contract == "action_conditional_pnl_winprob":
            action_probs = _extract_action_winprob(outputs, self._output_names)
            if action_probs is None:
                log_warning("onnx_action_contract_output_parse_failed", model_path=self.model_path)
                return None
            p_long_win, p_short_win = action_probs
            confidence = max(p_long_win, p_short_win)
            margin = abs(p_long_win - p_short_win)
            direction = "up" if p_long_win >= p_short_win else "down"
            effective_min_confidence, effective_min_margin, _ = self._effective_abstain_thresholds(
                features.get("symbol") or market_context.get("symbol"),
                market_context.get("session"),
            )
            reject = bool(confidence < effective_min_confidence or margin < effective_min_margin)
            reason = None
            if confidence < effective_min_confidence:
                reason = "action_low_winprob"
            elif margin < effective_min_margin:
                reason = "action_low_margin"
            return {
                "timestamp": timestamp,
                "direction": direction,
                "confidence": _clamp(confidence),
                "confidence_raw": _clamp(confidence),
                "source": "onnx_action_v1",
                "reject": reject,
                "reason": reason,
                "abstain": {
                    "min_confidence": effective_min_confidence,
                    "min_margin": effective_min_margin,
                    "max_entropy": None,
                },
                "probs": {"p_long_win": _clamp(p_long_win), "p_short_win": _clamp(p_short_win)},
                "probs_raw": {"p_long_win": _clamp(p_long_win), "p_short_win": _clamp(p_short_win)},
                "p_long_win": _clamp(p_long_win),
                "p_short_win": _clamp(p_short_win),
                "margin": _clamp(margin),
                "entropy": None,
                "calibration_applied": False,
            }
        probs = _extract_probabilities(outputs, self._output_names, self.class_labels)
        prob_map_raw: dict[str, float] = {}
        margin = None
        entropy = None
        abstain_reason = None
        confidence_raw = None
        calibration_applied = False
        symbol = features.get("symbol") or market_context.get("symbol")
        session = market_context.get("session")
        if probs:
            prob_map_raw = {
                label: _clamp(probs[i]) for i, label in enumerate(self.class_labels) if i < len(probs)
            }
            prob_map, calibration_applied = _apply_probability_calibration(
                prob_map_raw, self.class_labels, self._probability_calibration
            )
            idx = int(max(range(len(self.class_labels)), key=lambda i: prob_map.get(self.class_labels[i], 0.0)))
            direction = self.class_labels[idx] if self.class_labels else "flat"
            confidence = _clamp(prob_map.get(direction, 0.0))
            confidence_raw = _clamp(prob_map_raw.get(direction, confidence))
            margin = _probability_margin(prob_map, self.class_labels)
            entropy = _normalized_entropy(prob_map, self.class_labels)
            effective_min_confidence, effective_min_margin, effective_max_entropy = self._effective_abstain_thresholds(
                symbol, session
            )
            abstain_reason = _abstain_reason(
                confidence=confidence,
                margin=margin,
                entropy=entropy,
                min_confidence=effective_min_confidence,
                min_margin=effective_min_margin,
                max_entropy=effective_max_entropy,
                direction=direction,
                reject_flat_class=self._reject_flat_class,
                f1_down=self._f1_down,
                min_f1_down=self._min_f1_down,
            )
        else:
            result = _coerce_output(outputs)
            if not result:
                return None
            direction, confidence = _interpret_prediction(result, self.class_labels)
            prob_map = {}
        # Provide per-class probabilities when available. These enable side-aware p_hat
        # mapping (e.g., long -> p_up, short -> p_down) without abusing "confidence".
        p_up = prob_map.get("up")
        p_down = prob_map.get("down")
        p_flat = prob_map.get("flat")
        # Keep side probabilities explicit for downstream gates/alignment.
        # For multiclass (down/flat/up), directional win likelihood for taking a side
        # is the class probability mass of that side.
        p_long_win = p_up
        p_short_win = p_down
        if p_long_win is None or p_short_win is None:
            if direction == "up":
                p_long_win = confidence
                p_short_win = 1.0 - confidence
            elif direction == "down":
                p_short_win = confidence
                p_long_win = 1.0 - confidence
            else:
                p_long_win = 0.5
                p_short_win = 0.5
        return {
            "timestamp": timestamp,
            "direction": direction,
            "confidence": confidence,
            "confidence_raw": confidence_raw,
            "source": "onnx_v1",
            "reject": bool(abstain_reason),
            "reason": abstain_reason,
            # Explainable abstain thresholds (effective, per-symbol). These are used only
            # for diagnostics/UI and must not be interpreted as model outputs.
            "abstain": {
                "min_confidence": effective_min_confidence if probs else None,
                "min_margin": effective_min_margin if probs else None,
                "max_entropy": effective_max_entropy if probs else None,
                "reject_flat_class": self._reject_flat_class if probs else None,
                "f1_down": self._f1_down if probs else None,
                "min_f1_down_for_short": self._min_f1_down if probs else None,
            },
            "probs": prob_map if prob_map else None,
            "probs_raw": prob_map_raw if prob_map_raw else None,
            "p_up": p_up,
            "p_down": p_down,
            "p_flat": p_flat,
            "p_long_win": _clamp(p_long_win) if p_long_win is not None else None,
            "p_short_win": _clamp(p_short_win) if p_short_win is not None else None,
            "margin": margin,
            "entropy": entropy,
            "calibration_applied": calibration_applied,
        }

    def validate(self, now_ts: float | None = None) -> bool:
        """Eagerly validate model path/runtime and load a session if possible."""
        ts = _resolve_float(now_ts, 0.0, 0.0)
        return self._ensure_session(ts)

    def _warn_stale_calibration(self) -> None:
        payload = self.provider_config.get("probability_calibration")
        if not isinstance(payload, dict):
            return
        fitted_at = _resolve_float(payload.get("fitted_at"), None)
        if fitted_at is None:
            return
        max_age_sec = _resolve_float(os.getenv("PREDICTION_CALIBRATION_MAX_AGE_SEC"), 7 * 24 * 3600.0, 7 * 24 * 3600.0)
        age = time.time() - fitted_at
        if age > max_age_sec:
            log_warning(
                "onnx_calibration_stale",
                fitted_at=fitted_at,
                age_sec=round(age, 1),
                max_age_sec=max_age_sec,
                model_path=self.model_path,
            )

    def _ensure_session(self, now_ts: float) -> bool:
        self._reload_if_needed(now_ts)
        if self._session is not None:
            return True
        if not self.model_path:
            log_warning("onnx_prediction_missing_model_path")
            return False
        if not os.path.exists(self.model_path):
            log_warning("onnx_prediction_model_missing", path=self.model_path)
            return False
        if ort is None or np is None:
            log_warning("onnx_prediction_missing_runtime")
            return False
        try:
            self._session = ort.InferenceSession(self.model_path, providers=["CPUExecutionProvider"])
            inputs = self._session.get_inputs()
            self._input_name = inputs[0].name if inputs else None
            self._output_names = [item.name for item in self._session.get_outputs()]
            self._model_mtime = _safe_mtime(self.model_path)
        except Exception as exc:
            log_warning("onnx_prediction_load_failed", error=str(exc))
            self._session = None
            self._input_name = None
            self._output_names = []
            return False
        if not self._input_name:
            log_warning("onnx_prediction_missing_input")
            return False
        return True

    def _reload_if_needed(self, now_ts: float) -> None:
        if not self.model_path or self._refresh_interval_sec <= 0:
            return
        try:
            now = float(now_ts)
        except (TypeError, ValueError):
            return
        if (now - self._last_refresh_check) < self._refresh_interval_sec:
            return
        self._last_refresh_check = now
        mtime = _safe_mtime(self.model_path)
        if mtime is None:
            return
        if self._model_mtime is None:
            self._model_mtime = mtime
            return
        if mtime > self._model_mtime:
            self._model_mtime = mtime
            self._session = None
            self._input_name = None
            self._output_names = []
            log_info("onnx_prediction_model_reloaded", path=self.model_path, mtime=mtime)


@dataclass
class OnnxExpertRoute:
    id: str
    provider: PredictionProvider
    match: dict[str, set[str]] = field(default_factory=dict)
    priority: int = 0
    disabled: bool = False


class RoutedOnnxPredictionProvider:
    """
    Mixture-of-experts style router for ONNX prediction providers.

    Routing is deterministic and rule-based:
    - first, highest-priority matching expert is selected
    - otherwise falls back to the default provider
    """

    def __init__(
        self,
        default_provider: PredictionProvider,
        experts: list[OnnxExpertRoute],
    ):
        self.default_provider = default_provider
        self.experts = sorted(experts, key=lambda item: (-int(item.priority), str(item.id)))

    def _matches(self, route: OnnxExpertRoute, features: dict, market_context: dict) -> bool:
        match = route.match or {}
        if not match:
            return True
        symbol = str(features.get("symbol") or market_context.get("symbol") or "").upper()
        session = str(market_context.get("session") or "").upper()
        volatility_regime = str(market_context.get("volatility_regime") or "").lower()
        trend_regime = str(market_context.get("trend_regime") or "").lower()
        spread_regime = str(market_context.get("spread_regime") or "").lower()
        market_regime = str(market_context.get("market_regime") or "").lower()
        profile_id = str(market_context.get("profile_id") or "").lower()
        strategy_id = str(market_context.get("strategy_id") or "").lower()
        checks = {
            "symbols": symbol,
            "sessions": session,
            "volatility_regimes": volatility_regime,
            "trend_regimes": trend_regime,
            "spread_regimes": spread_regime,
            "market_regimes": market_regime,
            "profile_ids": profile_id,
            "strategy_ids": strategy_id,
        }
        for key, value in checks.items():
            allowed = match.get(key)
            if not allowed:
                continue
            if value not in allowed:
                return False
        return True

    def _annotate(self, payload: dict, expert_id: str, matched_by: dict[str, list[str]]) -> dict:
        out = dict(payload)
        out["expert_id"] = expert_id
        out["expert_routed"] = expert_id != "default"
        if matched_by:
            out["expert_match"] = matched_by
        return out

    def build_prediction(self, features: dict, market_context: dict, timestamp: float) -> Optional[dict]:
        symbol = str(features.get("symbol") or market_context.get("symbol") or "").upper()
        session = str(market_context.get("session") or "").upper()
        for route in self.experts:
            if route.disabled:
                continue
            if not self._matches(route, features, market_context):
                continue
            payload = route.provider.build_prediction(features, market_context, timestamp)
            if payload:
                return self._annotate(payload, route.id, {k: sorted(v) for k, v in (route.match or {}).items()})
            log_warning(
                "onnx_expert_no_payload_fallback_default",
                expert_id=route.id,
                symbol=symbol,
                session=session,
            )
        payload = self.default_provider.build_prediction(features, market_context, timestamp)
        if not payload:
            log_warning(
                "onnx_default_no_payload",
                symbol=symbol,
                session=session,
            )
            return None
        return self._annotate(payload, "default", {})

    def validate(self, now_ts: float | None = None) -> bool:
        ok = True
        default_validate = getattr(self.default_provider, "validate", None)
        if callable(default_validate):
            ok = bool(default_validate(now_ts))
        for route in self.experts:
            validate_fn = getattr(route.provider, "validate", None)
            if callable(validate_fn):
                is_valid = bool(validate_fn(now_ts))
                route.disabled = not is_valid
                if not is_valid:
                    log_warning("onnx_expert_validation_failed", expert_id=route.id)
        if self.experts and not any(not route.disabled for route in self.experts):
            log_warning("onnx_all_experts_disabled")
            return False
        return ok


def _normalize_match_map(raw: Any) -> dict[str, set[str]]:
    if not isinstance(raw, dict):
        return {}
    out: dict[str, set[str]] = {}
    for key in (
        "symbols",
        "sessions",
        "volatility_regimes",
        "trend_regimes",
        "spread_regimes",
        "market_regimes",
        "profile_ids",
        "strategy_ids",
    ):
        value = raw.get(key)
        if value is None:
            continue
        if isinstance(value, str):
            tokens = [value]
        elif isinstance(value, list):
            tokens = [str(item) for item in value if item is not None]
        else:
            continue
        if key in {"symbols", "sessions"}:
            normalized = {token.strip().upper() for token in tokens if token.strip()}
        else:
            normalized = {token.strip().lower() for token in tokens if token.strip()}
        if normalized:
            out[key] = normalized
    return out


def _resolve_onnx_model_path(model_path: Optional[str], config_path: str = "") -> Optional[str]:
    if not model_path:
        return None
    model = Path(str(model_path)).expanduser()
    if model.is_absolute():
        return str(model)
    candidates: list[Path] = []
    if config_path:
        try:
            cfg_path = Path(config_path).expanduser().resolve()
            candidates.append((cfg_path.parent / model).resolve())
        except Exception:
            pass
    try:
        repo_root = Path(__file__).parent.parent.parent.parent
        candidates.append((repo_root / "quantgambit-python" / model).resolve())
        candidates.append((repo_root / model).resolve())
    except Exception:
        pass
    candidates.append((Path.cwd() / model).resolve())
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return str(candidates[0] if candidates else model)


def _build_routed_onnx_provider(
    model_path: Optional[str],
    feature_keys: Optional[list[str]],
    class_labels: Optional[list[str]],
    provider_config: Optional[dict[str, Any]],
    min_confidence: Optional[float],
    min_margin: Optional[float],
    max_entropy: Optional[float],
) -> PredictionProvider:
    config = provider_config or {}
    config_path = str(config.get("__config_path") or "")
    resolved_default_model = _resolve_onnx_model_path(model_path, config_path)
    default_provider = OnnxPredictionProvider(
        model_path=resolved_default_model,
        feature_keys=feature_keys,
        class_labels=class_labels,
        provider_config=config,
        min_confidence=min_confidence,
        min_margin=min_margin,
        max_entropy=max_entropy,
    )
    expert_items = config.get("experts")
    if not isinstance(expert_items, list) or not expert_items:
        return default_provider
    routes: list[OnnxExpertRoute] = []
    default_features = feature_keys or []
    default_classes = class_labels or ["down", "flat", "up"]
    for idx, item in enumerate(expert_items):
        if not isinstance(item, dict):
            continue
        expert_id = str(item.get("id") or f"expert_{idx}").strip()
        expert_model_path = item.get("model_path") or item.get("onnx_path")
        if not expert_model_path:
            log_warning("onnx_expert_missing_model_path", expert_id=expert_id)
            continue
        resolved_expert_model = _resolve_onnx_model_path(str(expert_model_path), config_path)
        expert_features = item.get("feature_keys") if isinstance(item.get("feature_keys"), list) else default_features
        expert_classes = item.get("class_labels") if isinstance(item.get("class_labels"), list) else default_classes
        expert_provider_cfg = item.get("provider_config")
        if not isinstance(expert_provider_cfg, dict):
            expert_provider_cfg = {}
        if isinstance(item.get("probability_calibration"), dict):
            expert_provider_cfg = dict(expert_provider_cfg)
            expert_provider_cfg["probability_calibration"] = item.get("probability_calibration")
        expert_provider = OnnxPredictionProvider(
            model_path=resolved_expert_model,
            feature_keys=[str(k) for k in expert_features],
            class_labels=[str(k) for k in expert_classes],
            provider_config=expert_provider_cfg,
            min_confidence=min_confidence,
            min_margin=min_margin,
            max_entropy=max_entropy,
        )
        routes.append(
            OnnxExpertRoute(
                id=expert_id,
                provider=expert_provider,
                match=_normalize_match_map(item.get("match")),
                priority=int(item.get("priority") or 0),
            )
        )
    if not routes:
        return default_provider
    return RoutedOnnxPredictionProvider(default_provider=default_provider, experts=routes)


def _coerce_output(outputs: list) -> list[float]:
    if not outputs:
        return []
    value = outputs[0]
    if hasattr(value, "tolist"):
        value = value.tolist()
    if isinstance(value, list) and value and isinstance(value[0], list):
        value = value[0]
    if isinstance(value, list):
        out: list[float] = []
        for item in value:
            try:
                out.append(float(item))
            except (TypeError, ValueError):
                continue
        return out
    return []


def _extract_probabilities(
    outputs: list,
    output_names: list[str],
    labels: list[str],
) -> list[float] | None:
    if not outputs:
        return None

    def _normalize(value):
        if hasattr(value, "tolist"):
            value = value.tolist()
        if isinstance(value, list) and value and isinstance(value[0], list):
            if len(value) == 1:
                value = value[0]
        return value

    def _as_probs(value):
        value = _normalize(value)
        if isinstance(value, list) and value and isinstance(value[0], dict):
            value = value[0]
        def _float_or_zero(item) -> float:
            if hasattr(item, "tolist"):
                item = item.tolist()
            # Some runtimes expose map values as singleton tensor/list containers.
            if isinstance(item, (list, tuple)):
                if not item:
                    return 0.0
                if len(item) == 1:
                    return _float_or_zero(item[0])
                # If multiple values unexpectedly appear, use the first deterministically.
                return _float_or_zero(item[0])
            try:
                return float(item)
            except (TypeError, ValueError):
                return 0.0
        if isinstance(value, dict) and labels:
            # sklearn-onnx often returns probabilities as a map(int64 -> float) where
            # keys are class indices 0..k-1. Map those indices to the label order.
            if value and all(isinstance(k, numbers.Integral) for k in value.keys()):
                return [_float_or_zero(value.get(i, 0.0)) for i in range(len(labels))]
            return [_float_or_zero(value.get(label, 0.0)) for label in labels]
        if isinstance(value, list) and labels and len(value) == len(labels):
            return [_float_or_zero(item) for item in value]
        return None

    for name, value in zip(output_names, outputs):
        if "prob" in name.lower():
            probs = _as_probs(value)
            if probs is not None:
                return probs

    for value in outputs:
        probs = _as_probs(value)
        if probs is not None:
            return probs

    if len(outputs) > 1:
        return _as_probs(outputs[1])
    return None


def _extract_action_winprob(outputs: list, output_names: list[str]) -> tuple[float, float] | None:
    if not outputs:
        return None
    named = list(zip(output_names, outputs))
    for name, value in named:
        key = str(name).lower()
        if "p_long_win" in key:
            if hasattr(value, "tolist"):
                value = value.tolist()
            if isinstance(value, list):
                if value and isinstance(value[0], list):
                    value = value[0]
                if value:
                    try:
                        p_long = float(value[0])
                    except (TypeError, ValueError):
                        p_long = 0.0
                else:
                    p_long = 0.0
            else:
                p_long = _safe_float(value, 0.0) or 0.0
            p_short = None
            for name2, value2 in named:
                if "p_short_win" in str(name2).lower():
                    if hasattr(value2, "tolist"):
                        value2 = value2.tolist()
                    if isinstance(value2, list):
                        if value2 and isinstance(value2[0], list):
                            value2 = value2[0]
                        v = value2[0] if value2 else 0.0
                    else:
                        v = value2
                    p_short = _safe_float(v, 0.0) or 0.0
                    break
            if p_short is not None:
                return (_clamp(p_long), _clamp(p_short))
    # Fallback for common ONNX output where first tensor is [p_long_win, p_short_win].
    first = outputs[0]
    if hasattr(first, "tolist"):
        first = first.tolist()
    if isinstance(first, list):
        if first and isinstance(first[0], list):
            first = first[0]
        if len(first) >= 2:
            return (_clamp(_safe_float(first[0], 0.0) or 0.0), _clamp(_safe_float(first[1], 0.0) or 0.0))
    return None


def _interpret_prediction(values: list[float], labels: list[str]) -> tuple[str, float]:
    if len(values) == len(labels) and len(values) > 1:
        idx = int(max(range(len(values)), key=lambda i: values[i]))
        confidence = _clamp(values[idx])
        return labels[idx], confidence
    if len(values) >= 2:
        score = values[0]
        confidence = _clamp(values[1])
        return _direction_from_score(score), confidence
    if len(values) == 1:
        score = values[0]
        confidence = _clamp(abs(score))
        return _direction_from_score(score), confidence
    return "flat", 0.0


def _safe_mtime(path: str) -> Optional[float]:
    try:
        return os.path.getmtime(path)
    except Exception:
        return None


def _direction_from_score(score: float) -> str:
    if score > 0.05:
        return "up"
    if score < -0.05:
        return "down"
    return "flat"


def _clamp(value: float) -> float:
    try:
        value_f = float(value)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(value_f):
        return 0.0
    return max(0.0, min(1.0, value_f))


def _safe_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _nested_get(data: dict[str, Any], *keys: str) -> Any:
    cur: Any = data
    for key in keys:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


def _resolve_float(*candidates: Any) -> float:
    for value in candidates:
        resolved = _safe_float(value)
        if resolved is not None:
            return float(resolved)
    return 0.0


def _parse_probability_calibration(
    provider_config: dict[str, Any],
    class_labels: Optional[list[str]] = None,
) -> dict[str, dict[str, float]]:
    calibration = provider_config.get("probability_calibration")
    if not isinstance(calibration, dict):
        calibration = provider_config.get("calibration")
    if not isinstance(calibration, dict):
        return {}
    raw_map = calibration.get("per_class")
    if not isinstance(raw_map, dict):
        raw_map = calibration
    parsed: dict[str, dict[str, float]] = {}
    allowed_labels = {str(label) for label in (class_labels or [])}
    for label, params in raw_map.items():
        if not isinstance(params, dict):
            continue
        a = _safe_float(params.get("a"))
        b = _safe_float(params.get("b"))
        if a is None or b is None:
            continue
        key = str(label)
        if allowed_labels and key not in allowed_labels:
            continue
        parsed[key] = {"a": float(a), "b": float(b)}
    return parsed


def _apply_logit_affine(prob: float, a: float, b: float) -> float:
    eps = 1e-6
    p = max(eps, min(1.0 - eps, _clamp(prob)))
    logit = math.log(p / (1.0 - p))
    z = (a * logit) + b
    if z >= 40:
        return 1.0
    if z <= -40:
        return 0.0
    return 1.0 / (1.0 + math.exp(-z))


def _apply_probability_calibration(
    probs: dict[str, float],
    class_labels: list[str],
    calibration: dict[str, dict[str, float]],
) -> tuple[dict[str, float], bool]:
    normalized = {label: _clamp(probs.get(label, 0.0)) for label in class_labels}
    if not calibration:
        return normalized, False
    calibrated: dict[str, float] = {}
    applied = False
    for label in class_labels:
        params = calibration.get(label)
        value = normalized.get(label, 0.0)
        if params:
            value = _apply_logit_affine(value, params.get("a", 1.0), params.get("b", 0.0))
            applied = True
        calibrated[label] = _clamp(value)
    total = sum(calibrated.values())
    if total <= 0:
        return normalized, False
    for label in class_labels:
        calibrated[label] = calibrated[label] / total
    return calibrated, applied


def _probability_margin(probs: dict[str, float], class_labels: list[str]) -> float:
    values = sorted((_clamp(probs.get(label, 0.0)) for label in class_labels), reverse=True)
    if not values:
        return 0.0
    if len(values) == 1:
        return values[0]
    return max(0.0, values[0] - values[1])


def _normalized_entropy(probs: dict[str, float], class_labels: list[str]) -> float:
    values = [_clamp(probs.get(label, 0.0)) for label in class_labels]
    total = sum(values)
    if total <= 0:
        return 1.0
    entropy = 0.0
    for value in values:
        p = value / total
        if p > 0:
            entropy -= p * math.log(p)
    base = math.log(max(2, len(class_labels)))
    if base <= 0:
        return 0.0
    return _clamp(entropy / base)


def _abstain_reason(
    confidence: float,
    margin: float,
    entropy: float,
    min_confidence: float,
    min_margin: float,
    max_entropy: float,
    *,
    direction: Optional[str] = None,
    reject_flat_class: bool = True,
    f1_down: Optional[float] = None,
    min_f1_down: Optional[float] = None,
) -> Optional[str]:
    if reject_flat_class and direction == "flat":
        return "onnx_flat_class"
    if direction == "down" and f1_down is not None and min_f1_down is not None and f1_down < min_f1_down:
        return "onnx_unreliable_down_class"
    if confidence < min_confidence:
        return "onnx_low_confidence"
    if margin < min_margin:
        return "onnx_low_margin"
    if entropy > max_entropy:
        return "onnx_high_entropy"
    return None


def build_prediction_provider(
    name: str,
    model=None,
    model_path: Optional[str] = None,
    feature_keys: Optional[list[str]] = None,
    class_labels: Optional[list[str]] = None,
    provider_config: Optional[dict[str, Any]] = None,
    min_confidence: Optional[float] = None,
    min_margin: Optional[float] = None,
    max_entropy: Optional[float] = None,
) -> PredictionProvider:
    normalized = (name or "").lower()
    if normalized in {"legacy", "deeptrader"}:
        return LegacyPredictionProvider()
    if normalized in {"model", "ml"}:
        return ModelPredictionProvider(model=model)
    if normalized in {"onnx"}:
        return _build_routed_onnx_provider(
            model_path=model_path,
            feature_keys=feature_keys,
            class_labels=class_labels,
            provider_config=provider_config,
            min_confidence=min_confidence,
            min_margin=min_margin,
            max_entropy=max_entropy,
        )
    if normalized in {"deepseek_context", "ai_spot_swing", "context_model"}:
        return DeepSeekContextPredictionProvider(provider_config=provider_config)
    return HeuristicPredictionProvider(provider_config=provider_config)
