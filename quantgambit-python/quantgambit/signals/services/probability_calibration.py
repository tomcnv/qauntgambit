"""
Probability Calibration Module for EV-Based Entry Gate.

This module implements probability calibration using Platt scaling to ensure
that model confidence outputs are well-calibrated (e.g., 60% confidence
actually means 60% win rate).

Components:
- CalibrationStorage: Interface for storing/retrieving calibration parameters
- CalibrationParams: Data class for calibration parameters
- CalibrationMetrics: Data class for calibration quality metrics
- ProbabilityCalibrator: Main calibrator class with Platt scaling

Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.8, 4.10
"""

from __future__ import annotations

import math
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Protocol
from enum import Enum


# =============================================================================
# Data Classes
# =============================================================================

class CalibrationMethod(Enum):
    """Calibration method used."""
    UNCALIBRATED = "uncalibrated"
    POOLED = "pooled"
    PER_SYMBOL = "per_symbol"
    PER_SYMBOL_REGIME = "per_symbol_regime"


@dataclass
class CalibrationParams:
    """
    Parameters for Platt scaling calibration.
    
    Platt scaling transforms raw probability p_raw to calibrated probability:
    p_calibrated = 1 / (1 + exp(a * p_raw + b))
    
    Attributes:
        method: Calibration method used
        a: Platt scaling slope parameter
        b: Platt scaling intercept parameter
        sample_count: Number of samples used for fitting
        last_fit_ts: Timestamp of last calibration fit
        brier_score: Brier score (lower is better)
        ece: Expected Calibration Error
        reliability_score: 1 - ECE (higher is better)
    """
    method: CalibrationMethod = CalibrationMethod.UNCALIBRATED
    a: float = -1.0  # Default: identity transform (approximately)
    b: float = 0.0
    sample_count: int = 0
    last_fit_ts: float = 0.0
    brier_score: float = 1.0  # Worst case
    ece: float = 1.0  # Worst case
    reliability_score: float = 0.0  # Worst case
    
    def is_valid(self) -> bool:
        """Check if calibration parameters are valid."""
        return (
            self.method != CalibrationMethod.UNCALIBRATED
            and self.sample_count > 0
            and not math.isnan(self.a)
            and not math.isnan(self.b)
        )


@dataclass
class CalibrationMetrics:
    """
    Metrics for evaluating calibration quality.
    
    Attributes:
        brier_score: Mean squared error between predictions and outcomes
        ece: Expected Calibration Error
        reliability_score: 1 - ECE
        bin_accuracies: Accuracy per probability bin (for reliability diagram)
        bin_confidences: Mean confidence per bin
        bin_counts: Sample count per bin
    """
    brier_score: float
    ece: float
    reliability_score: float
    bin_accuracies: List[float] = field(default_factory=list)
    bin_confidences: List[float] = field(default_factory=list)
    bin_counts: List[int] = field(default_factory=list)


@dataclass
class TradeOutcome:
    """
    Record of a trade outcome for calibration training.
    
    Attributes:
        symbol: Trading symbol
        regime: Market regime label
        p_raw: Raw model probability at entry
        outcome: 1 if win (hit TP), 0 if loss (hit SL)
        timestamp: Trade entry timestamp
        trade_id: Unique trade identifier
        is_closed: Whether the trade is closed (realized)
    """
    symbol: str
    regime: str
    p_raw: float
    outcome: int  # 0 or 1
    timestamp: float
    trade_id: str
    is_closed: bool = True


# =============================================================================
# CalibrationStorage Interface (Requirement 4.2)
# =============================================================================

