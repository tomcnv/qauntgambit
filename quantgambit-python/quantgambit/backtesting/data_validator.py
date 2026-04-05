"""Data validation for backtesting.

Feature: backtest-data-validation
Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 2.1-2.5, 3.1-3.5, 4.1-4.5, 5.1-5.5, 6.1-6.5, 7.1-7.5

This module provides comprehensive data validation for backtesting:
- Pre-flight validation before backtest execution
- Gap detection and analysis
- Multi-source data validation
- Quality scoring and grading
- Runtime quality tracking
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Optional, Tuple
import asyncio

from quantgambit.observability.logger import log_info, log_warning


# =============================================================================
# Configuration
# =============================================================================

@dataclass
class ValidationConfig:
    """Configuration for data validation thresholds.
    
    Requirements: 4.1, 4.2, 4.3
    """
    minimum_completeness_pct: float = 80.0  # Minimum overall completeness
    max_critical_gaps: int = 5  # Maximum critical gaps allowed
    max_gap_duration_pct: float = 10.0  # Max total gap time as % of range
    gap_threshold_minutes: int = 5  # Minutes between points to count as gap
    critical_gap_minutes: int = 15  # Minutes to classify gap as critical
    min_source_completeness_pct: float = 50.0  # Minimum per-source completeness


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class GapInfo:
    """Information about a detected data gap.
    
    Requirements: 2.2
    """
    start_time: str  # ISO format
    end_time: str  # ISO format
    duration_minutes: float
    is_critical: bool
    session: str  # "asia", "europe", "us", "overnight"


@dataclass
class QualityReport:
    """Report containing data quality metrics and validation results.
    
    Requirements: 1.5, 2.5, 3.5, 5.1
    """
    symbol: str
    start_date: str
    end_date: str
    
    # Overall metrics
    overall_completeness_pct: float
    data_quality_grade: str  # A, B, C, D, F
    recommendation: str  # "proceed", "proceed_with_caution", "insufficient_data"
    
    # Gap analysis
    total_gaps: int
    critical_gaps: int
    gap_duration_pct: float
    gap_details: List[GapInfo] = field(default_factory=list)
    
    # Per-source completeness
    decision_events_completeness: float = 0.0
    orderbook_events_completeness: float = 0.0
    candle_data_completeness: float = 0.0
    
    # Validation result
    passes_threshold: bool = False
    threshold_overridden: bool = False
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for API response."""
        return {
            "symbol": self.symbol,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "overall_completeness_pct": self.overall_completeness_pct,
            "data_quality_grade": self.data_quality_grade,
            "recommendation": self.recommendation,
            "total_gaps": self.total_gaps,
            "critical_gaps": self.critical_gaps,
            "gap_duration_pct": self.gap_duration_pct,
            "gap_details": [
                {
                    "start_time": g.start_time,
                    "end_time": g.end_time,
                    "duration_minutes": g.duration_minutes,
                    "is_critical": g.is_critical,
                    "session": g.session,
                }
                for g in self.gap_details[:10]  # Limit to first 10
            ],
            "decision_events_completeness": self.decision_events_completeness,
            "orderbook_events_completeness": self.orderbook_events_completeness,
            "candle_data_completeness": self.candle_data_completeness,
            "passes_threshold": self.passes_threshold,
            "threshold_overridden": self.threshold_overridden,
            "warnings": self.warnings,
            "errors": self.errors,
        }


