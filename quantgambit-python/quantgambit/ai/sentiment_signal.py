"""Crypto Sentiment Signal — scrapes free news/social feeds and scores with LLM.

Sources (all free, no API key needed):
- CoinGecko trending coins API
- DeFiLlama TVL changes (protocol health proxy)
- Reddit r/cryptocurrency, r/bitcoin (via old.reddit.com JSON)
- Fear & Greed Index

Publishes sentiment to Redis for the trading pipeline to consume.

Usage: python -m quantgambit.ai.sentiment_signal
"""

import asyncio
import json
import os
import time
import logging
from datetime import datetime, timezone

import httpx
import redis.asyncio as redis

from quantgambit.ai import llm_complete

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

REDIS_URL = os.getenv("BOT_REDIS_URL") or os.getenv("REDIS_URL", "redis://localhost:6379")
SENTIMENT_KEY = "ai:sentiment:{symbol}"
SENTIMENT_GLOBAL_KEY = "ai:sentiment:global"
POLL_INTERVAL = int(os.getenv("SENTIMENT_POLL_SEC", "300"))  # 5 min default

# Symbols we care about
SYMBOLS = ["BTC", "ETH", "SOL"]
SYMBOL_MAP = {"BTC": "BTCUSDT", "ETH": "ETHUSDT", "SOL": "SOLUSDT"}

SYSTEM_PROMPT = """You are a crypto market sentiment analyst for spot and swing trading.
Given recent headlines and market tone inputs, score the overall context for each asset.
Return ONLY valid JSON with this exact shape:
{
  "BTC": {
    "news_sentiment": 0.3,
    "social_sentiment": 0.1,
    "combined_sentiment": 0.24,
    "summary": "brief reason",
    "top_topics": ["etf", "risk-on"],
    "event_flags": ["macro_week"],
    "narrative_bias": 0.2,
    "source_quality": 0.8
  },
  "ETH": {
    "news_sentiment": -0.1,
    "social_sentiment": 0.0,
    "combined_sentiment": -0.05,
    "summary": "brief reason",
    "top_topics": ["upgrade"],
    "event_flags": [],
    "narrative_bias": -0.1,
    "source_quality": 0.75
  },
  "SOL": {
    "news_sentiment": 0.0,
    "social_sentiment": 0.2,
    "combined_sentiment": 0.1,
    "summary": "brief reason",
    "top_topics": ["memecoins"],
    "event_flags": [],
    "narrative_bias": 0.1,
    "source_quality": 0.7
  },
  "market": {
    "combined_sentiment": 0.2,
    "summary": "overall crypto market mood",
    "top_topics": ["etf", "macro"],
    "event_flags": ["macro_week"],
    "risk_tone": 0.2,
    "source_quality": 0.8
  }
}

Use score range -1.0 to +1.0. Be conservative; most news is noise."""


async def _fetch_defillama_tvl() -> list[str]:
    """Fetch TVL changes from DeFiLlama (free, no key)."""
    url = "https://api.llama.fi/protocols"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url)
            if resp.status_code != 200:
                return []
            protocols = resp.json()[:20]
            headlines = []
            for p in protocols:
                change_1d = p.get("change_1d")
                if change_1d is not None:
                    direction = "up" if change_1d > 0 else "down"
                    headlines.append(f"{p['name']} TVL {direction} {abs(change_1d):.1f}% (24h)")
            return headlines[:10]
    except Exception as e:
        logger.warning("defillama_error: %s", e)
        return []


async def _fetch_reddit(subreddit: str = "cryptocurrency", limit: int = 10) -> list[str]:
    """Fetch top post titles from Reddit JSON API."""
    url = f"https://old.reddit.com/r/{subreddit}/hot.json?limit={limit}"
    try:
        async with httpx.AsyncClient(timeout=10, headers={"User-Agent": "QuantGambit/1.0"}) as client:
            resp = await client.get(url)
            if resp.status_code != 200:
                return []
            data = resp.json()
            return [p["data"]["title"] for p in (data.get("data", {}).get("children") or [])[:limit]]
    except Exception as e:
        logger.warning("reddit_error subreddit=%s: %s", subreddit, e)
        return []


