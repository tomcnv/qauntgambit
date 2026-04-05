"""
Adaptive Parameter Resolver - Converts multiplier-based parameters to absolute values.

Implements Requirements 2.1-2.8 for symbol-adaptive parameters:
- Converts multiplier-based parameters to absolute values (2.1)
- Calculates min_distance_from_poc from daily range (2.2)
- Calculates max_spread from typical spread (2.3)
- Calculates min_depth_per_side_usd from typical depth (2.4)
- Calculates stop_loss_pct from daily range (2.5)
- Calculates take_profit_pct from daily range (2.6)
- Applies floor and ceiling bounds (2.7)
- Falls back to hardcoded defaults when unavailable (2.8)

Also implements BPS standardization (Strategy Signal Architecture Fixes Requirement 1.8):
- Converts legacy percent-based parameters to bps during resolution
- Logs all conversions for debugging
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from quantgambit.deeptrader_core.types import SymbolCharacteristics
from quantgambit.core.unit_converter import pct_to_bps, bps_to_pct, convert_legacy_pct_to_bps


logger = logging.getLogger(__name__)


@dataclass
class ResolvedParameters:
    """
    Resolved absolute parameters with source information.
    
    Contains both the resolved absolute values and the original multipliers
    used to calculate them, plus the symbol characteristics for debugging.
    
    BPS Standardization (Requirement 1.8):
    - Includes both legacy pct values and new bps values
    - min_distance_from_poc_bps: Distance threshold in basis points
    - stop_loss_bps: Stop loss distance in basis points
    - take_profit_bps: Take profit distance in basis points
    """
    # Resolved absolute values (legacy pct format for backward compatibility)
    min_distance_from_poc_pct: float
    max_spread_bps: float
    min_depth_per_side_usd: float
    stop_loss_pct: float
    take_profit_pct: float
    
    # BPS versions of distance parameters (Requirement 1.8)
    min_distance_from_poc_bps: float = field(default=0.0)
    stop_loss_bps: float = field(default=0.0)
    take_profit_bps: float = field(default=0.0)
    
    # Original multipliers (for debugging)
    poc_distance_multiplier: float = field(default=0.0)
    spread_multiplier: float = field(default=0.0)
    depth_multiplier: float = field(default=0.0)
    stop_loss_multiplier: float = field(default=0.0)
    take_profit_multiplier: float = field(default=0.0)
    
    # Symbol characteristics used (for debugging)
    symbol_characteristics: SymbolCharacteristics = field(default=None)
    
    # Flags
    used_defaults: bool = field(default=False)  # True if characteristics were unavailable
    bps_conversion_logged: bool = field(default=False)  # True if bps conversion was logged
    
    def __post_init__(self):
        """Calculate bps values from pct values if not already set."""
        if self.min_distance_from_poc_bps == 0.0 and self.min_distance_from_poc_pct > 0:
            self.min_distance_from_poc_bps = pct_to_bps(self.min_distance_from_poc_pct)
        if self.stop_loss_bps == 0.0 and self.stop_loss_pct > 0:
            self.stop_loss_bps = pct_to_bps(self.stop_loss_pct)
        if self.take_profit_bps == 0.0 and self.take_profit_pct > 0:
            self.take_profit_bps = pct_to_bps(self.take_profit_pct)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for telemetry and serialization."""
        return {
            # Resolved values (legacy pct)
            "min_distance_from_poc_pct": self.min_distance_from_poc_pct,
            "max_spread_bps": self.max_spread_bps,
            "min_depth_per_side_usd": self.min_depth_per_side_usd,
            "stop_loss_pct": self.stop_loss_pct,
            "take_profit_pct": self.take_profit_pct,
            # BPS values (Requirement 1.8)
            "min_distance_from_poc_bps": self.min_distance_from_poc_bps,
            "stop_loss_bps": self.stop_loss_bps,
            "take_profit_bps": self.take_profit_bps,
            # Multipliers
            "poc_distance_multiplier": self.poc_distance_multiplier,
            "spread_multiplier": self.spread_multiplier,
            "depth_multiplier": self.depth_multiplier,
            "stop_loss_multiplier": self.stop_loss_multiplier,
            "take_profit_multiplier": self.take_profit_multiplier,
            # Characteristics
            "symbol": self.symbol_characteristics.symbol if self.symbol_characteristics else None,
            "typical_spread_bps": self.symbol_characteristics.typical_spread_bps if self.symbol_characteristics else None,
            "typical_depth_usd": self.symbol_characteristics.typical_depth_usd if self.symbol_characteristics else None,
            "typical_daily_range_pct": self.symbol_characteristics.typical_daily_range_pct if self.symbol_characteristics else None,
            # Flags
            "used_defaults": self.used_defaults,
            "bps_conversion_logged": self.bps_conversion_logged,
        }


