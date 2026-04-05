"""Replay validation data structures for trading pipeline integration.

This module provides the ReplayResult and ReplayReport dataclasses for
capturing and aggregating replay validation results.

Feature: trading-pipeline-integration
Requirements: 7.2 - WHEN replaying decisions THEN the System SHALL compare new
              decisions against original decisions
Requirements: 7.3 - THE System SHALL report decision changes with categorization
              (expected, unexpected, improved, degraded)
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from quantgambit.integration.decision_recording import RecordedDecision


# Valid change categories for replay results
VALID_CHANGE_CATEGORIES = frozenset({"expected", "unexpected", "improved", "degraded"})


def categorize_change(
    original_decision: str,
    replayed_decision: str,
) -> str:
    """Categorize a change between original and replayed decisions.
    
    This function implements the change categorization logic as specified in
    the design document:
    - "improved" if original was rejected and replay is accepted
    - "degraded" if original was accepted and replay is rejected
    - "unexpected" for other changes
    - "expected" when decisions match
    
    Feature: trading-pipeline-integration
    Requirements: 7.3 - THE System SHALL report decision changes with categorization
                  (expected, unexpected, improved, degraded)
    
    Args:
        original_decision: The original decision outcome ("accepted" or "rejected")
        replayed_decision: The replayed decision outcome ("accepted" or "rejected")
        
    Returns:
        Change category: "expected", "unexpected", "improved", or "degraded"
        
    Examples:
        >>> categorize_change("accepted", "accepted")
        'expected'
        >>> categorize_change("rejected", "accepted")
        'improved'
        >>> categorize_change("accepted", "rejected")
        'degraded'
        >>> categorize_change("rejected", "rejected")
        'expected'
    """
    # When decisions match, the change is expected (no change)
    if original_decision == replayed_decision:
        return "expected"
    
    # When original was rejected and replay is accepted, it's an improvement
    # (the pipeline is now accepting previously rejected decisions)
    if original_decision == "rejected" and replayed_decision == "accepted":
        return "improved"
    
    # When original was accepted and replay is rejected, it's a degradation
    # (the pipeline is now rejecting previously accepted decisions)
    if original_decision == "accepted" and replayed_decision == "rejected":
        return "degraded"
    
    # Any other change is unexpected (e.g., shadow decisions changing)
    return "unexpected"


def identify_stage_diff(
    original_rejection_stage: str | None,
    replayed_rejection_stage: str | None,
) -> str | None:
    """Identify the stage difference between original and replayed decisions.
    
    When the rejection stage changes between original and replayed decisions,
    this function generates a diff string in the format:
    "{original_stage}->{replayed_stage}"
    
    Feature: trading-pipeline-integration
    Requirements: 7.6 - WHEN replay detects unexpected decision changes THEN the
                  System SHALL provide detailed diff showing which stage caused
                  the change
    
    Args:
        original_rejection_stage: The stage that rejected in the original decision,
            or None if the decision was accepted
        replayed_rejection_stage: The stage that rejected in the replayed decision,
            or None if the decision was accepted
            
    Returns:
        Stage diff string in format "{original}->{replayed}", or None if stages
        are the same
        
    Examples:
        >>> identify_stage_diff("ev_gate", "confirmation")
        'ev_gate->confirmation'
        >>> identify_stage_diff(None, "ev_gate")
        'none->ev_gate'
        >>> identify_stage_diff("ev_gate", None)
        'ev_gate->none'
        >>> identify_stage_diff("ev_gate", "ev_gate")
        None
        >>> identify_stage_diff(None, None)
        None
    """
    # If stages are the same, no diff
    if original_rejection_stage == replayed_rejection_stage:
        return None
    
    # Convert None to "none" for display
    original_stage = original_rejection_stage or "none"
    new_stage = replayed_rejection_stage or "none"
    
    return f"{original_stage}->{new_stage}"


def aggregate_changes(
    results: list["ReplayResult"],
) -> tuple[dict[str, int], dict[str, int]]:
    """Aggregate changes by category and stage from replay results.
    
    This function processes a list of ReplayResult objects and aggregates
    the changes into two dictionaries:
    1. changes_by_category: Count of changes by category (expected, unexpected,
       improved, degraded)
    2. changes_by_stage: Count of changes by stage difference
    
    Feature: trading-pipeline-integration
    Requirements: 7.3 - THE System SHALL report decision changes with categorization
    
    Args:
        results: List of ReplayResult objects to aggregate
        
    Returns:
        Tuple of (changes_by_category, changes_by_stage) dictionaries
        
    Examples:
        >>> results = [
        ...     ReplayResult(original_decision=..., matches=False, 
        ...                  change_category="improved", stage_diff="ev_gate->none"),
        ...     ReplayResult(original_decision=..., matches=False,
        ...                  change_category="degraded", stage_diff="none->ev_gate"),
        ... ]
        >>> by_category, by_stage = aggregate_changes(results)
        >>> by_category
        {'improved': 1, 'degraded': 1}
        >>> by_stage
        {'ev_gate->none': 1, 'none->ev_gate': 1}
    """
    changes_by_category: dict[str, int] = {}
    changes_by_stage: dict[str, int] = {}
    
    for result in results:
        if not result.matches:
            # Aggregate by category
            changes_by_category[result.change_category] = \
                changes_by_category.get(result.change_category, 0) + 1
            
            # Aggregate by stage diff (if present)
            if result.stage_diff:
                changes_by_stage[result.stage_diff] = \
                    changes_by_stage.get(result.stage_diff, 0) + 1
    
    return changes_by_category, changes_by_stage


@dataclass
class ReplayResult:
    """Result of replaying a single decision.
    
    Represents the comparison between an original recorded decision and the
    result of replaying it through the current pipeline. This enables
    validation of pipeline changes by comparing historical decisions.
    
    Feature: trading-pipeline-integration
    Requirements: 7.2, 7.3
    
    Attributes:
        original_decision: The original RecordedDecision being replayed
        replayed_decision: The decision outcome from replay ("accepted" or "rejected")
        replayed_signal: Signal generated during replay (if accepted)
        replayed_rejection_stage: Stage that rejected during replay (if rejected)
        matches: Whether the replayed decision matches the original
        change_category: Category of change if decisions differ:
            - "expected": Change was anticipated (e.g., known bug fix)
            - "unexpected": Change was not anticipated
            - "improved": Now accepting previously rejected (potential improvement)
            - "degraded": Now rejecting previously accepted (potential regression)
        stage_diff: Description of stage difference if rejection_stage changed
            Format: "{original_stage}->{replayed_stage}"
    """
    original_decision: "RecordedDecision"
    replayed_decision: str
    replayed_signal: Optional[Dict[str, Any]] = None
    replayed_rejection_stage: Optional[str] = None
    matches: bool = True
    change_category: str = "expected"
    stage_diff: Optional[str] = None
    
    def __post_init__(self) -> None:
        """Validate the ReplayResult after initialization."""
        if self.replayed_decision not in ("accepted", "rejected"):
            raise ValueError(
                f"replayed_decision must be 'accepted' or 'rejected', "
                f"got '{self.replayed_decision}'"
            )
        if self.change_category not in VALID_CHANGE_CATEGORIES:
            raise ValueError(
                f"change_category must be one of {VALID_CHANGE_CATEGORIES}, "
                f"got '{self.change_category}'"
            )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization.
        
        Returns:
            Dictionary representation of the ReplayResult
        """
        return {
            "original_decision": self.original_decision.to_dict(),
            "replayed_decision": self.replayed_decision,
            "replayed_signal": self.replayed_signal,
            "replayed_rejection_stage": self.replayed_rejection_stage,
            "matches": self.matches,
            "change_category": self.change_category,
            "stage_diff": self.stage_diff,
        }
    
    @classmethod
    def from_dict(
        cls,
        data: Dict[str, Any],
        recorded_decision_cls: type,
    ) -> "ReplayResult":
        """Create ReplayResult from dictionary.
        
        Args:
            data: Dictionary with ReplayResult fields
            recorded_decision_cls: The RecordedDecision class for deserialization
            
        Returns:
            ReplayResult instance
        """
        original_decision = recorded_decision_cls.from_dict(data["original_decision"])
        
        return cls(
            original_decision=original_decision,
            replayed_decision=data["replayed_decision"],
            replayed_signal=data.get("replayed_signal"),
            replayed_rejection_stage=data.get("replayed_rejection_stage"),
            matches=data.get("matches", True),
            change_category=data.get("change_category", "expected"),
            stage_diff=data.get("stage_diff"),
        )
    
    def is_improvement(self) -> bool:
        """Check if this result represents an improvement.
        
        An improvement is when a previously rejected decision is now accepted.
        
        Returns:
            True if this is an improvement
        """
        return self.change_category == "improved"
    
    def is_degradation(self) -> bool:
        """Check if this result represents a degradation.
        
        A degradation is when a previously accepted decision is now rejected.
        
        Returns:
            True if this is a degradation
        """
        return self.change_category == "degraded"
    
    def is_unexpected(self) -> bool:
        """Check if this result represents an unexpected change.
        
        Returns:
            True if this is an unexpected change
        """
        return self.change_category == "unexpected"
    
    def get_original_decision_id(self) -> str:
        """Get the decision ID of the original decision.
        
        Returns:
            The original decision's ID
        """
        return self.original_decision.decision_id
    
    def get_original_symbol(self) -> str:
        """Get the symbol from the original decision.
        
        Returns:
            The original decision's symbol
        """
        return self.original_decision.symbol
    
    def get_original_timestamp(self) -> datetime:
        """Get the timestamp from the original decision.
        
        Returns:
            The original decision's timestamp
        """
        return self.original_decision.timestamp


