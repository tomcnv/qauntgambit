"""Spot Momentum Breakout — buys breakouts above value area high.

Entry: price above VAH + strong trend + positive orderflow.
Wider TP than dip accumulator since breakouts can run.
"""

import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, Optional

from ..types import AccountState, Features, Profile, StrategySignal
from .base import Strategy

try:
    from quantgambit.ai.sentiment_reader import get_sentiment
except ImportError:
    def get_sentiment(symbol: str) -> float: return 0.0

try:
    from quantgambit.ai.prediction_reader import get_prediction
except ImportError:
    def get_prediction(symbol: str) -> dict: return {}


class SpotMomentumBreakout(Strategy):

    strategy_id = "spot_momentum_breakout"

    def __init__(self):
        self._logger = logging.getLogger(__name__)

    def generate_signal(
        self,
        features: Features,
        account: AccountState,
        profile: Profile,
        params: Dict[str, Any],
    ) -> Optional[StrategySignal]:

        stop_loss_pct = params.get("stop_loss_pct", 0.025)
        take_profit_pct = params.get("take_profit_pct", 0.03)
        risk_per_trade_pct = params.get("risk_per_trade_pct", 0.04)
        max_spread = params.get("max_spread", 0.002)
        min_trend_strength = params.get("min_trend_strength", 0.4)
        min_orderflow = params.get("min_orderflow", 0.2)
        min_vah_distance_bps = params.get("min_vah_distance_bps", 5.0)

        if features.spread > max_spread:
            return None
        if features.position_in_value != "above":
            return None
        if features.distance_to_vah is None or features.price is None:
            return None

        # Sentiment gate
        sentiment_floor = params.get("sentiment_floor", -0.3)
        if get_sentiment(features.symbol) < sentiment_floor:
            return None

        # Model gate: require model agrees (up) for breakout
        pred = get_prediction(features.symbol)
        if pred.get("direction") == "down" and not pred.get("reject"):
            return None

        # Must be above VAH by some margin (confirmed breakout, not just a wick)
        vah_dist_bps = abs(features.distance_to_vah / features.price * 10000)
        if vah_dist_bps < min_vah_distance_bps:
            return None

        # Need trend confirmation OR strong positive rotation
        has_trend = features.trend_direction == "up" and features.trend_strength >= min_trend_strength
        has_rotation = features.rotation_factor is not None and features.rotation_factor > 1.0
        if not has_trend and not has_rotation:
            return None

        # Need positive orderflow (buyers in control)
        ofi = features.orderflow_imbalance
        if ofi is None or ofi < min_orderflow:
            return None

        # EMA confirmation: fast above slow (skip if not available)
        if features.ema_fast_15m and features.ema_slow_15m:
            if features.ema_fast_15m <= features.ema_slow_15m:
                if not has_rotation:  # rotation can override EMA
                    return None

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
            meta_reason="vah_breakout",
            profile_id="spot_momentum",
        )
