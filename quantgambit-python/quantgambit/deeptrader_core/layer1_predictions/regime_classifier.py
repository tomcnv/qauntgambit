"""
Regime Classifier - Classify market regime from multiple indicators

Classifies market regime as:
- range: Range-bound market (low rotation, low trend, normal vol)
- breakout: Breakout in progress (high rotation, strong trend, expanding vol)
- squeeze: Volatility squeeze (low vol, building pressure)
- chop: Choppy/whipsaw market (high rotation, no trend, high vol)

Returns both classification and confidence (0.0-1.0)
"""

from typing import Tuple


def classify_regime(
    rotation_factor: float,
    atr_ratio: float,
    trend_strength: float,
    spread_bps: float
) -> Tuple[str, float]:
    """
    Classify market regime from multiple indicators
    
    Args:
        rotation_factor: AMT rotation factor (momentum)
        atr_ratio: Current ATR / baseline ATR (volatility)
        trend_strength: Absolute EMA spread (trend)
        spread_bps: Bid-ask spread in basis points (liquidity)
        
    Returns:
        Tuple of (market_regime, confidence)
        - market_regime: 'range', 'breakout', 'squeeze', or 'chop'
        - confidence: 0.0-1.0 (how clear the regime is)
    """
    # Thresholds (tunable)
    HIGH_ROTATION = 3.0  # Strong momentum
    LOW_ROTATION = 1.0   # Weak momentum
    
    HIGH_VOL = 1.3  # Elevated volatility
    LOW_VOL = 0.7   # Suppressed volatility
    
    STRONG_TREND = 0.003  # 0.3% EMA spread
    WEAK_TREND = 0.001    # 0.1% EMA spread
    
    # Classify regime based on combination of factors
    
    # BREAKOUT: High rotation + strong trend + expanding volatility
    if rotation_factor > HIGH_ROTATION and trend_strength > STRONG_TREND and atr_ratio > 1.0:
        market_regime = "breakout"
        
        # Confidence based on how extreme the values are
        rotation_confidence = min(1.0, (rotation_factor - HIGH_ROTATION) / HIGH_ROTATION)
        trend_confidence = min(1.0, (trend_strength - STRONG_TREND) / STRONG_TREND)
        vol_confidence = min(1.0, (atr_ratio - 1.0) / (HIGH_VOL - 1.0))
        
        confidence = (rotation_confidence + trend_confidence + vol_confidence) / 3
    
    # SQUEEZE: Low volatility + building pressure (moderate rotation)
    elif atr_ratio < LOW_VOL and rotation_factor > LOW_ROTATION:
        market_regime = "squeeze"
        
        # Confidence based on how compressed volatility is
        vol_compression = (LOW_VOL - atr_ratio) / LOW_VOL
        rotation_build = min(1.0, (rotation_factor - LOW_ROTATION) / (HIGH_ROTATION - LOW_ROTATION))
        
        confidence = (vol_compression + rotation_build) / 2
    
    # CHOP: High rotation + no trend + elevated volatility
    elif rotation_factor > HIGH_ROTATION and trend_strength < WEAK_TREND and atr_ratio > HIGH_VOL:
        market_regime = "chop"
        
        # Confidence based on rotation and lack of trend
        rotation_confidence = min(1.0, (rotation_factor - HIGH_ROTATION) / HIGH_ROTATION)
        no_trend_confidence = 1.0 - (trend_strength / WEAK_TREND)
        vol_confidence = min(1.0, (atr_ratio - HIGH_VOL) / (2.0 - HIGH_VOL))
        
        confidence = (rotation_confidence + no_trend_confidence + vol_confidence) / 3
    
    # RANGE: Low rotation + weak trend + normal volatility
    else:
        market_regime = "range"
        
        # Confidence based on how stable conditions are
        low_rotation_confidence = 1.0 - min(1.0, rotation_factor / HIGH_ROTATION)
        weak_trend_confidence = 1.0 - min(1.0, trend_strength / STRONG_TREND)
        normal_vol_confidence = 1.0 - abs(atr_ratio - 1.0)
        
        confidence = (low_rotation_confidence + weak_trend_confidence + normal_vol_confidence) / 3
    
    # Adjust confidence based on spread (wide spread = less confident)
    if spread_bps > 10.0:
        confidence *= 0.8  # Reduce confidence by 20% in wide spreads
    
    # Clamp confidence to [0.0, 1.0]
    confidence = max(0.0, min(1.0, confidence))
    
    return market_regime, confidence


def get_regime_strategies(market_regime: str) -> list:
    """
    Get recommended strategy types for each regime
    
    Args:
        market_regime: 'range', 'breakout', 'squeeze', or 'chop'
        
    Returns:
        List of recommended strategy types
    """
    if market_regime == "range":
        return ["mean_reversion", "value_area_rejection", "poc_magnet"]
    
    elif market_regime == "breakout":
        return ["trend_continuation", "momentum_breakout", "breakout_scalp"]
    
    elif market_regime == "squeeze":
        return ["breakout_anticipation", "range_compression", "volatility_expansion"]
    
    elif market_regime == "chop":
        return ["avoid_trading", "tight_stops", "reduce_size"]
    
    else:
        return []


def should_trade_regime(market_regime: str, confidence: float) -> bool:
    """
    Determine if we should trade in this regime
    
    Args:
        market_regime: 'range', 'breakout', 'squeeze', or 'chop'
        confidence: Regime confidence (0.0-1.0)
        
    Returns:
        True if regime is tradeable, False if should avoid
    """
    # Don't trade in choppy markets
    if market_regime == "chop":
        return False
    
    # Don't trade if regime is unclear (low confidence)
    if confidence < 0.3:
        return False
    
    # All other regimes are tradeable
    return True


def get_regime_position_multiplier(market_regime: str, confidence: float) -> float:
    """
    Get position sizing multiplier based on regime
    
    Args:
        market_regime: 'range', 'breakout', 'squeeze', or 'chop'
        confidence: Regime confidence (0.0-1.0)
        
    Returns:
        Multiplier for position sizing
    """
    if market_regime == "chop":
        return 0.3  # Reduce size by 70% in choppy markets
    
    elif market_regime == "breakout" and confidence > 0.7:
        return 1.3  # Increase size by 30% in strong breakouts
    
    elif market_regime == "squeeze" and confidence > 0.7:
        return 0.7  # Reduce size by 30% in squeeze (waiting for breakout)
    
    else:
        return 1.0  # Normal size























