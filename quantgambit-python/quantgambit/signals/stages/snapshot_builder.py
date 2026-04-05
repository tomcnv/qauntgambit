"""
SnapshotBuilderStage - Creates frozen MarketSnapshot from features.

This stage freezes all market state into an immutable MarketSnapshot object.
All subsequent stages read from this snapshot to ensure consistency.

CRITICAL FIXES (2026-01-20):
1. All AMT distances are now in bps using canonical formula: (price - ref) / mid_price * 10000
2. flow_rotation and trend_bias are computed even in fallback path (never default to 0)
3. Realized volatility (_estimate_rv) returns actual bps with proper scaling
4. Snapshot age is deterministic in backtest mode (set to 0)
5. Data quality flags added when bid/ask missing or inverted
6. Slippage estimation includes freshness and volatility penalties

CRITICAL FIXES (2026-01-21):
7. mid_price stored correctly in snapshot (was storing price instead)
8. Volatility penalty logic fixed (extreme branch was unreachable)
9. Timestamp normalization handles ms/ns inputs defensively
10. Bid/ask missingness detected BEFORE defaulting to price
11. Orderflow imbalance key normalized to single canonical key
12. ws_connected defaults to False when sync states unknown (fail-safe)
13. expected_fill_slippage_bps is explicitly ONE-WAY (entry only)
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional, Any, Tuple

from quantgambit.signals.pipeline import Stage, StageContext, StageResult
from quantgambit.deeptrader_core.types import MarketSnapshot
from quantgambit.observability.logger import log_info, log_warning


@dataclass
class SnapshotBuilderConfig:
    """Configuration for SnapshotBuilderStage."""
    # Default exchange if not specified
    default_exchange: str = "bybit"
    # Default slippage estimate in bps (ONE-WAY, entry fill only)
    default_slippage_bps: float = 2.0
    # Multiplier applied to slippage estimate (to align with live fills)
    slippage_multiplier: float = float(os.getenv("SNAPSHOT_SLIPPAGE_MULTIPLIER", "1.0"))
    # Minimum slippage floor after multiplier
    min_slippage_bps: float = float(os.getenv("SNAPSHOT_MIN_SLIPPAGE_BPS", "0.0"))
    # Default typical spread in bps
    default_typical_spread_bps: float = 3.0
    # POC staleness threshold - reject if POC is more than this % from current price
    poc_staleness_threshold_pct: float = 2.0
    # Flow rotation EWMA parameters for fallback calculation
    flow_rotation_scale: float = 5.0
    flow_rotation_clip_min: float = -5.0
    flow_rotation_clip_max: float = 5.0
    # Threshold for detecting if price_change is in percent vs fractional
    # If abs(price_change) > this, assume it's already in percent
    # Using 1.0 as threshold because 1.0 = 100% if fractional (impossible in normal markets)
    # This is safer than 0.2 which could misclassify a 25% crypto move
    price_change_percent_threshold: float = 1.0


class SnapshotBuilderStage(Stage):
    """
    Freeze market state into immutable MarketSnapshot.
    
    This is a critical stage that creates the single source of truth
    for all downstream stages. By freezing the data here, we ensure
    that all gate decisions are made on the same market state.
    
    CRITICAL: This stage must handle both the AMT path (when AMTCalculatorStage
    provides amt_levels) and the fallback path (when amt_levels is None).
    Both paths must produce consistent, correctly-scaled values.
    """
    name = "snapshot_builder"
    
    def __init__(self, config: Optional[SnapshotBuilderConfig] = None):
        self.config = config or SnapshotBuilderConfig()
        # Track typical spread per symbol for comparison
        self._spread_history: dict[str, list[float]] = {}
        # Track EWMA state for fallback flow_rotation calculation
        self._flow_rotation_ewma: dict[str, float] = {}
    
    def _dist_bps(self, price: float, level: Optional[float], mid_price: float) -> float:
        """
        Calculate signed distance in bps using canonical formula.
        
        Formula: (price - level) / mid_price * 10000
        
        Returns positive when price > level, negative when price < level.
        Returns 0.0 if level is None or mid_price <= 0.
        """
        if level is None or mid_price <= 0:
            return 0.0
        return (price - level) / mid_price * 10000.0
    
    def _dist_abs_bps(self, price: float, level: Optional[float], mid_price: float) -> float:
        """
        Calculate absolute distance in bps using canonical formula.
        
        Formula: abs(price - level) / mid_price * 10000
        
        Returns 0.0 if level is None or mid_price <= 0.
        """
        if level is None or mid_price <= 0:
            return 0.0
        return abs(price - level) / mid_price * 10000.0
    
    def _compute_flow_rotation_fallback(
        self, 
        symbol: str,
        imb_1s: float, 
        imb_5s: float, 
        imb_30s: float
    ) -> Tuple[float, float]:
        """
        Compute flow_rotation from orderflow imbalance when AMT levels unavailable.
        
        Uses EWMA smoothing to reduce noise. Returns (smoothed, raw) values.
        
        The raw value is a weighted combination of multi-timeframe imbalances:
        - 50% weight on 1s imbalance (most recent)
        - 30% weight on 5s imbalance
        - 20% weight on 30s imbalance
        
        This ensures flow_rotation is NEVER 0.0 just because AMT levels are missing.
        """
        # Weighted combination of multi-timeframe imbalances
        raw_imb = 0.5 * imb_1s + 0.3 * imb_5s + 0.2 * imb_30s
        raw = raw_imb * self.config.flow_rotation_scale
        
        # EWMA smoothing (alpha = 0.2 for span ~10)
        alpha = 0.2
        if symbol not in self._flow_rotation_ewma:
            self._flow_rotation_ewma[symbol] = raw
        else:
            self._flow_rotation_ewma[symbol] = alpha * raw + (1 - alpha) * self._flow_rotation_ewma[symbol]
        
        smoothed = self._flow_rotation_ewma[symbol]
        
        # Clip to configured range
        smoothed = max(self.config.flow_rotation_clip_min, 
                      min(self.config.flow_rotation_clip_max, smoothed))
        
        return smoothed, raw
    
    def _compute_trend_bias_fallback(
        self,
        trend_direction: str,
        trend_strength: float
    ) -> float:
        """
        Compute trend_bias from trend indicators when AMT levels unavailable.
        
        Returns signed value: positive for uptrend, negative for downtrend.
        Range: approximately [-1, +1]
        
        This ensures trend_bias is NEVER 0.0 just because AMT levels are missing.
        """
        if trend_direction == "up":
            return trend_strength
        elif trend_direction == "down":
            return -trend_strength
        return 0.0  # Only 0 when trend is truly neutral
    
    def _check_poc_staleness(
        self,
        price: float,
        poc_price: Optional[float]
    ) -> Tuple[bool, float]:
        """
        Check if POC appears stale (too far from current price).
        
        Returns (is_stale, distance_pct).
        
        A POC that is >2% from current price is likely stale/default data.
        """
        if poc_price is None or price <= 0:
            return True, 0.0
        
        distance_pct = abs(price - poc_price) / price * 100.0
        is_stale = distance_pct > self.config.poc_staleness_threshold_pct
        
        return is_stale, distance_pct
    
    def _normalize_timestamp(self, raw_timestamp: Optional[float]) -> float:
        """
        FIX #3: Normalize timestamp to seconds since epoch.
        
        Handles multiple input formats defensively:
        - None: returns current time
        - Seconds (< 1e12): returns as-is
        - Milliseconds (1e12 - 1e15): divides by 1000
        - Nanoseconds (> 1e15): divides by 1e9
        
        This prevents silent breakage when upstream provides different units.
        """
        if raw_timestamp is None:
            return 0.0
        
        # Detect unit based on magnitude
        if raw_timestamp > 1e15:
            # Nanoseconds (e.g., 1705000000000000000)
            return raw_timestamp / 1e9
        elif raw_timestamp > 1e12:
            # Milliseconds (e.g., 1705000000000)
            return raw_timestamp / 1000.0
        else:
            # Seconds (e.g., 1705000000)
            return raw_timestamp
    
    def _get_orderflow_imbalance(self, features: dict, ctx_data: dict) -> float:
        """
        FIX #5: Normalize orderflow imbalance from multiple possible keys.
        
        Tries multiple possible key names and returns the first non-None value.
        This prevents "always 0" outcomes from key name inconsistencies.
        
        Priority order:
        1. features["orderflow_imbalance"] - canonical key
        2. ctx_data["orderflow_imbalance"] - from feature worker
        3. features["orderbook_imbalance"] - alternate key
        4. 0.0 - fallback
        """
        # Try canonical key in features
        if features.get("orderflow_imbalance") is not None:
            return features["orderflow_imbalance"]
        
        # Try ctx_data (set by feature worker)
        if ctx_data.get("orderflow_imbalance") is not None:
            return ctx_data["orderflow_imbalance"]
        
        # Try alternate key
        if features.get("orderbook_imbalance") is not None:
            return features["orderbook_imbalance"]
        
        return 0.0
    
    async def run(self, ctx: StageContext) -> StageResult:
        features = ctx.data.get("features") or {}
        market_context = ctx.data.get("market_context") or {}
        
        # Determine if we're in backtest mode
        is_backtest = ctx.data.get("mode") == "backtest"
        
        # Extract core price data
        price = features.get("price") or 0.0
        
        # Data quality tracking
        missing_features: list[str] = []
        data_quality_state = "good"
        
        # FIX #4: Detect bid/ask missingness BEFORE defaulting to price
        # This makes "missing bid/ask" visible even when we fill for continuity
        bid_raw = features.get("bid")
        ask_raw = features.get("ask")
        
        if bid_raw is None or ask_raw is None:
            missing_features.append("bid_ask_missing")
            data_quality_state = "degraded"
            log_warning(
                "snapshot_bid_ask_missing",
                symbol=ctx.symbol,
                bid_present=bid_raw is not None,
                ask_present=ask_raw is not None,
            )
        
        # Now default to price for continuity
        bid = bid_raw if bid_raw is not None else price
        ask = ask_raw if ask_raw is not None else price
        spread_bps = features.get("spread_bps") or 0.0
        
        # Check for invalid bid/ask values (after defaulting)
        if bid <= 0 or ask <= 0:
            if "bid_ask_missing" not in missing_features:
                missing_features.append("bid_ask_invalid")
                data_quality_state = "degraded"
        elif ask < bid:
            # Inverted spread - definitely degraded
            missing_features.append("inverted_spread")
            data_quality_state = "degraded"
            log_warning(
                "snapshot_inverted_spread",
                symbol=ctx.symbol,
                bid=bid,
                ask=ask,
            )
        
        # FIX #1: Calculate mid_price correctly and store it (not price)
        if bid > 0 and ask > 0 and ask >= bid:
            mid_price = (bid + ask) / 2.0
        else:
            mid_price = price
        
        # Validate spread_bps - must be positive
        # If invalid, recalculate from bid/ask or use default
        if spread_bps <= 0:
            if bid > 0 and ask > 0 and ask > bid and mid_price > 0:
                spread_bps = (ask - bid) / mid_price * 10000
            else:
                spread_bps = self.config.default_typical_spread_bps
        # Clamp to reasonable range [0.1, 100.0] bps
        spread_bps = max(0.1, min(100.0, spread_bps))
        
        # FIX #3: Normalize timestamp units defensively
        # Handle seconds, milliseconds, and nanoseconds
        raw_timestamp = features.get("timestamp") or market_context.get("timestamp")
        timestamp = self._normalize_timestamp(raw_timestamp)
        if not timestamp:
            missing_features.append("timestamp_missing")
            data_quality_state = "degraded"
        
        if is_backtest:
            # In backtest mode, snapshot age is always 0 (data is "fresh" relative to backtest clock)
            snapshot_age_ms = 0.0
        else:
            now_ts = (
                ctx.data.get("now_ts_sec")
                or market_context.get("timestamp")
                or features.get("timestamp")
                or timestamp
            )
            snapshot_age_ms = max(0.0, (float(now_ts) - timestamp) * 1000.0)
        
        # Depth metrics - use is not None to preserve legitimate zeros
        bid_depth_raw = features.get("bid_depth_usd")
        ask_depth_raw = features.get("ask_depth_usd")
        bid_depth = bid_depth_raw if bid_depth_raw is not None else 0.0
        ask_depth = ask_depth_raw if ask_depth_raw is not None else 0.0
        depth_total = bid_depth + ask_depth
        depth_imbalance = (bid_depth - ask_depth) / depth_total if depth_total > 0 else 0.0
        
        # FIX #5: Normalize orderflow imbalance key - use single canonical key
        # Try multiple possible keys and normalize to one value
        orderflow_imbalance = self._get_orderflow_imbalance(features, ctx.data)
        
        # Get multi-timeframe orderflow imbalance
        # FIX: Use `is not None` to preserve legitimate 0.0 values
        # First try from ctx.data (set by feature worker with persistence tracking)
        # Fall back to the normalized orderflow_imbalance
        imb_1s_raw = ctx.data.get("imb_1s")
        imb_5s_raw = ctx.data.get("imb_5s")
        imb_30s_raw = ctx.data.get("imb_30s")
        imb_1s = imb_1s_raw if imb_1s_raw is not None else orderflow_imbalance
        imb_5s = imb_5s_raw if imb_5s_raw is not None else orderflow_imbalance
        imb_30s = imb_30s_raw if imb_30s_raw is not None else orderflow_imbalance
        
        persistence_raw = ctx.data.get("orderflow_persistence_sec")
        orderflow_persistence = persistence_raw if persistence_raw is not None else 0.0
        
        # Volatility metrics - calculate from features with PROPER bps scaling
        rv_1s = self._estimate_rv_bps(features, 1.0)
        rv_10s = self._estimate_rv_bps(features, 10.0)
        rv_1m = self._estimate_rv_bps(features, 60.0)
        
        # Vol shock detection: short-term vol >> medium-term vol
        # Add floor to prevent false positives when rv_10s is very small
        vol_shock = rv_1s > max(5.0, rv_10s * 3.0) if rv_10s > 0 else False
        
        # Regime classification - use is not None to preserve legitimate zeros
        vol_regime = market_context.get("volatility_regime") or "normal"
        vol_regime_score = self._vol_regime_to_score(vol_regime)
        trend_direction = market_context.get("trend_direction") or "neutral"
        trend_strength_raw = market_context.get("trend_strength")
        trend_strength = trend_strength_raw if trend_strength_raw is not None else 0.0
        
        # Volume profile levels - Get AMT levels from ctx.data (set by AMTCalculatorStage)
        # Fall back to features dict if amt_levels is None (legacy path)
        # Requirements: 5.1, 5.2, 5.3, 5.4
        amt_levels = ctx.data.get("amt_levels")
        
        if amt_levels:
            # Use AMT levels from AMTCalculatorStage (Requirement 5.3)
            poc_price = amt_levels.point_of_control
            vah_price = amt_levels.value_area_high
            val_price = amt_levels.value_area_low
            position_in_value = amt_levels.position_in_value
            
            # Use BPS distances from AMT levels (they're already in bps)
            # MarketSnapshot now uses _bps suffixed field names
            distance_to_poc = amt_levels.distance_to_poc_bps
            distance_to_vah = amt_levels.distance_to_vah_bps
            distance_to_val = amt_levels.distance_to_val_bps
            
            # Split rotation signals from AMT (Requirement 3.11)
            flow_rotation = amt_levels.flow_rotation
            trend_bias = amt_levels.trend_bias
            rotation_factor = amt_levels.rotation_factor
        else:
            # Fallback to features dict (legacy path) (Requirement 5.4)
            # CRITICAL: Must compute bps values and flow_rotation/trend_bias here too!
            poc_price = features.get("point_of_control")
            vah_price = features.get("value_area_high")
            val_price = features.get("value_area_low")
            position_in_value = features.get("position_in_value") or market_context.get("position_in_value") or "inside"
            
            # Check for stale POC data
            poc_is_stale, poc_distance_pct = self._check_poc_staleness(price, poc_price)
            if poc_is_stale and poc_price is not None:
                log_warning(
                    "snapshot_stale_poc_detected",
                    symbol=ctx.symbol,
                    price=price,
                    poc_price=poc_price,
                    distance_pct=round(poc_distance_pct, 2),
                    threshold_pct=self.config.poc_staleness_threshold_pct,
                )
                missing_features.append("stale_poc")
                data_quality_state = "degraded"
            
            # Calculate distances in BPS using canonical formula
            distance_to_poc = self._dist_bps(price, poc_price, mid_price)
            distance_to_vah = self._dist_abs_bps(price, vah_price, mid_price)
            distance_to_val = self._dist_abs_bps(price, val_price, mid_price)
            
            # Compute flow_rotation and trend_bias even in fallback path
            # NEVER default to 0.0 - always compute from available data
            flow_rotation, _ = self._compute_flow_rotation_fallback(
                ctx.symbol, imb_1s, imb_5s, imb_30s
            )
            trend_bias = self._compute_trend_bias_fallback(trend_direction, trend_strength)
            
            # Legacy rotation_factor for backward compatibility
            rotation_factor = self._calculate_rotation_factor(features, market_context)
            
            # Log that we're using fallback path (once per symbol per session would be better)
            log_info(
                "snapshot_using_fallback_path",
                symbol=ctx.symbol,
                poc_price=poc_price,
                flow_rotation=round(flow_rotation, 3),
                trend_bias=round(trend_bias, 3),
            )
        
        # Execution estimates with freshness and volatility penalties
        expected_slippage = self._estimate_slippage(
            spread_bps, bid_depth, ask_depth, 
            snapshot_age_ms, vol_regime, is_backtest
        )
        if expected_slippage <= 0:
            expected_slippage = self.config.default_slippage_bps
        if self.config.slippage_multiplier != 1.0:
            expected_slippage *= self.config.slippage_multiplier
        if self.config.min_slippage_bps > 0:
            expected_slippage = max(self.config.min_slippage_bps, expected_slippage)
        observed_slippage = (
            market_context.get("observed_slippage_bps")
            or features.get("observed_slippage_bps")
        )
        if observed_slippage is not None:
            try:
                observed_val = float(observed_slippage)
                if observed_val > 0:
                    expected_slippage = max(expected_slippage, observed_val)
            except (TypeError, ValueError):
                pass
        typical_spread = self._get_typical_spread(ctx.symbol, spread_bps)
        
        # Data quality - incorporate our degradation checks
        # Use is not None to preserve legitimate low scores
        base_quality_raw = market_context.get("data_quality_score")
        base_quality_score = base_quality_raw if base_quality_raw is not None else 1.0
        if data_quality_state == "degraded":
            quality_score = min(base_quality_score, 0.5)
        else:
            quality_score = base_quality_score
        
        # FIX #7: WS connection status - default to False when unknown (fail-safe)
        # "Unknown" should degrade risk, not improve it
        trade_sync = market_context.get("trade_sync_state")
        orderbook_sync = market_context.get("orderbook_sync_state")
        
        # Only consider connected if we have explicit confirmation
        # None/missing states are treated as disconnected (fail-safe)
        if trade_sync is None or orderbook_sync is None:
            ws_connected = False
        else:
            ws_connected = (
                trade_sync not in ("disconnected", "error", "stale") and 
                orderbook_sync not in ("disconnected", "error", "stale")
            )
        
        # FIX #1: Build frozen snapshot with correct mid_price (not price)
        snapshot = MarketSnapshot(
            symbol=ctx.symbol,
            exchange=ctx.data.get("exchange") or self.config.default_exchange,
            timestamp_ns=int(timestamp * 1e9),
            snapshot_age_ms=snapshot_age_ms,
            mid_price=mid_price,  # FIX: was storing price, now storing computed mid_price
            bid=bid,
            ask=ask,
            spread_bps=spread_bps,
            bid_depth_usd=bid_depth,
            ask_depth_usd=ask_depth,
            depth_imbalance=depth_imbalance,
            imb_1s=imb_1s,
            imb_5s=imb_5s,
            imb_30s=imb_30s,
            orderflow_persistence_sec=orderflow_persistence,
            rv_1s=rv_1s,
            rv_10s=rv_10s,
            rv_1m=rv_1m,
            vol_shock=vol_shock,
            vol_regime=vol_regime,
            vol_regime_score=vol_regime_score,
            trend_direction=trend_direction,
            trend_strength=trend_strength,
            poc_price=poc_price,
            vah_price=vah_price,
            val_price=val_price,
            position_in_value=position_in_value,
            # AMT distance fields - using _bps suffix (Requirements 2.1)
            distance_to_poc_bps=distance_to_poc,
            distance_to_vah_bps=distance_to_vah,
            distance_to_val_bps=distance_to_val,
            # Split rotation signals (Strategy Signal Architecture Fixes - Requirement 3.11)
            flow_rotation=flow_rotation,
            trend_bias=trend_bias,
            rotation_factor=rotation_factor,
            expected_fill_slippage_bps=expected_slippage,
            typical_spread_bps=typical_spread,
            data_quality_score=quality_score,
            ws_connected=ws_connected,
        )
        
        # Store snapshot in context for all downstream stages
        ctx.data["snapshot"] = snapshot
        
        # Store last_price separately for stages that need raw price (not mid_price)
        # This is useful when mid_price differs from the last traded price
        ctx.data["last_price"] = price
        
        # Store data quality info for downstream stages
        if missing_features:
            ctx.data["snapshot_missing_features"] = missing_features
            ctx.data["snapshot_data_quality_state"] = data_quality_state
        
        return StageResult.CONTINUE
    
    def _estimate_rv_bps(self, features: dict, horizon_sec: float) -> float:
        """
        Estimate realized volatility for given horizon, returning value in BPS.
        
        FIXED: Now properly converts fractional returns to bps.
        FIX #6: Added guard for percent vs fractional format.
        
        If price_change_* is a fractional return (e.g., 0.001 = 0.1%),
        we multiply by 10000 to get bps.
        
        If price_change_* is already in percent (e.g., 0.1 = 0.1%),
        we multiply by 100 to get bps.
        
        Returns volatility in bps (e.g., 10.0 = 10 bps = 0.1% move).
        """
        # Use price changes at different horizons as proxy for RV
        if horizon_sec <= 1.0:
            change = features.get("price_change_1s") or 0.0
        elif horizon_sec <= 10.0:
            change = features.get("price_change_5s") or 0.0
        elif horizon_sec <= 60.0:
            change = features.get("price_change_30s") or features.get("price_change_1m") or 0.0
        else:
            change = features.get("price_change_5m") or 0.0
        
        # FIX #6: Guard for percent vs fractional format
        # If abs(change) > threshold, assume it's already in percent
        abs_change = abs(change)
        if abs_change > self.config.price_change_percent_threshold:
            # Assume it's in percent (e.g., 0.5 = 0.5%), convert to bps
            return abs_change * 100.0
        else:
            # Assume it's fractional (e.g., 0.001 = 0.1%), convert to bps
            return abs_change * 10000.0
    
    def _vol_regime_to_score(self, regime: str) -> float:
        """Convert volatility regime string to numeric score."""
        regime_scores = {
            "low": 0.2,
            "normal": 0.5,
            "high": 0.8,
            "extreme": 1.0,
            "unknown": 0.5,
        }
        return regime_scores.get(regime, 0.5)
    
    def _estimate_slippage(
        self, 
        spread_bps: float, 
        bid_depth: float, 
        ask_depth: float,
        snapshot_age_ms: float,
        vol_regime: str,
        is_backtest: bool
    ) -> float:
        """
        Estimate expected fill slippage based on market conditions.
        
        IMPORTANT: This returns ONE-WAY slippage (entry fill only).
        For round-trip costs, multiply by 2 or add entry + exit separately.
        
        FIXED: Now includes freshness and volatility penalties.
        FIX #2: Fixed volatility penalty logic (extreme branch was unreachable).
        FIX #8: Clarified this is ONE-WAY slippage in docstring.
        
        Components:
        1. Base slippage: half the spread (market orders cross the spread)
        2. Depth penalty: thin books = more slippage
        3. Freshness penalty: stale data = more uncertainty
        4. Volatility penalty: high vol = more slippage
        
        Returns:
            ONE-WAY expected implementation shortfall in bps, including half-spread + penalties.
            This is the expected cost to cross the spread and fill at market.
        """
        # Base slippage is half the spread (market orders cross the spread)
        base_slippage = spread_bps / 2.0
        
        # Depth-based adjustment: thin books = more slippage
        min_depth = min(bid_depth, ask_depth)
        if min_depth < 10000:  # < $10k depth
            depth_penalty = (10000 - min_depth) / 10000 * 2.0  # Up to 2 bps extra
        else:
            depth_penalty = 0.0
        
        # Freshness penalty (only in live mode, not backtest)
        freshness_penalty = 0.0
        if not is_backtest:
            if snapshot_age_ms > 500:
                freshness_penalty = 2.0
            elif snapshot_age_ms > 200:
                freshness_penalty = 1.0
        
        # FIX #2: Volatility penalty - check extreme FIRST (was unreachable before)
        vol_penalty = 0.0
        if vol_regime == "extreme":
            vol_penalty = 3.0
        elif vol_regime == "high":
            vol_penalty = 1.5
        
        return base_slippage + depth_penalty + freshness_penalty + vol_penalty
    
    def _get_typical_spread(self, symbol: str, current_spread: float) -> float:
        """Get typical spread for symbol (rolling average)."""
        if symbol not in self._spread_history:
            self._spread_history[symbol] = []
        
        history = self._spread_history[symbol]
        history.append(current_spread)
        
        # Keep last 100 samples
        if len(history) > 100:
            history.pop(0)
        
        return sum(history) / len(history) if history else current_spread
    
    def _calculate_rotation_factor(self, features: dict, market_context: dict) -> float:
        """
        Calculate rotation factor from orderflow imbalance and trend.
        
        DEPRECATED: This is retained for backward compatibility only.
        Use flow_rotation and trend_bias instead.
        
        The rotation factor combines orderflow imbalance with trend information:
        - Base: orderflow_imbalance * scale_factor (5.0)
        - If trend is "up": add trend_strength * contribution_factor (5.0)
        - If trend is "down": subtract trend_strength * contribution_factor (5.0)
        - Result is clamped to [-15, +15] range
        
        Requirements: 4.1, 4.2, 4.3, 4.4
        """
        # FIX #5: Use normalized orderflow imbalance getter
        # This handles multiple possible key names consistently
        orderflow_imbalance = self._get_orderflow_imbalance(features, market_context)
        
        # Get trend information - use is not None to preserve legitimate zeros
        trend_direction = features.get("trend_direction") or market_context.get("trend_direction")
        trend_strength_raw = features.get("trend_strength")
        if trend_strength_raw is None:
            trend_strength_raw = market_context.get("trend_strength")
        trend_strength = trend_strength_raw if trend_strength_raw is not None else 0.0
        
        # Scale factors
        scale_factor = 5.0
        contribution_factor = 5.0
        
        # Calculate base rotation from orderflow imbalance (Requirement 4.1)
        base_rotation = orderflow_imbalance * scale_factor
        
        # Calculate trend contribution based on trend direction
        trend_contribution = 0.0
        if trend_direction == "up":
            # Add trend_strength contribution when trend is up (Requirement 4.2)
            trend_contribution = trend_strength * contribution_factor
        elif trend_direction == "down":
            # Subtract trend_strength contribution when trend is down (Requirement 4.3)
            trend_contribution = -trend_strength * contribution_factor
        
        # Calculate total rotation factor
        rotation_factor = base_rotation + trend_contribution
        
        # Clamp result to [-15, +15] range (Requirement 4.4)
        rotation_factor = max(-15.0, min(15.0, rotation_factor))
        
        return rotation_factor
