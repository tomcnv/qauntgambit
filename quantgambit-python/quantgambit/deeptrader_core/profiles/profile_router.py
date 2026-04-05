"""
Profile Router - Context-scoring profile selection engine

Scores all available profiles against current market context and selects
the top-K profiles to activate. Uses hybrid approach: rule filters + ML scoring.

Includes explicit regime inference rules (Requirement 11) that are non-lethal:
- Never rejects signals due to regime classification
- Falls back to default regime when data is missing
- Logs warnings for partial/default inference
"""

import logging
import math
import os
import time
from typing import List, Dict, Optional, Tuple, Any
from dataclasses import dataclass, field
from collections import defaultdict

from quantgambit.deeptrader_core.profiles.context_vector import ContextVector
from quantgambit.deeptrader_core.strategies.chessboard.profile_spec import ProfileSpec, ProfileConditions, ProfileInstance, ProfileLifecycleState
from quantgambit.deeptrader_core.strategies.chessboard import get_profile_registry
from quantgambit.deeptrader_core.profiles.profile_stability_manager import ProfileStabilityManager
from quantgambit.deeptrader_core.profiles.hysteresis_tracker import HysteresisTracker
from quantgambit.deeptrader_core.profiles.weighted_score_aggregator import WeightedScoreAggregator, clamp_score

from quantgambit.strategies.disable_rules import enabled_strategies_for_symbol


logger = logging.getLogger(__name__)


_REGIME_TAG_MAP = {
    "trend": {"trend", "momentum", "breakout", "volatility"},
    "mean_revert": {"mean_reversion", "reversal", "fade", "contrarian", "vwap", "range"},
    "avoid": {"chop", "avoid"},
}


def _normalize_profile_id_alias(profile_id: str) -> str:
    if str(profile_id).endswith("_profile"):
        return str(profile_id)[: -len("_profile")]
    return str(profile_id)


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _parse_hour(value: str, fallback: int) -> int:
    try:
        hour = int(str(value).strip())
    except (TypeError, ValueError):
        return fallback
    return max(0, min(23, hour))


def _in_utc_hour_window(hour_utc: int, start_hour: int, end_hour: int) -> bool:
    if start_hour == end_hour:
        return True
    if start_hour < end_hour:
        return start_hour <= hour_utc < end_hour
    # Overnight wrap, e.g. 22 -> 2
    return hour_utc >= start_hour or hour_utc < end_hour


def _infer_regime_allowlist(tags: List[str]) -> Optional[List[str]]:
    if not tags:
        return None
    normalized = {str(tag).lower() for tag in tags}
    allow = set()
    for regime, tagset in _REGIME_TAG_MAP.items():
        if normalized & tagset:
            allow.add(regime)
    return sorted(allow) if allow else None


@dataclass
class ProfileScore:
    """Score for a profile given current context"""
    profile_id: str
    score: float  # 0.0 to 1.0
    confidence: float  # 0.0 to 1.0
    reasons: List[str]  # Explanation for score
    rule_passed: bool
    ml_score: Optional[float] = None
    
    # Profile Router v2 fields (Requirements 6.4, 8.2)
    component_scores: Dict[str, float] = field(default_factory=dict)  # Per-component scores
    cost_viability_score: float = 0.0  # Economic viability score
    stability_adjusted: bool = False  # Whether stability mechanisms affected selection
    hard_filter_passed: bool = True  # Whether profile passed safety-critical hard filters


@dataclass
class RegimeInferenceConfig:
    """
    Configuration for regime inference rules.
    
    Implements Requirement 11: Explicit and non-lethal router/regime inference rules.
    
    Thresholds are configurable (not hardcoded) and can be loaded from YAML.
    """
    # Volatility regime thresholds (based on volatility_percentile)
    volatility_low_threshold: float = 0.3   # Below this -> "low" volatility
    volatility_high_threshold: float = 0.7  # Above this -> "high" volatility
    
    # Trend regime threshold (based on abs(trend_strength))
    trend_threshold: float = 0.5  # Above this -> "trending", below -> "ranging"
    
    # Spread regime thresholds (based on spread_percentile)
    spread_tight_threshold: float = 0.3   # Below this -> "tight" spread
    spread_wide_threshold: float = 0.7    # Above this -> "wide" spread
    
    @classmethod
    def from_yaml(cls, path: str) -> "RegimeInferenceConfig":
        """
        Load config from YAML file.
        
        Expected YAML structure:
        ```yaml
        regime_inference:
          volatility_low_threshold: 0.3
          volatility_high_threshold: 0.7
          trend_threshold: 0.5
          spread_tight_threshold: 0.3
          spread_wide_threshold: 0.7
        ```
        
        Args:
            path: Path to YAML config file
            
        Returns:
            RegimeInferenceConfig instance
        """
        import yaml
        with open(path) as f:
            data = yaml.safe_load(f)
        return cls(**data.get("regime_inference", {}))


@dataclass
class RegimeInference:
    """
    Result of regime inference.
    
    Implements Requirement 11: Explicit regime inference with quality tracking.
    
    The inference_quality field indicates how much data was available:
    - "full": All fields present, high confidence
    - "partial": Some fields missing, moderate confidence
    - "default": All fields missing, using defaults
    """
    volatility_regime: str  # "low", "normal", "high"
    trend_regime: str       # "trending", "ranging"
    spread_regime: str      # "tight", "normal", "wide"
    inference_quality: str  # "full", "partial", "default"
    missing_fields: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "volatility_regime": self.volatility_regime,
            "trend_regime": self.trend_regime,
            "spread_regime": self.spread_regime,
            "inference_quality": self.inference_quality,
            "missing_fields": self.missing_fields,
        }


