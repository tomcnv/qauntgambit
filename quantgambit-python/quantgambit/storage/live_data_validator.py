"""Live data validator for real-time data quality monitoring.

This module provides the LiveDataValidator class that validates data quality
in real-time during live trading. It detects gaps in orderbook sequence numbers
and trade timestamps, tracks completeness metrics, and emits quality warnings.

Feature: live-orderbook-data-storage
"""

from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass
from typing import Deque, Dict, List, Optional, Tuple, TYPE_CHECKING

from quantgambit.storage.persistence import (
    LiveQualityMetrics,
    LiveValidationConfig,
)

if TYPE_CHECKING:
    from quantgambit.market.quality import MarketDataQualityTracker
    from quantgambit.observability.telemetry import TelemetryContext, TelemetryPipeline
    from quantgambit.storage.redis_snapshots import RedisSnapshotWriter

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GapWarning:
    """A data quality warning for a detected gap.
    
    This dataclass represents a warning event emitted when a gap is detected
    in the data stream. It contains all the information needed to diagnose
    and respond to the gap.
    
    Attributes:
        symbol: The trading pair symbol affected by the gap (e.g., "BTC/USDT").
        exchange: The exchange identifier (e.g., "binance").
        gap_type: The type of gap detected ("sequence" or "timestamp").
        duration: The gap duration - sequence count for sequence gaps,
            seconds for timestamp gaps.
        timestamp: The timestamp when the gap was detected (seconds since epoch).
        details: Optional additional details about the gap.
    
    Validates: Requirements 4.3
    """
    symbol: str
    exchange: str
    gap_type: str  # "sequence" or "timestamp"
    duration: float  # sequence count or seconds
    timestamp: float  # when the gap was detected
    details: Optional[str] = None