class CalibrationStorage(ABC):
    """
    Abstract interface for storing and retrieving calibration parameters.
    
    Implementations can use in-memory storage, Redis, database, etc.
    
    Requirement 4.2: Store calibration parameters per symbol and regime.
    """
    
    @abstractmethod
    def get_params(
        self,
        symbol: str,
        regime: Optional[str] = None,
    ) -> Optional[CalibrationParams]:
        """
        Retrieve calibration parameters for a symbol/regime.
        
        Args:
            symbol: Trading symbol (e.g., "BTCUSDT")
            regime: Optional market regime label
            
        Returns:
            CalibrationParams if found, None otherwise
        """
        pass
    
    @abstractmethod
    def set_params(
        self,
        symbol: str,
        regime: Optional[str],
        params: CalibrationParams,
    ) -> None:
        """
        Store calibration parameters for a symbol/regime.
        
        Args:
            symbol: Trading symbol
            regime: Optional market regime label
            params: Calibration parameters to store
        """
        pass
    
    @abstractmethod
    def get_pooled_params(self) -> Optional[CalibrationParams]:
        """
        Retrieve pooled calibration parameters (across all symbols).
        
        Returns:
            CalibrationParams if found, None otherwise
        """
        pass
    
    @abstractmethod
    def set_pooled_params(self, params: CalibrationParams) -> None:
        """
        Store pooled calibration parameters.
        
        Args:
            params: Calibration parameters to store
        """
        pass
    
    @abstractmethod
    def get_sample_count(
        self,
        symbol: str,
        regime: Optional[str] = None,
    ) -> int:
        """
        Get the number of calibration samples for a symbol/regime.
        
        Args:
            symbol: Trading symbol
            regime: Optional market regime label
            
        Returns:
            Number of samples available
        """
        pass
    
    @abstractmethod
    def get_pooled_sample_count(self) -> int:
        """
        Get the total number of pooled calibration samples.
        
        Returns:
            Total number of samples across all symbols
        """
        pass


class InMemoryCalibrationStorage(CalibrationStorage):
    """
    In-memory implementation of CalibrationStorage.
    
    Suitable for testing and single-process deployments.
    """
    
    def __init__(self):
        self._params: Dict[str, CalibrationParams] = {}
        self._sample_counts: Dict[str, int] = {}
        self._pooled_params: Optional[CalibrationParams] = None
        self._pooled_sample_count: int = 0
    
    def _make_key(self, symbol: str, regime: Optional[str]) -> str:
        """Create storage key from symbol and regime."""
        if regime:
            return f"{symbol}:{regime}"
        return symbol
    
    def get_params(
        self,
        symbol: str,
        regime: Optional[str] = None,
    ) -> Optional[CalibrationParams]:
        key = self._make_key(symbol, regime)
        return self._params.get(key)
    
    def set_params(
        self,
        symbol: str,
        regime: Optional[str],
        params: CalibrationParams,
    ) -> None:
        key = self._make_key(symbol, regime)
        self._params[key] = params
        self._sample_counts[key] = params.sample_count
    
    def get_pooled_params(self) -> Optional[CalibrationParams]:
        return self._pooled_params
    
    def set_pooled_params(self, params: CalibrationParams) -> None:
        self._pooled_params = params
        self._pooled_sample_count = params.sample_count
    
    def get_sample_count(
        self,
        symbol: str,
        regime: Optional[str] = None,
    ) -> int:
        key = self._make_key(symbol, regime)
        return self._sample_counts.get(key, 0)
    
    def get_pooled_sample_count(self) -> int:
        return self._pooled_sample_count
    
    def clear(self) -> None:
        """Clear all stored calibration data."""
        self._params.clear()
        self._sample_counts.clear()
        self._pooled_params = None
        self._pooled_sample_count = 0




# =============================================================================
# Calibration Configuration
# =============================================================================

