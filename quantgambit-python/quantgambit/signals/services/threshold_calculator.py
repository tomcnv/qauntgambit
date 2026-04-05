"""
Threshold Calculator - Regime-Relative Dual Thresholds

This module implements the dual threshold calculation for strategy signal architecture.
It provides two separate thresholds:
1. setup_threshold_bps: For detecting geometric setups (regime-relative)
2. profitability_threshold_bps: For economic viability after costs

Requirements: 2.1-2.12 (Regime-Relative Thresholds with Setup vs Profitability Split)

Design Reference:
- Setup threshold: max(b * va_width_bps, floor_bps)
- Profitability threshold: max(k * expected_cost_bps, setup_threshold)

Where:
- k: Cost multiplier for profitability threshold (default 3.0)
- b: VA width multiplier for setup threshold (default 0.25)
- floor_bps: Absolute minimum for setup threshold (default 12.0)
"""

from dataclasses import dataclass, field
from typing import Optional
import logging

from quantgambit.observability.logger import log_info, log_warning

logger = logging.getLogger(__name__)


@dataclass
class ThresholdConfig:
    """
    Per-strategy threshold configuration.
    
    Attributes:
        k: Cost multiplier for profitability threshold (default 3.0)
           Higher k = more conservative (require more edge over costs)
        b: VA width multiplier for setup threshold (default 0.25)
           Higher b = require larger distance relative to VA width
        floor_bps: Absolute minimum for setup threshold (default 12.0)
           Ensures minimum distance even in tight VA conditions
    
    Requirements: 2.6, 2.7
    """
    k: float = 3.0          # Cost multiplier for profitability threshold
    b: float = 0.25         # VA width multiplier for setup threshold
    floor_bps: float = 12.0 # Absolute minimum for setup threshold
    
    def __post_init__(self):
        """Validate configuration parameters."""
        if self.k <= 0:
            raise ValueError(f"k must be positive, got {self.k}")
        if self.b < 0:
            raise ValueError(f"b must be non-negative, got {self.b}")
        if self.floor_bps < 0:
            raise ValueError(f"floor_bps must be non-negative, got {self.floor_bps}")


@dataclass
class DualThreshold:
    """
    Computed regime-relative thresholds.
    
    Contains both the final threshold values and the component values
    that contributed to them, along with binding constraint information
    for debugging and diagnostics.
    
    Attributes:
        setup_threshold_bps: Minimum distance to detect a geometric setup
        profitability_threshold_bps: Minimum distance for economic viability
        va_component_bps: b * va_width_bps contribution
        cost_component_bps: k * expected_cost_bps contribution
        floor_component_bps: floor_bps value
        setup_binding_constraint: Which constraint bound setup threshold ("va_width" or "floor")
        profit_binding_constraint: Which constraint bound profitability threshold ("cost" or "setup")
    
    Requirements: 2.1, 2.2, 2.3
    """
    setup_threshold_bps: float      # For detecting geometric setups
    profitability_threshold_bps: float  # For economic viability
    va_component_bps: float         # b * va_width_bps
    cost_component_bps: float       # k * expected_cost_bps
    floor_component_bps: float      # floor_bps value
    setup_binding_constraint: str   # "va_width" or "floor"
    profit_binding_constraint: str  # "cost" or "setup"
    
    def __post_init__(self):
        """Validate threshold values."""
        if self.setup_threshold_bps < 0:
            raise ValueError(f"setup_threshold_bps must be non-negative, got {self.setup_threshold_bps}")
        if self.profitability_threshold_bps < 0:
            raise ValueError(f"profitability_threshold_bps must be non-negative, got {self.profitability_threshold_bps}")
        if self.profitability_threshold_bps < self.setup_threshold_bps:
            raise ValueError(
                f"profitability_threshold_bps ({self.profitability_threshold_bps}) must be >= "
                f"setup_threshold_bps ({self.setup_threshold_bps})"
            )
        if self.setup_binding_constraint not in ("va_width", "floor"):
            raise ValueError(f"setup_binding_constraint must be 'va_width' or 'floor', got {self.setup_binding_constraint}")
        if self.profit_binding_constraint not in ("cost", "setup"):
            raise ValueError(f"profit_binding_constraint must be 'cost' or 'setup', got {self.profit_binding_constraint}")