class AdaptiveParameterResolver:
    """
    Converts multiplier-based parameters to absolute values.
    
    Uses symbol characteristics to scale parameters appropriately.
    Applies bounds to prevent extreme values.
    
    Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8
    """
    
    # Default multipliers (used if not specified in profile)
    # Requirement 7.4, 7.5, 7.6, 7.7, 7.8
    # NOTE: POC distance multiplier calculation:
    # - typical_daily_range_pct is ~0.03 (3%) for BTC
    # - We want min_distance_from_poc_pct ~0.003 (0.3% = 30 bps)
    # - So multiplier = 0.003 / 0.03 = 0.1
    # This gives: 0.1 × 0.03 = 0.003 (0.3%) = 30 bps
    # Reverted to a stricter baseline to reduce low-quality micro-POC entries.
    # 0.10 × 0.03 ≈ 0.003 (0.3% = 30 bps) for typical daily range.
    DEFAULT_POC_DISTANCE_MULTIPLIER = 0.10
    DEFAULT_SPREAD_MULTIPLIER = 2.0  # 2x typical spread
    DEFAULT_DEPTH_MULTIPLIER = 0.05  # 0.05x typical depth (tightened to reduce thin-book fills)
    DEFAULT_STOP_LOSS_MULTIPLIER = 1.0  # 1x daily range
    DEFAULT_TAKE_PROFIT_MULTIPLIER = 1.5  # 1.5x daily range (1.5:1 R:R)
    
    # Bounds to prevent extreme values (Requirement 2.7)
    MIN_POC_DISTANCE_PCT = 0.0005  # 5 bps minimum to avoid micro-POC noise
    MAX_POC_DISTANCE_PCT = 0.10  # 10% maximum
    MIN_SPREAD_BPS = 0.5  # 0.5 bps minimum
    MAX_SPREAD_BPS = 50.0  # 50 bps maximum
    MIN_DEPTH_USD = 1500.0  # $1.5k minimum (reduce thin-book fills)
    MAX_DEPTH_USD = 1000000.0  # $1M maximum
    #
    # Scalper-friendly caps:
    # Historically, stop/TP were derived from *daily* range and clamped in pct (0.5%..5%+),
    # which makes the bot behave like a swing system (multi-% holds).
    #
    # We keep the symbol-adaptive formula (multiplier × daily range) but clamp *in bps* to
    # enforce "scalp-sized" distances. These pct values are derived from the bps bounds.
    MIN_STOP_LOSS_BPS = 20.0   # 0.20%
    MAX_STOP_LOSS_BPS = 80.0  # 0.80%
    MIN_TAKE_PROFIT_BPS = 35.0   # 0.35%
    MAX_TAKE_PROFIT_BPS = 140.0  # 1.40%

    MIN_STOP_LOSS_PCT = bps_to_pct(MIN_STOP_LOSS_BPS)
    MAX_STOP_LOSS_PCT = bps_to_pct(MAX_STOP_LOSS_BPS)
    MIN_TAKE_PROFIT_PCT = bps_to_pct(MIN_TAKE_PROFIT_BPS)
    MAX_TAKE_PROFIT_PCT = bps_to_pct(MAX_TAKE_PROFIT_BPS)
    
    def __init__(self):
        """Initialize the resolver."""
        def _env_bps(name: str, default: float) -> float:
            raw = os.getenv(name)
            if raw is None or raw == "":
                return default
            try:
                value = float(raw)
                return value if value > 0 else default
            except (TypeError, ValueError):
                return default

        self.MIN_STOP_LOSS_BPS = _env_bps("PARAM_MIN_STOP_LOSS_BPS", self.MIN_STOP_LOSS_BPS)
        self.MAX_STOP_LOSS_BPS = _env_bps("PARAM_MAX_STOP_LOSS_BPS", self.MAX_STOP_LOSS_BPS)
        self.MIN_TAKE_PROFIT_BPS = _env_bps("PARAM_MIN_TAKE_PROFIT_BPS", self.MIN_TAKE_PROFIT_BPS)
        self.MAX_TAKE_PROFIT_BPS = _env_bps("PARAM_MAX_TAKE_PROFIT_BPS", self.MAX_TAKE_PROFIT_BPS)

        if self.MIN_STOP_LOSS_BPS > self.MAX_STOP_LOSS_BPS:
            self.MIN_STOP_LOSS_BPS, self.MAX_STOP_LOSS_BPS = self.MAX_STOP_LOSS_BPS, self.MIN_STOP_LOSS_BPS
        if self.MIN_TAKE_PROFIT_BPS > self.MAX_TAKE_PROFIT_BPS:
            self.MIN_TAKE_PROFIT_BPS, self.MAX_TAKE_PROFIT_BPS = self.MAX_TAKE_PROFIT_BPS, self.MIN_TAKE_PROFIT_BPS

        self.MIN_STOP_LOSS_PCT = bps_to_pct(self.MIN_STOP_LOSS_BPS)
        self.MAX_STOP_LOSS_PCT = bps_to_pct(self.MAX_STOP_LOSS_BPS)
        self.MIN_TAKE_PROFIT_PCT = bps_to_pct(self.MIN_TAKE_PROFIT_BPS)
        self.MAX_TAKE_PROFIT_PCT = bps_to_pct(self.MAX_TAKE_PROFIT_BPS)
    
    def resolve(
        self,
        profile_params: Dict[str, Any],
        characteristics: SymbolCharacteristics,
    ) -> ResolvedParameters:
        """
        Resolve multiplier-based parameters to absolute values.
        
        The resolution formula is: absolute_value = multiplier × characteristic
        
        For each parameter:
        - If a multiplier is specified in profile_params, use it
        - Otherwise, use the default multiplier
        - Multiply by the corresponding symbol characteristic
        - Apply bounds to prevent extreme values
        
        Args:
            profile_params: Parameters from profile (may contain multipliers or absolutes)
            characteristics: Symbol characteristics for scaling
            
        Returns:
            ResolvedParameters with absolute values
            
        Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8
        """
        # Determine if we're using default characteristics
        used_defaults = not characteristics.is_warmed_up()
        
        # Get multipliers from profile or use defaults
        poc_multiplier = self._get_multiplier(
            profile_params,
            "poc_distance_atr_multiplier",
            self.DEFAULT_POC_DISTANCE_MULTIPLIER,
        )
        scale_overrides_enabled = os.getenv("ENABLE_PARAMETER_MULTIPLIER_SCALES", "false").lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        poc_multiplier_scale = float(os.getenv("POC_DISTANCE_MULTIPLIER_SCALE", "1.0"))
        if scale_overrides_enabled and poc_multiplier_scale > 0.0 and poc_multiplier_scale != 1.0:
            poc_multiplier *= poc_multiplier_scale
        spread_multiplier = self._get_multiplier(
            profile_params,
            "spread_typical_multiplier",
            self.DEFAULT_SPREAD_MULTIPLIER,
        )
        depth_multiplier = self._get_multiplier(
            profile_params,
            "depth_typical_multiplier",
            self.DEFAULT_DEPTH_MULTIPLIER,
        )
        stop_loss_multiplier = self._get_multiplier(
            profile_params,
            "stop_loss_atr_multiplier",
            self.DEFAULT_STOP_LOSS_MULTIPLIER,
        )
        stop_loss_multiplier_scale = float(os.getenv("STOP_LOSS_MULTIPLIER_SCALE", "1.0"))
        if scale_overrides_enabled and stop_loss_multiplier_scale > 0.0 and stop_loss_multiplier_scale != 1.0:
            stop_loss_multiplier *= stop_loss_multiplier_scale
        take_profit_multiplier = self._get_multiplier(
            profile_params,
            "take_profit_atr_multiplier",
            self.DEFAULT_TAKE_PROFIT_MULTIPLIER,
        )
        take_profit_multiplier_scale = float(os.getenv("TAKE_PROFIT_MULTIPLIER_SCALE", "1.0"))
        if scale_overrides_enabled and take_profit_multiplier_scale > 0.0 and take_profit_multiplier_scale != 1.0:
            take_profit_multiplier *= take_profit_multiplier_scale
        
        # Calculate raw values using formula: absolute = multiplier × characteristic
        # Requirement 2.2: min_distance_from_poc = multiplier × typical_daily_range_pct
        raw_poc_distance = poc_multiplier * characteristics.typical_daily_range_pct
        
        # Requirement 2.3: max_spread = multiplier × typical_spread_bps
        raw_spread = spread_multiplier * characteristics.typical_spread_bps
        
        # Requirement 2.4: min_depth = multiplier × typical_depth_usd
        raw_depth = depth_multiplier * characteristics.typical_depth_usd
        
        # Requirement 2.5: stop_loss = multiplier × typical_daily_range_pct
        raw_stop_loss = stop_loss_multiplier * characteristics.typical_daily_range_pct
        
        # Requirement 2.6: take_profit = multiplier × typical_daily_range_pct
        raw_take_profit = take_profit_multiplier * characteristics.typical_daily_range_pct
        
        # Apply bounds (Requirement 2.7)
        bounded_poc_distance = self._apply_bounds(
            raw_poc_distance,
            self.MIN_POC_DISTANCE_PCT,
            self.MAX_POC_DISTANCE_PCT,
            "poc_distance",
            characteristics.symbol,
        )
        bounded_spread = self._apply_bounds(
            raw_spread,
            self.MIN_SPREAD_BPS,
            self.MAX_SPREAD_BPS,
            "spread",
            characteristics.symbol,
        )
        bounded_depth = self._apply_bounds(
            raw_depth,
            self.MIN_DEPTH_USD,
            self.MAX_DEPTH_USD,
            "depth",
            characteristics.symbol,
        )
        bounded_stop_loss = self._apply_bounds(
            raw_stop_loss,
            self.MIN_STOP_LOSS_PCT,
            self.MAX_STOP_LOSS_PCT,
            "stop_loss",
            characteristics.symbol,
        )
        bounded_take_profit = self._apply_bounds(
            raw_take_profit,
            self.MIN_TAKE_PROFIT_PCT,
            self.MAX_TAKE_PROFIT_PCT,
            "take_profit",
            characteristics.symbol,
        )
        
        return ResolvedParameters(
            min_distance_from_poc_pct=bounded_poc_distance,
            max_spread_bps=bounded_spread,
            min_depth_per_side_usd=bounded_depth,
            stop_loss_pct=bounded_stop_loss,
            take_profit_pct=bounded_take_profit,
            # BPS values are calculated in __post_init__
            min_distance_from_poc_bps=pct_to_bps(bounded_poc_distance),
            stop_loss_bps=pct_to_bps(bounded_stop_loss),
            take_profit_bps=pct_to_bps(bounded_take_profit),
            poc_distance_multiplier=poc_multiplier,
            spread_multiplier=spread_multiplier,
            depth_multiplier=depth_multiplier,
            stop_loss_multiplier=stop_loss_multiplier,
            take_profit_multiplier=take_profit_multiplier,
            symbol_characteristics=characteristics,
            used_defaults=used_defaults,
            bps_conversion_logged=True,
        )
    
    def resolve_with_bps_logging(
        self,
        profile_params: Dict[str, Any],
        characteristics: SymbolCharacteristics,
        symbol: str,
    ) -> ResolvedParameters:
        """
        Resolve parameters and log all bps conversions for debugging.
        
        This method wraps resolve() and adds detailed logging of all
        percent-to-bps conversions as required by Requirement 1.8.
        
        Args:
            profile_params: Parameters from profile
            characteristics: Symbol characteristics for scaling
            symbol: Symbol name for logging context
            
        Returns:
            ResolvedParameters with absolute values and bps conversions logged
            
        Requirements: 1.8, 1.2.1, 1.2.2
        """
        result = self.resolve(profile_params, characteristics)
        
        # Log all bps conversions (Requirement 1.2.2)
        logger.info(
            "parameter_bps_conversion",
            extra={
                "symbol": symbol,
                "min_distance_from_poc_pct": result.min_distance_from_poc_pct,
                "min_distance_from_poc_bps": result.min_distance_from_poc_bps,
                "stop_loss_pct": result.stop_loss_pct,
                "stop_loss_bps": result.stop_loss_bps,
                "take_profit_pct": result.take_profit_pct,
                "take_profit_bps": result.take_profit_bps,
                "max_spread_bps": result.max_spread_bps,
                "used_defaults": result.used_defaults,
            },
        )
        
        return result
    
    def _get_multiplier(
        self,
        profile_params: Dict[str, Any],
        key: str,
        default: float,
    ) -> float:
        """
        Get multiplier from profile params or return default.
        
        Args:
            profile_params: Profile parameters dict
            key: Key to look up
            default: Default value if not found
            
        Returns:
            Multiplier value
        """
        value = profile_params.get(key)
        if value is not None:
            return float(value)
        return default
    
    def _apply_bounds(
        self,
        value: float,
        min_val: float,
        max_val: float,
        param_name: str = "",
        symbol: str = "",
    ) -> float:
        """
        Clamp value to bounds.
        
        Logs a warning when bounds are hit for debugging.
        
        Args:
            value: Raw calculated value
            min_val: Minimum allowed value
            max_val: Maximum allowed value
            param_name: Parameter name for logging
            symbol: Symbol for logging
            
        Returns:
            Value clamped to [min_val, max_val]
            
        Requirement 2.7
        """
        if value < min_val:
            logger.debug(
                "parameter_bounds_hit: %s %s raw=%.6f hit min=%.6f",
                symbol, param_name, value, min_val,
            )
            return min_val
        if value > max_val:
            logger.debug(
                "parameter_bounds_hit: %s %s raw=%.6f hit max=%.6f",
                symbol, param_name, value, max_val,
            )
            return max_val
        return value
    
    def resolve_with_fallback(
        self,
        profile_params: Dict[str, Any],
        characteristics: Optional[SymbolCharacteristics],
        symbol: str,
    ) -> ResolvedParameters:
        """
        Resolve parameters with fallback to defaults if characteristics unavailable.
        
        Requirement 2.8: Fall back to hardcoded default values when unavailable.
        
        Args:
            profile_params: Parameters from profile
            characteristics: Symbol characteristics (may be None)
            symbol: Symbol name for creating default characteristics
            
        Returns:
            ResolvedParameters with absolute values
        """
        if characteristics is None:
            logger.info(
                "parameter_resolver_using_defaults",
                extra={"symbol": symbol, "reason": "no_characteristics"},
            )
            characteristics = SymbolCharacteristics.default(symbol)
        
        return self.resolve(profile_params, characteristics)
