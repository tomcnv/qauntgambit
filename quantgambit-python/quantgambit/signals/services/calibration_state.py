"""
Calibration State Machine - Handles cold-start trading safely.

This module implements a calibration state machine that allows trading
on day 0 without "blind" trading, using Bayesian priors and shrinkage
instead of hard rejection.

States:
- COLD: Insufficient samples (< 30 trades); use conservative priors, size down
- WARMING: Some samples (30-200 trades); blend priors with empirical
- OK: Enough samples (>= 200 trades); use calibrated values

Key principles:
1. Never treat "no data" as "max penalty" - that creates a deadlock
2. Use Bayesian priors + shrinkage for p_hat rather than penalizing EV threshold
3. Size down + tighter eligibility instead of rejecting
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Optional, Dict, Any

import os

logger = logging.getLogger(__name__)


class CalibrationState(Enum):
    """Calibration state machine states."""
    COLD = "cold"        # < 30 trades: use priors, size down significantly
    WARMING = "warming"  # 30-200 trades: blend priors with empirical
    OK = "ok"            # >= 200 trades: use calibrated values


# Conservative priors by strategy family
# These are intentionally lower than historical averages to be safe
STRATEGY_PRIORS: Dict[str, float] = {
    "mean_reversion": 0.48,
    "breakout": 0.45,
    "trend_pullback": 0.47,
    "low_vol_grind": 0.48,
    "default": 0.45,
}

# Live scalper strategies are not well represented by the coarse family
# names above. Keep them slightly above the generic default so fresh
# scalper symbols do not get forced into a dead-end cold start.
SCALPER_PRIOR = 0.48

# Warmup thresholds
N_COLD_THRESHOLD = 30      # Below this: COLD state
N_WARMUP_THRESHOLD = 200   # Below this: WARMING state


@dataclass
class CalibrationStatus:
    """Result of calibration status evaluation."""
    state: CalibrationState
    n_trades: int
    reliability: float
    
    # Effective probability after shrinkage
    p_effective: float
    p_prior: float
    p_observed: Optional[float]
    shrinkage_weight: float  # 0 = all prior, 1 = all observed
    
    # Size and cost adjustments for cold-start safety
    size_multiplier: float
    max_cost_bps_adjustment: float  # Additional bps to subtract from expected edge
    min_edge_bps_adjustment: float  # Additional bps required
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for logging/telemetry."""
        return {
            "state": self.state.value,
            "n_trades": self.n_trades,
            "reliability": round(self.reliability, 3),
            "p_effective": round(self.p_effective, 4),
            "p_prior": round(self.p_prior, 4),
            "p_observed": round(self.p_observed, 4) if self.p_observed else None,
            "shrinkage_weight": round(self.shrinkage_weight, 3),
            "size_multiplier": round(self.size_multiplier, 2),
            "max_cost_bps_adjustment": round(self.max_cost_bps_adjustment, 1),
            "min_edge_bps_adjustment": round(self.min_edge_bps_adjustment, 1),
        }


def get_calibration_state(n_trades: int, reliability: Optional[float] = None) -> CalibrationState:
    """
    Determine calibration state based on trade count and reliability.
    
    Args:
        n_trades: Number of trades for this strategy-symbol combination
        reliability: Optional reliability score (0-1) from calibration model
        
    Returns:
        CalibrationState enum value
    """
    if n_trades < N_COLD_THRESHOLD:
        return CalibrationState.COLD
    
    if n_trades < N_WARMUP_THRESHOLD:
        return CalibrationState.WARMING
    
    # Even with enough trades, if reliability is very low, stay in WARMING
    if reliability is not None and reliability < 0.4:
        return CalibrationState.WARMING
    
    return CalibrationState.OK


def get_strategy_prior(strategy_id: str) -> float:
    """
    Get conservative prior probability for a strategy family.
    
    Args:
        strategy_id: Strategy identifier (e.g., "mean_reversion_fade")
        
    Returns:
        Prior probability (conservative estimate)
    """
    strategy_lower = strategy_id.lower()

    if "scalp" in strategy_lower:
        return SCALPER_PRIOR
    
    for family, prior in STRATEGY_PRIORS.items():
        if family in strategy_lower:
            return prior
    
    return STRATEGY_PRIORS["default"]


