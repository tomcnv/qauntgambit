"""
Shared Volume Profile Calculation Module.

This module provides a shared implementation of the volume profile algorithm
used by both the live AMTCalculatorStage and the BacktestExecutor to ensure
identical POC, VAH, VAL calculations.

The volume profile algorithm distributes candle volume across price bins:

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

Requirements: 8.2 - Algorithm Consistency Between Live and Backtest
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class VolumeProfileConfig:
    """
    Configuration for volume profile calculation.
    
    This configuration controls how the volume profile is calculated
    and how AMT levels are derived from price/volume data.
    
    Attributes:
        bin_count: Number of price bins for volume profile resolution.
            Default is 20 bins. More bins provide finer resolution but may
            create noisier profiles with sparse data.
        value_area_pct: Percentage of total volume that defines the value area.
            Default is 68.0% (one standard deviation in normal distribution).
            Higher values create wider value areas.
        min_data_points: Minimum number of data points required for calculation.
            Default is 10. If fewer data points are available, the
            calculator returns an empty result.
    """
    bin_count: int = 20
    value_area_pct: float = 68.0
    min_data_points: int = 10


@dataclass(frozen=True)
class VolumeProfileResult:
    """
    Result of volume profile calculation.
    
    This is a frozen (immutable) dataclass that holds the calculated
    volume profile metrics.
    
    Attributes:
        point_of_control: Price level with highest traded volume (POC)
        value_area_high: Upper boundary of value area (VAH)
        value_area_low: Lower boundary of value area (VAL)
    """
    point_of_control: float
    value_area_high: float
    value_area_low: float
    
    def to_dict(self) -> Dict[str, float]:
        """Convert to dictionary format."""
        return {
            "point_of_control": self.point_of_control,
            "value_area_low": self.value_area_low,
            "value_area_high": self.value_area_high,
        }


def calculate_volume_profile(
    prices: List[float],
    volumes: List[float],
    config: Optional[VolumeProfileConfig] = None,
) -> Optional[VolumeProfileResult]:
    """
    Calculate volume profile from price and volume data.
    
    This is the shared implementation used by both AMTCalculatorStage (live)
    and BacktestExecutor (backtest) to ensure identical results.
    
    Algorithm:
    1. Calculate price range: min_price, max_price from all data points
    2. Create N bins of equal size: bin_size = (max - min) / N
    3. For each price/volume pair:
       - Find bin index: floor((price - min) / bin_size)
       - Add volume to bin
    4. Find POC: center of bin with maximum volume
    5. Calculate value area:
       - Start from POC bin
       - Expand outward until configured percentage of total volume is captured
       - VAL = lower bound of expanded region
       - VAH = upper bound of expanded region
    
    Args:
        prices: List of representative prices (typically OHLC average)
        volumes: List of volumes corresponding to each price
        config: Optional configuration. If None, uses defaults.
    
    Returns:
        VolumeProfileResult with POC, VAH, VAL values, or None if insufficient data.
    
    Requirements: 8.2 - Algorithm Consistency Between Live and Backtest
    
    Examples:
        >>> prices = [100.0, 101.0, 102.0, 101.5, 100.5]
        >>> volumes = [1000.0, 2000.0, 1500.0, 2500.0, 1000.0]
        >>> result = calculate_volume_profile(prices, volumes)
        >>> result.point_of_control  # Price with highest volume
    """
    if config is None:
        config = VolumeProfileConfig()
    
    # Validate input - return None if insufficient data
    if not prices or not volumes or len(prices) != len(volumes):
        return None
    
    if len(prices) < config.min_data_points:
        return None
    
    # Calculate price range
    min_price = min(prices)
    max_price = max(prices)
    
    # Handle edge case where all prices are the same
    if min_price == max_price:
        return VolumeProfileResult(
            point_of_control=min_price,
            value_area_low=min_price,
            value_area_high=min_price,
        )
    
    # Create price bins
    bins = config.bin_count
    bin_size = (max_price - min_price) / bins
    volume_bins = [0.0] * bins
    
    # Distribute volume across bins
    for price, volume in zip(prices, volumes):
        if min_price <= price <= max_price:
            # Calculate bin index, clamping to valid range
            bin_index = min(int((price - min_price) / bin_size), bins - 1)
            volume_bins[bin_index] += volume
    
    # Find Point of Control (POC) - bin with highest volume
    max_volume = max(volume_bins)
    
    # Handle edge case where total volume is zero
    if max_volume == 0:
        return VolumeProfileResult(
            point_of_control=(min_price + max_price) / 2,
            value_area_low=min_price,
            value_area_high=max_price,
        )
    
    poc_bin = volume_bins.index(max_volume)
    # POC is the center of the highest volume bin
    point_of_control = min_price + (poc_bin * bin_size) + (bin_size / 2)
    
    # Calculate Value Area (configured percentage of volume around POC)
    total_volume = sum(volume_bins)
    value_area_volume = total_volume * (config.value_area_pct / 100)
    
    # Find value area bounds by expanding from POC
    accumulated_volume = volume_bins[poc_bin]
    value_area_start = poc_bin
    value_area_end = poc_bin
    
    # Expand outward from POC until we capture the configured percentage of volume
    while accumulated_volume < value_area_volume:
        expanded = False
        
        # Try to expand downward (lower prices)
        if value_area_start > 0:
            value_area_start -= 1
            accumulated_volume += volume_bins[value_area_start]
            expanded = True
        
        # Try to expand upward (higher prices) if still need more volume
        if accumulated_volume < value_area_volume and value_area_end < bins - 1:
            value_area_end += 1
            accumulated_volume += volume_bins[value_area_end]
            expanded = True
        
        # If we can't expand anymore, break
        if not expanded:
            break
    
    # Calculate VAL and VAH from bin boundaries
    # Guard against floating point edge effects: ensure the value-area bounds
    # are inclusive of any representative prices that fell into the included bins.
    eps = bin_size * 1e-9
    value_area_low = max(min_price, (min_price + (value_area_start * bin_size)) - eps)
    value_area_high = min(max_price, (min_price + ((value_area_end + 1) * bin_size)) + eps)
    
    return VolumeProfileResult(
        point_of_control=point_of_control,
        value_area_low=value_area_low,
        value_area_high=value_area_high,
    )


def calculate_volume_profile_from_candles(
    candles: List[Dict[str, Any]],
    config: Optional[VolumeProfileConfig] = None,
) -> Optional[VolumeProfileResult]:
    """
    Calculate volume profile from candle data.
    
    This is a convenience function that extracts prices and volumes from
    candle dictionaries and calls calculate_volume_profile().
    
    Each candle's representative price is calculated as the OHLC average:
    (open + high + low + close) / 4
    
    Args:
        candles: List of candle dictionaries with keys:
            - open: Opening price
            - high: High price
            - low: Low price
            - close: Closing price
            - volume: Traded volume
        config: Optional configuration. If None, uses defaults.
    
    Returns:
        VolumeProfileResult with POC, VAH, VAL values, or None if insufficient data.
    
    Requirements: 8.2 - Algorithm Consistency Between Live and Backtest
    
    Examples:
        >>> candles = [
        ...     {"open": 100, "high": 102, "low": 99, "close": 101, "volume": 1000},
        ...     {"open": 101, "high": 103, "low": 100, "close": 102, "volume": 1500},
        ... ]
        >>> result = calculate_volume_profile_from_candles(candles)
    """
    if config is None:
        config = VolumeProfileConfig()
    
    # Validate input
    if not candles:
        return None
    
    # Extract prices and volumes from candles
    # Use OHLC average as representative price for each candle
    prices: List[float] = []
    volumes: List[float] = []
    
    for candle in candles:
        try:
            open_price = float(candle.get("open", 0))
            high_price = float(candle.get("high", 0))
            low_price = float(candle.get("low", 0))
            close_price = float(candle.get("close", 0))
            volume = float(candle.get("volume", 0))
            
            # Skip invalid candles (zero or negative prices)
            if open_price <= 0 or high_price <= 0 or low_price <= 0 or close_price <= 0:
                continue
            
            # Calculate representative price as OHLC average
            representative_price = (open_price + high_price + low_price + close_price) / 4
            prices.append(representative_price)
            volumes.append(volume)
        except (TypeError, ValueError):
            # Skip candles with invalid data
            continue
    
    # Use the shared calculation function
    return calculate_volume_profile(prices, volumes, config)
