"""StageContextBuilder - Builds StageContext objects from backtest data.

This module provides utilities for constructing proper StageContext objects
that can be processed by the DecisionEngine pipeline during backtesting.

Requirements: 3.1, 3.2, 3.3, 3.4
"""

from __future__ import annotations

import logging
from dataclasses import asdict
from typing import Dict, Any, List, Optional

from quantgambit.signals.pipeline import StageContext
from quantgambit.deeptrader_core.types import MarketSnapshot, Features, AccountState

logger = logging.getLogger(__name__)


class StageContextBuilder:
    """Builds StageContext objects from backtest data.
    
    Ensures all required fields are present for pipeline stages to function
    correctly, including trend indicators and market context.
    
    Requirements:
    - 3.1: Construct StageContext with all required fields
    - 3.2: Include trend indicators (ema_fast_15m, ema_slow_15m) in features
    - 3.3: Include trend_direction, trend_strength, volatility_regime in market_context
    - 3.4: Handle missing fields with safe defaults
    """
    
    # Required fields for features dict
    REQUIRED_FEATURE_FIELDS = [
        "symbol",
        "price",
        "spread",
        "rotation_factor",
        "position_in_value",
    ]
    
    # Required fields for market_context dict
    REQUIRED_MARKET_CONTEXT_FIELDS = [
        "trend_direction",
        "trend_strength",
        "volatility_regime",
    ]
    
    def __init__(self):
        """Initialize StageContextBuilder."""
        pass
    
    def build(
        self,
        symbol: str,
        snapshot: MarketSnapshot,
        features: Features,
        account_state: AccountState,
        positions: Optional[List[Dict[str, Any]]] = None,
        profile_settings: Optional[Dict[str, Any]] = None,
        ema_fast: Optional[float] = None,
        ema_slow: Optional[float] = None,
        amt_levels: Optional[Any] = None,
    ) -> StageContext:
        """Build a complete StageContext for pipeline processing.
        
        Args:
            symbol: Trading symbol
            snapshot: MarketSnapshot with current market state
            features: Features object with calculated features
            account_state: Current account state
            positions: List of open positions (default empty)
            profile_settings: Optional profile settings
            ema_fast: Fast EMA value for trend indicators
            ema_slow: Slow EMA value for trend indicators
            amt_levels: Optional pre-calculated AMT levels (for backtesting)
            
        Returns:
            StageContext ready for DecisionEngine processing
        """
        # Build features dict with all required fields
        features_dict = self._build_features_dict(
            symbol=symbol,
            snapshot=snapshot,
            features=features,
            ema_fast=ema_fast,
            ema_slow=ema_slow,
        )
        
        # Build market_context dict with all required fields
        market_context = self._build_market_context(
            snapshot=snapshot,
            ema_fast=ema_fast,
            ema_slow=ema_slow,
        )
        
        # Convert account_state to dict
        account_dict = self._account_to_dict(account_state)
        
        # Build prediction dict with default confidence for backtesting
        # The EV gate requires prediction.confidence for EV calculation
        prediction_dict = {
            "confidence": 0.5,  # Default 50% confidence for backtesting
            "direction": "neutral",
            "source": "backtest_default",
        }
        
        # Build the StageContext
        ctx = StageContext(
            symbol=symbol,
            data={
                "features": features_dict,
                "market_context": market_context,
                "account": account_dict,
                "positions": positions or [],
                "risk_ok": True,
                "profile_settings": profile_settings,
                "prediction": prediction_dict,
                # Pre-calculated AMT levels (for backtesting with timestamp filtering)
                "amt_levels": amt_levels,
            },
        )
        
        return ctx
    
    def _build_features_dict(
        self,
        symbol: str,
        snapshot: MarketSnapshot,
        features: Features,
        ema_fast: Optional[float] = None,
        ema_slow: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Build features dict with all required fields.
        
        Requirements: 3.1, 3.2
        """
        # Start with basic features
        features_dict = {
            "symbol": symbol,
            "price": snapshot.mid_price,
            "spread": snapshot.spread_bps / 10000 if snapshot.spread_bps else 0,
            "rotation_factor": getattr(features, "rotation_factor", 0),
            "position_in_value": snapshot.position_in_value or "inside",
            "timestamp": snapshot.timestamp_ns / 1e9 if snapshot.timestamp_ns else 0,
        }
        
        # Add AMT-related features
        features_dict.update({
            "distance_to_poc": getattr(features, "distance_to_poc", None),
            "distance_to_vah": getattr(features, "distance_to_vah", None),
            "distance_to_val": getattr(features, "distance_to_val", None),
            "point_of_control": snapshot.poc_price,
            "value_area_high": snapshot.vah_price,
            "value_area_low": snapshot.val_price,
        })
        
        # Add depth and imbalance features
        features_dict.update({
            "bid_depth_usd": snapshot.bid_depth_usd,
            "ask_depth_usd": snapshot.ask_depth_usd,
            "orderbook_imbalance": snapshot.depth_imbalance,
            "orderflow_imbalance": snapshot.depth_imbalance,  # Use depth as proxy
        })
        
        # Add ATR features (with safe defaults)
        features_dict.update({
            "atr_5m": getattr(features, "atr_5m", None),
            "atr_5m_baseline": getattr(features, "atr_5m_baseline", None),
        })
        
        # Add trend indicators (Requirement 3.2)
        features_dict.update({
            "ema_fast_15m": ema_fast,
            "ema_slow_15m": ema_slow,
            "trend_direction": snapshot.trend_direction or "flat",
            "trend_strength": snapshot.trend_strength or 0.0,
        })
        
        # Add bid/ask fields for backwards compatibility and best_bid/best_ask for EV gate
        # Requirements: 2.1, 2.3
        features_dict.update({
            "bid": snapshot.bid,       # For backwards compatibility
            "ask": snapshot.ask,       # For backwards compatibility
            "best_bid": snapshot.bid,  # Required by EV gate
            "best_ask": snapshot.ask,  # Required by EV gate
        })
        
        return features_dict
    
    def _build_market_context(
        self,
        snapshot: MarketSnapshot,
        ema_fast: Optional[float] = None,
        ema_slow: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Build market_context dict with all required fields.
        
        Requirements: 2.2, 3.3
        
        Context Vector Parity Fix:
        - Uses the unified build_context_vector() to derive all fields
        - This ensures parity between live and backtest
        """
        from quantgambit.deeptrader_core.profiles.context_vector import (
            ContextVectorInput,
            build_context_vector,
        )
        
        # Build ContextVectorInput from snapshot
        input_data = ContextVectorInput(
            symbol=snapshot.symbol or "UNKNOWN",
            timestamp=snapshot.timestamp_ns / 1e9 if snapshot.timestamp_ns else 0,
            price=snapshot.mid_price,
            bid=snapshot.bid,
            ask=snapshot.ask,
            spread_bps=snapshot.spread_bps,
            bid_depth_usd=snapshot.bid_depth_usd,
            ask_depth_usd=snapshot.ask_depth_usd,
            orderbook_imbalance=snapshot.depth_imbalance,
            trend_direction=snapshot.trend_direction,
            trend_strength=snapshot.trend_strength,
            vol_regime=snapshot.vol_regime,
            poc_price=snapshot.poc_price,
            vah_price=snapshot.vah_price,
            val_price=snapshot.val_price,
            position_in_value=snapshot.position_in_value,
            book_age_ms=snapshot.snapshot_age_ms,
            data_quality_score=snapshot.data_quality_score,
        )
        
        # Use unified builder to get properly derived fields
        ctx_vector = build_context_vector(input_data, backtesting_mode=True)
        
        return {
            # Required trend fields (Requirement 3.3)
            "trend_direction": ctx_vector.trend_direction,
            "trend_strength": ctx_vector.trend_strength,
            "volatility_regime": ctx_vector.volatility_regime,
            
            # CRITICAL: market_regime and regime_family for profile routing
            # Derived by build_context_vector using shared logic
            "market_regime": ctx_vector.market_regime,
            "regime_family": ctx_vector.regime_family,
            
            # Additional context from ContextVector
            "position_in_value": ctx_vector.position_in_value,
            "spread_bps": ctx_vector.spread_bps,
            "bid_depth_usd": ctx_vector.bid_depth_usd,
            "ask_depth_usd": ctx_vector.ask_depth_usd,
            "vol_shock": snapshot.vol_shock or False,
            "liquidity_score": ctx_vector.liquidity_score,
            "expected_cost_bps": ctx_vector.expected_cost_bps,
            "expected_fee_bps": ctx_vector.expected_fee_bps,
            
            # Price for position evaluation
            "price": ctx_vector.price,
            
            # Trend indicators
            "ema_spread_pct": ctx_vector.ema_spread_pct,
            "atr_ratio": ctx_vector.atr_ratio,
            "ema_fast_15m": ema_fast,
            "ema_slow_15m": ema_slow,
            
            # Orderflow imbalances
            "imb_1s": snapshot.imb_1s or 0,
            "imb_5s": snapshot.imb_5s or 0,
            "imb_30s": snapshot.imb_30s or 0,
            "orderflow_imbalance": ctx_vector.orderbook_imbalance,
            
            # AMT distances
            "distance_to_vah_pct": ctx_vector.distance_to_vah_pct,
            "distance_to_val_pct": ctx_vector.distance_to_val_pct,
            "distance_to_poc_pct": ctx_vector.distance_to_poc_pct,
            
            # Data quality
            "data_quality_score": ctx_vector.data_completeness,
            "data_quality_state": ctx_vector.data_quality_state,
            "snapshot_age_ms": snapshot.snapshot_age_ms or 0,
            
            # Session
            "session": ctx_vector.session,
            "hour_utc": ctx_vector.hour_utc,
            
            # Bid/ask prices for EV gate (Requirement 2.2)
            "best_bid": snapshot.bid,
            "best_ask": snapshot.ask,
        }
    
    def _account_to_dict(self, account_state: AccountState) -> Dict[str, Any]:
        """Convert AccountState to dict.
        
        Handles both dataclass and dict inputs.
        """
        if hasattr(account_state, "__dataclass_fields__"):
            return asdict(account_state)
        elif isinstance(account_state, dict):
            return account_state
        else:
            # Try to extract common fields
            return {
                "equity": getattr(account_state, "equity", 0),
                "daily_pnl": getattr(account_state, "daily_pnl", 0),
                "max_daily_loss": getattr(account_state, "max_daily_loss", 0),
                "open_positions": getattr(account_state, "open_positions", 0),
                "symbol_open_positions": getattr(account_state, "symbol_open_positions", 0),
                "symbol_daily_pnl": getattr(account_state, "symbol_daily_pnl", 0),
            }
    
    def validate_context(self, ctx: StageContext) -> List[str]:
        """Validate that a StageContext has all required fields.
        
        Returns list of missing or invalid fields.
        """
        errors = []
        
        if not ctx.symbol:
            errors.append("symbol is missing")
        
        if not ctx.data:
            errors.append("data is missing")
            return errors
        
        # Check features
        features = ctx.data.get("features", {})
        for field in self.REQUIRED_FEATURE_FIELDS:
            if field not in features or features[field] is None:
                errors.append(f"features.{field} is missing")
        
        # Check market_context
        market_context = ctx.data.get("market_context", {})
        for field in self.REQUIRED_MARKET_CONTEXT_FIELDS:
            if field not in market_context:
                errors.append(f"market_context.{field} is missing")
        
        # Check account
        if "account" not in ctx.data:
            errors.append("account is missing")
        
        # Check positions (should be a list)
        if "positions" not in ctx.data:
            errors.append("positions is missing")
        elif not isinstance(ctx.data["positions"], list):
            errors.append("positions should be a list")
        
        return errors


# Singleton instance for convenience
_default_builder: Optional[StageContextBuilder] = None


def get_stage_context_builder() -> StageContextBuilder:
    """Get the default StageContextBuilder instance."""
    global _default_builder
    if _default_builder is None:
        _default_builder = StageContextBuilder()
    return _default_builder
