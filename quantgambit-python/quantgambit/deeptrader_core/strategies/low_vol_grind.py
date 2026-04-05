"""
Low Volatility Grind Strategy

Profits from extremely tight ranges with micro support/resistance scalping.
Focuses on ultra-low volatility periods with frequent small wins.

Entry Conditions:
- ATR must be < 0.75x baseline (still low volatility)
- Price within 0.10% of POC (micro proximity)
- Very tight spread (< 0.05%)
- Sufficient liquidity (trades per second)
- Mean reversion back to POC from extremes
- Sufficient edge after fees (expected profit > min_edge_bps)

Risk Management:
- Very tight stops (0.15%) to minimize risk
- Small targets (0.4%) for frequent wins
- Conservative position sizing (0.3% risk)
- High win rate expected (60-70%)

Ideal Market Conditions:
- Flat/inside value area
- Low volatility (ATR < 0.5x baseline)
- Overnight or Asia session (typically)
- High liquidity despite low volatility

Symbol-Adaptive Parameters (Requirement 4.6):
- stop_loss_pct: Read from resolved_params if available
- max_spread: Read from resolved_params.max_spread_bps if available

Fee-Aware Entry Filtering (US-4):
- min_edge_bps: Minimum edge after fees/slippage (default 3 bps, configurable via STRATEGY_MIN_EDGE_BPS)
- fee_bps: Estimated round-trip fees in basis points (default 6 bps, configurable via STRATEGY_FEE_BPS)
- slippage_bps: Estimated slippage in basis points (default 2 bps, configurable via STRATEGY_SLIPPAGE_BPS)
"""

from typing import Optional, Dict, Any
import logging
import os
from quantgambit.deeptrader_core.types import Features, AccountState, Profile, StrategySignal
from .base import Strategy
from quantgambit.observability.logger import log_info

logger = logging.getLogger(__name__)

# Symbol-specific overrides let us loosen/tighten BTC without changing global behavior.
# Format: "BTCUSDT:1.0,ETHUSDT:0.8"
def _parse_symbol_float_map(raw: str) -> Dict[str, float]:
    parsed: Dict[str, float] = {}
    if not raw:
        return parsed
    for token in raw.split(","):
        token = token.strip()
        if not token or ":" not in token:
            continue
        sym_raw, val_raw = token.split(":", 1)
        sym = sym_raw.strip().upper()
        try:
            val = float(val_raw.strip())
        except ValueError:
            continue
        if sym:
            parsed[sym] = val
    return parsed


def _symbol_override(symbol: str, env_key: str) -> Optional[float]:
    sym = (symbol or "").upper()
    if not sym:
        return None
    raw = os.getenv(env_key, "")
    return _parse_symbol_float_map(raw).get(sym)


# Default values used when resolved_params unavailable
DEFAULT_STOP_LOSS_PCT = 0.008  # 0.8% (scalp-sized fallback)
DEFAULT_MAX_SPREAD = 0.0005  # 0.05%

# Fee-aware entry filtering defaults (US-4)
# RELAXED: Reduced from 8.0 to 3.0 bps for scalping (was blocking most trades)
# Can be overridden via STRATEGY_MIN_EDGE_BPS environment variable
DEFAULT_MIN_EDGE_BPS = float(os.getenv("STRATEGY_MIN_EDGE_BPS", "3.0"))
DEFAULT_FEE_BPS = float(os.getenv("STRATEGY_FEE_BPS", "6.0"))  # Round-trip fees (~0.06% taker)
DEFAULT_SLIPPAGE_BPS = float(os.getenv("STRATEGY_SLIPPAGE_BPS", "2.0"))  # Expected slippage


