"""
Profile Stability Manager - TTL and switch margin enforcement for stable profile selection

This module implements the ProfileStabilityManager class that provides stable profile
selection by enforcing:
- Profile TTL (minimum time before switching)
- Switch margin (score difference required to switch)
- Safety disqualifier bypass (immediate switching for unsafe conditions)

Implements Requirements 2.1, 2.2, 2.4, 2.5, 2.6 (Profile Stability)
"""

import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Any, TYPE_CHECKING

if TYPE_CHECKING:
    from .router_config import RouterConfig

logger = logging.getLogger(__name__)


# Safety disqualifier conditions that bypass TTL
SAFETY_DISQUALIFIERS = frozenset([
    "spread_too_wide",
    "depth_too_low",
    "data_stale",
    "risk_mode_off",
    "book_age_exceeded",
    "trade_age_exceeded",
    "tps_too_low",
])


@dataclass
class ProfileSelection:
    """Information about a profile selection."""
    profile_id: str
    selected_at: float  # Unix timestamp
    score: float
    switch_count: int = 0  # Number of times this symbol has switched profiles


@dataclass
class StabilityMetrics:
    """Metrics for profile stability per symbol."""
    switch_count: int = 0
    durations: List[float] = field(default_factory=list)
    current_profile_id: Optional[str] = None
    current_profile_selected_at: Optional[float] = None
    current_profile_score: float = 0.0


