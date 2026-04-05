"""
Calibrator implementations.

Calibrates raw model probabilities to meaningful probabilities.
"""

from typing import Optional, Dict, Any, List
import math

from quantgambit.core.decision.interfaces import (
    ModelOutput,
    CalibratedOutput,
    Calibrator,
)


class IdentityCalibrator(Calibrator):
    """
    Identity calibrator - passes through raw probability.
    
    Use when model is already well-calibrated or for testing.
    """
    
    def __init__(self, calibrator_version_id: str = "identity:1.0.0"):
        """
        Initialize identity calibrator.
        
        Args:
            calibrator_version_id: Version identifier
        """
        self._version_id = calibrator_version_id
    
    def calibrate(self, model_out: ModelOutput) -> CalibratedOutput:
        """
        Pass through probability unchanged.
        
        Args:
            model_out: Raw model output
            
        Returns:
            CalibratedOutput with unchanged probability
        """
        return CalibratedOutput(
            calibrator_version_id=self._version_id,
            p_hat=model_out["p_raw"],
            extra={},
        )


class PlattCalibrator(Calibrator):
    """
    Platt scaling calibrator.
    
    Applies logistic regression: p_hat = 1 / (1 + exp(A * p_raw + B))
    
    Parameters A and B are learned from validation data.
    """
    
    def __init__(
        self,
        a: float = -1.0,
        b: float = 0.0,
        calibrator_version_id: str = "platt:1.0.0",
    ):
        """
        Initialize Platt calibrator.
        
        Args:
            a: Scaling parameter A
            b: Offset parameter B
            calibrator_version_id: Version identifier
        """
        self._a = a
        self._b = b
        self._version_id = calibrator_version_id
    
    def calibrate(self, model_out: ModelOutput) -> CalibratedOutput:
        """
        Apply Platt scaling.
        
        Args:
            model_out: Raw model output
            
        Returns:
            CalibratedOutput with calibrated probability
        """
        p_raw = model_out["p_raw"]
        
        # Platt scaling
        z = self._a * p_raw + self._b
        p_hat = 1.0 / (1.0 + math.exp(-z))
        
        return CalibratedOutput(
            calibrator_version_id=self._version_id,
            p_hat=p_hat,
            extra={
                "z": z,
                "a": self._a,
                "b": self._b,
            },
        )


class IsotonicCalibrator(Calibrator):
    """
    Isotonic regression calibrator.
    
    Uses a monotonic function learned from validation data.
    Stored as a sorted list of (p_raw, p_hat) pairs.
    """
    
    def __init__(
        self,
        calibration_map: List[tuple[float, float]],
        calibrator_version_id: str = "isotonic:1.0.0",
    ):
        """
        Initialize isotonic calibrator.
        
        Args:
            calibration_map: List of (p_raw, p_hat) pairs, sorted by p_raw
            calibrator_version_id: Version identifier
        """
        self._map = sorted(calibration_map, key=lambda x: x[0])
        self._version_id = calibrator_version_id
    
    def calibrate(self, model_out: ModelOutput) -> CalibratedOutput:
        """
        Apply isotonic calibration via interpolation.
        
        Args:
            model_out: Raw model output
            
        Returns:
            CalibratedOutput with calibrated probability
        """
        p_raw = model_out["p_raw"]
        
        # Handle edge cases
        if not self._map:
            return CalibratedOutput(
                calibrator_version_id=self._version_id,
                p_hat=p_raw,
                extra={"warning": "empty_map"},
            )
        
        if p_raw <= self._map[0][0]:
            return CalibratedOutput(
                calibrator_version_id=self._version_id,
                p_hat=self._map[0][1],
                extra={"bin": 0},
            )
        
        if p_raw >= self._map[-1][0]:
            return CalibratedOutput(
                calibrator_version_id=self._version_id,
                p_hat=self._map[-1][1],
                extra={"bin": len(self._map) - 1},
            )
        
        # Linear interpolation
        for i in range(len(self._map) - 1):
            x0, y0 = self._map[i]
            x1, y1 = self._map[i + 1]
            
            if x0 <= p_raw <= x1:
                # Interpolate
                if x1 == x0:
                    p_hat = y0
                else:
                    t = (p_raw - x0) / (x1 - x0)
                    p_hat = y0 + t * (y1 - y0)
                
                return CalibratedOutput(
                    calibrator_version_id=self._version_id,
                    p_hat=p_hat,
                    extra={"bin": i, "t": t if x1 != x0 else 0},
                )
        
        # Fallback (shouldn't reach here)
        return CalibratedOutput(
            calibrator_version_id=self._version_id,
            p_hat=p_raw,
            extra={"warning": "interpolation_failed"},
        )


class BinningCalibrator(Calibrator):
    """
    Simple binning calibrator.
    
    Divides probability space into bins and maps to bin centers
    adjusted by historical accuracy.
    """
    
    def __init__(
        self,
        num_bins: int = 10,
        bin_adjustments: Optional[List[float]] = None,
        calibrator_version_id: str = "binning:1.0.0",
    ):
        """
        Initialize binning calibrator.
        
        Args:
            num_bins: Number of bins
            bin_adjustments: Adjustment factor for each bin (default: 1.0)
            calibrator_version_id: Version identifier
        """
        self._num_bins = num_bins
        self._adjustments = bin_adjustments or [1.0] * num_bins
        self._version_id = calibrator_version_id
    
    def calibrate(self, model_out: ModelOutput) -> CalibratedOutput:
        """
        Apply binning calibration.
        
        Args:
            model_out: Raw model output
            
        Returns:
            CalibratedOutput with calibrated probability
        """
        p_raw = model_out["p_raw"]
        
        # Determine bin
        bin_idx = min(int(p_raw * self._num_bins), self._num_bins - 1)
        bin_idx = max(0, bin_idx)
        
        # Apply adjustment
        adjustment = self._adjustments[bin_idx] if bin_idx < len(self._adjustments) else 1.0
        p_hat = p_raw * adjustment
        p_hat = max(0.0, min(1.0, p_hat))
        
        return CalibratedOutput(
            calibrator_version_id=self._version_id,
            p_hat=p_hat,
            extra={
                "bin": bin_idx,
                "adjustment": adjustment,
            },
        )
