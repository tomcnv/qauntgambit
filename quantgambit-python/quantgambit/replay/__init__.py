"""
Deterministic replay system for QuantGambit.

This package provides:
- EventReplayer: Replay recorded sessions through the pipeline
- ReplayDiff: Compare decisions between runs
- Golden test support

Replay enables:
- Regression testing
- Debugging production issues
- Validating changes
"""

from quantgambit.replay.replayer import EventReplayer, ReplayConfig, ReplayResult
from quantgambit.replay.diff import ReplayDiff, DiffResult

__all__ = [
    "EventReplayer",
    "ReplayConfig",
    "ReplayResult",
    "ReplayDiff",
    "DiffResult",
]
