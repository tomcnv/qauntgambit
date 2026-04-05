"""
ExecutionPolicy - Determines execution approach based on strategy intent.

This module separates execution assumptions (maker/taker probabilities, urgency)
from strategy logic, preventing hardcoded execution parameters from rotting over time.

Requirements: V2 Proposal Section 5 - Execution Policy Integration
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional, Set


# Valid urgency levels
VALID_URGENCIES: Set[str] = {"immediate", "patient", "passive"}


@dataclass
class ExecutionPlan:
    """Execution plan for a trade.
    
    Attributes:
        entry_urgency: Urgency level for entry ("immediate", "patient", "passive")
        exit_urgency: Urgency level for exit ("immediate", "patient", "passive")
        p_entry_maker: Probability of maker fill on entry (0 to 1)
        p_exit_maker: Probability of maker fill on exit (0 to 1)
        entry_timeout_ms: Timeout for entry order in milliseconds
        exit_timeout_ms: Timeout for exit order in milliseconds
    """
    entry_urgency: str  # "immediate", "patient", "passive"
    exit_urgency: str   # "immediate", "patient", "passive"
    
    # Derived probabilities
    p_entry_maker: float  # Probability of maker fill on entry
    p_exit_maker: float   # Probability of maker fill on exit
    
    # Fallback behavior
    entry_timeout_ms: int
    exit_timeout_ms: int
    
    def __post_init__(self):
        """Validate execution plan parameters (FIX #3: defensive programming)."""
        # Validate probabilities are in [0, 1]
        for name, p in (("p_entry_maker", self.p_entry_maker), ("p_exit_maker", self.p_exit_maker)):
            if not (0.0 <= p <= 1.0):
                raise ValueError(f"{name} must be in [0, 1], got {p}")
        
        # Validate urgency levels
        if self.entry_urgency not in VALID_URGENCIES:
            raise ValueError(f"entry_urgency must be one of {VALID_URGENCIES}, got '{self.entry_urgency}'")
        if self.exit_urgency not in VALID_URGENCIES:
            raise ValueError(f"exit_urgency must be one of {VALID_URGENCIES}, got '{self.exit_urgency}'")
        
        # Validate timeouts are positive
        if self.entry_timeout_ms <= 0:
            raise ValueError(f"entry_timeout_ms must be > 0, got {self.entry_timeout_ms}")
        if self.exit_timeout_ms <= 0:
            raise ValueError(f"exit_timeout_ms must be > 0, got {self.exit_timeout_ms}")


class ExecutionPolicy:
    """Determines execution approach based on strategy intent.
    
    This class encapsulates execution assumptions (maker/taker mix, urgency levels)
    that were previously hardcoded in strategies. By centralizing these decisions,
    we can:
    1. Update execution behavior without modifying strategy code
    2. Adapt to changing market conditions
    3. Ensure consistent cost calculations across strategies
    
    Phase 1 Implementation: Returns fixed plans based on strategy type.
    Future: Will adapt to market conditions (spread, depth, volatility).
    
    NOTE: This is the canonical source for setup type inference. Other modules
    (e.g., EVGateStage) should use infer_setup_type() from this class to avoid
    drift between duplicate implementations.
    """
    
    def plan_execution(
        self,
        strategy_id: str,
        setup_type: Optional[str] = None,
        market_state: Optional[dict] = None,
    ) -> ExecutionPlan:
        """Create execution plan based on strategy and market conditions.
        
        Args:
            strategy_id: Strategy identifier (e.g., "mean_reversion_fade")
            setup_type: Setup type if different from strategy_id (e.g., "mean_reversion", "breakout")
            market_state: Optional market state for adaptive planning (Phase 2)
            
        Returns:
            ExecutionPlan with urgency levels and maker/taker probabilities.
        """
        # If the bot is running market orders, maker probabilities are fiction and
        # will under-estimate costs in EV/cost models. Force taker semantics.
        if os.getenv("EXECUTION_POLICY_FORCE_TAKER", "").lower() in {"1", "true", "yes"}:
            return ExecutionPlan(
                entry_urgency="immediate",
                exit_urgency="immediate",
                p_entry_maker=0.0,
                p_exit_maker=0.0,
                entry_timeout_ms=500,
                exit_timeout_ms=1000,
            )

        # Determine setup type from strategy_id if not provided
        if setup_type is None:
            setup_type = self.infer_setup_type(strategy_id)
        
        # Phase 1: Fixed plans based on setup type
        # Phase 2 will add market-state-adaptive logic
        
        if setup_type == "mean_reversion":
            # FIX #1: Mean reversion: immediate/taker-biased entry (need quick fill on reversal),
            # patient/maker-biased exit at POC target (limit order at target price)
            return ExecutionPlan(
                entry_urgency="immediate",
                exit_urgency="patient",
                p_entry_maker=0.1,          # Usually taker (90% taker, 10% maker)
                p_exit_maker=0.6,           # Often fills at limit (60% maker, 40% taker)
                entry_timeout_ms=500,
                exit_timeout_ms=30000,
            )
        
        elif setup_type == "breakout":
            # Breakout: immediate entry and exit (chase momentum)
            # FIX #6: p_exit_maker reduced from 0.2 to 0.1 since exit is "immediate"
            return ExecutionPlan(
                entry_urgency="immediate",
                exit_urgency="immediate",
                p_entry_maker=0.0,  # Always taker
                p_exit_maker=0.1,   # Usually taker (10% maker, 90% taker) - immediate exit
                entry_timeout_ms=200,
                exit_timeout_ms=1000,
            )
        
        elif setup_type == "trend_pullback":
            # Trend pullback: patient entry on pullback, immediate exit on invalidation
            return ExecutionPlan(
                entry_urgency="patient",
                exit_urgency="immediate",
                p_entry_maker=0.4,  # Often maker (40% maker, 60% taker)
                p_exit_maker=0.1,   # Usually taker (10% maker, 90% taker)
                entry_timeout_ms=2000,
                exit_timeout_ms=500,
            )
        
        elif setup_type == "low_vol_grind":
            # Low volatility grind: passive entry and exit (willing to wait for fills)
            # NOTE: These probabilities assume system genuinely waits and doesn't chase.
            # If frequently converting to taker due to timeout, these should drop.
            return ExecutionPlan(
                entry_urgency="passive",
                exit_urgency="passive",
                p_entry_maker=0.7,  # Mostly maker (70% maker, 30% taker)
                p_exit_maker=0.7,   # Mostly maker (70% maker, 30% taker)
                entry_timeout_ms=5000,
                exit_timeout_ms=5000,
            )
        
        else:
            # Default: conservative assumptions (taker entry, mixed exit)
            return ExecutionPlan(
                entry_urgency="immediate",
                exit_urgency="patient",
                p_entry_maker=0.0,  # Assume taker
                p_exit_maker=0.5,   # 50/50 mix
                entry_timeout_ms=1000,
                exit_timeout_ms=2000,
            )
    
    def infer_setup_type(self, strategy_id: str) -> str:
        """Infer setup type from strategy_id.
        
        This is the CANONICAL source for setup type inference.
        Other modules should call this method rather than duplicating the logic.
        
        FIX #5: Single source of truth for strategy -> setup_type mapping.
        
        Args:
            strategy_id: Strategy identifier
            
        Returns:
            Setup type string: "mean_reversion", "breakout", "trend_pullback", 
            "low_vol_grind", or "unknown"
        """
        strategy_id_lower = strategy_id.lower()
        
        if "mean_reversion" in strategy_id_lower or "fade" in strategy_id_lower:
            return "mean_reversion"
        elif "breakout" in strategy_id_lower or "momentum" in strategy_id_lower:
            return "breakout"
        elif "pullback" in strategy_id_lower or "trend" in strategy_id_lower:
            return "trend_pullback"
        elif "low_vol" in strategy_id_lower or "grind" in strategy_id_lower:
            return "low_vol_grind"
        else:
            return "unknown"
    
    # Backward compatibility alias
    _infer_setup_type = infer_setup_type


def calculate_expected_fees_bps(
    fee_model,
    execution_plan: ExecutionPlan,
    entry_price: float,
    exit_price: float,
    size: float,
) -> float:
    """Calculate expected fees accounting for maker/taker probabilities.
    
    FIX #2: Compute per-leg bps and sum them, each normalized by its own leg notional.
    This avoids distortion in high-R setups where exit_price differs materially from entry_price.
    
    This function computes the expected fee cost based on the probability
    of getting maker vs taker fills, rather than assuming best-case or
    worst-case scenarios.
    
    Args:
        fee_model: FeeModel instance
        execution_plan: ExecutionPlan with maker/taker probabilities
        entry_price: Entry price
        exit_price: Exit price
        size: Position size
        
    Returns:
        Expected fees in basis points (sum of entry_bps + exit_bps)
        
    Requirements: V2 Proposal Section 5 - Expected Fee Calculation
    """
    # Entry expected fee (in currency units)
    entry_fee_maker = fee_model.calculate_entry_fee(size, entry_price, is_maker=True)
    entry_fee_taker = fee_model.calculate_entry_fee(size, entry_price, is_maker=False)
    expected_entry_fee = (
        execution_plan.p_entry_maker * entry_fee_maker +
        (1 - execution_plan.p_entry_maker) * entry_fee_taker
    )
    
    # Exit expected fee (in currency units)
    exit_fee_maker = fee_model.calculate_exit_fee(size, exit_price, is_maker=True)
    exit_fee_taker = fee_model.calculate_exit_fee(size, exit_price, is_maker=False)
    expected_exit_fee = (
        execution_plan.p_exit_maker * exit_fee_maker +
        (1 - execution_plan.p_exit_maker) * exit_fee_taker
    )
    
    # FIX #2: Convert each leg to bps using its own notional
    # This makes "fee_bps" match the intuitive "bps per leg" definition
    # and avoids distortion in high-R or volatile moves
    entry_notional = size * entry_price
    exit_notional = size * exit_price
    
    entry_fee_bps = (expected_entry_fee / entry_notional) * 10000.0 if entry_notional > 0 else 0.0
    exit_fee_bps = (expected_exit_fee / exit_notional) * 10000.0 if exit_notional > 0 else 0.0
    
    return entry_fee_bps + exit_fee_bps