async def _fetch_coingecko_trending() -> list[str]:
    """Fetch trending coins from CoinGecko (free, no key)."""
    url = "https://api.coingecko.com/api/v3/search/trending"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url)
            if resp.status_code != 200:
                return []
            coins = resp.json().get("coins", [])
            return [f"{c['item']['name']} ({c['item']['symbol']}) trending — rank #{c['item']['market_cap_rank'] or '?'}" for c in coins[:7]]
    except Exception as e:
        logger.warning("coingecko_error: %s", e)
        return []


async def _fetch_fear_greed() -> str:
    """Fetch Fear & Greed Index (free)."""
    url = "https://api.alternative.me/fng/?limit=1"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url)
            if resp.status_code != 200:
                return ""
            data = resp.json().get("data", [{}])[0]
            return f"Fear & Greed Index: {data.get('value', '?')} ({data.get('value_classification', '?')})"
    except Exception as e:
        logger.warning("fear_greed_error: %s", e)
        return ""


async def score_sentiment() -> dict:
    """Gather headlines from all sources and score with LLM."""
    # Fetch all sources in parallel
    results = await asyncio.gather(
        _fetch_defillama_tvl(),
        _fetch_reddit("cryptocurrency"),
        _fetch_reddit("bitcoin"),
        _fetch_coingecko_trending(),
        _fetch_fear_greed(),
        return_exceptions=True,
    )

    source_buckets = {
        "news": results[0] if isinstance(results[0], list) else [],
        "social": [],
        "trending": results[3] if isinstance(results[3], list) else [],
    }
    if isinstance(results[1], list):
        source_buckets["social"].extend(results[1])
    if isinstance(results[2], list):
        source_buckets["social"].extend(results[2])
    headlines = []
    for bucket in source_buckets.values():
        headlines.extend(bucket)
    fear_greed = results[4] if isinstance(results[4], str) else ""

    if not headlines:
        logger.warning("no_headlines_fetched")
        return {}

    # Deduplicate and limit
    seen = set()
    unique = []
    for h in headlines:
        key = h.lower().strip()[:80]
        if key not in seen:
            seen.add(key)
            unique.append(h)
    unique = unique[:30]

    prompt = f"""Recent crypto headlines ({datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}):

{chr(10).join(f'- {h}' for h in unique)}

{fear_greed}

Source counts:
- news_count_1h={len(source_buckets["news"])}
- social_count_15m={len(source_buckets["social"])}
- trending_mentions={len(source_buckets["trending"])}

Score the sentiment for BTC, ETH, SOL, and overall market:"""

    try:
        response = await llm_complete(prompt, system=SYSTEM_PROMPT, temperature=0.2, max_tokens=512)
        # Extract JSON from response
        start = response.find("{")
        end = response.rfind("}") + 1
        if start >= 0 and end > start:
            parsed = json.loads(response[start:end])
            if isinstance(parsed, dict):
                news_count = len(source_buckets["news"])
                social_count = len(source_buckets["social"])
                trending_count = len(source_buckets["trending"])
                for symbol in SYMBOLS:
                    item = parsed.get(symbol)
                    if not isinstance(item, dict):
                        continue
                    item.setdefault("news_count_1h", news_count)
                    item.setdefault("social_count_15m", social_count)
                    item.setdefault("trending_mentions", trending_count)
                market = parsed.get("market")
                if isinstance(market, dict):
                    market.setdefault("news_count_1h", news_count)
                    market.setdefault("social_count_15m", social_count)
                    market.setdefault("trending_mentions", trending_count)
            return parsed
        logger.warning("sentiment_parse_failed response=%s", response[:200])
        return {}
    except Exception as e:
        logger.error("sentiment_llm_error: %s", e)
        return {}


