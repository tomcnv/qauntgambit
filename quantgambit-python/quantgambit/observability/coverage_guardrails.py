"""Coverage Guardrails - Metrics and alerts for mid-volatility coverage restoration.

This module provides guardrail metrics and alerts to prevent the coverage restoration
from degrading signal quality. It tracks trade count, win rate, and expectancy
over a 24-hour rolling window.

Requirements: 8.1, 8.2, 8.3
"""

from __future__ import annotations

import time
import logging
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Tuple
from collections import deque
from enum import Enum

logger = logging.getLogger(__name__)


class AlertSeverity(str, Enum):
    """Alert severity levels."""
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class AlertType(str, Enum):
    """Types of coverage guardrail alerts."""
    TRADE_COUNT_SPIKE = "trade_count_spike"
    WIN_RATE_LOW = "win_rate_low"
    EXPECTANCY_NEGATIVE = "expectancy_negative"


@dataclass(frozen=True)
class GuardrailAlert:
    """Represents a guardrail alert.
    
    Attributes:
        alert_type: Type of alert (trade_count_spike, win_rate_low, expectancy_negative)
        severity: Alert severity (warning or critical)
        message: Human-readable alert message
        current_value: Current metric value that triggered the alert
        threshold: Threshold that was breached
        metadata: Additional context about the alert
        timestamp: Unix timestamp when alert was generated
    """
    alert_type: AlertType
    severity: AlertSeverity
    message: str
    current_value: float
    threshold: float
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "alert_type": self.alert_type.value,
            "severity": self.severity.value,
            "message": self.message,
            "current_value": self.current_value,
            "threshold": self.threshold,
            "metadata": self.metadata,
            "timestamp": self.timestamp,
        }


@dataclass
class TradeRecord:
    """Record of a single trade for metrics calculation.
    
    Attributes:
        timestamp: Unix timestamp of trade close
        pnl: Realized PnL in USD
        profile_id: Profile that generated the trade
        symbol: Trading symbol
        atr_ratio_at_entry: ATR ratio when trade was entered
    """
    timestamp: float
    pnl: float
    profile_id: str
    symbol: str
    atr_ratio_at_entry: Optional[float] = None


@dataclass
class CoverageMetrics:
    """Aggregated coverage metrics for a time window.
    
    Attributes:
        trade_count: Total number of trades in the window
        win_count: Number of winning trades (pnl > 0)
        loss_count: Number of losing trades (pnl <= 0)
        win_rate: Win rate as a decimal (0.0 to 1.0)
        avg_win: Average winning trade PnL in USD
        avg_loss: Average losing trade PnL in USD (absolute value)
        expectancy: Expected value per trade = (avg_win * win_rate) - (avg_loss * loss_rate)
        total_pnl: Sum of all trade PnLs
        window_start: Start of the metrics window (Unix timestamp)
        window_end: End of the metrics window (Unix timestamp)
        trades_by_profile: Dict mapping profile_id -> trade count
        atr_distribution: Dict mapping ATR bucket -> trade count
    
    Requirements: 8.1, 8.2, 8.3
    """
    trade_count: int
    win_count: int
    loss_count: int
    win_rate: float
    avg_win: float
    avg_loss: float
    expectancy: float
    total_pnl: float
    window_start: float
    window_end: float
    trades_by_profile: Dict[str, int] = field(default_factory=dict)
    atr_distribution: Dict[str, int] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)
    
    @classmethod
    def empty(cls, window_hours: float = 24.0) -> "CoverageMetrics":
        """Create empty metrics with default values."""
        now = time.time()
        return cls(
            trade_count=0,
            win_count=0,
            loss_count=0,
            win_rate=0.0,
            avg_win=0.0,
            avg_loss=0.0,
            expectancy=0.0,
            total_pnl=0.0,
            window_start=now - (window_hours * 3600),
            window_end=now,
            trades_by_profile={},
            atr_distribution={},
        )


def calculate_expectancy(
    avg_win: float,
    avg_loss: float,
    win_rate: float,
) -> float:
    """Calculate trading expectancy.
    
    Formula: expectancy = (avg_win * win_rate) - (avg_loss * (1 - win_rate))
    
    Args:
        avg_win: Average winning trade PnL (positive value)
        avg_loss: Average losing trade PnL (absolute value, positive)
        win_rate: Win rate as decimal (0.0 to 1.0)
    
    Returns:
        Expectancy value (positive = profitable, negative = losing)
    
    Requirements: 8.3
    """
    loss_rate = 1.0 - win_rate
    return (avg_win * win_rate) - (avg_loss * loss_rate)


