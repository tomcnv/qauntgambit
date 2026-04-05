"""
Context Vector - Full feature aggregation for profile scoring

Aggregates all available market data into a comprehensive context vector
that can be used for profile scoring, ML models, and decision making.

Context Vector Parity (Requirements 1-7):
- Unified builder ensures live and backtest produce equivalent outputs
- Shared validation and derivation logic for all data sources
- Consistent regime_family derivation via RegimeMapper
"""

from dataclasses import dataclass, field
from typing import Dict, Optional, List, Tuple, TYPE_CHECKING
from datetime import datetime, timezone
from collections import deque
import logging
import time

if TYPE_CHECKING:
    from .regime_mapper import RegimeMapper
    from .router_config import RouterConfig

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# CONTEXT VECTOR CONFIGURATION (Context Vector Parity - Req 2, 3)
# ═══════════════════════════════════════════════════════════════

@dataclass
class ContextVectorConfig:
    """Configuration for ContextVector building and validation.
    
    This configuration is shared between live and backtest builders
    to ensure consistent behavior.
    
    Requirements: 2.1, 3.1, 3.3, 3.4, 3.5
    """
    # Spread validation (Requirement 2.1)
    min_spread_bps: float = 0.1
    max_spread_bps: float = 100.0
    default_spread_bps: float = 5.0
    
    # Cost defaults (Requirement 3.1)
    default_fee_bps: float = 12.0  # 6 bps taker × 2 for round-trip
    
    # Slippage tiers (Requirements 3.3, 3.4, 3.5)
    high_depth_threshold_usd: float = 100000.0
    medium_depth_threshold_usd: float = 50000.0
    high_depth_slippage_bps: float = 0.5
    medium_depth_slippage_bps: float = 1.0
    low_depth_slippage_bps: float = 2.0
    
    # ATR ratio mapping from vol_regime (Requirement 4.5)
    atr_ratio_low: float = 0.5
    atr_ratio_normal: float = 1.0
    atr_ratio_high: float = 1.5
    atr_ratio_extreme: float = 2.0
    
    # EMA spread derivation multiplier (Requirement 4.2, 4.3)
    ema_spread_multiplier: float = 0.01


# ═══════════════════════════════════════════════════════════════
# SPREAD VALIDATION (Context Vector Parity - Requirement 2)
# ═══════════════════════════════════════════════════════════════

@dataclass
class SpreadValidationResult:
    """Result of spread validation.
    
    Requirements: 2.1, 2.2, 2.3, 2.4
    """
    spread_bps: float
    was_clamped: bool
    was_defaulted: bool
    original_value: float
    warning_message: Optional[str]


def validate_spread_bps(
    spread_bps: float,
    bid: Optional[float] = None,
    ask: Optional[float] = None,
    price: Optional[float] = None,
    config: Optional[ContextVectorConfig] = None,
) -> SpreadValidationResult:
    """
    Validate and clamp spread_bps to valid range.
    
    Requirements:
    - 2.1: Clamp spread to [0.1, 100.0] range
    - 2.2: Default to 5.0 bps when invalid (0 or negative)
    - 2.3: Detect crossed books (bid >= ask) and estimate spread
    - 2.4: Log warnings when validation occurs
    - 2.5: Assert best_ask > best_bid before computing
    
    Args:
        spread_bps: Raw spread value in basis points
        bid: Best bid price (optional, for crossed book detection)
        ask: Best ask price (optional, for crossed book detection)
        price: Mid price (optional, for spread estimation)
        config: Optional configuration (uses defaults if None)
        
    Returns:
        SpreadValidationResult with validated spread and metadata
    """
    cfg = config or ContextVectorConfig()
    original_value = spread_bps
    was_clamped = False
    was_defaulted = False
    warning_message = None
    
    # Check for crossed book (Requirement 2.3, 2.5)
    if bid is not None and ask is not None:
        if bid >= ask:
            # Crossed book - estimate spread from price
            warning_message = f"Crossed book detected (bid={bid:.2f} >= ask={ask:.2f}), using default spread"
            logger.warning(warning_message)
            spread_bps = cfg.default_spread_bps
            was_defaulted = True
            return SpreadValidationResult(
                spread_bps=spread_bps,
                was_clamped=False,
                was_defaulted=True,
                original_value=original_value,
                warning_message=warning_message,
            )
    
    # Check for invalid spread (Requirement 2.2)
    if spread_bps <= 0:
        warning_message = f"Invalid spread_bps={spread_bps:.4f}, using default {cfg.default_spread_bps}"
        logger.warning(warning_message)
        spread_bps = cfg.default_spread_bps
        was_defaulted = True
    
    # Clamp to valid range (Requirement 2.1)
    if spread_bps < cfg.min_spread_bps:
        warning_message = f"Spread {spread_bps:.4f} below min, clamping to {cfg.min_spread_bps}"
        logger.warning(warning_message)
        spread_bps = cfg.min_spread_bps
        was_clamped = True
    elif spread_bps > cfg.max_spread_bps:
        warning_message = f"Spread {spread_bps:.4f} above max, clamping to {cfg.max_spread_bps}"
        logger.warning(warning_message)
        spread_bps = cfg.max_spread_bps
        was_clamped = True
    
    return SpreadValidationResult(
        spread_bps=spread_bps,
        was_clamped=was_clamped,
        was_defaulted=was_defaulted,
        original_value=original_value,
        warning_message=warning_message,
    )


# ═══════════════════════════════════════════════════════════════
# COST FIELDS CALCULATION (Context Vector Parity - Requirement 3)
# ═══════════════════════════════════════════════════════════════

@dataclass
class CostFieldsResult:
    """Result of cost fields calculation.
    
    Requirements: 3.1, 3.2, 3.3, 3.4, 3.5
    """
    expected_fee_bps: float
    expected_cost_bps: float
    slippage_estimate_bps: float


