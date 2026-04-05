"""
EVPositionSizerStage - Position sizing based on EV margin.

This stage replaces ConfidencePositionSizer with EV-based sizing that scales
position size based on edge (EV - EV_Min), cost environment, and calibration
reliability.

Formula: final_mult = ev_mult × cost_scale × reliability_scale
Where:
- ev_mult = clamp(min_mult, max_mult, 1.0 + k × edge)
- cost_scale = clamp(0.5, 1.0, 1.0 - alpha × C)
- reliability_scale = clamp(min_reliability_mult, 1.0, reliability_score)

Requirements: ev-position-sizer 1, 2, 3, 6
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional, TYPE_CHECKING

from quantgambit.signals.pipeline import Stage, StageContext, StageResult, signal_to_dict
from quantgambit.observability.logger import log_info, log_warning

if TYPE_CHECKING:
    from quantgambit.observability.blocked_signal_telemetry import BlockedSignalTelemetry


@dataclass
class EVPositionSizerConfig:
    """Configuration for EV-based position sizing.
    
    Attributes:
        k: Edge-to-multiplier scaling factor (default 2.0)
        min_mult: Minimum size multiplier (default 0.5)
        max_mult: Maximum size multiplier (default 1.25)
        cost_alpha: Cost environment scaling factor (default 0.5)
        min_reliability_mult: Minimum reliability multiplier (default 0.8)
        enabled: Whether EV sizing is enabled (default True)
    """
    k: float = 2.0
    min_mult: float = 0.5
    max_mult: float = 1.25
    cost_alpha: float = 0.5
    min_reliability_mult: float = 0.8
    enabled: bool = True
    
    def __post_init__(self):
        """Validate configuration parameters."""
        if self.k < 0:
            raise ValueError(f"k must be non-negative, got {self.k}")
        if self.min_mult < 0:
            raise ValueError(f"min_mult must be non-negative, got {self.min_mult}")
        if self.max_mult < self.min_mult:
            raise ValueError(f"max_mult ({self.max_mult}) must be >= min_mult ({self.min_mult})")
        if self.cost_alpha < 0:
            raise ValueError(f"cost_alpha must be non-negative, got {self.cost_alpha}")
        if not 0 <= self.min_reliability_mult <= 1:
            raise ValueError(f"min_reliability_mult must be in [0, 1], got {self.min_reliability_mult}")


@dataclass
class EVSizingResult:
    """Result of EV-based position sizing."""
    
    # Input values
    base_size: float
    edge: float  # EV - EV_Min
    EV: float
    EV_Min: float
    C: float  # Cost ratio
    reliability_score: float
    
    # Computed multipliers
    ev_mult: float
    cost_mult: float
    reliability_mult: float
    calibration_mult: float
    final_mult: float
    
    # Output
    final_size: float
    
    # Diagnostics
    limiting_cap: Optional[str] = None  # Which cap was binding


def compute_ev_multiplier(
    edge: float,
    k: float,
    min_mult: float,
    max_mult: float,
) -> tuple[float, Optional[str]]:
    """
    Compute EV-based size multiplier.
    
    Formula: mult = clamp(min_mult, max_mult, 1.0 + k × edge)
    
    Args:
        edge: EV - EV_Min (how far above threshold)
        k: Scaling factor
        min_mult: Minimum multiplier
        max_mult: Maximum multiplier
        
    Returns:
        Tuple of (multiplier, limiting_cap)
    """
    raw_mult = 1.0 + k * edge
    
    limiting_cap = None
    if raw_mult < min_mult:
        limiting_cap = "ev_min_mult"
        mult = min_mult
    elif raw_mult > max_mult:
        limiting_cap = "ev_max_mult"
        mult = max_mult
    else:
        mult = raw_mult
    
    return mult, limiting_cap


def compute_cost_scale(
    C: float,
    alpha: float,
) -> float:
    """
    Compute cost environment scaling factor.
    
    Formula: scale = clamp(0.5, 1.0, 1.0 - alpha × C)
    
    Args:
        C: Cost ratio (total_costs / stop_loss_distance)
        alpha: Scaling factor
        
    Returns:
        Cost scale multiplier (0.5 to 1.0)
    """
    raw_scale = 1.0 - alpha * C
    return max(0.5, min(1.0, raw_scale))


def compute_reliability_scale(
    reliability_score: float,
    min_reliability_mult: float,
) -> float:
    """
    Compute reliability scaling factor.
    
    Formula: scale = clamp(min_reliability_mult, 1.0, reliability_score)
    
    Args:
        reliability_score: Calibration reliability (0 to 1)
        min_reliability_mult: Minimum multiplier
        
    Returns:
        Reliability scale multiplier
    """
    return max(min_reliability_mult, min(1.0, reliability_score))


class EVPositionSizerStage(Stage):
    """
    Pipeline stage that sizes positions based on EV margin.
    
    Replaces ConfidencePositionSizer with EV-based sizing that considers:
    - Edge (EV - EV_Min): How much above the threshold
    - Cost environment (C): Higher costs = smaller size
    - Calibration reliability: Lower reliability = smaller size
    
    Requirements:
    - 1.1-1.7: EV-based multiplier
    - 2.1-2.5: Cost environment scaling
    - 3.1-3.5: Reliability scaling
    - 6.1-6.3: Comprehensive telemetry
    """
    name = "ev_position_sizer"
    
    def __init__(
        self,
        config: Optional[EVPositionSizerConfig] = None,
        telemetry: Optional["BlockedSignalTelemetry"] = None,
    ):
        """Initialize EVPositionSizerStage.
        
        Args:
            config: Configuration for EV sizing. Uses defaults if None.
            telemetry: Optional telemetry for recording sizing decisions.
        """
        self.config = config or EVPositionSizerConfig()
        self.telemetry = telemetry
    
    async def run(self, ctx: StageContext) -> StageResult:
        """
        Apply EV-based position sizing to the signal.
        
        Args:
            ctx: Stage context containing signal and EV gate result.
            
        Returns:
            StageResult.CONTINUE (sizing doesn't reject, only modifies size)
        """
        if not self.config.enabled:
            return StageResult.CONTINUE
        
        signal = signal_to_dict(ctx.signal)
        if not signal:
            return StageResult.CONTINUE
        
        # Skip exit signals
        side = signal.get("side", "").lower()
        if side in ("close_long", "close_short", "close"):
            return StageResult.CONTINUE
        
        # Get EV gate result from context
        ev_gate_result = ctx.data.get("ev_gate_result")
        
        # Get base size from signal
        base_size = signal.get("size") or signal.get("position_size") or 0.0
        if base_size <= 0:
            return StageResult.CONTINUE
        
        # Extract EV metrics
        if ev_gate_result:
            EV = getattr(ev_gate_result, "EV", 0.0)
            EV_Min = getattr(ev_gate_result, "ev_min_adjusted", 0.02)
            C = getattr(ev_gate_result, "C", 0.0)
            reliability_score = getattr(ev_gate_result, "calibration_reliability", 1.0)
        else:
            # Fallback: try to get from context data
            EV = ctx.data.get("EV", 0.0)
            EV_Min = ctx.data.get("ev_min", 0.02)
            C = ctx.data.get("cost_ratio", 0.0)
            reliability_score = ctx.data.get("calibration_reliability", 1.0)
        
        # Compute edge
        edge = EV - EV_Min
        
        # Compute multipliers
        ev_mult, ev_cap = compute_ev_multiplier(
            edge=edge,
            k=self.config.k,
            min_mult=self.config.min_mult,
            max_mult=self.config.max_mult,
        )
        
        cost_mult = compute_cost_scale(
            C=C,
            alpha=self.config.cost_alpha,
        )
        
        reliability_mult = compute_reliability_scale(
            reliability_score=reliability_score,
            min_reliability_mult=self.config.min_reliability_mult,
        )
        
        # Compute final multiplier
        calibration_mult = float(ctx.data.get("calibration_size_multiplier", 1.0) or 1.0)
        calibration_mult = max(0.0, min(1.0, calibration_mult))
        final_mult = ev_mult * cost_mult * reliability_mult * calibration_mult
        
        # Apply to base size
        final_size = base_size * final_mult
        
        # Determine limiting cap
        limiting_cap = ev_cap
        if cost_mult < 1.0 and (limiting_cap is None or cost_mult < ev_mult):
            limiting_cap = "cost_scale"
        if reliability_mult < 1.0 and (limiting_cap is None or reliability_mult < min(ev_mult, cost_mult)):
            limiting_cap = "reliability_scale"
        if calibration_mult < 1.0 and (
            limiting_cap is None or calibration_mult < min(ev_mult, cost_mult, reliability_mult)
        ):
            limiting_cap = "calibration_scale"
        
        # Create result for telemetry
        result = EVSizingResult(
            base_size=base_size,
            edge=edge,
            EV=EV,
            EV_Min=EV_Min,
            C=C,
            reliability_score=reliability_score,
            ev_mult=ev_mult,
            cost_mult=cost_mult,
            reliability_mult=reliability_mult,
            calibration_mult=calibration_mult,
            final_mult=final_mult,
            final_size=final_size,
            limiting_cap=limiting_cap,
        )
        
        # Update signal with new size
        if "size" in signal:
            signal["size"] = final_size
        if "position_size" in signal:
            signal["position_size"] = final_size
        
        # Store sizing result in context for downstream stages
        ctx.data["ev_sizing_result"] = result
        ctx.data["size_multiplier"] = final_mult
        
        # Log sizing decision
        self._log_sizing(ctx, result)
        
        return StageResult.CONTINUE
    
    def _log_sizing(self, ctx: StageContext, result: EVSizingResult) -> None:
        """Log sizing decision with full breakdown."""
        log_info(
            "ev_position_sizer_applied",
            symbol=ctx.symbol,
            base_size=round(result.base_size, 6),
            final_size=round(result.final_size, 6),
            ev_mult=round(result.ev_mult, 4),
            cost_mult=round(result.cost_mult, 4),
            reliability_mult=round(result.reliability_mult, 4),
            calibration_mult=round(result.calibration_mult, 4),
            final_mult=round(result.final_mult, 4),
            edge=round(result.edge, 4),
            EV=round(result.EV, 4),
            EV_Min=round(result.EV_Min, 4),
            C=round(result.C, 4),
            reliability_score=round(result.reliability_score, 4),
            limiting_cap=result.limiting_cap,
        )
