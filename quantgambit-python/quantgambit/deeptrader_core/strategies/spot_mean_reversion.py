"""Spot Mean Reversion — buys inside value area near POC in range-bound markets.

Entry: price inside value area + range/mean-revert regime + low volatility.
Tighter TP targeting POC reversion. Conservative sizing.
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


class SpotMeanReversion(Strategy):

    strategy_id = "spot_mean_reversion"

    def __init__(self):
        self._logger = logging.getLogger(__name__)

    def generate_signal(
        self,
        features: Features,
        account: AccountState,
        profile: Profile,
        params: Dict[str, Any],
    ) -> Optional[StrategySignal]:

        stop_loss_pct = params.get("stop_loss_pct", 0.01)  # 1% SL
        take_profit_pct = params.get("take_profit_pct", 0.025)  # 2.5% TP (2.5:1 R:R)
        risk_per_trade_pct = params.get("risk_per_trade_pct", 0.03)
        max_spread = params.get("max_spread", 0.003)
        min_poc_distance_bps = params.get("min_poc_distance_bps", 0.5)
        max_poc_distance_bps = params.get("max_poc_distance_bps", 120.0)
        max_trend_strength = params.get("max_trend_strength", 0.4)

        if features.spread > max_spread:
            return None
        # Allow inside or below value area (buy dips and mean reversion)
        if features.position_in_value not in ("inside", "below"):
            return None
        if features.distance_to_poc is None or features.price is None:
            return None

        # Sentiment gate
        sentiment_floor = params.get("sentiment_floor", -0.5)
        if get_sentiment(features.symbol) < sentiment_floor:
            return None

        # Model gate: don't buy when model predicts down
        pred = get_prediction(features.symbol)
        if pred.get("direction") == "down" and not pred.get("reject"):
            return None

        # Must be range-bound — reject strong trends
        if features.trend_strength > max_trend_strength:
            return None

        # Price should be near or below POC (buy dips and near-POC entries)
        poc_dist_bps = abs(features.distance_to_poc / features.price * 10000)
        if features.distance_to_poc > 0 and poc_dist_bps > max_poc_distance_bps * 0.25:
            return None  # too far above POC
        if poc_dist_bps > max_poc_distance_bps:
            return None

        # Orderbook imbalance: prefer bid-heavy (support)
        if features.bid_depth_usd and features.ask_depth_usd:
            if features.bid_depth_usd < features.ask_depth_usd * 0.7:
                return None  # sellers dominating depth

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
            meta_reason="mean_revert_to_poc",
            profile_id="spot_mean_reversion",
        )
