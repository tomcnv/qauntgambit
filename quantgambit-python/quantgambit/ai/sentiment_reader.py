"""Read sentiment scores from Redis (sync, for use in strategies)."""

from quantgambit.ai.context import get_sentiment_score, get_symbol_context


def get_sentiment(symbol: str) -> float:
    """Get sentiment score for a symbol. Returns 0.0 if unavailable."""
    return get_sentiment_score(symbol)


def get_sentiment_context(symbol: str) -> dict:
    """Get the full cached sentiment/context payload for a symbol."""
    payload = get_symbol_context(symbol)
    return payload if isinstance(payload, dict) else {}
