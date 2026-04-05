"""Loss Prevention Metrics - Aggregated metrics for loss prevention dashboard.

This module provides metrics aggregation for the loss prevention system,
tracking rejected signals and estimating losses avoided.

Requirements: 8.2, 8.4, 8.5
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from quantgambit.observability.logger import log_info

if TYPE_CHECKING:
    from quantgambit.observability.blocked_signal_telemetry import BlockedSignalRepository


# Default average loss per trade (USD) - used when historical data unavailable
DEFAULT_AVG_LOSS_PER_TRADE_USD = 15.0


@dataclass
class LossPreventionMetrics:
    """Aggregated metrics for the loss prevention dashboard.
    
    This dataclass captures all metrics needed for the Loss Prevention panel
    as specified in Requirements 8.2 and 8.5.
    
    Attributes:
        total_signals_rejected: Total count of rejected signals in the time window
        rejection_breakdown: Dict mapping rejection_reason -> count
        estimated_losses_avoided_usd: Estimated USD saved by rejecting signals
        average_loss_per_trade_usd: Average loss per trade from historical data
        
        # Per-reason counts (for quick access)
        low_confidence_count: Count of signals rejected for low confidence
        strategy_trend_mismatch_count: Count of signals rejected for strategy-trend mismatch
        fee_trap_count: Count of signals rejected as fee traps
        session_mismatch_count: Count of signals rejected for session mismatch
        
        # Time window
        window_start: Start of the metrics window (Unix timestamp)
        window_end: End of the metrics window (Unix timestamp)
    
    Requirements: 8.2, 8.5
    """
    total_signals_rejected: int
    rejection_breakdown: Dict[str, int]
    estimated_losses_avoided_usd: float
    average_loss_per_trade_usd: float
    
    # Per-reason counts
    low_confidence_count: int = 0
    strategy_trend_mismatch_count: int = 0
    fee_trap_count: int = 0
    session_mismatch_count: int = 0
    
    # Time window
    window_start: float = 0.0
    window_end: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)
    
    @classmethod
    def empty(cls, window_hours: float = 24.0) -> "LossPreventionMetrics":
        """Create an empty metrics instance with default values.
        
        Args:
            window_hours: Time window in hours (default: 24)
        
        Returns:
            LossPreventionMetrics with zero counts
        """
        now = time.time()
        return cls(
            total_signals_rejected=0,
            rejection_breakdown={},
            estimated_losses_avoided_usd=0.0,
            average_loss_per_trade_usd=DEFAULT_AVG_LOSS_PER_TRADE_USD,
            low_confidence_count=0,
            strategy_trend_mismatch_count=0,
            fee_trap_count=0,
            session_mismatch_count=0,
            window_start=now - (window_hours * 3600),
            window_end=now,
        )


class LossPreventionMetricsAggregator:
    """Aggregates loss prevention metrics from blocked signals.
    
    This class queries the blocked_signals table and calculates:
    1. Total signals rejected by reason
    2. Estimated losses avoided based on historical average loss per trade
    
    Requirements: 8.4
    """
    
    def __init__(
        self,
        repository: Optional["BlockedSignalRepository"] = None,
        avg_loss_per_trade_usd: float = DEFAULT_AVG_LOSS_PER_TRADE_USD,
    ):
        """Initialize LossPreventionMetricsAggregator.
        
        Args:
            repository: BlockedSignalRepository for querying blocked signals
            avg_loss_per_trade_usd: Average loss per trade for estimation
        """
        self._repository = repository
        self._avg_loss_per_trade_usd = avg_loss_per_trade_usd
    
    def set_avg_loss_per_trade(self, avg_loss_usd: float) -> None:
        """Update the average loss per trade value.
        
        Args:
            avg_loss_usd: New average loss per trade in USD
        """
        if avg_loss_usd > 0:
            self._avg_loss_per_trade_usd = avg_loss_usd
    
    async def get_metrics(
        self,
        window_hours: float = 24.0,
    ) -> LossPreventionMetrics:
        """Get aggregated loss prevention metrics.
        
        Args:
            window_hours: Time window in hours (default: 24)
        
        Returns:
            LossPreventionMetrics with aggregated data
        
        Requirements: 8.4
        """
        now = time.time()
        window_start = now - (window_hours * 3600)
        
        # Get counts by reason from repository
        if self._repository:
            counts_by_reason = await self._repository.get_counts_by_reason()
        else:
            counts_by_reason = {}
        
        # Calculate total rejected
        total_rejected = sum(counts_by_reason.values())
        
        # Calculate estimated losses avoided
        # Formula: count × avg_loss_per_trade (Requirement 8.4)
        estimated_losses_avoided = total_rejected * self._avg_loss_per_trade_usd
        
        # Extract per-reason counts
        low_confidence_count = (
            counts_by_reason.get("low_confidence", 0) +
            counts_by_reason.get("confidence_gate", 0)
        )
        strategy_trend_mismatch_count = counts_by_reason.get("strategy_trend_mismatch", 0)
        fee_trap_count = counts_by_reason.get("fee_trap", 0)
        session_mismatch_count = counts_by_reason.get("session_mismatch", 0)
        
        return LossPreventionMetrics(
            total_signals_rejected=total_rejected,
            rejection_breakdown=counts_by_reason,
            estimated_losses_avoided_usd=estimated_losses_avoided,
            average_loss_per_trade_usd=self._avg_loss_per_trade_usd,
            low_confidence_count=low_confidence_count,
            strategy_trend_mismatch_count=strategy_trend_mismatch_count,
            fee_trap_count=fee_trap_count,
            session_mismatch_count=session_mismatch_count,
            window_start=window_start,
            window_end=now,
        )
    
    def get_metrics_sync(
        self,
        counts_by_reason: Dict[str, int],
        window_hours: float = 24.0,
    ) -> LossPreventionMetrics:
        """Get aggregated loss prevention metrics synchronously.
        
        This method is useful when counts are already available
        (e.g., from in-memory storage or cached data).
        
        Args:
            counts_by_reason: Dict mapping rejection_reason -> count
            window_hours: Time window in hours (default: 24)
        
        Returns:
            LossPreventionMetrics with aggregated data
        
        Requirements: 8.4
        """
        now = time.time()
        window_start = now - (window_hours * 3600)
        
        # Calculate total rejected
        total_rejected = sum(counts_by_reason.values())
        
        # Calculate estimated losses avoided
        # Formula: count × avg_loss_per_trade (Requirement 8.4)
        estimated_losses_avoided = total_rejected * self._avg_loss_per_trade_usd
        
        # Extract per-reason counts
        low_confidence_count = (
            counts_by_reason.get("low_confidence", 0) +
            counts_by_reason.get("confidence_gate", 0)
        )
        strategy_trend_mismatch_count = counts_by_reason.get("strategy_trend_mismatch", 0)
        fee_trap_count = counts_by_reason.get("fee_trap", 0)
        session_mismatch_count = counts_by_reason.get("session_mismatch", 0)
        
        return LossPreventionMetrics(
            total_signals_rejected=total_rejected,
            rejection_breakdown=counts_by_reason,
            estimated_losses_avoided_usd=estimated_losses_avoided,
            average_loss_per_trade_usd=self._avg_loss_per_trade_usd,
            low_confidence_count=low_confidence_count,
            strategy_trend_mismatch_count=strategy_trend_mismatch_count,
            fee_trap_count=fee_trap_count,
            session_mismatch_count=session_mismatch_count,
            window_start=window_start,
            window_end=now,
        )
    
    @staticmethod
    def calculate_estimated_losses_avoided(
        rejected_count: int,
        avg_loss_per_trade: float,
    ) -> float:
        """Calculate estimated losses avoided.
        
        Formula: rejected_count × avg_loss_per_trade
        
        Args:
            rejected_count: Number of rejected signals
            avg_loss_per_trade: Average loss per trade in USD
        
        Returns:
            Estimated losses avoided in USD
        
        Requirements: 8.4
        """
        return rejected_count * avg_loss_per_trade
