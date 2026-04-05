"""
Risk mapper implementations.

Maps edge signals and volatility to position sizing.
"""

import math
from typing import Optional

from quantgambit.core.decision.interfaces import (
    DecisionInput,
    RiskOutput,
    RiskMapper,
)


class VolTargetRiskMapper(RiskMapper):
    """
    Volatility-targeting risk mapper.
    
    Sizes positions to achieve a target volatility contribution.
    Uses Kelly-inspired fractional sizing with volatility scaling.
    """
    
    def __init__(
        self,
        risk_profile_version_id: str = "vol_target:1.0.0",
        w_max: float = 0.10,  # Maximum position weight
        target_vol: float = 0.02,  # Target portfolio volatility
        min_delta_w: float = 0.005,  # Churn guard threshold
        kelly_fraction: float = 0.25,  # Fraction of Kelly (quarter Kelly)
    ):
        """
        Initialize risk mapper.
        
        Args:
            risk_profile_version_id: Version identifier
            w_max: Maximum absolute position weight
            target_vol: Target portfolio volatility contribution
            min_delta_w: Minimum weight change to trade (churn guard)
            kelly_fraction: Fraction of Kelly criterion to use
        """
        self._version_id = risk_profile_version_id
        self._w_max = w_max
        self._target_vol = target_vol
        self._min_delta_w = min_delta_w
        self._kelly_frac = kelly_fraction
    
    def map(
        self,
        *,
        s: float,
        vol_hat: float,
        decision_input: DecisionInput,
    ) -> RiskOutput:
        """
        Map edge and volatility to position weight.
        
        Args:
            s: Edge signal in [-1, +1]
            vol_hat: Volatility estimate (annualized)
            decision_input: Complete decision input
            
        Returns:
            RiskOutput with position sizing
        """
        # Get current position weight
        w_current = self._compute_current_weight(decision_input)
        
        # Compute target weight from signal and vol
        w_raw = self._compute_raw_weight(s, vol_hat)
        
        # Clip to max
        clipped = abs(w_raw) >= self._w_max
        w_target = max(min(w_raw, self._w_max), -self._w_max)
        
        # Compute delta
        delta_w = w_target - w_current
        
        # Apply churn guard
        churn_guard_blocked = abs(delta_w) < self._min_delta_w
        if churn_guard_blocked:
            # Don't trade, keep current
            w_target = w_current
            delta_w = 0.0
        
        return RiskOutput(
            risk_profile_version_id=self._version_id,
            w_current=w_current,
            w_target=w_target,
            delta_w=delta_w,
            clipped=clipped,
            churn_guard_blocked=churn_guard_blocked,
            extra={
                "w_raw": w_raw,
                "vol_hat": vol_hat,
                "kelly_frac": self._kelly_frac,
                "target_vol": self._target_vol,
            },
        )
    
    def _compute_current_weight(self, decision_input: DecisionInput) -> float:
        """Compute current position weight."""
        if not decision_input.current_position:
            return 0.0
        
        pos = decision_input.current_position
        mid = decision_input.book.mid_price
        equity = decision_input.account_equity
        
        if not mid or mid <= 0 or equity <= 0:
            return 0.0
        
        # Position value as fraction of equity
        pos_value = pos.size * mid
        return pos_value / equity
    
    def _compute_raw_weight(self, s: float, vol_hat: float) -> float:
        """
        Compute raw target weight from signal and volatility.
        
        Uses volatility-targeting:
        w = (target_vol / asset_vol) * signal * kelly_fraction
        """
        if vol_hat <= 0:
            return 0.0
        
        # Scale by target vol / asset vol
        vol_scalar = self._target_vol / vol_hat
        
        # Apply Kelly fraction and signal
        w_raw = vol_scalar * s * self._kelly_frac
        
        return w_raw


