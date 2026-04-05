"""Spot Dip Accumulator Strategy

Buys dips using AMT levels and model direction for intelligent spot accumulation.
Unlike scalp strategies, this targets wider moves (50-200 bps) and holds longer.

Entry conditions:
- Price at or below VAL (value area low) — buying the dip
- OR price near POC with strong upward trend — buying momentum
- Model predicts "up" direction (injected via prediction pipeline)
- Orderflow not strongly adverse

Exit via position guard:
- Trailing stop at configurable distance
- Time-based exit if no progress
- TP at configurable distance (default 150 bps / 1.5%)
"""

import os
import logging
from typing import Optional, Dict, Any

from quantgambit.deeptrader_core.strategies.base import Strategy
from quantgambit.deeptrader_core.types import Features, AccountState, Profile, StrategySignal

try:
    from quantgambit.ai.sentiment_reader import get_sentiment
except ImportError:
    def get_sentiment(symbol: str) -> float: return 0.0

try:
    from quantgambit.ai.prediction_reader import get_prediction
except ImportError:
    def get_prediction(symbol: str) -> dict: return {}


class SpotDipAccumulator(Strategy):

    strategy_id = "spot_dip_accumulator"

    def __init__(self):
        self._logger = logging.getLogger(__name__)

    def _trace_enabled(self) -> bool:
        return os.getenv("TRACE_STRATEGIES", "false").lower() in {"1", "true", "yes"}
    
    def generate_exit_signal(
        self,
        position: Any,  # PositionSnapshot
        features: Features,
        params: Dict[str, Any],
    ) -> Optional[StrategySignal]:
        """Generate exit signals for open spot positions.
        
        Exit conditions:
        - Take profit hit
        - Stop loss hit
        - Max hold time exceeded
        - Adverse market conditions (strong downtrend)
        """
        if not position or not position.entry_price:
            return None
        
        price = features.price
        entry_price = position.entry_price
        pnl_pct = (price - entry_price) / entry_price
        
        # Take profit
        take_profit_pct = params.get("take_profit_pct", 0.015)
        if pnl_pct >= take_profit_pct:
            return self._build_exit_signal(position, "take_profit_hit")
        
        # Stop loss
        stop_loss_pct = params.get("stop_loss_pct", 0.03)
        if pnl_pct <= -stop_loss_pct:
            return self._build_exit_signal(position, "stop_loss_hit")
        
        # Max hold time
        if position.opened_at:
            max_hold_sec = params.get("max_hold_sec", 14400)  # 4 hours default
            hold_time = features.timestamp - position.opened_at if features.timestamp else 0
            if hold_time > max_hold_sec:
                return self._build_exit_signal(position, "max_hold_exceeded")
        
        # Adverse conditions: strong downtrend + negative orderflow
        if features.trend_direction == "down" and features.trend_strength > 0.5:
            ofi = features.orderflow_imbalance
            if ofi is not None and ofi < -0.5:
                return self._build_exit_signal(position, "adverse_conditions")
        
        # Model predicts strong down move
        pred = get_prediction(features.symbol)
        if pred.get("direction") == "down" and pred.get("confidence", 0) > 0.7:
            return self._build_exit_signal(position, "model_exit_signal")
        
        return None
    
    def _build_exit_signal(self, position: Any, reason: str) -> StrategySignal:
        """Build exit signal to close position."""
        return StrategySignal(
            strategy_id=self.strategy_id,
            symbol=position.symbol,
            side="sell",  # Sell to close long spot position
            size=position.size,
            entry_price=None,  # Market order
            stop_loss=None,
            take_profit=None,
            meta_reason=reason,
            profile_id="spot_accumulation",
            is_exit_signal=True,
            reduce_only=False,  # Spot doesn't use reduce_only
        )

    def generate_signal(
        self,
        features: Features,
        account: AccountState,
        profile: Profile,
        params: Dict[str, Any],
    ) -> Optional[StrategySignal]:

        # --- params with spot-friendly defaults ---
        stop_loss_pct = params.get("stop_loss_pct", 0.03)       # 3% SL (300 bps)
        take_profit_pct = params.get("take_profit_pct", 0.015)  # 1.5% TP (150 bps)
        risk_per_trade_pct = params.get("risk_per_trade_pct", 0.05)
        max_spread = params.get("max_spread", 0.002)            # wider spread tolerance for spot
        min_poc_distance_bps = params.get("min_poc_distance_bps", 15.0)
        max_adverse_orderflow = params.get("max_adverse_orderflow", 0.6)

        # --- fast filters ---
        if features.spread > max_spread:
            return None

        if features.distance_to_poc is None or features.distance_to_val is None:
            return None

        # Sentiment gate: don't buy into strong negative sentiment
        sentiment_floor = params.get("sentiment_floor", -0.5)
        sentiment = get_sentiment(features.symbol)
        if sentiment < sentiment_floor:
            if self._trace_enabled():
                self._logger.info("[%s] spot_dip: reject — sentiment %.2f < %.2f", features.symbol, sentiment, sentiment_floor)
            return None

        # Model gate: don't buy when ONNX predicts down
        pred = get_prediction(features.symbol)
        if pred.get("direction") == "down" and not pred.get("reject"):
            if self._trace_enabled():
                self._logger.info("[%s] spot_dip: reject — model predicts down (p=%.2f)", features.symbol, pred.get("confidence", 0))
            return None

        # Spot = long only
        # Don't buy into strong sell pressure
        ofi = features.orderflow_imbalance
        if ofi is not None and ofi < -max_adverse_orderflow:
            if self._trace_enabled():
                self._logger.info(
                    "[%s] spot_dip: reject — adverse orderflow %.3f", features.symbol, ofi
                )
            return None

        poc_dist_bps = abs(features.distance_to_poc / features.price * 10000) if features.price else 0

        signal = None
        trace = self._trace_enabled()

        # --- Mode 1: Price at or below VAL — classic dip buy ---
        if features.position_in_value == "below":
            if poc_dist_bps >= min_poc_distance_bps:
                signal = self._build_long(features, account, stop_loss_pct, take_profit_pct, risk_per_trade_pct, "below_val_dip")
            elif trace:
                self._logger.info("[%s] spot_dip: below_val but poc_dist=%.1f < %.1f", features.symbol, poc_dist_bps, min_poc_distance_bps)

        # --- Mode 2: Price inside value area — accumulation ---
        elif features.position_in_value == "inside":
            signal = self._build_long(features, account, stop_loss_pct, take_profit_pct, risk_per_trade_pct, "inside_value_area")

        elif trace:
            self._logger.info("[%s] spot_dip: position=%s (need below/inside)", features.symbol, features.position_in_value)

        # --- Mode 3: Price above value area — momentum buy ---
        if signal is None and features.position_in_value == "above":
            # Only buy above value if orderflow is positive (buyers in control)
            if ofi is not None and ofi > 0.1:
                signal = self._build_long(features, account, stop_loss_pct, take_profit_pct, risk_per_trade_pct, "above_value_momentum")
            elif trace:
                self._logger.info("[%s] spot_dip: above_value but ofi=%.3f (need >0.1)", features.symbol, ofi if ofi is not None else 0)

        if signal and self._trace_enabled():
            self._logger.info(
                "[%s] spot_dip: SIGNAL side=long reason=%s poc_dist=%.1f bps",
                features.symbol, signal.meta_reason, poc_dist_bps,
            )

        return signal

    def _build_long(
        self,
        features: Features,
        account: AccountState,
        stop_loss_pct: float,
        take_profit_pct: float,
        risk_per_trade_pct: float,
        reason: str,
    ) -> StrategySignal:
        entry = features.price
        sl = entry * (1.0 - stop_loss_pct)
        tp = entry * (1.0 + take_profit_pct)
        size = risk_per_trade_pct * account.equity / entry

        return StrategySignal(
            strategy_id=self.strategy_id,
            symbol=features.symbol,
            side="long",
            size=size,
            entry_price=entry,
            stop_loss=sl,
            take_profit=tp,
            meta_reason=reason,
            profile_id="spot_accumulation",
        )