class LowVolGrind(Strategy):
    """
    Low volatility grind strategy for micro scalping.
    
    Symbol-Adaptive Parameters (Requirement 4.6):
    This strategy reads stop_loss_pct and max_spread from resolved_params
    when available, falling back to hardcoded defaults if unavailable.
    """
    strategy_id = "low_vol_grind"

    def generate_signal(
        self,
        features: Features,
        account: AccountState,
        profile: Profile,
        params: Dict[str, Any],
    ) -> Optional[StrategySignal]:
        """
        Generate signal for low volatility grind strategy.
        
        Args:
            features: Market features including price, AMT metrics, indicators
            account: Account state for position sizing
            profile: Current market profile
            params: Strategy parameters from profile config. May contain:
                - resolved_params: ResolvedParameters with symbol-adaptive values
                - symbol_characteristics: SymbolCharacteristics for transparency
            
        Returns:
            StrategySignal if conditions met, None otherwise
        """
        # Extract resolved parameters if available (Requirement 4.6)
        resolved_params = params.get("resolved_params")
        
        # Check if longs/shorts are allowed
        # Default to allowing both unless explicitly disabled.
        allow_longs = bool(params.get("allow_longs", True))
        allow_shorts = bool(params.get("allow_shorts", True))
        if not allow_longs and not allow_shorts:
            return None
        
        # Must be flat or inside value area for grind strategy
        if profile.value_location not in ["flat", "inside"]:
            return None
        
        # max_spread is expressed as a decimal fraction (e.g. 0.0005 = 5 bps).
        # Features.spread in our pipeline is an absolute price delta, so convert to pct here.
        spread_pct = (features.spread / features.price) if (features.price and features.price > 0) else 0.0
        if resolved_params is not None and hasattr(resolved_params, "max_spread_bps"):
            max_spread_pct = resolved_params.max_spread_bps / 10000.0  # bps -> decimal
        else:
            max_spread_pct = float(params.get("max_spread", DEFAULT_MAX_SPREAD))

        if spread_pct > max_spread_pct:
            log_info(
                f"LowVolGrind: Spread too wide ({spread_pct * 10000:.2f} bps) for {features.symbol}"
            )
            return None
        
        # Validate required features
        if not features.point_of_control:
            log_info(f"LowVolGrind: Missing POC data for {features.symbol}")
            return None
        
        # Check for ultra-low ATR (core requirement)
        atr_ratio = features.atr_5m / features.atr_5m_baseline if features.atr_5m_baseline > 0 else 1.0
        max_atr_ratio = params.get("max_atr_ratio", 0.75)
        override_atr = _symbol_override(features.symbol, "LOW_VOL_GRIND_MAX_ATR_RATIO_BY_SYMBOL")
        if override_atr is not None:
            max_atr_ratio = override_atr
        
        if atr_ratio > max_atr_ratio:
            # Volatility too high for grind strategy
            return None
        
        # Check for sufficient liquidity
        min_trades_per_second = params.get("min_trades_per_second", 1.2)
        if features.trades_per_second < min_trades_per_second:
            log_info(f"LowVolGrind: Insufficient liquidity ({features.trades_per_second:.1f} tps) for {features.symbol}")
            return None

        # Check if we're in a micro range
        micro_range_pct = params.get("micro_range_pct", 0.004)
        if features.value_area_high and features.value_area_low:
            value_range = (features.value_area_high - features.value_area_low) / features.price
            if value_range > micro_range_pct:
                log_info(f"LowVolGrind: Range too wide ({value_range:.4f}) for micro scalping on {features.symbol}")
                return None

        signal_side = None
        entry_price = features.price
        stop_loss = 0.0
        take_profit = 0.0
        meta_reason = ""

        poc_proximity_pct = params.get("poc_proximity_pct", 0.001)
        override_poc = _symbol_override(features.symbol, "LOW_VOL_GRIND_POC_PROXIMITY_PCT_BY_SYMBOL")
        if override_poc is not None:
            poc_proximity_pct = override_poc
        poc_distance = abs(features.price - features.point_of_control)
        poc_distance_pct = poc_distance / features.price
        
        # Fee-aware entry filtering parameters (US-4)
        min_edge_bps = params.get("min_edge_bps", DEFAULT_MIN_EDGE_BPS)
        fee_bps = params.get("fee_bps", DEFAULT_FEE_BPS)
        slippage_bps = params.get("slippage_bps", DEFAULT_SLIPPAGE_BPS)
        total_cost_bps = fee_bps + slippage_bps
        
        # Fee-aware edge check (US-4): expected profit must exceed costs + minimum edge
        # Expected profit = distance to POC (our target for mean reversion)
        expected_profit_bps = poc_distance_pct * 10000 - total_cost_bps
        
        if expected_profit_bps < min_edge_bps:
            logger.info(
                f"[{features.symbol}] low_vol_grind: Rejecting entry - insufficient edge. "
                f"expected_profit={expected_profit_bps:.1f}bps, min_edge={min_edge_bps:.1f}bps, "
                f"distance_to_poc={poc_distance_pct * 10000:.1f}bps, costs={total_cost_bps:.1f}bps"
            )
            return None  # No edge after costs!
        
        # stop_loss_pct: Use resolved_params if available (Requirement 4.6)
        if resolved_params is not None and hasattr(resolved_params, "stop_loss_pct"):
            stop_loss_pct = resolved_params.stop_loss_pct
        else:
            stop_loss_pct = params.get("stop_loss_pct", DEFAULT_STOP_LOSS_PCT)

        # Long signal: Price slightly below POC, expecting mean reversion up
        if allow_longs and \
           features.price < features.point_of_control and \
           poc_distance_pct < poc_proximity_pct * 3:  # Within 0.15% of POC
            
            # Need slight upward rotation or price stabilization
            if features.rotation_factor >= -1.0:  # Not strongly rotating down
                signal_side = "long"
                stop_loss = features.price * (1 - stop_loss_pct)
                take_profit = features.point_of_control * (1 + poc_proximity_pct)  # Target just above POC
                meta_reason = f"low_vol_grind_long_below_poc_atr_{atr_ratio:.2f}x"

        # Short signal: Price slightly above POC, expecting mean reversion down
        elif allow_shorts and \
             features.price > features.point_of_control and \
             poc_distance_pct < poc_proximity_pct * 3:  # Within 0.15% of POC
            
            # Need slight downward rotation or price stabilization
            if features.rotation_factor <= 1.0:  # Not strongly rotating up
                signal_side = "short"
                stop_loss = features.price * (1 + stop_loss_pct)
                take_profit = features.point_of_control * (1 - poc_proximity_pct)  # Target just below POC
                meta_reason = f"low_vol_grind_short_above_poc_atr_{atr_ratio:.2f}x"

        if signal_side:
            # Calculate position size - conservative for grinding strategy
            risk_per_trade_pct = params.get("risk_per_trade_pct", 0.003)
            price_diff = abs(entry_price - stop_loss)
            
            if price_diff == 0:
                log_info(f"LowVolGrind: Stop loss price is same as entry price for {features.symbol}, cannot calculate size.")
                return None
            
            # Position size based on risk percentage and stop distance
            position_value = account.equity * (risk_per_trade_pct / stop_loss_pct)
            size = position_value / entry_price
            
            if size <= 0:
                log_info(f"LowVolGrind: Calculated size is zero or negative for {features.symbol}")
                return None

            log_info(f"LowVolGrind: Generated {signal_side} signal for {features.symbol} @ {entry_price:.2f} "
                    f"with size {size:.4f}. ATR: {atr_ratio:.2f}x baseline. POC: {features.point_of_control:.2f}. "
                    f"SL: {stop_loss:.2f}, TP: {take_profit:.2f}. Reason: {meta_reason}")
            
            return StrategySignal(
                strategy_id=self.strategy_id,
                symbol=features.symbol,
                side=signal_side,
                size=size,
                entry_price=entry_price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                meta_reason=meta_reason,
                profile_id=profile.id
            )
        
        return None