async def publish_sentiment(scores: dict):
    """Publish sentiment scores to Redis."""
    r = redis.from_url(REDIS_URL)
    try:
        ts = time.time()
        ts_ms = int(ts * 1000)
        sentiment_max_age_ms = int(os.getenv("SENTIMENT_MAX_AGE_MS", "30000"))
        for symbol in SYMBOLS:
            data = scores.get(symbol, {})
            if not data:
                continue
            trading_symbol = SYMBOL_MAP.get(symbol, symbol)
            news_sentiment = float(data.get("news_sentiment", data.get("combined_sentiment", data.get("score", 0.0)) or 0.0))
            social_sentiment = float(data.get("social_sentiment", data.get("combined_sentiment", data.get("score", 0.0)) or 0.0))
            combined_sentiment = float(data.get("combined_sentiment", data.get("score", 0.0)) or 0.0)
            news_count = int(data.get("news_count_1h", data.get("news_count", 0)) or 0)
            social_count = int(data.get("social_count_15m", data.get("social_count", 0)) or 0)
            source_quality = float(data.get("source_quality", 0.0) or 0.0)
            top_topics = [str(item) for item in (data.get("top_topics") or []) if str(item).strip()]
            event_flags = [str(item) for item in (data.get("event_flags") or []) if str(item).strip()]
            payload = {
                "symbol": trading_symbol,
                "score": combined_sentiment,
                "summary": data.get("summary", ""),
                "timestamp": ts,
                "timestamp_ms": ts_ms,
                "source": "ai_sentiment",
                "sentiment": {
                    "news_sentiment": news_sentiment,
                    "social_sentiment": social_sentiment,
                    "combined_sentiment": combined_sentiment,
                    "news_count_1h": news_count,
                    "social_count_15m": social_count,
                    "source_quality": source_quality,
                    "top_topics": top_topics,
                    "event_flags": event_flags,
                    "summary": data.get("summary", ""),
                    "asof_ts_ms": ts_ms,
                    "age_ms": 0,
                    "is_stale": False,
                },
                "events": {
                    "has_macro_event": "macro_week" in event_flags or "macro" in top_topics,
                    "has_symbol_catalyst": bool(event_flags),
                    "exchange_risk_flag": False,
                    "narrative_bias": float(data.get("narrative_bias", combined_sentiment) or 0.0),
                    "event_flags": event_flags,
                    "asof_ts_ms": ts_ms,
                    "age_ms": 0,
                },
                "quality": {
                    "fast_features_ready": False,
                    "slow_features_ready": True,
                    "feature_completeness": 1.0 if source_quality > 0 else 0.0,
                    "sentiment_fresh": True,
                    "market_data_stale": False,
                    "reasons": [],
                },
                "valid_for_ms": sentiment_max_age_ms,
            }
            await r.set(SENTIMENT_KEY.format(symbol=trading_symbol), json.dumps(payload), ex=600)
            logger.info("sentiment_published symbol=%s score=%.2f summary=%s", trading_symbol, payload["score"], payload["summary"][:60])

        # Global market sentiment
        market = scores.get("market", {})
        if market:
            await r.set(SENTIMENT_GLOBAL_KEY, json.dumps({
                "score": market.get("combined_sentiment", market.get("score", 0)),
                "summary": market.get("summary", ""),
                "timestamp": ts,
                "timestamp_ms": ts_ms,
                "sentiment": {
                    "combined_sentiment": float(market.get("combined_sentiment", market.get("score", 0)) or 0.0),
                    "top_topics": [str(item) for item in (market.get("top_topics") or []) if str(item).strip()],
                    "event_flags": [str(item) for item in (market.get("event_flags") or []) if str(item).strip()],
                    "source_quality": float(market.get("source_quality", 0.0) or 0.0),
                    "summary": market.get("summary", ""),
                    "asof_ts_ms": ts_ms,
                    "age_ms": 0,
                    "is_stale": False,
                },
                "events": {
                    "has_macro_event": bool(market.get("event_flags")),
                    "has_symbol_catalyst": False,
                    "exchange_risk_flag": False,
                    "narrative_bias": float(market.get("risk_tone", market.get("combined_sentiment", 0.0)) or 0.0),
                    "event_flags": [str(item) for item in (market.get("event_flags") or []) if str(item).strip()],
                    "asof_ts_ms": ts_ms,
                    "age_ms": 0,
                },
            }), ex=600)
            logger.info("sentiment_global score=%.2f", market.get("combined_sentiment", market.get("score", 0)))
    finally:
        await r.aclose()


async def run_loop():
    """Run sentiment scoring in a loop."""
    logger.info("sentiment_signal_started poll_interval=%ds", POLL_INTERVAL)
    while True:
        try:
            scores = await score_sentiment()
            if scores:
                await publish_sentiment(scores)
        except Exception as e:
            logger.error("sentiment_loop_error: %s", e)
        await asyncio.sleep(POLL_INTERVAL)


async def run_once():
    """Single sentiment score — for testing."""
    scores = await score_sentiment()
    if scores:
        await publish_sentiment(scores)
        print(json.dumps(scores, indent=2))
    else:
        print("No scores generated")


if __name__ == "__main__":
    mode = os.getenv("SENTIMENT_MODE", "loop")
    if mode == "once":
        asyncio.run(run_once())
    else:
        asyncio.run(run_loop())
