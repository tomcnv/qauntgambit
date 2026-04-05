"""
Per-symbol threshold calibration for spread and depth norms.

Tracks rolling statistics for each symbol to establish "normal" conditions,
enabling dynamic thresholds based on recent history rather than fixed absolutes.

Usage:
    calibrator = SymbolCalibrator()
    
    # Feed observations
    calibrator.observe(symbol="BTCUSDT", spread_bps=2.5, bid_depth_usd=50000, ask_depth_usd=48000)
    
    # Get calibrated thresholds
    thresholds = calibrator.get_thresholds("BTCUSDT")
    # thresholds.spread_warn_bps = 5.0  (2x typical)
    # thresholds.spread_block_bps = 10.0 (4x typical)
    # thresholds.min_depth_reduce_usd = 25000  (0.5x typical)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional
from collections import deque
import time
import statistics

from quantgambit.observability.logger import log_info


@dataclass
class SymbolThresholds:
    """Calibrated thresholds for a symbol."""
    symbol: str
    
    # Spread thresholds (bps)
    spread_typical_bps: float          # Rolling median spread
    spread_warn_bps: float             # 2x typical - reduce size
    spread_block_bps: float            # 4x typical - block entries
    
    # Depth thresholds (USD)
    depth_typical_usd: float           # Rolling median depth
    depth_warn_usd: float              # 0.5x typical - reduce size  
    depth_block_usd: float             # 0.25x typical - block entries
    
    # Confidence
    sample_count: int                  # Number of observations
    calibration_quality: str           # "good" (>100 samples), "fair" (>20), "poor" (<20)
    last_updated: float                # Timestamp
    
    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "spread_typical_bps": round(self.spread_typical_bps, 2),
            "spread_warn_bps": round(self.spread_warn_bps, 2),
            "spread_block_bps": round(self.spread_block_bps, 2),
            "depth_typical_usd": round(self.depth_typical_usd, 0),
            "depth_warn_usd": round(self.depth_warn_usd, 0),
            "depth_block_usd": round(self.depth_block_usd, 0),
            "sample_count": self.sample_count,
            "calibration_quality": self.calibration_quality,
        }


@dataclass
class CalibrationConfig:
    """Configuration for symbol calibration."""
    # Sample window
    max_samples: int = 1000             # Keep last N observations
    sample_interval_sec: float = 1.0    # Minimum time between samples
    
    # Spread multipliers
    spread_warn_multiplier: float = 2.0     # Warn at 2x typical
    spread_block_multiplier: float = 4.0    # Block at 4x typical
    
    # Depth multipliers (fraction of typical)
    depth_warn_fraction: float = 0.5        # Warn at 50% of typical
    depth_block_fraction: float = 0.25      # Block at 25% of typical
    
    # Fallback absolute thresholds (when insufficient data)
    fallback_spread_warn_bps: float = 10.0
    fallback_spread_block_bps: float = 30.0
    fallback_depth_warn_usd: float = 5000.0
    fallback_depth_block_usd: float = 1000.0
    
    # Minimum calibration samples before using dynamic thresholds
    min_samples_for_calibration: int = 20
    good_samples_threshold: int = 100


@dataclass
class SymbolStats:
    """Rolling statistics for a symbol."""
    spread_samples: deque = field(default_factory=lambda: deque(maxlen=1000))
    depth_samples: deque = field(default_factory=lambda: deque(maxlen=1000))
    last_sample_time: float = 0.0
    
    def add_sample(
        self,
        spread_bps: Optional[float],
        min_depth_usd: Optional[float],
        timestamp: float,
        min_interval: float,
    ) -> bool:
        """Add a sample if enough time has passed."""
        if timestamp - self.last_sample_time < min_interval:
            return False
        
        if spread_bps is not None and spread_bps > 0:
            self.spread_samples.append(spread_bps)
        
        if min_depth_usd is not None and min_depth_usd > 0:
            self.depth_samples.append(min_depth_usd)
        
        self.last_sample_time = timestamp
        return True
    
    def spread_median(self) -> Optional[float]:
        """Get median spread."""
        if len(self.spread_samples) >= 5:
            return statistics.median(self.spread_samples)
        return None
    
    def spread_percentile(self, p: float) -> Optional[float]:
        """Get spread at given percentile (0-100)."""
        if len(self.spread_samples) >= 20:
            sorted_samples = sorted(self.spread_samples)
            idx = int(len(sorted_samples) * p / 100)
            return sorted_samples[min(idx, len(sorted_samples) - 1)]
        return None
    
    def depth_median(self) -> Optional[float]:
        """Get median depth."""
        if len(self.depth_samples) >= 5:
            return statistics.median(self.depth_samples)
        return None
    
    def depth_percentile(self, p: float) -> Optional[float]:
        """Get depth at given percentile (0-100)."""
        if len(self.depth_samples) >= 20:
            sorted_samples = sorted(self.depth_samples)
            idx = int(len(sorted_samples) * p / 100)
            return sorted_samples[min(idx, len(sorted_samples) - 1)]
        return None


class SymbolCalibrator:
    """
    Tracks rolling statistics per symbol to provide calibrated thresholds.
    
    Features:
    - Rolling median/percentile calculation for spread and depth
    - Dynamic thresholds based on recent history
    - Fallback to absolute thresholds when insufficient data
    - Confidence indicator for calibration quality
    """
    
    def __init__(self, config: Optional[CalibrationConfig] = None):
        self.config = config or CalibrationConfig()
        self._stats: Dict[str, SymbolStats] = {}
        self._cached_thresholds: Dict[str, SymbolThresholds] = {}
        self._cache_ttl_sec: float = 10.0  # Recompute thresholds every 10s
    
    def observe(
        self,
        symbol: str,
        spread_bps: Optional[float] = None,
        bid_depth_usd: Optional[float] = None,
        ask_depth_usd: Optional[float] = None,
        timestamp: Optional[float] = None,
    ) -> None:
        """
        Record an observation for a symbol.
        
        Args:
            symbol: Trading symbol
            spread_bps: Current spread in basis points
            bid_depth_usd: Bid side depth in USD
            ask_depth_usd: Ask side depth in USD
            timestamp: Observation timestamp (defaults to now)
        """
        ts = timestamp if timestamp is not None else time.time()
        
        if symbol not in self._stats:
            self._stats[symbol] = SymbolStats(
                spread_samples=deque(maxlen=self.config.max_samples),
                depth_samples=deque(maxlen=self.config.max_samples),
            )
        
        # Compute min depth for calibration
        min_depth = None
        if bid_depth_usd is not None and ask_depth_usd is not None:
            min_depth = min(bid_depth_usd, ask_depth_usd)
        elif bid_depth_usd is not None:
            min_depth = bid_depth_usd
        elif ask_depth_usd is not None:
            min_depth = ask_depth_usd
        
        self._stats[symbol].add_sample(
            spread_bps=spread_bps,
            min_depth_usd=min_depth,
            timestamp=ts,
            min_interval=self.config.sample_interval_sec,
        )
    
    def get_thresholds(self, symbol: str, now_ts: Optional[float] = None) -> SymbolThresholds:
        """
        Get calibrated thresholds for a symbol.
        
        Returns thresholds based on rolling statistics if sufficient data,
        otherwise returns fallback absolute thresholds.
        """
        # Check cache
        if now_ts is None:
            now = time.time()
        else:
            now = now_ts
        cached = self._cached_thresholds.get(symbol)
        if cached and (now - cached.last_updated) < self._cache_ttl_sec:
            return cached
        
        # Compute new thresholds
        thresholds = self._compute_thresholds(symbol, now)
        self._cached_thresholds[symbol] = thresholds
        return thresholds
    
    def _compute_thresholds(self, symbol: str, now: float) -> SymbolThresholds:
        """Compute thresholds from statistics."""
        stats = self._stats.get(symbol)
        
        if stats is None:
            # No data - return fallbacks
            return self._fallback_thresholds(symbol, sample_count=0, now=now)
        
        sample_count = len(stats.spread_samples)
        
        # Not enough samples - return fallbacks
        if sample_count < self.config.min_samples_for_calibration:
            return self._fallback_thresholds(symbol, sample_count=sample_count, now=now)
        
        # Compute spread thresholds
        spread_median = stats.spread_median() or self.config.fallback_spread_warn_bps / 2
        spread_warn = spread_median * self.config.spread_warn_multiplier
        spread_block = spread_median * self.config.spread_block_multiplier
        
        # Ensure minimums (don't let calibration make thresholds too tight)
        spread_warn = max(spread_warn, 2.0)  # At least 2 bps
        spread_block = max(spread_block, 5.0)  # At least 5 bps
        
        # Compute depth thresholds
        depth_median = stats.depth_median() or self.config.fallback_depth_warn_usd * 2
        depth_warn = depth_median * self.config.depth_warn_fraction
        depth_block = depth_median * self.config.depth_block_fraction
        
        # Ensure minimums (don't let calibration make thresholds too loose)
        depth_block = max(depth_block, 500.0)  # At least $500
        
        # Determine calibration quality
        if sample_count >= self.config.good_samples_threshold:
            quality = "good"
        elif sample_count >= self.config.min_samples_for_calibration:
            quality = "fair"
        else:
            quality = "poor"
        
        return SymbolThresholds(
            symbol=symbol,
            spread_typical_bps=spread_median,
            spread_warn_bps=spread_warn,
            spread_block_bps=spread_block,
            depth_typical_usd=depth_median,
            depth_warn_usd=depth_warn,
            depth_block_usd=depth_block,
            sample_count=sample_count,
            calibration_quality=quality,
            last_updated=now,
        )
    
    def _fallback_thresholds(self, symbol: str, sample_count: int, now: float) -> SymbolThresholds:
        """Return fallback thresholds when insufficient data."""
        return SymbolThresholds(
            symbol=symbol,
            spread_typical_bps=self.config.fallback_spread_warn_bps / 2,
            spread_warn_bps=self.config.fallback_spread_warn_bps,
            spread_block_bps=self.config.fallback_spread_block_bps,
            depth_typical_usd=self.config.fallback_depth_warn_usd * 2,
            depth_warn_usd=self.config.fallback_depth_warn_usd,
            depth_block_usd=self.config.fallback_depth_block_usd,
            sample_count=sample_count,
            calibration_quality="poor",
            last_updated=now,
        )
    
    def get_all_thresholds(self) -> Dict[str, SymbolThresholds]:
        """Get thresholds for all tracked symbols."""
        result = {}
        for symbol in self._stats:
            result[symbol] = self.get_thresholds(symbol)
        return result
    
    def get_stats_summary(self, symbol: str) -> Optional[dict]:
        """Get raw statistics for debugging."""
        stats = self._stats.get(symbol)
        if stats is None:
            return None
        
        return {
            "spread_sample_count": len(stats.spread_samples),
            "depth_sample_count": len(stats.depth_samples),
            "spread_median": stats.spread_median(),
            "spread_p95": stats.spread_percentile(95),
            "depth_median": stats.depth_median(),
            "depth_p5": stats.depth_percentile(5),
            "last_sample_time": stats.last_sample_time,
        }
    
    def reset(self, symbol: Optional[str] = None) -> None:
        """Reset calibration state."""
        if symbol:
            if symbol in self._stats:
                del self._stats[symbol]
            if symbol in self._cached_thresholds:
                del self._cached_thresholds[symbol]
        else:
            self._stats.clear()
            self._cached_thresholds.clear()


# Singleton for global access
_default_calibrator: Optional[SymbolCalibrator] = None


def get_symbol_calibrator() -> SymbolCalibrator:
    """Get the default symbol calibrator instance."""
    global _default_calibrator
    if _default_calibrator is None:
        _default_calibrator = SymbolCalibrator()
    return _default_calibrator


def set_symbol_calibrator(calibrator: SymbolCalibrator) -> None:
    """Set the default symbol calibrator instance."""
    global _default_calibrator
    _default_calibrator = calibrator