@dataclass
class ProbabilityCalibrationConfig:
    """
    Configuration for probability calibration.
    
    Attributes:
        min_samples_pooled: Minimum samples for pooled calibration (Req 4.6)
        min_samples_per_symbol: Minimum samples for per-symbol calibration (Req 4.4)
        min_samples_per_symbol_regime: Minimum samples for per-symbol-regime (Req 4.5)
        num_bins: Number of bins for ECE calculation
        calibration_window_days: Days of data to use for calibration (Req 4.7)
        p_margin_uncalibrated: EV_Min increase when uncalibrated (Req 4.6)
        min_reliability_score: Minimum reliability for using calibration
    """
    min_samples_pooled: int = 200
    min_samples_per_symbol: int = 200
    min_samples_per_symbol_regime: int = 1000
    num_bins: int = 10
    calibration_window_days: int = 30
    p_margin_uncalibrated: float = 0.02
    min_reliability_score: float = 0.6


# =============================================================================
# ProbabilityCalibrator (Requirements 4.1, 4.3, 4.4, 4.5, 4.10)
# =============================================================================

class ProbabilityCalibrator:
    """
    Calibrates raw model probabilities using Platt scaling.
    
    Implements tiered calibration:
    - < 200 samples: pooled calibration across all symbols (Req 4.3)
    - 200-1000 samples: per-symbol calibration (Req 4.4)
    - >= 1000 samples: per-symbol-per-regime calibration (Req 4.5)
    
    Requirements: 4.1, 4.3, 4.4, 4.5, 4.10
    """
    
    def __init__(
        self,
        storage: Optional[CalibrationStorage] = None,
        config: Optional[ProbabilityCalibrationConfig] = None,
    ):
        """
        Initialize ProbabilityCalibrator.
        
        Args:
            storage: CalibrationStorage instance. Uses InMemoryCalibrationStorage if None.
            config: Configuration. Uses defaults if None.
        """
        self.storage = storage or InMemoryCalibrationStorage()
        self.config = config or ProbabilityCalibrationConfig()
        self._cache: Dict[str, Tuple[CalibrationParams, float]] = {}  # key -> (params, cache_ts)
        self._cache_ttl_sec: float = 60.0  # Cache TTL in seconds
    
    def calibrate(
        self,
        p_raw: float,
        symbol: str,
        regime: Optional[str] = None,
    ) -> Tuple[float, CalibrationMethod, float]:
        """
        Calibrate a raw probability using the appropriate calibration tier.
        
        Args:
            p_raw: Raw model probability (0 to 1)
            symbol: Trading symbol
            regime: Optional market regime label
            
        Returns:
            Tuple of (p_calibrated, method_used, reliability_score)
            
        Requirements: 4.3, 4.4, 4.5
        """
        # Clamp input to valid range
        p_raw = max(0.0, min(1.0, p_raw))
        
        # Get calibration parameters using tiering logic
        params, method = self._get_calibration_params(symbol, regime)
        
        if params is None or not params.is_valid():
            # No valid calibration available - return uncalibrated
            return p_raw, CalibrationMethod.UNCALIBRATED, 0.0
        
        # Apply Platt scaling: p_calibrated = 1 / (1 + exp(a * p_raw + b))
        p_calibrated = self._apply_platt_scaling(p_raw, params.a, params.b)
        
        return p_calibrated, params.method, params.reliability_score
    
    def _get_calibration_params(
        self,
        symbol: str,
        regime: Optional[str],
    ) -> Tuple[Optional[CalibrationParams], CalibrationMethod]:
        """
        Get calibration parameters using tiering logic.
        
        Tiering (Requirements 4.3, 4.4, 4.5):
        - >= 1000 samples for symbol+regime: use per-symbol-regime
        - >= 200 samples for symbol: use per-symbol
        - >= 200 pooled samples: use pooled
        - Otherwise: uncalibrated
        """
        # Check per-symbol-regime first (highest tier)
        if regime:
            symbol_regime_count = self.storage.get_sample_count(symbol, regime)
            if symbol_regime_count >= self.config.min_samples_per_symbol_regime:
                params = self.storage.get_params(symbol, regime)
                if params and params.is_valid():
                    return params, CalibrationMethod.PER_SYMBOL_REGIME
        
        # Check per-symbol (middle tier)
        symbol_count = self.storage.get_sample_count(symbol, None)
        if symbol_count >= self.config.min_samples_per_symbol:
            params = self.storage.get_params(symbol, None)
            if params and params.is_valid():
                return params, CalibrationMethod.PER_SYMBOL
        
        # Check pooled (lowest tier)
        pooled_count = self.storage.get_pooled_sample_count()
        if pooled_count >= self.config.min_samples_pooled:
            params = self.storage.get_pooled_params()
            if params and params.is_valid():
                return params, CalibrationMethod.POOLED
        
        # No valid calibration available
        return None, CalibrationMethod.UNCALIBRATED
    
    def _apply_platt_scaling(self, p_raw: float, a: float, b: float) -> float:
        """
        Apply Platt scaling transformation.
        
        Formula: p_calibrated = 1 / (1 + exp(a * p_raw + b))
        
        Note: For well-calibrated models, a ≈ -1 and b ≈ 0 (identity transform).
        """
        try:
            exponent = a * p_raw + b
            # Clamp to avoid overflow
            exponent = max(-700, min(700, exponent))
            p_calibrated = 1.0 / (1.0 + math.exp(exponent))
            return max(0.0, min(1.0, p_calibrated))
        except (OverflowError, ValueError):
            return p_raw
    
    def fit(
        self,
        predictions: List[float],
        outcomes: List[int],
        symbol: Optional[str] = None,
        regime: Optional[str] = None,
    ) -> CalibrationParams:
        """
        Fit Platt scaling calibration using predictions and outcomes.
        
        Uses logistic regression to find optimal a, b parameters.
        
        Args:
            predictions: List of raw model probabilities
            outcomes: List of outcomes (0 = loss, 1 = win)
            symbol: Optional symbol for per-symbol calibration
            regime: Optional regime for per-symbol-regime calibration
            
        Returns:
            Fitted CalibrationParams
            
        Requirement 4.1: Implement Platt scaling calibration
        """
        if len(predictions) != len(outcomes):
            raise ValueError("predictions and outcomes must have same length")
        
        if len(predictions) < 10:
            # Not enough data for meaningful calibration
            return CalibrationParams(
                method=CalibrationMethod.UNCALIBRATED,
                sample_count=len(predictions),
            )
        
        # Fit Platt scaling using gradient descent
        a, b = self._fit_platt_params(predictions, outcomes)
        
        # Compute calibration metrics
        metrics = self.compute_metrics(predictions, outcomes, a, b)
        
        # Determine method based on context
        if symbol and regime:
            method = CalibrationMethod.PER_SYMBOL_REGIME
        elif symbol:
            method = CalibrationMethod.PER_SYMBOL
        else:
            method = CalibrationMethod.POOLED
        
        params = CalibrationParams(
            method=method,
            a=a,
            b=b,
            sample_count=len(predictions),
            last_fit_ts=time.time(),
            brier_score=metrics.brier_score,
            ece=metrics.ece,
            reliability_score=metrics.reliability_score,
        )
        
        # Store the fitted parameters
        if symbol and regime:
            self.storage.set_params(symbol, regime, params)
        elif symbol:
            self.storage.set_params(symbol, None, params)
        else:
            self.storage.set_pooled_params(params)
        
        return params
    
    def _fit_platt_params(
        self,
        predictions: List[float],
        outcomes: List[int],
        max_iter: int = 100,
        lr: float = 0.1,
        tol: float = 1e-6,
    ) -> Tuple[float, float]:
        """
        Fit Platt scaling parameters using gradient descent.
        
        Minimizes negative log-likelihood:
        NLL = -sum(y * log(p) + (1-y) * log(1-p))
        
        where p = 1 / (1 + exp(a * p_raw + b))
        """
        # Initialize parameters (start near identity transform)
        a = -1.0
        b = 0.0
        
        n = len(predictions)
        eps = 1e-15  # For numerical stability
        
        for _ in range(max_iter):
            # Compute calibrated probabilities
            p_cal = []
            for p_raw in predictions:
                exponent = max(-700, min(700, a * p_raw + b))
                p = 1.0 / (1.0 + math.exp(exponent))
                p_cal.append(max(eps, min(1 - eps, p)))
            
            # Compute gradients
            grad_a = 0.0
            grad_b = 0.0
            
            for i in range(n):
                y = outcomes[i]
                p = p_cal[i]
                p_raw = predictions[i]
                
                # Gradient of NLL with respect to a and b
                # d(NLL)/da = sum((p - y) * p_raw)
                # d(NLL)/db = sum(p - y)
                error = p - y
                grad_a += error * p_raw
                grad_b += error
            
            grad_a /= n
            grad_b /= n
            
            # Update parameters
            a_new = a - lr * grad_a
            b_new = b - lr * grad_b
            
            # Check convergence
            if abs(a_new - a) < tol and abs(b_new - b) < tol:
                break
            
            a = a_new
            b = b_new
        
        return a, b
    
    def compute_metrics(
        self,
        predictions: List[float],
        outcomes: List[int],
        a: Optional[float] = None,
        b: Optional[float] = None,
    ) -> CalibrationMetrics:
        """
        Compute calibration quality metrics.
        
        Args:
            predictions: List of raw model probabilities
            outcomes: List of outcomes (0 = loss, 1 = win)
            a: Optional Platt scaling parameter (if None, use raw predictions)
            b: Optional Platt scaling parameter
            
        Returns:
            CalibrationMetrics with Brier score, ECE, reliability score
            
        Requirement 4.10: Compute Brier score and ECE
        """
        if len(predictions) != len(outcomes):
            raise ValueError("predictions and outcomes must have same length")
        
        n = len(predictions)
        if n == 0:
            return CalibrationMetrics(
                brier_score=1.0,
                ece=1.0,
                reliability_score=0.0,
            )
        
        # Apply calibration if parameters provided
        if a is not None and b is not None:
            calibrated = [self._apply_platt_scaling(p, a, b) for p in predictions]
        else:
            calibrated = predictions
        
        # Compute Brier score: mean((p - y)^2)
        brier_score = sum((p - y) ** 2 for p, y in zip(calibrated, outcomes)) / n
        
        # Compute ECE using binning
        num_bins = self.config.num_bins
        bin_boundaries = [i / num_bins for i in range(num_bins + 1)]
        
        bin_accuracies = []
        bin_confidences = []
        bin_counts = []
        
        for i in range(num_bins):
            lower = bin_boundaries[i]
            upper = bin_boundaries[i + 1]
            
            # Get samples in this bin
            bin_preds = []
            bin_outcomes = []
            for p, y in zip(calibrated, outcomes):
                if lower <= p < upper or (i == num_bins - 1 and p == upper):
                    bin_preds.append(p)
                    bin_outcomes.append(y)
            
            if len(bin_preds) > 0:
                bin_acc = sum(bin_outcomes) / len(bin_outcomes)
                bin_conf = sum(bin_preds) / len(bin_preds)
                bin_accuracies.append(bin_acc)
                bin_confidences.append(bin_conf)
                bin_counts.append(len(bin_preds))
            else:
                bin_accuracies.append(0.0)
                bin_confidences.append((lower + upper) / 2)
                bin_counts.append(0)
        
        # ECE = weighted average of |accuracy - confidence| per bin
        ece = 0.0
        total_samples = sum(bin_counts)
        if total_samples > 0:
            for acc, conf, count in zip(bin_accuracies, bin_confidences, bin_counts):
                ece += (count / total_samples) * abs(acc - conf)
        
        reliability_score = 1.0 - ece
        
        return CalibrationMetrics(
            brier_score=brier_score,
            ece=ece,
            reliability_score=reliability_score,
            bin_accuracies=bin_accuracies,
            bin_confidences=bin_confidences,
            bin_counts=bin_counts,
        )
    
    def get_calibration_status(
        self,
        symbol: str,
        regime: Optional[str] = None,
    ) -> Dict:
        """
        Get calibration status for a symbol/regime.
        
        Returns dict with calibration_method, sample_count, last_calibration_ts,
        brier_score, ece, reliability_score.
        
        Requirement 4.9: Display calibration status
        """
        params, method = self._get_calibration_params(symbol, regime)
        
        if params is None:
            return {
                "calibration_method": CalibrationMethod.UNCALIBRATED.value,
                "sample_count": 0,
                "last_calibration_ts": None,
                "brier_score": None,
                "ece": None,
                "reliability_score": 0.0,
            }
        
        return {
            "calibration_method": params.method.value,
            "sample_count": params.sample_count,
            "last_calibration_ts": params.last_fit_ts,
            "brier_score": params.brier_score,
            "ece": params.ece,
            "reliability_score": params.reliability_score,
        }



