"""
Volatility Classifier - Classify volatility regime from ATR

Classifies market volatility as:
- high: Elevated volatility (atr_ratio > 1.3)
- normal: Average volatility (0.7 <= atr_ratio <= 1.3)
- low: Suppressed volatility (atr_ratio < 0.7)

Returns both classification and percentile (0.0-1.0)
"""

from typing import Tuple


def classify_volatility(
    atr_ratio: float,
    rotation_factor: float = 0.0
) -> Tuple[str, float]:
    """
    Classify volatility regime from ATR ratio
    
    Args:
        atr_ratio: Current ATR / baseline ATR
        rotation_factor: AMT rotation factor (optional, for confirmation)
        
    Returns:
        Tuple of (volatility_regime, volatility_percentile)
        - volatility_regime: 'high', 'normal', or 'low'
        - volatility_percentile: 0.0-1.0 (where current vol sits in historical distribution)
    """
    # Thresholds (tunable)
    LOW_VOL_THRESHOLD = 0.7  # Below this = low volatility
    HIGH_VOL_THRESHOLD = 1.3  # Above this = high volatility
    
    # Classify volatility regime
    if atr_ratio < LOW_VOL_THRESHOLD:
        volatility_regime = "low"
        
        # Calculate percentile (0.0 at very low vol, 0.3 at threshold)
        # Assume 0.3 = extremely low volatility (30% of baseline)
        if atr_ratio <= 0.3:
            volatility_percentile = 0.0
        else:
            # Linear interpolation from 0.3 to LOW_VOL_THRESHOLD
            volatility_percentile = (atr_ratio - 0.3) / (LOW_VOL_THRESHOLD - 0.3) * 0.3
    
    elif atr_ratio > HIGH_VOL_THRESHOLD:
        volatility_regime = "high"
        
        # Calculate percentile (0.7 at threshold, 1.0 at very high vol)
        # Assume 2.0 = extremely high volatility (200% of baseline)
        if atr_ratio >= 2.0:
            volatility_percentile = 1.0
        else:
            # Linear interpolation from HIGH_VOL_THRESHOLD to 2.0
            volatility_percentile = 0.7 + (atr_ratio - HIGH_VOL_THRESHOLD) / (2.0 - HIGH_VOL_THRESHOLD) * 0.3
    
    else:
        volatility_regime = "normal"
        
        # Calculate percentile (0.3 at LOW_VOL_THRESHOLD, 0.7 at HIGH_VOL_THRESHOLD)
        volatility_percentile = 0.3 + (atr_ratio - LOW_VOL_THRESHOLD) / (HIGH_VOL_THRESHOLD - LOW_VOL_THRESHOLD) * 0.4
    
    # Adjust for rotation factor (if provided)
    # High rotation = increased volatility signal
    if rotation_factor > 5.0:
        # Strong rotation suggests volatility expansion
        if volatility_regime == "normal":
            volatility_regime = "high"
        volatility_percentile = min(1.0, volatility_percentile + 0.1)
    
    # Clamp percentile to [0.0, 1.0]
    volatility_percentile = max(0.0, min(1.0, volatility_percentile))
    
    return volatility_regime, volatility_percentile


def get_volatility_multiplier(volatility_regime: str) -> float:
    """
    Get position sizing multiplier based on volatility regime
    
    Args:
        volatility_regime: 'high', 'normal', or 'low'
        
    Returns:
        Multiplier for position sizing (reduce size in high vol, increase in low vol)
    """
    if volatility_regime == "high":
        return 0.7  # Reduce size by 30% in high volatility
    elif volatility_regime == "low":
        return 1.3  # Increase size by 30% in low volatility
    else:
        return 1.0  # Normal size


def get_stop_multiplier(volatility_regime: str) -> float:
    """
    Get stop-loss multiplier based on volatility regime
    
    Args:
        volatility_regime: 'high', 'normal', or 'low'
        
    Returns:
        Multiplier for stop-loss distance (wider stops in high vol, tighter in low vol)
    """
    if volatility_regime == "high":
        return 1.5  # 50% wider stops in high volatility
    elif volatility_regime == "low":
        return 0.7  # 30% tighter stops in low volatility
    else:
        return 1.0  # Normal stops























