"""
Trend Classifier - Classify trend bias from HTF indicators

Classifies market trend as:
- long: Bullish trend (ema_fast > ema_slow significantly)
- short: Bearish trend (ema_fast < ema_slow significantly)
- neutral: No clear trend (EMAs close together)

Returns both classification and confidence (0.0-1.0)
"""

from typing import Tuple


def classify_trend(
    ema_fast: float,
    ema_slow: float,
    price: float
) -> Tuple[str, float]:
    """
    Classify trend bias from EMA crossover
    
    Args:
        ema_fast: Fast EMA (e.g., 15-minute)
        ema_slow: Slow EMA (e.g., 15-minute)
        price: Current price
        
    Returns:
        Tuple of (trend_bias, confidence)
        - trend_bias: 'long', 'short', or 'neutral'
        - confidence: 0.0-1.0 (how strong the trend is)
    """
    # Handle missing data
    if ema_fast == 0 or ema_slow == 0 or price == 0:
        return "neutral", 0.0
    
    # Calculate EMA spread as percentage of price
    ema_spread_pct = (ema_fast - ema_slow) / price
    
    # Thresholds (tunable)
    WEAK_TREND_THRESHOLD = 0.001  # 0.1% = weak trend
    STRONG_TREND_THRESHOLD = 0.005  # 0.5% = strong trend
    
    # Classify trend
    if ema_spread_pct > WEAK_TREND_THRESHOLD:
        # Bullish trend
        trend_bias = "long"
        
        # Calculate confidence (0.0 at weak threshold, 1.0 at strong threshold)
        if ema_spread_pct >= STRONG_TREND_THRESHOLD:
            confidence = 1.0
        else:
            # Linear interpolation between weak and strong thresholds
            confidence = (ema_spread_pct - WEAK_TREND_THRESHOLD) / (STRONG_TREND_THRESHOLD - WEAK_TREND_THRESHOLD)
    
    elif ema_spread_pct < -WEAK_TREND_THRESHOLD:
        # Bearish trend
        trend_bias = "short"
        
        # Calculate confidence
        if ema_spread_pct <= -STRONG_TREND_THRESHOLD:
            confidence = 1.0
        else:
            # Linear interpolation
            confidence = (abs(ema_spread_pct) - WEAK_TREND_THRESHOLD) / (STRONG_TREND_THRESHOLD - WEAK_TREND_THRESHOLD)
    
    else:
        # No clear trend
        trend_bias = "neutral"
        
        # Confidence is inverse of how close we are to threshold
        # 0.0 at threshold, 1.0 at zero spread
        confidence = 1.0 - (abs(ema_spread_pct) / WEAK_TREND_THRESHOLD)
    
    # Clamp confidence to [0.0, 1.0]
    confidence = max(0.0, min(1.0, confidence))
    
    return trend_bias, confidence


def get_trend_strength(ema_spread_pct: float) -> str:
    """
    Get human-readable trend strength
    
    Args:
        ema_spread_pct: EMA spread as percentage of price
        
    Returns:
        Trend strength: 'very_weak', 'weak', 'moderate', 'strong', 'very_strong'
    """
    abs_spread = abs(ema_spread_pct)
    
    if abs_spread < 0.0005:
        return "very_weak"
    elif abs_spread < 0.001:
        return "weak"
    elif abs_spread < 0.003:
        return "moderate"
    elif abs_spread < 0.005:
        return "strong"
    else:
        return "very_strong"