# =============================================================================
# Uncalibrated Fallback Helper (Requirement 4.6)
# =============================================================================

def get_ev_min_adjustment(
    calibration_method: CalibrationMethod,
    reliability_score: float,
    config: ProbabilityCalibrationConfig,
) -> Tuple[float, str]:
    """
    Get EV_Min adjustment based on calibration quality.
    
    When calibration is unavailable or unreliable, increase EV_Min
    to be more conservative.
    
    Args:
        calibration_method: The calibration method used
        reliability_score: Reliability score (1 - ECE)
        config: Calibration configuration
        
    Returns:
        Tuple of (ev_min_margin, reason)
        
    Requirement 4.6: Use uncalibrated p with EV_Min margin when insufficient samples
    """
    if calibration_method == CalibrationMethod.UNCALIBRATED:
        return config.p_margin_uncalibrated, "uncalibrated"
    
    if reliability_score < config.min_reliability_score:
        return config.p_margin_uncalibrated, "low_reliability"
    
    return 0.0, None


# =============================================================================
# Trade Outcome Collector with Leakage Prevention (Requirement 4.8)
# =============================================================================

class TradeOutcomeCollector:
    """
    Collects trade outcomes for calibration training with leakage prevention.
    
    Ensures:
    - Only closed trades are used for calibration (Requirement 4.8)
    - Data after calibration timestamp is excluded (no lookahead)
    - Trades still open are excluded from training
    
    Requirement 4.8: Exclude open trades and data after calibration timestamp
    """
    
    def __init__(
        self,
        calibration_window_days: int = 30,
    ):
        """
        Initialize TradeOutcomeCollector.
        
        Args:
            calibration_window_days: Days of data to use for calibration
        """
        self._outcomes: List[TradeOutcome] = []
        self._open_trade_ids: set = set()
        self._calibration_window_days = calibration_window_days
    
    def record_entry(
        self,
        trade_id: str,
        symbol: str,
        regime: str,
        p_raw: float,
        timestamp: float,
    ) -> None:
        """
        Record a trade entry (before outcome is known).
        
        Args:
            trade_id: Unique trade identifier
            symbol: Trading symbol
            regime: Market regime label
            p_raw: Raw model probability at entry
            timestamp: Trade entry timestamp
        """
        self._open_trade_ids.add(trade_id)
        # Store pending outcome
        self._outcomes.append(TradeOutcome(
            symbol=symbol,
            regime=regime,
            p_raw=p_raw,
            outcome=-1,  # Unknown
            timestamp=timestamp,
            trade_id=trade_id,
            is_closed=False,
        ))
    
    def record_outcome(
        self,
        trade_id: str,
        outcome: int,
        close_timestamp: float,
    ) -> None:
        """
        Record a trade outcome (when trade closes).
        
        Args:
            trade_id: Unique trade identifier
            outcome: 1 if win (hit TP), 0 if loss (hit SL)
            close_timestamp: Trade close timestamp
        """
        self._open_trade_ids.discard(trade_id)
        
        # Find and update the outcome
        for i, o in enumerate(self._outcomes):
            if o.trade_id == trade_id:
                self._outcomes[i] = TradeOutcome(
                    symbol=o.symbol,
                    regime=o.regime,
                    p_raw=o.p_raw,
                    outcome=outcome,
                    timestamp=o.timestamp,
                    trade_id=trade_id,
                    is_closed=True,
                )
                break
    
    def get_training_data(
        self,
        symbol: Optional[str] = None,
        regime: Optional[str] = None,
        cutoff_timestamp: Optional[float] = None,
    ) -> Tuple[List[float], List[int]]:
        """
        Get training data for calibration with leakage prevention.
        
        Args:
            symbol: Optional filter by symbol
            regime: Optional filter by regime
            cutoff_timestamp: Exclude data after this timestamp (for backtesting)
            
        Returns:
            Tuple of (predictions, outcomes) lists
            
        Requirement 4.8: Exclude open trades and data after calibration timestamp
        """
        if cutoff_timestamp is None:
            cutoff_timestamp = time.time()
        
        # Calculate window start
        window_start = cutoff_timestamp - (self._calibration_window_days * 24 * 3600)
        
        predictions = []
        outcomes = []
        
        for o in self._outcomes:
            # Skip open trades (leakage prevention)
            if not o.is_closed:
                continue
            
            # Skip trades after cutoff (no lookahead)
            if o.timestamp > cutoff_timestamp:
                continue
            
            # Skip trades before window
            if o.timestamp < window_start:
                continue
            
            # Skip invalid outcomes
            if o.outcome not in (0, 1):
                continue
            
            # Apply filters
            if symbol and o.symbol != symbol:
                continue
            if regime and o.regime != regime:
                continue
            
            predictions.append(o.p_raw)
            outcomes.append(o.outcome)
        
        return predictions, outcomes
    
    def get_sample_counts(self) -> Dict[str, int]:
        """
        Get sample counts by symbol and regime.
        
        Returns:
            Dict with keys like "BTCUSDT", "BTCUSDT:trending", etc.
        """
        counts: Dict[str, int] = {}
        pooled_count = 0
        
        for o in self._outcomes:
            if not o.is_closed or o.outcome not in (0, 1):
                continue
            
            # Count by symbol
            symbol_key = o.symbol
            counts[symbol_key] = counts.get(symbol_key, 0) + 1
            
            # Count by symbol+regime
            if o.regime:
                regime_key = f"{o.symbol}:{o.regime}"
                counts[regime_key] = counts.get(regime_key, 0) + 1
            
            pooled_count += 1
        
        counts["_pooled"] = pooled_count
        return counts
    
    def prune_old_data(self, max_age_days: int = 90) -> int:
        """
        Remove old data to prevent unbounded growth.
        
        Args:
            max_age_days: Remove data older than this
            
        Returns:
            Number of records removed
        """
        cutoff = time.time() - (max_age_days * 24 * 3600)
        original_count = len(self._outcomes)
        
        self._outcomes = [
            o for o in self._outcomes
            if o.timestamp >= cutoff or not o.is_closed
        ]
        
        return original_count - len(self._outcomes)
    
    def clear(self) -> None:
        """Clear all collected data."""
        self._outcomes.clear()
        self._open_trade_ids.clear()


