"""Persistence layer for orderbook snapshots and trade records.

This module provides configuration and data classes for persisting
orderbook snapshots and trade records to TimescaleDB.

Feature: live-orderbook-data-storage
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import List


@dataclass
class OrderbookSnapshotWriterConfig:
    """Configuration for orderbook snapshot persistence.
    
    This configuration controls how orderbook snapshots are captured and
    persisted to TimescaleDB. The writer uses asynchronous batch writes
    to avoid impacting live trading latency.
    
    Attributes:
        enabled: Whether snapshot persistence is enabled. When False,
            the writer will not capture or persist any snapshots.
        snapshot_interval_sec: Minimum interval between snapshots for
            the same symbol. Snapshots are throttled to this interval
            to balance storage vs granularity. Default is 1.0 second.
        batch_size: Maximum number of snapshots per batch write.
            When the buffer reaches this size, a flush is triggered.
            Default is 100 snapshots.
        flush_interval_sec: Maximum time before a forced flush of
            buffered snapshots, regardless of buffer size. Default
            is 5.0 seconds.
        max_buffer_size: Maximum number of buffered snapshots before
            backpressure is applied. When exceeded, new captures may
            block until space is available. Default is 1000 snapshots.
        retry_max_attempts: Maximum number of retry attempts for failed
            database writes. After this many failures, the batch is
            dropped to protect live trading. Default is 3 attempts.
        retry_base_delay_sec: Base delay for exponential backoff on
            write failures. The delay for attempt i is calculated as
            base_delay * 2^(i-1). Default is 0.1 seconds.
    
    Validates: Requirements 1.1, 1.6
    """
    
    enabled: bool = True
    snapshot_interval_sec: float = 1.0
    # Max levels persisted per side (bids/asks). Reducing this is the biggest
    # lever for cutting storage when bids/asks are stored as JSONB.
    max_depth_levels: int = 20
    batch_size: int = 100
    flush_interval_sec: float = 5.0
    max_buffer_size: int = 1000
    retry_max_attempts: int = 3
    retry_base_delay_sec: float = 0.1


@dataclass
class TradeRecordWriterConfig:
    """Configuration for trade record persistence.
    
    This configuration controls how trade records are captured and
    persisted to TimescaleDB. The writer uses asynchronous batch writes
    to avoid impacting live trading latency.
    
    Attributes:
        enabled: Whether trade record persistence is enabled. When False,
            the writer will not capture or persist any trade records.
        batch_size: Maximum number of trades per batch write.
            When the buffer reaches this size, a flush is triggered.
            Default is 500 trades.
        flush_interval_sec: Maximum time before a forced flush of
            buffered trades, regardless of buffer size. Default
            is 1.0 second.
        max_buffer_size: Maximum number of buffered trades before
            backpressure is applied. When exceeded, new records may
            block until space is available. Default is 10000 trades.
        retry_max_attempts: Maximum number of retry attempts for failed
            database writes. After this many failures, the batch is
            dropped to protect live trading. Default is 3 attempts.
        retry_base_delay_sec: Base delay for exponential backoff on
            write failures. The delay for attempt i is calculated as
            base_delay * 2^(i-1). Default is 0.1 seconds.
    
    Validates: Requirements 2.5
    """
    
    enabled: bool = True
    batch_size: int = 500
    flush_interval_sec: float = 1.0
    max_buffer_size: int = 10000
    retry_max_attempts: int = 3
    retry_base_delay_sec: float = 0.1


@dataclass
class PersistenceTradeRecord:
    """An individual trade record for persistence.
    
    This dataclass represents a single trade execution for persisting
    to TimescaleDB. It is distinct from the TradeRecord in
    quantgambit.market.trades which is used for the TradeStatsCache
    and has fewer fields.
    
    The PersistenceTradeRecord includes all fields needed for historical
    analysis, accurate VWAP calculation, volume profile reconstruction,
    and backtest replay.
    
    Attributes:
        symbol: The trading pair symbol (e.g., "BTC/USDT").
            Must be a non-empty string.
        exchange: The exchange identifier (e.g., "binance", "coinbase").
            Must be a non-empty string.
        timestamp: The timestamp of the trade. This MUST be the original
            exchange timestamp to ensure accurate replay, not the local
            processing time.
        price: The execution price of the trade.
            Must be a positive float.
        size: The size/quantity of the trade.
            Must be a positive float.
        side: The side of the trade, either "buy" or "sell".
            Indicates whether the trade was a buy or sell from the
            taker's perspective.
        trade_id: The unique trade identifier from the exchange.
            Must be a non-empty string. Used for deduplication and
            ensuring trade uniqueness.
    
    Validates: Requirements 2.2
    """
    
    symbol: str
    exchange: str
    timestamp: datetime
    price: float
    size: float
    side: str  # "buy" or "sell"
    trade_id: str
    tenant_id: str = "default"
    bot_id: str = "default"


@dataclass
class OrderbookSnapshot:
    """A point-in-time orderbook snapshot for persistence.
    
    This dataclass represents a complete orderbook state at a specific
    moment in time, including the full depth (up to 20 levels) and
    derived metrics. It is used for persisting orderbook data to
    TimescaleDB for historical analysis and backtest replay.
    
    Attributes:
        symbol: The trading pair symbol (e.g., "BTC/USDT").
            Must be a non-empty string.
        exchange: The exchange identifier (e.g., "binance", "coinbase").
            Must be a non-empty string.
        timestamp: The timestamp of the snapshot. This should be the
            exchange timestamp when available, or local time otherwise.
        seq: The sequence number from the exchange orderbook feed.
            Used for detecting gaps and ensuring ordering.
            Must be a positive integer.
        bids: List of bid levels, each as [price, size] pairs.
            Ordered from best (highest) to worst (lowest) price.
            Contains up to 20 levels.
        asks: List of ask levels, each as [price, size] pairs.
            Ordered from best (lowest) to worst (highest) price.
            Contains up to 20 levels.
        spread_bps: The bid-ask spread in basis points (1 bps = 0.01%).
            Calculated as ((best_ask - best_bid) / mid_price) * 10000.
        bid_depth_usd: Total USD value of all bid orders.
            Calculated as sum(price * size) for all bid levels.
        ask_depth_usd: Total USD value of all ask orders.
            Calculated as sum(price * size) for all ask levels.
        orderbook_imbalance: Ratio of bid depth to total depth.
            Calculated as bid_depth_usd / (bid_depth_usd + ask_depth_usd).
            Values > 0.5 indicate buying pressure, < 0.5 indicate selling pressure.
            Returns 0.5 if both depths are zero.
    
    Validates: Requirements 1.2, 1.3
    """
    
    symbol: str
    exchange: str
    timestamp: datetime
    seq: int
    bids: List[List[float]]  # [[price, size], ...]
    asks: List[List[float]]  # [[price, size], ...]
    spread_bps: float
    bid_depth_usd: float
    ask_depth_usd: float
    orderbook_imbalance: float
    tenant_id: str = "default"
    bot_id: str = "default"


@dataclass
class LiveValidationConfig:
    """Configuration for live data validation.
    
    This configuration controls how the LiveDataValidator monitors data
    quality in real-time during live trading. It defines thresholds for
    gap detection, completeness tracking, and metric emission.
    
    Attributes:
        enabled: Whether live data validation is enabled. When False,
            the validator will not track or emit any quality metrics.
        gap_threshold_sec: Seconds without data to count as a gap.
            When the time between consecutive updates exceeds this
            threshold, a gap is detected and counted. Default is 5.0
            seconds.
        critical_gap_sec: Seconds to classify a gap as critical.
            Gaps exceeding this threshold trigger more severe warnings
            and may indicate serious connectivity issues. Default is
            30.0 seconds.
        completeness_window_sec: Rolling window duration for calculating
            completeness percentage. The validator tracks how many
            updates were received vs expected within this window.
            Default is 60.0 seconds.
        min_completeness_pct: Minimum completeness percentage before
            triggering a warning. When completeness falls below this
            threshold, the data quality is considered degraded.
            Default is 80.0 percent.
        emit_interval_sec: Interval for emitting quality metrics to
            Redis and telemetry. Metrics are aggregated and emitted
            at this frequency. Default is 10.0 seconds.
        expected_orderbook_updates_per_sec: Expected number of orderbook
            updates per second. Used to calculate completeness percentage.
            Default is 1.0 (one update per second).
        expected_trades_per_sec: Expected number of trades per second.
            Used to calculate trade completeness percentage.
            Default is 1.0 (one trade per second).
    
    Validates: Requirements 4.2, 4.4, 4.6
    """
    
    enabled: bool = True
    gap_threshold_sec: float = 5.0
    critical_gap_sec: float = 30.0
    completeness_window_sec: float = 60.0
    min_completeness_pct: float = 80.0
    emit_interval_sec: float = 10.0
    expected_orderbook_updates_per_sec: float = 1.0
    expected_trades_per_sec: float = 1.0


@dataclass
class LiveQualityMetrics:
    """Real-time quality metrics for a symbol.
    
    This dataclass represents the current data quality state for a
    specific symbol/exchange pair. It is used by the LiveDataValidator
    to track and report data quality in real-time during live trading.
    
    The metrics are divided into three categories:
    1. Orderbook metrics - Track orderbook feed quality
    2. Trade metrics - Track trade feed quality
    3. Overall metrics - Aggregate quality assessment
    
    Attributes:
        symbol: The trading pair symbol (e.g., "BTC/USDT").
        exchange: The exchange identifier (e.g., "binance", "coinbase").
        timestamp: Unix timestamp when these metrics were calculated.
        
        orderbook_completeness_pct: Percentage of expected orderbook
            updates received within the rolling window (0.0 to 100.0).
        orderbook_gap_count: Number of detected gaps in orderbook data
            within the rolling window.
        orderbook_last_seq: The last observed sequence number from the
            orderbook feed.
        orderbook_seq_gaps: Total number of sequence gaps detected,
            indicating missed orderbook updates.
        
        trade_completeness_pct: Percentage of expected trade updates
            received within the rolling window (0.0 to 100.0).
        trade_gap_count: Number of detected gaps in trade data within
            the rolling window.
        trade_last_ts: Unix timestamp of the last received trade.
        
        quality_score: Overall quality score from 0.0 (worst) to 1.0
            (best), calculated from completeness and gap metrics.
        quality_grade: Letter grade (A, B, C, D, F) derived from
            quality_score for human-readable assessment.
        is_degraded: True if quality has fallen below the configured
            threshold, indicating potential data issues.
        warnings: List of warning messages describing current quality
            issues (e.g., "Gap detected: 15.2s without trades").
    
    Validates: Requirements 4.3, 4.4
    """
    
    symbol: str
    exchange: str
    timestamp: float
    
    # Orderbook metrics
    orderbook_completeness_pct: float
    orderbook_gap_count: int
    orderbook_last_seq: int
    orderbook_seq_gaps: int
    
    # Trade metrics
    trade_completeness_pct: float
    trade_gap_count: int
    trade_last_ts: float
    
    # Overall metrics
    quality_score: float  # 0.0 to 1.0
    quality_grade: str  # A, B, C, D, F
    is_degraded: bool
    warnings: List[str]
