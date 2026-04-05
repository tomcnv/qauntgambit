"""Read ONNX prediction from Redis (sync, for use in strategies)."""

import json
import os
import time
import redis

_REDIS_URL = os.getenv("BOT_REDIS_URL") or os.getenv("REDIS_URL", "redis://localhost:6379")
_TENANT = os.getenv("TENANT_ID") or os.getenv("DEFAULT_TENANT_ID", "11111111-1111-1111-1111-111111111111")
_BOT = os.getenv("BOT_ID") or os.getenv("DEFAULT_BOT_ID", "")
_client = None
_cache = {}
_CACHE_TTL = 10  # seconds


def _get_client():
    global _client
    if _client is None:
        _client = redis.from_url(_REDIS_URL, decode_responses=True)
    return _client


def get_prediction(symbol: str) -> dict:
    """Get latest prediction for symbol. Returns {} if unavailable. Cached 10s."""
    now = time.time()
    cached = _cache.get(symbol)
    if cached and now - cached[1] < _CACHE_TTL:
        return cached[0]
    try:
        key = f"quantgambit:{_TENANT}:{_BOT}:prediction:{symbol}:latest"
        raw = _get_client().get(key)
        if raw:
            data = json.loads(raw)
            _cache[symbol] = (data, now)
            return data
    except Exception:
        pass
    return {}
