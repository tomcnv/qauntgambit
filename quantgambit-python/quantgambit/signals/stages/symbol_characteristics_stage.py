"""
SymbolCharacteristicsStage - Injects symbol characteristics into pipeline context.

This stage runs early in the pipeline (after data_readiness, before global_gate)
to provide symbol-adaptive parameters to all downstream stages.

Implements Requirements 5.1, 5.2, 5.3, 5.4:
- Pipeline includes SymbolCharacteristicsStage that runs early (5.1)
- Stage fetches current characteristics and stores in ctx.data (5.2)
- Characteristics stored under ctx.data["symbol_characteristics"] (5.3)
- Logs warning and uses defaults when characteristics unavailable (5.4)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from quantgambit.signals.pipeline import Stage, StageContext, StageResult
from quantgambit.signals.services.symbol_characteristics import SymbolCharacteristicsService
from quantgambit.signals.services.parameter_resolver import (
    AdaptiveParameterResolver,
    ResolvedParameters,
)
from quantgambit.deeptrader_core.types import SymbolCharacteristics


logger = logging.getLogger(__name__)


@dataclass
class SymbolCharacteristicsStageConfig:
    """Configuration for SymbolCharacteristicsStage."""
    # Whether to update characteristics with current market data
    update_on_tick: bool = True
    # Minimum samples before considering characteristics reliable
    min_warmup_samples: int = 100
    # Whether to log when using default characteristics
    log_defaults: bool = True


class SymbolCharacteristicsStage(Stage):
    """
    Pipeline stage that injects symbol characteristics into context.
    
    Runs early in the pipeline before any gates or signal generation.
    Updates characteristics service with current market data and
    resolves adaptive parameters for downstream stages.
    
    Context Outputs:
    - ctx.data["symbol_characteristics"]: SymbolCharacteristics object
    - ctx.data["resolved_params"]: ResolvedParameters with absolute values
    
    Requirements: 5.1, 5.2, 5.3, 5.4
    """
    name = "symbol_characteristics"
    
    def __init__(
        self,
        characteristics_service: SymbolCharacteristicsService,
        resolver: Optional[AdaptiveParameterResolver] = None,
        config: Optional[SymbolCharacteristicsStageConfig] = None,
    ):
        """
        Initialize the stage.
        
        Args:
            characteristics_service: Service for tracking symbol characteristics
            resolver: Parameter resolver for converting multipliers to absolutes
            config: Stage configuration
        """
        self._service = characteristics_service
        self._resolver = resolver or AdaptiveParameterResolver()
        self._config = config or SymbolCharacteristicsStageConfig()
    
    async def run(self, ctx: StageContext) -> StageResult:
        """
        Fetch and inject symbol characteristics.
        
        1. Update service with current market data (if available)
        2. Get current characteristics
        3. Store in ctx.data["symbol_characteristics"]
        4. Resolve parameters and store in ctx.data["resolved_params"]
        
        Requirements: 5.2, 5.3, 5.4
        """
        symbol = ctx.symbol
        features = ctx.data.get("features") or {}
        market_context = ctx.data.get("market_context") or {}
        
        # Step 1: Update characteristics with current market data
        if self._config.update_on_tick:
            self._update_characteristics(symbol, features, market_context)
        
        # Step 2: Get current characteristics (Requirement 5.2)
        characteristics = self._service.get_characteristics(symbol)
        
        # Step 3: Store in context (Requirement 5.3)
        ctx.data["symbol_characteristics"] = characteristics
        
        # Step 4: Check if using defaults and log warning (Requirement 5.4)
        using_defaults = not characteristics.is_warmed_up(self._config.min_warmup_samples)
        if using_defaults and self._config.log_defaults:
            logger.warning(
                "symbol_characteristics_using_defaults",
                extra={
                    "symbol": symbol,
                    "sample_count": characteristics.sample_count,
                    "min_required": self._config.min_warmup_samples,
                },
            )
        
        # Step 5: Resolve parameters using profile params (if available)
        profile_params = self._get_profile_params(ctx)
        resolved = self._resolver.resolve(profile_params, characteristics)
        ctx.data["resolved_params"] = resolved
        
        # Log resolution at DEBUG level for troubleshooting
        logger.debug(
            "symbol_characteristics_resolved",
            extra={
                "symbol": symbol,
                "using_defaults": using_defaults,
                "typical_spread_bps": characteristics.typical_spread_bps,
                "typical_depth_usd": characteristics.typical_depth_usd,
                "typical_daily_range_pct": characteristics.typical_daily_range_pct,
                "resolved_poc_distance_pct": resolved.min_distance_from_poc_pct,
                "resolved_max_spread_bps": resolved.max_spread_bps,
                "resolved_min_depth_usd": resolved.min_depth_per_side_usd,
            },
        )
        
        # Always continue - this stage doesn't reject
        return StageResult.CONTINUE
    
    def _update_characteristics(
        self,
        symbol: str,
        features: dict,
        market_context: dict,
    ) -> None:
        """
        Update characteristics service with current market data.
        
        Extracts spread, depth, ATR, price, and volatility regime from
        features and market_context to update the rolling statistics.
        """
        # Extract spread in basis points
        spread_bps = features.get("spread_bps")
        if spread_bps is None:
            bid = features.get("bid")
            ask = features.get("ask")
            price = features.get("price")
            if bid and ask and price and price > 0:
                spread_bps = (ask - bid) / price * 10000
            else:
                spread_bps = 5.0  # Default if can't calculate
        
        # Extract minimum depth (min of bid/ask depth)
        bid_depth = features.get("bid_depth_usd") or 0.0
        ask_depth = features.get("ask_depth_usd") or 0.0
        min_depth = min(bid_depth, ask_depth) if bid_depth > 0 and ask_depth > 0 else 50000.0
        
        # Extract ATR (try multiple sources)
        atr = (
            features.get("atr") or
            features.get("atr_5m") or
            market_context.get("atr") or
            0.0
        )
        
        # Extract price
        price = features.get("price") or features.get("mid") or 0.0
        
        # Extract volatility regime
        vol_regime = market_context.get("volatility_regime") or "normal"
        
        # Only update if we have valid data
        if price > 0 and spread_bps > 0:
            self._service.update(
                symbol=symbol,
                spread_bps=spread_bps,
                min_depth_usd=min_depth,
                atr=atr,
                price=price,
                volatility_regime=vol_regime,
            )
    
    def _get_profile_params(self, ctx: StageContext) -> dict:
        """
        Extract profile parameters from context.
        
        Looks for profile-specific multiplier settings that may have been
        set by ProfileRoutingStage or passed in via profile_settings.
        """
        # Try to get from profile settings
        profile_settings = ctx.data.get("profile_settings") or {}
        
        # Try to get from matched profile
        matched_profile = ctx.data.get("matched_profile") or {}
        risk_params = matched_profile.get("risk_parameters") or {}
        
        # Merge settings (profile-specific takes precedence)
        params = {}
        params.update(profile_settings)
        params.update(risk_params)
        
        return params
