"""
AMTCalculatorStage - Calculate Auction Market Theory metrics from candle data.

This stage calculates volume profile metrics (POC, VAH, VAL) from candle data
and makes them available to downstream stages. It runs before SnapshotBuilderStage
to ensure AMT fields are available when building the MarketSnapshot.

AMT (Auction Market Theory) provides:
- POC (Point of Control): Price level with highest traded volume
- VAH (Value Area High): Upper boundary of value area (68% of volume)
- VAL (Value Area Low): Lower boundary of value area (68% of volume)
- Position in Value: Classification of current price relative to value area
- Distance metrics: Distance from current price to AMT levels (in bps using canonical formula)
- Rotation Factor: Measure of price rotation/reversal strength
- VA Width: Value area width in bps

BPS Standardization (Strategy Signal Architecture Fixes):
- All distances are expressed in basis points (bps)
- Uses canonical formula: (price - reference) / mid_price * 10000
- mid_price is used as denominator (NOT reference price)
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING

from quantgambit.signals.pipeline import Stage, StageContext, StageResult
from quantgambit.observability.logger import log_info, log_warning
from quantgambit.core.volume_profile import (
    calculate_volume_profile_from_candles,
    VolumeProfileConfig,
    VolumeProfileResult,
)
from quantgambit.core.unit_converter import (
    price_distance_to_bps,
    price_distance_abs_bps,
    calculate_va_width_bps,
)

if TYPE_CHECKING:
    from collections import deque


# Track whether deprecation warning has been logged (once per session)
_ROTATION_FACTOR_DEPRECATION_LOGGED = False


@dataclass
class FlowRotationConfig:
    """
    Configuration for flow_rotation calculation with EWMA smoothing.
    
    This configuration controls how the flow_rotation signal is calculated
    from orderflow imbalance data. The signal is smoothed using EWMA
    (Exponentially Weighted Moving Average) and clipped to a configurable range.
    
    Strategy Signal Architecture Fixes - Requirement 3:
    - Split rotation factor into flow_rotation (pure orderflow) and trend_bias (HTF trend)
    - EWMA smoothing for noise reduction
    - Configurable clipping to prevent extreme values
    
    Attributes:
        ewma_span: EWMA span for smoothing (default: 10 ticks).
            Higher values provide more smoothing but slower response.
        clip_min: Minimum clipped value (default: -5.0).
            Values below this are clamped to clip_min.
        clip_max: Maximum clipped value (default: +5.0).
            Values above this are clamped to clip_max.
        scale_factor: Multiplier for raw orderflow imbalance (default: 5.0).
            Scales the orderflow imbalance before EWMA smoothing.
    """
    ewma_span: int = 10
    clip_min: float = -5.0
    clip_max: float = +5.0
    scale_factor: float = 5.0
    
    @classmethod
    def from_env(cls) -> "FlowRotationConfig":
        """
        Create configuration from environment variables.
        
        Environment variables:
            FLOW_ROTATION_EWMA_SPAN: EWMA span for smoothing (default: 10)
            FLOW_ROTATION_CLIP_MIN: Minimum clipped value (default: -5.0)
            FLOW_ROTATION_CLIP_MAX: Maximum clipped value (default: 5.0)
            FLOW_ROTATION_SCALE_FACTOR: Scale factor for orderflow (default: 5.0)
        
        Returns:
            FlowRotationConfig instance with values from environment or defaults
        """
        return cls(
            ewma_span=int(os.environ.get("FLOW_ROTATION_EWMA_SPAN", "10")),
            clip_min=float(os.environ.get("FLOW_ROTATION_CLIP_MIN", "-5.0")),
            clip_max=float(os.environ.get("FLOW_ROTATION_CLIP_MAX", "5.0")),
            scale_factor=float(os.environ.get("FLOW_ROTATION_SCALE_FACTOR", "5.0")),
        )


class FlowRotationCalculator:
    """
    Calculates flow_rotation with EWMA smoothing.
    
    This calculator computes a pure orderflow imbalance signal (flow_rotation)
    that is separate from trend information. The signal is smoothed using EWMA
    to reduce noise while maintaining responsiveness to orderflow changes.
    
    Strategy Signal Architecture Fixes - Requirement 3:
    - Pure orderflow signal without trend mixing
    - EWMA smoothing with configurable span
    - Clipping to prevent extreme values
    - Returns both smoothed and raw values for analysis
    
    The EWMA formula is:
        ewma_t = alpha * raw_t + (1 - alpha) * ewma_{t-1}
    where alpha = 2 / (span + 1)
    
    Attributes:
        config: FlowRotationConfig with calculation parameters
        _ewma_state: Dictionary mapping symbol to current EWMA value
        _alpha: EWMA smoothing factor calculated from span
    """
    
    def __init__(self, config: Optional[FlowRotationConfig] = None):
        """
        Initialize the flow rotation calculator.
        
        Args:
            config: Configuration for flow rotation calculation.
                If None, uses default FlowRotationConfig.
        """
        self.config = config or FlowRotationConfig()
        self._ewma_state: Dict[str, float] = {}
        self._alpha = 2.0 / (self.config.ewma_span + 1)
    
    def calculate(
        self,
        symbol: str,
        orderflow_imbalance: float,
    ) -> Tuple[float, float]:
        """
        Calculate flow_rotation with EWMA smoothing.
        
        This method computes the flow_rotation signal from orderflow imbalance:
        1. Scale the raw orderflow imbalance by scale_factor
        2. Apply EWMA smoothing (initializes on first call per symbol)
        3. Clip the smoothed value to [clip_min, clip_max]
        
        Args:
            symbol: Trading symbol (e.g., "BTCUSDT")
            orderflow_imbalance: Raw orderflow imbalance value, typically in [-1, 1].
                Positive values indicate buying pressure, negative values indicate
                selling pressure.
        
        Returns:
            Tuple of (flow_rotation_smoothed, flow_rotation_raw):
                - flow_rotation_smoothed: EWMA smoothed and clipped value
                - flow_rotation_raw: Pre-EWMA raw value (scaled but not smoothed)
        
        Requirements: 3.1, 3.2, 3.3
        """
        # Raw value (pre-EWMA) - scale the orderflow imbalance
        raw = orderflow_imbalance * self.config.scale_factor
        
        # EWMA smoothing
        if symbol not in self._ewma_state:
            # Initialize EWMA state with first raw value
            self._ewma_state[symbol] = raw
        else:
            # Apply EWMA formula: ewma_t = alpha * raw_t + (1 - alpha) * ewma_{t-1}
            self._ewma_state[symbol] = (
                self._alpha * raw + 
                (1 - self._alpha) * self._ewma_state[symbol]
            )
        
        smoothed = self._ewma_state[symbol]
        
        # Clip to range [clip_min, clip_max]
        smoothed = max(self.config.clip_min, min(self.config.clip_max, smoothed))
        
        return smoothed, raw
    
    def reset(self, symbol: Optional[str] = None) -> None:
        """
        Reset EWMA state.
        
        Args:
            symbol: If specified, only reset state for this symbol.
                If None, reset all state.
        """
        if symbol is not None:
            if symbol in self._ewma_state:
                del self._ewma_state[symbol]
        else:
            self._ewma_state.clear()
    
    def get_ewma_state(self, symbol: str) -> Optional[float]:
        """
        Get current EWMA state for a symbol.
        
        Args:
            symbol: Trading symbol
            
        Returns:
            Current EWMA value, or None if no state exists for symbol.
        """
        return self._ewma_state.get(symbol)


def _calculate_trend_bias(
    trend_direction: Optional[str],
    trend_strength: float,
) -> float:
    """
    Calculate trend bias from HTF trend indicators.
    
    This function computes a signed trend bias value that represents
    the higher timeframe trend direction and strength. It is separate
    from flow_rotation to allow strategies to use these signals independently.
    
    Strategy Signal Architecture Fixes - Requirement 3.4:
    - Separate trend signal from orderflow
    - Returns signed value: positive for uptrend, negative for downtrend
    - Range: approximately [-1, +1]
    
    Args:
        trend_direction: Current trend direction - "up", "down", or None/other.
            When "up", returns positive trend_strength.
            When "down", returns negative trend_strength.
            When None or other value, returns 0.0.
        trend_strength: Strength of the current trend, typically in range [0, 1].
            Higher values indicate stronger trends.
    
    Returns:
        Signed trend bias value:
            - Positive when trend is up (magnitude = trend_strength)
            - Negative when trend is down (magnitude = trend_strength)
            - Zero when trend is neutral or unknown
    
    Requirements: 3.4
    """
    if trend_direction == "up":
        return trend_strength
    elif trend_direction == "down":
        return -trend_strength
    return 0.0


@dataclass(frozen=True)
class AMTLevels:
    """
    Calculated AMT levels from volume profile.
    
    This is a frozen (immutable) dataclass that holds all AMT metrics
    calculated from candle data. Once created, the values cannot be modified.
    
    BPS Standardization (Strategy Signal Architecture Fixes Requirement 1.3):
    - distance_to_poc_bps: Signed distance in bps using canonical formula
    - distance_to_vah_bps: Absolute distance in bps
    - distance_to_val_bps: Absolute distance in bps
    - va_width_bps: Value area width in bps
    
    Canonical Formula: (price - reference) / mid_price * 10000
    
    Attributes:
        point_of_control: Price level with highest traded volume (POC)
        value_area_high: Upper boundary of value area containing 68% of volume (VAH)
        value_area_low: Lower boundary of value area containing 68% of volume (VAL)
        position_in_value: Classification of current price - "above", "below", or "inside"
        distance_to_poc: Signed distance from price to POC (LEGACY - use distance_to_poc_bps)
        distance_to_vah: Absolute distance from price to VAH (LEGACY - use distance_to_vah_bps)
        distance_to_val: Absolute distance from price to VAL (LEGACY - use distance_to_val_bps)
        distance_to_poc_bps: Signed distance in bps (positive when price > POC)
        distance_to_vah_bps: Absolute distance in bps
        distance_to_val_bps: Absolute distance in bps
        va_width_bps: Value area width in bps: (VAH - VAL) / mid_price * 10000
        flow_rotation: EWMA smoothed orderflow signal (Requirement 3.1, 3.2)
        flow_rotation_raw: Pre-EWMA raw orderflow signal (Requirement 3.8)
        trend_bias: HTF trend signal, signed [-1, +1] (Requirement 3.4)
        rotation_factor: DEPRECATED - Legacy combined signal (Requirement 3.9)
        candle_count: Number of candles used in the calculation
        calculation_ts: Unix timestamp when calculation was performed
    """
    point_of_control: float
    value_area_high: float
    value_area_low: float
    position_in_value: str
    # Legacy distance fields (for backward compatibility)
    distance_to_poc: float
    distance_to_vah: float
    distance_to_val: float
    # BPS distance fields (Requirement 1.3)
    distance_to_poc_bps: float = 0.0
    distance_to_vah_bps: float = 0.0
    distance_to_val_bps: float = 0.0
    va_width_bps: float = 0.0
    # Split rotation signals (Requirement 3)
    flow_rotation: float = 0.0       # EWMA smoothed orderflow signal
    flow_rotation_raw: float = 0.0   # Pre-EWMA raw value
    trend_bias: float = 0.0          # HTF trend signal
    # Legacy rotation (deprecated - Requirement 3.9)
    rotation_factor: float = 0.0     # DEPRECATED: Use flow_rotation and trend_bias
    # Metadata
    candle_count: int = 0
    calculation_ts: float = 0.0


@dataclass
class AMTCalculatorConfig:
    """
    Configuration for AMT calculation.
    
    This configuration controls how the volume profile is calculated
    and how AMT levels are derived from candle data.
    
    Attributes:
        lookback_candles: Number of candles to use for volume profile calculation.
            Default is 100 candles. More candles provide smoother profiles but
            may be less responsive to recent market structure changes.
        value_area_pct: Percentage of total volume that defines the value area.
            Default is 68.0% (one standard deviation in normal distribution).
            Higher values create wider value areas.
        bin_count: Number of price bins for volume profile resolution.
            Default is 20 bins. More bins provide finer resolution but may
            create noisier profiles with sparse data.
        min_candles: Minimum number of candles required for calculation.
            Default is 10 candles. If fewer candles are available, the
            calculator returns None for all AMT fields.
        candle_timeframe_sec: Expected candle timeframe in seconds.
            Default is 300 (5-minute candles). Used for validation and
            lookback time calculations.
    """
    lookback_candles: int = 100
    value_area_pct: float = 68.0
    bin_count: int = 20
    min_candles: int = 10
    candle_timeframe_sec: int = 300
    
    @classmethod
    def from_env(cls) -> "AMTCalculatorConfig":
        """
        Create configuration from environment variables.
        
        Environment variables:
            AMT_LOOKBACK_CANDLES: Number of candles for volume profile (default: 100)
            AMT_VALUE_AREA_PCT: Value area percentage (default: 68.0)
            AMT_BIN_COUNT: Number of price bins (default: 20)
            AMT_MIN_CANDLES: Minimum candles required (default: 10)
            AMT_CANDLE_TIMEFRAME_SEC: Candle timeframe in seconds (default: 300)
        
        Returns:
            AMTCalculatorConfig instance with values from environment or defaults
        """
        return cls(
            lookback_candles=int(os.environ.get("AMT_LOOKBACK_CANDLES", "100")),
            value_area_pct=float(os.environ.get("AMT_VALUE_AREA_PCT", "68.0")),
            bin_count=int(os.environ.get("AMT_BIN_COUNT", "20")),
            min_candles=int(os.environ.get("AMT_MIN_CANDLES", "10")),
            candle_timeframe_sec=int(os.environ.get("AMT_CANDLE_TIMEFRAME_SEC", "300")),
        )


def _calculate_volume_profile(
    candles: List[Dict[str, Any]],
    config: AMTCalculatorConfig,
) -> Dict[str, float]:
    """
    Calculate volume profile from candle data.
    
    This function is a wrapper around the shared volume profile calculation
    in quantgambit.core.volume_profile to ensure algorithm consistency
    between live and backtest systems.
    
    Algorithm:
    1. Calculate price range: min_price, max_price from all candles
    2. Create N bins of equal size: bin_size = (max - min) / N
    3. For each candle:
       - Calculate representative price: (O + H + L + C) / 4
       - Find bin index: floor((price - min) / bin_size)
       - Add volume to bin
    4. Find POC: bin with maximum volume
    5. Calculate value area:
       - Start from POC bin
       - Expand outward until configured percentage of total volume is captured
       - VAL = lower bound of expanded region
       - VAH = upper bound of expanded region
    
    Args:
        candles: List of candle dictionaries with keys:
            - open: Opening price
            - high: High price
            - low: Low price
            - close: Closing price
            - volume: Traded volume
        config: AMTCalculatorConfig with bin_count and value_area_pct settings
    
    Returns:
        Dictionary with keys:
            - point_of_control: Price level with highest volume (POC)
            - value_area_low: Lower boundary of value area (VAL)
            - value_area_high: Upper boundary of value area (VAH)
        Returns empty dict if insufficient data or invalid input.
    
    Requirements: 1.1, 1.2, 1.3, 8.2
    """
    # Validate input - return empty dict if insufficient data
    if not candles or len(candles) < config.min_candles:
        return {}
    
    # Create shared config from AMTCalculatorConfig
    shared_config = VolumeProfileConfig(
        bin_count=config.bin_count,
        value_area_pct=config.value_area_pct,
        min_data_points=config.min_candles,
    )
    
    # Use the shared volume profile calculation
    result = calculate_volume_profile_from_candles(candles, shared_config)
    
    # Convert result to dict format (for backward compatibility)
    if result is None:
        return {}
    
    return result.to_dict()


def _classify_position(
    price: float,
    value_area_high: Optional[float],
    value_area_low: Optional[float],
) -> str:
    """
    Classify current price position relative to value area.
    
    This function determines whether the current price is above, below,
    or inside the value area defined by VAH and VAL boundaries.
    
    Args:
        price: Current market price
        value_area_high: Upper boundary of value area (VAH)
        value_area_low: Lower boundary of value area (VAL)
    
    Returns:
        "above" if price > VAH
        "below" if price < VAL
        "inside" if VAL <= price <= VAH
        "inside" if VAH or VAL is None (default)
    
    Requirements: 2.1, 2.2, 2.3, 2.4
    """
    # Default to "inside" when VAH or VAL is not available (Requirement 2.4)
    if value_area_high is None or value_area_low is None:
        return "inside"
    
    # Classify based on price position relative to value area
    if price > value_area_high:
        # Price is above VAH (Requirement 2.1)
        return "above"
    elif price < value_area_low:
        # Price is below VAL (Requirement 2.2)
        return "below"
    else:
        # Price is between VAL and VAH inclusive (Requirement 2.3)
        return "inside"


def _calculate_distances(
    price: float,
    point_of_control: Optional[float],
    value_area_high: Optional[float],
    value_area_low: Optional[float],
    mid_price: Optional[float] = None,
) -> Dict[str, float]:
    """
    Calculate distances from current price to AMT levels.
    
    This function calculates the distance from the current market price
    to each of the AMT levels (POC, VAH, VAL). These distances are used
    by trading strategies to evaluate entry proximity to value area boundaries.
    
    BPS Standardization (Strategy Signal Architecture Fixes Requirement 1.3):
    - Uses canonical formula: (price - reference) / mid_price * 10000
    - mid_price is used as denominator (NOT reference price)
    - Returns both legacy absolute distances and new bps distances
    
    Args:
        price: Current market price
        point_of_control: POC price level (price with highest volume)
        value_area_high: VAH price level (upper boundary of value area)
        value_area_low: VAL price level (lower boundary of value area)
        mid_price: Mid price for bps calculation (best_bid + best_ask) / 2.
                   If None, uses price as fallback for bps calculation.
    
    Returns:
        Dictionary with:
            - distance_to_val: Absolute distance from price to VAL (legacy)
            - distance_to_vah: Absolute distance from price to VAH (legacy)
            - distance_to_poc: Signed distance from price to POC (legacy)
            - distance_to_val_bps: Absolute distance in bps (Requirement 1.3)
            - distance_to_vah_bps: Absolute distance in bps (Requirement 1.3)
            - distance_to_poc_bps: Signed distance in bps (Requirement 1.3)
            - va_width_bps: Value area width in bps (Requirement 1.3.3)
        All values are 0.0 if corresponding AMT level is None.
    
    Requirements: 1.3.1, 1.3.2, 1.3.3, 3.1, 3.2, 3.3, 3.4
    """
    # Use price as fallback for mid_price if not provided
    effective_mid_price = mid_price if mid_price is not None else price
    
    # Calculate distance_to_val - absolute distance (Requirement 3.1)
    # Return 0.0 if VAL is None (Requirement 3.4)
    if value_area_low is not None:
        distance_to_val = abs(price - value_area_low)
        distance_to_val_bps = price_distance_abs_bps(price, value_area_low, effective_mid_price)
    else:
        distance_to_val = 0.0
        distance_to_val_bps = 0.0
    
    # Calculate distance_to_vah - absolute distance (Requirement 3.2)
    # Return 0.0 if VAH is None (Requirement 3.4)
    if value_area_high is not None:
        distance_to_vah = abs(price - value_area_high)
        distance_to_vah_bps = price_distance_abs_bps(price, value_area_high, effective_mid_price)
    else:
        distance_to_vah = 0.0
        distance_to_vah_bps = 0.0
    
    # Calculate distance_to_poc - signed distance (Requirement 3.3)
    # Positive when price > POC, negative when price < POC
    # Return 0.0 if POC is None (Requirement 3.4)
    if point_of_control is not None:
        distance_to_poc = price - point_of_control
        distance_to_poc_bps = price_distance_to_bps(price, point_of_control, effective_mid_price)
    else:
        distance_to_poc = 0.0
        distance_to_poc_bps = 0.0
    
    # Calculate VA width in bps (Requirement 1.3.3)
    if value_area_high is not None and value_area_low is not None:
        va_width_bps = calculate_va_width_bps(value_area_high, value_area_low, effective_mid_price)
    else:
        va_width_bps = 0.0
    
    return {
        # Legacy distances (for backward compatibility)
        "distance_to_val": distance_to_val,
        "distance_to_vah": distance_to_vah,
        "distance_to_poc": distance_to_poc,
        # BPS distances (Requirement 1.3)
        "distance_to_val_bps": distance_to_val_bps,
        "distance_to_vah_bps": distance_to_vah_bps,
        "distance_to_poc_bps": distance_to_poc_bps,
        "va_width_bps": va_width_bps,
    }


def _calculate_rotation_factor(
    orderflow_imbalance: float,
    trend_direction: Optional[str],
    trend_strength: float,
    scale_factor: float = 5.0,
    contribution_factor: float = 5.0,
) -> float:
    """
    Calculate rotation factor from orderflow imbalance and trend state.
    
    The rotation factor is a measure of price rotation/reversal strength that
    combines orderflow imbalance with trend information. It is used by trading
    strategies to identify potential reversal setups at value area boundaries.
    
    The calculation follows this formula:
    - Base: orderflow_imbalance * scale_factor
    - If trend_direction is "up": add trend_strength * contribution_factor
    - If trend_direction is "down": subtract trend_strength * contribution_factor
    - Result is clamped to [-15, +15] range
    
    Args:
        orderflow_imbalance: Orderflow imbalance value, typically in range [-1, 1].
            Positive values indicate buying pressure, negative values indicate
            selling pressure.
        trend_direction: Current trend direction - "up", "down", or None/other.
            When "up", trend contribution is added.
            When "down", trend contribution is subtracted.
            When None or other value, no trend contribution is applied.
        trend_strength: Strength of the current trend, typically in range [0, 1].
            Higher values indicate stronger trends.
        scale_factor: Multiplier for orderflow imbalance. Default is 5.0.
            This scales the base contribution from orderflow.
        contribution_factor: Multiplier for trend strength contribution. Default is 5.0.
            This scales the trend contribution that is added or subtracted.
    
    Returns:
        Rotation factor value clamped to [-15, +15] range.
        Positive values suggest upward rotation potential.
        Negative values suggest downward rotation potential.
    
    Requirements: 4.1, 4.2, 4.3, 4.4
    
    Examples:
        >>> _calculate_rotation_factor(0.5, "up", 0.8)
        6.5  # (0.5 * 5.0) + (0.8 * 5.0) = 2.5 + 4.0 = 6.5
        
        >>> _calculate_rotation_factor(0.5, "down", 0.8)
        -1.5  # (0.5 * 5.0) - (0.8 * 5.0) = 2.5 - 4.0 = -1.5
        
        >>> _calculate_rotation_factor(-0.3, None, 0.5)
        -1.5  # (-0.3 * 5.0) + 0 = -1.5 (no trend contribution)
    """
    # Calculate base rotation from orderflow imbalance (Requirement 4.1)
    base_rotation = orderflow_imbalance * scale_factor
    
    # Calculate trend contribution based on trend direction
    trend_contribution = 0.0
    
    if trend_direction == "up":
        # Add trend_strength contribution when trend is up (Requirement 4.2)
        trend_contribution = trend_strength * contribution_factor
    elif trend_direction == "down":
        # Subtract trend_strength contribution when trend is down (Requirement 4.3)
        trend_contribution = -trend_strength * contribution_factor
    # For None or other trend directions, trend_contribution remains 0.0
    
    # Calculate total rotation factor
    rotation_factor = base_rotation + trend_contribution
    
    # Clamp result to [-15, +15] range (Requirement 4.4)
    rotation_factor = max(-15.0, min(15.0, rotation_factor))
    
    return rotation_factor


class CandleCache:
    """
    Cache for recent candle data used by AMT calculations.
    
    This class maintains a rolling window of recent candles for each symbol,
    allowing the AMTCalculatorStage to access historical candle data without
    querying the database on every tick.
    
    The cache is designed to be thread-safe for single-writer, multiple-reader
    scenarios (typical in the trading pipeline).
    
    Attributes:
        _candles: Dictionary mapping symbol to deque of candles
        _max_candles: Maximum number of candles to retain per symbol
    """
    
    def __init__(self, max_candles: int = 500):
        """
        Initialize the candle cache.
        
        Args:
            max_candles: Maximum number of candles to retain per symbol.
                Default is 500, which provides ~41 hours of 5-minute candles.
        """
        from collections import deque
        self._candles: Dict[str, deque] = {}
        self._max_candles = max_candles
    
    def add_candle(self, symbol: str, candle: Dict[str, Any]) -> None:
        """
        Add a candle to the cache for a symbol.
        
        If the cache for this symbol exceeds max_candles, the oldest
        candle is automatically removed.
        
        Args:
            symbol: Trading symbol (e.g., "BTCUSDT")
            candle: Candle dictionary with keys: open, high, low, close, volume, ts
        """
        from collections import deque
        if symbol not in self._candles:
            self._candles[symbol] = deque(maxlen=self._max_candles)
        self._candles[symbol].append(candle)
    
    def get_recent_candles(
        self,
        symbol: str,
        count: int,
        before_ts: Optional[float] = None,
    ) -> List[Dict[str, Any]]:
        """
        Get recent candles for a symbol.
        
        Args:
            symbol: Trading symbol (e.g., "BTCUSDT")
            count: Maximum number of candles to return
            before_ts: Optional timestamp filter - only return candles
                with ts <= before_ts. If None, returns most recent candles.
        
        Returns:
            List of candle dictionaries, ordered from oldest to newest.
            Returns empty list if symbol not in cache or no matching candles.
        """
        if symbol not in self._candles:
            return []
        
        candles = list(self._candles[symbol])
        
        # Filter by timestamp if specified
        if before_ts is not None:
            candles = [c for c in candles if c.get("ts", 0) <= before_ts]
        
        # Return the most recent 'count' candles
        return candles[-count:] if len(candles) > count else candles
    
    def clear(self, symbol: Optional[str] = None) -> None:
        """
        Clear the cache.
        
        Args:
            symbol: If specified, only clear candles for this symbol.
                If None, clear all candles.
        """
        if symbol is not None:
            if symbol in self._candles:
                self._candles[symbol].clear()
        else:
            self._candles.clear()
    
    def get_candle_count(self, symbol: str) -> int:
        """
        Get the number of candles cached for a symbol.
        
        Args:
            symbol: Trading symbol
            
        Returns:
            Number of candles in cache for the symbol, or 0 if not cached.
        """
        if symbol not in self._candles:
            return 0
        return len(self._candles[symbol])


class AMTCalculatorStage(Stage):
    """
    Calculate AMT metrics from candle data.
    
    This pipeline stage calculates Auction Market Theory (AMT) metrics from
    historical candle data and stores them in the stage context for use by
    downstream stages (particularly SnapshotBuilderStage).
    
    The stage:
    1. Gets candles from the candle cache or ctx.data["candles"]
    2. Calculates volume profile (POC, VAH, VAL) using the configured algorithm
    3. Classifies current price position relative to value area
    4. Calculates distances from price to AMT levels
    5. Calculates flow_rotation (EWMA smoothed) and trend_bias separately
    6. Calculates legacy rotation_factor for backward compatibility (deprecated)
    7. Stores AMTLevels in ctx.data["amt_levels"]
    8. Always returns CONTINUE (never blocks the pipeline)
    
    If insufficient candle data is available, the stage sets ctx.data["amt_levels"]
    to None and continues processing. Downstream stages should handle this gracefully.
    
    Strategy Signal Architecture Fixes - Requirement 3:
    - Split rotation signals: flow_rotation (pure orderflow) and trend_bias (HTF trend)
    - EWMA smoothing for flow_rotation with configurable parameters
    - Legacy rotation_factor retained for backward compatibility (deprecated)
    
    Attributes:
        name: Stage name for identification ("amt_calculator")
        config: AMTCalculatorConfig with calculation parameters
        flow_rotation_config: FlowRotationConfig for flow_rotation calculation
        _candle_cache: Optional CandleCache for accessing historical candles
        _flow_rotation_calculator: FlowRotationCalculator instance
    
    Requirements: 1.1, 1.4, 1.5, 3.1, 3.2, 3.3, 3.4, 3.8, 3.9
    """
    name = "amt_calculator"
    
    def __init__(
        self,
        config: Optional[AMTCalculatorConfig] = None,
        candle_cache: Optional[CandleCache] = None,
        flow_rotation_config: Optional[FlowRotationConfig] = None,
    ):
        """
        Initialize the AMT calculator stage.
        
        Args:
            config: Configuration for AMT calculation. If None, uses defaults.
            candle_cache: Optional cache for accessing historical candles.
                If None, the stage will look for candles in ctx.data["candles"].
            flow_rotation_config: Configuration for flow_rotation calculation.
                If None, uses default FlowRotationConfig.
        """
        self.config = config or AMTCalculatorConfig()
        self._candle_cache = candle_cache
        self.flow_rotation_config = flow_rotation_config or FlowRotationConfig()
        self._flow_rotation_calculator = FlowRotationCalculator(self.flow_rotation_config)
    
    async def run(self, ctx: StageContext) -> StageResult:
        """
        Calculate AMT levels and store in context.
        
        This method:
        1. Gets candles from cache or ctx.data
        2. Calculates volume profile if sufficient data
        3. Calculates position, distances, and rotation factor
        4. Stores AMTLevels in ctx.data["amt_levels"]
        5. Returns CONTINUE (never blocks pipeline)
        
        Args:
            ctx: Stage context containing symbol, data dict, and other state
        
        Returns:
            StageResult.CONTINUE always - this stage never blocks the pipeline
        
        Requirements: 1.1, 1.4, 1.5
        """
        symbol = ctx.symbol
        calculation_ts = time.time()
        
        # Check if AMT levels are already present in context (e.g., from backtest pre-calculation)
        # This allows backtesting to pre-calculate AMT levels with proper timestamp filtering
        existing_amt = ctx.data.get("amt_levels")
        if existing_amt is not None:
            log_info(
                "amt_calculation_skipped_existing",
                symbol=symbol,
                reason="amt_levels_already_present",
            )
            return StageResult.CONTINUE
        
        # Get candles from cache or ctx.data
        candles = self._get_candles(ctx)
        
        # Check if we have sufficient data (Requirement 1.5)
        if not candles or len(candles) < self.config.min_candles:
            # Insufficient data - set amt_levels to None and continue
            ctx.data["amt_levels"] = None
            log_info(
                "amt_calculation_insufficient_data",
                symbol=symbol,
                candle_count=len(candles) if candles else 0,
                min_required=self.config.min_candles,
            )
            return StageResult.CONTINUE
        
        # Calculate volume profile (POC, VAH, VAL) - Requirement 1.1
        volume_profile = _calculate_volume_profile(candles, self.config)
        
        if not volume_profile:
            # Volume profile calculation failed - set amt_levels to None
            ctx.data["amt_levels"] = None
            log_warning(
                "amt_calculation_failed",
                symbol=symbol,
                candle_count=len(candles),
                reason="volume_profile_calculation_failed",
            )
            return StageResult.CONTINUE
        
        # Extract POC, VAH, VAL from volume profile
        poc = volume_profile.get("point_of_control")
        vah = volume_profile.get("value_area_high")
        val = volume_profile.get("value_area_low")
        
        # Get current price from context
        features = ctx.data.get("features") or {}
        market_context = ctx.data.get("market_context") or {}
        current_price = features.get("price") or market_context.get("price")
        
        if current_price is None:
            # No price available - set amt_levels to None
            ctx.data["amt_levels"] = None
            log_warning(
                "amt_calculation_no_price",
                symbol=symbol,
                reason="no_current_price_available",
            )
            return StageResult.CONTINUE
        
        # Classify position in value area (Requirement 2.1-2.4)
        position_in_value = _classify_position(current_price, vah, val)
        
        # Get mid_price for bps calculations (Requirement 1.3.1)
        # Use best_bid/best_ask if available, otherwise use current_price
        best_bid = features.get("best_bid") or market_context.get("best_bid")
        best_ask = features.get("best_ask") or market_context.get("best_ask")
        if best_bid is not None and best_ask is not None:
            mid_price = (best_bid + best_ask) / 2
        else:
            mid_price = current_price
        
        # Calculate distances with bps values (Requirement 1.3.1, 1.3.2, 1.3.3)
        distances = _calculate_distances(current_price, poc, vah, val, mid_price)
        
        # Get orderflow and trend data for rotation factor calculation
        orderflow_imbalance = features.get("orderflow_imbalance") or market_context.get("orderflow_imbalance") or 0.0
        trend_direction = features.get("trend_direction") or market_context.get("trend_direction")
        trend_strength = features.get("trend_strength") or market_context.get("trend_strength") or 0.0
        
        # Calculate flow_rotation with EWMA smoothing (Requirement 3.1, 3.2, 3.3)
        flow_rotation, flow_rotation_raw = self._flow_rotation_calculator.calculate(
            symbol=symbol,
            orderflow_imbalance=orderflow_imbalance,
        )
        
        # Calculate trend_bias separately (Requirement 3.4)
        trend_bias = _calculate_trend_bias(
            trend_direction=trend_direction,
            trend_strength=trend_strength,
        )
        
        # Calculate legacy rotation factor for backward compatibility (Requirement 3.9)
        # Log deprecation warning once per session
        global _ROTATION_FACTOR_DEPRECATION_LOGGED
        if not _ROTATION_FACTOR_DEPRECATION_LOGGED:
            log_warning(
                "rotation_factor is deprecated. Use flow_rotation and trend_bias instead.",
                event="rotation_factor_deprecated",
                symbol=symbol,
            )
            _ROTATION_FACTOR_DEPRECATION_LOGGED = True
        
        rotation_factor = _calculate_rotation_factor(
            orderflow_imbalance=orderflow_imbalance,
            trend_direction=trend_direction,
            trend_strength=trend_strength,
        )
        
        # Create AMTLevels dataclass instance with bps fields (Requirement 1.3, 1.4, 3.8)
        amt_levels = AMTLevels(
            point_of_control=poc,
            value_area_high=vah,
            value_area_low=val,
            position_in_value=position_in_value,
            # Legacy distance fields
            distance_to_poc=distances["distance_to_poc"],
            distance_to_vah=distances["distance_to_vah"],
            distance_to_val=distances["distance_to_val"],
            # BPS distance fields (Requirement 1.3)
            distance_to_poc_bps=distances["distance_to_poc_bps"],
            distance_to_vah_bps=distances["distance_to_vah_bps"],
            distance_to_val_bps=distances["distance_to_val_bps"],
            va_width_bps=distances["va_width_bps"],
            # Split rotation signals (Requirement 3)
            flow_rotation=flow_rotation,
            flow_rotation_raw=flow_rotation_raw,
            trend_bias=trend_bias,
            # Legacy rotation (deprecated - Requirement 3.9)
            rotation_factor=rotation_factor,
            candle_count=len(candles),
            calculation_ts=calculation_ts,
        )
        
        # Store AMTLevels in context for downstream stages (Requirement 1.4)
        ctx.data["amt_levels"] = amt_levels
        
        # Log with bps suffix for clarity (Requirement 1.5)
        log_info(
            "amt_calculation_complete",
            symbol=symbol,
            poc=round(poc, 2) if poc else None,
            vah=round(vah, 2) if vah else None,
            val=round(val, 2) if val else None,
            position_in_value=position_in_value,
            distance_to_poc_bps=round(distances["distance_to_poc_bps"], 2),
            distance_to_vah_bps=round(distances["distance_to_vah_bps"], 2),
            distance_to_val_bps=round(distances["distance_to_val_bps"], 2),
            va_width_bps=round(distances["va_width_bps"], 2),
            flow_rotation=round(flow_rotation, 2),
            flow_rotation_raw=round(flow_rotation_raw, 2),
            trend_bias=round(trend_bias, 2),
            rotation_factor=round(rotation_factor, 2),
            candle_count=len(candles),
        )
        
        # Always return CONTINUE - never block the pipeline (Requirement 1.5)
        return StageResult.CONTINUE
    
    def _get_candles(self, ctx: StageContext) -> List[Dict[str, Any]]:
        """
        Get candles from cache or context data.
        
        This method tries to get candles in the following order:
        1. From the candle cache (if available)
        2. From ctx.data["candles"]
        
        Args:
            ctx: Stage context
        
        Returns:
            List of candle dictionaries, or empty list if no candles available
        """
        symbol = ctx.symbol
        
        # Try to get candles from cache first
        if self._candle_cache is not None:
            candles = self._candle_cache.get_recent_candles(
                symbol=symbol,
                count=self.config.lookback_candles,
            )
            if candles:
                return candles
        
        # Fall back to ctx.data["candles"]
        candles = ctx.data.get("candles")
        if candles:
            # Limit to lookback_candles
            return candles[-self.config.lookback_candles:]
        
        return []
