"""
Hysteresis Tracker - State tracking with entry/exit bands to prevent flip-flopping

This module implements the HysteresisTracker class that provides stable state
transitions by requiring values to cross entry thresholds to change state,
and exit thresholds to revert.

Implements Requirements 2.3 (Profile Stability - Hysteresis)
"""

from dataclasses import dataclass
from typing import Dict, Tuple, Optional, TYPE_CHECKING
import logging

if TYPE_CHECKING:
    from .router_config import RouterConfig

logger = logging.getLogger(__name__)


# Valid volatility regime states
VOLATILITY_REGIMES = frozenset(["low", "normal", "high"])

# Valid trend direction states
TREND_DIRECTIONS = frozenset(["up", "down", "flat"])


@dataclass
class HysteresisState:
    """State information for a tracked category."""
    current_state: str
    last_value: float
    transition_count: int = 0


class HysteresisTracker:
    """
    Track state with hysteresis to prevent flip-flopping.
    
    This class implements hysteresis bands for threshold-based categories
    as specified in Requirement 2.3:
    - Volatility regime: entry at 0.65/1.35, exit at 0.75/1.25
    - Trend direction: entry at ±0.0012, exit at ±0.0008
    
    The key principle is that state transitions require crossing different
    thresholds for entry vs exit, creating a "dead zone" that prevents
    rapid oscillation when values hover near a threshold.
    
    For upward transitions (e.g., normal -> high volatility):
        - Value must exceed entry_threshold to transition
    For downward transitions (e.g., high -> normal volatility):
        - Value must fall below exit_threshold to transition
    """
    
    def __init__(self):
        """Initialize HysteresisTracker with empty state."""
        self._states: Dict[Tuple[str, str], HysteresisState] = {}
    
    def get_state(
        self,
        symbol: str,
        category: str,
        value: float,
        entry_threshold: float,
        exit_threshold: float,
        high_state: str,
        low_state: str,
        default_state: str
    ) -> str:
        """
        Get state with hysteresis.
        
        This method implements the core hysteresis logic:
        - If currently in low_state: need to exceed entry_threshold to transition to high_state
        - If currently in high_state: need to fall below exit_threshold to transition to low_state
        
        Args:
            symbol: Trading symbol (e.g., "BTC-USDT")
            category: Category being tracked (e.g., "vol_regime_high", "trend_up")
            value: Current value to evaluate
            entry_threshold: Threshold to cross to enter high_state
            exit_threshold: Threshold to cross to exit high_state (return to low_state)
            high_state: State name when value is high
            low_state: State name when value is low
            default_state: Initial state if no history exists
            
        Returns:
            Current state after applying hysteresis logic
        """
        key = (symbol, category)
        
        # Get or initialize state
        if key not in self._states:
            self._states[key] = HysteresisState(
                current_state=default_state,
                last_value=value
            )
        
        state_info = self._states[key]
        current_state = state_info.current_state
        old_state = current_state
        
        # Apply hysteresis logic
        if current_state == low_state:
            # In low state - need to exceed entry threshold to transition up
            if value > entry_threshold:
                current_state = high_state
                state_info.transition_count += 1
                logger.debug(
                    f"Hysteresis [{symbol}][{category}]: {low_state} -> {high_state} "
                    f"(value={value:.6f} > entry={entry_threshold:.6f})"
                )
        elif current_state == high_state:
            # In high state - need to fall below exit threshold to transition down
            if value < exit_threshold:
                current_state = low_state
                state_info.transition_count += 1
                logger.debug(
                    f"Hysteresis [{symbol}][{category}]: {high_state} -> {low_state} "
                    f"(value={value:.6f} < exit={exit_threshold:.6f})"
                )
        else:
            # In default/other state - check both directions
            if value > entry_threshold:
                current_state = high_state
                state_info.transition_count += 1
            elif value < exit_threshold:
                current_state = low_state
                state_info.transition_count += 1
        
        # Update state
        state_info.current_state = current_state
        state_info.last_value = value
        
        return current_state
    
    def get_volatility_regime(
        self,
        symbol: str,
        atr_ratio: float,
        config: "RouterConfig"
    ) -> str:
        """
        Get volatility regime with hysteresis.
        
        Applies hysteresis bands for volatility regime classification:
        - Low volatility: atr_ratio < 0.65 (entry), exits when > 0.75
        - High volatility: atr_ratio > 1.35 (entry), exits when < 1.25
        - Normal: between the bands
        
        Args:
            symbol: Trading symbol
            atr_ratio: Current ATR ratio (atr / baseline)
            config: RouterConfig with hysteresis band settings
            
        Returns:
            Volatility regime: "low", "normal", or "high"
        """
        # Check for high volatility
        entry_high, exit_high = config.vol_regime_high_band
        high_state = self.get_state(
            symbol=symbol,
            category="vol_regime_high",
            value=atr_ratio,
            entry_threshold=entry_high,
            exit_threshold=exit_high,
            high_state="high",
            low_state="not_high",
            default_state="not_high"
        )
        
        if high_state == "high":
            return "high"
        
        # Check for low volatility
        entry_low, exit_low = config.vol_regime_low_band
        # For low band, we invert the logic: enter low when value drops below entry,
        # exit low when value rises above exit
        low_state = self.get_state(
            symbol=symbol,
            category="vol_regime_low",
            value=atr_ratio,
            entry_threshold=exit_low,  # Inverted: exit becomes entry for "not_low"
            exit_threshold=entry_low,  # Inverted: entry becomes exit for "not_low"
            high_state="not_low",
            low_state="low",
            default_state="not_low"
        )
        
        if low_state == "low":
            return "low"
        
        return "normal"
    
    def get_trend_direction(
        self,
        symbol: str,
        ema_spread_pct: float,
        config: "RouterConfig"
    ) -> str:
        """
        Get trend direction with hysteresis.
        
        Applies hysteresis bands for trend direction classification:
        - Up trend: ema_spread_pct > +0.0012 (entry), exits when < +0.0008
        - Down trend: ema_spread_pct < -0.0012 (entry), exits when > -0.0008
        - Flat: between the bands
        
        Args:
            symbol: Trading symbol
            ema_spread_pct: Current EMA spread percentage
            config: RouterConfig with trend direction band settings
            
        Returns:
            Trend direction: "up", "down", or "flat"
        """
        entry_threshold, exit_threshold = config.trend_direction_band
        
        # Check for upward trend
        up_state = self.get_state(
            symbol=symbol,
            category="trend_up",
            value=ema_spread_pct,
            entry_threshold=entry_threshold,
            exit_threshold=exit_threshold,
            high_state="up",
            low_state="not_up",
            default_state="not_up"
        )
        
        if up_state == "up":
            return "up"
        
        # Check for downward trend (using negative thresholds)
        down_state = self.get_state(
            symbol=symbol,
            category="trend_down",
            value=-ema_spread_pct,  # Negate to use same logic
            entry_threshold=entry_threshold,
            exit_threshold=exit_threshold,
            high_state="down",
            low_state="not_down",
            default_state="not_down"
        )
        
        if down_state == "down":
            return "down"
        
        return "flat"
    
    def get_state_info(self, symbol: str, category: str) -> Optional[HysteresisState]:
        """
        Get state information for a symbol/category pair.
        
        Args:
            symbol: Trading symbol
            category: Category being tracked
            
        Returns:
            HysteresisState if exists, None otherwise
        """
        key = (symbol, category)
        return self._states.get(key)
    
    def reset_state(self, symbol: str, category: str) -> None:
        """
        Reset state for a symbol/category pair.
        
        Args:
            symbol: Trading symbol
            category: Category to reset
        """
        key = (symbol, category)
        if key in self._states:
            del self._states[key]
            logger.debug(f"Hysteresis state reset: [{symbol}][{category}]")
    
    def reset_symbol(self, symbol: str) -> None:
        """
        Reset all states for a symbol.
        
        Args:
            symbol: Trading symbol to reset
        """
        keys_to_remove = [key for key in self._states if key[0] == symbol]
        for key in keys_to_remove:
            del self._states[key]
        logger.debug(f"Hysteresis states reset for symbol: {symbol}")
    
    def reset_all(self) -> None:
        """Reset all tracked states."""
        self._states.clear()
        logger.debug("All hysteresis states reset")
    
    def get_transition_count(self, symbol: str, category: str) -> int:
        """
        Get the number of state transitions for a symbol/category pair.
        
        Args:
            symbol: Trading symbol
            category: Category being tracked
            
        Returns:
            Number of transitions, 0 if not tracked
        """
        key = (symbol, category)
        state_info = self._states.get(key)
        return state_info.transition_count if state_info else 0
    
    def get_all_states(self) -> Dict[Tuple[str, str], str]:
        """
        Get all current states.
        
        Returns:
            Dictionary mapping (symbol, category) to current state
        """
        return {key: info.current_state for key, info in self._states.items()}
