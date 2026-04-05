"""Shared AI context models and Redis readers."""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Literal, Optional

import redis


Direction = Literal["long", "short", "flat", "abstain"]

_REDIS_URL = os.getenv("BOT_REDIS_URL") or os.getenv("REDIS_URL", "redis://localhost:6379")
_SENTIMENT_KEY = "ai:sentiment:{symbol}"
_SENTIMENT_GLOBAL_KEY = "ai:sentiment:global"
_CONTEXT_CACHE_TTL_SEC = max(1, int(os.getenv("AI_CONTEXT_CACHE_TTL_SEC", "15")))
_client = None
_cache: dict[str, tuple[dict[str, Any], float]] = {}


@dataclass
class SentimentSnapshot:
    news_sentiment: float | None = None
    social_sentiment: float | None = None
    news_count_1h: int = 0
    social_count_15m: int = 0
    source_quality: float = 0.0
    top_topics: list[str] = field(default_factory=list)
    event_flags: list[str] = field(default_factory=list)
    summary: str = ""
    asof_ts_ms: int = 0
    age_ms: int = 0
    is_stale: bool = True


@dataclass
class EventContext:
    has_macro_event: bool = False
    has_symbol_catalyst: bool = False
    exchange_risk_flag: bool = False
    narrative_bias: float | None = None
    event_flags: list[str] = field(default_factory=list)
    asof_ts_ms: int = 0
    age_ms: int = 0


@dataclass
class ContextQuality:
    fast_features_ready: bool = False
    slow_features_ready: bool = False
    feature_completeness: float = 0.0
    sentiment_fresh: bool = False
    market_data_stale: bool = False
    reasons: list[str] = field(default_factory=list)


@dataclass
class MarketContextEnvelope:
    symbol: str
    asof_ts_ms: int
    microstructure: dict[str, Any]
    regime: dict[str, Any]
    sentiment: SentimentSnapshot | None
    event_context: EventContext | None
    quality: ContextQuality

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ProviderRequest:
    symbol: str
    ts_ms: int
    feature_snapshot: dict[str, Any]
    market_context: dict[str, Any]
    profile: str
    strategy: str
    max_inference_ms: int
    trace_id: str


@dataclass
class ProviderResponse:
    direction: Direction
    confidence: float
    expected_move_bps: float | None
    horizon_sec: int | None
    reason_codes: list[str] = field(default_factory=list)
    risk_flags: list[str] = field(default_factory=list)
    valid_for_ms: int = 0
    provider_name: str = ""
    provider_version: str = ""
    latency_ms: int = 0
    fallback_used: bool = False
    raw_score: float | None = None

    def to_prediction_payload(self, timestamp: float) -> dict[str, Any]:
        direction = {
            "long": "up",
            "short": "down",
            "flat": "flat",
            "abstain": "flat",
        }[self.direction]
        reject = self.direction == "abstain"
        reason = self.reason_codes[0] if self.reason_codes else None
        payload = {
            "timestamp": timestamp,
            "direction": direction,
            "confidence": float(self.confidence),
            "source": self.provider_name or "deepseek_context",
            "provider_version": self.provider_version or "",
            "reject": reject,
            "reason": reason,
            "reason_codes": list(self.reason_codes),
            "risk_flags": list(self.risk_flags),
            "expected_move_bps": self.expected_move_bps,
            "horizon_sec": self.horizon_sec,
            "valid_for_ms": int(self.valid_for_ms),
            "provider_latency_ms": int(self.latency_ms),
            "fallback_used": bool(self.fallback_used),
            "raw_score": self.raw_score,
        }
        if reject and reason is None:
            payload["reason"] = "ai_abstain"
        return payload


def _get_client():
    global _client
    if _client is None:
        _client = redis.from_url(_REDIS_URL, decode_responses=True)
    return _client


def _load_cached_json(key: str) -> dict[str, Any]:
    now = time.time()
    cached = _cache.get(key)
    if cached and (now - cached[1]) < _CONTEXT_CACHE_TTL_SEC:
        return cached[0]
    raw = _get_client().get(key)
    if not raw:
        payload: dict[str, Any] = {}
    else:
        try:
            payload = json.loads(raw)
        except Exception:
            payload = {}
    _cache[key] = (payload, now)
    return payload


def get_symbol_context(symbol: str) -> dict[str, Any]:
    return _load_cached_json(_SENTIMENT_KEY.format(symbol=str(symbol or "").upper()))


def get_global_context() -> dict[str, Any]:
    return _load_cached_json(_SENTIMENT_GLOBAL_KEY)


def get_sentiment_score(symbol: str) -> float:
    context = get_symbol_context(symbol)
    sentiment = context.get("sentiment") if isinstance(context, dict) else {}
    if not isinstance(sentiment, dict):
        sentiment = {}
    score = sentiment.get("combined_sentiment")
    try:
        return float(score)
    except (TypeError, ValueError):
        return 0.0


def build_context_quality(
    market_context: dict[str, Any],
    sentiment_payload: Optional[dict[str, Any]],
    reasons: Optional[list[str]] = None,
) -> ContextQuality:
    quality = ContextQuality(
        fast_features_ready=(market_context.get("data_completeness") or 0.0) >= 0.9,
        slow_features_ready=bool(sentiment_payload),
        feature_completeness=float(market_context.get("data_completeness") or 0.0),
        sentiment_fresh=False,
        market_data_stale=str(market_context.get("data_quality_status") or "").lower() == "stale",
        reasons=list(reasons or []),
    )
    sentiment = sentiment_payload.get("sentiment") if isinstance(sentiment_payload, dict) else None
    if isinstance(sentiment, dict):
        quality.sentiment_fresh = not bool(sentiment.get("is_stale"))
    return quality
