"""Backtesting helpers."""

from quantgambit.backtesting.ev_threshold_sweep import (
    EVThresholdSweeper,
    BacktestTrade,
    ThresholdMetrics,
    SweepResult,
    WalkForwardFold,
    WalkForwardValidator,
    WalkForwardFoldResult,
    WalkForwardValidationResult,
    KneeDetector,
    KneeDetectionResult,
    ThresholdRecommender,
    CandidateScore,
    ThresholdRecommendation,
    generate_sweep_report,
    generate_walk_forward_report,
    generate_recommendation_report,
)
from quantgambit.backtesting.dataset_scanner import (
    DatasetScanner,
    DatasetMetadata,
    ScanConfig,
    scan_datasets,
)
from quantgambit.backtesting.job_queue import (
    BacktestJobQueue,
    JobInfo,
    JobStatus,
)
from quantgambit.backtesting.executor import (
    BacktestExecutor,
    BacktestStatus,
    ExecutorConfig,
    ExecutionResult,
    is_valid_transition,
    is_terminal_status,
    create_executor_function,
    VALID_TRANSITIONS,
)

__all__ = [
    "EVThresholdSweeper",
    "BacktestTrade",
    "ThresholdMetrics",
    "SweepResult",
    "WalkForwardFold",
    "WalkForwardValidator",
    "WalkForwardFoldResult",
    "WalkForwardValidationResult",
    "KneeDetector",
    "KneeDetectionResult",
    "ThresholdRecommender",
    "CandidateScore",
    "ThresholdRecommendation",
    "generate_sweep_report",
    "generate_walk_forward_report",
    "generate_recommendation_report",
    # Dataset scanner
    "DatasetScanner",
    "DatasetMetadata",
    "ScanConfig",
    "scan_datasets",
    # Job queue
    "BacktestJobQueue",
    "JobInfo",
    "JobStatus",
    # Executor
    "BacktestExecutor",
    "BacktestStatus",
    "ExecutorConfig",
    "ExecutionResult",
    "is_valid_transition",
    "is_terminal_status",
    "create_executor_function",
    "VALID_TRANSITIONS",
]