def calculate_win_rate(win_count: int, total_count: int) -> float:
    """Calculate win rate from counts.
    
    Args:
        win_count: Number of winning trades
        total_count: Total number of trades
    
    Returns:
        Win rate as decimal (0.0 to 1.0), or 0.0 if no trades
    """
    if total_count == 0:
        return 0.0
    return win_count / total_count


def get_atr_bucket(atr_ratio: Optional[float]) -> str:
    """Get ATR bucket label for distribution tracking.
    
    Args:
        atr_ratio: ATR ratio value
    
    Returns:
        Bucket label string
    """
    if atr_ratio is None:
        return "unknown"
    if atr_ratio < 0.5:
        return "very_low_<0.5"
    elif atr_ratio < 1.0:
        return "low_0.5-1.0"
    elif atr_ratio < 1.4:
        return "midvol_low_1.0-1.4"
    elif atr_ratio < 2.0:
        return "midvol_high_1.4-2.0"
    elif atr_ratio < 3.0:
        return "high_2.0-3.0"
    else:
        return "very_high_>3.0"



class CoverageGuardrailsTracker:
    """Tracks trade metrics and emits guardrail alerts.
    
    This class maintains a rolling window of trades and calculates metrics
    to detect when coverage restoration may be degrading signal quality.
    
    Alerts are emitted when:
    - Trade count > 3x baseline (warning) - Requirement 8.1
    - Win rate < 45% over 24h (warning) - Requirement 8.2
    - Expectancy < 0 (critical) - Requirement 8.3
    
    Requirements: 8.1, 8.2, 8.3
    """
    
    # Default thresholds
    DEFAULT_BASELINE_TRADE_COUNT_24H = 10  # Expected trades per 24h before changes
    DEFAULT_TRADE_COUNT_MULTIPLIER = 3.0  # Alert if > 3x baseline
    DEFAULT_MIN_WIN_RATE = 0.45  # 45% minimum win rate
    DEFAULT_WINDOW_HOURS = 24.0
    
    def __init__(
        self,
        baseline_trade_count_24h: int = DEFAULT_BASELINE_TRADE_COUNT_24H,
        trade_count_multiplier: float = DEFAULT_TRADE_COUNT_MULTIPLIER,
        min_win_rate: float = DEFAULT_MIN_WIN_RATE,
        window_hours: float = DEFAULT_WINDOW_HOURS,
    ):
        """Initialize CoverageGuardrailsTracker.
        
        Args:
            baseline_trade_count_24h: Expected trades per 24h before changes
            trade_count_multiplier: Alert if trade count > multiplier × baseline
            min_win_rate: Minimum acceptable win rate (0.0 to 1.0)
            window_hours: Rolling window size in hours
        """
        self._baseline_trade_count = baseline_trade_count_24h
        self._trade_count_multiplier = trade_count_multiplier
        self._min_win_rate = min_win_rate
        self._window_hours = window_hours
        self._window_seconds = window_hours * 3600
        
        # Rolling window of trades
        self._trades: deque[TradeRecord] = deque()
        
        # Alert state to prevent duplicate alerts
        self._last_alert_times: Dict[AlertType, float] = {}
        self._alert_cooldown_seconds = 3600  # 1 hour between same alert type
    
    def record_trade(self, trade: TradeRecord) -> None:
        """Record a completed trade.
        
        Args:
            trade: TradeRecord with trade details
        """
        self._trades.append(trade)
        self._prune_old_trades()
        
        logger.debug(
            "coverage_guardrails_trade_recorded",
            extra={
                "symbol": trade.symbol,
                "profile_id": trade.profile_id,
                "pnl": trade.pnl,
                "atr_ratio": trade.atr_ratio_at_entry,
            }
        )
    
    def record_trade_simple(
        self,
        pnl: float,
        profile_id: str,
        symbol: str,
        atr_ratio_at_entry: Optional[float] = None,
        timestamp: Optional[float] = None,
    ) -> None:
        """Record a trade with simple parameters.
        
        Args:
            pnl: Realized PnL in USD
            profile_id: Profile that generated the trade
            symbol: Trading symbol
            atr_ratio_at_entry: ATR ratio when trade was entered
            timestamp: Trade timestamp (defaults to now)
        """
        trade = TradeRecord(
            timestamp=timestamp or time.time(),
            pnl=pnl,
            profile_id=profile_id,
            symbol=symbol,
            atr_ratio_at_entry=atr_ratio_at_entry,
        )
        self.record_trade(trade)
    
    def _prune_old_trades(self) -> None:
        """Remove trades outside the rolling window."""
        cutoff = time.time() - self._window_seconds
        while self._trades and self._trades[0].timestamp < cutoff:
            self._trades.popleft()
    
    def get_metrics(self) -> CoverageMetrics:
        """Calculate current coverage metrics.
        
        Returns:
            CoverageMetrics with aggregated data
        
        Requirements: 8.1, 8.2, 8.3
        """
        self._prune_old_trades()
        
        now = time.time()
        window_start = now - self._window_seconds
        
        if not self._trades:
            return CoverageMetrics.empty(self._window_hours)
        
        # Calculate basic counts
        trade_count = len(self._trades)
        wins = [t for t in self._trades if t.pnl > 0]
        losses = [t for t in self._trades if t.pnl <= 0]
        win_count = len(wins)
        loss_count = len(losses)
        
        # Calculate averages
        avg_win = sum(t.pnl for t in wins) / win_count if win_count > 0 else 0.0
        avg_loss = abs(sum(t.pnl for t in losses) / loss_count) if loss_count > 0 else 0.0
        
        # Calculate rates
        win_rate = calculate_win_rate(win_count, trade_count)
        
        # Calculate expectancy
        expectancy = calculate_expectancy(avg_win, avg_loss, win_rate)
        
        # Calculate total PnL
        total_pnl = sum(t.pnl for t in self._trades)
        
        # Calculate trades by profile
        trades_by_profile: Dict[str, int] = {}
        for trade in self._trades:
            trades_by_profile[trade.profile_id] = trades_by_profile.get(trade.profile_id, 0) + 1
        
        # Calculate ATR distribution
        atr_distribution: Dict[str, int] = {}
        for trade in self._trades:
            bucket = get_atr_bucket(trade.atr_ratio_at_entry)
            atr_distribution[bucket] = atr_distribution.get(bucket, 0) + 1
        
        return CoverageMetrics(
            trade_count=trade_count,
            win_count=win_count,
            loss_count=loss_count,
            win_rate=win_rate,
            avg_win=avg_win,
            avg_loss=avg_loss,
            expectancy=expectancy,
            total_pnl=total_pnl,
            window_start=window_start,
            window_end=now,
            trades_by_profile=trades_by_profile,
            atr_distribution=atr_distribution,
        )
    
    def check_alerts(self) -> List[GuardrailAlert]:
        """Check for guardrail violations and return alerts.
        
        Returns:
            List of GuardrailAlert objects for any violations
        
        Requirements: 8.1, 8.2, 8.3
        """
        alerts: List[GuardrailAlert] = []
        metrics = self.get_metrics()
        now = time.time()
        
        # Requirement 8.1: Trade count spike
        trade_count_threshold = self._baseline_trade_count * self._trade_count_multiplier
        if metrics.trade_count > trade_count_threshold:
            if self._can_emit_alert(AlertType.TRADE_COUNT_SPIKE, now):
                alerts.append(GuardrailAlert(
                    alert_type=AlertType.TRADE_COUNT_SPIKE,
                    severity=AlertSeverity.WARNING,
                    message=f"Trade count ({metrics.trade_count}) exceeds {self._trade_count_multiplier}x baseline ({self._baseline_trade_count})",
                    current_value=float(metrics.trade_count),
                    threshold=trade_count_threshold,
                    metadata={
                        "baseline": self._baseline_trade_count,
                        "multiplier": self._trade_count_multiplier,
                        "window_hours": self._window_hours,
                        "trades_by_profile": metrics.trades_by_profile,
                    },
                    timestamp=now,
                ))
                self._last_alert_times[AlertType.TRADE_COUNT_SPIKE] = now
        
        # Requirement 8.2: Win rate too low
        # Only check if we have enough trades for statistical significance
        if metrics.trade_count >= 10 and metrics.win_rate < self._min_win_rate:
            if self._can_emit_alert(AlertType.WIN_RATE_LOW, now):
                alerts.append(GuardrailAlert(
                    alert_type=AlertType.WIN_RATE_LOW,
                    severity=AlertSeverity.WARNING,
                    message=f"Win rate ({metrics.win_rate:.1%}) below minimum ({self._min_win_rate:.1%})",
                    current_value=metrics.win_rate,
                    threshold=self._min_win_rate,
                    metadata={
                        "win_count": metrics.win_count,
                        "loss_count": metrics.loss_count,
                        "trade_count": metrics.trade_count,
                        "window_hours": self._window_hours,
                    },
                    timestamp=now,
                ))
                self._last_alert_times[AlertType.WIN_RATE_LOW] = now
        
        # Requirement 8.3: Negative expectancy
        # Only check if we have enough trades for statistical significance
        if metrics.trade_count >= 10 and metrics.expectancy < 0:
            if self._can_emit_alert(AlertType.EXPECTANCY_NEGATIVE, now):
                alerts.append(GuardrailAlert(
                    alert_type=AlertType.EXPECTANCY_NEGATIVE,
                    severity=AlertSeverity.CRITICAL,
                    message=f"Expectancy is negative (${metrics.expectancy:.2f})",
                    current_value=metrics.expectancy,
                    threshold=0.0,
                    metadata={
                        "avg_win": metrics.avg_win,
                        "avg_loss": metrics.avg_loss,
                        "win_rate": metrics.win_rate,
                        "total_pnl": metrics.total_pnl,
                        "trade_count": metrics.trade_count,
                        "window_hours": self._window_hours,
                    },
                    timestamp=now,
                ))
                self._last_alert_times[AlertType.EXPECTANCY_NEGATIVE] = now
        
        return alerts
    
    def _can_emit_alert(self, alert_type: AlertType, now: float) -> bool:
        """Check if we can emit an alert (respecting cooldown).
        
        Args:
            alert_type: Type of alert to check
            now: Current timestamp
        
        Returns:
            True if alert can be emitted
        """
        last_time = self._last_alert_times.get(alert_type, 0)
        return (now - last_time) >= self._alert_cooldown_seconds
    
    def set_baseline_trade_count(self, count: int) -> None:
        """Update the baseline trade count.
        
        Args:
            count: New baseline trade count per 24h
        """
        if count > 0:
            self._baseline_trade_count = count
    
    def set_alert_cooldown(self, seconds: float) -> None:
        """Update the alert cooldown period.
        
        Args:
            seconds: Cooldown period in seconds
        """
        if seconds >= 0:
            self._alert_cooldown_seconds = seconds
    
    def clear_trades(self) -> None:
        """Clear all recorded trades."""
        self._trades.clear()
    
    def clear_alert_state(self) -> None:
        """Clear alert cooldown state."""
        self._last_alert_times.clear()



