"""
EVGateStage - Expected Value based entry filtering.

This module implements EV-based entry filtering that replaces the fixed 50%
confidence threshold with a proper expected value calculation that accounts
for reward-to-risk ratio (R) and costs (C).

Formula: EV = p × R - (1 - p) × 1 - C
Implied threshold: p > (1 + C) / (R + 1)

Requirements: 1.1-1.8, 2.1-2.8, 3.1-3.7

Phase 3 Integration: Uses ExecutionPolicy and SlippageModel for accurate cost estimation.
"""

from __future__ import annotations

import os
import math
import time
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Optional, List, Tuple, TYPE_CHECKING, Any, Union

from quantgambit.signals.pipeline import Stage, StageContext, StageResult
from quantgambit.observability.logger import log_info, log_warning, log_error
from quantgambit.execution.execution_policy import ExecutionPolicy
from quantgambit.risk.slippage_model import SlippageModel, calculate_adverse_selection_bps
from quantgambit.risk.fee_model import FeeModel, FeeConfig
from quantgambit.signals.services.calibration_state import (
    CalibrationState,
    CalibrationStatus,
    evaluate_calibration,
    get_strategy_prior,
)

if TYPE_CHECKING:
    from quantgambit.observability.blocked_signal_telemetry import BlockedSignalTelemetry
    from quantgambit.signals.services.strategy_diagnostics import StrategyDiagnostics

# Import metrics collector for recording decisions
try:
    from quantgambit.api.ev_gate_endpoints import get_metrics_collector, EVGateDecisionLog
    _HAS_METRICS_COLLECTOR = True
except ImportError:
    _HAS_METRICS_COLLECTOR = False


class EVGateRejectCode(Enum):
    """Stable reject codes for telemetry and dashboards."""
    
    # Input validation
    MISSING_STOP_LOSS = "MISSING_STOP_LOSS"
    MISSING_TAKE_PROFIT = "MISSING_TAKE_PROFIT"
    MISSING_REQUIRED_FIELD = "MISSING_REQUIRED_FIELD"
    INVALID_SL = "INVALID_SL"  # L <= 0
    INVALID_R = "INVALID_R"  # R <= 0 or NaN
    INVALID_P = "INVALID_P"  # p outside [0, 1]
    
    # Edge cases
    STOP_TOO_TIGHT = "STOP_TOO_TIGHT"  # L < min_stop_distance_bps
    COST_EXCEEDS_SL = "COST_EXCEEDS_SL"  # C > 1.0

    # Data quality
    STALE_BOOK = "STALE_BOOK"
    STALE_SPREAD = "STALE_SPREAD"
    EXCHANGE_CONNECTIVITY = "EXCHANGE_CONNECTIVITY"
    ORDERBOOK_SYNC = "ORDERBOOK_SYNC"
    
    # EV threshold
    EV_BELOW_MIN = "EV_BELOW_MIN"
    P_BELOW_PMIN = "P_BELOW_PMIN"
    EXPECTED_EDGE_BELOW_MIN = "EXPECTED_EDGE_BELOW_MIN"


# =============================================================================
# Conservative p_hat fallback values (Requirement 5)
# These are LOWER than before to be conservative when uncalibrated
# =============================================================================
REGIME_P_HAT_DEFAULTS_CONSERVATIVE = {
    "mean_reversion": 0.48,  # Was 0.52
    "breakout": 0.45,        # Was 0.48
    "trend_pullback": 0.47,
    "low_vol_grind": 0.48,
    "default": 0.45,         # Was 0.50
}

# Margin to add to ev_min when using uncalibrated p_hat (Requirement 5.4)
P_MARGIN_UNCALIBRATED_DEFAULT = 0.03  # Was 0.02
P_MIN_TOLERANCE_MEAN_REVERSION_DEFAULT = 0.015
EXPECTED_EDGE_TOLERANCE_MEAN_REVERSION_BPS_DEFAULT = 8.0


@dataclass
class EVGateConfig:
    """Configuration for EV-based entry gate.
    
    Attributes:
        ev_min: Minimum EV threshold (default 0.02)
        ev_min_floor: Absolute minimum after relaxation (default 0.01)
        adverse_selection_bps: Buffer for market orders (default 1.5)
        min_slippage_bps: Floor for slippage estimate (default 0.5)
        max_book_age_ms: Maximum orderbook staleness (default 250)
        max_spread_age_ms: Maximum spread data staleness (default 250)
        min_stop_distance_bps: Minimum stop loss distance (default 5.0)
        p_margin_uncalibrated: EV_Min increase when uncalibrated (default 0.03)
        min_reliability_score: Minimum calibration reliability (default 0.6)
        min_expected_edge_bps: Minimum expected net edge in bps after costs (default 0.0)
        max_exchange_latency_ms: Maximum exchange latency (default 500)
        mode: "shadow" or "enforce" (default "enforce")
    """
    ev_min: float = 0.02
    ev_min_floor: float = 0.01
    adverse_selection_bps: float = 1.5
    min_slippage_bps: float = 0.5
    max_book_age_ms: int = 250
    max_spread_age_ms: int = 250
    min_stop_distance_bps: float = 5.0
    p_margin_uncalibrated: float = 0.03  # Updated from 0.02 per Requirement 5.4
    min_reliability_score: float = 0.6
    min_expected_edge_bps: float = 0.0
    min_expected_edge_bps_by_symbol: dict[str, float] = field(default_factory=dict)
    min_expected_edge_bps_by_side: dict[str, float] = field(default_factory=dict)
    min_expected_edge_bps_by_symbol_side: dict[str, float] = field(default_factory=dict)
    
    # Safety guard parameters (Requirement 10.2)
    max_exchange_latency_ms: int = 500
    
    # Relaxation parameters
    relaxation_spread_percentile: float = 0.30
    relaxation_multiplier: float = 0.8
    tightening_spread_percentile: float = 0.70
    tightening_multiplier: float = 1.25
    
    # Mode
    mode: str = "enforce"  # "shadow" or "enforce"
    
    def __post_init__(self):
        """Validate configuration parameters."""
        if self.ev_min < 0:
            raise ValueError(f"ev_min must be non-negative, got {self.ev_min}")
        if self.ev_min_floor < 0:
            raise ValueError(f"ev_min_floor must be non-negative, got {self.ev_min_floor}")
        if self.ev_min_floor > self.ev_min:
            raise ValueError(f"ev_min_floor ({self.ev_min_floor}) must be <= ev_min ({self.ev_min})")
        if self.adverse_selection_bps < 0:
            raise ValueError(f"adverse_selection_bps must be non-negative, got {self.adverse_selection_bps}")
        if self.min_slippage_bps < 0:
            raise ValueError(f"min_slippage_bps must be non-negative, got {self.min_slippage_bps}")
        if self.max_book_age_ms <= 0:
            raise ValueError(f"max_book_age_ms must be positive, got {self.max_book_age_ms}")
        if self.max_exchange_latency_ms <= 0:
            raise ValueError(f"max_exchange_latency_ms must be positive, got {self.max_exchange_latency_ms}")
        if self.min_stop_distance_bps <= 0:
            raise ValueError(f"min_stop_distance_bps must be positive, got {self.min_stop_distance_bps}")
        if self.min_expected_edge_bps < 0:
            raise ValueError(
                f"min_expected_edge_bps must be non-negative, got {self.min_expected_edge_bps}"
            )
        for symbol, threshold in self.min_expected_edge_bps_by_symbol.items():
            if threshold < 0:
                raise ValueError(
                    f"min_expected_edge_bps_by_symbol[{symbol}] must be non-negative, got {threshold}"
                )
        for side, threshold in self.min_expected_edge_bps_by_side.items():
            if side not in {"long", "short"}:
                raise ValueError(
                    f"min_expected_edge_bps_by_side key must be long/short, got {side}"
                )
            if threshold < 0:
                raise ValueError(
                    f"min_expected_edge_bps_by_side[{side}] must be non-negative, got {threshold}"
                )
        for symbol_side, threshold in self.min_expected_edge_bps_by_symbol_side.items():
            if ":" not in symbol_side:
                raise ValueError(
                    f"min_expected_edge_bps_by_symbol_side key must be SYMBOL:SIDE, got {symbol_side}"
                )
            if threshold < 0:
                raise ValueError(
                    f"min_expected_edge_bps_by_symbol_side[{symbol_side}] must be non-negative, got {threshold}"
                )
        if self.mode not in ("shadow", "enforce"):
            raise ValueError(f"mode must be 'shadow' or 'enforce', got {self.mode}")


@dataclass
class CostEstimate:
    """
    Result of cost estimation.
    
    FIX #5: Cost component definitions (all values are ROUND-TRIP):
    - spread_bps: Full spread (ask-bid)/mid, representing round-trip crossing cost
                  (half-spread on entry + half-spread on exit)
    - fee_bps: Expected round-trip fees, weighted by maker/taker probabilities
               from ExecutionPolicy
    - slippage_bps: Incremental price impact beyond spread, round-trip
                    (does NOT include spread, which is separate)
    - adverse_selection_bps: Incremental adverse selection cost, round-trip
    - total_bps: Sum of all components (spread + fee + slippage + adverse_selection)
    """
    spread_bps: float
    fee_bps: float
    slippage_bps: float
    adverse_selection_bps: float
    total_bps: float


@dataclass
class EVGateResult:
    """Result of EV gate evaluation."""
    
    # Decision
    decision: str  # "ACCEPT" or "REJECT"
    reject_code: Optional[EVGateRejectCode] = None
    reject_reason: Optional[str] = None
    
    # Calculated values
    L_bps: float = 0.0  # Stop loss distance in bps
    G_bps: float = 0.0  # Take profit distance in bps
    R: float = 0.0  # Reward-to-risk ratio
    C: float = 0.0  # Cost ratio
    EV: float = 0.0  # Expected value
    expected_gross_edge_bps: float = 0.0  # p*G - (1-p)*L (before costs)
    expected_net_edge_bps: float = 0.0  # expected_gross_edge_bps - total_cost_bps
    min_expected_edge_bps: float = 0.0  # configured minimum net edge
    p_min: float = 0.0  # Implied minimum probability
    p_calibrated: float = 0.0  # Calibrated probability used
    
    # Cost breakdown
    spread_bps: float = 0.0
    fee_bps: float = 0.0
    slippage_bps: float = 0.0
    adverse_selection_bps: float = 0.0
    total_cost_bps: float = 0.0
    
    # Threshold info
    ev_min_base: float = 0.0
    ev_min_adjusted: float = 0.0
    adjustment_factor: float = 1.0
    adjustment_reason: Optional[str] = None
    
    # Metadata
    calibration_method: str = "uncalibrated"
    calibration_reliability: float = 0.0
    book_age_ms: float = 0.0
    spread_age_ms: float = 0.0
    
    # p_hat source tracking (Requirement 5)
    p_hat_source: str = "calibrated"  # "calibrated" or "uncalibrated_conservative"
    defaulted_fields: Optional[dict] = None  # Fields that were defaulted


# =============================================================================
# Core EV Calculation Functions
# Requirements: 1.1, 1.2, 1.3, 1.4, 1.6
# =============================================================================

