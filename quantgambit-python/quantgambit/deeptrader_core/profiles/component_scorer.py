"""
Component Scorer - Normalized scoring for Profile Router v2

This module implements the ComponentScorer class that calculates normalized
component scores (0-1) for profile matching against market context.

Implements Requirements: 6.1, 4.1, 4.2, 4.3, 4.4, 5.2, 5.3, 5.4, 1.2, 1.3
"""

from typing import List, Optional, Dict, Tuple
import logging

from quantgambit.deeptrader_core.profiles.router_config import RouterConfig
from quantgambit.deeptrader_core.profiles.context_vector import ContextVector
from quantgambit.deeptrader_core.strategies.chessboard.profile_spec import ProfileConditions


logger = logging.getLogger(__name__)


# Regime tag mapping for inferring regime preferences from profile tags
# Maps regime_family to tags that indicate preference for that regime
REGIME_TAG_MAP: Dict[str, frozenset] = {
    "trend": frozenset(["trend", "momentum", "breakout", "volatility"]),
    "mean_revert": frozenset(["mean_reversion", "mean-reversion", "reversal", "fade", 
                              "contrarian", "vwap", "range", "reversion"]),
    "avoid": frozenset(["chop", "avoid"]),
}


# Session overlap definitions: (session1, session2) -> hours_utc where overlap occurs
SESSION_OVERLAPS: Dict[Tuple[str, str], List[int]] = {
    ("us", "overnight"): [20, 21],
    ("overnight", "us"): [20, 21],
    ("overnight", "asia"): [23, 0],
    ("asia", "overnight"): [23, 0],
    ("asia", "europe"): [7, 8],
    ("europe", "asia"): [7, 8],
    ("europe", "us"): [13, 14],
    ("us", "europe"): [13, 14],
}

# Tags that indicate mean-reversion profiles (for cost viability)
MEAN_REVERT_TAGS = frozenset([
    "mean_reversion", "mean-reversion", "fade", "range", "reversal",
    "contrarian", "vwap", "reversion"
])

# Tags that indicate momentum/taker profiles
MOMENTUM_TAGS = frozenset([
    "momentum", "breakout", "trend", "volatility", "taker"
])