def calculate_cost_fields(
    spread_bps: float,
    bid_depth_usd: float,
    ask_depth_usd: float,
    config: Optional[ContextVectorConfig] = None,
    custom_fee_bps: Optional[float] = None,
) -> CostFieldsResult:
    """
    Calculate expected cost fields for ContextVector.
    
    Requirements:
    - 3.1: Set expected_fee_bps to 12.0 bps by default
    - 3.2: Calculate expected_cost_bps = spread + fees + slippage
    - 3.3: Use 0.5 bps slippage for depth > $100k
    - 3.4: Use 1.0 bps slippage for $50k < depth <= $100k
    - 3.5: Use 2.0 bps slippage for depth <= $50k
    - 3.6: Support custom fee configuration
    - 3.7: No double-counting of spread/slippage
    
    Args:
        spread_bps: Validated spread in basis points
        bid_depth_usd: Bid side depth in USD
        ask_depth_usd: Ask side depth in USD
        config: Optional configuration (uses defaults if None)
        custom_fee_bps: Optional custom fee override (Requirement 3.6)
        
    Returns:
        CostFieldsResult with fee, cost, and slippage estimates
    """
    cfg = config or ContextVectorConfig()
    
    # Use custom fee if provided, otherwise default (Requirement 3.6)
    expected_fee_bps = custom_fee_bps if custom_fee_bps is not None else cfg.default_fee_bps
    
    # Calculate total depth (handle negative values gracefully)
    total_depth_usd = max(0.0, bid_depth_usd) + max(0.0, ask_depth_usd)
    
    # Determine slippage based on depth tiers (Requirements 3.3, 3.4, 3.5)
    if total_depth_usd > cfg.high_depth_threshold_usd:
        slippage_estimate_bps = cfg.high_depth_slippage_bps
    elif total_depth_usd > cfg.medium_depth_threshold_usd:
        slippage_estimate_bps = cfg.medium_depth_slippage_bps
    else:
        slippage_estimate_bps = cfg.low_depth_slippage_bps
    
    # Calculate total expected cost (Requirement 3.2, 3.7)
    # No double-counting: spread is the bid-ask spread, slippage is additional market impact
    expected_cost_bps = spread_bps + expected_fee_bps + slippage_estimate_bps
    
    return CostFieldsResult(
        expected_fee_bps=expected_fee_bps,
        expected_cost_bps=expected_cost_bps,
        slippage_estimate_bps=slippage_estimate_bps,
    )


# ═══════════════════════════════════════════════════════════════
# TREND FIELDS DERIVATION (Context Vector Parity - Requirement 4)
# ═══════════════════════════════════════════════════════════════

@dataclass
class TrendFieldsResult:
    """Result of trend fields derivation.
    
    Requirements: 4.1, 4.2, 4.3, 4.4, 4.5
    """
    ema_spread_pct: float
    atr_ratio: float


def derive_trend_fields(
    trend_direction: str,
    trend_strength: float,
    vol_regime: str,
    existing_ema_spread_pct: Optional[float] = None,
    existing_atr_ratio: Optional[float] = None,
    config: Optional[ContextVectorConfig] = None,
) -> TrendFieldsResult:
    """
    Derive trend fields from available snapshot data.
    
    Requirements:
    - 4.1: Derive ema_spread_pct from trend_direction and trend_strength when not available
    - 4.2: If trend_direction is "up", ema_spread_pct = trend_strength * 0.01 (positive)
    - 4.3: If trend_direction is "down", ema_spread_pct = -trend_strength * 0.01 (negative)
    - 4.4: If trend_direction is "flat" or "neutral", ema_spread_pct = 0.0
    - 4.5: Derive atr_ratio from vol_regime: "low" → 0.5, "normal" → 1.0, "high" → 1.5, "extreme" → 2.0
    
    Args:
        trend_direction: "up", "down", "flat", or "neutral"
        trend_strength: Trend strength value (0.0 to 1.0)
        vol_regime: "low", "normal", "high", or "extreme"
        existing_ema_spread_pct: Use if already available (non-None and non-zero)
        existing_atr_ratio: Use if already available (non-None and > 0)
        config: Optional configuration (uses defaults if None)
        
    Returns:
        TrendFieldsResult with derived ema_spread_pct and atr_ratio
    """
    cfg = config or ContextVectorConfig()
    
    # Derive ema_spread_pct (Requirements 4.1, 4.2, 4.3, 4.4)
    if existing_ema_spread_pct is not None and existing_ema_spread_pct != 0.0:
        ema_spread_pct = existing_ema_spread_pct
    else:
        direction = trend_direction.lower() if trend_direction else "flat"
        if direction == "up":
            ema_spread_pct = trend_strength * cfg.ema_spread_multiplier
        elif direction == "down":
            ema_spread_pct = -trend_strength * cfg.ema_spread_multiplier
        else:  # "flat", "neutral", or unknown
            ema_spread_pct = 0.0
    
    # Derive atr_ratio from vol_regime (Requirement 4.5)
    if existing_atr_ratio is not None and existing_atr_ratio > 0:
        atr_ratio = existing_atr_ratio
    else:
        regime = vol_regime.lower() if vol_regime else "normal"
        atr_ratio_map = {
            "low": cfg.atr_ratio_low,
            "normal": cfg.atr_ratio_normal,
            "high": cfg.atr_ratio_high,
            "extreme": cfg.atr_ratio_extreme,
        }
        atr_ratio = atr_ratio_map.get(regime, cfg.atr_ratio_normal)
    
    return TrendFieldsResult(
        ema_spread_pct=ema_spread_pct,
        atr_ratio=atr_ratio,
    )


# ═══════════════════════════════════════════════════════════════
# CONTEXT VECTOR INPUT (Context Vector Parity - Unified Input)
# ═══════════════════════════════════════════════════════════════

