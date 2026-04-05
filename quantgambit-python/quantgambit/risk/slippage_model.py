"""
SlippageModel - Market-state-adaptive slippage estimation.

This module provides sophisticated slippage estimation that adapts to:
- Symbol characteristics (BTC vs altcoins)
- Current spread conditions
- Order book depth
- Volatility regime
- Execution urgency

Requirements: V2 Proposal Section 6 - Market-State-Adaptive Slippage
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Dict, Optional


@dataclass
class SlippageEstimate:
    """Result of slippage estimation."""
    slippage_bps: float
    base_bps: float
    spread_factor: float
    depth_factor: float
    volatility_multiplier: float
    urgency_multiplier: float


class SlippageModel:
    """Calculate expected slippage based on market state.
    
    Slippage estimation considers multiple factors:
    1. Symbol-specific floor (BTC < ETH < altcoins)
    2. Current spread (tight spread = low slippage)
    3. Order size vs book depth
    4. Volatility regime
    5. Execution urgency
    
    Requirements: V2 Proposal Section 6
    """
    
    # Symbol-specific floors (basis points)
    SYMBOL_FLOORS: Dict[str, float] = {
        "BTCUSDT": 0.5,
        "ETHUSDT": 0.8,
        "SOLUSDT": 2.0,
        "BNBUSDT": 1.0,
        "ADAUSDT": 2.5,
        "DOGEUSDT": 3.0,
        "XRPUSDT": 1.5,
    }
    
    DEFAULT_FLOOR = 2.0  # Default for unknown symbols
    
    def __init__(self):
        """Initialize slippage model."""
        self.multiplier = float(os.getenv("SLIPPAGE_MODEL_MULTIPLIER", "1.0"))
        self.floor_override_bps = float(os.getenv("SLIPPAGE_MODEL_FLOOR_BPS", "0.0"))
        self.max_slippage_bps = float(os.getenv("SLIPPAGE_MODEL_MAX_BPS", "250.0"))
        self.min_depth_usd = float(os.getenv("SLIPPAGE_MODEL_MIN_DEPTH_USD", "500.0"))
        self.max_depth_factor = float(os.getenv("SLIPPAGE_MODEL_MAX_DEPTH_FACTOR", "10.0"))
    
    def calculate_slippage_bps(
        self,
        symbol: str,
        spread_bps: float,
        spread_percentile: Optional[float] = None,
        book_depth_usd: Optional[float] = None,
        order_size_usd: Optional[float] = None,
        volatility_regime: Optional[str] = None,
        urgency: Optional[str] = None,
    ) -> float:
        """Calculate expected INCREMENTAL slippage in basis points (excludes spread).
        
        IMPORTANT: This returns slippage BEYOND the spread. The spread is accounted
        for separately in cost calculations. Do NOT add spread to this value again.
        
        The spread_bps parameter is used as a market condition indicator (tight spread
        = lower slippage), NOT to include spread in the returned value.
        
        Args:
            symbol: Trading symbol (e.g., "BTCUSDT")
            spread_bps: Current spread in basis points (used as market condition indicator)
            spread_percentile: Spread percentile (0-100), optional
            book_depth_usd: Order book depth in USD, optional
            order_size_usd: Order size in USD, optional
            volatility_regime: "low", "normal", "high", "extreme", optional
            urgency: "passive", "patient", "immediate", optional
            
        Returns:
            Expected slippage in basis points
        """
        # Base: symbol floor (optionally overridden)
        base = max(self.SYMBOL_FLOORS.get(symbol, self.DEFAULT_FLOOR), self.floor_override_bps)
        
        # Spread component (tight spread = low slippage)
        # If spread is 2 bps, factor = 1.0
        # If spread is 4 bps, factor = 2.0
        spread_factor = max(1.0, spread_bps / 2.0)
        
        # Depth component (size vs depth)
        depth_factor = 1.0
        if book_depth_usd is not None and order_size_usd is not None and order_size_usd > 0:
            depth = max(book_depth_usd, self.min_depth_usd)
            depth_ratio = order_size_usd / depth
            # 10% of depth = +1.0 bps additional slippage
            depth_factor = 1.0 + (depth_ratio * 10.0)
            depth_factor = min(depth_factor, self.max_depth_factor)
        
        # Volatility multiplier
        vol_multiplier = self._get_volatility_multiplier(volatility_regime)
        
        # Urgency multiplier
        urgency_multiplier = self._get_urgency_multiplier(urgency)
        
        # Calculate total slippage
        slippage = base * spread_factor * depth_factor * vol_multiplier * urgency_multiplier
        
        # Never below floor; apply global multiplier
        slippage = max(base, slippage)
        slippage = max(base * self.multiplier, slippage * self.multiplier)
        return min(slippage, self.max_slippage_bps)
    
    def calculate_slippage_with_detail(
        self,
        symbol: str,
        spread_bps: float,
        spread_percentile: Optional[float] = None,
        book_depth_usd: Optional[float] = None,
        order_size_usd: Optional[float] = None,
        volatility_regime: Optional[str] = None,
        urgency: Optional[str] = None,
    ) -> SlippageEstimate:
        """Calculate slippage with detailed breakdown.
        
        Same as calculate_slippage_bps but returns detailed breakdown
        of all factors for transparency and debugging.
        
        Args:
            Same as calculate_slippage_bps
            
        Returns:
            SlippageEstimate with detailed breakdown
        """
        # Base: symbol floor (optionally overridden)
        base = max(self.SYMBOL_FLOORS.get(symbol, self.DEFAULT_FLOOR), self.floor_override_bps)
        
        # Spread component
        spread_factor = max(1.0, spread_bps / 2.0)
        
        # Depth component
        depth_factor = 1.0
        if book_depth_usd is not None and order_size_usd is not None and order_size_usd > 0:
            depth = max(book_depth_usd, self.min_depth_usd)
            depth_ratio = order_size_usd / depth
            depth_factor = 1.0 + (depth_ratio * 10.0)
            depth_factor = min(depth_factor, self.max_depth_factor)
        
        # Volatility multiplier
        vol_multiplier = self._get_volatility_multiplier(volatility_regime)
        
        # Urgency multiplier
        urgency_multiplier = self._get_urgency_multiplier(urgency)
        
        # Calculate total slippage
        slippage = base * spread_factor * depth_factor * vol_multiplier * urgency_multiplier
        slippage = max(base, slippage)
        slippage = max(base * self.multiplier, slippage * self.multiplier)
        slippage = min(slippage, self.max_slippage_bps)
        
        return SlippageEstimate(
            slippage_bps=slippage,
            base_bps=base * self.multiplier,
            spread_factor=spread_factor,
            depth_factor=depth_factor,
            volatility_multiplier=vol_multiplier,
            urgency_multiplier=urgency_multiplier,
        )
    
    def _get_volatility_multiplier(self, volatility_regime: Optional[str]) -> float:
        """Get volatility multiplier.
        
        Args:
            volatility_regime: "low", "normal", "high", "extreme"
            
        Returns:
            Multiplier for volatility regime
        """
        if volatility_regime is None:
            return 1.0
        
        multipliers = {
            "low": 0.8,
            "normal": 1.0,
            "high": 1.5,
            "extreme": 2.5,
        }
        
        return multipliers.get(volatility_regime.lower(), 1.0)
    
    def _get_urgency_multiplier(self, urgency: Optional[str]) -> float:
        """Get urgency multiplier.
        
        Args:
            urgency: "passive", "patient", "immediate"
            
        Returns:
            Multiplier for execution urgency
        """
        if urgency is None:
            return 1.0
        
        multipliers = {
            "passive": 0.5,   # Limit orders, willing to wait
            "patient": 0.8,   # Limit with timeout
            "immediate": 1.2, # Market orders
        }
        
        return multipliers.get(urgency.lower(), 1.0)


def calculate_adverse_selection_bps(
    symbol: str,
    volatility_regime: Optional[str] = None,
    hold_time_expected_sec: Optional[float] = None,
) -> float:
    """Estimate adverse selection cost.
    
    Adverse selection occurs when informed traders move the market against us
    between entry and exit. This is particularly relevant for:
    - High volatility periods (more informed flow)
    - Longer hold times (more time for adverse moves)
    - Less liquid symbols (easier to move)
    
    Args:
        symbol: Trading symbol
        volatility_regime: "low", "normal", "high", "extreme"
        hold_time_expected_sec: Expected hold time in seconds
        
    Returns:
        Adverse selection cost in basis points
        
    Requirements: V2 Proposal Section 6 - Adverse Selection Buffer
    """
    # Base adverse selection (informed traders moving against us)
    base_adverse_selection = {
        "BTCUSDT": 1.0,
        "ETHUSDT": 1.2,
        "SOLUSDT": 2.0,
        "BNBUSDT": 1.5,
        "ADAUSDT": 2.5,
        "DOGEUSDT": 3.0,
        "XRPUSDT": 1.8,
    }.get(symbol, 1.5)  # Default 1.5 bps
    
    # Volatility increases adverse selection
    vol_multiplier = 1.0
    if volatility_regime is not None:
        vol_multipliers = {
            "low": 0.8,
            "normal": 1.0,
            "high": 1.5,
            "extreme": 2.5,
        }
        vol_multiplier = vol_multipliers.get(volatility_regime.lower(), 1.0)
    
    # Longer holds = more adverse selection
    time_factor = 1.0
    if hold_time_expected_sec is not None and hold_time_expected_sec > 0:
        # +10% per 5 minutes
        time_factor = 1.0 + (hold_time_expected_sec / 300.0) * 0.1
    
    return base_adverse_selection * vol_multiplier * time_factor


@dataclass
class CostBreakdown:
    """Complete cost breakdown for a trade."""
    fee_bps: float
    spread_bps: float
    slippage_bps: float
    adverse_selection_bps: float
    total_bps: float
    
    # Optional detailed breakdown
    slippage_detail: Optional[SlippageEstimate] = None


def calculate_stress_costs(
    normal_costs: CostBreakdown,
    spread_percentile: Optional[float] = None,
    volatility_regime: Optional[str] = None,
) -> CostBreakdown:
    """Calculate costs under stress conditions (P90 spread/slippage).
    
    Stress costs provide safety margins for adverse market conditions:
    - High spread percentile (> 70%)
    - High volatility regime
    
    Args:
        normal_costs: Normal cost breakdown
        spread_percentile: Current spread percentile (0-100)
        volatility_regime: "low", "normal", "high", "extreme"
        
    Returns:
        Stressed cost breakdown
        
    Requirements: V2 Proposal Section 7 - Stress Costs for Safety Margins
    """
    stress_multiplier = 1.0
    
    # High spread percentile
    if spread_percentile is not None and spread_percentile > 70:
        stress_multiplier *= 1.5
    
    # High volatility
    if volatility_regime is not None and volatility_regime.lower() in ["high", "extreme"]:
        stress_multiplier *= 1.8
    
    return CostBreakdown(
        fee_bps=normal_costs.fee_bps,  # Fees don't change under stress
        spread_bps=normal_costs.spread_bps * stress_multiplier,
        slippage_bps=normal_costs.slippage_bps * stress_multiplier,
        adverse_selection_bps=normal_costs.adverse_selection_bps * stress_multiplier,
        total_bps=(
            normal_costs.fee_bps +
            normal_costs.spread_bps * stress_multiplier +
            normal_costs.slippage_bps * stress_multiplier +
            normal_costs.adverse_selection_bps * stress_multiplier
        ),
    )
