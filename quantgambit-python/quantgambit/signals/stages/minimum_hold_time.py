"""
Minimum Hold Time Enforcer for Trading Loss Prevention.

This module implements strategy-specific minimum hold times to prevent
premature exits that don't allow the trading edge to materialize.

Requirements:
- 3.1: Record minimum hold time when position is opened
- 3.2: Defer non-safety exits until minimum hold time is reached
- 3.3: Allow normal exit logic after minimum hold time
- 3.4: Configure minimum hold times per strategy
- 3.5: Override minimum hold time for stop loss (safety exits)
- 3.6: Display time remaining until minimum hold time is satisfied
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from quantgambit.deeptrader_core.types import ExitDecision, ExitType


# =============================================================================
# STRATEGY_MIN_HOLD_TIMES Configuration (Requirement 3.4)
# =============================================================================

STRATEGY_MIN_HOLD_TIMES: dict[str, float] = {
    "mean_reversion_fade": 120.0,  # 2 minutes - allow mean reversion to work
    "trend_following": 300.0,      # 5 minutes - trends need time to develop
    "default": 60.0,               # 1 minute fallback for unknown strategies
}


@dataclass
class MinimumHoldTimeConfig:
    """Configuration for minimum hold time enforcement."""
    
    # Strategy-specific hold times (seconds)
    strategy_hold_times: dict[str, float] = None
    
    # Default hold time for unknown strategies
    default_hold_time: float = 60.0
    
    def __post_init__(self):
        if self.strategy_hold_times is None:
            self.strategy_hold_times = STRATEGY_MIN_HOLD_TIMES.copy()
    
    def get_min_hold_time(self, strategy_id: str) -> float:
        """
        Get minimum hold time for a strategy.
        
        Args:
            strategy_id: The strategy identifier
            
        Returns:
            Minimum hold time in seconds
        """
        return self.strategy_hold_times.get(
            strategy_id, 
            self.strategy_hold_times.get("default", self.default_hold_time)
        )


class MinimumHoldTimeEnforcer:
    """
    Enforces minimum hold times before allowing exits.
    
    This enforcer ensures positions are held long enough for the trading
    edge to materialize. Safety exits (stop loss, hard stop) always bypass
    the minimum hold time requirement.
    
    Requirements:
    - 3.2: Defer non-safety exits until minimum hold time is reached
    - 3.3: Allow normal exit logic after minimum hold time
    - 3.5: Override minimum hold time for stop loss (safety exits)
    """
    
    def __init__(self, config: Optional[MinimumHoldTimeConfig] = None):
        """
        Initialize the enforcer.
        
        Args:
            config: Configuration for hold times. Uses defaults if None.
        """
        self.config = config or MinimumHoldTimeConfig()
    
    def should_allow_exit(
        self,
        position: dict,
        exit_decision: "ExitDecision",
    ) -> Tuple[bool, Optional[str]]:
        """
        Check if exit should be allowed based on hold time.
        
        Safety exits (ExitType.SAFETY) always bypass the minimum hold time.
        Invalidation exits (ExitType.INVALIDATION) must wait for min_hold.
        
        Args:
            position: Position dict with 'strategy_id', 'opened_at' fields
            exit_decision: The exit decision being evaluated
            
        Returns:
            Tuple of (allowed: bool, reason: Optional[str])
            - allowed: True if exit should proceed, False if deferred
            - reason: Explanation string (None if allowed without special reason)
            
        Requirements:
        - 3.2: Defer non-safety exits until minimum hold time is reached
        - 3.3: Allow normal exit logic after minimum hold time
        - 3.5: Override minimum hold time for stop loss (safety exits)
        """
        from quantgambit.deeptrader_core.types import ExitType
        
        # Safety exits always allowed (Requirement 3.5)
        if exit_decision.exit_type == ExitType.SAFETY:
            return True, "safety_exit_bypass"
        
        # Get strategy-specific minimum hold time
        strategy_id = position.get("strategy_id", "default")
        min_hold = self.config.get_min_hold_time(strategy_id)
        
        # Check if position has opened_at timestamp
        opened_at = position.get("opened_at")
        if opened_at is None:
            # No timestamp - allow exit (can't enforce without data)
            return True, "no_opened_at"
        
        # Calculate hold time
        hold_time = time.time() - opened_at
        
        # Check if minimum hold time is met (Requirement 3.2, 3.3)
        if hold_time < min_hold:
            time_remaining = min_hold - hold_time
            return False, f"min_hold_not_met: {hold_time:.1f}s < {min_hold:.1f}s (remaining: {time_remaining:.1f}s)"
        
        # Minimum hold time satisfied
        return True, None
    
    def get_time_remaining(
        self,
        position: dict,
    ) -> Optional[float]:
        """
        Get time remaining until minimum hold time is satisfied.
        
        Args:
            position: Position dict with 'strategy_id', 'opened_at' fields
            
        Returns:
            Time remaining in seconds, or None if already satisfied or no data
            
        Requirement 3.6: Display time remaining until minimum hold time is satisfied
        """
        opened_at = position.get("opened_at")
        if opened_at is None:
            return None
        
        strategy_id = position.get("strategy_id", "default")
        min_hold = self.config.get_min_hold_time(strategy_id)
        
        hold_time = time.time() - opened_at
        time_remaining = min_hold - hold_time
        
        if time_remaining <= 0:
            return None  # Already satisfied
        
        return time_remaining
    
    def get_hold_time_info(
        self,
        position: dict,
    ) -> dict:
        """
        Get comprehensive hold time information for display.
        
        Args:
            position: Position dict with 'strategy_id', 'opened_at' fields
            
        Returns:
            Dict with hold time details for dashboard display
            
        Requirement 3.6: Display time remaining until minimum hold time is satisfied
        """
        strategy_id = position.get("strategy_id", "default")
        min_hold = self.config.get_min_hold_time(strategy_id)
        
        opened_at = position.get("opened_at")
        if opened_at is None:
            return {
                "strategy_id": strategy_id,
                "min_hold_time_sec": min_hold,
                "hold_time_sec": None,
                "time_remaining_sec": None,
                "min_hold_satisfied": True,  # Can't enforce without data
            }
        
        hold_time = time.time() - opened_at
        time_remaining = max(0, min_hold - hold_time)
        
        return {
            "strategy_id": strategy_id,
            "min_hold_time_sec": min_hold,
            "hold_time_sec": round(hold_time, 1),
            "time_remaining_sec": round(time_remaining, 1) if time_remaining > 0 else None,
            "min_hold_satisfied": hold_time >= min_hold,
        }
