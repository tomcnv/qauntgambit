"""
Router Configuration - Tunable parameters for Profile Router v2

This module defines the RouterConfig dataclass with all configurable parameters
for the profile routing engine, including validation logic.
"""

import os
from dataclasses import dataclass, field
from typing import Dict, Tuple

from dotenv import dotenv_values


# Default component weights (must sum to 1.0)
# Updated to include regime_fit for soft regime handling (Req 1.2, 1.3)
DEFAULT_COMPONENT_WEIGHTS = {
    'trend_fit': 0.12,
    'vol_fit': 0.12,
    'value_fit': 0.08,
    'microstructure_fit': 0.18,
    'rotation_fit': 0.08,
    'session_fit': 0.10,
    'cost_viability_fit': 0.18,
    'regime_fit': 0.14,  # Soft regime preference scoring
}

# Required component names for validation
REQUIRED_COMPONENTS = frozenset(DEFAULT_COMPONENT_WEIGHTS.keys())


def _layered_env_value(name: str) -> str | None:
    raw = os.getenv(name)
    if raw is not None:
        return raw

    baseline = dotenv_values(".env").get(name)
    env_file = os.getenv("ENV_FILE")
    if env_file:
        overlay = dotenv_values(env_file).get(name)
        if overlay is not None:
            return str(overlay)
    if baseline is not None:
        return str(baseline)
    return None


def _layered_env_float(name: str, default: str) -> float:
    raw = _layered_env_value(name)
    return float(raw if raw is not None else default)