@dataclass
class ContextVectorInput:
    """Unified input for ContextVector building.
    
    Can be populated from StateManager, MarketSnapshot, or raw dict.
    All fields are optional - the builder will derive/default missing values.
    
    Requirements: 1.1, 6.1, 6.2, 6.3, 6.4, 6.5
    """
    symbol: str
    timestamp: float
    price: float
    
    # Orderbook data (optional - will be derived/defaulted if missing)
    bid: Optional[float] = None
    ask: Optional[float] = None
    spread_bps: Optional[float] = None
    bid_depth_usd: Optional[float] = None
    ask_depth_usd: Optional[float] = None
    orderbook_imbalance: Optional[float] = None
    
    # Trend data (optional - will be derived if missing)
    trend_direction: Optional[str] = None
    trend_strength: Optional[float] = None
    ema_spread_pct: Optional[float] = None
    
    # Volatility data (optional - will be derived if missing)
    vol_regime: Optional[str] = None
    atr_ratio: Optional[float] = None
    
    # Market regime (optional - will default to "range" if missing)
    market_regime: Optional[str] = None
    
    # AMT data (optional)
    poc_price: Optional[float] = None
    vah_price: Optional[float] = None
    val_price: Optional[float] = None
    position_in_value: Optional[str] = None
    
    # Cost data (optional - will be calculated if missing)
    expected_fee_bps: Optional[float] = None
    expected_cost_bps: Optional[float] = None
    
    # Data quality
    trades_per_second: Optional[float] = None
    book_age_ms: Optional[float] = None
    trade_age_ms: Optional[float] = None
    data_quality_score: Optional[float] = None
    
    # Session info (optional - will be derived from timestamp)
    session: Optional[str] = None
    hour_utc: Optional[int] = None


def _derive_regime_family(
    market_regime: str,
    trend_strength: float,
    liquidity_score: float,
    expected_cost_bps: float,
) -> str:
    """
    Derive regime_family from market_regime using RegimeMapper logic.
    
    This is a simplified version that doesn't require RouterConfig.
    For full RegimeMapper integration, use the RegimeMapper class.
    
    Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 1.9
    
    Mapping rules:
    - "range" → "mean_revert" (unless trend_strength > 0.3 → "trend")
    - "breakout" → "trend"
    - "squeeze" → "avoid" (if liquidity_score < 0.3) or "trend"
    - "chop" → "avoid" (if expected_cost_bps > 15) or "mean_revert"
    - unknown → "unknown"
    """
    regime = market_regime.lower() if market_regime else ""
    
    if regime == "range":
        # Requirement 1.2, 1.3
        if trend_strength >= 0.3:
            return "trend"
        return "mean_revert"
    
    elif regime == "breakout":
        # Requirement 1.4
        return "trend"
    
    elif regime == "squeeze":
        # Requirement 1.5, 1.6
        if liquidity_score < 0.3:
            return "avoid"
        return "trend"
    
    elif regime == "chop":
        # Requirement 1.7, 1.8
        if expected_cost_bps > 15.0:
            return "avoid"
        return "mean_revert"
    
    else:
        # Requirement 1.9
        return "unknown"


def _derive_session_from_timestamp(timestamp: float) -> Tuple[str, int]:
    """Derive session and hour_utc from timestamp."""
    dt = datetime.fromtimestamp(timestamp, tz=timezone.utc)
    hour_utc = dt.hour

    # Canonical session boundaries must match profile_classifier.classify_session
    # and feature_worker._session_label to avoid cross-stage drift.
    if 0 <= hour_utc < 7:
        session = "asia"
    elif 7 <= hour_utc < 12:
        session = "europe"
    elif 12 <= hour_utc < 22:
        session = "us"
    else:
        session = "overnight"
    
    return session, hour_utc


