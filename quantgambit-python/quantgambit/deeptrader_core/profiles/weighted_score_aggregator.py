"""
Weighted Score Aggregator - Aggregates component scores into final weighted score

This module implements the WeightedScoreAggregator class that computes the final
weighted score from component scores and populates ProfileScore with all scoring data.

Implements Requirements: 6.1, 6.2, 6.5
"""

from typing import Dict, List, Optional, Any
import logging

from quantgambit.deeptrader_core.profiles.router_config import RouterConfig
from quantgambit.deeptrader_core.profiles.context_vector import ContextVector
from quantgambit.deeptrader_core.profiles.component_scorer import ComponentScorer
from quantgambit.deeptrader_core.strategies.chessboard.profile_spec import (
    ProfileSpec,
    ProfileConditions,
)


logger = logging.getLogger(__name__)


class WeightedScoreAggregator:
    """
    Aggregates component scores into a final weighted score.
    
    This class orchestrates the scoring pipeline:
    1. Computes all component scores via ComponentScorer
    2. Applies configurable weights to each component
    3. Computes weighted sum
    4. Clamps final score to [0.0, 1.0]
    5. Returns scoring breakdown for observability
    
    Implements Requirements 6.1, 6.2, 6.5
    """
    
    def __init__(self, config: RouterConfig):
        """
        Initialize WeightedScoreAggregator with configuration.
        
        Args:
            config: RouterConfig with component weights and scoring parameters
        """
        self.config = config
        self.component_scorer = ComponentScorer(config)
    
    def compute_weighted_score(
        self,
        conditions: ProfileConditions,
        context: ContextVector,
        profile_tags: Optional[List[str]] = None,
        custom_weights: Optional[Dict[str, float]] = None,
    ) -> Dict[str, Any]:
        """
        Compute weighted score from component scores.
        
        This method:
        1. Computes all component scores (0-1 normalized)
        2. Applies weights from config (or custom weights)
        3. Computes weighted sum
        4. Clamps result to [0.0, 1.0]
        
        Args:
            conditions: Profile conditions for scoring
            context: Current market context
            profile_tags: Optional list of profile tags for cost viability
            custom_weights: Optional custom weights (overrides config)
            
        Returns:
            Dictionary containing:
            - 'final_score': float in [0.0, 1.0]
            - 'component_scores': Dict[str, float] of individual scores
            - 'weighted_contributions': Dict[str, float] of weight * score
            - 'weights_used': Dict[str, float] of weights applied
            
        Implements Requirements 6.1, 6.2, 6.5
        """
        # Step 1: Compute all component scores
        component_scores = self.component_scorer.compute_all_scores(
            conditions=conditions,
            context=context,
            profile_tags=profile_tags,
        )
        
        # Step 2: Get weights to use
        weights = custom_weights if custom_weights is not None else self.config.component_weights
        
        # Step 3: Compute weighted contributions
        weighted_contributions = {}
        total_score = 0.0
        
        for component, score in component_scores.items():
            weight = weights.get(component, 0.0)
            contribution = weight * score
            weighted_contributions[component] = contribution
            total_score += contribution
        
        # Step 4: Clamp to [0.0, 1.0] (Requirement 6.5)
        final_score = max(0.0, min(1.0, total_score))
        
        # Log component contributions at DEBUG level (Requirement 6.3)
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                f"Weighted score breakdown: final={final_score:.3f}, "
                f"components={component_scores}, contributions={weighted_contributions}"
            )
        
        return {
            'final_score': final_score,
            'component_scores': component_scores,
            'weighted_contributions': weighted_contributions,
            'weights_used': weights,
        }
    
    def compute_profile_score(
        self,
        spec: ProfileSpec,
        context: ContextVector,
        custom_weights: Optional[Dict[str, float]] = None,
    ) -> Dict[str, Any]:
        """
        Compute full scoring breakdown for a profile.
        
        Convenience method that extracts conditions and tags from ProfileSpec.
        
        Args:
            spec: Profile specification
            context: Current market context
            custom_weights: Optional custom weights
            
        Returns:
            Same as compute_weighted_score()
        """
        return self.compute_weighted_score(
            conditions=spec.conditions,
            context=context,
            profile_tags=spec.tags,
            custom_weights=custom_weights,
        )
    
    def aggregate_scores(
        self,
        component_scores: Dict[str, float],
        weights: Optional[Dict[str, float]] = None,
    ) -> float:
        """
        Aggregate pre-computed component scores into final weighted score.
        
        This is a lower-level method for when component scores are already computed.
        
        Args:
            component_scores: Dictionary of component name -> score (0-1)
            weights: Optional custom weights (uses config if None)
            
        Returns:
            Final weighted score clamped to [0.0, 1.0]
            
        Implements Requirements 6.1, 6.2, 6.5
        """
        if weights is None:
            weights = self.config.component_weights
        
        total = 0.0
        for component, score in component_scores.items():
            weight = weights.get(component, 0.0)
            total += weight * score
        
        # Clamp to [0.0, 1.0] (Requirement 6.5)
        return max(0.0, min(1.0, total))
    
    def get_top_contributors(
        self,
        weighted_contributions: Dict[str, float],
        top_k: int = 3,
    ) -> List[tuple]:
        """
        Get top contributing components for observability.
        
        Args:
            weighted_contributions: Dict of component -> weighted contribution
            top_k: Number of top contributors to return
            
        Returns:
            List of (component_name, contribution) tuples, sorted by contribution
        """
        sorted_contributions = sorted(
            weighted_contributions.items(),
            key=lambda x: x[1],
            reverse=True,
        )
        return sorted_contributions[:top_k]
    
    def validate_weights(self, weights: Dict[str, float]) -> bool:
        """
        Validate that weights sum to 1.0 (within tolerance).
        
        Args:
            weights: Dictionary of component weights
            
        Returns:
            True if weights are valid, False otherwise
        """
        total = sum(weights.values())
        return abs(total - 1.0) <= 0.001


def clamp_score(score: float) -> float:
    """
    Clamp a score to the valid range [0.0, 1.0].
    
    This is a utility function for score clamping as required by Requirement 6.5.
    
    Args:
        score: Raw score value
        
    Returns:
        Score clamped to [0.0, 1.0]
    """
    return max(0.0, min(1.0, score))