class ProfileRouter:
    """
    Context-based profile scoring and selection engine
    
    Implements Requirement 11: Explicit and non-lethal router/regime inference rules.
    - Never rejects signals due to regime classification
    - Falls back to default regime when data is missing
    - Logs warnings for partial/default inference
    
    Usage:
        router = ProfileRouter()
        context = build_context_vector_from_state(state, symbol)
        selected = router.select_profiles(context, top_k=3)
    """
    
    def __init__(
        self,
        enable_ml: bool = False,
        config: Optional['RouterConfig'] = None,
        regime_inference_config: Optional[RegimeInferenceConfig] = None,
        default_profile_id: Optional[str] = None,
    ):
        self.enable_ml = enable_ml
        self.regime_inference_config = regime_inference_config or RegimeInferenceConfig()
        self.default_profile_id = default_profile_id
        
        self.registry = get_profile_registry()
        if not self.registry.list_specs():
            from quantgambit.deeptrader_core.strategies.chessboard.canonical_profiles import (
                register_canonical_profiles,
            )

            register_canonical_profiles()
        
        # Import RouterConfig for defaults
        from quantgambit.deeptrader_core.profiles.router_config import RouterConfig
        self.config = config if config is not None else RouterConfig()
        
        # Profile stability components (Requirements 2.1, 2.2, 2.3, 2.4, 2.5, 2.6)
        self.stability_manager = ProfileStabilityManager(self.config)
        self.hysteresis_tracker = HysteresisTracker()
        
        # v2 scoring components (Requirement 10.5)
        # WeightedScoreAggregator is used when use_v2_scoring=True
        self.weighted_score_aggregator = WeightedScoreAggregator(self.config)
        
        # Performance tracking per (profile_id, symbol, session) tuple
        # Requirements 7.1, 7.2, 7.3, 7.4, 7.5
        # Each entry contains a list of trade results with timestamps for decay calculation
        self.performance_v2: Dict[Tuple[str, str, str], Dict] = defaultdict(lambda: {
            'trades': [],  # List of (timestamp, pnl, is_win) tuples for decay
            'total_trades': 0,
            'total_wins': 0,
            'total_pnl': 0.0,
        })
        
        # Legacy performance tracking per (profile_id, symbol) for backward compatibility
        self.performance: Dict[Tuple[str, str], Dict] = defaultdict(lambda: {
            'trades': 0,
            'wins': 0,
            'total_pnl': 0.0,
            'last_trade_time': 0.0,
        })
        # Latest selections per symbol for observability
        self.last_selections: Dict[str, List[ProfileScore]] = defaultdict(list)
        self.last_selection_ts: Dict[str, float] = defaultdict(float)
        self.selection_history: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        
        # Track why profiles are NOT selected (rejection reasons)
        self.last_rejections: Dict[str, List[ProfileScore]] = defaultdict(list)  # symbol -> rejected profiles
        self.rejection_counts: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))  # reason -> count
        
        # ML models (placeholder for future implementation)
        self.ml_models: Dict[str, Any] = {}
    
    def select_profiles(self, context: ContextVector, top_k: int = 3, symbol: Optional[str] = None) -> List[ProfileScore]:
        """
        Select top-K profiles for given context
        
        Profiles are selected dynamically based on market conditions only.
        Lifecycle state is NOT checked here - it's only used for performance tracking
        and auto-disable, not for blocking selection. Data readiness is already
        validated by DataReadinessStage before profile routing.
        
        Profile Router v2 Stability Integration (Requirements 2.1, 2.2, 2.3, 2.4, 2.5, 2.6):
        - Apply hysteresis to volatility_regime and trend_direction classification
        - Check TTL before allowing profile switch
        - Apply switch margin check
        - Handle safety disqualifier bypass
        - Update stability metrics
        
        Args:
            context: Market context vector
            top_k: Number of profiles to select
            symbol: Symbol for tracking purposes (optional)
            
        Returns:
            List of ProfileScore objects, sorted by score (highest first)
        """
        # Apply hysteresis to context if symbol is provided (Requirement 2.3)
        if symbol:
            context = self._apply_hysteresis_to_context(context, symbol)
        
        # Get all registered profile specs
        all_specs = self.registry.list_specs()
        
        # Score each profile and track rejections
        scores = []
        rejected = []
        safety_disqualified = False
        safety_reasons = []
        
        for spec in all_specs:
            # Score all profiles based on market conditions
            # Lifecycle state is NOT checked here - profiles are selected dynamically
            # Lifecycle is only used for performance tracking and auto-disable, not blocking selection
            score = self._score_profile(spec, context)
            if score.rule_passed:  # Only consider profiles that pass rule filters
                # Architectural guard: don't select profiles that have no enabled strategies
                # for this symbol (e.g., mean-reversion disabled per-symbol).
                if symbol:
                    enabled = enabled_strategies_for_symbol(getattr(spec, "strategy_ids", []) or [], symbol)
                    if not enabled:
                        score.rule_passed = False
                        score.reasons.append("no_enabled_strategies_for_symbol")
                        rejected.append(score)
                        if symbol:
                            self.rejection_counts[symbol]["no_enabled_strategies_for_symbol"] += 1
                        continue
                scores.append(score)
            else:
                rejected.append(score)
                # Track rejection reasons
                if symbol:
                    for reason in score.reasons:
                        # Extract the rejection type (e.g., "trend_mismatch", "vol_too_low")
                        reason_type = reason.split(':')[0] if ':' in reason else reason
                        self.rejection_counts[symbol][reason_type] += 1
                        
                        # Check for safety disqualifiers (Requirement 2.5)
                        if ProfileStabilityManager.is_safety_disqualifier(reason):
                            safety_disqualified = True
                            safety_reasons.append(reason)
        
        # Apply near-POC preference to avoid selecting distance-heavy profiles when price is at POC
        try:
            near_poc_threshold_bps = float(os.getenv("NEAR_POC_MAX_DISTANCE_BPS", "12"))
        except (TypeError, ValueError):
            near_poc_threshold_bps = 12.0
        try:
            near_poc_boost = float(os.getenv("NEAR_POC_SCORE_BOOST", "0.15"))
        except (TypeError, ValueError):
            near_poc_boost = 0.15
        preferred_profiles_env = os.getenv(
            "NEAR_POC_PREFERRED_PROFILES",
            "poc_magnet_profile,low_vol_grind_profile,spread_compression_profile",
        )
        preferred_profiles = {p.strip() for p in preferred_profiles_env.split(",") if p.strip()}
        preferred_tags = {"poc", "micro_range", "compression", "range"}
        distance_poc_bps = None
        if context.distance_to_poc_pct is not None:
            distance_poc_bps = abs(context.distance_to_poc_pct) * 10000.0
        if distance_poc_bps is not None and distance_poc_bps <= near_poc_threshold_bps:
            for score in scores:
                spec = self.registry.get_spec(score.profile_id)
                tags = {t.lower() for t in (spec.tags or [])} if spec else set()
                if score.profile_id in preferred_profiles or tags.intersection(preferred_tags):
                    score.score = min(1.0, score.score + near_poc_boost)
                    score.reasons.append("near_poc_preference_boost")
                else:
                    score.reasons.append("near_poc_deprioritized")
            logger.info(
                f"[{symbol or 'unknown'}] Near-POC preference applied "
                f"(distance_bps={distance_poc_bps:.2f}, threshold_bps={near_poc_threshold_bps:.2f})"
            )

        # US-open preference window: prioritize opening-playbook profiles only during
        # the configured UTC window, and lightly penalize them outside that window.
        if context.session == "us" and context.hour_utc is not None:
            open_window_enabled = _env_bool("PROFILE_US_OPEN_WINDOW_ENABLED", True)
            if open_window_enabled:
                start_hour = _parse_hour(os.getenv("PROFILE_US_OPEN_WINDOW_START_UTC", "13"), 13)
                end_hour = _parse_hour(os.getenv("PROFILE_US_OPEN_WINDOW_END_UTC", "16"), 16)
                in_open_window = _in_utc_hour_window(int(context.hour_utc), start_hour, end_hour)

                try:
                    open_boost = float(os.getenv("PROFILE_US_OPEN_WINDOW_SCORE_BOOST", "0.12"))
                except (TypeError, ValueError):
                    open_boost = 0.12
                try:
                    outside_penalty = float(os.getenv("PROFILE_US_OPEN_WINDOW_OUTSIDE_PENALTY", "0.08"))
                except (TypeError, ValueError):
                    outside_penalty = 0.08
                open_boost = max(0.0, open_boost)
                outside_penalty = max(0.0, outside_penalty)

                open_profiles_env = os.getenv(
                    "PROFILE_US_OPEN_WINDOW_PROFILE_IDS",
                    "us_open_momentum,opening_range_breakout",
                )
                open_profiles = {p.strip() for p in open_profiles_env.split(",") if p.strip()}

                if open_profiles:
                    for score in scores:
                        if score.profile_id not in open_profiles:
                            continue
                        if in_open_window:
                            score.score = min(1.0, score.score + open_boost)
                            score.reasons.append("us_open_window_boost")
                        else:
                            score.score = max(0.0, score.score - outside_penalty)
                            score.reasons.append("us_open_window_outside_penalty")
                    logger.info(
                        f"[{symbol or 'unknown'}] US-open preference applied "
                        f"(hour_utc={context.hour_utc}, window={start_hour}-{end_hour}, in_window={in_open_window})"
                    )

        # Sort by score (highest first)
        scores.sort(key=lambda s: s.score, reverse=True)
        
        # Log all profile scores for visibility (top 5)
        if symbol and scores:
            score_summary = ", ".join([f"{s.profile_id.replace('_profile', '')}={s.score:.3f}" for s in scores[:5]])
            logger.info(f"[{symbol}] Profile scores: {score_summary}")
        
        # Apply stability logic if symbol is provided (Requirements 2.1, 2.2, 2.4, 2.5, 2.6)
        selected = self._apply_stability_selection(
            scores=scores,
            symbol=symbol,
            top_k=top_k,
            safety_disqualified=safety_disqualified,
            safety_reasons=safety_reasons,
            context=context
        )
        
        # Remember latest selection and log
        if symbol:
            self.last_selections[symbol] = selected
            self.last_rejections[symbol] = rejected
            ts = time.time()
            self.last_selection_ts[symbol] = ts
            
            # Enhanced rejection logging (US-3, AC3.1, AC3.2)
            # Log all profile rejections at DEBUG level, limited to top 5 to avoid log spam
            if rejected:
                logger.debug(f"[{symbol}] Profile rejections ({len(rejected)} profiles):")
                for r in rejected[:5]:
                    logger.debug(f"  - {r.profile_id}: {r.reasons}")
                if len(rejected) > 5:
                    logger.debug(f"  ... and {len(rejected) - 5} more rejections")
            
            if selected:
                # Log selected profile at INFO level with score and session (US-3, AC3.1)
                stability_info = ""
                if selected[0].stability_adjusted:
                    stability_info = " [stability-adjusted]"
                logger.info(
                    f"[{symbol}] Profile selected: {selected[0].profile_id} "
                    f"(score={selected[0].score:.3f}, session={context.session}, hour_utc={context.hour_utc}){stability_info}"
                )
                history_entry = {
                    'timestamp': ts,
                    'profile_id': selected[0].profile_id,
                    'score': selected[0].score,
                    'confidence': selected[0].confidence,
                    'session': context.session,  # Store session for debugging
                    'stability_adjusted': selected[0].stability_adjusted,
                }
                self.selection_history[symbol].append(history_entry)
                if len(self.selection_history[symbol]) > 20:
                    self.selection_history[symbol] = self.selection_history[symbol][-20:]
            else:
                logger.warning(f"[{symbol}] No profiles matched (session={context.session}, rejected={len(rejected)})")
        return selected
    
    def _apply_hysteresis_to_context(self, context: ContextVector, symbol: str) -> ContextVector:
        """
        Apply hysteresis to context vector classifications.
        
        Implements Requirement 2.3: Hysteresis bands for threshold-based categories.
        
        Args:
            context: Original context vector
            symbol: Trading symbol
            
        Returns:
            Context vector with hysteresis-adjusted classifications
        """
        # Apply hysteresis to volatility regime
        hysteresis_vol_regime = self.hysteresis_tracker.get_volatility_regime(
            symbol=symbol,
            atr_ratio=context.atr_ratio,
            config=self.config
        )
        
        # Apply hysteresis to trend direction
        hysteresis_trend_direction = self.hysteresis_tracker.get_trend_direction(
            symbol=symbol,
            ema_spread_pct=context.ema_spread_pct,
            config=self.config
        )
        
        # Log if hysteresis changed the classification
        if hysteresis_vol_regime != context.volatility_regime:
            logger.debug(
                f"[{symbol}] Hysteresis adjusted volatility_regime: "
                f"{context.volatility_regime} -> {hysteresis_vol_regime}"
            )
        
        if hysteresis_trend_direction != context.trend_direction:
            logger.debug(
                f"[{symbol}] Hysteresis adjusted trend_direction: "
                f"{context.trend_direction} -> {hysteresis_trend_direction}"
            )
        
        # Create a new context with adjusted values
        # We use object.__setattr__ to avoid dataclass immutability issues
        # or create a new instance with updated values
        from dataclasses import replace
        return replace(
            context,
            volatility_regime=hysteresis_vol_regime,
            trend_direction=hysteresis_trend_direction
        )
    
    def infer_regime(self, market_context: Dict[str, Any]) -> RegimeInference:
        """
        Infer regime from market context with fallbacks.
        
        Implements Requirement 11: Explicit and non-lethal regime inference rules.
        
        This method:
        - Uses explicit threshold-based rules for regime classification
        - Falls back to default values when data is missing (NEVER rejects)
        - Tracks which fields were missing for diagnostics
        - Returns inference quality indicator
        
        Args:
            market_context: Dictionary containing market data:
                - volatility_percentile: 0.0-1.0 percentile of current volatility
                - trend_strength: Absolute trend strength (0.0-1.0)
                - spread_percentile: 0.0-1.0 percentile of current spread
                
        Returns:
            RegimeInference with inferred regimes and quality indicator
        """
        missing_fields: List[str] = []
        config = self.regime_inference_config
        
        def _safe_float(value: Any) -> Optional[float]:
            """Safely convert value to float, returning None on failure."""
            if value is None:
                return None
            try:
                return float(value)
            except (TypeError, ValueError):
                return None
        
        # Volatility regime inference
        vol_percentile = _safe_float(market_context.get("volatility_percentile"))
        if vol_percentile is not None:
            if vol_percentile < config.volatility_low_threshold:
                volatility_regime = "low"
            elif vol_percentile > config.volatility_high_threshold:
                volatility_regime = "high"
            else:
                volatility_regime = "normal"
        else:
            missing_fields.append("volatility_percentile")
            volatility_regime = "normal"  # Default: assume normal volatility
        
        # Trend regime inference
        trend_strength = _safe_float(market_context.get("trend_strength"))
        if trend_strength is not None:
            if abs(trend_strength) > config.trend_threshold:
                trend_regime = "trending"
            else:
                trend_regime = "ranging"
        else:
            missing_fields.append("trend_strength")
            trend_regime = "ranging"  # Default: assume ranging (conservative)
        
        # Spread regime inference
        spread_percentile = _safe_float(market_context.get("spread_percentile"))
        if spread_percentile is not None:
            if spread_percentile < config.spread_tight_threshold:
                spread_regime = "tight"
            elif spread_percentile > config.spread_wide_threshold:
                spread_regime = "wide"
            else:
                spread_regime = "normal"
        else:
            missing_fields.append("spread_percentile")
            spread_regime = "normal"  # Default: assume normal spread
        
        # Determine inference quality
        if not missing_fields:
            quality = "full"
        elif len(missing_fields) < 3:
            quality = "partial"
        else:
            quality = "default"
        
        return RegimeInference(
            volatility_regime=volatility_regime,
            trend_regime=trend_regime,
            spread_regime=spread_regime,
            inference_quality=quality,
            missing_fields=missing_fields,
        )
    
    def select_profile_with_regime(
        self,
        context: ContextVector,
        market_context: Optional[Dict[str, Any]] = None,
        symbol: Optional[str] = None,
    ) -> Tuple[str, RegimeInference]:
        """
        Select profile based on market regime with explicit inference.
        
        Implements Requirement 11: Non-lethal regime inference for profile selection.
        
        This method:
        - Infers regime from market context
        - Logs warnings for partial/default inference
        - Applies conservative profile selection for degraded inference
        - NEVER rejects - always returns a valid profile
        
        Args:
            context: Market context vector
            market_context: Optional dictionary with regime inference data
            symbol: Trading symbol for logging
            
        Returns:
            Tuple of (profile_id, RegimeInference)
        """
        # Infer regime from market context
        market_ctx = market_context or {}
        regime = self.infer_regime(market_ctx)
        
        # Log warning for degraded inference quality
        if regime.inference_quality != "full":
            logger.warning(
                f"[{symbol or 'unknown'}] Degraded regime inference: "
                f"quality={regime.inference_quality}, missing_fields={regime.missing_fields}"
            )
        
        # Select profiles using standard method
        selected = self.select_profiles(context, top_k=1, symbol=symbol)
        
        if selected:
            profile_id = selected[0].profile_id
            
            # Apply conservative profile selection for degraded inference
            if regime.inference_quality in ("partial", "default"):
                # For degraded inference, prefer conservative profiles
                # Log that we're using potentially suboptimal selection
                logger.info(
                    f"[{symbol or 'unknown'}] Using profile {profile_id} with "
                    f"degraded inference (quality={regime.inference_quality})"
                )
        else:
            profile_id = self.default_profile_id
            logger.warning(
                f"[{symbol or 'unknown'}] No profiles matched"
            )
        
        # Log regime inference results
        logger.info(
            f"[{symbol or 'unknown'}] Regime inference: "
            f"volatility={regime.volatility_regime}, "
            f"trend={regime.trend_regime}, "
            f"spread={regime.spread_regime}, "
            f"quality={regime.inference_quality}, "
            f"profile={profile_id}"
        )
        
        return profile_id, regime
    
    def _apply_stability_selection(
        self,
        scores: List[ProfileScore],
        symbol: Optional[str],
        top_k: int,
        safety_disqualified: bool,
        safety_reasons: List[str],
        context: ContextVector
    ) -> List[ProfileScore]:
        """
        Apply stability logic to profile selection.
        
        Implements Requirements 2.1, 2.2, 2.4, 2.5, 2.6:
        - Check TTL before allowing switch
        - Apply switch margin check
        - Handle safety disqualifier bypass
        - Update stability metrics
        
        Args:
            scores: Sorted list of profile scores (highest first)
            symbol: Trading symbol (optional)
            top_k: Number of profiles to select
            safety_disqualified: Whether a safety disqualifier triggered
            safety_reasons: List of safety disqualifier reasons
            context: Current market context
            
        Returns:
            List of selected ProfileScore objects
        """
        if not symbol or not scores:
            return scores[:top_k]
        
        current_time = context.timestamp if context.timestamp else time.time()
        
        # Get the top candidate
        top_candidate = scores[0]
        current_profile_id = self.stability_manager.get_current_profile(symbol)
        current_live_score = None
        if current_profile_id:
            current_aliases = {
                current_profile_id,
                _normalize_profile_id_alias(current_profile_id),
            }
            for score in scores:
                score_aliases = {
                    score.profile_id,
                    _normalize_profile_id_alias(score.profile_id),
                }
                if current_aliases & score_aliases:
                    current_live_score = score.score
                    break
        
        # Check if we should switch to the new profile
        should_switch = self.stability_manager.should_switch(
            symbol=symbol,
            new_profile_id=top_candidate.profile_id,
            new_score=top_candidate.score,
            current_live_score=current_live_score,
            current_time=current_time,
            safety_disqualified=safety_disqualified,
            safety_reasons=safety_reasons
        )
        
        if should_switch:
            # Record the new selection
            self.stability_manager.record_selection(
                symbol=symbol,
                profile_id=top_candidate.profile_id,
                score=top_candidate.score,
                current_time=current_time
            )
            return scores[:top_k]
        else:
            # Keep the current profile - find it in the scores list
            current_score = self.stability_manager.get_current_score(symbol)
            
            # Find the current profile in scores
            current_profile_score = None
            for score in scores:
                if score.profile_id == current_profile_id:
                    current_profile_score = score
                    break
            
            if current_profile_score:
                # Mark as stability-adjusted and return current profile first
                current_profile_score.stability_adjusted = True
                
                # Build result with current profile first, then others
                result = [current_profile_score]
                for score in scores:
                    if score.profile_id != current_profile_id and len(result) < top_k:
                        result.append(score)
                
                logger.debug(
                    f"[{symbol}] Stability: keeping {current_profile_id} "
                    f"(TTL or margin not met, top candidate was {top_candidate.profile_id})"
                )
                return result
            else:
                # Current profile no longer passes filters - allow switch
                # This handles the case where the current profile is now rejected
                self.stability_manager.record_selection(
                    symbol=symbol,
                    profile_id=top_candidate.profile_id,
                    score=top_candidate.score,
                    current_time=current_time
                )
                return scores[:top_k]
    
    def _score_profile(self, spec: ProfileSpec, context: ContextVector) -> ProfileScore:
        """
        Score a single profile against context
        
        Hybrid approach:
        1. Rule-based filters (hard constraints)
        2. v2 weighted scoring OR legacy base scoring (based on use_v2_scoring flag)
        3. ML scoring (if enabled)
        4. Performance-based adjustment
        
        Backward Compatibility (Requirement 10.5):
        - When use_v2_scoring=True (default): Use ComponentScorer and WeightedScoreAggregator
        - When use_v2_scoring=False: Use legacy _calculate_base_score method
        """
        reasons = []
        component_scores = {}
        cost_viability_score = 0.0
        
        # Step 1: Rule-based filtering
        rule_passed, rule_reasons = self._check_rule_filters(spec, context)
        reasons.extend(rule_reasons)
        
        if not rule_passed:
            return ProfileScore(
                profile_id=spec.id,
                score=0.0,
                confidence=0.0,
                reasons=reasons,
                rule_passed=False,
                hard_filter_passed=False,
            )
        
        # Step 2: Calculate base score
        # Backward Compatibility (Requirement 10.5): Use v2 or legacy scoring based on flag
        if self.config.use_v2_scoring:
            # v2 scoring: Use ComponentScorer and WeightedScoreAggregator
            scoring_result = self.weighted_score_aggregator.compute_weighted_score(
                conditions=spec.conditions,
                context=context,
                profile_tags=spec.tags,
            )
            base_score = scoring_result['final_score']
            component_scores = scoring_result['component_scores']
            cost_viability_score = component_scores.get('cost_viability_fit', 0.0)
            
            # Add top contributors to reasons for observability
            top_contributors = self.weighted_score_aggregator.get_top_contributors(
                scoring_result['weighted_contributions'], top_k=3
            )
            reasons.append(f"v2_score={base_score:.2f}")
            for comp, contrib in top_contributors:
                reasons.append(f"{comp}={component_scores.get(comp, 0):.2f}*{self.config.component_weights.get(comp, 0):.2f}")
        else:
            # Legacy scoring: Use _calculate_base_score
            base_score = self._calculate_base_score(spec.conditions, context)
            reasons.append(f"base_score={base_score:.2f}")
        
        # Step 3: ML scoring (if enabled)
        ml_score = None
        if self.enable_ml and spec.id in self.ml_models:
            ml_score = self._calculate_ml_score(spec, context)
            reasons.append(f"ml_score={ml_score:.2f}")
        
        # Step 4: Performance-based adjustment
        # Profile Router v2: Pass session for per-session tracking (Requirement 7.4)
        perf_multiplier = self._get_performance_multiplier(spec.id, context.symbol, context.session)
        reasons.append(f"perf_mult={perf_multiplier:.2f}")
        
        # Step 5: Combine scores
        if ml_score is not None:
            # Weighted average: 60% ML, 40% base
            final_score = (0.6 * ml_score + 0.4 * base_score) * perf_multiplier
        else:
            final_score = base_score * perf_multiplier
        
        # Clamp final score (Requirement 6.5)
        final_score = clamp_score(final_score)
        
        # Confidence based on data completeness and performance history
        perf_data = self.performance.get((spec.id, context.symbol), {})
        confidence = context.data_completeness
        if perf_data.get('trades', 0) >= 20:
            confidence *= 0.9  # High confidence with sufficient data
        else:
            confidence *= 0.5  # Lower confidence without history
        
        return ProfileScore(
            profile_id=spec.id,
            score=final_score,
            confidence=confidence,
            reasons=reasons,
            rule_passed=True,
            ml_score=ml_score,
            component_scores=component_scores,
            cost_viability_score=cost_viability_score,
            hard_filter_passed=True,
        )
    
    def _check_rule_filters(self, spec: ProfileSpec,
                            context: ContextVector) -> Tuple[bool, List[str]]:
        """
        Check if context passes all rule-based filters.
        
        Profile Router v2 Redesign (Requirements 3.1, 3.2, 5.5):
        - Hard filters are reserved for safety-critical "must-not-trade" conditions only
        - Soft preferences (trend, volatility, value_location, session) affect scoring, not rejection
        - Cost viability hard rejection at 2x threshold
        
        Returns: (passed, reasons)
        """
        reasons = []
        
        # Step 1: Check safety-critical hard filters (Requirements 3.1, 3.2)
        # These are "must-not-trade" conditions that cause immediate rejection
        hard_passed, hard_reasons = self._check_safety_hard_filters(spec, context, self.config)
        reasons.extend(hard_reasons)
        
        if not hard_passed:
            return False, reasons
        
        # Step 2: Check cost viability hard rejection (Requirement 5.5)
        # Hard reject when expected_cost_bps >= 2x max_viable_cost_bps
        cost_passed, cost_reasons = self._check_cost_viability_hard_filter(spec, context)
        reasons.extend(cost_reasons)
        
        if not cost_passed:
            return False, reasons
        
        # Step 3: Check explicit regime hard constraint (Requirement 1.4)
        # Only profiles with explicitly specified allowed_regimes use hard filtering
        regime_passed, regime_reasons = self._check_explicit_regime_constraint(spec, context)
        reasons.extend(regime_reasons)
        
        if not regime_passed:
            return False, reasons

        # Step 4: Required session is a hard eligibility constraint.
        #
        # Rationale:
        # - Many profiles are explicitly session-scoped (e.g., asia_range_scalp).
        # - Treating required_session as soft can select the wrong profile during the wrong session,
        #   which is confusing operationally and generally degrades expectancy.
        conditions = spec.conditions
        if conditions.required_session and conditions.required_session != context.session:
            return False, [
                f"required_session_mismatch: required_session={conditions.required_session}, current_session={context.session}"
            ]
        
        # All hard filters passed
        # Note: Trend, volatility, value_location, session are now soft preferences
        # handled by ComponentScorer, not hard filters (Requirement 3.2)
        reasons.append("all_rules_passed")
        return True, reasons
    
    def _check_safety_hard_filters(
        self,
        spec: ProfileSpec,
        context: ContextVector,
        config: Optional['RouterConfig'] = None
    ) -> Tuple[bool, List[str]]:
        """
        Check safety-critical hard filters only.
        
        Profile Router v2 (Requirements 3.1, 3.2):
        Hard filters are reserved for "must-not-trade" conditions:
        - spread_bps > max_safe_spread_bps (default: 50)
        - total_depth_usd < min_safe_depth_usd (default: 10000)
        - trades_per_second < min_safe_tps (default: 0.1)
        - book_age_ms > max_book_age_ms (default: 5000)
        - trade_age_ms > max_trade_age_ms (default: 10000)
        - risk_mode in ["off", "protection"]
        
        All other conditions (trend, volatility, value_location, session) are
        converted to soft preferences that affect scoring but NOT rejection.
        
        Args:
            spec: Profile specification
            context: Current market context
            config: Optional RouterConfig for thresholds (uses defaults if None)
            
        Returns:
            (passed, reasons) tuple
        """
        from quantgambit.deeptrader_core.profiles.router_config import RouterConfig
        
        # Use provided config or defaults
        if config is None:
            config = RouterConfig()
        
        reasons = []
        conditions = spec.conditions
        
        # 1. Spread check (safety-critical)
        spread_bps = context.spread_bps if context.spread_bps is not None else 0.0
        if spread_bps > config.max_safe_spread_bps:
            return False, [f"spread_too_wide: {spread_bps:.1f}bp > {config.max_safe_spread_bps:.1f}bp (safety limit)"]
        
        # 2. Depth check (safety-critical)
        bid_depth = context.bid_depth_usd if context.bid_depth_usd is not None else 0.0
        ask_depth = context.ask_depth_usd if context.ask_depth_usd is not None else 0.0
        total_depth = bid_depth + ask_depth
        if total_depth < config.min_safe_depth_usd:
            return False, [f"depth_too_low: ${total_depth:.0f} < ${config.min_safe_depth_usd:.0f} (safety limit)"]
        
        # 3. TPS check (safety-critical)
        # Skip in backtesting mode - historical data doesn't have real-time trade flow
        if not config.backtesting_mode:
            tps = context.trades_per_second if context.trades_per_second is not None else 0.0
            if tps < config.min_safe_tps:
                return False, [f"tps_too_low: {tps:.2f} < {config.min_safe_tps:.2f} (safety limit)"]
        
        # 4. Book age check (safety-critical - stale data)
        # Skip in backtesting mode - historical data will always be "stale"
        if not config.backtesting_mode:
            book_age_ms = context.book_age_ms if context.book_age_ms is not None else 0.0
            if book_age_ms > config.max_book_age_ms:
                return False, [f"book_data_stale: {book_age_ms:.0f}ms > {config.max_book_age_ms:.0f}ms (safety limit)"]
        
        # 5. Trade age check (safety-critical - stale data)
        # Skip in backtesting mode - historical data will always be "stale"
        if not config.backtesting_mode:
            trade_age_ms = context.trade_age_ms if context.trade_age_ms is not None else 0.0
            if trade_age_ms > config.max_trade_age_ms:
                return False, [f"trade_data_stale: {trade_age_ms:.0f}ms > {config.max_trade_age_ms:.0f}ms (safety limit)"]
        
        # 6. Risk mode check (safety-critical)
        risk_mode = context.risk_mode if context.risk_mode else "normal"
        if risk_mode in ["off", "protection"]:
            return False, [f"risk_mode_unsafe: {risk_mode} (trading disabled)"]
        
        # All safety hard filters passed
        return True, reasons
    
    def _check_cost_viability_hard_filter(
        self,
        spec: ProfileSpec,
        context: ContextVector
    ) -> Tuple[bool, List[str]]:
        """
        Check cost viability hard rejection threshold.
        
        Requirement 5.5: Hard reject when expected_cost_bps >= 2x max_viable_cost_bps
        
        Max viable cost depends on profile type:
        - Mean-reversion profiles: 8 bps
        - Momentum/taker profiles: 15 bps (12 in non-high volatility)
        - Default: 10 bps
        
        Args:
            spec: Profile specification
            context: Current market context
            
        Returns:
            (passed, reasons) tuple
        """
        # Determine max viable cost based on profile tags
        tags = spec.tags or []
        normalized_tags = {str(tag).lower() for tag in tags}
        
        # Mean-reversion tags
        mean_revert_tags = {
            "mean_reversion", "mean-reversion", "fade", "range", "reversal",
            "contrarian", "vwap", "reversion"
        }
        # Momentum tags
        momentum_tags = {
            "momentum", "breakout", "trend", "volatility", "taker"
        }
        
        is_mean_revert = bool(normalized_tags & mean_revert_tags)
        is_momentum = bool(normalized_tags & momentum_tags)
        
        if is_mean_revert:
            max_viable_cost = 8.0
        elif is_momentum:
            # Momentum profiles can tolerate higher costs in high volatility
            if context.volatility_regime == "high":
                max_viable_cost = 15.0
            else:
                max_viable_cost = 12.0
        else:
            max_viable_cost = 10.0
        
        # Hard rejection threshold: 2x max viable cost (Requirement 5.5)
        hard_rejection_threshold = 2 * max_viable_cost
        expected_cost = context.expected_cost_bps if context.expected_cost_bps is not None else 0.0
        
        if expected_cost >= hard_rejection_threshold:
            return False, [
                f"cost_too_high: {expected_cost:.1f}bp >= {hard_rejection_threshold:.1f}bp "
                f"(2x max_viable={max_viable_cost:.1f}bp)"
            ]
        
        return True, []
    
    def _check_explicit_regime_constraint(
        self,
        spec: ProfileSpec,
        context: ContextVector
    ) -> Tuple[bool, List[str]]:
        """
        Check explicit regime hard constraint.
        
        Requirement 1.4: Only profiles with explicitly specified 
        ProfileConditions.allowed_regimes use hard filtering for regime.
        Tag-inferred regime allowlists are soft scoring factors, not hard constraints.
        
        Args:
            spec: Profile specification
            context: Current market context
            
        Returns:
            (passed, reasons) tuple
        """
        conditions = spec.conditions
        
        # Only check if profile explicitly specifies allowed_regimes
        # Tag-inferred regimes are handled as soft preferences in scoring
        if conditions.allowed_regimes:
            allowed = {str(item).lower() for item in conditions.allowed_regimes if item}
            current = {str(context.market_regime).lower(), str(context.regime_family).lower()}
            
            # Remove "unknown" values - they should not block matching
            current.discard("unknown")
            current.discard("none")
            
            # If we have no known regime info, allow the profile to proceed
            # This prevents profiles from being blocked when data is incomplete
            if current and not (current & allowed):
                return False, [f"regime_mismatch: explicit allowed_regimes={list(allowed)}, current={list(current)}"]
        
        return True, []
    
    def _calculate_base_score(self, conditions: ProfileConditions, 
                             context: ContextVector) -> float:
        """
        Calculate base score from how well context matches conditions
        
        Returns: 0.0 to 1.0
        """
        score = 0.5  # Start at neutral
        
        # Trend alignment bonus
        if conditions.required_trend == context.trend_direction:
            score += 0.1
        
        # Volatility alignment bonus
        if conditions.required_volatility == context.volatility_regime:
            score += 0.1
        
        # Value location alignment bonus
        if conditions.required_value_location == context.position_in_value:
            score += 0.1
        
        # Session alignment bonus
        if conditions.required_session == context.session:
            score += 0.1
        
        # Rotation strength bonus
        if conditions.min_rotation_factor is not None:
            rotation_excess = context.rotation_factor - conditions.min_rotation_factor
            if rotation_excess > 0:
                score += min(0.1, rotation_excess / 10.0)  # Up to 0.1 bonus
        
        # Spread tightness bonus
        if conditions.max_spread is not None:
            spread_margin = (conditions.max_spread * 10000) - context.spread_bps
            if spread_margin > 0:
                score += min(0.1, spread_margin / 50.0)  # Up to 0.1 bonus
        
        return min(1.0, max(0.0, score))
    
    def _calculate_ml_score(self, spec: ProfileSpec, context: ContextVector) -> float:
        """
        Calculate ML-based score (placeholder for future implementation)
        
        This would use a trained model to predict profile profitability
        given the current context.
        """
        # TODO: Implement ML scoring
        # For now, return base score
        return 0.5
    
    def _get_performance_multiplier(self, profile_id: str, symbol: str, session: str = "us") -> float:
        """
        Adjust score based on historical performance with exponential decay.
        
        Profile Router v2 (Requirements 7.1, 7.2, 7.3, 7.4, 7.5):
        - Require minimum 20 trades before applying performance multiplier (7.1)
        - Cap multiplier to [0.7, 1.3] (7.2)
        - Apply exponential decay with 50-trade half-life (7.3)
        - Track per (profile_id, symbol, session) tuple (7.4)
        - Use neutral multiplier of 1.0 for profiles with < 20 trades (7.5)
        
        Args:
            profile_id: Profile identifier
            symbol: Trading symbol
            session: Trading session ('asia', 'europe', 'us', 'overnight')
            
        Returns:
            Performance multiplier in range [0.7, 1.3]
        """
        key = (profile_id, symbol, session)
        perf = self.performance_v2.get(key)
        
        # Requirement 7.5: Neutral multiplier for insufficient data
        min_trades = self.config.min_trades_for_perf_adjustment
        if not perf or perf['total_trades'] < min_trades:
            return 1.0
        
        # Get multiplier bounds from config
        min_mult, max_mult = self.config.perf_multiplier_range
        half_life = self.config.perf_decay_half_life_trades
        
        # Calculate decay-weighted win rate and PnL
        # Requirement 7.3: Exponential decay with configurable half-life
        trades = perf['trades']
        if not trades:
            return 1.0
        
        # Calculate weights using exponential decay
        # Most recent trade has weight 1.0, trade N trades ago has weight 0.5^(N/half_life)
        total_weight = 0.0
        weighted_wins = 0.0
        weighted_pnl = 0.0
        
        num_trades = len(trades)
        for i, (timestamp, pnl, is_win) in enumerate(trades):
            # i=0 is oldest, i=num_trades-1 is newest
            trades_ago = num_trades - 1 - i
            # Decay factor: 0.5^(trades_ago / half_life)
            decay_factor = math.pow(0.5, trades_ago / half_life)
            
            total_weight += decay_factor
            if is_win:
                weighted_wins += decay_factor
            weighted_pnl += pnl * decay_factor
        
        if total_weight == 0:
            return 1.0
        
        # Calculate decay-weighted win rate
        weighted_win_rate = weighted_wins / total_weight
        
        # Calculate multiplier based on win rate
        # Win rate of 0.5 -> multiplier of 1.0
        # Win rate of 1.0 -> multiplier of max_mult
        # Win rate of 0.0 -> multiplier of min_mult
        multiplier = min_mult + (max_mult - min_mult) * weighted_win_rate
        
        # Bonus for positive weighted PnL
        weighted_avg_pnl = weighted_pnl / total_weight
        if weighted_avg_pnl > 0:
            multiplier += 0.05  # Small bonus for positive PnL
        elif weighted_avg_pnl < 0:
            multiplier -= 0.05  # Small penalty for negative PnL
        
        # Requirement 7.2: Cap to configured range
        return min(max_mult, max(min_mult, multiplier))
    
    def record_trade(self, profile_id: str, symbol: str, pnl: float, session: str = "us") -> None:
        """
        Record trade result for performance tracking.
        
        Profile Router v2 (Requirements 7.3, 7.4):
        - Track per (profile_id, symbol, session) tuple
        - Store individual trades for decay calculation
        
        Args:
            profile_id: Profile identifier
            symbol: Trading symbol
            pnl: Trade profit/loss
            session: Trading session ('asia', 'europe', 'us', 'overnight')
        """
        current_time = time.time()
        is_win = pnl > 0
        
        # Update v2 performance tracking (per profile/symbol/session)
        key_v2 = (profile_id, symbol, session)
        perf_v2 = self.performance_v2[key_v2]
        perf_v2['trades'].append((current_time, pnl, is_win))
        perf_v2['total_trades'] += 1
        if is_win:
            perf_v2['total_wins'] += 1
        perf_v2['total_pnl'] += pnl
        
        # Limit stored trades to prevent unbounded memory growth
        # Keep last 200 trades (enough for decay calculation with 50-trade half-life)
        max_stored_trades = 200
        if len(perf_v2['trades']) > max_stored_trades:
            perf_v2['trades'] = perf_v2['trades'][-max_stored_trades:]
        
        # Update legacy performance tracking for backward compatibility
        key = (profile_id, symbol)
        perf = self.performance[key]
        perf['trades'] += 1
        if is_win:
            perf['wins'] += 1
        perf['total_pnl'] += pnl
        perf['last_trade_time'] = current_time
    
    def get_performance_stats(self, profile_id: str, symbol: str, session: Optional[str] = None) -> Dict[str, Any]:
        """
        Get performance statistics for a profile on a symbol.
        
        Args:
            profile_id: Profile identifier
            symbol: Trading symbol
            session: Optional session filter. If None, returns aggregated stats.
            
        Returns:
            Dictionary with performance statistics
        """
        if session is not None:
            # Return v2 per-session stats
            key = (profile_id, symbol, session)
            perf = self.performance_v2.get(key)
            if not perf or perf['total_trades'] == 0:
                return {
                    'trades': 0,
                    'win_rate': 0.0,
                    'avg_pnl': 0.0,
                    'total_pnl': 0.0,
                    'session': session,
                }
            
            return {
                'trades': perf['total_trades'],
                'win_rate': perf['total_wins'] / perf['total_trades'],
                'avg_pnl': perf['total_pnl'] / perf['total_trades'],
                'total_pnl': perf['total_pnl'],
                'session': session,
            }
        
        # Return legacy aggregated stats (backward compatibility)
        perf = self.performance.get((profile_id, symbol))
        if not perf:
            return {
                'trades': 0,
                'win_rate': 0.0,
                'avg_pnl': 0.0,
                'total_pnl': 0.0,
            }
        
        return {
            'trades': perf['trades'],
            'win_rate': perf['wins'] / perf['trades'] if perf['trades'] > 0 else 0.0,
            'avg_pnl': perf['total_pnl'] / perf['trades'] if perf['trades'] > 0 else 0.0,
            'total_pnl': perf['total_pnl'],
            'last_trade_time': perf['last_trade_time'],
        }


    def get_all_metrics(self) -> Dict[str, Any]:
        """
        Get comprehensive router metrics for dashboard.
        
        Profile Router v2 (Requirement 8.1) adds:
        - eligible_profiles_count: Number of profiles passing hard filters
        - profile_switches_count: Per-symbol switch counts
        - avg_profile_duration_sec: Per-symbol average profile duration
        - component_score_distributions: Distribution stats per component
        - rejection_reasons_histogram: Reason -> count mapping
        
        Returns:
            Dictionary with all router metrics
        """
        # Aggregate performance across all profiles and symbols
        total_trades = 0
        total_wins = 0
        total_pnl = 0.0
        profile_stats = {}
        
        for (profile_id, symbol), perf in self.performance.items():
            total_trades += perf['trades']
            total_wins += perf['wins']
            total_pnl += perf['total_pnl']
            
            # Per-profile aggregation
            if profile_id not in profile_stats:
                profile_stats[profile_id] = {
                    'trades': 0,
                    'wins': 0,
                    'total_pnl': 0.0,
                    'symbols': []
                }
            profile_stats[profile_id]['trades'] += perf['trades']
            profile_stats[profile_id]['wins'] += perf['wins']
            profile_stats[profile_id]['total_pnl'] += perf['total_pnl']
            if symbol not in profile_stats[profile_id]['symbols']:
                profile_stats[profile_id]['symbols'].append(symbol)
        
        # Calculate aggregated metrics
        overall_win_rate = (total_wins / total_trades * 100) if total_trades > 0 else 0.0
        avg_pnl_per_trade = total_pnl / total_trades if total_trades > 0 else 0.0
        
        # Top performing profiles
        top_profiles = []
        for profile_id, stats in profile_stats.items():
            if stats['trades'] > 0:
                win_rate = (stats['wins'] / stats['trades']) * 100
                avg_pnl = stats['total_pnl'] / stats['trades']
                top_profiles.append({
                    'profile_id': profile_id,
                    'trades': stats['trades'],
                    'win_rate': win_rate,
                    'avg_pnl': avg_pnl,
                    'total_pnl': stats['total_pnl'],
                    'symbols': stats['symbols']
                })
        
        # Sort by total PnL
        top_profiles.sort(key=lambda x: x['total_pnl'], reverse=True)
        
        live_top_profiles = []
        for symbol_name, selections in self.last_selections.items():
            if not selections:
                continue
            entry = {
                'profile_id': selections[0].profile_id,
                'symbol': symbol_name,
                'score': selections[0].score,
                'confidence': selections[0].confidence,
                'timestamp': self.last_selection_ts.get(symbol_name)
            }
            live_top_profiles.append(entry)
        live_top_profiles.sort(key=lambda x: x['score'], reverse=True)

        selection_history = {
            symbol: history[-5:]
            for symbol, history in self.selection_history.items()
            if history
        }
        
        # Aggregate rejection data
        rejection_summary = {}
        for symbol, rejections in self.last_rejections.items():
            if rejections:
                rejection_summary[symbol] = [
                    {
                        'profile_id': r.profile_id,
                        'reasons': r.reasons[:3]  # Limit to first 3 reasons
                    }
                    for r in rejections[:10]  # Limit to 10 rejections per symbol
                ]
        
        # Top rejection reasons across all symbols
        all_rejection_reasons = defaultdict(int)
        for symbol, counts in self.rejection_counts.items():
            for reason, count in counts.items():
                all_rejection_reasons[reason] += count
        
        top_rejection_reasons = sorted(
            all_rejection_reasons.items(),
            key=lambda x: x[1],
            reverse=True
        )[:10]
        
        # Stability metrics (Requirement 2.6)
        stability_metrics = self.stability_manager.get_all_metrics()
        
        # ============================================================
        # Profile Router v2 Metrics (Requirement 8.1)
        # ============================================================
        
        # 1. eligible_profiles_count: Count profiles that passed hard filters
        #    This is tracked per symbol from last_selections
        eligible_profiles_count = self._compute_eligible_profiles_count()
        
        # 2. profile_switches_count: Per-symbol switch counts from stability manager
        profile_switches_count = {}
        for symbol, metrics in stability_metrics.items():
            profile_switches_count[symbol] = metrics.get('switch_count', 0)
        
        # 3. avg_profile_duration_sec: Per-symbol average duration from stability manager
        avg_profile_duration_sec = {}
        for symbol, metrics in stability_metrics.items():
            avg_profile_duration_sec[symbol] = metrics.get('avg_duration_sec', 0.0)
        
        # 4. component_score_distributions: Distribution stats per component
        component_score_distributions = self._compute_component_score_distributions()
        
        # 5. rejection_reasons_histogram: Full histogram of rejection reasons
        rejection_reasons_histogram = dict(all_rejection_reasons)
        
        # 6. scored_profiles_count: Profiles with score > 0 per symbol
        scored_profiles_count = {}
        for symbol, selections in self.last_selections.items():
            scored_profiles_count[symbol] = len([s for s in selections if s.score > 0])

        return {
            'total_trades': total_trades,
            'total_wins': total_wins,
            'overall_win_rate': overall_win_rate,
            'total_pnl': total_pnl,
            'avg_pnl_per_trade': avg_pnl_per_trade,
            'active_profiles': len(profile_stats),
            'registered_profiles': len(self.registry.list_specs()),
            'ml_enabled': self.enable_ml,
            'top_profiles': top_profiles[:5],  # Top 5 performers
            'live_top_profiles': live_top_profiles[:5],
            'selection_history': selection_history,
            'rejection_summary': rejection_summary,
            'top_rejection_reasons': top_rejection_reasons,
            'stability_metrics': stability_metrics,  # v2: per-symbol stability metrics
            # Profile Router v2 additions (Requirement 8.1)
            'eligible_profiles_count': eligible_profiles_count,
            'profile_switches_count': profile_switches_count,
            'avg_profile_duration_sec': avg_profile_duration_sec,
            'component_score_distributions': component_score_distributions,
            'rejection_reasons_histogram': rejection_reasons_histogram,
            'scored_profiles_count': scored_profiles_count,
        }
    
    def _compute_eligible_profiles_count(self) -> Dict[str, int]:
        """
        Compute eligible profiles count per symbol.
        
        Eligible profiles are those that passed hard filters (rule_passed=True).
        
        Returns:
            Dictionary mapping symbol to eligible profile count
        """
        eligible_count = {}
        
        # Count from last_selections (profiles that passed filters)
        for symbol, selections in self.last_selections.items():
            eligible_count[symbol] = len(selections)
        
        return eligible_count
    
    def _compute_component_score_distributions(self) -> Dict[str, Dict[str, float]]:
        """
        Compute distribution statistics for component scores.
        
        Aggregates component scores from recent selections to provide
        min, max, mean, and count for each component.
        
        Returns:
            Dictionary mapping component name to distribution stats:
            {
                'trend_fit': {'min': 0.2, 'max': 0.9, 'mean': 0.55, 'count': 10},
                ...
            }
        """
        # Collect all component scores from recent selections
        component_values: Dict[str, List[float]] = defaultdict(list)
        
        for symbol, selections in self.last_selections.items():
            for score in selections:
                if score.component_scores:
                    for component, value in score.component_scores.items():
                        component_values[component].append(value)
        
        # Compute distribution stats for each component
        distributions = {}
        for component, values in component_values.items():
            if values:
                distributions[component] = {
                    'min': min(values),
                    'max': max(values),
                    'mean': sum(values) / len(values),
                    'count': len(values),
                }
            else:
                distributions[component] = {
                    'min': 0.0,
                    'max': 0.0,
                    'mean': 0.0,
                    'count': 0,
                }
        
        return distributions
    
    def get_routing_diagnostics(self, symbol: str) -> Dict[str, Any]:
        """
        Get full routing diagnostics for a symbol.
        
        Returns comprehensive scoring breakdown including:
        - All component scores for top profiles
        - Rejection reasons for all profiles
        - Current stability state
        - Performance multipliers
        
        Implements Requirement 8.5.
        
        Args:
            symbol: Trading symbol to get diagnostics for
            
        Returns:
            Dictionary with full routing diagnostics:
            {
                'symbol': str,
                'timestamp': float,
                'top_profiles': [
                    {
                        'profile_id': str,
                        'score': float,
                        'confidence': float,
                        'component_scores': Dict[str, float],
                        'cost_viability_score': float,
                        'stability_adjusted': bool,
                        'hard_filter_passed': bool,
                        'performance_multiplier': float,
                        'reasons': List[str],
                    },
                    ...
                ],
                'rejected_profiles': [
                    {
                        'profile_id': str,
                        'rejection_reasons': List[str],
                        'hard_filter_passed': bool,
                    },
                    ...
                ],
                'stability_state': {
                    'current_profile': str,
                    'time_active_sec': float,
                    'switch_count': int,
                    'avg_duration_sec': float,
                    'within_ttl': bool,
                },
                'eligible_count': int,
                'rejected_count': int,
                'total_registered': int,
            }
        """
        diagnostics = {
            'symbol': symbol,
            'timestamp': time.time(),
            'top_profiles': [],
            'rejected_profiles': [],
            'stability_state': {},
            'eligible_count': 0,
            'rejected_count': 0,
            'total_registered': len(self.registry.list_specs()),
        }
        
        # Get top profiles with full scoring breakdown
        selections = self.last_selections.get(symbol, [])
        for score in selections:
            profile_diag = {
                'profile_id': score.profile_id,
                'score': score.score,
                'confidence': score.confidence,
                'component_scores': score.component_scores.copy() if score.component_scores else {},
                'cost_viability_score': score.cost_viability_score,
                'stability_adjusted': score.stability_adjusted,
                'hard_filter_passed': score.hard_filter_passed,
                'performance_multiplier': self._get_performance_multiplier(
                    score.profile_id, symbol, "us"  # Default session for diagnostics
                ),
                'reasons': score.reasons.copy() if score.reasons else [],
            }
            diagnostics['top_profiles'].append(profile_diag)
        
        diagnostics['eligible_count'] = len(selections)
        
        # Get rejected profiles with rejection reasons
        rejections = self.last_rejections.get(symbol, [])
        for score in rejections:
            rejection_diag = {
                'profile_id': score.profile_id,
                'rejection_reasons': score.reasons.copy() if score.reasons else [],
                'hard_filter_passed': score.hard_filter_passed,
            }
            diagnostics['rejected_profiles'].append(rejection_diag)
        
        diagnostics['rejected_count'] = len(rejections)
        
        # Get stability state
        stability_metrics = self.stability_manager.get_metrics(symbol)
        diagnostics['stability_state'] = {
            'current_profile': stability_metrics.get('current_profile'),
            'time_active_sec': stability_metrics.get('time_active_sec', 0.0),
            'switch_count': stability_metrics.get('switch_count', 0),
            'avg_duration_sec': stability_metrics.get('avg_duration_sec', 0.0),
            'within_ttl': self.stability_manager.is_within_ttl(symbol),
        }
        
        return diagnostics
    
    def get_stability_metrics(self, symbol: Optional[str] = None) -> Dict[str, Any]:
        """
        Get stability metrics for profile selection.
        
        Implements Requirement 2.6.
        
        Args:
            symbol: Optional symbol to get metrics for. If None, returns all symbols.
            
        Returns:
            Dictionary with stability metrics
        """
        if symbol:
            return self.stability_manager.get_metrics(symbol)
        return self.stability_manager.get_all_metrics()
    
    def reset_stability(self, symbol: Optional[str] = None) -> None:
        """
        Reset stability state.
        
        Args:
            symbol: Optional symbol to reset. If None, resets all symbols.
        """
        if symbol:
            self.stability_manager.reset_symbol(symbol)
            self.hysteresis_tracker.reset_symbol(symbol)
        else:
            self.stability_manager.reset_all()
            self.hysteresis_tracker.reset_all()
    
    def update_config(self, config: 'RouterConfig') -> None:
        """
        Update router configuration at runtime.
        
        Implements Requirements 9.2, 9.4:
        - Validate new config
        - Apply changes to all sub-components
        - Log config changes at INFO level
        
        Args:
            config: New RouterConfig to apply
            
        Raises:
            ValueError: If the new config is invalid
        """
        from quantgambit.deeptrader_core.profiles.router_config import RouterConfig
        
        # Step 1: Validate new config (Requirement 9.3)
        # This will raise ValueError if invalid
        config.validate()
        
        # Step 2: Log config changes at INFO level (Requirement 9.4)
        old_config = self.config
        changes = []
        
        # Track stability parameter changes
        if old_config.min_profile_ttl_sec != config.min_profile_ttl_sec:
            changes.append(f"min_profile_ttl_sec: {old_config.min_profile_ttl_sec} -> {config.min_profile_ttl_sec}")
        
        if old_config.switch_margin != config.switch_margin:
            changes.append(f"switch_margin: {old_config.switch_margin} -> {config.switch_margin}")
        
        # Track hard filter threshold changes
        if old_config.max_safe_spread_bps != config.max_safe_spread_bps:
            changes.append(f"max_safe_spread_bps: {old_config.max_safe_spread_bps} -> {config.max_safe_spread_bps}")
        
        if old_config.min_safe_depth_usd != config.min_safe_depth_usd:
            changes.append(f"min_safe_depth_usd: {old_config.min_safe_depth_usd} -> {config.min_safe_depth_usd}")
        
        if old_config.min_safe_tps != config.min_safe_tps:
            changes.append(f"min_safe_tps: {old_config.min_safe_tps} -> {config.min_safe_tps}")
        
        if old_config.max_book_age_ms != config.max_book_age_ms:
            changes.append(f"max_book_age_ms: {old_config.max_book_age_ms} -> {config.max_book_age_ms}")
        
        if old_config.max_trade_age_ms != config.max_trade_age_ms:
            changes.append(f"max_trade_age_ms: {old_config.max_trade_age_ms} -> {config.max_trade_age_ms}")
        
        # Track hysteresis band changes
        if old_config.vol_regime_low_band != config.vol_regime_low_band:
            changes.append(f"vol_regime_low_band: {old_config.vol_regime_low_band} -> {config.vol_regime_low_band}")
        
        if old_config.vol_regime_high_band != config.vol_regime_high_band:
            changes.append(f"vol_regime_high_band: {old_config.vol_regime_high_band} -> {config.vol_regime_high_band}")
        
        if old_config.trend_direction_band != config.trend_direction_band:
            changes.append(f"trend_direction_band: {old_config.trend_direction_band} -> {config.trend_direction_band}")
        
        # Track performance adjustment changes
        if old_config.min_trades_for_perf_adjustment != config.min_trades_for_perf_adjustment:
            changes.append(f"min_trades_for_perf_adjustment: {old_config.min_trades_for_perf_adjustment} -> {config.min_trades_for_perf_adjustment}")
        
        if old_config.perf_multiplier_range != config.perf_multiplier_range:
            changes.append(f"perf_multiplier_range: {old_config.perf_multiplier_range} -> {config.perf_multiplier_range}")
        
        if old_config.perf_decay_half_life_trades != config.perf_decay_half_life_trades:
            changes.append(f"perf_decay_half_life_trades: {old_config.perf_decay_half_life_trades} -> {config.perf_decay_half_life_trades}")
        
        # Track regime mapping changes
        if old_config.regime_soft_penalty != config.regime_soft_penalty:
            changes.append(f"regime_soft_penalty: {old_config.regime_soft_penalty} -> {config.regime_soft_penalty}")
        
        if old_config.squeeze_liquidity_threshold != config.squeeze_liquidity_threshold:
            changes.append(f"squeeze_liquidity_threshold: {old_config.squeeze_liquidity_threshold} -> {config.squeeze_liquidity_threshold}")
        
        if old_config.chop_cost_threshold_bps != config.chop_cost_threshold_bps:
            changes.append(f"chop_cost_threshold_bps: {old_config.chop_cost_threshold_bps} -> {config.chop_cost_threshold_bps}")
        
        if old_config.trend_strength_for_range_to_trend != config.trend_strength_for_range_to_trend:
            changes.append(f"trend_strength_for_range_to_trend: {old_config.trend_strength_for_range_to_trend} -> {config.trend_strength_for_range_to_trend}")
        
        # Track component weight changes
        if old_config.component_weights != config.component_weights:
            changes.append(f"component_weights: updated")
        
        # Track feature flag changes
        if old_config.use_v2_scoring != config.use_v2_scoring:
            changes.append(f"use_v2_scoring: {old_config.use_v2_scoring} -> {config.use_v2_scoring}")
        
        # Log changes
        if changes:
            logger.info(f"ProfileRouter config updated: {', '.join(changes)}")
        else:
            logger.info("ProfileRouter config updated (no changes detected)")
        
        # Step 3: Apply changes to all sub-components (Requirement 9.2)
        self.config = config
        
        # Update stability manager config
        self.stability_manager.update_config(config)
        
        # Update weighted score aggregator config (Requirement 10.5)
        self.weighted_score_aggregator = WeightedScoreAggregator(config)
        
        # Note: HysteresisTracker doesn't store config - it receives config
        # as a parameter in get_volatility_regime() and get_trend_direction()
        # so it will automatically use the new config on next call
    
    def get_config(self) -> 'RouterConfig':
        """
        Get the current router configuration.
        
        Returns:
            Current RouterConfig
        """
        return self.config


# Global router instance
_profile_router: Optional[ProfileRouter] = None


def get_profile_router(
    enable_ml: bool = False,
    config: Optional['RouterConfig'] = None,
    force_new: bool = False,
) -> ProfileRouter:
    """Get or create global profile router instance.
    
    Args:
        enable_ml: Enable ML scoring (default: False)
        config: Optional RouterConfig. If provided with force_new=True,
                creates a new router with this config.
        force_new: If True, creates a new router instance instead of
                   returning the cached one. Useful for backtesting.
    
    Returns:
        ProfileRouter instance
    """
    global _profile_router
    
    if force_new and config is not None:
        # Create a new router with the provided config (for backtesting)
        return ProfileRouter(enable_ml=enable_ml, config=config)
    
    if _profile_router is None:
        _profile_router = ProfileRouter(enable_ml=enable_ml, config=config)
    return _profile_router
