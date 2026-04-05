"""
Layer 1: Predictions (Market Context)

Unified market prediction layer that consolidates all market analysis into a single MarketContext.

Components:
- MarketContext: Unified dataclass with all predictions
- Trend Classifier: Classify trend bias (long/short/neutral)
- Volatility Classifier: Classify volatility regime (high/normal/low)
- Liquidity Classifier: Classify liquidity (deep/normal/thin)
- Regime Classifier: Classify market regime (range/breakout/squeeze/chop)
- Orderflow Predictor: ML-based orderflow prediction (from Layer 0)
"""

from .market_context import MarketContext, build_market_context
from .trend_classifier import classify_trend
from .volatility_classifier import classify_volatility
from .liquidity_classifier import classify_liquidity
from .regime_classifier import classify_regime

__all__ = [
    'MarketContext',
    'build_market_context',
    'classify_trend',
    'classify_volatility',
    'classify_liquidity',
    'classify_regime',
]