@dataclass
class RouterConfig:
    """
    Configuration for Profile Router v2
    
    All tunable parameters with defaults and validation.
    Implements Requirements 9.1, 9.3.
    """
    # Stability parameters
    min_profile_ttl_sec: float = field(
        default_factory=lambda: _layered_env_float("PROFILE_MIN_TTL_SEC", "75.0")
    )
    switch_margin: float = field(
        default_factory=lambda: _layered_env_float("PROFILE_SWITCH_MARGIN", "0.06")
    )
    
    # Component weights (must sum to 1.0)
    component_weights: Dict[str, float] = field(default_factory=lambda: DEFAULT_COMPONENT_WEIGHTS.copy())
    
    # Hard filter thresholds (safety-critical only)
    max_safe_spread_bps: float = 50.0
    min_safe_depth_usd: float = 10000.0
    min_safe_tps: float = 0.1
    max_book_age_ms: float = 5000.0
    max_trade_age_ms: float = 10000.0
    
    # Hysteresis bands: (entry_threshold, exit_threshold)
    vol_regime_low_band: Tuple[float, float] = (0.65, 0.75)
    vol_regime_high_band: Tuple[float, float] = (1.35, 1.25)
    trend_direction_band: Tuple[float, float] = (0.0012, 0.0008)
    
    # Performance adjustment
    min_trades_for_perf_adjustment: int = 20
    perf_multiplier_range: Tuple[float, float] = (0.7, 1.3)
    perf_decay_half_life_trades: int = 50
    
    # Regime mapping
    regime_soft_penalty: float = 0.15
    squeeze_liquidity_threshold: float = 0.3
    chop_cost_threshold_bps: float = 5.0
    trend_strength_for_range_to_trend: float = 0.003
    
    # Feature flags
    use_v2_scoring: bool = True
    backtesting_mode: bool = False  # When True, disables data freshness hard filters
    
    def __post_init__(self):
        """Validate configuration after initialization."""
        self.validate()
    
    def validate(self) -> None:
        """
        Validate configuration values.
        
        Raises:
            ValueError: If any configuration value is invalid.
        """
        errors = []
        
        # Validate stability parameters
        if self.min_profile_ttl_sec < 0:
            errors.append(f"min_profile_ttl_sec must be non-negative, got {self.min_profile_ttl_sec}")
        
        if not (0.0 <= self.switch_margin <= 1.0):
            errors.append(f"switch_margin must be in [0.0, 1.0], got {self.switch_margin}")
        
        # Validate component weights
        self._validate_component_weights(errors)
        
        # Validate hard filter thresholds
        if self.max_safe_spread_bps < 0:
            errors.append(f"max_safe_spread_bps must be non-negative, got {self.max_safe_spread_bps}")
        
        if self.min_safe_depth_usd < 0:
            errors.append(f"min_safe_depth_usd must be non-negative, got {self.min_safe_depth_usd}")
        
        if self.min_safe_tps < 0:
            errors.append(f"min_safe_tps must be non-negative, got {self.min_safe_tps}")
        
        if self.max_book_age_ms < 0:
            errors.append(f"max_book_age_ms must be non-negative, got {self.max_book_age_ms}")
        
        if self.max_trade_age_ms < 0:
            errors.append(f"max_trade_age_ms must be non-negative, got {self.max_trade_age_ms}")
        
        # Validate hysteresis bands
        self._validate_hysteresis_bands(errors)
        
        # Validate performance adjustment
        if self.min_trades_for_perf_adjustment < 0:
            errors.append(f"min_trades_for_perf_adjustment must be non-negative, got {self.min_trades_for_perf_adjustment}")
        
        self._validate_perf_multiplier_range(errors)
        
        if self.perf_decay_half_life_trades <= 0:
            errors.append(f"perf_decay_half_life_trades must be positive, got {self.perf_decay_half_life_trades}")
        
        # Validate regime mapping
        if not (0.0 <= self.regime_soft_penalty <= 1.0):
            errors.append(f"regime_soft_penalty must be in [0.0, 1.0], got {self.regime_soft_penalty}")
        
        if not (0.0 <= self.squeeze_liquidity_threshold <= 1.0):
            errors.append(f"squeeze_liquidity_threshold must be in [0.0, 1.0], got {self.squeeze_liquidity_threshold}")
        
        if self.chop_cost_threshold_bps < 0:
            errors.append(f"chop_cost_threshold_bps must be non-negative, got {self.chop_cost_threshold_bps}")
        
        if self.trend_strength_for_range_to_trend < 0:
            errors.append(f"trend_strength_for_range_to_trend must be non-negative, got {self.trend_strength_for_range_to_trend}")
        
        if errors:
            raise ValueError("Invalid RouterConfig: " + "; ".join(errors))
    
    def _validate_component_weights(self, errors: list) -> None:
        """Validate component weights sum to 1.0 and contain required components."""
        if not self.component_weights:
            errors.append("component_weights cannot be empty")
            return
        
        # Check for required components
        provided_components = set(self.component_weights.keys())
        missing = REQUIRED_COMPONENTS - provided_components
        if missing:
            errors.append(f"component_weights missing required components: {sorted(missing)}")
        
        unknown = provided_components - REQUIRED_COMPONENTS
        if unknown:
            errors.append(f"component_weights contains unknown components: {sorted(unknown)}")
        
        # Check all weights are non-negative
        for name, weight in self.component_weights.items():
            if weight < 0:
                errors.append(f"component_weights['{name}'] must be non-negative, got {weight}")
        
        # Check weights sum to 1.0 (with tolerance)
        total = sum(self.component_weights.values())
        if abs(total - 1.0) > 0.001:
            errors.append(f"component_weights must sum to 1.0, got {total}")
    
    def _validate_hysteresis_bands(self, errors: list) -> None:
        """Validate hysteresis bands have correct entry/exit relationship."""
        # For low band: entry < exit (we enter low state when value drops below entry,
        # exit when it rises above exit)
        entry_low, exit_low = self.vol_regime_low_band
        if entry_low >= exit_low:
            errors.append(
                f"vol_regime_low_band entry ({entry_low}) must be less than exit ({exit_low})"
            )
        
        # For high band: entry > exit (we enter high state when value rises above entry,
        # exit when it drops below exit)
        entry_high, exit_high = self.vol_regime_high_band
        if entry_high <= exit_high:
            errors.append(
                f"vol_regime_high_band entry ({entry_high}) must be greater than exit ({exit_high})"
            )
        
        # For trend direction: entry > exit (absolute values)
        entry_trend, exit_trend = self.trend_direction_band
        if entry_trend <= exit_trend:
            errors.append(
                f"trend_direction_band entry ({entry_trend}) must be greater than exit ({exit_trend})"
            )
    
    def _validate_perf_multiplier_range(self, errors: list) -> None:
        """Validate performance multiplier range."""
        min_mult, max_mult = self.perf_multiplier_range
        
        if min_mult < 0:
            errors.append(f"perf_multiplier_range min ({min_mult}) must be non-negative")
        
        if max_mult < min_mult:
            errors.append(
                f"perf_multiplier_range max ({max_mult}) must be >= min ({min_mult})"
            )
        
        if max_mult > 10.0:
            errors.append(f"perf_multiplier_range max ({max_mult}) is unreasonably high (> 10.0)")
