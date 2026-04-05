"""Derived metrics calculator for orderbook data.

This module provides utility functions for calculating orderbook-derived metrics
including spread in basis points, depth in USD, and orderbook imbalance.

Feature: live-orderbook-data-storage
"""

from __future__ import annotations

from typing import List


def calculate_spread_bps(best_bid: float, best_ask: float) -> float:
    """Calculate spread in basis points.
    
    The spread is calculated as:
        spread_bps = ((best_ask - best_bid) / mid_price) * 10000
    
    where mid_price = (best_ask + best_bid) / 2
    
    Args:
        best_bid: The best (highest) bid price.
        best_ask: The best (lowest) ask price.
    
    Returns:
        The spread in basis points (1 bps = 0.01%).
        Returns 0.0 if mid_price is zero or if inputs are invalid.
    
    Validates: Requirements 3.1
    """
    # Handle edge cases
    if best_bid <= 0 or best_ask <= 0:
        return 0.0
    
    mid_price = (best_ask + best_bid) / 2.0
    
    if mid_price == 0:
        return 0.0
    
    spread = best_ask - best_bid
    spread_bps = (spread / mid_price) * 10000.0
    
    return spread_bps


def calculate_depth_usd(levels: List[List[float]]) -> float:
    """Calculate total depth in USD.
    
    The depth is calculated as:
        depth_usd = sum(price * size for price, size in levels)
    
    Args:
        levels: A list of [price, size] pairs representing orderbook levels.
                Each level is a list/tuple of [price, size].
    
    Returns:
        The total depth in USD.
        Returns 0.0 if levels is empty or contains invalid data.
    
    Validates: Requirements 3.2, 3.3
    """
    if not levels:
        return 0.0
    
    total_depth = 0.0
    
    for level in levels:
        try:
            # Handle both list and tuple formats
            if len(level) < 2:
                continue
            
            price = float(level[0])
            size = float(level[1])
            
            # Skip invalid values
            if price <= 0 or size <= 0:
                continue
            
            total_depth += price * size
        except (TypeError, ValueError, IndexError):
            # Skip malformed levels
            continue
    
    return total_depth


def calculate_orderbook_imbalance(bid_depth: float, ask_depth: float) -> float:
    """Calculate orderbook imbalance.
    
    The imbalance is calculated as:
        imbalance = (bid_depth - ask_depth) / (bid_depth + ask_depth)
    
    This metric indicates buying/selling pressure:
    - imbalance > 0: More buying pressure (more bids than asks)
    - imbalance < 0: More selling pressure (more asks than bids)
    - imbalance = 0: Balanced orderbook
    
    Args:
        bid_depth: Total USD value of all bid orders.
        ask_depth: Total USD value of all ask orders.
    
    Returns:
        The orderbook imbalance ratio (-1.0 to 1.0).
        Returns 0.0 if both depths are zero (balanced by default).
    
    Validates: Requirements 3.4
    """
    # Handle negative depths (shouldn't happen, but be defensive)
    # Clamp to zero first
    if bid_depth < 0:
        bid_depth = 0.0
    if ask_depth < 0:
        ask_depth = 0.0
    
    # Calculate total after clamping
    total_depth = bid_depth + ask_depth
    
    # Handle edge case where both depths are zero
    if total_depth == 0:
        return 0.0
    
    return (bid_depth - ask_depth) / total_depth