# =============================================================================
# Calibration Manager (Combines all components)
# =============================================================================

class CalibrationManager:
    """
    High-level manager for probability calibration.
    
    Combines:
    - TradeOutcomeCollector for data collection
    - ProbabilityCalibrator for calibration
    - Automatic recalibration scheduling
    
    Requirements: 4.1-4.10
    """
    
    def __init__(
        self,
        storage: Optional[CalibrationStorage] = None,
        config: Optional[ProbabilityCalibrationConfig] = None,
    ):
        """
        Initialize CalibrationManager.
        
        Args:
            storage: CalibrationStorage instance
            config: Configuration
        """
        self.config = config or ProbabilityCalibrationConfig()
        self.storage = storage or InMemoryCalibrationStorage()
        self.calibrator = ProbabilityCalibrator(self.storage, self.config)
        self.collector = TradeOutcomeCollector(self.config.calibration_window_days)
        self._last_recalibration_ts: float = 0.0
        self._recalibration_interval_sec: float = 7 * 24 * 3600  # Weekly (Req 4.7)
    
    def calibrate_probability(
        self,
        p_raw: float,
        symbol: str,
        regime: Optional[str] = None,
    ) -> Tuple[float, CalibrationMethod, float, float]:
        """
        Calibrate a raw probability and get EV_Min adjustment.
        
        Args:
            p_raw: Raw model probability
            symbol: Trading symbol
            regime: Optional market regime
            
        Returns:
            Tuple of (p_calibrated, method, reliability_score, ev_min_margin)
        """
        p_calibrated, method, reliability = self.calibrator.calibrate(p_raw, symbol, regime)
        ev_min_margin, _ = get_ev_min_adjustment(method, reliability, self.config)
        
        return p_calibrated, method, reliability, ev_min_margin
    
    def record_trade_entry(
        self,
        trade_id: str,
        symbol: str,
        regime: str,
        p_raw: float,
        timestamp: Optional[float] = None,
    ) -> None:
        """Record a trade entry for future calibration."""
        self.collector.record_entry(
            trade_id=trade_id,
            symbol=symbol,
            regime=regime,
            p_raw=p_raw,
            timestamp=timestamp or time.time(),
        )
    
    def record_trade_outcome(
        self,
        trade_id: str,
        outcome: int,
        close_timestamp: Optional[float] = None,
    ) -> None:
        """Record a trade outcome."""
        self.collector.record_outcome(
            trade_id=trade_id,
            outcome=outcome,
            close_timestamp=close_timestamp or time.time(),
        )
    
    def recalibrate_all(self, force: bool = False) -> Dict[str, CalibrationParams]:
        """
        Recalibrate all symbols/regimes if due.
        
        Args:
            force: Force recalibration even if not due
            
        Returns:
            Dict of calibration results by key
            
        Requirement 4.7: Recalibrate weekly
        """
        now = time.time()
        
        if not force and (now - self._last_recalibration_ts) < self._recalibration_interval_sec:
            return {}
        
        results = {}
        sample_counts = self.collector.get_sample_counts()
        
        # Fit pooled calibration
        pooled_preds, pooled_outcomes = self.collector.get_training_data()
        if len(pooled_preds) >= self.config.min_samples_pooled:
            params = self.calibrator.fit(pooled_preds, pooled_outcomes)
            results["_pooled"] = params
        
        # Fit per-symbol and per-symbol-regime calibrations
        symbols_seen = set()
        for key, count in sample_counts.items():
            if key == "_pooled":
                continue
            
            if ":" in key:
                # Per-symbol-regime
                symbol, regime = key.split(":", 1)
                if count >= self.config.min_samples_per_symbol_regime:
                    preds, outcomes = self.collector.get_training_data(symbol, regime)
                    if len(preds) >= self.config.min_samples_per_symbol_regime:
                        params = self.calibrator.fit(preds, outcomes, symbol, regime)
                        results[key] = params
            else:
                # Per-symbol
                symbol = key
                if symbol not in symbols_seen and count >= self.config.min_samples_per_symbol:
                    preds, outcomes = self.collector.get_training_data(symbol)
                    if len(preds) >= self.config.min_samples_per_symbol:
                        params = self.calibrator.fit(preds, outcomes, symbol)
                        results[symbol] = params
                    symbols_seen.add(symbol)
        
        self._last_recalibration_ts = now
        return results
    
    def get_status(self, symbol: str, regime: Optional[str] = None) -> Dict:
        """Get calibration status for a symbol/regime."""
        return self.calibrator.get_calibration_status(symbol, regime)