@dataclass
class ReplayReport:
    """Summary of replay validation.
    
    Aggregates results from replaying multiple decisions through the current
    pipeline. Provides statistics on match rates, change categories, and
    stage-level differences.
    
    Feature: trading-pipeline-integration
    Requirements: 7.2, 7.3
    
    Attributes:
        total_replayed: Total number of decisions replayed
        matches: Number of decisions that matched original outcome
        changes: Number of decisions that changed from original outcome
        match_rate: Ratio of matches to total (0.0 to 1.0)
        changes_by_category: Count of changes by category
            (expected, unexpected, improved, degraded)
        changes_by_stage: Count of changes by stage difference
            Keys are in format "{original_stage}->{replayed_stage}"
        sample_changes: Sample of ReplayResult objects for changed decisions
            (limited to first 10 changes for review)
        run_id: Optional unique identifier for this replay run
        run_at: Timestamp when the replay was executed
        start_time: Start of the time range that was replayed
        end_time: End of the time range that was replayed
    """
    total_replayed: int
    matches: int
    changes: int
    match_rate: float
    changes_by_category: Dict[str, int] = field(default_factory=dict)
    changes_by_stage: Dict[str, int] = field(default_factory=dict)
    sample_changes: List[ReplayResult] = field(default_factory=list)
    run_id: Optional[str] = None
    run_at: Optional[datetime] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    
    def __post_init__(self) -> None:
        """Validate the ReplayReport after initialization."""
        if self.total_replayed < 0:
            raise ValueError(
                f"total_replayed must be non-negative, got {self.total_replayed}"
            )
        if self.matches < 0:
            raise ValueError(f"matches must be non-negative, got {self.matches}")
        if self.changes < 0:
            raise ValueError(f"changes must be non-negative, got {self.changes}")
        if not (0.0 <= self.match_rate <= 1.0):
            raise ValueError(
                f"match_rate must be between 0.0 and 1.0, got {self.match_rate}"
            )
        
        # Validate that matches + changes equals total_replayed
        if self.matches + self.changes != self.total_replayed:
            raise ValueError(
                f"matches ({self.matches}) + changes ({self.changes}) must equal "
                f"total_replayed ({self.total_replayed})"
            )
        
        # Validate change categories
        for category in self.changes_by_category:
            if category not in VALID_CHANGE_CATEGORIES:
                raise ValueError(
                    f"Invalid change category '{category}', "
                    f"must be one of {VALID_CHANGE_CATEGORIES}"
                )
        
        # Set run_at to now if not provided
        if self.run_at is None:
            object.__setattr__(
                self,
                'run_at',
                datetime.now(timezone.utc)
            )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization.
        
        Returns:
            Dictionary representation of the ReplayReport
        """
        return {
            "total_replayed": self.total_replayed,
            "matches": self.matches,
            "changes": self.changes,
            "match_rate": self.match_rate,
            "changes_by_category": self.changes_by_category,
            "changes_by_stage": self.changes_by_stage,
            "sample_changes": [r.to_dict() for r in self.sample_changes],
            "run_id": self.run_id,
            "run_at": self.run_at.isoformat() if self.run_at else None,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "end_time": self.end_time.isoformat() if self.end_time else None,
        }
    
    @classmethod
    def from_dict(
        cls,
        data: Dict[str, Any],
        recorded_decision_cls: type,
    ) -> "ReplayReport":
        """Create ReplayReport from dictionary.
        
        Args:
            data: Dictionary with ReplayReport fields
            recorded_decision_cls: The RecordedDecision class for deserialization
            
        Returns:
            ReplayReport instance
        """
        # Parse timestamps
        run_at = data.get("run_at")
        if isinstance(run_at, str):
            run_at = datetime.fromisoformat(run_at.replace('Z', '+00:00'))
        
        start_time = data.get("start_time")
        if isinstance(start_time, str):
            start_time = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
        
        end_time = data.get("end_time")
        if isinstance(end_time, str):
            end_time = datetime.fromisoformat(end_time.replace('Z', '+00:00'))
        
        # Parse sample changes
        sample_changes = [
            ReplayResult.from_dict(r, recorded_decision_cls)
            for r in data.get("sample_changes", [])
        ]
        
        return cls(
            total_replayed=data["total_replayed"],
            matches=data["matches"],
            changes=data["changes"],
            match_rate=data["match_rate"],
            changes_by_category=data.get("changes_by_category", {}),
            changes_by_stage=data.get("changes_by_stage", {}),
            sample_changes=sample_changes,
            run_id=data.get("run_id"),
            run_at=run_at,
            start_time=start_time,
            end_time=end_time,
        )
    
    def to_db_tuple(self) -> tuple:
        """Convert to tuple for database insertion.
        
        Returns:
            Tuple of values in database column order for replay_validations table
        """
        return (
            self.run_id,
            self.run_at,
            self.start_time,
            self.end_time,
            self.total_replayed,
            self.matches,
            self.changes,
            self.match_rate,
            json.dumps(self.changes_by_category) if self.changes_by_category else None,
            json.dumps(self.changes_by_stage) if self.changes_by_stage else None,
        )
    
    @classmethod
    def from_db_row(cls, row) -> "ReplayReport":
        """Create ReplayReport from database row.
        
        Note: This does not restore sample_changes as they are not stored
        in the replay_validations table.
        
        Args:
            row: Database row from asyncpg
            
        Returns:
            ReplayReport instance
        """
        # Parse JSON fields
        def parse_json(value, default):
            if value is None:
                return default
            if isinstance(value, dict):
                return value
            try:
                return json.loads(value)
            except (json.JSONDecodeError, TypeError):
                return default
        
        # Ensure timestamps have timezone info
        def ensure_tz(ts):
            if ts is None:
                return None
            if ts.tzinfo is None:
                return ts.replace(tzinfo=timezone.utc)
            return ts
        
        return cls(
            total_replayed=row["total_replayed"],
            matches=row["matches"],
            changes=row["changes"],
            match_rate=row["match_rate"],
            changes_by_category=parse_json(row.get("changes_by_category"), {}),
            changes_by_stage=parse_json(row.get("changes_by_stage"), {}),
            sample_changes=[],  # Not stored in DB
            run_id=row.get("run_id"),
            run_at=ensure_tz(row.get("run_at")),
            start_time=ensure_tz(row.get("start_time")),
            end_time=ensure_tz(row.get("end_time")),
        )
    
    def has_degradations(self) -> bool:
        """Check if any changes are degradations.
        
        Returns:
            True if there are any degraded changes
        """
        return self.changes_by_category.get("degraded", 0) > 0
    
    def has_improvements(self) -> bool:
        """Check if any changes are improvements.
        
        Returns:
            True if there are any improved changes
        """
        return self.changes_by_category.get("improved", 0) > 0
    
    def has_unexpected_changes(self) -> bool:
        """Check if any changes are unexpected.
        
        Returns:
            True if there are any unexpected changes
        """
        return self.changes_by_category.get("unexpected", 0) > 0
    
    def get_degradation_count(self) -> int:
        """Get the count of degraded changes.
        
        Returns:
            Number of degraded changes
        """
        return self.changes_by_category.get("degraded", 0)
    
    def get_improvement_count(self) -> int:
        """Get the count of improved changes.
        
        Returns:
            Number of improved changes
        """
        return self.changes_by_category.get("improved", 0)
    
    def get_unexpected_count(self) -> int:
        """Get the count of unexpected changes.
        
        Returns:
            Number of unexpected changes
        """
        return self.changes_by_category.get("unexpected", 0)
    
    def get_expected_count(self) -> int:
        """Get the count of expected changes.
        
        Returns:
            Number of expected changes
        """
        return self.changes_by_category.get("expected", 0)
    
    def is_passing(self, max_degradation_rate: float = 0.05) -> bool:
        """Check if the replay validation passes.
        
        A replay validation passes if the degradation rate is below the
        specified threshold.
        
        Args:
            max_degradation_rate: Maximum allowed degradation rate (default: 5%)
            
        Returns:
            True if the replay validation passes
        """
        if self.total_replayed == 0:
            return True
        
        degradation_rate = self.get_degradation_count() / self.total_replayed
        return degradation_rate <= max_degradation_rate
    
    def get_summary(self) -> str:
        """Get a human-readable summary of the replay report.
        
        Returns:
            Summary string
        """
        lines = [
            f"Replay Report (run_id: {self.run_id or 'N/A'})",
            f"  Total replayed: {self.total_replayed}",
            f"  Matches: {self.matches} ({self.match_rate:.1%})",
            f"  Changes: {self.changes}",
        ]
        
        if self.changes_by_category:
            lines.append("  Changes by category:")
            for category, count in sorted(self.changes_by_category.items()):
                lines.append(f"    - {category}: {count}")
        
        if self.changes_by_stage:
            lines.append("  Changes by stage:")
            for stage_diff, count in sorted(self.changes_by_stage.items()):
                lines.append(f"    - {stage_diff}: {count}")
        
        return "\n".join(lines)
    
    @classmethod
    def create_empty(cls, run_id: Optional[str] = None) -> "ReplayReport":
        """Create an empty replay report.
        
        Useful for cases where no decisions were replayed.
        
        Args:
            run_id: Optional run identifier
            
        Returns:
            Empty ReplayReport instance
        """
        return cls(
            total_replayed=0,
            matches=0,
            changes=0,
            match_rate=1.0,  # 100% match rate when nothing to compare
            changes_by_category={},
            changes_by_stage={},
            sample_changes=[],
            run_id=run_id,
            run_at=datetime.now(timezone.utc),
        )
    
    def validate(self) -> tuple[bool, List[str]]:
        """Validate the replay report for consistency.
        
        Returns:
            Tuple of (is_valid, list of error messages)
        """
        errors = []
        
        # Check totals
        if self.matches + self.changes != self.total_replayed:
            errors.append(
                f"matches ({self.matches}) + changes ({self.changes}) != "
                f"total_replayed ({self.total_replayed})"
            )
        
        # Check match rate calculation
        if self.total_replayed > 0:
            expected_rate = self.matches / self.total_replayed
            if abs(self.match_rate - expected_rate) > 0.001:
                errors.append(
                    f"match_rate ({self.match_rate}) doesn't match "
                    f"calculated rate ({expected_rate})"
                )
        
        # Check category totals
        category_total = sum(self.changes_by_category.values())
        if category_total != self.changes:
            errors.append(
                f"sum of changes_by_category ({category_total}) != "
                f"changes ({self.changes})"
            )
        
        return len(errors) == 0, errors


# Protocol imports for type checking
from typing import Protocol


class DecisionEngineProtocol(Protocol):
    """Protocol for decision engine used in replay validation."""
    
    async def decide_with_context(
        self, decision_input: Any
    ) -> tuple[bool, Any]:
        """Run decision pipeline and return result with context."""
        ...


class ConfigurationRegistryProtocol(Protocol):
    """Protocol for configuration registry used in replay validation."""
    
    async def get_live_config(self) -> Any:
        """Get current live configuration."""
        ...


class ReplayManager:
    """Replays historical decisions for validation.
    
    The ReplayManager enables validation of pipeline changes by replaying
    recorded decisions through the current pipeline and comparing outcomes.
    This is essential for CI/CD validation and regression testing.
    
    Feature: trading-pipeline-integration
    Requirements: 7.1 - THE System SHALL support replaying recorded decision events
                  through the current pipeline
    Requirements: 7.5 - THE System SHALL support filtering replay by time range,
                  symbol, and decision type
    
    Attributes:
        _pool: asyncpg connection pool for TimescaleDB
        _engine: DecisionEngine for replaying decisions
        _config_registry: ConfigurationRegistry for config versioning
    
    Example:
        >>> manager = ReplayManager(pool, decision_engine, config_registry)
        >>> report = await manager.replay_range(
        ...     start_time=datetime(2024, 1, 1, tzinfo=timezone.utc),
        ...     end_time=datetime(2024, 1, 2, tzinfo=timezone.utc),
        ...     symbol="BTCUSDT",
        ...     decision_filter="rejected",
        ... )
        >>> print(f"Match rate: {report.match_rate:.1%}")
    """
    
    def __init__(
        self,
        timescale_pool,
        decision_engine: DecisionEngineProtocol,
        config_registry: ConfigurationRegistryProtocol,
    ) -> None:
        """Initialize the ReplayManager.
        
        Args:
            timescale_pool: asyncpg connection pool for TimescaleDB
            decision_engine: DecisionEngine for replaying decisions
            config_registry: ConfigurationRegistry for config versioning
        """
        self._pool = timescale_pool
        self._engine = decision_engine
        self._config_registry = config_registry
    
    async def replay_range(
        self,
        start_time: datetime,
        end_time: datetime,
        symbol: Optional[str] = None,
        decision_filter: Optional[str] = None,  # "accepted", "rejected"
        max_decisions: int = 10000,
    ) -> ReplayReport:
        """Replay decisions in a time range.
        
        Loads recorded decisions from the database and replays them through
        the current pipeline, comparing outcomes to detect changes.
        
        Feature: trading-pipeline-integration
        Requirements: 7.1, 7.5
        
        Args:
            start_time: Start of replay range (inclusive)
            end_time: End of replay range (inclusive)
            symbol: Optional symbol filter (e.g., "BTCUSDT")
            decision_filter: Optional decision outcome filter ("accepted", "rejected")
            max_decisions: Maximum decisions to replay (default: 10000)
            
        Returns:
            ReplayReport with comparison results and statistics
            
        Raises:
            ValueError: If decision_filter is not a valid value
            
        Example:
            >>> report = await manager.replay_range(
            ...     start_time=datetime(2024, 1, 1, tzinfo=timezone.utc),
            ...     end_time=datetime(2024, 1, 2, tzinfo=timezone.utc),
            ...     symbol="BTCUSDT",
            ... )
        """
        # Validate decision_filter if provided
        if decision_filter is not None and decision_filter not in ("accepted", "rejected"):
            raise ValueError(
                f"decision_filter must be 'accepted' or 'rejected', got '{decision_filter}'"
            )
        
        # Ensure timestamps have timezone info
        if start_time.tzinfo is None:
            start_time = start_time.replace(tzinfo=timezone.utc)
        if end_time.tzinfo is None:
            end_time = end_time.replace(tzinfo=timezone.utc)
        
        # Generate unique run_id for this replay run
        from uuid import uuid4
        run_id = f"replay_{uuid4().hex[:12]}"
        
        # Load decisions from database
        decisions = await self._load_decisions(
            start_time, end_time, symbol, decision_filter, max_decisions
        )
        
        # Handle empty result case
        if not decisions:
            return ReplayReport.create_empty(run_id=run_id)
        
        results: List[ReplayResult] = []
        
        for decision in decisions:
            result = await self._replay_single(decision)
            results.append(result)
        
        # Aggregate results using helper function
        matches = sum(1 for r in results if r.matches)
        changes_by_category, changes_by_stage = aggregate_changes(results)
        
        # Sample some changes for review (first 10)
        sample_changes = [r for r in results if not r.matches][:10]
        
        return ReplayReport(
            total_replayed=len(results),
            matches=matches,
            changes=len(results) - matches,
            match_rate=matches / len(results) if results else 1.0,
            changes_by_category=changes_by_category,
            changes_by_stage=changes_by_stage,
            sample_changes=sample_changes,
            run_id=run_id,
            run_at=datetime.now(timezone.utc),
            start_time=start_time,
            end_time=end_time,
        )
    
    async def _replay_single(self, decision: "RecordedDecision") -> ReplayResult:
        """Replay a single decision.
        
        Reconstructs the DecisionInput from the recorded decision and runs it
        through the current pipeline, comparing the outcome.
        
        Feature: trading-pipeline-integration
        Requirements: 7.1, 7.2
        
        Args:
            decision: The RecordedDecision to replay
            
        Returns:
            ReplayResult with comparison details
        """
        # Reconstruct decision input from recorded data
        decision_input = self._reconstruct_input(decision)
        
        # Run through current pipeline
        result, ctx = await self._engine.decide_with_context(decision_input)
        
        replayed_decision = "accepted" if result else "rejected"
        matches = replayed_decision == decision.decision
        
        # Categorize change using helper function
        change_category = categorize_change(decision.decision, replayed_decision)
        
        # Identify stage difference using helper function
        replayed_rejection_stage = getattr(ctx, 'rejection_stage', None)
        stage_diff = identify_stage_diff(decision.rejection_stage, replayed_rejection_stage)
        
        # Extract signal from context
        replayed_signal = getattr(ctx, 'signal', None)
        
        return ReplayResult(
            original_decision=decision,
            replayed_decision=replayed_decision,
            replayed_signal=replayed_signal,
            replayed_rejection_stage=replayed_rejection_stage,
            matches=matches,
            change_category=change_category,
            stage_diff=stage_diff,
        )
    
    def _reconstruct_input(self, decision: "RecordedDecision") -> Any:
        """Rebuild DecisionInput from recorded decision.
        
        Reconstructs the DecisionInput object from the recorded decision's
        stored context, enabling replay through the current pipeline.
        
        Feature: trading-pipeline-integration
        Requirements: 7.1
        
        Args:
            decision: The RecordedDecision to reconstruct input from
            
        Returns:
            DecisionInput object ready for pipeline execution
        """
        # Import DecisionInput here to avoid circular imports
        from quantgambit.signals.decision_engine import DecisionInput
        
        # Extract market context from market_snapshot
        market_context = decision.market_snapshot.copy() if decision.market_snapshot else {}
        
        # Extract features
        features = decision.features.copy() if decision.features else {}
        
        # Extract account state
        account_state = decision.account_state.copy() if decision.account_state else {}
        
        # Extract positions
        positions = decision.positions.copy() if decision.positions else []
        
        # Extract prediction from features if present
        prediction = features.pop("prediction", None)
        
        # Extract expected_bps and expected_fee_usd if present in features
        expected_bps = features.pop("expected_bps", None)
        expected_fee_usd = features.pop("expected_fee_usd", None)
        
        # Extract risk_ok from features if present
        risk_ok = features.pop("risk_ok", True)
        
        # Extract profile_settings from features if present
        profile_settings = features.pop("profile_settings", None)
        
        # Extract risk_limits from features if present
        risk_limits = features.pop("risk_limits", None)
        
        return DecisionInput(
            symbol=decision.symbol,
            market_context=market_context,
            features=features,
            account_state=account_state,
            positions=positions,
            risk_limits=risk_limits,
            profile_settings=profile_settings,
            prediction=prediction,
            rejection_reason=None,  # Clear rejection reason for replay
            expected_bps=expected_bps,
            expected_fee_usd=expected_fee_usd,
            risk_ok=risk_ok,
        )
    
    async def _load_decisions(
        self,
        start_time: datetime,
        end_time: datetime,
        symbol: Optional[str],
        decision_filter: Optional[str],
        max_decisions: int,
    ) -> List["RecordedDecision"]:
        """Load recorded decisions from database.
        
        Queries the recorded_decisions table for decisions within the specified
        time range, with optional filtering by symbol and decision outcome.
        
        Feature: trading-pipeline-integration
        Requirements: 7.5
        
        Args:
            start_time: Start of time range (inclusive)
            end_time: End of time range (inclusive)
            symbol: Optional filter by trading symbol
            decision_filter: Optional filter by decision outcome
            max_decisions: Maximum number of decisions to load
            
        Returns:
            List of RecordedDecision objects matching the filters
        """
        # Import RecordedDecision here to avoid circular imports at module level
        from quantgambit.integration.decision_recording import RecordedDecision
        
        # Build query with dynamic filters
        query_parts = [
            "SELECT * FROM recorded_decisions",
            "WHERE timestamp >= $1 AND timestamp <= $2",
        ]
        params: List[Any] = [start_time, end_time]
        param_idx = 3
        
        if symbol is not None:
            query_parts.append(f"AND symbol = ${param_idx}")
            params.append(symbol)
            param_idx += 1
        
        if decision_filter is not None:
            query_parts.append(f"AND decision = ${param_idx}")
            params.append(decision_filter)
            param_idx += 1
        
        # Order by timestamp for consistent replay order
        query_parts.append("ORDER BY timestamp ASC")
        query_parts.append(f"LIMIT ${param_idx}")
        params.append(max_decisions)
        
        query = " ".join(query_parts)
        
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(query, *params)
            return [RecordedDecision.from_db_row(row) for row in rows]
    
    async def save_report(self, report: ReplayReport) -> None:
        """Save a replay report to the database.
        
        Persists the replay report to the replay_validations table for
        historical tracking and analysis.
        
        Args:
            report: The ReplayReport to save
        """
        async with self._pool.acquire() as conn:
            # replay_validations schema uses SERIAL primary key and does not
            # guarantee UNIQUE(run_id) across all deployments. Persist safely
            # by replacing existing rows for this run_id before insert.
            await conn.execute(
                "DELETE FROM replay_validations WHERE run_id = $1",
                report.run_id,
            )
            await conn.execute(
                """
                INSERT INTO replay_validations (
                    run_id, run_at, start_time, end_time,
                    total_replayed, matches, changes, match_rate,
                    changes_by_category, changes_by_stage
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                """,
                *report.to_db_tuple(),
            )
    
    async def get_report(self, run_id: str) -> Optional[ReplayReport]:
        """Get a replay report by run_id.
        
        Retrieves a previously saved replay report from the database.
        
        Args:
            run_id: The unique identifier of the replay run
            
        Returns:
            ReplayReport if found, None otherwise
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT * FROM replay_validations
                WHERE run_id = $1
                """,
                run_id
            )
            
            if row is None:
                return None
            
            return ReplayReport.from_db_row(row)
    
    async def list_reports(
        self,
        limit: int = 100,
        offset: int = 0,
    ) -> List[ReplayReport]:
        """List recent replay reports.
        
        Retrieves a paginated list of replay reports, ordered by run_at
        descending (most recent first).
        
        Args:
            limit: Maximum number of reports to return (default: 100)
            offset: Number of reports to skip (default: 0)
            
        Returns:
            List of ReplayReport objects
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT * FROM replay_validations
                ORDER BY run_at DESC
                LIMIT $1 OFFSET $2
                """,
                limit, offset
            )
            
            return [ReplayReport.from_db_row(row) for row in rows]