def calculate_L_G_R(
    entry_price: float,
    stop_loss: float,
    take_profit: float,
    side: str,
) -> Tuple[float, float, float]:
    """
    Calculate L (stop distance), G (profit distance), and R (reward-to-risk).
    
    FIX #2: Reject wrong-side SL/TP instead of abs()-masking it.
    Wrong-side geometry returns (0, 0, NaN) so caller rejects with INVALID_SL/INVALID_R.
    
    Args:
        entry_price: Entry price
        stop_loss: Stop loss price
        take_profit: Take profit price
        side: "long" or "short"
        
    Returns:
        Tuple of (L_bps, G_bps, R)
        Returns (0, 0, NaN) for invalid geometry (wrong-side SL/TP)
        
    Requirements: 1.1, 1.2
    """
    if entry_price <= 0:
        return 0.0, 0.0, float('nan')
    
    side_l = side.lower()
    
    if side_l == "long":
        # Long: stop below entry, take profit above entry
        L_raw = (entry_price - stop_loss) / entry_price * 10000  # bps
        G_raw = (take_profit - entry_price) / entry_price * 10000  # bps
        
        # FIX #2: Reject wrong-side geometry instead of masking with abs()
        if L_raw <= 0 or G_raw <= 0:
            log_warning(
                "ev_gate_wrong_side_geometry: Invalid SL/TP for long position",
                side=side,
                entry_price=entry_price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                L_raw=L_raw,
                G_raw=G_raw,
            )
            return 0.0, 0.0, float('nan')
    else:
        # Short: stop above entry, take profit below entry
        L_raw = (stop_loss - entry_price) / entry_price * 10000  # bps
        G_raw = (entry_price - take_profit) / entry_price * 10000  # bps
        
        # FIX #2: Reject wrong-side geometry instead of masking with abs()
        if L_raw <= 0 or G_raw <= 0:
            log_warning(
                "ev_gate_wrong_side_geometry: Invalid SL/TP for short position",
                side=side,
                entry_price=entry_price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                L_raw=L_raw,
                G_raw=G_raw,
            )
            return 0.0, 0.0, float('nan')
    
    # Valid geometry - use raw values (already positive)
    L, G = L_raw, G_raw
    R = (G / L) if L > 0 else float('nan')
    
    return L, G, R


def calculate_cost_ratio(
    total_cost_bps: float,
    stop_loss_distance_bps: float,
) -> float:
    """
    Calculate cost ratio C = total_costs / L.
    
    Args:
        total_cost_bps: Total round-trip costs in bps
        stop_loss_distance_bps: Stop loss distance in bps (L)
        
    Returns:
        Cost ratio C (dimensionless)
        
    Requirements: 1.3
    """
    if stop_loss_distance_bps <= 0:
        return float('inf')
    return total_cost_bps / stop_loss_distance_bps


def _parse_symbol_float_map(raw: str) -> dict[str, float]:
    mapping: dict[str, float] = {}
    for part in (raw or "").split(","):
        token = part.strip()
        if not token or ":" not in token:
            continue
        symbol, value = token.split(":", 1)
        symbol_key = symbol.strip().upper()
        if not symbol_key:
            continue
        try:
            parsed = float(value.strip())
        except (TypeError, ValueError):
            continue
        if parsed < 0:
            continue
        mapping[symbol_key] = parsed
    return mapping


def calculate_ev(p: float, R: float, C: float) -> float:
    """
    Calculate expected value: EV = p × R - (1 - p) × 1 - C
    
    Args:
        p: Win probability (0 to 1)
        R: Reward-to-risk ratio
        C: Cost ratio
        
    Returns:
        Expected value (dimensionless, in units of stop loss)
        
    Requirements: 1.4
    """
    return p * R - (1 - p) * 1 - C


def calculate_p_min(R: float, C: float) -> float:
    """
    Calculate implied minimum probability: p_min = (1 + C) / (R + 1)
    
    Args:
        R: Reward-to-risk ratio
        C: Cost ratio
        
    Returns:
        Minimum probability required for positive EV
        
    Requirements: 1.6
    """
    if R <= -1:
        return float('inf')  # Impossible to have positive EV
    return (1 + C) / (R + 1)


# =============================================================================
# Cost Estimation
# Requirements: 5.1, 5.2, 5.3, 5.4, 5.5
# =============================================================================

# =============================================================================
# Relaxation Engine
# Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7
# =============================================================================

@dataclass
class RelaxationResult:
    """Result of relaxation computation."""
    adjustment_factor: float
    reason: Optional[str]
    candidate_factors: List[Tuple[float, str]]  # List of (factor, reason) pairs


class RelaxationEngine:
    """
    Computes EV_Min adjustments based on market conditions.
    
    Requirements:
    - 6.1: Relaxation when spread_percentile < 30% AND favorable book_imbalance
    - 6.2: Relaxation when volatility_regime is "low" AND session is "us" or "europe"
    - 6.3: Tightening when spread_percentile > 70%
    - 6.4: Combine factors: final = min(relax_factors) * max(tighten_factors)
    - 6.5: Enforce EV_MIN_FLOOR
    - 6.6: Disable relaxation when reliability < 0.8
    - 6.7: Disable relaxation when book stale
    """
    
    # Threshold for disabling relaxation due to low reliability (Requirement 6.6)
    RELAXATION_RELIABILITY_THRESHOLD = 0.8
    
    def __init__(self, config: EVGateConfig):
        """Initialize RelaxationEngine with configuration.
        
        Args:
            config: EVGateConfig containing relaxation parameters.
        """
        self.config = config
    
    def compute_adjustment(
        self,
        spread_percentile: float,
        book_imbalance: float,
        signal_side: str,
        volatility_regime: str,
        session: str,
        calibration_reliability: float,
        book_age_ms: float,
    ) -> RelaxationResult:
        """
        Compute EV_Min adjustment based on market conditions.
        
        FIX #1: Properly separate relax vs tighten factors.
        - Relaxation factors are < 1.0 (lower EV_min = easier to pass)
        - Tightening factors are > 1.0 (higher EV_min = harder to pass)
        - Final factor = min(relax_factors) * max(tighten_factors)
        
        This ensures relaxation can actually happen when conditions are favorable,
        while still applying tightening when conditions are adverse.
        
        Args:
            spread_percentile: Current spread relative to historical distribution (0-1)
            book_imbalance: Ratio of bid vs ask depth (positive = more bids)
            signal_side: "long" or "short"
            volatility_regime: "low", "medium", or "high"
            session: Trading session ("us", "europe", "asia", etc.)
            calibration_reliability: Calibration reliability score (0-1)
            book_age_ms: Orderbook age in milliseconds
            
        Returns:
            RelaxationResult with adjustment_factor and reason.
        """
        candidate_factors: List[Tuple[float, str]] = []
        relax_factors: List[Tuple[float, str]] = []
        tighten_factors: List[Tuple[float, str]] = []
        
        # Check safety guards first (Requirements 6.6, 6.7)
        relaxation_disabled = self._check_relaxation_safety_guards(
            calibration_reliability, book_age_ms
        )
        
        # Only compute relaxation factors if safety guards pass
        if not relaxation_disabled:
            # Requirement 6.1: Spread + book imbalance relaxation
            spread_imbalance_factor = self._compute_spread_imbalance_factor(
                spread_percentile, book_imbalance, signal_side
            )
            if spread_imbalance_factor is not None:
                relax_factors.append(spread_imbalance_factor)
                candidate_factors.append(spread_imbalance_factor)
            
            # Requirement 6.2: Volatility + session relaxation
            volatility_session_factor = self._compute_volatility_session_factor(
                volatility_regime, session
            )
            if volatility_session_factor is not None:
                relax_factors.append(volatility_session_factor)
                candidate_factors.append(volatility_session_factor)
        
        # Requirement 6.3: Spread tightening (always applies, not affected by safety guards)
        spread_tightening_factor = self._compute_spread_tightening_factor(spread_percentile)
        if spread_tightening_factor is not None:
            tighten_factors.append(spread_tightening_factor)
            candidate_factors.append(spread_tightening_factor)
        
        # FIX #1: Combine relax and tighten factors properly
        # - Take the MINIMUM of relax factors (most aggressive relaxation)
        # - Take the MAXIMUM of tighten factors (most conservative tightening)
        # - Multiply them together: final = relax_factor * tighten_factor
        
        # Default to 1.0 (no adjustment) if no factors
        relax_factor = 1.0
        relax_reason = None
        if relax_factors:
            # Pick the most aggressive relaxation (lowest factor)
            relax_factor, relax_reason = min(relax_factors, key=lambda x: x[0])
        
        tighten_factor = 1.0
        tighten_reason = None
        if tighten_factors:
            # Pick the most conservative tightening (highest factor)
            tighten_factor, tighten_reason = max(tighten_factors, key=lambda x: x[0])
        
        # Combine: final = relax * tighten
        final_factor = relax_factor * tighten_factor
        
        # Build reason string
        reasons = []
        if relax_reason and relax_factor < 1.0:
            reasons.append(relax_reason)
        if tighten_reason and tighten_factor > 1.0:
            reasons.append(tighten_reason)
        final_reason = "; ".join(reasons) if reasons else None
        
        # Add base factor for logging
        candidate_factors.append((1.0, "base"))
        
        return RelaxationResult(
            adjustment_factor=final_factor,
            reason=final_reason,
            candidate_factors=candidate_factors,
        )
    
    def apply_adjustment(
        self,
        ev_min_base: float,
        adjustment_factor: float,
    ) -> float:
        """
        Apply adjustment factor to EV_Min with floor enforcement.
        
        Args:
            ev_min_base: Base EV_Min value
            adjustment_factor: Adjustment factor from compute_adjustment
            
        Returns:
            Adjusted EV_Min, enforcing EV_MIN_FLOOR (Requirement 6.5)
        """
        ev_min_adjusted = ev_min_base * adjustment_factor
        
        # Requirement 6.5: Enforce EV_MIN_FLOOR
        return max(ev_min_adjusted, self.config.ev_min_floor)
    
    def _check_relaxation_safety_guards(
        self,
        calibration_reliability: float,
        book_age_ms: float,
    ) -> bool:
        """
        Check if relaxation should be disabled due to safety guards.
        
        Requirements:
        - 6.6: Disable relaxation when reliability < 0.8
        - 6.7: Disable relaxation when book stale
        
        Args:
            calibration_reliability: Calibration reliability score (0-1)
            book_age_ms: Orderbook age in milliseconds
            
        Returns:
            True if relaxation should be disabled, False otherwise.
        """
        # Requirement 6.6: Disable relaxation when reliability < 0.8
        if calibration_reliability < self.RELAXATION_RELIABILITY_THRESHOLD:
            return True
        
        # Requirement 6.7: Disable relaxation when book stale
        if book_age_ms > self.config.max_book_age_ms:
            return True
        
        return False
    
    def _compute_spread_imbalance_factor(
        self,
        spread_percentile: float,
        book_imbalance: float,
        signal_side: str,
    ) -> Optional[Tuple[float, str]]:
        """
        Compute relaxation factor based on spread and book imbalance.
        
        Requirement 6.1: WHEN spread_percentile < 30% AND book_imbalance is favorable
        for signal direction, THEN apply relaxation_multiplier = 0.8
        
        Args:
            spread_percentile: Current spread relative to historical distribution (0-1)
            book_imbalance: Ratio of bid vs ask depth (positive = more bids)
            signal_side: "long" or "short"
            
        Returns:
            Tuple of (factor, reason) if condition met, None otherwise.
        """
        # Check spread condition
        if spread_percentile >= self.config.relaxation_spread_percentile:
            return None
        
        # Check book imbalance is favorable for signal direction
        # For long: favorable = more bids (positive imbalance)
        # For short: favorable = more asks (negative imbalance)
        is_favorable = (
            (signal_side.lower() == "long" and book_imbalance > 0) or
            (signal_side.lower() == "short" and book_imbalance < 0)
        )
        
        if not is_favorable:
            return None
        
        return (
            self.config.relaxation_multiplier,
            f"spread_imbalance_relaxation (spread_pct={spread_percentile:.1%}, imbalance={book_imbalance:.2f})"
        )
    
    def _compute_volatility_session_factor(
        self,
        volatility_regime: str,
        session: str,
    ) -> Optional[Tuple[float, str]]:
        """
        Compute relaxation factor based on volatility regime and session.
        
        Requirement 6.2: WHEN volatility regime is "low" AND session is "us" or "europe",
        THEN apply relaxation_multiplier = 0.9
        
        Args:
            volatility_regime: "low", "medium", or "high"
            session: Trading session ("us", "europe", "asia", etc.)
            
        Returns:
            Tuple of (factor, reason) if condition met, None otherwise.
        """
        # Check volatility condition
        if volatility_regime.lower() != "low":
            return None
        
        # Check session condition
        if session.lower() not in ("us", "europe"):
            return None
        
        # Use a slightly less aggressive relaxation for volatility/session
        volatility_session_multiplier = 0.9
        
        return (
            volatility_session_multiplier,
            f"volatility_session_relaxation (vol={volatility_regime}, session={session})"
        )
    
    def _compute_spread_tightening_factor(
        self,
        spread_percentile: float,
    ) -> Optional[Tuple[float, str]]:
        """
        Compute tightening factor based on high spread.
        
        Requirement 6.3: WHEN spread_percentile > 70%, THEN apply
        tightening_multiplier = 1.25
        
        Args:
            spread_percentile: Current spread relative to historical distribution (0-1)
            
        Returns:
            Tuple of (factor, reason) if condition met, None otherwise.
        """
        if spread_percentile <= self.config.tightening_spread_percentile:
            return None
        
        return (
            self.config.tightening_multiplier,
            f"spread_tightening (spread_pct={spread_percentile:.1%})"
        )


