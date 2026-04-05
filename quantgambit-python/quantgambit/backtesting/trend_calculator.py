"""TrendCalculator - Calculates market trend from historical data.

This module provides trend calculation utilities for backtesting when the stored
trend_direction in historical data is unreliable (e.g., always "flat").

The calculator uses:
1. EMA relationship (fast vs slow) as primary method
2. Price action fallback when EMAs are inconclusive
3. Safe defaults when insufficient data

Requirements: 2.1, 2.2, 2.5
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)


@dataclass
class TrendResult:
    """Result of trend calculation.
    
    Attributes:
        direction: Trend direction - "up", "down", or "flat"
        strength: Trend strength from 0.0 to 1.0
        method: Method used for calculation - "ema", "price_action", or "default"
        ema_fast: Calculated fast EMA value (if available)
        ema_slow: Calculated slow EMA value (if available)
    """
    direction: str  # "up", "down", "flat"
    strength: float  # 0.0 to 1.0
    method: str  # "ema", "price_action", "default"
    ema_fast: Optional[float] = None
    ema_slow: Optional[float] = None


class TrendCalculator:
    """Calculates trend from historical candle data.
    
    Uses EMA relationships as the primary method for trend detection,
    with price action as a fallback when EMAs are inconclusive.
    
    Requirements:
    - 2.1: Calculate trend_direction from EMA relationships if not present
    - 2.2: Recalculate trend from price action if "flat" but price moved >2%
    - 2.5: Classify trend as "up", "down", or "flat" based on EMA relationships
    """
    
    def __init__(
        self,
        ema_fast_period: int = 8,
        ema_slow_period: int = 21,
        ema_threshold_pct: float = 0.001,  # 0.1% difference for trend classification
        price_move_threshold_pct: float = 0.02,  # 2% price move for fallback
    ):
        """Initialize TrendCalculator.
        
        Args:
            ema_fast_period: Period for fast EMA (default 8)
            ema_slow_period: Period for slow EMA (default 21)
            ema_threshold_pct: Minimum EMA difference for trend (default 0.1%)
            price_move_threshold_pct: Price move threshold for fallback (default 2%)
        """
        self.ema_fast_period = ema_fast_period
        self.ema_slow_period = ema_slow_period
        self.ema_threshold_pct = ema_threshold_pct
        self.price_move_threshold_pct = price_move_threshold_pct
    
    def calculate_from_candles(
        self,
        candles: List[Dict[str, Any]],
        lookback: int = 50,
    ) -> TrendResult:
        """Calculate trend from candle history.
        
        Priority:
        1. EMA relationship (fast vs slow)
        2. Price action (if EMAs inconclusive but price moved significantly)
        3. Default to "flat" if insufficient data
        
        Args:
            candles: List of candle dicts with 'close' field
            lookback: Number of candles to use for calculation
            
        Returns:
            TrendResult with direction, strength, and method
        """
        if not candles or len(candles) < self.ema_slow_period:
            logger.debug(
                f"TrendCalculator: Insufficient data ({len(candles) if candles else 0} candles), "
                f"need at least {self.ema_slow_period}"
            )
            return TrendResult("flat", 0.0, "default")
        
        # Get closes from recent candles
        recent_candles = candles[-lookback:] if len(candles) > lookback else candles
        closes = self._extract_closes(recent_candles)
        
        if len(closes) < self.ema_slow_period:
            return TrendResult("flat", 0.0, "default")
        
        # Calculate EMAs
        ema_fast = self._calculate_ema(closes, self.ema_fast_period)
        ema_slow = self._calculate_ema(closes, self.ema_slow_period)
        
        # EMA-based trend classification
        if ema_slow > 0:
            diff_pct = (ema_fast - ema_slow) / ema_slow
            
            if diff_pct > self.ema_threshold_pct:
                # Uptrend: fast EMA above slow EMA
                strength = min(1.0, abs(diff_pct) / 0.01)  # Normalize to 0-1
                logger.debug(
                    f"TrendCalculator: UP trend detected via EMA. "
                    f"diff_pct={diff_pct:.4f}, strength={strength:.2f}"
                )
                return TrendResult("up", strength, "ema", ema_fast, ema_slow)
            
            elif diff_pct < -self.ema_threshold_pct:
                # Downtrend: fast EMA below slow EMA
                strength = min(1.0, abs(diff_pct) / 0.01)
                logger.debug(
                    f"TrendCalculator: DOWN trend detected via EMA. "
                    f"diff_pct={diff_pct:.4f}, strength={strength:.2f}"
                )
                return TrendResult("down", strength, "ema", ema_fast, ema_slow)
        
        # Price action fallback (Requirement 2.2)
        if len(closes) >= 2:
            price_change_pct = (closes[-1] - closes[0]) / closes[0]
            
            if abs(price_change_pct) > self.price_move_threshold_pct:
                direction = "up" if price_change_pct > 0 else "down"
                strength = min(1.0, abs(price_change_pct) / 0.05)  # Normalize to 0-1
                logger.debug(
                    f"TrendCalculator: {direction.upper()} trend detected via price action. "
                    f"price_change_pct={price_change_pct:.4f}, strength={strength:.2f}"
                )
                return TrendResult(direction, strength, "price_action", ema_fast, ema_slow)
        
        # Default to flat
        logger.debug(
            f"TrendCalculator: FLAT trend (EMAs inconclusive, no significant price move). "
            f"ema_fast={ema_fast:.2f}, ema_slow={ema_slow:.2f}"
        )
        return TrendResult("flat", 0.0, "ema", ema_fast, ema_slow)
    
    def calculate_from_prices(
        self,
        prices: List[float],
    ) -> TrendResult:
        """Calculate trend from a list of prices.
        
        Convenience method that wraps prices in candle format.
        
        Args:
            prices: List of price values (oldest to newest)
            
        Returns:
            TrendResult with direction, strength, and method
        """
        candles = [{"close": p} for p in prices]
        return self.calculate_from_candles(candles)
    
    def calculate_from_emas(
        self,
        ema_fast: float,
        ema_slow: float,
    ) -> TrendResult:
        """Calculate trend from pre-computed EMA values.
        
        Useful when EMAs are already available in the data.
        
        Args:
            ema_fast: Fast EMA value
            ema_slow: Slow EMA value
            
        Returns:
            TrendResult with direction, strength, and method
        """
        if ema_slow <= 0:
            return TrendResult("flat", 0.0, "default", ema_fast, ema_slow)
        
        diff_pct = (ema_fast - ema_slow) / ema_slow
        
        if diff_pct > self.ema_threshold_pct:
            strength = min(1.0, abs(diff_pct) / 0.01)
            return TrendResult("up", strength, "ema", ema_fast, ema_slow)
        elif diff_pct < -self.ema_threshold_pct:
            strength = min(1.0, abs(diff_pct) / 0.01)
            return TrendResult("down", strength, "ema", ema_fast, ema_slow)
        else:
            return TrendResult("flat", 0.0, "ema", ema_fast, ema_slow)
    
    def _extract_closes(self, candles: List[Dict[str, Any]]) -> List[float]:
        """Extract close prices from candles.
        
        Handles various candle formats (dict with 'close' or 'Close').
        """
        closes = []
        for candle in candles:
            close = candle.get("close") or candle.get("Close")
            if close is not None:
                closes.append(float(close))
        return closes
    
    def _calculate_ema(self, prices: List[float], period: int) -> float:
        """Calculate Exponential Moving Average.
        
        Uses the standard EMA formula:
        EMA = Price * k + EMA_prev * (1 - k)
        where k = 2 / (period + 1)
        
        Args:
            prices: List of prices (oldest to newest)
            period: EMA period
            
        Returns:
            EMA value
        """
        if not prices or len(prices) < period:
            return 0.0
        
        # Start with SMA for first period
        sma = sum(prices[:period]) / period
        
        # Calculate EMA
        multiplier = 2.0 / (period + 1)
        ema = sma
        
        for price in prices[period:]:
            ema = (price * multiplier) + (ema * (1 - multiplier))
        
        return ema


# Singleton instance for convenience
_default_calculator: Optional[TrendCalculator] = None


def get_trend_calculator() -> TrendCalculator:
    """Get the default TrendCalculator instance."""
    global _default_calculator
    if _default_calculator is None:
        _default_calculator = TrendCalculator()
    return _default_calculator
