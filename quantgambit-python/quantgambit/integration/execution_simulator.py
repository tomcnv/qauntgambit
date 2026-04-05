"""Execution simulator configuration for realistic backtest execution modeling.

This module provides configuration for simulating realistic execution behavior
in backtests, including latency, partial fills, and slippage modeling.
"""

from dataclasses import dataclass, field, asdict
from typing import Dict, Any, List, Optional, Tuple
from uuid import uuid4
import random
import math


@dataclass
class ExecutionSimulatorConfig:
    """Configuration for execution simulation.
    
    This configuration controls how the execution simulator models realistic
    exchange behavior including latency, partial fills, and slippage.
    
    Attributes:
        base_latency_ms: Base latency in milliseconds for order execution.
            Must be >= 0.
        latency_std_ms: Standard deviation of latency in milliseconds.
            Must be >= 0.
        partial_fill_prob_small: Probability of partial fill for small orders
            (< 1% of available depth). Must be in [0, 1].
        partial_fill_prob_medium: Probability of partial fill for medium orders
            (1-5% of available depth). Must be in [0, 1].
        partial_fill_prob_large: Probability of partial fill for large orders
            (5-20% of available depth). Must be in [0, 1].
        partial_fill_ratio_min: Minimum fill ratio when partial fill occurs.
            Must be in [0, 1].
        partial_fill_ratio_max: Maximum fill ratio when partial fill occurs.
            Must be in [0, 1] and >= partial_fill_ratio_min.
        queue_position_factor: How much queue position affects fill probability.
            Must be >= 0.
        base_slippage_bps: Base slippage in basis points.
            Must be >= 0.
        depth_slippage_factor: Additional slippage per 10% of depth consumed.
            Must be >= 0.
        scenario: Scenario preset name ("optimistic", "realistic", "pessimistic").
    """
    
    # Latency simulation
    base_latency_ms: float = 50.0
    latency_std_ms: float = 20.0
    
    # Partial fill simulation
    partial_fill_prob_small: float = 0.02   # Orders < 1% of depth
    partial_fill_prob_medium: float = 0.10  # Orders 1-5% of depth
    partial_fill_prob_large: float = 0.30   # Orders 5-20% of depth
    partial_fill_ratio_min: float = 0.3
    partial_fill_ratio_max: float = 0.9
    
    # Queue position effects
    queue_position_factor: float = 0.5  # How much queue affects fill prob
    
    # Slippage model
    base_slippage_bps: float = 1.0
    depth_slippage_factor: float = 0.1  # Additional slippage per 10% of depth
    
    # Scenario presets
    scenario: str = "realistic"  # "optimistic", "realistic", "pessimistic"
    
    def __post_init__(self) -> None:
        """Validate configuration parameters after initialization."""
        self._validate()
    
    def _validate(self) -> None:
        """Validate all configuration parameters.
        
        Raises:
            ValueError: If any parameter is out of valid range.
        """
        errors: List[str] = []
        
        # Latency validation
        if self.base_latency_ms < 0:
            errors.append(f"base_latency_ms must be >= 0, got {self.base_latency_ms}")
        if self.latency_std_ms < 0:
            errors.append(f"latency_std_ms must be >= 0, got {self.latency_std_ms}")
        
        # Partial fill probability validation
        if not 0 <= self.partial_fill_prob_small <= 1:
            errors.append(
                f"partial_fill_prob_small must be in [0, 1], got {self.partial_fill_prob_small}"
            )
        if not 0 <= self.partial_fill_prob_medium <= 1:
            errors.append(
                f"partial_fill_prob_medium must be in [0, 1], got {self.partial_fill_prob_medium}"
            )
        if not 0 <= self.partial_fill_prob_large <= 1:
            errors.append(
                f"partial_fill_prob_large must be in [0, 1], got {self.partial_fill_prob_large}"
            )
        
        # Partial fill ratio validation
        if not 0 <= self.partial_fill_ratio_min <= 1:
            errors.append(
                f"partial_fill_ratio_min must be in [0, 1], got {self.partial_fill_ratio_min}"
            )
        if not 0 <= self.partial_fill_ratio_max <= 1:
            errors.append(
                f"partial_fill_ratio_max must be in [0, 1], got {self.partial_fill_ratio_max}"
            )
        if self.partial_fill_ratio_min > self.partial_fill_ratio_max:
            errors.append(
                f"partial_fill_ratio_min ({self.partial_fill_ratio_min}) must be <= "
                f"partial_fill_ratio_max ({self.partial_fill_ratio_max})"
            )
        
        # Queue position factor validation
        if self.queue_position_factor < 0:
            errors.append(
                f"queue_position_factor must be >= 0, got {self.queue_position_factor}"
            )
        
        # Slippage validation
        if self.base_slippage_bps < 0:
            errors.append(f"base_slippage_bps must be >= 0, got {self.base_slippage_bps}")
        if self.depth_slippage_factor < 0:
            errors.append(
                f"depth_slippage_factor must be >= 0, got {self.depth_slippage_factor}"
            )
        
        # Scenario validation
        valid_scenarios = {"optimistic", "realistic", "pessimistic"}
        if self.scenario not in valid_scenarios:
            errors.append(
                f"scenario must be one of {valid_scenarios}, got '{self.scenario}'"
            )
        
        if errors:
            raise ValueError("Invalid ExecutionSimulatorConfig: " + "; ".join(errors))
    
    @classmethod
    def optimistic(cls) -> "ExecutionSimulatorConfig":
        """Create an optimistic execution scenario.
        
        Optimistic scenarios model favorable market conditions with:
        - Lower latency (30ms base, 10ms std)
        - Lower partial fill probabilities
        - Lower slippage (0.5 bps)
        
        Returns:
            ExecutionSimulatorConfig with optimistic parameters.
        """
        return cls(
            base_latency_ms=30.0,
            latency_std_ms=10.0,
            partial_fill_prob_small=0.01,
            partial_fill_prob_medium=0.05,
            partial_fill_prob_large=0.15,
            partial_fill_ratio_min=0.3,
            partial_fill_ratio_max=0.9,
            queue_position_factor=0.5,
            base_slippage_bps=0.5,
            depth_slippage_factor=0.1,
            scenario="optimistic",
        )
    
    @classmethod
    def realistic(cls) -> "ExecutionSimulatorConfig":
        """Create a realistic execution scenario.
        
        Realistic scenarios model typical market conditions with:
        - Moderate latency (50ms base, 20ms std)
        - Moderate partial fill probabilities
        - Moderate slippage (1.0 bps)
        
        This is the default scenario.
        
        Returns:
            ExecutionSimulatorConfig with realistic parameters.
        """
        return cls(
            base_latency_ms=50.0,
            latency_std_ms=20.0,
            partial_fill_prob_small=0.02,
            partial_fill_prob_medium=0.10,
            partial_fill_prob_large=0.30,
            partial_fill_ratio_min=0.3,
            partial_fill_ratio_max=0.9,
            queue_position_factor=0.5,
            base_slippage_bps=1.0,
            depth_slippage_factor=0.1,
            scenario="realistic",
        )
    
    @classmethod
    def pessimistic(cls) -> "ExecutionSimulatorConfig":
        """Create a pessimistic execution scenario.
        
        Pessimistic scenarios model adverse market conditions with:
        - Higher latency (100ms base, 50ms std)
        - Higher partial fill probabilities
        - Higher slippage (2.0 bps)
        
        Returns:
            ExecutionSimulatorConfig with pessimistic parameters.
        """
        return cls(
            base_latency_ms=100.0,
            latency_std_ms=50.0,
            partial_fill_prob_small=0.05,
            partial_fill_prob_medium=0.20,
            partial_fill_prob_large=0.50,
            partial_fill_ratio_min=0.3,
            partial_fill_ratio_max=0.9,
            queue_position_factor=0.5,
            base_slippage_bps=2.0,
            depth_slippage_factor=0.1,
            scenario="pessimistic",
        )
    
    @classmethod
    def from_scenario(cls, scenario: str) -> "ExecutionSimulatorConfig":
        """Create a configuration from a scenario name.
        
        Args:
            scenario: One of "optimistic", "realistic", or "pessimistic".
            
        Returns:
            ExecutionSimulatorConfig for the specified scenario.
            
        Raises:
            ValueError: If scenario is not a valid scenario name.
        """
        scenario_map = {
            "optimistic": cls.optimistic,
            "realistic": cls.realistic,
            "pessimistic": cls.pessimistic,
        }
        
        if scenario not in scenario_map:
            raise ValueError(
                f"Unknown scenario '{scenario}'. "
                f"Valid scenarios: {list(scenario_map.keys())}"
            )
        
        return scenario_map[scenario]()
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert configuration to a dictionary for serialization.
        
        Returns:
            Dictionary containing all configuration parameters.
        """
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ExecutionSimulatorConfig":
        """Create a configuration from a dictionary.
        
        Args:
            data: Dictionary containing configuration parameters.
            
        Returns:
            ExecutionSimulatorConfig instance.
            
        Raises:
            ValueError: If any parameter is invalid.
        """
        return cls(**data)
    
    def is_more_favorable_than(self, other: "ExecutionSimulatorConfig") -> bool:
        """Check if this configuration is more favorable than another.
        
        A configuration is more favorable if it has:
        - Lower latency (base and std)
        - Lower partial fill probabilities
        - Lower slippage
        
        Args:
            other: Another ExecutionSimulatorConfig to compare against.
            
        Returns:
            True if this configuration is strictly more favorable.
        """
        # Check latency (lower is better)
        latency_better = (
            self.base_latency_ms <= other.base_latency_ms and
            self.latency_std_ms <= other.latency_std_ms
        )
        
        # Check partial fill probabilities (lower is better)
        partial_fill_better = (
            self.partial_fill_prob_small <= other.partial_fill_prob_small and
            self.partial_fill_prob_medium <= other.partial_fill_prob_medium and
            self.partial_fill_prob_large <= other.partial_fill_prob_large
        )
        
        # Check slippage (lower is better)
        slippage_better = self.base_slippage_bps <= other.base_slippage_bps
        
        return latency_better and partial_fill_better and slippage_better


@dataclass
class SimulatedFill:
    """Result of simulated execution.
    
    Attributes:
        order_id: Unique identifier for the simulated order.
        filled_size: Amount of the order that was filled.
        fill_price: Price at which the order was filled (including slippage).
        slippage_bps: Slippage in basis points applied to the fill.
        latency_ms: Simulated latency in milliseconds.
        is_partial: Whether this was a partial fill.
        queue_position_effect: Effect of queue position on fill (for maker orders).
    """
    order_id: str
    filled_size: float
    fill_price: float
    slippage_bps: float
    latency_ms: float
    is_partial: bool
    queue_position_effect: float


@dataclass
class CalibrationResult:
    """Result of calibrating the execution simulator from live data.
    
    Contains statistics about the calibration process and the resulting
    parameter updates.
    
    Attributes:
        num_fills: Number of live fills used for calibration.
        latency_mean_ms: Calculated mean latency in milliseconds.
        latency_std_ms: Calculated standard deviation of latency.
        slippage_mean_bps: Calculated mean slippage in basis points.
        partial_fill_rate_small: Partial fill rate for small orders (<1% depth).
        partial_fill_rate_medium: Partial fill rate for medium orders (1-5% depth).
        partial_fill_rate_large: Partial fill rate for large orders (>5% depth).
        fills_by_size_bucket: Count of fills in each size bucket.
        parameters_updated: List of parameter names that were updated.
    """
    num_fills: int
    latency_mean_ms: float
    latency_std_ms: float
    slippage_mean_bps: float
    partial_fill_rate_small: float
    partial_fill_rate_medium: float
    partial_fill_rate_large: float
    fills_by_size_bucket: Dict[str, int]
    parameters_updated: List[str]


class ExecutionSimulator:
    """Simulates realistic execution behavior for backtests.
    
    This simulator models real exchange behavior including:
    - Partial fills based on order size relative to available liquidity
    - Latency drawn from a Gaussian distribution
    - Slippage based on order size and market depth
    - Queue position effects for maker orders
    
    Example:
        >>> config = ExecutionSimulatorConfig.realistic()
        >>> simulator = ExecutionSimulator(config)
        >>> simulator.seed(42)  # For reproducible results
        >>> fill = simulator.simulate_fill(
        ...     side="buy",
        ...     size=1.0,
        ...     price=50000.0,
        ...     bid_depth_usd=100000.0,
        ...     ask_depth_usd=100000.0,
        ...     spread_bps=2.0,
        ...     is_maker=False,
        ... )
        >>> print(f"Filled {fill.filled_size} at {fill.fill_price}")
    """
    
    def __init__(self, config: Optional[ExecutionSimulatorConfig] = None):
        """Initialize the execution simulator.
        
        Args:
            config: Configuration for execution simulation. If None, uses
                default realistic configuration.
        """
        self.config = config or ExecutionSimulatorConfig()
        self._rng = random.Random()
    
    def seed(self, seed: int) -> None:
        """Set the random seed for reproducible testing.
        
        Args:
            seed: Random seed value.
        """
        self._rng.seed(seed)
    
    def simulate_fill(
        self,
        side: str,
        size: float,
        price: float,
        bid_depth_usd: float,
        ask_depth_usd: float,
        spread_bps: float,
        is_maker: bool = False,
        base_slippage_bps: Optional[float] = None,
    ) -> SimulatedFill:
        """Simulate order execution.
        
        Simulates realistic execution behavior including partial fills,
        slippage, and latency based on order characteristics and market
        conditions.
        
        Args:
            side: Order side, either "buy" or "sell".
            size: Order size in base currency.
            price: Order price.
            bid_depth_usd: Available bid liquidity in USD.
            ask_depth_usd: Available ask liquidity in USD.
            spread_bps: Current spread in basis points.
            is_maker: Whether this is a maker order (limit order that adds
                liquidity). Maker orders have reduced partial fill probability
                and negative slippage (price improvement).
            base_slippage_bps: Optional override for base slippage in basis points.
                If None, uses the configured base_slippage_bps.
            
        Returns:
            SimulatedFill with execution details including filled size,
            fill price, slippage, latency, and whether it was a partial fill.
        """
        # Calculate order size relative to available depth
        relevant_depth = ask_depth_usd if side == "buy" else bid_depth_usd
        order_value = size * price
        size_ratio = order_value / relevant_depth if relevant_depth > 0 else 1.0
        
        # Determine partial fill probability based on size ratio
        # Small orders (<1% of depth) have lowest probability
        # Medium orders (1-5% of depth) have moderate probability
        # Large orders (>5% of depth) have highest probability
        if size_ratio < 0.01:
            partial_prob = self.config.partial_fill_prob_small
        elif size_ratio < 0.05:
            partial_prob = self.config.partial_fill_prob_medium
        else:
            partial_prob = self.config.partial_fill_prob_large
        
        # Maker orders are less likely to partial fill (50% reduction)
        if is_maker:
            partial_prob *= 0.5
        
        # Check for partial fill
        is_partial = self._rng.random() < partial_prob
        if is_partial:
            fill_ratio = self._rng.uniform(
                self.config.partial_fill_ratio_min,
                self.config.partial_fill_ratio_max
            )
            filled_size = size * fill_ratio
        else:
            filled_size = size
        
        # Calculate slippage
        # Base slippage plus additional slippage based on order size relative to depth
        # Formula: slippage = base + (size_ratio × depth_factor × 100)
        slippage_bps = float(base_slippage_bps) if base_slippage_bps is not None else self.config.base_slippage_bps
        slippage_bps += size_ratio * self.config.depth_slippage_factor * 100
        
        # Maker orders have negative slippage (price improvement)
        # They capture some of the spread
        if is_maker:
            slippage_bps = -spread_bps / 4  # Capture 25% of spread
        
        # Apply slippage to price
        # Buy orders pay more (positive slippage increases price)
        # Sell orders receive less (positive slippage decreases price)
        if side == "buy":
            fill_price = price * (1 + slippage_bps / 10000)
        else:
            fill_price = price * (1 - slippage_bps / 10000)
        
        # Simulate latency from Gaussian distribution
        # Clamped to minimum 1.0ms to ensure realistic values
        latency_ms = max(1.0, self._rng.gauss(
            self.config.base_latency_ms,
            self.config.latency_std_ms
        ))
        
        # Queue position effect (for maker orders only)
        # Represents the uncertainty of queue position affecting fill probability
        queue_effect = 0.0
        if is_maker:
            queue_effect = self._rng.random() * self.config.queue_position_factor
        
        return SimulatedFill(
            order_id=f"sim_{uuid4().hex[:8]}",
            filled_size=filled_size,
            fill_price=fill_price,
            slippage_bps=slippage_bps,
            latency_ms=latency_ms,
            is_partial=is_partial,
            queue_position_effect=queue_effect,
        )

    def calibrate_from_live(
        self,
        live_fills: List[Dict[str, Any]],
    ) -> CalibrationResult:
        """Calibrate simulator parameters from live execution data.
        
        Analyzes live fill data to update the simulator configuration with
        realistic parameters based on actual exchange behavior. This includes:
        - Latency distribution (mean and standard deviation)
        - Slippage (mean basis points)
        - Partial fill rates by order size bucket
        
        Args:
            live_fills: List of live fill dictionaries. Each fill should contain:
                - latency_ms (float): Execution latency in milliseconds
                - slippage_bps (float): Slippage in basis points
                - is_partial (bool): Whether the fill was partial
                - size_ratio (float, optional): Order size relative to depth
                  (used for bucketing). If not provided, fill is not counted
                  toward partial fill rate calculation.
                
        Returns:
            CalibrationResult containing statistics about the calibration
            and which parameters were updated.
            
        Example:
            >>> simulator = ExecutionSimulator()
            >>> live_fills = [
            ...     {"latency_ms": 45.0, "slippage_bps": 0.8, "is_partial": False, "size_ratio": 0.005},
            ...     {"latency_ms": 55.0, "slippage_bps": 1.2, "is_partial": True, "size_ratio": 0.03},
            ...     {"latency_ms": 48.0, "slippage_bps": 1.0, "is_partial": False, "size_ratio": 0.08},
            ... ]
            >>> result = simulator.calibrate_from_live(live_fills)
            >>> print(f"Calibrated from {result.num_fills} fills")
            >>> print(f"New latency: {simulator.config.base_latency_ms:.1f}ms")
        """
        # Handle empty list case
        if not live_fills:
            return CalibrationResult(
                num_fills=0,
                latency_mean_ms=self.config.base_latency_ms,
                latency_std_ms=self.config.latency_std_ms,
                slippage_mean_bps=self.config.base_slippage_bps,
                partial_fill_rate_small=self.config.partial_fill_prob_small,
                partial_fill_rate_medium=self.config.partial_fill_prob_medium,
                partial_fill_rate_large=self.config.partial_fill_prob_large,
                fills_by_size_bucket={"small": 0, "medium": 0, "large": 0},
                parameters_updated=[],
            )
        
        parameters_updated: List[str] = []
        
        # Calculate actual latency distribution
        latencies = [
            f.get("latency_ms", self.config.base_latency_ms) 
            for f in live_fills
        ]
        latency_mean = sum(latencies) / len(latencies)
        
        # Calculate standard deviation
        if len(latencies) > 1:
            variance = sum((l - latency_mean) ** 2 for l in latencies) / len(latencies)
            latency_std = math.sqrt(variance)
        else:
            # Single fill - use existing std or a reasonable default
            latency_std = self.config.latency_std_ms
        
        # Update latency parameters
        self.config.base_latency_ms = latency_mean
        parameters_updated.append("base_latency_ms")
        self.config.latency_std_ms = latency_std
        parameters_updated.append("latency_std_ms")
        
        # Calculate actual slippage
        slippages = [
            f.get("slippage_bps", self.config.base_slippage_bps) 
            for f in live_fills
        ]
        slippage_mean = sum(slippages) / len(slippages)
        
        # Update slippage parameter
        self.config.base_slippage_bps = slippage_mean
        parameters_updated.append("base_slippage_bps")
        
        # Calculate partial fill rates by size bucket
        # Bucket fills by size_ratio: small (<1%), medium (1-5%), large (>5%)
        small_fills: List[Dict[str, Any]] = []
        medium_fills: List[Dict[str, Any]] = []
        large_fills: List[Dict[str, Any]] = []
        
        for fill in live_fills:
            size_ratio = fill.get("size_ratio")
            if size_ratio is None:
                # Skip fills without size_ratio for bucketing
                continue
            
            if size_ratio < 0.01:
                small_fills.append(fill)
            elif size_ratio < 0.05:
                medium_fills.append(fill)
            else:
                large_fills.append(fill)
        
        # Calculate partial fill rates for each bucket
        partial_rate_small = self._calculate_partial_rate(
            small_fills, self.config.partial_fill_prob_small
        )
        partial_rate_medium = self._calculate_partial_rate(
            medium_fills, self.config.partial_fill_prob_medium
        )
        partial_rate_large = self._calculate_partial_rate(
            large_fills, self.config.partial_fill_prob_large
        )
        
        # Update partial fill probabilities if we have enough data
        # Require at least 5 fills in a bucket to update its probability
        MIN_FILLS_FOR_UPDATE = 5
        
        if len(small_fills) >= MIN_FILLS_FOR_UPDATE:
            self.config.partial_fill_prob_small = partial_rate_small
            parameters_updated.append("partial_fill_prob_small")
        
        if len(medium_fills) >= MIN_FILLS_FOR_UPDATE:
            self.config.partial_fill_prob_medium = partial_rate_medium
            parameters_updated.append("partial_fill_prob_medium")
        
        if len(large_fills) >= MIN_FILLS_FOR_UPDATE:
            self.config.partial_fill_prob_large = partial_rate_large
            parameters_updated.append("partial_fill_prob_large")
        
        return CalibrationResult(
            num_fills=len(live_fills),
            latency_mean_ms=latency_mean,
            latency_std_ms=latency_std,
            slippage_mean_bps=slippage_mean,
            partial_fill_rate_small=partial_rate_small,
            partial_fill_rate_medium=partial_rate_medium,
            partial_fill_rate_large=partial_rate_large,
            fills_by_size_bucket={
                "small": len(small_fills),
                "medium": len(medium_fills),
                "large": len(large_fills),
            },
            parameters_updated=parameters_updated,
        )
    
    def _calculate_partial_rate(
        self,
        fills: List[Dict[str, Any]],
        default_rate: float,
    ) -> float:
        """Calculate partial fill rate from a list of fills.
        
        Args:
            fills: List of fill dictionaries with 'is_partial' field.
            default_rate: Default rate to return if no fills provided.
            
        Returns:
            Partial fill rate as a float between 0 and 1.
        """
        if not fills:
            return default_rate
        
        partial_count = sum(1 for f in fills if f.get("is_partial", False))
        return partial_count / len(fills)