def build_context_vector(
    input: ContextVectorInput,
    config: Optional[ContextVectorConfig] = None,
    backtesting_mode: bool = False,
) -> "ContextVector":
    """
    Build a complete ContextVector from any data source.
    
    This is the SINGLE entry point for ContextVector construction.
    Both live and backtest code paths should call this function.
    
    Requirements:
    - 1.1-1.9: Regime family derivation via RegimeMapper logic
    - 2.1-2.5: Spread validation
    - 3.1-3.7: Cost field calculation
    - 4.1-4.5: Trend field derivation
    - 6.1-6.5: Parity verification invariants
    
    Args:
        input: ContextVectorInput with available data
        config: Optional configuration for defaults/thresholds
        backtesting_mode: If True, use backtest-appropriate defaults
        
    Returns:
        Fully populated and validated ContextVector
    """
    cfg = config or ContextVectorConfig()
    
    # ═══════════════════════════════════════════════════════════════
    # SPREAD VALIDATION (Requirement 2)
    # ═══════════════════════════════════════════════════════════════
    
    raw_spread = input.spread_bps if input.spread_bps is not None else 0.0
    spread_result = validate_spread_bps(
        spread_bps=raw_spread,
        bid=input.bid,
        ask=input.ask,
        price=input.price,
        config=cfg,
    )
    validated_spread_bps = spread_result.spread_bps
    
    # ═══════════════════════════════════════════════════════════════
    # DEPTH AND LIQUIDITY (for cost calculation)
    # ═══════════════════════════════════════════════════════════════
    
    bid_depth_usd = input.bid_depth_usd if input.bid_depth_usd is not None else 0.0
    ask_depth_usd = input.ask_depth_usd if input.ask_depth_usd is not None else 0.0
    total_depth_usd = bid_depth_usd + ask_depth_usd
    
    # Calculate liquidity score
    trades_per_second = input.trades_per_second if input.trades_per_second is not None else 1.0
    orderbook_imbalance = input.orderbook_imbalance if input.orderbook_imbalance is not None else 0.0
    
    spread_score = max(0.0, 1.0 - (validated_spread_bps / 50.0))
    depth_score = min(1.0, total_depth_usd / 100000.0)
    tps_score = min(1.0, trades_per_second / 5.0)
    balance_score = 1.0 - abs(orderbook_imbalance)
    liquidity_score = 0.35 * spread_score + 0.30 * depth_score + 0.25 * tps_score + 0.10 * balance_score
    
    # ═══════════════════════════════════════════════════════════════
    # COST FIELDS CALCULATION (Requirement 3)
    # ═══════════════════════════════════════════════════════════════
    
    cost_result = calculate_cost_fields(
        spread_bps=validated_spread_bps,
        bid_depth_usd=bid_depth_usd,
        ask_depth_usd=ask_depth_usd,
        config=cfg,
        custom_fee_bps=input.expected_fee_bps,
    )
    
    # ═══════════════════════════════════════════════════════════════
    # TREND FIELDS DERIVATION (Requirement 4)
    # ═══════════════════════════════════════════════════════════════
    
    trend_direction = input.trend_direction if input.trend_direction else "flat"
    trend_strength = input.trend_strength if input.trend_strength is not None else 0.0
    vol_regime = input.vol_regime if input.vol_regime else "normal"
    
    trend_result = derive_trend_fields(
        trend_direction=trend_direction,
        trend_strength=trend_strength,
        vol_regime=vol_regime,
        existing_ema_spread_pct=input.ema_spread_pct,
        existing_atr_ratio=input.atr_ratio,
        config=cfg,
    )
    
    # ═══════════════════════════════════════════════════════════════
    # REGIME FAMILY DERIVATION (Requirement 1)
    # ═══════════════════════════════════════════════════════════════
    
    market_regime = input.market_regime if input.market_regime else "range"
    regime_family = _derive_regime_family(
        market_regime=market_regime,
        trend_strength=trend_strength,
        liquidity_score=liquidity_score,
        expected_cost_bps=cost_result.expected_cost_bps,
    )
    
    # ═══════════════════════════════════════════════════════════════
    # SESSION DERIVATION
    # ═══════════════════════════════════════════════════════════════
    
    if input.hour_utc is not None:
        # Normalize supplied hour_utc into canonical session labels. This prevents
        # inconsistent payloads (e.g. session=europe + hour_utc=12) from causing
        # router/strategy session mismatches.
        hour_utc = int(input.hour_utc) % 24
        if 0 <= hour_utc < 7:
            session = "asia"
        elif 7 <= hour_utc < 12:
            session = "europe"
        elif 12 <= hour_utc < 22:
            session = "us"
        else:
            session = "overnight"
    else:
        session, hour_utc = _derive_session_from_timestamp(input.timestamp)
    
    # ═══════════════════════════════════════════════════════════════
    # DATA QUALITY STATE
    # ═══════════════════════════════════════════════════════════════
    
    book_age_ms = input.book_age_ms if input.book_age_ms is not None else 0.0
    trade_age_ms = input.trade_age_ms if input.trade_age_ms is not None else 0.0
    data_quality_state = _determine_data_quality_state(book_age_ms, trade_age_ms)
    data_completeness = input.data_quality_score if input.data_quality_score is not None else 1.0
    
    # ═══════════════════════════════════════════════════════════════
    # AMT FIELDS
    # ═══════════════════════════════════════════════════════════════
    
    poc_price = input.poc_price if input.poc_price else 0.0
    vah_price = input.vah_price if input.vah_price else 0.0
    val_price = input.val_price if input.val_price else 0.0
    position_in_value = input.position_in_value if input.position_in_value else "inside"
    
    # Calculate distances to AMT levels
    price = input.price
    distance_to_vah_pct = abs(price - vah_price) / price if vah_price > 0 and price > 0 else 0.0
    distance_to_val_pct = abs(price - val_price) / price if val_price > 0 and price > 0 else 0.0
    distance_to_poc_pct = abs(price - poc_price) / price if poc_price > 0 and price > 0 else 0.0
    
    # ═══════════════════════════════════════════════════════════════
    # BUILD CONTEXT VECTOR
    # ═══════════════════════════════════════════════════════════════
    
    return ContextVector(
        symbol=input.symbol,
        timestamp=input.timestamp,
        price=price,
        # Trend fields
        ema_spread_pct=trend_result.ema_spread_pct,
        trend_strength=trend_strength,
        trend_direction=trend_direction,
        atr_ratio=trend_result.atr_ratio,
        volatility_regime=vol_regime,
        # Regime fields
        market_regime=market_regime,
        regime_family=regime_family,
        # AMT fields
        value_area_high=vah_price,
        value_area_low=val_price,
        point_of_control=poc_price,
        position_in_value=position_in_value,
        distance_to_vah_pct=distance_to_vah_pct,
        distance_to_val_pct=distance_to_val_pct,
        distance_to_poc_pct=distance_to_poc_pct,
        rotation_factor=orderbook_imbalance * 5,  # Scale imbalance to rotation factor
        # Orderbook fields
        spread_bps=validated_spread_bps,
        bid_depth_usd=bid_depth_usd,
        ask_depth_usd=ask_depth_usd,
        orderbook_imbalance=orderbook_imbalance,
        # Order flow
        trades_per_second=trades_per_second,
        # Session
        session=session,
        hour_utc=hour_utc,
        # Cost fields
        expected_fee_bps=cost_result.expected_fee_bps,
        expected_cost_bps=cost_result.expected_cost_bps,
        # Data quality
        book_age_ms=book_age_ms,
        trade_age_ms=trade_age_ms,
        liquidity_score=liquidity_score,
        data_quality_state=data_quality_state,
        data_completeness=data_completeness,
    )


# ═══════════════════════════════════════════════════════════════
# SPREAD PERCENTILE TRACKER
# ═══════════════════════════════════════════════════════════════

class SpreadPercentileTracker:
    """
    Track spread history per symbol to calculate spread percentile.
    
    Maintains a rolling window of recent spread observations to determine
    where the current spread falls relative to recent history.
    """
    
    def __init__(self, window_size: int = 1000):
        """
        Initialize tracker with configurable window size.
        
        Args:
            window_size: Number of spread observations to keep per symbol
        """
        self._spreads: Dict[str, deque] = {}
        self._window_size = window_size
    
    def record_spread(self, symbol: str, spread_bps: float) -> None:
        """Record a spread observation for a symbol."""
        if symbol not in self._spreads:
            self._spreads[symbol] = deque(maxlen=self._window_size)
        self._spreads[symbol].append(spread_bps)
    
    def get_percentile(self, symbol: str, current_spread_bps: float) -> float:
        """
        Calculate what percentile the current spread is at.
        
        Returns:
            Percentile (0-100) where 0 = tightest spread, 100 = widest spread
            Returns 50.0 if insufficient history
        """
        if symbol not in self._spreads or len(self._spreads[symbol]) < 10:
            return 50.0  # Default to median if insufficient data
        
        spreads = list(self._spreads[symbol])
        count_below = sum(1 for s in spreads if s < current_spread_bps)
        return (count_below / len(spreads)) * 100.0
    
    def clear(self, symbol: Optional[str] = None) -> None:
        """Clear spread history for a symbol or all symbols."""
        if symbol:
            self._spreads.pop(symbol, None)
        else:
            self._spreads.clear()


