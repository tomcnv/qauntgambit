"""
Pre-Trade Gating Stages

This module provides the two-layer gating system:

Layer A - Global Gates (side-agnostic, run before signal generation):
- DataReadinessStage: Sanity checks (book/trades present, clock sync)
- SnapshotBuilderStage: Freeze immutable MarketSnapshot
- SymbolCharacteristicsStage: Inject symbol characteristics and resolved params
- GlobalGateStage: Side-agnostic rejection (spread, depth, staleness, vol shock)
- StrategyTrendAlignmentStage: Reject signals that conflict with market trend

Layer B - Candidate Pipeline (side-aware, run after signal generation):
- CandidateGenerationStage: Wraps strategy + prediction to produce TradeCandidate
- CandidateVetoStage: Side-aware vetoes (orderflow, regime, tradeability)
- CooldownStage: Per-symbol-strategy cooldown and hysteresis
"""

from quantgambit.signals.stages.data_readiness import DataReadinessStage
from quantgambit.signals.stages.snapshot_builder import SnapshotBuilderStage
from quantgambit.signals.stages.amt_calculator import (
    AMTCalculatorStage,
    AMTCalculatorConfig,
    AMTLevels,
    CandleCache,
)
from quantgambit.signals.stages.symbol_characteristics_stage import SymbolCharacteristicsStage
from quantgambit.signals.stages.global_gate import (
    GlobalGateStage,
    GlobalGateConfig,
    VolShockConfig,
)
from quantgambit.signals.stages.strategy_trend_alignment import (
    StrategyTrendAlignmentStage,
    StrategyTrendAlignmentConfig,
    STRATEGY_TREND_RULES,
)
from quantgambit.signals.stages.model_direction_alignment import (
    ModelDirectionAlignmentStage,
    ModelDirectionAlignmentConfig,
)
from quantgambit.signals.stages.minimum_hold_time import (
    MinimumHoldTimeEnforcer,
    MinimumHoldTimeConfig,
    STRATEGY_MIN_HOLD_TIMES,
)
from quantgambit.signals.stages.candidate_generation import CandidateGenerationStage
from quantgambit.signals.stages.candidate_veto import CandidateVetoStage
from quantgambit.signals.stages.cooldown import CooldownStage
from quantgambit.signals.stages.session_risk import (
    SessionRiskResult,
    classify_session_risk,
    get_utc_hour_from_timestamp,
    is_strategy_allowed_in_session,
    is_strategy_preferred_for_session_risk,
    STRATEGY_SESSION_PREFERENCES,
)
from quantgambit.signals.stages.session_filter import (
    SessionFilterStage,
    SessionFilterConfig,
)
from quantgambit.signals.stages.ev_gate import (
    EVGateStage,
    EVGateConfig,
    EVGateResult,
    EVGateRejectCode,
    CostEstimator,
    CostEstimate,
    calculate_L_G_R,
    calculate_cost_ratio,
    calculate_ev,
    calculate_p_min,
)
from quantgambit.signals.stages.ev_position_sizer import (
    EVPositionSizerStage,
    EVPositionSizerConfig,
    EVSizingResult,
    compute_ev_multiplier,
    compute_cost_scale,
    compute_reliability_scale,
)
from quantgambit.signals.stages.cost_data_quality import (
    CostDataQualityStage,
    CostDataQualityConfig,
    CostDataQualityResult,
)
from quantgambit.signals.stages.arbitration_stage import (
    ArbitrationStage,
    ArbitrationConfig,
)
from quantgambit.signals.stages.confirmation_stage import (
    ConfirmationStage,
    ConfirmationConfig,
)
from quantgambit.signals.stages.execution_feasibility_gate import (
    ExecutionFeasibilityGate,
    ExecutionFeasibilityConfig,
    ExecutionPolicy,
)

__all__ = [
    "DataReadinessStage",
    "SnapshotBuilderStage",
    # AMT calculator stage
    "AMTCalculatorStage",
    "AMTCalculatorConfig",
    "AMTLevels",
    "CandleCache",
    "SymbolCharacteristicsStage",
    "GlobalGateStage",
    "GlobalGateConfig",
    "VolShockConfig",
    "StrategyTrendAlignmentStage",
    "StrategyTrendAlignmentConfig",
    "ModelDirectionAlignmentStage",
    "ModelDirectionAlignmentConfig",
    "STRATEGY_TREND_RULES",
    "MinimumHoldTimeEnforcer",
    "MinimumHoldTimeConfig",
    "STRATEGY_MIN_HOLD_TIMES",
    "CandidateGenerationStage",
    "CandidateVetoStage",
    "CooldownStage",
    # Session risk exports
    "SessionRiskResult",
    "classify_session_risk",
    "get_utc_hour_from_timestamp",
    "is_strategy_allowed_in_session",
    "is_strategy_preferred_for_session_risk",
    "STRATEGY_SESSION_PREFERENCES",
    # Session filter stage
    "SessionFilterStage",
    "SessionFilterConfig",
    # EV gate stage
    "EVGateStage",
    "EVGateConfig",
    "EVGateResult",
    "EVGateRejectCode",
    "CostEstimator",
    "CostEstimate",
    "calculate_L_G_R",
    "calculate_cost_ratio",
    "calculate_ev",
    "calculate_p_min",
    # EV position sizer stage
    "EVPositionSizerStage",
    "EVPositionSizerConfig",
    "EVSizingResult",
    "compute_ev_multiplier",
    "compute_cost_scale",
    "compute_reliability_scale",
    # Cost data quality stage
    "CostDataQualityStage",
    "CostDataQualityConfig",
    "CostDataQualityResult",
    # Arbitration stage (Requirement 4.5)
    "ArbitrationStage",
    "ArbitrationConfig",
    # Confirmation stage (Requirement 4.6, 4.7)
    "ConfirmationStage",
    "ConfirmationConfig",
    # Execution feasibility gate (Requirement 9)
    "ExecutionFeasibilityGate",
    "ExecutionFeasibilityConfig",
    "ExecutionPolicy",
]