class FixedSizeRiskMapper(RiskMapper):
    """
    Fixed size risk mapper.
    
    Uses a fixed position size based on signal direction only.
    """
    
    def __init__(
        self,
        risk_profile_version_id: str = "fixed:1.0.0",
        fixed_weight: float = 0.05,  # Fixed weight when signaled
        min_delta_w: float = 0.01,
    ):
        """
        Initialize fixed size mapper.
        
        Args:
            risk_profile_version_id: Version identifier
            fixed_weight: Fixed position weight when signal present
            min_delta_w: Churn guard threshold
        """
        self._version_id = risk_profile_version_id
        self._fixed_w = fixed_weight
        self._min_delta_w = min_delta_w
    
    def map(
        self,
        *,
        s: float,
        vol_hat: float,
        decision_input: DecisionInput,
    ) -> RiskOutput:
        """
        Map signal to fixed position weight.
        
        Args:
            s: Edge signal in [-1, +1]
            vol_hat: Volatility estimate (ignored)
            decision_input: Complete decision input
            
        Returns:
            RiskOutput with position sizing
        """
        # Get current position weight
        w_current = self._compute_current_weight(decision_input)
        
        # Target: fixed weight in signal direction, 0 if no signal
        if abs(s) > 0.01:  # Some signal threshold
            w_target = self._fixed_w if s > 0 else -self._fixed_w
        else:
            w_target = 0.0
        
        delta_w = w_target - w_current
        
        # Churn guard
        churn_guard_blocked = abs(delta_w) < self._min_delta_w
        if churn_guard_blocked:
            w_target = w_current
            delta_w = 0.0
        
        return RiskOutput(
            risk_profile_version_id=self._version_id,
            w_current=w_current,
            w_target=w_target,
            delta_w=delta_w,
            clipped=False,
            churn_guard_blocked=churn_guard_blocked,
            extra={
                "fixed_weight": self._fixed_w,
                "signal": s,
            },
        )
    
    def _compute_current_weight(self, decision_input: DecisionInput) -> float:
        """Compute current position weight."""
        if not decision_input.current_position:
            return 0.0
        
        pos = decision_input.current_position
        mid = decision_input.book.mid_price
        equity = decision_input.account_equity
        
        if not mid or mid <= 0 or equity <= 0:
            return 0.0
        
        pos_value = pos.size * mid
        return pos_value / equity


class ScaledSignalRiskMapper(RiskMapper):
    """
    Scaled signal risk mapper.
    
    Scales position size proportionally to signal strength.
    """
    
    def __init__(
        self,
        risk_profile_version_id: str = "scaled:1.0.0",
        max_weight: float = 0.10,
        min_delta_w: float = 0.005,
    ):
        """
        Initialize scaled mapper.
        
        Args:
            risk_profile_version_id: Version identifier
            max_weight: Maximum position weight at |s|=1
            min_delta_w: Churn guard threshold
        """
        self._version_id = risk_profile_version_id
        self._max_w = max_weight
        self._min_delta_w = min_delta_w
    
    def map(
        self,
        *,
        s: float,
        vol_hat: float,
        decision_input: DecisionInput,
    ) -> RiskOutput:
        """
        Map signal to scaled position weight.
        
        Args:
            s: Edge signal in [-1, +1]
            vol_hat: Volatility estimate (ignored)
            decision_input: Complete decision input
            
        Returns:
            RiskOutput with position sizing
        """
        w_current = self._compute_current_weight(decision_input)
        
        # Linear scaling: w_target = s * max_weight
        w_target = s * self._max_w
        clipped = abs(s) >= 1.0
        
        delta_w = w_target - w_current
        
        churn_guard_blocked = abs(delta_w) < self._min_delta_w
        if churn_guard_blocked:
            w_target = w_current
            delta_w = 0.0
        
        return RiskOutput(
            risk_profile_version_id=self._version_id,
            w_current=w_current,
            w_target=w_target,
            delta_w=delta_w,
            clipped=clipped,
            churn_guard_blocked=churn_guard_blocked,
            extra={
                "max_weight": self._max_w,
                "signal": s,
            },
        )
    
    def _compute_current_weight(self, decision_input: DecisionInput) -> float:
        """Compute current position weight."""
        if not decision_input.current_position:
            return 0.0
        
        pos = decision_input.current_position
        mid = decision_input.book.mid_price
        equity = decision_input.account_equity
        
        if not mid or mid <= 0 or equity <= 0:
            return 0.0
        
        pos_value = pos.size * mid
        return pos_value / equity