class ComponentScorer:
    """
    Calculate normalized component scores for profile matching.
    
    Each scoring method returns a value in [0, 1] where:
    - 1.0 = perfect match
    - 0.5 = neutral (no preference or partial match)
    - 0.0 = poor match or hard rejection
    
    Implements Requirements 6.1, 4.1, 4.2, 4.3, 4.4, 5.2, 5.3, 5.4
    """
    
    def __init__(self, config: RouterConfig):
        """
        Initialize ComponentScorer with configuration.
        
        Args:
            config: RouterConfig with scoring parameters
        """
        self.config = config
    
    def score_trend_fit(
        self,
        conditions: ProfileConditions,
        context: ContextVector
    ) -> float:
        """
        Score trend alignment (0-1 normalized).
        
        Evaluates how well the current trend matches profile requirements.
        
        Args:
            conditions: Profile conditions with trend requirements
            context: Current market context
            
        Returns:
            Score in [0, 1] where 1.0 = perfect trend match
            
        Implements Requirement 6.1 (trend_fit component)
        """
        score = 0.5  # Neutral baseline when no requirements
        
        # Check required trend direction
        if conditions.required_trend:
            if conditions.required_trend == context.trend_direction:
                score = 1.0
            elif context.trend_direction == "flat":
                # Partial credit for flat when trend is required
                score = 0.3
            else:
                # Wrong direction
                score = 0.0
        
        # Trend strength bonus/penalty
        if conditions.min_trend_strength is not None:
            if context.trend_strength >= conditions.min_trend_strength:
                # Bonus for meeting minimum strength
                excess = context.trend_strength - conditions.min_trend_strength
                score = min(1.0, score + min(0.2, excess * 20))
            else:
                # Penalty for insufficient strength
                score = max(0.0, score - 0.2)
        
        if conditions.max_trend_strength is not None:
            if context.trend_strength > conditions.max_trend_strength:
                # Penalty for exceeding maximum strength
                excess = context.trend_strength - conditions.max_trend_strength
                score = max(0.0, score - min(0.3, excess * 30))
        
        return max(0.0, min(1.0, score))
    
    def score_vol_fit(
        self,
        conditions: ProfileConditions,
        context: ContextVector
    ) -> float:
        """
        Score volatility alignment (0-1 normalized).
        
        Evaluates how well the current volatility regime matches profile requirements.
        
        Args:
            conditions: Profile conditions with volatility requirements
            context: Current market context
            
        Returns:
            Score in [0, 1] where 1.0 = perfect volatility match
            
        Implements Requirement 6.1 (vol_fit component)
        """
        if conditions.required_volatility:
            if conditions.required_volatility == context.volatility_regime:
                return 1.0
            
            # Adjacent regime gets partial credit
            regime_order = ["low", "normal", "high"]
            try:
                req_idx = regime_order.index(conditions.required_volatility)
                ctx_idx = regime_order.index(context.volatility_regime)
                if abs(req_idx - ctx_idx) == 1:
                    return 0.5  # Adjacent regime
            except ValueError:
                pass
            
            return 0.0  # Non-adjacent regime
        
        # Check min/max volatility (ATR ratio)
        score = 0.5  # Neutral baseline
        
        if conditions.min_volatility is not None:
            if context.atr_ratio >= conditions.min_volatility:
                score = min(1.0, score + 0.25)
            else:
                score = max(0.0, score - 0.25)
        
        if conditions.max_volatility is not None:
            if context.atr_ratio <= conditions.max_volatility:
                score = min(1.0, score + 0.25)
            else:
                score = max(0.0, score - 0.25)
        
        return score
    
    def score_value_fit(
        self,
        conditions: ProfileConditions,
        context: ContextVector
    ) -> float:
        """
        Score value area alignment (0-1 normalized).
        
        Evaluates how well the current price position relative to value area
        matches profile requirements.
        
        Scoring logic:
        - 1.0: required_value_location matches position_in_value
        - 0.85: Boundary profile matches boundary position (VAH boundary profile
                when price is above, or VAL boundary profile when price is below)
        - 0.5: Neutral (no value requirements or inside position with boundary profile)
        - 0.0: required_value_location doesn't match position_in_value
        
        Args:
            conditions: Profile conditions with value location requirements
            context: Current market context
            
        Returns:
            Score in [0, 1] where 1.0 = perfect value location match
            
        Implements Requirement 6.1 (value_fit component)
        Implements Requirements 1.1, 1.2, 1.3, 1.4, 2.1, 2.2, 2.3, 2.4, 3.1, 3.2, 3.3
        (value-boundary-profile-selection spec)
        """
        # Existing logic: required_value_location takes precedence
        if conditions.required_value_location:
            if conditions.required_value_location == context.position_in_value:
                base_score = 1.0
            else:
                return 0.0  # Strong penalty for mismatch
        else:
            # NEW: Check for boundary profile conditions
            is_vah_boundary_profile = conditions.min_distance_from_vah is not None
            is_val_boundary_profile = conditions.min_distance_from_val is not None

            # Give bonus when boundary profile matches boundary position
            if context.position_in_value == "above" and is_vah_boundary_profile:
                base_score = 0.85  # Bonus for VAH boundary profile when price is above
            elif context.position_in_value == "below" and is_val_boundary_profile:
                base_score = 0.85  # Bonus for VAL boundary profile when price is below
            elif is_vah_boundary_profile or is_val_boundary_profile:
                # Boundary profile but not at boundary → neutral (no bonus).
                # This matches the value-boundary-profile-selection contract tests.
                base_score = 0.5
            else:
                base_score = 0.5  # No requirement = neutral

        # Apply distance-based soft penalties when thresholds are specified
        # These are soft preferences (not hard rejections).
        penalty = 1.0
        has_amt_levels = any(
            level and level > 0.0
            for level in (
                context.value_area_high,
                context.value_area_low,
                context.point_of_control,
            )
        )
        if has_amt_levels:
            if conditions.min_distance_from_poc is not None:
                min_poc_pct = (
                    conditions.min_distance_from_poc
                    if conditions.min_distance_from_poc <= 1.0
                    else conditions.min_distance_from_poc / 10000.0
                )
                if context.distance_to_poc_pct < min_poc_pct:
                    penalty *= 0.6
            # For value-boundary profiles, these thresholds represent "how close we must be"
            # to the boundary (i.e., a max distance), not "how far away we must be".
            if conditions.min_distance_from_vah is not None:
                max_vah_pct = (
                    conditions.min_distance_from_vah
                    if conditions.min_distance_from_vah <= 1.0
                    else conditions.min_distance_from_vah / 10000.0
                )
                if context.distance_to_vah_pct > max_vah_pct:
                    penalty *= 0.7
            if conditions.min_distance_from_val is not None:
                max_val_pct = (
                    conditions.min_distance_from_val
                    if conditions.min_distance_from_val <= 1.0
                    else conditions.min_distance_from_val / 10000.0
                )
                if context.distance_to_val_pct > max_val_pct:
                    penalty *= 0.7

        return max(0.0, min(1.0, base_score * penalty))
    
    def score_microstructure_fit(
        self,
        context: ContextVector,
        conditions: Optional[ProfileConditions] = None
    ) -> float:
        """
        Score microstructure quality (0-1 normalized).
        
        Evaluates spread, depth, and trade activity quality.
        
        Args:
            context: Current market context
            
        Returns:
            Score in [0, 1] where 1.0 = excellent microstructure
            
        Implements Requirement 6.1 (microstructure_fit component)
        """
        # Spread component (lower is better)
        # Normalize: 0 bps = 1.0, 20+ bps = 0.0
        spread_bps = context.spread_bps if context.spread_bps is not None else 0.0
        spread_score = max(0.0, 1.0 - (spread_bps / 20.0))
        
        # Depth component (higher is better)
        # Normalize: 100k+ USD = 1.0, 0 USD = 0.0
        total_depth = (context.bid_depth_usd or 0.0) + (context.ask_depth_usd or 0.0)
        depth_score = min(1.0, total_depth / 100000.0)
        
        # TPS component (higher is better)
        # Normalize: 5+ tps = 1.0, 0 tps = 0.0
        tps = context.trades_per_second if context.trades_per_second is not None else 0.0
        tps_score = min(1.0, tps / 5.0)
        
        # Weighted average: spread is most important
        score = 0.4 * spread_score + 0.3 * depth_score + 0.3 * tps_score

        # Apply condition-based soft penalties when specified
        if conditions is not None:
            penalty = 1.0
            # max_spread / min_spread are stored as decimal (e.g., 0.002 = 20 bps)
            if conditions.max_spread is not None:
                max_spread_bps = (
                    conditions.max_spread * 10000.0
                    if conditions.max_spread <= 1.0
                    else conditions.max_spread
                )
                if spread_bps > max_spread_bps:
                    penalty *= 0.4
            if conditions.min_spread is not None:
                min_spread_bps = (
                    conditions.min_spread * 10000.0
                    if conditions.min_spread <= 1.0
                    else conditions.min_spread
                )
                if spread_bps < min_spread_bps:
                    penalty *= 0.7
            if conditions.min_orderbook_depth is not None:
                if total_depth < conditions.min_orderbook_depth:
                    penalty *= 0.6
            if conditions.min_trades_per_second is not None:
                if tps < conditions.min_trades_per_second:
                    penalty *= 0.6

            score *= penalty

        return max(0.0, min(1.0, score))
    
    def score_rotation_fit(
        self,
        conditions: ProfileConditions,
        context: ContextVector
    ) -> float:
        """
        Score rotation factor alignment (0-1 normalized).
        
        Evaluates how well the current rotation factor matches profile requirements.
        
        Args:
            conditions: Profile conditions with rotation requirements
            context: Current market context
            
        Returns:
            Score in [0, 1] where 1.0 = perfect rotation match
            
        Implements Requirement 6.1 (rotation_fit component)
        """
        rotation = context.rotation_factor if context.rotation_factor is not None else 0.0
        
        if conditions.min_rotation_factor is not None:
            if rotation >= conditions.min_rotation_factor:
                # Bonus for exceeding minimum
                excess = rotation - conditions.min_rotation_factor
                return min(1.0, 0.5 + excess / 10.0)
            return 0.2  # Below minimum
        
        if conditions.max_rotation_factor is not None:
            if rotation <= conditions.max_rotation_factor:
                return 0.7  # Within maximum
            return 0.2  # Above maximum
        
        return 0.5  # No requirement = neutral

    def score_session_fit(
        self,
        conditions: ProfileConditions,
        context: ContextVector
    ) -> float:
        """
        Score session alignment (0-1 normalized) with overlap handling.
        
        Implements soft session preference scoring:
        - 1.0 for exact match with required_session
        - 0.8 for match with allowed_sessions
        - 0.7 for overlap period between required and current session
        - 0.5 for neutral (no session requirements)
        - 0.3 for non-matching session
        
        Args:
            conditions: Profile conditions with session requirements
            context: Current market context
            
        Returns:
            Score in [0, 1] where 1.0 = perfect session match
            
        Implements Requirements 4.1, 4.2, 4.3, 4.4 (session soft scoring)
        """
        score = 0.5  # Neutral baseline
        
        # Check required_session (soft preference with +0.15 bonus per Req 4.1)
        if conditions.required_session:
            if conditions.required_session == context.session:
                score = 1.0  # Exact match
            elif self._is_session_overlap(
                conditions.required_session,
                context.session,
                context.hour_utc
            ):
                score = 0.7  # Overlap bonus (Req 4.3)
            else:
                score = 0.3  # Different session
        
        # Check allowed_sessions (soft preference with +0.10 bonus per Req 4.2)
        if conditions.allowed_sessions:
            if context.session in conditions.allowed_sessions:
                score = max(score, 0.8)  # Match with allowed sessions
            elif self._is_any_session_overlap(
                conditions.allowed_sessions,
                context.session,
                context.hour_utc
            ):
                score = max(score, 0.6)  # Partial overlap with allowed
        
        return score
    
    def _is_session_overlap(
        self,
        required: str,
        current: str,
        hour_utc: int
    ) -> bool:
        """
        Check if sessions overlap at boundary.
        
        Session boundaries with overlap handling (Req 4.3):
        - Late US (20:00-21:00 UTC) overlaps with early overnight
        - Late overnight (23:00-00:00 UTC) overlaps with early Asia
        - Late Asia (07:00-08:00 UTC) overlaps with early Europe
        - Late Europe (13:00-14:00 UTC) overlaps with early US
        
        Args:
            required: Required session name
            current: Current session name
            hour_utc: Current hour in UTC
            
        Returns:
            True if sessions overlap at current hour
        """
        overlap_hours = SESSION_OVERLAPS.get((required, current))
        if overlap_hours:
            return hour_utc in overlap_hours
        return False
    
    def _is_any_session_overlap(
        self,
        allowed_sessions: List[str],
        current: str,
        hour_utc: int
    ) -> bool:
        """
        Check if current session overlaps with any allowed session.
        
        Args:
            allowed_sessions: List of allowed session names
            current: Current session name
            hour_utc: Current hour in UTC
            
        Returns:
            True if current session overlaps with any allowed session
        """
        for allowed in allowed_sessions:
            if self._is_session_overlap(allowed, current, hour_utc):
                return True
        return False
    
    def score_cost_viability_fit(
        self,
        conditions: ProfileConditions,
        context: ContextVector,
        profile_tags: Optional[List[str]] = None
    ) -> float:
        """
        Score cost viability (0-1 normalized).
        
        Evaluates economic viability based on expected costs vs profile type.
        
        Mean-reversion profiles: max_viable_cost = 8 bps (Req 5.2)
        Momentum/taker profiles: max_viable_cost = 15 bps (Req 5.3)
        
        Formula: max(0, 1 - (expected_cost_bps / max_viable_cost_bps)) (Req 5.4)
        
        Hard rejection when expected_cost_bps >= 2x max_viable_cost (Req 5.5)
        
        Args:
            conditions: Profile conditions
            context: Current market context with expected_cost_bps
            profile_tags: List of profile tags to determine profile type
            
        Returns:
            Score in [0, 1] where 1.0 = excellent cost viability
            0.0 indicates hard rejection (cost too high)
            
        Implements Requirements 5.2, 5.3, 5.4, 5.5
        """
        tags = profile_tags or []
        normalized_tags = {str(tag).lower() for tag in tags}
        
        # Determine max viable cost based on profile type
        is_mean_revert = bool(normalized_tags & MEAN_REVERT_TAGS)
        is_momentum = bool(normalized_tags & MOMENTUM_TAGS)
        
        if is_mean_revert:
            # Mean-reversion profiles have tighter cost constraints (Req 5.2)
            max_viable_cost = 8.0
        elif is_momentum:
            # Momentum profiles can tolerate higher costs (Req 5.3)
            # But penalize in low volatility
            max_viable_cost = 15.0
            if context.volatility_regime != "high":
                # Stricter cost threshold in non-high volatility
                max_viable_cost = 12.0
        else:
            # Default: moderate cost tolerance
            max_viable_cost = 10.0
        
        expected_cost = context.expected_cost_bps
        
        # Hard rejection threshold: 2x max viable cost (Req 5.5)
        if expected_cost >= 2 * max_viable_cost:
            return 0.0
        
        # Cost viability formula (Req 5.4)
        return max(0.0, 1.0 - (expected_cost / max_viable_cost))
    
    def score_regime_fit(
        self,
        conditions: ProfileConditions,
        context: ContextVector,
        profile_tags: Optional[List[str]] = None
    ) -> float:
        """
        Score regime alignment (0-1 normalized) using soft preferences.
        
        Implements soft regime handling:
        - Uses RegimeMapper for taxonomy alignment (Req 1.2)
        - Applies soft penalty (0.15) for unknown/mismatched regimes (Req 1.2)
        - Tag-inferred regime allowlists are soft scoring factors (Req 1.3)
        - Explicit allowed_regimes is handled as hard constraint elsewhere (Req 1.4)
        
        Scoring:
        - 1.0: Perfect regime match (mapped regime_family matches profile preference)
        - 0.85: Unknown regime with profile demanding specific family (soft penalty)
        - 0.7: Partial match (related regime families)
        - 0.5: Neutral (no regime preference from tags)
        - 0.3: Mismatched regime family
        
        Args:
            conditions: Profile conditions
            context: Current market context with regime_family
            profile_tags: List of profile tags to infer regime preference
            
        Returns:
            Score in [0, 1] where 1.0 = perfect regime match
            
        Implements Requirements 1.2, 1.3
        """
        from quantgambit.deeptrader_core.profiles.regime_mapper import RegimeMapper
        
        tags = profile_tags or []
        normalized_tags = {str(tag).lower() for tag in tags}
        
        # Infer regime preference from tags (Req 1.3)
        inferred_regime_family = self._infer_regime_family_from_tags(normalized_tags)
        
        # If no regime preference inferred from tags, return neutral score
        if inferred_regime_family is None:
            return 0.5
        
        # Get the mapped regime family from context
        # Use RegimeMapper for consistent taxonomy (Req 1.2)
        mapper = RegimeMapper(self.config)
        mapped_family, confidence = mapper.map_regime(context)
        
        # Handle unknown regime with soft penalty (Req 1.2)
        if mapped_family == "unknown":
            # Apply soft penalty of 0.15 for profiles demanding specific family
            # Score = 1.0 - 0.15 = 0.85
            return 1.0 - self.config.regime_soft_penalty
        
        # Check if mapped regime matches inferred preference
        if mapped_family == inferred_regime_family:
            # Perfect match - full score
            return 1.0
        
        # Check for related regime families (partial match)
        # trend and mean_revert are opposites, avoid is separate
        related_families = {
            "trend": {"trend"},  # Only matches itself
            "mean_revert": {"mean_revert"},  # Only matches itself
            "avoid": {"avoid"},  # Only matches itself
        }
        
        if mapped_family in related_families.get(inferred_regime_family, set()):
            return 0.7  # Partial match
        
        # Mismatched regime - apply penalty but don't reject (soft preference)
        # Score = 1.0 - 0.15 * 2 = 0.7 for mismatch
        # Actually, let's use a clearer scoring:
        # - Mismatch with "avoid" regime: lower score (0.3)
        # - Mismatch between trend/mean_revert: moderate penalty (0.5)
        if mapped_family == "avoid":
            # Current market is in "avoid" regime, penalize profiles that want to trade
            return 0.3
        
        if inferred_regime_family == "avoid":
            # Profile wants to avoid trading, but market is tradeable
            return 0.5
        
        # Mismatch between trend and mean_revert
        return 0.5 - self.config.regime_soft_penalty  # 0.35 with default penalty
    
    def _infer_regime_family_from_tags(
        self,
        normalized_tags: set
    ) -> Optional[str]:
        """
        Infer regime family preference from profile tags.
        
        Uses REGIME_TAG_MAP to determine which regime family a profile
        prefers based on its tags.
        
        Args:
            normalized_tags: Set of lowercase profile tags
            
        Returns:
            Inferred regime family ("trend", "mean_revert", "avoid") or None
            
        Implements Requirement 1.3 (tag-inferred regime allowlists)
        """
        for regime_family, tag_set in REGIME_TAG_MAP.items():
            if normalized_tags & tag_set:
                return regime_family
        return None
    
    def compute_all_scores(
        self,
        conditions: ProfileConditions,
        context: ContextVector,
        profile_tags: Optional[List[str]] = None
    ) -> Dict[str, float]:
        """
        Compute all component scores for a profile.
        
        Args:
            conditions: Profile conditions
            context: Current market context
            profile_tags: Optional list of profile tags
            
        Returns:
            Dictionary mapping component names to scores
        """
        return {
            'trend_fit': self.score_trend_fit(conditions, context),
            'vol_fit': self.score_vol_fit(conditions, context),
            'value_fit': self.score_value_fit(conditions, context),
            'microstructure_fit': self.score_microstructure_fit(context, conditions),
            'rotation_fit': self.score_rotation_fit(conditions, context),
            'session_fit': self.score_session_fit(conditions, context),
            'cost_viability_fit': self.score_cost_viability_fit(
                conditions, context, profile_tags
            ),
            'regime_fit': self.score_regime_fit(
                conditions, context, profile_tags
            ),
        }
    
    def compute_weighted_score(
        self,
        component_scores: Dict[str, float],
        weights: Optional[Dict[str, float]] = None
    ) -> float:
        """
        Compute weighted sum of component scores.
        
        Args:
            component_scores: Dictionary of component name -> score
            weights: Optional custom weights (uses config weights if None)
            
        Returns:
            Weighted score clamped to [0.0, 1.0]
            
        Implements Requirements 6.1, 6.2, 6.5
        """
        if weights is None:
            weights = self.config.component_weights
        
        total = 0.0
        for component, score in component_scores.items():
            weight = weights.get(component, 0.0)
            total += weight * score
        
        # Clamp to [0.0, 1.0] (Req 6.5)
        return max(0.0, min(1.0, total))