@dataclass
class RuntimeQualityMetrics:
    """Metrics tracked during backtest execution.
    
    Requirements: 7.1, 7.2, 7.3
    """
    total_snapshots: int = 0
    missing_price_count: int = 0
    missing_depth_count: int = 0
    missing_orderbook_count: int = 0
    skipped_snapshots: int = 0
    
    @property
    def missing_price_pct(self) -> float:
        """Percentage of snapshots missing price data."""
        if self.total_snapshots == 0:
            return 0.0
        return (self.missing_price_count / self.total_snapshots) * 100
    
    @property
    def missing_depth_pct(self) -> float:
        """Percentage of snapshots missing depth data."""
        if self.total_snapshots == 0:
            return 0.0
        return (self.missing_depth_count / self.total_snapshots) * 100
    
    @property
    def is_degraded(self) -> bool:
        """Check if quality is degraded (>20% missing data)."""
        return self.missing_price_pct > 20 or self.missing_depth_pct > 20
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for storage."""
        return {
            "total_snapshots": self.total_snapshots,
            "missing_price_count": self.missing_price_count,
            "missing_depth_count": self.missing_depth_count,
            "missing_orderbook_count": self.missing_orderbook_count,
            "skipped_snapshots": self.skipped_snapshots,
            "missing_price_pct": self.missing_price_pct,
            "missing_depth_pct": self.missing_depth_pct,
            "is_degraded": self.is_degraded,
        }


# =============================================================================
# Gap Analyzer
# =============================================================================

class GapAnalyzer:
    """Analyzes gaps in historical data.
    
    Requirements: 2.1, 2.2, 2.3, 2.4
    
    Detects gaps in time series data and classifies them as critical
    if they occur during trading hours and exceed a threshold duration.
    """
    
    def __init__(
        self,
        gap_threshold_minutes: int = 5,
        critical_gap_minutes: int = 15,
    ):
        """Initialize the gap analyzer.
        
        Args:
            gap_threshold_minutes: Minutes between points to count as gap
            critical_gap_minutes: Minutes to classify gap as critical
        """
        self.gap_threshold_minutes = gap_threshold_minutes
        self.critical_gap_minutes = critical_gap_minutes
    
    def analyze_gaps(
        self,
        timestamps: List[datetime],
        start_date: datetime,
        end_date: datetime,
    ) -> Tuple[List[GapInfo], float]:
        """Analyze gaps in timestamp sequence.
        
        Args:
            timestamps: List of timestamps (must be sorted)
            start_date: Start of the date range
            end_date: End of the date range
            
        Returns:
            Tuple of (gap_list, gap_duration_pct)
        """
        if not timestamps:
            # No data = 100% gap
            return [], 100.0
        
        # Sort timestamps
        sorted_ts = sorted(timestamps)
        
        gaps: List[GapInfo] = []
        total_gap_seconds = 0.0
        gap_threshold_seconds = self.gap_threshold_minutes * 60
        
        # Check for gap at the start
        if sorted_ts[0] > start_date:
            start_gap_seconds = (sorted_ts[0] - start_date).total_seconds()
            if start_gap_seconds > gap_threshold_seconds:
                is_trading, session = self.is_trading_hours(start_date)
                is_critical = (
                    is_trading and 
                    start_gap_seconds > self.critical_gap_minutes * 60
                )
                gaps.append(GapInfo(
                    start_time=start_date.isoformat(),
                    end_time=sorted_ts[0].isoformat(),
                    duration_minutes=start_gap_seconds / 60,
                    is_critical=is_critical,
                    session=session,
                ))
                total_gap_seconds += start_gap_seconds
        
        # Check for gaps between consecutive timestamps
        for i in range(1, len(sorted_ts)):
            delta_seconds = (sorted_ts[i] - sorted_ts[i - 1]).total_seconds()
            
            if delta_seconds > gap_threshold_seconds:
                gap_start = sorted_ts[i - 1]
                gap_end = sorted_ts[i]
                
                is_trading, session = self.is_trading_hours(gap_start)
                is_critical = (
                    is_trading and 
                    delta_seconds > self.critical_gap_minutes * 60
                )
                
                gaps.append(GapInfo(
                    start_time=gap_start.isoformat(),
                    end_time=gap_end.isoformat(),
                    duration_minutes=delta_seconds / 60,
                    is_critical=is_critical,
                    session=session,
                ))
                total_gap_seconds += delta_seconds
        
        # Check for gap at the end
        if sorted_ts[-1] < end_date:
            end_gap_seconds = (end_date - sorted_ts[-1]).total_seconds()
            if end_gap_seconds > gap_threshold_seconds:
                is_trading, session = self.is_trading_hours(sorted_ts[-1])
                is_critical = (
                    is_trading and 
                    end_gap_seconds > self.critical_gap_minutes * 60
                )
                gaps.append(GapInfo(
                    start_time=sorted_ts[-1].isoformat(),
                    end_time=end_date.isoformat(),
                    duration_minutes=end_gap_seconds / 60,
                    is_critical=is_critical,
                    session=session,
                ))
                total_gap_seconds += end_gap_seconds
        
        # Calculate gap duration percentage
        total_range_seconds = (end_date - start_date).total_seconds()
        if total_range_seconds <= 0:
            gap_duration_pct = 0.0
        else:
            gap_duration_pct = (total_gap_seconds / total_range_seconds) * 100
        
        return gaps, gap_duration_pct
    
    def is_trading_hours(self, dt: datetime) -> Tuple[bool, str]:
        """Check if datetime falls within trading hours.
        
        Trading sessions (UTC):
        - Asia: 00:00-08:00 UTC
        - Europe: 08:00-14:00 UTC
        - US: 14:00-21:00 UTC
        - Overnight: 21:00-00:00 UTC
        
        Args:
            dt: Datetime to check
            
        Returns:
            Tuple of (is_trading_hours, session_name)
        """
        # Ensure we're working with UTC
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        
        hour = dt.hour
        
        if 0 <= hour < 8:
            return True, "asia"
        elif 8 <= hour < 14:
            return True, "europe"
        elif 14 <= hour < 21:
            return True, "us"
        else:  # 21-24
            return False, "overnight"
    
    def count_critical_gaps(self, gaps: List[GapInfo]) -> int:
        """Count the number of critical gaps.
        
        Args:
            gaps: List of gap info objects
            
        Returns:
            Count of critical gaps
        """
        return sum(1 for g in gaps if g.is_critical)


# =============================================================================
# Multi-Source Checker
# =============================================================================

class MultiSourceChecker:
    """Checks data availability across multiple sources.
    
    Requirements: 3.1, 3.2, 3.3, 3.4, 3.5
    
    Validates data availability in:
    - decision_events (TimescaleDB)
    - orderbook_events (TimescaleDB)
    - market_candles (TimescaleDB)
    """
    
    def __init__(self, timescale_pool):
        """Initialize the multi-source checker.
        
        Args:
            timescale_pool: asyncpg connection pool for TimescaleDB
        """
        self.pool = timescale_pool
    
    async def check_decision_events(
        self,
        symbol: str,
        start_date: datetime,
        end_date: datetime,
    ) -> Tuple[int, float, List[datetime]]:
        """Check decision events availability.
        
        Args:
            symbol: Trading symbol
            start_date: Start of date range
            end_date: End of date range
            
        Returns:
            Tuple of (count, completeness_pct, timestamps)
        """
        query = """
            SELECT ts
            FROM decision_events
            WHERE symbol = $1 AND ts >= $2 AND ts <= $3
            ORDER BY ts ASC
        """
        
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(query, symbol, start_date, end_date)
                timestamps = [row["ts"] for row in rows]
                count = len(timestamps)
                
                # Calculate expected count (assume ~1 event per 10 seconds)
                total_seconds = (end_date - start_date).total_seconds()
                expected_count = max(1, int(total_seconds / 10))
                completeness_pct = min(100.0, (count / expected_count) * 100)
                
                return count, completeness_pct, timestamps
        except Exception as e:
            log_warning("check_decision_events_failed", error=str(e))
            return 0, 0.0, []
    
    async def check_orderbook_events(
        self,
        symbol: str,
        start_date: datetime,
        end_date: datetime,
    ) -> Tuple[int, float, List[datetime]]:
        """Check orderbook events availability.
        
        Args:
            symbol: Trading symbol
            start_date: Start of date range
            end_date: End of date range
            
        Returns:
            Tuple of (count, completeness_pct, timestamps)
        """
        query = """
            SELECT ts
            FROM orderbook_events
            WHERE symbol = $1 AND ts >= $2 AND ts <= $3
            ORDER BY ts ASC
        """
        
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(query, symbol, start_date, end_date)
                timestamps = [row["ts"] for row in rows]
                count = len(timestamps)
                
                # Calculate expected count (assume ~1 event per second)
                total_seconds = (end_date - start_date).total_seconds()
                expected_count = max(1, int(total_seconds))
                completeness_pct = min(100.0, (count / expected_count) * 100)
                
                return count, completeness_pct, timestamps
        except Exception as e:
            log_warning("check_orderbook_events_failed", error=str(e))
            return 0, 0.0, []
    
    async def check_candle_data(
        self,
        symbol: str,
        start_date: datetime,
        end_date: datetime,
    ) -> Tuple[int, float, List[datetime]]:
        """Check candle data availability.
        
        Args:
            symbol: Trading symbol
            start_date: Start of date range
            end_date: End of date range
            
        Returns:
            Tuple of (count, completeness_pct, timestamps)
        """
        # Check 5-minute candles
        query = """
            SELECT ts
            FROM market_candles
            WHERE symbol = $1 AND timeframe_sec = 300 AND ts >= $2 AND ts <= $3
            ORDER BY ts ASC
        """
        
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(query, symbol, start_date, end_date)
                timestamps = [row["ts"] for row in rows]
                count = len(timestamps)
                
                # Calculate expected count (1 candle per 5 minutes)
                total_minutes = (end_date - start_date).total_seconds() / 60
                expected_count = max(1, int(total_minutes / 5))
                completeness_pct = min(100.0, (count / expected_count) * 100)
                
                return count, completeness_pct, timestamps
        except Exception as e:
            log_warning("check_candle_data_failed", error=str(e))
            return 0, 0.0, []
    
    async def check_all_sources(
        self,
        symbol: str,
        start_date: datetime,
        end_date: datetime,
    ) -> Dict[str, Tuple[int, float, List[datetime]]]:
        """Check all data sources in parallel.
        
        Args:
            symbol: Trading symbol
            start_date: Start of date range
            end_date: End of date range
            
        Returns:
            Dict mapping source name to (count, completeness_pct, timestamps)
        """
        results = await asyncio.gather(
            self.check_decision_events(symbol, start_date, end_date),
            self.check_orderbook_events(symbol, start_date, end_date),
            self.check_candle_data(symbol, start_date, end_date),
            return_exceptions=True,
        )
        
        # Handle any exceptions
        decision_result = results[0] if not isinstance(results[0], Exception) else (0, 0.0, [])
        orderbook_result = results[1] if not isinstance(results[1], Exception) else (0, 0.0, [])
        candle_result = results[2] if not isinstance(results[2], Exception) else (0, 0.0, [])
        
        return {
            "decision_events": decision_result,
            "orderbook_events": orderbook_result,
            "candle_data": candle_result,
        }
    
    def generate_source_warnings(
        self,
        source_results: Dict[str, Tuple[int, float, List[datetime]]],
        min_completeness_pct: float = 50.0,
    ) -> List[str]:
        """Generate warnings for sources with low completeness.
        
        Args:
            source_results: Results from check_all_sources
            min_completeness_pct: Minimum completeness to avoid warning
            
        Returns:
            List of warning messages
        """
        warnings = []
        
        for source_name, (count, completeness_pct, _) in source_results.items():
            if completeness_pct < min_completeness_pct:
                warnings.append(
                    f"{source_name} completeness is only {completeness_pct:.1f}% "
                    f"(below {min_completeness_pct}% threshold)"
                )
        
        return warnings


# =============================================================================
# Data Validator
# =============================================================================

class DataValidator:
    """Validates data quality before backtest execution.
    
    Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 4.1-4.5, 5.4, 5.5, 6.4
    
    Orchestrates pre-flight validation by:
    - Checking data availability across multiple sources
    - Analyzing gaps in the data
    - Calculating quality scores and grades
    - Generating recommendations
    """
    
    def __init__(
        self,
        timescale_pool,
        config: Optional[ValidationConfig] = None,
    ):
        """Initialize the data validator.
        
        Args:
            timescale_pool: asyncpg connection pool for TimescaleDB
            config: Optional validation configuration
        """
        self.pool = timescale_pool
        self.config = config or ValidationConfig()
        self.gap_analyzer = GapAnalyzer(
            gap_threshold_minutes=self.config.gap_threshold_minutes,
            critical_gap_minutes=self.config.critical_gap_minutes,
        )
        self.source_checker = MultiSourceChecker(timescale_pool)
    
    async def validate(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
        config: Optional[ValidationConfig] = None,
        force_run: bool = False,
    ) -> QualityReport:
        """Perform pre-flight data validation.
        
        Args:
            symbol: Trading symbol
            start_date: Start date (ISO format or YYYY-MM-DD)
            end_date: End date (ISO format or YYYY-MM-DD)
            config: Optional override for validation config
            force_run: If True, allow backtest even if thresholds not met
            
        Returns:
            QualityReport with validation results
        """
        cfg = config or self.config
        
        # Parse dates
        start_dt = self._parse_date(start_date)
        end_dt = self._parse_date(end_date)
        
        log_info(
            "data_validation_start",
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
        )
        
        # Check all data sources
        source_results = await self.source_checker.check_all_sources(
            symbol, start_dt, end_dt
        )
        
        # Extract completeness values
        decision_count, decision_pct, decision_ts = source_results["decision_events"]
        orderbook_count, orderbook_pct, orderbook_ts = source_results["orderbook_events"]
        candle_count, candle_pct, candle_ts = source_results["candle_data"]
        
        # Calculate overall completeness (weighted average)
        # Decision events are most important for backtesting
        overall_completeness = (
            decision_pct * 0.5 +
            orderbook_pct * 0.3 +
            candle_pct * 0.2
        )
        
        # Combine all timestamps for gap analysis
        all_timestamps = sorted(set(decision_ts + orderbook_ts + candle_ts))
        
        # Analyze gaps
        gaps, gap_duration_pct = self.gap_analyzer.analyze_gaps(
            all_timestamps, start_dt, end_dt
        )
        critical_gaps = self.gap_analyzer.count_critical_gaps(gaps)
        
        # Calculate grade
        grade = self.calculate_grade(overall_completeness)
        
        # Generate warnings
        warnings = self.source_checker.generate_source_warnings(
            source_results, cfg.min_source_completeness_pct
        )
        
        # Add grade warning if below B
        if grade in ("C", "D", "F"):
            warnings.append(f"Data quality grade is {grade} (below B threshold)")
        
        # Check thresholds
        errors = []
        passes_threshold = True
        
        if overall_completeness < cfg.minimum_completeness_pct:
            passes_threshold = False
            errors.append(
                f"Completeness {overall_completeness:.1f}% is below "
                f"minimum threshold {cfg.minimum_completeness_pct}%"
            )
        
        if critical_gaps > cfg.max_critical_gaps:
            passes_threshold = False
            errors.append(
                f"Critical gaps ({critical_gaps}) exceed maximum "
                f"allowed ({cfg.max_critical_gaps})"
            )
        
        if gap_duration_pct > cfg.max_gap_duration_pct:
            passes_threshold = False
            errors.append(
                f"Gap duration {gap_duration_pct:.1f}% exceeds maximum "
                f"allowed {cfg.max_gap_duration_pct}%"
            )
        
        # Check for no data
        if decision_count == 0 and orderbook_count == 0 and candle_count == 0:
            passes_threshold = False
            errors.append("No data available for the requested date range")
        
        # Determine recommendation
        recommendation = self.get_recommendation(
            passes_threshold, warnings, force_run
        )
        
        # Handle force_run override
        threshold_overridden = force_run and not passes_threshold
        if threshold_overridden:
            passes_threshold = True
        
        report = QualityReport(
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
            overall_completeness_pct=round(overall_completeness, 2),
            data_quality_grade=grade,
            recommendation=recommendation,
            total_gaps=len(gaps),
            critical_gaps=critical_gaps,
            gap_duration_pct=round(gap_duration_pct, 2),
            gap_details=gaps[:10],  # Limit to first 10
            decision_events_completeness=round(decision_pct, 2),
            orderbook_events_completeness=round(orderbook_pct, 2),
            candle_data_completeness=round(candle_pct, 2),
            passes_threshold=passes_threshold,
            threshold_overridden=threshold_overridden,
            warnings=warnings,
            errors=errors,
        )
        
        log_info(
            "data_validation_complete",
            symbol=symbol,
            grade=grade,
            completeness=overall_completeness,
            passes=passes_threshold,
            recommendation=recommendation,
        )
        
        return report
    
    def calculate_grade(self, completeness_pct: float) -> str:
        """Calculate data quality grade from completeness percentage.
        
        Grade thresholds:
        - A: >= 95%
        - B: >= 85%
        - C: >= 70%
        - D: >= 50%
        - F: < 50%
        
        Args:
            completeness_pct: Overall completeness percentage
            
        Returns:
            Grade letter (A, B, C, D, or F)
        """
        if completeness_pct >= 95:
            return "A"
        elif completeness_pct >= 85:
            return "B"
        elif completeness_pct >= 70:
            return "C"
        elif completeness_pct >= 50:
            return "D"
        else:
            return "F"
    
    def get_recommendation(
        self,
        passes_threshold: bool,
        warnings: List[str],
        force_run: bool,
    ) -> str:
        """Determine recommendation based on quality metrics.
        
        Args:
            passes_threshold: Whether validation passed
            warnings: List of warning messages
            force_run: Whether force_run was requested
            
        Returns:
            Recommendation string
        """
        if not passes_threshold and not force_run:
            return "insufficient_data"
        elif warnings:
            return "proceed_with_caution"
        else:
            return "proceed"
    
    def _parse_date(self, date_str: str) -> datetime:
        """Parse date string to datetime.
        
        Args:
            date_str: Date string (ISO format or YYYY-MM-DD)
            
        Returns:
            datetime object with UTC timezone
        """
        formats = [
            "%Y-%m-%d",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%dT%H:%M:%SZ",
            "%Y-%m-%d %H:%M:%S",
        ]
        
        for fmt in formats:
            try:
                dt = datetime.strptime(date_str, fmt)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt
            except ValueError:
                continue
        
        # Try ISO format with timezone
        try:
            dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            return dt
        except ValueError:
            pass
        
        raise ValueError(f"Unable to parse date: {date_str}")


# =============================================================================
# Runtime Quality Tracker
# =============================================================================

class RuntimeQualityTracker:
    """Tracks data quality during backtest execution.
    
    Requirements: 7.1, 7.2, 7.3, 7.5
    
    Tracks missing data during snapshot processing and determines
    if the backtest status should be degraded.
    """
    
    def __init__(self):
        """Initialize the runtime quality tracker."""
        self.metrics = RuntimeQualityMetrics()
    
    def record_snapshot(
        self,
        has_price: bool,
        has_depth: bool,
        has_orderbook: bool = True,
    ) -> None:
        """Record quality metrics for a processed snapshot.
        
        Args:
            has_price: Whether the snapshot has price data
            has_depth: Whether the snapshot has depth data
            has_orderbook: Whether the snapshot has orderbook data
        """
        self.metrics.total_snapshots += 1
        
        if not has_price:
            self.metrics.missing_price_count += 1
            log_info(
                "runtime_quality_missing_price",
                total=self.metrics.total_snapshots,
                missing=self.metrics.missing_price_count,
            )
        
        if not has_depth:
            self.metrics.missing_depth_count += 1
        
        if not has_orderbook:
            self.metrics.missing_orderbook_count += 1
    
    def record_skipped(self) -> None:
        """Record a skipped snapshot."""
        self.metrics.skipped_snapshots += 1
    
    def get_metrics(self) -> RuntimeQualityMetrics:
        """Get current quality metrics.
        
        Returns:
            RuntimeQualityMetrics object
        """
        return self.metrics
    
    def should_degrade_status(self) -> bool:
        """Check if backtest status should be degraded.
        
        Returns True if missing data exceeds 20% threshold.
        
        Returns:
            True if status should be degraded
        """
        return self.metrics.is_degraded
    
    def get_quality_grade(self) -> str:
        """Get quality grade based on runtime metrics.
        
        Returns:
            Grade letter (A, B, C, D, or F)
        """
        # Use the lower of price and depth completeness
        price_completeness = 100 - self.metrics.missing_price_pct
        depth_completeness = 100 - self.metrics.missing_depth_pct
        min_completeness = min(price_completeness, depth_completeness)
        
        if min_completeness >= 95:
            return "A"
        elif min_completeness >= 85:
            return "B"
        elif min_completeness >= 70:
            return "C"
        elif min_completeness >= 50:
            return "D"
        else:
            return "F"
