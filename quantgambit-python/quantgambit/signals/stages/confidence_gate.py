"""
ConfidenceGateStage - Rejects signals below minimum confidence threshold.

DEPRECATED: This stage is deprecated in favor of EVGateStage, which provides
proper Expected Value (EV) based filtering that accounts for reward-to-risk
ratio and costs. Use EVGateStage instead for new implementations.

This stage is part of the loss prevention system that filters out low-quality
trades before execution. It runs early in the pipeline to reject signals
with confidence below the configured threshold.

Requirements: 1.1, 1.2, 1.3, 1.4, 1.5
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass
from typing import Optional, TYPE_CHECKING

from quantgambit.signals.pipeline import Stage, StageContext, StageResult
from quantgambit.observability.logger import log_info, log_warning

if TYPE_CHECKING:
    from quantgambit.observability.blocked_signal_telemetry import BlockedSignalTelemetry


@dataclass
class ConfidenceGateConfig:
    """Configuration for ConfidenceGateStage.
    
    Attributes:
        min_confidence: Minimum confidence threshold (0.0 to 1.0).
                       Signals with confidence below this value are rejected.
                       Default is 0.50 (50% minimum confidence).
                       
    Requirements: 1.3
    """
    min_confidence: float = 0.50  # 50% minimum confidence
    
    def __post_init__(self):
        """Validate configuration parameters."""
        if not 0.0 <= self.min_confidence <= 1.0:
            raise ValueError(
                f"min_confidence must be between 0 and 1, got {self.min_confidence}"
            )


class ConfidenceGateStage(Stage):
    """
    Pipeline stage that rejects signals below the minimum confidence threshold.
    
    DEPRECATED: Use EVGateStage instead. EVGateStage provides proper EV-based
    filtering that accounts for reward-to-risk ratio (R) and costs (C), rather
    than using a fixed confidence threshold.
    
    This stage extracts the confidence value from ctx.data["prediction"]["confidence"]
    and rejects signals that fall below the configured threshold. Rejected signals
    are logged with telemetry for observability.
    
    Requirements:
    - 1.1: Reject signals with confidence below 50%
    - 1.2: Emit telemetry with signal details and confidence value
    - 1.4: Apply threshold before position sizing or risk calculations
    """
    name = "confidence_gate"
    
    def __init__(
        self,
        config: Optional[ConfidenceGateConfig] = None,
        telemetry: Optional["BlockedSignalTelemetry"] = None,
    ):
        """Initialize ConfidenceGateStage.
        
        Args:
            config: Configuration for the confidence gate. Uses defaults if None.
            telemetry: Optional telemetry for recording blocked signals.
            
        .. deprecated::
            Use EVGateStage instead for EV-based entry filtering.
        """
        warnings.warn(
            "ConfidenceGateStage is deprecated. Use EVGateStage instead for "
            "EV-based entry filtering that accounts for reward-to-risk ratio and costs.",
            DeprecationWarning,
            stacklevel=2,
        )
        log_warning(
            "ConfidenceGateStage is deprecated. Use EVGateStage instead.",
            event="confidence_gate_deprecated",
        )
        self.config = config or ConfidenceGateConfig()
        self.telemetry = telemetry
    
    async def run(self, ctx: StageContext) -> StageResult:
        """
        Evaluate signal confidence and reject if below threshold.
        
        Args:
            ctx: Stage context containing prediction data.
            
        Returns:
            StageResult.REJECT if confidence is below threshold,
            StageResult.CONTINUE otherwise.
            
        Requirements: 1.1, 1.4
        """
        # Extract confidence from prediction data
        prediction = ctx.data.get("prediction") or {}
        confidence = prediction.get("confidence", 0.0)
        
        # Normalize confidence to 0-1 range if provided as percentage
        if confidence > 1.0:
            confidence = confidence / 100.0
        
        # Check against threshold
        if confidence < self.config.min_confidence:
            ctx.rejection_reason = "low_confidence"
            ctx.rejection_stage = self.name
            ctx.rejection_detail = {
                "confidence": confidence,
                "threshold": self.config.min_confidence,
            }
            
            # Emit telemetry for blocked signal (Requirement 1.2)
            if self.telemetry:
                await self.telemetry.record_blocked(
                    symbol=ctx.symbol,
                    gate_name="confidence_gate",
                    reason=f"confidence {confidence:.1%} < threshold {self.config.min_confidence:.1%}",
                    metrics={
                        "confidence": confidence,
                        "threshold": self.config.min_confidence,
                    },
                )
            
            log_warning(
                "confidence_gate_reject",
                symbol=ctx.symbol,
                confidence=round(confidence, 4),
                threshold=self.config.min_confidence,
            )
            
            return StageResult.REJECT
        
        # Log successful pass for debugging
        log_info(
            "confidence_gate_pass",
            symbol=ctx.symbol,
            confidence=round(confidence, 4),
            threshold=self.config.min_confidence,
        )
        
        return StageResult.CONTINUE