class ProfileStabilityManager:
    """
    Manage profile TTL and switching logic for stable profile selection.
    
    This class implements the stability mechanisms specified in Requirement 2:
    - Profile TTL per symbol (Requirement 2.1)
    - TTL enforcement preventing premature switching (Requirement 2.2)
    - Switch margin enforcement (Requirement 2.4)
    - Safety disqualifier bypass (Requirement 2.5)
    - Metrics tracking (Requirement 2.6)
    
    Usage:
        manager = ProfileStabilityManager(config)
        
        # Check if switch is allowed
        if manager.should_switch(symbol, new_profile_id, new_score, current_time):
            manager.record_selection(symbol, new_profile_id, new_score, current_time)
    """
    
    def __init__(self, config: "RouterConfig"):
        """
        Initialize ProfileStabilityManager.
        
        Args:
            config: RouterConfig with stability parameters
        """
        self.config = config
        self._active_profiles: Dict[str, ProfileSelection] = {}
        self._metrics: Dict[str, StabilityMetrics] = defaultdict(StabilityMetrics)
    
    def should_switch(
        self,
        symbol: str,
        new_profile_id: str,
        new_score: float,
        current_live_score: Optional[float] = None,
        current_time: Optional[float] = None,
        safety_disqualified: bool = False,
        safety_reasons: Optional[List[str]] = None
    ) -> bool:
        """
        Determine if profile should switch.
        
        Implements Requirements 2.1, 2.2, 2.4, 2.5:
        - Returns True if no current profile (first selection)
        - Returns True if safety disqualifier triggered (bypasses TTL)
        - Returns False if within TTL period
        - Returns True if TTL expired AND new score exceeds current by switch_margin
        
        Args:
            symbol: Trading symbol (e.g., "BTC-USDT")
            new_profile_id: ID of the new profile being considered
            new_score: Score of the new profile
            current_time: Current Unix timestamp (defaults to time.time())
            safety_disqualified: Whether a safety disqualifier has triggered
            safety_reasons: List of safety disqualifier reasons (for logging)
            
        Returns:
            True if profile switch should occur, False otherwise
        """
        if current_time is None:
            current_time = time.time()
        
        # No current profile - allow selection
        if symbol not in self._active_profiles:
            logger.debug(
                f"[{symbol}] No active profile, allowing selection of {new_profile_id}"
            )
            return True
        
        current_selection = self._active_profiles[symbol]
        current_profile_id = current_selection.profile_id
        current_score = (
            float(current_live_score)
            if current_live_score is not None
            else current_selection.score
        )
        selected_at = current_selection.selected_at
        
        # Safety disqualifier bypasses TTL (Requirement 2.5)
        if safety_disqualified:
            reasons_str = ", ".join(safety_reasons) if safety_reasons else "unknown"
            logger.info(
                f"[{symbol}] Safety disqualifier triggered ({reasons_str}), "
                f"allowing immediate switch from {current_profile_id} to {new_profile_id}"
            )
            return True
        
        # Check TTL (Requirement 2.1, 2.2)
        time_active = current_time - selected_at
        if time_active < self.config.min_profile_ttl_sec:
            logger.info(
                f"[{symbol}] Stability: keeping {current_profile_id} "
                f"(TTL: {time_active:.1f}s / {self.config.min_profile_ttl_sec}s, "
                f"blocking switch to {new_profile_id})"
            )
            return False
        
        # Same profile - no switch needed
        if new_profile_id == current_profile_id:
            logger.debug(
                f"[{symbol}] Same profile {current_profile_id}, no switch needed"
            )
            return False
        
        # Check switch margin (Requirement 2.4)
        score_difference = new_score - current_score
        if score_difference < self.config.switch_margin:
            logger.info(
                f"[{symbol}] Stability: keeping {current_profile_id} (score={current_score:.3f}) "
                f"- switch margin not met (diff={score_difference:.3f} < {self.config.switch_margin:.3f}, "
                f"candidate={new_profile_id} score={new_score:.3f})"
            )
            return False
        
        # TTL expired and switch margin met - allow switch
        logger.info(
            f"[{symbol}] Profile switch allowed: {current_profile_id} -> {new_profile_id} "
            f"(score diff={score_difference:.3f} >= margin={self.config.switch_margin}, "
            f"TTL expired after {time_active:.1f}s)"
        )
        return True
    
    def record_selection(
        self,
        symbol: str,
        profile_id: str,
        score: float,
        current_time: Optional[float] = None
    ) -> None:
        """
        Record profile selection and update metrics.
        
        Implements Requirement 2.6 (metrics tracking).
        
        Args:
            symbol: Trading symbol
            profile_id: ID of the selected profile
            score: Score of the selected profile
            current_time: Current Unix timestamp (defaults to time.time())
        """
        if current_time is None:
            current_time = time.time()
        
        metrics = self._metrics[symbol]
        
        # Track duration of previous profile if switching
        if symbol in self._active_profiles:
            old_selection = self._active_profiles[symbol]
            old_profile_id = old_selection.profile_id
            
            if old_profile_id != profile_id:
                # Calculate duration of previous profile
                duration = current_time - old_selection.selected_at
                metrics.durations.append(duration)
                metrics.switch_count += 1
                
                logger.info(
                    f"[{symbol}] Profile switched: {old_profile_id} -> {profile_id} "
                    f"(duration={duration:.1f}s, total_switches={metrics.switch_count})"
                )
        
        # Update active profile
        self._active_profiles[symbol] = ProfileSelection(
            profile_id=profile_id,
            selected_at=current_time,
            score=score,
            switch_count=metrics.switch_count
        )
        
        # Update metrics
        metrics.current_profile_id = profile_id
        metrics.current_profile_selected_at = current_time
        metrics.current_profile_score = score
    
    def get_current_profile(self, symbol: str) -> Optional[str]:
        """
        Get the current active profile for a symbol.
        
        Args:
            symbol: Trading symbol
            
        Returns:
            Profile ID if active, None otherwise
        """
        selection = self._active_profiles.get(symbol)
        return selection.profile_id if selection else None
    
    def get_current_score(self, symbol: str) -> float:
        """
        Get the current profile's score for a symbol.
        
        Args:
            symbol: Trading symbol
            
        Returns:
            Current profile score, 0.0 if no active profile
        """
        selection = self._active_profiles.get(symbol)
        return selection.score if selection else 0.0
    
    def get_time_active(self, symbol: str, current_time: Optional[float] = None) -> float:
        """
        Get how long the current profile has been active.
        
        Args:
            symbol: Trading symbol
            current_time: Current Unix timestamp (defaults to time.time())
            
        Returns:
            Time in seconds, 0.0 if no active profile
        """
        if current_time is None:
            current_time = time.time()
        
        selection = self._active_profiles.get(symbol)
        if selection is None:
            return 0.0
        
        return current_time - selection.selected_at
    
    def is_within_ttl(self, symbol: str, current_time: Optional[float] = None) -> bool:
        """
        Check if the current profile is within its TTL period.
        
        Args:
            symbol: Trading symbol
            current_time: Current Unix timestamp (defaults to time.time())
            
        Returns:
            True if within TTL, False otherwise (or if no active profile)
        """
        time_active = self.get_time_active(symbol, current_time)
        if time_active == 0.0:
            return False
        
        return time_active < self.config.min_profile_ttl_sec
    
    def get_metrics(self, symbol: str) -> Dict[str, Any]:
        """
        Get stability metrics for a symbol.
        
        Implements Requirement 2.6.
        
        Args:
            symbol: Trading symbol
            
        Returns:
            Dictionary with stability metrics:
            - switch_count: Number of profile switches
            - avg_duration_sec: Average profile duration
            - current_profile: Current active profile ID
            - current_profile_score: Current profile's score
            - time_active_sec: How long current profile has been active
        """
        metrics = self._metrics.get(symbol, StabilityMetrics())
        selection = self._active_profiles.get(symbol)
        
        durations = metrics.durations
        avg_duration = sum(durations) / len(durations) if durations else 0.0
        
        time_active = 0.0
        if selection:
            time_active = time.time() - selection.selected_at
        
        return {
            'switch_count': metrics.switch_count,
            'avg_duration_sec': avg_duration,
            'current_profile': selection.profile_id if selection else None,
            'current_profile_score': selection.score if selection else 0.0,
            'time_active_sec': time_active,
            'total_durations_recorded': len(durations),
        }
    
    def get_all_metrics(self) -> Dict[str, Dict[str, Any]]:
        """
        Get stability metrics for all tracked symbols.
        
        Returns:
            Dictionary mapping symbol to metrics
        """
        all_symbols = set(self._active_profiles.keys()) | set(self._metrics.keys())
        return {symbol: self.get_metrics(symbol) for symbol in all_symbols}
    
    def reset_symbol(self, symbol: str) -> None:
        """
        Reset all state for a symbol.
        
        Args:
            symbol: Trading symbol to reset
        """
        if symbol in self._active_profiles:
            del self._active_profiles[symbol]
        if symbol in self._metrics:
            del self._metrics[symbol]
        
        logger.debug(f"[{symbol}] Stability state reset")
    
    def reset_all(self) -> None:
        """Reset all tracked state."""
        self._active_profiles.clear()
        self._metrics.clear()
        logger.debug("All stability state reset")
    
    def update_config(self, config: "RouterConfig") -> None:
        """
        Update configuration.
        
        Args:
            config: New RouterConfig
        """
        old_ttl = self.config.min_profile_ttl_sec
        old_margin = self.config.switch_margin
        
        self.config = config
        
        logger.info(
            f"Stability config updated: TTL {old_ttl}s -> {config.min_profile_ttl_sec}s, "
            f"margin {old_margin} -> {config.switch_margin}"
        )
    
    @staticmethod
    def is_safety_disqualifier(reason: str) -> bool:
        """
        Check if a rejection reason is a safety disqualifier.
        
        Safety disqualifiers bypass TTL and allow immediate profile switching.
        
        Args:
            reason: Rejection reason string
            
        Returns:
            True if the reason is a safety disqualifier
        """
        # Check if any safety disqualifier keyword is in the reason
        reason_lower = reason.lower()
        for disqualifier in SAFETY_DISQUALIFIERS:
            if disqualifier in reason_lower:
                return True
        return False
    
    @staticmethod
    def extract_safety_disqualifiers(reasons: List[str]) -> List[str]:
        """
        Extract safety disqualifier reasons from a list of rejection reasons.
        
        Args:
            reasons: List of rejection reason strings
            
        Returns:
            List of reasons that are safety disqualifiers
        """
        return [r for r in reasons if ProfileStabilityManager.is_safety_disqualifier(r)]