def compute_shrinkage_weight(n_trades: int) -> float:
    """
    Compute shrinkage weight for blending prior with observed.
    
    Uses linear warmup: w = clamp(n / N_warmup, 0, 1)
    
    Args:
        n_trades: Number of trades
        
    Returns:
        Weight for observed probability (0 = all prior, 1 = all observed)
    """
    weight = min(1.0, max(0.0, n_trades / N_WARMUP_THRESHOLD))
    if n_trades < N_COLD_THRESHOLD:
        try:
            # Default to a small floor so cold-start doesn't deadlock EV gate on priors alone.
            min_weight = float(os.getenv("CALIBRATION_MIN_SHRINKAGE_WEIGHT", "0.2"))
        except ValueError:
            min_weight = 0.2
        min_weight = min(1.0, max(0.0, min_weight))
        weight = max(weight, min_weight)
    return weight


def compute_effective_probability(
    p_observed: Optional[float],
    p_prior: float,
    n_trades: int,
    shrinkage_weight: Optional[float] = None,
) -> float:
    """
    Compute effective probability using Bayesian shrinkage.
    
    Formula: p_eff = w * p_obs + (1 - w) * p_prior
    Where w = clamp(n / N_warmup, 0, 1)
    
    Args:
        p_observed: Observed/model probability (may be None if no data)
        p_prior: Prior probability for this strategy family
        n_trades: Number of trades for shrinkage weight
        
    Returns:
        Effective probability after shrinkage
    """
    if p_observed is None:
        return p_prior
    
    w = shrinkage_weight if shrinkage_weight is not None else compute_shrinkage_weight(n_trades)
    return w * p_observed + (1 - w) * p_prior


def get_cold_start_adjustments(state: CalibrationState) -> tuple[float, float, float]:
    """
    Get size and cost adjustments for cold-start safety.
    
    Instead of rejecting trades, we:
    1. Reduce size
    2. Require tighter cost/spread gates
    3. Require higher minimum edge
    
    Args:
        state: Current calibration state
        
    Returns:
        Tuple of (size_multiplier, max_cost_bps_adjustment, min_edge_bps_adjustment)
    """
    cold_min_edge_bps = float(os.getenv("CALIBRATION_COLD_MIN_EDGE_BPS", "4.0"))
    warm_min_edge_bps = float(os.getenv("CALIBRATION_WARM_MIN_EDGE_BPS", "2.0"))
    if state == CalibrationState.COLD:
        # Very conservative: 25% size, +3 bps cost buffer, configurable min edge
        return (0.25, 3.0, cold_min_edge_bps)
    
    elif state == CalibrationState.WARMING:
        # Moderate: 50% size, +1.5 bps cost buffer, configurable min edge
        return (0.50, 1.5, warm_min_edge_bps)
    
    else:  # OK
        # Normal: 100% size, no adjustments
        return (1.0, 0.0, 0.0)


def evaluate_calibration(
    strategy_id: str,
    n_trades: int,
    p_observed: Optional[float] = None,
    reliability: Optional[float] = None,
) -> CalibrationStatus:
    """
    Evaluate calibration status and compute effective probability.
    
    This is the main entry point for the calibration state machine.
    
    Args:
        strategy_id: Strategy identifier
        n_trades: Number of trades for this strategy-symbol
        p_observed: Observed/model probability (may be None)
        reliability: Reliability score from calibration model (0-1)
        
    Returns:
        CalibrationStatus with all computed values
    """
    state = get_calibration_state(n_trades, reliability)
    p_prior = get_strategy_prior(strategy_id)
    shrinkage_weight = compute_shrinkage_weight(n_trades)
    if p_observed is None:
        shrinkage_weight = 0.0
    p_effective = compute_effective_probability(
        p_observed,
        p_prior,
        n_trades,
        shrinkage_weight=shrinkage_weight,
    )
    size_mult, cost_adj, edge_adj = get_cold_start_adjustments(state)
    
    # Use reliability if available, otherwise estimate from state
    if reliability is None:
        if state == CalibrationState.COLD:
            reliability = 0.0
        elif state == CalibrationState.WARMING:
            reliability = 0.3 + 0.4 * shrinkage_weight  # 0.3 to 0.7
        else:
            reliability = 0.8
    
    status = CalibrationStatus(
        state=state,
        n_trades=n_trades,
        reliability=reliability,
        p_effective=p_effective,
        p_prior=p_prior,
        p_observed=p_observed,
        shrinkage_weight=shrinkage_weight,
        size_multiplier=size_mult,
        max_cost_bps_adjustment=cost_adj,
        min_edge_bps_adjustment=edge_adj,
    )
    
    # Log calibration status
    logger.info(
        "calibration_status_evaluated",
        extra={
            "strategy_id": strategy_id,
            **status.to_dict(),
        },
    )
    
    return status
