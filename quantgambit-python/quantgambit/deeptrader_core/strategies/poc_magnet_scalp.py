"""POC Magnet Scalp Strategy

Theory:
The Point of Control (POC) represents the price level with the highest traded volume.
It acts as a "magnet" - price tends to revert to this level, especially when inside
the value area.

Entry Logic:
- Price is INSIDE value area (between VAL and VAH)
- Price is sufficiently far from POC (> distance_threshold in bps)
- Rotation is moving TOWARDS POC (confirming the magnet effect)
- Trade direction: Always towards POC
- MUST have sufficient edge after costs (fees + slippage)

BPS Standardization (Strategy Signal Architecture Fixes Requirement 1.4.3):
- min_distance_from_poc_bps: Distance threshold in basis points (default 12 bps)
- Uses canonical formula: (price - poc) / mid_price * 10000
- All threshold logging includes "bps" suffix for clarity

Exit Logic:
- Take profit: At or near POC
- Stop loss: Beyond VAL/VAH (price breaking out of value area)

Parameters:
- min_distance_from_poc_bps: Minimum bps distance from POC to enter (default 12 bps)
- max_distance_from_poc_bps: Maximum bps distance (too far = different regime)
- rotation_threshold: Minimum rotation strength towards POC
- risk_per_trade_pct: Position size as % of equity
- stop_loss_pct: Stop loss distance
- take_profit_at_poc: Whether to exit at POC or slightly before
- max_spread: Maximum spread filter
- min_edge_bps: Minimum edge after fees/slippage (default 5 bps)
"""

from typing import Optional, Dict, Any
import os
from quantgambit.deeptrader_core.types import Features, AccountState, Profile, StrategySignal
from quantgambit.core.unit_converter import pct_to_bps, bps_to_pct
from .base import Strategy


def _parse_key_float_map(raw: str) -> Dict[str, float]:
    parsed: Dict[str, float] = {}
    if not raw:
        return parsed
    normalized = raw.replace(";", ",")
    for token in normalized.split(","):
        token = token.strip()
        if not token or ":" not in token:
            continue
        key_raw, val_raw = token.split(":", 1)
        key = key_raw.strip().upper()
        if not key:
            continue
        try:
            parsed[key] = float(val_raw.strip())
        except ValueError:
            continue
    return parsed


def _symbol_session_override(
    symbol: str,
    session: str,
    by_symbol_env: str,
    by_symbol_session_env: str,
) -> Optional[float]:
    symbol_key = (symbol or "").strip().upper()
    session_key = (session or "").strip().upper()
    if not symbol_key:
        return None
    by_symbol = _parse_key_float_map(os.getenv(by_symbol_env, ""))
    by_symbol_session = _parse_key_float_map(os.getenv(by_symbol_session_env, ""))
    composite_key = f"{symbol_key}@{session_key}" if session_key else ""
    if composite_key and composite_key in by_symbol_session:
        return by_symbol_session[composite_key]
    return by_symbol.get(symbol_key)