async def emit_coverage_guardrail_alert(
    alerts_client: Any,  # AlertsClient from alerts.py
    alert: GuardrailAlert,
    tenant_id: str,
    bot_id: str,
) -> bool:
    """Emit a coverage guardrail alert via the AlertsClient.
    
    Args:
        alerts_client: AlertsClient instance for sending webhooks
        alert: GuardrailAlert to emit
        tenant_id: Tenant identifier
        bot_id: Bot identifier
    
    Returns:
        True if alert was sent successfully
    
    Requirements: 8.1, 8.2, 8.3
    """
    # Log the alert
    log_level = logging.CRITICAL if alert.severity == AlertSeverity.CRITICAL else logging.WARNING
    logger.log(
        log_level,
        f"coverage_guardrail_alert: {alert.alert_type.value}",
        extra={
            "alert_type": alert.alert_type.value,
            "severity": alert.severity.value,
            "current_value": alert.current_value,
            "threshold": alert.threshold,
            "tenant_id": tenant_id,
            "bot_id": bot_id,
            **alert.metadata,
        }
    )
    
    # Send via webhook if client is available
    if alerts_client is None:
        return False
    
    try:
        return await alerts_client.send(
            alert_type=f"coverage_{alert.alert_type.value}",
            message=alert.message,
            metadata={
                "tenant_id": tenant_id,
                "bot_id": bot_id,
                "current_value": alert.current_value,
                "threshold": alert.threshold,
                **alert.metadata,
            },
            severity=alert.severity.value,
        )
    except Exception as e:
        logger.error(f"Failed to emit coverage guardrail alert: {e}")
        return False


