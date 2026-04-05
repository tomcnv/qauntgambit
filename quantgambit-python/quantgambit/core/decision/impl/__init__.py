"""
Concrete implementations of decision pipeline interfaces.

This package contains production-ready implementations of the
protocol interfaces defined in core.decision.interfaces.
"""

from quantgambit.core.decision.impl.feature_builder import (
    DefaultFeatureFrameBuilder,
)
from quantgambit.core.decision.impl.model_runner import (
    PassthroughModelRunner,
    ImbalanceModelRunner,
)
from quantgambit.core.decision.impl.calibrator import (
    IdentityCalibrator,
    PlattCalibrator,
)

# Backward compatibility aliases
DummyFeatureFrameBuilder = DefaultFeatureFrameBuilder
DummyModelRunner = PassthroughModelRunner
DummyCalibrator = IdentityCalibrator
from quantgambit.core.decision.impl.edge_transform import (
    TanhEdgeTransform,
    LinearEdgeTransform,
    ThresholdEdgeTransform,
)
from quantgambit.core.decision.impl.vol_estimator import (
    SimpleVolatilityEstimator,
    EWMAVolatilityEstimator,
    ConstantVolatilityEstimator,
)
from quantgambit.core.decision.impl.risk_mapper import (
    VolTargetRiskMapper,
    FixedSizeRiskMapper,
    ScaledSignalRiskMapper,
)
from quantgambit.core.decision.impl.execution_policy import (
    MarketExecutionPolicy,
    LimitExecutionPolicy,
    ExitOnlyExecutionPolicy,
    ProtectiveOrderParams,
)

__all__ = [
    # Feature builders
    "DefaultFeatureFrameBuilder",
    # Model runners
    "PassthroughModelRunner",
    "ImbalanceModelRunner",
    # Calibrators
    "IdentityCalibrator",
    "PlattCalibrator",
    # Edge transforms
    "TanhEdgeTransform",
    "LinearEdgeTransform",
    "ThresholdEdgeTransform",
    # Volatility estimators
    "SimpleVolatilityEstimator",
    "EWMAVolatilityEstimator",
    "ConstantVolatilityEstimator",
    # Risk mappers
    "VolTargetRiskMapper",
    "FixedSizeRiskMapper",
    "ScaledSignalRiskMapper",
    # Execution policies
    "MarketExecutionPolicy",
    "LimitExecutionPolicy",
    "ExitOnlyExecutionPolicy",
    "ProtectiveOrderParams",
    # Backward compatibility aliases
    "DummyFeatureFrameBuilder",
    "DummyModelRunner",
    "DummyCalibrator",
]
