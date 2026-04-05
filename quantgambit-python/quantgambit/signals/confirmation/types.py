"""Shared types for unified confirmation policy."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Mapping, Optional


@dataclass(frozen=True)
class ConfirmationWeights:
    trend: float = 1.0
    flow: float = 1.0
    risk_stability: float = 1.0


@dataclass(frozen=True)
class EntryPolicyConfig:
    min_confidence: float = 0.67
    min_votes: int = 2


@dataclass(frozen=True)
class ExitPolicyConfig:
    min_confidence: float = 0.50
    min_votes: int = 2


@dataclass(frozen=True)
class ConfirmationOverrideBounds:
    min_weight: float = 0.1
    max_weight: float = 5.0
    min_confidence: float = 0.1
    max_confidence: float = 0.99
    min_votes: int = 1
    max_votes: int = 3


@dataclass(frozen=True)
class StrategyPolicyOverride:
    weights: Optional[ConfirmationWeights] = None
    entry_min_confidence: Optional[float] = None
    entry_min_votes: Optional[int] = None
    exit_min_confidence: Optional[float] = None
    exit_min_votes: Optional[int] = None


@dataclass(frozen=True)
class ConfirmationPolicyConfig:
    enabled: bool = True
    mode: str = "shadow"  # shadow | enforce
    version: str = "v1"
    weights: ConfirmationWeights = field(default_factory=ConfirmationWeights)
    entry: EntryPolicyConfig = field(default_factory=EntryPolicyConfig)
    exit_non_emergency: ExitPolicyConfig = field(default_factory=ExitPolicyConfig)
    override_bounds: ConfirmationOverrideBounds = field(default_factory=ConfirmationOverrideBounds)
    strategy_overrides: Mapping[str, StrategyPolicyOverride] = field(default_factory=dict)


@dataclass(frozen=True)
class ConfirmationPolicyResult:
    confirm: bool
    confidence: float
    evidence_votes: Dict[str, bool]
    failed_hard_guards: List[str]
    decision_reason_codes: List[str]
    passed_evidence: List[str]
    mode: str
    version: str

