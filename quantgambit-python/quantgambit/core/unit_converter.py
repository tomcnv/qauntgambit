"""
Unit Converter Module - Canonical unit conversion with mid_price denominator.

This module provides standardized conversion functions for expressing distances
and costs in basis points (bps). All distance calculations use the CANONICAL
formula with mid_price as the denominator for consistency.

CRITICAL: All distance calculations MUST use mid_price as denominator,
not the reference price. This ensures consistency across all components.

Canonical Formula:
    distance_bps = (price - reference) / mid_price * 10000

Where:
    - price: Current price
    - reference: Reference price (POC, VAH, VAL, entry, etc.)
    - mid_price: Mid price for normalization (best_bid + best_ask) / 2

Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 1.9, 1.10
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


def pct_to_bps(pct: float) -> float:
    """
    Convert percentage (as decimal) to basis points.
    
    1 bps = 0.01% = 0.0001
    
    Args:
        pct: Percentage as decimal (e.g., 0.01 for 1%)
        
    Returns:
        Value in basis points (e.g., 100 for 1%)
        
    Examples:
        >>> pct_to_bps(0.01)  # 1%
        100.0
        >>> pct_to_bps(0.003)  # 0.3%
        30.0
        >>> pct_to_bps(0.0001)  # 0.01%
        1.0
        
    Requirements: 1.2
    """
    return pct * 10000


def bps_to_pct(bps: float) -> float:
    """
    Convert basis points to percentage (as decimal).
    
    1 bps = 0.01% = 0.0001
    
    Args:
        bps: Value in basis points (e.g., 100 for 1%)
        
    Returns:
        Percentage as decimal (e.g., 0.01 for 1%)
        
    Examples:
        >>> bps_to_pct(100)  # 100 bps
        0.01
        >>> bps_to_pct(30)  # 30 bps
        0.003
        >>> bps_to_pct(1)  # 1 bps
        0.0001
        
    Requirements: 1.3
    """
    return bps / 10000


def price_distance_to_bps(
    price: float,
    reference: float,
    mid_price: float,
) -> float:
    """
    Calculate signed distance in bps using CANONICAL formula.
    
    Formula: (price - reference) / mid_price * 10000
    
    IMPORTANT: Uses mid_price as denominator, NOT reference price.
    This ensures consistent scaling across all distance calculations.
    
    Args:
        price: Current price
        reference: Reference price (POC, VAH, VAL, entry, etc.)
        mid_price: Mid price for normalization (best_bid + best_ask) / 2
        
    Returns:
        Signed distance in bps. Positive when price > reference.
        Returns 0.0 if mid_price is 0 (to avoid division by zero).
        
    Examples:
        >>> price_distance_to_bps(100.5, 100.0, 100.0)  # Price 0.5% above reference
        50.0
        >>> price_distance_to_bps(99.5, 100.0, 100.0)  # Price 0.5% below reference
        -50.0
        >>> price_distance_to_bps(100.0, 100.0, 100.0)  # At reference
        0.0
        
    Requirements: 1.1, 1.4, 1.5, 1.10
    """
    if mid_price == 0:
        logger.warning(
            "price_distance_to_bps called with mid_price=0, returning 0.0"
        )
        return 0.0
    return (price - reference) / mid_price * 10000


def price_distance_abs_bps(
    price: float,
    reference: float,
    mid_price: float,
) -> float:
    """
    Calculate absolute distance in bps using canonical formula.
    
    This is a convenience function that returns the absolute value
    of the signed distance calculation.
    
    Args:
        price: Current price
        reference: Reference price (POC, VAH, VAL, entry, etc.)
        mid_price: Mid price for normalization (best_bid + best_ask) / 2
        
    Returns:
        Absolute distance in bps. Always non-negative.
        Returns 0.0 if mid_price is 0 (to avoid division by zero).
        
    Examples:
        >>> price_distance_abs_bps(100.5, 100.0, 100.0)
        50.0
        >>> price_distance_abs_bps(99.5, 100.0, 100.0)
        50.0
        >>> price_distance_abs_bps(100.0, 100.0, 100.0)
        0.0
        
    Requirements: 1.4
    """
    return abs(price_distance_to_bps(price, reference, mid_price))


def calculate_va_width_bps(
    vah: float,
    val: float,
    mid_price: float,
) -> float:
    """
    Calculate value area width in bps using canonical formula.
    
    Formula: (vah - val) / mid_price * 10000
    
    Args:
        vah: Value Area High price
        val: Value Area Low price
        mid_price: Mid price for normalization
        
    Returns:
        Value area width in bps. Always non-negative.
        Returns 0.0 if mid_price is 0.
        
    Examples:
        >>> calculate_va_width_bps(101.0, 99.0, 100.0)  # 2% VA width
        200.0
        >>> calculate_va_width_bps(100.5, 99.5, 100.0)  # 1% VA width
        100.0
        
    Requirements: 2.5
    """
    if mid_price == 0:
        logger.warning(
            "calculate_va_width_bps called with mid_price=0, returning 0.0"
        )
        return 0.0
    return (vah - val) / mid_price * 10000


def log_threshold_bps(
    name: str,
    value_bps: float,
    symbol: Optional[str] = None,
    extra: Optional[dict] = None,
) -> None:
    """
    Log a threshold value with "bps" suffix for clarity.
    
    This helper function ensures all threshold logging follows
    the convention of suffixing values with "bps".
    
    Args:
        name: Name of the threshold (e.g., "min_distance_from_poc")
        value_bps: Threshold value in basis points
        symbol: Optional symbol for context
        extra: Optional extra fields to include in log
        
    Requirements: 1.9
    """
    log_extra = {
        "threshold_name": name,
        "threshold_value_bps": round(value_bps, 2),
    }
    if symbol:
        log_extra["symbol"] = symbol
    if extra:
        log_extra.update(extra)
    
    logger.info(
        f"{name}={value_bps:.2f}bps",
        extra=log_extra,
    )


def convert_legacy_pct_to_bps(
    param_name: str,
    value_pct: float,
    symbol: Optional[str] = None,
) -> float:
    """
    Convert a legacy percent-based parameter to bps and log the conversion.
    
    This function is used by Parameter_Resolver to convert legacy parameters
    during resolution. It logs the conversion for debugging purposes.
    
    Args:
        param_name: Name of the parameter being converted
        value_pct: Value in percentage (decimal form, e.g., 0.003 for 0.3%)
        symbol: Optional symbol for context
        
    Returns:
        Value converted to basis points
        
    Requirements: 1.8
    """
    value_bps = pct_to_bps(value_pct)
    
    log_extra = {
        "param_name": param_name,
        "original_pct": value_pct,
        "converted_bps": value_bps,
        "conversion_type": "legacy_pct_to_bps",
    }
    if symbol:
        log_extra["symbol"] = symbol
    
    logger.info(
        f"Converted legacy parameter {param_name}: {value_pct:.6f} (pct) -> {value_bps:.2f}bps",
        extra=log_extra,
    )
    
    return value_bps


# Validation helper
def validate_mid_price_denominator(
    calculation_name: str,
    denominator: float,
    mid_price: float,
) -> bool:
    """
    Validate that a distance calculation uses mid_price as denominator.
    
    This helper is used to ensure all distance calculations follow
    the canonical formula with mid_price as denominator.
    
    Args:
        calculation_name: Name of the calculation for logging
        denominator: The denominator being used
        mid_price: The expected mid_price value
        
    Returns:
        True if denominator matches mid_price, False otherwise
        
    Requirements: 1.10
    """
    if abs(denominator - mid_price) > 1e-10:  # Allow for floating point tolerance
        logger.error(
            f"Distance calculation '{calculation_name}' using incorrect denominator. "
            f"Expected mid_price={mid_price}, got denominator={denominator}. "
            f"All distance calculations MUST use mid_price as denominator.",
            extra={
                "calculation_name": calculation_name,
                "expected_denominator": mid_price,
                "actual_denominator": denominator,
            },
        )
        return False
    return True
