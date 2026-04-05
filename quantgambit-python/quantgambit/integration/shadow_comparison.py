"""Shadow comparison data structures for trading pipeline integration.

This module provides the ComparisonResult and ComparisonMetrics dataclasses
for comparing live and shadow pipeline decisions in real-time, as well as
the ShadowComparator class for running both pipelines and comparing decisions.

Feature: trading-pipeline-integration
Requirements: 4.1 - THE System SHALL support running a shadow pipeline that
              processes live market data through an alternative configuration
Requirements: 4.2 - WHEN shadow mode is enabled THEN the System SHALL record
              both live and shadow decisions for each market event
Requirements: 4.3 - THE System SHALL compute decision agreement rate between
              live and shadow pipelines
Requirements: 4.4 - WHEN live and shadow decisions differ THEN the System SHALL
              log the difference with full context
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Protocol, TYPE_CHECKING

if TYPE_CHECKING:
    from quantgambit.observability.telemetry import TelemetryPipeline


class StageContextProtocol(Protocol):
    """Protocol for stage context objects used in shadow comparison."""
    
    @property
    def rejection_stage(self) -> Optional[str]:
        """Stage that rejected the decision, if any."""
        ...
    
    @property
    def profile_id(self) -> Optional[str]:
        """Profile ID used for the decision."""
        ...
    
    @property
    def signal(self) -> Optional[Dict[str, Any]]:
        """Signal details if decision was accepted."""
        ...


class DecisionEngineProtocol(Protocol):
    """Protocol for decision engine used in shadow comparison."""
    
    async def decide_with_context(
        self, decision_input: Any
    ) -> tuple[bool, StageContextProtocol]:
        """Run decision pipeline and return result with context."""
        ...


class DecisionInputProtocol(Protocol):
    """Protocol for decision input used in shadow comparison."""
    
    @property
    def symbol(self) -> str:
        """Trading symbol for the decision."""
        ...


@dataclass
class ComparisonResult:
    """Result of comparing live vs shadow decision.
    
    Represents the outcome of running both live and shadow pipelines on the
    same market event and comparing their decisions. This enables real-time
    validation of strategy changes before deployment.
    
    Feature: trading-pipeline-integration
    Requirements: 4.2, 4.3
    
    Attributes:
        timestamp: When the comparison was made
        symbol: Trading symbol (e.g., "BTCUSDT")
        live_decision: Decision from live pipeline ("accepted" or "rejected")
        shadow_decision: Decision from shadow pipeline ("accepted" or "rejected")
        agrees: True if live_decision == shadow_decision
        divergence_reason: Reason for divergence if decisions differ
        live_signal: Signal details from live pipeline (if accepted)
        shadow_signal: Signal details from shadow pipeline (if accepted)
        live_rejection_stage: Stage that rejected in live pipeline (if rejected)
        shadow_rejection_stage: Stage that rejected in shadow pipeline (if rejected)
        live_config_version: Configuration version used by live pipeline
        shadow_config_version: Configuration version used by shadow pipeline
    """
    timestamp: datetime
    symbol: str
    live_decision: str
    shadow_decision: str
    agrees: bool
    divergence_reason: Optional[str] = None
    live_signal: Optional[Dict[str, Any]] = None
    shadow_signal: Optional[Dict[str, Any]] = None
    live_rejection_stage: Optional[str] = None
    shadow_rejection_stage: Optional[str] = None
    live_config_version: Optional[str] = None
    shadow_config_version: Optional[str] = None
    
    def __post_init__(self) -> None:
        """Validate the ComparisonResult after initialization."""
        if not self.symbol:
            raise ValueError("symbol cannot be empty")
        if self.live_decision not in ("accepted", "rejected"):
            raise ValueError(
                f"live_decision must be 'accepted' or 'rejected', got '{self.live_decision}'"
            )
        if self.shadow_decision not in ("accepted", "rejected"):
            raise ValueError(
                f"shadow_decision must be 'accepted' or 'rejected', got '{self.shadow_decision}'"
            )
        
        # Ensure timestamp has timezone info
        if self.timestamp.tzinfo is None:
            object.__setattr__(
                self,
                'timestamp',
                self.timestamp.replace(tzinfo=timezone.utc)
            )
        
        # Auto-compute agrees if not explicitly set correctly
        expected_agrees = self.live_decision == self.shadow_decision
        if self.agrees != expected_agrees:
            object.__setattr__(self, 'agrees', expected_agrees)
    
    @classmethod
    def create(
        cls,
        timestamp: datetime,
        symbol: str,
        live_decision: str,
        shadow_decision: str,
        divergence_reason: Optional[str] = None,
        live_signal: Optional[Dict[str, Any]] = None,
        shadow_signal: Optional[Dict[str, Any]] = None,
        live_rejection_stage: Optional[str] = None,
        shadow_rejection_stage: Optional[str] = None,
        live_config_version: Optional[str] = None,
        shadow_config_version: Optional[str] = None,
    ) -> "ComparisonResult":
        """Factory method to create a ComparisonResult with auto-computed agrees.
        
        This is the preferred way to create ComparisonResult instances as it
        automatically computes the agrees field based on the decisions.
        
        Args:
            timestamp: When the comparison was made
            symbol: Trading symbol (e.g., "BTCUSDT")
            live_decision: Decision from live pipeline ("accepted" or "rejected")
            shadow_decision: Decision from shadow pipeline ("accepted" or "rejected")
            divergence_reason: Reason for divergence if decisions differ
            live_signal: Signal details from live pipeline (if accepted)
            shadow_signal: Signal details from shadow pipeline (if accepted)
            live_rejection_stage: Stage that rejected in live pipeline (if rejected)
            shadow_rejection_stage: Stage that rejected in shadow pipeline (if rejected)
            live_config_version: Configuration version used by live pipeline
            shadow_config_version: Configuration version used by shadow pipeline
            
        Returns:
            ComparisonResult instance with agrees auto-computed
        """
        agrees = live_decision == shadow_decision
        return cls(
            timestamp=timestamp,
            symbol=symbol,
            live_decision=live_decision,
            shadow_decision=shadow_decision,
            agrees=agrees,
            divergence_reason=divergence_reason,
            live_signal=live_signal,
            shadow_signal=shadow_signal,
            live_rejection_stage=live_rejection_stage,
            shadow_rejection_stage=shadow_rejection_stage,
            live_config_version=live_config_version,
            shadow_config_version=shadow_config_version,
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization.
        
        Returns:
            Dictionary representation of the ComparisonResult
        """
        return {
            "timestamp": self.timestamp.isoformat(),
            "symbol": self.symbol,
            "live_decision": self.live_decision,
            "shadow_decision": self.shadow_decision,
            "agrees": self.agrees,
            "divergence_reason": self.divergence_reason,
            "live_signal": self.live_signal,
            "shadow_signal": self.shadow_signal,
            "live_rejection_stage": self.live_rejection_stage,
            "shadow_rejection_stage": self.shadow_rejection_stage,
            "live_config_version": self.live_config_version,
            "shadow_config_version": self.shadow_config_version,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ComparisonResult":
        """Create ComparisonResult from dictionary.
        
        Args:
            data: Dictionary with ComparisonResult fields
            
        Returns:
            ComparisonResult instance
        """
        timestamp = data["timestamp"]
        if isinstance(timestamp, str):
            # Parse ISO format string
            timestamp = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
        
        return cls(
            timestamp=timestamp,
            symbol=data["symbol"],
            live_decision=data["live_decision"],
            shadow_decision=data["shadow_decision"],
            agrees=data["agrees"],
            divergence_reason=data.get("divergence_reason"),
            live_signal=data.get("live_signal"),
            shadow_signal=data.get("shadow_signal"),
            live_rejection_stage=data.get("live_rejection_stage"),
            shadow_rejection_stage=data.get("shadow_rejection_stage"),
            live_config_version=data.get("live_config_version"),
            shadow_config_version=data.get("shadow_config_version"),
        )
    
    def to_db_tuple(self) -> tuple:
        """Convert to tuple for database insertion.
        
        Returns:
            Tuple of values in database column order for executemany
        """
        return (
            self.timestamp,
            self.symbol,
            self.live_decision,
            self.shadow_decision,
            self.agrees,
            self.divergence_reason,
            self.live_config_version,
            self.shadow_config_version,
        )
    
    @classmethod
    def from_db_row(cls, row) -> "ComparisonResult":
        """Create ComparisonResult from database row.
        
        Args:
            row: Database row from asyncpg
            
        Returns:
            ComparisonResult instance
        """
        # Ensure timestamp has timezone info
        timestamp = row["timestamp"]
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        
        return cls(
            timestamp=timestamp,
            symbol=row["symbol"],
            live_decision=row["live_decision"],
            shadow_decision=row["shadow_decision"],
            agrees=row["agrees"],
            divergence_reason=row.get("divergence_reason"),
            live_signal=None,  # Not stored in DB
            shadow_signal=None,  # Not stored in DB
            live_rejection_stage=None,  # Not stored in DB
            shadow_rejection_stage=None,  # Not stored in DB
            live_config_version=row.get("live_config_version"),
            shadow_config_version=row.get("shadow_config_version"),
        )
    
    def is_agreement(self) -> bool:
        """Check if live and shadow decisions agree.
        
        Returns:
            True if decisions agree
        """
        return self.agrees
    
    def is_divergence(self) -> bool:
        """Check if live and shadow decisions diverge.
        
        Returns:
            True if decisions diverge
        """
        return not self.agrees


@dataclass
class ComparisonMetrics:
    """Aggregated comparison metrics for shadow mode.
    
    Provides summary statistics for comparing live and shadow pipeline
    decisions over a window of comparisons. Used for monitoring shadow
    mode performance and detecting systematic divergence.
    
    Feature: trading-pipeline-integration
    Requirements: 4.3
    
    Attributes:
        total_comparisons: Total number of comparisons in the window
        agreements: Number of comparisons where decisions agreed
        disagreements: Number of comparisons where decisions diverged
        agreement_rate: Ratio of agreements to total (0.0 to 1.0)
        divergence_by_reason: Count of divergences by reason category
        live_pnl_estimate: Estimated P&L from live decisions
        shadow_pnl_estimate: Estimated P&L from shadow decisions
    """
    total_comparisons: int
    agreements: int
    disagreements: int
    agreement_rate: float
    divergence_by_reason: Dict[str, int] = field(default_factory=dict)
    live_pnl_estimate: float = 0.0
    shadow_pnl_estimate: float = 0.0
    
    def __post_init__(self) -> None:
        """Validate the ComparisonMetrics after initialization."""
        if self.total_comparisons < 0:
            raise ValueError("total_comparisons cannot be negative")
        if self.agreements < 0:
            raise ValueError("agreements cannot be negative")
        if self.disagreements < 0:
            raise ValueError("disagreements cannot be negative")
        if not (0.0 <= self.agreement_rate <= 1.0):
            raise ValueError(
                f"agreement_rate must be between 0.0 and 1.0, got {self.agreement_rate}"
            )
        
        # Validate consistency
        if self.total_comparisons > 0:
            expected_total = self.agreements + self.disagreements
            if expected_total != self.total_comparisons:
                raise ValueError(
                    f"agreements ({self.agreements}) + disagreements ({self.disagreements}) "
                    f"must equal total_comparisons ({self.total_comparisons})"
                )
            
            # Validate agreement_rate is consistent
            expected_rate = self.agreements / self.total_comparisons
            if abs(self.agreement_rate - expected_rate) > 0.001:
                raise ValueError(
                    f"agreement_rate ({self.agreement_rate}) is inconsistent with "
                    f"agreements/total ({expected_rate})"
                )
    
    @classmethod
    def create_empty(cls) -> "ComparisonMetrics":
        """Create empty metrics with no comparisons.
        
        Returns:
            ComparisonMetrics with zero comparisons and 1.0 agreement rate
        """
        return cls(
            total_comparisons=0,
            agreements=0,
            disagreements=0,
            agreement_rate=1.0,
            divergence_by_reason={},
            live_pnl_estimate=0.0,
            shadow_pnl_estimate=0.0,
        )
    
    @classmethod
    def from_comparisons(
        cls,
        comparisons: list["ComparisonResult"],
        live_pnl_estimate: float = 0.0,
        shadow_pnl_estimate: float = 0.0,
    ) -> "ComparisonMetrics":
        """Create metrics from a list of comparison results.
        
        Aggregates a list of ComparisonResult objects into summary metrics.
        
        Args:
            comparisons: List of ComparisonResult objects
            live_pnl_estimate: Estimated P&L from live decisions
            shadow_pnl_estimate: Estimated P&L from shadow decisions
            
        Returns:
            ComparisonMetrics with aggregated statistics
        """
        if not comparisons:
            return cls.create_empty()
        
        total = len(comparisons)
        agreements = sum(1 for c in comparisons if c.agrees)
        disagreements = total - agreements
        
        # Aggregate divergence reasons
        divergence_by_reason: Dict[str, int] = {}
        for c in comparisons:
            if c.divergence_reason:
                divergence_by_reason[c.divergence_reason] = (
                    divergence_by_reason.get(c.divergence_reason, 0) + 1
                )
        
        return cls(
            total_comparisons=total,
            agreements=agreements,
            disagreements=disagreements,
            agreement_rate=agreements / total,
            divergence_by_reason=divergence_by_reason,
            live_pnl_estimate=live_pnl_estimate,
            shadow_pnl_estimate=shadow_pnl_estimate,
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization.
        
        Returns:
            Dictionary representation of the ComparisonMetrics
        """
        return {
            "total_comparisons": self.total_comparisons,
            "agreements": self.agreements,
            "disagreements": self.disagreements,
            "agreement_rate": self.agreement_rate,
            "divergence_by_reason": self.divergence_by_reason,
            "live_pnl_estimate": self.live_pnl_estimate,
            "shadow_pnl_estimate": self.shadow_pnl_estimate,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ComparisonMetrics":
        """Create ComparisonMetrics from dictionary.
        
        Args:
            data: Dictionary with ComparisonMetrics fields
            
        Returns:
            ComparisonMetrics instance
        """
        return cls(
            total_comparisons=data["total_comparisons"],
            agreements=data["agreements"],
            disagreements=data["disagreements"],
            agreement_rate=data["agreement_rate"],
            divergence_by_reason=data.get("divergence_by_reason", {}),
            live_pnl_estimate=data.get("live_pnl_estimate", 0.0),
            shadow_pnl_estimate=data.get("shadow_pnl_estimate", 0.0),
        )
    
    def divergence_rate(self) -> float:
        """Get the divergence rate (1 - agreement_rate).
        
        Returns:
            Divergence rate between 0.0 and 1.0
        """
        if self.total_comparisons > 0:
            return self.disagreements / self.total_comparisons
        return 1.0 - self.agreement_rate
    
    def exceeds_threshold(self, threshold: float = 0.20) -> bool:
        """Check if divergence rate exceeds the alert threshold.
        
        Args:
            threshold: Maximum acceptable divergence rate (default: 0.20)
            
        Returns:
            True if divergence rate exceeds threshold
        """
        return self.divergence_rate() > float(threshold)
    
    def top_divergence_reasons(self, n: int = 5) -> list[tuple[str, int]]:
        """Get the top N divergence reasons by count.
        
        Args:
            n: Number of top reasons to return
            
        Returns:
            List of (reason, count) tuples sorted by count descending
        """
        sorted_reasons = sorted(
            self.divergence_by_reason.items(),
            key=lambda x: x[1],
            reverse=True,
        )
        return sorted_reasons[:n]
    
    def pnl_difference(self) -> float:
        """Get the P&L difference between shadow and live.
        
        Returns:
            shadow_pnl_estimate - live_pnl_estimate
        """
        return self.shadow_pnl_estimate - self.live_pnl_estimate


class ShadowComparator:
    """Compares live and shadow pipeline decisions in real-time.
    
    The ShadowComparator runs both live and shadow decision engines on the same
    market data and compares their decisions. This enables validation of strategy
    changes before deployment by running them in parallel with the live system.
    
    Feature: trading-pipeline-integration
    Requirements: 4.1 - THE System SHALL support running a shadow pipeline that
                  processes live market data through an alternative configuration
    Requirements: 4.3 - THE System SHALL compute decision agreement rate between
                  live and shadow pipelines
    Requirements: 4.4 - WHEN live and shadow decisions differ THEN the System SHALL
                  log the difference with full context
    
    Attributes:
        _live_engine: The live decision engine
        _shadow_engine: The shadow decision engine with alternative configuration
        _telemetry: Optional telemetry pipeline for alert emission
        _alert_threshold: Threshold for systematic divergence alerts (default: 0.20)
        _comparisons: Rolling window of recent comparison results
        _window_size: Size of the comparison window (default: 100)
    
    Example:
        >>> comparator = ShadowComparator(
        ...     live_engine=live_engine,
        ...     shadow_engine=shadow_engine,
        ...     alert_threshold=0.20,
        ... )
        >>> result = await comparator.compare(decision_input)
        >>> metrics = comparator.get_metrics()
        >>> print(f"Agreement rate: {metrics.agreement_rate:.1%}")
    """
    
    def __init__(
        self,
        live_engine: DecisionEngineProtocol,
        shadow_engine: DecisionEngineProtocol,
        telemetry: Optional["TelemetryPipeline"] = None,
        alert_threshold: float = 0.20,  # Alert if >20% disagreement
        window_size: int = 100,
    ):
        """Initialize the ShadowComparator.
        
        Args:
            live_engine: The live decision engine
            shadow_engine: The shadow decision engine with alternative configuration
            telemetry: Optional telemetry pipeline for alert emission
            alert_threshold: Threshold for systematic divergence alerts (default: 0.20)
            window_size: Size of the comparison window (default: 100)
        """
        self._live_engine = live_engine
        self._shadow_engine = shadow_engine
        self._telemetry = telemetry
        self._alert_threshold = alert_threshold
        self._comparisons: List[ComparisonResult] = []
        self._window_size = window_size
    
    async def compare(
        self,
        decision_input: DecisionInputProtocol,
    ) -> ComparisonResult:
        """Run both pipelines and compare decisions.
        
        Executes the decision input through both live and shadow engines,
        compares the results, and records the comparison. If decisions diverge,
        identifies the reason for divergence.
        
        Feature: trading-pipeline-integration
        Requirements: 4.1, 4.3, 4.4
        
        Args:
            decision_input: The decision input to process through both pipelines
            
        Returns:
            ComparisonResult with live/shadow decisions and divergence info
        """
        # Run live pipeline
        live_result, live_ctx = await self._live_engine.decide_with_context(decision_input)
        
        # Run shadow pipeline
        shadow_result, shadow_ctx = await self._shadow_engine.decide_with_context(decision_input)
        
        # Compare results
        agrees = live_result == shadow_result
        divergence_reason = None
        
        if not agrees:
            divergence_reason = self._identify_divergence(live_ctx, shadow_ctx)
        
        result = ComparisonResult(
            timestamp=datetime.now(timezone.utc),
            symbol=decision_input.symbol,
            live_decision="accepted" if live_result else "rejected",
            shadow_decision="accepted" if shadow_result else "rejected",
            agrees=agrees,
            divergence_reason=divergence_reason,
            live_signal=live_ctx.signal,
            shadow_signal=shadow_ctx.signal,
            live_rejection_stage=live_ctx.rejection_stage,
            shadow_rejection_stage=shadow_ctx.rejection_stage,
        )
        
        self._comparisons.append(result)
        if len(self._comparisons) > self._window_size:
            self._comparisons.pop(0)
        
        # Check for systematic divergence
        await self._check_alert_threshold()
        
        return result
    
    def get_metrics(self) -> ComparisonMetrics:
        """Get aggregated comparison metrics.
        
        Computes summary statistics from the rolling window of comparisons,
        including agreement rate and divergence reasons breakdown.
        
        Feature: trading-pipeline-integration
        Requirements: 4.3
        
        Returns:
            ComparisonMetrics with aggregated statistics
        """
        if not self._comparisons:
            return ComparisonMetrics(0, 0, 0, 1.0, {}, 0.0, 0.0)
        
        agreements = sum(1 for c in self._comparisons if c.agrees)
        disagreements = len(self._comparisons) - agreements
        
        divergence_by_reason: Dict[str, int] = {}
        for c in self._comparisons:
            if c.divergence_reason:
                divergence_by_reason[c.divergence_reason] = \
                    divergence_by_reason.get(c.divergence_reason, 0) + 1
        
        return ComparisonMetrics(
            total_comparisons=len(self._comparisons),
            agreements=agreements,
            disagreements=disagreements,
            agreement_rate=agreements / len(self._comparisons),
            divergence_by_reason=divergence_by_reason,
            live_pnl_estimate=0.0,  # TODO: Calculate from signals
            shadow_pnl_estimate=0.0,
        )
    
    def _identify_divergence(
        self,
        live_ctx: StageContextProtocol,
        shadow_ctx: StageContextProtocol,
    ) -> str:
        """Identify why decisions diverged.
        
        Analyzes the stage contexts from both pipelines to determine the
        reason for divergence. Checks for differences in rejection stage
        and profile ID.
        
        Feature: trading-pipeline-integration
        Requirements: 4.4
        
        Args:
            live_ctx: Stage context from live pipeline
            shadow_ctx: Stage context from shadow pipeline
            
        Returns:
            String describing the divergence reason
        """
        if live_ctx.rejection_stage != shadow_ctx.rejection_stage:
            live_stage = live_ctx.rejection_stage or "none"
            shadow_stage = shadow_ctx.rejection_stage or "none"
            return f"stage_diff:{live_stage}vs{shadow_stage}"
        if live_ctx.profile_id != shadow_ctx.profile_id:
            live_profile = live_ctx.profile_id or "none"
            shadow_profile = shadow_ctx.profile_id or "none"
            return f"profile_diff:{live_profile}vs{shadow_profile}"
        return "unknown"
    
    async def _check_alert_threshold(self) -> None:
        """Check if divergence exceeds alert threshold.
        
        When the comparison window reaches 100 decisions and the divergence
        rate exceeds the alert threshold, emits an alert via telemetry.
        
        Feature: trading-pipeline-integration
        Requirements: 4.6 - WHEN shadow mode detects systematic divergence
                      (>20% disagreement over 100 decisions) THEN the System
                      SHALL emit an alert
        """
        metrics = self.get_metrics()
        if metrics.total_comparisons >= 100:
            if (1 - metrics.agreement_rate) > self._alert_threshold:
                if self._telemetry:
                    # Use publish_event as a generic alert mechanism
                    # The telemetry pipeline may have different alert methods
                    # depending on the implementation
                    try:
                        await self._telemetry.publish_event(
                            event_type="shadow_divergence_high",
                            payload={
                                "divergence_rate": 1 - metrics.agreement_rate,
                                "threshold": self._alert_threshold,
                                "total_comparisons": metrics.total_comparisons,
                                "divergence_by_reason": metrics.divergence_by_reason,
                                "severity": "warning",
                            },
                        )
                    except AttributeError:
                        # Telemetry pipeline may not have publish_event method
                        # This is acceptable - alerting is optional
                        pass
    
    def clear_comparisons(self) -> None:
        """Clear all stored comparisons.
        
        Useful for resetting the comparison window after configuration changes
        or when starting a new comparison session.
        """
        self._comparisons.clear()
    
    @property
    def comparison_count(self) -> int:
        """Get the current number of stored comparisons.
        
        Returns:
            Number of comparisons in the rolling window
        """
        return len(self._comparisons)
    
    @property
    def window_size(self) -> int:
        """Get the comparison window size.
        
        Returns:
            Maximum number of comparisons stored
        """
        return self._window_size
    
    @property
    def alert_threshold(self) -> float:
        """Get the alert threshold.
        
        Returns:
            Divergence rate threshold for alerts
        """
        return self._alert_threshold