class CostEstimator:
    """
    Estimates total round-trip costs for a trade.
    
    Phase 3: Integrated with ExecutionPolicy, SlippageModel, and FeeModel
    for accurate, market-state-adaptive cost estimation.
    """
    
    def __init__(
        self,
        fee_model: Optional[FeeModel] = None,
        execution_policy: Optional[ExecutionPolicy] = None,
        slippage_model: Optional[SlippageModel] = None,
    ):
        """Initialize CostEstimator with Phase 2 models.
        
        Args:
            fee_model: FeeModel instance for fee calculation
            execution_policy: ExecutionPolicy for execution assumptions
            slippage_model: SlippageModel for adaptive slippage
        """
        # Default to exchange-appropriate fees. NOTE: runtime loads .env at startup,
        # but depending on wiring, CostEstimator may be constructed before dotenv is applied.
        # To avoid "sticky OKX default" behavior, we resolve env-driven defaults lazily too.
        self._fee_model_locked = fee_model is not None
        self.fee_model = fee_model or self._resolve_default_fee_model()
        self.execution_policy = execution_policy or ExecutionPolicy()
        self.slippage_model = slippage_model or SlippageModel()

    @staticmethod
    def _resolve_default_fee_model() -> FeeModel:
        fee_config_name = (os.getenv("EV_GATE_FEE_CONFIG") or os.getenv("POSITION_GUARD_FEE_CONFIG") or "").strip().lower()
        exchange_name = (os.getenv("EXCHANGE") or os.getenv("ACTIVE_EXCHANGE") or "").strip().lower()
        if fee_config_name:
            try:
                return FeeModel(getattr(FeeConfig, fee_config_name)())
            except AttributeError:
                pass
        return FeeModel(FeeConfig.bybit_regular() if "bybit" in exchange_name else FeeConfig.okx_regular())

    def _ensure_env_fee_model(self) -> None:
        if self._fee_model_locked:
            return
        self.fee_model = self._resolve_default_fee_model()
    
    def estimate(
        self,
        symbol: str,
        strategy_id: str,
        setup_type: str,
        entry_price: float,
        exit_price: float,
        size: float,
        best_bid: float,
        best_ask: float,
        order_size_usd: float,
        volatility_regime: Optional[str] = None,
        spread_percentile: Optional[float] = None,
        bid_depth_usd: Optional[float] = None,
        ask_depth_usd: Optional[float] = None,
        hold_time_expected_sec: float = 300.0,
        observed_slippage_bps: Optional[float] = None,
    ) -> CostEstimate:
        """
        Estimate costs using Phase 2 models (ExecutionPolicy + SlippageModel).
        
        Args:
            symbol: Trading symbol (e.g., "BTCUSDT")
            strategy_id: Strategy identifier
            setup_type: Setup type (e.g., "mean_reversion", "breakout")
            entry_price: Entry price
            exit_price: Expected exit price (TP)
            size: Position size in base currency
            best_bid: Best bid price
            best_ask: Best ask price
            order_size_usd: Order size in USD
            volatility_regime: Volatility regime ("low", "normal", "high", "extreme")
            spread_percentile: Spread percentile (0-100)
            bid_depth_usd: Bid depth in USD
            ask_depth_usd: Ask depth in USD
            hold_time_expected_sec: Expected hold time in seconds
            
        Returns:
            CostEstimate with all cost components
            
        Requirements: 5.1, 5.2, 5.3, 5.4, 5.5 + Phase 2 integration
        """
        self._ensure_env_fee_model()
        mid_price = (best_bid + best_ask) / 2 if best_bid > 0 and best_ask > 0 else entry_price
        
        # Spread cost (Requirement 5.1)
        # Round-trip spread = half-spread on entry + half-spread on exit
        if mid_price > 0:
            spread_bps = (best_ask - best_bid) / mid_price * 10000
        else:
            spread_bps = 0.0
        
        # Get execution plan from ExecutionPolicy (Phase 2)
        execution_plan = self.execution_policy.plan_execution(
            strategy_id=strategy_id,
            setup_type=setup_type,
        )
        
        # Calculate expected fees using ExecutionPolicy probabilities (Requirement 5.2 + Phase 2)
        from quantgambit.execution.execution_policy import calculate_expected_fees_bps
        fee_bps = calculate_expected_fees_bps(
            fee_model=self.fee_model,
            execution_plan=execution_plan,
            entry_price=entry_price,
            exit_price=exit_price,
            size=size,
        )
        
        # Calculate adaptive slippage using SlippageModel (Requirement 5.3 + Phase 2)
        slippage_bps = self.slippage_model.calculate_slippage_bps(
            symbol=symbol,
            spread_bps=spread_bps,
            spread_percentile=spread_percentile,
            book_depth_usd=min(bid_depth_usd or 0, ask_depth_usd or 0) if bid_depth_usd and ask_depth_usd else None,
            order_size_usd=order_size_usd,
            volatility_regime=volatility_regime,
            urgency=execution_plan.entry_urgency,
        )
        if observed_slippage_bps is not None:
            try:
                observed_val = float(observed_slippage_bps)
                if observed_val > 0:
                    slippage_bps = max(slippage_bps, observed_val)
            except (TypeError, ValueError):
                pass
        
        # Calculate adverse selection (Phase 2)
        adverse_selection_bps = calculate_adverse_selection_bps(
            symbol=symbol,
            volatility_regime=volatility_regime or "normal",
            hold_time_expected_sec=hold_time_expected_sec,
        )
        
        # Total cost
        total_bps = spread_bps + fee_bps + slippage_bps + adverse_selection_bps
        
        return CostEstimate(
            spread_bps=spread_bps,
            fee_bps=fee_bps,
            slippage_bps=slippage_bps,
            adverse_selection_bps=adverse_selection_bps,
            total_bps=total_bps,
        )


# =============================================================================
# EVGateStage - Pipeline Stage
# Requirements: 1.5, 1.7, 1.8, 2.5, 2.6, 3.1-3.7
# =============================================================================