def log_coverage_metrics(metrics: CoverageMetrics, tenant_id: str, bot_id: str) -> None:
    """Log coverage metrics for monitoring dashboards.
    
    Args:
        metrics: CoverageMetrics to log
        tenant_id: Tenant identifier
        bot_id: Bot identifier
    
    Requirements: 8.4, 8.5
    """
    logger.info(
        "coverage_metrics",
        extra={
            "tenant_id": tenant_id,
            "bot_id": bot_id,
            "trade_count": metrics.trade_count,
            "win_rate": metrics.win_rate,
            "expectancy": metrics.expectancy,
            "total_pnl": metrics.total_pnl,
            "avg_win": metrics.avg_win,
            "avg_loss": metrics.avg_loss,
            "window_hours": (metrics.window_end - metrics.window_start) / 3600,
            "trades_by_profile": metrics.trades_by_profile,
            "atr_distribution": metrics.atr_distribution,
        }
    )


class CoverageGuardrailsService:
    """Service for managing coverage guardrails with alert emission.
    
    This service wraps CoverageGuardrailsTracker and provides:
    - Automatic alert emission via AlertsClient
    - Periodic metrics logging
    - Integration with the telemetry pipeline
    
    Requirements: 8.1, 8.2, 8.3, 8.4, 8.5
    """
    
    def __init__(
        self,
        tracker: Optional[CoverageGuardrailsTracker] = None,
        alerts_client: Any = None,  # AlertsClient
        tenant_id: str = "default",
        bot_id: str = "default",
    ):
        """Initialize CoverageGuardrailsService.
        
        Args:
            tracker: CoverageGuardrailsTracker instance (creates default if None)
            alerts_client: AlertsClient for sending webhook alerts
            tenant_id: Tenant identifier
            bot_id: Bot identifier
        """
        self._tracker = tracker or CoverageGuardrailsTracker()
        self._alerts_client = alerts_client
        self._tenant_id = tenant_id
        self._bot_id = bot_id
    
    def record_trade(
        self,
        pnl: float,
        profile_id: str,
        symbol: str,
        atr_ratio_at_entry: Optional[float] = None,
        timestamp: Optional[float] = None,
    ) -> None:
        """Record a completed trade.
        
        Args:
            pnl: Realized PnL in USD
            profile_id: Profile that generated the trade
            symbol: Trading symbol
            atr_ratio_at_entry: ATR ratio when trade was entered
            timestamp: Trade timestamp (defaults to now)
        """
        self._tracker.record_trade_simple(
            pnl=pnl,
            profile_id=profile_id,
            symbol=symbol,
            atr_ratio_at_entry=atr_ratio_at_entry,
            timestamp=timestamp,
        )
    
    def get_metrics(self) -> CoverageMetrics:
        """Get current coverage metrics."""
        return self._tracker.get_metrics()
    
    async def check_and_emit_alerts(self) -> List[GuardrailAlert]:
        """Check for guardrail violations and emit alerts.
        
        Returns:
            List of alerts that were emitted
        
        Requirements: 8.1, 8.2, 8.3
        """
        alerts = self._tracker.check_alerts()
        
        for alert in alerts:
            await emit_coverage_guardrail_alert(
                alerts_client=self._alerts_client,
                alert=alert,
                tenant_id=self._tenant_id,
                bot_id=self._bot_id,
            )
        
        return alerts
    
    def log_metrics(self) -> None:
        """Log current coverage metrics."""
        metrics = self._tracker.get_metrics()
        log_coverage_metrics(metrics, self._tenant_id, self._bot_id)
    
    def set_baseline_trade_count(self, count: int) -> None:
        """Update the baseline trade count."""
        self._tracker.set_baseline_trade_count(count)
    
    def clear(self) -> None:
        """Clear all trades and alert state."""
        self._tracker.clear_trades()
        self._tracker.clear_alert_state()