# Global spread percentile tracker instance
_spread_tracker = SpreadPercentileTracker()


@dataclass
class ContextVector:
    """
    Complete market context for a symbol at a point in time
    
    This is the input to the profile scoring engine.
    """
    # Identity
    symbol: str
    timestamp: float
    
    # Price features
    price: float
    price_change_1s: float = 0.0
    price_change_5s: float = 0.0
    price_change_30s: float = 0.0
    price_change_5m: float = 0.0
    price_change_1m: float = 0.0
    price_change_1h: float = 0.0
    
    # Trend features (from HTF indicators)
    ema_fast_15m: float = 0.0
    ema_slow_15m: float = 0.0
    ema_spread_pct: float = 0.0  # (fast - slow) / price
    trend_strength: float = 0.0  # Absolute EMA spread
    trend_direction: str = "flat"  # 'up', 'down', 'flat'
    
    # Volatility features
    atr_5m: float = 0.0
    atr_5m_baseline: float = 0.0
    atr_ratio: float = 1.0  # atr / baseline
    volatility_regime: str = "normal"  # 'low', 'normal', 'high'
    realized_vol_1m: float = 0.0
    market_regime: str = "range"  # 'range', 'breakout', 'squeeze', 'chop'
    regime_confidence: float = 0.0
    regime_family: str = "unknown"  # 'trend', 'mean_revert', 'avoid'
    
    # AMT features
    value_area_high: float = 0.0
    value_area_low: float = 0.0
    point_of_control: float = 0.0
    rotation_factor: float = 0.0
    position_in_value: str = "inside"  # 'above', 'below', 'inside'
    distance_to_vah_pct: float = 0.0
    distance_to_val_pct: float = 0.0
    distance_to_poc_pct: float = 0.0
    
    # Orderbook features
    spread: float = 0.0
    spread_bps: float = 0.0
    bid_depth_usd: float = 0.0
    ask_depth_usd: float = 0.0
    orderbook_imbalance: float = 0.0  # (bid - ask) / (bid + ask)
    bid_pressure_bps: float = 0.0
    ask_pressure_bps: float = 0.0
    
    # Order flow features
    trades_per_second: float = 0.0
    buy_volume_1m: float = 0.0
    sell_volume_1m: float = 0.0
    volume_imbalance: float = 0.0  # (buy - sell) / (buy + sell)
    aggressive_buy_pct: float = 0.0
    aggressive_sell_pct: float = 0.0
    
    # Session features
    session: str = "us"  # 'asia', 'europe', 'us', 'overnight'
    hour_utc: int = 0
    is_market_hours: bool = True
    
    # Risk features
    daily_pnl: float = 0.0
    risk_mode: str = "normal"  # 'normal', 'protection', 'recovery', 'off'
    open_positions: int = 0
    account_equity: float = 10000.0
    
    # Funding features (if available)
    funding_rate: Optional[float] = None
    funding_extreme: bool = False
    
    # Correlation features (if available)
    correlation_to_btc: Optional[float] = None
    btc_direction: Optional[str] = None
    
    # Prediction features (if available)
    predicted_direction: Optional[str] = None
    prediction_confidence: Optional[float] = None
    predicted_move_bps: Optional[float] = None
    
    # Data quality
    data_completeness: float = 1.0  # 0.0 to 1.0
    missing_features: List[str] = field(default_factory=list)
    
    # Cost-related fields (Profile Router v2 - Requirement 5.1)
    expected_fee_bps: float = 0.0  # Expected fee from FeeModel/tier
    expected_cost_bps: float = 0.0  # Total: spread + fees + slippage + adverse selection
    spread_percentile: float = 50.0  # Per symbol/venue, 0-100
    maker_fill_prob: float = 0.5  # Maker-first viability proxy, 0-1
    book_age_ms: float = 0.0  # Age of orderbook data in milliseconds
    trade_age_ms: float = 0.0  # Age of last trade data in milliseconds
    liquidity_score: float = 0.5  # Normalized 0-1 from depth + tps
    data_quality_state: str = "good"  # "good", "degraded", "stale"
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for ML models"""
        return {
            'symbol': self.symbol,
            'timestamp': self.timestamp,
            'price': self.price,
            'price_change_1s': self.price_change_1s,
            'price_change_5s': self.price_change_5s,
            'price_change_30s': self.price_change_30s,
            'price_change_5m': self.price_change_5m,
            'price_change_1m': self.price_change_1m,
            'price_change_1h': self.price_change_1h,
            'ema_spread_pct': self.ema_spread_pct,
            'trend_strength': self.trend_strength,
            'atr_ratio': self.atr_ratio,
            'market_regime': self.market_regime,
            'rotation_factor': self.rotation_factor,
            'regime_confidence': self.regime_confidence,
            'regime_family': self.regime_family,
            'distance_to_vah_pct': self.distance_to_vah_pct,
            'distance_to_val_pct': self.distance_to_val_pct,
            'distance_to_poc_pct': self.distance_to_poc_pct,
            'spread_bps': self.spread_bps,
            'orderbook_imbalance': self.orderbook_imbalance,
            'trades_per_second': self.trades_per_second,
            'volume_imbalance': self.volume_imbalance,
            'data_completeness': self.data_completeness,
            # Cost-related fields (v2)
            'expected_fee_bps': self.expected_fee_bps,
            'expected_cost_bps': self.expected_cost_bps,
            'spread_percentile': self.spread_percentile,
            'maker_fill_prob': self.maker_fill_prob,
            'book_age_ms': self.book_age_ms,
            'trade_age_ms': self.trade_age_ms,
            'liquidity_score': self.liquidity_score,
            'data_quality_state': self.data_quality_state,
        }
    
    def get_feature_vector(self) -> List[float]:
        """Get numerical feature vector for ML models"""
        return [
            self.price_change_1s,
            self.price_change_5s,
            self.price_change_30s,
            self.price_change_5m,
            self.price_change_1m,
            self.price_change_1h,
            self.ema_spread_pct,
            self.trend_strength,
            self.atr_ratio,
            self.rotation_factor,
            self.regime_confidence,
            self.distance_to_vah_pct,
            self.distance_to_val_pct,
            self.distance_to_poc_pct,
            self.spread_bps,
            self.orderbook_imbalance,
            self.bid_pressure_bps,
            self.ask_pressure_bps,
            self.trades_per_second,
            self.volume_imbalance,
        ]


def build_context_vector_from_state(state, symbol: str) -> Optional[ContextVector]:
    """
    Build context vector from StateManager
    
    This is a bridge function that converts the current StateManager
    data structures into the new ContextVector format.
    
    Profile Router v2 Enhancement (Requirement 5.1):
    - Populates expected_fee_bps from FeeModel
    - Calculates expected_cost_bps (spread + fees + slippage + adverse selection)
    - Calculates spread_percentile (per symbol/venue)
    - Calculates liquidity_score (normalized from depth + tps)
    - Sets data_quality_state based on ages
    """
    try:
        # Get orderbook
        orderbook = state.get_orderbook(symbol)
        if not orderbook or not orderbook.bids or not orderbook.asks:
            return None
        
        # Get AMT metrics
        amt = state.get_amt_metrics(symbol)
        if not amt:
            return None
        
        # Get HTF indicators
        htf = state.get_htf_indicators(symbol)
        if not htf:
            return None
        
        # Calculate mid price
        mid_price = (orderbook.bids[0][0] + orderbook.asks[0][0]) / 2.0
        
        # Calculate spread
        spread = (orderbook.asks[0][0] - orderbook.bids[0][0]) / mid_price
        spread_bps = spread * 10000
        
        # ═══════════════════════════════════════════════════════════════
        # ORDERBOOK DEPTH CALCULATION
        # ═══════════════════════════════════════════════════════════════
        
        # Calculate bid/ask depth in USD
        bid_depth_usd = 0.0
        ask_depth_usd = 0.0
        
        # Sum up depth from orderbook levels (price, size)
        for price, size in orderbook.bids[:10]:  # Top 10 levels
            bid_depth_usd += price * size
        
        for price, size in orderbook.asks[:10]:  # Top 10 levels
            ask_depth_usd += price * size
        
        total_depth_usd = bid_depth_usd + ask_depth_usd
        
        # Calculate orderbook imbalance
        orderbook_imbalance = 0.0
        if total_depth_usd > 0:
            orderbook_imbalance = (bid_depth_usd - ask_depth_usd) / total_depth_usd
        
        # ═══════════════════════════════════════════════════════════════
        # TRADES PER SECOND CALCULATION
        # ═══════════════════════════════════════════════════════════════
        
        recent_trades = state.get_recent_trades(symbol, count=10)
        trades_per_second = 0.0
        trade_age_ms = 0.0
        
        if len(recent_trades) >= 2:
            def _trade_timestamp(trade):
                if isinstance(trade, dict):
                    return trade.get('timestamp', 0)
                if isinstance(trade, (list, tuple)):
                    if len(trade) >= 4:
                        return trade[3]
                    if len(trade) >= 3:
                        return trade[2]
                return 0
            
            start_ts = _trade_timestamp(recent_trades[0])
            end_ts = _trade_timestamp(recent_trades[-1])
            time_window = end_ts - start_ts
            if time_window > 0:
                trades_per_second = len(recent_trades) / time_window
            
            # Calculate trade age (time since last trade)
            last_trade_ts = _trade_timestamp(recent_trades[-1])
            if last_trade_ts > 0:
                trade_age_ms = (time.time() - last_trade_ts) * 1000.0
        
        # ═══════════════════════════════════════════════════════════════
        # BOOK AGE CALCULATION
        # ═══════════════════════════════════════════════════════════════
        
        book_age_ms = 0.0
        # Try to get orderbook timestamp from state if available
        if hasattr(state, 'orderbook_timestamps') and symbol in state.orderbook_timestamps:
            book_ts = state.orderbook_timestamps[symbol]
            book_age_ms = (time.time() - book_ts) * 1000.0
        elif hasattr(orderbook, 'timestamp') and orderbook.timestamp:
            book_age_ms = (time.time() - orderbook.timestamp) * 1000.0
        
        # ═══════════════════════════════════════════════════════════════
        # FEE MODEL INTEGRATION (Requirement 5.1)
        # ═══════════════════════════════════════════════════════════════
        
        # Get expected fee from FeeModel
        expected_fee_bps = 6.0  # Default: 6 bps (OKX regular taker fee)
        
        # Try to get fee model from state
        fee_model = None
        if hasattr(state, 'default_fee_model') and state.default_fee_model:
            fee_model = state.default_fee_model
        elif hasattr(state, 'fee_model') and state.fee_model:
            fee_model = state.fee_model
        
        if fee_model:
            # Get taker fee rate in bps (round-trip: entry + exit)
            if hasattr(fee_model, 'config'):
                # FeeModel from quantgambit.risk.fee_model
                taker_rate = getattr(fee_model.config, 'taker_fee_rate', 0.0006)
                expected_fee_bps = taker_rate * 10000.0 * 2  # Round-trip
            elif hasattr(fee_model, 'taker_fee_bps'):
                # Legacy fee model
                expected_fee_bps = fee_model.taker_fee_bps * 2  # Round-trip
        
        # ═══════════════════════════════════════════════════════════════
        # EXPECTED COST CALCULATION (Requirement 5.1)
        # ═══════════════════════════════════════════════════════════════
        
        # Expected cost = spread + fees + slippage estimate + adverse selection estimate
        # Slippage estimate: ~1 bps for liquid markets, more for illiquid
        slippage_estimate_bps = _estimate_slippage_bps(total_depth_usd, trades_per_second)
        
        # Adverse selection estimate: ~1-2 bps for scalping
        adverse_selection_bps = _estimate_adverse_selection_bps(trades_per_second, orderbook_imbalance)
        
        expected_cost_bps = spread_bps + expected_fee_bps + slippage_estimate_bps + adverse_selection_bps
        
        # ═══════════════════════════════════════════════════════════════
        # SPREAD PERCENTILE CALCULATION (Requirement 5.1)
        # ═══════════════════════════════════════════════════════════════
        
        # Record current spread and get percentile
        _spread_tracker.record_spread(symbol, spread_bps)
        spread_percentile = _spread_tracker.get_percentile(symbol, spread_bps)
        
        # ═══════════════════════════════════════════════════════════════
        # MAKER FILL PROBABILITY (Requirement 5.1)
        # ═══════════════════════════════════════════════════════════════
        
        # Estimate maker fill probability based on market activity
        maker_fill_prob = _estimate_maker_fill_probability(
            trades_per_second, spread_bps, orderbook_imbalance
        )
        
        # ═══════════════════════════════════════════════════════════════
        # LIQUIDITY SCORE CALCULATION (Requirement 5.1)
        # ═══════════════════════════════════════════════════════════════
        
        liquidity_score = _calculate_liquidity_score(
            spread_bps=spread_bps,
            total_depth_usd=total_depth_usd,
            trades_per_second=trades_per_second,
            orderbook_imbalance=orderbook_imbalance
        )
        
        # ═══════════════════════════════════════════════════════════════
        # DATA QUALITY STATE (Requirement 5.1)
        # ═══════════════════════════════════════════════════════════════
        
        data_quality_state = _determine_data_quality_state(
            book_age_ms=book_age_ms,
            trade_age_ms=trade_age_ms
        )
        
        # ═══════════════════════════════════════════════════════════════
        # TREND AND VOLATILITY CALCULATIONS
        # ═══════════════════════════════════════════════════════════════
        
        # Calculate EMA spread
        ema_spread_pct = 0.0
        if htf.get('ema_slow_15m', 0) > 0:
            ema_spread_pct = (htf['ema_fast_15m'] - htf['ema_slow_15m']) / mid_price
        
        # Determine trend direction
        trend_direction = "flat"
        if ema_spread_pct > 0.001:
            trend_direction = "up"
        elif ema_spread_pct < -0.001:
            trend_direction = "down"
        
        # Calculate ATR ratio
        atr_ratio = 1.0
        if htf.get('atr_5m_baseline', 0) > 0:
            atr_ratio = htf['atr_5m'] / htf['atr_5m_baseline']
        
        # Determine volatility regime
        volatility_regime = "normal"
        if atr_ratio < 0.7:
            volatility_regime = "low"
        elif atr_ratio > 1.3:
            volatility_regime = "high"
        
        # Calculate distances to AMT levels
        distance_to_vah_pct = abs(mid_price - amt.value_area_high) / mid_price
        distance_to_val_pct = abs(mid_price - amt.value_area_low) / mid_price
        distance_to_poc_pct = abs(mid_price - amt.point_of_control) / mid_price
        
        # Get session
        from quantgambit.deeptrader_core.profiles.profile_classifier import classify_session
        session = classify_session(time.time())
        hour_utc = datetime.now(timezone.utc).hour
        logger.debug(f"[{symbol}] Session classified: {session} (hour_utc={hour_utc})")
        
        # Build context vector
        context = ContextVector(
            symbol=symbol,
            timestamp=time.time(),
            price=mid_price,
            ema_fast_15m=htf.get('ema_fast_15m', 0),
            ema_slow_15m=htf.get('ema_slow_15m', 0),
            ema_spread_pct=ema_spread_pct,
            trend_strength=abs(ema_spread_pct),
            trend_direction=trend_direction,
            atr_5m=htf.get('atr_5m', 0),
            atr_5m_baseline=htf.get('atr_5m_baseline', 0),
            atr_ratio=atr_ratio,
            volatility_regime=volatility_regime,
            value_area_high=amt.value_area_high,
            value_area_low=amt.value_area_low,
            point_of_control=amt.point_of_control,
            rotation_factor=amt.rotation_factor,
            position_in_value=amt.position_in_value,
            distance_to_vah_pct=distance_to_vah_pct,
            distance_to_val_pct=distance_to_val_pct,
            distance_to_poc_pct=distance_to_poc_pct,
            spread=spread,
            spread_bps=spread_bps,
            bid_depth_usd=bid_depth_usd,
            ask_depth_usd=ask_depth_usd,
            orderbook_imbalance=orderbook_imbalance,
            trades_per_second=trades_per_second,
            session=session,
            hour_utc=hour_utc,
            daily_pnl=state.risk_state.daily_pnl,
            open_positions=state.risk_state.position_count,
            account_equity=state.risk_state.account_balance,
            # Profile Router v2 cost-related fields (Requirement 5.1)
            expected_fee_bps=expected_fee_bps,
            expected_cost_bps=expected_cost_bps,
            spread_percentile=spread_percentile,
            maker_fill_prob=maker_fill_prob,
            book_age_ms=book_age_ms,
            trade_age_ms=trade_age_ms,
            liquidity_score=liquidity_score,
            data_quality_state=data_quality_state,
        )
        
        return context
        
    except Exception as e:
        print(f"⚠️ Failed to build context vector for {symbol}: {e}")
        return None


# ═══════════════════════════════════════════════════════════════
# HELPER FUNCTIONS FOR COST CALCULATIONS
# ═══════════════════════════════════════════════════════════════

def _estimate_slippage_bps(total_depth_usd: float, trades_per_second: float) -> float:
    """
    Estimate expected slippage in basis points.
    
    Slippage increases with:
    - Lower depth (less liquidity to absorb orders)
    - Lower trading activity (wider effective spreads)
    
    Returns:
        Estimated slippage in basis points (0.5 - 5.0 typical range)
    """
    # Base slippage for liquid markets
    base_slippage = 0.5
    
    # Depth factor: less depth = more slippage
    # Reference: $100k depth = minimal slippage, $10k = moderate, <$5k = high
    if total_depth_usd < 5000:
        depth_factor = 3.0
    elif total_depth_usd < 10000:
        depth_factor = 2.0
    elif total_depth_usd < 50000:
        depth_factor = 1.5
    elif total_depth_usd < 100000:
        depth_factor = 1.2
    else:
        depth_factor = 1.0
    
    # Activity factor: less activity = more slippage
    # Reference: 5 tps = active, 1 tps = moderate, <0.5 tps = slow
    if trades_per_second < 0.1:
        activity_factor = 2.0
    elif trades_per_second < 0.5:
        activity_factor = 1.5
    elif trades_per_second < 1.0:
        activity_factor = 1.2
    else:
        activity_factor = 1.0
    
    return base_slippage * depth_factor * activity_factor


def _estimate_adverse_selection_bps(trades_per_second: float, orderbook_imbalance: float) -> float:
    """
    Estimate adverse selection cost in basis points.
    
    Adverse selection is the cost of trading against informed traders.
    Higher in:
    - Fast-moving markets (high TPS with directional flow)
    - Imbalanced orderbooks (one side being depleted)
    
    Returns:
        Estimated adverse selection cost in basis points (0.5 - 3.0 typical range)
    """
    # Base adverse selection for scalping
    base_adverse = 0.5
    
    # Imbalance factor: strong imbalance suggests directional pressure
    imbalance_abs = abs(orderbook_imbalance)
    if imbalance_abs > 0.6:
        imbalance_factor = 2.0
    elif imbalance_abs > 0.4:
        imbalance_factor = 1.5
    elif imbalance_abs > 0.2:
        imbalance_factor = 1.2
    else:
        imbalance_factor = 1.0
    
    # Activity factor: high activity with imbalance = more adverse selection
    if trades_per_second > 5.0 and imbalance_abs > 0.3:
        activity_factor = 1.5
    else:
        activity_factor = 1.0
    
    return base_adverse * imbalance_factor * activity_factor


def _estimate_maker_fill_probability(
    trades_per_second: float,
    spread_bps: float,
    orderbook_imbalance: float
) -> float:
    """
    Estimate probability of maker order fill.
    
    Higher fill probability when:
    - Higher trading activity (more order flow)
    - Tighter spreads (more competitive)
    - Balanced orderbook (both sides active)
    
    Returns:
        Estimated fill probability (0.0 - 1.0)
    """
    # Base probability
    base_prob = 0.5
    
    # Activity bonus: more trades = higher fill probability
    if trades_per_second > 5.0:
        activity_bonus = 0.3
    elif trades_per_second > 2.0:
        activity_bonus = 0.2
    elif trades_per_second > 1.0:
        activity_bonus = 0.1
    elif trades_per_second > 0.5:
        activity_bonus = 0.05
    else:
        activity_bonus = 0.0
    
    # Spread penalty: wider spread = lower fill probability
    if spread_bps > 20:
        spread_penalty = 0.2
    elif spread_bps > 10:
        spread_penalty = 0.1
    elif spread_bps > 5:
        spread_penalty = 0.05
    else:
        spread_penalty = 0.0
    
    # Imbalance penalty: strong imbalance = harder to fill on one side
    imbalance_penalty = abs(orderbook_imbalance) * 0.2
    
    prob = base_prob + activity_bonus - spread_penalty - imbalance_penalty
    return max(0.1, min(0.95, prob))


def _calculate_liquidity_score(
    spread_bps: float,
    total_depth_usd: float,
    trades_per_second: float,
    orderbook_imbalance: float
) -> float:
    """
    Calculate normalized liquidity score (0-1).
    
    Combines multiple factors:
    - Spread (lower = better)
    - Depth (higher = better)
    - Trading activity (higher = better)
    - Balance (more balanced = better)
    
    Returns:
        Liquidity score (0.0 - 1.0)
    """
    # Spread component (lower spread = higher score)
    # Reference: <5 bps = excellent, 5-10 = good, 10-20 = moderate, >20 = poor
    spread_score = max(0.0, 1.0 - (spread_bps / 50.0))
    
    # Depth component (higher depth = higher score)
    # Reference: $100k+ = excellent, $50k = good, $10k = moderate
    depth_score = min(1.0, total_depth_usd / 100000.0)
    
    # TPS component (higher activity = higher score)
    # Reference: 5+ tps = excellent, 2 = good, 0.5 = moderate
    tps_score = min(1.0, trades_per_second / 5.0)
    
    # Balance component (more balanced = higher score)
    balance_score = 1.0 - abs(orderbook_imbalance)
    
    # Weighted average (spread and depth most important)
    weights = [0.35, 0.30, 0.25, 0.10]
    scores = [spread_score, depth_score, tps_score, balance_score]
    
    liquidity_score = sum(w * s for w, s in zip(weights, scores))
    return max(0.0, min(1.0, liquidity_score))


def _determine_data_quality_state(book_age_ms: float, trade_age_ms: float) -> str:
    """
    Determine data quality state based on data ages.
    
    States:
    - "good": Both orderbook and trade data are fresh
    - "degraded": One data source is getting stale
    - "stale": Data is too old to be reliable
    
    Thresholds (from RouterConfig defaults):
    - max_book_age_ms: 5000 (5 seconds)
    - max_trade_age_ms: 10000 (10 seconds)
    
    Returns:
        Data quality state: "good", "degraded", or "stale"
    """
    # Thresholds for data freshness
    BOOK_DEGRADED_MS = 2000.0   # 2 seconds
    BOOK_STALE_MS = 5000.0      # 5 seconds
    TRADE_DEGRADED_MS = 5000.0  # 5 seconds
    TRADE_STALE_MS = 10000.0    # 10 seconds
    
    # Check for stale data (either source)
    if book_age_ms > BOOK_STALE_MS or trade_age_ms > TRADE_STALE_MS:
        return "stale"
    
    # Check for degraded data (either source)
    if book_age_ms > BOOK_DEGRADED_MS or trade_age_ms > TRADE_DEGRADED_MS:
        return "degraded"
    
    return "good"
