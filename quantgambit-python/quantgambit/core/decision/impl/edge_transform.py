"""
Edge transform implementations.

Converts calibrated probability to edge signal with deadband.
"""

import math
from typing import Optional

from quantgambit.core.decision.interfaces import EdgeOutput, EdgeTransform


class TanhEdgeTransform(EdgeTransform):
    """
    Tanh-based edge transform with deadband.
    
    Transforms probability p_hat to signal s:
    s = tanh(k * (p_hat - 0.5))
    
    Then applies deadband: if |s| < tau, blocked.
    
    Parameters:
    - k: Steepness of the curve (higher = more decisive signals)
    - tau: Deadband threshold (minimum signal strength to trade)
    """
    
    def __init__(
        self,
        k: float = 2.5,
        tau: float = 0.15,
    ):
        """
        Initialize edge transform.
        
        Args:
            k: Curve steepness (default 2.5)
            tau: Deadband threshold (default 0.15)
        """
        self._k = k
        self._tau = tau
    
    def to_edge(self, p_hat: float) -> EdgeOutput:
        """
        Transform probability to edge signal.
        
        Args:
            p_hat: Calibrated probability [0, 1]
            
        Returns:
            EdgeOutput with signal and deadband status
        """
        # Center probability around 0.5 and scale
        x = p_hat - 0.5
        
        # Apply tanh
        s = math.tanh(self._k * x)
        
        # Check deadband
        deadband_blocked = abs(s) < self._tau
        
        return EdgeOutput(
            s=s,
            k=self._k,
            tau=self._tau,
            deadband_blocked=deadband_blocked,
        )
    
    @property
    def k(self) -> float:
        """Get curve steepness."""
        return self._k
    
    @property
    def tau(self) -> float:
        """Get deadband threshold."""
        return self._tau


class LinearEdgeTransform(EdgeTransform):
    """
    Linear edge transform with deadband.
    
    Simpler alternative to tanh:
    s = 2 * (p_hat - 0.5)
    
    Clamped to [-1, 1].
    """
    
    def __init__(
        self,
        tau: float = 0.15,
        scale: float = 2.0,
    ):
        """
        Initialize linear edge transform.
        
        Args:
            tau: Deadband threshold
            scale: Scaling factor (default 2.0 maps [0,1] to [-1,1])
        """
        self._tau = tau
        self._scale = scale
    
    def to_edge(self, p_hat: float) -> EdgeOutput:
        """
        Transform probability to edge signal linearly.
        
        Args:
            p_hat: Calibrated probability [0, 1]
            
        Returns:
            EdgeOutput with signal and deadband status
        """
        # Linear transform
        s = self._scale * (p_hat - 0.5)
        
        # Clamp to [-1, 1]
        s = max(-1.0, min(1.0, s))
        
        # Check deadband
        deadband_blocked = abs(s) < self._tau
        
        return EdgeOutput(
            s=s,
            k=self._scale,  # Using scale as k for consistency
            tau=self._tau,
            deadband_blocked=deadband_blocked,
        )


class ThresholdEdgeTransform(EdgeTransform):
    """
    Threshold-based edge transform.
    
    Discrete signals: +1, -1, or 0 (blocked).
    
    If p_hat > upper_threshold: s = +1
    If p_hat < lower_threshold: s = -1
    Else: blocked
    """
    
    def __init__(
        self,
        upper_threshold: float = 0.6,
        lower_threshold: float = 0.4,
    ):
        """
        Initialize threshold edge transform.
        
        Args:
            upper_threshold: Threshold for bullish signal
            lower_threshold: Threshold for bearish signal
        """
        self._upper = upper_threshold
        self._lower = lower_threshold
        # Compute effective tau from thresholds
        self._tau = (self._upper - self._lower) / 2
    
    def to_edge(self, p_hat: float) -> EdgeOutput:
        """
        Transform probability to discrete edge signal.
        
        Args:
            p_hat: Calibrated probability [0, 1]
            
        Returns:
            EdgeOutput with signal and deadband status
        """
        if p_hat >= self._upper:
            s = 1.0
            deadband_blocked = False
        elif p_hat <= self._lower:
            s = -1.0
            deadband_blocked = False
        else:
            s = 0.0
            deadband_blocked = True
        
        return EdgeOutput(
            s=s,
            k=1.0,  # Not applicable for threshold
            tau=self._tau,
            deadband_blocked=deadband_blocked,
        )
