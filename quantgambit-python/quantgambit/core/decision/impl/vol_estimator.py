"""
Volatility estimator implementations.

Estimates current market volatility for position sizing.
"""

import math
from typing import Optional, List, Dict, Any

from quantgambit.core.decision.interfaces import (
    DecisionInput,
    VolOutput,
    VolatilityEstimator,
)


class SimpleVolatilityEstimator(VolatilityEstimator):
    """
    Simple volatility estimator using spread as proxy.
    
    Uses bid-ask spread as a proxy for short-term volatility.
    Wider spreads indicate higher volatility.
    """
    
    def __init__(
        self,
        vol_version_id: str = "spread_proxy:1.0.0",
        base_vol: float = 0.20,  # 20% annualized
        spread_multiplier: float = 100.0,  # How much spread affects vol
    ):
        """
        Initialize volatility estimator.
        
        Args:
            vol_version_id: Version identifier
            base_vol: Base volatility (annualized)
            spread_multiplier: How much spread adds to volatility
        """
        self._version_id = vol_version_id
        self._base_vol = base_vol
        self._spread_mult = spread_multiplier
    
    def estimate(self, decision_input: DecisionInput) -> VolOutput:
        """
        Estimate volatility from spread.
        
        Args:
            decision_input: Complete decision input
            
        Returns:
            VolOutput with volatility estimate
        """
        spread_bps = decision_input.book.spread_bps or 0.0
        
        # Convert spread to volatility component
        # spread_bps=10 -> ~1% additional vol
        spread_vol = (spread_bps / 10000) * self._spread_mult
        
        vol_hat = self._base_vol + spread_vol
        
        return VolOutput(
            vol_version_id=self._version_id,
            vol_hat=vol_hat,
            extra={
                "spread_bps": spread_bps,
                "base_vol": self._base_vol,
                "spread_vol": spread_vol,
            },
        )


class EWMAVolatilityEstimator(VolatilityEstimator):
    """
    EWMA (Exponentially Weighted Moving Average) volatility estimator.
    
    Tracks realized volatility from recent returns.
    """
    
    def __init__(
        self,
        vol_version_id: str = "ewma:1.0.0",
        decay: float = 0.94,  # EWMA decay factor (higher = more memory)
        initial_vol: float = 0.20,  # Initial volatility estimate
        annualization_factor: float = math.sqrt(365 * 24 * 60),  # Per-minute to annual
    ):
        """
        Initialize EWMA estimator.
        
        Args:
            vol_version_id: Version identifier
            decay: EWMA decay factor
            initial_vol: Initial volatility estimate
            annualization_factor: Factor to annualize volatility
        """
        self._version_id = vol_version_id
        self._decay = decay
        self._initial_vol = initial_vol
        self._annualization = annualization_factor
        
        # State per symbol
        self._variance: Dict[str, float] = {}
        self._last_price: Dict[str, float] = {}
    
    def estimate(self, decision_input: DecisionInput) -> VolOutput:
        """
        Estimate volatility using EWMA.
        
        Args:
            decision_input: Complete decision input
            
        Returns:
            VolOutput with volatility estimate
        """
        symbol = decision_input.symbol
        mid = decision_input.book.mid_price
        
        if mid is None or mid <= 0:
            return VolOutput(
                vol_version_id=self._version_id,
                vol_hat=self._initial_vol,
                extra={"warning": "no_mid_price"},
            )
        
        # Initialize if first observation
        if symbol not in self._variance:
            self._variance[symbol] = (self._initial_vol / self._annualization) ** 2
            self._last_price[symbol] = mid
            return VolOutput(
                vol_version_id=self._version_id,
                vol_hat=self._initial_vol,
                extra={"initialized": True},
            )
        
        # Compute return
        last = self._last_price[symbol]
        if last > 0:
            ret = math.log(mid / last)
        else:
            ret = 0.0
        
        # Update EWMA variance
        var = self._variance[symbol]
        var = self._decay * var + (1 - self._decay) * ret ** 2
        self._variance[symbol] = var
        self._last_price[symbol] = mid
        
        # Annualize
        vol_hat = math.sqrt(var) * self._annualization
        
        return VolOutput(
            vol_version_id=self._version_id,
            vol_hat=vol_hat,
            extra={
                "return": ret,
                "variance": var,
                "decay": self._decay,
            },
        )
    
    def reset(self, symbol: Optional[str] = None) -> None:
        """Reset state for a symbol or all symbols."""
        if symbol:
            self._variance.pop(symbol, None)
            self._last_price.pop(symbol, None)
        else:
            self._variance.clear()
            self._last_price.clear()


class ConstantVolatilityEstimator(VolatilityEstimator):
    """
    Constant volatility estimator.
    
    Returns a fixed volatility regardless of market conditions.
    Useful for testing or when vol estimation is handled elsewhere.
    """
    
    def __init__(
        self,
        vol_hat: float = 0.25,
        vol_version_id: str = "constant:1.0.0",
    ):
        """
        Initialize constant estimator.
        
        Args:
            vol_hat: Fixed volatility to return
            vol_version_id: Version identifier
        """
        self._vol_hat = vol_hat
        self._version_id = vol_version_id
    
    def estimate(self, decision_input: DecisionInput) -> VolOutput:
        """
        Return constant volatility.
        
        Args:
            decision_input: Complete decision input (ignored)
            
        Returns:
            VolOutput with fixed volatility
        """
        return VolOutput(
            vol_version_id=self._version_id,
            vol_hat=self._vol_hat,
            extra={},
        )
