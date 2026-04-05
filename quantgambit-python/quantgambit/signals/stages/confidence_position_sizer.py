"""
ConfidencePositionSizer - Scales position sizes based on signal confidence.

DEPRECATED: This module is deprecated in favor of EVPositionSizerStage, which
provides EV-based position sizing that scales based on edge (EV - EV_Min),
cost environment, and calibration reliability. Use EVPositionSizerStage instead.

This module implements confidence-based position sizing that scales trade sizes
according to the model's prediction confidence. Higher confidence signals get
larger position sizes, while lower confidence signals get reduced sizes.

Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass, field
from typing import List, Tuple, Optional, TYPE_CHECKING

from quantgambit.signals.pipeline import Stage, StageContext, StageResult, signal_to_dict
from quantgambit.observability.logger import log_info, log_warning

if TYPE_CHECKING:
    from quantgambit.observability.blocked_signal_telemetry import BlockedSignalTelemetry


# =============================================================================
# CONFIDENCE_MULTIPLIERS Configuration
# Requirements: 7.2, 7.3, 7.4, 7.5
# =============================================================================

# Confidence bands and their corresponding position size multipliers
# Format: (min_confidence, max_confidence, multiplier)
# - 50-60% confidence → 0.5x position size (low confidence, reduce risk)
# - 60-75% confidence → 0.75x position size (moderate confidence)
# - 75-90% confidence → 1.0x position size (high confidence, full size)
# - 90%+ confidence → 1.25x position size (very high confidence, increase size)
CONFIDENCE_MULTIPLIERS: List[Tuple[float, float, float]] = [
    (0.50, 0.60, 0.50),   # 50-60% confidence → 0.5x size (Requirement 7.2)
    (0.60, 0.75, 0.75),   # 60-75% confidence → 0.75x size (Requirement 7.3)
    (0.75, 0.90, 1.00),   # 75-90% confidence → 1.0x size (Requirement 7.4)
    (0.90, 1.01, 1.25),   # 90%+ confidence → 1.25x size (Requirement 7.5)
]


@dataclass
class ConfidencePositionSizerConfig:
    """Configuration for ConfidencePositionSizer.
    
    Attributes:
        multipliers: List of (min_confidence, max_confidence, multiplier) tuples.
                    Defines the confidence bands and their corresponding multipliers.
        default_multiplier: Multiplier to use when confidence doesn't fall in any band.
        min_confidence_for_sizing: Minimum confidence required for sizing.
                                   Signals below this are not sized (should be rejected earlier).
    
    Requirements: 7.2, 7.3, 7.4, 7.5
    """
    multipliers: List[Tuple[float, float, float]] = field(
        default_factory=lambda: list(CONFIDENCE_MULTIPLIERS)
    )
    default_multiplier: float = 1.0
    min_confidence_for_sizing: float = 0.50  # Must pass confidence gate first
    
    def __post_init__(self):
        """Validate configuration parameters."""
        # Validate multipliers
        for min_conf, max_conf, mult in self.multipliers:
            if not 0.0 <= min_conf <= 1.0:
                raise ValueError(f"min_confidence must be between 0 and 1, got {min_conf}")
            if not 0.0 <= max_conf <= 1.01:  # Allow 1.01 for 90%+ band
                raise ValueError(f"max_confidence must be between 0 and 1.01, got {max_conf}")
            if min_conf >= max_conf:
                raise ValueError(f"min_confidence ({min_conf}) must be < max_confidence ({max_conf})")
            if mult <= 0:
                raise ValueError(f"multiplier must be positive, got {mult}")
        
        # Validate default multiplier
        if self.default_multiplier <= 0:
            raise ValueError(f"default_multiplier must be positive, got {self.default_multiplier}")
        
        # Validate min_confidence_for_sizing
        if not 0.0 <= self.min_confidence_for_sizing <= 1.0:
            raise ValueError(
                f"min_confidence_for_sizing must be between 0 and 1, got {self.min_confidence_for_sizing}"
            )



class ConfidencePositionSizer:
    """
    Scales position sizes based on signal confidence.
    
    DEPRECATED: Use EVPositionSizerStage instead. EVPositionSizerStage provides
    EV-based sizing that scales based on edge (EV - EV_Min), cost environment,
    and calibration reliability.
    
    This class implements confidence-based position sizing that adjusts trade
    sizes according to the model's prediction confidence. The sizing follows
    predefined bands:
    
    - 50-60% confidence → 0.5x position size
    - 60-75% confidence → 0.75x position size  
    - 75-90% confidence → 1.0x position size
    - 90%+ confidence → 1.25x position size
    
    Requirements:
    - 7.1: Calculate confidence multiplier for signals passing threshold
    - 7.2: 50-60% confidence → 0.5x multiplier
    - 7.3: 60-75% confidence → 0.75x multiplier
    - 7.4: 75-90% confidence → 1.0x multiplier
    - 7.5: 90%+ confidence → 1.25x multiplier
    - 7.6: Apply multiplier after base sizing, before risk limits
    - 7.7: Add confidence_multiplier and confidence to signal metadata
    """
    
    def __init__(self, config: Optional[ConfidencePositionSizerConfig] = None):
        """Initialize ConfidencePositionSizer.
        
        Args:
            config: Configuration for the sizer. Uses defaults if None.
            
        .. deprecated::
            Use EVPositionSizerStage instead for EV-based position sizing.
        """
        warnings.warn(
            "ConfidencePositionSizer is deprecated. Use EVPositionSizerStage instead "
            "for EV-based position sizing that accounts for edge, cost, and reliability.",
            DeprecationWarning,
            stacklevel=2,
        )
        self.config = config or ConfidencePositionSizerConfig()
    
    def get_multiplier(self, confidence: float) -> float:
        """
        Get the position size multiplier for a given confidence level.
        
        Args:
            confidence: Signal confidence value (0.0 to 1.0)
            
        Returns:
            Position size multiplier based on confidence band.
            
        Requirements: 7.1, 7.2, 7.3, 7.4, 7.5
        """
        # Normalize confidence to 0-1 range if provided as percentage
        if confidence > 1.0:
            confidence = confidence / 100.0
        
        # Find the matching confidence band
        for min_conf, max_conf, multiplier in self.config.multipliers:
            if min_conf <= confidence < max_conf:
                return multiplier
        
        # Return default if no band matches
        return self.config.default_multiplier
    
    def apply(self, signal: dict, confidence: float) -> dict:
        """
        Apply confidence-based sizing to a signal.
        
        Scales the signal's size fields by the confidence multiplier and
        adds metadata about the confidence and multiplier applied.
        
        Args:
            signal: Signal dict with optional 'size' and 'size_usd' fields
            confidence: Signal confidence value (0.0 to 1.0)
            
        Returns:
            Modified signal dict with scaled sizes and added metadata.
            
        Requirements: 7.1, 7.6, 7.7
        """
        # Normalize confidence to 0-1 range if provided as percentage
        if confidence > 1.0:
            confidence = confidence / 100.0
        
        # Get the multiplier for this confidence level
        multiplier = self.get_multiplier(confidence)
        
        # Scale size fields if present
        if "size" in signal and signal["size"] is not None:
            signal["size"] = signal["size"] * multiplier
        
        if "size_usd" in signal and signal["size_usd"] is not None:
            signal["size_usd"] = signal["size_usd"] * multiplier
        
        # Add metadata (Requirement 7.7)
        signal["confidence_multiplier"] = multiplier
        signal["confidence"] = confidence
        
        return signal
    
    def get_band_description(self, confidence: float) -> str:
        """
        Get a human-readable description of the confidence band.
        
        Args:
            confidence: Signal confidence value (0.0 to 1.0)
            
        Returns:
            Description string for the confidence band.
        """
        # Normalize confidence to 0-1 range if provided as percentage
        if confidence > 1.0:
            confidence = confidence / 100.0
        
        multiplier = self.get_multiplier(confidence)
        
        if multiplier == 0.50:
            return f"low_confidence ({confidence:.0%}): 0.5x size"
        elif multiplier == 0.75:
            return f"moderate_confidence ({confidence:.0%}): 0.75x size"
        elif multiplier == 1.00:
            return f"high_confidence ({confidence:.0%}): 1.0x size"
        elif multiplier == 1.25:
            return f"very_high_confidence ({confidence:.0%}): 1.25x size"
        else:
            return f"confidence ({confidence:.0%}): {multiplier}x size"


class ConfidencePositionSizerStage(Stage):
    """
    Pipeline stage that applies confidence-based position sizing.
    
    DEPRECATED: Use EVPositionSizerStage instead. EVPositionSizerStage provides
    EV-based sizing that scales based on edge (EV - EV_Min), cost environment,
    and calibration reliability.
    
    This stage runs after the confidence gate and before risk limits.
    It scales position sizes based on signal confidence using the
    ConfidencePositionSizer.
    
    Requirements:
    - 7.1: Calculate confidence multiplier for signals passing threshold
    - 7.6: Apply multiplier after base sizing, before risk limits
    - 7.7: Add confidence_multiplier and confidence to signal metadata
    """
    name = "confidence_position_sizer"
    
    def __init__(
        self,
        config: Optional[ConfidencePositionSizerConfig] = None,
        telemetry: Optional["BlockedSignalTelemetry"] = None,
    ):
        """Initialize ConfidencePositionSizerStage.
        
        Args:
            config: Configuration for the sizer. Uses defaults if None.
            telemetry: Optional telemetry for logging sizing decisions.
            
        .. deprecated::
            Use EVPositionSizerStage instead for EV-based position sizing.
        """
        warnings.warn(
            "ConfidencePositionSizerStage is deprecated. Use EVPositionSizerStage instead "
            "for EV-based position sizing that accounts for edge, cost, and reliability.",
            DeprecationWarning,
            stacklevel=2,
        )
        log_warning(
            "ConfidencePositionSizerStage is deprecated. Use EVPositionSizerStage instead.",
            event="confidence_position_sizer_deprecated",
        )
        # Note: ConfidencePositionSizer also emits a deprecation warning
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            self.sizer = ConfidencePositionSizer(config)
        self.telemetry = telemetry
    
    async def run(self, ctx: StageContext) -> StageResult:
        """
        Apply confidence-based sizing to the signal.
        
        Args:
            ctx: Stage context containing signal and prediction data.
            
        Returns:
            StageResult.CONTINUE after applying sizing.
            
        Requirements: 7.1, 7.6, 7.7
        """
        # Get confidence from prediction data
        prediction = ctx.data.get("prediction") or {}
        confidence = prediction.get("confidence", 0.0)
        
        # Normalize confidence to 0-1 range if provided as percentage
        if confidence > 1.0:
            confidence = confidence / 100.0
        
        # Skip sizing if no signal present
        if not ctx.signal:
            return StageResult.CONTINUE
        
        # Convert signal to dict for processing
        signal = signal_to_dict(ctx.signal)
        
        # Apply confidence-based sizing
        original_size = signal.get("size")
        original_size_usd = signal.get("size_usd")
        
        self.sizer.apply(signal, confidence)
        
        # Store the modified sizing in ctx.data for downstream stages
        ctx.data["confidence_sized_signal"] = signal
        ctx.data["confidence_multiplier"] = signal.get("confidence_multiplier")
        ctx.data["confidence_scaled_size"] = signal.get("size")
        ctx.data["confidence_scaled_size_usd"] = signal.get("size_usd")
        
        # Log the sizing decision
        log_info(
            "confidence_position_sizer_applied",
            symbol=ctx.symbol,
            confidence=round(confidence, 4),
            multiplier=signal.get("confidence_multiplier"),
            original_size=original_size,
            scaled_size=signal.get("size"),
            original_size_usd=original_size_usd,
            scaled_size_usd=signal.get("size_usd"),
        )
        
        return StageResult.CONTINUE