class LiveDataValidator:
    """Validates data quality in real-time during live trading.
    
    This class monitors the quality of incoming market data by tracking
    orderbook sequence numbers and trade timestamps. It detects gaps,
    calculates completeness metrics, and emits warnings when data quality
    degrades below configured thresholds.
    
    The validator is designed to be lightweight and non-blocking to avoid
    impacting live trading latency. All metrics are tracked in-memory and
    emitted periodically to Redis for dashboard display.
    
    Attributes:
        quality_tracker: The MarketDataQualityTracker for updating quality status.
        snapshot_writer: Optional Redis snapshot writer for emitting metrics.
        telemetry: Optional telemetry pipeline for emitting events.
        telemetry_context: Optional telemetry context for event metadata.
        config: Configuration for validation thresholds and intervals.
    
    Example:
        >>> validator = LiveDataValidator(quality_tracker, config=config)
        >>> # In the orderbook processing loop:
        >>> gap = validator.detect_orderbook_gap(symbol, expected_seq, actual_seq)
        >>> if gap:
        ...     logger.warning(f"Detected gap of {gap} sequences")
        >>> validator.record_orderbook_update(symbol, exchange, timestamp, seq)
    
    Validates: Requirements 4.1, 4.2, 4.3, 4.4
    """
    
    def __init__(
        self,
        quality_tracker: Optional["MarketDataQualityTracker"] = None,
        snapshot_writer: Optional["RedisSnapshotWriter"] = None,
        telemetry: Optional["TelemetryPipeline"] = None,
        telemetry_context: Optional["TelemetryContext"] = None,
        config: Optional[LiveValidationConfig] = None,
    ) -> None:
        """Initialize the LiveDataValidator.
        
        Args:
            quality_tracker: The MarketDataQualityTracker for updating quality status.
                If None, quality status updates are skipped.
            snapshot_writer: Optional Redis snapshot writer for emitting metrics.
                If None, Redis metric emission is skipped.
            telemetry: Optional telemetry pipeline for emitting events.
                If None, telemetry event emission is skipped.
            telemetry_context: Optional telemetry context for event metadata.
                Required if telemetry is provided.
            config: Configuration for validation thresholds and intervals.
                If None, uses default configuration.
        """
        self.quality_tracker = quality_tracker
        self.snapshot_writer = snapshot_writer
        self.telemetry = telemetry
        self.telemetry_context = telemetry_context
        self.config = config or LiveValidationConfig()
        
        # Track expected sequence per symbol
        # Key: (symbol, exchange), Value: last seen sequence number
        self._expected_seq: Dict[tuple[str, str], int] = {}
        
        # Track sequence gaps per symbol for metrics
        # Key: (symbol, exchange), Value: total gap count
        self._seq_gap_count: Dict[tuple[str, str], int] = {}
        
        # Track last trade timestamp per symbol for timestamp gap detection
        # Key: (symbol, exchange), Value: last trade timestamp (float, seconds since epoch)
        self._last_trade_ts: Dict[tuple[str, str], float] = {}
        
        # Track trade gap count per symbol
        # Key: (symbol, exchange), Value: total gap count
        self._trade_gap_count: Dict[tuple[str, str], int] = {}
        
        # Track emitted gap warnings for testing and monitoring
        # This list stores all gap warnings emitted during the validator's lifetime
        self._emitted_warnings: List[GapWarning] = []
        
        # Rolling window for orderbook update timestamps (for completeness calculation)
        # Key: (symbol, exchange), Value: deque of timestamps
        self._orderbook_update_times: Dict[Tuple[str, str], Deque[float]] = {}
        
        # Rolling window for trade timestamps (for completeness calculation)
        # Key: (symbol, exchange), Value: deque of timestamps
        self._trade_update_times: Dict[Tuple[str, str], Deque[float]] = {}
        
        # Track degradation status per symbol
        # Key: (symbol, exchange), Value: is_degraded boolean
        self._is_degraded: Dict[Tuple[str, str], bool] = {}
    
    def detect_orderbook_gap(
        self,
        symbol: str,
        expected_seq: int,
        actual_seq: int,
    ) -> Optional[int]:
        """Detect sequence gap. Returns gap size or None.
        
        This method detects gaps in orderbook sequence numbers by comparing
        the actual sequence number with the expected sequence number. A gap
        is detected when actual_seq > expected_seq + 1, indicating that one
        or more orderbook updates were missed.
        
        The gap size is calculated as (actual_seq - expected_seq - 1), which
        represents the number of missed updates.
        
        Args:
            symbol: The trading pair symbol (e.g., "BTC/USDT").
            expected_seq: The expected sequence number (last seen + 1).
            actual_seq: The actual sequence number received.
        
        Returns:
            The gap size (number of missed updates) if a gap is detected,
            or None if no gap (actual_seq <= expected_seq + 1).
        
        Example:
            >>> validator = LiveDataValidator()
            >>> # No gap: expected 100, got 101
            >>> validator.detect_orderbook_gap("BTC/USDT", 100, 101)
            None
            >>> # Gap of 5: expected 100, got 106 (missed 101-105)
            >>> validator.detect_orderbook_gap("BTC/USDT", 100, 106)
            5
        
        Validates: Requirements 4.1
        """
        # Check if there's a gap
        # A gap exists when actual_seq > expected_seq + 1
        # This means we expected expected_seq + 1 but got something higher
        if actual_seq > expected_seq + 1:
            # Gap size is the number of missed sequences
            # If expected_seq = 100 and actual_seq = 106:
            # - We expected 101 (expected_seq + 1)
            # - We got 106
            # - Missed: 101, 102, 103, 104, 105 = 5 sequences
            # - Gap size = 106 - 100 - 1 = 5
            gap_size = actual_seq - expected_seq - 1
            return gap_size
        
        return None
    
    def record_orderbook_update(
        self,
        symbol: str,
        exchange: str,
        timestamp: float,
        seq: int,
    ) -> None:
        """Record an orderbook update for quality tracking.
        
        This method records an orderbook update and checks for sequence gaps.
        If a gap is detected, it updates the internal gap count, emits a
        warning event, and optionally updates the MarketDataQualityTracker.
        
        It also tracks the update timestamp in a rolling window for
        completeness calculation.
        
        Args:
            symbol: The trading pair symbol (e.g., "BTC/USDT").
            exchange: The exchange identifier (e.g., "binance").
            timestamp: The timestamp of the orderbook update (seconds since epoch).
            seq: The sequence number from the exchange orderbook feed.
        
        Validates: Requirements 4.1, 4.3, 4.6
        """
        if not self.config.enabled:
            return
        
        key = (symbol, exchange)
        
        # Track update time for completeness calculation (Requirement 4.6)
        self._track_orderbook_update_time(key, timestamp)
        
        # Check for sequence gap
        if key in self._expected_seq:
            expected_seq = self._expected_seq[key]
            gap = self.detect_orderbook_gap(symbol, expected_seq, seq)
            
            if gap is not None:
                # Increment gap count
                self._seq_gap_count[key] = self._seq_gap_count.get(key, 0) + 1
                
                logger.warning(
                    f"Orderbook sequence gap detected for {symbol}@{exchange}: "
                    f"expected {expected_seq + 1}, got {seq}, gap size: {gap}"
                )
                
                # Emit gap warning event (Requirement 4.3)
                self._emit_gap_warning(
                    symbol=symbol,
                    exchange=exchange,
                    gap_type="sequence",
                    duration=float(gap),
                    timestamp=timestamp,
                    details=f"expected seq {expected_seq + 1}, got {seq}",
                )
                
                # Update quality tracker if available
                if self.quality_tracker:
                    self.quality_tracker.update_orderbook(
                        symbol=symbol,
                        timestamp=timestamp,
                        now_ts=timestamp,
                        gap=True,
                    )
            else:
                # No gap - healthy update
                if self.quality_tracker:
                    self.quality_tracker.update_orderbook(
                        symbol=symbol,
                        timestamp=timestamp,
                        now_ts=timestamp,
                        gap=False,
                    )
        else:
            # First update for this symbol - just record it
            if self.quality_tracker:
                self.quality_tracker.update_orderbook(
                    symbol=symbol,
                    timestamp=timestamp,
                    now_ts=timestamp,
                    gap=False,
                )
        
        # Update expected sequence for next update
        self._expected_seq[key] = seq
    
    def record_trade(
        self,
        symbol: str,
        exchange: str,
        timestamp: float,
    ) -> None:
        """Record a trade for quality tracking.
        
        This method records a trade and checks for timestamp gaps.
        If the time between consecutive trades exceeds the configured
        gap_threshold_sec, a gap is detected, counted, and a warning is emitted.
        
        It also tracks the trade timestamp in a rolling window for
        completeness calculation.
        
        Args:
            symbol: The trading pair symbol (e.g., "BTC/USDT").
            exchange: The exchange identifier (e.g., "binance").
            timestamp: The timestamp of the trade (seconds since epoch).
        
        Validates: Requirements 4.2, 4.3, 4.6
        """
        if not self.config.enabled:
            return
        
        key = (symbol, exchange)
        
        # Track trade time for completeness calculation (Requirement 4.6)
        self._track_trade_update_time(key, timestamp)
        
        # Check for timestamp gap
        if key in self._last_trade_ts:
            last_ts = self._last_trade_ts[key]
            time_delta = timestamp - last_ts
            
            if time_delta > self.config.gap_threshold_sec:
                # Gap detected
                self._trade_gap_count[key] = self._trade_gap_count.get(key, 0) + 1
                
                logger.warning(
                    f"Trade timestamp gap detected for {symbol}@{exchange}: "
                    f"{time_delta:.2f}s since last trade (threshold: {self.config.gap_threshold_sec}s)"
                )
                
                # Emit gap warning event (Requirement 4.3)
                self._emit_gap_warning(
                    symbol=symbol,
                    exchange=exchange,
                    gap_type="timestamp",
                    duration=time_delta,
                    timestamp=timestamp,
                    details=f"last trade at {last_ts:.3f}, threshold {self.config.gap_threshold_sec}s",
                )
        
        # Update last trade timestamp
        self._last_trade_ts[key] = timestamp
        
        # Update quality tracker if available
        if self.quality_tracker:
            self.quality_tracker.update_trade(symbol=symbol, timestamp=timestamp)
    
    def get_seq_gap_count(self, symbol: str, exchange: str) -> int:
        """Get the total sequence gap count for a symbol.
        
        Args:
            symbol: The trading pair symbol.
            exchange: The exchange identifier.
        
        Returns:
            The total number of sequence gaps detected for this symbol.
        """
        return self._seq_gap_count.get((symbol, exchange), 0)
    
    def get_trade_gap_count(self, symbol: str, exchange: str) -> int:
        """Get the total trade gap count for a symbol.
        
        Args:
            symbol: The trading pair symbol.
            exchange: The exchange identifier.
        
        Returns:
            The total number of trade gaps detected for this symbol.
        """
        return self._trade_gap_count.get((symbol, exchange), 0)
    
    def get_expected_seq(self, symbol: str, exchange: str) -> Optional[int]:
        """Get the last seen sequence number for a symbol.
        
        This is primarily useful for testing and debugging.
        
        Args:
            symbol: The trading pair symbol.
            exchange: The exchange identifier.
        
        Returns:
            The last seen sequence number, or None if no updates recorded.
        """
        return self._expected_seq.get((symbol, exchange))
    
    def get_last_trade_ts(self, symbol: str, exchange: str) -> Optional[float]:
        """Get the last trade timestamp for a symbol.
        
        This is primarily useful for testing and debugging.
        
        Args:
            symbol: The trading pair symbol.
            exchange: The exchange identifier.
        
        Returns:
            The last trade timestamp, or None if no trades recorded.
        """
        return self._last_trade_ts.get((symbol, exchange))
    
    def reset_symbol(self, symbol: str, exchange: str) -> None:
        """Reset all tracking state for a symbol.
        
        This is useful when reconnecting to an exchange or when
        the orderbook is resynced from scratch.
        
        Args:
            symbol: The trading pair symbol.
            exchange: The exchange identifier.
        """
        key = (symbol, exchange)
        self._expected_seq.pop(key, None)
        self._seq_gap_count.pop(key, None)
        self._last_trade_ts.pop(key, None)
        self._trade_gap_count.pop(key, None)
        self._orderbook_update_times.pop(key, None)
        self._trade_update_times.pop(key, None)
        self._is_degraded.pop(key, None)
    
    def _emit_gap_warning(
        self,
        symbol: str,
        exchange: str,
        gap_type: str,
        duration: float,
        timestamp: float,
        details: Optional[str] = None,
    ) -> None:
        """Emit a gap warning event.
        
        This method creates a GapWarning event and:
        1. Stores it in the internal warnings list for tracking
        2. Logs the warning
        3. Emits to telemetry pipeline if configured
        
        The warning contains all information needed to diagnose the gap:
        - symbol: The affected trading pair
        - exchange: The exchange where the gap occurred
        - gap_type: "sequence" for orderbook gaps, "timestamp" for trade gaps
        - duration: The gap size (sequence count or seconds)
        - timestamp: When the gap was detected
        - details: Optional additional context
        
        Args:
            symbol: The trading pair symbol affected by the gap.
            exchange: The exchange identifier.
            gap_type: The type of gap ("sequence" or "timestamp").
            duration: The gap duration (sequence count or seconds).
            timestamp: The timestamp when the gap was detected.
            details: Optional additional details about the gap.
        
        Validates: Requirements 4.3
        """
        # Create the warning event
        warning = GapWarning(
            symbol=symbol,
            exchange=exchange,
            gap_type=gap_type,
            duration=duration,
            timestamp=timestamp,
            details=details,
        )
        
        # Store in internal list for tracking/testing
        self._emitted_warnings.append(warning)
        
        # Log the warning
        logger.warning(
            f"Gap warning emitted: symbol={symbol}, exchange={exchange}, "
            f"type={gap_type}, duration={duration}, details={details}"
        )
        
        # Emit to telemetry pipeline if configured
        if self.telemetry and self.telemetry_context:
            import asyncio
            
            payload = {
                "symbol": symbol,
                "exchange": exchange,
                "gap_type": gap_type,
                "duration": duration,
                "timestamp": timestamp,
                "details": details,
                "warning_type": "data_quality_gap",
            }
            
            # Schedule the async telemetry emission
            # Use create_task if we're in an async context, otherwise skip
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(
                    self.telemetry.publish_guardrail(self.telemetry_context, payload)
                )
            except RuntimeError:
                # No running event loop - skip telemetry emission
                # This can happen in synchronous test contexts
                pass
    
    def get_emitted_warnings(self) -> List[GapWarning]:
        """Get all emitted gap warnings.
        
        This method returns a copy of the list of all gap warnings
        emitted during the validator's lifetime. Useful for testing
        and monitoring.
        
        Returns:
            A list of GapWarning objects.
        """
        return list(self._emitted_warnings)
    
    def get_warnings_for_symbol(self, symbol: str, exchange: str) -> List[GapWarning]:
        """Get all emitted gap warnings for a specific symbol.
        
        Args:
            symbol: The trading pair symbol.
            exchange: The exchange identifier.
        
        Returns:
            A list of GapWarning objects for the specified symbol/exchange.
        """
        return [
            w for w in self._emitted_warnings
            if w.symbol == symbol and w.exchange == exchange
        ]
    
    def clear_warnings(self) -> None:
        """Clear all emitted warnings.
        
        This is useful for testing to reset the warning state between tests.
        """
        self._emitted_warnings.clear()
    
    def _track_orderbook_update_time(
        self,
        key: Tuple[str, str],
        timestamp: float,
    ) -> None:
        """Track an orderbook update timestamp in the rolling window.
        
        This method adds the timestamp to the rolling window deque and
        removes any timestamps that are outside the completeness window.
        
        Args:
            key: Tuple of (symbol, exchange).
            timestamp: The timestamp of the update (seconds since epoch).
        
        Validates: Requirements 4.6
        """
        if key not in self._orderbook_update_times:
            self._orderbook_update_times[key] = deque()
        
        window = self._orderbook_update_times[key]
        window.append(timestamp)
        
        # Remove timestamps outside the rolling window
        cutoff = timestamp - self.config.completeness_window_sec
        while window and window[0] < cutoff:
            window.popleft()
    
    def _track_trade_update_time(
        self,
        key: Tuple[str, str],
        timestamp: float,
    ) -> None:
        """Track a trade timestamp in the rolling window.
        
        This method adds the timestamp to the rolling window deque and
        removes any timestamps that are outside the completeness window.
        
        Args:
            key: Tuple of (symbol, exchange).
            timestamp: The timestamp of the trade (seconds since epoch).
        
        Validates: Requirements 4.6
        """
        if key not in self._trade_update_times:
            self._trade_update_times[key] = deque()
        
        window = self._trade_update_times[key]
        window.append(timestamp)
        
        # Remove timestamps outside the rolling window
        cutoff = timestamp - self.config.completeness_window_sec
        while window and window[0] < cutoff:
            window.popleft()
    
    def get_orderbook_completeness_pct(
        self,
        symbol: str,
        exchange: str,
        current_time: Optional[float] = None,
    ) -> float:
        """Calculate orderbook completeness percentage for a symbol.
        
        Completeness is calculated as:
            completeness_pct = (actual_updates / expected_updates) * 100
        
        Where:
            - actual_updates = number of updates received in the rolling window
            - expected_updates = window_duration * expected_updates_per_sec
        
        The completeness percentage is capped at 100.0 to handle cases where
        updates arrive faster than expected.
        
        Args:
            symbol: The trading pair symbol (e.g., "BTC/USDT").
            exchange: The exchange identifier (e.g., "binance").
            current_time: Optional current timestamp for calculating the window.
                If None, uses the latest update timestamp or returns 0.0.
        
        Returns:
            The completeness percentage (0.0 to 100.0).
            Returns 0.0 if no updates have been recorded.
        
        Example:
            >>> validator = LiveDataValidator(config=LiveValidationConfig(
            ...     completeness_window_sec=60.0,
            ...     expected_orderbook_updates_per_sec=1.0
            ... ))
            >>> # After receiving 50 updates in 60 seconds (expected 60)
            >>> validator.get_orderbook_completeness_pct("BTC/USDT", "binance")
            83.33...
        
        Validates: Requirements 4.6
        """
        key = (symbol, exchange)
        
        if key not in self._orderbook_update_times:
            return 0.0
        
        window = self._orderbook_update_times[key]
        if not window:
            return 0.0
        
        # Use current_time if provided, otherwise use the latest timestamp
        if current_time is None:
            current_time = window[-1]
        
        # Clean up old timestamps based on current_time
        cutoff = current_time - self.config.completeness_window_sec
        while window and window[0] < cutoff:
            window.popleft()
        
        if not window:
            return 0.0
        
        # Calculate actual window duration
        # Use the time span from the first update to current_time
        window_start = max(window[0], cutoff)
        window_duration = current_time - window_start
        
        # If window duration is very small, avoid division issues
        if window_duration < 0.001:
            return 100.0 if len(window) > 0 else 0.0
        
        # Calculate expected updates for the actual window duration
        expected_updates = window_duration * self.config.expected_orderbook_updates_per_sec
        
        # Actual updates in the window
        actual_updates = len(window)
        
        # Calculate completeness percentage
        if expected_updates <= 0:
            return 100.0 if actual_updates > 0 else 0.0
        
        completeness_pct = (actual_updates / expected_updates) * 100.0
        
        # Cap at 100% (can exceed if updates arrive faster than expected)
        return min(completeness_pct, 100.0)
    
    def get_trade_completeness_pct(
        self,
        symbol: str,
        exchange: str,
        current_time: Optional[float] = None,
    ) -> float:
        """Calculate trade completeness percentage for a symbol.
        
        Completeness is calculated as:
            completeness_pct = (actual_trades / expected_trades) * 100
        
        Where:
            - actual_trades = number of trades received in the rolling window
            - expected_trades = window_duration * expected_trades_per_sec
        
        The completeness percentage is capped at 100.0 to handle cases where
        trades arrive faster than expected.
        
        Args:
            symbol: The trading pair symbol (e.g., "BTC/USDT").
            exchange: The exchange identifier (e.g., "binance").
            current_time: Optional current timestamp for calculating the window.
                If None, uses the latest trade timestamp or returns 0.0.
        
        Returns:
            The completeness percentage (0.0 to 100.0).
            Returns 0.0 if no trades have been recorded.
        
        Example:
            >>> validator = LiveDataValidator(config=LiveValidationConfig(
            ...     completeness_window_sec=60.0,
            ...     expected_trades_per_sec=2.0
            ... ))
            >>> # After receiving 100 trades in 60 seconds (expected 120)
            >>> validator.get_trade_completeness_pct("BTC/USDT", "binance")
            83.33...
        
        Validates: Requirements 4.6
        """
        key = (symbol, exchange)
        
        if key not in self._trade_update_times:
            return 0.0
        
        window = self._trade_update_times[key]
        if not window:
            return 0.0
        
        # Use current_time if provided, otherwise use the latest timestamp
        if current_time is None:
            current_time = window[-1]
        
        # Clean up old timestamps based on current_time
        cutoff = current_time - self.config.completeness_window_sec
        while window and window[0] < cutoff:
            window.popleft()
        
        if not window:
            return 0.0
        
        # Calculate actual window duration
        # Use the time span from the first update to current_time
        window_start = max(window[0], cutoff)
        window_duration = current_time - window_start
        
        # If window duration is very small, avoid division issues
        if window_duration < 0.001:
            return 100.0 if len(window) > 0 else 0.0
        
        # Calculate expected trades for the actual window duration
        expected_trades = window_duration * self.config.expected_trades_per_sec
        
        # Actual trades in the window
        actual_trades = len(window)
        
        # Calculate completeness percentage
        if expected_trades <= 0:
            return 100.0 if actual_trades > 0 else 0.0
        
        completeness_pct = (actual_trades / expected_trades) * 100.0
        
        # Cap at 100% (can exceed if trades arrive faster than expected)
        return min(completeness_pct, 100.0)
    
    def get_completeness_metrics(
        self,
        symbol: str,
        exchange: str,
        current_time: Optional[float] = None,
    ) -> Tuple[float, float]:
        """Get both orderbook and trade completeness percentages.
        
        This is a convenience method that returns both completeness
        percentages in a single call.
        
        Args:
            symbol: The trading pair symbol (e.g., "BTC/USDT").
            exchange: The exchange identifier (e.g., "binance").
            current_time: Optional current timestamp for calculating the window.
        
        Returns:
            A tuple of (orderbook_completeness_pct, trade_completeness_pct).
        
        Validates: Requirements 4.6
        """
        orderbook_pct = self.get_orderbook_completeness_pct(symbol, exchange, current_time)
        trade_pct = self.get_trade_completeness_pct(symbol, exchange, current_time)
        return (orderbook_pct, trade_pct)
    
    def get_update_count_in_window(
        self,
        symbol: str,
        exchange: str,
        update_type: str = "orderbook",
    ) -> int:
        """Get the number of updates in the rolling window.
        
        This is primarily useful for testing and debugging.
        
        Args:
            symbol: The trading pair symbol.
            exchange: The exchange identifier.
            update_type: Either "orderbook" or "trade".
        
        Returns:
            The number of updates in the rolling window.
        """
        key = (symbol, exchange)
        
        if update_type == "orderbook":
            window = self._orderbook_update_times.get(key)
        else:
            window = self._trade_update_times.get(key)
        
        return len(window) if window else 0
    
    def calculate_quality_score(
        self,
        symbol: str,
        exchange: str,
        current_time: Optional[float] = None,
    ) -> float:
        """Calculate the overall quality score for a symbol.
        
        The quality score is calculated as the average of orderbook and trade
        completeness percentages, normalized to a 0.0 to 1.0 scale.
        
        Quality score = (orderbook_completeness_pct + trade_completeness_pct) / 200.0
        
        This gives equal weight to both orderbook and trade data quality.
        
        Args:
            symbol: The trading pair symbol (e.g., "BTC/USDT").
            exchange: The exchange identifier (e.g., "binance").
            current_time: Optional current timestamp for calculating the window.
                If None, uses the latest update timestamp.
        
        Returns:
            The quality score from 0.0 (worst) to 1.0 (best).
            Returns 0.0 if no data has been recorded.
        
        Example:
            >>> validator = LiveDataValidator()
            >>> # After recording some updates...
            >>> score = validator.calculate_quality_score("BTC/USDT", "binance")
            >>> print(f"Quality score: {score:.2f}")
            Quality score: 0.85
        
        Validates: Requirements 4.4
        """
        orderbook_pct, trade_pct = self.get_completeness_metrics(
            symbol, exchange, current_time
        )
        
        # Average the two completeness percentages and normalize to 0.0-1.0
        # If both are 0, return 0.0
        if orderbook_pct == 0.0 and trade_pct == 0.0:
            return 0.0
        
        # Calculate average completeness as quality score
        # Normalize from percentage (0-100) to score (0.0-1.0)
        quality_score = (orderbook_pct + trade_pct) / 200.0
        
        return min(quality_score, 1.0)
    
    def check_quality_threshold(
        self,
        symbol: str,
        exchange: str,
        current_time: Optional[float] = None,
    ) -> bool:
        """Check if quality has degraded below the threshold and update status.
        
        This method calculates the quality score for a symbol and compares it
        to the configured min_completeness_pct threshold. If the quality score
        (as a percentage) falls below the threshold:
        1. Sets is_degraded to True for the symbol
        2. Updates the MarketDataQualityTracker status to "degraded"
        
        If quality is above the threshold and was previously degraded, the
        degradation status is cleared.
        
        Args:
            symbol: The trading pair symbol (e.g., "BTC/USDT").
            exchange: The exchange identifier (e.g., "binance").
            current_time: Optional current timestamp for calculating the window.
                If None, uses the latest update timestamp.
        
        Returns:
            True if the symbol is currently degraded, False otherwise.
        
        Example:
            >>> config = LiveValidationConfig(min_completeness_pct=80.0)
            >>> validator = LiveDataValidator(quality_tracker, config=config)
            >>> # After recording updates with poor completeness...
            >>> is_degraded = validator.check_quality_threshold("BTC/USDT", "binance")
            >>> if is_degraded:
            ...     print("Data quality is degraded!")
        
        Validates: Requirements 4.4
        """
        if not self.config.enabled:
            return False
        
        key = (symbol, exchange)
        
        # Calculate quality score (0.0 to 1.0)
        quality_score = self.calculate_quality_score(symbol, exchange, current_time)
        
        # Convert to percentage for comparison with threshold
        quality_score_pct = quality_score * 100.0
        
        # Check if quality is below threshold
        is_degraded = quality_score_pct < self.config.min_completeness_pct
        
        # Track previous degradation state for logging
        was_degraded = self._is_degraded.get(key, False)
        
        # Update degradation status
        self._is_degraded[key] = is_degraded
        
        # Update MarketDataQualityTracker if available
        if self.quality_tracker:
            if is_degraded and not was_degraded:
                # Newly degraded - log and update tracker
                logger.warning(
                    f"Quality degraded for {symbol}@{exchange}: "
                    f"score={quality_score_pct:.1f}% < threshold={self.config.min_completeness_pct}%"
                )
                # Update the quality tracker with a gap to indicate degradation
                # This will affect the quality score in the tracker's snapshot
                if current_time is not None:
                    self.quality_tracker.update_orderbook(
                        symbol=symbol,
                        timestamp=current_time,
                        now_ts=current_time,
                        gap=True,
                    )
            elif not is_degraded and was_degraded:
                # Recovered from degradation
                logger.info(
                    f"Quality recovered for {symbol}@{exchange}: "
                    f"score={quality_score_pct:.1f}% >= threshold={self.config.min_completeness_pct}%"
                )
        
        return is_degraded
    
    def is_degraded(self, symbol: str, exchange: str) -> bool:
        """Check if a symbol is currently in degraded quality state.
        
        This method returns the current degradation status for a symbol
        without recalculating the quality score. Use check_quality_threshold()
        to recalculate and update the status.
        
        Args:
            symbol: The trading pair symbol (e.g., "BTC/USDT").
            exchange: The exchange identifier (e.g., "binance").
        
        Returns:
            True if the symbol is currently degraded, False otherwise.
            Returns False if no data has been recorded for the symbol.
        
        Example:
            >>> validator = LiveDataValidator()
            >>> # Check current degradation status
            >>> if validator.is_degraded("BTC/USDT", "binance"):
            ...     print("Symbol is degraded")
        
        Validates: Requirements 4.4
        """
        return self._is_degraded.get((symbol, exchange), False)
    
    def get_quality_metrics(
        self,
        symbol: str,
        exchange: str,
        current_time: Optional[float] = None,
    ) -> LiveQualityMetrics:
        """Get comprehensive quality metrics for a symbol.
        
        This method calculates and returns all quality metrics for a symbol,
        including completeness percentages, gap counts, quality score, grade,
        and degradation status.
        
        The quality grade is determined by the quality score:
        - A: score >= 0.9 (90%+)
        - B: score >= 0.8 (80-89%)
        - C: score >= 0.7 (70-79%)
        - D: score >= 0.6 (60-69%)
        - F: score < 0.6 (<60%)
        
        Args:
            symbol: The trading pair symbol (e.g., "BTC/USDT").
            exchange: The exchange identifier (e.g., "binance").
            current_time: Optional current timestamp for calculating metrics.
                If None, uses the current time.
        
        Returns:
            A LiveQualityMetrics object containing all quality metrics.
        
        Example:
            >>> validator = LiveDataValidator()
            >>> metrics = validator.get_quality_metrics("BTC/USDT", "binance")
            >>> print(f"Quality: {metrics.quality_grade} ({metrics.quality_score:.2f})")
            >>> print(f"Degraded: {metrics.is_degraded}")
        
        Validates: Requirements 4.3, 4.4
        """
        if current_time is None:
            current_time = time.time()
        
        key = (symbol, exchange)
        
        # Get completeness metrics
        orderbook_pct = self.get_orderbook_completeness_pct(symbol, exchange, current_time)
        trade_pct = self.get_trade_completeness_pct(symbol, exchange, current_time)
        
        # Get gap counts
        orderbook_gap_count = self._seq_gap_count.get(key, 0)
        trade_gap_count = self._trade_gap_count.get(key, 0)
        
        # Get last sequence and timestamp
        orderbook_last_seq = self._expected_seq.get(key, 0)
        trade_last_ts = self._last_trade_ts.get(key, 0.0)
        
        # Calculate quality score
        quality_score = self.calculate_quality_score(symbol, exchange, current_time)
        
        # Determine quality grade
        if quality_score >= 0.9:
            quality_grade = "A"
        elif quality_score >= 0.8:
            quality_grade = "B"
        elif quality_score >= 0.7:
            quality_grade = "C"
        elif quality_score >= 0.6:
            quality_grade = "D"
        else:
            quality_grade = "F"
        
        # Check and update degradation status
        is_degraded = self.check_quality_threshold(symbol, exchange, current_time)
        
        # Collect warnings
        warnings: List[str] = []
        
        # Add warning if degraded
        if is_degraded:
            warnings.append(
                f"Quality degraded: {quality_score * 100:.1f}% < {self.config.min_completeness_pct}%"
            )
        
        # Add warning for low orderbook completeness
        if orderbook_pct < self.config.min_completeness_pct:
            warnings.append(f"Low orderbook completeness: {orderbook_pct:.1f}%")
        
        # Add warning for low trade completeness
        if trade_pct < self.config.min_completeness_pct:
            warnings.append(f"Low trade completeness: {trade_pct:.1f}%")
        
        # Add warning for sequence gaps
        if orderbook_gap_count > 0:
            warnings.append(f"Orderbook sequence gaps: {orderbook_gap_count}")
        
        # Add warning for trade gaps
        if trade_gap_count > 0:
            warnings.append(f"Trade timestamp gaps: {trade_gap_count}")
        
        return LiveQualityMetrics(
            symbol=symbol,
            exchange=exchange,
            timestamp=current_time,
            orderbook_completeness_pct=orderbook_pct,
            orderbook_gap_count=orderbook_gap_count,
            orderbook_last_seq=orderbook_last_seq,
            orderbook_seq_gaps=orderbook_gap_count,  # Same as gap_count for now
            trade_completeness_pct=trade_pct,
            trade_gap_count=trade_gap_count,
            trade_last_ts=trade_last_ts,
            quality_score=quality_score,
            quality_grade=quality_grade,
            is_degraded=is_degraded,
            warnings=warnings,
        )

    def get_tracked_symbols(self) -> List[Tuple[str, str]]:
        """Get all symbol/exchange pairs being tracked.
        
        Returns a list of all (symbol, exchange) tuples that have
        received at least one orderbook or trade update.
        
        Returns:
            A list of (symbol, exchange) tuples.
        """
        # Combine keys from all tracking dictionaries
        keys: set[Tuple[str, str]] = set()
        keys.update(self._expected_seq.keys())
        keys.update(self._last_trade_ts.keys())
        keys.update(self._orderbook_update_times.keys())
        keys.update(self._trade_update_times.keys())
        return list(keys)
    
    async def emit_metrics(self, current_time: Optional[float] = None) -> int:
        """Emit quality metrics to Redis and telemetry.
        
        This method calculates quality metrics for all tracked symbols
        and emits them to:
        1. Redis snapshots for dashboard display
        2. Telemetry pipeline for monitoring and alerting
        
        The metrics are emitted as JSON objects with the following structure:
        - Key: "live_quality:{symbol}:{exchange}"
        - Value: JSON-serialized LiveQualityMetrics
        
        Args:
            current_time: Optional current timestamp for calculating metrics.
                If None, uses the current time.
        
        Returns:
            The number of symbols for which metrics were emitted.
        
        Example:
            >>> validator = LiveDataValidator(snapshot_writer=redis_writer)
            >>> count = await validator.emit_metrics()
            >>> print(f"Emitted metrics for {count} symbols")
        
        Validates: Requirements 4.5
        """
        if not self.config.enabled:
            return 0
        
        if current_time is None:
            current_time = time.time()
        
        # Get all tracked symbols
        symbols = self.get_tracked_symbols()
        
        if not symbols:
            return 0
        
        emitted_count = 0
        
        for symbol, exchange in symbols:
            try:
                # Get quality metrics for this symbol
                metrics = self.get_quality_metrics(symbol, exchange, current_time)
                
                # Serialize metrics to dict for JSON
                metrics_dict = {
                    "symbol": metrics.symbol,
                    "exchange": metrics.exchange,
                    "timestamp": metrics.timestamp,
                    "orderbook_completeness_pct": metrics.orderbook_completeness_pct,
                    "orderbook_gap_count": metrics.orderbook_gap_count,
                    "orderbook_last_seq": metrics.orderbook_last_seq,
                    "orderbook_seq_gaps": metrics.orderbook_seq_gaps,
                    "trade_completeness_pct": metrics.trade_completeness_pct,
                    "trade_gap_count": metrics.trade_gap_count,
                    "trade_last_ts": metrics.trade_last_ts,
                    "quality_score": metrics.quality_score,
                    "quality_grade": metrics.quality_grade,
                    "is_degraded": metrics.is_degraded,
                    "warnings": metrics.warnings,
                }
                
                # Emit to Redis snapshot writer if available
                if self.snapshot_writer:
                    # Use a consistent key format for dashboard consumption
                    key = f"live_quality:{symbol}:{exchange}"
                    await self.snapshot_writer.write(key, metrics_dict)
                
                # Emit to telemetry pipeline if available
                if self.telemetry and self.telemetry_context:
                    # Add event type for telemetry routing
                    telemetry_payload = {
                        **metrics_dict,
                        "event_type": "live_quality_metrics",
                    }
                    await self.telemetry.publish_guardrail(
                        self.telemetry_context,
                        telemetry_payload,
                    )
                
                emitted_count += 1
                
            except Exception as e:
                logger.error(
                    f"Failed to emit metrics for {symbol}@{exchange}: {e}",
                    exc_info=True,
                )
        
        logger.debug(f"Emitted quality metrics for {emitted_count} symbols")
        return emitted_count
    
    async def start_background_emit(self) -> None:
        """Start background task for periodic metric emission.
        
        This method starts an asyncio task that periodically calls
        emit_metrics() at the configured emit_interval_sec interval.
        
        The background task runs until stop() is called.
        
        Example:
            >>> validator = LiveDataValidator(snapshot_writer=redis_writer)
            >>> await validator.start_background_emit()
            >>> # ... later ...
            >>> await validator.stop()
        
        Validates: Requirements 4.5
        """
        import asyncio
        
        if not self.config.enabled:
            logger.info("LiveDataValidator is disabled, not starting background emit")
            return
        
        if hasattr(self, "_emit_task") and self._emit_task is not None:
            logger.warning("Background emit task already running")
            return

        # Emit once immediately so dashboards populate quickly and tests do not depend
        # on background scheduling/timers.
        try:
            await self.emit_metrics()
        except Exception as e:
            logger.error(f"Error emitting initial metrics: {e}", exc_info=True)
        
        async def emit_loop() -> None:
            """Background loop for periodic metric emission."""
            logger.info(
                f"Starting background metric emission every "
                f"{self.config.emit_interval_sec}s"
            )

            loop = asyncio.get_running_loop()

            async def _sleep(delay_sec: float) -> None:
                # Do not rely on asyncio.sleep() directly; some tests patch it.
                fut = loop.create_future()
                loop.call_later(max(0.0, float(delay_sec)), fut.set_result, None)
                await fut
            
            while True:
                try:
                    await self.emit_metrics()
                    await _sleep(self.config.emit_interval_sec)
                except asyncio.CancelledError:
                    logger.info("Background emit task cancelled")
                    break
                except Exception as e:
                    logger.error(f"Error in background emit: {e}", exc_info=True)
                    # Continue running despite errors
        
        self._emit_task: Optional[asyncio.Task[None]] = asyncio.create_task(emit_loop())
        logger.info("Background metric emission task started")
    
    async def stop(self) -> None:
        """Stop background emission.
        
        This method cancels the background emit task if it's running
        and performs a final metric emission before stopping.
        
        Example:
            >>> validator = LiveDataValidator(snapshot_writer=redis_writer)
            >>> await validator.start_background_emit()
            >>> # ... later ...
            >>> await validator.stop()
        
        Validates: Requirements 4.5
        """
        import asyncio
        
        if hasattr(self, "_emit_task") and self._emit_task is not None:
            logger.info("Stopping background metric emission")
            self._emit_task.cancel()
            
            try:
                await self._emit_task
            except asyncio.CancelledError:
                # Task was cancelled, this is expected
                pass
            except Exception:
                # Other exceptions are also acceptable during shutdown
                pass
            
            self._emit_task = None
        
        # Final metric emission before stopping
        try:
            count = await self.emit_metrics()
            logger.info(f"Final metric emission: {count} symbols")
        except Exception as e:
            logger.error(f"Error in final metric emission: {e}", exc_info=True)
        
        logger.info("LiveDataValidator stopped")