class ThresholdCalculator:
    """
    Calculates regime-relative dual thresholds for strategy signal evaluation.
    
    This calculator provides two separate thresholds:
    1. setup_threshold_bps: For detecting geometric setups
       - Adapts to market regime via VA width
       - Has an absolute floor to prevent too-tight thresholds
    
    2. profitability_threshold_bps: For economic viability
       - Ensures sufficient edge over costs
       - Never lower than setup threshold
    
    Requirements: 2.1-2.12
    """
    
    # Default configuration when resolved_params unavailable (Requirement 2.7)
    DEFAULT_CONFIG = ThresholdConfig(k=3.0, b=0.25, floor_bps=12.0)
    
    def __init__(self, default_config: Optional[ThresholdConfig] = None):
        """
        Initialize ThresholdCalculator.
        
        Args:
            default_config: Default configuration to use when not provided.
                           Uses DEFAULT_CONFIG if None.
        """
        self.default_config = default_config or self.DEFAULT_CONFIG
    
    def calculate_setup_threshold(
        self,
        va_width_bps: float,
        b: float,
        floor_bps: float,
    ) -> tuple[float, str]:
        """
        Calculate setup threshold for detecting geometric setups.
        
        Formula: max(b * va_width_bps, floor_bps)
        
        Args:
            va_width_bps: Value area width in basis points
            b: VA width multiplier
            floor_bps: Absolute minimum threshold
            
        Returns:
            Tuple of (setup_threshold_bps, binding_constraint)
            binding_constraint is "va_width" or "floor"
        
        Requirements: 2.2, 2.8
        """
        va_component = b * va_width_bps
        setup_threshold = max(va_component, floor_bps)
        binding_constraint = "va_width" if va_component >= floor_bps else "floor"
        
        return setup_threshold, binding_constraint
    
    def calculate_profitability_threshold(
        self,
        expected_cost_bps: float,
        setup_threshold_bps: float,
        k: float,
    ) -> tuple[float, str]:
        """
        Calculate profitability threshold for economic viability.
        
        Formula: max(k * expected_cost_bps, setup_threshold_bps)
        
        Args:
            expected_cost_bps: Total expected round-trip cost in bps
            setup_threshold_bps: Setup threshold (profitability can't be lower)
            k: Cost multiplier
            
        Returns:
            Tuple of (profitability_threshold_bps, binding_constraint)
            binding_constraint is "cost" or "setup"
        
        Requirements: 2.3, 2.9
        """
        cost_component = k * expected_cost_bps
        profitability_threshold = max(cost_component, setup_threshold_bps)
        binding_constraint = "cost" if cost_component >= setup_threshold_bps else "setup"
        
        return profitability_threshold, binding_constraint
    
    def calculate_dual_threshold(
        self,
        expected_cost_bps: float,
        va_width_bps: float,
        config: Optional[ThresholdConfig] = None,
    ) -> DualThreshold:
        """
        Calculate dual regime-relative thresholds.
        
        This is the main entry point for threshold calculation. It computes
        both setup and profitability thresholds based on market conditions
        and configuration.
        
        Args:
            expected_cost_bps: Total expected round-trip cost in bps
                              (fees + spread + slippage)
            va_width_bps: Value area width in bps
                         Calculated as (VAH - VAL) / mid_price * 10000
            config: Threshold configuration. Uses default_config if None.
            
        Returns:
            DualThreshold with both thresholds and component breakdown
        
        Requirements: 2.1, 2.2, 2.3, 2.4, 2.5
        """
        config = config or self.default_config
        
        # Calculate setup threshold (Requirement 2.2)
        va_component = config.b * va_width_bps
        floor_component = config.floor_bps
        setup_threshold, setup_binding = self.calculate_setup_threshold(
            va_width_bps=va_width_bps,
            b=config.b,
            floor_bps=config.floor_bps,
        )
        
        # Calculate profitability threshold (Requirement 2.3)
        cost_component = config.k * expected_cost_bps
        profitability_threshold, profit_binding = self.calculate_profitability_threshold(
            expected_cost_bps=expected_cost_bps,
            setup_threshold_bps=setup_threshold,
            k=config.k,
        )
        
        return DualThreshold(
            setup_threshold_bps=setup_threshold,
            profitability_threshold_bps=profitability_threshold,
            va_component_bps=va_component,
            cost_component_bps=cost_component,
            floor_component_bps=floor_component,
            setup_binding_constraint=setup_binding,
            profit_binding_constraint=profit_binding,
        )
    
    def calculate_va_width_bps(
        self,
        vah: float,
        val: float,
        mid_price: float,
    ) -> float:
        """
        Calculate value area width in bps using canonical formula.
        
        Formula: (VAH - VAL) / mid_price * 10000
        
        Args:
            vah: Value Area High price
            val: Value Area Low price
            mid_price: Mid price for normalization
            
        Returns:
            Value area width in basis points
        
        Requirements: 2.5
        """
        if mid_price == 0:
            return 0.0
        return (vah - val) / mid_price * 10000
    
    def log_thresholds(
        self,
        symbol: str,
        dual_threshold: DualThreshold,
        actual_distance_bps: float,
        strategy_id: str = "",
        profile_id: str = "",
    ) -> None:
        """
        Log both thresholds alongside actual distance for debugging.
        
        Requirements: 2.12
        
        Args:
            symbol: Trading symbol
            dual_threshold: Calculated dual thresholds
            actual_distance_bps: Actual distance from reference in bps
            strategy_id: Strategy identifier
            profile_id: Profile identifier
        """
        log_info(
            "dual_threshold_evaluation",
            symbol=symbol,
            strategy_id=strategy_id,
            profile_id=profile_id,
            actual_distance_bps=round(actual_distance_bps, 2),
            setup_threshold_bps=round(dual_threshold.setup_threshold_bps, 2),
            profitability_threshold_bps=round(dual_threshold.profitability_threshold_bps, 2),
            va_component_bps=round(dual_threshold.va_component_bps, 2),
            cost_component_bps=round(dual_threshold.cost_component_bps, 2),
            floor_component_bps=round(dual_threshold.floor_component_bps, 2),
            setup_binding=dual_threshold.setup_binding_constraint,
            profit_binding=dual_threshold.profit_binding_constraint,
            passes_setup=actual_distance_bps >= dual_threshold.setup_threshold_bps,
            passes_profitability=actual_distance_bps >= dual_threshold.profitability_threshold_bps,
        )


# Module-level singleton for convenience
_default_calculator: Optional[ThresholdCalculator] = None


def get_threshold_calculator() -> ThresholdCalculator:
    """Get the default ThresholdCalculator singleton."""
    global _default_calculator
    if _default_calculator is None:
        _default_calculator = ThresholdCalculator()
    return _default_calculator
