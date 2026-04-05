"""AMT Value Area Rejection Scalp Strategy

Refactored from the original fast_scalper decision_engine.py logic.

Entry rules:
- LONG: Price below VAL + strong rotation up + within margin
- SHORT: Price above VAH + strong rotation down + within margin
- MUST have sufficient edge after costs (fees + slippage)

Parameters (from profile config):
- allow_longs / allow_shorts: Enable long/short trades
- rotation_threshold: Minimum rotation factor
- value_margin: Distance threshold from VAL/VAH
- risk_per_trade_pct: Position size as % of equity
- stop_loss_pct: Stop loss distance
- max_spread: Maximum spread filter
- min_edge_bps: Minimum edge after fees/slippage (default 8 bps)
"""

from typing import Optional, Dict, Any
import logging
import os
from quantgambit.deeptrader_core.types import Features, AccountState, Profile, StrategySignal
from .base import Strategy


class AmtValueAreaRejectionScalp(Strategy):
    """AMT-based value area rejection scalping strategy"""
    
    strategy_id = "amt_value_area_rejection_scalp"
    
    # Trading cost estimates
    DEFAULT_FEE_BPS = float(os.getenv("STRATEGY_FEE_BPS", "5.5"))  # Round-trip fees
    DEFAULT_SLIPPAGE_BPS = float(os.getenv("STRATEGY_SLIPPAGE_BPS", "2.0"))  # Expected slippage
    
    def __init__(self):
        super().__init__()
        self._logger = logging.getLogger(__name__)

    def _trace_enabled(self) -> bool:
        return os.getenv("DECISION_GATE_TRACE_VERBOSE", "false").lower() in {"1", "true", "yes"}
    
    def generate_signal(
        self,
        features: Features,
        account: AccountState,
        profile: Profile,
        params: Dict[str, Any],
    ) -> Optional[StrategySignal]:
        """
        Generate AMT rejection signal
        
        Returns StrategySignal if valid setup found, None otherwise
        """
        # Extract params with defaults
        allow_longs = params.get("allow_longs", True)
        allow_shorts = params.get("allow_shorts", True)
        rotation_threshold = params.get("rotation_threshold", 3.0)
        value_margin = params.get("value_margin", 0.001)
        risk_per_trade_pct = params.get("risk_per_trade_pct", 0.02)
        stop_loss_pct = params.get("stop_loss_pct", 0.012)  # 1.2%
        
        # CRITICAL: Max orderflow imbalance against our trade direction
        # Exit logic triggers at 0.6, so don't enter if imbalance would immediately trigger exit
        max_adverse_orderflow = params.get("max_adverse_orderflow", 0.5)
        
        # Minimum edge requirement
        min_edge_bps = params.get("min_edge_bps", 8.0)  # 8 bps minimum edge after costs
        fee_bps = params.get("fee_bps", self.DEFAULT_FEE_BPS)
        slippage_bps = params.get("slippage_bps", self.DEFAULT_SLIPPAGE_BPS)
        total_cost_bps = fee_bps + slippage_bps
        
        # Fast filters
        max_spread = params.get("max_spread", 0.001)
        if features.spread > max_spread:
            if self._trace_enabled():
                self._logger.info(
                    "[%s] amt_value_area_rejection_scalp: Rejecting - spread too wide. spread=%.6f max_spread=%.6f",
                    features.symbol,
                    features.spread,
                    max_spread,
                )
            return None
        if (
            features.distance_to_val is None
            or features.distance_to_vah is None
            or features.distance_to_poc is None
        ):
            if self._trace_enabled():
                self._logger.info(
                    "[%s] amt_value_area_rejection_scalp: Rejecting - missing distance metrics. "
                    "dist_val=%s dist_vah=%s dist_poc=%s",
                    features.symbol,
                    features.distance_to_val,
                    features.distance_to_vah,
                    features.distance_to_poc,
                )
            return None
        
        # Edge check: potential profit (distance to POC) minus costs must exceed minimum
        distance_to_poc_bps = abs(features.distance_to_poc / features.price) * 10000
        expected_profit_bps = distance_to_poc_bps - total_cost_bps
        if expected_profit_bps < min_edge_bps:
            if self._trace_enabled():
                self._logger.info(
                    "[%s] amt_value_area_rejection_scalp: Rejecting - edge too small. "
                    "expected_profit_bps=%.2f min_edge_bps=%.2f total_cost_bps=%.2f",
                    features.symbol,
                    expected_profit_bps,
                    min_edge_bps,
                    total_cost_bps,
                )
            return None  # No edge after costs!
        
        # LONG: below VAL + strong rotation up
        if allow_longs and features.position_in_value == "below":
            # CRITICAL: Check orderflow imbalance - don't long into strong sell pressure
            orderflow = features.orderflow_imbalance
            if orderflow is not None and orderflow < -max_adverse_orderflow:
                if self._trace_enabled():
                    self._logger.info(
                        "[%s] amt_value_area_rejection_scalp: Rejecting long - adverse orderflow. "
                        "orderflow=%.3f max_adverse=%.3f",
                        features.symbol,
                        orderflow,
                        -max_adverse_orderflow,
                    )
                return None  # Too much sell pressure to long
            
            if features.rotation_factor > rotation_threshold:
                if features.distance_to_val <= value_margin * features.price:
                    size = risk_per_trade_pct * account.equity / features.price
                    entry = features.price
                    sl = entry * (1.0 - stop_loss_pct)
                    tp = features.price + features.distance_to_poc
                    
                    return StrategySignal(
                        strategy_id=self.strategy_id,
                        symbol=features.symbol,
                        side="long",
                        size=size,
                        entry_price=entry,
                        stop_loss=sl,
                        take_profit=tp,
                        meta_reason="below_val_strong_rotation",
                        profile_id=profile.id
                    )
            else:
                if self._trace_enabled():
                    self._logger.info(
                        "[%s] amt_value_area_rejection_scalp: Rejecting long - rotation below threshold. "
                        "rotation=%.3f threshold=%.3f",
                        features.symbol,
                        features.rotation_factor,
                        rotation_threshold,
                    )
        
        # SHORT: above VAH + strong rotation down
        if allow_shorts and features.position_in_value == "above":
            # CRITICAL: Check orderflow imbalance - don't short into strong buy pressure
            orderflow = features.orderflow_imbalance
            if orderflow is not None and orderflow > max_adverse_orderflow:
                if self._trace_enabled():
                    self._logger.info(
                        "[%s] amt_value_area_rejection_scalp: Rejecting short - adverse orderflow. "
                        "orderflow=%.3f max_adverse=%.3f",
                        features.symbol,
                        orderflow,
                        max_adverse_orderflow,
                    )
                return None  # Too much buy pressure to short
            
            if features.rotation_factor < -rotation_threshold:
                if features.distance_to_vah <= value_margin * features.price:
                    size = risk_per_trade_pct * account.equity / features.price
                    entry = features.price
                    sl = entry * (1.0 + stop_loss_pct)
                    tp = features.price - features.distance_to_poc
                    
                    return StrategySignal(
                        strategy_id=self.strategy_id,
                        symbol=features.symbol,
                        side="short",
                        size=size,
                        entry_price=entry,
                        stop_loss=sl,
                        take_profit=tp,
                        meta_reason="above_vah_strong_rotation",
                        profile_id=profile.id
                    )
            else:
                if self._trace_enabled():
                    self._logger.info(
                        "[%s] amt_value_area_rejection_scalp: Rejecting short - rotation above threshold. "
                        "rotation=%.3f threshold=%.3f",
                        features.symbol,
                        features.rotation_factor,
                        -rotation_threshold,
                    )
        
        return None