class POCMagnetScalp(Strategy):
    """POC Magnet mean reversion scalping strategy"""
    
    strategy_id = "poc_magnet_scalp"
    
    # Trading cost estimates (should match actual exchange fees)
    DEFAULT_FEE_BPS = 2.0  # Entry + exit fees
    DEFAULT_SLIPPAGE_BPS = 2.0  # Expected slippage
    
    # BPS Standardization defaults (Requirement 1.4.3)
    DEFAULT_MIN_DISTANCE_FROM_POC_BPS = 12.0  # 12 bps = 0.12%
    DEFAULT_MAX_DISTANCE_FROM_POC_BPS = 150.0  # 150 bps = 1.5%
    
    def generate_signal(
        self,
        features: Features,
        account: AccountState,
        profile: Profile,
        params: Dict[str, Any],
    ) -> Optional[StrategySignal]:
        """
        Generate POC magnet signal
        
        Returns StrategySignal if valid setup found, None otherwise
        """
        # BPS Standardization: Extract params with bps as primary unit (Requirement 1.4.3)
        # Support both bps and legacy pct parameters
        if "min_distance_from_poc_bps" in params:
            min_distance_from_poc_bps = params["min_distance_from_poc_bps"]
        elif "min_distance_from_poc" in params:
            # Legacy: Convert pct to bps
            min_distance_from_poc_bps = pct_to_bps(params["min_distance_from_poc"])
        else:
            min_distance_from_poc_bps = self.DEFAULT_MIN_DISTANCE_FROM_POC_BPS
        
        if "max_distance_from_poc_bps" in params:
            max_distance_from_poc_bps = params["max_distance_from_poc_bps"]
        elif "max_distance_from_poc" in params:
            # Legacy: Convert pct to bps
            max_distance_from_poc_bps = pct_to_bps(params["max_distance_from_poc"])
        else:
            max_distance_from_poc_bps = self.DEFAULT_MAX_DISTANCE_FROM_POC_BPS
        
        rotation_threshold = params.get("rotation_threshold", 1.0)
        short_rotation_max = params.get("short_rotation_max", -float(rotation_threshold))
        long_rotation_min = params.get("long_rotation_min", float(rotation_threshold))
        risk_per_trade_pct = params.get("risk_per_trade_pct", 0.01)
        stop_loss_pct = params.get("stop_loss_pct", 0.012)  # 1.2%
        take_profit_at_poc = params.get("take_profit_at_poc", True)
        poc_offset_pct = params.get("poc_offset_pct", 0.001)  # Exit 0.1% before POC
        allow_longs = params.get("allow_longs", True)
        allow_shorts = params.get("allow_shorts", True)
        
        # CRITICAL: Max orderflow imbalance against our trade direction
        # Exit logic triggers at 0.6, so don't enter if imbalance would immediately trigger exit
        max_adverse_orderflow = params.get("max_adverse_orderflow", 0.5)
        
        # Minimum edge requirement (profit target - costs must exceed this)
        min_edge_bps = params.get("min_edge_bps", 5.0)  # 5 bps minimum edge after costs
        fee_bps = params.get("fee_bps", self.DEFAULT_FEE_BPS)
        slippage_bps = params.get("slippage_bps", self.DEFAULT_SLIPPAGE_BPS)
        total_cost_bps = fee_bps + slippage_bps

        # Optional scoped overrides for fast live tuning without changing global profiles.
        session = getattr(profile, "session", "") or ""
        short_rotation_override = _symbol_session_override(
            features.symbol,
            session,
            "POC_MAGNET_SHORT_ROTATION_MAX_BY_SYMBOL",
            "POC_MAGNET_SHORT_ROTATION_MAX_BY_SYMBOL_SESSION",
        )
        if short_rotation_override is not None:
            short_rotation_max = float(short_rotation_override)
        long_rotation_override = _symbol_session_override(
            features.symbol,
            session,
            "POC_MAGNET_LONG_ROTATION_MIN_BY_SYMBOL",
            "POC_MAGNET_LONG_ROTATION_MIN_BY_SYMBOL_SESSION",
        )
        if long_rotation_override is not None:
            long_rotation_min = float(long_rotation_override)
        
        # Fast filters
        if features.spread > params.get("max_spread", 0.002):
            return None
        if features.distance_to_poc is None:
            return None
        
        # Must be INSIDE value area
        if features.position_in_value != "inside":
            return None
        
        # BPS Standardization: Calculate distance from POC in bps (Requirement 1.4.3)
        # Use distance_to_poc_bps if available from AMTLevels, otherwise calculate
        if hasattr(features, 'distance_to_poc_bps') and features.distance_to_poc_bps is not None:
            distance_from_poc_bps = abs(features.distance_to_poc_bps)
        else:
            # Fallback: Calculate using canonical formula with price as mid_price
            distance_from_poc_bps = abs(features.distance_to_poc) / features.price * 10000
        
        # Edge check: potential profit (distance to POC) minus costs must exceed minimum
        expected_profit_bps = distance_from_poc_bps - total_cost_bps
        if expected_profit_bps < min_edge_bps:
            return None  # No edge after costs!
        
        # Must be far enough from POC to justify trade (in bps)
        if distance_from_poc_bps < min_distance_from_poc_bps:
            return None
        
        # But not TOO far (different regime) (in bps)
        if distance_from_poc_bps > max_distance_from_poc_bps:
            return None
        
        # Determine which side of POC we're on and trade direction
        # If price > POC, we're above POC → trade SHORT (towards POC)
        # If price < POC, we're below POC → trade LONG (towards POC)
        
        price_above_poc = features.price > (features.price - features.distance_to_poc)
        
        if price_above_poc:
            # Price ABOVE POC → Consider SHORT (down to POC)
            if not allow_shorts:
                return None
            
            # CRITICAL: Check orderflow imbalance - don't short into strong buy pressure
            orderflow = features.orderflow_imbalance
            if orderflow is not None and orderflow > max_adverse_orderflow:
                return None  # Too much buy pressure to short
            
            # Need downward rotation towards POC (overrideable via short_rotation_max).
            if features.rotation_factor > short_rotation_max:
                return None
            
            # Calculate trade parameters
            size = risk_per_trade_pct * account.equity / features.price
            entry = features.price
            
            # Stop loss: Above current price (if price moves away from POC)
            sl = entry * (1.0 + stop_loss_pct)
            
            # Take profit: At POC (or slightly before to ensure fill)
            poc_price = entry - features.distance_to_poc
            if take_profit_at_poc:
                tp = poc_price * (1.0 + poc_offset_pct)  # Slightly above POC
            else:
                tp = poc_price
            
            return StrategySignal(
                strategy_id=self.strategy_id,
                symbol=features.symbol,
                side="short",
                size=size,
                entry_price=entry,
                stop_loss=sl,
                take_profit=tp,
                meta_reason=f"poc_magnet_short_dist_{distance_from_poc_bps:.1f}bps",
                profile_id=profile.id
            )
        
        else:
            # Price BELOW POC → Consider LONG (up to POC)
            if not allow_longs:
                return None
            
            # CRITICAL: Check orderflow imbalance - don't long into strong sell pressure
            orderflow = features.orderflow_imbalance
            if orderflow is not None and orderflow < -max_adverse_orderflow:
                return None  # Too much sell pressure to long
            
            # Need upward rotation towards POC (overrideable via long_rotation_min).
            if features.rotation_factor < long_rotation_min:
                return None
            
            # Calculate trade parameters
            size = risk_per_trade_pct * account.equity / features.price
            entry = features.price
            
            # Stop loss: Below current price (if price moves away from POC)
            sl = entry * (1.0 - stop_loss_pct)
            
            # Take profit: At POC (or slightly before to ensure fill)
            poc_price = entry + features.distance_to_poc
            if take_profit_at_poc:
                tp = poc_price * (1.0 - poc_offset_pct)  # Slightly below POC
            else:
                tp = poc_price
            
            return StrategySignal(
                strategy_id=self.strategy_id,
                symbol=features.symbol,
                side="long",
                size=size,
                entry_price=entry,
                stop_loss=sl,
                take_profit=tp,
                meta_reason=f"poc_magnet_long_dist_{distance_from_poc_bps:.1f}bps",
                profile_id=profile.id
            )
        
        return None