class EVGateStage(Stage):
    """
    Pipeline stage that applies EV-based entry filtering.
    
    Replaces the fixed confidence threshold with proper EV calculation
    that accounts for reward-to-risk ratio and costs.
    
    Requirements:
    - 1.1-1.8: EV calculation and decision
    - 2.1-2.8: Dynamic threshold
    - 3.1-3.7: Edge case handling
    - 6.1-6.7: Conditional relaxation
    - 7.5, 7.6: Strategy diagnostics integration
    """
    name = "ev_gate"
    
    def __init__(
        self,
        config: Optional[EVGateConfig] = None,
        cost_estimator: Optional[CostEstimator] = None,
        relaxation_engine: Optional[RelaxationEngine] = None,
        telemetry: Optional["BlockedSignalTelemetry"] = None,
        diagnostics: Optional["StrategyDiagnostics"] = None,
    ):
        """Initialize EVGateStage.
        
        Args:
            config: Configuration for the EV gate. Uses defaults if None.
            cost_estimator: Cost estimator instance. Creates default if None.
            relaxation_engine: Relaxation engine instance. Creates default if None.
            telemetry: Optional telemetry for recording blocked signals.
            diagnostics: Optional StrategyDiagnostics for recording EV pass/fail.
        """
        self.config = config or EVGateConfig()
        self.cost_estimator = cost_estimator or CostEstimator()
        self.relaxation_engine = relaxation_engine or RelaxationEngine(self.config)
        self.telemetry = telemetry
        self._diagnostics = diagnostics
    
    async def run(self, ctx: StageContext) -> StageResult:
        """
        Evaluate signal EV and accept/reject based on threshold.
        
        Args:
            ctx: Stage context containing signal and market data.
            
        Returns:
            StageResult.REJECT if EV below threshold (in enforce mode),
            StageResult.CONTINUE otherwise.
        """
        signal = ctx.signal
        
        # Skip if no signal to evaluate
        if not signal:
            return StageResult.CONTINUE
        
        # Skip exit signals - this stage is for entry filtering only
        # signal is a StrategySignal dataclass, access side attribute directly
        side = getattr(signal, "side", "") or ""
        side = side.lower() if isinstance(side, str) else ""
        if side in ("close_long", "close_short", "close"):
            return StageResult.CONTINUE
        
        # Evaluate EV
        result = self._evaluate(ctx, signal)
        
        # Log the decision
        self._log_decision(ctx, result)
        
        # FIX #8: Store ev_gate_result in both modes for post-trade forensics
        ctx.data["ev_gate_result"] = result
        
        # In shadow mode, always continue (just log)
        if self.config.mode == "shadow":
            ctx.data["ev_gate_would_reject"] = result.decision == "REJECT"
            return StageResult.CONTINUE
        
        # In enforce mode, reject if decision is REJECT
        if result.decision == "REJECT":
            ctx.rejection_reason = result.reject_code.value if result.reject_code else "ev_gate_reject"
            ctx.rejection_stage = self.name
            ctx.rejection_detail = {
                "reject_code": result.reject_code.value if result.reject_code else None,
                "reject_reason": result.reject_reason,
                "p_calibrated": result.p_calibrated,
                "p_min": result.p_min,
                "R": result.R,
                "C": result.C,
                "EV": result.EV,
                "ev_min_adjusted": result.ev_min_adjusted,
                "L_bps": result.L_bps,
                "G_bps": result.G_bps,
                "total_cost_bps": result.total_cost_bps,
            }
            
            # Record EV failure for diagnostics (Requirement 7.5)
            if self._diagnostics:
                strategy_id = None
                if hasattr(signal, 'strategy_id'):
                    strategy_id = signal.strategy_id
                elif isinstance(signal, dict):
                    strategy_id = signal.get('strategy_id')
                if strategy_id:
                    # Map reject code to failure type
                    if result.reject_code == EVGateRejectCode.EV_BELOW_MIN:
                        self._diagnostics.record_predicate_failure(strategy_id, "fail_ev")
                    elif result.reject_code == EVGateRejectCode.COST_EXCEEDS_SL:
                        self._diagnostics.record_predicate_failure(strategy_id, "fail_cost")
                    elif result.reject_code in (EVGateRejectCode.MISSING_REQUIRED_FIELD, 
                                                 EVGateRejectCode.STALE_BOOK,
                                                 EVGateRejectCode.STALE_SPREAD):
                        self._diagnostics.record_predicate_failure(strategy_id, "fail_data")
                    else:
                        # Default to fail_ev for other EV-related rejections
                        self._diagnostics.record_predicate_failure(strategy_id, "fail_ev")
            
            # Emit telemetry
            if self.telemetry:
                await self.telemetry.record_blocked(
                    symbol=ctx.symbol,
                    gate_name="ev_gate",
                    reason=result.reject_reason or "EV below threshold",
                    metrics={
                        "p": result.p_calibrated,
                        "p_min": result.p_min,
                        "R": result.R,
                        "C": result.C,
                        "EV": result.EV,
                        "ev_min": result.ev_min_adjusted,
                    },
                )
            
            return StageResult.REJECT
        
        # Signal passed EV gate - record for diagnostics (Requirement 7.6)
        if self._diagnostics:
            strategy_id = None
            if hasattr(ctx.signal, 'strategy_id'):
                strategy_id = ctx.signal.strategy_id
            elif isinstance(ctx.signal, dict):
                strategy_id = ctx.signal.get('strategy_id')
            if strategy_id:
                self._diagnostics.record_ev_pass(strategy_id)
        
        return StageResult.CONTINUE

    
    def _evaluate(self, ctx: StageContext, signal: Union[dict, Any]) -> EVGateResult:
        """Evaluate signal and return EVGateResult."""
        result = EVGateResult(decision="ACCEPT")
        
        # Convert signal to dict if it's a dataclass (e.g., StrategySignal)
        if hasattr(signal, '__dataclass_fields__'):
            signal = asdict(signal)
        elif not isinstance(signal, dict):
            # Try to convert to dict if it has __dict__
            signal = getattr(signal, '__dict__', {}) or {}
        
        # Get market context
        market_context = ctx.data.get("market_context") or {}
        features = ctx.data.get("features") or {}
        prediction = ctx.data.get("prediction") or {}
        
        # =====================================================================
        # Safety Guard: Missing Field Detection (Requirement 5.1)
        # Only check for truly required fields: entry_price, side, SL, TP
        # =====================================================================
        missing_field = self._check_required_fields(ctx, signal, market_context, features, prediction)
        if missing_field:
            return self._reject(
                result,
                EVGateRejectCode.MISSING_REQUIRED_FIELD,
                f"Missing required field: {missing_field}"
            )
        
        # =====================================================================
        # Fill missing optional fields with conservative defaults (Requirement 5.7)
        # =====================================================================
        defaulted_fields = self._compute_defaults(ctx, signal)
        result.defaulted_fields = defaulted_fields if defaulted_fields else None
        
        # Track p_hat source for calibration adjustment
        result.p_hat_source = signal.get("p_hat_source", "calibrated")
        if result.p_hat_source == "uncalibrated_conservative":
            result.calibration_method = "uncalibrated_conservative"
        
        # =====================================================================
        # Safety Guard: Connectivity Checks (Requirements 10.2, 10.3)
        # =====================================================================
        connectivity_error = self._check_connectivity(ctx, market_context)
        if connectivity_error:
            code, reason = connectivity_error
            return self._reject(result, code, reason)
        
        # Get prices
        entry_price = signal.get("entry_price") or market_context.get("price") or features.get("price", 0)
        side = signal.get("side", "long").lower()
        
        # Get SL/TP - support both price-based and distance-based (Requirement 5.8)
        stop_loss = signal.get("stop_loss") or signal.get("sl_price")
        take_profit = signal.get("take_profit") or signal.get("target_price") or signal.get("tp_price")
        
        # If we have distances but not prices, convert them
        mid_price = market_context.get("mid_price") or features.get("mid_price") or entry_price
        
        if stop_loss is None and signal.get("sl_distance_bps") is not None:
            sl_distance_bps = signal.get("sl_distance_bps")
            if side == "long":
                stop_loss = entry_price * (1 - sl_distance_bps / 10000)
            else:
                stop_loss = entry_price * (1 + sl_distance_bps / 10000)
            signal["stop_loss"] = stop_loss
        
        if take_profit is None and signal.get("tp_distance_bps") is not None:
            tp_distance_bps = signal.get("tp_distance_bps")
            if side == "long":
                take_profit = entry_price * (1 + tp_distance_bps / 10000)
            else:
                take_profit = entry_price * (1 - tp_distance_bps / 10000)
            signal["take_profit"] = take_profit
        
        # Validate SL/TP are now available
        if stop_loss is None:
            return self._reject(result, EVGateRejectCode.MISSING_STOP_LOSS, "Missing stop_loss")
        
        if take_profit is None:
            # Check if strategy has implicit target
            strategy_id = signal.get("strategy_id", "")
            if not self._has_implicit_target(strategy_id):
                return self._reject(result, EVGateRejectCode.MISSING_TAKE_PROFIT, "Missing take_profit")
            # Use estimated target based on strategy
            take_profit = self._estimate_implicit_target(entry_price, stop_loss, side, strategy_id)

        # Sanity-fix TP direction to avoid invalid geometry (diagnostic guard)
        if side == "short" and take_profit >= entry_price:
            tp_distance = abs(take_profit - entry_price) or abs(entry_price * 0.001)
            take_profit = entry_price - tp_distance
            signal["take_profit"] = take_profit
        if side == "long" and take_profit <= entry_price:
            tp_distance = abs(entry_price - take_profit) or abs(entry_price * 0.001)
            take_profit = entry_price + tp_distance
            signal["take_profit"] = take_profit
        
        # Calculate L, G, R (Requirement 1.1, 1.2)
        L_bps, G_bps, R = calculate_L_G_R(entry_price, stop_loss, take_profit, side)
        result.L_bps = L_bps
        result.G_bps = G_bps
        result.R = R
        
        # Validate L (Requirement 3.1, 3.5)
        if L_bps <= 0:
            return self._reject(result, EVGateRejectCode.INVALID_SL, f"Invalid stop loss distance: L={L_bps:.2f} bps")
        
        if L_bps < self.config.min_stop_distance_bps:
            return self._reject(
                result, 
                EVGateRejectCode.STOP_TOO_TIGHT, 
                f"Stop too tight: L={L_bps:.2f} bps < min={self.config.min_stop_distance_bps} bps"
            )
        
        # Validate R (Requirement 3.2)
        if math.isnan(R) or R <= 0:
            return self._reject(result, EVGateRejectCode.INVALID_R, f"Invalid reward-to-risk ratio: R={R}")
        
        # Check data staleness (Requirement 3.6)
        # FIX #4: Treat missing timestamps as stale/invalid
        book_age_ms = self._get_book_age_ms(ctx)
        if book_age_ms is None:
            self._log_staleness_details(ctx, book_age_ms, None)
            return self._reject(
                result,
                EVGateRejectCode.STALE_BOOK,
                "Missing book timestamp - cannot verify data freshness"
            )
        result.book_age_ms = book_age_ms
        if book_age_ms > self.config.max_book_age_ms:
            self._log_staleness_details(ctx, book_age_ms, None)
            return self._reject(
                result,
                EVGateRejectCode.STALE_BOOK,
                f"Stale book data: age={book_age_ms:.0f}ms > max={self.config.max_book_age_ms}ms"
            )
        
        # FIX #4: Check spread staleness (treat missing as stale)
        spread_age_ms = self._get_spread_age_ms(ctx)
        if spread_age_ms is None:
            self._log_staleness_details(ctx, book_age_ms, spread_age_ms)
            return self._reject(
                result,
                EVGateRejectCode.STALE_SPREAD,
                "Missing spread timestamp - cannot verify data freshness"
            )
        result.spread_age_ms = spread_age_ms
        if spread_age_ms > self.config.max_spread_age_ms:
            self._log_staleness_details(ctx, book_age_ms, spread_age_ms)
            return self._reject(
                result,
                EVGateRejectCode.STALE_SPREAD,
                f"Stale spread data: age={spread_age_ms:.0f}ms > max={self.config.max_spread_age_ms}ms"
            )
        
        # Estimate costs using Phase 2 models (Requirement 5.1-5.5 + Phase 2)
        best_bid = market_context.get("best_bid") or features.get("best_bid", 0)
        best_ask = market_context.get("best_ask") or features.get("best_ask", 0)
        order_size_usd = signal.get("size_usd") or self._estimate_size_usd(signal, entry_price)
        
        # Get strategy info for ExecutionPolicy
        strategy_id = signal.get("strategy_id", "")
        setup_type = self._extract_setup_type(strategy_id, signal.get("meta_reason", ""))
        
        # Get market state for SlippageModel
        # FIX #2: Normalize spread_percentile for cost estimation too
        volatility_regime = market_context.get("volatility_regime") or features.get("volatility_regime")
        spread_percentile_for_cost = market_context.get("spread_percentile") or features.get("spread_percentile")
        # Normalize to 0-100 scale for SlippageModel (it expects 0-100)
        if spread_percentile_for_cost is not None:
            spread_percentile_for_cost = float(spread_percentile_for_cost)
            if spread_percentile_for_cost <= 1.0:
                spread_percentile_for_cost = spread_percentile_for_cost * 100.0
        bid_depth_usd = market_context.get("bid_depth_usd")
        if bid_depth_usd is None:
            bid_depth_usd = features.get("bid_depth_usd")
        ask_depth_usd = market_context.get("ask_depth_usd")
        if ask_depth_usd is None:
            ask_depth_usd = features.get("ask_depth_usd")
        observed_slippage_bps = (
            market_context.get("observed_slippage_bps")
            or features.get("observed_slippage_bps")
        )
        
        # Estimate hold time based on strategy
        hold_time_expected_sec = self._estimate_hold_time(strategy_id, setup_type)
        
        cost_estimate = self.cost_estimator.estimate(
            symbol=ctx.symbol,
            strategy_id=strategy_id,
            setup_type=setup_type,
            entry_price=entry_price,
            exit_price=take_profit,
            size=signal.get("size") or signal.get("quantity", 0.1),
            best_bid=best_bid,
            best_ask=best_ask,
            order_size_usd=order_size_usd,
            volatility_regime=volatility_regime,
            spread_percentile=spread_percentile_for_cost,
            bid_depth_usd=bid_depth_usd,
            ask_depth_usd=ask_depth_usd,
            hold_time_expected_sec=hold_time_expected_sec,
            observed_slippage_bps=observed_slippage_bps,
        )

        # Apply EVGateConfig floors (env-driven) so config knobs actually affect the cost model.
        # This is critical for taker-only trading where we want conservative, stable cost estimates.
        slippage_bps = max(float(cost_estimate.slippage_bps or 0.0), float(self.config.min_slippage_bps))
        adverse_sel_bps = max(float(cost_estimate.adverse_selection_bps or 0.0), float(self.config.adverse_selection_bps))
        total_cost_bps = float(cost_estimate.spread_bps or 0.0) + float(cost_estimate.fee_bps or 0.0) + slippage_bps + adverse_sel_bps
        
        result.spread_bps = float(cost_estimate.spread_bps or 0.0)
        result.fee_bps = float(cost_estimate.fee_bps or 0.0)
        result.slippage_bps = slippage_bps
        result.adverse_selection_bps = adverse_sel_bps
        result.total_cost_bps = total_cost_bps
        
        # Calculate C (Requirement 1.3)
        C = calculate_cost_ratio(cost_estimate.total_bps, L_bps)
        result.C = C
        
        # Validate C (Requirement 3.4)
        if C > 1.0:
            return self._reject(
                result,
                EVGateRejectCode.COST_EXCEEDS_SL,
                f"Costs exceed stop loss: C={C:.3f} > 1.0"
            )
        
        # Get probability - use p_hat from signal if available (may have been defaulted).
        # EVGate must never treat prediction confidence as p_hat unless we explicitly
        # define/ship a calibrated probability contract.
        p_raw = signal.get("p_hat")
        if p_raw is None:
            # This should be unreachable because _compute_defaults() sets p_hat.
            # Fail safe with neutral probability so EV tends to reject after costs.
            p_raw = 0.5
            log_warning(
                "ev_gate_missing_p_hat_fell_back_to_neutral",
                symbol=ctx.symbol,
                strategy_id=strategy_id,
                prediction_confidence=prediction.get("confidence"),
            )
        p_raw = self._normalize_p(p_raw, ctx.symbol)
        
        # Use the p_hat value
        p_calibrated = p_raw
        result.p_calibrated = p_calibrated
        
        # =====================================================================
        # Calibration State Machine - Cold-Start Safety (Requirement 10.4)
        # Uses Bayesian shrinkage instead of penalizing EV threshold
        # =====================================================================
        # FIX #7: Get calibration state from per-(symbol, strategy) store, not market_context
        # Calibration is a model/strategy attribute, not a market attribute
        calibration_data = ctx.data.get("calibration")
        if not isinstance(calibration_data, dict):
            calibration_data = {}
        calibration_key = f"{ctx.symbol}:{strategy_id}"
        strategy_calibration_raw = (
            calibration_data.get(calibration_key)
            or calibration_data.get(strategy_id)
            or calibration_data.get(ctx.symbol)
            or {}
        )
        if isinstance(strategy_calibration_raw, dict):
            strategy_calibration = strategy_calibration_raw
        elif isinstance(strategy_calibration_raw, (int, float)):
            # Backward-compat path: older snapshots store plain trade counts.
            strategy_calibration = {"n_trades": int(strategy_calibration_raw)}
        else:
            strategy_calibration = {}
        
        # Fall back to market_context for backward compatibility, but prefer dedicated store
        calibration_reliability = (
            strategy_calibration.get("reliability")
            or market_context.get("calibration_reliability", 0.0)
        )
        n_trades = (
            strategy_calibration.get("n_trades")
            or market_context.get("n_trades", 0)
        )
        
        # Evaluate calibration status using state machine
        calibration_status = evaluate_calibration(
            strategy_id=strategy_id,
            n_trades=n_trades,
            p_observed=p_raw,
            reliability=calibration_reliability if calibration_reliability > 0 else None,
        )
        
        # Use p_effective from Bayesian shrinkage instead of raw p_hat
        # This blends the observed probability with conservative priors
        p_calibrated = calibration_status.p_effective
        result.p_calibrated = p_calibrated
        result.calibration_reliability = calibration_status.reliability
        result.calibration_method = calibration_status.state.value
        
        # Store size multiplier for downstream position sizing
        ctx.data["calibration_size_multiplier"] = calibration_status.size_multiplier
        ctx.data["calibration_status"] = calibration_status
        
        # Calculate p_min (Requirement 1.6)
        p_min = calculate_p_min(R, C)
        result.p_min = p_min

        # Cold-start alignment: avoid rejecting solely due to conservative shrinkage
        # when raw model p_hat would satisfy p_min.
        mean_reversion_tolerance = self._mean_reversion_pmin_tolerance(ctx.symbol)
        mean_reversion_edge_tolerance_bps = self._mean_reversion_expected_edge_tolerance_bps(ctx.symbol)
        if calibration_status.state != CalibrationState.OK and p_raw is not None:
            mean_reversion_gap = p_min - p_calibrated
            if p_calibrated < p_min <= p_raw:
                p_calibrated = p_min
                result.p_calibrated = p_calibrated
                result.p_hat_source = "calibrated_floor"
                ctx.data["calibration_pmin_override"] = True
            elif (
                strategy_id in {"mean_reversion_fade", "vwap_reversion"}
                and mean_reversion_gap > 0
                and mean_reversion_gap
                <= max(self.config.p_margin_uncalibrated + 0.015, mean_reversion_tolerance)
            ):
                p_calibrated = p_min
                result.p_calibrated = p_calibrated
                result.p_hat_source = "calibrated_floor_mean_reversion_buffer"
                ctx.data["calibration_pmin_override"] = True
        elif (
            setup_type == "mean_reversion"
            and p_calibrated < p_min
            and (p_min - p_calibrated) <= mean_reversion_tolerance
        ):
            p_calibrated = p_min
            result.p_calibrated = p_calibrated
            result.p_hat_source = "mean_reversion_pmin_tolerance"
            ctx.data["ev_gate_pmin_tolerance_override"] = True

        # Calculate EV (Requirement 1.4)
        EV = calculate_ev(p_calibrated, R, C)
        result.EV = EV
        expected_gross_edge_bps = (p_calibrated * G_bps) - ((1.0 - p_calibrated) * L_bps)
        expected_net_edge_bps = expected_gross_edge_bps - float(result.total_cost_bps or 0.0)
        result.expected_gross_edge_bps = float(expected_gross_edge_bps)
        result.expected_net_edge_bps = float(expected_net_edge_bps)
        symbol_key = str(ctx.symbol or "").upper()
        side_key = "long" if str(side).lower() in {"long", "buy"} else "short"
        symbol_side_key = f"{symbol_key}:{side_key}"
        min_expected_edge_bps = float(
            self.config.min_expected_edge_bps_by_symbol_side.get(
                symbol_side_key,
                self.config.min_expected_edge_bps_by_symbol.get(
                    symbol_key,
                    self.config.min_expected_edge_bps_by_side.get(
                        side_key,
                        self.config.min_expected_edge_bps,
                    ),
                ),
            )
        )
        result.min_expected_edge_bps = min_expected_edge_bps
        
        # Get market condition parameters for relaxation
        # FIX #2: Normalize spread_percentile to 0-1 scale
        spread_percentile_raw = market_context.get("spread_percentile") or features.get("spread_percentile")
        spread_percentile = self._normalize_percentile(spread_percentile_raw, default=0.5)
        
        # FIX #3: Unify book_imbalance source keys
        book_imbalance = (
            market_context.get("book_imbalance")
            or market_context.get("depth_imbalance")
            or features.get("depth_imbalance")
            or features.get("orderbook_imbalance")
            or 0.0
        )
        # Clamp to [-1, 1]
        book_imbalance = max(-1.0, min(1.0, float(book_imbalance)))
        
        volatility_regime = market_context.get("volatility_regime", "medium")
        session = market_context.get("session", "unknown")
        
        # FIX #6: Pass L_bps to _get_adjusted_ev_min for proper edge scaling
        ev_min_adjusted, adjustment_reason = self._get_adjusted_ev_min(
            calibration_reliability=calibration_status.reliability,
            spread_percentile=spread_percentile,
            book_imbalance=book_imbalance,
            signal_side=side,
            volatility_regime=volatility_regime,
            session=session,
            book_age_ms=book_age_ms,
            calibration_status=calibration_status,
            L_bps=L_bps,  # Pass stop distance for proper edge scaling
        )
        # Cost-multiple gate: require expected edge to beat conservative recent cost baseline.
        cost_multiple = float(os.getenv("EV_GATE_COST_MULTIPLE", "3.0"))
        symbol_cost_override = None
        by_symbol = (os.getenv("EV_GATE_RECENT_COST_P75_BPS_BY_SYMBOL") or "").strip()
        if by_symbol:
            for part in by_symbol.split(","):
                raw = part.strip()
                if not raw or ":" not in raw:
                    continue
                sym, val = raw.split(":", 1)
                if sym.strip().upper() != str(ctx.symbol or "").upper():
                    continue
                try:
                    symbol_cost_override = float(val.strip())
                except (TypeError, ValueError):
                    symbol_cost_override = None
                break
        global_cost_override = None
        raw_global_override = (os.getenv("EV_GATE_RECENT_COST_P75_BPS") or "").strip()
        if raw_global_override:
            try:
                global_cost_override = float(raw_global_override)
            except (TypeError, ValueError):
                global_cost_override = None
        recent_cost_p75 = (
            symbol_cost_override
            or global_cost_override
            or
            market_context.get("recent_total_cost_bps_p75")
            or features.get("recent_total_cost_bps_p75")
            or result.total_cost_bps
        )
        try:
            recent_cost_p75 = float(recent_cost_p75)
        except (TypeError, ValueError):
            recent_cost_p75 = float(result.total_cost_bps or 0.0)
        if cost_multiple > 0 and recent_cost_p75 > 0 and L_bps > 0:
            required_edge_bps = cost_multiple * recent_cost_p75
            required_ev_min = required_edge_bps / L_bps
            if required_ev_min > ev_min_adjusted:
                ev_min_adjusted = required_ev_min
                extra_reason = (
                    f"cost_multiple_gate (required_edge_bps={required_edge_bps:.2f}, "
                    f"recent_cost_p75={recent_cost_p75:.2f}, multiple={cost_multiple:.2f})"
                )
                adjustment_reason = f"{adjustment_reason}; {extra_reason}" if adjustment_reason else extra_reason
        
        # NOTE: Removed _get_ev_min_adjusted_for_calibration call
        # Cold-start safety is now handled by:
        # 1. Bayesian shrinkage for p_effective (above)
        # 2. min_edge_bps_adjustment in _get_adjusted_ev_min (scaled by L_bps)
        # 3. size_multiplier stored in ctx.data for downstream sizing
        
        result.ev_min_base = self.config.ev_min
        result.ev_min_adjusted = ev_min_adjusted
        result.adjustment_reason = adjustment_reason
        
        # Update adjustment reason with calibration state info
        if calibration_status.state != CalibrationState.OK:
            state_info = f"calibration_state={calibration_status.state.value}"
            if adjustment_reason:
                result.adjustment_reason = f"{adjustment_reason}; {state_info}"
            else:
                result.adjustment_reason = state_info
        
        if result.adjustment_reason:
            result.adjustment_factor = ev_min_adjusted / self.config.ev_min if self.config.ev_min > 0 else 1.0
        else:
            result.adjustment_factor = 1.0

        if (
            strategy_id in {"mean_reversion_fade", "vwap_reversion"}
            and calibration_status.state != CalibrationState.OK
            and abs(p_calibrated - p_min) <= 1e-6
            and EV >= -1e-6
            and ev_min_adjusted > 0.0
        ):
            EV = 0.0
            result.EV = EV
            expected_net_edge_bps = 0.0
            result.expected_net_edge_bps = expected_net_edge_bps
            ev_min_adjusted = 0.0
            result.ev_min_adjusted = ev_min_adjusted
            min_expected_edge_bps = 0.0
            result.min_expected_edge_bps = min_expected_edge_bps
            extra_reason = (
                "mean_reversion_borderline_pmin_relax"
                if strategy_id == "mean_reversion_fade"
                else f"{strategy_id}_borderline_pmin_relax"
            )
            result.adjustment_reason = (
                f"{result.adjustment_reason}; {extra_reason}"
                if result.adjustment_reason
                else extra_reason
            )
            result.adjustment_factor = 0.0

        if (
            strategy_id in {"mean_reversion_fade", "vwap_reversion"}
            and calibration_status.state != CalibrationState.OK
            and min_expected_edge_bps > 0.0
            and expected_net_edge_bps < min_expected_edge_bps
            and expected_net_edge_bps >= (min_expected_edge_bps - mean_reversion_edge_tolerance_bps)
        ):
            expected_net_edge_bps = min_expected_edge_bps
            result.expected_net_edge_bps = expected_net_edge_bps
            extra_reason = (
                "mean_reversion_expected_edge_tolerance"
                if strategy_id == "mean_reversion_fade"
                else f"{strategy_id}_expected_edge_tolerance"
            )
            result.adjustment_reason = (
                f"{result.adjustment_reason}; {extra_reason}"
                if result.adjustment_reason
                else extra_reason
            )

        if (
            strategy_id in {"mean_reversion_fade", "vwap_reversion"}
            and calibration_status.state != CalibrationState.OK
            and EV > 0.0
            and EV < ev_min_adjusted
            and L_bps > 0.0
        ):
            ev_tolerance = mean_reversion_edge_tolerance_bps / L_bps
            if EV >= (ev_min_adjusted - ev_tolerance):
                EV = ev_min_adjusted
                result.EV = EV
                extra_reason = (
                    "mean_reversion_ev_tolerance"
                    if strategy_id == "mean_reversion_fade"
                    else f"{strategy_id}_ev_tolerance"
                )
                result.adjustment_reason = (
                    f"{result.adjustment_reason}; {extra_reason}"
                    if result.adjustment_reason
                    else extra_reason
                )

        # FIX #1: Separate P_BELOW_PMIN and EV_BELOW_MIN checks with correct messages
        # First check: is probability below the minimum required for positive EV?
        if p_calibrated < p_min:
            return self._reject(
                result,
                EVGateRejectCode.P_BELOW_PMIN,
                f"p={p_calibrated:.3f} < p_min={p_min:.3f} (R={R:.2f}, C={C:.3f})"
            )
        
        # Second check: is EV below the minimum threshold?
        if EV < ev_min_adjusted:
            return self._reject(
                result,
                EVGateRejectCode.EV_BELOW_MIN,
                f"EV={EV:.4f} < ev_min={ev_min_adjusted:.4f} (p={p_calibrated:.3f}, p_min={p_min:.3f}, R={R:.2f}, C={C:.3f})"
            )

        # Explicit net-edge guard: expected net edge must clear configured floor in bps.
        if expected_net_edge_bps < min_expected_edge_bps:
            return self._reject(
                result,
                EVGateRejectCode.EXPECTED_EDGE_BELOW_MIN,
                (
                    f"expected_net_edge_bps={expected_net_edge_bps:.3f} < "
                    f"min_expected_edge_bps={min_expected_edge_bps:.3f}"
                ),
            )

        # Conservative throughput boost: allow borderline passes, but size down hard.
        p_buffer = max(0.0, p_calibrated - p_min)
        ev_buffer = max(0.0, EV - ev_min_adjusted)
        marginal_size_multiplier = 1.0
        marginal_reason = None
        if p_buffer < 0.015 or ev_buffer < 0.004:
            marginal_size_multiplier = 0.55
            marginal_reason = "very_marginal_pass"
        elif p_buffer < 0.03 or ev_buffer < 0.008:
            marginal_size_multiplier = 0.75
            marginal_reason = "marginal_pass"
        if marginal_size_multiplier < 1.0:
            base_multiplier = float(ctx.data.get("calibration_size_multiplier", 1.0) or 1.0)
            combined_multiplier = max(0.0, min(1.0, base_multiplier * marginal_size_multiplier))
            ctx.data["calibration_size_multiplier"] = combined_multiplier
            ctx.data["ev_gate_marginal_size_multiplier"] = marginal_size_multiplier
            ctx.data["ev_gate_marginal_reason"] = marginal_reason
            log_info(
                "ev_gate_marginal_pass_size_haircut",
                symbol=ctx.symbol,
                strategy_id=strategy_id,
                p_buffer=round(p_buffer, 4),
                ev_buffer=round(ev_buffer, 5),
                marginal_size_multiplier=marginal_size_multiplier,
                calibration_size_multiplier_before=round(base_multiplier, 4),
                calibration_size_multiplier_after=round(combined_multiplier, 4),
                reason=marginal_reason,
            )

        return result

    
    def _reject(
        self,
        result: EVGateResult,
        code: EVGateRejectCode,
        reason: str,
    ) -> EVGateResult:
        """Set rejection on result and return it."""
        result.decision = "REJECT"
        result.reject_code = code
        result.reject_reason = reason
        return result
    
    def _normalize_percentile(self, value: Optional[float], default: float = 0.5) -> float:
        """
        Normalize percentile to 0-1 scale.
        
        FIX #2: Handles both 0-1 and 0-100 scales from upstream.
        
        Args:
            value: Raw percentile value (may be 0-1 or 0-100)
            default: Default value if None
            
        Returns:
            Percentile in 0-1 scale
        """
        if value is None:
            return default
        value = float(value)
        # If value > 1, assume it's in 0-100 scale
        if value > 1.0:
            return value / 100.0
        return value
    
    def _normalize_p(self, p_raw: Optional[float], ctx_symbol: str = "") -> float:
        """
        Normalize probability to [0, 1] scale.
        
        FIX #3: Explicit percent detection to avoid dividing 1.2 → 0.012.
        
        Args:
            p_raw: Raw probability value (may be 0-1 or 0-100)
            ctx_symbol: Symbol for logging
            
        Returns:
            Probability in [0, 1] scale
        """
        if p_raw is None:
            return 0.5  # Conservative default
        
        p = float(p_raw)
        
        # Treat [0, 1] as probability
        if 0.0 <= p <= 1.0:
            return p
        
        # Treat (1, 100] as percentage
        if 1.0 < p <= 100.0:
            return p / 100.0
        
        # Otherwise clamp and log error
        log_error(
            "ev_gate_invalid_p: Probability out of expected range",
            symbol=ctx_symbol,
            p_raw=p_raw,
        )
        return max(0.0, min(1.0, p))
    
    def _has_implicit_target(self, strategy_id: str) -> bool:
        """Check if strategy has implicit target (time-based exit, etc.)."""
        # Strategies with time-based exits or other implicit targets
        implicit_target_strategies = {
            "time_based_exit",
            "trailing_stop",
        }
        return strategy_id in implicit_target_strategies
    
    def _estimate_implicit_target(
        self,
        entry_price: float,
        stop_loss: float,
        side: str,
        strategy_id: str,
    ) -> float:
        """Estimate implicit target for strategies without explicit TP."""
        # Default: assume R=1 (target = same distance as stop)
        stop_distance = abs(entry_price - stop_loss)
        if side.lower() == "long":
            return entry_price + stop_distance
        else:
            return entry_price - stop_distance

    def _sanitize_age_ms(self, age_ms: Optional[float]) -> Optional[float]:
        """Normalize and validate age values from mixed timestamp sources."""
        if age_ms is None:
            return None
        try:
            age = float(age_ms)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(age):
            return None
        # Future timestamps / unit mismatches should be treated as invalid, not fresh.
        if age < 0:
            return None
        return age
    
    def _get_book_age_ms(self, ctx: StageContext) -> Optional[float]:
        """
        Get orderbook age in milliseconds.
        
        FIX #4: Returns None if timestamp missing (caller should reject as stale).
        Diagnostic override: when IGNORE_FEED_GAPS is set, treat missing ts as fresh (0ms).
        
        Args:
            ctx: Stage context
            
        Returns:
            Book age in milliseconds, or None if timestamp not available.
        """
        if os.getenv("IGNORE_FEED_GAPS", "false").lower() in {"1", "true", "yes"}:
            return 0.0
        market_context = ctx.data.get("market_context") or {}
        current_time_ms = time.time() * 1000
        book_lag_ms = market_context.get("book_lag_ms") or market_context.get("orderbook_lag_ms")
        book_recv_ms = market_context.get("book_recv_ms")
        book_cts_ms = market_context.get("book_cts_ms")
        book_ts = market_context.get("book_timestamp_ms") or market_context.get("timestamp_ms")
        feed_staleness = market_context.get("feed_staleness") or {}
        ob_staleness_sec = feed_staleness.get("orderbook")

        if book_lag_ms is not None:
            return self._sanitize_age_ms(book_lag_ms)
        if ob_staleness_sec is not None:
            return self._sanitize_age_ms(ob_staleness_sec * 1000)
        if book_recv_ms is not None:
            return self._sanitize_age_ms(current_time_ms - book_recv_ms)
        if book_ts:
            return self._sanitize_age_ms(current_time_ms - book_ts)
        if book_cts_ms is not None:
            return self._sanitize_age_ms(current_time_ms - book_cts_ms)
        return None
    
    def _get_spread_age_ms(self, ctx: StageContext) -> Optional[float]:
        """
        Get spread data age in milliseconds.
        
        FIX #4: Returns None if timestamp missing (caller should reject as stale).
        Diagnostic override: when IGNORE_FEED_GAPS is set, treat missing ts as fresh (0ms).
        
        Args:
            ctx: Stage context
            
        Returns:
            Spread age in milliseconds, or None if timestamp not available.
        """
        if os.getenv("IGNORE_FEED_GAPS", "false").lower() in {"1", "true", "yes"}:
            return 0.0
        market_context = ctx.data.get("market_context") or {}
        features = ctx.data.get("features") or {}
        current_time_ms = time.time() * 1000

        feed_staleness = market_context.get("feed_staleness") or {}
        ob_staleness_sec = feed_staleness.get("orderbook")
        if ob_staleness_sec is not None:
            return self._sanitize_age_ms(ob_staleness_sec * 1000)
        
        book_recv_ms = market_context.get("book_recv_ms")
        book_cts_ms = market_context.get("book_cts_ms")
        if book_recv_ms is not None:
            return self._sanitize_age_ms(current_time_ms - book_recv_ms)
        spread_ts = market_context.get("spread_timestamp_ms") or features.get("spread_timestamp_ms")
        if spread_ts is not None:
            return self._sanitize_age_ms(current_time_ms - spread_ts)
        if book_cts_ms is not None:
            return self._sanitize_age_ms(current_time_ms - book_cts_ms)
        
        return None

    def _log_staleness_details(
        self,
        ctx: StageContext,
        book_age_ms: Optional[float],
        spread_age_ms: Optional[float],
    ) -> None:
        market_context = ctx.data.get("market_context") or {}
        log_warning(
            "ev_gate_staleness_inputs",
            symbol=ctx.symbol,
            book_age_ms=book_age_ms,
            spread_age_ms=spread_age_ms,
            max_book_age_ms=self.config.max_book_age_ms,
            max_spread_age_ms=self.config.max_spread_age_ms,
            book_timestamp_ms=market_context.get("book_timestamp_ms"),
            timestamp_ms=market_context.get("timestamp_ms"),
            book_recv_ms=market_context.get("book_recv_ms"),
            book_cts_ms=market_context.get("book_cts_ms"),
            book_lag_ms=market_context.get("book_lag_ms"),
            orderbook_lag_ms=market_context.get("orderbook_lag_ms"),
            spread_timestamp_ms=market_context.get("spread_timestamp_ms"),
            quote_timestamp_ms=market_context.get("quote_timestamp_ms"),
            feed_staleness=market_context.get("feed_staleness"),
        )
    
    def _estimate_size_usd(self, signal: dict, entry_price: float) -> float:
        """Estimate position size in USD from signal."""
        size = signal.get("size") or signal.get("quantity", 0)
        if size and entry_price:
            return abs(float(size) * float(entry_price))
        return 0.0
    
    def _extract_setup_type(self, strategy_id: str, meta_reason: str) -> str:
        """Extract setup type from strategy_id or meta_reason.
        
        FIX #5: Delegates to ExecutionPolicy.infer_setup_type() as the canonical source,
        with fallback to meta_reason parsing for additional context.
        
        Args:
            strategy_id: Strategy identifier
            meta_reason: Signal meta reason
            
        Returns:
            Setup type (e.g., "mean_reversion", "breakout", "trend_pullback")
        """
        # FIX #5: Use ExecutionPolicy as the canonical source for setup type inference
        # This avoids drift between duplicate implementations
        setup_type = self.cost_estimator.execution_policy.infer_setup_type(strategy_id)
        
        # If ExecutionPolicy returns "unknown", try to extract from meta_reason
        if setup_type == "unknown" and meta_reason:
            meta_lower = meta_reason.lower()
            if "mean_reversion" in meta_lower or "fade" in meta_lower:
                return "mean_reversion"
            elif "breakout" in meta_lower:
                return "breakout"
            elif "pullback" in meta_lower:
                return "trend_pullback"
        
        # If still unknown, default to mean_reversion (conservative)
        if setup_type == "unknown":
            return "mean_reversion"
        
        return setup_type
    
    def _estimate_hold_time(self, strategy_id: str, setup_type: str) -> float:
        """Estimate expected hold time in seconds based on strategy.
        
        Args:
            strategy_id: Strategy identifier
            setup_type: Setup type
            
        Returns:
            Expected hold time in seconds
        """
        # Mean reversion: typically quick (5-15 min)
        if setup_type == "mean_reversion":
            return 600.0  # 10 minutes
        
        # Breakout: medium hold (15-30 min)
        elif setup_type == "breakout":
            return 1200.0  # 20 minutes
        
        # Trend pullback: longer hold (30-60 min)
        elif setup_type == "trend_pullback":
            return 2400.0  # 40 minutes
        
        # Low vol grind: very long hold (1-4 hours)
        elif setup_type == "low_vol_grind":
            return 7200.0  # 2 hours
        
        # Default: 5 minutes
        return 300.0

    def _mean_reversion_pmin_tolerance(self, symbol: Optional[str] = None) -> float:
        symbol_key = str(symbol or "").strip().upper()
        raw_by_symbol = os.getenv("EV_GATE_MEAN_REVERSION_PMIN_TOLERANCE_BY_SYMBOL", "")
        if symbol_key and raw_by_symbol:
            for token in raw_by_symbol.replace(";", ",").split(","):
                entry = token.strip()
                if not entry or ":" not in entry:
                    continue
                raw_symbol, raw_value = entry.split(":", 1)
                if raw_symbol.strip().upper() != symbol_key:
                    continue
                try:
                    return max(0.0, float(raw_value.strip()))
                except (TypeError, ValueError):
                    break
        raw = os.getenv(
            "EV_GATE_MEAN_REVERSION_PMIN_TOLERANCE",
            str(P_MIN_TOLERANCE_MEAN_REVERSION_DEFAULT),
        )
        try:
            return max(0.0, float(raw))
        except (TypeError, ValueError):
            return P_MIN_TOLERANCE_MEAN_REVERSION_DEFAULT

    def _mean_reversion_expected_edge_tolerance_bps(self, symbol: Optional[str] = None) -> float:
        symbol_key = str(symbol or "").strip().upper()
        raw_by_symbol = os.getenv(
            "EV_GATE_MEAN_REVERSION_EXPECTED_EDGE_TOLERANCE_BPS_BY_SYMBOL",
            "",
        )
        if symbol_key and raw_by_symbol:
            for token in raw_by_symbol.replace(";", ",").split(","):
                entry = token.strip()
                if not entry or ":" not in entry:
                    continue
                raw_symbol, raw_value = entry.split(":", 1)
                if raw_symbol.strip().upper() != symbol_key:
                    continue
                try:
                    return max(0.0, float(raw_value.strip()))
                except (TypeError, ValueError):
                    break
        raw = os.getenv(
            "EV_GATE_MEAN_REVERSION_EXPECTED_EDGE_TOLERANCE_BPS",
            str(EXPECTED_EDGE_TOLERANCE_MEAN_REVERSION_BPS_DEFAULT),
        )
        try:
            return max(0.0, float(raw))
        except (TypeError, ValueError):
            return EXPECTED_EDGE_TOLERANCE_MEAN_REVERSION_BPS_DEFAULT

    # =========================================================================
    # Safety Guard Methods (Requirements 10.1, 10.2, 10.3, 10.4)
    # =========================================================================
    
    def _check_required_fields(
        self,
        ctx: StageContext,
        signal: dict,
        market_context: dict,
        features: dict,
        prediction: dict,
    ) -> Optional[str]:
        """
        Check ONLY the truly required input fields.
        
        Requirement 5.1: THE EVGate SHALL require only:
        - entry_price
        - side
        - (sl_distance_bps OR sl_price)
        - (tp_distance_bps OR tp_price) UNLESS strategy has implicit target
        
        FIX #2: Check for implicit target strategies BEFORE rejecting for missing TP.
        Strategies with time-based exits or trailing stops don't need explicit TP.
        
        All other fields (cost_estimate, p_hat, etc.) are OPTIONAL and will be
        filled with conservative defaults by compute_defaults().
        
        Args:
            ctx: Stage context
            signal: Signal data
            market_context: Market context data
            features: Feature data
            prediction: Prediction data
            
        Returns:
            Name of missing field, or None if all required fields are present.
        """
        # Check for entry price (required for EV calculation)
        # Try multiple sources: signal, market_context, features
        entry_price = (
            signal.get("entry_price") or 
            market_context.get("price") or 
            market_context.get("mid_price") or
            features.get("price") or
            features.get("mid_price")
        )
        if entry_price is None or entry_price <= 0:
            return "entry_price"
        
        # Check for side (required to determine L and G direction)
        side = signal.get("side")
        if not side:
            return "side"
        
        # Check for SL - accept EITHER sl_distance_bps OR sl_price (or stop_loss)
        has_sl = (
            signal.get("sl_distance_bps") is not None or
            signal.get("sl_price") is not None or
            signal.get("stop_loss") is not None
        )
        if not has_sl:
            return "sl_distance_bps or sl_price"
        
        # Check for TP - accept EITHER tp_distance_bps OR tp_price (or take_profit)
        # FIX #2: Allow missing TP for strategies with implicit targets
        has_tp = (
            signal.get("tp_distance_bps") is not None or
            signal.get("tp_price") is not None or
            signal.get("take_profit") is not None or
            signal.get("target_price") is not None
        )
        if not has_tp:
            # Check if strategy has implicit target before rejecting
            strategy_id = signal.get("strategy_id", "")
            if not self._has_implicit_target(strategy_id):
                return "tp_distance_bps or tp_price"
            # Strategy has implicit target, TP will be estimated later
        
        # NOTE: bid/ask, confidence, cost_estimate are NOT required
        # They will be filled with conservative defaults by compute_defaults()
        
        # All required fields present
        return None
    
    def _compute_defaults(
        self,
        ctx: StageContext,
        signal: dict,
    ) -> dict:
        """
        Fill missing optional fields with CONSERVATIVE defaults.
        
        Requirement 5.7: THE EVGate SHALL provide compute_defaults(ctx, signal)
        to fill missing optional fields.
        
        FIX #3: Use setdefault() to ensure defaults persist into ctx.data dicts.
        
        Args:
            ctx: Stage context
            signal: Signal data (will be modified in place)
            
        Returns:
            Dict of fields that were defaulted with their values.
        """
        defaulted = {}
        
        # FIX #3: Use setdefault to ensure dicts exist and persist
        market_context = ctx.data.get("market_context") or {}
        features = ctx.data.get("features") or {}
        prediction = ctx.data.get("prediction") or {}
        ctx.data["market_context"] = market_context
        ctx.data["features"] = features
        ctx.data["prediction"] = prediction
        
        # Get entry price for conversions
        entry_price = (
            signal.get("entry_price") or 
            market_context.get("price") or 
            market_context.get("mid_price") or
            features.get("price") or
            features.get("mid_price") or
            0.0
        )
        mid_price = (
            market_context.get("mid_price") or
            features.get("mid_price") or
            entry_price
        )
        
        # Default p_hat based on strategy type - CONSERVATIVE (Requirement 5.3)
        #
        # IMPORTANT:
        # prediction["confidence"] is NOT necessarily a calibrated P(win). Treating it as p_hat
        # silently corrupts EV calculations (and can cause systematic fee-burn / bad entries).
        # Until we ship an explicit calibrated probability contract (ONNX + calibration),
        # EVGate must *never* derive p_hat from prediction confidence.
        if "p_hat" not in signal or signal.get("p_hat") is None:
            strategy_id = signal.get("strategy_id", "")
            setup_type = self._extract_setup_type(strategy_id, signal.get("meta_reason", ""))
            p_hat = REGIME_P_HAT_DEFAULTS_CONSERVATIVE.get(
                setup_type,
                REGIME_P_HAT_DEFAULTS_CONSERVATIVE["default"]
            )
            signal["p_hat"] = p_hat
            signal["p_hat_source"] = "uncalibrated_conservative"
            defaulted["p_hat"] = p_hat
            defaulted["p_hat_source"] = "uncalibrated_conservative"

            # Log warning when using uncalibrated fallback (Requirement 5.9)
            log_warning(
                "ev_gate_using_uncalibrated_p_hat",
                symbol=ctx.symbol,
                strategy_id=strategy_id,
                p_hat=p_hat,
                setup_type=setup_type,
                prediction_confidence=prediction.get("confidence"),
            )
        
        # Default cost estimate from context (Requirement 5.6)
        if "cost_estimate_bps" not in signal or signal.get("cost_estimate_bps") is None:
            spread_bps = market_context.get("spread_bps", 3.0)  # Conservative default
            fee_bps = 7.0  # Conservative default (was 6.0)
            slippage_bps = 3.0  # Conservative default (was 2.0)
            cost_estimate = spread_bps + fee_bps + slippage_bps
            signal["cost_estimate_bps"] = cost_estimate
            defaulted["cost_estimate_bps"] = cost_estimate
        
        # Convert SL/TP prices to distances if needed (Requirement 5.8)
        # FIX #6: Use entry_price as denominator for consistency with calculate_L_G_R()
        side = signal.get("side", "long").lower()
        
        # Handle SL conversion
        if signal.get("sl_distance_bps") is None:
            sl_price = signal.get("sl_price") or signal.get("stop_loss")
            if sl_price is not None and entry_price > 0:
                # Convert price to distance using entry_price as denominator (consistent with calculate_L_G_R)
                sl_distance_bps = abs(entry_price - sl_price) / entry_price * 10000
                signal["sl_distance_bps"] = sl_distance_bps
                defaulted["sl_distance_bps"] = sl_distance_bps
                defaulted["sl_distance_bps_source"] = "converted_from_price"
        
        # Handle TP conversion
        if signal.get("tp_distance_bps") is None:
            tp_price = signal.get("tp_price") or signal.get("take_profit") or signal.get("target_price")
            if tp_price is not None and entry_price > 0:
                # Convert price to distance using entry_price as denominator (consistent with calculate_L_G_R)
                tp_distance_bps = abs(tp_price - entry_price) / entry_price * 10000
                signal["tp_distance_bps"] = tp_distance_bps
                defaulted["tp_distance_bps"] = tp_distance_bps
                defaulted["tp_distance_bps_source"] = "converted_from_price"
        
        # Default bid/ask from entry_price if missing (for backtesting)
        best_bid = (
            market_context.get("best_bid") or 
            features.get("best_bid") or
            features.get("bid") or
            market_context.get("bid")
        )
        best_ask = (
            market_context.get("best_ask") or 
            features.get("best_ask") or
            features.get("ask") or
            market_context.get("ask")
        )
        
        if best_bid is None or best_bid <= 0:
            best_bid = entry_price * 0.9999  # Slight offset for bid
            market_context["best_bid"] = best_bid
            features["best_bid"] = best_bid
            defaulted["best_bid"] = best_bid
        if best_ask is None or best_ask <= 0:
            best_ask = entry_price * 1.0001  # Slight offset for ask
            market_context["best_ask"] = best_ask
            features["best_ask"] = best_ask
            defaulted["best_ask"] = best_ask
        
        # Log which fields were defaulted (Requirement 5.9)
        if defaulted:
            log_info(
                "ev_gate_fields_defaulted",
                symbol=ctx.symbol,
                strategy_id=signal.get("strategy_id", ""),
                defaulted_fields=list(defaulted.keys()),
                defaulted_values=defaulted,
            )
        
        return defaulted
    
    # FIX #7: Removed dead code _get_ev_min_adjusted_for_calibration()
    # Cold-start safety is now handled by:
    # 1. Bayesian shrinkage for p_effective (in _evaluate)
    # 2. Size reduction (in ctx.data["calibration_size_multiplier"])
    # 3. min_edge_bps_adjustment scaled by L_bps (in _get_adjusted_ev_min)
    
    def _check_connectivity(
        self,
        ctx: StageContext,
        market_context: dict,
    ) -> Optional[Tuple[EVGateRejectCode, str]]:
        """
        Check exchange connectivity and orderbook sync status.
        
        Requirements:
        - 10.2: WHEN exchange connectivity is degraded (latency > MAX_EXCHANGE_LATENCY_MS),
                THEN THE EV_Gate SHALL reject with reason "exchange_connectivity_degraded"
        - 10.3: WHEN orderbook is out-of-sync or lagging > MAX_BOOK_AGE_MS,
                THEN THE EV_Gate SHALL reject with reason "orderbook_stale"
        
        Args:
            ctx: Stage context
            market_context: Market context data
            
        Returns:
            Tuple of (reject_code, reason) if connectivity check fails, None otherwise.
        """
        # Check exchange latency (Requirement 10.2)
        exchange_latency_ms = market_context.get("exchange_latency_ms")
        if exchange_latency_ms is not None and exchange_latency_ms > self.config.max_exchange_latency_ms:
            return (
                EVGateRejectCode.EXCHANGE_CONNECTIVITY,
                f"Exchange connectivity degraded: latency={exchange_latency_ms:.0f}ms > max={self.config.max_exchange_latency_ms}ms"
            )
        
        # Check orderbook sync status (Requirement 10.3)
        orderbook_synced = market_context.get("orderbook_synced")
        if orderbook_synced is not None and not orderbook_synced:
            return (
                EVGateRejectCode.ORDERBOOK_SYNC,
                "Orderbook out-of-sync"
            )
        
        # Check orderbook lag (also part of Requirement 10.3)
        orderbook_lag_ms = market_context.get("orderbook_lag_ms") or market_context.get("book_lag_ms")
        if orderbook_lag_ms is not None and orderbook_lag_ms > self.config.max_book_age_ms:
            return (
                EVGateRejectCode.ORDERBOOK_SYNC,
                f"Orderbook lagging: lag={orderbook_lag_ms:.0f}ms > max={self.config.max_book_age_ms}ms"
            )
        
        # All connectivity checks passed
        return None
    
    def _get_adjusted_ev_min(
        self,
        calibration_reliability: float,
        spread_percentile: float = 0.5,
        book_imbalance: float = 0.0,
        signal_side: str = "long",
        volatility_regime: str = "medium",
        session: str = "unknown",
        book_age_ms: float = 0.0,
        calibration_status: Optional[CalibrationStatus] = None,
        L_bps: float = 100.0,
    ) -> Tuple[float, Optional[str]]:
        """
        Get adjusted EV_Min with relaxation and cold-start handling.
        
        UPDATED: No longer applies 5x penalty for low reliability.
        Instead, uses calibration state machine with shrinkage.
        
        Cold-start safety is handled via:
        1. Bayesian shrinkage for p_effective (in _evaluate)
        2. Size reduction (in ctx.data["calibration_size_multiplier"])
        3. Tighter cost gates (via min_edge_bps_adjustment scaled by L_bps)
        
        Requirements:
        - 6.1-6.5: Conditional relaxation based on market conditions
        - 6.6, 6.7: Safety guards for relaxation
        
        Args:
            calibration_reliability: Calibration reliability score (0 to 1)
            spread_percentile: Current spread relative to historical distribution (0-1)
            book_imbalance: Ratio of bid vs ask depth (positive = more bids), [-1, 1]
            signal_side: "long" or "short"
            volatility_regime: "low", "medium", or "high"
            session: Trading session ("us", "europe", "asia", etc.)
            book_age_ms: Orderbook age in milliseconds
            calibration_status: Optional CalibrationStatus from state machine
            L_bps: Stop loss distance in bps (for scaling edge adjustment)
            
        Returns:
            Tuple of (adjusted_ev_min, adjustment_reason).
        """
        ev_min_base = self.config.ev_min
        reasons = []
        
        # REMOVED: The old 5x penalty for low reliability
        # Instead, cold-start safety is handled by:
        # 1. Bayesian shrinkage for p_effective
        # 2. Size reduction via calibration_status.size_multiplier
        # 3. min_edge_bps_adjustment scaled by L_bps for proper EV units
        
        # FIX #6: Apply cold-start min_edge adjustment scaled by L_bps
        # EV is in units of "stop loss", so edge_bps / L_bps gives proper EV units
        if calibration_status is not None and calibration_status.min_edge_bps_adjustment > 0:
            # Convert bps edge requirement to EV units using actual stop distance
            # extra_ev_margin = edge_bps / L_bps
            # This makes the adjustment consistent across symbols and strategies
            L_bps_safe = max(L_bps, 1.0)  # Avoid division by zero
            ev_adjustment = calibration_status.min_edge_bps_adjustment / L_bps_safe
            ev_min_base = ev_min_base + ev_adjustment
            reasons.append(f"cold_start_edge_adj (+{calibration_status.min_edge_bps_adjustment:.1f}bps / {L_bps_safe:.0f}bps = +{ev_adjustment:.4f} EV)")
            
            log_info(
                "ev_gate_cold_start_adjustment",
                calibration_state=calibration_status.state.value,
                min_edge_bps_adjustment=calibration_status.min_edge_bps_adjustment,
                L_bps=L_bps_safe,
                ev_adjustment=round(ev_adjustment, 4),
                size_multiplier=calibration_status.size_multiplier,
            )
        
        # Apply relaxation/tightening (Requirements 6.1-6.7)
        relaxation_result = self.relaxation_engine.compute_adjustment(
            spread_percentile=spread_percentile,
            book_imbalance=book_imbalance,
            signal_side=signal_side,
            volatility_regime=volatility_regime,
            session=session,
            calibration_reliability=calibration_reliability,
            book_age_ms=book_age_ms,
        )
        
        # Apply the adjustment factor with floor enforcement
        ev_min_adjusted = self.relaxation_engine.apply_adjustment(
            ev_min_base=ev_min_base,
            adjustment_factor=relaxation_result.adjustment_factor,
        )
        
        # Build adjustment reason
        if relaxation_result.reason:
            reasons.append(relaxation_result.reason)
        
        adjustment_reason = "; ".join(reasons) if reasons else None
        
        # Log relaxation if applied
        if relaxation_result.adjustment_factor != 1.0:
            log_info(
                "ev_gate_relaxation_applied",
                adjustment_factor=relaxation_result.adjustment_factor,
                reason=relaxation_result.reason,
                ev_min_base=ev_min_base,
                ev_min_adjusted=ev_min_adjusted,
                candidate_factors=[f for f, _ in relaxation_result.candidate_factors],
            )
        
        return ev_min_adjusted, adjustment_reason
    
    def _log_decision(self, ctx: StageContext, result: EVGateResult) -> None:
        """Log the EV gate decision with comprehensive cost breakdown."""
        log_func = log_warning if result.decision == "REJECT" else log_info
        
        # Enhanced cost logging (Phase 3)
        log_func(
            "ev_gate_decision",
            symbol=ctx.symbol,
            decision=result.decision,
            reject_code=result.reject_code.value if result.reject_code else None,
            # Probabilities
            p=round(result.p_calibrated, 4),
            p_min=round(result.p_min, 4),
            # EV components
            R=round(result.R, 3),
            C=round(result.C, 4),
            EV=round(result.EV, 4),
            ev_min=round(result.ev_min_adjusted, 4),
            # Distances
            L_bps=round(result.L_bps, 2),
            G_bps=round(result.G_bps, 2),
            # Cost breakdown (Phase 3 enhancement)
            fee_bps=round(result.fee_bps, 2),
            spread_bps=round(result.spread_bps, 2),
            slippage_bps=round(result.slippage_bps, 2),
            adverse_selection_bps=round(result.adverse_selection_bps, 2),
            total_cost_bps=round(result.total_cost_bps, 2),
            # Threshold adjustments
            adjustment_factor=round(result.adjustment_factor, 3) if result.adjustment_factor != 1.0 else None,
            adjustment_reason=result.adjustment_reason,
            # Mode
            mode=self.config.mode,
        )
        
        # Record to metrics collector for API access
        if _HAS_METRICS_COLLECTOR:
            try:
                signal = ctx.signal
                # Convert signal to dict if it's a dataclass
                if hasattr(signal, '__dataclass_fields__'):
                    signal = asdict(signal)
                elif not isinstance(signal, dict):
                    signal = getattr(signal, '__dict__', {}) or {}
                signal = signal or {}
                
                market_context = ctx.data.get("market_context") or {}
                prediction = ctx.data.get("prediction") or {}
                
                decision_log = EVGateDecisionLog(
                    timestamp=time.time(),
                    symbol=ctx.symbol,
                    signal_id=signal.get("signal_id", ""),
                    decision=result.decision,
                    reject_code=result.reject_code.value if result.reject_code else None,
                    reject_reason=result.reject_reason,
                    # Use the EV input probability (signal p_hat), not generic prediction confidence.
                    p_hat=float(signal.get("p_hat", result.p_calibrated) or 0.0),
                    p_calibrated=result.p_calibrated,
                    p_min=result.p_min,
                    R=result.R,
                    C=result.C,
                    EV=result.EV,
                    L_bps=result.L_bps,
                    G_bps=result.G_bps,
                    spread_bps=result.spread_bps,
                    fee_bps=result.fee_bps,
                    slippage_bps=result.slippage_bps,
                    adverse_selection_bps=result.adverse_selection_bps,
                    total_cost_bps=result.total_cost_bps,
                    ev_min_base=result.ev_min_base,
                    ev_min_adjusted=result.ev_min_adjusted,
                    adjustment_factor=result.adjustment_factor,
                    adjustment_reason=result.adjustment_reason,
                    regime_label=market_context.get("regime_label"),
                    session=market_context.get("session"),
                    volatility_regime=market_context.get("volatility_regime"),
                    strategy_id=signal.get("strategy_id"),
                    calibration_method=result.calibration_method,
                    calibration_reliability=result.calibration_reliability,
                    book_age_ms=result.book_age_ms,
                    spread_age_ms=result.spread_age_ms,
                    ev_gate_would_reject=ctx.data.get("ev_gate_would_reject"),
                    confidence_gate_rejected=ctx.data.get("confidence_gate_rejected"),
                )
                
                collector = get_metrics_collector()
                collector.record_decision(decision_log)
            except Exception as e:
                log_warning("ev_gate_metrics_record_failed", error=str(e))
