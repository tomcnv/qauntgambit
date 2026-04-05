"""
CalibrationOutput and CalibrationGate for per-symbol threshold gating.

This module provides:
- CalibrationOutput: Data class capturing calibration thresholds and gating results
- CalibrationGate: Component that gates entries based on calibrated spread/depth thresholds

The calibration gate is placed early in the decision pipeline to avoid wasted
computation when market conditions are unfavorable for a specific symbol.
"""

from dataclasses import dataclass
from typing import Any, Dict, Optional

from quantgambit.risk.symbol_calibrator import SymbolCalibrator, SymbolThresholds


@dataclass
class CalibrationOutput:
    """
    Output from calibration gating step.
    
    Contains:
    - Calibrated thresholds (spread and depth)
    - Current market values
    - Gating decisions (blocked/warn)
    - Size adjustment factor
    - Calibration quality metrics
    """
    
    # Spread thresholds (basis points)
    spread_block_bps: float
    spread_warn_bps: float
    spread_typical_bps: float
    
    # Depth thresholds (USD)
    depth_block_usd: float
    depth_warn_usd: float
    depth_typical_usd: float
    
    # Current values
    spread_current_bps: float
    depth_current_usd: float
    
    # Gating results
    spread_blocked: bool
    spread_warn: bool
    depth_blocked: bool
    depth_warn: bool
    
    # Risk adjustment
    size_multiplier: float  # 1.0, 0.5, or 0.25
    adjustment_reason: Optional[str]
    
    # Calibration quality
    calibration_quality: str  # "good", "fair", "poor"
    sample_count: int
    using_fallback: bool
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary for event payloads."""
        return {
            "spread_block_bps": round(self.spread_block_bps, 2),
            "spread_warn_bps": round(self.spread_warn_bps, 2),
            "spread_typical_bps": round(self.spread_typical_bps, 2),
            "depth_block_usd": round(self.depth_block_usd, 0),
            "depth_warn_usd": round(self.depth_warn_usd, 0),
            "depth_typical_usd": round(self.depth_typical_usd, 0),
            "spread_current_bps": round(self.spread_current_bps, 2),
            "depth_current_usd": round(self.depth_current_usd, 0),
            "spread_blocked": self.spread_blocked,
            "spread_warn": self.spread_warn,
            "depth_blocked": self.depth_blocked,
            "depth_warn": self.depth_warn,
            "size_multiplier": round(self.size_multiplier, 4),
            "adjustment_reason": self.adjustment_reason,
            "calibration_quality": self.calibration_quality,
            "sample_count": self.sample_count,
            "using_fallback": self.using_fallback,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CalibrationOutput":
        """Deserialize from dictionary."""
        return cls(
            spread_block_bps=data["spread_block_bps"],
            spread_warn_bps=data["spread_warn_bps"],
            spread_typical_bps=data["spread_typical_bps"],
            depth_block_usd=data["depth_block_usd"],
            depth_warn_usd=data["depth_warn_usd"],
            depth_typical_usd=data["depth_typical_usd"],
            spread_current_bps=data["spread_current_bps"],
            depth_current_usd=data["depth_current_usd"],
            spread_blocked=data["spread_blocked"],
            spread_warn=data["spread_warn"],
            depth_blocked=data["depth_blocked"],
            depth_warn=data["depth_warn"],
            size_multiplier=data["size_multiplier"],
            adjustment_reason=data.get("adjustment_reason"),
            calibration_quality=data["calibration_quality"],
            sample_count=data["sample_count"],
            using_fallback=data["using_fallback"],
        )
    
    def is_blocked(self) -> bool:
        """Check if entry should be blocked."""
        return self.spread_blocked or self.depth_blocked
    
    def is_degraded(self) -> bool:
        """Check if conditions are degraded (warn zone)."""
        return self.spread_warn or self.depth_warn


class CalibrationGate:
    """
    Gates entries based on calibrated spread/depth thresholds.
    
    Placed early in the pipeline to avoid wasted computation
    when market conditions are unfavorable.
    
    Usage:
        gate = CalibrationGate(calibrator)
        output = gate.check(symbol, spread_bps, bid_depth, ask_depth)
        
        if output.spread_blocked:
            # Block entry - spread too wide
        elif output.depth_blocked:
            # Block entry - depth too thin
        else:
            # Continue with size_multiplier applied
    """
    
    def __init__(
        self,
        calibrator: SymbolCalibrator,
        warn_size_multiplier: float = 0.5,
    ):
        """
        Initialize calibration gate.
        
        Args:
            calibrator: SymbolCalibrator instance for threshold lookup
            warn_size_multiplier: Size multiplier for warn zone (default 0.5)
        """
        self._calibrator = calibrator
        self._warn_multiplier = warn_size_multiplier
    
    def check(
        self,
        symbol: str,
        spread_bps: float,
        bid_depth_usd: float,
        ask_depth_usd: float,
    ) -> CalibrationOutput:
        """
        Check if entry should be gated based on calibrated thresholds.
        
        Args:
            symbol: Trading symbol
            spread_bps: Current spread in basis points
            bid_depth_usd: Bid side depth in USD
            ask_depth_usd: Ask side depth in USD
            
        Returns:
            CalibrationOutput with gating decision and size adjustment
        """
        # Get calibrated thresholds
        thresholds = self._calibrator.get_thresholds(symbol)
        
        # Current depth is minimum of bid/ask
        depth_current = min(bid_depth_usd, ask_depth_usd)
        
        # Check spread against thresholds
        spread_blocked = spread_bps > thresholds.spread_block_bps
        spread_warn = (
            spread_bps > thresholds.spread_warn_bps 
            and not spread_blocked
        )
        
        # Check depth against thresholds
        depth_blocked = depth_current < thresholds.depth_block_usd
        depth_warn = (
            depth_current < thresholds.depth_warn_usd 
            and not depth_blocked
        )
        
        # Compute size multiplier (multiplicative for multiple warn conditions)
        size_multiplier = 1.0
        reasons = []
        
        if spread_warn:
            size_multiplier *= self._warn_multiplier
            reasons.append("spread_warn")
        
        if depth_warn:
            size_multiplier *= self._warn_multiplier
            reasons.append("depth_warn")
        
        return CalibrationOutput(
            spread_block_bps=thresholds.spread_block_bps,
            spread_warn_bps=thresholds.spread_warn_bps,
            spread_typical_bps=thresholds.spread_typical_bps,
            depth_block_usd=thresholds.depth_block_usd,
            depth_warn_usd=thresholds.depth_warn_usd,
            depth_typical_usd=thresholds.depth_typical_usd,
            spread_current_bps=spread_bps,
            depth_current_usd=depth_current,
            spread_blocked=spread_blocked,
            spread_warn=spread_warn,
            depth_blocked=depth_blocked,
            depth_warn=depth_warn,
            size_multiplier=size_multiplier,
            adjustment_reason=", ".join(reasons) if reasons else None,
            calibration_quality=thresholds.calibration_quality,
            sample_count=thresholds.sample_count,
            using_fallback=thresholds.calibration_quality == "poor",
        )
