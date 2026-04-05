"""
Regime Mapper - Deterministic mapping from market_regime to regime_family

This module implements the RegimeMapper class that provides consistent regime
classification to prevent vocabulary mismatch between market regimes and
profile requirements.

Implements Requirements 1.1 (Regime Taxonomy Alignment)
"""

from dataclasses import dataclass
from typing import Tuple, TYPE_CHECKING
import logging

if TYPE_CHECKING:
    from .context_vector import ContextVector
    from .router_config import RouterConfig

logger = logging.getLogger(__name__)


# Valid regime families
REGIME_FAMILIES = frozenset(["trend", "mean_revert", "avoid", "unknown"])

# Valid market regimes
MARKET_REGIMES = frozenset(["range", "breakout", "squeeze", "chop"])


@dataclass
class RegimeMappingResult:
    """Result of regime mapping operation."""
    regime_family: str
    confidence: float
    source_regime: str
    mapping_reason: str


class RegimeMapper:
    """
    Deterministic mapping from market_regime to regime_family.
    
    This class implements the regime taxonomy alignment specified in Requirement 1.1:
    - "range" → "mean_revert" (unless trend_strength > threshold)
    - "breakout" → "trend"
    - "squeeze" → "trend" (or "avoid" if liquidity_score < threshold)
    - "chop" → "avoid" (or "mean_revert" if expected_cost_bps < threshold)
    
    The mapping is deterministic given the same inputs, ensuring consistent
    profile selection behavior.
    """
    
    def __init__(self, config: "RouterConfig"):
        """
        Initialize RegimeMapper with configuration.
        
        Args:
            config: RouterConfig containing regime mapping thresholds
        """
        self.config = config
    
    def map_regime(self, context: "ContextVector") -> Tuple[str, float]:
        """
        Map market_regime to regime_family with confidence.
        
        This is the main entry point for regime mapping. It applies the
        deterministic mapping rules based on the current market context.
        
        Args:
            context: ContextVector containing market state
            
        Returns:
            Tuple of (regime_family, confidence) where:
            - regime_family is one of: "trend", "mean_revert", "avoid", "unknown"
            - confidence is a float in [0, 1] indicating mapping certainty
        """
        result = self.map_regime_detailed(context)
        return (result.regime_family, result.confidence)
    
    def map_regime_detailed(self, context: "ContextVector") -> RegimeMappingResult:
        """
        Map market_regime to regime_family with full details.
        
        This method provides additional context about the mapping decision
        for debugging and observability.
        
        Args:
            context: ContextVector containing market state
            
        Returns:
            RegimeMappingResult with regime_family, confidence, and reasoning
        """
        market_regime = context.market_regime.lower() if context.market_regime else ""
        trend_strength = context.trend_strength
        liquidity_score = context.liquidity_score
        expected_cost_bps = context.expected_cost_bps
        
        # Apply mapping rules based on market_regime
        if market_regime == "range":
            result = self._map_range_regime(trend_strength)
        elif market_regime == "breakout":
            result = self._map_breakout_regime()
        elif market_regime == "squeeze":
            result = self._map_squeeze_regime(liquidity_score)
        elif market_regime == "chop":
            result = self._map_chop_regime(expected_cost_bps)
        else:
            # Unknown regime - return with low confidence
            result = RegimeMappingResult(
                regime_family="unknown",
                confidence=0.3,
                source_regime=market_regime,
                mapping_reason=f"Unknown market_regime '{market_regime}'"
            )
        
        # Log the mapping decision at DEBUG level (Requirement 1.5)
        logger.debug(
            f"Regime mapping: {result.source_regime} -> {result.regime_family} "
            f"(confidence={result.confidence:.2f}, reason={result.mapping_reason})"
        )
        
        return result
    
    def _map_range_regime(self, trend_strength: float) -> RegimeMappingResult:
        """
        Map 'range' market regime to regime family.
        
        Rules:
        - If trend_strength > threshold → "trend" (confidence 0.6)
        - Otherwise → "mean_revert" (confidence 0.8)
        """
        threshold = self.config.trend_strength_for_range_to_trend
        
        if trend_strength > threshold:
            return RegimeMappingResult(
                regime_family="trend",
                confidence=0.6,
                source_regime="range",
                mapping_reason=f"trend_strength ({trend_strength:.4f}) > threshold ({threshold})"
            )
        
        return RegimeMappingResult(
            regime_family="mean_revert",
            confidence=0.8,
            source_regime="range",
            mapping_reason=f"trend_strength ({trend_strength:.4f}) <= threshold ({threshold})"
        )
    
    def _map_breakout_regime(self) -> RegimeMappingResult:
        """
        Map 'breakout' market regime to regime family.
        
        Rules:
        - Always → "trend" (confidence 0.9)
        """
        return RegimeMappingResult(
            regime_family="trend",
            confidence=0.9,
            source_regime="breakout",
            mapping_reason="breakout always maps to trend"
        )
    
    def _map_squeeze_regime(self, liquidity_score: float) -> RegimeMappingResult:
        """
        Map 'squeeze' market regime to regime family.
        
        Rules:
        - If liquidity_score < threshold → "avoid" (confidence 0.7)
        - Otherwise → "trend" (confidence 0.7)
        """
        threshold = self.config.squeeze_liquidity_threshold
        
        if liquidity_score < threshold:
            return RegimeMappingResult(
                regime_family="avoid",
                confidence=0.7,
                source_regime="squeeze",
                mapping_reason=f"liquidity_score ({liquidity_score:.2f}) < threshold ({threshold})"
            )
        
        return RegimeMappingResult(
            regime_family="trend",
            confidence=0.7,
            source_regime="squeeze",
            mapping_reason=f"liquidity_score ({liquidity_score:.2f}) >= threshold ({threshold})"
        )
    
    def _map_chop_regime(self, expected_cost_bps: float) -> RegimeMappingResult:
        """
        Map 'chop' market regime to regime family.
        
        Rules:
        - If expected_cost_bps < threshold → "mean_revert" (confidence 0.5)
        - Otherwise → "avoid" (confidence 0.8)
        """
        threshold = self.config.chop_cost_threshold_bps
        
        if expected_cost_bps < threshold:
            return RegimeMappingResult(
                regime_family="mean_revert",
                confidence=0.5,
                source_regime="chop",
                mapping_reason=f"expected_cost_bps ({expected_cost_bps:.2f}) < threshold ({threshold})"
            )
        
        return RegimeMappingResult(
            regime_family="avoid",
            confidence=0.8,
            source_regime="chop",
            mapping_reason=f"expected_cost_bps ({expected_cost_bps:.2f}) >= threshold ({threshold})"
        )
    
    def is_valid_regime_family(self, regime_family: str) -> bool:
        """Check if a regime family is valid."""
        return regime_family in REGIME_FAMILIES
    
    def is_valid_market_regime(self, market_regime: str) -> bool:
        """Check if a market regime is valid."""
        return market_regime.lower() in MARKET_REGIMES
