"""Integration module for trading pipeline integration.

This module provides components for integrating the backtesting system
with the live trading pipeline, including:
- Configuration version management
- Configuration diff engine
- Configuration registry (single source of truth)
- Decision recording
- Warm start support
- Shadow mode comparison
- Execution simulation
- Replay validation
"""

from quantgambit.integration.config_version import (
    ConfigVersion,
    ConfigVersionStore,
)
from quantgambit.integration.config_diff import (
    ConfigDiff,
    ConfigDiffEngine,
    CRITICAL_PARAMS,
    WARNING_PARAMS,
)
from quantgambit.integration.config_registry import (
    ConfigurationRegistry,
    ConfigurationError,
)
from quantgambit.integration.decision_recording import (
    RecordedDecision,
)
from quantgambit.integration.warm_start import (
    WarmStartState,
)
from quantgambit.integration.shadow_comparison import (
    ComparisonResult,
    ComparisonMetrics,
)
from quantgambit.integration.execution_simulator import (
    ExecutionSimulatorConfig,
    SimulatedFill,
    ExecutionSimulator,
    CalibrationResult,
)
from quantgambit.integration.replay_validation import (
    ReplayResult,
    ReplayReport,
    ReplayManager,
    VALID_CHANGE_CATEGORIES,
)
from quantgambit.integration.unified_metrics import (
    UnifiedMetrics,
    MetricsComparison,
    empty_metrics,
    MetricsReconciler,
    SIGNIFICANT_DIFFERENCE_THRESHOLD,
)

__all__ = [
    "ConfigVersion",
    "ConfigVersionStore",
    "ConfigDiff",
    "ConfigDiffEngine",
    "CRITICAL_PARAMS",
    "WARNING_PARAMS",
    "ConfigurationRegistry",
    "ConfigurationError",
    "RecordedDecision",
    "WarmStartState",
    "ComparisonResult",
    "ComparisonMetrics",
    "ExecutionSimulatorConfig",
    "SimulatedFill",
    "ExecutionSimulator",
    "CalibrationResult",
    "ReplayResult",
    "ReplayReport",
    "ReplayManager",
    "VALID_CHANGE_CATEGORIES",
    "UnifiedMetrics",
    "MetricsComparison",
    "empty_metrics",
    "MetricsReconciler",
    "SIGNIFICANT_DIFFERENCE_THRESHOLD",
]
