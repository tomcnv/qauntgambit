"""
Decision pipeline interfaces and implementations.

This package defines the formal decision pipeline:
1. BookGuardian (quoteability gate)
2. FeatureFrameBuilder (market data -> features)
3. ModelRunner (features -> raw probability)
4. Calibrator (raw -> calibrated probability)
5. EdgeTransform (probability -> edge signal)
6. VolatilityEstimator (market data -> volatility)
7. RiskMapper (signal + vol -> target weight)
8. ExecutionPolicy (weight delta -> intents)

Each step is a Protocol that can be implemented and tested independently.
"""

from quantgambit.core.decision.interfaces import (
    # Data types
    FeatureFrame,
    ModelOutput,
    CalibratedOutput,
    EdgeOutput,
    VolOutput,
    RiskOutput,
    Position,
    BookSnapshot,
    DecisionInput,
    ExecutionIntent,
    # Protocols
    FeatureFrameBuilder,
    ModelRunner,
    Calibrator,
    EdgeTransform,
    VolatilityEstimator,
    RiskMapper,
    ExecutionPolicy,
)
from quantgambit.core.decision.record import (
    DecisionOutcome,
    DecisionRecord,
    DecisionRecordBuilder,
)
from quantgambit.core.decision.calibration import (
    CalibrationOutput,
    CalibrationGate,
)

__all__ = [
    # Data types
    "FeatureFrame",
    "ModelOutput",
    "CalibratedOutput",
    "EdgeOutput",
    "VolOutput",
    "RiskOutput",
    "Position",
    "BookSnapshot",
    "DecisionInput",
    "ExecutionIntent",
    # Decision record
    "DecisionOutcome",
    "DecisionRecord",
    "DecisionRecordBuilder",
    # Calibration
    "CalibrationOutput",
    "CalibrationGate",
    # Protocols
    "FeatureFrameBuilder",
    "ModelRunner",
    "Calibrator",
    "EdgeTransform",
    "VolatilityEstimator",
    "RiskMapper",
    "ExecutionPolicy",
]
